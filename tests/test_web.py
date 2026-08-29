"""The server-rendered browser UI must gate itself exactly like the JSON API.

The cases here are the ones a plausible implementation gets wrong: an
unauthenticated visitor reaching a real page instead of being bounced to
login, a forced-password-change session finding a way around the tree, two
users with different grants somehow seeing the same content, a bad path
leaking whether it exists via a 403 instead of a 404, and unsanitized page
content escaping into the rendered HTML.
"""

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
    assert "Admin Agent" in tree.text


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
    alice_tree = client.get("/tree")
    assert "Alice Book" in alice_tree.text
    assert "Bob Book" not in alice_tree.text
    client.cookies.clear()

    _login(client, "bob")
    bob_tree = client.get("/tree")
    assert "Bob Book" in bob_tree.text
    assert "Alice Book" not in bob_tree.text


# --------------------------------------------------------------------------
# Book dashboard (cards)
# --------------------------------------------------------------------------


def test_dashboard_renders_a_card_per_book_linked_to_its_book_page(client, content):
    _login(client, "admin")
    page = client.get("/tree")
    assert page.status_code == 200
    assert 'data-key="alice-book"' in page.text
    assert 'data-key="bob-book"' in page.text
    assert 'href="/books/alice-book"' in page.text
    assert 'href="/books/bob-book"' in page.text


def test_the_add_book_button_is_admin_only(app_env, client, content):
    app, _settings, _admin, _token = app_env
    _make_user(app, "reader")

    _login(client, "admin")
    admin_page = client.get("/tree")
    assert "new-book-popover" in admin_page.text
    client.cookies.clear()

    _login(client, "reader")
    reader_page = client.get("/tree")
    assert "new-book-popover" not in reader_page.text


def test_dashboard_empty_state_when_no_books_are_visible(app_env, client):
    app, _settings, _admin, _token = app_env
    _make_user(app, "reader")

    _login(client, "reader")
    page = client.get("/tree")
    assert "Nothing here yet" in page.text
    assert 'id="book-cards"' not in page.text


# --------------------------------------------------------------------------
# Book overview page (chapter rows of page cards)
# --------------------------------------------------------------------------


@pytest.fixture
def book_with_chapters(app_env):
    """A book with a loose page, a chapter with pages, and an empty chapter."""

    app, _settings, admin, _token = app_env
    repository = app.state.content
    repository.create_book("Handbook", "handbook", admin)
    repository.create_page("handbook", "Overview", "overview", "# Overview", [], False, admin)
    repository.create_chapter("handbook", "Policies", "policies", admin)
    repository.create_page("handbook/policies", "Leave", "leave", "# Leave", [], False, admin)
    repository.create_page("handbook/policies", "Travel", "travel", "# Travel", [], True, admin)
    repository.create_chapter("handbook", "Empty Chapter", "empty-chapter", admin)
    return repository


def test_book_page_renders_a_row_per_chapter_with_page_cards(client, book_with_chapters):
    _login(client, "admin")
    page = client.get("/books/handbook")
    assert page.status_code == 200
    assert "Policies" in page.text
    assert "Empty Chapter" in page.text
    assert 'href="/pages/handbook/policies/leave"' in page.text
    assert 'href="/pages/handbook/policies/travel"' in page.text
    assert "No pages yet" in page.text  # the empty chapter's row


def test_book_page_shows_loose_pages_under_a_pages_row(client, book_with_chapters):
    _login(client, "admin")
    page = client.get("/books/handbook")
    assert 'href="/pages/handbook/overview"' in page.text


def test_book_page_carries_page_drag_reorder_markup(client, book_with_chapters):
    """Page cards are draggable with a stable key and load the shared script."""

    _login(client, "admin")
    page = client.get("/books/handbook")
    assert '<script src="/static/reorder.js"></script>' in page.text
    assert "initDragReorder(document.querySelector('#chapter-rows')" not in page.text
    assert 'class="drag-handle"' not in page.text
    assert '<section class="chapter-row">' in page.text
    assert 'class="page-card" draggable="true" data-key="handbook/policies/leave"' in page.text
    assert 'data-parent="handbook/policies"' in page.text
    assert 'data-parent="handbook"' in page.text  # the loose-pages row
    assert 'aria-label="Scroll pages left"' in page.text
    assert 'aria-label="Scroll pages right"' in page.text
    assert 'class="page-scroller" id="policies-pages"' in page.text
    assert 'data-scroll-target="policies-pages-list"' in page.text


def test_book_page_rows_have_a_collapse_toggle(client, book_with_chapters):
    _login(client, "admin")
    page = client.get("/books/handbook")
    assert 'aria-controls="pages-row"' in page.text
    assert 'aria-controls="policies-pages"' in page.text
    assert 'aria-controls="empty-chapter-pages"' in page.text
    # Every aria-controls target must actually exist, whether that's the
    # page list or the "No pages yet" placeholder.
    assert 'id="policies-pages"' in page.text
    assert 'id="empty-chapter-pages"' in page.text


def test_chapter_collapse_toggle_precedes_its_title(client, book_with_chapters):
    """The small down/right triangle belongs directly before the chapter name."""

    _login(client, "admin")
    page = client.get("/books/handbook")
    toggle = page.text.index('aria-controls="policies-pages"')
    title = page.text.index('<h2 class="chapter-row-title">Policies</h2>')
    assert toggle < title


