from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import quote
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import (
    GLOBAL_RECRUITING_ROLES,
    enforce_candidate_scope,
    get_current_user,
    require_recruiting_user,
)
from app.models import (
    Candidate,
    CandidateSkill,
    JobApplication,
    JobRequisition,
    ResumeFile,
    User,
)
from app.schemas.hr import (
    ResumeConfirmRequest,
    ResumeConfirmResult,
    ResumeParsedUpdate,
    ResumeRead,
    ResumeSourceReview,
    ResumeUploadResult,
)
from app.services.applications import normalize_email, normalize_phone
from app.services.resume_parser import PARSER_VERSION, parse_resume
from app.services.security import client_ip, write_audit
from app.services.storage import (
    PreparedResumeUpload,
    get_storage_provider,
    prepare_resume_upload,
)
from app.services.talent_retention import candidate_retention_until

router = APIRouter(prefix="/resumes")
SourcePlatform = Literal["direct", "p104", "p1111", "generic"]


@contextmanager
def _stored_path(resume: ResumeFile) -> Iterator[Path]:
    if not resume.storage_key:
        raise HTTPException(status_code=422, detail="This resume has no stored file")
    try:
        with get_storage_provider().materialize(resume.storage_key) as path:
            yield path
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Stored resume file was not found") from exc


def _stored_resume_response(
    resume: ResumeFile,
    *,
    disposition: Literal["attachment", "inline"],
    media_type: str | None = None,
) -> Response:
    # Resume uploads are capped at 10 MiB. Read the object before creating the
    # response so a missing file returns a real 404 instead of failing after a
    # streaming 200 has started and leaving the browser waiting indefinitely.
    with _stored_path(resume) as path:
        content = path.read_bytes()

    filename = resume.original_filename or f"resume-{resume.id}"
    headers = {
        "Content-Disposition": (
            f"{disposition}; filename*=UTF-8''{quote(filename, safe='')}"
        ),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    }
    if disposition == "inline":
        headers["X-Frame-Options"] = "SAMEORIGIN"
    return Response(
        content=content,
        media_type=media_type or resume.mime or "application/octet-stream",
        headers=headers,
    )


def _apply_parse(resume: ResumeFile, path: Path, requested: str) -> None:
    parsed = parse_resume(path, requested)
    resume.source_platform = parsed.source_platform
    resume.parse_status = parsed.status
    resume.resume_text = parsed.raw_text
    resume.parsed_payload = parsed.payload
    resume.field_confidence = parsed.confidence
    resume.overall_confidence = parsed.overall_confidence
    resume.requested_source_platform = requested
    resume.source_confidence = parsed.source_confidence
    resume.source_evidence = parsed.source_evidence
    resume.source_review_required = parsed.source_review_required
    resume.parser_version = PARSER_VERSION
    resume.error_message = parsed.error_message


def _enforce_resume_scope(db: Session, user: User, resume: ResumeFile) -> None:
    """Enforce a target department first, falling back to legacy candidate scope."""

    if user.role in GLOBAL_RECRUITING_ROLES:
        return
    if user.role != "manager":
        raise HTTPException(status_code=403, detail="Outside resume scope")
    if resume.target_requisition_id is not None:
        if user.department_id is None:
            raise HTTPException(status_code=403, detail="Outside resume scope")
        target_department_id = db.scalar(
            select(JobRequisition.department_id).where(
                JobRequisition.id == resume.target_requisition_id
            )
        )
        if target_department_id != user.department_id:
            raise HTTPException(status_code=403, detail="Outside resume scope")
        return
    if resume.candidate_id is not None:
        enforce_candidate_scope(db, user, resume.candidate_id)
        return
    raise HTTPException(status_code=403, detail="Outside resume scope")


def _enforce_targeted_resume_scope(db: Session, user: User, resume: ResumeFile) -> None:
    """Downloads require an explicit requisition target for department managers."""

    if user.role in GLOBAL_RECRUITING_ROLES:
        return
    if (
        user.role != "manager"
        or user.department_id is None
        or resume.target_requisition_id is None
        or resume.parse_status != "confirmed"
    ):
        raise HTTPException(status_code=403, detail="Outside resume scope")
    department_id = db.scalar(
        select(JobRequisition.department_id).where(
            JobRequisition.id == resume.target_requisition_id
        )
    )
    if department_id != user.department_id:
        raise HTTPException(status_code=403, detail="Outside resume scope")


