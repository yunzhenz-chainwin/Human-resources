from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import BIGINT_PK, Base, TimestampMixin, UTCDateTime

DEIDENTIFICATION_STATUSES = (
    "processing",
    "review_required",
    "analysis_ready",
    "failed",
    "superseded",
)


class DeidentifiedResumeDocument(TimestampMixin, Base):
    """A versioned, separately stored derivative of an original resume.

    Candidate identity is intentionally not duplicated here.  The restricted
    source-resume relationship is the only path back to the original record.
    """

    __tablename__ = "deidentified_resume_documents"
    __table_args__ = (
        UniqueConstraint(
            "source_resume_id",
            "version",
            name="uq_deidentified_resume_source_version",
        ),
        CheckConstraint("version >= 1", name="positive_version"),
        CheckConstraint(
            "file_size IS NULL OR file_size > 0",
            name="positive_file_size",
        ),
        CheckConstraint(
            "validation_status IN "
            "('processing','review_required','analysis_ready','failed','superseded')",
            name="valid_validation_status",
        ),
        CheckConstraint(
            "file_hash IS NULL OR length(file_hash) = 64",
            name="valid_file_hash",
        ),
        CheckConstraint(
            "length(source_file_hash) = 64",
            name="valid_source_file_hash",
        ),
        CheckConstraint(
            "length(anonymous_ref) = 36",
            name="valid_anonymous_ref",
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    source_resume_id: Mapped[int] = mapped_column(
        ForeignKey("resume_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    anonymous_ref: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(500), unique=True)
    file_hash: Mapped[str | None] = mapped_column(String(64))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    mime: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="application/pdf",
        server_default="application/pdf",
    )
    source_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    deidentification_version: Mapped[str] = mapped_column(String(50), nullable=False)
    payload_schema_version: Mapped[str] = mapped_column(String(80), nullable=False)
    analysis_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    validation_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="processing",
        server_default="processing",
        index=True,
    )
    validation_summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    source_resume = relationship("ResumeFile")
    creator = relationship("User", foreign_keys=[created_by])
    reviewer = relationship("User", foreign_keys=[reviewed_by])

    @property
    def has_file(self) -> bool:
        return bool(self.storage_key and self.file_size)
