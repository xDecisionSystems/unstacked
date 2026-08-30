"""Administrator API for users, groups, memberships and path grants.

This router owns everything that *feeds* :mod:`app.acl` without ever
re-implementing it: groups, memberships and ``permissions`` rows go in here,
and ``resolve_access`` keeps deciding what they mean.

Three things are deliberate and easy to get wrong:

* **Both transports are supported.**  An administrator may act through the
  bearer-token API or the browser's cookie session, so the actor is resolved
  from whichever credential is present.  Cookie-authenticated state changes
  additionally require the CSRF token; bearer ones must not, because an
  ``Authorization`` header is never attached by the browser on its own.
* **The last active administrator is protected by the database, not by a
  read-then-write check.**  See :func:`_not_last_active_admin`.
* **Audit records go to the ordinary logging tree**, not to a table.  Content
  is files and history is Git; an audit table would be a fourth source of
  truth.  :func:`_audit` refuses field names that could carry a secret, so a
  password or token cannot reach a log line by accident.

Authorization is an inline ``is_admin`` check on every route.  T4.2 replaces
it with a central dependency; keeping the check in one helper
(:func:`get_admin_actor`) means that swap is a one-line change here.
"""

import base64
import logging
import re
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, not_, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from sqlmodel import Session, select

from app import backup_config, backup_runtime, branding, theme, theme_config
from app.acl import AccessPolicy, Rule, explain_access
from app.auth import bearer_scheme, get_current_user, hash_password
from app.backup_config import GIT_REMOTE, BackupTarget
from app.content import ContentConflict, ContentError, ContentRepository
from app.default_groups import (
    ADMIN_GROUP_NAME,
    PUBLIC_GROUP_NAME,
    copy_public_book_defaults,
    sync_admin_membership,
)
from app.git_backend import GitSyncError, scrub_git_output
from app.models import Group, Permission, User, UserGroup, normalize_path_prefix
from app.paths import (
    RESERVED_ROOT_NAMES,
    UnsafePath,
    normalize_relative_path,
    path_depth,
    safe_join,
)
from app.theme import Palette
from app.web_auth import get_current_web_user, invalidate_web_sessions, require_csrf

router = APIRouter(prefix="/api/admin", tags=["Administration"])

audit_log = logging.getLogger("unstacked.audit")

# Passwords are set by an administrator rather than mailed out, so the floor
# matches the bootstrap CLI's rather than the login form's shorter minimum.
MINIMUM_PASSWORD_LENGTH = 12
PRIMARY_ADMIN_USERNAME = "admin"

# Field names an audit record may never carry.  The audit trail records *who
# changed what*, and a value under any of these names would be either a
# credential or a content body.
FORBIDDEN_AUDIT_FIELD = re.compile(
    r"password|passwd|secret|token|hash|credential|markdown|body|content",
    re.IGNORECASE,
)


class UserCreate(BaseModel):
    # The login identifier `authenticate()` looks up (see app/auth.py) —
    # distinct from email, which is contact/audit information only.
    username: str = Field(min_length=1, max_length=200)
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=200)
    # There is no mail transport in this deployment model, so an administrator
    # sets the initial password directly and communicates it out of band. No
    # invitation tokens are minted here.
    password: str = Field(min_length=MINIMUM_PASSWORD_LENGTH, max_length=1024)
    is_admin: bool = False


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    is_admin: bool | None = None
    is_active: bool | None = None


class PasswordReset(BaseModel):
    password: str = Field(min_length=MINIMUM_PASSWORD_LENGTH, max_length=1024)


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    display_name: str
    is_admin: bool
    is_active: bool


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)


class GroupResponse(BaseModel):
    id: int
    name: str
    description: str


class PermissionCreate(BaseModel):
    group_id: int
    path_prefix: str = Field(min_length=1, max_length=500)
    can_read: bool = True
    can_write: bool = False


class PermissionResponse(BaseModel):
    id: int
    group_id: int
    path_prefix: str
    can_read: bool
    can_write: bool


class PermissionUpdate(BaseModel):
    """The access level for an existing, exact path grant."""

    can_read: bool
    can_write: bool = False


class BookResponse(BaseModel):
    """A book path available for assignment in the Settings matrix."""

    path: str


class HomeItemResponse(BaseModel):
    """One Git-versioned home-screen target available for exact grants."""

    path: str
    kind: Literal["book", "page"]


class OrphanedPermissionResponse(PermissionResponse):
    """A stored grant that can no longer match anything on disk."""

    reason: str


class RuleResponse(BaseModel):
    group_id: int
    prefix: str
    depth: int
    can_read: bool
    can_write: bool


class AccessExplanationResponse(BaseModel):
    """Why a user does or does not reach a path, for admin diagnostics only."""

    user_id: int
    path: str | None
    can_read: bool
    can_write: bool
    reason: str
    matching_rules: list[RuleResponse]
    decisive_rules: list[RuleResponse]


