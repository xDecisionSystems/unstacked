"""System-level routes that exist to answer operational questions from
outside the app, not to serve the wiki itself: is it up (``/healthz``), and
exactly which commit is it running (``/version``) -- the latter exists so an
operator can confirm a redeployed container actually picked up a given push,
rather than assuming a rebuild took effect.
"""

import subprocess

from app import main as app_main


def test_healthz_reports_ok(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_version_endpoint_reports_the_current_checkout_commit(client):
    """Outside Docker, the baked file never exists, so this exercises the
    local-checkout fallback -- and gives a real, independently-verifiable
    expected value to compare against."""

    expected = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    response = client.get("/version")
    assert response.status_code == 200
    assert response.json() == {"commit": expected}


def test_resolve_commit_prefers_the_baked_file_when_present(tmp_path, monkeypatch):
    baked = tmp_path / "GIT_COMMIT"
    baked.write_text("abc123deadbeef\n", encoding="utf-8")
    monkeypatch.setattr(app_main, "_BAKED_COMMIT_FILE", baked)
    assert app_main._resolve_commit() == "abc123deadbeef"


def test_resolve_commit_ignores_a_blank_baked_file(tmp_path, monkeypatch):
    """A present-but-empty file (e.g. a build step that ran but wrote
    nothing) must fall back rather than report an empty commit."""

    baked = tmp_path / "GIT_COMMIT"
    baked.write_text("   \n", encoding="utf-8")
    monkeypatch.setattr(app_main, "_BAKED_COMMIT_FILE", baked)
    assert app_main._resolve_commit() != ""


def test_resolve_commit_is_unknown_when_neither_source_is_available(tmp_path, monkeypatch):
    monkeypatch.setattr(app_main, "_BAKED_COMMIT_FILE", tmp_path / "does-not-exist")

    def _boom(*args, **kwargs):
        raise OSError("git not installed")

    monkeypatch.setattr(app_main.subprocess, "run", _boom)
    assert app_main._resolve_commit() == "unknown"
