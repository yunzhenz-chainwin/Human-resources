from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import BIGINT_PK, Base, TimestampMixin


class Candidate(TimestampMixin, Base):
    __tablename__ = "candidates"
    __table_args__ = (
        CheckConstraint(
            "birth_year IS NULL OR birth_year BETWEEN 1900 AND 2100", name="birth_year_range"
        ),
        CheckConstraint("total_years IS NULL OR total_years >= 0", name="total_years_nonnegative"),
        CheckConstraint(
            "expected_salary_min IS NULL OR expected_salary_min >= 0", name="salary_min_nonnegative"
        ),
        CheckConstraint(
            "expected_salary_max IS NULL OR expected_salary_max >= expected_salary_min",
            name="salary_range",
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    gender: Mapped[str | None] = mapped_column(String(1))
    birth_year: Mapped[int | None] = mapped_column(SmallInteger)
    birth_date: Mapped[date | None] = mapped_column(Date)
    email: Mapped[str | None] = mapped_column(String(255))
    email_norm: Mapped[str | None] = mapped_column(String(255), index=True)
    phone: Mapped[str | None] = mapped_column(String(50))
    phone_norm: Mapped[str | None] = mapped_column(String(20), index=True)
    city: Mapped[str | None] = mapped_column(String(50), index=True)
    address: Mapped[str | None] = mapped_column(String(255))
    highest_education: Mapped[str | None] = mapped_column(String(20))
    total_years: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    current_title: Mapped[str | None] = mapped_column(String(100))
    current_company: Mapped[str | None] = mapped_column(String(100))
    expected_title: Mapped[str | None] = mapped_column(String(100))
    expected_job_categories: Mapped[list[str] | None] = mapped_column(JSON)
    expected_cities: Mapped[list[str] | None] = mapped_column(JSON)
    expected_salary_min: Mapped[int | None]
    expected_salary_max: Mapped[int | None]
    salary_type: Mapped[str | None] = mapped_column(String(10))
    availability: Mapped[str | None] = mapped_column(String(20))
    job_type: Mapped[str | None] = mapped_column(String(20))
    source: Mapped[str | None] = mapped_column(String(20))
    source_note: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="new", server_default="new", index=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    summary: Mapped[str | None] = mapped_column(Text)
    consent_status: Mapped[str | None] = mapped_column(String(20))
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retention_until: Mapped[date | None] = mapped_column(Date, index=True)
    is_blacklisted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    blacklist_reason: Mapped[str | None] = mapped_column(String(200))
    dedup_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    educations: Mapped[list["CandidateEducation"]] = relationship(cascade="all, delete-orphan")
    experiences: Mapped[list["CandidateExperience"]] = relationship(cascade="all, delete-orphan")
    skills: Mapped[list["CandidateSkill"]] = relationship(cascade="all, delete-orphan")


class CandidateEducation(Base):
    __tablename__ = "candidate_educations"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    school: Mapped[str] = mapped_column(String(150), nullable=False)
    major: Mapped[str | None] = mapped_column(String(150))
    degree: Mapped[str | None] = mapped_column(String(20))
    start_ym: Mapped[str | None] = mapped_column(String(7))
    end_ym: Mapped[str | None] = mapped_column(String(7))
    is_graduated: Mapped[bool | None] = mapped_column(Boolean)
    sort_order: Mapped[int] = mapped_column(default=0, server_default="0")
    __table_args__ = (
        UniqueConstraint("candidate_id", "sort_order", name="uq_candidate_education_order"),
    )


class CandidateExperience(Base):
    __tablename__ = "candidate_experiences"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    company: Mapped[str] = mapped_column(String(150), nullable=False)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(100))
    start_ym: Mapped[str | None] = mapped_column(String(7))
    end_ym: Mapped[str | None] = mapped_column(String(7))
    years: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(default=0, server_default="0")
    __table_args__ = (
        UniqueConstraint("candidate_id", "sort_order", name="uq_candidate_experience_order"),
    )


class CandidateSkill(Base):
    """Canonical, searchable skills. Parser JSON is only an import snapshot."""

    __tablename__ = "candidate_skills"
    __table_args__ = (
        UniqueConstraint("candidate_id", "skill_norm", name="uq_candidate_skill_norm"),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    skill: Mapped[str] = mapped_column(String(100), nullable=False)
    skill_norm: Mapped[str] = mapped_column(String(100), nullable=False)


class CandidateActivity(Base):
    __tablename__ = "candidate_activities"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    happened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
