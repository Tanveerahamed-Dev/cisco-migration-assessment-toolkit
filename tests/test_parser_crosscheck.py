"""Parser cross-check harness — validate the project's hand-rolled regex parsers against a
community reference parser (ntc-templates / TextFSM) on the synthetic fixtures.

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

DESIGN — deliberately robust, not brittle
    * Compare normalized identifier SETS, never field-by-field text: two independent parsers will
      format/case values differently, and that is not a bug.
    * Normalize interface names through the project's own ``normalize_ifname`` so naming
      (``Gi0/1`` vs ``GigabitEthernet0/1``) can never cause a false mismatch.
    * Assert the project found AT LEAST every entity the reference found (a SUPERSET check). This is
      the gap-detecting direction. The reverse is intentionally NOT asserted because the reference
      parser is itself imperfect: e.g. on the core1 fixture ntc-templates misses the Port-channel
      CDP neighbour that the project's parser correctly reports — so a strict ``==`` would fail on a
      project STRENGTH. We only fail when the project misses something the reference saw.

COVERAGE
    Cross-checks ``show cdp neighbors detail`` (neighbour links), ``show vlan brief`` (VLAN ids), and
    ``show ip ospf neighbor`` (routing adjacencies) across the IOS fixtures. Add a command by writing
    one more ``test_<command>_…`` that extracts the project's and the reference's identifier sets and
    calls ``_assert_project_superset`` — the synthetic fixtures are the smoke layer; the real signal
    comes from running this against diverse production output.
"""
import pytest

# Reference parser is optional: skip the whole module (with a clear reason) when it's absent.
ntc_parse = pytest.importorskip("ntc_templates.parse",
                                reason="ntc-templates not installed (dev-only cross-check dependency)")

import synthetic_fixtures as fx                                              # noqa: E402
from cisco_toolkit.parse import (                                           # noqa: E402
    normalize_ifname, parse_neighbors_cdp, parse_vlan_brief, parse_ospf_neighbors,
)


def _ios_hosts_with(command: str):
    """IOS fixture hosts (ntc platform = cisco_ios) that carry `command`."""
    return [h for h, (plat, cmds) in fx.COLLECTIONS.items()
            if plat == "ios" and command in cmds]


def _ntc(command: str, data: str):
    """Reference (ntc-templates) records for an IOS `command`."""
    return ntc_parse.parse_output(platform="cisco_ios", command=command, data=data)


def _assert_project_superset(host: str, kind: str, project_ids: set, reference_ids: set):
    """Fail iff the project parser missed an identifier the reference parser found. Skip (don't pass
    vacuously) when the reference matched nothing on this fixture, so a green run means a real check."""
    if not reference_ids:
        pytest.skip(f"reference parser matched no {kind} on the {host} fixture — nothing to cross-check")
    missed = reference_ids - project_ids
    assert not missed, (
        f"{host}: the project parser MISSED {kind} the reference parser found: {sorted(missed)} "
        f"— likely a parsing gap. project={sorted(project_ids)} reference={sorted(reference_ids)}"
    )


@pytest.mark.parametrize("host", _ios_hosts_with("show cdp neighbors detail"))
def test_cdp_neighbors_no_missed_link(host):
    """The hand-rolled CDP parser must discover at least every neighbour link the reference finds."""
    data = fx.COLLECTIONS[host][1]["show cdp neighbors detail"]
    project = set(parse_neighbors_cdp(data).keys())          # already normalized + keyed by local intf
    reference = {normalize_ifname((r.get("local_interface") or r.get("local_port") or "").strip())
                 for r in _ntc("show cdp neighbors detail", data)
                 if (r.get("local_interface") or r.get("local_port"))}
    _assert_project_superset(host, "CDP neighbour link(s) (local interface)", project, reference)


@pytest.mark.parametrize("host", _ios_hosts_with("show vlan brief"))
def test_vlan_brief_no_missed_vlan(host):
    """The hand-rolled VLAN parser must discover at least every VLAN id the reference finds."""
    data = fx.COLLECTIONS[host][1]["show vlan brief"]
    project = {str(v) for v in parse_vlan_brief(data).keys()}
    reference = {str(r["vlan_id"]) for r in _ntc("show vlan brief", data) if r.get("vlan_id")}
    _assert_project_superset(host, "VLAN id(s)", project, reference)


@pytest.mark.parametrize("host", _ios_hosts_with("show ip ospf neighbor"))
def test_ospf_neighbor_no_missed_adjacency(host):
    """The hand-rolled OSPF parser must discover at least every adjacency (by neighbour Router ID)
    the reference finds — a dropped adjacency would understate the routing topology."""
    data = fx.COLLECTIONS[host][1]["show ip ospf neighbor"]
    project = {row["neighbor"] for row in parse_ospf_neighbors(data)}
    reference = {r["neighbor_id"] for r in _ntc("show ip ospf neighbor", data) if r.get("neighbor_id")}
    _assert_project_superset(host, "OSPF adjacency/adjacencies (neighbour Router ID)", project, reference)


def test_harness_actually_runs_against_the_fixtures():
    """Guard the guard: make sure the parametrizations aren't empty (a refactor that renamed a command
    or the fixture host keys would silently disable the cross-checks above)."""
    assert _ios_hosts_with("show cdp neighbors detail"), "no IOS host with a CDP fixture"
    assert _ios_hosts_with("show vlan brief"), "no IOS host with a VLAN-brief fixture"
    assert _ios_hosts_with("show ip ospf neighbor"), "no IOS host with an OSPF-neighbor fixture"
