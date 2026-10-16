"""Doctrine graph (W3-6): the offline AST projection of the design-detector <-> design_kb principle relationship,
plus the two coverage-honesty INVARIANTS over it.

A design detector cites a principle by passing its principle-id to ``_decision(pid, ...)``; the interactive
requirements overlay cites via the ``_NEEDS`` table (one ``_decision`` call with a *variable* pid). This module
rebuilds the graph from SOURCE on every call -- AST-only, no egress, no committed snapshot to rot -- so two
invariants can gate it in CI:

  * **no orphan detector** -- every cited pid exists in ``design_kb`` (a detector can never cite a principle that
    does not exist), and
  * **engine_actionable subset of cited** -- every principle that *claims* the engine can act on it
    (``engine_actionable: true``) is actually wired by a detector (no overclaimed actionability).

Together they make coverage-honesty a build gate and attack the recurring detector<->KB drift class.
"""
from __future__ import annotations

import ast
from typing import Any, Dict, Iterable, List, Set, Tuple


def doctrine_invariants(cited: Iterable[str], kb_ids: Iterable[str], actionable: Iterable[str]) -> Dict[str, List[str]]:
    """Pure invariant logic over the three id sets -- separated from the AST/KB loading so it is unit-testable.
    Returns {'orphan_detectors': sorted(cited - kb_ids), 'uncited_actionable': sorted(actionable - cited)}."""
    cited, kb_ids, actionable = set(cited), set(kb_ids), set(actionable)
    return {
        "orphan_detectors": sorted(cited - kb_ids),       # cited by a detector but absent from the KB
        "uncited_actionable": sorted(actionable - cited),  # claims engine_actionable but no detector wires it
    }


def _cited_pids() -> Tuple[Set[str], Set[str], List[int]]:
    """(literal _decision() pids, _NEEDS pids, dynamic _decision call line numbers) from the design_advisor SOURCE.
    A dynamic call is a ``_decision(...)`` whose first arg is NOT a string literal (the _NEEDS loop is the one
    legitimate case -- its pids are recovered from the imported ``_NEEDS`` table)."""
    from cisco_toolkit import design_advisor
    with open(design_advisor.__file__, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    literal: Set[str] = set()
    dynamic: List[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_decision":
            a0 = node.args[0] if node.args else None
            if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                literal.add(a0.value)
            else:
                dynamic.append(node.lineno)
    needs: Set[str] = {t[0] for t in getattr(design_advisor, "_NEEDS", [])
                       if isinstance(t, (tuple, list)) and t and isinstance(t[0], str)}
    return literal, needs, dynamic


def build_doctrine_graph() -> Dict[str, Any]:
    """Project the doctrine graph from source + the KB and evaluate the two invariants. Offline (AST + a dict
    read); total. Returns the cited/kb/actionable id sets, the detector/needs counts, the dynamic-call lines, and
    the two invariant verdicts (orphan_detectors / uncited_actionable -- both empty when the graph is healthy)."""
    from cisco_toolkit import design_kb
    literal, needs, dynamic = _cited_pids()
    cited = literal | needs
    kb_ids = {p["id"] for p in getattr(design_kb, "DOCTRINE", []) if isinstance(p, dict) and p.get("id")}
    actionable = {p["id"] for p in getattr(design_kb, "DOCTRINE", [])
                  if isinstance(p, dict) and p.get("engine_actionable")}
    inv = doctrine_invariants(cited, kb_ids, actionable)
    return {
        "cited": sorted(cited),
        "kb_ids": sorted(kb_ids),
        "actionable": sorted(actionable),
        "n_detectors": len(literal),
        "n_needs": len(needs),
        "dynamic_decision_lines": dynamic,
        **inv,
    }
