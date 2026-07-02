"""Guard tests for the golden harness itself (Plan A / Move-0.1).

The golden files are the repo's behavior-preservation oracle: "suite green with no
UPDATE_GOLDEN" is only a proof if the harness can never re-baseline silently. Two holes
are closed and pinned here:

1. AUTO-BLESS: a *missing* golden must FAIL the test (a deleted/lost golden is a broken
   contract), never regenerate-and-skip — regeneration is only ever the deliberate
   UPDATE_GOLDEN=1 path.
2. SHRINKAGE: even under UPDATE_GOLDEN=1, silently REMOVING contract surface (a snapshot
   top-level key, a workbook sheet, a header cell of a retained sheet) vs the git-HEAD
   baseline is rejected unless ALLOW_GOLDEN_SHRINK=1 makes the removal explicit.
"""
import json
import os
import subprocess

import pytest

import test_pipeline_golden as tpg


@pytest.fixture()
def golden_dir(tmp_path, monkeypatch):
    """Point the harness at an isolated golden dir and a clean env."""
    monkeypatch.setattr(tpg, "GOLDEN_DIR", str(tmp_path))
    monkeypatch.delenv("UPDATE_GOLDEN", raising=False)
    monkeypatch.delenv("ALLOW_GOLDEN_SHRINK", raising=False)
    return tmp_path


def test_missing_golden_fails_not_skips(golden_dir):
    """The auto-bless hole: a missing golden used to regenerate + skip, silently
    re-baselining the contract. It must now FAIL — and write NOTHING."""
    with pytest.raises(pytest.fail.Exception, match="MISSING"):
        tpg._golden("snapshot.json", {"section": 1})
    assert not (golden_dir / "snapshot.json").exists(), \
        "a failing missing-golden check must not leave a fresh baseline behind"


def test_existing_golden_is_returned_for_assertion(golden_dir):
    """Normal path: an existing golden is parsed and handed back to the caller to assert."""
    (golden_dir / "snapshot.json").write_text(json.dumps({"a": 1}), encoding="utf-8")
    assert tpg._golden("snapshot.json", {"a": 2}) == {"a": 1}


def test_update_golden_writes_baseline_when_untracked(golden_dir, monkeypatch):
    """UPDATE_GOLDEN=1 with no git-HEAD baseline (brand-new golden) writes and returns
    None (the caller's regenerate-early-return contract)."""
    monkeypatch.setenv("UPDATE_GOLDEN", "1")
    monkeypatch.setattr(tpg, "_git_head_golden", lambda name: None)
    assert tpg._golden("snapshot.json", {"a": 1}) is None
    assert json.loads((golden_dir / "snapshot.json").read_text(encoding="utf-8")) == {"a": 1}


def test_update_golden_rejects_snapshot_key_removal(golden_dir, monkeypatch):
    """UPDATE_GOLDEN=1 must refuse to bless a golden that DROPS a top-level snapshot
    section vs git HEAD — shrinkage needs the explicit ALLOW_GOLDEN_SHRINK=1."""
    monkeypatch.setenv("UPDATE_GOLDEN", "1")
    monkeypatch.setattr(tpg, "_git_head_golden",
                        lambda name: {"kept": 1, "vanished_section": 2})
    with pytest.raises(pytest.fail.Exception, match="SHRINK"):
        tpg._golden("snapshot.json", {"kept": 1})
    assert not (golden_dir / "snapshot.json").exists(), \
        "a rejected shrink must not write the shrunken golden"


def test_update_golden_shrink_allowed_with_explicit_flag(golden_dir, monkeypatch):
    """ALLOW_GOLDEN_SHRINK=1 makes a deliberate contract removal possible (reviewed)."""
    monkeypatch.setenv("UPDATE_GOLDEN", "1")
    monkeypatch.setenv("ALLOW_GOLDEN_SHRINK", "1")
    monkeypatch.setattr(tpg, "_git_head_golden",
                        lambda name: {"kept": 1, "vanished_section": 2})
    assert tpg._golden("snapshot.json", {"kept": 1}) is None
    assert json.loads((golden_dir / "snapshot.json").read_text(encoding="utf-8")) == {"kept": 1}


def test_contract_shrinkage_semantics():
    """The shrink detector is surface-removal only — additions and value changes are the
    additive/blessed norm and must NOT trip it."""
    # additive + value-change: not shrinkage
    assert tpg._contract_shrinkage("snapshot.json", {"a": 1}, {"a": 999, "b": 2}) == []
    # removed snapshot section: shrinkage
    assert tpg._contract_shrinkage("snapshot.json", {"a": 1, "b": 2}, {"a": 1})
    # sheet schema: a removed SHEET and a removed HEADER CELL of a retained sheet both count
    lost = tpg._contract_shrinkage(
        "sheet_schema.json",
        {"Sheet A": ["H1", "H2"], "Sheet B": ["X"]},
        {"Sheet A": ["H1"]})
    assert any("Sheet B" in m for m in lost), f"removed sheet not detected: {lost}"
    assert any("H2" in m for m in lost), f"removed header cell not detected: {lost}"
    # header reorder / append on a retained sheet: not shrinkage (exact order is the
    # golden equality assertion's job, not the shrink guard's)
    assert tpg._contract_shrinkage(
        "sheet_schema.json", {"S": ["A", "B"]}, {"S": ["B", "A", "C"]}) == []


def test_git_head_golden_reads_the_tracked_baseline():
    """The shrink guard's baseline really is git HEAD: the tracked snapshot golden loads
    as a non-empty dict, and an untracked name returns None (nothing to shrink against)."""
    probe = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=tpg.ROOT,
                           capture_output=True, text=True)
    if probe.returncode != 0:
        pytest.skip("no git HEAD available")
    head = tpg._git_head_golden("snapshot.json")
    assert isinstance(head, dict) and head, "tracked golden must load from HEAD"
    assert tpg._git_head_golden("definitely_not_a_golden_file.json") is None


def test_real_goldens_exist_on_disk():
    """Belt-and-braces: the two contract goldens are present in the working tree (the
    missing-golden FAIL above is the backstop; this catches an accidental deletion at
    the point of deletion, with a clearer message)."""
    for name in ("snapshot.json", "sheet_schema.json"):
        assert os.path.isfile(os.path.join(tpg.GOLDEN_DIR, name)), \
            f"tests/golden/{name} is missing from the working tree"
