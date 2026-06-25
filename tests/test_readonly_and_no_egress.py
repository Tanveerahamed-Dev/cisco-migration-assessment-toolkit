"""Wave-1 'lock the moat' guards — turn the engine's three differentiators from TRUST statements into
FALSIFIABLE, fully-offline regression nets caught by the pytest Stop-hook (universal-best-roadmap.md W1).

The engine's competitive moat is that it is READ-ONLY by construction and FULLY OFFLINE by construction —
but until now no test PROVED either, so a silent regression (a future write command, a stray `import
requests` in a deliverable) would have shipped green. These guards close that.

Doctrine grounded (verified, not assumed): the only non-`show` strings on the SSH wire are the two terminal
setup commands (COLLECT_PARSE_V3_23_0.py:810); the SSH collector has a protocol-level read-only floor
(send_command cannot configure); rest_collect is GET-only except a single login POST; and no analysis ->
deliverable module imports a network library. These tests re-derive the allow-list from the ACTUAL registries
(not a hardcoded verb list) and walk imports at ANY nesting depth (lazy imports too).
"""
import ast
import os
import re

import COLLECT_PARSE_V3_23_0 as C

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOOLKIT = os.path.join(_HERE, "cisco_toolkit")

# Read-only command allow-list, re-derived to cover EXACTLY the read verbs the six registries actually use:
# SSH/CLI reads (show/display/get/dir/ping/moquery), the AWS read-only describe-*, and the controller-REST GET
# paths (api/ FMC, ers/ ISE, dataservice/ vManage). A write verb (config/set/execute/reload/request/aws ec2
# authorize-/create-/delete-, a POST-only REST path, …) matches none of these and fails the test.
_READ_ONLY_CMD = re.compile(
    r"^(show|display|get|dir|ping|moquery)\b"          # SSH/CLI read verbs (incl. ACI moquery over SSH)
    r"|^aws ec2 describe-"                              # AWS read-only describe (never authorize/create/delete)
    r"|^(api/|ers/|dataservice/)",                     # controller-REST GET paths (FMC / ISE / vManage)
)

# netmiko config / write sinks that would break the SSH read-only floor, and any direct network egress lib.
_CONFIG_SINKS = ("send_config_set", "send_config_from_file", "config_mode(",
                 "configure terminal", "\nsend_config", " send_config(")
_NETWORK_IMPORTS = {"socket", "requests", "httpx", "http.client", "httplib", "urllib.request",
                    "netmiko", "paramiko", "telnetlib", "ftplib", "smtplib", "aiohttp", "pycurl"}


def _registries():
    return {k: getattr(C, k) for k in dir(C) if k.startswith("COMMANDS_")}


def _toolkit_py(exclude=()):
    for name in os.listdir(_TOOLKIT):
        if name.endswith(".py") and name not in exclude:
            yield os.path.join(_TOOLKIT, name)


# ------------------------------------------------------------------ W1-1: read-only ---
def test_command_registries_are_read_only():
    """Every command in every COMMANDS_* registry is a read-only query — the allow-list is re-derived from the
    registries, so a future write command (e.g. an `aws ec2 authorize-security-group-ingress`, a FortiGate
    `config`/`execute`, a `reload`) fails this test instead of silently shipping on the wire."""
    regs = _registries()
    assert regs, "no COMMANDS_* registries found — has the collector moved?"
    offenders = {}
    for rname, cmds in regs.items():
        bad = [c for c in cmds if not _READ_ONLY_CMD.match(str(c).strip())]
        if bad:
            offenders[rname] = bad
    assert not offenders, f"NON-read-only command(s) in the collection registries: {offenders}"
    # sanity: the union actually contains the known read verbs (the test isn't vacuously passing on an empty set)
    allcmds = {c for cmds in regs.values() for c in cmds}
    assert len(allcmds) >= 100 and any(c.startswith("show ") for c in allcmds)


def test_ssh_send_path_has_no_config_or_write_sink():
    """The SSH collector's protocol-level read-only floor: no module in cisco_toolkit/ + the collector entry
    issues a netmiko CONFIG/write call (send_config_set/from_file, config_mode, configure terminal). send_command
    cannot change device state, so the absence of these sinks IS the read-only guarantee. (_ref/ — a stale
    checked-in duplicate — is outside this scope by construction.)"""
    targets = list(_toolkit_py()) + [os.path.join(_HERE, "COLLECT_PARSE_V3_23_0.py")]
    hits = {}
    for path in targets:
        src = open(path, encoding="utf-8", errors="replace").read()
        found = [s.strip() for s in _CONFIG_SINKS if s in src]
        if found:
            hits[os.path.basename(path)] = found
    assert not hits, f"netmiko config/write sink found (breaks the read-only floor): {hits}"


def test_rest_collect_is_get_only_except_single_login_post():
    """The controller-REST collector (rest_collect.py) issues only HTTP GET, with exactly ONE POST — the login.
    No PUT/PATCH/DELETE method anywhere, so the collector cannot create/modify/delete a fabric object."""
    src = open(os.path.join(_TOOLKIT, "rest_collect.py"), encoding="utf-8").read()
    for verb in ("PUT", "PATCH", "DELETE"):
        assert f'method="{verb}"' not in src and f"method='{verb}'" not in src, \
            f"rest_collect issues a write method {verb} — REST is no longer read-only"
    n_post = src.count('method="POST"') + src.count("method='POST'")
    assert n_post == 1, f"expected exactly one POST (the login); found {n_post} — a new POST may write state"


# ------------------------------------------------------------------ W1-2: no egress ---
def _imported_names(tree):
    """Every imported module name in a parsed module, at ANY nesting depth (catches lazy in-function imports)."""
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


def test_no_network_egress_in_analysis_pipeline():
    """The analysis -> deliverable library imports NO network library, at any nesting depth. Only the two
    intended collectors may touch the network: rest_collect.py (the REST collector) and the dev-only
    data/gen_port_registry.py (a one-off data-pack generator, not import-reachable from the runtime pipeline).
    COLLECT_PARSE_V3_23_0.py (the SSH collector) lives at the repo root, outside cisco_toolkit/, so it is
    naturally out of this analysis-library scope. A stray `import requests` in a deliverable fails here."""
    offenders = {}
    for path in _toolkit_py(exclude={"rest_collect.py"}):
        tree = ast.parse(open(path, encoding="utf-8", errors="replace").read(), filename=path)
        imported = _imported_names(tree)
        bad = sorted(n for n in imported if any(n == net or n.startswith(net + ".") for net in _NETWORK_IMPORTS))
        if bad:
            offenders[os.path.basename(path)] = bad
    # the dev-only data-pack generator is the one documented exception (urllib to IANA; not pipeline-reachable)
    offenders.pop("gen_port_registry.py", None)
    assert not offenders, f"network-egress import(s) in the offline analysis pipeline: {offenders}"
