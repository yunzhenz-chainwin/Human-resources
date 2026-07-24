from datetime import UTC, datetime
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
    Department,
    JobApplication,
    JobRequisition,
    MatchResult,
)
from app.services.matching import assess_matching_readiness, resolve_weights, score_candidate


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
        assert 0 <= missing.total_score <= 100
        assert "required_skills" in missing.breakdown["gate"]["miss"]
        assert missing.breakdown["highlights"][0]["text"].startswith(
            "未通過必要條件：必要技能"
        )
        assert "required_skills" not in missing.breakdown["highlights"][0]["text"]

        wrong_city = score_candidate(requisition, candidates[3], ["Python"])
        assert wrong_city.gate_passed is False
        assert "location" in wrong_city.breakdown["gate"]["miss"]

        # A current city is still location evidence when expected_cities is absent;
        # the hard gate and component score must use the same source of truth.
        candidates[1].city = "高雄市"
        candidates[1].expected_cities = None
        current_city_mismatch = score_candidate(requisition, candidates[1], ["Python"])
        assert current_city_mismatch.gate_passed is False
        assert "location" in current_city_mismatch.breakdown["gate"]["miss"]
        assert current_city_mismatch.breakdown["location"]["score"] == 0.2
        assert sum(resolve_weights({"skill": 9}).values()) == pytest.approx(1.0)


def test_skill_alias_has_auditable_evidence(matching_client) -> None:
    _, testing_session = matching_client
    with testing_session() as db:
        requisition = db.get(JobRequisition, 1)
        requisition.match_weights = {
            "required_skills": ["PostgreSQL"],
            "preferred_skills": ["FastAPI"],
        }
        candidate = db.get(Candidate, 1)
        result = score_candidate(requisition, candidate, ["Postgres", "Fast API"])
        assert result.gate_passed is True
        assert result.breakdown["skill"]["evidence"] == {
            "PostgreSQL": "Postgres",
            "FastAPI": "Fast API",
        }
        assert result.breakdown["recommendation"] in {"strong", "potential", "review"}
        assert "missing" in result.breakdown["data_quality"]


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


def test_candidate_match_overview_includes_uncomputed_people(matching_client) -> None:
    client, testing_session = matching_client
    before = client.get("/api/v1/requisitions/1/candidate-match-overview")
    assert before.status_code == 200
    assert before.json()["total_candidates"] == 4
    assert before.json()["computed_count"] == 0
    assert before.json()["uncomputed_count"] == 4
    assert all(item["match"] is None for item in before.json()["items"])

    assert client.post("/api/v1/requisitions/1/rematch").status_code == 200
    with testing_session() as db:
        deleted = db.scalar(select(Candidate).where(Candidate.code == "T-MATCH-4"))
        deleted.deleted_at = datetime.now(UTC)
        db.commit()

    after = client.get("/api/v1/requisitions/1/candidate-match-overview")
    assert after.status_code == 200
    assert after.json()["total_candidates"] == 3
    assert after.json()["computed_count"] == 3
    assert after.json()["uncomputed_count"] == 0
    assert all(item["match"] is not None for item in after.json()["items"])


def test_manager_match_overview_only_exposes_actual_applicants(
    matching_client,
) -> None:
    client, testing_session = matching_client
    with testing_session() as db:
        db.add(
            JobApplication(
                requisition_id=1,
                candidate_id=1,
                status="submitted",
                source="career_site",
            )
        )
        db.add_all(
            [
                MatchResult(
                    requisition_id=1,
                    candidate_id=2,
                    gate_passed=True,
                    total_score=75,
                    score_breakdown={"gate": {"passed": True, "miss": []}},
                    status="recommended",
                ),
                MatchResult(
                    requisition_id=1,
                    candidate_id=3,
                    gate_passed=False,
                    total_score=50,
                    score_breakdown={"gate": {"passed": False, "miss": ["required_skills"]}},
                    status="ineligible",
                ),
            ]
        )
        # The requisition belongs to a department; the viewing manager must own that
        # same department (a null-department manager is now correctly rejected).
        db.get(JobRequisition, 1).department_id = 5
        db.commit()

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=10, role="manager", department_id=5, is_active=True
    )
    manager_response = client.get("/api/v1/requisitions/1/candidate-match-overview")
    assert manager_response.status_code == 200
    assert {
        item["candidate"]["id"] for item in manager_response.json()["items"]
    } == {1}

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1, role="hr", department_id=None, is_active=True
    )
    hr_response = client.get("/api/v1/requisitions/1/candidate-match-overview")
    assert hr_response.status_code == 200
    assert hr_response.json()["total_candidates"] == 4


