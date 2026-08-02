"""Bounded, public-Internet-only HTTPS intake for the egressing research lane.

The default :mod:`urllib.request` opener follows redirects before callers can inspect
the destination and performs a second, unconstrained DNS lookup when it connects.
That is not an SSRF boundary.  This module owns the complete fetch path instead:

* every initial URL and redirect is HTTPS, credential-free, and host-constrained;
* every A/AAAA answer must be globally routable;
* the connection is pinned to one of the addresses that was actually validated,
  while TLS still verifies the original hostname;
* environment proxies are disabled so they cannot silently change this trust path;
* redirect, response, aggregate-byte, and wall-clock budgets fail closed.

The operating-system/network egress policy remains the outer defense against
resolver compromise.  The checks here make the application boundary explicit and
close the ordinary DNS-to-private and redirect-to-private paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import http.client
import ipaddress
import json
import re
import socket
import time
from typing import Any, Iterable
from urllib.parse import urljoin, urlsplit
import urllib.error
import urllib.request

DEFAULT_MAX_BYTES = 16 * 1024 * 1024
DEFAULT_AGGREGATE_BYTES = 32 * 1024 * 1024
DEFAULT_MAX_RESPONSES = 250
DEFAULT_DEADLINE_SECONDS = 300.0
MAX_REDIRECTS = 5

_DOMAIN_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_SENSITIVE_REDIRECT_HEADERS = frozenset(
    {"authorization", "cookie", "proxy-authorization"}
)


def _url_parts(url: str):
    parsed = urlsplit(str(url or ""))
    if parsed.scheme.lower() != "https":
        raise ValueError("research-lane egress requires an https URL")
    if parsed.username or parsed.password:
        raise ValueError("credentials embedded in a research-lane URL are forbidden")
    host = (parsed.hostname or "").rstrip(".").lower()
    if not host:
        raise ValueError("research-lane URL has no hostname")
    if parsed.port not in (None, 443):
        raise ValueError("research-lane HTTPS URLs must use port 443")
    return parsed, host


def _canonical_host(host: str) -> str:
    """Return the ASCII host spelling used for allowlist comparisons."""
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        try:
            ascii_host = host.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise ValueError("research-lane URL has an invalid hostname") from exc
        labels = ascii_host.split(".")
        if (
            len(labels) < 2
            or any(not label or not _DOMAIN_LABEL.fullmatch(label) for label in labels)
        ):
            raise ValueError(
                "research-lane URL must use a valid, fully-qualified public hostname"
            )
        return ascii_host


def validate_public_https_url(url: str) -> str:
    """Validate URL syntax without performing DNS or network I/O."""
    parsed, host = _url_parts(url)
    canonical = _canonical_host(host)
    if canonical == "localhost" or canonical.endswith(
        (".local", ".internal", ".localhost")
    ):
        raise ValueError("research-lane URL targets a local/internal hostname")
    try:
        address = ipaddress.ip_address(canonical)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError("research-lane URL targets a non-public IP address")
    return parsed.geturl()


def resolve_public_addresses(url: str) -> tuple[str, ...]:
    """Resolve *url* and return only an all-public, deterministic address set.

    A mixed public/private response is refused whole: selecting only its public member
    would make round-robin DNS an intermittent SSRF bypass.
    """
    safe_url = validate_public_https_url(url)
    _parsed, host = _url_parts(safe_url)
    try:
        answers = socket.getaddrinfo(
            host, 443, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
        )
    except OSError as exc:
        raise ValueError(f"research-lane hostname did not resolve: {host}") from exc
    addresses: list[str] = []
    for answer in answers:
        raw = str(answer[4][0]).split("%", 1)[0]
        try:
            address = ipaddress.ip_address(raw)
        except ValueError as exc:
            raise ValueError(f"resolver returned an invalid address for {host}") from exc
        if not address.is_global:
            raise ValueError(
                f"research-lane hostname {host} resolves to non-public address {address}"
            )
        addresses.append(address.compressed)
    if not addresses:
        raise ValueError(f"research-lane hostname returned no usable address: {host}")
    return tuple(dict.fromkeys(addresses))


def _origin(url: str) -> tuple[str, str, int]:
    parsed, host = _url_parts(url)
    return parsed.scheme.lower(), _canonical_host(host), parsed.port or 443


@dataclass
class FetchBudget:
    """Aggregate bounds shared by every response in one logical source sweep."""

    max_bytes: int = DEFAULT_AGGREGATE_BYTES
    max_responses: int = DEFAULT_MAX_RESPONSES
    deadline_seconds: float = DEFAULT_DEADLINE_SECONDS
    used_bytes: int = 0
    responses: int = 0
    _started: float = field(default_factory=lambda: time.monotonic(), repr=False)

    def response_limit(self, per_response: int) -> int:
        if per_response <= 0 or self.max_bytes <= 0 or self.max_responses <= 0:
            raise ValueError("research fetch budgets must be positive")
        if self.responses >= self.max_responses:
            raise ValueError(
                f"research source exceeded the {self.max_responses}-response limit"
            )
        remaining = self.max_bytes - self.used_bytes
        if remaining <= 0:
            raise ValueError(
                f"research source exceeded the {self.max_bytes}-byte aggregate limit"
            )
        return min(per_response, remaining)

    def consume(self, byte_count: int) -> None:
        self.responses += 1
        self.used_bytes += byte_count
        if self.responses > self.max_responses or self.used_bytes > self.max_bytes:
            raise ValueError("research source exceeded its aggregate response budget")

    def timeout(self, requested: float) -> float:
        if requested <= 0:
            raise ValueError("research source timeout must be positive")
        remaining = self.deadline_seconds - (time.monotonic() - self._started)
        if remaining <= 0:
            raise TimeoutError("research source exceeded its overall deadline")
        return min(float(requested), remaining)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection whose TCP peer is a previously validated DNS answer."""

    def __init__(self, host: str, *, pinned_ip: str, **kwargs: Any) -> None:
        self._pinned_ip = pinned_ip
        super().__init__(host, **kwargs)

    def connect(self) -> None:
        if self._tunnel_host:
            raise OSError("HTTP CONNECT tunnels are disabled for research-lane intake")
        self.sock = self._create_connection(
            (self._pinned_ip, self.port),
            self.timeout,
            self.source_address,
        )
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):  # type: ignore[no-untyped-def]
        addresses = resolve_public_addresses(req.full_url)
        pinned_ip = addresses[0]

        def connection_factory(host: str, **kwargs: Any):
            return _PinnedHTTPSConnection(host, pinned_ip=pinned_ip, **kwargs)

        return self.do_open(
            connection_factory,
            req,
            context=self._context,
        )


