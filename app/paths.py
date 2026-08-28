import ctypes
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


def read_confined_bytes(root: Path, relative: str, *, max_bytes: int | None = None) -> bytes:
    """Read one regular file without a symlink check-then-open race.

    The budget is enforced while reading rather than by stat-then-read: the
    size a stat reports is not the size a later read returns, and for uploads
    the byte count is the one thing an attacker fully controls.  Reading one
    byte past the budget is enough to know the file is over it, so an
    oversized file is never fully materialized.
    """

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
        return content
    finally:
        os.close(descriptor)


def read_confined_text(root: Path, relative: str, *, max_bytes: int | None = None) -> str:
    """Read one regular UTF-8 file without a symlink check-then-open race."""

    return read_confined_bytes(root, relative, max_bytes=max_bytes).decode("utf-8")


def atomic_write_confined_bytes(
    root: Path,
    relative: str,
    content: bytes,
    *,
    overwrite: bool,
) -> None:
    """Atomically write a regular file beneath ``root`` without symlink races.

    ``overwrite=False`` uses a hard-link publication rather than a preliminary
    ``exists`` check, so a concurrent creator cannot be clobbered.  Replacing
    an existing final symlink is safe: ``replace`` changes the link itself and
    never follows it.  Parent directories are held by descriptor throughout.
    """

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
                    handle.write(content)
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


def atomic_write_confined(
    root: Path,
    relative: str,
    text: str,
    *,
    overwrite: bool,
) -> None:
    """Atomically write a regular UTF-8 file beneath ``root``."""

    atomic_write_confined_bytes(root, relative, text.encode("utf-8"), overwrite=overwrite)


def unlink_confined(root: Path, relative: str) -> None:
    """Remove one regular file beneath ``root`` without following a symlink.

    Deleting through a ``Path`` would resolve every ancestor first, so an
    untrusted local process could swap a directory for a symlink between the
    check and the unlink and have the deletion land outside the content root.
    """

    try:
        with _confined_parent(root, relative) as (parent_fd, leaf):
            os.unlink(leaf, dir_fd=parent_fd)
    except (OSError, UnsafePath) as exc:
        raise UnsafePath("path is missing or unsafe") from exc


def _rename_no_replace(
    source_parent_fd: int,
    source_leaf: str,
    destination_parent_fd: int,
    destination_leaf: str,
) -> None:
    """Atomically rename only when ``destination_leaf`` does not exist.

    POSIX ``rename`` overwrites its destination, which is unsuitable for the
    create-style content operations that use this primitive.  Linux provides
    ``renameat2(..., RENAME_NOREPLACE)`` and Darwin provides the equivalent
    descriptor-relative ``renameatx_np(..., RENAME_EXCL)``.  Do not replace
    this with an exists-then-rename fallback: that reintroduces the race this
    module exists to avoid.
    """

    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is not None:
        result = renameat2(
            source_parent_fd,
            os.fsencode(source_leaf),
            destination_parent_fd,
            os.fsencode(destination_leaf),
            1,  # RENAME_NOREPLACE
        )
    else:
        renameatx_np = getattr(libc, "renameatx_np", None)
        if renameatx_np is None:
            raise UnsafePath("atomic no-clobber rename is unavailable on this platform")
        result = renameatx_np(
            source_parent_fd,
            os.fsencode(source_leaf),
            destination_parent_fd,
            os.fsencode(destination_leaf),
            0x0004,  # RENAME_EXCL
        )
    if result != 0:
        error = ctypes.get_errno()
        if error == 17:  # EEXIST; avoiding a platform-specific errno import is intentional.
            raise FileExistsError(destination_leaf)
        raise OSError(error, os.strerror(error))