class BackupConfigUpdate(BaseModel):
    """A backup target as an administrator supplies it.

    Deliberately not length- or pattern-constrained on ``token``: a 422 body
    echoes the offending input, which for a credential is exactly the wrong
    place for it to appear.  The value is checked by ``configure_remote``,
    whose errors never contain it.
    """

    # Target-typed from the start, so an rsync or S3 variant is a new literal
    # rather than a redesign of the route.
    type: Literal["git-remote"] = GIT_REMOTE
    # Checked manually so FastAPI's validation body cannot echo a rejected URL
    # that happened to contain embedded credentials.
    url: str
    # A `content/` backup is the whole wiki, drafts included, with no per-user
    # ACL.  Nothing here can check privacy over the network, so the operator
    # affirms it and `configure_remote` refuses the target without it.
    confirmed_private: bool = False
    # HTTPS: either an inline token (stored by the app in its own owner-only
    # file) or the path of a token file the operator manages themselves.
    token: str | None = None
    token_path: str | None = Field(default=None, max_length=4096)
    # SSH: a deploy key plus the known_hosts entry its host key is pinned to.
    ssh_key_path: str | None = Field(default=None, max_length=4096)
    ssh_known_hosts_path: str | None = Field(default=None, max_length=4096)


class BackupConfigResponse(BaseModel):
    """Backup status for the admin UI: never a token, key, or its content."""

    configured: bool
    type: str
    url: str | None
    confirmed_private: bool
    requires_private_repository: bool
    # Which kind of credential is in place, not the credential or its path.
    # Changing a credential requires supplying it again; nothing is prefilled.
    credential: str
    # "file" once saved through this API, "environment" while the deployment's
    # variables are still the only source, "unset" when there is no target.
    source: str
    updated_at: str | None
    # Whether the sync worker and manual backup routes are live in this
    # process.  A saved target activates them without a restart.
    active: bool
    ahead_count: int | None = None
    last_success_at: str | None = None
    last_error: str | None = None
    retry_at: str | None = None
    requires_admin_action: bool = False


class DetailResponse(BaseModel):
    detail: str


class PaletteModel(BaseModel):
    """The five colors a palette is made of; see :mod:`app.theme`."""

    accent: str
    accent_secondary: str
    warm: str
    muted: str
    text: str


class PresetOption(BaseModel):
    key: str
    label: str
    palette: PaletteModel


class ThemeResponse(BaseModel):
    mode: Literal["preset", "custom"]
    preset: str | None
    palette: PaletteModel
    presets: list[PresetOption]
    updated_at: str | None


class ThemeUpdate(BaseModel):
    """Exactly one of ``preset`` or ``palette`` is used, chosen by ``mode``.

    Supplying both is refused rather than silently picking one -- the same
    "either X or Y, not both" shape as :class:`BackupConfigUpdate`.
    """

    mode: Literal["preset", "custom"]
    preset: str | None = None
    palette: PaletteModel | None = None


class BrandingResponse(BaseModel):
    name: str
    logo_url: str
    updated_at: str | None


class BrandingUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    logo_base64: str | None = Field(default=None, max_length=20_000_000)


# --------------------------------------------------------------------------
# Authorization
# --------------------------------------------------------------------------


