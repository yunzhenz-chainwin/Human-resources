"""initial_core_schema

Revision ID: a2dbd6c1cc90
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a2dbd6c1cc90"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BIGINT_PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", BIGINT_PK, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "parent_id",
            sa.BigInteger(),
            sa.ForeignKey("departments.id", ondelete="RESTRICT"),
        ),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("name", name="uq_departments_name"),
    )
    op.create_table(
        "users",
        sa.Column("id", BIGINT_PK, primary_key=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column(
            "department_id",
            sa.BigInteger(),
            sa.ForeignKey("departments.id", ondelete="SET NULL"),
        ),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint("role IN ('admin','hr','manager')", name="ck_users_valid_role"),
    )
    op.create_index("ix_users_role", "users", ["role"])
    op.create_table(
        "candidates",
        sa.Column("id", BIGINT_PK, primary_key=True),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("gender", sa.String(1)),
        sa.Column("birth_year", sa.SmallInteger()),
        sa.Column("birth_date", sa.Date()),
        sa.Column("email", sa.String(255)),
        sa.Column("email_norm", sa.String(255)),
        sa.Column("phone", sa.String(50)),
        sa.Column("phone_norm", sa.String(20)),
        sa.Column("city", sa.String(50)),
        sa.Column("address", sa.String(255)),
        sa.Column("highest_education", sa.String(20)),
        sa.Column("total_years", sa.Numeric(4, 1)),
        sa.Column("current_title", sa.String(100)),
        sa.Column("current_company", sa.String(100)),
        sa.Column("expected_title", sa.String(100)),
        sa.Column("expected_job_categories", sa.JSON()),
        sa.Column("expected_cities", sa.JSON()),
        sa.Column("expected_salary_min", sa.Integer()),
        sa.Column("expected_salary_max", sa.Integer()),
        sa.Column("salary_type", sa.String(10)),
        sa.Column("availability", sa.String(20)),
        sa.Column("job_type", sa.String(20)),
        sa.Column("source", sa.String(20)),
        sa.Column("source_note", sa.String(200)),
        sa.Column("status", sa.String(20), server_default="new", nullable=False),
        sa.Column("owner_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("summary", sa.Text()),
        sa.Column("consent_status", sa.String(20)),
        sa.Column("consent_at", sa.DateTime(timezone=True)),
        sa.Column("retention_until", sa.Date()),
        sa.Column("is_blacklisted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("blacklist_reason", sa.String(200)),
        sa.Column("dedup_hash", sa.String(64)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("code", name="uq_candidates_code"),
        sa.CheckConstraint(
            "birth_year IS NULL OR birth_year BETWEEN 1900 AND 2100",
            name="ck_candidates_birth_year_range",
        ),
        sa.CheckConstraint(
            "total_years IS NULL OR total_years >= 0", name="ck_candidates_total_years_nonnegative"
        ),
        sa.CheckConstraint(
            "expected_salary_min IS NULL OR expected_salary_min >= 0",
            name="ck_candidates_salary_min_nonnegative",
        ),
        sa.CheckConstraint(
            "expected_salary_max IS NULL OR expected_salary_max >= expected_salary_min",
            name="ck_candidates_salary_range",
        ),
    )
    for column in ("email_norm", "phone_norm", "city", "status", "retention_until"):
        op.create_index(f"ix_candidates_{column}", "candidates", [column])
    op.create_index("ix_candidates_dedup_hash", "candidates", ["dedup_hash"])
    op.create_table(
        "candidate_educations",
        sa.Column("id", BIGINT_PK, primary_key=True),
        sa.Column(
            "candidate_id",
            sa.BigInteger(),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("school", sa.String(150), nullable=False),
        sa.Column("major", sa.String(150)),
        sa.Column("degree", sa.String(20)),
        sa.Column("start_ym", sa.String(7)),
        sa.Column("end_ym", sa.String(7)),
        sa.Column("is_graduated", sa.Boolean()),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.UniqueConstraint("candidate_id", "sort_order", name="uq_candidate_education_order"),
    )
    op.create_table(
        "candidate_experiences",
        sa.Column("id", BIGINT_PK, primary_key=True),
        sa.Column(
            "candidate_id",
            sa.BigInteger(),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("company", sa.String(150), nullable=False),
        sa.Column("title", sa.String(150), nullable=False),
        sa.Column("industry", sa.String(100)),
        sa.Column("start_ym", sa.String(7)),
        sa.Column("end_ym", sa.String(7)),
        sa.Column("years", sa.Numeric(4, 1)),
        sa.Column("description", sa.Text()),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.UniqueConstraint("candidate_id", "sort_order", name="uq_candidate_experience_order"),
    )
    op.create_table(
        "candidate_activities",
        sa.Column("id", BIGINT_PK, primary_key=True),
        sa.Column(
            "candidate_id",
            sa.BigInteger(),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("happened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_candidate_activities_candidate_id", "candidate_activities", ["candidate_id"]
    )
    op.create_table(
        "job_requisitions",
        sa.Column("id", BIGINT_PK, primary_key=True),
        sa.Column("req_no", sa.String(20), nullable=False, unique=True),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column(
            "department_id", sa.BigInteger(), sa.ForeignKey("departments.id", ondelete="SET NULL")
        ),
        sa.Column("requested_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("headcount", sa.Integer(), server_default="1", nullable=False),
        sa.Column("employment_type", sa.String(20), nullable=False),
        sa.Column("work_city", sa.String(50), nullable=False),
        sa.Column("work_address", sa.String(255)),
        sa.Column("salary_min", sa.Integer()),
        sa.Column("salary_max", sa.Integer()),
        sa.Column("salary_type", sa.String(10)),
        sa.Column("min_years", sa.Numeric(4, 1)),
        sa.Column("education_req", sa.String(20)),
        sa.Column("language_req", sa.String(100)),
        sa.Column("jd", sa.Text(), nullable=False),
        sa.Column("summary", sa.String(500)),
        sa.Column("skills", sa.JSON()),
        sa.Column("urgency", sa.String(10), server_default="normal"),
        sa.Column("needed_by", sa.Date()),
        sa.Column("status", sa.String(20), server_default="draft", nullable=False),
        sa.Column("return_reason", sa.String(500)),
        sa.Column("match_weights", sa.JSON()),
        sa.Column("approved_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("filled_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("headcount > 0", name="ck_job_requisitions_positive_headcount"),
        sa.CheckConstraint(
            "salary_min IS NULL OR salary_min >= 0",
            name="ck_job_requisitions_salary_min_nonnegative",
        ),
        sa.CheckConstraint(
            "salary_max IS NULL OR salary_max >= salary_min",
            name="ck_job_requisitions_salary_range",
        ),
        sa.CheckConstraint(
            "min_years IS NULL OR min_years >= 0", name="ck_job_requisitions_min_years_nonnegative"
        ),
    )
    for column in ("title", "department_id", "work_city", "status", "published_at"):
        op.create_index(f"ix_job_requisitions_{column}", "job_requisitions", [column])
    op.create_table(
        "resume_files",
        sa.Column("id", BIGINT_PK, primary_key=True),
        sa.Column(
            "candidate_id", sa.BigInteger(), sa.ForeignKey("candidates.id", ondelete="SET NULL")
        ),
        sa.Column("storage_key", sa.String(500)),
        sa.Column("original_filename", sa.String(255)),
        sa.Column("file_hash", sa.String(64), unique=True),
        sa.Column("file_size", sa.BigInteger()),
        sa.Column("mime", sa.String(100)),
        sa.Column("source_platform", sa.String(20), server_default="direct", nullable=False),
        sa.Column("platform_code", sa.String(50)),
        sa.Column("parse_status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("parsed_payload", sa.JSON()),
        sa.Column("field_confidence", sa.JSON()),
        sa.Column("overall_confidence", sa.Numeric(3, 2)),
        sa.Column("parser_version", sa.String(20)),
        sa.Column("error_message", sa.Text()),
        sa.Column("resume_url", sa.String(1000)),
        sa.Column("resume_text", sa.Text()),
        sa.Column(
            "uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "file_size IS NULL OR file_size >= 0", name="ck_resume_files_file_size_nonnegative"
        ),
    )
    op.create_index("ix_resume_files_candidate_id", "resume_files", ["candidate_id"])
    op.create_index("ix_resume_files_parse_status", "resume_files", ["parse_status"])
    op.create_table(
        "job_applications",
        sa.Column("id", BIGINT_PK, primary_key=True),
        sa.Column(
            "requisition_id",
            sa.BigInteger(),
            sa.ForeignKey("job_requisitions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            sa.BigInteger(),
            sa.ForeignKey("candidates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "resume_id", sa.BigInteger(), sa.ForeignKey("resume_files.id", ondelete="SET NULL")
        ),
        sa.Column("cover_letter", sa.Text()),
        sa.Column("linkedin_url", sa.String(1000)),
        sa.Column("portfolio_url", sa.String(1000)),
        sa.Column("status", sa.String(20), server_default="submitted", nullable=False),
        sa.Column("source", sa.String(20), server_default="career_site", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "requisition_id", "candidate_id", name="uq_application_requisition_candidate"
        ),
    )
    op.create_index("ix_job_applications_requisition_id", "job_applications", ["requisition_id"])
    op.create_index("ix_job_applications_candidate_id", "job_applications", ["candidate_id"])
    op.create_index("ix_job_applications_status", "job_applications", ["status"])


def downgrade() -> None:
    op.drop_table("job_applications")
    op.drop_table("resume_files")
    op.drop_table("job_requisitions")
    op.drop_table("candidate_activities")
    op.drop_table("candidate_experiences")
    op.drop_table("candidate_educations")
    op.drop_table("candidates")
    op.drop_table("users")
    op.drop_table("departments")
