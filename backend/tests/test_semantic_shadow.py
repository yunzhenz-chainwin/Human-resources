import json
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.semantic_shadow import router as semantic_shadow_router
from app.db.base import Base
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.candidate import Candidate, CandidateExperience, CandidateSkill
from app.models.matching import MatchResult
from app.models.organization import Department, User
from app.models.recruitment import JobApplication, JobRequisition
from app.models.semantic_shadow import SemanticShadowEvaluation
from app.services import semantic_shadow as semantic_shadow_service


@pytest.fixture()
def semantic_shadow_client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    with testing_session() as db:
        department = Department(id=10, name="Engineering")
        other_department = Department(id=20, name="Sales")
        users = [
            User(
                id=1,
                username="hr-shadow",
                email="hr-shadow@example.test",
                password_hash="not-used",
                display_name="HR",
                role="hr",
            ),
            User(
                id=2,
                username="manager-shadow",
                email="manager-shadow@example.test",
                password_hash="not-used",
                display_name="Manager",
                role="manager",
                department_id=10,
            ),
        ]
        requisition = JobRequisition(
            id=1,
            req_no="SHADOW-001",
            title="Backend Engineer",
            department_id=10,
            employment_type="full_time",
            work_city="台北市",
            min_years=Decimal("3.0"),
            jd="Build APIs",
            skills=["Python"],
            match_weights={
                "required_skills": ["Python", "PostgreSQL"],
                "preferred_skills": ["Docker"],
            },
            status="sourcing",
        )
        candidate = Candidate(
            id=1,
            code="PRIVATE-CODE-001",
            name="Alice Chen",
            gender="F",
            birth_year=1990,
            email="alice.private@example.test",
            phone="0912-345-678",
            address="台北市私人路 99 號",
            photo_path="private/photo/alice.jpg",
            current_company="Secret Employer Ltd",
            current_title="API Developer",
            total_years=Decimal("5.0"),
            highest_education="Private University",
            status="new",
        )
        db.add_all([department, other_department, *users, requisition, candidate])
        db.flush()
        db.add_all(
            [
                CandidateSkill(candidate_id=1, skill="Python", skill_norm="python"),
                CandidateSkill(candidate_id=1, skill="Postgres", skill_norm="postgres"),
                CandidateExperience(
                    candidate_id=1,
                    company="Secret Employer Ltd",
                    title="Backend Developer",
                    years=Decimal("4.0"),
                    description=(
                        "Contact Alice Chen at alice.private@example.test or 0912-345-678"
                    ),
                    sort_order=0,
                ),
                MatchResult(
                    id=1,
                    requisition_id=1,
                    candidate_id=1,
                    gate_passed=True,
                    total_score=Decimal("78.25"),
                    score_breakdown={"gate": {"passed": True, "miss": []}},
                    rank=2,
                    status="recommended",
                ),
            ]
        )
        db.commit()

    test_app = FastAPI()
    test_app.include_router(semantic_shadow_router, prefix="/api/v1")

    def override_db():
        with testing_session() as db:
            yield db

    test_app.dependency_overrides[get_db] = override_db
    test_app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1, role="hr", department_id=None, is_active=True
    )
    with TestClient(test_app) as client:
        yield client, testing_session, test_app
    test_app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def _settings(*, enabled: bool = True, api_key: str | None = "test-key") -> SimpleNamespace:
    return SimpleNamespace(
        gemini_enabled=enabled,
        gemini_api_key=api_key,
        gemini_model="gemini-test-model",
        gemini_timeout_seconds=5.0,
        gemini_max_output_tokens=2048,
    )


