from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="UNSTACKED_",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    content_repo_path: Path = Path("content")
    db_path: Path = Path("data/app.db")
    content_lock_path: Path = Path("data/content.lock")
    api_token_secret: str = "development-only-change-me"
    api_token_audience: str = "unstacked-ai"
    api_token_ttl_seconds: int = 3600
    login_attempts_per_minute: int = 5
    max_page_bytes: int = 2_000_000
    max_export_bytes: int = 50_000_000

    @model_validator(mode="after")
    def validate_production_secret(self) -> "Settings":
        if self.environment == "production" and (
            self.api_token_secret == "development-only-change-me"
            or len(self.api_token_secret.encode("utf-8")) < 32
        ):
            raise ValueError("UNSTACKED_API_TOKEN_SECRET must be at least 32 bytes in production")
        if self.api_token_ttl_seconds < 60:
            raise ValueError("API token lifetime must be at least 60 seconds")
        if self.login_attempts_per_minute < 1:
            raise ValueError("login rate limit must be positive")
        return self
