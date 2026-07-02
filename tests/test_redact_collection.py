"""Raw-collection-dir secrets at rest (Plan A / Tier-1 #5).

The gap: --redact makes the DELIVERABLES share-safe but the raw collection dir (the
.txt captures, running-configs included) keeps every password / community / key in
CLEARTEXT on the consulting laptop, and nothing ever said so. This slice adds:
- redact_collection_dir(): opt-in IN-PLACE scrub of secret VALUES across the captures,
  reusing the same conservative _scrub_secrets deny-list (IPs / hostnames / MACs are
  KEPT so the dir stays analyzable and --compare-able; never auto-deleted);
- a loud [SENSITIVE] warning on every run naming the dir;
- --redact-collection CLI wiring (scrub runs AFTER analysis so the current run reads
  originals);
- devices.example.json + README making the password_env / $CISCO_PASS chain the
  documented default (the chain itself has existed since V3.23.1 — just unused)."""
import json
import os
import subprocess
import sys

import synthetic_fixtures as fx
from openpyxl import Workbook

from cisco_toolkit.html import _REDACT_PLACEHOLDER, redact_collection_dir

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "COLLECT_PARSE_V3_23_0.py")

CONFIG = """hostname CORE-1
enable secret 5 $1$AAAA$FakeHashValue123
username admin privilege 15 secret 9 $9$FakeAdminHash
snmp-server community S3cr3tRW RW
tacacs-server host 10.9.9.9 key MyTacacsKey99
interface Vlan10
 ip address 10.1.2.3 255.255.255.0
"""


def _seed(tmp_path):
    dev = tmp_path / "CORE-1"
    dev.mkdir()
    (dev / "show_running-config.txt").write_text(CONFIG, encoding="utf-8")
    (dev / "show_version.txt").write_text(
        "Cisco IOS XE Software, Version 17.09.04a\nUptime is 1 week\nSerial: FXS1234\n",
        encoding="utf-8")
    (dev / "api_dump.json").write_text('{"password": "keepme-not-a-txt-capture"}',
                                       encoding="utf-8")
    return dev


def test_scrub_replaces_secret_values_keeps_topology_facts(tmp_path):
    dev = _seed(tmp_path)
    scanned, changed = redact_collection_dir(str(tmp_path))
    text = (dev / "show_running-config.txt").read_text(encoding="utf-8")
    for gone in ("$1$AAAA$FakeHashValue123", "$9$FakeAdminHash", "S3cr3tRW", "MyTacacsKey99"):
        assert gone not in text, f"secret value survived the scrub: {gone}"
    assert _REDACT_PLACEHOLDER in text
    # the analyzable facts SURVIVE — this dir must stay usable for --no-collect/--compare
    for kept in ("hostname CORE-1", "10.1.2.3", "interface Vlan10", "snmp-server community"):
        assert kept in text, f"non-secret context was destroyed: {kept}"
    assert scanned == 2 and changed == 1        # both .txt scanned; only the config changed


def test_scrub_is_idempotent(tmp_path):
    _seed(tmp_path)
    redact_collection_dir(str(tmp_path))
    scanned, changed = redact_collection_dir(str(tmp_path))
    assert scanned == 2 and changed == 0, "second pass must be a no-op"


def test_non_txt_captures_are_untouched(tmp_path):
    dev = _seed(tmp_path)
    redact_collection_dir(str(tmp_path))
    assert (dev / "api_dump.json").read_text(encoding="utf-8") == \
        '{"password": "keepme-not-a-txt-capture"}'


