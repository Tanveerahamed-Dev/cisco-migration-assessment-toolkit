"""AssessHub serves Atlas Scope at /scope — one door, same origin, no client data in static files.

The contract pinned here (webapp/backend/app.py, ``create_app(scope_dist_dir=...)``):

* ``/scope/assets/<file>`` serves exactly the startup-indexed bytes of the scope build's
  ``assets/`` directory; ``/scope``, ``/scope/`` and ``/scope/<anything else>`` serve ONLY that
  build's ``index.html`` (traversal and UNC-shaped input fall back to it, never to a file outside
  the build). These routes are registered BEFORE AssessHub's own SPA catch-all, so /scope never
  answers with AssessHub's shell.
* When no usable scope build exists the answer is an honest non-200 ("Atlas Scope is not built in
  this installation"), never AssessHub's shell and never a half-working page. "Usable" means the
  build was made FOR this mount (every asset reference is under /scope/assets/) and declares that it
  reads its snapshot at run time from /api (the ``atlas-scope-snapshot-source`` meta contract) —
  a sample-fleet build must not be linked from a client snapshot page as if it showed that snapshot.
* Static output carries no client data: the scope routes are unguarded by construction (a static
  shell and bundles), so a scope build that embeds the digest of any stored snapshot is REFUSED —
  at startup for snapshots already stored, and at the moment a matching snapshot is stored.
* Every scope route is GET-only (Atlas Scope is first-party, read-only code served same-origin).
* ``GET /api/snapshots/{id}/scope-view`` (guarded) reports whether the view is available and owns
  the link target, so the SPA never renders a dead link.
"""
import hashlib
import json
import sys
import urllib.parse
from pathlib import Path

import anyio
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `backend` importable

from backend import app as app_mod  # noqa: E402
from backend.app import create_app  # noqa: E402
from frontend_fixture import write_frontend_dist  # noqa: E402

SCOPE_MARKER = "ATLAS-SCOPE-SHELL"
SPA_MARKER = "ASSESSHUB-SPA-SHELL"
_NOT_BUILT = "Atlas Scope is not built in this installation"


def write_scope_dist(
    dist: Path,
    *,
    mount: str = "/scope/",
    runtime_source: str | None = "assesshub-api-runtime",
    entry_bytes: bytes = b"export const scope = true;",
    extra_asset: tuple[str, bytes] | None = None,
) -> dict[str, bytes]:
    """A small, complete Vite-shaped Atlas Scope build: an inline classic theme-boot script, one
    module entry, a modulepreload and a stylesheet, all referenced under ``mount``."""
    assets = dist / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    files = {
        "assets/index-abc123.js": entry_bytes,
        "assets/react-def456.js": b"export const react = 1;",
        "assets/index-789.css": b":root{--bg:#000}",
    }
    if extra_asset is not None:
        files[f"assets/{extra_asset[0]}"] = extra_asset[1]
    for rel, content in files.items():
        (dist / rel).write_bytes(content)
    meta = (f'<meta name="atlas-scope-snapshot-source" content="{runtime_source}">'
            if runtime_source is not None else "")
    index = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"UTF-8\">"
        f"{meta}"
        "<script>try{var p=localStorage.getItem('t');}catch(e){}</script>"
        "<title>Atlas Scope</title>"
        "<link rel=\"icon\" href=\"data:image/svg+xml,%3Csvg%3E%3C/svg%3E\">"
        f'<script type="module" crossorigin src="{mount}assets/index-abc123.js"></script>'
        f'<link rel="modulepreload" crossorigin href="{mount}assets/react-def456.js">'
        f'<link rel="stylesheet" crossorigin href="{mount}assets/index-789.css">'
        f"</head><body><div id=\"root\">{SCOPE_MARKER}</div></body></html>"
    ).encode("utf-8")
    (dist / "index.html").write_bytes(index)
    files["index.html"] = index
    return files


