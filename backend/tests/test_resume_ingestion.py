import shutil
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.dependencies.auth import audit_pii_read, get_current_user
from app.main import app
from app.models import CandidateSkill, ResumeFile
from app.services.resume_parser import parse_text


def docx_bytes(text: str) -> bytes:
    document = Document()
    for line in text.splitlines():
        document.add_paragraph(line)
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


@pytest.fixture()
def resume_client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    test_storage = Path("storage") / f"resume-test-{uuid4().hex}"
    get_settings().resume_storage_path = str(test_storage)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1, role="admin", department_id=None, is_active=True
    )
    app.dependency_overrides[audit_pii_read] = lambda: None
    with TestClient(app) as client:
        yield client, testing_session
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    shutil.rmtree(test_storage, ignore_errors=True)


def test_parser_recognizes_104_and_generic_custom_formats() -> None:
    fixed = parse_text(
        "104人力銀行\n姓名：王小明\nEmail: ming@example.com\n手機：0912-345-678\n"
        "居住地：台北市\n目前職稱：後端工程師\n工作年資：5年\n技能：Python、FastAPI、SQL"
    )
    assert fixed.source_platform == "p104"
    assert fixed.payload["name"] == "王小明"
    assert fixed.payload["total_years"] == 5
    assert "python" in {item.lower() for item in fixed.payload["skills"]}

    custom = parse_text(
        "陳美玲\nmeiling@example.org\n0988 123 456\n高雄市\nSkills: Excel, Power BI",
        "generic",
    )
    assert custom.payload["name"] == "陳美玲"
    assert custom.payload["city"] == "高雄市"
    assert custom.status == "parsed"


def test_batch_upload_duplicate_review_and_confirm(resume_client) -> None:
    client, testing_session = resume_client
    content = docx_bytes(
        "1111人力銀行\n姓名：林志偉\nEmail：lin@example.com\n手機：0911-222-333\n"
        "居住地：新北市\n目前職稱：資料工程師\n工作年資：3年\n技能：Python、SQL"
    )
    files = [("files", ("resume.docx", content, "application/octet-stream"))]
    first = client.post(
        "/api/v1/resumes/upload", data={"source_platform": "generic"}, files=files
    )
    assert first.status_code == 201
    item = first.json()[0]
    assert item["source_platform"] == "p1111"
    assert item["duplicate"] is False

    duplicate = client.post(
        "/api/v1/resumes/upload", data={"source_platform": "generic"}, files=files
    )
    assert duplicate.status_code == 201
    assert duplicate.json()[0]["id"] == item["id"]
    assert duplicate.json()[0]["duplicate"] is True

    reviewed = client.put(
        f"/api/v1/resumes/{item['id']}/parsed",
        json={
            "parsed_payload": {
                "name": "林志偉",
                "email": "lin@example.com",
                "phone": "0911222333",
                "city": "新北市",
                "current_title": "資料工程師",
                "total_years": 3,
                "skills": ["Python", "SQL"],
            }
        },
    )
    assert reviewed.status_code == 200
    confirmed = client.post(f"/api/v1/resumes/{item['id']}/confirm", json={})
    assert confirmed.status_code == 200
    assert confirmed.json()["created"] is True

    with testing_session() as db:
        resume = db.get(ResumeFile, item["id"])
        skills = db.scalars(
            select(CandidateSkill.skill).where(
                CandidateSkill.candidate_id == confirmed.json()["candidate_id"]
            )
        ).all()
        assert resume.parse_status == "confirmed"
        assert set(skills) == {"Python", "SQL"}


def test_talent_pool_application_without_job_id(resume_client) -> None:
    client, _ = resume_client
    content = docx_bytes("姓名：吳佳蓉\nEmail：wu@example.com\n技能：Vue、TypeScript")
    response = client.post(
        "/api/v1/public/applications",
        data={
            "name": "吳佳蓉",
            "email": "wu@example.com",
            "skills": "Vue, TypeScript",
            "consent": "true",
            "source_platform": "direct",
        },
        files={"resume": ("custom.docx", content, "application/octet-stream")},
    )
    assert response.status_code == 201
    assert response.json()["duplicate"] is False
    detail = client.get(f"/api/v1/resumes/{response.json()['resume_id']}").json()
    assert detail["parsed_payload"]["name"] == "吳佳蓉"
    assert detail["parsed_payload"]["skills"] == ["Vue", "TypeScript"]


def test_candidate_activities_are_listed_newest_first(resume_client) -> None:
    client, _ = resume_client
    candidate = client.post(
        "/api/v1/candidates", json={"name": "活動測試", "email": "activity@example.com"}
    ).json()
    for happened_at, note in (
        ("2026-01-01T01:00:00Z", "older"),
        ("2026-01-02T01:00:00Z", "newer"),
    ):
        response = client.post(
            f"/api/v1/candidates/{candidate['id']}/activities",
            json={"type": "note", "content": note, "happened_at": happened_at},
        )
        assert response.status_code == 201
    response = client.get(f"/api/v1/candidates/{candidate['id']}/activities")
    assert response.status_code == 200
    assert [item["content"] for item in response.json()] == ["newer", "older"]
    assert client.get("/api/v1/candidates/99999/activities").status_code == 404
