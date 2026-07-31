from __future__ import annotations

import hashlib
import json
from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fpdf import FPDF
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import deidentified_resumes as routes_module
from app.db.base import Base
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models import (
    AuditLog,
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
from app.models.deidentified_resume import DeidentifiedResumeDocument
from app.services import deidentification as service_module
from app.services.file_scanning import ScanResult, ScanStatus
from app.services.storage import LocalStorageProvider


def _make_pdf(text: str) -> bytes:
    """Build a small, real PDF whose text pypdf can extract for PII scanning."""

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    for line in text.splitlines() or [""]:
        pdf.multi_cell(0, 8, line, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


# A properly redacted de-identified PDF: no name/email/phone/id numbers.
CLEAN_UPLOAD_BYTES = _make_pdf(
    "De-identified candidate profile\nRole Backend Engineer\nSkills Python SQL\nYears five"
)
# A file the HR user *thinks* is redacted but still leaks contact details.
LEAKY_UPLOAD_BYTES = _make_pdf(
    "Name Sensitive Person\n"
    "Email sensitive.person@example.test\n"
    "Phone 0912-345-678"
)


class _CleanScanner:
    def scan(self, path: Path) -> ScanResult:
        return ScanResult(ScanStatus.CLEAN)


class _InfectedScanner:
    def scan(self, path: Path) -> ScanResult:
        return ScanResult(ScanStatus.INFECTED, "eicar-test")


class FailAfterPutStorage(LocalStorageProvider):
    def put_file(self, source: Path, key: str, content_type: str) -> None:
        super().put_file(source, key, content_type)
        if key.startswith("deidentified-resumes/"):
            raise RuntimeError("simulated object-store failure")


@pytest.fixture()
def deidentified_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[
    tuple[TestClient, sessionmaker, dict[str, int], dict, LocalStorageProvider],
    None,
    None,
]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    storage = LocalStorageProvider(tmp_path / "objects")
    quarantine = tmp_path / "quarantine"
    monkeypatch.setattr(routes_module, "get_storage_provider", lambda: storage)
    monkeypatch.setattr(
        service_module,
        "get_settings",
        lambda: SimpleNamespace(
            resume_quarantine_path=str(quarantine),
            resume_max_bytes=10_000_000,
        ),
    )
    # The manual-upload path validates content with the shared resume pipeline;
    # inject a deterministic clean scanner so tests never touch a real ClamAV.
    monkeypatch.setattr(service_module, "get_file_scanner", lambda settings=None: _CleanScanner())

    source_bytes = b"%PDF-1.4\nprivate original bytes that must never change\n%%EOF"
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(source_bytes)
    storage.put_file(source_path, "resumes/source.pdf", "application/pdf")
    source_hash = hashlib.sha256(source_bytes).hexdigest()

    with testing_session() as db:
        engineering = Department(name="Engineering")
        sales = Department(name="Sales")
        db.add_all([engineering, sales])
        db.flush()
        hr = User(
            username="deid-hr",
            email="deid-hr@example.test",
            password_hash="unused",
            display_name="De-identification HR",
            role="hr",
        )
        engineering_manager = User(
            username="deid-engineering-manager",
            email="deid-engineering-manager@example.test",
            password_hash="unused",
            display_name="Engineering Manager",
            role="manager",
            department_id=engineering.id,
        )
        sales_manager = User(
            username="deid-sales-manager",
            email="deid-sales-manager@example.test",
            password_hash="unused",
            display_name="Sales Manager",
            role="manager",
            department_id=sales.id,
        )
        db.add_all([hr, engineering_manager, sales_manager])
        db.flush()
        candidate = Candidate(
            code="T-PRIVATE-001",
            name="Sensitive Person",
            email="sensitive.person@example.test",
            phone="0912-345-678",
            city="Taipei",
            address="Taipei Private Street 99",
            current_title="Backend Engineer",
            current_company="Secret Employer Ltd",
            highest_education="Bachelor",
            total_years=5,
        )
        candidate.skills.append(CandidateSkill(skill="Python", skill_norm="python"))
        candidate.experiences.append(
            CandidateExperience(
                company="Secret Employer Ltd",
                title="API Engineer",
                industry="SaaS",
                years=4,
                sort_order=0,
            )
        )
        candidate.educations.append(
            CandidateEducation(
                school="Private University",
                degree="Bachelor",
                sort_order=0,
            )
        )
        db.add(candidate)
        db.flush()
        requisition = JobRequisition(
            req_no="DEID-ENG-001",
            title="Platform Engineer",
            department_id=engineering.id,
            requested_by=engineering_manager.id,
            employment_type="full_time",
            work_city="Taipei",
            jd="Build reliable services",
            status="submitted",
        )
        db.add(requisition)
        db.flush()
        resume = ResumeFile(
            candidate_id=candidate.id,
            uploaded_by=hr.id,
            storage_key="resumes/source.pdf",
            original_filename="resume.pdf",
            file_hash=source_hash,
            file_size=len(source_bytes),
            mime="application/pdf",
            source_platform="direct",
            parse_status="confirmed",
            parsed_payload={
                "name": "Sensitive Person",
                "email": "sensitive.person@example.test",
                "phone": "0912-345-678",
                "address": "Taipei Private Street 99",
                "current_company": "Secret Employer Ltd",
                "current_title": "Backend Engineer",
                "total_years": 5,
                "skills": ["Python"],
            },
        )
        db.add(resume)
        db.flush()
        application = JobApplication(
            requisition_id=requisition.id,
            candidate_id=candidate.id,
            resume_id=resume.id,
            status="submitted",
            source="career_site",
        )
        db.add(application)
        db.commit()
        ids = {
            "hr": hr.id,
            "engineering_manager": engineering_manager.id,
            "sales_manager": sales_manager.id,
            "engineering": engineering.id,
            "sales": sales.id,
            "candidate": candidate.id,
            "resume": resume.id,
        }
        users = {
            "hr": hr,
            "engineering_manager": engineering_manager,
            "sales_manager": sales_manager,
        }

    current_user = {"value": users["hr"]}

    def override_db():
        with testing_session() as db:
            yield db

    def override_user():
        return current_user["value"]

    app = FastAPI()
    app.include_router(routes_module.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, testing_session, ids, current_user, storage
    finally:
        Base.metadata.drop_all(engine)


def _as_user(current_user: dict, testing_session: sessionmaker, user_id: int) -> None:
    with testing_session() as db:
        current_user["value"] = db.get(User, user_id)


def _upload(
    client: TestClient,
    resume_id: int,
    *,
    filename: str = "deidentified.pdf",
    content: bytes = CLEAN_UPLOAD_BYTES,
    content_type: str = "application/pdf",
) -> object:
    return client.post(
        f"/api/v1/resumes/{resume_id}/deidentifications",
        files={"file": (filename, content, content_type)},
    )


def _upload_ok(client: TestClient, resume_id: int) -> dict:
    response = _upload(client, resume_id)
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "private, no-store"
    return response.json()


def test_upload_derives_payload_and_scans_without_touching_original(
    deidentified_client,
) -> None:
    client, testing_session, ids, _current_user, storage = deidentified_client
    with storage.materialize("resumes/source.pdf") as original_path:
        original_before = original_path.read_bytes()

    body = _upload_ok(client, ids["resume"])
    assert body["version"] == 1
    assert body["validation_status"] == "review_required"
    assert body["deidentification_version"] == "manual-upload-v1"
    assert body["mime"] == "application/pdf"
    assert body["has_file"] is True

    # The clean upload leaks nothing, so it is approvable.
    summary = body["validation_summary"]
    assert summary["blocker_count"] == 0
    assert summary["manual"] is True
    assert set(summary) >= {
        "schema_version",
        "blocker_count",
        "findings",
        "redactions",
        "payload_field_count",
        "pdf_character_count",
    }

    # analysis_payload is derived from the candidate's structured safe fields,
    # not from the uploaded bytes, and never carries PII.
    assert set(body["analysis_payload"]) == {
        "schema_version",
        "current_title",
        "total_years",
        "skills",
        "experience_roles",
        "highest_education",
    }
    serialized_payload = json.dumps(body["analysis_payload"], ensure_ascii=False)
    for private_value in (
        "Sensitive Person",
        "sensitive.person@example.test",
        "0912-345-678",
        "Taipei Private Street 99",
        "Secret Employer Ltd",
        "Private University",
        "T-PRIVATE-001",
    ):
        assert private_value not in serialized_payload

    with storage.materialize("resumes/source.pdf") as original_path:
        assert original_path.read_bytes() == original_before
    with testing_session() as db:
        document = db.get(DeidentifiedResumeDocument, body["id"])
        assert document.storage_key.startswith("deidentified-resumes/")
        assert document.storage_key != "resumes/source.pdf"
        assert storage.exists(document.storage_key)
        assert storage.path_for(document.storage_key).read_bytes() == CLEAN_UPLOAD_BYTES
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "deidentified_resume.create"))
        assert audit is not None
        assert "Sensitive Person" not in json.dumps(audit.details, ensure_ascii=False)


def test_full_flow_upload_review_approve_and_download(deidentified_client) -> None:
    client, testing_session, ids, _current_user, _storage = deidentified_client
    body = _upload_ok(client, ids["resume"])
    assert body["validation_status"] == "review_required"

    approved = client.post(f"/api/v1/deidentified-resumes/{body['id']}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["validation_status"] == "analysis_ready"

    with testing_session() as db:
        assert db.get(DeidentifiedResumeDocument, body["id"]).validation_status == "analysis_ready"

    download = client.get(f"/api/v1/deidentified-resumes/{body['id']}/file")
    assert download.status_code == 200
    assert download.content == CLEAN_UPLOAD_BYTES
    assert download.headers["cache-control"] == "private, no-store"
    preview = client.get(f"/api/v1/deidentified-resumes/{body['id']}/preview")
    assert preview.status_code == 200
    assert preview.content == CLEAN_UPLOAD_BYTES


def test_residual_pii_upload_is_flagged_and_blocks_approval(deidentified_client) -> None:
    client, testing_session, ids, _current_user, _storage = deidentified_client
    response = _upload(client, ids["resume"], content=LEAKY_UPLOAD_BYTES)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["validation_status"] == "review_required"
    assert body["validation_summary"]["blocker_count"] > 0

    approval = client.post(f"/api/v1/deidentified-resumes/{body['id']}/approve")
    assert approval.status_code == 409
    assert "blockers" in approval.json()["detail"]
    with testing_session() as db:
        assert db.get(DeidentifiedResumeDocument, body["id"]).validation_status == (
            "review_required"
        )


def test_illegal_upload_is_rejected(deidentified_client) -> None:
    client, testing_session, ids, _current_user, _storage = deidentified_client

    # Not a PDF at all.
    wrong_type = _upload(
        client,
        ids["resume"],
        filename="notes.txt",
        content=b"just some text",
        content_type="text/plain",
    )
    assert wrong_type.status_code == 415

    # PDF extension/mime but the magic bytes do not match a real PDF.
    bad_signature = _upload(
        client,
        ids["resume"],
        filename="fake.pdf",
        content=b"this is not really a pdf",
        content_type="application/pdf",
    )
    assert bad_signature.status_code == 415

    with testing_session() as db:
        assert db.scalars(select(DeidentifiedResumeDocument)).all() == []


def test_infected_upload_is_rejected(
    deidentified_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, testing_session, ids, _current_user, _storage = deidentified_client
    monkeypatch.setattr(
        service_module, "get_file_scanner", lambda settings=None: _InfectedScanner()
    )
    response = _upload(client, ids["resume"])
    assert response.status_code == 422
    assert "Malware" in response.json()["detail"]
    with testing_session() as db:
        assert db.scalars(select(DeidentifiedResumeDocument)).all() == []


def test_new_version_only_supersedes_ready_document_when_approved(
    deidentified_client,
) -> None:
    client, testing_session, ids, _current_user, _storage = deidentified_client
    first = _upload_ok(client, ids["resume"])
    approved_first = client.post(f"/api/v1/deidentified-resumes/{first['id']}/approve")
    assert approved_first.status_code == 200
    assert approved_first.headers["cache-control"] == "private, no-store"
    assert approved_first.json()["validation_status"] == "analysis_ready"

    second = _upload_ok(client, ids["resume"])
    assert second["version"] == 2
    assert second["anonymous_ref"] == first["anonymous_ref"]
    with testing_session() as db:
        assert db.get(DeidentifiedResumeDocument, first["id"]).validation_status == (
            "analysis_ready"
        )
        first_key = db.get(DeidentifiedResumeDocument, first["id"]).storage_key
        second_key = db.get(DeidentifiedResumeDocument, second["id"]).storage_key
        assert first_key != second_key

    approved_second = client.post(f"/api/v1/deidentified-resumes/{second['id']}/approve")
    assert approved_second.status_code == 200
    with testing_session() as db:
        assert db.get(DeidentifiedResumeDocument, first["id"]).validation_status == ("superseded")
        assert db.get(DeidentifiedResumeDocument, second["id"]).validation_status == (
            "analysis_ready"
        )


def test_validation_blockers_prevent_approval(deidentified_client) -> None:
    client, testing_session, ids, _current_user, _storage = deidentified_client
    body = _upload_ok(client, ids["resume"])
    with testing_session() as db:
        document = db.get(DeidentifiedResumeDocument, body["id"])
        document.validation_summary = {
            **document.validation_summary,
            "blocker_count": 1,
            "findings": [{"type": "pdf_email", "count": 1}],
        }
        db.commit()
    response = client.post(f"/api/v1/deidentified-resumes/{body['id']}/approve")
    assert response.status_code == 409
    assert "blockers" in response.json()["detail"]
    with testing_session() as db:
        assert db.get(DeidentifiedResumeDocument, body["id"]).validation_status == (
            "review_required"
        )


def test_manager_scope_approval_gate_and_no_store_headers(deidentified_client) -> None:
    client, testing_session, ids, current_user, _storage = deidentified_client
    body = _upload_ok(client, ids["resume"])

    _as_user(current_user, testing_session, ids["engineering_manager"])
    assert _upload(client, ids["resume"]).status_code == 403
    assert client.post(f"/api/v1/deidentified-resumes/{body['id']}/approve").status_code == 403
    assert client.get(f"/api/v1/candidates/{ids['candidate']}/deidentified-resumes").json() == []
    assert client.get(f"/api/v1/deidentified-resumes/{body['id']}/preview").status_code == 403

    _as_user(current_user, testing_session, ids["hr"])
    assert client.post(f"/api/v1/deidentified-resumes/{body['id']}/approve").status_code == 200

    _as_user(current_user, testing_session, ids["engineering_manager"])
    visible = client.get(f"/api/v1/candidates/{ids['candidate']}/deidentified-resumes")
    assert visible.status_code == 200
    assert visible.headers["cache-control"] == "private, no-store"
    assert [item["id"] for item in visible.json()] == [body["id"]]
    preview = client.get(f"/api/v1/deidentified-resumes/{body['id']}/preview")
    assert preview.status_code == 200
    assert preview.headers["cache-control"] == "private, no-store"
    assert preview.headers["pragma"] == "no-cache"
    download = client.get(f"/api/v1/deidentified-resumes/{body['id']}/file")
    assert download.status_code == 200
    assert download.headers["cache-control"] == "private, no-store"
    assert "Sensitive Person" not in download.headers["content-disposition"]

    _as_user(current_user, testing_session, ids["sales_manager"])
    assert (
        client.get(f"/api/v1/candidates/{ids['candidate']}/deidentified-resumes").status_code == 403
    )
    assert client.get(f"/api/v1/deidentified-resumes/{body['id']}/file").status_code == 403


def test_storage_failure_rolls_back_metadata_and_partial_object(
    deidentified_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, testing_session, ids, _current_user, storage = deidentified_client
    failing = FailAfterPutStorage(storage.root)
    monkeypatch.setattr(routes_module, "get_storage_provider", lambda: failing)

    response = _upload(client, ids["resume"])
    assert response.status_code == 500
    with testing_session() as db:
        assert db.scalars(select(DeidentifiedResumeDocument)).all() == []
    assert failing.exists("resumes/source.pdf")
    derivative_root = failing.root / "deidentified-resumes"
    assert not derivative_root.exists() or list(derivative_root.iterdir()) == []


def test_tampered_derivative_cannot_be_approved_or_served(deidentified_client) -> None:
    client, testing_session, ids, _current_user, storage = deidentified_client
    body = _upload_ok(client, ids["resume"])
    with testing_session() as db:
        document = db.get(DeidentifiedResumeDocument, body["id"])
        derivative_path = storage.path_for(document.storage_key)
    derivative_path.write_bytes(b"%PDF-1.4\ntampered derivative\n%%EOF")

    approval = client.post(f"/api/v1/deidentified-resumes/{body['id']}/approve")
    assert approval.status_code == 409
    assert "integrity" in approval.json()["detail"]
    preview = client.get(f"/api/v1/deidentified-resumes/{body['id']}/preview")
    assert preview.status_code == 409
    with testing_session() as db:
        assert db.get(DeidentifiedResumeDocument, body["id"]).validation_status == (
            "review_required"
        )
