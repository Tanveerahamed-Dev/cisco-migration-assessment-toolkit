"""AssessHub FastAPI application.

REST surface over the snapshot store. The engine produces snapshots (CLI); this serves, slices,
diffs, trends, and renders them. Also serves the built frontend (webapp/frontend/dist) when present,
so the whole platform runs from one origin in production.
"""

from __future__ import annotations

import contextlib
import functools
import hmac
import json
import os
import re
import sqlite3
import sys
import tempfile
import threading
import urllib.parse
from pathlib import Path
from typing import Annotated, Any, BinaryIO, Dict, List

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi import Path as PathParam
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from cisco_toolkit import brand_tokens, docmeta
from cisco_toolkit.protocol_assurance import (
    reject_duplicate_json_keys as _reject_duplicate_json_keys,
)

from . import (
    cutover,
    deliverables,
    engine,
    execution,
    gates,
    graph,
    ingest,
    protocol_portfolio,
    serve,
    summary,
)
from .storage import Store

_HERE = Path(__file__).resolve().parent
_WEBAPP = _HERE.parent


def _platform_default_db() -> str:
    """Return a writable default store path for a checkout or an installed wheel."""
    if (_WEBAPP.parent / "pyproject.toml").is_file():
        return str(_WEBAPP / "data" / "assesshub.db")
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return str(Path(base) / "Atlas" / "assesshub.db")
    if sys.platform == "darwin":
        return str(Path.home() / "Library" / "Application Support" / "Atlas" / "assesshub.db")
    base = os.environ.get("XDG_DATA_HOME")
    return str((Path(base) if base else Path.home() / ".local" / "share")
               / "atlas" / "assesshub.db")


# Public for diagnostics/self-test. ASSESSHUB_DB is read when an app is created, not captured
# while importing this module.
DEFAULT_DB = _platform_default_db()


def _default_db_path() -> str:
    return os.environ.get("ASSESSHUB_DB") or DEFAULT_DB


FRONTEND_DIST = _WEBAPP / "frontend" / "dist"

# Prefer the richer, engine-computed demo fleet (webapp/sample_data/build_sample.py); fall back to the
# small bundled golden snapshot if it hasn't been generated.
_RICH_SAMPLE = _WEBAPP / "sample_data" / "sample_fleet.snapshot.json"
_GOLDEN_SAMPLE = _WEBAPP.parent / "tests" / "golden" / "snapshot.json"
SAMPLE_SNAPSHOT = _RICH_SAMPLE if _RICH_SAMPLE.exists() else _GOLDEN_SAMPLE

# Sections the UI may request as a detail slice (top-level snapshot keys it knows how to render).
_ALLOWED_SECTIONS = {k for k, _ in summary.SECTION_LABELS} | {
    "devices", "interfaces", "stp_roots", "routing_neighbors", "subnet_intelligence",
    "endpoint_dependencies", "migration_scenarios", "operational_drift", "security",
    "config_hygiene", "service_map", "addressing_conflicts", "calibration", "score_sensitivity",
    "design_blueprint", "architecture_coverage",
}


# --- write-model length caps -------------------------------------------------------
# EVERY string a write model accepts is capped. The caps started on GateIn alone (V3.23.159), but the
# property that earned them there is shared by every sibling: the value is stored VERBATIM, echoed by
# every later fetch, and rendered into a DOCX table cell (the war-room notes/observations become the
# PIR's as-executed record). Capping one model and not its twins guards a named subset of a structural
# class, so the vector just relocates to the next unguarded field. Sizes are per ROLE, not per model,
# so a new model has an obvious precedent to copy:
_LEN_TOKEN = 40      # a closed vocabulary token (status / decision / kind / gate key)
_LEN_NAME = 200      # a label, wave name, campaign name, operator
_LEN_NOTE = 2000     # free text an engineer types (notes, observations, descriptions)
_LEN_PATH = 4096     # a filesystem path (Windows extended-length paths reach 32k, but not usefully)


# --- row identifiers ---------------------------------------------------------------
# EVERY id this API accepts is a SQLite rowid, which is a signed 64-bit INTEGER — a value outside
# that range cannot name a row, and sqlite3 refuses to BIND it ("Python int too large to convert to
# SQLite INTEGER", an OverflowError). Nothing caught it, so `GET /api/snapshots/1000...0` (31 digits)
# returned HTTP 500 + a server-side traceback instead of "not found", on EVERY id-taking route:
# measured across all 25 of them (18 GET, 4 POST, 3 DELETE) plus CompareIn's two body ids. The bound
# lives on ONE shared alias rather than per-route, because "the routes that take an id" is the
# structural class and a named subset just relocates the crash to the next sibling added —
# webapp/tests/test_backend.py::test_every_row_id_param_is_range_bounded enumerates app.routes and
# fails if a new int id param (path OR body) lacks it. Out-of-range now answers 422, exactly as
# a NON-numeric id already did ("/api/snapshots/abc"), so the two malformed-id shapes agree.
_SQLITE_INT_MIN = -(2 ** 63)
_SQLITE_INT_MAX = 2 ** 63 - 1
RowId = Annotated[int, PathParam(ge=_SQLITE_INT_MIN, le=_SQLITE_INT_MAX)]
#: The same bound for an id carried in a request BODY (Pydantic model field).
BodyRowId = Field(ge=_SQLITE_INT_MIN, le=_SQLITE_INT_MAX)
BoundedToken = Annotated[str, Field(max_length=_LEN_TOKEN)]
BoundedName = Annotated[str, Field(max_length=_LEN_NAME)]


class CampaignIn(BaseModel):
    name: str = Field(max_length=_LEN_NAME)
    description: str = Field(default="", max_length=_LEN_NOTE)
    engagement_id: str = Field(default="", max_length=_LEN_NAME)


class ExpectedFamilyChangeIn(BaseModel):
    family: str = Field(min_length=1, max_length=_LEN_NAME)
    transitions: List[BoundedToken] = Field(min_length=1, max_length=9)
    subjects: List[BoundedName] = Field(default_factory=list, max_length=200)
    reason: str = Field(default="", max_length=_LEN_NOTE)


class ChangeIntentIn(BaseModel):
    expected_changes: List[ExpectedFamilyChangeIn] = Field(default_factory=list, max_length=200)
    note: str = Field(default="", max_length=_LEN_NOTE)


class CompareIn(BaseModel):
    old_id: int = BodyRowId
    new_id: int = BodyRowId
    change_intent: ChangeIntentIn | None = None


class ExecutionCompareIn(BaseModel):
    after_snapshot_id: int = BodyRowId
    change_intent: ChangeIntentIn | None = None


class FolderIngestIn(BaseModel):
    path: str = Field(max_length=_LEN_PATH)
    label: str = Field(default="", max_length=_LEN_NAME)


class ExecutionIn(BaseModel):
    label: str = Field(default="", max_length=_LEN_NAME)
    operator: str = Field(default="", max_length=_LEN_NAME)


class StepIn(BaseModel):
    wave: str = Field(max_length=_LEN_NAME)
    index: int
    status: str = Field(max_length=_LEN_TOKEN)  # pending | done | skipped
    note: str = Field(default="", max_length=_LEN_NOTE)
    operator: str = Field(default="", max_length=_LEN_NAME)


class CheckIn(BaseModel):
    wave: str = Field(max_length=_LEN_NAME)
    index: int
    result: str = Field(max_length=_LEN_TOKEN)  # pending | pass | fail | na
    observed: str = Field(default="", max_length=_LEN_NOTE)
    operator: str = Field(default="", max_length=_LEN_NAME)


class CloseoutIn(BaseModel):
    wave: str = Field(max_length=_LEN_NAME)
    decision: str = Field(max_length=_LEN_TOKEN)  # COMPLETE | ROLLED BACK | DEFERRED
    note: str = Field(default="", max_length=_LEN_NOTE)
    operator: str = Field(default="", max_length=_LEN_NAME)


class EventIn(BaseModel):
    kind: str = Field(max_length=_LEN_TOKEN)  # note | deviation
    text: str = Field(max_length=_LEN_NOTE)
    wave: str = Field(default="", max_length=_LEN_NAME)
    operator: str = Field(default="", max_length=_LEN_NAME)


class FinishIn(BaseModel):
    status: str = Field(max_length=_LEN_TOKEN)  # completed | aborted
    note: str = Field(default="", max_length=_LEN_NOTE)
    operator: str = Field(default="", max_length=_LEN_NAME)


class GateIn(BaseModel):
    # Length caps (V3.23.159): these strings are stored verbatim, echoed by every board fetch and
    # rendered into a DOCX table cell — unbounded input was a DB/document bloat vector.
    wave: str = Field(min_length=1, max_length=120)
    gate: str = Field(max_length=40)      # a cisco_toolkit.engagement.GATE_SEQUENCE key
    decision: str = Field(max_length=20)  # go | no-go | slipped | pending (pending clears)
    signed_by: str = Field(default="", max_length=120)
    note: str = Field(default="", max_length=500)


def _max_json_body_bytes() -> int:
    """Ceiling on a non-upload /api request body (default 1 MiB).

    The per-field caps above reject an oversized value, but only AFTER Starlette has buffered the whole
    body and json.loads has materialised it, so the raw request also needs a ceiling. Always at
    least 64 KiB; a non-integer env value falls back to the default."""
    try:
        return max(64 * 1024, int(os.environ.get("ASSESSHUB_MAX_JSON_BODY_BYTES", str(1024 * 1024))))
    except ValueError:
        return 1024 * 1024


_MULTIPART_UPLOAD_PATH_RE = re.compile(
    r"^/api/campaigns/[^/]+/(?:snapshots|ingest)/?$")


def _is_multipart_upload(request: Request) -> bool:
    """True only for the two routes whose contract accepts a collection upload."""
    content_type = (request.headers.get("content-type") or "").lower()
    return (
        request.method == "POST"
        and "multipart/form-data" in content_type
        and bool(_MULTIPART_UPLOAD_PATH_RE.fullmatch(request.url.path))
    )


def _request_body_limit(request: Request) -> int:
    """Raw HTTP-body ceiling before Starlette's JSON/multipart parser runs."""
    if _is_multipart_upload(request):
        # Boundary and form-field bytes sit outside the uploaded file itself.
        return ingest.MAX_ARCHIVE_BYTES + 2 * 1024 * 1024
    return _max_json_body_bytes()


def _declared_body_too_large(request: Request) -> bool:
    if request.method not in _UNSAFE_METHODS:
        return False
    try:
        declared = int(request.headers.get("content-length", "") or 0)
    except ValueError:
        return False
    return declared > _request_body_limit(request)


class _RequestBodyLimitMiddleware:
    """Spool and count request bytes before FastAPI invokes JSON or multipart parsing.

    Content-Length rejects the normal case without reading a byte; this receive wrapper closes
    the chunked/omitted-length gap. It sits downstream of the access guard, so authentication and
    CSRF are still checked before any request body is consumed.
    """

    def __init__(self, app, upload_semaphore: threading.BoundedSemaphore | None = None):
        self.app = app
        self.upload_semaphore = upload_semaphore

    async def __call__(self, scope, receive, send):
        if (scope.get("type") != "http"
                or str(scope.get("method", "")).upper() not in _UNSAFE_METHODS
                or not str(scope.get("path", "")).startswith("/api/")):
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        limit = _request_body_limit(request)
        received = 0
        disconnected = False
        spool = tempfile.SpooledTemporaryFile(max_size=1024 * 1024)
        slot_held = False
        try:
            while True:
                message = await receive()
                if message.get("type") == "http.disconnect":
                    disconnected = True
                    break
                if message.get("type") != "http.request":
                    continue
                chunk = message.get("body", b"")
                received += len(chunk)
                if received > limit:
                    detail = ("Multipart request body exceeds the upload limit."
                              if _is_multipart_upload(request)
                              else "Request body exceeds the JSON endpoint limit.")
                    await JSONResponse({"detail": detail}, status_code=413)(
                        scope, receive, send)
                    return
                await run_in_threadpool(spool.write, chunk)
                if not message.get("more_body", False):
                    break
            await run_in_threadpool(spool.seek, 0)

            # Take the shared heavy-work slot ONLY NOW — the body is fully received and spooled, so
            # the slot covers the handler's actual work rather than the network read.
            #
            # It used to be acquired before the first body byte. With no read timeout, a client that
            # opened a chunked upload and stalled held the slot for as long as it liked; measured at
            # cap 1, every deliverable generation, explorer render and PIR export returned 503 while
            # one upload sat idle. The cap scales with host RAM and is 1 on a <=4 GiB field laptop,
            # so a single slow connection was total denial of heavy work. Receiving bytes is not the
            # expensive operation this semaphore exists to bound.
            #
            # Refusing here rather than earlier costs only the spooled body, which is already capped
            # by `limit` above and discarded on return. The scope marker still tells the handler not
            # to acquire a second time, and `finally` still releases exactly what was taken.
            if _is_multipart_upload(request) and self.upload_semaphore is not None:
                if not self.upload_semaphore.acquire(blocking=False):
                    await JSONResponse(
                        {"detail": "AssessHub is at its safe heavy-work capacity; retry shortly."},
                        status_code=503,
                        headers={"Retry-After": "5"},
                    )(scope, receive, send)
                    return
                slot_held = True
                scope.setdefault("state", {})["assesshub_generation_slot_held"] = True

            async def replay_receive():
                nonlocal disconnected
                if disconnected:
                    return {"type": "http.disconnect"}
                chunk = await run_in_threadpool(spool.read, 1024 * 1024)
                if chunk:
                    position = await run_in_threadpool(spool.tell)
                    return {
                        "type": "http.request",
                        "body": chunk,
                        "more_body": position < received,
                    }
                disconnected = True
                return {"type": "http.request", "body": b"", "more_body": False}

            await self.app(scope, replay_receive, send)
        finally:
            await run_in_threadpool(spool.close)
            if slot_held and self.upload_semaphore is not None:
                self.upload_semaphore.release()


