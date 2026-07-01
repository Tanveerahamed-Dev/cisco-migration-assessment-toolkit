## buildable
yes

## unit_tests_green
True

## firing_condition
snap['shadow_infra'] (built from already-collected CDP/LLDP detail, capability-filtered to switches/routers) contains at least one neighbour whose canonical hostname (_canon_host: FQDN/serial/case-stripped) is NOT in the assessed-host set (collected health_scores[].switch UNION inventoried devices keys). I.e. an INFRA neighbour (switch/router) that assessed devices see over CDP/LLDP but that was never inventoried/collected. Coverage-honest & non-cry-wolf: silent when the axis is absent, when every infra neighbour reconciles to an assessed device (even one advertised by its FQDN/serial), and when the only off-scan neighbours are edge devices (CDP Host/Phone/Trans-Bridge, LLDP T/W/S) — phones, APs and WLCs are excluded by capability so they can never trigger it. A device that is inventoried but uncollected is also NOT flagged (it is known). It is a discovery-completeness STATE (a real undocumented box in the production path), not blanket absence.

## collection_command
show cdp neighbors detail / show lldp neighbors detail (BOTH already in the base command lists — COLLECT_PARSE_V3_23_0.py lines ~491-492 and ~545-546; no new collection required, reuses the topology-discovery evidence)

## snapshot_axis
shadow_infra

## fixture_device
core2

## notes
BUILDABLE = yes. The commands are ALREADY collected (no new collection), and the firing condition is a clean broken-STATE (a real undocumented switch/router in the production path), not blanket absence — fully coverage-honest and non-cry-wolf.

CRITICAL no-cry-wolf finding (self-refutation caught a real bug): the engine's existing `infer_endpoint_type()` returns "Switch" for ANYTHING whose platform contains the bare word "cisco" — including `Cisco IP Phone 8845` and `cisco AIR-AP...`. Using it as a positive infra signal made the fixture's phone and AP fire as shadow infra. Fixed by making _neighbor_is_infra treat advertised CAPABILITIES as authoritative (Host/Phone/Trans-Bridge/T/W -> never infra) and only falling back to a NARROW explicit switch/router model-family regex (_INFRA_PLATFORM_RE, which excludes 'IP Phone'/'AIR-AP') when capabilities are absent. Edge-case tested 20+ platform strings both directions (every switch/router family matches; every phone/AP/WLC/server excluded).

Coverage-honesty refutation (all pass): in-scope FQDN+serial neighbour -> silent (canon-match guard load-bearing); inventoried-but-uncollected device -> silent (known, not shadow); axis absent -> silent; only edge neighbours off-scan -> silent (capability filter at build).

KB DECISION: I registered the principle 'discover-undocumented-infrastructure-before-cutover' in design_kb as engine_actionable=True (domain 'operations', a pre-existing valid domain), which is STRICTLY RICHER than the reference multi-arch detectors (vxlan-nve-peer-down / fhrp-resilience-tracking-and-preempt are NOT in the KB and render with pid-as-title/empty-citation). Because it is engine_actionable=True, I had to (a) extend _maximal_snap() with a firing shadow_infra axis and (b) add an end-to-end assertion in test_pipeline_inprocess so the emit-invariant test_every_engine_actionable_principle_is_emitted stays green — both done.

SSOT: snap['shadow_infra'] is the Python-canonical version of the explorer's existing client-side `offscan`/`ghosts` derivation. The design blueprint now reads it from one source. The raw axis is kept in the embedded explorer payload (consistent with overlay/fhrp_detail, which _slim_for_embed also keeps); per-device infra-neighbour counts are small/bounded (a switch has a handful of switch/router uplinks), so the payload stays lean.

VALIDATION: full suite 577 passed (was 575; +2 parser, +2 classifier/detector tests, some co-located). Golden regenerated via UPDATE_GOLDEN=1 — the ONLY new top-level snapshot key is 'shadow_infra'; the other golden deltas (core2 capacity/physical_health/devices.total_ports/architecture_review) are the correct downstream effect of the 3 new CDP neighbour entries in the fixture, verified by diff. graphify refreshed (python -m graphify update .).

WORKTREE NOTE: the worktree was checked out at 1a7f889 (an older commit) but the prompt's reference slices live at fa9739e; I checked out fa9739e (where build_fhrp_detail/build_overlay/_d_fhrp_resilience/parse_hsrp_detail/parse_nve_peers/parse_evpn_summary all exist) before replicating, so the slice integrates against the correct base the orchestrator's main tree is on.

