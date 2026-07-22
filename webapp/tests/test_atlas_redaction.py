"""Atlas `--redact-folder` — the share-safe deliverable set, producible FROM THE STICK (ADR-0004 P3).

The gap this closes: `--redact` is the control that makes client data shareable, but the engine
hard-requires a `--template` workbook and a `--devices-file` that the portable bundle does not
carry, so the documented field command could not run there at all. Both are synthesized exactly as
the ingest channel already does.

Harness discipline matches the sibling files: the engine subprocess is always faked (a stub that
writes the snapshot the caller harvests), no real engine run, no real DB.
"""

import io
import json
import os
import re
import sys
import time
import types
import zipfile
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


def _docbytes(name="word/document.xml"):
    """A minimal REAL zip — .docx/.pptx/.xlsx are zips, and the completeness check reads their
    central directory to tell a finished document from a truncated one."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, "<w:document/>")
    return buf.getvalue()


def _family_engine(record: dict, omit=(), stderr="", truncate=(), extra_files=()):
    """A COMPLETE engine run — every document of the family, named exactly as the real writers
    name them — with `omit` naming family keys whose writer "failed" and `truncate` naming ones
    left 0-byte. Reproduces the fail-soft shape the engine really has: the writer logs a warning
    and the run still exits 0. Documents are written as real (tiny) zips, because that is what
    distinguishes a delivered .docx from a half-written one."""
    from cisco_toolkit.docmeta import cli_artifacts

    def run(cmd, cwd=None, **kw):
        record["cmd"] = list(cmd)
        out = Path(cmd[cmd.index("--output") + 1])
        stem = str(out)[: -len(".xlsx")]
        Path(stem + ".snapshot.json").write_text(json.dumps(REDACTED_SNAP), encoding="utf-8")
        for key, _name, filename in cli_artifacts(Path(stem).name):
            if key in omit:
                continue
            target = out.parent / filename
            if key in truncate:
                target.write_bytes(b"")          # truncate-then-ENOSPC: the file exists, empty
            elif filename.endswith((".docx", ".pptx", ".xlsx")):
                target.write_bytes(_docbytes())
            else:
                target.write_text("<html>explorer</html>", encoding="utf-8")
        for name in extra_files:
            (out.parent / name).write_bytes(b"deliverable")
        return types.SimpleNamespace(returncode=0, stdout="engine ok", stderr=stderr)
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
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec, extra_files=("Deck.pptx",)))
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


# ── the OTHER silence: a set that is safe but SHORT ─────────────────────────────
# Every deliverable writer in the engine sits in its own try/except that only logs a warning and
# continues (deliberately: the workbook and snapshot must still save when an optional library is
# absent). The redaction guards above certify that what IS written is safe and say nothing about
# what is ABSENT — so a run that rendered 13 of 15 files exited 0, printed "Wrote 13 file(s)", and
# the engineer could send a partial family believing it was the whole set.
def test_a_complete_run_reports_nothing_missing(monkeypatch, tmp_path):
    """Non-vacuity anchor for every case below: when the engine writes the whole family the check
    must stay SILENT. A completeness check that fires on a good run is worse than none — it is
    the exact false-alarm shape that trained engineers to ignore the redaction warnings."""
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec))
    out = tmp_path / "share"
    report = ing.run_redaction_folder(str(_collection(tmp_path)), str(out))
    assert report["missing"] == []
    assert report["engine_warnings"] == []
    assert not (out / "INCOMPLETE-SET.txt").exists()
    assert len(report["files"]) >= 10, report["files"]


def test_a_short_set_is_named_deliverable_by_deliverable(monkeypatch, tmp_path):
    """The engineer must learn WHICH documents are absent — 'incomplete' alone is unactionable at
    a client site with no second copy of the tool."""
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec, omit=("runbook", "deck")))
    report = ing.run_redaction_folder(str(_collection(tmp_path)), str(tmp_path / "share"))
    missing = {m["key"]: m for m in report["missing"]}
    assert set(missing) == {"runbook", "deck"}
    assert missing["runbook"]["filename"] == "Assessment_redacted_runbook.docx"
    assert "Runbook" in missing["runbook"]["name"]
    # ...and the documents that DID render are still reported as produced.
    assert "Assessment_redacted_design.docx" in report["files"]
    # The engine said NOTHING here, and the gap is still caught: the produced-vs-expected diff is
    # the detector, its warnings only the explanation. Verified against the real engine — running
    # it with --no-docx --no-pptx drops two documents and logs not one word about either, so a
    # design that scanned stderr for "write failed" would have missed this exact case.
    assert report["engine_warnings"] == []


def test_a_short_set_is_not_refused(monkeypatch, tmp_path):
    """Deliberate: a missing document is not a leak. Raising EngineRunError would print 'treat
    anything already written as UNREDACTED' over files that are correctly redacted — false, and
    the fastest way to make the real leak alarm unbelievable."""
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec, omit=("crd",)))
    report = ing.run_redaction_folder(str(_collection(tmp_path)), str(tmp_path / "share"))
    assert report["missing"] and report["files"]      # produced AND disclosed, not refused


def test_the_engines_own_reason_is_surfaced(monkeypatch, tmp_path):
    """The diff detects the gap; the engine's warning explains it. Both matter: 'missing' tells
    the engineer what to re-send, the reason tells them whether a re-run would even help."""
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(
        rec, omit=("runbook",),
        stderr="WARNING -   Runbook (DOCX) skipped: python-docx not installed\n"
               "INFO - [OK] Snapshot: written"))
    report = ing.run_redaction_folder(str(_collection(tmp_path)), str(tmp_path / "share"))
    assert any("python-docx not installed" in w for w in report["engine_warnings"])
    assert not any("[OK] Snapshot" in w for w in report["engine_warnings"]), \
        "only lines explaining a GAP belong here"


def test_a_refused_document_gate_is_reported_as_a_reason(monkeypatch, tmp_path):
    """A gate refusal is a correct refusal, but the SET is still short — the engineer must not
    discover that at the client.

    NB this shape is currently UNREACHABLE through --redact-folder: gate_state.enforce resolves
    docs/engagement-state.json against the engine child's cwd, which is always a fresh temp
    workdir, so no store is ever found and the design/MOP gates always pass. The case is kept
    because the reporting must hold if that ever changes; it is not evidence that it happens."""
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(
        rec, omit=("design",),
        stderr="ERROR - [GATE REFUSED] design: missing upstream approval(s): assessment"))
    report = ing.run_redaction_folder(str(_collection(tmp_path)), str(tmp_path / "share"))
    assert [m["key"] for m in report["missing"]] == ["design"]
    assert any("GATE REFUSED" in w for w in report["engine_warnings"])


def test_a_short_set_leaves_an_on_disk_note_that_does_not_cry_leak(monkeypatch, tmp_path):
    """stderr scrolls away; the folder is what a hurried engineer looks at before zipping it. The
    note must be honest in BOTH directions — the files here ARE safe to share."""
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec, omit=("mop",)))
    out = tmp_path / "share"
    ing.run_redaction_folder(str(_collection(tmp_path)), str(out))
    marker = out / "INCOMPLETE-SET.txt"
    assert marker.is_file()
    text = marker.read_text(encoding="ascii")            # cp437 field consoles / Notepad
    assert "INCOMPLETE" in text and "Assessment_redacted_mop.docx" in text
    assert "IS redacted and safe to share" in text
    assert not (out / "DO-NOT-SEND-NOT-REDACTED.txt").exists(), \
        "a missing document must not be reported as an unredacted-output leak"


def test_the_note_is_not_counted_as_a_deliverable(monkeypatch, tmp_path):
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec, omit=("crd",)))
    report = ing.run_redaction_folder(str(_collection(tmp_path)), str(tmp_path / "share"))
    assert "INCOMPLETE-SET.txt" not in report["files"]


def test_a_stale_note_is_cleared_once_the_set_is_whole(monkeypatch, tmp_path):
    """A marker that outlives its cause is the same lie in the other direction."""
    rec = {}
    out = tmp_path / "share"
    src = str(_collection(tmp_path))
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec, omit=("deck",)))
    ing.run_redaction_folder(src, str(out))
    assert (out / "INCOMPLETE-SET.txt").is_file()
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec))     # re-run, complete
    report = ing.run_redaction_folder(src, str(out), reuse_out=True)
    assert report["missing"] == []
    assert not (out / "INCOMPLETE-SET.txt").exists()


def test_only_atlas_own_note_is_ever_deleted(monkeypatch, tmp_path):
    """The engineer's own file of that name is not ours to remove."""
    rec = {}
    out = tmp_path / "share"
    out.mkdir()
    (out / "INCOMPLETE-SET.txt").write_text("my own notes about this job", encoding="ascii")
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec))
    ing.run_redaction_folder(str(_collection(tmp_path)), str(out))
    assert (out / "INCOMPLETE-SET.txt").read_text(encoding="ascii") == "my own notes about this job"


