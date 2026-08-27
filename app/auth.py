from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from threading import Lock
from time import monotonic
from uuid import uuid4

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from pwdlib import PasswordHash
from sqlmodel import Session, select

from app.config import Settings
from app.models import User

password_hash = PasswordHash.recommended()
DUMMY_PASSWORD_HASH = password_hash.hash("dummy-password")
bearer_scheme = HTTPBearer(auto_error=False)


class LoginRateLimiter:
    def __init__(self, attempts: int, window_seconds: int = 60):
        self.attempts = attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str) -> None:
        now = monotonic()
        with self._lock:
            history = self._attempts[key]
            while history and history[0] <= now - self.window_seconds:
                history.popleft()
            if len(history) >= self.attempts:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many authentication attempts",
                    headers={"Retry-After": str(self.window_seconds)},
                )
            history.append(now)


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def authenticate(session: Session, email: str, password: str) -> User | None:
    user = session.exec(select(User).where(User.email == email.casefold())).first()
    if user is None:
        password_hash.verify(password, DUMMY_PASSWORD_HASH)
        return None
    if not user.is_active or not password_hash.verify(password, user.password_hash):
        return None
    return user


def create_api_token(user: User, settings: Settings) -> str:
    if user.id is None:
        raise ValueError("user must be persisted before issuing a token")
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "generation": user.api_token_generation,
        "iat": now,
        "exp": now + timedelta(seconds=settings.api_token_ttl_seconds),
        "aud": settings.api_token_audience,
        "jti": str(uuid4()),
    }
    return jwt.encode(payload, settings.api_token_secret, algorithm="HS256")


def decode_api_token(token: str, settings: Settings) -> tuple[int, int]:
    try:
        payload = jwt.decode(
            token,
            settings.api_token_secret,
            algorithms=["HS256"],
            audience=settings.api_token_audience,
            options={"require": ["sub", "generation", "iat", "exp", "aud", "jti"]},
        )
        return int(payload["sub"]), int(payload["generation"])
    except (InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User:
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id, generation = decode_api_token(credentials.credentials, request.app.state.settings)
    with Session(request.app.state.engine) as session:
        user = session.get(User, user_id)
        if user is None or not user.is_active or user.api_token_generation != generation:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        session.expunge(user)
        return user