FILES TOUCHED (all absolute under the worktree root ...\.claude\worktrees\wf_b61a3107-d35-6): cisco_toolkit\parse.py (parse_neighbors_detail), cisco_toolkit\build.py (_INFRA_PLATFORM_RE, _neighbor_is_infra, build_undocumented_neighbors + import), cisco_toolkit\design_advisor.py (_signals shadow block, _d_shadow_infra, _DETECTORS), cisco_toolkit\design_kb.py (_SHADOW_INFRA_ADDENDUM), COLLECT_PARSE_V3_23_0.py (import + all_shadow_infra accumulate/publish snap['shadow_infra']), tests\synthetic_fixtures.py, tests\test_parsers.py, tests\test_design_blueprint.py (+_maximal_snap), tests\test_pipeline_inprocess.py, tests\golden\snapshot.json.

## sources
['https://www.cisco.com/c/en/us/support/docs/network-management/discovery-protocol-cdp/118736-technote-cdp-00.html (CDP capability TLVs: AP advertises Trans-Bridge 0x02, WLC advertises Host 0x10)', "https://itexamanswers.net/show-cdp-neighbors-detail-command-on-cisco-router-switch.html ('show cdp neighbors detail' format: 'Platform: ..., Capabilities: Router Switch IGMP' full words on one line)", "https://study-ccna.com/link-layer-discovery-protocol-lldp/ ('show lldp neighbors detail' format: 'System Capabilities:'/'Enabled Capabilities:' single letters e.g. R; legend (R)Router (B)Bridge (T)Telephone (W)WLAN-AP (S)Station)", 'https://www.cisco.com/c/en/us/td/docs/iosxr/ncs5000/interfaces/710x/b-interfaces-hardware-component-cg-ncs5000-710x/configuring-lldp.html (LLDP capability bit map: AP sets WLAN-AP bit only, all others 0; IP phone sets Telephone; switch sets Bridge and/or Router)', 'https://www.cisco.com/E-Learning/bulk/public/tac/cim/cib/using_cisco_ios_software/cmdrefs/show_cdp_neighbors.htm (CDP capability code legend R/T/B/S/H/I/r/P)']

