from sqlmodel import Session

from app.acl import resolve_access
from app.content import ContentRepository, CreatedContent
from app.models import User
from app.paths import normalize_relative_path


class AccessDenied(RuntimeError):
    """Raised without path details so missing and unreadable content stay indistinguishable."""


class AIContentService:
    def __init__(self, content: ContentRepository):
        self.content = content

    def tree(self, session: Session, user: User) -> list[dict]:
        return self.content.tree(session, user)

    def export(self, session: Session, user: User) -> bytes:
        return self.content.export_zip(session, user)

    def get_page(self, session: Session, user: User, path: str) -> tuple[dict, str, str]:
        path = normalize_relative_path(path)
        if not resolve_access(session, user, path).can_read:
            raise AccessDenied
        return self.content.read_page(path)

    def create_book(
        self,
        user: User,
        *,
        title: str,
        slug: str | None,
    ) -> CreatedContent:
        self._require_admin(user)
        return self.content.create_book(title, slug, user)

    def create_chapter(
        self,
        user: User,
        *,
        book_slug: str,
        title: str,
        slug: str | None,
    ) -> CreatedContent:
        self._require_admin(user)
        return self.content.create_chapter(book_slug, title, slug, user)

    def create_page(
        self,
        session: Session,
        user: User,
        *,
        parent: str,
        title: str,
        slug: str | None,
        markdown: str,
        tags: list[str],
        draft: bool,
    ) -> CreatedContent:
        parent = normalize_relative_path(parent)
        if not resolve_access(session, user, parent).can_write:
            raise AccessDenied
        return self.content.create_page(
            parent,
            title,
            slug,
            markdown,
            tags,
            draft,
            user,
        )

    @staticmethod
    def _require_admin(user: User) -> None:
        if not user.is_admin:
            raise AccessDenied
