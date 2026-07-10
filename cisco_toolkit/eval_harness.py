"""Golden-snapshot eval harness — the deterministic scorer behind the *feedback nerve*.

Phase 0 of ``docs/autonomous-brain-plan-v4-final-2026-07-06.md``: until a deliverable's quality is a
falsifiable *number* rather than a self-assessment, "improvement" is unfalsifiable and nothing
downstream can be trusted to compound. This module scores a **fixed known-good deliverable** (its
snapshot substrate, and — when supplied — its rendered document text) against **deterministic,
offline, no-egress** checks, so a regression drops the score *before* release.

What it verifies — **verifiable facts only, never an opinion**:

* **SSOT reconcile clean (Law 1)** — ``ssot.reconcile(snap) == []`` with ≥1 canonical fact actually
  published (a reconcile that is empty only because *nothing was published* is a coverage-honest
  SKIP, not a pass).
* **Citations byte-match (Law 1 / provenance)** — every published headline fact's value byte-matches
  an independent re-read of its own cited canonical path (``fact_lineage`` integrity), and — on the
  rendered tier — the document's self-verification badge reports the *same* fact count the machine
  does.
* **The machine-checkable Deliverable-Excellence Laws present** — the subset the *repo* grounds in
  real signals (**L1, L2, L3, L6, L8, L9, L10**). The full ten-Law Standard is owned OUTSIDE this
  repo (the Deliverable Excellence Kit — see ``docs/ssot.md``); Laws with no repo machine signal are
  reported **UNVERIFIED**, never silently counted as passed. This harness therefore reports
  "N machine-checkable Laws verified", never a blanket "10/10".

Coverage-honesty is the load-bearing invariant (Law 3, turned on our own scoring): a check whose
*evidence is absent* is ``unverified`` — it is excluded from the score's denominator and disclosed,
**never rendered green**. A minimal/partial snapshot scores over what it can prove, with the
unproven checks named, rather than a false 100.

Tiering (``docs/quality/README.md``): the snapshot-only checks are the **smoke** set (fast, hermetic
— run on every change by the ``verify-green`` gate); passing ``texts=`` (rendered document text)
additionally evaluates the **render** checks — the **full** set, run on release.

Pure: stdlib + ``cisco_toolkit.ssot`` only. No I/O, no network, no device access, no dates.
"""
from __future__ import annotations

import dataclasses
import re
from typing import Any, Dict, List, Optional

from cisco_toolkit import ssot

# The machine-checkable Laws this harness grounds in a real repo signal, with the short name the
# repo uses for each. This is NOT the full Standard (ten Laws, owned by the external Deliverable
# Excellence Kit — docs/ssot.md); it is the subset with a deterministic in-repo signal. Kept as an
# explicit registry so the coverage claim ("which Laws are machine-verified") is itself auditable.
GROUNDED_LAWS: Dict[str, str] = {
    "L1": "Single source of truth (reconcile + citations byte-match)",
    "L2": "Document control / provenance",
    "L3": "Coverage honesty (accounting)",
    "L6": "Answer-first at-a-glance register",
    "L8": "Coverage-honest [NOT OBSERVED] on absence",
    "L9": "Inputs-required register",
    "L10": "Independent self-verification badge",
}

# The rendered self-verification badge docmeta.add_excellence_front emits (docmeta.py): the number
# right before this phrase must byte-match ssot.summary(snap)['n_facts'].
_BADGE_COUNT_RE = re.compile(r"(\d+)\s+headline figures self-verified")

_PASS = "pass"
_FAIL = "fail"
_UNVERIFIED = "unverified"


@dataclasses.dataclass
class CheckResult:
    """One deterministic check. ``status`` is exactly one of ``pass`` / ``fail`` / ``unverified``.
    ``unverified`` means the *evidence was absent* — the check could be neither confirmed nor
    refuted — and is excluded from the score (coverage-honest), never treated as a pass."""
    check_id: str
    law: str
    status: str
    detail: str


