"""End-to-end regression coverage for the guarded content-backup restore."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from git import Repo

from app import manual_backup
from app.git_backend import GitBackend, GitSyncError
from app.manual_backup import ManualBackupService


def _checkout_with_backup(tmp_path: Path) -> tuple[Path, Path, GitBackend]:
    """Create a multi-revision content checkout backed by a local bare repo."""

    remote_path = tmp_path / "backup.git"
    Repo.init(remote_path, bare=True)
    local_path = tmp_path / "content"
    local = Repo.init(local_path, initial_branch="main")
    (local_path / "docs").mkdir()
    (local_path / "docs" / "index.md").write_text("# Initial\n", encoding="utf-8")
    local.index.add(["docs/index.md"])
    local.index.commit("Initial")
    (local_path / "docs" / "guide.md").write_text("First revision\n", encoding="utf-8")
    local.index.add(["docs/guide.md"])
    local.index.commit("Add guide")
    local.create_remote("origin", remote_path.as_uri())
    backend = GitBackend(local_path, tmp_path / "content.lock")
    backend.push()
    return local_path, remote_path, backend


def _remote_commit(remote_path: Path, tmp_path: Path) -> str:
    peer_path = tmp_path / "peer"
    peer = Repo.clone_from(remote_path.as_uri(), peer_path, branch="main")
    (peer_path / "docs" / "guide.md").write_text("Remote revision\n", encoding="utf-8")
    (peer_path / "docs" / "remote-only.md").write_text("From remote\n", encoding="utf-8")
    peer.index.add(["docs/guide.md", "docs/remote-only.md"])
    revision = peer.index.commit("Remote revision")
    peer.remotes.origin.push("main:main")
    return revision.hexsha


def _tree(repo: Repo, revision: str = "main") -> str:
    return repo.git.ls_tree("-r", "--full-tree", revision)


def _history(repo: Repo, revision: str = "main") -> str:
    return repo.git.rev_list("--parents", revision)


def test_backup_round_trip_restores_a_removed_checkout_with_identical_history_and_tree(
    tmp_path: Path,
):
    local_path, remote_path, backend = _checkout_with_backup(tmp_path)
    expected_remote = Repo(remote_path)
    expected_head = expected_remote.commit("main").hexsha
    expected_history = _history(expected_remote)
    expected_tree = _tree(expected_remote)
    service = ManualBackupService(backend)

    # The local checkout is deliberately disposable: the remote is the only
    # source used to rebuild it, and no app/database state participates.
    shutil.rmtree(local_path)
    result = service.restore()

    restored = Repo(local_path)
    assert result.action == "cloned"
    assert restored.commit("main").hexsha == expected_head
    assert _history(restored) == expected_history
    assert _tree(restored) == expected_tree
    assert restored.git.show_ref("--verify", "refs/heads/main").split()[0] == expected_head
    assert (local_path / "docs" / "guide.md").read_text(encoding="utf-8") == "First revision\n"


def test_divergent_dirty_restore_preserves_verified_recovery_before_replacement(tmp_path: Path):
    local_path, remote_path, backend = _checkout_with_backup(tmp_path)
    remote_revision = _remote_commit(remote_path, tmp_path)
    local = Repo(local_path)
    (local_path / "docs" / "local-only.md").write_text("Local revision\n", encoding="utf-8")
    local.index.add(["docs/local-only.md"])
    local_revision = local.index.commit("Local revision").hexsha
    (local_path / "operator-note.txt").write_text("do not lose\n", encoding="utf-8")
    service = ManualBackupService(backend)

    prepared = service.restore()

    assert prepared.action == "confirmation_required"
    assert prepared.recovery_verified is True
    assert prepared.local_revision == local_revision
    assert prepared.remote_revision == remote_revision
    # Nothing is replaced until the caller presents the one-time confirmation.
    assert Repo(local_path).head.commit.hexsha == local_revision
    assert (local_path / "operator-note.txt").read_text(encoding="utf-8") == "do not lose\n"
    recovery = next((local_path.parent / ".unstacked-recovery").iterdir())
    recovered = Repo(recovery)
    assert recovered.head.commit.hexsha == local_revision
    assert (recovery / "operator-note.txt").read_text(encoding="utf-8") == "do not lose\n"
    assert (recovery / "docs" / "local-only.md").read_text(encoding="utf-8") == "Local revision\n"

    replaced = service.restore(confirmation_id=prepared.confirmation_id)

    restored = Repo(local_path)
    remote = Repo(remote_path)
    assert replaced.action == "replaced_after_recovery"
    assert restored.head.commit.hexsha == remote_revision
    assert _history(restored) == _history(remote)
    assert _tree(restored) == _tree(remote)
    assert not (local_path / "operator-note.txt").exists()
    # The independent recovery checkout remains available after replacement.
    assert recovered.head.commit.hexsha == local_revision


def test_interrupted_replacement_restores_the_original_checkout(tmp_path: Path, monkeypatch):
    local_path, remote_path, backend = _checkout_with_backup(tmp_path)
    _remote_commit(remote_path, tmp_path)
    local = Repo(local_path)
    (local_path / "docs" / "local-only.md").write_text("Local revision\n", encoding="utf-8")
    local.index.add(["docs/local-only.md"])
    local_revision = local.index.commit("Local revision").hexsha
    (local_path / "operator-note.txt").write_text("do not lose\n", encoding="utf-8")
    service = ManualBackupService(backend)
    prepared = service.restore()
    original_replace = manual_backup.os.replace

    def fail_staging_publish(source: str | Path, destination: str | Path) -> None:
        source_path, destination_path = Path(source), Path(destination)
        if (
            destination_path == local_path
            and source_path.name.startswith(".content.restore-")
            and not source_path.name.startswith(".content.restore-retired-")
        ):
            raise OSError("simulated replacement interruption")
        original_replace(source, destination)

    monkeypatch.setattr(manual_backup.os, "replace", fail_staging_publish)

    with pytest.raises(GitSyncError, match="replacement did not complete safely"):
        service.restore(confirmation_id=prepared.confirmation_id)

    restored_original = Repo(local_path)
    assert restored_original.head.commit.hexsha == local_revision
    assert (local_path / "operator-note.txt").read_text(encoding="utf-8") == "do not lose\n"
    assert (local_path / "docs" / "local-only.md").read_text(encoding="utf-8") == "Local revision\n"


def test_restore_transport_failure_redacts_remote_secret_material(tmp_path: Path):
    local_path = tmp_path / "content"
    local = Repo.init(local_path, initial_branch="main")
    (local_path / "docs").mkdir()
    (local_path / "docs" / "index.md").write_text("# Initial\n", encoding="utf-8")
    local.index.add(["docs/index.md"])
    local.index.commit("Initial")
    secret = "ghp_0123456789abcdefghijklmnopqrstuvwxyzAB"
    local.create_remote("origin", (tmp_path / f"missing-{secret}.git").as_uri())
    service = ManualBackupService(GitBackend(local_path, tmp_path / "content.lock"))

    with pytest.raises(GitSyncError) as raised:
        service.restore()

    assert str(raised.value) == "unable to fetch content backup"
    assert secret not in str(raised.value)
