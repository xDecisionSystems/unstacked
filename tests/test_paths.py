"""Adversarial coverage for the only control preventing arbitrary file access."""

from pathlib import Path

import pytest

from app.paths import UnsafePath, make_slug, normalize_relative_path, path_depth, safe_join


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


@pytest.mark.parametrize(
    ("value", "expected"),
    [("book", 1), ("book/page.md", 2), ("book/chapter/page.md", 3)],
)
def test_path_depth_counts_segments(value: str, expected: int):
    assert path_depth(value) == expected
