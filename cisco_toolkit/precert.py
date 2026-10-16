"""Pre-Change Validation Certificate (orchestration roadmap C1) — offline, read-only, coverage-honest.

Forward Networks' "Predict" / Cisco NDI pre-change analysis / NetBrain's "Triple Defense" all certify a
candidate change before the maintenance window. The engine already ships the differential core
(`fib.reachability_delta`, live in `--compare`); this module packages it — plus the segmentation posture and
any `--path-intents` catalog re-validated across the pair — as the named PPDIOO gate ARTIFACT: a
decision-grade certificate JSON (`<output>.precert.json`) and a 'Pre-Change Certificate' diff-workbook sheet.

Verdict doctrine (encoded EXACTLY; coverage-honest):
  * any regression (newly-blocked flow / broken path intent / violated segmentation invariant) -> FAIL;
  * no regressions but >0 inconclusive flows or not_evaluable invariants -> CONDITIONAL — a certificate is
    never PASS with an open blind spot;
  * everything checkable checked and clean -> PASS;
  * nothing definitively checkable at all -> INDETERMINATE — we certify nothing we did not compute.
Every changed flow is cited `before -> after`; every blind spot is NAMED in `blind_spots`. Pure stdlib over
two already-collected snapshots; no egress, no device contact; total on malformed input.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

from typing import Any, Dict, List, Optional, Tuple

from . import fib
from .path_assertions import revalidate
from .textutils import _as_num          # shared fail-soft numeric coercion (rejects Infinity/NaN)

SCHEMA = "precert/1"
# Single-snapshot pre-window READINESS freeze (the prediction half of a calibration row).
READINESS_SCHEMA = "precert-readiness/1"

# The diff-workbook sheet contract (write_diff_workbook renders the certificate from these).
CERT_SHEET_NAME = "Pre-Change Certificate"
CERT_SHEET_HEADERS = ("Section", "Item", "Before", "After", "Disposition", "Evidence / Detail")

_VERDICTS = ("PASS", "CONDITIONAL", "FAIL", "INDETERMINATE")


def _stamp(snap: Dict[str, Any]) -> dict:
    """Provenance reference for one side of the pair: when it was generated, by which engine, over how many
    devices — the certificate is only as good as the snapshots it binds."""
    s = snap if isinstance(snap, dict) else {}
    devs = s.get("devices")
    return {"generated_at": str(s.get("generated_at", "") or ""),
            "script_version": str(s.get("script_version", "") or ""),
            "n_devices": len(devs) if isinstance(devs, dict) else 0,
            # Content-semantic fallback binding. The file-loading caller can additionally provide
            # the exact input-byte SHA-256 via ``source_hashes``.
            "snapshot_content_sha256": _snapshot_content_hash(s)}


def _snapshot_content_hash(snap: Any) -> str:
    """Stable SHA-256 of the loaded snapshot object; total on malformed/non-JSON leaves."""
    try:
        payload = json.dumps(snap, sort_keys=True, ensure_ascii=True, separators=(",", ":"),
                             default=str, allow_nan=False)
    except (TypeError, ValueError, OverflowError):
        payload = json.dumps(str(snap), ensure_ascii=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_sha256(value: Any) -> bool:
    """Return whether *value* is the canonical ``sha256:<64 lowercase hex>`` form."""
    if not isinstance(value, str) or len(value) != 71 or not value.startswith("sha256:"):
        return False
    digest = value[7:]
    return digest == digest.lower() and all(ch in "0123456789abcdef" for ch in digest)


def _canonical_sha256(value: Any) -> Any:
    """Accept a BARE 64-hex digest as the canonical ``sha256:`` form; pass anything else through.

    The prefix is a labelling convention, not part of the digest, and this repo has TWO producers
    that disagree about it: `webapp/backend/storage.py` emits ``"sha256:" + hexdigest()`` while the
    engine's `_record_from_bytes` (COLLECT_PARSE_V3_23_0.py) emits the bare hexdigest, and
    COLLECT_PARSE passes that straight into `compute_precert(source_hashes=...)`.

    So `_is_sha256` rejected both sides of every CLI `--compare`, which became two `gate_failures`,
    which made `verdict = "FAIL"` on runs with NO regressions at all. Measured on two IDENTICAL clean
    snapshots: `verdict: FAIL — 2 blocking condition(s) … not safe to approve`, with
    `source_binding: {}`. A PPDIOO cutover gate that fails every time trains its reader to ignore it,
    and the certificate was UNBOUND on exactly the runs it exists to gate — while `html.py` still
    rendered the raw binding as `BOUND` in the workbook sheet beside the blocking gate failure.

    Widening here rather than changing the producer: `_record_from_bytes` builds generic evidence
    records consumed in several places, so re-spelling its output is the larger blast radius. This
    accepts strictly more DIGESTS but no more non-digests — a 64-character lowercase hex string is
    exactly as much a proof as the same string with a label on it. Everything else still fails closed.
    """
    if isinstance(value, str):
        candidate = value.strip()
        if len(candidate) == 64 and all(ch in "0123456789abcdef" for ch in candidate.lower()):
            return "sha256:" + candidate.lower()
        return candidate
    return value


def _normalize_source_hashes(value: Any, *, issues: Optional[List[str]] = None) -> dict:
    """Preserve only validated caller-provided exact input hashes.

    A supplied-but-invalid binding is reported through ``issues`` so a decision-bearing caller can
    fail closed instead of silently treating arbitrary prose as a cryptographic digest.
    """
    if not isinstance(value, dict):
        if value is not None and issues is not None:
            issues.append("source hashes must be an object of canonical sha256 bindings")
        return {}
    out = {}
    for side in ("before", "after", "snapshot"):
        if side not in value:
            continue
        raw = value.get(side)
        if isinstance(raw, dict):
            raw = raw.get("sha256") or raw.get("hash")
        raw = _canonical_sha256(raw)
        if _is_sha256(raw):
            out[side] = raw
        elif issues is not None:
            issues.append(
                f"{side} source hash is not canonical sha256:<64 lowercase hex>"
            )
    return out


def _normalize_schema_status(value: Any) -> dict:
    """Accept the schema gate's historic tuple or a richer mapping with an override marker."""
    if isinstance(value, dict):
        return {"status": str(value.get("status") or "").strip().lower(),
                "message": str(value.get("message") or ""),
                "override": bool(value.get("override") or value.get("overridden"))}
    if isinstance(value, (list, tuple)) and value:
        return {"status": str(value[0] or "").strip().lower(),
                "message": str(value[1] or "") if len(value) > 1 else "",
                "override": False}
    if isinstance(value, str) and value.strip():
        return {"status": value.strip().lower(), "message": "", "override": False}
    return {}


