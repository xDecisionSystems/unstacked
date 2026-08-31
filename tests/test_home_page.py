"""The reserved Home page (``docs/index.md``) and its widget-aware starter.

Covers the Phase 1+2 foundation from ``plans/plan_editable_widget_home.md``:
dedicated read/update operations with the same optimistic blob-SHA workflow
every other page uses, the bootstrap-vs-migrate-vs-leave-alone-if-edited
startup logic, and a real ``mkdocs build --strict`` against the new starter
content.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from git import Repo
from sqlmodel import Session

from app.config import Settings
from app.content import (
    HOME_LAYOUT_FILE,
    HOME_STARTER_WIDGETS,
    LEGACY_HOME_PAGE_PLACEHOLDER,
    ContentConflict,
    ContentError,
    ContentRepository,
)
from app.models import User


def _content_repository(tmp_path: Path) -> tuple[ContentRepository, Path]:
    root = tmp_path / "content"
    settings = Settings(
        environment="test",
        content_repo_path=root,
        db_path=tmp_path / "data" / "app.db",
        content_lock_path=tmp_path / "data" / "content.lock",
        api_token_secret="test-secret-that-is-long-and-random-enough",
    )
    content = ContentRepository(settings)
    content.initialize()
    return content, root


def _strict_build(content_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mkdocs", "build", "--strict"],
        cwd=content_root,
        check=False,
        capture_output=True,
        text=True,
    )


# --------------------------------------------------------------------------
# Bootstrap / migration
# --------------------------------------------------------------------------


def test_bootstrap_writes_widget_aware_starter_home_page(tmp_path: Path):
    content, root = _content_repository(tmp_path)
    metadata, body, _raw = content.read_home_page()

    assert metadata["title"] == "Home"
    assert metadata["widgets"] == HOME_STARTER_WIDGETS
    assert "Your featured books and pages." in body

    result = _strict_build(root)
    assert result.returncode == 0, result.stdout + result.stderr
    site = root / "site"
    assert (site / "index.html").is_file()
    # The static export shows only the rendered Markdown body -- no widget
    # content and no literal placeholder token, since v1 renders widgets in
    # a fixed slot the application adds, never inline in the Markdown itself.
    html = (site / "index.html").read_text(encoding="utf-8")
    assert "widgets:" not in html
    assert "type: featured" not in html


def test_existing_untouched_placeholder_is_migrated_once(tmp_path: Path):
    content, root = _content_repository(tmp_path)
    page = root / "docs" / "index.md"
    repo = Repo(root)

    # Simulate a repository bootstrapped before the widget-aware starter
    # existed: the bare placeholder, with no front matter at all.
    page.write_text(LEGACY_HOME_PAGE_PLACEHOLDER, encoding="utf-8")
    repo.index.add(["docs/index.md"])
    repo.index.commit("Simulate a pre-widget content repository")

    content.initialize()

    metadata, body, _raw = content.read_home_page()
    assert metadata["widgets"] == HOME_STARTER_WIDGETS
    assert metadata["title"] == "Home"
    assert "Your featured books and pages." in body
    assert repo.head.commit.message == "Migrate default home page to the widget-aware starter"

    # Re-running startup is a no-op once the migration already ran.
    seeded_head = repo.head.commit.hexsha
    content.initialize()
    assert repo.head.commit.hexsha == seeded_head
    assert not repo.is_dirty()


def test_hand_edited_home_page_is_never_touched_by_migration(tmp_path: Path):
    content, root = _content_repository(tmp_path)
    page = root / "docs" / "index.md"
    repo = Repo(root)

    # An administrator's hand-authored Home page, deliberately still equal in
    # every way *except* one byte to the legacy placeholder -- migration must
    # compare exact bytes, not merely "does it look like the old page".
    custom = "# Unstacked!\n"
    page.write_text(custom, encoding="utf-8")
    repo.index.add(["docs/index.md"])
    repo.index.commit("Administrator edit")
    head_before = repo.head.commit.hexsha

    content.initialize()

    assert page.read_text(encoding="utf-8") == custom
    assert repo.head.commit.hexsha == head_before
    assert not repo.is_dirty()


# --------------------------------------------------------------------------
# Read / update round trip
# --------------------------------------------------------------------------


@pytest.fixture
def content(app_env):
    _app, settings, _admin, _token = app_env
    return ContentRepository(settings)


@pytest.fixture
def actor(app_env):
    app, _settings, admin, _token = app_env
    with Session(app.state.engine) as session:
        yield session.get(User, admin.id)


def test_update_home_page_round_trip_including_unknown_widget(content, actor):
    _metadata, _body, _raw = content.read_home_page()
    base_sha = content.home_page_blob_sha()

    new_widgets = [
        {"id": "featured", "type": "featured", "config": {}},
        # An entry from a newer/unknown widget type must still round-trip
        # byte-for-byte: content.py never gatekeeps on the widget registry.
        {"id": "future-thing", "type": "not-yet-invented", "config": {"count": 3}},
    ]
    commit = content.update_home_page(
        "# Updated Home\n\nNew copy.\n",
        new_widgets,
        actor,
        base_blob_sha=base_sha,
        title="Updated Home",
    )
    assert commit

    metadata, body, _raw = content.read_home_page()
    # ``python-frontmatter`` trims a single trailing newline on serialization,
    # exactly as it already does for ordinary pages -- assert on content
    # rather than the exact trailing whitespace.
    assert body.strip() == "# Updated Home\n\nNew copy."
    assert metadata["title"] == "Updated Home"
    assert metadata["widgets"] == new_widgets


def test_update_home_page_keeps_title_when_not_supplied(content, actor):
    base_sha = content.home_page_blob_sha()
    content.update_home_page("# Body only\n", HOME_STARTER_WIDGETS, actor, base_blob_sha=base_sha)
    metadata, _body, _raw = content.read_home_page()
    assert metadata["title"] == "Home"


def test_update_home_page_detects_stale_blob_sha(content, actor):
    base_sha = content.home_page_blob_sha()
    content.update_home_page("# First\n", HOME_STARTER_WIDGETS, actor, base_blob_sha=base_sha)

    with pytest.raises(ContentConflict):
        content.update_home_page(
            "# Second, using the now-stale sha\n",
            HOME_STARTER_WIDGETS,
            actor,
            base_blob_sha=base_sha,
        )


@pytest.mark.parametrize(
    "widgets",
    [
        "not-a-list",
        ["not-a-dict"],
        [{"type": "featured", "config": {}}],  # missing id
        [{"id": "featured", "config": {}}],  # missing type
        [{"id": "featured", "type": "featured", "config": "not-a-mapping"}],
    ],
)
def test_update_home_page_rejects_malformed_widgets(content, actor, widgets):
    base_sha = content.home_page_blob_sha()
    with pytest.raises(ContentError):
        content.update_home_page("# Body\n", widgets, actor, base_blob_sha=base_sha)

    # A rejected update must never have written anything.
    metadata, _body, _raw = content.read_home_page()
    assert metadata["widgets"] == HOME_STARTER_WIDGETS


# --------------------------------------------------------------------------
# Grid-keyed curation storage (Phase 1 of plans/plan_multiple_featured_grids.md)
# --------------------------------------------------------------------------


def test_home_items_reads_legacy_flat_items_shape(content, actor):
    content.create_book("Alpha", "alpha", actor)
    content.create_book("Beta", "beta", actor)
    layout = content.root / HOME_LAYOUT_FILE
    layout.write_text(json.dumps({"items": ["alpha", "beta"]}), encoding="utf-8")

    # The old flat shape (no "grids" key) is treated as exactly one implicit
    # "featured" grid -- no migration script or write-on-read needed.
    assert content.home_items("featured") == ["alpha", "beta"]
    assert content.home_items() == ["alpha", "beta"]


def test_home_items_with_unknown_grid_id_returns_empty_list(content, actor):
    content.create_book("Alpha", "alpha", actor)
    content.feature_on_home("alpha", "featured", actor)

    assert content.home_items("some-grid-with-no-list-yet") == []


def test_feature_and_remove_from_home_never_perturb_another_grid(content, actor):
    content.create_book("Alpha", "alpha", actor)
    content.create_book("Beta", "beta", actor)
    content.create_book("Gamma", "gamma", actor)

    content.feature_on_home("beta", "news", actor)
    content.feature_on_home("alpha", "research", actor)
    content.feature_on_home("gamma", "research", actor)

    assert content.home_items("news") == ["beta"]
    assert content.home_items("research") == ["alpha", "gamma"]

    # Removing a target from one grid must leave the other grid's list intact.
    content.remove_from_home("alpha", "research", actor)
    assert content.home_items("research") == ["gamma"]
    assert content.home_items("news") == ["beta"]

    # Re-adding an already-present target to a grid is a no-op that leaves
    # every other grid's list untouched too.
    content.feature_on_home("beta", "news", actor)
    assert content.home_items("news") == ["beta"]
    assert content.home_items("research") == ["gamma"]


def test_home_items_union_dedupes_across_grids_in_first_seen_order(content, actor):
    content.create_book("Alpha", "alpha", actor)
    content.create_book("Beta", "beta", actor)

    content.feature_on_home("alpha", "research", actor)
    content.feature_on_home("beta", "news", actor)
    content.feature_on_home("alpha", "news", actor)  # already seen via "research"

    assert content.home_items() == ["alpha", "beta"]


def test_update_home_page_purges_deleted_featured_grids_curated_list(content, actor):
    content.create_book("Alpha", "alpha", actor)
    content.create_book("Beta", "beta", actor)

    two_grids = [
        {"id": "research", "type": "featured", "config": {}},
        {"id": "news", "type": "featured", "config": {}},
    ]
    base_sha = content.home_page_blob_sha()
    content.update_home_page("# Home\n", two_grids, actor, base_blob_sha=base_sha)

    content.feature_on_home("alpha", "research", actor)
    content.feature_on_home("beta", "news", actor)
    assert content.home_items("research") == ["alpha"]
    assert content.home_items("news") == ["beta"]

    # Drop the "news" widget from the tray, keeping only "research".
    remaining_widget = [{"id": "research", "type": "featured", "config": {}}]
    base_sha = content.home_page_blob_sha()
    commit_sha = content.update_home_page(
        "# Home, edited\n", remaining_widget, actor, base_blob_sha=base_sha
    )

    # The purged grid's curated list is gone entirely (not merely emptied);
    # the surviving grid's list is untouched.
    assert content.home_items("news") == []
    layout = json.loads((content.root / HOME_LAYOUT_FILE).read_text(encoding="utf-8"))
    assert "news" not in layout["grids"]
    assert content.home_items("research") == ["alpha"]

    # Both files landed in the one commit.
    repo = Repo(content.root)
    commit = repo.commit(commit_sha)
    assert set(commit.stats.files) == {"docs/index.md", HOME_LAYOUT_FILE}


def test_update_home_page_commits_only_index_when_no_grid_is_removed(content, actor):
    content.create_book("Alpha", "alpha", actor)
    widgets = [{"id": "research", "type": "featured", "config": {}}]
    base_sha = content.home_page_blob_sha()
    content.update_home_page("# Home\n", widgets, actor, base_blob_sha=base_sha)
    content.feature_on_home("alpha", "research", actor)

    # A save that keeps the exact same set of featured widget ids (e.g. a
    # body-only edit) must not touch the home layout file at all.
    base_sha = content.home_page_blob_sha()
    commit_sha = content.update_home_page(
        "# Home, edited again\n", widgets, actor, base_blob_sha=base_sha
    )

    repo = Repo(content.root)
    commit = repo.commit(commit_sha)
    assert set(commit.stats.files) == {"docs/index.md"}
    assert content.home_items("research") == ["alpha"]
