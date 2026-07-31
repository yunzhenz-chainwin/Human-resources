import shutil
from collections.abc import Generator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.talent_retention import router
from app.core.config import Settings
from app.db.base import Base
from app.db.session import get_db
from app.dependencies.auth import require_recruiting_manager
from app.models import (
    AuditLog,
    Candidate,
    CandidateActivity,
    CandidateEducation,
    CandidateExperience,
    CandidateSkill,
    DeidentifiedResumeDocument,
    InterviewRecord,
    JobApplication,
    JobRequisition,
    MatchResult,
    ResumeFile,
    RetentionStorageDeletion,
    SystemSetting,
    User,
)
from app.services.retention_worker import run_retention_cycle
from app.services.talent_retention import (
    RETENTION_SETTING_KEY,
    process_pending_storage_deletions,
    purge_expired_candidates,
    set_candidate_retention,
    set_retention_policy,
)


class FakeStorage:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.deleted: list[str] = []

    def delete(self, key: str) -> None:
        if self.fail:
            raise RuntimeError("provider detail must not be persisted")
        self.deleted.append(key)


@pytest.fixture()
def retention_db() -> Generator[tuple[sessionmaker, Settings], None, None]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    storage_root = Path("storage") / f"retention-test-{uuid4().hex}"
    settings = Settings(
        app_env="test",
        database_url="sqlite://",
        candidate_photo_storage_path=str(storage_root / "photos"),
        resume_storage_path=str(storage_root / "resumes"),
        resume_quarantine_path=str(storage_root / "quarantine"),
        talent_retention_batch_size=1,
        talent_retention_max_batches_per_run=10,
    )
    yield testing_session, settings
    Base.metadata.drop_all(engine)
    shutil.rmtree(storage_root, ignore_errors=True)


def _create_requisition(db: Session) -> JobRequisition:
    requisition = JobRequisition(
        req_no="REQ-RETENTION",
        title="Retention Test",
        headcount=1,
        employment_type="full_time",
        work_city="Taipei",
        jd="Test role",
        status="closed",
    )
    db.add(requisition)
    db.flush()
    return requisition


