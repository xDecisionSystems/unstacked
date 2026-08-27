import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import frontmatter
import yaml
from git import Actor, Repo
from sqlmodel import Session

from app.acl import resolve_access
from app.config import Settings
from app.git_backend import GitBackend
from app.models import User
from app.paths import make_slug, normalize_relative_path, safe_join


class ContentError(RuntimeError):
    pass


class ContentExists(ContentError):
    pass


class ContentMissing(ContentError):
    pass


@dataclass(frozen=True)
class CreatedContent:
    kind: str
    path: str
    slug: str
    commit: str


MKDOCS_YML = """site_name: Unstacked
strict: true
plugins:
  - search
  - awesome-nav:
      filename: .pages
hooks:
  - hooks/drafts.py
"""

CONTENT_REQUIREMENTS = """mkdocs==1.6.1
mkdocs-awesome-nav==3.3.0
"""

DRAFT_HOOK = """from pathlib import Path

import yaml
from mkdocs.structure.files import Files


def _is_draft(file, config):
    if not file.src_uri.endswith(".md"):
        return False
    text = (Path(config.docs_dir) / file.src_uri).read_text(encoding="utf-8")
    if not text.startswith("---\\n"):
        return False
    end = text.find("\\n---\\n", 4)
    if end == -1:
        raise ValueError(f"Malformed front matter in {file.src_uri}")
    metadata = yaml.safe_load(text[4:end])
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError(f"Front matter must be a mapping in {file.src_uri}")
    return bool(metadata and metadata.get("draft") is True)


def on_files(files, config, **kwargs):
    return Files([file for file in files if not _is_draft(file, config)])
"""


