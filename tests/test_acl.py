from sqlmodel import Session

from app.acl import resolve_access
from app.auth import hash_password
from app.models import Group, Permission, User, UserGroup


def test_equal_specificity_deny_wins_and_more_specific_rule_overrides(app_env):
    app, _settings, _admin, _token = app_env
    with Session(app.state.engine) as session:
        user = User(
            email="acl@example.com",
            password_hash=hash_password("acl password is sufficiently long"),
            display_name="ACL Agent",
        )
        allow_group = Group(name="allow")
        deny_group = Group(name="deny")
        session.add(user)
        session.add(allow_group)
        session.add(deny_group)
        session.commit()
        session.refresh(user)
        session.refresh(allow_group)
        session.refresh(deny_group)
        session.add(UserGroup(user_id=user.id, group_id=allow_group.id))
        session.add(UserGroup(user_id=user.id, group_id=deny_group.id))
        session.add(
            Permission(
                group_id=allow_group.id,
                path_prefix="book/chapter",
                can_read=True,
                can_write=True,
            )
        )
        session.add(
            Permission(
                group_id=deny_group.id,
                path_prefix="book/chapter",
                can_read=False,
                can_write=False,
            )
        )
        session.add(
            Permission(
                group_id=allow_group.id,
                path_prefix="book/chapter/allowed.md",
                can_read=True,
                can_write=True,
            )
        )
        session.commit()

        denied = resolve_access(session, user, "book/chapter/denied.md")
        allowed = resolve_access(session, user, "book/chapter/allowed.md")

    assert not denied.can_read
    assert not denied.can_write
    assert allowed.can_read
    assert allowed.can_write
