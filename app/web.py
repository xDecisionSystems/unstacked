"""Server-rendered browser UI: login, forced password change, tree, page view.

Plain Jinja2 templates, no SPA framework and no client-side routing. The
JSON-oriented routes in :mod:`app.web_auth` (``/auth/login``,
``/auth/change-password``, ``/auth/logout``) were built for a machine caller:
they return a JSON body and never redirect. A browser ``<form>`` submission
needs the opposite -- a redirect with the session cookie already set -- so
this module bridges the two by calling those routes' own handler functions
directly (as plain Python, not through FastAPI's dependency injection) with a
:class:`~fastapi.responses.RedirectResponse` standing in for the ``Response``
they write the cookie onto. This keeps every bit of credential verification,
CSRF validation, and session-cookie issuance in :mod:`app.web_auth`; nothing
here re-implements any of it. The alternative considered was a client-side
``fetch()`` call handling the JSON response in vanilla JS -- also defensible,
but this keeps the login/change-password flow working with JavaScript
disabled and avoids a second copy of "what does a successful login redirect
to" logic living in a template's inline script.

Every other route (tree, page view, logout) requires
``require_normal_web_user`` -- never the bare ``get_current_web_user`` -- so a
forced password change cannot be bypassed by simply not following the
redirect from ``/``.
"""

import difflib
from pathlib import Path
from typing import Annotated
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from sqlmodel import Session

from app import branding, theme, theme_config
from app.acl import AccessDenied, AuthorizationContext
from app.assets import AssetTooLarge, UnsupportedAsset, detect_image
from app.content import ContentConflict, ContentError, ContentExists, ContentMissing
from app.export import ExportError, StaticExportRunner
from app.models import User
from app.nav import NavigationError, read_navigation
from app.paths import UnsafePath
from app.render import MarkdownRenderer, RenderConfigurationError
from app.search import SearchError, SearchTimeout
from app.web_auth import (
    FORM_CONTENT_TYPE,
    MAX_FORM_BYTES,
    LoginRequest,
    PasswordChangeRequest,
    get_current_web_user,
    read_session,
    require_csrf,
    require_normal_web_user,
)
from app.web_auth import change_password as auth_change_password
from app.web_auth import login as auth_login
from app.web_auth import logout as auth_logout

router = APIRouter(tags=["Web UI"])

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
EDITOR_FORM_OVERHEAD = 16_384


def _theme_style_tag(request: Request) -> Markup:
    """The admin-selected palette as an inline ``<style>`` override.

    Registered as a Jinja global (below) rather than threaded through every
    route's context: every page -- including the pre-login screens, which
    never call ``_base_context`` -- needs the same override, and reading a
    small JSON file per render keeps a saved change visible immediately, with
    no cache to invalidate.
    """

    settings = request.app.state.settings
    state = theme_config.load(settings.theme_config_path)
    return Markup(f"<style>{theme.css_block(state.palette)}</style>")


templates.env.globals["theme_style"] = _theme_style_tag


def _branding(request: Request) -> dict[str, str | None]:
    return branding.load(request.app.state.settings.branding_config_path).__dict__


templates.env.globals["branding"] = _branding


@router.get("/branding/logo", include_in_schema=False)
def branding_logo(request: Request) -> Response:
    path = request.app.state.settings.branding_config_path.with_name("branding-logo")
    try:
        data = path.read_bytes()
        detected = detect_image(
            data,
            max_pixels=request.app.state.settings.max_upload_pixels,
            max_dimension=request.app.state.settings.max_upload_dimension,
        )
    except (OSError, AssetTooLarge, UnsupportedAsset):
        return RedirectResponse("/static/branding/badger-typewriter.png", status_code=307)
    return Response(
        data, media_type=detected.media_type, headers={"X-Content-Type-Options": "nosniff"}
    )


async def _read_form(request: Request, *, max_bytes: int = MAX_FORM_BYTES) -> dict[str, str]:
    """Parse a urlencoded form body without requiring ``python-multipart``.

    Mirrors ``app.web_auth._csrf_from_form``: Starlette's ``request.form()``
    needs ``python-multipart`` even for a plain urlencoded body, and that
    package is not one of this project's dependencies. Every form in this
    module is a handful of short fields, so a manual parse under the same
    byte cap used for the CSRF field is enough.
    """

    if not request.headers.get("content-type", "").startswith(FORM_CONTENT_TYPE):
        return {}
    body = await request.body()
    if len(body) > max_bytes:
        return {}
    return dict(parse_qsl(body.decode("utf-8", "replace"), keep_blank_values=True))


def _authorization(session: Session, user: User) -> AuthorizationContext:
    return AuthorizationContext(session, user)


def _slug_title(slug: str) -> str:
    """Humanize a slug for display when no nicer title is available."""

    return slug.replace("-", " ").replace("_", " ").strip().title() or slug


def _container_title(docs: Path, *parts: str) -> str:
    """Read a book's display title from its ``.pages`` file.

    Falls back to a humanized slug when the file is missing or malformed --
    the tree must still render even if the container navigation file is
    hand-edited into something ``read_navigation`` cannot parse.
    """

    nav_path = docs.joinpath(*parts, ".pages")
    if nav_path.is_file():
        try:
            title = read_navigation(nav_path).title
        except NavigationError:
            title = None
        if title:
            return title
    return _slug_title(parts[-1])


