from sqlmodel import Session, select

from app.default_groups import ADMIN_GROUP_NAME, PUBLIC_GROUP_NAME
from app.models import Group, Permission


def test_default_groups_keep_public_denied_and_admin_writable_for_new_chapters(app_env):
    app, _settings, admin, _token = app_env
    with Session(app.state.engine) as session:
        groups = {group.name: group for group in session.exec(select(Group)).all()}
        assert set(groups) == {PUBLIC_GROUP_NAME, ADMIN_GROUP_NAME}
        public = groups[PUBLIC_GROUP_NAME]
        assert session.exec(select(Permission).where(Permission.group_id == public.id)).all() == []

    app.state.content.create_book("Handbook", "handbook", admin)
    app.state.content.create_chapter("handbook", "Policies", "policies", admin)

    with Session(app.state.engine) as session:
        admin_group = session.exec(
            select(Group).where(Group.name == ADMIN_GROUP_NAME)
        ).one()
        grant = session.exec(
            select(Permission)
            .where(Permission.group_id == admin_group.id)
            .where(Permission.path_prefix == "handbook/policies")
        ).one()
        assert grant.can_read and grant.can_write
