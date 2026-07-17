"""GET-based resource-exhaustion hardening for the compute-heavy AssessHub GET routes.

Vector (a follow-up to the CSRF *write* fix — this one never mutates the store): many GET routes do
non-trivial server-side work whose dominant cost is a full multi-MB snapshot parse (store.get_snapshot
-> json.loads), on top of which some render the explorer HTML, generate a DOCX/PPTX, or run an engine
compute. A foreign page a victim visits can trigger any of them with a "simple" cross-origin GET —
fetch(url,{mode:'no-cors'}) or an <img>/<iframe> src — which EXECUTES server-side even though CORS hides
the response, driving CPU/RAM work. Two complementary defenses are asserted here (both in backend/app.py):

  1. Sec-Fetch-Site provenance on EVERY parse/compute/generate GET route (so the vector isn't just
     relocated to an unguarded sibling): an explicit 'cross-site' request is refused (403); our own
     same-origin SPA calls, the sandboxed explorer iframe (same-origin *request*, Origin: null *document*),
     direct navigations (Sec-Fetch-Site: none) and non-browser clients (absent header) all still work.
  2. A concurrency cap on the three heavy document/HTML GENERATORS (explorer, deliverable, PIR report):
     excess simultaneous generations are shed with 503 + Retry-After. Parse/compute routes are NOT capped
     (a normal dashboard load fans out several at once).

Real-browser confirmation of the Sec-Fetch-Site VALUES these tests assume (a same-origin sandboxed iframe
sends `same-origin`; cross-site embeds send `cross-site`) was done empirically in Chromium out-of-band and
is spec-grounded (W3C Fetch Metadata) — TestClient cannot itself emit browser-controlled Sec-Fetch headers.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `backend` importable

from backend import deliverables  # noqa: E402
from backend.app import create_app  # noqa: E402

# A section name that is in the allow-list AND present in every snapshot -> deterministic 200.
_SECTION = "devices"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("ASSESSHUB_TOKEN", raising=False)
    app = create_app(db_path=str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c


def _seed(client) -> int:
    """A real, fully-populated snapshot (the demo sample stores every section)."""
    r = client.post("/api/demo/seed")
    assert r.status_code == 200, r.text
    return r.json()["snapshot"]["id"]


def _seed_ids(client):
    """Seed the demo and materialise the ids the guarded routes need: (campaign, snapshot, execution)."""
    r = client.post("/api/demo/seed")
    assert r.status_code == 200, r.text
    d = r.json()
    sid, cid = d["snapshot"]["id"], d["campaign"]["id"]
    eid = client.post(f"/api/snapshots/{sid}/executions", json={}).json()["id"]
    return cid, sid, eid


def _parse_compute_routes(cid, sid):
    """Guarded routes that return 200 for the demo data (full-snapshot parse and/or engine compute, plus
    the explorer render). Includes the compute_* siblings AND the plain parse routes (graph/cable_map/
    cutover/section/trend) — guarding only some would leave a trivially-equivalent cross-origin bypass."""
    return [
        f"/api/campaigns/{cid}/trend",
        f"/api/snapshots/{sid}/section/{_SECTION}",
        f"/api/snapshots/{sid}/graph",
        f"/api/snapshots/{sid}/cable_map",
        f"/api/snapshots/{sid}/cutover",
        f"/api/snapshots/{sid}/archreview",
        f"/api/snapshots/{sid}/design",
        f"/api/snapshots/{sid}/causal_flows",
        f"/api/snapshots/{sid}/architecture_coverage",
        f"/api/snapshots/{sid}/domain_packs",
        f"/api/snapshots/{sid}/design/nrfu",
        f"/api/snapshots/{sid}/explorer",
    ]


def _generator_routes(sid, eid):
    """The three heavy doc/HTML generators — same-origin returns 200 OR 503 (optional lib), never 403."""
    return [
        f"/api/snapshots/{sid}/deliverable/mop",
        f"/api/executions/{eid}/report",
        f"/api/snapshots/{sid}/explorer",
    ]


# ── defense 1: Sec-Fetch-Site provenance ─────────────────────────────────────────
def test_cross_site_get_is_refused_on_every_guarded_route(client):
    """The core assertion: a cross-site-triggered GET to ANY compute/parse/generate route is refused
    BEFORE any store read or engine work (the deliverable/report cases prove the guard runs ahead of the
    kind/404/503 checks — 403 even for a valid kind and an existing snapshot)."""
    cid, sid, eid = _seed_ids(client)
    routes = _parse_compute_routes(cid, sid) + [f"/api/snapshots/{sid}/deliverable/mop",
                                                f"/api/executions/{eid}/report"]
    for path in routes:
        r = client.get(path, headers={"sec-fetch-site": "cross-site"})
        assert r.status_code == 403, f"{path} must refuse a cross-site GET, got {r.status_code}"
        assert "cross-site" in r.json()["detail"].lower()


def test_same_origin_get_is_allowed(client):
    """The SPA's own fetches and links carry Sec-Fetch-Site: same-origin — never blocked. The generators
    return 200 (or 503 if their optional lib is missing) but never the guard's 403."""
    cid, sid, eid = _seed_ids(client)
    for path in _parse_compute_routes(cid, sid):
        r = client.get(path, headers={"sec-fetch-site": "same-origin"})
        assert r.status_code == 200, f"{path}: same-origin GET must pass ({r.status_code}: {r.text[:200]})"
    for path in _generator_routes(sid, eid):
        assert client.get(path, headers={"sec-fetch-site": "same-origin"}).status_code != 403, path


