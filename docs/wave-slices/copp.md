## buildable
yes

## unit_tests_green
True

## firing_condition
A CoPP class with a non-zero discard counter (drops = exceeded + violated + dropped > 0) — i.e. the control-plane policer is ACTIVELY dropping punted traffic. This is a broken STATE, not absence: an armed-but-not-firing policer (every class at drops==0, the normal case) stays silent, and an absent copp axis stays silent. Fires only on observed active discards (a mistuned policer clipping legitimate routing/ARP/management punts, or a control-plane flood/DoS starving the supervisor). priority=High.

## collection_command
show policy-map interface control-plane   (NX-OS; added to COMMANDS_NXOS) and show policy-map control-plane   (IOS / IOS-XE; added to COMMANDS_IOS). build_copp tries both names via _load_cmd_output.

## snapshot_axis
copp

## fixture_device
core2

## notes
WORKTREE COMMIT MISMATCH (handled): the prompt said HEAD=fa9739e but the worktree was actually checked out at 1a7f889, which PREDATES design_advisor.py and every named reference slice. I git reset --hard fa9739e (the real HEAD of feat/asne-rig-and-ssot, the commit that introduced the FHRP/overlay slices) so I replicated against the genuine committed template rather than reinventing. The orchestrator should integrate from a fa9739e (or later) base; the diffs assume it.

WHY buildable=yes and NON-CRY-WOLF: the firing signal is a broken STATE (drops>0 = the policer is actively discarding CPU-punted traffic), not blanket absence. CoPP being unconfigured, or configured-but-not-firing (every class at drops==0, the overwhelmingly common case), both stay SILENT. This is the clean analogue of _d_nve_peer_health (a DOWN peer fires; an all-Up fabric is silent) rather than _d_fhrp (absence fires) — chosen deliberately because 'no CoPP' on a brownfield box is noisy/expected and would cry wolf. The 4-case refutation suite proves: armed-but-clean (3 classes, 0 drops) -> silent; absent/empty axis -> silent; flip one counter 0->1 -> fires (evidence-gated, not hardcoded); multi-host -> only the dropping host is attributed.

UNIT semantics (honest): NX-OS counts in BYTES, IOS/IOS-XE in PACKETS. copp_drop_pkts is therefore a per-platform count and the summary says 'total discarded' (no unit) rather than asserting 'packets'. The firing predicate (drops>0) is unit-agnostic so the verdict is identical on both platforms; the regex only matches when the unit token is literally 'packets' or 'bytes', which also excludes the rate lines ('5-min violate rate N bytes/sec' — 'rate' precedes the number) and the policer config line ('police cir 36000 kbps bc 250 ms') so neither is miscounted.

KB: design_kb.py deliberately NOT touched. PID 'copp-control-plane-policer-dropping' is absent from the KB, exactly like the reference detectors' PIDs (vxlan-nve-peer-down, fhrp-resilience-tracking-and-preempt are both MISSING too); _decision resolves it via 'design_kb.by_id(pid) or {}' to title=pid + empty citation/action, and the detector carries the full summary/driver/axes. The KB already holds the control-plane-protection doctrine (8 CoPP mentions) for grounding, but had no engine_actionable CoPP-DROPS detector — this is genuine net-new coverage of collected-but-previously-unparsed evidence.

GOLDEN: tests/golden/snapshot.json was regenerated (UPDATE_GOLDEN=1) because 'copp' is a new top-level snapshot key — the same churn fa9739e took for 'overlay'/'fhrp_detail'. If the orchestrator prefers to own the regen, it can discard my tests/golden/snapshot.json change and re-run UPDATE_GOLDEN=1 after integration; the only delta is the added 'copp' section (core2: 2 classes, critical drops=4521).

FULL SUITE: 575 passed / 0 failed in the worktree (108s), including the regenerated golden, the new parser+detector tests, and the end-to-end pipeline/in-process tests. graphify was NOT refreshed (out of scope for a slice handed back to the orchestrator).

