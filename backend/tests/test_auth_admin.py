from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

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
from app.models.candidate import Candidate
from app.models.organization import Department, User
from app.models.recruitment import ResumeFile
from app.models.security import (  # noqa: F401
    AuditLog,
    RefreshToken,
    SystemIssue,
    SystemSetting,
)
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


def test_login_timestamp_uses_system_clock_and_has_utc_offset(auth_client) -> None:
    client, _ = auth_client
    before = datetime.now(UTC) - timedelta(seconds=1)
    admin = login(client, "rootadmin", "Bootstrap-Test-Password-123")
    users = client.get(
        "/admin/users", headers=bearer(admin["access_token"])
    )
    after = datetime.now(UTC) + timedelta(seconds=1)
    assert users.status_code == 200
    root = next(item for item in users.json() if item["username"] == "rootadmin")
    timestamp = root["last_login_at"]
    assert timestamp.endswith(("Z", "+00:00"))
    recorded = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    assert before <= recorded <= after


def test_system_admin_resets_one_time_temporary_password_with_audit(auth_client) -> None:
    client, testing_session = auth_client
    manager_session = login(client, "manager", "Manager-Test-Password-123")
    with testing_session() as db:
        manager = db.scalar(select(User).where(User.username == "manager"))
        assert manager is not None
        manager_id = manager.id

    admin = login(client, "rootadmin", "Bootstrap-Test-Password-123")
    response = client.post(
        f"/admin/users/{manager_id}/reset-password",
        headers=bearer(admin["access_token"]),
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    payload = response.json()
    temporary_password = payload["temporary_password"]
    assert payload["user_id"] == manager_id
    assert payload["username"] == "manager"
    assert payload["sessions_revoked"] >= 1
    assert len(temporary_password) >= 24
    assert any(character.isupper() for character in temporary_password)
    assert any(character.islower() for character in temporary_password)
    assert any(character.isdigit() for character in temporary_password)
    assert any(not character.isalnum() for character in temporary_password)

    assert client.post(
        "/auth/login",
        json={"username": "manager", "password": "Manager-Test-Password-123"},
    ).status_code == 401
    assert client.post(
        "/auth/refresh",
        json={"refresh_token": manager_session["refresh_token"]},
    ).status_code == 401
    assert login(client, "manager", temporary_password)["access_token"]

    users = client.get(
        "/admin/users", headers=bearer(admin["access_token"])
    ).json()
    reset_user = next(item for item in users if item["id"] == manager_id)
    assert reset_user["created_at"]
    assert reset_user["updated_at"]
    assert reset_user["last_login_at"]
    assert reset_user["password_changed_at"]
    assert {item["role"] for item in users} == {"admin", "hr", "manager"}

    with testing_session() as db:
        manager = db.get(User, manager_id)
        assert manager is not None
        assert manager.password_hash != temporary_password
        assert temporary_password not in manager.password_hash
        assert verify_password(temporary_password, manager.password_hash)
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "password.reset",
                AuditLog.resource_id == str(manager_id),
            )
        )
        assert audit is not None
        assert audit.actor_user_id != manager_id
        assert audit.ip_address == "testclient"
        assert audit.details is not None
        assert audit.details["target_username"] == "manager"
        assert audit.details["temporary_password_issued"] is True
        assert temporary_password not in str(audit.details)


def test_system_admin_sets_chosen_password_as_hash_and_revokes_sessions(auth_client) -> None:
    client, testing_session = auth_client
    manager_session = login(client, "manager", "Manager-Test-Password-123")
    with testing_session() as db:
        manager = db.scalar(select(User).where(User.username == "manager"))
        assert manager is not None
        manager_id = manager.id

    admin = login(client, "rootadmin", "Bootstrap-Test-Password-123")
    chosen_password = "Chosen-Manager-Password-456"
    mismatch = client.patch(
        f"/admin/users/{manager_id}",
        json={"password": chosen_password, "password_confirm": "Different-Password-789"},
        headers=bearer(admin["access_token"]),
    )
    assert mismatch.status_code == 422
    response = client.patch(
        f"/admin/users/{manager_id}",
        json={"password": chosen_password, "password_confirm": chosen_password},
        headers=bearer(admin["access_token"]),
    )
    assert response.status_code == 200
    assert "password" not in response.json()
    assert client.post(
        "/auth/login",
        json={"username": "manager", "password": "Manager-Test-Password-123"},
    ).status_code == 401
    assert client.post(
        "/auth/refresh",
        json={"refresh_token": manager_session["refresh_token"]},
    ).status_code == 401
    assert login(client, "manager", chosen_password)["access_token"]

    with testing_session() as db:
        manager = db.get(User, manager_id)
        assert manager is not None
        assert manager.password_hash != chosen_password
        assert chosen_password not in manager.password_hash
        assert verify_password(chosen_password, manager.password_hash)
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "password.set",
                AuditLog.resource_id == str(manager_id),
            )
        )
        assert audit is not None
        assert audit.ip_address == "testclient"
        assert audit.details is not None
        assert audit.details["target_username"] == "manager"
        assert audit.details["sessions_revoked"] >= 1
        assert chosen_password not in str(audit.details)


