from app.acl import AccessDenied, AuthorizationContext
from app.content import (
    ASSETS_ROOT,
    AssetContent,
    ContentMissing,
    ContentRepository,
    CreatedContent,
    MovedContent,
    StoredAsset,
)
from app.git_backend import Revision
from app.paths import make_slug, normalize_relative_path
from app.search import ContentSearch, SearchPage


class AIContentService:
    """The shared, bounded AI-facing content contract.

    Transports deliberately receive only this service.  In particular, search
    keeps using :class:`ContentSearch` rather than reproducing its ACL-first
    filesystem walk or its deterministic item/snippet budgets in each client.
    """

    def __init__(self, content: ContentRepository, *, search: ContentSearch | None = None):
        self.content = content
        self.search_engine = search or ContentSearch(content)

    def tree(self, authorization: AuthorizationContext) -> list[dict]:
        return self.content.tree(authorization.session, authorization.user)

    def export(self, authorization: AuthorizationContext) -> bytes:
        return self.content.export_zip(authorization.session, authorization.user)

    def get_page(self, authorization: AuthorizationContext, path: str) -> tuple[dict, str, str]:
        # The service contract is intentionally no more informative than a
        # missing page.  Transports therefore cannot accidentally expose an
        # authorization oracle by treating these two failures differently.
        try:
            path = authorization.require_read(path)
        except AccessDenied as exc:
            raise ContentMissing("page not found") from exc
        return self.content.read_page(path)

    def search(
        self,
        authorization: AuthorizationContext,
        query: str,
        *,
        page: int = 1,
        page_size: int | None = None,
    ) -> SearchPage:
        """Search only content readable by ``authorization``.

        ``ContentSearch`` validates all inputs and applies the configured
        fixed item, file, byte, timeout, and snippet-character budgets.  The
        structured ``SearchPage`` is returned unchanged so every future
        transport sees identical pagination and truncation semantics.
        """

        # Keep the transport-neutral default usable when an operator lowers
        # the global item cap below the normal 20-item page size.
        effective_page_size = min(20, self.content.settings.max_search_results)
        return self.search_engine.search(
            authorization.session,
            authorization.user,
            query,
            page=page,
            page_size=effective_page_size if page_size is None else page_size,
        )

    def create_book(
        self,
        authorization: AuthorizationContext,
        *,
        title: str,
        slug: str | None,
    ) -> CreatedContent:
        authorization.require_admin()
        target = make_slug(title, slug)
        # Let the content layer report an ordinary duplicate before checking
        # stale grants. Creating a book also installs the built-in Admin grant,
        # so checking it first would turn a duplicate-book 409 into a 403.
        if (self.content.docs / target).exists():
            return self.content.create_book(title, slug, authorization.user)
        authorization.reject_orphaned_exact_grant(target)
        return self.content.create_book(title, slug, authorization.user)

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

    def set_container_tags(
        self, authorization: AuthorizationContext, *, path: str, tags: list[str]
    ) -> str:
        writable_path = authorization.require_write(path)
        return self.content.set_container_tags(writable_path, tags, authorization.user)

    def set_container_public(
        self, authorization: AuthorizationContext, *, path: str, public: bool
    ) -> str:
        return self.content.set_container_public(
            authorization.require_write(path), public, authorization.user
        )

    def set_subtree_public(
        self, authorization: AuthorizationContext, *, path: str, public: bool
    ) -> str:
        return self.content.set_subtree_public(
            authorization.require_write(path), public, authorization.user
        )

    def upload_asset(
        self,
        authorization: AuthorizationContext,
        *,
        book_slug: str,
        filename: str,
        data: bytes,
    ) -> StoredAsset:
        """Store an image for a book the caller may write to.

        Assets are authorized by the book that owns them, not by their own
        ``assets/...`` path: an asset is part of that book's content, so
        uploading one requires exactly what creating a page in it requires.
        """

        book_slug = make_slug(book_slug, book_slug)
        authorization.require_write(book_slug)
        return self.content.store_asset(book_slug, filename, data, authorization.user)

    def get_asset(self, authorization: AuthorizationContext, path: str) -> AssetContent:
        try:
            normalized = normalize_relative_path(path)
            parts = normalized.split("/")
            if len(parts) != 3 or parts[0] != ASSETS_ROOT:
                raise ContentMissing("asset not found")
            authorization.require_read(parts[1])
        except AccessDenied as exc:
            # Indistinguishable from a missing asset, as elsewhere: the reply
            # must not tell an unauthorized caller which books exist.
            raise ContentMissing("asset not found") from exc
        return self.content.read_asset(normalized)

    def delete_asset(
        self, authorization: AuthorizationContext, *, book_slug: str, filename: str
    ) -> str:
        book_slug = make_slug(book_slug, book_slug)
        authorization.require_write(book_slug)
        return self.content.delete_asset(book_slug, filename, authorization.user)

    def list_assets(self, authorization: AuthorizationContext, book_slug: str) -> list[str]:
        try:
            book = authorization.require_read(make_slug(book_slug, book_slug))
        except AccessDenied as exc:
            raise ContentMissing("book not found") from exc
        return self.content.list_assets(book)

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

    def page_revision_source(
        self, authorization: AuthorizationContext, path: str, revision: str
    ) -> str:
        return self.content.page_revision_source(authorization.require_read(path), revision)

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

    def set_page_title(self, authorization: AuthorizationContext, path: str, title: str) -> str:
        return self.content.set_page_title(
            authorization.require_write(path), title, authorization.user
        )

    def delete_page(self, authorization: AuthorizationContext, path: str) -> str:
        return self.content.delete_page(
            authorization.require_ungranted_subtree(path), authorization.user
        )

    def delete_book(self, authorization: AuthorizationContext, slug: str) -> str:
        path = authorization.require_ungranted_subtree(make_slug(slug, slug))
        return self.content.delete_book(path, authorization.user)

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
        parent = normalize_relative_path(new_parent) if new_parent else source.rsplit("/", 1)[0]
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
