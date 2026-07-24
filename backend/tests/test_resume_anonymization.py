import json
from collections.abc import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.resume_anonymization import router
from app.db.base import Base
from app.db.session import get_db
from app.dependencies.auth import require_recruiting_user
from app.models import AuditLog, User
from app.services.resume_anonymization import anonymize_resume_text


@pytest.fixture()
def anonymization_client() -> Generator[tuple[TestClient, sessionmaker], None, None]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    with testing_session() as db:
        user = User(
            username="privacy-hr",
            email="privacy-hr@example.test",
            password_hash="not-used-in-this-test",
            display_name="Privacy HR",
            role="hr",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    app = FastAPI()

    def override_db():
        with testing_session() as db:
            yield db

    def override_user() -> User:
        with testing_session() as db:
            return db.scalar(select(User).where(User.username == "privacy-hr"))

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_recruiting_user] = override_user
    app.include_router(router)
    with TestClient(app) as client:
        yield client, testing_session
    Base.metadata.drop_all(engine)


def test_standalone_anonymization_masks_header_name_and_taiwan_pii(
    anonymization_client,
) -> None:
    client, testing_session = anonymization_client
    source = """王小明
個人履歷
Email：wang.xiaoming@example.com
手機：0912-345-678
台北市中正區仁愛路一段123號8樓
生日：1990/01/02
身分證字號：A123456789
個人網站：https://portfolio.example/about
自傳：王小明具備十年專案經驗。
"""
    response = client.post("/resume-anonymization", json={"plain_text": source})
    assert response.status_code == 201
    body = response.json()
    anonymized = body["anonymized_text"]
    for original in (
        "王小明",
        "wang.xiaoming@example.com",
        "0912-345-678",
        "台北市中正區仁愛路一段123號8樓",
        "1990/01/02",
        "A123456789",
        "https://portfolio.example/about",
    ):
        assert original not in anonymized
    counts = body["summary"]["field_counts"]
    assert counts == {
        "name": 2,
        "address": 1,
        "phone": 1,
        "email": 1,
        "birth_date": 1,
        "national_id": 1,
        "personal_url": 1,
    }
    assert body["summary"]["total_replacements"] == 8

    with testing_session() as db:
        audit = db.scalar(select(AuditLog).where(AuditLog.resource_id == body["operation_id"]))
        assert audit is not None
        serialized_audit = json.dumps(audit.details, ensure_ascii=False)
        assert "王小明" not in serialized_audit
        assert "wang.xiaoming@example.com" not in serialized_audit
        assert "plain_text" not in serialized_audit
        assert audit.details == {"summary": body["summary"]}

    summary_response = client.get(
        f"/resume-anonymization/{body['operation_id']}/summary"
    )
    assert summary_response.status_code == 200
    summary_body = summary_response.json()
    assert summary_body["summary"] == body["summary"]
    assert "anonymized_text" not in summary_body


def test_header_name_detection_requires_resume_context() -> None:
    result = anonymize_resume_text("王小明\n今天完成一般工作紀錄。")
    assert result.anonymized_text.startswith("王小明")
    assert result.summary.field_counts["name"] == 0


def test_additional_hints_are_masked_without_appearing_in_summary() -> None:
    result = anonymize_resume_text(
        "候選人代稱 Alpha Candidate，住在 Example Private Address。",
        additional_names=["Alpha Candidate"],
        additional_addresses=["Example Private Address"],
    )
    assert "Alpha Candidate" not in result.anonymized_text
    assert "Example Private Address" not in result.anonymized_text
    serialized = json.dumps(result.summary.model_dump(), ensure_ascii=False)
    assert "Alpha Candidate" not in serialized
    assert result.summary.field_counts["name"] == 1
    assert result.summary.field_counts["address"] == 1
