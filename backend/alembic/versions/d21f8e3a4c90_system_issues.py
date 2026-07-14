"""add IT system issue tracker

Revision ID: d21f8e3a4c90
Revises: d31c8a7e9f20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d21f8e3a4c90"
down_revision: str | None = "d31c8a7e9f20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
BIGINT_PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "system_issues",
        sa.Column("id", BIGINT_PK, nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("page", sa.String(length=255), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reproduction_steps", sa.Text(), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("updated_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_system_issues_title"), "system_issues", ["title"])
    op.create_index(op.f("ix_system_issues_page"), "system_issues", ["page"])
    op.create_index(op.f("ix_system_issues_severity"), "system_issues", ["severity"])
    op.create_index(op.f("ix_system_issues_status"), "system_issues", ["status"])
    op.create_index(
        op.f("ix_system_issues_created_by_user_id"), "system_issues", ["created_by_user_id"]
    )
    op.create_index(
        op.f("ix_system_issues_updated_by_user_id"), "system_issues", ["updated_by_user_id"]
    )


def downgrade() -> None:
    op.drop_table("system_issues")
