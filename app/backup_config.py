"""Runtime-editable persistence for the optional content backup target.

An off-site backup is optional and pluggable: local disk is the complete,
durable state, so every function here has to behave sensibly when nothing is
configured at all -- that is the default and fully supported state.

Three decisions are deliberate:

* **A file under ``data/``, not a table.**  This follows the same precedent as
  ``api_token_secret_path`` in :mod:`app.config`: a small operator-owned record
  with owner-only permissions.  The database keeps exactly four tables, and a
  backup target is deployment configuration rather than wiki data.
* **The record is target-typed.**  ``type`` is ``"git-remote"`` today and
  ``"none"`` once an administrator clears it.  An rsync or S3 target later is
  another value of the same field with its own fields alongside, not a
  redesign of the file.
* **No credential value is ever written here.**  The record holds *paths* --
  a token file, a deploy key, a pinned ``known_hosts`` -- which is the same
  shape :class:`~app.git_backend.RemoteConfig` prefers, and which is what lets
  the generated credential helper read the secret at the moment git asks for
  it.  An inline token supplied through the admin API is written to its own
  owner-only file (:func:`managed_token_path`) and only that path is recorded.
  :func:`_record` builds the JSON from an explicit key list, so a credential
  cannot reach the file by someone later adding a field.

**Precedence.**  The persisted file wins whenever it exists; the environment
settings are the *initial* value used until an administrator saves one.  That
mirrors ``api_token_secret``, where an explicit environment value is used and a
generated file otherwise, except in the opposite direction: here the runtime
record is the primary path going forward and the environment is the bootstrap.
A file that cannot be parsed is ignored (with a warning) rather than crashing
the app, and the environment fallback applies -- an unreadable optional backup
record must never be able to stop the wiki from serving content.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings
from app.git_backend import RemoteConfig

logger = logging.getLogger("unstacked.backup")

# Bumped only if the on-disk shape changes incompatibly.  An unknown version is
# treated like an unparsable file: ignored, never guessed at.
RECORD_VERSION = 1

GIT_REMOTE = "git-remote"
NO_TARGET = "none"

# Filename of the app-managed token file, kept beside the config record so one
# setting locates both.
MANAGED_TOKEN_FILENAME = "backup_token"

# Owner-only, as with every other secret this application writes.
_PRIVATE_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR

_SOURCE_FILE = "file"
_SOURCE_ENVIRONMENT = "environment"
_SOURCE_UNSET = "unset"


@dataclass(frozen=True)
class BackupTarget:
    """The effective backup target, whatever its source.

    ``token`` exists only because the environment supports an inline value
    (``UNSTACKED_GITHUB_TOKEN``); it is excluded from ``repr`` and is never
    serialized -- :func:`_record` enumerates the persisted keys explicitly.
    """

    type: str = NO_TARGET
    url: str | None = None
    confirmed_private: bool = False
    token_path: Path | None = None
    ssh_key_path: Path | None = None
    ssh_known_hosts_path: Path | None = None
    updated_at: str | None = None
    source: str = _SOURCE_UNSET
    token: str | None = field(default=None, repr=False, compare=False)

    @property
    def configured(self) -> bool:
        return self.type == GIT_REMOTE and bool(self.url)

    @property
    def credential(self) -> str:
        """Which *kind* of credential is configured; never the value itself."""

        if not self.configured:
            return "none"
        if self.token_path is not None or self.token:
            return "token_file" if self.token_path is not None else "token_value"
        if self.ssh_key_path is not None:
            return "ssh_key"
        return "none"

    def remote_config(self) -> RemoteConfig:
        """Describe this target the way :meth:`GitBackend.configure_remote` reads it.

        An unconfigured target yields a ``RemoteConfig`` with no URL, which
        ``configure_remote`` treats as "no backup" and skips entirely.
        """

        if not self.configured:
            return RemoteConfig()
        return RemoteConfig(
            url=self.url,
            confirmed_private=self.confirmed_private,
            token=self.token,
            token_path=self.token_path,
            ssh_key_path=self.ssh_key_path,
            ssh_known_hosts_path=self.ssh_known_hosts_path,
        )


def managed_token_path(settings: Settings) -> Path:
    """Where an inline token supplied through the admin API is stored.

    Beside the configuration record, so one setting places both and neither
    can end up inside ``content/`` (which is exported and backed up in full).
    """

    return settings.backup_config_path.parent / MANAGED_TOKEN_FILENAME


def target_from_settings(settings: Settings) -> BackupTarget:
    """The environment-provided target: the initial value before any save."""

    if not settings.github_remote_url:
        return BackupTarget(source=_SOURCE_UNSET)
    return BackupTarget(
        type=GIT_REMOTE,
        url=settings.github_remote_url,
        confirmed_private=settings.github_remote_confirmed_private,
        token=settings.github_token,
        token_path=settings.github_token_path,
        ssh_key_path=settings.github_ssh_key_path,
        ssh_known_hosts_path=settings.github_ssh_known_hosts_path,
        source=_SOURCE_ENVIRONMENT,
    )


def load(path: Path) -> BackupTarget | None:
    """Read the persisted record, or ``None`` when there is not a usable one.

    A missing file is the ordinary case.  A malformed or unreadable one is
    reported and then treated the same way: the backup target is optional, so
    a bad record degrades to "not configured from a file" instead of taking
    the application down with it.
    """

    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        logger.warning("backup configuration at %s could not be read; ignoring it", path)
        return None
    try:
        record = json.loads(raw)
    except ValueError:
        logger.warning("backup configuration at %s is not valid JSON; ignoring it", path)
        return None
    if not isinstance(record, dict) or record.get("version") != RECORD_VERSION:
        logger.warning("backup configuration at %s has an unknown shape; ignoring it", path)
        return None
    kind = record.get("type")
    if kind not in (GIT_REMOTE, NO_TARGET):
        logger.warning("backup configuration at %s names an unknown target type", path)
        return None
    if kind == NO_TARGET:
        # An administrator cleared the target.  This is a real record, not an
        # absent one: it has to outrank the environment, or a stale variable
        # would silently re-enable a backup that was deliberately switched off.
        return BackupTarget(source=_SOURCE_FILE, updated_at=_text(record.get("updated_at")))
    url = _text(record.get("url"))
    if not url:
        logger.warning("backup configuration at %s has no target URL; ignoring it", path)
        return None
    return BackupTarget(
        type=GIT_REMOTE,
        url=url,
        confirmed_private=bool(record.get("confirmed_private")),
        token_path=_path(record.get("token_path")),
        ssh_key_path=_path(record.get("ssh_key_path")),
        ssh_known_hosts_path=_path(record.get("ssh_known_hosts_path")),
        updated_at=_text(record.get("updated_at")),
        source=_SOURCE_FILE,
    )


def effective_target(settings: Settings) -> BackupTarget:
    """The target actually in force: the persisted record, else the environment."""

    stored = load(settings.backup_config_path)
    return stored if stored is not None else target_from_settings(settings)


def save(path: Path, target: BackupTarget) -> BackupTarget:
    """Persist ``target`` atomically with owner-only permissions.

    Returns the stored record (stamped with its write time) so a caller can
    report exactly what is now on disk.
    """

    stamped = BackupTarget(
        type=target.type,
        url=target.url,
        confirmed_private=target.confirmed_private,
        token_path=target.token_path,
        ssh_key_path=target.ssh_key_path,
        ssh_known_hosts_path=target.ssh_known_hosts_path,
        updated_at=target.updated_at or datetime.now(timezone.utc).isoformat(),
        source=_SOURCE_FILE,
    )
    write_private_bytes(path, json.dumps(_record(stamped), indent=2).encode("utf-8") + b"\n")
    return stamped


def clear(path: Path) -> BackupTarget:
    """Record that no backup target is configured, and return that record.

    A tombstone rather than a deleted file: the record's whole job is to
    outrank the environment, and an administrator who clears the target must
    not have it come back at the next restart because a variable was left set
    in the deployment.  Deleting ``data/backup_config.json`` by hand is how an
    operator hands control back to the environment.
    """

    return save(path, BackupTarget(type=NO_TARGET))


def write_managed_token(path: Path, token: str) -> None:
    """Store an admin-supplied inline token in its own owner-only file.

    Keeping the secret in a file rather than in the JSON record is what makes
    "never rendered back" structural: the record holds a path, the credential
    helper reads the file at the moment git asks for it, and nothing that
    serializes the configuration can reach the value.
    """

    write_private_bytes(path, token.encode("utf-8"))


def forget_managed_token(path: Path) -> None:
    """Remove the app-managed token file; never an operator's own token file."""

    path.unlink(missing_ok=True)


