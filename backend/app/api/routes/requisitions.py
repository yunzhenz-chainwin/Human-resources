from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.db.session import get_db
from app.dependencies.auth import (
    enforce_department_scope,
    get_current_user,
    require_recruiting_manager,
    require_recruiting_user,
)
from app.models import JobRequisition, User
from app.schemas.hr import (
    ALLOWED_REQUISITION_TRANSITIONS,
    REQUISITION_STATUSES,
    RequisitionCreate,
    RequisitionRead,
    RequisitionUpdate,
)
from app.schemas.matching import (
    JobComplianceLintRequest,
    JobComplianceResult,
)
from app.services.interview_scoring import (
    recompute_requisition_composite_scores,
    resolve_composite_weights,
)
from app.services.jd_compliance import JD_COMPLIANCE_RULES_VERSION, lint_job_text
from app.services.security import write_audit

router = APIRouter(prefix="/requisitions")

# Statuses whose entry means the requisition is published; the first of these to
# be reached stamps published_at.
_PUBLISHED_STATUSES = frozenset({"approved", "sourcing", "interviewing"})

# Upper bound for an explicitly requested page size.
_MAX_PAGE_SIZE = 200

# The rule a requisition gets when nobody decides one: blind review on. Mirrors
# JobRequisition.blind_review_enabled's column default, which is what actually
# writes the row; the create path needs the value up front to tell a real decision
# apart from a client restating the default. The two cannot drift silently -- the
# create tests pin both ends, since a create with no flag must come back blind and
# a non-HR caller restating that same default must not be refused.
DEFAULT_BLIND_REVIEW_ENABLED = True


def _apply_status_timestamps(requisition: JobRequisition, new_status: str) -> None:
    """Stamp workflow timestamps as a requisition enters ``new_status``.

    Only empty columns are filled, so re-entering a status keeps the original
    timestamp. Writing filled_at here is what makes the time-to-fill report work.
    """
    now = datetime.now(UTC)
    if new_status == "approved" and requisition.approved_at is None:
        requisition.approved_at = now
    if new_status in _PUBLISHED_STATUSES and requisition.published_at is None:
        requisition.published_at = now
    if new_status == "filled" and requisition.filled_at is None:
        requisition.filled_at = now
    if new_status == "closed" and requisition.closed_at is None:
        requisition.closed_at = now


