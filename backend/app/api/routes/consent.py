from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import (
    enforce_candidate_scope,
    require_recruiting_manager,
    require_recruiting_user,
)
from app.models.candidate import Candidate
from app.models.consent import CandidateConsent, ConsentNotice
from app.models.organization import User
from app.schemas.consent import (
    CandidateConsentCreate,
    CandidateConsentRead,
    ConsentNoticeCreate,
    ConsentNoticeRead,
)
from app.services.consent import (
    activate_notice,
    active_notice,
    next_version,
    record_consent,
    withdraw_consent,
)
from app.services.security import client_ip, write_audit

router = APIRouter()


def _audit(
    db: Session, actor: User, request: Request, action: str, resource_type: str,
    resource_id: int, details: dict | None = None,
) -> None:
    write_audit(
        db,
        actor,
        action,
        resource_type,
        resource_id,
        actor.department_id,
        details=details,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


# --- Consent notices (versioned clauses) ------------------------------------


@router.get("/consent/notices", response_model=list[ConsentNoticeRead])
def list_notices(
    _: User = Depends(require_recruiting_user),
    db: Session = Depends(get_db),
) -> list[ConsentNotice]:
    return list(
        db.scalars(select(ConsentNotice).order_by(ConsentNotice.version.desc())).all()
    )


@router.get("/consent/notices/active", response_model=ConsentNoticeRead)
def get_active_notice(
    _: User = Depends(require_recruiting_user),
    db: Session = Depends(get_db),
) -> ConsentNotice:
    notice = active_notice(db)
    if notice is None:
        raise HTTPException(status_code=404, detail="No active consent notice")
    return notice


@router.post(
    "/consent/notices",
    response_model=ConsentNoticeRead,
    status_code=status.HTTP_201_CREATED,
)
def create_notice(
    payload: ConsentNoticeCreate,
    request: Request,
    actor: User = Depends(require_recruiting_manager),
    db: Session = Depends(get_db),
) -> ConsentNotice:
    notice = ConsentNotice(
        version=next_version(db),
        title=payload.title.strip(),
        body=payload.body.strip(),
        purpose_code=(payload.purpose_code.strip() or None) if payload.purpose_code else None,
        is_active=False,
        created_by=actor.id,
    )
    db.add(notice)
    try:
        db.flush()
        if payload.activate:
            activate_notice(db, notice)
        _audit(
            db, actor, request, "consent.notice.create", "consent_notice", notice.id,
            {"version": notice.version, "activated": payload.activate},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Consent notice version already exists"
        ) from exc
    db.refresh(notice)
    return notice


@router.post("/consent/notices/{notice_id}/activate", response_model=ConsentNoticeRead)
def activate(
    notice_id: int,
    request: Request,
    actor: User = Depends(require_recruiting_manager),
    db: Session = Depends(get_db),
) -> ConsentNotice:
    notice = db.get(ConsentNotice, notice_id)
    if notice is None:
        raise HTTPException(status_code=404, detail="Consent notice not found")
    activate_notice(db, notice)
    _audit(
        db, actor, request, "consent.notice.activate", "consent_notice", notice.id,
        {"version": notice.version},
    )
    db.commit()
    db.refresh(notice)
    return notice


# --- Candidate consents ------------------------------------------------------


@router.get(
    "/candidates/{candidate_id}/consents",
    response_model=list[CandidateConsentRead],
)
def list_candidate_consents(
    candidate_id: int,
    user: User = Depends(require_recruiting_user),
    db: Session = Depends(get_db),
) -> list[CandidateConsent]:
    enforce_candidate_scope(db, user, candidate_id)
    return list(
        db.scalars(
            select(CandidateConsent)
            .where(CandidateConsent.candidate_id == candidate_id)
            .order_by(CandidateConsent.consented_at.desc())
        ).all()
    )


@router.post(
    "/candidates/{candidate_id}/consents",
    response_model=CandidateConsentRead,
    status_code=status.HTTP_201_CREATED,
)
def record_candidate_consent(
    candidate_id: int,
    payload: CandidateConsentCreate,
    request: Request,
    user: User = Depends(require_recruiting_user),
    db: Session = Depends(get_db),
) -> CandidateConsent:
    enforce_candidate_scope(db, user, candidate_id)
    notice = active_notice(db)
    if notice is None:
        raise HTTPException(
            status_code=409, detail="No active consent notice to record against"
        )
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    consent, created = record_consent(
        db,
        candidate,
        notice,
        consented_at=payload.consented_at,
        channel=payload.channel,
    )
    _audit(
        db, user, request, "consent.candidate.record", "candidate_consent", consent.id,
        {
            "candidate_id": candidate_id,
            "notice_version": notice.version,
            "channel": payload.channel,
            "created": created,
        },
    )
    db.commit()
    db.refresh(consent)
    return consent


@router.post(
    "/consent/candidate-consents/{consent_id}/withdraw",
    response_model=CandidateConsentRead,
)
def withdraw_candidate_consent(
    consent_id: int,
    request: Request,
    actor: User = Depends(require_recruiting_manager),
    db: Session = Depends(get_db),
) -> CandidateConsent:
    consent = db.get(CandidateConsent, consent_id)
    if consent is None:
        raise HTTPException(status_code=404, detail="Consent record not found")
    withdrawn_count = withdraw_consent(db, consent)
    _audit(
        db, actor, request, "consent.candidate.withdraw", "candidate_consent", consent.id,
        {
            "candidate_id": consent.candidate_id,
            "notice_version": consent.notice_version,
            "withdrawn_count": withdrawn_count,
        },
    )
    db.commit()
    db.refresh(consent)
    return consent
