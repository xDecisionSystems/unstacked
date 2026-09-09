"""Portable workspace archives and their optional SSH-server destination.

Git synchronisation and disaster-recovery archives solve different problems.
The former preserves a content repository's normal collaborative history; this
module produces a private ZIP that can rebuild an Unstacked workspace on a new
server.  It contains the complete MkDocs source tree plus the four permitted
database tables and presentation settings, but never transport credentials,
SMTP passwords, API signing secrets, or browser sessions.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from git import Actor, Repo
from sqlalchemy import delete
from sqlmodel import Session, select

from app import branding
from app.backup_config import SshHostKey, discover_ssh_host_key, write_private_bytes
from app.config import Settings
from app.content import ContentRepository
from app.mkdocs_import import MAX_ARCHIVE_FILES, MAX_ARCHIVE_UNCOMPRESSED_BYTES
from app.models import Group, Permission, User, UserGroup

ARCHIVE_ROOT = PurePosixPath("unstacked-workspace")
ARCHIVE_VERSION = 1
RECORD_VERSION = 1
MANAGED_KNOWN_HOSTS_FILENAME = "ssh_archive_known_hosts"
_PRIVATE_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR
_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")
_USER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")


class WorkspaceArchiveError(RuntimeError):
    """A safe-to-display archive or transport failure."""


@dataclass(frozen=True)
class SshArchiveTarget:
    host: str = ""
    username: str = ""
    remote_path: str = ""
    ssh_key_path: Path | None = None
    port: int = 22
    known_hosts_path: Path | None = None
    fingerprint: str | None = None
    schedules: tuple[str, ...] = ()
    updated_at: str | None = None

    @property
    def configured(self) -> bool:
        return bool(
            self.host
            and self.username
            and self.remote_path
            and self.ssh_key_path
            and self.known_hosts_path
            and self.fingerprint
        )


@dataclass(frozen=True)
class PendingRestore:
    staging: Path
    state: dict[str, object]
    digest: str
    actor: User


def managed_known_hosts_path(settings: Settings) -> Path:
    return settings.ssh_archive_config_path.parent / MANAGED_KNOWN_HOSTS_FILENAME


def load_target(path: Path) -> SshArchiveTarget:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return SshArchiveTarget()
    if not isinstance(raw, dict) or raw.get("version") != RECORD_VERSION:
        return SshArchiveTarget()
    schedules = raw.get("schedules", [])
    if not isinstance(schedules, list) or any(
        item not in {"hourly", "daily", "weekly"} for item in schedules
    ):
        schedules = []
    key = raw.get("ssh_key_path")
    known = raw.get("known_hosts_path")
    return SshArchiveTarget(
        host=_text(raw.get("host")),
        username=_text(raw.get("username")),
        remote_path=_text(raw.get("remote_path")),
        ssh_key_path=Path(key) if isinstance(key, str) and key.strip() else None,
        port=raw.get("port") if isinstance(raw.get("port"), int) else 22,
        known_hosts_path=Path(known) if isinstance(known, str) and known.strip() else None,
        fingerprint=_text(raw.get("fingerprint")) or None,
        schedules=tuple(schedules),
        updated_at=_text(raw.get("updated_at")) or None,
    )


def discover_target_host_key(host: str, port: int) -> SshHostKey:
    _validate_host(host)
    if not 1 <= port <= 65535:
        raise ValueError("SSH port must be between 1 and 65535")
    found = discover_ssh_host_key(f"ssh://archive@{host}:{port}/")
    if found is None:  # Defensive: a syntactically valid URL always yields a scan.
        raise ValueError("could not retrieve the SSH server fingerprint")
    return found


def save_target(
    settings: Settings, target: SshArchiveTarget, host_key: SshHostKey
) -> SshArchiveTarget:
    _validate_target(target)
    if host_key.fingerprint != target.fingerprint:
        raise ValueError("SSH server fingerprint must be checked and confirmed before saving")
    assert target.ssh_key_path is not None
    if not target.ssh_key_path.is_file():
        raise ValueError("SSH private-key file does not exist")
    known_hosts = managed_known_hosts_path(settings)
    write_private_bytes(known_hosts, host_key.known_hosts_line.encode("utf-8"))
    stored = SshArchiveTarget(
        host=target.host.strip(),
        username=target.username.strip(),
        remote_path=target.remote_path.strip(),
        ssh_key_path=target.ssh_key_path,
        port=target.port,
        known_hosts_path=known_hosts,
        fingerprint=target.fingerprint,
        schedules=target.schedules,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    record = {
        "version": RECORD_VERSION,
        "host": stored.host,
        "username": stored.username,
        "remote_path": stored.remote_path,
        "ssh_key_path": str(stored.ssh_key_path),
        "port": stored.port,
        "known_hosts_path": str(stored.known_hosts_path),
        "fingerprint": stored.fingerprint,
        "schedules": list(stored.schedules),
        "updated_at": stored.updated_at,
    }
    write_private_bytes(
        settings.ssh_archive_config_path, json.dumps(record, indent=2).encode() + b"\n"
    )
    return stored


def _validate_target(target: SshArchiveTarget) -> None:
    _validate_host(target.host)
    if not _USER.fullmatch(target.username.strip()):
        raise ValueError("SSH username contains unsupported characters")
    path = target.remote_path.strip()
    if not path.startswith("/") or "\x00" in path or any(ch.isspace() for ch in path):
        raise ValueError("remote folder must be an absolute path without spaces")
    if not 1 <= target.port <= 65535:
        raise ValueError("SSH port must be between 1 and 65535")
    if not target.ssh_key_path:
        raise ValueError("SSH private-key path is required")
    if not target.fingerprint:
        raise ValueError("SSH server fingerprint must be checked and confirmed")
    if any(schedule not in {"hourly", "daily", "weekly"} for schedule in target.schedules):
        raise ValueError("backup schedule is invalid")


def _validate_host(host: str) -> None:
    value = host.strip()
    if not _HOST.fullmatch(value) or ".." in value or value.startswith(".") or value.endswith("."):
        raise ValueError("SSH host contains unsupported characters")


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


class WorkspaceArchiveService:
    """Create, upload, stage, and restore versioned workspace archives."""

    def __init__(self, settings: Settings, content: ContentRepository, engine) -> None:
        self.settings = settings
        self.content = content
        self.engine = engine
        self._pending: dict[str, PendingRestore] = {}

    def filename(self) -> str:
        name = branding.load(self.settings.branding_config_path).name
        compact = re.sub(r"[^A-Za-z0-9_-]+", "", name) or "workspace"
        return f"keybadger_{compact}{datetime.now().strftime('%d%m%Y-%H%M')}.zip"

    def package(self) -> bytes:
        """Create a self-contained ZIP while holding the content mutation lock."""

        with self.content.git.lock:
            output = BytesIO()
            with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
                state = self._state()
                archive.writestr(
                    f"{ARCHIVE_ROOT}/manifest.json",
                    json.dumps(
                        {
                            "format": "unstacked-workspace",
                            "version": ARCHIVE_VERSION,
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        },
                        indent=2,
                    ),
                )
                archive.writestr(f"{ARCHIVE_ROOT}/state.json", json.dumps(state, indent=2))
                self._write_content(archive)
                logo = self.settings.branding_config_path.with_name("branding-logo")
                if logo.is_file() and not logo.is_symlink():
                    archive.write(logo, f"{ARCHIVE_ROOT}/branding-logo")
            return output.getvalue()

    def upload(self) -> str:
        target = load_target(self.settings.ssh_archive_config_path)
        if not target.configured:
            raise WorkspaceArchiveError("No SSH archive destination is configured")
        assert target.ssh_key_path and target.known_hosts_path
        if not target.ssh_key_path.is_file() or not target.known_hosts_path.is_file():
            raise WorkspaceArchiveError("SSH archive credentials are unavailable")
        archive = self.package()
        filename = self.filename()
        with tempfile.TemporaryDirectory(
            dir=self.settings.ssh_archive_config_path.parent, prefix=".ssh-archive-"
        ) as temporary:
            local = Path(temporary) / filename
            local.write_bytes(archive)
            os.chmod(local, _PRIVATE_FILE_MODE)
            remote = f"{target.username}@{target.host}:{target.remote_path.rstrip('/')}/{filename}"
            command = [
                "scp",
                "-q",
                "-i",
                str(target.ssh_key_path),
                "-oBatchMode=yes",
                "-oStrictHostKeyChecking=yes",
                f"-oUserKnownHostsFile={target.known_hosts_path}",
                "-P",
                str(target.port),
                str(local),
                remote,
            ]
            try:
                result = subprocess.run(
                    command,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise WorkspaceArchiveError("SSH archive upload could not be started") from exc
            if result.returncode:
                raise WorkspaceArchiveError(
                    "SSH archive upload failed; check the server folder, key, and fingerprint"
                )
        return filename

    def prepare_restore(self, data: bytes, actor: User) -> str:
        if not data:
            raise WorkspaceArchiveError("Choose an Unstacked workspace ZIP file")
        with self.content.git.write_lock():
            staging, state = self._extract(data, actor)
            token = secrets.token_urlsafe(32)
            self._pending[token] = PendingRestore(staging, state, self._tree_digest(staging), actor)
            return token

    def confirm_restore(self, token: str) -> None:
        with self.content.git.write_lock():
            pending = self._pending.pop(token, None)
            if pending is None or not secrets.compare_digest(
                self._tree_digest(pending.staging), pending.digest
            ):
                raise WorkspaceArchiveError(
                    "Archive restore confirmation is invalid or has expired"
                )
            recovery = self._recovery()
            old_root = self.content.root
            retired = old_root.parent / f".{old_root.name}.workspace-retired-{secrets.token_hex(8)}"
            try:
                os.replace(old_root, retired)
                os.replace(pending.staging, old_root)
                self._restore_state(pending.state)
            except Exception as exc:
                if not old_root.exists() and retired.exists():
                    os.replace(retired, old_root)
                self._restore_recovery_state(recovery)
                raise WorkspaceArchiveError(
                    "Workspace archive could not be restored safely"
                ) from exc

    def _state(self) -> dict[str, object]:
        with Session(self.engine) as session:
            return {
                "users": [self._row(user) for user in session.exec(select(User)).all()],
                "groups": [self._row(group) for group in session.exec(select(Group)).all()],
                "user_groups": [self._row(row) for row in session.exec(select(UserGroup)).all()],
                "permissions": [self._row(row) for row in session.exec(select(Permission)).all()],
                "appearance": {
                    "branding": self._json_file(self.settings.branding_config_path),
                    "theme": self._json_file(self.settings.theme_config_path),
                },
            }

    @staticmethod
    def _row(item) -> dict[str, object]:
        return {key: value for key, value in item.model_dump().items()}

    @staticmethod
    def _json_file(path: Path) -> dict[str, object] | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    def _write_content(self, archive: ZipFile) -> None:
        root = self.content.root
        if not root.is_dir() or root.is_symlink():
            raise WorkspaceArchiveError("Workspace content is unavailable")
        for current, directories, files in os.walk(root, followlinks=False):
            current_path = Path(current)
            directories[:] = [
                name
                for name in directories
                if name != ".git" and not (current_path / name).is_symlink()
            ]
            for name in files:
                source = current_path / name
                if source.is_file() and not source.is_symlink():
                    archive.write(
                        source, (ARCHIVE_ROOT / "content" / source.relative_to(root)).as_posix()
                    )

    def _extract(self, data: bytes, actor: User) -> tuple[Path, dict[str, object]]:
        parent = self.content.root.parent
        staging = Path(tempfile.mkdtemp(prefix=f".{self.content.root.name}.workspace-", dir=parent))
        try:
            with ZipFile(BytesIO(data)) as archive:
                entries = [entry for entry in archive.infolist() if not entry.is_dir()]
                if not entries or len(entries) > MAX_ARCHIVE_FILES:
                    raise WorkspaceArchiveError("Archive has an invalid number of files")
                total = 0
                state: dict[str, object] | None = None
                manifest: dict[str, object] | None = None
                seen: set[PurePosixPath] = set()
                for entry in entries:
                    path = self._member_path(entry.filename)
                    if (
                        stat.S_ISLNK(entry.external_attr >> 16)
                        or entry.file_size < 0
                        or path in seen
                    ):
                        raise WorkspaceArchiveError("Archive contains an unsafe file")
                    seen.add(path)
                    total += entry.file_size
                    if total > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                        raise WorkspaceArchiveError("Archive expands beyond the supported size")
                    if path == ARCHIVE_ROOT / "manifest.json":
                        manifest = json.loads(archive.read(entry))
                    elif path == ARCHIVE_ROOT / "state.json":
                        state = json.loads(archive.read(entry))
                    elif (
                        path.parts[:2] == (ARCHIVE_ROOT.parts[0], "content") and len(path.parts) > 2
                    ):
                        destination = staging.joinpath(*path.parts[2:])
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(entry) as source, destination.open("wb") as output:
                            shutil.copyfileobj(source, output)
                    elif path == ARCHIVE_ROOT / "branding-logo":
                        with archive.open(entry) as source:
                            (staging / ".branding-logo").write_bytes(source.read())
                    else:
                        raise WorkspaceArchiveError("Archive contains an unsupported file")
            if (
                not isinstance(manifest, dict)
                or manifest.get("format") != "unstacked-workspace"
                or manifest.get("version") != ARCHIVE_VERSION
            ):
                raise WorkspaceArchiveError("ZIP is not an Unstacked workspace archive")
            if (
                not isinstance(state, dict)
                or not (staging / "mkdocs.yml").is_file()
                or not (staging / "docs").is_dir()
            ):
                raise WorkspaceArchiveError("Archive is missing workspace data")
            self._validate_state(state)
            logo = staging / ".branding-logo"
            if logo.exists():
                staged_logo = self.settings.branding_config_path.with_name(
                    f".{secrets.token_hex(8)}.branding-logo"
                )
                logo.replace(staged_logo)
                state["branding_logo_staged"] = str(staged_logo)
            repo = Repo.init(staging, initial_branch="main")
            files = [
                path.relative_to(staging).as_posix()
                for path in staging.rglob("*")
                if path.is_file()
            ]
            git_actor = Actor(actor.display_name or actor.username, actor.email)
            repo.index.add(files)
            repo.index.commit(
                "Restore Unstacked workspace archive", author=git_actor, committer=git_actor
            )
            return staging, state
        except (BadZipFile, OSError, ValueError, json.JSONDecodeError) as exc:
            shutil.rmtree(staging, ignore_errors=True)
            if isinstance(exc, WorkspaceArchiveError):
                raise
            raise WorkspaceArchiveError("Archive is not a valid Unstacked workspace ZIP") from exc
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    @staticmethod
    def _member_path(name: str) -> PurePosixPath:
        path = PurePosixPath(name)
        if (
            "\\" in name
            or "\x00" in name
            or path.is_absolute()
            or not path.parts
            or any(part in {"", ".", "..", ".git"} for part in path.parts)
        ):
            raise WorkspaceArchiveError("Archive contains an unsafe file name")
        return path

    @staticmethod
    def _validate_state(state: dict[str, object]) -> None:
        for key in ("users", "groups", "user_groups", "permissions"):
            if not isinstance(state.get(key), list):
                raise WorkspaceArchiveError("Archive has invalid permission data")

    def _restore_state(self, state: dict[str, object]) -> None:
        with Session(self.engine) as session:
            session.exec(delete(UserGroup))
            session.exec(delete(Permission))
            session.exec(delete(Group))
            session.exec(delete(User))
            for row in state["users"]:
                # The archive intentionally has no signing secret.  A restore
                # also revokes browser/API credentials issued before it, so a
                # stale cookie from the replaced workspace cannot survive.
                restored = dict(row)
                restored["session_generation"] = int(restored.get("session_generation", 0)) + 1
                restored["api_token_generation"] = int(restored.get("api_token_generation", 0)) + 1
                session.add(User(**restored))
            for row in state["groups"]:
                session.add(Group(**row))
            for row in state["user_groups"]:
                session.add(UserGroup(**row))
            for row in state["permissions"]:
                session.add(Permission(**row))
            session.commit()
        appearance = state.get("appearance", {})
        if not isinstance(appearance, dict):
            raise WorkspaceArchiveError("Archive has invalid appearance data")
        self._restore_json(self.settings.branding_config_path, appearance.get("branding"))
        self._restore_json(self.settings.theme_config_path, appearance.get("theme"))
        staged_logo = state.get("branding_logo_staged")
        logo = self.settings.branding_config_path.with_name("branding-logo")
        if isinstance(staged_logo, str) and Path(staged_logo).is_file():
            os.replace(staged_logo, logo)
        elif logo.exists():
            logo.unlink()

    @staticmethod
    def _restore_json(path: Path, value: object) -> None:
        if value is None:
            path.unlink(missing_ok=True)
        elif isinstance(value, dict):
            write_private_bytes(path, json.dumps(value, indent=2).encode() + b"\n")
        else:
            raise WorkspaceArchiveError("Archive has invalid settings data")

    def _recovery(self) -> Path:
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        name = f".workspace-recovery-{stamp}-{secrets.token_hex(4)}"
        root = self.content.root.parent / name
        root.mkdir()
        shutil.copytree(self.content.root, root / "content", symlinks=True)
        (root / "state.json").write_text(json.dumps(self._state()), encoding="utf-8")
        for path in (
            self.settings.branding_config_path,
            self.settings.theme_config_path,
            self.settings.branding_config_path.with_name("branding-logo"),
        ):
            if path.is_file():
                shutil.copy2(path, root / path.name)
        return root

    def _restore_recovery_state(self, recovery: Path) -> None:
        try:
            self._restore_state(json.loads((recovery / "state.json").read_text(encoding="utf-8")))
            saved_logo = recovery / "branding-logo"
            logo = self.settings.branding_config_path.with_name("branding-logo")
            if saved_logo.is_file():
                shutil.copy2(saved_logo, logo)
        except Exception:
            pass

    @staticmethod
    def _tree_digest(root: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
        return digest.hexdigest()
