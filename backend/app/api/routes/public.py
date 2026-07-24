import re
import threading
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Candidate, JobRequisition, ResumeFile
from app.repositories.recruitment import RecruitmentRepository
from app.schemas.public import (
    PublicApplicationCreate,
    PublicApplicationResult,
    PublicJob,
    PublicTalentPoolResult,
    PublicTalentProfileCreate,
)
from app.services.applications import (
    normalize_email,
    normalize_phone,
    submit_application,
    sync_candidate_skills,
)
from app.services.resume_parser import PARSER_VERSION, parse_resume
from app.services.storage import prepare_resume_upload
from app.services.talent_retention import candidate_retention_until

router = APIRouter(prefix="/public")
SourcePlatform = Literal["direct", "p104", "p1111", "generic"]

# --- Anonymous upload throttle (per-process) ---
# Dependency-free, per-process sliding-window limiter for the public upload
# endpoints. Each scanned PDF can hold a worker for up to ~45s of OCR, so an
# unthrottled anonymous route is an easy resource-exhaustion vector. The parse
# itself now runs in a threadpool (see run_in_threadpool below), so this is
# defense-in-depth: a generous per-IP cap that bounds anonymous floods without
# tripping legitimate bursty use. State lives in-process: a multi-worker /
# multi-host deployment should additionally throttle at the reverse proxy.
_UPLOAD_RATE_LIMIT = 20  # max uploads per client IP per window
_UPLOAD_RATE_WINDOW = 60.0  # sliding window, seconds
_UPLOAD_RATE_MAX_CLIENTS = 4096  # hard cap on tracked IPs to bound memory
_upload_hits: dict[str, deque[float]] = {}
_upload_hits_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    """Best-effort client IP: first X-Forwarded-For hop, else the socket peer."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _enforce_upload_rate_limit(request: Request) -> None:
    """Throttle a client IP that exceeds the public upload rate (HTTP 429)."""
    ip = _client_ip(request)
    now = monotonic()
    cutoff = now - _UPLOAD_RATE_WINDOW
    with _upload_hits_lock:
        # Bound the table before inserting: drop clients whose window has fully
        # expired, then hard-cap so a spoofed-IP flood cannot grow it.
        if len(_upload_hits) > _UPLOAD_RATE_MAX_CLIENTS:
            stale = [k for k, v in _upload_hits.items() if not v or v[-1] <= cutoff]
            for key in stale:
                del _upload_hits[key]
            while len(_upload_hits) > _UPLOAD_RATE_MAX_CLIENTS:
                del _upload_hits[next(iter(_upload_hits))]
        hits = _upload_hits.get(ip)
        if hits is None:
            hits = _upload_hits[ip] = deque()
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= _UPLOAD_RATE_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many uploads, please retry shortly",
            )
        hits.append(now)


def to_public_job(job: JobRequisition) -> PublicJob:
    return PublicJob(
        id=job.id,
        req_no=job.req_no,
        title=job.title,
        department=job.department.name if job.department else None,
        location=job.work_city,
        employment_type=job.employment_type,
        summary=job.summary or job.jd[:240],
        jd=job.jd,
        skills=job.skills or [],
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        salary_type=job.salary_type,
        status=job.status,
        published_at=job.published_at,
    )


def _parse_into(resume: ResumeFile, path: Path, source_platform: str) -> None:
    parsed = parse_resume(path, source_platform)
    resume.source_platform = parsed.source_platform
    resume.parse_status = parsed.status
    resume.resume_text = parsed.raw_text
    resume.parsed_payload = parsed.payload
    resume.field_confidence = parsed.confidence
    resume.overall_confidence = parsed.overall_confidence
    resume.requested_source_platform = source_platform
    resume.source_confidence = parsed.source_confidence
    resume.source_evidence = parsed.source_evidence
    resume.source_review_required = parsed.source_review_required
    resume.parser_version = PARSER_VERSION
    resume.error_message = parsed.error_message


def _validate_public_phone(phone: str | None) -> None:
    """Reject anonymous phone input that normalizes to an unusable dedup key.

    Multipart submissions bypass the JSON schema, so guard the normalized phone
    here: it must not be empty (a false dedup key) nor exceed the
    ``Candidate.phone_norm`` column limit (``String(20)``).
    """
    if phone is None:
        return
    phone_norm = normalize_phone(phone)
    if not phone_norm or len(phone_norm) > 20:
        raise HTTPException(status_code=422, detail="Invalid phone number")


def _save_talent_profile(
    db: Session,
    *,
    name: str,
    email: str | None,
    phone: str | None,
    city: str | None,
    current_title: str | None,
    total_years: float | None,
    skills: list[str],
    commit: bool = True,
) -> tuple[Candidate, bool]:
    email_norm = normalize_email(email)
    phone_norm = normalize_phone(phone)
    candidate = RecruitmentRepository(db).find_candidate(email_norm, phone_norm)
    created = candidate is None
    now = datetime.now(UTC)
    if candidate is None:
        candidate = Candidate(
            code=f"T{now.year}-{now.strftime('%m%d%H%M%S%f')[-10:]}",
            name=name,
            email=email.strip() if email else None,
            email_norm=email_norm,
            phone=phone,
            phone_norm=phone_norm,
            city=city,
            current_title=current_title,
            total_years=total_years,
            source="career_site",
            status="new",
            consent_status="consented",
            consent_at=now,
            retention_until=candidate_retention_until(db, now),
        )
        db.add(candidate)
        db.flush()
    else:
        candidate.name = candidate.name or name
        candidate.email = candidate.email or (email.strip() if email else None)
        candidate.email_norm = candidate.email_norm or email_norm
        candidate.phone = candidate.phone or phone
        candidate.phone_norm = candidate.phone_norm or phone_norm
        candidate.city = candidate.city or city
        candidate.current_title = candidate.current_title or current_title
        candidate.total_years = (
            candidate.total_years if candidate.total_years is not None else total_years
        )
    sync_candidate_skills(db, candidate, skills)
    if commit:
        db.commit()
        db.refresh(candidate)
    else:
        db.flush()
    return candidate, created


@router.get("/jobs", response_model=list[PublicJob])
def list_jobs(db: Session = Depends(get_db)) -> list[PublicJob]:
    return [to_public_job(job) for job in RecruitmentRepository(db).public_jobs()]


@router.get("/jobs/{job_id}", response_model=PublicJob)
def get_job(job_id: int, db: Session = Depends(get_db)) -> PublicJob:
    job = RecruitmentRepository(db).public_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return to_public_job(job)


@router.post(
    "/applications",
    response_model=PublicApplicationResult | PublicTalentPoolResult,
    status_code=status.HTTP_201_CREATED,
)
async def create_application(
    request: Request,
    job_id: int | None = Form(None),
    name: str = Form(...),
    email: str | None = Form(None),
    phone: str | None = Form(None),
    city: str | None = Form(None),
    current_title: str | None = Form(None),
    total_years: float | None = Form(None),
    skills: str | None = Form(None),
    linkedin_url: str | None = Form(None),
    portfolio_url: str | None = Form(None),
    cover_letter: str | None = Form(None),
    source_platform: SourcePlatform = Form("direct"),
    consent: bool = Form(...),
    resume: UploadFile | None = File(None),
    db: Session = Depends(get_db),
) -> PublicApplicationResult | PublicTalentPoolResult:
    if job_id is None:
        return await join_talent_pool(
            request=request,
            name=name,
            email=email,
            phone=phone,
            city=city,
            current_title=current_title,
            total_years=total_years,
            skills=skills,
            self_intro=None,
            cover_letter=cover_letter,
            source_platform=source_platform,
            consent=consent,
            resume=resume,
            db=db,
        )
    _enforce_upload_rate_limit(request)
    try:
        payload = PublicApplicationCreate(
            requisition_id=job_id,
            name=name,
            email=email,
            phone=phone,
            city=city,
            current_title=current_title,
            total_years=total_years,
            skills=[
                item.strip()
                for item in re.split(r"[,，、;|]", skills or "")
                if item.strip()
            ],
            linkedin_url=linkedin_url,
            portfolio_url=portfolio_url,
            cover_letter=cover_letter,
            consent=consent,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    _validate_public_phone(payload.phone)

    if resume is None:
        return submit_application(db, payload)

    prepared = await prepare_resume_upload(resume)
    upload_data = prepared.upload_data
    try:
        stored_path = prepared.promote()
        result = submit_application(db, payload, upload_data)
        stored = db.scalar(
            select(ResumeFile).where(ResumeFile.storage_key == upload_data.storage_key)
        )
        if stored:
            await run_in_threadpool(_parse_into, stored, stored_path, "direct")
            # Public submissions must remain visible in the HR queue even when
            # extraction cannot run synchronously; the error is retained for retry.
            if stored.parse_status in {"failed", "needs_review"}:
                stored.parse_status = "pending"
            db.commit()
            prepared.finish()
        else:
            prepared.discard()
        return result
    except Exception:
        db.rollback()
        prepared.discard()
        raise


@router.post(
    "/talent-pool", response_model=PublicTalentPoolResult, status_code=status.HTTP_201_CREATED
)
async def join_talent_pool(
    request: Request,
    name: str = Form(..., min_length=1, max_length=100),
    email: str | None = Form(None),
    phone: str | None = Form(None),
    city: str | None = Form(None),
    current_title: str | None = Form(None),
    total_years: float | None = Form(None),
    skills: str | None = Form(None),
    self_intro: str | None = Form(None),
    cover_letter: str | None = Form(None),
    source_platform: SourcePlatform = Form("direct"),
    consent: bool = Form(...),
    resume: UploadFile | None = File(None),
    db: Session = Depends(get_db),
) -> PublicTalentPoolResult:
    _enforce_upload_rate_limit(request)
    email = (email or "").strip() or None
    phone = (phone or "").strip() or None
    if not consent:
        raise HTTPException(status_code=422, detail="Consent is required")
    if not email and not phone:
        raise HTTPException(status_code=422, detail="Email or phone is required")
    submitted_skills = [
        item.strip() for item in re.split(r"[,，、;|]", skills or "") if item.strip()
    ]
    try:
        profile = PublicTalentProfileCreate(
            name=name,
            email=email,
            phone=phone,
            city=city,
            current_title=current_title,
            total_years=total_years,
            skills=submitted_skills,
            consent=consent,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    _validate_public_phone(profile.phone)
    if resume is None:
        candidate, created = _save_talent_profile(
            db,
            name=name,
            email=email,
            phone=phone,
            city=city,
            current_title=current_title,
            total_years=total_years,
            skills=submitted_skills,
        )
        return PublicTalentPoolResult(
            candidate_id=candidate.id,
            status="created" if created else "updated",
            duplicate=not created,
        )

    prepared = await prepare_resume_upload(resume)
    upload_data = prepared.upload_data
    try:
        candidate, created = _save_talent_profile(
            db,
            name=name,
            email=email,
            phone=phone,
            city=city,
            current_title=current_title,
            total_years=total_years,
            skills=submitted_skills,
            commit=False,
        )
        existing = db.scalar(
            select(ResumeFile).where(ResumeFile.file_hash == upload_data.file_hash)
        )
        if existing:
            if existing.candidate_id not in (None, candidate.id):
                # The file hash is already stored under a different candidate.
                # Do not reveal content-existence/ownership to anonymous
                # submitters: persist the profile, drop the duplicate upload,
                # and return the same generic result as a no-resume submission.
                db.commit()
                prepared.discard()
                return PublicTalentPoolResult(
                    candidate_id=candidate.id,
                    status="created" if created else "updated",
                    duplicate=not created,
                )
            existing.candidate_id = candidate.id
            db.commit()
            prepared.discard()
            return PublicTalentPoolResult(
                resume_id=existing.id,
                candidate_id=candidate.id,
                status=existing.parse_status,
                duplicate=True,
            )
        path = prepared.promote()
        record = ResumeFile(
            candidate_id=candidate.id,
            storage_key=upload_data.storage_key,
            original_filename=upload_data.original_filename,
            file_hash=upload_data.file_hash,
            file_size=upload_data.file_size,
            mime=upload_data.mime,
            source_platform=source_platform,
            parse_status="pending",
        )
        db.add(record)
        await run_in_threadpool(_parse_into, record, path, source_platform)
        parsed = dict(record.parsed_payload or {})
        submitted = {
            "name": name,
            "email": email,
            "phone": phone,
            "city": city,
            "current_title": current_title,
            "total_years": total_years,
            "skills": submitted_skills,
            "self_intro": self_intro or cover_letter,
        }
        for key, value in submitted.items():
            if value not in (None, "", []):
                parsed[key] = value
        record.parsed_payload = parsed
        confidence = dict(record.field_confidence or {})
        confidence.update(
            {key: 1.0 for key, value in submitted.items() if value not in (None, "", [])}
        )
        record.field_confidence = confidence
        record.overall_confidence = min(1.0, sum(confidence.values()) / max(len(confidence), 1))
        if record.parse_status != "failed":
            record.parse_status = "parsed"
        db.commit()
        prepared.finish()
        return PublicTalentPoolResult(
            resume_id=record.id,
            candidate_id=candidate.id,
            status=record.parse_status,
            duplicate=not created,
        )
    except Exception:
        db.rollback()
        prepared.discard()
        raise


@router.post(
    "/talent-pool/json",
    response_model=PublicTalentPoolResult,
    status_code=status.HTTP_201_CREATED,
)
def join_talent_pool_json(
    payload: PublicTalentProfileCreate,
    db: Session = Depends(get_db),
) -> PublicTalentPoolResult:
    candidate, created = _save_talent_profile(
        db,
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        city=payload.city,
        current_title=payload.current_title,
        total_years=payload.total_years,
        skills=payload.skills,
    )
    return PublicTalentPoolResult(
        candidate_id=candidate.id,
        status="created" if created else "updated",
        duplicate=not created,
    )


@router.post(
    "/applications/json",
    response_model=PublicApplicationResult,
    status_code=status.HTTP_201_CREATED,
)
def create_application_json(
    payload: PublicApplicationCreate, db: Session = Depends(get_db)
) -> PublicApplicationResult:
    try:
        return submit_application(db, payload)
    except Exception:
        db.rollback()
        raise
