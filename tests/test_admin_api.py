"""Administration must change what other users see, and never lock everyone out.

The cases here are the ones a plausible implementation gets wrong: a grant
that is stored but never matches, a password reset that leaves one of the two
transports authenticated, a cascade done by hand that misses a table, an audit
line that carries the password it was recording, and -- the one a sequential
test cannot see -- two concurrent requests that each believe another
administrator still exists.
"""

import logging
import shutil
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, select

from app.acl import resolve_access
from app.admin_api import _audit
from app.auth import create_api_token, hash_password
from app.models import Permission, User, UserGroup
from app.web_auth import CSRF_HEADER_NAME, SESSION_COOKIE_NAME
from tests.conftest import bearer

PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "an entirely different passphrase"


@pytest.fixture
def content(app_env):
    """A small but real content tree, so grants have targets that exist."""

    app, _settings, admin, _token = app_env
    repository = app.state.content
    repository.create_book("Handbook", "handbook", admin)
    repository.create_page("handbook", "Leave", "leave", "# Leave", [], False, admin)
    repository.create_book("Archive", "archive", admin)
    repository.create_page("archive", "Old", "old", "# Old", [], False, admin)
    return repository


@pytest.fixture
def docs(app_env) -> Path:
    _app, settings, _admin, _token = app_env
    return Path(settings.content_repo_path) / "docs"


