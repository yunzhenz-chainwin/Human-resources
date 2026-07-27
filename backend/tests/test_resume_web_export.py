import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("standalone_resume_anonymizer_export", ROOT / "resume_anonymizer.py")
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


def test_result_page_contains_download_link() -> None:
    handler = object.__new__(module.WebHandler)
    page = handler._page(result="[NAME]", download="token", filename="resume_20260727.txt").decode("utf-8")
    assert "/download/token" in page
    assert "resume_20260727.txt" in page
