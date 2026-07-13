import shutil
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.dependencies.auth import audit_pii_read, get_current_user
from app.main import app
from app.models import Department, JobRequisition


@pytest.fixture()
def client() -> TestClient:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    test_storage = Path("storage") / f"test-{uuid4().hex}"
    get_settings().resume_storage_path = str(test_storage)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    with testing_session() as db:
        department = Department(name="Engineering")
        db.add(department)
        db.flush()
        db.add_all(
            [
                JobRequisition(
                    req_no="R2026-0001",
                    title="Backend Engineer",
                    department_id=department.id,
                    employment_type="full_time",
                    work_city="Taipei",
                    jd="Build reliable APIs",
                    summary="Talent platform",
                    skills=["Python", "FastAPI"],
                    status="sourcing",
                    published_at=datetime.now(UTC),
                ),
                JobRequisition(
                    req_no="R2026-0002",
                    title="Draft Job",
                    department_id=department.id,
                    employment_type="full_time",
                    work_city="Taipei",
                    jd="Draft",
                    status="draft",
                ),
            ]
        )
        db.commit()

    def override_db():
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1, role="admin", department_id=None, is_active=True
    )
    app.dependency_overrides[audit_pii_read] = lambda: None
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    shutil.rmtree(test_storage, ignore_errors=True)


def test_public_jobs_only_returns_published_states(client: TestClient) -> None:
    response = client.get("/api/v1/public/jobs")
    assert response.status_code == 200
    jobs = response.json()
    assert len(jobs) == 1
    assert jobs[0]["req_no"] == "R2026-0001"
    assert jobs[0]["department"] == "Engineering"
    assert jobs[0]["skills"] == ["Python", "FastAPI"]


def test_multipart_application_persists_and_deduplicates(client: TestClient) -> None:
    data = {
        "job_id": "1",
        "name": "Applicant",
        "email": " USER@Example.com ",
        "phone": "+886 912-345-678",
        "linkedin_url": "https://linkedin.com/in/test",
        "portfolio_url": "https://example.com",
        "cover_letter": "Hello",
        "consent": "true",
    }
    upload = {"resume": ("resume.pdf", b"%PDF-1.4 test", "application/pdf")}
    first = client.post("/api/v1/public/applications", data=data, files=upload)
    assert first.status_code == 201
    assert first.json()["duplicate"] is False
    second = client.post("/api/v1/public/applications", data=data, files=upload)
    assert second.status_code == 201
    assert second.json() == {**first.json(), "duplicate": True}

    candidates = client.get("/api/v1/candidates").json()
    resumes = client.get("/api/v1/resumes").json()
    assert len(candidates) == 1
    assert candidates[0]["email"] == "USER@Example.com"
    assert len(resumes) == 1
    assert resumes[0]["parse_status"] == "pending"


def test_application_rejects_draft_job_and_missing_consent(client: TestClient) -> None:
    base = {"name": "Test", "email": "test@example.com", "consent": True}
    assert (
        client.post(
            "/api/v1/public/applications/json", json={**base, "requisition_id": 2}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/public/applications/json",
            json={**base, "requisition_id": 1, "consent": False},
        ).status_code
        == 422
    )


def test_resume_upload_rejects_invalid_type_and_oversize(client: TestClient) -> None:
    data = {"job_id": "1", "name": "Test", "email": "test@example.com", "consent": "true"}
    invalid = client.post(
        "/api/v1/public/applications",
        data=data,
        files={"resume": ("resume.exe", b"bad", "application/octet-stream")},
    )
    assert invalid.status_code == 415
    spoofed = client.post(
        "/api/v1/public/applications",
        data=data,
        files={"resume": ("resume.pdf", b"not a pdf", "application/pdf")},
    )
    assert spoofed.status_code == 415
    oversized = client.post(
        "/api/v1/public/applications",
        data=data,
        files={"resume": ("resume.pdf", b"x" * (10 * 1024 * 1024 + 1), "application/pdf")},
    )
    assert oversized.status_code == 413


def test_hr_candidate_requisition_and_activity_updates_persist(client: TestClient) -> None:
    created = client.post(
        "/api/v1/candidates",
        json={"name": "Candidate", "email": "candidate@example.com", "source": "manual"},
    )
    assert created.status_code == 201
    candidate_id = created.json()["id"]
    updated = client.patch(
        f"/api/v1/candidates/{candidate_id}",
        json={"current_title": "Senior Engineer", "status": "contacted"},
    )
    assert updated.status_code == 200
    assert updated.json()["current_title"] == "Senior Engineer"

    activity = client.post(
        f"/api/v1/candidates/{candidate_id}/activities",
        json={
            "activity_type": "call",
            "note": "Interview scheduled",
            "next_status": "interviewing",
        },
    )
    assert activity.status_code == 201
    assert activity.json()["type"] == "call"
    assert client.get(f"/api/v1/candidates/{candidate_id}").json()["status"] == "interviewing"

    requisition = client.patch(
        "/api/v1/requisitions/1", json={"title": "Senior Backend Engineer", "salary_min": 70000}
    )
    assert requisition.status_code == 200
    assert requisition.json()["title"] == "Senior Backend Engineer"