def _make_user(app, email, *, password=PASSWORD, is_admin=False, is_active=True) -> User:
    with Session(app.state.engine) as session:
        user = User(
            username=email.split("@")[0],
            email=email,
            password_hash=hash_password(password),
            display_name=email.split("@")[0],
            is_admin=is_admin,
            is_active=is_active,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        session.expunge(user)
        return user


def _active_admin_count(app) -> int:
    with Session(app.state.engine) as session:
        return len(
            session.exec(
                select(User).where(User.is_admin.is_(True)).where(User.is_active.is_(True))
            ).all()
        )


def _reload(app, user_id: int) -> User:
    with Session(app.state.engine) as session:
        return session.get(User, user_id)


def _group_with_member(client, token, user_id: int, name: str = "editors") -> int:
    group_id = client.post(
        "/api/admin/groups", json={"name": name}, headers=bearer(token)
    ).json()["id"]
    client.put(f"/api/admin/groups/{group_id}/members/{user_id}", headers=bearer(token))
    return group_id


# --------------------------------------------------------------------------
# Authorization
# --------------------------------------------------------------------------


def test_admin_routes_reject_an_unauthenticated_caller(client):
    assert client.get("/api/admin/users").status_code == 401


def test_admin_routes_reject_an_authenticated_non_admin(app_env, client):
    app, settings, _admin, _token = app_env
    reader = _make_user(app, "reader@example.com")
    token = create_api_token(reader, settings)
    assert client.get("/api/admin/users", headers=bearer(token)).status_code == 403


def test_cookie_authenticated_admin_still_needs_a_csrf_token(client):
    """The cookie alone is exactly what a cross-site form can already send."""

    csrf = client.post(
        "/auth/login", json={"username": "admin", "password": PASSWORD}
    ).json()["csrf_token"]
    payload = {"name": "via-browser"}

    assert client.post("/api/admin/groups", json=payload).status_code == 403
    ok = client.post("/api/admin/groups", json=payload, headers={CSRF_HEADER_NAME: csrf})
    assert ok.status_code == 201


# --------------------------------------------------------------------------
# Grants and their effect on a second user
# --------------------------------------------------------------------------


def test_grant_immediately_changes_a_second_users_view(app_env, client, content):
    """A saved grant has to take effect on the next request, not a restart."""

    app, settings, _admin, token = app_env
    reader = _make_user(app, "reader@example.com")
    reader_token = create_api_token(reader, settings)
    page = "handbook/leave.md"

    assert client.get("/api/ai/tree", headers=bearer(reader_token)).json()["books"] == []
    with Session(app.state.engine) as session:
        assert not resolve_access(session, reader, page).can_read

    group_id = _group_with_member(client, token, reader.id)
    created = client.post(
        "/api/admin/permissions",
        json={"group_id": group_id, "path_prefix": "handbook", "can_read": True},
        headers=bearer(token),
    )
    assert created.status_code == 201

    with Session(app.state.engine) as session:
        decision = resolve_access(session, reader, page)
    assert decision.can_read
    assert not decision.can_write
    books = client.get("/api/ai/tree", headers=bearer(reader_token)).json()["books"]
    assert [book["slug"] for book in books] == ["handbook"]


def test_revoking_a_grant_takes_effect_immediately_too(app_env, client, content):
    app, settings, _admin, token = app_env
    reader = _make_user(app, "reader@example.com")
    reader_token = create_api_token(reader, settings)
    group_id = _group_with_member(client, token, reader.id)
    permission_id = client.post(
        "/api/admin/permissions",
        json={"group_id": group_id, "path_prefix": "handbook"},
        headers=bearer(token),
    ).json()["id"]

    assert client.get("/api/ai/tree", headers=bearer(reader_token)).json()["books"]
    client.delete(f"/api/admin/permissions/{permission_id}", headers=bearer(token))
    assert client.get("/api/ai/tree", headers=bearer(reader_token)).json()["books"] == []


def test_book_without_read_grant_is_hidden(app_env, client, content):
    """A group without a book grant cannot discover that book in the tree."""

    app, settings, _admin, token = app_env
    reader = _make_user(app, "reader@example.com")
    reader_token = create_api_token(reader, settings)
    _group_with_member(client, token, reader.id)
    assert client.get("/api/ai/tree", headers=bearer(reader_token)).json()["books"] == []


def test_book_permissions_list_and_update_without_a_grant_gap(app_env, client, content):
    """The book matrix can discover paths and change an existing grant in place."""

    _app, _settings, _admin, token = app_env
    group_id = _group_with_member(client, token, 1)
    assert client.get("/api/admin/books", headers=bearer(token)).json() == [
        {"path": "archive"},
        {"path": "handbook"},
    ]
    created = client.post(
        "/api/admin/permissions",
        json={"group_id": group_id, "path_prefix": "handbook", "can_read": True},
        headers=bearer(token),
    )
    updated = client.put(
        f"/api/admin/permissions/{created.json()['id']}",
        json={"can_read": True, "can_write": True},
        headers=bearer(token),
    )
    assert updated.status_code == 200
    assert updated.json()["can_write"] is True


def test_featured_page_can_receive_an_exact_permission(app_env, client, content):
    app, _settings, admin, token = app_env
    content.feature_on_home("handbook/leave.md", "featured", admin)
    group_id = _group_with_member(client, token, admin.id)

    assert client.get("/api/admin/home-items", headers=bearer(token)).json() == [
        {"path": "handbook/leave.md", "kind": "page"}
    ]
    created = client.post(
        "/api/admin/permissions",
        json={"group_id": group_id, "path_prefix": "handbook/leave.md", "can_read": True},
        headers=bearer(token),
    )
    assert created.status_code == 201


def test_home_page_can_receive_an_explicit_write_grant(app_env, client, content):
    """``index.md`` classifies as a valid grant target, the same as a book.

    An administrator must be able to hand another group write access to
    Home explicitly -- Admin's own blanket grant already covers it, but any
    other group starts with no access to the reserved home path.
    """

    app, _settings, admin, token = app_env
    group_id = _group_with_member(client, token, admin.id)
    created = client.post(
        "/api/admin/permissions",
        json={"group_id": group_id, "path_prefix": "index.md", "can_read": True, "can_write": True},
        headers=bearer(token),
    )
    assert created.status_code == 201


@pytest.mark.parametrize(
    "prefix",
    ["", "   ", "..", "book/../secret", "book//page", "book/./page", "book\\page"],
)
def test_malformed_prefix_is_rejected(app_env, client, content, prefix):
    _app, _settings, _admin, token = app_env
    group_id = client.post(
        "/api/admin/groups", json={"name": "editors"}, headers=bearer(token)
    ).json()["id"]
    response = client.post(
        "/api/admin/permissions",
        json={"group_id": group_id, "path_prefix": prefix},
        headers=bearer(token),
    )
    assert response.status_code == 422
    assert response.json()["detail"]


def test_prefix_the_content_layer_could_never_produce_is_rejected(app_env, client, content):
    """The stricter content-path rules apply, or the grant would be a dead row.

    ``nul`` normalizes fine as a bare prefix but is a reserved name no page can
    be created under, so ``AccessPolicy.explain`` would reject every path that
    could have matched it.
    """

    _app, _settings, _admin, token = app_env
    group_id = client.post(
        "/api/admin/groups", json={"name": "editors"}, headers=bearer(token)
    ).json()["id"]
    response = client.post(
        "/api/admin/permissions",
        json={"group_id": group_id, "path_prefix": "handbook/nul.md"},
        headers=bearer(token),
    )
    assert response.status_code == 422
    assert "usable content path" in response.json()["detail"]


def test_padded_prefix_is_repaired_rather_than_rejected(app_env, client, content):
    """A leading or trailing slash is a typo, not a different grant."""

    _app, _settings, _admin, token = app_env
    group_id = client.post(
        "/api/admin/groups", json={"name": "editors"}, headers=bearer(token)
    ).json()["id"]
    response = client.post(
        "/api/admin/permissions",
        json={"group_id": group_id, "path_prefix": "  /handbook/  "},
        headers=bearer(token),
    )
    assert response.status_code == 201
    assert response.json()["path_prefix"] == "handbook"


def test_grant_to_a_target_that_does_not_exist_is_rejected(app_env, client, content):
    _app, _settings, _admin, token = app_env
    group_id = client.post(
        "/api/admin/groups", json={"name": "editors"}, headers=bearer(token)
    ).json()["id"]
    response = client.post(
        "/api/admin/permissions",
        json={"group_id": group_id, "path_prefix": "handbook/does-not-exist"},
        headers=bearer(token),
    )
    assert response.status_code == 422
    assert "No book or featured page exists" in response.json()["detail"]


def test_write_grant_without_read_is_rejected(app_env, client, content):
    _app, _settings, _admin, token = app_env
    group_id = client.post(
        "/api/admin/groups", json={"name": "editors"}, headers=bearer(token)
    ).json()["id"]
    response = client.post(
        "/api/admin/permissions",
        json={
            "group_id": group_id,
            "path_prefix": "handbook",
            "can_read": False,
            "can_write": True,
        },
        headers=bearer(token),
    )
    assert response.status_code == 422


def test_duplicate_grant_on_the_same_prefix_is_a_conflict(app_env, client, content):
    _app, _settings, _admin, token = app_env
    group_id = client.post(
        "/api/admin/groups", json={"name": "editors"}, headers=bearer(token)
    ).json()["id"]
    body = {"group_id": group_id, "path_prefix": "handbook"}
    first = client.post("/api/admin/permissions", json=body, headers=bearer(token))
    assert first.status_code == 201
    second = client.post("/api/admin/permissions", json=body, headers=bearer(token))
    assert second.status_code == 409


# --------------------------------------------------------------------------
# Orphaned-rule reporting
# --------------------------------------------------------------------------


def test_orphan_report_flags_a_deleted_target_and_spares_a_live_one(
    app_env, client, content, docs
):
    """Out-of-band edits strand grants; the report is how an admin finds them."""

    _app, _settings, _admin, token = app_env
    group_id = client.post(
        "/api/admin/groups", json={"name": "editors"}, headers=bearer(token)
    ).json()["id"]
    live = client.post(
        "/api/admin/permissions",
        json={"group_id": group_id, "path_prefix": "handbook"},
        headers=bearer(token),
    ).json()["id"]
    stranded = client.post(
        "/api/admin/permissions",
        json={"group_id": group_id, "path_prefix": "archive"},
        headers=bearer(token),
    ).json()["id"]

    assert client.get("/api/admin/permissions/orphaned", headers=bearer(token)).json() == []

    # Somebody removed the book with a text editor and a git commit.
    shutil.rmtree(docs / "archive")

    orphans = client.get("/api/admin/permissions/orphaned", headers=bearer(token)).json()
    assert [row["id"] for row in orphans] == [stranded]
    assert orphans[0]["reason"] == "missing_target"
    assert live not in [row["id"] for row in orphans]

    # Reporting is read-only: the row is still there until an admin removes it.
    assert stranded in [
        row["id"] for row in client.get("/api/admin/permissions", headers=bearer(token)).json()
    ]
    deleted = client.delete(f"/api/admin/permissions/{stranded}", headers=bearer(token))
    assert deleted.status_code == 200
    assert client.get("/api/admin/permissions/orphaned", headers=bearer(token)).json() == []


def test_orphan_report_also_flags_a_prefix_the_model_would_have_refused(app_env, client, content):
    """A row written around the app must still be visible as unusable."""

    app, _settings, _admin, token = app_env
    group_id = client.post(
        "/api/admin/groups", json={"name": "editors"}, headers=bearer(token)
    ).json()["id"]
    with Session(app.state.engine) as session:
        session.execute(
            text(
                "INSERT INTO permission (group_id, path_prefix, can_read, can_write) "
                "VALUES (:group_id, 'handbook//policies', 1, 0)"
            ),
            {"group_id": group_id},
        )
        session.commit()

    orphans = client.get("/api/admin/permissions/orphaned", headers=bearer(token)).json()
    assert [row["reason"] for row in orphans] == ["malformed_prefix"]


# --------------------------------------------------------------------------
# Password resets
# --------------------------------------------------------------------------


def test_password_reset_revokes_the_cookie_and_the_bearer_token(app_env, client, content):
    """One reset, both transports: either survivor would defeat the reset."""

    app, settings, _admin, token = app_env
    target = _make_user(app, "target@example.com")
    target_token = create_api_token(target, settings)

    with TestClient(app) as browser:
        login = browser.post(
            "/auth/login", json={"username": "target", "password": PASSWORD}
        )
        assert login.status_code == 200
        assert browser.get("/auth/session").status_code == 200
        assert client.get("/api/ai/tree", headers=bearer(target_token)).status_code == 200

        response = client.post(
            f"/api/admin/users/{target.id}/password",
            json={"password": NEW_PASSWORD},
            headers=bearer(token),
        )
        assert response.status_code == 200

        assert browser.cookies.get(SESSION_COOKIE_NAME)
        assert browser.get("/auth/session").status_code == 401
        assert client.get("/api/ai/tree", headers=bearer(target_token)).status_code == 401
        assert (
            browser.post(
                "/auth/login", json={"username": "target", "password": NEW_PASSWORD}
            ).status_code
            == 200
        )

    refreshed = _reload(app, target.id)
    assert refreshed.session_generation == target.session_generation + 1
    assert refreshed.api_token_generation == target.api_token_generation + 1


# --------------------------------------------------------------------------
# Last-administrator protection
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("patch", "/api/admin/users/{id}", {"is_admin": False}),
        ("patch", "/api/admin/users/{id}", {"is_active": False}),
        ("delete", "/api/admin/users/{id}", None),
    ],
)
def test_last_active_admin_cannot_be_removed(app_env, client, method, path, body):
    app, _settings, admin, token = app_env
    request = getattr(client, method)
    kwargs = {"headers": bearer(token)}
    if body is not None:
        kwargs["json"] = body

    response = request(path.format(id=admin.id), **kwargs)
    assert response.status_code == 409
    assert _active_admin_count(app) == 1


