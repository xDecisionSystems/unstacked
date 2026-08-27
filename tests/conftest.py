from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.auth import create_api_token, hash_password
from app.config import Settings
from app.main import create_app
from app.models import User


@pytest.fixture
def app_env(tmp_path: Path):
    settings = Settings(
        environment="test",
        content_repo_path=tmp_path / "content",
        db_path=tmp_path / "data" / "app.db",
        content_lock_path=tmp_path / "data" / "content.lock",
        api_token_secret="test-secret-that-is-long-and-random-enough",
    )
    app = create_app(settings)
    with Session(app.state.engine) as session:
        admin = User(
            username="admin",
            email="admin@example.com",
            password_hash=hash_password("correct horse battery staple"),
            display_name="Admin Agent",
            is_admin=True,
        )
        session.add(admin)
        session.commit()
        session.refresh(admin)
        token = create_api_token(admin, settings)
        session.expunge(admin)
    return app, settings, admin, token


@pytest.fixture
def client(app_env):
    app, _settings, _admin, _token = app_env
    with TestClient(app) as test_client:
        yield test_client


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