def _container_tags(docs: Path, *parts: str) -> list[str]:
    try:
        return read_navigation(docs.joinpath(*parts, ".pages")).tags
    except NavigationError:
        return []


def _container_public(docs: Path, *parts: str) -> bool:
    try:
        return read_navigation(docs.joinpath(*parts, ".pages")).public
    except NavigationError:
        return False


def _optional_normal_web_user(request: Request) -> User | None:
    try:
        return require_normal_web_user(get_current_web_user(request))
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            return None
        raise


def _public_page(content, target: str) -> bool:
    try:
        metadata, _markdown, _raw = content.read_page(target)
    except (ContentError, UnsafePath):
        return False
    parts = target.removesuffix(".md").split("/")
    if metadata.get("draft"):
        return False
    # Pages inherit the visibility of their book.  The book/page model has
    # no intermediate container whose visibility could override this.
    return len(parts) == 2 and _container_public(content.docs, parts[0])


def _public_context(request: Request) -> dict:
    return {
        "request": request,
        "current_user": None,
        "csrf_token": "",
        "tree": [],
        "is_admin": False,
    }


def _page_view(content, path: str) -> dict[str, str | bool]:
    slug = path.rsplit("/", 1)[-1].removesuffix(".md")
    try:
        metadata, _markdown, _raw = content.read_page(path)
        draft = bool(metadata.get("draft"))
        label = metadata.get("title") or _slug_title(slug)
        card_image = metadata.get("card_image")
    except (ContentError, UnsafePath):
        # A hand-edited broken page must not make every authenticated view
        # fail.  The page route will present the actual error when opened.
        draft, label, card_image = False, _slug_title(slug), None
    return {
        "path": path.removesuffix(".md"),
        "label": label,
        "draft": draft,
        "public": bool(metadata.get("public")) if "metadata" in locals() else False,
        "card_image": card_image if isinstance(card_image, str) else None,
    }


def _tree_view_model(
    content, authorization: AuthorizationContext, raw_tree: list[dict]
) -> list[dict]:
    """Turn ``AIContentService.tree()``'s raw dicts into a display-ready shape.

    Book titles come from each book's ``.pages`` file rather than a per-page
    front-matter read.  Page labels use their front matter where available.
    A book's write decision controls its single add-page control.
    """

    books = []
    for book in raw_tree:
        pages = [_page_view(content, p) for p in book["pages"]]
        book_tags: set[str] = set(_container_tags(content.docs, book["slug"]))
        for page in book["pages"]:
            try:
                metadata, _body, _raw = content.read_page(page)
            except (ContentError, UnsafePath):
                continue
            book_tags.update(
                tag for tag in metadata.get("tags", []) if isinstance(tag, str) and tag
            )
        books.append(
            {
                "slug": book["slug"],
                "title": _container_title(content.docs, book["slug"]),
                "pages": pages,
                "page_count": len(pages),
                "tags": sorted(book_tags, key=str.casefold),
                "can_read_book": authorization.policy.decide(book["slug"]).can_read,
                "can_write": authorization.policy.decide(book["slug"]).can_write,
                "public": _container_public(content.docs, book["slug"]),
                "visibility": "public"
                if _container_public(content.docs, book["slug"])
                else "private",
            }
        )
    return books


def _breadcrumbs(docs: Path, path: str, metadata: dict) -> list[str]:
    parts = path.split("/")
    crumbs = [_container_title(docs, parts[0])]
    title = metadata.get("title") if isinstance(metadata, dict) else None
    crumbs.append(title or _slug_title(parts[-1].removesuffix(".md")))
    return crumbs


def _base_context(request: Request, session: Session, user: User) -> dict:
    content = request.app.state.content
    authorization = _authorization(session, user)
    raw_tree = request.app.state.ai_service.tree(authorization)
    display_tree = _tree_view_model(content, authorization, raw_tree)
    home_targets = content.home_items()
    featured_targets = set(home_targets)
    for book in display_tree:
        book["featured"] = book["slug"] in featured_targets
        for page in book["pages"]:
            page["featured"] = f"{page['path']}.md" in featured_targets
    books_by_slug = {book["slug"]: book for book in display_tree}
    pages_by_path = {
        page["path"] + ".md": {**page, "book_title": book["title"]}
        for book in display_tree
        for page in book["pages"]
    }
    home_items = []
    for target in home_targets:
        if target.endswith(".md") and target in pages_by_path:
            home_items.append({"kind": "page", "target": target, **pages_by_path[target]})
        elif target in books_by_slug:
            home_items.append({"kind": "book", "target": target, **books_by_slug[target]})
    pages = sorted(
        pages_by_path.values(), key=lambda page: (page["label"].casefold(), page["path"])
    )
    return {
        "request": request,
        "current_user": user,
        "csrf_token": read_session(request, user).csrf_token,
        "tree": [book for book in display_tree if book["can_read_book"]],
        "pages": pages,
        "home_items": home_items,
        "is_admin": user.is_admin,
    }


def _home_return_path(value: str | None) -> str:
    """Keep home-toggle forms on a local page without permitting redirects elsewhere."""

    if isinstance(value, str) and value.startswith("/") and not value.startswith("//"):
        return value
    return "/tree"