def test_re_running_into_the_same_folder_still_reports_what_it_wrote(monkeypatch, tmp_path):
    """Regression: 'produced by this run' was membership-only, so a second run into the same --out
    saw every re-rendered document as pre-existing and reported 'Wrote 0 file(s)'. Harmless while
    nothing read that list; the completeness check reads it, and would have called a perfectly
    complete re-run a set missing all ten deliverables."""
    rec = {}
    out = tmp_path / "share"
    src = str(_collection(tmp_path))
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec))
    first = ing.run_redaction_folder(src, str(out))
    # Force a distinguishable mtime even on a coarse (FAT32, 2s) filesystem.
    for p in out.iterdir():
        os.utime(p, (0, 0))
    second = ing.run_redaction_folder(src, str(out), reuse_out=True)
    assert second["missing"] == []
    assert set(second["files"]) == set(first["files"])


def test_cli_says_the_set_is_short_without_calling_it_unsafe(monkeypatch, tmp_path, capsys):
    """The field surface: the gap is impossible to miss and is never dressed up as a leak."""
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec, omit=("runbook", "opshandbook")))
    rc = serve.main(["--redact-folder", str(_collection(tmp_path)), "--out", str(tmp_path / "o")])
    cap = capsys.readouterr()
    assert rc == 3, "0 must keep meaning complete-and-verified; 1 is the redaction-failure code"
    assert "INCOMPLETE SET" in cap.out
    assert "Assessment_redacted_runbook.docx" in cap.out
    assert "Assessment_redacted_ops_handbook.docx" in cap.out
    assert "redaction FAILED" not in cap.out and "UNREDACTED" not in cap.out
    # The path the banner tells the engineer to look at must be the file that actually exists.
    # The marker name is spelled in ingest.py, serve.py and README-FIELD.txt; nothing but this
    # reconciles them, and a note nobody can find is the same as no note at all.
    named = re.search(r"list is saved as (.+INCOMPLETE-SET\.txt)", cap.out)
    assert named and Path(named.group(1)).is_file(), cap.out


