"""AssessHub FastAPI application.

REST surface over the snapshot store. The engine produces snapshots (CLI); this serves, slices,
diffs, trends, and renders them. Also serves the built frontend (webapp/frontend/dist) when present,
so the whole platform runs from one origin in production.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
from dataclasses import dataclass, field
import functools
import hashlib
import hmac
from html.parser import HTMLParser
import json
import mimetypes
import os
import posixpath
import re
import sqlite3
import stat
import sys
import tempfile
import threading
import urllib.parse
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, BinaryIO, Callable, Dict, List, Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi import Path as PathParam
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from cisco_toolkit import brand_tokens, docmeta
from cisco_toolkit.protocol_assurance import (
    PERSISTED_SOURCE as _PERSISTED_SNAPSHOT_SOURCE,
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
    ui_projection_api,
)
from .storage import ExecutionReceiptAuthorityError, Store

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
# Atlas Scope (the 3-D investigation app, `atlas-scope/` in this repository) is served same-origin at
# /scope when its /scope build exists: the HUB build, which atlas-scope's `npm run build:hub` writes to
# atlas-scope/dist-hub (base /scope/, no compiled dataset, the runtime-source declaration below). The
# standalone sample build (atlas-scope/dist, `npm run build`) is a different artifact that declares no
# runtime source and is refused here (invalid_build), so it is never the default. Absent in an
# installed wheel (the parent is site-packages), in which case /scope answers honestly that it is not
# built. A frozen Atlas bundle passes its bundled copy explicitly (webapp/backend/serve.py
# `_resolve_scope_dist`); `create_app(scope_dist_dir=...)` overrides.
_ATLAS_SCOPE_HUB_BUILD_DIR = "dist-hub"
_REPO_ATLAS_SCOPE_DIST = _WEBAPP.parent / "atlas-scope" / _ATLAS_SCOPE_HUB_BUILD_DIR
ATLAS_SCOPE_DIST = _REPO_ATLAS_SCOPE_DIST
_SCOPE_MOUNT = "/scope/"
# The build contract a scope build must declare to be linked from a stored snapshot: it reads that
# snapshot at RUN TIME from /api (GET /api/snapshots/{id}/raw), rather than showing whatever evidence
# was compiled into it. Without it, /scope/snapshots/{id}/ could render the bundled sample fleet under
# a client snapshot's URL — a view of the wrong data presented as the right one.
_SCOPE_RUNTIME_SOURCE_META = "atlas-scope-snapshot-source"
_SCOPE_RUNTIME_SOURCE_VALUE = "assesshub-api-runtime"
_SCOPE_ENGINE_PROJECTION_META = "atlas-scope-engine-projection"
_SCOPE_ENGINE_PROJECTION_PROTOCOL = "atlas.ui_projection_embed/1"
_SCOPE_DIST_DEFAULT: Any = object()
_SHA256_HEX_TOKEN_RE = re.compile(rb"(?<![0-9A-Fa-f])[0-9A-Fa-f]{64}(?![0-9A-Fa-f])")
_SCOPE_UNAVAILABLE_DETAIL = {
    "not_built": "Atlas Scope is not built in this installation. AssessHub serves it at /scope only "
                 "when a /scope build of atlas-scope is present.",
    "invalid_build": "Atlas Scope is not built in this installation for AssessHub: the build found is "
                     "not a /scope runtime-snapshot build (every asset must load from /scope/assets/ "
                     f"and index.html must declare <meta name=\"{_SCOPE_RUNTIME_SOURCE_META}\" "
                     f"content=\"{_SCOPE_RUNTIME_SOURCE_VALUE}\">, in markup this server reads "
                     "exactly as a browser does, built only from the constructs it accepts, with "
                     "an icon and no referrer policy of its own, which would override the "
                     "same-origin policy AssessHub's write containment relies on; index.html must "
                     "be the build's only HTML page and it may carry no XML document; and every "
                     "stylesheet must name no resource, so the page loads nothing outside /scope), "
                     "so it is not served.",
    "refused_compiled_evidence": "Atlas Scope is withheld: its static build carries snapshot "
                                 "evidence (a compiled snapshot model — a compiled source binding "
                                 "or a compiled record's snapshot citation — or an engine snapshot "
                                 "itself), so it would show that evidence instead of the snapshot "
                                 "it is opened for. AssessHub serves only a build that carries no "
                                 "compiled dataset at all and reads every snapshot at run time "
                                 "from /api.",
    "refused_uninspectable": "Atlas Scope is withheld: its static build carries content this "
                             "server cannot inspect for snapshot evidence (a content encoding it "
                             "does not decode, such as Brotli; a compressed stream that does not "
                             "decode completely within the per-file bound; or a payload nested "
                             "beyond the scan bound), so it cannot establish that the build "
                             "carries no compiled dataset. Rebuild Atlas Scope without "
                             "precompressed copies.",
    "refused_embeds_stored_snapshot": "Atlas Scope is withheld: its static build embeds the digest of "
                                      "a stored snapshot. Rebuild Atlas Scope without compiling "
                                      "client evidence into it; it must read snapshots at run time "
                                      "from /api.",
}
# What 'ready' establishes, and no more: the build DECLARES the runtime snapshot source and no file
# in it carries a form of snapshot evidence this server recognises (_scope_file_carries_compiled_model).
_SCOPE_READY_DETAIL = ("Atlas Scope is built for this installation: the build declares that it reads "
                       "the snapshot at run time from the guarded /api, and no file in it carries a "
                       "recognised compiled snapshot model or engine snapshot.")
# PRIVACY BY CONSTRUCTION. /scope files are served outside the /api guard, so a servable build
# carries NO compiled dataset: it reads every snapshot at run time from /api. The Atlas Scope
# compiler (atlas-scope/tools/lib/compile-model.mjs, whose exported BINDING_KEYS lists every key a
# source binding carries) writes the binding into the `meta` of EVERY file it emits, and these two
# keys always carry literal values there — the digest form's name and the Git blob id. A file in
# which BOTH are bound to string literals is a compiled model, whatever snapshot it came from and
# whichever digest form it uses (the bundled sample included). The keys' mere NAMES are not the
# signature: a runtime build bundles the compiler, which names every key, and labels its own
# binding with a literal `sourceDigestForm`; only a compiled record binds `sourceGitBlob` to a
# literal. webapp/tests/test_scope_mount.py pins the pair to BINDING_KEYS and to the compiler's
# real output, so a rename there fails the suite instead of silently reopening the gap.
_SCOPE_COMPILED_MODEL_SIGNATURE_KEYS = ("sourceDigestForm", "sourceGitBlob")
# Whitespace between JSON tokens in every form a build ships a document: literal whitespace (JSON, a
# bundler's object literal) or its escape (\n \r \t) when the document is itself a string — escaped
# inside a JS string, or once more inside a sourcemap's sourcesContent (\\n). Every signature below
# uses it wherever JSON allows whitespace, so a PRETTY-printed document escaped inside a string is
# recognised exactly like a compact one (R8-V2-2: a pretty, escaped citation-keyed map was not).
_JS_WS = rb"(?:\s|\\+[nrt])*"
# A key bound to a string literal in any form a build ships it: JSON ("k": "v"), a JSON document
# escaped inside a JS string or a sourcemap (\"k\":\"v\"), or a bundler's object literal (k:`v`).
_SCOPE_COMPILED_MODEL_SIGNATURE = tuple(
    re.compile(rb"(?<![A-Za-z0-9_$])" + re.escape(key.encode("ascii"))
               + rb"(?![A-Za-z0-9_$])\\*[\"'`]?" + _JS_WS + rb":" + _JS_WS + rb"\\*[\"'`]")
    for key in _SCOPE_COMPILED_MODEL_SIGNATURE_KEYS)
# The binding lives only in each compiled file's `meta` ENVELOPE, which a bundler drops: Vite's JSON
# plugin turns every top-level member into a named export, so `import { devices } from
# "./fabric.json"` ships the device records with no `meta` at all (measured: a real Vite 8 build
# carried compiled records and neither signature key). The compiler's per-RECORD contract survives
# that: "Every record carries `cite`: a dotted path back into the snapshot" (compile-model.mjs), and
# a citation is rooted at one of the snapshot sections the compiler reads (its exported
# SECTIONS_READ). A compiled record is therefore recognised by a snapshot citation bound as DATA —
# the value of a `cite`-named key (`cite`, `centralityCite`, ...) or an object key (the cite-keyed
# maps) — as a complete string literal. The compiler's own code builds citations from template
# literals (`interfaces.${host}.${port}`), which never match. Pinned to SECTIONS_READ and to the
# compiler's real output, member by member, by webapp/tests/test_scope_mount.py.
_SCOPE_SNAPSHOT_SECTIONS = (
    "acl_line_reachability", "acls", "cable_map", "cross_layer", "devices", "endpoint_identity",
    "failure_impact", "health_scores", "interfaces", "l3_forwarding", "link_centrality",
    "object_groups", "overlay", "physical_health", "protocol_assessability", "protocol_health",
    "punchlist", "routes", "routing_neighbors",
)
# An engine snapshot itself (the very file a client uploads) is evidence too: it binds `schema` to
# the engine's snapshot schema family (the compiler's exported SUPPORTED_SCHEMAS, versions dropped).
_SCOPE_SNAPSHOT_SCHEMA_FAMILIES = ("collect_parse_snapshot/",)
# One string literal in any quoting a build ships (JSON "..", an escaped JSON document inside a JS
# string \"..\", a bundler's `..` or '..'), whose body has no template substitution.
_JS_QUOTE = rb"""\\*["'`]"""
_JS_LITERAL_BODY = rb"""(?:[^"'`\\\r\n$]|\$(?!\{))+"""
# A citation takes one of the two forms a snapshot address is written in: the compiler's dotted path
# rooted at a section it reads (`interfaces.core1.Gi1/0/1`), or the ENGINE's own form — an RFC 6901
# JSON Pointer into the same snapshot (`/interfaces/core1/Gi1~10~11`, the form of every punch-list
# `evidence_refs` pointer, docs/ssot.md "Per-finding evidence pointers"), which a compiled record
# carries when it projects a pointed-to engine record. A pointer may root at ANY published section
# (the engine publishes more sections than the compiler reads), so its root is bounded by shape — a
# lowercase snake-case section name followed by at least one more reference token — not by
# SECTIONS_READ.
_SNAPSHOT_CITATION = (
    _JS_QUOTE + rb"(?:(?:" + b"|".join(re.escape(s.encode("ascii")) for s in _SCOPE_SNAPSHOT_SECTIONS)
    + rb")[.\[]|/[a-z][a-z0-9_]*/)" + _JS_LITERAL_BODY + _JS_QUOTE)
_SCOPE_RECORD_CITATION_SIGNATURE = (
    # a citation bound to a `cite`-named key
    re.compile(rb"(?<![A-Za-z0-9_$])(?:[A-Za-z_$][A-Za-z0-9_$]*)?[Cc]ite" + _JS_QUOTE
               + rb"?" + _JS_WS + rb":" + _JS_WS + _SNAPSHOT_CITATION),
    # a citation used as an object key (a map keyed by citation)
    re.compile(rb"[{,]" + _JS_WS + _SNAPSHOT_CITATION + _JS_WS + rb":"),
)
_SCOPE_RAW_SNAPSHOT_SIGNATURE = re.compile(
    rb"(?<![A-Za-z0-9_$])schema" + _JS_QUOTE + rb"?" + _JS_WS + rb":" + _JS_WS + _JS_QUOTE + rb"(?:"
    + b"|".join(re.escape(f.encode("ascii")) for f in _SCOPE_SNAPSHOT_SCHEMA_FAMILIES)
    + rb")[0-9]+" + _JS_QUOTE)
# A base64 `data:` URI: how a bundler inlines a small asset or an inline sourcemap (whose
# sourcesContent carries the compiled JSON verbatim). Its payload is inspected like a file, and so
# is the decompressed content of every stream a standard-library codec decodes (gzip, bzip2, xz) —
# a precompressed copy a compression plugin emits, or a compressed payload inside a data: URI —
# recognised by its magic whatever the file is called.
_BASE64_DATA_URI_RE = re.compile(rb"data:[A-Za-z0-9.+/-]*(?:;[A-Za-z0-9.+/=-]*)*;base64,"
                                 rb"([A-Za-z0-9+/_-]{16,}={0,2})")
_GZIP_MAGIC = b"\x1f\x8b\x08"
_BZIP2_MAGIC_RE = re.compile(rb"BZh[1-9]1AY&SY")
_XZ_MAGIC = b"\xfd7zXZ\x00"
_SCOPE_DATA_URI_DEPTH = 3
# The census-keyed startup index of recently seen scope builds (see _scope_file_index).
_SCOPE_INDEX_CACHE: "dict[tuple[str, tuple], tuple[str, dict, frozenset[str]]]" = {}
_SCOPE_INDEX_CACHE_MAX = 4
_SCOPE_INDEX_CACHE_LOCK = threading.Lock()
# Same-origin write containment for the first-party read-only viewer (see _referred_from_scope).
_SCOPE_WRITE_REFUSED_DETAIL = ("State-changing request refused: it was referred from an Atlas "
                               "Scope page (/scope/), and Atlas Scope is a read-only viewer that "
                               "never writes.")
_FRONTEND_MAX_FILES = 4_096
_FRONTEND_MAX_ENTRIES = 8_192
_FRONTEND_MAX_FILE_BYTES = 64 * 1024 * 1024
_FRONTEND_MAX_TOTAL_BYTES = 256 * 1024 * 1024
_FRONTEND_PINNED_MEDIA_TYPES = {
    ".css": "text/css",
    ".html": "text/html",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
}


@dataclass(frozen=True)
class _FrontendFile:
    content: bytes
    media_type: str
    etag: str


class _FrontendShellParser(HTMLParser):
    """Extract the small, local boot contract from Vite's generated shell."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.doctype = 0
        self.html_start = 0
        self.html_end = 0
        self.head_start = 0
        self.head_end = 0
        self.body_start = 0
        self.body_end = 0
        self.script_start = 0
        self.script_end = 0
        self.root_mounts = 0
        self.in_head = False
        self.in_body = False
        self.invalid = False
        self.references: list[tuple[str, Literal["module", "script", "stylesheet"]]] = []

    def handle_decl(self, declaration: str) -> None:
        if declaration.strip().casefold() == "doctype html":
            self.doctype += 1
        else:
            self.invalid = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attribute_names = [name.casefold() for name, _value in attrs]
        if len(attribute_names) != len(set(attribute_names)):
            self.invalid = True
            return
        attributes = dict(attrs)
        tag = tag.casefold()
        if tag in ("base", "template"):
            self.invalid = True
        elif tag == "html":
            self.html_start += 1
        elif tag == "head":
            self.head_start += 1
            self.in_head = True
        elif tag == "body":
            self.body_start += 1
            self.in_body = True
        elif tag == "div" and attributes.get("id") == "root" and self.in_body:
            self.root_mounts += 1
        elif tag == "script":
            self.script_start += 1
            if (
                not self.in_head
                or set(attribute_names) - {"type", "crossorigin", "src"}
                or (attributes.get("type") or "").casefold() != "module"
                or not attributes.get("src")
            ):
                self.invalid = True
            else:
                self.references.append((attributes["src"] or "", "module"))
        elif tag == "link" and attributes.get("href"):
            relationships = (attributes.get("rel") or "").casefold().split()
            if "stylesheet" in relationships:
                if (
                    not self.in_head
                    or set(attribute_names) - {"rel", "crossorigin", "href", "media"}
                ):
                    self.invalid = True
                else:
                    self.references.append((attributes["href"] or "", "stylesheet"))
        elif tag == "meta" and "http-equiv" in attributes:
            self.invalid = True

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() not in {
            "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
            "param", "source", "track", "wbr",
        }:
            self.invalid = True
            return
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "html":
            self.html_end += 1
        elif tag == "head":
            self.head_end += 1
            self.in_head = False
        elif tag == "body":
            self.body_end += 1
            self.in_body = False
        elif tag == "script":
            self.script_end += 1

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
BodyRowId = Annotated[
    int,
    Field(strict=True, ge=_SQLITE_INT_MIN, le=_SQLITE_INT_MAX),
]
BoundedToken = Annotated[str, Field(max_length=_LEN_TOKEN)]
BoundedName = Annotated[str, Field(max_length=_LEN_NAME)]


class CampaignIn(BaseModel):
    name: str = Field(max_length=_LEN_NAME)
    description: str = Field(default="", max_length=_LEN_NOTE)
    engagement_id: str = Field(default="", max_length=_LEN_NAME)


class ExpectedFamilyChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family: str = Field(min_length=1, max_length=_LEN_NAME)
    transitions: List[BoundedToken] = Field(min_length=1, max_length=9)
    subjects: List[BoundedName] = Field(default_factory=list, max_length=200)
    reason: str = Field(default="", max_length=_LEN_NOTE)
    intent_kind: Literal["", "revision_reset"] = ""


class ChangeIntentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_changes: List[ExpectedFamilyChangeIn] = Field(default_factory=list, max_length=200)
    note: str = Field(default="", max_length=_LEN_NOTE)


class L2FailureTrialIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pre_failure_snapshot_id: BodyRowId
    post_failure_snapshot_id: BodyRowId
    witness_json_base64: str = Field(min_length=1, max_length=90_000)


class CompareIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    old_id: BodyRowId
    new_id: BodyRowId
    change_intent: ChangeIntentIn | None = None
    l2_failure_trial: L2FailureTrialIn | None = None


class ExecutionCompareIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    after_snapshot_id: BodyRowId
    change_intent: ChangeIntentIn | None = None
    l2_failure_trial: L2FailureTrialIn | None = None


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

            # FastAPI/Pydantic normally receives an already-decoded mapping, which means duplicate
            # JSON member names have been silently collapsed before any route model can reject
            # them.  Comparison intent and snapshot identities are decision inputs, so the exact
            # bounded wire body must have one unambiguous interpretation.  Validate ordinary JSON
            # bodies here, while their original bytes still exist, then rewind for Starlette.  The
            # multipart snapshot-upload path retains its dedicated strict snapshot parser.
            content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if received and content_type == "application/json":
                raw_body = await run_in_threadpool(spool.read)
                try:
                    json.loads(
                        raw_body,
                        parse_constant=ingest.reject_nonfinite,
                        object_pairs_hook=_reject_duplicate_json_keys,
                    )
                except (UnicodeDecodeError, ValueError) as exc:
                    # Never reflect decoder/hook exception text.  The duplicate-key hook includes
                    # the attacker-supplied member name in its ValueError, and other decoder
                    # implementations may disclose parser internals.  Preserve the one useful,
                    # bounded reason without returning the exception itself.
                    detail = "Invalid JSON request body"
                    if (
                        isinstance(exc, ValueError)
                        and str(exc).startswith("duplicate JSON object key ")
                    ):
                        detail += ": duplicate JSON object key"
                    await JSONResponse(
                        {"detail": detail},
                        status_code=400,
                    )(scope, receive, send)
                    return
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


def _is_filesystem_link(path: Path) -> bool:
    """Identify symlinks/junctions; metadata uncertainty propagates to refuse the whole index."""
    junction_probe = getattr(path, "is_junction", None)
    attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return (
        path.is_symlink()
        or bool(junction_probe and junction_probe())
        or bool(reparse_flag and attributes & reparse_flag)
    )


def _frontend_stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_nlink,
    )


def _frontend_path_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    """Identity fields whose precision is stable across Windows handle/path stat APIs."""
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_nlink,
    )


def _frontend_census_identity(value: os.stat_result) -> tuple[int, ...]:
    """Exact path-stat fields used to reconcile the complete physical tree around reads."""
    return (
        *_frontend_stat_identity(value),
        value.st_mode,
        getattr(value, "st_file_attributes", 0),
    )


def _frontend_media_type(relative: str) -> str:
    suffix = PurePosixPath(relative).suffix.casefold()
    if suffix in _FRONTEND_PINNED_MEDIA_TYPES:
        return _FRONTEND_PINNED_MEDIA_TYPES[suffix]
    return mimetypes.guess_type(relative)[0] or "application/octet-stream"


def _read_frontend_file(path: Path, dist: Path) -> bytes | None:
    """Read twice through one bounded guarded handle, then revalidate its fixed path."""
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size < 0
            or before.st_size > _FRONTEND_MAX_FILE_BYTES
        ):
            return None

        def read_once() -> bytes:
            chunks: list[bytes] = []
            remaining = _FRONTEND_MAX_FILE_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            return b"".join(chunks)

        content = read_once()
        os.lseek(descriptor, 0, os.SEEK_SET)
        repeated = read_once()
        after = os.fstat(descriptor)
        current = os.stat(path, follow_symlinks=False)
        current_path = path.resolve(strict=True)
        if (
            len(content) != before.st_size
            or repeated != content
            or _frontend_stat_identity(after) != _frontend_stat_identity(before)
            or _frontend_path_identity(current) != _frontend_path_identity(before)
            or not stat.S_ISREG(current.st_mode)
            or current_path != path
            or not current_path.is_relative_to(dist)
        ):
            return None
        return content
    except (OSError, OverflowError, ValueError):
        return None
    finally:
        if descriptor is not None:
            with contextlib.suppress(OSError):
                os.close(descriptor)


def _frontend_tree_census(
    dist: Path,
) -> tuple[tuple[tuple[str, str, tuple[int, ...]], ...], tuple[tuple[str, Path], ...]] | None:
    """Return a bounded deterministic path/type/identity census plus canonical file members."""
    pending = [dist]
    records: list[tuple[str, str, tuple[int, ...]]] = []
    files: list[tuple[str, Path]] = []
    relative_files: set[str] = set()
    encountered = 0
    total_bytes = 0
    try:
        while pending:
            directory = pending.pop()
            if _is_filesystem_link(directory):
                return None
            current_directory = directory.resolve(strict=True)
            directory_stat = os.stat(directory, follow_symlinks=False)
            if (
                current_directory != directory
                or not current_directory.is_relative_to(dist)
                or not stat.S_ISDIR(directory_stat.st_mode)
            ):
                return None
            relative_directory = "." if directory == dist else directory.relative_to(dist).as_posix()
            records.append(
                ("directory", relative_directory, _frontend_census_identity(directory_stat))
            )

            entries = []
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    encountered += 1
                    if encountered > _FRONTEND_MAX_ENTRIES:
                        return None
                    entries.append(entry)

            child_directories = []
            for entry in sorted(entries, key=lambda item: item.name):
                candidate = directory / entry.name
                if _is_filesystem_link(candidate):
                    return None
                candidate_stat = os.stat(candidate, follow_symlinks=False)
                if stat.S_ISDIR(candidate_stat.st_mode):
                    child_directories.append(candidate)
                    continue
                if not stat.S_ISREG(candidate_stat.st_mode) or candidate_stat.st_nlink != 1:
                    return None
                if (
                    candidate_stat.st_size < 0
                    or candidate_stat.st_size > _FRONTEND_MAX_FILE_BYTES
                ):
                    return None
                resolved = candidate.resolve(strict=True)
                if resolved != candidate or not resolved.is_relative_to(dist):
                    return None
                relative = candidate.relative_to(dist).as_posix()
                if relative in relative_files or len(files) >= _FRONTEND_MAX_FILES:
                    return None
                relative_files.add(relative)
                total_bytes += candidate_stat.st_size
                if total_bytes > _FRONTEND_MAX_TOTAL_BYTES:
                    return None
                records.append(("file", relative, _frontend_census_identity(candidate_stat)))
                files.append((relative, candidate))
            pending.extend(reversed(child_directories))
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    return tuple(sorted(records)), tuple(sorted(files))


def _frontend_reference_key(value: str, mount: str = "/") -> str | None:
    """The startup-index key (``assets/...``) a shell reference names, or None when the reference is
    not a plain local asset under ``<mount>assets/``. ``mount`` is "/" for AssessHub's own SPA and
    ``_SCOPE_MOUNT`` for Atlas Scope."""
    if (
        not value
        or len(value) > 2_048
        or "\\" in value
        or "%" in value
        or any(ord(character) < 0x20 or ord(character) == 0x7f for character in value)
    ):
        return None
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        return None
    if (
        parsed.scheme
        or parsed.netloc
        or not parsed.path.startswith(mount + "assets/")
        or parsed.path.startswith("//")
    ):
        return None
    raw_path = parsed.path[len(mount):]
    segments = raw_path.split("/")
    if not segments or any(segment in ("", ".", "..") for segment in segments):
        return None
    path = PurePosixPath(*segments)
    if path.is_absolute():
        return None
    return path.as_posix()


def _frontend_shell_valid(indexed: dict[str, _FrontendFile]) -> bool:
    """Require one complete local Vite boot shell; presence-only readiness is not sufficient."""
    index_file = indexed.get("index.html")
    if index_file is None or not index_file.content or len(index_file.content) > _FRONTEND_MAX_FILE_BYTES:
        return False
    try:
        text = index_file.content.decode("utf-8", errors="strict")
        parser = _FrontendShellParser()
        parser.feed(text)
        parser.close()
    except (UnicodeDecodeError, ValueError):
        return False
    if (
        parser.invalid
        or parser.doctype != 1
        or parser.html_start != 1
        or parser.html_end != 1
        or parser.head_start != 1
        or parser.head_end != 1
        or parser.body_start != 1
        or parser.body_end != 1
        or parser.root_mounts != 1
        or parser.script_start != 1
        or parser.script_end != 1
        or parser.in_head
        or parser.in_body
    ):
        return False
    module_entries = 0
    for reference, kind in parser.references:
        key = _frontend_reference_key(reference)
        if key is None or key not in indexed or not indexed[key].content.strip():
            return False
        if kind in ("module", "script"):
            if (
                not key.casefold().endswith((".js", ".mjs"))
                or indexed[key].media_type != "text/javascript"
            ):
                return False
        elif not key.casefold().endswith(".css") or indexed[key].media_type != "text/css":
            return False
        if kind == "module":
            module_entries += 1
    return module_entries >= 1


def _frontend_file_index(dist_root: Path) -> tuple[Path, dict[str, _FrontendFile]] | None:
    """Snapshot bounded immutable SPA bytes under one trusted root before serving requests.

    Request text never enters filesystem handling. Enumeration rejects links, junctions, hard
    links, path escapes, races, partial walks, oversized members, and aggregate/file-count excess.
    """
    return _indexed_dist_tree(dist_root, _frontend_shell_valid)


# -- /scope markup: read the way a browser reads it, by construction ---------------------------------
# A /scope document is judged by the reading a BROWSER makes of it, never by a tokenizer that
# differs from the browser's (P3F-V2-1): the standard library's HTMLParser closes comments, raw-text
# elements and markup declarations differently from the WHATWG tokenizer (and differently again
# across Python releases), so a `<!-->` or a `</script x>` hid a `<meta name="referrer">` that a
# browser applies. Instead of modelling every error-recovery path of the WHATWG tokenizer, AssessHub
# accepts only markup in a RESTRICTED language on which its tokenization is the browser's by
# construction, and refuses everything else (`invalid_build`, never passed):
#
# * the text is UTF-8 with no NUL and no C0 control but TAB/LF/FF/CR (CR and CRLF become LF first,
#   as the browser's input-stream preprocessing does);
# * every `<` begins a complete token — `<!doctype html>`, a start tag, an end tag `</name>`, or a
#   conforming comment — never text; attribute values contain no `<` and only the character
#   references `&amp; &lt; &gt; &quot; &apos; &#39;`; comments contain no `</` and follow the HTML
#   standard's comment syntax (no leading `>`/`->`, no `<!--`, `-->` or `--!>` inside, no trailing
#   `<!-`); ASCII names; whitespace-separated attributes; no attribute twice (a browser keeps the
#   first); no `<![CDATA[`, `<?`, bogus comment or other markup declaration.
#
# In that language every `</` is an end-tag token, so whatever element a browser reads as raw text
# (script, style, title, textarea, xmp, iframe, noembed, noframes, noscript, plaintext, or any
# other), its raw text ends exactly at one of the reader's end tags, or never: the browser can only
# read LESS markup than this reader, never more. The reader therefore reads NO element as raw text,
# which also makes foreign content (svg/math, where those names do not switch the tokenizer) read
# the same. Every attribute a browser puts on an element it builds from such a document is one the
# reader read — proven differentially in real Chromium over a generated family (webapp/tests/
# test_scope_mount.py, "the browser is the oracle").
#
# That superset reading is sound ONLY for what must be ABSENT (a referrer declaration, a construct
# off the shell's accept-list): markup the browser reads as text cannot declare or load anything.
# It is unsound for what must be PRESENT — an icon in the shell's head, a module entry, the
# runtime-source declaration — since it would count an icon inside a <title>, which the browser
# reads as text and then requests /favicon.ico outside /scope (RQF-V2-1). So the shell is judged on
# ONE parse (_scope_shell_tokens) and only where that parse IS the browser's: every element the
# browser reads as raw text or RCDATA (_SCOPE_HTML_RAW_TEXT_ELEMENTS) closed by its own end tag with
# no `<` inside, no PLAINTEXT, and token lists and names read with the browser's ASCII rules
# (_scope_html_token_list, _scope_html_ascii_lower). No second tokenizer judges any of it.
#
# Which refusals carry that argument was MEASURED clause by clause (QF-R1-2): removing any one of the
# abrupt `<!-->` / `<!--->` openings, a `--!>` or `</` inside a comment, the control characters, a `<`
# inside a quoted value, an unknown character reference, a missing space between attributes, a
# repeated attribute, a non-ASCII-letter tag name or the CR normalisation lets a document through
# that a unit pin or the Chromium family shows is read differently. The rest are conformance, kept
# only to keep the language small — removing one changes no reading a browser makes: a comment that
# contains `<!--` or ends in `<!-` still ends at the same `-->` (the WHATWG nested-comment states
# reconsume into the comment-end state); every DOCTYPE and end-tag state ends at the first `>`
# outside quotes, so a laxer doctype or end tag can only let the BROWSER hide more; and an `&` in an
# unquoted value still meets the character-reference rule.
#
# XML-typed members (SVG, XHTML, any */xml or *+xml type, text/xsl — _scope_markup_kind) are NOT
# read at all: every one is refused (_SCOPE_REFUSED_XML), whatever it holds (QF-V2-1). No XML reader
# available here reads one the way the browser does — with an external DOCTYPE, expat silently DROPS
# an undefined entity reference inside an attribute value, while Blink expands the whole HTML
# named-entity table for the XHTML and MathML public identifiers (`rel="noopener&Tab;noreferrer"`:
# "noopenernoreferrer" to expat, "noopener noreferrer" to Chromium), and which parser Blink uses for
# XML is itself a browser implementation choice. The hub build ships no XML-typed member (measured:
# `npm run build:hub` emits index.html, JavaScript and CSS; pinned by
# test_the_hub_build_ships_no_xml_document), so refusing them costs nothing and closes the class
# by construction: nothing is judged by a tokenizer that differs from the browser's, because nothing
# XML is judged. A build that one day needs an XML document brings a reader proven against the
# browser, not a reopening of this rule.
#
# The SHELL is held to more than readability (QF-V2-3): every construct in it must be on a closed
# ACCEPT-list (_SCOPE_SHELL_ELEMENTS and the rules in _scope_shell_refusal), so "every URL the shell
# loads is a startup-indexed /scope asset" holds by construction — not by a list of URL-bearing
# attributes, which a `table background`, an SVG `xlink:href` or a `style` url() walked past. The
# accept-list admits only elements that load nothing, attributes that load nothing, a `style` whose
# declarations cannot name a resource, `<script type=module src>` / `<link rel=stylesheet|
# modulepreload|icon href>` naming a startup-indexed asset (an icon may be a `data:image/` URL), and
# the one inline classic script whose exact text is pinned (_SCOPE_SHELL_INLINE_SCRIPTS). Because
# the browser reads no more markup than the reader does (above), every attributed element a browser
# builds from an accepted shell is one this list admitted. The shell must also declare an icon IN
# ITS HEAD: without one -- or with one the browser meets only after the head has ended, or never
# builds at all (inside a title, behind a non-ASCII blank in its `rel`) -- the browser requests the
# origin's /favicon.ico, a load no attribute names (RQF-V1-4, RQF-V2-1); that presence is judged on
# the shell's exact reading above. The stylesheets it links are held to the /scope CSS accept-list
# (_scope_css_refusal, RQF-V1-3), so they name no resource either. Proven in real Chromium with
# request interception and a recording proxy -- which also sees the browser's own favicon request
# -- over a generated family of every URL-bearing construct enumerated there, in markup and in CSS,
# and of icons in every position the browser builds none; and every element the shell reading of a
# served-ready shell holds is shown to be one Chromium built.
#
# The shell is the ONLY HTML page served under /scope: any other HTML member is refused, whatever it
# holds (_SCOPE_REFUSED_HTML_PAGE, RQF-V1-6) -- the hub build ships none, and a page not held to the
# shell's accept-list could load anything. What the admitted first-party module entry does when it
# runs is its code's behaviour, not markup or CSS, and is not judged here.

@dataclass(frozen=True)
class _ScopeMarkupElement:
    """One element as a browser reads it: its lower-cased (local) name and its attributes, each a
    lower-cased (local) name and its decoded value, in source order. ``text`` is the character data
    from the end of its start tag to the next ``<``, and ``closed`` says whether that ``<`` begins
    this element's own end tag — so an element whose content is exactly ``text`` is recognisable
    (the shell's inline script). Neither takes part in comparison."""
    name: str
    attributes: tuple[tuple[str, str], ...]
    text: str = field(default="", compare=False)
    closed: bool = field(default=False, compare=False)


@dataclass(frozen=True)
class _ScopeMarkupEndTag:
    """One end tag as the reader reads it: its lower-cased name."""
    name: str


#: One token of the restricted language, in source order: a start tag (an element), an end tag, or
#: a run of character data (a str). Comments and the doctype are read and dropped.
_ScopeMarkupToken = "_ScopeMarkupElement | _ScopeMarkupEndTag | str"

#: The elements the WHATWG tree builder switches the tokenizer out of the data state for, so that a
#: browser reads their content as TEXT, not markup: RCDATA (title, textarea), RAWTEXT (style, xmp,
#: iframe, noembed, noframes, and noscript where scripting is enabled), script data (script) and
#: PLAINTEXT (plaintext, which never ends). The reader reads markup inside them -- a superset of the
#: browser's reading, sound for what must be ABSENT -- so a POSITIVE requirement is judged only on a
#: shell where each one is closed with no `<` inside (_scope_raw_text_misread, RQF-V2-1). Measured,
#: not trusted: over every element name parse5 knows, every element the shell may carry under which
#: Chromium hides markup must be one of these
#: (test_every_element_the_shell_may_carry_that_hides_markup_in_chromium_is_read_exactly).
_SCOPE_HTML_RAW_TEXT_ELEMENTS = frozenset({"script", "style", "title", "textarea", "xmp", "iframe",
                                           "noembed", "noframes", "noscript", "plaintext"})


_SCOPE_HTML_FORBIDDEN_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0e-\x1f]")
_SCOPE_HTML_DOCTYPE = re.compile(r"<!doctype[\t\n\f ]+html[\t\n\f ]*>", re.IGNORECASE)
_SCOPE_HTML_END_TAG = re.compile(r"</([A-Za-z][A-Za-z0-9-]*)[\t\n\f ]*>")
_SCOPE_HTML_ATTRIBUTE_RE = re.compile(
    r"[\t\n\f ]+([A-Za-z_:][A-Za-z0-9_:.-]*)"
    r"(?:[\t\n\f ]*=[\t\n\f ]*(?:\"([^\"<]*)\"|'([^'<]*)'|([^\t\n\f \"'=<>`&]+)))?")
_SCOPE_HTML_START_TAG = re.compile(
    r"<([A-Za-z][A-Za-z0-9-]*)"
    r"((?:[\t\n\f ]+[A-Za-z_:][A-Za-z0-9_:.-]*"
    r"(?:[\t\n\f ]*=[\t\n\f ]*(?:\"[^\"<]*\"|'[^'<]*'|[^\t\n\f \"'=<>`&]+))?)*)"
    r"[\t\n\f ]*/?>")
_SCOPE_HTML_REFERENCE = re.compile(r"&(?:(amp|lt|gt|quot|apos);|#39;)?")
_SCOPE_HTML_REFERENCE_TEXT = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}


