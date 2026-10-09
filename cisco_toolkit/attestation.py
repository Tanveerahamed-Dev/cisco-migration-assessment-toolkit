"""Zero-egress attestation panel (roadmap D3; next-best-improvements-2026-07-04 do-first).

RE-DERIVES the engine's trust claims at build time — read-only command surface, no-egress
import graph, GET-only REST collector, no LLM in the runtime pipeline, and the confinement of the
opt-in legacy SSH tier (W59) — with the SAME mechanics as tests/test_readonly_and_no_egress.py
(which imports THIS module's grammar, so the shipped panel and the CI doctrine-guard can never
diverge). A falsifiable proof, never a hardcoded badge:

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
from types import MappingProxyType

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
             "rest_collect_get_only", "no_llm_runtime", "legacy_ssh_confined")

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

# Documented egress charter of the no-egress claim (same as the doctrine test). Every charter
# entry is PAIRED with a published claim that states that module's own floor, so the walk never
# subtracts anything the client is told nothing about. There are two kinds of entry:
# - a WHOLE-FILE exclusion (NO_EGRESS_EXCLUDE): rest_collect.py IS the opt-in controller-REST
#   collector — its floor (GET-only except the single login POST) is `rest_collect_get_only`;
# - a PER-FILE PERMITTED IMPORT (NO_EGRESS_PERMITTED_IMPORTS): legacy_ssh.py IS the opt-in legacy SSH
#   transport tier (W59 PR-2). It stays IN the walk, and only network imports rooted at paramiko are
#   permitted there, so a planted `socket` / `urllib.request` / `requests` import in it still VIOLATES
#   this claim (W59 PR-2 review P1-a: excluding the whole file left no check standing in for it). Its
#   floor (no command/channel/authentication call of its own, stock paramiko tables only ever copied, a
#   closed import allowlist, SHA-1 identifiers confined) is `legacy_ssh_confined`.
# Keyed by the path RELATIVE to the scanned package root (posix separators), because the walk is
# recursive: a bare basename would exempt a same-named file in ANY subpackage. (Until the walk was made
# recursive, `data/gen_port_registry.py` — one directory down, then the one documented EXCEPTION — was
# never scanned and its exception was DEAD CODE: the panel published "0 network-library imports" over a
# file that fetched iana.org. :func:`_claim_no_egress` now NAMES what it exempted and reports an
# exception or a permitted import that matched nothing, so an exemption cannot go dead again unnoticed.)
# The method/detail texts, the doctrine test and the paired-claim check all DERIVE from these mappings.
NO_EGRESS_CHARTER = MappingProxyType({
    "rest_collect.py": "rest_collect_get_only",
    "legacy_ssh.py": "legacy_ssh_confined",
})
NO_EGRESS_EXCLUDE = frozenset({"rest_collect.py"})
NO_EGRESS_PERMITTED_IMPORTS = MappingProxyType({
    "legacy_ssh.py": frozenset({"paramiko"}),
})
if set(NO_EGRESS_CHARTER) != NO_EGRESS_EXCLUDE | set(NO_EGRESS_PERMITTED_IMPORTS) \
        or NO_EGRESS_EXCLUDE & set(NO_EGRESS_PERMITTED_IMPORTS):
    raise ImportError("every no-egress charter entry must be exactly one whole-file exclusion or exactly one "
                      "per-file import permission, each paired with its published floor claim")
# NO_EGRESS_EXCEPTIONS is EMPTY, and that is the strong form of this claim rather than a gap in it.
#
# This set held "data/gen_port_registry.py" for as long as that generator fetched iana.org over
# `urllib.request`. It no longer imports urllib at all, so the exemption named a file that could no
# longer offend — a STALE CHARTER, which `_claim_no_egress` below is built to detect and report
# ("declared exception(s) that matched nothing"). Measured before removing it: `scan_imports` over
# the package walks 72 files, reaches `data/gen_port_registry.py`, and returns `offenders={}`.
#
# With the set empty the published Trust & Sovereignty claim reads "no documented exception was
# needed" instead of carrying a caveat that no longer applies. If any file here ever imports a
# network library again it lands in `unexplained` and the claim goes VIOLATED — which is the
# fail-closed direction, and the reason removing a dead exception costs nothing.
NO_EGRESS_EXCEPTIONS: frozenset = frozenset()

_COLLECTOR_MODULE = "COLLECT_PARSE_V3_23_0"

# ------------------------------------------------- legacy SSH tier confinement (W59 PR-2) ---
# The fifth claim's subject and the one module allowed to hold the SSH algorithm vocabulary, both as
# posix relpaths under the analysis package (the same keying as NO_EGRESS_CHARTER).
_LEGACY_SSH_MODULE = "legacy_ssh.py"
_SSH_VOCABULARY_MODULE = "ssh_session.py"

#: An SSH algorithm name whose exchange hash or host-key signature is SHA-1. Deliberately an
#: INDEPENDENT pattern rather than an import of the vocabulary owner (proposer != verifier, as with
#: ``is_read_only_command``): a name the owner forgot to grade is still caught here. MACs are out of
#: scope by design (HMAC does not rest on collision resistance; RFC 6194 §3.3). The RFC 6187 X.509
#: names signing with SHA-1 (``x509v3-ssh-*`` and the draft-era ``x509v3-sign-*``) are host-key names too
#: (W59 PR-2 review P3-f); ``tests/test_legacy_ssh.py`` holds every name of the owner's SHA-1 boundary to it.
SSH_SHA1_ALGORITHM = re.compile(
    r"^(?:diffie-hellman-[a-z0-9-]*-sha1"                      # SHA-1 exchange hash: fixed groups, GEX
    r"|gss-[a-z0-9-]*-sha1-[A-Za-z0-9+/=]+"                    # GSS-API key exchange over SHA-1
    r"|ssh-(?:rsa|dss)(?:-cert-v0[01]@openssh\.com)?"          # SHA-1 RSA / DSA host-key signatures
    r"|x509v3-(?:ssh|sign)-(?:rsa|dss))$")                     # RFC 6187 X.509 SHA-1 host-key signatures
# A string constant is split into tokens before matching, so a name inside prose or a list literal
# is still a literal; trailing sentence punctuation is stripped from each token.
_TOKEN_SPLIT = re.compile(r"[\s,;()\[\]{}<>'\"`|]+")

#: Calls the legacy module must never make: anything that sends, executes, authenticates or opens a
#: session. Matched as a PREFIX class plus the netmiko write family, not as one enumerated spelling,
#: so a new ``send_*`` helper is covered by construction.
_SEND_METHOD_PREFIXES = ("send", "_send", "write_", "exec_", "invoke_", "open_", "auth_", "start_")
_SEND_METHOD_NAMES = frozenset({
    "connect", "config_mode", "exit_config_mode", "save_config", "commit", "commit_config",
    "enable", "request_port_forward"})
#: Builtins that run code or import a module by NAME, past every import-statement rule below.
_DYNAMIC_CALLS = frozenset({"__import__", "eval", "exec", "compile", "getattr", "vars", "globals", "locals"})
#: Attributes that reach a class's tables or bases by reflection, around every name-based rule here.
_REFLECTIVE_ATTRS = frozenset({"__dict__", "__bases__", "__base__", "__mro__", "__class__", "__subclasses__",
                               "__globals__", "__builtins__"})
#: An inherited paramiko algorithm table, by attribute name (the stock tuples/dicts the tier extends).
_TABLE_ATTR = re.compile(r"^(?:_preferred_\w+|_\w+_info|HASHES|key_classes)$")
_MUTATING_METHODS = frozenset({
    "update", "setdefault", "__setitem__", "__delitem__", "pop", "popitem", "clear",
    "append", "extend", "insert", "remove", "__setattr__", "__delattr__"})
#: W59 PR-2 review (P2-c): the ONLY uses the legacy module may make of anything rooted in a paramiko binding
#: (a stock class, one of its tables, a paramiko module): a class BASE, or the operand of a COPY -- ``tuple(...)``,
#: a ``+`` chain, a ``{**...}`` display or ``MappingProxyType(...)``. Everything else (an alias, a method call, an
#: unbound ``dict.update(Transport._kex_info, ...)``, ``operator.setitem``, ``type.__setattr__(Transport, ...)``, a
#: subscript, an argument to any other call) is a violation: an allowlist of copy shapes, not a denylist of
#: mutation spellings.
_COPY_CALLS = frozenset({"tuple", "MappingProxyType"})
#: W59 PR-2 review (P1-a): the legacy module's CLOSED import allowlist (fully qualified imported names). It replaces
#: the no-egress walk's view of this one file: anything outside it -- a network library, ``importlib``, ``ctypes``,
#: ``subprocess`` -- is a violation, and among network libraries only paramiko may appear at all.
_LEGACY_SSH_IMPORTS_EXACT = frozenset({"hashlib", "paramiko", "cryptography.hazmat.primitives.hashes"})
_LEGACY_SSH_IMPORT_PREFIXES = ("__future__.", "types.", "paramiko.", "cisco_toolkit.ssh_session.", ".ssh_session.")
#: The tier's vocabulary names, by the owner's naming convention (``LEGACY_SHA1_TIER_KEX`` /
#: ``LEGACY_SHA1_TIER_HOST_KEYS``): the names the legacy module imports with this prefix are the tier.
_LEGACY_TIER_PREFIX = "LEGACY_SHA1_TIER_"


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
    # Built FROM the live sets, never restated alongside them. This paragraph previously named
    # `data/gen_port_registry.py` as a documented exception in prose while NO_EGRESS_EXCEPTIONS had
    # been emptied, so the published claim contradicted itself: METHOD announced an exception that
    # DETAIL simultaneously reported as "no documented exception was needed". Worse, the test that
    # checks exclusions are DISCLOSED was satisfied by the stale prose alone, so it pinned the
    # contradiction in place instead of catching it. A duplicated fact is a cache; derive it.
    # The charter entries (and the claim each one is paired with) are derived from the same
    # mappings, so adding an exclusion or a permission without a published floor claim cannot read
    # as covered.
    _exclude_txt = (", ".join(sorted(NO_EGRESS_EXCLUDE)) or "none")
    _charter_txt = ("; ".join(
        (f"{rel} excluded whole" if rel in NO_EGRESS_EXCLUDE else
         f"{rel} scanned with only {', '.join(sorted(NO_EGRESS_PERMITTED_IMPORTS.get(rel, ())))} permitted")
        + f" (covered by its own published claim {cid})"
        for rel, cid in sorted(NO_EGRESS_CHARTER.items())) or "none")
    _except_txt = (", ".join(sorted(NO_EGRESS_EXCEPTIONS))
                   or "none — the package is clean without subtracting anything")
    method = ("RECURSIVE AST import-walk (every subpackage, any nesting depth, lazy imports "
              "included) over the analysis package for network libraries; charter entries, "
              f"each opt-in collector paired with its own floor claim: {_charter_txt}; "
              f"documented exception(s), subtracted AFTER the scan and named in the result: "
              f"{_except_txt}")
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
    # A per-file charter permission is applied FIRST and only to its own file, and only to imports
    # rooted at a permitted library: anything else that file imports stays an offender (P1-a).
    permitted, remaining = {}, {}
    for rel, bad in offenders.items():
        roots = NO_EGRESS_PERMITTED_IMPORTS.get(rel, frozenset())
        ok = [b for b in bad if b.split(".")[0] in roots]
        rest = [b for b in bad if b.split(".")[0] not in roots]
        if ok:
            permitted[rel] = ok
        if rest:
            remaining[rel] = rest
    # Documented exceptions are subtracted HERE, and disclosed: what was exempted (with the
    # import that made it an offender) and any declared exception that matched NOTHING — a
    # never-firing exception means either the walk cannot see the file or the charter is stale.
    exempt = {rel: bad for rel, bad in remaining.items() if rel in NO_EGRESS_EXCEPTIONS}
    unexplained = {rel: bad for rel, bad in remaining.items() if rel not in NO_EGRESS_EXCEPTIONS}
    stale = sorted(e for e in NO_EGRESS_EXCEPTIONS if e not in remaining)
    stale_permitted = sorted(rel for rel in NO_EGRESS_PERMITTED_IMPORTS if rel not in permitted)
    if unexplained:
        return _claim(cid, method, VIOLATED,
                      f"network-egress import(s) in the offline analysis pipeline: {unexplained}")
    permitted_txt = ("; network imports permitted by charter: "
                     + ", ".join(f"{rel} -> {', '.join(sorted(NO_EGRESS_PERMITTED_IMPORTS[rel]))} only "
                                 f"({len(bad)} import name(s))" for rel, bad in sorted(permitted.items()))
                     if permitted else "")
    exempt_txt = ("; documented exception(s) applied: "
                  + ", ".join(f"{rel} -> {','.join(bad)}" for rel, bad in sorted(exempt.items()))
                  if exempt else "; no documented exception was needed")
    stale_txt = (f"; declared exception(s) that matched nothing (stale charter?): {stale}"
                 if stale else "")
    stale_txt += (f"; declared import permission(s) that matched nothing (stale charter?): {stale_permitted}"
                  if stale_permitted else "")
    return _claim(cid, method, HOLDS,
                  f"0 unexplained network-library imports across {n} analysis modules "
                  f"(recursive walk; excluded by charter: {_exclude_txt}{permitted_txt}{exempt_txt}{stale_txt})")


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
    method = ("AST import-walk over the analysis package (its no-egress charter entries "
              f"{', '.join(sorted(NO_EGRESS_CHARTER)) or 'none'} included) + the "
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


# ------------------------------------------ legacy SSH tier confinement mechanics (W59) ---
def ssh_sha1_literals(tree):
    """``[(lineno, name)]`` for every string token in a parsed module that names an SSH algorithm with
    a SHA-1 exchange hash or host-key signature (:data:`SSH_SHA1_ALGORITHM`). Docstrings and f-string
    parts are string constants too, so prose that spells such a name counts — comments do not reach the
    AST. Shared with ``tests/test_legacy_ssh.py``'s shipped-file scan."""
    hits = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, (str, bytes)):
            continue
        text = node.value if isinstance(node.value, str) else node.value.decode("latin-1")
        for token in _TOKEN_SPLIT.split(text):
            token = token.strip(".:")
            if token and SSH_SHA1_ALGORITHM.match(token):
                hits.add((getattr(node, "lineno", 0), token))
    return sorted(hits)


