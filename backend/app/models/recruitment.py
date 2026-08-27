from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    or_,
    select,
    true,
)
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import BIGINT_PK, Base, TimestampMixin, UTCDateTime
from app.models.interview import InterviewRecord


class JobRequisition(TimestampMixin, Base):
    __tablename__ = "job_requisitions"
    __table_args__ = (
        CheckConstraint("headcount > 0", name="positive_headcount"),
        CheckConstraint("salary_min IS NULL OR salary_min >= 0", name="salary_min_nonnegative"),
        CheckConstraint("salary_max IS NULL OR salary_max >= salary_min", name="salary_range"),
        CheckConstraint("min_years IS NULL OR min_years >= 0", name="min_years_nonnegative"),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    req_no: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"), index=True
    )
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    headcount: Mapped[int] = mapped_column(default=1, server_default="1", nullable=False)
    employment_type: Mapped[str] = mapped_column(String(20), nullable=False)
    work_city: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    work_address: Mapped[str | None] = mapped_column(String(255))
    salary_min: Mapped[int | None]
    salary_max: Mapped[int | None]
    salary_type: Mapped[str | None] = mapped_column(String(10))
    min_years: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    education_req: Mapped[str | None] = mapped_column(String(20))
    language_req: Mapped[str | None] = mapped_column(String(100))
    jd: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(String(500))
    skills: Mapped[list[str] | None] = mapped_column(JSON)
    urgency: Mapped[str] = mapped_column(String(10), default="normal", server_default="normal")
    needed_by: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        String(20), default="draft", server_default="draft", index=True
    )
    return_reason: Mapped[str | None] = mapped_column(String(500))
    match_weights: Mapped[dict | None] = mapped_column(JSON)
    # How this requisition weighs the five candidate scores into the composite:
    # resume / hr_questions / hr_overall / manager_questions / manager_overall.
    # NULL means "use the defaults"; a partial dict overrides only the keys it
    # names. Normalised on read by services.interview_scoring.resolve_composite_weights,
    # exactly like match_weights above. Only HR may change it (see the requisitions
    # route), and a reweighting re-derives every composite stored on the requisition
    # so the whole list stays ranked on one scale; the audit entry for the change
    # records what each composite was before, which is where the old snapshot lives.
    composite_score_weights: Mapped[dict | None] = mapped_column(JSON)
    # Blind review is the default: each interviewer's evaluation stays hidden from
    # the other side until both stages are submitted. HR may switch it off for a
    # single requisition, but only before scoring starts (see blind_review_locked).
    # true() compiles to native 1 on SQLite; the quoted "true" spelling is the one
    # e7b2c91d5f40 had to clean up, because any non-empty string reads back as True.
    blind_review_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    filled_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    department = relationship("Department")
    applications: Mapped[list["JobApplication"]] = relationship(cascade="all, delete-orphan")

    @property
    def department_name(self) -> str | None:
        return self.department.name if self.department else None

    @property
    def composite_score_weights_resolved(self) -> dict[str, float]:
        """The composite weights actually applied, rescaled to sum 1."""

        # Imported lazily: services import models, so a module-level import here
        # would close the cycle.
        from app.services.interview_scoring import resolve_composite_weights

        return resolve_composite_weights(self.composite_score_weights)


class ResumeFile(Base):
    __tablename__ = "resume_files"
    __table_args__ = (
        CheckConstraint("file_size IS NULL OR file_size >= 0", name="file_size_nonnegative"),
        CheckConstraint(
            "source_platform IN ('direct','p104','p1111','generic')",
            name="valid_source_platform",
        ),
        CheckConstraint(
            "parse_status IN ('pending','parsed','needs_review','failed','confirmed')",
            name="valid_parse_status",
        ),
        CheckConstraint(
            "overall_confidence IS NULL OR (overall_confidence >= 0 AND overall_confidence <= 1)",
            name="valid_overall_confidence",
        ),
        CheckConstraint(
            "source_confidence IS NULL OR (source_confidence >= 0 AND source_confidence <= 1)",
            name="valid_source_confidence",
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL"), index=True
    )
    target_requisition_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_requisitions.id", ondelete="SET NULL"), index=True
    )
    uploaded_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    storage_key: Mapped[str | None] = mapped_column(String(500))
    original_filename: Mapped[str | None] = mapped_column(String(255))
    file_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    mime: Mapped[str | None] = mapped_column(String(100))
    source_platform: Mapped[str] = mapped_column(
        String(20), default="direct", server_default="direct"
    )
    requested_source_platform: Mapped[str | None] = mapped_column(String(20))
    source_confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    source_evidence: Mapped[list[dict] | None] = mapped_column(JSON)
    source_review_required: Mapped[bool] = mapped_column(
        default=True, server_default="true", nullable=False
    )
    source_reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    source_reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    platform_code: Mapped[str | None] = mapped_column(String(50))
    parse_status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", index=True
    )
    parsed_payload: Mapped[dict | None] = mapped_column(JSON)
    field_confidence: Mapped[dict | None] = mapped_column(JSON)
    overall_confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    parser_version: Mapped[str | None] = mapped_column(String(20))
    error_message: Mapped[str | None] = mapped_column(Text)
    resume_url: Mapped[str | None] = mapped_column(String(1000))
    resume_text: Mapped[str | None] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now()
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    @property
    def document_origin(self) -> str:
        payload = self.parsed_payload or {}
        if payload.get("_document_origin") == "system_generated_profile":
            return "system_generated"
        return "applicant_upload"