def test_password_reset_is_forbidden_to_hr_and_manager(auth_client) -> None:
    client, testing_session = auth_client
    with testing_session() as db:
        manager = db.scalar(select(User).where(User.username == "manager"))
        assert manager is not None
        manager_id = manager.id

    hr = login(client, "hruser", "HR-Test-Password-123")
    manager_session = login(client, "manager", "Manager-Test-Password-123")
    assert client.post(
        f"/admin/users/{manager_id}/reset-password",
        headers=bearer(hr["access_token"]),
    ).status_code == 403
    assert client.post(
        f"/admin/users/{manager_id}/reset-password",
        headers=bearer(manager_session["access_token"]),
    ).status_code == 403
    assert client.post(f"/admin/users/{manager_id}/reset-password").status_code == 401
    assert client.patch(
        f"/admin/users/{manager_id}",
        json={"password": "HR-Must-Not-Reset-This-Password"},
        headers=bearer(hr["access_token"]),
    ).status_code == 403
    assert login(client, "manager", "Manager-Test-Password-123")["access_token"]


def test_it_role_can_reset_password(auth_client) -> None:
    client, testing_session = auth_client
    admin = login(client, "rootadmin", "Bootstrap-Test-Password-123")
    created = client.post(
        "/admin/users",
        json={
            "username": "itoperator",
            "email": "itoperator@example.test",
            "password": "IT-Operator-Password-123",
            "display_name": "IT Operator",
            "role": "it",
            "department_id": None,
        },
        headers=bearer(admin["access_token"]),
    )
    assert created.status_code == 201
    it_session = login(client, "itoperator", "IT-Operator-Password-123")
    with testing_session() as db:
        manager = db.scalar(select(User).where(User.username == "manager"))
        assert manager is not None
        manager_id = manager.id
    reset = client.post(
        f"/admin/users/{manager_id}/reset-password",
        headers=bearer(it_session["access_token"]),
    )
    assert reset.status_code == 200
    assert reset.json()["temporary_password"]


