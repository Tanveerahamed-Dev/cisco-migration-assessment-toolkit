"""Client-data confidentiality hardening (Plan A / Tier-1 #4).

The confirmed exposure this closes: with `allow_origins=['*']` and a zero-auth API, ANY
open browser tab could cross-origin read client topology / IPs / serials / parsed configs
and forge gate sign-offs against the default localhost bind; the unsandboxed same-origin
explorer iframe was the innerHTML -> parent -> API escape path.

Model under test:
- CORS: localhost-only origin regex by default (+ ASSESSHUB_CORS_ORIGINS extras).
- ASSESSHUB_TOKEN set   -> Bearer required on ALL /api (except /api/health liveness + OPTIONS).
- ASSESSHUB_TOKEN unset -> /api serves LOOPBACK clients only (dev UX unchanged; the ASGI
  test harness counts as loopback), 403 with an actionable message otherwise.
- The explorer iframe is sandboxed WITHOUT allow-same-origin (the explorer feature-detects
  storage for opaque origins, so this is loss-free)."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `backend` importable

from backend import app as app_module  # noqa: E402
from backend.app import create_app  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("ASSESSHUB_TOKEN", raising=False)
    a = create_app(db_path=str(tmp_path / "test.db"))
    with TestClient(a) as c:
        yield c


# ---------------------------------------------------------------- CORS
def test_internet_origin_gets_no_cors_allow(client):
    r = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


def test_localhost_origin_is_allowed(client):
    r = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_preflight_from_internet_origin_is_refused(client):
    r = client.options("/api/campaigns", headers={
        "Origin": "https://evil.example",
        "Access-Control-Request-Method": "POST",
    })
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


# ------------------------------------------------- no-token mode (loopback-only)
def test_loopback_dev_flow_needs_no_token(client):
    """The zero-config localhost workflow must be untouched: seed + read + write."""
    assert client.get("/api/campaigns").status_code == 200
    assert client.post("/api/demo/seed").status_code == 200


def test_nonloopback_client_is_refused_without_token(client, monkeypatch):
    """Bound non-loopback with no token configured -> every /api data route refuses,
    with a message that says HOW to enable remote access."""
    monkeypatch.setattr(app_module, "_client_is_loopback", lambda request: False)
    r = client.get("/api/campaigns")
    assert r.status_code == 403
    assert "ASSESSHUB_TOKEN" in r.json()["detail"]
    assert client.post("/api/demo/seed").status_code == 403
    # liveness stays open for monitoring probes (no client data in it)
    assert client.get("/api/health").status_code == 200


# ------------------------------------------------- token mode
def test_token_gates_all_api_routes(client, monkeypatch):
    monkeypatch.setenv("ASSESSHUB_TOKEN", "s3cret-token")
    assert client.get("/api/campaigns").status_code == 401
    assert client.get("/api/campaigns",
                      headers={"Authorization": "Bearer wrong"}).status_code == 401
    ok = client.get("/api/campaigns", headers={"Authorization": "Bearer s3cret-token"})
    assert ok.status_code == 200
    assert client.post("/api/demo/seed",
                       headers={"Authorization": "Bearer s3cret-token"}).status_code == 200
    # health liveness stays open even in token mode
    assert client.get("/api/health").status_code == 200


def test_token_applies_to_loopback_too(client, monkeypatch):
    """One mental model: once a token is configured it is required everywhere — a local
    process is not implicitly trusted on a multi-user machine."""
    monkeypatch.setenv("ASSESSHUB_TOKEN", "s3cret-token")
    assert client.post("/api/demo/seed").status_code == 401


# ----------------------------------- cross-site write / blind-CSRF protection
# CORS hides RESPONSES from foreign origins, but `multipart/form-data` and empty-body POSTs
# are CORS "simple requests" that need no preflight and still EXECUTE. Without a request-side
# guard a page on evil.example could blind-fire snapshot upload / ZIP ingest (a heavy engine
# subprocess) / demo-seed against the victim's zero-token loopback bind — store pollution +
# resource-exhaustion DoS. Every state-changing method is checked against the CORS allowlist.
def test_cross_origin_simple_post_is_rejected(client):
    """The pinned regression: a foreign-origin simple-request POST to a write route must be
    refused BEFORE it executes (this exact call returned 200 before the fix)."""
    r = client.post("/api/demo/seed", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert "cross-site" in r.json()["detail"].lower()
    # and it must not have run: no campaign was created by the refused request
    assert client.get("/api/campaigns").json() == []


def test_cross_origin_multipart_upload_is_rejected(client):
    """The multipart upload route (a CORS simple request) is refused at the guard, before the
    body is even parsed — a 403, not a 404/422 from the route."""
    r = client.post("/api/campaigns/1/snapshots",
                    headers={"Origin": "https://evil.example"},
                    files={"file": ("x.json", b'{"devices": []}', "application/json")})
    assert r.status_code == 403


def test_cross_site_write_rejected_via_fetch_metadata(client):
    """Fallback signal: a cross-site write that (unusually) carries no Origin is still caught by
    the browser-set, JS-unforgeable Sec-Fetch-Site header."""
    r = client.post("/api/demo/seed", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_cross_site_delete_is_rejected(client):
    """DELETE is preflight-protected in real browsers, but the server-side guard refuses a
    foreign-origin DELETE too (defense in depth, one rule for all unsafe methods)."""
    r = client.delete("/api/snapshots/1", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_same_origin_write_is_allowed(client):
    """The SPA's own writes carry a localhost Origin (or Sec-Fetch-Site: same-origin) and must
    pass untouched — the write-side guard mirrors the read-side CORS allowlist, nothing more."""
    assert client.post("/api/demo/seed",
                       headers={"Origin": "http://localhost:5173"}).status_code == 200
    assert client.post("/api/demo/seed",
                       headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200
    # a non-browser client (curl / TestClient) sends neither header and is likewise allowed —
    # this is the zero-config loopback path pinned by test_loopback_dev_flow_needs_no_token.
    # KNOWN, DELIBERATE residual: a request with NEITHER header is trusted, so a pre-2019 browser
    # that omits both on a cross-site write is undefended. That trade-off is load-bearing — denying
    # it would break every non-browser client (curl / the ASGI harness) and the zero-config UX —
    # and modern browsers (Chrome 76+/FF 90+/Safari 16.4+) always send at least one of the two.


def test_origin_null_write_is_rejected(client):
    """`Origin: null` is the classic allowlist-bypass: a foreign page mints it via a sandboxed
    iframe + data: URL (and Chrome sends it on cross-site redirects). It is neither a localhost
    origin nor a configured extra, so it must be refused — never whitelisted 'for local dev'."""
    assert client.post("/api/demo/seed", headers={"Origin": "null"}).status_code == 403


def test_localhost_lookalike_origins_are_rejected(client):
    """The allowlist regex is fully anchored: an attacker domain that merely embeds a trusted host
    must NOT match. Covers the suffix, subdomain, userinfo-`@`, and fragment/query tricks."""
    for origin in ("http://localhost.evil.example",
                   "http://127.0.0.1.evil.example",
                   "https://evil.example/localhost",
                   "http://localhost:8000@evil.example",
                   "http://evil.example#http://localhost"):
        r = client.post("/api/demo/seed", headers={"Origin": origin})
        assert r.status_code == 403, f"lookalike origin was not refused: {origin}"


def test_cross_site_ingest_is_rejected_before_the_subprocess(client):
    """The heaviest route (ZIP ingest spawns a bounded-but-expensive engine subprocess) is the
    prime resource-exhaustion target — the guard must refuse a foreign-origin ingest at the door,
    before any body is read or subprocess is launched."""
    r = client.post("/api/campaigns/1/ingest",
                    headers={"Origin": "https://evil.example"},
                    files={"file": ("c.zip", b"PK\x03\x04not-a-real-zip", "application/zip")})
    assert r.status_code == 403


def test_cross_site_write_refused_even_in_token_mode(client, monkeypatch):
    """CSRF protection runs BEFORE the Bearer check, so a foreign-origin write is refused in token
    mode too — even carrying the correct token (defense in depth; one rule for all writes)."""
    monkeypatch.setenv("ASSESSHUB_TOKEN", "s3cret-token")
    r = client.post("/api/demo/seed",
                    headers={"Origin": "https://evil.example",
                             "Authorization": "Bearer s3cret-token"})
    assert r.status_code == 403


# --- production (non-localhost single-origin) deployment: same-origin writes must WORK -------
# The documented production mode (app.py module docstring: "the whole platform runs from one origin
# in production") is a non-loopback bind behind ASSESSHUB_TOKEN, served at e.g. https://assesshub.example.com.
# The SPA's own writes are SAME-ORIGIN there — they must be allowed even though the origin is not
# localhost. The guard must trust the browser's Sec-Fetch-Site oracle (primary), falling back to an
# Origin-equals-own-host comparison for pre-Fetch-Metadata browsers — NOT a hardcoded localhost list.
def test_prod_same_origin_write_allowed_via_fetch_metadata(client):
    """Modern browser on a non-localhost deployment: Sec-Fetch-Site: same-origin is authoritative."""
    r = client.post("/api/demo/seed", headers={"Origin": "https://assesshub.example.com",
                                               "Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 200


def test_prod_same_origin_write_allowed_via_origin_host_match(client):
    """Pre-Fetch-Metadata browser (no Sec-Fetch-Site): Origin equals the host the request was
    addressed to => same-origin => allowed. Host header simulates the non-localhost deployment."""
    r = client.post("/api/demo/seed", headers={"Origin": "http://assesshub.example.com:8000",
                                               "Host": "assesshub.example.com:8000"})
    assert r.status_code == 200


def test_prod_cross_site_write_still_refused(client):
    """The fix must not over-open: on that same non-localhost deployment a genuine foreign origin is
    still refused — via Sec-Fetch-Site: cross-site, and via the no-metadata Origin!=Host fallback."""
    assert client.post("/api/demo/seed",
                       headers={"Host": "assesshub.example.com",
                                "Origin": "https://evil.example",
                                "Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.post("/api/demo/seed",
                       headers={"Host": "assesshub.example.com",
                                "Origin": "https://evil.example"}).status_code == 403


def test_allowlisted_cross_origin_frontend_can_write(client, monkeypatch):
    """Split-origin deployment: the UI is a DIFFERENT site than the API, explicitly trusted via
    ASSESSHUB_CORS_ORIGINS (CORS already grants it reads). Its writes legitimately carry
    Sec-Fetch-Site: cross-site — an admin-allowlisted origin must be honored on the WRITE side too,
    for read/write parity. This must hold on a MODERN browser (Sec-Fetch-Site present)."""
    monkeypatch.setenv("ASSESSHUB_CORS_ORIGINS", "https://frontend.example.com")
    r = client.post("/api/demo/seed", headers={"Origin": "https://frontend.example.com",
                                               "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 200


def test_allowlist_does_not_extend_to_localhost_bypass(client):
    """The allowlist override must be EXACT and not leak the blanket localhost trust: a localhost-origin
    page issuing a cross-site write to a non-localhost deployment is still refused (Sec-Fetch-Site wins;
    only an explicit ASSESSHUB_CORS_ORIGINS entry overrides it, never the localhost regex)."""
    r = client.post("/api/demo/seed", headers={"Origin": "http://localhost:9999",
                                               "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


# ------------------------------------------------- static source pins
def test_no_wildcard_cors_in_source():
    src = (_REPO / "webapp" / "backend" / "app.py").read_text(encoding="utf-8")
    assert 'allow_origins=["*"]' not in src and "allow_origins=['*']" not in src, \
        "CORS wildcard must not return"


def test_explorer_iframe_is_sandboxed_without_same_origin():
    """The iframe must carry a sandbox WITHOUT allow-same-origin — same-origin was the
    escape path from explorer innerHTML to the parent app and its API."""
    tsx = (_REPO / "webapp" / "frontend" / "src" / "pages" / "Snapshot.tsx").read_text(encoding="utf-8")
    assert "sandbox=" in tsx, "explorer iframe lost its sandbox attribute"
    sandbox_line = next(ln for ln in tsx.splitlines() if "sandbox=" in ln)
    assert "allow-scripts" in sandbox_line
    assert "allow-same-origin" not in sandbox_line, \
        "allow-same-origin would hand the iframe the parent origin + zero-auth API"
