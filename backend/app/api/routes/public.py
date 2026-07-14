import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
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

router = APIRouter(prefix="/public")
SourcePlatform = Literal["direct", "p104", "p1111", "generic"]


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
    resume.parser_version = PARSER_VERSION
    resume.error_message = parsed.error_message


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
            retention_until=date(now.year + 2, now.month, 1),
        )
        db.add(candidate)
        db.flush()
    else:
        candidate.name = name or candidate.name
        candidate.email = candidate.email or (email.strip() if email else None)
        candidate.email_norm = candidate.email_norm or email_norm
        candidate.phone = candidate.phone or phone
        candidate.phone_norm = candidate.phone_norm or phone_norm
        candidate.city = city or candidate.city
        candidate.current_title = current_title or candidate.current_title
        candidate.total_years = (
            total_years if total_years is not None else candidate.total_years
        )
        candidate.consent_status = "consented"
        candidate.consent_at = now
    sync_candidate_skills(db, candidate, skills)
    db.commit()
    db.refresh(candidate)
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
            _parse_into(stored, stored_path, "direct")
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
    if not consent:
        raise HTTPException(status_code=422, detail="Consent is required")
    if not email and not phone:
        raise HTTPException(status_code=422, detail="Email or phone is required")
    submitted_skills = [
        item.strip() for item in re.split(r"[,，、;|]", skills or "") if item.strip()
    ]
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
        existing = db.scalar(
            select(ResumeFile).where(ResumeFile.file_hash == upload_data.file_hash)
        )
        if existing:
            prepared.discard()
            return PublicTalentPoolResult(
                resume_id=existing.id,
                candidate_id=existing.candidate_id,
                status=existing.parse_status,
                duplicate=True,
            )
        path = prepared.promote()
        record = ResumeFile(
            storage_key=upload_data.storage_key,
            original_filename=upload_data.original_filename,
            file_hash=upload_data.file_hash,
            file_size=upload_data.file_size,
            mime=upload_data.mime,
            source_platform=source_platform,
            parse_status="pending",
        )
        db.add(record)
        _parse_into(record, path, source_platform)
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
            resume_id=record.id, status=record.parse_status, duplicate=False
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
