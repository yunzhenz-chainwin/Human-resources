from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

DeidentificationStatus = Literal[
    "processing",
    "review_required",
    "analysis_ready",
    "failed",
    "superseded",
]


class DeidentifiedExperienceRole(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=150)
    years: float | None = Field(default=None, ge=0, le=80)
    industry: str | None = Field(default=None, max_length=100)


class DeidentifiedAnalysisPayload(BaseModel):
    """The complete and exclusive allow-list available to analysis code."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["talenthub.deidentified-resume.v1"]
    current_title: str | None = Field(default=None, max_length=100)
    total_years: float | None = Field(default=None, ge=0, le=80)
    skills: list[str] = Field(default_factory=list, max_length=50)
    experience_roles: list[DeidentifiedExperienceRole] = Field(
        default_factory=list,
        max_length=20,
    )
    highest_education: str | None = Field(default=None, max_length=40)


class ValidationCount(BaseModel):
    type: str = Field(min_length=1, max_length=80)
    count: int = Field(ge=0)


class DeidentificationValidationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["talenthub.deidentification-validation.v1"]
    blocker_count: int = Field(ge=0)
    findings: list[ValidationCount] = Field(default_factory=list)
    redactions: list[ValidationCount] = Field(default_factory=list)
    payload_field_count: int = Field(ge=0)
    pdf_character_count: int = Field(ge=0)
    # Set on manually uploaded, already de-identified files.
    manual: bool = Field(default=False)


class DeidentifiedResumeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_resume_id: int
    anonymous_ref: str
    version: int
    file_hash: str | None
    file_size: int | None
    mime: str
    source_file_hash: str
    deidentification_version: str
    payload_schema_version: str
    # A system-generated snapshot carries a strict allow-list payload; a manual
    # HR upload carries only an opaque marker (``{"manual_upload": true}``), so
    # this is exposed as a raw mapping rather than the structured schema.
    analysis_payload: dict[str, Any]
    validation_status: DeidentificationStatus
    validation_summary: DeidentificationValidationSummary
    created_by: int | None
    reviewed_by: int | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    has_file: bool
