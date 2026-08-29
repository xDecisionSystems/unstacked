"""Admin API for the web UI color palette (GET/PUT /api/admin/theme).

Cosmetic, but the route-level contracts are the same shape as every other
admin endpoint: admin-only, CSRF-guarded for the cookie transport, and a
malformed body is refused with a 422 that never persists anything.
"""

import pytest

from app import theme, theme_config
from app.auth import create_api_token, hash_password
from app.models import User
from app.web_auth import CSRF_HEADER_NAME
from tests.conftest import bearer

PASSWORD = "correct horse battery staple"
SAMPLE_PALETTE = {
    "accent": "#123456",
    "accent_secondary": "#654321",
    "warm": "#abcdef",
    "muted": "#999999",
    "text": "#000000",
}


def _make_reader(app) -> User:
    from sqlmodel import Session

    with Session(app.state.engine) as session:
        user = User(
            username="reader",
            email="reader@example.com",
            password_hash=hash_password(PASSWORD),
            display_name="Reader",
            is_admin=False,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        session.expunge(user)
        return user


def test_default_theme_is_the_future_green_preset(app_env, client):
    _app, _settings, _admin, token = app_env
    response = client.get("/api/admin/theme", headers=bearer(token))
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "preset"
    assert body["preset"] == theme.DEFAULT_PRESET
    assert len(body["presets"]) == 4
    assert {p["key"] for p in body["presets"]} == set(theme.PRESETS)


def test_theme_routes_reject_an_unauthenticated_caller(client):
    assert client.get("/api/admin/theme").status_code == 401


def test_theme_routes_reject_an_authenticated_non_admin(app_env, client):
    app, settings, _admin, _token = app_env
    reader = _make_reader(app)
    token = create_api_token(reader, settings)
    body = {"mode": "preset", "preset": "ocean-blue"}
    assert client.get("/api/admin/theme", headers=bearer(token)).status_code == 403
    assert client.put("/api/admin/theme", json=body, headers=bearer(token)).status_code == 403


def test_selecting_a_preset_updates_the_effective_palette(app_env, client):
    _app, settings, _admin, token = app_env
    response = client.put(
        "/api/admin/theme", json={"mode": "preset", "preset": "ocean-blue"}, headers=bearer(token)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "preset"
    assert body["preset"] == "ocean-blue"
    assert body["palette"]["accent"] == theme.PRESETS["ocean-blue"].accent

    again = client.get("/api/admin/theme", headers=bearer(token))
    assert again.json()["preset"] == "ocean-blue"

    state = theme_config.load(settings.theme_config_path)
    assert state.mode == "preset"
    assert state.preset == "ocean-blue"


def test_selecting_an_unknown_preset_is_rejected(app_env, client):
    _app, settings, _admin, token = app_env
    body = {"mode": "preset", "preset": "no-such-preset"}
    response = client.put("/api/admin/theme", json=body, headers=bearer(token))
    assert response.status_code == 422
    assert theme_config.load(settings.theme_config_path) == theme_config.DEFAULT_STATE


def test_a_custom_palette_is_saved_and_takes_effect(app_env, client):
    _app, settings, _admin, token = app_env
    body = {"mode": "custom", "palette": SAMPLE_PALETTE}
    response = client.put("/api/admin/theme", json=body, headers=bearer(token))
    assert response.status_code == 200
    result = response.json()
    assert result["mode"] == "custom"
    assert result["preset"] is None
    assert result["palette"] == SAMPLE_PALETTE

    state = theme_config.load(settings.theme_config_path)
    assert state.mode == "custom"
    assert state.palette.accent == "#123456"


def test_a_custom_palette_with_a_malformed_color_is_rejected(app_env, client):
    _app, settings, _admin, token = app_env
    palette = {**SAMPLE_PALETTE, "accent": "not-a-color"}
    body = {"mode": "custom", "palette": palette}
    response = client.put("/api/admin/theme", json=body, headers=bearer(token))
    assert response.status_code == 422
    assert theme_config.load(settings.theme_config_path) == theme_config.DEFAULT_STATE


@pytest.mark.parametrize(
    "body",
    [
        {"mode": "preset", "preset": "ocean-blue", "palette": SAMPLE_PALETTE},
        {"mode": "custom", "preset": "ocean-blue", "palette": SAMPLE_PALETTE},
    ],
)
def test_supplying_both_a_preset_and_a_custom_palette_is_rejected(app_env, client, body):
    _app, settings, _admin, token = app_env
    response = client.put("/api/admin/theme", json=body, headers=bearer(token))
    assert response.status_code == 422
    assert theme_config.load(settings.theme_config_path) == theme_config.DEFAULT_STATE


def test_custom_mode_without_a_palette_is_rejected(app_env, client):
    _app, _settings, _admin, token = app_env
    response = client.put("/api/admin/theme", json={"mode": "custom"}, headers=bearer(token))
    assert response.status_code == 422


def test_cookie_authenticated_admin_needs_a_csrf_token(client):
    csrf = client.post("/auth/login", json={"username": "admin", "password": PASSWORD}).json()[
        "csrf_token"
    ]
    payload = {"mode": "preset", "preset": "ocean-blue"}

    assert client.put("/api/admin/theme", json=payload).status_code == 403
    ok = client.put("/api/admin/theme", json=payload, headers={CSRF_HEADER_NAME: csrf})
    assert ok.status_code == 200


def test_the_selected_palette_appears_on_a_rendered_page(app_env, client):
    """The Jinja global, not just the API, has to reflect a saved change."""

    _app, _settings, _admin, token = app_env
    body = {"mode": "preset", "preset": "ocean-blue"}
    client.put("/api/admin/theme", json=body, headers=bearer(token))

    csrf = client.post("/auth/login", json={"username": "admin", "password": PASSWORD}).json()[
        "csrf_token"
    ]
    assert csrf
    page = client.get("/tree")
    assert page.status_code == 200
    assert f"--accent:{theme.PRESETS['ocean-blue'].accent}" in page.text


def test_the_default_palette_appears_on_the_login_page(client):
    """Login never calls `_base_context`, so this exercises the standalone template."""

    page = client.get("/login")
    assert page.status_code == 200
    assert f"--accent:{theme.PRESETS[theme.DEFAULT_PRESET].accent}" in page.text
