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
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

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


def _source_shell_inline_scripts() -> list[str]:
    """The inline classic scripts of the shell the hub build is made from (atlas-scope/index.html):
    Vite copies them verbatim into the hub shell. The fixture shell carries the same one, so the
    fixture exercises the reader's real accept-list, not a script only a test would write."""
    source = (Path(__file__).resolve().parents[2] / "atlas-scope" / "index.html").read_text(
        encoding="utf-8")

    class _InlineClassicScripts(HTMLParser):
        """Collects the body of every <script> that has no ``src`` and no module ``type``. The
        parser lower-cases tag names and reads a script's body as raw text, so an upper-case tag or a
        ``<`` inside the body cannot make it miss a script the way a tag regex would (CodeQL
        py/bad-tag-filter on the regex this replaces)."""

        def __init__(self) -> None:
            super().__init__()
            self.bodies: list[str] = []
            self._open = False

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            attributes = dict(attrs)
            classic = (attributes.get("type") or "").strip().lower() in ("", "text/javascript")
            self._open = tag == "script" and "src" not in attributes and classic

        def handle_data(self, data: str) -> None:
            if self._open:
                self.bodies.append(data)

        def handle_endtag(self, tag: str) -> None:
            if tag == "script":
                self._open = False

    parser = _InlineClassicScripts()
    parser.feed(source.replace("\r\n", "\n"))
    parser.close()
    assert parser.bodies, "atlas-scope/index.html carries no inline classic script for the fixture to copy"
    return parser.bodies


_THEME_BOOT = _source_shell_inline_scripts()[0]
#: The fixture shell's icon: without one, a browser requests the origin's /favicon.ico -- outside
#: /scope (measured in Chromium's full headless and headed modes; RQF-V1-4).
_SHELL_ICON = '<link rel="icon" href="data:image/svg+xml,%3Csvg%3E%3C/svg%3E">'


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
        f"<script>{_THEME_BOOT}</script>"
        "<title>Atlas Scope</title>"
        f"{_SHELL_ICON}"
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
#: file inside this test's own tmp directory on EVERY platform — there the canary is planted exactly
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
    test's own directory, where a canary can be planted at the exact spot a naive shell would read."""
    return tmp_path / "d1" / "d2" / "scope-dist"


def _plant_where_a_naive_shell_would_read(tmp_path: Path, dist: Path, raw_target: str,
                                          prefix: str, base: Path | None = None) -> bytes | None:
    """Plant a unique canary at ``normpath(base / rest)`` (``base`` defaults to the build root) —
    pure string arithmetic, never a filesystem resolve (which would touch a UNC share) — when that
    lands outside the build ``dist`` and inside tmp_path. Returns the canary, or None when the target
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
    canary = b"PLANTED-CANARY-" + hashlib.sha256(raw_target.encode()).hexdigest()[:16].encode()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(canary)
    return canary


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
    canary = _plant_where_a_naive_shell_would_read(tmp_path, dist, path, "/scope/")
    # NON-VACUITY: the inputs that climb out of the build really do have a canary waiting exactly
    # where `dist / rest` points, so serving from disk would hand it out.
    assert canary is not None or not plantable, f"{path}: nothing planted where it resolves"
    with _client(tmp_path, dist) as c:
        with _filesystem_trap(monkeypatch) as touched:
            status, body = _raw_get(c.app, path)
        assert touched == [], f"{path}: the scope shell touched the filesystem at request time"
        if canary is not None:
            assert canary not in body
        assert status == 200, (path, status)
        assert body == files["index.html"], path


@pytest.mark.parametrize("path,plantable", _ASSET_TRAVERSALS)
def test_scope_asset_traversal_is_404_never_a_file_outside_assets(tmp_path, monkeypatch, path,
                                                                  plantable):
    dist = _nested_scope_dist(tmp_path)
    write_scope_dist(dist)
    canary = _plant_where_a_naive_shell_would_read(tmp_path, dist, path, "/scope/assets/",
                                                   base=dist / "assets")
    assert canary is not None or not plantable, f"{path}: nothing planted where it resolves"
    with _client(tmp_path, dist) as c:
        with _filesystem_trap(monkeypatch) as touched:
            status, body = _raw_get(c.app, path)
        assert touched == [], f"{path}: the scope asset route touched the filesystem"
        if canary is not None:
            assert canary not in body
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
    # P3F-V2-1: parser differentials. Python's stdlib HTMLParser read each of these differently from
    # a browser's WHATWG tokenizer and hid a meta that Chromium APPLIES (measured: no Referer on a
    # same-origin POST). The /scope reader no longer judges with a tokenizer that differs from the
    # browser's (app._scope_html_reading); the generated Chromium family further below proves it
    # over the whole comment / markup-declaration / raw-text / nesting class, not these six.
    "abrupt-empty-comment": '<!--><meta name="referrer" content="no-referrer"><!-- -->',
    "abrupt-dash-comment": '<!---><meta name="referrer" content="no-referrer"><!-- -->',
    # QF-R1-2: the same two abrupt openings closed by a plain `-->`, so that no OTHER comment rule
    # (a `<!--` inside the comment data) refuses them: only the abrupt-opening rule itself can.
    "abrupt-empty-comment-closed": '<!--><meta name="referrer" content="no-referrer">-->',
    "abrupt-dash-comment-closed": '<!---><meta name="referrer" content="no-referrer">-->',
    "bang-closed-comment-closed": '<!--x--!><meta name="referrer" content="no-referrer">-->',
    "bang-closed-comment": '<!--x--!><meta name="referrer" content="no-referrer"><!-- -->',
    "script-end-tag-with-attribute": ('<script>/**/</script x><meta name="referrer" '
                                      'content="no-referrer"><script>/**/</script>'),
    "script-end-tag-self-closing": ('<script>/**/</script/><meta name="referrer" '
                                    'content="no-referrer"><script>/**/</script>'),
    "style-end-tag-with-attribute": ('<style>/**/</style x><meta name="referrer" '
                                     'content="no-referrer"><style>/**/</style>'),
}
_PARSER_DIFFERENTIAL_FORMS = ("abrupt-empty-comment", "abrupt-dash-comment",
                              "abrupt-empty-comment-closed", "abrupt-dash-comment-closed",
                              "bang-closed-comment", "bang-closed-comment-closed",
                              "script-end-tag-with-attribute", "script-end-tag-self-closing",
                              "style-end-tag-with-attribute")


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


#: RQF-V1-6. An HTML page under /scope other than the shell is a page AssessHub would serve with
#: none of the shell's accept-list -- it could load any URL (measured below in Chromium) or declare
#: its own referrer policy. The hub build ships none (only index.html, JavaScript and CSS:
#: test_the_hub_build_ships_no_document_but_its_shell), so every one is refused, whatever it holds
#: -- the same decision as for XML (QF-V2-1): what AssessHub does not need, it does not judge.
_HTML_PAGES = {
    "referrer-meta": '<meta name="referrer" content="no-referrer">',
    "third-party-image": '<img src="https://third-party.invalid/x">',
    "outside-scope-script": '<script src="/outside-scope/x.js"></script>',
    "description-only": '<meta name="description" content="x">',
    "empty": "",
}


@pytest.mark.parametrize("page", sorted(_HTML_PAGES))
def test_every_html_page_but_the_shell_is_refused_whatever_it_holds(tmp_path, page):
    """The class is every HTML document served under /scope, not only the shell: an HTML asset at
    /scope/assets/x.html is a page under /scope too. It is refused for being a page at all -- a
    clean one included -- so no rule for what a page may load or declare needs to hold there."""
    document = ("<!doctype html><html><head><title>x</title>" + _HTML_PAGES[page]
                + "</head><body>x</body></html>").encode("utf-8")
    template = write_scope_dist(tmp_path / "template")
    assert app_mod._scope_markup_refusal(_scope_members(template)) is None
    for name in ("assets/x.html", "assets/nested/page.HTML", "assets/x.htm", "other.html"):
        assert app_mod._scope_markup_kind(app_mod._frontend_media_type(name)) == "html", name
        members = _scope_members({**template, name: document})
        assert app_mod._scope_markup_refused(members), f"{name} ({page}) served ready"
        assert app_mod._scope_markup_refusal(members) == \
            f"{name}: {app_mod._SCOPE_REFUSED_HTML_PAGE}", (page, name)
    dist = tmp_path / "scope-dist"
    write_scope_dist(dist, extra_asset=("x.html", document))
    with _client(tmp_path, dist) as c:
        assert c.app.state.scope_status == "invalid_build", page
        assert c.get("/scope/assets/x.html").status_code == 503
    # the control: the same build without the page is served
    (dist / "assets" / "x.html").unlink()
    with _client(tmp_path, dist, db_name="control.db") as c:
        assert c.app.state.scope_status == "ready"


_REPEATED_SHELL_ATTRIBUTES = {
    "script-src": (b'src="/scope/assets/index-abc123.js"',
                   b'src="https://example.invalid/x.js" src="/scope/assets/index-abc123.js"'),
    "link-href": (b'href="/scope/assets/react-def456.js"',
                  b'href="https://example.invalid/x.js" href="/scope/assets/react-def456.js"'),
    "runtime-source-content": (b'content="assesshub-api-runtime"',
                               b'content="sample-fleet" content="assesshub-api-runtime"'),
}


@pytest.mark.parametrize("variant", sorted(_REPEATED_SHELL_ATTRIBUTES))
def test_a_scope_shell_repeating_an_attribute_is_refused_because_a_browser_keeps_the_first(
        tmp_path, variant):
    """QF-R1-2 (per-clause): a browser keeps the FIRST of a repeated attribute and drops the rest,
    so a shell repeating a checked attribute would load or declare what the FIRST says while any
    last-wins reading approves what the second says. The reader refuses every repeat."""
    dist = tmp_path / "scope-dist"
    files = write_scope_dist(dist)
    plain, repeated = _REPEATED_SHELL_ATTRIBUTES[variant]
    assert files["index.html"].count(plain) == 1
    (dist / "index.html").write_bytes(files["index.html"].replace(plain, repeated))
    with _client(tmp_path, dist) as c:
        assert c.app.state.scope_status == "invalid_build", variant
    (dist / "index.html").write_bytes(files["index.html"])
    with _client(tmp_path, dist, db_name="control.db") as c:
        assert c.app.state.scope_status == "ready"


#: QF-V2-3. "Every URL the shell loads is a startup-indexed /scope asset" held over a closed
#: ACCEPT-list of constructs (app._SCOPE_SHELL_ELEMENTS and its attribute rules), never over a list
#: of URL-bearing attributes: a construct not on the list is refused whatever it is. The generator
#: below spells a load through every URL-bearing construct enumerated here -- attributes, SVG
#: xlink:href/href and paint servers, style attributes and elements (url(), image-set(), escapes,
#: custom properties, @import, @font-face), meta refresh, every link relation, base, srcdoc, inline
#: and module scripts and event handlers -- to a third-party origin, protocol-relative, and to
#: same-origin paths outside /scope; real Chromium then proves the property with request
#: interception (test_no_scope_shell_served_ready_makes_a_request_outside_scope).
_SHELL_LOAD_URLS = {"third-party": "https://third-party.invalid/x",
                    "protocol-relative": "//third-party.invalid/x",
                    "outside-scope": "/outside-scope/x"}
_SHELL_LOADS = {
    "img-src": '<img src="{u}">', "img-srcset": '<img srcset="{u} 1x">',
    "picture-source": '<picture><source srcset="{u}"><img alt=""></picture>',
    "video-poster": '<video poster="{u}"></video>',
    "video-src": '<video src="{u}" preload="auto"></video>',
    "video-source": '<video preload="auto"><source src="{u}"></video>',
    "audio-src": '<audio src="{u}" preload="auto"></audio>',
    "track-src": '<video preload="auto"><track default src="{u}"></video>',
    "object-data": '<object data="{u}"></object>', "embed-src": '<embed src="{u}">',
    "iframe-src": '<iframe src="{u}"></iframe>',
    "iframe-srcdoc": '<iframe srcdoc="&lt;img src=&quot;{u}&quot;&gt;"></iframe>',
    "input-image": '<input type="image" src="{u}">',
    "table-background": '<table background="{u}"><tr><td>x</td></tr></table>',
    "td-background": '<table><tr><td background="{u}">x</td></tr></table>',
    "body-background": '<body background="{u}">',
    "svg-image-href": '<svg><image href="{u}" width="9" height="9"/></svg>',
    "svg-image-xlink-href": ('<svg xmlns:xlink="http://www.w3.org/1999/xlink"><image xlink:href="{u}" '
                             'width="9" height="9"/></svg>'),
    "svg-use-href": '<svg><use href="{u}#x"/></svg>',
    "svg-feimage": ('<svg><filter id="f"><feImage href="{u}"/></filter>'
                    '<rect filter="url(#f)" width="9" height="9"/></svg>'),
    "svg-paint-server": '<svg><rect fill="url({u}#g)" width="9" height="9"/></svg>',
    "svg-script-href": '<svg><script href="{u}"></script></svg>',
    "svg-style-element": '<svg><style>rect{{fill:url({u}#g)}}</style><rect width="9" height="9"/></svg>',
    "style-url": '<div style="background:url({u})">x</div>',
    "style-url-quoted": '<div style="background-image:url(&quot;{u}&quot;)">x</div>',
    "style-image-set": '<div style="background-image:image-set(&quot;{u}&quot; 1x)">x</div>',
    "style-webkit-image-set": '<div style="background-image:-webkit-image-set(url({u}) 1x)">x</div>',
    "style-escaped-url": '<div style="background:u\\72l({u})">x</div>',
    "style-commented-url": '<div style="background:u/**/rl({u})">x</div>',
    "style-custom-property": '<div style="--x:url({u});background:var(--x)">x</div>',
    "style-list-style-image": '<ul style="list-style-image:url({u})"><li>x</li></ul>',
    "style-border-image": '<div style="border:1px solid;border-image:url({u}) 1">x</div>',
    "style-mask-image": '<div style="-webkit-mask-image:url({u});mask-image:url({u})">x</div>',
    "style-content": '<div style="content:url({u})">x</div>',
    "style-cursor": '<div style="cursor:url({u}),auto">x</div>',
    "style-element-url": "<style>body{{background:url({u})}}</style>",
    "style-element-import": "<style>@import url({u});</style>",
    "style-element-import-string": '<style>@import "{u}";</style>',
    "style-element-font-face": ("<style>@font-face{{font-family:q;src:url({u})}}"
                                "body{{font-family:q}}</style>"),
    "meta-refresh": '<meta http-equiv="refresh" content="0;url={u}">',
    "meta-link-header": '<meta http-equiv="Link" content="&lt;{u}&gt;; rel=preload; as=image">',
    **{f"link-{rel}": f'<link rel="{rel}" href="{{u}}">'
       for rel in ("stylesheet", "modulepreload", "prefetch", "icon", "manifest", "preconnect",
                   "dns-prefetch", "alternate stylesheet", "apple-touch-icon", "prerender")},
    "link-preload-image": '<link rel="preload" as="image" href="{u}">',
    "link-preload-fetch": '<link rel="preload" as="fetch" crossorigin href="{u}">',
    "link-preload-imagesrcset": '<link rel="preload" as="image" imagesrcset="{u} 1x">',
    "link-stylesheet-crossorigin": '<link rel="stylesheet" crossorigin href="{u}">',
    "base-href": '<base href="{u}/">',
    "script-src": '<script src="{u}"></script>',
    "script-module-src": '<script type="module" src="{u}"></script>',
    "script-inline-fetch": '<script>fetch("{u}")</script>',
    "script-inline-module-import": '<script type="module">import("{u}")</script>',
    "img-onerror": '<img src="data:," onerror="fetch(&quot;{u}&quot;)">',
    "body-onload": '<body onload="fetch(&quot;{u}&quot;)">',
    "svg-onload": '<svg onload="fetch(&quot;{u}&quot;)"></svg>',
    "html-manifest": '<html manifest="{u}">',
    "a-ping": '<a href="/scope/" ping="{u}">x</a>',
    "form-action": '<form action="{u}"><button formaction="{u}">x</button></form>',
    "noscript-img": '<noscript><img src="{u}"></noscript>',
    "template-img": "<template><img src=\"{u}\"></template>",
    "math-href": '<math href="{u}"><mi>x</mi></math>',
}
#: Constructs the accept-list admits: they carry a URL-shaped value where no browser loads it, or
#: load only a startup-indexed /scope asset. Each must be served ready AND load nothing outside
#: /scope in Chromium -- the non-vacuity half (a list that refused everything would prove nothing).
_SHELL_INERT = {
    "data-attribute": '<div data-src="{u}">x</div>',
    "aria-attribute": '<span aria-label="{u}">x</span>',
    "title-attribute": '<p title="url({u})">x</p>',
    "class-attribute": '<p id="x" class="{u}">x</p>',
    "meta-description": '<meta name="description" content="{u}">',
    "style-inert": '<p style="margin:0;color:var(--text,CanvasText);width:calc(100% - 2px)">x</p>',
    "modulepreload-indexed": '<link rel="modulepreload" crossorigin href="/scope/assets/react-def456.js">',
    "stylesheet-indexed": '<link rel="stylesheet" href="/scope/assets/index-789.css">',
}


def _shell_family() -> dict[str, tuple[str, bool]]:
    """id -> (fragment for the fixture shell (_shell_with), whether the reader must REFUSE it:
    every construct that loads -- ids `load:` -- and the few it refuses conservatively, `refused:`;
    the inert ones, `inert:`, it must serve)."""
    family = {}
    for construct, template in _SHELL_LOADS.items():
        for url_id, url in _SHELL_LOAD_URLS.items():
            family[f"load:{construct}:{url_id}"] = (template.format(u=url), True)
    for construct, template in _SHELL_INERT.items():
        family[f"inert:{construct}"] = (template.format(u=_SHELL_LOAD_URLS["third-party"]), False)
    # a relation the list does not name is refused even over a startup-indexed asset: a manifest's
    # members name further URLs (icons, start_url) the reader never reads, and the list stays closed
    for relation in ("manifest", "preload", "prefetch", "alternate stylesheet", "icon stylesheet"):
        family[f"load:unlisted-relation-{relation.replace(' ', '-')}:indexed"] = (
            f'<link rel="{relation}" href="/scope/assets/index-789.css">', True)
    # RQF-V1-4: a shell that declares NO icon in its head makes the browser request the origin's
    # /favicon.ico, outside /scope, by default -- a load no attribute names. Measured: an icon the
    # browser meets only after the head has ended (behind body text, a <p>, `</head><body>`) comes
    # too late, and the default request is made; an icon anywhere in the head is honoured.
    family["load:icon-absent"] = (_WITHOUT_ICON, True)
    family["load:icon-in-body"] = (_WITHOUT_ICON + "</head><body><p>x</p>" + _SHELL_ICON, True)
    family["load:icon-after-body-text"] = (_WITHOUT_ICON + "x" + _SHELL_ICON, True)
    family["load:icon-after-a-p"] = (_WITHOUT_ICON + "<p>x</p>" + _SHELL_ICON, True)
    family["load:icon-after-an-empty-div"] = (_WITHOUT_ICON + "<div></div>" + _SHELL_ICON, True)
    family["load:icon-after-an-empty-span"] = (_WITHOUT_ICON + "<span></span>" + _SHELL_ICON, True)
    family["load:icon-after-a-body-tag"] = (_WITHOUT_ICON + "<body>" + _SHELL_ICON, True)
    # refused CONSERVATIVELY (ids `refused:`): measured, the browser makes no default request here
    # -- a <link> after `</head>` goes back into the head, and `</br>` or `</p>` in the head leaves
    # the icon honoured -- but the reader keeps its head rule simple: before the icon, no end tag
    # but the one closing a title or script (_scope_shell_declares_an_icon_in_its_head)
    family["refused:icon-after-a-closed-head"] = (_WITHOUT_ICON + "</head>" + _SHELL_ICON, True)
    family["refused:icon-after-a-br-end-tag"] = (_WITHOUT_ICON + "</br>" + _SHELL_ICON, True)
    family["inert:body-content-after-the-icon"] = ("<p>x</p><div>y</div>", False)
    # RQF-V2-1: an icon link the markup reader reads but the BROWSER does not build is no icon, and
    # the browser requests /favicon.ico. The reader reads no element as raw text (a superset of the
    # browser's reading, safe only for what must be ABSENT), so the shell's positive requirements
    # must be judged on the browser's own reading. Measured in Chromium (2 of 2 runs each): an icon
    # inside every element the browser reads as raw text or RCDATA -- with its end tag and without
    # -- inside a comment, a template or foreign content, and an icon whose `rel` carries a
    # non-ASCII blank (the browser splits a token list on ASCII whitespace only) all request it;
    # an icon after a CLOSED title, a `rel` in upper case or padded with ASCII blanks, and an icon
    # whose data: URL or indexed asset Chromium cannot decode do not (it falls back to no default).
    for element in _RAW_TEXT_ELEMENTS:
        family[f"load:icon-inside-{element}"] = (
            _WITHOUT_ICON + f"<{element}>{_SHELL_ICON}</{element}>", True)
        family[f"load:icon-inside-an-unclosed-{element}"] = (
            _WITHOUT_ICON + f"<{element}>{_SHELL_ICON}", True)
    family["load:icon-inside-an-upper-case-title"] = (_WITHOUT_ICON + f"<TITLE>{_SHELL_ICON}</TITLE>", True)
    family["load:icon-inside-a-title-closed-with-a-blank"] = (
        _WITHOUT_ICON + f"<title>{_SHELL_ICON}</title >", True)
    family["load:icon-inside-a-title-after-its-text"] = (
        _WITHOUT_ICON + f"<title>x {_SHELL_ICON}</title>", True)
    family["load:icon-inside-a-comment"] = (_WITHOUT_ICON + f"<!--{_SHELL_ICON}-->", True)
    family["load:icon-inside-a-template"] = (_WITHOUT_ICON + f"<template>{_SHELL_ICON}</template>", True)
    family["load:icon-inside-svg"] = (_WITHOUT_ICON + f"<svg>{_SHELL_ICON}</svg>", True)
    for name, blank in _NON_ASCII_BLANKS.items():
        family[f"load:icon-rel-ending-in-{name}"] = (
            _WITHOUT_ICON + _SHELL_ICON.replace('rel="icon"', f'rel="icon{blank}"'), True)
    family["inert:icon-after-a-closed-title"] = (_WITHOUT_ICON + "<title>x</title>" + _SHELL_ICON, False)
    family["inert:icon-rel-in-upper-case"] = (
        _WITHOUT_ICON + _SHELL_ICON.replace('rel="icon"', 'rel="ICON"'), False)
    family["inert:icon-rel-padded-with-ascii-blanks"] = (
        _WITHOUT_ICON + _SHELL_ICON.replace('rel="icon"', 'rel=" icon\t"'), False)
    for name, href in (("data-url-without-a-comma", "data:image/png"),
                       ("data-url-with-bad-base64", "data:image/png;base64,%%%"),
                       ("data-url-that-is-no-image", "data:image/png,notanimage"),
                       ("indexed-asset-that-is-no-image", "/scope/assets/index-789.css")):
        family[f"inert:icon-href-{name}"] = (
            _WITHOUT_ICON + f'<link rel="icon" href="{href}">', False)
    return family


#: Blanks Python's str.split() splits on but the browser does not: HTML splits a token list (`rel`)
#: on ASCII whitespace only, so `rel="icon<blank>"` names no icon to a browser (measured).
_NON_ASCII_BLANKS = {"no-break-space": " ", "ideographic-space": "　", "em-space": " ",
                     "next-line": "\x85", "line-separator": " "}


#: A fragment starting with this REPLACES the template shell's icon link (see _shell_with).
_WITHOUT_ICON = "<!--without-icon-->"


def _shell_with(fragment: str, template: dict[str, bytes]) -> bytes:
    """The template shell with ``fragment`` directly after its icon link -- still in the head, so a
    fragment that ends the head (a <p>, an <img>) leaves the icon declared there -- or, for a
    fragment starting with _WITHOUT_ICON, in the icon link's place."""
    shell, icon = template["index.html"], _SHELL_ICON.encode("utf-8")
    assert shell.count(icon) == 1
    if fragment.startswith(_WITHOUT_ICON):
        return shell.replace(icon, fragment[len(_WITHOUT_ICON):].encode("utf-8"), 1)
    return shell.replace(icon, icon + fragment.encode("utf-8"), 1)