## parser_code
```python
# CDP advertises capabilities as FULL WORDS on the Platform line ("Capabilities: Router Switch IGMP");
# LLDP advertises them as SINGLE LETTERS in "Enabled Capabilities: B,R". The infra-vs-edge distinction is
# carried ENTIRELY by these codes, which the brief parsers above DROP -- a switch/router is Switch/Router (CDP)
# or B/R (LLDP, Bridge/Router), while an access point is Trans-Bridge (CDP) / W (LLDP), an IP phone is Phone /
# T, and a WLC/server is Host. Capturing the raw capability string is what lets the shadow-infra detector tell
# an undocumented DISTRIBUTION SWITCH from a CDP-speaking phone or AP (no cry-wolf).
#   CDP codes: R Router, T Trans-Bridge, B Source-Route-Bridge, S Switch, H Host, I IGMP, r Repeater, P Phone.
#   LLDP codes: R Router, B Bridge, T Telephone, C DOCSIS, W WLAN-AP, P Repeater, S Station, O Other.
def parse_neighbors_detail(output: str, proto: str = "cdp") -> List[Dict[str, str]]:
    """'show cdp neighbors detail' (proto='cdp') / 'show lldp neighbors detail' (proto='lldp') ->
    [{device_id, platform, capabilities, mgmt_ip, local_intf, remote_port, proto}] -- ONE record per
    discovered neighbour, KEEPING the capability codes the topology-link parsers discard. `capabilities`
    is the raw advertised string (CDP full words / LLDP letters) so a consumer can classify infra (Switch/
    Router) vs edge (phone/AP/host) reliably. [] on empty / unrecognised input; tolerant, never raises.
    Reuses the already-collected CDP/LLDP detail (no new command)."""
    out: List[Dict[str, str]] = []
    if not output:
        return out
    if (proto or "").lower() == "lldp":
        # LLDP detail: per-neighbour blocks keyed by 'Local Intf:'; Enabled Capabilities preferred over System.
        for ch in re.split(r"\n\s*Local Intf:\s*", "\n" + output):
            ch = ch.strip()
            if not ch:
                continue
            local = normalize_ifname(ch.splitlines()[0].strip().split()[0])
            rec = {"device_id": "", "platform": "", "capabilities": "", "mgmt_ip": "",
                   "local_intf": local, "remote_port": "", "proto": "lldp"}
            sys_caps = ""
            for line in ch.splitlines():
                ls = line.strip()
                m = re.match(r"^System Name:\s*(.+)$", ls, re.IGNORECASE)
                if m:
                    rec["device_id"] = m.group(1).strip()
                m = re.match(r"^Port id:\s*(.+)$", ls, re.IGNORECASE)
                if m and not rec["remote_port"]:
                    rec["remote_port"] = normalize_ifname(m.group(1).strip())
                m = re.match(r"^System Description:\s*(.+)$", ls, re.IGNORECASE)
                if m and not rec["platform"]:
                    rec["platform"] = m.group(1).strip()
                m = re.match(r"^Enabled Capabilities:\s*(.+)$", ls, re.IGNORECASE)
                if m:
                    rec["capabilities"] = m.group(1).strip()
                m = re.match(r"^System Capabilities:\s*(.+)$", ls, re.IGNORECASE)
                if m:
                    sys_caps = m.group(1).strip()
                m = re.search(r"\b(\d+\.\d+\.\d+\.\d+)\b", ls)
                if m and not rec["mgmt_ip"] and "management" in ls.lower():
                    rec["mgmt_ip"] = m.group(1)
            if not rec["capabilities"]:
                rec["capabilities"] = sys_caps   # fall back to advertised (vs enabled) caps
            caps = rec["capabilities"].upper().replace("N/A", "").strip()
            if local and (rec["device_id"] or caps):
                out.append(rec)
        return out
    # CDP detail: '----' separated sections; Platform + Capabilities share one line.
    for sec in re.split(r"-{5,}", output):
        sec = sec.strip()
        if not sec:
            continue
        rec = {"device_id": "", "platform": "", "capabilities": "", "mgmt_ip": "",
               "local_intf": "", "remote_port": "", "proto": "cdp"}
        for line in sec.splitlines():
            ls = line.strip()
            if ls.lower().startswith("device id:"):
                rec["device_id"] = ls.split(":", 1)[1].strip()
            pm = re.match(r"^Platform:\s*(.*)$", ls, re.IGNORECASE)
            if pm:
                body = pm.group(1)
                cm = re.search(r"Capabilities:\s*(.+)$", body, re.IGNORECASE)
                if cm:
                    rec["capabilities"] = cm.group(1).strip()
                rec["platform"] = re.split(r",\s*Capabilities", body, 1)[0].strip()
            ipm = re.search(r"\bip address:\s*(\d+\.\d+\.\d+\.\d+)\b", ls, re.IGNORECASE)
            if ipm and not rec["mgmt_ip"]:
                rec["mgmt_ip"] = ipm.group(1)
            if ls.lower().startswith("interface:"):
                mv = re.search(r"Interface:\s*([^,]+)", ls, re.IGNORECASE)
                if mv:
                    rec["local_intf"] = normalize_ifname(mv.group(1).strip())
                pp = re.search(r"Port ID\s*\(outgoing port\):\s*(\S+)", ls, re.IGNORECASE)
                if pp:
                    rec["remote_port"] = normalize_ifname(pp.group(1).strip())
        if rec["device_id"] or rec["capabilities"]:
            out.append(rec)
    return out
```

