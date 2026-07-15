from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.models import Candidate, Department, JobApplication, JobRequisition, User
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
