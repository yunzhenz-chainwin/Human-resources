import re
from dataclasses import dataclass
from datetime import UTC, date, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Candidate, JobApplication, ResumeFile
from app.repositories.recruitment import RecruitmentRepository
from app.schemas.public import PublicApplicationCreate, PublicApplicationResult


@dataclass
class ResumeUploadData:
    storage_key: str
    original_filename: str
    file_hash: str
    file_size: int
    mime: str


def normalize_email(email: str | None) -> str | None:
    return email.strip().lower() if email else None


def normalize_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("886"):
        digits = "0" + digits[3:]
    return digits


def submit_application(
    db: Session, payload: PublicApplicationCreate, upload: ResumeUploadData | None = None
) -> PublicApplicationResult:
    repo = RecruitmentRepository(db)
    if repo.public_job(payload.requisition_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="職缺不存在或未公開")

    email_norm = normalize_email(str(payload.email) if payload.email else None)
    phone_norm = normalize_phone(payload.phone)
    candidate = repo.find_candidate(email_norm, phone_norm)
    if candidate:
        existing = repo.existing_application(payload.requisition_id, candidate.id)
        if existing:
            return PublicApplicationResult(
                application_id=existing.id, status=existing.status, duplicate=True
            )
        candidate.email = candidate.email or (str(payload.email).strip() if payload.email else None)
        candidate.email_norm = candidate.email_norm or email_norm
        candidate.phone = candidate.phone or payload.phone
        candidate.phone_norm = candidate.phone_norm or phone_norm
        candidate.city = candidate.city or payload.city
        candidate.current_title = candidate.current_title or payload.current_title
        candidate.total_years = candidate.total_years or payload.total_years
        candidate.consent_status = "consented"
        candidate.consent_at = datetime.now(UTC)
    else:
        candidate = Candidate(
            code=f"T{datetime.now(UTC).year}-{datetime.now(UTC).strftime('%m%d%H%M%S%f')[-10:]}",
            name=payload.name,
            email=str(payload.email).strip() if payload.email else None,
            email_norm=email_norm,
            phone=payload.phone,
            phone_norm=phone_norm,
            city=payload.city,
            current_title=payload.current_title,
            total_years=payload.total_years,
            source="career_site",
            status="new",
            consent_status="consented",
            consent_at=datetime.now(UTC),
            retention_until=date(datetime.now(UTC).year + 2, datetime.now(UTC).month, 1),
        )
        db.add(candidate)
        db.flush()

    resume = None
    if upload:
        resume = db.scalar(select(ResumeFile).where(ResumeFile.file_hash == upload.file_hash))
        if resume and resume.candidate_id != candidate.id:
            raise HTTPException(status_code=409, detail="履歷檔案已屬於其他人才，請聯絡 HR")
        if not resume:
            resume = ResumeFile(
                candidate_id=candidate.id,
                source_platform="direct",
                parse_status="pending",
                storage_key=upload.storage_key,
                original_filename=upload.original_filename,
                file_hash=upload.file_hash,
                file_size=upload.file_size,
                mime=upload.mime,
            )
            db.add(resume)
            db.flush()
    elif payload.resume_url or payload.resume_text:
        resume = ResumeFile(
            candidate_id=candidate.id,
            source_platform="direct",
            parse_status="needs_review",
            resume_url=str(payload.resume_url) if payload.resume_url else None,
            resume_text=payload.resume_text,
        )
        db.add(resume)
        db.flush()
    application = JobApplication(
        requisition_id=payload.requisition_id,
        candidate_id=candidate.id,
        resume_id=resume.id if resume else None,
        cover_letter=payload.cover_letter,
        linkedin_url=str(payload.linkedin_url) if payload.linkedin_url else None,
        portfolio_url=str(payload.portfolio_url) if payload.portfolio_url else None,
    )
    db.add(application)
    db.commit()
    db.refresh(application)
    return PublicApplicationResult(
        application_id=application.id, status=application.status, duplicate=False
    )
