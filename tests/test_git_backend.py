"""Git is the only revision history this project keeps, so its edges matter."""

from pathlib import Path

import pytest
from git import Repo
from sqlmodel import Session

from app.content import ContentRepository
from app.git_backend import GitBackend, GitSyncError
from app.models import User
from tests.conftest import bearer


def _repo(settings) -> Repo:
    return Repo(settings.content_repo_path)


def _admin_page(client, headers) -> str:
    client.post("/api/ai/books", json={"title": "Ops"}, headers=headers)
    client.post(
        "/api/ai/books/ops/pages",
        json={"title": "Runbook", "markdown": "original body"},
        headers=headers,
    )
    return "ops/runbook.md"


def test_unrelated_staged_content_is_not_swept_into_a_users_commit(client, app_env):
    """An operator's staged file must not be committed under another author."""

    app, settings, _admin, token = app_env
    headers = bearer(token)
    repo = _repo(settings)

    stray = Path(settings.content_repo_path) / "docs" / "operator-scratch.md"
    stray.write_text("operator work in progress\n", encoding="utf-8")
    repo.index.add(["docs/operator-scratch.md"])

    _admin_page(client, headers)

    head = repo.head.commit
    committed = [item.path for item in head.tree.traverse() if item.type == "blob"]
    assert "docs/operator-scratch.md" not in committed
    # Their file itself is untouched on disk; only the staging was dropped.
    assert stray.read_text(encoding="utf-8") == "operator work in progress\n"


def test_commit_leaves_the_index_consistent_with_head(client, app_env):
    app, settings, _admin, token = app_env
    _admin_page(client, bearer(token))
    repo = _repo(settings)
    assert not repo.is_dirty()


def test_history_follows_a_rename(client, app_env):
    """`git log --follow` is what keeps history across a slug rename."""

    app, settings, _admin, token = app_env
    headers = bearer(token)
    path = _admin_page(client, headers)
    repo = _repo(settings)

    repo.git.mv(f"docs/{path}", "docs/ops/renamed.md")
    repo.index.commit("Rename page")

    content = ContentRepository(settings)
    history = content.page_history("ops/renamed.md")
    messages = [revision.message for revision in history]
    assert "Rename page" in messages
    assert any("Create page" in message for message in messages), (
        "history stopped at the rename instead of following it"
    )


def test_deleted_page_keeps_its_history_and_can_be_restored(client, app_env):
    """Git standing in for a recycle bin only works if deletes stay reachable."""

    app, settings, admin, token = app_env
    headers = bearer(token)
    path = _admin_page(client, headers)
    repo = _repo(settings)
    content = ContentRepository(settings)

    original_sha = content.page_history(path)[0].sha
    repo.git.rm(f"docs/{path}")
    repo.index.commit("Delete page")
    assert not (Path(settings.content_repo_path) / "docs" / path).exists()

    history = content.page_history(path)
    assert any("Delete page" in revision.message for revision in history)

    with Session(app.state.engine) as session:
        actor = session.get(User, admin.id)
        content.restore_page(path, original_sha, actor)

    restored = Path(settings.content_repo_path) / "docs" / path
    assert restored.is_file()
    assert "original body" in restored.read_text(encoding="utf-8")


def test_history_for_a_page_that_never_existed_is_not_found(app_env):
    from app.content import ContentMissing

    _app, settings, _admin, _token = app_env
    content = ContentRepository(settings)
    with pytest.raises(ContentMissing):
        content.page_history("ops/never-written.md")


def test_diff_against_a_revision_predating_the_page_shows_a_creation(client, app_env):
    app, settings, _admin, token = app_env
    headers = bearer(token)
    path = _admin_page(client, headers)
    content = ContentRepository(settings)
    repo = _repo(settings)

    root = list(repo.iter_commits())[-1].hexsha
    head = repo.head.commit.hexsha
    diff = content.page_diff(path, root, head)
    assert "original body" in diff


def _sync_repositories(tmp_path: Path) -> tuple[Repo, Repo, GitBackend]:
    """Create a content checkout and a second checkout sharing a bare backup."""

    remote_path = tmp_path / "remote.git"
    Repo.init(remote_path, bare=True)
    local_path = tmp_path / "local"
    local = Repo.init(local_path, initial_branch="main")
    (local_path / "docs").mkdir()
    (local_path / "docs" / "index.md").write_text("# Initial\n", encoding="utf-8")
    local.index.add(["docs/index.md"])
    local.index.commit("Initial")
    local.create_remote("origin", remote_path.as_uri())
    backend = GitBackend(local_path, tmp_path / "content.lock")
    backend.push()
    peer_path = tmp_path / "peer"
    peer = Repo.clone_from(remote_path.as_uri(), peer_path, branch="main")
    return local, peer, backend


def test_push_and_guarded_fast_forward_use_the_content_backup(tmp_path: Path):
    local, peer, backend = _sync_repositories(tmp_path)
    peer_file = Path(peer.working_tree_dir) / "docs" / "from-peer.md"
    peer_file.write_text("peer update\n", encoding="utf-8")
    peer.index.add(["docs/from-peer.md"])
    peer.index.commit("Peer update")
    peer.remotes.origin.push("main:main")

    assert backend.fetch_and_fast_forward() is True
    assert (Path(local.working_tree_dir) / "docs" / "from-peer.md").is_file()
    assert backend.fetch_and_fast_forward() is False


def test_fast_forward_refuses_dirty_or_divergent_content_history(tmp_path: Path):
    local, peer, backend = _sync_repositories(tmp_path)
    local_file = Path(local.working_tree_dir) / "docs" / "local.md"
    local_file.write_text("uncommitted operator work\n", encoding="utf-8")
    with pytest.raises(GitSyncError, match="local changes"):
        backend.fetch_and_fast_forward()
    local_file.unlink()

    peer_file = Path(peer.working_tree_dir) / "docs" / "peer.md"
    peer_file.write_text("peer update\n", encoding="utf-8")
    peer.index.add(["docs/peer.md"])
    peer.index.commit("Peer update")
    peer.remotes.origin.push("main:main")
    local_file.write_text("local update\n", encoding="utf-8")
    local.index.add(["docs/local.md"])
    local.index.commit("Local update")

    with pytest.raises(GitSyncError, match="diverged"):
        backend.fetch_and_fast_forward()
