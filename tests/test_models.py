"""Database invariants for the four-table authorization schema."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models import Group, Permission, User, UserGroup, create_db_engine, migrate_schema


def _alembic_config(db_path: Path) -> Config:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "app" / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return config


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
        username=email,
        email=email,
        password_hash="not-a-real-password-hash",
        display_name="Member",
    )


def test_migrations_create_only_the_authorization_tables(database):
    tables = set(inspect(database).get_table_names())
    assert tables == {"alembic_version", "user", "group", "usergroup", "permission"}
    columns = {column["name"] for column in inspect(database).get_columns("user")}
    assert {"username", "must_change_password"} <= columns

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
            path_prefix="/books/getting-started/",
            can_read=True,
            can_write=True,
        )
        assert permission.path_prefix == "books/getting-started"
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

        session.add(
            User(
                username="another-user",
                email=user.email,
                password_hash="hash",
                display_name="Duplicate",
            )
        )
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

        with pytest.raises(IntegrityError):
            session.execute(
                text(
                    "INSERT INTO permission (group_id, path_prefix, can_read, can_write) "
                    "VALUES (:group_id, '', 1, 0)"
                ),
                {"group_id": group.id},
            )
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


def test_username_and_password_change_flag_migrate_existing_users(tmp_path: Path):
    """Legacy email logins stay usable after the non-null username upgrade."""

    db_path = tmp_path / "data" / "legacy.db"
    db_path.parent.mkdir()
    config = _alembic_config(db_path)
    command.upgrade(config, "20260827_0002")
    legacy_engine = create_db_engine(db_path)
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                'INSERT INTO "user" '
                "(email, password_hash, display_name, is_admin, is_active, "
                "session_generation, api_token_generation) "
                "VALUES ('legacy@example.com', 'hash', 'Legacy', 0, 1, 0, 0)"
            )
        )
    legacy_engine.dispose()

    command.upgrade(config, "head")
    engine = create_db_engine(db_path)
    try:
        with Session(engine) as session:
            legacy = session.exec(select(User).where(User.email == "legacy@example.com")).one()
            assert legacy.username == "legacy@example.com"
            assert legacy.must_change_password is False
            session.add(
                User(
                    username="legacy@example.com",
                    email="other@example.com",
                    password_hash="hash",
                    display_name="Duplicate username",
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
    finally:
        engine.dispose()
