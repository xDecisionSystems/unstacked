from dataclasses import dataclass

from sqlmodel import Session, select

from app.models import Permission, User, UserGroup
from app.paths import normalize_relative_path


@dataclass(frozen=True)
class AccessDecision:
    can_read: bool
    can_write: bool


def resolve_access(session: Session, user: User, raw_path: str) -> AccessDecision:
    path = normalize_relative_path(raw_path)
    if not user.is_active:
        return AccessDecision(False, False)
    if user.is_admin:
        return AccessDecision(True, True)
    group_ids = session.exec(select(UserGroup.group_id).where(UserGroup.user_id == user.id)).all()
    if not group_ids:
        return AccessDecision(False, False)
    rules = session.exec(select(Permission).where(Permission.group_id.in_(group_ids))).all()
    matching = [
        rule
        for rule in rules
        if path == rule.path_prefix or path.startswith(f"{rule.path_prefix}/")
    ]
    if not matching:
        return AccessDecision(False, False)
    max_depth = max(len(rule.path_prefix.split("/")) for rule in matching)
    specific = [rule for rule in matching if len(rule.path_prefix.split("/")) == max_depth]
    can_read = all(rule.can_read for rule in specific) and any(rule.can_read for rule in specific)
    can_write = (
        can_read
        and all(rule.can_write for rule in specific)
        and any(rule.can_write for rule in specific)
    )
    return AccessDecision(can_read, can_write)
