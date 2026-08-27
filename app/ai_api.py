import re
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.ai_service import AccessDenied
from app.auth import authenticate, client_identifier, create_api_token, get_current_user
from app.content import ContentError, ContentExists, ContentMissing, CreatedContent
from app.models import User
from app.paths import UnsafePath, make_slug, normalize_relative_path

router = APIRouter(prefix="/api", tags=["AI content"])

# Characters safe to place inside a quoted Content-Disposition filename.
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]")


def attachment_disposition(filename: str) -> str:
    """Build a Content-Disposition header that a hostile filename cannot break.

    Slugs cannot contain quotes, but files may also be hand-created in the
    content repository, so the name is sanitized rather than trusted.
    """

    fallback = SAFE_FILENAME_RE.sub("_", filename) or "page.md"
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"


class TokenRequest(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=1024)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class RevokeTokensRequest(BaseModel):
    """Optionally select another user whose machine credentials to revoke.

    Omitting ``user_id`` always means the bearer-token caller.  Selecting a
    different account is an administrator-only security operation.
    """

    user_id: int | None = Field(default=None, gt=0)


class RevokeTokensResponse(BaseModel):
    user_id: int
    api_token_generation: int


class ContainerCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    slug: str | None = None


class PageCreate(ContainerCreate):
    markdown: str = ""
    tags: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list,
        max_length=100,
    )
    draft: bool = False


class CreatedResponse(BaseModel):
    kind: str
    path: str
    slug: str
    commit: str


class RevisionResponse(BaseModel):
    sha: str
    message: str
    author_name: str
    author_email: str
    authored_at: str


class DiffResponse(BaseModel):
    path: str
    from_revision: str
    to_revision: str
    diff: str


class RestoreRequest(BaseModel):
    revision: str = Field(min_length=7, max_length=64, pattern=r"^[0-9a-fA-F]+$")


class RestoreResponse(BaseModel):
    path: str
    restored_revision: str
    commit: str


def _created(value: CreatedContent) -> CreatedResponse:
    return CreatedResponse(**value.__dict__)


def _content_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ContentExists):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, (AccessDenied, ContentMissing, UnsafePath)):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Content not found")
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


@router.post("/auth/token", response_model=TokenResponse)
def issue_token(payload: TokenRequest, request: Request) -> TokenResponse:
    settings = request.app.state.settings
    client_host = client_identifier(request, settings.trusted_proxy_hops)
    request.app.state.login_limiter.check(f"{client_host}:{payload.username}")
    with Session(request.app.state.engine) as session:
        user = authenticate(session, payload.username, payload.password)
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
        if user.must_change_password:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Password change required")
        token = create_api_token(user, request.app.state.settings)
    return TokenResponse(
        access_token=token,
        expires_in=request.app.state.settings.api_token_ttl_seconds,
    )