def test_the_warning_is_the_last_thing_in_a_redirected_log(monkeypatch, tmp_path, capsys):
    """`Atlas.exe ... > run.log 2>&1` is the natural thing to do for a ten-minute run at a client
    site. Python block-buffers stdout and line-buffers stderr when redirected, so a warning on
    stderr got hoisted ABOVE the command banner — reading as though it belonged to a previous
    command — and the log ENDED on the reassurance block, making `tail` show a clean success.
    One stream, warning last: the final words the engineer reads are the ones that qualify it."""
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec, omit=("deck",)))
    serve.main(["--redact-folder", str(_collection(tmp_path)), "--out", str(tmp_path / "o")])
    cap = capsys.readouterr()
    assert "INCOMPLETE SET" not in cap.err, "must not straddle two differently-buffered streams"
    body = cap.out.strip()
    assert body.index("Checked:") < body.index("INCOMPLETE SET"), \
        "the qualification must come after the thing it qualifies"
    tail = "\n".join(body.splitlines()[-6:])
    assert "INCOMPLETE SET" in tail or "not included" in tail, \
        f"a `tail` of the log must show the warning, got:\n{tail}"


def test_the_reuse_refusal_reaches_the_console_as_a_sentence(monkeypatch, tmp_path, capsys):
    rec = {}
    out = tmp_path / "o"
    src = str(_collection(tmp_path))
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec))
    assert serve.main(["--redact-folder", src, "--out", str(out)]) == 0
    rc = serve.main(["--redact-folder", src, "--out", str(out)])
    err = capsys.readouterr().err
    assert rc == 1 and "Traceback" not in err
    assert "--reuse-out" in err and "already holds a redacted deliverable set" in err
    assert serve.main(["--redact-folder", src, "--out", str(out), "--reuse-out"]) == 0


