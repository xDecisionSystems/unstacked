"""Update, delete, move and rename must never strand the tree or the index.

Every test here guards an invariant that a plausible implementation loses:
history surviving a rename or a delete, URLs surviving a title edit, the index
being clean after a failure, and the content folder still building on its own.
"""

import multiprocessing
import subprocess
import sys
from pathlib import Path

import pytest
from filelock import FileLock
from git import Repo
from git.index.base import IndexFile
from sqlmodel import Session

from app.content import (
    ContentConflict,
    ContentError,
    ContentExists,
    ContentLockTimeout,
    ContentMissing,
    ContentRepository,
)
from app.frontmatter_io import read_page
from app.models import User
from app.nav import read_navigation, set_order


@pytest.fixture
def content(app_env):
    _app, settings, _admin, _token = app_env
    return ContentRepository(settings)


@pytest.fixture
def actor(app_env):
    app, _settings, admin, _token = app_env
    with Session(app.state.engine) as session:
        yield session.get(User, admin.id)


@pytest.fixture
def docs(app_env) -> Path:
    _app, settings, _admin, _token = app_env
    return Path(settings.content_repo_path) / "docs"


@pytest.fixture
def repo(app_env) -> Repo:
    _app, settings, _admin, _token = app_env
    return Repo(settings.content_repo_path)


@pytest.fixture
def seeded(content, actor):
    """Two books, each with pages directly beneath it."""

    content.create_book("Ops", None, actor)
    content.create_book("Runbooks", None, actor)
    content.create_page("ops", "Overview", None, "overview body", ["intro"], False, actor)
    content.create_page(
        "runbooks", "Restart", None, "restart body", ["oncall"], False, actor
    )
    return content


def _build(settings) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "mkdocs", "build", "--strict"],
        cwd=settings.content_repo_path,
        check=False,
        capture_output=True,
        text=True,
    )


def _concurrent_update(settings, base_blob_sha: str, body: str, start, results) -> None:
    """Spawn-safe worker used to prove the file lock works across processes."""

    actor = User(
        username="concurrent-editor",
        email="concurrent@example.com",
        password_hash="not-used-by-content-service",
        display_name="Concurrent Editor",
    )
    start.wait(10)
    try:
        ContentRepository(settings).update_page(
            "ops/overview.md", body, [], False, actor, base_blob_sha=base_blob_sha
        )
    except ContentConflict:
        results.put("conflict")
    except Exception as exc:  # pragma: no cover - makes child failures visible
        results.put(f"error: {type(exc).__name__}: {exc}")
    else:
        results.put("committed")


def _hold_write_lock(lock_path: Path, ready, release) -> None:
    with FileLock(lock_path):
        ready.set()
        release.wait(10)


def test_update_replaces_the_body_without_losing_page_identity(seeded, docs, actor, repo):
    """A page's id and creation time outlive its body; only Git records who edited."""

    before = read_page(docs / "ops" / "overview.md").metadata
    seeded.update_page(
        "ops/overview.md",
        "rewritten body",
        ["intro", "ops"],
        True,
        actor,
        base_blob_sha=seeded.page_blob_sha("ops/overview.md"),
    )
    after = read_page(docs / "ops" / "overview.md").metadata

    assert "rewritten body" in (docs / "ops" / "overview.md").read_text(encoding="utf-8")
    assert after["id"] == before["id"]
    assert after["created_at"] == before["created_at"]
    assert after["title"] == before["title"]
    assert after["tags"] == ["intro", "ops"]
    assert after["draft"] is True
    assert after["updated_at"] != before["updated_at"]
    # The front-matter author stays the creator; the commit names the editor.
    assert after["author"] == before["author"]
    assert not repo.is_dirty()
    assert repo.head.commit.author.email == actor.email
    assert repo.head.commit.message.startswith("Update page: ops/overview.md")


def test_update_rejects_a_page_that_is_not_in_the_tree(seeded, actor):
    with pytest.raises(ContentMissing):
        seeded.update_page("ops/missing.md", "body", [], False, actor, base_blob_sha="0" * 40)


def test_concurrent_cross_process_saves_commit_once_and_conflict_once(seeded, app_env, repo):
    """The stale writer must recheck its base after acquiring the file lock."""

    _app, settings, _admin, _token = app_env
    base_blob_sha = seeded.page_blob_sha("ops/overview.md")
    before = repo.head.commit.hexsha
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    workers = [
        context.Process(
            target=_concurrent_update,
            args=(settings, base_blob_sha, f"body from writer {number}", start, results),
        )
        for number in (1, 2)
    ]
    for worker in workers:
        worker.start()
    start.set()
    outcomes = sorted(results.get(timeout=15) for _ in workers)
    for worker in workers:
        worker.join(timeout=15)
        assert worker.exitcode == 0

    assert outcomes == ["committed", "conflict"]
    assert repo.head.commit.hexsha != before
    assert repo.head.commit.parents[0].hexsha == before
    assert not repo.is_dirty()


