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
_SSH_SHA1_NAME = (r"(?:diffie-hellman-[a-z0-9-]*-sha1"         # SHA-1 exchange hash: fixed groups, GEX
                  r"|gss-[a-z0-9-]*-sha1-[A-Za-z0-9+/=]+"       # GSS-API key exchange over SHA-1
                  r"|ssh-(?:rsa|dss)(?:-cert-v0[01]@openssh\.com)?"   # SHA-1 RSA / DSA host-key signatures
                  r"|x509v3-(?:ssh|sign)-(?:rsa|dss))")         # RFC 6187 X.509 SHA-1 host-key signatures
SSH_SHA1_ALGORITHM = re.compile("^" + _SSH_SHA1_NAME + "$")
#: A character that continues an SSH algorithm name: a letter, a digit or '-' (the registered names, RFC 4251 §6),
#: '@' (which joins a local name to its domain) and '_' (an identifier or file-name character, so ``id_ssh-rsa`` is
#: another word). A '.' continues a name only when a letter or digit follows it (the domain of a local name), so a
#: name that ends a sentence is still a name.
_SSH_NAME_CONTINUES = r"[A-Za-z0-9_@-]"
#: W59 PR-2 review round 3 (P3): a SHA-1 name is found wherever it occurs in a string constant, anchored at each end
#: by the string's edge or by ANY character that cannot continue the name -- not by a hand-kept list of delimiters,
#: so a name joined to its neighbour by '=', '/', ':', '+', '#' or any other non-name character is still a literal.
#: (A GSS-API name's base64 tail is part of the name, so its '+', '/' and '=' are consumed by the name itself.)
_SSH_SHA1_IN_TEXT = re.compile("(?<!" + _SSH_NAME_CONTINUES + ")" + _SSH_SHA1_NAME
                               + "(?!" + _SSH_NAME_CONTINUES + r"|\.[A-Za-z0-9])")

#: Calls the legacy module must never make: anything that sends, executes, authenticates or opens a
#: session, as a PREFIX class plus the netmiko write family. W59 PR-2 review round 2 (P2): this is no longer the
#: rule that closes the class -- ``t.global_request(...)``, ``t.renegotiate_keys()`` and ``chan.get_pty()`` walked
#: past it. The closed call-site allowlist (:data:`_LEGACY_SSH_CALL_SITES`) is; these only NAME the common shapes
#: in a violation's text.
_SEND_METHOD_PREFIXES = ("send", "_send", "write_", "exec_", "invoke_", "open_", "auth_", "start_")
_SEND_METHOD_NAMES = frozenset({
    "connect", "config_mode", "exit_config_mode", "save_config", "commit", "commit_config",
    "enable", "request_port_forward"})
#: Builtins that run code, import a module by NAME, or read or write an attribute by a computed name, past every
#: import-statement, call and attribute rule below. W59 PR-2 review round 2 (P2): each is a violation wherever its
#: NAME appears (called, aliased or passed), not only when it is called with a paramiko-rooted argument.
_DYNAMIC_CALLS = frozenset({"__import__", "eval", "exec", "compile", "getattr", "setattr", "delattr", "vars",
                            "globals", "locals", "breakpoint", "__builtins__"})
#: Attributes that reach a class's tables, bases or attribute machinery by reflection, around every name-based rule
#: here. W59 PR-2 review round 2 (P2): ``mro`` (``setattr(type(t).mro()[-2], n, v)`` widened paramiko's Transport for
#: every thread), ``__setattr__`` / ``__delattr__`` / ``__getattribute__`` and the descriptor hooks are flagged
#: outright. The closed attribute allowlist (:data:`_LEGACY_SSH_ATTRIBUTES`) is what closes the class; this set names
#: the reflective shapes in a violation's text.
_REFLECTIVE_ATTRS = frozenset({"__dict__", "__bases__", "__base__", "__mro__", "__class__", "__subclasses__",
                               "__globals__", "__builtins__", "mro", "__setattr__", "__delattr__",
                               "__getattribute__", "__getattr__", "__new__", "__init_subclass__", "__set_name__",
                               "__code__", "__closure__", "__func__", "__self__", "__wrapped__"})
#: An inherited paramiko algorithm table, by attribute name (the stock tuples/dicts the tier extends).
_TABLE_ATTR = re.compile(r"^(?:_preferred_\w+|_\w+_info|HASHES|key_classes)$")
_MUTATING_METHODS = frozenset({
    "update", "setdefault", "__setitem__", "__delitem__", "pop", "popitem", "clear",
    "append", "extend", "insert", "remove", "__setattr__", "__delattr__"})
