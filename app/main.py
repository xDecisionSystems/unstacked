from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from app.admin_api import router as admin_router
from app.ai_api import asset_router
from app.ai_api import router as ai_router
from app.ai_service import AIContentService
from app.auth import LoginRateLimiter
from app.backup import BackupSyncWorker
from app.backup_api import router as backup_router
from app.config import Settings
from app.content import ContentRepository
from app.manual_backup import ManualBackupService
from app.models import create_db_engine, migrate_schema
from app.upload_limit import UploadSizeLimitMiddleware
from app.web import router as web_router
from app.web_auth import router as web_auth_router

STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    migrate_schema(settings.db_path)
    engine = create_db_engine(settings.db_path)
    content = ContentRepository(settings)
    content.initialize()

    app = FastAPI(
        title="Unstacked AI Content API",
        version="0.1.0",
        description="Permission-aware read and create access to a Git-backed Markdown wiki.",
    )
    # Registered before any router so it wraps the whole application: an
    # oversized upload has to be refused above the framework, not inside a
    # handler the framework only reaches after buffering the body.
    app.add_middleware(UploadSizeLimitMiddleware, max_bytes=settings.max_upload_bytes)
    app.state.settings = settings
    app.state.engine = engine
    app.state.content = content
    app.state.ai_service = AIContentService(content)
    app.state.login_limiter = LoginRateLimiter(
        settings.login_attempts_per_minute,
        max_keys=settings.max_rate_limit_keys,
    )
    # A remote is optional.  Do not construct (or start) a worker when none
    # was configured: local disk remains the complete application state.
    if settings.github_remote_url:
        app.state.manual_backup = ManualBackupService(content.git)
        worker = BackupSyncWorker(
            content.git,
            debounce_seconds=settings.backup_sync_debounce_seconds,
            max_backoff_seconds=settings.backup_sync_max_backoff_seconds,
        )
        app.state.backup_sync_worker = worker

        @app.on_event("startup")
        def start_backup_sync_worker() -> None:
            worker.start()

        @app.on_event("shutdown")
        def stop_backup_sync_worker() -> None:
            worker.stop()
        app.include_router(backup_router)
    app.include_router(ai_router)
    app.include_router(asset_router)
    app.include_router(web_auth_router)
    app.include_router(admin_router)
    app.include_router(web_router)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/healthz", tags=["System"])
    def healthcheck():
        return {"status": "ok"}

    @app.get("/llm.md", include_in_schema=False)
    def llm_md():
        return Response(content.read_llm_md(), media_type="text/markdown")

    return app
