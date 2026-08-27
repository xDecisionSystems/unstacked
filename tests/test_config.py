"""The signing secret decides who can forge a token, so its defaults matter."""

from pathlib import Path

import pytest

from app.config import Settings


def _settings(tmp_path: Path, **overrides) -> Settings:
    base = {
        "content_repo_path": tmp_path / "content",
        "db_path": tmp_path / "data" / "app.db",
        "content_lock_path": tmp_path / "data" / "content.lock",
        "api_token_secret_path": tmp_path / "data" / "api_token_secret",
        "_env_file": None,
    }
    base.update(overrides)
    return Settings(**base)


def test_development_generates_a_private_secret_instead_of_a_shared_default(tmp_path: Path):
    settings = _settings(tmp_path, environment="development")
    assert settings.token_secret
    assert settings.token_secret != "development-only-change-me"
    assert len(settings.token_secret) >= 32


def test_generated_secret_is_persisted_and_owner_only(tmp_path: Path):
    settings = _settings(tmp_path, environment="development")
    secret_file = tmp_path / "data" / "api_token_secret"
    assert secret_file.read_text(encoding="utf-8").strip() == settings.token_secret
    assert secret_file.stat().st_mode & 0o077 == 0


def test_generated_secret_is_stable_across_restarts(tmp_path: Path):
    first = _settings(tmp_path, environment="development")
    second = _settings(tmp_path, environment="development")
    assert first.token_secret == second.token_secret


def test_production_refuses_to_start_without_an_explicit_secret(tmp_path: Path):
    with pytest.raises(ValueError, match="must be set in production"):
        _settings(tmp_path, environment="production")


def test_production_rejects_a_short_secret(tmp_path: Path):
    with pytest.raises(ValueError, match="at least 32 bytes"):
        _settings(tmp_path, environment="production", api_token_secret="too-short")


@pytest.mark.parametrize(
    "placeholder", ["development-only-change-me", "change-me", "changeme", "secret"]
)
def test_known_placeholder_secrets_are_rejected_in_every_environment(
    tmp_path: Path, placeholder: str
):
    with pytest.raises(ValueError, match="placeholder"):
        _settings(tmp_path, environment="development", api_token_secret=placeholder)


def test_production_accepts_a_real_secret(tmp_path: Path):
    secret = "x" * 48
    settings = _settings(tmp_path, environment="production", api_token_secret=secret)
    assert settings.token_secret == secret


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("api_token_ttl_seconds", 30, "at least 60 seconds"),
        ("login_attempts_per_minute", 0, "must be positive"),
        ("trusted_proxy_hops", -1, "cannot be negative"),
    ],
)
def test_invalid_limits_are_rejected(tmp_path: Path, field: str, value: int, message: str):
    with pytest.raises(ValueError, match=message):
        _settings(tmp_path, environment="development", **{field: value})
