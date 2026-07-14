from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.reports import router as reports_router
from app.db.base import Base
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models import Candidate, CandidateSkill, Department, JobApplication, JobRequisition
from app.services.reports import (
    funnel_report,
    sources_report,
    talent_pool_report,
    time_to_fill_report,
)


def moment(day: int) -> datetime:
    return datetime(2026, 1, day, 12, tzinfo=UTC)


@pytest.fixture()
def report_db() -> Session:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
    Base.metadata.drop_all(engine)


def add_fixture_data(db: Session) -> tuple[Department, Department]:
    engineering = Department(name="Engineering")
    sales = Department(name="Sales")
    db.add_all([engineering, sales])
    db.flush()
    candidates = [
        Candidate(
            code="C001",
            name="Alpha",
            source="p104",
            city="Taipei",
            highest_education="bachelor",
            total_years=2,
            created_at=moment(1),
            updated_at=moment(1),
        ),
        Candidate(
            code="C002",
            name="Beta",
            source="p1111",
            city="Kaohsiung",
            highest_education="master",
            total_years=7,
            created_at=moment(31),
            updated_at=moment(31),
        ),
        Candidate(
            code="C003",
            name="Deleted",
            source="referral",
            deleted_at=moment(15),
            created_at=moment(5),
            updated_at=moment(5),
        ),
    ]
    db.add_all(candidates)
    db.flush()
    db.add_all(
        [
            CandidateSkill(candidate_id=candidates[0].id, skill="Python", skill_norm="python"),
            CandidateSkill(candidate_id=candidates[1].id, skill="Python", skill_norm="python"),
            CandidateSkill(candidate_id=candidates[1].id, skill="SQL", skill_norm="sql"),
            CandidateSkill(candidate_id=candidates[2].id, skill="Hidden", skill_norm="hidden"),
        ]
    )
    jobs = [
        JobRequisition(
            req_no="R001",
            title="Backend Engineer",
            department_id=engineering.id,
            employment_type="full_time",
            work_city="Taipei",
            jd="Build APIs",
            status="filled",
            published_at=moment(1),
            filled_at=moment(11),
            created_at=moment(1),
            updated_at=moment(11),
        ),
        JobRequisition(
            req_no="R002",
            title="Sales",
            department_id=sales.id,
            employment_type="full_time",
            work_city="Taipei",
            jd="Sell",
            status="sourcing",
            published_at=moment(1),
            created_at=moment(1),
            updated_at=moment(1),
        ),
    ]
    db.add_all(jobs)
    db.flush()
    db.add_all(
        [
            JobApplication(
                requisition_id=jobs[0].id,
                candidate_id=candidates[0].id,
                status="submitted",
                source="career_site",
                created_at=moment(10),
                updated_at=moment(10),
            ),
            JobApplication(
                requisition_id=jobs[0].id,
                candidate_id=candidates[1].id,
                status="hired",
                source="career_site",
                created_at=moment(31),
                updated_at=moment(31),
            ),
            JobApplication(
                requisition_id=jobs[0].id,
                candidate_id=candidates[2].id,
                status="hired",
                source="referral",
                created_at=moment(15),
                updated_at=moment(15),
            ),
        ]
    )
    db.commit()
    return engineering, sales


def test_empty_reports_return_zero(report_db: Session) -> None:
    assert funnel_report(report_db)["total"] == 0
    assert all(stage["count"] == 0 for stage in funnel_report(report_db)["stages"])
    assert time_to_fill_report(report_db) == {
        "filled_count": 0,
        "average_days": 0.0,
        "items": [],
    }
    assert sources_report(report_db) == {"total": 0, "items": []}
    assert talent_pool_report(report_db)["total"] == 0


def test_formal_reports_exclude_demo_namespace(report_db: Session) -> None:
    department = Department(name="Demo Department")
    candidate = Candidate(
        code="T-DEMO-REPORT",
        name="Demo Candidate",
        source="demo",
        created_at=moment(1),
        updated_at=moment(1),
    )
    report_db.add_all([department, candidate])
    report_db.flush()
    job = JobRequisition(
        req_no="DEMO-REPORT-001",
        title="Demo Job",
        department_id=department.id,
        employment_type="full_time",
        work_city="Taipei",
        jd="Demo only",
        status="filled",
        published_at=moment(1),
        filled_at=moment(10),
        created_at=moment(1),
        updated_at=moment(10),
    )
    report_db.add(job)
    report_db.flush()
    report_db.add_all(
        [
            CandidateSkill(
                candidate_id=candidate.id,
                skill="Demo Skill",
                skill_norm="demo skill",
            ),
            JobApplication(
                requisition_id=job.id,
                candidate_id=candidate.id,
                status="hired",
                source="demo",
                created_at=moment(5),
                updated_at=moment(5),
            ),
        ]
    )
    report_db.commit()

    assert funnel_report(report_db)["total"] == 0
    assert sources_report(report_db) == {"total": 0, "items": []}
    assert time_to_fill_report(report_db)["filled_count"] == 0
    assert talent_pool_report(report_db)["total"] == 0


def test_funnel_sources_and_soft_delete(report_db: Session) -> None:
    engineering, _ = add_fixture_data(report_db)
    funnel = funnel_report(
        report_db,
        datetime(2026, 1, 10).date(),
        datetime(2026, 1, 31).date(),
        engineering.id,
    )
    assert funnel["total"] == 2
    assert [stage["count"] for stage in funnel["stages"]] == [2, 1, 1, 1]
    assert [stage["conversion_rate"] for stage in funnel["stages"]] == [1.0, 0.5, 1.0, 1.0]

    sources = sources_report(report_db, department_id=engineering.id)
    assert sources == {
        "total": 2,
        "items": [
            {"source": "p104", "total": 1, "hired": 0, "hire_rate": 0.0},
            {"source": "p1111", "total": 1, "hired": 1, "hire_rate": 1.0},
        ],
    }


def test_time_to_fill_and_talent_distributions(report_db: Session) -> None:
    engineering, sales = add_fixture_data(report_db)
    fill = time_to_fill_report(
        report_db,
        datetime(2026, 1, 11).date(),
        datetime(2026, 1, 11).date(),
        engineering.id,
    )
    assert fill["filled_count"] == 1
    assert fill["average_days"] == 10.0
    assert fill["items"][0]["days"] == 10.0
    assert time_to_fill_report(report_db, department_id=sales.id)["filled_count"] == 0

    pool = talent_pool_report(
        report_db,
        datetime(2026, 1, 1).date(),
        datetime(2026, 1, 31).date(),
        engineering.id,
    )
    assert pool["total"] == 2
    assert pool["skills"][0] == {"label": "Python", "count": 2}
    assert pool["monthly_growth"] == [{"month": "2026-01", "count": 2}]
    assert {item["label"] for item in pool["experience"]} == {"1-2", "6-9"}


def test_report_routes_validate_dates_and_serve_database(report_db: Session) -> None:
    add_fixture_data(report_db)
    app = FastAPI()
    app.include_router(reports_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: report_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1, role="admin", department_id=None, is_active=True
    )
    with TestClient(app) as client:
        invalid = client.get("/api/v1/reports/funnel?from=2026-02-01&to=2026-01-01")
        assert invalid.status_code == 422
        response = client.get("/api/v1/reports/talent-pool?to=2026-01-31")
        assert response.status_code == 200
        assert response.json()["total"] == 2
