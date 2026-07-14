from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import Base
from app.models import Department, JobRequisition, MatchResult, SystemIssue
from app.services.demo_data import (
    DEMO_REQUISITIONS,
    seed_demo_requisitions,
    seed_matching_showcase,
)
from app.services.system_issue_seed import SYSTEM_ISSUE_SEED, seed_system_issues


def test_demo_job_seed_is_idempotent_and_does_not_overwrite() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Department(name="測試部門", is_active=True))
        db.add(
            JobRequisition(
                req_no="DEMO-BE-001",
                title="既有職缺不可被覆蓋",
                employment_type="contract",
                work_city="高雄市",
                jd="Existing content",
                status="draft",
            )
        )
        db.commit()

        first = seed_demo_requisitions(db)
        second = seed_demo_requisitions(db)

        assert len(first) == len(DEMO_REQUISITIONS) - 1
        assert second == []
        jobs = list(db.scalars(select(JobRequisition).order_by(JobRequisition.req_no)).all())
        assert len(jobs) == len(DEMO_REQUISITIONS)
        existing = next(job for job in jobs if job.req_no == "DEMO-BE-001")
        assert existing.title == "既有職缺不可被覆蓋"
        assert existing.work_city == "高雄市"


def test_matching_showcase_has_exact_three_score_levels() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Department(name="展示部門", is_active=True))
        db.commit()
        job, candidates = seed_matching_showcase(db)
        first_ids = [candidate.id for candidate in candidates]
        _, repeated = seed_matching_showcase(db)
        assert [candidate.id for candidate in repeated] == first_ids
        results = list(
            db.scalars(
                select(MatchResult)
                .where(
                    MatchResult.requisition_id == job.id,
                    MatchResult.candidate_id.in_(first_ids),
                )
                .order_by(MatchResult.total_score.desc())
            )
        )
        assert [float(item.total_score) for item in results] == [100.0, 75.0, 50.0]


def test_demo_seed_is_blocked_in_production() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    settings = get_settings()
    original_environment = settings.app_env
    settings.app_env = "production"
    try:
        with Session(engine) as db:
            with pytest.raises(RuntimeError, match="disabled in production"):
                seed_demo_requisitions(db)
            with pytest.raises(RuntimeError, match="disabled in production"):
                seed_matching_showcase(db)
            assert db.scalar(select(JobRequisition.id)) is None
    finally:
        settings.app_env = original_environment


def test_system_issue_seed_preserves_it_workflow_state() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        created, updated = seed_system_issues(db)
        assert (created, updated) == (len(SYSTEM_ISSUE_SEED), 0)
        issue = db.scalar(
            select(SystemIssue).where(SystemIssue.title == SYSTEM_ISSUE_SEED[0]["title"])
        )
        assert issue is not None
        issue.status = "investigating"
        issue.progress_percent = 73
        issue.expected_completion_date = date(2027, 1, 31)
        issue.resolution_notes = "IT-maintained progress must survive reseeding."
        db.commit()

        created, updated = seed_system_issues(db)
        assert (created, updated) == (0, len(SYSTEM_ISSUE_SEED))
        db.refresh(issue)
        assert issue.status == "investigating"
        assert issue.progress_percent == 73
        assert issue.expected_completion_date == date(2027, 1, 31)
        assert issue.resolution_notes == "IT-maintained progress must survive reseeding."
