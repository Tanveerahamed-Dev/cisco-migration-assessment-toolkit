"""Adapter to the existing `cisco_toolkit` engine.

All coupling to the CLI engine lives here: path bootstrap + the handful of functions the web layer
re-uses. Nothing in `cisco_toolkit` is modified — we only call its public snapshot/diff/trend/explorer
helpers, so the 260-test golden contract is untouched.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# webapp/backend/engine.py -> webapp/backend -> webapp -> <repo root that contains cisco_toolkit>
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cisco_toolkit import analyze as _analyze  # noqa: E402  (after path bootstrap)
from cisco_toolkit import comparison as _comparison  # noqa: E402
from cisco_toolkit import html as _html  # noqa: E402
from cisco_toolkit import impact_assessability as _impact_assessability  # noqa: E402
from cisco_toolkit.textutils import _as_num as _as_num  # noqa: E402  (shared fail-soft numeric coercion)
from cisco_toolkit import __version__ as ENGINE_SCHEMA_VERSION  # noqa: E402,F401  (re-exported for the app)
from cisco_toolkit.precert import schema_compat_status  # noqa: E402  (P3-E2 schema gate)
from cisco_toolkit import protocol_assurance as _protocol_assurance  # noqa: E402
from cisco_toolkit import ui_projection as _ui_projection  # noqa: E402

def ui_projection(snapshot: Any, host: str | None = None) -> Dict[str, Any]:
    """Delegate a whole document to its engine owner; do not reconstruct view context."""
    if host is not None:
        return _ui_projection.project_device(snapshot, host)
    return _ui_projection.project(snapshot)


def ui_projection_schema() -> Dict[str, Any]:
    """Fresh owner schema for the API's cached validator and mechanical OpenAPI projection."""
    return _ui_projection.ui_projection_schema()


def ui_projection_path(snapshot: Any, src_ip: str, dst_ip: str) -> Dict[str, Any]:
    """Delegate route investigation and every disclosed result to its engine owner."""
    return _ui_projection.project_path(snapshot, src_ip, dst_ip)


def failure_impact_projection(snapshot: Any) -> Dict[str, Any]:
    """The engine-owned ``failure_impact`` FactList (``ui_projection/1``) for a stored snapshot.

    Each row is built by the projection's one shared failure-impact row builder, the row the fleet topology and
    the device page publish, so every cell carries its own state and reason: the producer's INDETERMINATE rows,
    rows older than its off-scan marker, unreadable counts, a switch without its scoped interface running-config,
    a partial simulation, an uncollected neighbour and a duplicated host are withheld there, never here. An
    AssessHub surface that shows or ranks failure impact reads it through this call and never re-derives a value
    from the raw stored rows. Pure and total by the projection's contract; nothing is re-simulated."""
    return _ui_projection.project_topology(snapshot)["failure_impact"]


def fleet_blind_spot_rows(snapshot: Any) -> List[int]:
    """The ``collection_completeness.devices`` rows the projection's fleet qualifier reads as a partial or
    not-collected device, by index. Every other witness that qualifier cites is a row, list or section it cannot read
    as one, so a surface wording the qualifier tells the two kinds apart by this one owner, never by re-reading the
    stored rows."""
    return _ui_projection.fleet_blind_spot_rows(snapshot)


# The engine owner's wave rule (W48 follow-up): how a migration wave's failure-impact rows add up to one worst-case
# figure, and the projection's fleet qualifier counts it takes (impact_assessability.fleet_blind over the projected
# list and fleet_blind_spot_rows above: blind devices, and records it cannot read as one). The cutover plan applies
# the rule the MOP applies, to the projection's rows where the MOP reads the owner's verdicts.
WaveRow = _impact_assessability.WaveRow
wave_blast = _impact_assessability.wave_blast
failure_impact_fleet_blind = _impact_assessability.fleet_blind
IMPACT_FLEET_BLIND_CAVEAT = _impact_assessability.FLEET_BLIND_CAVEAT
IMPACT_R_FLEET_BLIND = _impact_assessability.R_WAVE_FLEET_BLIND
IMPACT_R_FLEET_BLIND_UNREAD = _impact_assessability.R_WAVE_FLEET_BLIND_UNREAD
IMPACT_R_WAVE_ZERO = _impact_assessability.R_WAVE_ZERO
IMPACT_R_WAVE_NONE = _impact_assessability.R_WAVE_NONE


