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
from app.models import (
    Candidate,
    CandidateSkill,
    Department,
    JobApplication,
    JobRequisition,
    MatchResult,
)
from app.services.matching import evaluate_matching
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


def match_result(
    candidate_id: int,
    gate_passed: bool,
    score: float,
    status: str,
    rank: int | None,
    requisition_id: int = 1,
) -> MatchResult:
    return MatchResult(
        requisition_id=requisition_id,
        candidate_id=candidate_id,
        gate_passed=gate_passed,
        total_score=score,
        score_breakdown={},
        status=status,
        rank=rank,
        computed_at=moment(1),
    )


def add_match_fixture_data(report_db: Session) -> SimpleNamespace:
    engineering = Department(name="Engineering")
    sales = Department(name="Sales")
    report_db.add_all([engineering, sales])
    report_db.flush()
    people = [
        Candidate(
            code=f"M{index:03d}",
            name=f"Match {index}",
            source="p104",
            created_at=moment(1),
            updated_at=moment(1),
        )
        for index in range(1, 6)
    ]
    ghost = Candidate(
        code="M999",
        name="Ghost",
        source="p104",
        deleted_at=moment(2),
        created_at=moment(1),
        updated_at=moment(1),
    )
    report_db.add_all([*people, ghost])
    report_db.flush()
    eng_job = JobRequisition(
        req_no="RM01",
        title="Backend Engineer",
        department_id=engineering.id,
        employment_type="full_time",
        work_city="Taipei",
        jd="Build",
        status="sourcing",
        created_at=moment(1),
        updated_at=moment(1),
    )
    sales_job = JobRequisition(
        req_no="RM02",
        title="Sales",
        department_id=sales.id,
        employment_type="full_time",
        work_city="Taipei",
        jd="Sell",
        status="sourcing",
        created_at=moment(1),
        updated_at=moment(1),
    )
    report_db.add_all([eng_job, sales_job])
    report_db.flush()
    report_db.add_all(
        [
            match_result(people[0].id, True, 90, "hired", 1, eng_job.id),
            match_result(people[1].id, True, 80, "interview", 2, eng_job.id),
            match_result(people[2].id, True, 70, "rejected_by_manager", 3, eng_job.id),
            # A soft-deleted candidate's match must drop out of every evaluation.
            match_result(ghost.id, True, 60, "hired", 4, eng_job.id),
            match_result(people[3].id, True, 85, "offered", 1, sales_job.id),
            # A positive outcome the gate blocked -> a gate false negative.
            match_result(people[4].id, False, 40, "hired", None, sales_job.id),
        ]
    )
    report_db.commit()
    return SimpleNamespace(
        engineering_id=engineering.id,
        sales_id=sales.id,
        eng_job_id=eng_job.id,
        sales_job_id=sales_job.id,
        gate_fn_candidate_id=people[4].id,
    )


def test_evaluate_matching_computes_accuracy_metrics() -> None:
    results = [
        match_result(1, True, 95, "hired", 1),
        match_result(2, True, 88, "interview", 2),
        match_result(3, True, 82, "rejected_by_manager", 3),
        match_result(4, True, 70, "recommended", 4),
        match_result(5, True, 65, "offered", 5),
        match_result(6, True, 55, "withdrawn", 6),
        # Gate-blocked (rank None) yet a human hired them: a gate false negative.
        match_result(7, False, 50, "hired", None),
        match_result(8, False, 30, "ineligible", None),
    ]
    report = evaluate_matching(results)

    assert report["sample_size"] == 8
    assert report["labeled_outcomes"] == 6
    assert report["positive_outcomes"] == 4
    assert report["negative_outcomes"] == 2
    # Top-5 eligible by rank are cands 1-5; cand 4 is unlabeled, so precision is measured
    # over {1,2,3,5} and only the rejection (cand 3) is not positive.
    assert report["precision_at_k"] == {"5": 0.75, "10": 0.6}
    # cand 7 is a positive the gate buried (rank None), pulling recall below 1.0.
    assert report["recall_at_k"] == {"5": 0.75, "10": 0.75}
    assert report["gate_false_negatives"] == 1
    assert report["gate_false_negative_candidates"] == [7]
    assert report["score_calibration"] == [
        {"bucket": "0-39", "count": 0, "positive_rate": None},
        {"bucket": "40-59", "count": 2, "positive_rate": 0.5},
        {"bucket": "60-79", "count": 1, "positive_rate": 1.0},
        {"bucket": "80-100", "count": 3, "positive_rate": 0.6667},
    ]
    assert report["rank_effectiveness"] == {"avg_rank_positive": 2.67, "avg_rank_negative": 4.5}
    assert report["notes"] == ["small_sample", "insufficient_for_tuning"]


def test_evaluate_matching_empty_is_safe() -> None:
    report = evaluate_matching([])
    assert report["sample_size"] == 0
    assert report["precision_at_k"] == {"5": None, "10": None}
    assert report["recall_at_k"] == {"5": None, "10": None}
    assert report["gate_false_negatives"] == 0
    assert report["gate_false_negative_candidates"] == []
    assert all(bucket["positive_rate"] is None for bucket in report["score_calibration"])
    assert report["rank_effectiveness"] == {
        "avg_rank_positive": None,
        "avg_rank_negative": None,
    }
    assert report["notes"] == ["small_sample", "insufficient_for_tuning"]


def test_matching_evaluation_endpoint_honors_scope(report_db: Session) -> None:
    data = add_match_fixture_data(report_db)
    app = FastAPI()
    app.include_router(reports_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: report_db

    def as_user(role: str, department_id: int | None) -> None:
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=1, role=role, department_id=department_id, is_active=True
        )

    with TestClient(app) as client:
        as_user("admin", None)
        everything = client.get("/api/v1/reports/matching-evaluation")
        assert everything.status_code == 200
        body = everything.json()
        # Six match rows exist, but the soft-deleted candidate's row is excluded.
        assert body["sample_size"] == 5
        assert body["positive_outcomes"] == 4
        assert body["negative_outcomes"] == 1
        assert body["gate_false_negatives"] == 1
        assert body["gate_false_negative_candidates"] == [data.gate_fn_candidate_id]
        assert set(body["precision_at_k"]) == {"5", "10"}
        assert set(body["recall_at_k"]) == {"5", "10"}
        assert [bucket["bucket"] for bucket in body["score_calibration"]] == [
            "0-39",
            "40-59",
            "60-79",
            "80-100",
        ]
        assert set(body["rank_effectiveness"]) == {"avg_rank_positive", "avg_rank_negative"}

        scoped = client.get(
            f"/api/v1/reports/matching-evaluation?requisition_id={data.eng_job_id}"
        )
        assert scoped.status_code == 200
        assert scoped.json()["sample_size"] == 3
        assert scoped.json()["positive_outcomes"] == 2

        as_user("manager", data.engineering_id)
        # A manager sees only their own department's requisitions' matches.
        mine = client.get("/api/v1/reports/matching-evaluation")
        assert mine.status_code == 200
        assert mine.json()["sample_size"] == 3

        outside = client.get(
            f"/api/v1/reports/matching-evaluation?requisition_id={data.sales_job_id}"
        )
        assert outside.status_code == 403
