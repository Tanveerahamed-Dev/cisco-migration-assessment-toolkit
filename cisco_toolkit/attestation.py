"""Zero-egress attestation panel (roadmap D3; next-best-improvements-2026-07-04 do-first).

RE-DERIVES the engine's trust claims at build time — read-only command surface, no-egress
import graph, GET-only REST collector, no LLM in the runtime pipeline — with the SAME
mechanics as tests/test_readonly_and_no_egress.py (which imports THIS module's grammar, so
the shipped panel and the CI doctrine-guard can never diverge). A falsifiable proof, never
a hardcoded badge:

- every result is COMPUTED at call time from the actual registries / actual sources;
- a check that cannot run (source tree unavailable in an installed-without-sources wheel,
  collector module not importable) publishes NOT_EVALUATED with its reason — an abstention
  is first-class, absence of evidence is never rendered as a pass;
- a violation NAMES the offending registry/command or module/import.

Published as snap['attestation'] and the workbook 'Trust & Sovereignty' sheet
(excel.write_attestation_sheet). Explorer panel + HLD front-matter rendering: deferred.
No I/O beyond reading this package's own source files; no network; no new dependencies.
"""
import ast
import importlib
import importlib.util
import ipaddress
import os
import re
from datetime import datetime, timezone

def loopback_only(hostport: str, *, env_var: str = "OLLAMA_HOST") -> str:
    """Return ``hostport`` if it names a LOOPBACK endpoint; raise ``ValueError`` otherwise.

    ADR-0001 Amendment 1 carves out exactly one exception to the no-egress doctrine: a **local**
    Ollama on 127.0.0.1, on the grounds that on-host compute is not egress. That reasoning holds only
    while the endpoint really is on-host. The three helpers read their endpoint from ``$OLLAMA_HOST``
    — Ollama's own standard variable, so it is plausibly already set in a shell profile — and built
    ``f"http://{OLLAMA_HOST}/api/chat"`` from it with no validation, so a single
    ``OLLAMA_HOST=ollama.corp.example:11434`` silently turned the carve-out into real egress. The
    payloads make that serious: the retrieval judge posts excerpts from a corpus built out of every
    git-tracked ``*.py``/``*.md`` plus verified vault-digest entries.

    Deliberately does NOT resolve names: a DNS lookup for an attacker- or misconfiguration-supplied
    host is itself a network round trip, and resolving would let a hostname that happens to map to
    127.0.0.1 today point elsewhere tomorrow. An IP literal, or the exact name ``localhost``, only.
    """
    host = (hostport or "").strip()
    if host.startswith("["):                                   # [::1]:11434
        host = host[1:].split("]", 1)[0]
    elif host.count(":") == 1:                                 # host:port (never a bare IPv6)
        host = host.split(":", 1)[0]
    host = host.strip()
    if host.lower() == "localhost":
        return hostport
    try:
        ip = ipaddress.ip_address(host)
    except ValueError as e:
        raise ValueError(
            f"{env_var}={hostport!r} is not a loopback endpoint. The local-inference carve-out "
            f"(ADR-0001 Amendment 1) permits ON-HOST compute only, so this must be an IP literal on "
            f"127.0.0.0/8 or ::1, or the name 'localhost'. Cloud/remote LLM calls stay forbidden."
        ) from e
    if not ip.is_loopback:
        raise ValueError(
            f"{env_var}={hostport!r} points OFF-HOST ({ip}). That is egress, which this repo's "
            f"no-egress doctrine forbids; the ADR-0001 Amendment 1 carve-out covers a local Ollama "
            f"on 127.0.0.1 only.")
    return hostport


ATTESTATION_SCHEMA = "attestation/1"

HOLDS = "HOLDS"
VIOLATED = "VIOLATED"
NOT_EVALUATED = "NOT_EVALUATED"

CLAIM_IDS = ("read_only_command_surface", "no_egress_import_graph",
             "rest_collect_get_only", "no_llm_runtime")

