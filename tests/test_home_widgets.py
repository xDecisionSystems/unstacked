"""The small, explicit widget registry that renders Home's ``featured`` slot.

Covers malformed/unknown-widget-type handling (never crash the page; never
silently drop an entry) and the ``featured`` widget's ACL filtering, which
must match ``home_items()``'s stored order and hide anything the viewing
user cannot read.
"""

import pytest
from sqlmodel import Session

from app.acl import AuthorizationContext
from app.auth import hash_password
from app.content import ContentError, ContentRepository, widget_entries_for_location
from app.home_widgets import (
    WidgetEntry,
    _render_featured,
    build_home_widgets,
    parse_widget_entries,
    render_widgets,
)
from app.models import Group, Permission, User, UserGroup

# --------------------------------------------------------------------------
# Parsing: malformed front matter must not crash, and nothing is dropped.
# --------------------------------------------------------------------------


def test_parse_accepts_a_well_formed_list():
    entries, errors = parse_widget_entries(
        [{"id": "featured", "type": "featured", "config": {}}]
    )
    assert errors == []
    assert entries == [WidgetEntry(id="featured", type="featured", config={})]


def test_parse_none_widgets_is_simply_empty():
    entries, errors = parse_widget_entries(None)
    assert entries == []
    assert errors == []


def test_parse_reports_non_list_without_raising():
    entries, errors = parse_widget_entries("not-a-list")
    assert entries == []
    assert len(errors) == 1
    assert "list" in errors[0].message


def test_parse_skips_only_the_malformed_entries():
    entries, errors = parse_widget_entries(
        [
            {"id": "featured", "type": "featured", "config": {}},
            "not-a-mapping",
            {"type": "featured", "config": {}},  # missing id
            {"id": "broken", "config": {}},  # missing type
            {"id": "broken-config", "type": "featured", "config": "nope"},
        ]
    )
    assert entries == [WidgetEntry(id="featured", type="featured", config={})]
    assert len(errors) == 4


def test_unknown_widget_type_is_preserved_by_parsing_but_not_rendered(app_env):
    """An unrecognized type is never dropped at the parsing stage.

    Dropping it here would make a round trip through ``update_home_page``
    lossy; that responsibility belongs to ``app.content``, which serializes
    back whatever the caller passes. This module only has to (a) keep the
    entry available and (b) refuse to render it.
    """

    app, _settings, admin, _token = app_env
    content = app.state.content
    entries, parse_errors = parse_widget_entries(
        [{"id": "mystery", "type": "not-yet-invented", "config": {"count": 3}}]
    )
    assert parse_errors == []
    assert entries == [WidgetEntry(id="mystery", type="not-yet-invented", config={"count": 3})]

    with Session(app.state.engine) as session:
        authorization = AuthorizationContext(session, session.get(User, admin.id))
        rendered, render_errors = render_widgets(entries, authorization, content)
    assert rendered == []
    assert len(render_errors) == 1
    assert render_errors[0].entry_id == "mystery"
    assert "unknown widget type" in render_errors[0].message


# --------------------------------------------------------------------------
# The ``featured`` widget: order and ACL filtering.
# --------------------------------------------------------------------------


