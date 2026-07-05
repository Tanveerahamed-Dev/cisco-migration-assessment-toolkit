"""Single source of truth (SSOT) for the assessment's canonical headline facts.

The engine computes each headline fact ONCE during snapshot assembly and publishes it in a
canonical block:

    executive_brief.scale      -> n_devices / n_collected / n_endpoints / n_vlans / n_domains
    executive_brief.posture    -> avg_health / n_critical / n_poor / worst_band
    lifecycle_risk.summary     -> n_past_ldos / n_past_eos / n_near / n_active (+ by_band)
    design_blueprint.summary   -> n_decisions

EVERY downstream surface -- the DOCX/PPTX/XLSX deliverables, the HTML explorer, and the web
dashboard -- must READ those canonical fields, never recompute them from the raw arrays and
never conflate a sibling field. This module is the one place that

  * names the canonical facts (:data:`CANONICAL_FACTS`),
  * reads them canonical-first (:func:`canonical_facts`), and
  * proves each published value still matches an independent derivation from the raw evidence
    (:func:`reconcile`) -- the producer-side guard that catches drift the moment it appears,
    instead of a client noticing a wrong number in a rendered deliverable.

The recurring drift class this exists to kill (it cost several audit waves to find by hand, one
surface at a time across crd/runbook/engagement/deck): a surface reads
``lifecycle_risk.summary.n_past_eos`` (0 on the AJ fleet) where it means the *past-support*
population, which is ``n_past_ldos`` (152) -- silently dropping 152 end-of-support devices into a
false "healthy" reading. The near-twin: ``len(devices)`` / ``len(health_scores)`` used as a
reported device count instead of ``executive_brief.scale.n_devices``.

Read-only and side-effect free: this module derives, it never mutates the snapshot.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Canonical facts: name -> (dotted snapshot path of the published value, one-line concept).
# The dotted path is the SINGLE authoritative source; anything else reporting the same concept
# must agree with it. Kept as data so tests (and future surfaces) can iterate the contract.
CANONICAL_FACTS: Dict[str, tuple] = {
    "n_devices":          ("executive_brief.scale.n_devices",     "inventoried devices (== len(health_scores))"),
    "n_collected":        ("executive_brief.scale.n_collected",   "devices with a complete collection"),
    "n_endpoints":        ("executive_brief.scale.n_endpoints",   "evidenced endpoints (== len(endpoint_identity))"),
    "n_vlans":            ("executive_brief.scale.n_vlans",       "VLANs in use (== len(analyze.vlan_inventory))"),
    "n_domains":          ("executive_brief.scale.n_domains",     "broadcast/management domains"),
    "avg_health":         ("executive_brief.posture.avg_health",  "mean fleet health score"),
    "n_critical":         ("executive_brief.posture.n_critical",  "devices in the Critical health band"),
    "n_poor":             ("executive_brief.posture.n_poor",      "devices in the Poor health band"),
    "worst_band":         ("executive_brief.posture.worst_band",  "worst health band observed"),
    "n_past_ldos":        ("lifecycle_risk.summary.n_past_ldos",  "devices past last-day-of-support (the past-SUPPORT population)"),
    "n_past_eos":         ("lifecycle_risk.summary.n_past_eos",   "devices past end-of-sale but NOT yet past LDoS (a different, smaller set)"),
    "n_near":             ("lifecycle_risk.summary.n_near",       "devices within 1yr of LDoS (Near-LDoS band)"),
    "n_active":           ("lifecycle_risk.summary.n_active",     "devices in active support (Active band)"),
    "n_design_decisions": ("design_blueprint.summary.n_decisions","ranked target-state design decisions"),
}

# Health-band labels (from analyze.compute_health_scores) and lifecycle-band labels (from
# analyze.lifecycle_risk per_device). Named here so the reconciliation derivation can't silently
# drift from the producer's band vocabulary.
_HEALTH_BAND_CRITICAL = "Critical"
_HEALTH_BAND_POOR = "Poor"
# Worst-band severity order, mirroring analyze.compute_executive_brief: the most-severe band that
# is PRESENT in health_scores wins. "Insufficient Data" is intentionally absent -- it never counts
# as the worst health band, and the avg-health mean excludes it too.
_HEALTH_BAND_ORDER = ("Critical", "Poor", "Fair", "Good", "Excellent")
_HEALTH_BAND_NOT_SCORED = "Insufficient Data"
_LIFECYCLE_BANDS = {
    "n_past_ldos": "Past-LDoS",
    "n_past_eos": "Past-EoS",
    "n_near": "Near-LDoS",
    "n_active": "Active",
}


def _as_int(value: Any) -> Optional[int]:
    """Best-effort int coercion; None on anything non-numeric (coverage-honest, never guesses 0)."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        s = value.strip().replace(",", "")
        try:
            return int(float(s))
        except (ValueError, TypeError):
            return None
    return None


