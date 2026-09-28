"""Sample-fleet forwarding substrate: the demo collection carries enough routed evidence for a
decided multi-hop trace (Atlas Scope A2/B8), fixed at the SOURCE (webapp/sample_data/build_sample.py).

What this pins, all through the engine's REAL parsers and producers (no hand-built parse results):

* dist1 and dist2 have collected routing tables whose next hops point at addresses another collected
  host owns (dist1 -> core1 over the routed 10.0.140.0/30 transit; dist2 -> dist1 over Vlan40), and
  core1's table carries the OSPF routes back to the pod;
* dist1 and dist2 carry a `show running-config` with an ACL definition, so the `acls` axis keeps them;
* the OSPF adjacencies core1 <-> dist1 <-> dist2 parse FULL on the interfaces the tables route over;
* EIGRP on core1/dist1/dist2 is COLLECTED and EMPTY, and BGP on dist1/dist2 is the IOS no-process
  banner ('% BGP not active') -- the realistic output of switches that do not run them, never a
  fabricated adjacency;
* core1's inter-core OSPF session with core2 (router ID 10.0.99.2) runs over a transit SVI (VLAN 900,
  10.0.199.0/30) carried by the Po1 trunk, which both cores' tables hold -- an OSPF adjacency cannot
  form on an L2 trunk port-channel (owner decision O2), and core2 holds the routes core1 advertises;
* core1 Gi1/0/40 (the port dist1 already cables to) is a routed stanza, while every CDP capture,
  including the deliberately disputed core1 Gi1/0/40 claim by access16 and dist1, is byte-identical;
* the substrate edits only deep copies (tests/synthetic_fixtures.py stays byte-for-byte what it was);
* the snapshot writer emits LF on every platform -- pinned through main(), not only the helper --
  and `--out` redirects it away from the tracked path;
* every IPv4 literal the substrate adds is RFC 1918 / RFC 5737 (or a mask), and every hostname it
  names is an existing fleet host (client-privacy marker hygiene).
"""
from __future__ import annotations

import copy
import ipaddress
import os
import re
import sys

import pytest

import synthetic_fixtures as fx
from webapp.sample_data import build_sample as bs
from cisco_toolkit.analyze import compute_protocol_assessability, compute_protocol_health
from cisco_toolkit.capture_integrity import inspect_capture
from cisco_toolkit.build import build_acls, build_routing_neighbors
from cisco_toolkit.parse import parse_ip_routes, parse_run_config_interfaces

ROUTED = ("core1", "dist1", "dist2")
# Every host the substrate edits: the three routed hosts plus core2, the far end of core1's transit SVI.
EDITED = ("core1", "core2", "dist1", "dist2")


@pytest.fixture(scope="module")
def cols():
    return bs.build_collections()


@pytest.fixture(scope="module")
def base_cols():
    """The fleet exactly as build_collections() made it BEFORE this substrate existed."""
    saved = bs._add_forwarding_substrate
    bs._add_forwarding_substrate = lambda c: c
    try:
        return bs.build_collections()
    finally:
        bs._add_forwarding_substrate = saved


@pytest.fixture(scope="module")
def c2f(cols, tmp_path_factory):
    """hostname -> {command: captured file}, written by the same writer the real build uses."""
    root = str(tmp_path_factory.mktemp("substrate_collection"))
    bs._write_collection(root, cols)
    return {h: {cmd: os.path.join(root, h, fx.cmd_filename(cmd)) for cmd in outs}
            for h, (_plat, outs) in cols.items()}


@pytest.fixture(scope="module")
def assessability(cols, c2f):
    ifaces = {h: {} for h in cols}
    health = compute_protocol_health(ifaces, c2f)
    receipt = compute_protocol_assessability(sorted(cols), ifaces, c2f, health)
    return {(r["switch"], r["protocol"]): r for r in receipt["rows"]}


