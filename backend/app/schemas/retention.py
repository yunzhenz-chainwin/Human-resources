from datetime import date

from pydantic import BaseModel, Field


class TalentRetentionPolicyUpdate(BaseModel):
    retention_years: int = Field(ge=1, le=20)


class TalentRetentionPolicyRead(BaseModel):
    setting_key: str
    retention_years: int
    defaulted: bool = False
    applied_candidates: int = Field(default=0, ge=0)


class CandidateRetentionUpdate(BaseModel):
    # NULL means this candidate follows the company-wide default again.
    retention_years: int | None = Field(default=None, ge=1, le=20)


class CandidateRetentionRead(BaseModel):
    candidate_id: int
    retention_years_override: int | None
    effective_retention_years: int = Field(ge=1, le=20)
    uses_company_default: bool
    anchor_date: date
    retention_until: date


class TalentRetentionPurgeRequest(BaseModel):
    # A destructive call must opt in explicitly with {"dry_run": false}.
    dry_run: bool = True


class TalentRetentionPurgeRead(BaseModel):
    as_of: date
    dry_run: bool
    lock_acquired: bool
    eligible_candidates: int = Field(ge=0)
    eligible_resume_files: int = Field(ge=0)
    deleted_candidates: int = Field(ge=0)
    deleted_resume_files: int = Field(ge=0)
    remaining_candidates: int = Field(ge=0)
    queued_storage_deletions: int = Field(ge=0)
    deleted_storage_objects: int = Field(ge=0)
    deleted_photos: int = Field(ge=0)
    storage_delete_failures: int = Field(ge=0)