# --- client-data confidentiality (Plan A / Tier-1 #4) -------------------------------
# The snapshots served here are CLIENT data (topology, IPs, serials, parsed configs).
# Browser vector: CORS is localhost-origin-only (the dev UI proxies /api same-origin, so
# even that rarely applies); internet-origin pages get no readable responses and no
# approved preflights. Network vector: without ASSESSHUB_TOKEN the API serves LOOPBACK
# clients only; setting the token (required for any non-loopback bind) gates every /api
# route behind `Authorization: Bearer <token>`. /api/health stays open as a liveness
# probe — it carries no client data.
# CONFIDENTIALITY is thus covered on the response-READ side by CORS. But WRITES need a
# second guard: a cross-origin page cannot READ our replies, yet it can still EXECUTE
# "simple request" POSTs (multipart / empty-body, no preflight) — blind CSRF that pollutes
# the store and spins up heavy ingest subprocesses (resource-exhaustion DoS). So every
# state-changing method is additionally screened on the REQUEST side (see `_cross_site_write`):
# the browser's Sec-Fetch-Site oracle first, then a same-origin / localhost / extras Origin check —
# the write-side complement to the read-side CORS policy, leaving BOTH the zero-token loopback dev
# flow AND the non-localhost single-origin production deployment working.
_LOCALHOST_ORIGIN_RE = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"