def get_admin_actor(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> User:
    """Resolve an administrator from either transport.

    A bearer credential wins when present so an API client never falls back to
    a stale cookie in the same browser-driven test client.
    """

    user = get_current_user(request, credentials) if credentials else get_current_web_user(request)
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required")
    return user


async def require_admin_csrf(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> None:
    """Require a CSRF token only for the cookie-authenticated transport.

    ``Authorization`` headers are never attached automatically, so demanding a
    synchronizer token from an API client would reject every legitimate
    bearer request without preventing any attack.
    """

    if credentials is not None:
        return
    await require_csrf(request)


AdminActor = Annotated[User, Depends(get_admin_actor)]
CsrfGuard = [Depends(require_admin_csrf)]


def _audit(action: str, actor: User, **fields: object) -> None:
    """Record one administrative action, with no way to smuggle a secret in."""

    for name in fields:
        if FORBIDDEN_AUDIT_FIELD.search(name):
            raise ValueError(f"audit field {name!r} could carry a secret or content body")
    detail = " ".join(f"{name}={value}" for name, value in fields.items())
    audit_log.info(
        "%s actor_id=%s actor_email=%s%s",
        action,
        actor.id,
        actor.email,
        f" {detail}" if detail else "",
    )


# --------------------------------------------------------------------------
# Last-administrator protection
# --------------------------------------------------------------------------


def _not_last_active_admin(user_id: int):
    """A WHERE clause that is false exactly when ``user_id`` is the last admin.

    This must live *inside* the mutating statement rather than in a preceding
    ``SELECT``.  Python's ``sqlite3`` opens a deferred transaction only when
    the first DML statement runs, so a ``SELECT COUNT(*)`` in a route executes
    in autocommit and two concurrent demotions both read "2 admins" before
    either writes -- verified to leave zero administrators.  Folding the count
    into the UPDATE/DELETE makes it one statement evaluated under the write
    lock, so the loser of the race re-evaluates it against the winner's
    committed state and matches no rows.
    """

    other = aliased(User, name="other_admin")
    others = (
        select(other.id)
        .where(other.id != user_id)
        .where(other.is_admin.is_(True))
        .where(other.is_active.is_(True))
    )
    return or_(
        not_(User.is_admin),
        not_(User.is_active),
        others.exists(),
    )


def _last_admin_conflict() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        "Refusing to remove the last active administrator",
    )


# --------------------------------------------------------------------------
# Grant prefix validation
# --------------------------------------------------------------------------


def _target_kind(content: ContentRepository, prefix: str) -> str | None:
    """Name what a normalized prefix points at on disk, or ``None``."""

    if prefix.split("/")[0] in RESERVED_ROOT_NAMES:
        return None
    depth = path_depth(prefix)
    try:
        target = safe_join(content.docs, prefix)
    except UnsafePath:
        return None
    if depth == 1 and target.is_dir() and not prefix.endswith(".md"):
        return "book"
    if prefix == "index.md" and target.is_file():
        return "home"
    if (
        depth == 2
        and prefix.endswith(".md")
        and target.is_file()
        and prefix in content.home_items()
    ):
        return "featured_page"
    return None


def _normalize_grant_prefix(raw: str) -> str:
    """Repair what is repairable, then reject what could never match a path.

    Two normalizers apply, in this order and for different reasons.
    :func:`app.models.normalize_path_prefix` is the lenient one the model
    layer already runs: it *repairs* the spellings an administrator plausibly
    types (``/book/``, stray whitespace, a non-NFKC form) into the single form
    ACL matching compares against.  :func:`app.paths.normalize_relative_path`
    is the strict one every real content path is validated with, and it is
    applied second as a *rejection* filter: ``AccessPolicy.explain`` runs the
    requested path through it and denies anything it refuses, so a grant on a
    prefix that fails it -- ``.git``, a Windows-reserved name like ``nul`` --
    can never match any path the resolver will ever be asked about.  Storing
    such a grant would only ever be a dead row that looks live in the admin
    UI, so it is refused at creation instead.
    """

    try:
        repaired = normalize_path_prefix(raw)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    try:
        return normalize_relative_path(repaired)
    except UnsafePath as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"permission path prefix is not a usable content path: {exc}",
        ) from exc


def _orphan_reason(content: ContentRepository, row: Permission) -> str | None:
    """Why a stored grant matches nothing, or ``None`` when it is still live."""

    try:
        prefix = normalize_relative_path(normalize_path_prefix(row.path_prefix))
    except (UnsafePath, ValueError):
        return "malformed_prefix"
    if _target_kind(content, prefix) is None:
        return "missing_target"
    return None


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _content(request: Request) -> ContentRepository:
    return request.app.state.content


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
        is_active=user.is_active,
    )


def _group_response(group: Group) -> GroupResponse:
    return GroupResponse(id=group.id, name=group.name, description=group.description)


def _permission_response(row: Permission) -> PermissionResponse:
    return PermissionResponse(
        id=row.id,
        group_id=row.group_id,
        path_prefix=row.path_prefix,
        can_read=row.can_read,
        can_write=row.can_write,
    )


def _rule_response(rule: Rule) -> RuleResponse:
    return RuleResponse(
        group_id=rule.group_id,
        prefix=rule.prefix,
        depth=rule.depth,
        can_read=rule.can_read,
        can_write=rule.can_write,
    )


def _require_user(session: Session, user_id: int) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


def _require_group(session: Session, group_id: int) -> Group:
    group = session.get(Group, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    return group


# --------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=CsrfGuard,
)
def create_user(payload: UserCreate, request: Request, actor: AdminActor) -> UserResponse:
    # Exact match, not casefolded: authenticate() looks username up with a
    # plain equality comparison, so normalizing it here would let an admin
    # create an account the login form's own lookup could never find.
    username = payload.username
    email = str(payload.email).casefold()
    with Session(request.app.state.engine) as session:
        user = User(
            username=username,
            email=email,
            password_hash=hash_password(payload.password),
            display_name=payload.display_name,
            is_admin=payload.is_admin,
            # An administrator may choose a permanent password for a new
            # account. Bootstrap credentials remain the separate case that
            # must be replaced on first use.
            must_change_password=False,
        )
        session.add(user)
        try:
            session.flush()
            sync_admin_membership(session, user)
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT, "A user with that username or email already exists"
            ) from exc
        session.refresh(user)
        _audit(
            "admin.user.create",
            actor,
            user_id=user.id,
            username=username,
            email=email,
            is_admin=user.is_admin,
        )
        return _user_response(user)


@router.get("/users", response_model=list[UserResponse])
def list_users(request: Request, actor: AdminActor) -> list[UserResponse]:
    with Session(request.app.state.engine) as session:
        rows = session.exec(select(User).order_by(User.id)).all()
        return [_user_response(row) for row in rows]


