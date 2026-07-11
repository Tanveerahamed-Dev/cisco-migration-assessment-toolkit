"""NEW-V3.23.93: the Assessment & Migration Runbook (DOCX) deliverable. python-docx is optional, so
the whole module is skipped when it is not installed (the generator itself fails soft the same way)."""
import pytest

docx = pytest.importorskip("docx")  # skip the file if the optional dep is absent
from docx import Document  # noqa: E402

from cisco_toolkit.runbook import write_runbook_docx  # noqa: E402


def _snap():
    """A minimal but representative snapshot exercising every section the generator builds."""
    return {
        "script_version": "V3.23.0",
        "devices": {
            "sw1": {"hostname": "sw1", "model": "C9300", "sw_version": "17.9", "platform": "ios",
                    "ps_status": "ok", "fan_status": "ok", "temperature_status": "ok",
                    "total_ports": 48, "active_ports": 10},
            "sw2": {"hostname": "sw2", "model": "N9K-C93180", "ps_status": "fail", "fan_status": "ok",
                    "temperature_status": "ok", "total_ports": 48, "active_ports": 5},
        },
        "interfaces": {
            "sw1": {"Gi1/0/1": {"switchport_mode": "Access", "vlan": "10", "end_host_mac": "aaaa.0000.0001"},
                    "Gi1/0/2": {"switchport_mode": "Access", "vlan": "10", "end_host_mac": "aaaa.0000.0002"},
                    "Te1/1": {"switchport_mode": "Trunk", "end_host_mac": "cccc.0000.0001"}},  # trunk excluded
            "sw2": {"Gi1/0/1": {"switchport_mode": "Access", "vlan": "20", "end_host_mac": "bbbb.0000.0001"}},
        },
        "health_scores": [{"switch": "sw1", "score": 50, "band": "Poor"},
                          {"switch": "sw2", "score": 10, "band": "Critical"}],
        "move_groups": [{"switches": ["sw1"], "endpoints": 2}, {"switches": ["sw2"], "endpoints": 1}],
        "migration_readiness": [{"group": "Group 1", "switches": ["sw1"], "endpoints": 2,
                                 "readiness": "NOT READY", "n_fail": 1, "n_warn": 0, "checks": []}],
        "wave_sequencing": [{"group": "Group 1", "make_before_break": ["sw1"], "hard_cutover": [],
                             "hard_cutover_endpoints": 0, "sequence": "make-before-break"}],
        "cross_layer": [{"id": "CL-01", "severity": "Critical", "layers": "L1+L3",
                         "title": "VLAN 10: single-fiber uplink to a sole gateway",
                         "detail": "single fiber fronts the sole gateway", "recommendation": "add redundancy",
                         "hosts": ["sw1"]}],
        "punchlist": [{"severity": "Critical", "category": "Cross-layer", "devices": ["sw1"],
                       "title": "x", "detail": "y"}],
        "failure_impact": [{"host": "sw1", "severity": "High", "vlans_impacted": 3, "stranded": 5,
                            "hard": 2, "backup": 1, "fhrp": 0, "detail": "..."}],
        "link_centrality": [{"a_host": "sw1", "a_port": "Te1/1", "b_host": "sw2", "b_port": "Te1/1",
                             "betweenness": 1.0, "is_bridge": True, "pairs_cut": 4, "rank": 1}],
        "l3_forwarding": [{"switch": "sw1", "vlan": "10", "svi_ip": "10.0.10.1", "fhrp": "",
                           "role": "", "risk": "single-gateway"}],
        "capacity": [{"hostname": "sw1", "model": "C9300", "total_ports": 48, "active_ports": 10,
                      "free_ports": 38, "port_util": 20.8}],
        "operational_drift": [{"severity": "High", "category": "False-health", "devices": ["sw1"],
                               "title": "Temporary L2 bridge on sw1",
                               "detail": "a temp bridge enlarges the STP domain", "remediation": "remove it"}],
        "endpoint_identity": [
            {"host": "sw1", "port": "Gi1/0/1", "vlan": "10", "ip": "", "mac": "00:50:56:aa:00:01",
             "mac_count": 1, "vendor": "VMware, Inc.", "endpoint_class": "VM / Hypervisor",
             "confidence": "Inferred-high", "evidence": "vendor 'VMware, Inc.'"},
            {"host": "sw1", "port": "Gi1/0/2", "vlan": "20", "ip": "", "mac": "00:c0:b7:00:00:01",
             "mac_count": 1, "vendor": "APC", "endpoint_class": "UPS/PDU",
             "confidence": "Inferred-high", "evidence": "vendor 'APC'"},
        ],
        "endpoint_dependencies": {
            "clusters": [{"vendor": "VMware, Inc.", "endpoint_class": "VM / Hypervisor", "count": 12,
                          "switches": 4, "vlans": 2, "move_groups": 1, "spans_groups": False}],
            "dual_homed": [{"mac": "bb:00:00:00:00:01", "ip": "10.0.0.5", "vendor": "NetApp",
                            "endpoint_class": "Storage", "switches": ["sw1", "sw2"], "ports": [],
                            "move_groups": ["Group 1"], "split_across_groups": False}],
            "shared_ip": [],
            "affinity": [{"vlan": "10", "total": 12, "classes": {"VM / Hypervisor": 12}, "dominant": "VM / Hypervisor"}],
            "per_switch_validation": {"sw1": ["Storage: datastore/LUN reachable AND the cluster peer is up"]},
        },
        "subnet_intelligence": {
            "per_device": [
                {"host": "sw1", "is_l3": True, "destination_subnets": ["10.0.10.0/24"],
                 "destination_count": 1, "reachable_count": 2, "reachable_sources": {"ospf": 2},
                 "reachable_sample": [], "default_next_hop": "10.0.0.1", "served_subnets": [],
                 "bgp_received_count": 0},
                {"host": "sw2", "is_l3": False, "destination_subnets": [], "destination_count": 0,
                 "reachable_count": 0, "reachable_sources": {}, "reachable_sample": [],
                 "default_next_hop": "", "served_subnets": [{"subnet": "10.0.10.0/24", "gateway": "sw1", "vlan": "10"}],
                 "bgp_received_count": 0},
            ],
            "move_groups": [{"group": "Group 1", "switches": 2, "local_subnets": ["10.0.10.0/24"],
                             "local_count": 1, "remote_count": 3}],
            "bgp_received_collected": False,
        },
        "migration_scenarios": {
            "per_group": [{"group": "Group 1", "switches": 5, "endpoints": 50, "readiness": "READY",
                           "make_before_break": 4, "hard_cutover": 1, "hard_cutover_endpoints": 2,
                           "dual_homed_pct": 80, "recommended_scenario": "parallel-run",
                           "rationale": "mostly dual-homed — build beside and cut leg-by-leg",
                           "playbook": {"pre": "build beside", "validate": "cut one leg, prove forwarding",
                                        "rollback": "fail back to legacy leg"}}],
            "fleet_recommendation": "89% of switches are Poor/Critical — consider a GREENFIELD rebuild.",
            "scenario_counts": {"parallel-run": 1},
        },
        "collection_completeness": {
            "summary": {"inventory": 3, "complete": 1, "partial": 1, "not_collected": 1},
            "devices": [
                {"host": "sw3-unreachable", "status": "not collected", "data_quality": 0,
                 "missing": ["interface status", "switchport", "version/inventory", "CDP/LLDP neighbors"]},
                {"host": "sw2", "status": "partial", "data_quality": 75, "missing": ["CDP/LLDP neighbors"]},
            ],
        },
        "protocol_intelligence": [
            {"switch": "sw1", "protocol": "EtherChannel", "state": "I", "severity": "High",
             "meaning": "Member is stand-alone (individual) — NOT bundled.",
             "likely_cause": "Incompatible port settings vs the bundle, or no LACP partner.",
             "remediation": "Make the member config identical to the bundle and verify LACP on the peer.",
             "confidence": "observed state = fact; likely cause = Inferred (Cisco doctrine)"},
        ],
        "service_map": {
            "services": [
                {"port": 319, "proto": "udp", "service": "PTP-event", "category": "Broadcast-AV",
                 "broadcast": True, "refs": 2, "host_count": 1,
                 "evidence_class": "Inferred (ACL design intent -- not active traffic; no flow telemetry)"},
            ],
            "categories": [{"category": "Broadcast-AV", "refs": 2}],
            "acl_rule_count": 12,
            "multicast": {"active_interfaces": 4, "active_switch_count": 2,
                          "active_switches": ["sw1", "sw2"],
                          "classified_groups": [{"group": "224.0.1.129", "name": "PTP-primary",
                                                 "category": "Broadcast-AV", "broadcast": True, "source": "IGMP/mroute"}],
                          "group_level_collected": True,
                          "ptp": {"sw1": {"device_type": "Unknown", "num_ports": 0, "grandmaster": "", "operational": False}},
                          "igmp_queriers": [{"switch": "sw1", "vlan": "10", "querier": "10.0.10.1"}]},
        },
    }


