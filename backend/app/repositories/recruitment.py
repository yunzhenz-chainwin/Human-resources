from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import Candidate, JobApplication, JobRequisition


class RecruitmentRepository:
    def __init__(self, db: Session):
        self.db = db

    def public_jobs(self) -> list[JobRequisition]:
        query = (
            select(JobRequisition)
            .options(joinedload(JobRequisition.department))
            .where(
                JobRequisition.status.in_(("approved", "sourcing", "interviewing")),
                ~JobRequisition.req_no.startswith("DEMO-"),
            )
            .order_by(JobRequisition.published_at.desc(), JobRequisition.id.desc())
        )
        return list(self.db.scalars(query).all())

    def public_job(self, job_id: int) -> JobRequisition | None:
        query = (
            select(JobRequisition)
            .options(joinedload(JobRequisition.department))
            .where(
                JobRequisition.id == job_id,
                JobRequisition.status.in_(("approved", "sourcing", "interviewing")),
                ~JobRequisition.req_no.startswith("DEMO-"),
            )
        )
        return self.db.scalar(query)

    def find_candidate(self, email_norm: str | None, phone_norm: str | None) -> Candidate | None:
        # Prefer an email match; only fall back to phone when no email match exists
        # so a shared phone number cannot bind an applicant to the wrong person.
        if email_norm:
            candidate = self.db.scalar(
                select(Candidate)
                .where(Candidate.deleted_at.is_(None), Candidate.email_norm == email_norm)
                .order_by(Candidate.id)
            )
            if candidate is not None:
                return candidate
        if phone_norm:
            return self.db.scalar(
                select(Candidate)
                .where(Candidate.deleted_at.is_(None), Candidate.phone_norm == phone_norm)
                .order_by(Candidate.id)
            )
        return None

    def existing_application(self, requisition_id: int, candidate_id: int) -> JobApplication | None:
        return self.db.scalar(
            select(JobApplication).where(
                JobApplication.requisition_id == requisition_id,
                JobApplication.candidate_id == candidate_id,
            )
        )
