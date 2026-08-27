"""Git is the only revision history this project keeps, so its edges matter."""

from pathlib import Path

import pytest
from git import Repo
from sqlmodel import Session

from app.content import ContentRepository
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
