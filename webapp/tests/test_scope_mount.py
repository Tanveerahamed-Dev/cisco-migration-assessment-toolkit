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
* Static output carries no client data: a build is served only when no file in it carries snapshot
  evidence (the compiler's binding envelope, a compiled record's snapshot citation, or a raw engine
  snapshot — see "privacy by construction" below) and every file the scan must read was read
  completely (a Brotli copy, a truncated or over-bound stream, or a payload nested beyond the scan
  bound is refused as uninspectable, never served as clean), and a scope build that embeds the
  digest of any stored snapshot is REFUSED — at startup for snapshots already stored, and at the moment a matching
  snapshot is stored. Because a content scan can only ever recognise the forms it knows, the /scope
  routes ALSO sit behind the same access guard as /api (cross-site read refusal, loopback + Host,
  token): whatever a build carries is readable exactly by whoever may read /api/snapshots/{id}/raw.
* Every scope route is GET-only (Atlas Scope is first-party, read-only code served same-origin).
* ``GET /api/snapshots/{id}/scope-view`` (guarded) reports whether the view is available and owns
  the link target, so the SPA never renders a dead link.
"""
import base64
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
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
    """Static routes must not read client data: trip every Store method. (The access guard in front
    of them reads no store either; a cross-site request is refused before routing — see
    test_every_scope_route_sits_behind_the_api_access_guard.)"""
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
                r = c.get(path, headers={"sec-fetch-site": "same-origin"})
                assert r.status_code == 200, (path, r.status_code)
                refused = c.get(path, headers={"sec-fetch-site": "cross-site"})
                assert refused.status_code == 403, (path, refused.status_code)
            assert touched == []
        finally:
            for name in tripped:  # the instance attributes shadow the class methods; drop them
                delattr(store, name)


#: Which inputs a NAIVE filesystem-serving shell (``Path(scope_dist) / rest``) would resolve to a
#: file inside this test's own tmp directory on EVERY platform — there the secret is planted exactly
#: where that shell would read it. The others resolve to a drive root or a UNC share (or, on POSIX, a
#: backslash-named file inside the build), where nothing can be planted; for every input the
#: request-time filesystem trap below is what a naive shell cannot pass.
_SHELL_TRAVERSALS = [
    ("/scope/..%2f..%2fpyproject.toml", True),
    ("/scope/%2e%2e/%2e%2e/secret.txt", True),
    ("/scope/..\\..\\secret.txt", False),
    ("/scope//server/share/secret.txt", False),
    ("/scope/\\\\server\\share\\secret.txt", False),
    ("/scope/%5c%5cserver%5cshare%5csecret.txt", False),
    ("/scope/C:/secret.txt", False),
    ("/scope/snapshots/1/../../../secret.txt", True),
]
_ASSET_TRAVERSALS = [
    ("/scope/assets/..%2findex.html", False),   # resolves INSIDE the build: the trap catches it
    ("/scope/assets/%2e%2e/%2e%2e/secret.txt", True),
    ("/scope/assets/..\\..\\secret.txt", False),
    ("/scope/assets//server/share/secret.txt", False),
    ("/scope/assets/%2e%2e/%2e%2e/%2e%2e/%2e%2e/secret.txt", True),
]


def _nested_scope_dist(tmp_path: Path) -> Path:
    """The build sits three levels below tmp_path so every ``..`` input above still lands INSIDE the
    test's own directory, where a secret can be planted at the exact spot a naive shell would read."""
    return tmp_path / "d1" / "d2" / "scope-dist"


def _plant_where_a_naive_shell_would_read(tmp_path: Path, dist: Path, raw_target: str,
                                          prefix: str, base: Path | None = None) -> bytes | None:
    """Plant a unique secret at ``normpath(base / rest)`` (``base`` defaults to the build root) —
    pure string arithmetic, never a filesystem resolve (which would touch a UNC share) — when that
    lands outside the build ``dist`` and inside tmp_path. Returns the secret, or None when the target
    cannot be planted."""
    rest = urllib.parse.unquote(raw_target)[len(prefix):]
    target = Path(os.path.normpath(str((base or dist) / rest)))
    try:
        inside_tmp = target.is_relative_to(tmp_path)
        inside_dist = target.is_relative_to(dist)
    except ValueError:
        return None
    if not inside_tmp or inside_dist:
        return None
    secret = b"TOP-SECRET-" + hashlib.sha256(raw_target.encode()).hexdigest()[:16].encode()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(secret)
    return secret


@contextlib.contextmanager
def _filesystem_trap(monkeypatch):
    """Record every filesystem entry point a request could use to NAME a file (stat, open, list).
    The scope routes select startup-captured bytes by exact key, so a request must record nothing; a
    shell that serves ``dist / rest`` from disk has to call at least one of these."""
    import builtins
    import io

    seen: list[tuple[str, str]] = []
    # The interpreter's own bookkeeping (linecache/inspect re-stat an imported module's source file)
    # is not the route naming a file; everything else is recorded.
    module_sources = {os.path.normcase(os.path.abspath(f)) for f in
                      (getattr(mod, "__file__", None) for mod in list(sys.modules.values()))
                      if isinstance(f, str)}

    def wrap(owner, name):
        original = getattr(owner, name)

        def recorder(*args, **kwargs):
            target = args[0] if args else ""
            if not (isinstance(target, (str, os.PathLike))
                    and os.path.normcase(os.path.abspath(os.fspath(target))) in module_sources):
                seen.append((name, str(target)))
            return original(*args, **kwargs)
        return recorder

    with monkeypatch.context() as m:
        for owner, name in ((os, "stat"), (os, "lstat"), (os, "open"), (os, "scandir"),
                            (os, "listdir"), (builtins, "open"), (io, "open")):
            m.setattr(owner, name, wrap(owner, name))
        yield seen


@pytest.mark.parametrize("path,plantable", _SHELL_TRAVERSALS)
def test_scope_traversal_and_unc_input_falls_back_to_the_shell(tmp_path, monkeypatch, path,
                                                               plantable):
    dist = _nested_scope_dist(tmp_path)
    files = write_scope_dist(dist)
    secret = _plant_where_a_naive_shell_would_read(tmp_path, dist, path, "/scope/")
    # NON-VACUITY: the inputs that climb out of the build really do have a secret waiting exactly
    # where `dist / rest` points, so serving from disk would hand it out.
    assert secret is not None or not plantable, f"{path}: nothing planted where it resolves"
    with _client(tmp_path, dist) as c:
        with _filesystem_trap(monkeypatch) as touched:
            status, body = _raw_get(c.app, path)
        assert touched == [], f"{path}: the scope shell touched the filesystem at request time"
        if secret is not None:
            assert secret not in body
        assert status == 200, (path, status)
        assert body == files["index.html"], path


@pytest.mark.parametrize("path,plantable", _ASSET_TRAVERSALS)
def test_scope_asset_traversal_is_404_never_a_file_outside_assets(tmp_path, monkeypatch, path,
                                                                  plantable):
    dist = _nested_scope_dist(tmp_path)
    write_scope_dist(dist)
    secret = _plant_where_a_naive_shell_would_read(tmp_path, dist, path, "/scope/assets/",
                                                   base=dist / "assets")
    assert secret is not None or not plantable, f"{path}: nothing planted where it resolves"
    with _client(tmp_path, dist) as c:
        with _filesystem_trap(monkeypatch) as touched:
            status, body = _raw_get(c.app, path)
        assert touched == [], f"{path}: the scope asset route touched the filesystem"
        if secret is not None:
            assert secret not in body
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


#: R8-V2-1. Every way an HTML document can declare its own referrer policy, which OVERRIDES the
#: `Referrer-Policy: same-origin` header every /scope response carries. A policy that strips the path
#: on same-origin requests (no-referrer, origin, strict-origin) makes the viewer's /api writes arrive
#: with no /scope Referer, so `_referred_from_scope` cannot refuse them. The server's header is the one
#: owner of the policy, so the class refused is "the document declares a policy at all" — whatever the
#: value, the spelling of the name, or which element carries it — not a list of bad values.
_REFERRER_DECLARATIONS = {
    "meta-no-referrer": '<meta name="referrer" content="no-referrer">',
    "meta-origin": '<meta name="referrer" content="origin">',
    "meta-strict-origin": '<meta name="referrer" content="strict-origin">',
    "meta-same-origin-still-a-second-owner": '<meta name="referrer" content="same-origin">',
    "meta-name-case": '<meta NAME="Referrer" content="no-referrer">',
    "meta-no-content": '<meta name="referrer">',
    "meta-policy-list": '<meta name="referrer" content="unsafe-url, no-referrer">',
    "script-referrerpolicy": '<script type="module" referrerpolicy="no-referrer" '
                             'src="/scope/assets/react-def456.js"></script>',
    "link-referrerpolicy": '<link rel="modulepreload" referrerpolicy="origin" '
                           'href="/scope/assets/react-def456.js">',
    # A duplicated attribute: the HTML tokenizer keeps the FIRST one, so a browser applies this
    # no-referrer policy whatever the second NAME says. A document that cannot be read the way a
    # browser reads it is refused, never passed (P3F-V1-2).
    "meta-duplicate-name-first-wins": '<meta name="referrer" NAME="x" content="no-referrer">',
    # The `noreferrer` link type is a referrer-policy declaration too: a form (or a followed link)
    # carrying it sends NO Referer, so a same-origin write from it escapes the /scope containment.
    "form-rel-noreferrer": '<form method="post" action="/api/demo/seed" rel="noreferrer"></form>',
    "a-rel-noreferrer-token-case": '<a rel="noopener NoReferrer">x</a>',
    "area-rel-noreferrer": '<area rel="noreferrer">',
    # A nested document the page itself declares (iframe srcdoc) is a page under /scope too.
    "iframe-srcdoc-meta": ('<iframe srcdoc="&lt;meta name=&quot;referrer&quot; '
                           'content=&quot;no-referrer&quot;&gt;"></iframe>'),
}


