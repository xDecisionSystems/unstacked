"""Runtime backup configuration is transactional, secret-safe, and optional."""

import json
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from git import Repo
from sqlmodel import Session

from app import backup_config, backup_runtime
from app.auth import create_api_token, hash_password
from app.backup_config import GIT_REMOTE, BackupTarget
from app.config import Settings
from app.main import create_app
from app.models import Group, User
from app.web_auth import CSRF_HEADER_NAME
from tests.conftest import bearer

PASSWORD = "correct horse battery staple"


def _bare_remote(tmp_path: Path, name: str = "backup.git") -> Path:
    path = tmp_path / name
    Repo.init(path, bare=True)
    return path


def _payload(remote: Path) -> dict[str, object]:
    return {
        "type": "git-remote",
        "url": remote.as_uri(),
        "confirmed_private": True,
    }


def _settings(tmp_path: Path, **overrides) -> Settings:
    return Settings(
        environment="test",
        content_repo_path=tmp_path / "content",
        db_path=tmp_path / "data" / "app.db",
        content_lock_path=tmp_path / "data" / "content.lock",
        static_export_path=tmp_path / "data" / "static-export",
        backup_config_path=tmp_path / "data" / "backup_config.json",
        api_token_secret="test-secret-that-is-long-and-random-enough",
        **overrides,
    )


def _admin_token(app, settings: Settings) -> str:
    with Session(app.state.engine) as session:
        admin = User(
            username="admin",
            email="admin@example.com",
            password_hash=hash_password(PASSWORD),
            display_name="Admin",
            is_admin=True,
        )
        session.add(admin)
        session.commit()
        session.refresh(admin)
        return create_api_token(admin, settings)


def test_unconfigured_status_is_admin_only_and_has_no_runtime_services(app_env, client):
    app, _settings_value, _admin, token = app_env

    assert client.get("/api/admin/backup/config").status_code == 401
    response = client.get("/api/admin/backup/config", headers=bearer(token))

    assert response.status_code == 200
    assert response.json() == {
        "configured": False,
        "type": "none",
        "url": None,
        "confirmed_private": False,
        "requires_private_repository": False,
        "credential": "none",
        "source": "unset",
        "updated_at": None,
        "active": False,
        "ahead_count": None,
        "last_success_at": None,
        "last_error": None,
        "retry_at": None,
        "requires_admin_action": False,
    }
    assert not hasattr(app.state, "backup_sync_worker")