@pytest.fixture(autouse=True)
def _no_token(monkeypatch):
    monkeypatch.delenv("ASSESSHUB_TOKEN", raising=False)
    monkeypatch.delenv("ASSESSHUB_ALLOWED_HOSTS", raising=False)


def _client(tmp_path, scope_dist, *, spa=True, db_name="scope.db", **kw):
    spa_dist = tmp_path / "spa-dist"
    if spa and not spa_dist.exists():
        write_frontend_dist(spa_dist, SPA_MARKER)
    app = create_app(db_path=str(tmp_path / db_name),
                     dist_dir=spa_dist if spa else tmp_path / "no-spa",
                     scope_dist_dir=scope_dist, **kw)
    return TestClient(app, base_url="http://localhost")


def _raw_get(app, raw_target: str) -> tuple[int, bytes]:
    """Send ``raw_target`` to the ASGI app exactly as a server would (percent-decoded ``path``, the
    untouched ``raw_path``), bypassing the HTTP client's own dot-segment normalisation — otherwise a
    traversal test would only prove what the CLIENT does to the URL."""
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
        "scheme": "http", "path": urllib.parse.unquote(raw_target),
        "raw_path": raw_target.encode("latin-1"), "query_string": b"", "root_path": "",
        "headers": [(b"host", b"localhost")],
        "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 80),
    }
    anyio.run(app, scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], body


def _demo_blob_sha256() -> str:
    """The store-form digest demo_seed will produce for the bundled sample (demo_seed stores the
    parsed sample re-serialised compactly and stamps nothing), computed WITHOUT the app."""
    snap = json.loads(app_mod.SAMPLE_SNAPSHOT.read_text(encoding="utf-8"))
    return hashlib.sha256(json.dumps(snap, separators=(",", ":")).encode("utf-8")).hexdigest()


# ── serving a built scope ───────────────────────────────────────────────────────────────────────
def test_scope_shell_and_assets_are_served_before_the_spa_catch_all(tmp_path):
    files = write_scope_dist(tmp_path / "scope-dist")
    with _client(tmp_path, tmp_path / "scope-dist") as c:
        for path in ("/scope", "/scope/", "/scope/snapshots/1/", "/scope/snapshots/1/deep/link"):
            r = c.get(path)
            assert r.status_code == 200, (path, r.status_code, r.text[:200])
            assert r.content == files["index.html"], path
            assert SPA_MARKER not in r.text, f"{path} answered with AssessHub's own shell"
            assert r.headers["content-type"].startswith("text/html")
        for rel in ("assets/index-abc123.js", "assets/react-def456.js", "assets/index-789.css"):
            r = c.get(f"/scope/{rel}")
            assert r.status_code == 200, rel
            assert r.content == files[rel]
        assert c.get("/scope/assets/index-abc123.js").headers["content-type"].startswith(
            "text/javascript")
        # a missing asset is an honest 404 — not the shell (which a module loader would choke on)
        missing = c.get("/scope/assets/nope.js")
        assert missing.status_code == 404
        assert SCOPE_MARKER not in missing.text
        # AssessHub's own SPA is untouched by the new mount
        assert SPA_MARKER in c.get("/campaigns").text


def test_scope_routes_answer_without_any_store_access(tmp_path):
    """Unguarded by construction means they must not read client data: trip every Store method."""
    write_scope_dist(tmp_path / "scope-dist")
    with _client(tmp_path, tmp_path / "scope-dist") as c:
        store = c.app.state.store
        touched = []
        tripped = []
        for name in dir(store):
            if name.startswith("__") or not callable(getattr(type(store), name, None)):
                continue

            def _trip(*_a, _n=name, **_k):
                touched.append(_n)
                raise AssertionError(f"scope route touched Store.{_n}")
            setattr(store, name, _trip)
            tripped.append(name)
        try:
            assert "get_snapshot_blob" in tripped and "get_snapshot_meta" in tripped
            for path in ("/scope/snapshots/7/", "/scope/assets/index-abc123.js"):
                r = c.get(path, headers={"sec-fetch-site": "cross-site"})
                assert r.status_code == 200, (path, r.status_code)
            assert touched == []
        finally:
            for name in tripped:  # the instance attributes shadow the class methods; drop them
                delattr(store, name)


