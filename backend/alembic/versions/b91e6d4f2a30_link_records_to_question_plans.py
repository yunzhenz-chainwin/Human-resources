"""link interview records to the question-plan version used

Revision ID: b91e6d4f2a30
Revises: a8f4c2d9e710
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b91e6d4f2a30"
down_revision: str = "a8f4c2d9e710"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("interview_records") as batch_op:
        batch_op.add_column(sa.Column("question_plan_id", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("question_plan_version", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_interview_records_question_plan_id_interview_question_plans",
            "interview_question_plans",
            ["question_plan_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_check_constraint(
            "ck_interview_records_valid_question_plan_version",
            "question_plan_version IS NULL OR question_plan_version >= 1",
        )
    op.create_index(
        "ix_interview_records_question_plan_id",
        "interview_records",
        ["question_plan_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_interview_records_question_plan_id", table_name="interview_records")
    with op.batch_alter_table("interview_records") as batch_op:
        batch_op.drop_constraint(
            "ck_interview_records_valid_question_plan_version",
            type_="check",
        )
        batch_op.drop_constraint(
            "fk_interview_records_question_plan_id_interview_question_plans",
            type_="foreignkey",
        )
        batch_op.drop_column("question_plan_version")
        batch_op.drop_column("question_plan_id")
