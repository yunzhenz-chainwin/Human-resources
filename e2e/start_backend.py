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
backend_path = str(BACKEND)
if backend_path in sys.path:
    sys.path.remove(backend_path)
sys.path.insert(0, backend_path)

from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.consent import ConsentNotice  # noqa: E402
from app.services.consent import activate_notice, active_notice, next_version  # noqa: E402
from app.services.initial_data import seed_initial_data  # noqa: E402
from app.services.matching_benchmark import seed_matching_benchmark  # noqa: E402

with SessionLocal() as database:
    seed_initial_data(database)
    seed_matching_benchmark(database)
    # Product behaviour: the public career page withholds its consent checkbox
    # until an administrator publishes a notice, and nothing seeds one -- the
    # privacy text is a deliberate human decision, not a shipped default. The
    # public-submission specs still need one, so publish a disposable notice
    # here rather than weakening that rule in the application itself.
    if active_notice(database) is None:
        notice = ConsentNotice(
            version=next_version(database),
            title="E2E 測試用招募個資告知事項",
            body="本告知事項僅供端對端測試使用，不含真實個人資料處理政策。",
            purpose_code="e2e-test",
            is_active=False,
        )
        database.add(notice)
        database.flush()
        activate_notice(database, notice)
        database.commit()

import uvicorn  # noqa: E402

uvicorn.run(app, host="127.0.0.1", port=8018, log_level="warning")
