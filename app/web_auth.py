"""Cookie-backed sessions for the browser UI.

Deliberately separate from the bearer-token API auth in :mod:`app.auth`:
browsers attach cookies automatically, so anything authenticated this way is
CSRF-exposed and needs the synchronizer token below, while ``Authorization``
headers are never auto-attached and must not inherit that machinery.  The two
mechanisms share the credential check (:func:`app.auth.authenticate`) and the
login throttle, but never a dependency function.

Nothing about a session is stored server-side — the database holds only users,
groups and permissions — so the cookie carries the user id, the
``session_generation`` current at issue time, and a freshly minted random
session id.  Bumping ``session_generation`` therefore invalidates every
outstanding cookie for that user without a session table.
"""

import secrets
from typing import Annotated
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from itsdangerous import Signer as _Signer
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.auth import authenticate, client_identifier, hash_password
from app.config import Settings
from app.models import User

SESSION_COOKIE_NAME = "unstacked_session"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_FORM_FIELD = "csrf_token"
FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
# A CSRF form post is a handful of fields; anything larger is not one, and
# buffering it in a dependency would be an easy memory sink.
MAX_FORM_BYTES = 64 * 1024
MIN_PASSWORD_LENGTH = 12

# Distinct itsdangerous salts give each purpose its own derived key, so a
# session cookie can never be replayed as a CSRF token (or vice versa) even
# though both are keyed from the one configured application secret.
SESSION_SALT = "unstacked.web.session"
CSRF_SALT = "unstacked.web.csrf"

router = APIRouter(prefix="/auth", tags=["Web session"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=1024)


class LoginResponse(BaseModel):
    user_id: int
    display_name: str
    is_admin: bool
    must_change_password: bool
    csrf_token: str


class LogoutResponse(BaseModel):
    detail: str = "Signed out"


class SessionResponse(BaseModel):
    user_id: int
    username: str
    email: str
    display_name: str
    is_admin: bool
    csrf_token: str


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=1024)


class PasswordChangeResponse(LoginResponse):
    pass


def _session_serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.token_secret, salt=SESSION_SALT)


def _csrf_signer(settings: Settings) -> _Signer:
    return _Signer(settings.token_secret, salt=CSRF_SALT)


def _unauthenticated() -> HTTPException:
    """Always the same failure, so probing cannot distinguish the reason."""

    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")


def issue_session_cookie(response: Response, user: User, settings: Settings) -> str:
    """Write a freshly rotated session cookie and return its CSRF token.

    The session id is regenerated on every login and never derived from an
    inbound value, which is what stops an attacker who planted a cookie in the
    victim's browser from being upgraded to that victim's authenticated
    session.
    """

    if user.id is None:
        raise ValueError("user must be persisted before issuing a session")
    session_id = secrets.token_urlsafe(32)
    payload = {"sub": user.id, "gen": user.session_generation, "sid": session_id}
    response.set_cookie(
        SESSION_COOKIE_NAME,
        _session_serializer(settings).dumps(payload),
        max_age=settings.session_ttl_seconds,
        httponly=True,
        # Lax rather than Strict: a wiki is deep-linked into from chat and
        # mail, and Strict would render every such arrival logged out on the
        # first navigation.  CSRF is covered by the synchronizer token, which
        # does not depend on the cookie policy.
        samesite="lax",
        secure=settings.environment == "production",
        path="/",
    )
    return _csrf_signer(settings).sign(session_id).decode("utf-8")


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        httponly=True,
        samesite="lax",
        secure=settings.environment == "production",
        path="/",
    )


def _read_session_cookie(request: Request) -> dict:
    raw = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw:
        raise _unauthenticated()
    settings: Settings = request.app.state.settings
    try:
        payload = _session_serializer(settings).loads(raw, max_age=settings.session_ttl_seconds)
    except (BadSignature, SignatureExpired) as exc:
        raise _unauthenticated() from exc
    if not isinstance(payload, dict) or not {"sub", "gen", "sid"} <= payload.keys():
        raise _unauthenticated()
    return payload


def get_current_web_user(request: Request) -> User:
    """Resolve the cookie-authenticated user, re-checking the database each request.

    The cookie is only a claim: the account may have been deactivated or its
    sessions invalidated since it was issued, so both are verified against
    current state on every request rather than trusted from the signature.
    """

    payload = _read_session_cookie(request)
    with Session(request.app.state.engine) as session:
        user = session.get(User, payload["sub"])
        if user is None or not user.is_active or user.session_generation != payload["gen"]:
            raise _unauthenticated()
        session.expunge(user)
        return user


def require_normal_web_user(
    user: Annotated[User, Depends(get_current_web_user)],
) -> User:
    """Reject a forced-password-change session from ordinary web routes.

    The restricted session intentionally remains valid for only the two
    recovery actions: logout and password change.  Keeping this as a separate
    dependency makes future browser routes opt into the same server-side
    boundary instead of relying on a redirect in their templates.
    """

    if user.must_change_password:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Password change required")
    return user


