from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import Department, JobRequisition, MatchResult
from app.services.demo_data import (
    DEMO_REQUISITIONS,
    seed_demo_requisitions,
    seed_matching_showcase,
)


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
