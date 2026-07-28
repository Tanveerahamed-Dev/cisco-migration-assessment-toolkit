"""Regression guard for docs/review-findings-2026-07-28.md finding #79 (design_kb coverage honesty)."""
from pathlib import Path

import cisco_toolkit.design_advisor as da
from cisco_toolkit import design_kb


def test_l2_access_edge_suite_is_not_demoted_while_the_advisor_emits_it():
    """#79 `_NOT_YET_AUTO_DETECTED` force-set engine_actionable=False for security-l2-access-edge-suite on
    the ground "no port-security / BPDU-guard / DHCP-snooping finding collected". That went stale when
    design_advisor._d_port_security_errdisable landed: it emits exactly this principle id from
    snap['port_security'] (parse_port_security_detail / 'show port-security interface'). The stale flag is
    republished VERBATIM by _doctrine_catalog() into design_blueprint.doctrine, which the HLD and the /ask
    surface read -- so a client-facing surface under-claimed real, shipped coverage."""
    snap = {"port_security": {"access1": {"Gi0/10": {"port_status": "Secure-shutdown",
                                                     "last_src": "0011.2233.4455"}}}}
    bp = da.compute_design_blueprint(snap)
    assert "security-l2-access-edge-suite" in {d["id"] for d in bp["decisions"]}, \
        "pre-condition: the advisor DOES emit this principle from collected evidence"
    p = design_kb.by_id("security-l2-access-edge-suite")
    assert p["engine_actionable"] is True, "a principle the advisor emits must not be demoted"
    assert "security-l2-access-edge-suite" in {x["id"] for x in design_kb.engine_actionable()}
    # and the flag as PUBLISHED (doctrine catalog -> design_blueprint.doctrine -> HLD / /ask) agrees
    pub = [x for row in bp["doctrine"].values() if isinstance(row, list) for x in row
           if isinstance(x, dict) and x.get("id") == "security-l2-access-edge-suite"]
    assert pub and all(x.get("engine_actionable") is True for x in pub), pub


def test_the_remaining_demotions_are_still_honest():
    """The block is only legitimate for principles the advisor genuinely does NOT emit; a demotion that
    outlives its detector is the same overstated/understated-coverage defect in the other direction.
    Guard the ones that remain by proving no decision carries their id on the fixture that fires the
    whole switch-fleet detector set, AND that no detector names the id at all.

    NB the `engine_actionable is False` assertion this test used to make was VACUOUS: design_kb's own
    module-level demotion loop force-sets that flag for every id in the block, so the assertion restated
    the input. A stale demotion -- #79 exactly -- passed it silently, and the forward lock
    (test_every_engine_actionable_principle_is_emitted) only checks actionable-but-not-emitted, so
    emitted-but-demoted was unguarded in BOTH directions. Verified by injecting an emitted principle
    (dc-lacp-over-static-etherchannel) into the block: the old body passed while the advisor kept
    emitting it and design_kb.engine_actionable() hid it."""
    still = design_kb._NOT_YET_AUTO_DETECTED
    assert "security-l2-access-edge-suite" not in still
    assert still, "the block is not empty -- some principles are still genuinely undetected"
    for pid in still:
        assert design_kb.by_id(pid) is not None, f"{pid} is not a registered principle"

    # (a) BEHAVIOURAL: nothing the advisor emits on the maximal + every-architecture fixtures may be
    #     demoted here. Runs the real advisor rather than re-reading the flag design_kb just set.
    from test_design_blueprint import _maximal_snap, _arch_fire_snap
    emitted = set()
    for snap in (_maximal_snap(), _arch_fire_snap()):
        emitted |= {d["id"] for d in da.compute_design_blueprint(snap)["decisions"]}
    stale = sorted(still & emitted)
    assert not stale, f"demoted as un-detectable, but the advisor emits them: {stale}"

    # (b) STATIC, and the stronger arm: a detector can exist while the fixture lacks its evidence --
    #     which is how #79 hid (snap['port_security'] was only added to _maximal_snap by that fix).
    #     Every one of the 90 ids the advisor emits appears as a literal in its source, so an id named
    #     anywhere in design_advisor.py has a detector and must not be demoted.
    src = Path(da.__file__).read_text(encoding="utf-8")
    named = sorted(pid for pid in still if pid in src)
    assert not named, f"demoted as un-detectable, but design_advisor.py names them: {named}"