def test_runbook_has_12_sections_and_reconciles(tmp_path):
    out = str(tmp_path / "rb.docx")
    write_runbook_docx(out, _snap(), "Unit Test Fleet")
    d = Document(out)
    h1 = [p.text for p in d.paragraphs if p.style.name == "Heading 1"]
    # the 12 standard sections (plus a Contents heading)
    for n in range(1, 13):
        assert any(t.startswith(f"{n}.") for t in h1), f"missing section {n}: {h1}"

    # numbers reconcile to the snapshot (the workbook-vs-runbook agreement contract).
    # Locate the §1 metric table by its header — the document-control front matter
    # (V3.23.150) inserts tables before it, so index 0 is no longer the exec summary.
    exec_t = next((t for t in d.tables if t.rows[0].cells[0].text == "Metric"), None)
    assert exec_t is not None, "exec-summary Metric table not found in the runbook"
    exec_rows = {r.cells[0].text: r.cells[1].text for r in exec_t.rows}
    assert exec_rows["Devices in scope"] == "2"
    assert exec_rows["Migration move groups"] == "2"
    assert exec_rows["Punch-list items"] == "1"
    assert exec_rows["Endpoints — access-port host MACs at snapshot (superset of canonical)"] == "3"   # trunk MAC excluded
    assert "Evidenced endpoints (canonical assessment scale)" in exec_rows   # SSOT-endpoint-deliv-1: canonical headline present


