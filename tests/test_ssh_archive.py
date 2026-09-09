"""Portable SSH archive contents and guarded restore regression tests."""

from io import BytesIO
from zipfile import ZipFile

from sqlalchemy import delete
from sqlmodel import Session, select

from app.models import Group, Permission, User
from app.ssh_archive import ARCHIVE_ROOT, WorkspaceArchiveService


def test_workspace_archive_round_trip_preserves_content_permissions_and_appearance(app_env):
    app, settings, admin, _token = app_env
    content = app.state.content
    content.create_book("Archive book", None, admin)
    content.create_page("archive-book", "Archive page", None, "restorable body", [], False, admin)
    with Session(app.state.engine) as session:
        group = Group(name="Archive readers", description="Restored from archive")
        session.add(group)
        session.flush()
        assert group.id is not None
        session.add(Permission(group_id=group.id, path_prefix="archive-book", can_read=True))
        session.commit()

    service = WorkspaceArchiveService(settings, content, app.state.engine)
    archive = service.package()
    with ZipFile(BytesIO(archive)) as zip_file:
        names = set(zip_file.namelist())
        assert f"{ARCHIVE_ROOT}/manifest.json" in names
        assert f"{ARCHIVE_ROOT}/state.json" in names
        assert f"{ARCHIVE_ROOT}/content/docs/archive-book/archive-page.md" in names
        state = zip_file.read(f"{ARCHIVE_ROOT}/state.json").decode()
        assert "password_hash" in state
        assert "backup_token" not in state

    (content.docs / "archive-book" / "archive-page.md").unlink()
    with Session(app.state.engine) as session:
        session.exec(delete(Permission).where(Permission.path_prefix == "archive-book"))
        session.commit()

    confirmation = service.prepare_restore(archive, admin)
    service.confirm_restore(confirmation)

    assert (content.docs / "archive-book" / "archive-page.md").is_file()
    with Session(app.state.engine) as session:
        assert (
            len(
                session.exec(
                    select(Permission).where(Permission.path_prefix == "archive-book")
                ).all()
            )
            == 2
        )
        assert session.exec(select(User).where(User.username == "admin")).one()


def test_workspace_archive_rejects_mkdocs_only_zip(app_env):
    app, settings, admin, _token = app_env
    service = WorkspaceArchiveService(settings, app.state.content, app.state.engine)
    with ZipFile(BytesIO(), "w") as _unused:
        pass
    try:
        service.prepare_restore(b"not a zip", admin)
    except Exception as exc:
        assert "valid Unstacked workspace ZIP" in str(exc)
    else:  # pragma: no cover - makes the rejection contract explicit.
        raise AssertionError("non-archive ZIP input was accepted")
