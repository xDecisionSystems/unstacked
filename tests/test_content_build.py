import subprocess
import sys
from pathlib import Path

from tests.conftest import bearer


def test_api_created_tree_builds_strictly_and_excludes_drafts(client, app_env):
    _app, settings, _admin, token = app_env
    headers = bearer(token)
    assert (
        client.post("/api/ai/books", json={"title": "Knowledge"}, headers=headers).status_code
        == 201
    )
    assert (
        client.post(
            "/api/ai/books/knowledge/pages",
            json={"title": "Public Page", "markdown": "# Public Page"},
            headers=headers,
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/ai/books/knowledge/pages",
            json={"title": "Draft Page", "markdown": "# Draft Page", "draft": True},
            headers=headers,
        ).status_code
        == 201
    )

    result = subprocess.run(
        [sys.executable, "-m", "mkdocs", "build", "--strict"],
        cwd=settings.content_repo_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    site = Path(settings.content_repo_path) / "site"
    workflow = settings.content_repo_path / "docs" / "llm.md"
    assert workflow.is_file()
    assert "### user" in workflow.read_text(encoding="utf-8")
    assert (site / "llm.md").read_text(encoding="utf-8") == workflow.read_text(encoding="utf-8")
    assert (site / "llm" / "index.html").is_file()
    assert (site / "knowledge" / "public-page" / "index.html").is_file()
    assert not (site / "knowledge" / "draft-page").exists()
    assert "Draft Page" not in (site / "search" / "search_index.json").read_text()


def test_hand_authored_crlf_draft_is_still_excluded(client, app_env):
    """A Windows-edited page must not publish just because of its line endings."""

    _app, settings, _admin, token = app_env
    headers = bearer(token)
    client.post("/api/ai/books", json={"title": "Knowledge"}, headers=headers)

    crlf_draft = settings.content_repo_path / "docs" / "knowledge" / "crlf-draft.md"
    crlf_draft.write_bytes(
        b"---\r\ntitle: CRLF Draft Sentinel\r\ndraft: true\r\n---\r\n\r\n# CRLF Draft Sentinel\r\n"
    )

    result = subprocess.run(
        [sys.executable, "-m", "mkdocs", "build", "--strict"],
        cwd=settings.content_repo_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    site = Path(settings.content_repo_path) / "site"
    assert not (site / "knowledge" / "crlf-draft").exists()
    assert "CRLF Draft Sentinel" not in (site / "search" / "search_index.json").read_text()