@router.patch("/users/{user_id}", response_model=UserResponse, dependencies=CsrfGuard)
def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    actor: AdminActor,
) -> UserResponse:
    """Rename, (de)activate or (de)promote a user, never below one admin."""

    values = payload.model_dump(exclude_none=True)
    if not values:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No changes supplied")
    with Session(request.app.state.engine) as session:
        _require_user(session, user_id)
        statement = update(User).where(User.id == user_id)
        # Only a change that actually withdraws administrative power needs the
        # guard; without this a plain rename of the sole admin would be
        # refused by it.
        if values.get("is_admin") is False or values.get("is_active") is False:
            statement = statement.where(_not_last_active_admin(user_id))
        if session.execute(statement.values(**values)).rowcount == 0:
            session.rollback()
            raise _last_admin_conflict()
        user = _require_user(session, user_id)
        sync_admin_membership(session, user)
        session.commit()
        _audit("admin.user.update", actor, user_id=user_id, **values)
        return _user_response(user)


@router.post("/users/{user_id}/password", response_model=DetailResponse, dependencies=CsrfGuard)
def reset_password(
    user_id: int,
    payload: PasswordReset,
    request: Request,
    actor: AdminActor,
) -> DetailResponse:
    """Set a new password and retire every credential issued under the old one.

    Both generations move: ``session_generation`` kills outstanding browser
    cookies and ``api_token_generation`` kills outstanding bearer tokens.
    Bumping only one would leave the other transport authenticated as the very
    user whose account was just secured.
    """

    with Session(request.app.state.engine) as session:
        user = _require_user(session, user_id)
        user.password_hash = hash_password(payload.password)
        user.api_token_generation += 1
        # An admin-set password is a temporary credential communicated out of
        # band, same as at account creation — force the user to replace it.
        user.must_change_password = True
        session.add(user)
        session.commit()
        invalidate_web_sessions(session, user)
        _audit("admin.user.password_reset", actor, user_id=user_id, email=user.email)
    return DetailResponse(detail="Password reset; existing sessions and tokens revoked")


@router.delete("/users/{user_id}", response_model=DetailResponse, dependencies=CsrfGuard)
def delete_user(user_id: int, request: Request, actor: AdminActor) -> DetailResponse:
    with Session(request.app.state.engine) as session:
        user = _require_user(session, user_id)
        if user.username == PRIMARY_ADMIN_USERNAME:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "The primary Admin account cannot be deleted",
            )
        email = user.email
        statement = (
            delete(User).where(User.id == user_id).where(_not_last_active_admin(user_id))
        )
        if session.execute(statement).rowcount == 0:
            session.rollback()
            raise _last_admin_conflict()
        session.commit()
        _audit("admin.user.delete", actor, user_id=user_id, email=email)
    return DetailResponse(detail="User deleted")


# --------------------------------------------------------------------------
# Groups and memberships
# --------------------------------------------------------------------------


@router.post(
    "/groups",
    response_model=GroupResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=CsrfGuard,
)
def create_group(payload: GroupCreate, request: Request, actor: AdminActor) -> GroupResponse:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Group name must not be blank")
    if _public_repository_is_linked(request):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A group without read permissions cannot be created while the GitHub repository "
            "is public",
        )
    with Session(request.app.state.engine) as session:
        group = Group(name=name, description=payload.description)
        session.add(group)
        try:
            session.flush()
            copy_public_book_defaults(session, group)
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT, "A group with that name already exists"
            ) from exc
        session.refresh(group)
        _audit("admin.group.create", actor, group_id=group.id, name=name)
        return _group_response(group)


@router.get("/groups", response_model=list[GroupResponse])
def list_groups(request: Request, actor: AdminActor) -> list[GroupResponse]:
    with Session(request.app.state.engine) as session:
        rows = session.exec(select(Group).order_by(Group.id)).all()
        return [_group_response(row) for row in rows]


@router.delete("/groups/{group_id}", response_model=DetailResponse, dependencies=CsrfGuard)
def delete_group(group_id: int, request: Request, actor: AdminActor) -> DetailResponse:
    """Delete a group; memberships and grants go with it.

    No manual cleanup: both child tables declare ``ON DELETE CASCADE`` and
    ``create_db_engine`` turns ``PRAGMA foreign_keys`` on for every connection,
    so deleting the parent row is the whole operation.  Doing it by hand as
    well would only add a way for the two paths to disagree.
    """

    with Session(request.app.state.engine) as session:
        group = _require_group(session, group_id)
        name = group.name
        session.delete(group)
        session.commit()
        _audit("admin.group.delete", actor, group_id=group_id, name=name)
    return DetailResponse(detail="Group deleted")


@router.get("/groups/{group_id}/members", response_model=list[UserResponse])
def list_members(group_id: int, request: Request, actor: AdminActor) -> list[UserResponse]:
    with Session(request.app.state.engine) as session:
        _require_group(session, group_id)
        rows = session.exec(
            select(User)
            .join(UserGroup, UserGroup.user_id == User.id)
            .where(UserGroup.group_id == group_id)
            .order_by(User.id)
        ).all()
        return [_user_response(row) for row in rows]


