"""support HR and manager question-plan versions with token usage

Revision ID: a8f4c2d9e710
Revises: f6a2d4c8b901
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a8f4c2d9e710"
down_revision: str = "f6a2d4c8b901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(
        "ix_interview_question_plans_application_version",
        table_name="interview_question_plans",
    )
    with op.batch_alter_table("interview_question_plans") as batch_op:
        batch_op.add_column(
            sa.Column("stage", sa.String(length=20), server_default="manager", nullable=False)
        )
        batch_op.add_column(
            sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column("thinking_tokens", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column("total_tokens", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.drop_constraint(
            "uq_interview_question_plans_application_version",
            type_="unique",
        )
        batch_op.create_check_constraint(
            "ck_interview_question_plans_valid_stage",
            "stage IN ('hr','manager')",
        )
        batch_op.create_unique_constraint(
            "uq_interview_question_plans_application_stage_version",
            ["application_id", "stage", "version"],
        )
    op.create_index(
        "ix_interview_question_plans_application_stage_version",
        "interview_question_plans",
        ["application_id", "stage", "version"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_interview_question_plans_application_stage_version",
        table_name="interview_question_plans",
    )
    # The previous schema stored manager plans only and required version numbers
    # to be unique per application.  HR and manager plans may both have version
    # 1 now, so retain the manager history when returning to that schema.
    op.execute(sa.text("DELETE FROM interview_question_plans WHERE stage = 'hr'"))
    with op.batch_alter_table("interview_question_plans") as batch_op:
        batch_op.drop_constraint(
            "uq_interview_question_plans_application_stage_version",
            type_="unique",
        )
        batch_op.drop_constraint(
            "ck_interview_question_plans_valid_stage",
            type_="check",
        )
        batch_op.create_unique_constraint(
            "uq_interview_question_plans_application_version",
            ["application_id", "version"],
        )
        batch_op.drop_column("total_tokens")
        batch_op.drop_column("thinking_tokens")
        batch_op.drop_column("output_tokens")
        batch_op.drop_column("input_tokens")
        batch_op.drop_column("stage")
    op.create_index(
        "ix_interview_question_plans_application_version",
        "interview_question_plans",
        ["application_id", "version"],
        unique=False,
    )