## build_code
```python
# Explicit switch/router model families, used ONLY when a neighbour advertises no capabilities (a bare
# LLDP neighbour). Deliberately NARROW -- it must NOT match a Cisco IP phone ('Cisco IP Phone 8845') or
# access point ('AIR-AP...'), so we do NOT key off the bare word 'cisco' the way infer_endpoint_type does
# (that maps every Cisco-branded box, phones and APs included, to 'Switch' -> a cry-wolf source here).
_INFRA_PLATFORM_RE = re.compile(
    r"(\bnexus|\bcatalyst|\bn[0-9]k\b|\bc9[0-9]{3}|\bc3[0-9]{3}|\bc2[0-9]{3}|\bws-c[23456]|"
    r"\basr[0-9]|\bisr[0-9]|\bcsr[0-9]|\bncs[- ]?[0-9]|\bcisco[ -][0-9]{4}\b)", re.IGNORECASE)


def _neighbor_is_infra(rec: Dict[str, str]) -> bool:
    """Classify a CDP/LLDP neighbour record (parse_neighbors_detail) as INFRASTRUCTURE (a switch/router in
    the L2/L3 path) vs an EDGE device (phone / access-point / host / WLC). The distinction is AFFIRMATIVE and
    deliberately conservative so the shadow-infra detector never cries wolf over a CDP-speaking phone or AP.
    The advertised CAPABILITIES are AUTHORITATIVE when present (a device that says it is a phone/AP/host is
    not silently re-read as a switch via its platform string):
      * CDP capabilities (full words): infra iff 'Switch' or 'Router' appears. Trans-Bridge alone = AP,
        Host alone = WLC/server, Phone = IP phone -> NOT infra.
      * LLDP enabled-capabilities (letters): infra iff 'R' (Router) or 'B' (Bridge) is set AND 'W' (WLAN-AP)
        is NOT (an AP sets only W; a switch advertises B). A phone sets only T.
      * Only when NO capabilities are advertised (a bare neighbour) do we fall back to an explicit
        switch/router PLATFORM family (_INFRA_PLATFORM_RE) -- never the greedy 'cisco'-substring rule, which
        would classify a Cisco phone/AP as a switch.
    A neighbour with neither an infra capability nor an infra platform is treated as NON-infra (unknown is
    never assumed to be a switch)."""
    caps = (rec.get("capabilities") or "").strip()
    proto = (rec.get("proto") or "cdp").lower()
    if caps:
        if proto == "lldp":
            tokens = {t.strip().upper() for t in re.split(r"[,\s]+", caps) if t.strip()}
            return ("R" in tokens or "B" in tokens) and "W" not in tokens
        low = caps.lower()
        return bool(re.search(r"\bswitch\b", low) or re.search(r"\brouter\b", low))
    # No advertised capabilities: fall back to an explicit infra platform family only.
    return bool(_INFRA_PLATFORM_RE.search(rec.get("platform", "") or ""))


def build_undocumented_neighbors(cmd_to_file: Dict[str, str]) -> list:
    """INFRASTRUCTURE CDP/LLDP neighbours of THIS device, parsed from the already-collected
    'show cdp neighbors detail' + 'show lldp neighbors detail' (parse_neighbors_detail) and filtered to
    switches/routers via _neighbor_is_infra. Returns [{device_id, platform, capabilities, mgmt_ip,
    local_intf, remote_port, proto}] -- the candidate set the shadow-infra detector reconciles against the
    assessed inventory (a candidate whose canonical hostname is NOT an assessed device = undocumented /
    shadow infrastructure carrying production traffic outside the migration scope). Edge devices (phones /
    APs / hosts) are excluded here. [] when the device advertises no infra neighbour. No NEW collected
    command (reuses the topology CDP/LLDP detail). Fail-soft via _safe_parse."""
    cdp = _safe_parse(parse_neighbors_detail, _load_cmd_output(cmd_to_file, "show cdp neighbors detail"), "cdp") or []
    lldp = _safe_parse(parse_neighbors_detail, _load_cmd_output(cmd_to_file, "show lldp neighbors detail"), "lldp") or []
    out = []
    seen = set()
    for rec in list(cdp) + list(lldp):
        if not _neighbor_is_infra(rec):
            continue
        key = ((rec.get("device_id") or "").strip().lower(), (rec.get("local_intf") or "").lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)
    return out

# NOTE: add `parse_neighbors_detail` to build.py's `from cisco_toolkit.parse import (...)` block
# (next to parse_neighbors_cdp, parse_neighbors_lldp). `infer_endpoint_type` is already imported and
# still used by build_interfaces; _neighbor_is_infra deliberately does NOT use it (it is too greedy).
```

