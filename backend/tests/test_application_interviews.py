import json
from collections.abc import Generator
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.api.routes import interview_records as interview_routes
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.models import (
    Candidate,
    CandidateEducation,
    CandidateExperience,
    CandidateSkill,
    Department,
    InterviewQuestionPlan,
    InterviewRecord,
    JobApplication,
    JobRequisition,
    ResumeFile,
    User,
)
from app.models.security import AuditLog
from app.services.interview_questions import GeminiTokenUsage
from app.services.security import hash_password

PASSWORDS = {
    "admin": "Applications-Admin-Password-123",
    "hr": "Applications-HR-Password-123",
    "it": "Applications-IT-Password-123",
    "engineering-manager": "Applications-Engineering-Password-123",
    "design-manager": "Applications-Design-Password-123",
}

APPLICATION_KEYS = {
    "id",
    "candidate_id",
    "requisition_id",
    "status",
    "source",
    "applied_at",
    "resume_id",
    "cover_letter",
    "linkedin_url",
    "portfolio_url",
    "interview_at",
    "interview_result",
    "interview_notes",
    "hr_interview",
    "manager_interview",
    "composite_score",
    "composite_score_breakdown",
    "candidate",
    "requisition",
}


@pytest.fixture()
def application_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[TestClient, sessionmaker, dict[str, int]], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    settings = get_settings()
    original = {
        "auth_secret_key": settings.auth_secret_key,
        "bootstrap_admin_username": settings.bootstrap_admin_username,
        "bootstrap_admin_email": settings.bootstrap_admin_email,
        "bootstrap_admin_password": settings.bootstrap_admin_password,
        "gemini_enabled": settings.gemini_enabled,
        "gemini_api_key": settings.gemini_api_key,
    }
    settings.auth_secret_key = "application-test-secret-key-with-at-least-32-bytes"
    settings.bootstrap_admin_username = None
    settings.bootstrap_admin_email = None
    settings.bootstrap_admin_password = None
    settings.gemini_enabled = False
    settings.gemini_api_key = None

    with testing_session() as db:
        engineering = Department(name="Application Engineering")
        design = Department(name="Application Design")
        db.add_all([engineering, design])
        db.flush()
        users = [
            User(
                username="admin",
                email="application-admin@example.test",
                password_hash=hash_password(PASSWORDS["admin"]),
                display_name="Application Admin",
                role="admin",
                is_active=True,
            ),
            User(
                username="hr",
                email="application-hr@example.test",
                password_hash=hash_password(PASSWORDS["hr"]),
                display_name="Application HR",
                role="hr",
                is_active=True,
            ),
            User(
                username="it",
                email="application-it@example.test",
                password_hash=hash_password(PASSWORDS["it"]),
                display_name="Application IT",
                role="it",
                is_active=True,
            ),
            User(
                username="engineering-manager",
                email="application-engineering@example.test",
                password_hash=hash_password(PASSWORDS["engineering-manager"]),
                display_name="Engineering Manager",
                role="manager",
                department_id=engineering.id,
                is_active=True,
            ),
            User(
                username="design-manager",
                email="application-design@example.test",
                password_hash=hash_password(PASSWORDS["design-manager"]),
                display_name="Design Manager",
                role="manager",
                department_id=design.id,
                is_active=True,
            ),
        ]
        db.add_all(users)
        candidates = [
            Candidate(
                code="APP-CAND-001",
                name="Alice Applicant",
                email="alice@app.test",
                phone="0912-345-678",
                city="Taipei",
                source="direct",
            ),
            Candidate(
                code="APP-CAND-002",
                name="Bob Applicant",
                email="bob@app.test",
                source="direct",
            ),
            Candidate(
                code="APP-CAND-003",
                name="Deleted Applicant",
                source="direct",
                deleted_at=datetime.now(UTC),
            ),
        ]
        db.add_all(candidates)
        db.flush()
        engineering_job = JobRequisition(
            req_no="APP-ENG-001",
            title="Application Backend Engineer",
            department_id=engineering.id,
            employment_type="full_time",
            work_city="Taipei",
            jd="Build application APIs",
            status="approved",
        )
        design_job = JobRequisition(
            req_no="APP-DES-001",
            title="Application Product Designer",
            department_id=design.id,
            employment_type="full_time",
            work_city="Taipei",
            jd="Design application flows",
            status="approved",
        )
        db.add_all([engineering_job, design_job])
        db.flush()
        engineering_application = JobApplication(
            requisition_id=engineering_job.id,
            candidate_id=candidates[0].id,
            status="submitted",
            source="career_site",
        )
        design_application = JobApplication(
            requisition_id=design_job.id,
            candidate_id=candidates[1].id,
            status="submitted",
            source="career_site",
        )
        db.add_all([engineering_application, design_application])
        db.commit()
        ids = {
            "engineering": engineering.id,
            "design": design.id,
            "alice": candidates[0].id,
            "bob": candidates[1].id,
            "deleted": candidates[2].id,
            "engineering_job": engineering_job.id,
            "design_job": design_job.id,
            "engineering_application": engineering_application.id,
            "design_application": design_application.id,
            "engineering_manager": users[3].id,
            "design_manager": users[4].id,
        }

    def override_db():
        with testing_session() as db:
            yield db

    main_module.app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(main_module, "SessionLocal", testing_session)
    try:
        with TestClient(main_module.app) as client:
            yield client, testing_session, ids
    finally:
        main_module.app.dependency_overrides.clear()
        for key, value in original.items():
            setattr(settings, key, value)
        Base.metadata.drop_all(engine)


def _headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORDS[username]},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _assert_aware(value: str) -> None:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() is not None


def test_application_listing_is_role_and_department_scoped(application_client) -> None:
    client, _, ids = application_client
    assert client.get("/api/v1/applications").status_code == 401
    assert client.get("/api/v1/applications", headers=_headers(client, "it")).status_code == 403

    hr_response = client.get("/api/v1/applications", headers=_headers(client, "hr"))
    assert hr_response.status_code == 200
    assert {item["id"] for item in hr_response.json()} == {
        ids["engineering_application"],
        ids["design_application"],
    }
    assert all(set(item) == APPLICATION_KEYS for item in hr_response.json())
    assert all(item["candidate"]["id"] == item["candidate_id"] for item in hr_response.json())
    assert all(item["requisition"]["id"] == item["requisition_id"] for item in hr_response.json())
    hr_alice = next(
        item for item in hr_response.json() if item["candidate_id"] == ids["alice"]
    )
    assert hr_alice["candidate"]["email"] == "alice@app.test"
    assert hr_alice["candidate"]["phone"] == "0912-345-678"
    assert hr_alice["candidate"]["city"] == "Taipei"
    for item in hr_response.json():
        _assert_aware(item["applied_at"])

    engineering_headers = _headers(client, "engineering-manager")
    own = client.get("/api/v1/applications", headers=engineering_headers)
    assert own.status_code == 200
    assert [item["id"] for item in own.json()] == [ids["engineering_application"]]
    assert own.json()[0]["candidate"]["email"] == "a***@app.test"
    assert own.json()[0]["candidate"]["phone"] == "*******678"
    assert own.json()[0]["candidate"]["city"] is None
    assert (
        client.get(
            f"/api/v1/applications?department_id={ids['design']}",
            headers=engineering_headers,
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"/api/v1/applications?requisition_id={ids['design_job']}",
            headers=engineering_headers,
        ).status_code
        == 403
    )
    own_filter = client.get(
        f"/api/v1/applications?requisition_id={ids['engineering_job']}",
        headers=engineering_headers,
    )
    assert own_filter.status_code == 200
    assert [item["id"] for item in own_filter.json()] == [ids["engineering_application"]]

    design_filter = client.get(
        f"/api/v1/applications?department_id={ids['design']}",
        headers=_headers(client, "admin"),
    )
    assert design_filter.status_code == 200
    assert [item["id"] for item in design_filter.json()] == [ids["design_application"]]


