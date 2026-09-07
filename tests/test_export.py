import stat
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from app.export import ExportAccessDenied, ExportError, StaticExportRunner
from app.models import User
from tests.conftest import bearer


def _runner(app_env) -> StaticExportRunner:
    app, settings, _admin, _token = app_env
    return StaticExportRunner(settings, app.state.content)


def _script(path: Path, body: str) -> Path:
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_static_export_builds_non_drafts_and_keeps_drafts_out_of_search(client, app_env):
    _app, settings, admin, token = app_env
    headers = bearer(token)
    assert (
        client.post("/api/ai/books", json={"title": "Knowledge"}, headers=headers).status_code
        == 201
    )
    assert (
        client.post(
            "/api/ai/books/knowledge/pages",
            json={"title": "Published", "markdown": "# Published"},
            headers=headers,
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/ai/books/knowledge/pages",
            json={"title": "Private Draft", "markdown": "Draft sentinel", "draft": True},
            headers=headers,
        ).status_code
        == 201
    )

    destination = _runner(app_env).build_for(admin)

    assert (destination / "knowledge" / "published" / "index.html").is_file()
    assert not (destination / "knowledge" / "private-draft").exists()
    assert "Draft sentinel" not in (destination / "search" / "search_index.json").read_text()
    assert destination == settings.static_export_path.resolve()


def test_failed_build_preserves_the_last_successful_export(app_env, tmp_path: Path):
    app, settings, _admin, _token = app_env
    good = settings.static_export_path
    good.mkdir(parents=True)
    (good / "sentinel.txt").write_text("last good", encoding="utf-8")
    failure = _script(
        tmp_path / "failing-mkdocs",
        "printf '%s\\n' '/secret/path is not usable'; exit 2",
    )
    assert failure.is_file()
    settings.mkdocs_executable = str(failure)

    with pytest.raises(ExportError, match="MkDocs exited 2") as caught:
        StaticExportRunner(settings, app.state.content).build()

    assert (good / "sentinel.txt").read_text(encoding="utf-8") == "last good"
    assert "/secret/path" in str(caught.value)
    assert str(settings.content_repo_path) not in str(caught.value)


def test_timeout_and_output_cap_preserve_previous_export(app_env, tmp_path: Path):
    app, settings, _admin, _token = app_env
    good = settings.static_export_path
    good.mkdir(parents=True)
    (good / "sentinel.txt").write_text("last good", encoding="utf-8")
    noisy = _script(
        tmp_path / "noisy-mkdocs",
        "head -c 1000 /dev/zero | tr '\\000' x; sleep 10",
    )
    assert noisy.is_file()
    settings.mkdocs_executable = str(noisy)
    settings.static_export_output_limit_bytes = 100
    settings.static_export_timeout_seconds = 1

    with pytest.raises(ExportError, match="output exceeded"):
        StaticExportRunner(settings, app.state.content).build()

    assert (good / "sentinel.txt").read_text(encoding="utf-8") == "last good"


def test_only_administrators_can_build_static_exports(app_env):
    app, settings, _admin, _token = app_env
    user = User(username="reader", email="reader@example.com", password_hash="not-used")

    with pytest.raises(ExportAccessDenied):
        StaticExportRunner(settings, app.state.content).build_for(user)


def test_admin_can_package_portable_mkdocs_source_without_server_paths(app_env, tmp_path: Path):
    app, settings, admin, _token = app_env
    app.state.content.create_book("Knowledge", None, admin)
    app.state.content.create_page("knowledge", "Published", None, "# Published", [], False, admin)

    archive = StaticExportRunner(settings, app.state.content).package_for(admin)

    with ZipFile(BytesIO(archive)) as zip_file:
        assert "unstacked-mkdocs/mkdocs.yml" in zip_file.namelist()
        assert "unstacked-mkdocs/requirements.txt" in zip_file.namelist()
        assert "unstacked-mkdocs/hooks/drafts.py" in zip_file.namelist()
        assert "unstacked-mkdocs/docs/knowledge/published.md" in zip_file.namelist()
        published = zip_file.read("unstacked-mkdocs/docs/knowledge/published.md")
        assert published.endswith(b"# Published\n")
        assert not any(name.startswith("unstacked-mkdocs/.git/") for name in zip_file.namelist())
    assert str(tmp_path) not in archive.decode("latin-1")


def test_packaging_rejects_non_admins_and_excludes_symlinked_files(app_env, tmp_path: Path):
    app, settings, _admin, _token = app_env
    destination = app.state.content.root
    (destination / "safe.txt").write_text("safe", encoding="utf-8")
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("must not escape", encoding="utf-8")
    (destination / "outside.txt").symlink_to(outside)
    user = User(username="reader", email="reader@example.com", password_hash="not-used")
    runner = StaticExportRunner(settings, app.state.content)

    with pytest.raises(ExportAccessDenied):
        runner.package_for(user)

    archive = runner.package_for(_admin)
    with ZipFile(BytesIO(archive)) as zip_file:
        assert "unstacked-mkdocs/safe.txt" in zip_file.namelist()
        assert "unstacked-mkdocs/outside.txt" not in zip_file.namelist()
        assert b"must not escape" not in archive
