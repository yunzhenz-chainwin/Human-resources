from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import GLOBAL_RECRUITING_ROLES, require_recruiting_user
from app.models import AuditLog, User
from app.schemas.privacy import (
    ResumeAnonymizationRead,
    ResumeAnonymizationRequest,
    ResumeAnonymizationSummary,
    ResumeAnonymizationSummaryRead,
)
from app.services.resume_anonymization import anonymize_resume_text
from app.services.security import client_ip, write_audit

router = APIRouter(prefix="/resume-anonymization")


@router.post("", response_model=ResumeAnonymizationRead, status_code=status.HTTP_201_CREATED)
def anonymize_resume(
    payload: ResumeAnonymizationRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> ResumeAnonymizationRead:
    result = anonymize_resume_text(
        payload.plain_text,
        additional_names=payload.additional_names,
        additional_addresses=payload.additional_addresses,
    )
    operation_id = str(uuid4())
    # Privacy invariant: only aggregate counts and lengths enter the audit trail.
    # Neither source values nor the anonymized document are stored.
    write_audit(
        db,
        user,
        "resume.anonymize",
        "resume_anonymization",
        operation_id,
        user.department_id,
        details={"summary": result.summary.model_dump(mode="json")},
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    return ResumeAnonymizationRead(
        operation_id=operation_id,
        anonymized_text=result.anonymized_text,
        summary=result.summary,
    )


@router.get("/{operation_id}/summary", response_model=ResumeAnonymizationSummaryRead)
def get_anonymization_summary(
    operation_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> ResumeAnonymizationSummaryRead:
    statement = select(AuditLog).where(
        AuditLog.action == "resume.anonymize",
        AuditLog.resource_type == "resume_anonymization",
        AuditLog.resource_id == str(operation_id),
    )
    if user.role not in GLOBAL_RECRUITING_ROLES:
        statement = statement.where(AuditLog.actor_user_id == user.id)
    audit = db.scalar(statement)
    if audit is None:
        raise HTTPException(status_code=404, detail="Anonymization summary not found")
    raw_summary = (audit.details or {}).get("summary")
    try:
        summary = ResumeAnonymizationSummary.model_validate(raw_summary)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="Anonymization summary is invalid") from exc
    return ResumeAnonymizationSummaryRead(
        operation_id=str(operation_id),
        summary=summary,
        created_at=audit.created_at,
    )