def test_authenticated_non_admin_cannot_read_backup_configuration(app_env, client):
    app, settings, _admin, _token = app_env
    with Session(app.state.engine) as session:
        user = User(
            username="reader",
            email="reader@example.com",
            password_hash=hash_password(PASSWORD),
            display_name="Reader",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        token = create_api_token(user, settings)

    assert client.get(
        "/api/admin/backup/config", headers=bearer(token)
    ).status_code == 403


def test_public_repository_is_allowed_without_groups_but_blocks_new_restricted_groups(
    app_env, client, tmp_path
):
    _app, _settings_value, _admin, token = app_env
    payload = _payload(_bare_remote(tmp_path))
    payload["confirmed_private"] = False

    configured = client.put("/api/admin/backup/config", json=payload, headers=bearer(token))
    assert configured.status_code == 200, configured.text
    assert configured.json()["confirmed_private"] is False
    assert configured.json()["requires_private_repository"] is False
    blocked = client.post(
        "/api/admin/groups", json={"name": "restricted"}, headers=bearer(token)
    )
    assert blocked.status_code == 409


def test_public_repository_is_refused_when_a_group_lacks_read_access(app_env, client, tmp_path):
    app, _settings_value, _admin, token = app_env
    with Session(app.state.engine) as session:
        session.add(Group(name="restricted"))
        session.commit()
    payload = _payload(_bare_remote(tmp_path))
    payload["confirmed_private"] = False

    response = client.put("/api/admin/backup/config", json=payload, headers=bearer(token))
    assert response.status_code == 409


def test_cookie_admin_needs_csrf_to_change_backup_configuration(app_env, client, tmp_path):
    _app, _settings_value, _admin, _token = app_env
    csrf = client.post(
        "/auth/login", json={"username": "admin", "password": PASSWORD}
    ).json()["csrf_token"]
    payload = _payload(_bare_remote(tmp_path))

    assert client.put("/api/admin/backup/config", json=payload).status_code == 403
    accepted = client.put(
        "/api/admin/backup/config",
        json=payload,
        headers={CSRF_HEADER_NAME: csrf},
    )
    assert accepted.status_code == 200, accepted.text


def test_configure_activates_services_and_clear_removes_the_managed_remote(
    app_env, client, tmp_path
):
    app, settings, _admin, token = app_env
    headers = bearer(token)
    remote = _bare_remote(tmp_path)

    # Manual routes do not exist until a target has been configured.
    assert client.post("/api/admin/backup/now", headers=headers).status_code == 404
    configured = client.put(
        "/api/admin/backup/config", json=_payload(remote), headers=headers
    )

    assert configured.status_code == 200, configured.text
    assert configured.json()["configured"] is True
    assert configured.json()["source"] == "file"
    assert configured.json()["active"] is True
    assert Repo(settings.content_repo_path).remotes.origin.url == remote.as_uri()
    record = settings.backup_config_path
    assert stat.S_IMODE(record.stat().st_mode) == 0o600
    assert client.post("/api/admin/backup/now", headers=headers).status_code == 200

    cleared = client.delete("/api/admin/backup/config", headers=headers)

    assert cleared.status_code == 200
    assert cleared.json()["configured"] is False
    assert cleared.json()["source"] == "file"
    assert cleared.json()["active"] is False
    assert not list(Repo(settings.content_repo_path).remotes)
    assert json.loads(record.read_text())["type"] == "none"
    # Dynamically mounted routes stay mounted, but no service is reachable.
    assert client.post("/api/admin/backup/now", headers=headers).status_code == 409


def test_inline_token_is_written_once_and_never_rendered_or_serialized(
    app_env, client, monkeypatch
):
    app, settings, _admin, token = app_env
    secret = "runtime-token-value-that-must-never-return"
    # A fake HTTPS host lets this test inspect credential handling without a
    # network dependency; reachability itself is covered with a missing file
    # remote below.
    monkeypatch.setattr(app.state.content.git, "test_remote", lambda: None)
    monkeypatch.setattr(backup_runtime, "activate", lambda _app: True)

    response = client.put(
        "/api/admin/backup/config",
        json={
            "url": "https://git.example.invalid/team/wiki.git",
            "confirmed_private": True,
            "token": secret,
        },
        headers=bearer(token),
    )

    assert response.status_code == 200, response.text
    managed = backup_config.managed_token_path(settings)
    assert managed.read_text() == secret
    assert stat.S_IMODE(managed.stat().st_mode) == 0o600
    assert secret not in response.text
    assert secret not in settings.backup_config_path.read_text()
    repository = Repo(settings.content_repo_path)
    assert secret not in (Path(repository.git_dir) / "config").read_text()
    helper = Path(repository.git_dir) / "unstacked-credential-helper"
    assert secret not in helper.read_text()
    reread = client.get("/api/admin/backup/config", headers=bearer(token))
    assert secret not in reread.text
    assert "token" not in reread.json()


def test_unreachable_target_is_not_saved_and_restores_exact_git_configuration(
    app_env, client, tmp_path
):
    app, settings, _admin, token = app_env
    headers = bearer(token)
    working = _bare_remote(tmp_path, "working.git")
    assert client.put(
        "/api/admin/backup/config", json=_payload(working), headers=headers
    ).status_code == 200

    repository = Repo(settings.content_repo_path)
    git_config = Path(repository.git_dir) / "config"
    before_git = git_config.read_bytes()
    before_record = settings.backup_config_path.read_bytes()
    missing = tmp_path / "does-not-exist.git"

    refused = client.put(
        "/api/admin/backup/config", json=_payload(missing), headers=headers
    )

    assert refused.status_code == 422
    assert "could not be reached" in refused.json()["detail"]
    assert missing.as_uri() not in refused.text
    assert git_config.read_bytes() == before_git
    assert settings.backup_config_path.read_bytes() == before_record
    assert repository.remotes.origin.url == working.as_uri()
    assert backup_runtime.is_active(app)


def test_clear_failure_restores_remote_record_and_running_services(
    app_env, client, tmp_path, monkeypatch
):
    app, settings, _admin, token = app_env
    headers = bearer(token)
    remote = _bare_remote(tmp_path)
    assert client.put(
        "/api/admin/backup/config", json=_payload(remote), headers=headers
    ).status_code == 200
    repository = Repo(settings.content_repo_path)
    git_config = Path(repository.git_dir) / "config"
    before_git = git_config.read_bytes()
    before_record = settings.backup_config_path.read_bytes()

    def fail_clear(_path):
        raise OSError("injected persistence failure")

    monkeypatch.setattr(backup_config, "clear", fail_clear)
    with pytest.raises(OSError, match="injected persistence failure"):
        client.delete("/api/admin/backup/config", headers=headers)

    assert git_config.read_bytes() == before_git
    assert settings.backup_config_path.read_bytes() == before_record
    assert repository.remotes.origin.url == remote.as_uri()
    assert backup_runtime.is_active(app)


def test_failed_first_save_preserves_an_operator_owned_origin(app_env, client, tmp_path):
    app, settings, _admin, token = app_env
    repository = Repo(settings.content_repo_path)
    operator_remote = _bare_remote(tmp_path, "operator.git")
    repository.create_remote("origin", operator_remote.as_uri())
    config_path = Path(repository.git_dir) / "config"
    before = config_path.read_bytes()

    refused = client.put(
        "/api/admin/backup/config",
        json={
            "url": "https://git.example.invalid/team/wiki.git",
            "confirmed_private": True,
            # HTTPS without a credential fails after the new URL is installed,
            # which exercises rollback of a genuinely partial configuration.
        },
        headers=bearer(token),
    )

    assert refused.status_code == 422
    assert config_path.read_bytes() == before
    assert repository.remotes.origin.url == operator_remote.as_uri()
    assert not settings.backup_config_path.exists()


def test_clear_tombstone_outweighs_environment_configuration_after_restart(tmp_path):
    remote = _bare_remote(tmp_path)
    settings = _settings(
        tmp_path,
        github_remote_url=remote.as_uri(),
        github_remote_confirmed_private=True,
    )
    app = create_app(settings)
    token = _admin_token(app, settings)

    with TestClient(app) as client:
        assert client.delete(
            "/api/admin/backup/config", headers=bearer(token)
        ).status_code == 200

    restarted = create_app(settings)
    assert backup_config.effective_target(settings).configured is False
    assert not hasattr(restarted.state, "backup_sync_worker")
    assert not list(Repo(settings.content_repo_path).remotes)


def test_saved_target_is_loaded_and_activated_after_restart(tmp_path):
    remote = _bare_remote(tmp_path)
    settings = _settings(tmp_path)
    app = create_app(settings)
    token = _admin_token(app, settings)

    with TestClient(app) as client:
        configured = client.put(
            "/api/admin/backup/config", json=_payload(remote), headers=bearer(token)
        )
        assert configured.status_code == 200, configured.text

    restarted = create_app(settings)
    assert backup_config.effective_target(settings).source == "file"
    assert backup_runtime.is_active(restarted)
    assert Repo(settings.content_repo_path).remotes.origin.url == remote.as_uri()


def test_broken_persisted_credential_never_prevents_application_startup(tmp_path):
    settings = _settings(tmp_path)
    missing_token = tmp_path / "missing-token"
    backup_config.save(
        settings.backup_config_path,
        BackupTarget(
            type=GIT_REMOTE,
            url="https://git.example.invalid/team/wiki.git",
            confirmed_private=True,
            token_path=missing_token,
        ),
    )

    app = create_app(settings)

    assert app.state.content.backup_config_error
    assert "token file is missing" in app.state.content.backup_config_error
    assert not hasattr(app.state, "backup_sync_worker")
    assert not list(Repo(settings.content_repo_path).remotes)
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}


def test_validation_error_does_not_echo_a_token(app_env, client):
    _app, _settings_value, _admin, token = app_env
    secret = "token-that-must-not-appear-in-validation"

    response = client.put(
        "/api/admin/backup/config",
        json={"url": "", "confirmed_private": True, "token": secret},
        headers=bearer(token),
    )

    assert response.status_code == 422
    assert secret not in response.text

    embedded = "credential-in-an-overlong-url"
    response = client.put(
        "/api/admin/backup/config",
        json={
            "url": f"https://{embedded}@git.example.invalid/" + "x" * 2100,
            "confirmed_private": True,
        },
        headers=bearer(token),
    )
    assert response.status_code == 422
    assert embedded not in response.text
