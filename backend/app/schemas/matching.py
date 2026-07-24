from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MatchStatus = Literal[
    "ineligible",
    "recommended",
    "shortlisted",
    "contacted",
    "interview",
    "offered",
    "hired",
    "rejected_by_manager",
    "withdrawn",
]


class MatchHighlight(BaseModel):
    kind: Literal["strength", "concern", "info"]
    category: str
    text: str


class MatchingWeights(BaseModel):
    """Relative importance points; callers need not make them add up to 100."""

    model_config = ConfigDict(extra="forbid")

    skill: float = Field(ge=0, le=100)
    relevance: float = Field(ge=0, le=100)
    years: float = Field(ge=0, le=100)
    salary: float = Field(ge=0, le=100)
    education: float = Field(ge=0, le=100)
    location: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def require_positive_total(self):
        if sum(self.model_dump().values()) <= 0:
            raise ValueError("At least one matching weight must be greater than zero")
        return self

    def normalized(self) -> "MatchingWeights":
        values = self.model_dump()
        total = sum(values.values())
        normalized = {key: value / total for key, value in values.items()}
        return MatchingWeights(**normalized)


def _default_matching_weights() -> MatchingWeights:
    return MatchingWeights(
        skill=0.40,
        relevance=0.20,
        years=0.15,
        salary=0.10,
        education=0.10,
        location=0.05,
    )


class MatchCandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    current_title: str | None
    total_years: float | None
    phone: str | None
    email: str | None


class MatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    requisition_id: int
    candidate_id: int
    candidate: MatchCandidateRead
    gate_passed: bool
    total_score: float
    score_breakdown: dict
    highlights: list[MatchHighlight] = Field(default_factory=list)
    rank: int | None
    status: MatchStatus
    feedback_reason: str | None
    feedback_at: datetime | None
    computed_at: datetime


class MatchList(BaseModel):
    items: list[MatchRead]
    total: int


class CandidateMatchOverviewItem(BaseModel):
    candidate: MatchCandidateRead
    match: MatchRead | None = None


class CandidateMatchOverview(BaseModel):
    items: list[CandidateMatchOverviewItem]
    total_candidates: int
    computed_count: int
    uncomputed_count: int


class MatchingCriteria(BaseModel):
    required_skills: list[str] = Field(default_factory=list, max_length=30)
    preferred_skills: list[str] = Field(default_factory=list, max_length=30)
    min_years: float | None = Field(default=None, ge=0, le=80)
    education_req: str | None = Field(default=None, max_length=20)
    work_city: str = Field(min_length=1, max_length=50)
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    require_skills: bool = True
    require_years: bool = True
    require_education: bool = True
    require_location: bool = True
    # Fraction of required skills a candidate must have to pass the hard gate.
    # 1.0 keeps the strict "must have all" behaviour; lower it to surface strong
    # partial matches instead of gating them out entirely.
    required_skill_ratio: float = Field(default=1.0, ge=0, le=1)
    weights: MatchingWeights = Field(default_factory=_default_matching_weights)

    @model_validator(mode="after")
    def validate_salary_range(self):
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_max < self.salary_min
        ):
            raise ValueError("薪資上限不可低於薪資下限")
        return self


class MatchFeedback(BaseModel):
    status: Literal["interview", "rejected_by_manager"]
    reason: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def require_rejection_reason(self):
        if self.status == "rejected_by_manager" and not (self.reason or "").strip():
            raise ValueError("A rejection reason is required")
        return self


class MatchStatusUpdate(BaseModel):
    status: Literal[
        "recommended",
        "shortlisted",
        "contacted",
        "interview",
        "offered",
        "hired",
        "withdrawn",
    ]
