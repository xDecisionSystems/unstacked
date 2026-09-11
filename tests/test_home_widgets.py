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
from app.content import (
    ContentError,
    ContentRepository,
    is_widget_source_path,
    widget_entries_for_location,
    widget_source_path,
)
from app.home_widgets import (
    WidgetEntry,
    _describe_target,
    _render_data_cards,
    _render_featured,
    _render_text,
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


@pytest.mark.parametrize(
    ("widget_type", "config", "message"),
    [
        ("text", {}, "requires a Markdown source page"),
        ("data-cards", {}, "requires a Markdown source page"),
        ("text", {"source": "/outside.md"}, "has an invalid source page"),
        ("data-cards", {"source": "research"}, "source must be a Markdown page"),
        ("text", {"source": "research/missing.md"}, "source page could not be read"),
    ],
)
def test_source_backed_widgets_report_invalid_source_configuration(
    app_env, widget_type, config, message
):
    """Bad widget-source configuration should be editor-visible, never fatal."""

    app, _settings, admin, _token = app_env
    with Session(app.state.engine) as session:
        authorization = AuthorizationContext(session, session.get(User, admin.id))
        result = build_home_widgets(
            [{"id": "broken", "type": widget_type, "config": config}],
            authorization,
            app.state.content,
        )
    assert result.rendered == []
    assert message in result.errors[0].message


@pytest.mark.parametrize(
    ("widget_block", "message"),
    [
        ("cards: not-a-list\n", "cards' front-matter list"),
        ("cards: []\nwidget: not-a-mapping\n", "widget' must be a mapping"),
        ("cards: []\nwidget:\n  title: 4\n", "widget title must be text"),
        ("cards: []\nwidget:\n  filters: not-a-list\n", "widget filters must be a list"),
        (
            "cards: []\nwidget:\n  filters:\n    - id: valid\n      label: 4\n",
            "widget filters need labels",
        ),
    ],
)
def test_data_card_widget_reports_invalid_source_schema(app_env, widget_block, message):
    app, _settings, admin, _token = app_env
    content = app.state.content
    content.create_book("Research", "research", admin)
    content.create_page("research", "Cards", "cards", "", [], False, admin)
    source = content.docs / "research" / "cards.md"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "title: Cards\n", "title: Cards\n" + widget_block
        ),
        encoding="utf-8",
    )
    with Session(app.state.engine) as session:
        authorization = AuthorizationContext(session, session.get(User, admin.id))
        result = build_home_widgets(
            [{"id": "cards", "type": "data-cards", "config": {"source": "research/cards.md"}}],
            authorization,
            content,
        )
    assert result.rendered == []
    assert message in result.errors[0].message


@pytest.mark.parametrize(
    ("card_block", "message"),
    [
        ("- text: Missing title\n", "each card needs a title"),
        ("- title: Example\n  text: 4\n", "card text values must be text"),
        ("- title: Example\n  filters: bad\n", "card filters must be a list"),
        ("- title: Example\n  filters: [missing]\n", "card uses unknown filter"),
        ("- title: Example\n  url: ftp://example.test\n", "card links must use http or https"),
        ("- title: Example\n  target: 4\n", "card targets must be book or page paths"),
    ],
)
def test_data_card_widget_reports_invalid_card_schema(app_env, card_block, message):
    app, _settings, admin, _token = app_env
    content = app.state.content
    content.create_book("Research", "research", admin)
    content.create_page("research", "Cards", "cards", "", [], False, admin)
    source = content.docs / "research" / "cards.md"
    block = "cards:\n" + card_block
    source.write_text(
        source.read_text(encoding="utf-8").replace("title: Cards\n", "title: Cards\n" + block),
        encoding="utf-8",
    )
    with Session(app.state.engine) as session:
        authorization = AuthorizationContext(session, session.get(User, admin.id))
        result = build_home_widgets(
            [{"id": "cards", "type": "data-cards", "config": {"source": "research/cards.md"}}],
            authorization,
            content,
        )
    assert result.rendered == []
    assert message in result.errors[0].message