def _create_expired_candidate(
    db: Session,
    *,
    code: str,
    created_at: datetime,
    photo_path: str | None = None,
) -> Candidate:
    candidate = Candidate(
        code=code,
        name="Private Candidate",
        email="private@example.test",
        email_norm="private@example.test",
        phone="0912345678",
        phone_norm="0912345678",
        address="Taipei private address",
        birth_date=date(1990, 1, 2),
        summary="Private biography",
        status="archived",
        retention_until=date(2022, 1, 1),
        photo_path=photo_path,
        photo_content_type="image/png" if photo_path else None,
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(candidate)
    db.flush()
    return candidate


def test_policy_recalculates_company_defaults_but_preserves_individual_periods(
    retention_db,
) -> None:
    testing_session, _ = retention_db
    with testing_session() as db:
        individual = _create_expired_candidate(
            db,
            code="RET-INDIVIDUAL",
            created_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        individual.retention_years_override = 5
        individual.retention_until = date(2025, 1, 1)
        company_default = Candidate(
            code="RET-COMPANY-DEFAULT",
            name="Company default deadline",
            created_at=datetime(2024, 6, 1, tzinfo=UTC),
            updated_at=datetime(2024, 6, 1, tzinfo=UTC),
        )
        db.add(company_default)
        db.flush()
        policy, applied = set_retention_policy(db, 3)
        db.commit()
        assert policy.retention_years == 3
        assert applied == 1
        assert individual.retention_years_override == 5
        assert individual.retention_until == date(2025, 1, 1)
        assert company_default.retention_years_override is None
        assert company_default.retention_until == date(2027, 6, 1)
        assert db.get(SystemSetting, RETENTION_SETTING_KEY).value == 3


def test_individual_period_can_be_longer_than_default_and_restore_default(
    retention_db,
) -> None:
    testing_session, settings = retention_db
    with testing_session() as db:
        candidate = Candidate(
            code="RET-FIVE-YEARS",
            name="Five year candidate",
            created_at=datetime(2024, 2, 29, tzinfo=UTC),
            updated_at=datetime(2024, 2, 29, tzinfo=UTC),
        )
        db.add(candidate)
        db.flush()
        set_retention_policy(db, 1)
        individual = set_candidate_retention(db, candidate, 5)
        db.commit()
        candidate_id = candidate.id
        assert individual.uses_company_default is False
        assert individual.retention_until == date(2029, 2, 28)

    with testing_session() as db:
        preview = purge_expired_candidates(
            db,
            dry_run=True,
            as_of=date(2026, 7, 24),
            settings=settings,
        )
        assert preview.eligible_candidates == 0
        candidate = db.get(Candidate, candidate_id)
        restored = set_candidate_retention(db, candidate, None)
        db.commit()
        assert restored.uses_company_default is True
        assert restored.effective_retention_years == 1
        assert restored.retention_until == date(2025, 2, 28)

    with testing_session() as db:
        preview = purge_expired_candidates(
            db,
            dry_run=True,
            as_of=date(2026, 7, 24),
            settings=settings,
        )
        assert preview.eligible_candidates == 1


def test_dry_run_defaults_safe_and_actual_purge_erases_all_candidate_pii(
    retention_db,
) -> None:
    testing_session, settings = retention_db
    photo = Path(settings.candidate_photo_storage_path) / "candidate.png"
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b"private-photo")
    storage = FakeStorage()
    with testing_session() as db:
        actor = User(
            username="retention-hr",
            email="retention-hr@example.test",
            password_hash="unused",
            display_name="Retention HR",
            role="hr",
            is_active=True,
        )
        db.add(actor)
        requisition = _create_requisition(db)
        candidate = _create_expired_candidate(
            db,
            code="RET-DELETE",
            created_at=datetime(2020, 1, 1, tzinfo=UTC),
            photo_path=str(photo),
        )
        db.add_all(
            [
                CandidateEducation(
                    candidate_id=candidate.id,
                    school="Private School",
                    sort_order=0,
                ),
                CandidateExperience(
                    candidate_id=candidate.id,
                    company="Private Employer",
                    title="Private Job",
                    description="Private work history",
                    sort_order=0,
                ),
                CandidateSkill(
                    candidate_id=candidate.id,
                    skill="Secret Skill",
                    skill_norm="secret",
                ),
                CandidateActivity(
                    candidate_id=candidate.id,
                    type="note",
                    content="Private HR note",
                    happened_at=datetime(2021, 1, 1, tzinfo=UTC),
                ),
            ]
        )
        resume = ResumeFile(
            # Imported legacy rows can be linked only through the application.
            # Retention cleanup must not leave their parsed PII behind.
            candidate_id=None,
            storage_key="resumes/random-key.pdf",
            original_filename="private-name.pdf",
            file_hash="a" * 64,
            source_platform="direct",
            parse_status="confirmed",
            parsed_payload={"name": "Private Candidate"},
            resume_text="full private resume",
        )
        db.add(resume)
        db.flush()
        deidentified_resume = DeidentifiedResumeDocument(
            source_resume_id=resume.id,
            anonymous_ref=str(uuid4()),
            version=1,
            storage_key="deidentified-resumes/anonymous-v1.pdf",
            file_hash="c" * 64,
            file_size=128,
            source_file_hash=resume.file_hash,
            deidentification_version="test-v1",
            payload_schema_version="talenthub.deidentified-resume.v1",
            analysis_payload={
                "schema_version": "talenthub.deidentified-resume.v1",
                "skills": ["Python"],
            },
            validation_status="analysis_ready",
            validation_summary={"blocker_count": 0},
            created_by=actor.id,
            reviewed_by=actor.id,
            reviewed_at=datetime(2021, 1, 1, tzinfo=UTC),
        )
        db.add(deidentified_resume)
        db.flush()
        application = JobApplication(
            requisition_id=requisition.id,
            candidate_id=candidate.id,
            resume_id=resume.id,
            cover_letter="Private cover letter",
            status="withdrawn",
        )
        db.add(application)
        db.flush()
        db.add_all(
            [
                MatchResult(
                    requisition_id=requisition.id,
                    candidate_id=candidate.id,
                    gate_passed=True,
                    total_score=Decimal("80.00"),
                    score_breakdown={"private": "assessment"},
                ),
                InterviewRecord(
                    application_id=application.id,
                    stage="hr",
                    interviewed_at=datetime(2021, 1, 1, tzinfo=UTC),
                    mode="video",
                    status="completed",
                    questions=[{"question": "private", "answer": "private"}],
                    summary="Private interview summary",
                    interviewer_name="HR",
                    updated_by_name="HR",
                ),
            ]
        )
        db.commit()
        candidate_id = candidate.id
        resume_id = resume.id
        deidentified_resume_id = deidentified_resume.id
        application_id = application.id
        actor_id = actor.id

    with testing_session() as db:
        preview = purge_expired_candidates(
            db,
            dry_run=True,
            as_of=date(2026, 7, 24),
            batch_size=100,
            storage_provider=storage,
            settings=settings,
        )
        assert preview.eligible_candidates == 1
        assert preview.eligible_resume_files == 1
        assert preview.deleted_candidates == 0
        assert db.get(Candidate, candidate_id) is not None
        assert photo.exists()

    with testing_session() as db:
        result = purge_expired_candidates(
            db,
            dry_run=False,
            as_of=date(2026, 7, 24),
            actor=db.get(User, actor_id),
            batch_size=100,
            storage_provider=storage,
            settings=settings,
        )
        assert result.deleted_candidates == 1
        assert result.deleted_resume_files == 1
        assert result.deleted_photos == 1
        assert result.storage_delete_failures == 0
        assert db.get(Candidate, candidate_id) is None
        assert db.get(ResumeFile, resume_id) is None
        assert db.get(DeidentifiedResumeDocument, deidentified_resume_id) is None
        assert db.get(JobApplication, application_id) is None
        assert db.scalar(select(func.count()).select_from(CandidateEducation)) == 0
        assert db.scalar(select(func.count()).select_from(CandidateExperience)) == 0
        assert db.scalar(select(func.count()).select_from(CandidateSkill)) == 0
        assert db.scalar(select(func.count()).select_from(CandidateActivity)) == 0
        assert db.scalar(select(func.count()).select_from(MatchResult)) == 0
        assert db.scalar(select(func.count()).select_from(InterviewRecord)) == 0
        assert db.scalar(select(func.count()).select_from(RetentionStorageDeletion)) == 0
        audit = db.scalar(
            select(AuditLog).where(AuditLog.action == "talent_retention.purge")
        )
        assert audit is not None
        assert "Private Candidate" not in str(audit.details)
    assert sorted(storage.deleted) == [
        "deidentified-resumes/anonymous-v1.pdf",
        "resumes/random-key.pdf",
    ]
    assert not photo.exists()


def test_failed_file_delete_stays_in_outbox_and_is_retryable(retention_db) -> None:
    testing_session, settings = retention_db
    with testing_session() as db:
        candidate = _create_expired_candidate(
            db,
            code="RET-RETRY",
            created_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        db.add(
            ResumeFile(
                candidate_id=candidate.id,
                storage_key="resumes/retry.pdf",
                file_hash="b" * 64,
                source_platform="direct",
                parse_status="confirmed",
            )
        )
        db.commit()
        candidate_id = candidate.id

    with testing_session() as db:
        result = purge_expired_candidates(
            db,
            dry_run=False,
            as_of=date(2026, 7, 24),
            storage_provider=FakeStorage(fail=True),
            settings=settings,
        )
        assert result.deleted_candidates == 1
        assert result.storage_delete_failures == 1
        assert db.get(Candidate, candidate_id) is None
        task = db.scalar(select(RetentionStorageDeletion))
        assert task is not None
        assert task.attempts == 1
        assert task.last_error == "RuntimeError"
        assert "provider detail" not in (task.last_error or "")

    succeeding = FakeStorage()
    with testing_session() as db:
        retry = process_pending_storage_deletions(
            db, storage_provider=succeeding, settings=settings
        )
        assert retry.deleted_storage_objects == 1
        assert retry.failures == 0
        assert db.scalar(select(func.count()).select_from(RetentionStorageDeletion)) == 0
    assert succeeding.deleted == ["resumes/retry.pdf"]


def test_worker_drains_all_batches_and_retries_outbox_when_no_candidates(
    retention_db, monkeypatch
) -> None:
    testing_session, settings = retention_db
    storage = FakeStorage()
    monkeypatch.setattr("app.services.storage.get_storage_provider", lambda _settings: storage)
    with testing_session() as db:
        db.add(RetentionStorageDeletion(kind="resume", locator="resumes/orphan.pdf"))
        db.commit()

    first = run_retention_cycle(settings=settings, session_factory=testing_session)
    assert first["deleted_candidates"] == 0
    assert first["deleted_storage_objects"] == 1
    assert storage.deleted == ["resumes/orphan.pdf"]

    with testing_session() as db:
        for index in range(3):
            _create_expired_candidate(
                db,
                code=f"RET-BATCH-{index}",
                created_at=datetime(2020, 1, index + 1, tzinfo=UTC),
            )
        db.commit()

    second = run_retention_cycle(settings=settings, session_factory=testing_session)
    assert second["deleted_candidates"] == 3
    assert second["remaining_candidates"] == 0
    with testing_session() as db:
        assert db.scalar(select(func.count()).select_from(Candidate)) == 0


def test_retention_api_defaults_purge_to_dry_run(retention_db) -> None:
    testing_session, _ = retention_db
    with testing_session() as db:
        actor = User(
            username="api-hr",
            email="api-hr@example.test",
            password_hash="unused",
            display_name="API HR",
            role="hr",
            is_active=True,
        )
        db.add(actor)
        candidate = _create_expired_candidate(
            db,
            code="RET-API",
            created_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        db.commit()
        actor_id = actor.id
        candidate_id = candidate.id

    app = FastAPI()

    def override_db():
        with testing_session() as db:
            yield db

    def override_actor() -> User:
        with testing_session() as db:
            return db.get(User, actor_id)

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_recruiting_manager] = override_actor
    app.include_router(router)
    with TestClient(app) as client:
        policy = client.put("/talent-retention/policy", json={"retention_years": 2})
        assert policy.status_code == 200
        assert policy.json()["retention_years"] == 2
        individual = client.put(
            f"/talent-retention/candidates/{candidate_id}",
            json={"retention_years": 10},
        )
        assert individual.status_code == 200
        assert individual.json()["retention_years_override"] == 10
        assert individual.json()["uses_company_default"] is False
        preview = client.post("/talent-retention/purge")
        assert preview.status_code == 200
        assert preview.json()["dry_run"] is True
        assert preview.json()["eligible_candidates"] == 0
        restored = client.put(
            f"/talent-retention/candidates/{candidate_id}",
            json={"retention_years": None},
        )
        assert restored.status_code == 200
        assert restored.json()["uses_company_default"] is True
        preview = client.post("/talent-retention/purge")
        assert preview.json()["eligible_candidates"] == 1
    with testing_session() as db:
        assert db.scalar(select(func.count()).select_from(Candidate)) == 1