# ---------------------------------------------------------------------------------------------------------------
# W50: the live, DISPLAY-ONLY interpretation of the failure-impact rows a comparison binds
# ---------------------------------------------------------------------------------------------------------------
#: A comparison's ``operator_evidence.rehearsal.impacts`` binds the after snapshot's stored failure_impact rows as
#: raw EVIDENCE (protocol_assurance._rehearsal_impact_evidence_v1), because a stored execution receipt is re-verified
#: by recomputing it on every read and so must never depend on evolving code. What each row MEANS (a measurement, a
#: lower bound, not assessed, ambiguous) is decided here, at request time, by the engine owner of row assessability
#: (cisco_toolkit/impact_assessability.py) from the comparison's bound after snapshot. The result is the
#: ``impacts_view`` an AssessHub response carries BESIDE a comparison (an execution receipt row, a trend pair), never
#: inside it. It is never stored, never hashed and never an input to receipt verification: the comparison, its
#: detached envelope and every receipt digest are byte-identical with or without it
#: (webapp/tests/test_compare_execution_receipts.py, tests/test_operator_evidence_contract.py). Because it is
#: computed live, a later owner change reinterprets every stored receipt's evidence without touching the receipt.
REHEARSAL_IMPACTS_VIEW_SCHEMA = "rehearsal_impacts_view/1"
#: The cells of an impacts_view row: the owner's display cells (every blast-radius measure, then the detail).
IMPACTS_VIEW_CELLS: Tuple[str, ...] = tuple(_impact_assessability.CELL_FIELDS)
#: Why an impacts_view is unavailable, by code (closed). An unavailable view never falls back to the raw rows.
IMPACTS_VIEW_UNAVAILABLE: Dict[str, str] = {
    "binding_unreadable": (
        "the comparison names no readable after-snapshot binding (snapshot id and SHA-256), so the evidence "
        "to interpret cannot be identified"),
    "snapshot_missing": (
        "the bound after snapshot is no longer stored, so its failure-impact rows cannot be interpreted"),
    "snapshot_unreadable": "the bound after snapshot could not be read",
    "snapshot_mismatch": (
        "the stored after snapshot's bytes no longer match the SHA-256 the comparison binds, so interpreting "
        "them would describe different evidence"),
    "owner_fault": (
        "the engine owner of row assessability could not interpret the bound evidence"),
}


def rehearsal_impacts_view_unavailable(code: str) -> Dict[str, Any]:
    """An explicitly unavailable impacts_view (``code`` is a key of :data:`IMPACTS_VIEW_UNAVAILABLE`). DISPLAY ONLY."""
    return {
        "schema": REHEARSAL_IMPACTS_VIEW_SCHEMA,
        "display_only": True,
        "available": False,
        "code": code,
        "reason": IMPACTS_VIEW_UNAVAILABLE[code],
    }


def _impacts_view_disclosed(verdict: Any) -> Dict[str, Any]:
    """How one row is NAMED wherever the view discloses it: its stored position, the host the owner publishes
    (``None`` when it withholds it), the verdict, the owner's state and the reason codes with the count each quotes."""
    return {
        "index": verdict.index,
        "host": None if verdict.withholds("host") else verdict.host,
        "assessable": verdict.assessable,
        "state": verdict.state,
        "reasons": [{"code": code, "n": n} for code, n in verdict.code_counts],
    }