@router.put(
    "/groups/{group_id}/members/{user_id}",
    response_model=DetailResponse,
    dependencies=CsrfGuard,
)
def add_member(
    group_id: int,
    user_id: int,
    request: Request,
    actor: AdminActor,
) -> DetailResponse:
    """Idempotent: re-adding an existing member is a success, not a conflict."""

    with Session(request.app.state.engine) as session:
        _require_group(session, group_id)
        _require_user(session, user_id)
        if session.get(UserGroup, (user_id, group_id)) is None:
            session.add(UserGroup(user_id=user_id, group_id=group_id))
            session.commit()
            _audit("admin.membership.add", actor, group_id=group_id, user_id=user_id)
    return DetailResponse(detail="User is a member of the group")


@router.delete(
    "/groups/{group_id}/members/{user_id}",
    response_model=DetailResponse,
    dependencies=CsrfGuard,
)
def remove_member(
    group_id: int,
    user_id: int,
    request: Request,
    actor: AdminActor,
) -> DetailResponse:
    with Session(request.app.state.engine) as session:
        _require_group(session, group_id)
        _require_user(session, user_id)
        membership = session.get(UserGroup, (user_id, group_id))
        if membership is not None:
            session.delete(membership)
            session.commit()
            _audit("admin.membership.remove", actor, group_id=group_id, user_id=user_id)
    return DetailResponse(detail="User is not a member of the group")


# --------------------------------------------------------------------------
# Permission grants
# --------------------------------------------------------------------------


@router.post(
    "/permissions",
    response_model=PermissionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=CsrfGuard,
)
def create_permission(
    payload: PermissionCreate,
    request: Request,
    actor: AdminActor,
) -> PermissionResponse:
    """Grant a group read/write on a book or featured page.

    The target has to exist now.  A grant on a path that has never existed is
    almost always a typo, and there is nothing else in the system that would
    ever tell the administrator so -- ``resolve_access`` simply never matches
    it.  Content deleted *later* is a different case and is surfaced by
    :func:`list_orphaned_permissions` rather than blocking anything.
    """

    if payload.can_write and not payload.can_read:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "A write grant requires read; deny both instead",
        )
    if not payload.can_read and _public_repository_is_linked(request):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A private GitHub repository is required for a group with restricted read access",
        )
    prefix = _normalize_grant_prefix(payload.path_prefix)
    kind = _target_kind(_content(request), prefix)
    if kind is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "No book or featured page exists at that path prefix",
        )
    with Session(request.app.state.engine) as session:
        _require_group(session, payload.group_id)
        row = Permission(
            group_id=payload.group_id,
            path_prefix=prefix,
            can_read=payload.can_read,
            can_write=payload.can_write,
        )
        session.add(row)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "That group already has a grant on that path prefix",
            ) from exc
        session.refresh(row)
        _audit(
            "admin.permission.create",
            actor,
            permission_id=row.id,
            group_id=row.group_id,
            path_prefix=row.path_prefix,
            target=kind,
            can_read=row.can_read,
            can_write=row.can_write,
        )
        return _permission_response(row)