OPTIONAL FOLLOW-UP for the orchestrator (not done here, to keep the slice surgical): surface snap['copp'] in the not-collected/coverage scanner the way other axes are, and consider a workbook/explorer mirror — but those are downstream-deliverable wiring, beyond the parser+detector slice contract.

## sources
['https://www.cisco.com/c/en/us/support/docs/quality-of-service-qos/control-plane-policing/217946-verify-control-plane-policing-violations.html', 'https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus7000/sw/security/config/cisco_nexus7000_security_config_guide_8x/configuring_control_plane_policing.html', 'https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-18/configuration_guide/sec/b_1718_sec_9300_cg/configuring_control_plane_policing.html', 'https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/qos/b-quality-of-service/m_qos-plcshp-ctrl-pln-plc-0.html', 'https://interc0nnect.wordpress.com/2015/01/13/how-to-verify-copp-policy-and-drops-in-nx-os/', 'https://uni-koeln.de/~pbogusze/posts/NX-OS_Control_Plane_Policing.html']

## parser_code
```python
def parse_copp_drops(output: str) -> list:
    """'show policy-map interface control-plane' (NX-OS) / 'show policy-map control-plane' (IOS / IOS-XE)
    -> [{class, conformed, exceeded, violated, dropped, drops}] per CoPP class. `drops` = the total
    control-plane traffic DISCARDED by the policer for that class (exceeded + violated + dropped). A class
    with drops > 0 means the box is actively policing/dropping punted control-plane traffic -- a mistuned
    policer or a control-plane flood/CPU-pressure event (protocol packets can be silently starved).

    Counters are in PACKETS on IOS/IOS-XE ('conformed N packets, N bytes; actions: ...') and in BYTES on
    NX-OS ('conformed N bytes,' / 'dropped N bytes;' / 'violated N bytes,' under each 'module N :'); NX-OS
    module blocks are summed per class. The engine reports drops as a count (packets or bytes per platform);
    the firing condition is platform-agnostic (drops > 0), so the unit does not change the verdict. [] when
    no CoPP policy is applied (or the command is absent). Tolerant; never raises."""
    out: list = []
    cur: Optional[dict] = None

    def _flush():
        if cur is not None:
            cur["drops"] = cur["exceeded"] + cur["violated"] + cur["dropped"]
            out.append(cur)

    for raw in (output or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        # Class header. NX-OS: 'class-map NAME (match-any)'. IOS/IOS-XE: 'Class-map: NAME (match-any)'.
        h = re.match(r"^[Cc]lass-?map:?\s+(\S+)\s*\(match-", s)
        if h:
            _flush()
            cur = {"class": h.group(1), "conformed": 0, "exceeded": 0, "violated": 0, "dropped": 0, "drops": 0}
            continue
        if cur is None:
            continue
        # Skip the policer-RATE lines ('police cir 130 kbps bc 1000 ms') so the numbers in them are never
        # mistaken for counters; only count the conformed/exceeded/violated/dropped COUNTER lines.
        if re.match(r"^police\b", s, re.IGNORECASE):
            continue
        # First integer after the keyword = the counter (packets on IOS, bytes on NX-OS). The 'X-min ...
        # rate N bytes/sec' lines are rates, not cumulative counters -> excluded via the (?!...rate) guard.
        for key in ("conformed", "exceeded", "violated", "dropped"):
            m = re.match(rf"^{key}\s+(\d+)\s+(packets|bytes)\b", s, re.IGNORECASE)
            if m:
                cur[key] += int(m.group(1))
                break
    _flush()
    return out
```