#: RQF-V1-3. The shell links a startup-indexed stylesheet, and a stylesheet loads what it names:
#: `@import`, url(), image-set() and every other resource function fetch from the browser exactly
#: as a <style> element would. Every text/css member is therefore held to a closed ACCEPT-list
#: (app._scope_css_refusal): no escape, a closed set of at-rules and of functions -- none of them a
#: resource function -- and no `url` word, so no declaration can name a resource. The family spells
#: a load through every resource-naming CSS construct enumerated here, each to the three URLs above;
#: the inert half is CSS the list admits, the repository's own hub stylesheets included.
_CSS_LOADS = {
    "url": "body{{background:url({u})}}",
    "url-quoted": 'body{{background-image:url("{u}")}}',
    "url-single-quoted": "body{{background-image:url('{u}')}}",
    "url-upper": "body{{background:URL({u})}}",
    "import-url": "@import url({u});body{{color:red}}",
    "import-string": '@import "{u}";body{{color:red}}',
    "import-layer": '@import "{u}" layer(x);',
    "import-upper": '@IMPORT "{u}";',
    "image-set": 'body{{background-image:image-set("{u}" 1x)}}',
    "webkit-image-set": "body{{background-image:-webkit-image-set(url({u}) 1x)}}",
    "image-function": 'body{{background-image:image("{u}")}}',
    "cross-fade": 'body{{background-image:-webkit-cross-fade(url({u}),url({u}),50%)}}',
    "src-function": 'body{{background-image:src("{u}")}}',
    "font-face": '@font-face{{font-family:q;src:url({u})}}body{{font-family:q}}',
    "font-face-format": '@font-face{{font-family:q;src:url({u}) format("woff2")}}body{{font-family:q}}',
    "custom-property": ":root{{--x:url({u})}}body{{background:var(--x)}}",
    "list-style-image": "ul,body{{list-style-image:url({u})}}",
    "border-image": "body{{border:1px solid;border-image:url({u}) 1}}",
    "mask-image": "body{{-webkit-mask-image:url({u});mask-image:url({u})}}",
    "cursor": "body{{cursor:url({u}),auto}}",
    "content": "body:before{{content:url({u})}}",
    "filter": "body{{filter:url({u}#f)}}",
    "clip-path": "body{{clip-path:url({u}#c)}}",
    "shape-outside": "body{{float:left;shape-outside:url({u})}}",
    "escaped-url": "body{{background:u\\72l({u})}}",
    "escaped-import": '@\\69mport "{u}";',
    "escaped-string": 'body{{background-image:image-set("\\{u}" 1x)}}',
    "namespace": "@namespace url({u});",
    "media-nested": "@media all{{body{{background:url({u})}}}}",
    "supports-nested": "@supports (display:grid){{body{{background:url({u})}}}}",
    "container-nested": "@container (min-width:1px){{body{{background:url({u})}}}}",
    "commented-around": "body{{background:/**/url({u})/**/}}",
    "bom-prefixed": "\ufeffbody{{background:url({u})}}",
    # CSS Values' typed attr(): `attr(name url)` would make an attribute's value a URL with no url(
    # token at all -- refused by the word `url` itself, escaped or not
    # a line feed ends a CSS string (a bad-string) and the declarations after it are read as code:
    # a reader that let the string run on to its next quote would hide this url()
    "string-broken-by-a-line-feed": 'p:after{{content:"a\n;background:url({u})}}p:before{{content:"}}',
    "attr-url": 'p{{background-image:attr(data-src url)}}p:after{{content:"{u}"}}',
    "attr-url-escaped": 'p{{background-image:attr(data-src u\\72l)}}p:after{{content:"{u}"}}',
}
_CSS_INERT = {
    "tokens": ":root{--bg:#000;--text:#fff}body{background:var(--bg,Canvas);color:var(--text)}",
    "gradient": "body{background:linear-gradient(90deg,rgb(0 0 0),color-mix(in srgb,red 50%,blue))}",
    "url-in-a-string": 'body:before{content:"url(https://third-party.invalid/x)"}',
    "url-in-a-comment": "/* url(https://third-party.invalid/x) @import */body{color:red}",
    "attr-content": "p[data-src]:before{content:attr(data-src)}",
    "media-container": "@media (min-width:1px){body{margin:0}}@container (min-width:1px){p{margin:0}}",
    "font-family-string": 'body{font-family:"Inter var",system-ui,sans-serif}',
    "bom-prefixed": "\ufeffbody{margin:0}",
    # escapes the hub build really carries: an escaped blank in a selector's value, and string
    # escapes -- including an escaped quote that does NOT end the string it is in
    "escaped-ident": "[data-badge=INVALID\\ INPUT]{color:red}",
    "string-escapes": 'p:before{content:"\\b7 \\"url(https://third-party.invalid/x)\\""}',
}


def _css_family() -> dict[str, tuple[str, bool]]:
    """id -> (stylesheet text, whether it LOADS a resource)."""
    family = {f"css-load:{construct}:{url_id}": (template.format(u=url), True)
              for construct, template in _CSS_LOADS.items()
              for url_id, url in _SHELL_LOAD_URLS.items()}
    family.update({f"css-inert:{name}": (text, False) for name, text in _CSS_INERT.items()})
    hub = app_mod._REPO_ATLAS_SCOPE_DIST
    for path in sorted((hub / "assets").glob("*.css")) if (hub / "index.html").is_file() else []:
        family[f"css-inert:hub-{path.stem.split('-')[0]}"] = (path.read_text(encoding="utf-8"), False)
    return family


#: The fixture stylesheet the template shell links (write_scope_dist).
_LINKED_CSS = "assets/index-789.css"


def test_every_stylesheet_that_can_name_a_resource_is_refused(tmp_path):
    """RQF-V1-3 as a class: a build serves ready only when EVERY text/css member -- the one the
    shell links and any other -- is on the CSS accept-list; each loading stylesheet is refused with
    its reason, and every inert one (the hub build's own stylesheets included) is served."""
    template = write_scope_dist(tmp_path / "template")
    assert app_mod._scope_markup_refusal(_scope_members(template)) is None
    family = _css_family()
    assert len(family) >= 100, len(family)
    wrong = []
    for case_id, (text, loads) in family.items():
        for member in (_LINKED_CSS, "assets/other-unlinked.css"):
            refused = app_mod._scope_markup_refused(
                _scope_members({**template, member: text.encode("utf-8")}))
            if refused is not loads:
                wrong.append((case_id, member, "refused" if refused else "served ready"))
    assert not wrong, f"{len(wrong)} stylesheet(s) judged wrongly: {wrong[:12]}"
    for case_id, (text, loads) in family.items():
        refusal = app_mod._scope_css_refusal(text.encode("utf-8"))
        assert (refusal is not None) is loads, (case_id, refusal)
        assert refusal is None or refusal.startswith(app_mod._SCOPE_REFUSED_CSS), refusal
    assert any(case_id.startswith("css-inert:hub-") for case_id in family) or not (
        app_mod._REPO_ATLAS_SCOPE_DIST / "index.html").is_file()
    # a stylesheet that is not UTF-8 (a UTF-16 BOM decides the browser's reading) is not read
    assert app_mod._scope_css_refusal("\ufeffbody{}".encode("utf-16")) is not None
    # the in-memory verdict IS the index's, on a stride plus the verifier's @import
    sample = sorted(family)[::11] + ["css-load:import-url:third-party"]
    for number, case_id in enumerate(sample):
        dist = tmp_path / f"built-{number}"
        write_scope_dist(dist)
        (dist / _LINKED_CSS).write_bytes(family[case_id][0].encode("utf-8"))
        expected = "invalid_build" if family[case_id][1] else "ready"
        assert app_mod._scope_file_index(dist)[0] == expected, case_id


