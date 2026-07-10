"""PPDIOO document-gate state — the mechanized human-gate record (P0-3 / DEC-003 / gap G-003).

The engagement gate sequence (Assess → *approve* → Design → *peer review* → MOP → *dry-run+CAB* →
cutover → PIR) was prose-only: every arrow is a human checkpoint, but no generator refused to run
when its upstream approval was missing. This module is the enforcement half of that doctrine:

- ``DOC_GATES`` is the **document-gate axis** — per-engagement document approvals. It complements
  (does not replace) ``cisco_toolkit.engagement.GATE_SEQUENCE``, which is the **per-wave T-minus
  execution cadence** (commit → … → hypercare exit). Same record model as the AssessHub gate board
  (``webapp/backend/gates.py``): a gate row stores ``decision / signed_by / note / decided_at``.
  Same append-only key contract as GATE_SEQUENCE: the keys are a storage schema — never rename or
  remove one (existing stores would orphan); only append.
- The store is ``docs/engagement-state.json`` **relative to the working directory** (gate state is
  per-engagement and lives next to that engagement's artifacts). Registered in ``docs/ssot.md``
  (Law 1): the store is the one owner of engagement gate/approval state + the override audit trail.
- ``enforce()`` is what the engine calls before generating a gated deliverable
  (``COLLECT_PARSE_V3_23_0`` design/MOP blocks). Semantics — additive and fail-safe by design:

  * **No store at all** → warn-and-proceed (brownfield compatibility: existing engagements keep
    working ungated until someone records the first approval).
  * **Store present, upstream approvals recorded** → proceed.
  * **Store present, an upstream approval missing/revoked** → REFUSE (the generator skips, loudly).
    Overridable ONLY by an explicit non-empty ``--override-gate "<reason>"``, which proceeds AND
    appends a who/when/why audit line to the store (DEC-003: overrides are reviewed weekly —
    ``python -m cisco_toolkit.gate_state show`` lists them).
  * **Store present but unreadable** → REFUSE, even with an override (an unreadable ledger cannot
    take the audit line that makes an override legitimate; fix or remove the store).

Gate requirements mirror the agent charters: design requires an APPROVED assessment
(.claude/agents/design-author.md — "design follows an approved assessment"); the MOP requires an
approved LLD + a captured current-state baseline (.claude/agents/mop-change-author.md — "Require an
approved LLD + current-state baseline"). Stdlib-only; no cisco_toolkit imports; deterministic; no
network. CLI: ``python -m cisco_toolkit.gate_state show | approve <gate> | revoke <gate>``.
"""
from __future__ import annotations

import getpass
import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

STORE_RELPATH = os.path.join("docs", "engagement-state.json")

# The PPDIOO document-gate chain — (key, label, arrow, criteria). APPEND-ONLY keys (storage schema,
# same contract as engagement.GATE_SEQUENCE). Only the gates named in GENERATOR_REQUIRES are
# mechanically enforced today; the later arrows (CAB, NRFU) are recordable now, enforceable later.
DOC_GATES = (
    ("assessment_approved", "Assessment + gap analysis approved", "Assess -> Design",
     "Human approved the current-state assessment and gap analysis"),
    ("lld_approved", "HLD/LLD peer-reviewed and approved", "Design -> MOP",
     "Design peer review passed; the LLD the MOP will implement is signed"),
    ("baseline_captured", "Current-state baseline captured", "Design -> MOP",
     "A baseline snapshot exists for pre/post --compare validation"),
    ("cab_approved", "MOP dry-run validated + CAB approval", "MOP -> Cutover",
     "MOP dry-run passed; CAB approved the change inside a maintenance window"),
    ("nrfu_signed", "NRFU acceptance signed", "Cutover -> PIR",
     "NRFU/ATP passed and was signed by the acceptance owner"),
)
GATE_KEYS = tuple(key for key, *_rest in DOC_GATES)
GATE_LABELS = {key: label for key, label, *_rest in DOC_GATES}

# Which upstream approvals each gated generator needs before it may produce its artifact.
GENERATOR_REQUIRES: Dict[str, Tuple[str, ...]] = {
    "design": ("assessment_approved",),
    "mop": ("lld_approved", "baseline_captured"),
}


class GateStateError(RuntimeError):
    """The gate-state store exists but cannot be read/parsed — fail CLOSED, never silently ungate."""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _whoami() -> str:
    try:
        return getpass.getuser() or "unknown"
    except Exception:
        return os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"


