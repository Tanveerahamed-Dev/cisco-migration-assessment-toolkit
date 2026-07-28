"""LIVE-COLLECTION safety regressions — whole-repo review 2026-07-28, findings #10, #11, #57, #66, #89, #90.

Everything here is about what happens when the engine is pointed at *production gear*: what it types at an
exec prompt, what it does with a session that is failing under it, and what it then CLAIMS about the evidence.
Each test drives the real function with a fake transport (no socket is ever opened) and fails on the
pre-fix behaviour.

Both live front doors are homed together on purpose — the SSH collector (`COLLECT_PARSE_V3_23_0`) and the
controller-REST collector (`cisco_toolkit.rest_collect`) are the only two code paths in this repo that touch a
customer device, and their safety properties are the same family: never write, never loop on a production
controller, never put a credential where a bystander can read it, and never let a transport failure be
rendered as an observation. (#9 — the controller-REST strings that were being typed at device exec prompts —
is pinned in tests/test_readonly_and_no_egress.py, next to the doctrine sentence it falsified.)
"""
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import COLLECT_PARSE_V3_23_0 as C          # noqa: E402
from cisco_toolkit import rest_collect as R  # noqa: E402
from cisco_toolkit.capture_integrity import CAPTURE_META_FILENAME  # noqa: E402
from cisco_toolkit.cmdio import cmd_capture_state                  # noqa: E402


def _meta(dev_dir):
    p = os.path.join(dev_dir, CAPTURE_META_FILENAME)
    return json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else {}


# ============================================================ #10: a dead session is not an answer ===
class _DeadSessionDev:
    """The SSH session dies mid-sweep: both transports raise for one command."""

    DEAD = "show vlan brief"

    def send_command(self, cmd, read_timeout=None):
        if cmd == self.DEAD:
            raise OSError("Socket is closed")
        return f"real output for {cmd}\nrow\nrow\n"

    def send_command_timing(self, cmd, read_timeout=None):
        raise OSError("Socket is closed")


def test_failed_send_is_reported_not_collected_never_empty(tmp_path):
    """#10: when BOTH transports fail, `send_cmd` returns "" — which `collect()` used to write as a normal
    capture with `paths[cmd]` set. `cmdio.cmd_capture_state` ranks `empty` (2) ABOVE `error` (1), so a device
    whose session had DIED read as one that positively reported nothing to report — the exact
    absence-rendered-as-health this repo's doctrine forbids. The failure must be recorded and the path omitted,
    so the command reads `missing` (rank 0: a blind spot)."""
    dev_dir = tmp_path / "SW1"
    paths = C.collect("SW1", "ios", _DeadSessionDev(), str(dev_dir))
    cmd = _DeadSessionDev.DEAD

    assert cmd not in paths, "a command that produced NO output must not be published as a capture"
    assert cmd_capture_state(paths, cmd) == "missing"          # a blind spot, not an answer
    assert not (dev_dir / "show_vlan_brief.txt").exists(), "no 0-byte file may stand in for a dead session"
    assert _meta(str(dev_dir)).get(cmd) == "send_failed", "the transport failure must leave an audit record"
    # the rest of the sweep is unaffected — one dead command does not discard the device
    assert paths and "show version" in paths


# ================================= #11: a denied `terminal length 0` invalidates every later capture ===
class _TacacsDeniesTerminalDev:
    """A TACACS+ command-authorization policy that denies `terminal *` (the narrow read-only account this
    repo's own security doctrine recommends). Every other read succeeds and LOOKS clean."""

    def __init__(self):
        self.sent = []

    def send_command(self, cmd, read_timeout=None):
        self.sent.append(cmd)
        if cmd.startswith("terminal "):
            raise ValueError("Command authorization failed")
        return f"output for {cmd}\nrow\nrow\n"

    def send_command_timing(self, cmd, read_timeout=None):     # pragma: no cover
        return ""

    def disconnect(self):
        pass