def _enforce_original_file_access(user: User, resume: ResumeFile) -> None:
    """Keep all ResumeFile binaries behind the HR/admin boundary.

    A system-generated profile can still contain direct identifiers, so its
    origin is not a safe basis for manager access. Managers use only approved
    de-identified document endpoints.
    """

    if user.role == "manager":
        raise HTTPException(
            status_code=403,
            detail="Resume files are available to HR and recruiting administrators only",
        )


def _enforce_original_detail_access(user: User, resume: ResumeFile) -> None:
    """Keep raw/parsed ResumeFile content behind the HR/admin boundary."""

    if user.role == "manager":
        raise HTTPException(
            status_code=403,
            detail="Resume details are available to HR and recruiting administrators only",
        )


def _resolve_target_requisition(
    db: Session,
    user: User,
    requisition_id: int | None,
) -> JobRequisition | None:
    if requisition_id is None:
        if user.role == "manager":
            raise HTTPException(
                status_code=422,
                detail="requisition_id is required for manager uploads",
            )
        return None
    requisition = db.get(JobRequisition, requisition_id)
    if requisition is None:
        raise HTTPException(status_code=404, detail="Requisition not found")
    if user.role == "manager":
        if user.department_id is None or requisition.department_id != user.department_id:
            raise HTTPException(status_code=403, detail="Outside department scope")
    return requisition


def _ensure_target_application(
    db: Session,
    resume: ResumeFile,
    candidate: Candidate,
    actor: User,
) -> JobApplication | None:
    """Create the department-workspace row, or safely reuse its unique pair."""

    if resume.target_requisition_id is None:
        return None
    application = db.scalar(
        select(JobApplication).where(
            JobApplication.requisition_id == resume.target_requisition_id,
            JobApplication.candidate_id == candidate.id,
        )
    )
    if application is not None:
        if application.resume_id is None:
            application.resume_id = resume.id
        return application
    uploader = db.get(User, resume.uploaded_by) if resume.uploaded_by is not None else None
    uploader_role = uploader.role if uploader is not None else None
    if uploader_role is None and resume.uploaded_by == actor.id:
        uploader_role = actor.role
    source = "manager_upload" if uploader_role == "manager" else "hr_upload"
    application = JobApplication(
        requisition_id=resume.target_requisition_id,
        candidate_id=candidate.id,
        resume_id=resume.id,
        status="submitted",
        source=source,
    )
    db.add(application)
    return application


