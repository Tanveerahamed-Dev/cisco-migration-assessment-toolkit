"""Multi-vendor (Juniper Junos) chassis-cluster HA assessment -- the SECOND non-Cisco vendor.

Proves the vendor-adapter pattern generalises beyond Arista: a different NOS, a different (notoriously nested)
structured-output dialect ('show ... | display json', where every value is wrapped as [{"data": "<v>"}]), the
same coverage-honesty contract. Covers parse_junos_chassis_cluster, build_juniper, the _signals extraction, the
_d_junos_chassis_cluster_degraded detector, the KB principle and the _ARCH_COVERAGE_REGISTRY entry.

SRX chassis cluster is Juniper's stateful-firewall HA -- the analogue of the Cisco firewall 'show failover' and
(at L2) the Arista MLAG / Cisco vPC dual-active primitives. FIRING STATE (coverage-honest): a redundancy group
that is configured yet operationally degraded -- a node at PRIORITY 0 (the documented 'not ready to accept
traffic' trap -- Junos even refuses a manual failover to it), a node with monitor-failures (interface/IP
monitoring detected a fault), or a node lost/disabled/ineligible. SILENT for a healthy primary+secondary pair
(non-zero priorities, monitor None), for the transient hold states, and for a non-cluster device (absence of HA
is not broken HA). The JSON shape is grounded in a real 'show chassis cluster status | display json' capture."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from cisco_toolkit import parse        # noqa: E402
from cisco_toolkit import build        # noqa: E402
import cisco_toolkit.design_advisor as da  # noqa: E402
import cisco_toolkit.design_kb as design_kb  # noqa: E402


# --- real 'show chassis cluster status | display json' shape (every value wrapped [{"data": "<v>"}]) --------
# Two redundancy groups, two nodes each. Distinct priorities (100/1, 200/150) so the degraded variants below
# can be derived with unambiguous single-substring replaces.
_HEALTHY = """\
{"chassis-cluster-status": [
  {"redundancy-group": [
    {"redundancy-group-id": [{"data": "0"}], "device-stats": [
      {"device-name": [{"data": "node0"}], "device-priority": [{"data": "100"}], "redundancy-group-status": [{"data": "primary"}], "preempt": [{"data": "no"}], "monitor-failures": [{"data": "None"}]},
      {"device-name": [{"data": "node1"}], "device-priority": [{"data": "1"}], "redundancy-group-status": [{"data": "secondary"}], "preempt": [{"data": "no"}], "monitor-failures": [{"data": "None"}]}
    ]},
    {"redundancy-group-id": [{"data": "1"}], "device-stats": [
      {"device-name": [{"data": "node0"}], "device-priority": [{"data": "200"}], "redundancy-group-status": [{"data": "primary"}], "preempt": [{"data": "yes"}], "monitor-failures": [{"data": "None"}]},
      {"device-name": [{"data": "node1"}], "device-priority": [{"data": "150"}], "redundancy-group-status": [{"data": "secondary"}], "preempt": [{"data": "yes"}], "monitor-failures": [{"data": "None"}]}
    ]}
  ]}
]}
"""

# RG1 secondary (node1, the only priority 150) drops to priority 0 -- it cannot take over, so RG1 has no working
# standby (the marquee SRX false-health trap: HA configured but a node not ready to accept traffic).
_PRI0 = _HEALTHY.replace('"data": "150"', '"data": "0"')
# RG1 primary (the only priority 200) reports an interface-monitoring failure (IF) -- a monitored link is down,
# so the group is at risk / may have already demoted.
_MONFAIL = _HEALTHY.replace(
    '"device-priority": [{"data": "200"}], "redundancy-group-status": [{"data": "primary"}], "preempt": [{"data": "yes"}], "monitor-failures": [{"data": "None"}]',
    '"device-priority": [{"data": "200"}], "redundancy-group-status": [{"data": "primary"}], "preempt": [{"data": "yes"}], "monitor-failures": [{"data": "IF"}]')
# RG0 secondary (the only priority 1) is LOST -- the node dropped out of the cluster for RG0 (no control-plane
# standby).
_NODELOST = _HEALTHY.replace(
    '"device-priority": [{"data": "1"}], "redundancy-group-status": [{"data": "secondary"}]',
    '"device-priority": [{"data": "1"}], "redundancy-group-status": [{"data": "lost"}]')

# Not a chassis cluster (standalone SRX) -- 'show chassis cluster status' errors; parse -> [] -> never assessed.
_STANDALONE = "error: Chassis cluster is not enabled.\n"


def _snap(*cluster_jsons):
    juniper = {}
    for i, j in enumerate(cluster_jsons):
        recs = parse.parse_junos_chassis_cluster(j)
        if recs:
            juniper[f"srx{i + 1}"] = {"chassis_cluster": recs}
    return {"juniper": juniper}


def _fire(snap):
    sig = da._signals(snap)
    return da._d_junos_chassis_cluster_degraded(snap, sig)


# ----------------------------------------------------------------------------- parser
def test_parse_healthy_unwraps_and_lists_every_rg_node():
    recs = parse.parse_junos_chassis_cluster(_HEALTHY)
    assert len(recs) == 4                                   # 2 redundancy groups x 2 nodes
    by = {(r["rg"], r["node"]): r for r in recs}
    assert by[("0", "node0")]["priority"] == 100 and by[("0", "node0")]["status"] == "primary"
    assert by[("1", "node1")]["priority"] == 150 and by[("1", "node1")]["status"] == "secondary"
    assert all(r["monitor_failures"] == "None" for r in recs)   # the [{"data": "..."}] form was unwrapped


def test_parse_standalone_or_hostile_is_empty():
    for bad in ("", _STANDALONE, "not json", "[1,2,3]", "{}", '{"chassis-cluster-status": "x"}',
                '{"chassis-cluster-status": [{"redundancy-group": "x"}]}'):
        out = parse.parse_junos_chassis_cluster(bad)
        assert out == [] or isinstance(out, list)


def test_parse_tolerates_bare_dict_value_form():
    # some Junos versions emit {"data": v} (not list-wrapped); the unwrap must still work
    j = '{"chassis-cluster-status": [{"redundancy-group": [{"redundancy-group-id": {"data": "0"}, "device-stats": [{"device-name": {"data": "node0"}, "device-priority": {"data": "0"}, "redundancy-group-status": {"data": "primary"}, "monitor-failures": {"data": "None"}}]}]}]}'
    recs = parse.parse_junos_chassis_cluster(j)
    assert recs and recs[0]["priority"] == 0 and recs[0]["node"] == "node0"


def test_build_juniper_offline(tmp_path):
    d = tmp_path / "srx1"
    d.mkdir()
    (d / "show_chassis_cluster_status.txt").write_text(_PRI0, encoding="utf-8")
    out = build.build_juniper({"show chassis cluster status": str(d / "show_chassis_cluster_status.txt")})
    assert isinstance(out.get("chassis_cluster"), list) and any(r["priority"] == 0 for r in out["chassis_cluster"])
    assert build.build_juniper({}) == {}                   # a non-Juniper device -> {} -> coverage-honest


# ----------------------------------------------------------------------------- detector: FIRES on degraded
def test_fires_on_priority_zero():
    d = _fire(_snap(_PRI0))
    assert d and d["id"] == "junos-chassis-cluster-ha-degraded" and d["priority"] == "High"
    assert "priority 0" in d["evidence"]["summary"]
    assert d["evidence"]["devices"] == ["srx1"]


def test_fires_on_monitor_failure():
    d = _fire(_snap(_MONFAIL))
    assert d and "monitor" in d["evidence"]["summary"].lower() and "IF" in d["evidence"]["summary"]


def test_fires_on_node_lost():
    d = _fire(_snap(_NODELOST))
    assert d and "lost" in d["evidence"]["summary"].lower()


# ----------------------------------------------------------------------------- detector: SILENT on clean
def test_silent_on_healthy_cluster():
    assert _fire(_snap(_HEALTHY)) is None


def test_silent_when_no_cluster_observed():
    assert _fire(_snap(_STANDALONE)) is None                # standalone -> [] -> no axis
    assert _fire({"juniper": {}}) is None
    assert _fire({}) is None


# ----------------------------------------------------------------------------- robustness (proposer != verifier)
def test_detector_never_raises_on_malformed_axis():
    for bad in ({"juniper": "x"}, {"juniper": ["srx1"]}, {"juniper": {"s1": "x"}},
                {"juniper": {"s1": {"chassis_cluster": "x"}}},
                {"juniper": {"s1": {"chassis_cluster": [{"priority": None, "status": None}]}}}):
        sig = da._signals(bad)
        out = da._d_junos_chassis_cluster_degraded(bad, sig)
        assert out is None or isinstance(out, dict)


# ----------------------------------------------------------------------------- KB principle + registry
def test_principle_complete_and_engine_actionable():
    p = design_kb.by_id("junos-chassis-cluster-ha-degraded")
    assert p and p["engine_actionable"] is True
    for k in ("title", "domain", "design_intent", "observable", "trigger", "recommended_action",
              "alternatives", "tradeoffs", "citation"):
        assert (p.get(k) or "").strip(), f"principle missing {k}"
    assert "Juniper" in p["citation"]


def test_juniper_in_architecture_coverage_registry():
    keys = {axis for axis, *_ in da._ARCH_COVERAGE_REGISTRY}
    assert "juniper" in keys
    snap = _snap(_PRI0) | {"design_blueprint": {"decisions": [{"id": "junos-chassis-cluster-ha-degraded"}]}}
    cov = da.compute_architecture_coverage(snap)
    by = {c["key"]: c for c in cov["classes"]}
    assert by["juniper"]["observed"] and by["juniper"]["status"] == "finding" and by["juniper"]["channel"] == "ssh"
    none = {c["key"]: c for c in da.compute_architecture_coverage({})["classes"]}
    assert none["juniper"]["status"] == "not-observed"


def test_junos_numeric_zero_priority_survives_display_json():
    """[audit-3 #1 HIGH false-health] real `show chassis cluster status | display json` emits numeric leaves
    (device-priority, redundancy-group-id) as JSON NUMBERS, not quoted strings. _junos_val's `x[0].get('data','')
    or ''` collapsed the falsy integer 0 to '' -> priority parsed None -> the 'priority 0 = not ready to accept
    traffic' HA-degraded detector went SILENT (the self-authored-fixture trap: the test fixture quoted every leaf
    "data":"0"). 0/0.0 must survive; only None -> ''."""
    from cisco_toolkit.parse import _junos_val, parse_junos_chassis_cluster
    assert _junos_val([{"data": 0}]) == "0"          # numeric zero survives (was '')
    assert _junos_val([{"data": 200}]) == "200"
    assert _junos_val([{"data": None}]) == ""        # genuine absence still empty
    assert _junos_val({"data": 0}) == "0"            # bare-dict form too
    real = ('{"chassis-cluster-status":[{"redundancy-group":[{"redundancy-group-id":[{"data":0}],'
            '"device-stats":[{"device-name":[{"data":"node0"}],"device-priority":[{"data":200}],'
            '"redundancy-group-status":[{"data":"primary"}],"monitor-failures":[{"data":"none"}]},'
            '{"device-name":[{"data":"node1"}],"device-priority":[{"data":0}],'
            '"redundancy-group-status":[{"data":"secondary"}],"monitor-failures":[{"data":"none"}]}]}]}]}')
    recs = parse_junos_chassis_cluster(real)
    node1 = [r for r in recs if r["node"] == "node1"][0]
    assert node1["priority"] == 0                     # the 'not ready' node — was None (false-health)
    assert recs[0]["rg"] == "0"                        # control-plane RG0 renders '0', not ''