def test_terminal_setup_failure_is_logged_and_recorded(tmp_path, monkeypatch, caplog):
    """#11: `terminal length 0` / `terminal width 511` failures were swallowed by a bare
    `except Exception: pass` — no log line, no record. With paging on and the width at 80, every capture comes
    back pager-truncated and line-wrapped and the fixed-column parsers return plausible-but-wrong values, while
    the run looks completely normal. The failure must be WARNED about and persisted so an offline re-analysis
    can distrust the device."""
    import logging

    dev = _TacacsDeniesTerminalDev()
    monkeypatch.setattr(C, "ConnectHandler", lambda **kw: dev)
    with caplog.at_level(logging.WARNING, logger=C.logger.name):
        conn, _ = C.connect_device("10.0.0.1", "SW1", "u", "p", "ios")

    assert dev.sent[:2] == list(C.TERMINAL_SETUP_CMDS), "session setup must still be attempted"
    warned = [r.getMessage() for r in caplog.records if "TERMINAL-SETUP" in r.getMessage()]
    assert warned, "a denied terminal-setup command must produce a WARNING, not silence"
    assert "terminal length 0" in warned[0] and "unproven" in warned[0]

    recorded = getattr(conn, C.TERMINAL_SETUP_ATTR, None)
    assert recorded and set(recorded) == set(C.TERMINAL_SETUP_CMDS)

    dev_dir = tmp_path / "SW1"
    C.collect("SW1", "ios", conn, str(dev_dir))
    meta = _meta(str(dev_dir))
    assert all(meta.get(c) == "terminal_setup_failed" for c in C.TERMINAL_SETUP_CMDS), (
        "the sidecar must carry the setup failure — it is the only thing that tells an offline re-analysis "
        "these captures may be truncated/wrapped")


def test_successful_terminal_setup_records_nothing(tmp_path, monkeypatch):
    """Negative control for #11: the happy path must not manufacture a defect record (a guard that fires
    always is as useless as one that never fires)."""
    class _Ok(_TacacsDeniesTerminalDev):
        def send_command(self, cmd, read_timeout=None):
            self.sent.append(cmd)
            return "ok\nrow\nrow\n"

    dev = _Ok()
    monkeypatch.setattr(C, "ConnectHandler", lambda **kw: dev)
    conn, _ = C.connect_device("10.0.0.1", "SW1", "u", "p", "ios")
    assert getattr(conn, C.TERMINAL_SETUP_ATTR) == {}
    dev_dir = tmp_path / "SW1"
    C.collect("SW1", "ios", conn, str(dev_dir))
    assert _meta(str(dev_dir)) == {}


# =========================================================== #89: no leaked VTY line on autodetect ===
class _FakeSession:
    def __init__(self):
        self.disconnected = False

    def disconnect(self):
        self.disconnected = True


def test_autodetect_closes_the_session_when_the_probe_raises(monkeypatch):
    """#89: `SSHDetect.__init__` OPENS the connection (it builds a ConnectHandler and reads the channel);
    `autodetect()` disconnects on each of its own return paths but NOT when it raises — the ordinary outcome of
    a slow device (a read timeout mid-probe). The `except Exception` arm returned 'ios' and dropped the last
    reference to an established session, holding a VTY line on production gear until the exec-timeout reaps it.
    This is the DEFAULT path (`platform: auto`), so it is one leaked line per device per run."""
    holder = {}

    class _BoomDetect:
        def __init__(self, **kw):
            self.connection = _FakeSession()
            holder["conn"] = self.connection

        def autodetect(self):
            raise TimeoutError("read timeout during autodetect")

    monkeypatch.setattr(C, "SSHDetect", _BoomDetect)
    assert C.autodetect_platform("10.0.0.1", "u", "p") == "ios"     # unchanged fail-soft default
    assert holder["conn"].disconnected, "the autodetect session must be closed on the exception path"


def test_autodetect_success_path_still_resolves_and_closes(monkeypatch):
    """The close must be idempotent-safe on the SUCCESS path too (netmiko's own autodetect() already
    disconnected there), and must not change the resolved platform."""
    holder = {}

    class _OkDetect:
        def __init__(self, **kw):
            self.connection = _FakeSession()
            holder["conn"] = self.connection

        def autodetect(self):
            return "cisco_nxos"

    monkeypatch.setattr(C, "SSHDetect", _OkDetect)
    assert C.autodetect_platform("10.0.0.1", "u", "p") == "nxos"
    assert holder["conn"].disconnected