@router.post(
    "/upload", response_model=list[ResumeUploadResult], status_code=status.HTTP_201_CREATED
)
async def upload_resumes(
    files: list[UploadFile] = File(...),
    source_platform: SourcePlatform = Form("generic"),
    candidate_id: int | None = Form(None),
    requisition_id: int | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> list[ResumeUploadResult]:
    if not files:
        raise HTTPException(status_code=422, detail="At least one resume is required")
    target_requisition = _resolve_target_requisition(db, user, requisition_id)
    candidate: Candidate | None = None
    if candidate_id is not None:
        candidate = db.get(Candidate, candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="Candidate not found")
        if candidate.deleted_at is not None:
            raise HTTPException(status_code=409, detail="Deleted candidate cannot receive a resume")
        if user.role == "manager":
            enforce_candidate_scope(db, user, candidate.id)
    prepared_uploads: list[PreparedResumeUpload] = []
    results: list[ResumeUploadResult] = []
    try:
        for upload in files:
            prepared = await prepare_resume_upload(upload)
            upload_data = prepared.upload_data
            existing = db.scalar(
                select(ResumeFile).where(ResumeFile.file_hash == upload_data.file_hash)
            )
            if existing:
                prepared.discard()
                _enforce_resume_scope(db, user, existing)
                if (
                    target_requisition is not None
                    and existing.target_requisition_id not in (None, target_requisition.id)
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="Resume file is already assigned to another requisition",
                    )
                if (
                    target_requisition is not None
                    and existing.target_requisition_id is None
                ):
                    # Only global recruiting users can reach an untargeted duplicate.
                    existing.target_requisition_id = target_requisition.id
                if candidate is not None:
                    if existing.candidate_id not in (None, candidate.id):
                        raise HTTPException(
                            status_code=409,
                            detail="Resume file is already linked to another candidate",
                        )
                    existing.candidate_id = candidate.id
                results.append(
                    ResumeUploadResult(
                        id=existing.id,
                        original_filename=upload_data.original_filename,
                        target_requisition_id=existing.target_requisition_id,
                        source_platform=existing.source_platform,
                        parse_status=existing.parse_status,
                        source_confidence=existing.source_confidence,
                        source_evidence=existing.source_evidence,
                        source_review_required=existing.source_review_required,
                        duplicate=True,
                    )
                )
                continue
            prepared_uploads.append(prepared)
            path = prepared.promote()
            resume = ResumeFile(
                candidate_id=candidate.id if candidate is not None else None,
                target_requisition_id=(
                    target_requisition.id if target_requisition is not None else None
                ),
                uploaded_by=user.id,
                storage_key=upload_data.storage_key,
                original_filename=upload_data.original_filename,
                file_hash=upload_data.file_hash,
                file_size=upload_data.file_size,
                mime=upload_data.mime,
                source_platform=source_platform,
                parse_status="pending",
            )
            db.add(resume)
            await run_in_threadpool(_apply_parse, resume, path, source_platform)
            db.flush()
            results.append(
                ResumeUploadResult(
                    id=resume.id,
                    original_filename=upload_data.original_filename,
                    target_requisition_id=resume.target_requisition_id,
                    source_platform=resume.source_platform,
                    parse_status=resume.parse_status,
                    source_confidence=resume.source_confidence,
                    source_evidence=resume.source_evidence,
                    source_review_required=resume.source_review_required,
                )
            )
        db.commit()
        for prepared in prepared_uploads:
            prepared.finish()
        return results
    except Exception:
        db.rollback()
        for prepared in prepared_uploads:
            prepared.discard()
        raise


@router.get("", response_model=list[ResumeRead])
def list_resumes(
    parse_status: str | None = None,
    source_platform: SourcePlatform | None = None,
    query: str | None = None,
    include_confirmed: bool = Query(True),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> list[ResumeFile]:
    if user.role == "manager":
        raise HTTPException(
            status_code=403,
            detail="Resume lists are available to HR and recruiting administrators only",
        )
    statement = select(ResumeFile).order_by(ResumeFile.uploaded_at.desc())
    if parse_status:
        statement = statement.where(ResumeFile.parse_status == parse_status)
    elif not include_confirmed:
        statement = statement.where(ResumeFile.parse_status != "confirmed")
    if source_platform:
        statement = statement.where(ResumeFile.source_platform == source_platform)
    if query:
        pattern = f"%{query.strip()}%"
        statement = statement.where(
            or_(ResumeFile.original_filename.ilike(pattern), ResumeFile.resume_text.ilike(pattern))
        )
    statement = statement.offset((page - 1) * page_size).limit(page_size)
    return list(db.scalars(statement).all())


@router.get("/{resume_id}/file", response_class=Response)
def download_resume_file(
    resume_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> Response:
    resume = db.get(ResumeFile, resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    _enforce_targeted_resume_scope(db, user, resume)
    _enforce_original_file_access(user, resume)
    if not resume.storage_key:
        raise HTTPException(status_code=404, detail="This resume has no downloadable file")
    response = _stored_resume_response(resume, disposition="attachment")
    write_audit(
        db,
        user,
        "resume.download",
        "resume",
        resume.id,
        user.department_id,
        details={
            "candidate_id": resume.candidate_id,
            "target_requisition_id": resume.target_requisition_id,
        },
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    return response


@router.get("/{resume_id}/preview", response_class=Response)
def preview_resume_file(
    resume_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> Response:
    resume = db.get(ResumeFile, resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    _enforce_targeted_resume_scope(db, user, resume)
    _enforce_original_file_access(user, resume)
    if not resume.storage_key:
        raise HTTPException(status_code=404, detail="This resume has no previewable file")

    filename = (resume.original_filename or "").lower()
    mime = (resume.mime or "").lower()
    if not (filename.endswith(".pdf") or mime == "application/pdf"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Browser preview is available for PDF resumes only",
        )
    response = _stored_resume_response(
        resume,
        disposition="inline",
        media_type="application/pdf",
    )

    write_audit(
        db,
        user,
        "resume.preview",
        "resume",
        resume.id,
        user.department_id,
        details={
            "candidate_id": resume.candidate_id,
            "target_requisition_id": resume.target_requisition_id,
            "format": "pdf",
        },
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    return response


@router.get("/{resume_id}", response_model=ResumeRead)
def get_resume(
    resume_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ResumeFile:
    resume = db.get(ResumeFile, resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    _enforce_resume_scope(db, user, resume)
    _enforce_original_detail_access(user, resume)
    return resume


@router.put("/{resume_id}/parsed", response_model=ResumeRead)
def update_parsed_resume(
    resume_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> ResumeFile:
    resume = db.get(ResumeFile, resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    _enforce_resume_scope(db, user, resume)
    _enforce_original_detail_access(user, resume)
    if resume.parse_status == "confirmed":
        raise HTTPException(status_code=409, detail="Confirmed resume cannot be edited")
    parsed = ResumeParsedUpdate.model_validate(payload.get("parsed_payload", payload))
    resume.parsed_payload = {
        **(resume.parsed_payload or {}),
        **parsed.model_dump(exclude_unset=True),
    }
    resume.field_confidence = {
        **(resume.field_confidence or {}),
        **{key: 1.0 for key in parsed.model_fields_set},
    }
    resume.overall_confidence = 1.0
    resume.parse_status = "parsed" if resume.parsed_payload.get("name") else "needs_review"
    resume.error_message = None
    db.commit()
    db.refresh(resume)
    return resume


@router.post("/{resume_id}/reparse", response_model=ResumeRead)
def reparse_resume(
    resume_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> ResumeFile:
    resume = db.get(ResumeFile, resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    _enforce_resume_scope(db, user, resume)
    _enforce_original_detail_access(user, resume)
    if resume.parse_status == "confirmed":
        raise HTTPException(status_code=409, detail="Confirmed resume cannot be reparsed")
    with _stored_path(resume) as path:
        _apply_parse(resume, path, resume.source_platform)
    db.commit()
    db.refresh(resume)
    return resume


@router.put("/{resume_id}/source", response_model=ResumeRead)
def review_resume_source(
    resume_id: int,
    payload: ResumeSourceReview,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> ResumeFile:
    """Human override for an ambiguous automatic source classification."""
    resume = db.get(ResumeFile, resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    _enforce_resume_scope(db, user, resume)
    _enforce_original_detail_access(user, resume)
    if resume.parse_status == "confirmed":
        raise HTTPException(status_code=409, detail="Confirmed resume source cannot be edited")
    previous = resume.source_platform
    resume.source_platform = payload.source_platform
    resume.source_confidence = 1.0
    resume.source_review_required = False
    resume.source_reviewed_by = user.id
    resume.source_reviewed_at = datetime.now(UTC)
    if resume.error_message and resume.error_message.startswith("Unknown "):
        resume.error_message = None
    parsed = resume.parsed_payload or {}
    if (
        resume.parse_status == "needs_review"
        and parsed.get("name")
        and (parsed.get("email") or parsed.get("phone"))
    ):
        resume.parse_status = "parsed"
    resume.source_evidence = list(resume.source_evidence or []) + [
        {
            "type": "human_override",
            "from": previous,
            "to": payload.source_platform,
            "reviewed_by": user.id,
        }
    ]
    db.commit()
    db.refresh(resume)
    return resume


@router.post("/{resume_id}/confirm", response_model=ResumeConfirmResult)
def confirm_resume(
    resume_id: int,
    request: ResumeConfirmRequest | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> ResumeConfirmResult:
    resume = db.get(ResumeFile, resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    _enforce_resume_scope(db, user, resume)
    _enforce_original_detail_access(user, resume)
    requested_candidate_id = request.candidate_id if request else None
    if resume.parse_status == "confirmed":
        if resume.candidate_id is None:
            raise HTTPException(status_code=409, detail="Confirmed resume has no candidate")
        if (
            requested_candidate_id is not None
            and requested_candidate_id != resume.candidate_id
        ):
            raise HTTPException(
                status_code=409,
                detail="Confirmed resume cannot be linked to another candidate",
            )
        confirmed_candidate = db.get(Candidate, resume.candidate_id)
        if confirmed_candidate is None or confirmed_candidate.deleted_at is not None:
            raise HTTPException(status_code=409, detail="Confirmed candidate is unavailable")
        _ensure_target_application(db, resume, confirmed_candidate, user)
        db.commit()
        return ResumeConfirmResult(
            resume_id=resume.id,
            candidate_id=confirmed_candidate.id,
            candidate_code=confirmed_candidate.code,
            created=False,
        )

    payload = resume.parsed_payload or {}
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name is required before confirmation")

    if (
        resume.candidate_id is not None
        and requested_candidate_id is not None
        and requested_candidate_id != resume.candidate_id
    ):
        raise HTTPException(
            status_code=409,
            detail="Linked resume cannot be reassigned during confirmation",
        )
    target_candidate_id = requested_candidate_id or resume.candidate_id
    candidate = db.get(Candidate, target_candidate_id) if target_candidate_id else None
    if target_candidate_id is not None and not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    if candidate and candidate.deleted_at is not None:
        raise HTTPException(status_code=409, detail="Deleted candidate cannot receive a resume")
    if candidate and requested_candidate_id is not None and user.role == "manager":
        enforce_candidate_scope(db, user, candidate.id)
    email_norm = normalize_email(payload.get("email"))
    phone_norm = normalize_phone(payload.get("phone"))
    if not candidate and (email_norm or phone_norm):
        clauses = []
        if email_norm:
            clauses.append(Candidate.email_norm == email_norm)
        if phone_norm:
            clauses.append(Candidate.phone_norm == phone_norm)
        candidate = db.scalar(
            select(Candidate)
            .where(Candidate.deleted_at.is_(None), or_(*clauses))
            .limit(1)
        )
        if candidate is not None and user.role == "manager":
            enforce_candidate_scope(db, user, candidate.id)
    created = candidate is None
    if candidate is None:
        now = datetime.now(UTC)
        candidate = Candidate(
            code=f"T-{now:%Y%m%d}-{uuid4().hex[:8].upper()}",
            name=name,
            source=resume.source_platform,
            status="new",
            retention_until=candidate_retention_until(db, now),
        )
        db.add(candidate)
        db.flush()

    candidate.name = name
    if created:
        candidate.email = payload.get("email")
        candidate.email_norm = email_norm
        candidate.phone = payload.get("phone")
        candidate.phone_norm = phone_norm
        candidate.city = payload.get("city")
        candidate.current_title = payload.get("current_title")
        candidate.total_years = payload.get("total_years")
        candidate.current_company = payload.get("current_company")
        candidate.highest_education = payload.get("highest_education")
        candidate.expected_title = payload.get("expected_title")
        candidate.expected_cities = payload.get("expected_cities") or None
        db.execute(delete(CandidateSkill).where(CandidateSkill.candidate_id == candidate.id))
        for skill in payload.get("skills") or []:
            clean = str(skill).strip()[:100]
            if clean:
                db.add(
                    CandidateSkill(
                        candidate_id=candidate.id, skill=clean, skill_norm=clean.casefold()
                    )
                )
    else:
        # Dedup-matched existing candidate: only fill fields the parsed payload actually
        # provides so a partial resume never wipes curated data, and merge skills instead
        # of deleting the curated set.
        if payload.get("email"):
            candidate.email = payload.get("email")
            candidate.email_norm = email_norm
        if payload.get("phone"):
            candidate.phone = payload.get("phone")
            candidate.phone_norm = phone_norm
        if payload.get("city"):
            candidate.city = payload.get("city")
        if payload.get("current_title"):
            candidate.current_title = payload.get("current_title")
        if payload.get("total_years") is not None:
            candidate.total_years = payload.get("total_years")
        if payload.get("current_company"):
            candidate.current_company = payload.get("current_company")
        if payload.get("highest_education"):
            candidate.highest_education = payload.get("highest_education")
        if payload.get("expected_title"):
            candidate.expected_title = payload.get("expected_title")
        if payload.get("expected_cities"):
            candidate.expected_cities = payload.get("expected_cities")
        existing_skill_norms = set(
            db.scalars(
                select(CandidateSkill.skill_norm).where(
                    CandidateSkill.candidate_id == candidate.id
                )
            ).all()
        )
        for skill in payload.get("skills") or []:
            clean = str(skill).strip()[:100]
            if clean and clean.casefold() not in existing_skill_norms:
                db.add(
                    CandidateSkill(
                        candidate_id=candidate.id, skill=clean, skill_norm=clean.casefold()
                    )
                )
                existing_skill_norms.add(clean.casefold())

    resume.candidate_id = candidate.id
    resume.parse_status = "confirmed"
    resume.confirmed_at = datetime.now(UTC)
    _ensure_target_application(db, resume, candidate, user)
    db.commit()
    return ResumeConfirmResult(
        resume_id=resume.id,
        candidate_id=candidate.id,
        candidate_code=candidate.code,
        created=created,
    )
