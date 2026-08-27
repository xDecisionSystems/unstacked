import os
import re
import unicodedata
from pathlib import Path, PurePosixPath

from slugify import slugify

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RESERVED_ROOT_NAMES = {"assets"}
RESERVED_PART_NAMES = {".pages", ".git", "site"}


class UnsafePath(ValueError):
    pass


def make_slug(title: str, requested: str | None = None) -> str:
    candidate = requested if requested is not None else slugify(title)
    candidate = unicodedata.normalize("NFKC", candidate).casefold()
    if len(candidate) > 100 or not SLUG_RE.fullmatch(candidate):
        raise UnsafePath("slug must contain only lowercase letters, numbers, and hyphens")
    if candidate in RESERVED_ROOT_NAMES or candidate in RESERVED_PART_NAMES:
        raise UnsafePath("slug is reserved")
    return candidate


def normalize_relative_path(raw: str) -> str:
    if not raw or "\x00" in raw or "\\" in raw:
        raise UnsafePath("invalid path")
    path = PurePosixPath(unicodedata.normalize("NFKC", raw))
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise UnsafePath("invalid path")
    if any(part.startswith(".") or part in RESERVED_PART_NAMES for part in path.parts):
        raise UnsafePath("reserved path component")
    return path.as_posix()


def safe_join(root: Path, relative: str) -> Path:
    normalized = normalize_relative_path(relative)
    resolved_root = root.resolve()
    candidate = (resolved_root / normalized).resolve(strict=False)
    if os.path.commonpath((str(resolved_root), str(candidate))) != str(resolved_root):
        raise UnsafePath("path escapes the content root")
    return candidate
