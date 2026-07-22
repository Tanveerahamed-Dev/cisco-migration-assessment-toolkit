"""Atlas `--redact-folder` — the share-safe deliverable set, producible FROM THE STICK (ADR-0004 P3).

The gap this closes: `--redact` is the control that makes client data shareable, but the engine
hard-requires a `--template` workbook and a `--devices-file` that the portable bundle does not
carry, so the documented field command could not run there at all. Both are synthesized exactly as
the ingest channel already does.

Harness discipline matches the sibling files: the engine subprocess is always faked (a stub that
writes the snapshot the caller harvests), no real engine run, no real DB.
"""

import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `backend` importable

import backend.ingest as ing  # noqa: E402
import backend.serve as serve  # noqa: E402

REDACTED_SNAP = {"devices": {"core1": {"model": "C9300", "mgmt_ip": "240.0.0.1"}},
                 "interfaces": [{"switch": "core1", "port": "Gi1/0/1"}]}
LEAKY_SNAP = {"devices": {"core1": {"model": "C9300", "mgmt_ip": "10.20.30.40"}},
              "interfaces": [{"switch": "core1", "port": "Gi1/0/1"}]}


def _collection(tmp_path: Path) -> Path:
    d = tmp_path / "fleet"
    (d / "core1").mkdir(parents=True)
    (d / "core1" / "show_version.txt").write_text("Cisco IOS XE Software", encoding="utf-8")
    return d


def _fake_engine(record: dict, snapshot=None, extra_files=()):
    """Stand-in for a successful engine run: records argv/cwd and writes the deliverables the
    real engine would leave beside --output."""
    def run(cmd, cwd=None, **kw):
        record["cmd"] = list(cmd)
        record["cwd"] = cwd
        out = Path(cmd[cmd.index("--output") + 1])
        stem = str(out)[: -len(".xlsx")]
        Path(stem + ".snapshot.json").write_text(
            json.dumps(REDACTED_SNAP if snapshot is None else snapshot), encoding="utf-8")
        out.write_bytes(b"xlsx")
        for name in extra_files:
            (out.parent / name).write_bytes(b"deliverable")
        return types.SimpleNamespace(returncode=0, stdout="engine ok", stderr="")
    return run


# ── the synthesis that makes this runnable from the stick ───────────────────────
def test_synthesizes_the_two_inputs_the_stick_does_not_carry(monkeypatch, tmp_path):
    """The whole point: the engine needs a template and devices.json, the bundle ships neither."""
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _fake_engine(rec))
    ing.run_redaction_folder(str(_collection(tmp_path)), str(tmp_path / "out"))
    cmd = rec["cmd"]
    template = Path(cmd[cmd.index("--template") + 1])
    devices = Path(cmd[cmd.index("--devices-file") + 1])
    # Both were real files at call time, and both lived in the private workdir — never on the
    # stick and never in the user's tree.
    assert Path(rec["cwd"]) == template.parent == devices.parent
    assert Path(rec["cwd"]) not in (tmp_path / "out").parents
    assert "--redact" in cmd


def test_produces_the_full_document_family_not_ingests_fast_path(monkeypatch, tmp_path):
    """Ingest suppresses every document (`--no-docx` …) because AssessHub renders on demand. A
    redaction run is the opposite: the shareable set is the deliverable."""
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _fake_engine(rec))
    ing.run_redaction_folder(str(_collection(tmp_path)), str(tmp_path / "out"))
    assert not [f for f in rec["cmd"] if f.startswith("--no-") and f != "--no-collect"]


def test_deliverables_are_preserved_in_the_users_out_dir(monkeypatch, tmp_path):
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run",
                        _fake_engine(rec, extra_files=("Runbook.docx", "explorer.html")))
    out = tmp_path / "share"
    report = ing.run_redaction_folder(str(_collection(tmp_path)), str(out))
    assert {"Assessment_redacted.xlsx", "Runbook.docx", "explorer.html"} <= set(report["files"])
    assert (out / "Runbook.docx").is_file()      # survives the workdir cleanup
    assert report["out_dir"] == str(out.resolve())


def test_source_captures_are_untouched_unless_explicitly_asked(monkeypatch, tmp_path):
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _fake_engine(rec))
    src = _collection(tmp_path)
    before = (src / "core1" / "show_version.txt").read_bytes()
    ing.run_redaction_folder(str(src), str(tmp_path / "out"))
    assert "--redact-collection" not in rec["cmd"]
    assert (src / "core1" / "show_version.txt").read_bytes() == before
    assert not (src / "Assessment_redacted.xlsx").exists()


