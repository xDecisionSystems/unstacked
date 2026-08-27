"""Tolerant, lossless-enough front-matter access for wiki pages.

The content repository is intentionally editable without this application.
Consequently a page that lacks front matter, or contains YAML we cannot
understand, is still readable.  Writes only replace known application fields
and retain every other key from a parseable existing document.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import frontmatter

KNOWN_FIELDS = frozenset(
    {"id", "title", "created_at", "updated_at", "author", "tags", "draft"}
)


class FrontMatterError(ValueError):
    """Raised when a page cannot be serialized safely."""


@dataclass(frozen=True)
class PageDocument:
    """A page body and normalized application metadata.

    ``raw_metadata`` is retained internally so callers that round-trip a
    document can keep arbitrary operator-supplied front-matter keys.
    """

    metadata: dict[str, Any]
    content: str
    raw_metadata: dict[str, Any]


def read_page(path: Path, *, default_title: str | None = None) -> PageDocument:
    """Read ``path`` without allowing hand-authored metadata to crash callers."""

    return parse_page(path.read_text(encoding="utf-8"), default_title=default_title or path.stem)


def parse_page(raw: str, *, default_title: str = "Untitled") -> PageDocument:
    """Parse Markdown into a tolerant, normalized page document.

    Invalid front matter is deliberately treated as Markdown body text.  This
    leaves a pasted-in or damaged page visible and avoids silently interpreting
    a malformed ``draft`` value as publishable metadata.
    """

    try:
        post = frontmatter.loads(raw)
        raw_metadata = dict(post.metadata) if isinstance(post.metadata, Mapping) else {}
        content = post.content
    except Exception:
        raw_metadata = {}
        content = raw
    return PageDocument(
        metadata=_normalize_metadata(raw_metadata, default_title),
        content=content,
        raw_metadata=raw_metadata,
    )


def serialize_page(document: PageDocument, *, metadata: Mapping[str, Any] | None = None) -> str:
    """Serialize a document while retaining unknown keys from its source."""

    combined = dict(document.raw_metadata)
    combined.update(document.metadata)
    if metadata:
        combined.update(metadata)
    try:
        return frontmatter.dumps(frontmatter.Post(document.content, **combined)) + "\n"
    except Exception as exc:
        raise FrontMatterError("page front matter cannot be serialized") from exc


def write_page(
    path: Path,
    document: PageDocument,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    """Atomically replace a page, retaining unknown parseable metadata keys."""

    _atomic_write(path, serialize_page(document, metadata=metadata))


def new_page(content: str, metadata: Mapping[str, Any]) -> str:
    """Create serialized Markdown for a newly created page."""

    title = metadata.get("title")
    document = PageDocument(
        metadata=_normalize_metadata(metadata, title if isinstance(title, str) else "Untitled"),
        content=content,
        raw_metadata={},
    )
    # Preserve supplied known values (notably UUID and timestamps) verbatim.
    return serialize_page(document, metadata=metadata)


def _normalize_metadata(raw: Mapping[str, Any], default_title: str) -> dict[str, Any]:
    """Return the public schema with safe defaults for arbitrary YAML values."""

    title = raw.get("title")
    normalized: dict[str, Any] = {
        "id": raw.get("id") if isinstance(raw.get("id"), str) else None,
        "title": title.strip() if isinstance(title, str) and title.strip() else default_title,
        "created_at": _timestamp(raw.get("created_at")),
        "updated_at": _timestamp(raw.get("updated_at")),
        "author": raw.get("author") if isinstance(raw.get("author"), str) else None,
        "tags": _tags(raw.get("tags")),
        "draft": raw.get("draft") if isinstance(raw.get("draft"), bool) else False,
    }
    normalized.update({key: value for key, value in raw.items() if key not in KNOWN_FIELDS})
    return normalized


def _timestamp(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value if isinstance(value, str) else None


def _tags(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [tag for tag in value if isinstance(tag, str)]
    return []


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise
