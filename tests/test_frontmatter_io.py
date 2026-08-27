from pathlib import Path

from app.frontmatter_io import new_page, parse_page, read_page, write_page


def test_round_trip_preserves_unknown_front_matter_keys(tmp_path: Path):
    page = tmp_path / "runbook.md"
    page.write_text(
        """---
id: stable-id
title: Restart service
created_at: 2026-01-02T03:04:05+00:00
updated_at: 2026-01-03T03:04:05+00:00
author: Ada
tags: [operations, production]
draft: false
operator_setting:
  owner: platform
custom_number: 7
---
# Restart
""",
        encoding="utf-8",
    )

    document = read_page(page)
    assert document.metadata["tags"] == ["operations", "production"]
    assert document.metadata["operator_setting"] == {"owner": "platform"}
    write_page(page, document, metadata={"title": "Restart safely", "draft": True})

    round_tripped = read_page(page)
    assert round_tripped.metadata["title"] == "Restart safely"
    assert round_tripped.metadata["draft"] is True
    assert round_tripped.metadata["operator_setting"] == {"owner": "platform"}
    assert round_tripped.metadata["custom_number"] == 7
    assert round_tripped.content == "# Restart"


def test_missing_or_malformed_front_matter_has_sane_defaults(tmp_path: Path):
    plain = tmp_path / "plain-page.md"
    plain.write_text("# Plain page\n", encoding="utf-8")
    document = read_page(plain)
    assert document.metadata == {
        "id": None,
        "title": "plain-page",
        "created_at": None,
        "updated_at": None,
        "author": None,
        "tags": [],
        "draft": False,
    }
    assert document.content == "# Plain page"

    malformed = parse_page("---\ntitle: [not valid\n---\n# Damaged\n", default_title="Damaged")
    assert malformed.metadata["title"] == "Damaged"
    assert malformed.metadata["draft"] is False
    assert malformed.content.startswith("---\n")


def test_new_page_writes_complete_schema():
    serialized = new_page(
        "# New\n",
        {
            "id": "page-id",
            "title": "New page",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "author": "author@example.com",
            "tags": ["new"],
            "draft": False,
        },
    )
    document = parse_page(serialized)
    assert document.metadata["id"] == "page-id"
    assert document.metadata["title"] == "New page"
    assert document.content == "# New"
