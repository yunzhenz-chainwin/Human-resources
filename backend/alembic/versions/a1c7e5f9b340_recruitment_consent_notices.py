"""add versioned recruitment consent notices and candidate consents

Revision ID: a1c7e5f9b340
Revises: f8c3a1d6e204
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1c7e5f9b340"
down_revision: str = "f8c3a1d6e204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BIGINT_PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "consent_notices",
        sa.Column("id", BIGINT_PK, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("purpose_code", sa.String(length=100), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "version >= 1", name="ck_consent_notices_positive_version"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_consent_notices_created_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_consent_notices"),
        sa.UniqueConstraint("version", name="uq_consent_notices_version"),
    )
    op.create_index(
        op.f("ix_consent_notices_is_active"),
        "consent_notices",
        ["is_active"],
    )
    op.create_index(
        op.f("ix_consent_notices_created_by"),
        "consent_notices",
        ["created_by"],
    )

    op.create_table(
        "candidate_consents",
        sa.Column("id", BIGINT_PK, nullable=False),
        sa.Column("candidate_id", sa.BigInteger(), nullable=False),
        sa.Column("notice_id", sa.BigInteger(), nullable=False),
        sa.Column("notice_version", sa.Integer(), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "channel",
            sa.String(length=30),
            server_default="hr_manual",
            nullable=False,
        ),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidates.id"],
            name="fk_candidate_consents_candidate_id_candidates",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["notice_id"],
            ["consent_notices.id"],
            name="fk_candidate_consents_notice_id_consent_notices",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_candidate_consents"),
    )
    op.create_index(
        op.f("ix_candidate_consents_candidate_id"),
        "candidate_consents",
        ["candidate_id"],
    )
    op.create_index(
        op.f("ix_candidate_consents_notice_id"),
        "candidate_consents",
        ["notice_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_candidate_consents_notice_id"),
        table_name="candidate_consents",
    )
    op.drop_index(
        op.f("ix_candidate_consents_candidate_id"),
        table_name="candidate_consents",
    )
    op.drop_table("candidate_consents")
    op.drop_index(
        op.f("ix_consent_notices_created_by"),
        table_name="consent_notices",
    )
    op.drop_index(
        op.f("ix_consent_notices_is_active"),
        table_name="consent_notices",
    )
    op.drop_table("consent_notices")
