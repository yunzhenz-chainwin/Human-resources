import hashlib
import json
import threading
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.dependencies.auth import enforce_department_scope, require_recruiting_user
from app.models import (
    Candidate,
    CandidateExperience,
    CandidateSkill,
    InterviewQuestionPlan,
    InterviewRecord,
    JobApplication,
    JobRequisition,
    User,
)
from app.schemas.interview_questions import (
    InterviewQuestionPlanItem,
    InterviewQuestionPlanResponse,
    InterviewQuestionSuggestionRequest,
    InterviewQuestionSuggestionResponse,
)
from app.schemas.interviews import (
    InterviewRecordCreate,
    InterviewRecordQuestion,
    InterviewRecordRead,
    InterviewRecordReopenRequest,
    InterviewRecordUpdate,
    InterviewStage,
    validate_completed_evaluation,
)
from app.services.interview_questions import (
    HR_QUESTION_CATEGORIES,
    HR_QUESTION_PROMPT_VERSION,
    MANAGER_QUESTION_CATEGORIES,
    MANAGER_QUESTION_PROMPT_VERSION,
    annotate_question_compliance,
    gemini_hr_question_plan,
    gemini_manager_question_plan,
    gemini_question_replacement,
    personalized_trait_interview_questions,
    standard_hr_question_plan,
)
from app.services.interview_scoring import (
    application_interview_records,
    both_stages_submitted,
    recompute_application_composite_score,
)
from app.services.security import client_ip, write_audit

router = APIRouter(prefix="/applications")

_QUESTION_GENERATION_LOCKS = tuple(threading.Lock() for _ in range(64))


@contextmanager
def _question_generation_scope(
    application_id: int,
    stage: InterviewStage,
    user_id: int,
) -> Iterator[None]:
    """Serialize matching generation requests without an unbounded lock registry."""
    lock_count = len(_QUESTION_GENERATION_LOCKS)
    lock_indexes = sorted(
        {
            (application_id * 2 + (stage == "manager")) % lock_count,
            (user_id * 31 + 17) % lock_count,
        }
    )
    with ExitStack() as stack:
        for index in lock_indexes:
            stack.enter_context(_QUESTION_GENERATION_LOCKS[index])
        yield


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
        if user.role != "hr":
            raise HTTPException(status_code=403, detail="Only HR can record the HR interview")
        return
    if user.role != "manager":
        raise HTTPException(
            status_code=403,
            detail="Only the department manager can record the manager interview",
        )


def _enforce_question_plan_generate(user: User, stage: InterviewStage) -> None:
    if stage == "hr" and user.role == "hr":
        return
    if stage == "manager" and user.role == "manager":
        return
    raise HTTPException(
        status_code=403,
        detail=(
            "Only HR can generate HR interview questions"
            if stage == "hr"
            else "Only the department manager can generate manager interview questions"
        ),
    )


def _enforce_private_notes_write(
    user: User,
    stage: InterviewStage,
    fields_set: set[str],
) -> None:
    if "private_notes" not in fields_set:
        return
    if stage != "hr" or user.role != "hr":
        raise HTTPException(
            status_code=403,
            detail="HR private notes can only be maintained by HR",
        )


def _owns_stage(user: User, stage: str) -> bool:
    return (stage == "hr" and user.role == "hr") or (
        stage == "manager" and user.role == "manager"
    )


def _peer_evaluations_released(records: list[InterviewRecord]) -> bool:
    # Shares its definition with the composite score, which may only exist once
    # both stages are submitted. Keeping one implementation is what guarantees the
    # composite cannot appear one moment before the scores it is built from are
    # released.
    return both_stages_submitted(records)