def test_manager_candidate_detail_is_department_scoped_and_resume_download_is_audited(
    application_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, testing_session, ids = application_client
    fixture_root = Path(__file__).parent / "fixtures" / "resumes"
    stored_paths = {
        "scoped/engineering.pdf": fixture_root / "generic_synthetic_v1.txt",
        "scoped/design.pdf": fixture_root / "p104_synthetic_v1.txt",
    }

    class FixtureStorageProvider:
        def exists(self, key: str) -> bool:
            return key in stored_paths

        def materialize(self, key: str):
            path = stored_paths.get(key)
            if path is None:
                raise FileNotFoundError(key)
            return nullcontext(path)

    monkeypatch.setattr(
        "app.api.routes.resumes.get_storage_provider",
        lambda: FixtureStorageProvider(),
    )
    monkeypatch.setattr(
        "app.api.routes.candidates.get_storage_provider",
        lambda: FixtureStorageProvider(),
    )
    engineering_bytes = stored_paths["scoped/engineering.pdf"].read_bytes()

    with testing_session() as db:
        candidate = db.get(Candidate, ids["alice"])
        assert candidate is not None
        candidate.summary = "Platform engineer with product delivery experience"
        candidate.current_company = "Example Platform"
        candidate.highest_education = "master"
        db.add_all(
            [
                CandidateSkill(candidate_id=candidate.id, skill="Python", skill_norm="python"),
                CandidateExperience(
                    candidate_id=candidate.id,
                    company="Example Platform",
                    title="Senior Engineer",
                    start_ym="2022-01",
                    years=4,
                    sort_order=0,
                ),
                CandidateEducation(
                    candidate_id=candidate.id,
                    school="Example University",
                    major="Computer Science",
                    degree="master",
                    sort_order=0,
                ),
            ]
        )
        engineering_application = db.get(JobApplication, ids["engineering_application"])
        assert engineering_application is not None
        engineering_application.cover_letter = "Engineering-only cover letter"
        engineering_application.linkedin_url = "javascript:alert('blocked')"
        engineering_application.portfolio_url = "https://portfolio.example/engineering"
        engineering_resume = ResumeFile(
            candidate_id=candidate.id,
            target_requisition_id=ids["engineering_job"],
            original_filename="engineering.pdf",
            storage_key="scoped/engineering.pdf",
            mime="application/pdf",
            source_platform="direct",
            source_review_required=False,
            parse_status="confirmed",
            parsed_payload={"skills": ["Python", "SQL"], "experience": "Platform APIs"},
        )
        db.add(engineering_resume)
        db.commit()
        engineering_resume_id = engineering_resume.id

    engineering_headers = _headers(client, "engineering-manager")
    design_headers = _headers(client, "design-manager")
    assert (
        client.get(f"/api/v1/candidates/{ids['alice']}", headers=design_headers).status_code == 403
    )

    with testing_session() as db:
        design_application = JobApplication(
            requisition_id=ids["design_job"],
            candidate_id=ids["alice"],
            status="submitted",
            source="manual_hr",
            cover_letter="Design-only private cover letter",
            linkedin_url="https://linkedin.example/design-candidate",
            portfolio_url="https://portfolio.example/design",
        )
        design_resume = ResumeFile(
            candidate_id=ids["alice"],
            target_requisition_id=ids["design_job"],
            original_filename="design.pdf",
            storage_key="scoped/design.pdf",
            mime="application/pdf",
            source_platform="direct",
            source_review_required=False,
            parse_status="confirmed",
            resume_url="javascript:alert('blocked')",
        )
        db.add_all([design_application, design_resume])
        db.commit()
        design_resume_id = design_resume.id

    engineering_detail = client.get(
        f"/api/v1/candidates/{ids['alice']}", headers=engineering_headers
    )
    assert engineering_detail.status_code == 200
    engineering_body = engineering_detail.json()
    assert engineering_body["skills"] == ["Python"]
    assert engineering_body["experiences"][0]["title"] == "Senior Engineer"
    assert engineering_body["educations"][0]["school"] == "Example University"
    assert engineering_body["email"] == "a***@app.test"
    assert engineering_body["phone"] == "*******678"
    assert engineering_body["city"] is None
    assert len(engineering_body["applications"]) == 1
    assert engineering_body["applications"][0]["requisition_id"] == ids["engineering_job"]
    assert engineering_body["applications"][0]["resume_id"] is None
    assert engineering_body["applications"][0]["resume"] is None
    assert engineering_body["applications"][0]["cover_letter"] == ("Engineering-only cover letter")
    assert engineering_body["applications"][0]["linkedin_url"] is None
    assert "Design-only private cover letter" not in engineering_detail.text
    assert engineering_body["resumes"] == []

    design_detail = client.get(f"/api/v1/candidates/{ids['alice']}", headers=design_headers)
    assert design_detail.status_code == 200
    design_body = design_detail.json()
    assert len(design_body["applications"]) == 1
    assert design_body["applications"][0]["requisition_id"] == ids["design_job"]
    assert "Engineering-only cover letter" not in design_detail.text
    assert design_body["resumes"] == []

    denied_download = client.get(
        f"/api/v1/resumes/{engineering_resume_id}/file",
        headers={**engineering_headers, "User-Agent": "candidate-detail-test"},
    )
    assert denied_download.status_code == 403
    denied_preview = client.get(
        f"/api/v1/resumes/{engineering_resume_id}/preview",
        headers={**engineering_headers, "User-Agent": "candidate-preview-test"},
    )
    assert denied_preview.status_code == 403
    assert client.get("/api/v1/resumes", headers=engineering_headers).status_code == 403
    assert (
        client.get(f"/api/v1/resumes/{engineering_resume_id}", headers=engineering_headers)
        .status_code
        == 403
    )

    hr_headers = _headers(client, "hr")
    own_download = client.get(
        f"/api/v1/resumes/{engineering_resume_id}/file",
        headers={**hr_headers, "User-Agent": "candidate-detail-test"},
    )
    assert own_download.status_code == 200
    assert own_download.content == engineering_bytes
    assert own_download.headers["cache-control"] == "private, no-store"
    assert "engineering.pdf" in own_download.headers["content-disposition"]

    own_preview = client.get(
        f"/api/v1/resumes/{engineering_resume_id}/preview",
        headers={**hr_headers, "User-Agent": "candidate-preview-test"},
    )
    assert own_preview.status_code == 200
    assert own_preview.content == engineering_bytes
    assert own_preview.headers["content-type"] == "application/pdf"
    assert own_preview.headers["cache-control"] == "private, no-store"
    assert own_preview.headers["x-content-type-options"] == "nosniff"
    assert own_preview.headers["x-frame-options"] == "SAMEORIGIN"
    assert own_preview.headers["content-disposition"].startswith("inline;")
    assert "engineering.pdf" in own_preview.headers["content-disposition"]
    assert (
        client.get(
            f"/api/v1/resumes/{design_resume_id}/file",
            headers=engineering_headers,
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"/api/v1/resumes/{design_resume_id}/preview",
            headers=engineering_headers,
        ).status_code
        == 403
    )

    with testing_session() as db:
        missing_resume = ResumeFile(
            candidate_id=ids["alice"],
            target_requisition_id=ids["engineering_job"],
            original_filename="missing.pdf",
            storage_key="scoped/missing.pdf",
            mime="application/pdf",
            source_platform="direct",
            source_review_required=False,
            parse_status="confirmed",
        )
        db.add(missing_resume)
        db.commit()
        missing_resume_id = missing_resume.id

    missing_preview = client.get(
        f"/api/v1/resumes/{missing_resume_id}/preview",
        headers=hr_headers,
    )
    assert missing_preview.status_code == 404
    assert missing_preview.json()["detail"] == "Stored resume file was not found"

    with testing_session() as db:
        download_audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "resume.download",
                AuditLog.resource_id == str(engineering_resume_id),
            )
        )
        assert download_audit is not None
        assert download_audit.department_id is None
        assert download_audit.details["candidate_id"] == ids["alice"]
        assert download_audit.ip_address is not None

        preview_audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "resume.preview",
                AuditLog.resource_id == str(engineering_resume_id),
            )
        )
        assert preview_audit is not None
        assert preview_audit.department_id is None
        assert preview_audit.details == {
            "candidate_id": ids["alice"],
            "target_requisition_id": ids["engineering_job"],
            "format": "pdf",
        }
        assert preview_audit.ip_address is not None
        assert (
            db.scalar(
                select(AuditLog).where(
                    AuditLog.action == "resume.preview",
                    AuditLog.resource_id == str(missing_resume_id),
                )
            )
            is None
        )


def test_manager_cannot_read_unconfirmed_or_system_generated_resume_files(
    application_client,
) -> None:
    client, testing_session, ids = application_client
    with testing_session() as db:
        unconfirmed = ResumeFile(
            candidate_id=ids["alice"],
            target_requisition_id=ids["engineering_job"],
            original_filename="unconfirmed-private.pdf",
            storage_key="scoped/unconfirmed-private.pdf",
            mime="application/pdf",
            source_platform="direct",
            source_review_required=False,
            parse_status="parsed",
            parsed_payload={"email": "alice@app.test", "description": "private prose"},
            resume_text="private unconfirmed resume text",
        )
        generated = ResumeFile(
            candidate_id=ids["alice"],
            target_requisition_id=ids["engineering_job"],
            original_filename="generated-profile.pdf",
            storage_key="scoped/generated-profile.pdf",
            mime="application/pdf",
            source_platform="direct",
            source_review_required=False,
            parse_status="confirmed",
            parsed_payload={
                "_document_origin": "system_generated_profile",
                "name": "Alice Applicant",
                "email": "alice@app.test",
                "phone": "0912-345-678",
            },
            resume_text="generated profile with direct identifiers",
        )
        db.add_all([unconfirmed, generated])
        db.commit()
        resume_ids = (unconfirmed.id, generated.id)

    manager_headers = _headers(client, "engineering-manager")
    assert client.get("/api/v1/resumes", headers=manager_headers).status_code == 403
    for resume_id in resume_ids:
        assert (
            client.get(f"/api/v1/resumes/{resume_id}", headers=manager_headers).status_code
            == 403
        )
        assert (
            client.get(
                f"/api/v1/resumes/{resume_id}/file", headers=manager_headers
            ).status_code
            == 403
        )
        assert (
            client.get(
                f"/api/v1/resumes/{resume_id}/preview", headers=manager_headers
            ).status_code
            == 403
        )

    hr_headers = _headers(client, "hr")
    assert client.get(f"/api/v1/resumes/{resume_ids[0]}", headers=hr_headers).status_code == 200
    assert client.get(f"/api/v1/resumes/{resume_ids[1]}", headers=hr_headers).status_code == 200


