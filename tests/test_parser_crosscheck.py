"""Parser cross-check harness — validate the project's hand-rolled regex parsers against a
community reference parser (ntc-templates / TextFSM) on the synthetic fixtures, across BOTH
IOS and NX-OS.

WHY THIS EXISTS
    The collector's parsers are deliberately hand-rolled (offline, stdlib-only — no heavy Genie /
    pyATS runtime dependency). The standing risk of that choice is that a regex silently MISSES an
    entity on a real-world output shape — the exact failure mode this project has hit before
    (CDP-FQDN handling, a 4948E `show env` block, NX-OS variants). This harness cross-checks the
    hand-rolled output against ntc-templates so that class of regression is caught automatically.

DEV-ONLY DEPENDENCY
    ntc-templates is a *test* dependency (requirements-dev.txt), not a runtime one — the shipped
    tool still has zero new dependencies. When ntc-templates isn't installed these tests skip, so
    the core suite stays dependency-light; CI installs it, so they run there.

DESIGN — deliberately robust, not brittle (unchanged from the original 3-command harness)
    * Compare normalized identifier SETS, never field-by-field text.
    * Normalize interface names / MACs so cosmetic formatting can never cause a false mismatch.
    * Assert the project found AT LEAST every entity the reference found (a SUPERSET check) — the
      gap-detecting direction. The reverse is intentionally NOT asserted because the reference is
      itself imperfect (it misses the Port-channel CDP neighbour the project reports; on NX-OS it is
      a documented misread surface — ubest/mbest RIB, HSRPv2, BFD). Where the community template
      simply ERRORS on an off-shape fixture, the referee is unavailable and we skip (never pass
      vacuously and never assert against a broken reference — the "TextFSM is a referee, not the
      lane" doctrine).

COVERAGE (widened — Plan-A #17)
    A data-driven registry cross-checks CDP / VLAN / interface-status / version / MAC-table across
    IOS *and* NX-OS, plus OSPF-neighbor and ip-route on IOS — ~18 host x command checks spanning both
    operating systems. Add a command by appending one CROSSCHECKS row (a project extractor + a
    reference extractor). The synthetic fixtures are the smoke layer; the real signal comes from
    running this against diverse production output.
"""
import re

import pytest

# Reference parser is optional: skip the whole module (with a clear reason) when it's absent.
ntc_parse = pytest.importorskip("ntc_templates.parse",
                                reason="ntc-templates not installed (dev-only cross-check dependency)")

import synthetic_fixtures as fx                                              # noqa: E402
from cisco_toolkit.parse import (                                           # noqa: E402
    normalize_ifname, parse_neighbors_cdp, parse_vlan_brief, parse_ospf_neighbors,
    parse_show_interface_status, parse_show_version, parse_show_mac_address_table, parse_ip_routes,
)

_PLAT = {"ios": "cisco_ios", "nxos": "cisco_nxos"}


def _ifset(names):
    return {normalize_ifname(n) for n in names if n}


def _mac(m):
    return re.sub(r"[^0-9a-fA-F]", "", m or "").lower()


# --- project extractors: (raw output) -> set of normalized identifiers ---------------
def _p_cdp(d):    return set(parse_neighbors_cdp(d).keys())                       # keyed by local intf
def _p_vlan(d):   return {str(v) for v in parse_vlan_brief(d).keys()}
def _p_ospf(d):   return {r["neighbor"] for r in parse_ospf_neighbors(d) if r.get("neighbor")}
def _p_ifst(d):   return _ifset(parse_show_interface_status(d).keys())
def _p_ver(d):    return {(parse_show_version(d).get("serial_number") or "").strip().upper()} - {""}
def _p_mac(d):    return {_mac(m) for macs in parse_show_mac_address_table(d).values() for m in macs} - {""}
def _p_route(d):  return set(parse_ip_routes(d).keys())


# --- reference (ntc-templates) extractors: (records) -> set --------------------------
def _r_cdp(recs):    return _ifset(r.get("local_interface") or r.get("local_port") for r in recs)
def _r_vlan(recs):   return {str(r["vlan_id"]) for r in recs if r.get("vlan_id")}
def _r_ospf(recs):   return {r["neighbor_id"] for r in recs if r.get("neighbor_id")}
def _r_ifst(recs):   return _ifset(r.get("port") or r.get("interface") for r in recs)
def _r_ver(recs):    return {(r.get("serial") or "").strip().upper() for r in recs if r.get("serial")}
def _r_mac(recs):    return {_mac(r.get("destination_address") or r.get("mac_address")) for r in recs
                             if (r.get("destination_address") or r.get("mac_address"))} - {""}
def _r_route(recs):  return {f"{r['network']}/{r['prefix_length']}" for r in recs
                             if r.get("network") and r.get("prefix_length")}


# (command, kind, project_extractor, reference_extractor)
CROSSCHECKS = [
    ("show cdp neighbors detail", "CDP neighbour link (local intf)", _p_cdp, _r_cdp),
    ("show vlan brief",           "VLAN id",                         _p_vlan, _r_vlan),
    ("show ip ospf neighbor",     "OSPF adjacency (neighbour RID)",  _p_ospf, _r_ospf),
    ("show interface status",     "interface (port)",                _p_ifst, _r_ifst),
    ("show version",              "chassis serial",                  _p_ver, _r_ver),
    ("show mac address-table",    "MAC address",                     _p_mac, _r_mac),
    ("show ip route",             "route prefix",                    _p_route, _r_route),
]
_BY_CMD = {row[0]: row for row in CROSSCHECKS}


def _cases():
    """(host, platform, command) triples where the fixture carries a cross-checkable command."""
    return [(host, plat, cmd)
            for host, (plat, cmds) in fx.COLLECTIONS.items()
            for cmd, *_ in CROSSCHECKS if cmd in cmds]


def _ntc(plat, cmd, data):
    """Reference records, or None when the community template ERRORS on this fixture shape (an
    off-shape NX-OS RIB / trunk block) — in which case the referee is unavailable, not a failure."""
    try:
        return ntc_parse.parse_output(platform=_PLAT[plat], command=cmd, data=data)
    except Exception:
        return None


@pytest.mark.parametrize("host,plat,cmd", _cases())
def test_project_parser_is_superset_of_reference(host, plat, cmd):
    _, kind, pfn, rfn = _BY_CMD[cmd]
    data = fx.COLLECTIONS[host][1][cmd]
    recs = _ntc(plat, cmd, data)
    if recs is None:
        pytest.skip(f"ntc template errored on the {host}[{plat}] {cmd!r} fixture (off-shape) — referee unavailable")
    reference = rfn(recs)
    if not reference:
        pytest.skip(f"reference matched no {kind} on {host}[{plat}] — nothing to cross-check")
    project = pfn(data)
    missed = reference - project
    assert not missed, (
        f"{host}[{plat}]: the project parser MISSED {kind} the reference found: {sorted(missed)} "
        f"— likely a parsing gap. project={sorted(project)} reference={sorted(reference)}")


def test_harness_covers_ios_and_nxos():
    """Guard the guard: the widened set must actually span both operating systems and not have been
    silently emptied by a fixture-key rename."""
    cases = _cases()
    plats = {plat for _, plat, _ in cases}
    assert "ios" in plats and "nxos" in plats, f"cross-check must span IOS and NX-OS; got {plats}"
    assert len(cases) >= 12, f"expected the widened cross-check set (>=12 host x command); got {len(cases)}"
