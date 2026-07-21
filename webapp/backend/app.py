"""AssessHub FastAPI application.

REST surface over the snapshot store. The engine produces snapshots (CLI); this serves, slices,
diffs, trends, and renders them. Also serves the built frontend (webapp/frontend/dist) when present,
so the whole platform runs from one origin in production.
"""

from __future__ import annotations

import contextlib
import hmac
import json
import os
import re
import tempfile
import threading
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from cisco_toolkit import brand_tokens

from . import cutover, deliverables, engine, execution, gates, graph, ingest, serve, summary
from .storage import Store

_HERE = Path(__file__).resolve().parent
_WEBAPP = _HERE.parent
DEFAULT_DB = os.environ.get("ASSESSHUB_DB", str(_WEBAPP / "data" / "assesshub.db"))
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


class CampaignIn(BaseModel):
    name: str
    description: str = ""


class CompareIn(BaseModel):
    old_id: int
    new_id: int


class FolderIngestIn(BaseModel):
    path: str
    label: str = ""


class ExecutionIn(BaseModel):
    label: str = ""
    operator: str = ""


class StepIn(BaseModel):
    wave: str
    index: int
    status: str  # pending | done | skipped
    note: str = ""
    operator: str = ""


class CheckIn(BaseModel):
    wave: str
    index: int
    result: str  # pending | pass | fail | na
    observed: str = ""
    operator: str = ""


class CloseoutIn(BaseModel):
    wave: str
    decision: str  # COMPLETE | ROLLED BACK | DEFERRED
    note: str = ""
    operator: str = ""


class EventIn(BaseModel):
    kind: str  # note | deviation
    text: str
    wave: str = ""
    operator: str = ""


class FinishIn(BaseModel):
    status: str  # completed | aborted
    note: str = ""
    operator: str = ""


class GateIn(BaseModel):
    # Length caps (V3.23.159): these strings are stored verbatim, echoed by every board fetch and
    # rendered into a DOCX table cell — unbounded input was a DB/document bloat vector.
    wave: str = Field(min_length=1, max_length=120)
    gate: str = Field(max_length=40)      # a cisco_toolkit.engagement.GATE_SEQUENCE key
    decision: str = Field(max_length=20)  # go | no-go | slipped | pending (pending clears)
    signed_by: str = Field(default="", max_length=120)
    note: str = Field(default="", max_length=500)


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
    only — e.g. a reverse-proxied UI on another host). Empty by default."""
    raw = os.environ.get("ASSESSHUB_CORS_ORIGINS", "")
    return [o.strip() for o in raw.split(",") if o.strip()]


def _client_is_loopback(request: Request) -> bool:
    """True when the ASGI peer is loopback (or an in-process test harness, which has no
    real socket). Deliberately conservative: a peer with a non-loopback IP is NOT loopback.
    NB uvicorn runs proxy_headers=True, so behind a trusted proxy request.client reflects
    X-Forwarded-For — but forwarded_allow_ips defaults to 127.0.0.1, so a REMOTE peer's forged
    header is ignored. The safe posture for any non-loopback / proxied bind is a token
    (ASSESSHUB_TOKEN): token mode ignores peer position entirely, closing this deployment edge."""
    host = getattr(request.client, "host", None)
    if host is None or host == "testclient":
        return True
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
    TLS-terminating proxy): only `cross-site` (and any unknown value) is refused; `same-origin`/`same-site`/
    `none` are the app's own UI / user-initiated nav. Note the blanket localhost trust is deliberately NOT
    an override here — a localhost page issuing a cross-site write to a non-localhost deployment must still
    be refused. When Sec-Fetch-Site is absent (pre-2023 browsers) fall back to `Origin` (same-origin host
    match / localhost / extras). A request carrying NEITHER header is a non-browser client (curl, the ASGI
    test harness): browsers ALWAYS attach `Origin` to an unsafe-method request (real origin or `null`), so
    this branch is never a cross-site browser write, and allowing it keeps the zero-config loopback dev
    flow (and its pinned test) untouched."""
    if request.method not in _UNSAFE_METHODS:
        return False
    origin = request.headers.get("origin")
    if origin is not None and origin in _cors_origins():
        return False
    site = request.headers.get("sec-fetch-site")
    if site is not None:
        return site not in ("same-origin", "same-site", "none")
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
# resource-exhaustion DoS. Token mode needs no Host check: a rebound page cannot forge the Bearer
# credential (it is not a cookie the browser auto-attaches), so the token is already the authority.
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