def _root_and_attrs(node):
    """The root ``Name`` of an attribute/subscript/call chain and every attribute name along it."""
    attrs = []
    while True:
        if isinstance(node, ast.Attribute):
            attrs.append(node.attr)
            node = node.value
        elif isinstance(node, (ast.Subscript, ast.Starred)):
            node = node.value
        elif isinstance(node, ast.Call):
            node = node.func
        else:
            break
    return (node.id if isinstance(node, ast.Name) else None), attrs


def _paramiko_bindings(tree):
    """Every local name a module binds to paramiko or to something imported from it."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "paramiko" or alias.name.startswith("paramiko."):
                    names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            mod = node.module or ""
            if mod == "paramiko" or mod.startswith("paramiko."):
                names.update(alias.asname or alias.name for alias in node.names)
    return names


def _store_targets(node):
    """Attribute / subscript STORE targets of an assignment-like node (tuple targets unpacked)."""
    if isinstance(node, (ast.Assign, ast.Delete)):
        pending = list(node.targets)
    elif isinstance(node, (ast.AugAssign, ast.AnnAssign, ast.For, ast.AsyncFor, ast.comprehension)):
        pending = [node.target]
    elif isinstance(node, ast.withitem):
        pending = [node.optional_vars] if node.optional_vars is not None else []
    else:
        return []
    out = []
    while pending:
        target = pending.pop()
        if isinstance(target, (ast.Tuple, ast.List)):
            pending.extend(target.elts)
        elif isinstance(target, ast.Starred):
            pending.append(target.value)
        elif isinstance(target, (ast.Attribute, ast.Subscript)):
            out.append(target)
    return out


def _is_tuple_call(node):
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tuple"


def _add_leaves(node):
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _add_leaves(node.left) + _add_leaves(node.right)
    return [node]


def _is_frozen_table_value(value):
    """A table definition is frozen when it is a tuple display, ``tuple(...)``, ``MappingProxyType(...)``,
    or a ``+`` chain of tuples and references with at least one tuple operand (tuple + list raises)."""
    if isinstance(value, ast.Tuple) or _is_tuple_call(value):
        return True
    if isinstance(value, ast.Call):
        fn = value.func
        name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
        return name == "MappingProxyType"
    if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add):
        leaves = _add_leaves(value)
        return (all(isinstance(leaf, (ast.Tuple, ast.Attribute, ast.Name)) or _is_tuple_call(leaf)
                    for leaf in leaves)
                and any(isinstance(leaf, ast.Tuple) or _is_tuple_call(leaf) for leaf in leaves))
    return False


def _parent_map(tree):
    """id(child) -> parent node, for every node of a parsed module."""
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def _maximal_chain(node, parents):
    """``(chain, parent)``: the outermost attribute / subscript chain whose innermost value is ``node``."""
    cur = node
    while True:
        parent = parents.get(id(cur))
        if isinstance(parent, (ast.Attribute, ast.Subscript)) and parent.value is cur:
            cur = parent
        else:
            return cur, parent


def _is_copy_use(chain, parent):
    """True when ``chain`` is a class base or the operand of a COPY: ``tuple(<chain>)``,
    ``MappingProxyType(<chain>)``, a ``{**<chain>}`` display, or an operand of ``+``."""
    if isinstance(parent, ast.ClassDef):
        return any(base is chain for base in parent.bases)
    if isinstance(parent, ast.Call):
        fn = parent.func
        name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
        return (name in _COPY_CALLS and fn is not chain and not parent.keywords
                and len(parent.args) == 1 and parent.args[0] is chain)
    if isinstance(parent, ast.Dict):
        return any(key is None and value is chain for key, value in zip(parent.keys, parent.values))
    if isinstance(parent, ast.BinOp) and isinstance(parent.op, ast.Add):
        return parent.left is chain or parent.right is chain
    return False


def _paramiko_use_violations(tree, pm_names):
    """W59 PR-2 review (P2-c), an ALLOWLIST: every expression rooted in a paramiko binding, and every
    attribute named like an inherited algorithm table (:data:`_TABLE_ATTR`) whatever its root, may only be a
    class base or the operand of a copy (:func:`_is_copy_use`). An alias, a method call, a subscript, an
    argument to any other call (``dict.update(Transport._kex_info, ...)``, ``operator.setitem``,
    ``type.__setattr__(Transport, ...)``), a store, a delete or a rebinding is a violation."""
    parents = _parent_map(tree)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in pm_names:
            if not isinstance(node.ctx, ast.Load):
                out.append(f"line {node.lineno}: rebinds or deletes the paramiko binding {node.id}")
                continue
        elif not (isinstance(node, ast.Attribute) and _TABLE_ATTR.match(node.attr)):
            continue
        chain, parent = _maximal_chain(node, parents)
        if not isinstance(getattr(chain, "ctx", ast.Load()), ast.Load):
            out.append(f"line {chain.lineno}: stores into or deletes {ast.unparse(chain)} (a paramiko table)")
        elif not _is_copy_use(chain, parent):
            out.append(f"line {chain.lineno}: uses {ast.unparse(chain)} other than as a class base or the "
                       "operand of a copy (tuple(...), +, {**...}, MappingProxyType(...))")
    return out


def legacy_import_violations(tree):
    """W59 PR-2 review (P1-a): every import of the legacy module against its CLOSED allowlist
    (:data:`_LEGACY_SSH_IMPORTS_EXACT` / :data:`_LEGACY_SSH_IMPORT_PREFIXES`), lazy imports included, and every
    network-library import (:data:`NETWORK_IMPORTS`) that is not rooted at paramiko. With the no-egress walk's
    per-file permission, this is what judges the one file whose paramiko imports that walk accepts."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = "." * node.level + (node.module or "")
            names = [f"{base}.{alias.name}" if base and not base.endswith(".") else f"{base}{alias.name}"
                     for alias in node.names]
        else:
            continue
        for name in names:
            if name not in _LEGACY_SSH_IMPORTS_EXACT and not name.startswith(_LEGACY_SSH_IMPORT_PREFIXES):
                out.append(f"line {node.lineno}: imports {name} (outside the closed import allowlist)")
            if any(name == net or name.startswith(net + ".") for net in NETWORK_IMPORTS) \
                    and name.split(".")[0] != "paramiko":
                out.append(f"line {node.lineno}: imports the network library {name} (only paramiko is "
                           "permitted)")
    return out


