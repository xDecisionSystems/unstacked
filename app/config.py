import os
import secrets
import stat
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MINIMUM_SECRET_BYTES = 32

# Values that must never sign a token.  Historic placeholder defaults are
# listed so an existing .env carrying one fails loudly instead of silently
# signing with a publicly known key.
REJECTED_SECRETS = frozenset(
    {
        "",
        "change-me",
        "changeme",
        "development-only-change-me",
        "secret",
    }
)


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
    # No default secret: a shared constant would let anyone forge a token for
    # any user.  Development and test generate a private random secret on
    # first use; production must supply one explicitly.
    api_token_secret: str | None = None
    api_token_secret_path: Path = Path("data/api_token_secret")
    api_token_audience: str = "unstacked-ai"
    api_token_ttl_seconds: int = 3600
    login_attempts_per_minute: int = 5
    # Number of trusted reverse proxies in front of the app.  0 means the
    # socket peer is the client; behind a proxy this must be set or every
    # client shares one rate-limit bucket.
    trusted_proxy_hops: int = 0
    max_page_bytes: int = 2_000_000
    max_export_bytes: int = 50_000_000
    max_rate_limit_keys: int = 10_000

    @model_validator(mode="after")
    def resolve_and_validate_secrets(self) -> "Settings":
        if self.api_token_ttl_seconds < 60:
            raise ValueError("API token lifetime must be at least 60 seconds")
        if self.login_attempts_per_minute < 1:
            raise ValueError("login rate limit must be positive")
        if self.trusted_proxy_hops < 0:
            raise ValueError("trusted proxy hops cannot be negative")

        secret = (self.api_token_secret or "").strip()
        if secret.casefold() in REJECTED_SECRETS:
            if secret:
                raise ValueError(
                    "UNSTACKED_API_TOKEN_SECRET is a known placeholder value; "
                    "generate a real secret"
                )
            secret = ""
        if self.environment == "production":
            if not secret:
                raise ValueError(
                    "UNSTACKED_API_TOKEN_SECRET must be set in production "
                    f"(at least {MINIMUM_SECRET_BYTES} bytes)"
                )
            if len(secret.encode("utf-8")) < MINIMUM_SECRET_BYTES:
                raise ValueError(
                    f"UNSTACKED_API_TOKEN_SECRET must be at least {MINIMUM_SECRET_BYTES} bytes"
                )
        elif not secret:
            secret = _load_or_create_secret(self.api_token_secret_path)
        self.api_token_secret = secret
        return self

    @property
    def token_secret(self) -> str:
        """The resolved signing secret; never empty after validation."""

        if not self.api_token_secret:
            raise RuntimeError("API token secret was not resolved")
        return self.api_token_secret


def _load_or_create_secret(path: Path) -> str:
    """Return a persistent per-installation secret for non-production use.

    Generated once and stored with owner-only permissions so restarts do not
    invalidate previously issued development tokens.
    """

    if path.is_file():
        existing = path.read_text(encoding="utf-8").strip()
        if len(existing.encode("utf-8")) >= MINIMUM_SECRET_BYTES:
            return existing
    path.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(48)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(secret)
    return secret
