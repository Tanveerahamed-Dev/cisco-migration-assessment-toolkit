"""Unit tests for the QoS-audit axis (NEW-V3.23.165):
parse_qos_config (parse layer) + compute_qos_audit (analyze layer) — the configured
QoS posture audit (trust boundary / voice edge / policy attachment / fleet consistency)."""
from cisco_toolkit.analyze import compute_qos_audit
from cisco_toolkit.parse import parse_qos_config


_IOS_MQC = """\
mls qos
class-map match-any VOICE
 match dscp ef
class-map match-all SIGNALING
 match dscp cs3
policy-map ACCESS-IN
 class VOICE
  set dscp ef
policy-map UPLINK-OUT
 class VOICE
  priority
interface GigabitEthernet1/0/2
 switchport access vlan 10
 switchport voice vlan 110
 mls qos trust device cisco-phone
 service-policy input ACCESS-IN
interface GigabitEthernet1/0/3
 switchport access vlan 10
 switchport voice vlan 110
interface GigabitEthernet1/0/24
 switchport mode trunk
 mls qos trust dscp
 service-policy output UPLINK-OUT
"""

_NXOS_QOS = """\
class-map type qos match-all RT-MEDIA
policy-map type qos PM-IN
 class RT-MEDIA
  set qos-group 4
system qos
  service-policy type network-qos NQ-8E
interface Ethernet1/1
 service-policy type qos input PM-IN
"""


def _kinds(qa, host=None):
    return [f["kind"] for f in qa["findings"] if host is None or f["host"] == host]


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #
def test_parse_ios_mqc_config():
    q = parse_qos_config(_IOS_MQC)
    assert q["mls_qos"] is True
    assert q["class_maps"] == ["VOICE", "SIGNALING"]
    assert q["policy_maps"] == ["ACCESS-IN", "UPLINK-OUT"]
    ifs = q["interfaces"]
    # interface names are normalized to the short canonical form (Gi1/0/2)
    phone = ifs["Gi1/0/2"]
    assert phone["voice_vlan"] == "110"
    assert phone["trust"] == "device cisco-phone"
    assert phone["policy_in"] == "ACCESS-IN"
    naked = ifs["Gi1/0/3"]
    assert naked["voice_vlan"] == "110" and naked["trust"] is None
    uplink = ifs["Gi1/0/24"]
    assert uplink["trust"] == "dscp" and uplink["policy_out"] == "UPLINK-OUT"


def test_parse_nxos_types_and_global_attach():
    q = parse_qos_config(_NXOS_QOS)
    assert q["class_maps"] == ["RT-MEDIA"] and q["policy_maps"] == ["PM-IN"]
    assert q["global_attach"] == ["NQ-8E"]          # system qos attachment counts as in-use
    assert q["interfaces"]["Eth1/1"]["policy_in"] == "PM-IN"
    assert q["mls_qos"] is False


def test_parse_empty_and_qos_free_config():
    assert parse_qos_config("") == {"mls_qos": False, "class_maps": [], "policy_maps": [],
                                    "interfaces": {}, "global_attach": [], "child_policies": []}
    assert parse_qos_config(None)["interfaces"] == {}
    q = parse_qos_config("hostname sw1\ninterface Gi1/0/1\n ip address 10.0.0.1 255.255.255.0\n")
    assert q["interfaces"] == {}                    # non-QoS interfaces are not listed


# --------------------------------------------------------------------------- #
# doctrine findings
# --------------------------------------------------------------------------- #
def test_voice_without_qos_flags_only_the_naked_port():
    qa = compute_qos_audit({"sw1": _IOS_MQC})
    voice = [f for f in qa["findings"] if f["kind"] == "voice-without-qos"]
    assert len(voice) == 1 and voice[0]["severity"] == "High"
    assert "Gi1/0/3" in voice[0]["detail"]
    assert "Gi1/0/2" not in voice[0]["detail"]      # the trusted phone port is fine
    # the trust boundary exists here, so no no-trust-boundary finding
    assert "no-trust-boundary" not in _kinds(qa)


def test_no_trust_boundary_the_mls_qos_foot_gun():
    cfg = "mls qos\ninterface Gi1/0/1\n switchport access vlan 10\n"
    qa = compute_qos_audit({"sw1": cfg})
    kinds = _kinds(qa, "sw1")
    assert "no-trust-boundary" in kinds
    d = {f["kind"]: f for f in qa["findings"]}
    assert d["no-trust-boundary"]["severity"] == "High"
    by_host = {p["host"]: p for p in qa["per_device"]}
    assert by_host["sw1"]["mode"] == "mls qos"


def test_inert_and_dangling_policy():
    inert = "policy-map LONELY\n class class-default\n"
    qa = compute_qos_audit({"sw1": inert})
    assert "inert-policy" in _kinds(qa, "sw1")
    dangling = "interface Gi1/0/1\n service-policy input GHOST\n"
    qa2 = compute_qos_audit({"sw1": dangling})
    assert "undefined-policy-ref" in _kinds(qa2, "sw1")
    assert "inert-policy" not in _kinds(qa2, "sw1")   # an attachment exists (to GHOST)


