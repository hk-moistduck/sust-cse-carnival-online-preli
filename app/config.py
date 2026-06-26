"""Environment-driven configuration."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "SupportOps Investigator"
    app_version: str = "1.0.0"
    environment: str = "development"
    log_level: str = "INFO"

    # Severity thresholds (currency-agnostic, treated as numeric units)
    large_amount_threshold: float = 100_000.0
    critical_amount_threshold: float = 500_000.0

    # Human review policy
    default_human_review: bool = True

    # Time window (seconds) for matching "recent" transaction to complaint
    default_time_window_seconds: int = 24 * 3600


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()