from io import BytesIO
from zipfile import ZipFile

from git import Repo
from sqlmodel import Session

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
        json={"email": "admin@example.com", "password": "correct horse battery staple"},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    assert client.get("/api/ai/tree", headers=bearer(token)).status_code == 200


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
            json={"email": "nobody@example.com", "password": "incorrect-password"},
        )
        assert response.status_code == 401
    response = client.post(
        "/api/auth/token",
        json={"email": "nobody@example.com", "password": "incorrect-password"},
    )
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"


def test_incrementing_token_generation_revokes_existing_token(client, app_env):
    app, _settings, admin, token = app_env
    assert client.get("/api/ai/tree", headers=bearer(token)).status_code == 200
    with Session(app.state.engine) as session:
        persisted = session.get(User, admin.id)
        persisted.api_token_generation += 1
        session.add(persisted)
        session.commit()
    assert client.get("/api/ai/tree", headers=bearer(token)).status_code == 401
