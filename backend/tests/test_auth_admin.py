from collections.abc import Generator

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.admin import router as admin_router
from app.api.routes.auth import router as auth_router
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.dependencies.auth import audit_pii_read, enforce_department_scope, get_current_user
from app.models.organization import Department, User
from app.models.security import AuditLog, RefreshToken, SystemIssue  # noqa: F401
from app.services.security import bootstrap_admin, hash_password, verify_password


@pytest.fixture()
def auth_client() -> Generator[tuple[TestClient, sessionmaker], None, None]:
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
    settings.auth_secret_key = "test-only-secret-that-is-at-least-32-bytes-long"
    settings.bootstrap_admin_username = "rootadmin"
    settings.bootstrap_admin_email = "root@example.test"
    settings.bootstrap_admin_password = "Bootstrap-Test-Password-123"

    with testing_session() as db:
        admin = bootstrap_admin(db)
        department = Department(name="Engineering", is_active=True)
        db.add(department)
        db.flush()
        db.add_all(
            [
                User(
                    username="hruser",
                    email="hr@example.test",
                    password_hash=hash_password("HR-Test-Password-123"),
                    display_name="HR User",
                    role="hr",
                    department_id=department.id,
                    is_active=True,
                ),
                User(
                    username="manager",
                    email="manager@example.test",
                    password_hash=hash_password("Manager-Test-Password-123"),
                    display_name="Manager",
                    role="manager",
                    department_id=department.id,
                    is_active=True,
                ),
            ]
        )
        db.commit()
        assert admin is not None

    app = FastAPI()

    def override_db():
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.include_router(auth_router)
    app.include_router(admin_router)

    @app.get("/scoped/{department_id}")
    def scoped(department_id: int, user: User = Depends(get_current_user)) -> dict:
        enforce_department_scope(user, department_id)
        return {"allowed": True}

    @app.get("/pii/{candidate_id}")
    def pii(_: User = Depends(audit_pii_read)) -> dict:
        return {"ok": True}

    with TestClient(app) as client:
        yield client, testing_session

    for key, value in original.items():
        setattr(settings, key, value)
    Base.metadata.drop_all(engine)


def login(client: TestClient, username: str, password: str) -> dict:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_scrypt_password_hash_is_salted_and_verifiable() -> None:
    first = hash_password("A-Strong-Test-Password")
    second = hash_password("A-Strong-Test-Password")
    assert first != second
    assert verify_password("A-Strong-Test-Password", first)
    assert not verify_password("wrong", first)


