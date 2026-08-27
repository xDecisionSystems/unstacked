from fastapi import FastAPI
from fastapi.responses import Response

from app.ai_api import router as ai_router
from app.ai_service import AIContentService
from app.auth import LoginRateLimiter
from app.config import Settings
from app.content import ContentRepository
from app.models import create_db_engine, migrate_schema


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
    app.state.settings = settings
    app.state.engine = engine
    app.state.content = content
    app.state.ai_service = AIContentService(content)
    app.state.login_limiter = LoginRateLimiter(settings.login_attempts_per_minute)
    app.include_router(ai_router)

    @app.get("/healthz", tags=["System"])
    def healthcheck():
        return {"status": "ok"}

    @app.get("/llm.md", include_in_schema=False)
    def llm_md():
        return Response(content.read_llm_md(), media_type="text/markdown")

    return app
