from datetime import datetime, timedelta, timezone
from io import BytesIO
from zipfile import ZipFile

import jwt
import pytest
from git import Repo
from sqlmodel import Session

from app.acl import AccessDenied, AuthorizationContext
from app.ai_api import DIFF_RESPONSE_OVERHEAD_BYTES, MAX_PAGE_MARKDOWN_CHARS
from app.auth import create_api_token, hash_password
from app.models import Group, Permission, User, UserGroup
from tests.conftest import bearer


def test_admin_can_create_and_download_complete_content(client, app_env):
    _app, settings, _admin, token = app_env
    headers = bearer(token)

    book = client.post("/api/ai/books", json={"title": "Operations"}, headers=headers)
    assert book.status_code == 201
    assert book.json()["path"] == "operations"

    chapter = client.post(
        "/api/ai/books/operations/chapters",
        json={"title": "Runbooks"},
        headers=headers,
    )
    assert chapter.status_code == 201

    page = client.post(
        "/api/ai/books/operations/chapters/runbooks/pages",
        json={
            "title": "Restart Service",
            "markdown": "# Restart Service\n\nUse the safe restart procedure.",
            "tags": ["operations"],
        },
        headers=headers,
    )
    assert page.status_code == 201
    assert page.json()["path"] == "operations/runbooks/restart-service.md"

    tree = client.get("/api/ai/tree", headers=headers)
    assert tree.status_code == 200
    assert tree.json()["books"][0]["chapters"][0]["pages"] == [
        "operations/runbooks/restart-service.md"
    ]

    content = client.get("/api/ai/content/operations/runbooks/restart-service.md", headers=headers)
    assert content.status_code == 200
    assert content.json()["metadata"]["title"] == "Restart Service"
    assert "safe restart" in content.json()["markdown"]

    download = client.get(
        "/api/ai/content/operations/runbooks/restart-service.md?download=true",
        headers=headers,
    )
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("text/markdown")
    assert "title: Restart Service" in download.text

    export = client.get("/api/ai/export", headers=headers)
    assert export.status_code == 200
    with ZipFile(BytesIO(export.content)) as archive:
        assert "docs/operations/runbooks/restart-service.md" in archive.namelist()

    repo = Repo(settings.content_repo_path)
    commits = list(repo.iter_commits())
    assert len(commits) == 4
    assert commits[0].author.email == "admin@example.com"
    assert not repo.is_dirty(untracked_files=True)


def test_non_admin_can_create_page_only_with_parent_write(client, app_env):
    app, settings, _admin, admin_token = app_env
    admin_headers = bearer(admin_token)
    assert (
        client.post(
            "/api/ai/books", json={"title": "Engineering"}, headers=admin_headers
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/ai/books/engineering/chapters",
            json={"title": "Guides"},
            headers=admin_headers,
        ).status_code
        == 201
    )

    with Session(app.state.engine) as session:
        user = User(
            username="writer",
            email="writer@example.com",
            password_hash=hash_password("writer password is sufficiently long"),
            display_name="Writer Agent",
        )
        group = Group(name="writers")
        session.add(user)
        session.add(group)
        session.commit()
        session.refresh(user)
        session.refresh(group)
        session.add(UserGroup(user_id=user.id, group_id=group.id))
        session.add(
            Permission(
                group_id=group.id,
                path_prefix="engineering/guides",
                can_read=True,
                can_write=True,
            )
        )
        session.commit()
        writer_token = create_api_token(user, settings)

    headers = bearer(writer_token)
    denied_book = client.post("/api/ai/books", json={"title": "Forbidden"}, headers=headers)
    assert denied_book.status_code == 403

    created = client.post(
        "/api/ai/books/engineering/chapters/guides/pages",
        json={"title": "Agent Guide", "markdown": "# Agent Guide"},
        headers=headers,
    )
    assert created.status_code == 201

    forbidden = client.get("/api/ai/content/other/private.md", headers=headers)
    assert forbidden.status_code == 404
    tree = client.get("/api/ai/tree", headers=headers).json()
    assert tree["books"][0]["slug"] == "engineering"


def test_unreadable_and_missing_pages_have_the_same_public_response(client, app_env):
    app, _settings, _admin, token = app_env
    headers = bearer(token)
    response = client.post("/api/ai/books", json={"title": "Private"}, headers=headers)
    assert response.status_code == 201
    assert (
        client.post(
            "/api/ai/books/private/pages",
            json={"title": "Secret", "markdown": "do not disclose"},
            headers=headers,
        ).status_code
        == 201
    )
    with Session(app.state.engine) as session:
        reader = User(
            username="reader",
            email="reader@example.com",
            password_hash=hash_password("reader password is sufficiently long"),
            display_name="Reader",
        )
        session.add(reader)
        session.commit()
        session.refresh(reader)
        reader_token = create_api_token(reader, app.state.settings)

    unreadable = client.get("/api/ai/content/private/secret.md", headers=bearer(reader_token))
    missing = client.get("/api/ai/content/private/missing.md", headers=bearer(reader_token))
    assert (unreadable.status_code, unreadable.json()) == (missing.status_code, missing.json())
    assert unreadable.status_code == 404


