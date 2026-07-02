"""Tests for compute_cable_map — the EDA-style physical cable-map SSOT.

A Nokia-EDA-style cable map is a node/port/cable graph laid out in role tiers, with
op-status color derived from the underlying interface states. This engine is the single
source of truth both front-ends (explorer + webapp) render, so the model — tiering, LAG
bundling, and coverage-honest op-status ([NOT OBSERVED] neutral for uncollected devices) —
is pinned here rather than in JS/TS. (Nokia EDA physical-topology anatomy, deep-research 2026-07-01.)
"""
import json

from cisco_toolkit.analyze import compute_cable_map
from cisco_toolkit.model import InterfaceData


def _if(**kw):
    return InterfaceData(**kw)


def _nodes(cm):
    return {n["host"]: n for n in cm["nodes"]}


def test_basic_tiering_and_cable_up():
    """core seeds the top tier; a one-hop access switch lands one tier down; a link whose
    both observed ends are 'connected' is op_status 'up', with a port stub on each node."""
    all_ifaces = {
        "CORE-1": {"Gi1/0/1": _if(port="Gi1/0/1", status="connected",
                                  cdp_neighbor="ACC-1", neighbor_port="Gi1/0/24", endpoint_type="Switch")},
        "ACC-1": {"Gi1/0/24": _if(port="Gi1/0/24", status="connected",
                                  cdp_neighbor="CORE-1", neighbor_port="Gi1/0/1", endpoint_type="Switch")},
    }
    health = [{"switch": "CORE-1", "role": "core"}, {"switch": "ACC-1", "role": "access"}]
    cm = compute_cable_map(all_ifaces, health)

    assert set(cm) >= {"nodes", "cables", "tiers", "summary"}
    nodes = _nodes(cm)
    assert nodes["CORE-1"]["tier"] == 0            # core seeds the top tier
    assert nodes["ACC-1"]["tier"] == 1             # one hop down
    assert nodes["CORE-1"]["op_status"] == "up"    # collected device
    assert nodes["CORE-1"]["collected"] is True
    assert cm["tiers"][0] == ["CORE-1"]

    assert len(cm["cables"]) == 1
    c = cm["cables"][0]
    assert {c["a"], c["b"]} == {"CORE-1", "ACC-1"}
    assert c["op_status"] == "up"                  # both ends connected
    assert any(p["name"] == "Gi1/0/1" for p in nodes["CORE-1"]["ports"])
    assert any(p["name"] == "Gi1/0/24" for p in nodes["ACC-1"]["ports"])


def test_cable_down_when_either_observed_end_notconnect():
    """A 'notconnect'/'err-disabled' port makes the cable op_status 'down' — the down end wins,
    even if the far end reports connected. (EDA derives cable status from underlying interfaces.)"""
    all_ifaces = {
        "CORE-1": {"Gi1/0/1": _if(port="Gi1/0/1", status="notconnect",
                                  cdp_neighbor="ACC-1", neighbor_port="Gi1/0/24", endpoint_type="Switch")},
        "ACC-1": {"Gi1/0/24": _if(port="Gi1/0/24", status="connected",
                                  cdp_neighbor="CORE-1", neighbor_port="Gi1/0/1", endpoint_type="Switch")},
    }
    cm = compute_cable_map(all_ifaces, [{"switch": "CORE-1", "role": "core"},
                                        {"switch": "ACC-1", "role": "access"}])
    assert cm["cables"][0]["op_status"] == "down"

    # err-disabled is also 'down'
    all_ifaces["CORE-1"]["Gi1/0/1"].status = "err-disabled"
    cm2 = compute_cable_map(all_ifaces, None)
    assert cm2["cables"][0]["op_status"] == "down"


