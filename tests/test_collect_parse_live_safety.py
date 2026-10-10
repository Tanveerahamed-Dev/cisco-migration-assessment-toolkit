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

W44/F10 adds the evidence-BYTES half of that family: what both doors store must be what the session or
controller delivered, byte for byte, whichever host collects it. A default text-mode write turned every "\\n"
into "\\r\\n" on a Windows collecting host, and the engine reads, hashes and parses the stored bytes with no
newline translation, so the raw-evidence receipts and the parser input depended on the collecting host. The
tests below simulate Windows text-mode translation on ANY host, so they fail on the pre-fix writers on Linux
and on Windows alike.
"""
import ast
import copy
import hashlib
import inspect
import json
import logging
import os
import re
import subprocess
import sys

import pytest

import synthetic_fixtures as fx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import COLLECT_PARSE_V3_23_0 as C          # noqa: E402
from cisco_toolkit import rest_collect as R  # noqa: E402
from cisco_toolkit.capture_integrity import CAPTURE_META_FILENAME  # noqa: E402
from cisco_toolkit.cmdio import _load_cmd_output, cmd_capture_state  # noqa: E402


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
    # W59 PR-1: the collector constructs every connection through ONE factory; patching it intercepts
    # the whole connection path (C.ConnectHandler no longer exists, so a stale patch fails loudly).
    monkeypatch.setattr(C, "_open_connection", lambda kwargs, platform, profile, recorder: dev)
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
    # W59 PR-1: the collector constructs every connection through ONE factory; patching it intercepts
    # the whole connection path (C.ConnectHandler no longer exists, so a stale patch fails loudly).
    monkeypatch.setattr(C, "_open_connection", lambda kwargs, platform, profile, recorder: dev)
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


def test_rest_cli_password_env_name_never_crosses_the_log_sink(monkeypatch, caplog):
    """CodeQL #24: ``password_env`` names a variable; it is not the password value.

    It is nevertheless caller-controlled and can itself contain sensitive/log-forging text.  The
    warning must remain actionable without reflecting that name into the terminal.
    """
    marker = "PRIVATE_PASSWORD_ENV_9f0c2a"
    for var in (marker, "CISCO_REST_PASS", "CISCO_PASS"):
        monkeypatch.delenv(var, raising=False)

    with caplog.at_level(logging.WARNING, logger=R.logger.name):
        assert R.resolve_cli_password(None, marker, allow_prompt=False) == ""

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert marker not in messages
    assert "requested --password-env variable is empty/unset" in messages


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


# ===================================== W44/F10: the stored evidence bytes do not depend on the host ===
_REAL_OPEN = open


def _windows_text_open(seen: list):
    """An ``open`` that writes text the way Windows text mode does, on ANY host.

    A text-mode write that leaves ``newline`` at its default translates every "\\n" to os.linesep, which is
    "\\r\\n" on Windows. A monkeypatched ``os.linesep`` does not reach CPython's C text layer, so the translation
    is reproduced by turning a default ``newline`` into "\\r\\n", which is what a Windows build does with it.
    Installed as a collector module's ``open``, it makes a Linux run fail on a writer that relies on the host's
    translation, exactly as a Windows run does. ``seen`` records ``(path, newline)`` for every text-mode write;
    binary opens and reads pass through untouched and unrecorded. (The idea of the W36 demo-writer simulator,
    copied rather than imported so this file stands alone.)"""
    def fake_open(file, mode="r", buffering=-1, encoding=None, errors=None, newline=None,
                  closefd=True, opener=None):
        if "b" not in mode and any(flag in mode for flag in "wax+"):
            seen.append((file if isinstance(file, int) else os.fspath(file), newline))
            if newline is None:
                newline = "\r\n"
        return _REAL_OPEN(file, mode, buffering, encoding, errors, newline, closefd, opener)
    return fake_open


def _read(path) -> bytes:
    with _REAL_OPEN(path, "rb") as fh:
        return fh.read()


def _published(seen) -> set:
    """Final paths of the recorded writes (`_write_json_atomic` writes `<path>.<pid>.tmp`, then renames it)."""
    out = set()
    for path, _newline in seen:
        m = re.fullmatch(r"(.+)\.\d+\.tmp", str(path))
        out.add(os.path.abspath(m.group(1) if m else str(path)))
    return out


def _files_under(root) -> set:
    return {os.path.abspath(os.path.join(d, f)) for d, _dirs, files in os.walk(str(root)) for f in files}


def test_the_windows_text_simulator_really_translates_on_this_host(tmp_path):
    """The simulator every F10 test relies on is not inert here: a default-newline write through it is CRLF (and
    a delivered "\\r\\n" becomes "\\r\\r\\n", the doubled form the pre-fix collector stored), while an explicit
    no-translation write stores the text verbatim."""
    seen = []
    fake = _windows_text_open(seen)
    with fake(str(tmp_path / "default.txt"), "w", encoding="utf-8") as f:
        f.write("a\nb\r\nc")
    with fake(str(tmp_path / "verbatim.txt"), "w", encoding="utf-8", newline="") as f:
        f.write("a\nb\r\nc")
    with fake(str(tmp_path / "default.txt"), "rb") as f:            # a read passes through, unrecorded
        assert f.read() == b"a\r\nb\r\r\nc"
    assert _read(tmp_path / "verbatim.txt") == b"a\nb\r\nc"
    assert seen == [(str(tmp_path / "default.txt"), None), (str(tmp_path / "verbatim.txt"), "")]


class _FixedAnswerDev:
    """A healthy device session. Every command answers a fixed multi-line LF text (what netmiko's default
    line-feed normalisation delivers); VERBATIM answers with the raw "\\r\\n" and lone "\\r" a session with that
    normalisation disabled would deliver; SLOW needs the timing fallback, so the capture-metadata sidecar -- bound
    raw evidence as well -- is written too."""

    VERBATIM = "show inventory"
    SLOW = "show vlan brief"

    @classmethod
    def answer(cls, cmd):
        if cmd == cls.VERBATIM:
            return 'NAME: "Chassis", DESCR: "synthetic"\r\nPID: C9300-24T, VID: V01\rend of record\n'
        return f"{cmd}\nrow 1 of {cmd}\nrow 2 of {cmd}\n"

    def send_command(self, cmd, read_timeout=None):
        if cmd == self.SLOW:
            raise TimeoutError("pattern not detected in output")
        return self.answer(cmd)

    def send_command_timing(self, cmd, read_timeout=None):
        return self.answer(cmd)

    def clear_buffer(self, *a, **kw):
        return ""


def test_live_collector_stores_exactly_the_session_bytes_under_windows_translation(tmp_path, monkeypatch):
    """F10, SSH door: every capture is byte-for-byte the session's text encoded UTF-8 -- a "\\n" stays "\\n", a
    delivered "\\r\\n" stays "\\r\\n" (never "\\r\\r\\n") -- and every JSON file the collector writes beside the
    captures (the capture-metadata sidecar, the archive index, the device info) is the dump's own LF bytes, under
    Windows text-mode translation. Every file in the device directory came through a write that declared no
    translation, so no writer escapes the check by living on another code path."""
    seen = []
    monkeypatch.setattr(C, "open", _windows_text_open(seen), raising=False)
    dev = _FixedAnswerDev()
    dev_dir = tmp_path / "SW1"
    paths = C.collect("SW1", "ios", dev, str(dev_dir), archive_all_output=True)

    assert dev.VERBATIM in paths and dev.SLOW in paths and len(paths) > 10
    for cmd, path in paths.items():
        assert _read(path) == dev.answer(cmd).encode("utf-8"), cmd
    verbatim = _read(paths[dev.VERBATIM])
    assert verbatim.count(b"\r\n") == 1 and b"\r\r\n" not in verbatim

    meta = {dev.SLOW: "timing_fallback"}
    assert _read(dev_dir / CAPTURE_META_FILENAME) == \
        json.dumps(meta, indent=2, ensure_ascii=False).encode("utf-8")
    index = _read(dev_dir / "command_index.json")
    assert b"\r" not in index
    rows = json.loads(index)["commands"]
    assert sorted(row["command"] for row in rows) == sorted(paths)
    for row in rows:
        expected = dev.answer(row["command"]).encode("utf-8")
        assert (row["bytes"], row["sha256"]) == (len(expected), hashlib.sha256(expected).hexdigest()), \
            row["command"]
    info = _read(dev_dir / "device_info.json")
    assert b"\r" not in info and b"\n" in info

    assert seen and {newline for _path, newline in seen} == {""}, sorted({n for _p, n in seen}, key=repr)
    assert _files_under(dev_dir) == _published(seen)


def test_raw_evidence_receipts_are_the_session_bytes_whatever_the_collecting_host(tmp_path, monkeypatch):
    """F10 at the custody layer: `_evidence_records` -- the producer of the run's raw-evidence receipts, which
    `input_custody` then enforces on every parser read -- gives the SAME receipts for a collection written
    natively and one written under Windows text-mode translation, each the size/SHA-256 of the delivered bytes;
    the capture-metadata sidecar is one of those receipts. The parsers are handed the session's own text."""
    dev = _FixedAnswerDev()
    native_root, windows_root = tmp_path / "native", tmp_path / "windows"
    native = C.collect("SW1", "ios", dev, str(native_root / "SW1"))
    monkeypatch.setattr(C, "open", _windows_text_open([]), raising=False)
    translated = C.collect("SW1", "ios", dev, str(windows_root / "SW1"))

    a = C._evidence_records({"SW1": native}, str(native_root))
    b = C._evidence_records({"SW1": translated}, str(windows_root))
    assert a["files"] == b["files"] and a["root_sha256"] == b["root_sha256"]
    rows = {row["path"]: row for row in b["files"]}
    assert len(rows) == len(set(translated.values())) + 1           # every capture, plus the sidecar
    for cmd, path in translated.items():
        expected = dev.answer(cmd).encode("utf-8")
        row = rows["SW1/" + os.path.basename(path)]
        assert (row["size"], row["sha256"]) == (len(expected), hashlib.sha256(expected).hexdigest()), cmd
    assert rows["SW1/" + CAPTURE_META_FILENAME]["commands"] == ["<capture-metadata>"]

    assert _load_cmd_output(translated, "show running-config") == dev.answer("show running-config")
    assert _load_cmd_output(translated, dev.VERBATIM) == dev.answer(dev.VERBATIM)