## signal_code
```python
# --- insert inside _signals(snap), immediately after the nve_vni_down block (before `devs = []`) ---
    # SHADOW INFRASTRUCTURE (snap['shadow_infra'] from build_undocumented_neighbors): an INFRA neighbour
    # (switch/router, by capability/platform) that real assessed devices see over CDP/LLDP but whose
    # canonical hostname is NOT in the assessed inventory -> an undocumented box in the production L2/L3
    # path, outside the migration scope. Reconcile here against the assessed-host set (collected +
    # inventoried), canon-normalising names exactly as the topology map does (strip FQDN/serial/case) so a
    # neighbour advertised by its FQDN is NOT mis-flagged. Coverage-honest: empty when no CDP/LLDP infra
    # neighbour is undocumented.
    try:
        from .analyze import _canon_host as _ch
    except Exception:
        def _ch(_n):
            import re as _re
            _n = _re.sub(r"\(.*?\)\s*$", "", str(_n or "").strip()).strip().split(".")[0]
            return _n.lower()
    _assessed = set()
    for _r in _as_list(snap.get("health_scores")):           # collected (first-hand) devices
        _hh = _ch((_r or {}).get("switch"))
        if _hh:
            _assessed.add(_hh)
    for _hk in _as_dict(snap.get("devices")):                 # inventoried devices (known, even if uncollected)
        _ck = _ch(_hk)
        if _ck:
            _assessed.add(_ck)
    _shadow: dict = {}
    _si = snap.get("shadow_infra")
    for _host, _recs in (_si.items() if isinstance(_si, dict) else []):
        for _n in _as_list(_recs):
            _did = (_n.get("device_id") or "").strip()
            _cn = _ch(_did)
            if not _cn or _cn in _assessed:                  # blank id, or a known/assessed device -> not shadow
                continue
            _e = _shadow.setdefault(_cn, {"name": _did, "platform": _n.get("platform", ""),
                                          "proto": _n.get("proto", ""), "seen_from": set(), "via": []})
            _e["seen_from"].add(_host)
            _lp = (_n.get("local_intf") or "?")
            _via = f"{_host}:{_lp}"
            if _via not in _e["via"]:
                _e["via"].append(_via)
            if not _e["platform"] and _n.get("platform"):
                _e["platform"] = _n.get("platform")
    sig["shadow_infra"] = [
        {"name": v["name"], "platform": v["platform"], "proto": v["proto"],
         "n_attach": len(v["seen_from"]), "seen_from": sorted(v["seen_from"]), "via": v["via"][:6]}
        for _k, v in sorted(_shadow.items())
    ]
    sig["shadow_infra_devices"] = sorted({h for v in _shadow.values() for h in v["seen_from"]})[:12]
```