def _assessment_integrity(snap: Any, required=()) -> dict:
    """Normalize failed phases/sentinels and missing required analyses into one fail-closed channel."""
    s = snap if isinstance(snap, dict) else {}
    ai = s.get("assessment_integrity")
    ai = ai if isinstance(ai, dict) else {}
    failures: List[str] = []
    phases = ai.get("failed_phases")
    if isinstance(phases, list):
        failures.extend(f"phase failed: {str(p)}" for p in phases if str(p).strip())
    elif phases:
        failures.append(f"phase failed: {str(phases)}")
    for key, value in ai.items():
        if key in ("failed_phases", "n_violations"):
            continue
        if str(value).strip().lower() in ("failed", "compute_failed", "unavailable", "error"):
            failures.append(f"{key}: {value}")
    for key, value in s.items():
        if isinstance(value, dict) and value.get("_unavailable"):
            failures.append(f"{key}: unavailable")
    expected = {"migration_readiness": list}
    for key in required:
        if key not in s or not isinstance(s.get(key), expected.get(key, object)):
            failures.append(f"{key}: missing or unusable")
    failures = list(dict.fromkeys(failures))
    return {"ok": not failures, "failures": failures}


def _schema_signature(snap: Dict[str, Any]) -> tuple[str, str]:
    """The comparable schema signature of one snapshot: (script_version, schema_version). script_version
    is emitted on every real snapshot ('V{__version__}', the DECOUPLED schema/engine version — NOT the
    pyproject release version); schema_version is optional. A missing token -> '' (unverifiable, which is
    NOT the same as a mismatch). Total on a non-dict snapshot (-> ('', ''))."""
    s = snap if isinstance(snap, dict) else {}
    return (str(s.get("script_version", "") or "").strip(),
            str(s.get("schema_version", "") or "").strip())


