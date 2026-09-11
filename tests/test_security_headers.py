from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient as StarletteTestClient

from app.config import Settings
from app.main import create_app
from app.security_headers import SecurityHeadersMiddleware


def test_every_response_carries_the_static_security_headers(client):
    response = client.get("/login")
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert (
        response.headers["permissions-policy"]
        == "geolocation=(), microphone=(), camera=()"
    )


def test_hsts_is_absent_outside_production(client):
    response = client.get("/login")
    assert "strict-transport-security" not in response.headers


def test_hsts_is_present_in_production(tmp_path):
    settings = Settings(
        environment="production",
        content_repo_path=tmp_path / "content",
        db_path=tmp_path / "data" / "app.db",
        content_lock_path=tmp_path / "data" / "content.lock",
        static_export_path=tmp_path / "data" / "static-export",
        public_site_path=tmp_path / "public-site",
        backup_config_path=tmp_path / "data" / "backup_config.json",
        ssh_archive_config_path=tmp_path / "data" / "ssh_archive.json",
        theme_config_path=tmp_path / "data" / "theme.json",
        smtp_config_path=tmp_path / "data" / "smtp.json",
        api_token_secret="test-secret-that-is-long-and-random-enough",
    )
    app = create_app(settings)
    with StarletteTestClient(app) as test_client:
        response = test_client.get("/login")
    assert response.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"


def test_a_header_a_route_already_set_is_not_duplicated():
    """A route (e.g. the asset route) may set one of these headers itself.

    The middleware must not add a second copy alongside it.
    """

    async def already_sets_it(request):
        return PlainTextResponse("ok", headers={"X-Content-Type-Options": "nosniff"})

    app = Starlette(routes=[Route("/", already_sets_it)])
    app.add_middleware(SecurityHeadersMiddleware, hsts=False)

    with StarletteTestClient(app) as test_client:
        response = test_client.get("/")
    assert response.headers.get_list("x-content-type-options") == ["nosniff"]