@pytest.mark.parametrize("declaration", sorted(_REFERRER_DECLARATIONS))
def test_a_scope_shell_that_declares_its_own_referrer_policy_is_refused(tmp_path, declaration):
    dist = tmp_path / "scope-dist"
    files = write_scope_dist(dist)
    shell = files["index.html"].replace(
        b"<title>", _REFERRER_DECLARATIONS[declaration].encode("utf-8") + b"<title>", 1)
    assert shell != files["index.html"]
    (dist / "index.html").write_bytes(shell)
    with _client(tmp_path, dist) as c:
        assert c.app.state.scope_status == "invalid_build", declaration
        r = c.get("/scope/snapshots/1/")
        assert r.status_code == 503 and SCOPE_MARKER not in r.text
    # the control: the same build without the declaration is served
    (dist / "index.html").write_bytes(files["index.html"])
    with _client(tmp_path, dist, db_name="control.db") as c:
        assert c.app.state.scope_status == "ready"


def test_any_html_document_the_scope_mount_serves_may_not_declare_a_referrer_policy(tmp_path):
    """The class is every HTML document served under /scope, not only the shell: an HTML asset at
    /scope/assets/x.html is a page under /scope too, and its own policy would strip ITS Referer."""
    dist = tmp_path / "scope-dist"
    page = (b"<!doctype html><html><head><meta name=\"referrer\" content=\"no-referrer\"></head>"
            b"<body>x</body></html>")
    write_scope_dist(dist, extra_asset=("x.html", page))
    with _client(tmp_path, dist) as c:
        assert c.app.state.scope_status == "invalid_build"
    write_scope_dist(dist, extra_asset=("x.html", page.replace(b"referrer", b"description")))
    with _client(tmp_path, dist, db_name="control.db") as c:
        assert c.app.state.scope_status == "ready"
        assert c.get("/scope/assets/x.html").status_code == 200


@pytest.mark.parametrize("declaration", sorted(_REFERRER_DECLARATIONS))
def test_an_html_asset_declaring_a_referrer_policy_in_any_form_is_refused(tmp_path, declaration):
    """Every declaration form the shell is refused for is refused in an HTML ASSET too. An asset's
    references are not held to the shell's /scope/assets grammar, so the shell's other refusals (an
    unindexed reference, a duplicate attribute) cannot stand in for the referrer rule there: a form
    with rel=noreferrer, or a duplicated meta name, must be refused on its own."""
    dist = tmp_path / "scope-dist"
    page = ("<!doctype html><html><head><title>x</title>" + _REFERRER_DECLARATIONS[declaration]
            + "</head><body>x</body></html>").encode("utf-8")
    write_scope_dist(dist, extra_asset=("x.html", page))
    with _client(tmp_path, dist) as c:
        assert c.app.state.scope_status == "invalid_build", declaration
        assert c.get("/scope/assets/x.html").status_code == 503
    # the control: the same page with the declaration removed is served
    write_scope_dist(dist, extra_asset=(
        "x.html", b"<!doctype html><html><head><title>x</title></head><body>x</body></html>"))
    with _client(tmp_path, dist, db_name="control.db") as c:
        assert c.app.state.scope_status == "ready"


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
    # The module default is the repository's HUB build (atlas-scope `npm run build:hub` ->
    # atlas-scope/dist-hub, the /scope runtime-snapshot build), never the standalone sample build
    # (atlas-scope/dist), which declares no runtime source and is refused as invalid_build: defaulting
    # to it made a checkout answer "not built for AssessHub" even after the hub build existed.
    assert app_mod._REPO_ATLAS_SCOPE_DIST == Path(app_mod.__file__).resolve().parents[2] / \
        "atlas-scope" / "dist-hub"
    monkeypatch.undo()
    assert app_mod.ATLAS_SCOPE_DIST == app_mod._REPO_ATLAS_SCOPE_DIST


def test_the_default_and_the_contract_are_the_hub_builds_own_constants():
    """Two owners, one fact each, reconciled from source text (no node needed): atlas-scope's build
    config owns where `npm run build:hub` writes and which runtime-source meta it declares; the
    server's default directory and its build contract must be exactly those."""
    config = (_ATLAS_SCOPE_ROOT / "vite.config.ts").read_text(encoding="utf-8")
    package = json.loads((_ATLAS_SCOPE_ROOT / "package.json").read_text(encoding="utf-8"))
    out_dir = re.search(r'export const HUB_OUT_DIR = "([^"]+)"', config)
    mode = re.search(r'export const HUB_MODE = "([^"]+)"', config)
    meta = re.search(r'export const RUNTIME_SOURCE_META = \{ name: "([^"]+)", content: "([^"]+)" \}',
                     config)
    assert out_dir and mode and meta, "atlas-scope/vite.config.ts no longer exports the hub constants"
    assert out_dir.group(1) == app_mod._ATLAS_SCOPE_HUB_BUILD_DIR
    assert f"--mode {mode.group(1)}" in package["scripts"]["build:hub"]
    assert meta.groups() == (app_mod._SCOPE_RUNTIME_SOURCE_META, app_mod._SCOPE_RUNTIME_SOURCE_VALUE)


_ATLAS_SCOPE_ROOT = Path(__file__).resolve().parents[2] / "atlas-scope"


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


def test_the_insert_observer_withdraws_the_build_before_the_insert_commits(tmp_path):
    """R8-V2-3(a). The pre-commit insert observer is its own mechanism, not a duplicate of the
    request-time watermark recheck: the build is withdrawn BEFORE the row is committed (so before any
    reader can see it), with no scope request at all. A second observer registered after the app's
    runs inside the same pre-commit window and records the status there."""
    digest = _demo_blob_sha256()
    write_scope_dist(tmp_path / "scope-dist",
                     extra_asset=("mount-x.js", f'export const s="{digest}";'.encode()))
    with _client(tmp_path, tmp_path / "scope-dist") as c:
        store = c.app.state.store
        assert c.app.state.scope_status == "ready"
        seen_before_commit = []

        def _witness(_blob_digest):
            # the insert's transaction is still open here: nothing has been committed yet (another
            # connection cannot even read the database — the writer holds it — so the Store's own
            # connection state is the witness)
            seen_before_commit.append((c.app.state.scope_status, store._conn.in_transaction))
        store.add_snapshot_digest_observer(_witness)
        c.post("/api/demo/seed")
        # inside the pre-commit window: already withdrawn, and the row is not yet committed
        assert seen_before_commit == [("refused_embeds_stored_snapshot", True)]
        assert store._conn.in_transaction is False  # ...and it did commit afterwards
        # and with no /scope request or capability read having run the watermark recheck
        assert c.app.state.scope_status == "refused_embeds_stored_snapshot"


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


# ── privacy by construction: a served build carries NO compiled dataset ─────────────────────────
# The digest check above catches only one digest form (the store blob). The class it stands for is
# "client evidence compiled into a static file", and the Atlas Scope compiler marks every file it
# emits: it writes the source binding into each compiled file's `meta`. A build is therefore refused
# when ANY file in it carries that compiled-model signature — whatever digest form, whatever
# snapshot, the bundled sample included (/scope must never show the sample in place of the user's
# snapshot). The signature keys are pinned to the compiler's own exported BINDING_KEYS and to its
# real output below, so a rename there turns these tests red instead of silently opening the gap.
_REPO = Path(__file__).resolve().parents[2]
_ATLAS_SCOPE = _REPO / "atlas-scope"
_COMPILE_MODEL = _ATLAS_SCOPE / "tools" / "lib" / "compile-model.mjs"
_SAMPLE = _REPO / "webapp" / "sample_data" / "sample_fleet.snapshot.json"
_NODE = shutil.which("node")
_REFUSED_COMPILED = "refused_compiled_evidence"


def _compiler_export(name: str) -> str:
    """The body of ``export const <name> = Object.freeze([...]);`` read from the compiler itself."""
    text = _COMPILE_MODEL.read_text(encoding="utf-8")
    match = re.search(r"export const " + name + r"\s*=\s*Object\.freeze\(\[(.*?)\]\);", text, re.S)
    assert match, f"compile-model.mjs no longer exports {name} as a frozen array"
    return match.group(1)


def _compiler_binding_keys() -> list[str]:
    return re.findall(r'"([A-Za-z0-9_$]+)"', _compiler_export("BINDING_KEYS"))


def _tracked_compiled_files() -> dict[str, bytes]:
    """The compiled files the compiler tracks for the sample build (its OUTPUTS[].trackedPath): real
    producer output that exists in every checkout, with no hand-made fixture standing in for it."""
    paths = re.findall(r'trackedPath:\s*"([^"]+)"', _compiler_export("OUTPUTS"))
    assert len(paths) >= 4, paths
    return {path: (_ATLAS_SCOPE / path).read_bytes() for path in paths}


