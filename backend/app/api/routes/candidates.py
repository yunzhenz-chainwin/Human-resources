from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import audit_pii_read
from app.models import Candidate, CandidateActivity
from app.schemas.hr import (
    CandidateActivityCreate,
    CandidateActivityRead,
    CandidateCreate,
    CandidateRead,
    CandidateUpdate,
)
from app.services.applications import normalize_email, normalize_phone

router = APIRouter(prefix="/candidates")


@router.get("", response_model=list[CandidateRead])
def list_candidates(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[Candidate]:
    query = (
        select(Candidate)
        .where(Candidate.deleted_at.is_(None))
        .order_by(Candidate.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(db.scalars(query).all())


@router.post("", response_model=CandidateRead, status_code=status.HTTP_201_CREATED)
def create_candidate(payload: CandidateCreate, db: Session = Depends(get_db)) -> Candidate:
    now = datetime.now(UTC)
    candidate = Candidate(
        code=f"T{now.year}-{now.strftime('%m%d%H%M%S%f')[-10:]}",
        name=payload.name,
        email=str(payload.email) if payload.email else None,
        email_norm=normalize_email(str(payload.email) if payload.email else None),
        phone=payload.phone,
        phone_norm=normalize_phone(payload.phone),
        city=payload.city,
        current_title=payload.current_title,
        total_years=payload.total_years,
        source=payload.source,
        status="new",
    )
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return candidate


@router.get("/{candidate_id}", response_model=CandidateRead)
def get_candidate(
    candidate_id: int,
    db: Session = Depends(get_db),
    _audited_user: object = Depends(audit_pii_read),
) -> Candidate:
    candidate = db.get(Candidate, candidate_id)
    if not candidate or candidate.deleted_at:
        raise HTTPException(status_code=404, detail="人才不存在")
    return candidate


@router.patch("/{candidate_id}", response_model=CandidateRead)
def update_candidate(
    candidate_id: int, payload: CandidateUpdate, db: Session = Depends(get_db)
) -> Candidate:
    candidate = db.get(Candidate, candidate_id)
    if not candidate or candidate.deleted_at:
        raise HTTPException(status_code=404, detail="人才不存在")
    updates = payload.model_dump(exclude_unset=True)
    if "email" in updates:
        candidate.email_norm = normalize_email(updates["email"])
    if "phone" in updates:
        candidate.phone_norm = normalize_phone(updates["phone"])
    for field, value in updates.items():
        setattr(candidate, field, value)
    db.commit()
    db.refresh(candidate)
    return candidate


@router.post(
    "/{candidate_id}/activities",
    response_model=CandidateActivityRead,
    status_code=status.HTTP_201_CREATED,
)
def create_activity(
    candidate_id: int, payload: CandidateActivityCreate, db: Session = Depends(get_db)
) -> CandidateActivity:
    candidate = db.get(Candidate, candidate_id)
    if not candidate or candidate.deleted_at:
        raise HTTPException(status_code=404, detail="人才不存在")
    activity = CandidateActivity(
        candidate_id=candidate_id,
        type=payload.type,
        content=payload.content,
        happened_at=payload.happened_at or datetime.now(UTC),
    )
    db.add(activity)
    if payload.next_status:
        candidate.status = payload.next_status
    db.commit()
    db.refresh(activity)
    return activity


@router.get("/{candidate_id}/activities", response_model=list[CandidateActivityRead])
def list_activities(
    candidate_id: int,
    page_size: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[CandidateActivity]:
    candidate = db.get(Candidate, candidate_id)
    if not candidate or candidate.deleted_at:
        raise HTTPException(status_code=404, detail="Candidate not found")
    statement = (
        select(CandidateActivity)
        .where(CandidateActivity.candidate_id == candidate_id)
        .order_by(CandidateActivity.happened_at.desc(), CandidateActivity.id.desc())
        .limit(page_size)
    )
    return list(db.scalars(statement).all())


@router.post(
    "/{candidate_id}/contacts",
    response_model=CandidateActivityRead,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
def create_contact_alias(
    candidate_id: int, payload: CandidateActivityCreate, db: Session = Depends(get_db)
) -> CandidateActivity:
    return create_activity(candidate_id, payload, db)


@router.delete("/{candidate_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_candidate(candidate_id: int, db: Session = Depends(get_db)) -> None:
    candidate = db.get(Candidate, candidate_id)
    if not candidate or candidate.deleted_at:
        raise HTTPException(status_code=404, detail="人才不存在")
    candidate.deleted_at = datetime.now(UTC)
    db.commit()
