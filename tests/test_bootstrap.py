import io
import sys

from sqlmodel import Session, select

from app import bootstrap
from app.models import User, create_db_engine


def test_bootstrap_reads_password_from_stdin_and_is_idempotent(
    app_env, monkeypatch, capsys
):
    _app, settings, _admin, _token = app_env
    settings.db_path.unlink()
    monkeypatch.setattr(bootstrap, "Settings", lambda: settings)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "unstacked-bootstrap",
            "--email",
            "first@example.com",
            "--display-name",
            "First Admin",
            "--password-stdin",
        ],
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO("correct horse battery staple\n"))

    bootstrap.main()

    with Session(create_db_engine(settings.db_path)) as session:
        users = session.exec(select(User)).all()
        assert [(user.email, user.is_admin) for user in users] == [("first@example.com", True)]

    monkeypatch.setattr(sys, "stdin", io.StringIO("this input must not be read\n"))
    bootstrap.main()
    assert "already complete" in capsys.readouterr().out
    with Session(create_db_engine(settings.db_path)) as session:
        assert len(session.exec(select(User)).all()) == 1