@pytest.mark.parametrize("host", sorted(fx.COLLECTIONS))
def test_live_collector_writes_the_golden_fixture_bytes_on_every_host(host, tmp_path, monkeypatch):
    """Fed the real golden fixture text (tests/synthetic_fixtures.py, the collection behind
    tests/golden/snapshot.json): a session answering each command with the fixture's capture is stored by the
    live collector, under Windows text-mode translation, as exactly the bytes the golden's own writer stores, and
    the custody producer's receipts over the two collections are identical. Before F10 a Windows live collection
    of the very devices the golden models carried different receipts than the golden."""
    platform, outputs = fx.COLLECTIONS[host]
    assert not any("\r" in text for text in outputs.values())       # any CR below would be the writer's
    refused = "% Invalid input detected at '^' marker.\n"

    class _Replay:
        def __init__(self):
            self.asked = []

        def send_command(self, cmd, read_timeout=None):
            self.asked.append(cmd)
            return outputs.get(cmd, refused)

        def send_command_timing(self, cmd, read_timeout=None):     # pragma: no cover - never needed
            return outputs.get(cmd, refused)

    dev = _Replay()
    monkeypatch.setattr(C, "open", _windows_text_open([]), raising=False)
    live_root = tmp_path / "live"
    live = C.collect(host, platform, dev, str(live_root / host))
    golden_root = fx.write_collection(str(tmp_path / "golden"))

    issued = sorted(cmd for cmd in outputs if cmd in dev.asked)
    assert issued == sorted(cmd for cmd in outputs if cmd in live)   # every fixture answer was stored
    assert len(issued) > len(outputs) // 2 and any(outputs[cmd].count("\n") > 2 for cmd in issued)
    golden = {cmd: os.path.join(golden_root, host, fx.cmd_filename(cmd)) for cmd in issued}
    for cmd in issued:
        assert _read(live[cmd]) == _read(golden[cmd]) == outputs[cmd].encode("utf-8"), cmd

    live_receipts = C._evidence_records({host: {cmd: live[cmd] for cmd in issued}}, str(live_root))
    golden_receipts = C._evidence_records({host: golden}, golden_root)
    assert live_receipts["files"] == golden_receipts["files"]
    assert live_receipts["root_sha256"] == golden_receipts["root_sha256"]


