from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

InterviewStage = Literal["hr", "manager"]
InterviewMode = Literal["onsite", "video", "phone", "other"]
InterviewRecordStatus = Literal[
    "planned",
    "in_progress",
    "completed",
    "cancelled",
    "no_show",
]
InterviewRecommendation = Literal["advance", "hold", "reject", "offer"]


class InterviewRecordQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1000)
    trait: str | None = Field(default=None, max_length=100)
    response: str | None = Field(default=None, max_length=5000)
    rating: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = Field(default=None, max_length=2000)
    purpose: str | None = Field(default=None, max_length=1000)
    follow_up: str | None = Field(default=None, max_length=1000)
    source: str | None = Field(default=None, max_length=200)

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("question must not be blank")
        return clean

    @field_validator("trait", "response", "notes", "purpose", "follow_up", "source")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        return clean or None


class InterviewRecordCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: InterviewStage
    interviewed_at: datetime
    duration_minutes: int | None = Field(default=None, ge=1, le=1440)
    mode: InterviewMode
    status: InterviewRecordStatus
    questions: list[InterviewRecordQuestion] = Field(default_factory=list, max_length=100)
    summary: str | None = Field(default=None, max_length=10000)
    private_notes: str | None = Field(default=None, max_length=10000)
    recommendation: InterviewRecommendation | None = None
    overall_rating: int | None = Field(default=None, ge=1, le=5)

    @field_validator("interviewed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("interviewed_at must include a timezone offset")
        return value

    @field_validator("summary", "private_notes")
    @classmethod
    def strip_long_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class InterviewRecordUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interviewed_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=1440)
    mode: InterviewMode | None = None
    status: InterviewRecordStatus | None = None
    questions: list[InterviewRecordQuestion] | None = Field(default=None, max_length=100)
    summary: str | None = Field(default=None, max_length=10000)
    private_notes: str | None = Field(default=None, max_length=10000)
    recommendation: InterviewRecommendation | None = None
    overall_rating: int | None = Field(default=None, ge=1, le=5)

    @field_validator("interviewed_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is None:
            raise ValueError("interviewed_at cannot be null")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("interviewed_at must include a timezone offset")
        return value

    @field_validator("mode", "status", "questions")
    @classmethod
    def forbid_null_required_fields(cls, value):
        if value is None:
            raise ValueError("field cannot be null")
        return value

    @field_validator("summary", "private_notes")
    @classmethod
    def strip_long_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def require_update_field(self):
        if not self.model_fields_set:
            raise ValueError("At least one interview record field is required")
        return self


class InterviewRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    stage: InterviewStage
    interviewed_at: datetime
    duration_minutes: int | None
    mode: InterviewMode
    status: InterviewRecordStatus
    questions: list[InterviewRecordQuestion]
    summary: str | None
    private_notes: str | None
    recommendation: InterviewRecommendation | None
    overall_rating: int | None
    evaluation_revealed: bool = True
    private_notes_visible: bool = False
    interviewer_id: int | None
    interviewer_name: str
    updated_by_id: int | None
    updated_by_name: str
    created_at: datetime
    updated_at: datetime
