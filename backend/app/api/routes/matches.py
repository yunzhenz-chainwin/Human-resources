from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.db.session import get_db
from app.dependencies.auth import (
    candidate_scope_clause,
    enforce_candidate_scope,
    enforce_department_scope,
    get_current_user,
    require_recruiting_manager,
    require_recruiting_user,
)
from app.models import Candidate, JobApplication, JobRequisition, MatchResult, User
from app.schemas.interview_questions import (
    InterviewQuestionSuggestionRequest,
    InterviewQuestionSuggestionResponse,
)
from app.schemas.matching import (
    CandidateMatchOverview,
    CandidateMatchOverviewItem,
    MatchCandidateRead,
    MatchFeedback,
    MatchingCriteria,
    MatchingCriteriaImpact,
    MatchingWeights,
    MatchList,
    MatchManualOverride,
    MatchRead,
    MatchSource,
    MatchStatusUpdate,
)
from app.services.interview_questions import suggest_interview_questions
from app.services.matching import (
    assess_matching_readiness,
    rematch_requisition,
    resolve_weights,
    score_candidate,
)
from app.services.security import write_audit

router = APIRouter()

ADVANCING_MATCH_STATUSES = {
    "recommended",
    "shortlisted",
    "contacted",
    "interview",
    "offered",
    "hired",
}


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
        required_skill_ratio=config.get("required_skill_ratio", 1.0),
        weights=MatchingWeights(**resolve_weights(config)),
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
    # HR has global recruiting scope. A manager can act only on candidates already
    # visible within their own department (including department talent-pool
    # recommendations), never on the global pool.
    enforce_candidate_scope(db, user, result.candidate_id)


def _guard_status_transition(result: MatchResult, new_status: str) -> None:
    """Refuse status changes that bypass the eligibility gate or reopen a hire.

    Shared by the feedback and status endpoints so neither path can advance an
    ineligible candidate to a positive outcome nor move a finalized hire.
    """
    if (
        not result.gate_passed
        and result.manual_override_at is None
        and new_status in ADVANCING_MATCH_STATUSES
    ):
        raise HTTPException(
            status_code=409,
            detail="A failed gate requires a documented manual override before advancing",
        )
    if result.status == "hired" and new_status != "hired":
        raise HTTPException(
            status_code=409,
            detail="A hired match is final and cannot be moved to another status",
        )


def _application_exists(requisition_id: int):
    return exists(
        select(JobApplication.id).where(
            JobApplication.requisition_id == requisition_id,
            JobApplication.candidate_id == Candidate.id,
        )
    )


def _application_id(requisition_id: int):
    return (
        select(JobApplication.id)
        .where(
            JobApplication.requisition_id == requisition_id,
            JobApplication.candidate_id == Candidate.id,
        )
        .correlate(Candidate)
        .scalar_subquery()
    )


def _effective_source(user: User, source: MatchSource) -> MatchSource:
    # Preserve the historical manager default: no source query means actual
    # applicants only. Explicit talent_pool requests stay department-scoped.
    if source == "all" and user.role == "manager":
        return "applicants"
    return source


def _candidate_conditions(user: User, requisition_id: int, source: MatchSource) -> list:
    effective = _effective_source(user, source)
    conditions = [Candidate.deleted_at.is_(None), candidate_scope_clause(user)]
    applied = _application_exists(requisition_id)
    if effective == "applicants":
        conditions.append(applied)
    elif effective == "talent_pool":
        conditions.append(~applied)
    return conditions


def _criteria_config(requisition: JobRequisition, payload: MatchingCriteria) -> dict:
    config = dict(requisition.match_weights or {})
    config.update(
        required_skills=payload.required_skills,
        preferred_skills=payload.preferred_skills,
        require_skills=payload.require_skills,
        require_years=payload.require_years,
        require_education=payload.require_education,
        require_location=payload.require_location,
        required_skill_ratio=payload.required_skill_ratio,
    )
    if "weights" in payload.model_fields_set:
        config.update(payload.weights.normalized().model_dump())
    return config


def _preview_requisition(
    requisition: JobRequisition, payload: MatchingCriteria
) -> JobRequisition:
    preview = JobRequisition(
        req_no=requisition.req_no,
        title=requisition.title,
        department_id=requisition.department_id,
        requested_by=requisition.requested_by,
        headcount=requisition.headcount,
        employment_type=requisition.employment_type,
        work_city=payload.work_city,
        work_address=requisition.work_address,
        salary_min=payload.salary_min,
        salary_max=payload.salary_max,
        salary_type=requisition.salary_type,
        min_years=payload.min_years,
        education_req=payload.education_req,
        language_req=requisition.language_req,
        jd=requisition.jd,
        summary=requisition.summary,
        skills=list(dict.fromkeys(payload.required_skills + payload.preferred_skills)),
        status=requisition.status,
        match_weights=_criteria_config(requisition, payload),
    )
    preview.id = requisition.id
    return preview


