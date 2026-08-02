"""Cisco-depth: multicast RPF integrity -- the #1 multicast data-plane outage, made COVERAGE-HONEST.

An (S,G) source-tree entry with 'Incoming interface: Null' AND a NON-ZERO RPF neighbour is a genuine RPF anomaly
(the reverse path the stream must use is unavailable), but TWO Null-IIF classes are benign: a (*,G) shared-tree
entry (locally-joined / well-known / SSM groups on NX-OS), and an (S,G) whose 'RPF nbr' is 0.0.0.0 -- per Cisco,
THIS router is the source (a local source / PIM register / SPT-pending), a normal Null IIF, not a failure. A naive
'Null IIF' detector cries wolf on every such benign entry; the coverage-honest one fires ONLY on (S,G)+Null+
non-zero-RPF. This is PROVEN against the real Meridian reference fleet: 36 benign (*,G)-Null entries and 0 (S,G)-Null, so the
detector is silent there. Covers parse_mroute_entries (NX-OS + IOS), build_mroute (the (S,G)-only filter), the
_signals extraction, _d_mcast_rpf_failure, the KB principle and the pim-class registry entry. The mroute text is
grounded in real NX-OS 'show ip mroute' output."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from cisco_toolkit import parse        # noqa: E402
from cisco_toolkit import build        # noqa: E402
import cisco_toolkit.design_advisor as da  # noqa: E402
import cisco_toolkit.design_kb as design_kb  # noqa: E402


# --- real NX-OS 'show ip mroute' shapes ---------------------------------------------------------------------
# Healthy: a (*,G) with a benign Null IIF (locally-joined group) AND an (S,G) with a REAL RPF interface.
_HEALTHY = """\
IP Multicast Routing Table for VRF "default"

(*, 224.0.1.22/32), uptime: 5y1w, igmp ip pim
  Incoming interface: Null, RPF nbr: 0.0.0.0
  Outgoing interface list: (count: 1)
    Vlan12, uptime: 5y1w, igmp

(10.203.16.14/32, 239.255.255.1/32), uptime: 00:01:05, ip pim
  Incoming interface: Ethernet1/1, RPF nbr: 10.203.0.1
  Outgoing interface list: (count: 1)
    Vlan20, uptime: 00:01:05, pim
"""
# The (S,G) keeps its non-zero RPF neighbour (10.203.0.1) but its incoming interface goes Null -> the reverse
# path the multicast must use is unavailable -> blackholed -> FIRES (the genuine RPF anomaly).
_SG_NULL = _HEALTHY.replace(
    "Incoming interface: Ethernet1/1, RPF nbr: 10.203.0.1",
    "Incoming interface: Null, RPF nbr: 10.203.0.1")
# An (S,G) with a Null IIF but 'RPF nbr 0.0.0.0' = THIS router is the source (local source / PIM register /
# SPT-pending) -- per Cisco a BENIGN Null IIF, NOT an RPF failure -> must STAY SILENT. The regression guard for the
# cry-wolf the old detector had: it ignored the RPF neighbour and flagged every (S,G)-Null local source.
_SG_NULL_LOCAL = _HEALTHY.replace(
    "Incoming interface: Ethernet1/1, RPF nbr: 10.203.0.1",
    "Incoming interface: Null, RPF nbr: 0.0.0.0")
# Only (*,G) Null entries (the dominant Meridian pattern -- 36 of them) -> must STAY SILENT (no cry-wolf).
_STAR_NULL_ONLY = """\
IP Multicast Routing Table for VRF "default"

(*, 224.0.1.84/32), uptime: 9y36w, ip pim igmp
  Incoming interface: Null, RPF nbr: 0.0.0.0
  Outgoing interface list: (count: 2)
    Vlan27, uptime: 8y43w, igmp
    Vlan25, uptime: 9y36w, igmp

(*, 232.0.0.0/8), uptime: 5y48w, pim ip
  Incoming interface: Null, RPF nbr: 0.0.0.0
  Outgoing interface list: (count: 0)