def _dotted(snap: Dict[str, Any], path: str) -> Any:
    """Read a dotted snapshot path, returning None if any hop is missing/not a dict."""
    cur: Any = snap
    for hop in path.split("."):
        if not isinstance(cur, dict) or hop not in cur:
            return None
        cur = cur[hop]
    return cur


def canonical_facts(snap: Dict[str, Any]) -> Dict[str, Any]:
    """The authoritative value for every canonical fact, read canonical-first from the snapshot.

    This is the accessor every surface SHOULD use rather than re-deriving a headline number. A
    fact whose canonical block is absent comes back as ``None`` (coverage-honest -- "not
    published" is never silently turned into 0). Counts are coerced to int; ``worst_band`` stays a
    string.
    """
    out: Dict[str, Any] = {}
    for name, (path, _concept) in CANONICAL_FACTS.items():
        raw = _dotted(snap, path)
        out[name] = raw if name == "worst_band" else _as_int(raw)
    return out


_MISSING = object()


def _is_deep_empty(val: Any) -> bool:
    """True when `val` carries NO evidence — a falsy scalar/empty container, OR a container whose every
    element/value is itself deep-empty. This is the coverage-honesty fix for the WRAPPER-of-empties shape
    (adversarial-review finding, 2026-07-05): a section like ``{'dup_ip': [], 'dup_subnet': []}`` (a compute
    that ALWAYS returns its keys, here with zero conflicts found) is truthy, so a shallow ``not val`` check
    mislabels it 'published' — a green "seen" row for a genuinely-empty result, the exact Law-3 inversion this
    module exists to prevent. Short-circuits on the first real leaf, so a populated section stays cheap."""
    if isinstance(val, dict):
        return all(_is_deep_empty(v) for v in val.values())
    if isinstance(val, (list, tuple, set)):
        return all(_is_deep_empty(v) for v in val)
    return not val


def _device_not_collected(snap: Dict[str, Any], device: str) -> bool:
    """True iff `device` is in the collection blind-spot list with status 'not collected' (a fully un-collected
    device). A 'partial' device (some evidence collected) or a fully-collected one is NOT a blind spot."""
    want = (device or "").strip().lower()                # device names vary in case (devices.json vs show-text)
    for d in (_dotted(snap, "collection_completeness.devices") or []):
        if isinstance(d, dict) and (d.get("host") or "").strip().lower() == want:
            return str(d.get("status", "")).strip().lower() == "not collected"
    return False


