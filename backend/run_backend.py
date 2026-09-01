# TalentHub 後端啟動器:確保 OCR 工具(Tesseract / Poppler)在 PATH 上,
# 再啟動 uvicorn。掃描型 PDF 的 OCR 依賴這兩個外部執行檔。
import os
import sys

# Per-OS fallbacks for hosts that have not put the two binaries on PATH. The
# Windows entries are where the LAN host installs them; on macOS and Linux both
# tools come from Homebrew, whose prefix differs by architecture and is missing
# from PATH whenever this launcher runs outside a login shell.
if sys.platform == "win32":
    _DEFAULT_OCR_DIRS = [
        r"C:\Program Files\Tesseract-OCR",
        r"C:\Users\Administrator\ocr-tools\poppler-26.02.0\Library\bin",
    ]
else:
    _DEFAULT_OCR_DIRS = ["/opt/homebrew/bin", "/usr/local/bin"]
# Allow overriding the OCR tool directories per host via OCR_TOOL_DIRS
# (os.pathsep-separated); fall back to the known local install paths.
_configured = os.environ.get("OCR_TOOL_DIRS")
_OCR_DIRS = [
    directory
    for directory in (_configured.split(os.pathsep) if _configured else _DEFAULT_OCR_DIRS)
    if directory
]
os.environ["PATH"] = os.pathsep.join(_OCR_DIRS) + os.pathsep + os.environ.get("PATH", "")

RELOAD_ENV_VAR = "BACKEND_RELOAD"
# Values that switch reload off. An empty value counts as off too: an operator who
# writes BACKEND_RELOAD= means "not for this host", and the safe direction for an
# ambiguous value is the non-reloading one.
_RELOAD_OFF_VALUES = frozenset({"", "0", "false", "no", "off"})


def reload_enabled() -> bool:
    """Whether uvicorn should watch for source changes, default on.

    On is the default because this file is the *local development* launcher: it
    binds 127.0.0.1 only, and a stale process is the failure this project has
    actually paid for twice. First a 422 storm, when the frontend sent a field the
    stale process's schema did not know and Pydantic's extra="forbid" rejected
    every save. Then a silent one: the requisition schemas do not set
    extra="forbid", so a stale process accepted saves and quietly discarded a new
    field, making a finished feature look unimplemented.

    Reload is never forced on: set BACKEND_RELOAD to a falsey value wherever it
    would be wrong. deploy/windows-lan/run-service.ps1 runs this same file as the
    SYSTEM autostart service and is the case to watch -- the reloader spawns a
    child process and restarts the app on every .py write. Reading the choice from
    the environment follows OCR_TOOL_DIRS above.
    """
    configured = os.environ.get(RELOAD_ENV_VAR)
    if configured is None:
        return True
    return configured.strip().casefold() not in _RELOAD_OFF_VALUES


import uvicorn  # noqa: E402

if __name__ == "__main__":
    # "app.main:app" is already the import-string form uvicorn requires before it
    # accepts reload=True; hand it the imported object instead and uvicorn logs
    # "You must pass the application as an import string" and exits.
    uvicorn.run("app.main:app", host="127.0.0.1", port=8010, reload=reload_enabled())
