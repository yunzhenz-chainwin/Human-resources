from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

BenchmarkStatus = Literal["blind", "revealed"]
BenchmarkVerdict = Literal["interview", "consider", "reject", "insufficient_data"]
BenchmarkReason = Literal[
    "strong_evidence",
    "skill_gap",
    "experience_gap",
    "role_relevance",
    "salary_mismatch",
    "location_mismatch",
    "education_gap",
    "transferable_experience",
    "missing_information",
    "other",
]
MetricStatus = Literal["available", "insufficient_data"]


class BenchmarkRatingWrite(BaseModel):
    verdict: BenchmarkVerdict
    reasons: list[BenchmarkReason] = Field(min_length=1, max_length=4)
    note: str | None = Field(default=None, max_length=1000)
    priority_rank: int | None = Field(default=None, ge=1, le=10)

    @model_validator(mode="after")
    def validate_reasons(self) -> BenchmarkRatingWrite:
        if len(set(self.reasons)) != len(self.reasons):
            raise ValueError("reasons must not contain duplicates")
        if self.verdict == "insufficient_data" and "missing_information" not in self.reasons:
            raise ValueError("insufficient_data requires missing_information")
        return self


class BenchmarkRatingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    verdict: BenchmarkVerdict
    reasons: list[BenchmarkReason]
    note: str | None
    priority_rank: int | None
    updated_at: datetime


class BenchmarkProgressRole(BaseModel):
    role: Literal["hr", "manager"]
    completed: int
    total: int
    complete_reviewer_count: int


class BenchmarkSuiteRead(BaseModel):
    key: str
    title: str
    fixture_version: str
    scoring_version: str
    status: BenchmarkStatus
    case_count: int
    revealed_at: datetime | None
    progress: list[BenchmarkProgressRole]


class BlindBenchmarkCaseRead(BaseModel):
    case_key: str
    sequence: int
    job_key: str
    job_profile: dict
    candidate_profile: dict
    my_rating: BenchmarkRatingRead | None


class BlindBenchmarkCaseList(BaseModel):
    suite: BenchmarkSuiteRead
    reviewer_role: Literal["hr", "manager"]
    cases: list[BlindBenchmarkCaseRead]


class MetricResult(BaseModel):
    status: MetricStatus
    value: float | None
    numerator: int | None = None
    denominator: int | None = None
    unit: Literal["percent", "count", "score"]
    explanation: str


class RevealedCaseResult(BaseModel):
    case_key: str
    job_key: str
    scenario: str
    expected_verdict: BenchmarkVerdict
    system_score: float
    system_gate_passed: bool
    data_completeness: float
    system_gate_misses: list[str]
    hr_verdict: BenchmarkVerdict | None
    manager_verdict: BenchmarkVerdict | None


class BenchmarkReport(BaseModel):
    suite: BenchmarkSuiteRead
    generated_at: datetime
    metrics: dict[str, MetricResult]
    warnings: list[str]
    cases: list[RevealedCaseResult]


class BenchmarkSeedResult(BaseModel):
    suite_key: str
    fixture_version: str
    total_cases: int
    created_cases: int
    updated_cases: int
    unchanged_fixture: bool
