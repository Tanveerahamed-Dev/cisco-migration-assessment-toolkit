"""Wave-1 'lock the moat' guards — turn the engine's three differentiators from TRUST statements into
FALSIFIABLE, fully-offline regression nets caught by the pytest Stop-hook (universal-best-roadmap.md W1).

The engine's competitive moat is that it is READ-ONLY by construction and FULLY OFFLINE by construction —
but until now no test PROVED either, so a silent regression (a future write command, a stray `import
requests` in a deliverable) would have shipped green. These guards close that.

Doctrine grounded (verified, not assumed): the only non-`show` strings on the SSH wire are the two terminal
setup commands (`COLLECT_PARSE_V3_23_0.TERMINAL_SETUP_CMDS`); the SSH collector has a protocol-level read-only
floor (send_command cannot configure); rest_collect is GET-only except a single login POST; and no analysis ->
deliverable module imports a network library. These tests re-derive the allow-list from the ACTUAL registries
(not a hardcoded verb list) and walk imports at ANY nesting depth (lazy imports too).

The wire sentence above used to be PROSE ONLY. It was also FALSE while this suite was green: the registries
are shared with the offline (`--no-collect`) reader, which keys controller exports by their REST endpoint path
(`api/…`, `ers/…`, `dataservice/…`) or APIC `moquery -c …`, and `collect()` sent the union of both Cisco
registries to every device — so 17 non-`show` strings were typed at the exec prompt of live gear (whole-repo
review 2026-07-28 #9). `test_ssh_wire_carries_only_show_plus_the_terminal_setup_commands` now DRIVES the real
`connect_device` + `collect()` with a recording fake and asserts over what is actually SENT, so the claim can
never again be truer in the docstring than in the code. Note the deliberate scope split: the registry walk
(`test_command_registries_are_read_only`) covers BOTH channels and so accepts the REST GET grammar; the wire
test covers the SSH channel only and accepts `show` + the two setup commands.

roadmap D3: the read-only grammar + banned-import lists + AST import-walk are FACTORED into
cisco_toolkit/attestation.py (the shipped 'Trust & Sovereignty' panel) and imported here, so
the CI doctrine-guard and the build-time attestation can never diverge. To keep the SHARED
grammar itself falsifiable (a loosened regex must not green both sides), this file adds a
negative-control test: known write verbs must be REJECTED by the grammar.
"""
import ast
import os

import pytest

import COLLECT_PARSE_V3_23_0 as C
from cisco_toolkit.attestation import (
    NETWORK_IMPORTS as _NETWORK_IMPORTS,
    READ_ONLY_CMD as _READ_ONLY_CMD,
    is_read_only_command as _is_read_only_command,
    imported_names as _imported_names,
)

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOOLKIT = os.path.join(_HERE, "cisco_toolkit")

# netmiko config / write sinks that would break the SSH read-only floor (SSH-collector-specific:
# stays here, not in the attestation module, whose scope is the four published claims).
_CONFIG_SINKS = ("send_config_set", "send_config_from_file", "config_mode(",
                 "configure terminal", "\nsend_config", " send_config(")


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
        bad = [c for c in cmds if not _is_read_only_command(c)]
        if bad:
            offenders[rname] = bad
    assert not offenders, f"NON-read-only command(s) in the collection registries: {offenders}"
    # sanity: the union actually contains the known read verbs (the test isn't vacuously passing on an empty set)
    allcmds = {c for cmds in regs.values() for c in cmds}
    assert len(allcmds) >= 100 and any(c.startswith("show ") for c in allcmds)


class _RecordingDev:
    """A netmiko stand-in that records every string typed at the (fake) exec prompt."""

    def __init__(self):
        self.sent = []

    def send_command(self, cmd, read_timeout=None):
        self.sent.append(cmd)
        return f"output for {cmd}\nline2\nline3\n"

    def send_command_timing(self, cmd, read_timeout=None):   # pragma: no cover - pattern read never fails here
        self.sent.append(cmd)
        return ""

    def disconnect(self):
        pass


def test_ssh_wire_carries_only_show_plus_the_terminal_setup_commands(tmp_path, monkeypatch):
    """The header's wire sentence, DERIVED from what the collector actually sends rather than asserted in
    prose: drive the real `connect_device` (session setup) + `collect()` (the command sweep) with a recording
    fake and take the union of everything typed at the prompt. Every string must be a `show` read except
    exactly the two `TERMINAL_SETUP_CMDS` — no controller-REST endpoint path (`api/`, `ers/`, `dataservice/`),
    no APIC `moquery`, nothing a device CLI would answer with a DNS lookup and a Telnet attempt.

    Both platform orderings are driven, because `collect()` sends the UNION of COMMANDS_NXOS + COMMANDS_IOS to
    every device — the mechanism that put the other channel's strings on the wire in the first place.
    """
    dev = _RecordingDev()
    monkeypatch.setattr(C, "ConnectHandler", lambda **kw: dev)
    conn, _ = C.connect_device("10.0.0.1", "SW1", "u", "p", "ios")
    assert conn is dev
    for i, plat in enumerate(("ios", "nxos")):
        C.collect("SW1", plat, dev, str(tmp_path / f"SW{i}"))

    setup = list(C.TERMINAL_SETUP_CMDS)
    assert setup, "the terminal-setup allowance must name real commands (an empty tuple proves nothing)"
    off_grammar = sorted({c for c in dev.sent
                          if not c.strip().startswith("show ") and c not in setup})
    assert not off_grammar, (
        "non-`show` string(s) typed at a device exec prompt — the SSH channel takes device CLI reads only; "
        f"controller-REST endpoints belong to cisco_toolkit.rest_collect: {off_grammar}")
    # not vacuous: the sweep really ran, and the two setup commands really were the wire's only exception
    assert sum(1 for c in dev.sent if c.startswith("show ")) >= 90
    assert sorted({c for c in dev.sent if not c.startswith("show ")}) == sorted(setup)
    # ... and the withheld strings must SURVIVE in the registries: the offline `--no-collect` reader keys a
    # controller export by exactly these names, so deleting them (instead of filtering the wire) would blind it.
    union = {c for cmds in _registries().values() for c in cmds}
    for controller_cmd in ("moquery -c fabricNode", "api/v1/deployment/node", "ers/config/node",
                           "dataservice/device", "api/fmc_platform/v1/info/serverversion"):
        assert controller_cmd in union, f"{controller_cmd!r} left the registries — offline re-analysis goes blind"
        assert not C.is_ssh_wire_command(controller_cmd)


