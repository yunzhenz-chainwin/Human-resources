"""Start a disposable migrated SQLite backend for browser E2E tests."""

import os
import subprocess
import sys
from pathlib import Path

E2E_DIR = Path(__file__).resolve().parent
ROOT = E2E_DIR.parent
BACKEND = ROOT / "backend"
ARTIFACTS = E2E_DIR / ".artifacts"
DATABASE = ARTIFACTS / "talenthub-e2e.db"

ARTIFACTS.mkdir(exist_ok=True)
DATABASE.unlink(missing_ok=True)

os.environ.update(
    {
        "APP_ENV": "test",
        "DATABASE_URL": f"sqlite:///{DATABASE.as_posix()}",
        "AUTH_SECRET_KEY": "e2e-only-secret-key-with-at-least-32-characters",
        "BOOTSTRAP_ADMIN_USERNAME": "e2e-admin",
        "BOOTSTRAP_ADMIN_EMAIL": "e2e-admin@example.test",
        "BOOTSTRAP_ADMIN_PASSWORD": "E2E-Admin-Password-123!",
        "BOOTSTRAP_ADMIN_DISPLAY_NAME": "E2E Admin",
        "RESUME_STORAGE_PATH": str(ARTIFACTS / "resumes"),
        "RESUME_QUARANTINE_PATH": str(ARTIFACTS / "quarantine"),
        "RESUME_SCANNER": "none",
        "RESUME_SCAN_POLICY": "allow_unavailable",
        "CORS_ORIGINS": "http://127.0.0.1:4173,http://127.0.0.1:4174",
    }
)

subprocess.run(
    [sys.executable, "-m", "alembic", "upgrade", "head"],
    cwd=BACKEND,
    env=os.environ,
    check=True,
)
os.chdir(BACKEND)

from app.db.session import SessionLocal  # noqa: E402
from app.services.initial_data import seed_initial_data  # noqa: E402

with SessionLocal() as database:
    seed_initial_data(database)

import uvicorn  # noqa: E402

uvicorn.run("app.main:app", host="127.0.0.1", port=8018, log_level="warning")