"""
# IOS 'show ip mroute' format (different header + no '(count: N)') -- the (S,G) here has a Null IIF with a
# NON-ZERO RPF nbr -> FIRES. The (*,G) Null and the (S,G)'s would-be local-source 0.0.0.0 are handled elsewhere.
_IOS_SG_NULL = """\
IP Multicast Routing Table
(*, 239.1.1.1), 00:01:00/00:02:30, RP 10.0.0.1, flags: S
  Incoming interface: Null, RPF nbr 0.0.0.0
  Outgoing interface list:
    Vlan10, Forward/Sparse, 00:01:00/00:02:30
(10.0.0.5, 239.1.1.1), 00:00:30/00:02:59, flags: T
  Incoming interface: Null, RPF nbr 10.0.0.9
  Outgoing interface list:
    Vlan10, Forward/Sparse, 00:00:30/00:02:30
"""


def _snap(*mroute_texts):
    """snap['mroute'] built by the REAL producer — cisco_toolkit.build.build_mroute — from the raw
    capture text, exactly as a collection run does.

    NON-VACUITY (mutation-proved, 2026-07-28). This helper used to RE-IMPLEMENT the
    (S,G)+Null+non-zero-RPF filter inline, "exactly as build_mroute does". That made every detector
    test below agree with the TEST's copy of the rule instead of the shipped one: deleting the
    local-source exclusion from `build.build_mroute` — which turns every real
    (S,G)+Null+'RPF nbr 0.0.0.0' local-source entry into a fabricated High RPF blackhole, the exact
    cry-wolf `test_silent_on_sg_null_local_source` exists to prevent — left this entire file GREEN.
    The one test that did drive the real builder never fed it the local-source fixture.

    Feeding the real producer costs a temp file and closes the gap for all six detector tests."""
    mr = {}
    with tempfile.TemporaryDirectory() as td:
        for i, t in enumerate(mroute_texts):
            path = os.path.join(td, f"show_ip_mroute_{i}.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(t)
            built = build.build_mroute({"show ip mroute": path})
            if built:                       # {} for a non-mroute device — same skip as before
                mr[f"rtr{i + 1}"] = built
    return {"mroute": mr}


def _fire(snap):
    sig = da._signals(snap)
    return da._d_mcast_rpf_failure(snap, sig)


# ----------------------------------------------------------------------------- parser
def test_parse_nxos_entries_source_group_iif():
    es = parse.parse_mroute_entries(_HEALTHY)
    assert len(es) == 2
    by = {(e["source"], e["group"]): e for e in es}
    assert by[("*", "224.0.1.22")]["iif"].lower() == "null"                  # (*,G) benign Null
    assert by[("*", "224.0.1.22")]["rpf_nbr"] == "0.0.0.0"                    # RPF nbr captured (local/self)
    assert by[("10.203.16.14", "239.255.255.1")]["iif"] == "Ethernet1/1"     # (S,G) healthy RPF
    assert by[("10.203.16.14", "239.255.255.1")]["rpf_nbr"] == "10.203.0.1"  # real upstream RPF neighbour
    assert by[("10.203.16.14", "239.255.255.1")]["oil_count"] == 1


def test_parse_ios_format():
    es = parse.parse_mroute_entries(_IOS_SG_NULL)
    by = {(e["source"], e["group"]): e for e in es}
    assert by[("*", "239.1.1.1")]["iif"].lower() == "null"
    assert by[("10.0.0.5", "239.1.1.1")]["iif"].lower() == "null"            # the (S,G) failure
    assert by[("10.0.0.5", "239.1.1.1")]["rpf_nbr"] == "10.0.0.9"            # non-zero RPF nbr (IOS 'RPF nbr X')


def test_parse_hostile_input_never_raises():
    for bad in ("", "no table here", "(*, garbage", "(1,2,3)\nIncoming interface:"):
        out = parse.parse_mroute_entries(bad)
        assert isinstance(out, list)


def test_build_mroute_only_flags_sg_null(tmp_path):
    d = tmp_path / "rtr"; d.mkdir()
    (d / "show_ip_mroute.txt").write_text(_SG_NULL, encoding="utf-8")
    out = build.build_mroute({"show ip mroute": str(d / "show_ip_mroute.txt")})
    assert out["n_entries"] == 2
    assert len(out["rpf_failures"]) == 1 and out["rpf_failures"][0]["source"] == "10.203.16.14"
    # the (*,G) Null entry is NOT a failure
    assert all(r["source"] != "*" for r in out["rpf_failures"])
    # a (*,G)-only table -> observed but ZERO failures (clean), and a non-mroute device -> {}
    (d / "show_ip_mroute.txt").write_text(_STAR_NULL_ONLY, encoding="utf-8")
    out2 = build.build_mroute({"show ip mroute": str(d / "show_ip_mroute.txt")})
    assert out2["rpf_failures"] == [] and out2["n_entries"] == 2
    assert build.build_mroute({}) == {}


# ----------------------------------------------------------------------------- detector: FIRES on (S,G) Null
def test_fires_on_sg_null():
    d = _fire(_snap(_SG_NULL))
    assert d and d["id"] == "multicast-rpf-failure-sg" and d["priority"] == "High"
    assert "10.203.16.14" in d["evidence"]["summary"] and d["evidence"]["devices"] == ["rtr1"]


def test_fires_on_ios_sg_null():
    d = _fire(_snap(_IOS_SG_NULL))
    assert d and "10.0.0.5" in d["evidence"]["summary"]


# ----------------------------------------------------------------------------- detector: SILENT (no cry-wolf)
def test_silent_on_star_g_null_only():
    # THE coverage-honesty case: a table of (*,G) Null entries (the 36-benign Meridian pattern) must NOT fire
    assert _fire(_snap(_STAR_NULL_ONLY)) is None


def test_silent_on_healthy_sg():
    assert _fire(_snap(_HEALTHY)) is None                # (S,G) has a real RPF interface


def test_silent_on_sg_null_local_source():
    # (S,G)+Null+'RPF nbr 0.0.0.0' = THIS router is the source (local source / PIM register / SPT-pending). Per
    # Cisco this is a BENIGN Null IIF, NOT an RPF failure -> must STAY SILENT. The regression guard for the
    # confirmed cry-wolf: the old filter ignored the RPF neighbour and fired on every such local-source entry.
    assert _fire(_snap(_SG_NULL_LOCAL)) is None


def test_silent_when_no_mroute():
    assert _fire(_snap("")) is None
    assert _fire({"mroute": {}}) is None
    assert _fire({}) is None


# ----------------------------------------------------------------------------- robustness (proposer != verifier)
def test_detector_never_raises_on_malformed_axis():
    for bad in ({"mroute": "x"}, {"mroute": ["rtr"]}, {"mroute": {"r": "x"}},
                {"mroute": {"r": {"rpf_failures": "x"}}},
                {"mroute": {"r": {"rpf_failures": [{"source": None, "group": None}]}}}):
        sig = da._signals(bad)
        out = da._d_mcast_rpf_failure(bad, sig)
        assert out is None or isinstance(out, dict)


# ----------------------------------------------------------------------------- KB principle + registry
def test_principle_complete_and_engine_actionable():
    p = design_kb.by_id("multicast-rpf-failure-sg")
    assert p and p["engine_actionable"] is True and p["domain"] == "multicast"
    for k in ("title", "design_intent", "observable", "trigger", "recommended_action",
              "alternatives", "tradeoffs", "citation"):
        assert (p.get(k) or "").strip(), f"principle missing {k}"
    assert any(t in p["citation"] for t in ("Cisco", "RFC"))


def test_rpf_pid_on_pim_registry_class():
    pim = [t for t in da._ARCH_COVERAGE_REGISTRY if t[0] == "pim"][0]
    assert "multicast-rpf-failure-sg" in pim[3] and "multicast-pim-rp-resilience" in pim[3]
