from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db.session import get_db
from app.dependencies.auth import enforce_department_scope, get_current_user
from app.models import JobRequisition, MatchResult, User
from app.schemas.matching import MatchFeedback, MatchList, MatchRead, MatchStatusUpdate
from app.services.matching import rematch_requisition

router = APIRouter()


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
    if status:
        statement = statement.where(MatchResult.status == status)
    items = list(db.scalars(statement).all())
    return MatchList(items=[MatchRead.model_validate(item) for item in items], total=len(items))


@router.post("/requisitions/{requisition_id}/rematch", response_model=MatchList)
def rematch(
    requisition_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
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


@router.post("/matches/{match_id}/feedback", response_model=MatchRead)
def match_feedback(
    match_id: int,
    payload: MatchFeedback,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MatchResult:
    result = _match(db, match_id)
    _requisition(db, result.requisition_id, user)
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
    user: User = Depends(get_current_user),
) -> MatchResult:
    result = _match(db, match_id)
    _requisition(db, result.requisition_id, user)
    result.status = payload.status
    db.commit()
    db.refresh(result)
    return result