# ============================================ #90: the timing retry must not splice two executions ===
class _TimeoutThenTimingDev:
    """The pattern read times out AFTER the device started printing; the tail of THAT execution is still
    sitting unread in the channel when the retry is written."""

    TAIL = "TAIL-OF-EXECUTION-1 (a previous command's output)\n"

    def __init__(self, with_clear_buffer=True):
        self.pending = self.TAIL
        self.cleared = False
        if not with_clear_buffer:
            del type(self).clear_buffer                            # pragma: no cover - see the sibling test

    def send_command(self, cmd, read_timeout=None):
        raise TimeoutError("pattern not detected in output")

    def send_command_timing(self, cmd, read_timeout=None):
        out, self.pending = self.pending, ""                        # whatever is buffered comes back spliced
        return out + f"EXECUTION-2 output for {cmd}\n"

    def clear_buffer(self, *a, **kw):
        self.cleared = True
        out, self.pending = self.pending, ""
        return out


def test_timing_fallback_drains_the_channel_before_resending():
    """#90: on a read timeout the device is NOT stopped — the rest of the first execution is still arriving.
    Re-sending straight into `send_command_timing` returned that tail PREPENDED to the second execution's
    output: one capture spliced from two executions (and, when the tail belonged to a `show running-config`,
    config text landing in an unrelated command's file and being parsed as that command's evidence)."""
    dev = _TimeoutThenTimingDev()
    out = C.send_cmd(dev, "show vlan brief")
    assert dev.cleared, "the pending output of the timed-out execution must be drained before re-sending"
    assert "TAIL-OF-EXECUTION-1" not in out, "the capture spliced the previous execution's output into itself"
    assert out.startswith("EXECUTION-2")
    assert C._SEND_TRANSPORT.fallback is True and C._SEND_TRANSPORT.failed is False


def test_timing_fallback_survives_a_transport_without_clear_buffer():
    """Fail-soft: a driver/stand-in with no `clear_buffer` must still get its retry (the drain is a
    best-effort hygiene step, never a new failure mode)."""
    class _NoDrain:
        def send_command(self, cmd, read_timeout=None):
            raise TimeoutError("pattern not detected")

        def send_command_timing(self, cmd, read_timeout=None):
            return "TIMING"

    assert C.send_cmd(_NoDrain(), "show version") == "TIMING"


# =============================== #57: a production controller credential does not belong on the CLI ===
def test_rest_cli_password_is_not_required_on_argv():
    """#57: `--password` was a REQUIRED argv parameter, so a production APIC/vManage/ISE/FMC read-only
    credential had to be typed on a command line — visible in the process table, the shell history and EDR
    process-creation telemetry. The SSH path already solved this (entry -> password_env -> $CISCO_PASS ->
    getpass). Asserted against the parser's OWN `--help`, not against the source text."""
    p = subprocess.run([sys.executable, "-m", "cisco_toolkit.rest_collect", "--help"],
                       capture_output=True, text=True, cwd=ROOT, timeout=120)
    assert p.returncode == 0, p.stderr
    usage = " ".join((p.stdout or "").split("options:")[0].split())
    assert "[--password PASSWORD]" in usage, f"--password must be OPTIONAL; usage was: {usage}"
    assert "[--password-env VAR]" in usage, "an env-var alternative must exist"