#: W59 PR-2 review (P2-c): the ONLY uses the legacy module may make of anything rooted in a paramiko binding
#: (a stock class, one of its tables, a paramiko module): a class BASE, the operand of a COPY -- a ``+`` chain, a
#: ``{**...}`` display or one of :data:`_COPY_CALLS` -- or of a NAME-LIST rendering (:data:`_NAME_LIST_CALLS`).
#: Everything else (an alias, a method call, an unbound ``dict.update(Transport._kex_info, ...)``,
#: ``operator.setitem``, ``type.__setattr__(Transport, ...)``, a subscript, an argument to any other call) is a
#: violation: an allowlist of copy shapes, not a denylist of mutation spellings.
#:
#: W59 PR-2 review round 3 (P2): each copy is a full CALL SIGNATURE (:func:`call_signature`: callee spelling, positional
#: count, sorted keyword names), so ``sorted(x)`` is a copy and ``sorted(x, key=f)``, which calls ``f``, is not. A
#: copy's RESULT holds its operand's members, so the T8 taint model (:class:`_Env`) carries a tainted member through
#: it: ``MappingProxyType({profile: LegacySHA1Transport})`` is as connection-capable as the class it holds. Only a
#: copy of untainted contents is clean.
_COPY_CALLS = frozenset({
    ("tuple", 1, ()), ("MappingProxyType", 1, ()), ("sorted", 1, ()), ("dict.fromkeys", 1, ()),
})
#: W59 PR-2 review round 3 (P2): the one PROJECTION a connection-capable value may be handed to -- rendering an
#: algorithm table as an SSH name-list (RFC 4251 §5: comma-separated names, which RFC 4251 §6 forbids to contain a
#: comma). ``str.join`` accepts only ``str`` members and calls none of them (any other member raises TypeError), so its
#: result is a ``str`` that cannot carry a class or a callable: the taint model treats it as clean, by construction.
_NAME_LIST_CALLS = frozenset({("','.join", 1, ())})
#: W59 PR-2 review (P1-a): the legacy module's CLOSED import allowlist (fully qualified imported names). It replaces
#: the no-egress walk's view of this one file: anything outside it -- a network library, ``importlib``, ``ctypes``,
#: ``subprocess`` -- is a violation, and among network libraries only paramiko may appear at all.
#: W59 PR-2 review round 2 (P2): EXACT names only, no prefix. The prefixes ``paramiko.`` and
#: ``cisco_toolkit.ssh_session.`` admitted anything those modules bind, a re-exported module included
#: (``from paramiko.transport import socket``, ``from cisco_toolkit.ssh_session import os`` then ``os.system(...)``).
#: ``tests/test_readonly_and_no_egress.py`` pins the paramiko names from the other side.
_LEGACY_SSH_IMPORTS_EXACT = frozenset({
    "__future__.annotations",
    "hashlib",
    "types.MappingProxyType", "types.SimpleNamespace",
    "cryptography.hazmat.primitives.hashes",
    "paramiko.kex_gex.KexGexSHA256", "paramiko.kex_group14.KexGroup14SHA256", "paramiko.rsakey.RSAKey",
    "paramiko.ssh_exception.IncompatiblePeer", "paramiko.transport.Transport",
})
#: The names the tier may import from the vocabulary owner (``cisco_toolkit.ssh_session``, or ``.ssh_session``
#: package-relative): the pinned PR-1 / PR-2 interface of the design (§4.2). The non-tier names are listed here; the
#: tier tuples themselves are admitted by the owner's naming convention (:data:`_LEGACY_TIER_NAME`, the same
#: derivation :func:`_legacy_tier_names` uses), because this module may not spell a tier name as a string -- the
#: confinement rule below holds every module but the tier to that. In both cases the name must be one the owner does
#: NOT bind through an import statement (the owner imports os, json, re, threading, time ...), and the call-site and
#: attribute allowlists confine whatever is imported to data use.
_LEGACY_SSH_IMPORTS_VOCABULARY = frozenset({
    "DEFAULT_PROFILE", "DH_FLOOR_BITS", "LEGACY_SHA1_PROFILE", "SSH_PROFILES", "ObservingTransportMixin",
    "permits_sha1",
})
#: W59 PR-2 review round 2 (P2): the legacy module's CLOSED call-site allowlist, ``{qualified enclosing def: call
#: signatures}`` (``<module>`` for module level and class bodies). Every call it makes -- an ``ast.Call``, a decorator,
#: a class keyword -- must be listed under its own enclosing def. Anything else is a violation: a method of a
#: runtime-reached object (``t.global_request(...)``, ``chan.get_pty()``), a class derived from paramiko
#: (``LegacySHA1Transport((host, port))`` opens a TCP connection), ``setattr``, ``os.system``. It replaces the
#: denylist of send-method spellings as the rule that closes the class. With the binding rule below (one binding per
#: scope, no builtin shadowed), a listed spelling always means the binding it names.
#:
#: W59 PR-2 review round 3 (P2): a site is its FULL call signature (:func:`call_signature`), not the callee's spelling
#: alone -- ``sorted(names)`` is listed, so ``sorted(names, key=LegacySHA1Transport)``, an implicit call of the class
#: under an allowlisted spelling, is not. A decorator is the call ``("@<spelling>", 1, ())`` (it is handed the def) and
#: a class keyword ``("<keyword>=<spelling>", 3, ())`` (the metaclass protocol: name, bases, namespace).
_LEGACY_SSH_CALL_SITES = MappingProxyType({
    "<module>": frozenset({
        ("ImportError", 1, ()), ("MappingProxyType", 1, ()), ("_HOST_KEY_RSA_SHA1_CERT.startswith", 1, ()),
        ("dict.fromkeys", 1, ()), ("len", 1, ()), ("tuple", 1, ())}),
    "WeakGroupRefused.__init__": frozenset({("int", 1, ()), ("super", 0, ()), ("super().__init__", 1, ())}),
    "LegacyKexGexSHA1._parse_kexdh_gex_group": frozenset({
        ("WeakGroupRefused", 2, ()), ("m.asbytes", 0, ()), ("prime.bit_length", 0, ()), ("probe.get_mpint", 0, ()),
        ("super", 0, ()), ("super()._parse_kexdh_gex_group", 1, ()), ("type", 1, ()), ("type(m)", 1, ())}),
    "_names_of": frozenset({("name_list.split", 1, ()), ("tuple", 1, ())}),
    "default_permits_sha1": frozenset({
        ("','.join", 1, ()), ("SimpleNamespace", 0, ("HASHES",)),
        ("SimpleNamespace", 0, ("_kex_info", "_key_info", "_preferred_kex", "_preferred_keys")),
        ("_names_of", 1, ()), ("bool", 1, ()), ("permits_sha1", 2, ())}),
    "transport_for": frozenset({
        ("LegacyTransportUnavailable", 1, ()), ("ValueError", 1, ()), ("default_permits_sha1", 0, ()),
        ("isinstance", 2, ()), ("sorted", 1, ())}),
})
#: W59 PR-2 review round 2 (P2): the CLOSED attribute allowlist -- every attribute name the legacy module reads or
#: writes. Reflection (``mro``, ``__class__``, ``__dict__``, ``__setattr__``, ...) and any attribute of a
#: runtime-reached object the tier does not need (``self.transport``, ``t.sock``) fall outside it. It replaces the
#: denylist of reflective attributes as the rule that closes the class.
_LEGACY_SSH_ATTRIBUTES = frozenset({
    "HASHES", "SHA1", "__init__", "_kex_info", "_key_info", "_parse_kexdh_gex_group", "_preferred_kex",
    "_preferred_keys", "asbytes", "bit_length", "floor_bits", "fromkeys", "get_mpint", "join", "offered_bits", "sha1",
    "split", "startswith",
})
#: W59 PR-2 review round 2 (P2): the CLOSED statement and expression grammar of the legacy module, by AST node type
#: (the forms it uses, plus the comparison, boolean, unary-minus and ``pass`` siblings of those). Deliberately absent: ``with``,
#: ``for``, ``while``, ``try``, ``match``, ``async`` / ``await``, ``yield``, ``lambda``, comprehensions, ``global`` /
#: ``nonlocal``, ``del``, augmented and annotated assignment, the walrus, starred and list / set displays -- each an
#: implicit call or a rebinding route the call, attribute and binding rules would not see. (A decorator or a class
#: keyword is an expression, not a node type: the call-site rule treats each as a call.)
_LEGACY_SSH_GRAMMAR = frozenset({
    "Module", "Expr", "Pass", "Import", "ImportFrom", "alias", "ClassDef", "FunctionDef", "arguments", "arg",
    "Assign", "If", "Raise", "Return",
    "Call", "keyword", "Attribute", "Subscript", "Name", "Load", "Store", "Constant", "Tuple", "Dict", "IfExp",
    "JoinedStr", "FormattedValue", "BinOp", "Add", "BoolOp", "And", "Or", "UnaryOp", "Not", "USub", "Compare",
    "Eq", "NotEq", "Lt", "LtE", "Gt", "GtE", "In", "NotIn", "Is", "IsNot",
})
#: The implicit-call and rebinding forms the comment above names as deliberately absent, by AST node type. Only the
#: method TEXT reads this: it prints those still absent from :data:`_LEGACY_SSH_GRAMMAR`, so a form admitted to the
#: grammar drops out of the published sentence instead of being misreported as excluded.
_GRAMMAR_ROUTES_NAMED = (
    "With", "AsyncWith", "For", "AsyncFor", "While", "Try", "Match", "AsyncFunctionDef", "Await", "Yield",
    "YieldFrom", "Lambda", "ListComp", "SetComp", "DictComp", "GeneratorExp", "Global", "Nonlocal", "Delete",
    "AugAssign", "AnnAssign", "NamedExpr", "Starred", "List", "Set",
)
#: The tier's vocabulary names, by the owner's naming convention (``LEGACY_SHA1_TIER_KEX`` /
#: ``LEGACY_SHA1_TIER_HOST_KEYS``): the names the legacy module imports with this prefix are the tier.
_LEGACY_TIER_PREFIX = "LEGACY_SHA1_TIER_"
#: A tier-tuple name, by that convention: the prefix and an upper-case constant suffix.
_LEGACY_TIER_NAME = re.compile("^" + re.escape(_LEGACY_TIER_PREFIX) + "[A-Z0-9_]+$")


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


