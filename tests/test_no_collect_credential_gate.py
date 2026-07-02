"""--no-collect must never block on credentials (the offline credential gate).

The defect (hit for real by the perf harness, 2026-07-02): load_devices() ran the FULL
V3.23.1 credential chain -- explicit password -> password_env -> $CISCO_PASS -> interactive
getpass on a TTY -- even when the run was --no-collect, i.e. a purely offline re-analysis
that never opens a single SSH session. A password-less devices.json on a TTY stdin
therefore parked the whole pipeline forever on an "SSH password for ..." prompt, for
credentials that are never used.

The fix (FIX-V3.23.177): main() passes allow_prompt=not args.no_collect into
load_devices(); with prompting disallowed the interactive getpass fallback is skipped
entirely (a debug note at most, never the loud set-$CISCO_PASS advice -- pointless
offline), while the NON-blocking env-chain resolution keeps running unchanged. Live
collection keeps the full V3.23.1 chain, TTY prompt included (default allow_prompt=True,
so every existing direct caller is untouched)."""
import json
import logging
import os
import sys

from openpyxl import Workbook

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import COLLECT_PARSE_V3_23_0 as cp  # noqa: E402


class _FakeTTYStdin:
    """Stands in for a console stdin: isatty() -> True (the pseudo-TTY the defect
    needs), and any actual read attempt fails loudly instead of blocking the suite."""

    def isatty(self):
        return True

    def read(self, *a, **k):
        raise AssertionError("pipeline tried to READ stdin during an offline run")

    readline = read


def _boobytrap_getpass(monkeypatch):
    """getpass.getpass on a real TTY BLOCKS forever; here it raises instead, so a
    regression turns the original silent hang into a loud test failure."""
    import getpass

    def _boom(prompt=""):
        raise AssertionError(f"getpass prompt fired during --no-collect: {prompt!r}")

    monkeypatch.setattr(getpass, "getpass", _boom)


def _passwordless_devices(tmp_path):
    p = tmp_path / "devices.json"
    p.write_text(json.dumps([
        {"hostname": "core1", "ip": "10.0.99.1", "username": "svc-audit", "platform": "ios"},
        {"hostname": "core2", "ip": "10.0.99.2", "username": "svc-audit", "platform": "nxos"},
    ]), encoding="utf-8")
    return p


def _template(tmp_path):
    path = tmp_path / "template.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Interface Data"
    ws.append(["Hostname", "Port", "Status"])
    wb.save(str(path))
    return path


def test_no_collect_passwordless_tty_does_not_prompt_and_completes(tmp_path, monkeypatch, caplog):
    """THE regression: --no-collect + password-less devices.json + a (pseudo) TTY must NOT
    prompt and must complete. Drives the REAL main() in-process (argv as from the command
    line) through the load_devices() choke point; --debug-headers then exits right after
    the template scan, so this isolates the credential gate without paying for the
    ~31-phase compute (the full --no-collect pipeline is already covered by
    test_pipeline_inprocess / the golden, whose fixture devices carry passwords)."""
    devices = _passwordless_devices(tmp_path)
    template = _template(tmp_path)
    collection = tmp_path / "collection"
    collection.mkdir()

    monkeypatch.delenv("CISCO_PASS", raising=False)
    monkeypatch.setattr(sys, "stdin", _FakeTTYStdin())
    _boobytrap_getpass(monkeypatch)
    monkeypatch.chdir(tmp_path)  # main() writes its log file into cwd
    monkeypatch.setattr(sys, "argv", [
        "cisco-assess", "--no-collect", "--collection-dir", str(collection),
        "--devices-file", str(devices), "--template", str(template),
        "--output", str(tmp_path / "out.xlsx"), "--workers", "1",
        "--debug-headers",
    ])
    with caplog.at_level(logging.DEBUG, logger="CiscoMigrationAutofillV3_14_6"):
        cp.main()  # pre-fix this re-raises the booby-trapped getpass (the real run HUNG here)

    # "at most a debug note": the loud '[WARN] No password ... set $CISCO_PASS or run
    # interactively' advice must NOT fire on an offline run -- those credentials are unused.
    noisy = [r for r in caplog.records
             if r.levelno >= logging.WARNING and "no password" in r.getMessage().lower()]
    assert noisy == [], f"offline run must not warn about unused credentials: {noisy}"


def test_live_collect_tty_prompt_chain_unchanged(tmp_path, monkeypatch):
    """Guard: V3.23.1 chain step 4 survives for LIVE collection. On a TTY, password-less
    entries still get the secure prompt -- once per username, not per device -- under the
    default allow_prompt=True (exactly what main() passes for a live run)."""
    devices = _passwordless_devices(tmp_path)
    monkeypatch.delenv("CISCO_PASS", raising=False)
    monkeypatch.setattr(sys, "stdin", _FakeTTYStdin())

    import getpass
    calls = []

    def _fake(prompt=""):
        calls.append(prompt)
        return "prompted-secret"

    monkeypatch.setattr(getpass, "getpass", _fake)
    out = cp.load_devices(str(devices))
    assert [d["password"] for d in out] == ["prompted-secret", "prompted-secret"]
    assert len(calls) == 1, "both devices share 'svc-audit' -> exactly one prompt"


def test_no_collect_env_chain_still_resolves(tmp_path, monkeypatch):
    """The gate kills ONLY the blocking step. With prompting disallowed, the non-blocking
    chain (explicit password -> password_env -> $CISCO_PASS) still resolves; a device with
    no source anywhere keeps password "" -- visible downstream, never a hang -- even on a
    TTY with getpass booby-trapped."""
    p = tmp_path / "devices.json"
    p.write_text(json.dumps([
        {"hostname": "a", "ip": "10.0.0.1", "username": "u", "password": "lit"},
        {"hostname": "b", "ip": "10.0.0.2", "username": "u", "password_env": "MY_PW"},
        {"hostname": "c", "ip": "10.0.0.3", "username": "u"},
    ]), encoding="utf-8")
    monkeypatch.setenv("MY_PW", "from-env")
    monkeypatch.delenv("CISCO_PASS", raising=False)
    monkeypatch.setattr(sys, "stdin", _FakeTTYStdin())
    _boobytrap_getpass(monkeypatch)

    out = cp.load_devices(str(p), allow_prompt=False)
    assert [d["password"] for d in out] == ["lit", "from-env", ""]