def _reader(session: Session, email: str) -> User:
    user = User(
        username=email,
        email=email,
        password_hash=hash_password("widget test password is long enough"),
        display_name="Widget Reader",
        is_admin=False,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _grant(session: Session, user: User, prefix: str, *, read: bool, group_name: str) -> None:
    group = Group(name=group_name)
    session.add(group)
    session.flush()
    session.add(UserGroup(user_id=user.id, group_id=group.id))
    session.add(Permission(group_id=group.id, path_prefix=prefix, can_read=read, can_write=False))
    session.commit()


def test_featured_widget_filters_out_unreadable_targets_and_keeps_order(app_env):
    app, _settings, admin, _token = app_env
    content: ContentRepository = app.state.content
    content.create_book("Alpha", "alpha", admin)
    content.create_book("Beta", "beta", admin)
    content.feature_on_home("beta", "featured", admin)
    content.feature_on_home("alpha", "featured", admin)  # featured second; order must survive

    with Session(app.state.engine) as session:
        reader = _reader(session, "widget-reader@example.com")
        _grant(session, reader, "alpha", read=True, group_name="alpha-readers")
        # No grant at all for "beta" -- default deny.
        authorization = AuthorizationContext(session, reader)
        result = build_home_widgets(
            [{"id": "featured", "type": "featured", "config": {}}], authorization, content
        )

    assert result.errors == []
    assert len(result.rendered) == 1
    widget = result.rendered[0]
    assert widget.type == "featured"
    targets = [item["target"] for item in widget.data["items"]]
    # "beta" was featured first but the reader cannot read it, so only
    # "alpha" survives, and stored order is otherwise preserved.
    assert targets == ["alpha"]


def test_featured_widget_is_empty_for_a_reader_with_no_grants(app_env):
    app, _settings, admin, _token = app_env
    content: ContentRepository = app.state.content
    content.create_book("Alpha", "alpha", admin)
    content.feature_on_home("alpha", "featured", admin)

    with Session(app.state.engine) as session:
        reader = _reader(session, "no-grants@example.com")
        authorization = AuthorizationContext(session, reader)
        result = build_home_widgets(
            [{"id": "featured", "type": "featured", "config": {}}], authorization, content
        )

    assert result.errors == []
    assert result.rendered[0].data["items"] == []


def test_featured_widget_resolves_page_and_book_titles(app_env):
    app, _settings, admin, _token = app_env
    content: ContentRepository = app.state.content
    content.create_book("Handbook", "handbook", admin)
    content.create_page("handbook", "Leave Policy", "leave", "# Leave\n", [], False, admin)
    content.feature_on_home("handbook/leave.md", "featured", admin)
    content.feature_on_home("handbook", "featured", admin)

    with Session(app.state.engine) as session:
        authorization = AuthorizationContext(session, session.get(User, admin.id))
        result = build_home_widgets(
            [{"id": "featured", "type": "featured", "config": {}}], authorization, content
        )

    items = {item["target"]: item for item in result.rendered[0].data["items"]}
    assert items["handbook/leave"]["kind"] == "page"
    assert items["handbook/leave"]["title"] == "Leave Policy"
    assert items["handbook"]["kind"] == "book"
    assert items["handbook"]["title"] == "Handbook"


def test_data_cards_widget_reads_generic_cards_from_one_markdown_page(app_env):
    app, _settings, admin, _token = app_env
    content: ContentRepository = app.state.content
    content.create_book("Research", "research", admin)
    content.create_page("research", "Card data", "cards", "Internal data", [], True, admin)
    source = content.docs / "research" / "cards.md"
    raw = source.read_text(encoding="utf-8")
    source.write_text(
        raw.replace(
            "title: Card data\n",
            "title: Card data\nwidget:\n"
            "  title: Funded Projects & Grants\n"
            "  text: Current and recent work.\n"
            "  filters:\n"
            "    - id: research\n"
            "      label: Research\n"
            "cards:\n"
            "  - title: Human-AI Collaboration\n"
            "    text: Safer autonomous systems.\n"
            "    label: Office of Naval Research\n"
            "    date: Aug 2021\n"
            "    url: https://www.onr.navy.mil\n"
            "    target: research\n"
            "    filters: [research]\n",
        ),
        encoding="utf-8",
    )

    with Session(app.state.engine) as session:
        authorization = AuthorizationContext(session, session.get(User, admin.id))
        result = build_home_widgets(
            [
                {
                    "id": "projects",
                    "type": "data-cards",
                    "config": {"source": "research/cards.md"},
                }
            ],
            authorization,
            content,
        )

    assert result.errors == []
    assert result.rendered[0].data["items"] == [
        {
            "title": "Human-AI Collaboration",
            "text": "Safer autonomous systems.",
            "label": "Office of Naval Research",
            "date": "Aug 2021",
            "url": "https://www.onr.navy.mil",
            "target_url": "/books/research",
            "filters": ["research"],
        }
    ]
    assert result.rendered[0].data["text"] == "Current and recent work."
    assert result.rendered[0].title == "Funded Projects & Grants"
    assert result.rendered[0].data["filters"] == [{"id": "research", "label": "Research"}]


def test_text_widget_loads_an_authorized_markdown_page(app_env):
    app, _settings, admin, _token = app_env
    content: ContentRepository = app.state.content
    content.create_book("Research", "research", admin)
    content.create_page("research", "About", "about", "Reusable **text**.", [], False, admin)

    with Session(app.state.engine) as session:
        authorization = AuthorizationContext(session, session.get(User, admin.id))
        result = build_home_widgets(
            [{"id": "about", "type": "text", "config": {"source": "research/about.md"}}],
            authorization,
            content,
        )

    assert result.errors == []
    assert result.rendered[0].data == {
        "source": "research/about.md",
        "markdown": "Reusable **text**.",
    }


def test_switching_cards_uses_the_data_card_source_format(app_env):
    app, _settings, admin, _token = app_env
    content: ContentRepository = app.state.content
    content.create_book("Research", "research", admin)
    content.create_page("research", "Cards", "cards", "", [], False, admin)
    source = content.docs / "research" / "cards.md"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "title: Cards\n",
            "title: Cards\nwidget:\n  filters:\n    - id: graduate\n      label: Graduate\n"
            "cards:\n  - title: Research role\n    filters: [graduate]\n",
        ),
        encoding="utf-8",
    )
    with Session(app.state.engine) as session:
        authorization = AuthorizationContext(session, session.get(User, admin.id))
        result = build_home_widgets(
            [
                {
                    "id": "hiring",
                    "type": "switching-cards",
                    "config": {"source": "research/cards.md"},
                }
            ],
            authorization,
            content,
        )
    assert result.errors == []
    assert result.rendered[0].type == "switching-cards"
    assert result.rendered[0].data["filters"] == [{"id": "graduate", "label": "Graduate"}]


