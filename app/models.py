from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Column, String, event
from sqlmodel import Field, Session, SQLModel, create_engine


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(sa_column=Column(String, unique=True, index=True, nullable=False))
    password_hash: str
    display_name: str
    is_admin: bool = False
    is_active: bool = True
    session_generation: int = 0
    api_token_generation: int = 0


class Group(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(sa_column=Column(String, unique=True, index=True, nullable=False))
    description: str = ""


class UserGroup(SQLModel, table=True):
    user_id: int = Field(foreign_key="user.id", primary_key=True, ondelete="CASCADE")
    group_id: int = Field(foreign_key="group.id", primary_key=True, ondelete="CASCADE")


class Permission(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="group.id", index=True, ondelete="CASCADE")
    path_prefix: str = Field(index=True)
    can_read: bool = True
    can_write: bool = False


def create_db_engine(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def migrate_schema(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(config, "head")


def session_for(engine) -> Session:
    return Session(engine)
