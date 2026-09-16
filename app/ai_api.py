import re
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from threading import Lock
from time import monotonic
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.openapi.utils import get_openapi
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool

from app.acl import AccessDenied, AuthorizationContext
from app.auth import (
    authenticate,
    bearer_scheme,
    client_identifier,
    create_api_token,
    get_current_user,
    revoke_all_api_tokens,
)
from app.content import ContentError, ContentExists, ContentMissing, CreatedContent, StoredAsset
from app.models import ApiToken, User
from app.paths import UnsafePath, make_slug, normalize_relative_path
from app.search import SearchError, SearchTimeout
from app.web_auth import get_current_web_user, require_csrf

router = APIRouter(prefix="/api", tags=["AI content"])

# Assets are served outside the /api prefix because ``app/render.py`` already
# rewrites Markdown image links onto a bare ``/assets/`` route; that contract
# is what makes a preview and a static build resolve the same link.
asset_router = APIRouter(tags=["Assets"])

# Characters safe to place inside a quoted Content-Disposition filename.
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]")

# ``ContentRepository`` is the final authority on the UTF-8 byte budget, but
# reject an obviously excessive JSON string before it reaches a filesystem or
# Git write.  This fixed transport ceiling intentionally matches the default
# configured page budget; deployments that lower the setting retain the
# stricter repository check.
MAX_PAGE_MARKDOWN_CHARS = 2_000_000
# A unified diff can contain both versions of a page.  Leave a small amount of
# room for file headers and context, but never stream an unbounded Git result
# into an API response.
DIFF_RESPONSE_OVERHEAD_BYTES = 65_536


class AIUserRateLimiter:
    """Bounded in-process throttle for authenticated AI content requests.

    The key is a persisted user id, never a bearer token or client IP.  Token
    rotation therefore cannot escape the limit, and users behind one proxy do
    not consume each other's budget.  A lock covers both housekeeping and the
    check/record operation so simultaneous requests cannot pass the same last
    available slot.
    """

    def __init__(self, requests: int, window_seconds: int = 60, max_keys: int = 10_000):
        self.requests = requests
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._requests: dict[int, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, user_id: int) -> None:
        now = monotonic()
        with self._lock:
            self._evict_expired(now)
            history = self._requests[user_id]
            while history and history[0] <= now - self.window_seconds:
                history.popleft()
            if len(history) >= self.requests:
                retry_after = max(1, int(history[0] + self.window_seconds - now) + 1)
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    "Too many AI API requests",
                    headers={"Retry-After": str(retry_after)},
                )
            history.append(now)

    def _evict_expired(self, now: float) -> None:
        if len(self._requests) < self.max_keys:
            return
        cutoff = now - self.window_seconds
        expired = [
            user_id
            for user_id, history in self._requests.items()
            if not history or history[-1] <= cutoff
        ]
        for user_id in expired:
            del self._requests[user_id]
        if len(self._requests) >= self.max_keys:
            oldest = min(self._requests, key=lambda user_id: self._requests[user_id][-1])
            del self._requests[oldest]


_ai_limiter_initialization_lock = Lock()


def _ai_limiter(request: Request) -> AIUserRateLimiter:
    """Get the app-local limiter without requiring a main.py wiring change."""

    limiter = getattr(request.app.state, "ai_user_limiter", None)
    if limiter is None:
        # ASGI apps may serve concurrent first requests.  Install exactly one
        # limiter for this app so those requests share a budget.
        with _ai_limiter_initialization_lock:
            limiter = getattr(request.app.state, "ai_user_limiter", None)
            if limiter is None:
                settings = request.app.state.settings
                limiter = AIUserRateLimiter(
                    settings.ai_requests_per_minute,
                    max_keys=settings.max_rate_limit_keys,
                )
                request.app.state.ai_user_limiter = limiter
    return limiter


def _disposition(kind: str, filename: str, fallback: str) -> str:
    fallback_name = SAFE_FILENAME_RE.sub("_", filename) or fallback
    encoded = quote(filename, safe="")
    return f"{kind}; filename=\"{fallback_name}\"; filename*=UTF-8''{encoded}"


