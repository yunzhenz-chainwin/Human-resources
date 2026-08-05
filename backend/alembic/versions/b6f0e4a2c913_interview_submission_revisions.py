"""add interview submission and reopen revision metadata

Revision ID: b6f0e4a2c913
Revises: a1c7e5f9b340
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b6f0e4a2c913"
down_revision: str | None = "a1c7e5f9b340"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("interview_records") as batch:
        batch.add_column(sa.Column("submitted_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("submitted_by_id", sa.BigInteger()))
        batch.add_column(sa.Column("submitted_by_name", sa.String(length=100)))
        batch.add_column(
            sa.Column(
                "revision_number",
                sa.Integer(),
                server_default="0",
                nullable=False,
            )
        )
        batch.add_column(sa.Column("last_reopen_reason", sa.Text()))
        batch.create_foreign_key(
            "fk_interview_records_submitted_by_id_users",
            "users",
            ["submitted_by_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_check_constraint(
            "valid_revision_number",
            "revision_number >= 0",
        )
        batch.create_index(
            "ix_interview_records_submitted_by_id",
            ["submitted_by_id"],
        )

    # Historical completed rows may predate structured scoring. Preserve them
    # without applying the new validation retroactively, while making their
    # original submission attribution and first revision explicit.
    op.execute(
        sa.text(
            """
            UPDATE interview_records
            SET submitted_at = updated_at,
                submitted_by_id = COALESCE(updated_by_id, interviewer_id),
                submitted_by_name = COALESCE(updated_by_name, interviewer_name),
                revision_number = 1
            WHERE status = 'completed'
            """
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("interview_records") as batch:
        batch.drop_index("ix_interview_records_submitted_by_id")
        batch.drop_constraint(
            "valid_revision_number",
            type_="check",
        )
        batch.drop_constraint(
            "fk_interview_records_submitted_by_id_users",
            type_="foreignkey",
        )
        batch.drop_column("last_reopen_reason")
        batch.drop_column("revision_number")
        batch.drop_column("submitted_by_name")
        batch.drop_column("submitted_by_id")
        batch.drop_column("submitted_at")
