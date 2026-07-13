"""initial_core_schema

Revision ID: a2dbd6c1cc90
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a2dbd6c1cc90"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), sa.ForeignKey("departments.id")),
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
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("department_id", sa.BigInteger(), sa.ForeignKey("departments.id")),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_role", "users", ["role"])
    op.create_table(
        "candidates",
        sa.Column("id", sa.BigInteger(), primary_key=True),
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
        sa.Column("expected_job_categories", postgresql.ARRAY(sa.String())),
        sa.Column("expected_cities", postgresql.ARRAY(sa.String())),
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
    )
    for column in ("email_norm", "phone_norm", "city", "status", "retention_until"):
        op.create_index(f"ix_candidates_{column}", "candidates", [column])
    op.create_table(
        "candidate_educations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
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
    )
    op.create_table(
        "candidate_experiences",
        sa.Column("id", sa.BigInteger(), primary_key=True),
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
    )


def downgrade() -> None:
    op.drop_table("candidate_experiences")
    op.drop_table("candidate_educations")
    op.drop_table("candidates")
    op.drop_table("users")
    op.drop_table("departments")