def _cors_origins() -> List[str]:
    """Extra allowed origins, comma-separated in ASSESSHUB_CORS_ORIGINS (advanced setups
    only — e.g. a reverse-proxied UI on another host). Empty by default.

    Fail closed on wildcard, opaque, credential-bearing, or URL-shaped values. CORSMiddleware
    compares serialized origins, not arbitrary URLs; accepting a path/query/userinfo here makes
    the read and CSRF allowlists disagree in surprising ways.
    """
    raw = os.environ.get("ASSESSHUB_CORS_ORIGINS", "")
    origins: List[str] = []
    for configured in (o.strip() for o in raw.split(",")):
        if not configured:
            continue
        if configured in {"*", "null"} or any(ord(ch) < 32 for ch in configured):
            raise ValueError(f"Unsafe ASSESSHUB_CORS_ORIGINS entry: {configured!r}")
        parsed = urllib.parse.urlsplit(configured)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError(
                f"Invalid ASSESSHUB_CORS_ORIGINS entry: {configured!r}") from exc
        if (parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
            raise ValueError(f"Invalid ASSESSHUB_CORS_ORIGINS entry: {configured!r}")
        host = parsed.hostname.lower()
        authority = f"[{host}]" if ":" in host else host
        if port is not None:
            authority += f":{port}"
        origin = f"{parsed.scheme.lower()}://{authority}"
        if origin not in origins:
            origins.append(origin)
    return origins


_SESSION_COOKIE = "assesshub_session"
_SESSION_CONTEXT = b"assesshub-browser-session-v1"


def _browser_session_value(token: str) -> str:
    """Derive a session-cookie value without putting the bearer token in browser storage."""
    return hmac.new(token.encode("utf-8"), _SESSION_CONTEXT, "sha256").hexdigest()


def _request_has_token_authority(request: Request, token: str) -> bool:
    supplied = request.headers.get("authorization", "")
    if hmac.compare_digest(supplied.encode("utf-8", "replace"),
                           f"Bearer {token}".encode("utf-8")):
        return True
    cookie = request.cookies.get(_SESSION_COOKIE, "")
    return hmac.compare_digest(cookie.encode("ascii", "replace"),
                               _browser_session_value(token).encode("ascii"))


# Starlette's in-process TestClient has no socket; it stamps this fixed sentinel peer into the ASGI
# scope. Honoured ONLY while the process is actually executing a pytest test (PYTEST_CURRENT_TEST is
# set per-item by pytest itself), so the literal cannot act as a bypass in a shipped Atlas/uvicorn
# deployment. It is not merely unreachable-by-construction: uvicorn's proxy-headers middleware copies
# X-Forwarded-For into scope["client"] VERBATIM without checking it parses as an IP, so an operator
# who widens forwarded_allow_ips beyond the default would otherwise let a remote client name itself
# "testclient" and be read as loopback.
_ASGI_TEST_HARNESS_HOST = "testclient"


def _under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ


def _client_is_loopback(request: Request) -> bool:
    """True when the ASGI peer is loopback (or the in-process test harness, which has no real socket).

    Deliberately conservative in BOTH directions: a peer with a non-loopback IP is NOT loopback, and an
    UNKNOWN peer is not loopback either. `request.client` is None whenever the server puts no "client"
    in the ASGI scope — a Unix-domain-socket bind, and several ASGI adapters/proxies. That case used to
    return True, i.e. the guard failed OPEN: in no-token mode every request through such a deployment
    satisfied the loopback half of the access guard, leaving only the Host allowlist, whose value a raw
    client picks for itself. Unknown position is not local position, so it fails CLOSED and the operator
    sets ASSESSHUB_TOKEN — already the documented posture for any proxied / non-loopback bind.
    NB uvicorn runs proxy_headers=True, so behind a trusted proxy request.client reflects
    X-Forwarded-For — but forwarded_allow_ips defaults to 127.0.0.1, so a REMOTE peer's forged
    header is ignored. Token mode ignores peer position entirely, closing this deployment edge."""
    host = getattr(request.client, "host", None)
    if host is None:
        return False
    if host == _ASGI_TEST_HARNESS_HOST:
        return _under_pytest()
    return host == "::1" or host.startswith("127.")


# State-changing (unsafe) HTTP methods. GET/HEAD/OPTIONS are safe and never guarded here.
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _origin_is_allowed(origin: str, request: Request) -> bool:
    """True when `origin` is trusted for a WRITE: SAME-ORIGIN (it equals the host this request was
    addressed to — the SPA is served from that origin in a single-origin production deployment), a
    localhost origin, or an admin ASSESSHUB_CORS_ORIGINS extra. That is the read-side CORS allowlist
    PLUS the same-origin case CORS grants implicitly. Only the fallback when there is no Sec-Fetch-Site.
    `fullmatch` (not `match`) mirrors Starlette CORSMiddleware exactly, and denies a trailing-newline
    lookalike (`http://localhost\\n.evil`) that a `$`-anchored `re.match` would otherwise accept."""
    if bool(re.fullmatch(_LOCALHOST_ORIGIN_RE, origin)) or origin in _cors_origins():
        return True
    # Same-origin: the Origin's host[:port] equals the Host this request was addressed to. Parse the
    # authority with urlsplit (netloc) — a naive rsplit("://") is fooled by a lookalike whose FRAGMENT
    # embeds a trusted host ('http://evil.example#http://localhost' rsplits to 'localhost'). A TLS-
    # terminating proxy can leave request.url.scheme http while Origin is https, so compare netloc only.
    host = request.headers.get("host", "")
    return host != "" and urllib.parse.urlsplit(origin).netloc == host


def _request_origin_is_admin_configured(request: Request) -> bool:
    """True when this request's `Origin` is an EXACT ASSESSHUB_CORS_ORIGINS entry.

    THE ONE definition of "the admin deliberately trusted this foreign origin", so the read guard
    (`_forbid_cross_site_get`) and the write guard (`_cross_site_write`) cannot drift apart. They did:
    the write guard honoured this allowance and the read guard did not, so on a split-origin
    deployment (`ASSESSHUB_CORS_ORIGINS=https://ui.example.com`, whose own fetches are labelled
    `Sec-Fetch-Site: cross-site` because the API lives on another registrable domain) the configured
    UI could POST but could not GET — measured on this checkout, `POST /api/campaigns` -> 201 while
    `GET /api/snapshots/1/design` -> 403 for the SAME Origin. A guard that is stricter on reads than
    on writes for the same trusted origin is not a security posture, it is a bug.

    Resolved TOWARDS the allowance, in both directions, because the allowance is already strictly
    weaker than what CORS grants that origin: `allow_origins=_cors_origins()` lets it READ every
    response body it can provoke, so refusing it the request is protection of nothing. And it is not
    forgeable by the drive-by vector this guard exists for: `Origin` is a WHATWG forbidden header
    name, so page JS cannot set it — a foreign page at evil.example sends its own Origin, never the
    admin's — while a non-browser client that could forge it can equally just omit Sec-Fetch-Site,
    which is already documented fail-open. `_cors_origins()` rejects the literal "null", so the
    opaque-origin (sandboxed iframe) value can never match an entry here.

    Returns False when no Origin is present: absence is not a configured origin (fail closed), and
    the caller's own Sec-Fetch-Site rule decides that case."""
    origin = request.headers.get("origin")
    return origin is not None and origin in _cors_origins()


def _cross_site_write(request: Request) -> bool:
    """True for a state-changing request that a foreign site drove the victim's browser
    into making — the blind-CSRF vector (ADR: client-data confidentiality). Even though CORS
    hides the response, a cross-origin page can still fire `multipart/form-data` or empty-body
    POSTs (CORS "simple requests" that skip preflight) that EXECUTE against the zero-token
    loopback bind: store pollution + a heavy ingest subprocess = resource-exhaustion DoS.

    Signal order follows OWASP Fetch-Metadata guidance. An EXPLICIT ASSESSHUB_CORS_ORIGINS match wins
    first: the admin trusts that origin for reads (CORS) so it is trusted for writes too, even though a
    genuine split-origin UI labels its own writes `Sec-Fetch-Site: cross-site` — read/write parity. Then
    `Sec-Fetch-Site` (browser-set, JS cannot forge it — a `Sec-` forbidden header — and correct across a
    TLS-terminating proxy): `same-origin`/`none` are the app's own UI / user-initiated navigation.
    `same-site` is still a different origin and is refused unless its exact Origin is explicitly configured;
    the token-mode Strict cookie is sent to sibling origins within the same site. Note the blanket localhost
    trust is deliberately NOT an override here — a localhost page issuing a cross-site write must still
    be refused. When Sec-Fetch-Site is absent (pre-2023 browsers) fall back to `Origin` (same-origin host
    match / localhost / extras). A request carrying NEITHER header is a non-browser client (curl, the ASGI
    test harness): browsers ALWAYS attach `Origin` to an unsafe-method request (real origin or `null`), so
    this branch is never a cross-site browser write, and allowing it keeps the zero-config loopback dev
    flow (and its pinned test) untouched."""
    if request.method not in _UNSAFE_METHODS:
        return False
    if _request_origin_is_admin_configured(request):
        return False
    origin = request.headers.get("origin")
    site = request.headers.get("sec-fetch-site")
    if site is not None:
        # Same-site is not same-origin. In bearer mode the shipped SPA exchanges the token for a
        # Strict cookie, and browsers send that cookie to sibling origins within the same site.
        # Trust a sibling only through the exact ASSESSHUB_CORS_ORIGINS check above.
        return site not in ("same-origin", "none")
    if origin is not None:
        return not _origin_is_allowed(origin, request)
    return False


# --- DNS-rebinding defense (Plan A / Tier-1 #4 follow-up) ---------------------------
# Loopback network position is NECESSARY but not SUFFICIENT to trust a caller. An attacker
# who lures a victim to a domain they control and rebinds its DNS to 127.0.0.1 reaches this
# server from a loopback peer (so _client_is_loopback is True) while the victim's browser still
# puts the ATTACKER's name in the Host header. Requiring the Host to name a loopback target (or
# an admin-allowlisted hostname) closes the blind cross-origin write that rebinding otherwise
# enables against a zero-token instance — store pollution + the heavy ingest subprocess = a
# resource-exhaustion DoS. Token mode needs no Host check: bearer requests prove authority directly,
# while the derived session cookie is origin-guarded for writes and scoped to the serving host.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

# host[:port] where host is a DNS reg-name / IPv4 ([a-z0-9.-]) or a bracketed IPv6 literal, with an
# OPTIONAL NUMERIC port. Mirrors Django's host_validation_re (the audited reference implementation).
# Anchored with \Z, not $ — $ also matches just before a trailing newline, which would let a smuggled
# "localhost\n" through. This strict gate (applied before the exact match) is what rejects userinfo
# confusion ("localhost:8000@evil.example"), non-numeric ports, embedded control chars / whitespace,
# and comma-joined duplicate Host headers — every one fails closed rather than parsing to "localhost".
_HOST_HEADER_RE = re.compile(r"^([a-z0-9.-]+|\[[a-f0-9:.]+\])(?::[0-9]+)?\Z")


def _allowed_hosts() -> set:
    """Extra Host values an admin trusts, comma-separated in ASSESSHUB_ALLOWED_HOSTS (e.g. a
    same-host reverse-proxy vhost that forwards to the loopback bind). Bare hostname only, no port —
    the request's port is stripped before the match. Empty by default; loopback names always pass."""
    raw = os.environ.get("ASSESSHUB_ALLOWED_HOSTS", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def _request_host_allowed(request: Request) -> bool:
    """True when the request's Host header names a loopback target or an ASSESSHUB_ALLOWED_HOSTS
    entry (exact match, port stripped, case-insensitive). Fail-closed: a malformed, empty, or
    unrecognized Host is rejected. The IP-encoding / 0.0.0.0 / IPv4-mapped-IPv6 rebinding 'bypasses'
    are not a concern for an exact-match allowlist — it rejects every one of them (they matter only
    to fuzzy/suffix matching and server-side SSRF resolvers, neither of which this does)."""
    host = request.headers.get("host", "").lower()
    if not _HOST_HEADER_RE.match(host):
        return False
    hostname = host[1:host.index("]")] if host.startswith("[") else host.rsplit(":", 1)[0]
    return hostname in _LOOPBACK_HOSTS or hostname in _allowed_hosts()


_MAX_SNAPSHOT_NODES = 2_000_000
_MAX_SNAPSHOT_DEPTH = 128


def _validate_snapshot(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict) or "devices" not in value:
        raise HTTPException(
            status_code=400,
            detail="JSON is not an engine snapshot (missing top-level 'devices').",
        )
    if summary.SNAPSHOT_PROVENANCE_KEY in value:
        raise HTTPException(
            status_code=400,
            detail=f"Snapshot field {summary.SNAPSHOT_PROVENANCE_KEY!r} is reserved for server provenance.",
        )
    stack: List[tuple[Any, int]] = [(value, 0)]
    visited = 0
    while stack:
        node, depth = stack.pop()
        visited += 1
        if visited > _MAX_SNAPSHOT_NODES:
            raise HTTPException(400, "Snapshot exceeds the structural node limit.")
        if depth > _MAX_SNAPSHOT_DEPTH:
            raise HTTPException(400, "Snapshot exceeds the structural nesting-depth limit.")
        if isinstance(node, dict):
            stack.extend((child, depth + 1) for child in node.values())
        elif isinstance(node, list):
            stack.extend((child, depth + 1) for child in node)
    return value


def _parse_snapshot_bytes(raw: bytes) -> Dict[str, Any]:
    try:
        # `ingest.reject_nonfinite` owns the refusal (see there for the stored-DoS it closes); this
        # is the untrusted-upload half of the same boundary. json.JSONDecodeError subclasses
        # ValueError, so the one clause covers both a malformed document and that refusal.
        snap = json.loads(
            raw.decode("utf-8"),
            parse_constant=ingest.reject_nonfinite,
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as e:
        raise HTTPException(status_code=400, detail=f"Not valid snapshot JSON: {e}") from e
    return _validate_snapshot(snap)


def _bounded_upload_size(stream: BinaryIO, noun: str) -> int:
    """Size a seekable UploadFile spool without reading or copying its payload."""
    try:
        stream.seek(0, os.SEEK_END)
        size = int(stream.tell())
        stream.seek(0)
    except (AttributeError, OSError, ValueError) as exc:
        raise HTTPException(400, f"{noun} upload is not a readable seekable file.") from exc
    if size > ingest.MAX_ARCHIVE_BYTES:
        raise HTTPException(
            413,
            f"{noun} exceeds the "
            f"{ingest.MAX_ARCHIVE_BYTES // (1024 * 1024)} MB upload limit",
        )
    return size


def _parse_snapshot_stream(stream: BinaryIO) -> Dict[str, Any]:
    _bounded_upload_size(stream, "Snapshot")
    try:
        snap = json.load(
            stream,
            parse_constant=ingest.reject_nonfinite,
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise HTTPException(status_code=400, detail=f"Not valid snapshot JSON: {exc}") from exc
    finally:
        with contextlib.suppress(OSError, ValueError):
            stream.seek(0)
    return _validate_snapshot(snap)


def _bounded_label(explicit: str, fallback: str, default: str) -> str:
    """Apply the same storage cap to client filenames/path basenames as explicit labels."""
    chosen = explicit.strip()
    if not chosen:
        leaf = re.split(r"[\\/]+", str(fallback or ""))[-1]
        chosen = leaf.rsplit(".", 1)[0].strip()
    return (chosen or default)[:_LEN_NAME]


def _stamp_snapshot_origin(
    snap: Dict[str, Any], origin: str, *, integrity_verified: bool | None = None
) -> None:
    """Overwrite input with route-owned origin and an optional positive producer attestation."""
    stamp: Dict[str, Any] = {"origin": origin}
    if integrity_verified is not None:
        stamp["integrity_verified"] = integrity_verified
    snap[summary.SNAPSHOT_PROVENANCE_KEY] = stamp


def _send_file(path: str, media_type: str, filename_stem: str, suffix: str,
               headers: Dict[str, str] | None = None) -> Response:
    """Return a generated temp file's BYTES as the response and delete the file IMMEDIATELY.

    The temp file is a fully-rendered, UNREDACTED client deliverable — hostnames, IPs, serials, parsed
    configs — sitting in the OS temp dir. Cleanup used to run only in a Starlette `BackgroundTask`,
    which fires after the body has been fully sent, so a client disconnect mid-download (or a killed
    process, the normal way a USB-stick field app ends) left that document in %TEMP% PERMANENTLY.
    Reading the bytes and unlinking before the response object exists removes the window entirely:
    there is no path through this function that returns while the file is still on disk. These are
    DOCX/PPTX deliverables (hundreds of KB) and every caller already holds a generation slot, so
    buffering is bounded and cheap; it preserves the writer's bytes without implying a CLI twin.
    `headers` carries out-of-band notes about the file (e.g. X-Gate-Status) without touching its bytes.
    """
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename_stem).strip("_") or "file"
    try:
        data = Path(path).read_bytes()
    finally:
        with contextlib.suppress(OSError):
            os.unlink(path)
    out = dict(headers or {})
    # `safe` is [A-Za-z0-9._-] only, so the quoted form needs no RFC 5987 `filename*` companion.
    out["content-disposition"] = f'attachment; filename="{safe}{suffix}"'
    return Response(content=data, media_type=media_type, headers=out)


# --- compute-heavy GET hardening (GET-based resource-exhaustion follow-up) ------------
# Many GET routes do non-trivial server-side work whose dominant cost is a full multi-MB snapshot
# parse (store.get_snapshot -> json.loads), on top of which some render the explorer HTML, generate a
# DOCX/PPTX, or run an engine compute_* analysis. A "simple" cross-origin GET — fetch(url,{mode:'no-cors'})
# or an <img>/<iframe> src on a foreign page a victim visits — still EXECUTES on the server even though
# CORS hides the response, so a drive-by page could drive CPU/RAM work (distinct from the CSRF *write*
# issue — this vector never mutates the store). Two complementary defenses:
#   1. Same-site provenance on EVERY /api GET (see _API_LIVENESS_PATH for the single carve-out and why
#      the rule is DERIVED rather than listed). Refuse an EXPLICITLY cross-site request. Sec-Fetch-Site is a browser-set
#      FORBIDDEN header (WHATWG Fetch: the `Sec-` prefix means page JS cannot forge or strip it), so it
#      cleanly separates our own same-origin SPA calls — including the sandboxed explorer iframe, whose LOAD
#      request is same-origin (the request's origin is the parent SPA, computed before the sandbox's opaque
#      origin exists) even though its DOCUMENT is opaque — from a cross-site embed. Keying on Sec-Fetch-Site
#      and NEVER on Origin is what keeps that iframe working (its own Origin is null). The allow-set
#      {same-origin, same-site, none, absent} is web.dev's Fetch-Metadata Resource Isolation Policy; we are
#      deliberately STRICTER (we also block cross-site *navigations*, so a cross-site <iframe> embed of the
#      explorer is refused too). Verified against real Chromium: same-origin iframe load -> same-origin;
#      cross-site embed (iframe/img/no-cors fetch) -> cross-site.
#   2. A concurrency cap on every HEAVY request handler, so even a same-origin burst or a non-browser flood
#      (which defense 1 can't see) can't run unbounded heavy work in parallel — excess load is shed with
#      503 + Retry-After. "Heavy" is the structural property, not a route list: the three document/HTML
#      GENERATORS (explorer render, deliverable, PIR report) AND the three INGEST/UPLOAD writes. Multipart
#      bodies and UploadFile payloads are disk-backed streams rather than joined memory copies, but parsing,
#      summary derivation, document generation, and the two collection engine children still have substantial
#      bounded memory footprints. The uploads were the two heaviest operations in the app and took no slot at
#      all, bounded only by Starlette's threadpool — the cap was written as a named list of three routes
#      rather than as the property that earned it.
#      The parse/compute GETs are still NOT capped: a normal dashboard load fans out several of them at
#      once, so throttling that would be wrong.
# LIMITATION (defense 1): an ABSENT Sec-Fetch-Site is treated as trustworthy (curl / server-to-server /
# pre-2023 browsers legitimately omit it — fail-open matches the web.dev policy). Browsers only emit it for a
# "potentially trustworthy" URL, so a no-token instance reached via a NON-canonical loopback hostname (e.g.
# assesshub.local -> 127.0.0.1) gets no header and defense 1 is inert there; the concurrency cap (2) is the
# backstop, and token mode 401s an unauthenticated cross-site request before any compute. For the default
# localhost / 127.0.0.1 bind the origin IS trustworthy and the guard is active.
def _cross_site_request(request: Request) -> bool:
    """True only when Sec-Fetch-Site is an explicit 'cross-site'. same-origin / same-site / none /
    absent are all treated as trustworthy (see the section note above for why)."""
    return (request.headers.get("sec-fetch-site") or "").strip().lower() == "cross-site"


#: The ONE /api path that answers a cross-site (and an unauthenticated) request. It is the liveness
#: probe: a constant-size dict of build/config facts about the SERVER, touching no store and no client
#: data, so its cost cannot scale with anything an attacker controls. `_api_access_guard` already
#: carves it out of the token/loopback checks for exactly that reason — both carve-outs now read this
#: one name, so the app has a single "open endpoint" fact rather than two lists that can disagree.
_API_LIVENESS_PATH = "/api/health"

#: Refusal body for a cross-site GET. A CONSTANT string chosen before any routing/lookup, so a foreign
#: page learns nothing about which snapshot/campaign/execution ids exist.
_CROSS_SITE_GET_DETAIL = ("This endpoint runs server-side work over collected client data and cannot "
                          "be requested cross-site; open AssessHub directly.")


def _forbid_cross_site_get(request: Request) -> bool:
    """True when this request must be refused as a cross-site-triggered READ of the API surface.

    THE RULE IS DERIVED, NOT LISTED. It is called from `_api_access_guard`, AFTER that middleware has
    already decided `guarded` from the app's own surface ("/api/* plus the OpenAPI/docs routes, minus
    the liveness path") — so this function inherits that one definition of the surface instead of
    re-deriving a second one, and everything in it is refused. This replaces a hand-maintained per-route
    `dependencies=[Depends(...)]` attachment, under which the guard covered only the 17 routes someone
    remembered: measured on the real 1.8 MB demo snapshot, `/api/meta` (200 cross-site, ~6x the cost of
    `/api/health` — ten `importlib.util.find_spec` probes plus a TOML parse of pyproject.toml on EVERY
    call), `/api/campaigns/{id}/gates` (200 cross-site, snapshot-proportional json_extract) and two
    execution reads were in neither the guarded list nor the "cheap" allow-list — they were simply
    omissions. A route added tomorrow is guarded by DEFAULT; opting one out means adding it to the
    liveness carve-out, which `tests/test_expensive_get_hardening.py` pins and requires to be
    store-free (i.e. genuinely constant-cost), so cheapness is an asserted property and never an
    accident of nobody having looked.

    An EXPLICIT ASSESSHUB_CORS_ORIGINS Origin is allowed, through the SAME helper the write guard
    uses (`_request_origin_is_admin_configured`) rather than a second copy of the rule — see its
    docstring for the measured read/write inversion this closes and why the allowance is the correct
    direction. A shared helper is the point: two hand-kept copies of "which origins does the admin
    trust" is how the guards diverged in the first place.

    OPTIONS is excluded by the caller (CORS preflight). Writes are NOT handled here: they have their
    own, stricter guard (`_cross_site_write`, which also refuses an unknown/absent provenance)."""
    if request.method not in ("GET", "HEAD"):
        return False
    if request.url.path == _API_LIVENESS_PATH:
        return False
    if _request_origin_is_admin_configured(request):
        return False
    return _cross_site_request(request)


_HEAVY_JOB_MEMORY_RESERVATION = 768 * 1024 * 1024
_HEAVY_JOB_HARD_CAP = 4


def _physical_memory_bytes() -> int | None:
    """Best-effort physical-memory discovery using only stdlib APIs available in Atlas."""
    if os.name == "nt":
        try:
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys)
        except (AttributeError, OSError, ValueError):
            return None
    try:
        pages = int(os.sysconf("SC_PHYS_PAGES"))
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        return pages * page_size if pages > 0 and page_size > 0 else None
    except (AttributeError, OSError, ValueError):
        return None


def _memory_safe_generation_cap(total_memory: int | None = None) -> int:
    """Reserve roughly two job footprints for the OS/UI and never exceed four heavy workers."""
    total = _physical_memory_bytes() if total_memory is None else total_memory
    if not total or total <= 0:
        return 1
    return max(1, min(_HEAVY_JOB_HARD_CAP, total // (_HEAVY_JOB_MEMORY_RESERVATION * 3)))


def _max_concurrent_generations() -> int:
    """Memory-derived heavy-work cap with a bounded, never-upward-unsafe env override."""
    safe_cap = _memory_safe_generation_cap()
    raw = os.environ.get("ASSESSHUB_MAX_CONCURRENT_GENERATIONS")
    if raw is None:
        return safe_cap
    try:
        requested = int(raw)
    except ValueError:
        return safe_cap
    return max(1, min(requested, safe_cap, _HEAVY_JOB_HARD_CAP))


@contextlib.contextmanager
def _generation_slot(semaphore: threading.BoundedSemaphore):
    """Hold one generation slot for the duration of a heavy generate/render, or shed load with a 503 when
    the server is already at its concurrency ceiling. Non-blocking on purpose: a saturated server tells the
    caller to retry rather than queueing (and holding a threadpool worker for) work it can't afford."""
    if not semaphore.acquire(blocking=False):
        raise HTTPException(
            status_code=503,
            detail="AssessHub is generating too many deliverables at once — please retry shortly.",
            headers={"Retry-After": "5"})
    try:
        yield
    finally:
        semaphore.release()


@contextlib.contextmanager
def _request_generation_slot(request: Request):
    """Reuse the multipart middleware's pre-body slot, or acquire one for non-upload work."""
    if request.scope.get("state", {}).get("assesshub_generation_slot_held") is True:
        yield
        return
    with _generation_slot(request.app.state.generation_semaphore):
        yield


#: Memoised optional-library probes, keyed by the probe callable that produced each answer.
#: `{slot: (callable, value)}` — see `_optional_lib_probe`.
_LIB_PROBE_CACHE: Dict[str, tuple] = {}


def _optional_lib_probe(slot: str, probe):
    """Run a PROCESS-STATIC optional-library probe once, and reuse the answer.

    `deliverables.availability()` is ten `importlib.util.find_spec` calls and `have_docx()` is one;
    both re-ran on EVERY request. Caching them under `_meta_build_facts` fixed only `/api/meta` — the
    identical cost sat unfixed on two other exits (`GET /api/snapshots/{id}/deliverable/{kind}` and
    `GET /api/executions/{id}/report`), which is the same defect, not a smaller one. Route them all
    through here so the property is "this app probes the optional libs once", not "someone remembered
    /api/meta". The answers cannot change while the process lives: a library cannot be installed into
    a running interpreter's already-resolved finder result.

    Keyed on the probe CALLABLE's identity, not on nothing, so a test that monkeypatches
    `deliverables.availability` / `deliverables.have_docx` is honoured immediately and unpatching
    restores the real answer — the failure mode a plain `lru_cache()` here would introduce (a stub
    silently ignored because an earlier request warmed the cache) is worse than the cost it saves.
    The cache is a fixed set of named slots, so it cannot grow without bound."""
    hit = _LIB_PROBE_CACHE.get(slot)
    if hit is not None and hit[0] is probe:
        return hit[1]
    value = probe()
    _LIB_PROBE_CACHE[slot] = (probe, value)
    return value


def _deliverable_availability() -> Dict[str, bool]:
    """`deliverables.availability()` without re-probing ten find_specs per request. Returns a fresh
    dict each call so a caller cannot mutate the memoised answer."""
    return dict(_optional_lib_probe("availability", deliverables.availability))


def _have_docx() -> bool:
    """`deliverables.have_docx()` without re-probing find_spec per request."""
    return bool(_optional_lib_probe("have_docx", deliverables.have_docx))


@functools.lru_cache(maxsize=1)
def _meta_build_facts() -> tuple[tuple[dict, ...], str]:
    """The two PROCESS-STATIC, genuinely expensive parts of /api/meta, computed once.

    `deliverables.catalogue()` probes the two registry-declared optional renderer modules and
    `serve._release_version()` re-opens and TOML-parses pyproject.toml — on EVERY
    request. Measured on this box with the demo snapshot loaded, that made /api/meta ~6x the cost of
    /api/health and comparable to a guarded snapshot-parsing route, which is why /api/meta was the
    most expensive route the old per-route guard did not cover. Neither answer can change without
    restarting the process (a library cannot be installed into a running interpreter's finder result,
    and the release string is baked into the checkout/dist), so caching them is the correct fix and
    not merely a mitigation; the SPA loads /api/meta on every page open, so this is a same-origin win
    as much as a cross-site one. Brand tokens and the section labels stay LIVE — they are plain
    module attributes, cost nothing, and are the ones a test may legitimately monkeypatch.

    Returns immutable data (a tuple of dicts) so a caller cannot mutate the cached value. Call
    `_meta_build_facts.cache_clear()` in a test that patches `deliverables`/`serve`."""
    return tuple(deliverables.catalogue()), serve._release_version()


def is_guarded_api_path(path: str, doc_paths) -> bool:
    """Whether `path` is on the API surface `_api_access_guard` protects (auth + cross-site read +
    CSRF). THE definition — the middleware calls this, and so does the completeness test, so a test
    asserting "everything registered is either guarded or explicitly recorded as not" cannot drift
    from the rule it is asserting about. `doc_paths` is the app's own OpenAPI/docs set
    (`app.state.api_doc_paths`), read off the FastAPI instance rather than hardcoded, so renaming or
    disabling one of those URLs cannot silently open a hole.

    Note what this rule does NOT cover, deliberately and visibly: anything registered outside
    `/api/*` and the docs set — a `Mount` (the SPA's `/assets` StaticFiles), or a route on some
    future `/v2` / `/internal` prefix. Those are unguarded BY CONSTRUCTION, which is correct for
    static assets and would be a hole for anything that reads client data;
    `tests/test_expensive_get_hardening.py` enumerates every registered route against this predicate
    so a new one outside the surface fails the suite instead of opening the gap silently."""
    return path.startswith("/api/") or path in doc_paths


def create_app(db_path: str | None = None, dist_dir: str | os.PathLike | None = None,
               boot_hardening: bool = False) -> FastAPI:
    """``dist_dir`` overrides where the built SPA is served from (default: the checkout's
    webapp/frontend/dist) — the hook the Atlas entry module uses to point at the bundled copy
    inside a frozen build (webapp/backend/serve.py, ADR-0004 P1). ``boot_hardening`` threads the
    P3 unplug-safety boot (integrity check + backup — see storage.Store) and may raise
    StoreCorruptError; only the production entry turns it on."""
    store = Store(db_path or _default_db_path(), boot_hardening=boot_hardening)
    app = FastAPI(
        title="AssessHub",
        version=engine.ENGINE_SCHEMA_VERSION,
        description="A live web platform over the Cisco Migration-Assessment engine.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),                 # env extras only; empty by default
        allow_origin_regex=_LOCALHOST_ORIGIN_RE,       # localhost on any port — never '*'
        allow_methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Authorization", "Content-Type"],
    )
    generation_semaphore = threading.BoundedSemaphore(_max_concurrent_generations())
    app.add_middleware(
        _RequestBodyLimitMiddleware,
        upload_semaphore=generation_semaphore,
    )

    # The FastAPI-generated API-DOCUMENTATION routes. They describe this very API but do NOT sit
    # under /api/, so the `path.startswith("/api/")` test below skipped them entirely: measured, a
    # token-protected AssessHub answered `GET /openapi.json` with HTTP 200 and the complete route +
    # request-model schema to a caller sending no Bearer at all, and the same request from a
    # NON-loopback peer on a zero-token instance also got 200 while /api/campaigns got 403. That is
    # the guard-completeness trap this codebase keeps re-learning — the rule was written as a path
    # PREFIX instead of as "everything this app generates except the SPA shell and liveness".
    # Read from the app's own attributes rather than hardcoded literals, so renaming docs_url (or
    # setting one to None to switch it off) cannot silently re-open the hole.
    _doc_paths = frozenset(p for p in (app.openapi_url, app.docs_url, app.redoc_url,
                                       app.swagger_ui_oauth2_redirect_url) if p)
    # Published so callers (the completeness tests) read the SAME derived set the middleware uses.
    # A test that re-lists these attributes by hand is a hand list again — and was one short of this
    # set, missing swagger_ui_oauth2_redirect_url ("/docs/oauth2-redirect").
    app.state.api_doc_paths = _doc_paths

    @app.middleware("http")
    async def _api_access_guard(request: Request, call_next):
        """Registered AFTER (so wrapping OUTSIDE) CORSMiddleware; skips OPTIONS so
        preflights fall through to CORS. Cross-site writes are refused (CSRF). Token set ->
        Bearer required on all /api (and on the OpenAPI/docs routes, which describe it);
        token unset -> those are loopback-only AND the Host header must name a loopback target
        (DNS-rebinding guard, see _request_host_allowed). Health/liveness stays open."""
        path = request.url.path
        guarded = is_guarded_api_path(path, _doc_paths)
        if (request.method == "OPTIONS" or not guarded
                or path == _API_LIVENESS_PATH):
            return await call_next(request)
        # The READ twin of the CSRF rule, and the SAME placement reasoning: refuse a cross-site GET
        # before any auth check, so the invariant holds identically in token and no-token modes. It
        # lives HERE — in the one place that already derives this app's whole API surface — rather
        # than as a per-route dependency, because a per-route list is a list (see
        # _forbid_cross_site_get for what that list was missing, measured).
        if _forbid_cross_site_get(request):
            return JSONResponse({"detail": _CROSS_SITE_GET_DETAIL}, status_code=403)
        # Refuse state-changing requests driven by a foreign origin BEFORE any auth check, so
        # the "no cross-site writes" invariant holds identically in token and no-token modes.
        if _cross_site_write(request):
            return JSONResponse({"detail": "Cross-site state-changing request refused: a write "
                                           "must originate from the AssessHub UI, not another "
                                           "site (CSRF protection)."},
                                status_code=403)
        # Same placement reasoning as the CSRF refusal: before the auth check, so the body ceiling
        # holds identically in token and no-token modes. Costs one header read; nothing is buffered.
        if _declared_body_too_large(request):
            limit = _request_body_limit(request)
            return JSONResponse({"detail": f"Request body exceeds the {limit // 1024} KB limit "
                                           f"for this endpoint."},
                                status_code=413)
        token = os.environ.get("ASSESSHUB_TOKEN", "")
        if token:
            if not _client_is_loopback(request) and request.url.scheme != "https":
                return JSONResponse(
                    {"detail": "Bearer-token access from a non-loopback client requires HTTPS."},
                    status_code=403,
                )
            if not _request_has_token_authority(request, token):
                return JSONResponse({"detail": "This AssessHub requires an API token: "
                                               "enter it in the Atlas sign-in prompt or send "
                                               "'Authorization: Bearer <ASSESSHUB_TOKEN>'."},
                                    status_code=401,
                                    headers={"WWW-Authenticate": "Bearer"})
        else:
            # No token -> trust rests on loopback network position, which is DNS-rebinding-forgeable.
            # Require BOTH: a loopback peer AND a Host header that names a loopback target (or an
            # ASSESSHUB_ALLOWED_HOSTS entry). Loopback check first, so its actionable message wins.
            if not _client_is_loopback(request):
                return JSONResponse({"detail": "AssessHub serves loopback clients only until an API "
                                               "token is configured — set ASSESSHUB_TOKEN on the server "
                                               "and send it as 'Authorization: Bearer <token>' to enable "
                                               "non-local access to client data."},
                                    status_code=403)
            if not _request_host_allowed(request):
                return JSONResponse({"detail": "AssessHub rejected this request's Host header "
                                               "(DNS-rebinding guard): reach it as localhost / 127.0.0.1, "
                                               "or set ASSESSHUB_ALLOWED_HOSTS to trust a specific "
                                               "hostname."},
                                    status_code=403)
        return await call_next(request)

    @app.middleware("http")
    async def _security_headers(request: Request, call_next):
        response = await call_next(request)
        # SAMEORIGIN intentionally permits the SPA's own explorer iframe while preventing a
        # foreign site from framing the cockpit or a client-data response.
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'self'")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    app.state.store = store
    # Bound concurrent heavy deliverable/explorer generations for this app (see _generation_slot).
    app.state.generation_semaphore = generation_semaphore

    # -- meta --------------------------------------------------------------
    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "status": "ok",
            "engine_schema": engine.ENGINE_SCHEMA_VERSION,
            "sample_available": SAMPLE_SNAPSHOT.exists(),
            "token_required": bool(os.environ.get("ASSESSHUB_TOKEN")),
        }
        # Build smoke tests set a one-use nonce so a pre-existing process on the fixed probe port
        # can never impersonate the child that was just spawned.
        nonce = os.environ.get("ASSESSHUB_INSTANCE_NONCE")
        if nonce:
            out["instance_nonce"] = nonce
        return out

    @app.post("/api/session", status_code=204)
    def create_browser_session(request: Request) -> Response:
        """Exchange one Bearer-authenticated request for a same-site HttpOnly browser session.

        This is what makes token mode usable by the shipped SPA, including native downloads and
        the same-origin explorer iframe, neither of which can attach an Authorization header.
        """
        token = os.environ.get("ASSESSHUB_TOKEN", "")
        if not token:
            raise HTTPException(409, "Bearer-token mode is not enabled on this AssessHub.")
        response = Response(status_code=204)
        response.set_cookie(
            _SESSION_COOKIE,
            _browser_session_value(token),
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="strict",
            path="/",
        )
        return response

    @app.delete("/api/session", status_code=204)
    def delete_browser_session() -> Response:
        response = Response(status_code=204)
        response.delete_cookie(_SESSION_COOKIE, path="/", samesite="strict")
        return response

    @app.get("/api/meta")
    def meta() -> Dict[str, Any]:
        catalogue, release = _meta_build_facts()
        return {
            "engine_schema": engine.ENGINE_SCHEMA_VERSION,
            "severity_order": summary.SEVERITY_ORDER,
            "bands": summary.BANDS,
            "section_labels": [{"key": k, "label": v} for k, v in summary.SECTION_LABELS],
            # copied out of the cache, so a caller that mutates the response cannot poison it
            "deliverables": [dict(d) for d in catalogue],
            # Includes non-download pre-cutover members and the conditional PIR; unlike
            # len(deliverables), these denominators describe the complete portable lifecycle.
            "artifact_family": docmeta.artifact_family_metadata(),
            # ADR-0004 D1: the SPA renders the brand it is SERVED — the values live in ONE place
            # (cisco_toolkit/brand_tokens.py), so a rename never touches the frontend.
            "app": {
                "name": brand_tokens.APP_NAME,
                "byline": brand_tokens.APP_BYLINE,
                "title": brand_tokens.APP_TITLE,
                "release": release,
            },
        }

    # -- campaigns ---------------------------------------------------------
    # Guarded because `_summary_freshened` makes this a state-CHANGING, expensive GET: a full
    # multi-MB snapshot parse plus a `store.update_summary()` WRITE. Measured cross-site before the
    # guard reached it: `/api/snapshots/{id}` -> 403, but `/api/campaigns` -> 200 with 1 parse
    # and 1 DB write, and `/api/campaigns/{id}` amplified per snapshot in the campaign. A foreign
    # page's `fetch('http://localhost:8000/api/campaigns')` executes even though CORS hides the
    # response — the Host is genuinely localhost and the peer is loopback, so neither the
    # DNS-rebinding allowlist nor `_client_is_loopback` fires. `_cross_site_write` cannot see it
    # either, because it keys on the METHOD and this is a GET.
    @app.get("/api/campaigns")
    def list_campaigns() -> List[Dict[str, Any]]:
        campaigns = store.list_campaigns()
        for campaign in campaigns:
            latest_id = store.latest_snapshot_id(campaign["id"])
            if latest_id is None:
                campaign["latest_summary"] = None
                continue
            meta = store.get_snapshot_meta(latest_id)
            if meta is not None:
                campaign["latest_summary"] = _summary_freshened(
                    latest_id, meta
                ).get("summary")
        return campaigns

    @app.post("/api/campaigns", status_code=201)
    def create_campaign(body: CampaignIn) -> Dict[str, Any]:
        return store.create_campaign(body.name, body.description, body.engagement_id)

    # freshens EVERY snapshot: parse + DB write each
    @app.get("/api/campaigns/{campaign_id}")
    def get_campaign(campaign_id: RowId) -> Dict[str, Any]:
        c = store.get_campaign(campaign_id)
        if not c:
            raise HTTPException(404, "Campaign not found")
        c["snapshots"] = [
            _summary_freshened(item["id"], item)
            for item in c.get("snapshots", [])
        ]
        return c

    @app.delete("/api/campaigns/{campaign_id}", status_code=204)
    def delete_campaign(campaign_id: RowId):
        deleted = store.delete_campaign_if_unreceipted(campaign_id)
        if deleted == "missing":
            raise HTTPException(404, "Campaign not found")
        if deleted == "receipted":
            raise HTTPException(
                409,
                "A campaign containing canonical comparison receipts is an immutable decision "
                "record and cannot be deleted",
            )
        # A bare 204 — JSONResponse(content=None) would serialize a "null" body, which uvicorn
        # rejects on a 204 with an ASGI RuntimeError on every delete.
        return Response(status_code=204)

    # parses EVERY snapshot in the campaign
    @app.get("/api/campaigns/{campaign_id}/trend")
    def campaign_trend(campaign_id: RowId) -> Dict[str, Any]:
        c = store.get_campaign(campaign_id)
        if not c:
            raise HTTPException(404, "Campaign not found")
        bound = [store.get_bound_snapshot(s["id"]) for s in c["snapshots"]]
        if any(item is None for item in bound):
            # Never bridge over a snapshot that disappeared between the roster read and the
            # exact-byte reads: C1→C3 is not the adjacent-pair evidence C1→C2 and C2→C3 named.
            # Return an explicit incomplete/indeterminate receipt set with the original expected
            # denominator. A retry may succeed against a coherent campaign roster.
            expected_pairs = max(0, len(c["snapshots"]) - 1)
            unavailable = engine.campaign_trend([], source_bindings=[])
            unavailable["verdict"] = "INDETERMINATE"
            prior_note = str(unavailable.get("verdict_note") or "")
            race_note = (
                "Canonical adjacent comparisons are NOT VERIFIED because a source snapshot "
                "disappeared while the ordered campaign was read; no non-adjacent pair was "
                "substituted. Retry against a stable campaign roster."
            )
            unavailable["verdict_note"] = f"{race_note} {prior_note}".strip()
            unavailable["adjacent_comparisons"] = []
            unavailable["adjacent_comparison_status"] = {
                "schema": "campaign_adjacent_comparison_set/1",
                "status": "not_verified",
                "n_pairs_total": expected_pairs,
                "n_pairs_returned": 0,
                "complete": False,
                "note": race_note,
            }
            return unavailable
        available = [item for item in bound if item is not None]
        return engine.campaign_trend(
            [item[0] for item in available],
            source_bindings=[item[1] for item in available],
        )

    # -- gate board (T-minus sign-offs; feeds the engagement plan of record) --
    def _campaign_waves(campaign_id: int) -> List[str]:
        """Wave labels for the gate board — section-only read (V3.23.159: this sat on the
        per-click hot path doing a full multi-MB snapshot parse)."""
        sid = store.latest_snapshot_id(campaign_id)
        if sid is None:
            return []
        rows = store.get_snapshot_section(sid, "migration_readiness")
        return gates.waves_from_snapshot({"migration_readiness": rows})

    @app.get("/api/campaigns/{campaign_id}/gates")
    def get_gates(campaign_id: RowId) -> Dict[str, Any]:
        if not store.campaign_exists(campaign_id):
            raise HTTPException(404, "Campaign not found")
        return {"cadence": gates.cadence(),
                "waves": _campaign_waves(campaign_id),
                "records": gates.annotate_out_of_order(store.list_gates(campaign_id))}

    @app.post("/api/campaigns/{campaign_id}/gates")
    def set_gate(campaign_id: RowId, body: GateIn) -> Dict[str, Any]:
        if not store.campaign_exists(campaign_id):
            raise HTTPException(404, "Campaign not found")
        wave = body.wave.strip()
        if not wave:
            raise HTTPException(400, "wave must not be empty")
        # Phantom-wave guard (V3.23.159): a decision may only target a wave the latest snapshot
        # derives, or one that already has recorded history (so legacy rows stay clearable after
        # the wave set changes) — a typo'd label can no longer mint a permanent row in the
        # governance trail.
        allowed = set(_campaign_waves(campaign_id)) | {r["wave"] for r in store.list_gates(campaign_id)}
        if wave not in allowed:
            raise HTTPException(400, f"Unknown wave '{wave}' — not in this campaign's calendar "
                                     f"(known waves: {sorted(allowed) or 'none derivable yet'})")
        try:
            gates.apply_decision(store, campaign_id, wave, body.gate, body.decision,
                                 body.signed_by, body.note)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return {"records": gates.annotate_out_of_order(store.list_gates(campaign_id))}

    # -- snapshots ---------------------------------------------------------
    @app.post("/api/campaigns/{campaign_id}/snapshots", status_code=201)
    async def upload_snapshot(campaign_id: RowId, request: Request, file: UploadFile = File(...),
                              label: str = Form("", max_length=_LEN_NAME)) -> Dict[str, Any]:
        if not store.get_campaign(campaign_id):
            raise HTTPException(404, "Campaign not found")
        # Multipart middleware acquired this slot before accepting the first body byte. UploadFile
        # is already a bounded spool; parse from that seekable file without a second chunks+join copy.
        # iobase_upload_file: every stream leaving the route layer carries the full IO probe
        # interface (py3.10's spool does not -- the owner's docstring has the why).
        with _request_generation_slot(request):
            snap = await run_in_threadpool(
                _parse_snapshot_stream, ingest.iobase_upload_file(file.file)
            )
            _stamp_snapshot_origin(snap, summary.DIRECT_UPLOAD_ORIGIN)
            lbl = _bounded_label(label, file.filename or "", "snapshot")
            derived = await run_in_threadpool(summary.summarize, snap)
            return await run_in_threadpool(store.add_snapshot, campaign_id, lbl, snap, derived)

    @app.post("/api/campaigns/{campaign_id}/ingest", status_code=201)
    async def ingest_collection(campaign_id: RowId, request: Request, file: UploadFile = File(...),
                                label: str = Form("", max_length=_LEN_NAME)) -> Dict[str, Any]:
        """Upload a raw collection ZIP (per-device show-command outputs); the real engine pipeline
        runs server-side and the resulting snapshot is stored like an uploaded one."""
        if not store.get_campaign(campaign_id):
            raise HTTPException(404, "Campaign not found")
        # The body is a disk-backed UploadFile spool for realistic archives. Pass that stream
        # directly to ZipFile; no raw-bytes duplicate is ever materialised in this process.
        # iobase_upload_file: the runner's contract is a stream with the full IO probe interface,
        # and the runner is replaceable -- so the route normalizes, not just _safe_extract.
        with _request_generation_slot(request):
            try:
                stream = ingest.iobase_upload_file(file.file)
                await run_in_threadpool(_bounded_upload_size, stream, "Archive")
                # The engine run blocks for seconds-to-minutes; off the event loop so the rest of the
                # API (including a live war-room console) stays responsive.
                snap, report = await run_in_threadpool(ingest.run_collection_zip, stream)
            except ingest.IngestError as e:
                raise HTTPException(400, str(e)) from e
            except ingest.EngineRunError as e:
                raise HTTPException(500, str(e)) from e
            _stamp_snapshot_origin(
                snap, summary.LOCAL_ENGINE_ORIGIN, integrity_verified=True
            )
            report["verification"] = summary.snapshot_verification(snap)
            lbl = _bounded_label(label, file.filename or "", "collection")
            derived = await run_in_threadpool(summary.summarize, snap)
            meta = await run_in_threadpool(store.add_snapshot, campaign_id, lbl, snap, derived)
            meta["ingest"] = report
            return meta

    @app.post("/api/campaigns/{campaign_id}/ingest-folder", status_code=201)
    async def ingest_collection_folder(campaign_id: RowId, body: FolderIngestIn,
                                       request: Request) -> Dict[str, Any]:
        """Ingest a SERVER-LOCAL collection folder — the portable-app 'one door' path (ADR-0004
        P1): on the stick the collection already sits beside the app, so a ZIP round-trip is pure
        friction. Same engine pipeline and the same middleware guards as every write (access guard
        + cross-site refusal); the folder is only READ — outputs land in a private temp workdir.

        ``contain=True`` because "only READ" is not the safety property here — reading is the
        exposure. The path arrives from the CLIENT, so without containment this route reads any
        directory the server process can reach (another engagement's captures, an old collection in
        Downloads, a UNC share), parses it, and stores a snapshot the caller reads back in full."""
        if not store.get_campaign(campaign_id):
            raise HTTPException(404, "Campaign not found")
        # Forks the same engine child with the same 600s timeout as /ingest — same generation slot.
        with _request_generation_slot(request):
            try:
                snap, report = await run_in_threadpool(
                    functools.partial(ingest.run_collection_folder, body.path, contain=True))
            except ingest.IngestError as e:
                raise HTTPException(400, str(e)) from e
            except ingest.EngineRunError as e:
                raise HTTPException(500, str(e)) from e
            _stamp_snapshot_origin(
                snap, summary.LOCAL_ENGINE_ORIGIN, integrity_verified=True
            )
            report["verification"] = summary.snapshot_verification(snap)
            lbl = _bounded_label(body.label, body.path, "folder")
            derived = await run_in_threadpool(summary.summarize, snap)
            meta = await run_in_threadpool(store.add_snapshot, campaign_id, lbl, snap, derived)
            meta["ingest"] = report
            return meta

    def _summary_freshened(snapshot_id: int, meta: Dict[str, Any]) -> Dict[str, Any]:
        """Heal a headline summary frozen by an OLDER engine schema than the one now recomputing the
        live section tabs, so the dashboard's headline cards can't disagree with a section tab on the
        SAME screen. Mirrors the device_dossiers staleness recompute (get_section): the summary is
        stamped with engine.ENGINE_SCHEMA_VERSION at write; a trailing/absent stamp triggers one
        recompute + re-persist (the snapshot_json itself is immutable, so the recompute is
        deterministic and the re-persist also self-heals the campaign-list card)."""
        summ = meta.get("summary")
        verification = summ.get("verification") if isinstance(summ, dict) else None
        if (
            isinstance(summ, dict)
            and summ.get("engine_schema") == engine.ENGINE_SCHEMA_VERSION
            and isinstance(verification, dict)
            and verification.get("status") in {"verified", "partial", "unverified"}
            and verification.get("contract_version") == summary.VERIFICATION_CONTRACT_VERSION
        ):
            return meta
        snap = store.get_snapshot(snapshot_id)
        if snap is None:                       # row vanished between meta read and heal — serve what we have
            return meta
        fresh = summary.summarize(snap)
        store.update_summary(snapshot_id, fresh)
        meta = dict(meta)
        meta["summary"] = fresh
        return meta

    # NOT a cheap metadata read: whenever the cached summary's engine_schema trails the live
    # one, _summary_freshened does a full multi-MB snapshot parse, an engine summarize() AND a
    # store.update_summary() DATABASE WRITE. So it belongs to the guarded expensive-GET class
    # on both counts — and it is a state-CHANGING GET, which _cross_site_write cannot see
    # (it returns False for GET by construction), leaving _forbid_cross_site_get as the only guard.
    @app.get("/api/snapshots/{snapshot_id}")
    def get_snapshot(snapshot_id: RowId) -> Dict[str, Any]:
        meta = store.get_snapshot_meta(snapshot_id)
        if not meta:
            raise HTTPException(404, "Snapshot not found")
        return _summary_freshened(snapshot_id, meta)

    # full-snapshot parse per call
    @app.get("/api/snapshots/{snapshot_id}/section/{name}")
    def get_section(snapshot_id: RowId, name: str) -> Dict[str, Any]:
        if name not in _ALLOWED_SECTIONS:
            raise HTTPException(400, f"Unknown section '{name}'")
        if name == protocol_portfolio.SECTION_KEY:
            bound = store.get_bound_snapshot(snapshot_id)
            if bound is None:
                raise HTTPException(404, "Snapshot not found")
            snap, binding = bound
            bundle = protocol_portfolio.build_protocol_single_snapshot_bundle(snap, binding)
            receipt = bundle["receipt"]
            return {
                "section": name,
                "data": {
                    "receipt": receipt,
                    "complete_export": {
                        **receipt["complete_export"],
                        "url": f"/api/snapshots/{snapshot_id}/protocol-assurance/export",
                    },
                },
            }
        snap = store.get_snapshot(snapshot_id)
        if snap is None:
            raise HTTPException(404, "Snapshot not found")
        if name not in snap:
            raise HTTPException(404, f"Section '{name}' not present in this snapshot")
        data = snap[name]
        if name == "device_dossiers":
            # one-source-of-truth, like the sibling heavy sections (archreview/design/...): a pre-V3.23.174
            # snapshot bands the uncollected fleet 'Low / routine migration handling' instead of 'Unassessed'
            # (false-health -- a blind device reads identical to a verified-low one). If the stored section is
            # stale -- uncollected devices exist but it carries NO 'Unassessed' band -- recompute with the current
            # engine so the live Risk Register surfaces them as a coverage gap (audit-4 #20).
            # isinstance-guard (summary._as_list) over `or []`: a TRUTHY non-list health_scores (an int in a
            # malformed/hostile upload) survives `or []` and 500s this `for h in` iteration -> unhandled 500 on
            # GET /section/device_dossiers. Likewise the stored device_dossiers 'summary' may be a truthy
            # non-dict, so guard it before .get('bands') rather than trusting `or {}`.
            _has_blind = any(isinstance(h, dict) and h.get("band") == "Insufficient Data"
                             for h in summary._as_list(snap.get("health_scores")))
            _summ = data.get("summary") if isinstance(data, dict) else None
            _bands = _summ.get("bands") if isinstance(_summ, dict) else None
            if _has_blind and isinstance(_bands, dict) and not _bands.get("Unassessed"):
                from cisco_toolkit.analyze import compute_device_dossiers
                data = compute_device_dossiers(
                    health_scores=snap.get("health_scores"), failure_impact=snap.get("failure_impact"),
                    lifecycle_risk=snap.get("lifecycle_risk"), software_risk=snap.get("software_risk"),
                    platform_health=snap.get("platform_health"), syslog_intelligence=snap.get("syslog_intelligence"),
                    qos_audit=snap.get("qos_audit"), golden_drift=snap.get("golden_drift"),
                    security=snap.get("security"), config_hygiene=snap.get("config_hygiene"),
                    stp_roots=snap.get("stp_roots"), vpc=snap.get("vpc"),
                    physical_health=snap.get("physical_health"), protocol_health=snap.get("protocol_health"),
                    move_groups=snap.get("move_groups"))
        return {"section": name, "data": data}

    @app.get("/api/snapshots/{snapshot_id}/protocol-assurance/export")
    def protocol_assurance_export(snapshot_id: RowId) -> Response:
        """Complete, uncapped JSON portfolio bound to the exact persisted snapshot blob."""
        bound = store.get_bound_snapshot(snapshot_id)
        if bound is None:
            raise HTTPException(404, "Snapshot not found")
        snap, binding = bound
        bundle = protocol_portfolio.build_protocol_single_snapshot_bundle(snap, binding)
        payload = protocol_portfolio.canonical_export_bytes(bundle["complete_export"])
        digest = bundle["receipt"]["complete_export"]["sha256"]
        return Response(
            content=payload,
            media_type="application/json",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="protocol-assurance-snapshot-{snapshot_id}.json"'
                ),
                "Cache-Control": "no-store",
                "X-Atlas-Content-SHA256": digest,
            },
        )

    @app.get("/api/snapshots/{snapshot_id}/graph")
    def snapshot_graph(snapshot_id: RowId) -> Dict[str, Any]:
        meta = store.get_snapshot_meta(snapshot_id)
        snap = store.get_snapshot(snapshot_id)
        if snap is None or meta is None:
            raise HTTPException(404, "Snapshot not found")
        keystones = [k.get("host") for k in (meta["summary"].get("keystones") or []) if k.get("host")]
        return graph.build_graph(snap, keystones)

    @app.get("/api/snapshots/{snapshot_id}/cable_map")
    def snapshot_cable_map(snapshot_id: RowId) -> Dict[str, Any]:
        """EDA-style physical cable map (Python SSOT snap['cable_map']): CDP/LLDP links laid out in role
        tiers, cables coloured by operational status. Recomputed from evidence for pre-feature snapshots."""
        snap = store.get_snapshot(snapshot_id)
        if snap is None:
            raise HTTPException(404, "Snapshot not found")
        return graph.cable_map_from_snapshot(snap)

    @app.get("/api/snapshots/{snapshot_id}/cutover")
    def snapshot_cutover(snapshot_id: RowId) -> Dict[str, Any]:
        """Gated, pilot-first cutover plan (run-of-show) synthesized from the snapshot's migration model."""
        snap = store.get_snapshot(snapshot_id)
        if snap is None:
            raise HTTPException(404, "Snapshot not found")
        return cutover.build_plan(snap)

    @app.get("/api/snapshots/{snapshot_id}/archreview")
    def snapshot_archreview(snapshot_id: RowId) -> Dict[str, Any]:
        """The senior-engineer design review (V3.23.160 engine compute) for this snapshot.
        Fast path: the stored architecture_review section (json_extract, no full-blob parse) when
        the snapshot was produced by V3.23.160+; otherwise computed server-side from the stored
        snapshot with the SAME engine function the CLI runs — one source of truth either way."""
        if not store.get_snapshot_meta(snapshot_id):
            raise HTTPException(404, "Snapshot not found")
        ar = store.get_snapshot_section(snapshot_id, "architecture_review")
        if not (isinstance(ar, dict) and ar.get("checks")):
            from cisco_toolkit.archreview import compute_architecture_review
            snap = store.get_snapshot(snapshot_id)
            if snap is None:
                raise HTTPException(404, "Snapshot not found")
            ar = compute_architecture_review(snap)
        return ar

    _fallback_bp: Dict[int, Any] = {}

    def _fallback_blueprint(snapshot_id: int, snap: Dict[str, Any]) -> Dict[str, Any]:
        """The design_blueprint computed on the fly for a snapshot that doesn't store one, MEMOISED by id. The
        four read endpoints below (causal_flows / design / architecture_coverage / nrfu) each fall back to this
        when the stored section is absent; a stored snapshot is immutable (the Store exposes no update), so this
        pure function of the snapshot + its STORED requirements is identical on every request -- compute it once
        per snapshot instead of re-running compute_design_blueprint on each panel load. The POST overlays use a
        REQUEST-supplied register and deliberately bypass this cache."""
        cached = _fallback_bp.get(snapshot_id)
        if cached is None:
            from cisco_toolkit.design_advisor import compute_design_blueprint
            cached = compute_design_blueprint(snap, snap.get("requirements_register") or {})
            if len(_fallback_bp) < 256:        # bound memory; immutable snapshots mean an entry never goes stale
                _fallback_bp[snapshot_id] = cached
        return cached

    @app.get("/api/snapshots/{snapshot_id}/causal_flows")
    def snapshot_causal_flows(snapshot_id: RowId) -> Dict[str, Any]:
        """Unified CAUSAL FLOW model (engine compute_causal_flows) — every finding family rendered as one
        trigger -> mechanism -> impact -> mitigation story (cross-layer compounds become a bowtie). This is
        the SAME normalization the explorer's Causal Flow mode shows; computed server-side so the dashboard
        never re-derives causal intent (one source of truth). For a snapshot that already carries a
        design_blueprint this matches the explorer exactly; for one that doesn't, the blueprint is computed on
        the fly (same fallback the /design endpoint uses) so the design-decision family is still present —
        keeping the webapp internally consistent with its own /design panel."""
        if not store.get_snapshot_meta(snapshot_id):
            raise HTTPException(404, "Snapshot not found")
        snap = store.get_snapshot(snapshot_id)
        if snap is None:
            raise HTTPException(404, "Snapshot not found")
        # compute design_blueprint when the stored snapshot lacks one (honouring any published requirements),
        # so the design-decision family appears — a no-op for engagement snapshots that already store it.
        bp = snap.get("design_blueprint")
        if not (isinstance(bp, dict) and isinstance(bp.get("decisions"), list)):
            try:
                snap = dict(snap)
                snap["design_blueprint"] = _fallback_blueprint(snapshot_id, snap)
            except Exception:
                pass  # design couldn't be computed -> fall through; the other families still render
        from cisco_toolkit.causal import compute_causal_flows
        try:
            return compute_causal_flows(snap)
        except Exception as exc:  # defense-in-depth: the engine fn is hardened to be total over any dict,
            raise HTTPException(500, f"causal-flow computation failed: {exc}")  # but never leak a raw stack

    @app.get("/api/snapshots/{snapshot_id}/design")
    def snapshot_design(snapshot_id: RowId) -> Dict[str, Any]:
        """The CCDE-grounded target-state DESIGN BLUEPRINT (engine compute_design_blueprint) — the SAME
        object the HLD/LLD DOCX and the explorer Design mode read. Prefers the stored design_blueprint
        section; computes server-side with the same engine function otherwise (one source of truth)."""
        if not store.get_snapshot_meta(snapshot_id):
            raise HTTPException(404, "Snapshot not found")
        bp = store.get_snapshot_section(snapshot_id, "design_blueprint")
        if not (isinstance(bp, dict) and isinstance(bp.get("decisions"), list)):
            snap = store.get_snapshot(snapshot_id)
            if snap is None:
                raise HTTPException(404, "Snapshot not found")
            # honour the register the CLI published with the snapshot so the fallback recompute is the SAME
            # right-sized blueprint the stored section would have been (not an un-right-sized one)
            bp = _fallback_blueprint(snapshot_id, snap)
        return bp

    def _resolve_architecture_coverage(snapshot_id: int) -> Dict[str, Any]:
        """The architecture-coverage SSOT for a snapshot: the stored section if present, else computed
        server-side with the SAME engine function the CLI/explorer use (one source of truth). Raises 404 for
        an unknown snapshot. Shared by the /architecture_coverage and /domain_packs endpoints so coverage is
        resolved exactly ONE way -- a pack selection can never disagree with the coverage grid beside it."""
        if not store.get_snapshot_meta(snapshot_id):
            raise HTTPException(404, "Snapshot not found")
        cov = store.get_snapshot_section(snapshot_id, "architecture_coverage")
        if not (isinstance(cov, dict) and isinstance(cov.get("classes"), list)):
            from cisco_toolkit.design_advisor import compute_architecture_coverage
            snap = store.get_snapshot(snapshot_id)
            if snap is None:
                raise HTTPException(404, "Snapshot not found")
            if not isinstance(snap.get("design_blueprint"), dict):
                snap["design_blueprint"] = _fallback_blueprint(snapshot_id, snap)
            cov = compute_architecture_coverage(snap)
        return cov

    # same lazy compute_* class as /causal_flows
    @app.get("/api/snapshots/{snapshot_id}/architecture_coverage")
    def snapshot_architecture_coverage(snapshot_id: RowId) -> Dict[str, Any]:
        """Architecture-coverage SSOT (engine compute_architecture_coverage): which architecture CLASSES were
        OBSERVED vs not, across both ingestion channels (ssh show-text / json controller-REST), and what fired
        -- the SAME map the explorer's ✎Design view renders. Coverage-honest: 'not-observed' is NOT 'healthy'.
        Prefers the stored section; computes server-side with the same engine function otherwise (one source of
        truth -- the dashboard never re-derives coverage)."""
        return _resolve_architecture_coverage(snapshot_id)

    # resolves architecture_coverage (may compute)
    @app.get("/api/snapshots/{snapshot_id}/domain_packs")
    def snapshot_domain_packs(snapshot_id: RowId) -> Dict[str, Any]:
        """Which DOMAIN SKILL-PACKS (DC/ACI · Enterprise/SD-Access · SP/MPLS-SR · Security/ISE-TrustSec) this
        snapshot engages (Phase-3 / D6). A pack loads IFF one of its architecture classes was OBSERVED in the
        SAME coverage map above -- retrieval-selected by evidence, never a default headcount. Selection is the
        engine SSOT (cisco_toolkit.domain_packs.select_packs); the dashboard never re-derives it in JS.
        Coverage-honest: no observed class -> no packs, said plainly (never 'no domain concerns')."""
        from cisco_toolkit.domain_packs import select_packs
        return select_packs(_resolve_architecture_coverage(snapshot_id))

    @app.post("/api/snapshots/{snapshot_id}/design")
    def design_overlay(snapshot_id: RowId, requirements: Dict[str, Any]) -> Dict[str, Any]:
        """Interactive requirements overlay: recompute the blueprint right-sized to a requirements
        register (availability_tier / critical_apps / convergence_budget_ms / growth_horizon /
        fabric_operating_model / constraints / data_classification / address_space / vlan_zones). The
        right-sizing logic lives ONLY here (Python, the same compute_design_blueprint the CLI runs) —
        the dashboard never re-derives design intent.

        The body is EITHER a typed requirements register OR the engagement interview's tagged answers
        wrapped as {"interview_answers": {...}} — the latter mapped through the SAME
        requirements_from_interview bridge the CLI uses, so interview output closes the requirements loop
        here too (one normalisation path, no second mapper)."""
        from cisco_toolkit.design_advisor import (compute_design_blueprint,
                                                  requirements_from_interview)
        snap = store.get_snapshot(snapshot_id)
        if snap is None:
            raise HTTPException(404, "Snapshot not found")
        body = requirements or {}
        register = (requirements_from_interview(body["interview_answers"])
                    if isinstance(body.get("interview_answers"), dict) else body)
        return compute_design_blueprint(snap, register or {})

    # computes the blueprint + NRFU on the fly
    @app.get("/api/snapshots/{snapshot_id}/design/nrfu")
    def design_nrfu(snapshot_id: RowId) -> Dict[str, Any]:
        """Design-driven NRFU/ATP acceptance-test checklist derived from the recommended design
        decisions. One structured item per decision, traceable to the CCDE principle, the evidence
        that triggered it, and the specific devices the NRFU engineer must verify. Items are phased
        across three cutover stages: pre-cutover → post-cutover-functional → post-cutover-operational.
        The right-sizing logic lives only in Python — the dashboard never re-derives test items."""
        from cisco_toolkit.design_advisor import compute_design_nrfu
        nrfu = store.get_snapshot_section(snapshot_id, "design_nrfu")   # canonical, published by the engine
        if isinstance(nrfu, dict) and isinstance(nrfu.get("items"), list):
            return nrfu
        bp = store.get_snapshot_section(snapshot_id, "design_blueprint")
        if not (isinstance(bp, dict) and isinstance(bp.get("decisions"), list)):
            snap = store.get_snapshot(snapshot_id)
            if snap is None:
                raise HTTPException(404, "Snapshot not found")
            bp = _fallback_blueprint(snapshot_id, snap)
        return compute_design_nrfu(bp)

    @app.post("/api/snapshots/{snapshot_id}/design/nrfu")
    def design_nrfu_overlay(snapshot_id: RowId, requirements: Dict[str, Any]) -> Dict[str, Any]:
        """Right-size the NRFU/ATP checklist to a requirements register (or {"interview_answers": {...}}),
        so the dashboard NRFU tab reflects right-sizing rather than the baseline. SSOT: derived server-side
        from the SAME overlay blueprint POST /design returns (compute_design_blueprint -> compute_design_nrfu)
        — the dashboard never re-derives test items or their phases."""
        from cisco_toolkit.design_advisor import (compute_design_blueprint, compute_design_nrfu,
                                                  requirements_from_interview)
        snap = store.get_snapshot(snapshot_id)
        if snap is None:
            raise HTTPException(404, "Snapshot not found")
        body = requirements or {}
        register = (requirements_from_interview(body["interview_answers"])
                    if isinstance(body.get("interview_answers"), dict) else body)
        return compute_design_nrfu(compute_design_blueprint(snap, register or {}))

    def _bound_comparison_pair(before_snapshot_id: int, after_snapshot_id: int):
        if before_snapshot_id == after_snapshot_id:
            raise HTTPException(400, "Before and after snapshots must be different")
        before_bound = store.get_bound_snapshot(before_snapshot_id)
        after_bound = store.get_bound_snapshot(after_snapshot_id)
        if before_bound is None or after_bound is None:
            raise HTTPException(404, "One or both snapshots not found")
        before, before_binding = before_bound
        after, after_binding = after_bound
        if before_binding.get("engagement_id") != after_binding.get("engagement_id"):
            raise HTTPException(
                409,
                "Snapshots belong to different engagements; cross-engagement comparison is non-overridable",
            )
        if before_binding.get("campaign_id") != after_binding.get("campaign_id"):
            raise HTTPException(
                409,
                "Snapshots belong to different campaigns; compare evidence within one campaign",
            )
        return before, before_binding, after, after_binding

    # -- execution runs (war room) ------------------------------------------
    def _execution_view(rec: Dict[str, Any], state: Dict[str, Any] | None = None) -> Dict[str, Any]:
        view = execution.with_progress(
            rec["id"], rec["snapshot_id"], state if state is not None else rec["state"])
        view["comparison_receipts"] = list(rec.get("comparisons") or [])
        return view

    def _mutate_execution(execution_id: int, fn) -> Dict[str, Any]:
        """Atomic read-modify-write on one run's state; returns the updated derived state."""
        with execution.MUTATION_LOCK:
            rec = store.get_execution(execution_id)
            if not rec:
                raise HTTPException(404, "Execution run not found")
            try:
                fn(rec["state"])
            except KeyError as e:
                raise HTTPException(404, f"Unknown wave {e}") from e
            except IndexError as e:
                raise HTTPException(400, "Step/check index out of range") from e
            except (execution.RunClosedError, execution.WaveClosedError) as e:
                raise HTTPException(409, str(e)) from e
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
            saved = store.save_execution_if_unchanged(
                execution_id, rec["_state_json"], rec["state"])
            if saved == "missing":
                raise HTTPException(404, "Execution run was deleted")
            if saved == "conflict":
                raise HTTPException(
                    409,
                    "Execution run changed in another server process. Reload it and retry "
                    "the update so no operator's record is overwritten.",
                )
            return _execution_view(rec, rec["state"])

    @app.post("/api/snapshots/{snapshot_id}/executions", status_code=201)
    def start_execution(snapshot_id: RowId, body: ExecutionIn) -> Dict[str, Any]:
        """Materialize the snapshot's cutover plan into a live, frozen execution run."""
        bound = store.get_bound_snapshot(snapshot_id)
        if bound is None:
            raise HTTPException(404, "Snapshot not found")
        snap, source_binding = bound
        # Build the (label-independent) plan OFF the lock — it can block for a while and must not
        # serialize the whole war room.
        state = execution.start_run(
            snap, body.label, body.operator, source_binding=source_binding)
        if not state["waves"]:
            raise HTTPException(400, "No migration waves were derived from this snapshot — nothing to execute")
        # Auto-label + insert atomically under Store's BEGIN IMMEDIATE, so independent server
        # processes cannot mint the same ordinal.
        with execution.MUTATION_LOCK:
            try:
                eid = store.create_execution(
                    snapshot_id, state, auto_label=not body.label.strip())
            except sqlite3.IntegrityError as e:
                # The snapshot was DELETED between the read above and this insert — a colleague
                # clearing a campaign while the war room starts its run. executions.snapshot_id is a
                # foreign key (storage._SCHEMA) with PRAGMA foreign_keys=ON, so the insert is refused
                # and the raw IntegrityError escaped as HTTP 500 + a server-side traceback. Nothing
                # is wrong with the REQUEST: the row it names is simply gone, which is the same 404
                # the read a few milliseconds earlier would have returned. `_mutate_execution` already
                # treats the mirror-image race (`save_execution` -> 0 rows) as a 404; this is the
                # start-side sibling that was left raw. The plan build is unaffected — it ran off the
                # snapshot already in memory — so nothing partial is persisted.
                raise HTTPException(404, "Snapshot not found") from e
        return {
            **execution.with_progress(eid, snapshot_id, state),
            "comparison_receipts": [],
        }

    @app.get("/api/snapshots/{snapshot_id}/executions")
    def list_executions(snapshot_id: RowId) -> List[Dict[str, Any]]:
        if not store.get_snapshot_meta(snapshot_id):
            raise HTTPException(404, "Snapshot not found")
        return store.list_executions(snapshot_id)

    @app.get("/api/executions/{execution_id}")
    def get_execution(execution_id: RowId) -> Dict[str, Any]:
        rec = store.get_execution(execution_id)
        if not rec:
            raise HTTPException(404, "Execution run not found")
        return _execution_view(rec)

    @app.post("/api/executions/{execution_id}/compare")
    def compare_execution(execution_id: RowId, body: ExecutionCompareIn) -> Dict[str, Any]:
        """Bind one after snapshot and append the canonical comparison receipt to a live run."""
        rec = store.get_execution(execution_id)
        if not rec:
            raise HTTPException(404, "Execution run not found")
        policy = rec["state"].get("comparison_policy") \
            if isinstance(rec.get("state"), dict) else None
        if (not isinstance(policy, dict)
                or policy.get("schema") != "execution_comparison_policy/1"
                or policy.get("canonical_gate_required") is not True):
            raise HTTPException(
                409,
                "This legacy execution predates canonical comparison receipts and cannot be backfilled",
            )
        if rec["state"].get("status") != "in_progress":
            raise HTTPException(409, "A finished execution cannot accept new comparison evidence")

        before, before_binding, after, after_binding = _bound_comparison_pair(
            rec["snapshot_id"], body.after_snapshot_id)
        frozen = policy.get("before_snapshot")
        required_keys = ("snapshot_id", "campaign_id", "engagement_id", "sha256")
        if (not isinstance(frozen, dict)
                or any(frozen.get(key) != before_binding.get(key) for key in required_keys)):
            raise HTTPException(
                409,
                "The execution's frozen start-snapshot custody no longer matches stored source bytes",
            )
        comparison = engine.compare_bound_pair(
            before,
            after,
            before_binding=before_binding,
            after_binding=after_binding,
            change_intent=(body.change_intent.model_dump(mode="json")
                           if body.change_intent is not None else None),
        )
        intent = comparison.get("change_intent")
        if not isinstance(intent, dict) or intent.get("valid") is not True:
            failures = intent.get("failures") if isinstance(intent, dict) else []
            detail = "; ".join(str(item) for item in failures if str(item).strip())
            raise HTTPException(
                422,
                "Change intent is malformed and cannot be bound to an execution receipt"
                + (f": {detail}" if detail else ""),
            )
        implementation_binding = execution.implementation_evidence_binding(rec["state"])
        if implementation_binding.get("valid") is not True:
            raise HTTPException(
                409,
                "Post-change comparison is available only after every implementation step has "
                "been actioned. Complete or explicitly skip the pending run-of-show steps, then "
                "collect and upload fresh evidence.",
            )
        receipt = engine.compact_execution_comparison(
            comparison,
            before_snapshot_id=rec["snapshot_id"],
            after_snapshot_id=body.after_snapshot_id,
            after_collected_at=(
                after.get("collected_at") if isinstance(after.get("collected_at"), str) else None
            ),
            implementation_binding=implementation_binding,
        )
        saved = store.append_execution_comparison_if_unchanged(
            execution_id, rec["_state_json"], receipt)
        status = saved.get("status")
        if status == "missing":
            raise HTTPException(404, "Execution run was deleted")
        if status == "closed":
            raise HTTPException(409, "A finished execution cannot accept new comparison evidence")
        if status == "legacy":
            raise HTTPException(409, "Legacy execution comparison backfill is not allowed")
        if status == "identity_mismatch":
            raise HTTPException(409, "Execution start-snapshot identity no longer matches")
        if status == "source_missing":
            raise HTTPException(
                404,
                "A comparison source snapshot was deleted while the canonical gate was computed",
            )
        if status == "source_mismatch":
            raise HTTPException(
                409,
                "Canonical comparison custody no longer matches the persisted source bytes",
            )
        if status == "comparison_mismatch":
            raise HTTPException(
                409,
                "Submitted comparison does not match a canonical recomputation from the persisted "
                "source bytes",
            )
        if status == "after_not_post_change":
            raise HTTPException(
                409,
                "Post-change evidence must be a newer snapshot uploaded after this execution "
                "started, with an aware collected_at after run start and no later than upload; "
                "stale, missing, future-dated, or ambiguously ordered captures cannot satisfy "
                "the canonical gate",
            )
        if status != "saved":
            raise HTTPException(
                409,
                "Execution run changed while comparison was computed. Reload and compare again.",
            )
        updated = store.get_execution(execution_id)
        if not updated:
            raise HTTPException(404, "Execution run was deleted")
        return _execution_view(updated)

    @app.post("/api/executions/{execution_id}/step")
    def execution_step(execution_id: RowId, body: StepIn) -> Dict[str, Any]:
        return _mutate_execution(
            execution_id,
            lambda st: execution.apply_step(st, body.wave, body.index, body.status,
                                            body.note, body.operator))

    @app.post("/api/executions/{execution_id}/check")
    def execution_check(execution_id: RowId, body: CheckIn) -> Dict[str, Any]:
        return _mutate_execution(
            execution_id,
            lambda st: execution.apply_check(st, body.wave, body.index, body.result,
                                             body.observed, body.operator))

    @app.post("/api/executions/{execution_id}/closeout")
    def execution_closeout(execution_id: RowId, body: CloseoutIn) -> Dict[str, Any]:
        return _mutate_execution(
            execution_id,
            lambda st: execution.apply_closeout(st, body.wave, body.decision,
                                                body.note, body.operator))

    @app.post("/api/executions/{execution_id}/event")
    def execution_event(execution_id: RowId, body: EventIn) -> Dict[str, Any]:
        return _mutate_execution(
            execution_id,
            lambda st: execution.add_event(st, body.kind, body.text, body.wave, body.operator))

    @app.post("/api/executions/{execution_id}/finish")
    def execution_finish(execution_id: RowId, body: FinishIn) -> Dict[str, Any]:
        return _mutate_execution(
            execution_id,
            lambda st: execution.finish(st, body.status, body.note, body.operator))

    @app.get("/api/executions/{execution_id}/report")
    def execution_report(execution_id: RowId, request: Request):
        """Post-Implementation Review / as-executed change record for this run, as .docx."""
        pir_spec = docmeta.artifact_spec("pir")
        rec = store.get_execution(execution_id)
        if not rec:
            raise HTTPException(404, "Execution run not found")
        if not _have_docx():
            raise HTTPException(503, "python-docx is not installed on the server")
        write_pir_docx = deliverables.resolve_writer(pir_spec)

        snap_meta = store.get_snapshot_meta(rec["snapshot_id"])
        snap_label = snap_meta["label"] if snap_meta else "snapshot"
        # Same heavy-generator treatment as /deliverable: bound concurrency, and take the slot BEFORE
        # creating the temp file so a shed (503) leaves nothing to clean up.
        with _generation_slot(request.app.state.generation_semaphore):
            fd, path = tempfile.mkstemp(suffix="." + pir_spec.ext, prefix="assesshub_pir_")
            os.close(fd)
            try:
                # Old rows may carry SUCCESSFUL from the former closeout-only authority rule.
                # Recompute the read view before exporting so a PIR cannot publish that stale
                # verdict when required steps/checks were never completed.
                report_state = {
                    **execution.with_current_outcome(rec["state"]),
                    "comparison_receipts": list(rec.get("comparisons") or []),
                }
                write_pir_docx(path, report_state, snap_label)
            except Exception as e:
                if os.path.exists(path):
                    os.unlink(path)
                raise HTTPException(500, f"Failed to generate the PIR: {e}") from e
        return _send_file(
            path, pir_spec.media, report_state.get("label", "run"),
            pir_spec.download_suffix)

    @app.delete("/api/executions/{execution_id}", status_code=204)
    def delete_execution(execution_id: RowId):
        # Under the mutation lock so a delete can't land inside another request's
        # read-modify-write window (whose save would then be a silent no-op).
        with execution.MUTATION_LOCK:
            deleted = store.delete_execution_if_unreceipted(execution_id)
            if deleted == "missing":
                raise HTTPException(404, "Execution run not found")
            if deleted == "receipted":
                raise HTTPException(
                    409,
                    "An execution with canonical comparison receipts is an immutable decision "
                    "record and cannot be deleted",
                )
        return Response(status_code=204)

    @app.get("/api/snapshots/{snapshot_id}/explorer", response_class=HTMLResponse)
    def snapshot_explorer(snapshot_id: RowId, request: Request) -> HTMLResponse:
        meta = store.get_snapshot_meta(snapshot_id)
        bound = store.get_bound_snapshot(snapshot_id)
        if bound is None or meta is None:
            raise HTTPException(404, "Snapshot not found")
        snap, binding = bound
        protocol_assurance_bundle = (
            protocol_portfolio.build_protocol_single_snapshot_bundle(snap, binding)
        )
        with _generation_slot(request.app.state.generation_semaphore):   # bound concurrent heavy renders
            html = engine.render_explorer_html(
                snap,
                meta["label"],
                protocol_assurance_bundle=protocol_assurance_bundle,
            )
        return HTMLResponse(content=html)

    @app.get("/api/snapshots/{snapshot_id}/deliverable/{kind}")
    def snapshot_deliverable(snapshot_id: RowId, kind: str, request: Request):
        if kind not in deliverables.SPECS:
            raise HTTPException(400, f"Unknown deliverable '{kind}'")
        meta = store.get_snapshot_meta(snapshot_id)
        protocol_assurance_bundle = None
        if kind in {"runbook", "mop", "nrfu"}:
            bound = store.get_bound_snapshot(snapshot_id)
            if bound is None:
                raise HTTPException(404, "Snapshot not found")
            snap, binding = bound
            protocol_assurance_bundle = (
                protocol_portfolio.build_protocol_single_snapshot_bundle(snap, binding)
            )
        else:
            snap = store.get_snapshot(snapshot_id)
        if snap is None or meta is None:
            raise HTTPException(404, "Snapshot not found")
        if not _deliverable_availability().get(kind):
            raise HTTPException(503, f"{deliverables.SPECS[kind].needs} is not installed on the server")
        # The feedback loop: the engagement plan of record carries the campaign's recorded gate
        # sign-offs (§4.3 "as signed"); every other deliverable is a pure snapshot read.
        gate_rec = (gates.gate_record(store.list_gates(meta["campaign_id"]))
                    if kind == "engagement" else None)
        # Slot acquired OUTSIDE the 500-wrapper so its 503 (server at the concurrency ceiling) isn't
        # rewritten to a 500; released by the context manager even if generation raises.
        with _generation_slot(request.app.state.generation_semaphore):
            try:
                path = deliverables.generate(
                    kind,
                    snap,
                    meta["label"],
                    gates=gate_rec,
                    protocol_assurance_bundle=protocol_assurance_bundle,
                )
            except Exception as e:  # generation failure (e.g. a malformed snapshot)
                raise HTTPException(500, f"Failed to generate {kind}: {e}") from e
        spec = deliverables.SPECS[kind]
        # PPDIOO document gates DISCLOSE on this surface rather than refuse (the reasoning, and the
        # known residual, are in deliverables.generate's docstring). Surfaced as a response header
        # so it is visible to the SPA and to curl without changing the bytes of the document.
        gate_note = deliverables.gate_disclosure(kind)
        headers = {"X-Gate-Status": f"{gate_note['status']}:"
                                    f"{','.join(gate_note.get('missing') or ['-'])}"} if gate_note else None
        return _send_file(path, spec.media, meta["label"], spec.download_suffix,
                          headers=headers)

    @app.delete("/api/snapshots/{snapshot_id}", status_code=204)
    def delete_snapshot(snapshot_id: RowId):
        deleted = store.delete_snapshot_if_unreceipted(snapshot_id)
        if deleted == "missing":
            raise HTTPException(404, "Snapshot not found")
        if deleted == "receipted":
            raise HTTPException(
                409,
                "A snapshot bound by a canonical comparison receipt is immutable and cannot be "
                "deleted",
            )
        return Response(status_code=204)

    @app.post("/api/compare")
    def compare(body: CompareIn) -> Dict[str, Any]:
        old, old_binding, new, new_binding = _bound_comparison_pair(
            body.old_id, body.new_id)
        return engine.compare_bound_pair(
            old,
            new,
            before_binding=old_binding,
            after_binding=new_binding,
            change_intent=(body.change_intent.model_dump(mode="json")
                           if body.change_intent is not None else None),
        )

    # -- demo --------------------------------------------------------------
    @app.post("/api/demo/seed")
    def demo_seed() -> Dict[str, Any]:
        """One-click: create a 'Sample Fleet' campaign seeded with the bundled sample snapshot."""
        if not SAMPLE_SNAPSHOT.exists():
            raise HTTPException(503, "No bundled sample snapshot available")
        snap = json.loads(SAMPLE_SNAPSHOT.read_text(encoding="utf-8"))
        c = store.create_campaign("Sample Fleet (demo)",
                                  "Bundled sample snapshot — explore AssessHub with zero setup.")
        s = store.add_snapshot(c["id"], "Baseline collection", snap, summary.summarize(snap))
        return {"campaign": store.get_campaign(c["id"]), "snapshot": s}

    # -- frontend (production) --------------------------------------------
    # Serve the built SPA with a history-fallback: hashed assets are served directly, every other
    # non-API path returns index.html so client-side deep links survive a hard refresh. The /api
    # routes above are registered first, so they always win over this catch-all.
    dist_root = Path(dist_dir) if dist_dir is not None else FRONTEND_DIST
    if dist_root.exists():
        assets_dir = dist_root / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            if full_path.startswith("api/"):
                raise HTTPException(404, "Not found")
            # SECURITY: this catch-all sits BELOW the /api access guard (no token/loopback check), so the
            # join MUST be contained. A raw client (browsers normalise `..`, sockets/curl --path-as-is do
            # not) can send `/../../../etc/passwd`; without the resolve()+containment check that FileResponse
            # served ANY file the process can read — the client-snapshot DB, source, keys — unauthenticated.
            # An escaping / absolute / drive-qualified path falls through to index.html, never a file read.
            #
            # The rejection happens BEFORE resolve(), because resolve() is itself a sink — the
            # containment check after it is correct but runs too late. On Windows a path beginning
            # `//` is a UNC name, and resolve() performs a LIVE NETWORK LOOKUP for it: measured
            # through the real app, `GET ///198.51.100.7/share/x` returned 200 after 42.3s, and each
            # such call opens an outbound SMB session in which Windows offers NTLMv2 credentials.
            # That is a credential-leak/relay primitive plus a threadpool-exhaustion DoS (this
            # handler is sync, so each request pins a worker for the whole lookup) on a route with no
            # token check, no loopback check, no Host allowlist and no generation cap — and an egress
            # the air-gapped field posture forbids outright. A NUL byte reaches resolve() the same
            # way and raises ValueError, i.e. an unhandled 500.
            dist = dist_root.resolve()
            segments = [s for s in re.split(r"[\\/]+", full_path) if s not in ("", ".")]
            unsafe = (
                not full_path
                or not segments
                or "\x00" in full_path
                or full_path[0] in "/\\"            # UNC (`//host/share`) or root-absolute
                or ":" in segments[0]               # drive- (`C:`) or scheme-qualified
                or any(s == ".." for s in segments)
            )
            if unsafe:
                return FileResponse(dist / "index.html")
            candidate = (dist / full_path).resolve()
            if candidate.is_relative_to(dist) and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app


def create_default_app() -> FastAPI:
    """Uvicorn factory for the default store, always with boot hardening enabled."""
    return create_app(boot_hardening=True)


class _LazyDefaultApp:
    """Compatibility ASGI object for ``backend.app:app`` without import-time I/O.

    ``serve.main`` remains the production entry because it turns boot failures into field-friendly
    refusals. This object preserves old developer commands while ensuring even that path does not
    open or mutate the default database until a hardened app is actually requested.
    """

    def __init__(self):
        self._app: FastAPI | None = None
        self._lock = threading.Lock()

    def _get(self) -> FastAPI:
        if self._app is None:
            with self._lock:
                if self._app is None:
                    self._app = create_default_app()
        return self._app

    async def __call__(self, scope, receive, send):
        await self._get()(scope, receive, send)


app = _LazyDefaultApp()
