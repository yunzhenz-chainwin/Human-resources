from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.main import app
from app.models import (
    Candidate,
    CandidateEducation,
    CandidateSkill,
    JobRequisition,
    MatchResult,
)
from app.services.matching import resolve_weights, score_candidate


@pytest.fixture()
def matching_client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    with testing_session() as db:
        requisition = JobRequisition(
            req_no="MATCH-001",
            title="Backend Engineer",
            employment_type="full_time",
            work_city="台北市",
            salary_min=60000,
            salary_max=80000,
            min_years=Decimal("3.0"),
            education_req="大學",
            jd="Build APIs",
            skills=["Python"],
            match_weights={
                "required_skills": ["Python"],
                "preferred_skills": ["SQL"],
            },
            status="sourcing",
        )
        db.add(requisition)
        db.flush()
        candidates = [
            Candidate(
                code="T-MATCH-1",
                name="Perfect",
                current_title="Backend Engineer",
                total_years=Decimal("5.0"),
                highest_education="大學",
                expected_cities=["台北市"],
                expected_salary_min=60000,
                expected_salary_max=75000,
                status="new",
            ),
            Candidate(
                code="T-MATCH-2",
                name="Eligible",
                current_title="Software Developer",
                total_years=Decimal("3.0"),
                highest_education="碩士",
                expected_cities=["台北市"],
                status="new",
            ),
            Candidate(
                code="T-MATCH-3",
                name="Missing Skill",
                current_title="Backend Engineer",
                total_years=Decimal("8.0"),
                highest_education="碩士",
                expected_cities=["台北市"],
                status="new",
            ),
            Candidate(
                code="T-MATCH-4",
                name="Wrong City",
                current_title="Backend Engineer",
                total_years=Decimal("5.0"),
                highest_education="大學",
                expected_cities=["高雄市"],
                status="new",
            ),
        ]
        db.add_all(candidates)
        db.flush()
        db.add_all(
            [
                CandidateSkill(candidate_id=candidates[0].id, skill="Python", skill_norm="python"),
                CandidateSkill(candidate_id=candidates[0].id, skill="SQL", skill_norm="sql"),
                CandidateSkill(candidate_id=candidates[1].id, skill="python", skill_norm="python"),
                CandidateSkill(candidate_id=candidates[3].id, skill="Python", skill_norm="python"),
                CandidateEducation(
                    candidate_id=candidates[0].id,
                    school="Example University",
                    degree="學士",
                    sort_order=0,
                ),
            ]
        )
        db.commit()

    def override_db():
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1, role="admin", department_id=None, is_active=True
    )
    with TestClient(app) as client:
        yield client, testing_session
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def test_score_is_deterministic_and_gates_hard_requirements(matching_client) -> None:
    _, testing_session = matching_client
    with testing_session() as db:
        requisition = db.get(JobRequisition, 1)
        candidates = list(db.scalars(select(Candidate).order_by(Candidate.id)).all())
        perfect = score_candidate(requisition, candidates[0], ["Python", "SQL"])
        repeated = score_candidate(requisition, candidates[0], ["Python", "SQL"])
        assert perfect == repeated
        assert perfect.gate_passed is True
        assert 0 <= perfect.total_score <= 100
        assert perfect.breakdown["skill"]["hit"] == ["Python", "SQL"]

        missing = score_candidate(requisition, candidates[2], [])
        assert missing.gate_passed is False
        assert missing.total_score == 0
        assert "required_skills" in missing.breakdown["gate"]["miss"]

        wrong_city = score_candidate(requisition, candidates[3], ["Python"])
        assert wrong_city.gate_passed is False
        assert "location" in wrong_city.breakdown["gate"]["miss"]
        assert sum(resolve_weights({"skill": 9}).values()) == pytest.approx(1.0)


def test_rematch_ranks_and_preserves_manual_status(matching_client) -> None:
    client, _ = matching_client
    response = client.post("/api/v1/requisitions/1/rematch")
    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["rank"] for item in items] == [1, 2]
    assert items[0]["candidate"]["name"] == "Perfect"
    assert items[0]["total_score"] > items[1]["total_score"]

    match_id = items[0]["id"]
    feedback = client.post(
        f"/api/v1/matches/{match_id}/feedback",
        json={"status": "rejected_by_manager", "reason": "Industry mismatch"},
    )
    assert feedback.status_code == 200
    assert feedback.json()["feedback_reason"] == "Industry mismatch"
    assert (
        client.post(
            f"/api/v1/matches/{items[1]['id']}/feedback",
            json={"status": "rejected_by_manager"},
        ).status_code
        == 422
    )

    rerun = client.post("/api/v1/requisitions/1/rematch")
    assert rerun.status_code == 200
    preserved = client.get(
        "/api/v1/requisitions/1/matches", params={"status": "rejected_by_manager"}
    ).json()
    assert preserved["total"] == 1
    assert preserved["items"][0]["id"] == match_id

    all_results = client.get(
        "/api/v1/requisitions/1/matches", params={"include_ineligible": "true"}
    ).json()
    assert all_results["total"] == 4
    assert sum(not item["gate_passed"] for item in all_results["items"]) == 2


def test_match_unique_pair_and_score_constraints(matching_client) -> None:
    client, testing_session = matching_client
    assert client.post("/api/v1/requisitions/1/rematch").status_code == 200
    with testing_session() as db:
        db.add(
            MatchResult(
                requisition_id=1,
                candidate_id=1,
                gate_passed=True,
                total_score=101,
                score_breakdown={},
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
