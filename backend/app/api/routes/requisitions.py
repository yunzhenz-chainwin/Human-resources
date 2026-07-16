from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.db.session import get_db
from app.dependencies.auth import (
    enforce_department_scope,
    get_current_user,
    require_recruiting_manager,
)
from app.models import JobRequisition, User
from app.schemas.hr import (
    REQUISITION_STATUSES,
    RequisitionCreate,
    RequisitionRead,
    RequisitionUpdate,
)

router = APIRouter(prefix="/requisitions")


@router.get("", response_model=list[RequisitionRead])
def list_requisitions(
    requisition_status: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[JobRequisition]:
    query = (
        select(JobRequisition)
        .options(joinedload(JobRequisition.department))
        .order_by(JobRequisition.updated_at.desc())
    )
    if user.role == "manager":
        query = query.where(JobRequisition.department_id == user.department_id)
    if requisition_status:
        query = query.where(JobRequisition.status == requisition_status)
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
    if "status" in updates and updates["status"] not in REQUISITION_STATUSES:
        raise HTTPException(status_code=422, detail="未知的需求單狀態")
    salary_min = updates.get("salary_min", requisition.salary_min)
    salary_max = updates.get("salary_max", requisition.salary_max)
    if salary_min is not None and salary_max is not None and salary_max < salary_min:
        raise HTTPException(status_code=422, detail="salary_max 不可小於 salary_min")
    for field, value in updates.items():
        setattr(requisition, field, value)
    if "status" in updates and updates["status"] in {"approved", "sourcing", "interviewing"}:
        requisition.published_at = requisition.published_at or datetime.now(UTC)
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
    if requisition.status not in {"draft", "submitted", "returned"}:
        raise HTTPException(status_code=409, detail="此狀態不可核准")
    requisition.status = "approved"
    requisition.approved_at = datetime.now(UTC)
    requisition.published_at = requisition.published_at or datetime.now(UTC)
    db.commit()
    db.refresh(requisition)
    return requisition