def store_path(root: str = ".") -> str:
    return os.path.join(root, STORE_RELPATH)


def load_store(root: str = ".") -> Tuple[Optional[dict], str]:
    """Return ``(store, path)``. ``store`` is None when the file is ABSENT (ungated brownfield).
    A file that exists but is unreadable / not a JSON object raises GateStateError — once an
    engagement is gate-tracked, a broken ledger must never be mistaken for "no gates"."""
    path = store_path(root)
    if not os.path.exists(path):
        return None, path
    try:
        with open(path, encoding="utf-8") as f:
            store = json.load(f)
    except (OSError, ValueError) as e:
        raise GateStateError(f"unreadable gate-state store {path}: {e}") from e
    if not isinstance(store, dict):
        raise GateStateError(f"gate-state store {path} is not a JSON object")
    return store, path


def save_store(path: str, store: dict) -> None:
    """Atomic write (tmp + os.replace) so a crash mid-write can never corrupt the audit ledger."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2, sort_keys=False)
        f.write("\n")
    os.replace(tmp, path)


def _new_store() -> dict:
    return {"schema": 1, "gates": {}, "audit": []}


def _gates(store: dict) -> dict:
    g = store.get("gates")
    return g if isinstance(g, dict) else {}


def is_approved(store: dict, gate: str) -> bool:
    """A gate counts as approved ONLY on an explicit recorded decision — any malformed row,
    absent marker, or non-'approved' decision is unapproved (fail closed once a store exists)."""
    rec = _gates(store).get(gate)
    return isinstance(rec, dict) and rec.get("decision") == "approved"


def missing_approvals(store: dict, generator: str) -> List[str]:
    if generator not in GENERATOR_REQUIRES:
        raise ValueError(f"unknown gated generator {generator!r} "
                         f"(expected one of {sorted(GENERATOR_REQUIRES)})")
    return [k for k in GENERATOR_REQUIRES[generator] if not is_approved(store, k)]


def _append_audit(path: str, store: dict, entry: dict) -> dict:
    audit = store.get("audit")
    if not isinstance(audit, list):
        audit = []
        store["audit"] = audit
    audit.append(entry)
    save_store(path, store)
    return entry


def record_decision(gate: str, decision: str, root: str = ".",
                    by: Optional[str] = None, note: str = "") -> dict:
    """Record a human gate disposition (approve/revoke). Creates the store on first use — that is
    the explicit opt-in moment that activates enforcement for the engagement in ``root``."""
    if gate not in GATE_KEYS:
        raise ValueError(f"unknown gate {gate!r} (expected one of {list(GATE_KEYS)})")
    if decision not in ("approved", "revoked"):
        raise ValueError(f"unknown decision {decision!r} (expected 'approved' or 'revoked')")
    store, path = load_store(root)
    if store is None:
        store = _new_store()
    who = by or _whoami()
    store.setdefault("gates", {})
    store["gates"][gate] = {"decision": decision, "signed_by": who,
                            "note": note, "decided_at": _now()}
    _append_audit(path, store, {"at": _now(), "who": who,
                                "event": "approve" if decision == "approved" else "revoke",
                                "gate": gate, "note": note})
    return store["gates"][gate]


def enforce(generator: str, override_reason: Optional[str] = None,
            root: str = ".", who: Optional[str] = None) -> bool:
    """Gate check for a generator run. True = proceed, False = REFUSE (caller must skip the write).

    Absent store → warn + True (brownfield). Unreadable store → error + False (not overridable —
    the override's audit line has nowhere trustworthy to land). Missing approvals → False, unless
    ``override_reason`` is non-empty, in which case an audit line (who/when/why + what was missing)
    is appended to the store and the run proceeds.
    """
    if generator not in GENERATOR_REQUIRES:
        raise ValueError(f"unknown gated generator {generator!r} "
                         f"(expected one of {sorted(GENERATOR_REQUIRES)})")
    try:
        store, path = load_store(root)
    except GateStateError as e:
        logger.error("[GATE REFUSED] %s: %s -- fix or remove the store; "
                     "--override-gate cannot bypass an unreadable ledger", generator, e)
        return False
    if store is None:
        logger.warning("[gate] no gate-state store at %s -- %s generation proceeds UNGATED "
                       "(brownfield). Activate PPDIOO gate enforcement with: "
                       "python -m cisco_toolkit.gate_state approve <gate>", path, generator)
        return True
    missing = missing_approvals(store, generator)
    if not missing:
        logger.info("[gate] %s: upstream approvals present (%s) -- proceeding",
                    generator, ", ".join(GENERATOR_REQUIRES[generator]))
        return True
    if override_reason is not None and override_reason.strip():
        actor = who or _whoami()
        _append_audit(path, store, {"at": _now(), "who": actor, "event": "override",
                                    "generator": generator, "missing": missing,
                                    "reason": override_reason.strip()})
        logger.warning("[GATE OVERRIDDEN] %s generated despite missing approval(s) %s -- "
                       "who=%s reason=%r (audit line appended to %s)",
                       generator, ", ".join(missing), actor, override_reason.strip(), path)
        return True
    if override_reason is not None:
        logger.error("[GATE REFUSED] %s: --override-gate requires a non-empty reason "
                     "(the who/when/why audit line is the point of the override)", generator)
        return False
    logger.error("[GATE REFUSED] %s: missing upstream approval(s): %s. Record the human gate with "
                 "'python -m cisco_toolkit.gate_state approve <gate> --by <name>', or override "
                 "explicitly with --override-gate \"<reason>\" (audited). Store: %s",
                 generator,
                 ", ".join(f"{k} ({GATE_LABELS[k]})" for k in missing),
                 path)
    return False


def main(argv: Optional[List[str]] = None) -> int:
    """CLI: ``show`` the gate board + audit tail; ``approve``/``revoke`` a gate (creates the store
    on first approve — the enforcement opt-in). Exit 0 on success, 2 on usage errors (argparse)."""
    import argparse

    ap = argparse.ArgumentParser(
        prog="python -m cisco_toolkit.gate_state",
        description="PPDIOO document-gate state (P0-3/DEC-003): record human gate approvals; "
                    "the design/MOP generators refuse when their upstream approval is absent.")
    ap.add_argument("--root", default=".",
                    help="engagement root holding docs/engagement-state.json (default: cwd)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show", help="print the gate board + the audit tail (overrides flagged)")
    for verb, help_txt in (("approve", "record a human gate approval"),
                           ("revoke", "revoke a previously recorded approval")):
        p = sub.add_parser(verb, help=help_txt)
        p.add_argument("gate", choices=list(GATE_KEYS))
        p.add_argument("--by", default=None, help="who signed (default: current OS user)")
        p.add_argument("--note", default="", help="optional note stored with the decision")
    args = ap.parse_args(argv)

    if args.cmd in ("approve", "revoke"):
        rec = record_decision(args.gate, "approved" if args.cmd == "approve" else "revoked",
                              root=args.root, by=args.by, note=args.note)
        print(f"{args.gate}: {rec['decision']} by {rec['signed_by']} at {rec['decided_at']}"
              f" -> {store_path(args.root)}")
        return 0

    # show
    try:
        store, path = load_store(args.root)
    except GateStateError as e:
        print(f"UNREADABLE gate-state store: {e}")
        return 1
    if store is None:
        print(f"no gate-state store at {path} -- engagement is UNGATED (brownfield). "
              f"First 'approve' creates it and activates enforcement.")
        return 0
    print(f"gate-state store: {path}")
    for key, label, arrow, _criteria in DOC_GATES:
        rec = _gates(store).get(key)
        if isinstance(rec, dict) and rec.get("decision"):
            print(f"  {key:20s} [{rec.get('decision'):8s}] {arrow:18s} "
                  f"by {rec.get('signed_by') or '?'} at {rec.get('decided_at') or '?'}")
        else:
            print(f"  {key:20s} [   --   ] {arrow:18s} {label}")
    audit = [a for a in store.get("audit", []) if isinstance(a, dict)]
    overrides = [a for a in audit if a.get("event") == "override"]
    print(f"audit: {len(audit)} entries ({len(overrides)} override(s) -- review weekly, DEC-003)")
    for a in audit[-10:]:
        flag = " **OVERRIDE**" if a.get("event") == "override" else ""
        what = a.get("gate") or a.get("generator") or "?"
        why = a.get("reason") or a.get("note") or ""
        print(f"  {a.get('at', '?')}  {a.get('event', '?'):8s} {what:12s} "
              f"by {a.get('who', '?')}  {why}{flag}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
