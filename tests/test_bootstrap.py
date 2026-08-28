from sqlmodel import Session, select

from app import bootstrap
from app.auth import authenticate
from app.models import User, create_db_engine


def test_bootstrap_creates_restricted_fixed_admin_and_is_idempotent(app_env, monkeypatch, capsys):
    _app, settings, _admin, _token = app_env
    settings.db_path.unlink()
    monkeypatch.setattr(bootstrap, "Settings", lambda: settings)
    bootstrap.main()

    with Session(create_db_engine(settings.db_path)) as session:
        users = session.exec(select(User)).all()
        assert [(user.username, user.is_admin, user.must_change_password) for user in users] == [
            ("admin", True, True)
        ]
        assert authenticate(session, "admin", "admin") is not None

    bootstrap.main()
    assert "already complete" in capsys.readouterr().out
    with Session(create_db_engine(settings.db_path)) as session:
        assert len(session.exec(select(User)).all()) == 1