def test_cli_stays_quiet_when_the_family_is_complete(monkeypatch, tmp_path, capsys):
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec))
    rc = serve.main(["--redact-folder", str(_collection(tmp_path)), "--out", str(tmp_path / "o")])
    cap = capsys.readouterr()
    assert rc == 0 and "INCOMPLETE" not in cap.err + cap.out


# ── what an independent refuter got past the first version of the check ─────────
# Each case below is a defect an adversarial review demonstrated against the completeness check
# as first written. They are the difference between a check that closes the silent-partial-set
# hole and one that only appears to.
def test_a_truncated_deliverable_is_not_counted_as_delivered(monkeypatch, tmp_path):
    """The original bug, re-armed. Every writer truncates its target and THEN writes, so a stick
    that fills mid-render leaves a 0-byte file with a brand-new timestamp; the engine logs a
    warning and exits 0. A name-and-mtime check certified that folder as the complete family."""
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec, truncate=("explorer",)))
    out = tmp_path / "share"
    report = ing.run_redaction_folder(str(_collection(tmp_path)), str(out))
    assert (out / "Assessment_redacted_explorer.html").stat().st_size == 0   # it IS on disk...
    gap = {m["key"]: m for m in report["missing"]}
    assert set(gap) == {"explorer"} and gap["explorer"]["state"] == "unusable"
    assert "0 bytes" in gap["explorer"]["detail"]


def test_a_corrupt_document_container_is_not_counted_as_delivered(monkeypatch, tmp_path):
    """Half a .docx is not a deliverable. A Word file is a zip whose central directory sits at the
    END, so a truncated one cannot be opened — which is exactly how an interrupted write fails."""
    rec = {}
    out = tmp_path / "share"
    engine = _family_engine(rec)

    def truncating(cmd, **kw):
        result = engine(cmd, **kw)
        p = Path(cmd[cmd.index("--output") + 1]).parent / "Assessment_redacted_design.docx"
        p.write_bytes(p.read_bytes()[:20])      # header survives, central directory does not
        return result

    monkeypatch.setattr(ing.subprocess, "run", truncating)
    report = ing.run_redaction_folder(str(_collection(tmp_path)), str(out))
    gap = {m["key"]: m for m in report["missing"]}
    assert set(gap) == {"design"} and "not open" in gap["design"]["detail"]


def test_a_clock_that_moved_backwards_does_not_condemn_a_perfect_run(monkeypatch, tmp_path):
    """The alarm-fatigue failure. A strictly-greater mtime test assumes the clock only moves
    forward; on an air-gapped field laptop (manual time correction) or a FAT32 stick carried
    across a timezone or a DST boundary, previously-written files read back as NEWER — and every
    document of a flawless run was reported missing, with a note written into a complete folder."""
    rec = {}
    out = tmp_path / "share"
    src = str(_collection(tmp_path))
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec))
    ing.run_redaction_folder(src, str(out))
    for p in out.iterdir():                      # every stamp an hour in the FUTURE
        os.utime(p, (time.time() + 3600, time.time() + 3600))
    report = ing.run_redaction_folder(src, str(out), reuse_out=True)
    assert report["missing"] == [], "a good re-run must never report the whole family missing"
    assert not (out / "INCOMPLETE-SET.txt").exists()
    assert len(report["files"]) >= 10


