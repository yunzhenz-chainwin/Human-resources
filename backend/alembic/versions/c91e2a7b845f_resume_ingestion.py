"""normalize resume ingestion and candidate skills

Revision ID: c91e2a7b845f
Revises: a2dbd6c1cc90
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c91e2a7b845f"
down_revision: str | None = "a2dbd6c1cc90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BIGINT_PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "candidate_skills",
        sa.Column("id", BIGINT_PK, primary_key=True),
        sa.Column(
            "candidate_id",
            sa.BigInteger(),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("skill", sa.String(100), nullable=False),
        sa.Column("skill_norm", sa.String(100), nullable=False),
        sa.UniqueConstraint("candidate_id", "skill_norm", name="uq_candidate_skill_norm"),
    )
    op.create_index("ix_candidate_skills_candidate_id", "candidate_skills", ["candidate_id"])
    with op.batch_alter_table("resume_files") as batch:
        batch.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            )
        )
        batch.add_column(sa.Column("confirmed_at", sa.DateTime(timezone=True)))
        batch.create_check_constraint(
            "ck_resume_files_valid_source_platform",
            "source_platform IN ('direct','p104','p1111','generic')",
        )
        batch.create_check_constraint(
            "ck_resume_files_valid_parse_status",
            "parse_status IN ('pending','parsed','needs_review','failed','confirmed')",
        )
        batch.create_check_constraint(
            "ck_resume_files_valid_overall_confidence",
            "overall_confidence IS NULL OR (overall_confidence >= 0 AND overall_confidence <= 1)",
        )


def downgrade() -> None:
    with op.batch_alter_table("resume_files") as batch:
        batch.drop_constraint("ck_resume_files_valid_overall_confidence", type_="check")
        batch.drop_constraint("ck_resume_files_valid_parse_status", type_="check")
        batch.drop_constraint("ck_resume_files_valid_source_platform", type_="check")
        batch.drop_column("confirmed_at")
        batch.drop_column("updated_at")
    op.drop_table("candidate_skills")
