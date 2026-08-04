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
from app.models import (
    Candidate,
    CandidateActivity,
    Department,
    JobApplication,
    JobRequisition,
    MatchResult,
    User,
)
from app.models.security import AuditLog
from app.services.security import hash_password

PASSWORDS = {
    "admin": "Admin-Integration-Password-123",
    "it": "IT-Integration-Password-123",
    "hr": "HR-Integration-Password-123",
    "manager": "Manager-Integration-Password-123",
    "sales_manager": "Sales-Manager-Integration-Password-123",
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
            User(
                username="sales_manager",
                email="sales-manager@app.test",
                password_hash=hash_password(PASSWORDS["sales_manager"]),
                display_name="Sales Manager",
                role="manager",
                department_id=sales.id,
                is_active=True,
            ),
        ]
        candidate = Candidate(code="SEC-001", name="Security Candidate", source="direct")
        scoped_candidate = Candidate(
            code="SEC-002",
            name="Engineering Candidate",
            email="engineering.candidate@app.test",
            phone="0912-000-789",
            city="Taipei",
            source="direct",
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
    talent_pool = client.get("/api/v1/candidates", headers=headers)
    assert talent_pool.status_code == 200
    assert {candidate["id"] for candidate in talent_pool.json()} == {
        ids["candidate"],
        ids["scoped_candidate"],
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
    # The company talent pool is an HR-only catalogue. Managers must enter
    # through their department applications/workspace instead of enumerating it.
    assert client.get(
        "/api/v1/candidates", headers=headers
    ).status_code == 403
    scoped_detail = client.get(
        f"/api/v1/candidates/{ids['scoped_candidate']}", headers=headers
    )
    assert scoped_detail.status_code == 200
    assert scoped_detail.json()["email"] == "e***@app.test"
    assert scoped_detail.json()["phone"] == "*******789"
    assert scoped_detail.json()["city"] is None
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
    assert client.patch(
        f"/api/v1/requisitions/{ids['engineering_job']}",
        headers=headers,
        json={"title": "Must Not Edit Own Department Here"},
    ).status_code == 403


def test_hr_and_department_managers_share_only_scoped_candidate_activities(
    secured_app_client,
) -> None:
    client, testing_session, ids = secured_app_client
    hr_headers = login_headers(client, "hr")
    admin_headers = login_headers(client, "admin")
    manager_headers = login_headers(client, "manager")
    sales_manager_headers = login_headers(client, "sales_manager")
    it_headers = login_headers(client, "it")
    scoped_url = f"/api/v1/candidates/{ids['scoped_candidate']}/activities"
    unscoped_url = f"/api/v1/candidates/{ids['candidate']}/activities"

    hr_response = client.post(
        scoped_url,
        headers=hr_headers,
        json={
            "type": "HR note",
            "content": "HR asks the manager to review this applicant.",
            "next_status": "contacted",
        },
    )
    assert hr_response.status_code == 201
    hr_activity = hr_response.json()
    assert hr_activity["candidate_id"] == ids["scoped_candidate"]
    assert hr_activity["author_name"] == "HR"
    assert hr_activity["author_role"] == "hr"
    assert hr_activity["author_department_id"] == ids["engineering"]
    assert hr_activity["author_department_name"] == "Engineering"
    assert hr_activity["user_id"] is not None
    assert hr_activity["created_at"]

    manager_list = client.get(scoped_url, headers=manager_headers)
    assert manager_list.status_code == 200
    assert [item["id"] for item in manager_list.json()] == [hr_activity["id"]]

    manager_response = client.post(
        scoped_url,
        headers=manager_headers,
        json={
            "type": "Manager note",
            "content": "The department manager would like to schedule an interview.",
        },
    )
    assert manager_response.status_code == 201
    manager_activity = manager_response.json()
    assert manager_activity["author_name"] == "Manager"
    assert manager_activity["author_role"] == "manager"
    assert manager_activity["author_department_id"] == ids["engineering"]
    assert manager_activity["author_department_name"] == "Engineering"

    status_escalation = client.post(
        scoped_url,
        headers=manager_headers,
        json={
            "type": "Manager note",
            "content": "This message must not change global candidate status.",
            "next_status": "archived",
        },
    )
    assert status_escalation.status_code == 403

    admin_response = client.post(
        unscoped_url,
        headers=admin_headers,
        json={"type": "Admin note", "content": "Global recruiting note."},
    )
    assert admin_response.status_code == 201
    admin_activity = admin_response.json()
    assert admin_activity["author_name"] == "Admin"
    assert admin_activity["author_role"] == "admin"
    assert admin_activity["author_department_id"] is None
    assert admin_activity["author_department_name"] is None
    assert client.get(unscoped_url, headers=hr_headers).status_code == 200

    for method, url in [
        ("get", scoped_url),
        ("post", scoped_url),
    ]:
        kwargs = {"headers": sales_manager_headers}
        if method == "post":
            kwargs["json"] = {"type": "Forbidden", "content": "Must not persist."}
        response = getattr(client, method)(url, **kwargs)
        assert response.status_code == 403
        assert response.json() == {"detail": "Outside candidate scope"}

    unknown_url = "/api/v1/candidates/999999/activities"
    cross_department = client.get(scoped_url, headers=sales_manager_headers)
    unknown_candidate = client.get(unknown_url, headers=sales_manager_headers)
    assert cross_department.status_code == unknown_candidate.status_code == 403
    assert cross_department.json() == unknown_candidate.json()
    assert client.get(scoped_url, headers=it_headers).status_code == 403
    assert client.post(
        scoped_url,
        headers=it_headers,
        json={"type": "IT note", "content": "Must not persist."},
    ).status_code == 403

    with testing_session() as db:
        legacy = CandidateActivity(
            candidate_id=ids["scoped_candidate"],
            user_id=None,
            type="legacy",
            content="Activity created before author attribution was available.",
            happened_at=datetime(2025, 1, 1, tzinfo=UTC),
        )
        db.add(legacy)
        db.commit()
        legacy_id = legacy.id

    hr_list = client.get(scoped_url, headers=hr_headers)
    assert hr_list.status_code == 200
    activities = {item["id"]: item for item in hr_list.json()}
    assert {hr_activity["id"], manager_activity["id"], legacy_id} <= activities.keys()
    assert activities[legacy_id]["user_id"] is None
    assert activities[legacy_id]["author_name"] is None
    assert activities[legacy_id]["author_role"] is None
    assert activities[legacy_id]["author_department_id"] is None
    assert activities[legacy_id]["author_department_name"] is None

    with testing_session() as db:
        scoped_candidate = db.get(Candidate, ids["scoped_candidate"])
        assert scoped_candidate is not None
        assert scoped_candidate.status == "contacted"
        persisted_activity_ids = set(
            db.scalars(
                select(CandidateActivity.id).where(
                    CandidateActivity.candidate_id == ids["scoped_candidate"]
                )
            )
        )
        assert persisted_activity_ids == {
            hr_activity["id"],
            manager_activity["id"],
            legacy_id,
        }
        audits = list(
            db.scalars(
                select(AuditLog)
                .where(AuditLog.action == "candidate.activity.create")
                .order_by(AuditLog.id)
            )
        )
        assert [audit.resource_id for audit in audits] == [
            str(hr_activity["id"]),
            str(manager_activity["id"]),
            str(admin_activity["id"]),
        ]
        manager_audit = next(
            audit for audit in audits if audit.resource_id == str(manager_activity["id"])
        )
        assert manager_audit.department_id == ids["engineering"]
        assert manager_audit.details == {
            "candidate_id": ids["scoped_candidate"],
            "activity_type": "Manager note",
            "candidate_status_changed": False,
        }
        assert manager_audit.ip_address is not None
        assert manager_audit.user_agent


def test_department_workspace_contains_only_own_jobs_and_actual_applicants(
    secured_app_client,
) -> None:
    client, testing_session, ids = secured_app_client
    manager_headers = login_headers(client, "manager")
    response = client.get("/api/v1/department/workspace", headers=manager_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["department_id"] == ids["engineering"]
    assert body["total_jobs"] == 1
    assert body["total_applications"] == 1
    assert [item["requisition"]["id"] for item in body["jobs"]] == [
        ids["engineering_job"]
    ]
    assert [
        item["candidate"]["id"] for item in body["jobs"][0]["applicants"]
    ] == [ids["scoped_candidate"]]
    workspace_candidate = body["jobs"][0]["applicants"][0]["candidate"]
    assert workspace_candidate["email"] == "e***@app.test"
    assert workspace_candidate["phone"] == "*******789"
    assert workspace_candidate["city"] is None
    assert client.get(
        "/api/v1/department/workspace", headers=login_headers(client, "hr")
    ).status_code == 403

    payload = {
        "title": "Department Platform Engineer",
        "employment_type": "full_time",
        "work_city": "Taipei",
        "jd": "Build the department platform",
        "summary": "Created directly by the department manager",
        "skills": ["Python", "SQL", "Python"],
        "salary_min": 70000,
        "salary_max": 100000,
        "salary_type": "monthly",
        "headcount": 2,
    }
    injected_scope = client.post(
        "/api/v1/department/requisitions",
        headers=manager_headers,
        json={**payload, "department_id": ids["sales"]},
    )
    assert injected_scope.status_code == 422

    created_response = client.post(
        "/api/v1/department/requisitions",
        headers=manager_headers,
        json=payload,
    )
    assert created_response.status_code == 201
    created = created_response.json()
    assert created["req_no"].startswith(f"D{ids['engineering']:02d}-")
    assert created["department_id"] == ids["engineering"]
    assert created["department_name"] == "Engineering"
    assert created["requested_by"] is not None
    assert created["status"] == "submitted"
    assert created["skills"] == ["Python", "SQL"]

    refreshed = client.get("/api/v1/department/workspace", headers=manager_headers)
    assert refreshed.status_code == 200
    assert refreshed.json()["total_jobs"] == 2
    assert created["id"] in {
        item["requisition"]["id"] for item in refreshed.json()["jobs"]
    }

    hr_jobs = client.get(
        "/api/v1/requisitions", headers=login_headers(client, "hr")
    )
    assert hr_jobs.status_code == 200
    assert created["id"] in {item["id"] for item in hr_jobs.json()}

    it_preview = client.get(
        f"/api/v1/admin/database/tables/job_requisitions/rows?search={created['req_no']}",
        headers=login_headers(client, "it"),
    )
    assert it_preview.status_code == 200
    assert it_preview.json()["total"] == 1
    assert it_preview.json()["rows"][0]["title"] == payload["title"]

    with testing_session() as db:
        requisition = db.get(JobRequisition, created["id"])
        manager = db.scalar(select(User).where(User.username == "manager"))
        assert requisition is not None
        assert manager is not None
        assert requisition.requested_by == manager.id
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "department.requisition.create",
                AuditLog.resource_id == str(created["id"]),
            )
        )
        assert audit is not None
        assert audit.department_id == ids["engineering"]


def test_department_manager_updates_and_deletes_only_own_requisitions(
    secured_app_client,
) -> None:
    client, testing_session, ids = secured_app_client
    manager_headers = login_headers(client, "manager")
    payload = {
        "title": "Senior Backend Engineer",
        "employment_type": "full_time",
        "work_city": "New Taipei",
        "jd": "Own and improve the backend platform",
        "summary": "Updated by the department manager",
        "skills": [" Python ", "", "SQL", "Python"],
        "salary_min": 90000,
        "salary_max": 130000,
        "salary_type": "monthly",
        "headcount": 3,
    }

    with testing_session() as db:
        original = db.get(JobRequisition, ids["engineering_job"])
        assert original is not None
        immutable_values = {
            "req_no": original.req_no,
            "department_id": original.department_id,
            "requested_by": original.requested_by,
            "status": original.status,
        }

    for field, value in {
        "req_no": "INJECTED-REQ-NO",
        "department_id": ids["sales"],
        "requested_by": 99999,
        "status": "approved",
    }.items():
        response = client.put(
            f"/api/v1/department/requisitions/{ids['engineering_job']}",
            headers=manager_headers,
            json={**payload, field: value},
        )
        assert response.status_code == 422, (field, response.text)

    invalid_salary = client.put(
        f"/api/v1/department/requisitions/{ids['engineering_job']}",
        headers=manager_headers,
        json={**payload, "salary_min": 140000, "salary_max": 130000},
    )
    assert invalid_salary.status_code == 422

    assert client.put(
        f"/api/v1/department/requisitions/{ids['sales_job']}",
        headers=manager_headers,
        json=payload,
    ).status_code == 403
    hr_headers = login_headers(client, "hr")
    assert client.put(
        f"/api/v1/department/requisitions/{ids['engineering_job']}",
        headers=hr_headers,
        json=payload,
    ).status_code == 403

    updated_response = client.put(
        f"/api/v1/department/requisitions/{ids['engineering_job']}",
        headers=manager_headers,
        json=payload,
    )
    assert updated_response.status_code == 200
    updated = updated_response.json()
    assert updated["title"] == payload["title"]
    assert updated["skills"] == ["Python", "SQL"]
    assert updated["salary_min"] == payload["salary_min"]
    assert updated["salary_max"] == payload["salary_max"]
    for field, value in immutable_values.items():
        assert updated[field] == value

    with testing_session() as db:
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "department.requisition.update",
                AuditLog.resource_id == str(ids["engineering_job"]),
            )
        )
        assert audit is not None
        assert audit.department_id == ids["engineering"]
        assert audit.ip_address == "testclient"

    blocked_delete = client.delete(
        f"/api/v1/department/requisitions/{ids['engineering_job']}",
        headers=manager_headers,
    )
    assert blocked_delete.status_code == 409
    with testing_session() as db:
        assert db.get(JobRequisition, ids["engineering_job"]) is not None

    assert client.delete(
        f"/api/v1/department/requisitions/{ids['sales_job']}",
        headers=manager_headers,
    ).status_code == 403
    assert client.delete(
        f"/api/v1/department/requisitions/{ids['engineering_job']}",
        headers=hr_headers,
    ).status_code == 403

    created_response = client.post(
        "/api/v1/department/requisitions",
        headers=manager_headers,
        json={**payload, "title": "Temporary Role Without Applications"},
    )
    assert created_response.status_code == 201
    removable_id = created_response.json()["id"]
    with testing_session() as db:
        match = MatchResult(
            requisition_id=removable_id,
            candidate_id=ids["candidate"],
            gate_passed=True,
            total_score=88,
            score_breakdown={"skills": {"score": 0.88}},
            status="recommended",
        )
        db.add(match)
        db.commit()
        match_id = match.id

    deleted_response = client.delete(
        f"/api/v1/department/requisitions/{removable_id}",
        headers=manager_headers,
    )
    assert deleted_response.status_code == 204
    assert deleted_response.content == b""
    with testing_session() as db:
        assert db.get(JobRequisition, removable_id) is None
        assert db.get(MatchResult, match_id) is None
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "department.requisition.delete",
                AuditLog.resource_id == str(removable_id),
            )
        )
        assert audit is not None
        assert audit.department_id == ids["engineering"]
        assert audit.details == {
            "req_no": created_response.json()["req_no"],
            "title": "Temporary Role Without Applications",
        }


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
