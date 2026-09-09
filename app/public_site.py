"""Build an anonymous, read-only MkDocs site from explicitly public content.

This is intentionally *not* :mod:`app.export`: the administrator export is a
private recovery artifact containing every non-draft page.  The public build
uses only the portable public flags stored in ``.pages`` and Home frontmatter,
and publishes a complete site only after a strict MkDocs build succeeds.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from app.config import Settings
from app.content import ASSETS_ROOT, HOME_PAGE_RELATIVE, ContentRepository
from app.export import ExportError, StaticExportRunner
from app.frontmatter_io import parse_page
from app.nav import NavigationError, read_navigation

_MARKDOWN_LINK = re.compile(r"!?\[[^]]*\]\(([^)\s]+)(?:\s+[^)]*)?\)")


class PublicSiteError(ExportError):
    """A safe-to-display reason a filtered public site was not published."""


@dataclass(frozen=True)
class PublicSiteStatus:
    last_success_at: str | None
    last_error: str | None


class PublicSiteBuilder:
    """Build a filtered site into a staging tree and publish it atomically."""

    def __init__(self, settings: Settings, content: ContentRepository):
        self.settings = settings
        self.content = content
        self.destination = settings.public_site_path.resolve()
        self._last_success_at: str | None = None
        self._last_error: str | None = None

    def status(self) -> PublicSiteStatus:
        return PublicSiteStatus(self._last_success_at, self._last_error)

    def build(self) -> Path:
        """Build and atomically replace the public webroot on success only."""

        self.destination.parent.mkdir(parents=True, exist_ok=True)
        with self.content.git.lock:
            with tempfile.TemporaryDirectory(
                dir=self.destination.parent, prefix=".unstacked-public-source-"
            ) as temporary:
                source = Path(temporary) / "source"
                self._stage_source(source)
                candidate = Path(temporary) / "site"
                runner = StaticExportRunner(self.settings, self.content)
                output, problem = runner._run(
                    [
                        self.settings.mkdocs_executable,
                        "build",
                        "--strict",
                        "--site-dir",
                        str(candidate),
                    ],
                    cwd=source,
                )
                if problem:
                    raise PublicSiteError(problem)
                if not candidate.is_dir() or not (candidate / "index.html").is_file():
                    raise PublicSiteError("Public site build produced no home page")
                self._publish(candidate)
        self._last_success_at = datetime.now(timezone.utc).isoformat()
        self._last_error = None
        return self.destination

    def build_recording_failure(self) -> None:
        """Run a best-effort publication without making content saves fail."""

        try:
            self.build()
        except PublicSiteError as exc:
            self.record_failure(exc)
        except OSError:
            # Keep optional public publication from affecting a durable
            # content save, while avoiding filesystem details in the UI.
            self._last_error = "Public site build failed"

    def record_failure(self, error: PublicSiteError) -> None:
        """Retain only the builder's safe, user-facing failure contract."""

        self._last_error = str(error)

    def _stage_source(self, destination: Path) -> None:
        root = self.content.root
        docs = root / "docs"
        destination.mkdir()
        # MkDocs configuration and the draft hook are portable, non-content
        # build inputs.  The generated source gets a safe root navigation below
        # rather than copying potentially private entries from root `.pages`.
        for name in ("mkdocs.yml", "requirements.txt"):
            source = root / name
            if not source.is_file() or source.is_symlink():
                raise PublicSiteError("Public site source is unavailable")
            shutil.copy2(source, destination / name)
        hooks = root / "hooks"
        if hooks.is_dir() and not hooks.is_symlink():
            shutil.copytree(hooks, destination / "hooks", symlinks=True)
        staged_docs = destination / "docs"
        staged_docs.mkdir()

        public_books = self._public_books(docs)
        home_is_public = self._home_is_public(docs)
        if home_is_public:
            self._copy_file(docs / HOME_PAGE_RELATIVE, staged_docs / HOME_PAGE_RELATIVE)
        else:
            # A fresh workspace with no public material is still a valid,
            # harmless website rather than a server error or directory listing.
            (staged_docs / HOME_PAGE_RELATIVE).write_text(
                "---\ntitle: Public workspace\n---\n\n# Public workspace\n\n"
                "No public content is available yet.\n",
                encoding="utf-8",
            )

        for slug in public_books:
            self._copy_tree(docs / slug, staged_docs / slug)
            asset_source = docs / ASSETS_ROOT / slug
            if asset_source.is_dir() and not asset_source.is_symlink():
                self._copy_tree(asset_source, staged_docs / ASSETS_ROOT / slug)

        # Explicitly listing only staged books makes root navigation incapable
        # of retaining a private entry supplied by an operator's original file.
        root_nav = ["index.md", *[f"{slug}/" for slug in public_books]]
        (staged_docs / ".pages").write_text(
            "nav:\n" + "".join(f"  - {entry}\n" for entry in root_nav),
            encoding="utf-8",
        )
        self._reject_private_links(staged_docs)

    @staticmethod
    def _copy_file(source: Path, destination: Path) -> None:
        if not source.is_file() or source.is_symlink():
            raise PublicSiteError("Public content source is unavailable")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    @staticmethod
    def _copy_tree(source: Path, destination: Path) -> None:
        if source.is_symlink():
            raise PublicSiteError("Public content source contains an unsupported link")
        try:
            shutil.copytree(source, destination, symlinks=False)
        except OSError as exc:
            raise PublicSiteError("Public content could not be staged") from exc
        for current, directories, files in os.walk(destination, followlinks=False):
            current_path = Path(current)
            if current_path.is_symlink() or any(
                (current_path / name).is_symlink() for name in files
            ):
                raise PublicSiteError("Public content source contains an unsupported link")
            directories[:] = [
                name for name in directories if not (current_path / name).is_symlink()
            ]

    @staticmethod
    def _public_books(docs: Path) -> list[str]:
        books: list[str] = []
        if not docs.is_dir():
            return books
        for candidate in sorted(docs.iterdir(), key=lambda item: item.name.casefold()):
            if (
                not candidate.is_dir()
                or candidate.is_symlink()
                or candidate.name == ASSETS_ROOT
                or candidate.name.startswith(".")
            ):
                continue
            try:
                if read_navigation(candidate / ".pages").public:
                    books.append(candidate.name)
            except NavigationError:
                # A malformed visibility file is private by default.
                continue
        return books

    @staticmethod
    def _home_is_public(docs: Path) -> bool:
        home = docs / HOME_PAGE_RELATIVE
        if not home.is_file() or home.is_symlink():
            return False
        try:
            document = parse_page(home.read_text(encoding="utf-8"), default_title="Home")
            return bool(document.metadata.get("public"))
        except OSError:
            return False

    @staticmethod
    def _reject_private_links(docs: Path) -> None:
        """Fail closed rather than render a public path to omitted material."""

        for page in docs.rglob("*.md"):
            if page.is_symlink():
                raise PublicSiteError("Public content source contains an unsupported link")
            text = page.read_text(encoding="utf-8")
            if re.search(r"(?:href|src)\\s*=\\s*['\"]/(?:pages|books|admin|api)(?:/|['\"])", text):
                raise PublicSiteError("Public content links to a management-only path")
            for match in _MARKDOWN_LINK.finditer(text):
                target = match.group(1)
                parts = urlsplit(target)
                if parts.scheme or target.startswith("#"):
                    continue
                if target.startswith(("/pages/", "/books/", "/admin", "/api")):
                    raise PublicSiteError("Public content links to a management-only path")
                raw_path = parts.path
                if target.startswith("/assets/"):
                    if not (docs / raw_path.lstrip("/")).is_file():
                        raise PublicSiteError("Public content links to non-public content")
                    continue
                if not raw_path or not raw_path.endswith(".md"):
                    continue
                resolved = (page.parent / raw_path).resolve()
                try:
                    resolved.relative_to(docs.resolve())
                except ValueError as exc:
                    raise PublicSiteError("Public content links outside the public site") from exc
                if not resolved.is_file():
                    raise PublicSiteError("Public content links to non-public content")

    def _publish(self, candidate: Path) -> None:
        previous = self.destination.with_name(f".{self.destination.name}.previous")
        if previous.exists():
            shutil.rmtree(previous)
        try:
            if self.destination.exists():
                os.replace(self.destination, previous)
            os.replace(candidate, self.destination)
            if previous.exists():
                shutil.rmtree(previous)
        except OSError as exc:
            if not self.destination.exists() and previous.exists():
                os.replace(previous, self.destination)
            raise PublicSiteError("Public site could not be published") from exc


class PublicSiteWorker:
    """Coalesce post-commit public builds outside the content-save request."""

    def __init__(self, builder: PublicSiteBuilder):
        self.builder = builder
        self._requested = threading.Event()
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stopped.clear()
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="public-site-build"
            )
            self._thread.start()
            self.request_build()

    def stop(self) -> None:
        with self._lifecycle_lock:
            thread = self._thread
            self._stopped.set()
            self._requested.set()
        if thread is not None:
            thread.join(timeout=5)

    def request_build(self) -> None:
        self._requested.set()

    def _run(self) -> None:
        while not self._stopped.is_set():
            self._requested.wait()
            self._requested.clear()
            if self._stopped.wait(1):
                return
            self.builder.build_recording_failure()
