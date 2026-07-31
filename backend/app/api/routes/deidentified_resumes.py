from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import (
    GLOBAL_RECRUITING_ROLES,
    enforce_candidate_scope,
    require_recruiting_manager,
    require_recruiting_user,
)
from app.models.candidate import Candidate
from app.models.deidentified_resume import DeidentifiedResumeDocument
from app.models.organization import User
from app.models.recruitment import JobApplication, JobRequisition, ResumeFile
from app.schemas.deidentified_resume import DeidentifiedResumeRead
from app.services.deidentification import (
    DeidentificationError,
    SourceDocumentError,
    SourceIntegrityError,
    approve_deidentified_document,
    create_manual_deidentified_document,
    read_verified_deidentified_file,
    reject_deidentified_document,
)
from app.services.security import client_ip, write_audit
from app.services.storage import StorageProvider, get_storage_provider

router = APIRouter(tags=["deidentified-resumes"])


def _set_no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"


def _source_resume(db: Session, resume_id: int) -> ResumeFile:
    resume = db.get(ResumeFile, resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    return resume


def _manager_is_actual_applicant(
    db: Session,
    user: User,
    resume: ResumeFile,
) -> bool:
    if user.role != "manager" or user.department_id is None or resume.candidate_id is None:
        return False
    application_id = db.scalar(
        select(JobApplication.id)
        .join(JobRequisition, JobRequisition.id == JobApplication.requisition_id)
        .where(
            JobApplication.candidate_id == resume.candidate_id,
            JobRequisition.department_id == user.department_id,
        )
        .limit(1)
    )
    return application_id is not None


def _enforce_read_scope(db: Session, user: User, resume: ResumeFile) -> None:
    if user.role in GLOBAL_RECRUITING_ROLES:
        return
    if not _manager_is_actual_applicant(db, user, resume):
        raise HTTPException(status_code=403, detail="Outside candidate scope")


def _document_for_read(
    db: Session,
    user: User,
    document_id: int,
) -> tuple[DeidentifiedResumeDocument, ResumeFile]:
    document = db.get(DeidentifiedResumeDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="De-identified resume not found")
    resume = _source_resume(db, document.source_resume_id)
    _enforce_read_scope(db, user, resume)
    if user.role == "manager" and document.validation_status != "analysis_ready":
        raise HTTPException(status_code=403, detail="De-identified resume is not approved")
    return document, resume


_MIME_EXTENSIONS = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}


def _document_response(
    document: DeidentifiedResumeDocument,
    *,
    disposition: str,
    storage: StorageProvider,
) -> Response:
    try:
        content = read_verified_deidentified_file(document, storage)
    except SourceDocumentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SourceIntegrityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    media_type = document.mime or "application/pdf"
    extension = _MIME_EXTENSIONS.get(media_type, ".pdf")
    filename = f"deidentified-resume-{document.anonymous_ref}-v{document.version}{extension}"
    headers = {
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(filename, safe='')}",
        "Cache-Control": "private, no-store",
        "Pragma": "no-cache",
        "Expires": "0",
        "X-Content-Type-Options": "nosniff",
    }
    if disposition == "inline":
        headers["X-Frame-Options"] = "SAMEORIGIN"
    return Response(content=content, media_type=media_type, headers=headers)


