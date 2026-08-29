"""Lifecycle mutations must reject files swapped for symlinks.

The content repository is trusted with a local Git checkout, but it must not
follow a path that another local process replaces after a user has selected a
page/container.  These cases are deliberately integration-level: they ensure
the lifecycle entry points keep using confined filesystem operations, rather
than merely testing a helper in isolation.
"""

import shutil
from pathlib import Path

import pytest
from sqlmodel import Session

from app.content import ContentError, ContentMissing, ContentRepository
from app.models import User
from app.paths import ConfinedTree, UnsafePath

_UNSAFE_MUTATION = (ContentError, ContentMissing, UnsafePath)


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
def seeded(content, actor):
    content.create_book("Ops", None, actor)
    content.create_page("ops", "Overview", None, "overview body", [], False, actor)
    return content


def _swap_for_symlink(path: Path, outside: Path) -> None:
    """Replace an existing container with a directory symlink."""

    shutil.rmtree(path)
    path.symlink_to(outside, target_is_directory=True)


def _swap_after_read(
    monkeypatch, container: Path, outside: Path, relative: str, *, method: str = "read_text"
) -> None:
    """Inject an ancestor substitution between confined read and write."""

    original_read = getattr(ConfinedTree, method)
    swapped = False

    def read_then_swap(self, candidate: str, *, max_bytes: int | None = None) -> str:
        nonlocal swapped
        result = original_read(self, candidate, max_bytes=max_bytes)
        if not swapped and candidate == relative:
            _swap_for_symlink(container, outside)
            swapped = True
        return result

    monkeypatch.setattr(ConfinedTree, method, read_then_swap)


def test_update_rejects_page_swapped_for_symlink(
    seeded, docs, actor, monkeypatch, tmp_path: Path
):
    """A save must not consume or replace an attacker-selected external page."""

    book = docs / "ops"
    version = seeded.page_blob_sha("ops/overview.md")
    outside = tmp_path / "outside-update"
    outside.mkdir()
    outside_page = outside / "overview.md"
    outside_page.write_text("outside update sentinel\n", encoding="utf-8")
    _swap_after_read(monkeypatch, book, outside, "ops/overview.md")

    with pytest.raises(_UNSAFE_MUTATION):
        seeded.update_page(
            "ops/overview.md", "new body", [], False, actor, base_blob_sha=version
        )

    assert outside_page.read_text(encoding="utf-8") == "outside update sentinel\n"
    assert book.is_symlink()


def test_page_retitle_rejects_page_swapped_for_symlink(
    seeded, docs, actor, monkeypatch, tmp_path: Path
):
    """Retitling must have the same confinement guarantee as saving."""

    book = docs / "ops"
    outside = tmp_path / "outside-retitle"
    outside.mkdir()
    outside_page = outside / "overview.md"
    outside_page.write_text("outside retitle sentinel\n", encoding="utf-8")
    _swap_after_read(monkeypatch, book, outside, "ops/overview.md")

    with pytest.raises(_UNSAFE_MUTATION):
        seeded.set_page_title("ops/overview.md", "Attacker selected title", actor)

    assert outside_page.read_text(encoding="utf-8") == "outside retitle sentinel\n"
    assert book.is_symlink()


def test_container_retitle_rejects_navigation_swapped_for_symlink(
    seeded, docs, actor, monkeypatch, tmp_path: Path
):
    """A container title edit must never rewrite an external `.pages` file."""

    book = docs / "ops"
    outside = tmp_path / "outside-navigation"
    outside.mkdir()
    outside_navigation = outside / ".pages"
    outside_navigation.write_text(
        "title: outside navigation sentinel\nnav:\n  - '*'\n", encoding="utf-8"
    )
    _swap_after_read(monkeypatch, book, outside, "ops", method="read_internal_text")

    with pytest.raises(_UNSAFE_MUTATION) as raised:
        seeded.set_container_title("ops", "Attacker selected title", actor)

    assert outside_navigation.read_text(encoding="utf-8") == (
        "title: outside navigation sentinel\nnav:\n  - '*'\n"
    )
    assert book.is_symlink(), repr(raised.value)