def test_home_widget_source_inherits_home_read_permission(app_env):
    app, _settings, admin, _token = app_env
    content = app.state.content
    entries = widget_entries_for_location(
        "index.md", [{"id": "notice", "type": "text", "config": {}}]
    )
    source = content.ensure_widget_sources("index.md", entries, admin)[0]
    path = content.docs / source
    path.write_text(path.read_text(encoding="utf-8") + "\nVisible Home notice.\n", encoding="utf-8")

    with Session(app.state.engine) as session:
        authorization = AuthorizationContext(session, session.get(User, admin.id))
        result = build_home_widgets(entries, authorization, content)
    assert result.errors == []
    assert result.rendered[0].data["markdown"].endswith("Visible Home notice.")


def test_featured_target_fallbacks_remain_useful_when_content_was_removed(app_env):
    """A stale featured item should still receive a clear title while it is repaired."""

    app, _settings, _admin, _token = app_env
    content = app.state.content

    assert _describe_target(content, "research/missing-page.md")["title"] == "Missing Page"
    assert _describe_target(content, "missing-book")["title"] == "Missing Book"


@pytest.mark.parametrize(
    ("renderer", "source", "message"),
    [
        (_render_data_cards, "/outside.md", "invalid source page"),
        (_render_data_cards, "research/missing.md", "source page could not be read"),
        (_render_text, "/outside.md", "invalid source page"),
        (_render_text, "research/not-a-page", "source must be a Markdown page"),
    ],
)
def test_source_renderers_reject_invalid_sources_directly(app_env, renderer, source, message):
    """Each renderer must protect callers that use the registry helpers directly."""

    app, _settings, admin, _token = app_env
    content = app.state.content
    content.create_book("Research", "research", admin)
    entry = WidgetEntry(id="broken", type="text", config={"source": source})
    with Session(app.state.engine) as session:
        authorization = AuthorizationContext(session, session.get(User, admin.id))
        with pytest.raises(ValueError, match=message):
            renderer(entry, authorization, content)


@pytest.mark.parametrize(
    ("source_block", "message"),
    [
        ("cards:\n" + "".join(f"  - title: Card {item}\n" for item in range(101)), "at most 100"),
        (
            "cards: []\nwidget:\n  filters:\n"
            + "".join(f"    - id: filter-{item}\n      label: Filter\n" for item in range(21)),
            "at most 20 filters",
        ),
        ("cards: []\nwidget:\n  filters:\n    - invalid\n", "filter must be a mapping"),
        (
            "cards: []\nwidget:\n  filters:\n    - id: duplicate\n      label: One\n"
            "    - id: duplicate\n      label: Two\n",
            "unique letter",
        ),
        ("cards:\n  - invalid\n", "card must be a mapping"),
    ],
)
def test_data_card_renderer_enforces_source_size_and_mapping_limits(app_env, source_block, message):
    app, _settings, admin, _token = app_env
    content = app.state.content
    content.create_book("Research", "research", admin)
    content.create_page("research", "Cards", "cards", "", [], False, admin)
    source = content.docs / "research" / "cards.md"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "title: Cards\n", "title: Cards\n" + source_block
        ),
        encoding="utf-8",
    )
    entry = WidgetEntry(id="cards", type="data-cards", config={"source": "research/cards.md"})
    with Session(app.state.engine) as session:
        authorization = AuthorizationContext(session, session.get(User, admin.id))
        with pytest.raises(ValueError, match=message):
            _render_data_cards(entry, authorization, content)


@pytest.mark.parametrize(
    ("target", "message"),
    [
        ("research/too/deep.md", "page targets must look like"),
        ("research/missing.md", "target page could not be read"),
        ("research/too/deep", "book targets must be a book path"),
        ("missing-book", "target book could not be read"),
        ("/outside.md", "card targets must be book or page paths"),
    ],
)
def test_data_card_renderer_validates_link_targets(app_env, target, message):
    app, _settings, admin, _token = app_env
    content = app.state.content
    content.create_book("Research", "research", admin)
    content.create_page("research", "Cards", "cards", "", [], False, admin)
    source = content.docs / "research" / "cards.md"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "title: Cards\n", "title: Cards\ncards:\n  - title: Card\n    target: " + target + "\n"
        ),
        encoding="utf-8",
    )
    entry = WidgetEntry(id="cards", type="data-cards", config={"source": "research/cards.md"})
    with Session(app.state.engine) as session:
        authorization = AuthorizationContext(session, session.get(User, admin.id))
        with pytest.raises(ValueError, match=message):
            _render_data_cards(entry, authorization, content)


