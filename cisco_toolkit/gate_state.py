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

**Every verdict is recorded structurally, not just logged** (``_VERDICTS`` / ``verdicts()``). An
OVERRIDE has always left a durable trace — the audit line it appends to the store — but a REFUSAL and
the brownfield ungated case left none: they only reached ``logging``, on a logger outside the engine's
configured tree, so they never appeared in ``cisco_migration_autofill_*.log`` and survived only as
transient stderr via ``logging.lastResort``. For a control whose overrides DEC-003 says are reviewed
weekly, the refused half must be as auditable as the overridden half. The engine seals ``verdicts()``
into the ``.run_manifest.json`` hash chain; see ``COLLECT_PARSE_V3_23_0.build_run_manifest``.
**Both dispositions are audited, not just the unsafe one.** ``enforce()`` returns a ``GateVerdict``
rather than a bool, and a REFUSAL over MISSING APPROVALS -- the refusal this control exists to make,
and the only one that means a located gate said no -- appends a durable ``refuse`` row to the same
``audit`` array the override writes to. Before this, only the override left a trace: the
control's *safe* path was its least accountable one, an absent ``design.docx`` was indistinguishable
from a ``--no-design`` run, and the engine exited 0 either way. The audit array is the right home
rather than the per-run ``.run_manifest.json`` — a refusal provokes a re-run, and a per-run seal is
overwritten by exactly that. The manifest may cache a copy, but must cite this array as its owner
(Law 1). The other five statuses are NOT recorded -- three cannot be (nowhere to write, or writing
would destroy evidence / enrol an unenrolled engagement) and two must not be (the ledger governs
another engagement) -- and they report ``GateVerdict.recorded=False`` rather than pretending
(``_record_refusal`` enumerates all five). The ledger therefore grows by one row per refused deliverable per
run; ``show`` counts them beside the overrides and tails the last ten.