# ----------------------------- connection taint fixpoint (W59; one owner, shared with the T8 tests) ---
# W59 PR-1 review (P3-f) built a CLOSED structural taint scan for the collector's one patchable connection factory
# (T8, tests/test_ssh_session.py, closed in its round 2): every name a netmiko / paramiko import binds is a root, and
# so is every dynamic route to a name; taint flows through every binding and expression form, names resolve as
# Python resolves them, and a connection-capable callee may be CALLED, or a connection-capable value HANDED to other
# code, only at named sites. W59 PR-2 review round 2 (P2) runs the SAME fixpoint inside the published
# `legacy_ssh_confined` claim, so it moved here verbatim, to the shipped owner, and the tests import it from here
# (tests/ssh_structural_support.py re-exports it), exactly as tests/test_readonly_and_no_egress.py imports the
# read-only grammar above: the published claim and the CI guard cannot diverge.
SSH_CONNECTION_LIBRARIES = ("netmiko", "paramiko")


def connection_roots(tree):
    """Every name an import of netmiko or paramiko binds (a module, the class map, a driver or client class), derived
    from the import statements, never hand-listed. Exception classes (imported from an exceptions module) construct
    no connection and are not roots."""
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in SSH_CONNECTION_LIBRARIES:
                    roots.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            module = node.module or ""
            if module.split(".")[0] in SSH_CONNECTION_LIBRARIES and not module.endswith(("exceptions", "ssh_exception")):
                roots.update(alias.asname or alias.name for alias in node.names)
    return roots


# A value's taint SHAPE: False (carries nothing), True (a connection-capable class, callable or module), (_SEQ, (s,
# ...)) a tuple or list display with one shape per element, or (_BAG, s) any other container whose members have shape s.
_SEQ, _BAG = "seq", "bag"
#: calls whose result can be ANY name -- a namespace, an import by string, an evaluated string -- so it is a root
_DYNAMIC_ROOT_CALLS = frozenset({"__import__", "import_module", "globals", "vars", "locals", "eval"})
#: calls that execute code from a string: each is a violation by itself, whatever it is handed
_DYNAMIC_CODE_CALLS = frozenset({"exec", "eval", "compile"})
#: readers the shape model already follows: handing them a tainted value hands it to no code
_READERS = frozenset({"type", "getattr", "isinstance", "issubclass", "hasattr"})
#: container operations that never call what they are given; on an already-tainted container they keep it tainted
_CONTAINER_OPS = frozenset({"get", "setdefault", "pop", "append", "extend", "insert", "add", "update", "index",
                            "count", "remove", "discard", "copy", "items", "keys", "values"})
#: attribute reads that are data, never a class (a class's name, a module's version)
_DATA_DUNDERS = frozenset({"__name__", "__qualname__", "__module__", "__version__", "__doc__"})
_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _any(shape):
    if shape is True:
        return True
    if isinstance(shape, tuple):
        return _any(shape[1]) if shape[0] == _BAG else any(_any(e) for e in shape[1])
    return False


def _elem(shape):
    """What iterating, indexing or a container operation on a value of `shape` yields."""
    if shape is True:
        return True
    if isinstance(shape, tuple):
        if shape[0] == _BAG:
            return shape[1]
        out = False
        for e in shape[1]:
            out = _join(out, e)
        return out
    return False


def _join(a, b):
    if a is True or b is True:
        return True
    if not a:
        return b
    if not b:
        return a
    if a == b:
        return a
    if a[0] == b[0] == _SEQ and len(a[1]) == len(b[1]):
        return (_SEQ, tuple(_join(x, y) for x, y in zip(a[1], b[1])))
    return (_BAG, _join(_elem(a), _elem(b)))


def _bag(shape):
    return (_BAG, shape) if _any(shape) else False


def _target_names(target):
    if isinstance(target, ast.Name):
        yield target.id
    elif isinstance(target, (ast.Tuple, ast.List)):
        for e in target.elts:
            yield from _target_names(e)
    elif isinstance(target, ast.Starred):
        yield from _target_names(target.value)


class _Scopes:
    """Python's own name resolution, statically: each function (and lambda) has its locals -- parameters and every
    name it binds, minus its ``global`` / ``nonlocal`` declarations -- and a name resolves to the innermost enclosing
    FUNCTION that binds it (class bodies are skipped, as Python skips them), else to the module. A method's first
    parameter is keyed by its class, so ``self`` in one method is the same object as in another."""

    def __init__(self, tree):
        self.scope_of, self.parent, self.locals, self.kind, self.self_key = {}, {}, {"<module>": set()}, {}, {}
        self.defs = {}                                   # binding key of a def/class -> its node
        self._visit(tree, "<module>")

    def _bound(self, node):
        out = set()
        if isinstance(node, _FUNCS):
            a = node.args
            out |= {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs}
            out |= {x.arg for x in (a.vararg, a.kwarg) if x is not None}
        declared = set()
        body = [node.body] if isinstance(node, ast.Lambda) else node.body
        stack = list(body) if isinstance(body, list) else [body]
        while stack:
            n = stack.pop()
            if isinstance(n, (ast.Global, ast.Nonlocal)):
                declared |= set(n.names)
                continue
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.add(n.name)
                stack.extend(n.decorator_list)
                if not isinstance(n, ast.ClassDef):
                    stack.extend(n.args.defaults + [d for d in n.args.kw_defaults if d is not None])
                else:
                    stack.extend(n.bases + [k.value for k in n.keywords])
                continue                                 # its body is its own scope
            if isinstance(n, ast.Lambda):
                stack.extend(n.args.defaults + [d for d in n.args.kw_defaults if d is not None])
                continue
            if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                out.add(n.id)
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                out |= {(a.asname or a.name).split(".")[0] for a in n.names}
            elif isinstance(n, ast.ExceptHandler) and n.name:
                out.add(n.name)
            stack.extend(ast.iter_child_nodes(n))
        return out - declared, declared

    def _visit(self, node, scope):
        for child in ast.iter_child_nodes(node):
            self.scope_of[id(child)] = scope
            if isinstance(child, (*_FUNCS, ast.ClassDef)):
                name = getattr(child, "name", f"<lambda@{child.lineno}:{child.col_offset}>")
                inner = name if scope == "<module>" else f"{scope}.{name}"
                if not isinstance(child, ast.Lambda):
                    where = (scope, name) if self.kind.get(scope) == "class" else self.resolve_name(name, scope)
                    self.defs.setdefault(where, []).append(child)
                self.parent[inner] = scope
                self.kind[inner] = "class" if isinstance(child, ast.ClassDef) else "function"
                if isinstance(child, ast.ClassDef):
                    self.locals[inner] = set()
                    for item in child.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.args.args:
                            self.self_key[(f"{inner}.{item.name}", item.args.args[0].arg)] = ("<self>", inner)
                else:
                    self.locals[inner], _declared = self._bound(child)
                # decorators, defaults and bases are evaluated in the ENCLOSING scope
                for sub in (getattr(child, "decorator_list", []) + getattr(child, "bases", [])
                            + [k.value for k in getattr(child, "keywords", [])]):
                    self._mark(sub, scope)
                if isinstance(child, _FUNCS):
                    for d in child.args.defaults + [d for d in child.args.kw_defaults if d is not None]:
                        self._mark(d, scope)
                self._visit_body(child, inner)
            else:
                self._visit(child, scope)

    def _mark(self, node, scope):
        for sub in ast.walk(node):
            self.scope_of[id(sub)] = scope
        self._visit(node, scope)

    def _visit_body(self, node, scope):
        body = [node.body] if isinstance(node, ast.Lambda) else node.body
        for stmt in body:
            self.scope_of[id(stmt)] = scope
            if isinstance(stmt, (*_FUNCS, ast.ClassDef)):
                wrapper = ast.Module(body=[stmt], type_ignores=[])
                self._visit(wrapper, scope)
            else:
                self._visit(stmt, scope)

    def resolve_name(self, name, scope):
        """The binding key of `name` read in `scope`."""
        if (scope, name) in self.self_key:
            return self.self_key[(scope, name)]
        s, first = scope, True
        while s != "<module>":
            if (self.kind.get(s) == "function" or first) and name in self.locals.get(s, ()):
                return (s, name)
            first = False
            s = self.parent.get(s, "<module>")
        return ("<module>", name)

    def key(self, node):
        scope = self.scope_of.get(id(node), "<module>")
        # a method's first parameter, anywhere inside that method (nested closures included)
        s = scope
        while s != "<module>":
            if (s, node.id) in self.self_key:
                return self.self_key[(s, node.id)]
            if node.id in self.locals.get(s, ()) and self.kind.get(s) == "function":
                break
            s = self.parent.get(s, "<module>")
        return self.resolve_name(node.id, scope)