def test_a_scope_shell_is_ready_only_in_the_constructs_the_reader_accepts(tmp_path):
    """QF-V2-3 as a class: every generated shell that loads a URL through any construct -- other
    than a startup-indexed /scope asset through a <script type=module src> or <link> the list
    admits -- is refused, and its refusal names the construct; every inert construct is served."""
    template = write_scope_dist(tmp_path / "template")
    assert not app_mod._scope_markup_refused(_scope_members(template))
    family = _shell_family()
    assert len(family) >= 200, len(family)
    wrong = []
    for case_id, (fragment, loads) in family.items():
        refused = app_mod._scope_markup_refused(
            _scope_members({**template, "index.html": _shell_with(fragment, template)}))
        if refused is not loads:
            wrong.append((case_id, "refused" if refused else "served ready"))
    assert not wrong, f"{len(wrong)} shell construct(s) judged wrongly: {wrong[:12]}"
    for case_id, (fragment, loads) in family.items():
        refusal = app_mod._scope_shell_refusal(
            _scope_members({**template, "index.html": _shell_with(fragment, template)}))
        assert (refusal is not None) is loads, (case_id, refusal)
    # the in-memory verdict IS the index's, on a stride plus the constructs the verifier measured
    sample = sorted(family)[::17] + ["load:table-background:third-party",
                                     "load:svg-image-xlink-href:third-party", "load:style-url:third-party"]
    for number, case_id in enumerate(sample):
        dist = tmp_path / f"built-{number}"
        files = write_scope_dist(dist)
        (dist / "index.html").write_bytes(_shell_with(family[case_id][0], files))
        expected = "invalid_build" if family[case_id][1] else "ready"
        assert app_mod._scope_file_index(dist)[0] == expected, case_id


def _shell_moving_into_a_title(template: dict[str, bytes], construct: bytes) -> bytes:
    """The template shell with ``construct`` moved from its place into a <title> of its own."""
    shell = template["index.html"]
    assert shell.count(construct) == 1, construct
    return shell.replace(construct, b"", 1).replace(b"</head>", b"<title>" + construct + b"</title></head>", 1)


def test_a_shell_is_judged_on_the_browsers_reading_never_a_superset(tmp_path):
    """RQF-V2-1 as a class, without a browser: every POSITIVE shell requirement -- an icon in the
    head, a module entry, the runtime-source declaration -- counts elements, so the shell must be
    read exactly as the browser reads it. An element the browser reads as raw text or RCDATA must
    end at its own end tag with no `<` in it (plaintext never ends), and every requirement moved
    into one is refused; the generic markup reader (a superset, used for what must be absent) still
    reads the moved element, which is exactly the reading the shell may no longer be judged on."""
    template = write_scope_dist(tmp_path / "template")
    assert app_mod._scope_shell_refusal(_scope_members(template)) is None
    constructs = {
        "icon": _SHELL_ICON.encode("utf-8"),
        "module-entry": b'<script type="module" crossorigin src="/scope/assets/index-abc123.js"></script>',
        "runtime-source": (b'<meta name="atlas-scope-snapshot-source" '
                           b'content="assesshub-api-runtime">'),
    }
    for name, construct in constructs.items():
        shell = _shell_moving_into_a_title(template, construct)
        generic = app_mod._scope_document_reading(shell, "text/html")
        assert generic is not None and len(generic) == len(app_mod._scope_document_reading(
            template["index.html"], "text/html")) + 1, name  # the superset reads the moved element
        assert app_mod._scope_shell_reading(shell) is None, name
        refusal = app_mod._scope_shell_refusal(_scope_members({**template, "index.html": shell}))
        assert refusal is not None and "raw text" in refusal, (name, refusal)
    # an element the browser reads as raw text, closed with nothing but text in it, is read exactly
    titled = template["index.html"].replace(b"<title>Atlas Scope</title>",
                                            b"<title>Atlas Scope &amp; x > y</title>", 1)
    assert app_mod._scope_shell_refusal(_scope_members({**template, "index.html": titled})) is None
    # PLAINTEXT never ends in a browser, whatever end tag the reader would read
    for element in app_mod._SCOPE_HTML_RAW_TEXT_ELEMENTS:
        wrapped = template["index.html"].replace(
            b"</head>", f"<{element}>x</{element}></head>".encode("ascii"), 1)
        reading = app_mod._scope_shell_reading(wrapped)
        if element == "plaintext":
            assert reading is None
        else:
            assert reading is not None, element
    assert set(_RAW_TEXT_ELEMENTS) == set(app_mod._SCOPE_HTML_RAW_TEXT_ELEMENTS)


def test_the_shell_reads_token_lists_and_names_as_the_browser_does():
    """RQF-V2-1, attribute half: a `rel`, a script `type` and a meta `name` are read with the
    browser's own rules -- split on ASCII whitespace only, compared ASCII case-insensitively -- not
    Python's Unicode-wide str.split()/casefold(), which read an icon (or a stylesheet, via the long
    s U+017F that casefolds to `s`) where the browser reads none."""
    assert app_mod._scope_html_token_list(" ICON\tStyleSheet\n") == ["icon", "stylesheet"]
    for blank in _NON_ASCII_BLANKS.values():
        assert app_mod._scope_html_token_list(f"icon{blank}") == [f"icon{blank}"], repr(blank)
    assert app_mod._scope_html_ascii_lower("ſtylesheet") == "ſtylesheet"
    assert app_mod._scope_html_ascii_lower("MODULE") == "module"


def test_the_shell_may_carry_only_the_inline_script_the_reader_pins(tmp_path):
    """The one inline classic script (the theme boot) is admitted by its exact text: any other
    inline script -- or the same one with anything added -- can load a URL the reader cannot see."""
    template = write_scope_dist(tmp_path / "template")
    shell = template["index.html"]
    assert f"<script>{_THEME_BOOT}</script>".encode("utf-8") in shell
    assert not app_mod._scope_markup_refused(_scope_members(template))
    for variant in (_THEME_BOOT + ";fetch('/outside-scope/x')", _THEME_BOOT.replace("atlas-scope", "x"),
                    " " + _THEME_BOOT, _THEME_BOOT + "<!-- -->"):
        doctored = shell.replace(f"<script>{_THEME_BOOT}</script>".encode("utf-8"),
                                 f"<script>{variant}</script>".encode("utf-8"), 1)
        assert doctored != shell
        assert app_mod._scope_markup_refused(_scope_members({**template, "index.html": doctored})), variant
    for attributes in ('type="module"', 'type="text/javascript"', 'id="boot"', "async"):
        doctored = shell.replace(b"<script>", f"<script {attributes}>".encode("utf-8"), 1)
        assert app_mod._scope_markup_refused(_scope_members({**template, "index.html": doctored})), \
            attributes


def test_the_hub_shells_inline_script_is_the_one_the_reader_pins():
    """Runs on every leg, without a build: the source shell's inline script (which Vite copies
    verbatim into the hub shell) is exactly the one the reader admits, so an edit to it fails here
    with this message, not only as an invalid_build once built. Change both together."""
    scripts = _source_shell_inline_scripts()
    assert scripts == [_THEME_BOOT]
    digest = hashlib.sha256(_THEME_BOOT.encode("utf-8")).hexdigest()
    assert app_mod._SCOPE_SHELL_INLINE_SCRIPTS == frozenset({digest}), (
        "atlas-scope/index.html's inline script changed: set app._SCOPE_SHELL_INLINE_SCRIPTS to "
        f"{{{digest!r}}} after reviewing that it loads nothing")


@pytest.mark.parametrize("declaration", sorted(_REFERRER_DECLARATIONS))
def test_the_markup_reader_refuses_every_referrer_declaration_form_in_any_document(tmp_path,
                                                                                 declaration):
    """Every declaration form the shell is refused for is refused by the markup reader itself
    (app._scope_html_refusal, the gate the shell passes first) in ANY document, not only by the
    shell's accept-list: the accept-list's other refusals (an unindexed reference, an element it
    does not name) cannot stand in for the referrer rule, which must bite on its own. An HTML page
    other than the shell is refused before any of this is asked (RQF-V1-6)."""
    page = ("<!doctype html><html><head><title>x</title>" + _REFERRER_DECLARATIONS[declaration]
            + "</head><body>x</body></html>").encode("utf-8")
    assert app_mod._scope_html_refusal(page) in (app_mod._SCOPE_REFUSED_REFERRER,
                                                 app_mod._SCOPE_REFUSED_HTML), declaration
    # the control: the same page with the declaration removed is read, and declares nothing
    assert app_mod._scope_html_refusal(
        b"<!doctype html><html><head><title>x</title></head><body>x</body></html>") is None
    dist = tmp_path / "scope-dist"
    write_scope_dist(dist, extra_asset=("x.html", page))
    with _client(tmp_path, dist) as c:
        assert c.app.state.scope_status == "invalid_build", declaration
        assert c.get("/scope/assets/x.html").status_code == 503


_SVG_NS_URI = "http://www.w3.org/2000/svg"
_XHTML_NS_URI = "http://www.w3.org/1999/xhtml"
#: QF-V2-1 / P3F-V2-3. A browser renders every XML-typed member (SVG, XHTML, text/xml, any */xml or
#: *+xml type) as markup, HTML elements included, and no XML reader available here reads one as the
#: browser does: with an external DOCTYPE expat silently DROPS an undefined entity reference in an
#: attribute value, while Blink expands the whole HTML named-entity table for the XHTML and MathML
#: public identifiers -- `rel="noopener&Tab;noreferrer"` read as "noopenernoreferrer" by the reader
#: and built as "noopener noreferrer" by Chromium, served ready. The hub build ships no XML-typed
#: member at all (test_the_hub_build_ships_no_xml_document), so AssessHub reads none: every one is
#: refused, with that reason, whatever it holds. The family is GENERATED -- roots x prologs x
#: DOCTYPEs (none, bare, SYSTEM, every public identifier below, internal subsets with general and
#: parameter entities and attribute defaults) x bodies (undefined entities in attributes and text,
#: declared entities, character references, CDATA, PIs, comments, a live declaration, a benign
#: element) -- and it is loaded in real Chromium below, which shows what a reader would have to match.
_XML_PUBLIC_IDS = {
    "xhtml10-strict": ("-//W3C//DTD XHTML 1.0 Strict//EN",
                       "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd"),
    "xhtml10-transitional": ("-//W3C//DTD XHTML 1.0 Transitional//EN",
                             "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd"),
    "xhtml10-frameset": ("-//W3C//DTD XHTML 1.0 Frameset//EN",
                         "http://www.w3.org/TR/xhtml1/DTD/xhtml1-frameset.dtd"),
    "xhtml11": ("-//W3C//DTD XHTML 1.1//EN", "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd"),
    "xhtml-basic10": ("-//W3C//DTD XHTML Basic 1.0//EN",
                      "http://www.w3.org/TR/xhtml-basic/xhtml-basic10.dtd"),
    "xhtml-basic11": ("-//W3C//DTD XHTML Basic 1.1//EN",
                      "http://www.w3.org/TR/xhtml-basic/xhtml-basic11.dtd"),
    "xhtml11-mathml": ("-//W3C//DTD XHTML 1.1 plus MathML 2.0//EN",
                       "http://www.w3.org/Math/DTD/mathml2/xhtml-math11-f.dtd"),
    "mathml2": ("-//W3C//DTD MathML 2.0//EN", "http://www.w3.org/Math/DTD/mathml2/mathml2.dtd"),
    "svg11": ("-//W3C//DTD SVG 1.1//EN", "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd"),
}
_XML_DOCTYPES = {
    "none": "", "bare": "<!DOCTYPE {root}>", "system": '<!DOCTYPE {root} SYSTEM "about:legacy-compat">',
    **{f"public-{key}": f'<!DOCTYPE {{root}} PUBLIC "{public}" "{system}">'
       for key, (public, system) in _XML_PUBLIC_IDS.items()},
    "internal-entity": '<!DOCTYPE {root} [<!ENTITY r "noreferrer">]>',
    "internal-parameter-entity": "<!DOCTYPE {root} [<!ENTITY % p \"<!ENTITY r 'noreferrer'>\"> %p;]>",
    "internal-attribute-default": '<!DOCTYPE {root} [<!ATTLIST a rel CDATA "noreferrer">]>',
    "public-plus-internal": ('<!DOCTYPE {root} PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" '
                             '"http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd" '
                             '[<!ENTITY r "noreferrer">]>'),
}
_XML_BODIES = {
    "rel-tab": '<a rel="noopener&Tab;noreferrer" href="/api/referrer-probe">x</a>',
    "rel-newline": '<a rel="x&NewLine;noreferrer">x</a>',
    "name-nbsp": '<meta name="referrer&nbsp;" content="no-referrer"/>',
    "name-zero-width": '<meta name="&ZeroWidthSpace;referrer" content="no-referrer"/>',
    "text-entities": "<p>&nbsp;&Tab;&r;</p>",
    "declared-entity-rel": '<a rel="&r;">x</a>',
    "defaulted-rel": "<a>x</a>",
    "character-reference-rel": '<a rel="noopener&#9;noreferrer">x</a>',
    "predefined-references": '<b title="&amp;&lt;&gt;&quot;&apos;">x</b>',
    "cdata": '<p><![CDATA[<meta name="referrer" content="no-referrer"/>]]></p>',
    "comment": '<!-- <meta name="referrer" content="no-referrer"/> -->',
    "processing-instruction": "<?atlas probe?><b>x</b>",
    "meta": '<meta name="referrer" content="no-referrer"/>',
    "benign": '<b title="x">x</b>',
}
_XML_PROLOGS = {"none": "", "declaration": '<?xml version="1.0" encoding="UTF-8"?>',
                "stylesheet-pi": '<?xml-stylesheet type="text/css" href="data:text/css,"?>'}
_XML_ROOTS = {
    "xhtml": ("x.xhtml", "html", f'<html xmlns="{_XHTML_NS_URI}"><head><title>x</title></head>'
                                 "<body>{body}</body></html>"),
    "xml": ("x.xml", "html", f'<html xmlns="{_XHTML_NS_URI}"><head><title>x</title></head>'
                             "<body>{body}</body></html>"),
    "svg": ("x.svg", "svg", f'<svg xmlns="{_SVG_NS_URI}"><foreignObject width="10" height="10">'
                            f'<div xmlns="{_XHTML_NS_URI}">{{body}}</div></foreignObject></svg>'),
}
#: prologs are crossed with this subset of DOCTYPEs only (the full cross adds nothing a prolog changes)
_XML_PROLOG_DOCTYPES = ("none", "public-xhtml10-strict", "internal-entity")


def _xml_family() -> dict[str, tuple[str, str]]:
    """id -> (member name, document): the generated XML family, ids `root:prolog:doctype:body`."""
    family = {}
    for root_id, (name, root, template) in _XML_ROOTS.items():
        for doctype_id, doctype in _XML_DOCTYPES.items():
            for prolog_id, prolog in _XML_PROLOGS.items():
                if prolog_id != "none" and (root_id != "xhtml" or doctype_id not in _XML_PROLOG_DOCTYPES):
                    continue
                for body_id, body in _XML_BODIES.items():
                    family[f"{root_id}:{prolog_id}:{doctype_id}:{body_id}"] = (
                        name, prolog + doctype.format(root=root) + template.format(body=body))
    return family


#: The verifier's measured bypass (QF-V2-1): served ready before this repair.
_XML_VERIFIER_CASE = "xhtml:none:public-xhtml10-strict:rel-tab"


def _scope_members(files: dict[str, bytes]) -> dict:
    return {relative: app_mod._FrontendFile(content, app_mod._frontend_media_type(relative), "")
            for relative, content in files.items()}


