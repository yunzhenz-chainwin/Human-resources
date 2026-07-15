"""add separate HR and department-manager interview stages

Revision ID: c83f2a6d4e70
Revises: b72e1f9a3c51
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c83f2a6d4e70"
down_revision: str | None = "b72e1f9a3c51"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("job_applications") as batch:
        for stage in ("hr", "manager"):
            batch.add_column(
                sa.Column(f"{stage}_interview_at", sa.DateTime(timezone=True), nullable=True)
            )
            batch.add_column(
                sa.Column(f"{stage}_interview_result", sa.String(length=30), nullable=True)
            )
            batch.add_column(sa.Column(f"{stage}_interview_notes", sa.Text(), nullable=True))
            batch.add_column(
                sa.Column(f"{stage}_interview_updated_by", sa.BigInteger(), nullable=True)
            )
            batch.add_column(
                sa.Column(
                    f"{stage}_interview_updated_at",
                    sa.DateTime(timezone=True),
                    nullable=True,
                )
            )
            batch.create_foreign_key(
                f"fk_job_applications_{stage}_interview_updated_by_users",
                "users",
                [f"{stage}_interview_updated_by"],
                ["id"],
                ondelete="SET NULL",
            )
            batch.create_index(
                f"ix_job_applications_{stage}_interview_updated_by",
                [f"{stage}_interview_updated_by"],
                unique=False,
            )

    # Preserve the latest legacy interview in the stage owned by its last editor.
    op.execute(
        sa.text(
            """
            UPDATE job_applications
               SET manager_interview_at = interview_at,
                   manager_interview_result = interview_result,
                   manager_interview_notes = interview_notes,
                   manager_interview_updated_by = interview_updated_by,
                   manager_interview_updated_at = updated_at
             WHERE (interview_at IS NOT NULL
                 OR interview_result IS NOT NULL
                 OR interview_notes IS NOT NULL)
               AND interview_updated_by IN (
                   SELECT id FROM users WHERE role = 'manager'
               )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE job_applications
               SET hr_interview_at = interview_at,
                   hr_interview_result = interview_result,
                   hr_interview_notes = interview_notes,
                   hr_interview_updated_by = interview_updated_by,
                   hr_interview_updated_at = updated_at
             WHERE (interview_at IS NOT NULL
                 OR interview_result IS NOT NULL
                 OR interview_notes IS NOT NULL)
               AND NOT EXISTS (
                   SELECT 1 FROM users
                    WHERE users.id = job_applications.interview_updated_by
                      AND users.role = 'manager'
               )
            """
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("job_applications") as batch:
        for stage in ("manager", "hr"):
            batch.drop_index(f"ix_job_applications_{stage}_interview_updated_by")
            batch.drop_constraint(
                f"fk_job_applications_{stage}_interview_updated_by_users",
                type_="foreignkey",
            )
            batch.drop_column(f"{stage}_interview_updated_at")
            batch.drop_column(f"{stage}_interview_updated_by")
            batch.drop_column(f"{stage}_interview_notes")
            batch.drop_column(f"{stage}_interview_result")
            batch.drop_column(f"{stage}_interview_at")
