"""P0-3 / DEC-003 (gap G-003): the PPDIOO human gates are mechanized, not prose-only.

Acceptance criteria from the architect master plan (2026-07-10):
- generating a MOP without an approved-LLD marker REFUSES (``test_mop_without_approved_lld_refuses``);
- ``--override-gate`` proceeds AND leaves a who/when/why audit line
  (``test_override_proceeds_and_appends_audit_line``);
plus the fail-safe brownfield contract (no store at all = warn-and-proceed, never hard-fail) and
the fail-closed contracts (revoked marker re-refuses; an unreadable store is NOT overridable).

The engine wiring is pinned by source guard (the repo's established pattern — see
``test_registry_cited_snapshot_keys_are_published_by_the_engine``): the design/MOP write blocks in
``COLLECT_PARSE_V3_23_0.main()`` must stay guarded by ``gate_state.enforce`` and the parser must
keep the ``--override-gate`` flag.
"""
import json
import logging
import re
from pathlib import Path

import pytest

from cisco_toolkit import gate_state

ROOT = Path(__file__).resolve().parents[1]


def _store(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "docs" / "engagement-state.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- brownfield fail-safe (no store)

def test_no_store_warns_and_proceeds(tmp_path, caplog):
    """ABSENT store = ungated brownfield: both generators proceed, loudly, and the warn path must
    never itself create a store (activation is an explicit human `approve`, not a side effect)."""
    with caplog.at_level(logging.WARNING, logger="cisco_toolkit.gate_state"):
        assert gate_state.enforce("design", root=str(tmp_path)) is True
        assert gate_state.enforce("mop", root=str(tmp_path)) is True
    assert "UNGATED" in caplog.text and "brownfield" in caplog.text
    assert not (tmp_path / "docs" / "engagement-state.json").exists()


# ------------------------------------------------------------------------- the refusal (blocking)

def test_mop_without_approved_lld_refuses(tmp_path, caplog):
    """ACCEPTANCE: store exists, baseline captured, but no approved-LLD marker -> MOP refuses."""
    gate_state.record_decision("baseline_captured", "approved", root=str(tmp_path), by="qa")
    with caplog.at_level(logging.ERROR, logger="cisco_toolkit.gate_state"):
        assert gate_state.enforce("mop", root=str(tmp_path)) is False
    assert "GATE REFUSED" in caplog.text and "lld_approved" in caplog.text


def test_design_without_approved_assessment_refuses(tmp_path, caplog):
    """Design's upstream is the approved assessment (design-author charter): a store whose only
    approval is a DIFFERENT gate still refuses design generation."""
    gate_state.record_decision("lld_approved", "approved", root=str(tmp_path), by="qa")
    with caplog.at_level(logging.ERROR, logger="cisco_toolkit.gate_state"):
        assert gate_state.enforce("design", root=str(tmp_path)) is False
    assert "assessment_approved" in caplog.text


def test_revoke_reactivates_refusal(tmp_path):
    """A revoked approval is not an approval: the gate closes again (fail closed)."""
    for g in ("lld_approved", "baseline_captured"):
        gate_state.record_decision(g, "approved", root=str(tmp_path), by="qa")
    assert gate_state.enforce("mop", root=str(tmp_path)) is True
    gate_state.record_decision("lld_approved", "revoked", root=str(tmp_path), by="qa")
    assert gate_state.enforce("mop", root=str(tmp_path)) is False


def test_approved_upstream_proceeds_and_override_is_inert(tmp_path):
    """With every upstream approval recorded, generation proceeds — and a redundant
    --override-gate must NOT log a phantom override (nothing was overridden)."""
    for g in ("assessment_approved", "lld_approved", "baseline_captured"):
        gate_state.record_decision(g, "approved", root=str(tmp_path), by="human")
    assert gate_state.enforce("design", root=str(tmp_path)) is True
    assert gate_state.enforce("mop", root=str(tmp_path),
                              override_reason="redundant flag") is True
    assert [a["event"] for a in _store(tmp_path)["audit"]] == ["approve"] * 3


# --------------------------------------------------------------- the override (audited bypass)

def test_override_proceeds_and_appends_audit_line(tmp_path, caplog):
    """ACCEPTANCE: --override-gate on a refused MOP proceeds AND the store gains a who/when/why
    audit line naming the generator and the approvals that were missing."""
    gate_state.record_decision("baseline_captured", "approved", root=str(tmp_path), by="qa")
    with caplog.at_level(logging.WARNING, logger="cisco_toolkit.gate_state"):
        ok = gate_state.enforce("mop", override_reason="lab dry-run; CAB waived by ops lead",
                                root=str(tmp_path), who="tester")
    assert ok is True
    line = _store(tmp_path)["audit"][-1]
    assert line["event"] == "override"
    assert line["generator"] == "mop"
    assert line["missing"] == ["lld_approved"]
    assert line["who"] == "tester"
    assert line["reason"] == "lab dry-run; CAB waived by ops lead"
    assert line["at"]  # the WHEN
    assert "GATE OVERRIDDEN" in caplog.text


def test_blank_override_reason_still_refuses(tmp_path):
    """The audit line is the point of the override: a whitespace-only reason refuses and no
    override line is written."""
    gate_state.record_decision("assessment_approved", "revoked", root=str(tmp_path), by="qa")
    assert gate_state.enforce("design", override_reason="   ", root=str(tmp_path)) is False
    assert all(a["event"] != "override" for a in _store(tmp_path)["audit"])


def test_unreadable_store_refuses_even_with_override(tmp_path, caplog):
    """A store that exists but cannot be parsed fails CLOSED — the override's audit line has
    nowhere trustworthy to land, so --override-gate cannot bypass it."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "engagement-state.json").write_text("{not json", encoding="utf-8")
    with caplog.at_level(logging.ERROR, logger="cisco_toolkit.gate_state"):
        assert gate_state.enforce("mop", override_reason="try anyway",
                                  root=str(tmp_path)) is False
    assert "unreadable" in caplog.text


# ------------------------------------------------------------------------------ schema contracts

def test_unknown_generator_gate_and_decision_raise(tmp_path):
    with pytest.raises(ValueError):
        gate_state.enforce("runbook", root=str(tmp_path))  # not a gated generator
    with pytest.raises(ValueError):
        gate_state.record_decision("not_a_gate", "approved", root=str(tmp_path))
    with pytest.raises(ValueError):
        gate_state.record_decision("lld_approved", "maybe", root=str(tmp_path))


def test_gate_keys_are_append_only_storage_schema():
    """The keys are persisted into per-engagement stores — a rename orphans recorded sign-offs
    (same contract as engagement.GATE_SEQUENCE). Renaming/removing one must fail here first."""
    assert {"assessment_approved", "lld_approved", "baseline_captured",
            "cab_approved", "nrfu_signed"} <= set(gate_state.GATE_KEYS)
    assert gate_state.GENERATOR_REQUIRES["design"] == ("assessment_approved",)
    assert gate_state.GENERATOR_REQUIRES["mop"] == ("lld_approved", "baseline_captured")


# ------------------------------------------------------------------------------------ CLI arms

def test_cli_approve_show_roundtrip(tmp_path, capsys):
    rc = gate_state.main(["--root", str(tmp_path), "approve", "lld_approved",
                          "--by", "reviewer", "--note", "LLD v2 signed"])
    assert rc == 0
    rc = gate_state.main(["--root", str(tmp_path), "show"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "lld_approved" in out and "approved" in out and "reviewer" in out
    assert "override(s)" in out  # the weekly-review counter (DEC-003)


def test_cli_show_absent_store_is_honest(tmp_path, capsys):
    assert gate_state.main(["--root", str(tmp_path), "show"]) == 0
    assert "UNGATED" in capsys.readouterr().out


# ------------------------------------------------------------------- engine wiring + Law 1 pins

def test_engine_wires_the_gates_and_the_override_flag():
    """Source guard: the design/MOP blocks in main() stay gate-guarded and the flag exists.
    (The write functions themselves stay ungated on purpose — the ~60 direct-call tests and the
    webapp regeneration path are additive-compatibility surfaces; the CLI is the enforcement
    point because that is where --override-gate lives.)"""
    src = (ROOT / "COLLECT_PARSE_V3_23_0.py").read_text(encoding="utf-8", errors="ignore")
    assert '"--override-gate"' in src, "the CLI lost the --override-gate flag"
    assert "from cisco_toolkit.gate_state import enforce as gate_enforce" in src
    assert re.search(r'if not args\.no_design and '
                     r'gate_enforce\("design", override_reason=args\.override_gate\)', src), \
        "the design write block is no longer gate-guarded"
    assert re.search(r'if not args\.no_mop and '
                     r'gate_enforce\("mop", override_reason=args\.override_gate\)', src), \
        "the MOP write block is no longer gate-guarded"


def test_ssot_registry_cites_the_gate_state_owner():
    """Law 1: the store is a source of truth, so the registry must name it and its schema owner."""
    txt = (ROOT / "docs" / "ssot.md").read_text(encoding="utf-8")
    assert "engagement-state.json" in txt
    assert "gate_state.py" in txt
    assert "test_gate_state.py" in txt  # the enforcement column cites this suite
