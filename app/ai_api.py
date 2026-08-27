from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlmodel import Session

from app.ai_service import AccessDenied
from app.auth import authenticate, create_api_token, get_current_user
from app.content import ContentError, ContentExists, ContentMissing, CreatedContent
from app.models import User
from app.paths import UnsafePath, make_slug, normalize_relative_path

router = APIRouter(prefix="/api", tags=["AI content"])


class TokenRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=1024)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


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
    client_host = request.client.host if request.client else "unknown"
    request.app.state.login_limiter.check(f"{client_host}:{str(payload.email).casefold()}")
    with Session(request.app.state.engine) as session:
        user = authenticate(session, str(payload.email), payload.password)
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
        token = create_api_token(user, request.app.state.settings)
    return TokenResponse(
        access_token=token,
        expires_in=request.app.state.settings.api_token_ttl_seconds,
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
        filename = path.rsplit("/", 1)[-1]
        return Response(
            content=raw,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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
