"""Safe, local-only OCR support for PDF resumes.

The public entry point is :func:`extract_pdf_with_ocr`.  It first uses the
PDF's text layer and only invokes an OCR provider when that layer is empty.
No cloud provider is registered by default; callers must explicitly inject
one if that policy ever changes.
"""

from __future__ import annotations

import importlib.util
import math
import os
import shutil
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from pypdf import PdfReader

from app.core.config import get_settings


@dataclass(frozen=True)
class OCRLimits:
    max_file_bytes: int = 10 * 1024 * 1024
    max_pages: int = 20
    max_pixels_per_page: int = 16_000_000
    max_output_chars: int = 250_000
    timeout_seconds: float = 45.0
    min_embedded_text_chars: int = 20


@dataclass(frozen=True)
class OCRResult:
    text: str
    status: str
    provider: str
    page_count: int = 0
    error_code: str | None = None
    error_message: str | None = None

    @property
    def needs_review(self) -> bool:
        return self.status == "needs_review"


class OCRProvider(Protocol):
    name: str

    def available(self) -> bool: ...

    def recognize(self, pdf_path: Path, page_count: int, limits: OCRLimits) -> str: ...


class OCRProviderError(RuntimeError):
    """An expected, isolated provider failure safe to report to the caller."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class LocalTesseractProvider:
    """OCR scanned PDFs using PyMuPDF rendering and local Tesseract."""

    name = "local_tesseract"

    def __init__(
        self,
        *,
        tesseract_command: str = "tesseract",
        languages: str = "chi_tra+eng",
    ) -> None:
        self.tesseract_command = self._resolve_tesseract(tesseract_command)
        self.languages = languages

    def available(self) -> bool:
        return bool(
            self.tesseract_command and importlib.util.find_spec("pymupdf")
        )

    @staticmethod
    def _resolve_tesseract(command: str) -> str | None:
        discovered = shutil.which(command)
        if discovered:
            return discovered
        if command != "tesseract":
            return None
        candidates: list[Path] = []
        # Allow the binary directory to be pinned via env for non-default
        # installs (other users, drives, or non-Windows hosts).
        configured_dir = os.environ.get("TESSERACT_DIR")
        if configured_dir:
            candidates += [
                Path(configured_dir) / name for name in ("tesseract.exe", "tesseract")
            ]
        # Keep the known Windows install locations as the default fallback.
        candidates += [
            Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
            Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
        ]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        return None

    @staticmethod
    def _temporary_root() -> Path:
        # Resolve to an absolute path from configuration rather than the process
        # working directory, which is unstable across launch contexts. An
        # explicit override wins; otherwise anchor to the configured storage area.
        override = os.environ.get("OCR_TEMP_DIR")
        if override:
            return Path(override).expanduser().resolve()
        storage_root = Path(get_settings().resume_storage_path).expanduser().resolve().parent
        return storage_root / "ocr-temp"

    def recognize(self, pdf_path: Path, page_count: int, limits: OCRLimits) -> str:
        if not self.available():
            raise OCRProviderError(
                "ocr_unavailable",
                "Local Tesseract OCR and/or PyMuPDF renderer is not installed",
            )

        deadline = time.monotonic() + limits.timeout_seconds
        import pymupdf

        max_dimension = max(1, math.isqrt(limits.max_pixels_per_page))
        chunks: list[str] = []
        # Use the application's writable storage instead of the Windows service
        # account temp directory, which may deny child OCR processes access.
        temporary_root = self._temporary_root()
        temporary_root.mkdir(parents=True, exist_ok=True)
        temporary_files: list[Path] = []
        try:
            with pymupdf.open(pdf_path) as document:
                for page_number, page in enumerate(document, start=1):
                    if time.monotonic() >= deadline:
                        raise OCRProviderError("ocr_timeout", "OCR exceeded its time limit")
                    longest_side = max(page.rect.width, page.rect.height, 1)
                    scale = max_dimension / longest_side
                    pixmap = page.get_pixmap(
                        matrix=pymupdf.Matrix(scale, scale),
                        alpha=False,
                        colorspace=pymupdf.csRGB,
                    )
                    if pixmap.width * pixmap.height > limits.max_pixels_per_page:
                        raise OCRProviderError("page_too_large", "Rendered page exceeds limit")
                    image_path = temporary_root / f"{uuid4().hex}-page-{page_number}.png"
                    image_path.write_bytes(pixmap.tobytes("png"))
                    temporary_files.append(image_path)
                    completed = self._run(
                        [
                            self.tesseract_command or "tesseract",
                            str(image_path),
                            "stdout",
                            "-l",
                            self.languages,
                        ],
                        deadline,
                        capture_output=True,
                    )
                    chunks.append(completed.stdout)
                    if sum(len(chunk) for chunk in chunks) > limits.max_output_chars:
                        raise OCRProviderError("output_too_large", "OCR output exceeds limit")
        finally:
            for temporary_file in temporary_files:
                temporary_file.unlink(missing_ok=True)
        return "\n".join(chunks).strip()

    @staticmethod
    def _run(
        command: list[str],
        deadline: float,
        *,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise OCRProviderError("ocr_timeout", "OCR exceeded its time limit")
        try:
            return subprocess.run(  # noqa: S603 - fixed executable and argument list
                command,
                check=True,
                capture_output=capture_output,
                text=True,
                # Tesseract emits UTF-8; decode it explicitly so hosts whose
                # locale is not UTF-8 (e.g. Windows cp950/Big5) don't crash on
                # CJK output. errors="replace" keeps a stray byte from aborting.
                encoding="utf-8",
                errors="replace",
                timeout=remaining,
            )
        except subprocess.TimeoutExpired as exc:
            raise OCRProviderError("ocr_timeout", "OCR exceeded its time limit") from exc
        except (OSError, subprocess.CalledProcessError) as exc:
            raise OCRProviderError("ocr_failed", "Local OCR process failed") from exc


def select_provider(providers: Sequence[OCRProvider] | None = None) -> OCRProvider | None:
    """Select the first available provider; defaults to local-only OCR."""

    candidates: Sequence[OCRProvider] = providers or (LocalTesseractProvider(),)
    return next((provider for provider in candidates if provider.available()), None)


def extract_pdf_with_ocr(
    path: Path,
    *,
    provider: OCRProvider | None = None,
    providers: Sequence[OCRProvider] | None = None,
    limits: OCRLimits | None = None,
) -> OCRResult:
    """Extract a PDF text layer, falling back to an explicitly bounded OCR provider."""

    limits = limits or OCRLimits()
    try:
        size = path.stat().st_size
        if size > limits.max_file_bytes:
            return _review("file_too_large", "PDF exceeds OCR file size limit")
        if path.suffix.lower() != ".pdf":
            return _review("unsupported_format", "OCR only accepts PDF files")

        reader = PdfReader(str(path))
        page_count = len(reader.pages)
        if page_count > limits.max_pages:
            return _review(
                "too_many_pages",
                f"PDF has {page_count} pages; limit is {limits.max_pages}",
                page_count,
            )
        embedded_text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        if len(embedded_text) >= limits.min_embedded_text_chars:
            return OCRResult(
                embedded_text[: limits.max_output_chars], "text_extracted", "pdf_text", page_count
            )

        selected = provider or select_provider(providers)
        if selected is None:
            return _review(
                "ocr_unavailable",
                "Scanned PDF needs local OCR, but no OCR provider is available",
                page_count,
            )
        text = selected.recognize(path, page_count, limits).strip()
        if not text:
            return _review("empty_ocr_result", "OCR did not recognize any text", page_count)
        return OCRResult(text, "ocr_extracted", selected.name, page_count)
    except OCRProviderError as exc:
        return _review(exc.code, str(exc), locals().get("page_count", 0))
    except Exception:
        # Parser/encryption/corrupt-file details can contain local paths. Keep
        # the public failure stable while preserving error isolation.
        return _review("invalid_pdf", "PDF could not be read", locals().get("page_count", 0))


def _review(code: str, message: str, page_count: int = 0) -> OCRResult:
    return OCRResult(
        "",
        "needs_review",
        "none",
        page_count,
        error_code=code,
        error_message=message,
    )
