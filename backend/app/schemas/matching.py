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