def schema_compat_status(snaps: List[Dict[str, Any]],
                         labels: Optional[List[str]] = None) -> tuple[str, str]:
    """Classify whether a SERIES of snapshots is safe to diff/trend, by their engine schema version, so
    ``--compare``/``--trend`` can warn-or-refuse instead of diffing across a schema change silently (P3-E2).
    Diffing across engine SCHEMA versions can MISREPORT — a field a newer engine renamed/moved reads as a
    real network change when it is only a schema difference. Returns ``(status, message)``:

      * ``"ok"``           — every snapshot carries the SAME non-empty script_version (and schema_version
                             where present): safe to diff. ``message`` is ''.
      * ``"unverifiable"`` — at least one snapshot omits script_version, so compatibility cannot be PROVEN;
                             never silently "ok" (coverage-honest) — the caller WARNS and proceeds (an
                             absent version is not evidence of a mismatch, so it is not refused).
      * ``"mismatch"``     — two snapshots carry DIFFERENT non-empty script_versions (or schema_versions):
                             a cross-schema diff — the caller REFUSES unless explicitly overridden.

    ``labels`` name the snapshots (e.g. file paths) in the message; default 'snapshot N'. Pure; total on
    malformed input (a non-dict snapshot contributes an empty signature)."""
    items = list(snaps or [])
    names = list(labels or [])
    sigs = []
    for i, s in enumerate(items):
        name = names[i] if i < len(names) else f"snapshot {i + 1}"
        script_v, schema_v = _schema_signature(s)
        sigs.append((name, script_v, schema_v))
    scripts = {sv for (_n, sv, _sc) in sigs if sv}
    schemas = {sc for (_n, _sv, sc) in sigs if sc}
    if len(scripts) > 1 or len(schemas) > 1:
        shown = ", ".join(f"{n}={sv or '?'}" + (f"/{sc}" if sc else "") for (n, sv, sc) in sigs)
        return ("mismatch",
                f"snapshots were produced by DIFFERENT engine schema versions ({shown}) -- a cross-schema "
                f"diff can misreport a schema change as a real network change")
    missing = [n for (n, sv, _sc) in sigs if not sv]
    if missing:
        return ("unverifiable",
                f"could not verify schema compatibility -- no script_version on: {', '.join(missing)}")
    return ("ok", "")


def _inconclusive_reason(pair: dict) -> str:
    """NAME the blind spot: which side(s) of the trace were lost to incomplete collection, and how."""
    bits = []
    for label, key in (("before", "old_status"), ("after", "new_status")):
        status = str(pair.get(key, "") or "")
        if not status.startswith("computed"):
            bits.append(f"{label}: {status or 'not traced'}")
    return "; ".join(bits) or "trace not computed end-to-end"


def _flows(delta: dict) -> dict:
    """The reachability_delta reshaped for the certificate: preserved/both-unreachable counts, every changed
    flow cited old->new (regression = newly blocked), every inconclusive flow with its named reason, and the
    bounded-sample disclosure (no silent caps)."""
    changed: List[dict] = []
    for p in (delta.get("newly_blocked") or []):
        changed.append({"src": p.get("src"), "dst": p.get("dst"),
                        "before": p.get("old_status"), "after": p.get("new_status"), "regression": True})
    for p in (delta.get("newly_reachable") or []):
        changed.append({"src": p.get("src"), "dst": p.get("dst"),
                        "before": p.get("old_status"), "after": p.get("new_status"), "regression": False})
    inconclusive = [{"src": p.get("src"), "dst": p.get("dst"), "reason": _inconclusive_reason(p)}
                    for p in (delta.get("inconclusive_pairs") or [])]
    return {"preserved": int(delta.get("preserved") or 0),
            "both_unreachable": int(delta.get("both_unreachable") or 0),
            "changed": changed, "inconclusive": inconclusive,
            # A flow can remain existentially reachable while one equal-cost leg is proven to
            # blackhole traffic.  That is partial packet loss, not a clean preserved flow.
            "ecmp_partial_drop": [dict(p) for p in _as_list(delta.get("ecmp_partial_drop"))
                                  if isinstance(p, dict)],
            "assessed": bool(delta.get("assessed")),
            "pairs_tested": int(delta.get("pairs_tested") or 0),
            "subnets_tested": int(delta.get("subnets_tested") or 0),
            "subnets_total": int(delta.get("subnets_total") or 0),
            "capped": bool(delta.get("capped"))}


def _as_dict(v: Any) -> dict:
    """Coerce a possibly-malformed snapshot block to a dict; a truthy non-dict degrades to ``{}``.

    The house guard (ssot._as_dict / docmeta.as_dict). ``x or {}`` guards None/empty but NOT a truthy
    non-dict, and the next ``.get`` then raises AttributeError."""
    return v if isinstance(v, dict) else {}


def _as_list(v: Any) -> list:
    """Coerce a possibly-malformed snapshot block to a list; a truthy non-list degrades to ``[]``.

    The list twin of :func:`_as_dict`. ``x or []`` keeps a truthy non-list (``5``, ``True``, the bare
    JSON ``Infinity`` json.loads accepts), and the following ``for ... in`` then raises
    ``TypeError: 'float' object is not iterable`` -- crashing compute_precert /
    compute_readiness_freeze and, through them, ``html.write_diff_workbook`` (the --compare
    deliverable, which renders the certificate). Coverage-honest: a malformed block reads as absent."""
    return v if isinstance(v, list) else []


def _dict_rows(v: Any) -> list:
    """The dict ELEMENTS of a snapshot list section -- the guard for every per-row ``.get()`` loop."""
    return [r for r in _as_list(v) if isinstance(r, dict)]


