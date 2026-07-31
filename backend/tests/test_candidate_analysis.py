import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.candidate_analysis import router
from app.db.base import Base
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models import (
    AuditLog,
    Candidate,
    DeidentifiedResumeDocument,
    Department,
    JobApplication,
    JobRequisition,
    MatchResult,
    ResumeFile,
    SemanticShadowEvaluation,
    User,
)
from app.services.candidate_analysis import (
    ALGORITHM_VERSION,
    SUPPORTED_PAYLOAD_SCHEMA,
    build_candidate_profile,
)
from app.services.deidentification import MANUAL_PAYLOAD_SCHEMA_VERSION


def _payload(**overrides) -> dict:
    value = {
        "schema_version": SUPPORTED_PAYLOAD_SCHEMA,
        "current_title": "Senior Backend Engineer",
        "total_years": 5.0,
        "skills": ["Python", "FastAPI", "SQL"],
        "experience_roles": [
            {
                "title": "Backend Engineer",
                "years": 5.0,
                "industry": "SaaS",
                # These unexpected fields model a compromised/legacy database row.
                # The analysis profile must still copy only its strict allow-list.
                "company": "Secret Employer Ltd",
                "description": "Contact Alice VeryPrivate at alice@example.test",
            }
        ],
        "highest_education": "bachelor",
        "name": "Alice VeryPrivate",
        "email": "alice@example.test",
        "phone": "0912-345-678",
        "company": "Secret Employer Ltd",
        "school": "Private University",
    }
    value.update(overrides)
    return value