def test_write_lock_times_out_instead_of_waiting_forever(seeded, app_env, actor):
    _app, settings, _admin, _token = app_env
    short_wait_settings = settings.model_copy(update={"content_lock_timeout_seconds": 0.1})
    content = ContentRepository(short_wait_settings)
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    holder = context.Process(
        target=_hold_write_lock,
        args=(settings.content_lock_path, ready, release),
    )
    holder.start()
    assert ready.wait(10)
    try:
        with pytest.raises(ContentLockTimeout, match="busy"):
            content.update_page(
                "ops/overview.md",
                "never committed",
                [],
                False,
                actor,
                base_blob_sha=content.page_blob_sha("ops/overview.md"),
            )
    finally:
        release.set()
        holder.join(timeout=15)
    assert holder.exitcode == 0


def test_title_edit_leaves_the_page_where_its_links_point(seeded, docs, actor):
    """Retitling must not touch the slug, or every existing URL breaks."""

    seeded.set_page_title("ops/overview.md", "Operational Overview", actor)

    page = docs / "ops" / "overview.md"
    assert page.is_file()
    assert not (docs / "ops" / "operational-overview.md").exists()
    assert read_page(page).metadata["title"] == "Operational Overview"


def test_container_title_edit_changes_only_the_navigation_file(seeded, docs, actor, repo):
    """A book's display name lives in `.pages`; renaming the folder would move URLs."""

    seeded.set_container_title("ops", "Operations Handbook", actor)

    assert (docs / "ops").is_dir()
    assert read_navigation(docs / "ops" / ".pages").title == "Operations Handbook"
    changed = repo.head.commit.stats.files
    assert list(changed) == ["docs/ops/.pages"]


def test_deleted_page_keeps_its_history_and_can_be_restored(seeded, docs, actor):
    """Git standing in for a recycle bin only works if the delete is committed."""

    original = seeded.page_history("ops/overview.md")[0].sha
    seeded.delete_page("ops/overview.md", actor)

    assert not (docs / "ops" / "overview.md").exists()
    history = seeded.page_history("ops/overview.md")
    assert any("Delete page" in revision.message for revision in history)

    seeded.restore_page("ops/overview.md", original, actor)
    restored = docs / "ops" / "overview.md"
    assert restored.is_file()
    assert "overview body" in restored.read_text(encoding="utf-8")


def test_deleting_a_book_takes_its_pages_with_it(seeded, docs, actor, repo):

    seeded.delete_book("ops", actor)

    assert not (docs / "ops").exists()
    assert not repo.is_dirty()
    assert "Delete book: ops" in repo.head.commit.message
    # Every removed page is still reachable through history.
    assert (docs / "runbooks" / "restart.md").is_file()


def test_deleting_a_book_leaves_other_books_alone(seeded, docs, actor, repo):
    seeded.delete_book("runbooks", actor)

    assert not (docs / "runbooks").exists()
    assert (docs / "ops" / "overview.md").is_file()
    assert not repo.is_dirty()


def test_slug_rename_keeps_the_pages_history_reachable(seeded, actor):
    """`git log --follow` only bridges a rename when both halves land in one commit."""

    moved = seeded.move_page("ops/overview.md", None, "summary", actor)

    assert moved.path == "ops/summary.md"
    assert moved.previous_path == "ops/overview.md"
    messages = [revision.message for revision in seeded.page_history("ops/summary.md")]
    assert any("Move page" in message for message in messages)
    assert any("Create page" in message for message in messages), (
        "history stopped at the rename instead of following it"
    )


def test_a_moved_page_is_byte_identical_so_git_sees_a_rename(seeded, docs, actor):
    """Rewriting the file during a move would look like an unrelated delete plus create."""

    before = (docs / "ops" / "overview.md").read_bytes()
    seeded.move_page("ops/overview.md", "runbooks", None, actor)
    assert (docs / "runbooks" / "overview.md").read_bytes() == before


def test_renaming_a_book_carries_every_descendant_and_its_history(seeded, docs, actor, repo):
    moved = seeded.rename_book("ops", "operations", actor)

    assert moved.path == "operations"
    assert moved.previous_path == "ops"
    assert not (docs / "ops").exists()
    assert (docs / "runbooks" / "restart.md").is_file()
    assert not repo.is_dirty()
    messages = [
        revision.message for revision in seeded.page_history("runbooks/restart.md")
    ]
    assert any("Create page" in message for message in messages)


