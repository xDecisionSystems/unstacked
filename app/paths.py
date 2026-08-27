import os
import re
import unicodedata
from pathlib import Path, PurePosixPath

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