def test_uncollected_neighbor_is_not_observed_neutral():
    """An off-scan CDP neighbour (the 50 uncollected DS/CS core analogue) becomes a node with
    op_status 'unknown' ([NOT OBSERVED]) and an 'uncollected' badge — never a fake green."""
    all_ifaces = {
        "ACC-1": {"Gi1/0/24": _if(port="Gi1/0/24", status="connected",
                                  cdp_neighbor="DS-CORE", neighbor_port="Te1/1/1", endpoint_type="Switch")},
    }
    cm = compute_cable_map(all_ifaces, [{"switch": "ACC-1", "role": "access"}])
    nodes = _nodes(cm)
    assert "DS-CORE" in nodes                       # the off-scan peer is still a node in the cabling
    assert nodes["DS-CORE"]["collected"] is False
    assert nodes["DS-CORE"]["op_status"] == "unknown"
    assert "uncollected" in nodes["DS-CORE"]["badges"]


def test_cable_unknown_when_no_status_observed_either_end():
    """If neither end exposes an interface status (empty local status + off-scan far end),
    the cable is op_status 'unknown', not silently 'up'."""
    all_ifaces = {
        "ACC-1": {"Gi1/0/24": _if(port="Gi1/0/24", status="",
                                  cdp_neighbor="DS-CORE", neighbor_port="Te1/1/1", endpoint_type="Switch")},
    }
    cm = compute_cable_map(all_ifaces, None)
    assert cm["cables"][0]["op_status"] == "unknown"


def test_lag_members_bundled_into_one_cable():
    """Two physical links between the same pair that are port-channel members collapse into ONE
    bundled cable (is_pc) carrying both member port pairs — not two separate cables."""
    def leg(local, remote, peer):
        return _if(port=local, status="connected", port_channel="Po1",
                   cdp_neighbor=peer, neighbor_port=remote, endpoint_type="Switch")
    all_ifaces = {
        "CORE-1": {"Gi1/0/1": leg("Gi1/0/1", "Gi1/0/1", "DIST-1"),
                   "Gi1/0/2": leg("Gi1/0/2", "Gi1/0/2", "DIST-1")},
        "DIST-1": {"Gi1/0/1": leg("Gi1/0/1", "Gi1/0/1", "CORE-1"),
                   "Gi1/0/2": leg("Gi1/0/2", "Gi1/0/2", "CORE-1")},
    }
    cm = compute_cable_map(all_ifaces, [{"switch": "CORE-1", "role": "core"},
                                        {"switch": "DIST-1", "role": "distribution"}])
    pc = [c for c in cm["cables"] if c["is_pc"]]
    assert len(pc) == 1                             # bundled, not two
    assert len(pc[0]["members"]) == 2
    assert pc[0]["op_status"] == "up"


def test_degree_fallback_tiering_without_roles():
    """With no role evidence, the highest-degree node seeds the top tier (clab-io-draw pattern),
    so a hub-and-spoke fabric still tiers sensibly."""
    def leg(local, peer, remote):
        return _if(port=local, status="connected", cdp_neighbor=peer,
                   neighbor_port=remote, endpoint_type="Switch")
    all_ifaces = {
        "HUB": {f"Gi1/0/{i}": leg(f"Gi1/0/{i}", f"L{i}", "Gi1/0/1") for i in (1, 2, 3)},
        "L1": {"Gi1/0/1": leg("Gi1/0/1", "HUB", "Gi1/0/1")},
        "L2": {"Gi1/0/1": leg("Gi1/0/1", "HUB", "Gi1/0/2")},
        "L3": {"Gi1/0/1": leg("Gi1/0/1", "HUB", "Gi1/0/3")},
    }
    cm = compute_cable_map(all_ifaces, None)
    nodes = _nodes(cm)
    assert nodes["HUB"]["tier"] == 0               # highest degree seeds the top
    assert nodes["L1"]["tier"] == 1


def test_deterministic_output():
    """Same input -> byte-identical output (SSOT stability; the golden freezes this)."""
    all_ifaces = {
        "CORE-1": {"Gi1/0/1": _if(port="Gi1/0/1", status="connected",
                                  cdp_neighbor="ACC-1", neighbor_port="Gi1/0/24", endpoint_type="Switch")},
        "ACC-1": {"Gi1/0/24": _if(port="Gi1/0/24", status="connected",
                                  cdp_neighbor="CORE-1", neighbor_port="Gi1/0/1", endpoint_type="Switch")},
    }
    h = [{"switch": "CORE-1", "role": "core"}, {"switch": "ACC-1", "role": "access"}]
    a = json.dumps(compute_cable_map(all_ifaces, h), sort_keys=True)
    b = json.dumps(compute_cable_map(all_ifaces, h), sort_keys=True)
    assert a == b