class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS
    max_repeats = MAX_REDIRECTS

    def __init__(self, allowed_hosts: Iterable[str]) -> None:
        super().__init__()
        self.allowed_hosts = frozenset(_canonical_host(h) for h in allowed_hosts)

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        destination = urljoin(req.full_url, newurl)
        validate_public_https_url(destination)
        destination_origin = _origin(destination)
        if destination_origin[1] not in self.allowed_hosts:
            raise urllib.error.HTTPError(
                destination,
                code,
                "research-lane redirect crossed the allowed-host boundary",
                headers,
                fp,
            )
        # Resolve before urllib is allowed to create the redirected request.  The pinned
        # HTTPS handler resolves again and connects to that checked address, closing the
        # check/use DNS gap.
        resolve_public_addresses(destination)
        redirected = super().redirect_request(req, fp, code, msg, headers, destination)
        if redirected is not None and destination_origin != _origin(req.full_url):
            for name in list(redirected.header_items()):
                if name[0].lower() in _SENSITIVE_REDIRECT_HEADERS:
                    redirected.remove_header(name[0])
        return redirected


def guarded_urlopen(
    target: str | urllib.request.Request,
    *,
    timeout: float,
    allowed_hosts: Iterable[str] | None = None,
):
    """Open one public HTTPS URL without proxies and with guarded redirects."""
    url = target.full_url if isinstance(target, urllib.request.Request) else str(target)
    safe_url = validate_public_https_url(url)
    initial_host = _origin(safe_url)[1]
    allowed = frozenset(
        _canonical_host(host) for host in (allowed_hosts or (initial_host,))
    )
    if initial_host not in allowed:
        raise ValueError(
            f"research source host {initial_host} is outside its endpoint allowlist"
        )
    resolve_public_addresses(safe_url)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _PinnedHTTPSHandler(),
        _GuardedRedirectHandler(allowed),
    )
    return opener.open(target, timeout=timeout)


def _set_response_timeout(response: Any, timeout: float) -> None:
    """Best-effort propagation of the shrinking wall-clock budget to urllib's socket.

    ``HTTPResponse.read`` otherwise applies the original timeout independently to each I/O.  A
    peer that sends one byte just before every timeout could therefore keep a bounded research
    sweep alive indefinitely.
    """
    candidates = [response]
    seen = set()
    for _depth in range(4):
        next_candidates = []
        for candidate in candidates:
            identity = id(candidate)
            if identity in seen:
                continue
            seen.add(identity)
            setter = getattr(candidate, "settimeout", None)
            if callable(setter):
                setter(timeout)
                return
            for attr in ("fp", "raw", "_sock", "sock"):
                try:
                    child = getattr(candidate, attr, None)
                except Exception:
                    child = None
                if child is not None:
                    next_candidates.append(child)
        candidates = next_candidates


def read_json_response(
    response: Any,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    budget: FetchBudget | None = None,
) -> Any:
    """Read one bounded UTF-8 JSON response and charge its exact bytes to *budget*."""
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    final_url = getattr(response, "geturl", lambda: "")()
    if final_url:
        validate_public_https_url(final_url)
    cap = budget.response_limit(max_bytes) if budget is not None else max_bytes
    headers = getattr(response, "headers", None)
    content_length = headers.get("Content-Length") if headers is not None else None
    if content_length:
        try:
            declared = int(content_length)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid Content-Length from research source") from exc
        if declared < 0:
            raise ValueError("negative Content-Length from research source")
        if declared > cap:
            raise ValueError(
                f"research source declared {declared} bytes; limit is {cap}"
            )
    chunks = []
    total = 0
    while total <= cap:
        request_size = min(64 * 1024, cap + 1 - total)
        if request_size <= 0:
            break
        if budget is not None:
            remaining = budget.timeout(budget.deadline_seconds)
            _set_response_timeout(response, remaining)
        chunk = response.read(request_size)
        if budget is not None:
            # Check after every blocking read as well as before it.  This catches slow fakes and
            # transports that do not expose a socket on which the timeout can be tightened.
            budget.timeout(budget.deadline_seconds)
        if not chunk:
            break
        if not isinstance(chunk, bytes):
            raise ValueError("research source returned a non-bytes response body")
        chunks.append(chunk)
        total += len(chunk)
    payload = b"".join(chunks)
    if len(payload) > cap:
        raise ValueError(f"research source exceeded the {cap}-byte response limit")
    if budget is not None:
        budget.consume(len(payload))
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("research source did not return valid UTF-8 JSON") from exc