## build_code
```python
def build_copp(cmd_to_file: Dict[str, str]) -> list:
    """Control-plane-policing (CoPP) drop state for THIS device from 'show policy-map interface
    control-plane' (NX-OS) or 'show policy-map control-plane' (IOS / IOS-XE), via parse_copp_drops:
    [{class, conformed, exceeded, violated, dropped, drops}] per CoPP class. [] when no CoPP policy is
    applied (or the command is absent). A class with drops > 0 means the box is actively policing/dropping
    punted control-plane traffic -- a mistuned policer or a control-plane flood starving the CPU (legitimate
    protocol packets can be silently discarded). Fail-soft via _safe_parse."""
    return _safe_parse(parse_copp_drops, _load_cmd_output(
        cmd_to_file, "show policy-map interface control-plane", "show policy-map control-plane")) or []

# NOTE: also add `parse_copp_drops` to build.py's `from cisco_toolkit.parse import (...)` block
# (added on the line that already imports parse_nve_peers, parse_evpn_summary, parse_nve_vni).
```

## signal_code
```python
# Inserted in _signals(snap) immediately after the nve_vni_down block (the overlay-adjacent group).
# _copp = snap.get("copp")  -> {host: [{class, drops, ...}]}
    # Control-plane policing (CoPP): a class with drops > 0 is actively discarding punted control-plane
    # traffic (mistuned policer, or a control-plane flood / CPU pressure). Coverage-honest: a class at
    # drops == 0 is NORMAL (policers are armed but not firing) and must NOT signal -- only a non-zero
    # discard counter does. "class" + first dropping class drive the device-attributed summary.
    _copp = snap.get("copp")
    copp_hits = []   # (host, class, drops) for classes actively dropping
    for _h, _cl in (_copp.items() if isinstance(_copp, dict) else []):
        for _c in _as_list(_cl):
            if _as_int(_c.get("drops")) > 0:
                copp_hits.append((_h, str(_c.get("class", "?")), _as_int(_c.get("drops"))))
    sig["copp_drop_classes"] = len(copp_hits)
    sig["copp_drop_pkts"] = sum(d for _, _, d in copp_hits)
    sig["copp_drop_hosts"] = sorted({h for h, _, _ in copp_hits})[:12]
    sig["copp_drop_examples"] = [f"{h} {cls}" for h, cls, _ in
                                 sorted(copp_hits, key=lambda t: -t[2])][:6]
```

## detector_code
```python
def _d_copp_drops(snap, sig):
    """Control-plane policing (CoPP/CPPr) actively DROPPING punted traffic: a CoPP class with a non-zero
    exceed/violate/drop counter (parse_copp_drops -> snap['copp']) means the policer is discarding traffic
    destined to the CPU -- either a mistuned policer clipping legitimate protocol traffic (BGP/OSPF/ARP/
    routing punts -> adjacency flaps, slow convergence) or a genuine control-plane flood / DoS starving the
    supervisor. Coverage-honest: an armed policer at drops == 0 is the NORMAL state and stays silent; this
    fires ONLY on observed non-zero discards, so it is a broken-state signal, not blanket absence."""
    n = sig.get("copp_drop_classes", 0)
    if n <= 0:
        return None
    egs = ", ".join(sig.get("copp_drop_examples") or [])
    return _decision(
        "copp-control-plane-policer-dropping",
        f"{n} control-plane-policing (CoPP) class(es) are actively dropping punted traffic"
        + (f" (e.g. {egs})" if egs else "")
        + f" -- {sig.get('copp_drop_pkts', 0)} total discarded. CoPP drops mean traffic destined to the "
        "CPU is being policed: either the policer is mistuned and clipping legitimate control-plane "
        "traffic (routing/ARP/management punts -> adjacency flaps, slow convergence) or a control-plane "
        "flood/DoS is starving the supervisor. Identify the dropping class, confirm whether the offered "
        "rate is legitimate, and re-baseline the policer (raise the CIR for that class) or trace and "
        "suppress the source before cutover.",
        n, ["availability", "security", "manageability"],
        ["copp[].drops (parse_copp_drops / show policy-map [interface] control-plane)",
         "copp[].exceeded", "copp[].violated"],
        priority="High",
        driver="Control-plane protection: a CoPP class dropping punted traffic either clips legitimate "
               "protocol packets (convergence/adjacency risk) or signals a control-plane flood; neither "
               "should be carried silently into a migration baseline.",
        devices=sig.get("copp_drop_hosts") or [])

# REGISTER in _DETECTORS (added next to _d_nve_peer_health):
# _DETECTORS = [_d_fhrp, _d_fhrp_state, _d_fhrp_resilience, _d_nve_peer_health, _d_evpn_rr_health,
#               _d_nve_vni_health, _d_copp_drops, _d_spof, ...]
```