# Read-only command grammar, shared with tests/test_readonly_and_no_egress.py: SSH/CLI read
# verbs (show/display/get/dir/ping/moquery), the AWS read-only describe-*, and the
# controller-REST GET paths (api/ FMC, ers/ ISE, dataservice/ vManage). A write verb
# (config/set/execute/reload/request/aws ec2 authorize-/create-/delete-, a POST-only REST
# path, ...) matches none of these.
#
# NECESSARY BUT NOT SUFFICIENT — always go through is_read_only_command() below. This regex
# constrains only the FIRST WORD, and `.match()` anchors at the start, so on its own it accepts
# `show running-config | redirect bootflash:x` (NX-OS WRITES that file), `show run | tftp://host/x`
# (ships the config off the box) and `show version ; reload`. A read verb with a write tacked onto
# it is precisely the string this claim exists to reject.
READ_ONLY_CMD = re.compile(
    r"^(show|display|get|dir|ping|moquery)\b"          # SSH/CLI read verbs (incl. ACI moquery over SSH)
    r"|^aws ec2 describe-"                              # AWS read-only describe (never authorize/create/delete)
    r"|^(api/|ers/|dataservice/)",                     # controller-REST GET paths (FMC / ISE / vManage)
)

# Anything that can chain, redirect, substitute or line-break a second command out of a read verb.
# netmiko writes the string to the channel verbatim, so an embedded newline is a second command
# typed at the exec prompt.
_CLI_CHAIN = re.compile(r"[\r\n;&`$><\\]")
# A pipe is legal on IOS/NX-OS only as an OUTPUT FILTER. redirect/tee/append and any URL sink write
# or egress, so the stage list is a closed allowlist, not a denylist.
_PIPE_FILTER_OK = re.compile(
    r"^(section|include|exclude|begin|grep|egrep|count|json|xml|no-more|last|head|diff|sort|uniq|in)\b")
_REST_PREFIXES = ("api/", "ers/", "dataservice/")


def is_read_only_command(cmd, *, extra_verbs: tuple = ()) -> bool:
    """True when the WHOLE string is read-only — the check this module's claim is built on.

    Deliberately re-derived here rather than imported from the collector: attestation is the
    verifier, and a verifier that borrows the proposer's own gate can only ever agree with it
    (proposer != verifier). The two implementations are independent by design, so a weakening of
    one is caught by the other.

    `extra_verbs` widens ONLY the verb list, never the whole-string safety below — it exists so a
    surface with a legitimately broader read vocabulary (the NRFU service phase also issues
    `traceroute`) composes with this owner instead of copying the grammar and drifting from it.
    """
    s = str(cmd).strip()
    ok_verb = bool(READ_ONLY_CMD.match(s))
    if not ok_verb and extra_verbs:
        ok_verb = bool(re.match(r"^(%s)\b" % "|".join(re.escape(v) for v in extra_verbs), s))
    if not ok_verb:
        return False
    if s.startswith(_REST_PREFIXES):
        # A REST path is handed to an HTTP client, not a shell: `?` and `&` are legitimate query
        # syntax there. Only a header-injection break matters.
        return not re.search(r"[\r\n]", s)
    if _CLI_CHAIN.search(s):
        return False
    return all(_PIPE_FILTER_OK.match(seg.strip()) for seg in s.split("|")[1:])

# Direct network-egress libraries: none of these may be imported (at ANY nesting depth) by
# the offline analysis -> deliverable pipeline. Shared with the doctrine test.
NETWORK_IMPORTS = frozenset({
    "socket", "requests", "httpx", "http.client", "httplib", "urllib.request",
    "netmiko", "paramiko", "telnetlib", "ftplib", "smtplib", "aiohttp", "pycurl"})

# LLM / GenAI SDKs: the pipeline is deterministic and air-gapped — no model call at runtime.
LLM_IMPORTS = frozenset({
    "openai", "anthropic", "cohere", "mistralai", "google.generativeai", "vertexai",
    "langchain", "langchain_core", "langchain_openai", "litellm", "llama_cpp",
    "ollama", "transformers", "huggingface_hub"})