@router.put(
    "/permissions/{permission_id}",
    response_model=PermissionResponse,
    dependencies=CsrfGuard,
)
def update_permission(
    permission_id: int,
    payload: PermissionUpdate,
    request: Request,
    actor: AdminActor,
) -> PermissionResponse:
    """Change a stored grant without a delete-and-recreate gap."""

    if payload.can_write and not payload.can_read:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "A write grant requires read; deny both instead",
        )
    if not payload.can_read and _public_repository_is_linked(request):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A private GitHub repository is required for a group with restricted read access",
        )
    with Session(request.app.state.engine) as session:
        row = session.get(Permission, permission_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Permission not found")
        row.can_read = payload.can_read
        row.can_write = payload.can_write
        session.add(row)
        session.commit()
        session.refresh(row)
        _audit(
            "admin.permission.update",
            actor,
            permission_id=row.id,
            group_id=row.group_id,
            path_prefix=row.path_prefix,
            can_read=row.can_read,
            can_write=row.can_write,
        )
        return _permission_response(row)


@router.get("/permissions", response_model=list[PermissionResponse])
def list_permissions(
    request: Request,
    actor: AdminActor,
    group_id: int | None = Query(default=None),
) -> list[PermissionResponse]:
    with Session(request.app.state.engine) as session:
        statement = select(Permission).order_by(Permission.id)
        if group_id is not None:
            statement = statement.where(Permission.group_id == group_id)
        return [_permission_response(row) for row in session.exec(statement).all()]


@router.get("/books", response_model=list[BookResponse])
def list_books(request: Request, actor: AdminActor) -> list[BookResponse]:
    """List every book an administrator can assign a group grant to."""

    with Session(request.app.state.engine) as session:
        return [
            BookResponse(path=book["slug"])
            for book in _content(request).tree(session, actor)
        ]


@router.get("/home-items", response_model=list[HomeItemResponse])
def list_home_items(request: Request, actor: AdminActor) -> list[HomeItemResponse]:
    """List curated home targets; only featured pages permit exact grants."""

    return [
        HomeItemResponse(path=path, kind="page" if path.endswith(".md") else "book")
        for path in _content(request).home_items()
    ]


@router.get("/permissions/orphaned", response_model=list[OrphanedPermissionResponse])
def list_orphaned_permissions(
    request: Request,
    actor: AdminActor,
) -> list[OrphanedPermissionResponse]:
    """Report grants whose target is gone, without touching them.

    Out-of-band edits to ``content/`` -- a book deleted or renamed with a text
    editor and a ``git commit`` -- leave rows that match nothing.  They are
    harmless to the resolver and misleading to a human, so they are reported
    for an administrator to delete deliberately rather than swept up
    automatically: an automatic cleanup would also erase a grant during the
    minutes a restore is in progress.
    """

    content = _content(request)
    with Session(request.app.state.engine) as session:
        admin_group = session.exec(
            select(Group).where(Group.name == ADMIN_GROUP_NAME)
        ).one_or_none()
        rows = session.exec(select(Permission).order_by(Permission.id)).all()
        return [
            OrphanedPermissionResponse(
                **_permission_response(row).model_dump(),
                reason=reason,
            )
            for row, reason in ((row, _orphan_reason(content, row)) for row in rows)
            if admin_group is None or row.group_id != admin_group.id
            if reason is not None
        ]


@router.delete(
    "/permissions/{permission_id}", response_model=DetailResponse, dependencies=CsrfGuard
)
def delete_permission(
    permission_id: int,
    request: Request,
    actor: AdminActor,
) -> DetailResponse:
    with Session(request.app.state.engine) as session:
        row = session.get(Permission, permission_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Permission not found")
        group_id, prefix = row.group_id, row.path_prefix
        session.delete(row)
        session.commit()
        _audit(
            "admin.permission.delete",
            actor,
            permission_id=permission_id,
            group_id=group_id,
            path_prefix=prefix,
        )
    return DetailResponse(detail="Permission deleted")


@router.get("/users/{user_id}/access", response_model=AccessExplanationResponse)
def explain_user_access(
    user_id: int,
    request: Request,
    actor: AdminActor,
    path: str = Query(min_length=1, max_length=500),
) -> AccessExplanationResponse:
    """Explain one user's effective access, including equal-specificity ties.

    ``AccessExplanation`` names every rule that matched and the subset that
    decided the outcome, which is what makes a cross-group tie ("two groups
    grant at the same depth and one denies") explainable instead of merely
    surprising.  It is exposed only here, behind the administrator check,
    because the rule list can name paths the caller cannot read.
    """

    with Session(request.app.state.engine) as session:
        user = _require_user(session, user_id)
        explanation = explain_access(session, user, path)
    return AccessExplanationResponse(
        user_id=user_id,
        path=explanation.path,
        can_read=explanation.decision.can_read,
        can_write=explanation.decision.can_write,
        reason=explanation.reason,
        matching_rules=[_rule_response(rule) for rule in explanation.matching_rules],
        decisive_rules=[_rule_response(rule) for rule in explanation.decisive_rules],
    )


# --------------------------------------------------------------------------
# Backup target configuration
# --------------------------------------------------------------------------
#
# A backup target is optional and stays optional: none of these routes is on
# any startup or request path, and "not configured" is a first-class answer
# rather than an error.  The record lives in a file under `data/` (see
# app/backup_config.py) rather than in a table, and the persisted record wins
# over the deployment's environment variables once it exists.
#
# A saved credential is never rendered back.  An inline token is written to its
# own owner-only file and only its *path* is stored, so there is no code path
# that could return the value even by accident.


# The credential protocol is line-oriented and `configure_remote` caps a token
# at this length anyway; refusing earlier avoids writing a large body to disk
# just to have it rejected.  The value never appears in the error.
MAX_BACKUP_TOKEN_CHARS = 512


def _public_repository_is_linked(request: Request) -> bool:
    target = backup_config.effective_target(request.app.state.settings)
    return target.configured and not target.confirmed_private


def _groups_restrict_read_access(session: Session, content: ContentRepository) -> bool:
    """Whether any group cannot read every currently addressable content target."""

    targets: list[str] = []
    for item in content.docs.rglob("*"):
        relative = item.relative_to(content.docs).as_posix()
        parts = relative.split("/")
        if "assets" in parts or any(part.startswith(".") for part in parts):
            continue
        depth = path_depth(relative)
        if (item.is_dir() and depth in {1, 2}) or (
            item.is_file() and item.suffix == ".md" and depth in {2, 3}
        ):
            targets.append(relative)
    for group in session.exec(select(Group)).all():
        # These are built-in roles, not restricted audiences: Public begins
        # empty by design, and Admin is already covered by the administrator
        # bypass. Their default state must not make every backup private.
        if group.name in {PUBLIC_GROUP_NAME, ADMIN_GROUP_NAME}:
            continue
        rows = session.exec(select(Permission).where(Permission.group_id == group.id)).all()
        if not any(row.can_read for row in rows):
            return True
        policy = AccessPolicy(
            is_admin=False,
            is_active=True,
            rules=tuple(
                Rule(
                    group_id=row.group_id,
                    prefix=row.path_prefix,
                    depth=path_depth(row.path_prefix),
                    can_read=row.can_read,
                    can_write=row.can_write,
                )
                for row in rows
            ),
        )
        if any(not policy.decide(target).can_read for target in targets):
            return True
    return False


def _backup_status_response(request: Request) -> BackupConfigResponse:
    settings = request.app.state.settings
    target = backup_config.effective_target(settings)
    worker = backup_runtime.status(request.app)
    # A target saved through this API but not wirable at the last startup (a
    # token file that has since been removed, say) is reported here rather than
    # having stopped the application from booting.
    startup_error = getattr(request.app.state.content, "backup_config_error", None)
    with Session(request.app.state.engine) as session:
        requires_private = _groups_restrict_read_access(session, _content(request))
    return BackupConfigResponse(
        configured=target.configured,
        type=target.type,
        url=scrub_git_output(target.url) if target.url is not None else None,
        confirmed_private=target.confirmed_private,
        requires_private_repository=requires_private,
        credential=target.credential,
        source=target.source,
        updated_at=target.updated_at,
        active=backup_runtime.is_active(request.app),
        ahead_count=worker.ahead_count if worker else None,
        last_success_at=worker.last_success_at if worker else None,
        last_error=(worker.last_error if worker else None) or startup_error,
        retry_at=worker.retry_at if worker else None,
        requires_admin_action=worker.requires_admin_action if worker else False,
    )


@router.get("/backup/config", response_model=BackupConfigResponse)
def read_backup_config(request: Request, actor: AdminActor) -> BackupConfigResponse:
    """Report the current backup target and its sync state, credentials aside."""

    return _backup_status_response(request)


@router.put("/backup/config", response_model=BackupConfigResponse, dependencies=CsrfGuard)
def update_backup_config(
    payload: BackupConfigUpdate,
    request: Request,
    actor: AdminActor,
) -> BackupConfigResponse:
    """Validate a backup target against the real repository, then persist it.

    ``configure_remote`` first validates the local configuration, then a
    read-only ``ls-remote`` probe verifies reachability and authentication
    without changing refs. Only after both succeed is anything persisted.

    A failure leaves the previous configuration in effect: both data files and
    the exact Git config/helper bytes are snapshotted and restored. This also
    preserves an operator-owned origin when no app target was configured.

    Supplying a filesystem path for a token or deploy key is deliberately
    allowed: it is the same capability the deployment's environment variables
    already grant, and it is available only to administrators, who are trusted
    operators in this application's model.
    """

    settings = request.app.state.settings
    content = _content(request)
    config_path = settings.backup_config_path
    managed_token = backup_config.managed_token_path(settings)

    if payload.token and payload.token_path:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Supply either a token value or a token file path, not both",
        )
    if payload.token and len(payload.token) > MAX_BACKUP_TOKEN_CHARS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"A backup token must be at most {MAX_BACKUP_TOKEN_CHARS} characters",
        )
    url = payload.url.strip()
    if not url or len(url) > 2000:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "A backup URL must contain between 1 and 2000 characters",
        )
    if not payload.confirmed_private:
        with Session(request.app.state.engine) as session:
            if _groups_restrict_read_access(session, content):
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "A private GitHub repository is required while groups have restricted "
                    "read access",
                )

    snapshot = backup_config.FileSnapshot(config_path, managed_token)
    try:
        with content.git.remote_configuration_transaction():
            if payload.token:
                backup_config.write_managed_token(managed_token, payload.token)
                token_path: Path | None = managed_token
            else:
                token_path = Path(payload.token_path) if payload.token_path else None
            target = BackupTarget(
                type=GIT_REMOTE,
                url=url,
                confirmed_private=payload.confirmed_private,
                token_path=token_path,
                ssh_key_path=Path(payload.ssh_key_path) if payload.ssh_key_path else None,
                ssh_known_hosts_path=(
                    Path(payload.ssh_known_hosts_path) if payload.ssh_known_hosts_path else None
                ),
            )
            content.git.configure_remote(target.remote_config())
            content.git.test_remote()
            stored = backup_config.save(config_path, target)
            if token_path != managed_token:
                # The target no longer uses the app-managed token file. Keep
                # this cleanup inside both snapshots so even an unlink failure
                # leaves the entire previous configuration in effect.
                backup_config.forget_managed_token(managed_token)
    except GitSyncError as exc:
        snapshot.undo()
        # These messages are written to be operator-actionable and are
        # credential-free by construction; scrubbed again in case a transport
        # echoed something back through them.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, scrub_git_output(str(exc))
        ) from None
    except Exception:
        snapshot.undo()
        raise

    content.backup_config_error = None
    # Lazy wiring: the worker, the manual-backup service and the
    # /api/admin/backup/* routes come up now, on an app that started with no
    # target configured.  No restart is required.
    backup_runtime.activate(request.app)
    _audit(
        "admin.backup.configure",
        actor,
        target_type=stored.type,
        url=scrub_git_output(stored.url or ""),
        confirmed_private=stored.confirmed_private,
        auth_method=stored.credential,
    )
    return _backup_status_response(request)