@dataclasses.dataclass
class ScoreResult:
    """The aggregate verdict over a deliverable. ``score`` is the percentage of *applicable*
    (pass|fail) checks that passed — ``None`` when nothing was applicable (an empty deliverable
    scores ``None`` with reasons, never 100). ``laws_tripped`` feeds the scorecard directly."""
    score: Optional[int]
    checks: List[CheckResult]
    laws_verified: List[str]
    laws_tripped: List[str]
    laws_unverified: List[str]
    counterexamples: int
    n_applicable: int
    n_passed: int

    @property
    def clean(self) -> bool:
        """True iff at least one check was applicable and none failed."""
        return self.n_applicable > 0 and not self.laws_tripped

    def to_scorecard_row(self, *, deliverable: str, commit: str, date: str,
                         notes: str = "") -> Dict[str, Any]:
        """Project onto the append-only scorecard schema (docs/quality/README.md). ``verdict`` is
        BLOCK iff any check failed (a grounded defect), else APPROVE. ``score`` is the eval number
        (may be ``None`` for an empty deliverable — reported as absence, never a fabricated 0)."""
        if not notes:
            if self.laws_tripped:
                first_fail = next((c for c in self.checks if c.status == _FAIL), None)
                notes = f"eval: {first_fail.detail}" if first_fail else "eval: defect(s) found"
            else:
                notes = (f"eval: {self.n_passed}/{self.n_applicable} checks pass"
                         f"{f'; {len(self.laws_unverified)} law(s) unverified (evidence absent)' if self.laws_unverified else ''}")
        row = {
            "date": date,
            "deliverable": deliverable,
            "score": self.score,
            "verdict": "BLOCK" if self.counterexamples else "APPROVE",
            "judge_tnr": None,       # deterministic checks — there is no judge to measure (bias-free)
            "provisional": None,     # derived below via THE predicate (never a second computation)
            "counterexamples": self.counterexamples,
            "laws_tripped": self.laws_tripped,
            "commit": commit,
            "notes": notes,
            "authored_by": None,     # deterministic harness — no provenance pair to declare (P0-2 keys, honest null)
            "reviewed_by": None,
        }
        # P0-6: a scored row is never provisional (no judge); an APPROVE with score=None (nothing was
        # applicable) quantifies nothing and honestly marks itself advisory rather than gate-worthy.
        from cisco_toolkit.scorecard import is_provisional
        row["provisional"] = is_provisional(row)
        return row


# --- individual checks -------------------------------------------------------------------------
# Each returns a list of CheckResult. Convention: return `fail` ONLY when the evidence is present
# AND wrong; `pass` only when present AND right; `unverified` when the evidence is absent.

def _coerce_like_canonical(name: str, raw: Any) -> Any:
    """Mirror how ssot.canonical_facts coerces a raw path value, so a citation comparison is
    apples-to-apples (every fact int-coerced except the string ``worst_band``)."""
    return raw if name == "worst_band" else ssot._as_int(raw)


def _check_reconcile(snap: Dict[str, Any]) -> List[CheckResult]:
    summ = ssot.summary(snap)
    n_facts = summ.get("n_facts", 0)
    if not n_facts:
        return [CheckResult("ssot.reconcile", "L1", _UNVERIFIED,
                            "no canonical facts published - nothing to reconcile (coverage-honest skip)")]
    violations = ssot.reconcile(snap)
    if violations:
        return [CheckResult("ssot.reconcile", "L1", _FAIL,
                            f"{len(violations)} SSOT violation(s): " + "; ".join(violations[:3]))]
    return [CheckResult("ssot.reconcile", "L1", _PASS,
                        f"{n_facts} canonical fact(s) reconcile to the raw evidence")]


def _check_citations_provenance(snap: Dict[str, Any]) -> List[CheckResult]:
    """Every PUBLISHED headline fact must byte-match an independent re-read of its own cited
    canonical path, and carry a non-empty basis (a claim with a working source)."""
    lineage = ssot.compute_fact_lineage(snap).get("facts", [])
    published = [f for f in lineage if f.get("state") == "published"]
    if not published:
        return [CheckResult("citations.provenance", "L1", _UNVERIFIED,
                            "no published headline facts to cite")]
    bad = []
    for f in published:
        raw = ssot._dotted(snap, f.get("path", ""))
        matches = raw is not None and str(f.get("value")) == str(_coerce_like_canonical(f.get("name", ""), raw))
        if not matches or not str(f.get("basis") or "").strip():
            bad.append(f"{f.get('name')} shows {f.get('value')!r} but cites {f.get('path')}={raw!r}")
    if bad:
        return [CheckResult("citations.provenance", "L1", _FAIL,
                            f"{len(bad)} citation(s) do not byte-match their source: " + "; ".join(bad[:3]))]
    return [CheckResult("citations.provenance", "L1", _PASS,
                        f"{len(published)} headline fact(s) byte-match their cited source path")]


