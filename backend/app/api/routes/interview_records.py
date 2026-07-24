from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import enforce_department_scope, require_recruiting_user
from app.models import (
    Candidate,
    CandidateExperience,
    CandidateSkill,
    InterviewRecord,
    JobApplication,
    JobRequisition,
    User,
)
from app.schemas.interview_questions import (
    InterviewQuestionPlanResponse,
    InterviewQuestionSuggestionRequest,
    InterviewQuestionSuggestionResponse,
)
from app.schemas.interviews import (
    InterviewRecordCreate,
    InterviewRecordRead,
    InterviewRecordUpdate,
    InterviewStage,
)
from app.services.interview_questions import (
    personalized_manager_question_plan,
    personalized_trait_interview_questions,
    standard_hr_question_plan,
)
from app.services.security import write_audit

router = APIRouter(prefix="/applications")


def _application_requisition(
    db: Session,
    application_id: int,
    user: User,
) -> tuple[JobApplication, JobRequisition]:
    row = db.execute(
        select(JobApplication, JobRequisition)
        .join(JobRequisition, JobRequisition.id == JobApplication.requisition_id)
        .where(JobApplication.id == application_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Application not found")
    application, requisition = row
    enforce_department_scope(user, requisition.department_id)
    return application, requisition


def _enforce_stage_write(user: User, stage: InterviewStage) -> None:
    if stage == "hr":
        if user.role not in {"admin", "hr"}:
            raise HTTPException(status_code=403, detail="Only HR can record the HR interview")
        return
    if user.role not in {"admin", "manager"}:
        raise HTTPException(
            status_code=403,
            detail="Only the department manager can record the manager interview",
        )


def _enforce_private_notes_write(
    user: User,
    stage: InterviewStage,
    fields_set: set[str],
) -> None:
    if "private_notes" not in fields_set:
        return
    if stage != "hr" or user.role not in {"admin", "hr"}:
        raise HTTPException(
            status_code=403,
            detail="HR private notes can only be maintained by HR",
        )


def _owns_stage(user: User, stage: str) -> bool:
    return user.role == "admin" or (
        (stage == "hr" and user.role == "hr") or (stage == "manager" and user.role == "manager")
    )


def _peer_evaluations_released(records: list[InterviewRecord]) -> bool:
    latest: dict[str, InterviewRecord] = {}
    for record in records:
        latest.setdefault(record.stage, record)
    return all(
        latest.get(stage) is not None and latest[stage].status == "completed"
        for stage in ("hr", "manager")
    )


def _record_read(
    record: InterviewRecord,
    user: User,
    peer_evaluations_released: bool,
) -> InterviewRecordRead:
    result = InterviewRecordRead.model_validate(record)
    evaluation_revealed = _owns_stage(user, record.stage) or peer_evaluations_released
    private_notes_visible = user.role == "admin" or (user.role == "hr" and record.stage == "hr")
    updates: dict[str, object] = {
        "evaluation_revealed": evaluation_revealed,
        "private_notes_visible": private_notes_visible,
        "private_notes": result.private_notes if private_notes_visible else None,
    }
    if not evaluation_revealed:
        updates.update(
            questions=[
                question.model_copy(update={"rating": None, "notes": None})
                for question in result.questions
            ],
            summary=None,
            recommendation=None,
            overall_rating=None,
        )
    return result.model_copy(update=updates)


def _application_records(db: Session, application_id: int) -> list[InterviewRecord]:
    return list(
        db.scalars(
            select(InterviewRecord)
            .where(InterviewRecord.application_id == application_id)
            .order_by(
                InterviewRecord.interviewed_at.desc(),
                InterviewRecord.id.desc(),
            )
        ).all()
    )


def _record(db: Session, application_id: int, record_id: int) -> InterviewRecord:
    record = db.scalar(
        select(InterviewRecord).where(
            InterviewRecord.id == record_id,
            InterviewRecord.application_id == application_id,
        )
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Interview record not found")
    return record


def _actor_name(user: User) -> str:
    return user.display_name.strip() or user.username


def _candidate_resume_context(
    db: Session,
    candidate_id: int,
) -> tuple[list[str], list[dict[str, object | None]]]:
    skills = list(
        db.scalars(
            select(CandidateSkill.skill)
            .where(CandidateSkill.candidate_id == candidate_id)
            .order_by(CandidateSkill.id)
        ).all()
    )
    experiences = [
        {
            "company": item.company,
            "title": item.title,
            "description": item.description,
        }
        for item in db.scalars(
            select(CandidateExperience)
            .where(CandidateExperience.candidate_id == candidate_id)
            .order_by(CandidateExperience.sort_order, CandidateExperience.id)
        ).all()
    ]
    return skills, experiences


@router.get(
    "/{application_id}/interview-question-plan",
    response_model=InterviewQuestionPlanResponse,
)
def interview_question_plan(
    application_id: int,
    stage: InterviewStage = Query(),
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> InterviewQuestionPlanResponse:
    application, requisition = _application_requisition(db, application_id, user)
    candidate = db.get(Candidate, application.candidate_id)
    if candidate is None or candidate.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Candidate not found")

    if stage == "hr":
        questions = standard_hr_question_plan()
        basis = ["全公司 HR 固定題庫（不因職位或個人背景改變）"]
        guidance = "HR 請依固定五題完成一致的初談紀錄，避免使用與工作無關的個人條件評估。"
    else:
        skills, experiences = _candidate_resume_context(db, candidate.id)
        questions, basis = personalized_manager_question_plan(
            job_title=requisition.title,
            current_title=candidate.current_title,
            total_years=candidate.total_years,
            candidate_skills=skills,
            required_skills=requisition.skills or [],
            experiences=experiences,
        )
        guidance = (
            "主管題目依應徵職位與目前履歷資料產生；請以實際行為與成果追問，"
            "若背景資料不完整，面試時應先向候選人確認。"
        )
    return InterviewQuestionPlanResponse(
        application_id=application.id,
        stage=stage,
        job_title=requisition.title,
        questions=questions,
        personalization_basis=basis,
        guidance=guidance,
    )


@router.post(
    "/{application_id}/interview-question-suggestions",
    response_model=InterviewQuestionSuggestionResponse,
)
def application_interview_question_suggestions(
    application_id: int,
    payload: InterviewQuestionSuggestionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> InterviewQuestionSuggestionResponse:
    application, requisition = _application_requisition(db, application_id, user)
    candidate = db.get(Candidate, application.candidate_id)
    if candidate is None or candidate.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    skills, experiences = _candidate_resume_context(db, candidate.id)
    suggestions, basis = personalized_trait_interview_questions(
        payload.personality_traits,
        requisition.title,
        current_title=candidate.current_title,
        total_years=candidate.total_years,
        highest_education=candidate.highest_education,
        expected_title=candidate.expected_title,
        candidate_skills=skills,
        required_skills=requisition.skills or [],
        experiences=experiences,
    )
    return InterviewQuestionSuggestionResponse(
        application_id=application.id,
        requisition_id=requisition.id,
        job_title=requisition.title,
        suggestions=suggestions,
        personalization_basis=basis,
        guidance=(
            "問題已結合這位候選人的職務履歷、所選人格特質與應徵職位。"
            "請先確認履歷事實，再以實際行為與成果追問；人格特質不可作為診斷或單獨錄用依據。"
        ),
    )


@router.get(
    "/{application_id}/interview-records",
    response_model=list[InterviewRecordRead],
)
def list_interview_records(
    application_id: int,
    stage: InterviewStage | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> list[InterviewRecordRead]:
    _application_requisition(db, application_id, user)
    records = _application_records(db, application_id)
    evaluations_released = _peer_evaluations_released(records)
    return [
        _record_read(record, user, evaluations_released)
        for record in records
        if stage is None or record.stage == stage
    ]


@router.post(
    "/{application_id}/interview-records",
    response_model=InterviewRecordRead,
    status_code=status.HTTP_201_CREATED,
)
def create_interview_record(
    application_id: int,
    payload: InterviewRecordCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> InterviewRecordRead:
    _, requisition = _application_requisition(db, application_id, user)
    _enforce_stage_write(user, payload.stage)
    _enforce_private_notes_write(user, payload.stage, payload.model_fields_set)
    actor_name = _actor_name(user)
    record = InterviewRecord(
        application_id=application_id,
        stage=payload.stage,
        interviewed_at=payload.interviewed_at.astimezone(UTC),
        duration_minutes=payload.duration_minutes,
        mode=payload.mode,
        status=payload.status,
        questions=[item.model_dump() for item in payload.questions],
        summary=payload.summary,
        private_notes=payload.private_notes,
        recommendation=payload.recommendation,
        overall_rating=payload.overall_rating,
        interviewer_id=user.id,
        interviewer_name=actor_name,
        updated_by_id=user.id,
        updated_by_name=actor_name,
    )
    db.add(record)
    db.flush()
    write_audit(
        db,
        user,
        "application.interview_record.create",
        "interview_record",
        record.id,
        requisition.department_id,
        details={
            "application_id": application_id,
            "stage": record.stage,
            "status": record.status,
            "question_count": len(record.questions),
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    db.refresh(record)
    records = _application_records(db, application_id)
    return _record_read(record, user, _peer_evaluations_released(records))


@router.get(
    "/{application_id}/interview-records/{record_id}",
    response_model=InterviewRecordRead,
)
def get_interview_record(
    application_id: int,
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> InterviewRecordRead:
    _application_requisition(db, application_id, user)
    record = _record(db, application_id, record_id)
    records = _application_records(db, application_id)
    return _record_read(record, user, _peer_evaluations_released(records))


@router.patch(
    "/{application_id}/interview-records/{record_id}",
    response_model=InterviewRecordRead,
)
def update_interview_record(
    application_id: int,
    record_id: int,
    payload: InterviewRecordUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> InterviewRecordRead:
    _, requisition = _application_requisition(db, application_id, user)
    record = _record(db, application_id, record_id)
    _enforce_stage_write(user, record.stage)  # type: ignore[arg-type]
    _enforce_private_notes_write(
        user,
        record.stage,  # type: ignore[arg-type]
        payload.model_fields_set,
    )
    updates = payload.model_dump(exclude_unset=True)
    if updates.get("interviewed_at") is not None:
        updates["interviewed_at"] = updates["interviewed_at"].astimezone(UTC)
    if updates.get("questions") is not None:
        updates["questions"] = [item.model_dump() for item in updates["questions"]]
    previous_status = record.status
    for field, value in updates.items():
        setattr(record, field, value)
    record.updated_by_id = user.id
    record.updated_by_name = _actor_name(user)
    write_audit(
        db,
        user,
        "application.interview_record.update",
        "interview_record",
        record.id,
        requisition.department_id,
        details={
            "application_id": application_id,
            "stage": record.stage,
            "fields": sorted(updates),
            "status": {"from": previous_status, "to": record.status},
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    db.refresh(record)
    records = _application_records(db, application_id)
    return _record_read(record, user, _peer_evaluations_released(records))