class _Env:
    """Shapes of every binding key, of every (receiver, attribute) store, and of what every def returns."""

    def __init__(self, tree):
        self.scopes = _Scopes(tree)
        self.names = {("<module>", name): True for name in connection_roots(tree)}
        for node in ast.walk(tree):                      # a root bound inside a function is that function's local
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                scope = self.scopes.scope_of.get(id(node), "<module>")
                for alias in node.names:
                    bound = (alias.asname or alias.name).split(".")[0]
                    if bound in connection_roots(ast.Module(body=[node], type_ignores=[])):
                        self.names[self.scopes.resolve_name(bound, scope)] = True
        self.attrs, self.returns, self.methods = {}, {}, {}
        self.changed = False

    def key(self, node):
        return self.scopes.key(node)

    def receiver(self, node):
        return self.key(node) if isinstance(node, ast.Name) else ast.unparse(node)

    def put(self, table, key, shape):
        if not shape:
            return
        old = table.get(key, False)
        new = _join(old, shape)
        if new != old:
            table[key] = new
            self.changed = True

    # ------------------------------------------------------------------------------------------- shapes ---
    def shape(self, node):
        if node is None:
            return False
        if isinstance(node, ast.Name):
            key = self.key(node)
            own = self.names.get(key, False)
            for (recv, _attr), s in self.attrs.items():
                if recv == key:                     # an object carrying a tainted attribute, used whole
                    own = _join(own, _bag(s))
            return own
        if isinstance(node, ast.Attribute):
            if node.attr in _DATA_DUNDERS:
                return False
            base = self.names.get(self.key(node.value), False) if isinstance(node.value, ast.Name) \
                else self.shape(node.value)
            if base is True:
                return True
            own = self.attrs.get((self.receiver(node.value), node.attr), False)
            if node.attr in _CONTAINER_OPS:
                # W59 PR-2 review round 3 (P2): a container's bound method, taken as a value (``pick = table.get``,
                # ``sorted(..., key=table.get)``), hands back what the container holds when it is called later.
                held = self.shape(node.value)
                if isinstance(held, tuple):
                    own = _join(own, held)
            return own
        if isinstance(node, ast.Subscript):
            if ast.unparse(node.value) in ("sys.modules", "modules"):
                key = node.slice
                return not (isinstance(key, ast.Constant) and isinstance(key.value, str)) \
                    or key.value.split(".")[0] in SSH_CONNECTION_LIBRARIES
            base = self.shape(node.value)
            if isinstance(base, tuple) and base[0] == _SEQ and isinstance(node.slice, ast.Constant) \
                    and isinstance(node.slice.value, int) and -len(base[1]) <= node.slice.value < len(base[1]):
                return base[1][node.slice.value]
            return _elem(base)
        if isinstance(node, (ast.Tuple, ast.List)):
            if any(isinstance(e, ast.Starred) for e in node.elts):
                out = False
                for e in node.elts:
                    out = _join(out, _elem(self.shape(e.value)) if isinstance(e, ast.Starred) else self.shape(e))
                return _bag(out)
            elts = tuple(self.shape(e) for e in node.elts)
            return (_SEQ, elts) if any(_any(e) for e in elts) else False
        if isinstance(node, ast.Set):
            out = False
            for e in node.elts:
                out = _join(out, self.shape(e))
            return _bag(out)
        if isinstance(node, ast.Dict):
            out = False
            for k, v in zip(node.keys, node.values):
                out = _join(out, self.shape(k) if k is not None else False)
                out = _join(out, self.shape(v) if k is not None else _elem(self.shape(v)))
            return _bag(out)
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            return _bag(self.shape(node.elt))
        if isinstance(node, ast.DictComp):
            return _bag(_join(self.shape(node.key), self.shape(node.value)))
        if isinstance(node, ast.IfExp):
            return _join(self.shape(node.body), self.shape(node.orelse))
        if isinstance(node, ast.BinOp):
            # W59 PR-2 review round 3 (P2): ``+`` (a copy the legacy rules accept), ``*``, ``|`` and the set operators
            # build a container from their operands' members, so a tainted member survives them.
            return _bag(_join(_elem(self.shape(node.left)), _elem(self.shape(node.right))))
        if isinstance(node, ast.BoolOp):
            out = False
            for v in node.values:
                out = _join(out, self.shape(v))
            return out
        if isinstance(node, (ast.NamedExpr, ast.Starred, ast.Await, ast.YieldFrom)):
            return self.shape(node.value)
        if isinstance(node, ast.Lambda):
            return True if _any(self.shape(node.body)) else False
        if isinstance(node, ast.Call):
            return self.call_shape(node)
        return False

    @staticmethod
    def callee_name(func):
        return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None

    def defs_of(self, call):
        """The defs a call reaches: a resolvable name's own def (a class's ``__init__``), or every method of that
        name for an attribute call (the receiver's class is not resolved statically, so all of them)."""
        func = call.func
        if isinstance(func, ast.Name):
            for node in self.scopes.defs.get(self.key(func), ()):
                if isinstance(node, ast.ClassDef):
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "__init__":
                            yield item, True
                else:
                    yield node, False
        elif isinstance(func, ast.Attribute):
            for key, nodes in self.scopes.defs.items():
                if key[1] == func.attr and self.scopes.kind.get(key[0]) == "class":
                    for node in nodes:
                        if not isinstance(node, ast.ClassDef):
                            yield node, True

    def call_shape(self, node):
        func = node.func
        name = self.callee_name(func)
        if name == "type" and len(node.args) >= 2:
            return True if _any(self.shape(node.args[1])) else False
        if name == "getattr" and isinstance(func, ast.Name) and node.args:
            attr = node.args[1] if len(node.args) >= 2 else None
            if isinstance(attr, ast.Constant) and attr.value in _DATA_DUNDERS:
                return False
            base = self.names.get(self.key(node.args[0]), False) if isinstance(node.args[0], ast.Name) \
                else self.shape(node.args[0])
            if base is True:
                return True
            held = self.shape(node.args[0])
            if isinstance(attr, ast.Constant) and isinstance(attr.value, str):
                own = self.attrs.get((self.receiver(node.args[0]), attr.value), False)
                if attr.value in _CONTAINER_OPS and isinstance(held, tuple):
                    own = _join(own, held)             # a container's bound method, as for an attribute read
                return own
            # a computed attribute name: whatever the object carries, or a bound method handing it back
            return _join(held, _elem(held)) if isinstance(held, tuple) else _elem(held)
        if name in ("__import__", "import_module"):
            arg = node.args[0] if node.args else None
            return not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)) \
                or arg.value.split(".")[0] in SSH_CONNECTION_LIBRARIES
        if name in _DYNAMIC_ROOT_CALLS and isinstance(func, ast.Name):
            return True
        if name == "partial" and node.args and _any(self.shape(node.args[0])):
            return True
        out = False
        for fn, _method in self.defs_of(node):
            out = _join(out, self.returns.get(id(fn), False))
        if out:
            return out
        callee = self.shape(func)
        if callee is True:
            return False                           # calling a class builds an instance, which taints nothing
        if call_signature(node) in _COPY_CALLS:
            # W59 PR-2 review round 3 (P2): a copy's result holds its operand's members -- tainted when they are
            return _bag(_elem(self.shape(node.args[0])))
        if isinstance(callee, tuple):
            # a container operation (``table.get(k)``), or a container's bound method held elsewhere and called
            # later (``pick(k)``, ``getattr(table, "get")(k)``), hands back what the container holds
            return _elem(callee)
        return False

    # ------------------------------------------------------------------------------------------ binding ---
    def bind(self, target, shape, value=None):
        if isinstance(target, ast.Name):
            key = self.key(target)
            self.put(self.names, key, shape)
            if isinstance(value, ast.Name):        # an alias of an object carrying tainted attributes
                src = self.key(value)
                for (recv, attr), s in list(self.attrs.items()):
                    if recv == src:
                        self.put(self.attrs, (key, attr), s)
        elif isinstance(target, (ast.Tuple, ast.List)):
            starred = any(isinstance(e, ast.Starred) for e in target.elts)
            if not starred and isinstance(shape, tuple) and shape[0] == _SEQ and len(shape[1]) == len(target.elts):
                vals = value.elts if isinstance(value, (ast.Tuple, ast.List)) and len(value.elts) == len(
                    target.elts) else [None] * len(target.elts)
                for e, s, v in zip(target.elts, shape[1], vals):
                    self.bind(e, s, v)
            else:
                for e in target.elts:
                    self.bind(e, _bag(_elem(shape)) if isinstance(e, ast.Starred) else _elem(shape))
        elif isinstance(target, ast.Starred):
            self.bind(target.value, shape)
        elif isinstance(target, ast.Attribute):
            self.put(self.attrs, (self.receiver(target.value), target.attr), shape)
        elif isinstance(target, ast.Subscript):
            root = target.value                    # storing into a container taints the container
            if isinstance(root, ast.Name):
                self.put(self.names, self.key(root), _bag(shape))
            elif isinstance(root, ast.Attribute):
                self.put(self.attrs, (self.receiver(root.value), root.attr), _bag(shape))

    def bind_params(self, fn, call, skip_self):
        scope = self.scopes.scope_of.get(id(fn.body[0] if isinstance(fn.body, list) else fn.body), None)
        args = fn.args
        params = [a.arg for a in args.posonlyargs + args.args]
        if skip_self and params:
            params = params[1:]

        def put(param, shape):
            self.put(self.names, (scope, param), shape)

        for i, a in enumerate(call.args):
            if isinstance(a, ast.Starred):
                for q in params[i:]:
                    put(q, _elem(self.shape(a.value)))
                if args.vararg is not None:
                    put(args.vararg.arg, _bag(_elem(self.shape(a.value))))
                break
            if i < len(params):
                put(params[i], self.shape(a))
            elif args.vararg is not None:
                put(args.vararg.arg, _bag(self.shape(a)))
        named = set(params) | {a.arg for a in args.kwonlyargs}
        for kw in call.keywords:
            if kw.arg is None:
                for q in named:
                    put(q, _elem(self.shape(kw.value)))
                if args.kwarg is not None:
                    put(args.kwarg.arg, self.shape(kw.value))
            elif kw.arg in named:
                put(kw.arg, self.shape(kw.value))
            elif args.kwarg is not None:
                put(args.kwarg.arg, _bag(self.shape(kw.value)))

    def step(self, tree):
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if any(_any(self.shape(b)) for b in list(node.bases) + [k.value for k in node.keywords]):
                    self.put(self.names, self.scopes.resolve_name(node.name, self.scopes.scope_of.get(
                        id(node), "<module>")), True)
            elif isinstance(node, ast.Assign):
                s = self.shape(node.value)
                for t in node.targets:
                    self.bind(t, s, node.value)
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and node.value is not None:
                self.bind(node.target, self.shape(node.value), node.value)
            elif isinstance(node, ast.NamedExpr):
                self.bind(node.target, self.shape(node.value), node.value)
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
                self.bind(node.target, _elem(self.shape(node.iter)))
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    if item.optional_vars is not None:
                        self.bind(item.optional_vars, self.shape(item.context_expr))
            elif isinstance(node, _FUNCS):
                args = node.args
                positional = args.posonlyargs + args.args
                inner = self.scopes.scope_of.get(id(node.body[0] if isinstance(node.body, list) else node.body))
                for a, d in zip(positional[len(positional) - len(args.defaults):], args.defaults):
                    self.put(self.names, (inner, a.arg), self.shape(d))
                for a, d in zip(args.kwonlyargs, args.kw_defaults):
                    if d is not None:
                        self.put(self.names, (inner, a.arg), self.shape(d))
                if not isinstance(node, ast.Lambda):
                    out = False
                    stack = list(node.body)
                    while stack:
                        r = stack.pop()
                        if isinstance(r, (*_FUNCS, ast.ClassDef)):
                            continue                 # a nested def's returns are its own
                        if isinstance(r, ast.Return) and r.value is not None:
                            out = _join(out, self.shape(r.value))
                        elif isinstance(r, (ast.Yield, ast.YieldFrom)) and r.value is not None:
                            out = _join(out, _bag(self.shape(r.value)))
                        stack.extend(ast.iter_child_nodes(r))
                    self.put(self.returns, id(node), out)
            elif isinstance(node, ast.Call):
                for fn, skip_self in self.defs_of(node):
                    self.bind_params(fn, node, skip_self)