def _all_text(doc):
    """All visible text — paragraphs AND table cells (findings live in both)."""
    parts = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for row in t.rows:
            parts.extend(c.text for c in row.cells)
    return "\n".join(parts)


def test_runbook_scope_distinguishes_collected_from_inventory(tmp_path):
    """Coverage-honesty: §2 Scope must NOT call the device INVENTORY total 'the collected dataset' — it
    states how many of the inventoried switches were actually collected (collection_completeness.complete)."""
    snap = _snap()
    snap["collection_completeness"] = {"summary": {"complete": 2, "inventory": 9}}
    out = str(tmp_path / "rb_scope.docx")
    write_runbook_docx(out, snap, "Unit Test Fleet")
    text = _all_text(Document(out))
    assert "present in the collected dataset" not in text   # the inventory-mislabeled-as-collected wording is gone
    assert "inventoried" in text                            # the honest inventoried/collected framing


def test_runbook_renders_device_risk_register_section(tmp_path):
    """NEW-V3.23.174: a snapshot carrying the Device Risk Register renders §10.1 with the
    ranked table + compound bullets; without the key the section is absent (data-gated)."""
    snap = _snap()
    out = str(tmp_path / "rb_no_register.docx")
    write_runbook_docx(out, snap, "Unit Test Fleet")
    assert "10.1 Per-asset compound risk" not in _all_text(Document(out))

    snap["device_dossiers"] = {
        "per_device": [
            {"host": "sw2", "risk_band": "Severe", "risk_index": 60, "impact_score": 10,
             "exposure_score": 6,
             "compound": [{"code": "CR-02", "title": "Failing hardware past support",
                           "severity": "High", "basis": "Critical health on EoL hardware."}],
             "verdict": "Stabilize or replace before migration — health Critical."}],
        "summary": {"n_devices": 1, "bands": {"Severe": 1, "Elevated": 0, "Guarded": 0, "Low": 0},
                    "n_compound": 1, "worst": ["sw2"]}}
    out2 = str(tmp_path / "rb_register.docx")
    write_runbook_docx(out2, snap, "Unit Test Fleet")
    text = _all_text(Document(out2))
    assert "10.1 Per-asset compound risk" in text
    assert "CR-02" in text and "Stabilize or replace" in text
    assert "not assessed" in text          # the honesty rule is stated in the section intro