def _scope_html_attribute_value(raw: str) -> str | None:
    """The value a browser decodes from ``raw``, or None when ``raw`` carries a character reference
    outside the few this reader decodes exactly as the WHATWG tokenizer does."""
    decoded, position = [], 0
    for match in _SCOPE_HTML_REFERENCE.finditer(raw):
        if match.group(0) == "&":
            return None
        decoded.append(raw[position:match.start()])
        decoded.append(_SCOPE_HTML_REFERENCE_TEXT[match.group(1)] if match.group(1) else "'")
        position = match.end()
    decoded.append(raw[position:])
    return "".join(decoded)


def _scope_html_comment_end(text: str, start: int) -> int | None:
    """The index after the conforming comment opening at ``start`` (``<!--``), or None."""
    end = text.find("-->", start + 4)
    if end < 0:
        return None
    data = text[start + 4:end]
    if (data.startswith((">", "->")) or data.endswith("<!-")
            or any(forbidden in data for forbidden in ("<!--", "--!>", "</"))):
        return None
    return end + 3


def _scope_html_reading(text: str) -> tuple[_ScopeMarkupElement, ...] | None:
    """Every element (start tag) of an HTML document in source order, read as a browser reads it —
    or None when the document is not in the restricted language above, which is refused."""
    tokens = _scope_html_tokens(text)
    return None if tokens is None else _scope_markup_elements(tokens)


