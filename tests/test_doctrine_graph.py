"""[W3-6] Coverage-honesty as a BUILD GATE: the doctrine graph (the offline AST projection of the design-detector
<-> design_kb principle relationship) and its two invariants. Rebuilt from SOURCE every run (AST-only, no egress)
so a future detector<->KB drift is caught at build time, not in a client deliverable."""
from cisco_toolkit.doctrine import build_doctrine_graph, doctrine_invariants


def test_doctrine_invariants_logic_catches_violations():
    """The invariant LOGIC is not a rubber-stamp -- on synthetic inputs it flags an orphan detector (a cited pid
    with no KB principle) AND an uncited engine_actionable principle (one claimed actionable but never wired)."""
    inv = doctrine_invariants(cited={"a", "ghost"}, kb_ids={"a", "b", "c"}, actionable={"a", "b"})
    assert inv["orphan_detectors"] == ["ghost"]          # 'ghost' is cited but not in the KB
    assert inv["uncited_actionable"] == ["b"]            # 'b' is engine_actionable but no detector cites it
    clean = doctrine_invariants(cited={"a", "b"}, kb_ids={"a", "b", "c"}, actionable={"a", "b"})
    assert clean["orphan_detectors"] == [] and clean["uncited_actionable"] == []


def test_doctrine_graph_holds_on_the_real_engine():
    """The GATE: the live design_advisor <-> design_kb graph must hold both invariants -- NO orphan detector, and
    every engine_actionable principle actually wired (via a literal _decision() OR the _NEEDS requirements overlay)."""
    g = build_doctrine_graph()
    assert g["orphan_detectors"] == [], f"detector cites a pid with no KB principle: {g['orphan_detectors']}"
    assert g["uncited_actionable"] == [], f"engine_actionable principle not wired by any detector: {g['uncited_actionable']}"
    # the ONLY non-literal _decision call is the _NEEDS requirements-overlay loop, so every pid is accounted for
    # (a NEW dynamic _decision call could otherwise smuggle an uncounted / orphan pid past the gate).
    assert len(g["dynamic_decision_lines"]) <= 1, f"unexpected dynamic _decision call(s): {g['dynamic_decision_lines']}"
    # sanity: the projection actually loaded the AST + the KB (not silently empty)
    assert g["n_detectors"] >= 50 and len(g["kb_ids"]) >= 100 and g["actionable"]