def test_hr_assignment_returns_full_dto_and_rejects_duplicates(application_client) -> None:
    client, testing_session, ids = application_client
    payload = {
        "candidate_id": ids["alice"],
        "requisition_id": ids["design_job"],
    }
    assert (
        client.post(
            "/api/v1/applications",
            headers=_headers(client, "engineering-manager"),
            json=payload,
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/applications",
            headers=_headers(client, "it"),
            json=payload,
        ).status_code
        == 403
    )

    hr_headers = _headers(client, "hr")
    created = client.post("/api/v1/applications", headers=hr_headers, json=payload)
    assert created.status_code == 201
    body = created.json()
    assert set(body) == APPLICATION_KEYS
    assert body["candidate_id"] == ids["alice"]
    assert body["requisition_id"] == ids["design_job"]
    assert body["candidate"]["name"] == "Alice Applicant"
    assert body["requisition"]["title"] == "Application Product Designer"
    assert body["status"] == "submitted"
    assert body["source"] == "manual_hr"
    assert body["interview_at"] is None
    assert body["interview_result"] is None
    assert body["interview_notes"] is None
    assert body["hr_interview"] == {
        "stage": "hr",
        "interview_at": None,
        "interview_result": None,
        "interview_notes": None,
        "updated_by": None,
        "updated_at": None,
    }
    assert body["manager_interview"] == {
        "stage": "manager",
        "interview_at": None,
        "interview_result": None,
        "interview_notes": None,
        "updated_by": None,
        "updated_at": None,
    }
    _assert_aware(body["applied_at"])

    duplicate = client.post("/api/v1/applications", headers=hr_headers, json=payload)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "Candidate is already assigned to this job"
    assert (
        client.post(
            "/api/v1/applications",
            headers=hr_headers,
            json={"candidate_id": 999999, "requisition_id": ids["design_job"]},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/applications",
            headers=hr_headers,
            json={"candidate_id": ids["alice"], "requisition_id": 999999},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/applications",
            headers=hr_headers,
            json={"candidate_id": ids["deleted"], "requisition_id": ids["design_job"]},
        ).status_code
        == 409
    )

    with testing_session() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(JobApplication)
                .where(
                    JobApplication.candidate_id == ids["alice"],
                    JobApplication.requisition_id == ids["design_job"],
                )
            )
            == 1
        )
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "application.assign",
                AuditLog.resource_id == str(body["id"]),
            )
        )
        assert audit is not None
        assert audit.department_id == ids["design"]


@pytest.mark.parametrize("requisition_status", ["draft", "submitted", "returned"])
def test_hr_can_stage_candidates_on_preapproval_requisitions(
    application_client,
    requisition_status: str,
) -> None:
    client, testing_session, ids = application_client
    with testing_session() as db:
        candidate = Candidate(
            code=f"APP-STAGE-{requisition_status.upper()}",
            name=f"Staged {requisition_status.title()} Candidate",
            source="manual",
        )
        requisition = JobRequisition(
            req_no=f"APP-{requisition_status.upper()}-001",
            title=f"{requisition_status.title()} staging target",
            department_id=ids["design"],
            employment_type="full_time",
            work_city="Taipei",
            jd="HR may stage a candidate before final requisition approval",
            status=requisition_status,
        )
        db.add_all([candidate, requisition])
        db.commit()
        candidate_id = candidate.id
        requisition_id = requisition.id

    response = client.post(
        "/api/v1/applications",
        headers=_headers(client, "hr"),
        json={"candidate_id": candidate_id, "requisition_id": requisition_id},
    )
    assert response.status_code == 201
    assert response.json()["requisition"]["status"] == requisition_status


def test_hr_reassigns_candidate_to_new_department_and_rejects_unavailable_job(
    application_client,
) -> None:
    client, testing_session, ids = application_client
    endpoint = f"/api/v1/applications/{ids['engineering_application']}/assignment"
    payload = {"requisition_id": ids["design_job"]}

    with testing_session() as db:
        resume = ResumeFile(
            candidate_id=ids["alice"],
            target_requisition_id=ids["engineering_job"],
            original_filename="alice-reassignment.pdf",
            source_platform="generic",
            source_review_required=False,
            parse_status="confirmed",
        )
        unlinked_resume = ResumeFile(
            candidate_id=ids["alice"],
            target_requisition_id=ids["engineering_job"],
            original_filename="alice-unlinked-history.pdf",
            source_platform="generic",
            source_review_required=False,
            parse_status="confirmed",
        )
        db.add_all([resume, unlinked_resume])
        db.flush()
        application = db.get(JobApplication, ids["engineering_application"])
        assert application is not None
        application.resume_id = resume.id
        db.commit()
        resume_id = resume.id
        unlinked_resume_id = unlinked_resume.id
        reassigned_resume_ids = {resume_id, unlinked_resume_id}

    assert (
        client.patch(
            endpoint,
            headers=_headers(client, "engineering-manager"),
            json=payload,
        ).status_code
        == 403
    )
    assert (
        client.patch(
            endpoint,
            headers=_headers(client, "it"),
            json=payload,
        ).status_code
        == 403
    )

    updated = client.patch(endpoint, headers=_headers(client, "hr"), json=payload)
    assert updated.status_code == 200
    body = updated.json()
    assert body["id"] == ids["engineering_application"]
    assert body["candidate_id"] == ids["alice"]
    assert body["requisition_id"] == ids["design_job"]
    assert body["requisition"]["department_id"] == ids["design"]

    engineering_resumes = client.get(
        "/api/v1/resumes?include_confirmed=true",
        headers=_headers(client, "engineering-manager"),
    )
    assert engineering_resumes.status_code == 403
    design_resumes = client.get(
        "/api/v1/resumes?include_confirmed=true",
        headers=_headers(client, "design-manager"),
    )
    assert design_resumes.status_code == 403
    hr_resumes = client.get(
        "/api/v1/resumes?include_confirmed=true",
        headers=_headers(client, "hr"),
    )
    assert hr_resumes.status_code == 200
    assert reassigned_resume_ids.issubset({item["id"] for item in hr_resumes.json()})
    for reassigned_resume_id in reassigned_resume_ids:
        assert client.get(
            f"/api/v1/resumes/{reassigned_resume_id}",
            headers=_headers(client, "engineering-manager"),
        ).status_code == 403
        assert client.get(
            f"/api/v1/resumes/{reassigned_resume_id}",
            headers=_headers(client, "design-manager"),
        ).status_code == 403

    engineering_candidates = client.get(
        "/api/v1/candidates",
        headers=_headers(client, "engineering-manager"),
    )
    assert engineering_candidates.status_code == 403
    design_candidates = client.get(
        "/api/v1/candidates",
        headers=_headers(client, "design-manager"),
    )
    assert design_candidates.status_code == 403
    assert client.get(
        f"/api/v1/candidates/{ids['alice']}",
        headers=_headers(client, "engineering-manager"),
    ).status_code == 403
    assert client.get(
        f"/api/v1/candidates/{ids['alice']}",
        headers=_headers(client, "design-manager"),
    ).status_code == 200

    with testing_session() as db:
        closed_job = JobRequisition(
            req_no="APP-CLOSED-001",
            title="Closed assignment target",
            department_id=ids["engineering"],
            employment_type="full_time",
            work_city="Taipei",
            jd="This requisition cannot receive new candidates",
            status="closed",
        )
        db.add(closed_job)
        db.commit()
        closed_job_id = closed_job.id

        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "application.reassign",
                AuditLog.resource_id == str(ids["engineering_application"]),
            )
        )
        assert audit is not None
        assert audit.department_id == ids["design"]
        assert audit.details["previous_department_id"] == ids["engineering"]
        assert audit.details["department_id"] == ids["design"]
        assert audit.details["resume_id"] == resume_id
        assert set(audit.details["resume_ids"]) == reassigned_resume_ids
        assert db.get(ResumeFile, resume_id).target_requisition_id == ids["design_job"]
        assert db.get(ResumeFile, unlinked_resume_id).target_requisition_id == ids["design_job"]

    unavailable = client.patch(
        endpoint,
        headers=_headers(client, "hr"),
        json={"requisition_id": closed_job_id},
    )
    assert unavailable.status_code == 409
    assert unavailable.json()["detail"] == (
        "Requisition is no longer available for candidate assignment"
    )
    unchanged = client.get(
        "/api/v1/applications?department_id=" + str(ids["design"]),
        headers=_headers(client, "hr"),
    )
    assert ids["engineering_application"] in {item["id"] for item in unchanged.json()}

    with testing_session() as db:
        application = db.get(JobApplication, ids["engineering_application"])
        assert application is not None
        application.manager_interview_notes = "Design manager historical assessment"
        db.commit()
    history_preserved = client.patch(
        endpoint,
        headers=_headers(client, "hr"),
        json={"requisition_id": ids["engineering_job"]},
    )
    assert history_preserved.status_code == 409
    assert history_preserved.json()["detail"] == (
        "Applications with interview or hiring history cannot be reassigned; "
        "create a new assignment instead"
    )
    with testing_session() as db:
        application = db.get(JobApplication, ids["engineering_application"])
        assert application is not None
        assert application.requisition_id == ids["design_job"]
        assert application.manager_interview_notes == "Design manager historical assessment"
        assert db.get(ResumeFile, resume_id).target_requisition_id == ids["design_job"]
        assert db.get(ResumeFile, unlinked_resume_id).target_requisition_id == ids["design_job"]

    new_assignment = client.post(
        "/api/v1/applications",
        headers=_headers(client, "hr"),
        json={
            "candidate_id": ids["alice"],
            "requisition_id": ids["engineering_job"],
        },
    )
    assert new_assignment.status_code == 201
    assert new_assignment.json()["id"] != ids["engineering_application"]
    assert new_assignment.json()["source"] == "manual_hr"
    engineering_candidates = client.get(
        "/api/v1/candidates",
        headers=_headers(client, "engineering-manager"),
    )
    assert engineering_candidates.status_code == 403
    assert client.get(
        f"/api/v1/candidates/{ids['alice']}",
        headers=_headers(client, "engineering-manager"),
    ).status_code == 200
    engineering_resumes = client.get(
        "/api/v1/resumes?include_confirmed=true",
        headers=_headers(client, "engineering-manager"),
    )
    assert engineering_resumes.status_code == 403
    for reassigned_resume_id in reassigned_resume_ids:
        assert client.get(
            f"/api/v1/resumes/{reassigned_resume_id}",
            headers=_headers(client, "engineering-manager"),
        ).status_code == 403


