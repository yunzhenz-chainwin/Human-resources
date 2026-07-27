from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "TalentHub API"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    # Local-dev fallback only. Production MUST override DATABASE_URL (env / .env) with real
    # credentials: this default embeds a well-known dev password and must never reach prod.
    database_url: str = "postgresql+psycopg://talenthub:talenthub_dev_only@localhost:5432/talenthub"
    cors_origins: str = "http://localhost:5173,http://localhost:5174"
    resume_storage_path: str = "./storage/resumes"
    resume_storage_provider: str = "local"
    resume_quarantine_path: str = "./storage/quarantine"
    resume_max_bytes: int = 10 * 1024 * 1024
    candidate_photo_storage_path: str = "./storage/candidate-photos"
    candidate_photo_max_bytes: int = 5 * 1024 * 1024
    talent_retention_worker_enabled: bool = False
    talent_retention_worker_initial_delay_seconds: int = Field(default=30, ge=0, le=86_400)
    talent_retention_worker_interval_seconds: int = Field(
        default=24 * 60 * 60, ge=60, le=31 * 24 * 60 * 60
    )
    talent_retention_batch_size: int = Field(default=500, ge=1, le=5_000)
    talent_retention_max_batches_per_run: int = Field(default=20, ge=1, le=100)
    resume_scanner: str = "none"
    resume_scan_policy: str = "allow_unavailable"
    clamav_host: str = "localhost"
    clamav_port: int = 3310
    clamav_timeout: float = 10.0
    s3_bucket: str = ""
    s3_endpoint_url: str | None = None
    s3_region: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_secure: bool = True
    auth_secret_key: str = ""
    auth_access_minutes: int = 15
    auth_refresh_days: int = 7
    bootstrap_admin_username: str | None = None
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None
    bootstrap_admin_display_name: str = "System Administrator"
    # Gemini is opt-in. Keep disabled by default so local/dev environments use the
    # deterministic, auditable question generator when no key is configured.
    gemini_enabled: bool = False
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash"
    gemini_timeout_seconds: float = Field(default=20.0, ge=2.0, le=120.0)

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