@router.delete("/backup/config", response_model=BackupConfigResponse, dependencies=CsrfGuard)
def clear_backup_config(request: Request, actor: AdminActor) -> BackupConfigResponse:
    """Return the app to the fully supported "no backup target" state.

    Idempotent: clearing a target that was never configured is a success.  A
    "no target" record is written rather than the file being deleted, so that
    an administrator's decision outranks a variable left set in the deployment
    instead of being undone by it at the next restart.  Removing
    ``data/backup_config.json`` by hand is how control goes back to the
    environment.
    """

    settings = request.app.state.settings
    content = _content(request)
    managed_token = backup_config.managed_token_path(settings)
    snapshot = backup_config.FileSnapshot(settings.backup_config_path, managed_token)
    previous = backup_config.effective_target(settings)
    try:
        with content.git.remote_configuration_transaction():
            if previous.configured:
                content.git.clear_configured_remote()
            stored = backup_config.clear(settings.backup_config_path)
            backup_config.forget_managed_token(managed_token)
    except Exception:
        snapshot.undo()
        raise
    backup_runtime.deactivate(request.app)
    content.backup_config_error = None
    _audit("admin.backup.clear", actor, target_type=stored.type)
    return _backup_status_response(request)


# --------------------------------------------------------------------------
# Web UI color palette
# --------------------------------------------------------------------------
#
# Cosmetic, not security-sensitive: unlike every other section in this file,
# these routes change what a page looks like, never who can reach it. The
# record lives in a file under `data/` (see app/theme_config.py) for the same
# reason the backup target does -- it is not wiki content and does not belong
# in a fifth table.