def abstention_reason(snap: Dict[str, Any], subject: str, device: str = None) -> str:
    """Why is `subject` absent — the coverage-honest core made callable. `subject` is a top-level snapshot
    section key (e.g. 'fhrp', 'vpc') or a dotted path (e.g. 'executive_brief.scale.n_vlans'); `device` optionally
    scopes the question to one host. Returns exactly one of:
      'published'           -- present and non-empty (a real result)
      'collected_but_empty' -- present but empty/zero (collected; genuinely nothing of this kind found)
      'not_collected'       -- the axis is absent, OR (device given) that device was never collected -- a BLIND
                               SPOT, never a clean result. This is the 'not observed never becomes healthy' rule
                               (the bare show-logging-on-NX-OS false-health class) made into a first-class token.
    Pure presence/absence logic over the snapshot -- no model, no egress; total (safe on None / bad input)."""
    snap = snap if isinstance(snap, dict) else {}
    # A fact about an UN-collected device is a blind spot, regardless of the fleet-level value.
    if device and _device_not_collected(snap, device):
        return "not_collected"
    val = _dotted(snap, subject) if "." in subject else snap.get(subject, _MISSING)
    if val is _MISSING or val is None:
        return "not_collected"
    # DEEP-empty, not just shallow-falsy: a wrapper whose every payload is empty (a compute that always
    # returns its keys but found nothing) is 'collected_but_empty', never the green 'published'.
    if _is_deep_empty(val):          # present but carries no evidence -> collected, nothing found
        return "collected_but_empty"
    return "published"


# ---------------------------------------------------------------------------------------------
# schema census (J3): a snapshot self-describes what it actually SAW -- the SuzieQ `describe`
# analog. For EVERY top-level snapshot section, project the coverage-honest 3-state token onto a
# queryable coverage map, so an access-only collection (e.g. the AJ fleet, where a whole
# distribution/core tier is UN-collected) reports exactly what was seen vs what is a blind spot,
# instead of a rendered "filler" output whose real cause is an uncollected tier, not a code bug.
# ---------------------------------------------------------------------------------------------

SCHEMA_CENSUS_SCHEMA = "schema_census/1"

# The honest note per 3-state token. Never "ok"/"healthy": absence of evidence is never health.
_CENSUS_NOTE = {
    "published":           "seen — collected and non-empty",
    "collected_but_empty": "collected, nothing of this kind found (not a blind spot)",
    "not_collected":       "blind spot — not collected",
}


def _census_kind(val: Any) -> str:
    """The shape of a section, for the census `kind` column: absent / list / dict / scalar.
    Purely structural (no model, no dates) so the census stays deterministic across runs."""
    if val is None:
        return "absent"
    if isinstance(val, list):
        return "list"
    if isinstance(val, dict):
        return "dict"
    return "scalar"


def compute_schema_census(snap: Dict[str, Any]) -> Dict[str, Any]:
    """The per-section coverage census -- a snapshot's self-description of what it actually saw.

    For EVERY top-level snapshot section key, emit one row::

        {key, state, count, kind, note}

    where ``state`` is the coverage-honest 3-state token :func:`abstention_reason` returns
    (``published`` / ``collected_but_empty`` / ``not_collected``), ``count`` is ``len()`` when the
    section is a list or dict (else ``None`` -- a scalar/absent section has no cardinality),
    ``kind`` is the section's structural shape, and ``note`` is a short honest phrase. A
    present-but-empty section is ``collected_but_empty`` (collected, genuinely nothing found -- NOT
    a blind spot); an absent section is ``not_collected`` (a real blind spot). Nothing is ever
    labelled "ok"/"healthy": absence of evidence is never health (Law 3).

    Deterministic (presence/absence only -- no dates, no model) and total on bad input: a non-dict
    snapshot yields an empty-but-well-formed census rather than raising.
    """
    snap = snap if isinstance(snap, dict) else {}
    sections: List[Dict[str, Any]] = []
    n_pub = n_empty = n_absent = 0
    for key in snap:                                   # iterate a snapshot copy's keys (see caller)
        val = snap.get(key)
        state = abstention_reason(snap, key)
        if state == "published":
            n_pub += 1
        elif state == "collected_but_empty":
            n_empty += 1
        else:
            n_absent += 1
        count = len(val) if isinstance(val, (list, dict)) else None
        sections.append({
            "key": key,
            "state": state,
            "count": count,
            "kind": _census_kind(val),
            "note": _CENSUS_NOTE.get(state, _CENSUS_NOTE["not_collected"]),
        })
    return {
        "schema": SCHEMA_CENSUS_SCHEMA,
        "sections": sections,
        "summary": {
            "n_published": n_pub,
            "n_collected_but_empty": n_empty,
            "n_not_collected": n_absent,
            "n_sections": len(sections),
        },
    }


