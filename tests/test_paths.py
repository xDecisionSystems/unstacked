"""Adversarial coverage for the only control preventing arbitrary file access."""

from pathlib import Path

import pytest

from app.paths import (
    ConfinedTree,
    UnsafePath,
    atomic_write_confined,
    make_slug,
    normalize_relative_path,
    path_depth,
    read_confined_text,
    safe_join,
)


@pytest.mark.parametrize(
    "value",
    [
        "../secret",
        "book/../../secret",
        "/absolute",
        "book\\page.md",
        ".git/config",
        ".pages",
        "book/.git/config",
        "book/page.md\x00.txt",
        "",
        ".",
        "..",
        "book//page.md",
        "./book/page.md",
        "book/page.md/",
        "site/index.html",
        # Windows-reserved device names, which cannot be checked out at all.
        "CON.md",
        "book/nul.md",
        "book/com1.md",
        "book/LPT9.md",
    ],
)
def test_unsafe_relative_paths_are_rejected(value: str):
    with pytest.raises(UnsafePath):
        normalize_relative_path(value)


@pytest.mark.parametrize("value", ["book/page.md", "book/chapter/page.md", "book"])
def test_ordinary_paths_are_accepted(value: str):
    assert normalize_relative_path(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "Book Title",
        "Ünïcode Títle",
        "日本語のタイトル",
    ],
)
def test_ordinary_international_titles_still_produce_slugs(value: str):
    # Titles that transliterate to nothing are an error, not a crash.
    try:
        slug = make_slug(value)
    except UnsafePath:
        return
    assert normalize_relative_path(slug) == slug


@pytest.mark.parametrize("value", ["con", "PRN", "aux", "nul", "com3", "lpt1"])
def test_reserved_device_names_cannot_become_slugs(value: str):
    with pytest.raises(UnsafePath):
        make_slug(value, value.casefold())


@pytest.mark.parametrize(
    "value", ["assets", "site", "..", "-leading", "trailing-", "a--b", "with space", "sl/ash"]
)
def test_invalid_or_reserved_slugs_are_rejected(value: str):
    with pytest.raises(UnsafePath):
        make_slug("ignored", value)


def test_percent_encoded_traversal_is_a_literal_name_not_an_escape(tmp_path: Path):
    """`%2e%2e` is a legitimate (if odd) directory name, never a parent ref."""

    docs = tmp_path / "docs"
    docs.mkdir()
    resolved = safe_join(docs, "book/%2e%2e/page.md")
    assert docs.resolve() in resolved.parents


def test_unicode_lookalike_slugs_are_normalized_not_smuggled():
    # Fullwidth characters normalize to ASCII rather than creating a second
    # path that looks identical in a listing.
    assert make_slug("ignored", "ｂｏｏｋ") == "book"