_REST_BODY = {
    "imdata": [{"fabricNode": {"attributes": {"id": "101", "name": "leaf-101", "fabricSt": "active"}}}],
    "items": [{"name": "FTD-01", "model": "Secure Firewall 3105"}],
    "data": [{"host-name": "BR01", "system-ip": "10.0.0.1", "reachability": "reachable"}],
    "response": [{"hostname": "ise-pan-1", "roles": ["PrimaryAdmin"], "nodeStatus": "Connected"}],
}


class _UniversalLogin:
    """One login response every controller door accepts: vManage reads a non-HTML body, FMC takes its token and
    DOMAINS from the headers, APIC only closes it (ISE has no login request)."""
    headers = {"X-auth-access-token": "TOK", "DOMAINS": json.dumps([{"name": "Global", "uuid": "dom-1"}])}

    def read(self):
        return b"OK"

    def close(self):
        pass


def test_every_controller_collector_stores_host_independent_json(tmp_path, monkeypatch):
    """F10, REST door, over the live `CONTROLLER_COLLECTORS` denominator rather than a hand-kept list: under
    Windows text-mode translation every export each registered collector writes -- ISE's consolidated ERS export
    and FMC's merged pages included -- is exactly ``json.dumps(obj, indent=2)`` encoded UTF-8, with LF line breaks
    on every host. These exports are a re-serialisation of the parsed response, never the controller's wire
    bytes; what F10 pins is that the re-serialisation does not depend on the collecting host."""
    def fake_get_json(opener, url, headers=None, timeout=30):
        if "/ers/config/node/" in url:                               # ISE ERS per-id detail
            return {"ers-node-data": {"name": "ise-pan-1", "nodeServiceTypes": "Session"}}
        if "/ers/config/node" in url:                                # ISE ERS list (a single page)
            return {"SearchResult": {"total": 1, "resources": [{"id": "n1", "name": "ise-pan-1"}]}}
        return copy.deepcopy(_REST_BODY)

    monkeypatch.setattr(R, "_post", lambda *a, **k: _UniversalLogin())
    monkeypatch.setattr(R, "_get_text",
                        lambda opener, url, headers=None, timeout=30: "XSRF" if "client/token" in url else None)
    monkeypatch.setattr(R, "_get_json", fake_get_json)
    expected, real_write = {}, R._write

    def recording_write(out_dir, cmd, obj):
        path = real_write(out_dir, cmd, obj)
        expected[os.path.abspath(path)] = json.dumps(obj, indent=2).encode("utf-8")
        return path

    monkeypatch.setattr(R, "_write", recording_write)
    seen = []
    monkeypatch.setattr(R, "open", _windows_text_open(seen), raising=False)

    fabrics = {name: collect(f"https://{name}.example", "ro", "pw", str(tmp_path / name))
               for name, collect in R.CONTROLLER_COLLECTORS.items()}
    assert fabrics and all(fabrics.values()), {name: len(files) for name, files in fabrics.items()}
    assert any(path.endswith("ers_config_node.txt") for path in fabrics["ise"])    # the second ISE write site

    written = sorted(os.path.abspath(path) for files in fabrics.values() for path in files)
    assert written == sorted(expected)
    for path in written:
        raw = _read(path)
        assert raw == expected[path], path
        assert b"\r" not in raw and raw.count(b"\n") >= 5, path      # multi-line: the simulator had work to do
    assert {newline for _path, newline in seen} == {""}
    assert _files_under(tmp_path) == _published(seen) == set(written)