# ---------------------------------------------------------------------------------------------
# fact lineage (J2): attribute-level provenance for the canonical headline facts (Infrahub-style).
# For each CANONICAL_FACTS entry, name WHERE the number comes from: its dotted canonical path, the
# published value, the coverage-honest state of that path, and the one-line basis/derivation
# already recorded in CANONICAL_FACTS -- provenance made queryable by REUSING the SSOT contract,
# not a parallel one. (source_command depth -- mapping each fact to the exact show-command -- is
# DEFERRED; the basis string is the v1 provenance.)
# ---------------------------------------------------------------------------------------------

FACT_LINEAGE_SCHEMA = "fact_lineage/1"


def compute_fact_lineage(snap: Dict[str, Any]) -> Dict[str, Any]:
    """Attribute-level provenance for every canonical headline fact.

    Emits one row per :data:`CANONICAL_FACTS` entry::

        {name, value, path, state, basis}

    where ``path`` is the dotted canonical snapshot path, ``value`` is the authoritative value from
    :func:`canonical_facts` (read canonical-first; ``None`` when the block isn't published),
    ``state`` is :func:`abstention_reason` on that path (``published`` / ``collected_but_empty`` /
    ``not_collected`` -- so an un-published block reads as a blind spot, never a silent 0), and
    ``basis`` is the one-line concept/derivation named in ``CANONICAL_FACTS`` (the "== len(...)"
    hints), so a reader sees WHERE each headline number comes from. Reuses the SSOT contract rather
    than inventing a parallel provenance store. Total on bad input.
    """
    snap = snap if isinstance(snap, dict) else {}
    values = canonical_facts(snap)
    facts: List[Dict[str, Any]] = []
    for name, (path, concept) in CANONICAL_FACTS.items():
        facts.append({
            "name": name,
            "value": values.get(name),
            "path": path,
            "state": abstention_reason(snap, path),
            "basis": concept,
        })
    return {"schema": FACT_LINEAGE_SCHEMA, "facts": facts}