def qualified_owners(tree):
    """id(node) -> the qualified name of its innermost enclosing function ('<module>' at module level)."""
    owners = {}

    def visit(node, qual, in_function):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                inner = f"{qual}.{child.name}" if qual else child.name
                owners[id(child)] = qual if in_function else (qual or "<module>")
                visit(child, inner, in_function or not isinstance(child, ast.ClassDef))
            else:
                owners[id(child)] = qual if in_function else "<module>"
                visit(child, qual, in_function)

    visit(tree, "", False)
    return owners


def connection_constructor_calls(tree, *, signatures=False):
    """``(constructs, hands_over, tainted, factories)`` over the module `tree`: ``{qualified owner: sorted callee
    sources}`` for every call that constructs through a connection-capable callee (and every ``exec`` / ``eval`` /
    ``compile``), the same for every call a connection-capable value is handed to as an argument (the readers and the
    container operations the shape model follows excepted), the set of tainted binding keys ``(scope, name)``, and the
    names of the defs that return a tainted value. The taint is a fixpoint over the whole module (see the T8 tests
    and :func:`_claim_legacy_ssh_confined`). With `signatures`, each call is keyed by its full
    :func:`call_signature` instead of its callee's source (a decorator as ``("@<spelling>", 1, ())``), so a caller can
    tell ``sorted(x)`` from ``sorted(x, key=f)``."""
    def key(call):
        return call_signature(call) if signatures else ast.unparse(call.func)

    env = _Env(tree)
    for _ in range(64):
        env.changed = False
        env.step(tree)
        if not env.changed:
            break
    else:
        raise AssertionError("the taint fixpoint did not converge")
    owners = qualified_owners(tree)
    found, passes = {}, {}
    for node in ast.walk(tree):
        owner = owners.get(id(node), "<module>")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for dec in node.decorator_list:
                if env.shape(dec.func if isinstance(dec, ast.Call) else dec) is True:
                    spelled = "@" + ast.unparse(dec)
                    found.setdefault(owner, []).append((spelled, 1, ()) if signatures else spelled)
        if not isinstance(node, ast.Call):
            continue
        name = env.callee_name(node.func)
        if isinstance(node.func, ast.Name) and name in _DYNAMIC_CODE_CALLS:
            found.setdefault(owner, []).append(key(node) if signatures else name)
            continue
        if env.shape(node.func) is True and not (isinstance(node.func, ast.Name) and name in _READERS):
            found.setdefault(owner, []).append(key(node))
        if isinstance(node.func, ast.Name) and name in _READERS:
            continue
        if isinstance(node.func, ast.Attribute) and name in _CONTAINER_OPS and isinstance(
                env.shape(node.func.value), tuple):
            continue
        if any(_any(env.shape(a)) for a in node.args) or any(_any(env.shape(k.value)) for k in node.keywords):
            passes.setdefault(owner, []).append(key(node))
    factories = {n.name for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and env.returns.get(id(n))}
    return ({o: sorted(c) for o, c in found.items()}, {o: sorted(c) for o, c in passes.items()},
            {key for key, shape in env.names.items() if _any(shape)}, factories)


