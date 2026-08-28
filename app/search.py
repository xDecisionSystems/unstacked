"""Bounded, ACL-first full-text search over the portable content tree.

This module deliberately has no HTTP concerns.  A caller supplies its already
authenticated user and database session; the same core can then be reused by
the web UI and agent transports without giving either an authorization bypass.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session

from app.acl import AccessPolicy, load_policy
from app.config import Settings
from app.content import ContentRepository
from app.frontmatter_io import PageDocument, parse_page
from app.models import User
from app.paths import ConfinedFileTooLarge, UnsafePath, path_depth, read_confined_text


class SearchError(ValueError):
    """A safe, input-or-budget-related search failure."""


class SearchTimeout(SearchError):
    """The configured search time budget elapsed."""


@dataclass(frozen=True)
class SearchResult:
    path: str
    title: str
    tags: tuple[str, ...]
    snippet: str


@dataclass(frozen=True)
class SearchPage:
    items: tuple[SearchResult, ...]
    page: int
    page_size: int
    total: int
    truncated: bool


Runner = Callable[..., subprocess.CompletedProcess[bytes]]


class ContentSearch:
    """Search Markdown bodies plus page titles/tags without a search index.

    Paths are discovered using directory metadata, ACL-filtered, and only then
    passed to ripgrep or opened by the fallback.  In particular, neither an
    unreadable page's bytes nor its match count influence this result.
    """

    def __init__(
        self,
        content: ContentRepository,
        *,
        rg_path: str | None = None,
        runner: Runner = subprocess.run,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.content = content
        self.settings: Settings = content.settings
        self._rg_path = rg_path if rg_path is not None else shutil.which("rg")
        self._runner = runner
        self._clock = clock

    def search(
        self,
        session: Session,
        user: User,
        query: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> SearchPage:
        query = self._validate_query(query)
        page, page_size = self._validate_pagination(page, page_size)
        deadline = self._clock() + self.settings.search_timeout_seconds
        policy = load_policy(session, user)
        candidates = self._authorized_candidates(policy, deadline)
        matched = self._matching_paths(candidates, query, deadline)

        results: list[SearchResult] = []
        truncated = False
        for relative in matched:
            self._check_deadline(deadline)
            result = self._result_for_path(relative, query)
            # A page can change after ripgrep scanned it.  Recheck the content
            # used for its returned snippet rather than returning a stale hit.
            if result is None:
                continue
            results.append(result)
            if len(results) == self.settings.max_search_results:
                truncated = len(matched) > len(results)
                break

        total = len(results)
        start = (page - 1) * page_size
        return SearchPage(
            items=tuple(results[start : start + page_size]),
            page=page,
            page_size=page_size,
            total=total,
            truncated=truncated,
        )

    def _authorized_candidates(self, policy: AccessPolicy, deadline: float) -> list[str]:
        candidates: list[str] = []
        for file_path in sorted(self.content.docs.rglob("*.md")):
            self._check_deadline(deadline)
            if file_path.is_symlink() or not file_path.is_file():
                continue
            relative = file_path.relative_to(self.content.docs).as_posix()
            if path_depth(relative) not in {2, 3}:
                continue
            # This permission check intentionally happens before a backend can
            # open the file.  ``read_confined_text`` later protects its actual
            # open against a symlink replacement race.
            if not policy.decide(relative).can_read:
                continue
            candidates.append(relative)
            if len(candidates) == self.settings.max_search_files:
                break
        return candidates

    def _matching_paths(self, candidates: Sequence[str], query: str, deadline: float) -> list[str]:
        if not candidates:
            return []
        if self._rg_path:
            return self._ripgrep_matches(candidates, query, deadline)
        return self._python_matches(candidates, query, deadline)

    def _ripgrep_matches(
        self, candidates: Sequence[str], query: str, deadline: float
    ) -> list[str]:
        """Return matching *authorized* paths using an option-safe argv array.

        ``--null`` makes filenames with line breaks unambiguous.  We still
        parse and verify the file ourselves, because the public contract only
        searches Markdown bodies and front-matter title/tags, not arbitrary
        metadata fields.
        """

        paths = [str(self.content.docs / relative) for relative in candidates]
        remaining = self._remaining_seconds(deadline)
        command = [
            self._rg_path,
            "--fixed-strings",
            "--files-with-matches",
            "--null",
            "--no-messages",
            "--max-filesize",
            str(self.settings.max_search_file_bytes),
            "--",
            query,
            *paths,
        ]
        try:
            completed = self._runner(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=remaining,
            )
        except subprocess.TimeoutExpired as exc:
            raise SearchTimeout("search timed out") from exc
        self._check_deadline(deadline)
        if completed.returncode not in {0, 1}:
            # If the optional accelerator cannot run, use the semantically
            # equivalent local implementation; a missing binary must not make
            # search unavailable on a minimal container image.
            return self._python_matches(candidates, query, deadline)
        by_absolute_path = {str(self.content.docs / relative): relative for relative in candidates}
        found: set[str] = set()
        for raw_path in completed.stdout.split(b"\0"):
            if not raw_path:
                continue
            try:
                value = raw_path.decode("utf-8")
            except UnicodeDecodeError:
                continue
            relative = by_absolute_path.get(value)
            if relative is not None:
                found.add(relative)
        return sorted(found)

    def _python_matches(
        self, candidates: Sequence[str], query: str, deadline: float
    ) -> list[str]:
        matches = []
        for relative in candidates:
            self._check_deadline(deadline)
            document = self._read_document(relative)
            if document is not None and self._matches(document, query):
                matches.append(relative)
        return matches

    def _result_for_path(self, relative: str, query: str) -> SearchResult | None:
        document = self._read_document(relative)
        if document is None or not self._matches(document, query):
            return None
        title = document.metadata["title"]
        tags = tuple(document.metadata["tags"])
        return SearchResult(
            path=relative,
            title=title,
            tags=tags,
            snippet=_snippet(self._first_matching_text(document, query), query,
                             self.settings.max_search_snippet_chars),
        )

    def _read_document(self, relative: str) -> PageDocument | None:
        try:
            raw = read_confined_text(
                self.content.docs, relative, max_bytes=self.settings.max_search_file_bytes
            )
        except (ConfinedFileTooLarge, UnicodeDecodeError, UnsafePath):
            return None
        return parse_page(raw, default_title=Path(relative).stem)

    @staticmethod
    def _matches(document: PageDocument, query: str) -> bool:
        return any(query in value for value in _searchable_text(document))

    @staticmethod
    def _first_matching_text(document: PageDocument, query: str) -> str:
        return next(value for value in _searchable_text(document) if query in value)

    def _validate_query(self, query: str) -> str:
        if not isinstance(query, str) or not query:
            raise SearchError("query must be a non-empty string")
        if len(query) > self.settings.max_search_query_chars:
            raise SearchError("query exceeds configured length limit")
        # Ripgrep is line-oriented unless explicitly put into a different
        # mode.  Reject line separators rather than letting the accelerator
        # and fallback disagree about a cross-line literal.
        if any(character in query for character in "\x00\r\n"):
            raise SearchError("query contains an invalid character")
        return query

    def _validate_pagination(self, page: int, page_size: int) -> tuple[int, int]:
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise SearchError("page must be a positive integer")
        if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size < 1:
            raise SearchError("page size must be a positive integer")
        if page_size > self.settings.max_search_results:
            raise SearchError("page size exceeds configured result limit")
        return page, page_size

    def _check_deadline(self, deadline: float) -> None:
        if self._clock() >= deadline:
            raise SearchTimeout("search timed out")

    def _remaining_seconds(self, deadline: float) -> float:
        self._check_deadline(deadline)
        return max(deadline - self._clock(), 0.001)


def _searchable_text(document: PageDocument) -> tuple[str, ...]:
    """The exact fields this product promises to search, in stable order."""

    return (document.metadata["title"], *document.metadata["tags"], document.content)


def _snippet(text: str, query: str, limit: int) -> str:
    """Return a deterministic plain-text excerpt; HTML escaping is a UI job."""

    index = text.index(query)
    if len(text) <= limit:
        return text
    room = limit - len(query)
    before = room // 2
    start = max(0, index - before)
    end = min(len(text), start + limit)
    start = max(0, end - limit)
    prefix = "…" if start else ""
    suffix = "…" if end < len(text) else ""
    # Keep the public string within its advertised character budget.
    body_limit = limit - len(prefix) - len(suffix)
    body = text[start : start + body_limit]
    return f"{prefix}{body}{suffix}"
