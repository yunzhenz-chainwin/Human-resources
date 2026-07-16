from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.db.session import get_db
from app.dependencies.auth import (
    GLOBAL_RECRUITING_ROLES,
    require_recruiting_manager,
    require_recruiting_user,
)
from app.models import Candidate, Department, JobApplication, JobRequisition, ResumeFile, User
from app.schemas.hr import (
    ApplicationAssignmentUpdate,
    ApplicationCreate,
    ApplicationInterviewStageRead,
    ApplicationInterviewUpdate,
    ApplicationRead,
    CandidateRead,
    InterviewStage,
    RequisitionRead,
)
from app.services.security import write_audit

router = APIRouter(prefix="/applications")

RESULT_APPLICATION_STATUSES = {
    "rejected": "rejected",
    "offered": "offered",
    "hired": "hired",
}
ASSIGNABLE_REQUISITION_STATUSES = frozenset(
    {"draft", "submitted", "returned", "approved", "sourcing", "interviewing"}
)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value


def _application_read(
    application: JobApplication,
    candidate: Candidate,
    requisition: JobRequisition,
) -> ApplicationRead:
    return ApplicationRead(
        id=application.id,
        candidate_id=application.candidate_id,
        requisition_id=application.requisition_id,
        status=application.status,
        source=application.source,
        applied_at=_aware(application.created_at),
        resume_id=application.resume_id,
        cover_letter=application.cover_letter,
        linkedin_url=application.linkedin_url,
        portfolio_url=application.portfolio_url,
        interview_at=_aware(application.interview_at),
        interview_result=application.interview_result,
        interview_notes=application.interview_notes,
        hr_interview=ApplicationInterviewStageRead(
            stage="hr",
            interview_at=_aware(application.hr_interview_at),
            interview_result=application.hr_interview_result,
            interview_notes=application.hr_interview_notes,
            updated_by=application.hr_interview_updated_by,
            updated_at=_aware(application.hr_interview_updated_at),
        ),
        manager_interview=ApplicationInterviewStageRead(
            stage="manager",
            interview_at=_aware(application.manager_interview_at),
            interview_result=application.manager_interview_result,
            interview_notes=application.manager_interview_notes,
            updated_by=application.manager_interview_updated_by,
            updated_at=_aware(application.manager_interview_updated_at),
        ),
        candidate=CandidateRead.model_validate(candidate),
        requisition=RequisitionRead.model_validate(requisition),
    )


