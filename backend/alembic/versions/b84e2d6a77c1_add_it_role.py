"""add explicit IT system-administrator role

Revision ID: b84e2d6a77c1
Revises: f73a9c0d4b11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b84e2d6a77c1"
down_revision: str | None = "f73a9c0d4b11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("ck_users_valid_role", type_="check")
        batch_op.create_check_constraint(
            "valid_role", "role IN ('admin','it','hr','manager')"
        )


def downgrade() -> None:
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'it'")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("ck_users_valid_role", type_="check")
        batch_op.create_check_constraint(
            "valid_role", "role IN ('admin','hr','manager')"
        )
