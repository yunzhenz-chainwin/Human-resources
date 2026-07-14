from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
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
    "admin": "Admin-Integration-Password-123",
    "it": "IT-Integration-Password-123",
    "hr": "HR-Integration-Password-123",
    "manager": "Manager-Integration-Password-123",
}


@pytest.fixture()
def secured_app_client(monkeypatch) -> Generator[tuple[TestClient, sessionmaker, dict], None, None]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
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
    settings.auth_secret_key = "app-integration-secret-with-more-than-32-bytes"
    settings.bootstrap_admin_username = None
    settings.bootstrap_admin_email = None
    settings.bootstrap_admin_password = None

    with testing_session() as db:
        engineering = Department(name="Engineering")
        sales = Department(name="Sales")
        db.add_all([engineering, sales])
        db.flush()
        users = [
            User(
                username="it",
                email="it@app.test",
                password_hash=hash_password(PASSWORDS["it"]),
                display_name="IT",
                role="it",
                is_active=True,
            ),
            User(
                username="admin",
                email="admin@app.test",
                password_hash=hash_password(PASSWORDS["admin"]),
                display_name="Admin",
                role="admin",
                is_active=True,
            ),
            User(
                username="hr",
                email="hr@app.test",
                password_hash=hash_password(PASSWORDS["hr"]),
                display_name="HR",
                role="hr",
                department_id=engineering.id,
                is_active=True,
            ),
            User(
                username="manager",
                email="manager@app.test",
                password_hash=hash_password(PASSWORDS["manager"]),
                display_name="Manager",
                role="manager",
                department_id=engineering.id,
                is_active=True,
            ),
        ]
        candidate = Candidate(code="SEC-001", name="Security Candidate", source="direct")
        scoped_candidate = Candidate(
            code="SEC-002", name="Engineering Candidate", source="direct"
        )
        db.add_all([*users, candidate, scoped_candidate])
        db.flush()
        public_job = JobRequisition(
            req_no="SEC-SALES-001",
            title="Sales Specialist",
            department_id=sales.id,
            employment_type="full_time",
            work_city="Taipei",
            jd="Sell responsibly",
            status="approved",
            published_at=datetime.now(UTC),
        )
        db.add(public_job)
        engineering_job = JobRequisition(
            req_no="SEC-ENG-001",
            title="Backend Engineer",
            department_id=engineering.id,
            employment_type="full_time",
            work_city="Taipei",
            jd="Build responsibly",
            status="draft",
        )
        db.add(engineering_job)
        db.flush()
        db.add(
            JobApplication(
                requisition_id=engineering_job.id,
                candidate_id=scoped_candidate.id,
                status="submitted",
                source="career_site",
            )
        )
        db.commit()
        ids = {
            "engineering": engineering.id,
            "sales": sales.id,
            "candidate": candidate.id,
            "scoped_candidate": scoped_candidate.id,
            "sales_job": public_job.id,
            "engineering_job": engineering_job.id,
        }

    def override_db():
        with testing_session() as db:
            yield db

    main_module.app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(main_module, "SessionLocal", testing_session)
    with TestClient(main_module.app) as client:
        yield client, testing_session, ids
    main_module.app.dependency_overrides.clear()
    for key, value in original.items():
        setattr(settings, key, value)
    Base.metadata.drop_all(engine)


