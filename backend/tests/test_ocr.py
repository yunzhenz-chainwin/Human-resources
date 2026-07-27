import shutil
import subprocess
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


class PathRecordingProvider(FakeProvider):
    """Provider used to ensure paths are passed as argv, never shell text."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.path_seen: Path | None = None

    def recognize(self, pdf_path: Path, page_count: int, limits: OCRLimits) -> str:
        self.path_seen = pdf_path
        return super().recognize(pdf_path, page_count, limits)


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


def test_empty_ocr_is_needs_review(ocr_path: Path) -> None:
    pdf = scanned_pdf(ocr_path / "empty.pdf")
    provider = FakeProvider("local_tesseract", True, "   \n")
    result = extract_pdf_with_ocr(pdf, provider=provider)
    assert result.needs_review
    assert result.error_code == "empty_ocr_result"


def test_provider_output_limit_is_enforced(ocr_path: Path) -> None:
    pdf = scanned_pdf(ocr_path / "huge.pdf")
    provider = FakeProvider("local_tesseract", True, "x" * 101)
    result = extract_pdf_with_ocr(
        pdf, provider=provider, limits=OCRLimits(max_output_chars=100)
    )
    assert result.needs_review
    assert result.error_code == "output_too_large"


def test_provider_receives_path_without_shell_interpolation(ocr_path: Path) -> None:
    # A filename containing shell metacharacters must stay an ordinary Path.
    pdf = scanned_pdf(ocr_path / "resume;echo INJECTED.pdf")
    provider = PathRecordingProvider("local_tesseract", True, "safe text")
    result = extract_pdf_with_ocr(pdf, provider=provider)
    assert result.status == "ocr_extracted"
    assert provider.path_seen == pdf


def test_timeout_is_reported_without_leaking_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.ocr import LocalTesseractProvider, OCRProviderError

    def blocked(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("tesseract", 0.01)

    monkeypatch.setattr(subprocess, "run", blocked)
    with pytest.raises(OCRProviderError) as captured:
        LocalTesseractProvider._run(["tesseract", "input.png", "stdout"], 1.0)
    assert captured.value.code == "ocr_timeout"
