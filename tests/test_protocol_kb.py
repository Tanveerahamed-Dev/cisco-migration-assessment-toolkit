"""NEW-V3.23.100: the protocol expected-vs-abnormal-state doctrine and the advisory join.
Observed protocol states are facts; the cause/remediation are Inferred per Cisco doctrine."""
from cisco_toolkit import protocol_kb
from cisco_toolkit.analyze import _extract_protocol_states, compute_protocol_intelligence


def test_doctrine_lookups():
    # OSPF EXSTART -> MTU mismatch is the headline diagnosis; composite state token is normalized
    adv = protocol_kb.advise("OSPF", "EXSTART/DROTHER")
    assert adv["severity"] == "High" and "MTU" in adv["likely_cause"]
    # EtherChannel flags are case-sensitive (s suspended vs I standalone vs D down)
    assert "suspended" in protocol_kb.advise("EtherChannel", "s")["meaning"]
    assert "stand-alone" in protocol_kb.advise("EtherChannel", "I")["meaning"]
    # BGP Active = stuck at TCP/179
    assert "179" in protocol_kb.advise("BGP", "Active")["likely_cause"]
    # VTP high-revision overwrite doctrine
    assert "overwrite" in protocol_kb.advise("VTP", "HIGH-REVISION")["likely_cause"]
    # healthy / unknown -> no advisory
    assert protocol_kb.advise("OSPF", "FULL/BDR") is None
    assert protocol_kb.advise("OSPF", "FULL") is None
    assert protocol_kb.advise("BGP", "12345") is None      # established peer (numeric prefix count)
    assert protocol_kb.advise("", "") is None


def test_extract_states_from_protocol_health_rows():
    assert _extract_protocol_states("EtherChannel", "", "Gi1/0/1(s); Gi1/0/2(I)") == ["I", "s"]
    assert _extract_protocol_states("OSPF", "", "10.0.0.1 EXSTART; 10.0.0.2 INIT") == ["EXSTART", "INIT"]
    assert _extract_protocol_states("BGP", "", "1.2.3.4 Active; 5.6.7.8 Idle (Admin)") == ["Active", "Idle"]
    # VTP only fires for a server with a high revision
    assert _extract_protocol_states("VTP", "mode server; domain X; rev 150", "") == ["HIGH-REVISION"]
    assert _extract_protocol_states("VTP", "mode transparent; domain X; rev 5", "") == []
    assert _extract_protocol_states("VTP", "mode server; domain X; rev 3", "") == []
    # STP only when there are inconsistent ports
    assert _extract_protocol_states("STP", "mode rstp; 2 blocked, 1 inconsistent", "") == ["INCONSISTENT"]
    assert _extract_protocol_states("STP", "mode rstp; 0 blocked, 0 inconsistent", "") == []


def test_compute_protocol_intelligence_join_and_sort():
    ph = [
        {"switch": "acc2", "protocol": "VTP", "severity": "Info",
         "summary": "mode transparent; domain X; rev 0", "detail": ""},          # healthy -> no advisory
        {"switch": "acc1", "protocol": "EtherChannel", "severity": "High",
         "summary": "1 bundle(s), 2 member(s); 2 not bundled", "detail": "Gi1/0/1(s); Gi1/0/2(I)"},
        {"switch": "core1", "protocol": "OSPF", "severity": "Info",
         "summary": "3 neighbor(s); 0 not Full/2Way", "detail": ""},             # healthy -> no advisory
    ]
    out = compute_protocol_intelligence(ph)
    # two EtherChannel advisories, both High; healthy rows produced nothing
    assert len(out) == 2
    assert {r["state"] for r in out} == {"s", "I"}
    assert all(r["switch"] == "acc1" and r["severity"] == "High" for r in out)
    assert all("Inferred" in r["confidence"] for r in out)
    assert compute_protocol_intelligence([]) == []
