"""Round-trip tests for the explicitly confirmed manual restore path."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from git import Repo
from sqlmodel import Session

from app.auth import create_api_token, hash_password
from app.config import Settings
from app.git_backend import GitBackend, GitSyncError
from app.main import create_app
from app.manual_backup import ManualBackupService
from app.models import User


def _repositories(tmp_path: Path) -> tuple[Path, Path, ManualBackupService]:
    remote_path = tmp_path / "backup.git"
    Repo.init(remote_path, bare=True)
    local_path = tmp_path / "content"
    local = Repo.init(local_path, initial_branch="main")
    (local_path / "docs").mkdir()
    (local_path / "docs" / "index.md").write_text("# Initial\n", encoding="utf-8")
    local.index.add(["docs/index.md"])
    local.index.commit("Initial")
    local.create_remote("origin", remote_path.as_uri())
    backend = GitBackend(local_path, tmp_path / "content.lock")
    backend.push()
    return local_path, remote_path, ManualBackupService(backend)


def _commit_remote(remote_path: Path, tmp_path: Path, name: str = "remote.md") -> str:
    peer_path = tmp_path / f"peer-{name}"
    peer = Repo.clone_from(remote_path.as_uri(), peer_path, branch="main")
    (peer_path / "docs" / name).write_text("from backup\n", encoding="utf-8")
    peer.index.add([f"docs/{name}"])
    commit = peer.index.commit("Remote update")
    peer.remotes.origin.push("main:main")
    return commit.hexsha


def test_manual_backup_pushes_pending_revision_to_bare_remote(tmp_path: Path):
    local_path, remote_path, service = _repositories(tmp_path)
    (local_path / "docs" / "local.md").write_text("local\n", encoding="utf-8")
    local = Repo(local_path)
    local.index.add(["docs/local.md"])
    local.index.commit("Local update")

    assert service.backup_now() == 1
    recovered = Repo.clone_from(remote_path.as_uri(), tmp_path / "recovered", branch="main")
    assert (Path(recovered.working_tree_dir) / "docs" / "local.md").read_text() == "local\n"


def test_empty_destination_is_restored_only_from_configured_remote(tmp_path: Path):
    local_path, remote_path, service = _repositories(tmp_path)
    _commit_remote(remote_path, tmp_path)
    # The destination is a fixed service property, never an API supplied path.
    for child in local_path.iterdir():
        if child.is_dir():
            import shutil

            shutil.rmtree(child)
        else:
            child.unlink()

    result = service.restore()

    assert result.action == "cloned"
    assert (local_path / "docs" / "remote.md").read_text() == "from backup\n"


def test_clean_checkout_fast_forwards_from_bare_remote(tmp_path: Path):
    local_path, remote_path, service = _repositories(tmp_path)
    remote_sha = _commit_remote(remote_path, tmp_path)

    result = service.restore()

    assert result.action == "fast_forwarded"
    assert result.remote_revision == remote_sha
    assert (local_path / "docs" / "remote.md").is_file()


@pytest.mark.parametrize("make_dirty", [True, False])
def test_dirty_or_divergent_restore_requires_verified_recovery_then_confirmation(
    tmp_path: Path, make_dirty: bool
):
    local_path, remote_path, service = _repositories(tmp_path)
    _commit_remote(remote_path, tmp_path)
    local = Repo(local_path)
    if make_dirty:
        (local_path / "operator.txt").write_text("do not lose\n", encoding="utf-8")
    else:
        (local_path / "docs" / "local.md").write_text("local\n", encoding="utf-8")
        local.index.add(["docs/local.md"])
        local.index.commit("Local update")

    prepared = service.restore()

    assert prepared.action == "confirmation_required"
    assert prepared.recovery_verified is True
    assert prepared.confirmation_id
    assert (local_path / "docs" / "remote.md").exists() is False
    recovery_root = local_path.parent / ".unstacked-recovery"
    copies = list(recovery_root.iterdir())
    assert len(copies) == 1
    assert (copies[0] / ".git").is_dir()
    assert (copies[0] / "operator.txt").exists() is make_dirty

    restored = service.restore(confirmation_id=prepared.confirmation_id)

    assert restored.action == "replaced_after_recovery"
    assert (local_path / "docs" / "remote.md").read_text() == "from backup\n"
    assert (copies[0] / "docs" / "index.md").is_file()


def test_confirmation_cannot_replace_after_recovery_copy_changes(tmp_path: Path):
    local_path, remote_path, service = _repositories(tmp_path)
    _commit_remote(remote_path, tmp_path)
    (local_path / "operator.txt").write_text("do not lose\n", encoding="utf-8")
    prepared = service.restore()
    recovery = next((local_path.parent / ".unstacked-recovery").iterdir())
    (recovery / "operator.txt").write_text("tampered\n", encoding="utf-8")

    with pytest.raises(GitSyncError, match="recovery copy changed"):
        service.restore(confirmation_id=prepared.confirmation_id)

    assert (local_path / "operator.txt").read_text() == "do not lose\n"


def test_invalid_confirmation_never_replaces_content(tmp_path: Path):
    local_path, _remote_path, service = _repositories(tmp_path)

    with pytest.raises(GitSyncError, match="confirmation is invalid"):
        service.restore(confirmation_id="x" * 32)

    assert (local_path / "docs" / "index.md").is_file()


def test_manual_routes_exist_only_with_a_configured_remote_and_require_bearer_admin(tmp_path: Path):
    remote = tmp_path / "backup.git"
    Repo.init(remote, bare=True)
    settings = Settings(
        environment="test",
        content_repo_path=tmp_path / "content",
        db_path=tmp_path / "data" / "app.db",
        content_lock_path=tmp_path / "data" / "content.lock",
        static_export_path=tmp_path / "data" / "static-export",
        api_token_secret="test-secret-that-is-long-and-random-enough",
        github_remote_url=remote.as_uri(),
        github_remote_confirmed_private=True,
    )
    app = create_app(settings)
    with Session(app.state.engine) as session:
        user = User(
            username="operator",
            email="operator@example.com",
            password_hash=hash_password("correct horse battery staple"),
            display_name="Operator",
            is_admin=True,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        token = create_api_token(user, settings)
    with TestClient(app) as client:
        assert client.post("/api/admin/backup/now").status_code == 401
        response = client.post(
            "/api/admin/backup/now", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200
    assert response.json()["pushed_commits"] >= 0
