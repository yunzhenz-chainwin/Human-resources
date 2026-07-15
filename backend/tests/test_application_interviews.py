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
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.models import (
    Candidate,
    CandidateEducation,
    CandidateExperience,
    CandidateSkill,
    Department,
    JobApplication,
    JobRequisition,
    ResumeFile,
    User,
)
from app.models.security import AuditLog
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
    }
    settings.auth_secret_key = "application-test-secret-key-with-at-least-32-bytes"
    settings.bootstrap_admin_username = None
    settings.bootstrap_admin_email = None
    settings.bootstrap_admin_password = None

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
    assert client.get(
        "/api/v1/applications", headers=_headers(client, "it")
    ).status_code == 403

    hr_response = client.get(
        "/api/v1/applications", headers=_headers(client, "hr")
    )
    assert hr_response.status_code == 200
    assert {item["id"] for item in hr_response.json()} == {
        ids["engineering_application"],
        ids["design_application"],
    }
    assert all(set(item) == APPLICATION_KEYS for item in hr_response.json())
    assert all(item["candidate"]["id"] == item["candidate_id"] for item in hr_response.json())
    assert all(
        item["requisition"]["id"] == item["requisition_id"]
        for item in hr_response.json()
    )
    for item in hr_response.json():
        _assert_aware(item["applied_at"])

    engineering_headers = _headers(client, "engineering-manager")
    own = client.get("/api/v1/applications", headers=engineering_headers)
    assert own.status_code == 200
    assert [item["id"] for item in own.json()] == [ids["engineering_application"]]
    assert client.get(
        f"/api/v1/applications?department_id={ids['design']}",
        headers=engineering_headers,
    ).status_code == 403
    assert client.get(
        f"/api/v1/applications?requisition_id={ids['design_job']}",
        headers=engineering_headers,
    ).status_code == 403
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
        def materialize(self, key: str):
            path = stored_paths.get(key)
            if path is None:
                raise FileNotFoundError(key)
            return nullcontext(path)

    monkeypatch.setattr(
        "app.api.routes.resumes.get_storage_provider",
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
    assert client.get(
        f"/api/v1/candidates/{ids['alice']}", headers=design_headers
    ).status_code == 403

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
    assert len(engineering_body["applications"]) == 1
    assert engineering_body["applications"][0]["requisition_id"] == ids["engineering_job"]
    assert engineering_body["applications"][0]["cover_letter"] == (
        "Engineering-only cover letter"
    )
    assert engineering_body["applications"][0]["linkedin_url"] is None
    assert "Design-only private cover letter" not in engineering_detail.text
    assert [item["id"] for item in engineering_body["resumes"]] == [engineering_resume_id]
    assert engineering_body["resumes"][0]["has_file"] is True

    design_detail = client.get(
        f"/api/v1/candidates/{ids['alice']}", headers=design_headers
    )
    assert design_detail.status_code == 200
    design_body = design_detail.json()
    assert len(design_body["applications"]) == 1
    assert design_body["applications"][0]["requisition_id"] == ids["design_job"]
    assert "Engineering-only cover letter" not in design_detail.text
    assert [item["id"] for item in design_body["resumes"]] == [design_resume_id]
    assert design_body["resumes"][0]["resume_url"] is None

    own_download = client.get(
        f"/api/v1/resumes/{engineering_resume_id}/file",
        headers={**engineering_headers, "User-Agent": "candidate-detail-test"},
    )
    assert own_download.status_code == 200
    assert own_download.content == engineering_bytes
    assert own_download.headers["cache-control"] == "private, no-store"
    assert "engineering.pdf" in own_download.headers["content-disposition"]
    assert client.get(
        f"/api/v1/resumes/{design_resume_id}/file",
        headers=engineering_headers,
    ).status_code == 403

    with testing_session() as db:
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "resume.download",
                AuditLog.resource_id == str(engineering_resume_id),
            )
        )
        assert audit is not None
        assert audit.department_id == ids["engineering"]
        assert audit.details["candidate_id"] == ids["alice"]
        assert audit.ip_address is not None


