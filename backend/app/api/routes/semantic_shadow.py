from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.db.session import get_db
from app.dependencies.auth import (
    enforce_candidate_scope,
    enforce_department_scope,
    require_recruiting_user,
)
from app.models.candidate import CandidateExperience, CandidateSkill
from app.models.matching import MatchResult
from app.models.organization import User
from app.models.semantic_shadow import SemanticShadowEvaluation
from app.schemas.semantic_shadow import (
    FormalMatchSnapshot,
    SemanticShadowComparison,
    SemanticShadowEvaluationRead,
    SemanticShadowTrigger,
)
from app.services import semantic_shadow as semantic_shadow_service
from app.services.security import write_audit

router = APIRouter(prefix="/semantic-shadow")


def _match(db: Session, match_id: int) -> MatchResult:
    result = db.scalar(
        select(MatchResult)
        .options(
            joinedload(MatchResult.candidate),
            joinedload(MatchResult.requisition),
        )
        .where(MatchResult.id == match_id)
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Match not found")
    return result


def _enforce_scope(db: Session, result: MatchResult, user: User) -> None:
    enforce_department_scope(user, result.requisition.department_id)
    # Keep the shadow experiment aligned with the formal matching page. Managers
    # can use it for applicants and department-scoped talent-pool recommendations,
    # but never for candidates outside their existing visibility scope.
    enforce_candidate_scope(db, user, result.candidate_id)


def _read(evaluation: SemanticShadowEvaluation) -> SemanticShadowEvaluationRead:
    return SemanticShadowEvaluationRead.model_validate(evaluation)


@router.post(
    "/matches/{match_id}/evaluations",
    response_model=SemanticShadowEvaluationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_semantic_shadow_evaluation(
    match_id: int,
    _trigger: SemanticShadowTrigger,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> SemanticShadowEvaluationRead:
    """Manually generate one experimental result without mutating formal matching."""

    result = _match(db, match_id)
    _enforce_scope(db, result, user)
    settings = get_settings()
    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    daily_count = int(
        db.scalar(
            select(func.count(SemanticShadowEvaluation.id)).where(
                SemanticShadowEvaluation.requested_by == user.id,
                SemanticShadowEvaluation.generated_at >= day_start,
            )
        )
        or 0
    )
    if daily_count >= settings.gemini_daily_generation_limit_per_user:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily semantic shadow generation limit reached",
        )
    skills = list(
        db.scalars(
            select(CandidateSkill.skill)
            .where(CandidateSkill.candidate_id == result.candidate_id)
            .order_by(CandidateSkill.id)
        ).all()
    )
    experiences = list(
        db.scalars(
            select(CandidateExperience)
            .where(CandidateExperience.candidate_id == result.candidate_id)
            .order_by(CandidateExperience.sort_order, CandidateExperience.id)
        ).all()
    )
    prompt_snapshot = semantic_shadow_service.build_deidentified_shadow_input(
        result.requisition,
        result.candidate,
        candidate_skills=skills,
        experiences=experiences,
    )
    generated = semantic_shadow_service.generate_semantic_shadow(
        prompt_snapshot,
        sensitive_values=semantic_shadow_service.candidate_sensitive_values(result.candidate),
    )
    analysis = generated.analysis.model_dump()
    usage = generated.token_usage
    evaluation = SemanticShadowEvaluation(
        match_result_id=result.id,
        requisition_id=result.requisition_id,
        candidate_id=result.candidate_id,
        requested_by=user.id,
        formal_total_score=result.total_score,
        formal_gate_passed=result.gate_passed,
        formal_rank=result.rank,
        formal_status=result.status,
        semantic_score=analysis["semantic_score"],
        synonym_evidence=analysis["synonym_evidence"],
        transferable_experience_evidence=analysis["transferable_experience_evidence"],
        concerns=analysis["concerns"],
        insufficient_data=analysis["insufficient_data"],
        interview_questions=analysis["interview_questions"],
        source=generated.source,
        generation_status=generated.generation_status,
        model_name=generated.model_name,
        prompt_version=generated.prompt_version,
        prompt_snapshot=prompt_snapshot,
        prompt_text=semantic_shadow_service.build_semantic_shadow_prompt(prompt_snapshot),
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        thinking_tokens=usage.thinking_tokens,
        total_tokens=usage.total_tokens,
        error_code=generated.error_code,
        error_detail=generated.error_detail,
    )
    db.add(evaluation)
    db.flush()
    write_audit(
        db,
        user,
        "semantic_shadow.generate",
        "semantic_shadow_evaluation",
        evaluation.id,
        result.requisition.department_id,
        details={
            "match_result_id": result.id,
            "source": generated.source,
            "generation_status": generated.generation_status,
            "model_name": generated.model_name,
            "prompt_version": generated.prompt_version,
            "total_tokens": usage.total_tokens,
            "experiment_only": True,
        },
    )
    db.commit()
    db.refresh(evaluation)
    return _read(evaluation)


@router.get(
    "/matches/{match_id}/comparison",
    response_model=SemanticShadowComparison,
)
def semantic_shadow_comparison(
    match_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> SemanticShadowComparison:
    result = _match(db, match_id)
    _enforce_scope(db, result, user)
    latest = db.scalar(
        select(SemanticShadowEvaluation)
        .where(SemanticShadowEvaluation.match_result_id == result.id)
        .order_by(
            SemanticShadowEvaluation.generated_at.desc(),
            SemanticShadowEvaluation.id.desc(),
        )
        .limit(1)
    )
    count = int(
        db.scalar(
            select(func.count(SemanticShadowEvaluation.id)).where(
                SemanticShadowEvaluation.match_result_id == result.id
            )
        )
        or 0
    )
    return SemanticShadowComparison(
        match_result_id=result.id,
        formal=FormalMatchSnapshot(
            total_score=float(result.total_score),
            gate_passed=result.gate_passed,
            rank=result.rank,
            status=result.status,
            computed_at=result.computed_at,
        ),
        latest_shadow=_read(latest) if latest else None,
        evaluation_count=count,
    )


@router.get(
    "/matches/{match_id}/evaluations",
    response_model=list[SemanticShadowEvaluationRead],
)
def list_semantic_shadow_evaluations(
    match_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> list[SemanticShadowEvaluationRead]:
    result = _match(db, match_id)
    _enforce_scope(db, result, user)
    rows = db.scalars(
        select(SemanticShadowEvaluation)
        .where(SemanticShadowEvaluation.match_result_id == result.id)
        .order_by(
            SemanticShadowEvaluation.generated_at.desc(),
            SemanticShadowEvaluation.id.desc(),
        )
        .limit(50)
    ).all()
    return [_read(row) for row in rows]
