from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.models import Candidate, JobApplication, JobRequisition


class RecruitmentRepository:
    def __init__(self, db: Session):
        self.db = db

    def public_jobs(self) -> list[JobRequisition]:
        query = (
            select(JobRequisition)
            .options(joinedload(JobRequisition.department))
            .where(JobRequisition.status.in_(("approved", "sourcing", "interviewing")))
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
            )
        )
        return self.db.scalar(query)

    def find_candidate(self, email_norm: str | None, phone_norm: str | None) -> Candidate | None:
        matches = []
        if email_norm:
            matches.append(Candidate.email_norm == email_norm)
        if phone_norm:
            matches.append(Candidate.phone_norm == phone_norm)
        if not matches:
            return None
        return self.db.scalar(
            select(Candidate)
            .where(Candidate.deleted_at.is_(None), or_(*matches))
            .order_by(Candidate.id)
        )

    def existing_application(self, requisition_id: int, candidate_id: int) -> JobApplication | None:
        return self.db.scalar(
            select(JobApplication).where(
                JobApplication.requisition_id == requisition_id,
                JobApplication.candidate_id == candidate_id,
            )
        )
