from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class InterviewQuestionSuggestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    personality_traits: list[str] = Field(min_length=1, max_length=10)

    @field_validator("personality_traits")
    @classmethod
    def clean_traits(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            clean = value.strip()
            if not clean:
                raise ValueError("personality traits must not be blank")
            if len(clean) > 100:
                raise ValueError("personality traits must be 100 characters or fewer")
            key = clean.casefold()
            if key not in seen:
                result.append(clean)
                seen.add(key)
        return result


class SuggestedInterviewQuestion(BaseModel):
    question: str
    purpose: str
    follow_up: str
    source: str | None = None


class TraitQuestionSuggestion(BaseModel):
    trait: str
    questions: list[SuggestedInterviewQuestion]


class InterviewQuestionSuggestionResponse(BaseModel):
    requisition_id: int
    job_title: str
    suggestions: list[TraitQuestionSuggestion]
    guidance: str
    application_id: int | None = None
    personalization_basis: list[str] = Field(default_factory=list)


class InterviewQuestionPlanItem(BaseModel):
    category: str
    question: str
    purpose: str
    follow_up: str
    source: str


class InterviewQuestionPlanResponse(BaseModel):
    application_id: int
    stage: Literal["hr", "manager"]
    job_title: str
    questions: list[InterviewQuestionPlanItem] = Field(min_length=5, max_length=5)
    personalization_basis: list[str]
    guidance: str
