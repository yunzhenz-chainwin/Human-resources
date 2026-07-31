import pytest

from app.core.config import Settings
from app.services.security import validate_auth_secret


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
