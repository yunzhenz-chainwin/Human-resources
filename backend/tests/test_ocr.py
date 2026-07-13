import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from pypdf import PdfWriter

from app.services.ocr import OCRLimits, extract_pdf_with_ocr, select_provider


class FakeProvider:
    def __init__(self, name: str, available: bool, text: str = "") -> None:
        self.name = name
        self._available = available
        self.text = text
        self.calls = 0

    def available(self) -> bool:
        return self._available

    def recognize(self, pdf_path: Path, page_count: int, limits: OCRLimits) -> str:
        self.calls += 1
        return self.text


def scanned_pdf(path: Path, pages: int = 1) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    with path.open("wb") as stream:
        writer.write(stream)
    return path


@pytest.fixture()
def ocr_path() -> Path:
    directory = Path("storage") / f"ocr-test-{uuid4().hex}"
    directory.mkdir(parents=True)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_provider_selection_uses_first_available() -> None:
    unavailable = FakeProvider("off", False)
    available = FakeProvider("on", True)
    assert select_provider([unavailable, available]) is available


def test_scanned_pdf_without_binary_falls_back_to_review(ocr_path: Path) -> None:
    pdf = scanned_pdf(ocr_path / "scan.pdf")
    unavailable = FakeProvider("missing_local_binary", False)
    result = extract_pdf_with_ocr(pdf, providers=[unavailable])
    assert result.needs_review
    assert result.error_code == "ocr_unavailable"
    assert unavailable.calls == 0


def test_successful_injected_provider(ocr_path: Path) -> None:
    pdf = scanned_pdf(ocr_path / "scan.pdf")
    provider = FakeProvider("mock_ocr", True, "王小明\nming@example.com")
    result = extract_pdf_with_ocr(pdf, provider=provider)
    assert result.status == "ocr_extracted"
    assert result.provider == "mock_ocr"
    assert result.text == "王小明\nming@example.com"
    assert provider.calls == 1


def test_page_and_file_limits_stop_before_ocr(ocr_path: Path) -> None:
    provider = FakeProvider("mock_ocr", True, "should not run")
    pages = scanned_pdf(ocr_path / "many.pdf", pages=2)
    page_result = extract_pdf_with_ocr(
        pages, provider=provider, limits=OCRLimits(max_pages=1)
    )
    assert page_result.error_code == "too_many_pages"

    file_result = extract_pdf_with_ocr(
        pages,
        provider=provider,
        limits=OCRLimits(max_file_bytes=1),
    )
    assert file_result.error_code == "file_too_large"
    assert provider.calls == 0
