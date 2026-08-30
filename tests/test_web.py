"""The server-rendered browser UI must gate itself exactly like the JSON API.

The cases here are the ones a plausible implementation gets wrong: an
unauthenticated visitor reaching a real page instead of being bounced to
login, a forced-password-change session finding a way around the tree, two
users with different grants somehow seeing the same content, a bad path
leaking whether it exists via a 403 instead of a 404, and unsanitized page
content escaping into the rendered HTML.
"""

import json
import re

import pytest
from sqlmodel import Session

from app.auth import hash_password
from app.models import Group, Permission, User, UserGroup

PASSWORD = "correct horse battery staple"


@pytest.fixture
def content(app_env):
    """A small real content tree with two independent books."""

    app, _settings, admin, _token = app_env
    repository = app.state.content
    repository.create_book("Alice Book", "alice-book", admin)
    repository.create_page(
        "alice-book", "Secret", "secret", "# Secret\n\nAlice-only body.", [], False, admin
    )
    repository.create_book("Bob Book", "bob-book", admin)
    repository.create_page(
        "bob-book", "Other", "other", "# Other\n\nBob-only body.", [], False, admin
    )
    return repository


def _make_user(app, username, *, password=PASSWORD, must_change_password=False) -> User:
    with Session(app.state.engine) as session:
        user = User(
            username=username,
            email=f"{username}@example.com",
            password_hash=hash_password(password),
            display_name=username.title(),
            must_change_password=must_change_password,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        session.expunge(user)
        return user


def _grant(
    app, user_id: int, path_prefix: str, *, group_name: str, can_write: bool = False
) -> None:
    with Session(app.state.engine) as session:
        group = Group(name=group_name)
        session.add(group)
        session.commit()
        session.refresh(group)
        session.add(UserGroup(user_id=user_id, group_id=group.id))
        session.add(
            Permission(
                group_id=group.id, path_prefix=path_prefix, can_read=True, can_write=can_write
            )
        )
        session.commit()


def _login(client, username, password=PASSWORD):
    return client.post(
        "/login", data={"username": username, "password": password}, follow_redirects=False
    )


def _csrf_from(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "expected a csrf_token hidden field in the rendered form"
    return match.group(1)


# --------------------------------------------------------------------------
# Root route and login
# --------------------------------------------------------------------------


def test_unauthenticated_root_redirects_to_login(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_page_renders_a_form_for_an_unauthenticated_visitor(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert 'name="username"' in response.text
    assert 'name="password"' in response.text


def test_successful_login_reaches_the_tree(client):
    """Logging in via the HTML form sets a cookie and lands on the tree."""

    login = _login(client, "admin")
    assert login.status_code == 303
    assert login.headers["location"] == "/tree"

    root = client.get("/", follow_redirects=False)
    assert root.headers["location"] == "/tree"

    tree = client.get("/tree")
    assert tree.status_code == 200
    assert 'aria-label="Settings"' in tree.text


def test_failed_login_shows_an_inline_error_without_a_redirect(client):
    response = _login(client, "admin", password="not the right password")
    assert response.status_code == 401
    assert "Invalid username or password" in response.text
    # No session was established.
    assert client.get("/", follow_redirects=False).headers["location"] == "/login"


# --------------------------------------------------------------------------
# Mandatory first password change
# --------------------------------------------------------------------------


def test_forced_password_change_session_cannot_reach_the_tree(app_env, client):
    app, _settings, _admin, _token = app_env
    _make_user(app, "newhire", must_change_password=True)

    login = _login(client, "newhire")
    assert login.headers["location"] == "/change-password"

    assert client.get("/tree", follow_redirects=False).status_code == 403
    assert client.get("/", follow_redirects=False).headers["location"] == "/change-password"


def test_change_password_flow_unblocks_the_tree(app_env, client):
    app, _settings, _admin, _token = app_env
    _make_user(app, "newhire", must_change_password=True)
    _login(client, "newhire")

    form_page = client.get("/change-password")
    assert form_page.status_code == 200
    csrf_token = _csrf_from(form_page.text)

    wrong = client.post(
        "/change-password",
        data={
            "csrf_token": csrf_token,
            "current_password": "definitely wrong",
            "new_password": "a whole new passphrase",
        },
    )
    assert wrong.status_code == 400
    assert "incorrect" in wrong.text

    changed = client.post(
        "/change-password",
        data={
            "csrf_token": csrf_token,
            "current_password": PASSWORD,
            "new_password": "a whole new passphrase",
        },
        follow_redirects=False,
    )
    assert changed.status_code == 303
    assert changed.headers["location"] == "/tree"
    assert client.get("/tree").status_code == 200


# --------------------------------------------------------------------------
# ACL-filtered tree and page view
# --------------------------------------------------------------------------


def test_two_users_with_different_grants_see_different_trees(app_env, client, content):
    app, _settings, _admin, _token = app_env
    alice = _make_user(app, "alice")
    bob = _make_user(app, "bob")
    _grant(app, alice.id, "alice-book", group_name="alice-group")
    _grant(app, bob.id, "bob-book", group_name="bob-group")

    _login(client, "alice")
    alice_tree = client.get("/books")
    assert "Alice Book" in alice_tree.text
    assert "Bob Book" not in alice_tree.text
    client.cookies.clear()

    _login(client, "bob")
    bob_tree = client.get("/books")
    assert "Bob Book" in bob_tree.text
    assert "Alice Book" not in bob_tree.text


# --------------------------------------------------------------------------
# Book dashboard (cards)
# --------------------------------------------------------------------------


def test_dashboard_renders_a_card_per_book_linked_to_its_book_page(client, content):
    _login(client, "admin")
    page = client.get("/books")
    assert page.status_code == 200
    assert 'data-key="alice-book"' in page.text
    assert 'data-key="bob-book"' in page.text
    assert 'href="/books/alice-book"' in page.text
    assert 'href="/books/bob-book"' in page.text


def test_home_only_shows_featured_content_and_navigation_exposes_libraries(client, content):
    _login(client, "admin")

    home = client.get("/tree")
    assert 'href="/books"' in home.text
    assert 'href="/pages"' in home.text
    assert "Alice Book" not in home.text
    assert "Secret" not in home.text

    csrf = _csrf_from(home.text)
    assert client.post(
        "/home/feature",
        data={"csrf_token": csrf, "target": "alice-book/secret.md", "return_to": "/tree"},
        follow_redirects=False,
    ).status_code == 303
    home = client.get("/tree")
    assert "Secret" in home.text
    assert "Bob Book" not in home.text


def test_pages_view_lists_only_pages_the_user_can_read(app_env, client, content):
    app, _settings, _admin, _token = app_env
    alice = _make_user(app, "alice")
    _grant(app, alice.id, "alice-book", group_name="alice-pages")

    _login(client, "alice")
    pages = client.get("/pages")
    assert pages.status_code == 200
    assert "Secret" in pages.text
    assert "Other" not in pages.text
    assert 'href="/pages/alice-book/secret"' in pages.text


def test_admin_can_feature_a_page_or_book_on_home(client, content):
    _login(client, "admin")
    csrf = _csrf_from(client.get("/tree").text)
    assert client.post(
        "/home/feature",
        data={"csrf_token": csrf, "target": "alice-book"},
        follow_redirects=False,
    ).status_code == 303
    assert client.post(
        "/home/feature",
        data={"csrf_token": csrf, "target": "alice-book/secret.md"},
        follow_redirects=False,
    ).status_code == 303

    page = client.get("/tree")

    assert "Featured" in page.text
    assert 'href="/books/alice-book"' in page.text
    assert 'href="/pages/alice-book/secret"' in page.text


# --------------------------------------------------------------------------
# Editable, widget-based Home (Phase 3 of plan_editable_widget_home.md)
# --------------------------------------------------------------------------


def test_home_renders_the_index_page_body_and_the_featured_widget(client, content):
    _login(client, "admin")
    csrf = _csrf_from(client.get("/tree").text)
    client.post(
        "/home/feature",
        data={"csrf_token": csrf, "target": "alice-book/secret.md"},
        follow_redirects=False,
    )

    home = client.get("/tree")
    assert home.status_code == 200
    # The starter body written by ContentRepository's bootstrap, rendered as
    # actual Markdown -- not the old fixed Branding-sourced heading.
    assert "Your featured books and pages." in home.text
    # The featured widget, rendered below the body in its own fixed slot.
    assert "Featured" in home.text
    assert 'href="/pages/alice-book/secret"' in home.text
    assert "Secret" in home.text


def test_home_edit_button_visibility_follows_write_access_not_admin_status(app_env, client):
    app, _settings, _admin, _token = app_env
    writer = _make_user(app, "writer")
    _grant(app, writer.id, "index.md", group_name="home-writers", can_write=True)
    _make_user(app, "reader")

    _login(client, "writer")
    home = client.get("/tree")
    assert 'href="/home/edit"' in home.text
    assert client.get("/home/edit").status_code == 200

    _login(client, "reader")
    home = client.get("/tree")
    assert 'href="/home/edit"' not in home.text
    assert client.get("/home/edit").status_code == 404


def test_home_edit_round_trip_updates_markdown_and_title(app_env, client):
    app, _settings, admin, _token = app_env
    content = app.state.content
    _login(client, "admin")

    editor = client.get("/home/edit")
    assert editor.status_code == 200
    assert "Your featured books and pages." in editor.text
    assert "toastui-editor-all.min.js" in editor.text
    assert 'name="widgets_json"' in editor.text
    assert 'data-id="featured"' in editor.text
    csrf_token = _csrf_from(editor.text)
    blob_sha = re.search(r'name="base_blob_sha" value="([0-9a-f]+)"', editor.text).group(1)

    saved = client.post(
        "/home/edit",
        data={
            "csrf_token": csrf_token,
            "base_blob_sha": blob_sha,
            "title": "Welcome",
            "markdown": "# Welcome\n\nUpdated home copy.",
            "widgets_json": json.dumps([{"id": "featured", "type": "featured", "config": {}}]),
        },
        follow_redirects=False,
    )
    assert saved.status_code == 303
    assert saved.headers["location"] == "/tree"

    metadata, markdown, _raw = content.read_home_page()
    assert markdown == "# Welcome\n\nUpdated home copy."
    assert metadata["title"] == "Welcome"
    home = client.get("/tree")
    assert "Updated home copy." in home.text


def test_home_edit_rejects_a_stale_save_without_overwriting(app_env, client):
    app, _settings, admin, _token = app_env
    content = app.state.content
    _login(client, "admin")

    editor = client.get("/home/edit")
    csrf_token = _csrf_from(editor.text)
    stale_sha = re.search(r'name="base_blob_sha" value="([0-9a-f]+)"', editor.text).group(1)
    content.update_home_page(
        "Changed elsewhere",
        [{"id": "featured", "type": "featured", "config": {}}],
        admin,
        base_blob_sha=content.home_page_blob_sha(),
    )

    response = client.post(
        "/home/edit",
        data={
            "csrf_token": csrf_token,
            "base_blob_sha": stale_sha,
            "title": "Home",
            "markdown": "Would overwrite",
            "widgets_json": json.dumps([{"id": "featured", "type": "featured", "config": {}}]),
        },
    )
    assert response.status_code == 409
    assert "changed since you opened it" in response.text
    assert content.read_home_page()[1] == "Changed elsewhere"


def test_home_edit_reorders_widgets_and_persists_the_new_order(app_env, client):
    app, _settings, admin, _token = app_env
    content = app.state.content
    content.update_home_page(
        "Body",
        [
            {"id": "featured", "type": "featured", "config": {}},
            {"id": "extra", "type": "featured", "config": {"note": "second"}},
        ],
        admin,
        base_blob_sha=content.home_page_blob_sha(),
    )
    _login(client, "admin")

    editor = client.get("/home/edit")
    assert editor.status_code == 200
    # Both widgets appear in the tray, in their stored order.
    assert editor.text.index('data-id="featured"') < editor.text.index('data-id="extra"')
    csrf_token = _csrf_from(editor.text)
    blob_sha = re.search(r'name="base_blob_sha" value="([0-9a-f]+)"', editor.text).group(1)

    saved = client.post(
        "/home/edit",
        data={
            "csrf_token": csrf_token,
            "base_blob_sha": blob_sha,
            "title": "Home",
            "markdown": "Body",
            "widgets_json": json.dumps(
                [
                    {"id": "extra", "type": "featured", "config": {"note": "second"}},
                    {"id": "featured", "type": "featured", "config": {}},
                ]
            ),
        },
        follow_redirects=False,
    )
    assert saved.status_code == 303

    metadata, _markdown, _raw = content.read_home_page()
    assert [entry["id"] for entry in metadata["widgets"]] == ["extra", "featured"]


def test_feature_star_toggles_in_place_on_a_book_page(client, content):
    _login(client, "admin")
    book = client.get("/books/alice-book")
    csrf = _csrf_from(book.text)
    assert 'class="feature-star"' in book.text
    assert "☆" in book.text

    featured = client.post(
        "/home/feature",
        data={
            "csrf_token": csrf,
            "target": "alice-book/secret.md",
            "return_to": "/books/alice-book",
        },
        follow_redirects=False,
    )
    assert featured.status_code == 303
    assert featured.headers["location"] == "/books/alice-book"
    selected = client.get("/books/alice-book")
    assert 'class="feature-star is-featured"' in selected.text
    assert "★" in selected.text

    removed = client.post(
        "/home/remove",
        data={
            "csrf_token": csrf,
            "target": "alice-book/secret.md",
            "return_to": "/books/alice-book",
        },
        follow_redirects=False,
    )
    assert removed.headers["location"] == "/books/alice-book"


def test_the_add_book_button_is_admin_only(app_env, client, content):
    app, _settings, _admin, _token = app_env
    _make_user(app, "reader")

    _login(client, "admin")
    admin_page = client.get("/books")
    assert "new-book-popover" in admin_page.text
    client.cookies.clear()

    _login(client, "reader")
    reader_page = client.get("/books")
    assert "new-book-popover" not in reader_page.text


def test_dashboard_empty_state_when_no_books_are_visible(app_env, client):
    app, _settings, _admin, _token = app_env
    _make_user(app, "reader")

    _login(client, "reader")
    page = client.get("/books")
    assert "Nothing here yet" in page.text
    assert 'id="book-cards"' not in page.text


# --------------------------------------------------------------------------
# Book overview page (one grid of page cards)
# --------------------------------------------------------------------------


@pytest.fixture
def book_with_pages(app_env):
    """A book whose pages all live directly in the book."""

    app, _settings, admin, _token = app_env
    repository = app.state.content
    repository.create_book("Handbook", "handbook", admin)
    repository.create_page("handbook", "Overview", "overview", "# Overview", [], False, admin)
    repository.create_page("handbook", "Leave", "leave", "# Leave", [], False, admin)
    repository.create_page("handbook", "Travel", "travel", "# Travel", [], True, admin)
    return repository


def test_book_page_renders_one_grid_of_page_cards(client, book_with_pages):
    _login(client, "admin")
    page = client.get("/books/handbook")
    assert page.status_code == 200
    assert 'href="/pages/handbook/leave"' in page.text
    assert 'href="/pages/handbook/travel"' in page.text
    assert 'class="page-cards book-page-grid"' in page.text
    assert "chapter-row" not in page.text


def test_book_page_shows_direct_pages(client, book_with_pages):
    _login(client, "admin")
    page = client.get("/books/handbook")
    assert 'href="/pages/handbook/overview"' in page.text


def test_book_page_renders_an_optional_page_card_image(client, book_with_pages):
    page_file = book_with_pages.docs / "handbook" / "overview.md"
    page_file.write_text(
        page_file.read_text(encoding="utf-8").replace(
            "draft: false", "draft: false\ncard_image: assets/handbook/cover.png"
        ),
        encoding="utf-8",
    )
    _login(client, "admin")

    page = client.get("/books/handbook")
    assert 'class="page-card-image" src="/assets/assets/handbook/cover.png"' in page.text


def test_book_page_carries_page_drag_reorder_markup(client, book_with_pages):
    """Page cards are draggable with a stable key and load the shared script."""

    _login(client, "admin")
    page = client.get("/books/handbook")
    assert '<script src="/static/reorder.js"></script>' in page.text
    assert "initDragReorder(document.querySelector('#book-page-cards')" in page.text
    assert 'class="drag-handle"' not in page.text
    assert 'class="page-card" draggable="true" data-key="handbook/leave"' in page.text
    assert 'data-parent="handbook"' in page.text
    assert 'aria-label="Scroll pages left"' not in page.text
    assert 'aria-label="Scroll pages right"' not in page.text


def test_book_page_has_no_chapter_collapse_controls(client, book_with_pages):
    _login(client, "admin")
    page = client.get("/books/handbook")
    assert 'class="row-toggle"' not in page.text
    assert 'id="book-page-cards"' in page.text


def test_creation_popovers_have_no_slug_field(client, book_with_pages):
    """Slug is always derived from the title now -- see make_slug."""

    _login(client, "admin")
    dashboard = client.get("/books")
    assert 'name="slug"' not in dashboard.text
    book_page = client.get("/books/handbook")
    assert 'name="slug"' not in book_page.text


def test_book_page_marks_drafts(client, book_with_pages):
    _login(client, "admin")
    page = client.get("/books/handbook")
    assert "Draft" in page.text


def test_book_page_404s_for_an_unknown_book(client):
    _login(client, "admin")
    assert client.get("/books/no-such-book").status_code == 404


def test_book_page_404s_rather_than_leaking_an_inaccessible_book(app_env, client, content):
    app, _settings, _admin, _token = app_env
    _make_user(app, "reader")

    _login(client, "reader")
    assert client.get("/books/alice-book").status_code == 404


def test_add_page_control_follows_write_access(app_env, client, book_with_pages):
    """A writer can add pages directly to a book; a reader cannot."""

    app, _settings, _admin, _token = app_env

    _login(client, "admin")
    admin_page = client.get("/books/handbook")
    assert 'name="parent" value="handbook"' in admin_page.text
    client.cookies.clear()

    reader = _make_user(app, "handbook-reader")
    _grant(app, reader.id, "handbook", group_name="handbook-reader-group")
    _login(client, "handbook-reader")
    reader_page = client.get("/books/handbook")
    assert 'name="parent" value="handbook"' not in reader_page.text
    client.cookies.clear()

    editor = _make_user(app, "handbook-editor")
    _grant(app, editor.id, "handbook", group_name="handbook-editor-group", can_write=True)
    _login(client, "handbook-editor")
    editor_page = client.get("/books/handbook")
    assert 'name="parent" value="handbook"' in editor_page.text


def test_the_topbar_has_no_manage_content_link(client):
    _login(client, "admin")
    page = client.get("/tree")
    assert "Manage content" not in page.text
    assert 'href="/settings"' in page.text


def test_creating_a_page_quick_redirects_to_the_book_page_with_its_new_card(
    client, book_with_pages
):
    """The quick-create popover makes a blank page (no markdown editor step)
    and lands back where its card is now visible, rather than the full editor's
    separate page-writing route."""

    _login(client, "admin")
    page = client.get("/books/handbook")
    csrf_token = _csrf_from(page.text)
    response = client.post(
        "/manage/page",
        data={"csrf_token": csrf_token, "parent": "handbook", "title": "Holidays"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/books/handbook"

    book_page = client.get("/books/handbook")
    assert 'href="/pages/handbook/holidays"' in book_page.text


def test_add_page_form_targets_the_current_book(
    app_env, client, book_with_pages
):
    """Page creation only needs a write grant (see AIContentService.create_page),
    unlike book creation which is admin-only -- the button must track
    that, not just is_admin, or a non-admin editor with a real write grant
    would never see it."""

    app, _settings, _admin, _token = app_env
    read_only = _make_user(app, "read-only")
    _grant(app, read_only.id, "handbook", group_name="read-only-group")
    editor = _make_user(app, "editor")
    _grant(app, editor.id, "handbook", group_name="editor-group", can_write=True)

    _login(client, "admin")
    admin_page = client.get("/books/handbook")
    assert 'name="parent" value="handbook"' in admin_page.text
    client.cookies.clear()

    _login(client, "read-only")
    reader_page = client.get("/books/handbook")
    assert 'name="parent" value="handbook"' not in reader_page.text
    client.cookies.clear()

    _login(client, "editor")
    editor_page = client.get("/books/handbook")
    assert 'name="parent" value="handbook"' in editor_page.text


def test_book_page_empty_state_for_a_book_with_nothing_in_it(app_env, client):
    app, _settings, admin, _token = app_env
    app.state.content.create_book("Empty Book", "empty-book", admin)

    _login(client, "admin")
    page = client.get("/books/empty-book")
    assert "Nothing here yet" in page.text


def test_page_view_renders_sanitized_html_with_the_front_matter_title(app_env, client):
    app, _settings, admin, _token = app_env
    app.state.content.create_book("Handbook", "handbook", admin)
    app.state.content.create_page(
        "handbook",
        "Leave policy",
        "leave",
        "# Body\n\nSafe text. <script>alert('xss')</script>",
        [],
        False,
        admin,
    )
    _login(client, "admin")

    response = client.get("/pages/handbook/leave")
    assert response.status_code == 200
    assert "Leave policy" in response.text
    assert "Safe text." in response.text
    assert "<script>alert('xss')</script>" not in response.text
    assert "handbook" in response.text.lower()
    assert 'id="editable-title"' in response.text
    assert 'id="title-editor"' not in response.text
    assert "Move or rename" not in response.text
    assert 'id="edit-toggle"' in response.text
    assert 'id="inline-editor" hidden' in response.text
    assert 'class="form-actions inline-editor-actions"' in response.text
    assert '<section id="inline-editor" hidden>' in response.text
    assert 'id="draft-toggle" class="draft-toggle" hidden' in response.text
    assert "Draft — exclude from the published site" not in response.text
    assert 'href="/books/handbook" title="Back to book"' in response.text
    assert "toastui-editor-all.min.js" in response.text
    assert "editor-plugin-table-merged-cell" in response.text
    assert "editor-plugin-uml" in response.text
    assert 'aria-label="Breadcrumb"' not in response.text

    changed = client.post(
        "/pages/handbook/leave/title",
        data={"csrf_token": _csrf_from(response.text), "title": "Updated title"},
        follow_redirects=False,
    )
    assert changed.status_code == 303
    assert app.state.content.read_page("handbook/leave.md")[0]["title"] == "Updated title"


def test_page_view_404s_for_a_missing_or_unreadable_path_never_403(app_env, client, content):
    app, _settings, _admin, _token = app_env
    reader = _make_user(app, "reader")
    _grant(app, reader.id, "alice-book", group_name="reader-group")
    _login(client, "reader")

    missing = client.get("/pages/alice-book/does-not-exist")
    assert missing.status_code == 404

    unreadable = client.get("/pages/bob-book/other")
    assert unreadable.status_code == 404


def test_web_routes_require_a_session(client):
    """The bare cookie dependency, not just the normal one, still gates access."""

    assert client.get("/tree", follow_redirects=False).status_code == 401
    assert client.get("/pages/alice-book/secret", follow_redirects=False).status_code == 404


# --------------------------------------------------------------------------
# Editor and browser mutations
# --------------------------------------------------------------------------


def test_editor_saves_through_the_acl_service_and_marks_drafts(app_env, client):
    app, _settings, admin, _token = app_env
    repository = app.state.content
    repository.create_book("Handbook", "handbook", admin)
    repository.create_page("handbook", "Leave", "leave", "Old body", [], False, admin)
    _login(client, "admin")

    editor = client.get("/pages/handbook/leave/edit")
    assert editor.status_code == 200
    assert "toastui-editor-all.min.js" in editor.text
    assert "getMarkdown" in editor.text
    # The chart plugin has a real, separate library dependency (toastui-chart);
    # without it, the plugin throws inside the editor's own constructor and
    # silently breaks its toolbar state tracking. Must load before the plugin.
    assert editor.text.index("toastui-chart.min.js") < editor.text.index(
        "editor-plugin-chart.min.js"
    )
    assert "editor-plugin-chart" in editor.text
    assert "editor-plugin-code-syntax-highlight" in editor.text
    # Unlike the other plugins, color-syntax has no "-all" bundle variant --
    # that filename 404s.
    assert "toastui-editor-plugin-color-syntax.min.js" in editor.text
    assert "toastui-editor-plugin-color-syntax-all.min.js" not in editor.text
    assert "editor-plugin-table-merged-cell" in editor.text
    assert "editor-plugin-uml" in editor.text
    assert 'name="card_image"' in editor.text
    csrf_token = _csrf_from(editor.text)
    blob_sha = re.search(r'name="base_blob_sha" value="([0-9a-f]+)"', editor.text).group(1)

    saved = client.post(
        "/pages/handbook/leave/edit",
        data={
            "csrf_token": csrf_token,
            "base_blob_sha": blob_sha,
            "markdown": "# Updated\n\nNew body",
            "tags": "hr, policy",
            "draft": "on",
        },
        follow_redirects=False,
    )
    assert saved.status_code == 303
    assert saved.headers["location"] == "/pages/handbook/leave"
    metadata, markdown, _raw = repository.read_page("handbook/leave.md")
    assert markdown == "# Updated\n\nNew body"
    assert metadata["tags"] == ["hr", "policy"]
    assert metadata["draft"] is True
    assert "Draft" in client.get("/books/handbook").text
    assert 'class="page-draft-status">(Draft)</em>' in client.get(
        "/pages/handbook/leave"
    ).text

    preview = client.post(
        "/pages/handbook/leave/preview",
        data={"csrf_token": csrf_token, "markdown": "# Rendered preview"},
    )
    assert preview.status_code == 200
    assert "Rendered preview" in preview.json()["html"]


def test_editor_rejects_a_stale_save_without_overwriting(app_env, client):
    app, _settings, admin, _token = app_env
    repository = app.state.content
    repository.create_book("Handbook", "handbook", admin)
    repository.create_page("handbook", "Leave", "leave", "Original", [], False, admin)
    _login(client, "admin")
    editor = client.get("/pages/handbook/leave/edit")
    csrf_token = _csrf_from(editor.text)
    stale_sha = re.search(r'name="base_blob_sha" value="([0-9a-f]+)"', editor.text).group(1)
    repository.update_page(
        "handbook/leave.md",
        "Changed elsewhere",
        [],
        False,
        admin,
        base_blob_sha=repository.page_blob_sha("handbook/leave.md"),
    )

    response = client.post(
        "/pages/handbook/leave/edit",
        data={
            "csrf_token": csrf_token,
            "base_blob_sha": stale_sha,
            "markdown": "Would overwrite",
            "tags": "",
        },
    )
    assert response.status_code == 409
    assert "changed since you opened it" in response.text
    assert repository.read_page("handbook/leave.md")[1] == "Changed elsewhere"


def test_editor_preview_is_csrf_and_write_gated(app_env, client, content):
    app, _settings, _admin, _token = app_env
    reader = _make_user(app, "reader")
    _grant(app, reader.id, "alice-book", group_name="reader-group")
    _login(client, "reader")

    denied = client.post("/pages/alice-book/secret/preview", data={"markdown": "# Nope"})
    assert denied.status_code == 403
    form = client.get("/pages/alice-book/secret/edit")
    assert form.status_code == 404


def test_browser_create_move_and_delete_use_the_existing_acl_rules(app_env, client):
    app, _settings, admin, _token = app_env
    repository = app.state.content
    repository.create_book("Source", "source", admin)
    repository.create_book("Destination", "destination", admin)
    _login(client, "admin")
    manage = client.get("/manage")
    csrf_token = _csrf_from(manage.text)
    created = client.post(
        "/pages/new",
        data={
            "csrf_token": csrf_token,
            "parent": "source",
            "title": "A page",
            "markdown": "Body",
            "tags": "",
        },
        follow_redirects=False,
    )
    assert created.headers["location"] == "/pages/source/a-page"

    move_form = client.get("/pages/source/a-page/move")
    moved = client.post(
        "/pages/source/a-page/move",
        data={
            "csrf_token": _csrf_from(move_form.text),
            "parent": "destination",
            "slug": "moved-page",
        },
        follow_redirects=False,
    )
    assert moved.headers["location"] == "/pages/destination/moved-page"
    page = client.get("/pages/destination/moved-page")
    deleted = client.post(
        "/pages/destination/moved-page/delete",
        data={"csrf_token": _csrf_from(page.text)},
        follow_redirects=False,
    )
    assert deleted.headers["location"] == "/tree"
    assert not (repository.docs / "destination" / "moved-page.md").exists()


def test_manage_content_is_admin_only_and_csrf_protected(app_env, client):
    app, _settings, _admin, _token = app_env
    _make_user(app, "editor")
    _login(client, "editor")
    assert client.get("/manage").status_code == 404
    assert client.post("/manage/book", data={"title": "Nope"}).status_code == 403


def test_admin_console_is_admin_only_and_exposes_existing_api_controls(app_env, client):
    app, _settings, _admin, _token = app_env
    _login(client, "admin")
    response = client.get("/admin")
    assert response.status_code == 200
    assert "Settings · Unstacked" in response.text
    assert 'data-admin-panel="users"' in response.text
    assert "/api/admin/users" in response.text
    assert "/api/admin/backup/config" in response.text
    assert "GitHub repository" in response.text
    assert "automatically synchronized to its <code>main</code> branch" in response.text
    assert 'data-admin-panel="groups"' in response.text
    assert 'data-admin-panel="book-permissions"' in response.text
    assert "Groups &amp; Assignments" in response.text
    assert 'data-admin-section="groups"' in response.text
    assert 'data-admin-section="users"' in response.text
    assert "selectPanel" in response.text
    assert client.get("/settings").status_code == 200
    # Live rows delegate their destructive actions to the established CSRF
    # guarded APIs; confirmation happens before each state-changing request.
    for control in (
        "data-user-deactivate",
        "data-user-reactivate",
        "data-user-delete",
        "primary Admin account cannot be deleted",
        "data-group-delete",
        "data-group-membership",
        "data-book-permission",
        "data-book-select-all",
        "data-book-default",
        "data-book-level",
        "data-permission-delete",
    ):
        assert control in response.text
    assert "confirmAction" in response.text
    assert "/members/${user}`,'DELETE'" in response.text
    assert "/permissions/${b.dataset.permissionDelete}`,'DELETE'" in response.text
    client.cookies.clear()
    _make_user(app, "reader")
    _login(client, "reader")
    assert client.get("/admin").status_code == 404


def test_settings_nav_has_a_dedicated_home_page_entry_pointing_to_home(app_env, client):
    """Home's copy/layout editing moved to the Home page itself (index.md).

    Settings keeps only administrator actions appropriate to the home page
    -- a pointer to where editing now happens, plus (optionally) a
    reset-to-starter action -- never the old copy-editing form fields.
    """

    _app, _settings, _admin, _token = app_env
    _login(client, "admin")
    response = client.get("/settings")
    assert response.status_code == 200
    assert 'data-admin-panel="home"' in response.text
    assert 'data-admin-section="home"' in response.text
    assert "Home page" in response.text
    assert 'href="/"' in response.text

    # The Branding form no longer carries Home's retired copy fields.
    assert 'name="home_eyebrow"' not in response.text
    assert 'name="home_title"' not in response.text
    assert 'name="home_description"' not in response.text
    assert 'name="featured_label"' not in response.text
    assert "home_eyebrow" not in response.text
    assert "home_title" not in response.text
    assert "home_description" not in response.text
    assert "featured_label" not in response.text


def test_public_page_and_book_are_available_without_a_session(app_env, client):
    app, _settings, admin, _token = app_env
    repository = app.state.content
    repository.create_book("Public handbook", "public-handbook", admin)
    repository.create_page(
        "public-handbook", "Welcome", "welcome", "# Welcome", [], False, admin
    )
    repository.set_subtree_public("public-handbook", True, admin)

    client.cookies.clear()
    assert client.get("/pages/public-handbook/welcome").status_code == 200
    assert client.get("/books/public-handbook").status_code == 200


# --------------------------------------------------------------------------
# History UI
# --------------------------------------------------------------------------


def test_history_ui_renders_escaped_side_by_side_diff_and_restores(app_env, client):
    app, _settings, admin, _token = app_env
    repository = app.state.content
    repository.create_book("Handbook", "handbook", admin)
    repository.create_page(
        "handbook", "Leave", "leave", "first <img src=x onerror=alert(1)>", [], False, admin
    )
    initial = repository.page_history("handbook/leave.md")[0].sha
    repository.update_page(
        "handbook/leave.md",
        "second version",
        [],
        False,
        admin,
        base_blob_sha=repository.page_blob_sha("handbook/leave.md"),
    )
    _login(client, "admin")

    page = client.get("/pages/handbook/leave")
    assert "/pages/handbook/leave/history" in page.text
    history = client.get("/pages/handbook/leave/history")
    assert history.status_code == 200
    assert "Side-by-side diff" in history.text
    assert "&lt;img" in history.text
    assert "onerror=alert" in history.text
    assert "<img src=x" not in history.text

    restored = client.post(
        "/pages/handbook/leave/history/restore",
        data={"csrf_token": _csrf_from(history.text), "revision": initial},
        follow_redirects=False,
    )
    assert restored.status_code == 303
    assert restored.headers["location"] == "/pages/handbook/leave"
    assert "first <img" in repository.read_page("handbook/leave.md")[1]


def test_read_only_user_can_view_history_but_cannot_restore(app_env, client, content):
    app, _settings, _admin, _token = app_env
    reader = _make_user(app, "reader")
    _grant(app, reader.id, "alice-book", group_name="reader-group")
    _login(client, "reader")

    history = client.get("/pages/alice-book/secret/history")
    assert history.status_code == 200
    assert "Side-by-side diff" in history.text
    assert ">Restore<" not in history.text
    revision = app.state.content.page_history("alice-book/secret.md")[0].sha
    denied = client.post(
        "/pages/alice-book/secret/history/restore",
        data={"csrf_token": _csrf_from(history.text), "revision": revision},
    )
    assert denied.status_code == 404


def test_history_ui_can_restore_a_deleted_page(app_env, client):
    app, _settings, admin, _token = app_env
    repository = app.state.content
    repository.create_book("Handbook", "handbook", admin)
    repository.create_page("handbook", "Leave", "leave", "recover me", [], False, admin)
    original = repository.page_history("handbook/leave.md")[0].sha
    repository.delete_page("handbook/leave.md", admin)
    _login(client, "admin")

    history = client.get("/pages/handbook/leave/history")
    assert history.status_code == 200
    restored = client.post(
        "/pages/handbook/leave/history/restore",
        data={"csrf_token": _csrf_from(history.text), "revision": original},
        follow_redirects=False,
    )
    assert restored.headers["location"] == "/pages/handbook/leave"
    assert repository.read_page("handbook/leave.md")[1] == "recover me"


# --------------------------------------------------------------------------
# Search UI
# --------------------------------------------------------------------------


def test_search_ui_uses_acl_filtered_results_and_escapes_literal_highlights(app_env, client):
    app, _settings, _admin, _token = app_env
    repository = app.state.content
    repository.create_book("Visible", "visible", _admin)
    repository.create_page(
        "visible",
        "Safe result",
        "safe-result",
        "before <img src=x onerror=alert(1)> needle after",
        ["guide"],
        False,
        _admin,
    )
    repository.create_book("Hidden", "hidden", _admin)
    repository.create_page(
        "hidden", "Private result", "private", "needle secret", [], False, _admin
    )
    reader = _make_user(app, "search-reader")
    _grant(app, reader.id, "visible", group_name="visible-search-group")
    _login(client, "search-reader")

    response = client.get("/search", params={"q": "needle"})

    assert response.status_code == 200
    assert "Safe result" in response.text
    assert "/pages/visible/safe-result" in response.text
    assert "<mark>needle</mark>" in response.text
    assert "&lt;img src=x onerror=alert(1)&gt;" in response.text
    assert "<img src=x" not in response.text
    assert "Private result" not in response.text
    assert "needle secret" not in response.text


def test_search_ui_paginates_the_already_filtered_result_set(app_env, client):
    app, settings, admin, _token = app_env
    docs = settings.content_repo_path / "docs" / "search-book"
    docs.mkdir(parents=True)
    for number in range(21):
        (docs / f"result-{number:02}.md").write_text(
            f"---\ntitle: Result {number:02}\ntags: []\n---\nneedle {number:02}", encoding="utf-8"
        )
    _login(client, "admin")

    first = client.get("/search", params={"q": "needle"})
    second = client.get("/search", params={"q": "needle", "page": 2})

    assert '<h2><a href="/pages/search-book/result-00">Result 00</a></h2>' in first.text
    assert '<h2><a href="/pages/search-book/result-20">Result 20</a></h2>' not in first.text
    assert "page=2" in first.text
    assert '<h2><a href="/pages/search-book/result-20">Result 20</a></h2>' in second.text
    assert '<h2><a href="/pages/search-book/result-00">Result 00</a></h2>' not in second.text
    assert "page=1" in second.text
