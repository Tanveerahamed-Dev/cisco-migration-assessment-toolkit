"""Compatibility route for the engine-owned projected topology.

The engine's project_tools_topology adapts its project_topology document for the
existing geometry renderer, preserving its interaction and visual contracts.
No CDP graph, degree, bridge verdict or failure model is rebuilt in this backend.
Selected-device failure facts use the typed projection transport.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import engine
from cisco_toolkit import ui_projection


def build_graph(snap: Dict[str, Any], keystones: Optional[List[str]] = None) -> Dict[str, Any]:
    """Return the topology owner unchanged; obsolete cache hints have no authority."""
    return ui_projection.project_tools_topology(snap)


def cable_map_from_snapshot(snap: Dict[str, Any]) -> Dict[str, Any]:
    """EDA-style physical cable map for the webapp cable-map view.

    Thin pass-through to the engine's cable_map_of_snapshot — the ONE rehydration SSOT the
    --compare delta also uses: prefer the engine-computed snap['cable_map'], else recompute from
    the stored interface evidence so pre-feature uploads still render. Coverage-honest either
    way — an uncollected device stays [NOT OBSERVED], never a fake green.
    """
    return engine.cable_map_of_snapshot(snap)