def test_cli_flag_scrubs_after_analysis_and_warns(tmp_path):
    """E2E: a --no-collect run with --redact-collection (a) prints the [SENSITIVE]
    warning naming the dir, (b) produces the normal deliverables from the ORIGINALS,
    (c) leaves the raw dir scrubbed afterwards. The synthetic fixture's own config
    carries real secret shapes (enable secret 9 / community public), so no injection
    is needed."""
    collection = fx.write_collection(str(tmp_path / "collection"))
    devices = tmp_path / "devices.json"
    devices.write_text(json.dumps(fx.DEVICES), encoding="utf-8")
    template = tmp_path / "template.xlsx"
    wb = Workbook(); ws = wb.active; ws.title = "Interface Data"
    ws.append(["Hostname", "Port", "Status"]); wb.save(str(template))
    out_xlsx = tmp_path / "out.xlsx"

    # precondition: cleartext secret shapes exist in the raw captures
    raw_before = ""
    for r, _d, files in os.walk(collection):
        for fn in files:
            if fn.endswith(".txt"):
                raw_before += open(os.path.join(r, fn), encoding="utf-8", errors="ignore").read()
    assert "community public" in raw_before and "$9$" in raw_before

    proc = subprocess.run(
        [sys.executable, SCRIPT, "--no-collect", "--collection-dir", collection,
         "--devices-file", str(devices), "--template", str(template),
         "--output", str(out_xlsx), "--no-html", "--workers", "1", "--redact-collection"],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, f"pipeline failed:\n{proc.stdout}\n{proc.stderr}"
    console = proc.stdout + proc.stderr
    assert "[SENSITIVE]" in console, "the cleartext raw-dir warning must print on every run"
    assert "redact-collection" in console.lower()

    # deliverables were produced (from the pre-scrub originals — scrub runs last)
    assert out_xlsx.is_file()
    snap = json.load(open(os.path.splitext(str(out_xlsx))[0] + ".snapshot.json",
                          encoding="utf-8"))
    assert "devices" in snap

    raw_after = ""
    for r, _d, files in os.walk(collection):
        for fn in files:
            if fn.endswith(".txt"):
                raw_after += open(os.path.join(r, fn), encoding="utf-8", errors="ignore").read()
    assert "$9$FAKEsecretHASHonly" not in raw_after, "enable-secret hash survived"
    assert "community public" not in raw_after, "SNMP community value survived"
    assert _REDACT_PLACEHOLDER in raw_after
    # and the dir still EXISTS (never auto-deleted — it is the --compare source)
    assert os.path.isdir(collection)


def test_sensitive_warning_prints_even_without_the_flag(tmp_path):
    """The warning is unconditional — knowing the exposure exists must not require
    having already opted into the fix."""
    collection = fx.write_collection(str(tmp_path / "collection"))
    devices = tmp_path / "devices.json"
    devices.write_text(json.dumps(fx.DEVICES), encoding="utf-8")
    template = tmp_path / "template.xlsx"
    wb = Workbook(); ws = wb.active; ws.title = "Interface Data"
    ws.append(["Hostname", "Port", "Status"]); wb.save(str(template))
    proc = subprocess.run(
        [sys.executable, SCRIPT, "--no-collect", "--collection-dir", collection,
         "--devices-file", str(devices), "--template", str(template),
         "--output", str(tmp_path / "o.xlsx"), "--no-html", "--workers", "1"],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0
    assert "[SENSITIVE]" in (proc.stdout + proc.stderr)
    # no flag -> raw dir untouched
    raw = ""
    for r, _d, files in os.walk(collection):
        for fn in files:
            if fn.endswith(".txt"):
                raw += open(os.path.join(r, fn), encoding="utf-8", errors="ignore").read()
    assert "community public" in raw


def test_devices_example_documents_the_env_chain(monkeypatch):
    """devices.example.json ships at the repo root, holds NO literal passwords, uses
    password_env, and round-trips through the real loader (password resolves empty when
    the env is unset — the loader then warns instead of blocking, as designed)."""
    path = os.path.join(ROOT, "devices.example.json")
    assert os.path.isfile(path), "devices.example.json is missing from the repo root"
    raw = json.load(open(path, encoding="utf-8"))
    assert isinstance(raw, list) and raw
    assert all("password" not in e for e in raw), \
        "the EXAMPLE file must never carry a literal password field"
    assert any("password_env" in e for e in raw)

    sys.path.insert(0, ROOT)
    import COLLECT_PARSE_V3_23_0 as cp
    monkeypatch.delenv("CISCO_PASS", raising=False)
    for e in raw:
        monkeypatch.delenv(e.get("password_env", "") or "_NOPE_", raising=False)
    devices = cp.load_devices(path)
    assert devices and all(d["password"] == "" for d in devices)


def test_readme_documents_env_chain_and_redact_collection():
    readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    for needle in ("CISCO_PASS", "password_env", "--redact-collection", "devices.example.json"):
        assert needle in readme, f"README must document {needle}"
