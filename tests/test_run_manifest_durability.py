"""Crash-safety of the JSON writer behind the snapshot and the sealed run manifest.

The manifest is the chain-of-custody record (NOT a debug artifact): a torn write destroys exactly
the tamper-evidence its `chain_root` seal exists to provide. It was written with a plain
`open(path, "w")`, which truncates the good file BEFORE the new bytes are written -- so a crash in
that window (ADR-0004 P3: a USB unplug mid-write) left neither the old file nor a complete new one.
`cisco_toolkit.gate_state.save_store` already had the right discipline; this writer did not.

The fix is atomic-where-possible with a LOUD degrade, and the second half is load-bearing on
Windows. `os.replace` must delete its destination, so it raises PermissionError while any process
holds a handle -- an AV on-access scan, the search indexer, a viewer the engineer left open on the
stick -- where the plain truncate-write simply succeeded. A bare atomic write would therefore be a
REGRESSION, and a worse failure than the one being fixed: the callers log the failure and ship the
run, leaving the PREVIOUS manifest beside freshly rewritten artifacts. That stale manifest still
passes verify_manifest while every hash in it is wrong. A torn write announces itself; a stale seal
certifies a lie.

So the contract pinned here is, in order of priority:
  1. never fail a write that the old implementation would have completed  (test_locked_destination_*)
  2. never publish a partial file                                         (test_crash_*)
  3. never leave a temp behind, including on KeyboardInterrupt            (test_crash_*)
  4. never seal a stray temp as a delivered artifact                      (test_stray_tmp_*)
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import COLLECT_PARSE_V3_23_0 as cp   # noqa: E402  (the entry module owning write_json_file)
from cisco_toolkit import manifest as m      # noqa: E402


def _tmps_in(d):
    return [f for f in os.listdir(d) if f.endswith(".tmp")]


# ------------------------------------------------- 1. never regress below the old success envelope

def test_locked_destination_still_completes_the_write(tmp_path, caplog):
    """THE REGRESSION GUARD. A reader holding the destination open makes os.replace fail on Windows
    while the old plain truncate-write succeeded. The write must still land, and must SAY that it
    gave up crash-safety to do so -- a silently non-atomic write is the failure mode --selftest
    exists to prevent elsewhere in this codebase.
    """
    path = str(tmp_path / "assessment.run_manifest.json")
    cp.write_json_file(path, {"chain_root": "run-one"})

    with open(path, "r", encoding="utf-8"):          # ordinary reader; CRT shares read+write
        with caplog.at_level("WARNING"):
            cp.write_json_file(path, {"chain_root": "run-two"})

    assert json.load(open(path, encoding="utf-8"))["chain_root"] == "run-two", \
        "the write was lost -- a stale seal would ship beside freshly written artifacts"
    assert _tmps_in(tmp_path) == []
    if "Atomic write unavailable" not in caplog.text:
        # POSIX renames over an open file happily, so the atomic path simply succeeds there.
        assert os.name != "nt", "on Windows the locked destination must have forced the fallback"


def test_fallback_is_not_silent(tmp_path, caplog):
    """Non-vacuous companion to the above: prove the warning is emitted for the real cause, rather
    than the test merely never exercising the fallback."""
    def _boom(_path, _dump):
        raise PermissionError(5, "Access is denied")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(cp, "_write_json_atomic", _boom)
        with caplog.at_level("WARNING"):
            cp.write_json_file(str(tmp_path / "out.json"), {"a": 1})
    assert "Atomic write unavailable" in caplog.text and "PermissionError" in caplog.text
    assert json.load(open(tmp_path / "out.json", encoding="utf-8")) == {"a": 1}


# --------------------------------------------------------------- 2/3. crash safety on the fast path

@pytest.mark.parametrize("boom", [RuntimeError("disk full"), KeyboardInterrupt()])
def test_crash_mid_write_preserves_the_previous_file(tmp_path, monkeypatch, boom):
    """KeyboardInterrupt is parametrized deliberately: it is a BaseException, so cleanup guarded by
    `except Exception` would leak the temp for exactly the signal (Ctrl-C / SIGTERM on unplug) this
    protection exists for. A RuntimeError instead falls back and completes -- so the two arms assert
    different things: the interrupt must NOT publish, the ordinary error must.
    """
    path = str(tmp_path / "assessment.run_manifest.json")
    cp.write_json_file(path, {"chain_root": "original"})
    before = open(path, encoding="utf-8").read()

    def exploding_dump(*a, **k):
        raise boom
    monkeypatch.setattr(cp.json, "dump", exploding_dump)

    if isinstance(boom, KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            cp.write_json_file(path, {"chain_root": "replacement"})
        assert open(path, encoding="utf-8").read() == before, "an interrupt destroyed the sealed file"
    else:
        # The fallback re-runs the same failing dump, so the error surfaces from the in-place write.
        with pytest.raises(RuntimeError):
            cp.write_json_file(path, {"chain_root": "replacement"})
    assert _tmps_in(tmp_path) == [], "a temp file leaked beside the artifact"


def test_interrupt_before_any_file_exists_publishes_nothing(tmp_path, monkeypatch):
    """With no prior file, an interrupted write must leave NOTHING -- never a truncated JSON that a
    reader would parse, or that verify_chain would report on."""
    path = str(tmp_path / "assessment.run_manifest.json")
    monkeypatch.setattr(cp.json, "dump",
                        lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        cp.write_json_file(path, {"chain_root": "x"})
    assert not os.path.exists(path)
    assert _tmps_in(tmp_path) == []


def test_successful_write_is_complete_and_leaves_no_temp(tmp_path):
    path = str(tmp_path / "nested" / "out.json")     # also pins makedirs on a fresh subdir
    cp.write_json_file(path, {"a": 1, "b": [1, 2]})
    assert json.load(open(path, encoding="utf-8")) == {"a": 1, "b": [1, 2]}
    assert _tmps_in(tmp_path / "nested") == []


def test_bare_filename_does_not_raise(tmp_path, monkeypatch):
    """`os.path.dirname("out.json")` is "", and makedirs("") raises -- so the old code could not
    write to a bare relative filename at all."""
    monkeypatch.chdir(tmp_path)
    cp.write_json_file("out.json", {"ok": True})
    assert json.load(open(tmp_path / "out.json", encoding="utf-8")) == {"ok": True}


# ------------------------------------------------------- 4. a stray temp is never sealed as evidence

def test_stray_tmp_is_not_sealed_as_a_delivered_artifact(tmp_path):
    """A write killed uncatchably (TerminateProcess, power loss) leaves a temp that `except
    BaseException` cannot clean up, and a CONCURRENT run's temp is visible for its whole write.
    Sealing either would publish, under the chain_root, bytes the pipeline deliberately never
    published -- and the manifest would still verify clean.
    """
    out_xlsx = str(tmp_path / "assessment.xlsx")
    open(out_xlsx, "w").close()
    (tmp_path / "assessment.snapshot.json.29460.tmp").write_text(
        '{"chain_root": "NEVER-PUBLISHED"}', encoding="utf-8")

    man = cp.build_run_manifest(out_xlsx, {})

    sealed = [a["name"] for a in man["artifacts"]]
    assert not any(n.endswith(".tmp") for n in sealed), f"a temp was sealed as an artifact: {sealed}"
    assert "assessment.xlsx" in sealed
    deliver = next(r for r in man["chain"] if r.get("stage") == "deliver")
    assert not any(n.endswith(".tmp") for n in deliver["artifacts"])
    ok, _ = m.verify_chain(man["chain"], expected_root=man["chain_root"])
    assert ok is True


# --------------------------------------------------------------- overwrite policy (decided, pinned)

def test_rerun_replaces_the_manifest(tmp_path):
    """DECIDED policy, pinned so it cannot drift into an accident: the manifest is a PER-RUN seal of
    the artifact set beside it. A re-run to the same --output replaces it exactly as it replaces the
    artifacts it hashes -- a manifest outliving its artifacts would seal files that no longer exist.
    The chain is append-only WITHIN one file; it is not a cross-run archive, and manifest.py and
    docs/ssot.md now say so rather than claiming "append-only" unqualified.
    """
    path = str(tmp_path / "assessment.run_manifest.json")
    cp.write_json_file(path, {"chain_root": "run-one"})
    cp.write_json_file(path, {"chain_root": "run-two"})
    assert json.load(open(path, encoding="utf-8"))["chain_root"] == "run-two"
    assert _tmps_in(tmp_path) == []
