"""separate matching fit from audited human review

Revision ID: c27d8e5f4a61
Revises: b91e6d4f2a30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c27d8e5f4a61"
down_revision: str | None = "b91e6d4f2a30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("match_results") as batch_op:
        batch_op.add_column(sa.Column("stage_updated_by", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("stage_updated_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("manual_override_category", sa.String(40)))
        batch_op.add_column(sa.Column("manual_override_note", sa.String(500)))
        batch_op.add_column(sa.Column("manual_override_by", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("manual_override_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("feedback_category", sa.String(40)))
        batch_op.add_column(sa.Column("feedback_note", sa.String(500)))
        batch_op.create_foreign_key(
            "fk_match_results_stage_updated_by_users",
            "users",
            ["stage_updated_by"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_match_results_manual_override_by_users",
            "users",
            ["manual_override_by"],
            ["id"],
            ondelete="SET NULL",
        )

    # Preserve legacy free-text decisions while moving new writes to structured
    # categories. Existing values remain in feedback_reason for old API clients.
    op.execute(
        sa.text(
            """
            UPDATE match_results
            SET feedback_category = 'other', feedback_note = feedback_reason
            WHERE feedback_reason IS NOT NULL AND feedback_category IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE match_results
            SET stage_updated_by = feedback_by,
                stage_updated_at = COALESCE(feedback_at, updated_at)
            WHERE status NOT IN ('ineligible', 'recommended')
              AND stage_updated_at IS NULL
            """
        )
    )
    # Older databases may already contain a positive human decision on a failed
    # gate. Mark it as an imported override so a subsequent rematch preserves it.
    op.execute(
        sa.text(
            """
            UPDATE match_results
            SET manual_override_category = 'legacy_decision',
                manual_override_note = '既有人工決策（系統升級時保留）',
                manual_override_by = feedback_by,
                manual_override_at = COALESCE(feedback_at, updated_at)
            WHERE gate_passed = false
              AND status IN ('shortlisted', 'contacted', 'interview', 'offered', 'hired')
              AND manual_override_at IS NULL
            """
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("match_results") as batch_op:
        batch_op.drop_constraint(
            "fk_match_results_manual_override_by_users", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_match_results_stage_updated_by_users", type_="foreignkey"
        )
        batch_op.drop_column("feedback_note")
        batch_op.drop_column("feedback_category")
        batch_op.drop_column("manual_override_at")
        batch_op.drop_column("manual_override_by")
        batch_op.drop_column("manual_override_note")
        batch_op.drop_column("manual_override_category")
        batch_op.drop_column("stage_updated_at")
        batch_op.drop_column("stage_updated_by")
