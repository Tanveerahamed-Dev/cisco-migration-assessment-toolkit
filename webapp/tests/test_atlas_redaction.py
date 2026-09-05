"""Atlas `--redact-folder` — the share-safe deliverable set, producible FROM THE STICK (ADR-0004 P3).

The gap this closes: `--redact` is the control that makes client data shareable, but the engine
hard-requires a `--template` workbook and a `--devices-file` that the portable bundle does not
carry, so the documented field command could not run there at all. Both are synthesized exactly as
the ingest channel already does.

Harness discipline matches the sibling files: the engine subprocess is always faked (a stub that
writes the snapshot the caller harvests), no real engine run, no real DB.
"""

import io
import hashlib
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

REDACTED_SNAP = {"devices": {"core1": {
                    "model": "C9300",
                    "mgmt_ip": "v4-n00001-h001.assesshub-redacted.invalid",
                 }},
                 "interfaces": [{"switch": "core1", "port": "Gi1/0/1"}]}
LEAKY_SNAP = {"devices": {"core1": {"model": "C9300", "mgmt_ip": "10.20.30.40"}},
              "interfaces": [{"switch": "core1", "port": "Gi1/0/1"}]}


def _positive_ledgers(out: Path) -> None:
    """Write the real positive phase/finalization contracts expected from a successful child."""
    from cisco_toolkit import manifest

    stem = str(out)[: -len(".xlsx")]
    timings = Path(stem + ".phase_timings.json")
    timings.write_text(
        json.dumps({
            "n_devices": 1,
            "workers": 1,
            "total_seconds": 0.2,
            "phases": [
                {"phase": "redact collected dataclasses", "seconds": 0.1, "ok": True},
                {"phase": "redact workbook cells", "seconds": 0.1, "ok": True},
            ],
        }),
        encoding="utf-8",
    )
    artifacts = {}
    for candidate in out.parent.iterdir():
        if not candidate.is_file() or candidate.name.endswith(".run_manifest.json"):
            continue
        raw = candidate.read_bytes()
        artifacts[candidate.name] = {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size": len(raw),
            "kind": "test",
        }
    payload = manifest.build_manifest(
        {
            "producer_finalization": {
                "mandatory_prerequisites": "complete",
                "failed_mandatory": [],
            },
            "redaction": {"requested": True, "status": "verified"},
        },
        artifacts,
        [],
    )
    Path(stem + ".run_manifest.json").write_text(json.dumps(payload), encoding="utf-8")


def _collection(tmp_path: Path) -> Path:
    d = tmp_path / "fleet"
    (d / "core1").mkdir(parents=True)
    (d / "core1" / "show_version.txt").write_text("Cisco IOS XE Software", encoding="utf-8")
    return d


def test_engine_filename_census_keeps_manifested_topology_sidecars() -> None:
    """A promoted manifest must not point back into the deleted private work directory."""
    names = ing._engine_filenames("Assessment_redacted")
    assert {"topology.dot", "topology.mmd"} <= names
    delivery = ing.redaction_delivery_filenames()
    assert delivery == names | {"Assessment_redacted.redaction.json"}


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
        out.write_bytes(_docbytes("xl/workbook.xml"))
        for name in extra_files:
            (out.parent / name).write_bytes(b"deliverable")
        _positive_ledgers(out)
        return types.SimpleNamespace(returncode=0, stdout="engine ok", stderr="")
    return run


#: The part a real Office package must carry for its kind, per `docmeta._OFFICE_REQUIRED` — asked
#: of the suffix, not hand-assigned, so a fixture cannot drift from the family it stands in for.
_OFFICE_PART = {".docx": "word/document.xml", ".pptx": "ppt/presentation.xml",
                ".xlsx": "xl/workbook.xml"}