def _record_read(
    record: InterviewRecord,
    user: User,
    peer_evaluations_released: bool,
    requisition: JobRequisition,
) -> InterviewRecordRead:
    result = InterviewRecordRead.model_validate(record)
    # Blind review is decided per requisition before scoring starts. With it off,
    # each side reads the other's evaluation immediately; the masked field list is
    # unchanged for every requisition that keeps the default.
    evaluation_revealed = (
        _owns_stage(user, record.stage)
        or peer_evaluations_released
        or not requisition.blind_review_enabled
    )
    private_notes_visible = user.role == "hr" and record.stage == "hr"
    updates: dict[str, object] = {
        "evaluation_revealed": evaluation_revealed,
        "private_notes_visible": private_notes_visible,
        "private_notes": result.private_notes if private_notes_visible else None,
    }
    if not evaluation_revealed:
        updates.update(
            questions=[
                question.model_copy(
                    update={
                        "rating": None,
                        "not_asked_reason": None,
                        "notes": None,
                    }
                )
                for question in result.questions
            ],
            summary=None,
            recommendation=None,
            overall_rating=None,
            overall_score=None,
            submitted_by_id=None,
            submitted_by_name=None,
            last_reopen_reason=None,
        )
    return result.model_copy(update=updates)


def _evaluation_audit_details(record: InterviewRecord) -> dict[str, object]:
    questions = record.questions or []
    rated_count = sum(item.get("rating") is not None for item in questions)
    not_asked_count = sum(bool(item.get("not_asked_reason")) for item in questions)
    return {
        "question_count": len(questions),
        "rated_question_count": rated_count,
        "not_asked_question_count": not_asked_count,
        "completed_question_count": rated_count + not_asked_count,
        "overall_rating_present": record.overall_rating is not None,
        "overall_score_present": record.overall_score is not None,
        "recommendation_present": record.recommendation is not None,
        "summary_present": bool(record.summary and record.summary.strip()),
        "revision_number": record.revision_number,
    }


def _validate_completed_update(
    *,
    status_value: str,
    questions_value: list[dict],
    summary_value: str | None,
    recommendation_value: str | None,
    overall_rating_value: int | None,
    overall_score_value: int | None,
) -> None:
    try:
        questions = [
            InterviewRecordQuestion.model_validate(question)
            for question in questions_value
        ]
        validate_completed_evaluation(
            status=status_value,  # type: ignore[arg-type]
            questions=questions,
            summary=summary_value,
            recommendation=recommendation_value,  # type: ignore[arg-type]
            overall_rating=overall_rating_value,
            overall_score=overall_score_value,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


def _application_records(db: Session, application_id: int) -> list[InterviewRecord]:
    return application_interview_records(db, application_id)


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
            "title": item.title,
            "years": item.years,
            "description": item.description,
        }
        for item in db.scalars(
            select(CandidateExperience)
            .where(CandidateExperience.candidate_id == candidate_id)
            .order_by(CandidateExperience.sort_order, CandidateExperience.id)
        ).all()
    ]
    return skills, experiences