## detector_code
```python
def _d_shadow_infra(snap, sig):
    """UNDOCUMENTED (shadow) infrastructure: a switch/router that assessed devices SEE over CDP/LLDP but that
    is NOT in the assessment inventory -> a box in the production L2/L3 path the migration neither inventoried,
    hardened, lifecycle-checked, nor planned a cutover for. It is an unmanaged failure domain and a scope
    blind-spot: its uplinks, redundancy and EoL status are unknown, and a wave that depends on it can break.
    Coverage-honest: built from collected CDP/LLDP detail and reconciled against the assessed inventory by
    canonical hostname (FQDN/serial/case-normalised exactly like the topology map), so an in-scope neighbour
    advertised under its FQDN is NOT mis-flagged; silent when every infra neighbour is an assessed device."""
    shadow = sig.get("shadow_infra") or []
    if not shadow:
        return None
    names = [s["name"] for s in shadow]
    return _decision(
        "discover-undocumented-infrastructure-before-cutover",
        f"{len(shadow)} undocumented infrastructure neighbour(s) (switch/router) are visible over CDP/LLDP "
        f"but absent from the assessed inventory: {', '.join(names[:8])}"
        + (f" (+{len(names) - 8} more)" if len(names) > 8 else "")
        + ". Each is an unmanaged device in the production path -- its uplinks, redundancy, software and "
        "end-of-support state are UNKNOWN, and a cutover wave that traverses it can fail silently. Add every "
        "shadow node to the inventory and collect it (or formally scope it out with the customer) before "
        "baselining the design.",
        len(shadow), ["availability", "manageability"],
        ["shadow_infra[].name (build_undocumented_neighbors / show cdp|lldp neighbors detail)",
         "shadow_infra[].seen_from", "shadow_infra[].via"],
        priority="High",
        driver="Coverage / blast radius: an un-inventoried switch or router in the data path is a migration "
               "blind-spot -- you cannot assess the resilience of, or safely cut over around, a device you "
               "have not collected.",
        devices=sig.get("shadow_infra_devices") or [])

# Register in _DETECTORS (placed right after _d_nve_vni_health):
# _DETECTORS = [_d_fhrp, _d_fhrp_state, _d_fhrp_resilience, _d_nve_peer_health, _d_evpn_rr_health,
#               _d_nve_vni_health, _d_shadow_infra, _d_spof, _d_eol, ...]
#
# KB PRINCIPLE (append to design_kb.py after `DOCTRINE.extend(_ACTIONABLE_DETECTOR_ADDENDUM_2)`), so the
# decision renders with a real title/citation/recommended_action and the emit-invariant stays satisfied:
# _SHADOW_INFRA_ADDENDUM = [{
#   "id": "discover-undocumented-infrastructure-before-cutover",
#   "title": "Discover and inventory undocumented (shadow) infrastructure before baselining the design",
#   "domain": "operations", "priority": "High", "engine_actionable": True,
#   "design_intent": "...CDP/LLDP discovery is the cross-check that the device inventory is COMPLETE; an
#       infra neighbour absent from the inventory is undocumented 'shadow' infrastructure in the path...",
#   "observable": "shadow_infra axis lists, per shadow node, advertised name/platform + the assessed devices
#       and ports that see it, capability-filtered to switches/routers and reconciled by canonical hostname.",
#   "trigger": "snap['shadow_infra'] is non-empty (an infra-capable CDP/LLDP neighbour whose canonical
#       hostname is not an assessed device).",
#   "recommended_action": "Identify each shadow node from the advertising device+port and its CDP/LLDP
#       platform/mgmt IP, then add it to the inventory and collect it (or formally scope it out WITH the
#       customer and record it). Re-run discovery until every infra neighbour reconciles, then freeze the
#       baseline.",
#   "alternatives": "Proceed on the partial inventory and discover the device during cutover (cheapest now,
#       but the wave starts blind to a live dependency)...",
#   "tradeoffs": "Chasing every neighbour costs discovery time, but it is the only way the inventory -- and
#       the hardening/lifecycle/cutover plans built on it -- is provably complete rather than silently partial.",
#   "citation": "Cisco Discovery Protocol (CDP) and IEEE 802.1AB LLDP neighbour-discovery capability codes
#       (Switch/Router vs Trans-Bridge/Host/Phone); Cisco PPDIOO Prepare/Plan network-discovery & inventory
#       completeness practice (the inventory must reconcile with discovered topology).",
# }]
# DOCTRINE.extend(_SHADOW_INFRA_ADDENDUM)
```

## fixture_block
```python
## Replace core2's existing "show cdp neighbors detail" block in tests/synthetic_fixtures.py (the _CORE2
## dict). core1.lab is assessed (in scan); wan-edge-rtr1.lab is an infra ROUTER not in inventory -> fires
## _d_shadow_infra. The phone (Host Phone) and AP (Trans-Bridge) are EDGE devices -> must be IGNORED.
    # core1.lab is an assessed device (in scan); wan-edge-rtr1.lab is an INFRA router (Capabilities: Router)
    # that is NOT in the inventory -> undocumented 'shadow' infrastructure -> _d_shadow_infra fires. The
    # CDP-speaking IP phone (Host Phone) and access point (Trans-Bridge) are EDGE devices and must be IGNORED
    # by the infra filter (no cry-wolf over phones/APs).
    "show cdp neighbors detail": """\
----------------------------------------
Device ID: core1.lab
  IP address: 10.0.99.1
Platform: cisco WS-C3850-24T,  Capabilities: Router Switch
Interface: port-channel1,  Port ID (outgoing port): Port-channel1
----------------------------------------
Device ID: wan-edge-rtr1.lab
  IP address: 10.0.250.1
Platform: cisco ASR1001-X,  Capabilities: Router
Interface: Ethernet1/47,  Port ID (outgoing port): GigabitEthernet0/0/1
----------------------------------------
Device ID: SEP00112233AABB
  IP address: 10.0.40.20
Platform: Cisco IP Phone 8845,  Capabilities: Host Phone
Interface: Ethernet1/20,  Port ID (outgoing port): Port 1
----------------------------------------
Device ID: AP-floor3-01
  IP address: 10.0.50.30
Platform: cisco AIR-AP2802I-B-K9,  Capabilities: Trans-Bridge
Interface: Ethernet1/30,  Port ID (outgoing port): GigabitEthernet0
""",
## NOTE: adding these CDP entries grows core2's interface table (the existing parse_neighbors_cdp learns
## Eth1/47, Eth1/20, Eth1/30 as ports), so the golden snapshot's core2 capacity/physical_health/total_ports
## shift accordingly (port_util 100%->40%, total_ports 2->5). That is correct downstream behaviour of adding
## real neighbour evidence; regen the golden with UPDATE_GOLDEN=1. The phone/AP intentionally remain so the
## in-process test proves the no-cry-wolf exclusion end-to-end. The single NEW snapshot top-level key is
## 'shadow_infra'.
```

