"""Cisco ISE (Identity Services Engine) deployment health -- the JSON controller-REST channel (additive over
the SSH show-text channel, mirroring the Cisco ACI / Catalyst SD-WAN ingestion). ISE is a CONTROLLER cluster,
not a CLI-`show` device, so its deployment state arrives as a read-only northbound REST export (Open API
`GET /api/v1/deployment/node`). Covers parse_ise_nodes, build_ise, the _signals ISE extraction, and the three
detectors. The contract is the universal coverage-honesty doctrine, with the three corrections an adversarial
verification pass raised against the field shapes:
  * the Open API LIST response is WRAPPED ({"response":[...], "version":...}); the parser must unwrap it
    (a bare-array assumption silently parses zero nodes);
  * nodeStatus is a node-REACHABILITY signal (Connected = healthy), NOT a replication verdict -- transient
    in-progress / registering states are excluded so a node mid-sync never cry-wolfs;
  * the redundancy detectors must NOT fire on a Cisco-supported STANDALONE deployment (one node carrying all
    personas is by definition single-PSN/PAN/MnT) -- they arm only when the deployment has >=2 nodes.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from cisco_toolkit import parse  # noqa: E402
import cisco_toolkit.design_advisor as da  # noqa: E402


def _resp(nodes):
    """Wrap node rows the way the ISE Open API list call does: {"response":[...], "version":"1.0.0"}."""
    return json.dumps({"response": nodes, "version": "1.0.0"})


def _node(host, roles, services, status="Connected"):
    return {"hostname": host, "fqdn": f"{host}.example.com", "roles": roles, "services": services,
            "nodeStatus": status}


# A healthy, fully-redundant 2-node deployment: both nodes PSN (Session), Secondary Admin + Monitoring
# present, all Connected -> every detector silent.
_HEALTHY = _resp([
    _node("ise-pan-1", ["PrimaryAdmin", "PrimaryMonitoring"], ["Session", "Profiler"]),
    _node("ise-pan-2", ["SecondaryAdmin", "SecondaryMonitoring"], ["Session", "Profiler"]),
])
# A node not reachable to the PAN (nodeStatus != Connected) -> node-not-connected fires (the rest stay clean).
_NODE_DOWN = _resp([
    _node("ise-pan-1", ["PrimaryAdmin", "PrimaryMonitoring"], ["Session"]),
    _node("ise-pan-2", ["SecondaryAdmin", "SecondaryMonitoring"], ["Session"]),
    _node("ise-psn-3", [], ["Session"], status="Disconnected"),
])
# A node mid-sync (transient) -> NOT a finding (cry-wolf exclusion).
_TRANSIENT = _resp([
    _node("ise-pan-1", ["PrimaryAdmin", "PrimaryMonitoring"], ["Session"]),
    _node("ise-pan-2", ["SecondaryAdmin", "SecondaryMonitoring"], ["Session"], status="In Progress"),
])
# Exactly ONE PSN in a multi-node deployment -> single-PSN fires (auth SPOF); admin/mnt redundant -> silent.
_SINGLE_PSN = _resp([
    _node("ise-pan-1", ["PrimaryAdmin", "PrimaryMonitoring"], ["Session"]),
    _node("ise-pan-2", ["SecondaryAdmin", "SecondaryMonitoring"], ["Profiler"]),
])
# Two PSNs but NO SecondaryAdmin -> admin/monitoring-redundancy fires (single PAN); psn redundant -> silent.
_SINGLE_PAN = _resp([
    _node("ise-pan-1", ["PrimaryAdmin", "PrimaryMonitoring"], ["Session"]),
    _node("ise-psn-2", ["SecondaryMonitoring"], ["Session"]),
])
# STANDALONE: one node carrying all personas -- a Cisco-supported topology, NOT a redundancy defect.
_STANDALONE = _resp([
    _node("ise", ["PrimaryAdmin", "PrimaryMonitoring"], ["Session", "Profiler", "DeviceAdmin"]),
])


def _snap(text, host="ise-pan-1"):
    return {"ise": {host: {"nodes": parse.parse_ise_nodes(text)}}}


# ============================================================ parser
def test_parse_ise_unwraps_response_list():
    nodes = parse.parse_ise_nodes(_HEALTHY)
    assert len(nodes) == 2
    n = [x for x in nodes if x["hostname"] == "ise-pan-1"][0]
    assert n["node_status"] == "Connected"
    assert "PrimaryAdmin" in n["roles"] and "Session" in n["services"]


def test_parse_ise_unwraps_single_node_dict():
    # the single-node call wraps ONE dict, not a list
    one = json.dumps({"response": {"hostname": "ise", "fqdn": "ise.x", "roles": ["PrimaryAdmin"],
                                   "services": ["Session"], "nodeStatus": "Connected"}, "version": "1.0.0"})
    nodes = parse.parse_ise_nodes(one)
    assert len(nodes) == 1 and nodes[0]["hostname"] == "ise"


def test_parse_ise_bare_array_is_not_assumed():
    # a bare top-level array is NOT the documented shape -> parser unwraps 'response', so a bare array yields
    # nothing rather than mis-parsing (coverage-honest: no fabricated nodes)
    assert parse.parse_ise_nodes(json.dumps([{"hostname": "x"}])) == []


def test_parse_ise_tolerates_hostile_input():
    for bad in ["", "   ", "not json", "{", "null", "12345", '{"response": null}',
                '{"response": "x"}', '{"response": [null, 1, "x", {}]}', '{"version": "1.0"}']:
        assert isinstance(parse.parse_ise_nodes(bad), list)


def test_parse_ise_tolerates_non_string_input():
    for bad in (None, 123, 3.14, True, b"{}", ["x"], {"a": 1}):
        assert parse.parse_ise_nodes(bad) == []


# ============================================================ detector: node-not-connected
def test_node_not_connected_fires_on_disconnected():
    snap = _snap(_NODE_DOWN)
    d = da._d_ise_node_unreachable(snap, da._signals(snap))
    assert d is not None and d["id"] == "ise-deployment-node-unreachable"


def test_node_not_connected_silent_on_all_connected():
    snap = _snap(_HEALTHY)
    assert da._d_ise_node_unreachable(snap, da._signals(snap)) is None


def test_node_not_connected_silent_on_transient_state():
    # a node 'In Progress' (mid-sync) must NOT cry wolf
    snap = _snap(_TRANSIENT)
    assert da._d_ise_node_unreachable(snap, da._signals(snap)) is None


# ============================================================ detector: single PSN
def test_single_psn_fires_in_multinode_deployment():
    snap = _snap(_SINGLE_PSN)
    d = da._d_ise_psn_no_redundancy(snap, da._signals(snap))
    assert d is not None and d["id"] == "ise-policy-service-node-redundancy"


def test_single_psn_silent_with_two_psns():
    snap = _snap(_HEALTHY)
    assert da._d_ise_psn_no_redundancy(snap, da._signals(snap)) is None


# ============================================================ detector: admin/monitoring redundancy
def test_admin_redundancy_fires_on_missing_secondary_admin():
    snap = _snap(_SINGLE_PAN)
    d = da._d_ise_admin_monitoring_redundancy(snap, da._signals(snap))
    assert d is not None and d["id"] == "ise-admin-monitoring-redundancy"


def test_admin_redundancy_silent_when_secondaries_present():
    snap = _snap(_HEALTHY)
    assert da._d_ise_admin_monitoring_redundancy(snap, da._signals(snap)) is None


# ============================================================ STANDALONE cry-wolf mitigation (critical)
def test_standalone_deployment_fires_nothing():
    """A Cisco-supported single-node standalone ISE is by definition single-PSN/PAN/MnT -- the redundancy
    detectors must NOT cry wolf on it (they arm only at >=2 nodes), and an all-Connected node is not down."""
    snap = _snap(_STANDALONE)
    sig = da._signals(snap)
    assert da._d_ise_node_unreachable(snap, sig) is None
    assert da._d_ise_psn_no_redundancy(snap, sig) is None
    assert da._d_ise_admin_monitoring_redundancy(snap, sig) is None


# ============================================================ coverage honesty
def test_all_ise_detectors_silent_when_no_ise_axis():
    sig = da._signals({})
    assert da._d_ise_node_unreachable({}, sig) is None
    assert da._d_ise_psn_no_redundancy({}, sig) is None
    assert da._d_ise_admin_monitoring_redundancy({}, sig) is None


def test_ise_in_architecture_coverage_registry():
    keys = {axis for axis, *_ in da._ARCH_COVERAGE_REGISTRY}
    assert "ise" in keys
    cov = da.compute_architecture_coverage(_snap(_NODE_DOWN) | {
        "design_blueprint": {"decisions": [{"id": "ise-deployment-node-unreachable"}]}})
    ise = [c for c in cov["classes"] if c["key"] == "ise"][0]
    assert ise["observed"] is True and ise["status"] == "finding" and ise["channel"] == "json"


# ============================================================ build
def test_build_ise_reads_nodes(tmp_path):
    from cisco_toolkit import build
    p = tmp_path / "api_v1_deployment_node.txt"
    p.write_text(_NODE_DOWN, encoding="utf-8")
    ise = build.build_ise({"api/v1/deployment/node": str(p)})
    assert any(n["node_status"] == "Disconnected" for n in ise["nodes"])


def test_build_ise_empty_when_absent():
    from cisco_toolkit import build
    assert build.build_ise({}) == {}


# ============================================================ robustness (malformed axis; never raises)
def test_ise_detectors_survive_malformed_axis():
    for snap in [{"ise": None}, {"ise": "x"}, {"ise": {"h": None}}, {"ise": {"h": {"nodes": "x"}}},
                 {"ise": {"h": {"nodes": [None, 1, {"roles": "x", "services": None, "node_status": None}]}}}]:
        sig = da._signals(snap)
        for det in (da._d_ise_node_unreachable, da._d_ise_psn_no_redundancy, da._d_ise_admin_monitoring_redundancy):
            assert det(snap, sig) is None or isinstance(det(snap, sig), dict)


# ============================================================ read-only collector
def test_collect_ise_is_https_only_and_password_safe(monkeypatch, tmp_path):
    from cisco_toolkit import rest_collect
    # refuses non-HTTPS (would leak Basic-auth credentials in cleartext)
    assert rest_collect.collect_ise("http://ise", "u", "p", str(tmp_path / "a")) == []
    # https + a node export written; the password must never land in the export file
    monkeypatch.setattr(rest_collect, "_get_json", lambda *a, **k: {"response": [{"hostname": "ise"}], "version": "1.0"})
    secret = "ISE-SECRET-PW-123"
    files = rest_collect.collect_ise("https://ise", "admin", secret, str(tmp_path / "ise"))
    assert len(files) == 1
    assert secret not in open(files[0], encoding="utf-8").read()
