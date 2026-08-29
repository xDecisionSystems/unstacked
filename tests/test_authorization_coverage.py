"""Regression coverage for authorization at the API and service boundaries.

The pure ACL truth table is deliberately separate in ``test_acl.py``.  These
tests make sure a future route or transport cannot accidentally skip the
``AuthorizationContext`` checks that turn that policy into a security boundary.
"""

import pytest
from sqlmodel import Session

from app.acl import AccessDenied, AuthorizationContext
from app.auth import create_api_token, hash_password
from app.models import Group, Permission, User, UserGroup
from tests.conftest import bearer


def _seed_private_and_shared_content(app, admin: User) -> str:
    """Create two books and return the shared page's first revision."""

    with Session(app.state.engine) as session:
        persisted_admin = session.get(User, admin.id)
        assert persisted_admin is not None
        service = app.state.ai_service
        authorization = AuthorizationContext(session, persisted_admin)
        service.create_book(authorization, title="Shared", slug=None)
        shared = service.create_page(
            authorization,
            parent="shared",
            title="Read Only",
            slug=None,
            markdown="shared body",
            tags=[],
            draft=False,
        )
        service.create_book(authorization, title="Private", slug=None)
        service.create_page(
            authorization,
            parent="private",
            title="Secret",
            slug=None,
            markdown="private body",
            tags=[],
            draft=False,
        )
        return shared.commit


def _read_only_user(session: Session) -> User:
    user = User(
        username="read-only",
        email="read-only@example.com",
        password_hash=hash_password("reader password is sufficiently long"),
        display_name="Read Only",
    )
    group = Group(name="read-only-group")
    session.add_all([user, group])
    session.commit()
    session.refresh(user)
    session.refresh(group)
    session.add_all(
        [
            UserGroup(user_id=user.id, group_id=group.id),
            Permission(group_id=group.id, path_prefix="shared", can_read=True),
        ]
    )
    session.commit()
    return user


def test_api_hides_unreadable_history_and_asset_books_like_missing_paths(client, app_env):
    """Read routes must not become existence oracles outside ``get_content``."""

    app, settings, admin, _token = app_env
    _seed_private_and_shared_content(app, admin)
    with Session(app.state.engine) as session:
        reader = _read_only_user(session)
        token = create_api_token(reader, settings)
    headers = bearer(token)

    unreadable_history = client.get("/api/ai/history/private/secret.md", headers=headers)
    missing_history = client.get("/api/ai/history/private/absent.md", headers=headers)
    assert (unreadable_history.status_code, unreadable_history.json()) == (
        missing_history.status_code,
        missing_history.json(),
    ) == (404, {"detail": "Content not found"})

    unreadable_assets = client.get("/api/ai/books/private/assets", headers=headers)
    missing_assets = client.get("/api/ai/books/absent/assets", headers=headers)
    assert (unreadable_assets.status_code, unreadable_assets.json()) == (
        missing_assets.status_code,
        missing_assets.json(),
    ) == (404, {"detail": "Content not found"})


def test_service_and_api_keep_admin_and_write_operations_behind_authorization(app_env, client):
    """Direct callers cannot bypass the same checks the REST routes apply."""

    app, settings, admin, _token = app_env
    revision = _seed_private_and_shared_content(app, admin)
    with Session(app.state.engine) as session:
        reader = _read_only_user(session)
        authorization = AuthorizationContext(session, reader)
        service = app.state.ai_service

        # The service is its own authorization boundary, not a helper that
        # trusts a future transport to have performed these checks first.
        with pytest.raises(AccessDenied):
            service.create_book(authorization, title="Forbidden", slug=None)
        with pytest.raises(AccessDenied):
            service.create_chapter(
                authorization, book_slug="shared", title="Forbidden", slug=None
            )
        with pytest.raises(AccessDenied):
            service.move_page(authorization, "shared/read-only.md", None, None)
        with pytest.raises(AccessDenied):
            service.update_page(authorization, "shared/read-only.md")
        with pytest.raises(AccessDenied):
            service.restore_page(authorization, "shared/read-only.md", revision)

        token = create_api_token(reader, settings)
    headers = bearer(token)
    assert (
        client.post("/api/ai/books", json={"title": "Forbidden"}, headers=headers).status_code
        == 403
    )
    # A readable-but-read-only parent must not be writable through the route,
    # for a chapter same as a page -- both need a write grant, not admin, so
    # both fold AccessDenied into the same indistinguishable-from-missing 404.
    assert (
        client.post(
            "/api/ai/books/shared/chapters",
            json={"title": "Forbidden"},
            headers=headers,
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/ai/books/shared/pages",
            json={"title": "Forbidden", "markdown": "must not be saved"},
            headers=headers,
        ).status_code
        == 404
    )