def test_unauthorized_login_access_and_refresh_rotation(auth_client) -> None:
    client, testing_session = auth_client
    assert client.get("/auth/me").status_code == 401
    assert client.post(
        "/auth/login", json={"username": "rootadmin", "password": "wrong"}
    ).status_code == 401

    tokens = login(client, "rootadmin", "Bootstrap-Test-Password-123")
    assert client.get("/auth/me", headers=bearer(tokens["access_token"])).status_code == 200
    refreshed = client.post(
        "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["refresh_token"] != tokens["refresh_token"]
    assert client.post(
        "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    ).status_code == 401
    with testing_session() as db:
        assert db.scalar(select(func.count()).select_from(RefreshToken)) == 2


def test_role_and_department_scope(auth_client) -> None:
    client, _ = auth_client
    hr = login(client, "hruser", "HR-Test-Password-123")
    headers = bearer(hr["access_token"])
    assert client.get("/admin/users", headers=headers).status_code == 200
    assert client.get("/scoped/1", headers=headers).status_code == 200
    assert client.get("/scoped/999", headers=headers).status_code == 200

    admin = login(client, "rootadmin", "Bootstrap-Test-Password-123")
    assert client.get("/scoped/999", headers=bearer(admin["access_token"])).status_code == 200


def test_hr_creates_persisted_login_without_privilege_escalation(auth_client) -> None:
    client, testing_session = auth_client
    hr = login(client, "hruser", "HR-Test-Password-123")
    headers = bearer(hr["access_token"])
    created = client.post(
        "/admin/users",
        json={
            "username": "manager2",
            "email": "manager2@example.test",
            "password": "hr123",
            "display_name": "Manager Two",
            "role": "manager",
            "department_id": 1,
        },
        headers=headers,
    )
    assert created.status_code == 201
    assert login(client, "manager2", "hr123")["access_token"]
    with testing_session() as db:
        assert db.scalar(select(User).where(User.username == "manager2")) is not None
    denied = client.post(
        "/admin/users",
        json={
            "username": "shadowit",
            "email": "shadowit@example.test",
            "password": "it123",
            "display_name": "Shadow IT",
            "role": "it",
        },
        headers=headers,
    )
    assert denied.status_code == 403


def test_admin_manages_resources_and_secret_settings(auth_client) -> None:
    client, _ = auth_client
    tokens = login(client, "rootadmin", "Bootstrap-Test-Password-123")
    headers = bearer(tokens["access_token"])

    department = client.post(
        "/admin/departments", json={"name": "Sales"}, headers=headers
    )
    assert department.status_code == 201
    user = client.post(
        "/admin/users",
        json={
            "username": "saleshr",
            "email": "saleshr@example.test",
            "password": "Sales-HR-Password-123",
            "display_name": "Sales HR",
            "role": "hr",
            "department_id": department.json()["id"],
        },
        headers=headers,
    )
    assert user.status_code == 201
    assert client.post(
        "/admin/skills", json={"name": "Python"}, headers=headers
    ).status_code == 201
    assert client.post(
        "/admin/tags", json={"name": "優先", "category": "candidate"}, headers=headers
    ).status_code == 201
    setting = client.put(
        "/admin/settings/integration.secret",
        json={"value": "must-not-be-returned", "is_secret": True},
        headers=headers,
    )
    assert setting.status_code == 200
    assert setting.json()["value"] is None
    assert client.get("/admin/settings", headers=headers).json()[0]["value"] is None
    assert len(client.get("/admin/audit-logs", headers=headers).json()) >= 5


def test_personal_data_read_writes_audit(auth_client) -> None:
    client, testing_session = auth_client
    tokens = login(client, "hruser", "HR-Test-Password-123")
    assert client.get("/pii/42", headers=bearer(tokens["access_token"])).status_code == 200
    with testing_session() as db:
        log = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "pii.read", AuditLog.resource_id == "42"
            )
        )
        assert log is not None
        assert log.resource_type == "candidate"
        assert log.department_id == 1


def test_bootstrap_requires_explicit_environment(auth_client) -> None:
    _, testing_session = auth_client
    settings = get_settings()
    settings.bootstrap_admin_username = None
    settings.bootstrap_admin_email = None
    settings.bootstrap_admin_password = None
    with testing_session() as db:
        assert bootstrap_admin(db) is None


def test_it_operations_issue_tracker_and_safe_database_overview(auth_client) -> None:
    client, testing_session = auth_client
    admin = login(client, "rootadmin", "Bootstrap-Test-Password-123")
    headers = bearer(admin["access_token"])

    created = client.post(
        "/admin/system-issues",
        headers=headers,
        json={
            "title": "Candidate page timeout",
            "description": "The page did not finish loading.",
            "page": "/candidates",
            "severity": "high",
            "status": "open",
            "reproduction_steps": "Open the page and apply a filter.",
        },
    )
    assert created.status_code == 201
    issue = created.json()
    assert issue["created_by_user_id"] == issue["updated_by_user_id"]
    assert client.patch(
        f"/admin/system-issues/{issue['id']}",
        headers=headers,
        json={"status": "resolved", "resolution_notes": "Index rebuilt."},
    ).json()["status"] == "resolved"
    assert len(client.get("/admin/system-issues", headers=headers).json()) == 1
    with testing_session() as db:
        assert db.get(SystemIssue, issue["id"]).resolution_notes == "Index rebuilt."

    overview_response = client.get("/admin/database/overview", headers=headers)
    assert overview_response.status_code == 200
    overview = overview_response.json()
    assert overview["healthy"] is True
    assert overview["dialect"] == "sqlite"
    users_table = next(item for item in overview["tables"] if item["name"] == "users")
    assert isinstance(users_table["row_count"], int)
    assert {column["name"] for column in users_table["columns"]} >= {"id", "username"}
    assert "database_url" not in overview
    assert "rows" not in users_table

    hr = login(client, "hruser", "HR-Test-Password-123")
    manager = login(client, "manager", "Manager-Test-Password-123")
    for tokens in (hr, manager):
        denied_headers = bearer(tokens["access_token"])
        assert client.get("/admin/system-issues", headers=denied_headers).status_code == 403
        assert client.get("/admin/database/overview", headers=denied_headers).status_code == 403
