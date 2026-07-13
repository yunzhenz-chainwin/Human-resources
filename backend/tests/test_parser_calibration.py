from pathlib import Path

import pytest

from app.parsers import select_adapter
from app.services.resume_parser import parse_text

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
            "generic",
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
    assert result.payload == expected
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