def _gemini_payload() -> dict:
    analysis = {
        "semantic_score": 86.5,
        "synonym_evidence": [
            {
                "required_skill": "PostgreSQL",
                "candidate_skill": "Postgres",
                "rationale": "Alice Chen 使用的技能名稱是常見簡稱。",
            }
        ],
        "transferable_experience_evidence": [
            {
                "experience": "Backend Developer 4 年",
                "target_requirement": "Backend Engineer",
                "rationale": "後端 API 經驗可轉移。",
            }
        ],
        "concerns": ["Docker 尚未提供直接證據"],
        "insufficient_data": [],
        "interview_questions": [
            {
                "gap": "Docker",
                "question": "請說明實際使用 Docker 部署服務的經驗。",
                "reason": "確認加分技能。",
            },
            {
                "gap": "不當問題",
                "question": "請說明你的年齡。",
                "reason": "這題必須被安全過濾。",
            },
        ],
    }
    return {
        "candidates": [{"content": {"parts": [{"text": json.dumps(analysis)}]}}],
        "usageMetadata": {
            "promptTokenCount": 120,
            "candidatesTokenCount": 80,
            "thoughtsTokenCount": 30,
            "totalTokenCount": 230,
        },
    }


def test_manual_opt_in_sends_no_pii_and_never_changes_formal_match(
    semantic_shadow_client, monkeypatch
) -> None:
    client, testing_session, _ = semantic_shadow_client
    captured: dict = {}
    monkeypatch.setattr(semantic_shadow_service, "get_settings", lambda: _settings())

    def fake_post(**kwargs):
        captured.update(kwargs)
        return _gemini_payload()

    monkeypatch.setattr(semantic_shadow_service, "_post_gemini", fake_post)
    with testing_session() as db:
        match = db.get(MatchResult, 1)
        before = (match.total_score, match.gate_passed, match.rank, match.status)

    assert client.post(
        "/api/v1/semantic-shadow/matches/1/evaluations",
        json={"acknowledge_experimental": False},
    ).status_code == 422
    response = client.post(
        "/api/v1/semantic-shadow/matches/1/evaluations",
        json={"acknowledge_experimental": True},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["experiment_only"] is True
    assert "不可作為" in body["disclaimer"]
    assert body["source"] == "gemini"
    assert body["semantic_score"] == 86.5
    assert body["total_tokens"] == 230
    # An unsafe/hallucinated demographic question is filtered before persistence.
    assert [item["gap"] for item in body["interview_questions"]] == ["Docker"]
    # If a provider somehow echoes PII, known candidate values are scrubbed locally.
    assert "Alice Chen" not in json.dumps(body, ensure_ascii=False)

    outbound = json.dumps(captured["body"], ensure_ascii=False)
    for forbidden in (
        "Alice Chen",
        "PRIVATE-CODE-001",
        "alice.private@example.test",
        "0912-345-678",
        "台北市私人路 99 號",
        "Secret Employer Ltd",
        "Private University",
        "private/photo/alice.jpg",
        "1990",
    ):
        assert forbidden not in outbound
    assert "API Developer" in outbound
    assert "Postgres" in outbound
    assert captured["api_key"] == "test-key"
    assert "test-key" not in outbound

    with testing_session() as db:
        match = db.get(MatchResult, 1)
        after = (match.total_score, match.gate_passed, match.rank, match.status)
        evaluation = db.scalar(select(SemanticShadowEvaluation))
        assert evaluation is not None
        snapshot = json.dumps(evaluation.prompt_snapshot, ensure_ascii=False)
        assert "Alice Chen" not in snapshot
        assert "Alice Chen" not in evaluation.prompt_text
        assert evaluation.prompt_version == "semantic-shadow-v1-2026-07"
    assert after == before

    comparison = client.get("/api/v1/semantic-shadow/matches/1/comparison")
    assert comparison.status_code == 200
    comparison_body = comparison.json()
    assert comparison_body["formal"]["total_score"] == 78.25
    assert comparison_body["latest_shadow"]["semantic_score"] == 86.5
    assert comparison_body["evaluation_count"] == 1
    assert comparison_body["experiment_only"] is True


@pytest.mark.parametrize(
    ("status_code", "error_code"),
    [(429, "GEMINI_RATE_LIMITED"), (503, "GEMINI_SERVICE_UNAVAILABLE")],
)
def test_gemini_http_failures_persist_safe_fallback_without_formal_mutation(
    semantic_shadow_client, monkeypatch, status_code, error_code
) -> None:
    client, testing_session, _ = semantic_shadow_client
    monkeypatch.setattr(semantic_shadow_service, "get_settings", lambda: _settings())

    def fail_post(**_kwargs):
        request = httpx.Request("POST", "https://gemini.invalid")
        response = httpx.Response(status_code, request=request)
        raise httpx.HTTPStatusError("provider error", request=request, response=response)

    monkeypatch.setattr(semantic_shadow_service, "_post_gemini", fail_post)
    response = client.post(
        "/api/v1/semantic-shadow/matches/1/evaluations",
        json={"acknowledge_experimental": True},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["generation_status"] == "fallback"
    assert body["source"] == "rules_fallback"
    assert body["error_code"] == error_code
    with testing_session() as db:
        match = db.get(MatchResult, 1)
        assert float(match.total_score) == 78.25
        assert match.gate_passed is True
        assert match.rank == 2


@pytest.mark.parametrize(
    "provider_payload",
    [
        [],
        {"candidates": [{"content": {"parts": [{"text": "[]"}]}}]},
        {"candidates": [{"content": {"parts": [{"text": "not-json"}]}}]},
    ],
)
def test_non_object_or_malformed_gemini_json_never_crashes(
    semantic_shadow_client, monkeypatch, provider_payload
) -> None:
    client, _, _ = semantic_shadow_client
    monkeypatch.setattr(semantic_shadow_service, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        semantic_shadow_service,
        "_post_gemini",
        lambda **_kwargs: provider_payload,
    )
    response = client.post(
        "/api/v1/semantic-shadow/matches/1/evaluations",
        json={"acknowledge_experimental": True},
    )
    assert response.status_code == 201
    assert response.json()["error_code"] == "GEMINI_INVALID_RESPONSE"
    assert response.json()["generation_status"] == "fallback"


def test_missing_api_key_never_calls_provider_and_returns_auditable_fallback(
    semantic_shadow_client, monkeypatch
) -> None:
    client, _, _ = semantic_shadow_client
    monkeypatch.setattr(
        semantic_shadow_service,
        "get_settings",
        lambda: _settings(enabled=True, api_key=None),
    )

    def forbidden_call(**_kwargs):
        raise AssertionError("Gemini must not be called without a key")

    monkeypatch.setattr(semantic_shadow_service, "_post_gemini", forbidden_call)
    response = client.post(
        "/api/v1/semantic-shadow/matches/1/evaluations",
        json={"acknowledge_experimental": True},
    )
    assert response.status_code == 201
    assert response.json()["error_code"] == "GEMINI_NOT_CONFIGURED"
    assert response.json()["total_tokens"] == 0


def test_role_department_and_actual_applicant_scope(semantic_shadow_client, monkeypatch) -> None:
    client, testing_session, test_app = semantic_shadow_client
    monkeypatch.setattr(
        semantic_shadow_service,
        "get_settings",
        lambda: _settings(enabled=False, api_key=None),
    )
    trigger = {"acknowledge_experimental": True}

    test_app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=2, role="manager", department_id=10, is_active=True
    )
    assert client.post(
        "/api/v1/semantic-shadow/matches/1/evaluations", json=trigger
    ).status_code == 403

    with testing_session() as db:
        db.add(
            JobApplication(
                requisition_id=1,
                candidate_id=1,
                source="career_site",
                status="submitted",
            )
        )
        db.commit()
    assert client.post(
        "/api/v1/semantic-shadow/matches/1/evaluations", json=trigger
    ).status_code == 201
    assert client.get("/api/v1/semantic-shadow/matches/1/comparison").status_code == 200

    test_app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=3, role="manager", department_id=20, is_active=True
    )
    assert client.post(
        "/api/v1/semantic-shadow/matches/1/evaluations", json=trigger
    ).status_code == 403
    assert client.get("/api/v1/semantic-shadow/matches/1/comparison").status_code == 403

    test_app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=4, role="it", department_id=None, is_active=True
    )
    assert client.post(
        "/api/v1/semantic-shadow/matches/1/evaluations", json=trigger
    ).status_code == 403
