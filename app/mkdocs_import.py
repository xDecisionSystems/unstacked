"""Guarded replacement of a content checkout from a portable MkDocs ZIP."""

from __future__ import annotations

import os
import secrets
import shutil
import stat
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from git import Actor, Repo

from app.backup_config import effective_target
from app.content import ContentRepository
from app.manual_backup import ManualBackupService
from app.models import User

MAX_ARCHIVE_FILES = 10_000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 128 * 1024 * 1024


class MkDocsImportError(RuntimeError):
    """A safe explanation for an archive that cannot be imported."""


@dataclass(frozen=True)
class ImportResult:
    action: str
    confirmation_id: str | None = None
    recovery_verified: bool = False


@dataclass(frozen=True)
class PendingImport:
    staging_path: Path
    staging_digest: str
    recovery_path: Path
    recovery_digest: str


class MkDocsImportService:
    """Validate a ZIP into staging, then replace only after confirmation."""

    def __init__(self, content: ContentRepository) -> None:
        self.content = content
        self._pending: dict[str, PendingImport] = {}

    def prepare(self, archive: bytes, actor: User) -> ImportResult:
        if not archive:
            raise MkDocsImportError("Choose a MkDocs ZIP file to import")
        with self.content.git.write_lock():
            staging = self._extract_to_staging(archive, actor)
            try:
                recovery = self._recovery_copy()
                token = secrets.token_urlsafe(32)
                self._pending[token] = PendingImport(
                    staging, self._tree_digest(staging), recovery, self._tree_digest(recovery)
                )
                return ImportResult("confirmation_required", token, True)
            except Exception:
                shutil.rmtree(staging, ignore_errors=True)
                raise

    def confirm(self, confirmation_id: str) -> ImportResult:
        with self.content.git.write_lock():
            pending = self._pending.pop(confirmation_id, None)
            if pending is None:
                raise MkDocsImportError("Import confirmation is invalid or has expired")
            if not secrets.compare_digest(
                self._tree_digest(pending.staging_path), pending.staging_digest
            ):
                raise MkDocsImportError("Prepared import files changed; upload the archive again")
            if not secrets.compare_digest(
                self._tree_digest(pending.recovery_path), pending.recovery_digest
            ):
                raise MkDocsImportError("Recovery copy changed; upload the archive again")
            target = self.content.root
            retired = target.parent / f".{target.name}.import-retired-{secrets.token_hex(8)}"
            try:
                os.replace(target, retired)
                os.replace(pending.staging_path, target)
                ManualBackupService._fsync_directory(target.parent)
                # Preserve only the app's optional backup transport. Do not run
                # bootstrap migrations here: an imported MkDocs source tree is
                # operator-owned and should not be silently rewritten.
                with self.content.git.remote_configuration_transaction():
                    self.content.git.configure_remote(
                        effective_target(self.content.settings).remote_config()
                    )
            except Exception as exc:
                if not target.exists() and retired.exists():
                    os.replace(retired, target)
                raise MkDocsImportError("MkDocs import could not be completed safely") from exc
            return ImportResult("imported_after_recovery", recovery_verified=True)

    def _extract_to_staging(self, data: bytes, actor: User) -> Path:
        parent = self.content.root.parent
        staging = Path(tempfile.mkdtemp(prefix=f".{self.content.root.name}.import-", dir=parent))
        try:
            with ZipFile(BytesIO(data)) as archive:
                members = [entry for entry in archive.infolist() if not entry.is_dir()]
                if not members or len(members) > MAX_ARCHIVE_FILES:
                    raise MkDocsImportError("Archive has an invalid number of files")
                normalized = [(entry, self._member_path(entry.filename)) for entry in members]
                root = self._archive_root([path for _entry, path in normalized])
                total = 0
                seen: set[PurePosixPath] = set()
                for entry, path in normalized:
                    if stat.S_ISLNK(entry.external_attr >> 16) or entry.file_size < 0:
                        raise MkDocsImportError("Archive links are not supported")
                    relative = path.relative_to(root) if root else path
                    if relative in seen:
                        raise MkDocsImportError("Archive contains duplicate files")
                    seen.add(relative)
                    total += entry.file_size
                    if total > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                        raise MkDocsImportError("Archive expands beyond the supported size")
                    destination = staging.joinpath(*relative.parts)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(entry) as source, destination.open("wb") as output:
                        shutil.copyfileobj(source, output)
            if not (staging / "mkdocs.yml").is_file() or not (staging / "docs").is_dir():
                raise MkDocsImportError("Archive must contain mkdocs.yml and a docs directory")
            repo = Repo.init(staging, initial_branch="main")
            files = [
                path.relative_to(staging).as_posix()
                for path in staging.rglob("*")
                if path.is_file()
            ]
            repo.index.add(files)
            name = actor.display_name or actor.username
            git_actor = Actor(name, actor.email)
            repo.index.commit("Import MkDocs archive", author=git_actor, committer=git_actor)
            ManualBackupService._fsync_tree(staging)
            return staging
        except (BadZipFile, OSError, ValueError) as exc:
            shutil.rmtree(staging, ignore_errors=True)
            raise MkDocsImportError("Archive is not a valid MkDocs ZIP") from exc
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def _recovery_copy(self) -> Path:
        target = self.content.root
        recovery = ManualBackupService._new_recovery_path(target)
        try:
            shutil.copytree(target, recovery, symlinks=True, copy_function=shutil.copy2)
            ManualBackupService._fsync_tree(recovery)
            if not secrets.compare_digest(self._tree_digest(target), self._tree_digest(recovery)):
                raise MkDocsImportError("Recovery copy verification failed")
            Repo(recovery).git.fsck("--no-dangling")
            return recovery
        except Exception as exc:
            raise MkDocsImportError("Unable to create a verified recovery copy") from exc

    @staticmethod
    def _member_path(name: str) -> PurePosixPath:
        if "\\" in name or "\x00" in name:
            raise MkDocsImportError("Archive contains an unsafe file name")
        path = PurePosixPath(name)
        if (
            path.is_absolute()
            or not path.parts
            or any(part in {"", ".", "..", ".git"} for part in path.parts)
        ):
            raise MkDocsImportError("Archive contains an unsafe file name")
        return path

    @staticmethod
    def _archive_root(paths: list[PurePosixPath]) -> PurePosixPath | None:
        first = {path.parts[0] for path in paths}
        return PurePosixPath("unstacked-mkdocs") if first == {"unstacked-mkdocs"} else None

    @staticmethod
    def _tree_digest(root: Path) -> str:
        return ManualBackupService._tree_digest(root)
