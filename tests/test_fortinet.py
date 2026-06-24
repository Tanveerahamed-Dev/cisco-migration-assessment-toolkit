"""Multi-vendor (Fortinet FortiGate) HA cluster-sync assessment -- the THIRD non-Cisco vendor.

FortiGate HA is the firewall HA pair (Active-Passive / Active-Active) -- the analogue of the Cisco ASA/FTD
'show failover' and the Juniper SRX chassis cluster. Covers parse_fortigate_ha_status ('get system ha status'),
build_fortigate, the _signals extraction, the _d_fortigate_ha_degraded detector, the KB principle and the
_ARCH_COVERAGE_REGISTRY entry. The contract is the universal coverage-honesty doctrine: the detector fires ONLY
on an OBSERVED, settled-broken HA state -- a member 'out-of-sync' (a config-checksum mismatch, so the standby
holds DIVERGENT config and a failover would apply the wrong ruleset) or the HA Health Status not OK -- while HA
is configured; it stays silent for an all-in-sync + Health-OK cluster and for a standalone FortiGate (absence of
HA is NOT broken HA). The text is grounded in a real 'get system ha status' capture."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from cisco_toolkit import parse        # noqa: E402
from cisco_toolkit import build        # noqa: E402
import cisco_toolkit.design_advisor as da  # noqa: E402
import cisco_toolkit.design_kb as design_kb  # noqa: E402


# --- a real 'get system ha status' capture (FortiOS, Active-Passive cluster) -------------------------------
_HEALTHY = """\
HA Health Status: OK
Model: FortiGate-100F
Mode: HA A-P
Group: 10
Debug: 0
Cluster Uptime: 45 days 3:14:22
Cluster state change time: 2026-01-08 02:17:41
Primary selected using:
  <2026/01/08 02:17:41> FGT-A is selected as the primary because its override priority is larger than peer member FGT-B.
ses_pickup: enable
override: enable
Configuration Status:
  FGT-A(updated 2 seconds ago): in-sync
  FGT-B(updated 3 seconds ago): in-sync
System Usage stats:
  FGT-A: CPU 3%, Memory 54%
  FGT-B: CPU 2%, Memory 51%
HBDEV stats:
  port3: FGT-A: up, FGT-B: up
