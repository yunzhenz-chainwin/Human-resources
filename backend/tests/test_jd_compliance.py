from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.requisitions import router as requisitions_router
from app.dependencies.auth import get_current_user
from app.services.jd_compliance import (
    JD_COMPLIANCE_RULES,
    JD_COMPLIANCE_RULES_VERSION,
    lint_job_text,
)


# ---------------------------------------------------------------------------
# Pure-function coverage: each protected category should fire on an obvious hit.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("category", "text"),
    [
        ("gender", "限男性，需輪班"),
        ("gender", "female only, night shift"),
        ("age", "限35歲以下，年輕有活力"),
        ("age", "限應屆畢業生"),
        ("marital_pregnancy", "限未婚，無家庭負擔"),
        ("military", "需役畢，可立即上工"),
        ("appearance", "需體貌端正、五官端正"),
        ("nationality_race", "限本國籍，不收外籍"),
        ("religion", "須為基督教徒"),
        ("disability", "須四肢健全、身體健康"),
        ("astrology", "參考星座與血型"),
    ],
)
def test_each_category_is_detected(category: str, text: str) -> None:
    result = lint_job_text(jd=text)
    assert result["status"] == "warning"
    categories = {finding["category"] for finding in result["findings"]}
    assert category in categories
    for finding in result["findings"]:
        assert finding["field"] == "jd"
        assert finding["matched"]
        assert finding["suggestion"]


def test_findings_carry_the_source_field() -> None:
    result = lint_job_text(
        title="限男性儲備幹部",
        summary="限35歲以下",
        jd="歡迎具備 Python 經驗者應徵",
    )
    by_field = {finding["field"]: finding["category"] for finding in result["findings"]}
    assert by_field.get("title") == "gender"
    assert by_field.get("age") in {None, "age"}  # summary carries the age hit
    assert any(f["field"] == "summary" and f["category"] == "age" for f in result["findings"])


def test_clean_jd_is_not_flagged() -> None:
    clean = (
        "負責後端 API 開發，熟悉 Python 與 FastAPI，具備三年以上開發經驗，"
        "須年滿 18 歲並具備在台合法工作權，能配合團隊合作。"
        "我們重視多元共融，不限性別、年齡、婚姻與背景，歡迎符合資格者應徵。"
    )
    result = lint_job_text(title="資深後端工程師", summary="協助平台開發", jd=clean)
    assert result["status"] == "ok"
    assert result["findings"] == []


def test_empty_input_is_ok() -> None:
    assert lint_job_text() == {"status": "ok", "findings": []}


def test_duplicate_matches_deduped_per_field() -> None:
    result = lint_job_text(jd="限男性；再次強調限男性；限男性優先")
    gender_matches = [f for f in result["findings"] if f["category"] == "gender"]
    # The identical "限男性" phrase collapses to a single finding.
    assert any(f["matched"] == "限男性" for f in gender_matches)
    assert len([f for f in gender_matches if f["matched"] == "限男性"]) == 1


def test_rules_version_is_stable_string() -> None:
    assert isinstance(JD_COMPLIANCE_RULES_VERSION, str)
    assert JD_COMPLIANCE_RULES_VERSION
    # Every category in the dictionary carries a rewrite suggestion.
    for rule in JD_COMPLIANCE_RULES:
        assert rule.suggestion


# ---------------------------------------------------------------------------
# Endpoint contract: POST /requisitions/lint returns 200 + structured result.
# ---------------------------------------------------------------------------
@pytest.fixture()
def lint_client() -> TestClient:
    app = FastAPI()
    app.include_router(requisitions_router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1, role="hr", department_id=None, is_active=True
    )
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_lint_endpoint_returns_findings(lint_client: TestClient) -> None:
    response = lint_client.post(
        "/requisitions/lint",
        json={"title": "限女性客服", "summary": "", "jd": "限35歲以下"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "warning"
    assert body["rules_version"] == JD_COMPLIANCE_RULES_VERSION
    assert body["findings"]
    finding = body["findings"][0]
    assert set(finding) == {"category", "matched", "field", "suggestion"}


def test_lint_endpoint_ok_for_clean_text(lint_client: TestClient) -> None:
    response = lint_client.post(
        "/requisitions/lint",
        json={"title": "資深工程師", "jd": "熟悉 Python，不限性別與年齡。"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["findings"] == []


def test_lint_endpoint_requires_recruiting_role() -> None:
    app = FastAPI()
    app.include_router(requisitions_router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=2, role="candidate", department_id=None, is_active=True
    )
    with TestClient(app) as client:
        response = client.post("/requisitions/lint", json={"jd": "限男性"})
    app.dependency_overrides.clear()
    assert response.status_code == 403
