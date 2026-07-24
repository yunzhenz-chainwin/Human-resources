"""add retention storage deletion outbox

Revision ID: f2c7a91d4e60
Revises: e15b9d4c7a83
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f2c7a91d4e60"
down_revision: str | None = "e15b9d4c7a83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BIGINT_PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "retention_storage_deletions",
        sa.Column("id", BIGINT_PK, primary_key=True),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("locator", sa.String(length=1000), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('resume','candidate_photo')",
            name="ck_retention_storage_deletions_valid_retention_storage_kind",
        ),
        sa.UniqueConstraint(
            "kind", "locator", name="uq_retention_storage_kind_locator"
        ),
    )
    op.create_index(
        "ix_retention_storage_deletions_kind",
        "retention_storage_deletions",
        ["kind"],
    )


def downgrade() -> None:
    op.drop_table("retention_storage_deletions")
