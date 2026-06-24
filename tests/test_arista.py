"""Multi-vendor (Arista EOS) MLAG assessment -- the FIRST non-Cisco vendor axis.

Covers parse_arista_mlag ('show mlag | json' device-native JSON parser), build_arista (the per-device axis),
the _signals MLAG extraction, the _d_arista_mlag_degraded detector, the KB principle, and the
_ARCH_COVERAGE_REGISTRY entry. The contract is the universal coverage-honesty doctrine: the detector fires
ONLY on an OBSERVED, settled-broken MLAG domain (config-sanity inconsistent, peer-link/local interface down,
negotiation not connected, state inactive, or Inactive / single-homed member ports) while MLAG is CONFIGURED;
it stays silent for a healthy active+connected+consistent domain, for the transient 'connecting' bring-up
state, and for a switch with MLAG 'disabled' (absence of MLAG is NOT broken MLAG). Proposer != verifier: a
fires-on-broken AND a silent-on-clean assertion for each case, plus a hostile-input robustness sweep.

MLAG is Arista's dual-active redundancy primitive -- the direct analogue of Cisco vPC. The JSON shapes below
follow the Arista EOS 'show mlag' model (state / negStatus / peerLinkStatus / localIntfStatus / configSanity /
mlagPorts), cross-checked against the Arista Network Test Automation (ANTA) MLAG health tests."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from cisco_toolkit import parse        # noqa: E402
from cisco_toolkit import build        # noqa: E402
import cisco_toolkit.design_advisor as da  # noqa: E402
import cisco_toolkit.design_kb as design_kb  # noqa: E402


# --- real 'show mlag | json' shapes (per the Arista EOS show-mlag model + ANTA health tests) -------------
_HEALTHY = """\
{
  "state": "active",
  "negStatus": "connected",
  "peerLinkStatus": "up",
  "localIntfStatus": "up",
  "configSanity": "consistent",
  "peerLink": "Port-Channel1000",
  "peerAddress": "10.0.0.2",
  "systemId": "02:1c:73:00:11:22",
  "domainId": "MLAG-DC1",
  "reloadDelay": 300,
  "reloadDelayNonMlag": 330,
  "portsErrdisabled": false,
  "mlagPorts": {"Disabled": 0, "Active-partial": 0, "Inactive": 0, "Configured": 0, "Active-full": 48}
}
"""

# config-sanity inconsistent -- the Arista analogue of a vPC Type-1 consistency failure (SUSPENDS VLANs).
_CFG_INCONSISTENT = _HEALTHY.replace('"configSanity": "consistent"', '"configSanity": "inconsistent"')
# Inactive member ports -- a leg up on only one peer / not bundled (silent forwarding asymmetry).
_INACTIVE_PORTS = _HEALTHY.replace('"Inactive": 0', '"Inactive": 2')
# Active-partial member ports -- single-homed MLAG ports (one peer only).
_PARTIAL_PORTS = _HEALTHY.replace('"Active-partial": 0', '"Active-partial": 1')
# Peer-link down + the domain gone inactive -- the dual-active fabric is broken / split-brain risk.
_PEERLINK_DOWN = _HEALTHY.replace('"peerLinkStatus": "up"', '"peerLinkStatus": "down"') \
                         .replace('"state": "active"', '"state": "inactive"')

# TRANSIENT bring-up: state connecting -- must NOT fire (mirrors the firewall transient-sync exclusion).
_TRANSIENT = _HEALTHY.replace('"state": "active"', '"state": "connecting"') \
                     .replace('"negStatus": "connected"', '"negStatus": "connecting"')
# MLAG not configured -- state disabled. parse_arista_mlag returns {} -> coverage-honest, never observed.
_DISABLED = _HEALTHY.replace('"state": "active"', '"state": "disabled"')


def _snap(*mlag_jsons):
    """A snapshot whose Arista hosts each carry one parsed MLAG axis (omitting hosts whose MLAG is absent)."""
    arista = {}
    for i, j in enumerate(mlag_jsons):
        m = parse.parse_arista_mlag(j)
        if m:
            arista[f"spine{i + 1}"] = {"mlag": m}
    return {"arista": arista}


def _fire(snap):
    """Run the real signal-build + detector path and return the decision dict (or None)."""
    sig = da._signals(snap)
    return da._d_arista_mlag_degraded(snap, sig)


# ----------------------------------------------------------------------------- parser
def test_parse_healthy_normalizes_fields():
    m = parse.parse_arista_mlag(_HEALTHY)
    assert m["state"] == "active" and m["neg_status"] == "connected"
    assert m["config_sanity"] == "consistent" and m["peer_link_status"] == "up"
    assert m["local_intf_status"] == "up" and m["peer_link"] == "Port-Channel1000"
    assert m["ports_active_full"] == 48 and m["ports_inactive"] == 0 and m["ports_active_partial"] == 0


def test_parse_disabled_is_empty_coverage_honest():
    # MLAG 'disabled' (not configured) -> {} so the axis is never OBSERVED -> the detector can never fire.
    assert parse.parse_arista_mlag(_DISABLED) == {}


def test_parse_hostile_input_never_raises():
    for bad in ("", "not json", "[1,2,3]", "{}", '{"state": null}', "null", '{"mlagPorts": "x"}'):
        out = parse.parse_arista_mlag(bad)
        assert out == {} or isinstance(out, dict)   # never raises; {} when state absent/disabled


def test_build_arista_offline(tmp_path):
    # build_arista reads the captured 'show mlag' file through the same offline path the Cisco classes use.
    d = tmp_path / "spine1"
    d.mkdir()
    (d / "show_mlag.txt").write_text(_CFG_INCONSISTENT, encoding="utf-8")
    out = build.build_arista({"show mlag": str(d / "show_mlag.txt")})
    assert out.get("mlag", {}).get("config_sanity") == "inconsistent"
    # a Cisco device (no show_mlag capture) -> {} -> coverage-honest silence
    assert build.build_arista({}) == {}


# ----------------------------------------------------------------------------- detector: FIRES on broken
def test_fires_on_config_sanity_inconsistent():
    d = _fire(_snap(_CFG_INCONSISTENT))
    assert d and d["id"] == "arista-mlag-domain-degraded" and d["priority"] == "High"
    assert "config-sanity inconsistent" in d["evidence"]["summary"]
    assert d["evidence"]["count"] == 1 and d["evidence"]["devices"] == ["spine1"]


def test_fires_on_inactive_ports():
    d = _fire(_snap(_INACTIVE_PORTS))
    assert d and d["id"] == "arista-mlag-domain-degraded"
    assert "inactive MLAG port" in d["evidence"]["summary"]


def test_fires_on_single_homed_partial_ports():
    d = _fire(_snap(_PARTIAL_PORTS))
    assert d and "single-homed MLAG port" in d["evidence"]["summary"]


def test_fires_on_peerlink_down_and_inactive_state():
    d = _fire(_snap(_PEERLINK_DOWN))
    assert d and d["id"] == "arista-mlag-domain-degraded"
    s = d["evidence"]["summary"]
    assert "peer-link down" in s and "state inactive" in s


def test_fires_counts_each_degraded_domain():
    d = _fire(_snap(_CFG_INCONSISTENT, _INACTIVE_PORTS, _HEALTHY))   # 2 broken + 1 healthy
    assert d and d["evidence"]["count"] == 2 and len(d["evidence"]["devices"]) == 2


# ----------------------------------------------------------------------------- detector: SILENT on clean
def test_silent_on_healthy_domain():
    assert _fire(_snap(_HEALTHY)) is None


def test_silent_on_transient_connecting_bringup():
    # a domain mid-bring-up (state connecting) must NOT cry wolf (the transient exclusion).
    assert _fire(_snap(_TRANSIENT)) is None


def test_silent_when_mlag_disabled_or_absent():
    # disabled -> parse {} -> no axis; an empty fleet -> no axis. Either way: never fires (coverage-honest).
    assert _fire(_snap(_DISABLED)) is None
    assert _fire({"arista": {}}) is None
    assert _fire({}) is None


# ----------------------------------------------------------------------------- robustness (proposer != verifier)
def test_detector_never_raises_on_malformed_axis():
    for bad in ({"arista": "x"}, {"arista": ["spine1"]}, {"arista": {"s1": "x"}},
                {"arista": {"s1": {"mlag": "x"}}}, {"arista": {"s1": {"mlag": {"state": "active"}}}}):
        sig = da._signals(bad)                       # must not raise
        out = da._d_arista_mlag_degraded(bad, sig)   # must not raise
        assert out is None or isinstance(out, dict)


# ----------------------------------------------------------------------------- KB principle + registry
def test_principle_is_complete_and_engine_actionable():
    p = design_kb.by_id("arista-mlag-domain-degraded")
    assert p and p["engine_actionable"] is True
    for k in ("title", "domain", "design_intent", "observable", "trigger", "recommended_action",
              "alternatives", "tradeoffs", "citation"):
        assert (p.get(k) or "").strip(), f"principle missing {k}"
    assert "Arista" in p["citation"]            # primary-source-cited (multi-vendor: the source is Arista's own docs)


def test_arista_in_architecture_coverage_registry():
    keys = {axis for axis, *_ in da._ARCH_COVERAGE_REGISTRY}
    assert "arista" in keys
    # observed-with-finding when an Arista MLAG axis is present AND its detector fired
    snap = _snap(_CFG_INCONSISTENT) | {"design_blueprint": {"decisions": [{"id": "arista-mlag-domain-degraded"}]}}
    cov = da.compute_architecture_coverage(snap)
    by = {c["key"]: c for c in cov["classes"]}
    assert by["arista"]["observed"] and by["arista"]["status"] == "finding" and by["arista"]["channel"] == "ssh"
    # coverage-honest: a fleet with no Arista evidence reads not-observed, never 'healthy'
    assert da.compute_architecture_coverage({})["summary"]["n_not_observed"] >= 1
    none = {c["key"]: c for c in da.compute_architecture_coverage({})["classes"]}
    assert none["arista"]["status"] == "not-observed"
