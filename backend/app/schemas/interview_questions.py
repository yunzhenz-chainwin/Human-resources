from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.interview_question_compliance import COMPLIANCE_RULES_VERSION


class QuestionCompliance(BaseModel):
    """Result of screening a question against the anti-discrimination rules.

    ``status`` is ``"warning"`` when the question appears to touch a protected
    attribute (marital / pregnancy / childcare / age / gender / race / religion
    / disability_health / appearance / astrology_blood, ...). The wording is a
    compliance aid and must be reviewed by legal counsel.
    """

    status: Literal["ok", "warning"] = "ok"
    categories: list[str] = Field(default_factory=list)
    matched: list[str] = Field(default_factory=list)
    suggestion: str = ""
    rules_version: str = COMPLIANCE_RULES_VERSION


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
    compliance: QuestionCompliance | None = None


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
    compliance: QuestionCompliance | None = None


class InterviewQuestionPlanResponse(BaseModel):
    id: int | None = None
    application_id: int
    stage: Literal["hr", "manager"]
    job_title: str
    questions: list[InterviewQuestionPlanItem] = Field(default_factory=list, max_length=5)
    personalization_basis: list[str]
    guidance: str
    generation_mode: Literal["gemini", "rules", "not_generated"] = "not_generated"
    generation_warning: str | None = None
    provider: str | None = None
    model_name: str | None = None
    version: int | None = None
    generated_at: datetime | None = None
    context_matches: bool = False
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    thinking_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