def write_private_bytes(path: Path, content: bytes) -> None:
    """Atomically write ``content`` with owner-only permissions.

    Same shape as ``GitBackend._atomic_write_bytes`` and ``_write_private_file``:
    write a temporary sibling, fsync, then rename, so a crash leaves either the
    previous record or the new one and never a truncated file.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, _PRIVATE_FILE_MODE)
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


class FileSnapshot:
    """Remember exactly what a set of files held, so a failure can undo itself.

    The same idea as ``app.content._Rollback``, kept separate because this
    module must not import the content layer (the content layer imports this
    one).  Saving a backup configuration touches two files and one git
    configuration; if any part of it fails, the previous working configuration
    -- or the absence of one -- has to remain in effect rather than a half of
    each.
    """

    def __init__(self, *paths: Path) -> None:
        self._files: dict[Path, bytes | None] = {
            path: (path.read_bytes() if path.is_file() else None) for path in paths
        }

    def undo(self) -> None:
        for path, original in self._files.items():
            if original is None:
                path.unlink(missing_ok=True)
            else:
                write_private_bytes(path, original)


def _record(target: BackupTarget) -> dict[str, object]:
    """The JSON body, built from an explicit key list.

    Enumerating the keys is the point: a credential value added to
    :class:`BackupTarget` later cannot reach the file by accident.
    """

    return {
        "version": RECORD_VERSION,
        "type": target.type,
        "url": target.url,
        "confirmed_private": target.confirmed_private,
        "token_path": _as_text(target.token_path),
        "ssh_key_path": _as_text(target.ssh_key_path),
        "ssh_known_hosts_path": _as_text(target.ssh_known_hosts_path),
        "updated_at": target.updated_at,
    }


def _text(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _path(value: object) -> Path | None:
    text = _text(value)
    return Path(text) if text else None


def _as_text(value: Path | None) -> str | None:
    return str(value) if value is not None else None