def _seg_of(snap: Dict[str, Any]) -> dict:
    v = snap.get("segmentation") if isinstance(snap, dict) else None
    return v if isinstance(v, dict) else {}


def _segmentation_invariants(snap_before: Dict[str, Any], snap_after: Dict[str, Any]) -> List[dict]:
    """Segmentation invariants derived from the BEFORE snapshot's posture (isolated app domains + dedicated
    VRFs) and re-checked on the AFTER side. `held` is a first-class tri-state: True / False (a violated
    invariant = a regression) / 'not_evaluable' (the data to re-verify it is absent — an abstention, never
    silently 'held'). A before snapshot with segmentation data but NO claim (flat network) yields no rows:
    nothing was claimed, so nothing can be violated or blind."""
    b, a = _seg_of(snap_before), _seg_of(snap_after)
    b_domains = _dict_rows(b.get("domains"))
    b_vrfs = _dict_rows(b.get("vrfs"))
    if not (b_domains or b_vrfs):
        return [{"invariant": "segmentation posture preserved", "held": "not_evaluable",
                 "evidence": "no segmentation data in the before snapshot — invariants cannot be derived "
                             "(NOT a statement that segmentation is unchanged)"}]
    a_domains = {str(d.get("domain")): d for d in _dict_rows(a.get("domains"))}
    a_vrf_names = {str(v.get("vrf")) for v in _dict_rows(a.get("vrfs"))}
    a_has = bool(a_domains) or bool(a_vrf_names)
    rows: List[dict] = []
    for d in b_domains:
        if not d.get("isolated"):
            continue                       # not isolated before -> no isolation invariant to preserve
        name = str(d.get("domain"))
        inv = f"application domain '{name}' remains isolated"
        ad = a_domains.get(name)
        if not a_has:
            rows.append({"invariant": inv, "held": "not_evaluable",
                         "evidence": "no segmentation data in the after snapshot — isolation cannot be re-verified"})
        elif ad is None:
            rows.append({"invariant": inv, "held": "not_evaluable",
                         "evidence": "domain absent from the after snapshot's segmentation data — "
                                     "isolation cannot be re-verified"})
        else:
            rows.append({"invariant": inv, "held": bool(ad.get("isolated")),
                         "evidence": str(ad.get("exposure", "") or
                                         ("still isolated after the change" if ad.get("isolated")
                                          else "no longer isolated after the change"))})
    for v in b_vrfs:
        name = str(v.get("vrf", "") or "")
        if not name or name == "(global)":
            continue                       # the global table is not a segmentation claim
        inv = f"VRF '{name}' still segments its gateways"
        n_gw = v.get("gateway_count", 0)
        if not a_has:
            rows.append({"invariant": inv, "held": "not_evaluable",
                         "evidence": "no segmentation data in the after snapshot — VRF presence cannot be re-verified"})
        elif name in a_vrf_names:
            rows.append({"invariant": inv, "held": True,
                         "evidence": f"{n_gw} gateway(s) before; VRF still present after the change"})
        else:
            rows.append({"invariant": inv, "held": False,
                         "evidence": f"VRF absent after the change — {n_gw} gateway(s) lost their VRF segmentation"})
    return rows


