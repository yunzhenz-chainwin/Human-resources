from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
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
from app.services.jd_compliance import JD_COMPLIANCE_RULES_VERSION, lint_job_text

router = APIRouter(prefix="/requisitions")

# Statuses whose entry means the requisition is published; the first of these to
# be reached stamps published_at.
_PUBLISHED_STATUSES = frozenset({"approved", "sourcing", "interviewing"})

# Upper bound for an explicitly requested page size.
_MAX_PAGE_SIZE = 200


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
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_manager),
) -> JobRequisition:
    enforce_department_scope(user, payload.department_id)
    data = payload.model_dump()
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
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_manager),
) -> JobRequisition:
    requisition = db.get(JobRequisition, requisition_id)
    if not requisition:
        raise HTTPException(status_code=404, detail="職缺不存在")
    enforce_department_scope(user, requisition.department_id)
    updates = payload.model_dump(exclude_unset=True)
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
