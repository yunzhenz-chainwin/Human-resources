from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

AnonymizedField = Literal[
    "name",
    "address",
    "phone",
    "email",
    "birth_date",
    "national_id",
    "personal_url",
]


class ResumeAnonymizationRequest(BaseModel):
    """Plain-text-only input for the standalone anonymization tool.

    The original text and optional hints are deliberately not represented by a
    persistence model. They exist only for the duration of this request.
    """

    plain_text: str = Field(min_length=1, max_length=200_000)
    additional_names: list[str] = Field(default_factory=list, max_length=20)
    additional_addresses: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("plain_text")
    @classmethod
    def require_visible_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("plain_text must contain visible text")
        return value

    @field_validator("additional_names", "additional_addresses")
    @classmethod
    def normalize_hints(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            clean = value.strip()
            if not clean:
                continue
            if len(clean) > 255:
                raise ValueError("an anonymization hint cannot exceed 255 characters")
            key = clean.casefold()
            if key not in seen:
                normalized.append(clean)
                seen.add(key)
        return normalized


class ResumeAnonymizationSummary(BaseModel):
    field_counts: dict[AnonymizedField, int]
    total_replacements: int = Field(ge=0)
    input_characters: int = Field(ge=0)
    output_characters: int = Field(ge=0)


class ResumeAnonymizationRead(BaseModel):
    operation_id: str
    anonymized_text: str
    summary: ResumeAnonymizationSummary


class ResumeAnonymizationSummaryRead(BaseModel):
    operation_id: str
    summary: ResumeAnonymizationSummary
    created_at: datetime