def compute_precert(snap_before: Dict[str, Any], snap_after: Dict[str, Any],
                    path_intents: Optional[List[dict]] = None,
                    limit: int = 24, max_pairs: int = 400, *,
                    source_hashes: Optional[dict] = None,
                    schema_status: Any = None) -> dict:
    """The Pre-Change Validation Certificate for a before/after snapshot pair (+ an optional path-intent
    catalog). Returns the certificate dict (schema 'precert/1'); pure JSON types; total on bad input."""
    before = snap_before if isinstance(snap_before, dict) else {}
    after = snap_after if isinstance(snap_after, dict) else {}
    source_hash_issues: List[str] = []
    source_binding = _normalize_source_hashes(source_hashes, issues=source_hash_issues)
    schema = _normalize_schema_status(schema_status)
    integrity = {
        "before": _assessment_integrity(before),
        "after": _assessment_integrity(after),
    }
    integrity_failures = (
        [f"before: {x}" for x in integrity["before"]["failures"]]
        + [f"after: {x}" for x in integrity["after"]["failures"]]
    )

    try:                                   # fail-open: a reachability hiccup degrades to 'not assessed'
        delta = fib.reachability_delta(before, after, limit=limit, max_pairs=max_pairs)
    except Exception:
        delta = {}
    flows = _flows(delta)
    segmentation = _segmentation_invariants(before, after)

    intents: List[dict] = []
    intents_failed = False
    if path_intents:
        try:                               # fail-open, but NEVER silently drop a supplied catalog
            intents = revalidate(before, after, path_intents)["results"]
        except Exception:
            intents_failed = True

    # ---- regressions / fail-closed gate failures: every one cited ----
    regressions: List[str] = []
    gate_failures: List[str] = list(source_hash_issues)
    for f in flows["changed"]:
        if f["regression"]:
            regressions.append(f"flow {f['src']} -> {f['dst']} newly blocked ({f['before']} -> {f['after']})")
    for f in flows["ecmp_partial_drop"]:
        legs = f.get("ecmp_dropping_legs") if isinstance(f.get("ecmp_dropping_legs"), list) else []
        gate_failures.append(
            f"flow {f.get('src')} -> {f.get('dst')} has {len(legs)} proven-blackholing ECMP leg(s) "
            "after the change (partial packet loss)")
    for s in segmentation:
        if s["held"] is False:
            regressions.append(f"segmentation invariant violated: {s['invariant']} — {s['evidence']}")
    for i in intents:
        if i.get("valid") is False or i.get("validation_errors"):
            gate_failures.append(
                f"path intent {str(i.get('id'))!r} is invalid: "
                + ", ".join(str(x) for x in (i.get("validation_errors") or ["invalid catalog row"])))
        if i.get("regressed"):
            regressions.append(f"path intent '{i.get('id')}' regressed "
                               f"({i.get('old_verdict')} -> {i.get('new_verdict')})")
    if schema and schema.get("status") == "mismatch" and not schema.get("override"):
        gate_failures.append(
            "snapshot schema mismatch was not overridden: "
            + (schema.get("message") or "the snapshots are not safely comparable"))

    # ---- blind spots: every one NAMED (>0 open => never PASS) ----
    blind_spots: List[str] = []
    if not flows["assessed"]:
        blind_spots.append("computed reachability not assessed — "
                           + ("no routes collected" if flows["subnets_total"] == 0 else
                              f"only {flows['subnets_total']} subnet(s) collected, no inter-subnet flow to test"))
    elif flows["capped"]:
        blind_spots.append(f"reachability sample capped: {flows['subnets_tested']} of "
                           f"{flows['subnets_total']} subnet(s) tested — untested subnets are unverified")
    for f in flows["inconclusive"]:
        blind_spots.append(f"flow {f['src']} -> {f['dst']} inconclusive: {f['reason']}")
    for s in segmentation:
        if s["held"] == "not_evaluable":
            blind_spots.append(f"segmentation invariant not evaluable: {s['invariant']} — {s['evidence']}")
    for i in intents:
        if i.get("new_verdict") == "not_observed":
            blind_spots.append(f"path intent '{i.get('id')}' not observed after the change — "
                               "it cannot be re-certified")
    if intents_failed:
        blind_spots.append("path intents supplied but could not be evaluated — the catalog is unverified")

    for item in integrity_failures:
        blind_spots.append(f"assessment integrity unavailable: {item}")
    if schema and schema.get("status") not in ("", "ok"):
        blind_spots.append(
            f"schema compatibility {schema.get('status')}: "
            f"{schema.get('message') or 'compatibility was not proven'}"
            + (" (explicit override recorded; PASS remains withheld)" if schema.get("override") else ""))

    # ---- verdict (the exact coverage-honest encoding) ----
    n_definitive = (flows["preserved"] + flows["both_unreachable"] + len(flows["changed"])
                    + sum(1 for s in segmentation if s["held"] in (True, False))
                    + sum(1 for i in intents if i.get("new_verdict") in ("pass", "fail")))
    if regressions or gate_failures:
        verdict = "FAIL"
        note = (f"{len(regressions)} regression(s): the candidate change demonstrably breaks the network — "
                "do not proceed. Each regression is cited below.")
        if gate_failures:
            n_block = len(regressions) + len(gate_failures)
            note = (f"{n_block} blocking condition(s): the candidate change or its validation inputs "
                    "are not safe to approve - do not proceed. Each condition is cited below.")
    elif integrity_failures:
        verdict = "INDETERMINATE"
        note = (f"{len(integrity_failures)} assessment-integrity failure(s) make the certificate "
                "unverifiable. Missing/failed analyses were not interpreted as clean; repair and re-run.")
    elif n_definitive == 0:
        verdict = "INDETERMINATE"
        note = ("nothing was definitively checkable across the pair — the certificate asserts NOTHING "
                "(this is not a pass; collect routes/segmentation evidence and re-run)")
    elif blind_spots:
        verdict = "CONDITIONAL"
        note = (f"no regressions across {n_definitive} definitive check(s), but {len(blind_spots)} named "
                "blind spot(s) remain open — clear or accept each before the window")
    else:
        verdict = "PASS"
        note = (f"all {n_definitive} definitive check(s) clean and no open blind spots "
                "(within the disclosed bounded sample)")

    return {
        "schema": SCHEMA,
        "verdict": verdict,
        "verdict_note": note,
        "flows": flows,
        "segmentation": segmentation,
        "intents": intents,
        "regressions": regressions,
        "gate_failures": gate_failures,
        "blind_spots": blind_spots,
        "stamps": {"before": _stamp(before), "after": _stamp(after)},
        "integrity": {"ok": not integrity_failures, "failures": integrity_failures},
        "source_binding": source_binding,
        "schema_status": schema,
    }


