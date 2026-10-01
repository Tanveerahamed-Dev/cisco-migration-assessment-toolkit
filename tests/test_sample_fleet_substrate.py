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
* core1's inter-core OSPF session with core2 (router ID 10.0.99.2) runs over Vlan10, an SVI both cores
  already have and Po1 already carries -- an OSPF adjacency cannot form on an L2 trunk port-channel, and a
  new transit VLAN would have changed the move groups (owner decision, phase 2.75, replacing O2's VLAN
  900); no L2 capture of either core changes, and core2 holds the routes core1 advertises;
* core1's BGP configured-peer baseline is INDETERMINATE, honestly: an Established configured peer beside a
  running-config capture the engine reads as incomplete (the fixtures' no-'end' convention);
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
# Every host the substrate edits: the three routed hosts plus core2, the far end of core1's inter-core
# OSPF session on Vlan10.
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
def _core1_area0_and_connected(cols):
    """(interfaces core1 puts in OSPF area 0, {connected prefix: interface}) read from core1's own
    configuration and table -- what every other OSPF router's table is checked against below."""
    ifaces = cols["core1"][1]["show running-config | section ^interface"]
    stanzas = re.findall(r"^interface (\S+)\n((?: .*\n)*)", ifaces, re.M)
    in_area = [name for name, body in stanzas if re.search(r"^ ip ospf \d+ area ", body, re.M)]
    connected = {p: _only(es)["out_intf"] for p, es in _routes(cols, "core1").items()
                 if _only(es)["source"] == "connected"}
    return in_area, connected


def _short(intf: str) -> str:
    return intf.replace("GigabitEthernet", "Gi")


def _core1_originated(cols):
    """{prefix: engine source} for what core1 originates into OSPF, DERIVED from its configuration: a
    connected subnet on an area-0 interface is intra-area ('ospf'); every other connected subnet reaches
    OSPF only through `redistribute connected`, so other routers hold it as external type 2
    ('ospf-ext2'); the default exists only because core1 originates it (2026-09-26 verifier, E2-V4)."""
    in_area, connected = _core1_area0_and_connected(cols)
    area = {_short(i) for i in in_area}
    out = {p: ("ospf" if intf in area else "ospf-ext2") for p, intf in connected.items()}
    out["0.0.0.0/0"] = "ospf-ext2"
    return out


def test_core1_ospf_config_originates_exactly_what_the_dist_tables_hold(cols):
    run = cols["core1"][1]["show running-config"]
    ospf = re.search(r"^router ospf 1\n((?: .*\n)*)", run, re.M).group(1)
    assert " redistribute connected\n" in ospf
    assert " default-information originate\n" in ospf  # the dists' O*E2 default has an originator
    assert not re.search(r"^ network ", ospf, re.M)      # interfaces join area 0 only by `ip ospf N area`
    in_area, _connected = _core1_area0_and_connected(cols)
    # The inter-core home (Vlan10, an SVI both cores already have) and the dist1 transit -- nothing else.
    assert in_area == [_HOME, "GigabitEthernet1/0/40"], in_area
    # Each dist table holds exactly core1's originations (bar the transit dist1 is itself attached to),
    # with the route type the configuration implies.
    for host, via in (("dist1", ("10.0.140.1", "Gi1/0/3")), ("dist2", ("10.0.40.2", "Vlan40"))):
        rib = _routes(cols, host)
        for prefix, source in _core1_originated(cols).items():
            if host == "dist1" and prefix == "10.0.140.0/30":
                continue
            e = _only(rib[prefix])
            assert (e["source"], e["next_hop"], e["out_intf"]) == (source, *via), (host, prefix, e)
        learned = {p for p, es in rib.items() if _only(es)["source"].startswith("ospf")}
        assert learned == set(_core1_originated(cols)) - (
            {"10.0.140.0/30"} if host == "dist1" else set()), (host, sorted(learned))


def test_dist1_routes_to_the_core_over_the_routed_transit(cols):
    rib = _routes(cols, "dist1")
    for dst in ("10.0.20.0/24", "10.0.30.0/24", "0.0.0.0/0"):  # redistributed connected + the default
        e = _only(rib[dst])
        assert (e["source"], e["next_hop"], e["out_intf"]) == ("ospf-ext2", "10.0.140.1", "Gi1/0/3"), (dst, e)
    # Vlan10 is in area 0 (it carries the inter-core adjacency), so it is intra-area here.
    e = _only(rib["10.0.10.0/24"])
    assert (e["source"], e["next_hop"], e["out_intf"]) == ("ospf", "10.0.140.1", "Gi1/0/3"), e
    assert _only(rib["10.0.140.0/30"])["source"] == "connected"
    assert _only(rib["10.0.140.2/32"])["source"] == "local"
    for pod in ("10.0.40.0/24", "10.0.41.0/24"):
        assert _only(rib[pod])["source"] == "connected"


def test_dist2_routes_to_the_core_via_dist1_on_vlan40(cols):
    rib = _routes(cols, "dist2")
    for dst in ("10.0.20.0/24", "10.0.30.0/24", "0.0.0.0/0"):
        e = _only(rib[dst])
        assert (e["source"], e["next_hop"], e["out_intf"]) == ("ospf-ext2", "10.0.40.2", "Vlan40"), (dst, e)
    # dist1 puts the transit in area 0 with a network statement, and core1 puts Vlan10 there, so dist2
    # holds both intra-area.
    for dst in ("10.0.140.0/30", "10.0.10.0/24"):
        e = _only(rib[dst])
        assert (e["source"], e["next_hop"], e["out_intf"]) == ("ospf", "10.0.40.2", "Vlan40"), (dst, e)


def test_core1_routes_the_pod_back_to_dist1_and_owns_the_transit(cols):
    rib = _routes(cols, "core1")
    for pod in ("10.0.40.0/24", "10.0.41.0/24"):
        e = _only(rib[pod])
        assert (e["source"], e["next_hop"], e["out_intf"]) == ("ospf", "10.0.140.2", "Gi1/0/40"), (pod, e)
    assert _only(rib["10.0.140.1/32"])["source"] == "local"
    # The transit next hops are addresses the far end OWNS as a local /32 (how a trace resolves the next host).
    assert _only(_routes(cols, "dist1")["10.0.140.2/32"])["out_intf"] == "Gi1/0/3"


# --------------------------------------------------------------------------- the inter-core session's L3 home
# An OSPF adjacency cannot form on an L2 trunk port-channel: core1's FULL/DR session with core2 (router
# ID 10.0.99.2) needs an L3 home. Owner decision (phase 2.75, replacing O2's VLAN 900 transit, verifier
# R2V-4): run it over an SVI BOTH cores already have and Po1 already carries, so no L2 capture of either
# core changes and the cable map, move groups, wave sequencing and failure impact stay byte-equal to the
# committed fleet. Of the shared SVIs, Vlan10 is the one an adjacency can hold FULL on: core1's Vlan20
# carries the inbound VOICE_FILTER, whose closing `deny ip any any` drops OSPF hellos (IP protocol 89) --
# the fixture's own core1 log records the Vlan20 adjacency going down on its dead timer.
_HOME = "Vlan10"


def _svis(host_cols, host):
    """{SVI name: (address, prefix length, inbound ACL)} from a core's interface configuration."""
    text = host_cols[host][1]["show running-config | section ^interface" if host == "core1"
                              else "show running-config interface"]
    out = {}
    for name, cfg in parse_run_config_interfaces(text).items():
        if not name.startswith("Vlan") or not cfg.get("ip_addr"):
            continue
        iface = ipaddress.ip_interface(cfg["ip_addr"].replace(" ", "/"))
        out[name] = (str(iface.ip), iface.network.prefixlen, cfg.get("acl_in") or "")
    return out


def _po1_vlans(host_cols, host):
    cmd = "show interfaces trunk" if host == "core1" else "show interface trunk"
    return set(re.search(r"^Po1\s+(\S+)$", host_cols[host][1][cmd], re.M).group(1).split(","))


def _home_addresses(base_cols):
    """(core1's, core2's) address on the home SVI, read from the fixtures' own configuration."""
    return _svis(base_cols, "core1")[_HOME][0], _svis(base_cols, "core2")[_HOME][0]


def test_the_home_is_an_svi_both_cores_already_have_that_po1_already_carries(base_cols):
    """Derived from the fixtures as they were BEFORE the substrate: the candidate homes are the SVIs both
    cores own in one shared subnet on a VLAN Po1 carries on both sides; Vlan10 is one, and it is the one
    with no inbound ACL on either core (Vlan20's VOICE_FILTER would drop the hellos)."""
    c1, c2 = _svis(base_cols, "core1"), _svis(base_cols, "core2")
    shared_po1 = _po1_vlans(base_cols, "core1") & _po1_vlans(base_cols, "core2")
    candidates = sorted(
        name for name in set(c1) & set(c2)
        if name[len("Vlan"):] in shared_po1
        and ipaddress.ip_interface(f"{c1[name][0]}/{c1[name][1]}").network
        == ipaddress.ip_interface(f"{c2[name][0]}/{c2[name][1]}").network)
    assert candidates == ["Vlan10", "Vlan20"], candidates
    unfiltered = [name for name in candidates if not c1[name][2] and not c2[name][2]]
    assert unfiltered == [_HOME], unfiltered
    assert c1["Vlan20"][2] == "VOICE_FILTER"
    assert ("%OSPF-5-ADJCHG: Process 1, Nbr 10.0.99.2 on Vlan20 from FULL to DOWN, Neighbor Down: Dead timer expired"
            in base_cols["core1"][1]["show logging"])


def test_core1_inter_core_ospf_session_runs_over_the_home_svi(cols, base_cols, c2f):
    core1_addr, core2_addr = _home_addresses(base_cols)
    ospf = build_routing_neighbors(c2f["core1"])["ospf"]
    core2 = [n for n in ospf if n["neighbor"] == "10.0.99.2"]  # the router ID is kept
    assert [(n["address"], n["interface"], n["state"]) for n in core2] == [(core2_addr, _HOME, "FULL/DR")]
    stanzas = dict(re.findall(r"^interface (\S+)\n((?: .*\n)*)",
                              cols["core1"][1]["show running-config | section ^interface"], re.M))
    assert " ip ospf 1 area 0\n" in stanzas[_HOME]
    base_stanzas = dict(re.findall(r"^interface (\S+)\n((?: .*\n)*)",
                                   base_cols["core1"][1]["show running-config | section ^interface"], re.M))
    # The SVI keeps every line it had (address, helpers, HSRP group) and gains only the OSPF enable.
    assert stanzas[_HOME] == base_stanzas[_HOME] + " ip ospf 1 area 0\n"
    rib = _routes(cols, "core1")
    home = [(p, e) for p, es in rib.items() for e in es if e["source"] == "connected" and e["out_intf"] == _HOME]
    assert [p for p, _e in home] == ["10.0.10.0/24"]
    assert ipaddress.ip_address(core2_addr) in ipaddress.ip_network(home[0][0])
    assert _only(rib[f"{core1_addr}/32"])["source"] == "local"


def test_core2_owns_the_far_end_of_the_home_and_holds_what_core1_advertises(cols, base_cols):
    core1_addr, _core2_addr = _home_addresses(base_cols)
    stanzas = dict(re.findall(r"^interface (\S+)\n((?:  .*\n)*)",
                              cols["core2"][1]["show running-config interface"], re.M))
    base_stanzas = dict(re.findall(r"^interface (\S+)\n((?:  .*\n)*)",
                                   base_cols["core2"][1]["show running-config interface"], re.M))
    # NX-OS prints an SVI's `ip router ospf` BEFORE its `hsrp` sub-mode (2026-09-28 refuter F4: it was
    # appended after the sub-mode, a stanza no NX-OS device prints).
    assert stanzas[_HOME] == base_stanzas[_HOME].replace(
        "  hsrp 10\n", "  ip router ospf 1 area 0.0.0.0\n  hsrp 10\n", 1)
    lines = stanzas[_HOME].splitlines()
    assert lines.index("  ip router ospf 1 area 0.0.0.0") < lines.index("  hsrp 10")
    rib = _routes(cols, "core2")
    # What core1 originates into OSPF reaches core2 over the home SVI: its default (default-information
    # originate), its redistributed server VLAN, the pod and the dist1 transit. core2's own connected
    # Vlan10/20 win over core1's copies, as a real RIB's administrative distance decides.
    learned = {p: _only(es) for p, es in rib.items() if _only(es)["source"].startswith("ospf")}
    assert sorted(learned) == ["0.0.0.0/0", "10.0.140.0/30", "10.0.30.0/24", "10.0.40.0/24", "10.0.41.0/24"]
    assert {(e["next_hop"], e["out_intf"]) for e in learned.values()} == {(core1_addr, _HOME)}
    core1_rib = _routes(cols, "core1")
    for prefix, e in learned.items():
        # The type core1's configuration implies for what it originates; for what core1 itself learned
        # (the pod, from dist1), the type core1 holds it as.
        expected = _core1_originated(cols).get(prefix) or _only(core1_rib[prefix])["source"]
        assert e["source"] == expected, (prefix, e)
    for own in ("10.0.10.0/24", "10.0.20.0/24"):
        assert _only(rib[own])["source"] == "connected"


# The captures the substrate may change on each core; EVERY other capture -- every L2 capture (trunk,
# switchport, VLAN, interface status, spanning tree, port-channel, CDP) and the FHRP groups among them --
# is byte-identical to the fixtures', which is what keeps the cable map, move groups, wave sequencing and
# failure impact byte-equal to the committed fleet.
_CORE_CAPTURES_THE_SUBSTRATE_CHANGES = {
    "core1": {"show ip route", "show ip ospf neighbor", "show ip interface brief", "show running-config",
              "show running-config | section ^interface", "show ip bgp summary", "show ip eigrp neighbors"},
    "core2": {"show ip route", "show running-config interface"},
}


def test_only_the_cores_l3_captures_change(cols, base_cols):
    for host, allowed in _CORE_CAPTURES_THE_SUBSTRATE_CHANGES.items():
        changed = {cmd for cmd, text in cols[host][1].items() if base_cols[host][1].get(cmd) != text}
        assert changed == allowed, (host, sorted(changed ^ allowed))
        l2 = [cmd for cmd in cols[host][1]
              if re.search(r"trunk|switchport|vlan|status|spanning|channel|cdp|standby|hsrp|mac address", cmd)]
        assert len(l2) >= 7 and not set(l2) & allowed, (host, l2)


def test_the_core_fhrp_groups_and_every_other_core_capture_line_survive(cols, base_cols):
    for host, cmds in (("core1", ("show standby brief", "show standby all")), ("core2", ("show hsrp brief",))):
        for cmd in cmds:
            assert cols[host][1][cmd] == base_cols[host][1][cmd], (host, cmd)
    # Every line core1/core2 held before is still there, except the one neighbour row that moved off Po1
    # to the home SVI and core1's routing-table subnet-count header. core2 loses nothing.
    moved = {
        ("core1", "10.0.99.2         1   FULL/DR         00:00:35    10.0.99.2       Port-channel1"),
        ("core1", "      10.0.0.0/8 is variably subnetted, 8 subnets, 3 masks"),
    }
    lost = set()
    for host in ("core1", "core2"):
        for cmd, before in base_cols[host][1].items():
            now = set(cols[host][1][cmd].splitlines())
            lost |= {(host, line) for line in before.splitlines() if line not in now}
    assert lost == moved, sorted(lost ^ moved)


def test_no_trace_of_the_retired_vlan_900_transit_remains(cols, base_cols):
    """The VLAN 900 CORE-TRANSIT home (O2) is retired: no VLAN, subnet, SVI or allow-list entry of it is
    left in any capture of any host, and the builder no longer carries its constants."""
    retired = re.compile(r"(?i)core-transit|10\.0\.199\.|\bvlan ?900\b|(?:^|,)900(?:,|$)", re.M)
    hits = [(h, cmd) for h, (_p, outs) in cols.items() for cmd, text in outs.items() if retired.search(text)]
    assert hits == [], hits
    assert not [name for name in dir(bs) if "TRANSIT" in name.upper()]
    for host in ("core1", "core2"):
        assert _po1_vlans(cols, host) == _po1_vlans(base_cols, host)


def _up(state: str) -> bool:
    s = state.strip()
    return bool(re.fullmatch(r"\d+", s)) or bool(re.match(r"(?i)(full|2way|established|up)\b", s))


def test_every_session_on_a_routed_host_runs_over_a_link_its_table_holds(cols, c2f):
    """The per-adjacency form of 'one control plane' (the rule Atlas Scope's rib-completeness.ts
    applies): an up session with a recorded interface needs a connected route there covering the
    neighbour's address; a BGP peer (no interface) needs a route OTHER THAN THE DEFAULT covering it (the
    default covers every address, so it evidences no path to this one). No exception remains: the
    fixture's B1 seed -- core1's FULL/DR neighbour 10.0.99.2 on the L2 trunk Po1 -- now runs over
    Vlan10, an SVI both cores already have and core1's table holds as connected."""
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


def _bgp_baseline(host_cols, root):
    """The engine's BGP configured-peer baseline over `host_cols`, written by the real collection writer."""
    from cisco_toolkit.bgp_intent import compute_bgp_configured_peer_baseline
    from cisco_toolkit.capture_integrity import compute_capture_integrity
    bs._write_collection(root, host_cols)
    files = {h: {cmd: os.path.join(root, h, fx.cmd_filename(cmd)) for cmd in outs}
             for h, (_plat, outs) in host_cols.items()}
    integrity = compute_capture_integrity({h: dict(outs) for h, (_plat, outs) in host_cols.items()})
    devices = [{"hostname": h, "platform": plat} for h, (plat, _outs) in host_cols.items()]
    return compute_bgp_configured_peer_baseline(files, integrity, devices), integrity


def test_the_bgp_configured_peer_baseline_validates_over_the_substrate_collection(cols, tmp_path):
    """The engine's own validator accepts the baseline the substrate produces (structure and verdict agree).
    That is NOT a clean verdict: see the next test."""
    from cisco_toolkit.bgp_intent import validate_bgp_configured_peer_baseline
    baseline, _integrity = _bgp_baseline(cols, str(tmp_path))
    view = validate_bgp_configured_peer_baseline(baseline)
    assert (view["valid"], view["reason"]) == (True, "ok")


def test_core1_bgp_baseline_is_honestly_indeterminate_because_its_config_capture_is_incomplete(cols, tmp_path):
    """Owner decision (phase 2.75): core1's running-config keeps the fixtures' no-'end' convention, so the
    engine's capture-integrity guard reads it as incomplete while the substrate collects a configured,
    Established eBGP peer on core1. A configured peer whose configuration capture cannot be trusted is not
    verified, so INDETERMINATE is the coverage-honest verdict -- not NOT_APPLICABLE, not CLEAR. The reason is
    read from the producers' own output, and a counterfactual proves it is the whole reason: the same
    collection with core1's capture terminated is CLEAR."""
    baseline, integrity = _bgp_baseline(cols, str(tmp_path / "as_collected"))
    assert (baseline["verdict"], baseline["assessed"]) == ("INDETERMINATE", False)
    # The only BGP subject is core1, and its only row is the peer core1's own summary reports Established.
    assert [c["switch"] for c in baseline["coverage"] if c["subject"]] == ["core1"]
    peers = [p["neighbor"] for p in build_routing_neighbors(
        {cmd: str(tmp_path / "as_collected" / "core1" / fx.cmd_filename(cmd)) for cmd in cols["core1"][1]})["bgp"]]
    [row] = baseline["rows"]
    assert (row["switch"], [row["peer"]]) == ("core1", peers)
    assert (row["runtime_observed"], row["runtime_state"]) == (True, "ESTABLISHED")
    assert (row["status"], [f["code"] for f in row["findings"]]) == ("not_verified", ["capture_not_verified"])
    # WHY: the configuration capture's integrity status, exactly as the capture-integrity producer found it.
    [finding] = [f for f in integrity["findings"] if (f["host"], f["command"]) == ("core1", "show running-config")]
    [cov] = [c for c in baseline["coverage"] if c["switch"] == "core1"]
    assert (cov["config_capture_status"], cov["runtime_capture_status"]) == (finding["status"], "ok")
    assert finding["status"] != "ok"
    assert inspect_capture("show running-config", cols["core1"][1]["show running-config"]) == {
        k: finding[k] for k in ("status", "reason", "evidence")}
    assert "BLOCKER" in row["acceptance"] and "NOT VERIFIED" in row["acceptance"]
    # Counterfactual: terminate core1's capture (a scratch copy, never the substrate) and nothing else.
    whole = copy.deepcopy(cols)
    whole["core1"][1]["show running-config"] += "end\n"
    clean, clean_integrity = _bgp_baseline(whole, str(tmp_path / "terminated"))
    assert not [f for f in clean_integrity["findings"] if (f["host"], f["command"]) == ("core1", "show running-config")]
    assert (clean["verdict"], [r["status"] for r in clean["rows"]]) == ("CLEAR", ["assessed"])


def test_every_learned_route_has_its_protocol_adjacency(cols, base_cols, c2f):
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
    # unknown); every route it learned names, as next hop, core1's address on the home SVI -- and core1
    # records that very session FULL there, at core2's address on the same SVI.
    core1_addr, core2_addr = _home_addresses(base_cols)
    nexthops = {(e["next_hop"], e["out_intf"]) for es in _routes(cols, "core2").values() for e in es
                if e["source"] not in ("connected", "local")}
    assert nexthops == {(core1_addr, _HOME)}
    assert "show ip ospf neighbor" not in cols["core2"][1]
    assert any((n["address"], n["interface"]) == (core2_addr, _HOME) and n["state"].startswith("FULL")
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
_IOS_SUBNET_HEADER = re.compile(
    r"^\s+(\d+\.\d+\.\d+\.\d+)/(\d+) is variably subnetted, (\d+) subnets, (\d+) masks$", re.M)
_IOS_ROUTE_LINE = re.compile(r"^[A-Za-z*]+(?:\s+[A-Z0-9]+)?\s+(\d+\.\d+\.\d+\.\d+/\d+)\s", re.M)


def test_every_ios_route_table_header_counts_the_subnets_it_lists(cols):
    """A real IOS table's 'is variably subnetted, N subnets, M masks' header counts exactly the prefixes it
    lists under that major network (2026-09-28 refuter F4: core1's said 12 and listed 11 -- the substrate
    carried an off-by-one forward from the fixture's own header). Checked over EVERY built table that carries
    the header, not the hosts the substrate edits."""
    checked = 0
    for host, (_plat, captures) in cols.items():
        table = captures.get("show ip route", "")
        for major, bits, n, m in _IOS_SUBNET_HEADER.findall(table):
            net = ipaddress.ip_network(f"{major}/{bits}")
            listed = [p for p in _IOS_ROUTE_LINE.findall(table) if ipaddress.ip_network(p).subnet_of(net)]
            masks = {p.split("/")[1] for p in listed}
            assert (int(n), int(m)) == (len(listed), len(masks)), (host, major, n, m, listed)
            checked += 1
    assert checked >= 3  # core1, dist1 and dist2 at least: the guard is not inert


def test_registry_clock_is_the_demo_evidence_date(tmp_path, monkeypatch):
    """The demo's registry-health statement is judged at ITS OWN evidence date, through the same seam and rule
    as the golden harness (tests/test_pipeline_golden.py, _GOLDEN_REGISTRY_CLOCK). Judged against the wall
    clock, a regeneration after the retained registries' freshness window would flip every authority to stale
    and cascade into assessment_integrity: the demo would change with the calendar, not the engine
    (2026-09-28 refuter F1). The pipeline is stubbed; main()'s pinning around it is real."""
    from datetime import datetime, timezone
    from cisco_toolkit import eoldb, ouidb, portdb, registry_integrity as ri

    stamp = bs._SAMPLE_COLLECTION_STAMP
    expected = datetime(int(stamp[0:4]), int(stamp[4:6]), int(stamp[6:8]), tzinfo=timezone.utc)
    real_datetime = ri.datetime
    seen = {}

    def fake_pipeline():
        seen["now"] = ri.datetime.now(timezone.utc)
        seen["naive_now"] = ri.datetime.now()
        seen["cached"] = [c.cache_info().currsize for c in
                          (eoldb._runtime_source_proof, ouidb._registry, portdb._registry)]
        xlsx = sys.argv[sys.argv.index("--output") + 1]
        with open(os.path.splitext(xlsx)[0] + ".snapshot.json", "w", encoding="utf-8", newline="\n") as f:
            f.write('{"devices": {}, "punchlist": []}')

    monkeypatch.setattr(bs.cp, "main", fake_pipeline)
    monkeypatch.setattr(bs, "build_collections", lambda: {"x": ("ios", {"show version": "v\n"})})
    bs.main(["--out", str(tmp_path / "fleet.json")])
    assert seen["now"] == expected
    assert seen["naive_now"].astimezone(timezone.utc) == expected
    assert seen["cached"] == [0, 0, 0]  # no registry verdict computed under another clock is reused
    assert ri.datetime is real_datetime  # the real clock is restored after the run


def test_volatile_strip_keeps_the_now_deterministic_registry_age():
    snap = {"generated_at": "t", "attestation": {"generated_at": "t", "x": 1},
            "data_authorities": {"eol": {"source_age_days": 7.4, "freshness_status": "fresh"}}}
    out = bs._strip_volatile(snap)
    assert "generated_at" not in out and "generated_at" not in out["attestation"]
    assert out["data_authorities"]["eol"]["source_age_days"] == 7.4


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
