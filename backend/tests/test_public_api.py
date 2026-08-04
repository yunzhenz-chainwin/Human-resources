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
from app.models import ConsentNotice, Department, JobRequisition

CONSENT_FIELDS = {"consent_notice_id": 1, "consent_notice_version": 1}


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
        db.add(
            ConsentNotice(
                version=1,
                title="人才招募個資告知暨同意書",
                body="TalentHub 將在招募與人才媒合目的內使用你提供的資料。",
                purpose_code="recruitment",
                is_active=True,
            )
        )
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
                JobRequisition(
                    req_no="DEMO-PUBLIC-001",
                    title="Demo job must stay private",
                    department_id=department.id,
                    employment_type="full_time",
                    work_city="Taipei",
                    jd="Demo only",
                    status="sourcing",
                    published_at=datetime.now(UTC),
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


def test_public_active_consent_notice_exposes_only_candidate_facing_fields(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/public/consent-notices/active")
    assert response.status_code == 200
    assert response.json() == {
        "id": 1,
        "version": 1,
        "title": "人才招募個資告知暨同意書",
        "body": "TalentHub 將在招募與人才媒合目的內使用你提供的資料。",
        "purpose_code": "recruitment",
    }


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
        **CONSENT_FIELDS,
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
    assert candidates[0]["retention_until"] is not None
    assert len(resumes) == 1
    assert resumes[0]["parse_status"] == "pending"
    consents = client.get(
        f"/api/v1/candidates/{candidates[0]['id']}/consents"
    ).json()
    assert len(consents) == 1
    assert consents[0]["notice_id"] == 1
    assert consents[0]["notice_version"] == 1
    assert consents[0]["channel"] == "public_form"


def test_talent_profile_can_be_created_without_resume(client: TestClient) -> None:
    response = client.post(
        "/api/v1/public/applications",
        data={
            "name": "Lightweight Talent",
            "email": "light@example.com",
            "city": "台北市",
            "current_title": "軟體／資訊",
            "total_years": "2",
            "skills": "軟體開發",
            "consent": "true",
            **CONSENT_FIELDS,
        },
    )
    assert response.status_code == 201
    assert response.json()["resume_id"] is None
    assert response.json()["candidate_id"] is not None
    assert response.json()["status"] == "created"

    candidates = client.get("/api/v1/candidates").json()
    assert len(candidates) == 1
    assert candidates[0]["name"] == "Lightweight Talent"
    assert candidates[0]["city"] == "台北市"
    assert client.get("/api/v1/resumes").json() == []


def test_job_application_can_be_submitted_without_resume(client: TestClient) -> None:
    response = client.post(
        "/api/v1/public/applications",
        data={
            "job_id": "1",
            "name": "No Resume Applicant",
            "phone": "0912345678",
            "skills": "資料分析／AI",
            "consent": "true",
            **CONSENT_FIELDS,
        },
    )
    assert response.status_code == 201
    assert response.json()["application_id"] is not None
    assert response.json()["duplicate"] is False
    assert client.get("/api/v1/resumes").json() == []


def test_duplicate_application_still_persists_a_later_resume(client: TestClient) -> None:
    data = {
        "job_id": "1",
        "name": "Later Resume Applicant",
        "email": "later-resume@example.com",
        "consent": "true",
        **CONSENT_FIELDS,
    }
    first = client.post("/api/v1/public/applications", data=data)
    assert first.status_code == 201
    assert first.json()["duplicate"] is False

    second = client.post(
        "/api/v1/public/applications",
        data=data,
        files={"resume": ("later.pdf", b"%PDF-1.4 later", "application/pdf")},
    )
    assert second.status_code == 201
    assert second.json()["application_id"] == first.json()["application_id"]
    assert second.json()["duplicate"] is True
    resumes = client.get("/api/v1/resumes").json()
    assert len(resumes) == 1
    assert resumes[0]["candidate_id"] is not None


def test_public_resubmission_cannot_reactivate_withdrawn_consent(
    client: TestClient,
) -> None:
    data = {
        "job_id": "1",
        "name": "Returning Applicant",
        "email": "returning@example.com",
        "consent": "true",
        **CONSENT_FIELDS,
    }
    first = client.post("/api/v1/public/applications", data=data)
    assert first.status_code == 201

    candidate_id = client.get("/api/v1/candidates").json()[0]["id"]
    initial_consents = client.get(
        f"/api/v1/candidates/{candidate_id}/consents"
    ).json()
    assert len(initial_consents) == 1

    withdrawn = client.post(
        "/api/v1/consent/candidate-consents/"
        f"{initial_consents[0]['id']}/withdraw"
    )
    assert withdrawn.status_code == 200

    repeated = client.post("/api/v1/public/applications", data=data)
    assert repeated.status_code == 409

    stored_consents = client.get(
        f"/api/v1/candidates/{candidate_id}/consents"
    ).json()
    assert len(stored_consents) == 1
    assert stored_consents[0]["withdrawn_at"] is not None


def test_existing_candidate_cannot_accept_new_notice_anonymously(
    client: TestClient,
) -> None:
    initial_data = {
        "job_id": "1",
        "name": "Existing Applicant",
        "email": "existing@example.com",
        "consent": "true",
        **CONSENT_FIELDS,
    }
    assert client.post(
        "/api/v1/public/applications",
        data=initial_data,
    ).status_code == 201
    candidate_id = client.get("/api/v1/candidates").json()[0]["id"]

    published = client.post(
        "/api/v1/consent/notices",
        json={
            "title": "人才招募個資告知暨同意書 v2",
            "body": "更新後的招募與人才媒合個資告知事項。",
            "purpose_code": "recruitment",
            "activate": True,
        },
    )
    assert published.status_code == 201, published.text

    forged = client.post(
        "/api/v1/public/applications",
        data={
            **initial_data,
            "consent_notice_id": published.json()["id"],
            "consent_notice_version": published.json()["version"],
        },
    )
    assert forged.status_code == 409

    consents = client.get(
        f"/api/v1/candidates/{candidate_id}/consents"
    ).json()
    assert len(consents) == 1
    assert consents[0]["notice_version"] == 1


def test_application_rejects_draft_job_and_missing_consent(client: TestClient) -> None:
    base = {
        "name": "Test",
        "email": "test@example.com",
        "consent": True,
        **CONSENT_FIELDS,
    }
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


def test_public_submission_rejects_a_stale_or_unbound_notice(client: TestClient) -> None:
    base = {
        "requisition_id": 1,
        "name": "Stale Notice",
        "email": "stale@example.com",
        "consent": True,
    }
    unbound = client.post("/api/v1/public/applications/json", json=base)
    assert unbound.status_code == 422

    stale = client.post(
        "/api/v1/public/applications/json",
        json={
            **base,
            "consent_notice_id": 1,
            "consent_notice_version": 999,
        },
    )
    assert stale.status_code == 409
    assert client.get("/api/v1/candidates").json() == []


def test_resume_upload_rejects_invalid_type_and_oversize(client: TestClient) -> None:
    data = {
        "job_id": "1",
        "name": "Test",
        "email": "test@example.com",
        "consent": "true",
        **CONSENT_FIELDS,
    }
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
        json={"current_title": "Senior Engineer", "source": "generic", "status": "contacted"},
    )
    assert updated.status_code == 200
    assert updated.json()["current_title"] == "Senior Engineer"
    assert updated.json()["source"] == "generic"
    assert client.patch(
        f"/api/v1/candidates/{candidate_id}",
        json={"source": "untrusted-source"},
    ).status_code == 422

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
