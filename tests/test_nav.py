from pathlib import Path

import pytest

from app.nav import (
    Navigation,
    NavigationError,
    create_navigation,
    parse_navigation,
    read_navigation,
    remove_stale_entry,
    serialize_navigation,
    set_order,
    set_title,
)


def test_pure_parse_and_serialize_do_not_require_a_navigation_path():
    navigation = parse_navigation(
        "title: Operations\nnav:\n  - overview.md\ncollapse: true\n",
        source="confined navigation",
    )

    assert navigation.values == {
        "title": "Operations",
        "nav": ["overview.md"],
        "collapse": True,
    }
    assert parse_navigation(serialize_navigation(navigation)).values == navigation.values


def test_pure_helpers_validate_and_identify_their_logical_source():
    with pytest.raises(NavigationError, match="confined navigation: duplicate key"):
        parse_navigation("title: One\ntitle: Two\n", source="confined navigation")

    with pytest.raises(NavigationError, match="serialized navigation: nav must be a list"):
        serialize_navigation(
            # Navigation is intentionally a transparent container so callers
            # cannot bypass validation simply by constructing it themselves.
            Navigation({"nav": "not-a-list"}),
            source="serialized navigation",
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
