"""Capture-integrity widening (Plan A / Tier-2 #6).

K1 shipped command-GENERIC (inspect_capture takes any command) but was FED run-config
only (the old `_ci_bodies = {host: {"show running-config": ...}}` at the entry call
site) — so a truncated/paginated/errored capture of any of the other ~160 collected
commands sailed through unflagged. This slice:

1. `compute_capture_integrity_from_paths` — same verdicts, fed from {host: {cmd: PATH}}
   (the pipeline's all_cmd_to_files), STREAMING one body at a time (the real fleet's
   captures total ~416 MB — never a whole-fleet dict in memory).
2. `unverified_prompt` — a live collection that fell back to netmiko's
   send_command_timing never had its prompt confirmed, so an OK-looking body may be
   silently truncated. The fallback set is persisted per device as _capture_meta.json
   and surfaced coverage-honestly: NO meta file (every pre-existing collection) means
   NO claim — never a retroactive verdict.

Together with snap['parse_yield'] this closes the explanation loop: zero-yield + a
non-ok capture = collection problem; zero-yield + clean capture = parser format gap."""
import json
import os
import sys

from cisco_toolkit.capture_integrity import (
    CAPTURE_META_FILENAME,
    compute_capture_integrity,
    compute_capture_integrity_from_paths,
    load_capture_meta,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

OK_BODY = "Interface    Status\nGi1/0/1      connected\nGi1/0/2      notconnect\n"
PAGED_BODY = "vlan 10\n name USERS\n --More-- "
ERR_BODY = "% Invalid input detected at '^' marker.\n"


def _write(tmp_path, host, cmd, body):
    d = tmp_path / host
    d.mkdir(parents=True, exist_ok=True)
    p = d / (cmd.replace(" ", "_") + ".txt")
    p.write_text(body, encoding="utf-8")
    return str(p)


def test_from_paths_matches_dict_api_verdicts(tmp_path):
    """Differential: the streaming path-fed API must produce the SAME findings the
    in-memory dict API produces for identical content."""
    paths = {"SW1": {
        "show interfaces status": _write(tmp_path, "SW1", "show interfaces status", OK_BODY),
        "show vlan brief": _write(tmp_path, "SW1", "show vlan brief", PAGED_BODY),
        "show ip route": _write(tmp_path, "SW1", "show ip route", ERR_BODY),
    }}
    bodies = {"SW1": {c: open(p, encoding="utf-8").read() for c, p in paths["SW1"].items()}}
    via_paths = compute_capture_integrity_from_paths(paths)
    via_dict = compute_capture_integrity(bodies)
    assert via_paths["findings"] == via_dict["findings"]
    assert via_paths["summary"]["n_findings"] == 2          # pager + CLI error; OK emits no row


def test_wider_than_runconfig_is_the_point(tmp_path):
    """The exact class the old feed missed: a paginated NON-config command is flagged."""
    paths = {"SW1": {"show mac address-table":
                     _write(tmp_path, "SW1", "show mac address-table", PAGED_BODY)}}
    out = compute_capture_integrity_from_paths(paths)
    (f,) = out["findings"]
    assert f["command"] == "show mac address-table" and f["status"] == "incomplete"


def test_missing_file_is_skipped_not_claimed(tmp_path):
    """A path that no longer exists is collection-completeness's domain — the integrity
    guard must skip it silently, never fabricate an 'empty' verdict about a body it
    never saw."""
    paths = {"SW1": {"show version": str(tmp_path / "SW1" / "nope.txt")}}
    out = compute_capture_integrity_from_paths(paths)
    assert out["findings"] == [] and out["summary"]["n_findings"] == 0


def test_timing_fallback_meta_yields_unverified_prompt(tmp_path):
    """An OK-looking body collected via the send_command_timing fallback is
    'unverified_prompt' — the prompt was never confirmed, so completeness is unproven."""
    p = _write(tmp_path, "SW1", "show ip arp", OK_BODY)
    meta = {"SW1": {"show ip arp": "timing_fallback"}}
    out = compute_capture_integrity_from_paths({"SW1": {"show ip arp": p}}, meta)
    (f,) = out["findings"]
    assert f["status"] == "unverified_prompt"
    assert "prompt" in f["reason"].lower()
    assert out["summary"]["n_unverified_prompt"] == 1


def test_stronger_verdict_beats_unverified_prompt(tmp_path):
    """A fallback-collected capture that is ALSO visibly broken reports the stronger
    primary status (incomplete/error), not the weaker unverified_prompt."""
    p = _write(tmp_path, "SW1", "show vlan brief", PAGED_BODY)
    meta = {"SW1": {"show vlan brief": "timing_fallback"}}
    out = compute_capture_integrity_from_paths({"SW1": {"show vlan brief": p}}, meta)
    (f,) = out["findings"]
    assert f["status"] == "incomplete"
    assert out["summary"]["n_unverified_prompt"] == 0


def test_no_meta_means_no_unverified_claim(tmp_path):
    """Coverage-honest: every pre-existing collection has no _capture_meta.json — the
    guard must stay SILENT about prompt verification there, not guess."""
    p = _write(tmp_path, "SW1", "show ip arp", OK_BODY)
    out = compute_capture_integrity_from_paths({"SW1": {"show ip arp": p}}, None)
    assert out["findings"] == []


def test_capture_meta_roundtrip(tmp_path):
    d = tmp_path / "SW1"
    d.mkdir()
    (d / CAPTURE_META_FILENAME).write_text(
        json.dumps({"show ip arp": "timing_fallback"}), encoding="utf-8")
    assert load_capture_meta(str(d)) == {"show ip arp": "timing_fallback"}
    assert load_capture_meta(str(tmp_path / "SW-ABSENT")) == {}        # absent -> {}
    (d / CAPTURE_META_FILENAME).write_text("not json", encoding="utf-8")
    assert load_capture_meta(str(d)) == {}                             # corrupt -> {} (fail-soft)


def test_send_cmd_records_fallback_and_collect_persists_meta(tmp_path, monkeypatch):
    """Live-collect side: send_cmd flags the timing fallback per call (thread-local) and
    collect() persists the per-device fallback set as _capture_meta.json — the offline
    bridge that lets a later --no-collect re-analysis still know which captures were
    prompt-unverified."""
    import COLLECT_PARSE_V3_23_0 as cp

    class FlakyDev:
        """Pattern-read fails ONLY for 'show ip arp'; timing read then succeeds."""
        def send_command(self, cmd, read_timeout=0):
            if cmd == "show ip arp":
                raise OSError("prompt never seen")
            return "ok output\nline2\n"
        def send_command_timing(self, cmd, read_timeout=0):
            return "timing output\nline2\n"

    out_dir = str(tmp_path / "DEV1")
    paths = cp.collect("DEV1", "ios", FlakyDev(), out_dir)
    assert paths, "collect returned no capture paths"
    meta_path = os.path.join(out_dir, CAPTURE_META_FILENAME)
    assert os.path.isfile(meta_path), "_capture_meta.json was not persisted"
    meta = json.load(open(meta_path, encoding="utf-8"))
    assert meta.get("show ip arp") == "timing_fallback"
    assert all(v == "timing_fallback" for v in meta.values())
    assert list(meta) == ["show ip arp"], f"only the fallback command belongs in meta: {meta}"
    # and the meta file must never be mistaken for a capture (loader builds cmd_to_file
    # from KNOWN command names, so the sidecar is invisible to it by construction)
    assert not meta_path.endswith(".txt")


def test_summary_and_sort_include_the_new_status(tmp_path):
    """unverified_prompt sorts after the harder failures and is counted in the summary."""
    paths = {"SW1": {
        "show ip route": _write(tmp_path, "SW1", "show ip route", ERR_BODY),
        "show ip arp": _write(tmp_path, "SW1", "show ip arp", OK_BODY),
    }}
    meta = {"SW1": {"show ip arp": "timing_fallback"}}
    out = compute_capture_integrity_from_paths(paths, meta)
    statuses = [f["status"] for f in out["findings"]]
    assert statuses == ["error", "unverified_prompt"]
    s = out["summary"]
    assert s["n_error"] == 1 and s["n_unverified_prompt"] == 1 and s["n_findings"] == 2
