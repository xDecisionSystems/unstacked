from io import BytesIO
from zipfile import ZipFile

import pytest
from git import Repo
from sqlmodel import Session

from app.acl import AuthorizationContext
from app.auth import hash_password
from app.content import ContentMissing
from app.models import Group, Permission, User, UserGroup


def _reader(session: Session, *, prefix: str) -> User:
    user = User(
        username="ai-reader",
        email="ai-reader@example.com",
        password_hash=hash_password("reader password is sufficiently long"),
        display_name="AI Reader",
    )
    group = Group(name="ai-readers")
    session.add_all([user, group])
    session.commit()
    session.refresh(user)
    session.refresh(group)
    session.add_all(
        [
            UserGroup(user_id=user.id, group_id=group.id),
            Permission(group_id=group.id, path_prefix=prefix, can_read=True, can_write=True),
        ]
    )
    session.commit()
    return user


def _create_fixture_content(app, admin: User) -> None:
    with Session(app.state.engine) as session:
        persisted_admin = session.get(User, admin.id)
        assert persisted_admin is not None
        authorization = AuthorizationContext(session, persisted_admin)
        service = app.state.ai_service
        service.create_book(authorization, title="Public", slug=None)
        service.create_page(
            authorization,
            parent="public",
            title="Visible",
            slug=None,
            markdown="needle " + "x" * 80,
            tags=["guide"],
            draft=False,
        )
        service.create_page(
            authorization,
            parent="public",
            title="Another Visible",
            slug=None,
            markdown="needle in a second permitted page",
            tags=[],
            draft=False,
        )
        service.create_book(authorization, title="Private", slug=None)
        service.create_page(
            authorization,
            parent="private",
            title="Secret",
            slug=None,
            markdown="needle must remain private",
            tags=[],
            draft=False,
        )


def test_service_read_export_and_search_share_acl_and_bounded_contract(app_env):
    app, settings, admin, _token = app_env
    settings.max_search_results = 1
    settings.max_search_snippet_chars = 20
    _create_fixture_content(app, admin)

    with Session(app.state.engine) as session:
        reader = _reader(session, prefix="public")
        authorization = AuthorizationContext(session, reader)
        service = app.state.ai_service

        metadata, markdown, _raw = service.get_page(authorization, "public/visible.md")
        assert metadata["title"] == "Visible"
        assert markdown.startswith("needle")

        # Direct consumers receive the same failure for an unreadable name as
        # an absent one, not just matching HTTP responses after serialization.
        with pytest.raises(ContentMissing, match="page not found"):
            service.get_page(authorization, "private/secret.md")
        with pytest.raises(ContentMissing, match="page not found"):
            service.get_page(authorization, "private/absent.md")

        found = service.search(authorization, "needle")
        assert found.total == 1
        assert found.truncated is True
        assert [item.path for item in found.items] == ["public/another-visible.md"]
        assert len(found.items[0].snippet) <= settings.max_search_snippet_chars
        assert "private/secret.md" not in {item.path for item in found.items}

        archive = service.export(authorization)

    with ZipFile(BytesIO(archive)) as zip_file:
        assert "docs/public/visible.md" in zip_file.namelist()
        assert "docs/private/secret.md" not in zip_file.namelist()


def test_service_creation_uses_actor_for_git_attribution_and_parent_write_acl(app_env):
    app, settings, admin, _token = app_env
    with Session(app.state.engine) as session:
        persisted_admin = session.get(User, admin.id)
        assert persisted_admin is not None
        admin_context = AuthorizationContext(session, persisted_admin)
        created_book = app.state.ai_service.create_book(
            admin_context, title="Engineering", slug=None
        )
        writer = _reader(session, prefix="engineering")
        writer_context = AuthorizationContext(session, writer)
        created_page = app.state.ai_service.create_page(
            writer_context,
            parent="engineering",
            title="Agent Notes",
            slug=None,
            markdown="authored by the agent",
            tags=[],
            draft=False,
        )

    assert created_book.path == "engineering"
    assert created_page.path == "engineering/agent-notes.md"
    commit = Repo(settings.content_repo_path).commit(created_page.commit)
    assert commit.author.name == "AI Reader"
    assert commit.author.email == "ai-reader@example.com"