def legacy_module_violations(tree):
    """``(violations, n_tables)`` for the legacy module's own floor: no command/channel/authentication/session
    call of its own and no dynamic import or reflection; a closed import allowlist with paramiko the only network
    library (:func:`legacy_import_violations`); every use of a paramiko binding or of an inherited algorithm table
    a class base or a COPY (:func:`_paramiko_use_violations`), and no store into or mutating call on one; and every
    table it defines frozen. Each violation names its line."""
    violations = []
    pm_names = _paramiko_bindings(tree)
    n_tables = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else "")
            if name and (name.startswith(_SEND_METHOD_PREFIXES) or name in _SEND_METHOD_NAMES):
                violations.append(f"line {node.lineno}: calls {name}() (a send/session method)")
            if isinstance(fn, ast.Name) and fn.id in _DYNAMIC_CALLS:
                violations.append(f"line {node.lineno}: calls {fn.id}() (dynamic code, import or lookup)")
            if isinstance(fn, ast.Attribute) and fn.attr in _MUTATING_METHODS:
                root, attrs = _root_and_attrs(fn.value)
                if root in pm_names or any(_TABLE_ATTR.match(a) for a in attrs):
                    violations.append(f"line {node.lineno}: mutating call .{fn.attr}() on a "
                                      "paramiko table")
            if isinstance(fn, ast.Name) and fn.id in ("setattr", "delattr") and node.args:
                root, attrs = _root_and_attrs(node.args[0])
                named = (len(node.args) > 1 and isinstance(node.args[1], ast.Constant)
                         and isinstance(node.args[1].value, str)
                         and bool(_TABLE_ATTR.match(node.args[1].value)))
                if root in pm_names or any(_TABLE_ATTR.match(a) for a in attrs) or named:
                    violations.append(f"line {node.lineno}: {fn.id}() on a paramiko table")
        if isinstance(node, ast.Attribute) and node.attr in _REFLECTIVE_ATTRS:
            violations.append(f"line {node.lineno}: reflective attribute {node.attr} (a route around the "
                              "table rules)")
        for target in _store_targets(node):
            root, attrs = _root_and_attrs(target)
            if root in pm_names or any(_TABLE_ATTR.match(a) for a in attrs):
                violations.append(f"line {target.lineno}: store into a paramiko table "
                                  f"({'.'.join([root or '?', *reversed(attrs)])})")
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and _TABLE_ATTR.match(target.id):
                    n_tables += 1
                    if node.value is None or not _is_frozen_table_value(node.value):
                        violations.append(f"line {node.lineno}: table {target.id} is not a tuple "
                                          "or a MappingProxyType")
    violations += _paramiko_use_violations(tree, pm_names)
    violations += legacy_import_violations(tree)
    return sorted(set(violations)), n_tables