class ContentRepository:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.content_repo_path.resolve()
        self.docs = self.root / "docs"
        self.git = GitBackend(self.root, settings.content_lock_path)

    def initialize(self) -> None:
        with self.git.lock:
            if (self.root / ".git").is_dir():
                self.docs.mkdir(parents=True, exist_ok=True)
                return
            if self.root.exists() and any(self.root.iterdir()):
                raise ContentError("content path is non-empty and is not a git repository")
            self.root.mkdir(parents=True, exist_ok=True)
            self.docs.mkdir(parents=True, exist_ok=True)
            (self.root / "hooks").mkdir(exist_ok=True)
            self._atomic_write(self.root / "mkdocs.yml", MKDOCS_YML)
            self._atomic_write(self.root / "requirements.txt", CONTENT_REQUIREMENTS)
            self._atomic_write(self.root / "hooks" / "drafts.py", DRAFT_HOOK)
            self._atomic_write(self.root / ".gitignore", "site/\n")
            self._atomic_write(self.docs / ".pages", 'nav:\n  - index.md\n  - "*"\n')
            self._atomic_write(self.docs / "index.md", "# Unstacked\n")
            repo = Repo.init(self.root, initial_branch="main")
            repo.index.add(
                [
                    "mkdocs.yml",
                    "requirements.txt",
                    "hooks/drafts.py",
                    ".gitignore",
                    "docs/.pages",
                    "docs/index.md",
                ]
            )
            actor = Actor("Unstacked", "system@unstacked.local")
            repo.index.commit(
                "Initialize portable MkDocs content repository",
                author=actor,
                committer=actor,
            )

    def create_book(self, title: str, requested_slug: str | None, actor: User) -> CreatedContent:
        slug = make_slug(title, requested_slug)
        book = safe_join(self.docs, slug)
        nav = book / ".pages"
        with self.git.lock:
            if book.exists():
                raise ContentExists("book already exists")
            try:
                book.mkdir()
                self._write_nav(nav, title)
                commit = self.git.commit_paths(
                    [nav],
                    name=actor.display_name,
                    email=actor.email,
                    message=f"Create book: {title}",
                )
            except Exception:
                shutil.rmtree(book, ignore_errors=True)
                raise
        return CreatedContent("book", slug, slug, commit)

    def create_chapter(
        self,
        book_slug: str,
        title: str,
        requested_slug: str | None,
        actor: User,
    ) -> CreatedContent:
        book_slug = make_slug(book_slug, book_slug)
        slug = make_slug(title, requested_slug)
        book = safe_join(self.docs, book_slug)
        chapter = safe_join(self.docs, f"{book_slug}/{slug}")
        nav = chapter / ".pages"
        with self.git.lock:
            if not book.is_dir():
                raise ContentMissing("book not found")
            if chapter.exists():
                raise ContentExists("chapter already exists")
            try:
                chapter.mkdir()
                self._write_nav(nav, title)
                commit = self.git.commit_paths(
                    [nav],
                    name=actor.display_name,
                    email=actor.email,
                    message=f"Create chapter: {book_slug}/{title}",
                )
            except Exception:
                shutil.rmtree(chapter, ignore_errors=True)
                raise
        path = f"{book_slug}/{slug}"
        return CreatedContent("chapter", path, slug, commit)

    def create_page(
        self,
        parent: str,
        title: str,
        requested_slug: str | None,
        markdown: str,
        tags: list[str],
        draft: bool,
        actor: User,
    ) -> CreatedContent:
        parent = normalize_relative_path(parent)
        slug = make_slug(title, requested_slug)
        parent_path = safe_join(self.docs, parent)
        page_relative = f"{parent}/{slug}.md"
        page = safe_join(self.docs, page_relative)
        if len(markdown.encode("utf-8")) > self.settings.max_page_bytes:
            raise ContentError("page exceeds configured size limit")
        now = datetime.now(timezone.utc).isoformat()
        post = frontmatter.Post(
            markdown,
            id=str(uuid4()),
            title=title,
            created_at=now,
            updated_at=now,
            author=actor.email,
            tags=tags,
            draft=draft,
        )
        serialized = frontmatter.dumps(post) + "\n"
        with self.git.lock:
            if not parent_path.is_dir():
                raise ContentMissing("parent book or chapter not found")
            if page.exists():
                raise ContentExists("page already exists")
            try:
                self._atomic_write(page, serialized)
                commit = self.git.commit_paths(
                    [page],
                    name=actor.display_name,
                    email=actor.email,
                    message=f"Create page: {page_relative}",
                )
            except Exception:
                page.unlink(missing_ok=True)
                raise
        return CreatedContent("page", page_relative, slug, commit)

    def read_page(self, relative: str) -> tuple[dict, str, str]:
        relative = normalize_relative_path(relative)
        if not relative.endswith(".md"):
            raise ContentMissing("page not found")
        page = safe_join(self.docs, relative)
        if not page.is_file():
            raise ContentMissing("page not found")
        if page.stat().st_size > self.settings.max_page_bytes:
            raise ContentError("page exceeds configured size limit")
        raw = page.read_text(encoding="utf-8")
        post = frontmatter.loads(raw)
        return dict(post.metadata), post.content, raw

    def authorized_pages(self, session: Session, user: User) -> list[str]:
        pages = []
        for page in sorted(self.docs.rglob("*.md")):
            relative = page.relative_to(self.docs).as_posix()
            if relative == "index.md":
                continue
            if resolve_access(session, user, relative).can_read:
                pages.append(relative)
        return pages

    def tree(self, session: Session, user: User) -> list[dict]:
        pages = self.authorized_pages(session, user)
        books: dict[str, dict] = {}
        if user.is_admin:
            for book_path in sorted(self.docs.iterdir()):
                if (
                    not book_path.is_dir()
                    or book_path.name == "assets"
                    or book_path.name.startswith(".")
                ):
                    continue
                book = books.setdefault(
                    book_path.name,
                    {"slug": book_path.name, "pages": [], "chapters": {}},
                )
                for chapter_path in sorted(book_path.iterdir()):
                    if chapter_path.is_dir() and not chapter_path.name.startswith("."):
                        book["chapters"].setdefault(
                            chapter_path.name,
                            {"slug": chapter_path.name, "pages": []},
                        )
        for path in pages:
            parts = path.split("/")
            if len(parts) not in {2, 3}:
                continue
            book = books.setdefault(parts[0], {"slug": parts[0], "pages": [], "chapters": {}})
            if len(parts) == 2:
                book["pages"].append(path)
            else:
                chapter = book["chapters"].setdefault(parts[1], {"slug": parts[1], "pages": []})
                chapter["pages"].append(path)
        result = []
        for book in books.values():
            book["chapters"] = list(book["chapters"].values())
            result.append(book)
        return result

    def export_zip(self, session: Session, user: User) -> bytes:
        pages = self.authorized_pages(session, user)
        output = BytesIO()
        with ZipFile(output, "w", ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps({"pages": pages}, indent=2))
            for relative in pages:
                archive.write(safe_join(self.docs, relative), f"docs/{relative}")
                if output.tell() > self.settings.max_export_bytes:
                    raise ContentError("export exceeds configured size limit")
        return output.getvalue()

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except Exception:
            Path(temporary).unlink(missing_ok=True)
            raise

    def _write_nav(self, path: Path, title: str) -> None:
        self._atomic_write(path, yaml.safe_dump({"title": title, "nav": ["*"]}, sort_keys=False))