def _docbytes(name="word/document.xml"):
    """A minimal REAL Office package — .docx/.pptx/.xlsx are zips, and the completeness check now
    validates them the way the engine's own custody gate does (`docmeta.validate_artifact`), which
    means opening `[Content_Types].xml` and the kind's required part.

    The fixture used to be a zip holding ONE arbitrary member, and a `word/document.xml` inside
    every .pptx and .xlsx at that. It stood in for a delivered document while being a shape Word
    cannot open — so a stronger check would have read as a broken run rather than a caught one.
    A fixture must come from the shape the real producer emits, or the test agrees with the bug."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr(name, "<document/>")
    return buf.getvalue()


def _family_engine(record: dict, omit=(), stderr="", truncate=(), extra_files=(), corrupt=None):
    """A COMPLETE engine run — every document of the family, named exactly as the real writers
    name them — with `omit` naming family keys whose writer "failed", `truncate` naming ones left
    0-byte and `corrupt` mapping a family key to the exact (non-empty, structurally broken) bytes
    an interrupted write leaves behind. Reproduces the fail-soft shape the engine really has: the
    writer logs a warning and the run still exits 0. Documents are written as real (tiny) zips,
    because that is what distinguishes a delivered .docx from a half-written one.

    `corrupt` writes BEFORE `_positive_ledgers`, so the run manifest seals the broken bytes exactly
    as a real interrupted write would — corrupting afterwards only reproduces a manifest mismatch,
    which is a different (already-guarded) failure and never reaches the completeness check."""
    from cisco_toolkit.docmeta import cli_artifacts

    corrupt = dict(corrupt or {})

    def run(cmd, cwd=None, **kw):
        record["cmd"] = list(cmd)
        out = Path(cmd[cmd.index("--output") + 1])
        stem = str(out)[: -len(".xlsx")]
        Path(stem + ".snapshot.json").write_text(json.dumps(REDACTED_SNAP), encoding="utf-8")
        for key, _name, filename in cli_artifacts(Path(stem).name):
            if key in omit:
                continue
            target = out.parent / filename
            if key in corrupt:
                target.write_bytes(corrupt[key])
            elif key in truncate:
                target.write_bytes(b"")          # truncate-then-ENOSPC: the file exists, empty
            elif target.suffix in _OFFICE_PART:
                target.write_bytes(_docbytes(_OFFICE_PART[target.suffix]))
            elif target.suffix == ".json":
                target.write_text("{}", encoding="utf-8")
            else:
                target.write_text("<html>explorer</html>", encoding="utf-8")
        for name in extra_files:
            (out.parent / name).write_bytes(b"deliverable")
        _positive_ledgers(out)
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


def test_only_canonical_engine_deliverables_are_certified_in_the_users_out_dir(monkeypatch, tmp_path):
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run",
                        _fake_engine(rec, extra_files=("Runbook.docx", "explorer.html")))
    out = tmp_path / "share"
    report = ing.run_redaction_folder(str(_collection(tmp_path)), str(out))
    assert "Assessment_redacted.xlsx" in report["files"]
    assert "Runbook.docx" not in report["files"] and "explorer.html" not in report["files"]
    assert not (out / "Runbook.docx").exists()   # non-canonical files never enter the certified set
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
    """It rewrites the RAW captures in place, so it must never ride along by default.

    NB this asserts only that the FLAG travelled, and says so by reading the key that names
    itself the flag. The old version asserted `report["redacted_collection"] is True` after
    passing `redact_collection=True` — it pinned the echo of its own input, which is why the
    scrub could stop happening without a single test noticing (see the outcome tests below)."""
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _scrub_engine(rec, stderr=_SCRUB_OK))
    report = ing.run_redaction_folder(str(_collection(tmp_path)), str(tmp_path / "out"),
                                      redact_collection=True)
    assert "--redact-collection" in rec["cmd"]
    assert report["redacted_collection_requested"] is True


# ── the failure that must never be silent ───────────────────────────────────────
def test_unredacted_output_is_refused_loudly(monkeypatch, tmp_path):
    """Shipping client evidence labelled 'redacted' is the worst outcome here, and a flag that
    silently did nothing looks exactly like success — so the result is verified, not trusted."""
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _fake_engine(rec, snapshot=LEAKY_SNAP))
    with pytest.raises(ing.EngineRunError) as e:
        ing.run_redaction_folder(str(_collection(tmp_path)), str(tmp_path / "out"))
    msg = str(e.value)
    assert "REDACTION DID NOT APPLY" in msg and "non-pseudonym IPv4" in msg
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
                "note": "Supply an address_space (supernet, e.g. 10.0.0.0/16) to allocate target subnets; "
                        "a net-new IP plan is not fabricated without one."}},
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
    with pytest.raises(ing.EngineRunError, match="IPv4"):
        ing.run_redaction_folder(str(_collection(tmp_path)), str(tmp_path / "out"))


def test_leak_report_names_where_it_found_it(monkeypatch, tmp_path):
    """A bare address is not actionable at a client site; the engineer needs to know where."""
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _fake_engine(rec, snapshot=LEAKY_SNAP))
    with pytest.raises(ing.EngineRunError) as e:
        ing.run_redaction_folder(str(_collection(tmp_path)), str(tmp_path / "out"))
    assert "devices.core1.mgmt_ip" in str(e.value)


def test_synthetic_pseudonyms_are_accepted(monkeypatch, tmp_path):
    """The verifier must accept the redactor's unmistakable ``.invalid`` marker namespace."""
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
    assert "Assessment_redacted.xlsx" in out and "Deck.pptx" not in out
    # The banner must state its limits without understating the independent checks.
    assert "independently scanned" in out and "HOSTNAMES ARE KEPT BY DESIGN" in out
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
    data while the verified file is spotless and the run exits 0.

    The `timings` sidecar is written in the engine's REAL shape — a dict whose "phases" key holds
    the rows (COLLECT_PARSE_V3_23_0._stage_finalize). It was faked here as a bare LIST, which is
    what the parser happened to expect: the stub and the bug agreed with each other, the test
    passed, and the sidecar arm was dead on every real run.
    tests/test_phase_timings_contract.py now pins the shape against a sidecar the real engine
    wrote, so a fabricated fixture can never certify the wrong format again."""
    def run(cmd, cwd=None, **kw):
        record["cmd"] = list(cmd)
        out = Path(cmd[cmd.index("--output") + 1])
        stem = str(out)[: -len(".xlsx")]
        Path(stem + ".snapshot.json").write_text(json.dumps(REDACTED_SNAP), encoding="utf-8")
        out.write_bytes(b"xlsx with UNREDACTED cells")
        if via == "timings":
            Path(stem + ".phase_timings.json").write_text(
                json.dumps({"n_devices": 1, "workers": 1, "total_seconds": 0.1,
                            "phases": [{"phase": phase, "seconds": 0.1, "ok": False}]}),
                encoding="utf-8")
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
    # Still reassures — but scoped to what THIS run wrote. The unqualified claim it used to make
    # ("Everything in this folder IS redacted and safe to share") was false whenever a document
    # from an earlier UNCERTIFIED run sat in the folder; see
    # test_the_note_never_claims_safety_over_an_uncertified_leftover.
    assert "IS redacted" in text and "DO NOT SEND THIS FOLDER" not in text
    assert not (out / ing.UNSAFE_MARKER).exists(), \
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


def test_a_corrupt_document_container_fails_redaction_verification(monkeypatch, tmp_path):
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
    with pytest.raises(ing.EngineRunError, match="corrupt OOXML container"):
        ing.run_redaction_folder(str(_collection(tmp_path)), str(out))
    assert (out / ing.UNSAFE_MARKER).is_file()


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


def test_reuse_promotes_only_the_current_generation_and_archives_the_prior_set(monkeypatch, tmp_path):
    """A short reuse run must not inherit a same-named document from the prior generation."""
    rec = {}
    out = tmp_path / "share"
    src = str(_collection(tmp_path))
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec))
    ing.run_redaction_folder(src, str(out))
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec, omit=("mop",)))
    report = ing.run_redaction_folder(src, str(out), reuse_out=True)
    gap = {m["key"]: m for m in report["missing"]}
    assert set(gap) == {"mop"} and gap["mop"]["state"] == "absent"
    assert not (out / "Assessment_redacted_mop.docx").exists()
    prior = Path(report["previous_set"])
    assert (prior / "Assessment_redacted_mop.docx").is_file()
    note = (out / "INCOMPLETE-SET.txt").read_text(encoding="ascii")
    assert "ABSENT" in note and "not written" in note


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


def test_a_prior_do_not_send_marker_is_archived_with_its_failed_generation(
        monkeypatch, tmp_path, capsys):
    """A clean receipt and an old failure marker must never coexist in the canonical folder."""
    rec = {}
    out = tmp_path / "share"
    src = str(_collection(tmp_path))
    monkeypatch.setattr(ing.subprocess, "run", _fake_engine(rec, snapshot=LEAKY_SNAP))
    with pytest.raises(ing.EngineRunError):
        ing.run_redaction_folder(src, str(out))
    assert (out / "DO-NOT-SEND-NOT-REDACTED.txt").is_file()
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec))
    rc = serve.main(["--redact-folder", src, "--out", str(out), "--reuse-out"])
    cap = capsys.readouterr().out
    assert rc == 0
    assert "DO-NOT-SEND-NOT-REDACTED.txt" not in cap
    assert not (out / ing.UNSAFE_MARKER).exists()
    backups = list(tmp_path.glob(".share.replaced-*"))
    assert len(backups) == 1 and (backups[0] / ing.UNSAFE_MARKER).is_file()


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


# --- empty-string flag values ---------------------------------------------------------------------
# argparse accepts `--flag ""`, and main() dispatched on truthiness, so an empty value was
# indistinguishable from "flag not passed". Measured before the fix: `--redact-folder ""` returned
# 0 and STARTED THE WEB SERVER. The engineer asked for a share-safe deliverable set, got a running
# cockpit and a success exit code, and nothing anywhere said the redaction had not happened.

def _no_serve(monkeypatch):
    """Stub the serve path so a regression is a FAILED ASSERT, not a test that binds a port and
    hangs. `served` flipping to True is the actual defect being detected — asserting only on the
    exit code would pass for a command that refused AND then somehow served."""
    state = {"served": False}
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(
        run=lambda app, **kw: state.update(served=True)))
    monkeypatch.setattr(serve, "_schedule_browser_open", lambda url: None)
    return state


def test_empty_redact_folder_refuses_instead_of_serving(monkeypatch, tmp_path, capsys):
    state = _no_serve(monkeypatch)
    assert serve.main(["--redact-folder", ""]) == 2
    assert state["served"] is False, "an empty --redact-folder started the server"
    assert "empty value" in capsys.readouterr().err
    # ...including when --out IS supplied, which previously produced the MISLEADING refusal
    # "--out only applies to --redact-folder" while --redact-folder was in fact supplied.
    assert serve.main(["--redact-folder", "", "--out", str(tmp_path / "o")]) == 2
    assert state["served"] is False
    assert "only apply" not in capsys.readouterr().err


def test_empty_out_refuses_instead_of_serving(monkeypatch, tmp_path, capsys):
    state = _no_serve(monkeypatch)
    assert serve.main(["--redact-folder", str(tmp_path), "--out", ""]) == 2
    assert state["served"] is False, "an empty --out started the server"
    assert "empty value" in capsys.readouterr().err
    # bare `--out ""` with no --redact-folder must still hit a refusal, not fall through to serving
    assert serve.main(["--out", ""]) == 2
    assert state["served"] is False


def test_every_path_valued_flag_rejects_an_empty_value(monkeypatch, capsys):
    """The whole class, not the three flags that happened to be reported. --db "" silently opened
    a DIFFERENT store than the one named; --dist "" served a different frontend (and disagreed
    with run_selftest, which already used `is not None` for it); --host "" binds every interface
    rather than loopback. Whitespace counts as empty - a quoted trailing space is invisible."""
    state = _no_serve(monkeypatch)
    for flag in ("--host", "--db", "--dist", "--redact-folder", "--out", "--verify-manifest",
                 "--expect-root"):
        for value in ("", "   "):
            assert serve.main([flag, value]) == 2, f"{flag} {value!r} was not refused"
            assert state["served"] is False, f"{flag} {value!r} reached the serve path"
            assert flag in capsys.readouterr().err


def test_the_guard_does_not_refuse_real_values(monkeypatch, tmp_path):
    """Non-vacuity: the guard must reject ONLY empty values. A blanket refusal would pass every
    assertion above while breaking the normal command."""
    state = _no_serve(monkeypatch)
    rc = serve.main(["--db", str(tmp_path / "a.db"), "--port", "8123", "--no-browser"])
    assert rc == 0 and state["served"] is True, "the guard swallowed a valid invocation"


def test_main_forwards_reuse_out_to_run_redaction(monkeypatch):
    """Direct pin on the dispatch contract, after a merge silently broke it.

    Two changes collided on these lines (#438's --reuse-out and the empty-value guard) and the
    conflict was resolved by keeping BOTH blocks stacked. `if args.redact_folder is not None`
    returns for every non-None value, so the second block was unreachable - and it was the only
    one that forwarded reuse_out. The flag was accepted, silently dropped, and Atlas refused an
    --out folder the engineer had explicitly authorised.

    #438's own tests did catch it, but only through their console assertions, which read as a
    message-wording problem. This asserts the argument itself reaches run_redaction, so the next
    re-stack fails with the actual cause on the line."""
    seen = {}
    monkeypatch.setattr(serve, "run_redaction",
                        lambda src, out, rc=False, ro=False: seen.update(
                            src=src, out=out, redact_collection=rc, reuse_out=ro) or 0)
    assert serve.main(["--redact-folder", "S", "--out", "O", "--reuse-out"]) == 0
    assert seen["reuse_out"] is True, "--reuse-out did not reach run_redaction"
    seen.clear()
    assert serve.main(["--redact-folder", "S", "--out", "O"]) == 0
    assert seen["reuse_out"] is False, "reuse_out must default off - it relaxes a safety refusal"


def test_reuse_out_without_redact_folder_is_refused(capsys):
    """The mirror: --reuse-out relaxes a safety refusal, so it must never be silently ignored
    when the command it modifies was not given."""
    assert serve.main(["--reuse-out"]) == 2
    assert "only apply to --redact-folder" in capsys.readouterr().err


def test_two_jobs_in_one_invocation_are_refused_not_silently_dropped(monkeypatch, tmp_path, capsys):
    """The three subcommands were dispatched by a fixed precedence with NO cross-check, so asking
    for two performed the first and discarded the rest in silence. Measured before the fix:
    `--verify-manifest X --redact-folder Y --out Z` printed "manifest OK" and returned 0 while the
    redaction - the ten-minute job producing the deliverables actually wanted - never ran. Same
    "asked for X, silently got Y, exit code says success" failure as the empty-value bug, reached
    by a different route."""
    state = _no_serve(monkeypatch)
    monkeypatch.setattr(ing, "run_redaction_folder",
                        lambda *a, **k: pytest.fail("redaction ran despite a competing job"))
    src = str(_collection(tmp_path))
    out = str(tmp_path / "o")
    for argv in (["--verify-manifest", "m.json", "--redact-folder", src, "--out", out],
                 ["--redact-folder", src, "--out", out, "--verify-manifest", "m.json"],
                 ["--selftest", "--redact-folder", src, "--out", out],
                 ["--selftest", "--verify-manifest", "m.json"]):
        assert serve.main(argv) == 2, argv
        assert state["served"] is False
        err = capsys.readouterr().err
        assert "one per run" in err, err


def test_invisible_and_control_characters_are_not_usable_values(monkeypatch, tmp_path, capsys):
    """`str.strip()` removes NBSP and the exotic spaces but NOT zero-width space or the BOM, so
    `--db "\u200b"` passed the empty-value guard and CREATED A REAL STORE named with an invisible
    character - exactly the "quietly opened a different store than the one you named" outcome that
    guard exists to stop. An embedded NUL instead raised ValueError from inside pathlib/sqlite3,
    escaping main() as a traceback after the job banner had printed."""
    state = _no_serve(monkeypatch)
    before = set(os.listdir(tmp_path))
    for value in ("\u200b", "\ufeff", "\u200b\u200c ", "\x00", "a\x00b", "\t"):
        for flag in ("--db", "--out", "--dist", "--host"):
            assert serve.main([flag, value]) == 2, (flag, repr(value))
            assert state["served"] is False, (flag, repr(value))
            capsys.readouterr()
    assert set(os.listdir(tmp_path)) == before, "a refused --db value still created a store"
    # a NUL reaching the redaction path used to crash inside ingest, after the banner
    src = str(_collection(tmp_path))
    capsys.readouterr()
    assert serve.main(["--redact-folder", src, "--out", "\x00"]) == 2
    assert "Traceback" not in capsys.readouterr().err


# ── the safety claim must be scoped to what THIS run wrote ──────────────────────
# Failed runs stay in private staging. A later successful generation archives the old warning and
# promotes only its own verified bytes, so an omitted document cannot be inherited by name.
def _leaky_then_clean(monkeypatch, tmp_path, omit=("mop",)):
    """Fail one staged run, then prove a short clean run cannot inherit its bytes."""
    src = str(_collection(tmp_path))
    out = tmp_path / "share"

    monkeypatch.setattr(ing.subprocess, "run", _family_engine({}, stderr=""))
    # Run 1 fails its scrub check: only the durable warning reaches the canonical folder.
    monkeypatch.setattr(ing, "_assert_scrubbed",
                        lambda p: (_ for _ in ()).throw(ing.EngineRunError("REDACTION DID NOT APPLY")))
    with pytest.raises(ing.EngineRunError):
        ing.run_redaction_folder(src, str(out))
    assert (out / ing.UNSAFE_MARKER).is_file(), "run 1 should have marked the folder unsafe"
    assert not (out / "Assessment_redacted_mop.docx").exists()

    # Run 2 passes its own checks but omits one document.
    monkeypatch.setattr(ing, "_assert_scrubbed", lambda p: 0)
    monkeypatch.setattr(ing.subprocess, "run", _family_engine({}, omit=omit))
    report = ing.run_redaction_folder(src, str(out), reuse_out=True)
    assert not (out / "Assessment_redacted_mop.docx").exists()
    assert (Path(report["previous_set"]) / ing.UNSAFE_MARKER).is_file()
    return report, out


def test_the_note_scopes_safety_to_the_promoted_current_generation(monkeypatch, tmp_path):
    """An archived failed run cannot contaminate the short current generation."""
    report, out = _leaky_then_clean(monkeypatch, tmp_path)
    assert [g["state"] for g in report["missing"]] == ["absent"]
    assert report["stale_unsafe_marker"] is False

    note = (out / report["incomplete_note"]).read_text(encoding="ascii")
    assert "What this run wrote IS redacted" in note
    assert "DO NOT SEND THIS FOLDER" not in note
    assert ing.UNSAFE_MARKER not in note


def test_the_note_still_says_what_is_safe_when_nothing_is_uncertified(monkeypatch, tmp_path):
    """The other edge: with no unsafe marker the note must still reassure, scoped to this run.
    A warning that fires on every short set is the false alarm that teaches people to ignore it."""
    src = str(_collection(tmp_path))
    out = tmp_path / "share"
    monkeypatch.setattr(ing.subprocess, "run", _family_engine({}, omit=("mop",)))
    report = ing.run_redaction_folder(src, str(out))

    note = (out / report["incomplete_note"]).read_text(encoding="ascii")
    assert report["stale_unsafe_marker"] is False
    assert "DO NOT SEND THIS FOLDER" not in note
    assert "What this run wrote IS redacted" in note


def test_archived_uncertified_generation_is_not_described_as_current(monkeypatch, tmp_path):
    """The canonical note must describe only the promoted current generation."""
    report, out = _leaky_then_clean(monkeypatch, tmp_path)
    note = (out / report["incomplete_note"]).read_text(encoding="ascii")
    assert "STALE" not in note and "EARLIER run" not in note
    assert "ABSENT" in note


def test_console_reports_only_the_promoted_short_generation(monkeypatch, tmp_path, capsys):
    src = str(_collection(tmp_path))
    out = tmp_path / "share"

    monkeypatch.setattr(ing.subprocess, "run", _family_engine({}))
    monkeypatch.setattr(ing, "_assert_scrubbed",
                        lambda p: (_ for _ in ()).throw(ing.EngineRunError("REDACTION DID NOT APPLY")))
    with pytest.raises(ing.EngineRunError):
        ing.run_redaction_folder(src, str(out))
    monkeypatch.setattr(ing, "_assert_scrubbed", lambda p: 0)
    monkeypatch.setattr(ing.subprocess, "run", _family_engine({}, omit=("mop",)))
    capsys.readouterr()

    rc = serve.main(["--redact-folder", src, "--out", str(out), "--reuse-out", "--no-browser"])
    text = capsys.readouterr().out
    assert rc == 3, "a short set still reports 3, not a redaction failure"
    assert "What THIS RUN wrote is independently verified" in text
    assert "DO NOT SEND THIS FOLDER" not in text
    assert "ABSENT" in text


def test_a_marker_only_failed_run_can_be_replaced_by_a_verified_generation(monkeypatch, tmp_path):
    """No failed deliverables are canonical, so a later verified run can archive the marker."""
    src = str(_collection(tmp_path))
    out = tmp_path / "share"
    monkeypatch.setattr(ing.subprocess, "run", _family_engine({}))
    monkeypatch.setattr(ing, "_assert_scrubbed",
                        lambda p: (_ for _ in ()).throw(ing.EngineRunError("REDACTION DID NOT APPLY")))
    with pytest.raises(ing.EngineRunError):
        ing.run_redaction_folder(src, str(out))

    monkeypatch.setattr(ing, "_assert_scrubbed", lambda p: 0)
    monkeypatch.setattr(ing.subprocess, "run", _family_engine({}))
    report = ing.run_redaction_folder(src, str(out))
    assert report["missing"] == []
    assert not (out / ing.UNSAFE_MARKER).exists()
    assert (Path(report["previous_set"]) / ing.UNSAFE_MARKER).is_file()


def test_the_unsafe_marker_name_has_one_owner():
    """It decides whether the report may claim safety, so a second literal would let the two drift
    into disagreeing about which file they mean (SSOT Law 1)."""
    import re as _re
    for mod in (ing, serve):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        literals = _re.findall(r'"DO-NOT-SEND-NOT-REDACTED\.txt"', src)
        assert len(literals) <= (1 if mod is ing else 0), (
            f"{Path(mod.__file__).name} restates the marker filename; use ingest.UNSAFE_MARKER")


# ── the raw-capture scrub must be reported from its OUTCOME, never from the flag ─
# `--redact-collection` is the control that takes the enable secrets, SNMP communities and PSKs
# off the stick. It is the one redaction step that is NOT a `_run_phase`: no ledger row, so
# `_REDACTION_PHASES` cannot see it, and its failure line matches neither `_ENGINE_GAP_RE` nor the
# `[SKIP] Phase` scrape. The engine's own log line is the only evidence there is.
def _scrub_engine(rec: dict, *, stdout="engine ok", stderr=""):
    """A successful engine run whose output carries whatever the Phase-40 scrub said about itself."""
    def run(cmd, cwd=None, **kw):
        rec["cmd"] = list(cmd)
        out = Path(cmd[cmd.index("--output") + 1])
        Path(str(out)[: -len(".xlsx")] + ".snapshot.json").write_text(
            json.dumps(REDACTED_SNAP), encoding="utf-8")
        out.write_bytes(_docbytes("xl/workbook.xml"))
        _positive_ledgers(out)
        return types.SimpleNamespace(returncode=0, stdout=stdout, stderr=stderr)
    return run


# The two shapes the engine really emits (COLLECT_PARSE_V3_23_0.py:3273-3278). One capture file
# exists in the fixture collection, so "1 of 1" is full coverage and "0 of 0" is none.
_SCRUB_OK = ("INFO - [OK] redact-collection: scrubbed secret values in 1 of 1 raw capture file(s) "
             "under C:\\job\\fleet (in place, idempotent; IPs/hostnames kept)")
_SCRUB_FAILED = ("WARNING -   redact-collection failed (non-fatal; raw dir unchanged): "
                 "PermissionError(13, 'Access is denied')")
_SCRUB_NONE_READ = ("INFO - [OK] redact-collection: scrubbed secret values in 0 of 0 raw capture "
                    "file(s) under C:\\job\\fleet (in place, idempotent; IPs/hostnames kept)")


@pytest.mark.parametrize("engine_says, verified", [
    (_SCRUB_OK, True),
    (_SCRUB_FAILED, False),
    ("", False),
    (_SCRUB_NONE_READ, False),
])
def test_the_scrub_is_reported_from_what_happened_not_from_the_flag(
        monkeypatch, tmp_path, engine_says, verified):
    """`redacted_collection` used to be `bool(redact_collection)` — the argument echoed back. It
    was therefore True for a run whose scrub raised, and for one that never reached the phase at
    all: exit 0 told a field engineer the secrets were gone from the captures on the stick.

    The last case is the quietest one and the reason the counts are compared rather than trusted:
    `redact_collection_dir` skips a capture it cannot open and carries on, so it reports success
    over a folder it never read."""
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _scrub_engine(rec, stderr=engine_says))
    if not verified:
        with pytest.raises(ing.EngineRunError, match="SCRUB COULD NOT BE VERIFIED"):
            ing.run_redaction_folder(
                str(_collection(tmp_path)), str(tmp_path / "out"),
                redact_collection=True,
            )
        return
    report = ing.run_redaction_folder(
        str(_collection(tmp_path)), str(tmp_path / "out"), redact_collection=True
    )
    assert report["redacted_collection_requested"] is True, "the flag did travel"
    assert report["redacted_collection"] is True
    assert "independently verified 1 raw capture" in report["redacted_collection_detail"]


def test_the_scrub_verdict_survives_a_long_run(monkeypatch, tmp_path):
    """Phase 40 is followed by the perf sidecar and the closing banner, so its line is routinely
    pushed out of the 12-line tail. Read the FULL output or the verdict silently becomes
    'could not verify' on every real run — a check that always fires is one nobody reads."""
    rec = {}
    noise = "\n".join(f"INFO - [OK] phase {i} done" for i in range(40))
    monkeypatch.setattr(ing.subprocess, "run",
                        _scrub_engine(rec, stderr=_SCRUB_OK + "\n" + noise))
    report = ing.run_redaction_folder(str(_collection(tmp_path)), str(tmp_path / "out"),
                                      redact_collection=True)
    assert report["redacted_collection"] is True
    assert _SCRUB_OK not in report["engine_log_tail"], "precondition: the line IS out of the tail"


def test_the_scrub_verdict_does_not_leak_the_collection_path(monkeypatch, tmp_path):
    """The engine's own line names the collection directory. The detail string is reported, so it
    carries counts extracted from that line, never the line itself (WEBAP-01)."""
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _scrub_engine(rec, stderr=_SCRUB_OK))
    report = ing.run_redaction_folder(str(_collection(tmp_path)), str(tmp_path / "out"),
                                      redact_collection=True)
    assert "C:\\job\\fleet" not in report["redacted_collection_detail"]


def test_no_scrub_verdict_is_invented_when_it_was_not_asked_for(monkeypatch, tmp_path):
    """"Not requested" is not an outcome, and must not read as a failed one."""
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _scrub_engine(rec))
    report = ing.run_redaction_folder(str(_collection(tmp_path)), str(tmp_path / "out"))
    assert report["redacted_collection_requested"] is False
    assert report["redacted_collection"] is False
    assert report["redacted_collection_detail"] == ""


# ── a certification must be over THIS run's evidence ────────────────────────────
def test_an_earlier_runs_snapshot_does_not_certify_this_one(monkeypatch, tmp_path):
    """`--reuse-out` renders into a folder that already holds a set, so the previous job's
    `.snapshot.json` sits under this run's name. The guard tested only `is_file()`, so a run whose
    engine wrote no snapshot at all was verified against the EARLIER run's clean one and reported
    as a certified, share-safe set."""
    out = tmp_path / "share"
    out.mkdir()
    (out / "Assessment_redacted.snapshot.json").write_text(json.dumps(REDACTED_SNAP),
                                                           encoding="utf-8")

    def engine_writes_no_snapshot(cmd, cwd=None, **kw):
        Path(cmd[cmd.index("--output") + 1]).write_bytes(_docbytes("xl/workbook.xml"))
        return types.SimpleNamespace(returncode=0, stdout="engine ok", stderr="")

    monkeypatch.setattr(ing.subprocess, "run", engine_writes_no_snapshot)
    with pytest.raises(ing.EngineRunError) as e:
        ing.run_redaction_folder(str(_collection(tmp_path)), str(out), reuse_out=True)
    assert "wrote no snapshot" in str(e.value)
    assert (out / ing.UNSAFE_MARKER).is_file()


def test_an_earlier_runs_phase_ledger_is_not_this_runs_evidence(monkeypatch, tmp_path):
    """Same shape one level down, and the quieter half of it. This run leaves NO ledger and says
    nothing on stderr — so the only thing standing between it and a share-safe verdict is the
    `ok: true` ledger the previous job left in the folder. Reading that one certifies the previous
    job. Private staging makes the prior ledger invisible; absence itself now fails closed."""
    out = tmp_path / "share"
    out.mkdir()
    (out / "Assessment_redacted.phase_timings.json").write_text(json.dumps(
        {"phases": [{"phase": p, "seconds": 0.1, "ok": True} for p in ing._REDACTION_PHASES]}),
        encoding="utf-8")

    def engine_writes_no_ledger(cmd, cwd=None, **kw):
        out_x = Path(cmd[cmd.index("--output") + 1])
        Path(str(out_x)[: -len(".xlsx")] + ".snapshot.json").write_text(
            json.dumps(REDACTED_SNAP), encoding="utf-8")
        out_x.write_bytes(_docbytes("xl/workbook.xml"))
        return types.SimpleNamespace(returncode=0, stdout="engine ok", stderr="")

    monkeypatch.setattr(ing.subprocess, "run", engine_writes_no_ledger)
    with pytest.raises(ing.EngineRunError) as e:
        ing.run_redaction_folder(str(_collection(tmp_path)), str(out), reuse_out=True)
    assert "COULD NOT BE VERIFIED" in str(e.value) and "ledger is absent" in str(e.value)
    assert (out / ing.UNSAFE_MARKER).is_file()


def test_an_absent_phase_ledger_fails_closed(monkeypatch, tmp_path):
    """Exit zero and quiet stderr cannot replace a positive mandatory-phase ledger."""
    positive = _fake_engine({})

    def without_ledgers(cmd, cwd=None, **kw):
        result = positive(cmd, cwd=cwd, **kw)
        out_x = Path(cmd[cmd.index("--output") + 1])
        stem = str(out_x)[: -len(".xlsx")]
        Path(stem + ".phase_timings.json").unlink()
        Path(stem + ".run_manifest.json").unlink()
        return result

    monkeypatch.setattr(ing.subprocess, "run", without_ledgers)
    with pytest.raises(ing.EngineRunError, match="mandatory phase ledger is absent"):
        ing.run_redaction_folder(str(_collection(tmp_path)), str(tmp_path / "out"))


def test_a_ledger_this_run_did_write_is_still_read(monkeypatch, tmp_path):
    """Non-vacuity: the attribution check must not disable the ledger arm on a normal re-run."""
    out = tmp_path / "share"
    out.mkdir()
    (out / "Assessment_redacted.phase_timings.json").write_text("{}", encoding="utf-8")
    os.utime(out / "Assessment_redacted.phase_timings.json", (0, 0))
    phase = ing._REDACTION_PHASES[1]

    def engine_writes_a_failed_ledger(cmd, cwd=None, **kw):
        out_x = Path(cmd[cmd.index("--output") + 1])
        stem = str(out_x)[: -len(".xlsx")]
        Path(stem + ".snapshot.json").write_text(json.dumps(REDACTED_SNAP), encoding="utf-8")
        Path(stem + ".phase_timings.json").write_text(json.dumps(
            {"phases": [{"phase": p, "seconds": 0.1, "ok": p != phase}
                        for p in ing._REDACTION_PHASES]}), encoding="utf-8")
        out_x.write_bytes(_docbytes("xl/workbook.xml"))
        return types.SimpleNamespace(returncode=0, stdout="engine ok", stderr="")

    monkeypatch.setattr(ing.subprocess, "run", engine_writes_a_failed_ledger)
    with pytest.raises(ing.EngineRunError, match="REDACTION PHASE FAILED"):
        ing.run_redaction_folder(str(_collection(tmp_path)), str(out), reuse_out=True)


# ── every failure exit leaves the on-disk warning, not just the redaction check ──
def _boom(kind):
    """An engine that leaves half a *_redacted* set behind and then fails in one of three ways."""
    def run(cmd, cwd=None, **kw):
        out_x = Path(cmd[cmd.index("--output") + 1])
        out_x.write_bytes(_docbytes("xl/workbook.xml"))                # partial deliverable
        (out_x.parent / "Assessment_redacted_design.docx").write_bytes(b"docx")
        if kind == "timeout":
            raise ing.subprocess.TimeoutExpired(cmd, ing.REDACT_TIMEOUT_S)
        if kind == "exit":
            return types.SimpleNamespace(returncode=2, stdout="", stderr="engine died")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")   # no snapshot written
    return run


@pytest.mark.parametrize("kind", ["timeout", "exit", "no_snapshot"])
def test_every_failure_exit_leaves_the_do_not_send_marker(monkeypatch, tmp_path, kind):
    """Only the redaction-check failure wrote the marker. The other three exits leave the same
    half-written `*_redacted*` files — names that ASSERT the property the run never certified —
    with nothing on disk saying so, and stderr scrolls away."""
    monkeypatch.setattr(ing.subprocess, "run", _boom(kind))
    out = tmp_path / "share"
    with pytest.raises(ing.EngineRunError):
        ing.run_redaction_folder(str(_collection(tmp_path)), str(out))
    assert not (out / "Assessment_redacted.xlsx").exists(), (
        "an uncertified staged generation must never reach the canonical output"
    )
    marker = out / ing.UNSAFE_MARKER
    assert marker.is_file(), f"{kind} exit left *_redacted* files with no warning"
    assert "NOT safe to share" in marker.read_text(encoding="ascii")


# ── the reuse refusal covers everything an engine run writes, not just documents ─
@pytest.mark.parametrize("leftover", ["Assessment_redacted.snapshot.json",
                                      "Assessment_redacted.run_manifest.json",
                                      "Assessment_redacted.phase_timings.json"])
def test_reuse_refusal_covers_the_engines_own_sidecars(monkeypatch, tmp_path, leftover):
    """The refusal checked `cli_artifacts` only — the ten documents. The snapshot is the fullest
    record of another engagement there is (the whole assessment, hostnames kept by design), and
    nothing else notices it: it is not a family document, so `_family_state` never names it, and a
    run that does not rewrite it does not list it in `files` either. It just travels."""
    out = tmp_path / "share"
    out.mkdir()
    (out / leftover).write_text('{"devices": {"other-client-core1": {}}}', encoding="utf-8")
    monkeypatch.setattr(ing.subprocess, "run", _family_engine({}))
    with pytest.raises(ing.IngestError) as e:
        ing.run_redaction_folder(str(_collection(tmp_path)), str(out))
    assert leftover in str(e.value) and "--reuse-out" in str(e.value)


def test_an_unrelated_json_beside_the_set_is_not_a_reason_to_refuse(monkeypatch, tmp_path):
    """Calibration: only names the ENGINE owns count. Refusing over the engineer's own files
    would make the escape hatch the habit, which is the opposite of the point."""
    out = tmp_path / "share"
    out.mkdir()
    (out / "my-notes.json").write_text("{}", encoding="utf-8")
    (out / "Assessment_redacted.snapshot.json.bak").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(ing.subprocess, "run", _family_engine({}))
    ing.run_redaction_folder(str(_collection(tmp_path)), str(out))      # must not raise


# ── the engine log tail must not disclose the caller's filesystem ───────────────
@pytest.mark.parametrize("channel", ["redact", "ingest"])
def test_the_log_tail_does_not_disclose_the_callers_path(monkeypatch, tmp_path, channel):
    """The tail reaches a (possibly remote, unauthenticated) uploader through the API 500 detail
    and the success report, and travels in the folder the engineer sends. It scrubbed only the
    private workdir — but the engine is pointed at `--collection-dir`, which is the CALLER's
    absolute path, so one breadcrumb naming it disclosed the server's layout and the engagement's
    own folder name."""
    src = tmp_path / "Acme-Bank-Merger" / "fleet"
    (src / "core1").mkdir(parents=True)
    (src / "core1" / "show_version.txt").write_text("Cisco IOS XE Software", encoding="utf-8")

    def chatty(cmd, cwd=None, **kw):
        root = cmd[cmd.index("--collection-dir") + 1]
        out_x = Path(cmd[cmd.index("--output") + 1])
        Path(str(out_x)[: -len(".xlsx")] + ".snapshot.json").write_text(
            json.dumps(REDACTED_SNAP), encoding="utf-8")
        out_x.write_bytes(_docbytes("xl/workbook.xml"))
        _positive_ledgers(out_x)
        return types.SimpleNamespace(returncode=0, stdout=f"INFO - reading {root}", stderr="")

    monkeypatch.setattr(ing.subprocess, "run", chatty)
    if channel == "redact":
        tail = ing.run_redaction_folder(str(src), str(tmp_path / "out"))["engine_log_tail"]
    else:
        tail = ing.run_collection_folder(str(src))[1]["engine_log_tail"]
    assert "Acme-Bank-Merger" not in tail, tail
    assert str(src) not in tail and "<workdir>" in tail


# ── hostile archive: a name can be a DEVICE, not a file ─────────────────────────
def _zip_of(*names: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("core1/show_version.txt", "Cisco IOS XE Software")
        for n in names:
            zf.writestr(n, "enable secret 5 $1$abc$realsecret\n" * 40)
    return buf.getvalue()


@pytest.mark.parametrize("name", ["core1/NUL", "core1/nul.txt", "core1/COM1", "core1/PRN",
                                  "NUL/show_version.txt", "core1/show_run.txt.",
                                  "core1/show_run.txt "])
def test_reserved_device_names_and_trailing_dots_are_refused(tmp_path, name):
    """`_safe_extract` validated traversal but not what the name IS on this platform. `core1/NUL`
    resolves inside `dest` and passes the containment check, then `open()` succeeds and writes to
    the NULL DEVICE: the bytes vanish, no error is raised, and the entry was counted as a captured
    file. `COM1`-`COM9` send the archive's bytes out a serial port. A trailing dot or space is
    stripped by Windows, so the entry lands on top of a different capture of that name."""
    dest = tmp_path / "extracted"
    dest.mkdir()
    with pytest.raises(ing.IngestError) as e:
        ing._safe_extract(_zip_of(name), dest)
    assert "refused" in str(e.value)
    assert not (dest / "core1" / "show_run.txt").exists(), "nothing may land under the stripped name"


@pytest.mark.parametrize("name", ["../evil.txt", "core1/../../evil.txt"])
def test_traversal_still_reports_traversal(tmp_path, name):
    """The name guard must not steal the diagnosis from the containment check. `..` has a trailing
    dot, so an unguarded trailing-dot rule fires first and refuses the entry for the wrong reason —
    still a refusal, but the API contract and the operator both read 'traversal' here."""
    dest = tmp_path / "extracted"
    dest.mkdir()
    with pytest.raises(ing.IngestError, match="traversal"):
        ing._safe_extract(_zip_of(name), dest)


def test_ordinary_capture_names_still_extract(tmp_path):
    """Calibration: the guard must not fire on the names a real collection actually uses —
    including ones that merely CONTAIN a reserved word."""
    dest = tmp_path / "extracted"
    dest.mkdir()
    n = ing._safe_extract(_zip_of("core1/show_console.txt", "aux-sw1/show_version.txt",
                                  "core1/show_run.auxiliary.txt"), dest)
    assert n == 4
    assert (dest / "aux-sw1" / "show_version.txt").is_file()


def test_case_aliases_are_refused_before_any_file_lands(tmp_path):
    """Cross-platform aliases are order-dependent overwrites, so they are rejected in preflight."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("core1/SHOW_VERSION.TXT", "Cisco IOS XE Software")
        zf.writestr("core1/show_version.txt", "Cisco IOS XE Software, different capture")
    dest = tmp_path / "extracted"
    dest.mkdir()
    with pytest.raises(ing.IngestError, match="duplicate aliases"):
        ing._safe_extract(buf.getvalue(), dest)
    assert not list(dest.rglob("*"))


def test_a_rewrite_inside_one_coarse_mtime_tick_is_not_reported_stale(monkeypatch, tmp_path):
    """Re-running the same collection into the same folder rewrites every document with the SAME
    bytes. `_written_by_this_run` decided "did this run write it?" by comparing (mtime, size)
    inequality against a pre-run stat, and an identical rewrite moves neither — measured directly
    on this platform, an immediate same-size rewrite shifts st_mtime by 0.0. The document WAS
    rewritten and the check said it was not, so it was reported

        stale - "left by an EARLIER run into this folder ... check which job it belongs to"

    i.e. a freshly-redacted set told the engineer it might belong to ANOTHER CLIENT. A false
    cross-job alarm on good output is the failure `_written_by_this_run`'s own docstring says this
    codebase already paid for once, and it is how a real alarm gets trained away.

    The tick is SIMULATED rather than raced: the engine wrapper stamps a fixed mtime after writing,
    so the collision happens every run instead of only when the machine is fast enough. Racing it
    produced a test that passed with the fix reverted — i.e. pinned nothing.
    """
    _TICK = 1_700_000_000.0          # one fixed "coarse tick" both runs land in

    def _engine_in_one_tick(**kw):
        inner = _family_engine({}, **kw)

        def run(cmd, cwd=None, **kwargs):
            out_dir = Path(cmd[cmd.index("--output") + 1]).parent
            before = {f.name: (f.stat().st_mtime, f.stat().st_size)
                      for f in out_dir.iterdir() if f.is_file()}
            res = inner(cmd, cwd=cwd, **kwargs)
            # Stamp ONLY what the engine actually wrote — a file it skipped must keep the mtime it
            # had, or the harness would fake a write and the omit case below could not fail.
            for f in out_dir.iterdir():
                if not f.is_file():
                    continue
                st = f.stat()
                if before.get(f.name) != (st.st_mtime, st.st_size):
                    os.utime(f, (_TICK, _TICK))          # the FS hands both runs the same stamp
            return res
        return run

    src = str(_collection(tmp_path))
    out = tmp_path / "share"
    monkeypatch.setattr(ing, "_assert_scrubbed", lambda p: 0)

    monkeypatch.setattr(ing.subprocess, "run", _engine_in_one_tick())
    first = ing.run_redaction_folder(src, str(out))
    assert first["missing"] == [], f"run 1 should deliver the whole family, got {first['missing']}"

    monkeypatch.setattr(ing.subprocess, "run", _engine_in_one_tick())
    second = ing.run_redaction_folder(src, str(out), reuse_out=True)
    assert second["missing"] == [], (
        "a rewritten document was reported as another job's leftover: "
        + repr([(g["state"], g["file"]) for g in second["missing"]]))

    # A genuinely omitted document is absent from the new coherent generation; the prior copy is
    # archived outside the canonical folder.
    monkeypatch.setattr(ing.subprocess, "run", _engine_in_one_tick(omit=("mop",)))
    third = ing.run_redaction_folder(src, str(out), reuse_out=True)
    assert [g["state"] for g in third["missing"]] == ["absent"], \
        f"a genuinely omitted document must be absent, got {third['missing']}"
    assert not (out / "Assessment_redacted_mop.docx").exists()
    assert (Path(third["previous_set"]) / "Assessment_redacted_mop.docx").is_file()


# ── W1/F1+F2: existence is not delivery, and .txt is not the capture class ──────
def _openable_zip_that_is_not_an_office_package():
    """A real, openable ZIP with a document part but NO ``[Content_Types].xml``.

    Deliberately the shape that the byte-scanning redaction verifier accepts (it is a readable
    container, so nothing upstream refuses the run) while Word/Excel cannot open it. That is the
    only way to reach the completeness check with a structurally invalid family document."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", "<document/>")
    return buf.getvalue()


def test_a_truncated_explorer_is_not_certified_as_a_delivered_document(monkeypatch, tmp_path):
    """The zip-only structural check certified the ONE family member that is not a zip.

    `_unusable` proved "existence is not delivery" for exactly two shapes: size == 0, and a zip
    whose central directory will not open. Every member of `docmeta.CLI_ARTIFACT_SUFFIX` is a zip
    EXCEPT `_explorer.html`, and for that one the only test was size > 0. Measured on the pre-fix
    code: a 36-byte truncated HTML document gave `missing == []`, no INCOMPLETE-SET.txt and exit 0
    — the repo contract for "complete + verified, safe to send" — while `docmeta.validate_artifact`,
    which the ENGINE already applies to the same bytes, returned
    `(False, 'HTML document is missing its root/open or closing tag')`."""
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(
        rec, corrupt={"explorer": b"<!doctype html><html><body>truncated"}))
    out = tmp_path / "share"
    report = ing.run_redaction_folder(str(_collection(tmp_path)), str(out))
    explorer = out / "Assessment_redacted_explorer.html"
    assert explorer.is_file() and explorer.stat().st_size > 0, \
        "precondition: it IS on disk and non-empty"
    gap = {m["key"]: m for m in report["missing"]}
    assert set(gap) == {"explorer"}, gap
    assert gap["explorer"]["state"] == "unusable"
    assert "root/open or closing tag" in gap["explorer"]["detail"]
    assert (out / "INCOMPLETE-SET.txt").is_file()


def test_the_completeness_check_covers_every_family_suffix_not_a_listed_two(monkeypatch, tmp_path):
    """Non-vacuity anchor for the check above AND the shape-fix assertion.

    The healthy family must acquire NO new disclosure (or the guard is always-on and proves
    nothing), and the check must be derived from the family rather than from a suffix list — so
    every suffix `docmeta.CLI_ARTIFACT_SUFFIX` names is exercised, not just the zips."""
    from cisco_toolkit.docmeta import CLI_ARTIFACT_SUFFIX

    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec))
    out = tmp_path / "share"
    report = ing.run_redaction_folder(str(_collection(tmp_path)), str(out))
    assert report["missing"] == [], report["missing"]
    assert not (out / "INCOMPLETE-SET.txt").exists()
    suffixes = {Path(s).suffix for s in CLI_ARTIFACT_SUFFIX.values()}
    assert suffixes - {".xlsx", ".docx", ".pptx"}, \
        "precondition: the family is not all-zip, so a zip-only check would have a blind spot"
    for name in report["files"]:
        if Path(name).suffix in suffixes:
            assert ing._unusable(out / name) == "", name


def test_an_openable_zip_that_word_cannot_open_is_reported_without_the_output_path(
        monkeypatch, tmp_path):
    """Second half of the routing fix, and the disclosure hygiene that comes with it.

    The old check asked only "does the central directory read back", which this file passes; the
    engine's own custody gate asks whether the required OOXML parts are there, which it fails. And
    because `validate_artifact` embeds the failing exception, the reason can carry the ABSOLUTE
    path — the WEBAP-01 disclosure — into a note that travels to the client inside the zipped
    folder, so the path is scrubbed before it is quoted."""
    rec = {}
    out = tmp_path / "Acme-Bank-Merger-share"
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(
        rec, corrupt={"opshandbook": _openable_zip_that_is_not_an_office_package()}))
    report = ing.run_redaction_folder(str(_collection(tmp_path)), str(out))
    gap = {m["key"]: m for m in report["missing"]}
    assert set(gap) == {"opshandbook"}, gap
    assert gap["opshandbook"]["state"] == "unusable"
    assert "Content_Types" in gap["opshandbook"]["detail"], gap["opshandbook"]["detail"]
    detail = " ".join(m["detail"] for m in report["missing"])
    assert "Acme-Bank-Merger" not in detail and str(out) not in detail, detail


def test_a_path_bearing_validator_reason_is_scrubbed_before_it_is_quoted(monkeypatch, tmp_path):
    """Unit-level guard for the same disclosure: `validate_artifact` interpolates the raw
    exception, so an OSError raised while reading a container member arrives carrying the absolute
    path. Forced here because that error is not reachable from a fixture, but the sanitizer it
    exercises is the one every branch above depends on."""
    from cisco_toolkit import docmeta

    doc = tmp_path / "Acme-Bank-Merger-share" / "Assessment_redacted_crd.docx"
    doc.parent.mkdir(parents=True)
    doc.write_bytes(b"x" * 64)
    monkeypatch.setattr(
        docmeta, "validate_artifact",
        lambda p, kind=None: (False, f"invalid Office package: [Errno 5] I/O error: '{p}'"))
    why = ing._unusable(doc)
    assert why and "Acme-Bank-Merger" not in why, why
    assert doc.name in why, why           # the FILE may be named; the folder that identifies the
    # ...and a reason that names only the CONTAINING folder loses it too. engagement may not.
    monkeypatch.setattr(
        docmeta, "validate_artifact",
        lambda p, kind=None: (False, f"invalid Office package: cannot read {doc.parent}"))
    why = ing._unusable(doc)
    assert "Acme-Bank-Merger" not in why and "<out>" in why, why


def test_the_engines_own_reason_survives_a_run_whose_family_is_complete(monkeypatch, tmp_path):
    """`gap_lines if missing else []` discarded the engine's [GATE REFUSED] / write-failed / [SKIP]
    lines whenever the produced-vs-expected diff came back clean — i.e. exactly in the case that
    looks healthy, which is the one case where the reader has nothing else to go on. A writer that
    failed and was retried, or a gate that refused a document already sitting in the folder, both
    reach here with a full family and a loud engine."""
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(
        rec, stderr="ERROR - [GATE REFUSED] design: missing upstream approval(s): assessment\n"
                    "INFO - [OK] Snapshot: written"))
    report = ing.run_redaction_folder(str(_collection(tmp_path)), str(tmp_path / "share"))
    assert report["missing"] == [], "precondition: the family IS complete"
    assert any("GATE REFUSED" in w for w in report["engine_warnings"]), report["engine_warnings"]
    # Non-vacuity: only lines that EXPLAIN a gap qualify, and a complete run whose engine said
    # nothing still reports none (pinned by test_a_complete_run_reports_nothing_missing above).
    assert not any("[OK] Snapshot" in w for w in report["engine_warnings"])


def test_the_capture_census_counts_the_class_the_scrub_owns(monkeypatch, tmp_path):
    """`_count_txt_captures` was the third copy of `endswith(".txt")`, and it is the DENOMINATOR
    the engine's "scrubbed N of M" is checked against. With a `backup-config.cfg` beside the
    `show_version.txt`, the engine's honest "1 of 1" used to satisfy a census of 1 and the run
    exited 0 with the .cfg untouched; the census now sees 2 and the shortfall is refused."""
    src = _collection(tmp_path)
    (src / "core1" / "backup-config.cfg").write_text(
        "snmp-server community S3cr3tRW RW\n", encoding="utf-8")
    assert ing._count_raw_captures(src) == 2, "precondition: both files are captures"
    monkeypatch.setattr(ing.subprocess, "run", _scrub_engine({}, stderr=_SCRUB_OK))
    with pytest.raises(ing.EngineRunError, match="SCRUB COULD NOT BE VERIFIED"):
        ing.run_redaction_folder(str(src), str(tmp_path / "out"), redact_collection=True)


def test_a_scrub_that_really_covered_the_class_is_still_reported_verified(monkeypatch, tmp_path):
    """Non-vacuity for the census test: the guard must not simply always fire. Two captures, an
    engine that says it read both, no residue -> verified, over the count that was proven."""
    src = _collection(tmp_path)
    (src / "core1" / "backup-config.cfg").write_text(
        "snmp-server community <redacted> RW\n", encoding="utf-8")
    engine_says = _SCRUB_OK.replace("in 1 of 1 raw capture", "in 1 of 2 raw capture")
    monkeypatch.setattr(ing.subprocess, "run", _scrub_engine({}, stderr=engine_says))
    report = ing.run_redaction_folder(str(src), str(tmp_path / "out"), redact_collection=True)
    assert report["redacted_collection"] is True
    assert "independently verified 2 raw capture" in report["redacted_collection_detail"]
    assert "NOT COVERED" not in report["redacted_collection_detail"]


def test_files_the_capture_grammar_cannot_read_are_disclosed_not_dropped(monkeypatch, tmp_path):
    """"Verified N raw captures" over a folder that also holds files nobody looked at is the
    dark-device shape: a number that means NOT MEASURED reading as nothing wrong."""
    src = _collection(tmp_path)
    (src / "core1" / "_capture_meta.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(ing.subprocess, "run", _scrub_engine({}, stderr=_SCRUB_OK))
    report = ing.run_redaction_folder(str(src), str(tmp_path / "out"), redact_collection=True)
    detail = report["redacted_collection_detail"]
    assert "NOT COVERED" in detail and "_capture_meta.json" in detail, detail
    assert "NOT a statement" in detail


def test_the_scrubbed_bytes_are_copied_back_for_every_capture_not_only_txt(monkeypatch, tmp_path):
    """The scrub happens in the PRIVATE staging tree; copy-back is what reaches the engineer's own
    folder. `rglob("*.txt")` there was a fourth copy of the extension test, and it alone would have
    made the whole fix cosmetic — verified clean in staging, cleartext on the laptop."""
    src = _collection(tmp_path)
    cfg = src / "core1" / "backup-config.cfg"
    cfg.write_text("snmp-server community S3cr3tRW RW\n", encoding="utf-8")
    engine_says = _SCRUB_OK.replace("in 1 of 1 raw capture", "in 1 of 2 raw capture")

    def scrubbing_engine(cmd, cwd=None, **kw):
        # Stand in for Phase 40: the engine scrubs the collection dir it was pointed at.
        from cisco_toolkit.html import redact_collection_dir
        redact_collection_dir(cmd[cmd.index("--collection-dir") + 1])
        return _scrub_engine({}, stderr=engine_says)(cmd, cwd=cwd, **kw)

    monkeypatch.setattr(ing.subprocess, "run", scrubbing_engine)
    report = ing.run_redaction_folder(str(src), str(tmp_path / "out"), redact_collection=True)
    assert report["redacted_collection"] is True
    body = cfg.read_text(encoding="utf-8")
    assert "S3cr3tRW" not in body, \
        "the scrubbed .cfg was never written back to the engineer's own folder"
    assert "<redacted>" in body


# ── R8/F5: `engine_warnings` was a control in name only ────────────────────────
def test_the_engines_warnings_reach_the_console_on_a_COMPLETE_run(monkeypatch, tmp_path, capsys):
    """`ingest.run_redaction_folder` keeps the engine's warning lines even when the family came out
    complete, on purpose — "a run can emit them while still producing every family document ...
    discarding them whenever the diff came back clean threw away the evidence precisely in the case
    that looks healthy". `serve.run_redaction` then printed them ONLY inside the INCOMPLETE branch,
    after `if not missing: return 0`. So in exactly the case ingest kept them for, nothing reached
    the engineer and the key was inert.

    Measured pre-fix on this input: rc 0, "Wrote N file(s)", and the engine's own [GATE REFUSED]
    line printed nowhere."""
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(
        rec, stderr="ERROR - [GATE REFUSED] design: missing upstream approval(s): assessment"))
    rc = serve.main(["--redact-folder", str(_collection(tmp_path)), "--out", str(tmp_path / "o")])
    cap = capsys.readouterr().out
    assert rc == 0, cap                                  # the family IS complete — this is the case
    assert "INCOMPLETE SET" not in cap
    assert "GATE REFUSED" in cap, f"the engine's own warning reached no one:\n{cap}"
    assert "engine reported 1 warning(s)" in cap, cap


def test_a_clean_run_invents_no_engine_warning_block(monkeypatch, tmp_path, capsys):
    """NON-VACUITY: an engine that warned about nothing must produce no warning block at all, or
    the banner is always-on and stops carrying information."""
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(rec))
    rc = serve.main(["--redact-folder", str(_collection(tmp_path)), "--out", str(tmp_path / "o")])
    cap = capsys.readouterr().out
    assert rc == 0
    assert "warning(s) during this run" not in cap, cap
    assert "engine:" not in cap, cap


def test_an_incomplete_run_still_prints_the_engines_warnings(monkeypatch, tmp_path, capsys):
    """The branch that DID print them must keep printing them — moving the block earlier must not
    trade one silent path for another."""
    rec = {}
    monkeypatch.setattr(ing.subprocess, "run", _family_engine(
        rec, omit=("runbook",),
        stderr="WARNING -   Runbook (DOCX) skipped: python-docx not installed"))
    rc = serve.main(["--redact-folder", str(_collection(tmp_path)), "--out", str(tmp_path / "o")])
    cap = capsys.readouterr().out
    assert rc == 3 and "INCOMPLETE SET" in cap
    assert "python-docx not installed" in cap, cap


# ── R9/F1: the THIRD matcher — the ingest census and the copy-back selector ─────
def test_the_ingest_census_counts_exactly_what_the_producer_scrubs(tmp_path):
    """``ingest._is_raw_capture`` is the third statement of the raw-capture rule, and the number it
    produces is compared against the producer's own count in ``_collection_scrub_outcome``
    (``scanned < present`` ⇒ "INCOMPLETE - captures were left untouched", which refuses the whole
    delivery). It delegates the NAME half to ``redaction_verify.is_uncoverable_capture`` — but that
    only removes the drift if the PRODUCER states the same rule too.

    Measured pre-fix, with ``os.path.splitext`` on the producer side: this tree gave census 5 and
    producer ``scanned`` 12 — the census and the scrub disagreed about 7 physical files, in the
    direction that hides it (the extra file was rewritten in the private staging tree, never copied
    back, and never named in the shortfall). Anything but equality here means the two are counting
    different sets.

    A real tree and the REAL producer, not a hand-shaped expectation: the census is asserted equal
    to what ``redact_collection_dir`` actually scanned, and the set the two are supposed to be
    counting is read back out of the OWNER of the name rule
    (``redaction_verify.is_uncoverable_capture``). That matters for the leading-dot class planted
    below: ``PurePath("..json").suffix`` reads it as a structured document through 3.13 and as a
    capture from 3.14, so a hand-built expected list would encode an interpreter. The equality the
    delivery gate depends on — census == producer == the owner rule's own answer — holds on
    either."""
    from cisco_toolkit import html as _html
    from cisco_toolkit.html import redact_collection_dir
    from backend import redaction_verify

    root = tmp_path / "collection" / "CORE-1"
    root.mkdir(parents=True)
    structured = sorted(set(redaction_verify._STRUCTURED_CAPTURE_SUFFIXES)
                        | {redaction_verify._SCRUB_TEMP_SUFFIX})
    # the class the two primitives read differently: a leading run of two dots
    planted = []
    for suffix in structured:
        for name in (f"dump{suffix}", f"..{suffix.lstrip('.')}"):
            (root / name).write_text('{"k": "v"}', encoding="utf-8")
            planted.append(name)
    (root / "blob.bin").write_bytes(b"\x00\x01\x02")
    # ...plus the BARE dotfile whose whole name is an excluded suffix: no extension, so a capture
    # on every interpreter — and the case the `str.endswith` restatement of this rule got wrong.
    captures = ["show_run.cfg", "show_tech-support.log", "running-config", ".hidden",
                "show_version.txt"] + structured
    for name in captures:
        (root / name).write_text("snmp-server community S3cr3t RO\n", encoding="utf-8")
        planted.append(name)

    # the expected set, from the owner rule itself (blob.bin is excluded by CONTENT, which is the
    # half of the rule the name cannot decide, so it is never in this list)
    expected = sorted(n for n in planted if not redaction_verify.is_uncoverable_capture(n))
    assert set(captures) <= set(expected), sorted(set(captures) - set(expected))
    assert set(expected) < set(planted), "the name rule excluded nothing — the tree proves nothing"

    collection = tmp_path / "collection"
    census = ing._count_raw_captures(collection)
    scanned, _changed = redact_collection_dir(str(collection))

    assert census == scanned == len(expected), (
        f"ingest census {census} vs producer scanned {scanned}; the two are counting different "
        f"sets of physical files (the owner rule names {len(expected)})")
    # ...and the copy-back selector — the fourth place the same rule is applied — agrees file by
    # file, because a capture it does not select is scrubbed in staging and never written back.
    selected = sorted(p.name for p in collection.rglob("*")
                      if p.is_file() and ing._is_raw_capture(p))
    assert selected == expected, selected
    # ...as does the PRODUCER's own name rule, file by file: the count matching while the two sets
    # differ is exactly the failure the equality above is supposed to catch.
    for name in planted:
        assert _html._is_raw_capture(name) == (name in set(expected)), name

    # NON-VACUITY: the census is not simply "every file" — the excluded ones really are there.
    assert len(list(collection.rglob("*"))) > len(expected) + 1
