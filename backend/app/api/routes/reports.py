from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import enforce_department_scope, get_current_user
from app.models import Candidate, JobRequisition, MatchResult, User
from app.schemas.reports import (
    FunnelReport,
    MatchingEvaluation,
    SourcesReport,
    TalentPoolReport,
    TimeToFillReport,
)
from app.services.matching import evaluate_matching
from app.services.reports import (
    funnel_report,
    sources_report,
    talent_pool_report,
    time_to_fill_report,
)

router = APIRouter(prefix="/reports")


def _validate_dates(from_date: date | None, to_date: date | None) -> None:
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=422, detail="from must be on or before to")


def _scoped_department(user: User, department_id: int | None) -> int | None:
    if user.role in {"admin", "hr"}:
        return department_id
    enforce_department_scope(user, department_id or user.department_id)
    return user.department_id


@router.get("/funnel", response_model=FunnelReport)
def get_funnel(
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    department_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _validate_dates(from_date, to_date)
    department_id = _scoped_department(user, department_id)
    return funnel_report(db, from_date, to_date, department_id)


@router.get("/time-to-fill", response_model=TimeToFillReport)
def get_time_to_fill(
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    department_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _validate_dates(from_date, to_date)
    department_id = _scoped_department(user, department_id)
    return time_to_fill_report(db, from_date, to_date, department_id)


@router.get("/sources", response_model=SourcesReport)
def get_sources(
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    department_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _validate_dates(from_date, to_date)
    department_id = _scoped_department(user, department_id)
    return sources_report(db, from_date, to_date, department_id)


@router.get("/talent-pool", response_model=TalentPoolReport)
def get_talent_pool(
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    department_id: int | None = None,
    skill_limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _validate_dates(from_date, to_date)
    department_id = _scoped_department(user, department_id)
    return talent_pool_report(db, from_date, to_date, department_id, skill_limit)


@router.get("/matching-evaluation", response_model=MatchingEvaluation)
def get_matching_evaluation(
    requisition_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    statement = (
        select(MatchResult)
        .join(Candidate, Candidate.id == MatchResult.candidate_id)
        .where(Candidate.deleted_at.is_(None))
    )
    if requisition_id is not None:
        requisition = db.get(JobRequisition, requisition_id)
        if requisition is None:
            raise HTTPException(status_code=404, detail="Requisition not found")
        enforce_department_scope(user, requisition.department_id)
        statement = statement.where(MatchResult.requisition_id == requisition_id)
    else:
        department_id = _scoped_department(user, None)
        if department_id is not None:
            statement = statement.join(
                JobRequisition, JobRequisition.id == MatchResult.requisition_id
            ).where(JobRequisition.department_id == department_id)
    results = list(db.scalars(statement).all())
    return evaluate_matching(results)
