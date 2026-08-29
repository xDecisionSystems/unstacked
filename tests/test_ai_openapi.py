"""The AI-only OpenAPI schema must actually be importable as a ChatGPT Action.

A schema that merely "looks like OpenAPI" is not the same as one a real
action client will accept — a validator that only checks the app's own
`response_model`s would never catch a missing `operationId`, a shape the
target's importer rejects, or a `security` requirement that silently didn't
propagate. Everything here is checked against the real OpenAPI 3.1 JSON
Schema and against constraints ChatGPT Actions specifically enforces, not
against what this repository's code happens to produce.
"""

import openapi_spec_validator

from app.ai_api import build_ai_openapi_schema

# ChatGPT Actions rejects an import with more operations than this.
MAX_ACTION_OPERATIONS = 30
_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}


def _operations(schema: dict) -> list[dict]:
    return [
        operation
        for methods in schema["paths"].values()
        for method, operation in methods.items()
        if method in _METHODS
    ]


def test_the_schema_validates_against_the_real_openapi_spec():
    """Not a shape this app's tests invented — the actual OpenAPI 3.1 schema."""

    schema = build_ai_openapi_schema(public_base_url=None)
    openapi_spec_validator.validate(schema)


def test_every_operation_has_a_unique_operation_id():
    """A missing or duplicate operationId is what an Action importer rejects first."""

    ids = [operation.get("operationId") for operation in _operations(build_ai_openapi_schema(None))]
    assert all(ids)
    assert len(ids) == len(set(ids))


def test_the_operation_count_is_within_the_action_import_limit():
    schema = build_ai_openapi_schema(public_base_url=None)
    assert 0 < len(_operations(schema)) <= MAX_ACTION_OPERATIONS


def test_every_operation_requires_the_bearer_scheme():
    """An Action that silently called an unauthenticated operation would be a bypass."""

    schema = build_ai_openapi_schema(public_base_url=None)
    schemes = schema["components"]["securitySchemes"]
    assert schemes["HTTPBearer"]["type"] == "http"
    assert schemes["HTTPBearer"]["scheme"].lower() == "bearer"
    for operation in _operations(schema):
        requirements = operation.get("security", schema.get("security", []))
        assert any("HTTPBearer" in requirement for requirement in requirements), operation


def test_credential_issuing_routes_are_not_exposed_as_ai_operations():
    """An Action is configured with one token obtained out of band, not by calling
    a login endpoint as one of its own tools."""

    schema = build_ai_openapi_schema(public_base_url=None)
    assert not any(path.startswith("/api/auth/") for path in schema["paths"])


def test_only_the_ai_content_surface_is_included():
    """The admin console and browser-cookie routes must never appear here."""

    schema = build_ai_openapi_schema(public_base_url=None)
    assert all(path.startswith("/api/ai/") for path in schema["paths"])
    assert not any("admin" in path for path in schema["paths"])


def test_a_configured_base_url_becomes_the_one_servers_entry():
    """An Action resolves every call against `servers`; without it, it cannot be used."""

    schema = build_ai_openapi_schema(public_base_url="https://wiki.example.com")
    assert schema["servers"] == [{"url": "https://wiki.example.com"}]
    openapi_spec_validator.validate(schema)


def test_an_unconfigured_base_url_omits_servers_rather_than_a_placeholder():
    """A fake default URL would be silently wrong; omitting it is honest instead."""

    schema = build_ai_openapi_schema(public_base_url=None)
    assert "servers" not in schema


def test_the_live_endpoint_matches_the_schema_the_app_would_build(client):
    """Guards against the route and the builder function drifting apart."""

    response = client.get("/api/ai/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    openapi_spec_validator.validate(schema)
    assert {path for path in schema["paths"]} == {
        path for path in build_ai_openapi_schema(None)["paths"]
    }