def attachment_disposition(filename: str) -> str:
    """Build a Content-Disposition header that a hostile filename cannot break.

    Slugs cannot contain quotes, but files may also be hand-created in the
    content repository, so the name is sanitized rather than trusted.
    """

    return _disposition("attachment", filename, "page.md")


def inline_disposition(filename: str) -> str:
    """The same header, but for content meant to render rather than download.

    An image referenced by an ``<img>`` tag has to be served ``inline`` or the
    browser saves it instead of drawing it.  ``inline`` is only safe here
    because the response also carries ``nosniff`` and a media type re-derived
    from the bytes, so the browser cannot be talked into treating the body as
    a document.
    """

    return _disposition("inline", filename, "asset")


# Named presets rather than an arbitrary caller-supplied duration, so a
# script hitting this endpoint directly can't quietly mint a token that
# outlives every sane review window.
TOKEN_TTL_PRESETS: dict[str, int | None] = {
    "1h": 3_600,
    "1d": 86_400,
    "7d": 604_800,
    "30d": 2_592_000,
    "90d": 7_776_000,
    "never": None,
}
# A "never expiring" token still carries a real JWT `exp` -- decoding always
# requires one -- so it gets one far enough out to be, in practice, never.
# The `ApiToken` row's `expires_at` is what actually says "never" (`None`);
# this is purely an implementation detail of the token's own signature.
_NEVER_EXPIRES_JWT_HORIZON = timedelta(days=36_500)


class TokenRequest(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=1024)
    description: str = Field(default="", max_length=200)
    # Matches the endpoint's prior fixed-TTL behavior for any caller that
    # omits this field, so an existing script's tokens don't silently start
    # living longer than before.
    expires_in: Literal["1h", "1d", "7d", "30d", "90d", "never"] = "1h"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int | None
    token_id: int
    description: str
    issued_at: datetime
    expires_at: datetime | None


class RevokeTokensRequest(BaseModel):
    """Optionally select another user whose machine credentials to revoke.

    Omitting ``user_id`` always means the bearer-token caller.  Selecting a
    different account is an administrator-only security operation.
    """

    user_id: int | None = Field(default=None, gt=0)


class RevokeTokensResponse(BaseModel):
    user_id: int
    api_token_generation: int


class ApiTokenResponse(BaseModel):
    id: int
    description: str
    issued_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None


class ContainerCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=200)


class PageCreate(ContainerCreate):
    markdown: str = Field(default="", max_length=MAX_PAGE_MARKDOWN_CHARS)
    tags: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list,
        max_length=100,
    )
    draft: bool = False
    card_image: str | None = Field(default=None, max_length=500)


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


class AssetResponse(BaseModel):
    """Where an asset landed, described the way a page will need to link to it."""

    path: str
    book: str
    filename: str
    media_type: str
    width: int
    height: int
    size_bytes: int
    commit: str


class AssetListResponse(BaseModel):
    book: str
    assets: list[str]


class DeletedAssetResponse(BaseModel):
    path: str
    commit: str


class SearchResultResponse(BaseModel):
    path: str
    title: str
    tags: list[str]
    snippet: str


class SearchPageResponse(BaseModel):
    items: list[SearchResultResponse]
    page: int
    page_size: int
    total: int
    truncated: bool


def _created(value: CreatedContent) -> CreatedResponse:
    return CreatedResponse(**value.__dict__)


def _content_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ContentExists):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, (AccessDenied, ContentMissing, UnsafePath)):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Content not found")
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


def _authorization(request: Request, session: Session, user: User) -> AuthorizationContext:
    """Construct the mandatory service authorization context for this request."""

    return AuthorizationContext(session, user)