def test_empty_input_is_safe():
    """Tolerant of an empty fleet (no crash, empty model)."""
    cm = compute_cable_map({}, None)
    assert cm["nodes"] == [] and cm["cables"] == [] and cm["tiers"] == []
    assert cm["summary"]["n_nodes"] == 0


def _demo_cable_map():
    return {
        "nodes": [], "tiers": [],
        "cables": [
            {"a": "CORE-1", "a_port": "Gi1/0/1", "b": "ACC-1", "b_port": "Gi1/0/24", "is_pc": False,
             "members": [{"a_port": "Gi1/0/1", "b_port": "Gi1/0/24"}], "op_status": "up", "confirmation": "Both ends"},
            {"a": "CORE-1", "a_port": "Gi1/0/2", "b": "ACC-2", "b_port": "Gi1/0/24", "is_pc": False,
             "members": [{"a_port": "Gi1/0/2", "b_port": "Gi1/0/24"}], "op_status": "down", "confirmation": "One end (CORE-1)"},
            {"a": "ACC-3", "a_port": "Te1/1/1", "b": "DS-CORE", "b_port": "Te1/1/1", "is_pc": False,
             "members": [{"a_port": "Te1/1/1", "b_port": "Te1/1/1"}], "op_status": "unknown", "confirmation": "One end (ACC-3)"},
            {"a": "CORE-1", "a_port": "Po1", "b": "DIST-1", "b_port": "Po1", "is_pc": True,
             "members": [{"a_port": "Gi1/0/3", "b_port": "Gi1/0/3"}, {"a_port": "Gi1/0/4", "b_port": "Gi1/0/4"}],
             "op_status": "up", "confirmation": "Both ends"},
        ],
        "summary": {"n_nodes": 0, "n_cables": 4, "n_tiers": 0, "op": {"up": 2, "down": 1, "unknown": 1}},
    }


def test_cabling_schedule_sheet():
    """The 'Cabling Schedule' workbook sheet is one row per cable from the cable_map SSOT: A/B host+port,
    LAG bundling, and op-status — coverage-honest (an unobserved end is '[NOT OBSERVED]', never 'Up')."""
    from openpyxl import Workbook
    from cisco_toolkit.excel import write_cabling_schedule_sheet, CABLING_SCHEDULE_SHEET_NAME
    wb = Workbook()
    write_cabling_schedule_sheet(wb, _demo_cable_map())
    assert CABLING_SCHEDULE_SHEET_NAME in wb.sheetnames
    ws = wb[CABLING_SCHEDULE_SHEET_NAME]
    header = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    assert header[:4] == ["Switch A", "Port A", "Switch B", "Port B"]
    assert "Op-Status" in header
    body = [[c.value for c in row] for row in ws.iter_rows(min_row=2)]
    assert len(body) == 4                                        # one row per cable
    op_col = header.index("Op-Status")
    ops = [r[op_col] for r in body]
    assert ops.count("Up") == 2 and ops.count("Down") == 1       # derived, per-link
    assert ops.count("[NOT OBSERVED]") == 1                      # the uncollected end — never a fake 'Up'
    # the port-channel is typed as a bundle carrying 2 members
    type_col = header.index("Type")
    pc = [r for r in body if r[type_col] == "Port-channel"]
    assert len(pc) == 1 and pc[0][header.index("LAG Members")] == 2


def test_cabling_schedule_sheet_empty_is_safe():
    from openpyxl import Workbook
    from cisco_toolkit.excel import write_cabling_schedule_sheet, CABLING_SCHEDULE_SHEET_NAME
    wb = Workbook()
    write_cabling_schedule_sheet(wb, {"cables": []})
    assert CABLING_SCHEDULE_SHEET_NAME in wb.sheetnames        # sheet still emitted (with a placeholder row)
