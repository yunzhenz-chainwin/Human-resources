"""add manager resume target and uploader metadata

Revision ID: a61d9e8f2b40
Revises: f95b7d2c8e40
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a61d9e8f2b40"
down_revision: str | None = "f95b7d2c8e40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Batch mode keeps this migration valid for both PostgreSQL deployments and
    # the project's local SQLite runtime, where adding foreign keys rebuilds a table.
    with op.batch_alter_table("resume_files") as batch:
        batch.add_column(
            sa.Column("target_requisition_id", sa.BigInteger(), nullable=True)
        )
        batch.add_column(sa.Column("uploaded_by", sa.BigInteger(), nullable=True))
        batch.create_foreign_key(
            "fk_resume_files_target_requisition_id_job_requisitions",
            "job_requisitions",
            ["target_requisition_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_resume_files_uploaded_by_users",
            "users",
            ["uploaded_by"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index(
            "ix_resume_files_target_requisition_id",
            ["target_requisition_id"],
            unique=False,
        )
        batch.create_index(
            "ix_resume_files_uploaded_by",
            ["uploaded_by"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("resume_files") as batch:
        batch.drop_index("ix_resume_files_uploaded_by")
        batch.drop_index("ix_resume_files_target_requisition_id")
        batch.drop_constraint(
            "fk_resume_files_uploaded_by_users",
            type_="foreignkey",
        )
        batch.drop_constraint(
            "fk_resume_files_target_requisition_id_job_requisitions",
            type_="foreignkey",
        )
        batch.drop_column("uploaded_by")
        batch.drop_column("target_requisition_id")
