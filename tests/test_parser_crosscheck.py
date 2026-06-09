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
    * Normalize BOTH sides through the project's own ``normalize_ifname`` so interface naming
      (``Gi0/1`` vs ``GigabitEthernet0/1``) can never cause a false mismatch.
    * Assert the project found AT LEAST every entity the reference found (a SUPERSET check). This is
      the gap-detecting direction. The reverse is intentionally NOT asserted because the reference
      parser is itself imperfect: e.g. on the core1 fixture ntc-templates misses the Port-channel
      CDP neighbour that the project's parser correctly reports — so a strict ``==`` would fail on a
      project STRENGTH. We only fail when the project misses something the reference saw.

EXTENDING
    Point it at real captures: drop ``show …`` outputs into per-host text and add a command to the
    ``_CDP_*`` style helpers below, or parametrize a new ``test_<command>_…`` over the same
    (project-parser, ntc-command, identity-extractor) shape. The synthetic fixtures here are the
    smoke layer; the real signal comes from running this against diverse production output.
"""
import pytest

# Reference parser is optional: skip the whole module (with a clear reason) when it's absent.
ntc_parse = pytest.importorskip("ntc_templates.parse",
                                reason="ntc-templates not installed (dev-only cross-check dependency)")

import synthetic_fixtures as fx                                   # noqa: E402
from cisco_toolkit.parse import normalize_ifname, parse_neighbors_cdp   # noqa: E402

# The IOS hosts in the fixture set that carry `show cdp neighbors detail` (ntc platform = cisco_ios).
_IOS_HOSTS_WITH_CDP = [
    h for h, (plat, cmds) in fx.COLLECTIONS.items()
    if plat == "ios" and "show cdp neighbors detail" in cmds
]


def _ntc_cdp_local_ifaces(data: str) -> set:
    """Local-interface set the reference parser extracts from `show cdp neighbors detail`,
    normalized through the project's own ifname normalizer for an apples-to-apples comparison."""
    recs = ntc_parse.parse_output(platform="cisco_ios",
                                  command="show cdp neighbors detail", data=data)
    out = set()
    for r in recs:
        # ntc-templates key naming has shifted across versions; accept the known spellings.
        local = r.get("local_interface") or r.get("LOCAL_PORT") or r.get("local_port") or ""
        if local:
            out.add(normalize_ifname(local.strip()))
    return out


@pytest.mark.parametrize("host", _IOS_HOSTS_WITH_CDP)
def test_cdp_neighbors_project_misses_no_reference_link(host):
    """The hand-rolled CDP parser must discover at least every neighbour link the reference parser
    finds — i.e. it never silently drops a CDP adjacency the community template catches."""
    data = fx.COLLECTIONS[host][1]["show cdp neighbors detail"]

    project_ifaces = set(parse_neighbors_cdp(data).keys())   # already normalized + keyed by local intf
    reference_ifaces = _ntc_cdp_local_ifaces(data)

    if not reference_ifaces:
        pytest.skip(f"reference parser matched no CDP neighbours on the {host} fixture — nothing to cross-check")

    missed = reference_ifaces - project_ifaces
    assert not missed, (
        f"{host}: the project CDP parser MISSED neighbour link(s) the reference parser found "
        f"on local interface(s) {sorted(missed)} — likely a parsing gap. "
        f"project={sorted(project_ifaces)} reference={sorted(reference_ifaces)}"
    )


def test_harness_actually_runs_against_the_fixtures():
    """Guard the guard: make sure the parametrization isn't empty (a refactor that renamed the CDP
    command or the fixture host keys would silently disable the cross-check above)."""
    assert _IOS_HOSTS_WITH_CDP, "no IOS hosts with a `show cdp neighbors detail` fixture were found"