def _check_citations_rendered(snap: Dict[str, Any], texts: Optional[str]) -> List[CheckResult]:
    """The rendered self-verification badge's fact count must byte-match ssot.summary(snap)."""
    if texts is None:
        return [CheckResult("citations.rendered", "L1", _UNVERIFIED,
                            "no rendered text supplied (snapshot-only smoke tier)")]
    n_facts = ssot.summary(snap).get("n_facts", 0)
    if not n_facts:
        return [CheckResult("citations.rendered", "L1", _UNVERIFIED,
                            "no published facts - the rendered badge has nothing to count")]
    m = _BADGE_COUNT_RE.search(texts)
    if not m:
        return [CheckResult("citations.rendered", "L1", _FAIL,
                            "rendered self-verification badge not found in the document")]
    rendered = int(m.group(1))
    if rendered != n_facts:
        return [CheckResult("citations.rendered", "L1", _FAIL,
                            f"rendered badge says {rendered} self-verified facts but the snapshot has {n_facts}")]
    return [CheckResult("citations.rendered", "L1", _PASS,
                        f"rendered badge count ({rendered}) byte-matches the snapshot ({n_facts})")]


def _has_content(snap: Dict[str, Any]) -> bool:
    """True when the snapshot carries enough to actually BE a deliverable — published facts or a
    real inventory. Distinguishes 'a deliverable missing its provenance' (a defect) from 'an empty
    input' (nothing to attest); an empty ``{}`` is never scored as a defective deliverable."""
    return (bool(ssot.summary(snap).get("n_facts")) or bool(snap.get("collection_completeness"))
            or bool(snap.get("devices")) or bool(snap.get("health_scores")))


def _check_provenance(snap: Dict[str, Any], texts: Optional[str]) -> List[CheckResult]:
    """Law 2 — the deliverable carries provenance. Snapshot signal: a script_version (always) and,
    when present, a sealed attestation block. A deliverable-with-content but NEITHER signal has no
    provenance (fail); an older-but-good snapshot with a version but no attestation is a pass
    (attestation is a *stronger* seal, absent → unverified, never a fail); an empty input has
    nothing to attest (unverified, never a fabricated defect)."""
    out: List[CheckResult] = []
    has_version = bool(str(snap.get("script_version") or "").strip())
    has_attestation = isinstance(snap.get("attestation"), dict) and bool(snap.get("attestation"))
    if not has_version and not has_attestation:
        out.append(CheckResult("law2.provenance", "L2",
                               _FAIL if _has_content(snap) else _UNVERIFIED,
                               "no provenance: neither script_version nor attestation present"
                               if _has_content(snap) else
                               "empty input — no content to attest provenance for"))
    else:
        out.append(CheckResult("law2.provenance", "L2", _PASS,
                               "provenance present: " + ", ".join(
                                   x for x in ("script_version" if has_version else "",
                                               "attestation seal" if has_attestation else "") if x)))
    if texts is not None:
        present = "Document Control" in texts
        out.append(CheckResult("law2.rendered", "L2", _PASS if present else _FAIL,
                               "Document Control block " + ("present" if present else "MISSING") + " in the render"))
    return out


def _check_coverage_accounting(snap: Dict[str, Any]) -> List[CheckResult]:
    """Law 3 — the collection completeness accounting is internally honest: collected never exceeds
    inventory, and (when all four buckets are published) they sum to the inventory. A snapshot that
    claims fewer blind spots than its own accounting implies is the exact Law-3 inversion to catch."""
    cc = ssot._dotted(snap, "collection_completeness.summary")
    if not isinstance(cc, dict):
        return [CheckResult("law3.accounting", "L3", _UNVERIFIED,
                            "collection_completeness.summary absent — coverage accounting not assessable")]
    inv, comp = ssot._as_int(cc.get("inventory")), ssot._as_int(cc.get("complete"))
    part, notc = ssot._as_int(cc.get("partial")), ssot._as_int(cc.get("not_collected"))
    if inv is not None and comp is not None and comp > inv:
        return [CheckResult("law3.accounting", "L3", _FAIL,
                            f"collected ({comp}) exceeds inventory ({inv}) — impossible coverage")]
    if None not in (inv, comp, part, notc):
        if comp + part + notc != inv:
            return [CheckResult("law3.accounting", "L3", _FAIL,
                                f"coverage buckets do not sum: {comp}+{part}+{notc} != inventory {inv}")]
        return [CheckResult("law3.accounting", "L3", _PASS,
                            f"coverage honest: {comp} collected + {part} partial + {notc} not-collected = {inv}")]
    if inv is not None and comp is not None:
        return [CheckResult("law3.accounting", "L3", _PASS,
                            f"coverage bounds honest (collected {comp} <= inventory {inv})")]
    return [CheckResult("law3.accounting", "L3", _UNVERIFIED,
                        "collection_completeness.summary lacks inventory/complete counts — accounting not assessable")]