def _routes(cols, host):
    table = parse_ip_routes(cols[host][1]["show ip route"])
    receipt = getattr(table, "parse_receipt", {})
    assert receipt.get("complete") is True, (host, receipt.get("incomplete_reasons"))
    return {prefix: info["entries"] for prefix, info in table.items()}


def _only(entries):
    assert len(entries) == 1, entries
    return entries[0]


# --------------------------------------------------------------------------- routing tables
# core1's user/voice/server subnets reach OSPF only through `redistribute connected` (its one
# OSPF-enabled interface is the Gi1/0/40 transit), so every other OSPF router holds them as EXTERNAL
# type-2 routes, and the default exists only because core1 originates it (2026-09-26 verifier, E2-V4).
_CORE1_REDISTRIBUTED = ("10.0.10.0/24", "10.0.20.0/24", "10.0.30.0/24")


def test_core1_ospf_config_originates_exactly_what_the_dist_tables_hold(cols):
    run = cols["core1"][1]["show running-config"]
    ospf = re.search(r"^router ospf 1\n((?: .*\n)*)", run, re.M).group(1)
    assert " redistribute connected\n" in ospf
    assert " default-information originate\n" in ospf  # the dists' O*E2 default has an originator
    assert not re.search(r"^ network ", ospf, re.M)      # no network statement puts a user VLAN in area 0
    ifaces = cols["core1"][1]["show running-config | section ^interface"]
    stanzas = re.findall(r"^interface (\S+)\n((?: .*\n)*)", ifaces, re.M)
    in_area = [name for name, body in stanzas if re.search(r"^ ip ospf \d+ area ", body, re.M)]
    # The dist1 transit, and the inter-core transit SVI (owner decision O2) -- never a user VLAN.
    assert in_area == ["GigabitEthernet1/0/40", "Vlan900"], in_area


def test_dist1_routes_to_the_core_over_the_routed_transit(cols):
    rib = _routes(cols, "dist1")
    for dst in _CORE1_REDISTRIBUTED:
        e = _only(rib[dst])
        assert (e["source"], e["next_hop"], e["out_intf"]) == ("ospf-ext2", "10.0.140.1", "Gi1/0/3"), (dst, e)
    e = _only(rib["0.0.0.0/0"])  # O*E2: the core's redistributed default
    assert (e["source"], e["next_hop"], e["out_intf"]) == ("ospf-ext2", "10.0.140.1", "Gi1/0/3"), e
    assert _only(rib["10.0.140.0/30"])["source"] == "connected"
    assert _only(rib["10.0.140.2/32"])["source"] == "local"
    for pod in ("10.0.40.0/24", "10.0.41.0/24"):
        assert _only(rib[pod])["source"] == "connected"
    # core1 puts the inter-core transit SVI in area 0, so the dists hold it intra-area.
    e = _only(rib["10.0.199.0/30"])
    assert (e["source"], e["next_hop"], e["out_intf"]) == ("ospf", "10.0.140.1", "Gi1/0/3"), e


def test_dist2_routes_to_the_core_via_dist1_on_vlan40(cols):
    rib = _routes(cols, "dist2")
    for dst in _CORE1_REDISTRIBUTED:
        e = _only(rib[dst])
        assert (e["source"], e["next_hop"], e["out_intf"]) == ("ospf-ext2", "10.0.40.2", "Vlan40"), (dst, e)
    # dist1 puts the transit in area 0 with a network statement, so dist2 holds it intra-area.
    e = _only(rib["10.0.140.0/30"])
    assert (e["source"], e["next_hop"], e["out_intf"]) == ("ospf", "10.0.40.2", "Vlan40"), e
    e = _only(rib["0.0.0.0/0"])
    assert (e["source"], e["next_hop"], e["out_intf"]) == ("ospf-ext2", "10.0.40.2", "Vlan40"), e
    e = _only(rib["10.0.199.0/30"])
    assert (e["source"], e["next_hop"], e["out_intf"]) == ("ospf", "10.0.40.2", "Vlan40"), e


