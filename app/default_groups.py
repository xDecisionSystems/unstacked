"""The two built-in groups and their durable, filesystem-derived grants.

The groups themselves and all grants remain ordinary rows in the four-table
authorization database.  Content stays entirely in ``content/docs``; this
module only mirrors each book path into the Admin group's ACL rows.
"""

from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models import Group, Permission, User, UserGroup

PUBLIC_GROUP_NAME = "Public"
ADMIN_GROUP_NAME = "Admin"
MAIN_BOOK_ACCESS = {
    "main-hidden": (False, False),
    "main-read": (True, False),
    "main-write": (True, True),
}


def _book_paths(docs: Path) -> list[str]:
    """Return real book directories, never the asset folder or dot directories."""

    if not docs.is_dir():
        return []
    return [
        book.name
        for book in sorted(docs.iterdir())
        if book.is_dir() and book.name != "assets" and not book.name.startswith(".")
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
    """Create default groups and make the Admin group writable on all books."""

    with Session(engine) as session:
        public = _group(
            session,
            PUBLIC_GROUP_NAME,
            "No book access unless an administrator grants it.",
        )
        admin = _group(
            session,
            ADMIN_GROUP_NAME,
            "Read and write access to every book.",
        )
        assert public.id is not None and admin.id is not None
        for user in session.exec(select(User)).all():
            sync_admin_membership(session, user)
        book_paths = set(_book_paths(docs))
        existing = session.exec(
            select(Permission).where(Permission.group_id == admin.id)
        ).all()
        existing_paths = {permission.path_prefix for permission in existing}
        # Admin is a filesystem-derived default rather than an administrator's
        # hand-authored grant. Drop a stale default when its book disappears;
        # it otherwise shows up as a misleading orphan despite Admin already
        # having the separate is_admin bypass.
        for permission in existing:
            if permission.path_prefix not in book_paths:
                session.delete(permission)
        for path in book_paths:
            if path not in existing_paths:
                session.add(
                    Permission(
                        group_id=admin.id,
                        path_prefix=path,
                        can_read=True,
                        can_write=True,
                    )
                )
        # The reserved front-page books define the starting template that a
        # newly created group inherits.  They remain ordinary editable grants
        # in Settings; startup only creates a missing baseline.
        public_grants = {
            permission.path_prefix: permission
            for permission in session.exec(
                select(Permission).where(Permission.group_id == public.id)
            ).all()
        }
        for path, access in MAIN_BOOK_ACCESS.items():
            if path not in book_paths:
                continue
            if path in public_grants:
                continue
            session.add(
                Permission(
                    group_id=public.id,
                    path_prefix=path,
                    can_read=access[0],
                    can_write=access[1],
                )
            )
        session.commit()


def copy_public_book_defaults(session: Session, group: Group) -> None:
    """Copy the Public template's book grants to a newly created group."""

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
        if default.path_prefix.count("/") != 0:
            continue
        session.add(
            Permission(
                group_id=group.id,
                path_prefix=default.path_prefix,
                can_read=default.can_read,
                can_write=default.can_write,
            )
        )


def grant_admin_group_write(engine, book_path: str) -> None:
    """Grant the built-in Admin group read/write access to a new book."""

    with Session(engine) as session:
        admin = session.exec(
            select(Group).where(Group.name == ADMIN_GROUP_NAME)
        ).one_or_none()
        if admin is None or admin.id is None:
            return
        existing = session.exec(
            select(Permission).where(Permission.group_id == admin.id).where(
                Permission.path_prefix == book_path
            )
        ).one_or_none()
        if existing is None:
            session.add(
                Permission(
                    group_id=admin.id,
                    path_prefix=book_path,
                    can_read=True,
                    can_write=True,
                )
            )
            session.commit()


def migrate_chapter_permission_paths(engine, old_to_new: dict[str, str]) -> None:
    """Move legacy chapter grants onto the books created from them.

    ``old_to_new`` is deliberately supplied by the filesystem migration: this
    module owns authorization rows, but must never infer a content rename from
    the database.  A destination grant already present for the same group is
    left intact; in that unusual case the legacy row is retained for an
    administrator to inspect instead of silently choosing between two access
    policies.
    """

    if not old_to_new:
        return
    with Session(engine) as session:
        rows = session.exec(select(Permission)).all()
        original_exact = {(row.group_id, row.path_prefix) for row in rows}
        destinations = {
            (row.group_id, row.path_prefix): row for row in rows
        }
        for row in rows:
            destination = old_to_new.get(row.path_prefix)
            if destination is None:
                continue
            if (row.group_id, destination) in destinations and (
                destinations[(row.group_id, destination)] is not row
            ):
                continue
            destinations.pop((row.group_id, row.path_prefix), None)
            row.path_prefix = destination
            destinations[(row.group_id, destination)] = row
            session.add(row)

        # A grant on the old book was inherited by each of its chapters.
        # Carry it to every promoted book unless the chapter had an exact rule,
        # which remains the more-specific intent.  This preserves effective
        # access while making the new book the only permission boundary.
        for old, destination in old_to_new.items():
            parent = old.split("/", 1)[0]
            for row in rows:
                if row.path_prefix != parent or (row.group_id, old) in original_exact:
                    continue
                key = (row.group_id, destination)
                if key in destinations:
                    continue
                copied = Permission(
                    group_id=row.group_id,
                    path_prefix=destination,
                    can_read=row.can_read,
                    can_write=row.can_write,
                )
                session.add(copied)
                destinations[key] = copied
        try:
            session.commit()
        except IntegrityError:
            # A concurrently-created grant can only make a legacy mapping
            # ambiguous.  Preserve the old rows rather than discarding access
            # information, then let the caller retry once the admin action is
            # complete.
            session.rollback()
            raise
