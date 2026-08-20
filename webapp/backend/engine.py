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
from typing import Any, Dict, List, Optional

# webapp/backend/engine.py -> webapp/backend -> webapp -> <repo root that contains cisco_toolkit>
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cisco_toolkit import analyze as _analyze  # noqa: E402  (after path bootstrap)
from cisco_toolkit import html as _html  # noqa: E402
from cisco_toolkit.textutils import _as_num as _as_num  # noqa: E402  (shared fail-soft numeric coercion)
from cisco_toolkit import __version__ as ENGINE_SCHEMA_VERSION  # noqa: E402,F401  (re-exported for the app)
from cisco_toolkit.precert import (  # noqa: E402  (P3-E2: webapp diff schema gate)
    compute_precert,
    schema_compat_status,
)
from cisco_toolkit import protocol_assurance as _protocol_assurance  # noqa: E402

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


def render_explorer_html(snapshot: Dict[str, Any], label: str) -> str:
    """Render the self-contained Blast-Radius Explorer for a stored snapshot, returned as a string.

    Re-uses `html.write_html_explorer` (which embeds a slimmed snapshot into the packaged template) by
    writing to a temp file and reading it back — the file the web layer serves is byte-identical to the
    CLI's `..._explorer.html`."""
    fd, path = tempfile.mkstemp(suffix=".html", prefix="assesshub_explorer_")
    os.close(fd)
    try:
        _html.write_html_explorer(path, snapshot, label)
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
        source_bindings: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    """Trajectory across a series (oldest-first) — thin pass-through to the engine, plus the
    fail-closed coverage-disclosure carry in `_carry_not_comparable`."""
    snaps = list(snapshots or [])
    schema = _schema_compat(snaps)
    result = compute_campaign_trend(
        snaps, source_bindings=source_bindings, schema_status=schema)
    return _with_schema_compat(_carry_not_comparable(result), schema)


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
        change_intent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Compose the canonical source-bound comparison without changing any v1 owner.

    The legacy delta fields remain at the top level for existing API consumers.  The certificate,
    reference-only family composition, admission envelope, and sole overall cutover gate are
    additive.  Both the delta and certificate consume hashes from the exact persisted bytes that
    produced ``old`` and ``new``.
    """
    schema = _schema_compat([old, new])
    source_binding = {
        "before": dict(before_binding),
        "after": dict(after_binding),
    }
    profiles = _protocol_assurance.protocol_support_profiles()
    owner_versions = {
        "snapshot_delta": "compute_snapshot_delta@v1",
        "precert": "precert/1",
        "cutover_gate": "cutover_gate/1",
        "protocol_family_change_set": "protocol_family_change_set/1",
        "engine_schema": ENGINE_SCHEMA_VERSION,
        "before_snapshot_owner": str(old.get("script_version") or ""),
        "after_snapshot_owner": str(new.get("script_version") or ""),
    }
    owner_versions.update({
        f"protocol:{profile['family']}": str(profile["owner_schema"])
        for profile in profiles
    })
    intent_binding = {
        "engagement_id": before_binding.get("engagement_id"),
        "campaign_id": before_binding.get("campaign_id"),
        "before_snapshot_id": before_binding.get("snapshot_id"),
        "after_snapshot_id": after_binding.get("snapshot_id"),
        "before_sha256": before_binding.get("sha256"),
        "after_sha256": after_binding.get("sha256"),
    }
    intent = _protocol_assurance.normalize_change_intent(
        change_intent, binding=intent_binding)
    admission = _protocol_assurance.comparison_admission(
        old,
        new,
        before_binding=before_binding,
        after_binding=after_binding,
        schema_status=schema,
        change_intent=intent,
        owner_versions=owner_versions,
        support_profiles=profiles,
    )
    delta = compute_snapshot_delta(
        old, new, source_binding=source_binding, schema_status=schema)
    delta = _with_schema_compat(delta, schema)
    certificate = compute_precert(
        old,
        new,
        source_hashes=source_binding,
        schema_status=schema,
    )
    native_deltas = _protocol_assurance.compute_native_protocol_deltas(
        old,
        new,
        before_binding=before_binding,
        after_binding=after_binding,
    )
    protocol_families = _protocol_assurance.protocol_family_change_set(
        delta.get("protocol_adjacencies"), intent, native_deltas=native_deltas)
    cutover_gate = _html.compute_cutover_gate(
        delta,
        certificate,
        comparison_admission=admission,
        protocol_family_changes=protocol_families,
    )
    operator_evidence = _protocol_assurance.cutover_operator_evidence(new)
    envelope = _protocol_assurance.receipt_envelope(
        admission=admission,
        change_intent=intent,
        protocol_families=protocol_families,
        delta=delta,
        precert=certificate,
        cutover_gate=cutover_gate,
        operator_evidence=operator_evidence,
    )
    return {
        **delta,
        "comparison_schema": "source_bound_cutover_comparison/1",
        "comparison_admission": admission,
        "change_intent": intent,
        "protocol_families": protocol_families,
        "precert": certificate,
        "cutover_gate": cutover_gate,
        "operator_evidence": operator_evidence,
        "comparison_receipt": envelope,
    }


def compact_execution_comparison(
        comparison: Dict[str, Any], *, before_snapshot_id: int,
        after_snapshot_id: int) -> Dict[str, Any]:
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
    body["receipt_sha256"] = _protocol_assurance.canonical_sha256(body)
    return body
