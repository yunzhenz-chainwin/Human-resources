from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import exists, select
from sqlalchemy.orm import Session, joinedload

from app.db.session import get_db
from app.dependencies.auth import (
    enforce_department_scope,
    get_current_user,
    require_recruiting_manager,
    require_recruiting_user,
)
from app.models import Candidate, JobApplication, JobRequisition, MatchResult, User
from app.schemas.matching import (
    CandidateMatchOverview,
    CandidateMatchOverviewItem,
    MatchCandidateRead,
    MatchFeedback,
    MatchingCriteria,
    MatchList,
    MatchRead,
    MatchStatusUpdate,
)
from app.services.matching import assess_matching_readiness, rematch_requisition

router = APIRouter()


def _criteria(requisition: JobRequisition) -> MatchingCriteria:
    config = requisition.match_weights or {}
    return MatchingCriteria(
        required_skills=config.get("required_skills") or [],
        preferred_skills=config.get("preferred_skills") or [],
        min_years=float(requisition.min_years) if requisition.min_years is not None else None,
        education_req=requisition.education_req,
        work_city=requisition.work_city,
        salary_min=requisition.salary_min,
        salary_max=requisition.salary_max,
        require_skills=config.get("require_skills", True),
        require_years=config.get("require_years", True),
        require_education=config.get("require_education", True),
        require_location=config.get("require_location", True),
    )


def _requisition(db: Session, requisition_id: int, user: User) -> JobRequisition:
    requisition = db.get(JobRequisition, requisition_id)
    if not requisition:
        raise HTTPException(status_code=404, detail="Requisition not found")
    enforce_department_scope(user, requisition.department_id)
    return requisition


def _match(db: Session, match_id: int) -> MatchResult:
    result = db.scalar(
        select(MatchResult)
        .options(joinedload(MatchResult.candidate))
        .where(MatchResult.id == match_id)
    )
    if not result:
        raise HTTPException(status_code=404, detail="Match not found")
    return result


def _enforce_match_action_scope(db: Session, result: MatchResult, user: User) -> None:
    _requisition(db, result.requisition_id, user)
    if user.role != "manager":
        return
    application_id = db.scalar(
        select(JobApplication.id)
        .where(
            JobApplication.requisition_id == result.requisition_id,
            JobApplication.candidate_id == result.candidate_id,
        )
        .limit(1)
    )
    if application_id is None:
        raise HTTPException(status_code=403, detail="Candidate did not apply to this requisition")


