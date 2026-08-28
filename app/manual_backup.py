"""Explicit, guarded operator actions for the optional git backup target.

The normal application never needs a remote.  This module is constructed only
when one was configured, and deliberately keeps restore replacement behind a
second, one-time confirmation after an independently verified recovery copy.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from git import BadName, GitCommandError, Repo

from app.git_backend import GitBackend, GitSyncError


@dataclass(frozen=True)
class RestoreResult:
    action: str
    local_revision: str | None = None
    remote_revision: str | None = None
    confirmation_id: str | None = None
    recovery_verified: bool = False


@dataclass(frozen=True)
class PendingRestore:
    confirmation_id: str
    recovery_path: Path
    recovery_digest: str
    local_revision: str | None
    remote_revision: str | None
    dirty: bool


class ManualBackupService:
    """Manual push and restore operations serialized with all content writes."""

    def __init__(self, git: GitBackend) -> None:
        self.git = git
        # Configuration has already validated this origin at application
        # startup.  Cache the branch/URL so an absent destination can be
        # restored without inventing a user-controlled target parameter.
        repo = git.repo
        try:
            self._branch = repo.active_branch.name
            self._remote_url = repo.remotes.origin.url
        except (TypeError, AttributeError) as exc:
            raise GitSyncError("content backup remote 'origin' is not configured") from exc
        self._transport_config: dict[str, str] = {}
        for key in ("credential.helper", "core.sshCommand"):
            try:
                self._transport_config[key] = repo.git.config("--get", key).strip()
            except GitCommandError:
                pass
        self._pending: dict[str, PendingRestore] = {}

    def backup_now(self) -> int:
        """Push local commits without forcing or merging anything."""

        return self.git.push_pending()

    def restore(self, *, confirmation_id: str | None = None) -> RestoreResult:
        """Restore only by clone, fast-forward, or confirmed safe replacement."""

        with self.git.write_lock():
            if confirmation_id:
                return self._replace_after_confirmation(confirmation_id)
            target = self.git.repo_path
            if not target.exists() or not any(target.iterdir()):
                return self._clone_into_empty_destination(target)
            repo = self.git.repo
            remote_sha = self._fetch_remote(repo)
            local_sha = repo.head.commit.hexsha
            dirty = repo.is_dirty(untracked_files=True)
            relation = self._history_relation(repo, local_sha, remote_sha)
            if not dirty and relation == "behind":
                self.git.fetch_and_fast_forward()
                return RestoreResult("fast_forwarded", local_sha, remote_sha)
            if not dirty and relation == "equal":
                return RestoreResult("up_to_date", local_sha, remote_sha)
            return self._preserve_for_confirmation(
                target, local_sha=local_sha, remote_sha=remote_sha, dirty=dirty
            )

    def _fetch_remote(self, repo: Repo) -> str:
        try:
            remote = repo.remotes.origin
            remote.fetch()
            return repo.refs[f"{remote.name}/{self._branch}"].commit.hexsha
        except (GitCommandError, AttributeError, BadName, IndexError) as exc:
            # Remote stderr can contain a URL or transport-controlled text;
            # callers only receive this stable message.
            raise GitSyncError("unable to fetch content backup") from exc

    @staticmethod
    def _history_relation(repo: Repo, local_sha: str, remote_sha: str) -> str:
        if local_sha == remote_sha:
            return "equal"
        try:
            repo.git.merge_base("--is-ancestor", local_sha, remote_sha)
            return "behind"
        except GitCommandError as exc:
            if exc.status != 1:
                raise GitSyncError("unable to compare content backup history") from exc
        try:
            repo.git.merge_base("--is-ancestor", remote_sha, local_sha)
            return "ahead"
        except GitCommandError as exc:
            if exc.status == 1:
                return "diverged"
            raise GitSyncError("unable to compare content backup history") from exc

    def _preserve_for_confirmation(
        self, target: Path, *, local_sha: str, remote_sha: str, dirty: bool
    ) -> RestoreResult:
        recovery = self._new_recovery_path(target)
        try:
            shutil.copytree(target, recovery, symlinks=True, copy_function=shutil.copy2)
            self._fsync_tree(recovery)
            source_digest = self._tree_digest(target)
            recovery_digest = self._tree_digest(recovery)
            if not secrets.compare_digest(source_digest, recovery_digest):
                raise GitSyncError("content recovery copy verification failed")
            Repo(recovery).git.fsck("--no-dangling")
        except GitSyncError:
            raise
        except Exception as exc:
            # A partial recovery directory is deliberately retained for human
            # inspection, but it can never authorize replacement.
            raise GitSyncError("unable to create verified content recovery copy") from exc
        confirmation_id = secrets.token_urlsafe(32)
        self._pending[confirmation_id] = PendingRestore(
            confirmation_id=confirmation_id,
            recovery_path=recovery,
            recovery_digest=recovery_digest,
            local_revision=local_sha,
            remote_revision=remote_sha,
            dirty=dirty,
        )
        return RestoreResult(
            "confirmation_required",
            local_sha,
            remote_sha,
            confirmation_id,
            recovery_verified=True,
        )

    def _replace_after_confirmation(self, confirmation_id: str) -> RestoreResult:
        pending = self._pending.pop(confirmation_id, None)
        if pending is None or not secrets.compare_digest(
            self._tree_digest(pending.recovery_path), pending.recovery_digest
        ):
            raise GitSyncError("restore confirmation is invalid or the recovery copy changed")
        target = self.git.repo_path
        if not target.is_dir():
            raise GitSyncError("content destination changed; begin restore again")
        staging = self._clone_to_staging(target)
        retired = target.parent / f".{target.name}.restore-retired-{secrets.token_hex(8)}"
        try:
            # Both renames are same-directory atomic operations.  If a process
            # dies between them, the old checkout remains at ``retired`` and a
            # verified complete recovery copy remains outside the destination.
            os.replace(target, retired)
            os.replace(staging, target)
            self._fsync_directory(target.parent)
        except Exception as exc:
            if not target.exists() and retired.exists():
                try:
                    os.replace(retired, target)
                except OSError:
                    pass
            raise GitSyncError("content restore replacement did not complete safely") from exc
        return RestoreResult(
            "replaced_after_recovery",
            pending.local_revision,
            pending.remote_revision,
            pending.confirmation_id,
            recovery_verified=True,
        )

    def _clone_into_empty_destination(self, target: Path) -> RestoreResult:
        if target.exists() and any(target.iterdir()):
            raise GitSyncError("content destination is not empty")
        staging = self._clone_to_staging(target)
        try:
            if target.exists():
                target.rmdir()
            os.replace(staging, target)
            self._fsync_directory(target.parent)
        except Exception as exc:
            raise GitSyncError("unable to publish restored content checkout") from exc
        return RestoreResult("cloned")

    def _clone_to_staging(self, target: Path) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.restore-", dir=target.parent))
        shutil.rmtree(staging)
        try:
            repo = Repo.init(staging, initial_branch=self._branch)
            remote = repo.create_remote("origin", self._remote_url)
            # Clone setup must use the already configured, repo-local helper
            # and pinned SSH command without putting a credential in an URL.
            for key, value in self._transport_config.items():
                repo.git.config("--local", key, value)
            remote.fetch(refspec=f"refs/heads/{self._branch}:refs/remotes/origin/{self._branch}")
            repo.git.checkout("-B", self._branch, f"origin/{self._branch}")
            repo.git.fsck("--no-dangling")
            self._fsync_tree(staging)
            return staging
        except Exception as exc:
            shutil.rmtree(staging, ignore_errors=True)
            raise GitSyncError("unable to clone content backup") from exc

    @staticmethod
    def _new_recovery_path(target: Path) -> Path:
        directory = target.parent / ".unstacked-recovery"
        directory.mkdir(mode=0o700, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return directory / f"{target.name}-{stamp}-{secrets.token_hex(6)}"

    @staticmethod
    def _tree_digest(root: Path) -> str:
        digest = hashlib.sha256()
        if not root.is_dir():
            raise GitSyncError("content recovery copy is missing")
        for path in sorted(root.rglob("*"), key=lambda value: value.as_posix()):
            relative = path.relative_to(root).as_posix().encode()
            if path.is_symlink():
                digest.update(b"L\0" + relative + b"\0" + os.readlink(path).encode())
            elif path.is_file():
                digest.update(b"F\0" + relative + b"\0")
                with path.open("rb") as handle:
                    for block in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(block)
        return digest.hexdigest()

    @classmethod
    def _fsync_tree(cls, root: Path) -> None:
        for path in root.rglob("*"):
            if path.is_file() and not path.is_symlink():
                with path.open("rb") as handle:
                    os.fsync(handle.fileno())
        cls._fsync_directory(root)

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