def test_every_xml_document_is_refused_with_its_reason_whatever_it_holds(tmp_path):
    """QF-V2-1, closed by construction: no XML-typed member is read, so none can be read
    differently from the browser. Every generated member -- including the benign ones and the old
    hand-kept 'controls' -- makes the build invalid, and its refusal says why."""
    family = _xml_family()
    assert len(family) >= 600 and _XML_VERIFIER_CASE in family, len(family)
    template = write_scope_dist(tmp_path / "template")
    assert not app_mod._scope_markup_refused(_scope_members(template))  # the control is served
    served = []
    for case_id, (name, page) in family.items():
        media_type = app_mod._frontend_media_type(name)
        assert app_mod._scope_markup_kind(media_type) == "xml", (name, media_type)
        if not app_mod._scope_markup_refused(_scope_members({**template, f"assets/{name}":
                                                             page.encode("utf-8")})):
            served.append(case_id)
    assert not served, f"{len(served)} XML member(s) served ready: {served[:12]}"
    for case_id, (name, page) in family.items():
        media_type = app_mod._frontend_media_type(name)
        assert app_mod._scope_document_refusal(page.encode("utf-8"), media_type) \
            == app_mod._SCOPE_REFUSED_XML, case_id
        assert app_mod._scope_document_reading(page.encode("utf-8"), media_type) is None, case_id
    # the in-memory verdict IS the index's: a stride of the family (and the verifier's case) is
    # written out as a real build and judged by the whole _scope_file_index, each against its control
    sample = sorted(family)[::53] + [_XML_VERIFIER_CASE]
    for number, case_id in enumerate(sample):
        name, page = family[case_id]
        dist = tmp_path / f"built-{number}"
        write_scope_dist(dist, extra_asset=(name, page.encode("utf-8")))
        assert app_mod._scope_file_index(dist)[0] == "invalid_build", case_id
        (dist / "assets" / name).unlink()
        assert app_mod._scope_file_index(dist)[0] == "ready", case_id


def test_the_hub_build_ships_no_xml_document():
    """The evidence behind refusing every XML-typed member (QF-V2-1): the hub build's source
    carries no static asset a build would emit as one -- nothing is imported by an XML-typed
    suffix and there is no public/ directory -- and, when the hub build is present, none of its
    members is XML-typed. A future build that needs one must bring a reader that reads it as the
    browser does, not reopen this."""
    package = _ATLAS_SCOPE_ROOT
    xml_suffixes = _xml_typed_suffixes()
    assert {".svg", ".xhtml", ".xml"} <= xml_suffixes, sorted(xml_suffixes)
    assert not (package / "public").exists()
    imports = _xml_typed_asset_references(package, xml_suffixes)
    assert not imports, imports
    hub = app_mod._REPO_ATLAS_SCOPE_DIST
    if (hub / "index.html").is_file():
        shipped = [p.relative_to(hub).as_posix() for p in hub.rglob("*") if p.is_file()
                   and app_mod._scope_markup_kind(app_mod._frontend_media_type(p.name)) == "xml"]
        assert not shipped, shipped


def _xml_typed_asset_references(package: Path, xml_suffixes: set[str]) -> list[tuple[str, str]]:
    """Every quoted string in the package's source and HTML entries that a build could emit as an XML-typed
    asset. A build emits an asset only for a reference that reaches a file, so a string counts when it is
    path-shaped (a separator or a leading dot: a relative, aliased or dependency path) or names a file beside
    the referencing one; a bare identifier that merely ends in such a suffix is not one. The suffix set is the
    host's served registry, which differs between hosts: the hosted Windows image types `.config` as XML, so
    the command id "select.config" in commands.ts once read as an asset there and nowhere else."""
    sources = [p for p in sorted((package / "src").rglob("*")) if p.is_file()
               and not _SCOPE_TEST_FILE.search(p.name) and p.suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".css")]
    found = []
    for path in sources + sorted(package.glob("*.html")):
        for spec in re.findall(r"""["'`]([^"'`\n]+)["'`]""", path.read_text(encoding="utf-8")):
            target = spec.split("?", 1)[0].split("#", 1)[0]
            if (PurePosixPath(target).suffix.casefold() in xml_suffixes
                    and not spec.startswith(("http:", "https:", "data:"))
                    and ("/" in target or "\\" in target or target.startswith(".")
                         or (path.parent / target).is_file())):
                found.append((path.name, spec))
    return found