Primary     : FGT-A, serial number FG100FTK00000001
Secondary   : FGT-B, serial number FG100FTK00000002
"""

# the secondary's config is OUT-OF-SYNC -- a checksum mismatch, so a failover would apply a divergent ruleset.
_OUT_OF_SYNC = _HEALTHY.replace("FGT-B(updated 3 seconds ago): in-sync",
                                "FGT-B(updated 8 seconds ago): out-of-sync")
# the cluster reports HA Health WARNING (a monitored fault) even though config still reads in-sync.
_HEALTH_WARNING = _HEALTHY.replace("HA Health Status: OK", "HA Health Status: WARNING")

# a standalone FortiGate (no HA) -- 'get system ha status' shows Mode: Standalone, no Configuration Status.
_STANDALONE = """\
HA Health Status: Standalone
Model: FortiGate-100F
Mode: Standalone
"""


def _snap(*ha_texts):
    fg = {}
    for i, t in enumerate(ha_texts):
        ha = parse.parse_fortigate_ha_status(t)
        if ha:
            fg[f"fgt{i + 1}"] = {"ha": ha}
    return {"fortigate": fg}


def _fire(snap):
    sig = da._signals(snap)
    return da._d_fortigate_ha_degraded(snap, sig)


# ----------------------------------------------------------------------------- parser
def test_parse_healthy_cluster():
    ha = parse.parse_fortigate_ha_status(_HEALTHY)
    assert ha["health"] == "OK" and ha["mode"].startswith("HA")
    by = {m["name"]: m["sync"] for m in ha["members"]}
    assert by == {"FGT-A": "in-sync", "FGT-B": "in-sync"}


def test_parse_out_of_sync_member():
    ha = parse.parse_fortigate_ha_status(_OUT_OF_SYNC)
    by = {m["name"]: m["sync"] for m in ha["members"]}
    assert by["FGT-B"] == "out-of-sync" and by["FGT-A"] == "in-sync"


def test_parse_standalone_is_empty_coverage_honest():
    # a standalone box (Mode: Standalone, no Configuration Status) -> {} so the axis is never OBSERVED
    assert parse.parse_fortigate_ha_status(_STANDALONE) == {}


def test_parse_hostile_input_never_raises():
    for bad in ("", "garbage", "Mode: HA A-P\n(no config status)", "Configuration Status:\n  x(updated): weird"):
        out = parse.parse_fortigate_ha_status(bad)
        assert out == {} or isinstance(out, dict)


def test_build_fortigate_offline(tmp_path):
    d = tmp_path / "fgt"
    d.mkdir()
    (d / "get_system_ha_status.txt").write_text(_OUT_OF_SYNC, encoding="utf-8")
    out = build.build_fortigate({"get system ha status": str(d / "get_system_ha_status.txt")})
    assert out.get("ha", {}).get("members")
    assert build.build_fortigate({}) == {}                 # a non-FortiGate device -> {} -> coverage-honest


# ----------------------------------------------------------------------------- detector: FIRES on degraded
def test_fires_on_out_of_sync():
    d = _fire(_snap(_OUT_OF_SYNC))
    assert d and d["id"] == "fortigate-ha-cluster-out-of-sync" and d["priority"] == "High"
    assert "out-of-sync" in d["evidence"]["summary"] and "FGT-B" in d["evidence"]["summary"]
    assert d["evidence"]["devices"] == ["fgt1"]


def test_fires_on_health_warning():
    d = _fire(_snap(_HEALTH_WARNING))
    assert d and "WARNING" in d["evidence"]["summary"]


# ----------------------------------------------------------------------------- detector: SILENT on clean
def test_silent_on_healthy_cluster():
    assert _fire(_snap(_HEALTHY)) is None


def test_silent_on_standalone_or_absent():
    assert _fire(_snap(_STANDALONE)) is None                # standalone -> {} -> no axis
    assert _fire({"fortigate": {}}) is None
    assert _fire({}) is None


# ----------------------------------------------------------------------------- robustness (proposer != verifier)
def test_detector_never_raises_on_malformed_axis():
    for bad in ({"fortigate": "x"}, {"fortigate": ["fgt"]}, {"fortigate": {"f": "x"}},
                {"fortigate": {"f": {"ha": "x"}}}, {"fortigate": {"f": {"ha": {"members": "x"}}}},
                {"fortigate": {"f": {"ha": {"members": [{"sync": None, "name": None}]}}}}):
        sig = da._signals(bad)
        out = da._d_fortigate_ha_degraded(bad, sig)
        assert out is None or isinstance(out, dict)


# ----------------------------------------------------------------------------- KB principle + registry
def test_principle_complete_and_engine_actionable():
    p = design_kb.by_id("fortigate-ha-cluster-out-of-sync")
    assert p and p["engine_actionable"] is True
    for k in ("title", "domain", "design_intent", "observable", "trigger", "recommended_action",
              "alternatives", "tradeoffs", "citation"):
        assert (p.get(k) or "").strip(), f"principle missing {k}"
    assert "Fortinet" in p["citation"] or "FortiGate" in p["citation"]


def test_fortigate_in_architecture_coverage_registry():
    keys = {axis for axis, *_ in da._ARCH_COVERAGE_REGISTRY}
    assert "fortigate" in keys
    snap = _snap(_OUT_OF_SYNC) | {"design_blueprint": {"decisions": [{"id": "fortigate-ha-cluster-out-of-sync"}]}}
    cov = da.compute_architecture_coverage(snap)
    by = {c["key"]: c for c in cov["classes"]}
    assert by["fortigate"]["observed"] and by["fortigate"]["status"] == "finding" and by["fortigate"]["channel"] == "ssh"
    none = {c["key"]: c for c in da.compute_architecture_coverage({})["classes"]}
    assert none["fortigate"]["status"] == "not-observed"
