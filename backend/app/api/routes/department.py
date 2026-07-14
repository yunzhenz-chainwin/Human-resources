from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import and_, select
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
    if (
        payload.salary_min is not None
        and payload.salary_max is not None
        and payload.salary_max < payload.salary_min
    ):
        raise HTTPException(status_code=422, detail="salary_max 不可小於 salary_min")

    req_no = (
        f"D{department.id:02d}-{datetime.now(UTC):%y%m%d}-"
        f"{uuid4().hex[:6].upper()}"
    )
    data = payload.model_dump()
    data["skills"] = list(
        dict.fromkeys(item.strip() for item in data["skills"] if item.strip())
    )
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