def test_manager_can_update_only_matches_for_actual_own_department_applicants(
    matching_client,
) -> None:
    client, testing_session = matching_client
    criteria = client.get("/api/v1/requisitions/1/matching-criteria").json()
    rematched = client.post("/api/v1/requisitions/1/rematch")
    assert rematched.status_code == 200
    matches_by_candidate = {
        item["candidate_id"]: item["id"] for item in rematched.json()["items"]
    }
    applied_match_id = matches_by_candidate[1]
    unapplied_match_id = matches_by_candidate[2]

    with testing_session() as db:
        own_department = Department(name="Product")
        other_department = Department(name="Sales")
        db.add_all([own_department, other_department])
        db.flush()
        requisition = db.get(JobRequisition, 1)
        assert requisition is not None
        requisition.department_id = own_department.id
        db.add(
            JobApplication(
                requisition_id=requisition.id,
                candidate_id=1,
                status="submitted",
                source="career_site",
            )
        )
        db.commit()
        own_department_id = own_department.id
        other_department_id = other_department.id

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=10,
        role="manager",
        department_id=own_department_id,
        is_active=True,
    )
    assert client.put(
        "/api/v1/requisitions/1/matching-criteria",
        json=criteria,
    ).status_code == 403
    assert client.post("/api/v1/requisitions/1/rematch").status_code == 403

    status_response = client.post(
        f"/api/v1/matches/{applied_match_id}/status",
        json={"status": "interview"},
    )
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "interview"
    feedback_response = client.post(
        f"/api/v1/matches/{applied_match_id}/feedback",
        json={"status": "rejected_by_manager", "reason": "Role expectations differ"},
    )
    assert feedback_response.status_code == 200
    assert feedback_response.json()["status"] == "rejected_by_manager"
    assert feedback_response.json()["feedback_reason"] == "Role expectations differ"

    assert client.post(
        f"/api/v1/matches/{unapplied_match_id}/status",
        json={"status": "interview"},
    ).status_code == 403
    assert client.post(
        f"/api/v1/matches/{unapplied_match_id}/feedback",
        json={"status": "rejected_by_manager", "reason": "Must not update"},
    ).status_code == 403
    with testing_session() as db:
        unapplied = db.get(MatchResult, unapplied_match_id)
        assert unapplied is not None
        assert unapplied.status == "recommended"
        assert unapplied.feedback_reason is None

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=11,
        role="manager",
        department_id=other_department_id,
        is_active=True,
    )
    assert client.post(
        f"/api/v1/matches/{applied_match_id}/status",
        json={"status": "interview"},
    ).status_code == 403

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1,
        role="hr",
        department_id=other_department_id,
        is_active=True,
    )
    assert client.post(
        f"/api/v1/matches/{unapplied_match_id}/status",
        json={"status": "shortlisted"},
    ).status_code == 200


def test_hr_can_update_matching_criteria_and_recalculate(matching_client) -> None:
    client, _ = matching_client
    response = client.put(
        "/api/v1/requisitions/1/matching-criteria",
        json={
            "required_skills": ["Python"],
            "preferred_skills": ["SQL", "Git"],
            "min_years": 2,
            "education_req": "大學",
            "work_city": "台北市",
            "salary_min": 60000,
            "salary_max": 90000,
            "require_skills": True,
            "require_years": False,
            "require_education": True,
            "require_location": False,
        },
    )
    assert response.status_code == 200
    assert response.json()["preferred_skills"] == ["SQL", "Git"]
    overview = client.get("/api/v1/requisitions/1/candidate-match-overview").json()
    assert overview["computed_count"] == 4


def test_relative_weights_are_normalized_validated_and_used(matching_client) -> None:
    client, testing_session = matching_client
    criteria = client.get("/api/v1/requisitions/1/matching-criteria")
    assert criteria.status_code == 200
    assert sum(criteria.json()["weights"].values()) == pytest.approx(1.0)

    response = client.put(
        "/api/v1/requisitions/1/matching-weights",
        json={
            "skill": 80,
            "relevance": 10,
            "years": 5,
            "salary": 2,
            "education": 2,
            "location": 1,
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "skill": 0.8,
        "relevance": 0.1,
        "years": 0.05,
        "salary": 0.02,
        "education": 0.02,
        "location": 0.01,
    }
    assert client.put(
        "/api/v1/requisitions/1/matching-weights",
        json={key: 0 for key in response.json()},
    ).status_code == 422
    missing = dict(response.json())
    missing.pop("location")
    assert client.put(
        "/api/v1/requisitions/1/matching-weights", json=missing
    ).status_code == 422

    with testing_session() as db:
        result = db.scalar(
            select(MatchResult).where(
                MatchResult.requisition_id == 1,
                MatchResult.candidate_id == 1,
            )
        )
        assert result is not None
        assert result.score_breakdown["skill"]["weight"] == 0.8
        assert result.highlights


def test_department_manager_can_adjust_only_own_job_weights(matching_client) -> None:
    client, testing_session = matching_client
    with testing_session() as db:
        own_department = Department(name="Weight Owner")
        other_department = Department(name="Weight Other")
        db.add_all([own_department, other_department])
        db.flush()
        db.get(JobRequisition, 1).department_id = own_department.id
        db.commit()
        own_id, other_id = own_department.id, other_department.id

    payload = {
        "skill": 60,
        "relevance": 20,
        "years": 10,
        "salary": 5,
        "education": 3,
        "location": 2,
    }
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=10, role="manager", department_id=own_id, is_active=True
    )
    assert client.put(
        "/api/v1/requisitions/1/matching-weights", json=payload
    ).status_code == 200

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=11, role="manager", department_id=other_id, is_active=True
    )
    assert client.put(
        "/api/v1/requisitions/1/matching-weights", json=payload
    ).status_code == 403


