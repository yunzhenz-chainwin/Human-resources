from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.dependencies.auth import require_recruiting_manager
from app.models import Candidate, User
from app.schemas.retention import (
    CandidateRetentionRead,
    CandidateRetentionUpdate,
    TalentRetentionPolicyRead,
    TalentRetentionPolicyUpdate,
    TalentRetentionPurgeRead,
    TalentRetentionPurgeRequest,
)
from app.services.security import client_ip, write_audit
from app.services.talent_retention import (
    RETENTION_SETTING_KEY,
    get_retention_policy,
    purge_expired_candidates,
    set_candidate_retention,
    set_retention_policy,
)

router = APIRouter(prefix="/talent-retention")


@router.get("/policy", response_model=TalentRetentionPolicyRead)
def read_policy(
    _: User = Depends(require_recruiting_manager),
    db: Session = Depends(get_db),
) -> TalentRetentionPolicyRead:
    policy = get_retention_policy(db)
    return TalentRetentionPolicyRead(
        setting_key=RETENTION_SETTING_KEY,
        retention_years=policy.retention_years,
        defaulted=policy.defaulted,
    )


@router.put("/policy", response_model=TalentRetentionPolicyRead)
def update_policy(
    payload: TalentRetentionPolicyUpdate,
    request: Request,
    actor: User = Depends(require_recruiting_manager),
    db: Session = Depends(get_db),
) -> TalentRetentionPolicyRead:
    policy, applied_candidates = set_retention_policy(db, payload.retention_years)
    write_audit(
        db,
        actor,
        "talent_retention.policy.update",
        "system_setting",
        RETENTION_SETTING_KEY,
        details={
            "retention_years": policy.retention_years,
            "applied_candidates": applied_candidates,
        },
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    return TalentRetentionPolicyRead(
        setting_key=RETENTION_SETTING_KEY,
        retention_years=policy.retention_years,
        defaulted=False,
        applied_candidates=applied_candidates,
    )


@router.put(
    "/candidates/{candidate_id}",
    response_model=CandidateRetentionRead,
)
def update_candidate_retention(
    candidate_id: int,
    payload: CandidateRetentionUpdate,
    request: Request,
    actor: User = Depends(require_recruiting_manager),
    db: Session = Depends(get_db),
) -> CandidateRetentionRead:
    candidate = db.get(Candidate, candidate_id)
    if candidate is None or candidate.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    previous_override = candidate.retention_years_override
    previous_deadline = candidate.retention_until
    setting = set_candidate_retention(db, candidate, payload.retention_years)
    write_audit(
        db,
        actor,
        "talent_retention.candidate.update",
        "candidate",
        candidate.id,
        details={
            "previous_retention_years_override": previous_override,
            "retention_years_override": setting.retention_years_override,
            "effective_retention_years": setting.effective_retention_years,
            "previous_retention_until": (
                previous_deadline.isoformat() if previous_deadline else None
            ),
            "retention_until": setting.retention_until.isoformat(),
        },
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    return CandidateRetentionRead(**asdict(setting))


@router.post("/purge", response_model=TalentRetentionPurgeRead)
def purge_expired_talent(
    request: Request,
    payload: TalentRetentionPurgeRequest | None = None,
    actor: User = Depends(require_recruiting_manager),
    db: Session = Depends(get_db),
) -> TalentRetentionPurgeRead:
    dry_run = True if payload is None else payload.dry_run
    settings = get_settings()
    result = purge_expired_candidates(
        db,
        dry_run=dry_run,
        actor=actor,
        batch_size=settings.talent_retention_batch_size,
        settings=settings,
    )
    if dry_run:
        write_audit(
            db,
            actor,
            "talent_retention.preview",
            "talent_pool",
            "retention",
            details={
                "as_of": result.as_of.isoformat(),
                "eligible_candidates": result.eligible_candidates,
                "eligible_resume_files": result.eligible_resume_files,
                "lock_acquired": result.lock_acquired,
            },
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        db.commit()
    return TalentRetentionPurgeRead(**asdict(result))
