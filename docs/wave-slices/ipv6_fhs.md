## buildable
needs-collection

## unit_tests_green
True

## firing_condition
A device has >=1 live PIM neighbor (hard proof sparse-mode is enabled and speaking) AND its 'show ip pim rp mapping' output was actually collected (header/RP/Group seen -> rp_mapping.present True) AND zero rendezvous points are learned (rp_count == 0) AND the domain is not SSM-only (ssm_only False, since 232.0.0.0/8 legitimately needs no RP). That is a definitively broken ASM forwarding state, not blanket absence. Silent (None) on: RP learned, SSM-only, no neighbor (can't prove PIM live), or rp-mapping not collected.

## collection_command
show ip pim rp mapping
show ip pim neighbor

## snapshot_axis
pim

## fixture_device
core1

## notes
buildable=needs-collection: the firing condition is a genuinely clean, senior-grade broken STATE (not cry-wolf), but it requires adding two show-commands. The engine already collects 'show ip pim interface' + 'show ip mroute' (PIM interface mode), but NOT 'show ip pim rp mapping' or 'show ip pim neighbor' -- so the RP-health axis cannot fire on existing evidence and the orchestrator MUST add both commands to COMMANDS_IOS and COMMANDS_NXOS (~lines 506-507 and ~560-561 in COLLECT_PARSE_V3_23_0.py, next to the existing 'show ip pim interface').

Cry-wolf discipline (this is the crux): blanket 'no RP' is NOT fired. Three explicit guards make the detector safe: (1) requires a LIVE PIM neighbor as hard proof sparse-mode is actually running before asserting 'broken' -- a config-only / not-running device never fires; (2) requires rp_mapping.present (the command actually ran) so 'not collected' is never mistaken for 'no RP' -- the classic false-health trap; (3) excludes SSM-only domains (232.0.0.0/8 needs no RP per the SSM model). The 'PIM interface with zero neighbors' idea from the prompt was deliberately DEMOTED to a non-firing signal (pim_running only): a legitimate stub/edge PIM interface (first-hop toward a directly-connected source/receiver with no downstream PIM router) routinely has zero neighbors, so firing on it would cry wolf. The clean, defensible signal is no-RP-while-running.

WORKTREE/COMMIT MISMATCH (important for integration): this worktree is at 1a7f889, which is BEFORE the design-advisor layer the prompt references. None of parse_hsrp_detail / parse_nve_peers / parse_evpn_summary / build_fhrp_detail / build_overlay / design_advisor.py / _d_fhrp_resilience / _decision / _signals exist here (verified by grep across the tree). I matched the engine's ACTUAL conventions (parse.py tolerant parsers returning {}/[]; build.py _safe_parse(parse_X, _load_cmd_output(...)) or {}/[]; the IGMP-querier accumulate-in-loop as the COLLECT_PARSE wiring template) and authored the detector + _decision + _signals exactly to the documented signatures in tests/_pim_detector_ref.py so they are genuinely test-proven. At integration into fa9739e: (a) parsers + build_pim already land cleanly in parse.py/build.py (build.py import line updated); (b) add `show ip pim rp mapping` + `show ip pim neighbor` to both base command lists; (c) in the COLLECT_PARSE Phase-5/6 accumulate loop add `all_pim[hostname] = build_pim(cmd_to_file)` (init `all_pim: Dict[str, dict] = {}`) and publish `snap['pim'] = all_pim`; (d) paste _d_pim_rp_health + the sig[...] block into design_advisor.py and register _d_pim_rp_health in the detector list; (e) re-point the test's `import _pim_detector_ref as ref` to the real design_advisor and delete tests/_pim_detector_ref.py.

VALIDATION (actually ran, green): `python -m pytest tests/test_pim_rp_health.py -q` => 15 passed (6 rp-mapping parser + 3 neighbor parser + 5 detector fire/silent + 1 end-to-end fixture-drives-detector). No regressions: tests/test_parsers.py, test_parser_robustness.py, test_collection_parsers.py, test_collection_completeness.py, test_multicast_intel.py, test_service_map.py, test_decision_layer.py, test_cry_wolf.py all green. COLLECT_PARSE_V3_23_0 + cisco_toolkit.build + cisco_toolkit.parse import cleanly.

FILES TOUCHED (worktree, absolute):
- `<checkout>\.claude\worktrees\wf_b61a3107-d35-2\cisco_toolkit\parse.py` (added parse_pim_rp_mapping, parse_pim_neighbors + 3 module-level regexes)
- ...\cisco_toolkit\build.py (added build_pim; added parse_pim_rp_mapping/parse_pim_neighbors to the parse import block)
- ...\tests\synthetic_fixtures.py (added the firing PIM block to _CORE1)
- ...\tests\_pim_detector_ref.py (NEW; runnable detector stand-in -- _decision + _pim_signals + _d_pim_rp_health)
- ...\tests\test_pim_rp_health.py (NEW; 15 tests)

NX-OS note: 'show ip pim rp mapping' on NX-OS is also accepted as 'show ip pim rp-mapping'/'show ip pim rp' on some trains; parse_pim_rp_mapping is form-agnostic (keys off 'Group(s)'/'RP'), and build_pim/_load_cmd_output could be given variant filenames if a future collection uses the hyphenated command. Detector id DSN-PIM-RP-001 follows the DSN-* design-advisor convention; adjust the prefix to match whatever _d_fhrp_resilience emits in fa9739e if it differs.

## sources
['https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/ipmulti_pim/configuration/xe-16/imc-pim-xe-16-book/imc-verify.html', 'https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/ipmulti_pim/configuration/xe-16/imc-pim-xe-16-book/imc-tech-oview.html', 'https://www.cisco.com/c/en/us/support/docs/ip/multicast/118405-config-rp-00.html', 'https://www.cisco.com/c/en/us/support/docs/ip/ip-multicast/16450-mcastguide0.html', 'https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus5000/sw/command/reference/multicast/n5k-mcast-cr/n5k-pim_cmds_show.html', 'https://datatracker.ietf.org/doc/rfc7761/', 'https://mrncciew.com/2013/02/01/pim-sm-auto-rp-configurations/', 'https://networklessons.com/multicast/multicast-pim-sparse-mode']

## parser_code
```python
# --- PIM-SM control-plane (RP mapping + neighbor adjacency) ------------------ #
# These read 'show ip pim rp mapping' and 'show ip pim neighbor' (IOS / IOS-XE /
# NX-OS). The pair powers the multicast-resilience detector: PIM sparse-mode that
# is *running* (>=1 neighbor or PIM-enabled interface) but has learned NO RP means
# ASM (*,G) shared trees cannot be built -- multicast forwarding is broken
# (RFC 7761 / Cisco: "when no RP is known, the packet is flooded dense-mode";
# the shared-tree join never forms). SSM (232.0.0.0/8) needs no RP, so an
# SSM-only domain is NOT a finding -- parse.rp_mapping flags that so the
# detector never cries wolf. Tolerant: empty/absent -> {} / [].

# Class-D 224-239 already covered by _MCAST_IP_RE; SSM default range is 232/8.
_PIM_RP_LINE_RE = re.compile(
    r"\bRP[:\s]+(\d+\.\d+\.\d+\.\d+)", re.IGNORECASE)          # 'RP 10.0.0.1' / 'Static RP: 10.0.0.1'
_PIM_GROUP_RE = re.compile(
    r"Group\(s\)[:\s]+(\d+\.\d+\.\d+\.\d+/\d+)", re.IGNORECASE)   # 'Group(s) 224.0.0.0/4'
_PIM_INFOSRC_RE = re.compile(
    r"Info source:\s*(\d+\.\d+\.\d+\.\d+)", re.IGNORECASE)


def parse_pim_rp_mapping(output: str) -> dict:
    """'show ip pim rp mapping' (IOS/IOS-XE/NX-OS) -> a learned-RP summary:
    {present, rp_count, rps:[{group, rp, source}], groups:[...], ssm_only}.

    `present`  -- the command actually ran (header / any RP / any Group seen), so an
                  empty {} unambiguously means 'not collected', never 'no RP'.
    `rp_count` -- distinct RP unicast addresses learned (static + Auto-RP + BSR).
    `ssm_only` -- True when the ONLY group range(s) mapped are inside SSM (232.0.0.0/8)
                  and zero RPs are learned: SSM needs no RP, so this is HEALTHY, not broken.

    Handles all three emit shapes:
      IOS Auto-RP / BSR (multi-line):
        Group(s) 224.0.0.0/4
          RP 10.10.205.20 (?), v2v1
            Info source: 10.10.105.20 (?), elected via Auto-RP
      IOS static (single-line):
        Group(s): 224.0.0.0/4, Static RP: 192.168.7.2
      NX-OS:
        Group(s) 224.0.0.0/4, uptime: ..., RP: 10.0.0.1, ...
    {} when no PIM RP-mapping output (absent / Cisco error)."""
    if not output or "rp" not in output.lower() and "group(s)" not in output.lower():
        return {}
    low = output.lower()
    present = ("group-to-rp" in low or "group(s)" in low
               or "rp-mapping" in low or "rp mapping" in low or "rp:" in low or "rp " in low)
    if not present:
        return {}
    rps: List[dict] = []
    groups: List[str] = []
    seen_rp: set = set()
    cur_group = ""
    for raw in output.splitlines():
        s = raw.strip()
        if not s:
            continue
        gm = _PIM_GROUP_RE.search(s)
        if gm:
            cur_group = gm.group(1)
            if cur_group not in groups:
                groups.append(cur_group)
        rm = _PIM_RP_LINE_RE.search(s)
        if rm:
            rp = rm.group(1)
            sm = _PIM_INFOSRC_RE.search(s)
            grp = cur_group
            # static single-line form carries Group(s) and RP on the SAME line
            inline_g = _PIM_GROUP_RE.search(s)
            if inline_g:
                grp = inline_g.group(1)
            rps.append({"group": grp, "rp": rp, "source": (sm.group(1) if sm else "")})
            seen_rp.add(rp)
            continue
        # IOS Auto-RP / BSR emit 'Info source: <ip>' on the line AFTER the RP line;
        # attach it to the most recent RP record whose source is still blank.
        ism = _PIM_INFOSRC_RE.search(s)
        if ism and rps and not rps[-1]["source"]:
            rps[-1]["source"] = ism.group(1)
    # SSM-only: every learned group range is within 232.0.0.0/8 OR no groups + no RP but
    # the operator clearly only advertises SSM ranges. We only assert ssm_only when there
    # are group ranges and they are ALL SSM and no RP was learned (no-RP is EXPECTED there).
    def _is_ssm(cidr: str) -> bool:
        try:
            return cidr.split(".")[0] == "232"
        except Exception:
            return False
    ssm_only = bool(groups) and all(_is_ssm(g) for g in groups) and not seen_rp
    return {"present": True, "rp_count": len(seen_rp), "rps": rps,
            "groups": groups, "ssm_only": ssm_only}


def parse_pim_neighbors(output: str) -> List[dict]:
    """'show ip pim neighbor' (IOS/IOS-XE/NX-OS) -> [{neighbor, interface, uptime}].
    [] when none (no adjacencies) or absent. The mode-legend / header / 'VRF' banner
    lines are skipped. Interfaces are normalised to the engine's short canonical form.

    IOS / IOS-XE (Uptime/Expires combined):
      192.168.12.2   GigabitEthernet0/1   00:00:17/00:01:27 v2   1 / DR S P G
    NX-OS (Uptime and Expires as separate columns, 'PIM Neighbor Status for VRF ...'):
      192.0.2.2   port-channel2000   03:43:40 00:01:21 1 no n/a"""
    out: List[dict] = []
    if not output:
        return out
    for raw in output.splitlines():
        s = raw.strip()
        if not s:
            continue
        low = s.lower()
        # skip headers / legend / VRF banner / column-title continuation lines
        if (low.startswith(("neighbor", "address", "mode:", "pim neighbor", "interface"))
                or "designated router" in low or "dr priority" in low
                or low.startswith(("b -", "p -", "s -", "g -", "l -", "n -"))):
            continue
        m = re.match(r"^(\d+\.\d+\.\d+\.\d+)\s+(\S+)\s+(\d+:\d+:\d+)\b", s)
        if m and is_valid_iface(m.group(2)):
            out.append({"neighbor": m.group(1),
                        "interface": normalize_ifname(m.group(2)),
                        "uptime": m.group(3)})
    return out
```

## build_code
```python
def build_pim(cmd_to_file: Dict[str, str]) -> dict:
    """PIM-SM control-plane facts for the multicast-resilience detector ->
    {rp_mapping, neighbors}:
      rp_mapping = parse_pim_rp_mapping('show ip pim rp mapping')  -- learned-RP summary
                   ({} when uncollected; {present, rp_count, rps, groups, ssm_only} otherwise)
      neighbors  = parse_pim_neighbors('show ip pim neighbor')     -- [{neighbor, interface, uptime}]

    Both {} / [] when their command is absent => the device is 'PIM not collected', distinct
    from 'PIM running but no RP' (rp_mapping.present True, rp_count 0). Fail-soft via _safe_parse."""
    return {
        "rp_mapping": _safe_parse(parse_pim_rp_mapping,
                                  _load_cmd_output(cmd_to_file, "show ip pim rp mapping")) or {},
        "neighbors": _safe_parse(parse_pim_neighbors,
                                 _load_cmd_output(cmd_to_file, "show ip pim neighbor")) or [],
    }

# NOTE: add `parse_pim_rp_mapping, parse_pim_neighbors` to the existing
# `from cisco_toolkit.parse import (...)` block at the top of build.py (done in this worktree).
```

## signal_code
```python
# --- add inside design_advisor._signals(snap), in the `sig` dict build -------- #
# snap['pim'] = {host: {rp_mapping:{present,rp_count,rps,groups,ssm_only}, neighbors:[...]}}
_pim = (snap or {}).get("pim") or {}
_pim_running, _pim_collected, _pim_no_rp = [], [], []
for _host, _facts in sorted(_pim.items()):
    _facts = _facts or {}
    _rpm = _facts.get("rp_mapping") or {}
    _neigh = _facts.get("neighbors") or []
    _present = bool(_rpm.get("present"))
    _running = bool(_neigh)                       # an adjacency is hard proof PIM is up & speaking
    if _present:
        _pim_collected.append(_host)
    if _running:
        _pim_running.append(_host)
    # FIRING STATE: PIM running here, rp-mapping WAS collected, yet no RP learned,
    # and the domain is not SSM-only (SSM legitimately needs no RP).
    if _running and _present and int(_rpm.get("rp_count") or 0) == 0 and not _rpm.get("ssm_only"):
        _pim_no_rp.append(_host)
sig["pim_running"] = _pim_running
sig["pim_collected"] = _pim_collected
sig["pim_no_rp"] = _pim_no_rp
```

## detector_code
```python
def _d_pim_rp_health(sig):
    """Multicast PIM-SM control-plane resilience.

    Fires ONLY on a broken STATE, never on blanket absence: one or more devices have
    PIM sparse-mode RUNNING (a live PIM neighbor) and their 'show ip pim rp mapping'
    WAS collected, yet ZERO rendezvous points are learned and the domain is not
    SSM-only. With no RP, ASM (*,G) shared trees can't be built -- multicast
    forwarding is broken (RFC 7761; Cisco: no-RP => dense-flood, the shared-tree
    join never forms). SSM-only and not-collected are excluded, so it cannot cry wolf.
    Returns None when the axis is absent or clean (coverage-honest)."""
    broken = sig.get("pim_no_rp") or []
    if not broken:
        return None
    n = len(broken)
    return _decision(
        "DSN-PIM-RP-001",
        f"PIM sparse-mode is running on {n} device(s) but no rendezvous point (RP) is "
        f"learned -- ASM multicast (*,G) shared trees cannot form, so multicast "
        f"forwarding is broken. Restore RP reachability/election (static RP, Auto-RP, "
        f"or BSR), or migrate affected groups to SSM, before the cutover baseline.",
        n,
        ["pim", "multicast"],
        {"devices_pim_no_rp": broken,
         "evidence": "show ip pim rp mapping (0 RP) + show ip pim neighbor (>=1 adj)"},
        priority="High",
        driver="multicast-resilience",
        devices=broken,
    )

# Register _d_pim_rp_health in the detector list the blueprint iterates (alongside
# _d_fhrp_resilience / _d_nve_peer_health). The _decision(...) call matches the
# documented helper signature: _decision(pid, summary, count, axes, fields, priority=, driver=, devices=).
```

## fixture_block
```python
    # PIM-SM control plane: core1 RUNS sparse-mode (a live PIM neighbor toward core2),
    # but 'show ip pim rp mapping' learned NO RP -> ASM (*,G) shared trees can't form,
    # multicast forwarding is broken. This is the firing state for _d_pim_rp_health
    # (running + collected + 0 RP + not SSM-only). The header is present so the axis is
    # unambiguously COLLECTED (distinct from 'PIM not collected').
    "show ip pim neighbor": """\
PIM Neighbor Table
Mode: B - Bidir Capable, DR - Designated Router, N - Default DR Priority,
      P - Proxy Capable, S - State Refresh Capable, G - GenID Capable
Neighbor          Interface                Uptime/Expires    Ver   DR
Address                                                            Prio/Mode
10.0.255.2        GigabitEthernet1/0/1     00:42:17/00:01:31 v2    1 / DR S P G
""",
    "show ip pim rp mapping": """\
PIM Group-to-RP Mappings

""",
```

## test_code
```python
# tests/test_pim_rp_health.py  (also imports tests/_pim_detector_ref.py = the runnable
# detector stand-in, since design_advisor.py does not exist at this commit). The
# orchestrator should re-point `import _pim_detector_ref as ref` to the real
# design_advisor once _d_pim_rp_health / _signals are merged there.
import textwrap

from cisco_toolkit.parse import parse_pim_rp_mapping, parse_pim_neighbors
from cisco_toolkit.build import build_pim
import _pim_detector_ref as ref


# ---- parser: parse_pim_rp_mapping ----
def test_rp_mapping_ios_autorp_learned():
    out = textwrap.dedent("""\
        PIM Group-to-RP Mappings
        Group(s) 224.0.0.0/4
          RP 10.10.205.20 (?), v2v1
            Info source: 10.10.105.20 (?), elected via Auto-RP
                 Uptime: 00:12:02, expires: 00:00:53
    """)
    r = parse_pim_rp_mapping(out)
    assert r["present"] is True
    assert r["rp_count"] == 1
    assert r["rps"][0]["rp"] == "10.10.205.20"
    assert r["rps"][0]["group"] == "224.0.0.0/4"
    assert r["rps"][0]["source"] == "10.10.105.20"
    assert r["ssm_only"] is False


def test_rp_mapping_ios_static_single_line():
    out = "PIM Group-to-RP Mappings\nGroup(s): 224.0.0.0/4, Static RP: 192.168.7.2 (?)\n"
    r = parse_pim_rp_mapping(out)
    assert r["rp_count"] == 1 and r["rps"][0]["rp"] == "192.168.7.2"
    assert r["rps"][0]["group"] == "224.0.0.0/4"


def test_rp_mapping_nxos_multiple_rps_distinct_count():
    out = textwrap.dedent("""\
        PIM Group-to-RP Mappings
        Group(s) 239.1.0.0/16, uptime: 1d02h, expires: never,
          RP: 10.0.0.1, (local), via static
        Group(s) 239.2.0.0/16, uptime: 1d02h, expires: never,
          RP: 10.0.0.2, via bsr
    """)
    r = parse_pim_rp_mapping(out)
    assert r["rp_count"] == 2
    assert {x["rp"] for x in r["rps"]} == {"10.0.0.1", "10.0.0.2"}


def test_rp_mapping_broken_header_only_no_rp():
    out = "PIM Group-to-RP Mappings\n\n"
    r = parse_pim_rp_mapping(out)
    assert r["present"] is True and r["rp_count"] == 0
    assert r["ssm_only"] is False


def test_rp_mapping_ssm_only_is_not_broken():
    out = "PIM Group-to-RP Mappings\nGroup(s) 232.0.0.0/8\n  (SSM, no RP required)\n"
    r = parse_pim_rp_mapping(out)
    assert r["present"] is True and r["rp_count"] == 0 and r["ssm_only"] is True


def test_rp_mapping_absent_returns_empty():
    assert parse_pim_rp_mapping("") == {}
    assert parse_pim_rp_mapping("% Invalid input detected") == {}


# ---- parser: parse_pim_neighbors ----
def test_pim_neighbors_ios_combined_uptime_expires():
    out = textwrap.dedent("""\
        PIM Neighbor Table
        Mode: B - Bidir Capable, DR - Designated Router, N - Default DR Priority
        Neighbor          Interface                Uptime/Expires    Ver   DR
        Address                                                            Prio/Mode
        192.168.12.2      GigabitEthernet0/1       00:00:17/00:01:27 v2    1 / DR S P G
        192.168.14.4      GigabitEthernet0/2       00:00:15/00:01:29 v2    1 / DR S P G
    """)
    rows = parse_pim_neighbors(out)
    assert len(rows) == 2
    assert rows[0]["neighbor"] == "192.168.12.2"
    assert rows[0]["interface"] == "Gi0/1"
    assert rows[0]["uptime"] == "00:00:17"


def test_pim_neighbors_nxos_separate_columns():
    out = textwrap.dedent("""\
        PIM Neighbor Status for VRF "default"
        Neighbor       Interface            Uptime    Expires   DR    Bidir-  BFD
                                                                Priority Capable State
        192.0.2.2      port-channel2000     03:43:40  00:01:21  1     no      n/a
        192.0.2.1      Ethernet1/26         03:43:44  00:01:33  1     no      n/a
    """)
    rows = parse_pim_neighbors(out)
    assert len(rows) == 2
    assert rows[0]["interface"] == "Po2000"
    assert rows[1]["interface"] == "Eth1/26"


def test_pim_neighbors_none_returns_empty():
    assert parse_pim_neighbors("") == []
    assert parse_pim_neighbors("PIM Neighbor Table\nNeighbor Interface Uptime\n") == []


# ---- detector: _d_pim_rp_health via the _signals -> detector chain ----
def _detect(snap):
    return ref._d_pim_rp_health(ref._pim_signals(snap))


def test_detector_fires_on_running_pim_without_rp():
    snap = {"pim": {
        "core1": {"rp_mapping": {"present": True, "rp_count": 0, "rps": [], "groups": [], "ssm_only": False},
                  "neighbors": [{"neighbor": "10.0.255.2", "interface": "Gi1/0/1", "uptime": "00:42:17"}]},
    }}
    d = _detect(snap)
    assert d is not None
    assert d["id"] == "DSN-PIM-RP-001"
    assert d["priority"] == "High"
    assert d["count"] == 1 and d["devices"] == ["core1"]
    assert d["engine_actionable"] is True
    assert "pim" in d["axes"] and "multicast" in d["axes"]


def test_detector_silent_when_rp_is_learned():
    snap = {"pim": {
        "core1": {"rp_mapping": {"present": True, "rp_count": 1,
                                 "rps": [{"group": "224.0.0.0/4", "rp": "10.0.0.1", "source": ""}],
                                 "groups": ["224.0.0.0/4"], "ssm_only": False},
                  "neighbors": [{"neighbor": "10.0.255.2", "interface": "Gi1/0/1", "uptime": "1d"}]},
    }}
    assert _detect(snap) is None


def test_detector_silent_on_ssm_only_domain():
    snap = {"pim": {
        "core1": {"rp_mapping": {"present": True, "rp_count": 0, "rps": [],
                                 "groups": ["232.0.0.0/8"], "ssm_only": True},
                  "neighbors": [{"neighbor": "10.0.255.2", "interface": "Gi1/0/1", "uptime": "1d"}]},
    }}
    assert _detect(snap) is None


def test_detector_silent_when_pim_not_running():
    snap = {"pim": {
        "core1": {"rp_mapping": {"present": True, "rp_count": 0, "rps": [], "groups": [], "ssm_only": False},
                  "neighbors": []},
    }}
    assert _detect(snap) is None


def test_detector_silent_when_axis_not_collected():
    assert _detect({"pim": {}}) is None
    assert _detect({}) is None
    snap = {"pim": {"core1": {"rp_mapping": {},
                              "neighbors": [{"neighbor": "10.0.255.2", "interface": "Gi1/0/1", "uptime": "1d"}]}}}
    assert _detect(snap) is None


# ---- end-to-end: the synthetic core1 fixture drives the detector to FIRE ----
def test_core1_fixture_build_pim_fires_detector(collection_root):
    import os
    import synthetic_fixtures as fx
    dev_dir = os.path.join(collection_root, "core1")
    c2f = {c: os.path.join(dev_dir, fx.cmd_filename(c))
           for c in ("show ip pim neighbor", "show ip pim rp mapping")}
    facts = build_pim(c2f)
    assert facts["rp_mapping"]["present"] is True
    assert facts["rp_mapping"]["rp_count"] == 0
    assert len(facts["neighbors"]) == 1
    snap = {"pim": {"core1": facts}}
    d = _detect(snap)
    assert d is not None and d["devices"] == ["core1"]


# ===== _pim_detector_ref.py (runnable detector stand-in; lift _d_pim_rp_health =====
# ===== + _pim_signals into design_advisor.py at integration) =====================
# from typing import Dict, List, Optional
#
# def _decision(pid, summary, count, axes, fields, priority="Medium", driver="", devices=None):
#     return {"id": pid, "summary": summary, "count": count, "axes": axes, "fields": fields,
#             "priority": priority, "driver": driver, "devices": devices or [], "engine_actionable": True}
#
# def _pim_signals(snap):
#     pim = (snap or {}).get("pim") or {}
#     running, broken, collected = [], [], []
#     for host, facts in sorted(pim.items()):
#         facts = facts or {}; rpm = facts.get("rp_mapping") or {}; neigh = facts.get("neighbors") or []
#         present = bool(rpm.get("present")); run = bool(neigh)
#         if present: collected.append(host)
#         if run: running.append(host)
#         if run and present and int(rpm.get("rp_count") or 0) == 0 and not rpm.get("ssm_only"):
#             broken.append(host)
#     return {"pim_running": running, "pim_collected": collected, "pim_no_rp": broken}
#
# def _d_pim_rp_health(sig):  # body identical to detector_code above
```
