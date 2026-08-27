"""Database invariants for the four-table authorization schema."""

from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.models import Group, Permission, User, UserGroup, create_db_engine, migrate_schema


@pytest.fixture
def database(tmp_path: Path):
    db_path = tmp_path / "data" / "app.db"
    migrate_schema(db_path)
    engine = create_db_engine(db_path)
    try:
        yield engine
    finally:
        engine.dispose()


def _user(email: str = "member@example.com") -> User:
    return User(
        email=email,
        password_hash="not-a-real-password-hash",
        display_name="Member",
    )


def test_migrations_create_only_the_authorization_tables(database):
    tables = set(inspect(database).get_table_names())
    assert tables == {"alembic_version", "user", "group", "usergroup", "permission"}

    with Session(database) as session:
        user = _user()
        group = Group(name="editors")
        session.add_all([user, group])
        session.commit()
        session.refresh(user)
        session.refresh(group)

        membership = UserGroup(user_id=user.id, group_id=group.id)
        permission = Permission(
            group_id=group.id,
            path_prefix="books/getting-started",
            can_read=True,
            can_write=True,
        )
        session.add_all([membership, permission])
        session.commit()


def test_memberships_and_permissions_cascade_with_their_parent_rows(database):
    with Session(database) as session:
        user = _user()
        group = Group(name="editors")
        session.add_all([user, group])
        session.commit()
        session.refresh(user)
        session.refresh(group)
        session.add_all(
            [
                UserGroup(user_id=user.id, group_id=group.id),
                Permission(group_id=group.id, path_prefix="books", can_read=True),
            ]
        )
        session.commit()

        session.delete(group)
        session.commit()
        assert session.get(UserGroup, (user.id, group.id)) is None
        assert session.get(Permission, 1) is None


def test_memberships_cascade_when_a_user_is_deleted(database):
    with Session(database) as session:
        user = _user()
        group = Group(name="editors")
        session.add_all([user, group])
        session.commit()
        session.refresh(user)
        session.refresh(group)
        session.add(UserGroup(user_id=user.id, group_id=group.id))
        session.commit()

        session.delete(user)
        session.commit()
        assert session.get(UserGroup, (user.id, group.id)) is None


def test_unique_foreign_key_and_check_constraints_reject_invalid_rows(database):
    with Session(database) as session:
        user = _user()
        group = Group(name="editors")
        session.add_all([user, group])
        session.commit()
        session.refresh(user)
        session.refresh(group)

        session.add(User(email=user.email, password_hash="hash", display_name="Duplicate"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(UserGroup(user_id=user.id, group_id=group.id))
        session.commit()
        session.add(UserGroup(user_id=user.id, group_id=group.id))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(
            Permission(group_id=group.id, path_prefix="books", can_read=True, can_write=True)
        )
        session.commit()
        session.add(
            Permission(group_id=group.id, path_prefix="books", can_read=True, can_write=False)
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(
            Permission(group_id=group.id, path_prefix="write-only", can_read=False, can_write=True)
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(Permission(group_id=group.id, path_prefix="", can_read=True, can_write=False))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        user.session_generation = -1
        session.add(user)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.refresh(user)
        user.api_token_generation = -1
        session.add(user)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(UserGroup(user_id=999_999, group_id=group.id))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