def test_xml_typed_asset_scan_tells_a_reference_from_an_identifier(tmp_path):
    """Pins the scan in both directions on every host, by forcing `.config` into the suffix set as the hosted
    Windows registry does: an identifier is not a reference, and each way a build reaches a file still is."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "beside.svg").write_text("<svg/>", encoding="utf-8")
    (src / "commands.ts").write_text('export const ids = ["select.config", "inspect.svg"];\n', encoding="utf-8")
    (src / "assets.ts").write_text(
        'import a from "./icon.svg";\nimport b from "pkg/sprite.svg?url";\n'
        'export const c = new URL("beside.svg", import.meta.url);\nexport const d = "../up.config";\n',
        encoding="utf-8")
    (src / "assets.test.ts").write_text('import t from "./only-in-a-test.svg";\n', encoding="utf-8")
    (tmp_path / "index.html").write_text('<link rel="icon" href="/favicon.svg">\n', encoding="utf-8")
    found = _xml_typed_asset_references(tmp_path, {".svg", ".config"})
    assert sorted(found) == sorted([
        ("assets.ts", "./icon.svg"), ("assets.ts", "pkg/sprite.svg?url"), ("assets.ts", "beside.svg"),
        ("assets.ts", "../up.config"), ("index.html", "/favicon.svg")]), found


def _xml_typed_suffixes() -> set[str]:
    """Every suffix the served registry types as an XML document (derived, not listed)."""
    import mimetypes

    mimetypes.init()
    return {suffix.casefold() for suffix in set(mimetypes.types_map) | set(app_mod._FRONTEND_PINNED_MEDIA_TYPES)
            if app_mod._scope_markup_kind(app_mod._frontend_media_type("x" + suffix)) == "xml"}


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


#: The markup oracle (real Chromium, "the browser is the oracle" below) has its OWN switch, because
#: a leg can hold node + atlas-scope's `npm ci` (the real-toolchain pins) without a browser. `1`: the
#: oracle MUST run (a missing browser fails). `0`: this leg opts out EXPLICITLY (it skips, visibly).
#: Unset: it follows the real-toolchain switch — so a leg that sets
#: ATLAS_SCOPE_REQUIRE_REAL_TOOLCHAIN=1 and installs no Chromium fails until it decides either way
#: (QF-R1-1; the workflows are held to that below, test_every_ci_leg_running_these_pins_...).
_REQUIRE_MARKUP_ORACLE_ENV = "ATLAS_SCOPE_REQUIRE_MARKUP_ORACLE"


def _oracle_prerequisite_absent(reason: str):
    switch = os.environ.get(_REQUIRE_MARKUP_ORACLE_ENV)
    if switch not in (None, "", "0", "1"):
        pytest.fail(f"{_REQUIRE_MARKUP_ORACLE_ENV}={switch!r} is neither 0 nor 1", pytrace=False)
    if switch == "1":
        pytest.fail(f"{_REQUIRE_MARKUP_ORACLE_ENV}=1 but {reason}", pytrace=False)
    if switch == "0":
        pytest.skip(f"{reason} (this leg opts out: {_REQUIRE_MARKUP_ORACLE_ENV}=0)")
    _prerequisite_absent(f"{reason}; a leg without the oracle's browser sets "
                         f"{_REQUIRE_MARKUP_ORACLE_ENV}=0 explicitly")


def test_the_markup_oracle_has_its_own_switch_and_absence_never_passes_silently(monkeypatch):
    cases = [(None, None, "skip"), (None, "1", "fail"), ("0", "1", "skip"), ("0", None, "skip"),
             ("1", None, "fail"), ("1", "0", "fail"), ("yes", None, "fail"), ("", "1", "fail")]
    for oracle, toolchain, expected in cases:
        for name, value in ((_REQUIRE_MARKUP_ORACLE_ENV, oracle),
                            (_REQUIRE_REAL_TOOLCHAIN_ENV, toolchain)):
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
        outcome = pytest.skip.Exception if expected == "skip" else pytest.fail.Exception
        with pytest.raises(outcome):
            _oracle_prerequisite_absent("absent")


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
        f'<title>Atlas Scope</title>{_SHELL_ICON}<script type="module" src="/main.js"></script></head>'
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


def test_the_source_shell_the_hub_build_is_made_from_is_markup_the_reader_reads():
    """Runs without a build, on every leg: atlas-scope/index.html (the shell Vite turns into the hub
    shell by adding its asset tags) stays inside the markup the /scope reader accepts, so an edit
    there that a browser would read differently from AssessHub fails here, not only once built."""
    source = (_ATLAS_SCOPE_ROOT / "index.html").read_bytes()
    reading = app_mod._scope_document_reading(source, app_mod._frontend_media_type("index.html"))
    assert reading is not None
    assert not app_mod._scope_reading_declares_referrer_policy(reading)
    assert {"html", "head", "body", "script", "meta"} <= {element.name for element in reading}


_SCOPE_PINS = "webapp/tests/test_scope_mount.py"
# The ONE reader of a step's pytest invocations, shared with tests/test_ssot_registry.py (W5b, S-CI-V2).
from pytest_invocation_reader import pytest_invocations as _pytest_invocations  # noqa: E402


def _collects_the_scope_pins(paths: list[str]) -> bool:
    return any(path == "." or _SCOPE_PINS == path.rstrip("/")
               or _SCOPE_PINS.startswith(path.rstrip("/") + "/") for path in paths)


def _workflow_legs_running_the_scope_pins() -> list[dict]:
    """Every CI step, in every workflow, whose pytest collects these pins -- read from the workflows
    (PyYAML ships with netmiko, a base dependency), with its effective env and what ran before it."""
    import yaml

    legs = []
    for workflow in sorted((_REPO / ".github" / "workflows").glob("*.yml")):
        document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        for job_id, job in (document.get("jobs") or {}).items():
            default_wd = (((job.get("defaults") or {}).get("run") or {}).get("working-directory")
                          or ".")
            earlier = []
            for step in job.get("steps") or []:
                run = str(step.get("run") or "")
                wd = os.path.normpath(step.get("working-directory") or default_wd).replace("\\", "/")
                if any(_collects_the_scope_pins(paths) for paths in _pytest_invocations(run, wd)):
                    env = {name: str(value) for scope in (document, job, step)
                           for name, value in (scope.get("env") or {}).items()}
                    legs.append({"leg": f"{workflow.name}:{job_id}", "env": env,
                                 "earlier": list(earlier)})
                earlier.append((wd, run))
    return legs


def _ran_in_atlas_scope(earlier: list, pattern: str) -> bool:
    return any(re.search(pattern, run) and (wd == "atlas-scope" or re.search(
        r"(?:\bcd|Set-Location)\s+['\"]?atlas-scope\b", run)) for wd, run in earlier)


def test_every_ci_leg_running_these_pins_installs_or_explicitly_declines_what_they_require():
    """QF-R1-1 / P3F-V2-2, derived from the workflows: every CI step whose pytest collects these pins
    -- `pytest webapp/tests/...` or a bare `pytest` over pytest.ini's testpaths -- is held to what it
    claims. A leg that requires the real toolchain must `npm ci` in atlas-scope first AND decide the
    markup oracle explicitly (it needs a browser the toolchain does not bring); a leg that requires
    the oracle must install atlas-scope's Playwright Chromium first; a leg that builds the hub build
    must build it first and require it."""
    legs = _workflow_legs_running_the_scope_pins()
    problems = []
    for leg in legs:
        env, earlier, name = leg["env"], leg["earlier"], leg["leg"]
        if env.get(_REQUIRE_REAL_TOOLCHAIN_ENV) == "1":
            if not _ran_in_atlas_scope(earlier, r"\bnpm ci\b"):
                problems.append((name, "requires the real toolchain but runs no npm ci in atlas-scope"))
            if env.get(_REQUIRE_MARKUP_ORACLE_ENV) not in ("0", "1"):
                problems.append((name, f"requires the real toolchain but does not set "
                                       f"{_REQUIRE_MARKUP_ORACLE_ENV} to 0 or 1"))
        if env.get(_REQUIRE_MARKUP_ORACLE_ENV) == "1" and not _ran_in_atlas_scope(
                earlier, r"\bplaywright install\b[^\n]*\bchromium\b"):
            problems.append((name, "requires the markup oracle but installs no atlas-scope Chromium"))
        builds_hub = _ran_in_atlas_scope(earlier, r"\bnpm run build:hub\b")
        if builds_hub and env.get(_REQUIRE_HUB_BUILD_ENV) != "1":
            problems.append((name, "builds the hub build but does not require it"))
        if env.get(_REQUIRE_HUB_BUILD_ENV) == "1" and not builds_hub:
            problems.append((name, "requires the hub build but does not build it first"))
    assert not problems, problems
    # non-vacuity: a bare `pytest`, `pytest webapp/tests` and the file itself are all recognised, and
    # the two legs that own the oracle really require it
    by_leg = {leg["leg"]: leg["env"] for leg in legs}
    assert by_leg.get("ci.yml:test", {}).get(_REQUIRE_REAL_TOOLCHAIN_ENV) == "1", sorted(by_leg)
    for owner in ("webapp-ci.yml:backend", "atlas-scope-ci.yml:atlas-scope"):
        assert by_leg.get(owner, {}).get(_REQUIRE_MARKUP_ORACLE_ENV) == "1", (owner, sorted(by_leg))
        assert by_leg[owner].get(_REQUIRE_HUB_BUILD_ENV) == "1", owner
    assert any(not env.get(_REQUIRE_REAL_TOOLCHAIN_ENV) for env in by_leg.values()), sorted(by_leg)


def test_the_ci_leg_reader_recognises_every_way_a_step_collects_these_pins():
    for run, wd, expected in [
            ("python -m pytest", ".", True), ("python -m pytest -q -p no:cacheprovider", ".", True),
            ("python -m pytest webapp/tests -q", ".", True),
            ("python -m pytest webapp/tests/test_scope_mount.py -q", ".", True),
            ("python -m pytest webapp/tests/test_scope_mount.py::test_x", ".", True),
            ("python -m pytest -k scope webapp", ".", True),
            ('& "$env:RUNNER_TEMP\\ci-venv\\Scripts\\python.exe" -m pytest', ".", True),
            ("pytest -q", ".", True), ("python -m pytest tests/test_scope_mount.py", "webapp", True),
            ("python -m pytest master-reference/tests -q", ".", False),
            ("python -m pytest tests -p webapp", ".", False),
            ("python -m pip install pytest-xdist", ".", False),
            # QF-V2-4: a line continuation carries the invocation onto the next line -- bash's
            # backslash and PowerShell's backtick, each ONLY as the last character before the line
            # feed (RQF-V1-5, measured: bash runs `a \<blank><LF>b` as two commands, and PowerShell
            # 5.1 runs a backtick before CR LF as two); bash deletes `\<LF>`, PowerShell reads a blank
            ("python -m pytest \\\n  webapp/tests/test_scope_mount.py -q", ".", True),
            ("python -m pytest master-reference/tests \\\n  webapp/tests -q", ".", True),
            ("python -m pytest -q \\\n  -p no:cacheprovider \\\n  webapp/tests", ".", True),
            ('& "$env:RUNNER_TEMP\\ci-venv\\Scripts\\python.exe" -m pytest `\n  webapp/tests', ".", True),
            ("python -m pytest \\\n  master-reference/tests -q", ".", False),
            ("python -m pytest `\n  tests/test_readme_field.py", ".", False),
            # NOT continuations: the next line is a command of its own, which collects nothing
            ("python -m pytest master-reference/tests -q \\  \n  webapp/tests", ".", False),
            ("python -m pytest master-reference/tests -q \\\r\n  webapp/tests", ".", False),
            ("python -m pytest master-reference/tests -q ` \n  webapp/tests", ".", False),
            ("python -m pytest master-reference/tests -q `\r\n  webapp/tests", ".", False),
            # bash deletes the backslash-newline pair outright, so `webapp\<LF>/tests` is ONE word
            ("python -m pytest webapp\\\n/tests -q", ".", True),
            ("python -m pytest master-reference\\\n/tests -q", ".", False),
            # W5b (S-CI-V2): a coverage option's value is not a collected path -- the ONE shared
            # reader (tests/pytest_invocation_reader.py) knows the --cov* options the CI legs pass
            ("python -m pytest --cov webapp master-reference/tests", ".", False),
            ("python -m pytest --cov-config webapp/.coveragerc master-reference/tests", ".", False),
            ("python -m pytest --cov-report term --cov webapp webapp/tests", ".", True)]:
        found = any(_collects_the_scope_pins(p) for p in _pytest_invocations(run, wd))
        assert found is expected, (run, wd)


_SCOPE_DIST_DEFAULT_SENTINEL = app_mod._SCOPE_DIST_DEFAULT
#: Set to 1 on a leg that runs atlas-scope `npm run build:hub` before this suite (the hub build is
#: untracked build output, so only such a leg can hold this pin to account).
_REQUIRE_HUB_BUILD_ENV = "ATLAS_SCOPE_REQUIRE_HUB_BUILD"


# -- the browser is the oracle (P3F-V2-1 / V2-3) ------------------------------------------------------
# A /scope document is judged by the reading a BROWSER makes of it, never by a tokenizer that differs
# from the browser's. The proof is differential and real: every document of a GENERATED family —
# abrupt and bang-closed comments, markup declarations, CDATA, raw-text end tags in every spelling for
# every element parse5 knows (the WHATWG tokenizer-switching ones in full), script escapes, foreign
# content and nesting, attribute spellings, and XML documents — is judged by AssessHub's own index
# (`_scope_file_index`), then loaded in real Chromium with the exact headers AssessHub serves it with.
# A document served 'ready' must carry NO referrer-policy declaration in the DOM Chromium built, must
# send its full /scope Referer on a same-origin POST, and every element attribute Chromium holds must
# be one the reader read. Needs node + atlas-scope's Playwright + its Chromium: where
# ATLAS_SCOPE_REQUIRE_MARKUP_ORACLE=1 (webapp-ci's backend leg, atlas-scope-ci) their absence FAILS,
# never skips; a leg without a browser declines it explicitly with =0 (_oracle_prerequisite_absent).
# Every refusal clause of the reader has a member of this family (or a unit pin above) that goes red
# without it, or is recorded as safety-equivalent: removing it changes no reading a browser makes.

_ORACLE_ORIGIN = "http://localhost:8765"
_ORACLE_HARNESS = r"""
const { createRequire } = require('node:module');
const fs = require('node:fs');
const path = require('node:path');
const [, , atlasScopeRoot, mode, inPath, outPath] = process.argv;
const load = createRequire(path.join(atlasScopeRoot, 'package.json'));
(async () => {
  if (mode === 'tags') {
    const { html } = load('parse5');
    fs.writeFileSync(outPath, JSON.stringify(Object.values(html.TAG_NAMES)));
    return;
  }
  const { chromium } = load('playwright');
  if (mode === 'requests') {
    // QF-V2-3 / RQF-V1-3 / RQF-V1-4: every request a shell makes, as the browser issues it. Each lane
    // runs FULL Chromium (channel 'chromium': the new headless mode, which -- like a headed browser
    // and unlike the headless shell -- requests the default /favicon.ico) behind its OWN recording
    // proxy, one case at a time, each case on an ORIGIN OF ITS OWN (the browser remembers a
    // favicon it failed to fetch per origin, and a request to an origin names its case, however
    // late it arrives). The page's own requests (every frame's) are the context's 'request'
    // events; the proxy also sees what the BROWSER requests for the page, which no page event
    // reports (the default favicon, a preconnect's tunnel) -- and the browser's own background
    // traffic, which the test tells apart by host.
    const http = require('node:http');
    const { assets, cases } = JSON.parse(fs.readFileSync(inPath, 'utf8'));
    const results = {};
    const worker = async (slice) => {
      let current = null;
      let last = null;
      const byHost = new Map();
      const owner = (host) => byHost.get(host) || current || last;
      const record = (host, url) => { const target = owner(host); if (target) target.proxy.push(url); };
      const server = http.createServer((req, res) => {
        let url = null;
        try { url = new URL(req.url); } catch (error) { url = null; }
        record(url ? url.host : '', url ? url.href : String(req.url));
        const plain = { 'content-type': 'text/plain', 'cache-control': 'no-store' };
        const reply = (status, headers, body) => {
          res.writeHead(status, { ...headers, 'cache-control': 'no-store' });
          res.end(body);
        };
        if (!current || !url || url.origin !== current.origin) return reply(404, plain, '');
        if (url.pathname === current.path && !current.served) {
          current.served = true;
          return reply(200, current.headers, Buffer.from(current.body, 'base64'));
        }
        const asset = current.assets ? ((current.extra || {})[url.pathname] || assets[url.pathname])
          : undefined;
        if (asset) return reply(200, asset.headers, Buffer.from(asset.body, 'base64'));
        return reply(404, plain, '');
      });
      server.on('connect', (req, socket) => {
        record(req.url, 'https://' + req.url + '/');
        socket.destroy();
      });
      await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
      let browser;
      try {
        browser = await chromium.launch({ channel: 'chromium', proxy: {
          server: 'http://127.0.0.1:' + server.address().port, bypass: '<-loopback>' } });
      } catch (error) {
        server.close();
        throw new Error('ORACLE-NO-BROWSER ' + String(error).split('\n')[0]);
      }
      try {
        for (const c of slice) {
          const state = { ...c, served: false, page: [], proxy: [] };
          byHost.set(new URL(c.origin).host, state);
          const context = await browser.newContext();
          context.on('request', (request) => { state.page.push(request.url()); });
          const page = await context.newPage();
          current = state;
          let rendered = true;
          try { await page.goto(c.origin + c.path, { waitUntil: 'load', timeout: 15000 }); }
          catch (error) { rendered = false; }
          await page.waitForTimeout(1200);
          // RQF-V2-1: the elements the browser BUILT, to hold the shell's own reading to
          let dom = null;
          try {
            dom = await page.evaluate(() => Array.from(document.querySelectorAll('*'), (e) => [
              e.localName, Array.from(e.attributes, (a) => [a.name, a.value])]));
          } catch (error) { dom = null; }
          await context.close();
          last = state;
          current = null;
          await new Promise((resolve) => setTimeout(resolve, 150));
          results[c.id] = { rendered, page: state.page, proxy: state.proxy, dom };
        }
      } finally {
        await browser.close();
        server.close();
      }
    };
    const lanes = 5;
    await Promise.all(Array.from({ length: lanes }, (_, lane) =>
      worker(cases.filter((_c, index) => index % lanes === lane))));
    fs.writeFileSync(outPath, JSON.stringify(results));
    return;
  }
  let browser;
  try { browser = await chromium.launch(); }
  catch (error) { console.log('ORACLE-NO-BROWSER ' + String(error).split('\n')[0]); process.exit(3); }
  try {
    const cases = JSON.parse(fs.readFileSync(inPath, 'utf8'));
    const results = {};
    // Independent contexts (own route, own current document) read the family in parallel.
    const worker = async (slice) => {
      const context = await browser.newContext();
      const page = await context.newPage();
      let current = null;
      let referer;
      await context.route('**/*', (route) => {
        const request = route.request();
        const url = new URL(request.url());
        if (url.pathname === '/api/referrer-probe') {
          referer = request.headers()['referer'] ?? null;
          return route.fulfill({ status: 204 });
        }
        if (current && url.pathname === current.path && request.isNavigationRequest()
            && request.frame() === page.mainFrame()) {
          return route.fulfill({ status: 200, headers: current.headers,
                                 body: Buffer.from(current.body, 'base64') });
        }
        return route.fulfill({ status: 404, headers: { 'content-type': 'text/plain' }, body: '' });
      });
      for (const c of slice) {
        current = c;
        referer = undefined;
        let rendered = true;
        let dom = null;
        const started = Date.now();
        try { await page.goto(%ORIGIN% + c.path, { waitUntil: 'domcontentloaded', timeout: 10000 }); }
        catch (error) { rendered = false; }
        if (rendered) {
          try {
            dom = await page.evaluate(() => Array.from(document.querySelectorAll('*'), (e) => [
              e.localName, Array.from(e.attributes, (a) => [a.name, a.localName, a.value, a.namespaceURI])]));
            await page.evaluate(() => fetch('/api/referrer-probe', { method: 'POST', body: 'x' })
              .then(() => 0, () => 0));
          } catch (error) { rendered = false; }
        }
        results[c.id] = { rendered, dom, referer: referer === undefined ? '<not requested>' : referer,
                          ms: Date.now() - started };
      }
      await context.close();
    };
    const lanes = 6;
    await Promise.all(Array.from({ length: lanes }, (_, lane) =>
      worker(cases.filter((_c, index) => index % lanes === lane))));
    fs.writeFileSync(outPath, JSON.stringify(results));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  if (String(error.message || error).startsWith('ORACLE-NO-BROWSER')) {
    console.log(String(error.message || error)); process.exit(3);
  }
  console.error(error); process.exit(1);
});
""".replace("%ORIGIN%", json.dumps(_ORACLE_ORIGIN))

_XMLNS_NS = "http://www.w3.org/2000/xmlns/"
_MEDIA_PROBE = "atlas-scope-markup-probe"
_ORACLE_META = '<meta name="referrer" content="no-referrer">'
#: What each wrapper hides or exposes: a policy meta, the noreferrer link type, a referrerpolicy —
#: and a benign element, so every wrapper also yields documents the reader ACCEPTS, whose reading
#: the containment test then holds to Chromium's.
_ORACLE_PAYLOADS = {"meta": _ORACLE_META, "a-rel": '<a rel="noreferrer">x</a>',
                    "i-referrerpolicy": '<i referrerpolicy="no-referrer">x</i>',
                    "benign": '<b title="referrer">x</b>',
                    # unquoted, so no quote of the payload's own can close a wrapper's quoted value
                    "meta-unquoted": "<meta name=referrer content=no-referrer>"}
#: The elements whose content the WHATWG tree builder switches the tokenizer out of the data state
#: for; the family runs them with every raw-text end-tag spelling, and runs EVERY element name parse5
#: knows with the core spellings (so a tokenizer-switching element missing here is still exercised).
_RAW_TEXT_ELEMENTS = ("script", "style", "title", "textarea", "xmp", "iframe", "noembed", "noframes",
                      "noscript", "plaintext")
_COMMENT_WRAPPERS = [
    ("<!-->", "<!-- -->"), ("<!--->", "<!-- -->"), ("<!-->", "-->"), ("<!--->", "-->"),
    ("<!---->", ""), ("<!--x--!>", "<!-- -->"), ("<!--x--!>", "-->"),
    ("<!--x--!", "-->"), ("<!--x-- >", "-->"), ("<!--x--\n>", "-->"), ("<!-- a <!-- b -->", ""),
    ("<!--x<!-->", "-->"), ("<!--x<!--->", "-->"), ("<!--", "-->"), ("<!-- x --", "->"),
    ("<!-- x -", "-->"), ("<!-- </p> ", "-->"), ("<!-- <p> ", "-->"), ("<!--x-", "->"),
    ("<!-- x --!", "-->"), ("<!--", "--!>"), ("<!--", "<!-->"),
]
_DECLARATION_WRAPPERS = [
    ("<!x>", ""), ("<!>", ""), ("<?x>", ""), ("<?x ", "?>"), ("</ x>", ""), ("</>", ""), ("</1>", ""),
    ("<![CDATA[", "]]>"), ("<![CDATA[x]]>", ""), ("<!DOCTYPE x>", ""), ("<!doctype html>", ""),
    ("<!ELEMENT x>", ""), ("<! -- ", " -- >"), ("<!-", ">"), ("a < b ", ""), ("<1 ", ""), ("<", ""),
    ("&lt;", ""), ("<p title='", "'>"), ('<p title="', '">'), ("<p title=", ">"),
]
_RAW_TEXT_WRAPPERS = [
    ("<{t}>", "</{t}>"), ("<{t}></{t} x>", ""), ("<{t}></{t}/>", ""), ("<{t}></{t}\t>", ""),
    ("<{t}></{t}\n>", ""), ("<{t}></{t} >", ""), ("<{t}><!--</{t}>", "-->"),
    ('<{t}><a title="</{t}>', '">'), ("<{t}><a title='</{t}>", "'>"), ("<{t}>x</{t}\f>", ""),
    ("<{t}><!--", "--></{t}>"),
    ("<{t}>", ""), ("<{T}></{t} x>", ""), ("<{t}></{T} x>", ""), ("<{t}></{t}\r>", ""),
]
_EVERY_ELEMENT_WRAPPERS = [("<{t}>", "</{t}>"), ("<{t}></{t} x>", ""), ("<{t}><!--</{t}>", "-->"),
                           ("<{t}><a title='</{t}>", "'>")]
_SCRIPT_WRAPPERS = [
    ("<script><!--<script>", "</script></script>"), ("<script><!--<script></script>", "</script>"),
    ("<script><!--", "--></script>"), ("<script><!--</script>", "-->"), ("<script>/*", "*/</script>"),
    ("<script><!--<script>-->", "</script>"), ("<script><!--<script>--></script>", ""),
]
_NESTING_WRAPPERS = [
    ("<svg>", "</svg>"), ("<svg><style>", "</style></svg>"), ("<svg><![CDATA[", "]]></svg>"),
    ("<svg><title>", "</title></svg>"), ("<svg><desc>", "</desc></svg>"),
    ("<svg><foreignObject>", "</foreignObject></svg>"), ("<svg><script>", "</script></svg>"),
    ("<math>", "</math>"), ("<math><mi>", "</mi></math>"),
    ('<math><annotation-xml encoding="text/html">', "</annotation-xml></math>"),
    ("<math><![CDATA[", "]]></math>"), ("<template>", "</template>"),
    ('<template shadowrootmode="open">', "</template>"), ("<noscript>", "</noscript>"),
    ("<select>", "</select>"), ("<table>", "</table>"), ("<object>", "</object>"),
    ("<div><p>", "</p></div>"), ("<a><a>", ""), ("<frameset>", ""), ("<head>", ""), ("<body>", ""),
    ("<html>", ""), ("<svg><foreignObject><svg><style>", "</style></svg></foreignObject></svg>"),
    ("<textarea>", "</textarea>"), ("<title>", "</title>"), ("<plaintext>", ""),
]
#: The declaration itself, spelled every way the tokenizer reads (or does not read) as one.
_ATTRIBUTE_SPELLINGS = [
    '<meta name=referrer content=no-referrer>', "<meta name='referrer' content='no-referrer'>",
    '<META NAME="REFERRER" CONTENT="NO-REFERRER">', '<meta\nname="referrer"\ncontent="no-referrer">',
    '<meta\fname="referrer" content="no-referrer">', '<meta\rname="referrer" content="no-referrer">',
    '<meta/name="referrer"/content="no-referrer">', '<meta name="referrer"content="no-referrer">',
    '<meta name="&#114;eferrer" content="no-referrer">', '<meta name="refer&#x72;er" content="no-referrer">',
    '<meta name="referrer" name="x" content="no-referrer">',
    '<meta name="x" name="referrer" content="no-referrer">',
    '<meta name="referrer" content="no&#45;referrer">', '<meta name="referrer" content="no-referrer"/>',
    '<meta name = "referrer" content = "no-referrer">', '<meta\x0bname="referrer" content="no-referrer">',
    '<me\x00ta name="referrer" content="no-referrer">', '<meta name="referrer\x00" content="no-referrer">',
    '<meta name="referrer" content="no-referrer" x=">', '<meta name="ref&NewLine;errer" content="x">',
    '<meta name=" referrer " content="no-referrer">', '<meta name="referrer" content=no-referrer/>',
    '<meta name="referrer" content="no-referrer"<p>', '<a rel=noreferrer>x</a>',
    '<a rel="noopener&#32;noreferrer">x</a>', '<i REFERRERPOLICY="origin">x</i>',
    '<iframe srcdoc="x"></iframe>', '<meta name="description" content="referrer no-referrer">',
    '<p>referrer noreferrer referrerpolicy</p>', '<!-- <meta name="referrer" content="no-referrer"> -->',
    # QF-R1-2 per-clause: a declaration directly after another attribute (no whitespace between
    # them), a noreferrer token split on TAB or LF, and a `<` inside another attribute's value
    '<meta content="no-referrer"name="referrer">', '<a title="x"rel="noreferrer">x</a>',
    '<a rel="noopener\tnoreferrer">x</a>', '<a rel="noopener\nnoreferrer">x</a>',
    '<meta name="referrer" content="no-referrer" title="a<b">',
    # CR in a value: a browser normalises it to LF before tokenizing, and so must the reader's value
    '<b title="a\r\nb">x</b>', '<b title="a\rb">x</b>',
]


def _oracle_fragments(element_names: list[str]) -> dict[str, tuple[str, bool]]:
    """id -> (fragment, whether the SHELL is exercised too). Every family runs as an HTML asset; the
    per-element family (the largest) runs as an asset only — the shell reads markup with the same
    reader and only adds refusals of its own."""
    fragments: dict[str, tuple[str, bool]] = {}
    for name in _PARSER_DIFFERENTIAL_FORMS:
        fragments[f"named:{name}"] = (_REFERRER_DECLARATIONS[name], True)
    families = {"comment": _COMMENT_WRAPPERS, "declaration": _DECLARATION_WRAPPERS,
                "script": _SCRIPT_WRAPPERS, "nesting": _NESTING_WRAPPERS,
                **{f"raw-text-{t}": [(p.format(t=t, T=t.upper()), s.format(t=t, T=t.upper()))
                                     for p, s in _RAW_TEXT_WRAPPERS] for t in _RAW_TEXT_ELEMENTS}}
    for family, wrappers in families.items():
        for index, (prefix, suffix) in enumerate(wrappers):
            for payload_name, payload in _ORACLE_PAYLOADS.items():
                fragments[f"{family}:{index}:{payload_name}"] = (prefix + payload + suffix, True)
    for element in element_names:
        for index, (prefix, suffix) in enumerate(_EVERY_ELEMENT_WRAPPERS):
            fragments[f"element-{element}:{index}"] = (
                prefix.format(t=element) + _ORACLE_META + suffix.format(t=element), False)
    for index, spelling in enumerate(_ATTRIBUTE_SPELLINGS):
        fragments[f"spelling:{index}"] = (spelling, True)
    return fragments


def _oracle_run(node_tmp: Path, mode: str, cases=None):
    harness = node_tmp / "scope-oracle.cjs"
    harness.write_text(_ORACLE_HARNESS, encoding="utf-8")
    source, out = node_tmp / f"{mode}-in.json", node_tmp / f"{mode}-out.json"
    source.write_text(json.dumps(cases or []), encoding="utf-8")
    proc = subprocess.run([_NODE, str(harness), str(_ATLAS_SCOPE), mode, str(source), str(out)],
                          capture_output=True, text=True, timeout=1800)
    if proc.returncode == 3 and "ORACLE-NO-BROWSER" in proc.stdout:
        _oracle_prerequisite_absent("atlas-scope's Playwright Chromium is not installed "
                                    f"(npx playwright install chromium): {proc.stdout.strip()[:300]}")
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    return json.loads(out.read_text(encoding="utf-8"))


def _oracle_headers(name: str, served: dict) -> dict[str, str]:
    """The headers AssessHub serves member ``name`` with: the security headers measured on a real
    /scope response, and the Content-Type the real response machinery derives for its media type."""
    from starlette.responses import Response
    content_type = Response(b"", media_type=app_mod._frontend_media_type(name)).headers["content-type"]
    return {**served, "content-type": content_type}


def _measured_scope_headers(tmp: Path) -> dict[str, str]:
    """The headers a real AssessHub serves /scope members with (measured, not restated): the same
    security headers on the shell and on an asset (a ready build carries no HTML page but its shell,
    so the asset measured is its stylesheet), each with its own Content-Type."""
    control = tmp / "control"
    write_scope_dist(control)
    app = create_app(db_path=str(tmp / "control.db"), dist_dir=tmp / "no-spa", scope_dist_dir=control)
    with TestClient(app, base_url="http://localhost") as c:
        assert app.state.scope_status == "ready"
        responses = {"shell": c.get("/scope/snapshots/1/"), "asset": c.get(f"/scope/{_LINKED_CSS}")}
    served = {}
    for response in responses.values():
        assert response.status_code == 200
        for header in ("x-content-type-options", "referrer-policy", "content-security-policy",
                       "x-frame-options"):
            assert served.setdefault(header, response.headers[header]) == response.headers[header]
    assert responses["shell"].headers["content-type"] == _oracle_headers("index.html", {})["content-type"]
    assert responses["asset"].headers["content-type"] == _oracle_headers(_LINKED_CSS, {})["content-type"]
    return served


def _oracle_browser_prerequisites() -> None:
    if not _NODE or not (_ATLAS_SCOPE / "node_modules" / "playwright" / "package.json").is_file():
        _oracle_prerequisite_absent("node or atlas-scope's Playwright is not installed "
                                    "(npm ci in atlas-scope)")


@pytest.fixture(scope="module")
def scope_markup_oracle(tmp_path_factory):
    _oracle_browser_prerequisites()
    tmp = tmp_path_factory.mktemp("scope-markup-oracle")
    element_names = sorted({name.lower() for name in _oracle_run(tmp, "tags")} | set(_RAW_TEXT_ELEMENTS))
    assert len(element_names) >= 100 and set(_RAW_TEXT_ELEMENTS) <= set(element_names), element_names
    served = _measured_scope_headers(tmp)

    cases = []
    shell_template = write_scope_dist(tmp / "shell-template")
    through_index = []

    def judge(case_id: str, kind: str, name: str, document: bytes, *, shell: bool = False):
        """The index's own markup verdict (app._scope_markup_refused) over the members the build
        would have; a sample of cases is ALSO built on disk and judged by the whole index below."""
        files = dict(shell_template)
        if shell:
            files["index.html"] = document
        else:
            files[f"assets/{name}"] = document
        members = {relative: app_mod._FrontendFile(content, app_mod._frontend_media_type(relative), "")
                   for relative, content in files.items()}
        status = "invalid_build" if app_mod._scope_markup_refused(members) else "ready"
        if case_id.split("|", 1)[1].startswith(("named:", "spelling:")) or len(cases) % 23 == 0:
            through_index.append((case_id, files, status))
        path = "/scope/snapshots/1/" if shell else f"/scope/assets/{name}"
        # the markup READER's own verdict (the first gate every shell passes), apart from the index's:
        # an HTML page other than the shell is refused outright (RQF-V1-6), but the reader's reading
        # of the same markup must still be the browser's, since the shell is read with it
        reader = "accepted" if kind == "html" and app_mod._scope_html_refusal(document) is None \
            else "refused"
        cases.append({"id": case_id, "kind": kind, "path": path, "status": status, "reader": reader,
                      "media_type": app_mod._frontend_media_type("index.html" if shell else name),
                      "headers": _oracle_headers("index.html" if shell else name, served),
                      "body": base64.b64encode(document).decode("ascii")})

    for fragment_id, (fragment, with_shell) in _oracle_fragments(element_names).items():
        page = ("<!doctype html><html><head><title>x</title>" + fragment
                + "</head><body>x</body></html>").encode("utf-8")
        judge(f"asset|{fragment_id}", "html", "x.html", page)
        if with_shell:
            shell = shell_template["index.html"].replace(
                b"<title>", fragment.encode("utf-8") + b"<title>", 1)
            judge(f"shell|{fragment_id}", "html", "index.html", shell, shell=True)
    for case_id, (name, page) in _xml_family().items():  # QF-V2-1: the generated XML family
        judge(f"xml|{case_id}", "xml", name, page.encode("utf-8"))
    # the in-memory verdict IS the index's: a sample (every named form and spelling, and a stride of
    # the rest) is written out as a real build and judged by the whole _scope_file_index
    for number, (case_id, files, status) in enumerate(through_index):
        dist = tmp / f"built-{number}"
        for relative, content in files.items():
            (dist / relative).parent.mkdir(parents=True, exist_ok=True)
            (dist / relative).write_bytes(content)
        assert app_mod._scope_file_index(dist)[0] == status, case_id
    assert len(through_index) >= 60, len(through_index)
    hub = app_mod._REPO_ATLAS_SCOPE_DIST
    if (hub / "index.html").is_file():  # the real hub shell, when built, is one more member
        cases.append({"id": "shell|repository-hub-build", "kind": "html", "path": "/scope/snapshots/1/",
                      "status": app_mod._scope_file_index(hub)[0],
                      "reader": "accepted" if app_mod._scope_html_refusal(
                          (hub / "index.html").read_bytes()) is None else "refused",
                      "media_type": app_mod._frontend_media_type("index.html"),
                      "headers": _oracle_headers("index.html", served),
                      "body": base64.b64encode((hub / "index.html").read_bytes()).decode("ascii")})

    # every media type the served registry can assign, each carrying well-formed markup whose meta a
    # browser shows only if it renders the type AS markup (V2-3: the markup class is not a type list)
    probe = (f'<html xmlns="{_XHTML_NS_URI}"><head><meta name="description" content="{_MEDIA_PROBE}"/></head>'
             "<body/></html>")
    by_type: dict[str, str] = {}
    import mimetypes
    mimetypes.init()
    for suffix in sorted(set(mimetypes.types_map) | set(app_mod._FRONTEND_PINNED_MEDIA_TYPES)):
        by_type.setdefault(app_mod._frontend_media_type("x" + suffix), "x" + suffix)
    media_cases = [{"id": f"media|{media_type}", "path": f"/scope/assets/{name}",
                    "media_type": media_type, "headers": _oracle_headers(name, served),
                    "body": base64.b64encode(probe.encode("utf-8")).decode("ascii")}
                   for media_type, name in sorted(by_type.items())]
    results = _oracle_run(tmp, "render", cases + media_cases)
    return cases, media_cases, results


def _oracle_declarations(dom) -> list:
    """Every referrer-policy declaration in the DOM Chromium built (over-approximated: any spelling
    of the value, any element carrying the attribute)."""
    found = []
    for element, attributes in dom or []:
        for name, local, value, namespace in attributes:
            attribute = (local or name).lower()
            if (attribute in ("referrerpolicy", "srcdoc")
                    or (attribute == "rel" and "noreferrer" in value.lower().split())
                    or (element.lower() == "meta" and attribute == "name"
                        and value.strip().lower() == "referrer")):
                found.append((element, name, value))
    return found


def test_no_scope_document_served_ready_carries_a_referrer_policy_chromium_applies(
        scope_markup_oracle):
    """Neither a document the INDEX serves ready nor one the markup READER accepts (the gate every
    shell passes first) carries a referrer-policy declaration Chromium applies: each must send its
    full /scope Referer on a same-origin POST."""
    cases, _media, results = scope_markup_oracle
    violations = []
    for case in cases:
        if case["status"] != "ready" and case["reader"] != "accepted":
            continue
        seen = results[case["id"]]
        live = _oracle_declarations(seen["dom"])
        if not seen["rendered"] or live or seen["referer"] != _ORACLE_ORIGIN + case["path"]:
            violations.append((case["id"], live, seen["referer"],
                               base64.b64decode(case["body"])[:300]))
    assert not violations, f"{len(violations)} served-ready or reader-accepted document(s) Chromium " \
                           f"reads differently: {violations[:8]}"
    # every HTML page other than the shell is refused by the index, whatever the reader says of it
    assert not [case["id"] for case in cases
                if case["id"].startswith("asset|") and case["status"] != "invalid_build"]
    # non-vacuity: the family is not all refused by the reader, and it really carries live
    # declarations Chromium applies — including each form the stdlib HTMLParser used to hide
    accepted = [case for case in cases if case["reader"] == "accepted"]
    applied = {case["id"] for case in cases if results[case["id"]]["referer"] is None}
    assert len(accepted) >= 150, len(accepted)
    assert {case["id"].split("|", 1)[1].split(":", 1)[0] for case in accepted} >= {
        "comment", "script", "nesting", "spelling", *(f"raw-text-{t}" for t in _RAW_TEXT_ELEMENTS)}
    assert len(applied) >= 300, len(applied)
    for name in _PARSER_DIFFERENTIAL_FORMS:
        for doc in ("asset", "shell"):
            assert f"{doc}|named:{name}" in applied, (doc, name)
    assert {"xml|svg:none:none:meta", "xml|xhtml:none:none:meta"} <= applied  # XML is markup too
    assert any(case["id"] == "shell|repository-hub-build" and case["status"] == "ready"
               for case in cases) or not (app_mod._REPO_ATLAS_SCOPE_DIST / "index.html").is_file()


def test_every_scope_document_the_reader_accepts_is_read_as_chromium_reads_it(scope_markup_oracle):
    """Containment, element by element: every attribute Chromium put on any element of a document
    the reader accepted is one the reader read, with the same value — the reader's reading is the
    browser's, not an approximation that happens to agree on the refused cases."""
    cases, _media, results = scope_markup_oracle
    checked = 0
    for case in cases:
        reading = app_mod._scope_document_reading(base64.b64decode(case["body"]), case["media_type"])
        if case["status"] == "ready":
            assert reading is not None, case["id"]
        if reading is None:
            continue
        seen = results[case["id"]]
        assert seen["rendered"], case["id"]
        ours = {(element.name, attribute, value)
                for element in reading for attribute, value in element.attributes}
        theirs = set()
        for element, attributes in seen["dom"]:
            element = {"image": "img"}.get(element.lower(), element.lower())
            for name, local, value, namespace in attributes:
                if namespace == _XMLNS_NS:
                    continue  # a namespace declaration, not an attribute of the element
                attribute = (local if case["kind"] == "xml" else name).lower()
                theirs.add((element, attribute, value))
        ours |= {("img", attribute, value) for name, attribute, value in ours if name == "image"}
        assert theirs <= ours, (case["id"], sorted(theirs - ours)[:6])
        checked += 1
    assert checked >= 150, checked


def test_every_element_the_shell_may_carry_that_hides_markup_in_chromium_is_read_exactly(
        scope_markup_oracle):
    """RQF-V2-1, the raw-text set measured rather than trusted: over EVERY element name parse5
    knows, Chromium shows which ones hide the markup inside them (`<t><meta name=referrer ...></t>`
    builds no meta). Every such element the shell's accept-list admits must be one the shell reads
    exactly -- closed at its own end tag with no `<` inside (app._SCOPE_HTML_RAW_TEXT_ELEMENTS) --
    so no positive shell requirement can be met by markup the browser reads as text."""
    cases, _media, results = scope_markup_oracle
    hiding, measured = set(), 0
    for case in cases:
        match = re.fullmatch(r"asset\|element-(.+):0", case["id"])
        if match is None:
            continue
        seen = results[case["id"]]
        assert seen["rendered"], case["id"]
        measured += 1
        if not any(element == "meta" and any(name == "name" and value == "referrer"
                                             for name, _local, value, _ns in attributes)
                   for element, attributes in seen["dom"] or []):
            hiding.add(match.group(1))
    assert measured >= 100, measured
    assert set(_RAW_TEXT_ELEMENTS) <= hiding, sorted(set(_RAW_TEXT_ELEMENTS) - hiding)
    admitted_hiding = hiding & set(app_mod._SCOPE_SHELL_ELEMENTS)
    assert {"title", "script"} <= admitted_hiding, sorted(admitted_hiding)
    assert admitted_hiding <= app_mod._SCOPE_HTML_RAW_TEXT_ELEMENTS, sorted(
        admitted_hiding - app_mod._SCOPE_HTML_RAW_TEXT_ELEMENTS)


def _chromium_attributes(dom) -> set:
    return {(element.lower(), (local or name).lower(), value)
            for element, attributes in dom or [] for name, local, value, _namespace in attributes}


def test_every_xml_document_is_refused_and_chromium_shows_why_none_may_be_read_here(
        scope_markup_oracle):
    """QF-V2-1 in the browser: the whole generated XML family is refused, and Chromium shows what a
    reader would have had to match -- it renders the family as markup, applies the policies XML
    members declare, and builds `noopener noreferrer` from an external-DOCTYPE XHTML member's
    `&Tab;`, which expat drops in silence (the reader's reading before this repair)."""
    cases, _media, results = scope_markup_oracle
    xml = {case["id"]: case for case in cases if case["kind"] == "xml"}
    assert len(xml) == len(_xml_family())
    assert not [case_id for case_id, case in xml.items() if case["status"] != "invalid_build"]
    rendered = [case_id for case_id in xml if results[case_id]["rendered"] and results[case_id]["dom"]]
    assert len(rendered) >= len(xml) // 2, len(rendered)
    verifier = _chromium_attributes(results[f"xml|{_XML_VERIFIER_CASE}"]["dom"])
    assert ("a", "rel", "noopener noreferrer") in verifier, sorted(verifier)
    expanded = [case_id for case_id in xml if case_id.endswith(":rel-tab") and any(
        attribute == "rel" and {"noopener", "noreferrer"} <= set(value.split())
        for _element, attribute, value in _chromium_attributes(results[case_id]["dom"]))]
    # measured: 26 -- every XHTML/MathML public identifier in all three roots; not SVG 1.1's
    assert len(expanded) >= 20, expanded
    applied = [case_id for case_id in xml if results[case_id]["referer"] is None]
    assert len(applied) >= 60, len(applied)  # measured: 78 of the 756


@pytest.fixture(scope="module")
def scope_shell_request_oracle(tmp_path_factory):
    """Every generated shell and stylesheet (and the fixture and repository hub shells), judged by
    the index's own markup verdict and then loaded in real Chromium with every request it makes
    recorded -- by the page's own request events and by a recording proxy (see the harness)."""
    _oracle_browser_prerequisites()
    tmp = tmp_path_factory.mktemp("scope-shell-requests")
    served = _measured_scope_headers(tmp)
    template = write_scope_dist(tmp / "template")

    def served_asset(relative: str, content: bytes) -> dict:
        return {"headers": _oracle_headers(relative, served),
                "body": base64.b64encode(content).decode("ascii")}

    assets = {f"/scope/{relative}": served_asset(relative, content)
              for relative, content in template.items() if relative != "index.html"}

    def case(case_id: str, shell: bytes, status: str, *, with_assets: bool = True, loads=None,
             extra=None):
        return {"id": case_id, "path": "/scope/snapshots/1/", "status": status, "loads": loads,
                "origin": _oracle_case_origin(len(cases)),
                "assets": with_assets, "extra": extra or {},
                "headers": _oracle_headers("index.html", served),
                "body": base64.b64encode(shell).decode("ascii")}

    cases: list[dict] = []
    cases.append(case("control:template", template["index.html"],
                      "invalid_build" if app_mod._scope_markup_refused(_scope_members(template))
                      else "ready"))
    for case_id, (fragment, loads) in _shell_family().items():
        shell = _shell_with(fragment, template)
        refused = app_mod._scope_markup_refused(_scope_members({**template, "index.html": shell}))
        cases.append(case(case_id, shell, "invalid_build" if refused else "ready", loads=loads))
    # RQF-V1-3: the template shell, its linked stylesheet replaced by each generated one -- with a
    # data- attribute for attr() to read and a list for list-style-image to draw
    css_shell = template["index.html"].replace(
        f'<div id="root">{SCOPE_MARKER}</div>'.encode("utf-8"),
        (f'<div id="root"><p data-src="{_SHELL_LOAD_URLS["third-party"]}">{SCOPE_MARKER}</p>'
         "<p>x</p></div>").encode("utf-8"), 1)
    assert css_shell != template["index.html"]
    for case_id, (text, loads) in _css_family().items():
        content = text.encode("utf-8")
        refused = app_mod._scope_markup_refused(_scope_members(
            {**template, "index.html": css_shell, _LINKED_CSS: content}))
        cases.append(case(case_id, css_shell, "invalid_build" if refused else "ready", loads=loads,
                          extra={f"/scope/{_LINKED_CSS}": served_asset(_LINKED_CSS, content)}))
    hub = app_mod._REPO_ATLAS_SCOPE_DIST
    if (hub / "index.html").is_file():  # its real assets are not served: they read /api at run time
        cases.append(case("control:repository-hub-build", (hub / "index.html").read_bytes(),
                          app_mod._scope_file_index(hub)[0], with_assets=False))
    return cases, _oracle_run(tmp, "requests", {"assets": assets, "cases": cases})


def _oracle_case_origin(number: int) -> str:
    """The request oracle's origin for its case ``number``: one origin per case (see the harness)."""
    return f"http://case-{number}.scope-oracle.test:8765"


def _outside_scope(url: str, origin: str = _ORACLE_ORIGIN) -> bool:
    parsed = urllib.parse.urlsplit(url)
    return not (f"{parsed.scheme}://{parsed.netloc}" == origin and parsed.path.startswith("/scope/"))


#: The hosts other than a case's own origin that a page under test can reach: every host the family
#: names. The recording proxy also carries Chromium's OWN background traffic (component updates,
#: account checks) -- never to one of these, and never the page's -- so a proxied request counts for
#: a case only when it goes to its origin or to one of these hosts; the page's own requests count
#: wherever they go.
_ORACLE_NAMED_HOSTS = frozenset(urllib.parse.urlsplit(url).hostname
                                for url in _SHELL_LOAD_URLS.values() if "//" in url)


def _requests_outside_scope(seen: dict, origin: str) -> list[str]:
    """Every request outside /scope the browser made for one case: the page's own, wherever they
    go, and the proxied ones to the case's origin or a host the family names (the default favicon,
    a preconnect's tunnel -- requests no page event reports)."""
    hosts = _ORACLE_NAMED_HOSTS | {urllib.parse.urlsplit(origin).hostname}
    proxied = [url for url in seen["proxy"] if urllib.parse.urlsplit(url).hostname in hosts]
    return sorted({url for url in [*seen["page"], *proxied] if _outside_scope(url, origin)})


def test_no_scope_shell_served_ready_makes_a_request_outside_scope(scope_shell_request_oracle):
    """QF-V2-3 / RQF-V1-3 / RQF-V1-4 in the browser: a build the reader serves `ready` makes NO
    request outside /scope -- through its shell's markup, through the stylesheets it links, or by
    the browser's own default (the favicon) -- the property the closed accept-lists hold by
    construction, measured with request events and a recording proxy in full Chromium."""
    cases, results = scope_shell_request_oracle
    violations = []
    for case in cases:
        if case["status"] != "ready":
            continue
        seen = results[case["id"]]
        outside = _requests_outside_scope(seen, case["origin"])
        if outside or not seen["rendered"]:
            violations.append((case["id"], seen["rendered"], outside[:4]))
    assert not violations, f"{len(violations)} served-ready shell(s) load outside /scope: {violations[:8]}"
    # non-vacuity: the controls and every inert construct are served, and their indexed assets were
    # really requested (the page events and the proxy both see the shell's loads) ...
    ready = {case["id"] for case in cases if case["status"] == "ready"}
    assert {"control:template", *(f"inert:{name}" for name in _SHELL_INERT), "inert:body-content-after-the-icon",
            *(f"css-inert:{name}" for name in _CSS_INERT)} <= ready, sorted(ready)
    for channel in ("page", "proxy"):
        assert any(url.endswith("/scope/assets/index-abc123.js")
                   for url in results["control:template"][channel]), channel
        assert any(url.endswith(f"/scope/{_LINKED_CSS}")
                   for url in results["control:template"][channel]), channel
    hub_built = (app_mod._REPO_ATLAS_SCOPE_DIST / "index.html").is_file()
    assert "control:repository-hub-build" in ready or not hub_built
    assert any(case_id.startswith("css-inert:hub-") for case_id in ready) or not hub_built
    # ... and the generator really exercises the class: Chromium loads outside /scope from the
    # refused constructs, including each one a verifier measured served ready before its repair
    loaded_outside = {case["id"] for case in cases
                      if _requests_outside_scope(results[case["id"]], case["origin"])}
    for measured in ("load:table-background:third-party", "load:svg-image-xlink-href:third-party",
                     "load:style-url:third-party", "css-load:import-url:third-party",
                     "css-load:url:third-party", "load:icon-absent", "load:icon-inside-title",
                     "load:icon-inside-an-unclosed-title"):
        assert measured in loaded_outside, (measured, results[measured])
    # RQF-V2-1: every icon the reader could read where the browser builds none -- inside each element
    # the browser reads as raw text or RCDATA, a comment, a template, foreign content, or behind a
    # non-ASCII blank in its `rel` -- really makes Chromium request the default favicon, so the
    # family exercises the class rather than asserting it
    unread_icons = {case["id"] for case in cases
                    if case["id"].startswith(("load:icon-inside-", "load:icon-rel-ending-in-"))}
    assert len(unread_icons) >= 2 * len(_RAW_TEXT_ELEMENTS) + len(_NON_ASCII_BLANKS), len(unread_icons)
    assert not sorted(unread_icons - loaded_outside), sorted(unread_icons - loaded_outside)
    # the default favicon is a request the BROWSER makes: only the proxy sees it
    absent = next(case for case in cases if case["id"] == "load:icon-absent")
    assert f"{absent['origin']}/favicon.ico" in results["load:icon-absent"]["proxy"]
    assert f"{absent['origin']}/favicon.ico" not in results["load:icon-absent"]["page"]
    shell_loads = {case_id for case_id in loaded_outside if case_id.startswith("load:")}
    css_loads = {case_id for case_id in loaded_outside if case_id.startswith("css-load:")}
    assert len(shell_loads) >= 150, len(shell_loads)
    assert len(css_loads) >= 60, len(css_loads)


def _unbuilt_elements(reading, dom) -> list:
    """The elements of ``reading`` (the reader's) that Chromium did not build: each must match a
    DISTINCT element the browser built, of the same name, carrying every attribute the reader read
    with the same value (the browser may add elements -- an implied one, `</p>` -- and attributes --
    a script's -- but never drop one the reader counted)."""
    built = [(name, dict(attributes)) for name, attributes in dom]
    used: set[int] = set()
    missing = []
    for element in sorted(reading, key=lambda e: -len(e.attributes)):
        match = next((index for index, (name, attributes) in enumerate(built)
                      if index not in used and name == element.name
                      and all(attributes.get(a) == v for a, v in element.attributes)), None)
        if match is None:
            missing.append((element.name, element.attributes))
        else:
            used.add(match)
    return missing


def test_every_element_a_ready_shell_is_judged_on_is_one_chromium_built(scope_shell_request_oracle):
    """RQF-V2-1 as a class, in the browser: the shell's positive requirements count elements, so
    the shell reading (app._scope_shell_reading) of EVERY shell served ready -- the generated shell
    and stylesheet families, the fixture and the repository hub shell -- holds no element Chromium
    did not build. The generic markup reader (a superset, sound only for what must be absent) is
    shown to read an icon Chromium never built in the measured RQF-V2-1 shell, which this
    containment would catch had the shell been judged on that reading."""
    cases, results = scope_shell_request_oracle
    checked, violations = 0, []
    for case in cases:
        if case["status"] != "ready":
            continue
        seen = results[case["id"]]
        reading = app_mod._scope_shell_reading(base64.b64decode(case["body"]))
        assert reading is not None and seen["dom"] is not None, case["id"]
        missing = _unbuilt_elements(reading, seen["dom"])
        if missing:
            violations.append((case["id"], missing[:3]))
        checked += 1
    assert not violations, f"{len(violations)} ready shell(s) read elements Chromium did not build: " \
                           f"{violations[:6]}"
    # every inert shell and stylesheet construct and the fixture control at least (measured: 31 with
    # the hub build present)
    assert checked >= 1 + len(_SHELL_INERT) + len(_CSS_INERT), checked
    titled = next(case for case in cases if case["id"] == "load:icon-inside-title")
    superset = app_mod._scope_document_reading(base64.b64decode(titled["body"]), "text/html")
    missing = _unbuilt_elements(superset, results[titled["id"]]["dom"])
    assert [name for name, _attributes in missing] == ["link"], missing
    assert ("rel", "icon") in missing[0][1], missing


def test_every_media_type_chromium_renders_as_markup_is_read_as_markup(scope_markup_oracle):
    """P3F-V2-3 as a class: over every media type the served registry can assign a /scope member,
    Chromium's own rendering decides what is markup, and the reader must hold each such type to
    the referrer rule — the markup set is measured, not a hand-kept pair of types."""
    _cases, media_cases, results = scope_markup_oracle
    # the probe's OWN meta, by its marker value (a browser's JSON, text and media viewers build
    # documents with metas of their own)
    rendered_as_markup = sorted(
        case["media_type"] for case in media_cases
        if any(value == _MEDIA_PROBE for _element, attributes in results[case["id"]]["dom"] or []
               for _name, _local, value, _namespace in attributes))
    missed = [t for t in rendered_as_markup if app_mod._scope_markup_kind(t) is None]
    assert not missed, missed
    for expected in ("text/html", "image/svg+xml", "application/xhtml+xml"):
        assert expected in rendered_as_markup, (expected, rendered_as_markup)
    assert len(media_cases) >= 20, len(media_cases)


# ── the test-only boundary, proved here rather than trusted (phase 3.5) ─────────────────────────
# Atlas Scope keeps its test-only modules under src/test-support/. The evidence scan below may pass
# over that directory ONLY because this file proves, with its own parser over the tree, that no
# module a build can reach imports anything there: every non-test module under the scanned roots,
# every root HTML page's module scripts, and every Vite configuration a build loads (the default
# vite.config.* and any file a package script passes with --config/-c). The specifier forms read are
# static import, re-export, side-effect import, dynamic import(), require(), `new URL(...,
# import.meta.url)`, `import.meta.glob` patterns — literal and expanded — and CSS @import/url(), with
# whitespace, block and line comments, and redundant parentheses between the tokens read as the
# trivia a bundler skips; in a configuration, every string literal that names the boundary
# directory is an edge, since its inputs are plain strings. A specifier Vite expands from pieces
# (`import("./test-support/" + name)`, a template literal with substitutions) is read by its first
# literal piece, so it is an edge whenever that piece names the directory; a directory name spelt
# ACROSS pieces, or a specifier held in a variable, is not modelled. A form that mentions a boundary
# path in a comment reads as an edge too: that only fails closed. The vitest
# guard (src/core/test-support-boundary.test.ts) states the same rule; this is deliberately a second,
# independent reading, so a bug or an edit in that file cannot quietly widen what this one skips.
# The CLASS of files a Vite build can bundle, stated as the vitest guard states it (src/core/test-support-boundary.test.ts:
# code is [cm]?[jt]sx?) plus the JSON and CSS a build imports. A fixed suffix list silently exempted .jsx/.cjs/.cts
# (phase 3.5 finishing verifier). A test module is exactly what vitest runs: *.test.[cm]?[jt]sx?.
_SCOPE_BUILD_FILE = re.compile(r"\.(?:[cm]?[jt]sx?|json|css)$")
_SCOPE_TEST_FILE = re.compile(r"\.test\.[cm]?[jt]sx?$")
_SCOPE_SOURCE_ROOTS = ("src", "tools/lib", "contracts")
_SCOPE_SUPPORT = Path("src") / "test-support"
_SCOPE_QUOTED = r"""(["'`])([^"'`\n]+)\1"""
# Trivia between a form's tokens, as a bundler's own scanner skips it: whitespace, a /* block */ and a
# // line comment. A form written across a comment is the same edge (phase 3.5 V2: `import(` then a
# line comment then the specifier was bundled by Vite and read here as no edge at all).
_SCOPE_GAP = r"(?:\s|/\*[\s\S]*?\*/|//[^\n]*(?:\n|$))*"
_SCOPE_GAP1 = r"(?:\s|/\*[\s\S]*?\*/|//[^\n]*(?:\n|$))+"
# ... and, inside a call, redundant parentheses around the argument: `import(("x"))` names "x" too.
_SCOPE_ARG = r"(?:\s|\(|/\*[\s\S]*?\*/|//[^\n]*(?:\n|$))*"
_SCOPE_SPECIFIER_FORMS = (
    ("from", re.compile(r"\bfrom" + _SCOPE_GAP + _SCOPE_QUOTED)),
    ("import", re.compile(r"(?<!@)\bimport" + _SCOPE_GAP + _SCOPE_QUOTED)),
    ("import()", re.compile(r"\bimport" + _SCOPE_GAP + r"\(" + _SCOPE_ARG + _SCOPE_QUOTED)),
    ("require()", re.compile(r"\brequire" + _SCOPE_GAP + r"\(" + _SCOPE_ARG + _SCOPE_QUOTED)),
    ("new URL", re.compile(r"\bnew" + _SCOPE_GAP1 + r"URL" + _SCOPE_GAP + r"\(" + _SCOPE_ARG + _SCOPE_QUOTED)),
    ("@import", re.compile(r"@import" + _SCOPE_GAP + r"(?:url\(" + _SCOPE_GAP + r")?"
                           + r"""(["']?)([^"')\s;]+)\1""")),
    ("url()", re.compile(r"\burl\(" + _SCOPE_GAP + r"""(["']?)([^"')\s]+)\1\s*\)""")),
    ("script src", re.compile(r"""<script\b[^>]*\bsrc\s*=\s*(["'])([^"']+)\1""", re.IGNORECASE)),
)
_SCOPE_GLOB_CALL = re.compile(
    r"\bimport" + _SCOPE_GAP + r"\." + _SCOPE_GAP + r"meta" + _SCOPE_GAP + r"\." + _SCOPE_GAP + r"glob"
    + _SCOPE_GAP + r"(?:<[^>()]*>)?" + _SCOPE_GAP + r"\(" + _SCOPE_ARG
    + r"""(\[[^\]]*\]|(["'`])[^"'`\n]*\2)""")
_SCOPE_LITERAL = re.compile(_SCOPE_QUOTED)
# A build configuration names its inputs as plain strings (rollupOptions.input, a plugin's path), so
# every literal in one that mentions the boundary directory is read as an edge into it.
_SCOPE_BOUNDARY_NAME = re.compile(r"(?:^|[\\/])test-support(?:[\\/]|$)")
_SCOPE_DEFAULT_CONFIGS = tuple(f"vite.config.{ext}" for ext in ("js", "mjs", "ts", "cjs", "mts", "cts"))
_SCOPE_CONFIG_FLAG = re.compile(r"""(?:^|\s)(?:--config|-c)(?:=|\s+)(["']?)([^\s"']+)\1""")


def _scope_is_build_file(path: Path) -> bool:
    return bool(_SCOPE_BUILD_FILE.search(path.name))


def _scope_is_test_module(path: Path) -> bool:
    return bool(_SCOPE_TEST_FILE.search(path.name))


def _scope_inside(target: str, directory: Path) -> bool:
    here, there = os.path.normcase(os.path.normpath(target)), os.path.normcase(os.path.normpath(directory))
    return here == there or here.startswith(there + os.sep)


def _scope_import_targets(path: Path, text: str, package: Path) -> list[tuple[str, str]]:
    """(form, normalised file-system path) for every specifier in one source that names a file:
    relative ones against the file's directory, root-absolute ones ('/src/...') against the
    package, bare package names skipped. A glob yields its pattern AND every file it expands to."""
    out: list[tuple[str, str]] = []

    def place(spec: str) -> str | None:
        spec = re.split(r"[?#]", spec, maxsplit=1)[0]
        if spec.startswith("/"):
            return os.path.normpath(package / spec.lstrip("/"))
        if spec.startswith("."):
            return os.path.normpath(path.parent / spec)
        return None

    for form, pattern in _SCOPE_SPECIFIER_FORMS:
        for match in pattern.finditer(text):
            target = place(match.group(2))
            if target is not None:
                out.append((form, target))
    for call in _SCOPE_GLOB_CALL.finditer(text):
        for literal in _SCOPE_LITERAL.finditer(call.group(1)):
            spec = literal.group(2)
            target = place(spec.lstrip("!"))
            if target is None:
                continue
            out.append(("import.meta.glob", target))
            out.extend(("import.meta.glob", os.path.normpath(hit))
                       for hit in glob.glob(target, recursive=True))
    return out


def _scope_build_configs(package: Path) -> list[Path]:
    """The Vite configurations a build loads, from the package itself: the default config file Vite
    looks for at the root, and every file a package.json script hands Vite with --config/-c."""
    configs = {package / name for name in _SCOPE_DEFAULT_CONFIGS}
    manifest = package / "package.json"
    if manifest.is_file():
        scripts = json.loads(manifest.read_text(encoding="utf-8")).get("scripts") or {}
        for command in scripts.values():
            if isinstance(command, str) and re.search(r"(?:^|[\s&|;])vite\b", command):
                configs.update(package / m.group(2) for m in _SCOPE_CONFIG_FLAG.finditer(command))
    return sorted(path for path in configs if path.is_file())


def _scope_test_support_boundary(package: Path) -> dict:
    """The boundary, read from the tree: every edge from a module a build can reach (a non-test
    module outside src/test-support/, a root HTML page, or a build configuration) into
    src/test-support/."""
    support = package / _SCOPE_SUPPORT
    violations, product_modules, test_edges = [], [], 0
    configs = _scope_build_configs(package)
    sources = [page for page in sorted(package.glob("*.html")) if page.is_file()] + configs
    for root in _SCOPE_SOURCE_ROOTS:
        sources += [p for p in sorted((package / root).rglob("*"))
                    if p.is_file() and _scope_is_build_file(p) and p not in configs]
    for path in sources:
        if _scope_inside(str(path), support):
            continue  # the boundary may import product code; that is not an edge out of a build
        text = path.read_text(encoding="utf-8", errors="replace")
        into = [(form, target) for form, target in _scope_import_targets(path, text, package)
                if _scope_inside(target, support)]
        if path in configs:
            # Every literal in a config that names the boundary directory is an edge, however it is
            # spelt or joined (resolve(__dirname, "src/test-support/x"), "./src/...", "src/..."):
            # reported at its package-relative reading, and never filtered by where that lands.
            into += [("build config literal", os.path.normpath(package / spec.lstrip("/")))
                     for _quote, spec in _SCOPE_LITERAL.findall(text) if _SCOPE_BOUNDARY_NAME.search(spec)]
        if _scope_is_test_module(path):
            test_edges += len(into)
            continue
        product_modules.append(path)
        violations += [f"{path.relative_to(package).as_posix()} -> "
                       f"{Path(os.path.relpath(target, package)).as_posix()} ({form})"
                       for form, target in into]
    return {"violations": sorted(set(violations)), "product_modules": product_modules,
            "test_edges": test_edges, "build_configs": configs}


def test_the_boundary_reader_reads_every_bundleable_suffix_and_only_real_tests_as_tests(tmp_path):
    """Phase 3.5 finishing verifier: the product-module class was a fixed suffix list, so a .jsx/.cjs/.cts
    module Vite bundles could reach into src/test-support/ unseen while the scan still skipped the boundary;
    and any name containing '.test.' was taken for a test. The class is now the vitest guard's own rule
    ([cm]?[jt]sx?, plus the JSON and CSS a build imports), and a test is exactly *.test.[cm]?[jt]sx?."""
    def put(rel: str, text: str) -> None:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")

    put("src/test-support/s.ts", "export const s = 1;\n")
    put("src/leak.jsx", 'import { s } from "./test-support/s";\nexport const x = s;\n')
    put("src/leak.cjs", 'module.exports = require("./test-support/s");\n')
    put("src/leak.cts", 'import { s } from "./test-support/s";\nexport = s;\n')
    put("src/helper.test.data.ts", 'import { s } from "./test-support/s";\nexport const d = s;\n')
    put("src/real.test.tsx", 'import { s } from "./test-support/s";\nexport { s };\n')
    put("src/notes.md", 'import { s } from "./test-support/s";\n')
    put("src/readme_ts", 'import { s } from "./test-support/s";\n')  # no suffix: the dot in the rule is literal

    report = _scope_test_support_boundary(tmp_path)
    assert report["violations"] == sorted([
        "src/helper.test.data.ts -> src/test-support/s (from)",
        "src/leak.cjs -> src/test-support/s (require())",
        "src/leak.cts -> src/test-support/s (from)",
        "src/leak.jsx -> src/test-support/s (from)",
    ]), report["violations"]


def test_the_test_support_boundary_reader_sees_every_import_form(tmp_path):
    """Known answer: a planted package whose product modules reach into src/test-support/ by each
    form is reported edge by edge; a test importing the boundary, and the boundary importing
    product code, are not; and the same package with those edges removed is clean."""
    def put(rel: str, text: str) -> None:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")

    for name in ("s", "r", "e", "d", "u", "g", "a", "w", "c"):
        put(f"src/test-support/{name}.ts", f"export const {name} = 1;\n")
    put("src/test-support/c.css", "a { color: red; }\n")
    put("src/test-support/back.ts", 'import { x } from "../static";\nexport { x };\n')
    put("index.html", '<script type="module" src="/src/test-support/e.ts"></script>\n')
    put("src/static.ts", 'import { s } from "./test-support/s";\nexport const x = s;\n')
    put("src/types.ts", 'import type {\n  R,\n} from "./test-support/r";\nexport type T = R;\n')
    put("src/reexport.ts", 'export * from "./test-support/e";\n')
    put("src/side.ts", 'import "./test-support/d";\n')
    put("src/dyn.tsx", 'export const f = () => import(\n  "./test-support/u"\n);\n')
    put("src/url.ts", 'export const w = new URL("./test-support/w.ts?url", import.meta.url);\n')
    put("src/glob.ts", 'export const g = import.meta.glob("./test-support/g.ts");\n')
    put("src/glob-array.ts", 'export const a = import . meta . glob(["!./x", "./test-support/a.ts"]);\n')
    put("src/glob-wild.ts", 'export const m = import.meta.glob("./*/w.ts", { eager: true });\n')
    put("src/style.css", '@import "./test-support/c.css";\n.b { background: url(./test-support/c.css); }\n')
    put("src/root-abs.ts", 'import { s } from "/src/test-support/s";\nexport { s };\n')
    put("src/x.test.ts", 'import { s } from "./test-support/s";\nexport { s };\n')
    put("src/clean.ts", '// mentions src/test-support/s.ts in prose only\nimport { y } from "./static";\n'
                        'import React from "react";\nexport { y, React };\n')
    # comments are trivia to a bundler: every form still names its file across a line or block comment
    put("src/dyn-line-comment.ts", 'export const f = () =>\n  import(\n    // the golden tier, lazily\n'
                                   '    "./test-support/u"\n  );\n')
    put("src/dyn-block-comment.ts",
        'export const f = () => import(/* webpackChunkName: "g" */ "./test-support/u");\n')
    put("src/from-comment.ts", 'import { u } from /* golden */ "./test-support/u";\nexport { u };\n')
    put("src/side-comment.ts", 'import /* for its effect */ "./test-support/d";\n')
    put("src/url-comment.ts", 'export const w = new /* an asset */ URL(\n  // the worker\n'
                              '  "./test-support/w.ts", import.meta.url);\n')
    put("src/glob-comment.ts", 'export const k = import.meta/* x */.glob(\n  /* lazily */ "./test-support/g.ts");\n')
    put("src/paren.ts", 'export const p = () => import(("./test-support/u"));\n')
    put("src/cjs.ts", 'export const r = require(\n  // interop\n  "./test-support/s");\n')
    # a specifier Vite expands from pieces is read by its first literal piece
    put("src/concat.ts", 'export const f = (n: string) => import("./test-support/" + n + ".ts");\n')
    put("src/template.ts", 'export const f = (n: string) => import(`./test-support/${n}.ts`);\n')
    # a build config names its inputs as plain strings: the default config and one a script selects
    put("package.json", '{"scripts": {"build": "tsc && vite build",'
                        ' "build:alt": "vite build --config build/alt.config.mjs --mode alt"}}\n')
    put("vite.config.ts", 'import { resolve } from "node:path";\nexport default { build: { rollupOptions:'
                          ' { input: { t: resolve(__dirname, "src/test-support/s.ts") } } } };\n')
    put("build/alt.config.mjs", 'export default { build: { rollupOptions: { input: "./src/test-support/e.ts" } } };\n')

    report = _scope_test_support_boundary(tmp_path)
    assert [p.relative_to(tmp_path).as_posix() for p in report["build_configs"]] == [
        "build/alt.config.mjs", "vite.config.ts"], report["build_configs"]
    assert report["violations"] == sorted([
        "src/dyn-line-comment.ts -> src/test-support/u (import())",
        "src/dyn-block-comment.ts -> src/test-support/u (import())",
        "src/from-comment.ts -> src/test-support/u (from)",
        "src/side-comment.ts -> src/test-support/d (import)",
        "src/url-comment.ts -> src/test-support/w.ts (new URL)",
        "src/glob-comment.ts -> src/test-support/g.ts (import.meta.glob)",
        "src/paren.ts -> src/test-support/u (import())",
        "src/cjs.ts -> src/test-support/s (require())",
        "src/concat.ts -> src/test-support (import())",
        "src/template.ts -> src/test-support/${n}.ts (import())",
        "vite.config.ts -> src/test-support/s.ts (build config literal)",
        "build/alt.config.mjs -> src/test-support/e.ts (build config literal)",
        "index.html -> src/test-support/e.ts (script src)",
        "src/static.ts -> src/test-support/s (from)",
        "src/types.ts -> src/test-support/r (from)",
        "src/reexport.ts -> src/test-support/e (from)",
        "src/side.ts -> src/test-support/d (import)",
        "src/dyn.tsx -> src/test-support/u (import())",
        "src/url.ts -> src/test-support/w.ts (new URL)",
        "src/glob.ts -> src/test-support/g.ts (import.meta.glob)",
        "src/glob-array.ts -> src/test-support/a.ts (import.meta.glob)",
        "src/glob-wild.ts -> src/test-support/w.ts (import.meta.glob)",
        "src/style.css -> src/test-support/c.css (@import)",
        "src/style.css -> src/test-support/c.css (url())",
        "src/root-abs.ts -> src/test-support/s (from)",
    ]), report["violations"]
    assert report["test_edges"] == 1

    # the same package with every product edge into the boundary removed is clean
    for rel in ("index.html", "src/static.ts", "src/types.ts", "src/reexport.ts", "src/side.ts",
                "src/dyn.tsx", "src/url.ts", "src/glob.ts", "src/glob-array.ts", "src/glob-wild.ts",
                "src/style.css", "src/root-abs.ts", "src/dyn-line-comment.ts", "src/dyn-block-comment.ts",
                "src/from-comment.ts", "src/side-comment.ts", "src/url-comment.ts", "src/glob-comment.ts",
                "src/paren.ts", "src/cjs.ts", "src/concat.ts", "src/template.ts"):
        (tmp_path / rel).unlink()
    put("src/static.ts", "export const x = 1;\n")
    put("vite.config.ts", 'import { resolve } from "node:path";\nexport default { build: { rollupOptions:'
                          ' { input: { t: resolve(__dirname, "index.html") } } } };\n')
    put("build/alt.config.mjs", 'export default { build: { outDir: "dist-alt" } };\n')
    clean = _scope_test_support_boundary(tmp_path)
    assert clean["violations"] == [] and clean["test_edges"] == 1, clean["violations"]


def test_no_module_a_runtime_build_can_bundle_reads_as_snapshot_evidence():
    """Every non-test module under atlas-scope/src and the compiler library — what a runtime build
    can import — scanned as a build file, derived from the tree. None may read as snapshot evidence,
    or the phase-3 runtime build would be refused for its own code. The compiled datasets (the
    compiler's own OUTPUTS[].trackedPath) are excluded, and so is src/test-support/ — but only
    because the boundary is proved first, by this file's own reading of the import graph: no module
    a build can reach imports anything there."""
    boundary = _scope_test_support_boundary(_ATLAS_SCOPE)
    assert boundary["violations"] == [], boundary["violations"]
    # NON-VACUITY: the reader resolves the real tree's imports — the app entry's own, and the
    # suite's edges into the boundary — so an empty violation list was found by looking
    entry = _ATLAS_SCOPE / "src" / "main.tsx"
    assert len(_scope_import_targets(entry, entry.read_text(encoding="utf-8"), _ATLAS_SCOPE)) >= 3
    assert boundary["test_edges"] >= 30, boundary["test_edges"]
    assert len(boundary["product_modules"]) >= 50, len(boundary["product_modules"])
    # the build's own configuration was read as a build input, not assumed to name nothing
    assert _ATLAS_SCOPE / "vite.config.ts" in boundary["build_configs"], boundary["build_configs"]

    support = _ATLAS_SCOPE / _SCOPE_SUPPORT
    compiled = {(_ATLAS_SCOPE / path).resolve() for path in _tracked_compiled_files()}
    scanned, skipped = [], []
    for root in (_ATLAS_SCOPE / "src", _ATLAS_SCOPE / "tools" / "lib", _ATLAS_SCOPE / "contracts"):
        for path in sorted(root.rglob("*")):
            if (not path.is_file() or path.resolve() in compiled or _scope_is_test_module(path)
                    or not _scope_is_build_file(path)):
                continue
            if _scope_inside(str(path), support):
                skipped.append(path)
                continue
            scanned.append(path)
            assert not app_mod._scope_file_carries_compiled_model(path.read_bytes()), path
    assert len(scanned) >= 50, len(scanned)
    assert len(compiled) >= 4
    assert skipped, "the boundary this test skips exists"


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
