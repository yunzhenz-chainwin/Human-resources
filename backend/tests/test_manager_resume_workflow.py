import shutil
from collections.abc import Generator
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models import (
    Department,
    JobApplication,
    JobRequisition,
    ResumeFile,
    User,
)


def _docx_bytes(text: str) -> bytes:
    document = Document()
    for line in text.splitlines():
        document.add_paragraph(line)
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


def _resume_file(content: bytes, filename: str = "candidate.docx") -> list[tuple]:
    return [
        (
            "files",
            (
                filename,
                content,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        )
    ]


@pytest.fixture()
def manager_resume_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[TestClient, sessionmaker, dict[str, int], dict], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    settings = get_settings()
    storage_root = Path("storage") / f"manager-resume-test-{uuid4().hex}"
    original_settings = {
        "resume_storage_path": settings.resume_storage_path,
        "resume_quarantine_path": settings.resume_quarantine_path,
        "resume_storage_provider": settings.resume_storage_provider,
        "resume_scanner": settings.resume_scanner,
        "resume_scan_policy": settings.resume_scan_policy,
        "bootstrap_admin_username": settings.bootstrap_admin_username,
        "bootstrap_admin_email": settings.bootstrap_admin_email,
        "bootstrap_admin_password": settings.bootstrap_admin_password,
    }
    settings.resume_storage_path = str(storage_root / "resumes")
    settings.resume_quarantine_path = str(storage_root / "quarantine")
    settings.resume_storage_provider = "local"
    settings.resume_scanner = "none"
    settings.resume_scan_policy = "allow_unavailable"
    settings.bootstrap_admin_username = None
    settings.bootstrap_admin_email = None
    settings.bootstrap_admin_password = None

    with testing_session() as db:
        engineering = Department(name="Engineering")
        sales = Department(name="Sales")
        db.add_all([engineering, sales])
        db.flush()
        engineering_manager = User(
            username="engineering-manager",
            email="engineering-manager@example.test",
            password_hash="unused",
            display_name="Engineering Manager",
            role="manager",
            department_id=engineering.id,
        )
        sales_manager = User(
            username="sales-manager",
            email="sales-manager@example.test",
            password_hash="unused",
            display_name="Sales Manager",
            role="manager",
            department_id=sales.id,
        )
        hr_user = User(
            username="resume-hr",
            email="resume-hr@example.test",
            password_hash="unused",
            display_name="Resume HR",
            role="hr",
        )
        db.add_all([engineering_manager, sales_manager, hr_user])
        db.flush()
        engineering_job = JobRequisition(
            req_no="MGR-ENG-001",
            title="Platform Engineer",
            department_id=engineering.id,
            requested_by=engineering_manager.id,
            employment_type="full_time",
            work_city="Taipei",
            jd="Build the platform",
            status="submitted",
        )
        sales_job = JobRequisition(
            req_no="MGR-SALES-001",
            title="Account Executive",
            department_id=sales.id,
            requested_by=sales_manager.id,
            employment_type="full_time",
            work_city="Taipei",
            jd="Grow accounts",
            status="submitted",
        )
        db.add_all([engineering_job, sales_job])
        db.commit()
        ids = {
            "engineering_manager": engineering_manager.id,
            "sales_manager": sales_manager.id,
            "hr": hr_user.id,
            "engineering_job": engineering_job.id,
            "sales_job": sales_job.id,
        }

    current_user = {
        "value": SimpleNamespace(
            id=ids["engineering_manager"],
            role="manager",
            department_id=engineering.id,
            is_active=True,
        )
    }

    def override_db():
        with testing_session() as db:
            yield db

    def override_user():
        return current_user["value"]

    main_module.app.dependency_overrides[get_db] = override_db
    main_module.app.dependency_overrides[get_current_user] = override_user
    monkeypatch.setattr(main_module, "SessionLocal", testing_session)
    try:
        with TestClient(main_module.app) as client:
            yield client, testing_session, ids, current_user
    finally:
        main_module.app.dependency_overrides.clear()
        for key, value in original_settings.items():
            setattr(settings, key, value)
        Base.metadata.drop_all(engine)
        shutil.rmtree(storage_root, ignore_errors=True)


def _as_user(current_user: dict, user_id: int, role: str, department_id: int | None) -> None:
    current_user["value"] = SimpleNamespace(
        id=user_id,
        role=role,
        department_id=department_id,
        is_active=True,
    )


def test_manager_upload_scope_confirmation_and_department_workspace(
    manager_resume_client,
) -> None:
    client, testing_session, ids, current_user = manager_resume_client
    with testing_session() as db:
        engineering_department_id = db.scalar(
            select(JobRequisition.department_id).where(
                JobRequisition.id == ids["engineering_job"]
            )
        )
        sales_department_id = db.scalar(
            select(JobRequisition.department_id).where(
                JobRequisition.id == ids["sales_job"]
            )
        )

    content = _docx_bytes(
        "Manager Candidate\nEmail: manager-candidate@example.test\n"
        "Phone: 0912-345-678\nSkills: Python, SQL"
    )
    missing_target = client.post(
        "/api/v1/resumes/upload",
        data={"source_platform": "generic"},
        files=_resume_file(content),
    )
    assert missing_target.status_code == 422
    assert missing_target.json()["detail"] == "requisition_id is required for manager uploads"

    other_department_target = client.post(
        "/api/v1/resumes/upload",
        data={
            "source_platform": "generic",
            "requisition_id": str(ids["sales_job"]),
        },
        files=_resume_file(content),
    )
    assert other_department_target.status_code == 403

    uploaded = client.post(
        "/api/v1/resumes/upload",
        data={
            "source_platform": "generic",
            "requisition_id": str(ids["engineering_job"]),
        },
        files=_resume_file(content),
    )
    assert uploaded.status_code == 201
    uploaded_item = uploaded.json()[0]
    resume_id = uploaded_item["id"]
    assert uploaded_item["target_requisition_id"] == ids["engineering_job"]
    assert uploaded_item["duplicate"] is False

    with testing_session() as db:
        resume = db.get(ResumeFile, resume_id)
        assert resume.target_requisition_id == ids["engineering_job"]
        assert resume.uploaded_by == ids["engineering_manager"]

    manager_list = client.get("/api/v1/resumes")
    assert manager_list.status_code == 403
    assert client.get(f"/api/v1/resumes/{resume_id}").status_code == 403
    assert client.get(f"/api/v1/resumes/{resume_id}/file").status_code == 403
    assert client.get(f"/api/v1/resumes/{resume_id}/preview").status_code == 403
    assert client.post(f"/api/v1/resumes/{resume_id}/reparse").status_code == 403

    _as_user(
        current_user,
        ids["sales_manager"],
        "manager",
        sales_department_id,
    )
    assert client.get("/api/v1/resumes").status_code == 403
    assert client.get(f"/api/v1/resumes/{resume_id}").status_code == 403
    assert (
        client.put(
            f"/api/v1/resumes/{resume_id}/parsed",
            json={"parsed_payload": {"name": "Blocked Change"}},
        ).status_code
        == 403
    )
    assert client.post(f"/api/v1/resumes/{resume_id}/reparse").status_code == 403
    assert (
        client.put(
            f"/api/v1/resumes/{resume_id}/source",
            json={"source_platform": "direct"},
        ).status_code
        == 403
    )
    assert client.post(f"/api/v1/resumes/{resume_id}/confirm", json={}).status_code == 403

    cross_department_duplicate = client.post(
        "/api/v1/resumes/upload",
        data={
            "source_platform": "generic",
            "requisition_id": str(ids["sales_job"]),
        },
        files=_resume_file(content),
    )
    assert cross_department_duplicate.status_code == 403
    assert cross_department_duplicate.json() == {"detail": "Outside resume scope"}
    assert str(resume_id) not in cross_department_duplicate.text

    _as_user(
        current_user,
        ids["engineering_manager"],
        "manager",
        engineering_department_id,
    )
    same_department_duplicate = client.post(
        "/api/v1/resumes/upload",
        data={
            "source_platform": "generic",
            "requisition_id": str(ids["engineering_job"]),
        },
        files=_resume_file(content),
    )
    assert same_department_duplicate.status_code == 201
    duplicate_item = same_department_duplicate.json()[0]
    assert duplicate_item["id"] == resume_id
    assert duplicate_item["target_requisition_id"] == ids["engineering_job"]
    assert duplicate_item["duplicate"] is True

    assert client.put(
        f"/api/v1/resumes/{resume_id}/parsed",
        json={"parsed_payload": {"name": "Manager must not inspect this"}},
    ).status_code == 403
    assert client.put(
        f"/api/v1/resumes/{resume_id}/source",
        json={"source_platform": "direct"},
    ).status_code == 403
    assert client.post(f"/api/v1/resumes/{resume_id}/confirm", json={}).status_code == 403

    _as_user(current_user, ids["hr"], "hr", None)
    hr_list = client.get("/api/v1/resumes")
    assert hr_list.status_code == 200
    assert [item["id"] for item in hr_list.json()] == [resume_id]
    assert client.get(f"/api/v1/resumes/{resume_id}").status_code == 200
    assert client.post(f"/api/v1/resumes/{resume_id}/reparse").status_code == 200

    reviewed = client.put(
        f"/api/v1/resumes/{resume_id}/parsed",
        json={
            "parsed_payload": {
                "name": "Manager Candidate",
                "email": "manager-candidate@example.test",
                "phone": "0912345678",
                "city": "Taipei",
                "current_title": "Software Engineer",
                "total_years": 4,
                "skills": ["Python", "SQL"],
            }
        },
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["target_requisition_id"] == ids["engineering_job"]
    assert (
        client.put(
            f"/api/v1/resumes/{resume_id}/source",
            json={"source_platform": "direct"},
        ).status_code
        == 200
    )

    confirmed = client.post(f"/api/v1/resumes/{resume_id}/confirm", json={})
    assert confirmed.status_code == 200
    candidate_id = confirmed.json()["candidate_id"]
    with testing_session() as db:
        applications = list(
            db.scalars(
                select(JobApplication).where(
                    JobApplication.requisition_id == ids["engineering_job"],
                    JobApplication.candidate_id == candidate_id,
                )
            ).all()
        )
        assert len(applications) == 1
        assert applications[0].resume_id == resume_id
        assert applications[0].status == "submitted"
        assert applications[0].source == "manager_upload"

    _as_user(
        current_user,
        ids["engineering_manager"],
        "manager",
        engineering_department_id,
    )
    workspace = client.get("/api/v1/department/workspace")
    assert workspace.status_code == 200
    matching_job = next(
        job
        for job in workspace.json()["jobs"]
        if job["requisition"]["id"] == ids["engineering_job"]
    )
    applicant = matching_job["applicants"][0]["candidate"]
    assert applicant["id"] == candidate_id
    assert applicant["email"] == "m***@example.test"
    assert applicant["phone"] == "*******678"
    assert applicant["city"] is None

    _as_user(current_user, ids["hr"], "hr", None)
    repeated = client.post(f"/api/v1/resumes/{resume_id}/confirm", json={})
    assert repeated.status_code == 200
    assert repeated.json()["created"] is False
    with testing_session() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(JobApplication)
                .where(
                    JobApplication.requisition_id == ids["engineering_job"],
                    JobApplication.candidate_id == candidate_id,
                )
            )
            == 1
        )


