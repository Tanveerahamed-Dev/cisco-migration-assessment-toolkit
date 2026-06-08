"""NEW-V3.23.126: compute_flow_paths — representative end-to-end flows (the workbook/runbook twin of the
explorer's Flow Simulator). The FLOW SELECTION (one lowest-IP rep per VLAN, consecutive-VLAN pairs) is
deterministic; trace_full_flow's hop tie-break is topology-dependent, so we mock it here."""
import cisco_toolkit.analyze as az


def _ident():
    return [
        {"ip": "10.0.10.5", "vlan": "10", "host": "A", "endpoint_class": "Workstation"},
        {"ip": "10.0.10.2", "vlan": "10", "host": "A", "endpoint_class": "Workstation"},  # lower IP -> rep
        {"ip": "10.0.20.9", "vlan": "20", "host": "B", "endpoint_class": "VoIP-Phone"},
        {"ip": "10.0.30.3", "vlan": "30", "host": "C", "endpoint_class": "Server"},
        {"ip": "", "vlan": "40", "host": "D", "endpoint_class": "Server"},                # no IP -> skipped
    ]


def _mock_trace(calls):
    def _t(sip, dip, _ai):
        calls.append((sip, dip))
        return {"summary": {"src_ip": sip, "dst_ip": dip, "flow_type": "L3 (routed)",
                            "risk": "MEDIUM", "spof_count": 1, "spofs": ["uplink:A:Gi1/0/24"],
                            "partitioned": False},
                "hops": [{"n": 1, "layer": "L1/L2", "from": sip, "to": "A",
                          "iface": "x", "detail": "d", "spof": False}]}
    return _t


def test_selects_lowest_ip_rep_and_consecutive_pairs(monkeypatch):
    calls = []
    monkeypatch.setattr(az, "trace_full_flow", _mock_trace(calls))
    out = az.compute_flow_paths({}, _ident())
    # VLAN 10->20, 20->30 = 2 flows; VLAN 40 has no IP -> excluded
    assert out["summary"]["n_flows"] == 2
    assert calls == [("10.0.10.2", "10.0.20.9"), ("10.0.20.9", "10.0.30.3")]   # lowest-IP rep of VLAN 10
    assert out["flows"][0]["label"] == "VLAN 10 (Workstation) → VLAN 20 (VoIP-Phone)"
    assert out["flows"][1]["label"] == "VLAN 20 (VoIP-Phone) → VLAN 30 (Server)"


def test_risk_and_partition_rollup(monkeypatch):
    def _t(sip, dip, _ai):
        return {"summary": {"risk": "HIGH" if dip.endswith(".3") else "LOW",
                            "flow_type": "L3 (routed)",
                            "partitioned": dip.endswith(".3"), "spofs": []},
                "hops": []}
    monkeypatch.setattr(az, "trace_full_flow", _t)
    out = az.compute_flow_paths({}, _ident())
    assert out["summary"]["n_at_risk"] == 1        # only the ->.3 (VLAN 30) flow is HIGH
    assert out["summary"]["n_partitioned"] == 1


def test_empty_identity_yields_no_flows(monkeypatch):
    monkeypatch.setattr(az, "trace_full_flow", _mock_trace([]))
    out = az.compute_flow_paths({}, [])
    assert out["flows"] == [] and out["summary"]["n_flows"] == 0
    assert out["summary"]["n_at_risk"] == 0