class ConfinedTree:
    """Descriptor-rooted, symlink-intolerant operations below one directory.

    This is the mutation-facing counterpart to :func:`safe_join`.  A normal
    ``Path`` captures a spelling, not the directory inode it was checked
    against; every method here instead opens ancestors with ``O_NOFOLLOW`` and
    performs the final operation through those descriptors.  It deliberately
    accepts only the canonical relative names enforced by
    :func:`normalize_relative_path`.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    @contextmanager
    def _directory(self, relative: str | None = None) -> Iterator[int]:
        """Yield an existing directory descriptor, never following a link."""

        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        try:
            current_fd = os.open(self.root, flags)
        except OSError as exc:
            raise UnsafePath("confined root is missing or unsafe") from exc
        try:
            if relative is not None:
                for part in PurePosixPath(normalize_relative_path(relative)).parts:
                    try:
                        next_fd = os.open(part, flags, dir_fd=current_fd)
                    except OSError as exc:
                        raise UnsafePath("path contains an unsafe or missing directory") from exc
                    os.close(current_fd)
                    current_fd = next_fd
            yield current_fd
        finally:
            os.close(current_fd)

    def read_bytes(self, relative: str, *, max_bytes: int | None = None) -> bytes:
        return read_confined_bytes(self.root, relative, max_bytes=max_bytes)

    def read_text(self, relative: str, *, max_bytes: int | None = None) -> str:
        return read_confined_text(self.root, relative, max_bytes=max_bytes)

    def write_bytes(self, relative: str, content: bytes, *, overwrite: bool = False) -> None:
        atomic_write_confined_bytes(self.root, relative, content, overwrite=overwrite)

    def write_text(self, relative: str, content: str, *, overwrite: bool = False) -> None:
        atomic_write_confined(self.root, relative, content, overwrite=overwrite)

    def unlink(self, relative: str) -> None:
        """Remove a regular file; a final symlink is rejected, not followed."""

        try:
            with _confined_parent(self.root, relative) as (parent_fd, leaf):
                info = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode):
                    raise UnsafePath("path is not a regular file")
                os.unlink(leaf, dir_fd=parent_fd)
                os.fsync(parent_fd)
        except (OSError, UnsafePath) as exc:
            if isinstance(exc, UnsafePath):
                raise
            raise UnsafePath("path is missing or unsafe") from exc

    def mkdir(self, relative: str, *, parents: bool = False, exist_ok: bool = False) -> None:
        """Create a directory without following any existing ancestor link."""

        parts = PurePosixPath(normalize_relative_path(relative)).parts
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        try:
            current_fd = os.open(self.root, flags)
            try:
                for index, part in enumerate(parts):
                    final = index == len(parts) - 1
                    try:
                        next_fd = os.open(part, flags, dir_fd=current_fd)
                    except FileNotFoundError:
                        if not parents and not final:
                            raise UnsafePath("parent directory is missing")
                        os.mkdir(part, 0o755, dir_fd=current_fd)
                        next_fd = os.open(part, flags, dir_fd=current_fd)
                    else:
                        if final and not exist_ok:
                            raise FileExistsError(relative)
                    os.close(current_fd)
                    current_fd = next_fd
                os.fsync(current_fd)
            finally:
                os.close(current_fd)
        except FileExistsError:
            raise
        except UnsafePath:
            raise
        except OSError as exc:
            raise UnsafePath("path is missing or unsafe") from exc

    def rename(self, source: str, destination: str, *, overwrite: bool = False) -> None:
        """Rename an entry inside the tree without resolving either leaf link."""

        try:
            with _confined_parent(self.root, source) as (source_fd, source_leaf):
                source_info = os.stat(source_leaf, dir_fd=source_fd, follow_symlinks=False)
                if stat.S_ISLNK(source_info.st_mode):
                    raise UnsafePath("source is a symlink")
                with _confined_parent(self.root, destination) as (destination_fd, destination_leaf):
                    if overwrite:
                        os.replace(
                            source_leaf,
                            destination_leaf,
                            src_dir_fd=source_fd,
                            dst_dir_fd=destination_fd,
                        )
                    else:
                        _rename_no_replace(source_fd, source_leaf, destination_fd, destination_leaf)
                    os.fsync(source_fd)
                    if destination_fd != source_fd:
                        os.fsync(destination_fd)
        except FileExistsError:
            raise
        except UnsafePath:
            raise
        except OSError as exc:
            raise UnsafePath("path is missing or unsafe") from exc

    def list(self, relative: str | None = None) -> list[str]:
        """List direct children, rejecting symlinks and non-file/non-directory entries."""

        try:
            with self._directory(relative) as directory_fd:
                names = sorted(os.listdir(directory_fd))
                for name in names:
                    info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                        raise UnsafePath("directory contains an unsafe entry")
                return names
        except UnsafePath:
            raise
        except OSError as exc:
            raise UnsafePath("path is missing or unsafe") from exc

    def delete_tree(self, relative: str) -> None:
        """Delete a directory tree, rejecting every symlink rather than traversing it."""

        def remove_directory(directory_fd: int) -> None:
            for name in os.listdir(directory_fd):
                info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if stat.S_ISREG(info.st_mode):
                    os.unlink(name, dir_fd=directory_fd)
                elif stat.S_ISDIR(info.st_mode):
                    child_fd = os.open(
                        name,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=directory_fd,
                    )
                    try:
                        remove_directory(child_fd)
                    finally:
                        os.close(child_fd)
                    os.rmdir(name, dir_fd=directory_fd)
                else:
                    raise UnsafePath("directory contains an unsafe entry")

        try:
            with _confined_parent(self.root, relative) as (parent_fd, leaf):
                descriptor = os.open(
                    leaf, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd
                )
                try:
                    remove_directory(descriptor)
                finally:
                    os.close(descriptor)
                os.rmdir(leaf, dir_fd=parent_fd)
                os.fsync(parent_fd)
        except UnsafePath:
            raise
        except OSError as exc:
            raise UnsafePath("path is missing or unsafe") from exc