def test_renaming_a_book_keeps_its_pages(seeded, docs, actor):
    moved = seeded.rename_book("runbooks", "playbooks", actor)

    assert moved.path == "playbooks"
    assert (docs / "playbooks" / "restart.md").is_file()
    assert not (docs / "runbooks").exists()


def test_move_cannot_create_a_nested_parent(seeded, docs, actor):

    (docs / "ops" / "deeper").mkdir()
    with pytest.raises(ContentError, match="pages live directly in a book"):
        seeded.move_page("ops/overview.md", "ops/deeper", None, actor)
    assert (docs / "ops" / "overview.md").is_file()


def test_move_refuses_to_overwrite_an_existing_page(seeded, actor):
    seeded.create_page("runbooks", "Overview", None, "other body", [], False, actor)
    with pytest.raises(ContentExists):
        seeded.move_page("ops/overview.md", "runbooks", None, actor)


def test_move_refuses_a_missing_destination(seeded, actor):
    with pytest.raises(ContentMissing):
        seeded.move_page("ops/overview.md", "no-such-book", None, actor)


def test_explicit_navigation_order_follows_a_rename_and_a_delete(seeded, docs, actor):
    """Operators may pin an order; a stale entry there fails `mkdocs build --strict`."""

    navigation = docs / "ops" / ".pages"
    set_order(navigation, ["overview.md"])

    seeded.move_page("ops/overview.md", None, "summary", actor)
    assert read_navigation(navigation).entries == ["summary.md"]

    seeded.delete_page("ops/summary.md", actor)
    assert read_navigation(navigation).entries == []


def test_moving_into_a_pinned_parent_adds_the_page_to_its_order(seeded, docs, actor):
    """Without a wildcard an unlisted page would silently vanish from the nav."""

    navigation = docs / "runbooks" / ".pages"
    set_order(navigation, ["restart.md"])

    seeded.move_page("ops/overview.md", "runbooks", None, actor)
    assert read_navigation(navigation).entries == ["restart.md", "overview.md"]


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(
            lambda content, actor: content.update_page(
                "ops/overview.md",
                "clobbered",
                [],
                False,
                actor,
                base_blob_sha=content.page_blob_sha("ops/overview.md"),
            ),
            id="update",
        ),
        pytest.param(
            lambda content, actor: content.set_page_title("ops/overview.md", "Clobbered", actor),
            id="retitle",
        ),
        pytest.param(
            lambda content, actor: content.delete_page("ops/overview.md", actor),
            id="delete-page",
        ),
        pytest.param(
            lambda content, actor: content.move_page("ops/overview.md", "runbooks", "x", actor),
            id="move-page",
        ),
        pytest.param(
            lambda content, actor: content.delete_book("ops", actor),
            id="delete-book",
        ),
        pytest.param(
            lambda content, actor: content.rename_book("ops", "operations", actor),
            id="rename-book",
        ),
    ],
)
def test_a_failed_commit_restores_the_pre_operation_bytes(
    seeded, docs, repo, actor, monkeypatch, operation
):
    """A half-applied operation would leave an unbuildable tree and a dirty index."""

    before = {
        path.relative_to(docs).as_posix(): path.read_bytes()
        for path in sorted(docs.rglob("*"))
        if path.is_file()
    }
    head = repo.head.commit.hexsha

    def explode(*args, **kwargs):
        raise RuntimeError("injected commit failure")

    monkeypatch.setattr(seeded.git, "commit_paths", explode)
    with pytest.raises(RuntimeError, match="injected commit failure"):
        operation(seeded, actor)

    after = {
        path.relative_to(docs).as_posix(): path.read_bytes()
        for path in sorted(docs.rglob("*"))
        if path.is_file()
    }
    assert after == before
    assert repo.head.commit.hexsha == head
    assert not repo.is_dirty()
    assert repo.untracked_files == []


def test_a_failed_write_or_stage_restores_the_page_and_index(
    seeded, docs, actor, repo, monkeypatch
):
    """No pre-commit failure may leave a partially saved page or dirty index."""

    before_page = (docs / "ops" / "overview.md").read_bytes()
    before_index = (Path(repo.git_dir) / "index").read_bytes()

    def explode(*args, **kwargs):
        raise RuntimeError("injected write failure")

    monkeypatch.setattr("app.content.ConfinedTree.write_text", explode)
    with pytest.raises(RuntimeError, match="injected write failure"):
        seeded.update_page(
            "ops/overview.md",
            "clobbered",
            [],
            False,
            actor,
            base_blob_sha=seeded.page_blob_sha("ops/overview.md"),
        )
    assert (docs / "ops" / "overview.md").read_bytes() == before_page
    assert (Path(repo.git_dir) / "index").read_bytes() == before_index
    monkeypatch.undo()

    def stage_explode(self, *args, **kwargs):
        raise RuntimeError("injected stage failure")

    monkeypatch.setattr(IndexFile, "add", stage_explode)
    with pytest.raises(RuntimeError, match="injected stage failure"):
        seeded.update_page(
            "ops/overview.md",
            "clobbered",
            [],
            False,
            actor,
            base_blob_sha=seeded.page_blob_sha("ops/overview.md"),
        )
    assert (docs / "ops" / "overview.md").read_bytes() == before_page
    assert (Path(repo.git_dir) / "index").read_bytes() == before_index