@pytest.mark.parametrize("path", [
    "/scope/..%2f..%2fpyproject.toml",
    "/scope/%2e%2e/%2e%2e/secret.txt",
    "/scope/..\\..\\secret.txt",
    "/scope//server/share/secret.txt",
    "/scope/\\\\server\\share\\secret.txt",
    "/scope/%5c%5cserver%5cshare%5csecret.txt",
    "/scope/C:/secret.txt",
    "/scope/snapshots/1/../../../secret.txt",
])
def test_scope_traversal_and_unc_input_falls_back_to_the_shell(tmp_path, path):
    files = write_scope_dist(tmp_path / "scope-dist")
    (tmp_path / "secret.txt").write_bytes(b"TOP-SECRET-OUTSIDE-DIST")
    with _client(tmp_path, tmp_path / "scope-dist") as c:
        status, body = _raw_get(c.app, path)
        assert b"TOP-SECRET-OUTSIDE-DIST" not in body
        assert status == 200, (path, status)
        assert body == files["index.html"], path


@pytest.mark.parametrize("path", [
    "/scope/assets/..%2findex.html",
    "/scope/assets/%2e%2e/%2e%2e/secret.txt",
    "/scope/assets/..\\..\\secret.txt",
    "/scope/assets//server/share/secret.txt",
])
def test_scope_asset_traversal_is_404_never_a_file_outside_assets(tmp_path, path):
    write_scope_dist(tmp_path / "scope-dist")
    (tmp_path / "secret.txt").write_bytes(b"TOP-SECRET-OUTSIDE-DIST")
    with _client(tmp_path, tmp_path / "scope-dist") as c:
        status, body = _raw_get(c.app, path)
        assert b"TOP-SECRET-OUTSIDE-DIST" not in body
        assert status == 404, (path, status)
        assert SCOPE_MARKER.encode() not in body


# ── honest absence ──────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path", ["/scope", "/scope/", "/scope/snapshots/1/",
                                  "/scope/assets/index-abc123.js"])
def test_absent_scope_build_answers_honestly_never_with_the_assesshub_shell(tmp_path, path):
    with _client(tmp_path, None) as c:
        r = c.get(path)
        assert r.status_code == 503, (path, r.status_code)
        assert _NOT_BUILT in r.text
        assert SPA_MARKER not in r.text
        assert r.headers["cache-control"] == "no-store"


def test_a_missing_scope_directory_is_absence_not_a_crash(tmp_path):
    with _client(tmp_path, tmp_path / "does-not-exist") as c:
        r = c.get("/scope/snapshots/1/")
        assert r.status_code == 503
        assert _NOT_BUILT in r.text


def test_absent_scope_without_the_spa_is_still_honest(tmp_path):
    with _client(tmp_path, None, spa=False) as c:
        r = c.get("/scope/snapshots/1/")
        assert r.status_code == 503
        assert _NOT_BUILT in r.text


@pytest.mark.parametrize("variant", ["root-mounted", "no-runtime-source", "sample-only-source"])
def test_a_build_not_made_for_the_scope_mount_is_refused_honestly(tmp_path, variant):
    """A build with Vite's default base loads /assets/... — AssessHub's own asset namespace — and a
    build that bakes the sample fleet in would show the sample under a client snapshot's URL. Both
    are refused with a non-200 that says why, never served as if they worked."""
    kw = {
        "root-mounted": {"mount": "/"},
        "no-runtime-source": {"runtime_source": None},
        "sample-only-source": {"runtime_source": "static-sample-fleet"},
    }[variant]
    write_scope_dist(tmp_path / "scope-dist", **kw)
    with _client(tmp_path, tmp_path / "scope-dist") as c:
        for path in ("/scope/snapshots/1/", "/scope/assets/index-abc123.js"):
            r = c.get(path)
            assert r.status_code == 503, (variant, path, r.status_code)
            assert SCOPE_MARKER not in r.text and SPA_MARKER not in r.text
            assert "/scope" in r.text
        view = c.get("/api/snapshots/1/scope-view")
        # no snapshot stored: the capability route 404s on the id, never claims availability
        assert view.status_code == 404