def test_hr_marks_interview_ready_and_the_status_survives_stage_sync(
    application_client,
) -> None:
    client, testing_session, ids = application_client
    application_id = ids["design_application"]
    endpoint = f"/api/v1/applications/{application_id}/mark-interview-ready"
    hr_headers = _headers(client, "hr")

    assert client.post(endpoint).status_code == 401
    assert client.post(endpoint, headers=_headers(client, "it")).status_code == 403
    assert (
        client.post(endpoint, headers=_headers(client, "design-manager")).status_code == 403
    )
    assert (
        client.post(
            "/api/v1/applications/999999/mark-interview-ready",
            headers=hr_headers,
        ).status_code
        == 404
    )

    marked = client.post(endpoint, headers=hr_headers)
    assert marked.status_code == 200, marked.text
    body = marked.json()
    assert set(body) == APPLICATION_KEYS
    assert body["status"] == "interview_ready"
    assert body["hr_interview"]["interview_at"] is None
    assert body["manager_interview"]["interview_at"] is None

    # Marking again is a no-op rather than an error.
    assert client.post(endpoint, headers=hr_headers).json()["status"] == "interview_ready"

    # _sync_application_status must not clobber the mark while no stage holds data.
    cleared = client.patch(
        f"/api/v1/applications/{application_id}/interviews/hr",
        headers=hr_headers,
        json={"interview_notes": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["status"] == "interview_ready"

    with testing_session() as db:
        application = db.get(JobApplication, application_id)
        assert application is not None
        assert application.status == "interview_ready"
        audit = db.scalar(
            select(AuditLog)
            .where(
                AuditLog.action == "application.mark_interview_ready",
                AuditLog.resource_id == str(application_id),
            )
            .order_by(AuditLog.id.desc())
        )
        assert audit is not None
        assert audit.department_id == ids["design"]
        assert audit.details["status"] == {"from": "submitted", "to": "interview_ready"}


def test_interview_ready_upgrades_to_interview_once_stage_data_exists(
    application_client,
) -> None:
    client, testing_session, ids = application_client
    application_id = ids["design_application"]
    endpoint = f"/api/v1/applications/{application_id}/mark-interview-ready"
    hr_headers = _headers(client, "hr")

    assert client.post(endpoint, headers=hr_headers).json()["status"] == "interview_ready"

    scheduled = client.patch(
        f"/api/v1/applications/{application_id}/interviews/hr",
        headers=hr_headers,
        json={
            "interview_at": "2030-09-01T09:30:00+08:00",
            "interview_result": "pending",
        },
    )
    assert scheduled.status_code == 200, scheduled.text
    assert scheduled.json()["status"] == "interview"

    # Once real interview data exists the application can no longer be re-marked.
    conflict = client.post(endpoint, headers=hr_headers)
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["detail"] == "Application already holds interview data"

    with testing_session() as db:
        application = db.get(JobApplication, application_id)
        assert application is not None
        assert application.status == "interview"


def test_mark_interview_ready_rejects_applications_past_the_pre_interview_stage(
    application_client,
) -> None:
    client, testing_session, ids = application_client
    application_id = ids["engineering_application"]
    with testing_session() as db:
        application = db.get(JobApplication, application_id)
        assert application is not None
        application.status = "hired"
        db.commit()

    conflict = client.post(
        f"/api/v1/applications/{application_id}/mark-interview-ready",
        headers=_headers(client, "hr"),
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["detail"] == (
        "Only a pre-interview application can be marked ready to interview"
    )

    with testing_session() as db:
        application = db.get(JobApplication, application_id)
        assert application is not None
        assert application.status == "hired"


def test_department_manager_updates_interview_with_status_sync_and_audit(
    application_client,
) -> None:
    client, testing_session, ids = application_client
    application_id = ids["design_application"]
    endpoint = f"/api/v1/applications/{application_id}/interview"
    engineering_headers = _headers(client, "engineering-manager")
    design_headers = _headers(client, "design-manager")
    assert (
        client.patch(
            endpoint,
            headers=engineering_headers,
            json={"interview_result": "pending"},
        ).status_code
        == 403
    )
    assert (
        client.patch(
            endpoint,
            headers=_headers(client, "it"),
            json={"interview_result": "pending"},
        ).status_code
        == 403
    )
    assert client.patch(endpoint, headers=design_headers, json={}).status_code == 422
    assert (
        client.patch(
            endpoint,
            headers=design_headers,
            json={"interview_at": "2030-08-20T09:30:00"},
        ).status_code
        == 422
    )
    assert (
        client.patch(
            endpoint,
            headers=design_headers,
            json={"interview_result": "unknown"},
        ).status_code
        == 422
    )

    scheduled = client.patch(
        endpoint,
        headers=design_headers,
        json={
            "interview_at": "2030-08-20T09:30:00+08:00",
            "interview_result": "pending",
            "interview_notes": "  First interview with the product lead.  ",
        },
    )
    assert scheduled.status_code == 200
    body = scheduled.json()
    assert set(body) == APPLICATION_KEYS
    assert body["status"] == "interview"
    assert body["interview_result"] == "pending"
    assert body["interview_notes"] == "First interview with the product lead."
    assert body["manager_interview"]["interview_result"] == "pending"
    assert body["manager_interview"]["interview_notes"] == (
        "First interview with the product lead."
    )
    assert body["hr_interview"]["interview_at"] is None
    _assert_aware(body["interview_at"])

    for result, expected_status in [
        ("advance", "interview"),
        ("hold", "interview"),
        ("no_show", "interview"),
        ("cancelled", "interview"),
        ("offered", "offered"),
        ("hired", "hired"),
        ("rejected", "rejected"),
    ]:
        updated = client.patch(
            endpoint,
            headers=design_headers,
            json={"interview_result": result},
        )
        assert updated.status_code == 200
        assert updated.json()["interview_result"] == result
        assert updated.json()["status"] == expected_status

    cleared = client.patch(
        endpoint,
        headers=design_headers,
        json={
            "interview_at": None,
            "interview_result": None,
            "interview_notes": None,
        },
    )
    assert cleared.status_code == 200
    assert cleared.json()["interview_at"] is None
    assert cleared.json()["interview_result"] is None
    assert cleared.json()["interview_notes"] is None

    with testing_session() as db:
        application = db.get(JobApplication, application_id)
        assert application is not None
        assert application.interview_updated_by == ids["design_manager"]
        audit = db.scalar(
            select(AuditLog)
            .where(
                AuditLog.action == "application.interview.manager.update",
                AuditLog.resource_id == str(application_id),
            )
            .order_by(AuditLog.id.desc())
        )
        assert audit is not None
        assert audit.actor_user_id == ids["design_manager"]
        assert audit.department_id == ids["design"]
        assert audit.details["stage"] == "manager"
        assert audit.details["notes_changed"] is True


def test_hr_and_manager_interview_records_are_separate_and_role_owned(
    application_client,
) -> None:
    client, testing_session, ids = application_client
    application_id = ids["design_application"]
    hr_endpoint = f"/api/v1/applications/{application_id}/interviews/hr"
    manager_endpoint = f"/api/v1/applications/{application_id}/interviews/manager"
    hr_headers = _headers(client, "hr")
    design_headers = _headers(client, "design-manager")

    assert (
        client.patch(
            hr_endpoint,
            headers=design_headers,
            json={"interview_notes": "Manager must not edit HR feedback"},
        ).status_code
        == 403
    )
    assert (
        client.patch(
            manager_endpoint,
            headers=hr_headers,
            json={"interview_notes": "HR must not edit manager feedback"},
        ).status_code
        == 403
    )
    admin_headers = _headers(client, "admin")
    assert (
        client.patch(
            hr_endpoint,
            headers=admin_headers,
            json={"interview_notes": "Admin is not an interview author"},
        ).status_code
        == 403
    )
    assert (
        client.patch(
            manager_endpoint,
            headers=admin_headers,
            json={"interview_notes": "Admin is not an interview author"},
        ).status_code
        == 403
    )
    assert (
        client.patch(
            manager_endpoint,
            headers=_headers(client, "engineering-manager"),
            json={"interview_notes": "Other department"},
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/v1/applications/{application_id}/interviews/third",
            headers=hr_headers,
            json={"interview_notes": "Invalid stage"},
        ).status_code
        == 422
    )

    hr_saved = client.patch(
        hr_endpoint,
        headers=hr_headers,
        json={
            "interview_at": "2030-08-20T09:30:00+08:00",
            "interview_result": "advance",
            "interview_notes": "HR recommends advancing; communication is clear.",
        },
    )
    assert hr_saved.status_code == 200
    hr_body = hr_saved.json()
    assert hr_body["hr_interview"]["interview_result"] == "advance"
    assert hr_body["hr_interview"]["updated_by"] is not None
    _assert_aware(hr_body["hr_interview"]["updated_at"])
    assert hr_body["manager_interview"]["interview_at"] is None
    assert hr_body["interview_notes"] == ("HR recommends advancing; communication is clear.")

    manager_saved = client.patch(
        manager_endpoint,
        headers=design_headers,
        json={
            "interview_at": "2030-08-22T14:00:00+08:00",
            "interview_result": "offered",
            "interview_notes": "Department recommends an offer after portfolio review.",
        },
    )
    assert manager_saved.status_code == 200
    body = manager_saved.json()
    assert body["status"] == "offered"
    assert body["hr_interview"]["interview_result"] == "advance"
    assert body["hr_interview"]["interview_notes"] == (
        "HR recommends advancing; communication is clear."
    )
    assert body["manager_interview"]["interview_result"] == "offered"
    _assert_aware(body["manager_interview"]["updated_at"])
    assert body["manager_interview"]["interview_notes"] == (
        "Department recommends an offer after portfolio review."
    )
    # Legacy fields expose the latest manager stage without erasing HR's record.
    assert body["interview_result"] == "offered"
    assert body["interview_notes"] == body["manager_interview"]["interview_notes"]

    with testing_session() as db:
        application = db.get(JobApplication, application_id)
        assert application is not None
        assert application.hr_interview_updated_by is not None
        assert application.manager_interview_updated_by == ids["design_manager"]
        actions = set(
            db.scalars(
                select(AuditLog.action).where(
                    AuditLog.resource_id == str(application_id),
                    AuditLog.action.like("application.interview.%.update"),
                )
            ).all()
        )
        assert actions == {
            "application.interview.hr.update",
            "application.interview.manager.update",
        }


def test_structured_interview_records_preserve_session_and_actor_history(
    application_client,
) -> None:
    client, testing_session, ids = application_client
    application_id = ids["design_application"]
    endpoint = f"/api/v1/applications/{application_id}/interview-records"
    hr_headers = _headers(client, "hr")
    design_headers = _headers(client, "design-manager")

    payload = {
        "stage": "hr",
        "interviewed_at": "2030-08-20T09:30:00+08:00",
        "duration_minutes": 50,
        "mode": "video",
        "status": "completed",
        "questions": [
            {
                "question": "  請分享跨部門合作的經驗？  ",
                "trait": "合作",
                "response": "  與產品和工程共同排定範圍。  ",
                "rating": 4,
                "notes": "  有具體結果。  ",
                "purpose": "  確認跨部門協作方式。  ",
                "follow_up": "  最後如何取得共識？  ",
                "source": "  HR 固定題  ",
            }
        ],
        "summary": "  溝通清楚，建議進入主管面談。  ",
        "recommendation": "advance",
        "overall_rating": 4,
    }
    assert client.post(endpoint, headers=design_headers, json=payload).status_code == 403
    assert (
        client.post(
            endpoint,
            headers=_headers(client, "engineering-manager"),
            json={**payload, "stage": "manager"},
        ).status_code
        == 403
    )

    created = client.post(endpoint, headers=hr_headers, json=payload)
    assert created.status_code == 201, created.text
    body = created.json()
    record_id = body["id"]
    assert body["stage"] == "hr"
    assert body["interviewer_name"] == "Application HR"
    assert body["interviewer_id"] is not None
    assert body["questions"][0]["question"] == "請分享跨部門合作的經驗？"
    assert body["questions"][0]["response"] == "與產品和工程共同排定範圍。"
    assert body["questions"][0]["purpose"] == "確認跨部門協作方式。"
    assert body["questions"][0]["follow_up"] == "最後如何取得共識？"
    assert body["questions"][0]["source"] == "HR 固定題"
    assert body["summary"] == "溝通清楚，建議進入主管面談。"
    _assert_aware(body["interviewed_at"])
    _assert_aware(body["created_at"])
    _assert_aware(body["updated_at"])

    listed = client.get(endpoint, headers=design_headers)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [record_id]
    assert client.get(f"{endpoint}/{record_id}", headers=design_headers).status_code == 200
    assert (
        client.patch(
            f"{endpoint}/{record_id}",
            headers=design_headers,
            json={"summary": "Manager must not alter HR record"},
        ).status_code
        == 403
    )
    for field in ("interviewed_at", "mode", "status", "questions"):
        assert (
            client.patch(
                f"{endpoint}/{record_id}",
                headers=hr_headers,
                json={field: None},
            ).status_code
            == 422
        )

    admin_update = client.patch(
        f"{endpoint}/{record_id}",
        headers=_headers(client, "admin"),
        json={"status": "completed", "summary": "Final HR interview summary"},
    )
    assert admin_update.status_code == 403

    updated = client.patch(
        f"{endpoint}/{record_id}",
        headers=hr_headers,
        json={"status": "completed", "summary": "Final HR interview summary"},
    )
    assert updated.status_code == 409

    manager_created = client.post(
        endpoint,
        headers=design_headers,
        json={
            **payload,
            "stage": "manager",
            "interviewed_at": "2030-08-22T14:00:00+08:00",
            "status": "in_progress",
            "questions": [],
        },
    )
    assert manager_created.status_code == 201
    filtered = client.get(f"{endpoint}?stage=manager", headers=hr_headers)
    assert filtered.status_code == 200
    assert [item["stage"] for item in filtered.json()] == ["manager"]

    with testing_session() as db:
        record = db.get(InterviewRecord, record_id)
        assert record is not None
        assert record.interviewer_id is not None
        assert record.interviewer_name == "Application HR"
        audit_actions = set(
            db.scalars(
                select(AuditLog.action).where(
                    AuditLog.resource_type == "interview_record",
                    AuditLog.resource_id == str(record_id),
                )
            ).all()
        )
        assert audit_actions == {"application.interview_record.create"}


def test_completed_interview_validation_lock_reopen_revision_and_safe_audit(
    application_client,
) -> None:
    client, testing_session, ids = application_client
    application_id = ids["design_application"]
    endpoint = f"/api/v1/applications/{application_id}/interview-records"
    hr_headers = _headers(client, "hr")
    manager_headers = _headers(client, "design-manager")

    valid_completed = {
        "stage": "hr",
        "interviewed_at": "2030-09-01T09:00:00+08:00",
        "duration_minutes": 45,
        "mode": "video",
        "status": "completed",
        "questions": [
            {
                "question": "Describe a difficult stakeholder conversation.",
                "response": "Sensitive answer must not enter the audit log.",
                "rating": 4,
                "notes": "Sensitive scoring note must not enter the audit log.",
            }
        ],
        "summary": "Clear evidence and reflection.",
        "private_notes": "Sensitive HR-only note must not enter the audit log.",
        "recommendation": "advance",
        "overall_rating": 4,
    }
    invalid_completed = [
        {**valid_completed, "questions": []},
        {
            **valid_completed,
            "questions": [{"question": "A question without an evaluation"}],
        },
        {**valid_completed, "overall_rating": None},
        {**valid_completed, "recommendation": None},
        {**valid_completed, "summary": "   "},
        {
            **valid_completed,
            "questions": [{"question": "Out-of-range rating", "rating": 6}],
        },
    ]
    for payload in invalid_completed:
        assert client.post(endpoint, headers=hr_headers, json=payload).status_code == 422

    mutually_exclusive = client.post(
        endpoint,
        headers=hr_headers,
        json={
            **valid_completed,
            "status": "in_progress",
            "questions": [
                {
                    "question": "This cannot be rated and skipped.",
                    "rating": 3,
                    "not_asked_reason": "No time",
                }
            ],
        },
    )
    assert mutually_exclusive.status_code == 422

    draft_without_evaluation = client.post(
        endpoint,
        headers=hr_headers,
        json={
            "stage": "hr",
            "interviewed_at": "2030-08-30T09:00:00+08:00",
            "mode": "phone",
            "status": "in_progress",
            "questions": [{"question": "Draft question"}],
        },
    )
    assert draft_without_evaluation.status_code == 201
    assert draft_without_evaluation.json()["revision_number"] == 0
    assert draft_without_evaluation.json()["submitted_at"] is None

    for offset, terminal_status in enumerate(("cancelled", "no_show"), start=1):
        terminal = client.post(
            endpoint,
            headers=hr_headers,
            json={
                "stage": "hr",
                "interviewed_at": f"2030-08-{offset + 20:02d}T09:00:00+08:00",
                "mode": "phone",
                "status": terminal_status,
                "questions": [],
            },
        )
        assert terminal.status_code == 201
        assert terminal.json()["revision_number"] == 0
        assert terminal.json()["submitted_at"] is None

    draft_payload = {
        **valid_completed,
        "status": "in_progress",
        "questions": [
            valid_completed["questions"][0],
            {
                "question": "Discuss another project example.",
                "not_asked_reason": "  Interview time expired.  ",
            },
        ],
    }
    created = client.post(endpoint, headers=hr_headers, json=draft_payload)
    assert created.status_code == 201, created.text
    record_id = created.json()["id"]
    assert created.json()["questions"][1]["not_asked_reason"] == (
        "Interview time expired."
    )
    assert created.json()["revision_number"] == 0

    submitted = client.patch(
        f"{endpoint}/{record_id}",
        headers=hr_headers,
        json={"status": "completed"},
    )
    assert submitted.status_code == 200, submitted.text
    first_submission = submitted.json()
    assert first_submission["revision_number"] == 1
    assert first_submission["submitted_at"] is not None
    assert first_submission["submitted_by_name"] == "Application HR"
    assert first_submission["last_reopen_reason"] is None

    locked = client.patch(
        f"{endpoint}/{record_id}",
        headers=hr_headers,
        json={"summary": "A completed record cannot be edited directly."},
    )
    assert locked.status_code == 409
    assert client.post(
        f"{endpoint}/{record_id}/reopen",
        headers=manager_headers,
        json={"reason": "Manager cannot reopen the HR stage."},
    ).status_code == 403
    assert client.post(
        f"{endpoint}/{record_id}/reopen",
        headers=_headers(client, "engineering-manager"),
        json={"reason": "Wrong department."},
    ).status_code == 403
    assert client.post(
        f"{endpoint}/{record_id}/reopen",
        headers=_headers(client, "admin"),
        json={"reason": "Admin is not an interview author."},
    ).status_code == 403
    assert client.post(
        f"{endpoint}/{record_id}/reopen",
        headers=hr_headers,
        json={"reason": "   "},
    ).status_code == 422

    reopen_reason = "Correct a documented scoring error: " + "x" * 700
    reopened = client.post(
        f"{endpoint}/{record_id}/reopen",
        headers=hr_headers,
        json={"reason": f"  {reopen_reason}  "},
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "in_progress"
    assert reopened.json()["revision_number"] == 1
    assert reopened.json()["last_reopen_reason"] == reopen_reason
    assert reopened.json()["submitted_at"] == first_submission["submitted_at"]
    assert client.post(
        f"{endpoint}/{record_id}/reopen",
        headers=hr_headers,
        json={"reason": "Cannot reopen a draft twice."},
    ).status_code == 409

    masked = client.get(f"{endpoint}/{record_id}", headers=manager_headers)
    assert masked.status_code == 200
    assert masked.json()["evaluation_revealed"] is False
    assert masked.json()["questions"][0]["rating"] is None
    assert masked.json()["questions"][1]["not_asked_reason"] is None
    assert masked.json()["submitted_by_id"] is None
    assert masked.json()["submitted_by_name"] is None
    assert masked.json()["last_reopen_reason"] is None

    incomplete_draft = client.patch(
        f"{endpoint}/{record_id}",
        headers=hr_headers,
        json={"questions": [{"question": "Needs evaluation before resubmission"}]},
    )
    assert incomplete_draft.status_code == 200
    assert client.patch(
        f"{endpoint}/{record_id}",
        headers=hr_headers,
        json={"status": "completed"},
    ).status_code == 422

    resubmitted = client.patch(
        f"{endpoint}/{record_id}",
        headers=hr_headers,
        json={
            "status": "completed",
            "questions": [
                {
                    "question": "Needs evaluation before resubmission",
                    "response": "Corrected sensitive answer.",
                    "rating": 5,
                    "notes": "Corrected sensitive note.",
                }
            ],
            "summary": "Corrected official summary.",
            "recommendation": "offer",
            "overall_rating": 5,
        },
    )
    assert resubmitted.status_code == 200, resubmitted.text
    assert resubmitted.json()["revision_number"] == 2
    assert resubmitted.json()["submitted_by_name"] == "Application HR"
    assert resubmitted.json()["last_reopen_reason"] == reopen_reason

    with testing_session() as db:
        audits = list(
            db.scalars(
                select(AuditLog)
                .where(
                    AuditLog.resource_type == "interview_record",
                    AuditLog.resource_id == str(record_id),
                )
                .order_by(AuditLog.id)
            ).all()
        )
        actions = [audit.action for audit in audits]
        assert actions == [
            "application.interview_record.create",
            "application.interview_record.update",
            "application.interview_record.reopen",
            "application.interview_record.update",
            "application.interview_record.update",
        ]
        serialized_audit = json.dumps(
            [audit.details for audit in audits],
            ensure_ascii=False,
        )
        for secret in (
            "Sensitive answer must not enter the audit log.",
            "Sensitive scoring note must not enter the audit log.",
            "Sensitive HR-only note must not enter the audit log.",
            "Corrected sensitive answer.",
            "Corrected sensitive note.",
        ):
            assert secret not in serialized_audit
        reopen_audit = next(
            audit
            for audit in audits
            if audit.action == "application.interview_record.reopen"
        )
        assert len(reopen_audit.details["reopen_reason"]) == 500
        assert audits[-1].details["revision_number"] == 2
        assert audits[-1].details["rated_question_count"] == 1
        assert audits[-1].details["completed_question_count"] == 1


def test_interview_answers_are_shared_but_peer_evaluations_wait_for_both_submissions(
    application_client,
) -> None:
    client, _, ids = application_client
    application_id = ids["design_application"]
    endpoint = f"/api/v1/applications/{application_id}/interview-records"
    hr_headers = _headers(client, "hr")
    manager_headers = _headers(client, "design-manager")

    hr_payload = {
        "stage": "hr",
        "interviewed_at": "2030-08-20T09:30:00+08:00",
        "duration_minutes": 45,
        "mode": "video",
        "status": "in_progress",
        "questions": [
            {
                "question": "Why are you interested in this role?",
                "response": "The candidate wants to own end-to-end product design.",
                "rating": 4,
                "notes": "Clear motivation with specific examples.",
            },
            {
                "question": "What compensation range are you considering?",
                "not_asked_reason": "Deferred until role scope is confirmed.",
            },
        ],
        "summary": "Strong communication and motivation.",
        "private_notes": "HR-only compensation context.",
        "recommendation": "advance",
        "overall_rating": 4,
    }
    hr_created = client.post(endpoint, headers=hr_headers, json=hr_payload)
    assert hr_created.status_code == 201, hr_created.text
    hr_record_id = hr_created.json()["id"]
    assert hr_created.json()["evaluation_revealed"] is True
    assert hr_created.json()["private_notes_visible"] is True
    assert hr_created.json()["private_notes"] == "HR-only compensation context."

    manager_view = client.get(endpoint, headers=manager_headers)
    assert manager_view.status_code == 200
    masked_hr = manager_view.json()[0]
    assert masked_hr["questions"][0]["response"] == (
        "The candidate wants to own end-to-end product design."
    )
    assert masked_hr["questions"][0]["rating"] is None
    assert masked_hr["questions"][0]["notes"] is None
    assert masked_hr["questions"][1]["not_asked_reason"] is None
    assert masked_hr["summary"] is None
    assert masked_hr["recommendation"] is None
    assert masked_hr["overall_rating"] is None
    assert masked_hr["private_notes"] is None
    assert masked_hr["evaluation_revealed"] is False
    assert masked_hr["private_notes_visible"] is False

    rejected_private_note = client.post(
        endpoint,
        headers=manager_headers,
        json={
            **hr_payload,
            "stage": "manager",
            "private_notes": "A manager must not create an HR-only note.",
        },
    )
    assert rejected_private_note.status_code == 403

    manager_payload = {
        "stage": "manager",
        "interviewed_at": "2030-08-22T14:00:00+08:00",
        "duration_minutes": 60,
        "mode": "onsite",
        "status": "in_progress",
        "questions": [
            {
                "question": "How did you validate your latest design decision?",
                "response": "The candidate described research, testing, and metrics.",
                "rating": 5,
                "notes": "Strong evidence-based decision process.",
            }
        ],
        "summary": "Strong role-specific evidence.",
        "recommendation": "offer",
        "overall_rating": 5,
    }
    manager_created = client.post(
        endpoint,
        headers=manager_headers,
        json=manager_payload,
    )
    assert manager_created.status_code == 201, manager_created.text
    manager_record_id = manager_created.json()["id"]

    hr_view_before_both_submit = client.get(f"{endpoint}/{manager_record_id}", headers=hr_headers)
    assert hr_view_before_both_submit.status_code == 200
    masked_manager = hr_view_before_both_submit.json()
    assert masked_manager["questions"][0]["response"] == (
        "The candidate described research, testing, and metrics."
    )
    assert masked_manager["questions"][0]["rating"] is None
    assert masked_manager["questions"][0]["notes"] is None
    assert masked_manager["summary"] is None
    assert masked_manager["evaluation_revealed"] is False

    hr_submitted = client.patch(
        f"{endpoint}/{hr_record_id}",
        headers=hr_headers,
        json={"status": "completed"},
    )
    assert hr_submitted.status_code == 200
    still_masked = client.get(f"{endpoint}/{hr_record_id}", headers=manager_headers).json()
    assert still_masked["evaluation_revealed"] is False
    assert still_masked["overall_rating"] is None
    assert still_masked["submitted_by_name"] is None

    manager_submitted = client.patch(
        f"{endpoint}/{manager_record_id}",
        headers=manager_headers,
        json={"status": "completed"},
    )
    assert manager_submitted.status_code == 200

    hr_view_after_both_submit = client.get(
        f"{endpoint}/{manager_record_id}", headers=hr_headers
    ).json()
    assert hr_view_after_both_submit["evaluation_revealed"] is True
    assert hr_view_after_both_submit["questions"][0]["rating"] == 5
    assert hr_view_after_both_submit["questions"][0]["notes"] == (
        "Strong evidence-based decision process."
    )
    assert hr_view_after_both_submit["summary"] == "Strong role-specific evidence."
    assert hr_view_after_both_submit["recommendation"] == "offer"

    manager_view_after_both_submit = client.get(
        f"{endpoint}/{hr_record_id}", headers=manager_headers
    ).json()
    assert manager_view_after_both_submit["evaluation_revealed"] is True
    assert manager_view_after_both_submit["questions"][0]["rating"] == 4
    assert manager_view_after_both_submit["questions"][1]["not_asked_reason"] == (
        "Deferred until role scope is confirmed."
    )
    assert manager_view_after_both_submit["summary"] == ("Strong communication and motivation.")
    assert manager_view_after_both_submit["private_notes"] is None
    assert manager_view_after_both_submit["private_notes_visible"] is False


def test_hr_and_manager_have_independent_five_question_versions(
    application_client,
) -> None:
    client, testing_session, ids = application_client
    with testing_session() as db:
        alice = db.get(Candidate, ids["alice"])
        engineering_job = db.get(JobRequisition, ids["engineering_job"])
        assert alice is not None
        assert engineering_job is not None
        alice.current_title = "Python API Developer"
        alice.total_years = 6
        engineering_job.skills = ["Python", "FastAPI", "PostgreSQL"]
        db.add_all(
            [
                CandidateSkill(
                    candidate_id=alice.id,
                    skill="Python",
                    skill_norm="python",
                ),
                CandidateExperience(
                    candidate_id=alice.id,
                    company="Example Systems",
                    title="API Developer",
                    description="Led a billing API migration",
                    years=3,
                    sort_order=0,
                ),
            ]
        )
        db.commit()

    hr_headers = _headers(client, "hr")
    engineering_application = ids["engineering_application"]
    design_application = ids["design_application"]
    engineering_hr = client.get(
        f"/api/v1/applications/{engineering_application}/interview-question-plan?stage=hr",
        headers=hr_headers,
    )
    design_hr = client.get(
        f"/api/v1/applications/{design_application}/interview-question-plan?stage=hr",
        headers=hr_headers,
    )
    assert engineering_hr.status_code == 200, engineering_hr.text
    assert design_hr.status_code == 200, design_hr.text
    assert len(engineering_hr.json()["questions"]) == 5
    assert [item["question"] for item in engineering_hr.json()["questions"]] == [
        item["question"] for item in design_hr.json()["questions"]
    ]
    assert all(item["source"] == "全公司 HR 固定題" for item in engineering_hr.json()["questions"])

    generated_hr = client.post(
        f"/api/v1/applications/{engineering_application}/interview-question-plan/generate"
        "?stage=hr",
        headers=hr_headers,
    )
    assert generated_hr.status_code == 200, generated_hr.text
    hr_body = generated_hr.json()
    assert hr_body["stage"] == "hr"
    assert len(hr_body["questions"]) == 5
    assert hr_body["version"] == 1
    assert hr_body["total_tokens"] == 0
    manager_can_view_hr = client.get(
        f"/api/v1/applications/{engineering_application}/interview-question-plan?stage=hr",
        headers=_headers(client, "engineering-manager"),
    )
    assert manager_can_view_hr.status_code == 200
    assert manager_can_view_hr.json()["questions"] == hr_body["questions"]

    regenerated_hr = client.post(
        f"/api/v1/applications/{engineering_application}/interview-question-plan/generate"
        "?stage=hr&force=true",
        headers=hr_headers,
    )
    assert regenerated_hr.status_code == 200
    assert regenerated_hr.json()["version"] == 2

    manager = client.get(
        f"/api/v1/applications/{engineering_application}/interview-question-plan?stage=manager",
        headers=_headers(client, "engineering-manager"),
    )
    assert manager.status_code == 200, manager.text
    body = manager.json()
    assert body["stage"] == "manager"
    assert body["job_title"] == "Application Backend Engineer"
    assert body["questions"] == []
    assert body["generation_mode"] == "not_generated"

    generated = client.post(
        f"/api/v1/applications/{engineering_application}/interview-question-plan/generate",
        headers=_headers(client, "engineering-manager"),
    )
    assert generated.status_code == 200, generated.text
    body = generated.json()
    assert len(body["questions"]) == 5
    assert body["generation_mode"] == "rules"
    assert body["version"] == 1
    assert body["total_tokens"] == 0
    assert body["context_matches"] is True
    combined_questions = " ".join(item["question"] for item in body["questions"])
    assert "Application Backend Engineer" in combined_questions
    assert "Python API Developer" in combined_questions
    assert "Python" in combined_questions
    assert any("候選人技能：Python" in item for item in body["personalization_basis"])
    hr_can_view_manager = client.get(
        f"/api/v1/applications/{engineering_application}/interview-question-plan?stage=manager",
        headers=hr_headers,
    )
    assert hr_can_view_manager.status_code == 200
    assert hr_can_view_manager.json()["questions"] == body["questions"]

    cached = client.get(
        f"/api/v1/applications/{engineering_application}/interview-question-plan?stage=manager",
        headers=_headers(client, "engineering-manager"),
    )
    assert cached.status_code == 200
    assert cached.json()["version"] == 1
    assert cached.json()["questions"] == body["questions"]

    regenerated = client.post(
        f"/api/v1/applications/{engineering_application}/interview-question-plan/generate?force=true",
        headers=_headers(client, "engineering-manager"),
    )
    assert regenerated.status_code == 200
    assert regenerated.json()["version"] == 2
    assert client.post(
        f"/api/v1/applications/{engineering_application}/interview-question-plan/generate"
        "?stage=hr&force=true",
        headers=_headers(client, "engineering-manager"),
    ).status_code == 403
    assert client.post(
        f"/api/v1/applications/{engineering_application}/interview-question-plan/generate"
        "?stage=manager&force=true",
        headers=hr_headers,
    ).status_code == 403
    admin_headers = _headers(client, "admin")
    assert client.post(
        f"/api/v1/applications/{engineering_application}/interview-question-plan/generate"
        "?stage=hr&force=true",
        headers=admin_headers,
    ).status_code == 403
    assert client.post(
        f"/api/v1/applications/{engineering_application}/interview-question-plan/generate"
        "?stage=manager&force=true",
        headers=admin_headers,
    ).status_code == 403
    assert (
        client.get(
            f"/api/v1/applications/{engineering_application}/interview-question-plan?stage=manager",
            headers=_headers(client, "design-manager"),
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"/api/v1/applications/{engineering_application}/interview-question-plan?stage=third",
            headers=hr_headers,
        ).status_code
        == 422
    )


def test_single_question_regeneration_preserves_other_four_and_old_versions(
    application_client,
) -> None:
    client, testing_session, ids = application_client
    application_id = ids["engineering_application"]
    manager_headers = _headers(client, "engineering-manager")

    initial_response = client.post(
        f"/api/v1/applications/{application_id}/interview-question-plan/generate",
        headers=manager_headers,
    )
    assert initial_response.status_code == 200, initial_response.text
    initial = initial_response.json()
    selected_index = 2

    regenerated_response = client.post(
        f"/api/v1/applications/{application_id}/interview-question-plan/questions/"
        f"{selected_index}/regenerate?stage=manager",
        headers=manager_headers,
    )
    assert regenerated_response.status_code == 200, regenerated_response.text
    regenerated = regenerated_response.json()
    assert regenerated["version"] == 2
    assert regenerated["id"] != initial["id"]
    assert len(regenerated["questions"]) == 5
    assert [item["category"] for item in regenerated["questions"]] == [
        item["category"] for item in initial["questions"]
    ]
    for index in range(5):
        if index == selected_index:
            assert (
                regenerated["questions"][index]["question"]
                != initial["questions"][index]["question"]
            )
        else:
            assert regenerated["questions"][index] == initial["questions"][index]
    assert any("其餘四題沿用" in item for item in regenerated["personalization_basis"])

    second_response = client.post(
        f"/api/v1/applications/{application_id}/interview-question-plan/questions/"
        f"{selected_index}/regenerate?stage=manager",
        headers=manager_headers,
    )
    assert second_response.status_code == 200, second_response.text
    second = second_response.json()
    assert second["version"] == 3
    assert (
        second["questions"][selected_index]["question"]
        != regenerated["questions"][selected_index]["question"]
    )
    assert [
        item for index, item in enumerate(second["questions"]) if index != selected_index
    ] == [
        item for index, item in enumerate(regenerated["questions"]) if index != selected_index
    ]

    with testing_session() as db:
        stored = list(
            db.scalars(
                select(InterviewQuestionPlan)
                .where(
                    InterviewQuestionPlan.application_id == application_id,
                    InterviewQuestionPlan.stage == "manager",
                )
                .order_by(InterviewQuestionPlan.version)
            ).all()
        )
        assert [plan.version for plan in stored] == [1, 2, 3]
        assert (
            stored[0].questions[selected_index]["question"]
            == initial["questions"][selected_index]["question"]
        )
        audit = db.scalar(
            select(AuditLog)
            .where(AuditLog.action == "application.interview_question_plan.generate")
            .order_by(AuditLog.id.desc())
        )
        assert audit is not None
        assert audit.details["question_index"] == selected_index
        assert (
            audit.details["question_category"]
            == initial["questions"][selected_index]["category"]
        )

    no_initial_plan = client.post(
        f"/api/v1/applications/{ids['design_application']}/interview-question-plan/"
        "questions/0/regenerate?stage=manager",
        headers=_headers(client, "design-manager"),
    )
    assert no_initial_plan.status_code == 409
    assert client.post(
        f"/api/v1/applications/{application_id}/interview-question-plan/questions/5/"
        "regenerate?stage=manager",
        headers=manager_headers,
    ).status_code == 422
    assert client.post(
        f"/api/v1/applications/{application_id}/interview-question-plan/questions/0/"
        "regenerate?stage=hr",
        headers=manager_headers,
    ).status_code == 403
    assert client.post(
        f"/api/v1/applications/{application_id}/interview-question-plan/questions/0/"
        "regenerate?stage=manager",
        headers=_headers(client, "admin"),
    ).status_code == 403

    default_hr = client.get(
        f"/api/v1/applications/{application_id}/interview-question-plan?stage=hr",
        headers=_headers(client, "hr"),
    ).json()
    regenerated_hr_response = client.post(
        f"/api/v1/applications/{application_id}/interview-question-plan/questions/0/"
        "regenerate?stage=hr",
        headers=_headers(client, "hr"),
    )
    assert regenerated_hr_response.status_code == 200, regenerated_hr_response.text
    regenerated_hr = regenerated_hr_response.json()
    assert regenerated_hr["version"] == 1
    assert regenerated_hr["questions"][0]["question"] != default_hr["questions"][0]["question"]
    assert regenerated_hr["questions"][1:] == default_hr["questions"][1:]


def test_interview_record_is_linked_to_exact_question_plan_version(
    application_client,
) -> None:
    client, _, ids = application_client
    application_id = ids["engineering_application"]
    hr_headers = _headers(client, "hr")
    manager_headers = _headers(client, "engineering-manager")
    plan_response = client.post(
        f"/api/v1/applications/{application_id}/interview-question-plan/generate?stage=hr",
        headers=hr_headers,
    )
    assert plan_response.status_code == 200, plan_response.text
    plan = plan_response.json()
    assert plan["id"] is not None

    payload = {
        "stage": "hr",
        "question_plan_id": plan["id"],
        "interviewed_at": "2030-08-20T09:30:00+08:00",
        "duration_minutes": 45,
        "mode": "video",
        "status": "in_progress",
        "questions": [
            {
                "question": item["question"],
                "trait": item["category"],
                "purpose": item["purpose"],
                "follow_up": item["follow_up"],
                "source": item["source"],
            }
            for item in plan["questions"]
        ],
    }
    created = client.post(
        f"/api/v1/applications/{application_id}/interview-records",
        headers=hr_headers,
        json=payload,
    )
    assert created.status_code == 201, created.text
    assert created.json()["question_plan_id"] == plan["id"]
    assert created.json()["question_plan_version"] == plan["version"]

    wrong_stage = client.post(
        f"/api/v1/applications/{application_id}/interview-records",
        headers=manager_headers,
        json={**payload, "stage": "manager"},
    )
    assert wrong_stage.status_code == 422
    missing_plan = client.post(
        f"/api/v1/applications/{application_id}/interview-records",
        headers=hr_headers,
        json={**payload, "question_plan_id": 999_999},
    )
    assert missing_plan.status_code == 422

    immutable_link = client.patch(
        f"/api/v1/applications/{application_id}/interview-records/{created.json()['id']}",
        headers=hr_headers,
        json={"question_plan_id": None},
    )
    assert immutable_link.status_code == 422


def test_gemini_daily_generation_limit_is_enforced(
    application_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, ids = application_client
    settings = get_settings()
    monkeypatch.setattr(settings, "gemini_enabled", True)
    monkeypatch.setattr(settings, "gemini_api_key", "daily-limit-test-key")
    monkeypatch.setattr(settings, "gemini_daily_generation_limit_per_user", 1)
    calls = 0

    def fake_generate(**_kwargs):
        nonlocal calls
        calls += 1
        return (
            interview_routes.standard_hr_question_plan(),
            ["Test Gemini plan"],
            "gemini",
            GeminiTokenUsage(total_tokens=100),
        )

    monkeypatch.setattr(interview_routes, "gemini_hr_question_plan", fake_generate)
    endpoint = (
        f"/api/v1/applications/{ids['engineering_application']}"
        "/interview-question-plan/generate?stage=hr"
    )
    headers = _headers(client, "hr")
    first = client.post(endpoint, headers=headers)
    assert first.status_code == 200, first.text
    assert calls == 1

    limited = client.post(f"{endpoint}&force=true", headers=headers)
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) > 0
    assert calls == 1


def test_trait_questions_differ_for_two_resumes_on_the_same_job(
    application_client,
) -> None:
    client, testing_session, ids = application_client
    with testing_session() as db:
        alice = db.get(Candidate, ids["alice"])
        bob = db.get(Candidate, ids["bob"])
        engineering_job = db.get(JobRequisition, ids["engineering_job"])
        assert alice is not None
        assert bob is not None
        assert engineering_job is not None
        alice.current_title = "Backend Developer"
        alice.total_years = 5
        bob.current_title = "Product Designer"
        bob.total_years = 3
        engineering_job.skills = ["Python", "System Design"]
        db.add_all(
            [
                CandidateSkill(
                    candidate_id=alice.id,
                    skill="Python",
                    skill_norm="python",
                ),
                CandidateSkill(
                    candidate_id=bob.id,
                    skill="Figma",
                    skill_norm="figma",
                ),
                CandidateExperience(
                    candidate_id=alice.id,
                    company="API Works",
                    title="Backend Developer",
                    description="Built payment services",
                    sort_order=0,
                ),
                CandidateExperience(
                    candidate_id=bob.id,
                    company="Design Lab",
                    title="Product Designer",
                    description="Redesigned onboarding journeys",
                    sort_order=0,
                ),
            ]
        )
        bob_engineering_application = JobApplication(
            requisition_id=engineering_job.id,
            candidate_id=bob.id,
            status="submitted",
            source="career_site",
        )
        db.add(bob_engineering_application)
        db.commit()
        bob_application_id = bob_engineering_application.id

    headers = _headers(client, "hr")
    payload = {"personality_traits": ["主動積極"]}
    alice_response = client.post(
        f"/api/v1/applications/{ids['engineering_application']}/interview-question-suggestions",
        headers=headers,
        json=payload,
    )
    bob_response = client.post(
        f"/api/v1/applications/{bob_application_id}/interview-question-suggestions",
        headers=headers,
        json=payload,
    )
    assert alice_response.status_code == 200, alice_response.text
    assert bob_response.status_code == 200, bob_response.text
    alice_body = alice_response.json()
    bob_body = bob_response.json()
    alice_questions = alice_body["suggestions"][0]["questions"]
    bob_questions = bob_body["suggestions"][0]["questions"]
    assert [item["question"] for item in alice_questions] != [
        item["question"] for item in bob_questions
    ]
    assert "Backend Developer" in alice_questions[0]["question"]
    assert "Product Designer" in bob_questions[0]["question"]
    assert alice_questions[0]["source"] == "最近經歷：Backend Developer"
    assert bob_questions[0]["source"] == "最近經歷：Product Designer"
    assert alice_body["application_id"] == ids["engineering_application"]
    assert bob_body["application_id"] == bob_application_id
    assert any("候選人技能：Python" in item for item in alice_body["personalization_basis"])
    assert any("候選人技能：Figma" in item for item in bob_body["personalization_basis"])
    assert (
        client.post(
            f"/api/v1/applications/{bob_application_id}/interview-question-suggestions",
            headers=_headers(client, "design-manager"),
            json=payload,
        ).status_code
        == 403
    )