def test_global_hr_upload_without_target_keeps_legacy_workflow(
    manager_resume_client,
) -> None:
    client, testing_session, ids, current_user = manager_resume_client
    _as_user(current_user, ids["hr"], "hr", None)
    content = _docx_bytes(
        "Legacy HR Candidate\nEmail: legacy-hr@example.test\nPhone: 0988-111-222"
    )
    uploaded = client.post(
        "/api/v1/resumes/upload",
        data={"source_platform": "generic"},
        files=_resume_file(content, "legacy.docx"),
    )
    assert uploaded.status_code == 201
    resume_id = uploaded.json()[0]["id"]
    assert uploaded.json()[0]["target_requisition_id"] is None
    assert (
        client.put(
            f"/api/v1/resumes/{resume_id}/parsed",
            json={
                "parsed_payload": {
                    "name": "Legacy HR Candidate",
                    "email": "legacy-hr@example.test",
                }
            },
        ).status_code
        == 200
    )
    confirmed = client.post(f"/api/v1/resumes/{resume_id}/confirm", json={})
    assert confirmed.status_code == 200
    with testing_session() as db:
        assert db.scalar(select(func.count()).select_from(JobApplication)) == 0
        resume = db.get(ResumeFile, resume_id)
        assert resume.uploaded_by == ids["hr"]
        assert resume.target_requisition_id is None
