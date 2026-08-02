"""GET-based resource-exhaustion hardening for the compute-heavy AssessHub GET routes.

Vector (a follow-up to the CSRF *write* fix — this one never mutates the store): many GET routes do
non-trivial server-side work whose dominant cost is a full multi-MB snapshot parse (store.get_snapshot
-> json.loads), on top of which some render the explorer HTML, generate a DOCX/PPTX, or run an engine
compute. A foreign page a victim visits can trigger any of them with a "simple" cross-origin GET —
fetch(url,{mode:'no-cors'}) or an <img>/<iframe> src — which EXECUTES server-side even though CORS hides
the response, driving CPU/RAM work. Two complementary defenses are asserted here (both in backend/app.py):

  1. Sec-Fetch-Site provenance on EVERY /api GET (so the vector isn't just relocated to an unguarded
     sibling): an explicit 'cross-site' request is refused (403); our own same-origin SPA calls, the
     sandboxed explorer iframe (same-origin *request*, Origin: null *document*), direct navigations
     (Sec-Fetch-Site: none) and non-browser clients (absent header) all still work.
     The rule is DERIVED, not listed: `_forbid_cross_site_get` runs inside the one middleware that
     already computes this app's whole API surface, and refuses everything in it except the single
     liveness path. It used to be a per-route `dependencies=[Depends(_forbid_cross_site)]` attachment
     covering the 17 routes someone remembered — see
     test_every_api_get_is_cross_site_guarded_unless_explicitly_exempt for the four expensive GETs
     that were in neither that list nor the "cheap" allow-list, with the measurements.
  2. A concurrency cap on the three heavy document/HTML GENERATORS (explorer, deliverable, PIR report):
     excess simultaneous generations are shed with 503 + Retry-After. Parse/compute routes are NOT capped
     (a normal dashboard load fans out several at once).

Real-browser confirmation of the Sec-Fetch-Site VALUES these tests assume (a same-origin sandboxed iframe
sends `same-origin`; cross-site embeds send `cross-site`) was done empirically in Chromium out-of-band and
is spec-grounded (W3C Fetch Metadata) — TestClient cannot itself emit browser-controlled Sec-Fetch headers.
"""
import asyncio
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `backend` importable

from backend import app as app_mod  # noqa: E402
from backend import deliverables  # noqa: E402
from backend.app import create_app  # noqa: E402

# A section name that is in the allow-list AND present in every snapshot -> deterministic 200.
_SECTION = "devices"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("ASSESSHUB_TOKEN", raising=False)
    app = create_app(db_path=str(tmp_path / "test.db"))
    with TestClient(app, base_url="http://localhost") as c:  # loopback Host passes the DNS-rebinding guard (#384)
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
        # /api/snapshots/{id} is in this list, NOT in the cheap-read list below: whenever the cached
        # summary's engine_schema trails the live one, _summary_freshened does a full snapshot parse,
        # an engine summarize() AND a store.update_summary() DB WRITE. See
        # test_snapshot_meta_is_guarded_because_it_can_parse_and_write for the discriminating case —
        # the demo seed writes a CURRENT-schema summary, so on this fixture the heavy branch never runs.
        f"/api/snapshots/{sid}",
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
    """The liveness probe stays open: a cross-site page still cannot READ the hidden response, and
    blanket-blocking every /api GET including liveness would be an out-of-scope behaviour change, so
    assert it did NOT happen. This is also the NON-VACUITY control for the whole guard — if this
    returned 403 the guard would be unconditional and every other assertion here would prove nothing.

    FOUR routes have now left this list, each for the same reason, which is why membership is no
    longer a matter of opinion (see test_the_only_unguarded_api_get_touches_no_store).
    `/api/snapshots/{id}` moved when `_summary_freshened` was wired into it (see the test below).
    `/api/campaigns` and `/api/campaigns/{id}` call `_summary_freshened` as well, so they are
    expensive AND state-CHANGING. `/api/meta`, `/api/campaigns/{id}/gates`,
    `/api/snapshots/{id}/executions` and `/api/executions/{id}` were never in this list at all — they
    were simply never considered, which is the failure this file now tests against structurally.

    They kept passing here for exactly the reason the sibling test documents: `_seed` writes a
    CURRENT-schema summary, so the heavy branch never runs under this fixture. A cheapness assertion
    that holds only because the fixture manufactured the cheapness is not evidence — which is why
    `/api/health` is now the only member, and it is genuinely a constant-time read.
    """
    _seed(client)
    for path in ("/api/health",):
        r = client.get(path, headers={"sec-fetch-site": "cross-site"})
        assert r.status_code == 200, f"{path} must not be provenance-guarded ({r.status_code})"