@pytest.mark.parametrize("poisoned", [
    "show running-config | redirect bootflash:pwn.txt",     # NX-OS: WRITES that file on the device
    "show running-config | tee bootflash:pwn.txt",          # ditto
    "show running-config | tftp://10.0.0.9/pwn.txt",        # ships the running-config OFF the device
    "show version\nconfigure terminal\nhostname PWNED",     # embedded lines are typed at the exec prompt
    "show version ; reload",
    "show version && write memory",
    "show version `reload`",
    "show running-config > bootflash:pwn.txt",
    "show run \\..\\..\\..\\evil",   # capture-filename traversal: collect() sanitises '/', not '\'
])
def test_a_write_tacked_onto_a_read_verb_never_reaches_the_wire(tmp_path, monkeypatch, poisoned):
    """The wire gate used to be `^show\\s+\\S` — a check on the FIRST WORD only. Everything after it was
    unconstrained, so a string that STARTS with a read verb and goes on to mutate the device or egress from
    it passed the guard whose entire job is to forbid exactly that: `| redirect`/`| tee` write a file ON the
    device, `| tftp://` ships the running-config off it, and an embedded newline is written to the channel
    verbatim by netmiko, so the extra lines are typed at the exec prompt (that one enters config mode and
    renames a production switch).

    No registry entry does this today, which is precisely why it needs a test: the positive grammar exists so
    that an entry added LATER is excluded BY DEFAULT rather than having to be remembered, and a write tacked
    onto a read verb is both the most dangerous such entry and the one a prefix check cannot see.

    Driven end-to-end through the real `collect()` with a recording transport, so the assertion is on what
    would actually be SENT rather than on the predicate in isolation."""
    monkeypatch.setattr(C, "COMMANDS_IOS", list(C.COMMANDS_IOS) + [poisoned])
    dev = _RecordingDev()
    C.collect("SW1", "ios", dev, str(tmp_path / "SW1"))
    assert dev.sent, "the sweep must actually have run (a collector that sends nothing proves nothing)"
    assert poisoned not in dev.sent, (
        f"a device-mutating / egressing string was typed at a production exec prompt: {poisoned!r}")
    assert not C.is_ssh_wire_command(poisoned)
    # negative control: the one legitimate pipe in the registries is an output FILTER and must survive
    assert C.is_ssh_wire_command("show running-config | section ^interface")
    assert "show version" in dev.sent


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
def test_shared_read_only_grammar_rejects_write_verbs():
    """Negative control for the SHARED grammar (imported from cisco_toolkit.attestation): a
    future loosening of the regex that lets a write verb through must fail HERE, even though
    the registry walk above and the shipped panel both use the same pattern."""
    for write_cmd in ("configure terminal", "reload", "request system reboot",
                      "aws ec2 authorize-security-group-ingress", "set system host-name x",
                      "execute factoryreset", "copy running-config startup-config",
                      "no shutdown", "delete flash:", "write memory"):
        assert not _is_read_only_command(write_cmd), \
            f"read-only grammar wrongly ACCEPTS write command {write_cmd!r}"
    # The class a VERB-anchored check cannot see: the string opens with a legitimate read verb and
    # then writes, egresses or chains. `_READ_ONLY_CMD` alone accepts every one of these — which is
    # why the claim goes through is_read_only_command(). Asserted BOTH ways so the weaker regex can
    # never quietly become the thing the attestation is built on again.
    for tacked_on in ("show running-config | redirect bootflash:pwn.txt",   # NX-OS WRITES that file
                      "show running-config | tftp://10.0.0.9/pwn.txt",      # ships the config off-box
                      "show running-config | append flash:x",
                      "show version ; reload",
                      "show version && write memory",
                      "show version `reload`",
                      "show version $(reload)",
                      "show version > flash:out.txt",
                      "show run \\..\\..\\..\\evil",                        # Windows path traversal
                      "show version\nconfigure terminal\nhostname PWNED"):  # newline = a 2nd command
        assert _READ_ONLY_CMD.match(tacked_on), \
            f"premise of this check changed — {tacked_on!r} no longer even reaches the verb gate"
        assert not _is_read_only_command(tacked_on), \
            f"read-only grammar wrongly ACCEPTS a write tacked onto a read verb: {tacked_on!r}"
    # ...while the legitimate output filters stay accepted (this must not become a blanket ban)
    for ok in ("show running-config | section ^interface", "show version | include Version",
               "show ip route | begin Gateway", "show interface | json",
               "dataservice/device/counters?deviceId=1.1.1.1"):
        assert _is_read_only_command(ok), f"read-only grammar wrongly REJECTS {ok!r}"
    # and the import-walk still sees LAZY nested imports (the mechanics stay honest too)
    lazy = ast.parse("def f():\n    import requests\n    from urllib.request import urlopen\n")
    got = _imported_names(lazy)
    assert "requests" in got and "urllib.request" in got


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
