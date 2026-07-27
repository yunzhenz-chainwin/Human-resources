import importlib.util
import io
import sys
from pathlib import Path

import pytest
from pypdf import PdfWriter
from docx import Document

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "resume_anonymizer.py"
SPEC = importlib.util.spec_from_file_location("standalone_resume_anonymizer", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
resume_anonymizer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = resume_anonymizer
SPEC.loader.exec_module(resume_anonymizer)


def _blank_pdf(page_count: int = 1) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=612, height=792)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_scanned_pdf_fails_closed_with_private_ocr_guidance() -> None:
    with pytest.raises(resume_anonymizer.ScannedPDFError) as captured:
        resume_anonymizer.extract_pdf(_blank_pdf())

    message = str(captured.value)
    assert "掃描型 PDF" in message
    assert "不會直接產出去識別結果" in message
    assert "公司核准的本機 OCR" in message
    assert "人工確認" in message
    assert "未核准的第三方 OCR" in message


def test_pdf_limits_are_checked_before_anonymization() -> None:
    with pytest.raises(ValueError, match="超過 20 頁上限"):
        resume_anonymizer.extract_pdf(_blank_pdf(21))

    with pytest.raises(ValueError, match="超過 10 MB 上限"):
        resume_anonymizer.extract_pdf(b"x" * (resume_anonymizer.PDF_MAX_BYTES + 1))


def test_cli_pdf_input_uses_the_same_scanned_pdf_guard() -> None:
    data = _blank_pdf()

    class ScannedPath:
        suffix = ".pdf"

        @staticmethod
        def stat():
            return type("Stat", (), {"st_size": len(data)})()

        @staticmethod
        def read_bytes() -> bytes:
            return data

    with pytest.raises(resume_anonymizer.ScannedPDFError):
        resume_anonymizer.read_resume_input(ScannedPath())


def test_selectable_pdf_text_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = "姓名：王小明\n工作經驗：後端工程師五年，負責金融系統 API 開發與維護"

    class FakePage:
        def extract_text(self) -> str:
            return expected

    class FakeReader:
        is_encrypted = False
        pages = [FakePage()]

    monkeypatch.setattr("pypdf.PdfReader", lambda _stream: FakeReader())
    assert resume_anonymizer.extract_pdf(b"%PDF-test") == expected


def test_web_page_escapes_resume_and_error_content() -> None:
    handler = object.__new__(resume_anonymizer.WebHandler)
    page = handler._page(
        source="</textarea><script>alert('pii')</script>",
        result="<b>[NAME]</b>",
        error="<script>error</script>",
    ).decode("utf-8")

    assert "<script>" not in page
    assert "&lt;/textarea&gt;&lt;script&gt;" in page
    assert "&lt;b&gt;[NAME]&lt;/b&gt;" in page


def test_docx_input_extracts_paragraphs_and_table_cells() -> None:
    document = Document()
    document.add_paragraph("姓名 王小名")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Email"
    table.cell(0, 1).text = "person@example.com"
    output = io.BytesIO()
    document.save(output)

    text = resume_anonymizer.extract_docx(output.getvalue())
    anonymized, summary = resume_anonymizer.anonymize(text)
    assert "姓名 [NAME]" in anonymized
    assert "[EMAIL]" in anonymized
    assert summary.replacements["name_label"] == 1


def test_text_input_accepts_utf8_and_rejects_unknown_suffix() -> None:
    class TextPath:
        suffix = ".txt"

        @staticmethod
        def read_bytes() -> bytes:
            return "姓名 王小名\n電話 0912-345-678".encode("utf-8")

    assert "姓名 王小名" in resume_anonymizer.read_resume_input(TextPath())

    class UnknownPath:
        suffix = ".rtf"

    unknown = UnknownPath()
    with pytest.raises(ValueError, match="不支援的檔案格式"):
        resume_anonymizer.read_resume_input(unknown)
