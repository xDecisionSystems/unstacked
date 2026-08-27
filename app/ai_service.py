from app.acl import AuthorizationContext
from app.content import ContentRepository, CreatedContent, MovedContent
from app.git_backend import Revision
from app.paths import make_slug, normalize_relative_path


class AIContentService:
    def __init__(self, content: ContentRepository):
        self.content = content

    def tree(self, authorization: AuthorizationContext) -> list[dict]:
        return self.content.tree(authorization.session, authorization.user)

    def export(self, authorization: AuthorizationContext) -> bytes:
        return self.content.export_zip(authorization.session, authorization.user)

    def get_page(self, authorization: AuthorizationContext, path: str) -> tuple[dict, str, str]:
        path = authorization.require_read(path)
        return self.content.read_page(path)

    def create_book(
        self,
        authorization: AuthorizationContext,
        *,
        title: str,
        slug: str | None,
    ) -> CreatedContent:
        authorization.require_admin()
        target = make_slug(title, slug)
        authorization.reject_orphaned_exact_grant(target)
        return self.content.create_book(title, slug, authorization.user)

    def create_chapter(
        self,
        authorization: AuthorizationContext,
        *,
        book_slug: str,
        title: str,
        slug: str | None,
    ) -> CreatedContent:
        authorization.require_admin()
        book_slug = make_slug(book_slug, book_slug)
        target = f"{book_slug}/{make_slug(title, slug)}"
        authorization.reject_orphaned_exact_grant(target)
        return self.content.create_chapter(book_slug, title, slug, authorization.user)

    def create_page(
        self,
        authorization: AuthorizationContext,
        *,
        parent: str,
        title: str,
        slug: str | None,
        markdown: str,
        tags: list[str],
        draft: bool,
    ) -> CreatedContent:
        parent = authorization.require_write(parent)
        target = f"{parent}/{make_slug(title, slug)}.md"
        authorization.reject_orphaned_exact_grant(target)
        return self.content.create_page(
            parent,
            title,
            slug,
            markdown,
            tags,
            draft,
            authorization.user,
        )

    def page_history(self, authorization: AuthorizationContext, path: str) -> list[Revision]:
        path = authorization.require_read(path)
        return self.content.page_history(path)

    def page_diff(
        self,
        authorization: AuthorizationContext,
        path: str,
        from_revision: str,
        to_revision: str,
    ) -> str:
        path = authorization.require_read(path)
        return self.content.page_diff(path, from_revision, to_revision)

    def restore_page(self, authorization: AuthorizationContext, path: str, revision: str) -> str:
        path = authorization.require_write(path)
        return self.content.restore_page(path, revision, authorization.user)

    # These methods are intentionally present even before a browser transport
    # exposes them.  Future routes must use this service rather than calling
    # ContentRepository directly, keeping the ACL boundary in one place.
    def update_page(self, authorization: AuthorizationContext, path: str, *args, **kwargs) -> str:
        return self.content.update_page(
            authorization.require_write(path), *args, authorization.user, **kwargs
        )

    def delete_page(self, authorization: AuthorizationContext, path: str) -> str:
        return self.content.delete_page(
            authorization.require_ungranted_subtree(path), authorization.user
        )

    def delete_book(self, authorization: AuthorizationContext, slug: str) -> str:
        path = authorization.require_ungranted_subtree(make_slug(slug, slug))
        return self.content.delete_book(path, authorization.user)

    def delete_chapter(
        self, authorization: AuthorizationContext, book_slug: str, chapter_slug: str
    ) -> str:
        path = authorization.require_ungranted_subtree(
            f"{make_slug(book_slug, book_slug)}/{make_slug(chapter_slug, chapter_slug)}"
        )
        return self.content.delete_chapter(*path.split("/"), authorization.user)

    def move_page(
        self,
        authorization: AuthorizationContext,
        path: str,
        new_parent: str | None,
        new_slug: str | None,
    ) -> MovedContent:
        authorization.require_admin()
        source = normalize_relative_path(path)
        authorization.require_ungranted_subtree(source)
        parent = (
            normalize_relative_path(new_parent) if new_parent else source.rsplit("/", 1)[0]
        )
        old_slug = source.rsplit("/", 1)[-1].removesuffix(".md")
        target = f"{parent}/{make_slug(old_slug, new_slug or old_slug)}.md"
        authorization.reject_orphaned_exact_grant(target)
        return self.content.move_page(source, parent, new_slug, authorization.user)

    def rename_book(
        self, authorization: AuthorizationContext, slug: str, new_slug: str
    ) -> MovedContent:
        authorization.require_admin()
        source = make_slug(slug, slug)
        authorization.require_ungranted_subtree(source)
        authorization.reject_orphaned_exact_grant(make_slug(source, new_slug))
        return self.content.rename_book(source, new_slug, authorization.user)

    def rename_chapter(
        self, authorization: AuthorizationContext, book_slug: str, slug: str, new_slug: str
    ) -> MovedContent:
        authorization.require_admin()
        source = f"{make_slug(book_slug, book_slug)}/{make_slug(slug, slug)}"
        authorization.require_ungranted_subtree(source)
        target = f"{source.rsplit('/', 1)[0]}/{make_slug(slug, new_slug)}"
        authorization.reject_orphaned_exact_grant(target)
        return self.content.rename_chapter(book_slug, slug, new_slug, authorization.user)