def test_reusing_an_output_folder_that_holds_a_set_is_refused_before_any_work(monkeypatch,
                                                                             tmp_path):
    """The whole answer to cross-job contamination, and it is PREVENTION, not repair.

    Two engagements sharing one --out plus one failed writer leaves job A's document under exactly
    the name job B's should have had — and redaction keeps hostnames and site codes, so it
    identifies job A's client inside job B's delivery. Every after-the-fact treatment was worse:
    warning about a file the engineer can plainly see is disbelieved; moving it aside mutates the
    folder, contradicts the manifest the engine already sealed over the pre-move contents, and
    rips a GOOD same-job document out of an otherwise complete set. Refusing costs milliseconds
    rather than ten minutes and removes the precondition instead of the symptom."""
    rec = {}
    out = tmp_path / "share"
    src = str(_collection(tmp_path))
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec))
    ing.run_redaction_folder(src, str(out))                       # job A
    rec["cmd"] = None
    with pytest.raises(ing.IngestError) as e:                     # job B, same folder
        ing.run_redaction_folder(src, str(out))
    assert rec["cmd"] is None, "must refuse BEFORE spending ten minutes in the engine"
    msg = str(e.value)
    assert "already holds a redacted deliverable set" in msg
    assert "--reuse-out" in msg and "EMPTY folder" in msg
    assert "hostnames" in msg                    # says WHY, not just what


def test_an_empty_or_unrelated_output_folder_is_not_refused(monkeypatch, tmp_path):
    """The refusal must key on a DELIVERABLE SET, not on the folder being non-empty — an
    engineer's own notes sitting in the destination are not a reason to stop."""
    rec = {}
    out = tmp_path / "share"
    out.mkdir()
    (out / "site-notes.txt").write_text("cab booked for 22:00", encoding="ascii")
    (out / "Assessment_FULL_UNREDACTED.xlsx").write_bytes(b"the engineer's own export")
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec))
    report = ing.run_redaction_folder(str(_collection(tmp_path)), str(out))   # must not raise
    assert report["missing"] == []


def test_reuse_out_is_the_deliberate_escape(monkeypatch, tmp_path):
    """Re-running the SAME job after a short set is legitimate and must stay possible."""
    rec = {}
    out = tmp_path / "share"
    src = str(_collection(tmp_path))
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec, omit=("mop",)))
    ing.run_redaction_folder(src, str(out))
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec))
    report = ing.run_redaction_folder(src, str(out), reuse_out=True)
    assert report["missing"] == []


def test_a_stale_copy_under_reuse_out_is_reported_as_stale_not_as_absent(monkeypatch, tmp_path):
    """With --reuse-out the engineer has accepted the folder, so stale becomes reachable again.
    It must be named as stale, NOT as absent: calling it missing sends them to a folder where the
    file plainly exists, which reads as a false alarm. Nothing is moved or deleted — the earlier
    refusal is what prevents the cross-job case, and mutating a same-job folder only ever removed
    a good document from a complete set."""
    rec = {}
    out = tmp_path / "share"
    src = str(_collection(tmp_path))
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec))
    ing.run_redaction_folder(src, str(out))
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec, omit=("mop",)))
    report = ing.run_redaction_folder(src, str(out), reuse_out=True)
    gap = {m["key"]: m for m in report["missing"]}
    assert set(gap) == {"mop"} and gap["mop"]["state"] == "stale"
    assert (out / "Assessment_redacted_mop.docx").is_file()      # untouched
    note = (out / "INCOMPLETE-SET.txt").read_text(encoding="ascii")
    assert "EARLIER run" in note and "STALE" in note
    assert "another client" in note              # hostnames survive redaction by design