def reconcile(snap: Dict[str, Any]) -> List[str]:
    """Return human-readable SSOT violations: a published canonical value that disagrees with an
    independent derivation from the raw evidence. Empty list == every published fact reconciles.

    Coverage-honest: a canonical block that isn't published yet (e.g. a partially-assembled or
    minimal snapshot whose ``executive_brief.scale`` is ``None``) is SKIPPED, not flagged -- the
    guard fires only when both the published value AND its raw basis are present, so it never
    invents a violation from absent evidence.
    """
    violations: List[str] = []
    scale = _dotted(snap, "executive_brief.scale") or {}
    posture = _dotted(snap, "executive_brief.posture") or {}
    cc = _dotted(snap, "collection_completeness.summary") or {}
    lc = _dotted(snap, "lifecycle_risk.summary") or {}
    per_device = _dotted(snap, "lifecycle_risk.per_device") or []
    health = snap.get("health_scores") or []
    endpoints = snap.get("endpoint_identity") or []

    def check(name: str, published: Any, derived: Any, basis: str) -> None:
        pi, di = _as_int(published), _as_int(derived)
        if pi is None or di is None:
            return  # not both present -> coverage-honest skip
        if pi != di:
            violations.append(f"{name}={pi} but {basis}={di}")

    # --- scale -------------------------------------------------------------------------------
    if "n_devices" in scale and health:
        check("executive_brief.scale.n_devices", scale.get("n_devices"), len(health), "len(health_scores)")
    if "n_devices" in scale and "inventory" in cc:
        check("executive_brief.scale.n_devices", scale.get("n_devices"), cc.get("inventory"),
              "collection_completeness.summary.inventory")
    if "n_collected" in scale and "complete" in cc:
        check("executive_brief.scale.n_collected", scale.get("n_collected"), cc.get("complete"),
              "collection_completeness.summary.complete")
    # ...and against an INDEPENDENT raw basis, not just the producer-shared sibling summary.complete: the device
    # list carries ONLY the blind spots ('the report lists only the blind spots', analyze.py), so collected =
    # inventory - len(devices). Without this, a coordinated off-by-N drift writing the SAME wrong value to both
    # scale.n_collected and summary.complete passes -- 'blind' silently reads 'fully collected' (audit-4 #11).
    _cc_devices = _dotted(snap, "collection_completeness.devices")
    _inv = _as_int(cc.get("inventory"))
    if "n_collected" in scale and _inv is not None and isinstance(_cc_devices, list):
        check("executive_brief.scale.n_collected", scale.get("n_collected"), _inv - len(_cc_devices),
              "collection_completeness.summary.inventory - len(collection_completeness.devices)")
    if "n_endpoints" in scale and endpoints:
        check("executive_brief.scale.n_endpoints", scale.get("n_endpoints"), len(endpoints),
              "len(endpoint_identity)")
    # n_domains (the broadcast/management application domains) was published + served via SSOT but had NO
    # reconcile check -- a drift vs its raw basis went undetected. It MUST equal len(application_intelligence
    # .domains), the source compute_application_intelligence counts it from (audit-5 scale-ssot #1/#2).
    _ai_domains = _dotted(snap, "application_intelligence.domains")
    if "n_domains" in scale and isinstance(_ai_domains, list) and _ai_domains:
        check("executive_brief.scale.n_domains", scale.get("n_domains"), len(_ai_domains),
              "len(application_intelligence.domains)")
    if "n_vlans" in scale:
        try:  # vlan_inventory is the canonical VLAN-in-use derivation; import lazily (avoids cycles)
            from cisco_toolkit.analyze import vlan_inventory
            derived_vlans = len(vlan_inventory(snap))
            if derived_vlans:   # raw-evidence guard (like the n_devices/n_endpoints checks): a slimmed snapshot
                # publishes n_vlans but strips the raw VLAN arrays -> derives 0 -> SKIP, never a false violation.
                check("executive_brief.scale.n_vlans", scale.get("n_vlans"), derived_vlans,
                      "len(vlan_inventory)")
        except Exception:
            pass  # not derivable on this snapshot shape -> skip, never a false violation

    # --- posture (health bands) --------------------------------------------------------------
    if health:
        if "n_critical" in posture:
            crit = sum(1 for h in health if isinstance(h, dict) and h.get("band") == _HEALTH_BAND_CRITICAL)
            check("executive_brief.posture.n_critical", posture.get("n_critical"), crit,
                  "count(health_scores.band==Critical)")
        if "n_poor" in posture:
            poor = sum(1 for h in health if isinstance(h, dict) and h.get("band") == _HEALTH_BAND_POOR)
            check("executive_brief.posture.n_poor", posture.get("n_poor"), poor,
                  "count(health_scores.band==Poor)")
        # avg_health and worst_band are DERIVED aggregates published in posture; both are counted as
        # self-verified facts, so both must be reconciled too (mirroring compute_executive_brief
        # exactly -> no tolerance, no false positives). The mean excludes "Insufficient Data" scores.
        if "avg_health" in posture:
            scored = [h.get("score") for h in health
                      if isinstance(h, dict) and isinstance(h.get("score"), (int, float))
                      and h.get("band") != _HEALTH_BAND_NOT_SCORED]
            if scored:
                check("executive_brief.posture.avg_health", posture.get("avg_health"),
                      round(sum(scored) / len(scored)), "round(mean(scored health_scores.score))")
        if "worst_band" in posture and posture.get("worst_band"):
            bands_present = {h.get("band") for h in health if isinstance(h, dict)}
            derived_worst = next((b for b in _HEALTH_BAND_ORDER if b in bands_present), "")
            if derived_worst and posture.get("worst_band") != derived_worst:
                violations.append(
                    f"executive_brief.posture.worst_band={posture.get('worst_band')!r} but "
                    f"most-severe band present={derived_worst!r}")

    # --- lifecycle bands (per_device is the raw basis) ---------------------------------------
    if per_device:
        # the lifecycle summary republishes the device count (consumed as the EoL rollup total in analyze.py); it
        # must reconcile to the raw per_device length, else a lifecycle device-count drift diverges silently from
        # the SSOT device count (audit-4 #12).
        if "n_devices" in lc:
            check("lifecycle_risk.summary.n_devices", lc.get("n_devices"), len(per_device),
                  "len(lifecycle_risk.per_device)")
        for field, band in _LIFECYCLE_BANDS.items():
            if field in lc:
                cnt = sum(1 for d in per_device if isinstance(d, dict) and d.get("band") == band)
                check(f"lifecycle_risk.summary.{field}", lc.get(field), cnt,
                      f"count(per_device.band=={band})")
        by_band = lc.get("by_band")
        if isinstance(by_band, dict):
            for band, count in by_band.items():
                cnt = sum(1 for d in per_device if isinstance(d, dict) and d.get("band") == band)
                check(f"lifecycle_risk.summary.by_band[{band}]", count, cnt,
                      f"count(per_device.band=={band})")

    # --- design decisions --------------------------------------------------------------------
    dbp = snap.get("design_blueprint")
    dbp = dbp if isinstance(dbp, dict) else {}      # the `x or {}` idiom does NOT guard a TRUTHY non-dict
    dsum = dbp.get("summary")                        # block (e.g. a str) -> it would crash the coverage guard
    dsum = dsum if isinstance(dsum, dict) else {}
    decisions = dbp.get("decisions")
    if "n_decisions" in dsum and isinstance(decisions, list):
        check("design_blueprint.summary.n_decisions", dsum.get("n_decisions"), len(decisions),
              "len(design_blueprint.decisions)")

    return violations