def test_runbook_is_evidence_disciplined(tmp_path):
    out = str(tmp_path / "rb.docx")
    write_runbook_docx(out, _snap(), "Unit Test Fleet")
    text = _all_text(Document(out))
    # every material finding carries the evidence frame
    for token in ("Observed Evidence:", "Interpretation:", "Impact / Blast Radius:",
                  "Confidence:", "Unknowns:", "Next Validation:"):
        assert token in text, token
    # false-health doctrine + confidence vocabulary are present
    assert "gateway-active is not service proof" in text
    # §6.5 protocol behaviour: the abnormal state's cause + remediation are present, evidence-framed
    assert "Protocol behaviour & remediation" in text
    assert "verify LACP on the peer" in text
    # §2.1 collection completeness: blind-spot devices are made explicit (not-collected listed)
    assert "Collection completeness" in text
    assert "sw3-unreachable" in text and "a missing device is not a healthy device" in text
    # §6.6 services & multicast: design-intent caveat + multicast forwarding presence
    assert "Services & multicast" in text
    assert "PTP-event" in text and "run PIM/mroute" in text
    # PTP operational-state finding: dormant (not boundary-clocked) is surfaced, not crashed on the {host:dict} map
    assert "NONE are active boundary" in text
    assert "Inferred-high" in text and "Unknown" in text
    # the cross-layer finding surfaced as a titled block
    assert "single-fiber uplink to a sole gateway" in text
    # the false-health / operational-drift section (§6.3) surfaced the drift finding
    assert "False-health / operational drift" in text
    assert "Temporary L2 bridge on sw1" in text
    # the endpoint identity section (§7.1) surfaced vendor + class grouping
    assert "Endpoint identity (vendor & type)" in text
    assert "VM / Hypervisor" in text and "VMware, Inc." in text
    # the dependency intelligence (§8.1 clusters/dual-homed + §11.1 per-class validation)
    assert "Endpoint clusters & dependencies" in text
    assert "Service validation by endpoint class" in text
    assert "datastore/LUN reachable" in text
    # subnet & routing reachability (§6.4) + source<->destination
    assert "Subnet & routing reachability" in text
    assert "Remote subnets to preserve" in text
    # migration scenario framework (§3 recommendation + §11.2 playbook)
    assert "GREENFIELD rebuild" in text and "parallel-run" in text
    assert "Cutover playbook by scenario" in text


def test_runbook_validation_section_uses_validation_group_noun(tmp_path):
    """QA row 12 (noun overload): §11.3 counts validation_plan.by_wave buckets (one per move-group, keyed
    'Group N'), a DISTINCT unit from the sequenced wave_plan waves. The noun must read 'validation group',
    reserving 'wave' for the wave_plan, so 'N check(s) across M ...' cannot be misread as the wave count."""
    snap = _snap()
    snap["validation_plan"] = {
        "banner": "Run after each cutover to confirm it succeeded.",
        "by_wave": {"Group 1": [{"device": "sw1", "category": "Gateway", "severity": "High",
                                 "check": "Default gateway for VLAN 10 is up", "command": "show ip int brief",
                                 "expect": "Vlan10 up/up", "why": "endpoints lose their gateway"}]},
        "summary": {"n_items": 1, "n_waves": 1, "n_high": 1, "by_category": {"Gateway": 1}},
    }
    out = str(tmp_path / "rb_val.docx")
    write_runbook_docx(out, snap, "Unit Test Fleet")
    text = _all_text(Document(out))
    assert "Post-cutover verification plan (per validation group)" in text
    assert "check(s) across 1 validation group(s)" in text          # the count noun matches the unit
    assert "Validation group: Group 1" in text                      # the per-bucket heading
    assert "1 wave(s)" not in text and "Wave: Group 1" not in text   # the old overloaded phrasings are gone


