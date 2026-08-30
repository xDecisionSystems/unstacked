"""The two built-in groups and their durable, filesystem-derived grants.

The groups themselves and all grants remain ordinary rows in the four-table
authorization database.  Content stays entirely in ``content/docs``; this
module only mirrors each chapter path into the Admin group's ACL rows.
"""

from pathlib import Path

from sqlmodel import Session, select

from app.models import Group, Permission, User, UserGroup
from app.paths import path_depth

PUBLIC_GROUP_NAME = "Public"
ADMIN_GROUP_NAME = "Admin"


def _chapter_paths(docs: Path) -> list[str]:
    """Return real chapter directories, never books, pages, or asset folders."""

    if not docs.is_dir():
        return []
    return [
        f"{book.name}/{chapter.name}"
        for book in sorted(docs.iterdir())
        if book.is_dir() and book.name != "assets" and not book.name.startswith(".")
        for chapter in sorted(book.iterdir())
        if chapter.is_dir() and not chapter.name.startswith(".")
    ]


def _group(session: Session, name: str, description: str) -> Group:
    group = session.exec(select(Group).where(Group.name == name)).one_or_none()
    if group is None:
        group = Group(name=name, description=description)
        session.add(group)
        session.flush()
    return group


def sync_admin_membership(session: Session, user: User) -> None:
    """Keep administrative accounts in the built-in Admin group.

    The ``is_admin`` flag remains the authorization bypass; this membership
    makes the Admin group useful and accurately represented in Settings.
    """

    group = session.exec(select(Group).where(Group.name == ADMIN_GROUP_NAME)).one_or_none()
    if group is None or user.id is None or group.id is None:
        return
    membership = session.get(UserGroup, (user.id, group.id))
    if user.is_admin and membership is None:
        session.add(UserGroup(user_id=user.id, group_id=group.id))
    elif not user.is_admin and membership is not None:
        session.delete(membership)


def ensure_default_groups(engine, docs: Path) -> None:
    """Create default groups and make the Admin group writable on all chapters."""

    with Session(engine) as session:
        public = _group(
            session,
            PUBLIC_GROUP_NAME,
            "No chapter access unless an administrator grants it.",
        )
        admin = _group(
            session,
            ADMIN_GROUP_NAME,
            "Read and write access to every chapter.",
        )
        # Public intentionally receives no rows: the ACL is default-deny until
        # a specific chapter grant is created in Settings.
        assert public.id is not None and admin.id is not None
        for user in session.exec(select(User)).all():
            sync_admin_membership(session, user)
        existing_paths = set(
            session.exec(
                select(Permission.path_prefix).where(Permission.group_id == admin.id)
            ).all()
        )
        for path in _chapter_paths(docs):
            if path not in existing_paths:
                session.add(
                    Permission(
                        group_id=admin.id,
                        path_prefix=path,
                        can_read=True,
                        can_write=True,
                    )
                )
        session.commit()


def copy_public_chapter_defaults(session: Session, group: Group) -> None:
    """Copy the Public template's chapter grants to a newly created group."""

    if group.id is None or group.name in {PUBLIC_GROUP_NAME, ADMIN_GROUP_NAME}:
        return
    public = session.exec(
        select(Group).where(Group.name == PUBLIC_GROUP_NAME)
    ).one_or_none()
    if public is None or public.id is None:
        return
    defaults = session.exec(
        select(Permission).where(Permission.group_id == public.id)
    ).all()
    for default in defaults:
        if path_depth(default.path_prefix) != 2:
            continue
        session.add(
            Permission(
                group_id=group.id,
                path_prefix=default.path_prefix,
                can_read=default.can_read,
                can_write=default.can_write,
            )
        )


def grant_admin_group_write(engine, chapter_path: str) -> None:
    """Grant the built-in Admin group read/write access to a new chapter."""

    with Session(engine) as session:
        admin = session.exec(
            select(Group).where(Group.name == ADMIN_GROUP_NAME)
        ).one_or_none()
        if admin is None or admin.id is None:
            return
        existing = session.exec(
            select(Permission).where(Permission.group_id == admin.id).where(
                Permission.path_prefix == chapter_path
            )
        ).one_or_none()
        if existing is None:
            session.add(
                Permission(
                    group_id=admin.id,
                    path_prefix=chapter_path,
                    can_read=True,
                    can_write=True,
                )
            )
            session.commit()