# ============================================================================================
# Single-snapshot pre-window READINESS FREEZE (roadmap: the perishable prediction half of a
# calibration row). `compute_precert` above certifies a before/after PAIR; this freezes ONE
# snapshot's migration-readiness prediction, hashed so it cannot be retrofitted after the outcome
# is known (the anti-hindsight point). It reads the snapshot's PRE-computed `migration_readiness`
# (the serialized `analyze.compute_migration_readiness` output) — it does NOT re-run analysis.
# ============================================================================================

# Worst-first ranking; accept the snapshot's literal "NOT READY" and the calibration-canonical "NOT_READY".
_READINESS_RANK = {"NOT READY": 2, "NOT_READY": 2, "CAUTION": 1, "READY": 0}
#: The distribution bucket for a move-group whose readiness label is absent or unrecognised. It is a
#: COVERAGE state, not a readiness rating — it is never ranked (an unassessed group cannot be scored
#: better or worse than an assessed one), it forbids a READY verdict, and it keeps
#: `readiness_distribution` summing to `n_groups` so a dropped group is visible in the certificate.
UNRATED = "UNRATED"


def _canon_readiness(v: Any) -> str:
    """A move-group readiness label normalized to READY / CAUTION / NOT READY, or '' if unrecognized."""
    s = str(v or "").strip().upper().replace("_", " ")
    return s if s in ("READY", "CAUTION", "NOT READY") else ""


def _prediction_hash(payload: dict) -> str:
    """SHA-256 over the canonical prediction payload — the tamper-evident freeze token. Deterministic:
    the same snapshot always yields the same hash, so a committed cert is independently re-verifiable, and
    any post-hoc edit to the frozen prediction changes the hash. Excludes `mode`/`verdict_note` (metadata),
    so a shadow and a real freeze of the SAME prediction share a hash."""
    canon = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canon.encode("utf-8")).hexdigest()


_READINESS_PAYLOAD_KEYS = (
    "verdict",
    "n_groups",
    "readiness_distribution",
    "groups",
    "coverage",
    "blind_spots",
    "stamp",
    "integrity",
    "source_binding",
    "schema_status",
)


def _readiness_certificate_hash(cert: Dict[str, Any]) -> str:
    """Bind the complete decision-bearing certificate envelope.

    ``prediction_hash`` deliberately remains comparable between a shadow and real run.  This
    second hash has a different job: it binds that prediction to the schema, operating mode,
    explanatory note, and exact source binding so a shadow certificate cannot be relabelled as a
    real pre-window freeze without invalidating the envelope.
    """
    envelope = {key: value for key, value in cert.items() if key != "certificate_hash"}
    return _prediction_hash(envelope)


def verify_readiness_freeze(cert: Any) -> Tuple[bool, str]:
    """Verify both hashes on a serialized readiness-freeze certificate."""
    if not isinstance(cert, dict):
        return False, "certificate must be a JSON object"
    if cert.get("schema") != READINESS_SCHEMA:
        return False, f"unsupported schema: {cert.get('schema')!r}"
    if cert.get("mode") not in ("shadow", "real"):
        return False, f"invalid mode: {cert.get('mode')!r}"
    payload = {key: cert.get(key) for key in _READINESS_PAYLOAD_KEYS}
    if cert.get("prediction_hash") != _prediction_hash(payload):
        return False, "prediction_hash does not match the prediction payload"
    if cert.get("certificate_hash") != _readiness_certificate_hash(cert):
        return False, "certificate_hash does not match the full certificate envelope"
    return True, "ok"


