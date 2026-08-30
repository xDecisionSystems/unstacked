import subprocess
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from app import backup_runtime
from app.admin_api import router as admin_router
from app.ai_api import asset_router
from app.ai_api import router as ai_router
from app.ai_service import AIContentService
from app.auth import LoginRateLimiter
from app.config import Settings
from app.content import ContentRepository
from app.default_groups import ensure_default_groups, migrate_chapter_permission_paths
from app.models import create_db_engine, migrate_schema
from app.upload_limit import UploadSizeLimitMiddleware
from app.web import router as web_router
from app.web_auth import router as web_auth_router

STATIC_DIR = Path(__file__).parent / "static"

# Baked into the image at Docker build time (see Dockerfile) from the
# SOURCE_COMMIT build arg -- not from `.git`, which the build context never
# has access to on at least one real deployment platform (Coolify imports a
# plain file snapshot of the commit, no `.git` directory at all).
_BAKED_COMMIT_FILE = Path("/app/GIT_COMMIT")


def _resolve_commit() -> str:
    """The exact git commit this running instance was built from.

    Lets an operator confirm a deployed container actually matches a given
    push (``GET /version``) rather than assuming a rebuild picked it up.
    Falls back to asking a local checkout directly outside Docker, where the
    baked file never exists; "unknown" if neither source is available.
    """

    if _BAKED_COMMIT_FILE.is_file():
        baked = _BAKED_COMMIT_FILE.read_text(encoding="utf-8").strip()
        if baked:
            return baked
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    migrate_schema(settings.db_path)
    engine = create_db_engine(settings.db_path)
    content = ContentRepository(settings)
    content.initialize()
    migrate_chapter_permission_paths(engine, content.migrate_legacy_chapters())
    ensure_default_groups(engine, content.docs)
    content.set_default_groups_engine(engine)

    app = FastAPI(
        title="Unstacked AI Content API",
        version="0.1.0",
        description="Permission-aware read and create access to a Git-backed Markdown wiki.",
        lifespan=backup_runtime.lifespan,
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
    # Resolved once at startup, not per request: it never changes for the
    # life of the process, and the local-checkout fallback path shells out.
    app.state.commit = _resolve_commit()
    # A backup target is optional, and now also runtime-editable: it may be
    # configured here from an already-persisted record (or the environment), or
    # later by an administrator through `PUT /api/admin/backup/config`.  No
    # worker, service or route exists until one is -- local disk remains the
    # complete application state on its own.
    backup_runtime.install(app)
    app.include_router(ai_router)
    app.include_router(asset_router)
    app.include_router(web_auth_router)
    app.include_router(admin_router)
    app.include_router(web_router)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/healthz", tags=["System"])
    def healthcheck():
        return {"status": "ok"}

    @app.get("/version", tags=["System"])
    def version():
        return {"commit": app.state.commit}

    @app.get("/llm.md", include_in_schema=False)
    def llm_md():
        return Response(content.read_llm_md(), media_type="text/markdown")

    return app