def rehearsal_impacts_view(snapshot: Any, *, source_sha256: str) -> Dict[str, Any]:
    """The engine owner's live interpretation of `snapshot`'s stored failure_impact rows. DISPLAY ONLY (see above).

    `snapshot` must be the comparison's bound after snapshot and `source_sha256` the SHA-256 that comparison binds
    for it; the caller establishes that binding (:func:`receipt_impacts_view`) and a display shows the view only
    when the two agree. Every stored row is interpreted, an unreadable one included (the owner holds it). Every
    decision is the owner's (``cisco_toolkit/impact_assessability.py``); this function only lays it out:

    * ``rows``: each row in the owner's ranking order (``ranking_order``) with its verdict, state and reason codes,
      whether the owner ranks it (``ranks``) and one cell per :data:`IMPACTS_VIEW_CELLS`, each its ``cell_reading``;
    * ``unranked``: every row the owner does not rank (``unranked``: held, ambiguous, a withheld or zero floor, an
      unreadable row), in stored order, so a display that caps ``rows`` still names each of them;
    * ``unreadable``: the stored position of every row that is not an object (``RowVerdict.readable``), the same rule
      as ``n_rows_unreadable``, so the census and the list never diverge (a failed section included);
    * ``n_rows_total`` and ``counts`` (per verdict) census every stored row; ``section_state`` says whether the section
      itself could be read, so an absent or failed section never reads as no impact; ``state_words`` is the owner's
      word for each state token (``STATE_WORD``)."""
    # every reading CALLS the owner through its module alias, the route the W48 guard admits (it does not resolve a
    # local alias of the module, which would leave this display path unrouted)
    verdicts = _impact_assessability.assess_failure_impact(snapshot)
    rows = [{
        **_impacts_view_disclosed(verdict),
        "ranked": _impact_assessability.ranks(verdict),
        "cells": {field: _impact_assessability.cell_reading(verdict, field)._asdict() for field in IMPACTS_VIEW_CELLS},
    } for verdict in sorted(verdicts, key=_impact_assessability.ranking_order)]
    unreadable = [verdict.index for verdict in verdicts if not verdict.readable]
    return {
        "schema": REHEARSAL_IMPACTS_VIEW_SCHEMA,
        "display_only": True,
        "available": True,
        "owner": _impact_assessability.SCHEMA,
        "source_sha256": source_sha256,
        # The owner's word for each withheld state token, sent with the view so the SPA holds no copy of them (a TS
        # literal naming not_collected/analysis_unavailable would read as a hand list of the protocol receipt's
        # vocabulary to that receipt's hand-list scanner); reason phrases and verdict labels are pinned SPA tables.
        "state_words": dict(_impact_assessability.STATE_WORD),
        "section_state": _impact_assessability.section_state(snapshot),
        "n_rows_total": len(verdicts),
        "n_rows_unreadable": len(unreadable),
        "unreadable": unreadable,
        "counts": {k: sum(1 for verdict in verdicts if verdict.assessable == k) for k in _impact_assessability.VERDICTS},
        "rows": rows,
        "unranked": [_impacts_view_disclosed(verdict) for verdict in _impact_assessability.unranked(verdicts)],
    }


def comparison_after_binding(comparison: Any) -> Optional[Tuple[int, str]]:
    """``(snapshot_id, sha256)`` of the after snapshot a comparison binds (``comparison_admission.source_binding``),
    whose stored rows its ``operator_evidence.rehearsal.impacts`` copies; ``None`` when it cannot be read."""
    admission = comparison.get("comparison_admission") if isinstance(comparison, dict) else None
    binding = admission.get("source_binding") if isinstance(admission, dict) else None
    after = binding.get("after") if isinstance(binding, dict) else None
    snapshot_id = after.get("snapshot_id") if isinstance(after, dict) else None
    sha256 = after.get("sha256") if isinstance(after, dict) else None
    if type(snapshot_id) is not int or not isinstance(sha256, str) or not sha256:
        return None
    return snapshot_id, sha256