def _highlight_search_snippet(snippet: str, query: str) -> Markup:
    """Escape a literal snippet, adding markup only around literal matches.

    Search text is content supplied by wiki editors.  It must never be handed
    to the template as safe HTML merely to draw the match highlight.  Splitting
    before escaping preserves the fixed-string search contract (including
    punctuation) while making both the surrounding text and the query safe.
    """

    pieces = snippet.split(query)
    if len(pieces) == 1:
        return escape(snippet)
    rendered: list[Markup] = []
    for index, piece in enumerate(pieces):
        rendered.append(escape(piece))
        if index != len(pieces) - 1:
            rendered.append(Markup("<mark>") + escape(query) + Markup("</mark>"))
    return Markup("").join(rendered)


def _search_breadcrumbs(content, path: str) -> list[str]:
    """Return display breadcrumbs without opening the matched page again."""

    parts = path.removesuffix(".md").split("/")
    breadcrumbs = [_container_title(content.docs, parts[0])]
    return breadcrumbs


@router.get("/", include_in_schema=False)
def index(request: Request) -> RedirectResponse:
    """Route by session state: unauthenticated, forced change, or ordinary."""

    try:
        user = get_current_web_user(request)
    except HTTPException:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if user.must_change_password:
        return RedirectResponse("/change-password", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse("/tree", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request) -> Response:
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login", include_in_schema=False)
async def login_submit(request: Request) -> Response:
    form = await _read_form(request)
    try:
        payload = LoginRequest(username=form.get("username", ""), password=form.get("password", ""))
    except Exception:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Username and password are required"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    redirect = RedirectResponse("/tree", status_code=status.HTTP_303_SEE_OTHER)
    try:
        result = auth_login(payload, request, redirect)
    except HTTPException as exc:
        message = (
            "Too many attempts. Try again shortly."
            if exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS
            else "Invalid username or password"
        )
        return templates.TemplateResponse(
            request, "login.html", {"error": message}, status_code=exc.status_code
        )
    if result.must_change_password:
        redirect.headers["location"] = "/change-password"
    return redirect


@router.get("/change-password", response_class=HTMLResponse, include_in_schema=False)
def change_password_page(
    request: Request,
    user: Annotated[User, Depends(get_current_web_user)],
) -> Response:
    """Reachable by a forced-change session -- this is its only way out."""

    session_info = read_session(request, user)
    return templates.TemplateResponse(
        request,
        "change_password.html",
        {"error": None, "csrf_token": session_info.csrf_token},
    )


@router.post(
    "/change-password",
    include_in_schema=False,
    dependencies=[Depends(require_csrf)],
)
async def change_password_submit(
    request: Request,
    user: Annotated[User, Depends(get_current_web_user)],
) -> Response:
    form = await _read_form(request)
    try:
        payload = PasswordChangeRequest(
            current_password=form.get("current_password", ""),
            new_password=form.get("new_password", ""),
        )
    except Exception:
        return templates.TemplateResponse(
            request,
            "change_password.html",
            {
                "error": "New password must be at least 12 characters",
                "csrf_token": read_session(request, user).csrf_token,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    redirect = RedirectResponse("/tree", status_code=status.HTTP_303_SEE_OTHER)
    try:
        auth_change_password(payload, request, redirect, user)
    except HTTPException as exc:
        return templates.TemplateResponse(
            request,
            "change_password.html",
            {
                "error": "Current password is incorrect",
                "csrf_token": read_session(request, user).csrf_token,
            },
            status_code=exc.status_code,
        )
    return redirect


@router.post("/logout", include_in_schema=False, dependencies=[Depends(require_csrf)])
def logout_submit(
    request: Request,
    user: Annotated[User, Depends(get_current_web_user)],
) -> Response:
    redirect = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    auth_logout(request, redirect, user)
    return redirect


@router.get("/tree", response_class=HTMLResponse, include_in_schema=False)
def tree_view(
    request: Request,
    user: Annotated[User, Depends(require_normal_web_user)],
) -> Response:
    with Session(request.app.state.engine) as session:
        context = _base_context(request, session, user)
    return templates.TemplateResponse(request, "tree.html", context)


@router.get("/books", response_class=HTMLResponse, include_in_schema=False)
def books_view(
    request: Request,
    user: Annotated[User, Depends(require_normal_web_user)],
) -> Response:
    with Session(request.app.state.engine) as session:
        context = _base_context(request, session, user)
    return templates.TemplateResponse(request, "books.html", context)


@router.get("/pages", response_class=HTMLResponse, include_in_schema=False)
def pages_view(
    request: Request,
    user: Annotated[User, Depends(require_normal_web_user)],
) -> Response:
    with Session(request.app.state.engine) as session:
        context = _base_context(request, session, user)
    return templates.TemplateResponse(request, "pages.html", context)


@router.get("/books/{book_slug}", response_class=HTMLResponse, include_in_schema=False)
def book_view(
    request: Request,
    book_slug: str,
    user: Annotated[User | None, Depends(_optional_normal_web_user)],
) -> Response:
    """A single book's pages, shown as one reorderable card grid.

    Reuses the same ACL-filtered ``tree`` context every page already builds
    rather than a second query -- a book absent from it is either nonexistent
    or unreadable by this user, and the two must stay indistinguishable, so
    both collapse to the same 404 as everywhere else in this module.
    """

    if user is None:
        content = request.app.state.content
        book_path = content.docs / book_slug
        pages = (
            [
                _page_view(content, page.relative_to(content.docs).as_posix())
                for page in sorted(book_path.rglob("*.md"))
                if _public_page(content, page.relative_to(content.docs).as_posix())
            ]
            if book_path.is_dir()
            else []
        )
        if not pages and not _container_public(content.docs, book_slug):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found")
        context = _public_context(request)
        context["book"] = {
            "slug": book_slug,
            "title": _container_title(content.docs, book_slug),
            "pages": pages,
            "page_count": len(pages),
            "tags": [],
            "can_write": False,
        }
        return templates.TemplateResponse(request, "book.html", context)
    with Session(request.app.state.engine) as session:
        context = _base_context(request, session, user)
    book = next((entry for entry in context["tree"] if entry["slug"] == book_slug), None)
    if book is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found")
    context["book"] = book
    return templates.TemplateResponse(request, "book.html", context)


@router.get("/search", response_class=HTMLResponse, include_in_schema=False)
def search_view(
    request: Request,
    user: Annotated[User, Depends(require_normal_web_user)],
    q: str = "",
    page: int = 1,
) -> Response:
    """Render bounded, ACL-filtered literal search results for browser users."""

    with Session(request.app.state.engine) as session:
        context = _base_context(request, session, user)
        context.update({"query": q, "results": None, "error": None})
        if not q:
            return templates.TemplateResponse(request, "search.html", context)
        try:
            results = request.app.state.ai_service.search(
                _authorization(session, user), q, page=page
            )
        except SearchTimeout:
            context["error"] = "Search timed out. Please try a narrower query."
        except SearchError as exc:
            # SearchError messages describe only caller-controlled validation
            # and configured budgets; no filesystem or ACL detail is exposed.
            context["error"] = str(exc)
        else:
            context["results"] = {
                "entries": [
                    {
                        "path": item.path.removesuffix(".md"),
                        "title": item.title,
                        "tags": item.tags,
                        "breadcrumbs": _search_breadcrumbs(request.app.state.content, item.path),
                        "snippet": _highlight_search_snippet(item.snippet, q),
                    }
                    for item in results.items
                ],
                "page": results.page,
                "has_previous": results.page > 1,
                "has_next": results.page * results.page_size < results.total,
                "previous_page": results.page - 1,
                "next_page": results.page + 1,
                "total": results.total,
                "truncated": results.truncated,
            }
    return templates.TemplateResponse(request, "search.html", context)


def _tags(value: str) -> list[str]:
    """Parse the compact comma-separated field used by the HTML editor."""

    tags = [tag.strip() for tag in value.split(",") if tag.strip()]
    if len(tags) > 100 or any(len(tag) > 100 for tag in tags):
        raise ValueError("Use at most 100 tags of 100 characters each")
    return tags


def _web_error(exc: Exception) -> str:
    if isinstance(exc, ContentConflict):
        return "This page changed since you opened it. Reload it before saving."
    if isinstance(exc, ContentExists):
        return "That location is already in use."
    if isinstance(exc, AccessDenied):
        return "That content does not exist, or you do not have access to it."
    if isinstance(exc, (ContentError, UnsafePath, ValueError)):
        return str(exc) or "The requested change is not valid."
    return "The requested change could not be completed."


def _editor_context(
    request: Request,
    session: Session,
    user: User,
    *,
    path: str | None = None,
    form: dict[str, str] | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> Response:
    context = _base_context(request, session, user)
    content = request.app.state.content
    if path is not None and form is None:
        authorization = _authorization(session, user)
        metadata, markdown, _raw = request.app.state.ai_service.get_page(authorization, path)
        form = {
            "title": str(metadata.get("title") or _slug_title(path.rsplit("/", 1)[-1])),
            "markdown": markdown,
            "tags": ", ".join(str(tag) for tag in metadata.get("tags", [])),
            "draft": "on" if metadata.get("draft") else "",
            "base_blob_sha": content.page_blob_sha(path),
            "parent": path.rsplit("/", 1)[0],
            "card_image": str(metadata.get("card_image") or ""),
        }
    context.update({"form": form or {}, "error": error, "editing_path": path})
    return templates.TemplateResponse(request, "editor.html", context, status_code=status_code)


def _history_context(
    request: Request,
    session: Session,
    user: User,
    path: str,
    *,
    from_revision: str | None = None,
    to_revision: str | None = None,
    error: str | None = None,
) -> dict:
    """Build a history view solely from the ACL-aware service contract."""

    authorization = _authorization(session, user)
    revisions = request.app.state.ai_service.page_history(authorization, path)
    known = {revision.sha for revision in revisions}
    if from_revision is not None and from_revision not in known:
        raise ContentMissing("revision not found")
    if to_revision is not None and to_revision not in known:
        raise ContentMissing("revision not found")
    if to_revision is None:
        to_revision = revisions[0].sha
    if from_revision is None:
        from_revision = revisions[1].sha if len(revisions) > 1 else revisions[0].sha
    before = request.app.state.ai_service.page_revision_source(authorization, path, from_revision)
    after = request.app.state.ai_service.page_revision_source(authorization, path, to_revision)
    context = _base_context(request, session, user)
    context.update(
        {
            "history_path": path.removesuffix(".md"),
            "revisions": revisions,
            "from_revision": from_revision,
            "to_revision": to_revision,
            # HtmlDiff escapes source lines before creating its table.  The
            # template may therefore render this one generated fragment safe.
            "diff_table": difflib.HtmlDiff(wrapcolumn=100).make_table(
                before.splitlines(),
                after.splitlines(),
                fromdesc=from_revision[:12],
                todesc=to_revision[:12],
                context=True,
                numlines=3,
            ),
            "can_restore": authorization.policy.decide(path).can_write,
            "error": error,
        }
    )
    return context


@router.get("/settings", response_class=HTMLResponse, include_in_schema=False)
@router.get("/admin", response_class=HTMLResponse, include_in_schema=False)
def admin_view(
    request: Request, user: Annotated[User, Depends(require_normal_web_user)]
) -> Response:
    """Administrative console; mutations stay in the established admin APIs."""

    if not user.is_admin:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found")
    with Session(request.app.state.engine) as session:
        context = _base_context(request, session, user)
    return templates.TemplateResponse(request, "admin.html", context)


@router.post("/admin/export", include_in_schema=False, dependencies=[Depends(require_csrf)])
async def download_static_export(
    request: Request, user: Annotated[User, Depends(require_normal_web_user)]
) -> Response:
    """Return a freshly packaged static export after explicit ACL warning."""

    if not user.is_admin:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found")
    form = await _read_form(request)
    if form.get("acknowledge_no_acl") != "on":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Acknowledge that this export includes all non-draft content without ACLs",
        )
    try:
        archive = StaticExportRunner(
            request.app.state.settings, request.app.state.content
        ).package_for(user)
    except ExportError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return Response(
        content=archive,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="unstacked-static-export.zip"'},
    )


@router.get("/pages/{page_path:path}/history", response_class=HTMLResponse, include_in_schema=False)
def page_history_view(
    request: Request,
    page_path: str,
    user: Annotated[User, Depends(require_normal_web_user)],
    from_revision: str | None = None,
    to_revision: str | None = None,
) -> Response:
    target = page_path if page_path.endswith(".md") else f"{page_path}.md"
    with Session(request.app.state.engine) as session:
        try:
            context = _history_context(
                request,
                session,
                user,
                target,
                from_revision=from_revision,
                to_revision=to_revision,
            )
        except (AccessDenied, ContentError, UnsafePath):
            context = _base_context(request, session, user)
            return templates.TemplateResponse(request, "404.html", context, status_code=404)
    return templates.TemplateResponse(request, "history.html", context)


@router.post(
    "/pages/{page_path:path}/history/restore",
    include_in_schema=False,
    dependencies=[Depends(require_csrf)],
)
async def restore_page_revision_submit(
    request: Request,
    page_path: str,
    user: Annotated[User, Depends(require_normal_web_user)],
) -> Response:
    form = await _read_form(request)
    target = page_path if page_path.endswith(".md") else f"{page_path}.md"
    revision = form.get("revision", "")
    with Session(request.app.state.engine) as session:
        try:
            # Only a revision which actually touched this page may be restored
            # through this form.  Besides making the UI predictable, this
            # avoids using Git's path lookup as a cross-page revision oracle.
            history = request.app.state.ai_service.page_history(
                _authorization(session, user), target
            )
            if revision not in {entry.sha for entry in history}:
                raise ContentMissing("revision not found")
            request.app.state.ai_service.restore_page(
                _authorization(session, user), target, revision
            )
        except AccessDenied:
            context = _base_context(request, session, user)
            return templates.TemplateResponse(request, "404.html", context, status_code=404)
        except (ContentError, UnsafePath) as exc:
            try:
                context = _history_context(request, session, user, target, error=_web_error(exc))
            except (AccessDenied, ContentError, UnsafePath):
                context = _base_context(request, session, user)
                return templates.TemplateResponse(request, "404.html", context, status_code=404)
            return templates.TemplateResponse(request, "history.html", context, status_code=422)
    return RedirectResponse(f"/pages/{target.removesuffix('.md')}", status_code=303)


@router.get("/pages/{page_path:path}/edit", response_class=HTMLResponse, include_in_schema=False)
def edit_page(
    request: Request,
    page_path: str,
    user: Annotated[User, Depends(require_normal_web_user)],
) -> Response:
    target = page_path if page_path.endswith(".md") else f"{page_path}.md"
    with Session(request.app.state.engine) as session:
        try:
            _authorization(session, user).require_write(target)
            return _editor_context(request, session, user, path=target)
        except (AccessDenied, ContentError, UnsafePath):
            context = _base_context(request, session, user)
            return templates.TemplateResponse(request, "404.html", context, status_code=404)


@router.post(
    "/pages/{page_path:path}/edit", include_in_schema=False, dependencies=[Depends(require_csrf)]
)
async def save_page(
    request: Request,
    page_path: str,
    user: Annotated[User, Depends(require_normal_web_user)],
) -> Response:
    form = await _read_form(
        request, max_bytes=request.app.state.settings.max_page_bytes + EDITOR_FORM_OVERHEAD
    )
    target = page_path if page_path.endswith(".md") else f"{page_path}.md"
    with Session(request.app.state.engine) as session:
        try:
            request.app.state.ai_service.update_page(
                _authorization(session, user),
                target,
                form.get("markdown", ""),
                _tags(form.get("tags", "")),
                form.get("draft") == "on",
                base_blob_sha=form.get("base_blob_sha", ""),
                card_image=form.get("card_image") or None,
            )
        except (AccessDenied, ContentError, UnsafePath, ValueError) as exc:
            return _editor_context(
                request,
                session,
                user,
                path=target,
                form=form,
                error=_web_error(exc),
                status_code=409 if isinstance(exc, ContentConflict) else 422,
            )
    return RedirectResponse(f"/pages/{target.removesuffix('.md')}", status_code=303)


@router.post(
    "/pages/{page_path:path}/title", include_in_schema=False, dependencies=[Depends(require_csrf)]
)
async def save_page_title(
    request: Request,
    page_path: str,
    user: Annotated[User, Depends(require_normal_web_user)],
) -> Response:
    """Retitle a page without leaving its reader view."""

    form = await _read_form(request)
    target = page_path if page_path.endswith(".md") else f"{page_path}.md"
    with Session(request.app.state.engine) as session:
        try:
            request.app.state.ai_service.set_page_title(
                _authorization(session, user), target, form.get("title", "")
            )
        except (AccessDenied, ContentError, UnsafePath, ValueError) as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, _web_error(exc)) from exc
    return RedirectResponse(f"/pages/{target.removesuffix('.md')}", status_code=303)


@router.post(
    "/pages/{page_path:path}/preview", include_in_schema=False, dependencies=[Depends(require_csrf)]
)
async def preview_page(
    request: Request,
    page_path: str,
    user: Annotated[User, Depends(require_normal_web_user)],
) -> Response:
    form = await _read_form(
        request, max_bytes=request.app.state.settings.max_page_bytes + EDITOR_FORM_OVERHEAD
    )
    target = page_path if page_path.endswith(".md") else f"{page_path}.md"
    with Session(request.app.state.engine) as session:
        try:
            _authorization(session, user).require_write(target)
            html = MarkdownRenderer(request.app.state.content.root).render(
                target, form.get("markdown", "")
            )
        except (AccessDenied, UnsafePath):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found") from None
        except RenderConfigurationError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Preview is unavailable"
            ) from exc
    return JSONResponse({"html": html})


@router.post("/pages/preview", include_in_schema=False, dependencies=[Depends(require_csrf)])
async def preview_new_page(
    request: Request,
    user: Annotated[User, Depends(require_normal_web_user)],
) -> Response:
    """Render an unsaved page in a writable parent with the normal renderer."""

    form = await _read_form(
        request, max_bytes=request.app.state.settings.max_page_bytes + EDITOR_FORM_OVERHEAD
    )
    with Session(request.app.state.engine) as session:
        try:
            parent = _authorization(session, user).require_write(form.get("parent", ""))
            html = MarkdownRenderer(request.app.state.content.root).render(
                f"{parent}/preview.md", form.get("markdown", "")
            )
        except (AccessDenied, UnsafePath):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found") from None
        except RenderConfigurationError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Preview is unavailable"
            ) from exc
    return JSONResponse({"html": html})