def callee_name(func):
    """The callee spelling the scan keys a call by (a name, or an attribute's last segment)."""
    return _Env.callee_name(func)


def call_signature(call):
    """``(callee source, positional count, sorted keyword names)`` of one ``ast.Call``: the full argument shape the
    legacy tier's closed call-site allowlist and copy denominator pin (W59 PR-2 review round 3, P2). A ``*iterable``
    argument counts as a positional and adds ``*`` to the names; a ``**mapping`` argument adds ``**`` (neither is a
    legal keyword name, so neither can collide with one)."""
    names = [k.arg if k.arg is not None else "**" for k in call.keywords]
    if any(isinstance(a, ast.Starred) for a in call.args):
        names.append("*")
    return ast.unparse(call.func), len(call.args), tuple(sorted(names))


def render_call(signature):
    """A call signature as readable source: ``("sorted", 1, ("key",))`` -> ``sorted(_, key=_)``."""
    callee, positional, names = signature
    starred = "*" in names
    args = ["_"] * (positional - starred) + ["*_"] * starred
    args += ["**_" if n == "**" else f"{n}=_" for n in names if n != "*"]
    return f"{callee}({', '.join(args)})"


# ------------------------------------------ legacy SSH tier confinement mechanics (W59) ---
def ssh_sha1_literals(tree):
    """``[(lineno, name)]`` for every SSH algorithm name with a SHA-1 exchange hash or host-key signature
    (:data:`SSH_SHA1_ALGORITHM`) that occurs in a string constant of a parsed module, as a token anchored at each end
    by the string's edge or any character that cannot continue the name (:data:`_SSH_SHA1_IN_TEXT`; W59 PR-2 review
    round 3). Docstrings and f-string parts are string constants too, so prose that spells such a name counts —
    comments do not reach the AST. Shared with ``tests/test_legacy_ssh.py``'s shipped-file scan."""
    hits = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, (str, bytes)):
            continue
        text = node.value if isinstance(node.value, str) else node.value.decode("latin-1")
        for match in _SSH_SHA1_IN_TEXT.finditer(text):
            hits.add((getattr(node, "lineno", 0), match.group(0)))
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
    """True when ``chain`` is a class base or the operand of a COPY -- the one argument of a call whose full signature
    is one of :data:`_COPY_CALLS`, a ``{**<chain>}`` display, or an operand of ``+`` -- or of a name-list rendering
    (:data:`_NAME_LIST_CALLS`)."""
    if isinstance(parent, ast.ClassDef):
        return any(base is chain for base in parent.bases)
    if isinstance(parent, ast.Call):
        return (parent.func is not chain and len(parent.args) == 1 and parent.args[0] is chain
                and call_signature(parent) in _COPY_CALLS | _NAME_LIST_CALLS)
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
                       f"operand of a copy ({_copy_forms()})")
    return out


def _copy_forms():
    """The accepted copy and projection forms, rendered from :data:`_COPY_CALLS` and :data:`_NAME_LIST_CALLS`."""
    return ", ".join(["+", "{**_}"] + [render_call(s) for s in sorted(_COPY_CALLS)]
                     + [f"the name-list rendering {render_call(s)}" for s in sorted(_NAME_LIST_CALLS)])


def _legacy_import_names(node):
    """``[(qualified name, alias)]`` for one import statement of the legacy module. The vocabulary owner's
    package-relative spelling (``from .ssh_session import X``) reads as ``cisco_toolkit.ssh_session.X``; any other
    relative import keeps its leading dots, so it can never match an allowlisted name."""
    if isinstance(node, ast.Import):
        return [(alias.name, alias) for alias in node.names]
    module = node.module or ""
    if node.level == 1 and module == _SSH_VOCABULARY_MODULE[:-3]:
        base = f"cisco_toolkit.{module}"
    else:
        base = "." * node.level + module
    return [(f"{base}.{alias.name}" if base and not base.endswith(".") else f"{base}{alias.name}", alias)
            for alias in node.names]


def owner_import_bound_names(owner_tree):
    """Every name the vocabulary owner binds through an import statement, anywhere in its module (a module or an
    object it merely re-exports, such as ``os`` or ``MappingProxyType``)."""
    return frozenset((alias.asname or alias.name).split(".")[0] for node in ast.walk(owner_tree)
                     if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names)