def _parse_snapshot_bytes(raw: bytes) -> Dict[str, Any]:
    try:
        snap = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=400, detail=f"Not valid snapshot JSON: {e}") from e
    if not isinstance(snap, dict) or "devices" not in snap:
        raise HTTPException(status_code=400,
                            detail="JSON is not an engine snapshot (missing top-level 'devices').")
    return snap


def _send_file(path: str, media_type: str, filename_stem: str, suffix: str) -> FileResponse:
    """Stream a generated temp file and delete it afterwards; filename is sanitized."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename_stem).strip("_") or "file"
    return FileResponse(
        path, media_type=media_type, filename=f"{safe}{suffix}",
        background=BackgroundTask(lambda p=path: os.path.exists(p) and os.unlink(p)),
    )


# --- compute-heavy GET hardening (GET-based resource-exhaustion follow-up) ------------
# Many GET routes do non-trivial server-side work whose dominant cost is a full multi-MB snapshot
# parse (store.get_snapshot -> json.loads), on top of which some render the explorer HTML, generate a
# DOCX/PPTX, or run an engine compute_* analysis. A "simple" cross-origin GET — fetch(url,{mode:'no-cors'})
# or an <img>/<iframe> src on a foreign page a victim visits — still EXECUTES on the server even though
# CORS hides the response, so a drive-by page could drive CPU/RAM work (distinct from the CSRF *write*
# issue — this vector never mutates the store). Two complementary defenses:
#   1. Same-site provenance (EVERY parse/compute/generate GET route: the whole class, so the vector isn't
#      just relocated to a sibling). Refuse an EXPLICITLY cross-site request. Sec-Fetch-Site is a browser-set
#      FORBIDDEN header (WHATWG Fetch: the `Sec-` prefix means page JS cannot forge or strip it), so it
#      cleanly separates our own same-origin SPA calls — including the sandboxed explorer iframe, whose LOAD
#      request is same-origin (the request's origin is the parent SPA, computed before the sandbox's opaque
#      origin exists) even though its DOCUMENT is opaque — from a cross-site embed. Keying on Sec-Fetch-Site
#      and NEVER on Origin is what keeps that iframe working (its own Origin is null). The allow-set
#      {same-origin, same-site, none, absent} is web.dev's Fetch-Metadata Resource Isolation Policy; we are
#      deliberately STRICTER (we also block cross-site *navigations*, so a cross-site <iframe> embed of the
#      explorer is refused too). Verified against real Chromium: same-origin iframe load -> same-origin;
#      cross-site embed (iframe/img/no-cors fetch) -> cross-site.
#   2. A concurrency cap on the three heavy GENERATORS (explorer render, deliverable, PIR report), so even a
#      same-origin burst or a non-browser flood (which defense 1 can't see) can't run unbounded heavy
#      generations in parallel — excess load is shed with 503 + Retry-After. The parse/compute routes are
#      NOT capped: a normal dashboard load fans out several of them at once, so throttling that would be wrong.
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


def _forbid_cross_site(request: Request) -> None:
    """Dependency guard for the compute-heavy GET routes: reject a cross-site-triggered request before
    any store read or engine compute (fail-fast, and so a foreign page gets no snapshot-existence oracle)."""
    if _cross_site_request(request):
        raise HTTPException(
            status_code=403,
            detail="This endpoint runs server-side compute and cannot be requested cross-site; "
                   "open AssessHub directly.")


def _max_concurrent_generations() -> int:
    """Ceiling on concurrent heavy deliverable/explorer generations (env ASSESSHUB_MAX_CONCURRENT_GENERATIONS,
    default 6): generous enough never to bite a small team's concurrent downloads, low enough to bound a
    burst's peak CPU/RAM. Always >= 1; a non-integer env value falls back to the default."""
    try:
        return max(1, int(os.environ.get("ASSESSHUB_MAX_CONCURRENT_GENERATIONS", "6")))
    except ValueError:
        return 6


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