def test_personality_trait_questions_are_job_specific_and_scoped(matching_client) -> None:
    client, testing_session = matching_client
    response = client.post(
        "/api/v1/requisitions/1/interview-question-suggestions",
        json={"personality_traits": ["細心", "抗壓性", "細心"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["job_title"] == "Backend Engineer"
    assert [item["trait"] for item in body["suggestions"]] == ["細心", "抗壓性"]
    assert all(len(item["questions"]) == 3 for item in body["suggestions"])
    assert "Backend Engineer" in body["suggestions"][0]["questions"][0]["question"]
    assert body["guidance"]
    assert client.post(
        "/api/v1/requisitions/1/interview-question-suggestions",
        json={"personality_traits": ["   "]},
    ).status_code == 422

    with testing_session() as db:
        db.get(JobRequisition, 1).department_id = 20
        db.commit()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=12, role="manager", department_id=21, is_active=True
    )
    assert client.post(
        "/api/v1/requisitions/1/interview-question-suggestions",
        json={"personality_traits": ["創意"]},
    ).status_code == 403


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


def test_matching_readiness_supports_shadow_pilot(matching_client) -> None:
    client, testing_session = matching_client
    assert client.post("/api/v1/requisitions/1/rematch").status_code == 200
    response = client.get("/api/v1/requisitions/1/match-readiness")
    assert response.status_code == 200
    readiness = response.json()
    assert readiness["pilot_status"] == "ready_for_shadow_pilot"
    assert readiness["metrics"]["candidate_count"] == 4
    assert readiness["metrics"]["eligible_count"] == 2
    assert "semantic_embeddings_shadow_score" in readiness["next_experiments"]
    assert "age" in readiness["excluded_features"]

    with testing_session() as db:
        results = list(db.scalars(select(MatchResult)).all())
        report = assess_matching_readiness(results)
        assert 0 <= report["metrics"]["data_completeness"] <= 1


def test_matching_accuracy_improvements(matching_client) -> None:
    _, testing_session = matching_client
    with testing_session() as db:
        requisition = db.get(JobRequisition, 1)  # 台北市, min 3y, 大學, title Backend Engineer
        candidate = db.get(Candidate, 1)  # 台北市, 5y, 大學 -> clears the non-skill gates

        # Chinese<->English skill synonym is matched with auditable evidence.
        requisition.match_weights = {"required_skills": ["Project Management"]}
        cross_lang = score_candidate(requisition, candidate, ["專案管理"])
        assert cross_lang.gate_passed is True
        assert cross_lang.breakdown["skill"]["evidence"] == {"Project Management": "專案管理"}

        # Version/punctuation variant via the alias table.
        requisition.match_weights = {"required_skills": ["React"]}
        assert score_candidate(requisition, candidate, ["React.js"]).gate_passed is True

        # Conservative fuzzy matches a near-spelling but never merges distinct skills.
        requisition.match_weights = {"required_skills": ["JavaScript"]}
        assert score_candidate(requisition, candidate, ["Javascripts"]).gate_passed is True
        assert score_candidate(requisition, candidate, ["Java"]).gate_passed is False

        # required_skill_ratio softens the all-or-nothing skill gate.
        requisition.match_weights = {"required_skills": ["Python", "Go"]}
        assert score_candidate(requisition, candidate, ["Python"]).gate_passed is False
        requisition.match_weights = {
            "required_skills": ["Python", "Go"],
            "required_skill_ratio": 0.5,
        }
        assert score_candidate(requisition, candidate, ["Python"]).gate_passed is True

        # Location gate now accepts an adjacent city instead of excluding it.
        requisition.match_weights = {}
        candidate.expected_cities = ["新北市"]
        adjacent = score_candidate(requisition, candidate, ["Python"])
        assert adjacent.gate_passed is True
        assert "location" not in adjacent.breakdown["gate"]["miss"]

        # Cross-language title relevance: 資深後端工程師 aligns with Backend Engineer.
        candidate.expected_cities = ["台北市"]
        candidate.current_title = "資深後端工程師"
        cross_title = score_candidate(requisition, candidate, ["Python"])
        assert cross_title.breakdown["relevance"]["score"] >= 0.6

        # near_miss surfaces a strong candidate gated by a single hard requirement.
        candidate.current_title = "Backend Engineer"
        requisition.match_weights = {
            "required_skills": ["Kubernetes"],
            "preferred_skills": ["Python"],
        }
        near = score_candidate(requisition, candidate, ["Python", "SQL", "Docker"])
        assert near.gate_passed is False
        assert near.breakdown["gate"]["miss"] == ["required_skills"]
        assert near.breakdown["near_miss"] is True