def test_hierarchical_child_policy_is_not_an_attachment():
    # V3.23.170: 'policy-map PARENT / class X / service-policy CHILD' is a definition-time
    # reference; a paper-only HQoS pair must still raise inert-policy.
    hqos = """\
policy-map CHILD
 class class-default
  priority
policy-map PARENT
 class class-default
  shape average 100000000
  service-policy CHILD
"""
    q = parse_qos_config(hqos)
    assert q["global_attach"] == [] and q["child_policies"] == ["CHILD"]
    qa = compute_qos_audit({"sw1": hqos})
    assert "inert-policy" in _kinds(qa, "sw1")
    # a real system-target attachment still suppresses it
    attached = hqos + "system qos\n  service-policy type queuing PARENT\n"
    assert "inert-policy" not in _kinds(compute_qos_audit({"sw1": attached}), "sw1")


def test_nxos_system_default_policies_not_dangling():
    # V3.23.170: default-nq-*/copp-system-* are defined only in 'show running-config all'.
    cfg = ("system qos\n  service-policy type network-qos default-nq-3e-policy\n"
           "control-plane\n service-policy input copp-system-p-policy-strict\n")
    qa = compute_qos_audit({"nx1": cfg})
    assert "undefined-policy-ref" not in _kinds(qa, "nx1")


def test_objects_only_mode_is_not_counted_as_none_or_active():
    # V3.23.170: class-maps-only config (Nexus default class-fcoe maps, leftover debris)
    qa = compute_qos_audit({"sw1": "class-map match-any FOO\n"})
    d = qa["per_device"][0]
    assert d["mode"] == "objects-only" and "best-effort" in d["posture"]
    fleet = [f for f in qa["findings"] if f["host"] == "(fleet)"]
    assert len(fleet) == 1 and fleet[0]["kind"] == "best-effort-fleet"
    assert "active QoS" in fleet[0]["detail"]          # truthful wording
    # objects-only sits on the WITHOUT side of mixed-posture
    qa2 = compute_qos_audit({"sw1": "class-map match-any FOO\n", "sw2": _IOS_MQC})
    mixed = next(f for f in qa2["findings"] if f["kind"] == "mixed-posture")
    assert "sw1" in mixed["detail"].split("while")[1]


def test_fleet_mixed_posture_and_best_effort():
    qa = compute_qos_audit({"sw1": _IOS_MQC, "sw2": "hostname sw2\n"})
    fleet = [f for f in qa["findings"] if f["host"] == "(fleet)"]
    assert len(fleet) == 1 and fleet[0]["kind"] == "mixed-posture"
    qa2 = compute_qos_audit({"sw1": "hostname sw1\n", "sw2": "hostname sw2\n"})
    fleet2 = [f for f in qa2["findings"] if f["host"] == "(fleet)"]
    assert len(fleet2) == 1 and fleet2[0]["kind"] == "best-effort-fleet"
    assert fleet2[0]["severity"] == "Low"
    assert qa2["summary"]["modes"] == {"none": 2}


# --------------------------------------------------------------------------- #
# honesty & shapes
# --------------------------------------------------------------------------- #
def test_not_assessable_declared_never_scored():
    qa = compute_qos_audit({"sw1": _IOS_MQC}, all_hosts=["sw1", "sw2", "sw3"])
    s = qa["summary"]
    assert s["n_devices"] == 3 and s["n_assessable"] == 1 and s["n_not_assessable"] == 2
    assert s["hosts_not_assessable"] == ["sw2", "sw3"]
    by_host = {p["host"]: p for p in qa["per_device"]}
    assert by_host["sw2"]["assessable"] is False
    assert not _kinds(qa, "sw2")                     # nothing scored against silence
    # an unassessable majority must not create a mixed-posture fleet finding
    assert "mixed-posture" not in _kinds(qa)


def test_findings_sorted_high_first_and_summary_counts():
    qa = compute_qos_audit({"sw1": _IOS_MQC, "sw2": "hostname sw2\n"})
    sevs = [f["severity"] for f in qa["findings"]]
    assert sevs == sorted(sevs, key={"High": 0, "Medium": 1, "Low": 2}.get)
    s = qa["summary"]
    assert s["n_findings"] == len(qa["findings"])
    assert s["n_voice_ports"] == 2                   # both voice ports counted, naked or not
    assert sum(s["by_kind"].values()) == s["n_findings"]


def test_empty_input_shapes():
    qa = compute_qos_audit({})
    assert qa["per_device"] == [] and qa["findings"] == []
    assert qa["summary"]["n_devices"] == 0
    assert compute_qos_audit(None)["summary"]["n_assessable"] == 0
    assert qa["note"]
