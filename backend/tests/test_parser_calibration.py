import base64
import hashlib
import hmac
import json
from pathlib import Path
from uuid import uuid4

import pytest
from pypdf import PdfWriter

from app.core.config import get_settings
from app.parsers import select_adapter
from app.parsers.registry import detect_source
from app.services.resume_parser import parse_resume, parse_text

FIXTURES = Path(__file__).parent / "fixtures" / "resumes"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("filename", "platform", "expected"),
    [
        (
            "p104_synthetic_v1.txt",
            "p104",
            {
                "name": "測試甲",
                "email": "synthetic.104@example.test",
                "phone": "0912-000-001",
                "city": "台北市",
                "current_title": "後端工程師",
                "total_years": 6.0,
                "skills": ["docker", "fastapi", "postgresql", "python"],
            },
        ),
        (
            "p1111_synthetic_v1.txt",
            "p1111",
            {
                "name": "測試乙",
                "email": "synthetic.1111@example.test",
                "phone": "0988-000-002",
                "city": "新北市",
                "current_title": "前端工程師",
                "total_years": 4.5,
                "skills": ["figma", "typescript", "vue"],
            },
        ),
        (
            "generic_synthetic_v1.txt",
            "direct",
            {
                "name": "測試丙",
                "email": "synthetic.generic@example.test",
                "phone": "0977-000-003",
                "city": "高雄市",
                "current_title": "資料分析師",
                "total_years": 3.0,
                "skills": ["power bi", "python", "sql"],
            },
        ),
    ],
)
def test_synthetic_golden_regression(filename: str, platform: str, expected: dict) -> None:
    result = parse_text(fixture_text(filename))
    assert result.source_platform == platform
    assert result.status == "parsed"
    assert {key: result.payload.get(key) for key in expected} == expected
    assert result.overall_confidence >= 0.85
    assert all(0 <= value <= 1 for value in result.confidence.values())


def test_requested_job_board_with_unknown_layout_requires_review() -> None:
    result = parse_text(fixture_text("unknown_p104_synthetic.txt"), "p104")
    assert result.source_platform == "p104"
    assert result.payload["name"] == "測試未知"
    assert result.status == "needs_review"
    assert result.error_message is not None
    assert "Unknown p104 layout" in result.error_message


def test_platform_marker_wins_over_requested_source() -> None:
    result = parse_text(fixture_text("p1111_synthetic_v1.txt"), "p104")
    assert result.source_platform == "p1111"
    assert result.status == "parsed"


def test_adapters_have_independent_versions() -> None:
    p104_result = select_adapter(fixture_text("p104_synthetic_v1.txt"))
    p1111_result = select_adapter(fixture_text("p1111_synthetic_v1.txt"))
    generic_result = select_adapter(fixture_text("generic_synthetic_v1.txt"))
    assert p104_result.version.startswith("p104-")
    assert p1111_result.version.startswith("p1111-")
    assert generic_result.version.startswith("generic-")
    assert len({p104_result.version, p1111_result.version, generic_result.version}) == 3


def test_source_detection_is_explainable_and_marks_ambiguous_claims() -> None:
    platform, confidence, evidence, review = detect_source(
        fixture_text("p104_synthetic_v1.txt"), "generic"
    )
    assert platform == "p104"
    assert confidence >= 0.70
    assert review is False
    assert {item["type"] for item in evidence} & {"platform_brand", "document_title"}

    platform, confidence, evidence, review = detect_source(
        "姓名：測試；Email: test@example.test", "p1111"
    )
    assert platform == "p1111"
    assert confidence == 0.35
    assert review is True
    assert any(item["type"] == "uploader_claim" for item in evidence)


@pytest.mark.parametrize(
    "text",
    [
        "104人力銀行 求職者履歷\n求職者姓名：測試\n累積年資：3年",
        "1111人力銀行 1111履歷表\n中文姓名：測試\n專長技能：Python",
        "求職者履歷\n求職者姓名：測試\n最近工作：工程師\n累積年資：3年",
    ],
)
def test_brand_or_common_fields_alone_do_not_prove_platform_export(text: str) -> None:
    platform, confidence, evidence, review = detect_source(text)
    assert platform == "generic"
    assert confidence == 0.40
    assert review is True
    assert any(item["type"] == "unverified_platform_claim" for item in evidence)


def test_ocr_name_without_colon_is_recovered() -> None:
    result = parse_text(
        "TalentHub履歷表\n姓名王小明13213321\n"
        "E-mail: candidate@example.com\n聯絡電話: 0912-345-678"
    )
    assert result.payload["name"] == "王小明"


def test_talenthub_pdf_metadata_restores_exact_fields() -> None:
    expected = {
        "schema": "talenthub.resume.v1",
        "name": "王小明",
        "email": "candidate@example.com",
        "phone": "0912-345-678",
        "city": "臺北市中正區",
        "current_title": "產品企劃",
        "total_years": 3,
        "highest_education": "大學",
        "expected_title": "產品企劃／專案管理",
        "expected_cities": ["臺北市", "新北市"],
        "skills": ["Excel", "Power BI", "SQL", "專案管理", "跨部門溝通"],
    }
    encoded = base64.b64encode(
        json.dumps(expected, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    # Sign the payload the way a genuine TalentHub export must: only an HMAC over the
    # base64 body (keyed by auth_secret_key) earns the trusted, no-review fast path.
    signature = base64.urlsafe_b64encode(
        hmac.new(
            get_settings().auth_secret_key.encode(), encoded.encode("ascii"), hashlib.sha256
        ).digest()
    ).decode("ascii")
    path = Path("storage") / f"metadata-test-{uuid4().hex}.pdf"
    path.parent.mkdir(exist_ok=True)
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Subject": f"THR1:{encoded}.{signature}"})
    with path.open("wb") as stream:
        writer.write(stream)

    try:
        result = parse_resume(path, "generic")
    finally:
        path.unlink(missing_ok=True)

    assert result.source_platform == "direct"
    assert result.status == "parsed"
    assert result.source_review_required is False
    assert result.payload == {key: value for key, value in expected.items() if key != "schema"}
    assert result.source_evidence == [
        {
            "type": "structured_pdf_metadata",
            "marker": "talenthub.resume.v1",
            "weight": 1.0,
        }
    ]


def test_generic_template_labels_map_title_and_skills() -> None:
    result = parse_text(
        "姓名：王小明\nEmail：candidate@example.com\n"
        "職務類別：產品企劃\n技能與專長：Excel、Power BI、SQL、專案管理"
    )
    assert result.payload["current_title"] == "產品企劃"
    assert result.payload["skills"] == ["excel", "power bi", "sql", "專案管理"]