def build_ai_openapi_schema(public_base_url: str | None) -> dict:
    """A provider-neutral OpenAPI document scoped to just the AI content surface.

    The whole app's own ``/openapi.json`` also carries the browser UI, the
    admin console, and backup/auth-cookie routes — none of that belongs in
    front of an AI client, and the combined operation count comfortably
    exceeds what a ChatGPT Action accepts in one schema. This document is
    built straight from ``router``'s own route objects (not `app.routes`,
    whose shape is a FastAPI-internal detail this file should not depend on)
    filtered to the ``/api/ai/`` paths, so it can never drift from what those
    routes actually accept and return.

    ``/auth/token`` and ``/auth/tokens/revoke`` are deliberately excluded: an
    Action is configured with one bearer token obtained out of band, not by
    calling a credential-issuing endpoint as one of its own operations.
    """

    ai_routes = [route for route in router.routes if route.path.startswith("/api/ai/")]
    schema = get_openapi(
        title="Unstacked AI Content API",
        version="0.1.0",
        description=(
            "Permission-aware read, search, and create access to a "
            "Git-backed Markdown wiki, scoped to what an AI agent may call. "
            "Every operation requires `Authorization: Bearer <token>` "
            "obtained separately from `POST /api/auth/token`."
        ),
        routes=ai_routes,
    )
    if public_base_url:
        schema["servers"] = [{"url": public_base_url}]
    return schema