@router.post("/auth/tokens/revoke", response_model=RevokeTokensResponse)
def revoke_api_tokens(
    payload: RevokeTokensRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> RevokeTokensResponse:
    """Invalidate every bearer token issued to one account.

    There are intentionally no token rows: advancing the account generation
    invalidates every signed token for that account without retaining a raw
    credential or even a credential fingerprint.  A user can revoke their own
    tokens; only an administrator may revoke another user's tokens.
    """

    target_id = payload.user_id if payload.user_id is not None else user.id
    if target_id is None:  # Defensive: authenticated users always have an id.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid bearer token")
    if target_id != user.id and not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required")

    with Session(request.app.state.engine) as session:
        target = session.get(User, target_id)
        if target is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
        target.api_token_generation += 1
        session.add(target)
        session.commit()
        session.refresh(target)
        return RevokeTokensResponse(
            user_id=target.id,
            api_token_generation=target.api_token_generation,
        )


@router.get("/ai/tree")
def get_tree(request: Request, user: Annotated[User, Depends(get_current_user)]):
    with Session(request.app.state.engine) as session:
        return {"books": request.app.state.ai_service.tree(session, user)}


@router.get("/ai/export")
def download_export(request: Request, user: Annotated[User, Depends(get_current_user)]):
    try:
        with Session(request.app.state.engine) as session:
            archive = request.app.state.ai_service.export(session, user)
    except ContentError as exc:
        raise _content_error(exc) from exc
    return Response(
        content=archive,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="unstacked-content.zip"'},
    )


@router.get("/ai/history/{content_path:path}/diff", response_model=DiffResponse)
def get_page_diff(
    content_path: str,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    from_revision: str = Query(min_length=7, max_length=64, pattern=r"^[0-9a-fA-F]+$"),
    to_revision: str = Query(min_length=7, max_length=64, pattern=r"^[0-9a-fA-F]+$"),
):
    try:
        path = normalize_relative_path(content_path)
        with Session(request.app.state.engine) as session:
            diff = request.app.state.ai_service.page_diff(
                session, user, path, from_revision, to_revision
            )
    except (AccessDenied, ContentError, UnsafePath) as exc:
        raise _content_error(exc) from exc
    return DiffResponse(
        path=path,
        from_revision=from_revision,
        to_revision=to_revision,
        diff=diff,
    )


@router.post("/ai/history/{content_path:path}/restore", response_model=RestoreResponse)
def restore_page_revision(
    content_path: str,
    payload: RestoreRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
):
    try:
        path = normalize_relative_path(content_path)
        with Session(request.app.state.engine) as session:
            commit = request.app.state.ai_service.restore_page(
                session, user, path, payload.revision
            )
    except (AccessDenied, ContentError, UnsafePath) as exc:
        raise _content_error(exc) from exc
    return RestoreResponse(path=path, restored_revision=payload.revision, commit=commit)


@router.get("/ai/history/{content_path:path}", response_model=list[RevisionResponse])
def get_page_history(
    content_path: str,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
):
    try:
        path = normalize_relative_path(content_path)
        with Session(request.app.state.engine) as session:
            return request.app.state.ai_service.page_history(session, user, path)
    except (AccessDenied, ContentError, UnsafePath) as exc:
        raise _content_error(exc) from exc


@router.get("/ai/content/{content_path:path}")
def get_content(
    content_path: str,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    download: bool = Query(False),
):
    try:
        path = normalize_relative_path(content_path)
        with Session(request.app.state.engine) as session:
            metadata, markdown, raw = request.app.state.ai_service.get_page(session, user, path)
    except (AccessDenied, ContentError, UnsafePath) as exc:
        raise _content_error(exc) from exc
    if download:
        return Response(
            content=raw,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": attachment_disposition(path.rsplit("/", 1)[-1])},
        )
    return {"path": path, "metadata": metadata, "markdown": markdown}


@router.post("/ai/books", response_model=CreatedResponse, status_code=201)
def create_book(
    payload: ContainerCreate,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
):
    try:
        return _created(
            request.app.state.ai_service.create_book(
                user,
                title=payload.title,
                slug=payload.slug,
            )
        )
    except AccessDenied as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required") from exc
    except (ContentError, UnsafePath) as exc:
        raise _content_error(exc) from exc


@router.post("/ai/books/{book_slug}/chapters", response_model=CreatedResponse, status_code=201)
def create_chapter(
    book_slug: str,
    payload: ContainerCreate,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
):
    try:
        return _created(
            request.app.state.ai_service.create_chapter(
                user,
                book_slug=make_slug(book_slug, book_slug),
                title=payload.title,
                slug=payload.slug,
            )
        )
    except AccessDenied as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required") from exc
    except (ContentError, UnsafePath) as exc:
        raise _content_error(exc) from exc


def _create_page(parent: str, payload: PageCreate, request: Request, user: User):
    try:
        parent = normalize_relative_path(parent)
        with Session(request.app.state.engine) as session:
            return _created(
                request.app.state.ai_service.create_page(
                    session,
                    user,
                    parent=parent,
                    title=payload.title,
                    slug=payload.slug,
                    markdown=payload.markdown,
                    tags=payload.tags,
                    draft=payload.draft,
                )
            )
    except (AccessDenied, ContentError, UnsafePath) as exc:
        raise _content_error(exc) from exc


@router.post("/ai/books/{book_slug}/pages", response_model=CreatedResponse, status_code=201)
def create_book_page(
    book_slug: str,
    payload: PageCreate,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
):
    try:
        parent = make_slug(book_slug, book_slug)
    except UnsafePath as exc:
        raise _content_error(exc) from exc
    return _create_page(parent, payload, request, user)


@router.post(
    "/ai/books/{book_slug}/chapters/{chapter_slug}/pages",
    response_model=CreatedResponse,
    status_code=201,
)
def create_chapter_page(
    book_slug: str,
    chapter_slug: str,
    payload: PageCreate,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
):
    try:
        parent = f"{make_slug(book_slug, book_slug)}/{make_slug(chapter_slug, chapter_slug)}"
    except UnsafePath as exc:
        raise _content_error(exc) from exc
    return _create_page(parent, payload, request, user)