def _legacy_tier_names(tree):
    """The vocabulary names the legacy module imports from the vocabulary owner with the
    :data:`_LEGACY_TIER_PREFIX` prefix — the legacy tier, as the module itself declares it."""
    stem = _SSH_VOCABULARY_MODULE[:-3]
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[-1] == stem:
            names.update(alias.name for alias in node.names if alias.name.startswith(_LEGACY_TIER_PREFIX))
    return names


def _confinement_violations(rel, tree, tier_names):
    """Identifier confinement for one module OTHER than the legacy module. A tier name is matched BY NAME,
    whatever owner alias reads it (``S.LEGACY_SHA1_TIER_KEX``, ``vocab.LEGACY_SHA1_TIER_KEX``), and as a string
    (``getattr(ssh_session, "LEGACY_SHA1_TIER_KEX")``)."""
    stem = _SSH_VOCABULARY_MODULE[:-3]
    out = []
    if rel != _SSH_VOCABULARY_MODULE:
        out += [f"{rel}:{ln}: SSH SHA-1 algorithm literal {tok!r} outside the vocabulary owner"
                for ln, tok in ssh_sha1_literals(tree)]
    for node in ast.walk(tree):
        if rel != _SSH_VOCABULARY_MODULE:
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[-1] == stem:
                hit = sorted(a.name for a in node.names if a.name in tier_names or a.name == "*")
                if hit:
                    out.append(f"{rel}:{node.lineno}: imports legacy-tier name(s) {hit}")
            elif isinstance(node, ast.Attribute) and node.attr in tier_names:
                out.append(f"{rel}:{node.lineno}: reads legacy-tier name {node.attr}")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in tier_names:
                out.append(f"{rel}:{node.lineno}: names legacy-tier name {node.value} as a string")
        if isinstance(node, ast.Attribute) and node.attr == "SHA1":
            out.append(f"{rel}:{node.lineno}: hashes.SHA1 outside {_LEGACY_SSH_MODULE}")
        elif isinstance(node, ast.ImportFrom) and any(a.name == "SHA1" for a in node.names):
            out.append(f"{rel}:{node.lineno}: imports SHA1 outside {_LEGACY_SSH_MODULE}")
    return out