def _check_answer_first(snap: Dict[str, Any], texts: Optional[str]) -> List[CheckResult]:
    """Law 6 — the answer-first register has real content (≥1 published canonical fact to answer
    with). Rendered: the 'At a Glance' heading is present."""
    out: List[CheckResult] = []
    n_facts = ssot.summary(snap).get("n_facts", 0)
    if n_facts:
        out.append(CheckResult("law6.register", "L6", _PASS,
                               f"answer-first register backed by {n_facts} published fact(s)"))
    else:
        out.append(CheckResult("law6.register", "L6", _UNVERIFIED,
                               "no published facts - the at-a-glance register has nothing to answer with"))
    if texts is not None:
        present = "At a Glance" in texts
        out.append(CheckResult("law6.rendered", "L6", _PASS if present else _FAIL,
                               "At-a-Glance register " + ("present" if present else "MISSING") + " in the render"))
    return out


def _check_not_observed(snap: Dict[str, Any], texts: Optional[str]) -> List[CheckResult]:
    """Law 8 — absence is REPRESENTED, never dropped or rendered as health. Snapshot signals:
    (a) every not-collected device is enumerated in the devices blind-spot list (not silently
    dropped from the count); (b) the coverage census never labels an absent section 'healthy'.
    Rendered: the '[NOT OBSERVED]' convention is carried."""
    out: List[CheckResult] = []
    cc = ssot._dotted(snap, "collection_completeness.summary")
    notc = ssot._as_int((cc or {}).get("not_collected")) if isinstance(cc, dict) else None
    devices = ssot._dotted(snap, "collection_completeness.devices")
    if notc:  # there ARE blind spots -> they must be enumerated, not just counted
        listed = sum(1 for d in (devices if isinstance(devices, list) else [])
                     if isinstance(d, dict) and str(d.get("status", "")).strip().lower() == "not collected")
        if isinstance(devices, list) and listed >= notc:
            out.append(CheckResult("law8.blindspots", "L8", _PASS,
                                   f"{notc} not-collected device(s) enumerated (represented, not dropped)"))
        else:
            out.append(CheckResult("law8.blindspots", "L8", _FAIL,
                                   f"summary claims {notc} not-collected but only {listed} enumerated (dropped blind spots)"))
    else:  # no blind spots to represent -> nothing to verify here (coverage-honest, not a vacuous pass)
        out.append(CheckResult("law8.blindspots", "L8", _UNVERIFIED,
                               "no not-collected devices declared — nothing to enumerate"))
    # The coverage census must account for EVERY section and never label an absent one 'healthy'.
    census = ssot.compute_schema_census(snap)
    sections = census.get("sections", [])
    if not sections:
        out.append(CheckResult("law8.census", "L8", _UNVERIFIED, "no sections to account for"))
    else:
        summ = census.get("summary", {})
        total = sum(summ.get(k, 0) for k in ("n_published", "n_collected_but_empty", "n_not_collected"))
        dishonest = [s for s in sections if s.get("state") == "not_collected"
                     and re.search(r"\b(healthy|ok|pass(?:ed|ing)?|fine|green)\b", str(s.get("note", "")), re.I)]
        if total != len(sections) or dishonest:
            out.append(CheckResult("law8.census", "L8", _FAIL,
                                   f"census inconsistent (accounts {total}/{len(sections)}) or labels absence healthy"))
        else:
            out.append(CheckResult("law8.census", "L8", _PASS,
                                   f"census accounts for all {len(sections)} section(s); absence never labeled healthy"))
    if texts is not None:
        present = "[NOT OBSERVED]" in texts
        out.append(CheckResult("law8.rendered", "L8", _PASS if present else _FAIL,
                               "[NOT OBSERVED] convention " + ("present" if present else "MISSING") + " in the render"))
    return out