def create_app(db_path: str | None = None, dist_dir: str | os.PathLike | None = None,
               boot_hardening: bool = False) -> FastAPI:
    """``dist_dir`` overrides where the built SPA is served from (default: the checkout's
    webapp/frontend/dist) — the hook the Atlas entry module uses to point at the bundled copy
    inside a frozen build (webapp/backend/serve.py, ADR-0004 P1). ``boot_hardening`` threads the
    P3 unplug-safety boot (integrity check + backup — see storage.Store) and may raise
    StoreCorruptError; only the production entry turns it on."""
    store = Store(db_path or DEFAULT_DB, boot_hardening=boot_hardening)
    app = FastAPI(
        title="AssessHub",
        version=engine.ENGINE_SCHEMA_VERSION,
        description="A live web platform over the Cisco Migration-Assessment engine.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),                 # env extras only; empty by default
        allow_origin_regex=_LOCALHOST_ORIGIN_RE,       # localhost on any port — never '*'
        allow_methods=["*"], allow_headers=["*"],
    )

    @app.middleware("http")
    async def _api_access_guard(request: Request, call_next):
        """Registered AFTER (so wrapping OUTSIDE) CORSMiddleware; skips OPTIONS so
        preflights fall through to CORS. Cross-site writes are refused (CSRF). Token set ->
        Bearer required on all /api; token unset -> /api is loopback-only AND the Host header
        must name a loopback target (DNS-rebinding guard, see _request_host_allowed).
        Health/liveness stays open."""
        path = request.url.path
        if (request.method == "OPTIONS" or not path.startswith("/api/")
                or path == "/api/health"):
            return await call_next(request)
        # Refuse state-changing requests driven by a foreign origin BEFORE any auth check, so
        # the "no cross-site writes" invariant holds identically in token and no-token modes.
        if _cross_site_write(request):
            return JSONResponse({"detail": "Cross-site state-changing request refused: a write "
                                           "must originate from the AssessHub UI, not another "
                                           "site (CSRF protection)."},
                                status_code=403)
        token = os.environ.get("ASSESSHUB_TOKEN", "")
        if token:
            supplied = request.headers.get("authorization", "")
            if not hmac.compare_digest(supplied.encode("utf-8", "replace"),
                                       f"Bearer {token}".encode("utf-8")):
                return JSONResponse({"detail": "This AssessHub requires an API token: "
                                               "send 'Authorization: Bearer <ASSESSHUB_TOKEN>'."},
                                    status_code=401)
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

    app.state.store = store
    # Bound concurrent heavy deliverable/explorer generations for this app (see _generation_slot).
    app.state.generation_semaphore = threading.BoundedSemaphore(_max_concurrent_generations())

    # -- meta --------------------------------------------------------------
    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        return {"status": "ok", "engine_schema": engine.ENGINE_SCHEMA_VERSION,
                "sample_available": SAMPLE_SNAPSHOT.exists()}

    @app.get("/api/meta")
    def meta() -> Dict[str, Any]:
        return {
            "engine_schema": engine.ENGINE_SCHEMA_VERSION,
            "severity_order": summary.SEVERITY_ORDER,
            "bands": summary.BANDS,
            "section_labels": [{"key": k, "label": v} for k, v in summary.SECTION_LABELS],
            "deliverables": deliverables.catalogue(),
            # ADR-0004 D1: the SPA renders the brand it is SERVED — the values live in ONE place
            # (cisco_toolkit/brand_tokens.py), so a rename never touches the frontend.
            "app": {
                "name": brand_tokens.APP_NAME,
                "byline": brand_tokens.APP_BYLINE,
                "title": brand_tokens.APP_TITLE,
                "release": serve._release_version(),
            },
        }

    # -- campaigns ---------------------------------------------------------
    @app.get("/api/campaigns")
    def list_campaigns() -> List[Dict[str, Any]]:
        return store.list_campaigns()

    @app.post("/api/campaigns", status_code=201)
    def create_campaign(body: CampaignIn) -> Dict[str, Any]:
        return store.create_campaign(body.name, body.description)

    @app.get("/api/campaigns/{campaign_id}")
    def get_campaign(campaign_id: int) -> Dict[str, Any]:
        c = store.get_campaign(campaign_id)
        if not c:
            raise HTTPException(404, "Campaign not found")
        return c

    @app.delete("/api/campaigns/{campaign_id}", status_code=204)
    def delete_campaign(campaign_id: int):
        if not store.delete_campaign(campaign_id):
            raise HTTPException(404, "Campaign not found")
        # A bare 204 — JSONResponse(content=None) would serialize a "null" body, which uvicorn
        # rejects on a 204 with an ASGI RuntimeError on every delete.
        return Response(status_code=204)

    @app.get("/api/campaigns/{campaign_id}/trend",
             dependencies=[Depends(_forbid_cross_site)])   # parses EVERY snapshot in the campaign
    def campaign_trend(campaign_id: int) -> Dict[str, Any]:
        c = store.get_campaign(campaign_id)
        if not c:
            raise HTTPException(404, "Campaign not found")
        snaps = [store.get_snapshot(s["id"]) for s in c["snapshots"]]
        snaps = [s for s in snaps if s]
        return engine.campaign_trend(snaps)

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
    def get_gates(campaign_id: int) -> Dict[str, Any]:
        if not store.campaign_exists(campaign_id):
            raise HTTPException(404, "Campaign not found")
        return {"cadence": gates.cadence(),
                "waves": _campaign_waves(campaign_id),
                "records": gates.annotate_out_of_order(store.list_gates(campaign_id))}

    @app.post("/api/campaigns/{campaign_id}/gates")
    def set_gate(campaign_id: int, body: GateIn) -> Dict[str, Any]:
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
    async def upload_snapshot(campaign_id: int, file: UploadFile = File(...),
                              label: str = Form("")) -> Dict[str, Any]:
        if not store.get_campaign(campaign_id):
            raise HTTPException(404, "Campaign not found")
        # Hard size cap (chunked) like the sibling /ingest endpoint -- `await file.read()` with no bound let a
        # multi-GB upload exhaust server memory before parsing (a trivial DoS on an unauthenticated POST).
        chunks: List[bytes] = []
        received = 0
        while chunk := await file.read(1024 * 1024):
            received += len(chunk)
            if received > ingest.MAX_ARCHIVE_BYTES:
                raise HTTPException(
                    413, f"Snapshot exceeds the {ingest.MAX_ARCHIVE_BYTES // (1024 * 1024)} MB upload limit")
            chunks.append(chunk)
        snap = _parse_snapshot_bytes(b"".join(chunks))
        lbl = label.strip() or (file.filename or "snapshot").rsplit(".", 1)[0]
        return store.add_snapshot(campaign_id, lbl, snap, summary.summarize(snap))

    @app.post("/api/campaigns/{campaign_id}/ingest", status_code=201)
    async def ingest_collection(campaign_id: int, file: UploadFile = File(...),
                                label: str = Form("")) -> Dict[str, Any]:
        """Upload a raw collection ZIP (per-device show-command outputs); the real engine pipeline
        runs server-side and the resulting snapshot is stored like an uploaded one."""
        if not store.get_campaign(campaign_id):
            raise HTTPException(404, "Campaign not found")
        # Read with a hard cap — the uncompressed-size guard inside ingest can only run after the
        # whole body is in memory, which is too late against a multi-GB upload.
        chunks: List[bytes] = []
        received = 0
        while chunk := await file.read(1024 * 1024):
            received += len(chunk)
            if received > ingest.MAX_ARCHIVE_BYTES:
                raise HTTPException(
                    413, f"Archive exceeds the {ingest.MAX_ARCHIVE_BYTES // (1024 * 1024)} MB upload limit")
            chunks.append(chunk)
        raw = b"".join(chunks)
        try:
            # The engine run blocks for seconds-to-minutes; off the event loop so the rest of the
            # API (including a live war-room console) stays responsive.
            snap, report = await run_in_threadpool(ingest.run_collection_zip, raw)
        except ingest.IngestError as e:
            raise HTTPException(400, str(e)) from e
        except ingest.EngineRunError as e:
            raise HTTPException(500, str(e)) from e
        lbl = label.strip() or (file.filename or "collection").rsplit(".", 1)[0]
        meta = store.add_snapshot(campaign_id, lbl, snap, summary.summarize(snap))
        meta["ingest"] = report
        return meta

    @app.post("/api/campaigns/{campaign_id}/ingest-folder", status_code=201)
    async def ingest_collection_folder(campaign_id: int, body: FolderIngestIn) -> Dict[str, Any]:
        """Ingest a SERVER-LOCAL collection folder — the portable-app 'one door' path (ADR-0004
        P1): on the stick the collection already sits beside the app, so a ZIP round-trip is pure
        friction. Same engine pipeline and the same middleware guards as every write (access guard
        + cross-site refusal); the folder is only READ — outputs land in a private temp workdir."""
        if not store.get_campaign(campaign_id):
            raise HTTPException(404, "Campaign not found")
        try:
            snap, report = await run_in_threadpool(ingest.run_collection_folder, body.path)
        except ingest.IngestError as e:
            raise HTTPException(400, str(e)) from e
        except ingest.EngineRunError as e:
            raise HTTPException(500, str(e)) from e
        lbl = body.label.strip() or Path(body.path).name or "folder"
        meta = store.add_snapshot(campaign_id, lbl, snap, summary.summarize(snap))
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
        if isinstance(summ, dict) and summ.get("engine_schema") == engine.ENGINE_SCHEMA_VERSION:
            return meta
        snap = store.get_snapshot(snapshot_id)
        if snap is None:                       # row vanished between meta read and heal — serve what we have
            return meta
        fresh = summary.summarize(snap)
        store.update_summary(snapshot_id, fresh)
        meta = dict(meta)
        meta["summary"] = fresh
        return meta

    @app.get("/api/snapshots/{snapshot_id}")
    def get_snapshot(snapshot_id: int) -> Dict[str, Any]:
        meta = store.get_snapshot_meta(snapshot_id)
        if not meta:
            raise HTTPException(404, "Snapshot not found")
        return _summary_freshened(snapshot_id, meta)

    @app.get("/api/snapshots/{snapshot_id}/section/{name}",
             dependencies=[Depends(_forbid_cross_site)])   # full-snapshot parse per call
    def get_section(snapshot_id: int, name: str) -> Dict[str, Any]:
        if name not in _ALLOWED_SECTIONS:
            raise HTTPException(400, f"Unknown section '{name}'")
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
            _has_blind = any(isinstance(h, dict) and h.get("band") == "Insufficient Data"
                             for h in (snap.get("health_scores") or []))
            _bands = (data.get("summary") or {}).get("bands") if isinstance(data, dict) else None
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

    @app.get("/api/snapshots/{snapshot_id}/graph",
             dependencies=[Depends(_forbid_cross_site)])
    def snapshot_graph(snapshot_id: int) -> Dict[str, Any]:
        meta = store.get_snapshot_meta(snapshot_id)
        snap = store.get_snapshot(snapshot_id)
        if snap is None or meta is None:
            raise HTTPException(404, "Snapshot not found")
        keystones = [k.get("host") for k in (meta["summary"].get("keystones") or []) if k.get("host")]
        return graph.build_graph(snap, keystones)

    @app.get("/api/snapshots/{snapshot_id}/cable_map",
             dependencies=[Depends(_forbid_cross_site)])
    def snapshot_cable_map(snapshot_id: int) -> Dict[str, Any]:
        """EDA-style physical cable map (Python SSOT snap['cable_map']): CDP/LLDP links laid out in role
        tiers, cables coloured by operational status. Recomputed from evidence for pre-feature snapshots."""
        snap = store.get_snapshot(snapshot_id)
        if snap is None:
            raise HTTPException(404, "Snapshot not found")
        return graph.cable_map_from_snapshot(snap)

    @app.get("/api/snapshots/{snapshot_id}/cutover",
             dependencies=[Depends(_forbid_cross_site)])
    def snapshot_cutover(snapshot_id: int) -> Dict[str, Any]:
        """Gated, pilot-first cutover plan (run-of-show) synthesized from the snapshot's migration model."""
        snap = store.get_snapshot(snapshot_id)
        if snap is None:
            raise HTTPException(404, "Snapshot not found")
        return cutover.build_plan(snap)

    @app.get("/api/snapshots/{snapshot_id}/archreview",
             dependencies=[Depends(_forbid_cross_site)])
    def snapshot_archreview(snapshot_id: int) -> Dict[str, Any]:
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

    @app.get("/api/snapshots/{snapshot_id}/causal_flows",
             dependencies=[Depends(_forbid_cross_site)])
    def snapshot_causal_flows(snapshot_id: int) -> Dict[str, Any]:
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

    @app.get("/api/snapshots/{snapshot_id}/design",
             dependencies=[Depends(_forbid_cross_site)])
    def snapshot_design(snapshot_id: int) -> Dict[str, Any]:
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

    @app.get("/api/snapshots/{snapshot_id}/architecture_coverage",
             dependencies=[Depends(_forbid_cross_site)])   # same lazy compute_* class as /causal_flows
    def snapshot_architecture_coverage(snapshot_id: int) -> Dict[str, Any]:
        """Architecture-coverage SSOT (engine compute_architecture_coverage): which architecture CLASSES were
        OBSERVED vs not, across both ingestion channels (ssh show-text / json controller-REST), and what fired
        -- the SAME map the explorer's ✎Design view renders. Coverage-honest: 'not-observed' is NOT 'healthy'.
        Prefers the stored section; computes server-side with the same engine function otherwise (one source of
        truth -- the dashboard never re-derives coverage)."""
        return _resolve_architecture_coverage(snapshot_id)

    @app.get("/api/snapshots/{snapshot_id}/domain_packs",
             dependencies=[Depends(_forbid_cross_site)])   # resolves architecture_coverage (may compute)
    def snapshot_domain_packs(snapshot_id: int) -> Dict[str, Any]:
        """Which DOMAIN SKILL-PACKS (DC/ACI · Enterprise/SD-Access · SP/MPLS-SR · Security/ISE-TrustSec) this
        snapshot engages (Phase-3 / D6). A pack loads IFF one of its architecture classes was OBSERVED in the
        SAME coverage map above -- retrieval-selected by evidence, never a default headcount. Selection is the
        engine SSOT (cisco_toolkit.domain_packs.select_packs); the dashboard never re-derives it in JS.
        Coverage-honest: no observed class -> no packs, said plainly (never 'no domain concerns')."""
        from cisco_toolkit.domain_packs import select_packs
        return select_packs(_resolve_architecture_coverage(snapshot_id))

    @app.post("/api/snapshots/{snapshot_id}/design")
    def design_overlay(snapshot_id: int, requirements: Dict[str, Any]) -> Dict[str, Any]:
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

    @app.get("/api/snapshots/{snapshot_id}/design/nrfu",
             dependencies=[Depends(_forbid_cross_site)])   # computes the blueprint + NRFU on the fly
    def design_nrfu(snapshot_id: int) -> Dict[str, Any]:
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
    def design_nrfu_overlay(snapshot_id: int, requirements: Dict[str, Any]) -> Dict[str, Any]:
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

    # -- execution runs (war room) ------------------------------------------
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
            if not store.save_execution(execution_id, rec["state"]):
                raise HTTPException(404, "Execution run was deleted")
            return execution.with_progress(execution_id, rec["snapshot_id"], rec["state"])

    @app.post("/api/snapshots/{snapshot_id}/executions", status_code=201)
    def start_execution(snapshot_id: int, body: ExecutionIn) -> Dict[str, Any]:
        """Materialize the snapshot's cutover plan into a live, frozen execution run."""
        snap = store.get_snapshot(snapshot_id)
        if snap is None:
            raise HTTPException(404, "Snapshot not found")
        # Build the (label-independent) plan OFF the lock — it can block for a while and must not
        # serialize the whole war room.
        state = execution.start_run(snap, body.label, body.operator)
        if not state["waves"]:
            raise HTTPException(400, "No migration waves were derived from this snapshot — nothing to execute")
        # Auto-label + insert ATOMICALLY: two concurrent starts must not both read the same
        # execution count and mint duplicate "Cutover run N" labels. The ordinal is cosmetic (the
        # row id is the real key) but a duplicate label misreads in the war-room run list.
        with execution.MUTATION_LOCK:
            if not body.label.strip():
                state["label"] = f"Cutover run {store.count_executions(snapshot_id) + 1}"
            eid = store.create_execution(snapshot_id, state)
        return execution.with_progress(eid, snapshot_id, state)

    @app.get("/api/snapshots/{snapshot_id}/executions")
    def list_executions(snapshot_id: int) -> List[Dict[str, Any]]:
        if not store.get_snapshot_meta(snapshot_id):
            raise HTTPException(404, "Snapshot not found")
        return store.list_executions(snapshot_id)

    @app.get("/api/executions/{execution_id}")
    def get_execution(execution_id: int) -> Dict[str, Any]:
        rec = store.get_execution(execution_id)
        if not rec:
            raise HTTPException(404, "Execution run not found")
        return execution.with_progress(rec["id"], rec["snapshot_id"], rec["state"])

    @app.post("/api/executions/{execution_id}/step")
    def execution_step(execution_id: int, body: StepIn) -> Dict[str, Any]:
        return _mutate_execution(
            execution_id,
            lambda st: execution.apply_step(st, body.wave, body.index, body.status,
                                            body.note, body.operator))

    @app.post("/api/executions/{execution_id}/check")
    def execution_check(execution_id: int, body: CheckIn) -> Dict[str, Any]:
        return _mutate_execution(
            execution_id,
            lambda st: execution.apply_check(st, body.wave, body.index, body.result,
                                             body.observed, body.operator))

    @app.post("/api/executions/{execution_id}/closeout")
    def execution_closeout(execution_id: int, body: CloseoutIn) -> Dict[str, Any]:
        return _mutate_execution(
            execution_id,
            lambda st: execution.apply_closeout(st, body.wave, body.decision,
                                                body.note, body.operator))

    @app.post("/api/executions/{execution_id}/event")
    def execution_event(execution_id: int, body: EventIn) -> Dict[str, Any]:
        return _mutate_execution(
            execution_id,
            lambda st: execution.add_event(st, body.kind, body.text, body.wave, body.operator))

    @app.post("/api/executions/{execution_id}/finish")
    def execution_finish(execution_id: int, body: FinishIn) -> Dict[str, Any]:
        return _mutate_execution(
            execution_id,
            lambda st: execution.finish(st, body.status, body.note, body.operator))

    @app.get("/api/executions/{execution_id}/report",
             dependencies=[Depends(_forbid_cross_site)])
    def execution_report(execution_id: int, request: Request):
        """Post-Implementation Review / as-executed change record for this run, as .docx."""
        rec = store.get_execution(execution_id)
        if not rec:
            raise HTTPException(404, "Execution run not found")
        if not deliverables.have_docx():
            raise HTTPException(503, "python-docx is not installed on the server")
        from .pir_docx import write_pir_docx

        snap_meta = store.get_snapshot_meta(rec["snapshot_id"])
        snap_label = snap_meta["label"] if snap_meta else "snapshot"
        # Same heavy-generator treatment as /deliverable: bound concurrency, and take the slot BEFORE
        # creating the temp file so a shed (503) leaves nothing to clean up.
        with _generation_slot(request.app.state.generation_semaphore):
            fd, path = tempfile.mkstemp(suffix=".docx", prefix="assesshub_pir_")
            os.close(fd)
            try:
                write_pir_docx(path, rec["state"], snap_label)
            except Exception as e:
                if os.path.exists(path):
                    os.unlink(path)
                raise HTTPException(500, f"Failed to generate the PIR: {e}") from e
        return _send_file(
            path, "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            rec["state"].get("label", "run"), "_pir.docx")

    @app.delete("/api/executions/{execution_id}", status_code=204)
    def delete_execution(execution_id: int):
        # Under the mutation lock so a delete can't land inside another request's
        # read-modify-write window (whose save would then be a silent no-op).
        with execution.MUTATION_LOCK:
            if not store.delete_execution(execution_id):
                raise HTTPException(404, "Execution run not found")
        return Response(status_code=204)

    @app.get("/api/snapshots/{snapshot_id}/explorer", response_class=HTMLResponse,
             dependencies=[Depends(_forbid_cross_site)])
    def snapshot_explorer(snapshot_id: int, request: Request) -> HTMLResponse:
        meta = store.get_snapshot_meta(snapshot_id)
        snap = store.get_snapshot(snapshot_id)
        if snap is None or meta is None:
            raise HTTPException(404, "Snapshot not found")
        with _generation_slot(request.app.state.generation_semaphore):   # bound concurrent heavy renders
            html = engine.render_explorer_html(snap, meta["label"])
        return HTMLResponse(content=html)

    @app.get("/api/snapshots/{snapshot_id}/deliverable/{kind}",
             dependencies=[Depends(_forbid_cross_site)])
    def snapshot_deliverable(snapshot_id: int, kind: str, request: Request):
        if kind not in deliverables.SPECS:
            raise HTTPException(400, f"Unknown deliverable '{kind}'")
        meta = store.get_snapshot_meta(snapshot_id)
        snap = store.get_snapshot(snapshot_id)
        if snap is None or meta is None:
            raise HTTPException(404, "Snapshot not found")
        if not deliverables.availability().get(kind):
            raise HTTPException(503, f"{deliverables.SPECS[kind].needs} is not installed on the server")
        # The feedback loop: the engagement plan of record carries the campaign's recorded gate
        # sign-offs (§4.3 "as signed"); every other deliverable is a pure snapshot read.
        gate_rec = (gates.gate_record(store.list_gates(meta["campaign_id"]))
                    if kind == "engagement" else None)
        # Slot acquired OUTSIDE the 500-wrapper so its 503 (server at the concurrency ceiling) isn't
        # rewritten to a 500; released by the context manager even if generation raises.
        with _generation_slot(request.app.state.generation_semaphore):
            try:
                path = deliverables.generate(kind, snap, meta["label"], gates=gate_rec)
            except Exception as e:  # generation failure (e.g. a malformed snapshot)
                raise HTTPException(500, f"Failed to generate {kind}: {e}") from e
        spec = deliverables.SPECS[kind]
        return _send_file(path, spec.media, meta["label"], f"_{kind}.{spec.ext}")

    @app.delete("/api/snapshots/{snapshot_id}", status_code=204)
    def delete_snapshot(snapshot_id: int):
        if not store.delete_snapshot(snapshot_id):
            raise HTTPException(404, "Snapshot not found")
        return Response(status_code=204)

    @app.post("/api/compare")
    def compare(body: CompareIn) -> Dict[str, Any]:
        old = store.get_snapshot(body.old_id)
        new = store.get_snapshot(body.new_id)
        if old is None or new is None:
            raise HTTPException(404, "One or both snapshots not found")
        return engine.snapshot_delta(old, new)

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
            dist = dist_root.resolve()
            candidate = (dist / full_path).resolve()
            if full_path and candidate.is_relative_to(dist) and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
