"""Administrator-only transport for optional manual backup operations.

These routes exist only once a backup target has been configured -- at startup
or later, through ``PUT /api/admin/backup/config``.  Because a target can also
be *cleared* at runtime, they can outlive the service they call: routes cannot
be un-mounted, so :func:`_manual_backup` reports the "no backup configured"
state as a conflict instead of failing on a missing attribute.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from app.auth import bearer_scheme, get_current_user
from app.git_backend import GitSyncError
from app.manual_backup import ManualBackupService, RestoreResult
from app.models import User
from app.web_auth import get_current_web_user, require_csrf

router = APIRouter(prefix="/api/admin/backup", tags=["Backup"])


class RestoreRequest(BaseModel):
    confirmation_id: str | None = Field(default=None, min_length=20, max_length=200)


class BackupResponse(BaseModel):
    pushed_commits: int


class RestoreResponse(BaseModel):
    action: str
    local_revision: str | None = None
    remote_revision: str | None = None
    confirmation_id: str | None = None
    recovery_verified: bool = False


def _admin(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> User:
    """Accept the same bearer-or-cookie admin transports as admin settings."""

    user = get_current_user(request, credentials) if credentials else get_current_web_user(request)
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required")
    return user


async def _csrf_for_cookie_backup(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> None:
    if credentials is None:
        await require_csrf(request)


def _manual_backup(request: Request) -> ManualBackupService:
    service = getattr(request.app.state, "manual_backup", None)
    if service is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "No content backup target is configured"
        )
    return service


def _restore_response(value: RestoreResult) -> RestoreResponse:
    return RestoreResponse(
        action=value.action,
        local_revision=value.local_revision,
        remote_revision=value.remote_revision,
        confirmation_id=value.confirmation_id,
        recovery_verified=value.recovery_verified,
    )


@router.post("/now", response_model=BackupResponse, dependencies=[Depends(_csrf_for_cookie_backup)])
def backup_now(request: Request, _user: Annotated[User, Depends(_admin)]) -> BackupResponse:
    try:
        return BackupResponse(pushed_commits=_manual_backup(request).backup_now())
    except GitSyncError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Content backup could not be completed"
        ) from exc


@router.post(
    "/restore", response_model=RestoreResponse, dependencies=[Depends(_csrf_for_cookie_backup)]
)
def restore_backup(
    payload: RestoreRequest,
    request: Request,
    _user: Annotated[User, Depends(_admin)],
) -> RestoreResponse:
    try:
        return _restore_response(
            _manual_backup(request).restore(confirmation_id=payload.confirmation_id)
        )
    except GitSyncError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Content restore could not be completed"
        ) from exc
