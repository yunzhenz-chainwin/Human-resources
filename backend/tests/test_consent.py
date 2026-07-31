from collections.abc import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.auth import router as auth_router
from app.api.routes.consent import router as consent_router
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.models.candidate import Candidate
from app.models.consent import CandidateConsent, ConsentNotice
from app.models.organization import Department, User
from app.services.security import bootstrap_admin, hash_password


@pytest.fixture()
def consent_client() -> Generator[tuple[TestClient, sessionmaker, dict[str, int]], None, None]:
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

    ids: dict[str, int] = {}
    with testing_session() as db:
        bootstrap_admin(db)
        department = Department(name="Engineering", is_active=True)
        other = Department(name="Sales", is_active=True)
        db.add_all([department, other])
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
                    department_id=other.id,
                    is_active=True,
                ),
            ]
        )
        candidate = Candidate(code="C-0001", name="Applicant One")
        db.add(candidate)
        db.commit()
        ids["candidate_id"] = candidate.id

    app = FastAPI()

    def override_db():
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.include_router(auth_router)
    app.include_router(consent_router)

    with TestClient(app) as client:
        yield client, testing_session, ids

    for key, value in original.items():
        setattr(settings, key, value)
    Base.metadata.drop_all(engine)


def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_create_versions_and_single_active_switch(consent_client) -> None:
    client, testing_session, _ = consent_client
    admin = _login(client, "rootadmin", "Bootstrap-Test-Password-123")

    first = client.post(
        "/consent/notices",
        headers=admin,
        json={"title": "招募告知 v1", "body": "第一版條款", "purpose_code": "002 人事管理", "activate": True},
    )
    assert first.status_code == 201, first.text
    assert first.json()["version"] == 1
    assert first.json()["is_active"] is True

    second = client.post(
        "/consent/notices",
        headers=admin,
        json={"title": "招募告知 v2", "body": "第二版條款", "activate": False},
    )
    assert second.status_code == 201
    assert second.json()["version"] == 2
    assert second.json()["is_active"] is False

    # Activating the second must leave exactly one active notice.
    activated = client.post(
        f"/consent/notices/{second.json()['id']}/activate", headers=admin
    )
    assert activated.status_code == 200
    assert activated.json()["is_active"] is True

    with testing_session() as db:
        active_count = db.scalar(
            select(func.count()).select_from(ConsentNotice).where(ConsentNotice.is_active.is_(True))
        )
        assert active_count == 1

    active = client.get("/consent/notices/active", headers=admin)
    assert active.status_code == 200
    assert active.json()["version"] == 2

    listing = client.get("/consent/notices", headers=admin)
    assert listing.status_code == 200
    assert [item["version"] for item in listing.json()] == [2, 1]


def test_record_and_withdraw_candidate_consent(consent_client) -> None:
    client, testing_session, ids = consent_client
    admin = _login(client, "rootadmin", "Bootstrap-Test-Password-123")
    candidate_id = ids["candidate_id"]

    # No active notice yet -> cannot record.
    blocked = client.post(
        f"/candidates/{candidate_id}/consents", headers=admin, json={"channel": "hr_manual"}
    )
    assert blocked.status_code == 409

    client.post(
        "/consent/notices",
        headers=admin,
        json={"title": "招募告知", "body": "條款全文", "activate": True},
    )

    recorded = client.post(
        f"/candidates/{candidate_id}/consents",
        headers=admin,
        json={"channel": "public_form"},
    )
    assert recorded.status_code == 201, recorded.text
    consent_id = recorded.json()["id"]
    assert recorded.json()["notice_version"] == 1
    assert recorded.json()["channel"] == "public_form"
    assert recorded.json()["withdrawn_at"] is None

    listing = client.get(f"/candidates/{candidate_id}/consents", headers=admin)
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    withdrawn = client.post(
        f"/consent/candidate-consents/{consent_id}/withdraw", headers=admin
    )
    assert withdrawn.status_code == 200
    assert withdrawn.json()["withdrawn_at"] is not None

    with testing_session() as db:
        stored = db.get(CandidateConsent, consent_id)
        assert stored is not None and stored.withdrawn_at is not None


def test_permissions_require_manager_for_management(consent_client) -> None:
    client, _, ids = consent_client
    hr = _login(client, "hruser", "HR-Test-Password-123")
    manager = _login(client, "manager", "Manager-Test-Password-123")

    # HR (recruiting manager role) may create notices.
    created = client.post(
        "/consent/notices",
        headers=hr,
        json={"title": "HR 版本", "body": "內容", "activate": True},
    )
    assert created.status_code == 201

    # Department manager cannot create or activate notices.
    assert client.post(
        "/consent/notices", headers=manager, json={"title": "x", "body": "y"}
    ).status_code == 403
    assert client.post(
        f"/consent/notices/{created.json()['id']}/activate", headers=manager
    ).status_code == 403

    # Department manager is outside this candidate's scope (no application).
    candidate_id = ids["candidate_id"]
    assert client.post(
        f"/candidates/{candidate_id}/consents", headers=manager, json={"channel": "hr_manual"}
    ).status_code == 403


def test_active_notice_missing_returns_404(consent_client) -> None:
    client, _, _ = consent_client
    admin = _login(client, "rootadmin", "Bootstrap-Test-Password-123")
    assert client.get("/consent/notices/active", headers=admin).status_code == 404
