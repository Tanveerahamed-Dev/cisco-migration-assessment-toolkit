"""Shared helper for hand-built failure-impact fixtures (W33).

Since W33 every engine deliverable reads a stored failure_impact row through the engine owner of row
assessability (cisco_toolkit/impact_assessability.py). The owner withholds a row unless the snapshot carries the
evidence the producer's row depends on: the producer's ``off_scan_gw_vlans`` marker and its per-row ``blind_links``
count (W32) on the row, an interface of the row's device carrying ``run_config_observed: true`` (the only source of
its gateway addresses), and a readable cable map with no uncollected neighbour that can carry endpoints. A hand-built
row without that evidence is, correctly, not a measurement (a row without ``blind_links`` predates that count, so the
owner reads it as a lower bound).

Tests whose subject is something else (a display cap, a disclosure sentence, a sort order) use :func:`assessable`
so their rows read as the producer's measurements, exactly as a real engine run's rows do. Tests whose subject IS the
withholding build the gap on purpose instead (tests/test_impact_assessability.py and the per-deliverable tests).
"""
from __future__ import annotations

import copy
from typing import Any, Dict


def assessable(snap: Dict[str, Any]) -> Dict[str, Any]:
    """A deep copy of `snap` carrying the assessability evidence for every failure_impact row that names a host.

    * a row without ``off_scan_gw_vlans`` gains ``0`` (the producer writes the key on every row since 2026-06-26);
    * a row without ``blind_links`` gains ``0`` (the producer writes its count of evidence-less inter-switch links on
      every row since W32), so the row is a current producer row with no such link;
    * each row's host gains an interface record with ``run_config_observed: true``: an existing port of that host is
      marked, so no port is invented where the fixture already has some; a host with no interface record gets one
      (``Gi0/0``);
    * an absent cable map becomes an empty one (``nodes: []``, ``cables: []``), which names no uncollected neighbour.
    """
    out = copy.deepcopy(snap)
    rows = out.get("failure_impact")
    if not isinstance(rows, list):
        return out
    interfaces = out.setdefault("interfaces", {})
    for row in rows:
        if not isinstance(row, dict):
            continue
        row.setdefault("off_scan_gw_vlans", 0)
        row.setdefault("blind_links", 0)
        host = row.get("host")
        if not isinstance(host, str) or not isinstance(interfaces, dict):
            continue
        ports = interfaces.get(host)
        if isinstance(ports, dict) and ports:
            first = next(iter(ports))
            if isinstance(ports[first], dict):
                ports[first]["run_config_observed"] = True
                continue
        interfaces[host] = {"Gi0/0": {"run_config_observed": True}}
    if not isinstance(out.get("cable_map"), dict):
        out["cable_map"] = {"nodes": [], "cables": []}
    else:
        out["cable_map"].setdefault("nodes", [])
        out["cable_map"].setdefault("cables", [])
    return out


def evidence_for(*hosts: str) -> Dict[str, Any]:
    """The evidence alone (for a writer that takes the rows and the evidence separately): an interface record with
    ``run_config_observed: true`` per host and an empty cable map."""
    return {"interfaces": {h: {"Gi0/0": {"run_config_observed": True}} for h in hosts},
            "cable_map": {"nodes": [], "cables": []}}