def login_headers(client: TestClient, role: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": role, "password": PASSWORDS[role]},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_public_boundary_and_protected_routes_require_token(secured_app_client) -> None:
    client, _, ids = secured_app_client
    assert client.get("/api/v1/health").status_code == 200
    jobs = client.get("/api/v1/public/jobs")
    assert jobs.status_code == 200
    assert [job["id"] for job in jobs.json()] == [ids["sales_job"]]

    protected_paths = [
        "/api/v1/candidates",
        "/api/v1/requisitions",
        "/api/v1/resumes",
        f"/api/v1/requisitions/{ids['sales_job']}/matches",
        "/api/v1/reports/funnel",
        "/api/v1/admin/users",
    ]
    assert {path: client.get(path).status_code for path in protected_paths} == {
        path: 401 for path in protected_paths
    }


def test_admin_token_accesses_all_protected_modules(secured_app_client) -> None:
    client, _, ids = secured_app_client
    headers = login_headers(client, "admin")
    paths = [
        "/api/v1/candidates",
        "/api/v1/requisitions",
        "/api/v1/resumes",
        f"/api/v1/requisitions/{ids['sales_job']}/matches",
        "/api/v1/reports/funnel",
        "/api/v1/admin/users",
    ]
    assert {path: client.get(path, headers=headers).status_code for path in paths} == {
        path: 200 for path in paths
    }


@pytest.mark.parametrize("role", ["manager"])
def test_non_admin_roles_cannot_access_admin(secured_app_client, role: str) -> None:
    client, _, _ = secured_app_client
    assert client.get("/api/v1/admin/users", headers=login_headers(client, role)).status_code == 403


def test_hr_can_manage_login_accounts_but_not_system_settings(secured_app_client) -> None:
    client, _, _ = secured_app_client
    headers = login_headers(client, "hr")
    assert client.get("/api/v1/admin/users", headers=headers).status_code == 200
    assert client.get("/api/v1/admin/departments", headers=headers).status_code == 200
    assert client.get("/api/v1/admin/settings", headers=headers).status_code == 403


def test_it_can_administer_but_cannot_read_recruiting_data(secured_app_client) -> None:
    client, _, _ = secured_app_client
    headers = login_headers(client, "it")
    assert client.get("/api/v1/admin/users", headers=headers).status_code == 200
    assert client.get("/api/v1/candidates", headers=headers).status_code == 403
    assert client.get("/api/v1/requisitions", headers=headers).status_code == 403


def test_hr_has_global_recruiting_scope(secured_app_client) -> None:
    client, _, ids = secured_app_client
    headers = login_headers(client, "hr")
    assert client.get(
        f"/api/v1/requisitions/{ids['sales_job']}/matches", headers=headers
    ).status_code == 200
    assert client.get(
        f"/api/v1/reports/funnel?department_id={ids['sales']}", headers=headers
    ).status_code == 200
    jobs = client.get("/api/v1/requisitions", headers=headers)
    assert jobs.status_code == 200
    assert {job["id"] for job in jobs.json()} == {
        ids["sales_job"],
        ids["engineering_job"],
    }


def test_manager_is_department_scoped_and_read_only(secured_app_client) -> None:
    client, _, ids = secured_app_client
    headers = login_headers(client, "manager")
    assert client.get(
        f"/api/v1/requisitions/{ids['sales_job']}", headers=headers
    ).status_code == 403
    assert [job["id"] for job in client.get(
        "/api/v1/requisitions", headers=headers
    ).json()] == [ids["engineering_job"]]
    assert [candidate["id"] for candidate in client.get(
        "/api/v1/candidates", headers=headers
    ).json()] == [ids["scoped_candidate"]]
    assert client.get(
        f"/api/v1/candidates/{ids['scoped_candidate']}", headers=headers
    ).status_code == 200
    assert client.get(
        f"/api/v1/candidates/{ids['candidate']}", headers=headers
    ).status_code == 403
    assert client.get(
        f"/api/v1/reports/funnel?department_id={ids['sales']}", headers=headers
    ).status_code == 403
    assert client.post(
        "/api/v1/candidates",
        headers=headers,
        json={"name": "Must Not Create"},
    ).status_code == 403
    assert client.patch(
        f"/api/v1/candidates/{ids['candidate']}",
        headers=headers,
        json={"name": "Must Not Edit"},
    ).status_code == 403
    assert client.patch(
        f"/api/v1/requisitions/{ids['sales_job']}",
        headers=headers,
        json={"title": "Must Not Edit"},
    ).status_code == 403


def test_candidate_detail_creates_real_audit_log(secured_app_client) -> None:
    client, testing_session, ids = secured_app_client
    headers = login_headers(client, "admin")
    response = client.get(f"/api/v1/candidates/{ids['candidate']}", headers=headers)
    assert response.status_code == 200
    with testing_session() as db:
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "pii.read",
                AuditLog.resource_type == "candidate",
                AuditLog.resource_id == str(ids["candidate"]),
            )
        )
        assert audit is not None
        assert audit.actor_user_id is not None
        assert audit.ip_address == "testclient"
