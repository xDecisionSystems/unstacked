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

from pathlib import Path
from typing import Annotated
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from app.acl import AuthorizationContext
from app.content import ContentMissing
from app.models import User
from app.nav import NavigationError, read_navigation
from app.paths import UnsafePath
from app.render import MarkdownRenderer, RenderConfigurationError
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


async def _read_form(request: Request) -> dict[str, str]:
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
    if len(body) > MAX_FORM_BYTES:
        return {}
    return dict(parse_qsl(body.decode("utf-8", "replace"), keep_blank_values=True))


def _authorization(session: Session, user: User) -> AuthorizationContext:
    return AuthorizationContext(session, user)


def _slug_title(slug: str) -> str:
    """Humanize a slug for display when no nicer title is available."""

    return slug.replace("-", " ").replace("_", " ").strip().title() or slug


def _container_title(docs: Path, *parts: str) -> str:
    """Read a book/chapter's display title from its ``.pages`` file.

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


def _page_view(path: str) -> dict[str, str]:
    slug = path.rsplit("/", 1)[-1].removesuffix(".md")
    return {"path": path.removesuffix(".md"), "label": _slug_title(slug)}


def _tree_view_model(docs: Path, raw_tree: list[dict]) -> list[dict]:
    """Turn ``AIContentService.tree()``'s raw dicts into a display-ready shape.

    Container titles come from each book/chapter's ``.pages`` file rather
    than a per-page front-matter read: there are far fewer containers than
    pages, and the sidebar renders on every authenticated request. Page
    labels use the slug rather than the front-matter title for the same
    reason -- the full title is still shown once the page itself is open.
    """

    books = []
    for book in raw_tree:
        chapters = [
            {
                "title": _container_title(docs, book["slug"], chapter["slug"]),
                "pages": [_page_view(p) for p in chapter["pages"]],
            }
            for chapter in book.get("chapters", [])
        ]
        books.append(
            {
                "title": _container_title(docs, book["slug"]),
                "pages": [_page_view(p) for p in book["pages"]],
                "chapters": chapters,
            }
        )
    return books


def _breadcrumbs(docs: Path, path: str, metadata: dict) -> list[str]:
    parts = path.split("/")
    crumbs = [_container_title(docs, parts[0])]
    if len(parts) == 3:
        crumbs.append(_container_title(docs, parts[0], parts[1]))
    title = metadata.get("title") if isinstance(metadata, dict) else None
    crumbs.append(title or _slug_title(parts[-1].removesuffix(".md")))
    return crumbs


def _base_context(request: Request, session: Session, user: User) -> dict:
    content = request.app.state.content
    authorization = _authorization(session, user)
    raw_tree = request.app.state.ai_service.tree(authorization)
    return {
        "request": request,
        "current_user": user,
        "csrf_token": read_session(request, user).csrf_token,
        "tree": _tree_view_model(content.docs, raw_tree),
    }


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


@router.get("/pages/{page_path:path}", response_class=HTMLResponse, include_in_schema=False)
def page_view(
    request: Request,
    page_path: str,
    user: Annotated[User, Depends(require_normal_web_user)],
) -> Response:
    content = request.app.state.content
    target = page_path if page_path.endswith(".md") else f"{page_path}.md"
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
            return templates.TemplateResponse(
                request, "page_error.html", context, status_code=500
            )
        context = _base_context(request, session, user)
        context.update(
            {
                "page_title": metadata.get("title") if isinstance(metadata, dict) else None,
                "body": html,
                "breadcrumbs": _breadcrumbs(content.docs, target, metadata),
                "current_path": target.removesuffix(".md"),
                "draft": bool(metadata.get("draft")) if isinstance(metadata, dict) else False,
            }
        )
    return templates.TemplateResponse(request, "page.html", context)