def test_hr_assignment_returns_full_dto_and_rejects_duplicates(application_client) -> None:
    client, testing_session, ids = application_client
    payload = {
        "candidate_id": ids["alice"],
        "requisition_id": ids["design_job"],
    }
    assert client.post(
        "/api/v1/applications",
        headers=_headers(client, "engineering-manager"),
        json=payload,
    ).status_code == 403
    assert client.post(
        "/api/v1/applications",
        headers=_headers(client, "it"),
        json=payload,
    ).status_code == 403

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
    assert client.post(
        "/api/v1/applications",
        headers=hr_headers,
        json={"candidate_id": 999999, "requisition_id": ids["design_job"]},
    ).status_code == 404
    assert client.post(
        "/api/v1/applications",
        headers=hr_headers,
        json={"candidate_id": ids["alice"], "requisition_id": 999999},
    ).status_code == 404
    assert client.post(
        "/api/v1/applications",
        headers=hr_headers,
        json={"candidate_id": ids["deleted"], "requisition_id": ids["design_job"]},
    ).status_code == 409

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

    assert client.patch(
        endpoint,
        headers=_headers(client, "engineering-manager"),
        json=payload,
    ).status_code == 403
    assert client.patch(
        endpoint,
        headers=_headers(client, "it"),
        json=payload,
    ).status_code == 403

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
    assert engineering_resumes.status_code == 200
    assert reassigned_resume_ids.isdisjoint(
        {item["id"] for item in engineering_resumes.json()}
    )
    design_resumes = client.get(
        "/api/v1/resumes?include_confirmed=true",
        headers=_headers(client, "design-manager"),
    )
    assert design_resumes.status_code == 200
    assert reassigned_resume_ids.issubset({item["id"] for item in design_resumes.json()})

    engineering_candidates = client.get(
        "/api/v1/candidates",
        headers=_headers(client, "engineering-manager"),
    )
    assert engineering_candidates.status_code == 200
    assert ids["alice"] not in {item["id"] for item in engineering_candidates.json()}
    design_candidates = client.get(
        "/api/v1/candidates",
        headers=_headers(client, "design-manager"),
    )
    assert design_candidates.status_code == 200
    assert ids["alice"] in {item["id"] for item in design_candidates.json()}

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
        assert (
            db.get(ResumeFile, unlinked_resume_id).target_requisition_id
            == ids["design_job"]
        )

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
        assert (
            db.get(ResumeFile, unlinked_resume_id).target_requisition_id
            == ids["design_job"]
        )

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
    assert ids["alice"] in {item["id"] for item in engineering_candidates.json()}
    engineering_resumes = client.get(
        "/api/v1/resumes?include_confirmed=true",
        headers=_headers(client, "engineering-manager"),
    )
    assert reassigned_resume_ids.isdisjoint(
        {item["id"] for item in engineering_resumes.json()}
    )


def test_department_manager_updates_interview_with_status_sync_and_audit(
    application_client,
) -> None:
    client, testing_session, ids = application_client
    application_id = ids["design_application"]
    endpoint = f"/api/v1/applications/{application_id}/interview"
    engineering_headers = _headers(client, "engineering-manager")
    design_headers = _headers(client, "design-manager")
    assert client.patch(
        endpoint,
        headers=engineering_headers,
        json={"interview_result": "pending"},
    ).status_code == 403
    assert client.patch(
        endpoint,
        headers=_headers(client, "it"),
        json={"interview_result": "pending"},
    ).status_code == 403
    assert client.patch(endpoint, headers=design_headers, json={}).status_code == 422
    assert client.patch(
        endpoint,
        headers=design_headers,
        json={"interview_at": "2030-08-20T09:30:00"},
    ).status_code == 422
    assert client.patch(
        endpoint,
        headers=design_headers,
        json={"interview_result": "unknown"},
    ).status_code == 422

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

    assert client.patch(
        hr_endpoint,
        headers=design_headers,
        json={"interview_notes": "Manager must not edit HR feedback"},
    ).status_code == 403
    assert client.patch(
        manager_endpoint,
        headers=hr_headers,
        json={"interview_notes": "HR must not edit manager feedback"},
    ).status_code == 403
    assert client.patch(
        manager_endpoint,
        headers=_headers(client, "engineering-manager"),
        json={"interview_notes": "Other department"},
    ).status_code == 403
    assert client.patch(
        f"/api/v1/applications/{application_id}/interviews/third",
        headers=hr_headers,
        json={"interview_notes": "Invalid stage"},
    ).status_code == 422

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
    assert hr_body["interview_notes"] == (
        "HR recommends advancing; communication is clear."
    )

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