@router.get("", response_model=list[RequisitionRead])
def list_requisitions(
    response: Response,
    requisition_status: str | None = Query(None, alias="status"),
    limit: int | None = Query(None, ge=1, le=_MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[JobRequisition]:
    filters = []
    if user.role == "manager":
        filters.append(JobRequisition.department_id == user.department_id)
    if requisition_status:
        filters.append(JobRequisition.status == requisition_status)
    count_stmt = select(func.count(JobRequisition.id))
    query = (
        select(JobRequisition)
        .options(joinedload(JobRequisition.department))
        .order_by(JobRequisition.updated_at.desc())
    )
    if filters:
        count_stmt = count_stmt.where(*filters)
        query = query.where(*filters)
    total = db.scalar(count_stmt) or 0
    query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
    response.headers["X-Total-Count"] = str(total)
    return list(db.scalars(query).all())


@router.post("", response_model=RequisitionRead, status_code=status.HTTP_201_CREATED)
def create_requisition(
    payload: RequisitionCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_manager),
) -> JobRequisition:
    enforce_department_scope(user, payload.department_id)
    data = payload.model_dump()
    # The column is NOT NULL, so an explicit null carries no decision at all and the
    # model default has to stay in charge -- same handling as the PATCH path.
    requested_blind_review = data.pop("blind_review_enabled", None)
    # Only a real decision is policed, exactly as on PATCH: a new requisition starts
    # blind, so a client that posts the whole form and restates that default decides
    # nothing and must not 403. The PATCH lock rule has nothing to apply to here --
    # blind_review_locked is derived from submitted interviews, and a requisition
    # that does not exist yet has no applications and therefore no interviews (the
    # create tests assert the flag comes back unlocked).
    blind_review_change = (
        requested_blind_review is not None
        and requested_blind_review != DEFAULT_BLIND_REVIEW_ENABLED
    )
    if blind_review_change and user.role != "hr":
        raise HTTPException(status_code=403, detail="僅人資可設定面試評分揭露規則")
    if requested_blind_review is not None:
        data["blind_review_enabled"] = requested_blind_review
    if data["status"] not in REQUISITION_STATUSES:
        raise HTTPException(status_code=422, detail="未知的需求單狀態")
    if data["status"] not in {"draft", "submitted"}:
        raise HTTPException(
            status_code=422,
            detail="新需求單僅能以草稿或待審核狀態建立，發佈請改用核准流程",
        )
    if (
        data["salary_min"] is not None
        and data["salary_max"] is not None
        and data["salary_max"] < data["salary_min"]
    ):
        raise HTTPException(status_code=422, detail="salary_max 不可小於 salary_min")
    requisition = JobRequisition(**data)
    db.add(requisition)
    try:
        # Flush first so the audit below can reference the new id, and so a duplicate
        # req_no still surfaces as the same 409 it always did.
        db.flush()
        if blind_review_change:
            # Opening a requisition already un-blinded is the same decision as
            # relaxing it later, and stays attributable the same way.
            write_audit(
                db,
                user,
                "requisition.blind_review.update",
                "job_requisition",
                requisition.id,
                requisition.department_id,
                details={
                    "req_no": requisition.req_no,
                    "blind_review_enabled": {
                        # "from" is the default a new requisition would have had;
                        # there is no earlier stored value to report.
                        "from": DEFAULT_BLIND_REVIEW_ENABLED,
                        "to": requisition.blind_review_enabled,
                    },
                    "on_create": True,
                },
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="需求單號重複或關聯資料不存在") from exc
    db.refresh(requisition)
    return requisition


@router.post("/lint", response_model=JobComplianceResult)
def lint_requisition_text(
    payload: JobComplianceLintRequest,
    user: User = Depends(require_recruiting_user),
) -> JobComplianceResult:
    """Preview anti-discrimination lint for requisition text without saving.

    Scans title/summary/JD for wording that likely violates 就服法 §5 and the
    related age / gender-equality statutes, and returns rewrite suggestions.
    Findings are advisory (``warning``) and never block creating/editing a
    requisition. Declared above ``/{requisition_id}`` so the literal ``lint``
    segment is not captured as a requisition id.
    """
    result = lint_job_text(
        title=payload.title,
        summary=payload.summary,
        jd=payload.jd,
    )
    return JobComplianceResult(
        status=result["status"],
        findings=result["findings"],
        rules_version=JD_COMPLIANCE_RULES_VERSION,
    )


@router.get("/{requisition_id}", response_model=RequisitionRead)
def get_requisition(
    requisition_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JobRequisition:
    requisition = db.get(JobRequisition, requisition_id)
    if not requisition:
        raise HTTPException(status_code=404, detail="職缺不存在")
    enforce_department_scope(user, requisition.department_id)
    return requisition


@router.patch("/{requisition_id}", response_model=RequisitionRead)
def update_requisition(
    requisition_id: int,
    payload: RequisitionUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_manager),
) -> JobRequisition:
    requisition = db.get(JobRequisition, requisition_id)
    if not requisition:
        raise HTTPException(status_code=404, detail="職缺不存在")
    enforce_department_scope(user, requisition.department_id)
    updates = payload.model_dump(exclude_unset=True)
    # The column is NOT NULL, so an explicit null carries no decision at all.
    if updates.get("blind_review_enabled") is None:
        updates.pop("blind_review_enabled", None)
    # Only a real change is policed: clients that re-send the whole requisition must
    # keep working, and re-stating the current rule decides nothing.
    blind_review_change = (
        "blind_review_enabled" in updates
        and updates["blind_review_enabled"] != requisition.blind_review_enabled
    )
    if blind_review_change:
        if user.role != "hr":
            raise HTTPException(status_code=403, detail="僅人資可設定面試評分揭露規則")
        if requisition.blind_review_locked:
            raise HTTPException(
                status_code=409,
                detail="已有面試提交紀錄，評分揭露規則不可變更",
            )
    # Same "only a real change is policed" rule as blind review above, compared on
    # the normalised weights rather than the raw dict: re-sending the whole
    # requisition, or restating the same split written differently (20/15/25/15/25
    # and 40/30/50/30/50 weigh identically), decides nothing and must not 403.
    # Unlike blind review this has no lock: a real change re-derives the composites
    # already stored here (see below), so the setting stays editable at any time.
    previous_weights = requisition.composite_score_weights
    previous_resolved_weights = requisition.composite_score_weights_resolved
    composite_weights_change = "composite_score_weights" in updates and (
        resolve_composite_weights(updates["composite_score_weights"])
        != previous_resolved_weights
    )
    if not composite_weights_change:
        updates.pop("composite_score_weights", None)
    elif user.role != "hr":
        raise HTTPException(status_code=403, detail="僅人資可設定綜合評分權重")
    previous_blind_review = requisition.blind_review_enabled
    new_status = updates.get("status")
    if new_status is not None and new_status not in REQUISITION_STATUSES:
        raise HTTPException(status_code=422, detail="未知的需求單狀態")
    transitioning = new_status is not None and new_status != requisition.status
    if transitioning and new_status not in ALLOWED_REQUISITION_TRANSITIONS.get(
        requisition.status, frozenset()
    ):
        raise HTTPException(
            status_code=409,
            detail=f"需求單狀態不可由「{requisition.status}」變更為「{new_status}」",
        )
    salary_min = updates.get("salary_min", requisition.salary_min)
    salary_max = updates.get("salary_max", requisition.salary_max)
    if salary_min is not None and salary_max is not None and salary_max < salary_min:
        raise HTTPException(status_code=422, detail="salary_max 不可小於 salary_min")
    for field, value in updates.items():
        setattr(requisition, field, value)
    if transitioning:
        _apply_status_timestamps(requisition, new_status)
    if blind_review_change:
        # Who relaxed or restored blind review, and when, has to stay attributable:
        # the audit log is this project's record of that everywhere else too.
        write_audit(
            db,
            user,
            "requisition.blind_review.update",
            "job_requisition",
            requisition.id,
            requisition.department_id,
            details={
                "req_no": requisition.req_no,
                "blind_review_enabled": {
                    "from": previous_blind_review,
                    "to": requisition.blind_review_enabled,
                },
            },
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    if composite_weights_change:
        # Reweighting changes how every candidate on this requisition ranks, so who
        # changed it and to what has to stay attributable, same as above.
        #
        # It also re-derives the composites already stored here, rather than leaving
        # them on the weights they were first computed with. HR asked for the number
        # on screen to follow the setting, and a list where some candidates carry the
        # old split and some the new one cannot be ranked at all. What the composites
        # were before the change is not lost -- recomputed_applications below records
        # every one that moved, which keeps the old snapshot auditable without
        # freezing it into the ranking.
        recomputed_applications = recompute_requisition_composite_scores(db, requisition)
        write_audit(
            db,
            user,
            "requisition.composite_score_weights.update",
            "job_requisition",
            requisition.id,
            requisition.department_id,
            details={
                "req_no": requisition.req_no,
                "composite_score_weights": {
                    "from": previous_weights,
                    "to": requisition.composite_score_weights,
                },
                "resolved_weights": {
                    "from": previous_resolved_weights,
                    "to": requisition.composite_score_weights_resolved,
                },
                "recomputed_applications": recomputed_applications,
            },
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    db.commit()
    db.refresh(requisition)
    return requisition


@router.post("/{requisition_id}/approve", response_model=RequisitionRead)
def approve_requisition(
    requisition_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_manager),
) -> JobRequisition:
    requisition = db.get(JobRequisition, requisition_id)
    if not requisition:
        raise HTTPException(status_code=404, detail="職缺不存在")
    enforce_department_scope(user, requisition.department_id)
    if "approved" not in ALLOWED_REQUISITION_TRANSITIONS.get(requisition.status, frozenset()):
        raise HTTPException(status_code=409, detail="此狀態不可核准")
    requisition.status = "approved"
    _apply_status_timestamps(requisition, "approved")
    db.commit()
    db.refresh(requisition)
    return requisition
