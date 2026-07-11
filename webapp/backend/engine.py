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
from typing import Any, Dict, List

# webapp/backend/engine.py -> webapp/backend -> webapp -> <repo root that contains cisco_toolkit>
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cisco_toolkit import analyze as _analyze  # noqa: E402  (after path bootstrap)
from cisco_toolkit import html as _html  # noqa: E402
from cisco_toolkit import __version__ as ENGINE_SCHEMA_VERSION  # noqa: E402,F401  (re-exported for the app)
from cisco_toolkit.precert import schema_compat_status  # noqa: E402  (P3-E2: webapp diff schema gate)

# Canonical hostname normalisation — reuse the engine's own so the web layer groups hosts identically.
canon_host = _analyze._canon_host
compute_cable_map = _analyze.compute_cable_map   # EDA-style physical cable-map SSOT (explorer + webapp share it)
cable_map_of_snapshot = _analyze.cable_map_of_snapshot   # stored-snapshot entry point (rehydrates pre-feature uploads)
trend_point = _html._trend_point
compute_snapshot_delta = _html.compute_snapshot_delta
compute_campaign_trend = _html.compute_campaign_trend
redact_snapshot = _html.redact_snapshot


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


def _with_schema_compat(result: Dict[str, Any], snaps: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Attach the pair/series schema-compatibility verdict to a diff/trend result (P3-E2, webapp surface).
    The CLI REFUSES a cross-schema diff; an interactive endpoint instead WARNS -- it surfaces the verdict
    (schema_compat.status: ok | unverifiable | mismatch) so the UI never presents a diff across an engine
    schema change as if it were a real network change. Additive + non-breaking."""
    if isinstance(result, dict):
        status, message = schema_compat_status(list(snaps or []))
        result["schema_compat"] = {"status": status, "message": message}
    return result


def campaign_trend(snapshots: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Trajectory across a series (oldest-first) — thin pass-through to the engine."""
    return _with_schema_compat(compute_campaign_trend(snapshots), list(snapshots or []))


def snapshot_delta(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    return _with_schema_compat(compute_snapshot_delta(old, new), [old, new])