@router.get("/requisitions/{requisition_id}/matches", response_model=MatchList)
def list_matches(
    requisition_id: int,
    source: MatchSource = Query("all"),
    min_score: float = Query(0, ge=0, le=100),
    status: str | None = None,
    include_ineligible: bool = False,
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MatchList:
    _requisition(db, requisition_id, user)
    conditions = [
        MatchResult.requisition_id == requisition_id,
        MatchResult.total_score >= min_score,
        *_candidate_conditions(user, requisition_id, source),
    ]
    if not include_ineligible:
        conditions.append(MatchResult.gate_passed.is_(True))
    if status:
        conditions.append(MatchResult.status == status)
    # True total over the filtered set, independent of the limit/offset page below.
    total = int(
        db.scalar(
            select(func.count(MatchResult.id))
            .join(Candidate, Candidate.id == MatchResult.candidate_id)
            .where(*conditions)
        )
        or 0
    )
    statement = (
        select(MatchResult)
        .join(Candidate, Candidate.id == MatchResult.candidate_id)
        .options(joinedload(MatchResult.candidate))
        .where(*conditions)
        .order_by(
            MatchResult.rank.is_(None),
            MatchResult.rank.asc(),
            MatchResult.candidate_id.asc(),
        )
    )
    if offset:
        statement = statement.offset(offset)
    if limit is not None:
        statement = statement.limit(limit)
    items = list(db.scalars(statement).all())
    return MatchList(items=[MatchRead.model_validate(item) for item in items], total=total)


@router.get(
    "/requisitions/{requisition_id}/candidate-match-overview",
    response_model=CandidateMatchOverview,
)
def candidate_match_overview(
    requisition_id: int,
    source: MatchSource = Query("all"),
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CandidateMatchOverview:
    """Return every active candidate, including people not scored for this job yet."""

    _requisition(db, requisition_id, user)
    match_join = (MatchResult.candidate_id == Candidate.id) & (
        MatchResult.requisition_id == requisition_id
    )
    effective_source = _effective_source(user, source)
    conditions = _candidate_conditions(user, requisition_id, source)
    base_conditions = [Candidate.deleted_at.is_(None), candidate_scope_clause(user)]
    applied = _application_exists(requisition_id)
    applicants_count = int(
        db.scalar(select(func.count(Candidate.id)).where(*base_conditions, applied)) or 0
    )
    talent_pool_count = int(
        db.scalar(select(func.count(Candidate.id)).where(*base_conditions, ~applied)) or 0
    )
    # Totals span the whole filtered set (ignoring limit/offset): every candidate
    # plus the subset that already has a computed match row.
    totals = db.execute(
        select(func.count(Candidate.id), func.count(MatchResult.id))
        .select_from(Candidate)
        .outerjoin(MatchResult, match_join)
        .where(*conditions)
    ).one()
    total_candidates = int(totals[0] or 0)
    computed_count = int(totals[1] or 0)
    application_id = _application_id(requisition_id)
    statement = (
        select(Candidate, MatchResult, application_id.label("application_id"))
        .outerjoin(MatchResult, match_join)
        .options(joinedload(MatchResult.candidate))
        .where(*conditions)
        .order_by(
            MatchResult.total_score.desc().nulls_last(),
            Candidate.name.asc(),
            Candidate.id.asc(),
        )
    )
    if offset:
        statement = statement.offset(offset)
    if limit is not None:
        statement = statement.limit(limit)
    rows = db.execute(statement).all()
    items = [
        CandidateMatchOverviewItem(
            candidate=MatchCandidateRead.model_validate(candidate),
            match=MatchRead.model_validate(result) if result else None,
            source="applicant" if application_id is not None else "talent_pool",
            application_id=application_id,
        )
        for candidate, result, application_id in rows
    ]
    return CandidateMatchOverview(
        items=items,
        source=effective_source,
        total_candidates=total_candidates,
        computed_count=computed_count,
        uncomputed_count=total_candidates - computed_count,
        applicants_count=applicants_count,
        talent_pool_count=talent_pool_count,
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
    requisition.match_weights = _criteria_config(requisition, payload)
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


@router.post(
    "/requisitions/{requisition_id}/matching-criteria/preview",
    response_model=MatchingCriteriaImpact,
)
def preview_matching_criteria(
    requisition_id: int,
    payload: MatchingCriteria,
    source: MatchSource = Query("all"),
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_manager),
) -> MatchingCriteriaImpact:
    """Calculate gate impact without changing the requisition or persisted matches."""

    requisition = _requisition(db, requisition_id, user)
    candidates = list(
        db.scalars(
            select(Candidate)
            .options(selectinload(Candidate.skills), selectinload(Candidate.educations))
            .where(*_candidate_conditions(user, requisition_id, source))
            .order_by(Candidate.id)
        ).all()
    )
    preview_requisition = _preview_requisition(requisition, payload)
    current_passed = 0
    preview_passed = 0
    changed_count = 0
    for candidate in candidates:
        skills = [item.skill for item in candidate.skills]
        current = score_candidate(requisition, candidate, skills).gate_passed
        prospective = score_candidate(preview_requisition, candidate, skills).gate_passed
        current_passed += int(current)
        preview_passed += int(prospective)
        changed_count += int(current != prospective)
    return MatchingCriteriaImpact(
        source=_effective_source(user, source),
        total_candidates=len(candidates),
        current_passed=current_passed,
        preview_passed=preview_passed,
        preview_excluded=len(candidates) - preview_passed,
        changed_count=changed_count,
    )


@router.get(
    "/requisitions/{requisition_id}/matching-weights",
    response_model=MatchingWeights,
)
def get_matching_weights(
    requisition_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MatchingWeights:
    requisition = _requisition(db, requisition_id, user)
    return MatchingWeights(**resolve_weights(requisition.match_weights))


@router.put(
    "/requisitions/{requisition_id}/matching-weights",
    response_model=MatchingWeights,
)
def update_matching_weights(
    requisition_id: int,
    payload: MatchingWeights,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> MatchingWeights:
    """Let HR or the owning department manager set relative scoring importance."""

    requisition = _requisition(db, requisition_id, user)
    normalized = payload.normalized()
    previous = resolve_weights(requisition.match_weights)
    config = dict(requisition.match_weights or {})
    config.update(normalized.model_dump())
    requisition.match_weights = config
    write_audit(
        db,
        user,
        "matching.weights.update",
        "job_requisition",
        requisition.id,
        requisition.department_id,
        details={
            "previous": previous,
            "weights": normalized.model_dump(),
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    db.refresh(requisition)
    rematch_requisition(db, requisition)
    return normalized


@router.post(
    "/requisitions/{requisition_id}/interview-question-suggestions",
    response_model=InterviewQuestionSuggestionResponse,
)
def interview_question_suggestions(
    requisition_id: int,
    payload: InterviewQuestionSuggestionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> InterviewQuestionSuggestionResponse:
    requisition = _requisition(db, requisition_id, user)
    return InterviewQuestionSuggestionResponse(
        requisition_id=requisition.id,
        job_title=requisition.title,
        suggestions=suggest_interview_questions(
            payload.personality_traits,
            requisition.title,
        ),
        guidance=(
            "請以與職務相關的實際行為與結果追問；人格特質僅用於安排提問，"
            "不應作為診斷或單獨的錄用依據。"
        ),
    )


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
        source="all",
        min_score=0,
        status=None,
        include_ineligible=False,
        limit=None,
        offset=0,
        db=db,
        user=user,
    )


@router.get("/requisitions/{requisition_id}/match-readiness")
def match_readiness(
    requisition_id: int,
    source: MatchSource = Query("all"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _requisition(db, requisition_id, user)
    statement = (
        select(MatchResult)
        .join(Candidate, Candidate.id == MatchResult.candidate_id)
        .where(
            MatchResult.requisition_id == requisition_id,
            *_candidate_conditions(user, requisition_id, source),
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
    _guard_status_transition(result, payload.status)
    now = datetime.now(UTC)
    result.status = payload.status
    result.stage_updated_by = user.id
    result.stage_updated_at = now
    result.feedback_by = user.id
    legacy_reason = (payload.reason or "").strip() or None
    note = (payload.note or "").strip() or legacy_reason
    result.feedback_category = payload.reason_category or ("other" if legacy_reason else None)
    result.feedback_note = note
    # Keep the original field populated for older clients and historical reports.
    result.feedback_reason = note or payload.reason_category
    result.feedback_at = now
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
    _guard_status_transition(result, payload.status)
    result.status = payload.status
    result.stage_updated_by = user.id
    result.stage_updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(result)
    return result


@router.post("/matches/{match_id}/manual-override", response_model=MatchRead)
def manual_override_match(
    match_id: int,
    payload: MatchManualOverride,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> MatchResult:
    """Document a human exception before advancing a failed system gate."""

    result = _match(db, match_id)
    _enforce_match_action_scope(db, result, user)
    if result.gate_passed:
        raise HTTPException(status_code=409, detail="This match already passes the system gate")
    if result.status == "hired":
        raise HTTPException(status_code=409, detail="A hired match is final")
    now = datetime.now(UTC)
    result.manual_override_category = payload.reason_category
    result.manual_override_note = (payload.note or "").strip() or None
    result.manual_override_by = user.id
    result.manual_override_at = now
    result.status = payload.target_stage
    result.stage_updated_by = user.id
    result.stage_updated_at = now
    write_audit(
        db,
        user,
        "matching.manual_override",
        "match_result",
        result.id,
        result.requisition.department_id,
        details={
            "gate_misses": (result.score_breakdown or {}).get("gate", {}).get("miss", []),
            "reason_category": payload.reason_category,
            "note": result.manual_override_note,
            "target_stage": payload.target_stage,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    db.refresh(result)
    return result