def test_redact_collection_is_opt_in_and_passed_through(monkeypatch, tmp_path):
    """It rewrites the RAW captures in place, so it must never ride along by default."""
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _fake_engine(rec))
    report = ing.run_redaction_folder(str(_collection(tmp_path)), str(tmp_path / "out"),
                                      redact_collection=True)
    assert "--redact-collection" in rec["cmd"] and report["redacted_collection"] is True


# ── the failure that must never be silent ───────────────────────────────────────
def test_unredacted_output_is_refused_loudly(monkeypatch, tmp_path):
    """Shipping client evidence labelled 'redacted' is the worst outcome here, and a flag that
    silently did nothing looks exactly like success — so the result is verified, not trusted."""
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _fake_engine(rec, snapshot=LEAKY_SNAP))
    with pytest.raises(ing.EngineRunError) as e:
        ing.run_redaction_folder(str(_collection(tmp_path)), str(tmp_path / "out"))
    msg = str(e.value)
    assert "REDACTION DID NOT APPLY" in msg and "10.20.30.40" in msg
    assert "not safe to share" in msg.lower()


def test_advisory_copy_citing_rfc1918_is_not_a_leak(monkeypatch, tmp_path):
    """The real engine ships guidance like "supernet, e.g. 10.0.0.0/16" in the design blueprint.
    Scanning raw JSON text flagged that and failed EVERY real run — and a check that always fires
    trains the engineer to ignore it. Caught by running the real engine, not by these stubs."""
    rec = {}
    snap = dict(REDACTED_SNAP)
    snap["design_blueprint"] = {
        "requirements_model": {"fields": [
            {"label": "Target address space (supernet, e.g. 10.0.0.0/16)"}]},
        "target_state": {"addressing_plan": {
            "note": "Supply an address_space (supernet, e.g. 10.0.0.0/16) to allocate subnets."}},
    }
    monkeypatch.setattr(ing.subprocess, "run", _fake_engine(rec, snapshot=snap))
    ing.run_redaction_folder(str(_collection(tmp_path)), str(tmp_path / "out"))  # must not raise


def test_a_private_address_in_config_text_is_still_a_leak(monkeypatch, tmp_path):
    """The exemption is for authored copy only — an address inside captured config text is
    exactly the leak this guard exists for, and must not be excused by living in a long string."""
    rec = {}
    snap = dict(REDACTED_SNAP)
    snap["running_config"] = {"core1": "interface Vlan10\n ip address 10.20.30.40 255.255.255.0\n"}
    monkeypatch.setattr(ing.subprocess, "run", _fake_engine(rec, snapshot=snap))
    with pytest.raises(ing.EngineRunError, match="10.20.30.40"):
        ing.run_redaction_folder(str(_collection(tmp_path)), str(tmp_path / "out"))


def test_leak_report_names_where_it_found_it(monkeypatch, tmp_path):
    """A bare address is not actionable at a client site; the engineer needs to know where."""
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _fake_engine(rec, snapshot=LEAKY_SNAP))
    with pytest.raises(ing.EngineRunError) as e:
        ing.run_redaction_folder(str(_collection(tmp_path)), str(tmp_path / "out"))
    assert "devices.core1.mgmt_ip" in str(e.value)


def test_class_e_pseudonyms_are_accepted(monkeypatch, tmp_path):
    """The redactor remaps every /24 into 240.0.0.0/4 — the check must not fire on its own output."""
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _fake_engine(rec))
    ing.run_redaction_folder(str(_collection(tmp_path)), str(tmp_path / "out"))  # must not raise


# ── refusals that protect the output ────────────────────────────────────────────
def test_refuses_to_write_inside_the_collection_folder(monkeypatch, tmp_path):
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _fake_engine(rec))
    src = _collection(tmp_path)
    with pytest.raises(ing.IngestError, match="collection folder"):
        ing.run_redaction_folder(str(src), str(src / "out"))


def test_refuses_to_write_inside_the_frozen_bundle(monkeypatch, tmp_path):
    """An update mirrors over everything in Atlas\\ except data\\, so output written there is lost."""
    bundle = tmp_path / "Atlas"
    bundle.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(bundle / "Atlas.exe"))
    with pytest.raises(ing.IngestError, match="app folder"):
        ing.run_redaction_folder(str(_collection(tmp_path)), str(bundle / "out"))


def test_rejects_a_missing_source_folder(tmp_path):
    with pytest.raises(ing.IngestError):
        ing.run_redaction_folder(str(tmp_path / "absent"), str(tmp_path / "out"))


def test_frozen_dispatch_uses_the_sentinel(monkeypatch, tmp_path):
    """Inside the exe there is no script on disk — the child must be the exe + sentinel."""
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _fake_engine(rec))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(ing, "_ENGINE_SCRIPT", tmp_path / "not-there.py")
    ing.run_redaction_folder(str(_collection(tmp_path)), str(tmp_path / "out"))
    assert rec["cmd"][:2] == [sys.executable, serve.ENGINE_SENTINEL]