def _application_row(
    db: Session,
    application_id: int,
) -> tuple[JobApplication, Candidate, JobRequisition]:
    row = db.execute(
        select(JobApplication, Candidate, JobRequisition)
        .join(Candidate, Candidate.id == JobApplication.candidate_id)
        .join(JobRequisition, JobRequisition.id == JobApplication.requisition_id)
        .where(JobApplication.id == application_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return row


def _assignment_requisition(db: Session, requisition_id: int) -> JobRequisition:
    requisition = db.get(JobRequisition, requisition_id)
    if requisition is None:
        raise HTTPException(status_code=404, detail="Requisition not found")
    if requisition.department_id is None:
        raise HTTPException(
            status_code=409,
            detail="Requisition must belong to an active department before assignment",
        )
    department = db.get(Department, requisition.department_id)
    if department is None or not department.is_active:
        raise HTTPException(
            status_code=409,
            detail="Requisition department is unavailable",
        )
    if requisition.status not in ASSIGNABLE_REQUISITION_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="Requisition is no longer available for candidate assignment",
        )
    return requisition


def _application_has_process_history(application: JobApplication) -> bool:
    interview_fields = (
        "interview_at",
        "interview_result",
        "interview_notes",
        "hr_interview_at",
        "hr_interview_result",
        "hr_interview_notes",
        "manager_interview_at",
        "manager_interview_result",
        "manager_interview_notes",
    )
    return application.status != "submitted" or any(
        getattr(application, field) is not None for field in interview_fields
    )


def _enforce_application_scope(user: User, requisition: JobRequisition) -> None:
    if user.role in GLOBAL_RECRUITING_ROLES:
        return
    if (
        user.role != "manager"
        or user.department_id is None
        or requisition.department_id != user.department_id
    ):
        raise HTTPException(status_code=403, detail="Outside department scope")


def _enforce_interview_stage_scope(
    user: User,
    requisition: JobRequisition,
    stage: InterviewStage,
) -> None:
    _enforce_application_scope(user, requisition)
    if stage == "hr":
        if user.role not in GLOBAL_RECRUITING_ROLES:
            raise HTTPException(status_code=403, detail="Only HR can update the first interview")
        return
    if user.role == "admin":
        return
    if user.role != "manager":
        raise HTTPException(
            status_code=403,
            detail="Only the department manager can update the second interview",
        )


def _stage_has_data(application: JobApplication, stage: InterviewStage) -> bool:
    return any(
        getattr(application, f"{stage}_{field}") is not None
        for field in ("interview_at", "interview_result", "interview_notes")
    )


def _sync_legacy_interview(application: JobApplication) -> None:
    """Keep the old single-interview fields useful for older clients."""
    display_stage: InterviewStage | None = None
    if _stage_has_data(application, "manager"):
        display_stage = "manager"
    elif _stage_has_data(application, "hr"):
        display_stage = "hr"
    if display_stage is None:
        application.interview_at = None
        application.interview_result = None
        application.interview_notes = None
        application.interview_updated_by = (
            application.manager_interview_updated_by
            or application.hr_interview_updated_by
        )
        return
    application.interview_at = getattr(application, f"{display_stage}_interview_at")
    application.interview_result = getattr(application, f"{display_stage}_interview_result")
    application.interview_notes = getattr(application, f"{display_stage}_interview_notes")
    application.interview_updated_by = getattr(
        application,
        f"{display_stage}_interview_updated_by",
    )


def _sync_application_status(application: JobApplication) -> None:
    # A terminal decision (offered/hired/rejected) from EITHER stage wins so a
    # non-terminal result in one stage never downgrades a finalized application
    # back to "interview". Manager keeps precedence when both stages are terminal.
    result_status = RESULT_APPLICATION_STATUSES.get(
        application.manager_interview_result or ""
    ) or RESULT_APPLICATION_STATUSES.get(application.hr_interview_result or "")
    if result_status is not None:
        application.status = result_status
    elif _stage_has_data(application, "hr") or _stage_has_data(application, "manager"):
        application.status = "interview"


@router.get("", response_model=list[ApplicationRead])
def list_applications(
    response: Response,
    department_id: int | None = Query(default=None, gt=0),
    requisition_id: int | None = Query(default=None, gt=0),
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> list[ApplicationRead]:
    if user.role == "manager":
        if user.department_id is None:
            raise HTTPException(status_code=403, detail="Outside department scope")
        if department_id is not None and department_id != user.department_id:
            raise HTTPException(status_code=403, detail="Outside department scope")
        if requisition_id is not None:
            filtered_requisition = db.get(JobRequisition, requisition_id)
            if filtered_requisition is None:
                raise HTTPException(status_code=404, detail="Requisition not found")
            _enforce_application_scope(user, filtered_requisition)

    conditions = [Candidate.deleted_at.is_(None)]
    if user.role == "manager":
        conditions.append(JobRequisition.department_id == user.department_id)
    if department_id is not None:
        conditions.append(JobRequisition.department_id == department_id)
    if requisition_id is not None:
        conditions.append(JobApplication.requisition_id == requisition_id)

    # Expose the full filtered size via a header so the bare-list body stays
    # backward compatible while clients can still page with limit/offset.
    total = int(
        db.scalar(
            select(func.count(JobApplication.id))
            .join(Candidate, Candidate.id == JobApplication.candidate_id)
            .join(JobRequisition, JobRequisition.id == JobApplication.requisition_id)
            .where(*conditions)
        )
        or 0
    )
    response.headers["X-Total-Count"] = str(total)

    statement = (
        select(JobApplication, Candidate, JobRequisition)
        .join(Candidate, Candidate.id == JobApplication.candidate_id)
        .join(JobRequisition, JobRequisition.id == JobApplication.requisition_id)
        .options(joinedload(JobRequisition.department))
        .where(*conditions)
        .order_by(JobApplication.created_at.desc(), JobApplication.id.desc())
    )
    if offset:
        statement = statement.offset(offset)
    if limit is not None:
        statement = statement.limit(limit)
    return [
        _application_read(application, candidate, requisition)
        for application, candidate, requisition in db.execute(statement).all()
    ]


@router.post("", response_model=ApplicationRead, status_code=status.HTTP_201_CREATED)
def create_application(
    payload: ApplicationCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_manager),
) -> ApplicationRead:
    candidate = db.get(Candidate, payload.candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    if candidate.deleted_at is not None:
        raise HTTPException(status_code=409, detail="Deleted candidate cannot be assigned")
    requisition = _assignment_requisition(db, payload.requisition_id)
    existing_id = db.scalar(
        select(JobApplication.id).where(
            JobApplication.requisition_id == requisition.id,
            JobApplication.candidate_id == candidate.id,
        )
    )
    if existing_id is not None:
        raise HTTPException(status_code=409, detail="Candidate is already assigned to this job")

    application = JobApplication(
        candidate_id=candidate.id,
        requisition_id=requisition.id,
        status="submitted",
        source="manual_hr",
    )
    db.add(application)
    try:
        db.flush()
        write_audit(
            db,
            user,
            "application.assign",
            "job_application",
            application.id,
            requisition.department_id,
            details={
                "candidate_id": candidate.id,
                "requisition_id": requisition.id,
                "source": application.source,
            },
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Candidate is already assigned to this job",
        ) from exc
    db.refresh(application)
    return _application_read(application, candidate, requisition)


@router.patch("/{application_id}/assignment", response_model=ApplicationRead)
def update_application_assignment(
    application_id: int,
    payload: ApplicationAssignmentUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_manager),
) -> ApplicationRead:
    """Correct the job/department routing for an existing candidate application."""

    application, candidate, current_requisition = _application_row(db, application_id)
    target_requisition = _assignment_requisition(db, payload.requisition_id)
    if application.requisition_id == target_requisition.id:
        return _application_read(application, candidate, current_requisition)
    if _application_has_process_history(application):
        raise HTTPException(
            status_code=409,
            detail=(
                "Applications with interview or hiring history cannot be reassigned; "
                "create a new assignment instead"
            ),
        )

    duplicate_id = db.scalar(
        select(JobApplication.id).where(
            JobApplication.id != application.id,
            JobApplication.candidate_id == candidate.id,
            JobApplication.requisition_id == target_requisition.id,
        )
    )
    if duplicate_id is not None:
        raise HTTPException(status_code=409, detail="Candidate is already assigned to this job")

    previous_requisition_id = application.requisition_id
    previous_department_id = current_requisition.department_id
    reassigned_resumes = {
        resume.id: resume
        for resume in db.scalars(
            select(ResumeFile).where(
                ResumeFile.candidate_id == candidate.id,
                ResumeFile.target_requisition_id == current_requisition.id,
            )
        )
    }
    linked_resume = db.get(ResumeFile, application.resume_id) if application.resume_id else None
    if linked_resume is not None and linked_resume.candidate_id not in (None, candidate.id):
        raise HTTPException(status_code=409, detail="Application resume linkage is inconsistent")
    if linked_resume is not None:
        reassigned_resumes[linked_resume.id] = linked_resume
    application.requisition_id = target_requisition.id
    for resume in reassigned_resumes.values():
        resume.target_requisition_id = target_requisition.id
    reassigned_resume_ids = sorted(reassigned_resumes)
    try:
        db.flush()
        write_audit(
            db,
            user,
            "application.reassign",
            "job_application",
            application.id,
            target_requisition.department_id,
            details={
                "candidate_id": candidate.id,
                "previous_requisition_id": previous_requisition_id,
                "requisition_id": target_requisition.id,
                "previous_department_id": previous_department_id,
                "department_id": target_requisition.department_id,
                "resume_id": linked_resume.id if linked_resume is not None else None,
                "resume_ids": reassigned_resume_ids,
            },
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Candidate is already assigned to this job",
        ) from exc
    db.refresh(application)
    return _application_read(application, candidate, target_requisition)


def _update_interview_stage(
    application_id: int,
    stage: InterviewStage,
    payload: ApplicationInterviewUpdate,
    request: Request,
    db: Session,
    user: User,
) -> ApplicationRead:
    application, candidate, requisition = _application_row(db, application_id)
    _enforce_interview_stage_scope(user, requisition, stage)
    updates = payload.model_dump(exclude_unset=True)
    previous_status = application.status
    previous_result = getattr(application, f"{stage}_interview_result")
    previous_interview_at = getattr(application, f"{stage}_interview_at")

    if "interview_at" in updates and updates["interview_at"] is not None:
        updates["interview_at"] = updates["interview_at"].astimezone(UTC)
    if "interview_notes" in updates and updates["interview_notes"] is not None:
        clean_notes = updates["interview_notes"].strip()
        updates["interview_notes"] = clean_notes or None
    for field, value in updates.items():
        setattr(application, f"{stage}_{field}", value)
    setattr(application, f"{stage}_interview_updated_by", user.id)
    setattr(application, f"{stage}_interview_updated_at", datetime.now(UTC))
    _sync_legacy_interview(application)
    _sync_application_status(application)

    write_audit(
        db,
        user,
        f"application.interview.{stage}.update",
        "job_application",
        application.id,
        requisition.department_id,
        details={
            "stage": stage,
            "fields": sorted(updates),
            "status": {"from": previous_status, "to": application.status},
            "interview_result": {
                "from": previous_result,
                "to": getattr(application, f"{stage}_interview_result"),
            },
            "interview_at": {
                "from": _aware(previous_interview_at).isoformat()
                if previous_interview_at
                else None,
                "to": _aware(getattr(application, f"{stage}_interview_at")).isoformat()
                if getattr(application, f"{stage}_interview_at")
                else None,
            },
            "notes_changed": "interview_notes" in updates,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    db.refresh(application)
    return _application_read(application, candidate, requisition)


@router.patch("/{application_id}/interviews/{stage}", response_model=ApplicationRead)
def update_application_interview_stage(
    application_id: int,
    stage: InterviewStage,
    payload: ApplicationInterviewUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> ApplicationRead:
    return _update_interview_stage(application_id, stage, payload, request, db, user)


@router.patch("/{application_id}/interview", response_model=ApplicationRead)
def update_application_interview(
    application_id: int,
    payload: ApplicationInterviewUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> ApplicationRead:
    """Backward-compatible endpoint; routes each role to its owned interview stage."""
    stage: InterviewStage = "manager" if user.role == "manager" else "hr"
    return _update_interview_stage(application_id, stage, payload, request, db, user)