def test_horizontal_rule_widget_needs_no_source_page(app_env):
    app, _settings, admin, _token = app_env
    with Session(app.state.engine) as session:
        authorization = AuthorizationContext(session, session.get(User, admin.id))
        result = build_home_widgets(
            [{"id": "break", "type": "horizontal-rule", "config": {}}],
            authorization,
            app.state.content,
        )
    assert result.errors == []
    assert result.rendered[0].type == "horizontal-rule"


def test_source_widget_paths_are_generated_from_host_location():
    entries = widget_entries_for_location(
        "research/about.md",
        [
            {"id": "project-cards", "type": "data-cards", "config": {"source": "ignored.md"}},
            {"id": "divider", "type": "horizontal-rule", "config": {}},
        ],
    )

    assert entries[0]["config"]["source"] == "research/widget-sources/about-project-cards.md"
    assert entries[1]["config"] == {}


def test_source_widget_ids_must_produce_unique_filenames():
    with pytest.raises(ContentError, match="unique source filenames"):
        widget_entries_for_location(
            "research",
            [
                {"id": "Student opportunities", "type": "text", "config": {}},
                {"id": "student-opportunities", "type": "text", "config": {}},
            ],
        )


def test_generated_widget_source_is_created_with_a_commented_example(app_env):
    app, _settings, admin, _token = app_env
    content = app.state.content
    widgets = widget_entries_for_location(
        "research",
        [{"id": "projects", "type": "data-cards", "config": {}}],
    )

    created = content.ensure_widget_sources("research", widgets, admin)

    assert created == ["research/widget-sources/book-projects.md"]
    metadata, markdown, _raw = content.read_page(created[0])
    assert metadata["draft"] is True
    assert metadata["widget_source"] is True
    assert markdown.startswith("<!--")


def test_removing_a_widget_deletes_its_generated_source_rather_than_orphaning_it(app_env):
    """A removed widget's source must not linger to be resurrected later.

    Before this fix, ``ensure_widget_sources`` only ever created a missing
    file -- it never deleted one for a widget that was removed. Reusing the
    same id later found the old file already present and silently kept its
    stale content instead of a fresh starter template.
    """

    app, _settings, admin, _token = app_env
    content = app.state.content
    first_pass = widget_entries_for_location(
        "research", [{"id": "old", "type": "text", "config": {}}]
    )
    created = content.ensure_widget_sources("research", first_pass, admin)
    source_path = content.docs / created[0]
    source_path.write_text(
        source_path.read_text(encoding="utf-8") + "\nDistinctive prior content.\n",
        encoding="utf-8",
    )

    # The widget is removed: an empty layout references no sources at all.
    content.ensure_widget_sources("research", [], admin)
    assert not source_path.exists()

    # A later widget reusing the same id must start fresh, not inherit the
    # deleted file's old content (which could only happen if it were never
    # actually removed).
    second_pass = widget_entries_for_location(
        "research", [{"id": "old", "type": "text", "config": {}}]
    )
    recreated = content.ensure_widget_sources("research", second_pass, admin)
    assert recreated == created
    _metadata, markdown, _raw = content.read_page(recreated[0])
    assert "Distinctive prior content." not in markdown
    assert markdown.startswith("<!--")