def test_absent_sec_fetch_site_is_allowed(client):
    """Non-browser clients (curl, monitoring probes, the Python API consumers, this TestClient) send no
    Sec-Fetch-Site. That is not the browser-forgery vector (and matches the web.dev policy's fail-open),
    so it must stay allowed — a header-based guard must never break the API for clients that omit it."""
    cid, sid, eid = _seed_ids(client)
    for path in _parse_compute_routes(cid, sid):
        assert client.get(path).status_code == 200, path


def test_same_site_and_direct_navigation_are_allowed(client):
    """same-site covers a reverse-proxied UI on a sibling subdomain (ASSESSHUB_CORS_ORIGINS); none covers a
    user opening the URL directly (bookmark/typed). Both are legitimate — only 'cross-site' is refused."""
    sid = _seed(client)
    for site in ("same-site", "none"):
        r = client.get(f"/api/snapshots/{sid}/design", headers={"sec-fetch-site": site})
        assert r.status_code == 200, f"sec-fetch-site={site} must pass ({r.status_code})"


def test_sandboxed_explorer_iframe_origin_null_still_loads(client):
    """The regression the follow-up flags. This asserts the SERVER-SIDE CONTRACT: a request carrying the
    header shape a same-origin sandboxed iframe actually sends — Sec-Fetch-Site: same-origin with a null/
    absent Origin — must load, because the guard keys on Sec-Fetch-Site and NEVER on Origin (a naive Origin
    check would 403 the embedded explorer at Snapshot.tsx:419). That a real browser sends exactly this shape
    for a same-origin sandboxed iframe is spec-grounded (the request's origin is the parent document, not the
    opaque doc origin) and was confirmed empirically in Chromium out-of-band; TestClient cannot itself emit
    the browser-controlled Sec-Fetch headers, so this test alone does not observe the browser behaviour."""
    sid = _seed(client)
    r = client.get(
        f"/api/snapshots/{sid}/explorer",
        headers={
            "sec-fetch-site": "same-origin",
            "sec-fetch-mode": "navigate",
            "sec-fetch-dest": "iframe",
            "origin": "null",           # the sandboxed opaque origin — must NOT be treated as cross-site
        },
    )
    assert r.status_code == 200, r.text[:300]
    assert r.headers["content-type"].startswith("text/html")
    assert "<" in r.text  # rendered HTML, not a JSON error body


def test_cheap_read_routes_are_not_cross_site_guarded(client):
    """The provenance guard is scoped to the compute/parse/generate routes; genuinely cheap metadata reads
    (health, campaign list, snapshot meta) stay governed by CORS + the token/loopback access guard (a
    cross-site page still cannot READ the hidden response). Blanket-blocking them would be an out-of-scope
    behaviour change, so assert it did NOT happen."""
    sid = _seed(client)
    for path in ("/api/health", "/api/campaigns", f"/api/snapshots/{sid}"):
        r = client.get(path, headers={"sec-fetch-site": "cross-site"})
        assert r.status_code == 200, f"{path} must not be provenance-guarded ({r.status_code})"


# ── defense 2: concurrency cap on the heavy generators ───────────────────────────
def _cap_shed_case(tmp_path, monkeypatch, db, make_path):
    """Shared harness: with the cap at 1 and the single slot already held (standing in for one heavy
    generation in flight), the next generation is shed with 503 + Retry-After; once the slot frees, it
    succeeds again — proving the cap sheds load rather than wedging the route."""
    monkeypatch.delenv("ASSESSHUB_TOKEN", raising=False)
    monkeypatch.setenv("ASSESSHUB_MAX_CONCURRENT_GENERATIONS", "1")
    app = create_app(db_path=str(tmp_path / db))
    with TestClient(app) as c:
        path = make_path(c)
        assert app.state.generation_semaphore.acquire(blocking=False)  # occupy the only slot
        try:
            r = c.get(path, headers={"sec-fetch-site": "same-origin"})
            assert r.status_code == 503, r.text[:200]
            assert r.headers.get("retry-after") == "5"
        finally:
            app.state.generation_semaphore.release()
        assert c.get(path).status_code == 200


def test_explorer_generation_sheds_load_when_at_capacity(tmp_path, monkeypatch):
    _cap_shed_case(tmp_path, monkeypatch, "cap_explorer.db",
                   lambda c: f"/api/snapshots/{_seed(c)}/explorer")


def test_deliverable_generation_is_capped(tmp_path, monkeypatch):
    if not deliverables.availability().get("mop"):
        pytest.skip("python-docx not installed — the availability 503 pre-empts the concurrency cap")
    _cap_shed_case(tmp_path, monkeypatch, "cap_deliverable.db",
                   lambda c: f"/api/snapshots/{_seed(c)}/deliverable/mop")


def test_pir_report_generation_is_capped(tmp_path, monkeypatch):
    """The PIR report is the third heavy generator (write_pir_docx) — it must share the same cap as the
    other document generators, else it is an un-throttled DOCX-generation twin of /deliverable."""
    if not deliverables.have_docx():
        pytest.skip("python-docx not installed — the availability 503 pre-empts the concurrency cap")

    def make(c):
        sid = _seed(c)
        return f"/api/executions/{c.post(f'/api/snapshots/{sid}/executions', json={}).json()['id']}/report"

    _cap_shed_case(tmp_path, monkeypatch, "cap_report.db", make)


def test_default_capacity_allows_normal_single_use(client):
    """Sanity: with the generous default cap a plain sequence of downloads is never shed (the cap must
    bound bursts without biting ordinary one-at-a-time use)."""
    sid = _seed(client)
    for _ in range(3):
        assert client.get(f"/api/snapshots/{sid}/explorer").status_code == 200
