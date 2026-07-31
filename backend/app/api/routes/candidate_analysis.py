from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db.session import get_db
from app.dependencies.auth import (
    GLOBAL_RECRUITING_ROLES,
    enforce_candidate_scope,
    enforce_department_scope,
    require_recruiting_user,
)
from app.models.deidentified_resume import DeidentifiedResumeDocument
from app.models.organization import User
from app.models.recruitment import JobRequisition, ResumeFile
from app.schemas.candidate_analysis import (
    RecommendedRolesResponse,
    RoleMatchRequest,
    RoleMatchResponse,
)
from app.services.candidate_analysis import (
    ALGORITHM_VERSION,
    UnsupportedAnalysisPayload,
    build_candidate_profile,
    build_requisition_profile,
    recommendation_sort_key,
    score_requisition,
)
from app.services.deidentification import has_structured_analysis_payload
from app.services.security import client_ip, write_audit

router = APIRouter(prefix="/deidentified-resumes")

_ACTIVE_REQUISITION_STATUSES = frozenset({"approved", "sourcing", "interviewing"})


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"


def _analysis_document(
    db: Session,
    document_id: int,
    user: User,
) -> DeidentifiedResumeDocument:
    document = db.get(DeidentifiedResumeDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="De-identified resume not found")
    if document.validation_status != "analysis_ready":
        raise HTTPException(
            status_code=409,
            detail="De-identified resume is not approved for analysis",
        )
    if not has_structured_analysis_payload(document):
        # A manual upload for which no candidate safe fields could be derived is
        # an opaque, human-redacted file with no structured allow-list.  Automated
        # scoring has nothing to read, so refuse clearly instead of letting the
        # profile builder raise an opaque server error.
        raise HTTPException(
            status_code=422,
            detail="手動上傳的去識別化檔案沒有可供自動分析的結構化資料",
        )
    source_resume = db.get(ResumeFile, document.source_resume_id)
    if source_resume is None or source_resume.candidate_id is None:
        raise HTTPException(
            status_code=409,
            detail="De-identified resume has no analyzable candidate scope",
        )
    if (
        source_resume.file_hash
        and document.source_file_hash
        and source_resume.file_hash != document.source_file_hash
    ):
        raise HTTPException(
            status_code=409,
            detail="Source resume changed; generate and approve a new de-identified version",
        )
    # The source link is used only for authorization.  The candidate id and ORM row
    # never enter the analysis profile or response.
    enforce_candidate_scope(db, user, source_resume.candidate_id)
    return document


def _candidate_profile(document: DeidentifiedResumeDocument):
    try:
        return build_candidate_profile(
            document.analysis_payload,
            payload_schema_version=document.payload_schema_version,
        )
    except UnsupportedAnalysisPayload as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _visible_requisitions(db: Session, user: User) -> list[JobRequisition]:
    conditions = [JobRequisition.status.in_(_ACTIVE_REQUISITION_STATUSES)]
    if user.role not in GLOBAL_RECRUITING_ROLES:
        if user.role != "manager" or user.department_id is None:
            raise HTTPException(status_code=403, detail="Outside department scope")
        conditions.append(JobRequisition.department_id == user.department_id)
    return list(
        db.scalars(
            select(JobRequisition)
            .options(joinedload(JobRequisition.department))
            .where(*conditions)
            .order_by(JobRequisition.id)
        ).all()
    )


def _active_requisition(db: Session, requisition_id: int, user: User) -> JobRequisition:
    requisition = db.scalar(
        select(JobRequisition)
        .options(joinedload(JobRequisition.department))
        .where(JobRequisition.id == requisition_id)
    )
    if requisition is None:
        raise HTTPException(status_code=404, detail="Requisition not found")
    enforce_department_scope(user, requisition.department_id)
    if requisition.status not in _ACTIVE_REQUISITION_STATUSES:
        raise HTTPException(status_code=409, detail="Requisition is not active for analysis")
    return requisition


def _audit_analysis(
    db: Session,
    *,
    user: User,
    request: Request,
    mode: str,
    document_id: int,
    requisition_ids: list[int],
) -> None:
    # Intentionally metadata-only.  Scores, findings, payload, prompts, and output
    # text are never written to the audit record or any analysis result table.
    write_audit(
        db,
        user,
        "candidate_analysis.generate",
        "deidentified_resume",
        document_id,
        user.department_id,
        details={
            "mode": mode,
            "document_id": document_id,
            "requisition_ids": requisition_ids,
            "algorithm_version": ALGORITHM_VERSION,
            "success": True,
            "token_usage": 0,
        },
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()


@router.post(
    "/{document_id}/analyses/recommended-roles",
    response_model=RecommendedRolesResponse,
)
def recommend_roles(
    document_id: int,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> RecommendedRolesResponse:
    """Calculate top-five role suggestions only when this POST is requested."""

    document = _analysis_document(db, document_id, user)
    candidate = _candidate_profile(document)
    requisitions = _visible_requisitions(db, user)
    items = [
        score_requisition(candidate, build_requisition_profile(requisition))
        for requisition in requisitions
    ]
    items.sort(key=recommendation_sort_key)
    items = items[:5]
    _audit_analysis(
        db,
        user=user,
        request=request,
        mode="recommended_roles",
        document_id=document.id,
        requisition_ids=[item.requisition_id for item in items],
    )
    _no_store(response)
    return RecommendedRolesResponse(
        items=items,
        generated_at=datetime.now(UTC),
        algorithm_version=ALGORITHM_VERSION,
    )


@router.post(
    "/{document_id}/analyses/role-match",
    response_model=RoleMatchResponse,
)
def match_role(
    document_id: int,
    payload: RoleMatchRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> RoleMatchResponse:
    """Calculate one selected role match without persisting the result."""

    document = _analysis_document(db, document_id, user)
    candidate = _candidate_profile(document)
    requisition = _active_requisition(db, payload.requisition_id, user)
    item = score_requisition(candidate, build_requisition_profile(requisition))
    _audit_analysis(
        db,
        user=user,
        request=request,
        mode="role_match",
        document_id=document.id,
        requisition_ids=[requisition.id],
    )
    _no_store(response)
    return RoleMatchResponse(
        item=item,
        generated_at=datetime.now(UTC),
        algorithm_version=ALGORITHM_VERSION,
    )