def _collector_source(collector_module):
    try:
        spec = importlib.util.find_spec(collector_module)
    except Exception:
        return None
    origin = getattr(spec, "origin", None) if spec else None
    return origin if origin and os.path.isfile(origin) else None


def _claim_legacy_ssh_confined(toolkit_dir, collector_module):
    method = (f"source/AST scan of {_LEGACY_SSH_MODULE}, the opt-in legacy SSH transport tier (the one module "
              "whose paramiko imports the no-egress walk permits): its imports are inside a CLOSED allowlist "
              "(__future__, hashlib, types, cryptography's hashes, paramiko, the vocabulary owner) and paramiko "
              "is its only network library; it makes no command/channel/authentication/session call of its "
              "own, no dynamic import or eval and no reflective attribute access; anything rooted in a paramiko "
              "binding, and any inherited algorithm table, is used only as a class base or the operand of a "
              "copy (tuple(...), +, {**...}, MappingProxyType(...)) -- never aliased, called, subscripted, "
              "passed to another call, stored into or mutated -- and every table it defines is a tuple or a "
              "MappingProxyType; and, across the analysis package + the collector entry, SSH algorithm names "
              f"with a SHA-1 exchange hash or host-key signature appear as literals only in "
              f"{_SSH_VOCABULARY_MODULE}, the legacy-tier vocabulary names (prefix {_LEGACY_TIER_PREFIX}) are "
              f"read only by {_LEGACY_SSH_MODULE}, and hashes.SHA1 appears only in {_LEGACY_SSH_MODULE}")
    cid = "legacy_ssh_confined"
    legacy_path = os.path.join(toolkit_dir, _LEGACY_SSH_MODULE)
    if not os.path.isfile(legacy_path):
        return _claim(cid, method, NOT_EVALUATED,
                      f"{_LEGACY_SSH_MODULE} source not available at {legacy_path!r} — "
                      "the confinement of the legacy SSH tier cannot be re-derived")
    try:
        legacy_tree = ast.parse(open(legacy_path, encoding="utf-8", errors="replace").read(),
                                filename=legacy_path)
        violations, n_tables = legacy_module_violations(legacy_tree)
        violations = [f"{_LEGACY_SSH_MODULE} {v}" for v in violations]
        # The tier takes every algorithm name from the vocabulary owner; it restates none itself.
        violations += [f"{_LEGACY_SSH_MODULE}:{ln}: SSH SHA-1 algorithm literal {tok!r} outside the "
                       "vocabulary owner" for ln, tok in ssh_sha1_literals(legacy_tree)]
        tier_names = _legacy_tier_names(legacy_tree)
        modules = [(rel, path) for rel, path in _iter_py(toolkit_dir) if rel != _LEGACY_SSH_MODULE]
        collector = _collector_source(collector_module)
        if collector:
            modules.append((os.path.basename(collector), collector))
        n_vocab = 0
        for rel, path in modules:
            tree = ast.parse(open(path, encoding="utf-8", errors="replace").read(), filename=path)
            if rel == _SSH_VOCABULARY_MODULE:
                n_vocab = len(ssh_sha1_literals(tree))
            violations += _confinement_violations(rel, tree, tier_names)
    except (OSError, SyntaxError, ValueError) as e:
        return _claim(cid, method, NOT_EVALUATED, f"source walk failed: {e!r}")
    if violations:
        return _claim(cid, method, VIOLATED,
                      "legacy SSH tier not confined: " + "; ".join(violations[:20])
                      + (f"; … {len(violations) - 20} more" if len(violations) > 20 else ""))
    # Non-vacuity: each rule must have had a subject, or its silence proves nothing.
    if n_tables == 0:
        return _claim(cid, method, NOT_EVALUATED,
                      f"{_LEGACY_SSH_MODULE} defines no algorithm table — the frozen-table rule had "
                      "nothing to judge (refusing a vacuous pass)")
    if not tier_names:
        return _claim(cid, method, NOT_EVALUATED,
                      f"{_LEGACY_SSH_MODULE} imports no {_LEGACY_TIER_PREFIX}* vocabulary name from "
                      f"{_SSH_VOCABULARY_MODULE} — the tier-confinement rule had no subject")
    if n_vocab == 0:
        return _claim(cid, method, NOT_EVALUATED,
                      f"the SHA-1 algorithm pattern recognised no literal in {_SSH_VOCABULARY_MODULE} "
                      "(absent, or the pattern no longer matches the vocabulary) — it cannot be shown "
                      "to recognise the names it confines")
    if not collector:
        return _claim(cid, method, NOT_EVALUATED,
                      f"{_LEGACY_SSH_MODULE} and {len(modules)} analysis modules are confined, but the "
                      f"collector entry {collector_module!r} source was not scannable — the full "
                      "confinement claim is not proven")
    return _claim(cid, method, HOLDS,
                  f"{_LEGACY_SSH_MODULE}: imports inside the closed allowlist, paramiko the only network "
                  f"library; no command/channel/authentication/session call of its own; paramiko bindings and "
                  f"inherited tables used only as class bases or copied; {n_tables} table(s) defined, each "
                  f"frozen; SHA-1 SSH algorithm literals only in "
                  f"{_SSH_VOCABULARY_MODULE} ({n_vocab} recognised there) across {len(modules)} other "
                  f"modules (analysis package + collector entry); legacy-tier name(s) "
                  f"{', '.join(sorted(tier_names))} read only by {_LEGACY_SSH_MODULE}; hashes.SHA1 only "
                  f"in {_LEGACY_SSH_MODULE}")