# ── the CLI surface ─────────────────────────────────────────────────────────────
def test_cli_runs_redaction_and_reports_what_it_wrote(monkeypatch, tmp_path, capsys):
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _fake_engine(rec, extra_files=("Deck.pptx",)))
    rc = serve.main(["--redact-folder", str(_collection(tmp_path)), "--out", str(tmp_path / "o")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Assessment_redacted.xlsx" in out and "Deck.pptx" in out
    # The banner must state its LIMITS, not certify more than the code checks.
    assert "NOT checked" in out and "HOSTNAMES ARE KEPT BY DESIGN" in out
    assert "Every IP/MAC/serial is pseudonymized" not in out


def test_cli_requires_out_and_says_so(tmp_path, capsys):
    rc = serve.main(["--redact-folder", str(_collection(tmp_path))])
    assert rc == 2
    assert "--out" in capsys.readouterr().err


def test_cli_reports_failure_without_a_traceback(monkeypatch, tmp_path, capsys):
    def boom(*a, **kw):
        raise ing.EngineRunError("REDACTION DID NOT APPLY - 2 private address(es) survive")

    monkeypatch.setattr(ing, "run_redaction_folder", boom)
    rc = serve.main(["--redact-folder", str(_collection(tmp_path)), "--out", str(tmp_path / "o")])
    err = capsys.readouterr().err
    assert rc == 1
    assert "redaction FAILED" in err and "UNREDACTED" in err and "Traceback" not in err


def test_out_without_redact_folder_is_rejected(tmp_path, capsys):
    rc = serve.main(["--out", str(tmp_path / "o"), "--no-browser"])
    assert rc == 2
    assert "only apply to --redact-folder" in capsys.readouterr().err


# ── the silent leak found by fault injection (independent review) ───────────────
def _engine_with_failed_phase(record: dict, phase: str, via: str = "timings"):
    """The engine's _run_phase LOGS AND CONTINUES on any exception 'so the workbook still saves'.
    The snapshot is redacted by a DIRECT call and stays clean, so the workbook can ship real client
    data while the verified file is spotless and the run exits 0."""
    def run(cmd, cwd=None, **kw):
        record["cmd"] = list(cmd)
        out = Path(cmd[cmd.index("--output") + 1])
        stem = str(out)[: -len(".xlsx")]
        Path(stem + ".snapshot.json").write_text(json.dumps(REDACTED_SNAP), encoding="utf-8")
        out.write_bytes(b"xlsx with UNREDACTED cells")
        if via == "timings":
            Path(stem + ".phase_timings.json").write_text(
                json.dumps([{"phase": phase, "seconds": 0.1, "ok": False}]), encoding="utf-8")
            return types.SimpleNamespace(returncode=0, stdout="engine ok", stderr="")
        return types.SimpleNamespace(
            returncode=0, stderr=f"  [SKIP] Phase '{phase}' failed: RuntimeError(); "
                                 f"continuing so the workbook still saves.", stdout="")
    return run


@pytest.mark.parametrize("phase", ["redact collected dataclasses", "redact workbook cells"])
@pytest.mark.parametrize("via", ["timings", "stderr"])
def test_a_skipped_redaction_phase_is_refused(monkeypatch, tmp_path, phase, via):
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _engine_with_failed_phase(rec, phase, via))
    with pytest.raises(ing.EngineRunError) as e:
        ing.run_redaction_folder(str(_collection(tmp_path)), str(tmp_path / "out"))
    msg = str(e.value)
    assert "REDACTION PHASE FAILED" in msg and phase in msg
    assert "Do NOT send" in msg


def test_a_refused_run_leaves_a_do_not_send_marker(monkeypatch, tmp_path):
    """Nothing is deleted (that would destroy evidence) but the files are named *_redacted* — they
    assert the very property the run declined to certify, and stderr scrolls away."""
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _fake_engine(rec, snapshot=LEAKY_SNAP))
    out = tmp_path / "share"
    with pytest.raises(ing.EngineRunError):
        ing.run_redaction_folder(str(_collection(tmp_path)), str(out))
    marker = out / "DO-NOT-SEND-NOT-REDACTED.txt"
    assert marker.is_file()
    assert "NOT safe to share" in marker.read_text(encoding="ascii")