def _scope_markup_elements(tokens) -> tuple[_ScopeMarkupElement, ...]:
    return tuple(token for token in tokens if isinstance(token, _ScopeMarkupElement))


def _scope_html_tokens(text: str) -> "tuple[_ScopeMarkupToken, ...] | None":
    """Every token of an HTML document in source order as the reader reads it -- start tags
    (elements), end tags and character data, the ONE parse every /scope markup judgement is made
    on -- or None when the document is not in the restricted language above, which is refused."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if _SCOPE_HTML_FORBIDDEN_CHARACTERS.search(text):
        return None
    tokens: list = []
    position, length = 0, len(text)
    while position < length:
        opening = text.find("<", position)
        if opening < 0:
            tokens.append(text[position:])
            break
        if opening > position:
            tokens.append(text[position:opening])
        if text.startswith("<!--", opening):
            end = _scope_html_comment_end(text, opening)
            if end is None:
                return None
            position = end
            continue
        token = _SCOPE_HTML_DOCTYPE.match(text, opening)
        if token is not None:
            position = token.end()
            continue
        token = _SCOPE_HTML_END_TAG.match(text, opening)
        if token is not None:
            tokens.append(_ScopeMarkupEndTag(token.group(1).lower()))
            position = token.end()
            continue
        match = _SCOPE_HTML_START_TAG.match(text, opening)
        if match is None:
            return None
        attributes = []
        for attribute in _SCOPE_HTML_ATTRIBUTE_RE.finditer(match.group(2)):
            raw = next((v for v in attribute.group(2, 3, 4) if v is not None), "")
            value = _scope_html_attribute_value(raw)
            if value is None:
                return None
            attributes.append((attribute.group(1).lower(), value))
        if len({name for name, _value in attributes}) != len(attributes):
            return None  # a browser keeps the FIRST of a repeated attribute
        name = match.group(1).lower()
        following = text.find("<", match.end())
        following = length if following < 0 else following
        end_tag = _SCOPE_HTML_END_TAG.match(text, following)
        tokens.append(_ScopeMarkupElement(
            name, tuple(attributes), text=text[match.end():following],
            closed=end_tag is not None and end_tag.group(1).lower() == name))
        position = match.end()
    return tuple(tokens)


#: Why a /scope member or shell is refused. Every refusal carries its reason (tests hold each
#: generated member to the reason it is refused for), and none is ever passed.
_SCOPE_REFUSED_XML = ("an XML document (SVG, XHTML or any */xml, *+xml or XSL type): the hub build "
                      "ships none, and AssessHub reads none, since no XML reader here reads one the "
                      "way the browser does (QF-V2-1)")
_SCOPE_REFUSED_HTML_PAGE = ("an HTML page other than the shell: the hub build ships none, and "
                            "AssessHub serves none, since nothing holds a page's loads and "
                            "declarations to the shell's accept-list (RQF-V1-6)")
_SCOPE_REFUSED_HTML = ("markup outside the restricted HTML language the /scope reader reads exactly "
                       "as a browser does")
_SCOPE_REFUSED_REFERRER = "a document that declares its own referrer policy (R8-V2-1)"
_SCOPE_REFUSED_UTF8 = "a document that is not UTF-8"
_SCOPE_REFUSED_CSS = "a stylesheet outside the /scope CSS accept-list (RQF-V1-3)"


def _scope_markup_kind(media_type: str) -> Literal["html", "xml"] | None:
    """How a browser renders a member served as ``media_type``: as HTML (text/html), as XML (the
    MIME Sniffing standard's XML MIME types — any */xml or *+xml — plus text/xsl, which Blink also
    renders as XML), or not as markup at all. Measured against Chromium over every media type the
    served registry assigns (test_every_media_type_chromium_renders_as_markup_is_read_as_markup)."""
    essence = media_type.split(";", 1)[0].strip().lower()
    if essence == "text/html":
        return "html"
    subtype = essence.partition("/")[2]
    if subtype == "xml" or subtype.endswith("+xml") or essence == "text/xsl":
        return "xml"
    return None


def _scope_document_reading(content: bytes,
                            media_type: str) -> tuple[_ScopeMarkupElement, ...] | None:
    """A served member's elements as a browser reads them: ``()`` for a member a browser does not
    render as markup, the elements of an HTML document, or None when the document is not read here
    the way a browser reads it — every XML document, and HTML outside the restricted language —
    which is refused, never passed."""
    kind = _scope_markup_kind(media_type)
    if kind is None:
        return ()
    if kind == "xml":
        return None
    try:
        return _scope_html_reading(content.decode("utf-8", errors="strict"))
    except UnicodeDecodeError:
        return None


def _scope_reading_declares_referrer_policy(elements: tuple[_ScopeMarkupElement, ...]) -> bool:
    """Whether a document declares its OWN referrer policy (R8-V2-1). Every /scope response carries
    `Referrer-Policy: same-origin`, which the /api guard's same-origin write containment
    (_referred_from_scope) relies on; a document-level declaration overrides it. The server's header
    is the one owner of the policy, so ANY declaration is refused, whatever its value: a
    `<meta name="referrer">`, a `referrerpolicy` attribute on any element, the `noreferrer` link type
    on any element (a form or followed link carrying it sends NO Referer), and a nested document the
    page declares itself (`srcdoc`, whose own markup the server serves no header for)."""
    for element in elements:
        for name, value in element.attributes:
            if (name in ("referrerpolicy", "srcdoc")
                    or (name == "rel" and "noreferrer" in value.casefold().split())
                    or (element.name == "meta" and name == "name"
                        and value.strip(" \t\n\f\r").casefold() == "referrer")):
                return True
    return False


def _scope_html_refusal(content: bytes) -> str | None:
    """The markup reader's own verdict on an HTML document -- the first gate the shell passes
    (_scope_shell_reading): not UTF-8, outside the restricted language, or declaring its own
    referrer policy; None when the reader reads it exactly as a browser does and it declares none."""
    try:
        elements = _scope_html_reading(content.decode("utf-8", errors="strict"))
    except UnicodeDecodeError:
        return _SCOPE_REFUSED_UTF8
    if elements is None:
        return _SCOPE_REFUSED_HTML
    return _SCOPE_REFUSED_REFERRER if _scope_reading_declares_referrer_policy(elements) else None


# -- the /scope CSS accept-list (RQF-V1-3) --------------------------------------------------------
# The shell links startup-indexed stylesheets, and a stylesheet loads what it names: `@import`,
# `url()`, `image-set()` and every other resource function fetch exactly as they would from a
# <style> element the shell may not carry (measured in Chromium: a linked stylesheet's @import and
# url() both request a third-party URL). So every text/css member -- linked or not; the browser
# applies only text/css as a stylesheet under `nosniff` -- is held to a closed ACCEPT-list whose
# reading is the browser's by construction:
#
# * UTF-8 (a UTF-8 BOM is dropped, as the browser drops it; the response says charset=utf-8, and a
#   UTF-16 BOM, which would override that, is not UTF-8) and no NUL; an escape outside a string is
#   read DECODED, as the browser reads the name it spells (`u\72l(` is url, `@\69mport` is
#   @import; the hub build's `[data-badge=INVALID\ INPUT]` is two plain words);
# * every comment is closed and every string ends on its own line with its own quote, read with
#   the CSS tokenizer's escapes (an escaped quote does not end it); a line feed inside a string, an
#   escaped line feed and a hex escape before a line feed -- where a bad-string or a swallowed line
#   feed could move the browser's string end -- are refused (_scope_css_string_end). So what lies
#   in comments and strings -- which name nothing unless a function or at-rule uses them -- is
#   exactly what the browser skips (the hub build's one string escape, `content:"\b7"`, is read);
# * outside comments and strings, every at-rule is one of _SCOPE_CSS_AT_RULES (conditions, names and
#   layers: none has a URL prelude, so no @import, @font-face or @namespace), every function is one
#   of _SCOPE_CSS_FUNCTIONS (none fetches: no url, src, image-set, image, cross-fade or element), and
#   the word `url` itself never appears -- so no declaration in the sheet can name a resource.
#
# A function name is read as the longest run of name characters before `(`: where the browser
# reads a different token (`#url(` is a hash then a parenthesis, `2url(` a dimension) the reader
# only refuses MORE. Names are matched ASCII case-insensitively, as the browser matches them.
# Proven in real Chromium with request interception over a generated family of every resource-naming
# construct (webapp/tests/test_scope_mount.py), the hub build's own stylesheets as the inert half.
_SCOPE_CSS_AT_RULES = frozenset({"media", "supports", "container", "keyframes", "layer", "property"})
_SCOPE_CSS_FUNCTIONS = frozenset({
    # values and colours
    "var", "calc", "min", "max", "clamp", "env", "attr", "round", "abs", "sign", "mod", "rem",
    "rgb", "rgba", "hsl", "hsla", "hwb", "lab", "lch", "oklab", "oklch", "color", "color-mix",
    "light-dark", "counter", "counters",
    # gradients, shapes, transforms, filters and timing -- drawn, never fetched
    "linear-gradient", "radial-gradient", "conic-gradient", "repeating-linear-gradient",
    "repeating-radial-gradient", "repeating-conic-gradient", "inset", "circle", "ellipse", "polygon",
    "translate", "translatex", "translatey", "translatez", "translate3d", "rotate", "rotatex",
    "rotatey", "rotatez", "rotate3d", "scale", "scalex", "scaley", "scalez", "scale3d", "skew",
    "skewx", "skewy", "matrix", "matrix3d", "perspective", "blur", "brightness", "contrast",
    "drop-shadow", "grayscale", "hue-rotate", "invert", "opacity", "saturate", "sepia",
    "cubic-bezier", "steps",
    # grid track sizing
    "minmax", "repeat", "fit-content",
    # selectors
    "not", "is", "where", "has", "nth-child", "nth-last-child", "nth-of-type", "nth-last-of-type",
    "lang", "dir",
})
_SCOPE_CSS_NAME = r"[-A-Za-z0-9_\u0080-\U0010ffff]+"
_SCOPE_CSS_FUNCTION = re.compile(rf"({_SCOPE_CSS_NAME})\(")
_SCOPE_CSS_AT_RULE = re.compile(rf"@({_SCOPE_CSS_NAME})?")
_SCOPE_CSS_WORD = re.compile(_SCOPE_CSS_NAME)


def _scope_css_name(name: str) -> str:
    """A CSS name as the browser compares it: ASCII case-insensitively (a non-ASCII name is never
    one of the accept-list's ASCII names)."""
    return name.lower() if name.isascii() else name


_SCOPE_CSS_HEX_ESCAPE = re.compile(r"[0-9A-Fa-f]{1,6}")


def _scope_css_string_end(text: str, start: int) -> int | None:
    """The index after the CSS string opening at ``start`` (its quote), read as the CSS tokenizer
    reads it -- or None where the reading could differ: a line feed before the closing quote (a
    bad-string), a backslash before a line feed (a continuation) or at the end, a hexadecimal
    escape followed by a line feed (the escape would swallow it), or no closing quote at all. An
    escape consumes its hex digits, or the one character after the backslash (an escaped quote
    does not end the string)."""
    quote, position = text[start], start + 1
    while position < len(text):
        character = text[position]
        if character == quote:
            return position + 1
        if character == "\n":
            return None
        if character == "\\":
            following = text[position + 1:position + 2]
            if following in ("", "\n"):
                return None
            digits = _SCOPE_CSS_HEX_ESCAPE.match(text, position + 1)
            if digits is not None:
                position = digits.end()
                if text[position:position + 1] == "\n":
                    return None
                continue
            position += 2
            continue
        position += 1
    return None


def _scope_css_refusal(content: bytes) -> str | None:
    """Why a stylesheet is refused, or None when it is on the /scope CSS accept-list above."""
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return f"{_SCOPE_REFUSED_CSS}: not UTF-8"
    text = text[1:] if text.startswith("﻿") else text
    if "\x00" in text:
        return f"{_SCOPE_REFUSED_CSS}: a NUL"
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n")
    code, position = [], 0
    while position < len(text):
        character = text[position]
        if text.startswith("/*", position):
            end = text.find("*/", position + 2)
            if end < 0:
                return f"{_SCOPE_REFUSED_CSS}: an unclosed comment"
            code.append(" ")
            position = end + 2
        elif character in "\"'":
            end = _scope_css_string_end(text, position)
            if end is None:
                return f"{_SCOPE_REFUSED_CSS}: a string that does not end on its own line"
            code.append(" ")
            position = end
        elif character == "\\":
            # an escape outside a string is part of a name: read it DECODED, as the browser reads
            # the name it spells (`u\72l(` is the function url, `@\69mport` the at-rule import).
            # Decoding can only make the reader see more names than the browser does, never fewer.
            following = text[position + 1:position + 2]
            if following in ("", "\n"):
                return f"{_SCOPE_REFUSED_CSS}: a backslash that escapes nothing"
            digits = _SCOPE_CSS_HEX_ESCAPE.match(text, position + 1)
            if digits is None:
                code.append(following)
                position += 2
            else:
                value = int(digits.group(0), 16)
                code.append(chr(value) if 0 < value <= 0x10FFFF and not 0xD800 <= value <= 0xDFFF
                            else "�")
                position = digits.end()
                if text[position:position + 1] in (" ", "\t", "\n"):
                    position += 1  # the one blank that ends a hexadecimal escape
        else:
            code.append(character)
            position += 1
    code_text = "".join(code)
    for match in _SCOPE_CSS_AT_RULE.finditer(code_text):
        if _scope_css_name(match.group(1) or "") not in _SCOPE_CSS_AT_RULES:
            return f"{_SCOPE_REFUSED_CSS}: the at-rule @{match.group(1) or ''}"
    for match in _SCOPE_CSS_FUNCTION.finditer(code_text):
        if _scope_css_name(match.group(1)) not in _SCOPE_CSS_FUNCTIONS:
            return f"{_SCOPE_REFUSED_CSS}: the function {match.group(1)}()"
    if any(_scope_css_name(word) == "url" for word in _SCOPE_CSS_WORD.findall(code_text)):
        return f"{_SCOPE_REFUSED_CSS}: the word url"
    return None


def _scope_document_refusal(content: bytes, media_type: str) -> str | None:
    """Why one served member OTHER than the shell is refused, or None when it is not: any document
    a browser renders as markup (_scope_markup_kind) -- an XML document (QF-V2-1) or an HTML page
    (RQF-V1-6), neither of which the hub build ships -- and any stylesheet outside the /scope CSS
    accept-list (RQF-V1-3). What was not read is refused, never passed."""
    if media_type.split(";", 1)[0].strip().lower() == "text/css":
        return _scope_css_refusal(content)
    kind = _scope_markup_kind(media_type)
    if kind is None:
        return None
    return _SCOPE_REFUSED_XML if kind == "xml" else _SCOPE_REFUSED_HTML_PAGE


_SCOPE_HTML_ASCII_WHITESPACE = re.compile(r"[\t\n\f\r ]+")
_SCOPE_HTML_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def _scope_html_ascii_lower(value: str) -> str:
    """``value`` lower-cased the way a browser compares ASCII case-insensitively: ASCII letters
    only (Python's lower()/casefold() also fold U+212A KELVIN SIGN to `k` and U+017F LONG S to `s`,
    which a browser never matches)."""
    return value.translate(_SCOPE_HTML_ASCII_LOWER)


def _scope_html_token_list(value: str) -> list[str]:
    """A token-list attribute (`rel`) as a browser reads it: split on ASCII whitespace ONLY, each
    token ASCII-lower-cased. Python's str.split() also splits on U+00A0, U+3000, U+0085 and every
    other Unicode blank, so `rel="icon&#xA0;"` read that way is an icon a browser never sees
    (measured in Chromium: it requests /favicon.ico; RQF-V2-1)."""
    return [token for token in _SCOPE_HTML_ASCII_WHITESPACE.split(_scope_html_ascii_lower(value))
            if token]


def _scope_raw_text_misread(elements: tuple[_ScopeMarkupElement, ...]) -> str | None:
    """The first element the browser reads as raw text or RCDATA whose content the reader would
    read differently (RQF-V2-1), or None. The reader reads markup inside such an element; the
    browser reads text up to the element's own end tag (PLAINTEXT: to the end of the document). So
    the reading is the browser's EXACTLY only when each such element is closed by its own end tag
    with no `<` before it -- in this language that end tag is where the browser's raw text ends too
    -- and no PLAINTEXT element occurs."""
    for element in elements:
        if element.name in _SCOPE_HTML_RAW_TEXT_ELEMENTS and (
                element.name == "plaintext" or not element.closed):
            return element.name
    return None


def _scope_shell_tokens(content: bytes) -> "tuple[_ScopeMarkupToken, ...] | str":
    """The shell's tokens, read EXACTLY as a browser reads them, or why it cannot be (a str).

    The shell's requirements are not only absences: an icon in the head, a module entry and the
    runtime-source declaration must be PRESENT, and a reading that holds more markup than the
    browser's (the reader's, by design) would count an icon inside a <title> that the browser reads
    as text -- served ready while the browser requests /favicon.ico outside /scope (RQF-V2-1). So
    the shell is judged only where the two readings are one: readable, every raw-text/RCDATA
    element closed with no `<` inside (_scope_raw_text_misread), no referrer policy, no <base>, no
    http-equiv pragma, and the runtime snapshot source declared exactly once."""
    try:
        tokens = _scope_html_tokens(content.decode("utf-8", errors="strict"))
    except UnicodeDecodeError:
        return "the shell is not UTF-8"
    if tokens is None:
        return "the shell is not markup in the restricted language the reader reads exactly"
    elements = _scope_markup_elements(tokens)
    misread = _scope_raw_text_misread(elements)
    if misread is not None:
        return (f"a <{misread}> holds markup a browser reads as raw text (or never ends), so the "
                "shell is not read as the browser reads it")
    if _scope_reading_declares_referrer_policy(elements):
        return "the shell declares its own referrer policy"
    runtime_sources = []
    for element in elements:
        attributes = dict(element.attributes)
        if element.name == "base" or (element.name == "meta" and "http-equiv" in attributes):
            return "the shell declares a <base> or an http-equiv pragma"
        if (element.name == "meta"
                and _scope_html_ascii_lower(attributes.get("name", "")) == _SCOPE_RUNTIME_SOURCE_META):
            runtime_sources.append(attributes.get("content", ""))
    if runtime_sources != [_SCOPE_RUNTIME_SOURCE_VALUE]:
        return "the shell does not declare the runtime snapshot source exactly once"
    return tokens


def _scope_shell_reading(content: bytes) -> tuple[_ScopeMarkupElement, ...] | None:
    """The shell's elements, read exactly as a browser reads them, when it can be judged at all
    (_scope_shell_tokens); else None."""
    tokens = _scope_shell_tokens(content)
    return None if isinstance(tokens, str) else _scope_markup_elements(tokens)


#: The shell's closed ACCEPT-list (QF-V2-3): the only elements it may carry, each with the
#: attributes it may carry beyond the global ones below. None of these elements loads anything by
#: itself; `script` and `link` load only what _scope_shell_refusal admits. Anything else — an img, a
#: table, an svg, a style element, an iframe, an event handler, a srcset, a background — is refused
#: as a construct the list does not name, whatever URL it would load.
_SCOPE_SHELL_ELEMENTS: dict[str, frozenset[str]] = {
    "html": frozenset(), "head": frozenset(), "body": frozenset(), "title": frozenset(),
    "div": frozenset(), "p": frozenset(), "span": frozenset(),
    "meta": frozenset({"charset", "name", "content"}),
    "link": frozenset({"rel", "href", "crossorigin"}),
    "script": frozenset({"type", "crossorigin", "src"}),
}
#: Attributes no browser loads anything from, admitted on every accepted element; `style` is
#: admitted only when its declarations cannot name a resource (_scope_shell_style_is_inert).
_SCOPE_SHELL_GLOBAL_ATTRIBUTES = frozenset({"id", "class", "lang", "dir", "title", "role", "hidden",
                                            "translate", "elementtiming", "style"})
_SCOPE_SHELL_ATTRIBUTE_FAMILY = re.compile(r"(?:aria|data)-[a-z0-9-]+")
#: The link relations the shell may declare, and the media type the named asset must be served as
#: (None: an icon, which may also be an inline `data:image/` URL — an image context loads nothing).
_SCOPE_SHELL_LINK_RELATIONS: dict[str, str | None] = {
    "stylesheet": "text/css", "modulepreload": "text/javascript", "icon": None}
#: A style attribute is admitted only in this character set — no quote (so no string, hence no
#: image-set("…")), no backslash (so no escape spelling `url`), no `*` (so no comment splitting a
#: name), no `@`, `{`, `}`, `<`, `&` or `!` — and every function it calls must be one of these, none
#: of which fetches: `url(`, `image-set(`, `image(`, `src(` and every other resource function are
#: absent, so no declaration in it can name a resource.
_SCOPE_SHELL_STYLE_CHARACTERS = re.compile(r"[A-Za-z0-9 \t\n.,:;%#/()+-]*")
_SCOPE_SHELL_STYLE_CALL = re.compile(r"([A-Za-z_-][A-Za-z0-9_-]*)?\(")
_SCOPE_SHELL_STYLE_FUNCTIONS = frozenset({"var", "calc", "min", "max", "clamp", "rgb", "rgba",
                                          "hsl", "hsla"})
#: The sha256 of the one inline classic script the shell may carry: atlas-scope/index.html's theme
#: boot, which Vite copies verbatim into the hub shell (reviewed: it reads localStorage and sets one
#: attribute; it loads nothing). Any other inline script — or this one edited — can load a URL the
#: reader cannot see, and is refused. Pinned to the source shell by
#: test_the_hub_shells_inline_script_is_the_one_the_reader_pins: change the two together.
_SCOPE_SHELL_INLINE_SCRIPTS = frozenset({
    "02fdc8517dab83c32172187a06b8e9c0183a4a4781a2840018250f4fbf5efeb0"})


def _scope_shell_style_is_inert(value: str) -> bool:
    """Whether a style attribute's declarations cannot name a resource (see the character set and
    function list above)."""
    if not _SCOPE_SHELL_STYLE_CHARACTERS.fullmatch(value):
        return False
    return all((call.group(1) or "").casefold() in _SCOPE_SHELL_STYLE_FUNCTIONS | {""}
               for call in _SCOPE_SHELL_STYLE_CALL.finditer(value))


#: The elements a browser keeps IN the head (under the shell accept-list); any other element, any
#: non-blank character data outside a title or script, or an end tag other than the one closing an
#: open title or script, ends the head -- and the head is where an icon must be declared.
_SCOPE_SHELL_HEAD_ELEMENTS = frozenset({"html", "head", "title", "meta", "link", "script"})


def _scope_shell_declares_an_icon_in_its_head(tokens: "tuple[_ScopeMarkupToken, ...]") -> bool:
    """Whether the shell's first `<link rel=icon>` comes before anything that ends the head.

    RQF-V1-4, measured in Chromium (full headless, per-case origins): with no icon, and also with an
    icon declared only AFTER the head has ended (behind body text, a <p>, a </head><body>), the
    browser requests the origin's /favicon.ico -- outside /scope -- before it sees the late icon.
    ``tokens`` is the shell's ONE parse (_scope_shell_tokens), which is the browser's reading
    exactly: no raw-text or RCDATA element in it holds a `<` (RQF-V2-1 -- an icon inside a <title>
    is text to the browser, and was counted here by a second tokenizer that read it as markup). The
    head ends at the first token the list above does not keep in it, which only makes this rule
    refuse MORE than the browser needs."""
    open_raw_text = None
    for token in tokens:
        if isinstance(token, str):
            if open_raw_text is None and token.strip("\t\n\f "):
                return False  # character data in the head starts the body
        elif isinstance(token, _ScopeMarkupEndTag):
            if token.name != open_raw_text:
                return False
            open_raw_text = None
        else:
            if open_raw_text is not None or token.name not in _SCOPE_SHELL_HEAD_ELEMENTS:
                return False
            if token.name == "link" and _scope_html_token_list(
                    dict(token.attributes).get("rel", "")) == ["icon"]:
                return True
            open_raw_text = token.name if token.name in _SCOPE_HTML_RAW_TEXT_ELEMENTS else None
    return False


def _scope_shell_asset(reference: str, indexed: dict[str, _FrontendFile],
                       media_type: str | None) -> bool:
    """Whether ``reference`` names a non-empty startup-indexed asset under /scope/assets/ (served
    as ``media_type``, when one is required)."""
    key = _frontend_reference_key(reference, _SCOPE_MOUNT)
    return (key is not None and key in indexed and bool(indexed[key].content.strip())
            and (media_type is None or indexed[key].media_type == media_type))


def _scope_shell_refusal(indexed: dict[str, _FrontendFile]) -> str | None:
    """Why the build's shell is not a servable /scope shell, or None when it is. It must be readable
    markup built FOR the /scope mount that declares the runtime-snapshot source contract
    (_scope_shell_reading), and every construct in it must be on the closed accept-list above, so
    that every URL it loads is a startup-indexed /scope asset by construction (QF-V2-3). A Vite
    build with the default base loads ``/assets/...`` — AssessHub's own asset namespace — and would
    render as a broken page; a build without the declaration may show compiled-in evidence under a
    snapshot URL it does not belong to."""
    index_file = indexed.get("index.html")
    if index_file is None or not index_file.content:
        return "the build has no index.html"
    tokens = _scope_shell_tokens(index_file.content)
    if isinstance(tokens, str):
        return tokens
    elements = _scope_markup_elements(tokens)
    module_entries = icons = 0
    for element in elements:
        allowed = _SCOPE_SHELL_ELEMENTS.get(element.name)
        if allowed is None:
            return f"<{element.name}> is not an element the shell may carry"
        attributes = dict(element.attributes)
        for name in attributes:
            if not (name in allowed or name in _SCOPE_SHELL_GLOBAL_ATTRIBUTES
                    or _SCOPE_SHELL_ATTRIBUTE_FAMILY.fullmatch(name)):
                return f"<{element.name} {name}> is not an attribute the shell may carry"
        if "style" in attributes and not _scope_shell_style_is_inert(attributes["style"]):
            return f"<{element.name} style> can name a resource"
        if element.name == "link":
            relations = _scope_html_token_list(attributes.get("rel", ""))
            if len(relations) != 1 or relations[0] not in _SCOPE_SHELL_LINK_RELATIONS:
                return f"<link rel={attributes.get('rel', '')!r}> is not a relation the shell may declare"
            href = attributes.get("href", "")
            if not ((relations[0] == "icon" and href.startswith("data:image/"))
                    or _scope_shell_asset(href, indexed, _SCOPE_SHELL_LINK_RELATIONS[relations[0]])):
                return f"<link href={href!r}> is not a startup-indexed /scope asset of its kind"
            icons += relations[0] == "icon"
        elif element.name == "script":
            if "src" in attributes:
                if _scope_html_ascii_lower(attributes.get("type", "")) != "module":
                    return "a <script src> that is not a module entry"
                if not element.closed or element.text.strip():
                    return "a <script src> with content of its own"
                if not _scope_shell_asset(attributes["src"], indexed, "text/javascript"):
                    return f"<script src={attributes['src']!r}> is not a startup-indexed /scope module"
                module_entries += 1
            elif attributes or not element.closed or hashlib.sha256(
                    element.text.encode("utf-8")).hexdigest() not in _SCOPE_SHELL_INLINE_SCRIPTS:
                return "an inline <script> other than the one whose exact text the reader pins"
    if not icons or not _scope_shell_declares_an_icon_in_its_head(tokens):
        # RQF-V1-4: with no icon in the head, a browser requests the origin's /favicon.ico by
        # default -- outside /scope, a load no attribute names (measured in Chromium)
        return "the shell declares no <link rel=icon> in its head, so a browser requests /favicon.ico"
    return None if module_entries >= 1 else "the shell loads no module entry"


def _scope_shell_valid(indexed: dict[str, _FrontendFile]) -> bool:
    """A scope shell is servable only when _scope_shell_refusal finds nothing to refuse."""
    return _scope_shell_refusal(indexed) is None


def _scope_engine_projection_declared(indexed: dict[str, _FrontendFile]) -> bool:
    """Admit only the one supported declaration in the validated startup shell."""
    shell = indexed.get("index.html")
    if shell is None:
        return False
    elements = _scope_shell_reading(shell.content)
    if elements is None:
        return False
    declarations = [dict(element.attributes).get("content") for element in elements
                    if element.name == "meta"
                    and _scope_html_ascii_lower(
                        dict(element.attributes).get("name", "")) == _SCOPE_ENGINE_PROJECTION_META]
    return declarations == [_SCOPE_ENGINE_PROJECTION_PROTOCOL]


def _scope_markup_refusal(files: dict[str, _FrontendFile]) -> str | None:
    """The index's one markup verdict over a build's members, with its reason: the shell's refusal
    (_scope_shell_refusal), or the first other member that is refused (_scope_document_refusal:
    every XML document and HTML page, and every stylesheet off the CSS accept-list); None when
    nothing is refused."""
    shell = _scope_shell_refusal(files)
    if shell is not None:
        return f"index.html: {shell}"
    for relative, entry in files.items():
        if relative != "index.html":
            refusal = _scope_document_refusal(entry.content, entry.media_type)
            if refusal is not None:
                return f"{relative}: {refusal}"
    return None


def _scope_markup_refused(files: dict[str, _FrontendFile]) -> bool:
    return _scope_markup_refusal(files) is not None


class _ScopeUninspectable(Exception):
    """A build file, or a payload inside it, that the privacy scan cannot read completely. What was
    not read is not clean: the build is refused (``refused_uninspectable``), never served."""


def _scope_stream_kind(content: bytes) -> str | None:
    """The standard-library codec whose stream ``content`` is (by magic, whatever its name)."""
    if content.startswith(_GZIP_MAGIC):
        return "gzip"
    if _BZIP2_MAGIC_RE.match(content):
        return "bzip2"
    if content.startswith(_XZ_MAGIC):
        return "xz"
    return None


def _scope_declared_encoding(relative: str) -> str | None:
    """The content encoding a member's NAME declares, read from the standard library's own registry
    (mimetypes.suffix_map aliases such as .svgz, then mimetypes.encodings_map: gzip, compress,
    bzip2, xz, br), case-insensitively — so the set of recognised encodings is the stdlib's, not a
    hand list here."""
    import mimetypes

    aliases = {k.casefold(): v for k, v in mimetypes.suffix_map.items()}
    encodings = {k.casefold(): v for k, v in mimetypes.encodings_map.items()}
    suffix = PurePosixPath(relative).suffix.casefold()
    for _hop in range(4):
        if suffix not in aliases:
            break
        suffix = PurePosixPath(aliases[suffix]).suffix.casefold()
    return encodings.get(suffix)


def _scope_inflate_bounded(content: bytes, kind: str) -> tuple[bytes, bytes]:
    """(decompressed bytes of every concatenated ``kind`` member, trailing bytes after them).
    Raises _ScopeUninspectable when the stream does not decode COMPLETELY within the per-file
    ceiling, or this interpreter lacks the codec: the cap is a bound on work, never a pass for the
    unread remainder."""
    try:
        if kind == "gzip":
            import zlib

            def make():
                return zlib.decompressobj(16 + zlib.MAX_WBITS)
            errors: tuple[type[BaseException], ...] = (zlib.error,)
        elif kind == "bzip2":
            import bz2
            make = bz2.BZ2Decompressor
            errors = (OSError, ValueError, EOFError)
        else:
            import lzma
            make = lzma.LZMADecompressor
            errors = (lzma.LZMAError, EOFError)
    except ImportError as exc:
        raise _ScopeUninspectable(f"this interpreter has no {kind} decoder") from exc
    out = bytearray()
    data = content
    try:
        while data and _scope_stream_kind(data) == kind:
            decoder = make()
            out += decoder.decompress(data, _FRONTEND_MAX_FILE_BYTES - len(out) + 1)
            if len(out) > _FRONTEND_MAX_FILE_BYTES:
                raise _ScopeUninspectable(f"a {kind} stream inflates beyond the per-file bound")
            if not decoder.eof:
                raise _ScopeUninspectable(f"a {kind} stream that does not decode completely")
            data = decoder.unused_data
    except errors as exc:
        raise _ScopeUninspectable(f"a {kind} stream that does not decode") from exc
    return bytes(out), data


def _scope_scan_views(content: bytes, depth: int = _SCOPE_DATA_URI_DEPTH):
    """The bytes a privacy scan must read for one build file: the file itself, then (bounded) the
    decompressed content of every standard-library stream and the decoded payload of every base64
    ``data:`` URI in it — a precompressed copy, an inlined asset or an inline sourcemap, whose
    sourcesContent carries a compiled document verbatim. Raises _ScopeUninspectable for anything
    it meets but cannot read completely, including a payload still encoded at the depth bound."""
    yield content
    kind = _scope_stream_kind(content)
    uris = _BASE64_DATA_URI_RE.finditer(content)
    if depth <= 0:
        if kind is not None or next(uris, None) is not None:
            raise _ScopeUninspectable("a payload nested beyond the scan bound")
        return
    if kind is not None:
        inflated, trailing = _scope_inflate_bounded(content, kind)
        yield from _scope_scan_views(inflated, depth - 1)
        if trailing.strip(b"\0"):
            yield from _scope_scan_views(trailing, depth - 1)
    budget = _FRONTEND_MAX_FILE_BYTES
    for match in uris:
        encoded = match.group(1)
        if len(encoded) > budget:
            raise _ScopeUninspectable("data: URI payloads beyond the per-file bound")
        budget -= len(encoded)
        padded = encoded + b"=" * (-len(encoded.rstrip(b"=")) % 4)
        try:
            decoded = base64.b64decode(padded.replace(b"-", b"+").replace(b"_", b"/"))
        except (binascii.Error, ValueError):
            continue  # not a payload a browser decodes either
        yield from _scope_scan_views(decoded, depth - 1)


def _scope_view_carries_snapshot_evidence(view: bytes) -> bool:
    return (all(pattern.search(view) for pattern in _SCOPE_COMPILED_MODEL_SIGNATURE)
            or any(pattern.search(view) for pattern in _SCOPE_RECORD_CITATION_SIGNATURE)
            or _SCOPE_RAW_SNAPSHOT_SIGNATURE.search(view) is not None)


def _scope_file_verdict(relative: str,
                        content: bytes) -> Literal["clean", "evidence", "uninspectable"]:
    """What the privacy scan establishes for one build file: ``evidence`` when it (or a stream or
    data: URI payload inside it) carries a recognised form of snapshot evidence (see
    _scope_file_carries_compiled_model); ``uninspectable`` when its name declares a content
    encoding its bytes are not a decodable stream of, or anything in it cannot be read completely;
    ``clean`` only when every byte the scan had to read was read and none of it was evidence."""
    if _scope_declared_encoding(relative) is not None and _scope_stream_kind(content) is None:
        return "uninspectable"
    try:
        for view in _scope_scan_views(content):
            if _scope_view_carries_snapshot_evidence(view):
                return "evidence"
    except _ScopeUninspectable:
        return "uninspectable"
    return "clean"


def _scope_file_carries_compiled_model(content: bytes) -> bool:
    """Whether one build file (or a stream / data: URI payload inside it) carries RECOGNISED
    snapshot evidence: a compiled file's binding envelope (every _SCOPE_COMPILED_MODEL_SIGNATURE key
    bound to a string literal), a compiled RECORD — which survives the bundler dropping that
    envelope — recognised by its snapshot citation (_SCOPE_RECORD_CITATION_SIGNATURE), or an engine
    snapshot itself (_SCOPE_RAW_SNAPSHOT_SIGNATURE). False is NOT "clean": content the scan cannot
    read is a separate verdict (_scope_file_verdict), and the index refuses it too."""
    return _scope_file_verdict("", content) == "evidence"


def _scope_file_index(
        dist_root: Path | None) -> tuple[str, dict[str, _FrontendFile], frozenset[str]]:
    """(status, files, embedded 64-hex tokens) for the Atlas Scope build: ``ready`` with its
    startup-indexed bytes, ``not_built`` when there is no build directory, ``invalid_build`` when
    one exists but is not a servable /scope runtime build, ``refused_compiled_evidence`` when any
    file in it carries recognised snapshot evidence, ``refused_uninspectable`` when the scan cannot
    read some file in it completely (see _scope_file_verdict). Never raises: a broken scope build
    must not stop AssessHub.

    A build is indexed ONCE per content census: the result is cached under the build's canonical
    path plus the census `_indexed_dist_tree` already takes (every member's path, type, size,
    mtime/ctime, inode and link count), so a later app over an unchanged build does not re-read and
    re-hash ~10 MB, while any change to any member (or a member added/removed) re-validates it. A
    rewrite that restores the same size AND the same timestamps on a platform whose ctime is the
    creation time is the stated limit of a stat census."""
    if dist_root is None:
        return "not_built", {}, frozenset()
    root = Path(dist_root)
    try:
        if not root.is_dir():
            return "not_built", {}, frozenset()
        dist = root.resolve(strict=True)
        if _is_filesystem_link(root):
            return "invalid_build", {}, frozenset()
    except (OSError, OverflowError, RuntimeError, ValueError):
        return "not_built", {}, frozenset()
    census = _frontend_tree_census(dist)
    if census is None:
        return "invalid_build", {}, frozenset()
    key = (str(dist), census[0])
    with _SCOPE_INDEX_CACHE_LOCK:
        cached = _SCOPE_INDEX_CACHE.get(key)
    if cached is not None:
        return cached
    result = _scope_file_index_uncached(root, dist, census[1])
    # Cache only what was validated against THIS census: if the tree moved while it was read, the
    # result stands for this start but is not remembered.
    if _frontend_tree_census(dist) == census:
        with _SCOPE_INDEX_CACHE_LOCK:
            _SCOPE_INDEX_CACHE[key] = result
            while len(_SCOPE_INDEX_CACHE) > _SCOPE_INDEX_CACHE_MAX:
                del _SCOPE_INDEX_CACHE[next(iter(_SCOPE_INDEX_CACHE))]
    return result


def _scope_file_index_uncached(
        root: Path, dist: Path, members: tuple[tuple[str, Path], ...],
) -> tuple[str, dict[str, _FrontendFile], frozenset[str]]:
    # Cheap refusal first: a build whose shell does not declare the runtime snapshot source (the
    # standalone sample build, today's repository atlas-scope/dist) is refused after reading ONLY
    # index.html, instead of reading and hashing every member.
    shell = dict(members).get("index.html")
    shell_bytes = _read_frontend_file(shell, dist) if shell is not None else None
    if not shell_bytes:
        return "invalid_build", {}, frozenset()
    if _scope_shell_reading(shell_bytes) is None:
        return "invalid_build", {}, frozenset()
    index = _indexed_dist_tree(root, _scope_shell_valid)
    if index is None:
        return "invalid_build", {}, frozenset()
    files = index[1]
    # Precedence, most specific finding first: evidence, then content the scan cannot read, then
    # markup a browser would read differently (a member whose name declares an encoding its bytes
    # are not is uninspectable first; a browser, given no Content-Encoding, could not render it).
    uninspectable = False
    for relative, entry in files.items():
        verdict = _scope_file_verdict(relative, entry.content)
        if verdict == "evidence":
            return "refused_compiled_evidence", {}, frozenset()
        uninspectable = uninspectable or verdict == "uninspectable"
    if uninspectable:
        return "refused_uninspectable", {}, frozenset()
    if _scope_markup_refused(files):
        return "invalid_build", {}, frozenset()
    return "ready", files, _embedded_sha256_tokens(files)


def _embedded_sha256_tokens(indexed: dict[str, _FrontendFile]) -> frozenset[str]:
    """Every 64-hex-digit token in the indexed files (and their base64 data: URI payloads),
    lower-cased — the form a snapshot binding digest takes when a compiler embeds it (with or
    without a ``sha256:`` prefix)."""
    tokens: set[str] = set()
    for entry in indexed.values():
        try:
            for view in _scope_scan_views(entry.content):
                tokens.update(match.decode("ascii").lower()
                              for match in _SHA256_HEX_TOKEN_RE.findall(view))
        except _ScopeUninspectable:
            continue  # unreachable for a `ready` build: its every file was read completely
    return frozenset(tokens)


def _is_scope_path(path: str) -> bool:
    return path == _SCOPE_MOUNT.rstrip("/") or path.startswith(_SCOPE_MOUNT)


def _referred_from_scope(request: Request) -> bool:
    """Whether the request's Referer names a page under /scope/ (any origin). A page is under
    /scope when EITHER reading of its path says so: the router's (percent-decoded, dot segments
    NOT collapsed — ``/scope/..%2fx`` is served the Atlas Scope shell, and a browser keeps
    ``..%2f`` verbatim in the page URL it sends as Referer) or the normalised one (dot segments,
    repeated slashes and backslashes collapsed). Both are case-folded. This rule only ever refuses
    writes, so the union is the safe reading; an unparsable Referer counts as one, since a browser
    never sends one."""
    referer = request.headers.get("referer")
    if not referer:
        return False
    try:
        path = urllib.parse.urlsplit(referer.strip()).path
    except ValueError:
        return True
    decoded = urllib.parse.unquote(path)
    routed = ("/" + decoded.lstrip("/")).casefold()
    normalised = posixpath.normpath("/" + decoded.replace("\\", "/").lstrip("/")).casefold()
    return _is_scope_path(routed) or _is_scope_path(normalised)


def _scope_unavailable_response(status: str) -> Response:
    return Response(
        content=_SCOPE_UNAVAILABLE_DETAIL[status] + "\n",
        status_code=503,
        media_type="text/plain; charset=utf-8",
        headers={"cache-control": "no-store"},
    )


def _indexed_dist_tree(
        dist_root: Path,
        shell_valid: Callable[[dict[str, _FrontendFile]], bool],
) -> tuple[Path, dict[str, _FrontendFile]] | None:
    try:
        dist = dist_root.resolve(strict=True)
        if not dist.is_dir() or _is_filesystem_link(dist_root):
            return None
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None

    before = _frontend_tree_census(dist)
    if before is None:
        return None
    before_records, members = before
    indexed: dict[str, _FrontendFile] = {}
    total_bytes = 0
    for relative, candidate in members:
        # Open the enumerated path, not a resolved target. The guarded reader compares its handle
        # back to this exact canonical path; the whole-tree pass below closes inter-member races.
        content = _read_frontend_file(candidate, dist)
        if content is None:
            return None
        total_bytes += len(content)
        if total_bytes > _FRONTEND_MAX_TOTAL_BYTES:
            return None
        indexed[relative] = _FrontendFile(
            content=content,
            media_type=_frontend_media_type(relative),
            etag=f'"{hashlib.sha256(content).hexdigest()}"',
        )
    after = _frontend_tree_census(dist)
    if after is None or after[0] != before_records or after[1] != members:
        return None
    if not shell_valid(indexed):
        return None
    return dist, indexed


def _etag_matches(header: str | None, expected: str) -> bool:
    if not header:
        return False
    for candidate in header.split(","):
        token = candidate.strip()
        if token == "*":
            return True
        if token.startswith("W/"):
            token = token[2:].strip()
        if token == expected:
            return True
    return False


def _single_byte_range(header: str, total: int) -> tuple[int, int] | None:
    value = header.strip()
    unit, equals, specification = value.partition("=")
    if (len(value) > 128 or not equals or unit.casefold() != "bytes"
            or "," in specification or total < 1):
        return None
    start_text, separator, end_text = specification.partition("-")
    if not separator or (not start_text and not end_text):
        return None
    if start_text:
        if (not start_text.isascii() or not start_text.isdigit()
                or (end_text and (not end_text.isascii() or not end_text.isdigit()))):
            return None
        start = int(start_text)
        end = int(end_text) if end_text else total - 1
        if start >= total or end < start:
            return None
        return start, min(end, total - 1)
    if not end_text.isascii() or not end_text.isdigit() or int(end_text) < 1:
        return None
    length = min(int(end_text), total)
    return total - length, total - 1


def _frontend_response(entry: _FrontendFile, request: Request) -> Response:
    headers = {"accept-ranges": "bytes", "etag": entry.etag}
    if_none_match = request.headers.get("if-none-match")
    if if_none_match and len(if_none_match) > 4_096:
        return Response(status_code=431, headers=headers)
    if _etag_matches(if_none_match, entry.etag):
        return Response(status_code=304, headers=headers)

    content = entry.content
    status_code = 200
    range_header = request.headers.get("range") if request.method == "GET" else None
    if range_header:
        unit, equals, _specification = range_header.strip().partition("=")
        if equals and unit.casefold() != "bytes":
            range_header = None  # RFC 9110: ignore an unsupported range unit
    if range_header and "," in range_header:
        range_header = None  # bounded implementation: ignore unsupported multipart ranges
    if range_header and request.headers.get("if-range") not in (None, entry.etag):
        range_header = None
    if range_header:
        selected = _single_byte_range(range_header, len(content))
        if selected is None:
            return Response(
                status_code=416,
                headers={**headers, "content-range": f"bytes */{len(content)}"},
            )
        start, end = selected
        content = content[start:end + 1]
        status_code = 206
        headers["content-range"] = f"bytes {start}-{end}/{len(entry.content)}"
    headers["content-length"] = str(len(content))
    body = b"" if request.method == "HEAD" else content
    return Response(
        content=body,
        status_code=status_code,
        media_type=entry.media_type,
        headers=headers,
    )


def is_guarded_api_path(path: str, doc_paths) -> bool:
    """Whether `path` is on the API surface `_api_access_guard` protects (auth + cross-site read +
    CSRF). THE definition — the middleware calls this, and so does the completeness test, so a test
    asserting "everything registered is either guarded or explicitly recorded as not" cannot drift
    from the rule it is asserting about. `doc_paths` is the app's own OpenAPI/docs set
    (`app.state.api_doc_paths`), read off the FastAPI instance rather than hardcoded, so renaming or
    disabling one of those URLs cannot silently open a hole.

    Note what this rule does NOT cover, deliberately and visibly: anything registered outside
    `/api/*` and the docs set — the SPA catch-all (including its exact indexed assets), or a route
    on some future `/v2` / `/internal` prefix. Those are unguarded BY CONSTRUCTION, which is correct
    for static assets and would be a hole for anything that reads client data;
    `tests/test_expensive_get_hardening.py` enumerates every registered route against this predicate
    so a new one outside the surface fails the suite instead of opening the gap silently.

    Atlas Scope (``/scope`` and everything under ``/scope/``) is ON the surface. Its files are
    static, but whether a static build carries client evidence is decided by a content scan
    (_scope_file_carries_compiled_model), and a scan recognises only the forms it knows — a bundler
    can drop a compiled file's envelope, a member can carry no citation, bytes can be re-encoded.
    Guarding the mount makes the exposure independent of that scan: whatever a build carries is
    readable exactly by whoever may read the same snapshot through /api/snapshots/{id}/raw. The
    viewer loses nothing: it is opened by same-origin navigation, and its own fetches carry the
    session cookie (path "/")."""
    return path.startswith("/api/") or path in doc_paths or _is_scope_path(path)


def create_app(db_path: str | None = None, dist_dir: str | os.PathLike | None = None,
               boot_hardening: bool = False,
               scope_dist_dir: str | os.PathLike | None = _SCOPE_DIST_DEFAULT) -> FastAPI:
    """``dist_dir`` overrides where the built SPA is served from (default: the checkout's
    webapp/frontend/dist) — the hook the Atlas entry module uses to point at the bundled copy
    inside a frozen build (webapp/backend/serve.py, ADR-0004 P1). ``scope_dist_dir`` is the Atlas
    Scope build served at /scope (default: the repository's hub build, atlas-scope/dist-hub from
    atlas-scope's ``npm run build:hub``, when it exists, else none; ``None`` disables it
    explicitly). ``boot_hardening`` threads the
    P3 unplug-safety boot (integrity check + backup — see storage.Store) and may raise
    StoreCorruptError; only the production entry turns it on. The returned ASGI object owns one
    Store for one application lifespan; create a new app object for a later independent run."""
    store = Store(db_path or _default_db_path(), boot_hardening=boot_hardening)

    @contextlib.asynccontextmanager
    async def lifespan(_application: FastAPI):
        try:
            yield
        finally:
            store.close()

    app = FastAPI(
        title="AssessHub",
        version=engine.ENGINE_SCHEMA_VERSION,
        description="A live web platform over the Cisco Migration-Assessment engine.",
        lifespan=lifespan,
    )

    @app.exception_handler(ExecutionReceiptAuthorityError)
    async def execution_receipt_authority_error(
            _request: Request, _error: ExecutionReceiptAuthorityError) -> JSONResponse:
        # Do not publish corrupted/torn receipt detail as a usable decision. Operators get a closed
        # conflict and must restore/recollect; server logs and integrity tooling retain diagnosis.
        return JSONResponse(
            status_code=409,
            content={
                "detail": "Execution comparison authority could not be revalidated from its "
                          "persisted receipt and exact source rows; no PASS is available.",
            },
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
        # Same-origin write containment for Atlas Scope (defence in depth). /scope is first-party,
        # read-only code served same-origin, so the cross-site and CSRF refusals below pass its
        # requests; a read-only viewer never writes. /scope responses set Referrer-Policy:
        # same-origin (the rest of AssessHub sends no Referer), and any non-GET request referred
        # from a /scope/ page is refused here — first, in token and no-token modes alike. A hostile
        # script can suppress or rewrite its Referer, so this backs up, and never replaces, the
        # viewer having no write code.
        if guarded and request.method not in ("GET", "HEAD") and _referred_from_scope(request):
            return JSONResponse({"detail": _SCOPE_WRITE_REFUSED_DETAIL}, status_code=403)
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
        if _is_scope_path(request.url.path):
            # Every /scope response (shell, asset, 404/405/503): the viewer's own requests carry a
            # same-origin Referer, which the /api guard uses to refuse any write it makes.
            response.headers["Referrer-Policy"] = "same-origin"
        else:
            response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    app.state.store = store

    # Atlas Scope build state, fixed at startup except for one transition: a build that embeds the
    # digest of a stored snapshot is withdrawn. Atlas Scope must fetch evidence at run time from
    # /api/snapshots/{id}/raw; a static build that carries it instead would show that evidence
    # under whatever snapshot URL it is opened at. (The /scope mount sits behind the same access
    # guard as /api — is_guarded_api_path — so its files are never readable cross-site, by a
    # non-loopback peer without a token, or without the token in token mode.)
    # Checked for every snapshot already stored, and — via the store's one insert path — for every
    # snapshot stored later, BEFORE its commit. The scope routes then read only this in-memory state.
    #
    # The PRIMARY control is privacy by construction: a build is `ready` only when it declares the
    # runtime snapshot source AND no file in it carries snapshot evidence — a compiled snapshot
    # model or an engine snapshot (_scope_file_index). The digest check below is defence in depth for a build that embeds a
    # stored blob digest some other way. It runs at startup, before the commit of every insert
    # through THIS Store (the observer), and — because another Store or process on the same
    # database never reaches this Store's observer — again on every scope request and capability
    # read, over the rows inserted since the last check (_current_scope_status). A withdrawal is
    # permanent for the app's lifetime.
    scope_status, scope_files, scope_digest_tokens = _scope_file_index(
        ATLAS_SCOPE_DIST if scope_dist_dir is _SCOPE_DIST_DEFAULT
        else (Path(scope_dist_dir) if scope_dist_dir is not None else None))
    app.state.scope_status = scope_status
    scope_recheck_lock = threading.Lock()
    scope_digest_watermark = [0]
    if scope_status == "ready" and scope_digest_tokens:
        scope_digest_watermark[0], stored_digests = store.snapshot_blob_digests_after(0)
        if stored_digests & scope_digest_tokens:
            app.state.scope_status = "refused_embeds_stored_snapshot"

        def _withdraw_scope_embedding(blob_digest: str) -> None:
            if blob_digest in scope_digest_tokens:
                app.state.scope_status = "refused_embeds_stored_snapshot"

        store.add_snapshot_digest_observer(_withdraw_scope_embedding)

    def _current_scope_status() -> str:
        """The scope status as of THIS request. A build with no 64-hex token cannot embed a
        stored digest, so it needs (and makes) no store access at all; otherwise the only store
        access is a digest-only read of rows newer than the last check (SQLite serialises writers
        and AUTOINCREMENT never reuses an id, so a watermark over ids sees every committed insert)."""
        if app.state.scope_status != "ready" or not scope_digest_tokens:
            return app.state.scope_status
        with scope_recheck_lock:
            watermark, new_digests = store.snapshot_blob_digests_after(scope_digest_watermark[0])
            scope_digest_watermark[0] = max(scope_digest_watermark[0], watermark)
            if new_digests & scope_digest_tokens:
                app.state.scope_status = "refused_embeds_stored_snapshot"
        return app.state.scope_status

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
            # a summary ranked from the raw failure_impact rows (no keystone contract) is recomputed too
            and summ.get("keystone_contract") == summary.KEYSTONE_CONTRACT_VERSION
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

    ui_projection_api.install_routes(app, store)

    @app.get("/api/snapshots/{snapshot_id}/raw")
    def get_snapshot_raw(snapshot_id: RowId) -> Response:
        """The persisted snapshot bytes, UNCHANGED, with the store's binding of those bytes.

        This is the runtime evidence source for Atlas Scope (/scope): client evidence is fetched
        here, under every /api guard, and never compiled into a static bundle. The body is the
        exact ``snapshots.snapshot_json`` blob — not a re-serialisation — so a consumer can verify
        ``sha256(body) == X-Snapshot-Sha256``. That digest is the store's blob form
        (``X-Snapshot-Digest-Form: assesshub-store-blob``), which is NOT the digest of the file that
        was uploaded (uploads are parsed, provenance-stamped and stored compact)."""
        blob = store.get_snapshot_blob(snapshot_id)
        if blob is None:
            raise HTTPException(404, "Snapshot not found")
        raw, binding = blob
        return Response(
            content=raw,
            media_type="application/json",
            headers={
                "cache-control": "no-store",
                "x-snapshot-sha256": str(binding["sha256"]).removeprefix("sha256:"),
                "x-snapshot-bytes": str(binding["bytes"]),
                "x-snapshot-digest-form": "assesshub-store-blob",
            },
        )

    @app.get("/api/snapshots/{snapshot_id}/scope-view")
    def get_snapshot_scope_view(snapshot_id: RowId, response: Response) -> Dict[str, Any]:
        """Whether this installation can show the snapshot in Atlas Scope, and the link to do it.

        The SPA renders its "Open in Atlas Scope" link only from ``href`` here, so the link target
        has one owner and an absent, invalid or withdrawn scope build never yields a dead link."""
        if not store.get_snapshot_meta(snapshot_id):
            raise HTTPException(404, "Snapshot not found", headers={"Cache-Control": "no-store"})
        response.headers["Cache-Control"] = "no-store"
        status = _current_scope_status()
        available = status == "ready"
        projection_available = available and _scope_engine_projection_declared(scope_files)
        return {
            "available": available,
            "status": status,
            "href": f"{_SCOPE_MOUNT}snapshots/{snapshot_id}/" if available else None,
            "detail": _SCOPE_READY_DETAIL if available else _SCOPE_UNAVAILABLE_DETAIL[status],
            "engine_projection": {
                "available": projection_available,
                "protocol": _SCOPE_ENGINE_PROJECTION_PROTOCOL,
                "projection_schema": "ui_projection/1",
                "style_schema": "ui_projection_topology_style/1",
                "href": (f"{_SCOPE_MOUNT}snapshots/{snapshot_id}/?engine_projection=1"
                         if projection_available else None),
                "detail": ("The installed Atlas Scope hub supports the engine topology contract."
                           if projection_available else
                           "The engine topology adapter is unavailable in this installation."),
            },
        }

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
        if name == "failure_impact":
            # The tab renders the engine-owned projection rows: a cell it withholds (a switch it could not
            # simulate, a row older than its marker, a partial simulation, an uncollected neighbour, a
            # duplicated host) shows its reason, never the stored Info / 0 / clean-bill text as a measurement.
            data = summary.failure_impact_table(snap)
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
                # failure_impact stays the STORED producer list on purpose: it is the list the pipeline hands this
                # engine function (main stores the same failure_impact its _device_dossiers adapter reads), and the
                # engine owns its inputs. Whether the dossier's impact term should honour the projection's holds is
                # an engine question, not one this route answers by feeding it different rows.
                from cisco_toolkit.analyze import compute_device_dossiers
                from cisco_toolkit.ssot import failed_sections
                data = compute_device_dossiers(
                    health_scores=snap.get("health_scores"), failure_impact=snap.get("failure_impact"),
                    lifecycle_risk=snap.get("lifecycle_risk"), software_risk=snap.get("software_risk"),
                    platform_health=snap.get("platform_health"), syslog_intelligence=snap.get("syslog_intelligence"),
                    qos_audit=snap.get("qos_audit"), golden_drift=snap.get("golden_drift"),
                    security=snap.get("security"), config_hygiene=snap.get("config_hygiene"),
                    stp_roots=snap.get("stp_roots"), vpc=snap.get("vpc"),
                    physical_health=snap.get("physical_health"), protocol_health=snap.get("protocol_health"),
                    move_groups=snap.get("move_groups"),
                    protocol_assessability=snap.get("protocol_assessability"),
                    parse_yield=snap.get("parse_yield"), input_failures=failed_sections(snap))
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
        # From the snapshot, not the cached summary: a summary cached before the keystone contract ranked raw
        # failure_impact rows, and this badge must not mark a device whose blast radius the engine withholds.
        keystones = [k.get("host") for k in summary._keystones(snap) if k.get("host")]
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
        bound_set = store.get_bound_snapshot_set([before_snapshot_id, after_snapshot_id])
        if bound_set is None:
            raise HTTPException(404, "One or both snapshots not found")
        before_source = bound_set[before_snapshot_id]
        after_source = bound_set[after_snapshot_id]
        before = before_source["snapshot"]
        before_binding = before_source["binding"]
        after = after_source["snapshot"]
        after_binding = after_source["binding"]
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

    def _stored_l2_failure_trial(
            request_body: L2FailureTrialIn,
            *,
            before_snapshot_id: int,
            recovery_snapshot_id: int) -> Dict[str, Any]:
        """Atomically acquire four persisted phases and mint store-owned trial authority."""
        pre_id = request_body.pre_failure_snapshot_id
        post_id = request_body.post_failure_snapshot_id
        recovery_id = recovery_snapshot_id
        all_ids = (before_snapshot_id, pre_id, post_id, recovery_id)
        if len(set(all_ids)) != 4:
            raise HTTPException(
                400,
                "Before, pre-failure, post-failure, and recovery snapshots must be four distinct rows",
            )
        source_set = store.get_bound_snapshot_set(list(all_ids))
        if source_set is None:
            raise HTTPException(404, "One or more observed-trial phase snapshots were not found")
        before_source = source_set[before_snapshot_id]
        pre_source = source_set[pre_id]
        post_source = source_set[post_id]
        recovery_source = source_set[recovery_id]
        pre_snapshot, pre_binding = pre_source["snapshot"], pre_source["binding"]
        post_snapshot, post_binding = post_source["snapshot"], post_source["binding"]
        recovery_snapshot = recovery_source["snapshot"]
        recovery_binding = recovery_source["binding"]
        bindings = (pre_binding, post_binding, recovery_binding)
        contexts = {
            (binding.get("source"), binding.get("campaign_id"), binding.get("engagement_id"))
            for binding in (before_source["binding"], *bindings)
        }
        if (len(contexts) != 1
                or next(iter(contexts))[0] != _PERSISTED_SNAPSHOT_SOURCE):
            raise HTTPException(
                409,
                "Observed-trial phases must belong to one persisted campaign and engagement",
            )
        try:
            witness_bytes = base64.b64decode(
                request_body.witness_json_base64.encode("ascii"), validate=True
            )
        except (UnicodeEncodeError, ValueError, binascii.Error) as error:
            raise HTTPException(
                422, "witness_json_base64 must be canonical base64-encoded JSON bytes"
            ) from error
        if not witness_bytes or len(witness_bytes) > 64 * 1024:
            raise HTTPException(422, "Observed-trial witness bytes exceed the 64 KiB limit")

        phase_rows = (
            ("pre_failure", pre_snapshot, pre_binding, pre_source),
            ("post_failure", post_snapshot, post_binding, post_source),
            ("recovery", recovery_snapshot, recovery_binding, recovery_source),
        )
        custody = {
            phase: {
                "source": binding["source"],
                "source_id": f"snapshot:{binding['snapshot_id']}",
                "campaign_id": binding["campaign_id"],
                "engagement_id": binding["engagement_id"],
                "custody_at": source["uploaded_at"],
            }
            for phase, _snapshot, binding, source in phase_rows
        }
        from cisco_toolkit.l2_rehearsal import compute_observed_l2_failure_evidence

        evidence = compute_observed_l2_failure_evidence(
            pre_snapshot,
            post_snapshot,
            recovery_snapshot,
            witness_bytes=witness_bytes,
            phase_custody=custody,
        )
        return {
            "before_snapshot": before_source["snapshot"],
            "before_binding": before_source["binding"],
            "recovery_snapshot": recovery_snapshot,
            "recovery_binding": recovery_binding,
            "evidence": evidence,
            # Internal persistence input. It is never accepted as a detached client receipt;
            # storage re-reads every row and remints evidence while BEGIN IMMEDIATE is held.
            "source_record": {
                "schema": "stored_l2_failure_trial_source/1",
                "pre_failure_snapshot_id": pre_id,
                "post_failure_snapshot_id": post_id,
                "recovery_snapshot_id": recovery_id,
                "witness_bytes": witness_bytes,
                "witness_sha256": "sha256:" + hashlib.sha256(witness_bytes).hexdigest(),
                "source": recovery_binding["source"],
                "campaign_id": recovery_binding["campaign_id"],
                "engagement_id": recovery_binding["engagement_id"],
            },
        }

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
            if saved == "closed":
                raise HTTPException(
                    409,
                    "Run is already finished and can no longer be modified.",
                )
            if saved == "authority_invalid":
                raise HTTPException(
                    409,
                    "Execution comparison authority could not be revalidated from its persisted "
                    "receipt and exact source rows; the mutation was refused.",
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

        trial_source_record = None
        if body.l2_failure_trial is not None:
            acquired_trial = _stored_l2_failure_trial(
                body.l2_failure_trial,
                before_snapshot_id=rec["snapshot_id"],
                recovery_snapshot_id=body.after_snapshot_id,
            )
            before = acquired_trial["before_snapshot"]
            before_binding = acquired_trial["before_binding"]
            after = acquired_trial["recovery_snapshot"]
            after_binding = acquired_trial["recovery_binding"]
            l2_failure_trial = acquired_trial["evidence"]
            trial_source_record = acquired_trial["source_record"]
        else:
            before, before_binding, after, after_binding = _bound_comparison_pair(
                rec["snapshot_id"], body.after_snapshot_id)
            l2_failure_trial = None
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
            l2_failure_trial=l2_failure_trial,
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
            execution_id,
            rec["_state_json"],
            receipt,
            l2_failure_trial_source=trial_source_record,
        )
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
        if status == "authority_invalid":
            raise HTTPException(
                409,
                "Existing execution comparison authority could not be revalidated from its "
                "persisted receipt and exact source rows; no newer receipt was appended.",
            )
        if status == "l2_trial_required":
            raise HTTPException(
                409,
                "A prior observed local L2 failure or not-verified trial remains unresolved. "
                "Supply a newer complete "
                "source-bound re-trial for that exact family, subject, and scenario; omitting or "
                "substituting the trial cannot replace the blocking evidence.",
            )
        if status == "comparison_not_newer":
            raise HTTPException(
                409,
                "Execution comparisons are append-only in evidence time. The new after snapshot "
                "must have a strictly newer snapshot ID, source-owned collected_at, and persisted "
                "upload time than the current latest comparison.",
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
                # Recompute only opted-in cutover_execution/2 read views before export. Legacy
                # outcomes are historical evidence and remain unchanged; they also remain
                # explicitly disclosed below as having no canonical comparison receipt.
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
        # One immutable gate read feeds both the forwarded DOCX and the response header. Reading
        # twice allowed a concurrent decision to split the two representations.
        gate_note = deliverables.gate_disclosure(kind, engagement=meta["engagement_id"])
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
                    document_gate=gate_note,
                )
            except Exception as e:  # generation failure (e.g. a malformed snapshot)
                raise HTTPException(500, f"Failed to generate {kind}: {e}") from e
        spec = deliverables.SPECS[kind]
        # PPDIOO document gates DISCLOSE on this surface rather than refuse (the reasoning, and the
        # remaining ownership limit, are in deliverables.generate's docstring). The same bounded
        # projection is embedded in Design/MOP DOCX files and exposed to the SPA/curl here.
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
        if body.l2_failure_trial is not None:
            acquired_trial = _stored_l2_failure_trial(
                body.l2_failure_trial,
                before_snapshot_id=body.old_id,
                recovery_snapshot_id=body.new_id,
            )
            old = acquired_trial["before_snapshot"]
            old_binding = acquired_trial["before_binding"]
            new = acquired_trial["recovery_snapshot"]
            new_binding = acquired_trial["recovery_binding"]
            l2_failure_trial = acquired_trial["evidence"]
        else:
            old, old_binding, new, new_binding = _bound_comparison_pair(
                body.old_id, body.new_id)
            l2_failure_trial = None
        return engine.compare_bound_pair(
            old,
            new,
            before_binding=old_binding,
            after_binding=new_binding,
            change_intent=(body.change_intent.model_dump(mode="json")
                           if body.change_intent is not None else None),
            l2_failure_trial=l2_failure_trial,
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

    # -- Atlas Scope (/scope) ---------------------------------------------
    # Registered BEFORE the SPA catch-all below, and ALWAYS (built or not), so a /scope URL never
    # falls through to AssessHub's own shell. GET only: Atlas Scope is first-party read-only code
    # served same-origin, which is exactly why it must never grow a write surface here. These sit
    # on the guarded surface (is_guarded_api_path), so the access guard answers before them. They
    # read no snapshot content and touch no filesystem at request time: an exact key selects bytes
    # captured at startup, so traversal/UNC-shaped input cannot name a file.
    @app.get("/scope/assets/{asset_path:path}", include_in_schema=False)
    def scope_asset(request: Request, asset_path: str):
        status = _current_scope_status()
        if status != "ready":
            return _scope_unavailable_response(status)
        selected = scope_files.get("assets/" + asset_path)
        if selected is None:
            raise HTTPException(404, "Not found")
        return _frontend_response(selected, request)

    @app.get("/scope", include_in_schema=False)
    @app.get("/scope/{rest:path}", include_in_schema=False)
    def scope_shell(request: Request, rest: str = ""):
        status = _current_scope_status()
        if status != "ready":
            return _scope_unavailable_response(status)
        return _frontend_response(scope_files["index.html"], request)

    # -- frontend (production) --------------------------------------------
    # Serve the built SPA with a history-fallback: hashed assets are served directly, every other
    # non-API path returns index.html so client-side deep links survive a hard refresh. The /api
    # routes above are registered first, so they always win over this catch-all.
    dist_root = Path(dist_dir) if dist_dir is not None else FRONTEND_DIST
    frontend_index = _frontend_file_index(dist_root)
    app.state.frontend_ready = False
    app.state.frontend_status = "bounded_startup_index_failed"
    if frontend_index is not None:
        _dist, frontend_files = frontend_index
        index_file = frontend_files["index.html"]
        app.state.frontend_ready = True
        app.state.frontend_status = "ready"

        @app.api_route(
            "/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
        def spa(request: Request, full_path: str):
            if full_path.startswith("api/"):
                raise HTTPException(404, "Not found")
            if full_path == _SCOPE_MOUNT.strip("/") or full_path.startswith(_SCOPE_MOUNT[1:]):
                # Only a non-GET (HEAD) method reaches here for /scope — the GET-only scope routes
                # above answer every GET. Refuse it rather than answering with AssessHub's shell.
                raise HTTPException(405, "Method Not Allowed", headers={"Allow": "GET"})
            # This unguarded catch-all accepts no request-time filesystem operation. Only an
            # exact key can select bounded immutable bytes captured under ``dist`` at startup;
            # missing assets stay 404 while non-asset deep links receive the SPA shell.
            selected = frontend_files.get(full_path)
            if selected is not None:
                return _frontend_response(selected, request)
            if full_path == "assets" or full_path.startswith("assets/"):
                raise HTTPException(404, "Not found")
            return _frontend_response(index_file, request)

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