async def _csrf_from_form(request: Request) -> str | None:
    """Pull the token out of a urlencoded body without Starlette's form parser.

    HTML forms cannot set headers, so the field has to be accepted, but
    ``request.form()`` insists on ``python-multipart`` even for urlencoded
    bodies.  The body is cached by Starlette, so a route can still parse it.
    """

    if not request.headers.get("content-type", "").startswith(FORM_CONTENT_TYPE):
        return None
    try:
        if int(request.headers.get("content-length", "0")) > MAX_FORM_BYTES:
            return None
    except ValueError:
        return None
    body = await request.body()
    if len(body) > MAX_FORM_BYTES:
        return None
    for field, value in parse_qsl(body.decode("utf-8", "replace"), keep_blank_values=True):
        if field == CSRF_FORM_FIELD:
            return value
    return None


async def require_csrf(request: Request) -> None:
    """Reject cookie-authenticated state changes without a matching CSRF token.

    Synchronizer pattern: the token is the session id signed under its own
    key, so it is bound to exactly one session and a cross-site attacker who
    can make the browser send the cookie still cannot produce it.
    """

    if request.method.upper() in SAFE_METHODS:
        return
    payload = _read_session_cookie(request)
    supplied = request.headers.get(CSRF_HEADER_NAME) or await _csrf_from_form(request)
    if not supplied:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF token missing")
    settings: Settings = request.app.state.settings
    try:
        signed_session_id = _csrf_signer(settings).unsign(supplied).decode("utf-8")
    except BadSignature as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF token invalid") from exc
    if not secrets.compare_digest(signed_session_id, str(payload["sid"])):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF token invalid")


def invalidate_web_sessions(session: Session, user: User) -> None:
    """Retire every outstanding cookie for this user.

    Used by logout and intended for password changes and admin security
    resets (T4.3), which must not leave an old cookie usable.
    """

    persisted = session.get(User, user.id)
    if persisted is None:
        return
    persisted.session_generation += 1
    session.add(persisted)
    session.commit()


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, response: Response) -> LoginResponse:
    settings: Settings = request.app.state.settings
    client_host = client_identifier(request, settings.trusted_proxy_hops)
    # Same bucket key as the bearer-token login route, so adding a second
    # entry point does not double an attacker's budget per credential.
    request.app.state.login_limiter.check(f"{client_host}:{payload.username}")
    with Session(request.app.state.engine) as session:
        user = authenticate(session, payload.username, payload.password)
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
        csrf_token = issue_session_cookie(response, user, settings)
        return LoginResponse(
            user_id=user.id,
            display_name=user.display_name,
            is_admin=user.is_admin,
            must_change_password=user.must_change_password,
            csrf_token=csrf_token,
        )


@router.post("/logout", response_model=LogoutResponse, dependencies=[Depends(require_csrf)])
def logout(
    request: Request,
    response: Response,
    user: Annotated[User, Depends(get_current_web_user)],
) -> LogoutResponse:
    with Session(request.app.state.engine) as session:
        invalidate_web_sessions(session, user)
    clear_session_cookie(response, request.app.state.settings)
    return LogoutResponse()


@router.get("/session", response_model=SessionResponse)
def read_session(
    request: Request,
    user: Annotated[User, Depends(require_normal_web_user)],
) -> SessionResponse:
    payload = _read_session_cookie(request)
    settings: Settings = request.app.state.settings
    return SessionResponse(
        user_id=user.id,
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
        csrf_token=_csrf_signer(settings).sign(str(payload["sid"])).decode("utf-8"),
    )


@router.post(
    "/change-password",
    response_model=PasswordChangeResponse,
    dependencies=[Depends(require_csrf)],
)
def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    response: Response,
    user: Annotated[User, Depends(get_current_web_user)],
) -> PasswordChangeResponse:
    """Verify the current password, revoke credentials, and rotate the session.

    This is deliberately available to restricted sessions.  It is the only
    state-changing escape hatch apart from logout, and it creates a fresh
    session only after both generations have been advanced atomically.
    """

    with Session(request.app.state.engine) as session:
        persisted = session.get(User, user.id)
        if persisted is None or authenticate(
            session, user.username, payload.current_password
        ) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
        persisted.password_hash = hash_password(payload.new_password)
        persisted.must_change_password = False
        persisted.session_generation += 1
        persisted.api_token_generation += 1
        session.add(persisted)
        session.commit()
        session.refresh(persisted)
        csrf_token = issue_session_cookie(response, persisted, request.app.state.settings)
        return PasswordChangeResponse(
            user_id=persisted.id,
            display_name=persisted.display_name,
            is_admin=persisted.is_admin,
            must_change_password=False,
            csrf_token=csrf_token,
        )
