from __future__ import annotations

import io
import json
import socket
import urllib.error
import urllib.request

import pytest

from research_lane import http_guard
from research_lane.http_guard import (
    FetchBudget,
    read_json_response,
    resolve_public_addresses,
    validate_public_https_url,
)


class _Response(io.BytesIO):
    def __init__(self, payload: bytes, *, url: str = "https://example.com/feed", length=None):
        super().__init__(payload)
        self._url = url
        self.headers = {}
        if length is not None:
            self.headers["Content-Length"] = str(length)

    def geturl(self):
        return self._url


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/feed",
        "https://user:secret@example.com/feed",
        "https://localhost/feed",
        "https://metadata.internal/feed",
        "https://127.0.0.1/feed",
        "https://10.0.0.8/feed",
        "https://singlelabel/feed",
        "https://example.com:444/feed",
    ],
)
def test_research_egress_rejects_insecure_or_internal_targets(url):
    with pytest.raises(ValueError):
        validate_public_https_url(url)


def test_research_egress_accepts_public_https_url():
    assert validate_public_https_url("https://www.cisa.gov/feed.json").startswith("https://")


def test_response_limit_checks_declared_and_streamed_sizes():
    payload = json.dumps({"ok": True}).encode()
    assert read_json_response(_Response(payload), max_bytes=100) == {"ok": True}
    with pytest.raises(ValueError, match="declared"):
        read_json_response(_Response(payload, length=101), max_bytes=100)
    with pytest.raises(ValueError, match="exceeded"):
        read_json_response(_Response(b"x" * 101), max_bytes=100)


def test_redirect_to_internal_target_is_refused():
    payload = json.dumps({"ok": True}).encode()
    with pytest.raises(ValueError):
        read_json_response(_Response(payload, url="http://127.0.0.1/metadata"))


def test_dns_name_resolving_to_private_or_mixed_addresses_is_refused(monkeypatch):
    def private(*_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]

    monkeypatch.setattr(socket, "getaddrinfo", private)
    with pytest.raises(ValueError, match="non-public"):
        resolve_public_addresses("https://public-looking.example/feed")

    def mixed(*_args, **_kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", mixed)
    with pytest.raises(ValueError, match="non-public"):
        resolve_public_addresses("https://public-looking.example/feed")


def test_alternate_numeric_loopback_spelling_is_refused_after_resolution(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        ],
    )
    with pytest.raises(ValueError, match="non-public"):
        resolve_public_addresses("https://0177.0.0.1/feed")


def test_redirect_is_validated_before_follow_and_cross_host_is_blocked(monkeypatch):
    checked = []

    def resolve(url):
        checked.append(url)
        if "private.example" in url:
            raise ValueError("private DNS answer")
        return ("8.8.8.8",)

    monkeypatch.setattr(http_guard, "resolve_public_addresses", resolve)
    handler = http_guard._GuardedRedirectHandler({"origin.example"})
    req = urllib.request.Request("https://origin.example/feed")
    with pytest.raises(urllib.error.HTTPError, match="allowed-host"):
        handler.redirect_request(
            req, None, 302, "Found", {}, "https://private.example/secret"
        )
    # The host boundary is evaluated before urllib creates/follows a second request.
    assert checked == []


def test_cross_origin_redirect_never_forwards_authorization(monkeypatch):
    monkeypatch.setattr(
        http_guard, "resolve_public_addresses", lambda _url: ("8.8.8.8",)
    )
    handler = http_guard._GuardedRedirectHandler(
        {"origin.example", "cdn.example"}
    )
    req = urllib.request.Request(
        "https://origin.example/feed",
        headers={"Authorization": "Bearer secret", "Cookie": "session=secret"},
    )
    redirected = handler.redirect_request(
        req, None, 302, "Found", {}, "https://cdn.example/feed"
    )
    assert redirected is not None
    lowered = {name.lower() for name, _value in redirected.header_items()}
    assert "authorization" not in lowered
    assert "cookie" not in lowered


def test_https_handler_pins_the_address_it_validated(monkeypatch):
    monkeypatch.setattr(
        http_guard, "resolve_public_addresses", lambda _url: ("8.8.8.8",)
    )
    handler = http_guard._PinnedHTTPSHandler()
    captured = {}

    def fake_do_open(factory, req, **kwargs):
        connection = factory(req.host, timeout=1, **kwargs)
        captured["connection"] = connection
        return "response"

    monkeypatch.setattr(handler, "do_open", fake_do_open)
    result = handler.https_open(urllib.request.Request("https://example.com/feed"))
    assert result == "response"
    assert captured["connection"]._pinned_ip == "8.8.8.8"
    assert captured["connection"].host == "example.com"


def test_aggregate_response_budget_fails_closed():
    budget = FetchBudget(max_bytes=12, max_responses=2, deadline_seconds=30)
    assert read_json_response(
        _Response(b'{"a":1}', length=7), max_bytes=10, budget=budget
    ) == {"a": 1}
    with pytest.raises(ValueError, match="limit"):
        read_json_response(
            _Response(b'{"b":2}', length=7), max_bytes=10, budget=budget
        )


def test_overall_deadline_is_enforced_during_slow_body_reads(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(http_guard.time, "monotonic", lambda: now[0])

    class SlowResponse:
        headers = {}

        def __init__(self):
            self._chunks = iter((b"{", b'"ok"', b":true}"))
            self.timeouts = []

        def geturl(self):
            return "https://example.com/feed"

        def settimeout(self, seconds):
            self.timeouts.append(seconds)

        def read(self, _size):
            now[0] += 0.6
            return next(self._chunks, b"")

    response = SlowResponse()
    budget = FetchBudget(max_bytes=100, max_responses=1, deadline_seconds=1.0)
    with pytest.raises(TimeoutError, match="overall deadline"):
        read_json_response(response, max_bytes=100, budget=budget)
    assert response.timeouts
    assert response.timeouts[-1] < response.timeouts[0]
