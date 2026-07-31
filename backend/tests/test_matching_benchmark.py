from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.matching_benchmark import router as benchmark_router
from app.db.base import Base
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.fixtures.matching_benchmark_v1 import SUITE_KEY, build_fixture_cases
from app.models.candidate import Candidate
from app.models.matching_benchmark import (
    MatchingBenchmarkCase,
    MatchingBenchmarkRating,
    MatchingBenchmarkSuite,
)
from app.models.organization import User
from app.models.recruitment import JobRequisition
from app.schemas.matching_benchmark import BenchmarkRatingWrite
from app.services.matching_benchmark import (
    BenchmarkStateError,
    blind_cases_payload,
    build_benchmark_report,
    get_benchmark_suite,
    reveal_benchmark_suite,
    save_blind_rating,
    seed_matching_benchmark,
)


@pytest.fixture()
def benchmark_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    with testing_session() as db:
        db.add_all(
            [
                User(
                    username="benchmark-hr",
                    email="benchmark-hr@example.test",
                    password_hash="not-used",
                    display_name="Benchmark HR",
                    role="hr",
                    is_active=True,
                ),
                User(
                    username="benchmark-manager",
                    email="benchmark-manager@example.test",
                    password_hash="not-used",
                    display_name="Benchmark Manager",
                    role="manager",
                    is_active=True,
                ),
            ]
        )
        db.commit()
        seed_matching_benchmark(db, settings=SimpleNamespace(app_env="test"))
    yield testing_session
    Base.metadata.drop_all(engine)


def _reviewers(db: Session) -> tuple[User, User]:
    hr = db.scalar(select(User).where(User.role == "hr"))
    manager = db.scalar(select(User).where(User.role == "manager"))
    assert hr is not None and manager is not None
    return hr, manager


def _complete_ratings(db: Session, suite: MatchingBenchmarkSuite) -> None:
    hr, manager = _reviewers(db)
    cases = list(
        db.scalars(
            select(MatchingBenchmarkCase)
            .where(MatchingBenchmarkCase.suite_id == suite.id)
            .order_by(MatchingBenchmarkCase.sequence)
        )
    )
    verdict_by_expected = {
        "interview": "interview",
        "consider": "consider",
        "reject": "reject",
        "insufficient_data": "insufficient_data",
    }
    reasons_by_expected = {
        "interview": ["strong_evidence"],
        "consider": ["transferable_experience"],
        "reject": ["skill_gap"],
        "insufficient_data": ["missing_information"],
    }
    for case in cases:
        rank = ((case.sequence - 1) % 10) + 1
        for reviewer in (hr, manager):
            db.add(
                MatchingBenchmarkRating(
                    case_id=case.id,
                    reviewer_id=reviewer.id,
                    reviewer_role=reviewer.role,
                    verdict=verdict_by_expected[case.expected_verdict],
                    reasons=reasons_by_expected[case.expected_verdict],
                    priority_rank=rank,
                )
            )
    db.commit()


def test_fixture_is_deterministic_pii_free_and_covers_required_scenarios() -> None:
    first = build_fixture_cases()
    second = build_fixture_cases()
    assert first == second
    assert len(first) == 50
    assert len({item["case_key"] for item in first}) == 50
    assert {item["job_key"] for item in first} == {
        "backend",
        "frontend",
        "data",
        "recruiting",
        "sales",
    }
    assert {item["scenario"] for item in first} >= {
        "strong",
        "boundary",
        "weak",
        "skill_synonym",
        "career_transition",
        "missing_data",
        "salary_mismatch",
        "location_mismatch",
        "experience_gap",
    }
    forbidden_keys = {"name", "email", "phone", "address", "birth_date"}
    for item in first:
        assert forbidden_keys.isdisjoint(item["candidate_profile"])
        assert item["candidate_profile"]["synthetic_code"].startswith("BENCH-")


def test_seed_is_idempotent_isolated_and_disabled_in_production(benchmark_db) -> None:
    with benchmark_db() as db:
        before = {
            "candidates": db.scalar(select(func.count(Candidate.id))),
            "jobs": db.scalar(select(func.count(JobRequisition.id))),
        }
        rerun = seed_matching_benchmark(db, settings=SimpleNamespace(app_env="development"))
        assert rerun == {
            "suite_key": SUITE_KEY,
            "fixture_version": "1.0.0",
            "total_cases": 50,
            "created_cases": 0,
            "updated_cases": 50,
            "unchanged_fixture": True,
        }
        assert db.scalar(select(func.count(MatchingBenchmarkSuite.id))) == 1
        assert db.scalar(select(func.count(MatchingBenchmarkCase.id))) == 50
        assert db.scalar(select(func.count(Candidate.id))) == before["candidates"] == 0
        assert db.scalar(select(func.count(JobRequisition.id))) == before["jobs"] == 0
        with pytest.raises(RuntimeError, match="disabled in production"):
            seed_matching_benchmark(db, settings=SimpleNamespace(app_env="production"))