@router.get("/pages/new", response_class=HTMLResponse, include_in_schema=False)
def new_page(
    request: Request, parent: str, user: Annotated[User, Depends(require_normal_web_user)]
) -> Response:
    with Session(request.app.state.engine) as session:
        try:
            parent = _authorization(session, user).require_write(parent)
        except (AccessDenied, UnsafePath):
            context = _base_context(request, session, user)
            return templates.TemplateResponse(request, "404.html", context, status_code=404)
        return _editor_context(
            request,
            session,
            user,
            form={
                "title": "",
                "markdown": "",
                "tags": "",
                "draft": "",
                "parent": parent,
                "card_image": "",
            },
        )


@router.post("/pages/new", include_in_schema=False, dependencies=[Depends(require_csrf)])
async def create_page_submit(
    request: Request, user: Annotated[User, Depends(require_normal_web_user)]
) -> Response:
    form = await _read_form(
        request, max_bytes=request.app.state.settings.max_page_bytes + EDITOR_FORM_OVERHEAD
    )
    with Session(request.app.state.engine) as session:
        try:
            created = request.app.state.ai_service.create_page(
                _authorization(session, user),
                parent=form.get("parent", ""),
                title=form.get("title", ""),
                slug=form.get("slug") or None,
                markdown=form.get("markdown", ""),
                tags=_tags(form.get("tags", "")),
                draft=form.get("draft") == "on",
                card_image=form.get("card_image") or None,
            )
        except (AccessDenied, ContentError, UnsafePath, ValueError) as exc:
            return _editor_context(
                request, session, user, form=form, error=_web_error(exc), status_code=422
            )
    return RedirectResponse(f"/pages/{created.path.removesuffix('.md')}", status_code=303)


