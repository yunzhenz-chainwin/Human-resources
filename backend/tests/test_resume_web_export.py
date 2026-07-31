import importlib.util
import sys
import threading
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "standalone_resume_anonymizer_export",
    ROOT / "resume_anonymizer.py",
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_download_filename_uses_input_stem_and_collision_suffix() -> None:
    module.WebHandler._used_names.clear()
    first = module.WebHandler._filename("candidate.docx")
    second = module.WebHandler._filename("candidate.docx")
    assert first.endswith(".txt")
    assert "candidate_" in first
    assert second.endswith("_01.txt")


def test_plain_text_filename_has_resume_prefix() -> None:
    module.WebHandler._used_names.clear()
    assert module.WebHandler._filename().startswith("resume_")


def test_docx_export_preserves_importable_format() -> None:
    name = module.WebHandler._filename("candidate.docx", ".docx")
    payload = module.render_docx("姓名：[NAME]\nEmail：[EMAIL]")
    assert name.endswith(".docx")
    assert payload.startswith(b"PK")
    assert "[NAME]" in module.extract_docx(payload)


def test_result_page_contains_download_link() -> None:
    handler = object.__new__(module.WebHandler)
    page = handler._page(
        result="[NAME]",
        download="token",
        filename="resume_20260727.txt",
    ).decode("utf-8")
    assert "/download/token" in page
    assert "resume_20260727.txt" in page


def test_empty_page_does_not_show_scanned_pdf_error() -> None:
    handler = object.__new__(module.WebHandler)
    page = handler._page().decode("utf-8")
    assert "偵測到掃描型 PDF" not in page
    assert "支援 PDF、DOCX、TXT" in page


def test_scanned_pdf_error_is_only_rendered_when_processing_fails() -> None:
    handler = object.__new__(module.WebHandler)
    page = handler._page(error="偵測到掃描型 PDF 或文字層不足").decode("utf-8")
    assert "偵測到掃描型 PDF 或文字層不足" in page


def test_short_text_post_redirect_displays_generated_result(tmp_path: Path) -> None:
    original_result_dir = module.WebHandler._result_dir
    module.WebHandler._result_dir = tmp_path
    module.WebHandler._results.clear()
    module.WebHandler._used_names.clear()
    server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.WebHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        data = urllib.parse.urlencode({"text": "姓名 中小名"}).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")

        assert response.status == 200
        assert "[NAME]" in body
        assert thread.is_alive()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        module.WebHandler._result_dir = original_result_dir
        module.WebHandler._results.clear()
