"""Invite-token helpers shared by the admin API (mints) and the browser UI (redeems).

Unlike the password-reset link in :mod:`app.web`, an invitation is minted
before any account exists: there is no user id to reference yet, so the
token itself carries the email, display name and requested admin flag an
administrator entered. No database row is created until the invitation is
accepted, so there is nothing to roll back if it is never redeemed -- the
token simply expires. Redeeming the same token twice is blocked by the
ordinary unique constraint on ``User.email``, not by any extra state kept
here.
"""

from __future__ import annotations

from urllib.parse import urlencode

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import Settings

INVITE_SALT = "unstacked.invite"
INVITE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60


def _invite_serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.token_secret, salt=INVITE_SALT)


def build_invite_url(settings: Settings, email: str, display_name: str, is_admin: bool) -> str:
    if not settings.public_base_url:
        raise ValueError("UNSTACKED_PUBLIC_BASE_URL must be set before inviting users")
    token = _invite_serializer(settings).dumps(
        {"email": email, "display_name": display_name, "is_admin": is_admin}
    )
    return f"{settings.public_base_url.rstrip('/')}/accept-invite?{urlencode({'token': token})}"


def read_invite_token(settings: Settings, token: str) -> dict[str, object] | None:
    """Decode and validate an invitation token, or ``None`` if it cannot be trusted."""

    try:
        payload = _invite_serializer(settings).loads(token, max_age=INVITE_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("email"), str)
        or not isinstance(payload.get("display_name"), str)
        or not isinstance(payload.get("is_admin"), bool)
    ):
        return None
    return payload
