"""add authentication administration tables and fix urgency nullability

Revision ID: f73a9c0d4b11
Revises: e42f1b6d9a20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f73a9c0d4b11"
down_revision: str | None = "e42f1b6d9a20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BIGINT_PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.execute("UPDATE job_requisitions SET urgency = 'normal' WHERE urgency IS NULL")
    with op.batch_alter_table("job_requisitions") as batch_op:
        batch_op.alter_column(
            "urgency",
            existing_type=sa.String(length=10),
            existing_server_default="normal",
            nullable=False,
        )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", BIGINT_PK, primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("jti_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])

    op.create_table(
        "skill_catalog",
        sa.Column("id", BIGINT_PK, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("name_norm", sa.String(100), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "tags",
        sa.Column("id", BIGINT_PK, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("category", sa.String(50), server_default="candidate", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("name", "category", name="uq_tag_name_category"),
    )
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.JSON()),
        sa.Column("description", sa.String(255)),
        sa.Column("is_secret", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", BIGINT_PK, primary_key=True),
        sa.Column("actor_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(100)),
        sa.Column(
            "department_id", sa.BigInteger(), sa.ForeignKey("departments.id", ondelete="SET NULL")
        ),
        sa.Column("details", sa.JSON()),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("user_agent", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in (
        "actor_user_id",
        "action",
        "resource_type",
        "resource_id",
        "department_id",
        "created_at",
    ):
        op.create_index(f"ix_audit_logs_{column}", "audit_logs", [column])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("system_settings")
    op.drop_table("tags")
    op.drop_table("skill_catalog")
    op.drop_table("refresh_tokens")
    with op.batch_alter_table("job_requisitions") as batch_op:
        batch_op.alter_column(
            "urgency",
            existing_type=sa.String(length=10),
            existing_server_default="normal",
            nullable=True,
        )