def legacy_import_violations(tree, owner_import_bound=frozenset()):
    """W59 PR-2 review (P1-a): every import of the legacy module against its CLOSED allowlist, lazy imports included,
    and every network-library import (:data:`NETWORK_IMPORTS`) that is not rooted at paramiko. With the no-egress
    walk's per-file permission, this is what judges the one file whose paramiko imports that walk accepts.

    W59 PR-2 review round 2 (P2): the allowlist is EXACT (:data:`_LEGACY_SSH_IMPORTS_EXACT`), with no prefix through
    which a module paramiko re-exports could be reached. From the vocabulary owner only the pinned names
    (:data:`_LEGACY_SSH_IMPORTS_VOCABULARY` and the tier tuples, :data:`_LEGACY_TIER_NAME`) may be imported, and
    none that the owner itself binds through an import statement (`owner_import_bound`, from
    :func:`owner_import_bound_names`; ``from cisco_toolkit.ssh_session import os`` then ``os.system(...)``). An
    import alias (``as``) is a violation, because it is a route around every spelling-based rule here."""
    vocab_prefix = f"cisco_toolkit.{_SSH_VOCABULARY_MODULE[:-3]}."
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        for name, alias in _legacy_import_names(node):
            leaf = name[len(vocab_prefix):] if name.startswith(vocab_prefix) else None
            vocab = leaf is not None and (leaf in _LEGACY_SSH_IMPORTS_VOCABULARY or bool(_LEGACY_TIER_NAME.match(leaf)))
            if name not in _LEGACY_SSH_IMPORTS_EXACT and not vocab:
                out.append(f"line {node.lineno}: imports {name} (outside the closed import allowlist)")
            if leaf is not None and leaf in owner_import_bound:
                out.append(f"line {node.lineno}: imports {name}, which the vocabulary owner binds through an import "
                           "statement (a module or object it only re-exports)")
            if alias.asname:
                out.append(f"line {node.lineno}: imports {name} as {alias.asname} (an import alias, a route around "
                           "every spelling-based rule)")
            if any(name == net or name.startswith(net + ".") for net in NETWORK_IMPORTS)                     and name.split(".")[0] != "paramiko":
                out.append(f"line {node.lineno}: imports the network library {name} (only paramiko is "
                           "permitted)")
    return out


def legacy_module_violations(tree, owner_import_bound=frozenset()):
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
        # W59 PR-2 review round 2 (P2): flagged OUTRIGHT, wherever the name or attribute appears -- called,
        # aliased or passed -- not only when it is called on a paramiko-rooted target.
        if isinstance(node, ast.Name) and node.id in _DYNAMIC_CALLS:
            violations.append(f"line {node.lineno}: names {node.id} (dynamic code, import, or attribute "
                              "lookup or store by a computed name)")
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
    violations += legacy_import_violations(tree, owner_import_bound)
    return sorted(set(violations)), n_tables


