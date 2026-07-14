from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import (
    candidate_scope_clause,
    enforce_candidate_scope,
    get_current_user,
    require_recruiting_manager,
)
from app.models import Candidate, CandidateSkill, ResumeFile, User
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
from app.services.storage import (
    PreparedResumeUpload,
    get_storage_provider,
    prepare_resume_upload,
)

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


@router.post(
    "/upload", response_model=list[ResumeUploadResult], status_code=status.HTTP_201_CREATED
)
async def upload_resumes(
    files: list[UploadFile] = File(...),
    source_platform: SourcePlatform = Form("generic"),
    db: Session = Depends(get_db),
    _user: User = Depends(require_recruiting_manager),
) -> list[ResumeUploadResult]:
    if not files:
        raise HTTPException(status_code=422, detail="At least one resume is required")
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
                results.append(
                    ResumeUploadResult(
                        id=existing.id,
                        original_filename=upload_data.original_filename,
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
                storage_key=upload_data.storage_key,
                original_filename=upload_data.original_filename,
                file_hash=upload_data.file_hash,
                file_size=upload_data.file_size,
                mime=upload_data.mime,
                source_platform=source_platform,
                parse_status="pending",
            )
            db.add(resume)
            _apply_parse(resume, path, source_platform)
            db.flush()
            results.append(
                ResumeUploadResult(
                    id=resume.id,
                    original_filename=upload_data.original_filename,
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
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ResumeFile]:
    statement = select(ResumeFile).order_by(ResumeFile.uploaded_at.desc())
    if user.role == "manager":
        statement = statement.where(
            ResumeFile.candidate_id.in_(
                select(Candidate.id).where(candidate_scope_clause(user))
            )
        )
    if parse_status:
        statement = statement.where(ResumeFile.parse_status == parse_status)
    if source_platform:
        statement = statement.where(ResumeFile.source_platform == source_platform)
    if query:
        pattern = f"%{query.strip()}%"
        statement = statement.where(
            or_(ResumeFile.original_filename.ilike(pattern), ResumeFile.resume_text.ilike(pattern))
        )
    statement = statement.offset((page - 1) * page_size).limit(page_size)
    return list(db.scalars(statement).all())


@router.get("/{resume_id}", response_model=ResumeRead)
def get_resume(
    resume_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ResumeFile:
    resume = db.get(ResumeFile, resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    if resume.candidate_id is None and user.role == "manager":
        raise HTTPException(status_code=403, detail="Outside candidate scope")
    if resume.candidate_id is not None:
        enforce_candidate_scope(db, user, resume.candidate_id)
    return resume


@router.put("/{resume_id}/parsed", response_model=ResumeRead)
def update_parsed_resume(
    resume_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    _user: User = Depends(require_recruiting_manager),
) -> ResumeFile:
    resume = db.get(ResumeFile, resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    if resume.parse_status == "confirmed":
        raise HTTPException(status_code=409, detail="Confirmed resume cannot be edited")
    parsed = ResumeParsedUpdate.model_validate(payload.get("parsed_payload", payload))
    resume.parsed_payload = parsed.model_dump()
    resume.field_confidence = {key: 1.0 for key in parsed.model_fields_set}
    resume.overall_confidence = 1.0
    resume.parse_status = "parsed" if parsed.name else "needs_review"
    resume.error_message = None
    db.commit()
    db.refresh(resume)
    return resume


@router.post("/{resume_id}/reparse", response_model=ResumeRead)
def reparse_resume(
    resume_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_recruiting_manager),
) -> ResumeFile:
    resume = db.get(ResumeFile, resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
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
    user: User = Depends(require_recruiting_manager),
) -> ResumeFile:
    """HR/administrator human override for ambiguous automatic classification."""
    resume = db.get(ResumeFile, resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
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
    _user: User = Depends(require_recruiting_manager),
) -> ResumeConfirmResult:
    resume = db.get(ResumeFile, resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    payload = resume.parsed_payload or {}
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name is required before confirmation")

    candidate = (
        db.get(Candidate, request.candidate_id) if request and request.candidate_id else None
    )
    if request and request.candidate_id and not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    if candidate and candidate.deleted_at is not None:
        raise HTTPException(status_code=409, detail="Deleted candidate cannot receive a resume")
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
    created = candidate is None
    if candidate is None:
        candidate = Candidate(
            code=f"T-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:8].upper()}",
            name=name,
            source=resume.source_platform,
            status="new",
        )
        db.add(candidate)
        db.flush()

    candidate.name = name
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
                CandidateSkill(candidate_id=candidate.id, skill=clean, skill_norm=clean.casefold())
            )

    resume.candidate_id = candidate.id
    resume.parse_status = "confirmed"
    resume.confirmed_at = datetime.now(UTC)
    db.commit()
    return ResumeConfirmResult(
        resume_id=resume.id,
        candidate_id=candidate.id,
        candidate_code=candidate.code,
        created=created,
    )