def test_campaign_reads_are_guarded_because_they_freshen_summaries(client):
    """The campaign routes are in the expensive/state-changing class, not the cheap one.

    `list_campaigns` and `get_campaign` both call `_summary_freshened`, which can parse a multi-MB
    snapshot and WRITE the refreshed summary back. `_cross_site_write` cannot see that: it keys on
    the HTTP method, and these are GETs. A foreign page's `fetch()` executes even though CORS hides
    the response — the Host is genuinely localhost and the peer is loopback, so neither the
    DNS-rebinding allowlist nor `_client_is_loopback` fires.
    """
    _seed(client)
    for path in ("/api/campaigns", "/api/campaigns/1"):
        r = client.get(path, headers={"sec-fetch-site": "cross-site"})
        assert r.status_code == 403, f"{path} must be provenance-guarded ({r.status_code})"
        # ...and the SPA's own same-origin call must still work, or the guard broke the product.
        ok = client.get(path, headers={"sec-fetch-site": "same-origin"})
        assert ok.status_code == 200, f"{path} same-origin broke ({ok.status_code}): {ok.text[:200]}"


def test_snapshot_meta_is_guarded_because_it_can_parse_and_write(client):
    """[#59] `GET /api/snapshots/{id}` was pinned above as a route that "must not be provenance-guarded",
    and that only held because the demo-seed fixture writes a CURRENT-schema summary first, so
    `_summary_freshened`'s heavy branch never ran in the test. Make the premise discriminating: age the
    stored summary's engine_schema, and the same GET becomes a full multi-MB snapshot parse + an engine
    summarize() + a `store.update_summary()` DATABASE WRITE. It is therefore both a member of the
    expensive-GET class and a state-CHANGING GET — and `_cross_site_write` returns False for GET by
    construction, so the CSRF guard cannot see it and this dependency is the only guard there is."""
    sid = _seed(client)
    store = client.app.state.store
    store.update_summary(sid, {"engine_schema": "V0.0.0-stale", "n_switches": -1})

    # cross-site: refused BEFORE the parse/compute — and, crucially, before the write
    r = client.get(f"/api/snapshots/{sid}", headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 403, r.text
    assert store.get_snapshot_meta(sid)["summary"]["engine_schema"] == "V0.0.0-stale", \
        "a cross-site GET drove a store.update_summary() write"

    # same-origin: the self-heal still runs, so guarding the route did not break the feature
    r = client.get(f"/api/snapshots/{sid}", headers={"sec-fetch-site": "same-origin"})
    assert r.status_code == 200, r.text
    assert r.json()["summary"]["engine_schema"] != "V0.0.0-stale"
    assert store.get_snapshot_meta(sid)["summary"]["engine_schema"] != "V0.0.0-stale"


# ── defense 1, COMPLETENESS: the guard is derived from the route table, not from a list ──────────
#: The ONE /api GET that may answer a cross-site request, mirroring backend.app._API_LIVENESS_PATH.
#: Adding a member here is a DELIBERATE decision and must be justified by
#: test_the_only_unguarded_api_get_touches_no_store, which proves the route reads no store at all.
_EXEMPT_API_GETS = frozenset({"/api/health"})

#: Everything registered OUTSIDE the surface `backend.app.is_guarded_api_path` derives — i.e.
#: unguarded BY CONSTRUCTION — with the reason each is allowed to be, and whether it exists only
#: when the SPA bundle has been built. `test_no_route_is_registered_outside_the_derived_guard_surface`
#: fails when anything else appears here, so the gap cannot open silently (the guard surface is
#: `/api/* + the docs set`; a Mount or a route on another prefix is invisible to it).
#: `{path: (is_registered_now, why_it_may_be_unguarded)}`. The first element is a PREDICATE, not a
#: constant: both entries are conditional on the SPA bundle, so "absent" is only excusable when the
#: bundle really is absent — otherwise a route that quietly stopped being registered would read as
#: an unbuilt frontend.
_UNGUARDED_SURFACE: dict[str, tuple] = {
    "/assets": (lambda: (app_mod.FRONTEND_DIST / "assets").is_dir(),
                "StaticFiles mount for the SPA's content-hashed bundles: no store access, no "
                "client data, and the app's own <script src>/<link href> loads are how it is "
                "meant to be fetched"),
    "/{full_path:path}": (lambda: app_mod.FRONTEND_DIST.is_dir(),
                          "the SPA shell + history fallback: a user following a cross-site link "
                          "must get the app, not a 403 (it reads no store)"),
}

#: GET routes that are legitimately outside the /api surface the guard derives from. The SPA shell
#: must stay reachable from a cross-site link, or a user following one gets a 403 instead of the app.
_NON_API_GET_PATHS = frozenset(_UNGUARDED_SURFACE)


def _api_get_routes(app):
    """Every GET APIRoute the app actually registered, read off app.routes (never a hand list)."""
    from fastapi.routing import APIRoute

    return [r for r in app.routes if isinstance(r, APIRoute) and "GET" in r.methods]


def _materialise(path: str, cid: int, sid: int, eid: int) -> str:
    return (path.replace("{campaign_id}", str(cid))
                .replace("{snapshot_id}", str(sid))
                .replace("{execution_id}", str(eid))
                .replace("{name}", _SECTION)
                .replace("{kind}", "mop"))


def test_every_api_get_is_cross_site_guarded_unless_explicitly_exempt(client):
    """[W2] The guard used to be attached route-by-route with `dependencies=[Depends(...)]`, i.e. a
    hand-maintained list standing in for the class it meant — this repo's most recurrent defect shape.
    Enumerating app.routes on the pre-fix code found FIVE unguarded /api GETs, and the most expensive
    one was in neither the guarded list nor the documented "cheap" allow-list:

        UNGUARDED /api/health                       cross-site -> 200   (intended)
        UNGUARDED /api/meta                         cross-site -> 200   plain 7.8ms  (vs health 1.3ms)
        UNGUARDED /api/campaigns/{id}/gates         cross-site -> 200   plain 3.3ms, snapshot-proportional
        UNGUARDED /api/snapshots/{id}/executions    cross-site -> 200
        UNGUARDED /api/executions/{id}              cross-site -> 200
        (40 sequential cross-site GETs of /api/meta: 200 x40 — it re-probed ten importlib
         find_specs and re-parsed pyproject.toml every time, and took no generation slot.)

    The fix inverts the default: `_forbid_cross_site_get` refuses everything on the API surface the
    access middleware already derives, so a route added tomorrow is guarded WITHOUT anyone
    remembering. What this test therefore polices is the only remaining way to open a hole — putting
    a route in the exemption set — and it fails if `_EXEMPT_API_GETS` grows, if an exempt entry goes
    stale, or if a GET route appears outside the derived surface entirely.
    """
    cid, sid, eid = _seed_ids(client)
    exempt_seen, guarded_seen = set(), 0
    for route in _api_get_routes(client.app):
        if not route.path.startswith("/api"):
            # A GET outside /api is outside what the middleware derives its rule from. Whitelisting
            # one is a decision too: if a future /v2 or /internal GET appears, this fails.
            assert route.path in _NON_API_GET_PATHS, (
                f"{route.path} is a GET outside the /api surface the cross-site guard derives from — "
                "it is unguarded by construction; guard it or record it as non-API here")
            continue
        url = _materialise(route.path, cid, sid, eid)
        r = client.get(url, headers={"sec-fetch-site": "cross-site"})
        if route.path in _EXEMPT_API_GETS:
            exempt_seen.add(route.path)
            assert r.status_code == 200, f"{url} is exempt but answered {r.status_code}"
            continue
        assert r.status_code == 403, f"{url} must refuse a cross-site GET, got {r.status_code}"
        assert "cross-site" in r.json()["detail"].lower(), r.text[:200]
        guarded_seen += 1

        # ...and the SPA's own call must still work, or the guard broke the product.
        ok = client.get(url, headers={"sec-fetch-site": "same-origin"})
        assert ok.status_code != 403, f"{url} same-origin was refused ({ok.status_code})"

    assert guarded_seen >= 21, f"only {guarded_seen} /api GETs enumerated — the sweep went stale"
    assert exempt_seen == set(_EXEMPT_API_GETS), (
        f"exemption set is stale: declared {set(_EXEMPT_API_GETS)}, present {exempt_seen}")


def test_no_route_is_registered_outside_the_derived_guard_surface(client):
    """[F5] The guard surface is DERIVED, but the derivation is itself a shape: `/api/* plus the docs
    set`. Anything registered outside it — a `Mount`, a route on a future `/v2` or `/internal` prefix
    — is unguarded by construction and nothing would have said so. The sweep above only walks
    `APIRoute`s, so it cannot even see the `/assets` StaticFiles mount.

    So enumerate EVERY registered route (Mounts included), classify each with the app's own
    `is_guarded_api_path`, and require anything outside the surface to be recorded in
    `_UNGUARDED_SURFACE` with a reason. A new unguarded prefix or mount fails here instead of
    silently opening the gap.
    """
    app = client.app
    doc_paths = app.state.api_doc_paths
    inside, outside = 0, {}
    for route in app.routes:
        path = getattr(route, "path", None)
        assert path, f"{route!r} exposes no .path — the sweep cannot classify it and would skip a hole"
        if app_mod.is_guarded_api_path(path, doc_paths):
            inside += 1
        else:
            outside[path] = type(route).__name__

    for path, kind in sorted(outside.items()):
        assert path in _UNGUARDED_SURFACE, (
            f"{kind} {path!r} is registered OUTSIDE the surface the access guard derives from "
            "(/api/* + the docs set), so it has no auth, no cross-site read guard and no CSRF "
            "guard. Move it under /api/, or record it in _UNGUARDED_SURFACE with the reason it "
            "may be unguarded.")

    # Staleness the other way: an entry that no longer exists is a rotten justification. Each entry
    # declares exactly when it should be registered, so "absent" is only excused when its own
    # precondition (the built SPA bundle) is false.
    for path, (is_registered_now, _why) in sorted(_UNGUARDED_SURFACE.items()):
        assert (path in outside) == bool(is_registered_now()), (
            f"_UNGUARDED_SURFACE entry {path!r} is "
            f"{'registered but its precondition says it should not be' if path in outside else 'gone'}"
            " — the recorded justification has rotted")

    # NON-VACUITY: the classifier really discriminates — it is not returning True for everything
    # (which would make `outside` empty and the assertions above unfalsifiable), and it does report
    # a hypothetical off-surface prefix as unguarded.
    assert inside >= 40, f"only {inside} routes classified as guarded — the enumeration went stale"
    assert app_mod.is_guarded_api_path("/api/anything", doc_paths)
    assert not app_mod.is_guarded_api_path("/v2/snapshots/1", doc_paths)
    assert not app_mod.is_guarded_api_path("/internal/metrics", doc_paths)
    for p in doc_paths:
        assert app_mod.is_guarded_api_path(p, doc_paths), p


def test_an_admin_configured_origin_is_treated_identically_for_reads_and_writes(tmp_path,
                                                                                monkeypatch):
    """[F1] The read guard and the write guard disagreed about the SAME trusted origin.

    `_cross_site_write` grants an exact `ASSESSHUB_CORS_ORIGINS` match first (the admin configured
    that origin, and CORS already lets it read every response body). `_forbid_cross_site_get` did
    not — so on a split-origin deployment, whose UI labels its own requests `Sec-Fetch-Site:
    cross-site` because the API is on another registrable domain, the configured origin could WRITE
    but could not READ. Measured on the pre-fix code: POST /api/campaigns -> 201, GET
    /api/snapshots/{id}/design -> 403, same Origin, same headers. A guard stricter on reads than on
    writes for one origin is a bug, not a posture; both now consult one helper.
    """
    monkeypatch.delenv("ASSESSHUB_TOKEN", raising=False)
    monkeypatch.setenv("ASSESSHUB_CORS_ORIGINS", "https://ui.example.com")
    app = create_app(db_path=str(tmp_path / "cors_parity.db"))
    with TestClient(app, base_url="http://localhost") as c:
        sid = _seed(c)
        trusted = {"origin": "https://ui.example.com", "sec-fetch-site": "cross-site"}
        foreign = {"origin": "https://evil.example", "sec-fetch-site": "cross-site"}

        # the configured origin: allowed for BOTH (this GET was 403 pre-fix)
        r = c.get(f"/api/snapshots/{sid}/design", headers=trusted)
        assert r.status_code == 200, f"configured origin refused a READ ({r.status_code}): {r.text[:200]}"
        w = c.post("/api/campaigns", json={"name": "split-origin"}, headers=trusted)
        assert w.status_code == 201, f"configured origin refused a WRITE ({w.status_code})"

        # NON-VACUITY, and the whole point of keeping the allowance narrow: an UNCONFIGURED origin
        # is still refused on both, so the parity fix did not turn the guard off.
        assert c.get(f"/api/snapshots/{sid}/design", headers=foreign).status_code == 403
        assert c.post("/api/campaigns", json={"name": "evil"}, headers=foreign).status_code == 403
        # ...and a cross-site request with NO Origin at all (an <img>/<iframe> embed) is still
        # refused: absence of an Origin is not a configured origin (fail closed).
        assert c.get(f"/api/snapshots/{sid}/design",
                     headers={"sec-fetch-site": "cross-site"}).status_code == 403


def test_the_four_omitted_expensive_gets_are_refused_cross_site(client):
    """The named regression for the measurement above: these four answered 200 to a cross-site GET
    before the guard became derivable. Kept as an explicit test so the specific hole is greppable and
    a future refactor that re-narrows the rule fails by name, not only in the sweep."""
    cid, sid, eid = _seed_ids(client)
    for path in ("/api/meta",
                 f"/api/campaigns/{cid}/gates",
                 f"/api/snapshots/{sid}/executions",
                 f"/api/executions/{eid}"):
        r = client.get(path, headers={"sec-fetch-site": "cross-site"})
        assert r.status_code == 403, f"{path} answered {r.status_code} to a cross-site GET"
        assert client.get(path, headers={"sec-fetch-site": "same-origin"}).status_code == 200, path


def test_the_derived_rule_also_covers_the_docs_routes_and_head(client):
    """Two things a PER-ROUTE dependency structurally could not reach, now covered for free because
    the rule is evaluated where the app's API surface is defined:

      * the OpenAPI/docs routes. FastAPI registers them itself, as plain Starlette routes with no
        `dependencies=`, so no per-route attachment could ever have guarded them. Measured before:
        `/openapi.json`, `/docs`, `/redoc` all answered 200 to a cross-site GET. `_api_access_guard`
        already treats them as part of this API's surface (it requires a Bearer for them in token
        mode), so the provenance rule follows the same definition rather than inventing a second one.
      * HEAD. A cross-site HEAD executes the same handler as GET; it is refused identically.

    The doc paths are read from `app.state.api_doc_paths` — the SAME frozenset the middleware derives
    its rule from. This loop used to re-list `(openapi_url, docs_url, redoc_url)` by hand, i.e. a hand
    list inside the file whose thesis is that hand lists are the defect, and it was one item short:
    `swagger_ui_oauth2_redirect_url` ("/docs/oauth2-redirect") is a registered GET route that the app
    guards and this test never exercised."""
    app = client.app
    doc_paths = sorted(app.state.api_doc_paths)
    # NON-VACUITY: the derived set is a STRICT superset of the 3-attribute hand list this loop used
    # to carry — i.e. it exercises at least one guarded docs route the hand list never reached.
    # Expressed against the app's own attributes so it pins the gap, not a literal path spelling.
    hand_list = {p for p in (app.openapi_url, app.docs_url, app.redoc_url) if p}
    assert set(doc_paths) > hand_list, (
        f"derived doc paths {sorted(doc_paths)} are not a superset of the old hand list "
        f"{sorted(hand_list)} — this loop is back to covering only what someone remembered")
    for path in doc_paths:
        assert client.get(path).status_code == 200, path            # unchanged for our own clients
        r = client.get(path, headers={"sec-fetch-site": "cross-site"})
        assert r.status_code == 403, f"{path} answered {r.status_code} to a cross-site GET"
        assert client.head(path, headers={"sec-fetch-site": "cross-site"}).status_code == 403, path

    assert client.head("/api/meta", headers={"sec-fetch-site": "cross-site"}).status_code == 403

    assert client.get("/api/health", headers={"sec-fetch-site": "cross-site"}).status_code == 200


def test_the_spa_shell_is_still_served_to_a_cross_site_navigation(client):
    """The "did the guard break the app" control, made non-inert.

    A user following a link to AssessHub from another site sends Sec-Fetch-Site: cross-site on that
    navigation and must get the app, not a 403. This was asserted as `client.get("/") != 403`, which
    PASSES FOR THE WRONG REASON wherever frontend/dist has not been built: the catch-all route is not
    registered at all, the response is 404, and 404 != 403 — so the control was inert exactly where
    CI runs it, and would have kept passing if the guard had swallowed the shell.

    Assert instead something that can only be true when the shell was actually SERVED, and skip
    loudly (never silently pass) when the bundle is absent."""
    if not app_mod.FRONTEND_DIST.exists():
        pytest.skip(f"SPA bundle not built at {app_mod.FRONTEND_DIST} — the shell route is not "
                    "registered, so this control cannot observe anything; run `npm run build` in "
                    "webapp/frontend to exercise it")

    r = client.get("/", headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 200, f"the SPA shell was refused a cross-site navigation: {r.status_code}"
    assert r.headers["content-type"].startswith("text/html"), r.headers.get("content-type")
    body = r.text.lower()
    assert "<html" in body and "assesshub" in body, body[:200]

    # ...and a deep link (client-side route) gets the shell too, not the guard's JSON refusal.
    deep = client.get("/campaigns/1", headers={"sec-fetch-site": "cross-site"})
    assert deep.status_code == 200, deep.status_code
    assert deep.headers["content-type"].startswith("text/html"), deep.headers.get("content-type")

    # NON-VACUITY: the same cross-site header on the API surface IS refused, so a 200 above is the
    # shell being exempt, not the guard being off in this fixture.
    assert client.get("/api/meta", headers={"sec-fetch-site": "cross-site"}).status_code == 403


def test_the_spa_shell_is_exempt_from_the_guard_without_needing_the_real_bundle(tmp_path,
                                                                                monkeypatch):
    """The same control, made unconditional — because a skip is still not coverage.

    `webapp/frontend/dist` is untracked, so on CI the test above skips and the "the guard did not
    swallow the SPA" property goes UNVERIFIED exactly where it most needs checking. `create_app`
    already takes `dist_dir` (the Atlas frozen-build hook), so build a two-file synthetic bundle and
    exercise the real route + the real middleware against it. The assertion is the bundle's own
    marker text, which can only appear if the shell was actually SERVED — it cannot pass for the
    "route not registered" reason the `!= 403` form did."""
    monkeypatch.delenv("ASSESSHUB_TOKEN", raising=False)
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><html><body><div id=root>SYNTHETIC-SHELL-MARKER</div></body></html>",
        encoding="utf-8")
    (dist / "assets" / "app-abc123.js").write_text("export const marker = 1;\n", encoding="utf-8")

    app = create_app(db_path=str(tmp_path / "shell.db"), dist_dir=dist)
    with TestClient(app, base_url="http://localhost") as c:
        cross = {"sec-fetch-site": "cross-site"}
        for path in ("/", "/campaigns/1"):      # the shell, and a client-side deep link
            r = c.get(path, headers=cross)
            assert r.status_code == 200, f"{path} was refused a cross-site navigation ({r.status_code})"
            assert r.headers["content-type"].startswith("text/html"), r.headers.get("content-type")
            assert "SYNTHETIC-SHELL-MARKER" in r.text, r.text[:200]

        # the /assets Mount too — recorded in _UNGUARDED_SURFACE, so pin that it really is reachable
        a = c.get("/assets/app-abc123.js", headers=cross)
        assert a.status_code == 200, a.status_code
        assert "export const marker" in a.text

        # NON-VACUITY: the guard is ON in this very app — the API surface still refuses the same
        # header, so the 200s above are the shell's exemption, not a disabled guard.
        assert c.get("/api/meta", headers=cross).status_code == 403
        assert c.get("/openapi.json", headers=cross).status_code == 403


def _store_calls_during(client, request_fn):
    """Record every public Store method the app calls while `request_fn` runs.

    The cheapness criterion for an exemption is structural, not a stopwatch: a route whose handler
    touches the store AT ALL has a cost that scales with client data (the store holds multi-MB
    snapshot blobs), so it cannot be certified constant-cost. Timing on a shared CI box would be
    flaky; a call census is deterministic."""
    store = client.app.state.store
    names = [n for n in dir(store)
             if not n.startswith("_") and callable(getattr(store, n, None))]
    assert names, "no public Store methods found — the instrument would prove nothing"
    calls: list[str] = []

    def wrap(name, orig):
        def probe(*a, **kw):
            calls.append(name)
            return orig(*a, **kw)
        return probe

    originals = {n: getattr(store, n) for n in names}
    for n, orig in originals.items():
        setattr(store, n, wrap(n, orig))
    try:
        request_fn()
    finally:
        for n in originals:
            try:
                delattr(store, n)          # drop the instance shadow; the class method returns
            except AttributeError:
                setattr(store, n, originals[n])
    return calls


def test_the_only_unguarded_api_get_touches_no_store(client):
    """[W2] Why /api/health may stay open, asserted rather than assumed.

    The old file said the cheap allow-list held "genuinely cheap" routes, but nothing checked it —
    and the sibling test already records that a cheapness claim which holds only because the fixture
    manufactured it is not evidence. So make it a property: an exempt route must make ZERO store
    calls, i.e. its cost cannot scale with any collected client data. Every exempt route is checked,
    so a future addition to `_EXEMPT_API_GETS` must earn it.
    """
    cid, sid, eid = _seed_ids(client)
    for path in sorted(_EXEMPT_API_GETS):
        url = _materialise(path, cid, sid, eid)
        seen = _store_calls_during(client, lambda: client.get(url))
        assert seen == [], f"{url} is exempt from the cross-site guard but called the store: {seen}"

    # NON-VACUITY: the census is live and DOES see store work — a route that was unguarded on the
    # pre-fix code fails the very criterion that would have been needed to exempt it.
    gates_calls = _store_calls_during(
        client, lambda: client.get(f"/api/campaigns/{cid}/gates"))
    assert gates_calls, "the store census recorded nothing at all — the instrument is inert"
    assert "get_snapshot_section" in gates_calls, gates_calls


def test_meta_does_not_reprobe_optional_libs_and_pyproject_on_every_request(client, monkeypatch):
    """[W2] /api/meta was the most expensive UNGUARDED GET measured (plain 7.8ms vs /api/health 1.3ms
    on this box; 52.3ms vs 12ms on the reporter's), because `deliverables.catalogue()` ran ten
    `importlib.util.find_spec` probes and `serve._release_version()` re-opened and TOML-parsed
    pyproject.toml on EVERY request. Both answers are fixed for the life of the process, so they are
    computed once. This matters for the SPA (it loads /api/meta on every page open) as well as for
    the abuse case, and it is what lets /api/meta be merely guarded rather than also throttled."""
    from backend import serve as serve_mod

    app_mod._meta_build_facts.cache_clear()
    calls = {"catalogue": 0, "release": 0}
    real_catalogue, real_release = deliverables.catalogue, serve_mod._release_version

    def counted_catalogue():
        calls["catalogue"] += 1
        return real_catalogue()

    def counted_release():
        calls["release"] += 1
        return real_release()

    monkeypatch.setattr(deliverables, "catalogue", counted_catalogue)
    monkeypatch.setattr(serve_mod, "_release_version", counted_release)
    try:
        bodies = []
        for _ in range(5):
            r = client.get("/api/meta")
            assert r.status_code == 200, r.text[:200]
            bodies.append(r.json())
        assert calls == {"catalogue": 1, "release": 1}, calls
        # the response is unchanged and still complete — caching must not hollow it out
        assert bodies[0] == bodies[-1]
        assert bodies[0]["deliverables"] and bodies[0]["app"]["release"]
        assert {d["key"] for d in bodies[0]["deliverables"]} == {s for s in deliverables.SPECS}

        # NON-VACUITY: the counters are wired to the code path that actually runs — clearing the
        # cache makes the probes run again, so `1` above is memoisation, not a dead monkeypatch.
        app_mod._meta_build_facts.cache_clear()
        assert client.get("/api/meta").status_code == 200
        assert calls == {"catalogue": 2, "release": 2}, calls
    finally:
        app_mod._meta_build_facts.cache_clear()


def test_deliverable_and_report_routes_do_not_reprobe_optional_libs_per_request(client, monkeypatch):
    """[F4] The sibling exits of the cost `_meta_build_facts` fixed for /api/meta.

    `GET /api/snapshots/{id}/deliverable/{kind}` called `deliverables.availability()` — the SAME ten
    `importlib.util.find_spec` probes — and `GET /api/executions/{id}/report` called
    `have_docx()`, both on EVERY request. Caching one route's copy and leaving two identical ones
    running is not a fix, it is a fix applied to one of three exits. All three now go through
    `_optional_lib_probe`, whose answer cannot change while the process lives.

    The stubs here return "unavailable", so each request answers 503 BEFORE any document generation:
    that 503 is itself the proof the app consulted THIS stub rather than a stale memoised answer.
    """
    from backend import deliverables as deliv

    calls = {"availability": 0, "have_docx": 0}

    def counted_availability():
        calls["availability"] += 1
        return {}

    def counted_have_docx():
        calls["have_docx"] += 1
        return False

    monkeypatch.setattr(deliv, "availability", counted_availability)
    monkeypatch.setattr(deliv, "have_docx", counted_have_docx)

    sid = _seed(client)
    eid = client.post(f"/api/snapshots/{sid}/executions", json={}).json()["id"]
    for _ in range(4):
        assert client.get(f"/api/snapshots/{sid}/deliverable/mop").status_code == 503
        assert client.get(f"/api/executions/{eid}/report").status_code == 503
    assert calls == {"availability": 1, "have_docx": 1}, calls   # 4 and 4 before the fix

    # NON-VACUITY, and the property that keeps the memo honest: it is keyed on the probe CALLABLE,
    # so swapping in a different one re-probes. A plain lru_cache would swallow the new stub — and
    # would swallow the sibling suites' `monkeypatch.setattr(deliverables, "availability", ...)`.
    def counted_availability_again():
        calls["availability"] += 1
        return {}

    monkeypatch.setattr(deliv, "availability", counted_availability_again)
    assert client.get(f"/api/snapshots/{sid}/deliverable/mop").status_code == 503
    assert calls["availability"] == 2, calls


# ── defense 2: concurrency cap on the heavy generators ───────────────────────────
def _cap_shed_case(tmp_path, monkeypatch, db, make_path):
    """Shared harness: with the cap at 1 and the single slot already held (standing in for one heavy
    generation in flight), the next generation is shed with 503 + Retry-After; once the slot frees, it
    succeeds again — proving the cap sheds load rather than wedging the route."""
    monkeypatch.delenv("ASSESSHUB_TOKEN", raising=False)
    monkeypatch.setenv("ASSESSHUB_MAX_CONCURRENT_GENERATIONS", "1")
    app = create_app(db_path=str(tmp_path / db))
    with TestClient(app, base_url="http://localhost") as c:  # loopback Host passes the DNS-rebinding guard (#384)
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


def test_ingest_and_upload_writes_take_a_generation_slot(tmp_path, monkeypatch):
    """[#60] The cap was applied to a NAMED LIST of three routes (explorer render, deliverable, PIR docx)
    rather than to the structural property that earned it — "this handler does heavy work". The two
    heaviest operations in the app took no slot at all: `/ingest` and `/ingest-folder` each fork a real
    engine child with a 600s timeout, and both they and `/snapshots` buffer up to
    ingest.MAX_ARCHIVE_BYTES in memory (transiently ~2x at the b"".join), bounded only by Starlette's
    40-worker threadpool. Assert every heavy WRITE sheds at capacity — and note each assertion would
    still pass on the old code with a DIFFERENT status (400 / 201), so it pins the cap, not the route."""
    import json

    monkeypatch.delenv("ASSESSHUB_TOKEN", raising=False)
    monkeypatch.setenv("ASSESSHUB_MAX_CONCURRENT_GENERATIONS", "1")
    app = create_app(db_path=str(tmp_path / "cap_writes.db"))
    with TestClient(app, base_url="http://localhost") as c:
        cid = c.post("/api/campaigns", json={"name": "cap"}).json()["id"]
        snap = json.dumps({"devices": {"sw1": {}}}).encode()
        assert app.state.generation_semaphore.acquire(blocking=False)   # occupy the only slot
        try:
            shed = [
                c.post(f"/api/campaigns/{cid}/snapshots",
                       files={"file": ("s.json", snap, "application/json")}),
                c.post(f"/api/campaigns/{cid}/ingest",
                       files={"file": ("c.zip", b"PK\x03\x04not-a-zip", "application/zip")}),
                c.post(f"/api/campaigns/{cid}/ingest-folder",
                       json={"path": str(tmp_path / "no-such-collection")}),
            ]
            for r in shed:
                assert r.status_code == 503, f"{r.request.url.path} ran at capacity ({r.status_code})"
                assert r.headers.get("retry-after") == "5"
        finally:
            app.state.generation_semaphore.release()
        # once the slot frees, the same upload succeeds — the cap sheds load, it does not wedge the route
        assert c.post(f"/api/campaigns/{cid}/snapshots",
                      files={"file": ("s.json", snap, "application/json")}).status_code == 201


def test_default_capacity_allows_normal_single_use(client):
    """Sanity: with the generous default cap a plain sequence of downloads is never shed (the cap must
    bound bursts without biting ordinary one-at-a-time use)."""
    sid = _seed(client)
    for _ in range(3):
        assert client.get(f"/api/snapshots/{sid}/explorer").status_code == 200


def test_the_generation_slot_is_not_held_while_the_body_is_still_arriving():
    """The heavy-work semaphore must cover the HANDLER, never the network receive.

    It used to be acquired before the first body byte, with no read timeout — so a client that
    opened a chunked upload and stalled held the slot indefinitely. Measured at cap 1, every
    deliverable generation, explorer render and PIR export returned 503 while one upload sat idle,
    and the cap is 1 on a <=4 GiB field laptop, making a single slow connection total denial.

    Functional, not a source scan: a receive callable that asserts the semaphore is FREE each time
    the server asks for another chunk. If the slot is taken before the loop, `acquire(False)`
    inside the probe fails and the test does too.
    """
    import threading
    from webapp.backend.app import _RequestBodyLimitMiddleware

    sem = threading.Semaphore(1)
    free_during_receive = []

    async def app(scope, receive, send):          # the "handler": drain, then answer
        while True:
            m = await receive()
            if not m.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    mw = _RequestBodyLimitMiddleware(app, upload_semaphore=sem)
    body = b"--b\r\nContent-Disposition: form-data; name=f; filename=x\r\n\r\nzz\r\n--b--\r\n"
    chunks = [body[:20], body[20:]]

    async def receive():
        # Probe on every chunk the server pulls: the slot must still be available.
        got = sem.acquire(blocking=False)
        free_during_receive.append(got)
        if got:
            sem.release()
        return {"type": "http.request", "body": chunks.pop(0), "more_body": bool(chunks)}

    sent = []

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "POST", "path": "/api/campaigns/1/snapshots",
             "headers": [(b"content-type", b"multipart/form-data; boundary=b"),
                         (b"content-length", str(len(body)).encode())],
             "query_string": b"", "state": {}}
    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(mw(scope, receive, send))

    assert free_during_receive, "the receive probe never ran — the rig proved nothing"
    assert all(free_during_receive), (
        "the generation slot was already held while the body was still arriving: "
        f"{free_during_receive}. A stalled upload would deny all heavy work."
    )
    assert any(m.get("status") == 200 for m in sent if m.get("type") == "http.response.start")