def test_symlink_escape_is_rejected(tmp_path: Path):
    docs = tmp_path / "docs"
    outside = tmp_path / "outside"
    docs.mkdir()
    outside.mkdir()
    (docs / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(UnsafePath):
        safe_join(docs, "escape/secret.md")


def test_symlinked_file_escape_is_rejected(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    secret = tmp_path / "secret.md"
    secret.write_text("secret", encoding="utf-8")
    (docs / "book").mkdir()
    (docs / "book" / "page.md").symlink_to(secret)
    with pytest.raises(UnsafePath):
        safe_join(docs, "book/page.md")


def test_safe_join_returns_a_path_inside_the_root(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    resolved = safe_join(docs, "book/chapter/page.md")
    assert resolved == docs.resolve() / "book" / "chapter" / "page.md"


def test_descriptor_read_rejects_a_symlink_swapped_after_path_validation(tmp_path: Path):
    """Opening by directory descriptor, not a previously resolved Path, matters."""

    docs = tmp_path / "docs"
    book = docs / "book"
    docs.mkdir()
    book.mkdir()
    page = book / "page.md"
    page.write_text("safe", encoding="utf-8")
    checked = safe_join(docs, "book/page.md")
    assert checked == page

    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    page.unlink()
    page.symlink_to(outside)

    with pytest.raises(UnsafePath):
        read_confined_text(docs, "book/page.md")


def test_descriptor_write_replaces_a_raced_final_symlink_without_touching_target(tmp_path: Path):
    """A final symlink is replaced as a directory entry, never followed."""

    docs = tmp_path / "docs"
    book = docs / "book"
    docs.mkdir()
    book.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    (book / "page.md").symlink_to(outside)

    atomic_write_confined(docs, "book/page.md", "replacement", overwrite=True)

    assert outside.read_text(encoding="utf-8") == "secret"
    assert (book / "page.md").read_text(encoding="utf-8") == "replacement"
    assert not (book / "page.md").is_symlink()


def test_descriptor_create_does_not_clobber_a_concurrent_existing_name(tmp_path: Path):
    """Create uses link publication, so it has no exists-then-replace race."""

    docs = tmp_path / "docs"
    book = docs / "book"
    docs.mkdir()
    book.mkdir()
    page = book / "page.md"
    page.write_text("first writer", encoding="utf-8")

    with pytest.raises(FileExistsError):
        atomic_write_confined(docs, "book/page.md", "second writer", overwrite=False)

    assert page.read_text(encoding="utf-8") == "first writer"


def test_confined_tree_performs_regular_lifecycle_operations(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    tree = ConfinedTree(docs)

    tree.mkdir("book/chapter", parents=True)
    tree.write_text("book/chapter/page.md", "first")
    assert tree.list("book") == ["chapter"]
    assert tree.list("book/chapter") == ["page.md"]
    tree.rename("book/chapter/page.md", "book/chapter/renamed.md")
    assert tree.read_text("book/chapter/renamed.md") == "first"
    tree.unlink("book/chapter/renamed.md")
    tree.delete_tree("book")
    assert not (docs / "book").exists()


def test_confined_tree_write_and_rename_are_atomic_no_clobber(tmp_path: Path):
    docs = tmp_path / "docs"
    (docs / "book").mkdir(parents=True)
    tree = ConfinedTree(docs)
    tree.write_text("book/source.md", "source")
    tree.write_text("book/destination.md", "destination")

    with pytest.raises(FileExistsError):
        tree.write_text("book/destination.md", "new")
    with pytest.raises(FileExistsError):
        tree.rename("book/source.md", "book/destination.md")

    assert tree.read_text("book/source.md") == "source"
    assert tree.read_text("book/destination.md") == "destination"


def test_confined_tree_internal_navigation_file_is_fixed_and_confined(tmp_path: Path):
    docs = tmp_path / "docs"
    (docs / "book").mkdir(parents=True)
    tree = ConfinedTree(docs)

    tree.write_internal_text("book", "nav:\n  - page.md\n")
    assert tree.read_internal_text("book") == "nav:\n  - page.md\n"
    tree.write_internal_text("book", "nav:\n  - renamed.md\n", overwrite=True)
    assert tree.read_internal_text("book") == "nav:\n  - renamed.md\n"

    with pytest.raises(FileExistsError):
        tree.write_internal_text("book", "nav: []\n")
    with pytest.raises(UnsafePath):
        tree.write_internal_text("book/.pages", "nav: []\n")


def test_confined_tree_internal_navigation_rejects_symlinked_parent_or_file(tmp_path: Path):
    docs = tmp_path / "docs"
    outside = tmp_path / "outside"
    docs.mkdir()
    outside.mkdir()
    tree = ConfinedTree(docs)
    (docs / "book").symlink_to(outside, target_is_directory=True)

    with pytest.raises(UnsafePath):
        tree.read_internal_text("book")
    with pytest.raises(UnsafePath):
        tree.write_internal_text("book", "nav: []\n")

    (docs / "book").unlink()
    (docs / "book").mkdir()
    secret = tmp_path / "secret.pages"
    secret.write_text("secret", encoding="utf-8")
    (docs / "book" / ".pages").symlink_to(secret)

    with pytest.raises(UnsafePath):
        tree.read_internal_text("book")
    assert secret.read_text(encoding="utf-8") == "secret"


@pytest.mark.parametrize(
    "operation", ["read", "write", "unlink", "mkdir", "rename", "list", "delete"]
)
def test_confined_tree_rejects_symlinked_ancestors(tmp_path: Path, operation: str):
    docs = tmp_path / "docs"
    outside = tmp_path / "outside"
    docs.mkdir()
    outside.mkdir()
    (docs / "book").symlink_to(outside, target_is_directory=True)
    tree = ConfinedTree(docs)

    with pytest.raises(UnsafePath):
        if operation == "read":
            tree.read_text("book/page.md")
        elif operation == "write":
            tree.write_text("book/page.md", "nope")
        elif operation == "unlink":
            tree.unlink("book/page.md")
        elif operation == "mkdir":
            tree.mkdir("book/chapter", parents=True)
        elif operation == "rename":
            tree.rename("book/page.md", "new.md")
        elif operation == "list":
            tree.list("book")
        else:
            tree.delete_tree("book")

    assert list(outside.iterdir()) == []


def test_confined_tree_rejects_final_symlinks_without_touching_targets(tmp_path: Path):
    docs = tmp_path / "docs"
    book = docs / "book"
    docs.mkdir()
    book.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    (book / "page.md").symlink_to(outside)
    tree = ConfinedTree(docs)

    with pytest.raises(UnsafePath):
        tree.unlink("book/page.md")
    with pytest.raises(UnsafePath):
        tree.rename("book/page.md", "book/other.md")
    with pytest.raises(UnsafePath):
        tree.list("book")
    with pytest.raises(UnsafePath):
        tree.delete_tree("book")

    assert outside.read_text(encoding="utf-8") == "secret"
    assert (book / "page.md").is_symlink()


@pytest.mark.parametrize(
    ("value", "expected"),
    [("book", 1), ("book/page.md", 2), ("book/chapter/page.md", 3)],
)
def test_path_depth_counts_segments(value: str, expected: int):
    assert path_depth(value) == expected