def _theme_response(request: Request) -> ThemeResponse:
    settings = request.app.state.settings
    state = theme_config.load(settings.theme_config_path)
    return ThemeResponse(
        mode=state.mode,
        preset=state.preset,
        palette=PaletteModel(**asdict(state.palette)),
        presets=[
            PresetOption(
                key=key, label=theme.PRESET_LABELS[key], palette=PaletteModel(**asdict(preset))
            )
            for key, preset in theme.PRESETS.items()
        ],
        updated_at=state.updated_at,
    )


@router.get("/theme", response_model=ThemeResponse)
def read_theme(request: Request, actor: AdminActor) -> ThemeResponse:
    return _theme_response(request)


@router.put("/theme", response_model=ThemeResponse, dependencies=CsrfGuard)
def update_theme(payload: ThemeUpdate, request: Request, actor: AdminActor) -> ThemeResponse:
    settings = request.app.state.settings
    if payload.mode == "preset":
        if payload.palette is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Supply a preset name, not a custom palette, for preset mode",
            )
        if not payload.preset or payload.preset not in theme.PRESETS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown palette preset")
        state = theme_config.save_preset(settings.theme_config_path, payload.preset)
    else:
        if payload.preset is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Supply a custom palette, not a preset name, for custom mode",
            )
        if payload.palette is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Custom mode requires a palette"
            )
        try:
            palette = Palette(**payload.palette.model_dump())
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        state = theme_config.save_custom(settings.theme_config_path, palette)
    _audit("admin.theme.update", actor, mode=state.mode, preset=state.preset or "custom")
    return _theme_response(request)


@router.get("/branding", response_model=BrandingResponse)
def read_branding(request: Request, actor: AdminActor) -> BrandingResponse:
    state = branding.load(request.app.state.settings.branding_config_path)
    return BrandingResponse(**state.__dict__)


@router.put("/branding", response_model=BrandingResponse, dependencies=CsrfGuard)
def update_branding(
    payload: BrandingUpdate, request: Request, actor: AdminActor
) -> BrandingResponse:
    settings = request.app.state.settings
    try:
        state = branding.save(settings.branding_config_path, name=payload.name)
        if payload.logo_base64:
            data = base64.b64decode(payload.logo_base64, validate=True)
            if len(data) > settings.max_upload_bytes:
                raise ValueError("Logo exceeds the configured upload size limit")
            state = branding.store_logo(
                settings.branding_config_path,
                data,
                max_pixels=settings.max_upload_pixels,
                max_dimension=settings.max_upload_dimension,
            )
    except (ValueError, TypeError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    _audit("admin.branding.update", actor)
    return BrandingResponse(**state.__dict__)


@router.post("/home/reset", response_model=DetailResponse, dependencies=CsrfGuard)
def reset_home_page(request: Request, actor: AdminActor) -> DetailResponse:
    """Discard the Home page's current body/widgets, restoring the starter.

    An explicit, admin-only action (the client is expected to confirm with
    the user first, since this discards any hand-authored edit) that goes
    through the ordinary :meth:`ContentRepository.update_home_page`
    blob-SHA commit path -- one Git commit authored by the admin, not a
    raw file overwrite.
    """

    try:
        commit = _content(request).reset_home_page_to_starter(actor)
    except ContentConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ContentError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    _audit("admin.home.reset", actor, commit=commit)
    return DetailResponse(detail=f"Home page reset to starter content ({commit[:12]})")