@pytest.mark.parametrize("var", ["CISCO_REST_PASS", "CISCO_PASS"])
def test_rest_cli_password_chain_reads_the_environment(monkeypatch, var):
    """The env chain mirrors the SSH collector's: an explicitly named variable, then $CISCO_REST_PASS, then
    $CISCO_PASS (so one engagement variable covers both channels)."""
    for v in ("CISCO_REST_PASS", "CISCO_PASS", "VAULT_VAR"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv(var, "from-" + var)
    assert R.resolve_cli_password(None, None, allow_prompt=False) == "from-" + var
    monkeypatch.setenv("VAULT_VAR", "from-named")
    assert R.resolve_cli_password(None, "VAULT_VAR", allow_prompt=False) == "from-named"
    assert R.resolve_cli_password("on-argv", "VAULT_VAR", allow_prompt=False) == "on-argv"   # back-compatible


def test_rest_cli_password_absent_yields_empty_not_a_blank_login(monkeypatch):
    """Nothing resolved must return "" so the CLI can REFUSE — never a blank-credential login attempt against
    a production controller (a failed auth there can trip account lockout)."""
    for v in ("CISCO_REST_PASS", "CISCO_PASS"):
        monkeypatch.delenv(v, raising=False)
    assert R.resolve_cli_password(None, None, allow_prompt=False) == ""
    assert R.resolve_cli_password(None, "NOT_SET_ANYWHERE", allow_prompt=False) == ""


# ================================== #66: ERS pagination must terminate against a hostile/broken PAN ===
def _ise_pagination_probe(monkeypatch, tmp_path, href_for):
    """Drive collect_ise with a mocked transport whose ERS SearchResult always offers a same-origin
    nextPage.href. Returns the LIST-PAGE GETs the collector made (the per-id detail GETs that follow are a
    bounded consequence of how many resources the walk accumulated, not the loop under test)."""
    pages = []

    def fake_get_json(opener, url, headers=None, timeout=30):
        if url.endswith("/api/v1/deployment/node"):
            return None                                  # Open API channel disabled — ERS only
        if "/ers/config/node/" in url:                   # per-id detail GET
            return {"ers-node-data": {"name": "pan"}}
        pages.append(url)
        if len(pages) > R._ERS_MAX_PAGES + 25:
            raise AssertionError(
                f"UNBOUNDED ERS pagination: {len(pages)} authenticated list GETs against the PAN and still "
                f"following nextPage.href")
        return {"SearchResult": {"total": 1, "resources": [{"id": f"n{len(pages)}"}],
                                 "nextPage": {"href": href_for(len(pages))}}}

    monkeypatch.setattr(R, "_get_json", fake_get_json)
    R.collect_ise("https://ise.example", "ro", "pw", str(tmp_path))
    return pages


def test_ise_ers_pagination_stops_on_a_self_referential_link(monkeypatch, tmp_path):
    """#66: `while nxt:` had no visited-set and no page cap, so a self-referential `nextPage.href` — a
    controller bug, a proxy, or a hostile response body — was an unbounded authenticated GET loop hammering a
    production ISE PAN. The same-origin guard does NOT help: a self-link is same-origin by definition. The FMC
    sibling `_fmc_get_all_pages` already carries both guards."""
    self_link = "https://ise.example:9060/ers/config/node?page=1"
    calls = _ise_pagination_probe(monkeypatch, tmp_path, lambda n: self_link)
    assert len(calls) <= 3, f"a repeated page must stop the walk almost immediately; made {len(calls)} GETs"


def test_ise_ers_pagination_is_capped_on_an_endless_distinct_page_series(monkeypatch, tmp_path):
    """A visited-set alone is defeated by an endless series of DISTINCT same-origin links, so the hard page
    cap is the guard that actually bounds the request count. Reaching it must also be DISCLOSED — a truncated
    census is never silently reported as the whole census."""
    import logging

    with monkeypatch.context() as mp:
        records = []

        class _Cap(logging.Handler):
            def emit(self, r):
                records.append(r.getMessage())

        R.logger.addHandler(_Cap())
        try:
            calls = _ise_pagination_probe(
                mp, tmp_path, lambda n: f"https://ise.example:9060/ers/config/node?page={n + 1}")
        finally:
            R.logger.handlers = [h for h in R.logger.handlers if not isinstance(h, _Cap)]
    assert len(calls) <= R._ERS_MAX_PAGES, f"the page cap must bound the walk; made {len(calls)} GETs"
    assert any("cap" in m and "TRUNCATED" in m for m in records), (
        "stopping at the cap must be disclosed — the node census may be incomplete")


def test_ise_ers_pagination_still_follows_a_genuine_multi_page_list(monkeypatch, tmp_path):
    """Negative control: the guards must not break real pagination (the reason the walk exists — reading only
    page 1 silently truncated the node census on a large deployment)."""
    pages = ["https://ise.example:9060/ers/config/node?page=2", None]
    calls = []

    def fake_get_json(opener, url, headers=None, timeout=30):
        if url.endswith("/api/v1/deployment/node"):
            return None
        if "/ers/config/node/" in url:                    # per-id detail GET
            return {"ers-node-data": {"name": "pan1"}}
        calls.append(url)
        nxt = pages[len(calls) - 1] if len(calls) <= len(pages) else None
        sr = {"total": 2, "resources": [{"id": f"n{len(calls)}"}]}
        if nxt:
            sr["nextPage"] = {"href": nxt}
        return {"SearchResult": sr}

    monkeypatch.setattr(R, "_get_json", fake_get_json)
    written = R.collect_ise("https://ise.example", "ro", "pw", str(tmp_path))
    assert len(calls) == 2, "both real pages must still be read"
    export = json.load(open(os.path.join(str(tmp_path), "ers_config_node.txt"), encoding="utf-8"))
    assert len(export["resources"]) == 2 and written