def receipt_impacts_view(
        comparison: Any,
        load_bound_snapshot: Callable[[int], Optional[Tuple[Dict[str, Any], Dict[str, Any]]]]) -> Dict[str, Any]:
    """The live impacts_view of a STORED comparison: its bound after snapshot is loaded by id
    (``Store.get_bound_snapshot``) and interpreted only when its stored bytes still carry the SHA-256 the comparison
    binds. Otherwise the view is explicitly unavailable with its reason, never the raw rows. DISPLAY ONLY: the
    receipt is read, never written, and nothing here feeds its verification."""
    bound_after = comparison_after_binding(comparison)
    if bound_after is None:
        return rehearsal_impacts_view_unavailable("binding_unreadable")
    snapshot_id, sha256 = bound_after
    try:
        bound = load_bound_snapshot(snapshot_id)
    except Exception:   # noqa: BLE001 -- a display must degrade to "unavailable", never fail the receipt read
        return rehearsal_impacts_view_unavailable("snapshot_unreadable")
    if bound is None:
        return rehearsal_impacts_view_unavailable("snapshot_missing")
    snapshot, binding = bound
    if not isinstance(binding, dict) or binding.get("sha256") != sha256:
        return rehearsal_impacts_view_unavailable("snapshot_mismatch")
    return _safe_rehearsal_impacts_view(snapshot, sha256)


def _safe_rehearsal_impacts_view(snapshot: Any, sha256: str) -> Dict[str, Any]:
    try:
        return rehearsal_impacts_view(snapshot, source_sha256=sha256)
    except Exception:   # noqa: BLE001 -- the owner is total by contract; a fault is shown as unavailable
        return rehearsal_impacts_view_unavailable("owner_fault")


def bind_ui_projection_snapshot(raw: bytes) -> Dict[str, Any]:
    """Preserve the exact-byte snapshot custody used by the store's bound reader."""
    return _protocol_assurance.bind_snapshot_json_bytes(raw)


# Canonical hostname normalisation — reuse the engine's own so the web layer groups hosts identically.
canon_host = _analyze._canon_host
as_num = _as_num   # fail-soft leaf-count coercion (rejects the JSON Infinity/NaN a raw int() would 500 on)
compute_cable_map = _analyze.compute_cable_map   # EDA-style physical cable-map SSOT (explorer + webapp share it)
cable_map_of_snapshot = _analyze.cable_map_of_snapshot   # stored-snapshot entry point (rehydrates pre-feature uploads)
trend_point = _html._trend_point
compute_snapshot_delta = _html.compute_snapshot_delta
compute_campaign_trend = _html.compute_campaign_trend
redact_snapshot = _html.redact_snapshot


def compute_current_baseline_gate(validation_plan: Any) -> Dict[str, Any]:
    """Return the engine-owned current-baseline cutover verdict for a validation plan.

    Keeping this call behind the adapter gives every AssessHub projection the same owner as the CLI,
    workbook, and explorer instead of teaching the web layer its own verdict vocabulary.
    """
    return _analyze.compute_current_baseline_gate(validation_plan)


def classify_current_baseline_item(item: Any) -> str:
    """Expose the engine's total typed-state/exact-marker classifier to AssessHub."""
    return _analyze.classify_current_baseline_item(item)


