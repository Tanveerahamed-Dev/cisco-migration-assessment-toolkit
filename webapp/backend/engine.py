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
from cisco_toolkit.precert import schema_compat_status  # noqa: E402  (P3-E2: webapp diff schema gate)

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
