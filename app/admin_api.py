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

import logging
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, not_, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from sqlmodel import Session, select

from app.acl import Rule, explain_access
from app.auth import bearer_scheme, get_current_user, hash_password
from app.content import ContentRepository
from app.models import Group, Permission, User, UserGroup, normalize_path_prefix
from app.paths import (
    RESERVED_ROOT_NAMES,
    UnsafePath,
    normalize_relative_path,
    path_depth,
    safe_join,
)
from app.web_auth import get_current_web_user, invalidate_web_sessions, require_csrf

router = APIRouter(prefix="/api/admin", tags=["Administration"])

audit_log = logging.getLogger("unstacked.audit")

# Passwords are set by an administrator rather than mailed out, so the floor
# matches the bootstrap CLI's rather than the login form's shorter minimum.
MINIMUM_PASSWORD_LENGTH = 12

# Field names an audit record may never carry.  The audit trail records *who
# changed what*, and a value under any of these names would be either a
# credential or a content body.
FORBIDDEN_AUDIT_FIELD = re.compile(
    r"password|passwd|secret|token|hash|credential|markdown|body|content",
    re.IGNORECASE,
)


class UserCreate(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=200)
    # There is no mail transport in this deployment model, so an administrator
    # sets the initial password directly and communicates it out of band; the
    # recipient changes it afterwards.  No invitation tokens are minted here.
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


class DetailResponse(BaseModel):
    detail: str


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
    if depth > 3:
        return None
    try:
        target = safe_join(content.docs, prefix)
    except UnsafePath:
        return None
    if prefix.endswith(".md"):
        return "page" if depth in {2, 3} and target.is_file() else None
    if not target.is_dir():
        return None
    return "book" if depth == 1 else "chapter"


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
    email = str(payload.email).casefold()
    with Session(request.app.state.engine) as session:
        user = User(
            email=email,
            password_hash=hash_password(payload.password),
            display_name=payload.display_name,
            is_admin=payload.is_admin,
        )
        session.add(user)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT, "A user with that email already exists"
            ) from exc
        session.refresh(user)
        _audit("admin.user.create", actor, user_id=user.id, email=email, is_admin=user.is_admin)
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
        session.commit()
        _audit("admin.user.update", actor, user_id=user_id, **values)
        return _user_response(_require_user(session, user_id))


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
        session.add(user)
        session.commit()
        invalidate_web_sessions(session, user)
        _audit("admin.user.password_reset", actor, user_id=user_id, email=user.email)
    return DetailResponse(detail="Password reset; existing sessions and tokens revoked")


@router.delete("/users/{user_id}", response_model=DetailResponse, dependencies=CsrfGuard)
def delete_user(user_id: int, request: Request, actor: AdminActor) -> DetailResponse:
    with Session(request.app.state.engine) as session:
        email = _require_user(session, user_id).email
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
    with Session(request.app.state.engine) as session:
        group = Group(name=name, description=payload.description)
        session.add(group)
        try:
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
    """Grant a group read/write on one book, chapter or page.

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
    prefix = _normalize_grant_prefix(payload.path_prefix)
    kind = _target_kind(_content(request), prefix)
    if kind is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "No book, chapter, or page exists at that path prefix",
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
        rows = session.exec(select(Permission).order_by(Permission.id)).all()
        return [
            OrphanedPermissionResponse(
                **_permission_response(row).model_dump(),
                reason=reason,
            )
            for row, reason in ((row, _orphan_reason(content, row)) for row in rows)
            if reason is not None
        ]


@router.delete("/permissions/{permission_id}", response_model=DetailResponse, dependencies=CsrfGuard)
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