_TRANSLATING_OPENERS = ("open", "builtins.open", "io.open", "os.fdopen")


def _text_writes_without_a_newline_policy(source: str):
    """``(text_writes, offenders)`` for one module's source. A text write is a call of a newline-translating
    writer -- builtin/``io`` ``open`` or ``os.fdopen`` in a write mode, or ``Path.write_text`` -- and an offender
    is one that does not pin ``newline`` to "" or "\\n". A mode that is not a string literal is an offender too:
    a write whose translation is chosen at runtime cannot be shown host-independent."""
    writes, offenders = 0, []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name = ast.unparse(node.func)
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        if name in _TRANSLATING_OPENERS:
            mode = kw.get("mode", node.args[1] if len(node.args) > 1 else None)
            if mode is None:
                continue                                             # default "r": a read
            if not (isinstance(mode, ast.Constant) and isinstance(mode.value, str)):
                offenders.append((node.lineno, name, "mode is not a literal"))
                continue
            if "b" in mode.value or not set(mode.value) & set("wax+"):
                continue                                             # binary, or a text read
            newline = kw.get("newline", node.args[5] if len(node.args) > 5 else None)
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "write_text":
            newline = kw.get("newline", node.args[3] if len(node.args) > 3 else None)
        else:
            continue
        writes += 1
        if not (isinstance(newline, ast.Constant) and newline.value in ("", "\n")):
            offenders.append((node.lineno, name, "newline unset" if newline is None else ast.unparse(newline)))
    return writes, offenders