def _js_literal(value) -> str:
    """A JSON value as the JS literal rolldown emits for a JSON import (see a Vite build's mount
    chunk): identifier keys bare, strings in template-literal backticks."""
    if isinstance(value, dict):
        return "{" + ",".join(
            (key if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", key) else json.dumps(key))
            + ":" + _js_literal(item) for key, item in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_js_literal(item) for item in value) + "]"
    if isinstance(value, str):
        return "`" + value.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${") + "`"
    return json.dumps(value)


_FORMS = ("json-asset", "json-parse-module", "rolldown-object-literal", "sourcemap",
          "inline-base64-sourcemap")


def _embeddings(name: str, content: bytes) -> dict[str, bytes]:
    """Every way a bundler ships a compiled JSON document inside a static build."""
    text = content.decode("utf-8")
    sourcemap = json.dumps({"version": 3, "sources": [f"../../{name}"], "sourcesContent": [text],
                            "names": [], "mappings": ""}).encode("utf-8")
    forms = {
        "json-asset": content,
        "json-parse-module": ("export default JSON.parse(" + json.dumps(text) + ");").encode(),
        "rolldown-object-literal": ("var e=" + _js_literal(json.loads(text))
                                    + ";export{e as t};").encode("utf-8"),
        "sourcemap": sourcemap,
        "inline-base64-sourcemap": (b"export const clean = 1;\n//# sourceMappingURL=data:"
                                    b"application/json;base64," + base64.b64encode(sourcemap)),
    }
    assert set(forms) == set(_FORMS)
    return forms


def test_the_signature_is_the_compilers_own_binding_keys():
    keys = _compiler_binding_keys()
    assert len(keys) >= 2, keys
    signature = app_mod._SCOPE_COMPILED_MODEL_SIGNATURE_KEYS
    assert len(signature) >= 2
    assert set(signature) <= set(keys), (
        f"the /scope refusal signature {signature} is no longer part of the compiler's BINDING_KEYS "
        f"{keys}: re-derive it from atlas-scope/tools/lib/compile-model.mjs")


def test_every_tracked_compiled_file_carries_the_signature_in_every_embedding():
    tracked = _tracked_compiled_files()
    for name, content in tracked.items():
        meta = json.loads(content)["meta"]
        for key in app_mod._SCOPE_COMPILED_MODEL_SIGNATURE_KEYS:
            assert isinstance(meta.get(key), str) and meta[key], (name, key)
        for form, embedded in _embeddings(name, content).items():
            assert app_mod._scope_file_carries_compiled_model(embedded), (name, form)


#: Set to 1 where the real-compiler / real-bundler pins MUST run (a CI leg that installs node and
#: atlas-scope's dependencies): a missing prerequisite then FAILS instead of skipping, so a leg that
#: lost node or `npm ci` cannot report green on pins it never executed.
_REQUIRE_REAL_TOOLCHAIN_ENV = "ATLAS_SCOPE_REQUIRE_REAL_TOOLCHAIN"


def _prerequisite_absent(reason: str):
    if os.environ.get(_REQUIRE_REAL_TOOLCHAIN_ENV) == "1":
        pytest.fail(f"{_REQUIRE_REAL_TOOLCHAIN_ENV}=1 but {reason}", pytrace=False)
    pytest.skip(reason)


def test_a_required_real_toolchain_that_is_absent_fails_instead_of_skipping(monkeypatch):
    monkeypatch.delenv(_REQUIRE_REAL_TOOLCHAIN_ENV, raising=False)
    with pytest.raises(pytest.skip.Exception):
        _prerequisite_absent("absent")
    monkeypatch.setenv(_REQUIRE_REAL_TOOLCHAIN_ENV, "1")
    with pytest.raises(pytest.fail.Exception, match=_REQUIRE_REAL_TOOLCHAIN_ENV):
        _prerequisite_absent("absent")


@pytest.fixture(scope="module")
def compiled_sample(tmp_path_factory):
    """The files the REAL compiler (tools/compile-all.mjs) emits for the sample snapshot — the same
    file the end-to-end test uploads — written outside the repository."""
    if not _NODE:
        _prerequisite_absent("node is not installed: the fresh-compile pins are skipped here; the "
                             "tracked compiled-output pins above still run")
    out = tmp_path_factory.mktemp("compiled-sample")
    proc = subprocess.run([_NODE, "tools/compile-all.mjs", "--source", str(_SAMPLE), "--out",
                           str(out)], cwd=_ATLAS_SCOPE, capture_output=True, text=True,
                          timeout=600)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    exports = subprocess.run(
        [_NODE, "--input-type=module", "-e",
         "const m = await import(process.argv[1]); console.log(JSON.stringify({"
         "BINDING_KEYS: m.BINDING_KEYS, SECTIONS_READ: m.SECTIONS_READ,"
         " SUPPORTED_SCHEMAS: m.SUPPORTED_SCHEMAS}));",
         _COMPILE_MODEL.as_uri()], capture_output=True, text=True, timeout=120)
    assert exports.returncode == 0, exports.stderr
    files = {path.name: path.read_bytes() for path in sorted(out.iterdir()) if path.is_file()}
    assert len(files) >= 4, sorted(files)
    return files, json.loads(exports.stdout)


def test_the_real_compiler_writes_the_signature_into_every_file_it_emits(compiled_sample):
    files, exports = compiled_sample
    binding_keys = exports["BINDING_KEYS"]
    # the authoritative export, imported by node, agrees with the source-text read above
    assert binding_keys == _compiler_binding_keys()
    assert set(app_mod._SCOPE_COMPILED_MODEL_SIGNATURE_KEYS) <= set(binding_keys)
    for name, content in files.items():
        assert set(app_mod._SCOPE_COMPILED_MODEL_SIGNATURE_KEYS) <= set(json.loads(content)["meta"])
        assert app_mod._scope_file_carries_compiled_model(content), name


@pytest.mark.parametrize("form", _FORMS)
def test_a_scope_build_carrying_a_compiled_dataset_is_refused_in_every_embedding(tmp_path, form):
    name, content = min(_tracked_compiled_files().items(), key=lambda item: len(item[1]))
    dist = tmp_path / "scope-dist"
    write_scope_dist(dist, extra_asset=("mount-x.js", _embeddings(name, content)[form]))
    with _client(tmp_path, dist) as c:
        assert c.app.state.scope_status == _REFUSED_COMPILED
        for path in ("/scope/", "/scope/snapshots/1/", "/scope/assets/mount-x.js",
                     "/scope/assets/index-abc123.js"):
            r = c.get(path, headers={"sec-fetch-site": "same-origin"})
            assert r.status_code == 503, (form, path, r.status_code)
            assert SCOPE_MARKER not in r.text and "compiled" in r.text
            assert b"sourceGitBlob" not in r.content
            assert c.get(path, headers={"sec-fetch-site": "cross-site"}).status_code == 403
        sid = c.post("/api/demo/seed").json()["snapshot"]["id"]
        view = c.get(f"/api/snapshots/{sid}/scope-view").json()
        assert view["available"] is False and view["href"] is None
        assert view["status"] == _REFUSED_COMPILED


def test_an_uploaded_snapshot_compiled_into_a_scope_build_is_refused_end_to_end(tmp_path,
                                                                                compiled_sample):
    """The refuter's X1 path, with the REAL producer: a client file is uploaded, the same file is
    compiled by the real compiler into a /scope runtime-declared build. The compiler binds the
    LF-normalised FILE bytes; the store holds a re-serialised, provenance-stamped blob — so no digest
    the build embeds is a stored digest, and the digest defence alone would have served it."""
    files, _exports = compiled_sample
    with _client(tmp_path, None, db_name="e2e.db") as c:
        cid = c.post("/api/campaigns", json={"name": "client"}).json()["id"]
        up = c.post(f"/api/campaigns/{cid}/snapshots",
                    files={"file": ("fleet.snapshot.json", _SAMPLE.read_bytes(),
                                    "application/json")},
                    data={"label": "uploaded"})
        assert up.status_code == 201, up.text[:300]
        sid = up.json()["id"]
        stored = c.get(f"/api/snapshots/{sid}/raw").headers["x-snapshot-sha256"]
    dist = tmp_path / "scope-dist"
    write_scope_dist(dist)
    for name, content in files.items():
        (dist / "assets" / name).write_bytes(content)
    embedded = set(re.findall(rb"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", b"".join(files.values())))
    assert embedded and stored.encode() not in embedded  # the digest defence cannot see this build
    with _client(tmp_path, dist, db_name="e2e.db") as c:
        for name in files:
            r = c.get(f"/scope/assets/{name}", headers={"sec-fetch-site": "same-origin"})
            assert r.status_code == 503, (name, r.status_code)
            assert r.content != files[name] and b"sourceGitBlob" not in r.content
            refused = c.get(f"/scope/assets/{name}", headers={"sec-fetch-site": "cross-site"})
            assert refused.status_code == 403 and b"sourceGitBlob" not in refused.content
        view = c.get(f"/api/snapshots/{sid}/scope-view").json()
        assert view["status"] == _REFUSED_COMPILED and view["href"] is None


def test_a_runtime_build_that_bundles_the_compiler_is_not_mistaken_for_a_compiled_dataset(tmp_path):
    """The phase-3 runtime build compiles in the browser, so it bundles the compiler (which NAMES
    every binding key) and builds a binding label from literals. Neither is a compiled dataset: the
    signature is the keys BOUND to compiled values, never their mere names."""
    runtime = (_COMPILE_MODEL.read_bytes()
               + b"\nconst label={source:`assesshub:snapshot/1`,sourceOrigin:`assesshub-store`,"
                 b"sourceDigestForm:`assesshub-store-blob`};\n")
    for key in app_mod._SCOPE_COMPILED_MODEL_SIGNATURE_KEYS:
        assert key.encode() in runtime
    assert not app_mod._scope_file_carries_compiled_model(runtime)
    dist = tmp_path / "scope-dist"
    write_scope_dist(dist, extra_asset=("compile-model-x.js", runtime))
    with _client(tmp_path, dist) as c:
        assert c.app.state.scope_status == "ready"
        r = c.get("/scope/assets/compile-model-x.js")
        assert r.status_code == 200 and r.content == runtime


# ── the envelope is removable: compiled RECORDS are recognised on their own ─────────────────────
# A bundler drops a compiled file's `meta` envelope: Vite turns every top-level JSON member into a
# named export, so `import { devices } from "./fabric.json"` ships the device records with neither
# signature key. The compiler's per-record contract — every record carries `cite`, a path into the
# snapshot rooted at a section it reads (SECTIONS_READ) — is what survives, and what is recognised.
#: Members that carry NO citation rooted in a snapshot section, so shipped without their envelope
#: they are not recognised: bare host-name lists / host-keyed maps (`tiers`, `deviceAbsent`), and the
#: coverage summary, whose one `cite` is a constant ("collection_completeness / coverage_matrix") that
#: the compiler's own code also binds — recognising it would refuse every runtime build that bundles
#: the compiler. A STATED residual (the compiler owns the fix: a section-rooted citation on every
#: member), whose exposure the access guard in front of /scope bounds. The member census below fails
#: if this set GROWS (a new unrecognisable member would be a new silent gap).
#: `evidenceProjection` (the bounds and counts of the evidence-record projection) is uncited because
#: it carries no record at all: aggregate numbers only, which _AGGREGATE_ONLY_MEMBERS pins
#: mechanically (no string anywhere in its value), so it can never carry a host, address or text.
_UNCITED_MEMBERS = frozenset({("fabric.json", "tiers"), ("fabric.json", "coverage"),
                              ("producer-emission.json", "deviceAbsent"),
                              ("fabric.json", "evidenceProjection")})
_AGGREGATE_ONLY_MEMBERS = frozenset({("fabric.json", "evidenceProjection")})


def _compiler_strings(name: str) -> list[str]:
    return re.findall(r'"([^"]+)"', _compiler_export(name))


#: Every JSON text a member can be serialised to before a bundler wraps it: compact (a named-export
#: stringify), and the pretty forms a compiled file is written in or a sourcemap carries verbatim
#: (one space — the tracked sidecars —, two spaces, a tab, and a CRLF checkout of a pretty file).
_MEMBER_SERIALISATIONS = {
    "compact": lambda v: json.dumps(v, separators=(",", ":")),
    "indent1": lambda v: json.dumps(v, indent=1),
    "indent2": lambda v: json.dumps(v, indent=2),
    "indent-tab": lambda v: json.dumps(v, indent="\t"),
    "indent1-crlf": lambda v: json.dumps(v, indent=1).replace("\n", "\r\n"),
    # JSON allows whitespace on BOTH sides of a colon; a newline or tab there becomes an ESCAPE once
    # the document is a string (\n inside JSON.parse, \\n inside a sourcemap). No serialiser above puts
    # one there, so without this form the escaped-whitespace rule is pinned only between members.
    "ws-around-colon": lambda v: json.dumps(v, indent="\t", separators=(",", "\r\n:\t")),
}


#: One minimal document per signature — each signature is exercised on its OWN, so no other
#: signature in the same file can mask a regression in it (P3F-V1-3: three of the four were
#: previously pinned only through documents another signature also recognised).
def _signature_documents() -> dict[str, tuple[object, object]]:
    meta = json.loads(min(_tracked_compiled_files().values(), key=len))["meta"]
    model = {key: meta[key] for key in app_mod._SCOPE_COMPILED_MODEL_SIGNATURE_KEYS}
    citation = "interfaces.core1.Gi1/0/1"
    assert citation.split(".", 1)[0] in app_mod._SCOPE_SNAPSHOT_SECTIONS
    return {
        "compiled-model-envelope": ({"meta": model}, app_mod._SCOPE_COMPILED_MODEL_SIGNATURE),
        "cite-key": ([{"cite": citation}], (app_mod._SCOPE_RECORD_CITATION_SIGNATURE[0],)),
        "citation-object-key": ({"x": 1, citation: 1},
                                (app_mod._SCOPE_RECORD_CITATION_SIGNATURE[1],)),
        "raw-engine-snapshot": ({"schema": json.loads(_SAMPLE.read_bytes())["schema"]},
                                (app_mod._SCOPE_RAW_SNAPSHOT_SIGNATURE,)),
    }


@pytest.mark.parametrize("document", ["compiled-model-envelope", "cite-key", "citation-object-key",
                                      "raw-engine-snapshot"])
def test_each_signature_on_its_own_tolerates_escaped_whitespace_in_every_form(document):
    value, patterns = _signature_documents()[document]
    assert len(patterns) >= 1
    missed = []
    for serialisation, dump in _MEMBER_SERIALISATIONS.items():
        for embedding, shipped in _embeddings("doc.json", dump(value).encode("utf-8")).items():
            views = [shipped]
            if embedding == "inline-base64-sourcemap":  # the scan reads the decoded payload
                views = [base64.b64decode(m) for m in app_mod._BASE64_DATA_URI_RE.findall(shipped)]
            if not all(any(p.search(view) for view in views) for p in patterns):
                missed.append(f"{serialisation}/{embedding}")
            if not app_mod._scope_file_carries_compiled_model(shipped):
                missed.append(f"{serialisation}/{embedding} (verdict)")
    assert not missed, (document, missed)
    # NON-VACUITY: the new form really does put an ESCAPED whitespace on both sides of a colon
    escaped = _embeddings("doc.json", _MEMBER_SERIALISATIONS["ws-around-colon"](value)
                          .encode("utf-8"))["json-parse-module"]
    assert re.search(rb'\\"\\r\\n:\\t', escaped), escaped[:200]


def _member_forms(value) -> dict[str, bytes]:
    """One compiled member with its file's envelope gone, in every form a build can ship it. DERIVED,
    not a hand list (R8-V2-2): every serialisation above composed with every file-level embedding
    `_embeddings` owns (the JSON asset, an escaped string inside JSON.parse, rolldown's object literal,
    a sourcemap's sourcesContent and an inline base64 sourcemap) — so a pretty member escaped inside a
    JS string or a sourcemap is in the census — plus the named-export shapes rolldown emits for one
    member (JSON.parse of a template literal or a string literal, and a plain object literal)."""
    forms: dict[str, bytes] = {}
    for serialisation, dump in _MEMBER_SERIALISATIONS.items():
        text = dump(value)
        for embedding, shipped in _embeddings("member.json", text.encode("utf-8")).items():
            forms[f"{serialisation}/{embedding}"] = shipped
        template = text.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
        forms[f"{serialisation}/json-parse-template"] = (
            "var e=JSON.parse(`" + template + "`);export{e as t};").encode("utf-8")
        forms[f"{serialisation}/json-parse-string"] = (
            "var e=JSON.parse(" + json.dumps(text) + ");export{e as t};").encode("utf-8")
    forms["object-literal"] = ("var e=" + _js_literal(value) + ";export{e as t};").encode("utf-8")
    assert len(forms) == len(_MEMBER_SERIALISATIONS) * (len(_FORMS) + 2) + 1
    return forms


def _strings_in(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in [k, *_strings_in(v)] if isinstance(s, str)]
    if isinstance(value, list):
        return [s for v in value for s in _strings_in(v)]
    return []


def _member_census(files: dict[str, bytes]) -> tuple[set, set]:
    caught, uncaught = set(), set()
    for name, content in files.items():
        members = {key: value for key, value in json.loads(content).items() if key != "meta"}
        assert members, name
        for member, value in members.items():
            if (name, member) in _AGGREGATE_ONLY_MEMBERS:
                # the residual's own claim: no string VALUE at any depth (keys are the projection's
                # own field names, never snapshot data)
                values = value.values() if isinstance(value, dict) else [value]
                assert not [s for v in values for s in _strings_in(v)], (name, member)
            forms = _member_forms(value)
            for form, shipped in forms.items():
                # the envelope really is gone from what is scanned
                for key in app_mod._SCOPE_COMPILED_MODEL_SIGNATURE_KEYS:
                    assert key.encode() not in shipped, (name, member, form, key)
            verdicts = {form: app_mod._scope_file_carries_compiled_model(shipped)
                        for form, shipped in forms.items()}
            # forms agree: a member recognised in one form and not another is a form-specific gap
            assert len(set(verdicts.values())) == 1, (
                name, member, sorted(form for form, seen in verdicts.items() if not seen))
            (caught if all(verdicts.values()) else uncaught).add((name, member))
    return caught, uncaught


def _assert_the_uncited_residual_is_exactly(uncaught: set, present: set) -> None:
    """The residual is recorded (docs/open-issues) as exactly these members, so it is pinned EXACTLY
    over the members the census input actually carries: a new uncited member is a new silent gap, and
    a present member the compiler has since given a citation must leave _UNCITED_MEMBERS (and the
    record) rather than linger as a stale, over-broad excuse. (Exact over what is PRESENT, so tracked
    output that trails the compiler by one regeneration is judged on its own members; that the
    residual names only members the compiler still emits is pinned against the REAL compiler.)"""
    expected = _UNCITED_MEMBERS & present
    assert not uncaught - expected, f"new uncited compiled member(s): {uncaught - expected}"
    assert not expected - uncaught, (
        f"now recognised, so no longer a residual: {expected - uncaught} — remove them from "
        f"_UNCITED_MEMBERS and from the recorded /scope residual")


def test_the_citation_signature_is_the_compilers_own_snapshot_sections():
    sections = _compiler_strings("SECTIONS_READ")
    assert len(sections) >= 10, sections
    assert set(app_mod._SCOPE_SNAPSHOT_SECTIONS) == set(sections), (
        "the /scope record-citation signature must be rooted at exactly the sections the compiler "
        "reads (compile-model.mjs SECTIONS_READ); re-derive app._SCOPE_SNAPSHOT_SECTIONS")
    families = {schema.rsplit("/", 1)[0] + "/" for schema in _compiler_strings("SUPPORTED_SCHEMAS")}
    assert families and families == set(app_mod._SCOPE_SNAPSHOT_SCHEMA_FAMILIES)
    # the engine's real sample snapshot is recognised by that family
    assert json.loads(_SAMPLE.read_bytes())["schema"].startswith(tuple(families))


def test_a_record_citing_the_snapshot_by_engine_json_pointer_is_recognised_in_every_form():
    """A compiled record that projects a pointed-to engine record cites it in the ENGINE's form, an
    RFC 6901 pointer (the form of every punch-list evidence_refs pointer), which may root at a section
    the compiler's dotted citations never use. The pointers here come from the real producer: the
    engine's sample snapshot's own punch-list evidence refs."""
    snap = json.loads(_SAMPLE.read_bytes())
    pointers = sorted({ref["ref"] for row in snap["punchlist"]
                       for ref in row.get("evidence_refs") or []
                       if isinstance(ref, dict) and isinstance(ref.get("ref"), str)
                       and ref["ref"].startswith("/")})
    roots = {p.split("/")[1] for p in pointers}
    assert len(pointers) >= 10 and roots - set(app_mod._SCOPE_SNAPSHOT_SECTIONS), roots  # NON-VACUITY
    for pointer in pointers:
        record = [{"pointer": pointer, "cite": pointer, "type": "object", "text": None}]
        forms = _member_forms(record)
        missed = sorted(f for f, shipped in forms.items()
                        if not app_mod._scope_file_carries_compiled_model(shipped))
        assert not missed, (pointer, missed)


def test_every_compiled_member_shipped_without_its_envelope_is_recognised():
    """Member by member over the compiler's real tracked output (no hand-made records): every member
    that carries a citation is recognised in every form a bundler ships it; the rest is exactly the
    stated residual and may not grow."""
    tracked = {Path(path).name: content for path, content in _tracked_compiled_files().items()}
    caught, uncaught = _member_census(tracked)
    _assert_the_uncited_residual_is_exactly(uncaught, caught | uncaught)
    assert len(caught) >= 15 and {name for name, _member in caught} == set(tracked), caught


def test_every_member_the_real_compiler_emits_is_recognised_without_its_envelope(compiled_sample):
    files, exports = compiled_sample
    assert set(exports["SECTIONS_READ"]) == set(app_mod._SCOPE_SNAPSHOT_SECTIONS)
    assert {s.rsplit("/", 1)[0] + "/" for s in exports["SUPPORTED_SCHEMAS"]} == set(
        app_mod._SCOPE_SNAPSHOT_SCHEMA_FAMILIES)
    caught, uncaught = _member_census(files)
    _assert_the_uncited_residual_is_exactly(uncaught, caught | uncaught)
    # the real compiler is the authority on what exists: the residual names no member it stopped emitting
    assert _UNCITED_MEMBERS <= caught | uncaught, _UNCITED_MEMBERS - (caught | uncaught)
    assert len(caught) >= 15 and {name for name, _member in caught} == set(files), caught


_VITE = _ATLAS_SCOPE / "node_modules" / "vite" / "dist" / "node" / "index.js"
_VITE_BUILD = (
    "import { pathToFileURL } from 'node:url';"
    "const vite = await import(pathToFileURL(process.argv[1]).href);"
    "await vite.build({ root: process.cwd(), base: '/scope/', configFile: false, logLevel: 'error',"
    " build: { outDir: 'dist', emptyOutDir: true, sourcemap: false } });")


def _vite_build(root: Path, main_js: str) -> Path:
    """A real Vite build (Atlas Scope's own pinned Vite) of a /scope runtime-declared page."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text(
        '<!doctype html><html lang="en"><head><meta charset="UTF-8">'
        '<meta name="atlas-scope-snapshot-source" content="assesshub-api-runtime">'
        '<title>Atlas Scope</title><script type="module" src="/main.js"></script></head>'
        '<body><div id="root"></div></body></html>', encoding="utf-8")
    (root / "main.js").write_text(main_js, encoding="utf-8")
    proc = subprocess.run([_NODE, "--input-type=module", "-e", _VITE_BUILD, str(_VITE)], cwd=root,
                          capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    return root / "dist"


@pytest.fixture(scope="module")
def vite_builds(tmp_path_factory):
    if not _NODE or not _VITE.is_file():
        _prerequisite_absent("node or atlas-scope's installed Vite is absent: the real-bundler pins "
                             "are skipped; the member census above still runs on the compiler's real "
                             "output")
    base = tmp_path_factory.mktemp("vite")
    data = base / "named-imports"
    data.mkdir()
    for path, content in _tracked_compiled_files().items():
        (data / Path(path).name).write_bytes(content)
    named = _vite_build(data, (
        'import { devices, links } from "./fabric.json";\n'
        'import { hosts } from "./acl-bindings.json";\n'
        'import { hosts as ribHosts } from "./rib-evidence.json";\n'
        'import { aclLineAbsent } from "./producer-emission.json";\n'
        'document.getElementById("root").textContent = JSON.stringify('
        '[devices, links, hosts, ribHosts, aclLineAbsent]);\n'))
    runtime = _vite_build(base / "runtime", (
        f"import {{ compileAll, BINDING_KEYS }} from {json.dumps(_COMPILE_MODEL.as_posix())};\n"
        'const label = { source: "assesshub:snapshot/1", sourceOrigin: "assesshub-store",'
        ' sourceDigestForm: "assesshub-store-blob" };\n'
        "window.atlasScope = [compileAll, BINDING_KEYS, label];\n"))
    return named, runtime


def _shipped(dist: Path) -> bytes:
    return b"".join(path.read_bytes() for path in sorted(dist.rglob("*")) if path.is_file())


def test_a_real_vite_build_importing_compiled_members_by_name_is_refused(tmp_path, vite_builds):
    """R8-V1: the project's own bundler, default settings, named JSON imports — the envelope is
    tree-shaken away and compiled client records ship on their own. Refused on those records."""
    named, _runtime = vite_builds
    shipped = _shipped(named)
    for key in app_mod._SCOPE_COMPILED_MODEL_SIGNATURE_KEYS:  # NON-VACUITY: the envelope is gone
        assert key.encode() not in shipped, key
    fabric = json.loads(_tracked_compiled_files()["src/data/fabric.json"])
    assert fabric["devices"][0]["cite"].encode() in shipped  # ...and the records really shipped
    assert app_mod._scope_file_index(named)[0] == _REFUSED_COMPILED
    with _client(tmp_path, named) as c:
        assert c.app.state.scope_status == _REFUSED_COMPILED
        for asset in sorted((named / "assets").iterdir()):
            r = c.get(f"/scope/assets/{asset.name}", headers={"sec-fetch-site": "same-origin"})
            assert r.status_code == 503 and r.content != asset.read_bytes(), asset.name
            assert c.get(f"/scope/assets/{asset.name}",
                         headers={"sec-fetch-site": "cross-site"}).status_code == 403


def test_a_real_vite_runtime_build_that_bundles_the_compiler_is_ready(tmp_path, vite_builds):
    """The negative control, built for real: the phase-3 shape bundles the compiler (which names
    both binding keys and builds citations from templates) and labels its binding with literals."""
    _named, runtime = vite_builds
    shipped = _shipped(runtime)
    for key in app_mod._SCOPE_COMPILED_MODEL_SIGNATURE_KEYS:  # NON-VACUITY: the names ARE there
        assert key.encode() in shipped, key
    assert app_mod._scope_file_index(runtime)[0] == "ready"


def test_the_repositorys_own_hub_build_is_served_at_the_one_door(tmp_path):
    """The real artifact, not a fixture: atlas-scope's `npm run build:hub` output is what AssessHub
    serves by default, and it passes every /scope refusal (runtime-snapshot contract, no compiled
    dataset, fully inspectable) — then a stored snapshot's capability hands out a live link to it.
    Needs the built directory: a leg that builds it sets ATLAS_SCOPE_REQUIRE_HUB_BUILD=1 (webapp-ci's
    backend leg), and there its absence FAILS instead of skipping."""
    hub = app_mod._REPO_ATLAS_SCOPE_DIST
    if not (hub / "index.html").is_file():
        reason = f"{hub} is not built (atlas-scope `npm run build:hub`)"
        if os.environ.get(_REQUIRE_HUB_BUILD_ENV) == "1":
            pytest.fail(f"{_REQUIRE_HUB_BUILD_ENV}=1 but {reason}", pytrace=False)
        pytest.skip(reason)
    assert not [p for p in hub.rglob("*") if p.name.casefold().endswith(".map")]
    assert app_mod._scope_file_index(hub)[0] == "ready"
    shell = (hub / "index.html").read_bytes()
    with _client(tmp_path, _SCOPE_DIST_DEFAULT_SENTINEL) as c:
        assert c.app.state.scope_status == "ready"
        sid = c.post("/api/demo/seed").json()["snapshot"]["id"]
        view = c.get(f"/api/snapshots/{sid}/scope-view").json()
        assert view["available"] is True and view["href"] == f"/scope/snapshots/{sid}/"
        page = c.get(view["href"], headers={"sec-fetch-site": "same-origin"})
        assert page.status_code == 200 and page.content == shell
        for asset in sorted((hub / "assets").iterdir()):
            r = c.get(f"/scope/assets/{asset.name}", headers={"sec-fetch-site": "same-origin"})
            assert r.status_code == 200 and r.content == asset.read_bytes(), asset.name


def test_a_required_hub_build_that_is_absent_fails_instead_of_skipping(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "_REPO_ATLAS_SCOPE_DIST", tmp_path / "not-built")
    monkeypatch.delenv(_REQUIRE_HUB_BUILD_ENV, raising=False)
    with pytest.raises(pytest.skip.Exception):
        test_the_repositorys_own_hub_build_is_served_at_the_one_door(tmp_path)
    monkeypatch.setenv(_REQUIRE_HUB_BUILD_ENV, "1")
    with pytest.raises(pytest.fail.Exception, match=_REQUIRE_HUB_BUILD_ENV):
        test_the_repositorys_own_hub_build_is_served_at_the_one_door(tmp_path)
    # and the leg that builds it really asks for it
    webapp_ci = (Path(__file__).resolve().parents[2] / ".github" / "workflows"
                 / "webapp-ci.yml").read_text(encoding="utf-8")
    backend = webapp_ci.split("\n  backend:", 1)[1].split("\n  frontend:", 1)[0]
    assert "run: npm run build:hub" in backend and f'{_REQUIRE_HUB_BUILD_ENV}: "1"' in backend
    assert backend.index("run: npm run build:hub") < backend.index("python -m pytest webapp/tests")


_SCOPE_DIST_DEFAULT_SENTINEL = app_mod._SCOPE_DIST_DEFAULT
#: Set to 1 on a leg that runs atlas-scope `npm run build:hub` before this suite (the hub build is
#: untracked build output, so only such a leg can hold this pin to account).
_REQUIRE_HUB_BUILD_ENV = "ATLAS_SCOPE_REQUIRE_HUB_BUILD"


def test_no_module_a_runtime_build_can_bundle_reads_as_snapshot_evidence():
    """Every non-test module under atlas-scope/src and the compiler library — what a runtime build
    can import — scanned as a build file, derived from the tree. None may read as snapshot evidence,
    or the phase-3 runtime build would be refused for its own code. The compiled datasets (the
    compiler's own OUTPUTS[].trackedPath) are exactly what is excluded."""
    compiled = {(_ATLAS_SCOPE / path).resolve() for path in _tracked_compiled_files()}
    scanned = []
    for root in (_ATLAS_SCOPE / "src", _ATLAS_SCOPE / "tools" / "lib", _ATLAS_SCOPE / "contracts"):
        for path in sorted(root.rglob("*")):
            if (not path.is_file() or path.resolve() in compiled or ".test." in path.name
                    or path.suffix not in {".ts", ".tsx", ".mts", ".mjs", ".js", ".json", ".css"}):
                continue
            scanned.append(path)
            assert not app_mod._scope_file_carries_compiled_model(path.read_bytes()), path
    assert len(scanned) >= 50, len(scanned)
    assert len(compiled) >= 4


_EVIDENCE_FORMS = ("raw-engine-snapshot", "gzip-compiled-file", "gzip-raw-engine-snapshot",
                   "base64-gzip-compiled-file")


def _evidence_asset(form: str) -> bytes:
    import gzip

    _name, compiled = min(_tracked_compiled_files().items(), key=lambda item: len(item[1]))
    raw = _SAMPLE.read_bytes()
    return {
        "raw-engine-snapshot": raw,
        "gzip-compiled-file": gzip.compress(compiled, mtime=0),
        "gzip-raw-engine-snapshot": gzip.compress(raw, mtime=0),
        "base64-gzip-compiled-file": (b"export const d='data:application/gzip;base64,"
                                      + base64.b64encode(gzip.compress(compiled, mtime=0)) + b"';"),
    }[form]


@pytest.mark.parametrize("form", _EVIDENCE_FORMS)
def test_a_build_carrying_a_raw_snapshot_or_a_precompressed_compiled_file_is_refused(tmp_path, form):
    """R8-V3: the uploaded file itself, and a compression plugin's .gz copy of a compiled file."""
    dist = tmp_path / "scope-dist"
    write_scope_dist(dist, extra_asset=("evidence.bin", _evidence_asset(form)))
    with _client(tmp_path, dist) as c:
        assert c.app.state.scope_status == _REFUSED_COMPILED, form
        r = c.get("/scope/assets/evidence.bin", headers={"sec-fetch-site": "same-origin"})
        assert r.status_code == 503


# ── what the scan cannot read is never read as clean (R8-VR4) ───────────────────────────────────
# A content scan that meets bytes it cannot decode has NOT established that they carry no snapshot
# evidence. A Brotli (.br) copy — the other common compression-plugin output, which the standard
# library cannot decode — or a stream that does not decode completely within the per-file bound
# is therefore refused as uninspectable, never served as `ready`. Which names declare a content
# encoding is the standard library's own registry (mimetypes.encodings_map / suffix_map), not a
# hand list; which streams are decoded is recognised by content (magic), whatever the name.
_REFUSED_UNINSPECTABLE = "refused_uninspectable"
_CLEAN_RUNTIME_ASSET = b"export const runtime = 'reads /api/snapshots/{id}/raw at run time';\n" * 64


def _stdlib_compressors() -> dict[str, "callable"]:
    import bz2
    import gzip
    import lzma

    return {"gzip": lambda data: gzip.compress(data, mtime=0), "bzip2": bz2.compress,
            "xz": lzma.compress}


def _declared_encoding_names() -> list[str]:
    """Every member name the standard library reads as content-encoded, in both cases: each
    encodings_map suffix and each suffix_map alias whose expansion ends in one (.svgz, .tgz ...)."""
    import mimetypes

    encodings = {suffix.casefold() for suffix in mimetypes.encodings_map}
    suffixes = set(mimetypes.encodings_map)
    suffixes |= {alias for alias, expansion in mimetypes.suffix_map.items()
                 if Path(expansion).suffix.casefold() in encodings}
    names = set()
    for suffix in suffixes:
        names |= {f"extra.js{suffix}", f"extra.js{suffix.upper()}", f"extra{suffix.lower()}"}
    return sorted(names)


def test_every_content_encoding_the_stdlib_names_is_decoded_or_refused(tmp_path):
    names = _declared_encoding_names()
    assert any(name.endswith(".br") for name in names) and len(names) >= 12, names  # NON-VACUITY
    opaque = b"\x8b\x05\x80opaque bytes no stdlib decoder reads as a stream" * 4
    for index, name in enumerate(names):
        dist = tmp_path / f"scope-dist-{index}"
        write_scope_dist(dist, extra_asset=(name, opaque))
        assert app_mod._scope_file_index(dist)[0] == _REFUSED_UNINSPECTABLE, name
    # the same bytes under a name that declares no encoding are ordinary content (control)
    dist = tmp_path / "scope-dist-plain"
    write_scope_dist(dist, extra_asset=("extra.bin", opaque))
    assert app_mod._scope_file_index(dist)[0] == "ready"


@pytest.mark.parametrize("encoding", ("gzip", "bzip2", "xz"))
def test_every_stdlib_stream_is_decoded_and_scanned_whatever_its_name(tmp_path, encoding):
    """A compiled file compressed with each standard-library codec is recognised — named with its
    suffix, or named as nothing in particular — and a clean asset compressed the same way stays
    ready (the stream really is decoded, not refused merely for being compressed)."""
    compress = _stdlib_compressors()[encoding]
    _name, compiled = min(_tracked_compiled_files().items(), key=lambda item: len(item[1]))
    suffix = {"gzip": ".gz", "bzip2": ".bz2", "xz": ".xz"}[encoding]
    cases = {
        ("fabric.json" + suffix, compress(compiled)): _REFUSED_COMPILED,
        ("evidence.bin", compress(compiled)): _REFUSED_COMPILED,
        ("inline.js", b"export const d='data:application/octet-stream;base64,"
                      + base64.b64encode(compress(compiled)) + b"';"): _REFUSED_COMPILED,
        ("runtime.js" + suffix, compress(_CLEAN_RUNTIME_ASSET)): "ready",
    }
    for index, ((name, content), expected) in enumerate(cases.items()):
        dist = tmp_path / f"scope-dist-{index}"
        write_scope_dist(dist, extra_asset=(name, content))
        assert app_mod._scope_file_index(dist)[0] == expected, (encoding, name)


@pytest.mark.parametrize("encoding", ("gzip", "bzip2", "xz"))
def test_a_stream_that_does_not_decode_completely_is_refused_as_uninspectable(tmp_path, monkeypatch,
                                                                            encoding):
    compress = _stdlib_compressors()[encoding]
    whole = compress(_CLEAN_RUNTIME_ASSET)
    truncated = whole[: len(whole) // 2]
    dist = tmp_path / "scope-dist-truncated"
    write_scope_dist(dist, extra_asset=("runtime.bin", truncated))
    assert app_mod._scope_file_index(dist)[0] == _REFUSED_UNINSPECTABLE, encoding
    # a stream that inflates beyond the per-file ceiling is not scanned up to the cap and passed:
    # what lies beyond the bound was never read
    bomb = compress(b"\0" * 300_000)
    assert len(bomb) < 64 * 1024
    monkeypatch.setattr(app_mod, "_FRONTEND_MAX_FILE_BYTES", 128 * 1024)
    dist = tmp_path / "scope-dist-over-bound"
    write_scope_dist(dist, extra_asset=("runtime.bin", bomb))
    assert app_mod._scope_file_index(dist)[0] == _REFUSED_UNINSPECTABLE, encoding


def test_a_payload_nested_beyond_the_scan_bound_is_refused_as_uninspectable(tmp_path):
    payload = _CLEAN_RUNTIME_ASSET
    for _level in range(app_mod._SCOPE_DATA_URI_DEPTH + 1):
        payload = (b"export const d='data:application/octet-stream;base64,"
                   + base64.b64encode(payload) + b"';")
    dist = tmp_path / "scope-dist-deep"
    write_scope_dist(dist, extra_asset=("deep.js", payload))
    assert app_mod._scope_file_index(dist)[0] == _REFUSED_UNINSPECTABLE
    with _client(tmp_path, dist) as c:
        r = c.get("/scope/assets/deep.js", headers={"sec-fetch-site": "same-origin"})
        assert r.status_code == 503 and r.content != payload
        assert "inspect" in r.text
        sid = c.post("/api/demo/seed").json()["snapshot"]["id"]
        view = c.get(f"/api/snapshots/{sid}/scope-view").json()
        assert view["status"] == _REFUSED_UNINSPECTABLE and view["href"] is None


# ── the mount sits behind the /api access guard ─────────────────────────────────────────────────
def _scope_urls(app) -> list[str]:
    urls = []
    for route in _scope_routes(app):
        urls.append(route.path.replace("{rest:path}", "snapshots/1/")
                    .replace("{asset_path:path}", "index-abc123.js"))
    assert {"/scope", "/scope/snapshots/1/", "/scope/assets/index-abc123.js"} <= set(urls), urls
    return urls


def test_every_scope_route_sits_behind_the_api_access_guard(tmp_path):
    """Whatever a build carries — in a form the scan knows or not — is readable exactly by whoever may
    read /api: refused cross-site, from a non-loopback peer without a token, and under a foreign Host;
    served to AssessHub's own same-origin navigation. Routes derived from the route table."""
    dist = tmp_path / "scope-dist"
    files = write_scope_dist(dist)
    with _client(tmp_path, dist) as c:
        assert app_mod.is_guarded_api_path("/scope/snapshots/1/", c.app.state.api_doc_paths)
        for url in _scope_urls(c.app):
            ok = c.get(url, headers={"sec-fetch-site": "same-origin"})
            assert ok.status_code == 200 and ok.content in files.values(), url
            for headers in ({"sec-fetch-site": "cross-site"}, {"host": "evil.example"}):
                refused = c.get(url, headers=headers)
                assert refused.status_code == 403, (url, headers, refused.status_code)
                assert SCOPE_MARKER not in refused.text and b"export const" not in refused.content
    remote = TestClient(create_app(db_path=str(tmp_path / "remote.db"), dist_dir=tmp_path / "no-spa",
                                   scope_dist_dir=dist),
                        base_url="http://localhost", client=("10.0.0.5", 50000))
    with remote as c:
        for url in _scope_urls(c.app):
            r = c.get(url)
            assert r.status_code == 403 and SCOPE_MARKER not in r.text, (url, r.status_code)


def test_in_token_mode_the_scope_mount_needs_the_session(tmp_path, monkeypatch):
    monkeypatch.setenv("ASSESSHUB_TOKEN", "t0k3n-for-scope")
    dist = tmp_path / "scope-dist"
    files = write_scope_dist(dist)
    with _client(tmp_path, dist) as c:
        for url in _scope_urls(c.app):
            r = c.get(url)
            assert r.status_code == 401 and SCOPE_MARKER not in r.text, (url, r.status_code)
        assert c.post("/api/session", headers={"authorization": "Bearer t0k3n-for-scope",
                                               "origin": "http://localhost",
                                               "sec-fetch-site": "same-origin"}).status_code < 300
        for url in _scope_urls(c.app):
            r = c.get(url, headers={"sec-fetch-site": "same-origin"})
            assert r.status_code == 200 and r.content in files.values(), (url, r.status_code)


# ── the startup index is cached by the build's own census ───────────────────────────────────────
def _count_reads(monkeypatch) -> list[str]:
    reads: list[str] = []
    real = app_mod._read_frontend_file

    def counting(path, dist):
        reads.append(Path(path).name)
        return real(path, dist)
    monkeypatch.setattr(app_mod, "_read_frontend_file", counting)
    return reads


def _scope_app(tmp_path, dist, db):
    return create_app(db_path=str(tmp_path / db), dist_dir=tmp_path / "no-spa",
                      scope_dist_dir=dist)


def test_an_unchanged_scope_build_is_indexed_once_and_a_changed_one_is_revalidated(tmp_path,
                                                                                  monkeypatch):
    dist = tmp_path / "scope-dist"
    files = write_scope_dist(dist)
    reads = _count_reads(monkeypatch)
    assert _scope_app(tmp_path, dist, "a.db").state.scope_status == "ready"
    assert sorted(set(reads)) == sorted({Path(rel).name for rel in files})
    reads.clear()
    assert _scope_app(tmp_path, dist, "b.db").state.scope_status == "ready"
    assert reads == [], "an unchanged build was re-read instead of served from the cache"

    # the build changes on disk: one asset now carries a compiled dataset -> re-validated, refused
    _name, content = min(_tracked_compiled_files().items(), key=lambda item: len(item[1]))
    (dist / "assets" / "react-def456.js").write_bytes(content)
    assert _scope_app(tmp_path, dist, "c.db").state.scope_status == _REFUSED_COMPILED
    assert reads, "a changed build was not re-read"
    reads.clear()
    # ...and cleaned again -> re-validated, served with its NEW bytes
    (dist / "assets" / "react-def456.js").write_bytes(b"export const react = 'rebuilt';")
    app = _scope_app(tmp_path, dist, "d.db")
    assert app.state.scope_status == "ready" and reads
    with TestClient(app, base_url="http://localhost") as c:
        assert c.get("/scope/assets/react-def456.js").content == b"export const react = 'rebuilt';"


def test_a_build_that_moved_while_it_was_indexed_is_not_remembered(tmp_path, monkeypatch):
    """R8-V2-3(b). The index is cached only when the build's census is unchanged AFTER indexing: a
    tree that moved mid-read produced a verdict over bytes that may not match either census, so it
    stands for that start and is never replayed. Simulated deterministically: the census taken right
    after the uncached index differs once; the next start, over the original census, must re-read."""
    dist = tmp_path / "scope-dist"
    write_scope_dist(dist)
    real_census = app_mod._frontend_tree_census
    real_uncached = app_mod._scope_file_index_uncached
    moved = {"pending": False, "fired": 0}

    def uncached(*args, **kwargs):
        result = real_uncached(*args, **kwargs)
        moved["pending"] = True  # the NEXT census is the post-index one in _scope_file_index
        return result

    def census(root):
        value = real_census(root)
        if moved["pending"] and value is not None:
            moved["pending"] = False
            moved["fired"] += 1
            return (value[0] + (("file", "assets/appeared-mid-read.js", ()),), value[1])
        return value
    monkeypatch.setattr(app_mod, "_scope_file_index_uncached", uncached)
    monkeypatch.setattr(app_mod, "_frontend_tree_census", census)
    reads = _count_reads(monkeypatch)
    assert _scope_app(tmp_path, dist, "a.db").state.scope_status == "ready"
    assert moved["fired"] == 1 and reads  # NON-VACUITY: the move was observed after a real read
    reads.clear()
    assert _scope_app(tmp_path, dist, "b.db").state.scope_status == "ready"
    assert reads, "a verdict indexed while the build moved was cached and replayed"
    # control: once the tree holds still across a start, that verdict IS remembered
    monkeypatch.setattr(app_mod, "_scope_file_index_uncached", real_uncached)
    monkeypatch.setattr(app_mod, "_frontend_tree_census", real_census)
    assert _scope_app(tmp_path, dist, "c.db").state.scope_status == "ready"
    reads.clear()
    assert _scope_app(tmp_path, dist, "d.db").state.scope_status == "ready"
    assert reads == []


def test_a_build_without_the_runtime_declaration_is_refused_after_reading_only_its_shell(
        tmp_path, monkeypatch):
    """The real repository build today (the standalone sample build) is ~10 MB and declares no
    runtime source: refusing it must not cost a full read and hash of every file on every start."""
    dist = tmp_path / "scope-dist"
    write_scope_dist(dist, runtime_source=None, extra_asset=("big.js.map", b"x" * 2_000_000))
    reads = _count_reads(monkeypatch)
    assert _scope_app(tmp_path, dist, "a.db").state.scope_status == "invalid_build"
    assert reads == ["index.html"]


# ── the withdrawal is re-checked at request time ────────────────────────────────────────────────
def _store_sample_through_another_store(db_path: Path) -> str:
    from backend.storage import Store

    snap = json.loads(app_mod.SAMPLE_SNAPSHOT.read_text(encoding="utf-8"))
    other = Store(str(db_path))
    try:
        campaign = other.create_campaign("another process")
        meta = other.add_snapshot(campaign["id"], "stored elsewhere", snap,
                                  app_mod.summary.summarize(snap))
        return str(meta["id"])
    finally:
        other.close()


@pytest.mark.parametrize("first", ["asset", "scope-view"])
def test_a_snapshot_stored_through_another_store_withdraws_a_running_build(tmp_path, first):
    """A second process (portable/qualify_atlas.py opens its own Store) or a second Store in this
    process inserts a snapshot whose digest the running build embeds. This app's insert observer
    never sees it; the next scope request or capability read must, not the next restart."""
    digest = _demo_blob_sha256()
    dist = tmp_path / "scope-dist"
    write_scope_dist(dist, extra_asset=("mount-x.js", f'export const s="{digest}";'.encode()))
    with _client(tmp_path, dist, db_name="shared.db") as c:
        assert c.get("/scope/assets/mount-x.js").status_code == 200  # nothing stored yet
        sid = _store_sample_through_another_store(tmp_path / "shared.db")
        if first == "scope-view":
            view = c.get(f"/api/snapshots/{sid}/scope-view").json()
            assert view["status"] == "refused_embeds_stored_snapshot" and view["href"] is None
        r = c.get("/scope/assets/mount-x.js")
        assert r.status_code == 503 and digest not in r.text and "stored snapshot" in r.text
        assert c.get("/scope/snapshots/1/").status_code == 503


def test_with_hex_tokens_the_scope_routes_only_run_the_digest_recheck(tmp_path):
    """When a build embeds 64-hex tokens the request-time re-check needs the store — and it is the
    ONLY store access, returning digests (never snapshot content). Without tokens there is none at
    all (test_scope_routes_answer_without_any_store_access)."""
    dist = tmp_path / "scope-dist"
    write_scope_dist(dist, extra_asset=("mount-x.js", b'export const s="' + b"ab" * 32 + b'";'))
    allowed = "snapshot_blob_digests_after"
    with _client(tmp_path, dist) as c:
        store = c.app.state.store
        touched, results, tripped = [], [], []
        real_recheck = getattr(store, allowed)
        for name in dir(store):
            if name.startswith("__") or not callable(getattr(type(store), name, None)):
                continue
            if name == allowed:
                def _record(*a, **k):
                    touched.append(allowed)
                    results.append(real_recheck(*a, **k))
                    return results[-1]
                setattr(store, name, _record)
            else:
                def _trip(*_a, _n=name, **_k):
                    touched.append(_n)
                    raise AssertionError(f"scope route touched Store.{_n}")
                setattr(store, name, _trip)
            tripped.append(name)
        try:
            assert allowed in tripped
            for path in ("/scope/snapshots/7/", "/scope/assets/mount-x.js"):
                r = c.get(path, headers={"sec-fetch-site": "same-origin"})
                assert r.status_code == 200, (path, r.status_code)
            assert touched and set(touched) == {allowed}
            for watermark, digests in results:
                assert isinstance(watermark, int)
                assert all(re.fullmatch(r"[0-9a-f]{64}", d) for d in digests)
        finally:
            for name in tripped:
                delattr(store, name)


# ── same-origin write containment (defence in depth) ────────────────────────────────────────────
# Atlas Scope is first-party, read-only code served same-origin, so the /api guard's cross-site and
# CSRF checks pass its requests. A read-only viewer never writes: /scope pages send a same-origin
# Referer (Referrer-Policy: same-origin, while the rest of AssessHub sends none), and the /api
# guard refuses every non-GET request whose Referer path is under /scope/. A hostile script can
# suppress or rewrite its Referer, so this is a second wall behind "no write code in the viewer",
# not a sandbox.
_SCOPE_REFERERS = [
    "http://localhost/scope/snapshots/1/",
    "http://localhost/scope",
    "http://localhost/scope/assets/index-abc123.js",
    "http://localhost/%73cope/snapshots/1/",
    "http://localhost/SCOPE/snapshots/1/",
    "http://localhost/elsewhere/../scope/snapshots/1/",
    "http://localhost//scope/snapshots/1/",
    # served AS the scope shell by the router (percent-decoded, dot segments kept), and kept
    # verbatim by a browser in the page URL it sends as Referer (%2f is not a WHATWG separator)
    "http://localhost/scope/..%2f..%2fcampaigns",
    "http://localhost/scope/%2e%2e%2fx",
    "http://localhost/scope/..%2fx",
]
_OTHER_REFERERS = [None, "http://localhost/campaigns", "http://localhost/scopes/1/",
                   "http://localhost/snapshots/scope/"]


def test_every_scope_response_carries_referrer_policy_same_origin(tmp_path):
    dist = tmp_path / "scope-dist"
    write_scope_dist(dist)
    with _client(tmp_path, dist) as c:
        for method, path, expected in (("GET", "/scope", 200), ("GET", "/scope/snapshots/1/", 200),
                                       ("GET", "/scope/assets/index-abc123.js", 200),
                                       ("GET", "/scope/assets/nope.js", 404),
                                       ("POST", "/scope/", 405), ("HEAD", "/scope/", 405)):
            r = c.request(method, path)
            assert r.status_code == expected, (method, path, r.status_code)
            assert r.headers["referrer-policy"] == "same-origin", (method, path)
        # the rest of AssessHub still sends no Referer at all
        for path in ("/api/health", "/campaigns", "/assets/app.js"):
            assert c.get(path).headers["referrer-policy"] == "no-referrer", path
    with _client(tmp_path, None, db_name="absent.db") as c:
        r = c.get("/scope/snapshots/1/")
        assert r.status_code == 503 and r.headers["referrer-policy"] == "same-origin"


def test_every_api_write_refuses_a_request_referred_from_a_scope_page(tmp_path):
    from fastapi.routing import APIRoute

    dist = tmp_path / "scope-dist"
    write_scope_dist(dist)
    with _client(tmp_path, dist) as c:
        same_origin = {"origin": "http://localhost", "sec-fetch-site": "same-origin"}
        before = c.get("/api/campaigns").json()
        writes = sorted({(method, re.sub(r"\{[^}]+\}", "1", route.path))
                         for route in c.app.routes
                         if isinstance(route, APIRoute) and route.path.startswith("/api/")
                         for method in set(route.methods) - {"GET", "HEAD"}})
        assert len(writes) >= 10, writes  # NON-VACUITY: derived from the route table
        for method, url in writes + [("OPTIONS", "/api/campaigns")]:
            r = c.request(method, url, headers={**same_origin, "referer": _SCOPE_REFERERS[0]})
            assert r.status_code == 403, (method, url, r.status_code, r.text[:200])
            assert "Atlas Scope" in r.json()["detail"]
        for referer in _SCOPE_REFERERS:
            r = c.post("/api/campaigns", json={"name": "from scope"},
                       headers={**same_origin, "referer": referer})
            assert r.status_code == 403, (referer, r.status_code)
        assert c.get("/api/campaigns").json() == before  # nothing was written
        # controls: the same write without a /scope Referer is served, so the 403 is this rule
        for referer in _OTHER_REFERERS:
            headers = dict(same_origin, **({"referer": referer} if referer else {}))
            r = c.post("/api/campaigns", json={"name": f"ok {referer}"}, headers=headers)
            assert r.status_code == 201, (referer, r.status_code, r.text[:200])
        # a scope page still READS the API it exists to read
        assert c.get("/api/campaigns",
                     headers={**same_origin, "referer": _SCOPE_REFERERS[0]}).status_code == 200


def test_a_write_referred_from_any_url_the_router_serves_as_the_scope_shell_is_refused(tmp_path):
    """R8-V2, derived from the router rather than from a list of spellings: every request target
    the app ANSWERS with the Atlas Scope shell is a page Atlas Scope can run at, so a write whose
    Referer names it is refused."""
    dist = tmp_path / "scope-dist"
    files = write_scope_dist(dist)
    targets = sorted({path for path, _plantable in _SHELL_TRAVERSALS}
                     | {"/scope", "/scope/", "/scope/snapshots/1/", "/scope/..%2f..%2fcampaigns",
                        "/scope/%2e%2e%2fx", "/scope/..%2fx", "/scope/a/..%2f..%2f..%2fx"})
    with _client(tmp_path, dist) as c:
        served_as_scope = [t for t in targets if _raw_get(c.app, t) == (200, files["index.html"])]
        # NON-VACUITY: the router really serves dot-segment-bearing targets as the scope shell
        assert len(served_as_scope) >= 10 and "/scope/..%2f..%2fcampaigns" in served_as_scope
        before = c.get("/api/campaigns").json()
        for target in served_as_scope:
            r = c.post("/api/campaigns", json={"name": "from scope"},
                       headers={"origin": "http://localhost", "sec-fetch-site": "same-origin",
                                "referer": "http://localhost" + target})
            assert r.status_code == 403, (target, r.status_code)
        assert c.get("/api/campaigns").json() == before