def test_runbook_carries_document_furniture(tmp_path):
    """V3.23.150: AS-style front/back matter — Document Control between cover and TOC, and the
    closing acceptance signature gate."""
    out = str(tmp_path / "rb.docx")
    write_runbook_docx(out, _snap(), "Unit Test Fleet")
    d = Document(out)
    h1 = [p.text for p in d.paragraphs if p.style.name == "Heading 1"]
    assert "Document Control" in h1 and "Document Acceptance" in h1
    text = _all_text(d)
    assert "Revision history" in text and "Assumptions & caveats" in text
    assert "Customer network owner" in text                      # acceptance signature roles
    assert "Assessment workbook (.xlsx)" in text                 # related-documents cross-reference


def test_runbook_failsoft_without_python_docx(monkeypatch, tmp_path):
    """If python-docx is not importable, the generator warns and returns -- it never crashes a run
    whose workbook/explorer/JSON already saved."""
    import builtins
    real_import = builtins.__import__

    def _blocked(name, *a, **k):
        if name == "docx" or name.startswith("docx."):
            raise ImportError("simulated missing python-docx")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    out = str(tmp_path / "rb.docx")
    write_runbook_docx(out, _snap(), "Unit Test Fleet")   # must not raise
    import os
    assert not os.path.exists(out)                          # nothing written, no crash


def test_runbook_endpoint_census_uses_canonical_not_mac_sum(tmp_path):
    """Single source of truth: §7 surfaces the canonical evidenced-endpoint count
    (executive_brief.scale.n_endpoints) labeled as endpoints, and labels the access-port MAC sum as
    MACs -- it must NOT publish the MAC sum under the bare word 'Total endpoints' (which diverges from
    the family-wide endpoint count)."""
    snap = _snap()
    snap["executive_brief"] = {"scale": {"n_devices": 2, "n_endpoints": 99, "n_domains": 1}}
    out = str(tmp_path / "rb_ep.docx")
    write_runbook_docx(out, snap, "Unit Test Fleet")
    text = _all_text(Document(out))
    assert "Evidenced endpoints: 99" in text          # canonical, labeled as endpoints
    assert "Access-port host MACs:" in text           # the MAC sum, labeled as MACs
    assert "Total endpoints:" not in text             # the old bare mislabel is gone


def test_runbook_no_fhrp_count_excludes_none_sentinel(tmp_path):
    """False-health guard (the 'none'-is-truthy bug class): gateways carry fhrp='none' when no FHRP is
    configured, and 'none'.strip() is truthy — so the §6 'N of M gateways have no FHRP peer' line
    counted ZERO single-gateway gateways for an all-'none' fleet, the exact inverse of the truth (every
    gateway single-homed). The no-FHRP test must treat 'none' as no-FHRP."""
    snap = _snap()
    snap["l3_forwarding"] = [
        {"switch": "sw1", "vlan": "10", "svi_ip": "10.0.10.1", "fhrp": "none"},        # no FHRP
        {"switch": "sw1", "vlan": "20", "svi_ip": "10.0.20.1", "fhrp": "none"},        # no FHRP
        {"switch": "sw1", "vlan": "30", "svi_ip": "10.0.30.1", "fhrp": "HSRP active"}, # real FHRP
    ]
    out = str(tmp_path / "rb_fhrp.docx")
    write_runbook_docx(out, snap, "Unit Test Fleet")
    text = _all_text(Document(out))
    assert "2 of 3 gateways have no FHRP peer" in text   # the two 'none' gateways, not hidden
    assert "0 of 3 gateways have no FHRP peer" not in text
