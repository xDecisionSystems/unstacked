"""Administrator-only transport for optional manual backup operations."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.git_backend import GitSyncError
from app.manual_backup import RestoreResult
from app.models import User

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


def _admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required")
    return user


def _restore_response(value: RestoreResult) -> RestoreResponse:
    return RestoreResponse(
        action=value.action,
        local_revision=value.local_revision,
        remote_revision=value.remote_revision,
        confirmation_id=value.confirmation_id,
        recovery_verified=value.recovery_verified,
    )


@router.post("/now", response_model=BackupResponse)
def backup_now(request: Request, _user: Annotated[User, Depends(_admin)]) -> BackupResponse:
    try:
        return BackupResponse(pushed_commits=request.app.state.manual_backup.backup_now())
    except GitSyncError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Content backup could not be completed"
        ) from exc


@router.post("/restore", response_model=RestoreResponse)
def restore_backup(
    payload: RestoreRequest,
    request: Request,
    _user: Annotated[User, Depends(_admin)],
) -> RestoreResponse:
    try:
        return _restore_response(
            request.app.state.manual_backup.restore(confirmation_id=payload.confirmation_id)
        )
    except GitSyncError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Content restore could not be completed"
        ) from exc