@pytest.fixture()
def analysis_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)

    with testing_session() as db:
        engineering = Department(name="Engineering")
        sales = Department(name="Sales")
        db.add_all([engineering, sales])
        db.flush()
        hr = User(
            username="analysis-hr",
            email="analysis-hr@example.test",
            password_hash="not-used",
            display_name="Analysis HR",
            role="hr",
        )
        manager = User(
            username="engineering-manager",
            email="engineering-manager@example.test",
            password_hash="not-used",
            display_name="Engineering Manager",
            role="manager",
            department_id=engineering.id,
        )
        sales_manager = User(
            username="sales-manager",
            email="sales-manager@example.test",
            password_hash="not-used",
            display_name="Sales Manager",
            role="manager",
            department_id=sales.id,
        )
        db.add_all([hr, manager, sales_manager])
        db.flush()

        primary_candidate = Candidate(
            code="PRIVATE-CANDIDATE-001",
            name="Alice VeryPrivate",
            email="alice@example.test",
            phone="0912-345-678",
            current_company="Secret Employer Ltd",
            status="new",
        )
        outside_candidate = Candidate(
            code="PRIVATE-CANDIDATE-002",
            name="Bob Restricted",
            email="bob@example.test",
            status="new",
        )
        db.add_all([primary_candidate, outside_candidate])
        db.flush()
        primary_resume = ResumeFile(
            candidate_id=primary_candidate.id,
            original_filename="Alice_VeryPrivate_resume.pdf",
            file_hash="a" * 64,
            parse_status="confirmed",
            resume_text="Alice VeryPrivate alice@example.test Secret Employer Ltd",
            parsed_payload={"school": "Private University"},
        )
        outside_resume = ResumeFile(
            candidate_id=outside_candidate.id,
            original_filename="Bob_Restricted_resume.pdf",
            file_hash="c" * 64,
            parse_status="confirmed",
        )
        db.add_all([primary_resume, outside_resume])
        db.flush()

        documents = [
            DeidentifiedResumeDocument(
                source_resume_id=primary_resume.id,
                anonymous_ref="00000000-0000-4000-8000-000000000001",
                version=1,
                source_file_hash=primary_resume.file_hash,
                deidentification_version="rules-v1",
                payload_schema_version=SUPPORTED_PAYLOAD_SCHEMA,
                analysis_payload=_payload(),
                validation_status="analysis_ready",
                validation_summary={},
                created_by=hr.id,
                reviewed_by=hr.id,
            ),
            DeidentifiedResumeDocument(
                source_resume_id=primary_resume.id,
                anonymous_ref="00000000-0000-4000-8000-000000000002",
                version=2,
                source_file_hash=primary_resume.file_hash,
                deidentification_version="rules-v1",
                payload_schema_version=SUPPORTED_PAYLOAD_SCHEMA,
                analysis_payload=_payload(),
                validation_status="review_required",
                validation_summary={},
                created_by=hr.id,
            ),
            DeidentifiedResumeDocument(
                source_resume_id=primary_resume.id,
                anonymous_ref="00000000-0000-4000-8000-000000000003",
                version=3,
                source_file_hash=primary_resume.file_hash,
                deidentification_version="rules-v1",
                payload_schema_version=SUPPORTED_PAYLOAD_SCHEMA,
                analysis_payload=_payload(
                    current_title=None,
                    total_years=None,
                    skills=[],
                    experience_roles=[],
                    highest_education=None,
                ),
                validation_status="analysis_ready",
                validation_summary={},
                created_by=hr.id,
                reviewed_by=hr.id,
            ),
            DeidentifiedResumeDocument(
                source_resume_id=primary_resume.id,
                anonymous_ref="00000000-0000-4000-8000-000000000004",
                version=4,
                source_file_hash="b" * 64,
                deidentification_version="rules-v1",
                payload_schema_version=SUPPORTED_PAYLOAD_SCHEMA,
                analysis_payload=_payload(),
                validation_status="analysis_ready",
                validation_summary={},
                created_by=hr.id,
                reviewed_by=hr.id,
            ),
            DeidentifiedResumeDocument(
                source_resume_id=primary_resume.id,
                anonymous_ref="00000000-0000-4000-8000-000000000005",
                version=5,
                source_file_hash=primary_resume.file_hash,
                deidentification_version="rules-v1",
                payload_schema_version=SUPPORTED_PAYLOAD_SCHEMA,
                analysis_payload=_payload(
                    current_title=None,
                    experience_roles=None,
                    experiences=[
                        {
                            "title": "Backend Engineer",
                            "company": "Secret Employer Ltd",
                        }
                    ],
                ),
                validation_status="analysis_ready",
                validation_summary={},
                created_by=hr.id,
                reviewed_by=hr.id,
            ),
            DeidentifiedResumeDocument(
                source_resume_id=outside_resume.id,
                anonymous_ref="00000000-0000-4000-8000-000000000006",
                version=1,
                source_file_hash=outside_resume.file_hash,
                deidentification_version="rules-v1",
                payload_schema_version=SUPPORTED_PAYLOAD_SCHEMA,
                analysis_payload=_payload(),
                validation_status="analysis_ready",
                validation_summary={},
                created_by=hr.id,
                reviewed_by=hr.id,
            ),
            # A manual upload for which no candidate safe fields could be derived:
            # approved and downloadable, but with no structured payload to analyze.
            DeidentifiedResumeDocument(
                source_resume_id=primary_resume.id,
                anonymous_ref="00000000-0000-4000-8000-000000000007",
                version=6,
                source_file_hash=primary_resume.file_hash,
                deidentification_version="manual-upload-v1",
                payload_schema_version=MANUAL_PAYLOAD_SCHEMA_VERSION,
                analysis_payload={"manual_upload": True},
                validation_status="analysis_ready",
                validation_summary={},
                created_by=hr.id,
                reviewed_by=hr.id,
            ),
        ]
        db.add_all(documents)

        backend = JobRequisition(
            req_no="ENG-001",
            title="Backend Engineer",
            department_id=engineering.id,
            requested_by=manager.id,
            employment_type="full_time",
            work_city="Taipei",
            min_years=Decimal("3.0"),
            jd="Build reliable APIs",
            skills=["Python", "FastAPI", "SQL"],
            match_weights={
                "required_skills": ["Python", "FastAPI"],
                "preferred_skills": ["SQL"],
                "required_industries": ["SaaS"],
            },
            status="sourcing",
        )
        data = JobRequisition(
            req_no="ENG-002",
            title="Data Analyst",
            department_id=engineering.id,
            requested_by=manager.id,
            employment_type="full_time",
            work_city="Taipei",
            min_years=Decimal("2.0"),
            jd="Analyze business data",
            skills=["Python", "Power BI"],
            match_weights={
                "required_skills": ["Python"],
                "preferred_skills": ["Power BI"],
            },
            status="approved",
        )
        sales_role = JobRequisition(
            req_no="SALES-001",
            title="Sales Manager",
            department_id=sales.id,
            requested_by=sales_manager.id,
            employment_type="full_time",
            work_city="Taipei",
            min_years=Decimal("2.0"),
            jd="Lead sales",
            skills=["Negotiation"],
            match_weights={"required_skills": ["Negotiation"]},
            status="interviewing",
        )
        inactive = JobRequisition(
            req_no="ENG-DRAFT",
            title="Backend Engineer",
            department_id=engineering.id,
            requested_by=manager.id,
            employment_type="full_time",
            work_city="Taipei",
            min_years=Decimal("1.0"),
            jd="Draft role",
            skills=["Python"],
            status="draft",
        )
        db.add_all([backend, data, sales_role, inactive])
        db.flush()
        db.add_all(
            [
                JobApplication(
                    requisition_id=backend.id,
                    candidate_id=primary_candidate.id,
                    resume_id=primary_resume.id,
                ),
                JobApplication(
                    requisition_id=sales_role.id,
                    candidate_id=outside_candidate.id,
                    resume_id=outside_resume.id,
                ),
            ]
        )
        db.commit()
        ids = {
            "ready": documents[0].id,
            "pending": documents[1].id,
            "insufficient": documents[2].id,
            "stale": documents[3].id,
            "legacy_experiences": documents[4].id,
            "outside_document": documents[5].id,
            "manual_no_payload": documents[6].id,
            "backend": backend.id,
            "data": data.id,
            "sales": sales_role.id,
            "inactive": inactive.id,
            "engineering_department": engineering.id,
            "sales_department": sales.id,
        }
        actors = {
            "hr": SimpleNamespace(id=hr.id, role="hr", department_id=None, is_active=True),
            "manager": SimpleNamespace(
                id=manager.id,
                role="manager",
                department_id=engineering.id,
                is_active=True,
            ),
            "sales_manager": SimpleNamespace(
                id=sales_manager.id,
                role="manager",
                department_id=sales.id,
                is_active=True,
            ),
        }

    current_actor = {"value": actors["hr"]}

    def override_db():
        with testing_session() as db:
            yield db

    test_app = FastAPI()
    test_app.include_router(router)
    test_app.dependency_overrides[get_db] = override_db
    test_app.dependency_overrides[get_current_user] = lambda: current_actor["value"]
    with TestClient(test_app) as client:
        yield client, testing_session, ids, actors, current_actor
    Base.metadata.drop_all(engine)