def test_core1_routes_the_pod_back_to_dist1_and_owns_the_transit(cols):
    rib = _routes(cols, "core1")
    for pod in ("10.0.40.0/24", "10.0.41.0/24"):
        e = _only(rib[pod])
        assert (e["source"], e["next_hop"], e["out_intf"]) == ("ospf", "10.0.140.2", "Gi1/0/40"), (pod, e)
    assert _only(rib["10.0.140.1/32"])["source"] == "local"
    # The transit next hops are addresses the far end OWNS as a local /32 (how a trace resolves the next host).
    assert _only(_routes(cols, "dist1")["10.0.140.2/32"])["out_intf"] == "Gi1/0/3"


# --------------------------------------------------------------------------- the inter-core transit (O2)
# An OSPF adjacency cannot form on an L2 trunk port-channel: core1's FULL/DR session with core2
# (router ID 10.0.99.2) needs an L3 home. The owner's decision O2 gives it a transit SVI, VLAN 900
# (10.0.199.0/30), carried by the existing Po1 trunk -- the cores stay L2-adjacent for their HSRP groups.
_TRANSIT_VLAN = "900"
_CORE1_TRANSIT, _CORE2_TRANSIT = "10.0.199.1", "10.0.199.2"


def test_core1_inter_core_ospf_session_runs_over_the_transit_svi(cols, c2f):
    ospf = build_routing_neighbors(c2f["core1"])["ospf"]
    core2 = [n for n in ospf if n["neighbor"] == "10.0.99.2"]  # the router ID is kept
    assert [(n["address"], n["interface"], n["state"]) for n in core2] == [(_CORE2_TRANSIT, "Vlan900", "FULL/DR")]
    stanzas = dict(re.findall(r"^interface (\S+)\n((?: .*\n)*)",
                              cols["core1"][1]["show running-config | section ^interface"], re.M))
    svi = stanzas["Vlan900"]
    assert f" ip address {_CORE1_TRANSIT} 255.255.255.252\n" in svi and " ip ospf 1 area 0\n" in svi
    assert "standby" not in svi  # a two-router transit segment carries no FHRP group
    rib = _routes(cols, "core1")
    e = _only(rib["10.0.199.0/30"])
    assert (e["source"], e["out_intf"]) == ("connected", "Vlan900"), e
    assert _only(rib[f"{_CORE1_TRANSIT}/32"])["source"] == "local"


@pytest.mark.parametrize("host, trunk_cmd, switchport_cmd, vlan_cmd", [
    ("core1", "show interfaces trunk", "show interfaces switchport", "show vlan brief"),
    ("core2", "show interface trunk", "show interface switchport", "show vlan brief"),
])
def test_both_ends_of_po1_carry_the_transit_vlan(cols, host, trunk_cmd, switchport_cmd, vlan_cmd):
    outs = cols[host][1]
    assert re.search(r"^Po1\s+10,20,30,900$", outs[trunk_cmd], re.M), outs[trunk_cmd]
    po1 = re.search(r"^Name: (?:Po1|port-channel1)\n((?:.+\n)*)", outs[switchport_cmd], re.M).group(1)
    assert re.search(r"Trunking VLANs (?:Enabled|Allowed): 10,20,30,900$", po1, re.M), po1
    assert re.search(rf"^{_TRANSIT_VLAN}\s+CORE-TRANSIT\s+active\b", outs[vlan_cmd], re.M)
    brief = outs["show ip interface brief"]
    assert re.search(rf"^Vlan900\s+{_CORE1_TRANSIT if host == 'core1' else _CORE2_TRANSIT}\s", brief, re.M)


