from sqlmodel import Session, select

from app.default_groups import (
    ADMIN_GROUP_NAME,
    PUBLIC_GROUP_NAME,
    migrate_chapter_permission_paths,
)
from app.models import Group, Permission
from tests.conftest import bearer


def test_default_groups_keep_public_denied_and_admin_writable_for_new_books(app_env):
    app, _settings, admin, _token = app_env
    with Session(app.state.engine) as session:
        groups = {group.name: group for group in session.exec(select(Group)).all()}
        assert set(groups) == {PUBLIC_GROUP_NAME, ADMIN_GROUP_NAME}
        public = groups[PUBLIC_GROUP_NAME]
        assert session.exec(select(Permission).where(Permission.group_id == public.id)).all() == []

    app.state.content.create_book("Handbook", "handbook", admin)

    with Session(app.state.engine) as session:
        admin_group = session.exec(
            select(Group).where(Group.name == ADMIN_GROUP_NAME)
        ).one()
        grant = session.exec(
            select(Permission)
            .where(Permission.group_id == admin_group.id)
            .where(Permission.path_prefix == "handbook")
        ).one()
        assert grant.can_read and grant.can_write


def test_new_group_inherits_public_book_defaults(app_env, client):
    app, _settings, admin, token = app_env
    app.state.content.create_book("Handbook", "handbook", admin)
    with Session(app.state.engine) as session:
        public = session.exec(select(Group).where(Group.name == PUBLIC_GROUP_NAME)).one()
        session.add(
            Permission(
                group_id=public.id,
                path_prefix="handbook",
                can_read=True,
                can_write=True,
            )
        )
        session.commit()

    response = client.post("/api/admin/groups", json={"name": "Editors"}, headers=bearer(token))
    assert response.status_code == 201
    with Session(app.state.engine) as session:
        grant = session.exec(
            select(Permission)
            .where(Permission.group_id == response.json()["id"])
            .where(Permission.path_prefix == "handbook")
        ).one()
        assert grant.can_read and grant.can_write


def test_chapter_migration_preserves_an_inherited_book_grant(app_env):
    app, _settings, _admin, _token = app_env
    with Session(app.state.engine) as session:
        group = Group(name="Readers")
        session.add(group)
        session.flush()
        session.add(
            Permission(
                group_id=group.id,
                path_prefix="operations",
                can_read=True,
                can_write=False,
            )
        )
        session.commit()

    migrate_chapter_permission_paths(app.state.engine, {"operations/runbooks": "runbooks"})

    with Session(app.state.engine) as session:
        grant = session.exec(
            select(Permission)
            .where(Permission.path_prefix == "runbooks")
            .where(Permission.can_write.is_(False))
        ).one()
        assert grant.can_read
