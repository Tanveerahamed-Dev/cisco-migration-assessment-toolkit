"""Plan-A #15 (Stage-3 positional collapse): the three ctx-adapters that let main() stop threading
15-19 locals positionally through _run_phase. Each adapter reads AnalysisContext fields and forwards
them to the UNCHANGED public compute_* by KEYWORD -- so the binding is named and reorder-proof, and
the webapp / excel / ~40 direct-call tests keep calling compute_* with explicit args untouched.

These pin the field->parameter MAPPING (including the main-local -> param renames
all_security->security, all_config_hygiene->config_hygiene, all_stp_roots->stp_roots, all_vpc->vpc)
by capturing exactly what the adapter forwards. A swapped field or a rename typo fails here at the
smallest possible slice, independently of the end-to-end pipeline golden. Every field is given a
DISTINCT sentinel value so a two-field swap cannot pass silently.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import COLLECT_PARSE_V3_23_0 as cp   # noqa: E402  (the entry module carrying the adapters)
from cisco_toolkit.context import AnalysisContext   # noqa: E402


def _capturing(monkeypatch, name):
    """Replace cp.<name> with a fake that records (args, kwargs) and returns a unique sentinel."""
    rec = {"args": None, "kwargs": None, "ret": object()}

    def _fake(*args, **kwargs):
        rec["args"] = args
        rec["kwargs"] = kwargs
        return rec["ret"]

    monkeypatch.setattr(cp, name, _fake)
    return rec


def test_device_dossiers_adapter_maps_ctx_to_explicit_kwargs(monkeypatch):
    rec = _capturing(monkeypatch, "compute_device_dossiers")
    ctx = AnalysisContext(
        health_scores=["hs"], failure_impact=["fi"], lifecycle_risk={"lc": 1},
        software_risk={"sw": 1}, platform_health={"pl": 1}, syslog_intelligence={"si": 1},
        qos_audit={"qa": 1}, golden_drift={"gd": 1}, all_security={"sec": 1},
        all_config_hygiene={"cfg": 1}, all_stp_roots={"stp": 1}, all_vpc={"vpc": 1},
        physical_health=["ph"], protocol_health=["pr"], move_groups=["mg"])
    out = cp._device_dossiers(ctx)
    assert out is rec["ret"]                 # the adapter returns the compute result verbatim
    assert rec["args"] == ()                 # everything forwarded by keyword -> reorder-proof
    assert rec["kwargs"] == {
        "health_scores": ["hs"], "failure_impact": ["fi"], "lifecycle_risk": {"lc": 1},
        "software_risk": {"sw": 1}, "platform_health": {"pl": 1}, "syslog_intelligence": {"si": 1},
        "qos_audit": {"qa": 1}, "golden_drift": {"gd": 1},
        "security": {"sec": 1}, "config_hygiene": {"cfg": 1},        # main-local -> param renames
        "stp_roots": {"stp": 1}, "vpc": {"vpc": 1},
        "physical_health": ["ph"], "protocol_health": ["pr"], "move_groups": ["mg"],
    }


def test_punchlist_adapter_maps_ctx_to_explicit_kwargs(monkeypatch):
    rec = _capturing(monkeypatch, "compute_migration_punchlist")
    ctx = AnalysisContext(
        cross_layer=["cl"], all_security={"sec": 1}, all_config_hygiene={"cfg": 1},
        physical_health=["ph"], l3_forwarding=["l3"], protocol_health=["pr"],
        stp_findings={"stp": 1}, health_scores=["hs"], move_groups=["mg"],
        l2={"l2": 1}, hostname_mismatches=["hm"], drift=["dr"], ptp_readiness=["ptp"],
        media_risks=["mr"], syslog_intelligence={"si": 1}, qos_audit={"qa": 1},
        software_risk={"sw": 1}, platform_health={"pl": 1}, device_dossiers={"dd": 1})
    out = cp._punchlist(ctx)
    assert out is rec["ret"]
    assert rec["args"] == ()
    assert rec["kwargs"] == {
        "cross_layer": ["cl"], "security": {"sec": 1}, "config_hygiene": {"cfg": 1},
        "physical_health": ["ph"], "l3_forwarding": ["l3"], "protocol_health": ["pr"],
        "stp_findings": {"stp": 1}, "health_scores": ["hs"], "move_groups": ["mg"],
        "l2": {"l2": 1}, "hostname_mismatches": ["hm"], "drift": ["dr"],
        "ptp_readiness": ["ptp"], "media_risks": ["mr"], "syslog_intelligence": {"si": 1},
            "qos_audit": {"qa": 1}, "software_risk": {"sw": 1}, "platform_health": {"pl": 1},
            "device_dossiers": {"dd": 1},
            "protocol_assessability": {}, "vtp_safety_baseline": {},
            "vtp_safety_subject_scope": [],
            "ipv6_routing_adjacency_baseline": {},
            "ipv6_routing_subject_scope": {},
        }


def test_executive_brief_adapter_maps_ctx_to_explicit_kwargs(monkeypatch):
    rec = _capturing(monkeypatch, "compute_executive_brief")
    ctx = AnalysisContext(
        health_scores=["hs"], punchlist=["pl"], migration_readiness=["mr"],
        application_intelligence={"app": 1}, lifecycle_risk={"lc": 1}, segmentation={"seg": 1},
        multicast_intelligence={"mi": 1}, remediation_plan={"rem": 1}, syslog_intelligence={"si": 1},
        qos_audit={"qa": 1}, software_risk={"sw": 1}, platform_health={"ph": 1},
        device_dossiers={"dd": 1}, endpoint_identity=["ep"])
    out = cp._executive_brief(ctx)
    assert out is rec["ret"]
    assert rec["args"] == ()
    assert rec["kwargs"] == {
        "health_scores": ["hs"], "punchlist": ["pl"], "migration_readiness": ["mr"],
        "application_intelligence": {"app": 1}, "lifecycle_risk": {"lc": 1}, "segmentation": {"seg": 1},
        "multicast_intelligence": {"mi": 1}, "remediation_plan": {"rem": 1},
        "syslog_intelligence": {"si": 1}, "qos_audit": {"qa": 1}, "software_risk": {"sw": 1},
        "platform_health": {"ph": 1}, "device_dossiers": {"dd": 1}, "endpoint_identity": ["ep"],
    }
