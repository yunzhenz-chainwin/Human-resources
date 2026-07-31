from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ANALYSIS_DISCLAIMER = (
    "此結果僅代表履歷資料與職缺條件的匹配程度，不是錄取率或自動錄取決策；"
    "資料不足與必要條件仍須由 HR 或主管人工確認。"
)


class RoleMatchRequest(BaseModel):
    requisition_id: int = Field(gt=0)


class AnalysisComponent(BaseModel):
    key: Literal["skills", "relevance", "years", "industry"]
    label: str
    score: float | None = Field(default=None, ge=0, le=100)
    known: bool
    weight: float = Field(ge=0, le=1)
    hit: list[str] = Field(default_factory=list)
    miss: list[str] = Field(default_factory=list)


class AnalysisHighlight(BaseModel):
    kind: Literal["strength", "concern", "info"]
    category: str
    text: str


class CandidateRoleMatchItem(BaseModel):
    requisition_id: int
    req_no: str
    title: str
    department_name: str | None
    total_score: float = Field(ge=0, le=100)
    gate_passed: bool
    confidence: Literal["high", "medium", "low"]
    data_completeness: float = Field(ge=0, le=1)
    components: list[AnalysisComponent]
    highlights: list[AnalysisHighlight]
    insufficient_data: list[str]


class CandidateAnalysisEnvelope(BaseModel):
    generated_at: datetime
    algorithm_version: str
    ai_used: Literal[False] = False
    token_usage: Literal[0] = 0
    disclaimer: str = ANALYSIS_DISCLAIMER


class RecommendedRolesResponse(CandidateAnalysisEnvelope):
    items: list[CandidateRoleMatchItem]


class RoleMatchResponse(CandidateAnalysisEnvelope):
    item: CandidateRoleMatchItem