def render_explorer_html(
        snapshot: Dict[str, Any],
        label: str,
        *,
        protocol_assurance_bundle: Optional[Dict[str, Any]] = None) -> str:
    """Render the self-contained Blast-Radius Explorer for a stored snapshot, returned as a string.

    Re-uses `html.write_html_explorer` (which embeds a slimmed snapshot into the packaged template) by
    writing to a temp file and reading it back — the file the web layer serves is byte-identical to the
    CLI's `..._explorer.html`."""
    fd, path = tempfile.mkstemp(suffix=".html", prefix="assesshub_explorer_")
    os.close(fd)
    try:
        _html.write_html_explorer(
            path,
            snapshot,
            label,
            protocol_assurance_bundle=protocol_assurance_bundle,
        )
        return Path(path).read_text(encoding="utf-8")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _schema_compat(snaps: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute the webapp's non-overridable pair/series schema verdict once."""
    status, message = schema_compat_status(list(snaps or []))
    return {"status": status, "message": message, "override": False}


def _with_schema_compat(result: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
    """Surface the exact compatibility verdict already consumed by the decision computation."""
    if isinstance(result, dict):
        result["schema_compat"] = {
            "status": schema["status"],
            "message": schema["message"],
        }
    return result


#: The wording `compute_campaign_trend` uses for a metric it could not compare. The web campaign view
#: renders `verdict_note` as its only prose, so this phrase is what a reader sees; the structural
#: `not_comparable` key is its machine-readable twin.
_NOT_COMPARABLE_PHRASE = "NOT COMPARABLE"

_PERSISTED_SNAPSHOT_SOURCE = _protocol_assurance.PERSISTED_SOURCE
_TREND_RECEIPT_SCHEMA = "campaign_adjacent_comparison_set/1"
_TREND_PAIR_SCHEMA = "campaign_adjacent_comparison/1"


def _matching_persisted_binding(snapshot: Any, binding: Any) -> bool:
    """Require one complete storage receipt for the exact bytes behind ``snapshot``.

    A serialized ``BoundSnapshot`` is deliberately just a dict, so neither a caller-provided hash nor
    an embedded ``source`` string can recreate storage custody. Trend receipts use the same
    process-local marker as the native protocol-family owners and compare the public receipt to it.
    """
    if not isinstance(snapshot, dict) or not isinstance(binding, dict):
        return False
    marker = _protocol_assurance.bound_snapshot_source(snapshot)
    required = {
        "source", "sha256", "bytes", "snapshot_id", "campaign_id",
        "engagement_id", "label", "script_version",
    }
    return (
        marker.get("source_bound") is True
        and set(binding) == required
        and binding.get("source") == _PERSISTED_SNAPSHOT_SOURCE
        and binding.get("sha256") == marker.get("sha256")
        and type(binding.get("bytes")) is int
        and binding.get("bytes") == marker.get("bytes")
        and type(binding.get("snapshot_id")) is int
        and type(binding.get("campaign_id")) is int
        and isinstance(binding.get("engagement_id"), str)
        and bool(binding["engagement_id"].strip())
        and isinstance(binding.get("label"), str)
        and bool(binding["label"].strip())
        and isinstance(binding.get("script_version"), str)
        and bool(binding["script_version"].strip())
        and binding.get("script_version") == snapshot.get("script_version")
    )


def _trend_comparison_receipts(
        snapshots: List[Dict[str, Any]],
        source_bindings: Optional[List[Dict[str, Any]]]) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Compose complete oldest-to-newest canonical receipts for every adjacent pair.

    The result is intentionally separate from the legacy trajectory owner. It never synthesizes a
    binding for callers that supplied none, and it never treats a detached dict/hash pair as proof of
    persisted source custody.
    """
    n_pairs = max(0, len(snapshots) - 1)
    unavailable = {
        "schema": _TREND_RECEIPT_SCHEMA,
        "status": "not_verified",
        "n_pairs_total": n_pairs,
        "n_pairs_returned": 0,
        "complete": False,
        "note": (
            "Canonical adjacent comparison receipts were not produced because a complete ordered "
            "set of exact-byte persisted source bindings was not available."
        ),
    }
    if n_pairs == 0:
        return [], unavailable
    if (
        not isinstance(source_bindings, list)
        or len(source_bindings) != len(snapshots)
        or any(
            not _matching_persisted_binding(snapshot, binding)
            for snapshot, binding in zip(snapshots, source_bindings)
        )
    ):
        return [], unavailable

    campaign_ids = {binding["campaign_id"] for binding in source_bindings}
    engagement_ids = {binding["engagement_id"] for binding in source_bindings}
    snapshot_ids = [binding["snapshot_id"] for binding in source_bindings]
    coherence_failures: List[str] = []
    if len(campaign_ids) != 1:
        coherence_failures.append("source bindings cross campaign identities")
    if len(engagement_ids) != 1:
        coherence_failures.append("source bindings cross engagement identities")
    if len(set(snapshot_ids)) != len(snapshot_ids):
        coherence_failures.append("source bindings repeat a snapshot identity")

    entries: List[Dict[str, Any]] = []
    for index in range(n_pairs):
        before_binding = source_bindings[index]
        after_binding = source_bindings[index + 1]
        comparison = compare_bound_pair(
            snapshots[index],
            snapshots[index + 1],
            before_binding=before_binding,
            after_binding=after_binding,
        )
        entries.append({
            "schema": _TREND_PAIR_SCHEMA,
            "index": index,
            "from": f"C{index + 1}",
            "to": f"C{index + 2}",
            "before_snapshot_id": before_binding["snapshot_id"],
            "after_snapshot_id": after_binding["snapshot_id"],
            "before_label": before_binding["label"],
            "after_label": after_binding["label"],
            "comparison": comparison,
            # DISPLAY ONLY (W50): the owner's live reading of the after snapshot's failure-impact rows, beside the
            # comparison and never inside it, so the comparison stays exactly the /api/compare document.
            "impacts_view": _safe_rehearsal_impacts_view(snapshots[index + 1], after_binding["sha256"]),
        })

    status = "not_comparable" if coherence_failures else "verified"
    note = (
        "Canonical comparisons were produced from the exact persisted bytes for every adjacent "
        "campaign pair."
        if not coherence_failures else
        "Canonical adjacent comparisons were retained, but the series is NOT COMPARABLE: "
        + "; ".join(coherence_failures) + "."
    )
    return entries, {
        "schema": _TREND_RECEIPT_SCHEMA,
        "status": status,
        "n_pairs_total": n_pairs,
        "n_pairs_returned": len(entries),
        "complete": len(entries) == n_pairs,
        "note": note,
    }


def _carry_not_comparable(result: Dict[str, Any]) -> Dict[str, Any]:
    """Guarantee the campaign trend's NOT-COMPARABLE coverage disclosure survives to the web exit.

    The workbook writer prints `verdict_note` and the web campaign view prints `verdict_note`, so
    today both carry it — but only because the engine happens to put the sentence in the prose. This
    adapter is the web's ONLY route to the trend, and it used to pass the dict through unexamined:
    an engine that stopped publishing the disclosure, or a `not_comparable` list the prose failed to
    mention, would have rendered a verdict with NO coverage caveat and nothing would have noticed.

    So it FAILS CLOSED, in both directions:

    * `not_comparable` missing or malformed -> normalised to empty lists with
      ``disclosure_available: False``, and the note SAYS the coverage disclosure is unavailable
      (absence of the caveat must not read as "every metric was comparable");
    * `not_comparable` populated but the prose does not carry the phrase -> the sentence is restated
      in `verdict_note`, because that is the string the UI renders.

    A fully-comparable campaign is untouched — no caveat is invented where there is nothing to
    disclose.
    """
    if not isinstance(result, dict):
        return result
    nc = result.get("not_comparable")
    lost = nc.get("lost") if isinstance(nc, dict) else None
    never = nc.get("never_measured") if isinstance(nc, dict) else None
    ok = isinstance(lost, list) and isinstance(never, list)
    note = str(result.get("verdict_note") or "")
    if not ok:
        result["not_comparable"] = {"lost": [], "never_measured": [], "disclosure_available": False}
        result["verdict_note"] = (
            f"{_NOT_COMPARABLE_PHRASE}: this trend carries no metric-comparability record, so which "
            "metrics were measured at both ends of the campaign is UNKNOWN — the trajectory below "
            "is not a statement that every metric was comparable. " + note
        ).strip()
        return result
    result["not_comparable"] = {"lost": list(lost), "never_measured": list(never),
                                "disclosure_available": True}
    if (lost or never) and _NOT_COMPARABLE_PHRASE not in note:
        names = ", ".join(str(m) for m in list(lost) + list(never))
        result["verdict_note"] = (
            f"{_NOT_COMPARABLE_PHRASE}: {len(lost) + len(never)} metric(s) ({names}) are absent from "
            "the trajectory because their evidence is missing at one or both ends of this campaign — "
            "NOT because there is nothing to report. " + note
        ).strip()
    return result


def campaign_trend(
        snapshots: List[Dict[str, Any]], *,
        source_bindings: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Trajectory across a series (oldest-first) — thin pass-through to the engine, plus the
    fail-closed coverage-disclosure carry in `_carry_not_comparable` and additive canonical
    adjacent-pair receipts when exact persisted custody is available."""
    snaps = list(snapshots or [])
    schema = _schema_compat(snaps)
    result = compute_campaign_trend(
        snaps, source_bindings=source_bindings, schema_status=schema)
    result = _with_schema_compat(_carry_not_comparable(result), schema)
    receipts, receipt_status = _trend_comparison_receipts(snaps, source_bindings)
    result["adjacent_comparisons"] = receipts
    result["adjacent_comparison_status"] = receipt_status
    if receipt_status["status"] == "not_comparable":
        prior_note = str(result.get("verdict_note") or "")
        result["verdict"] = "INDETERMINATE"
        result["verdict_note"] = f"{receipt_status['note']} {prior_note}".strip()
    return result


def snapshot_delta(
        old: Dict[str, Any], new: Dict[str, Any], *,
        source_binding: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    schema = _schema_compat([old, new])
    result = compute_snapshot_delta(
        old, new, source_binding=source_binding, schema_status=schema)
    return _with_schema_compat(result, schema)


def compare_bound_pair(
        old: Dict[str, Any], new: Dict[str, Any], *,
        before_binding: Dict[str, Any], after_binding: Dict[str, Any],
        change_intent: Optional[Dict[str, Any]] = None,
        l2_failure_trial: Any = None,
        operator_evidence_schema: Optional[str] = None) -> Dict[str, Any]:
    """Delegate to the presentation-independent canonical comparison composer.

    ``operator_evidence_schema`` stays ``None`` for every new comparison (the current contract). Only the stored
    receipt re-verification passes the contract the stored receipt declares (W50)."""
    return _comparison.compare_bound_pair(
        old,
        new,
        before_binding=before_binding,
        after_binding=after_binding,
        change_intent=change_intent,
        l2_failure_trial=l2_failure_trial,
        operator_evidence_schema=operator_evidence_schema,
    )


def stored_operator_evidence_contract(comparison: Any) -> Optional[str]:
    """The operator-evidence contract a stored comparison declares, when the engine can recompute it.

    ``None`` means missing, malformed or unknown: the stored receipt is unverified, never defaulted to the current
    contract (W50)."""
    return _protocol_assurance.stored_operator_evidence_schema(comparison)


def compact_execution_comparison(
        comparison: Dict[str, Any], *, before_snapshot_id: int,
        after_snapshot_id: int, after_collected_at: Optional[str] = None,
        implementation_binding: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Freeze the complete canonical comparison for one execution append.

    The stored receipt is uncapped and carries the exact same overall gate as ``/api/compare``.
    It intentionally omits no decision input; presentation layers may cap their rendered rows but
    must never feed those caps back into the decision.
    """
    body = {
        "schema": "execution_comparison_receipt/1",
        "before_snapshot_id": before_snapshot_id,
        "after_snapshot_id": after_snapshot_id,
        "comparison": comparison,
    }
    if after_collected_at is not None:
        body["after_collected_at"] = after_collected_at
    if implementation_binding is not None:
        body["implementation_binding"] = implementation_binding
    body["receipt_sha256"] = _protocol_assurance.canonical_sha256(body)
    return body
