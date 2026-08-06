import os
import runpy
from pathlib import Path

import pytest
import uvicorn

from app.core.config import Settings
from app.services.security import validate_auth_secret

LAUNCHER = Path(__file__).resolve().parents[1] / "run_backend.py"


@pytest.mark.parametrize(
    "secret",
    [
        "",
        "too-short",
        "change-me-to-at-least-32-random-characters",
        "replace-with-at-least-32-random-characters",
    ],
)
def test_auth_secret_rejects_missing_short_or_public_values(secret: str) -> None:
    settings = Settings(app_env="test", auth_secret_key=secret)

    with pytest.raises(RuntimeError, match="AUTH_SECRET_KEY"):
        validate_auth_secret(settings)


def test_auth_secret_accepts_unique_32_byte_value() -> None:
    settings = Settings(app_env="test", auth_secret_key="unique-test-secret-that-is-over-32-bytes")

    assert validate_auth_secret(settings) == settings.auth_secret_key.encode()


def _keep_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Register PATH for restore: importing the launcher prepends the OCR tool dirs."""
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))


def test_dev_launcher_reloads_by_default_and_the_environment_can_turn_it_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale process serving old code has cost this project a full day twice."""

    _keep_path(monkeypatch)
    import run_backend

    monkeypatch.delenv(run_backend.RELOAD_ENV_VAR, raising=False)
    assert run_backend.reload_enabled() is True

    for value in ("0", "false", "FALSE", " off ", "no", ""):
        monkeypatch.setenv(run_backend.RELOAD_ENV_VAR, value)
        assert run_backend.reload_enabled() is False, value

    for value in ("1", "true", "on", "yes"):
        monkeypatch.setenv(run_backend.RELOAD_ENV_VAR, value)
        assert run_backend.reload_enabled() is True, value


def test_dev_launcher_hands_uvicorn_the_import_string_reload_requires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _keep_path(monkeypatch)
    monkeypatch.delenv("BACKEND_RELOAD", raising=False)
    captured: dict[str, object] = {}

    def fake_run(app: object, **kwargs: object) -> None:
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    runpy.run_path(str(LAUNCHER), run_name="__main__")

    # uvicorn logs "You must pass the application as an import string" and exits when
    # reload is on and the app is anything but a string, so this is load-bearing.
    assert captured["app"] == "app.main:app"
    assert isinstance(captured["app"], str)
    assert captured["reload"] is True
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8010
