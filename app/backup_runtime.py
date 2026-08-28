"""Wire the optional backup services on and off while the app is running.

Everything a backup target needs -- the manual push/restore service (T6.3),
the debounced sync worker (T6.2) and the ``/api/admin/backup/*`` routes -- used
to be constructed once in ``create_app`` and only when an environment variable
happened to be set.  That is exactly the case an administrator configuring a
target through the admin API is *not* in: their instance started with nothing
configured, so none of it existed.

**Chosen approach: lazy wiring, no restart.**  Starlette resolves routes per
request by walking ``app.router.routes``, so a router included after startup
serves immediately (the OpenAPI cache is the only thing that needs clearing),
and the worker is a plain daemon thread that can be started at any point.  So
:func:`activate` builds and starts everything the moment a configuration is
saved, and :func:`deactivate` stops and drops it the moment one is cleared.
The alternative -- persist now, activate at the next restart -- was rejected
because "an admin configures ... a backup target entirely through the UI with
no env var edit or redeploy" is the task's own done-when.

Nothing here runs when no target is configured: no thread, no service, and no
routes.  That default is fully supported and must stay free of side effects.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.backup import BackupStatus, BackupSyncWorker
from app.backup_api import router as backup_router
from app.backup_config import effective_target
from app.git_backend import GitSyncError
from app.manual_backup import ManualBackupService

logger = logging.getLogger("unstacked.backup")


def install(app: FastAPI) -> None:
    """Initialize runtime state and activate an already-configured target.

    Called once from ``create_app`` before :func:`lifespan` starts. A target may
    also be configured later in this process's life through the admin API.
    """

    # The worker thread must not start while the app is merely being
    # constructed (tests build apps they never serve from).  Until the startup
    # event fires, activation only builds the services.
    app.state.backup_serving = False
    if (
        effective_target(app.state.settings).configured
        and app.state.content.backup_config_error is None
    ):
        activate(app)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start and stop the optional worker with the application's lifespan."""

    try:
        app.state.backup_serving = True
        worker = _worker(app)
        if worker is not None:
            worker.start()
        yield
    finally:
        app.state.backup_serving = False
        worker = _worker(app)
        if worker is not None:
            worker.stop()


def activate(app: FastAPI) -> bool:
    """Build, start and mount everything the configured target needs.

    Idempotent and safe to call after a configuration change: any previous
    worker is stopped first, so a re-pointed remote is never served by a
    thread still holding the old one.  Returns ``False`` when the services
    could not be built -- which is not an error here: the caller has already
    validated the target through ``configure_remote``, and a backup that
    cannot be wired must never take a request down with it.
    """

    deactivate(app)
    content = app.state.content
    settings = app.state.settings
    try:
        service = ManualBackupService(content.git)
    except GitSyncError as exc:
        logger.warning("content backup services could not be started: %s", exc)
        return False
    worker = BackupSyncWorker(
        content.git,
        debounce_seconds=settings.backup_sync_debounce_seconds,
        max_backoff_seconds=settings.backup_sync_max_backoff_seconds,
    )
    app.state.manual_backup = service
    app.state.backup_sync_worker = worker
    if app.state.backup_serving:
        worker.start()
    _mount_routes(app)
    return True


def deactivate(app: FastAPI) -> None:
    """Stop and forget the backup services, back to the "no target" state.

    The routes stay mounted once they have been -- Starlette has no supported
    route removal -- but they answer 409 without a service, which is what
    :mod:`app.backup_api` does when ``manual_backup`` is absent.
    """

    worker = _worker(app)
    if worker is not None:
        worker.stop()
    for name in ("backup_sync_worker", "manual_backup"):
        if hasattr(app.state, name):
            delattr(app.state, name)


def is_active(app: FastAPI) -> bool:
    return _worker(app) is not None


def status(app: FastAPI) -> BackupStatus | None:
    """The current sync state, or ``None`` when no target is wired up."""

    worker = _worker(app)
    return worker.status() if worker is not None else None


def _worker(app: FastAPI) -> BackupSyncWorker | None:
    return getattr(app.state, "backup_sync_worker", None)


def _mount_routes(app: FastAPI) -> None:
    """Include the backup router once, even after the app is serving.

    Starlette matches each request against ``app.router.routes`` as it arrives,
    so appending to that list takes effect on the next request.  The generated
    schema is cached once rendered, so it is dropped here and rebuilt on the
    next ``/openapi.json``.
    """

    if getattr(app.state, "backup_routes_mounted", False):
        return
    app.include_router(backup_router)
    app.state.backup_routes_mounted = True
    app.openapi_schema = None