def _question_context_hash(
    candidate: Candidate,
    requisition: JobRequisition,
    skills: list[str],
    experiences: list[dict[str, object | None]],
    stage: InterviewStage,
) -> str:
    """Hash only job-relevant, de-identified context used to generate questions."""
    payload = {
        "prompt_version": (
            HR_QUESTION_PROMPT_VERSION
            if stage == "hr"
            else MANAGER_QUESTION_PROMPT_VERSION
        ),
        "stage": stage,
        "job_title": requisition.title,
        "job_description": requisition.jd,
        "required_skills": requisition.skills or [],
        "current_title": candidate.current_title,
        "total_years": candidate.total_years,
        "candidate_skills": skills,
        "experiences": [
            {
                "title": item.get("title"),
                "years": item.get("years"),
                "description": item.get("description"),
            }
            for item in experiences
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _latest_question_plan(
    db: Session,
    application_id: int,
    stage: InterviewStage,
) -> InterviewQuestionPlan | None:
    return db.scalar(
        select(InterviewQuestionPlan)
        .where(
            InterviewQuestionPlan.application_id == application_id,
            InterviewQuestionPlan.stage == stage,
        )
        .order_by(InterviewQuestionPlan.version.desc(), InterviewQuestionPlan.id.desc())
    )


def _stored_plan_response(
    application: JobApplication,
    requisition: JobRequisition,
    plan: InterviewQuestionPlan | None,
    context_hash: str,
    stage: InterviewStage,
) -> InterviewQuestionPlanResponse:
    if plan is None:
        if stage == "hr":
            return InterviewQuestionPlanResponse(
                id=None,
                application_id=application.id,
                stage="hr",
                job_title=requisition.title,
                questions=standard_hr_question_plan(),
                personalization_basis=["HR 固定五個評估面向；可由 HR 重新產生不同問法"],
                guidance=(
                    "HR 題目維持相同評估面向與難度；若問法不適合，可按下重新產生。"
                ),
                generation_mode="rules",
                provider="internal",
                model_name="HR 標準題庫",
                version=None,
                context_matches=True,
            )
        return InterviewQuestionPlanResponse(
            id=None,
            application_id=application.id,
            stage=stage,
            job_title=requisition.title,
            questions=[],
            personalization_basis=[],
            guidance="尚未產生主管客製題目；請由 HR 或部門主管按下「產生客製題目」。",
            generation_mode="not_generated",
            provider=None,
            model_name=None,
            version=None,
            generated_at=None,
            context_matches=False,
        )
    return InterviewQuestionPlanResponse(
        id=plan.id,
        application_id=application.id,
        stage=stage,
        job_title=requisition.title,
        questions=annotate_question_compliance(
            [InterviewQuestionPlanItem.model_validate(item) for item in plan.questions]
        ),
        personalization_basis=plan.personalization_basis,
        guidance=(
            f"已載入保存的{'HR' if stage == 'hr' else '主管'}五題；"
            "重新整理不會再次呼叫 AI；可只重新產生不適合的單一題目。"
        ),
        generation_mode=plan.generation_mode,
        generation_warning=plan.generation_warning,
        provider=plan.provider,
        model_name=plan.model_name,
        version=plan.version,
        generated_at=plan.created_at,
        context_matches=plan.context_hash == context_hash,
        input_tokens=plan.input_tokens,
        output_tokens=plan.output_tokens,
        thinking_tokens=plan.thinking_tokens,
        total_tokens=plan.total_tokens,
    )


def _generate_question_plan_locked(
    *,
    db: Session,
    user: User,
    application: JobApplication,
    requisition: JobRequisition,
    candidate: Candidate,
    stage: InterviewStage,
    force: bool,
    question_index: int | None = None,
) -> InterviewQuestionPlanResponse:
    # PostgreSQL row locks protect against duplicate API calls across workers.
    # SQLite ignores FOR UPDATE, so the fixed in-process locks remain necessary.
    db.execute(select(User.id).where(User.id == user.id).with_for_update()).scalar_one()
    db.execute(
        select(JobApplication.id)
        .where(JobApplication.id == application.id)
        .with_for_update()
    ).scalar_one()

    skills, experiences = _candidate_resume_context(db, candidate.id)
    context_hash = _question_context_hash(candidate, requisition, skills, experiences, stage)
    latest = _latest_question_plan(db, application.id, stage)
    if (
        question_index is None
        and latest is not None
        and latest.context_hash == context_hash
        and not force
    ):
        return _stored_plan_response(application, requisition, latest, context_hash, stage)

    settings = get_settings()
    if settings.gemini_enabled and settings.gemini_api_key:
        now = datetime.now(UTC)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        generated_today = db.scalar(
            select(func.count(InterviewQuestionPlan.id)).where(
                InterviewQuestionPlan.generated_by_id == user.id,
                InterviewQuestionPlan.created_at >= day_start,
            )
        )
        if (generated_today or 0) >= settings.gemini_daily_generation_limit_per_user:
            retry_after = max(
                1,
                int((day_start + timedelta(days=1) - now).total_seconds()),
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Daily Gemini question generation limit reached",
                headers={"Retry-After": str(retry_after)},
            )

    next_version = (latest.version + 1) if latest else 1
    regenerated_category: str | None = None
    if question_index is None:
        generator = gemini_hr_question_plan if stage == "hr" else gemini_manager_question_plan
        questions, basis, generation_mode, token_usage = generator(
            job_title=requisition.title,
            job_description=requisition.jd,
            current_title=candidate.current_title,
            total_years=candidate.total_years,
            candidate_skills=skills,
            required_skills=requisition.skills or [],
            experiences=experiences,
            bypass_cache=force,
        )
    else:
        if latest is not None:
            base_questions = annotate_question_compliance(
                [
                    InterviewQuestionPlanItem.model_validate(item)
                    for item in latest.questions
                ]
            )
        elif stage == "hr":
            base_questions = standard_hr_question_plan()
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Generate the initial five manager questions before regenerating "
                    "one question"
                ),
            )

        expected_categories = (
            HR_QUESTION_CATEGORIES if stage == "hr" else MANAGER_QUESTION_CATEGORIES
        )
        if (
            len(base_questions) != 5
            or tuple(item.category for item in base_questions) != expected_categories
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "The current interview question plan is not eligible for "
                    "single-question regeneration"
                ),
            )
        regenerated_category = base_questions[question_index].category
        replacement, basis, generation_mode, token_usage = gemini_question_replacement(
            stage=stage,
            category=regenerated_category,
            existing_questions=base_questions,
            job_title=requisition.title,
            job_description=requisition.jd,
            current_title=candidate.current_title,
            total_years=candidate.total_years,
            candidate_skills=skills,
            required_skills=requisition.skills or [],
            experiences=experiences,
            variant_seed=next_version,
        )
        questions = list(base_questions)
        questions[question_index] = replacement
    warning_by_marker = {
        "GEMINI_QUOTA_EXCEEDED": (
            "Gemini API 已達目前使用上限，暫時改用規則式備援題目；"
            "請檢查 Google AI Studio 配額或計費設定。"
        ),
        "GEMINI_MODEL_UNAVAILABLE": (
            "目前設定的 Gemini 模型無法使用，已改用規則式備援題目；"
            "請由系統管理員確認 GEMINI_MODEL 設定。"
        ),
        "GEMINI_INVALID_RESPONSE": (
            "Gemini 有回覆，但未產生有效且不重複的"
            f"{'單題' if question_index is not None else '五個客製化評估面向'}，"
            "已改用規則式備援題目。"
        ),
        "GEMINI_SERVICE_UNAVAILABLE": (
            "Gemini 目前無法連線或服務異常，已改用規則式備援題目，稍後可重新產生。"
        ),
    }
    generation_warning = next(
        (warning for marker, warning in warning_by_marker.items() if marker in basis),
        None,
    )
    visible_basis = [item for item in basis if item not in warning_by_marker]
    plan = InterviewQuestionPlan(
        application_id=application.id,
        stage=stage,
        context_hash=context_hash,
        version=next_version,
        questions=[item.model_dump() for item in questions],
        personalization_basis=visible_basis,
        generation_mode=generation_mode,
        provider="gemini" if generation_mode == "gemini" else "rules",
        model_name=settings.gemini_model if settings.gemini_enabled else None,
        generation_warning=generation_warning,
        input_tokens=token_usage.input_tokens,
        output_tokens=token_usage.output_tokens,
        thinking_tokens=token_usage.thinking_tokens,
        total_tokens=token_usage.total_tokens,
        generated_by_id=user.id,
        generated_by_name=_actor_name(user),
    )
    try:
        db.add(plan)
        db.flush()
        write_audit(
            db,
            user,
            "application.interview_question_plan.generate",
            "interview_question_plan",
            plan.id,
            requisition.department_id,
            details={
                "application_id": application.id,
                "stage": stage,
                "version": plan.version,
                "generation_mode": generation_mode,
                "force": force,
                "question_index": question_index,
                "question_category": regenerated_category,
                "total_tokens": token_usage.total_tokens,
            },
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        current_application, current_requisition = _application_requisition(
            db, application.id, user
        )
        concurrent_plan = _latest_question_plan(db, application.id, stage)
        if concurrent_plan is not None and concurrent_plan.version >= next_version:
            return _stored_plan_response(
                current_application,
                current_requisition,
                concurrent_plan,
                context_hash,
                stage,
            )
        raise
    db.refresh(plan)
    return _stored_plan_response(application, requisition, plan, context_hash, stage)


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

    skills, experiences = _candidate_resume_context(db, candidate.id)
    context_hash = _question_context_hash(candidate, requisition, skills, experiences, stage)
    return _stored_plan_response(
        application,
        requisition,
        _latest_question_plan(db, application.id, stage),
        context_hash,
        stage,
    )


@router.post(
    "/{application_id}/interview-question-plan/generate",
    response_model=InterviewQuestionPlanResponse,
)
def generate_interview_question_plan(
    application_id: int,
    stage: InterviewStage = Query(default="manager"),
    force: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> InterviewQuestionPlanResponse:
    application, requisition = _application_requisition(db, application_id, user)
    candidate = db.get(Candidate, application.candidate_id)
    if candidate is None or candidate.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    _enforce_question_plan_generate(user, stage)
    with _question_generation_scope(application.id, stage, user.id):
        return _generate_question_plan_locked(
            db=db,
            user=user,
            application=application,
            requisition=requisition,
            candidate=candidate,
            stage=stage,
            force=force,
        )


@router.post(
    "/{application_id}/interview-question-plan/questions/{question_index}/regenerate",
    response_model=InterviewQuestionPlanResponse,
)
def regenerate_interview_question(
    application_id: int,
    question_index: int = Path(ge=0, le=4),
    stage: InterviewStage = Query(),
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> InterviewQuestionPlanResponse:
    application, requisition = _application_requisition(db, application_id, user)
    candidate = db.get(Candidate, application.candidate_id)
    if candidate is None or candidate.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    _enforce_question_plan_generate(user, stage)
    with _question_generation_scope(application.id, stage, user.id):
        return _generate_question_plan_locked(
            db=db,
            user=user,
            application=application,
            requisition=requisition,
            candidate=candidate,
            stage=stage,
            force=True,
            question_index=question_index,
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
    _, requisition = _application_requisition(db, application_id, user)
    records = _application_records(db, application_id)
    evaluations_released = _peer_evaluations_released(records)
    return [
        _record_read(record, user, evaluations_released, requisition)
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
    application, requisition = _application_requisition(db, application_id, user)
    _enforce_stage_write(user, payload.stage)
    _enforce_private_notes_write(user, payload.stage, payload.model_fields_set)
    question_plan: InterviewQuestionPlan | None = None
    if payload.question_plan_id is not None:
        question_plan = db.get(InterviewQuestionPlan, payload.question_plan_id)
        if (
            question_plan is None
            or question_plan.application_id != application_id
            or question_plan.stage != payload.stage
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Question plan does not belong to this application and interview stage",
            )
    actor_name = _actor_name(user)
    submitted_at = datetime.now(UTC) if payload.status == "completed" else None
    record = InterviewRecord(
        application_id=application_id,
        question_plan_id=question_plan.id if question_plan else None,
        question_plan_version=question_plan.version if question_plan else None,
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
        overall_score=payload.overall_score,
        submitted_at=submitted_at,
        submitted_by_id=user.id if submitted_at else None,
        submitted_by_name=actor_name if submitted_at else None,
        revision_number=1 if submitted_at else 0,
        interviewer_id=user.id,
        interviewer_name=actor_name,
        updated_by_id=user.id,
        updated_by_name=actor_name,
    )
    db.add(record)
    db.flush()
    recompute_application_composite_score(db, application, requisition)
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
            "question_plan_id": record.question_plan_id,
            "question_plan_version": record.question_plan_version,
            "status": record.status,
            **_evaluation_audit_details(record),
        },
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    db.refresh(record)
    records = _application_records(db, application_id)
    return _record_read(record, user, _peer_evaluations_released(records), requisition)


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
    _, requisition = _application_requisition(db, application_id, user)
    record = _record(db, application_id, record_id)
    records = _application_records(db, application_id)
    return _record_read(record, user, _peer_evaluations_released(records), requisition)


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
    application, requisition = _application_requisition(db, application_id, user)
    record = _record(db, application_id, record_id)
    _enforce_stage_write(user, record.stage)  # type: ignore[arg-type]
    if record.status == "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Completed interview records are locked; reopen before editing",
        )
    _enforce_private_notes_write(
        user,
        record.stage,  # type: ignore[arg-type]
        payload.model_fields_set,
    )
    updates = payload.model_dump(exclude_unset=True)
    if updates.get("interviewed_at") is not None:
        updates["interviewed_at"] = updates["interviewed_at"].astimezone(UTC)
    if "questions" in payload.model_fields_set:
        updates["questions"] = [
            item.model_dump() for item in (payload.questions or [])
        ]
    previous_status = record.status
    next_status = updates.get("status", record.status)
    next_questions = updates.get("questions", record.questions)
    next_summary = updates.get("summary", record.summary)
    next_recommendation = updates.get("recommendation", record.recommendation)
    next_overall_rating = updates.get("overall_rating", record.overall_rating)
    next_overall_score = updates.get("overall_score", record.overall_score)
    _validate_completed_update(
        status_value=next_status,
        questions_value=next_questions,
        summary_value=next_summary,
        recommendation_value=next_recommendation,
        overall_rating_value=next_overall_rating,
        overall_score_value=next_overall_score,
    )
    for field, value in updates.items():
        setattr(record, field, value)
    actor_name = _actor_name(user)
    record.updated_by_id = user.id
    record.updated_by_name = actor_name
    if previous_status != "completed" and record.status == "completed":
        record.submitted_at = datetime.now(UTC)
        record.submitted_by_id = user.id
        record.submitted_by_name = actor_name
        record.revision_number = (record.revision_number or 0) + 1
    db.flush()
    recompute_application_composite_score(db, application, requisition)
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
            **_evaluation_audit_details(record),
        },
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    db.refresh(record)
    records = _application_records(db, application_id)
    return _record_read(record, user, _peer_evaluations_released(records), requisition)


@router.post(
    "/{application_id}/interview-records/{record_id}/reopen",
    response_model=InterviewRecordRead,
)
def reopen_interview_record(
    application_id: int,
    record_id: int,
    payload: InterviewRecordReopenRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> InterviewRecordRead:
    application, requisition = _application_requisition(db, application_id, user)
    record = _record(db, application_id, record_id)
    _enforce_stage_write(user, record.stage)  # type: ignore[arg-type]
    if record.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only completed interview records can be reopened",
        )

    record.status = "in_progress"
    record.last_reopen_reason = payload.reason
    record.updated_by_id = user.id
    record.updated_by_name = _actor_name(user)
    # A reopened stage no longer has a submitted record, so by the composite's own
    # invariant the stored number has to go back to pending. It also closes the
    # only window in which a stale composite could outlive the re-masking that a
    # reopen performs on the peer's evaluation.
    db.flush()
    recompute_application_composite_score(db, application, requisition)
    write_audit(
        db,
        user,
        "application.interview_record.reopen",
        "interview_record",
        record.id,
        requisition.department_id,
        details={
            "application_id": application_id,
            "stage": record.stage,
            "status": {"from": "completed", "to": "in_progress"},
            "revision_number": record.revision_number,
            "reopen_reason": payload.reason[:500],
            **_evaluation_audit_details(record),
        },
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    db.refresh(record)
    records = _application_records(db, application_id)
    return _record_read(record, user, _peer_evaluations_released(records), requisition)