def _recommend(client: TestClient, document_id: int):
    return client.post(f"/deidentified-resumes/{document_id}/analyses/recommended-roles")


def _role_match(client: TestClient, document_id: int, requisition_id: int):
    return client.post(
        f"/deidentified-resumes/{document_id}/analyses/role-match",
        json={"requisition_id": requisition_id},
    )


def test_analysis_requires_ready_current_snapshot(analysis_client) -> None:
    client, _, ids, _, _ = analysis_client
    pending = _recommend(client, ids["pending"])
    assert pending.status_code == 409
    assert "not approved" in pending.json()["detail"]

    stale = _recommend(client, ids["stale"])
    assert stale.status_code == 409
    assert "Source resume changed" in stale.json()["detail"]


def test_manual_upload_without_structured_payload_is_refused_clearly(analysis_client) -> None:
    client, _, ids, _, _ = analysis_client
    recommend = _recommend(client, ids["manual_no_payload"])
    assert recommend.status_code == 422
    assert "手動上傳" in recommend.json()["detail"]

    role_match = _role_match(client, ids["manual_no_payload"], ids["backend"])
    assert role_match.status_code == 422
    assert "手動上傳" in role_match.json()["detail"]


def test_recommendations_are_ranked_active_and_do_not_leak_pii(analysis_client) -> None:
    client, _, ids, _, _ = analysis_client
    response = _recommend(client, ids["ready"])
    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["requisition_id"] == ids["backend"]
    assert body["items"][0]["gate_passed"] is True
    assert body["items"][0]["total_score"] == 100
    assert body["algorithm_version"] == ALGORITHM_VERSION
    assert body["ai_used"] is False
    assert body["token_usage"] == 0
    returned_ids = {item["requisition_id"] for item in body["items"]}
    assert ids["inactive"] not in returned_ids
    assert len(body["items"]) <= 5

    serialized = json.dumps(body, ensure_ascii=False)
    for forbidden in (
        "Alice VeryPrivate",
        "alice@example.test",
        "0912-345-678",
        "Secret Employer Ltd",
        "Private University",
        "PRIVATE-CANDIDATE-001",
        "Alice_VeryPrivate_resume.pdf",
        "00000000-0000-4000-8000-000000000001",
        "candidate_id",
        "document_id",
    ):
        assert forbidden not in serialized