# Documented egress charter of the no-egress claim (same as the doctrine test):
# - rest_collect.py IS the opt-in controller-REST collector — excluded from the no-egress
#   walk; its own floor (GET-only except the single login POST) is the third claim.
# - data/gen_port_registry.py is a dev-only data-pack generator (urllib to IANA), not
#   import-reachable from the runtime pipeline — a documented exception, disclosed in detail.
# Both are keyed by the path RELATIVE to the scanned package root (posix separators), because
# the walk is recursive: a bare basename would exempt a same-named file in ANY subpackage.
# (Until this was fixed the walk was top-level only, so `gen_port_registry.py` — one directory
# down — was never scanned and its exception was DEAD CODE: the panel published "0 network-library
# imports" over a file that fetches iana.org. :func:`_claim_no_egress` now NAMES what it exempted
# and reports an exception that matched nothing, so the exemption cannot go dead again unnoticed.)
NO_EGRESS_EXCLUDE = frozenset({"rest_collect.py"})
NO_EGRESS_EXCEPTIONS = frozenset({"data/gen_port_registry.py"})

_COLLECTOR_MODULE = "COLLECT_PARSE_V3_23_0"


# --------------------------------------------------------------- mechanics ---
def imported_names(tree):
    """Every imported module name in a parsed module, at ANY nesting depth (catches lazy
    in-function imports). Shared with tests/test_readonly_and_no_egress.py."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            names.add(mod)
            for a in node.names:
                names.add(f"{mod}.{a.name}" if mod else a.name)
    return names


def _iter_py(dirpath, exclude=frozenset()):
    """Every .py under `dirpath` at ANY depth, as (relpath, abspath) with posix relpaths.

    RECURSIVE by construction: a top-level-only walk cannot see a subpackage, and this walk is
    the evidence behind a client-facing claim — a module the walk never opened must never be
    counted as one it cleared. `exclude` holds relpaths (charter exclusions)."""
    for root, dirs, files in os.walk(dirpath):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__" and not d.startswith("."))
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, dirpath).replace(os.sep, "/")
            if rel in exclude:
                continue
            yield rel, path


def scan_imports(dirpath, banned, exclude=frozenset()):
    """AST import-walk over every .py under dirpath (any depth) -> (n_scanned, offenders) where
    offenders maps the posix RELPATH -> sorted banned imports found. Documented exceptions are
    NOT applied here: the caller subtracts them so the claim can NAME what it exempted (an
    exception silently absorbed inside the scan is how the last one went dead)."""
    offenders = {}
    n = 0
    for rel, path in _iter_py(dirpath, exclude):
        n += 1
        src = open(path, encoding="utf-8", errors="replace").read()
        tree = ast.parse(src, filename=path)
        bad = sorted({name for name in imported_names(tree)
                      if any(name == b or name.startswith(b + ".") for b in banned)})
        if bad:
            offenders[rel] = bad
    return n, offenders


def _claim(cid, method, result, detail):
    return {"id": cid, "method": method, "result": result, "detail": detail}


# ------------------------------------------------------------------ claims ---
def _claim_read_only(collector_module):
    method = ("re-derive over every COMMANDS_* registry of the collector: the WHOLE of each command "
              "must be read-only — a read verb (show/display/get/dir/ping/moquery | aws ec2 "
              "describe- | api|ers|dataservice REST GET paths) AND no way to chain, redirect or "
              "substitute a second command out of it (no CR/LF ; & ` $ > < \\, and every pipe stage "
              "an output filter, never redirect/tee/append or a URL sink)")
    cid = "read_only_command_surface"
    try:
        mod = importlib.import_module(collector_module)
    except Exception as e:
        return _claim(cid, method, NOT_EVALUATED,
                      f"collector module {collector_module!r} not importable: {e!r}")
    regs = {k: getattr(mod, k) for k in dir(mod) if k.startswith("COMMANDS_")}
    total = sum(len(cmds) for cmds in regs.values())
    if not regs or total == 0:
        return _claim(cid, method, NOT_EVALUATED,
                      f"no COMMANDS_* registry commands found on {collector_module!r} — "
                      "an empty surface proves nothing (refusing a vacuous pass)")
    offenders = {}
    for rname, cmds in regs.items():
        bad = [str(c) for c in cmds if not is_read_only_command(c)]
        if bad:
            offenders[rname] = bad
    if offenders:
        return _claim(cid, method, VIOLATED, f"non-read-only command(s): {offenders}")
    return _claim(cid, method, HOLDS,
                  f"all {total} registry commands across {len(regs)} COMMANDS_* registries "
                  "match the read-only grammar")


def _claim_no_egress(toolkit_dir):
    method = ("RECURSIVE AST import-walk (every subpackage, any nesting depth, lazy imports "
              "included) over the analysis package for network libraries; charter exclusion: "
              "rest_collect.py (the opt-in REST collector, covered by its own GET-only claim); "
              "documented dev-only exception: data/gen_port_registry.py (data-pack generator, "
              "not pipeline-reachable) — subtracted AFTER the scan and named in the result")
    cid = "no_egress_import_graph"
    if not os.path.isdir(toolkit_dir):
        return _claim(cid, method, NOT_EVALUATED,
                      f"analysis-package source tree not available at {toolkit_dir!r} "
                      "(installed without sources?) — cannot walk the import graph")
    try:
        n, offenders = scan_imports(toolkit_dir, NETWORK_IMPORTS, exclude=NO_EGRESS_EXCLUDE)
    except (OSError, SyntaxError, ValueError) as e:
        return _claim(cid, method, NOT_EVALUATED, f"source walk failed: {e!r}")
    if n == 0:
        return _claim(cid, method, NOT_EVALUATED,
                      f"no python sources found under {toolkit_dir!r} — nothing was proven")
    # Documented exceptions are subtracted HERE, and disclosed: what was exempted (with the
    # import that made it an offender) and any declared exception that matched NOTHING — a
    # never-firing exception means either the walk cannot see the file or the charter is stale.
    exempt = {rel: bad for rel, bad in offenders.items() if rel in NO_EGRESS_EXCEPTIONS}
    unexplained = {rel: bad for rel, bad in offenders.items() if rel not in NO_EGRESS_EXCEPTIONS}
    stale = sorted(e for e in NO_EGRESS_EXCEPTIONS if e not in offenders)
    if unexplained:
        return _claim(cid, method, VIOLATED,
                      f"network-egress import(s) in the offline analysis pipeline: {unexplained}")
    exempt_txt = ("; documented exception(s) applied: "
                  + ", ".join(f"{rel} -> {','.join(bad)}" for rel, bad in sorted(exempt.items()))
                  if exempt else "; no documented exception was needed")
    stale_txt = (f"; declared exception(s) that matched nothing (stale charter?): {stale}"
                 if stale else "")
    return _claim(cid, method, HOLDS,
                  f"0 unexplained network-library imports across {n} analysis modules "
                  f"(recursive walk; excluded by charter: rest_collect.py{exempt_txt}{stale_txt})")


def _claim_rest_get_only(rest_path):
    method = ("source scan of rest_collect.py: no PUT/PATCH/DELETE request method anywhere; "
              "exactly ONE POST (the login) — the collector cannot create/modify/delete a "
              "fabric object")
    cid = "rest_collect_get_only"
    if not os.path.isfile(rest_path):
        return _claim(cid, method, NOT_EVALUATED,
                      f"rest_collect.py source not available at {rest_path!r} — "
                      "the GET-only floor cannot be re-derived")
    src = open(rest_path, encoding="utf-8", errors="replace").read()
    bad = [v for v in ("PUT", "PATCH", "DELETE")
           if f'method="{v}"' in src or f"method='{v}'" in src]
    n_post = src.count('method="POST"') + src.count("method='POST'")
    n_get = src.count('method="GET"') + src.count("method='GET'")
    if bad:
        return _claim(cid, method, VIOLATED, f"write method(s) present: {bad}")
    if n_post != 1:
        return _claim(cid, method, VIOLATED,
                      f"expected exactly one POST (the login); found {n_post} — "
                      "an extra POST may write controller state")
    return _claim(cid, method, HOLDS,
                  f"GET-only with the single login POST ({n_get} GET call site(s), "
                  "1 POST, 0 PUT/PATCH/DELETE)")


def _claim_no_llm(toolkit_dir, collector_module):
    method = ("AST import-walk over the analysis package (rest_collect.py included) + the "
              "collector entry module for LLM/GenAI SDK imports — the pipeline is "
              "deterministic and air-gapped, no model call at runtime")
    cid = "no_llm_runtime"
    if not os.path.isdir(toolkit_dir):
        return _claim(cid, method, NOT_EVALUATED,
                      f"analysis-package source tree not available at {toolkit_dir!r} "
                      "(installed without sources?) — cannot walk the import graph")
    try:
        n, offenders = scan_imports(toolkit_dir, LLM_IMPORTS)
    except (OSError, SyntaxError, ValueError) as e:
        return _claim(cid, method, NOT_EVALUATED, f"source walk failed: {e!r}")
    # the collector entry lives OUTSIDE the package dir; scan its source too when resolvable
    collector_scanned = False
    try:
        spec = importlib.util.find_spec(collector_module)
        origin = getattr(spec, "origin", None) if spec else None
        if origin and os.path.isfile(origin):
            tree = ast.parse(open(origin, encoding="utf-8", errors="replace").read(),
                             filename=origin)
            bad = sorted({name for name in imported_names(tree)
                          if any(name == b or name.startswith(b + ".") for b in LLM_IMPORTS)})
            if bad:
                offenders[os.path.basename(origin)] = bad
            n += 1
            collector_scanned = True
    except Exception:
        collector_scanned = False
    if offenders:
        return _claim(cid, method, VIOLATED, f"LLM/GenAI SDK import(s): {offenders}")
    if not collector_scanned:
        # the package is clean but part of the claimed scope was unreachable — abstain on
        # the FULL claim rather than passing on partial evidence (coverage-honesty)
        return _claim(cid, method, NOT_EVALUATED,
                      f"{n} analysis modules are LLM-free, but the collector entry "
                      f"{collector_module!r} source was not scannable — the full-pipeline "
                      "claim is not proven")
    return _claim(cid, method, HOLDS,
                  f"0 LLM/GenAI SDK imports across {n} modules "
                  "(analysis package + collector entry)")


# ------------------------------------------------------------------- panel ---
def compute_attestation(toolkit_dir=None, collector_module=_COLLECTOR_MODULE):
    """The attestation panel: {schema, generated_at, claims[4]} with every claim RE-DERIVED
    now, from this installation's actual registries and sources. `toolkit_dir` defaults to
    this package's own directory; override only to attest a different tree (tests use a
    synthetic tampered tree to prove the checks falsify)."""
    toolkit_dir = toolkit_dir or os.path.dirname(os.path.abspath(__file__))
    claims = []
    for build, args in ((_claim_read_only, (collector_module,)),
                        (_claim_no_egress, (toolkit_dir,)),
                        (_claim_rest_get_only, (os.path.join(toolkit_dir, "rest_collect.py"),)),
                        (_claim_no_llm, (toolkit_dir, collector_module))):
        try:
            claims.append(build(*args))
        except Exception as e:  # a claim builder crash is an abstention, never a default
            cid = CLAIM_IDS[len(claims)]
            claims.append(_claim(cid, "claim builder crashed before deriving a method",
                                 NOT_EVALUATED, f"claim could not be evaluated: {e!r}"))
    return {"schema": ATTESTATION_SCHEMA,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "claims": claims}