@router.get("/pages/{page_path:path}/move", response_class=HTMLResponse, include_in_schema=False)
def move_page_form(
    request: Request, page_path: str, user: Annotated[User, Depends(require_normal_web_user)]
) -> Response:
    target = page_path if page_path.endswith(".md") else f"{page_path}.md"
    with Session(request.app.state.engine) as session:
        try:
            _authorization(session, user).require_admin()
            _authorization(session, user).require_ungranted_subtree(target)
        except (AccessDenied, UnsafePath):
            context = _base_context(request, session, user)
            return templates.TemplateResponse(request, "404.html", context, status_code=404)
        context = _base_context(request, session, user)
        context.update({"moving_path": target.removesuffix(".md"), "error": None})
        return templates.TemplateResponse(request, "move_page.html", context)


@router.post(
    "/pages/{page_path:path}/move", include_in_schema=False, dependencies=[Depends(require_csrf)]
)
async def move_page_submit(
    request: Request, page_path: str, user: Annotated[User, Depends(require_normal_web_user)]
) -> Response:
    form = await _read_form(request)
    target = page_path if page_path.endswith(".md") else f"{page_path}.md"
    with Session(request.app.state.engine) as session:
        try:
            moved = request.app.state.ai_service.move_page(
                _authorization(session, user),
                target,
                form.get("parent") or None,
                form.get("slug") or None,
            )
        except (AccessDenied, ContentError, UnsafePath) as exc:
            context = _base_context(request, session, user)
            context.update({"moving_path": target.removesuffix(".md"), "error": _web_error(exc)})
            return templates.TemplateResponse(request, "move_page.html", context, status_code=422)
    return RedirectResponse(f"/pages/{moved.path.removesuffix('.md')}", status_code=303)