def test_a_stem_named_file_the_engineer_saved_is_never_claimed(monkeypatch, tmp_path):
    """Guards a REGRESSION found by review: 'produced by this run' was widened from
    name-membership to a STEM PREFIX, which re-admitted anything the engineer kept alongside the
    set. `Assessment_redacted_IP_CROSSWALK.xlsx` — a pseudonym-to-real-IP crosswalk, the one file
    that must never travel — saved during the multi-minute run was then listed under the
    share-safe banner. The prefix test passed the old guard test only because its fixture name
    happened not to start with the stem."""
    rec = {}
    out = tmp_path / "share"
    out.mkdir()
    crosswalk = out / "Assessment_redacted_IP_CROSSWALK.xlsx"
    crosswalk.write_bytes(b"240.0.0.1 -> 10.20.30.40")
    engine = _family_engine(rec)

    def touching(cmd, **kw):
        result = engine(cmd, **kw)
        crosswalk.write_bytes(b"240.0.0.1 -> 10.20.30.40  (re-saved mid-run)")
        return result

    monkeypatch.setattr(ing.subprocess, "run", touching)
    report = ing.run_redaction_folder(str(_collection(tmp_path)), str(out))
    assert "Assessment_redacted_IP_CROSSWALK.xlsx" not in report["files"]
    assert report["missing"] == []               # ...and it is not mistaken for a deliverable


def test_an_unreadable_deliverable_does_not_leak_its_path_into_the_note(monkeypatch, tmp_path):
    """Sibling of the engine-warning scrub: _unusable's own OSError branch carried the absolute
    --out path (named after the engagement in practice) into a note that gets zipped and sent."""
    err = OSError(13, "Permission denied")
    monkeypatch.setattr(ing.Path, "stat", lambda self, **kw: (_ for _ in ()).throw(err))
    why = ing._unusable(Path(r"D:\Acme-Bank-Merger-share\Assessment_redacted_crd.docx"))
    assert "Permission denied" in why and "Acme-Bank-Merger" not in why


def test_the_engineers_own_note_of_that_name_is_never_overwritten(monkeypatch, tmp_path):
    """The delete path was guarded and the WRITE path was not — the asymmetry is the defect. An
    engineer's own record of what they sent is exactly the kind of file this app must not eat."""
    rec = {}
    out = tmp_path / "share"
    out.mkdir()
    theirs = "Sent to client 14:20 - ref CHG0041233. DO NOT DELETE - audit record."
    (out / "INCOMPLETE-SET.txt").write_text(theirs, encoding="ascii")
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec, omit=("crd",)))
    report = ing.run_redaction_folder(str(_collection(tmp_path)), str(out))
    assert (out / "INCOMPLETE-SET.txt").read_text(encoding="ascii") == theirs
    # ...and the note still gets written somewhere, and the report says where.
    assert report["incomplete_note"] == str(out / "INCOMPLETE-SET-ATLAS.txt")
    assert "Customer Requirements" in Path(report["incomplete_note"]).read_text(encoding="ascii")


def test_an_annotated_note_survives_a_later_complete_run(monkeypatch, tmp_path):
    """The note invites the engineer to act on it, so annotating it is expected behaviour. A
    startswith-header guard deleted their annotation along with our text."""
    rec = {}
    out = tmp_path / "share"
    src = str(_collection(tmp_path))
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec, omit=("deck",)))
    ing.run_redaction_folder(src, str(out))
    note = out / "INCOMPLETE-SET.txt"
    with note.open("a", encoding="ascii") as fh:
        fh.write("\n-- 22-Jul 14:20 told client the deck is missing; ref CHG0041233 --\n")
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec))
    ing.run_redaction_folder(src, str(out), reuse_out=True)
    assert note.is_file() and "CHG0041233" in note.read_text(encoding="ascii")


def test_an_untouched_note_is_still_cleared_when_the_set_is_whole(monkeypatch, tmp_path):
    """The other half of the same rule: our own unmodified note must not outlive its cause."""
    rec = {}
    out = tmp_path / "share"
    src = str(_collection(tmp_path))
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec, omit=("deck",)))
    ing.run_redaction_folder(src, str(out))
    assert (out / "INCOMPLETE-SET.txt").is_file()
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec))
    ing.run_redaction_folder(src, str(out), reuse_out=True)
    assert not (out / "INCOMPLETE-SET.txt").exists()


