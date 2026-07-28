"""Regression guard for docs/review-findings-2026-07-28.md finding #79 (design_kb coverage honesty)."""
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
    Guard the three that remain by proving no decision carries their id on the fixture that fires the
    whole switch-fleet detector set."""
    still = design_kb._NOT_YET_AUTO_DETECTED
    assert "security-l2-access-edge-suite" not in still
    assert still, "the block is not empty -- three principles are still genuinely undetected"
    for pid in still:
        assert design_kb.by_id(pid) is not None, f"{pid} is not a registered principle"
        assert design_kb.by_id(pid)["engine_actionable"] is False, pid
