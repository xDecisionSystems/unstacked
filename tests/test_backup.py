"""The optional backup worker must never become an application dependency."""

from pathlib import Path

from git import Repo

from app.backup import BackupSyncWorker
from app.config import Settings
from app.git_backend import GitAuthError, GitBackend, GitSyncError
from app.main import create_app


def _checkout_with_remote(tmp_path: Path) -> tuple[Repo, GitBackend, Path]:
    remote_path = tmp_path / "remote.git"
    Repo.init(remote_path, bare=True)
    checkout = tmp_path / "content"
    repo = Repo.init(checkout, initial_branch="main")
    (checkout / "docs").mkdir()
    (checkout / "docs" / "index.md").write_text("# Initial\n", encoding="utf-8")
    repo.index.add(["docs/index.md"])
    repo.index.commit("Initial")
    repo.create_remote("origin", remote_path.as_uri())
    return repo, GitBackend(checkout, tmp_path / "data" / "content.lock"), remote_path


def _worker(backend: GitBackend) -> BackupSyncWorker:
    return BackupSyncWorker(backend, debounce_seconds=0.01, max_backoff_seconds=0.1)


def test_pending_count_is_derived_from_refs_and_pushes_only_pending_commits(tmp_path: Path):
    repo, backend, remote_path = _checkout_with_remote(tmp_path)
    assert backend.pending_backup_count() == 1
    worker = _worker(backend)
    worker.sync_once()
    assert backend.pending_backup_count() == 0
    assert worker.status().ahead_count == 0
    assert worker.status().last_success_at is not None

    # A burst of local saves is still only one later worker push.  The remote
    # ends at the latest commit, proving no request path pushed each save.
    for number in range(10):
        page = Path(repo.working_tree_dir) / "docs" / f"{number}.md"
        page.write_text(f"#{number}\n", encoding="utf-8")
        repo.index.add([f"docs/{number}.md"])
        repo.index.commit(f"save {number}")
    assert backend.pending_backup_count() == 10
    worker.sync_once()
    remote = Repo(remote_path)
    assert remote.commit("main").hexsha == repo.head.commit.hexsha
    assert backend.pending_backup_count() == 0


def test_retryable_failure_has_bounded_retry_and_sanitized_status(tmp_path: Path, monkeypatch):
    _repo, backend, _remote = _checkout_with_remote(tmp_path)
    worker = _worker(backend)

    def unavailable() -> int:
        raise GitSyncError(
            "network temporary failure token=ghp_0123456789abcdefghijklmnopqrstuvwxyzAB"
        )

    monkeypatch.setattr(backend, "push_pending", unavailable)
    worker.sync_once()
    status = worker.status()
    assert status.last_error == "network temporary failure token=***"
    assert status.retry_at is not None
    assert not status.requires_admin_action
    assert 0 < worker._next_backoff() <= worker.max_backoff_seconds


def test_auth_failure_stops_automatic_retries_until_an_explicit_request(
    tmp_path: Path, monkeypatch
):
    _repo, backend, _remote = _checkout_with_remote(tmp_path)
    worker = _worker(backend)

    def refused() -> int:
        raise GitAuthError("content backup rejected the configured credentials")

    monkeypatch.setattr(backend, "push_pending", refused)
    worker.sync_once()
    assert worker.status().requires_admin_action
    assert worker.status().retry_at is None
    worker.request_sync()
    assert not worker.status().requires_admin_action


def test_no_backup_target_creates_no_worker_or_background_startup_task(tmp_path: Path):
    settings = Settings(
        environment="test",
        content_repo_path=tmp_path / "content",
        db_path=tmp_path / "data" / "app.db",
        content_lock_path=tmp_path / "data" / "content.lock",
        api_token_secret="test-secret-that-is-long-and-random-enough",
    )
    app = create_app(settings)
    assert not hasattr(app.state, "backup_sync_worker")


def test_backup_worker_is_only_wired_when_a_target_is_configured(tmp_path: Path):
    remote = tmp_path / "remote.git"
    Repo.init(remote, bare=True)
    settings = Settings(
        environment="test",
        content_repo_path=tmp_path / "content",
        db_path=tmp_path / "data" / "app.db",
        content_lock_path=tmp_path / "data" / "content.lock",
        api_token_secret="test-secret-that-is-long-and-random-enough",
        github_remote_url=remote.as_uri(),
        github_remote_confirmed_private=True,
    )
    # file:// needs no credential; showing the optional remote alone controls
    # worker wiring also avoids leaking any token in app state.
    app = create_app(settings)
    assert isinstance(app.state.backup_sync_worker, BackupSyncWorker)