# ------------------------------------------------------------------- panel ---
def compute_attestation(toolkit_dir=None, collector_module=_COLLECTOR_MODULE):
    """The attestation panel: {schema, generated_at, claims[len(CLAIM_IDS)]} with every claim
    RE-DERIVED now, from this installation's actual registries and sources. `toolkit_dir` defaults
    to this package's own directory; override only to attest a different tree (tests use a
    synthetic tampered tree to prove the checks falsify)."""
    toolkit_dir = toolkit_dir or os.path.dirname(os.path.abspath(__file__))
    claims = []
    for build, args in ((_claim_read_only, (collector_module,)),
                        (_claim_no_egress, (toolkit_dir,)),
                        (_claim_rest_get_only, (os.path.join(toolkit_dir, "rest_collect.py"),)),
                        (_claim_no_llm, (toolkit_dir, collector_module)),
                        (_claim_legacy_ssh_confined, (toolkit_dir, collector_module))):
        try:
            claims.append(build(*args))
        except Exception as e:  # a claim builder crash is an abstention, never a default
            cid = CLAIM_IDS[len(claims)]
            claims.append(_claim(cid, "claim builder crashed before deriving a method",
                                 NOT_EVALUATED, f"claim could not be evaluated: {e!r}"))
    return {"schema": ATTESTATION_SCHEMA,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "claims": claims}
