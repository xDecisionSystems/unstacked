"""Throttling must identify the real caller and stay bounded in memory."""

import pytest
from fastapi import HTTPException

from app.auth import LoginRateLimiter, client_identifier


class _FakeClient:
    def __init__(self, host: str):
        self.host = host


class _FakeRequest:
    def __init__(self, host: str, forwarded: str | None = None):
        self.client = _FakeClient(host)
        self.headers = {"x-forwarded-for": forwarded} if forwarded else {}


def test_direct_connections_use_the_socket_peer():
    request = _FakeRequest("203.0.113.7")
    assert client_identifier(request, trusted_proxy_hops=0) == "203.0.113.7"


def test_forwarded_header_is_ignored_without_configured_proxies():
    """Otherwise any client could spoof its way into a fresh bucket."""

    request = _FakeRequest("203.0.113.7", forwarded="1.2.3.4")
    assert client_identifier(request, trusted_proxy_hops=0) == "203.0.113.7"


def test_one_proxy_hop_reads_the_client_the_proxy_recorded():
    """With a single trusted proxy the last entry is the one it appended."""

    request = _FakeRequest("10.0.0.1", forwarded="198.51.100.9")
    assert client_identifier(request, trusted_proxy_hops=1) == "198.51.100.9"


def test_two_proxy_hops_skip_both_proxies():
    request = _FakeRequest("10.0.0.1", forwarded="198.51.100.9, 10.0.0.2")
    assert client_identifier(request, trusted_proxy_hops=2) == "198.51.100.9"


def test_client_supplied_entries_beyond_the_trusted_hops_are_ignored():
    """A client prepending its own hop must not escape into a fresh bucket."""

    request = _FakeRequest("10.0.0.1", forwarded="spoofed-by-client, 198.51.100.9")
    assert client_identifier(request, trusted_proxy_hops=1) == "198.51.100.9"


def test_short_forwarded_chain_cannot_index_out_of_range():
    request = _FakeRequest("10.0.0.1", forwarded="198.51.100.9")
    assert client_identifier(request, trusted_proxy_hops=3) == "198.51.100.9"


def test_separate_clients_do_not_share_a_bucket():
    limiter = LoginRateLimiter(attempts=2)
    limiter.check("a")
    limiter.check("a")
    with pytest.raises(HTTPException):
        limiter.check("a")
    # A different client is unaffected by the first one's exhaustion.
    limiter.check("b")


def test_key_table_stays_bounded_under_identifier_cycling():
    limiter = LoginRateLimiter(attempts=5, max_keys=64)
    for index in range(5_000):
        limiter.check(f"attacker-{index}")
    assert len(limiter._attempts) <= 64