def _audit_request(
    db: Session,
    user: User,
    request: Request,
    action: str,
    document: DeidentifiedResumeDocument,
) -> None:
    write_audit(
        db,
        user,
        action,
        "deidentified_resume",
        document.id,
        user.department_id,
        details={
            "anonymous_ref": document.anonymous_ref,
            "version": document.version,
            "status": document.validation_status,
        },
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


@router.post(
    "/resumes/{resume_id}/deidentifications",
    response_model=DeidentifiedResumeRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_deidentified_resume(
    resume_id: int,
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_manager),
) -> DeidentifiedResumeDocument:
    """Register an HR-supplied, already de-identified file as a new version.

    The system no longer generates a de-identified derivative automatically; a
    recruiting manager uploads a file they have already redacted.  It is stored
    as ``review_required`` and must still be approved before it is analysable.
    """

    resume = _source_resume(db, resume_id)
    storage = get_storage_provider()
    stored_key: str | None = None
    try:
        document = await create_manual_deidentified_document(
            db,
            resume,
            user,
            file,
            storage=storage,
        )
        stored_key = document.storage_key
        _audit_request(db, user, request, "deidentified_resume.create", document)
        db.commit()
        db.refresh(document)
        _set_no_store(response)
        return document
    except HTTPException:
        db.rollback()
        if stored_key:
            try:
                storage.delete(stored_key)
            except Exception:
                pass
        raise
    except SourceDocumentError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SourceIntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        if stored_key:
            try:
                storage.delete(stored_key)
            except Exception:
                pass
        raise HTTPException(
            status_code=409,
            detail="A de-identification version was created concurrently; try again",
        ) from exc
    except Exception:
        db.rollback()
        if stored_key:
            try:
                storage.delete(stored_key)
            except Exception:
                pass
        raise


@router.get(
    "/resumes/{resume_id}/deidentifications",
    response_model=list[DeidentifiedResumeRead],
)
def list_resume_deidentifications(
    resume_id: int,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> list[DeidentifiedResumeDocument]:
    resume = _source_resume(db, resume_id)
    _enforce_read_scope(db, user, resume)
    statement = (
        select(DeidentifiedResumeDocument)
        .where(DeidentifiedResumeDocument.source_resume_id == resume.id)
        .order_by(DeidentifiedResumeDocument.version.desc())
    )
    if user.role == "manager":
        statement = statement.where(
            DeidentifiedResumeDocument.validation_status == "analysis_ready"
        )
    _set_no_store(response)
    return list(db.scalars(statement).all())


@router.get(
    "/candidates/{candidate_id}/deidentified-resumes",
    response_model=list[DeidentifiedResumeRead],
)
def list_candidate_deidentified_resumes(
    candidate_id: int,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> list[DeidentifiedResumeDocument]:
    candidate = db.get(Candidate, candidate_id)
    if candidate is None or candidate.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    enforce_candidate_scope(db, user, candidate_id)
    statement = (
        select(DeidentifiedResumeDocument)
        .join(ResumeFile, ResumeFile.id == DeidentifiedResumeDocument.source_resume_id)
        .where(ResumeFile.candidate_id == candidate_id)
        .order_by(
            DeidentifiedResumeDocument.created_at.desc(),
            DeidentifiedResumeDocument.version.desc(),
        )
    )
    if user.role == "manager":
        statement = statement.where(
            DeidentifiedResumeDocument.validation_status == "analysis_ready"
        )
    _set_no_store(response)
    return list(db.scalars(statement).all())


@router.get("/deidentified-resumes/{document_id}/preview", response_class=Response)
def preview_deidentified_resume(
    document_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> Response:
    document, _resume = _document_for_read(db, user, document_id)
    response = _document_response(
        document,
        disposition="inline",
        storage=get_storage_provider(),
    )
    _audit_request(db, user, request, "deidentified_resume.preview", document)
    db.commit()
    return response


@router.get("/deidentified-resumes/{document_id}/file", response_class=Response)
def download_deidentified_resume(
    document_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> Response:
    document, _resume = _document_for_read(db, user, document_id)
    response = _document_response(
        document,
        disposition="attachment",
        storage=get_storage_provider(),
    )
    _audit_request(db, user, request, "deidentified_resume.download", document)
    db.commit()
    return response


def _review_document(db: Session, document_id: int) -> DeidentifiedResumeDocument:
    document = db.get(DeidentifiedResumeDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="De-identified resume not found")
    return document


@router.post(
    "/deidentified-resumes/{document_id}/approve",
    response_model=DeidentifiedResumeRead,
)
def approve_deidentified_resume(
    document_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_manager),
) -> DeidentifiedResumeDocument:
    document = _review_document(db, document_id)
    try:
        read_verified_deidentified_file(document, get_storage_provider())
        approve_deidentified_document(db, document, user)
    except DeidentificationError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit_request(db, user, request, "deidentified_resume.approve", document)
    db.commit()
    db.refresh(document)
    _set_no_store(response)
    return document


@router.post(
    "/deidentified-resumes/{document_id}/reject",
    response_model=DeidentifiedResumeRead,
)
def reject_deidentified_resume(
    document_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_manager),
) -> DeidentifiedResumeDocument:
    document = _review_document(db, document_id)
    try:
        reject_deidentified_document(db, document, user)
    except DeidentificationError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit_request(db, user, request, "deidentified_resume.reject", document)
    db.commit()
    db.refresh(document)
    _set_no_store(response)
    return document
