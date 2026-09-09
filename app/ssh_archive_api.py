"""Admin API for optional SSH-server workspace archive backups."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field

from app.admin_api import AdminActor, CsrfGuard
from app.ssh_archive import (
    SshArchiveTarget,
    WorkspaceArchiveError,
    WorkspaceArchiveService,
    discover_target_host_key,
    load_target,
    save_target,
)

router = APIRouter(prefix="/api/admin/ssh-archive", tags=["SSH archive backup"])


class ConfigUpdate(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    username: str = Field(min_length=1, max_length=64)
    remote_path: str = Field(min_length=1, max_length=2048)
    ssh_key_path: str = Field(min_length=1, max_length=4096)
    port: int = Field(default=22, ge=1, le=65535)
    fingerprint: str = Field(min_length=1, max_length=200)
    schedules: list[Literal["hourly", "daily", "weekly"]] = []


class ConfigResponse(BaseModel):
    configured: bool
    host: str | None = None
    username: str | None = None
    remote_path: str | None = None
    port: int = 22
    fingerprint: str | None = None
    schedules: list[str] = []
    updated_at: str | None = None


class HostKeyRequest(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=22, ge=1, le=65535)


class HostKeyResponse(BaseModel):
    fingerprint: str


class RestoreResponse(BaseModel):
    action: str
    confirmation_id: str | None = None


class ConfirmRequest(BaseModel):
    confirmation_id: str = Field(min_length=20, max_length=200)


def _service(request: Request) -> WorkspaceArchiveService:
    service = getattr(request.app.state, "ssh_archive_service", None)
    if service is None:
        service = WorkspaceArchiveService(
            request.app.state.settings, request.app.state.content, request.app.state.engine
        )
        request.app.state.ssh_archive_service = service
    return service


def _response(request: Request) -> ConfigResponse:
    target = load_target(request.app.state.settings.ssh_archive_config_path)
    return ConfigResponse(
        configured=target.configured,
        host=target.host or None,
        username=target.username or None,
        remote_path=target.remote_path or None,
        port=target.port,
        fingerprint=target.fingerprint,
        schedules=list(target.schedules),
        updated_at=target.updated_at,
    )


@router.get("/config", response_model=ConfigResponse)
def config(request: Request, _actor: AdminActor) -> ConfigResponse:
    return _response(request)


@router.post("/host-key", response_model=HostKeyResponse, dependencies=CsrfGuard)
def host_key(payload: HostKeyRequest, _actor: AdminActor) -> HostKeyResponse:
    try:
        found = discover_target_host_key(payload.host, payload.port)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return HostKeyResponse(fingerprint=found.fingerprint)


@router.put("/config", response_model=ConfigResponse, dependencies=CsrfGuard)
def save_config(payload: ConfigUpdate, request: Request, _actor: AdminActor) -> ConfigResponse:
    try:
        found = discover_target_host_key(payload.host, payload.port)
        save_target(
            request.app.state.settings,
            SshArchiveTarget(
                host=payload.host,
                username=payload.username,
                remote_path=payload.remote_path,
                ssh_key_path=Path(payload.ssh_key_path),
                port=payload.port,
                fingerprint=payload.fingerprint,
                schedules=tuple(dict.fromkeys(payload.schedules)),
            ),
            found,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return _response(request)


@router.post("/now", dependencies=CsrfGuard)
def upload_now(request: Request, _actor: AdminActor) -> dict[str, str]:
    try:
        return {"filename": _service(request).upload()}
    except WorkspaceArchiveError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.post("/restore/prepare", response_model=RestoreResponse, dependencies=CsrfGuard)
async def prepare_restore(
    request: Request, archive: UploadFile = File(...), actor: AdminActor = None
) -> RestoreResponse:
    if archive.content_type not in {"application/zip", "application/x-zip-compressed"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose a ZIP file")
    data = await archive.read(request.app.state.settings.max_upload_bytes + 1)
    if len(data) > request.app.state.settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, "Import ZIP exceeds the configured size limit"
        )
    try:
        return RestoreResponse(
            action="confirmation_required",
            confirmation_id=_service(request).prepare_restore(data, actor),
        )
    except WorkspaceArchiveError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.post("/restore/confirm", response_model=RestoreResponse, dependencies=CsrfGuard)
def confirm_restore(
    payload: ConfirmRequest, request: Request, _actor: AdminActor
) -> RestoreResponse:
    try:
        _service(request).confirm_restore(payload.confirmation_id)
    except WorkspaceArchiveError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return RestoreResponse(action="restored")