def test_only_files_this_run_produced_are_reported(monkeypatch, tmp_path):
    """Enumerating the directory reported the engineer's own pre-existing files under the
    share-safe banner — including, in the reviewer's run, an 'Assessment_FULL_UNREDACTED.xlsx'."""
    rec = {}
    out = tmp_path / "share"
    out.mkdir()
    (out / "Assessment_FULL_UNREDACTED.xlsx").write_bytes(b"pre-existing")
    monkeypatch.setattr(ing.subprocess, "run", _fake_engine(rec))
    report = ing.run_redaction_folder(str(_collection(tmp_path)), str(out))
    assert "Assessment_FULL_UNREDACTED.xlsx" not in report["files"]
    assert "Assessment_redacted.xlsx" in report["files"]


def test_refuses_when_out_is_the_parent_of_the_collection(tmp_path):
    """The raw captures would sit inside the folder the engineer zips and sends."""
    src = _collection(tmp_path / "job" / "share")
    with pytest.raises(ing.IngestError, match="raw captures would travel"):
        ing.run_redaction_folder(str(src), str(tmp_path / "job" / "share"))


def test_bad_out_path_is_a_sentence_not_a_traceback(monkeypatch, tmp_path, capsys):
    """--out is the one value the engineer invents on the spot, so it is the likeliest typo; a
    mistyped drive letter used to print a pathlib traceback after the reassuring banner."""
    blocker = tmp_path / "afile"
    blocker.write_text("not a directory", encoding="utf-8")
    rc = serve.main(["--redact-folder", str(_collection(tmp_path)), "--out", str(blocker / "sub")])
    err = capsys.readouterr().err
    assert rc == 1
    assert "Cannot create the output folder" in err and "Traceback" not in err


def test_truncated_snapshot_is_refused_not_a_json_traceback(monkeypatch, tmp_path):
    def run(cmd, cwd=None, **kw):
        out = Path(cmd[cmd.index("--output") + 1])
        Path(str(out)[: -len(".xlsx")] + ".snapshot.json").write_text('{"devices": {', encoding="utf-8")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(ing.subprocess, "run", run)
    with pytest.raises(ing.EngineRunError, match="could not be read back"):
        ing.run_redaction_folder(str(_collection(tmp_path)), str(tmp_path / "out"))


def test_field_messages_are_ascii(monkeypatch, tmp_path):
    """cp437 field consoles render an em-dash as '?'. serve.py already complies; these messages
    were outside both that rule and the README message ratchet."""
    import inspect
    src = inspect.getsource(ing)
    for i, line in enumerate(src.splitlines(), 1):
        s = line.strip()
        if s.startswith(("raise IngestError", "raise EngineRunError")) or "f\"" in s:
            if s.startswith(("#", "*", '"""', "#:")):
                continue
            assert "—" not in s, f"em-dash in a runtime message at ingest.py line ~{i}: {s[:80]}"


# ── calibration: the checker must be neither blind nor hysterical ───────────────
@pytest.mark.parametrize("fixture", ["tests/golden/snapshot.json",
                                     "webapp/sample_data/sample_fleet.snapshot.json"])
def test_checker_is_calibrated_against_real_redacted_snapshots(tmp_path, fixture):
    """Both failure modes have already happened here, one after the other:

    * too WIDE — scanning raw JSON flagged the design blueprint's own guidance
      ("supernet, e.g. 10.0.0.0/16") and would have failed EVERY real run; a check that always
      fires trains the engineer to ignore it.
    * too NARROW — the fix over-corrected into exempting 28% of the snapshot, including real
      evidence (punch-list titles, interface descriptions, per-device exposure labels).

    So pin both edges on REALISTIC data run through the REAL redactor: no false positive, and
    coverage stays high. A future exemption that quietly blinds the checker fails here."""
    from cisco_toolkit.html import redact_snapshot

    src = Path(__file__).resolve().parents[2] / fixture
    if not src.is_file():
        pytest.skip(f"{fixture} not present")
    redacted = redact_snapshot(json.loads(src.read_text(encoding="utf-8")))
    snap_path = tmp_path / "s.snapshot.json"
    snap_path.write_text(json.dumps(redacted), encoding="utf-8")

    ing._assert_scrubbed(snap_path)          # must NOT raise on properly-redacted evidence

    inspected = sum(1 for _ in ing._iter_evidence_strings(redacted))
    total = 0

    def count(node):
        nonlocal total
        if isinstance(node, dict):
            for v in node.values():
                count(v)
        elif isinstance(node, list):
            for v in node:
                count(v)
        elif isinstance(node, str):
            total += 1

    count(redacted)
    assert total > 100, "fixture too small to be a meaningful calibration"
    coverage = inspected / total
    assert coverage >= 0.90, (
        f"the checker now inspects only {coverage:.0%} of {fixture} ({inspected}/{total}); an "
        f"exemption has blinded it (this was 72% when real evidence was being skipped)")