def test_hr_creates_persisted_login_without_privilege_escalation(auth_client) -> None:
    client, testing_session = auth_client
    hr = login(client, "hruser", "HR-Test-Password-123")
    headers = bearer(hr["access_token"])
    missing_department = client.post(
        "/admin/users",
        json={
            "username": "unscopedmanager",
            "email": "unscopedmanager@example.test",
            "password": "dept123",
            "display_name": "Unscoped Manager",
            "role": "manager",
            "department_id": None,
        },
        headers=headers,
    )
    assert missing_department.status_code == 422
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
            "progress_percent": 35,
            "expected_completion_date": "2026-07-31",
            "reproduction_steps": "Open the page and apply a filter.",
        },
    )
    assert created.status_code == 201
    issue = created.json()
    assert issue["created_by_user_id"] == issue["updated_by_user_id"]
    assert issue["progress_percent"] == 35
    assert issue["expected_completion_date"] == "2026-07-31"
    assert client.patch(
        f"/admin/system-issues/{issue['id']}",
        headers=headers,
        json={"status": "resolved", "progress_percent": 100, "resolution_notes": "Index rebuilt."},
    ).json()["progress_percent"] == 100
    assert client.patch(
        f"/admin/system-issues/{issue['id']}",
        headers=headers,
        json={"progress_percent": 101},
    ).status_code == 422
    assert len(client.get("/admin/system-issues", headers=headers).json()) == 1
    with testing_session() as db:
        assert db.get(SystemIssue, issue["id"]).resolution_notes == "Index rebuilt."

        candidate = Candidate(
            code="PRIVATE-001",
            name="Private Candidate",
            email="private@example.test",
            phone="0912-345-678",
            city="Taipei",
            photo_path="C:/private/candidate-photo.jpg",
            source="direct",
        )
        db.add(candidate)
        db.flush()
        resume_file = ResumeFile(
            candidate_id=candidate.id,
            storage_key="resumes/private.pdf",
            original_filename="private-name.pdf",
            source_platform="direct",
            parse_status="parsed",
            parsed_payload={"name": "Private Candidate"},
            source_evidence=[{"type": "private"}],
            resume_text="full private resume text",
        )
        db.add_all(
            [
                resume_file,
                SystemSetting(
                    key="integration.secret",
                    value="must-never-appear-in-database-preview",
                    is_secret=True,
                ),
            ]
        )
        db.flush()
        resume_id = resume_file.id
        db.commit()

    created_it = client.post(
        "/admin/users",
        headers=headers,
        json={
            "username": "itviewer",
            "email": "itviewer@example.test",
            "password": "IT-Viewer-Password-123",
            "display_name": "IT Viewer",
            "role": "it",
        },
    )
    assert created_it.status_code == 201
    it_headers = bearer(
        login(client, "itviewer", "IT-Viewer-Password-123")["access_token"]
    )

    overview_response = client.get("/admin/database/overview", headers=it_headers)
    assert overview_response.status_code == 200
    overview = overview_response.json()
    assert overview["healthy"] is True
    assert overview["dialect"] == "sqlite"
    users_table = next(item for item in overview["tables"] if item["name"] == "users")
    assert users_table["display_name"] == "後台登入人員"
    resumes_table = next(item for item in overview["tables"] if item["name"] == "resume_files")
    assert resumes_table["display_name"] == "履歷檔案與解析紀錄"
    assert "解析內容" in resumes_table["description"]
    assert isinstance(users_table["row_count"], int)
    assert {column["name"] for column in users_table["columns"]} >= {"id", "username"}
    assert "database_url" not in overview
    assert "rows" not in users_table
    assert users_table["can_create"] is False
    assert users_table["protection_reason"]
    tags_table = next(item for item in overview["tables"] if item["name"] == "tags")
    assert tags_table["can_create"] is True
    assert tags_table["can_update"] is True
    assert tags_table["can_delete"] is True
    assert {"name", "category", "is_active"} <= set(tags_table["editable_columns"])
    candidates_table = next(
        item for item in overview["tables"] if item["name"] == "candidates"
    )
    candidate_columns = {column["name"]: column for column in candidates_table["columns"]}
    assert candidate_columns["name"]["redacted"] is True
    assert candidate_columns["name"]["revealable"] is True
    assert candidate_columns["email_norm"]["revealable"] is False

    preview_response = client.get(
        "/admin/database/tables/users/rows?page=1&page_size=10&search=rootadmin",
        headers=it_headers,
    )
    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["total"] == 1
    assert "password_hash" in preview["redacted_columns"]
    assert "password_hash" not in preview["visible_columns"]
    assert "password_hash" not in preview["rows"][0]
    assert preview["rows"][0]["username"] == "rootadmin"
    assert preview["display_name"] == "後台登入人員"

    user_detail = client.get(
        f"/admin/database/tables/users/rows/{preview['rows'][0]['id']}",
        headers=it_headers,
    )
    assert user_detail.status_code == 200
    assert user_detail.headers["cache-control"] == "no-store"
    assert "password_hash" in user_detail.json()["redacted_columns"]
    assert "password_hash" not in user_detail.json()["row"]

    for table_name, protected_columns in {
        "candidates": {"name", "email", "phone", "city", "photo_path"},
        "resume_files": {
            "storage_key",
            "original_filename",
            "parsed_payload",
            "source_evidence",
            "resume_text",
        },
        "system_settings": {"value", "is_secret"},
    }.items():
        protected_preview = client.get(
            f"/admin/database/tables/{table_name}/rows", headers=it_headers
        )
        assert protected_preview.status_code == 200
        body = protected_preview.json()
        assert protected_columns <= set(body["redacted_columns"])
        assert protected_columns.isdisjoint(body["visible_columns"])
        assert all(protected_columns.isdisjoint(row) for row in body["rows"])

    resume_detail = client.get(
        f"/admin/database/tables/resume_files/rows/{resume_id}",
        headers=it_headers,
    )
    assert resume_detail.status_code == 200
    resume_body = resume_detail.json()
    assert resume_body["row"]["parse_status"] == "parsed"
    assert resume_body["related"]["candidate"] == {
        "id": resume_body["row"]["candidate_id"],
        "code": "PRIVATE-001",
    }
    assert {
        "storage_key",
        "original_filename",
        "parsed_payload",
        "resume_text",
    } <= set(resume_body["redacted_columns"])
    assert "original_filename" not in resume_body["row"]
    assert client.get(
        f"/admin/database/tables/resume_files/rows/{resume_id}?reveal_pii=true",
        headers=it_headers,
    ).status_code == 422

    resume_reason = "協助 HR 確認履歷檔名與解析結果"
    revealed_resume = client.get(
        f"/admin/database/tables/resume_files/rows/{resume_id}?reveal_pii=true",
        headers={**it_headers, "X-PII-Access-Reason": quote(resume_reason)},
    )
    assert revealed_resume.status_code == 200
    revealed_resume_body = revealed_resume.json()
    assert revealed_resume_body["row"]["original_filename"] == "private-name.pdf"
    assert revealed_resume_body["row"]["parsed_payload"] == {
        "name": "Private Candidate"
    }
    assert revealed_resume_body["related"]["candidate"]["name"] == "Private Candidate"
    assert "storage_key" in revealed_resume_body["redacted_columns"]
    assert "storage_key" not in revealed_resume_body["row"]
    assert "resume_text" not in revealed_resume_body["row"]

    candidate_preview = client.get(
        "/admin/database/tables/candidates/rows?search=PRIVATE-001",
        headers=it_headers,
    )
    assert candidate_preview.status_code == 200
    candidate_body = candidate_preview.json()
    assert candidate_body["total"] == 1
    assert "code" in candidate_body["visible_columns"]
    assert candidate_body["rows"][0]["code"] == "PRIVATE-001"
    assert "name" not in candidate_body["rows"][0]

    missing_reason = client.get(
        "/admin/database/tables/candidates/rows?search=PRIVATE-001&reveal_pii=true",
        headers=it_headers,
    )
    assert missing_reason.status_code == 422
    pii_reason = "協助 HR 排查人才資料同步問題"
    revealed_preview = client.get(
        "/admin/database/tables/candidates/rows?search=PRIVATE-001&reveal_pii=true",
        headers={**it_headers, "X-PII-Access-Reason": quote(pii_reason)},
    )
    assert revealed_preview.status_code == 200
    revealed_body = revealed_preview.json()
    assert revealed_body["pii_revealed"] is True
    assert revealed_body["rows"][0]["name"] == "Private Candidate"
    assert revealed_body["rows"][0]["email"] == "private@example.test"
    assert "email_norm" not in revealed_body["visible_columns"]
    with testing_session() as db:
        pii_audit = db.scalar(
            select(AuditLog).where(AuditLog.action == "pii.database_preview")
        )
        assert pii_audit is not None
        assert pii_audit.actor_user_id is not None
        assert pii_audit.resource_id == "candidates"
        assert pii_audit.details["reason"] == pii_reason

    assert client.get(
        "/admin/database/tables/not_a_table/rows", headers=it_headers
    ).status_code == 404

    created_row = client.post(
        "/admin/database/tables/tags/rows",
        headers=it_headers,
        json={
            "values": {
                "name": "資料表手動維護",
                "category": "candidate",
                "is_active": True,
            }
        },
    )
    assert created_row.status_code == 201
    row_id = created_row.json()["row_id"]
    assert created_row.json()["row"]["name"] == "資料表手動維護"

    updated_row = client.patch(
        f"/admin/database/tables/tags/rows/{row_id}",
        headers=it_headers,
        json={"values": {"name": "資料表維護已更新"}},
    )
    assert updated_row.status_code == 200
    assert updated_row.json()["row"]["name"] == "資料表維護已更新"

    protected_write = client.post(
        "/admin/database/tables/users/rows",
        headers=it_headers,
        json={"values": {"username": "unsafe"}},
    )
    assert protected_write.status_code == 403

    deleted_row = client.delete(
        f"/admin/database/tables/tags/rows/{row_id}", headers=it_headers
    )
    assert deleted_row.status_code == 200
    assert deleted_row.json()["row"] is None

    with testing_session() as db:
        database_actions = set(
            db.scalars(
                select(AuditLog.action).where(
                    AuditLog.action.in_(
                        {
                            "database_row_create",
                            "database_row_update",
                            "database_row_delete",
                        }
                    )
                )
            )
        )
        assert database_actions == {
            "database_row_create",
            "database_row_update",
            "database_row_delete",
        }

    hr = login(client, "hruser", "HR-Test-Password-123")
    manager = login(client, "manager", "Manager-Test-Password-123")
    for tokens in (hr, manager):
        denied_headers = bearer(tokens["access_token"])
        assert client.get("/admin/system-issues", headers=denied_headers).status_code == 403
        assert client.get("/admin/database/overview", headers=denied_headers).status_code == 403
        assert client.get(
            "/admin/database/tables/users/rows", headers=denied_headers
        ).status_code == 403
        assert client.post(
            "/admin/database/tables/tags/rows",
            headers=denied_headers,
            json={"values": {"name": "denied", "category": "candidate"}},
        ).status_code == 403