def test_a_failed_container_retitle_restores_confined_navigation(
    seeded, docs, actor, repo, monkeypatch
):
    """A failed commit must restore `.pages` through its confined control-file API."""

    navigation = docs / "ops" / ".pages"
    before = navigation.read_bytes()
    before_index = (Path(repo.git_dir) / "index").read_bytes()

    def explode(*args, **kwargs):
        raise RuntimeError("injected commit failure")

    monkeypatch.setattr(seeded.git, "commit_paths", explode)
    with pytest.raises(RuntimeError, match="injected commit failure"):
        seeded.set_container_title("ops", "Never committed", actor)

    assert navigation.read_bytes() == before
    assert (Path(repo.git_dir) / "index").read_bytes() == before_index
    assert not repo.is_dirty()


def test_a_failed_commit_restores_the_preexisting_index(seeded, docs, actor, repo, monkeypatch):
    """The transaction must not erase an operator's already-staged work."""

    staged = docs / "ops" / "operator-staged.md"
    staged.write_text("operator work\n", encoding="utf-8")
    repo.index.add([staged.relative_to(repo.working_tree_dir).as_posix()])
    before_index = (Path(repo.git_dir) / "index").read_bytes()

    def explode(self, *args, **kwargs):
        raise RuntimeError("injected index commit failure")

    monkeypatch.setattr(IndexFile, "commit", explode)
    with pytest.raises(RuntimeError, match="injected index commit failure"):
        seeded.update_page(
            "ops/overview.md",
            "clobbered",
            [],
            False,
            actor,
            base_blob_sha=seeded.page_blob_sha("ops/overview.md"),
        )

    assert (Path(repo.git_dir) / "index").read_bytes() == before_index
    assert "ops/operator-staged.md" in repo.git.diff("--cached", "--name-only")
    assert "overview body" in (docs / "ops" / "overview.md").read_text(encoding="utf-8")


def test_the_content_folder_still_builds_after_a_full_lifecycle(app_env, seeded, docs, actor):
    """The whole point of the project: `content/` alone must stay a working site."""

    _app, settings, _admin, _token = app_env

    seeded.update_page(
        "ops/overview.md",
        "# Overview\n\nrewritten",
        ["intro"],
        False,
        actor,
        base_blob_sha=seeded.page_blob_sha("ops/overview.md"),
    )
    seeded.set_page_title("ops/overview.md", "Operational Overview", actor)
    seeded.set_container_title("ops", "Operations Handbook", actor)
    seeded.move_page("ops/overview.md", "runbooks", "summary", actor)
    seeded.rename_book("runbooks", "playbooks", actor)
    seeded.rename_book("ops", "operations", actor)
    seeded.delete_page("playbooks/restart.md", actor)

    result = _build(settings)
    assert result.returncode == 0, result.stdout + result.stderr
    site = Path(settings.content_repo_path) / "site"
    assert (site / "playbooks" / "summary" / "index.html").is_file()
    assert not (site / "ops").exists()


def test_the_content_folder_still_builds_after_a_book_is_deleted(app_env, seeded, actor):
    _app, settings, _admin, _token = app_env
    seeded.delete_book("ops", actor)

    result = _build(settings)
    assert result.returncode == 0, result.stdout + result.stderr


def test_emptying_a_book_still_leaves_a_buildable_tree(app_env, seeded, docs, actor):
    """Deleting the last page leaves a `.pages` with nothing left to order."""

    _app, settings, _admin, _token = app_env
    seeded.delete_page("runbooks/restart.md", actor)
    assert (docs / "runbooks" / ".pages").is_file()

    result = _build(settings)
    assert result.returncode == 0, result.stdout + result.stderr


def test_an_operators_untracked_file_does_not_block_deleting_a_book(seeded, docs, actor, repo):
    """`git rm` on a path Git never knew must not fail the whole delete."""

    (docs / "ops" / "scratch.txt").write_text("operator scratch\n", encoding="utf-8")
    seeded.delete_book("ops", actor)

    assert not (docs / "ops").exists()
    assert not repo.is_dirty()
    assert repo.untracked_files == []
