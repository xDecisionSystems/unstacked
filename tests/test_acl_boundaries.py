"""Small exhaustive checks for ACL matching boundaries.

These stay at the pure-policy layer: transport tests cover the routes, while
this matrix makes it hard to accidentally turn prefix matching into a string
prefix check during a future ACL refactor.
"""

from itertools import permutations, product

import pytest

from app.acl import AccessDecision, AccessPolicy, Rule


def _rule(prefix: str, *, group_id: int, read: bool, write: bool) -> Rule:
    return Rule(
        group_id=group_id,
        prefix=prefix,
        depth=len(prefix.split("/")),
        can_read=read,
        can_write=write,
    )


@pytest.mark.parametrize(
    "probe",
    (
        "book",
        "book/page.md",
        "book/chapter/page.md",
        "bookish/page.md",
        "book-archive/page.md",
        "book.page.md",
        "books/page.md",
    ),
)
def test_grant_prefix_matches_complete_path_segments_only(probe: str):
    policy = AccessPolicy(
        is_admin=False,
        is_active=True,
        rules=(_rule("book", group_id=1, read=True, write=True),),
    )

    assert policy.decide(probe) == AccessDecision(
        can_read=probe == "book" or probe.startswith("book/"),
        can_write=probe == "book" or probe.startswith("book/"),
    )


@pytest.mark.parametrize(
    ("ancestor", "exact"),
    tuple(
        product(
            ((False, False), (True, False), (True, True), (False, True)),
            ((False, False), (True, False), (True, True), (False, True)),
        )
    ),
)
def test_deeper_rule_determines_access_for_every_read_write_combination(
    ancestor: tuple[bool, bool], exact: tuple[bool, bool]
):
    """A deeper rule wins even when stale data says write without read."""

    policy = AccessPolicy(
        is_admin=False,
        is_active=True,
        rules=(
            _rule("docs", group_id=1, read=ancestor[0], write=ancestor[1]),
            _rule("docs/private", group_id=2, read=exact[0], write=exact[1]),
        ),
    )

    # The resolver must also enforce the invariant defensively: write is
    # never useful without read, even if a legacy row bypassed the DB check.
    assert policy.decide("docs/private/page.md") == AccessDecision(
        can_read=exact[0], can_write=exact[0] and exact[1]
    )


def test_equal_depth_conflict_is_order_independent_and_does_not_leak_to_siblings():
    rules = (
        _rule("manuals/internal", group_id=1, read=True, write=True),
        _rule("manuals/internal", group_id=2, read=False, write=False),
    )

    for ordered_rules in permutations(rules):
        policy = AccessPolicy(is_admin=False, is_active=True, rules=ordered_rules)
        assert policy.decide("manuals/internal/plan.md") == AccessDecision.denied()
        assert policy.decide("manuals/internal-notes/plan.md") == AccessDecision.denied()
        assert not policy.can_view_container("manuals/internal-notes")