def test_the_newline_policy_check_flags_the_pre_fix_writer_shapes():
    """The structural check below is not vacuous: it flags the exact pre-F10 writer shapes (and an unprovable
    runtime mode) and passes the fixed ones, binary writes and reads."""
    planted = (
        'open(p, "w", encoding="utf-8")\n'                            # 1 the pre-fix capture / export writer
        'os.fdopen(fd, "a")\n'                                        # 2
        'Path(p).write_text(s, encoding="utf-8")\n'                   # 3
        'open(p, "w", -1, "utf-8", None, None)\n'                     # 4 newline passed positionally, unset
        'open(p, mode)\n'                                             # 5 unprovable
        'open(p, "w", encoding="utf-8", newline="")\n'
        'open(p, "w", newline="\\n")\n'
        'open(p, "w", -1, "utf-8", None, "")\n'
        'open(p, "wb")\n'
        'open(p, encoding="utf-8")\n'
        'open(p, "r", encoding="utf-8")\n'
    )
    writes, offenders = _text_writes_without_a_newline_policy(planted)
    assert writes == 7
    assert sorted(line for line, _name, _why in offenders) == [1, 2, 3, 4, 5]


def test_every_live_collector_text_write_pins_no_newline_translation():
    """The class, not the call sites: every text-mode write in every module hosting a live collector -- derived
    from the live denominators (`collect` for SSH, `CONTROLLER_COLLECTORS` for REST), not from a list of file
    names -- declares newline="" (or "\\n"), so a writer added later cannot reintroduce host translation
    unnoticed. (The behavioural tests above prove the bytes; this one stops the next writer.)"""
    ssh_module = inspect.getsourcefile(C.collect)
    modules = {ssh_module} | {inspect.getsourcefile(fn) for fn in R.CONTROLLER_COLLECTORS.values()}
    assert len(modules) >= 2, modules                                # the SSH entry module and rest_collect
    for path in sorted(modules):
        with _REAL_OPEN(path, encoding="utf-8") as fh:
            writes, offenders = _text_writes_without_a_newline_policy(fh.read())
        name = os.path.basename(path)
        assert writes >= 1, f"{name}: no text write found -- the scan is looking at nothing"
        assert not offenders, f"{name}: text write(s) left to host newline translation: {offenders}"