def _scope_bindings(body, params=()):
    """``[(name, lineno)]`` for every name one scope binds: its parameters, and every def, class, import and
    assignment target in its body, not descending into a nested def or class (each is its own scope)."""
    out = [(a.arg, getattr(a, "lineno", 0)) for a in params]
    stack = list(body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.append((node.name, node.lineno))
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            out.append((node.id, node.lineno))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            out += [((a.asname or a.name).split(".")[0], node.lineno) for a in node.names]
        elif isinstance(node, ast.ExceptHandler) and node.name:
            out.append((node.name, node.lineno))
        stack.extend(ast.iter_child_nodes(node))
    return out


def _binding_violations(tree):
    """W59 PR-2 review round 2 (P2): every scope of the legacy module (the module, each class body, each def) binds
    each name ONCE, and no scope binds a builtin's name. A rebinding is how an allowlisted spelling could be made to
    mean something else (``tuple = LegacySHA1Transport`` then ``tuple((host, port))``, or a parameter ``m`` rebound
    before ``type(m)(...)``)."""
    import builtins
    builtin_names = set(dir(builtins))
    out = []
    scopes = [("<module>", tree.body, ())]
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            scopes.append((node.name, node.body, ()))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = node.args
            params = [*a.posonlyargs, *a.args, *a.kwonlyargs, *(x for x in (a.vararg, a.kwarg) if x is not None)]
            scopes.append((node.name, node.body, params))
    for scope, body, params in scopes:
        seen = {}
        for name, lineno in _scope_bindings(body, params):
            if name in seen:
                out.append(f"line {lineno}: rebinds {name} in {scope} (first bound at line {seen[name]})")
            else:
                seen[name] = lineno
            if name in builtin_names:
                out.append(f"line {lineno}: binds the builtin name {name} in {scope}")
    return out


def legacy_closure_violations(tree):
    """``(violations, stats)``: W59 PR-2 review round 2 (P2), the CLOSED rules that replace the round-1 denylists.

    - every call (an ``ast.Call``, a decorator, a class keyword) is listed in :data:`_LEGACY_SSH_CALL_SITES` under
      its own enclosing def, by its full :func:`call_signature` (W59 PR-2 review round 3: the callee's spelling, the
      positional count and the keyword names, so an allowlisted spelling cannot take an unlisted ``key=``);
    - every attribute name is in :data:`_LEGACY_SSH_ATTRIBUTES`;
    - every AST node type is in :data:`_LEGACY_SSH_GRAMMAR`;
    - every scope binds each name once and shadows no builtin (:func:`_binding_violations`);
    - the T8 taint fixpoint (:func:`connection_constructor_calls`) finds NO call of a class or callable derived from
      a paramiko binding (the module's own exception classes derive only from paramiko's exception module, which is
      not a root, so raising one is not such a call), and every connection-capable value it finds handed to other
      code is handed only to a copy (:data:`_COPY_CALLS`, whose result the fixpoint keeps tainted) or to the
      name-list rendering (:data:`_NAME_LIST_CALLS`, whose result is a ``str`` by construction).

    ``stats`` counts each rule's subject (calls, attributes, nodes, tainted bindings), so the claim can refuse a
    vacuous pass."""
    owners = qualified_owners(tree)
    violations = []
    calls = []
    for node in ast.walk(tree):
        owner = owners.get(id(node), "<module>")
        if isinstance(node, ast.Call):
            calls.append((owner, call_signature(node), node.lineno))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            calls += [(owner, ("@" + ast.unparse(d), 1, ()), d.lineno) for d in node.decorator_list]
            if isinstance(node, ast.ClassDef):
                calls += [(owner, (f"{k.arg if k.arg is not None else '**'}=" + ast.unparse(k.value), 3, ()),
                           node.lineno) for k in node.keywords]
    for owner, signature, lineno in calls:
        if signature not in _LEGACY_SSH_CALL_SITES.get(owner, frozenset()):
            violations.append(f"line {lineno}: calls {signature[0]} in {owner} (outside the closed call-site "
                              f"allowlist): {render_call(signature)}")
    attrs = [(n.attr, n.lineno) for n in ast.walk(tree) if isinstance(n, ast.Attribute)]
    violations += [f"line {lineno}: attribute {attr} (outside the closed attribute allowlist)"
                   for attr, lineno in attrs if attr not in _LEGACY_SSH_ATTRIBUTES]
    nodes, line_of = [], {}
    for node in ast.walk(tree):                   # breadth-first: a parent is seen before its children
        nodes.append(node)
        for child in ast.iter_child_nodes(node):
            line_of[id(child)] = getattr(child, "lineno", None) or line_of.get(id(node), 0)
    violations += [f"line {line_of.get(id(n), 0)}: {type(n).__name__} construct (outside the closed grammar)"
                   for n in nodes if type(n).__name__ not in _LEGACY_SSH_GRAMMAR]
    violations += _binding_violations(tree)
    found, passes, tainted, _factories = connection_constructor_calls(tree, signatures=True)
    violations += [f"{owner}: calls {signature[0]} (a class or callable derived from a paramiko binding: it could "
                   "open a connection)" for owner, signatures in sorted(found.items()) for signature in signatures]
    sinks = _COPY_CALLS | _NAME_LIST_CALLS
    violations += [f"{owner}: hands a connection-capable value to {signature[0]}() (only a copy may take one: "
                   f"{', '.join(render_call(s) for s in sorted(_COPY_CALLS))}; or the name-list rendering "
                   f"{', '.join(render_call(s) for s in sorted(_NAME_LIST_CALLS))}): {render_call(signature)}"
                   for owner, signatures in sorted(passes.items()) for signature in signatures
                   if signature not in sinks]
    stats = {"calls": len(calls), "call_sites": sum(len(v) for v in _LEGACY_SSH_CALL_SITES.values()),
             "attributes": len(attrs), "nodes": len(nodes), "tainted": len(tainted)}
    return sorted(set(violations)), stats


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


def _legacy_ssh_method():
    """The published method text of ``legacy_ssh_confined``. W59 PR-2 review round 3 (P3): every list and count in it
    is rendered from the allowlist or denominator it describes, never restated."""
    n_sites = sum(len(v) for v in _LEGACY_SSH_CALL_SITES.values())
    absent = [n for n in _GRAMMAR_ROUTES_NAMED if n not in _LEGACY_SSH_GRAMMAR]
    return (f"source/AST scan of {_LEGACY_SSH_MODULE}, the opt-in legacy SSH transport tier (the one module whose "
            "paramiko imports the no-egress walk permits), by CLOSED allowlists: every import is one of an exact "
            f"list of {len(_LEGACY_SSH_IMPORTS_EXACT)} names ({', '.join(sorted(_LEGACY_SSH_IMPORTS_EXACT))}) or, "
            f"from the vocabulary owner {_SSH_VOCABULARY_MODULE}, one of its {len(_LEGACY_SSH_IMPORTS_VOCABULARY)} "
            f"pinned names ({', '.join(sorted(_LEGACY_SSH_IMPORTS_VOCABULARY))}) or a {_LEGACY_TIER_PREFIX}* tier "
            "tuple, none of them a name the owner itself binds through an import; no import alias; and paramiko "
            "is its only network library; every explicit call (decorators and class keywords included) is one of "
            f"a closed list of {n_sites} call sites, each pinned by its enclosing def and its full signature (the "
            "callee's spelling, the positional count and the keyword names); every attribute name is one of a "
            f"closed list of {len(_LEGACY_SSH_ATTRIBUTES)}; every AST node type is one of a closed grammar of "
            f"{len(_LEGACY_SSH_GRAMMAR)} (none of {', '.join(absent)}); every scope binds each name once and "
            "shadows no builtin; and the collector's T8 taint fixpoint, run over the module, finds no call of a "
            "class or callable derived from a paramiko binding and hands a connection-capable value only to a "
            "copy, whose result it keeps tainted, or to the name-list rendering, whose result is a str. Within "
            "those: it makes no command/channel/authentication/session call of its own, names no dynamic-code, "
            f"import-by-name or computed-attribute builtin ({', '.join(sorted(_DYNAMIC_CALLS))}) and no reflective "
            f"attribute ({', '.join(sorted(_REFLECTIVE_ATTRS))}); anything rooted in a paramiko binding, and any "
            f"inherited algorithm table, is used only as a class base or the operand of a copy ({_copy_forms()}) "
            "-- never aliased, called, subscripted, passed to another call, stored into or mutated -- and every "
            "table it defines is a tuple or a MappingProxyType; and, across the analysis package + the collector "
            "entry, SSH algorithm names with a SHA-1 exchange hash or host-key signature appear as literals only in "
            f"{_SSH_VOCABULARY_MODULE} (a name is matched wherever it occurs in a string, bounded by any character "
            f"that cannot continue it), the legacy-tier vocabulary names (prefix {_LEGACY_TIER_PREFIX}) are read "
            f"only by {_LEGACY_SSH_MODULE}, and hashes.SHA1 appears only in {_LEGACY_SSH_MODULE}. What a static "
            "scan does not establish: the behaviour of the paramiko code the tier inherits, and calls made "
            "implicitly by operators, iteration and string formatting on the values the allowlisted code handles")


def _claim_legacy_ssh_confined(toolkit_dir, collector_module):
    method = _legacy_ssh_method()
    cid = "legacy_ssh_confined"
    legacy_path = os.path.join(toolkit_dir, _LEGACY_SSH_MODULE)
    if not os.path.isfile(legacy_path):
        return _claim(cid, method, NOT_EVALUATED,
                      f"{_LEGACY_SSH_MODULE} source not available at {legacy_path!r} — "
                      "the confinement of the legacy SSH tier cannot be re-derived")
    try:
        legacy_tree = ast.parse(open(legacy_path, encoding="utf-8", errors="replace").read(),
                                filename=legacy_path)
        owner_path = os.path.join(toolkit_dir, _SSH_VOCABULARY_MODULE)
        owner_bound = (owner_import_bound_names(ast.parse(open(owner_path, encoding="utf-8", errors="replace").read(),
                                                          filename=owner_path))
                       if os.path.isfile(owner_path) else frozenset())
        violations, n_tables = legacy_module_violations(legacy_tree, owner_bound)
        closure, stats = legacy_closure_violations(legacy_tree)
        violations = [f"{_LEGACY_SSH_MODULE} {v}" for v in sorted(set(violations) | set(closure))]
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
    except (OSError, SyntaxError, ValueError, AssertionError, RecursionError) as e:
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
    if stats["tainted"] == 0 or stats["calls"] == 0:
        return _claim(cid, method, NOT_EVALUATED,
                      f"the taint fixpoint found {stats['tainted']} connection-capable binding(s) and the call-site "
                      f"rule {stats['calls']} call(s) in {_LEGACY_SSH_MODULE} — a rule with no subject proves "
                      "nothing (refusing a vacuous pass)")
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
                  f"library; every call one of the {stats['call_sites']} allowlisted call sites; every attribute "
                  f"inside the closed attribute allowlist ({len(_LEGACY_SSH_ATTRIBUTES)} names); every AST node "
                  f"inside the closed grammar ({len(_LEGACY_SSH_GRAMMAR)} node types); one binding per name per "
                  f"scope, no builtin shadowed; the taint fixpoint found {stats['tainted']} connection-capable "
                  f"binding(s), "
                  f"none called and none handed to anything but a copy or the name-list rendering; no "
                  f"command/channel/authentication/session "
                  f"call of its own; paramiko bindings and inherited tables used only as class bases or copied; "
                  f"{n_tables} table(s) defined, each frozen; SHA-1 SSH algorithm literals only in "
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
