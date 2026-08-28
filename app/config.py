import os
import secrets
import stat
from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator
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
    # Every content mutation holds this repository-wide inter-process lock.
    # A finite timeout means a wedged peer cannot make a request wait forever.
    content_lock_timeout_seconds: float = 15.0
    # No default secret: a shared constant would let anyone forge a token for
    # any user.  Development and test generate a private random secret on
    # first use; production must supply one explicitly.
    api_token_secret: str | None = None
    api_token_secret_path: Path = Path("data/api_token_secret")
    api_token_audience: str = "unstacked-ai"
    api_token_ttl_seconds: int = 3600
    # Lifetime of a browser session cookie.  Signed and verified with the same
    # secret as API tokens but under a separate itsdangerous salt, so the two
    # token families cannot be swapped for one another.
    session_ttl_seconds: int = 43_200
    # --- Content backup remote (see GitBackend.configure_remote) -------------
    # The backup remote MUST be a private repository: a `content/` backup is a
    # complete, unfiltered copy of the wiki (drafts included) with no per-user
    # ACL, exactly like the static export.  Nothing here verifies that over the
    # network, so the operator affirms it explicitly and the remote is not
    # configured at all without that affirmation.
    github_remote_url: str | None = None
    github_remote_confirmed_private: bool = False
    # HTTPS transport: a fine-grained PAT scoped to this one repository with
    # only Contents read/write.  As with the token signing secret, prefer the
    # file path: a path in the environment is not a secret, whereas an inline
    # value is visible to anything that can read the process environment or a
    # container's configuration.  The path wins when both are set.
    github_token: str | None = None
    github_token_path: Path | None = None
    # SSH transport: a repository deploy key (write access to this repo only)
    # and the known_hosts entry its host key is pinned against.  Both are
    # required together; an unpinned host key is not accepted.
    github_ssh_key_path: Path | None = None
    github_ssh_known_hosts_path: Path | None = None
    # A backup is deliberately off the request path.  This is the shortest
    # delay before a worker coalesces a burst of local commits into one push.
    backup_sync_debounce_seconds: float = 10.0
    backup_sync_max_backoff_seconds: float = 300.0
    login_attempts_per_minute: int = 5
    # Number of trusted reverse proxies in front of the app.  0 means the
    # socket peer is the client; behind a proxy this must be set or every
    # client shares one rate-limit bucket.
    trusted_proxy_hops: int = 0
    max_page_bytes: int = 2_000_000
    max_export_bytes: int = 50_000_000
    # Search deliberately has its own smaller budgets.  A page may be valid
    # wiki content yet too expensive to inspect on every keystroke.
    max_search_query_chars: int = 500
    max_search_results: int = 100
    max_search_files: int = 1_000
    max_search_file_bytes: int = 512_000
    max_search_snippet_chars: int = 400
    search_timeout_seconds: float = 5.0
    max_rate_limit_keys: int = 10_000
    # Static exports intentionally live outside the content checkout: MkDocs'
    # output must never make the nested repository dirty, and the last good
    # artifact needs to survive a later failed build.
    static_export_path: Path = Path("data/static-export")
    mkdocs_executable: str = "mkdocs"
    static_export_timeout_seconds: int = 120
    static_export_output_limit_bytes: int = 65_536

    @field_validator(
        "github_token_path",
        "github_ssh_key_path",
        "github_ssh_known_hosts_path",
        mode="before",
    )
    @classmethod
    def blank_optional_path_is_unset(cls, value: object) -> object:
        """Treat an empty variable as "not configured", not as ``Path(".")``.

        Deployment templates commonly pass every variable through with an
        empty default; without this, an unused credential path would parse as
        the current directory and be read as if it were a secret file.
        """

        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def resolve_and_validate_secrets(self) -> "Settings":
        if self.api_token_ttl_seconds < 60:
            raise ValueError("API token lifetime must be at least 60 seconds")
        if self.session_ttl_seconds < 60:
            raise ValueError("session lifetime must be at least 60 seconds")
        if self.login_attempts_per_minute < 1:
            raise ValueError("login rate limit must be positive")
        if self.trusted_proxy_hops < 0:
            raise ValueError("trusted proxy hops cannot be negative")
        if not self.mkdocs_executable or "\x00" in self.mkdocs_executable:
            raise ValueError("mkdocs executable must be a non-empty command path")
        if self.static_export_timeout_seconds < 1:
            raise ValueError("static export timeout must be positive")
        if self.static_export_output_limit_bytes < 1:
            raise ValueError("static export output limit must be positive")
        if self.content_lock_timeout_seconds <= 0:
            raise ValueError("content lock timeout must be positive")
        if self.backup_sync_debounce_seconds <= 0:
            raise ValueError("backup sync debounce must be positive")
        if self.backup_sync_max_backoff_seconds < self.backup_sync_debounce_seconds:
            raise ValueError("backup sync maximum backoff must be at least the debounce")
        if self.max_search_query_chars < 1:
            raise ValueError("search query limit must be positive")
        if self.max_search_results < 1:
            raise ValueError("search result limit must be positive")
        if self.max_search_files < 1:
            raise ValueError("search file limit must be positive")
        if self.max_search_file_bytes < 1:
            raise ValueError("search file size limit must be positive")
        if self.max_search_snippet_chars < 20:
            raise ValueError("search snippet limit must be at least 20 characters")
        if self.search_timeout_seconds <= 0:
            raise ValueError("search timeout must be positive")

        # An unset variable and an empty one mean the same thing here: no
        # backup remote.  Normalizing once keeps every consumer from having to
        # tell `""` and `None` apart.  The values themselves are validated by
        # GitBackend.configure_remote, which raises errors that are already
        # scrubbed of credential material.
        self.github_remote_url = (self.github_remote_url or "").strip() or None
        self.github_token = (self.github_token or "").strip() or None

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