@router.post(
    "/pages/{page_path:path}/delete", include_in_schema=False, dependencies=[Depends(require_csrf)]
)
def delete_page_submit(
    request: Request, page_path: str, user: Annotated[User, Depends(require_normal_web_user)]
) -> Response:
    target = page_path if page_path.endswith(".md") else f"{page_path}.md"
    with Session(request.app.state.engine) as session:
        try:
            request.app.state.ai_service.delete_page(_authorization(session, user), target)
        except (AccessDenied, ContentError, UnsafePath) as exc:
            context = _base_context(request, session, user)
            context.update({"error": _web_error(exc)})
            return templates.TemplateResponse(request, "page_error.html", context, status_code=422)
    return RedirectResponse("/tree", status_code=303)


def _manage_error_response(
    request: Request, session: Session, user: User, exc: Exception
) -> Response:
    context = _base_context(request, session, user)
    context.update({"error": _web_error(exc)})
    return templates.TemplateResponse(request, "manage.html", context, status_code=422)


@router.get("/manage", response_class=HTMLResponse, include_in_schema=False)
def manage_content(
    request: Request, user: Annotated[User, Depends(require_normal_web_user)]
) -> Response:
    with Session(request.app.state.engine) as session:
        try:
            _authorization(session, user).require_admin()
        except AccessDenied:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found") from None
        context = _base_context(request, session, user)
    context.update({"error": None})
    return templates.TemplateResponse(request, "manage.html", context)