def compute_readiness_freeze(snap: Dict[str, Any], *, mode: str = "shadow",
                             source_hash: Optional[str] = None,
                             schema_status: Any = None) -> dict:
    """Pre-window readiness FREEZE for one snapshot (schema 'precert-readiness/1').

    Coverage-honest, exact:
      * verdict = the WORST move-group readiness (never rated better than its weakest group);
      * no per-move-group readiness at all -> INDETERMINATE (asserts NOTHING — this is not READY);
      * a move-group whose readiness label is ABSENT or UNRECOGNISED is UNRATED: it is counted in
        `readiness_distribution` (which therefore always sums to `n_groups`), NAMED in `blind_spots`,
        and it forbids a READY verdict — an unassessed group is not evidence of readiness, and a
        freeze is the tamper-evident record a cutover is authorised against. (Before this, such a
        group silently contributed to nothing: `_READINESS_RANK.get('', -1)` never beat the seed and
        `''` is not a key of `dist`, so 2 READY + 2 never-assessed groups certified READY.)
      * every not-collected device is NAMED as a blind spot (its readiness inputs are absent, so any
        move-group containing it is a PARTIAL prediction — absence of evidence is not readiness).
    `mode='real'` marks a genuine pre-cutover freeze (commit it BEFORE the window; the outcome later
    completes a REAL calibration row); `mode='shadow'` (default) is a mechanism-validation run that is
    NOT a REAL calibration input. Pure JSON types; total on malformed input; offline, no egress."""
    s = snap if isinstance(snap, dict) else {}
    integrity = _assessment_integrity(s, ("migration_readiness",))
    schema = _normalize_schema_status(schema_status)
    source_hash_issues: List[str] = []
    source_binding = _normalize_source_hashes(
        {} if source_hash is None else {"snapshot": source_hash},
        issues=source_hash_issues,
    )
    if source_hash_issues:
        integrity["failures"].extend(source_hash_issues)
        integrity["ok"] = False
    groups_in = s.get("migration_readiness")
    groups_in = groups_in if isinstance(groups_in, list) else []

    groups: List[dict] = []
    dist = {"READY": 0, "CAUTION": 0, "NOT READY": 0, UNRATED: 0}
    unrated: List[str] = []
    worst_rank, worst = -1, ""
    for row_index, g in enumerate(groups_in):
        if not isinstance(g, dict):
            label = f"malformed row #{row_index + 1}"
            dist[UNRATED] += 1
            unrated.append(
                f"move-group {label} is UNRATED (expected an object, got "
                f"{type(g).__name__}) - malformed readiness evidence cannot be dropped or "
                "certified READY"
            )
            groups.append({
                "group": label,
                "readiness": UNRATED,
                "n_fail": 0,
                "n_warn": 0,
                "blocking": [],
            })
            continue
        rd = _canon_readiness(g.get("readiness"))
        if rd in dist:
            dist[rd] += 1
        else:                              # absent or unrecognised label -> UNRATED, never dropped
            dist[UNRATED] += 1
            raw = str(g.get("readiness", "") or "").strip()
            unrated.append(f"move-group {str(g.get('group'))!r} is UNRATED ("
                           + (f"unrecognised readiness label {raw!r}" if raw else "no readiness label")
                           + ") - it was never assessed, so it can neither be certified READY nor "
                             "counted toward one")
        rank = _READINESS_RANK.get(rd, -1)
        if rank > worst_rank:
            worst_rank, worst = rank, rd
        blocking = [c.get("check") for c in _dict_rows(g.get("checks"))
                    if str(c.get("status", "")).lower() in ("fail", "warn")]
        # _as_num, not int(): a raw int() on a device-derived count raises OverflowError on the bare JSON
        # Infinity json.loads accepts, ValueError on NaN / a non-numeric string, and TypeError on a
        # dict/list -- and this runs inside write_diff_workbook, so one bad leaf aborted the whole
        # --compare deliverable (and 500'd the webapp diff route) instead of degrading that one field.
        groups.append({"group": g.get("group"), "readiness": rd or UNRATED,
                       "n_fail": int(_as_num(g.get("n_fail"), 0)), "n_warn": int(_as_num(g.get("n_warn"), 0)),
                       "blocking": blocking})

    # Coverage-honest blind spots: NAME every not-collected device (its readiness inputs are absent).
    cc = _as_dict(s.get("collection_completeness"))
    summ = _as_dict(cc.get("summary"))
    not_collected = sorted(str(d.get("host")) for d in _dict_rows(cc.get("devices"))
                           if str(d.get("status", "")).lower().startswith("not"))
    n_missing = int(_as_num(summ.get("not_collected"), 0)) or len(not_collected)
    blind_spots: List[str] = list(unrated)
    if n_missing:
        blind_spots.append(
            f"{n_missing} of {summ.get('inventory', '?')} inventoried device(s) were not collected "
            f"(named in coverage.not_collected_hosts) - their readiness inputs are absent, so any "
            f"move-group containing them is a PARTIAL prediction; absence of evidence is not readiness.")
    for item in integrity["failures"]:
        blind_spots.append(f"assessment integrity unavailable: {item}")
    if schema and schema.get("status") not in ("", "ok"):
        blind_spots.append(
            f"schema compatibility {schema.get('status')}: "
            f"{schema.get('message') or 'compatibility was not proven'}")

    if not groups:
        verdict = "INDETERMINATE"
        note = ("no per-move-group readiness in the snapshot - the freeze asserts NOTHING "
                "(this is not READY; re-run analysis and re-freeze)")
    else:
        verdict = worst or "INDETERMINATE"
        if unrated and verdict == "READY":
            # A worst-of over the RATED groups only is a lower bound: an unassessed group could be
            # the worst one. Never certify READY across an open blind spot (the same rule
            # compute_precert encodes as "a certificate is never PASS with an open blind spot").
            verdict = "INDETERMINATE"
        note = (f"worst-of {len(groups)} move-group(s): {dist['NOT READY']} NOT READY, "
                f"{dist['CAUTION']} CAUTION, {dist['READY']} READY"
                + (f", {dist[UNRATED]} UNRATED (never assessed - named in blind_spots; a READY "
                   "verdict is withheld while any group is unrated)" if unrated else "")
                + (f"; {n_missing} device(s) uncollected (blind spots named)" if n_missing else ""))
    if (integrity["failures"] or (schema and schema.get("status") not in ("", "ok"))) \
            and verdict != "NOT READY":
        verdict = "INDETERMINATE"
        note = ("readiness certification withheld because assessment/schema integrity is unavailable; "
                "known NOT READY evidence would still dominate, but no READY/CAUTION conclusion is issued. "
                + note)

    stamp = _stamp(s)
    stamp["collected_at"] = str(s.get("collected_at", "") or "")
    stamp["snapshot_schema"] = str(s.get("schema", "") or "")

    payload = {
        "verdict": verdict,
        "n_groups": len(groups),
        "readiness_distribution": dist,
        "groups": groups,
        "coverage": {"inventory": summ.get("inventory"), "collected": summ.get("complete"),
                     "not_collected": n_missing, "not_collected_hosts": not_collected},
        "blind_spots": blind_spots,
        "stamp": stamp,
        "integrity": integrity,
        "source_binding": source_binding,
        "schema_status": schema,
    }
    cert = {"schema": READINESS_SCHEMA,
            "mode": mode if mode in ("shadow", "real") else "shadow",
            "verdict_note": note}
    cert.update(payload)
    cert["prediction_hash"] = _prediction_hash(payload)   # hashes the prediction, not the mode/note
    cert["certificate_hash"] = _readiness_certificate_hash(cert)
    return cert