def test_core2_owns_the_far_end_of_the_transit_and_holds_what_core1_advertises(cols):
    stanzas = dict(re.findall(r"^interface (\S+)\n((?:  .*\n)*)",
                              cols["core2"][1]["show running-config interface"], re.M))
    svi = stanzas["Vlan900"]
    assert f"  ip address {_CORE2_TRANSIT}/30\n" in svi and "  ip router ospf 1 area 0.0.0.0\n" in svi
    rib = _routes(cols, "core2")
    e = _only(rib["10.0.199.0/30"])
    assert (e["source"], e["out_intf"]) == ("connected", "Vlan900"), e
    assert _only(rib[f"{_CORE2_TRANSIT}/32"])["source"] == "local"
    # What core1 originates into OSPF reaches core2 over the transit: its default (default-information
    # originate), its redistributed server VLAN, the pod and the dist1 transit. core2's own connected
    # Vlan10/20 win over core1's redistributed copies, as a real RIB's administrative distance decides.
    learned = {p: _only(es) for p, es in rib.items() if _only(es)["source"].startswith("ospf")}
    assert sorted(learned) == ["0.0.0.0/0", "10.0.140.0/30", "10.0.30.0/24", "10.0.40.0/24", "10.0.41.0/24"]
    assert {(e["next_hop"], e["out_intf"]) for e in learned.values()} == {(_CORE1_TRANSIT, "Vlan900")}
    assert learned["0.0.0.0/0"]["source"] == learned["10.0.30.0/24"]["source"] == "ospf-ext2"
    for own in ("10.0.10.0/24", "10.0.20.0/24"):
        assert _only(rib[own])["source"] == "connected"


def test_the_core_fhrp_groups_and_every_other_core_capture_line_survive(cols, base_cols):
    for host, cmds in (("core1", ("show standby brief", "show standby all")), ("core2", ("show hsrp brief",))):
        for cmd in cmds:
            assert cols[host][1][cmd] == base_cols[host][1][cmd], (host, cmd)
    # Every line core1/core2 held before is still there, except the one neighbour row that moved to the
    # transit SVI, the Po1 trunk allow-lists that gained VLAN 900 (core1's Gi1/0/24 keeps its own
    # 'Trunking VLANs Enabled: 10,20,30' line), and core1's routing-table subnet-count header.
    moved = {
        ("core1", "10.0.99.2         1   FULL/DR         00:00:35    10.0.99.2       Port-channel1"),
        ("core1", "Po1         10,20,30"),
        ("core1", "      10.0.0.0/8 is variably subnetted, 8 subnets, 3 masks"),
        ("core2", "Po1           10,20,30"), ("core2", "  Trunking VLANs Allowed: 10,20,30"),
    }
    lost = set()
    for host in ("core1", "core2"):
        for cmd, before in base_cols[host][1].items():
            now = set(cols[host][1][cmd].splitlines())
            lost |= {(host, line) for line in before.splitlines() if line not in now}
    assert lost == moved, sorted(lost ^ moved)


def _up(state: str) -> bool:
    s = state.strip()
    return bool(re.fullmatch(r"\d+", s)) or bool(re.match(r"(?i)(full|2way|established|up)\b", s))


def test_every_session_on_a_routed_host_runs_over_a_link_its_table_holds(cols, c2f):
    """The per-adjacency form of 'one control plane' (the rule Atlas Scope's rib-completeness.ts
    applies): an up session with a recorded interface needs a connected route there covering the
    neighbour's address; a BGP peer (no interface) needs a route OTHER THAN THE DEFAULT covering it (the
    default covers every address, so it evidences no path to this one). No exception remains: the
    fixture's B1 seed -- core1's FULL/DR neighbour 10.0.99.2 on the L2 trunk Po1 -- now runs over the
    transit SVI both tables hold (owner decision O2)."""
    unlinked, sessions = [], 0
    for host in ROUTED:
        rib = _routes(cols, host)
        for proto, rows in build_routing_neighbors(c2f[host]).items():
            for n in rows:
                if not _up(n.get("state") or ""):
                    continue
                sessions += 1
                addr = ipaddress.ip_address(n.get("address") or n["neighbor"])
                intf = n.get("interface")
                held = any(
                    addr in ipaddress.ip_network(prefix)
                    and (e["source"] == "connected" and e["out_intf"] == intf if intf
                         else ipaddress.ip_network(prefix).prefixlen > 0)
                    for prefix, es in rib.items() for e in es)
                if not held:
                    unlinked.append((host, proto, str(addr), intf))
    assert unlinked == [], unlinked
    assert sessions >= 6  # core1: dist1, core2, BGP peer; dist1: core1, dist2; dist2: dist1


