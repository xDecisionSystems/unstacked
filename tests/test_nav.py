from pathlib import Path

import pytest

from app.nav import (
    NavigationError,
    create_navigation,
    read_navigation,
    remove_stale_entry,
    set_order,
    set_title,
)


def test_title_and_order_preserve_operator_added_supported_keys(tmp_path: Path):
    nav_path = tmp_path / ".pages"
    nav_path.write_text(
        (
            "title: Original\ncollapse: true\nnav:\n  - old.md\n  - nested:\n"
            "      - child.md\ncustom-plugin-option:\n  visible: false\n"
        ),
        encoding="utf-8",
    )

    set_title(nav_path, "Renamed")
    set_order(nav_path, ["second.md", "first.md", "*"])

    navigation = read_navigation(nav_path)
    assert navigation.title == "Renamed"
    assert navigation.entries == ["second.md", "first.md", "*"]
    assert navigation.values["collapse"] is True
    assert navigation.values["custom-plugin-option"] == {"visible": False}


def test_malformed_navigation_is_rejected_without_clobbering_bytes(tmp_path: Path):
    nav_path = tmp_path / ".pages"
    original = "title: First\ntitle: Duplicate\nnav:\n  - page.md\n"
    nav_path.write_text(original, encoding="utf-8")

    with pytest.raises(NavigationError, match="duplicate key"):
        set_order(nav_path, ["page.md"])

    assert nav_path.read_text(encoding="utf-8") == original


def test_remove_stale_entry_preserves_globs_and_nested_navigation(tmp_path: Path):
    nav_path = tmp_path / ".pages"
    nav_path.write_text(
        """title: Book\nnav:\n  - deleted.md\n  - \"*\"\n  - nested:\n      - deleted.md\n""",
        encoding="utf-8",
    )

    remove_stale_entry(nav_path, "deleted.md")

    assert read_navigation(nav_path).entries == ["*", {"nested": ["deleted.md"]}]


def test_create_navigation_writes_the_default_container_order(tmp_path: Path):
    nav_path = tmp_path / ".pages"

    create_navigation(nav_path, "Engineering")

    assert read_navigation(nav_path).values == {"title": "Engineering", "nav": ["*"]}
