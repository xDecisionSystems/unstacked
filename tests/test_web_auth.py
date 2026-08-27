"""Browser sessions must survive nothing that should invalidate them.

A cookie is a bearer credential the browser attaches on its own, so every
case here is one of the ways it can outlive the authority it was issued
under: tampering, revocation, deactivation, fixation, and cross-site use.
"""

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models import User
from app.web_auth import CSRF_HEADER_NAME, SESSION_COOKIE_NAME

PASSWORD = "correct horse battery staple"
EMAIL = "admin@example.com"


def _login(client: TestClient, email: str = EMAIL, password: str = PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def _mutate_user(app, user_id: int, **changes) -> None:
    with Session(app.state.engine) as session:
        user = session.get(User, user_id)
        for field, value in changes.items():
            setattr(user, field, value)
        session.add(user)
        session.commit()


def test_login_issues_a_usable_session_cookie(client):
    response = _login(client)
    assert response.status_code == 200
    assert response.cookies.get(SESSION_COOKIE_NAME)
    assert response.json()["csrf_token"]
    assert client.get("/auth/session").json()["email"] == EMAIL


def test_session_cookie_is_httponly_and_not_secure_outside_production(client):
    """Script access is the main theft vector; Secure is environment-gated."""

    header = _login(client).headers["set-cookie"]
    assert "HttpOnly" in header
    assert "SameSite=lax" in header
    assert "Secure" not in header


def test_wrong_password_is_rejected_without_naming_the_reason(client):
    """A distinguishable message would turn login into an account oracle."""

    response = _login(client, password="not the right password at all")
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"
    assert SESSION_COOKIE_NAME not in response.cookies


def test_unknown_email_fails_exactly_like_a_wrong_password(client):
    response = _login(client, email="nobody@example.com")
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


def test_protected_route_rejects_a_request_with_no_cookie(client):
    assert client.get("/auth/session").status_code == 401


def test_logout_clears_the_cookie_and_retires_the_one_already_handed_out(client):
    """The user's copy must die too — clearing the jar only helps the browser."""

    csrf_token = _login(client).json()["csrf_token"]
    stale_cookie = client.cookies[SESSION_COOKIE_NAME]

    logout = client.post("/auth/logout", headers={CSRF_HEADER_NAME: csrf_token})
    assert logout.status_code == 200
    assert not client.cookies.get(SESSION_COOKIE_NAME)
    assert client.get("/auth/session").status_code == 401

    client.cookies.set(SESSION_COOKIE_NAME, stale_cookie)
    assert client.get("/auth/session").status_code == 401


def test_tampered_cookie_is_rejected(client):
    """Without signature verification the payload is attacker-chosen."""

    _login(client)
    cookie = client.cookies[SESSION_COOKIE_NAME]
    flipped = ("b" if cookie[0] != "b" else "c") + cookie[1:]
    client.cookies.set(SESSION_COOKIE_NAME, flipped)
    assert client.get("/auth/session").status_code == 401


def test_generation_bump_invalidates_an_otherwise_valid_cookie(app_env, client):
    """A password or admin security reset must not leave old sessions alive."""

    _, _settings, admin, _token = app_env
    _login(client)
    assert client.get("/auth/session").status_code == 200

    app = app_env[0]
    _mutate_user(app, admin.id, session_generation=admin.session_generation + 1)
    assert client.get("/auth/session").status_code == 401


def test_deactivated_user_loses_access_with_an_untouched_cookie(app_env, client):
    """Deactivation has to take effect now, not at cookie expiry."""

    app, _settings, admin, _token = app_env
    _login(client)
    _mutate_user(app, admin.id, is_active=False)
    assert client.get("/auth/session").status_code == 401


def test_login_rotates_the_session_identifier(client):
    """Fixation defence: a pre-planted cookie value never becomes authenticated."""

    first = _login(client)
    first_cookie = first.cookies[SESSION_COOKIE_NAME]
    first_csrf = first.json()["csrf_token"]

    second = _login(client)
    assert second.cookies[SESSION_COOKIE_NAME] != first_cookie
    # The CSRF token is the session id signed, so a changed token means a
    # genuinely new identifier rather than a re-serialized old one.
    assert second.json()["csrf_token"] != first_csrf


def test_state_change_without_a_csrf_token_is_rejected(client):
    """The cookie alone is exactly what a cross-site form can already send."""

    _login(client)
    assert client.post("/auth/logout").status_code == 403
    assert client.get("/auth/session").status_code == 200


def test_state_change_with_a_forged_csrf_token_is_rejected(client):
    _login(client)
    response = client.post("/auth/logout", headers={CSRF_HEADER_NAME: "not-a-signed-token"})
    assert response.status_code == 403


def test_csrf_token_from_another_session_is_rejected(client):
    """Binding to the session is what stops a token being reused as a bearer."""

    stolen_csrf = _login(client).json()["csrf_token"]
    _login(client)  # rotates the identifier the stolen token was bound to
    response = client.post("/auth/logout", headers={CSRF_HEADER_NAME: stolen_csrf})
    assert response.status_code == 403


def test_csrf_token_may_arrive_as_a_form_field(client):
    """Phase 5 posts HTML forms, which cannot set request headers."""

    csrf_token = _login(client).json()["csrf_token"]
    response = client.post("/auth/logout", data={"csrf_token": csrf_token})
    assert response.status_code == 200


def test_session_cookie_does_not_authenticate_the_bearer_api(client):
    """The two mechanisms stay separate; cookies must not reach /api routes."""

    _login(client)
    assert client.get("/api/ai/tree").status_code == 401


def test_login_is_rate_limited(client):
    """Bounded attempts, shared with the bearer login so budgets do not double."""

    for _ in range(5):
        _login(client, password="wrong password guess here")
    assert _login(client).status_code == 429