def test_default_scope_dist_is_the_repository_build_when_present(tmp_path, monkeypatch):
    present = tmp_path / "repo-scope-dist"
    write_scope_dist(present)
    monkeypatch.setattr(app_mod, "ATLAS_SCOPE_DIST", present)
    app = create_app(db_path=str(tmp_path / "d1.db"), dist_dir=tmp_path / "no-spa")
    with TestClient(app, base_url="http://localhost") as c:
        assert SCOPE_MARKER in c.get("/scope/snapshots/1/").text
    monkeypatch.setattr(app_mod, "ATLAS_SCOPE_DIST", tmp_path / "absent-scope-dist")
    app = create_app(db_path=str(tmp_path / "d2.db"), dist_dir=tmp_path / "no-spa")
    with TestClient(app, base_url="http://localhost") as c:
        r = c.get("/scope/snapshots/1/")
        assert r.status_code == 503 and _NOT_BUILT in r.text
    # the module default points at the repository's atlas-scope/dist, not somewhere invented
    assert app_mod._REPO_ATLAS_SCOPE_DIST == Path(app_mod.__file__).resolve().parents[2] / \
        "atlas-scope" / "dist"


# ── static output carries no client data ────────────────────────────────────────────────────────
def test_a_scope_build_embedding_an_already_stored_snapshot_digest_is_refused(tmp_path):
    """The failure the runtime-fetch design exists to prevent: compiling a client snapshot INTO the
    static bundle publishes it on an unguarded URL. Seed first, then start AssessHub with a scope
    build that carries that snapshot's store digest — nothing under /scope may be served."""
    with _client(tmp_path, None, db_name="shared.db") as c:
        sid = c.post("/api/demo/seed").json()["snapshot"]["id"]
        digest = c.get(f"/api/snapshots/{sid}/raw").headers["x-snapshot-sha256"]
    write_scope_dist(tmp_path / "scope-dist",
                     extra_asset=("mount-x.js", f'export const s="{digest}";'.encode()))
    with _client(tmp_path, tmp_path / "scope-dist", db_name="shared.db") as c:
        for path in ("/scope/snapshots/1/", "/scope/assets/mount-x.js",
                     "/scope/assets/index-abc123.js"):
            r = c.get(path)
            assert r.status_code == 503, (path, r.status_code)
            assert digest not in r.text
            assert "stored snapshot" in r.text
        view = c.get(f"/api/snapshots/{sid}/scope-view").json()
        assert view["available"] is False and view["href"] is None
        assert view["status"] == "refused_embeds_stored_snapshot"


def test_storing_a_snapshot_whose_digest_a_running_scope_build_embeds_withdraws_the_build(tmp_path):
    """The post-boot case: the digest is in the build before the snapshot exists in the store. The
    moment the store persists that snapshot, every scope file stops being served."""
    digest = _demo_blob_sha256()
    write_scope_dist(tmp_path / "scope-dist",
                     extra_asset=("mount-x.js", f'export const s="sha256:{digest}";'.encode()))
    with _client(tmp_path, tmp_path / "scope-dist") as c:
        assert c.get("/scope/assets/mount-x.js").status_code == 200  # nothing stored yet
        sid = c.post("/api/demo/seed").json()["snapshot"]["id"]
        assert c.get(f"/api/snapshots/{sid}/raw").headers["x-snapshot-sha256"] == digest
        r = c.get("/scope/assets/mount-x.js")
        assert r.status_code == 503 and digest not in r.text
        assert c.get("/scope/snapshots/1/").status_code == 503