def test_source_widgets_render_empty_when_viewer_cannot_read_the_source(app_env):
    app, _settings, admin, _token = app_env
    content = app.state.content
    content.create_book("Research", "research", admin)
    content.create_page("research", "Cards", "cards", "Secret", [], False, admin)
    source = content.docs / "research" / "cards.md"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "title: Cards\n", "title: Cards\ncards:\n  - title: Private card\n"
        ),
        encoding="utf-8",
    )

    with Session(app.state.engine) as session:
        reader = _reader(session, "unreadable-widget@example.com")
        authorization = AuthorizationContext(session, reader)
        cards = _render_data_cards(
            WidgetEntry(id="cards", type="data-cards", config={"source": "research/cards.md"}),
            authorization,
            content,
        )
        text = _render_text(
            WidgetEntry(id="text", type="text", config={"source": "research/cards.md"}),
            authorization,
            content,
        )

    assert cards.data == {"items": []}
    assert text.data == {"html": ""}


def test_data_card_omits_an_unreadable_but_valid_link_target(app_env):
    """Cards may be shared without turning a private target into a link."""

    app, _settings, admin, _token = app_env
    content = app.state.content
    content.create_book("Research", "research", admin)
    content.create_book("Private", "private", admin)
    content.create_page("research", "Cards", "cards", "", [], False, admin)
    source = content.docs / "research" / "cards.md"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "title: Cards\n",
            "title: Cards\ncards:\n  - title: Private reference\n    target: private\n",
        ),
        encoding="utf-8",
    )
    with Session(app.state.engine) as session:
        reader = _reader(session, "limited-widget@example.com")
        _grant(session, reader, "research", read=True, group_name="research-readers")
        authorization = AuthorizationContext(session, reader)
        rendered = _render_data_cards(
            WidgetEntry(id="cards", type="data-cards", config={"source": "research/cards.md"}),
            authorization,
            content,
        )

    assert rendered.data["items"][0]["target_url"] is None


def test_data_card_links_to_a_readable_book_or_page_target(app_env):
    """A valid, readable target becomes an internal management link."""

    app, _settings, admin, _token = app_env
    content = app.state.content
    content.create_book("Research", "research", admin)
    content.create_book("Projects", "projects", admin)
    content.create_page("projects", "Overview", "overview", "", [], False, admin)
    content.create_page("research", "Cards", "cards", "", [], False, admin)
    source = content.docs / "research" / "cards.md"
    source.write_text(
        "---\ntitle: Cards\ncards:\n  - title: Projects\n    target: projects\n"
        "  - title: Project overview\n    target: projects/overview.md\n---\n",
        encoding="utf-8",
    )
    with Session(app.state.engine) as session:
        authorization = AuthorizationContext(session, session.get(User, admin.id))
        rendered = _render_data_cards(
            WidgetEntry(id="cards", type="data-cards", config={"source": "research/cards.md"}),
            authorization,
            content,
        )

    assert rendered.data["items"][0]["target_url"] == "/books/projects"
    assert rendered.data["items"][1]["target_url"] == "/pages/projects/overview"


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


def test_is_widget_source_path_recognizes_every_shape_widget_source_path_generates():
    """The one predicate used to save-validate, list-exclude, and search-exclude
    generated widget sources must agree with the one function that generates
    their paths (widget_source_path) -- previously three independent,
    slightly different checks existed instead of this single pair."""

    home_source = widget_source_path("index.md", "notice")
    book_source = widget_source_path("research", "team")
    page_source = widget_source_path("research/about.md", "project-cards")
    assert is_widget_source_path(home_source)
    assert is_widget_source_path(book_source)
    assert is_widget_source_path(page_source)

    # Ordinary content at the same depths must not be mistaken for one.
    assert not is_widget_source_path("research/about.md")
    assert not is_widget_source_path("research/widget-sources-extra/x.md")
    assert not is_widget_source_path("widget-sources.md")


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