def test_core1_bgp_peer_is_reached_by_a_route_the_scoped_snapshot_keeps(cols, c2f):
    """core1's one eBGP peer is the upstream it already defaults to (10.0.10.254 on Vlan10): a
    directly connected single-hop session. The route that reaches it is CONNECTED, and the engine's
    route scoping keeps every connected route -- so the claim holds on the snapshot Atlas Scope reads,
    not only on the collected text (2026-09-27 verifier, E2R2-V2: the old multihop peer was reached by
    a static /32 that scope_routes dropped, leaving only the default under it)."""
    from cisco_toolkit.build import build_routes, scope_routes
    run = cols["core1"][1]["show running-config"]
    assert re.search(r"^router bgp 65001\n(?: .*\n)* neighbor 10\.0\.10\.254 remote-as 64500$", run, re.M)
    assert "ebgp-multihop" not in run
    peer = ipaddress.ip_address("10.0.10.254")
    # An empty in-scope set is the strictest projection: only connected/local/default routes survive.
    scoped = scope_routes(build_routes(c2f["core1"]), set())
    covering = [r for r in scoped if peer in ipaddress.ip_network(r["prefix"])
                and ipaddress.ip_network(r["prefix"]).prefixlen > 0]
    assert ("10.0.10.0/24", "connected", "Vlan10") in [(r["prefix"], r["source"], r["out_intf"]) for r in covering]


def test_substrate_captures_pass_the_engine_capture_integrity_guard(cols, base_cols):
    """Every capture the substrate authors or edits inspects 'ok' under the engine's own guard
    (cisco_toolkit/capture_integrity.inspect_capture), except (a) the three EIGRP neighbour tables
    captured EMPTY (a switch with no EIGRP AS configured prints nothing; the guard's 'empty' is the same
    whitespace-only observation assessability calls captured_empty, not a separate truncation/error
    tripwire) and (b) a capture whose pre-substrate form already carried the same non-ok status (core1's
    running-config keeps the fixture convention of no terminating 'end'). The dists' BGP summaries are
    the IOS no-process banner, which is text, not an empty capture."""
    empties, bad = [], []
    for host in EDITED:
        for cmd, text in cols[host][1].items():
            if base_cols[host][1].get(cmd) == text:
                continue
            status = inspect_capture(cmd, text)["status"]
            before = inspect_capture(cmd, base_cols[host][1][cmd])["status"] if cmd in base_cols[host][1] else None
            if status == "empty":
                empties.append((host, cmd))
            elif status != "ok" and status != before:
                bad.append((host, cmd, status))
    assert bad == []
    assert sorted(empties) == sorted([("core1", "show ip eigrp neighbors"),
                                      ("dist1", "show ip eigrp neighbors"), ("dist2", "show ip eigrp neighbors")])


def test_the_bgp_configured_peer_baseline_validates_over_the_substrate_collection(cols, c2f):
    """The dist pair's complete, BGP-free running-configs beside their '% BGP not active' summaries are a
    realistic, peerless-switch input; the engine's own BGP configured-peer baseline must validate over it."""
    from cisco_toolkit.bgp_intent import compute_bgp_configured_peer_baseline, validate_bgp_configured_peer_baseline
    from cisco_toolkit.capture_integrity import compute_capture_integrity
    integrity = compute_capture_integrity({h: dict(outs) for h, (_plat, outs) in cols.items()})
    devices = [{"hostname": h, "platform": plat} for h, (plat, _outs) in cols.items()]
    baseline = compute_bgp_configured_peer_baseline(c2f, integrity, devices)
    view = validate_bgp_configured_peer_baseline(baseline)
    assert (view["valid"], view["reason"]) == (True, "ok")