@router.get("/requisitions/{requisition_id}/matches", response_model=MatchList)
def list_matches(
    requisition_id: int,
    min_score: float = Query(0, ge=0, le=100),
    status: str | None = None,
    include_ineligible: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MatchList:
    _requisition(db, requisition_id, user)
    statement = (
        select(MatchResult)
        .options(joinedload(MatchResult.candidate))
        .where(
            MatchResult.requisition_id == requisition_id,
            MatchResult.total_score >= min_score,
        )
        .order_by(
            MatchResult.rank.is_(None),
            MatchResult.rank.asc(),
            MatchResult.candidate_id.asc(),
        )
    )
    if not include_ineligible:
        statement = statement.where(MatchResult.gate_passed.is_(True))
    if user.role == "manager":
        statement = statement.where(
            exists(
                select(JobApplication.id).where(
                    JobApplication.requisition_id == requisition_id,
                    JobApplication.candidate_id == MatchResult.candidate_id,
                )
            )
        )
    if status:
        statement = statement.where(MatchResult.status == status)
    items = list(db.scalars(statement).all())
    return MatchList(items=[MatchRead.model_validate(item) for item in items], total=len(items))


@router.get(
    "/requisitions/{requisition_id}/candidate-match-overview",
    response_model=CandidateMatchOverview,
)
def candidate_match_overview(
    requisition_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CandidateMatchOverview:
    """Return every active candidate, including people not scored for this job yet."""

    _requisition(db, requisition_id, user)
    statement = (
        select(Candidate, MatchResult)
        .outerjoin(
            MatchResult,
            (MatchResult.candidate_id == Candidate.id)
            & (MatchResult.requisition_id == requisition_id),
        )
        .options(joinedload(MatchResult.candidate))
        .where(Candidate.deleted_at.is_(None))
        .order_by(
            MatchResult.total_score.desc().nulls_last(),
            Candidate.name.asc(),
            Candidate.id.asc(),
        )
    )
    if user.role == "manager":
        applied_to_this_job = exists(
            select(JobApplication.id).where(
                JobApplication.requisition_id == requisition_id,
                JobApplication.candidate_id == Candidate.id,
            )
        )
        statement = statement.where(applied_to_this_job)
    rows = db.execute(statement).all()
    items = [
        CandidateMatchOverviewItem(
            candidate=MatchCandidateRead.model_validate(candidate),
            match=MatchRead.model_validate(result) if result else None,
        )
        for candidate, result in rows
    ]
    computed_count = sum(item.match is not None for item in items)
    return CandidateMatchOverview(
        items=items,
        total_candidates=len(items),
        computed_count=computed_count,
        uncomputed_count=len(items) - computed_count,
    )


@router.get(
    "/requisitions/{requisition_id}/matching-criteria", response_model=MatchingCriteria
)
def get_matching_criteria(
    requisition_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MatchingCriteria:
    return _criteria(_requisition(db, requisition_id, user))


@router.put(
    "/requisitions/{requisition_id}/matching-criteria", response_model=MatchingCriteria
)
def update_matching_criteria(
    requisition_id: int,
    payload: MatchingCriteria,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_manager),
) -> MatchingCriteria:
    requisition = _requisition(db, requisition_id, user)
    config = dict(requisition.match_weights or {})
    config.update(
        required_skills=payload.required_skills,
        preferred_skills=payload.preferred_skills,
        require_skills=payload.require_skills,
        require_years=payload.require_years,
        require_education=payload.require_education,
        require_location=payload.require_location,
    )
    requisition.match_weights = config
    requisition.skills = list(dict.fromkeys(payload.required_skills + payload.preferred_skills))
    requisition.min_years = payload.min_years
    requisition.education_req = payload.education_req or None
    requisition.work_city = payload.work_city
    requisition.salary_min = payload.salary_min
    requisition.salary_max = payload.salary_max
    db.commit()
    db.refresh(requisition)
    rematch_requisition(db, requisition)
    return _criteria(requisition)


@router.post("/requisitions/{requisition_id}/rematch", response_model=MatchList)
def rematch(
    requisition_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_manager),
) -> MatchList:
    requisition = _requisition(db, requisition_id, user)
    rematch_requisition(db, requisition)
    return list_matches(
        requisition_id,
        min_score=0,
        status=None,
        include_ineligible=False,
        db=db,
        user=user,
    )


@router.get("/requisitions/{requisition_id}/match-readiness")
def match_readiness(
    requisition_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _requisition(db, requisition_id, user)
    statement = select(MatchResult).where(MatchResult.requisition_id == requisition_id)
    if user.role == "manager":
        statement = statement.where(
            exists(
                select(JobApplication.id).where(
                    JobApplication.requisition_id == requisition_id,
                    JobApplication.candidate_id == MatchResult.candidate_id,
                )
            )
        )
    results = list(db.scalars(statement).all())
    return assess_matching_readiness(results)


@router.post("/matches/{match_id}/feedback", response_model=MatchRead)
def match_feedback(
    match_id: int,
    payload: MatchFeedback,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> MatchResult:
    result = _match(db, match_id)
    _enforce_match_action_scope(db, result, user)
    result.status = payload.status
    result.feedback_reason = payload.reason.strip() if payload.reason else None
    result.feedback_at = datetime.now(UTC)
    db.commit()
    db.refresh(result)
    return result


@router.post("/matches/{match_id}/status", response_model=MatchRead)
def update_match_status(
    match_id: int,
    payload: MatchStatusUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> MatchResult:
    result = _match(db, match_id)
    _enforce_match_action_scope(db, result, user)
    result.status = payload.status
    db.commit()
    db.refresh(result)
    return result
