from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

EXPERIMENT_DISCLAIMER = (
    "實驗性語意影子評分，不可作為錄取或淘汰依據，且不參與正式分數、必要條件或排序；"
    "僅供人工檢視與後續成效比較。"
)

ShortFinding = Annotated[str, Field(min_length=1, max_length=400)]


class SemanticShadowTrigger(BaseModel):
    acknowledge_experimental: Literal[True] = Field(
        description="必須明確確認這是實驗結果，才會人工觸發一次生成。"
    )


class SkillSynonymEvidence(BaseModel):
    required_skill: str = Field(min_length=1, max_length=100)
    candidate_skill: str = Field(min_length=1, max_length=100)
    rationale: str = Field(min_length=1, max_length=400)


class TransferableExperienceEvidence(BaseModel):
    experience: str = Field(min_length=1, max_length=200)
    target_requirement: str = Field(min_length=1, max_length=200)
    rationale: str = Field(min_length=1, max_length=400)


class ShadowInterviewQuestion(BaseModel):
    gap: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=400)


class SemanticShadowAnalysis(BaseModel):
    semantic_score: float = Field(ge=0, le=100)
    synonym_evidence: list[SkillSynonymEvidence] = Field(default_factory=list, max_length=10)
    transferable_experience_evidence: list[TransferableExperienceEvidence] = Field(
        default_factory=list, max_length=10
    )
    concerns: list[ShortFinding] = Field(default_factory=list, max_length=10)
    insufficient_data: list[ShortFinding] = Field(default_factory=list, max_length=10)
    interview_questions: list[ShadowInterviewQuestion] = Field(default_factory=list, max_length=5)


class FormalMatchSnapshot(BaseModel):
    total_score: float
    gate_passed: bool
    rank: int | None
    status: str
    computed_at: datetime


class SemanticShadowEvaluationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    match_result_id: int
    requisition_id: int
    candidate_id: int
    requested_by: int | None
    formal_total_score: float
    formal_gate_passed: bool
    formal_rank: int | None
    formal_status: str
    semantic_score: float
    synonym_evidence: list[SkillSynonymEvidence]
    transferable_experience_evidence: list[TransferableExperienceEvidence]
    concerns: list[str]
    insufficient_data: list[str]
    interview_questions: list[ShadowInterviewQuestion]
    source: Literal["gemini", "rules_fallback"]
    generation_status: Literal["completed", "fallback"]
    model_name: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    thinking_tokens: int
    total_tokens: int
    error_code: str | None
    generated_at: datetime
    experiment_only: Literal[True] = True
    disclaimer: str = EXPERIMENT_DISCLAIMER


class SemanticShadowComparison(BaseModel):
    match_result_id: int
    formal: FormalMatchSnapshot
    latest_shadow: SemanticShadowEvaluationRead | None
    evaluation_count: int
    experiment_only: Literal[True] = True
    disclaimer: str = EXPERIMENT_DISCLAIMER
