from dataclasses import dataclass
from pathlib import Path

from docx import Document

from app.parsers import select_adapter
from app.services.ocr import extract_pdf_with_ocr

PARSER_VERSION = "adapters-2.0"


@dataclass
class ParserResult:
    source_platform: str
    status: str
    raw_text: str
    payload: dict
    confidence: dict[str, float]
    overall_confidence: float
    error_message: str | None = None


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        result = extract_pdf_with_ocr(path)
        if result.needs_review:
            raise ValueError(result.error_message or "PDF requires manual review")
        return result.text
    if suffix == ".docx":
        document = Document(str(path))
        paragraphs = [paragraph.text for paragraph in document.paragraphs]
        for table in document.tables:
            paragraphs.extend(cell.text for row in table.rows for cell in row.cells)
        return "\n".join(paragraphs)
    if suffix == ".doc":
        raise ValueError(
            "Legacy DOC files are stored safely but require manual review or conversion"
        )
    raise ValueError("Unsupported resume format")


def detect_platform(text: str, requested: str) -> str:
    """Compatibility entry point used by older callers and tests."""
    return select_adapter(text, requested).platform


def parse_text(text: str, requested_platform: str = "generic") -> ParserResult:
    text = text.replace("\x00", "").strip()
    parsed = select_adapter(text, requested_platform)
    populated = [score for score in parsed.confidence.values() if score > 0]
    overall = (
        round(sum(populated) / len(parsed.confidence), 2) if populated else 0.0
    )
    has_identity = bool(
        parsed.payload.get("name")
        and (parsed.payload.get("email") or parsed.payload.get("phone"))
    )
    status = (
        "parsed"
        if parsed.layout_recognized and has_identity and overall >= 0.55
        else "needs_review"
    )
    error = None
    if not parsed.layout_recognized:
        error = (
            f"Unknown {parsed.platform} layout; parsed with {parsed.version} "
            "and requires manual review"
        )
    return ParserResult(
        parsed.platform,
        status,
        text,
        parsed.payload,
        parsed.confidence,
        overall,
        error,
    )


def parse_resume(path: Path, requested_platform: str) -> ParserResult:
    if path.suffix.lower() == ".pdf":
        ocr_result = extract_pdf_with_ocr(path)
        if ocr_result.needs_review:
            return ParserResult(
                requested_platform,
                "needs_review",
                "",
                {},
                {},
                0.0,
                ocr_result.error_message or "PDF requires manual review",
            )
        return parse_text(ocr_result.text, requested_platform)
    try:
        return parse_text(extract_text(path), requested_platform)
    except Exception as exc:
        return ParserResult(
            requested_platform,
            "needs_review" if path.suffix.lower() == ".doc" else "failed",
            "",
            {},
            {},
            0.0,
            str(exc)[:1000],
        )