@router.post("/manage/book", include_in_schema=False, dependencies=[Depends(require_csrf)])
async def create_book_submit(
    request: Request, user: Annotated[User, Depends(require_normal_web_user)]
) -> Response:
    form = await _read_form(request)
    with Session(request.app.state.engine) as session:
        try:
            created = request.app.state.ai_service.create_book(
                _authorization(session, user),
                title=form.get("title", ""),
                slug=form.get("slug") or None,
            )
        except (AccessDenied, ContentError, UnsafePath) as exc:
            return _manage_error_response(request, session, user, exc)
    return RedirectResponse(f"/pages/new?parent={created.path}", status_code=303)


@router.post("/home/feature", include_in_schema=False, dependencies=[Depends(require_csrf)])
async def feature_home_submit(
    request: Request, user: Annotated[User, Depends(require_normal_web_user)]
) -> Response:
    form = await _read_form(request)
    with Session(request.app.state.engine) as session:
        try:
            _authorization(session, user).require_admin()
            request.app.state.content.feature_on_home(form.get("target", ""), user)
        except (AccessDenied, ContentError, UnsafePath) as exc:
            return _manage_error_response(request, session, user, exc)
    return RedirectResponse(_home_return_path(form.get("return_to")), status_code=303)


@router.post("/home/remove", include_in_schema=False, dependencies=[Depends(require_csrf)])
async def remove_home_submit(
    request: Request, user: Annotated[User, Depends(require_normal_web_user)]
) -> Response:
    form = await _read_form(request)
    with Session(request.app.state.engine) as session:
        try:
            _authorization(session, user).require_admin()
            request.app.state.content.remove_from_home(form.get("target", ""), user)
        except (AccessDenied, ContentError, UnsafePath) as exc:
            return _manage_error_response(request, session, user, exc)
    return RedirectResponse(_home_return_path(form.get("return_to")), status_code=303)


@router.post(
    "/containers/{container_path:path}/tags",
    include_in_schema=False,
    dependencies=[Depends(require_csrf)],
)
async def set_container_tags_submit(
    request: Request,
    container_path: str,
    user: Annotated[User, Depends(require_normal_web_user)],
) -> Response:
    form = await _read_form(request)
    with Session(request.app.state.engine) as session:
        try:
            request.app.state.ai_service.set_container_tags(
                _authorization(session, user), path=container_path, tags=_tags(form.get("tags", ""))
            )
        except (AccessDenied, ContentError, UnsafePath, ValueError) as exc:
            return _manage_error_response(request, session, user, exc)
    return RedirectResponse(f"/books/{container_path.split('/')[0]}", status_code=303)


@router.post(
    "/containers/{container_path:path}/visibility",
    include_in_schema=False,
    dependencies=[Depends(require_csrf)],
)
async def set_container_public_submit(
    request: Request, container_path: str, user: Annotated[User, Depends(require_normal_web_user)]
) -> Response:
    form = await _read_form(request)
    with Session(request.app.state.engine) as session:
        request.app.state.ai_service.set_subtree_public(
            _authorization(session, user), path=container_path, public=form.get("public") == "on"
        )
    return RedirectResponse(f"/books/{container_path.split('/')[0]}", status_code=303)