def test_pruning_one_hosts_widgets_never_touches_a_sibling_hosts_widgets(app_env):
    """A book and one of its pages share the same widget-sources directory.

    A book's own widgets use the ``book-`` filename prefix; a page's use the
    page's own slug as the prefix (see ``_widget_source_dir_and_prefix``).
    Pruning must match only its own location's prefix -- glob'ing the shared
    directory without that filter would delete a sibling's widgets outright.
    """

    app, _settings, admin, _token = app_env
    content = app.state.content
    content.create_book("Research", "research", admin)
    content.create_page("research", "Overview", "overview", "Body", [], False, admin)

    book_widgets = content.ensure_widget_sources(
        "research",
        widget_entries_for_location("research", [{"id": "team", "type": "text", "config": {}}]),
        admin,
    )
    page_widgets = content.ensure_widget_sources(
        "research/overview.md",
        widget_entries_for_location(
            "research/overview.md", [{"id": "notice", "type": "text", "config": {}}]
        ),
        admin,
    )
    assert book_widgets == ["research/widget-sources/book-team.md"]
    assert page_widgets == ["research/widget-sources/overview-notice.md"]

    # Removing the page's own widget must not prune the book's.
    content.ensure_widget_sources("research/overview.md", [], admin)
    assert (content.docs / book_widgets[0]).exists()
    assert not (content.docs / page_widgets[0]).exists()


# --------------------------------------------------------------------------
# Multiple independent ``featured`` widget instances (per-widget grids).
# --------------------------------------------------------------------------


def test_multiple_featured_widgets_have_disjoint_grids_and_independent_acl(app_env):
    """Two ``featured`` widgets curate different grids, each with its own ACL view.

    Two widget instances (``research``/``news``) are each fed into their own
    ``feature_on_home`` grid; a reader with access to only some of the
    targets must see each grid's own subset, never a merged list and never
    an item leaking from a grid they cannot read.
    """

    app, _settings, admin, _token = app_env
    content: ContentRepository = app.state.content
    content.create_book("Alpha", "alpha", admin)
    content.create_book("Beta", "beta", admin)
    content.create_book("Gamma", "gamma", admin)
    content.feature_on_home("alpha", "research", admin)
    content.feature_on_home("beta", "research", admin)  # reader cannot read this one
    content.feature_on_home("gamma", "news", admin)

    with Session(app.state.engine) as session:
        reader = _reader(session, "grid-reader@example.com")
        _grant(session, reader, "alpha", read=True, group_name="alpha-readers")
        _grant(session, reader, "gamma", read=True, group_name="gamma-readers")
        # No grant for "beta" -- default deny.
        authorization = AuthorizationContext(session, reader)
        result = build_home_widgets(
            [
                {"id": "research", "type": "featured", "config": {"title": "Research"}},
                {"id": "news", "type": "featured", "config": {}},
            ],
            authorization,
            content,
        )

    assert result.errors == []
    research, news = result.rendered
    assert research.id == "research"
    assert research.title == "Research"
    assert [item["target"] for item in research.data["items"]] == ["alpha"]
    assert news.id == "news"
    assert news.title == ""
    assert [item["target"] for item in news.data["items"]] == ["gamma"]


def test_render_featured_title_is_taken_from_the_widget_instances_own_config(app_env):
    """``title`` comes from ``entry.config['title']``, not a shared constant.

    Unset, blank/whitespace-only, and non-string ``config['title']`` values
    all collapse to ``""`` (no header) rather than raising or falling back
    to a hardcoded "Featured".
    """

    app, _settings, admin, _token = app_env
    content: ContentRepository = app.state.content
    with Session(app.state.engine) as session:
        authorization = AuthorizationContext(session, session.get(User, admin.id))
        for config in ({}, {"title": ""}, {"title": "   "}, {"title": 42}):
            entry = WidgetEntry(id="featured", type="featured", config=config)
            widget = _render_featured(entry, authorization, content)
            assert widget.title == ""

        entry = WidgetEntry(id="featured", type="featured", config={"title": "  News  "})
        widget = _render_featured(entry, authorization, content)
        assert widget.title == "News"