def test_a_second_admin_makes_the_first_removable(app_env, client):
    """The guard is about the last one, not about self-service."""

    app, _settings, admin, token = app_env
    _make_user(app, "second@example.com", is_admin=True)
    response = client.patch(
        f"/api/admin/users/{admin.id}", json={"is_admin": False}, headers=bearer(token)
    )
    assert response.status_code == 200
    assert response.json()["is_admin"] is False
    assert _active_admin_count(app) == 1


def test_an_inactive_admin_does_not_count_as_the_survivor(app_env, client):
    app, _settings, admin, token = app_env
    _make_user(app, "suspended@example.com", is_admin=True, is_active=False)
    response = client.patch(
        f"/api/admin/users/{admin.id}", json={"is_admin": False}, headers=bearer(token)
    )
    assert response.status_code == 409


def test_the_sole_admin_may_still_be_renamed(app_env, client):
    """The guard must not fire on a change that withdraws no authority."""

    _app, _settings, admin, token = app_env
    response = client.patch(
        f"/api/admin/users/{admin.id}", json={"display_name": "Renamed"}, headers=bearer(token)
    )
    assert response.status_code == 200
    assert response.json()["display_name"] == "Renamed"


def test_concurrent_demotions_cannot_remove_the_last_admin(app_env, monkeypatch):
    """Two requests that both see two admins must not both succeed.

    The barrier holds each request open at the point where it has read the
    target user and has not yet written, which is the exact window a
    ``SELECT COUNT(*)``-then-``UPDATE`` implementation loses: Python's
    ``sqlite3`` runs that SELECT in autocommit, so both requests would read
    "two admins" and both would commit.  The check is folded into the mutating
    statement instead, so the loser re-evaluates it under the write lock.
    """

    app, _settings, admin, token = app_env
    second = _make_user(app, "second@example.com", is_admin=True)
    assert _active_admin_count(app) == 2

    import app.admin_api as admin_api

    original = admin_api._require_user
    barrier = threading.Barrier(2, timeout=10)
    # update_user calls _require_user twice per request — once to confirm the
    # target exists, again to build the response after the write. Only the
    # first call is the pre-write read-then-decide moment the barrier needs to
    # hold open; waiting on both would need 4 arrivals for 2 requests and the
    # barrier would mispair them.
    waited = threading.local()

    def stalled_require_user(session, user_id):
        user = original(session, user_id)
        if not getattr(waited, "done", False):
            waited.done = True
            barrier.wait()
        return user

    monkeypatch.setattr(admin_api, "_require_user", stalled_require_user)

    statuses: dict[int, int] = {}

    def demote(user_id: int) -> None:
        with TestClient(app) as caller:
            statuses[user_id] = caller.patch(
                f"/api/admin/users/{user_id}",
                json={"is_admin": False},
                headers=bearer(token),
            ).status_code

    threads = [
        threading.Thread(target=demote, args=(uid,)) for uid in (admin.id, second.id)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()

    assert sorted(statuses.values()) == [200, 409]
    assert _active_admin_count(app) == 1


def test_concurrent_deletions_cannot_remove_the_last_admin(app_env, monkeypatch):
    """The delete path carries the same guard as the demote path."""

    app, _settings, admin, token = app_env
    second = _make_user(app, "second@example.com", is_admin=True)

    import app.admin_api as admin_api

    original = admin_api._require_user
    barrier = threading.Barrier(2, timeout=10)

    def stalled_require_user(session, user_id):
        user = original(session, user_id)
        barrier.wait()
        return user

    monkeypatch.setattr(admin_api, "_require_user", stalled_require_user)

    statuses: dict[int, int] = {}

    def remove(user_id: int) -> None:
        with TestClient(app) as caller:
            statuses[user_id] = caller.delete(
                f"/api/admin/users/{user_id}", headers=bearer(token)
            ).status_code

    threads = [
        threading.Thread(target=remove, args=(uid,)) for uid in (admin.id, second.id)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()

    assert sorted(statuses.values()) == [200, 409]
    assert _active_admin_count(app) == 1


# --------------------------------------------------------------------------
# Users, groups, memberships
# --------------------------------------------------------------------------


def test_created_user_can_authenticate_with_the_password_the_admin_set(app_env, client):
    """There is no mail transport, so the initial password is set directly."""

    app, _settings, _admin, token = app_env
    response = client.post(
        "/api/admin/users",
        json={
            "username": "new-person",
            "email": "New.Person@Example.com",
            "display_name": "New Person",
            "password": NEW_PASSWORD,
        },
        headers=bearer(token),
    )
    assert response.status_code == 201
    assert response.json()["email"] == "new.person@example.com"
    with TestClient(app) as browser:
        login = browser.post(
            "/auth/login", json={"username": "new-person", "password": NEW_PASSWORD}
        )
        assert login.status_code == 200
        assert login.json()["must_change_password"] is False


def test_duplicate_email_is_a_conflict(app_env, client):
    _app, _settings, _admin, token = app_env
    body = {
        "username": "impostor",
        "email": "admin@example.com",
        "display_name": "Impostor",
        "password": NEW_PASSWORD,
    }
    assert client.post("/api/admin/users", json=body, headers=bearer(token)).status_code == 409


def test_deactivated_user_loses_access_and_can_be_reactivated(app_env, client, content):
    app, settings, _admin, token = app_env
    reader = _make_user(app, "reader@example.com")
    reader_token = create_api_token(reader, settings)
    assert client.get("/api/ai/tree", headers=bearer(reader_token)).status_code == 200

    client.patch(f"/api/admin/users/{reader.id}", json={"is_active": False}, headers=bearer(token))
    assert client.get("/api/ai/tree", headers=bearer(reader_token)).status_code == 401

    client.patch(f"/api/admin/users/{reader.id}", json={"is_active": True}, headers=bearer(token))
    assert client.get("/api/ai/tree", headers=bearer(reader_token)).status_code == 200


def test_promoting_a_user_grants_the_admin_bypass(app_env, client, content):
    app, settings, _admin, token = app_env
    reader = _make_user(app, "reader@example.com")
    reader_token = create_api_token(reader, settings)
    assert client.get("/api/admin/users", headers=bearer(reader_token)).status_code == 403

    client.patch(f"/api/admin/users/{reader.id}", json={"is_admin": True}, headers=bearer(token))
    assert client.get("/api/admin/users", headers=bearer(reader_token)).status_code == 200


def test_membership_add_and_remove_are_idempotent(app_env, client):
    app, _settings, _admin, token = app_env
    reader = _make_user(app, "reader@example.com")
    group_id = _group_with_member(client, token, reader.id)

    assert client.put(
        f"/api/admin/groups/{group_id}/members/{reader.id}", headers=bearer(token)
    ).status_code == 200
    members = client.get(f"/api/admin/groups/{group_id}/members", headers=bearer(token)).json()
    assert [member["id"] for member in members] == [reader.id]

    for _ in range(2):
        assert client.delete(
            f"/api/admin/groups/{group_id}/members/{reader.id}", headers=bearer(token)
        ).status_code == 200
    assert client.get(f"/api/admin/groups/{group_id}/members", headers=bearer(token)).json() == []


def test_membership_on_a_missing_group_or_user_is_not_found(app_env, client):
    app, _settings, _admin, token = app_env
    reader = _make_user(app, "reader@example.com")
    group_id = _group_with_member(client, token, reader.id)
    assert client.put(
        f"/api/admin/groups/{group_id}/members/9999", headers=bearer(token)
    ).status_code == 404
    assert client.put(
        f"/api/admin/groups/9999/members/{reader.id}", headers=bearer(token)
    ).status_code == 404


def test_deleting_a_group_cascades_memberships_and_grants(app_env, client, content):
    """The foreign keys already cascade; nothing is cleaned up by hand."""

    app, _settings, _admin, token = app_env
    reader = _make_user(app, "reader@example.com")
    group_id = _group_with_member(client, token, reader.id)
    client.post(
        "/api/admin/permissions",
        json={"group_id": group_id, "path_prefix": "handbook"},
        headers=bearer(token),
    )
    with Session(app.state.engine) as session:
        assert session.exec(select(UserGroup).where(UserGroup.group_id == group_id)).all()
        assert session.exec(select(Permission).where(Permission.group_id == group_id)).all()

    assert client.delete(f"/api/admin/groups/{group_id}", headers=bearer(token)).status_code == 200

    with Session(app.state.engine) as session:
        assert session.exec(select(UserGroup).where(UserGroup.group_id == group_id)).all() == []
        assert session.exec(select(Permission).where(Permission.group_id == group_id)).all() == []
        # The member itself survives; only the association does not.
        assert session.get(User, reader.id) is not None


def test_deleting_a_user_cascades_only_their_memberships(app_env, client):
    app, _settings, _admin, token = app_env
    _make_user(app, "keeper@example.com", is_admin=True)
    reader = _make_user(app, "reader@example.com")
    group_id = _group_with_member(client, token, reader.id)

    assert client.delete(f"/api/admin/users/{reader.id}", headers=bearer(token)).status_code == 200
    with Session(app.state.engine) as session:
        assert session.exec(select(UserGroup).where(UserGroup.user_id == reader.id)).all() == []
    assert client.get(f"/api/admin/groups/{group_id}/members", headers=bearer(token)).json() == []


def test_primary_admin_account_cannot_be_deleted(app_env, client):
    _app, _settings, admin, token = app_env
    response = client.delete(f"/api/admin/users/{admin.id}", headers=bearer(token))
    assert response.status_code == 409
    assert "cannot be deleted" in response.json()["detail"]


# --------------------------------------------------------------------------
# Conflict diagnostics
# --------------------------------------------------------------------------


def test_equal_specificity_conflict_is_explained(app_env, client, content):
    """A cross-group tie at the same depth denies, and says which rules did it."""

    app, _settings, _admin, token = app_env
    reader = _make_user(app, "reader@example.com")
    allow_group = _group_with_member(client, token, reader.id, name="allow")
    deny_group = _group_with_member(client, token, reader.id, name="deny")
    for group_id, can_read in ((allow_group, True), (deny_group, False)):
        client.post(
            "/api/admin/permissions",
            json={"group_id": group_id, "path_prefix": "handbook", "can_read": can_read},
            headers=bearer(token),
        )

    explanation = client.get(
        f"/api/admin/users/{reader.id}/access",
        params={"path": "handbook/leave.md"},
        headers=bearer(token),
    ).json()
    assert explanation["can_read"] is False
    assert explanation["reason"] == "read_denied_at_greatest_specificity"
    assert sorted(rule["group_id"] for rule in explanation["decisive_rules"]) == sorted(
        [allow_group, deny_group]
    )
    assert {rule["depth"] for rule in explanation["decisive_rules"]} == {1}


def test_nested_permission_target_is_rejected(app_env, client, content):
    """Pages inherit the book grant; only a book may be an ACL target."""

    _app, _settings, _admin, token = app_env
    group_id = _group_with_member(client, token, 1)
    response = client.post(
        "/api/admin/permissions",
        json={"group_id": group_id, "path_prefix": "handbook/leave.md"},
        headers=bearer(token),
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------
# Audit logging
# --------------------------------------------------------------------------


def test_audit_log_records_the_action_without_the_password(app_env, client, caplog):
    """The trail says who reset whose password, never what it was set to."""

    app, _settings, admin, token = app_env
    target = _make_user(app, "target@example.com")
    with caplog.at_level(logging.INFO, logger="unstacked.audit"):
        client.post(
            f"/api/admin/users/{target.id}/password",
            json={"password": NEW_PASSWORD},
            headers=bearer(token),
        )

    records = [record for record in caplog.records if record.name == "unstacked.audit"]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "admin.user.password_reset" in message
    assert f"actor_id={admin.id}" in message
    assert f"user_id={target.id}" in message
    assert NEW_PASSWORD not in caplog.text
    assert "$argon2" not in caplog.text
    assert _reload(app, target.id).password_hash not in caplog.text


def test_audit_log_never_carries_a_content_body(app_env, client, content, caplog):
    """Grant records name paths and flags, not what lives at those paths."""

    _app, _settings, _admin, token = app_env
    group_id = client.post(
        "/api/admin/groups", json={"name": "editors"}, headers=bearer(token)
    ).json()["id"]
    with caplog.at_level(logging.INFO, logger="unstacked.audit"):
        client.post(
            "/api/admin/permissions",
            json={"group_id": group_id, "path_prefix": "handbook"},
            headers=bearer(token),
        )
    message = [record for record in caplog.records if record.name == "unstacked.audit"][-1]
    assert "path_prefix=handbook" in message.getMessage()
    assert "# Leave" not in caplog.text


@pytest.mark.parametrize(
    "field", ["password", "new_password", "api_token", "password_hash", "markdown", "body"]
)
def test_audit_helper_refuses_a_field_that_could_carry_a_secret(app_env, field):
    """A structural guarantee, so a future route cannot log one by accident."""

    _app, _settings, admin, _token = app_env
    with pytest.raises(ValueError):
        _audit("admin.test", admin, **{field: "value"})


# --------------------------------------------------------------------------
# Branding: trimmed to name + logo only (Home's copy now lives in index.md)
# --------------------------------------------------------------------------


def test_branding_response_no_longer_carries_home_copy_fields(app_env, client):
    """Branding is name + logo only; Home's copy moved to ``index.md``."""

    _app, _settings, _admin, token = app_env
    body = client.get("/api/admin/branding", headers=bearer(token)).json()
    assert set(body) == {"name", "logo_url", "updated_at"}


def test_branding_update_ignores_home_copy_fields_if_supplied(app_env, client):
    """Extra legacy fields in the request body are simply ignored, not stored."""

    _app, _settings, _admin, token = app_env
    response = client.put(
        "/api/admin/branding",
        json={
            "name": "Renamed Workspace",
            "home_eyebrow": "SHOULD BE IGNORED",
            "home_title": "SHOULD BE IGNORED",
            "home_description": "SHOULD BE IGNORED",
            "featured_label": "SHOULD BE IGNORED",
        },
        headers=bearer(token),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed Workspace"
    assert set(body) == {"name", "logo_url", "updated_at"}


# --------------------------------------------------------------------------
# Home page reset (Settings' one admin action for the home page)
# --------------------------------------------------------------------------


def test_reset_home_page_restores_starter_content_via_update_home_page(app_env, client):
    """The reset action is one ordinary ``update_home_page`` commit, not a raw overwrite."""

    app, _settings, admin, token = app_env
    content = app.state.content
    base_blob_sha = content.home_page_blob_sha()
    content.update_home_page(
        "Hand-authored home copy that must be discarded by reset.",
        [],
        admin,
        base_blob_sha=base_blob_sha,
        title="Custom Home Title",
    )
    metadata, body, _raw = content.read_home_page()
    assert "Hand-authored" in body

    response = client.post("/api/admin/home/reset", json={}, headers=bearer(token))
    assert response.status_code == 200

    metadata, body, _raw = content.read_home_page()
    assert "Hand-authored" not in body
    assert metadata["title"] == "Home"
    assert metadata["widgets"] == [{"id": "featured", "type": "featured", "config": {}}]


def test_reset_home_page_requires_admin(app_env, client):
    app, settings, _admin, _token = app_env
    reader = _make_user(app, "reset-reader@example.com")
    token = create_api_token(reader, settings)
    assert client.post("/api/admin/home/reset", json={}, headers=bearer(token)).status_code == 403


# --------------------------------------------------------------------------
# Home page visibility (publish Home for unauthenticated visitors)
# --------------------------------------------------------------------------


def test_home_visibility_defaults_to_private_and_can_be_toggled(app_env, client):
    app, _settings, _admin, token = app_env
    content = app.state.content

    assert client.get("/api/admin/home/visibility", headers=bearer(token)).json() == {
        "public": False
    }

    made_public = client.put(
        "/api/admin/home/visibility", json={"public": True}, headers=bearer(token)
    )
    assert made_public.status_code == 200
    assert made_public.json() == {"public": True}
    metadata, _body, _raw = content.read_home_page()
    assert metadata["public"] is True

    made_private = client.put(
        "/api/admin/home/visibility", json={"public": False}, headers=bearer(token)
    )
    assert made_private.json() == {"public": False}
    metadata, _body, _raw = content.read_home_page()
    assert metadata["public"] is False


def test_home_visibility_survives_an_ordinary_home_page_edit(app_env, client):
    """``public`` is an unknown field to update_home_page -- it must round-trip
    through the same raw-metadata preservation every other custom front
    matter key gets, not be silently dropped by the next save."""

    app, _settings, admin, token = app_env
    content = app.state.content
    client.put("/api/admin/home/visibility", json={"public": True}, headers=bearer(token))

    content.update_home_page(
        "Updated body", [], admin, base_blob_sha=content.home_page_blob_sha()
    )

    metadata, _body, _raw = content.read_home_page()
    assert metadata["public"] is True


def test_home_visibility_requires_admin(app_env, client):
    app, settings, _admin, _token = app_env
    reader = _make_user(app, "visibility-reader@example.com")
    token = create_api_token(reader, settings)
    assert client.get("/api/admin/home/visibility", headers=bearer(token)).status_code == 403
    assert (
        client.put(
            "/api/admin/home/visibility", json={"public": True}, headers=bearer(token)
        ).status_code
        == 403
    )