def test_every_learned_route_has_its_protocol_adjacency(cols, c2f):
    """No learned route without the adjacency that would teach it: the tables and the neighbor
    captures describe ONE control plane (a route of protocol P implies an up P neighbor)."""
    for host in ROUTED:
        neigh = build_routing_neighbors(c2f[host])
        # The engine's route-source vocabulary sub-types a family as '<family>-<subtype>' (ospf-ext2, ...).
        learned = {e["source"].split("-")[0] for es in _routes(cols, host).values() for e in es}
        learned -= {"connected", "local", "static"}
        assert learned <= set(neigh), (host, learned)
        for proto in learned:
            assert neigh.get(proto), f"{host} holds {proto} routes but no {proto} adjacency"
    # core2 collects no neighbour table (its OSPF stays not_collected, so Atlas Scope keeps its table
    # unknown); every route it learned names, as next hop, core1's transit address -- and core1 records
    # that very session FULL on the transit SVI.
    nexthops = {e["next_hop"] for es in _routes(cols, "core2").values() for e in es
                if e["source"] not in ("connected", "local")}
    assert nexthops == {_CORE1_TRANSIT}
    assert "show ip ospf neighbor" not in cols["core2"][1]
    assert any(n["address"] == _CORE2_TRANSIT and n["state"].startswith("FULL")
               for n in build_routing_neighbors(c2f["core1"])["ospf"])


# --------------------------------------------------------------------------- ACL definitions
@pytest.mark.parametrize("host", ["dist1", "dist2"])
def test_dist_switches_carry_acl_definitions(c2f, host):
    acls = build_acls(c2f[host])
    assert "VTY_ACCESS" in acls, sorted(acls)
    assert len(acls["VTY_ACCESS"]) == 2


@pytest.mark.parametrize("host", ["dist1", "dist2"])
def test_dist_running_config_is_hardened_with_a_login_banner(cols, host):
    run = cols[host][1]["show running-config"]
    assert re.search(r"^banner login\b", run, re.M)
    assert re.search(r"^line vty 0 4\n access-class VTY_ACCESS in\n", run, re.M)
    assert re.search(r"^ transport input ssh$", run, re.M)
    # Not running EIGRP or BGP: the configuration and the neighbor captures agree.
    assert not re.search(r"^router (eigrp|bgp)\b", run, re.M)


# --------------------------------------------------------------------------- adjacencies
def _ospf(c2f, host):
    return {(n["neighbor"], n["address"], n["interface"]): n["state"]
            for n in build_routing_neighbors(c2f[host])["ospf"]}


def test_ospf_adjacencies_core1_dist1_dist2(c2f):
    core1, dist1, dist2 = _ospf(c2f, "core1"), _ospf(c2f, "dist1"), _ospf(c2f, "dist2")
    assert core1[("10.0.99.50", "10.0.140.2", "Gi1/0/40")].startswith("FULL")
    assert dist1[("10.0.99.1", "10.0.140.1", "Gi1/0/3")].startswith("FULL")
    assert dist1[("10.0.99.51", "10.0.40.3", "Vlan40")].startswith("FULL")
    assert dist2[("10.0.99.50", "10.0.40.2", "Vlan40")].startswith("FULL")


@pytest.mark.parametrize("host", ["dist1", "dist2"])
def test_dist_eigrp_is_captured_empty_not_fabricated(cols, c2f, assessability, host):
    command = "show ip eigrp neighbors"
    assert command in cols[host][1], f"{host} never collected {command!r}"
    assert cols[host][1][command].strip() == ""
    assert build_routing_neighbors(c2f[host])["eigrp"] == []
    row = assessability[(host, "EIGRP")]
    assert (row["state"], row["capture_state"], row["health_row_emitted"]) == ("captured_empty", "empty", False)