**Root resolution — the one way this module fails silently.** ``root`` defaults to ``"."``, so the
store is found only if the *process's working directory* is the engagement. That is right for a
human ``cisco-assess`` run (it inherits the operator's cwd) and wrong for any wrapper that re-homes
the engine child to a scratch directory: an empty cwd has no store, ``enforce()`` takes the
brownfield branch, and **every gate returns True** — enforcement disappears with no error, no
warning that looks like a failure, and **no visible difference in the output at all**: both gated
documents are produced exactly as if they had been approved. (Two MISSING documents is the
signature of enforcement working, not of it failing — do not use absence as the tell.) Note the
asymmetry that makes this dangerous: an unreadable store fails CLOSED (loudly), but an
*unreachable* store fails OPEN (quietly). Any caller that sets ``cwd=`` on the engine child, or
``os.chdir()``s around an in-process ``main()``, must therefore declare a posture — pass
``--gate-root``, or suppress the gated deliverables with ``--no-design --no-mop``, or be listed in
the guard's documented exemptions, or DISCLOSE the posture with
``pending_approvals()`` (below) instead of withholding. Being safe "because cwd happens to be empty" is a coincidence of a call
site, not a contract. Callers are inventoried in ``tests/test_gate_state.py``
(``test_no_engine_caller_declares_a_gate_posture``). A mis-set ``root`` is treated as an error, not
as an ungated engagement: every entry point REFUSES when ``root`` is not an existing directory (an
*omitted* root still means cwd, unchanged). Scope that honestly — it catches a path that does not
exist, NOT a wrong-but-existing one: ``--gate-root D:/Engagements`` when the engagement is
``D:/Engagements/ACME`` still reads as brownfield and ungates everything. Closing that needs the
ledger to declare what it governs — which is exactly what the ownership model below adds.

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
DOCX removes two renderers while the unapproved design ships anyway. Blocking is right where the
operator is AT the engagement and can approve or override with an audit line (the ``cisco-assess``
CLI, which also PRINTS the refusal); it is weaker on a wrapper that emits the whole family and
surfaces no gate output, where a refusal is a silent two-file omission. That is what
``pending_approvals()`` is for — the DISCLOSING counterpart to ``enforce()``, for surfaces that
should surface the posture rather than withhold a deliverable over it. Note what it is NOT built
on: ``missing_approvals(store, generator)`` is a pure computation over an already-loaded store, not
a reporting posture, and neither ``webapp/backend/gates.py`` nor ``webapp/backend/deliverables.py``
is precedent for it (``deliverables.py``'s ``_reconcile_gate`` is an SSOT-drift warning, and
``gates.py`` works the per-wave axis) — an earlier draft of this note cited both and was wrong.

Gate requirements mirror the agent charters: design requires an APPROVED assessment
(.claude/agents/design-author.md — "design follows an approved assessment"); the MOP requires an
approved LLD + a captured current-state baseline (.claude/agents/mop-change-author.md — "Require an
approved LLD + current-state baseline"). Stdlib-only; no cisco_toolkit imports; deterministic; no
network. CLI: ``python -m cisco_toolkit.gate_state show | approve <gate> | revoke <gate> |
bind <engagement>``.
"""
from __future__ import annotations

import copy
import getpass
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

STORE_RELPATH = os.path.join("docs", "engagement-state.json")

#: In-process ledger of the gate verdicts reached during THIS run — the STRUCTURAL half of the audit
#: trail. Before this existed, a refusal left nothing durable at all: verdicts went only to
#: ``logging``, on a logger the engine had not configured, while an OVERRIDE did persist (it appends
#: an audit line to the store) — the asymmetry that made refusals invisible after the fact. Now
#: ``enforce()`` appends one row per decision here, the engine seals the ledger into
#: ``.run_manifest.json``'s hash chain (``COLLECT_PARSE_V3_23_0.build_run_manifest``), AND the log
#: itself reaches that log file. Sealed row and log line are complementary — the row is
#: tamper-evident but end-of-run, the line is editable but immediate.
#:
#: Rows carry generator/verdict/missing/reason and NOT who/when. The reason is SSOT, not determinism:
#: the store's audit line is the one owner of who/when for an override, and this ledger cites it
#: rather than copying it (Law 1). Do not restate the omission as a determinism requirement — a run
#: manifest's ``chain_root`` already varies between otherwise-identical runs, because the sealed
#: ``deliver`` step carries artifact NAMES and the default output filename embeds a wall-clock stamp.
#: The real contract ``manifest.py`` guarantees is narrower: ``hash_chain`` is a pure function of the
#: steps list. Known limit of citing rather than copying: the store is not itself sealed, so deleting
#: it leaves an "overridden" row whose who/when is unrecoverable.
#:
#: Appended from the main thread only (the engine gates deliverables sequentially, after collection).
_VERDICTS: List[dict] = []

# NB: a separate flat ``VERDICTS`` enum used to live here ("approved"/"refused"/"refused_no_reason"
# /"refused_unreadable"/"overridden"/"ungated"). It was RETIRED when #439 landed: ``STATUSES``
# (defined below, beside ``UNEVALUATED``) is the ONE vocabulary shared by ``enforce``,
# ``pending_approvals`` and the sealed ledger, and a second enum for the same situations is the
# copy-that-drifts Law 1 exists to prevent. A sealed row reports the disposition as
# ``verdict`` (a STATUS) plus an explicit ``proceed``; an override additionally carries ``reason``.


def _record(generator: str, verdict: str, missing: Optional[List[str]] = None, **extra) -> dict:
    """``missing=None`` means the approvals were NEVER EVALUATED (no store, or an unreadable one) —
    deliberately distinct from ``[]``, which means "evaluated, nothing missing", so that counting
    missing approvals across rows cannot silently score a never-checked run as a clean zero.
    ``verdict`` remains the authoritative discriminator; ``missing`` only qualifies it. (This is the
    same *concern* ``ssot.abstention_reason`` addresses — not-observed must never render as healthy —
    but NOT the same mechanism: that function returns an enumerated token, never a nullable. Here the
    enumerated token is ``verdict`` itself, and ``missing`` is its optional detail.)"""
    row = {"generator": generator, "verdict": verdict,
           "missing": None if missing is None else list(missing)}
    row.update(extra)
    _VERDICTS.append(row)
    return row


def verdicts() -> List[dict]:
    """A DEEP copy of this run's gate-verdict ledger, in decision order. Empty means NO gate decision
    was made (e.g. ``--no-design --no-mop``) — coverage-honest: it must never be read as "gates
    passed". The copy is deep (not just the top level, and not just ``missing``) because this is the
    only read path to the audit source: a caller that sorted or normalised any nested value in place
    would otherwise rewrite the record about to be sealed."""
    return copy.deepcopy(_VERDICTS)


def reset_verdicts() -> None:
    """Clear the ledger, so one run's verdicts can never be sealed into the next run's manifest.
    The hosts that actually run ``main()`` twice in one process are the in-process pipeline tests
    (``tests/test_pipeline_inprocess.py``, ``tests/test_pipeline_failopen.py``); the webapp drives the
    engine as a SUBPROCESS and ``serve.py``'s ``--run-engine`` sentinel dispatches exactly once."""
    _VERDICTS.clear()
#: Every gate posture this module can report — the ONE vocabulary, shared verbatim by the deciding
#: path (``enforce``) and the disclosing path (``pending_approvals``). Law 1 applied to a taxonomy:
#: a second enum for "the same seven situations, as seen by the enforcer" is a copy that drifts, and
#: the two surfaces would then disagree about the same ledger. ``tests/test_gate_state.py`` pins that
#: neither function can emit a status outside this tuple. APPEND-ONLY (statuses reach the audit
#: ledger on disk, and a renamed one orphans the rows already written).
STATUSES = ("bad_root", "ungated", "unreadable", "ownership_mismatch",
            "ownership_unbound", "clear", "pending")

#: The statuses that mean the approvals were NEVER EVALUATED — no ledger was located, or the one
#: located could not be read or could not be confirmed to govern this run. Kept explicit because the
#: distinction is the coverage-honesty rule (D3) applied to governance: ``missing == ()`` on one of
#: these means "unknown", never "nothing missing". ``status`` is the discriminator that carries it,
#: which is why ``GateVerdict.missing`` does not need to be nullable.
UNEVALUATED = ("bad_root", "ungated", "unreadable", "ownership_mismatch", "ownership_unbound")

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


@dataclass(frozen=True)
class GateVerdict:
    """What ``enforce()`` DECIDED — returned so that no caller ever re-derives the decision.

    ``enforce`` used to return a bare ``bool``, which left every downstream consumer to reconstruct
    *why* from the inputs. That reconstruction is where the previous attempt at this feature failed:
    it inferred "overridden" from the presence of ``--override-gate``, but an override is INERT on an
    already-approved ledger (``enforce`` returns at its "approvals present" branch without appending
    an audit line), so it manufactured a governance breach that never happened. Every field here is
    therefore an observation of what the run actually did, not a re-computation:

    * ``proceed`` — the boolean that really governed the deliverable. ``bool(verdict)`` is exactly
      this, so the historical ``if not args.no_design and gate_enforce(...)`` call shape keeps
      working unchanged.
    * ``status`` — the ledger posture, from ``STATUSES``, the SAME vocabulary ``pending_approvals``
      reports (deciding and disclosing cannot disagree about one ledger).
    * ``overridden`` — True only where the override audit line was actually appended. It is set at
      that one site, so it cannot claim a breach the ledger has no line for.
    * ``recorded`` — whether this verdict's audit row reached the DURABLE ledger. Coverage-honest:
      several statuses legitimately cannot be recorded (see ``_record_refusal``), and a caller must
      be able to tell "refused and written down" from "refused, nothing persisted" rather than
      assume the write happened.
    """

    generator: str
    status: str
    proceed: bool
    overridden: bool = False
    missing: Tuple[str, ...] = ()
    recorded: bool = False
    store: str = ""
    detail: str = ""

    def __bool__(self) -> bool:
        """The decision itself — never a re-derivation, just the field that governed the run."""
        return self.proceed

    @property
    def refused(self) -> bool:
        return not self.proceed

    @property
    def evaluated(self) -> bool:
        """False when no ledger could be read, so ``missing == ()`` means UNKNOWN, not "none"."""
        return self.status not in UNEVALUATED


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
    """Atomic write (unique same-dir temp + os.replace) so a crash mid-write, OR a second writer,
    can never corrupt the audit ledger.

    The temp name must be UNIQUE, not ``path + ".tmp"``. With a fixed name two writers to one ledger
    share a single scratch file: on Windows the CRT opens it share-deny-none, so their bytes
    interleave and one ``os.replace`` then promotes the interleaved garbage to *be* the ledger —
    reproduced as ``Extra data: line 1 column 45``, after which ``load_store`` raises forever, every
    gate refuses, and (correctly) nothing can append to it again. There are no backups for this
    store, so that is the whole engagement's approval history gone. The fixed name predates the
    refusal record, but recording refusals is what moved writing from "a human occasionally runs
    approve/revoke" to "twice per assessment run", which is what makes concurrent writers realistic
    (two runs of one engagement, a CI fleet, an operator approving while a long run is in flight).

    On failure the temp is removed rather than left beside the ledger: an orphan is a full COPY of an
    audit trail, holding a row the real ledger does not, in the engagement's own docs/ folder.

    NB deliberately NO in-place fallback when ``os.replace`` cannot take the destination (Windows,
    any open handle — a reviewer with the ledger in an editor). Failing and reporting it is right
    here: truncate-and-rewrite is exactly how an audit ledger gets destroyed, and the caller already
    degrades safely (``_record_refusal`` → ``recorded=False``, loudly; the deliverable stays
    withheld). That is the opposite trade-off from ``manifest.py``, whose seal is regenerable.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".",
                               prefix=os.path.basename(path) + ".", suffix=".tmp")
    promoted = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(store, f, indent=2, sort_keys=False)
            f.write("\n")
            f.flush()
            # The rename can otherwise be durable while the CONTENT is not: a power loss then leaves
            # a short or zero-length ledger, which json.load rejects -> permanently "unreadable" and
            # never re-appendable. Same class as the 0-byte-DB-passes-quick_check defect.
            os.fsync(f.fileno())
        os.replace(tmp, path)
        promoted = True
    finally:
        if not promoted:
            try:
                os.remove(tmp)
            except OSError:                          # pragma: no cover - best-effort cleanup
                pass


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
    """Append one row to the ledger's audit array and persist it.

    A PRESENT but non-list ``audit`` is a corrupt ledger and REFUSES, rather than being replaced with
    a fresh list. Discarding it silently destroyed an audit trail and then reported success: a ledger
    whose ``audit`` is a JSON object still loads (``load_store`` validates only the top level), so it
    reaches this path, and the ``show`` CLI's ``isinstance(a, dict)`` filter iterates such a value's
    KEYS and drops them all — printing "audit: 0 entries" both before and after, so the destruction
    is invisible from the operator's only diagnostic tool. This is the same principle the unreadable
    branch already applies (a corrupt ledger is EVIDENCE, never something to overwrite); a PARTIALLY
    corrupt one had the opposite treatment. An ABSENT key is not corruption — older stores predate
    it, so it is still created.
    """
    if "audit" in store and not isinstance(store["audit"], list):
        raise GateStateError(
            f"gate-state store {path} has a corrupt 'audit' value of type "
            f"{type(store['audit']).__name__} (expected a list) -- refusing to overwrite it, since "
            f"that would destroy whatever audit trail it holds. Repair or archive the file by hand.")
    audit = store.get("audit")
    if not isinstance(audit, list):
        audit = []
        store["audit"] = audit
    audit.append(entry)
    save_store(path, store)
    return entry


def _record_refusal(path: str, store: dict, generator: str, status: str,
                    missing: List[str], detail: str, who: Optional[str] = None,
                    declared: Optional[str] = None) -> bool:
    """Append the durable ``refuse`` line for a withheld deliverable. True if the write completed
    (``os.replace`` returned after an fsync of the contents).

    This closes the asymmetry that made the gate's SAFE path its least auditable one: proceeding
    despite a missing approval has always appended a who/when/why line, while REFUSING wrote nothing
    anywhere, so an absent ``design.docx`` was indistinguishable from a ``--no-design`` run. The
    ledger's ``audit`` array is the right home rather than the per-run manifest, because a refusal
    provokes exactly one natural response — re-run — and a per-run seal is overwritten by it. Here
    the row outlives every re-run, and ``save_store``'s tmp+replace keeps the append atomic.

    **Takes the already-loaded ``(path, store)``, never a root.** Its sibling ``enforce()`` resolves
    and validates the root, so a second resolution here could disagree with the one that made the
    decision — and a ``root="."`` default would resolve to whatever cwd the caller happened to have,
    which on the ``--redact-folder`` path is a ``mkdtemp`` scratch directory. That defect shipped
    once (a record written against the wrong root claimed a posture the real ledger contradicted);
    the fix is structural — there is no root argument to get wrong.

    Only ``pending`` refusals reach here. The other statuses deliberately do not, and
    ``GateVerdict.recorded`` stays False so the gap is visible rather than assumed:

    * ``bad_root`` — the directory does not exist; there is nowhere to write, and creating one is the
      phantom-ledger bug ``_require_root`` exists to close.
    * ``unreadable`` — the ledger is corrupt. Rewriting it would destroy the evidence of the
      corruption, and ``save_store`` serialises the parsed dict we never got.
    * ``ungated`` — no ledger at all, and this is not a refusal anyway (brownfield proceeds).
      Writing here would CREATE a store, and the first write is the opt-in that activates
      enforcement for the engagement — a run must never silently gate an engagement nobody enrolled.
    * ``ownership_mismatch`` / ``ownership_unbound`` — the ledger is readable, so a row *could* be
      written, and must not be: it governs another engagement and this run has no standing to append
      to it (test_ownership_refusals_are_not_overridable_and_write_nothing).

    A failed write is reported, never fatal: the deliverable is already withheld (the safe outcome),
    so aborting the run over the bookkeeping would turn a working refusal into a crash. ``OSError``
    only — a locked or read-only ledger is the realistic failure (``os.replace`` raises it on Windows
    while any process holds the file); anything else is a bug that should surface.
    """
    # The row names WHICH ENGAGEMENT it is about, not just which generator. Ownership is verified
    # only when the run DECLARES itself (`ownership_error` returns None when `engagement` is empty),
    # so on the default path gates are applied by PROXIMITY -- and a mis-rooted run now WRITES to
    # the ledger it landed next to, where before it only read. An un-attributable row in the wrong
    # client's ledger is indistinguishable from a real one during the DEC-003 weekly review, so both
    # sides are recorded: what the ledger says it governs, and what (if anything) the run claimed.
    # `declared: None` is itself the signal that this row was matched by location alone.
    entry = {"at": _now(), "who": who or _whoami(), "event": "refuse",
             "generator": generator, "status": status,
             "engagement": engagement_of(store), "declared": (declared or "").strip() or None,
             "missing": list(missing), "reason": detail}
    try:
        _append_audit(path, store, entry)
    except (OSError, GateStateError, RecursionError) as e:
        # Narrow and enumerated, never a bare `except Exception` (that class of catch is what let an
        # earlier attempt seal "approved" over a swallowed ValueError). OSError: a locked/read-only
        # ledger, the realistic Windows case. GateStateError: _append_audit refusing to overwrite a
        # corrupt audit array. RecursionError: json.dump(indent=...) uses the pure-Python encoder,
        # whose depth limit is LOWER than the C scanner json.load accepted -- so a deeply nested
        # ledger loads and then fails to re-serialise. All three are properties of the FILE, not
        # bugs here, and none of them should turn a correct refusal into a crashed run.
        logger.error("[gate] the %s refusal could NOT be recorded in %s (%s: %s) -- the deliverable "
                     "is still withheld, but this refusal leaves no durable trace; fix the ledger's "
                     "permissions/contents or close whatever holds it open",
                     generator, path, type(e).__name__, e)
        return False
    return True


def record_decision(gate: str, decision: str, root: str = ".",
                    by: Optional[str] = None, note: str = "",
                    engagement: Optional[str] = None) -> dict:
    """Record a human gate disposition (approve/revoke). Creates the store on first use — that is
    the explicit opt-in moment that activates enforcement for the engagement in ``root``.

    ``root`` must ALREADY EXIST; only the ``docs/`` directory inside it is created. Creating the
    root too would mean a typo silently produces a phantom ledger plus a success receipt, so
    ``mkdir`` the engagement first (raises ``GateStateError`` otherwise).

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
    hardening.
    Only the empty STRING gets that treatment. ``None``/``0``/``b""`` are not "omitted",
    they are a caller bug: coercing them to cwd reaches the phantom-ledger outcome
    ``_require_root`` exists to stop, by a bad TYPE instead of a bad path.
    """
    if root is None or not isinstance(root, (str, os.PathLike)):
        raise TypeError(f"gate root must be a path string, got {type(root).__name__}: {root!r}")
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


def _emit(v: GateVerdict) -> GateVerdict:
    """The ONE exit for :func:`enforce` — seal the disposition into the per-run ledger (so the
    engine can chain it into ``.run_manifest.json``) and hand the caller the verdict. Producing
    both from a single object is the point: a row and a return value built at separate sites can
    disagree about the same decision, which is precisely the drift
    ``test_enforce_and_pending_approvals_share_one_status_vocabulary`` exists to forbid.

    ``missing`` is NULLABLE ON PURPOSE: ``None`` = the approvals were NEVER EVALUATED, ``[]`` =
    evaluated and nothing was missing. Those must not collapse (``list(v.missing) or None`` would
    report a clean evaluated run as never-checked), so the nullable is derived from ``UNEVALUATED``
    — the status set that encodes the same distinction on the verdict side.

    ``store`` and ``detail`` are deliberately NOT sealed: the store is an ABSOLUTE PATH and detail
    can embed one, so sealing either makes ``chain_root`` vary run-to-run for identical inputs and
    destroys the determinism the seal depends on (pinned by
    ``test_sealed_gate_step_is_deterministic``). The same reasoning already kept ``who``/``at`` out.
    The one human-supplied string that IS sealed is the override ``reason`` — it is the point of the
    override audit line, and it is caller-provided rather than environment-derived."""
    extra = {"reason": v.detail} if v.overridden else {}
    _record(v.generator, v.status,
            None if v.status in UNEVALUATED else list(v.missing),
            proceed=v.proceed, **extra)
    return v


def enforce(generator: str, override_reason: Optional[str] = None,
            root: str = ".", who: Optional[str] = None,
            engagement: Optional[str] = None) -> GateVerdict:
    """Gate check for a generator run. Returns a :class:`GateVerdict`; truthy = proceed, falsy =
    REFUSE (the caller must skip the write). ``if gate_enforce(...)`` therefore reads exactly as it
    did when this returned a bare ``bool`` — the object carries WHY alongside the same decision, so
    no caller has to reconstruct it (see ``GateVerdict`` for the defect that reconstruction caused).

    Absent store → warn + proceed (brownfield). Unreadable store → error + refuse (not overridable —
    the override's audit line has nowhere trustworthy to land). Missing approvals → refuse, unless
    ``override_reason`` is non-empty, in which case an audit line (who/when/why + what was missing)
    is appended to the store and the run proceeds.

    A refusal over MISSING APPROVALS also appends a durable ``refuse`` line, so the withheld
    deliverable is as auditable as the overridden one — the whole point of ``_record_refusal``,
    whose docstring enumerates the five statuses that are NOT recorded (two of which have a
    perfectly readable ledger in reach and deliberately decline to write to it). Check
    ``GateVerdict.recorded`` before telling anyone a refusal was written down.

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
        return _emit(GateVerdict(generator, "bad_root", False, store=store_path(root), detail=bad_root))
    try:
        store, path = load_store(root)
    except GateStateError as e:
        logger.error("[GATE REFUSED] %s: %s -- fix or remove the store; "
                     "--override-gate cannot bypass an unreadable ledger", generator, e)
        return _emit(GateVerdict(generator, "unreadable", False, store=store_path(root), detail=str(e)))
    if store is None:
        logger.warning("[gate] no gate-state store at %s -- %s generation proceeds UNGATED "
                       "(brownfield). Activate PPDIOO gate enforcement with: "
                       "python -m cisco_toolkit.gate_state approve <gate>", path, generator)
        return _emit(GateVerdict(generator, "ungated", True, store=path,
                           detail="no gate ledger -- brownfield, proceeding ungated"))
    owner_err = ownership_error(store, engagement, f"generating {generator}")
    if owner_err:
        logger.error("[GATE REFUSED] %s: %s Store: %s", generator, owner_err, path)
        # Deliberately NOT recorded, and this is the one place where that costs something real (the
        # ledger is readable, so a row COULD be written). It must not be: this ledger belongs to
        # another engagement, and a run declaring a different one has no standing to append to it —
        # pinned by test_ownership_refusals_are_not_overridable_and_write_nothing. Letting any run
        # write here by declaring a mismatching --engagement would also make every ledger in reach
        # append-able by an unrelated run. The evidence lives in the refusing run's log and in the
        # returned verdict; the innocent engagement's audit trail stays clean.
        status = "ownership_unbound" if engagement_of(store) is None else "ownership_mismatch"
        return _emit(GateVerdict(generator, status, False, store=path, detail=owner_err))
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
        # Reached WITHOUT consulting override_reason, and the verdict says so: overridden=False on
        # an approved ledger even when --override-gate was passed. A redundant override is inert
        # (test_approved_upstream_proceeds_and_override_is_inert), and a record that inferred
        # "overridden" from the flag here would assert a breach with no audit line behind it.
        return _emit(GateVerdict(generator, "clear", True, store=path,
                           detail="upstream approvals present"))
    if override_reason is not None and override_reason.strip():
        actor = who or _whoami()
        # NOT wrapped in _record_refusal's tolerant OSError handling, and deliberately so: do not
        # "make this consistent" later. A refusal has already withheld the deliverable, so a failed
        # write costs only bookkeeping and degrades to recorded=False. An override is the opposite —
        # the audit line is the ONLY thing that makes proceeding past a missing approval legitimate,
        # so if it cannot be written the run must not quietly generate the document anyway. Letting
        # the OSError propagate is the fail-closed choice.
        _append_audit(path, store, {"at": _now(), "who": actor, "event": "override",
                                    "generator": generator, "missing": missing,
                                    "reason": override_reason.strip()})
        logger.warning("[GATE OVERRIDDEN] %s generated despite missing approval(s) %s -- "
                       "who=%s reason=%r (audit line appended to %s)",
                       generator, ", ".join(missing), actor, override_reason.strip(), path)
        # overridden=True is set HERE, at the one site that appended the line, so the verdict and
        # the ledger can never disagree about whether an override happened.
        return _emit(GateVerdict(generator, "pending", True, overridden=True, missing=tuple(missing),
                           recorded=True, store=path, detail=override_reason.strip()))
    if override_reason is not None:
        detail = ("--override-gate requires a non-empty reason "
                  "(the who/when/why audit line is the point of the override)")
        logger.error("[GATE REFUSED] %s: %s", generator, detail)
        ok = _record_refusal(path, store, generator, "pending", missing, detail, who,
                             declared=engagement)
        return _emit(GateVerdict(generator, "pending", False, missing=tuple(missing),
                           recorded=ok, store=path, detail=detail))
    detail = ("missing upstream approval(s): "
              + ", ".join(f"{k} ({GATE_LABELS[k]})" for k in missing))
    logger.error("[GATE REFUSED] %s: %s. Record the human gate with "
                 "'python -m cisco_toolkit.gate_state approve <gate> --by <name>', or override "
                 "explicitly with --override-gate \"<reason>\" (audited). Store: %s",
                 generator, detail, path)
    ok = _record_refusal(path, store, generator, "pending", missing, detail, who,
                             declared=engagement)
    return _emit(GateVerdict(generator, "pending", False, missing=tuple(missing),
                       recorded=ok, store=path, detail=detail))


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
            # The WRITE side is the one that most needs a clean answer: a mis-set root here used to
            # create a phantom ledger. It must not now answer with a raw traceback while `show`
            # answers the same mistake with a sentence.
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
    # Refusals are counted beside overrides because they are the same control seen from its other
    # side: an override says a gate was bypassed, a refusal says a deliverable was withheld. Showing
    # only the first made the board mute about every run the gates actually stopped.
    refusals = [a for a in audit if a.get("event") == "refuse"]
    print(f"audit: {len(audit)} entries ({len(overrides)} override(s) -- review weekly, DEC-003; "
          f"{len(refusals)} refusal(s) -- deliverables withheld)")
    for a in audit[-10:]:
        flag = ""
        if a.get("event") == "override":
            flag = " **OVERRIDE**"
        elif a.get("event") == "refuse":
            flag = " **REFUSED**"
        what = a.get("gate") or a.get("generator") or "?"
        why = a.get("reason") or a.get("note") or ""
        print(f"  {a.get('at', '?')}  {a.get('event', '?'):8s} {what:12s} "
              f"by {a.get('who', '?')}  {why}{flag}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