def test_creation_popovers_have_no_slug_field(client, book_with_chapters):
    """Slug is always derived from the title now -- see make_slug."""

    _login(client, "admin")
    dashboard = client.get("/tree")
    assert 'name="slug"' not in dashboard.text
    book_page = client.get("/books/handbook")
    assert 'name="slug"' not in book_page.text


def test_book_page_marks_drafts(client, book_with_chapters):
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


def test_the_add_chapter_button_follows_write_access_not_admin_status(
    app_env, client, book_with_chapters
):
    """Chapter creation only needs a write grant on the book (see
    AIContentService.create_chapter), same as the page button one level down
    -- a non-admin editor with an actual write grant must still see it."""

    app, _settings, _admin, _token = app_env

    _login(client, "admin")
    admin_page = client.get("/books/handbook")
    assert "new-book-popover" in admin_page.text
    client.cookies.clear()

    reader = _make_user(app, "handbook-reader")
    _grant(app, reader.id, "handbook", group_name="handbook-reader-group")
    _login(client, "handbook-reader")
    reader_page = client.get("/books/handbook")
    assert "new-book-popover" not in reader_page.text
    client.cookies.clear()

    editor = _make_user(app, "handbook-editor")
    _grant(app, editor.id, "handbook", group_name="handbook-editor-group", can_write=True)
    _login(client, "handbook-editor")
    editor_page = client.get("/books/handbook")
    assert "new-book-popover" in editor_page.text


def test_creating_a_chapter_redirects_back_to_the_book_page(app_env, client):
    app, _settings, admin, _token = app_env
    app.state.content.create_book("Handbook", "handbook", admin)

    _login(client, "admin")
    page = client.get("/books/handbook")
    csrf_token = _csrf_from(page.text)
    response = client.post(
        "/manage/chapter",
        data={"csrf_token": csrf_token, "book_slug": "handbook", "title": "Policies"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/books/handbook"


def test_a_non_admin_with_a_write_grant_can_actually_create_a_chapter(app_env, client):
    """The button being visible has to match what the backend actually allows."""

    app, _settings, admin, _token = app_env
    app.state.content.create_book("Handbook", "handbook", admin)
    editor = _make_user(app, "handbook-editor")
    _grant(app, editor.id, "handbook", group_name="handbook-editor-group", can_write=True)

    _login(client, "handbook-editor")
    page = client.get("/books/handbook")
    csrf_token = _csrf_from(page.text)
    response = client.post(
        "/manage/chapter",
        data={"csrf_token": csrf_token, "book_slug": "handbook", "title": "Policies"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/books/handbook"


def test_the_topbar_has_no_manage_content_link(client):
    _login(client, "admin")
    page = client.get("/tree")
    assert "Manage content" not in page.text
    assert 'href="/admin"' in page.text


def test_creating_a_page_quick_redirects_to_the_book_page_with_its_new_card(
    client, book_with_chapters
):
    """The quick-create popover makes a blank page (no markdown editor step)
    and lands back where its card is now visible, matching the book/chapter
    creation flow -- not the full editor's own /pages/new, which is a
    separate route reserved for actually writing content."""

    _login(client, "admin")
    page = client.get("/books/handbook")
    csrf_token = _csrf_from(page.text)
    response = client.post(
        "/manage/page",
        data={"csrf_token": csrf_token, "parent": "handbook/policies", "title": "Holidays"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/books/handbook"

    book_page = client.get("/books/handbook")
    assert 'href="/pages/handbook/policies/holidays"' in book_page.text


def test_the_add_page_button_follows_write_access_not_admin_status(
    app_env, client, book_with_chapters
):
    """Page creation only needs a write grant (see AIContentService.create_page),
    unlike book/chapter creation which is admin-only -- the button must track
    that, not just is_admin, or a non-admin editor with a real write grant
    would never see it."""

    app, _settings, _admin, _token = app_env
    read_only = _make_user(app, "read-only")
    _grant(app, read_only.id, "handbook", group_name="read-only-group")
    editor = _make_user(app, "editor")
    _grant(app, editor.id, "handbook/policies", group_name="editor-group", can_write=True)

    _login(client, "admin")
    admin_page = client.get("/books/handbook")
    assert 'name="parent" value="handbook/policies"' in admin_page.text
    client.cookies.clear()

    _login(client, "read-only")
    reader_page = client.get("/books/handbook")
    assert 'name="parent" value="handbook/policies"' not in reader_page.text
    client.cookies.clear()

    _login(client, "editor")
    editor_page = client.get("/books/handbook")
    assert 'name="parent" value="handbook/policies"' in editor_page.text


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
    assert 'class="page-title"><a href="/pages/handbook/leave/edit"' in response.text
    assert "Move or rename" not in response.text
    assert 'id="edit-toggle"' in response.text
    assert 'id="inline-editor" hidden' in response.text
    assert 'href="/books/handbook" title="Back to book"' in response.text


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
    assert client.get("/pages/alice-book/secret", follow_redirects=False).status_code == 401


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
    assert "EasyMDE" in editor.text
    assert "/pages/handbook/leave/preview" in editor.text
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
    assert "not included in the published site" in client.get("/pages/handbook/leave").text

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
    assert "/api/admin/users" in response.text
    assert "/api/admin/backup/config" in response.text
    # Live rows delegate their destructive actions to the established CSRF
    # guarded APIs; confirmation happens before each state-changing request.
    for control in (
        "data-user-deactivate",
        "data-user-delete",
        "data-group-delete",
        "data-member-remove",
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