def test_stale_or_descendant_grants_block_create_and_delete(client, app_env):
    app, _settings, admin, token = app_env
    headers = bearer(token)
    assert client.post("/api/ai/books", json={"title": "Ops"}, headers=headers).status_code == 201
    with Session(app.state.engine) as session:
        group = Group(name="protected-paths")
        session.add(group)
        session.commit()
        session.refresh(group)
        session.add(
            Permission(group_id=group.id, path_prefix="ops/future.md", can_read=True)
        )
        session.add(
            Permission(group_id=group.id, path_prefix="ops/descendant", can_read=True)
        )
        session.commit()
        persisted_admin = session.get(User, admin.id)
        authorization = AuthorizationContext(session, persisted_admin)
        with pytest.raises(AccessDenied):
            app.state.ai_service.create_page(
                authorization,
                parent="ops",
                title="Future",
                slug=None,
                markdown="body",
                tags=[],
                draft=False,
            )
        with pytest.raises(AccessDenied):
            app.state.ai_service.delete_book(authorization, "ops")


def test_authentication_validation_and_collisions(client, app_env):
    _app, _settings, _admin, token = app_env
    assert client.get("/api/ai/tree").status_code == 401
    headers = bearer(token)
    assert (
        client.post(
            "/api/ai/books", json={"title": "Bad", "slug": "../bad"}, headers=headers
        ).status_code
        == 404
    )
    assert (
        client.post("/api/ai/books", json={"title": "Duplicate"}, headers=headers).status_code
        == 201
    )
    assert (
        client.post("/api/ai/books", json={"title": "Duplicate"}, headers=headers).status_code
        == 409
    )


def test_password_exchange_issues_bearer_token(client):
    response = client.post(
        "/api/auth/token",
        json={"username": "admin", "password": "correct horse battery staple"},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    assert client.get("/api/ai/tree", headers=bearer(token)).status_code == 200


def test_search_endpoint_returns_only_acl_readable_results(client, app_env):
    app, settings, _admin, admin_token = app_env
    admin_headers = bearer(admin_token)
    assert (
        client.post("/api/ai/books", json={"title": "Public"}, headers=admin_headers).status_code
        == 201
    )
    assert (
        client.post("/api/ai/books", json={"title": "Secret"}, headers=admin_headers).status_code
        == 201
    )
    assert (
        client.post(
            "/api/ai/books/public/pages",
            json={"title": "Guide", "markdown": "find-this", "tags": ["visible"]},
            headers=admin_headers,
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/ai/books/secret/pages",
            json={"title": "Hidden", "markdown": "find-this", "tags": ["private"]},
            headers=admin_headers,
        ).status_code
        == 201
    )
    with Session(app.state.engine) as session:
        reader = User(
            username="search-reader",
            email="search-reader@example.com",
            password_hash=hash_password("reader password is sufficiently long"),
            display_name="Search Reader",
        )
        group = Group(name="public-searchers")
        session.add_all([reader, group])
        session.commit()
        session.refresh(reader)
        session.refresh(group)
        session.add_all(
            [
                UserGroup(user_id=reader.id, group_id=group.id),
                Permission(group_id=group.id, path_prefix="public", can_read=True),
            ]
        )
        session.commit()
        reader_token = create_api_token(reader, settings)

    response = client.get(
        "/api/ai/search", params={"query": "find-this"}, headers=bearer(reader_token)
    )
    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "path": "public/guide.md",
                "title": "Guide",
                "tags": ["visible"],
                "snippet": "find-this",
            }
        ],
        "page": 1,
        "page_size": 20,
        "total": 1,
        "truncated": False,
    }


