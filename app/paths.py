import os
import re
import stat
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from uuid import uuid4

from slugify import slugify

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RESERVED_ROOT_NAMES = {"assets"}
RESERVED_PART_NAMES = {".pages", ".git", "site"}
# Names Windows refuses regardless of extension.  The content repository is
# meant to be copied between machines, so a page that cannot be checked out on
# Windows is a portability bug even though the server runs on POSIX.
RESERVED_WINDOWS_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{digit}" for digit in range(1, 10)}
    | {f"lpt{digit}" for digit in range(1, 10)}
)


def _is_reserved(part: str) -> bool:
    stem = part.split(".", 1)[0].casefold()
    return part in RESERVED_PART_NAMES or stem in RESERVED_WINDOWS_NAMES


class UnsafePath(ValueError):
    pass


class ConfinedFileTooLarge(UnsafePath):
    """A confined regular file exceeds the caller's byte budget."""


def make_slug(title: str, requested: str | None = None) -> str:
    candidate = requested if requested is not None else slugify(title)
    candidate = unicodedata.normalize("NFKC", candidate).casefold()
    if len(candidate) > 100 or not SLUG_RE.fullmatch(candidate):
        raise UnsafePath("slug must contain only lowercase letters, numbers, and hyphens")
    if candidate in RESERVED_ROOT_NAMES or _is_reserved(candidate):
        raise UnsafePath("slug is reserved")
    return candidate


def normalize_relative_path(raw: str) -> str:
    if not raw or "\x00" in raw or "\\" in raw:
        raise UnsafePath("invalid path")
    candidate = unicodedata.normalize("NFKC", raw)
    # Require canonical form rather than silently repairing it, so one
    # resource never has several spellings that callers might compare.
    if candidate.startswith("/") or candidate.endswith("/") or "//" in candidate:
        raise UnsafePath("invalid path")
    if any(segment in {"", ".", ".."} for segment in candidate.split("/")):
        raise UnsafePath("invalid path")
    path = PurePosixPath(candidate)
    if path.is_absolute() or not path.parts:
        raise UnsafePath("invalid path")
    if any(part.startswith(".") or _is_reserved(part) for part in path.parts):
        raise UnsafePath("reserved path component")
    return path.as_posix()


def path_depth(relative: str) -> int:
    """Number of path segments in an already-normalized relative path."""

    return len(PurePosixPath(relative).parts)


def safe_join(root: Path, relative: str) -> Path:
    normalized = normalize_relative_path(relative)
    resolved_root = root.resolve()
    candidate = (resolved_root / normalized).resolve(strict=False)
    if os.path.commonpath((str(resolved_root), str(candidate))) != str(resolved_root):
        raise UnsafePath("path escapes the content root")
    return candidate


@contextmanager
def _confined_parent(root: Path, relative: str) -> Iterator[tuple[int, str]]:
    """Open ``relative``'s parent without following any path component.

    ``safe_join`` is useful for converting a validated content name into a
    ``Path``, but a ``Path`` cannot retain the directory inode it checked.  An
    untrusted local process could otherwise replace an ancestor with a symlink
    between that check and a later ``open``.  Hold descriptor-relative handles
    while doing the actual I/O instead.  This is deliberately POSIX-only: the
    application does not support Windows as a server platform, while its
    content names remain portable to Windows.
    """

    normalized = normalize_relative_path(relative)
    parts = PurePosixPath(normalized).parts
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    root_fd = os.open(root, directory_flags)
    current_fd = root_fd
    try:
        for part in parts[:-1]:
            try:
                next_fd = os.open(part, directory_flags, dir_fd=current_fd)
            except OSError as exc:
                raise UnsafePath("path contains an unsafe or missing directory") from exc
            os.close(current_fd)
            current_fd = next_fd
        yield current_fd, parts[-1]
    finally:
        os.close(current_fd)


def is_confined_directory(root: Path, relative: str) -> bool:
    """Return whether an existing directory can be reached without symlinks."""

    try:
        with _confined_parent(root, relative) as (parent_fd, leaf):
            descriptor = os.open(
                leaf, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd
            )
    except (OSError, UnsafePath):
        return False
    os.close(descriptor)
    return True


def read_confined_text(root: Path, relative: str, *, max_bytes: int | None = None) -> str:
    """Read one regular UTF-8 file without a symlink check-then-open race."""

    try:
        with _confined_parent(root, relative) as (parent_fd, leaf):
            descriptor = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
    except (OSError, UnsafePath) as exc:
        raise UnsafePath("path is missing or unsafe") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise UnsafePath("path is not a regular file")
        limit = max_bytes + 1 if max_bytes is not None else -1
        chunks: list[bytes] = []
        remaining = limit
        while remaining != 0:
            chunk = os.read(descriptor, 65_536 if remaining < 0 else min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            if remaining > 0:
                remaining -= len(chunk)
        content = b"".join(chunks)
        if max_bytes is not None and len(content) > max_bytes:
            raise ConfinedFileTooLarge("file exceeds configured size limit")
        return content.decode("utf-8")
    finally:
        os.close(descriptor)


def atomic_write_confined(
    root: Path,
    relative: str,
    text: str,
    *,
    overwrite: bool,
) -> None:
    """Atomically write a regular file beneath ``root`` without symlink races.

    ``overwrite=False`` uses a hard-link publication rather than a preliminary
    ``exists`` check, so a concurrent creator cannot be clobbered.  Replacing
    an existing final symlink is safe: ``replace`` changes the link itself and
    never follows it.  Parent directories are held by descriptor throughout.
    """

    encoded = text.encode("utf-8")
    temporary = f".{uuid4().hex}.unstacked-tmp"
    try:
        with _confined_parent(root, relative) as (parent_fd, leaf):
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                stat.S_IRUSR | stat.S_IWUSR,
                dir_fd=parent_fd,
            )
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                if overwrite:
                    os.replace(temporary, leaf, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                else:
                    # link(2) publishes only if ``leaf`` does not already
                    # exist; unlike replace(2), this cannot clobber a raced
                    # concurrent creation.
                    os.link(temporary, leaf, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                    os.unlink(temporary, dir_fd=parent_fd)
                os.fsync(parent_fd)
            except Exception:
                try:
                    os.unlink(temporary, dir_fd=parent_fd)
                except FileNotFoundError:
                    pass
                raise
    except (UnsafePath, FileExistsError):
        raise
    except OSError as exc:
        raise UnsafePath("path is missing or unsafe") from exc