## fixture_block
```python
    # CoPP drop state (universality): the control-plane policer is ACTIVELY DROPPING punted traffic on the
    # 'critical' class (violated 4521 bytes -> a mistuned policer or a control-plane flood) while 'normal' is
    # armed but clean (violated 0) -> _d_copp_drops fires on the dropping class only (coverage-honest: an
    # armed-but-not-firing policer is NORMAL and stays silent). The engine had no CoPP visibility before.
    "show policy-map interface control-plane": """\
Control Plane

  Service-policy input: copp-system-p-policy-strict

    class-map copp-system-p-class-critical (match-any)
      match access-group name copp-system-p-acl-bgp
      set cos 7
      police cir 36000 kbps bc 250 ms
        conform action: transmit
        violate action: drop
      module 1:
        conformed 177446058 bytes,
          5-min offered rate 3 bytes/sec
          peak rate 80 bytes/sec at Sat Apr 23 04:25:27 2022
        violated 4521 bytes,
          5-min violate rate 12 bytes/sec
          peak rate 96 bytes/sec
    class-map copp-system-p-class-normal (match-any)
      match access-group name copp-system-p-acl-arp
      police cir 680 kbps bc 250 ms
        conform action: transmit
        violate action: drop
      module 1:
        conformed 88231005 bytes,
          5-min offered rate 7 bytes/sec
        violated 0 bytes,
          5-min violate rate 0 bytes/sec
""",
```