def main(argv: Optional[List[str]] = None) -> int:
    """CLI: freeze a single snapshot's readiness prediction. Writes the cert JSON and prints a summary.
    `--mode real` is a genuine pre-cutover freeze (commit the cert BEFORE the window); the default
    `shadow` validates the mechanism and is never a REAL calibration input."""
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m cisco_toolkit.precert",
        description="Pre-window readiness FREEZE from one snapshot (schema precert-readiness/1).")
    ap.add_argument("snapshot", help="path to a .snapshot.json")
    ap.add_argument("--mode", choices=("shadow", "real"), default="shadow",
                    help="shadow (default) = mechanism validation, NOT a REAL calibration input; "
                         "real = a genuine pre-cutover freeze (commit it before the maintenance window).")
    ap.add_argument("--out", default=None,
                    help="cert output path (default: <snapshot>.precert-readiness.json)")
    args = ap.parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        with open(args.snapshot, "rb") as f:
            snapshot_bytes = f.read()
        snap = json.loads(snapshot_bytes.decode("utf-8"))
    except (OSError, ValueError) as e:
        print(f"[precert-readiness] cannot read snapshot: {e}")
        return 2
    source_hash = "sha256:" + hashlib.sha256(snapshot_bytes).hexdigest()
    cert = compute_readiness_freeze(snap, mode=args.mode, source_hash=source_hash)
    verified, reason = verify_readiness_freeze(cert)
    if not verified:
        print(f"[precert-readiness] internal certificate verification failed: {reason}")
        return 2
    out = args.out or (os.path.splitext(args.snapshot)[0] + ".precert-readiness.json")
    try:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(cert, f, ensure_ascii=True, indent=2)
    except OSError as e:
        print(f"[precert-readiness] cannot write certificate: {e}")
        return 2
    d = cert["readiness_distribution"]
    cov = cert["coverage"]
    print(f"[precert-readiness] mode={cert['mode']}  verdict={cert['verdict']}  groups={cert['n_groups']}")
    print(f"  distribution : {d['NOT READY']} NOT READY / {d['CAUTION']} CAUTION / {d['READY']} READY"
          f" / {d.get(UNRATED, 0)} UNRATED (never assessed)")
    print(f"  coverage     : {cov['collected']} of {cov['inventory']} collected; "
          f"{cov['not_collected']} uncollected (blind spots: {len(cert['blind_spots'])})")
    print(f"  prediction_hash: {cert['prediction_hash']}")
    print(f"  written      : {out}")
    if cert["mode"] == "shadow":
        print("  NOTE: shadow mode - NOT a REAL calibration row (0 REAL is unchanged). It validates the "
              "freeze; a REAL row needs --mode real, committed before the window, plus the actual outcome.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
