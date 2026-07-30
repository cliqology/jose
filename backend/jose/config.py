from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    jose_env: str = "development"
    jose_log_level: str = "INFO"
    jose_default_user_email: str = "scott@example.com"
    jose_scheduler_token: str = "replace-me"
    jose_cors_origins: str = "http://localhost:3000"
    database_url: str = (
        "postgresql+psycopg://jose:jose-local-password@localhost:5432/jose"
    )

    collector_timeout_seconds: float = 30.0
    collector_user_agent: str = "JOSE-Collector/1.0"
    collector_max_redirects: int = 5
    collector_max_response_bytes: int = 20 * 1024 * 1024
    collector_retain_raw_payload: bool = True
    worker_poll_seconds: float = 2.0
    task_retry_base_seconds: float = 60.0
    task_retry_max_seconds: float = 1800.0
    task_retry_jitter_pct: float = 0.2
    task_stale_running_minutes: float = 30.0

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.jose_cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
