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

**Root resolution — the one way this module fails silently.** ``root`` defaults to ``"."``, so the
store is found only if the *process's working directory* is the engagement. That is right for a
human ``cisco-assess`` run (it inherits the operator's cwd) and wrong for any wrapper that re-homes
the engine child to a scratch directory: an empty cwd has no store, ``enforce()`` takes the
brownfield branch, and **every gate returns True** — enforcement disappears with no error, no
warning that looks like a failure, and no visible difference in the output except two missing
documents. Note the asymmetry that makes this dangerous: an unreadable store fails CLOSED (loudly),
but an *unreachable* store fails OPEN (quietly). Any caller that sets ``cwd=`` on the engine child,
or ``os.chdir()``s around an in-process ``main()``, must therefore declare a posture — pass
``--gate-root``, or suppress the gated deliverables with ``--no-design --no-mop``, or disclose via
``pending_approvals()``. Being safe "because cwd happens to be empty" is a coincidence of a call
site, not a contract. Callers are inventoried in ``tests/test_gate_state.py``
(``test_no_engine_caller_declares_a_gate_posture``). A mis-set ``root`` is treated as an error, not
as an ungated engagement: ``enforce()`` REFUSES when ``root`` is not an existing directory, so one
typo cannot silently ungate a run (an *omitted* root still means cwd, unchanged).

**Ownership — what a ledger governs, DECLARED rather than inferred (ADR-0006).** ``root`` says where
a ledger is; it never said *whose* it is. A ledger may therefore carry an ``engagement`` identifier
naming what it governs, and a run may declare which engagement it is for; enforcement then VERIFIES
the two agree instead of trusting proximity:

===============  ==============  =============================================================
ledger declares  run declares    outcome
===============  ==============  =============================================================
nothing          nothing         legacy — proximity decides, gates apply UNVERIFIED (unchanged)
an id            nothing         gates apply, logged UNVERIFIED (operator is at the root)
an id            the same id     gates apply, VERIFIED
an id            a different id  **REFUSE**, and not overridable
nothing          an id           **REFUSE** — bind the ledger first (``gate_state bind``)
===============  ==============  =============================================================

The bottom two rows are the whole point: a run that declares who it is can never be answered out of
another client's ledger. Neither is overridable — ``--override-gate`` is consent to skip a KNOWN
gate, and when ownership does not check out no gate for *this* engagement has been located, so there
is nothing to consent to (identical reasoning to a mis-set ``root``). Silence stays permissive, so
every existing engagement keeps working exactly as it did.

Why the identifier is human-minted and opaque rather than derived from the evidence — three
independent reasons, each sufficient: (1) there is nothing to derive it from; the snapshot has 59
top-level sections and not one names a client or engagement, and the engine has no ``--client``
input (``ssot.canonical_facts`` yields *counts*, not identity). (2) ``--redact`` pseudonymizes IPs,
MACs and serials, so any key derived from those differs between the redacted and unredacted run of
the SAME engagement — and the redaction path is precisely where this was needed. (3) The gates span
Assess→PIR, an interval across which a migration deliberately replaces the fleet a key would be
derived from. ``collected_at`` identifies a COLLECTION (a baseline, a pre and a post are several per
engagement), not an engagement. Two proximity heuristics were built and refuted end-to-end before
this — cwd (on a USB stick, the folder every ``make_stick.ps1`` update wipes) and
walk-up-from-the-collection (which adopted a shared parent's ledger and printed engagement ACME's
approvals for a run of GLOBEX). The conclusion is not that a third heuristic would work; it is that
ownership must be declared. **Auto-discovery is not a goal**, and a future "smarter" resolver would
be re-introducing the defect. This identifier is also the token the SQLite per-wave gate board
(``webapp/backend/gates.py``) would join on: the two records stay deliberately DISTINCT — a document
approved once is a different fact from a wave signed at each T-minus, so each keeps one owner under
Law 1 — and share only this vocabulary.

**Enforcement is not always the right posture.** ``enforce()`` refuses per DELIVERABLE, which only
withholds anything if the deliverable is the sole carrier of the content. It is not, for the
design/MOP: ``COLLECT_PARSE_V3_23_0`` computes ``design_blueprint`` and writes the snapshot (:2817),
the explorer (:2831) and the executive deck (:2853) — all carrying ``target_state``/``wave_plan`` —
*before* the gates run (:2864/:2879). So on a path that emits the whole family, refusing the two
DOCX removes two renderers while the unapproved design ships anyway, and tells the operator it was
withheld. That is worse than not gating. Blocking is right where the operator is AT the engagement
and can approve or override with an audit line (the ``cisco-assess`` CLI); elsewhere prefer
``pending_approvals()`` and disclose — the same stamp-and-disclose call ``webapp/backend/gates.py``
and ``webapp/backend/deliverables.py`` already made for this product.

Gate requirements mirror the agent charters: design requires an APPROVED assessment
(.claude/agents/design-author.md — "design follows an approved assessment"); the MOP requires an
approved LLD + a captured current-state baseline (.claude/agents/mop-change-author.md — "Require an
approved LLD + current-state baseline"). Stdlib-only; no cisco_toolkit imports; deterministic; no
network. CLI: ``python -m cisco_toolkit.gate_state show | approve <gate> | revoke <gate> |
bind <engagement>``.
"""
from __future__ import annotations

import getpass
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

STORE_RELPATH = os.path.join("docs", "engagement-state.json")

# Top-level store key naming the engagement a ledger governs. APPEND-ONLY, like the gate keys: an
# absent one means "unbound (legacy)", which stays permissive, so adding it breaks no existing store.
ENGAGEMENT_KEY = "engagement"

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


def is_revoked(store: dict, gate: str) -> bool:
    """True ONLY on an explicit recorded ``revoked`` decision.

    Deliberately not the complement of ``is_approved`` — the gap between them carries the meaning.
    A gate nobody ever signed is unapproved *by silence* (it may simply be an engagement that never
    opted in); a revoked gate is a human's positive decision to WITHDRAW approval they had given.
    Only the second is strong enough to justify withholding a deliverable outright, which is what
    the MOP posture in ADR-0006 turns on."""
    rec = _gates(store).get(gate)
    return isinstance(rec, dict) and rec.get("decision") == "revoked"


def engagement_of(store: dict) -> Optional[str]:
    """The engagement this ledger declares it governs, or None when it is UNBOUND (legacy).
    A blank/whitespace/non-string value reads as unbound rather than as an engagement named ""."""
    val = store.get(ENGAGEMENT_KEY)
    return val.strip() if isinstance(val, str) and val.strip() else None


def _same_engagement(a: str, b: str) -> bool:
    """Whitespace- and case-insensitive comparison. An operator who types ``acme-2026`` where the
    ledger says ``ACME-2026`` means the same engagement, and answering that with a hard refusal
    would only teach people to stop passing ``--engagement`` at all. Values are STORED verbatim;
    only the comparison normalizes."""
    return a.strip().casefold() == b.strip().casefold()


def ownership_error(store: dict, engagement: Optional[str], what: str) -> Optional[str]:
    """None if this run may legitimately use this ledger; otherwise the text explaining why not.

    The verification half of ADR-0006 (full rule table in the module docstring). Fails CLOSED on a
    contradiction and stays silent when nothing was declared, so it can never turn an existing
    engagement off. Both refusals are non-overridable by design."""
    declared = (engagement or "").strip()
    bound = engagement_of(store)
    if not declared:
        return None                      # legacy, or an operator standing in the engagement root
    if bound is None:
        return (f"this run declares engagement {declared!r}, but the ledger records no engagement "
                f"at all -- so it cannot be confirmed to govern this one while {what}. If this "
                f"ledger really is that engagement's, bind it once with 'python -m "
                f"cisco_toolkit.gate_state bind {declared}'. Not overridable.")
    if not _same_engagement(bound, declared):
        return (f"ledger governs engagement {bound!r} but this run declares {declared!r} -- "
                f"REFUSING to answer one engagement with another's approvals while {what}. "
                f"Not overridable.")
    return None


def missing_approvals(store: dict, generator: str) -> List[str]:
    if generator not in GENERATOR_REQUIRES:
        raise ValueError(f"unknown gated generator {generator!r} "
                         f"(expected one of {sorted(GENERATOR_REQUIRES)})")
    return [k for k in GENERATOR_REQUIRES[generator] if not is_approved(store, k)]


def revoked_requirements(store: dict, generator: str) -> List[str]:
    """The generator's upstream gates a human has explicitly REVOKED — a subset of
    ``missing_approvals``, separated out because it is the only part of "missing" that represents a
    decision rather than an absence (see ``is_revoked``)."""
    if generator not in GENERATOR_REQUIRES:
        raise ValueError(f"unknown gated generator {generator!r} "
                         f"(expected one of {sorted(GENERATOR_REQUIRES)})")
    return [k for k in GENERATOR_REQUIRES[generator] if is_revoked(store, k)]


def _append_audit(path: str, store: dict, entry: dict) -> dict:
    audit = store.get("audit")
    if not isinstance(audit, list):
        audit = []
        store["audit"] = audit
    audit.append(entry)
    save_store(path, store)
    return entry


def record_decision(gate: str, decision: str, root: str = ".",
                    by: Optional[str] = None, note: str = "",
                    engagement: Optional[str] = None) -> dict:
    """Record a human gate disposition (approve/revoke). Creates the store on first use — that is
    the explicit opt-in moment that activates enforcement for the engagement in ``root``.

    ``engagement`` binds a NEW ledger to that engagement as it is created, and on an existing one is
    verified exactly as ``enforce`` verifies it. Signing is where a mis-attribution does the most
    damage — an approval landing in the wrong client's ledger both fails to gate the engagement the
    lead meant AND silently unblocks a different one — so the check applies to the write path too."""
    if gate not in GATE_KEYS:
        raise ValueError(f"unknown gate {gate!r} (expected one of {list(GATE_KEYS)})")
    if decision not in ("approved", "revoked"):
        raise ValueError(f"unknown decision {decision!r} (expected 'approved' or 'revoked')")
    root = _normalize_root(root)
    # The write side needs this MORE than the read side: save_store() calls os.makedirs, so a typo
    # here does not fail — it CREATES a phantom ledger at the wrong path and returns a success
    # receipt, while the real engagement stays unapproved. The root must already exist; only the
    # docs/ directory inside it is created (recording the first approval is the opt-in moment).
    bad_root = _require_root(root, f"recording {gate}")
    if bad_root:
        raise GateStateError(bad_root)
    store, path = load_store(root)
    if store is None:
        store = _new_store()
        if (engagement or "").strip():
            store[ENGAGEMENT_KEY] = engagement.strip()
    else:
        owner_err = ownership_error(store, engagement, f"recording {gate}")
        if owner_err:
            raise GateStateError(owner_err)
    who = by or _whoami()
    store.setdefault("gates", {})
    store["gates"][gate] = {"decision": decision, "signed_by": who,
                            "note": note, "decided_at": _now()}
    _append_audit(path, store, {"at": _now(), "who": who,
                                "event": "approve" if decision == "approved" else "revoke",
                                "gate": gate, "note": note})
    return store["gates"][gate]


def bind_engagement(engagement: str, root: str = ".", by: Optional[str] = None) -> str:
    """Declare which engagement a ledger governs — the one act that makes ownership VERIFIABLE
    instead of inferred. Creates the ledger if absent; returns the bound identifier.

    Re-binding to the same identifier is a no-op. Re-binding to a DIFFERENT one is refused: every
    approval already signed in the ledger was signed for the engagement it was bound to, and
    silently re-pointing the label would retroactively re-attribute all of them — the exact
    cross-engagement mis-attribution this whole mechanism exists to make impossible. Copy the file
    and bind the copy if handing a ledger over is genuinely what is meant."""
    ident = (engagement or "").strip()
    if not ident:
        raise ValueError("engagement identifier must be a non-empty string")
    root = _normalize_root(root)
    bad_root = _require_root(root, f"binding engagement {ident}")
    if bad_root:
        raise GateStateError(bad_root)
    store, path = load_store(root)
    if store is None:
        store = _new_store()
    bound = engagement_of(store)
    if bound is not None and not _same_engagement(bound, ident):
        raise GateStateError(
            f"ledger at {path} is already bound to engagement {bound!r}; refusing to re-bind it to "
            f"{ident!r} -- that would retroactively re-attribute every approval already signed in "
            f"it. Copy the ledger and bind the copy if you mean to hand it over.")
    store[ENGAGEMENT_KEY] = ident
    who = by or _whoami()
    _append_audit(path, store, {"at": _now(), "who": who, "event": "bind",
                                "engagement": ident,
                                "note": "re-affirmed" if bound is not None else "initial binding"})
    return ident


def _normalize_root(root: str) -> str:
    """``""`` is the argv encoding of *omitted* — ``--gate-root "$ENG_ROOT"`` with the variable
    unset, or ``cmd += ["--gate-root", cfg.get("gate_root", "")]``. It always behaved exactly like
    ``"."`` because ``store_path`` joins relatively, so refusing it would be a pure regression:
    an omitted root means the working directory, and that contract predates this module's
    hardening."""
    return root or "."


def _require_root(root: str, what: str) -> Optional[str]:
    """None if ``root`` is usable; otherwise the error text explaining why it is not.

    A root that is not an existing directory is a MIS-SET root, never an ungated engagement.
    Applied at EVERY entry point — enforcing, recording and showing — because a control hardened
    on only one of them is defeated by the same typo it exists to catch: ``record_decision`` with a
    bad root used to ``makedirs`` a phantom ledger and hand the lead a success receipt for an
    approval that landed nowhere, while the real engagement stayed unapproved."""
    if not os.path.isdir(root):
        return (f"gate root {root} is not an existing directory -- refusing to treat a mis-set "
                f"root as an ungated (brownfield) engagement while {what}. Fix the path, or omit "
                f"it to use the working directory.")
    return None


def enforce(generator: str, override_reason: Optional[str] = None,
            root: str = ".", who: Optional[str] = None,
            engagement: Optional[str] = None) -> bool:
    """Gate check for a generator run. True = proceed, False = REFUSE (caller must skip the write).

    Absent store → warn + True (brownfield). Unreadable store → error + False (not overridable —
    the override's audit line has nowhere trustworthy to land). Missing approvals → False, unless
    ``override_reason`` is non-empty, in which case an audit line (who/when/why + what was missing)
    is appended to the store and the run proceeds.

    ``engagement`` is this run's declaration of what it is FOR. Declaring nothing preserves the
    historical behaviour exactly; declaring something that the ledger contradicts (or cannot
    confirm) REFUSES, non-overridably — see the ownership table in the module docstring.
    """
    if generator not in GENERATOR_REQUIRES:
        raise ValueError(f"unknown gated generator {generator!r} "
                         f"(expected one of {sorted(GENERATOR_REQUIRES)})")
    # Not overridable. NB the reason is NOT "the audit line has nowhere to land" (save_store would
    # happily makedirs it — that is exactly the phantom-ledger bug _require_root closes): it is
    # that an override is consent to bypass a SPECIFIC gate, and with a mis-set root no gate has
    # been identified. You cannot consent to bypassing an approval you never located.
    root = _normalize_root(root)
    bad_root = _require_root(root, f"generating {generator}")
    if bad_root:
        logger.error("[GATE REFUSED] %s: %s", generator, bad_root)
        return False
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
    owner_err = ownership_error(store, engagement, f"generating {generator}")
    if owner_err:
        logger.error("[GATE REFUSED] %s: %s Store: %s", generator, owner_err, path)
        return False
    bound = engagement_of(store)
    if bound and (engagement or "").strip():
        logger.info("[gate] %s: ledger ownership VERIFIED -- engagement %s", generator, bound)
    elif bound:
        logger.warning("[gate] %s: ledger declares engagement %r but this run declares none -- "
                       "gates applied on PROXIMITY, unverified. Pass --engagement %s to verify "
                       "that this run and this ledger are the same engagement.",
                       generator, bound, bound)
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


def pending_approvals(generator: str, root: str = ".",
                      engagement: Optional[str] = None) -> Dict[str, Any]:
    """DISCLOSE the gate posture. Reads without deciding and without writing.

    The read-only counterpart to ``enforce()``, for every surface that should SURFACE the gate
    posture rather than withhold a deliverable over it — refusing a document only contains something
    when that document is the sole carrier of its content, which for the design it is not.

    Contract, and the reason this is a separate function rather than a flag on ``enforce``: it never
    writes (no audit line, no store creation — a disclosure that mutates the ledger it reports on is
    not a disclosure) and it never raises. A broken or missing ledger comes back as a *status*,
    because the callers that most need this are field paths where an exception would abort a
    deliverable the operator is standing there waiting for.

    Returns ``{generator, status, verified, engagement, declared, missing, revoked, store,
    summary}``. ``status`` is one of ``bad_root`` | ``ungated`` | ``unreadable`` |
    ``ownership_mismatch`` | ``ownership_unbound`` | ``clear`` | ``pending``. ``summary`` is a
    single line safe to print verbatim; it never claims approval it did not verify.
    """
    if generator not in GENERATOR_REQUIRES:
        raise ValueError(f"unknown gated generator {generator!r} "
                         f"(expected one of {sorted(GENERATOR_REQUIRES)})")

    declared = (engagement or "").strip() or None
    root = _normalize_root(root)
    out: Dict[str, Any] = {"generator": generator, "status": "ungated", "verified": False,
                           "engagement": None, "declared": declared, "missing": [], "revoked": [],
                           "store": store_path(root), "summary": ""}

    def _done(status: str, summary: str) -> Dict[str, Any]:
        out["status"], out["summary"] = status, summary
        return out

    try:
        if _require_root(root, f"disclosing {generator} gate state"):
            return _done("bad_root", f"gate root {root} is not a directory -- gate state unknown "
                                     f"(NOT the same as ungated).")
        try:
            store, path = load_store(root)
        except GateStateError as e:
            return _done("unreadable", f"gate ledger present but unreadable ({e}) -- gate state "
                                       f"unknown; treat approvals as UNCONFIRMED.")
        out["store"] = path
        if store is None:
            return _done("ungated", "no gate ledger for this engagement -- approvals are not "
                                    "tracked here; this deliverable is unreviewed by default.")
        bound = engagement_of(store)
        out["engagement"] = bound
        if declared and bound is None:
            return _done("ownership_unbound",
                         f"a ledger exists here but records no engagement, so it cannot be "
                         f"confirmed to govern {declared} -- approvals UNCONFIRMED.")
        if declared and bound and not _same_engagement(bound, declared):
            return _done("ownership_mismatch",
                         f"the ledger here governs {bound}, not {declared} -- reporting its "
                         f"approvals would attribute another engagement's sign-off.")
        out["verified"] = bool(declared and bound)
        out["missing"] = missing_approvals(store, generator)
        out["revoked"] = revoked_requirements(store, generator)
        scope = f"engagement {bound}" if bound else "this ledger"
        if not out["missing"]:
            qualifier = "verified" if out["verified"] else "unverified ownership"
            return _done("clear", f"all upstream approvals for the {generator} are recorded in "
                                  f"{scope} ({qualifier}).")
        if out["revoked"]:
            return _done("pending", f"approval REVOKED for {', '.join(out['revoked'])} in {scope} "
                                    f"-- the {generator} must not be treated as approved.")
        return _done("pending", f"awaiting approval of {', '.join(out['missing'])} in {scope} -- "
                                f"the {generator} is not yet approved.")
    except Exception as e:                                    # pragma: no cover - belt and braces
        # The no-raise contract is the point of this function; a bug in it must degrade to "unknown"
        # rather than take down the deliverable run that only wanted a status line.
        logger.warning("[gate] disclosure failed for %s: %s", generator, e)
        return _done("unreadable", "gate state could not be determined -- treat approvals as "
                                   "UNCONFIRMED.")


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
    p_bind = sub.add_parser("bind", help="declare which engagement this ledger governs")
    p_bind.add_argument("engagement", help="engagement identifier, e.g. ACME-2026-DC")
    p_bind.add_argument("--by", default=None, help="who bound it (default: current OS user)")
    for verb, help_txt in (("approve", "record a human gate approval"),
                           ("revoke", "revoke a previously recorded approval")):
        p = sub.add_parser(verb, help=help_txt)
        p.add_argument("gate", choices=list(GATE_KEYS))
        p.add_argument("--by", default=None, help="who signed (default: current OS user)")
        p.add_argument("--note", default="", help="optional note stored with the decision")
        p.add_argument("--engagement", default=None,
                       help="the engagement this decision is for -- binds a NEW ledger, and is "
                            "VERIFIED against an existing one (a mismatch refuses)")
    args = ap.parse_args(argv)

    if args.cmd == "bind":
        try:
            ident = bind_engagement(args.engagement, root=args.root, by=args.by)
        except (GateStateError, ValueError) as e:
            print(f"REFUSING: {e}")
            return 1
        print(f"ledger at {store_path(args.root)} governs engagement: {ident}")
        return 0

    if args.cmd in ("approve", "revoke"):
        try:
            rec = record_decision(args.gate, "approved" if args.cmd == "approve" else "revoked",
                                  root=args.root, by=args.by, note=args.note,
                                  engagement=args.engagement)
        except GateStateError as e:
            print(f"REFUSING: {e}")
            return 1
        print(f"{args.gate}: {rec['decision']} by {rec['signed_by']} at {rec['decided_at']}"
              f" -> {store_path(args.root)}")
        return 0

    # show
    bad_root = _require_root(_normalize_root(args.root), "showing the gate board")
    if bad_root:
        # The operator's one diagnostic tool must not answer a typo with "UNGATED (brownfield)" —
        # that is the exact sentence this module exists to stop anything from saying wrongly.
        print(f"REFUSING: {bad_root}")
        return 1
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
    bound = engagement_of(store)
    if bound:
        print(f"governs engagement: {bound}")
    else:
        # Not an error — legacy ledgers are permissive by design — but the operator should know the
        # board they are reading is attributed by location alone, and how to fix that.
        print("governs engagement: UNBOUND -- ownership is inferred from this directory alone. "
              "Bind it with: python -m cisco_toolkit.gate_state bind <engagement>")
    for key, label, arrow, _criteria in DOC_GATES:
        row = _gates(store).get(key)
        if isinstance(row, dict) and row.get("decision"):
            print(f"  {key:20s} [{row.get('decision'):8s}] {arrow:18s} "
                  f"by {row.get('signed_by') or '?'} at {row.get('decided_at') or '?'}")
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
