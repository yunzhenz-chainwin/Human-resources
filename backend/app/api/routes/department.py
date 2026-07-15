from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import and_, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import require_department_manager
from app.models import (
    Candidate,
    Department,
    JobApplication,
    JobRequisition,
    MatchResult,
    User,
)
from app.schemas.hr import (
    CandidateRead,
    DepartmentApplicantRead,
    DepartmentJobWorkspaceRead,
    DepartmentRequisitionCreate,
    DepartmentWorkspaceRead,
    RequisitionRead,
)
from app.services.security import write_audit

router = APIRouter(prefix="/department")


def _clean_skills(skills: list[str]) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in skills if item.strip()))


def _validate_salary_range(salary_min: int | None, salary_max: int | None) -> None:
    if salary_min is not None and salary_max is not None and salary_max < salary_min:
        raise HTTPException(status_code=422, detail="salary_max 不可小於 salary_min")


def _get_owned_requisition(
    db: Session,
    user: User,
    requisition_id: int,
) -> JobRequisition:
    requisition = db.get(JobRequisition, requisition_id)
    if not requisition:
        raise HTTPException(status_code=404, detail="職缺不存在")
    if requisition.department_id != user.department_id:
        raise HTTPException(status_code=403, detail="Outside department scope")
    department = db.get(Department, user.department_id)
    if not department or not department.is_active:
        raise HTTPException(status_code=403, detail="Department is unavailable")
    return requisition


@router.post(
    "/requisitions",
    response_model=RequisitionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_department_requisition(
    payload: DepartmentRequisitionCreate,
    request: Request,
    user: User = Depends(require_department_manager),
    db: Session = Depends(get_db),
) -> JobRequisition:
    """Create a reviewable requisition locked to the manager's department."""

    department = db.get(Department, user.department_id)
    if not department or not department.is_active:
        raise HTTPException(status_code=403, detail="Department is unavailable")
    _validate_salary_range(payload.salary_min, payload.salary_max)

    req_no = (
        f"D{department.id:02d}-{datetime.now(UTC):%y%m%d}-"
        f"{uuid4().hex[:6].upper()}"
    )
    data = payload.model_dump()
    data["skills"] = _clean_skills(data["skills"])
    requisition = JobRequisition(
        **data,
        req_no=req_no,
        department_id=department.id,
        requested_by=user.id,
        status="submitted",
    )
    db.add(requisition)
    try:
        db.flush()
        write_audit(
            db,
            user,
            "department.requisition.create",
            "job_requisition",
            requisition.id,
            department.id,
            details={"req_no": req_no, "title": requisition.title},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="職缺編號重複，請重新送出") from exc
    db.refresh(requisition)
    return requisition


@router.put("/requisitions/{requisition_id}", response_model=RequisitionRead)
def update_department_requisition(
    requisition_id: int,
    payload: DepartmentRequisitionCreate,
    request: Request,
    user: User = Depends(require_department_manager),
    db: Session = Depends(get_db),
) -> JobRequisition:
    """Fully update editable details for a requisition in the manager's department."""

    requisition = _get_owned_requisition(db, user, requisition_id)
    _validate_salary_range(payload.salary_min, payload.salary_max)
    data = payload.model_dump()
    data["skills"] = _clean_skills(data["skills"])
    for field, value in data.items():
        setattr(requisition, field, value)
    write_audit(
        db,
        user,
        "department.requisition.update",
        "job_requisition",
        requisition.id,
        requisition.department_id,
        details={
            "req_no": requisition.req_no,
            "title": requisition.title,
            "fields": sorted(data),
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    db.refresh(requisition)
    return requisition


@router.delete(
    "/requisitions/{requisition_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_department_requisition(
    requisition_id: int,
    request: Request,
    user: User = Depends(require_department_manager),
    db: Session = Depends(get_db),
) -> None:
    """Delete an unused requisition in the manager's department."""

    requisition = _get_owned_requisition(db, user, requisition_id)
    application_id = db.scalar(
        select(JobApplication.id)
        .where(JobApplication.requisition_id == requisition.id)
        .limit(1)
    )
    if application_id is not None:
        raise HTTPException(status_code=409, detail="職缺已有應徵者，無法刪除")

    resource_id = requisition.id
    department_id = requisition.department_id
    audit_details = {"req_no": requisition.req_no, "title": requisition.title}
    try:
        # Keep deletion deterministic even where database-level cascades are disabled.
        db.execute(delete(MatchResult).where(MatchResult.requisition_id == resource_id))
        deleted = db.execute(
            delete(JobRequisition).where(
                JobRequisition.id == resource_id,
                ~select(JobApplication.id)
                .where(JobApplication.requisition_id == resource_id)
                .exists(),
            )
        )
        if deleted.rowcount != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail="職缺已有應徵者，無法刪除")
        write_audit(
            db,
            user,
            "department.requisition.delete",
            "job_requisition",
            resource_id,
            department_id,
            details=audit_details,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="職缺已有相依資料，無法刪除") from exc


@router.get("/workspace", response_model=DepartmentWorkspaceRead)
def department_workspace(
    user: User = Depends(require_department_manager),
    db: Session = Depends(get_db),
) -> DepartmentWorkspaceRead:
    """Return only this manager's jobs and people who applied to those jobs."""

    department = db.get(Department, user.department_id)
    if not department or not department.is_active:
        raise HTTPException(status_code=403, detail="Department is unavailable")

    requisitions = list(
        db.scalars(
            select(JobRequisition)
            .where(JobRequisition.department_id == department.id)
            .order_by(JobRequisition.updated_at.desc(), JobRequisition.id.desc())
        ).all()
    )
    grouped: dict[int, list[DepartmentApplicantRead]] = {
        requisition.id: [] for requisition in requisitions
    }
    if requisitions:
        rows = db.execute(
            select(JobApplication, Candidate, MatchResult)
            .join(Candidate, Candidate.id == JobApplication.candidate_id)
            .outerjoin(
                MatchResult,
                and_(
                    MatchResult.requisition_id == JobApplication.requisition_id,
                    MatchResult.candidate_id == JobApplication.candidate_id,
                ),
            )
            .where(
                JobApplication.requisition_id.in_(grouped),
                Candidate.deleted_at.is_(None),
            )
            .order_by(JobApplication.created_at.desc(), JobApplication.id.desc())
        ).all()
        for application, candidate, match in rows:
            grouped[application.requisition_id].append(
                DepartmentApplicantRead(
                    application_id=application.id,
                    application_status=application.status,
                    application_source=application.source,
                    applied_at=application.created_at,
                    match_score=float(match.total_score) if match else None,
                    match_status=match.status if match else None,
                    candidate=CandidateRead.model_validate(candidate),
                )
            )

    jobs = [
        DepartmentJobWorkspaceRead(
            requisition=RequisitionRead.model_validate(requisition),
            applicants=grouped[requisition.id],
        )
        for requisition in requisitions
    ]
    unique_candidates = {
        applicant.candidate.id for job in jobs for applicant in job.applicants
    }
    return DepartmentWorkspaceRead(
        department_id=department.id,
        department_name=department.name,
        total_jobs=len(jobs),
        total_applications=sum(len(job.applicants) for job in jobs),
        total_candidates=len(unique_candidates),
        jobs=jobs,
    )