@pytest.mark.parametrize("host", ["dist1", "dist2"])
def test_dist_bgp_summary_is_the_real_no_process_banner(cols, c2f, assessability, host):
    """IOS/IOS-XE with no `router bgp` answers `show ip bgp summary` with the '% BGP not active' banner,
    not with empty output (2026-09-27 refuter X3: an empty capture no real device emits was shaped to
    the consumer). The engine reads the banner as its own positive 'no BGP process' state, never as a
    parsed peer and never as an empty table."""
    assert cols[host][1]["show ip bgp summary"] == "% BGP not active\n"
    assert build_routing_neighbors(c2f[host])["bgp"] == []
    row = assessability[(host, "BGP")]
    assert (row["state"], row["health_row_emitted"]) == ("not_running", False), row


@pytest.mark.parametrize("host", ROUTED)
def test_ospf_is_assessed_on_every_routed_host(assessability, host):
    assert assessability[(host, "OSPF")]["state"] == "assessed"


def test_core1_keeps_its_configured_bgp_as_one_established_peer_and_runs_no_eigrp(cols, c2f, assessability):
    assert re.search(r"^router bgp 65001\n(?: .*\n)* neighbor 10\.0\.10\.254 remote-as 64500$",
                     cols["core1"][1]["show running-config"], re.M)
    peers = build_routing_neighbors(c2f["core1"])["bgp"]
    assert [(p["neighbor"], p["state"]) for p in peers] == [("10.0.10.254", "0")]  # Established, 0 received
    assert assessability[("core1", "BGP")]["state"] == "assessed"
    assert not re.search(r"^router eigrp\b", cols["core1"][1]["show running-config"], re.M)
    assert assessability[("core1", "EIGRP")]["state"] == "captured_empty"


# --------------------------------------------------------------------------- the routed stanza + CDP
def test_core1_gi1_0_40_and_dist1_gi1_0_3_are_routed_stanzas(cols):
    core1 = parse_run_config_interfaces(cols["core1"][1]["show running-config | section ^interface"])
    dist1 = parse_run_config_interfaces(cols["dist1"][1]["show running-config | section ^interface"])
    g40 = next(v for k, v in core1.items() if k in ("Gi1/0/40", "GigabitEthernet1/0/40"))
    g3 = next(v for k, v in dist1.items() if k in ("Gi1/0/3", "GigabitEthernet1/0/3"))
    assert g40["ip_addr"] == "10.0.140.1 255.255.255.252"
    assert g3["ip_addr"] == "10.0.140.2 255.255.255.252"
    for text, port in ((cols["core1"][1]["show running-config | section ^interface"], "1/0/40"),
                       (cols["dist1"][1]["show running-config | section ^interface"], "1/0/3")):
        stanza = re.search(rf"^interface GigabitEthernet{port}\n((?: .*\n)*)", text, re.M).group(1)
        assert " no switchport\n" in stanza and "switchport mode" not in stanza
    assert "Gi1/0/3 " not in cols["dist1"][1]["show interfaces trunk"]
    assert "Name: Gi1/0/3\nSwitchport: Disabled\n" in cols["dist1"][1]["show interfaces switchport"]


def test_every_cdp_capture_is_unchanged_including_the_disputed_core1_gi1_0_40(cols, base_cols):
    for host in cols:
        assert cols[host][1]["show cdp neighbors detail"] == base_cols[host][1]["show cdp neighbors detail"], host
    claims = re.findall(r"Device ID: (\S+)\.lab\n(?:.*\n){0,3}?Interface: GigabitEthernet1/0/40,",
                        cols["core1"][1]["show cdp neighbors detail"])
    assert sorted(claims) == ["access16", "dist1"]


