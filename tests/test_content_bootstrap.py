"""The content repository must remain portable without the application."""

import subprocess
import sys
from pathlib import Path

from git import Repo

from app.config import Settings
from app.content import CONTENT_CI_WORKFLOW, ContentRepository

WORKFLOW_PATH = Path(".github/workflows/validate-content.yml")


def _strict_build(content_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mkdocs", "build", "--strict"],
        cwd=content_root,
        check=False,
        capture_output=True,
        text=True,
    )


def _content_repository(tmp_path: Path) -> tuple[ContentRepository, Path]:
    root = tmp_path / "content"
    settings = Settings(
        environment="test",
        content_repo_path=root,
        db_path=tmp_path / "data" / "app.db",
        content_lock_path=tmp_path / "data" / "content.lock",
        api_token_secret="test-secret-that-is-long-and-random-enough",
    )
    content = ContentRepository(settings)
    content.initialize()
    return content, root


def test_bootstrap_commits_a_non_publishing_portable_validation_workflow(tmp_path: Path):
    """Initial content has CI that needs only the content repository itself."""

    _content, root = _content_repository(tmp_path)
    workflow = root / WORKFLOW_PATH
    repo = Repo(root)

    assert workflow.read_text(encoding="utf-8") == CONTENT_CI_WORKFLOW
    blob = repo.head.commit.tree[WORKFLOW_PATH.as_posix()]
    committed = blob.data_stream.read().decode("utf-8")
    assert committed == CONTENT_CI_WORKFLOW
    assert "-r requirements.txt" in CONTENT_CI_WORKFLOW
    assert "mkdocs build --strict" in CONTENT_CI_WORKFLOW
    assert "permissions:\n  contents: read" in CONTENT_CI_WORKFLOW
    assert "deploy" not in CONTENT_CI_WORKFLOW.lower()
    assert "pages" not in CONTENT_CI_WORKFLOW.lower()
    assert "upload-artifact" not in CONTENT_CI_WORKFLOW
    assert "app/" not in CONTENT_CI_WORKFLOW
    assert "database" not in CONTENT_CI_WORKFLOW.lower()

    result = _strict_build(root)
    assert result.returncode == 0, result.stdout + result.stderr


def test_existing_content_repo_receives_missing_ci_once_and_preserves_custom_workflow(
    tmp_path: Path,
):
    """Upgrade only fills the missing managed file; it never overwrites local CI."""

    content, root = _content_repository(tmp_path)
    workflow = root / WORKFLOW_PATH
    repo = Repo(root)

    workflow.unlink()
    repo.index.remove([WORKFLOW_PATH.as_posix()])
    repo.index.commit("Simulate a pre-CI content repository")

    content.initialize()
    assert workflow.read_text(encoding="utf-8") == CONTENT_CI_WORKFLOW
    assert repo.head.commit.message == "Add content validation workflow"
    seeded_head = repo.head.commit.hexsha

    # Re-running startup is a no-op once the managed workflow is present.
    content.initialize()
    assert repo.head.commit.hexsha == seeded_head
    assert not repo.is_dirty()

    custom_workflow = "name: Operator CI\n"
    workflow.write_text(custom_workflow, encoding="utf-8")
    repo.index.add([WORKFLOW_PATH.as_posix()])
    repo.index.commit("Customize validation")

    content.initialize()
    assert workflow.read_text(encoding="utf-8") == custom_workflow
    assert repo.head.commit.message == "Customize validation"
    assert not repo.is_dirty()