@router.post("/manage/page", include_in_schema=False, dependencies=[Depends(require_csrf)])
async def create_page_quick_submit(
    request: Request, user: Annotated[User, Depends(require_normal_web_user)]
) -> Response:
    """A blank page, the same "create empty, fill in later" shape as a new
    book -- unlike ``POST /pages/new``, which carries a full
    markdown body from the editor and belongs to that flow alone. Lands back
    on the book page so the new card is right there to click into, rather
    than opening the editor immediately.
    """

    form = await _read_form(request)
    with Session(request.app.state.engine) as session:
        try:
            created = request.app.state.ai_service.create_page(
                _authorization(session, user),
                parent=form.get("parent", ""),
                title=form.get("title", ""),
                slug=form.get("slug") or None,
                markdown="",
                tags=[],
                draft=False,
            )
        except (AccessDenied, ContentError, UnsafePath, ValueError) as exc:
            return _manage_error_response(request, session, user, exc)
    book_slug = created.path.split("/", 1)[0]
    return RedirectResponse(f"/books/{book_slug}", status_code=303)


@router.post("/manage/book/rename", include_in_schema=False, dependencies=[Depends(require_csrf)])
async def rename_book_submit(
    request: Request, user: Annotated[User, Depends(require_normal_web_user)]
) -> Response:
    form = await _read_form(request)
    with Session(request.app.state.engine) as session:
        try:
            moved = request.app.state.ai_service.rename_book(
                _authorization(session, user), form.get("book_slug", ""), form.get("new_slug", "")
            )
        except (AccessDenied, ContentError, UnsafePath) as exc:
            return _manage_error_response(request, session, user, exc)
    return RedirectResponse(f"/pages/new?parent={moved.path}", status_code=303)


@router.post("/manage/book/delete", include_in_schema=False, dependencies=[Depends(require_csrf)])
async def delete_book_submit(
    request: Request, user: Annotated[User, Depends(require_normal_web_user)]
) -> Response:
    form = await _read_form(request)
    with Session(request.app.state.engine) as session:
        try:
            request.app.state.ai_service.delete_book(
                _authorization(session, user), form.get("book_slug", "")
            )
        except (AccessDenied, ContentError, UnsafePath) as exc:
            return _manage_error_response(request, session, user, exc)
    return RedirectResponse("/tree", status_code=303)


@router.get("/pages/{page_path:path}", response_class=HTMLResponse, include_in_schema=False)
def page_view(
    request: Request,
    page_path: str,
    user: Annotated[User | None, Depends(_optional_normal_web_user)],
) -> Response:
    content = request.app.state.content
    target = page_path if page_path.endswith(".md") else f"{page_path}.md"
    if user is None:
        if not _public_page(content, target):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found")
        metadata, markdown_source, _raw = content.read_page(target)
        try:
            html = MarkdownRenderer(content.root).render(target, markdown_source)
        except RenderConfigurationError:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Page cannot be rendered")
        context = _public_context(request)
        context.update(
            {
                "page_title": metadata.get("title"),
                "body": html,
                "breadcrumbs": _breadcrumbs(content.docs, target, metadata),
                "current_path": target.removesuffix(".md"),
                "draft": False,
                "can_write": False,
                "edit_form": {},
                "available_tags": [],
            }
        )
        return templates.TemplateResponse(request, "page.html", context)
    with Session(request.app.state.engine) as session:
        authorization = _authorization(session, user)
        try:
            metadata, markdown_source, _raw = request.app.state.ai_service.get_page(
                authorization, target
            )
        except (ContentMissing, UnsafePath):
            # Deliberately the same response whether the page never existed
            # or the caller just cannot read it -- see AIContentService.get_page.
            context = _base_context(request, session, user)
            return templates.TemplateResponse(request, "404.html", context, status_code=404)
        try:
            html = MarkdownRenderer(content.root).render(target, markdown_source)
        except RenderConfigurationError:
            context = _base_context(request, session, user)
            context.update(
                {
                    "error": "This page cannot be previewed due to the site's Markdown "
                    "configuration.",
                }
            )
            return templates.TemplateResponse(request, "page_error.html", context, status_code=500)
        context = _base_context(request, session, user)
        available_tags: set[str] = set()
        if authorization.policy.decide(target).can_write:
            for readable_path in content.authorized_pages(session, user):
                try:
                    page_metadata, _body, _raw = content.read_page(readable_path)
                except (ContentError, UnsafePath):
                    continue
                available_tags.update(
                    tag for tag in page_metadata.get("tags", []) if isinstance(tag, str) and tag
                )
        context.update(
            {
                "page_title": metadata.get("title") if isinstance(metadata, dict) else None,
                "body": html,
                "breadcrumbs": _breadcrumbs(content.docs, target, metadata),
                "current_path": target.removesuffix(".md"),
                "draft": bool(metadata.get("draft")) if isinstance(metadata, dict) else False,
                "can_write": authorization.policy.decide(target).can_write,
                "edit_form": {
                    "markdown": markdown_source,
                    "tags": ", ".join(str(tag) for tag in metadata.get("tags", [])),
                    "draft": bool(metadata.get("draft")),
                    "public": bool(metadata.get("public")),
                    "base_blob_sha": content.page_blob_sha(target),
                    "card_image": str(metadata.get("card_image") or ""),
                },
                "available_tags": sorted(available_tags, key=str.casefold),
            }
        )
    return templates.TemplateResponse(request, "page.html", context)