def test_selected_role_contract_headers_and_determinism(analysis_client) -> None:
    client, _, ids, _, _ = analysis_client
    first = _role_match(client, ids["ready"], ids["backend"])
    second = _role_match(client, ids["ready"], ids["backend"])
    assert first.status_code == second.status_code == 200
    assert first.json()["item"] == second.json()["item"]
    assert first.json()["item"]["requisition_id"] == ids["backend"]
    assert [component["key"] for component in first.json()["item"]["components"]] == [
        "skills",
        "relevance",
        "years",
        "industry",
    ]
    assert "no-store" in first.headers["cache-control"]
    assert "private" in first.headers["cache-control"]
    assert "max-age=0" in first.headers["cache-control"]
    assert first.headers["pragma"] == "no-cache"
    assert first.headers["expires"] == "0"


def test_manager_is_limited_by_candidate_and_department_scope(analysis_client) -> None:
    client, _, ids, actors, current_actor = analysis_client
    current_actor["value"] = actors["manager"]

    recommendation = _recommend(client, ids["ready"])
    assert recommendation.status_code == 200
    assert {item["department_name"] for item in recommendation.json()["items"]} == {"Engineering"}

    outside_role = _role_match(client, ids["ready"], ids["sales"])
    assert outside_role.status_code == 403

    outside_candidate = _recommend(client, ids["outside_document"])
    assert outside_candidate.status_code == 403


def test_analysis_does_not_persist_results_and_audit_is_metadata_only(
    analysis_client,
) -> None:
    client, testing_session, ids, _, _ = analysis_client
    with testing_session() as db:
        before = (
            db.scalar(select(func.count(MatchResult.id))),
            db.scalar(select(func.count(SemanticShadowEvaluation.id))),
        )

    response = _recommend(client, ids["ready"])
    assert response.status_code == 200

    with testing_session() as db:
        after = (
            db.scalar(select(func.count(MatchResult.id))),
            db.scalar(select(func.count(SemanticShadowEvaluation.id))),
        )
        audit = db.scalar(
            select(AuditLog)
            .where(AuditLog.action == "candidate_analysis.generate")
            .order_by(AuditLog.id.desc())
        )
        assert audit is not None
        assert audit.actor_user_id is not None
        assert audit.created_at is not None
        assert audit.resource_id == str(ids["ready"])
        assert audit.details == {
            "mode": "recommended_roles",
            "document_id": ids["ready"],
            "requisition_ids": [item["requisition_id"] for item in response.json()["items"]],
            "algorithm_version": ALGORITHM_VERSION,
            "success": True,
            "token_usage": 0,
        }
        serialized_audit = json.dumps(audit.details, ensure_ascii=False)
        for forbidden in (
            "total_score",
            "highlights",
            "analysis_payload",
            "Alice VeryPrivate",
            "alice@example.test",
        ):
            assert forbidden not in serialized_audit
    assert after == before


def test_missing_data_is_not_reported_as_a_known_mismatch(analysis_client) -> None:
    client, _, ids, _, _ = analysis_client
    response = _role_match(client, ids["insufficient"], ids["backend"])
    assert response.status_code == 200
    item = response.json()["item"]
    assert item["gate_passed"] is False
    assert item["total_score"] == 50
    assert item["data_completeness"] == 0
    assert item["confidence"] == "low"
    assert len(item["insufficient_data"]) == 4
    assert all(component["known"] is False for component in item["components"])
    assert all(component["score"] is None for component in item["components"])
    assert all(component["miss"] == [] for component in item["components"])


def test_strict_profile_ignores_legacy_experiences_and_rejects_wrong_schema(
    analysis_client,
) -> None:
    client, _, ids, _, _ = analysis_client
    response = _role_match(client, ids["legacy_experiences"], ids["backend"])
    assert response.status_code == 200
    relevance = next(
        component
        for component in response.json()["item"]["components"]
        if component["key"] == "relevance"
    )
    assert relevance["known"] is False
    assert "Secret Employer Ltd" not in json.dumps(response.json(), ensure_ascii=False)

    with pytest.raises(ValueError, match="schema"):
        build_candidate_profile(
            {"schema_version": "unsupported", "skills": ["Python"]},
            payload_schema_version="unsupported",
        )