def test_blind_payload_and_independent_rating_never_expose_system_result(benchmark_db) -> None:
    with benchmark_db() as db:
        suite = get_benchmark_suite(db, SUITE_KEY)
        hr, manager = _reviewers(db)
        hr_payload = blind_cases_payload(db, suite, hr)
        first = hr_payload["cases"][0]
        assert hr_payload["reviewer_role"] == "hr"
        assert "system_score" not in first
        assert "system_gate_passed" not in first
        assert "scenario" not in first
        assert "expected_verdict" not in first
        rating = save_blind_rating(
            db,
            suite,
            first["case_key"],
            hr,
            BenchmarkRatingWrite(
                verdict="interview",
                reasons=["strong_evidence"],
                priority_rank=1,
            ),
        )
        assert rating.reviewer_role == "hr"
        assert blind_cases_payload(db, suite, hr)["cases"][0]["my_rating"] is not None
        assert blind_cases_payload(db, suite, manager)["cases"][0]["my_rating"] is None
        with pytest.raises(BenchmarkStateError, match="Cannot reveal"):
            reveal_benchmark_suite(db, suite, hr)


def test_rating_validation_preserves_unknown_semantics() -> None:
    with pytest.raises(ValidationError, match="missing_information"):
        BenchmarkRatingWrite(
            verdict="insufficient_data",
            reasons=["skill_gap"],
        )
    with pytest.raises(ValidationError, match="duplicates"):
        BenchmarkRatingWrite(
            verdict="reject",
            reasons=["skill_gap", "skill_gap"],
        )


def test_completed_blind_study_reveals_metrics_and_small_sample_warning(benchmark_db) -> None:
    with benchmark_db() as db:
        suite = get_benchmark_suite(db, SUITE_KEY)
        _complete_ratings(db, suite)
        partial_hr = User(
            username="partial-benchmark-hr",
            email="partial-benchmark-hr@example.test",
            password_hash="not-used",
            display_name="Partial Benchmark HR",
            role="hr",
            is_active=True,
        )
        db.add(partial_hr)
        first = db.scalar(
            select(MatchingBenchmarkCase)
            .where(MatchingBenchmarkCase.suite_id == suite.id)
            .order_by(MatchingBenchmarkCase.sequence)
        )
        assert first is not None
        db.flush()
        db.add(
            MatchingBenchmarkRating(
                case_id=first.id,
                reviewer_id=partial_hr.id,
                reviewer_role="hr",
                verdict="reject",
                reasons=["skill_gap"],
            )
        )
        db.commit()
        hr, _ = _reviewers(db)
        reveal_benchmark_suite(db, suite, hr)
        report = build_benchmark_report(db, suite)
        assert report["suite"]["status"] == "revealed"
        assert len(report["cases"]) == 50
        assert report["metrics"]["top5_overlap_hr"].status == "available"
        assert report["metrics"]["top5_overlap_manager"].denominator == 25
        assert report["metrics"]["role_agreement"].value == 100.0
        assert report["metrics"]["data_completeness"].value is not None
        assert any("合成案例" in warning for warning in report["warnings"])
        assert any("小樣本" in warning for warning in report["warnings"])
        first_case = report["cases"][0]
        assert first_case["system_score"] >= 0
        assert first_case["hr_verdict"] == first_case["manager_verdict"]
        assert first_case["hr_verdict"] == "interview"


def test_insufficient_metric_is_null_not_zero(benchmark_db) -> None:
    with benchmark_db() as db:
        suite = get_benchmark_suite(db, SUITE_KEY)
        suite.status = "revealed"
        db.commit()
        report = build_benchmark_report(db, suite)
        agreement = report["metrics"]["role_agreement"]
        assert agreement.status == "insufficient_data"
        assert agreement.value is None
        assert agreement.numerator is None
        assert agreement.denominator == 0


def test_route_contract_stays_blind_until_reveal(benchmark_db) -> None:
    api = FastAPI()
    api.include_router(benchmark_router, prefix="/api/v1")
    current_user: dict[str, User] = {}

    def override_db():
        with benchmark_db() as db:
            yield db

    with benchmark_db() as db:
        current_user["value"] = _reviewers(db)[0]
    api.dependency_overrides[get_db] = override_db
    api.dependency_overrides[get_current_user] = lambda: current_user["value"]
    with TestClient(api) as client:
        response = client.get(f"/api/v1/matching-benchmark/suites/{SUITE_KEY}/cases")
        assert response.status_code == 200
        body = response.json()
        assert len(body["cases"]) == 50
        serialized = response.text
        assert "system_score" not in serialized
        assert "system_gate_passed" not in serialized
        assert "expected_verdict" not in serialized
        hidden_report = client.get(
            f"/api/v1/matching-benchmark/suites/{SUITE_KEY}/report"
        )
        assert hidden_report.status_code == 409