def test_search_endpoint_authentication_pagination_and_input_bounds(client, app_env):
    _app, settings, _admin, token = app_env
    headers = bearer(token)
    assert client.get("/api/ai/search", params={"query": "needle"}).status_code == 401
    assert (
        client.post("/api/ai/books", json={"title": "Guides"}, headers=headers).status_code == 201
    )
    for title in ("Alpha", "Beta"):
        assert (
            client.post(
                "/api/ai/books/guides/pages",
                json={"title": title, "markdown": "needle"},
                headers=headers,
            ).status_code
            == 201
        )

    page = client.get(
        "/api/ai/search", params={"query": "needle", "page": 2, "page_size": 1}, headers=headers
    )
    assert page.status_code == 200
    assert page.json()["page"] == 2
    assert page.json()["page_size"] == 1
    assert page.json()["total"] == 2
    assert [item["path"] for item in page.json()["items"]] == ["guides/beta.md"]

    invalid = client.get(
        "/api/ai/search",
        params={"query": "x" * (settings.max_search_query_chars + 1)},
        headers=headers,
    )
    assert invalid.status_code == 422
    assert "length limit" in invalid.json()["detail"]


def test_rest_rejects_oversized_page_payload_before_a_content_write(client, app_env):
    _app, _settings, _admin, token = app_env

    response = client.post(
        "/api/ai/books/does-not-matter/pages",
        json={"title": "Too large", "markdown": "x" * (MAX_PAGE_MARKDOWN_CHARS + 1)},
        headers=bearer(token),
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "markdown"]
    assert "at most" in response.json()["detail"][0]["msg"]


