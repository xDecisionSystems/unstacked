from dataclasses import dataclass

from sqlmodel import Session, select

from app.models import Permission, User, UserGroup, normalize_path_prefix
from app.paths import UnsafePath, normalize_relative_path


@dataclass(frozen=True)
class AccessDecision:
    can_read: bool
    can_write: bool

    @staticmethod
    def denied() -> "AccessDecision":
        return AccessDecision(False, False)


@dataclass(frozen=True)
class Rule:
    prefix: str
    depth: int
    can_read: bool
    can_write: bool


@dataclass(frozen=True)
class AccessPolicy:
    """A user's effective rules, loaded once and reusable across many paths.

    Listing a tree evaluates every page, so the rules are fetched once rather
    than re-queried per path.
    """

    is_admin: bool
    is_active: bool
    rules: tuple[Rule, ...]

    def decide(self, raw_path: str) -> AccessDecision:
        if not self.is_active:
            return AccessDecision.denied()
        if self.is_admin:
            return AccessDecision(True, True)
        try:
            path = normalize_relative_path(raw_path)
        except UnsafePath:
            return AccessDecision.denied()
        matching = [
            rule
            for rule in self.rules
            if path == rule.prefix or path.startswith(f"{rule.prefix}/")
        ]
        if not matching:
            return AccessDecision.denied()
        max_depth = max(rule.depth for rule in matching)
        specific = [rule for rule in matching if rule.depth == max_depth]
        # Deny wins an equal-specificity tie across groups, and write never
        # outlives read.
        can_read = all(rule.can_read for rule in specific)
        can_write = can_read and all(rule.can_write for rule in specific)
        return AccessDecision(can_read, can_write)


def load_policy(session: Session, user: User) -> AccessPolicy:
    if not user.is_active or user.is_admin:
        return AccessPolicy(is_admin=user.is_admin, is_active=user.is_active, rules=())
    group_ids = session.exec(select(UserGroup.group_id).where(UserGroup.user_id == user.id)).all()
    if not group_ids:
        return AccessPolicy(is_admin=False, is_active=True, rules=())
    rows = session.exec(select(Permission).where(Permission.group_id.in_(group_ids))).all()
    rules = []
    for row in rows:
        try:
            prefix = normalize_path_prefix(row.path_prefix)
        except ValueError:
            # A prefix that cannot be normalized grants nothing rather than
            # matching something unintended.
            continue
        rules.append(
            Rule(
                prefix=prefix,
                depth=len(prefix.split("/")),
                can_read=row.can_read,
                can_write=row.can_write,
            )
        )
    return AccessPolicy(is_admin=False, is_active=True, rules=tuple(rules))


def resolve_access(session: Session, user: User, raw_path: str) -> AccessDecision:
    return load_policy(session, user).decide(raw_path)