class JobApplication(TimestampMixin, Base):
    __tablename__ = "job_applications"
    __table_args__ = (
        UniqueConstraint(
            "requisition_id", "candidate_id", name="uq_application_requisition_candidate"
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    requisition_id: Mapped[int] = mapped_column(
        ForeignKey("job_requisitions.id", ondelete="RESTRICT"), index=True
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="RESTRICT"), index=True
    )
    resume_id: Mapped[int | None] = mapped_column(
        ForeignKey("resume_files.id", ondelete="SET NULL")
    )
    cover_letter: Mapped[str | None] = mapped_column(Text)
    linkedin_url: Mapped[str | None] = mapped_column(String(1000))
    portfolio_url: Mapped[str | None] = mapped_column(String(1000))
    # Allowed values: submitted, screening, interview_ready, interview, offered,
    # hired, rejected, withdrawn. "interview_ready" is set explicitly by HR
    # ("確定面試") before any interview data exists, so the process can be gated on
    # readiness; it upgrades to "interview" once a stage carries real data. No
    # database CHECK governs this column, so the enumeration stays advisory.
    status: Mapped[str] = mapped_column(
        String(20), default="submitted", server_default="submitted", index=True
    )
    source: Mapped[str] = mapped_column(
        String(20), default="career_site", server_default="career_site"
    )
    interview_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    interview_result: Mapped[str | None] = mapped_column(String(30))
    interview_notes: Mapped[str | None] = mapped_column(Text)
    interview_updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    hr_interview_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    hr_interview_result: Mapped[str | None] = mapped_column(String(30))
    hr_interview_notes: Mapped[str | None] = mapped_column(Text)
    hr_interview_updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    hr_interview_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    manager_interview_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    manager_interview_result: Mapped[str | None] = mapped_column(String(30))
    manager_interview_notes: Mapped[str | None] = mapped_column(Text)
    manager_interview_updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    manager_interview_updated_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime()
    )
    # Sixth score: the weighted combination of the resume match, both stages'
    # per-question scores and both interviewers' own totals. Kept here because it
    # is per candidate-per-requisition and interview records already key off
    # application_id. Follows the MatchResult.total_score + score_breakdown
    # precedent: a numeric column to rank on, and a JSON breakdown recording each
    # component's value, the weight applied to it, and which components were
    # missing. NULL until both interview stages are submitted; the breakdown's
    # "status" separates "never computed" (breakdown NULL) from "computed and
    # still null". Never influences ``status`` -- evaluation must not drive
    # application state.
    composite_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    composite_score_breakdown: Mapped[dict | None] = mapped_column(JSON)


# Expressed against interview_records, which never imports this module, so the
# InterviewRecord import above stays acyclic.
#
# True once any interview for this requisition has ever been submitted. Mapped as a
# correlated subquery so every read of a requisition carries the lock state, including
# the nested requisition inside application payloads, without extra plumbing.
#
# "Ever submitted" deliberately includes records that were completed and then
# reopened: submitted_at is stamped on the first completion and never cleared. If a
# reopen unlocked the flag, an interviewer could reopen, switch blind review off and
# read the other side's evaluation, which is exactly what the lock prevents. The
# status check keeps rows whose submitted_at predates that column covered as well.
#
# Declared after JobApplication so both mappers exist when the join is built.
JobRequisition.blind_review_locked = column_property(
    select(InterviewRecord.id)
    .join(JobApplication, JobApplication.id == InterviewRecord.application_id)
    .where(
        JobApplication.requisition_id == JobRequisition.id,
        or_(
            InterviewRecord.status == "completed",
            InterviewRecord.submitted_at.is_not(None),
        ),
    )
    .exists()
    .correlate_except(InterviewRecord, JobApplication)
)