def get_rate_limited_ai_user(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Authenticate then account for one AI content request for this user."""

    if user.id is None:  # Defensive: ``get_current_user`` only returns persisted users.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid bearer token")
    _ai_limiter(request).check(user.id)
    return user


def _bounded_diff(diff: str, max_page_bytes: int) -> str:
    """Refuse a Git diff that would exceed the REST response budget.

    The content layer already limits each current page, but Git history may
    contain older oversized files.  Measuring encoded bytes (rather than
    Python characters) makes the response limit hold for non-ASCII content.
    """

    limit = (max_page_bytes * 2) + DIFF_RESPONSE_OVERHEAD_BYTES
    if len(diff.encode("utf-8")) > limit:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "Diff exceeds the configured response size limit",
        )
    return diff


async def _csrf_for_cookie_token_action(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> None:
    if credentials is None:
        await require_csrf(request)


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
        ttl_seconds = TOKEN_TTL_PRESETS[payload.expires_in]
        issued_at = datetime.now(timezone.utc)
        expires_at = None if ttl_seconds is None else issued_at + timedelta(seconds=ttl_seconds)
        jti = str(uuid4())
        record = ApiToken(
            user_id=user.id,
            jti=jti,
            description=payload.description.strip(),
            issued_at=issued_at,
            expires_at=expires_at,
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        token = create_api_token(
            user,
            settings,
            jti=jti,
            expires_at=expires_at or (issued_at + _NEVER_EXPIRES_JWT_HORIZON),
        )
    return TokenResponse(
        access_token=token,
        expires_in=ttl_seconds,
        token_id=record.id,
        description=record.description,
        issued_at=record.issued_at,
        expires_at=record.expires_at,
    )


@router.get("/auth/tokens", response_model=list[ApiTokenResponse])
def list_api_tokens(
    request: Request,
    user_id: Annotated[int | None, Query(gt=0)] = None,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> list[ApiTokenResponse]:
    """List one account's issued tokens, newest first.

    Omitting ``user_id`` means the caller's own tokens; viewing another
    account's is an administrator-only operation, matching ``tokens/revoke``.
    """

    caller = (
        get_current_user(request, credentials) if credentials else get_current_web_user(request)
    )
    target_id = user_id if user_id is not None else caller.id
    if target_id != caller.id and not caller.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required")
    with Session(request.app.state.engine) as session:
        rows = session.exec(
            select(ApiToken)
            .where(ApiToken.user_id == target_id)
            .order_by(ApiToken.issued_at.desc())
        ).all()
        return [
            ApiTokenResponse(
                id=row.id,
                description=row.description,
                issued_at=row.issued_at,
                expires_at=row.expires_at,
                revoked_at=row.revoked_at,
            )
            for row in rows
        ]


@router.post(
    "/auth/tokens/{token_id}/revoke",
    response_model=ApiTokenResponse,
    dependencies=[Depends(_csrf_for_cookie_token_action)],
)
def revoke_one_api_token(
    token_id: int,
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> ApiTokenResponse:
    """Revoke exactly one token, leaving every other token for the account valid.

    The coarser ``/auth/tokens/revoke`` bumps the account generation and kills
    everything at once; this only marks one ``ApiToken`` row, so disconnecting
    one integration (a leaked or retired GPT token, say) doesn't also log out
    every other one.
    """

    caller = (
        get_current_user(request, credentials) if credentials else get_current_web_user(request)
    )
    with Session(request.app.state.engine) as session:
        record = session.get(ApiToken, token_id)
        if record is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Token not found")
        if record.user_id != caller.id and not caller.is_admin:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required")
        if record.revoked_at is None:
            record.revoked_at = datetime.now(timezone.utc)
            session.add(record)
            session.commit()
            session.refresh(record)
        return ApiTokenResponse(
            id=record.id,
            description=record.description,
            issued_at=record.issued_at,
            expires_at=record.expires_at,
            revoked_at=record.revoked_at,
        )


@router.post(
    "/auth/tokens/revoke",
    response_model=RevokeTokensResponse,
    dependencies=[Depends(_csrf_for_cookie_token_action)],
)
def revoke_api_tokens(
    payload: RevokeTokensRequest,
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> RevokeTokensResponse:
    """Invalidate every bearer token issued to one account, all at once.

    Advancing the account generation invalidates every signed token for that
    account, including any minted with no ``ApiToken`` row at all. See
    ``revoke_api_token`` below to kill just one token instead.  A user can
    revoke their own tokens; only an administrator may revoke another user's.
    """

    user = get_current_user(request, credentials) if credentials else get_current_web_user(request)
    target_id = payload.user_id if payload.user_id is not None else user.id
    if target_id is None:  # Defensive: authenticated users always have an id.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid bearer token")
    if target_id != user.id and not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required")

    with Session(request.app.state.engine) as session:
        target = session.get(User, target_id)
        if target is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
        revoke_all_api_tokens(session, target)
        session.add(target)
        session.commit()
        session.refresh(target)
        return RevokeTokensResponse(
            user_id=target.id,
            api_token_generation=target.api_token_generation,
        )


@router.get("/ai/openapi.json", include_in_schema=False)
def ai_openapi_schema(request: Request) -> dict:
    """The AI-only OpenAPI document — what a ChatGPT Action should import.

    Deliberately unauthenticated: the schema describes the API's shape, not
    any wiki content, and an Action needs to fetch it before it has a bearer
    token configured. Every operation it documents still requires one.
    """

    return build_ai_openapi_schema(request.app.state.settings.public_base_url)


@router.get("/ai/tree")
def get_tree(request: Request, user: Annotated[User, Depends(get_rate_limited_ai_user)]):
    with Session(request.app.state.engine) as session:
        return {"books": request.app.state.ai_service.tree(_authorization(request, session, user))}


@router.get("/ai/search", response_model=SearchPageResponse)
def search_content(
    request: Request,
    user: Annotated[User, Depends(get_rate_limited_ai_user)],
    query: str = Query(),
    page: int = Query(1),
    page_size: int | None = Query(None),
) -> SearchPageResponse:
    """Search content through the shared, ACL-filtering service contract."""

    try:
        with Session(request.app.state.engine) as session:
            result = request.app.state.ai_service.search(
                _authorization(request, session, user),
                query,
                page=page,
                page_size=page_size,
            )
    except SearchTimeout as exc:
        raise HTTPException(status.HTTP_408_REQUEST_TIMEOUT, "Search timed out") from exc
    except SearchError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return SearchPageResponse(
        items=[
            SearchResultResponse(
                path=item.path,
                title=item.title,
                tags=list(item.tags),
                snippet=item.snippet,
            )
            for item in result.items
        ],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
        truncated=result.truncated,
    )


@router.get("/ai/export")
def download_export(request: Request, user: Annotated[User, Depends(get_rate_limited_ai_user)]):
    try:
        with Session(request.app.state.engine) as session:
            archive = request.app.state.ai_service.export(_authorization(request, session, user))
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
    user: Annotated[User, Depends(get_rate_limited_ai_user)],
    from_revision: str = Query(min_length=7, max_length=64, pattern=r"^[0-9a-fA-F]+$"),
    to_revision: str = Query(min_length=7, max_length=64, pattern=r"^[0-9a-fA-F]+$"),
):
    try:
        path = normalize_relative_path(content_path)
        with Session(request.app.state.engine) as session:
            diff = request.app.state.ai_service.page_diff(
                _authorization(request, session, user), path, from_revision, to_revision
            )
    except (AccessDenied, ContentError, UnsafePath) as exc:
        raise _content_error(exc) from exc
    return DiffResponse(
        path=path,
        from_revision=from_revision,
        to_revision=to_revision,
        diff=_bounded_diff(diff, request.app.state.settings.max_page_bytes),
    )


@router.post("/ai/history/{content_path:path}/restore", response_model=RestoreResponse)
def restore_page_revision(
    content_path: str,
    payload: RestoreRequest,
    request: Request,
    user: Annotated[User, Depends(get_rate_limited_ai_user)],
):
    try:
        path = normalize_relative_path(content_path)
        with Session(request.app.state.engine) as session:
            commit = request.app.state.ai_service.restore_page(
                _authorization(request, session, user), path, payload.revision
            )
    except (AccessDenied, ContentError, UnsafePath) as exc:
        raise _content_error(exc) from exc
    return RestoreResponse(path=path, restored_revision=payload.revision, commit=commit)


@router.get("/ai/history/{content_path:path}", response_model=list[RevisionResponse])
def get_page_history(
    content_path: str,
    request: Request,
    user: Annotated[User, Depends(get_rate_limited_ai_user)],
):
    try:
        path = normalize_relative_path(content_path)
        with Session(request.app.state.engine) as session:
            return request.app.state.ai_service.page_history(
                _authorization(request, session, user), path
            )
    except (AccessDenied, ContentError, UnsafePath) as exc:
        raise _content_error(exc) from exc


@router.get("/ai/content/{content_path:path}")
def get_content(
    content_path: str,
    request: Request,
    user: Annotated[User, Depends(get_rate_limited_ai_user)],
    download: bool = Query(False),
):
    try:
        path = normalize_relative_path(content_path)
        with Session(request.app.state.engine) as session:
            metadata, markdown, raw = request.app.state.ai_service.get_page(
                _authorization(request, session, user), path
            )
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
    user: Annotated[User, Depends(get_rate_limited_ai_user)],
):
    try:
        with Session(request.app.state.engine) as session:
            return _created(
                request.app.state.ai_service.create_book(
                    _authorization(request, session, user),
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
                    _authorization(request, session, user),
                    parent=parent,
                    title=payload.title,
                    slug=payload.slug,
                    markdown=payload.markdown,
                    tags=payload.tags,
                    draft=payload.draft,
                    card_image=payload.card_image,
                )
            )
    except (AccessDenied, ContentError, UnsafePath) as exc:
        raise _content_error(exc) from exc


@router.post("/ai/books/{book_slug}/pages", response_model=CreatedResponse, status_code=201)
def create_book_page(
    book_slug: str,
    payload: PageCreate,
    request: Request,
    user: Annotated[User, Depends(get_rate_limited_ai_user)],
):
    try:
        parent = make_slug(book_slug, book_slug)
    except UnsafePath as exc:
        raise _content_error(exc) from exc
    return _create_page(parent, payload, request, user)


def _asset(value: StoredAsset) -> AssetResponse:
    return AssetResponse(**value.__dict__)


def _store_asset(request: Request, user: User, book_slug: str, filename: str, data: bytes):
    """The blocking half of an upload: ACL check, signature check, git commit."""

    try:
        with Session(request.app.state.engine) as session:
            return _asset(
                request.app.state.ai_service.upload_asset(
                    _authorization(request, session, user),
                    book_slug=book_slug,
                    filename=filename,
                    data=data,
                )
            )
    except (AccessDenied, ContentError, UnsafePath) as exc:
        raise _content_error(exc) from exc


@router.post("/ai/books/{book_slug}/assets", response_model=AssetResponse, status_code=201)
async def upload_asset(
    book_slug: str,
    request: Request,
    user: Annotated[User, Depends(get_rate_limited_ai_user)],
    file: Annotated[UploadFile, File()],
):
    """Accept one image for a book, identified by its bytes rather than its name.

    ``UploadSizeLimitMiddleware`` has already bounded the request body, so the
    read below cannot be the thing that exhausts memory.  It still reads one
    byte past the budget and checks, because a route must not depend on a
    middleware someone could forget to install for its own safety property.
    """

    limit = request.app.state.settings.max_upload_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "Upload exceeds the configured size limit",
        )
    # Git and the filesystem are blocking; keep them off the event loop.
    return await run_in_threadpool(
        _store_asset, request, user, book_slug, file.filename or "", data
    )


@router.get("/ai/books/{book_slug}/assets", response_model=AssetListResponse)
def list_assets(
    book_slug: str,
    request: Request,
    user: Annotated[User, Depends(get_rate_limited_ai_user)],
):
    try:
        with Session(request.app.state.engine) as session:
            assets = request.app.state.ai_service.list_assets(
                _authorization(request, session, user), book_slug
            )
    except (AccessDenied, ContentError, UnsafePath) as exc:
        raise _content_error(exc) from exc
    return AssetListResponse(book=book_slug, assets=assets)


@router.delete("/ai/books/{book_slug}/assets/{filename}", response_model=DeletedAssetResponse)
def delete_asset(
    book_slug: str,
    filename: str,
    request: Request,
    user: Annotated[User, Depends(get_rate_limited_ai_user)],
):
    try:
        with Session(request.app.state.engine) as session:
            commit = request.app.state.ai_service.delete_asset(
                _authorization(request, session, user),
                book_slug=book_slug,
                filename=filename,
            )
    except (AccessDenied, ContentError, UnsafePath) as exc:
        raise _content_error(exc) from exc
    return DeletedAssetResponse(path=f"assets/{book_slug}/{filename}", commit=commit)


@asset_router.get("/assets/{asset_path:path}", include_in_schema=False)
def serve_asset(
    asset_path: str,
    request: Request,
    user: Annotated[User, Depends(get_rate_limited_ai_user)],
):
    """Serve one asset for the live preview only.

    A static build never reaches this route: MkDocs copies ``docs/assets/``
    into the site and the page's own relative ``<img src>`` resolves to that
    file directly.  This exists so the same Markdown also renders while the
    app is running, where the file is behind an ACL.

    ``app/render.py`` prefixes every non-Markdown link with ``/assets/``, so a
    docs-relative ``assets/book/logo.png`` arrives here doubled.  Both spellings
    are accepted; they cannot be ambiguous because ``assets`` is a reserved
    name that no book may take.
    """

    try:
        normalized = normalize_relative_path(asset_path)
        if not normalized.startswith("assets/"):
            normalized = f"assets/{normalized}"
        with Session(request.app.state.engine) as session:
            asset = request.app.state.ai_service.get_asset(
                _authorization(request, session, user), normalized
            )
    except (AccessDenied, ContentError, UnsafePath) as exc:
        raise _content_error(exc) from exc
    return Response(
        content=asset.data,
        # The type comes from the file's own signature, never from its
        # extension, so a mislabelled file cannot pick its own media type.
        media_type=asset.media_type,
        headers={
            "Content-Disposition": inline_disposition(asset.filename),
            # Without this a browser may sniff the body and honour what it
            # finds instead of the type sent, which is the whole mechanism a
            # polyglot upload relies on.
            "X-Content-Type-Options": "nosniff",
            # Defence in depth: even if a future format slipped past the
            # allowlist, nothing in it may load or execute.
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Referrer-Policy": "no-referrer",
            # Assets are permission-controlled, so a shared cache must not
            # keep one and hand it to a different user.
            "Cache-Control": "private, max-age=0, must-revalidate",
        },
    )
