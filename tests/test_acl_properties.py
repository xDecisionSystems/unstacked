"""Exhaustive invariants for the pure ACL resolver.

Hypothesis is not an application dependency, so these use small finite domains
instead.  The domains cover every read/write state (including stale impossible
``write=True, read=False`` rows), all three specificity depths, and all
permutations of an equal-specificity conflict.
"""

from itertools import permutations, product

import pytest

from app.acl import AccessDecision, AccessPolicy, Rule

ACCESS_STATES = ((False, False), (False, True), (True, False), (True, True))
PREFIXES = ("handbook", "handbook/team", "handbook/team/drafts")


def _rule(prefix: str, group_id: int, state: tuple[bool, bool]) -> Rule:
    return Rule(
        group_id=group_id,
        prefix=prefix,
        depth=len(prefix.split("/")),
        can_read=state[0],
        can_write=state[1],
    )


def _oracle(rules: tuple[Rule, ...], path: str) -> AccessDecision:
    matching = tuple(
        rule for rule in rules if path == rule.prefix or path.startswith(f"{rule.prefix}/")
    )
    if not matching:
        return AccessDecision.denied()
    depth = max(rule.depth for rule in matching)
    decisive = tuple(rule for rule in matching if rule.depth == depth)
    can_read = all(rule.can_read for rule in decisive)
    return AccessDecision(
        can_read=can_read,
        can_write=can_read and all(rule.can_write for rule in decisive),
    )


@pytest.mark.parametrize("states", tuple(product(ACCESS_STATES, repeat=len(PREFIXES))))
def test_resolution_matches_specificity_oracle_for_all_permission_states(
    states: tuple[tuple[bool, bool], ...],
):
    """Every deeper matching rule replaces ancestors for both read and write."""

    rules = tuple(
        _rule(prefix, index + 1, state)
        for index, (prefix, state) in enumerate(zip(PREFIXES, states, strict=True))
    )
    policy = AccessPolicy(is_admin=False, is_active=True, rules=rules)

    for path in (
        "handbook/page.md",
        "handbook/team/page.md",
        "handbook/team/drafts/page.md",
        "handbook-team/page.md",
    ):
        assert policy.decide(path) == _oracle(rules, path)


@pytest.mark.parametrize("states", tuple(product(ACCESS_STATES, repeat=3)))
def test_equal_depth_ties_are_order_independent_and_require_unanimous_allow(
    states: tuple[tuple[bool, bool], ...],
):
    """No group ordering can turn a same-depth denial into an allow."""

    rules = tuple(_rule("handbook/team", index + 1, state) for index, state in enumerate(states))
    expected = _oracle(rules, "handbook/team/page.md")

    for ordered in permutations(rules):
        policy = AccessPolicy(is_admin=False, is_active=True, rules=ordered)
        assert policy.decide("handbook/team/page.md") == expected

    assert expected.can_read is all(state[0] for state in states)
    assert expected.can_write is (expected.can_read and all(state[1] for state in states))


@pytest.mark.parametrize("states", tuple(product(ACCESS_STATES, repeat=2)))
def test_container_visibility_requires_an_effectively_readable_descendant(
    states: tuple[tuple[bool, bool], ...],
):
    """An ancestor is navigation-only and cannot be exposed by a denied child."""

    rules = (
        _rule("handbook/team", 1, states[0]),
        _rule("handbook/team/drafts", 2, states[1]),
    )
    policy = AccessPolicy(is_admin=False, is_active=True, rules=rules)

    expected = any(
        _oracle(rules, rule.prefix).can_read
        for rule in rules
        if rule.prefix.startswith("handbook/") and rule.can_read
    )
    assert policy.can_view_container("handbook") is expected
    assert not policy.can_view_container("handbook-notes")