def test_the_console_never_promises_a_note_that_was_not_written(monkeypatch, tmp_path, capsys):
    """A directory (or a read-only file) at that path made the write fail silently while stderr
    still told the engineer to go and read it."""
    rec = {}
    out = tmp_path / "share"
    (out / "INCOMPLETE-SET.txt").mkdir(parents=True)
    (out / "INCOMPLETE-SET-ATLAS.txt").mkdir()
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec, omit=("crd",)))
    rc = serve.main(["--redact-folder", str(_collection(tmp_path)), "--out", str(out)])
    cap = capsys.readouterr().out
    assert rc == 3 and "INCOMPLETE SET" in cap
    assert "list is saved as" not in cap
    assert "this console is the record" in cap


def test_engine_paths_do_not_travel_into_the_shared_note(monkeypatch, tmp_path):
    """The note is in the folder that gets zipped and sent. Engine breadcrumbs carry the --out
    path, which in practice is named after the engagement."""
    rec = {}
    out = tmp_path / "Acme-Bank-Merger-share"
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(
        rec, omit=("mop",),
        stderr=f"WARNING -   MOP (DOCX) write failed: [Errno 28] No space left: "
               f"'{out}\\Assessment_redacted_mop.docx'"))
    report = ing.run_redaction_folder(str(_collection(tmp_path)), str(out))
    assert report["engine_warnings"], "the reason should still be reported"
    assert not any("Acme-Bank-Merger" in w for w in report["engine_warnings"])
    assert "Acme-Bank-Merger" not in Path(report["incomplete_note"]).read_text(encoding="ascii")


def test_the_explorers_own_skip_message_is_recognised(monkeypatch, tmp_path):
    """A missing explorer template in the frozen bundle is the likeliest explorer failure, and it
    logs 'HTML Explorer skipped: template not found' — which a 'skipped: python-' pattern missed,
    leaving the most likely gap the least explained."""
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(
        rec, omit=("explorer",),
        stderr="WARNING -   HTML Explorer skipped: template not found at <path>"))
    report = ing.run_redaction_folder(str(_collection(tmp_path)), str(tmp_path / "share"))
    assert any("template not found" in w for w in report["engine_warnings"])


def test_a_pre_existing_unrelated_file_is_never_claimed_even_if_touched(monkeypatch, tmp_path):
    """Guards the ORIGINAL protection against the mtime rewrite: an engineer's own export saved
    while the (multi-minute) run is in flight must not join the share-safe file list."""
    rec = {}
    out = tmp_path / "share"
    out.mkdir()
    theirs = out / "Assessment_FULL_UNREDACTED.xlsx"
    theirs.write_bytes(b"pre-existing")
    engine = _family_engine(rec)

    def touching(cmd, **kw):
        result = engine(cmd, **kw)
        theirs.write_bytes(b"pre-existing, re-saved during the run")
        return result

    monkeypatch.setattr(ing.subprocess, "run", touching)
    report = ing.run_redaction_folder(str(_collection(tmp_path)), str(out))
    assert "Assessment_FULL_UNREDACTED.xlsx" not in report["files"]


def test_a_leftover_do_not_send_marker_is_called_out(monkeypatch, tmp_path, capsys):
    """Nothing deletes a DO-NOT-SEND marker (erring towards keeping a safety warning), so a clean
    run into a folder that holds one leaves it saying 'unsafe' and 'complete' at the same time."""
    rec = {}
    out = tmp_path / "share"
    src = str(_collection(tmp_path))
    monkeypatch.setattr(ing.subprocess, "run", _fake_engine(rec, snapshot=LEAKY_SNAP))
    with pytest.raises(ing.EngineRunError):
        ing.run_redaction_folder(src, str(out))
    assert (out / "DO-NOT-SEND-NOT-REDACTED.txt").is_file()
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec))
    # The refused run left a partial set behind, so retrying into the same folder is itself
    # refused until the engineer opts in - which is the correct order of business here.
    rc = serve.main(["--redact-folder", src, "--out", str(out), "--reuse-out"])
    cap = capsys.readouterr().out
    assert rc == 0
    assert "EARLIER" in cap and "DO-NOT-SEND-NOT-REDACTED.txt" in cap
    assert (out / "DO-NOT-SEND-NOT-REDACTED.txt").is_file(), "must not be deleted, only explained"


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
