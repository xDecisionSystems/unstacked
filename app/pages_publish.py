"""Optional publication of the filtered public site to a GitHub Pages repo.

This is deliberately separate from the content backup in :mod:`app.backup_config`:
the backup pushes the complete, unfiltered ``content/`` repository and must go
to a *private* remote, while this pushes only the already-filtered static HTML
that :class:`app.public_site.PublicSiteBuilder` produced -- exactly what the
public hostname serves -- to a repository that is normally public.

Nothing here is required.  With no record saved, :func:`load` returns ``None``
and every caller treats publication as a no-op.

* The record lives at ``data/pages_config.json`` and holds only paths and
  non-secret values; the deploy key and pinned ``known_hosts`` are their own
  owner-only files beside it.
* The working repository at ``data/pages-repo`` is a scratch checkout of the
  Pages branch.  Each publish fetches the branch, moves ``HEAD`` onto it
  without touching the worktree, replaces the worktree with the new build and
  commits only if something changed, then pushes *without* force -- so history
  on the Pages branch is preserved and a concurrent external push is reported
  rather than overwritten.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from app import backup_config
from app.config import Settings
from app.git_backend import scrub_git_output

logger = logging.getLogger("unstacked.pages")

CONFIG_FILENAME = "pages_config.json"
DEPLOY_KEY_FILENAME = "pages_deploy_key"
KNOWN_HOSTS_FILENAME = "pages_known_hosts"
REPO_DIRNAME = "pages-repo"

_BRANCH = re.compile(r"^(?!-)(?!.*\.\.)[A-Za-z0-9._/-]{1,100}$")
_DOMAIN = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9-]{1,63}\.)+[A-Za-z]{2,63}$")
_GIT_TIMEOUT = 120


class PagesPublishError(Exception):
    """A safe-to-display reason the public site was not pushed."""


@dataclass(frozen=True)
class PagesTarget:
    url: str
    branch: str
    ssh_host_fingerprint: str
    cname: str | None = None
    updated_at: str | None = None


def _data_dir(settings: Settings) -> Path:
    return settings.backup_config_path.parent


def config_path(settings: Settings) -> Path:
    return _data_dir(settings) / CONFIG_FILENAME


def deploy_key_path(settings: Settings) -> Path:
    return _data_dir(settings) / DEPLOY_KEY_FILENAME


def known_hosts_path(settings: Settings) -> Path:
    return _data_dir(settings) / KNOWN_HOSTS_FILENAME


def repo_path(settings: Settings) -> Path:
    return _data_dir(settings) / REPO_DIRNAME


def validate(url: str, branch: str, cname: str | None) -> tuple[str, str, str | None]:
    url = url.strip()
    if backup_config._ssh_endpoint(url) is None:
        raise ValueError("An SSH repository URL such as git@github.com:org/repo.git is required")
    branch = branch.strip()
    if not _BRANCH.match(branch) or branch.endswith((".", "/", ".lock")):
        raise ValueError("Enter a valid branch name")
    cname = (cname or "").strip().lower() or None
    if cname is not None and not _DOMAIN.match(cname):
        raise ValueError("Enter a bare custom domain such as docs.example.com, or leave it blank")
    return url, branch, cname


def load(settings: Settings) -> PagesTarget | None:
    path = config_path(settings)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return PagesTarget(
            url=raw["url"],
            branch=raw["branch"],
            ssh_host_fingerprint=raw["ssh_host_fingerprint"],
            cname=raw.get("cname"),
            updated_at=raw.get("updated_at"),
        )
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError):
        logger.warning("ignoring unreadable GitHub Pages configuration at %s", path)
        return None


def save(settings: Settings, target: PagesTarget, known_hosts_line: str) -> PagesTarget:
    stored = PagesTarget(
        url=target.url,
        branch=target.branch,
        ssh_host_fingerprint=target.ssh_host_fingerprint,
        cname=target.cname,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    backup_config.write_private_bytes(known_hosts_path(settings), known_hosts_line.encode("utf-8"))
    backup_config.write_private_bytes(
        config_path(settings), json.dumps(asdict(stored), indent=2).encode("utf-8")
    )
    return stored


def clear(settings: Settings) -> None:
    """Forget the target and its scratch checkout; the deploy key is kept."""

    config_path(settings).unlink(missing_ok=True)
    known_hosts_path(settings).unlink(missing_ok=True)
    shutil.rmtree(repo_path(settings), ignore_errors=True)


def _ssh_command(settings: Settings) -> str:
    key = deploy_key_path(settings)
    known_hosts = known_hosts_path(settings)
    if not key.is_file():
        raise PagesPublishError("Generate a GitHub Pages deploy key first")
    if not known_hosts.is_file() or known_hosts.stat().st_size == 0:
        raise PagesPublishError("Confirm the SSH server fingerprint first")
    return " ".join(
        [
            "ssh",
            "-o BatchMode=yes",
            "-o IdentitiesOnly=yes",
            f"-i {shlex.quote(str(key))}",
            f"-o UserKnownHostsFile={shlex.quote(str(known_hosts))}",
            "-o GlobalKnownHostsFile=/dev/null",
            "-o StrictHostKeyChecking=yes",
        ]
    )


def _git(settings: Settings, args: list[str], cwd: Path | None = None) -> str:
    env = {
        **os.environ,
        "GIT_SSH_COMMAND": _ssh_command(settings),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": "Unstacked",
        "GIT_AUTHOR_EMAIL": "unstacked@localhost",
        "GIT_COMMITTER_NAME": "Unstacked",
        "GIT_COMMITTER_EMAIL": "unstacked@localhost",
    }
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PagesPublishError("git could not be run for GitHub Pages publication") from exc
    if result.returncode != 0:
        detail = scrub_git_output((result.stderr or result.stdout).strip()).splitlines()
        message = detail[-1] if detail else f"git {args[0]} failed"
        raise PagesPublishError(f"GitHub Pages push failed: {message[:300]}")
    return result.stdout


def test_access(settings: Settings, url: str) -> None:
    """Prove the key and pinned host key can reach the repository."""

    _git(settings, ["ls-remote", "--heads", url])


def publish(settings: Settings, target: PagesTarget, site: Path) -> bool:
    """Push ``site`` to the Pages branch; return whether a new commit was pushed."""

    if not (site / "index.html").is_file():
        raise PagesPublishError("No built public site to publish yet")
    repo = repo_path(settings)
    if not (repo / ".git").is_dir():
        shutil.rmtree(repo, ignore_errors=True)
        repo.mkdir(parents=True)
        _git(settings, ["init", "-q"], cwd=repo)
    if "origin" in _git(settings, ["remote"], cwd=repo).split():
        _git(settings, ["remote", "set-url", "origin", target.url], cwd=repo)
    else:
        _git(settings, ["remote", "add", "origin", target.url], cwd=repo)
    branch = target.branch
    _git(settings, ["symbolic-ref", "HEAD", f"refs/heads/{branch}"], cwd=repo)
    if _git(settings, ["ls-remote", "--heads", "origin", branch], cwd=repo).strip():
        _git(settings, ["fetch", "-q", "--depth", "1", "origin", branch], cwd=repo)
        # Move the branch onto the remote tip without touching files, so the
        # commit below is a fast-forward and the push never needs force.
        _git(settings, ["reset", "-q", "--soft", "FETCH_HEAD"], cwd=repo)

    for entry in repo.iterdir():
        if entry.name == ".git":
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    shutil.copytree(site, repo, dirs_exist_ok=True, symlinks=False)
    # MkDocs output has underscore-prefixed paths Jekyll would drop.
    (repo / ".nojekyll").write_text("", encoding="utf-8")
    if target.cname:
        (repo / "CNAME").write_text(target.cname + "\n", encoding="utf-8")

    _git(settings, ["add", "-A"], cwd=repo)
    if not _git(settings, ["status", "--porcelain"], cwd=repo).strip():
        return False
    _git(settings, ["commit", "-q", "-m", "Publish public site from Unstacked"], cwd=repo)
    _git(settings, ["push", "-q", "origin", f"HEAD:refs/heads/{branch}"], cwd=repo)
    return True


class PagesPublisher:
    """Push successful public builds to GitHub Pages when a target is saved."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.Lock()
        self.last_success_at: str | None = None
        self.last_error: str | None = None

    def publish_now(self, site: Path) -> bool:
        target = load(self.settings)
        if target is None:
            raise PagesPublishError("No GitHub Pages repository is configured")
        with self._lock:
            try:
                pushed = publish(self.settings, target, site)
            except PagesPublishError as exc:
                self.last_error = str(exc)
                raise
            except OSError as exc:
                self.last_error = "GitHub Pages publication failed"
                raise PagesPublishError(self.last_error) from exc
        self.last_success_at = datetime.now(timezone.utc).isoformat()
        self.last_error = None
        return pushed

    def publish_recording_failure(self, site: Path) -> None:
        """Best-effort hook after a public build; never raises."""

        if load(self.settings) is None:
            return
        try:
            self.publish_now(site)
        except PagesPublishError:
            logger.warning("GitHub Pages publication failed: %s", self.last_error)