def audit(snap: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Runtime SSOT self-check for the assembly line — the field-data safety net.

    The test suite only proves SSOT-consistency on its own fixtures; a snapshot produced by
    ``cisco-assess`` on a real customer fleet is never seen by the suite. So at assembly time the
    engine reconciles its own published facts and, IF (and only if) they don't reconcile, returns a
    disclosure dict to be stamped into ``assessment_integrity`` — the SAME machine-readable channel
    the engine already uses to disclose a failed cross-axis brief, which the deck/explorer surface
    instead of rendering missing numbers as healthy zeros.

    Returns ``None`` on a clean run (the normal case) so a healthy snapshot raises NO false integrity
    alarm and grows NO new field (preserving the ``assessment_integrity not in snap`` invariant).
    """
    violations = reconcile(snap)
    if not violations:
        return None
    return {
        "ssot_reconciliation": "failed",
        "n_violations": len(violations),
        "violations": violations[:20],  # bounded so a pathological snapshot can't bloat the disclosure
    }


def summary(snap: Dict[str, Any]) -> Dict[str, Any]:
    """A compact, always-present self-verification summary for the dashboards -- the POSITIVE
    companion to :func:`audit` (which discloses only on drift). Reports how many canonical facts
    were published and whether they all reconcile to the raw evidence, so a surface can render a
    client-facing trust signal ("N headline facts self-verified against the raw evidence") without
    re-running any check itself.

    Returns ``{"verified": bool, "n_facts": int, "n_violations": int}``. ``verified`` is True iff
    every published canonical fact reconciles. ``n_facts`` counts the canonical facts actually
    published (None facts -- unpublished blocks -- are not counted, so the signal is coverage-honest
    about how much was assessable).
    """
    facts = canonical_facts(snap)
    violations = reconcile(snap)
    return {
        "verified": not violations,
        "n_facts": sum(1 for value in facts.values() if value is not None),
        "n_violations": len(violations),
    }