## test_code
```python
# --- in tests/test_parsers.py (parser tests) ---
def test_parse_neighbors_detail_cdp_keeps_capabilities(cp):
    """Shadow-infra discovery: parse_neighbors_detail reads 'show cdp neighbors detail' and KEEPS the
    capability words the topology-link parser discards (Router/Switch vs Trans-Bridge/Host/Phone) so an
    undocumented switch/router can be told apart from a CDP-speaking phone or AP. [] on empty."""
    out = (
        "-------------------------\n"
        "Device ID: dist-core-7.lab\n"
        "  IP address: 10.0.0.7\n"
        "Platform: cisco N9K-C93180YC-EX,  Capabilities: Router Switch\n"
        "Interface: Ethernet1/47,  Port ID (outgoing port): Ethernet1/1\n"
        "-------------------------\n"
        "Device ID: SEP00112233AABB\n"
        "  IP address: 10.0.40.20\n"
        "Platform: Cisco IP Phone 8845,  Capabilities: Host Phone\n"
        "Interface: GigabitEthernet1/0/20,  Port ID (outgoing port): Port 1\n")
    r = parse.parse_neighbors_detail(out, "cdp")
    assert len(r) == 2
    assert r[0]["device_id"] == "dist-core-7.lab" and r[0]["capabilities"] == "Router Switch"
    assert r[0]["platform"] == "cisco N9K-C93180YC-EX" and r[0]["local_intf"] == "Eth1/47"
    assert r[0]["remote_port"] == "Eth1/1" and r[0]["mgmt_ip"] == "10.0.0.7" and r[0]["proto"] == "cdp"
    assert r[1]["device_id"] == "SEP00112233AABB" and r[1]["capabilities"] == "Host Phone"
    assert parse.parse_neighbors_detail("", "cdp") == []


def test_parse_neighbors_detail_lldp_enabled_capabilities(cp):
    """LLDP detail: parse_neighbors_detail prefers the single-letter 'Enabled Capabilities' (B/R = switch/
    router, W = AP, T = phone) and falls back to 'System Capabilities'. [] on empty."""
    out = (
        "Local Intf: Gi1/0/47\n"
        "Chassis id: 00aa.bbcc.ddee\n"
        "Port id: Gi1/0/1\n"
        "System Name: agg-sw-2\n"
        "System Description: Cisco IOS Software, C9300\n"
        "System Capabilities: B,R\n"
        "Enabled Capabilities: B,R\n"
        "Management Addresses:\n"
        "  IP: 10.0.0.8\n"
        "\n"
        "Local Intf: Gi1/0/20\n"
        "Port id: 1\n"
        "System Name: phone-2\n"
        "System Capabilities: T\n"
        "Enabled Capabilities: T\n")
    r = parse.parse_neighbors_detail(out, "lldp")
    assert len(r) == 2
    assert r[0]["device_id"] == "agg-sw-2" and r[0]["capabilities"] == "B,R"
    assert r[0]["local_intf"] == "Gi1/0/47" and r[0]["remote_port"] == "Gi1/0/1" and r[0]["proto"] == "lldp"
    assert r[1]["device_id"] == "phone-2" and r[1]["capabilities"] == "T"
    assert parse.parse_neighbors_detail("", "lldp") == []


# --- in tests/test_design_blueprint.py (classifier + detector tests) ---
def test_neighbor_is_infra_excludes_phones_aps_hosts():
    """No-cry-wolf classifier: _neighbor_is_infra accepts only switches/routers (CDP Switch/Router words,
    LLDP B/R letters, or a switch/router platform) and REJECTS IP phones (CDP 'Host Phone' / LLDP 'T'),
    access points (CDP 'Trans-Bridge' / LLDP 'W') and WLCs/servers (CDP 'Host'). A neighbour with neither an
    infra capability nor an infra platform is NOT assumed to be infra."""
    from cisco_toolkit.build import _neighbor_is_infra
    assert _neighbor_is_infra({"capabilities": "Router Switch", "proto": "cdp"}) is True
    assert _neighbor_is_infra({"capabilities": "Router", "proto": "cdp"}) is True
    assert _neighbor_is_infra({"capabilities": "B,R", "proto": "lldp"}) is True
    assert _neighbor_is_infra({"capabilities": "", "platform": "cisco N9K-C93180YC-EX", "proto": "lldp"}) is True
    assert _neighbor_is_infra({"capabilities": "Host Phone", "proto": "cdp"}) is False
    assert _neighbor_is_infra({"capabilities": "Trans-Bridge", "proto": "cdp"}) is False   # access point
    assert _neighbor_is_infra({"capabilities": "Host", "proto": "cdp"}) is False            # WLC / server
    assert _neighbor_is_infra({"capabilities": "T", "proto": "lldp"}) is False              # phone
    assert _neighbor_is_infra({"capabilities": "W", "proto": "lldp"}) is False              # AP (W only)
    assert _neighbor_is_infra({"capabilities": "W,B", "proto": "lldp"}) is False            # AP advertising bridge -> excluded
    assert _neighbor_is_infra({"capabilities": "", "platform": "", "device_id": "x", "proto": "cdp"}) is False


def test_d_shadow_infra_flags_undocumented_switch_router_only():
    """Undocumented (shadow) infrastructure: an infra CDP/LLDP neighbour whose canonical hostname is NOT an
    assessed device fires _d_shadow_infra. Coverage-honest: an in-scope neighbour (even advertised by its
    FQDN/serial) does NOT fire, and the axis being absent is silent. The detector reconciles by canonical
    hostname exactly like the topology map (FQDN/serial/case-normalised)."""
    import cisco_toolkit.design_advisor as da
    snap = {
        "health_scores": [{"switch": "core1"}, {"switch": "core2"}],
        "devices": {"core1": {"hostname": "core1"}, "core2": {"hostname": "core2"}},
        "shadow_infra": {
            "core2": [
                {"device_id": "wan-edge-rtr1.lab", "platform": "cisco ASR1001-X", "capabilities": "Router",
                 "proto": "cdp", "local_intf": "Eth1/47"},
                {"device_id": "core1.lab(FOC1234ABCD)", "platform": "cisco WS-C3850", "capabilities": "Router Switch",
                 "proto": "cdp", "local_intf": "Po1"},
            ]
        },
    }
    sig = da._signals(snap)
    names = [s["name"] for s in sig["shadow_infra"]]
    assert names == ["wan-edge-rtr1.lab"]                     # only the undocumented one
    assert sig["shadow_infra"][0]["seen_from"] == ["core2"] and sig["shadow_infra"][0]["via"] == ["core2:Eth1/47"]
    assert sig["shadow_infra_devices"] == ["core2"]
    dec = da._d_shadow_infra(snap, sig)
    assert dec is not None and "undocumented infrastructure" in str(dec) and "wan-edge-rtr1.lab" in str(dec)
    assert dec["priority"] == "High" and dec["principle"]["id"] == "discover-undocumented-infrastructure-before-cutover"
    clean = {"health_scores": [{"switch": "core1"}, {"switch": "core2"}], "devices": {},
             "shadow_infra": {"core2": [{"device_id": "core1.lab", "capabilities": "Router Switch",
                                         "proto": "cdp", "local_intf": "Po1"}]}}
    assert da._d_shadow_infra(clean, da._signals(clean)) is None
    assert da._d_shadow_infra({}, da._signals({})) is None

# --- ALSO extend tests/test_design_blueprint.py::_maximal_snap() with a firing shadow_infra axis so the
#     engine_actionable emit-invariant stays green (the principle is engine_actionable=True): ---
#   shadow_infra={"d0": [{"device_id": "wan-edge-rtr1.corp", "platform": "cisco ASR1001-X",
#                         "capabilities": "Router", "proto": "cdp", "local_intf": "Gi0/0/0",
#                         "mgmt_ip": "10.0.0.254", "remote_port": "Gi0/0/1"}]},
# --- and add an end-to-end assertion block in tests/test_pipeline_inprocess.py after the VXLAN-VNI check
#     (proves snap['shadow_infra'] published, the fixture's wan-edge-rtr1.lab fires, and the phone/AP/core1
#     are excluded). All run green (577 passed).
```