def test_only_the_substrate_hosts_change_and_only_deep_copies_are_edited(cols, base_cols):
    before = {name: copy.deepcopy(getattr(fx, name)) for name in dir(fx)
              if name.startswith("_") and not name.startswith("__") and isinstance(getattr(fx, name), dict)}
    assert {"_CORE1", "_CORE2", "_ACCESS1"} <= set(before)
    bs.build_collections()
    after = {name: getattr(fx, name) for name in before}
    assert before == after, "build_collections() mutated tests/synthetic_fixtures.py templates"
    assert sorted(h for h in cols if cols[h] != base_cols[h]) == sorted(EDITED)
    probe = copy.deepcopy(base_cols)
    frozen = copy.deepcopy(probe)
    bs._add_forwarding_substrate(probe)
    assert probe == frozen, "_add_forwarding_substrate must not mutate its argument"


# --------------------------------------------------------------------------- writer + --out
def test_snapshot_writer_emits_lf_only(tmp_path):
    out = tmp_path / "fleet.json"
    bs._write_snapshot(str(out), {"a": ["x", {"b": "multi\nline"}], "c": 1})
    raw = out.read_bytes()
    assert b"\r" not in raw
    assert raw.count(b"\n") >= 5  # indent=2 pretty form, not a one-line blob


def test_main_writes_the_snapshot_through_the_lf_writer(tmp_path, monkeypatch):
    """LF pinned through main() itself (2026-09-27 verifier, E2R2-V5: only the helper was exercised,
    so reverting main()'s write to a text-mode open() would have left the suite green). The pipeline is
    replaced by a stub that writes a compact snapshot where the real engine would; everything main()
    does after it is real."""
    out = tmp_path / "fleet.json"

    def fake_pipeline():
        argv = sys.argv
        xlsx = argv[argv.index("--output") + 1]
        with open(os.path.splitext(xlsx)[0] + ".snapshot.json", "w", encoding="utf-8", newline="\n") as f:
            f.write('{"devices": {"a": {}}, "notes": ["multi\\nline"], "punchlist": []}')

    monkeypatch.setattr(bs.cp, "main", fake_pipeline)
    monkeypatch.setattr(bs, "build_collections", lambda: {"x": ("ios", {"show version": "v\n"})})
    bs.main(["--out", str(out)])
    raw = out.read_bytes()
    assert b"\r" not in raw
    assert raw.count(b"\n") >= 5  # re-dumped pretty (indent=2), not a copy of the compact blob


def test_out_option_defaults_to_the_tracked_path(tmp_path):
    assert bs._parse_args([]) == (False, bs.OUT)
    assert bs._parse_args(["--check"]) == (True, bs.OUT)
    target = str(tmp_path / "scratch.json")
    assert bs._parse_args(["--out", target]) == (False, target)
    assert bs._parse_args(["--check", "--out", target]) == (True, target)
    with pytest.raises(SystemExit):
        bs._parse_args(["--out"])


# --------------------------------------------------------------------------- marker hygiene
_ALLOWED_NETS = [ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",       # RFC 1918
    "192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24",  # RFC 5737
)]


def _added_text(cols, base_cols):
    for host in EDITED:
        for cmd, text in cols[host][1].items():
            old = set(base_cols[host][1].get(cmd, "").splitlines())
            for line in text.splitlines():
                if line not in old:
                    yield host, line


def test_added_collection_text_uses_only_documentation_or_private_addresses_and_fleet_hostnames(cols, base_cols):
    fleet = set(cols)
    added = list(_added_text(cols, base_cols))
    assert added, "the substrate added no collection text"
    for host, line in added:
        for lit in re.findall(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])", line):
            if lit.startswith(("255.", "0.")):
                continue  # subnet masks / wildcard masks / the default route
            ip = ipaddress.ip_address(lit)
            assert any(ip in n for n in _ALLOWED_NETS), f"{host}: {lit!r} in {line!r}"
        for name in re.findall(r"(?:^hostname |Device ID: |description to-|^\S+\s+to-)([A-Za-z][\w-]*?)(?:\.lab)?(?:\s|$)", line):
            assert name in fleet, f"{host}: unknown hostname {name!r} in {line!r}"