def _check_inputs_required(snap: Dict[str, Any], texts: Optional[str]) -> List[CheckResult]:
    """Law 9 — 'what is still owed' is derivable: the collection-completeness gap (not-collected
    devices) is the load-bearing input. Rendered: the 'Inputs Required' register is present."""
    out: List[CheckResult] = []
    cc = snap.get("collection_completeness")
    if isinstance(cc, dict) and isinstance(cc.get("summary"), dict):
        out.append(CheckResult("law9.inputs", "L9", _PASS,
                               "outstanding inputs derivable from the collection-completeness gap"))
    else:
        out.append(CheckResult("law9.inputs", "L9", _UNVERIFIED,
                               "collection_completeness absent — outstanding inputs not derivable"))
    if texts is not None:
        present = "Inputs Required" in texts
        out.append(CheckResult("law9.rendered", "L9", _PASS if present else _FAIL,
                               "Inputs-Required register " + ("present" if present else "MISSING") + " in the render"))
    return out


def _check_self_verification(snap: Dict[str, Any], texts: Optional[str]) -> List[CheckResult]:
    """Law 10 — an independent self-verification signal with real content (ssot.summary over ≥1
    published fact). Rendered: the 'Single source of truth' badge is present."""
    out: List[CheckResult] = []
    n_facts = ssot.summary(snap).get("n_facts", 0)
    if n_facts:
        out.append(CheckResult("law10.selfverify", "L10", _PASS,
                               f"self-verification summary covers {n_facts} published fact(s)"))
    else:
        out.append(CheckResult("law10.selfverify", "L10", _UNVERIFIED,
                               "no published facts - self-verification badge has nothing to attest"))
    if texts is not None:
        present = "Single source of truth" in texts
        out.append(CheckResult("law10.rendered", "L10", _PASS if present else _FAIL,
                               "SSOT self-verified badge " + ("present" if present else "MISSING") + " in the render"))
    return out


def score(snap: Dict[str, Any], *, texts: Optional[str] = None) -> ScoreResult:
    """Score a known-good deliverable. ``snap`` is the deliverable's snapshot substrate; ``texts``
    is the concatenated rendered document text (``None`` on the snapshot-only smoke tier, which
    leaves every render check ``unverified``). Deterministic, offline, total on bad input."""
    snap = snap if isinstance(snap, dict) else {}
    checks: List[CheckResult] = []
    checks += _check_reconcile(snap)
    checks += _check_citations_provenance(snap)
    checks += _check_citations_rendered(snap, texts)
    checks += _check_provenance(snap, texts)
    checks += _check_coverage_accounting(snap)
    checks += _check_answer_first(snap, texts)
    checks += _check_not_observed(snap, texts)
    checks += _check_inputs_required(snap, texts)
    checks += _check_self_verification(snap, texts)
    return _aggregate(checks)


def _aggregate(checks: List[CheckResult]) -> ScoreResult:
    applicable = [c for c in checks if c.status in (_PASS, _FAIL)]
    passed = [c for c in applicable if c.status == _PASS]
    failed = [c for c in applicable if c.status == _FAIL]
    # law rollup: a law FAILS if any of its checks failed; is VERIFIED if ≥1 passed and none failed;
    # is UNVERIFIED only if every one of its checks was unverified (no evidence either way).
    by_law: Dict[str, set] = {}
    for c in checks:
        by_law.setdefault(c.law, set()).add(c.status)
    tripped = sorted((law for law, st in by_law.items() if _FAIL in st), key=_law_sort_key)
    verified = sorted((law for law, st in by_law.items() if _FAIL not in st and _PASS in st), key=_law_sort_key)
    unverified = sorted((law for law, st in by_law.items() if st == {_UNVERIFIED}), key=_law_sort_key)
    score_val = round(100 * len(passed) / len(applicable)) if applicable else None
    return ScoreResult(
        score=score_val,
        checks=checks,
        laws_verified=verified,
        laws_tripped=tripped,
        laws_unverified=unverified,
        counterexamples=len(failed),
        n_applicable=len(applicable),
        n_passed=len(passed),
    )


def _law_sort_key(law: str):
    m = re.match(r"L(\d+)", law)
    return int(m.group(1)) if m else 999
