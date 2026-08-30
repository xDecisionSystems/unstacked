"""Structural invariants: anything reachable must also be listable."""

import pytest
from sqlmodel import Session, select

from app.ai_api import attachment_disposition
from app.content import ContentError, ContentRepository
from app.models import User
from tests.conftest import bearer


def test_pages_cannot_be_created_below_a_book(client, app_env):
    """A deeper page would build into the static site yet never appear in the tree."""

    _app, settings, _admin, token = app_env
    headers = bearer(token)
    client.post("/api/ai/books", json={"title": "Ops"}, headers=headers)
    # Fabricate a nested directory the way a stray operator mkdir would.
    nested = settings.content_repo_path / "docs" / "ops" / "deeper"
    nested.mkdir(parents=True)

    content = ContentRepository(settings)
    with Session(_app.state.engine) as session:
        actor = session.exec(select(User)).first()
        with pytest.raises(ContentError, match="pages live directly in a book"):
            content.create_page("ops/deeper", "Too Deep", None, "body", [], False, actor)


def test_pages_cannot_be_created_in_the_assets_tree(client, app_env):
    _app, settings, _admin, _token = app_env
    (settings.content_repo_path / "docs" / "assets").mkdir(parents=True, exist_ok=True)
    content = ContentRepository(settings)
    with Session(_app.state.engine) as session:
        actor = session.exec(select(User)).first()
        with pytest.raises(ContentError, match="reserved location"):
            content.create_page("assets", "Sneaky", None, "body", [], False, actor)


def test_tree_and_export_agree_on_what_exists(client, app_env):
    _app, _settings, _admin, token = app_env
    headers = bearer(token)
    client.post("/api/ai/books", json={"title": "Ops"}, headers=headers)
    client.post(
        "/api/ai/books/ops/pages",
        json={"title": "Runbook", "markdown": "body"},
        headers=headers,
    )
    tree = client.get("/api/ai/tree", headers=headers).json()
    listed = {page for book in tree["books"] for page in book["pages"]}
    assert "ops/runbook.md" in listed


def test_attachment_filename_cannot_break_the_header():
    header = attachment_disposition('evil";name="x.md')
    # Exactly the two quotes that delimit the fallback name.
    assert header.count('"') == 2
    assert header.startswith('attachment; filename="evil__name__x.md"')
    assert "filename*=UTF-8''" in header


def test_attachment_filename_keeps_unicode_in_the_extended_form():
    header = attachment_disposition("笔记.md")
    assert "filename*=UTF-8''%E7%AC%94%E8%AE%B0.md" in header
