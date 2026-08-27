"""Truth table for permission resolution.

Every other module trusts this answer, so the cases are enumerated
explicitly rather than exercised only through the API.
"""

import pytest
from sqlmodel import Session, select

from app.acl import load_policy, resolve_access
from app.auth import hash_password
from app.models import Group, Permission, User, UserGroup, normalize_path_prefix


def _make_user(session: Session, email: str, *, is_admin=False, is_active=True) -> User:
    user = User(
        email=email,
        password_hash=hash_password("acl password is sufficiently long"),
        display_name="ACL Agent",
        is_admin=is_admin,
        is_active=is_active,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _grant(session: Session, user: User, prefix: str, read: bool, write: bool, group: str) -> None:
    existing = session.exec(select(Group).where(Group.name == group)).first()
    if existing is None:
        existing = Group(name=group)
        session.add(existing)
        session.commit()
        session.refresh(existing)
        session.add(UserGroup(user_id=user.id, group_id=existing.id))
    session.add(
        Permission(group_id=existing.id, path_prefix=prefix, can_read=read, can_write=write)
    )
    session.commit()


def test_default_deny_without_any_rule(app_env):
    app, *_ = app_env
    with Session(app.state.engine) as session:
        user = _make_user(session, "norules@example.com")
        decision = resolve_access(session, user, "book/page.md")
    assert not decision.can_read
    assert not decision.can_write


def test_admin_bypasses_all_rules(app_env):
    app, _settings, admin, _token = app_env
    with Session(app.state.engine) as session:
        decision = resolve_access(session, admin, "any/unknown/page.md")
    assert decision.can_read
    assert decision.can_write


def test_inactive_user_is_denied_despite_grants(app_env):
    app, *_ = app_env
    with Session(app.state.engine) as session:
        user = _make_user(session, "inactive@example.com", is_active=False)
        _grant(session, user, "book", read=True, write=True, group="inactive-group")
        decision = resolve_access(session, user, "book/page.md")
    assert not decision.can_read
    assert not decision.can_write


def test_inherited_allow_from_ancestor_prefix(app_env):
    app, *_ = app_env
    with Session(app.state.engine) as session:
        user = _make_user(session, "inherit@example.com")
        _grant(session, user, "book", read=True, write=True, group="inherit")
        decision = resolve_access(session, user, "book/chapter/page.md")
    assert decision.can_read
    assert decision.can_write


def test_more_specific_deny_overrides_inherited_allow(app_env):
    app, *_ = app_env
    with Session(app.state.engine) as session:
        user = _make_user(session, "override@example.com")
        _grant(session, user, "book", read=True, write=True, group="override")
        _grant(session, user, "book/secret", read=False, write=False, group="override")
        allowed = resolve_access(session, user, "book/public/page.md")
        denied = resolve_access(session, user, "book/secret/page.md")
    assert allowed.can_read
    assert not denied.can_read


def test_equal_specificity_deny_wins_across_groups(app_env):
    app, *_ = app_env
    with Session(app.state.engine) as session:
        user = _make_user(session, "conflict@example.com")
        _grant(session, user, "book/chapter", read=True, write=True, group="allow-group")
        _grant(session, user, "book/chapter", read=False, write=False, group="deny-group")
        _grant(session, user, "book/chapter/ok.md", read=True, write=True, group="allow-group")
        denied = resolve_access(session, user, "book/chapter/other.md")
        allowed = resolve_access(session, user, "book/chapter/ok.md")
    assert not denied.can_read
    assert allowed.can_read
    assert allowed.can_write


def test_sibling_prefix_is_not_confused_with_a_longer_name(app_env):
    """`chapter` must not grant access to `chapter-old`."""

    app, *_ = app_env
    with Session(app.state.engine) as session:
        user = _make_user(session, "sibling@example.com")
        _grant(session, user, "book/chapter", read=True, write=True, group="sibling")
        inside = resolve_access(session, user, "book/chapter/page.md")
        outside = resolve_access(session, user, "book/chapter-old/page.md")
    assert inside.can_read
    assert not outside.can_read


def test_write_never_outlives_read(app_env):
    app, *_ = app_env
    with Session(app.state.engine) as session:
        user = _make_user(session, "writeonly@example.com")
        _grant(session, user, "book", read=False, write=True, group="writeonly")
        decision = resolve_access(session, user, "book/page.md")
    assert not decision.can_read
    assert not decision.can_write


def test_ancestor_grant_does_not_leak_to_a_sibling_book(app_env):
    app, *_ = app_env
    with Session(app.state.engine) as session:
        user = _make_user(session, "ancestor@example.com")
        _grant(session, user, "book-a", read=True, write=True, group="ancestor")
        assert resolve_access(session, user, "book-a/page.md").can_read
        assert not resolve_access(session, user, "book-b/page.md").can_read


def test_unsafe_paths_are_denied_rather_than_raising(app_env):
    app, *_ = app_env
    with Session(app.state.engine) as session:
        user = _make_user(session, "unsafe@example.com")
        _grant(session, user, "book", read=True, write=True, group="unsafe")
        policy = load_policy(session, user)
    assert not policy.decide("../escape.md").can_read
    assert not policy.decide("/absolute.md").can_read


def test_policy_is_loaded_once_and_reused(app_env):
    """Tree listings evaluate every page, so rules must not be re-queried."""

    app, *_ = app_env
    with Session(app.state.engine) as session:
        user = _make_user(session, "policy@example.com")
        _grant(session, user, "book", read=True, write=False, group="policy")
        policy = load_policy(session, user)
    # Usable with the session closed: proves no lazy per-path query remains.
    assert policy.decide("book/page.md").can_read
    assert not policy.decide("book/page.md").can_write


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("book/chapter/", "book/chapter"),
        ("/book/chapter", "book/chapter"),
        ("  book/chapter  ", "book/chapter"),
    ],
)
def test_permission_prefixes_are_normalized_on_save(stored: str, expected: str):
    assert normalize_path_prefix(stored) == expected


@pytest.mark.parametrize("stored", ["", "   ", "/", "book//chapter", "../book", ".hidden"])
def test_unusable_permission_prefixes_are_rejected(stored: str):
    with pytest.raises(ValueError):
        normalize_path_prefix(stored)


def test_stored_prefix_with_trailing_slash_still_grants_access(app_env):
    """A grant saved with sloppy formatting must not silently do nothing."""

    app, *_ = app_env
    with Session(app.state.engine) as session:
        user = _make_user(session, "sloppy@example.com")
        _grant(session, user, "book/chapter/", read=True, write=True, group="sloppy")
        decision = resolve_access(session, user, "book/chapter/page.md")
    assert decision.can_read