def test_no_served_scope_file_carries_a_stored_snapshot_digest_and_requests_cannot_add_one(tmp_path):
    """Structural half: the served scope bytes are captured once at startup from the build and no
    request — seeding, raw reads, scope views — can change them, so no file under the scope mount
    can come to carry a stored snapshot's digest."""
    files = write_scope_dist(tmp_path / "scope-dist")
    with _client(tmp_path, tmp_path / "scope-dist") as c:
        before = {rel: c.get(f"/scope/{rel}" if rel != "index.html" else "/scope/").content
                  for rel in files}
        digests = set()
        for _ in range(2):
            sid = c.post("/api/demo/seed").json()["snapshot"]["id"]
            digests.add(c.get(f"/api/snapshots/{sid}/raw").headers["x-snapshot-sha256"])
            assert c.get(f"/api/snapshots/{sid}/scope-view").json()["available"] is True
        after = {rel: c.get(f"/scope/{rel}" if rel != "index.html" else "/scope/").content
                 for rel in files}
        assert after == before == files
        for content in after.values():
            for digest in digests:
                assert digest.encode() not in content
        # and the build directory on disk was never written by the server
        for rel, content in files.items():
            assert (tmp_path / "scope-dist" / rel).read_bytes() == content


# ── capability for the SPA link ─────────────────────────────────────────────────────────────────
def test_scope_view_capability_reports_availability_and_owns_the_href(tmp_path):
    write_scope_dist(tmp_path / "scope-dist")
    with _client(tmp_path, tmp_path / "scope-dist") as c:
        sid = c.post("/api/demo/seed").json()["snapshot"]["id"]
        r = c.get(f"/api/snapshots/{sid}/scope-view")
        assert r.status_code == 200
        body = r.json()
        assert body == {"available": True, "status": "ready",
                        "href": f"/scope/snapshots/{sid}/", "detail": body["detail"]}
        # the href it hands out is live: it serves the scope shell
        assert SCOPE_MARKER in c.get(body["href"]).text
        assert c.get("/api/snapshots/424242/scope-view").status_code == 404
        # it is on the guarded /api surface
        assert c.get(f"/api/snapshots/{sid}/scope-view",
                     headers={"sec-fetch-site": "cross-site"}).status_code == 403


def test_scope_view_capability_is_false_when_the_build_is_absent(tmp_path):
    with _client(tmp_path, None) as c:
        sid = c.post("/api/demo/seed").json()["snapshot"]["id"]
        body = c.get(f"/api/snapshots/{sid}/scope-view").json()
        assert body["available"] is False
        assert body["href"] is None
        assert body["status"] == "not_built"
        assert _NOT_BUILT in body["detail"]


# ── R5: read-only ───────────────────────────────────────────────────────────────────────────────
def _scope_routes(app):
    return [r for r in app.routes if getattr(r, "path", "").startswith("/scope")]


@pytest.mark.parametrize("built", [True, False])
def test_no_scope_route_accepts_a_non_get_method(tmp_path, built):
    scope = tmp_path / "scope-dist"
    if built:
        write_scope_dist(scope)
    with _client(tmp_path, scope if built else None) as c:
        routes = _scope_routes(c.app)
        # NON-VACUITY: the enumeration found the mount (derived from the route table, not listed)
        assert {r.path for r in routes} >= {"/scope", "/scope/{rest:path}"}
        assert any(r.path.startswith("/scope/assets") for r in routes)
        for route in routes:
            assert set(route.methods) == {"GET"}, (route.path, route.methods)
        for path in ("/scope", "/scope/", "/scope/snapshots/1/", "/scope/assets/index-abc123.js"):
            for method in ("POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
                r = c.request(method, path)
                assert r.status_code == 405, (method, path, r.status_code)
                assert SPA_MARKER not in r.text and SCOPE_MARKER not in r.text
