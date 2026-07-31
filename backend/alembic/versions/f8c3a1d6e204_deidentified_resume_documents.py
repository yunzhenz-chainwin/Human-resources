"""add versioned de-identified resume documents

Revision ID: f8c3a1d6e204
Revises: e63b1f8a2d40
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f8c3a1d6e204"
down_revision: str = "e63b1f8a2d40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BIGINT_PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "deidentified_resume_documents",
        sa.Column("id", BIGINT_PK, nullable=False),
        sa.Column("source_resume_id", sa.BigInteger(), nullable=False),
        sa.Column("anonymous_ref", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=True),
        sa.Column("file_hash", sa.String(length=64), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column(
            "mime",
            sa.String(length=100),
            server_default="application/pdf",
            nullable=False,
        ),
        sa.Column("source_file_hash", sa.String(length=64), nullable=False),
        sa.Column("deidentification_version", sa.String(length=50), nullable=False),
        sa.Column("payload_schema_version", sa.String(length=80), nullable=False),
        sa.Column("analysis_payload", sa.JSON(), nullable=False),
        sa.Column(
            "validation_status",
            sa.String(length=20),
            server_default="processing",
            nullable=False,
        ),
        sa.Column("validation_summary", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_by", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
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
            "version >= 1",
            name="ck_deidentified_resume_documents_positive_version",
        ),
        sa.CheckConstraint(
            "file_size IS NULL OR file_size > 0",
            name="ck_deidentified_resume_documents_positive_file_size",
        ),
        sa.CheckConstraint(
            "validation_status IN "
            "('processing','review_required','analysis_ready','failed','superseded')",
            name="ck_deidentified_resume_documents_valid_validation_status",
        ),
        sa.CheckConstraint(
            "file_hash IS NULL OR length(file_hash) = 64",
            name="ck_deidentified_resume_documents_valid_file_hash",
        ),
        sa.CheckConstraint(
            "length(source_file_hash) = 64",
            name="ck_deidentified_resume_documents_valid_source_file_hash",
        ),
        sa.CheckConstraint(
            "length(anonymous_ref) = 36",
            name="ck_deidentified_resume_documents_valid_anonymous_ref",
        ),
        sa.ForeignKeyConstraint(
            ["source_resume_id"],
            ["resume_files.id"],
            name="fk_deidentified_resume_documents_source_resume_id_resume_files",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_deidentified_resume_documents_created_by_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["users.id"],
            name="fk_deidentified_resume_documents_reviewed_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_deidentified_resume_documents"),
        sa.UniqueConstraint(
            "source_resume_id",
            "version",
            name="uq_deidentified_resume_source_version",
        ),
        sa.UniqueConstraint(
            "storage_key",
            name="uq_deidentified_resume_documents_storage_key",
        ),
    )
    op.create_index(
        op.f("ix_deidentified_resume_documents_source_resume_id"),
        "deidentified_resume_documents",
        ["source_resume_id"],
    )
    op.create_index(
        op.f("ix_deidentified_resume_documents_anonymous_ref"),
        "deidentified_resume_documents",
        ["anonymous_ref"],
    )
    op.create_index(
        op.f("ix_deidentified_resume_documents_validation_status"),
        "deidentified_resume_documents",
        ["validation_status"],
    )
    op.create_index(
        op.f("ix_deidentified_resume_documents_created_by"),
        "deidentified_resume_documents",
        ["created_by"],
    )
    op.create_index(
        op.f("ix_deidentified_resume_documents_reviewed_by"),
        "deidentified_resume_documents",
        ["reviewed_by"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_deidentified_resume_documents_reviewed_by"),
        table_name="deidentified_resume_documents",
    )
    op.drop_index(
        op.f("ix_deidentified_resume_documents_created_by"),
        table_name="deidentified_resume_documents",
    )
    op.drop_index(
        op.f("ix_deidentified_resume_documents_validation_status"),
        table_name="deidentified_resume_documents",
    )
    op.drop_index(
        op.f("ix_deidentified_resume_documents_anonymous_ref"),
        table_name="deidentified_resume_documents",
    )
    op.drop_index(
        op.f("ix_deidentified_resume_documents_source_resume_id"),
        table_name="deidentified_resume_documents",
    )
    op.drop_table("deidentified_resume_documents")