def test_rest_rejects_utf8_diff_larger_than_its_response_budget(client, app_env, monkeypatch):
    app, settings, _admin, token = app_env
    # Keep the test small while proving the check measures encoded bytes, not
    # characters: each emoji below occupies four UTF-8 bytes.
    settings.max_page_bytes = 16
    limit = (settings.max_page_bytes * 2) + DIFF_RESPONSE_OVERHEAD_BYTES
    monkeypatch.setattr(app.state.ai_service, "page_diff", lambda *_args: "🙂" * ((limit // 4) + 1))

    response = client.get(
        "/api/ai/history/anything/page.md/diff",
        params={"from_revision": "a" * 7, "to_revision": "b" * 7},
        headers=bearer(token),
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "Diff exceeds the configured response size limit"}


def test_llm_md_is_available_from_the_app(client):
    response = client.get("/llm.md")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "### user" in response.text


def test_page_history_diff_and_restore_are_git_backed(client, app_env):
    app, settings, _admin, token = app_env
    headers = bearer(token)
    book = client.post("/api/ai/books", json={"title": "Handbook"}, headers=headers)
    assert book.status_code == 201
    created = client.post(
        "/api/ai/books/handbook/pages",
        json={"title": "Welcome", "markdown": "first version"},
        headers=headers,
    )
    assert created.status_code == 201
    path = created.json()["path"]
    initial_revision = created.json()["commit"]

    page = settings.content_repo_path / "docs" / path
    original = page.read_text(encoding="utf-8")
    page.write_text(original.replace("first version", "second version"), encoding="utf-8")
    updated_revision = app.state.content.git.commit_paths(
        [page],
        name="Admin Agent",
        email="admin@example.com",
        message="Update page: handbook/welcome.md",
    )

    history = client.get(f"/api/ai/history/{path}", headers=headers)
    assert history.status_code == 200
    assert [entry["sha"] for entry in history.json()] == [updated_revision, initial_revision]

    diff = client.get(
        f"/api/ai/history/{path}/diff",
        params={"from_revision": initial_revision, "to_revision": updated_revision},
        headers=headers,
    )
    assert diff.status_code == 200
    assert "-first version" in diff.json()["diff"]
    assert "+second version" in diff.json()["diff"]

    restored = client.post(
        f"/api/ai/history/{path}/restore",
        json={"revision": initial_revision},
        headers=headers,
    )
    assert restored.status_code == 200
    assert restored.json()["commit"] not in {initial_revision, updated_revision}
    page_after_restore = client.get(f"/api/ai/content/{path}", headers=headers)
    assert "first version" in page_after_restore.json()["markdown"]

    restored_history = client.get(f"/api/ai/history/{path}", headers=headers).json()
    assert restored_history[0]["sha"] == restored.json()["commit"]
    assert restored_history[0]["message"].startswith("Restore page:")
    assert Repo(settings.content_repo_path).head.commit.parents[0].hexsha == updated_revision


def test_password_exchange_is_rate_limited(client):
    for _ in range(5):
        response = client.post(
            "/api/auth/token",
            json={"username": "nobody", "password": "incorrect-password"},
        )
        assert response.status_code == 401
    response = client.post(
        "/api/auth/token",
        json={"username": "nobody", "password": "incorrect-password"},
    )
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"


def test_ai_requests_are_rate_limited_per_authenticated_user(client, app_env):
    """Token rotation and a shared client address cannot evade or share a budget."""

    app, settings, _admin, admin_token = app_env
    settings.ai_requests_per_minute = 2
    with Session(app.state.engine) as session:
        second_user = User(
            username="second-user",
            email="second@example.com",
            password_hash=hash_password("another correct horse battery staple"),
            display_name="Second User",
        )
        session.add(second_user)
        session.commit()
        session.refresh(second_user)
        second_token = create_api_token(second_user, settings)

    for token in (admin_token, create_api_token(_admin, settings)):
        assert client.get("/api/ai/tree", headers=bearer(token)).status_code == 200

    limited = client.get("/api/ai/tree", headers=bearer(admin_token))
    assert limited.status_code == 429
    assert limited.json() == {"detail": "Too many AI API requests"}
    assert limited.headers["retry-after"]

    # TestClient uses one client address for both accounts; the second account
    # must still retain its own principal-keyed budget.
    assert client.get("/api/ai/tree", headers=bearer(second_token)).status_code == 200


def test_incrementing_token_generation_revokes_existing_token(client, app_env):
    app, _settings, admin, token = app_env
    assert client.get("/api/ai/tree", headers=bearer(token)).status_code == 200
    with Session(app.state.engine) as session:
        persisted = session.get(User, admin.id)
        persisted.api_token_generation += 1
        session.add(persisted)
        session.commit()
    assert client.get("/api/ai/tree", headers=bearer(token)).status_code == 401


def _signed_token(settings, user: User, **overrides: object) -> str:
    """Build a deliberately controlled token for negative verification cases."""

    now = datetime.now(timezone.utc)
    payload: dict[str, object] = {
        "sub": str(user.id),
        "generation": user.api_token_generation,
        "iat": now,
        "exp": now + timedelta(hours=1),
        "aud": settings.api_token_audience,
        "jti": "test-jti",
    }
    payload.update(overrides)
    return jwt.encode(payload, settings.token_secret, algorithm="HS256")


def test_bearer_tokens_reject_expiry_wrong_audience_and_tampering(client, app_env):
    _app, settings, admin, _token = app_env
    expired = _signed_token(settings, admin, exp=datetime.now(timezone.utc) - timedelta(seconds=1))
    wrong_audience = _signed_token(settings, admin, aud="another-service")
    valid = _signed_token(settings, admin)
    tampered = f"{valid[:-1]}{'A' if valid[-1] != 'A' else 'B'}"

    for token in (expired, wrong_audience, tampered):
        response = client.get("/api/ai/tree", headers=bearer(token))
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"


def test_bearer_token_rechecks_active_user_and_generation(client, app_env):
    app, settings, admin, token = app_env
    second_token = create_api_token(admin, settings)
    assert client.get("/api/ai/tree", headers=bearer(token)).status_code == 200
    assert client.get("/api/ai/tree", headers=bearer(second_token)).status_code == 200

    with Session(app.state.engine) as session:
        persisted = session.get(User, admin.id)
        persisted.is_active = False
        session.add(persisted)
        session.commit()
    assert client.get("/api/ai/tree", headers=bearer(token)).status_code == 401

    with Session(app.state.engine) as session:
        persisted = session.get(User, admin.id)
        persisted.is_active = True
        persisted.api_token_generation += 1
        session.add(persisted)
        session.commit()
    assert client.get("/api/ai/tree", headers=bearer(token)).status_code == 401
    assert client.get("/api/ai/tree", headers=bearer(second_token)).status_code == 401


def test_revoke_all_endpoint_invalidates_every_token_for_caller(client, app_env):
    _app, settings, admin, token = app_env
    second_token = create_api_token(admin, settings)

    revoked = client.post("/api/auth/tokens/revoke", json={}, headers=bearer(token))
    assert revoked.status_code == 200
    assert revoked.json()["user_id"] == admin.id
    assert revoked.json()["api_token_generation"] == 1
    assert client.get("/api/ai/tree", headers=bearer(token)).status_code == 401
    assert client.get("/api/ai/tree", headers=bearer(second_token)).status_code == 401


def test_only_admin_can_revoke_another_users_tokens(client, app_env):
    app, settings, admin, admin_token = app_env
    with Session(app.state.engine) as session:
        user = User(
            username="member",
            email="member@example.com",
            password_hash=hash_password("member password is sufficiently long"),
            display_name="Member",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        member_token = create_api_token(user, settings)
        member_id = user.id

    denied = client.post(
        "/api/auth/tokens/revoke", json={"user_id": admin.id}, headers=bearer(member_token)
    )
    assert denied.status_code == 403

    revoked = client.post(
        "/api/auth/tokens/revoke", json={"user_id": member_id}, headers=bearer(admin_token)
    )
    assert revoked.status_code == 200
    assert revoked.json()["user_id"] == member_id
    assert client.get("/api/ai/tree", headers=bearer(member_token)).status_code == 401