## test_code
```python
# --- in tests/test_parsers.py (after test_parse_nve_vni_states) ---
def test_parse_copp_drops_nxos_and_iosxe(cp):
    """Universality (control-plane policing): the engine had no CoPP visibility. parse_copp_drops reads
    'show policy-map [interface] control-plane' on BOTH NX-OS (bytes, 'module N :' blocks, violated/dropped)
    and IOS/IOS-XE ('Class-map:', packets, exceeded/violated ... actions: drop) so a CoPP class actively
    DROPPING punted control-plane traffic (drops > 0) becomes detectable. `drops` = exceeded+violated+dropped;
    rate lines ('5-min violate rate ... bytes/sec') and the policer 'cir/bc' config line are never miscounted.
    Coverage-honest: an armed policer at drops == 0 reports a class with drops == 0 (NOT silence-as-health)."""
    # --- NX-OS: 'critical' actively dropping (violated 4521 bytes), 'normal' armed-but-clean (violated 0) ---
    nxos = (
        "    class-map copp-system-p-class-critical (match-any)\n"
        "      police cir 36000 kbps bc 250 ms\n"
        "      module 1:\n"
        "        conformed 177446058 bytes,\n"
        "          5-min offered rate 3 bytes/sec\n"
        "        violated 4521 bytes,\n"
        "          5-min violate rate 12 bytes/sec\n"
        "    class-map copp-system-p-class-normal (match-any)\n"
        "      module 1:\n"
        "        conformed 88231005 bytes,\n"
        "        violated 0 bytes,\n")
    r = parse.parse_copp_drops(nxos)
    by = {c["class"]: c for c in r}
    assert by["copp-system-p-class-critical"]["violated"] == 4521
    assert by["copp-system-p-class-critical"]["drops"] == 4521          # exceeded+violated+dropped
    assert by["copp-system-p-class-normal"]["drops"] == 0               # armed but not firing -> not a drop
    # the '5-min violate rate ... bytes/sec' line is a RATE, not the cumulative counter -> not added in
    assert by["copp-system-p-class-critical"]["conformed"] == 177446058

    # --- NX-OS older dialect: 'dropped N bytes' increments the drop counter ---
    nxos_old = (
        "class-map copp-class-critical (match-any)\n"
        "  police cir 19000 pps bc 128 packets\n"
        "  module 1 :\n"
        "  transmitted 1084573 bytes;\n"
        "  dropped 8800 bytes;\n")
    r2 = parse.parse_copp_drops(nxos_old)
    assert len(r2) == 1 and r2[0]["dropped"] == 8800 and r2[0]["drops"] == 8800

    # --- IOS / IOS-XE: 'Class-map:', packets, exceeded + violated both 'actions: drop' ---
    iosxe = (
        "    Class-map: copp-class-bgp (match-any)\n"
        "      120 packets, 7680 bytes\n"
        "      police:\n"
        "          cir 8000 bps, bc 1500 bytes\n"
        "        conformed 15 packets, 6210 bytes; actions: transmit\n"
        "        exceeded 5 packets, 5070 bytes; actions: drop\n"
        "        violated 2 packets, 140 bytes; actions: drop\n"
        "    Class-map: class-default (match-any)\n"
        "        conformed 0 packets, 0 bytes; actions: transmit\n"
        "        exceeded 0 packets, 0 bytes; actions: drop\n"
        "        violated 0 packets, 0 bytes; actions: drop\n")
    r3 = parse.parse_copp_drops(iosxe)
    byx = {c["class"]: c for c in r3}
    assert byx["copp-class-bgp"]["exceeded"] == 5 and byx["copp-class-bgp"]["violated"] == 2
    assert byx["copp-class-bgp"]["drops"] == 7
    assert byx["class-default"]["drops"] == 0
    # absent / non-CoPP output -> [] (coverage-honest: no policy applied is not a fabricated clean class)
    assert parse.parse_copp_drops("") == []
    assert parse.parse_copp_drops("% policy-map not configured\n") == []


# --- in tests/test_design_blueprint.py (after test_d_nve_peer_health_flags_down_vtep) ---
def test_d_copp_drops_fires_on_dropping_class_only():
    """Universality (control-plane policing): a CoPP class actively dropping punted traffic (drops > 0) fires
    _d_copp_drops; an armed-but-clean policer (every class drops == 0) and an ABSENT copp axis are both silent.
    Coverage-honest -- 'CoPP configured, nothing dropping' is the NORMAL state and must NOT cry wolf; only an
    observed non-zero discard counter signals. The engine had no CoPP visibility before this slice."""
    import cisco_toolkit.design_advisor as da
    dropping = {"copp": {"core2": [
        {"class": "copp-system-p-class-critical", "conformed": 177446058, "exceeded": 0,
         "violated": 4521, "dropped": 0, "drops": 4521},                                    # actively dropping
        {"class": "copp-system-p-class-normal", "conformed": 88231005, "exceeded": 0,
         "violated": 0, "dropped": 0, "drops": 0},                                          # armed, clean
    ]}}
    sig = da._signals(dropping)
    assert sig["copp_drop_classes"] == 1 and sig["copp_drop_pkts"] == 4521
    assert sig["copp_drop_hosts"] == ["core2"]
    assert sig["copp_drop_examples"] == ["core2 copp-system-p-class-critical"]
    dec = da._d_copp_drops(dropping, sig)
    assert dec is not None and "CoPP" in str(dec) and "dropping" in str(dec)
    assert "core2" in dec["evidence"]["devices"] and dec["priority"] == "High"
    # armed-but-clean policer (every class at drops == 0) -> SILENT (not a fabricated finding)
    clean = {"copp": {"core2": [{"class": "copp-system-p-class-critical", "conformed": 5, "exceeded": 0,
                                 "violated": 0, "dropped": 0, "drops": 0}]}}
    assert da._d_copp_drops(clean, da._signals(clean)) is None
    # absent copp axis -> SILENT (coverage-honest: 'not observed' is never 'healthy')
    assert da._d_copp_drops({}, da._signals({})) is None
```
