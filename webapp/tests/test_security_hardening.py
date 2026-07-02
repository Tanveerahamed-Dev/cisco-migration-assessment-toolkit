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
