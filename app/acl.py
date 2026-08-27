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
    group_id: int
    prefix: str
    depth: int
    can_read: bool
    can_write: bool


@dataclass(frozen=True)
class AccessExplanation:
    """Deterministic, internal-only detail behind an ACL decision.

    This object is deliberately a Python service result rather than an API
    response.  Permission rules can reveal private paths, so callers must
    only surface it after their own administrator authorization check.
    """

    path: str | None
    decision: AccessDecision
    reason: str
    matching_rules: tuple[Rule, ...]
    decisive_rules: tuple[Rule, ...]


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
        return self.explain(raw_path).decision

    def explain(self, raw_path: str) -> AccessExplanation:
        """Explain an access decision without querying or mutating storage.

        ``load_policy`` snapshots the user's rules once; this method remains
        pure so tree walks and admin diagnostics use identical semantics.
        """

        if not self.is_active:
            return AccessExplanation(
                path=None,
                decision=AccessDecision.denied(),
                reason="inactive_user",
                matching_rules=(),
                decisive_rules=(),
            )
        if self.is_admin:
            return AccessExplanation(
                path=None,
                decision=AccessDecision(True, True),
                reason="admin_bypass",
                matching_rules=(),
                decisive_rules=(),
            )
        try:
            path = normalize_relative_path(raw_path)
        except UnsafePath:
            return AccessExplanation(
                path=None,
                decision=AccessDecision.denied(),
                reason="unsafe_path",
                matching_rules=(),
                decisive_rules=(),
            )
        matching = tuple(
            rule
            for rule in self.rules
            if path == rule.prefix or path.startswith(f"{rule.prefix}/")
        )
        if not matching:
            return AccessExplanation(
                path=path,
                decision=AccessDecision.denied(),
                reason="default_deny",
                matching_rules=(),
                decisive_rules=(),
            )
        max_depth = max(rule.depth for rule in matching)
        specific = tuple(rule for rule in matching if rule.depth == max_depth)
        # Deny wins an equal-specificity tie across groups, and write never
        # outlives read.
        can_read = all(rule.can_read for rule in specific)
        can_write = can_read and all(rule.can_write for rule in specific)
        if not can_read:
            reason = "read_denied_at_greatest_specificity"
        elif not can_write:
            reason = "write_denied_at_greatest_specificity"
        else:
            reason = "allowed"
        return AccessExplanation(
            path=path,
            decision=AccessDecision(can_read, can_write),
            reason=reason,
            matching_rules=matching,
            decisive_rules=specific,
        )

    def can_view_container(self, raw_path: str) -> bool:
        """Whether a navigation container is needed for a readable child.

        This deliberately does *not* change ``decide``: a visible ancestor is
        only navigation metadata and never grants read access to a page body
        at that ancestor path.
        """

        if not self.is_active:
            return False
        if self.is_admin:
            return True
        try:
            path = normalize_relative_path(raw_path)
        except UnsafePath:
            return False
        if self.decide(path).can_read:
            return True
        return any(
            rule.can_read
            and rule.prefix.startswith(f"{path}/")
            and self.decide(rule.prefix).can_read
            for rule in self.rules
        )


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
                group_id=row.group_id,
                prefix=prefix,
                depth=len(prefix.split("/")),
                can_read=row.can_read,
                can_write=row.can_write,
            )
        )
    return AccessPolicy(
        is_admin=False,
        is_active=True,
        rules=tuple(sorted(rules, key=lambda rule: (rule.prefix, rule.group_id))),
    )


def resolve_access(session: Session, user: User, raw_path: str) -> AccessDecision:
    return load_policy(session, user).decide(raw_path)


def explain_access(session: Session, user: User, raw_path: str) -> AccessExplanation:
    """Return diagnostic information for an already-authorized admin caller."""

    return load_policy(session, user).explain(raw_path)
