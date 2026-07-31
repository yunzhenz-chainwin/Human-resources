from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ConsentNoticeCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)
    purpose_code: str | None = Field(default=None, max_length=100)
    # A new version may be published as the active one immediately, which
    # deactivates any previously active notice.
    activate: bool = False


class ConsentNoticeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    version: int
    title: str
    body: str
    purpose_code: str | None
    is_active: bool
    created_by: int | None
    created_at: datetime
    updated_at: datetime


class CandidateConsentCreate(BaseModel):
    # Records that the candidate consented to whichever notice is active now.
    channel: Literal["hr_manual", "public_form"] = "hr_manual"
    consented_at: datetime | None = None


class CandidateConsentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    candidate_id: int
    notice_id: int
    notice_version: int
    consented_at: datetime
    channel: str
    withdrawn_at: datetime | None
