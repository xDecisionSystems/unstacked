"""The small, explicit widget registry that renders Home's ``featured`` slot.

Covers malformed/unknown-widget-type handling (never crash the page; never
silently drop an entry) and the ``featured`` widget's ACL filtering, which
must match ``home_items()``'s stored order and hide anything the viewing
user cannot read.
"""

from sqlmodel import Session

from app.acl import AuthorizationContext
from app.auth import hash_password
from app.content import ContentRepository
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