def test_delete_rejects_page_parent_swapped_after_confined_snapshot(
    seeded, docs, actor, monkeypatch, tmp_path: Path
):
    """Delete must not follow a parent swapped after it saved rollback bytes."""

    book = docs / "ops"
    outside = tmp_path / "outside-delete"
    outside.mkdir()
    outside_page = outside / "overview.md"
    outside_page.write_text("outside delete sentinel\n", encoding="utf-8")
    _swap_after_read(monkeypatch, book, outside, "ops/overview.md", method="read_bytes")

    with pytest.raises(_UNSAFE_MUTATION):
        seeded.delete_page("ops/overview.md", actor)

    assert outside_page.read_text(encoding="utf-8") == "outside delete sentinel\n"
    assert book.is_symlink()


def test_move_rejects_source_parent_swapped_after_confined_snapshot(
    seeded, docs, actor, monkeypatch, tmp_path: Path
):
    """Move must not publish a source selected through a substituted parent."""

    book = docs / "ops"
    outside = tmp_path / "outside-move"
    outside.mkdir()
    outside_page = outside / "overview.md"
    outside_page.write_text("outside move sentinel\n", encoding="utf-8")
    _swap_after_read(monkeypatch, book, outside, "ops/overview.md", method="read_bytes")

    with pytest.raises(_UNSAFE_MUTATION):
        seeded.move_page("ops/overview.md", "ops/runbooks", "summary", actor)

    assert outside_page.read_text(encoding="utf-8") == "outside move sentinel\n"


# --- Recursive container delete/rename ---------------------------------
#
# A book/chapter delete or rename walks and then mutates a whole subtree
# through ConfinedTree rather than a single file, so the race to close is an
# ancestor swapped in between the confined walk and the confined delete/rename
# that follows it, rather than between a single read and a single write.


def _swap_after_walk(monkeypatch, container: Path, outside: Path, relative: str) -> None:
    """Inject an ancestor substitution between the confined subtree walk and
    the delete/rename that consumes its result — the container-level
    counterpart to :func:`_swap_after_read` above."""

    original_walk = ConfinedTree.walk_files
    swapped = False

    def walk_then_swap(self, candidate: str) -> list[str]:
        nonlocal swapped
        result = original_walk(self, candidate)
        if not swapped and candidate == relative:
            _swap_for_symlink(container, outside)
            swapped = True
        return result

    monkeypatch.setattr(ConfinedTree, "walk_files", walk_then_swap)


@pytest.fixture
def seeded_chapter(content, actor):
    """A book with a chapter, for exercising the container-level races above."""

    content.create_book("Ops", None, actor)
    content.create_chapter("ops", "Runbooks", None, actor)
    content.create_page("ops/runbooks", "Restart", None, "restart body", [], False, actor)
    return content


def test_delete_chapter_rejects_book_swapped_after_confined_walk(
    seeded_chapter, docs, actor, monkeypatch, tmp_path: Path
):
    """A recursive delete must not follow a book substituted after its walk."""

    book = docs / "ops"
    outside = tmp_path / "outside-delete-chapter"
    outside.mkdir()
    (outside / "runbooks").mkdir()
    sentinel = outside / "runbooks" / "restart.md"
    sentinel.write_text("outside chapter delete sentinel\n", encoding="utf-8")
    _swap_after_walk(monkeypatch, book, outside, "ops/runbooks")

    with pytest.raises(_UNSAFE_MUTATION):
        seeded_chapter.delete_chapter("ops", "runbooks", actor)

    assert sentinel.read_text(encoding="utf-8") == "outside chapter delete sentinel\n"
    assert book.is_symlink()


def test_rename_chapter_rejects_book_swapped_after_confined_walk(
    seeded_chapter, docs, actor, monkeypatch, tmp_path: Path
):
    """A recursive rename must not follow a book substituted after its walk."""

    book = docs / "ops"
    outside = tmp_path / "outside-rename-chapter"
    outside.mkdir()
    (outside / "runbooks").mkdir()
    sentinel = outside / "runbooks" / "restart.md"
    sentinel.write_text("outside chapter rename sentinel\n", encoding="utf-8")
    _swap_after_walk(monkeypatch, book, outside, "ops/runbooks")

    with pytest.raises(_UNSAFE_MUTATION):
        seeded_chapter.rename_chapter("ops", "runbooks", "playbooks", actor)

    assert sentinel.read_text(encoding="utf-8") == "outside chapter rename sentinel\n"
    assert book.is_symlink()
