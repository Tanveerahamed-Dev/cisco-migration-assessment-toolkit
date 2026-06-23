"""Pure show-command parsers + column primitives. Depends only on `re`, stdlib
typing, and cisco_toolkit.textutils (the leaf layer). Extracted verbatim from
COLLECT_PARSE_V3_23_0.py in PHASE 2.7 step 2 (behaviour byte-identical)."""
import json
import logging
import re
from typing import Dict, List, Optional, Tuple

from cisco_toolkit.textutils import (
    normalize_ifname, is_valid_iface, normalize_status, normalize_duplex, normalize_speed,
    normalize_mac, IFACE_TOKEN_RE, VALID_IFACE_RE, PHYSICAL_IFACE_RE,
)

logger = logging.getLogger(__name__)   # NEW-V3.23.17: parse_show_environment_power emits a debug breadcrumb


def extract_fixed_cols(header_line: str, keys: List[Tuple[str,str]]) -> Dict[str, Tuple[int, Optional[int]]]:
    pos = {}
    for needle, name in keys:
        p = header_line.find(needle)
        if p >= 0: pos[name] = p
    items = sorted(pos.items(), key=lambda x: x[1])
    ranges = {}
    for i, (name, start) in enumerate(items):
        end = items[i+1][1] if i < len(items)-1 else None
        ranges[name] = (start, end)
    return ranges

def slice_col(line: str, start: int, end: Optional[int]) -> str:
    return line[start:].strip() if end is None else line[start:end].strip()


def parse_ospf_neighbors(output: str) -> List[Dict[str, str]]:
    """'show ip ospf neighbor' -> [{neighbor, state, address, interface}]."""
    rows = []
    for line in output.splitlines():
        m = re.match(r"\s*(\d+\.\d+\.\d+\.\d+)\s+\d+\s+(\S+)\s+\S+\s+(\d+\.\d+\.\d+\.\d+)\s+(\S+)", line)
        if m:
            rows.append({"neighbor": m.group(1), "state": m.group(2),
                         "address": m.group(3), "interface": normalize_ifname(m.group(4))})
    return rows

def parse_eigrp_neighbors(output: str) -> List[Dict[str, str]]:
    """'show ip eigrp neighbors' -> [{neighbor, interface, state}]."""
    rows = []
    for line in output.splitlines():
        m = re.match(r"\s*\d+\s+(\d+\.\d+\.\d+\.\d+)\s+(\S+)\s+\d+\s+(\S+)", line)
        if m:
            rows.append({"neighbor": m.group(1), "interface": normalize_ifname(m.group(2)),
                         "state": f"up {m.group(3)}"})
    return rows

def parse_bgp_summary(output: str) -> List[Dict[str, str]]:
    """'show ip bgp summary' / 'show bgp summary' -> [{neighbor, as, state}].
    Last column (State/PfxRcd) is the established state or the prefix count."""
    rows = []
    for line in output.splitlines():
        m = re.match(r"\s*(\d+\.\d+\.\d+\.\d+|[0-9A-Fa-f:]+:[0-9A-Fa-f:]+)\s+\d+\s+(\d+)\s+.*\s(\S+)\s*$", line)
        if m:
            rows.append({"neighbor": m.group(1), "as": m.group(2), "state": m.group(3)})
    return rows


def parse_bgp_table(output: str) -> List[str]:
    """NEW-V3.23.97: 'show ip bgp' / 'show bgp ipv4 unicast' -> sorted distinct IPv4 prefixes in the
    BGP RIB (what this device learned via BGP = its received/best prefixes). [] when absent/empty.
    Tolerant of the leading status codes (*, >, s, d, h, r, i, e) and the header/legend lines."""
    out: set = set()
    if not output:
        return []
    for raw in output.splitlines():
        s = raw.strip()
        if not s or s.lower().startswith(("network", "bgp table", "status codes", "origin codes")):
            continue
        m = re.match(r"^[*>sdhrieSx&\s]*?(\d{1,3}(?:\.\d{1,3}){3}/\d{1,2})\b", s)
        if m:
            out.add(m.group(1))
    return sorted(out)


def parse_ip_routes(output: str) -> Dict[str, Dict[str, object]]:
    routes: Dict[str, Dict[str, object]] = {}
    if not output:
        return routes
    code_map = {
        'C':'connected','L':'local','S':'static','R':'rip','M':'mobile','B':'bgp','D':'eigrp','EX':'eigrp-external',
        'O':'ospf','IA':'ospf-interarea','N1':'ospf-nssa1','N2':'ospf-nssa2','E1':'ospf-ext1','E2':'ospf-ext2',
        'i':'isis','su':'static','*':'candidate-default','H':'hsrp'
    }
    current = None
    for raw in output.splitlines():
        line = raw.rstrip()
        s = line.strip()
        if not s or s.lower().startswith(('gateway of last resort','codes:','route source','is variably subnetted','is subnetted')):
            continue
        m = re.match(r"^([A-Z][A-Z0-9\*]*)\s+(\d+\.\d+\.\d+\.\d+/\d+|\d+\.\d+\.\d+\.\d+\s*/\s*\d+)", s)
        if m:
            code = m.group(1)
            prefix = m.group(2).replace(' ', '')
            nh = ''
            out_intf = ''
            mvia = re.search(r"via\s+(\d+\.\d+\.\d+\.\d+)", s, re.IGNORECASE)
            if mvia:
                nh = mvia.group(1)
            mint = re.search(r",\s*([A-Za-z]+[A-Za-z0-9/\.:-]+)\s*$", s)
            if mint and not re.match(r"^\d+\.\d+\.\d+\.\d+$", mint.group(1)):
                out_intf = normalize_ifname(mint.group(1))
            routes.setdefault(prefix, {'entries': []})
            entry = {'prefix': prefix, 'code': code, 'source': code_map.get(code, code.lower()), 'next_hop': nh, 'out_intf': out_intf, 'raw': s}
            routes[prefix]['entries'].append(entry)
            current = prefix
            continue
        if current:
            m2 = re.search(r"via\s+(\d+\.\d+\.\d+\.\d+)", s, re.IGNORECASE)
            if m2:
                nh = m2.group(1)
                mint = re.search(r",\s*([A-Za-z]+[A-Za-z0-9/\.:-]+)\s*$", s)
                out_intf = ''
                if mint and not re.match(r"^\d+\.\d+\.\d+\.\d+$", mint.group(1)):
                    out_intf = normalize_ifname(mint.group(1))
                routes[current]['entries'].append({'prefix': current, 'code': '', 'source': '', 'next_hop': nh, 'out_intf': out_intf, 'raw': s})
    return routes

def parse_copp_drops(output: str) -> list:
    """'show policy-map interface control-plane' (NX-OS) / 'show policy-map control-plane' (IOS / IOS-XE)
    -> [{class, conformed, exceeded, violated, dropped, drops}] per CoPP class. `drops` = the total
    control-plane traffic DISCARDED by the policer for that class (exceeded + violated + dropped). A class
    with drops > 0 means the box is actively policing/dropping punted control-plane traffic -- a mistuned
    policer or a control-plane flood/CPU-pressure event (protocol packets can be silently starved).
    Counters are PACKETS on IOS/IOS-XE and BYTES on NX-OS (module blocks summed per class); the firing
    condition (drops > 0) is platform-agnostic. [] when no CoPP policy is applied. Tolerant; never raises."""
    out: list = []
    cur = None

    def _flush():
        if cur is not None:
            cur["drops"] = cur["exceeded"] + cur["violated"] + cur["dropped"]
            out.append(cur)

    for raw in (output or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        h = re.match(r"^[Cc]lass-?map:?\s+(\S+)\s*\(match-", s)
        if h:
            _flush()
            cur = {"class": h.group(1), "conformed": 0, "exceeded": 0, "violated": 0, "dropped": 0, "drops": 0}
            continue
        if cur is None:
            continue
        if re.match(r"^police\b", s, re.IGNORECASE):
            continue
        # Scan ANYWHERE in the line (not just line-start) and allow multiple counters per line, so the NX-OS
        # one-line 'module N : transmitted X bytes; dropped Y bytes;' form (counter mid-line) is captured -- not
        # only the split-line NX-OS / classic IOS-XE forms. ('transmitted' is intentionally not summed.)
        for kw, num in re.findall(r"\b(conformed|exceeded|violated|dropped)\s+(\d+)\s+(?:packets|bytes)\b", s, re.IGNORECASE):
            cur[kw.lower()] += int(num)
    _flush()
    return out


# --- PIM-SM control-plane (RP mapping + neighbor adjacency) ------------------ #
# These read 'show ip pim rp mapping' and 'show ip pim neighbor' (IOS / IOS-XE /
# NX-OS). The pair powers the multicast-resilience detector: PIM sparse-mode that
# is *running* (>=1 neighbor) but has learned NO RP means ASM (*,G) shared trees
# cannot be built -- multicast forwarding is broken (RFC 7761). SSM (232.0.0.0/8)
# needs no RP, so an SSM-only domain is NOT a finding. Tolerant: empty/absent -> {}/[].
_PIM_RP_LINE_RE = re.compile(r"\bRP[:\s]+(\d+\.\d+\.\d+\.\d+)", re.IGNORECASE)
_PIM_GROUP_RE = re.compile(r"(?:Group\(s\)|Group ranges?)[:\s]+(\d+\.\d+\.\d+\.\d+/\d+)", re.IGNORECASE)
_PIM_INFOSRC_RE = re.compile(r"Info source:\s*(\d+\.\d+\.\d+\.\d+)", re.IGNORECASE)


def parse_pim_rp_mapping(output: str) -> dict:
    """'show ip pim rp mapping' (IOS/IOS-XE/NX-OS) -> a learned-RP summary:
    {present, rp_count, rps:[{group, rp, source}], groups:[...], ssm_only}.

    `present`  -- the command actually ran (header / any RP / any Group seen), so an
                  empty {} unambiguously means 'not collected', never 'no RP'.
    `rp_count` -- distinct RP unicast addresses learned (static + Auto-RP + BSR).
    `ssm_only` -- True when the ONLY group range(s) mapped are inside SSM (232.0.0.0/8)
                  and zero RPs are learned: SSM needs no RP, so this is HEALTHY, not broken.
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
        gms = _PIM_GROUP_RE.findall(s)                     # NX-OS may list multiple comma-separated ranges per line
        if gms:
            cur_group = gms[0]
            for g in gms:
                if g not in groups:
                    groups.append(g)
        rm = _PIM_RP_LINE_RE.search(s)
        if rm:
            rp = rm.group(1)
            sm = _PIM_INFOSRC_RE.search(s)
            grp = cur_group
            inline_g = _PIM_GROUP_RE.search(s)
            if inline_g:
                grp = inline_g.group(1)
            rps.append({"group": grp, "rp": rp, "source": (sm.group(1) if sm else "")})
            seen_rp.add(rp)
            continue
        ism = _PIM_INFOSRC_RE.search(s)
        if ism and rps and not rps[-1]["source"]:
            rps[-1]["source"] = ism.group(1)

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
    lines are skipped. Interfaces are normalised to the engine's short canonical form."""
    out: List[dict] = []
    if not output:
        return out
    for raw in output.splitlines():
        s = raw.strip()
        if not s:
            continue
        low = s.lower()
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


def parse_ipv6_raguard_policy(output: str) -> list:
    """'show ipv6 nd raguard policy' (IOS / IOS-XE / NX-OS IPv6 first-hop security) ->
    [{policy, device_role, trusted, targets:[{name, type}]}]. RA-Guard blocks rogue / spoofed Router
    Advertisements at the L2 access edge -- without it a single bogus RA hijacks the default gateway for the
    whole segment (RFC 6104 / RFC 4861 gateway-hijack -> MITM/DoS). [] when the device runs no RA-Guard (or
    the command is unsupported). Tolerant; never raises. normalize_ifname canonicalises PORT targets."""
    out: list = []
    cur = None
    for raw in (output or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        m = re.match(r"^(?:RA guard )?Policy\s+(\S+)\s+configuration\s*:?\s*$", s, re.IGNORECASE)
        if m:
            cur = {"policy": m.group(1), "device_role": "", "trusted": False, "targets": []}
            out.append(cur)
            continue
        if cur is None:
            continue
        m = re.match(r"^device-role\s+(\S+)", s, re.IGNORECASE)
        if m:
            cur["device_role"] = m.group(1).lower(); continue
        if re.match(r"^trusted-port\b", s, re.IGNORECASE):
            cur["trusted"] = True; continue
        mt = re.match(r"^(\S+(?:\s+\d[\d,\- ]*)?)\s+(PORT|VLAN)\s+(\S+)\s+RA guard\b", s, re.IGNORECASE)
        if mt:
            ttype = mt.group(2).upper()
            tname = mt.group(1).strip()
            name = normalize_ifname(tname) if ttype == "PORT" else tname
            owner = next((p for p in out if p["policy"] == mt.group(3)), cur)
            owner["targets"].append({"name": name, "type": ttype})
    return out


def parse_ipv6_dhcp_guard_policy(output: str) -> list:
    """'show ipv6 dhcp guard policy' (IPv6 first-hop security) -> [{policy, device_role, targets:[{name,type}]}].
    DHCPv6-Guard blocks DHCPv6 reply/advertise messages from unauthorised servers/relays at the access edge
    (rogue-DHCPv6 -> address theft / MITM). [] when no DHCPv6-Guard. Tolerant; never raises."""
    out: list = []
    cur = None
    for raw in (output or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        m = re.match(r"^Dhcp guard policy\s*:?\s*(\S+)", s, re.IGNORECASE)
        if m:
            cur = {"policy": m.group(1), "device_role": "", "targets": []}
            out.append(cur)
            continue
        if cur is None:
            continue
        m = re.match(r"^Device Role\s*:?\s*(?:dhcp\s+)?(\S+)", s, re.IGNORECASE)
        if m:
            cur["device_role"] = m.group(1).lower(); continue
        m = re.match(r"^Target\s*:?\s*(.+)$", s, re.IGNORECASE)
        if m:
            rest = m.group(1).strip()
            vlans = re.findall(r"vlan\s+(\d+)", rest, re.IGNORECASE)
            if vlans:
                for v in vlans:
                    cur["targets"].append({"name": v, "type": "VLAN"})
            else:
                for tok in rest.split():
                    cur["targets"].append({"name": normalize_ifname(tok), "type": "PORT"})
    return out


def parse_ntp_status(output: str) -> Dict[str, object]:
    """Clock-synchronization STATE from 'show ntp status' (IOS/IOS-XE) OR 'show ntp peer-status' (NX-OS) ->
    {synchronized: True|False|None, stratum: int|None, reference: str, source: str}. The OPERATIONAL complement
    to the config-only `no-ntp` CIS check: a device can have NTP configured yet be UNSYNCHRONIZED (stratum 16).

    IOS/IOS-XE: 'Clock is synchronized, stratum 7, reference is 10.0.0.10' (first line authoritative).
    NX-OS: 'show ntp status' has no sync line, so it is derived from 'show ntp peer-status' -- a '*'-prefixed
    row is the peer selected for sync; its 'st' column is the system stratum (16 = none).

    Coverage-honest: returns {} when there is NO NTP output at all (absence is NOT unsynchronized). synchronized
    stays None when neither shape is present, so a device is never inferred unsynced from silence. Never raises."""
    text = output or ""
    if not text.strip():
        return {}
    res: Dict[str, object] = {"synchronized": None, "stratum": None, "reference": "", "source": ""}

    m = re.search(r"Clock is (un)?synchroni[sz]ed", text, re.IGNORECASE)
    if m:
        res["synchronized"] = (m.group(1) is None)
        res["source"] = "ios-status"
        ms = re.search(r"\bstratum\s+(\d+)", text, re.IGNORECASE)
        if ms:
            res["stratum"] = int(ms.group(1))
        mr = re.search(r"reference is\s+(\S+)", text, re.IGNORECASE)
        if mr:
            res["reference"] = mr.group(1).rstrip(",")
        return res

    saw_table = False
    for raw in text.splitlines():
        s = raw.strip()
        pm = re.match(r"^([*+=-])\s*(\d+\.\d+\.\d+\.\d+)\s+(?:\d+\.\d+\.\d+\.\d+|[0-9A-Fa-f:.]+)\s+(\d+)\b", s)
        if not pm:
            continue
        saw_table = True
        sym, remote, st = pm.group(1), pm.group(2), int(pm.group(3))
        if sym == "*":
            res["synchronized"] = True
            res["stratum"] = st
            res["reference"] = remote
            res["source"] = "nxos-peer-status"
    if saw_table:
        res["source"] = res["source"] or "nxos-peer-status"
        if res["synchronized"] is None:
            res["synchronized"] = False
            res["stratum"] = 16
        return res

    return res if (res["synchronized"] is not None or res["stratum"] is not None) else {}


def parse_port_security_detail(output: str) -> Dict[str, dict]:
    """Per-interface 'show port-security interface [<if>]' DETAIL -> {ifname: {enabled, port_status,
    violation_mode, violation_count, last_src, last_vlan}}. The summary parser (parse_port_security)
    has NO port-status column, so it cannot tell an err-disabled (Secure-shutdown) port from a healthy one.
    A shutdown-mode violation err-disables the port (Port Status -> 'Secure-shutdown'), stopping ALL traffic
    incl. authorized devices, whereas 'restrict'/'protect' keep the port up (Secure-up) and merely drop+count
    -- so only Secure-shutdown is a live outage, not a raw nonzero counter. Tolerant: {} on empty / non-detail
    input; never raises. port_status is lower-cased canonical ('secure-shutdown', 'secure-up', 'secure-down')."""
    res: Dict[str, dict] = {}
    cur: Optional[str] = None
    pend: Optional[str] = None
    for raw in (output or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        hm = re.match(r"^(?:Secure\s+Port|Port|Interface)\s*[:=]\s*(\S+)\s*$", s, re.IGNORECASE)
        if hm and is_valid_iface(hm.group(1)):
            pend = normalize_ifname(hm.group(1)); continue
        bare = re.match(r"^(\S+)$", s)
        if bare and is_valid_iface(bare.group(1)) and PHYSICAL_IFACE_RE.match(normalize_ifname(bare.group(1))):
            pend = normalize_ifname(bare.group(1)); continue
        m = re.match(r"^Port\s+Security\s*[:=]\s*(\w+)", s, re.IGNORECASE)
        if m:
            cur = pend or cur
            pend = None
            if cur is None:
                continue
            res.setdefault(cur, {"enabled": False, "port_status": "", "violation_mode": "",
                                 "violation_count": 0, "last_src": "", "last_vlan": ""})
            res[cur]["enabled"] = m.group(1).strip().lower() == "enabled"
            continue
        if cur is None or cur not in res:
            continue
        r = res[cur]
        m = re.match(r"^Port\s+Status\s*[:=]\s*(\S+)", s, re.IGNORECASE)
        if m: r["port_status"] = m.group(1).strip().lower(); continue
        m = re.match(r"^Violation\s+Mode\s*[:=]\s*(\w+)", s, re.IGNORECASE)
        if m: r["violation_mode"] = m.group(1).strip().capitalize(); continue
        m = re.match(r"^Security\s+Violation\s+Count\s*[:=]\s*(\d+)", s, re.IGNORECASE)
        if m: r["violation_count"] = int(m.group(1)); continue
        m = re.match(r"^Last\s+Source\s+Address(?::Vlan)?\s*[:=]\s*([0-9a-fA-F.:]+?)(?::(\d+))?\s*$", s, re.IGNORECASE)
        if m:
            r["last_src"] = m.group(1)
            if m.group(2): r["last_vlan"] = m.group(2)
            continue
    return res


_STORM_TYPE_WORD = {"B": "broadcast", "M": "multicast", "U": "unicast",
                    "BCAST": "broadcast", "MCAST": "multicast", "UCAST": "unicast",
                    "BROADCAST": "broadcast", "MULTICAST": "multicast", "UNICAST": "unicast"}


def parse_storm_control(output: str) -> list:
    """'show storm-control' -> [{interface, traffic, filter_state, upper, lower, current, action, configured}].
    The per-traffic ACTION decides what happens when the storm crosses the rising threshold -- 'Shutdown'
    err-disables the port, 'Trap' raises an SNMP notification, and 'None' SILENTLY drops the excess with no
    operator visibility. The senior gap (-> _d_storm_control_action) is a configured rule whose action is None.
    `configured` is True when a real Upper threshold is present (the rule exists), so a port simply ABSENT from
    the output is never flagged. Tolerant of the modern Action+Type form and the older no-Action form (action
    ''). [] on empty / non-storm-control input; never raises."""
    out = []
    for raw in (output or "").splitlines():
        s = raw.strip()
        if not s or s.lower().startswith(("key:", "interface", "---")):
            continue
        toks = s.split()
        if len(toks) < 2 or not is_valid_iface(toks[0]):
            continue
        ifname = normalize_ifname(toks[0])
        rest = toks[1:]
        traffic = ""
        if rest and rest[-1].upper() in _STORM_TYPE_WORD and len(rest[-1]) == 1:
            traffic = _STORM_TYPE_WORD[rest.pop().upper()]
        if not traffic and rest and rest[0].upper() in _STORM_TYPE_WORD:
            traffic = _STORM_TYPE_WORD[rest.pop(0).upper()]
        action = ""
        if rest and rest[-1].lower() in ("none", "trap", "shutdown"):
            action = rest.pop().capitalize()
        nums = [t for t in rest if re.match(r"^[\d.]+[a-z%]*$", t, re.IGNORECASE)]
        upper = nums[0] if len(nums) >= 1 else ""
        lower = nums[1] if len(nums) >= 2 else ""
        current = nums[2] if len(nums) >= 3 else (nums[-1] if nums else "")
        state_words = []
        for t in rest:
            if re.match(r"^[\d.]+[a-z%]*$", t, re.IGNORECASE):
                break
            state_words.append(t)
        out.append({"interface": ifname, "traffic": traffic,
                    "filter_state": " ".join(state_words), "upper": upper, "lower": lower,
                    "current": current, "action": action, "configured": bool(upper)})
    return out


# 'show policy-map interface' RUNTIME statistics regexes (egress queue/policer drops). Validated against
# Cisco's genieparser golden corpus + IOS-XE/NX-OS QoS guides. The drops line is identical for bandwidth and
# priority (LLQ) classes on modern IOS-XE; priority/policer context is tracked by the line-driven state machine.
_PM_IFACE_RE   = re.compile(r"^([A-Za-z][\w./-]*\d[\w./-]*)\s*$")
_PM_SVCPOL_RE  = re.compile(r"^Service-policy\s+(?:\((?P<kind>[^)]*)\)\s+)?(?P<dir>input|output)\s*:\s*(?P<name>\S+)",
                            re.IGNORECASE)
_PM_CLASS_RE   = re.compile(r"^Class-map(?:\s+\((?P<kind>[^)]*)\))?\s*:\s*(?P<name>\S+)", re.IGNORECASE)
_PM_QDROPS_RE  = re.compile(r"\(queue depth/total drops/no-buffer drops\)\s+(\d+)/(\d+)/(\d+)", re.IGNORECASE)
_PM_PRIDROPS_RE = re.compile(r"\(total drops/bytes drops\)\s+(\d+)/(\d+)", re.IGNORECASE)
_PM_OUTPUT_RE  = re.compile(r"\(pkts output/bytes output\)\s+(\d+)/(\d+)", re.IGNORECASE)
_PM_PRIORITY_RE = re.compile(r"^(?:priority(?:\s+level\s+\d+)?\b|Strict Priority|Priority:)", re.IGNORECASE)
_PM_BWEXCEED_RE = re.compile(r"b/w\s+exceed\s+drops:\s*(\d+)", re.IGNORECASE)   # IOS 15.x+ LLQ priority-class drops
_PM_POLICE_RE  = re.compile(r"^police\b", re.IGNORECASE)
_PM_EXCEEDED_RE = re.compile(r"^exceeded\s+(\d+)\s+packets,\s+(\d+)\s+bytes", re.IGNORECASE)
_PM_VIOLATED_RE = re.compile(r"^violated\s+(\d+)\s+packets,\s+(\d+)\s+bytes", re.IGNORECASE)
_PM_NX_CLASS_RE = re.compile(r"^Class-map\s+\(queuing\)\s*:\s*(?P<name>\S+)", re.IGNORECASE)
_PM_NX_DROP_RE = re.compile(r"^queue\s+dropped\s+pkts\s*:\s*(\d+)", re.IGNORECASE)
_PM_NX_DROPB_RE = re.compile(r"^queue\s+dropped\s+bytes\s*:\s*(\d+)", re.IGNORECASE)
_PM_NX_TX_RE   = re.compile(r"^queue\s+transmit\s+pkts\s*:\s*(\d+)", re.IGNORECASE)


def parse_policymap_drops(output: str) -> list:
    """'show policy-map interface' RUNTIME stats -> one record per EGRESS class/queue that has data:
    [{interface, policy, class, priority(bool), drop_pkts, drop_bytes, output_pkts, police_drop_pkts,
    police_drop_bytes}]. The QoS-RUNTIME complement to parse_qos_config (which only proves a policy EXISTS):
    a class with significant egress drops means the queue/policer is shedding the very traffic the intent
    classified. Only the OUTPUT (egress) direction is recorded. Both IOS/IOS-XE and NX-OS queuing dialects are
    parsed. Tolerant: [] on empty / non-policy-map input; never raises."""
    out: list = []
    iface = ""
    egress = False
    policy = ""
    cur: Optional[dict] = None
    in_police = False

    def _flush():
        if cur is not None and egress and iface:
            out.append(cur)

    for raw in (output or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        mi = _PM_IFACE_RE.match(s)
        if mi and not s.lower().startswith(("class-map", "service-policy", "police", "queueing",
                                            "queue", "match", "priority", "bandwidth", "exceeded",
                                            "conformed", "violated")):
            _flush(); cur = None; in_police = False
            iface = normalize_ifname(mi.group(1)); egress = False; policy = ""
            continue
        msp = _PM_SVCPOL_RE.match(s)
        if msp:
            _flush(); cur = None; in_police = False
            egress = msp.group("dir").lower() == "output"
            policy = msp.group("name")
            continue
        mnc = _PM_NX_CLASS_RE.match(s)
        mc = mnc or _PM_CLASS_RE.match(s)
        if mc:
            _flush(); in_police = False
            cur = {"interface": iface, "policy": policy, "class": mc.group("name"),
                   "priority": False, "drop_pkts": 0, "drop_bytes": 0, "output_pkts": 0,
                   "police_drop_pkts": 0, "police_drop_bytes": 0}
            continue
        if cur is None:
            continue
        m = _PM_BWEXCEED_RE.search(s)        # IOS 15.x+ LLQ drop counter on the 'Priority: ... b/w exceed drops: N'
        if m:                                 # line; the _PM_PRIORITY_RE continue below would otherwise SKIP it
            cur["priority"] = True
            cur["drop_pkts"] = max(cur["drop_pkts"], int(m.group(1)))
            continue
        if _PM_PRIORITY_RE.match(s):
            cur["priority"] = True
            continue
        if _PM_POLICE_RE.match(s):
            in_police = True
            continue
        m = _PM_QDROPS_RE.search(s)
        if m:
            # max(), not assign: a later aggregate 'queue stats for all priority classes' 0/0/0 line must not
            # clobber a real 'b/w exceed drops' value already captured for an LLQ class.
            cur["drop_pkts"] = max(cur["drop_pkts"], int(m.group(2))); continue
        m = _PM_PRIDROPS_RE.search(s)
        if m:
            cur["priority"] = True
            cur["drop_pkts"] = int(m.group(1)); cur["drop_bytes"] = int(m.group(2)); continue
        m = _PM_OUTPUT_RE.search(s)
        if m:
            cur["output_pkts"] = int(m.group(1)); continue
        if in_police:
            m = _PM_EXCEEDED_RE.match(s)
            if m:
                cur["police_drop_pkts"] += int(m.group(1)); cur["police_drop_bytes"] += int(m.group(2)); continue
            m = _PM_VIOLATED_RE.match(s)
            if m:
                cur["police_drop_pkts"] += int(m.group(1)); cur["police_drop_bytes"] += int(m.group(2)); continue
        m = _PM_NX_DROP_RE.match(s)
        if m:
            cur["drop_pkts"] = int(m.group(1)); continue
        m = _PM_NX_DROPB_RE.match(s)
        if m:
            cur["drop_bytes"] = int(m.group(1)); continue
        m = _PM_NX_TX_RE.match(s)
        if m:
            cur["output_pkts"] = int(m.group(1)); continue
    _flush()
    return out


# CDP advertises capabilities as FULL WORDS on the Platform line ("Capabilities: Router Switch IGMP");
# LLDP advertises them as SINGLE LETTERS in "Enabled Capabilities: B,R". Capturing the raw capability string
# is what lets the shadow-infra detector tell an undocumented DISTRIBUTION SWITCH from a CDP-speaking phone or
# AP. CDP codes: R Router, T Trans-Bridge, B Source-Route-Bridge, S Switch, H Host, I IGMP, r Repeater, P Phone.
# LLDP codes: R Router, B Bridge, T Telephone, C DOCSIS, W WLAN-AP, P Repeater, S Station, O Other.
def parse_neighbors_detail(output: str, proto: str = "cdp") -> List[Dict[str, str]]:
    """'show cdp neighbors detail' (proto='cdp') / 'show lldp neighbors detail' (proto='lldp') ->
    [{device_id, platform, capabilities, mgmt_ip, local_intf, remote_port, proto}] -- ONE record per
    discovered neighbour, KEEPING the capability codes the topology-link parsers discard. [] on empty /
    unrecognised input; tolerant, never raises. Reuses the already-collected CDP/LLDP detail (no new command)."""
    out: List[Dict[str, str]] = []
    if not output:
        return out
    if (proto or "").lower() == "lldp":
        # IOS/IOS-XE blocks begin with 'Local Intf:'; NX-OS has none and begins each block with 'Chassis id:'
        # (its local interface is on a 'Local Port id:' line). Split on whichever delimits THIS output so an
        # NX-OS capture is not collapsed into one Frankenstein record spanning every neighbour.
        iosxe = bool(re.search(r"(?im)^\s*Local Intf:", output))
        blocks = (re.split(r"\n\s*Local Intf:\s*", "\n" + output) if iosxe
                  else re.split(r"(?im)^(?=[ \t]*Chassis id:)", output))
        for ch in blocks:
            ch = ch.strip()
            if not ch:
                continue
            rec = {"device_id": "", "platform": "", "capabilities": "", "mgmt_ip": "",
                   "local_intf": "", "remote_port": "", "proto": "lldp"}
            # IOS-XE: the split consumed 'Local Intf:', so the block's first token IS the local interface.
            if iosxe:
                rec["local_intf"] = normalize_ifname(ch.splitlines()[0].strip().split()[0])
            sys_caps = ""
            for line in ch.splitlines():
                ls = line.strip()
                m = re.match(r"^Local Port id:\s*(.+)$", ls, re.IGNORECASE)   # NX-OS local interface (by LABEL)
                if m and not rec["local_intf"]:
                    rec["local_intf"] = normalize_ifname(m.group(1).strip())
                m = re.match(r"^System Name:\s*(.+)$", ls, re.IGNORECASE)
                if m:
                    rec["device_id"] = m.group(1).strip()
                m = re.match(r"^Port id:\s*(.+)$", ls, re.IGNORECASE)         # remote port ('Local Port id:' excluded)
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
                # mgmt IP: NX-OS 'Management Address: x'; IOS-XE 'Management Addresses:' then an indented 'IP: x'
                m = re.search(r"\b(\d+\.\d+\.\d+\.\d+)\b", ls)
                if m and not rec["mgmt_ip"] and ("management" in ls.lower() or re.match(r"^IP:\s", ls, re.IGNORECASE)):
                    rec["mgmt_ip"] = m.group(1)
            if not rec["capabilities"]:
                rec["capabilities"] = sys_caps
            caps = rec["capabilities"].upper().replace("N/A", "").strip()
            if rec["local_intf"] and (rec["device_id"] or caps):
                out.append(rec)
        return out
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
            ipm = re.search(r"\b(?:ip address|ipv4 address):\s*(\d+\.\d+\.\d+\.\d+)\b", ls, re.IGNORECASE)
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


def parse_nve_vni(output: str) -> list:
    """'show nve vni' (NX-OS VXLAN) -> [{vni, mcast_group, state, mode, type}]. The L2 (VLAN<->VNI) and L3
    (VRF<->L3VNI) bindings on this VTEP; State Up = the VNI is operational. A VNI not Up strands its VLAN/VRF
    on the local VTEP (no overlay reachability for that segment). [] when no NVE. Tolerant; never raises."""
    out = []
    for raw in (output or "").splitlines():
        # NX-OS: 'Interface VNI Multicast-group State Mode(CP/DP) Type(L2/L3) [BD/VRF]'
        m = re.match(r"^\s*nve\d+\s+(\d+)\s+(\S+)\s+(\w+)\s+(\w+)\s+(L[23])\b", raw, re.IGNORECASE)
        if m:
            mc = m.group(2)
            out.append({"vni": m.group(1), "mcast_group": "" if mc.lower() in ("n/a", "--", "unknown") else mc,
                        "state": m.group(3).capitalize(), "mode": m.group(4).upper(), "type": m.group(5).upper()})
            continue
        # IOS-XE Catalyst 9000: 'Interface VNI Multicast-group State Mode(L2CP/L3CP) vlan vrf' -- Type is fused
        # into the Mode token and the column after it is the VLAN/BD number (not an L2/L3 type token).
        m2 = re.match(r"^\s*nve\d+\s+(\d+)\s+(\S+)\s+(\w+)\s+L([23])CP\b", raw, re.IGNORECASE)
        if m2:
            mc = m2.group(2)
            out.append({"vni": m2.group(1), "mcast_group": "" if mc.lower() in ("n/a", "--", "unknown") else mc,
                        "state": m2.group(3).capitalize(), "mode": "CP", "type": "L" + m2.group(4)})
    return out


def _parse_bgp_summary_rows(output: str) -> list:
    """Shared parser for the standard BGP neighbor summary grid (address-family agnostic) that
    'show bgp <afi> <safi> summary' prints identically for l2vpn evpn, vpnv4 unicast, ipv4 unicast, etc.:
    'Neighbor V AS MsgRcvd MsgSent TblVer InQ OutQ Up/Down State/PfxRcd' -> [{neighbor, as, state, prefixes}].
    'state' is 'Established' when the final column is a prefix count, else the literal BGP state word
    (Idle/Active/Connect/OpenSent/OpenConfirm). A wide Neighbor/AS (a 15-char IPv4, any IPv6 peer, or a
    4-byte asdot AS) makes IOS/NX-OS WRAP the State/PfxRcd onto a continuation line; rows are stitched back
    (head line + following numeric continuation) so a wrapped DOWN peer is never read as Established and IPv6
    peers are not dropped. Tolerant; never raises."""
    # a neighbor row STARTS with an IPv4 or IPv6 address as its first token (then optionally a %zone-id)
    head = re.compile(r"^(\d+\.\d+\.\d+\.\d+|[0-9A-Fa-f:]*:[0-9A-Fa-f:]+)(?:%\S+)?(?:\s|$)")
    out = []
    cur = None

    def _flush(toks):
        if not toks or len(toks) < 10:        # the full grid is 10 columns; a header/partial fragment is dropped
            return
        last = toks[-1]
        out.append({"neighbor": toks[0], "as": toks[2],
                    "state": "Established" if last.isdigit() else last,
                    "prefixes": int(last) if last.isdigit() else 0})

    for raw in (output or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        if head.match(s):
            _flush(cur)
            cur = s.split()
        elif cur is not None and len(cur) < 10 and re.match(r"^\d", s):
            cur.extend(s.split())             # wrapped continuation: the numeric stats + State/PfxRcd
    _flush(cur)
    return out


def parse_evpn_summary(output: str) -> list:
    """'show bgp l2vpn evpn summary' -> [{neighbor, as, state, prefixes}]. The BGP-EVPN control plane that
    distributes VXLAN MAC/IP (Type-2) and prefix (Type-5) routes between VTEPs; a neighbor not Established
    means no overlay route exchange with that peer (the data plane can be Up while the control plane is
    dark). State = 'Established' when the last column is a prefix count, else the BGP state word. []
    when EVPN is not running. Tolerant; never raises."""
    return _parse_bgp_summary_rows(output)


def parse_bgp_vpnv4_summary(output: str) -> list:
    """'show bgp vpnv4 unicast summary' (MPLS L3VPN PE) -> [{neighbor, as, state, prefixes}]. The MP-BGP
    VPNv4 control plane carries per-VRF customer prefixes between PE routers; a neighbor not 'Established'
    means no VPN routes are exchanged with that PE, so every VRF depending on it loses its remote sites
    (the LDP/data plane can be Up while VPNv4 is dark). Same neighbor grid as the EVPN/IPv4 summaries.
    Tolerant; never raises."""
    return _parse_bgp_summary_rows(output)


def parse_mpls_ldp_neighbors(output: str) -> list:
    """'show mpls ldp neighbor' (IOS / IOS-XE) -> [{peer, label_space, state}] per LDP adjacency. LDP
    distributes the transport labels for the MPLS underlay; the operational state is 'Oper'. Any other
    state (Nonexistent, Initialized, OpenSent, OpenRec) means the session is not exchanging label bindings,
    so LSPs through that peer -- and the L3VPN/L2VPN services riding them -- blackhole. [] when no MPLS/LDP
    is configured. Tolerant; never raises."""
    out = []
    cur = None
    for raw in (output or "").splitlines():
        s = raw.strip()
        m = re.match(r"^Peer LDP Ident:\s*(\d+\.\d+\.\d+\.\d+):(\d+)", s, re.IGNORECASE)
        if m:
            if cur is not None:
                out.append(cur)
            cur = {"peer": m.group(1), "label_space": m.group(2), "state": ""}
            continue
        if cur is None:
            continue
        st = re.match(r"^State:\s*(\w+)", s, re.IGNORECASE)
        if st:
            cur["state"] = st.group(1)
    if cur is not None:
        out.append(cur)
    return out


def parse_mpls_l2vpn_vc(output: str) -> list:
    """'show mpls l2transport vc' (IOS / IOS-XE AToM/EoMPLS) -> [{local_intf, dest, vc_id, status}] per L2VPN
    pseudowire. Status is UP (forwarding), DOWN (the pseudowire is signalled down -- the customer L2 circuit
    is broken), or STANDBY (a healthy backup PW). The 'Local circuit' column contains spaces, so each data
    row is parsed from the RIGHT (status, VC ID, dest IP) with the first token as the local interface; a row
    whose dest is not an IPv4 address (header / separator) is skipped. [] when no L2VPN VC is configured.
    Tolerant; never raises."""
    out = []
    for raw in (output or "").splitlines():
        s = raw.strip()
        if not s or re.match(r"^Local\s+intf", s, re.IGNORECASE):
            continue
        toks = s.split()
        if len(toks) < 4:
            continue
        # Anchor on the VC ID = the rightmost all-digit token preceded by an IPv4 dest; everything to its right
        # is the status, so a two-word 'ADMIN DOWN' state is captured WHOLE instead of dropping the row entirely.
        vc_i = next((i for i in range(len(toks) - 1, 1, -1)
                     if toks[i].isdigit() and re.match(r"^\d+\.\d+\.\d+\.\d+$", toks[i - 1])), -1)
        if vc_i < 0 or vc_i >= len(toks) - 1:
            continue
        out.append({"local_intf": toks[0], "dest": toks[vc_i - 1],
                    "vc_id": toks[vc_i], "status": " ".join(toks[vc_i + 1:])})
    return out


def parse_lisp_sessions(output: str) -> list:
    """'show lisp session' (IOS-XE SD-Access fabric) -> [{vrf, total, established, peers:[{peer, port, state}]}]
    per VRF block. Each fabric node opens a LISP reliable-transport (TCP) session to every control-plane node
    (map-server / map-resolver, port 4342); registrations and EID-to-RLOC resolution ride those sessions. The
    summary line 'Sessions for VRF <name>, total: N, established: M' is the device's OWN count of configured vs
    established sessions, and each peer row is 'IP[:port] State Up/Down In/Out Users' with State Up or Down.
    COVERAGE-HONESTY: a lone Down peer is NORMAL on a border that imports no routes or an edge with no endpoints
    (nothing to register on that session) -- so the down-peer list is carried as raw evidence, NOT a verdict;
    the detector keys off the summary counts (total>=1 & established==0 = every CP session down), never off a
    single Down row. [] when no LISP session output is present. Tolerant; never raises."""
    out = []
    cur = None
    for raw in (output or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        m = re.match(r"^Sessions\s+for\s+VRF\s+(\S+?),?\s+total:\s*(\d+),\s*established:\s*(\d+)",
                     s, re.IGNORECASE)
        if m:
            cur = {"vrf": m.group(1), "total": int(m.group(2)),
                   "established": int(m.group(3)), "peers": []}
            out.append(cur)
            continue
        if cur is None:
            continue
        if re.match(r"^Peer\b", s, re.IGNORECASE):   # column header
            continue
        # data row: 'IP[:port]  State  Up/Down  In/Out  Users' -- State is the 2nd column.
        pm = re.match(r"^(\d+\.\d+\.\d+\.\d+)(?::(\d+))?\s+(\w+)\b", s)
        if pm:
            cur["peers"].append({"peer": pm.group(1), "port": pm.group(2) or "",
                                 "state": pm.group(3).capitalize()})
    return out


def parse_cts_environment_data(output: str) -> dict:
    """'show cts environment-data' (IOS-XE & NX-OS TrustSec) -> {} when CTS is not configured / absent,
    else {state, last_status, sgt_count, server_count, lifetime}. The environment-data download is the
    state machine that pulls the SGT->name table (and SGACL policy) from Cisco ISE; 'Current state =
    COMPLETE' (with 'Last status = Successful') is the only fully-downloaded/valid state. Any other state
    (START, WAITING_RESPONSE, WAITING_PAC, ...) means the SGT-to-policy data is stale or was never
    downloaded, so group-based segmentation has no map to enforce (default-permit) -- the device is blind.

    Read ONLY the env-data 'Current state' / 'Last status' lines and the size of the 'Security Group Name
    Table'. The per-server 'Status = DEAD' line is deliberately IGNORED: a device can hold a COMPLETE,
    cached environment-data set while its RADIUS/ISE servers later go DEAD (verified against Cisco docs /
    field output), so server liveness is NOT an env-data-validity signal and must not drive this detector.
    Tolerant: returns {} when no env-data block is present; never raises."""
    text = output or ""
    # Anchor on the env-data block header; a box with no CTS env-data prints neither this nor 'Current state'.
    if not re.search(r"^\s*(?:CTS|TS)\s+Environment\s+Data\b", text, re.IGNORECASE | re.MULTILINE) \
            and not re.search(r"^\s*Current state\s*[=:]", text, re.IGNORECASE | re.MULTILINE):
        return {}
    res = {"state": "", "last_status": "", "sgt_count": 0, "server_count": 0, "lifetime": None}
    m = re.search(r"^\s*Current state\s*[=:]\s*(\S+)", text, re.IGNORECASE | re.MULTILINE)
    if m:
        st = m.group(1).strip().upper()
        # IOS-XE prints 'COMPLETE' with '='; NX-OS prints the download-state ENUM with a ':' separator
        # (CTS_ENV_DNLD_ST_ENV_DOWNLOAD_DONE = the success/valid state, verified vs the DevNet NX-API CTS ref).
        # Normalise the NX-OS success enum to COMPLETE so the COMPLETE-is-healthy detector does NOT false-fire
        # on a fully-downloaded Nexus; any in-progress enum stays non-COMPLETE so it is still flagged.
        res["state"] = "COMPLETE" if st in ("COMPLETE", "CTS_ENV_DNLD_ST_ENV_DOWNLOAD_DONE") else st
    m = re.search(r"^\s*Last status\s*[=:]\s*(.+?)\s*$", text, re.IGNORECASE | re.MULTILINE)
    if m:
        res["last_status"] = m.group(1).strip()
    m = re.search(r"Lifetime\s*=\s*(\d+)", text, re.IGNORECASE)
    if m:
        res["lifetime"] = int(m.group(1))
    # SGT->name entries look like '0-07:Unknown' / '4-04:Employees' (tag '-' generation ':' name), one or
    # more per line in the 'Security Group Name Table'. Count distinct leading SGT tags actually present.
    _tbl = text.split("Security Group Name Table", 1)   # count only the policy SGT name table,
    sgts = set(re.findall(r"(?:^|\s)(\d+)-[0-9a-fA-F]+:\S+", _tbl[1])) if len(_tbl) == 2 else set()
    res["sgt_count"] = len(sgts)   # never the device's own Local Device SGT line
    # RADIUS server lines: ' *Server: 10.10.10.1, port 1812, A-ID ...'. Count them (informational only).
    res["server_count"] = len(re.findall(r"^\s*\*?Server:\s*\d+\.\d+\.\d+\.\d+", text, re.MULTILINE))
    # A state line with no recognizable value is not a usable signal -> treat as absent.
    if not res["state"]:
        return {}
    return res


def parse_dmvpn_peers(output: str) -> list:
    """'show dmvpn' (IOS / IOS-XE DMVPN mGRE/NHRP overlay) -> [{interface, nbma, tunnel_ip, state, attrb}]
    per NHRP/tunnel peer entry. 'State' is the per-peer tunnel session state: UP is the ONLY fully-established
    (healthy) state; NHRP (stuck resolving the next-hop), IKE (stuck in IPsec/IKE negotiation) and down each
    mean that spoke/hub DMVPN tunnel is broken (no overlay forwarding to that peer). Each data row carries two
    addresses (Peer NBMA Addr, Peer Tunnel Add) followed by State and the UpDn time (HH:MM:SS); the State token
    is anchored to the immediately-following HH:MM:SS time, which lets the legend / column-header / dashed-
    separator lines (none of which carry a HH:MM:SS time) be skipped. The leading '# Ent' count is optional
    (continuation rows for multi-network peers omit it), so it is not required by the row regex; 'interface' is
    carried from the most recent 'Interface: TunnelN' header. [] when the device runs no DMVPN ('show dmvpn'
    absent / '% Incomplete command' / no peer rows). Tolerant; never raises."""
    out = []
    cur_if = ""
    # Peer NBMA / Peer Tunnel are IPv4 (sample) or IPv6 NBMA on dual-stack; match either, then anchor State to
    # the UpDn HH:MM:SS time so only real peer rows match.  Attrb (trailing letters) is optional / best-effort.
    addr = r"[0-9A-Fa-f:.]+"
    # UpDn Tm is HH:MM:SS (<24h) OR a Cisco compact uptime (1d05h / 3w0d / 48w0d / 2y34w) OR 'never'. Anchor
    # State to it so legend / header / separator lines (which carry no such token) are skipped -- while an
    # aged or never-up broken peer (the SINGLE most common real broken case) is NOT silently dropped.
    updn = r"(?:\d{1,2}:\d{2}:\d{2}|\d+[ywd]\d+[ywdh]|\d+[ywdhms]|never)"
    row = re.compile(
        r"^\s*(?:\d+\s+)?(" + addr + r")\s+(" + addr + r")\s+"   # Peer NBMA Addr, Peer Tunnel Add
        r"([A-Za-z]+)\s+"                                          # State (UP / NHRP / IKE / down)
        + updn +                                                  # UpDn Tm (anchor)
        r"(?:\s+([A-Za-z0-9]+))?")                                 # Attrb (optional)
    for raw in (output or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        h = re.match(r"^Interface:\s*(\S+?),", s, re.IGNORECASE)   # 'Interface: Tunnel1, IPv4 NHRP Details'
        if h:
            cur_if = h.group(1)
            continue
        m = row.match(s)
        if not m:
            continue
        nbma, tun, state = m.group(1), m.group(2), m.group(3)
        # Guard: at least one of the two address columns must look like a real NBMA/tunnel address (contain a
        # '.' or ':'), so a stray two-word alpha line can never be mistaken for a peer row.
        if "." not in (nbma + tun) and ":" not in (nbma + tun):
            continue
        out.append({"interface": cur_if, "nbma": nbma, "tunnel_ip": tun,
                    "state": state, "attrb": (m.group(4) or "")})
    return out


def parse_crypto_sessions(output: str) -> list:
    """'show crypto session' (IOS / IOS-XE site-to-site IPsec) -> [{interface, peer, status}] per crypto
    session. A crypto session is the IKE + IPsec SA bundle to one peer; the operational health is the
    'Session status:' field. UP-ACTIVE (passing data) / UP-IDLE (established, idle) / UP-NO-IKE (IPsec SAs
    up, IKE re-keying) are all UP states -- the encrypted tunnel exists. DOWN and DOWN-NEGOTIATING mean the
    IKE/IPsec SA is not established, so the tunnel is down and carries nothing. Each 'Interface:' opens a new
    record; 'Peer:' (first token after the label, before any 'port') and 'Session status:' fill it. [] when
    the device runs no IPsec / the command produced nothing. Tolerant; never raises."""
    out = []
    cur = None
    for raw in (output or "").splitlines():
        s = raw.strip()
        m = re.match(r"^Interface:\s*(\S+)", s, re.IGNORECASE)
        if m:
            if cur is not None:
                out.append(cur)
            cur = {"interface": m.group(1), "peer": "", "status": ""}
            continue
        if cur is None:
            continue
        st = re.match(r"^Session status:\s*(\S+)", s, re.IGNORECASE)
        if st:
            cur["status"] = st.group(1).upper()
            continue
        pr = re.match(r"^Peer:\s*(\d+\.\d+\.\d+\.\d+)", s, re.IGNORECASE)
        if pr and not cur["peer"]:
            cur["peer"] = pr.group(1)
    if cur is not None:
        out.append(cur)
    return out


def parse_bfd_neighbors(output: str) -> list:
    """'show bfd neighbors' (IOS / IOS-XE / NX-OS) -> [{neighbor, local_disc, remote_disc, state, interface}]
    per BFD session. BFD gives a client protocol (OSPF/BGP/EIGRP/HSRP/static) sub-second forwarding-path
    failure detection; a session in the Up state is protecting its clients. A session in the Down state means
    the fast-failover path is broken -- the client falls back to its native (multi-second) timers, so a link
    failure no longer converges in milliseconds. AdminDown (operator-disabled) is captured but is NOT a
    forwarding failure.

    Two real on-the-wire layouts exist and BOTH are handled by anchoring on the header line and reading the
    'State' column BY POSITION (never the FIRST Up/Down token, because the 'RH/RS' column is also literally
    'Up'/'Down' and would otherwise be misread):
      * IOS:            'NeighAddr  LD/RD  RH/RS  State  Int'
      * IOS-XE / NX-OS: 'OurAddr  NeighAddr  LD/RD  RH/RS  Holdown(mult)  State  Int [Vrf  Type]'
    NX-OS adds trailing Vrf/Type (SH/MH) columns and may leave Int blank for a multihop session. [] when the
    device runs no BFD ('% BFD is not enabled' / no header / empty). Tolerant; never raises."""
    lines = (output or "").splitlines()
    hdr_idx = -1
    cols = {}
    for i, raw in enumerate(lines):
        # The header is the line carrying both 'NeighAddr' and 'State' (case-insensitive).
        if re.search(r"NeighAddr", raw, re.IGNORECASE) and re.search(r"\bState\b", raw, re.IGNORECASE):
            cols = extract_fixed_cols(raw, [
                ("OurAddr", "ouraddr"), ("NeighAddr", "neighaddr"), ("LD/RD", "ldrd"),
                ("RH/RS", "rhrs"), ("Holdown", "holdown"), ("State", "state"),
                ("Int", "interface"), ("Vrf", "vrf"), ("Type", "type"),
            ])
            hdr_idx = i
            break
    out = []
    if hdr_idx < 0 or "state" not in cols or "neighaddr" not in cols:
        return out
    ip_re = re.compile(r"^(?:\d+\.\d+\.\d+\.\d+|[0-9A-Fa-f:]+:[0-9A-Fa-f:]+)$")
    for raw in lines[hdr_idx + 1:]:
        s = raw.strip()
        if not s or set(s) <= {"-"}:
            continue
        toks = s.split()
        # Anchor on the LD/RD discriminator pair (digits/digits): immune to the column DRIFT a wide 32-bit
        # discriminator causes (header char-position slicing otherwise misreads State as the Holdown ')' or Int).
        ld_i = next((i for i, t in enumerate(toks) if re.match(r"^\d+/\d+$", t)), -1)
        if ld_i < 1 or not ip_re.match(toks[ld_i - 1]):     # need an IP NeighAddr immediately before LD/RD
            continue
        ld, _, rd = toks[ld_i].partition("/")
        rest = toks[ld_i + 1:]                               # RH/RS [Holdown(mult)] State [Int] [Vrf Type]
        # State is the column AFTER the Holdown(mult) paren token (IOS-XE / NX-OS); classic IOS has no Holdown
        # column, so State is one token after RH/RS. Read by TOKEN, never by header char-position.
        hold_j = next((j for j, t in enumerate(rest) if "(" in t and ")" in t), -1)
        st_j = hold_j + 1 if hold_j >= 0 else 1
        if st_j >= len(rest):
            continue
        iface = next((normalize_ifname(t) for t in rest[st_j + 1:] if is_valid_iface(t)), "")
        out.append({"neighbor": toks[ld_i - 1], "local_disc": ld, "remote_disc": rd,
                    "state": rest[st_j], "interface": iface})
    return out


def parse_ipv6_interface_addrs(output: str) -> list:
    """'show ipv6 interface' (IOS / IOS-XE) -> one record per L3 interface that has IPv6 enabled:
    [{interface, admin_up, proto_up, ipv6_enabled, link_local, link_local_dup, global:[{addr, subnet,
    dad_state}]}]. dad_state is 'ok' (no marker), 'duplicate' (a [DUPLICATE]/[DUP] marker -> DAD positively
    detected an address clash, so Cisco sets the address to DUPLICATE and STOPS using it), or 'tentative'
    (a [TENTATIVE] marker -> DAD still in progress, transient -- NOT a fault). A duplicate LINK-LOCAL disables
    IPv6 packet processing on the whole interface (link_local_dup=True). [] when the device shows no IPv6 at
    all (a pure-IPv4 box contributes nothing, so nothing can cry wolf). Tolerant; never raises.

    Header line: 'GigabitEthernet0/1 is up, line protocol is up' (or 'administratively down'); IPv6 enabled
    line: 'IPv6 is enabled, link-local address is FE80::130 [DUPLICATE]'; address line:
    'Global unicast address(es): 1:4::1, subnet is 1:4::/64 [DUPLICATE]'. A single 'Global unicast
    address(es):' header may be followed by additional indented address-only continuation lines, each its own
    record. Grounded verbatim in the Cisco IPv6 command reference / config-guide sample output."""
    out: list = []
    cur = None

    def _dad(tail: str) -> str:
        t = (tail or "").upper()
        if "[DUPLICATE]" in t or "[DUP]" in t:
            return "duplicate"
        if "[TENTATIVE]" in t or "[TEN]" in t:
            return "tentative"
        return "ok"

    # 'Global unicast address(es):' may carry the first address on the same line OR start a list whose
    # addresses are on the following indented continuation lines; track that we are inside that block.
    in_global = False
    nx_addr = False                                          # inside an NX-OS bare 'IPv6 address:' block
    for raw in (output or "").splitlines():
        s = raw.strip()
        if not s:
            in_global = nx_addr = False
            continue
        # IOS / IOS-XE interface header: '<ifname> is [administratively ]up/down, line protocol is up/down'
        mh = re.match(r"^(\S+)\s+is\s+(administratively\s+down|up|down),"
                      r"\s+line protocol is\s+(up|down)", s, re.IGNORECASE)
        # NX-OS interface header: '<ifname>, Interface status: protocol-up/link-up/admin-up, iod: N'
        mnx = re.match(r"^(\S+),\s+Interface status:\s+protocol-(up|down)/link-\S+/admin-(up|down)", s, re.IGNORECASE)
        if mh or mnx:
            if cur is not None:
                out.append(cur)
            if mh:
                cur = {"interface": normalize_ifname(mh.group(1)),
                       "admin_up": mh.group(2).lower() == "up", "proto_up": mh.group(3).lower() == "up",
                       "ipv6_enabled": False, "link_local": "", "link_local_dup": False, "global": []}
            else:   # NX-OS lists an interface in 'show ipv6 interface' ONLY when IPv6 is enabled on it
                cur = {"interface": normalize_ifname(mnx.group(1)),
                       "admin_up": mnx.group(3).lower() == "up", "proto_up": mnx.group(2).lower() == "up",
                       "ipv6_enabled": True, "link_local": "", "link_local_dup": False, "global": []}
            in_global = nx_addr = False
            continue
        if cur is None:
            continue
        # IOS: 'IPv6 is enabled/disabled[, link-local address is FE80::130 [DUPLICATE]]' (the verb itself may be
        # tentative/duplicate when the link-local fails DAD)
        ml = re.match(r"^IPv6 is (enabled|disabled|tentative|duplicate)(?:,\s*link-local address is\s+(\S+)(.*))?$",
                      s, re.IGNORECASE)
        if ml:
            cur["ipv6_enabled"] = ml.group(1).lower() != "disabled"
            if ml.group(2):
                cur["link_local"] = ml.group(2)
                cur["link_local_dup"] = _dad(ml.group(3)) == "duplicate" or ml.group(1).lower() == "duplicate"
            in_global = nx_addr = False
            continue
        # NX-OS: 'IPv6 link-local address: fe80::1 (default) [VALID]'
        mnl = re.match(r"^IPv6 link-local address:\s+(\S+)(?:\s+\([^)]*\))?\s*(\[[^\]]*\])?", s, re.IGNORECASE)
        if mnl:
            cur["link_local"] = mnl.group(1)
            cur["link_local_dup"] = _dad(mnl.group(2) or "") == "duplicate"
            in_global = nx_addr = False
            continue
        # IOS: 'Global unicast address(es): 1:4::1, subnet is 1:4::/64 [DUPLICATE]'  (first addr inline)
        mg = re.match(r"^Global unicast address\(es\):\s*(.+)$", s, re.IGNORECASE)
        if mg:
            in_global = True
            nx_addr = False
            rest = mg.group(1).strip()
            if rest:  # an address sits on the header line itself
                _addr_line(cur, rest, _dad)
            continue
        # NX-OS: bare 'IPv6 address:' header, with the addresses on the FOLLOWING indented lines
        if re.match(r"^IPv6 address:\s*$", s, re.IGNORECASE):
            nx_addr = True
            in_global = False
            continue
        # NX-OS indented address line: '2001:db8:1::1/64 [VALID|DUPLICATE|TENTATIVE]'
        if nx_addr:
            mna = re.match(r"^([0-9A-Fa-f:]+)/(\d+)\s*(\[[^\]]*\])?", s)
            if mna and ":" in mna.group(1):
                cur["global"].append({"addr": mna.group(1), "subnet": "", "dad_state": _dad(mna.group(3) or "")})
                continue
            nx_addr = False     # a non-address line ends the NX-OS address block
        # IOS indented address-only continuation under the Global block:
        #   '1:5::1, subnet is 1:5::/64 [DUPLICATE]'  or  '1:5::1 [TENTATIVE]'
        if in_global and re.match(r"^[0-9A-Fa-f:]+(?:,|\s|$)", s):
            _addr_line(cur, s, _dad)
            continue
        # any other field line ends the continuation contexts but keeps the interface block open
        in_global = nx_addr = False
    if cur is not None:
        out.append(cur)
    return out


def _addr_line(cur: dict, rest: str, _dad) -> None:
    """Parse one global-unicast address fragment ('<addr>, subnet is <pfx> [MARK]' or '<addr> [MARK]')
    into cur['global']. A fragment whose first token is not an IPv6 address is ignored (defensive)."""
    m = re.match(r"^([0-9A-Fa-f:]+)(?:,\s*subnet is\s+(\S+?))?\s*(\[[^\]]*\])?\s*$", rest)
    if not m or ":" not in m.group(1):
        return
    cur["global"].append({"addr": m.group(1), "subnet": (m.group(2) or ""),
                          "dad_state": _dad(m.group(3) or "")})


def parse_ipv6_route_summary(output: str) -> dict:
    """'show ipv6 route summary' (IOS / IOS-XE / NX-OS) -> {present, total, by_source:{name:count}, has_default}.
    The summary header is 'IPv6 Routing Table - <vrf>? - N entries' followed by per-source 'name: N (subnets|total)'
    lines (connected/local/static/RIP/OSPF/BGP/EIGRP/...). This is the IPv6-routing-active GATE, not a fault by
    itself: a device that runs no IPv6 routing emits nothing -> {} so the detector never cries wolf. has_default is
    True only if an explicit '::/0' line is present in the source breakdown (most boxes summarise without it, so it
    is NOT used as a firing signal -- recorded for context only). Tolerant; never raises; {} when absent."""
    out = {"present": False, "total": 0, "by_source": {}, "has_default": False}
    txt = output or ""
    if not txt.strip():
        return {}
    # Header: 'IPv6 Routing Table - 21 entries' or 'IPv6 Routing Table - default - 21 entries'
    mh = re.search(r"IPv6 Routing Table.*?-\s*(\d+)\s+entries", txt, re.IGNORECASE)
    if not mh:
        return {}
    out["present"] = True
    out["total"] = int(mh.group(1))
    # Inline form: '... entries: 4 connected, 2 static, 0 RIP, 1 OSPF, 0 BGP'
    tail = txt[mh.end():]
    minl = re.match(r"\s*:\s*(.+)", tail.splitlines()[0] if tail.splitlines() else "")
    if minl:
        for piece in minl.group(1).split(","):
            m = re.match(r"\s*(\d+)\s+([A-Za-z][\w /-]*?)\s*$", piece)
            if m:
                out["by_source"][m.group(2).strip().lower()] = int(m.group(1))
    # Block form: 'connected: 4' / 'local: 6' / 'static: 2 (5 subnets)' on their own lines
    for raw in tail.splitlines():
        m = re.match(r"\s*([A-Za-z][\w /-]*?)\s*:\s*(\d+)\b", raw)
        if m and "entries" not in m.group(1).lower():
            out["by_source"][m.group(1).strip().lower()] = int(m.group(2))
    # Columnar table form: 'connected  4  0  384  576' (Route Source/Networks/Subnets/Overhead/Memory)
    for raw in tail.splitlines():
        mc = re.match(r"\s*([A-Za-z][\w ]*?)\s+(\d+)\s+\d+\s+\d+\s+\d+\s*$", raw)
        if mc and mc.group(1).strip().lower() not in ("total", "route source"):
            out["by_source"].setdefault(mc.group(1).strip().lower(), int(mc.group(2)))
    # Number-first comma list on its OWN line: '  37 local, 35 connected, 25 static, 0 RIP, 160 BGP' (the real
    # IOS/IOS-XE 'show ipv6 route summary' form; the inline branch above only fires when the list trails a colon).
    for raw in tail.splitlines():
        if ":" in raw:                              # skip 'Number of prefixes:' and the '/NN: c' prefix-length lines
            continue
        for piece in raw.split(","):
            mnf = re.match(r"\s*(\d+)\s+([A-Za-z][\w /-]*?)\s*$", piece)
            if mnf:
                out["by_source"].setdefault(mnf.group(2).strip().lower(), int(mnf.group(1)))
    if "::/0" in txt:
        out["has_default"] = True
    return out


def parse_ospfv3_neighbors(output: str) -> list:
    """'show ospfv3 neighbor' / 'show ipv6 ospf neighbor' (IOS / IOS-XE) -> [{neighbor_id, pri, state, role,
    interface}] per OSPFv3 adjacency. The State column carries a role suffix: 'FULL/DR', 'FULL/BDR', 'FULL/  -',
    '2WAY/DROTHER', 'EXSTART/  -', etc.; state is the token LEFT of '/', role the token right of it (normalised,
    '-' kept). FULL and 2WAY are the two healthy resting states (2WAY is the intentional DROTHER<->DROTHER state on
    a broadcast segment); INIT/ATTEMPT/EXSTART/EXCHANGE/LOADING/DOWN are transient-stuck (broken/forming adjacency,
    e.g. MTU mismatch sticks EXSTART, a one-way hello sticks INIT). The OSPFv3 process header line and the column
    header never create phantom neighbors (their first token is not a router-id). [] when no OSPFv3 is configured.
    Tolerant; never raises."""
    out = []
    for raw in (output or "").splitlines():
        s = raw.strip()
        if not s or re.match(r"^(OSPFv3|Neighbor ID)\b", s, re.IGNORECASE):
            continue
        # <router-id> <pri> <STATE/ROLE> <dead-time> <if-id> <interface>
        m = re.match(r"^(\d+\.\d+\.\d+\.\d+)\s+(\d+)\s+([A-Za-z0-9-]+)\s*/\s*([A-Za-z0-9-]+)\s+\S+\s+\S+\s+(\S+)", s)
        if not m:
            continue
        out.append({"neighbor_id": m.group(1), "pri": m.group(2),
                    "state": m.group(3).upper(), "role": m.group(4),
                    "interface": m.group(5)})
    return out


def parse_bgp_ipv6_summary(output: str) -> list:
    """'show bgp ipv6 unicast summary' (IOS / IOS-XE / NX-OS) -> [{neighbor, as, state, prefixes}] per IPv6 BGP
    peer. The session is Established ONLY when the final 'State/PfxRcd' column is NUMERIC (the accepted-prefix
    count); any state WORD there (Idle / Active / Connect / OpenSent / OpenConfirm / Idle(Admin)) means the peer
    is not Established and exchanges no IPv6 routes. The 'Neighbor' value is an IPv6 address that, when long,
    wraps to its own line with the grid on the next line; both the single-line and wrapped forms are handled
    (delegated to the shared BGP-summary row parser). [] when no IPv6 BGP is configured. Tolerant; never raises."""
    return _parse_bgp_summary_rows(output)


def _aci_imdata(output: str, cls: str) -> list:
    """Extract the list of `attributes` dicts for one MO class from an APIC export -- the JSON that
    'moquery -c <cls> -o json' (or the REST GET /api/class/<cls>.json) returns: {totalCount, imdata:[{<cls>:
    {attributes:{...}}}]}. 'imdata' is the response container (not a class). This is the JSON-ingestion
    front door for controller-based fabrics (ACI/APIC): the engine reads the export file as text via the
    SAME _load_cmd_output path the show-text parsers use, and these normalizers json.load it instead of
    regex-matching it. Tolerant: [] on empty / non-JSON / missing-imdata; never raises."""
    try:
        obj = json.loads(output or "")
    except (ValueError, TypeError):
        return []
    rows = obj.get("imdata") if isinstance(obj, dict) else None
    out = []
    for it in rows or []:
        mo = it.get(cls) if isinstance(it, dict) else None
        attrs = mo.get("attributes") if isinstance(mo, dict) else None
        if isinstance(attrs, dict):
            # APIC attribute VALUES are strings on the wire; coerce defensively so a malformed export with a
            # non-string value can never make a downstream .lower()/re.search raise (no-op on real data).
            out.append({k: ("" if v is None else str(v)) for k, v in attrs.items()})
    return out


def parse_aci_faults(output: str) -> list:
    """APIC 'moquery -c faultInst -o json' / REST /api/class/faultInst.json -> [{code, severity, lc, ack,
    domain, cause, dn, descr}] per active fault. The APIC fault list IS the fabric's current broken-state
    inventory; severity is warning|minor|major|critical, lc (lifecycle) is soaking|raised|raised-clearing|
    retaining, ack is yes|no. A raised (lc=raised), unacknowledged (ack=no) critical/major fault is an
    active service-affecting condition. [] when no ACI export is present. Tolerant; never raises."""
    out = []
    for a in _aci_imdata(output, "faultInst"):
        out.append({"code": a.get("code", ""), "severity": (a.get("severity", "") or "").lower(),
                    "lc": (a.get("lc", "") or "").lower(), "ack": (a.get("ack", "") or "").lower(),
                    "domain": a.get("domain", ""), "cause": a.get("cause", ""),
                    "dn": a.get("dn", ""), "descr": a.get("descr", "")})
    return out


def parse_aci_fabric_nodes(output: str) -> list:
    """APIC 'moquery -c fabricNode -o json' / REST /api/class/fabricNode.json -> [{id, name, role, model,
    serial, version, fabric_st, ad_st, dn}] per fabric node. role is leaf|spine|controller; fabricSt is the
    OPERATIONAL state active|inactive|disabled|decommissioned; adSt is the ADMIN state on|off. A node present
    in the MIT but with fabricSt not 'active' is a ghost/decommissioned asset or an admin-vs-operational
    divergence. [] when no ACI export is present. Tolerant; never raises."""
    out = []
    for a in _aci_imdata(output, "fabricNode"):
        out.append({"id": a.get("id", ""), "name": a.get("name", ""), "role": a.get("role", ""),
                    "model": a.get("model", ""), "serial": a.get("serial", ""), "version": a.get("version", ""),
                    "fabric_st": (a.get("fabricSt", "") or "").lower(),
                    "ad_st": (a.get("adSt", "") or "").lower(), "dn": a.get("dn", "")})
    return out


def parse_aci_health(output: str) -> dict:
    """APIC 'moquery -c fabricHealthTotal -o json' / REST /api/class/fabricHealthTotal.json -> {cur, max_sev}
    -- the fabric-wide rollup health score (cur, 0-100) and the worst contributing severity (maxSev). {} when
    no ACI export is present or cur is non-numeric. Tolerant; never raises."""
    rows = _aci_imdata(output, "fabricHealthTotal")
    if not rows:
        return {}
    a = rows[0]
    try:
        cur = int(a.get("cur"))
    except (TypeError, ValueError):
        return {}
    return {"cur": cur, "max_sev": (a.get("maxSev", "") or "").lower()}


def parse_aci_vrfs(output: str) -> list:
    """APIC 'moquery -c fvCtx' / REST /api/class/fvCtx.json -> [{name, tenant, dn, pc_enf_pref, pc_enf_dir}]
    per VRF. fvCtx is the ACI routing context (the L3 segmentation boundary) and a primary migration
    move-group unit -- you migrate a fabric tenant/VRF at a time. pcEnfPref is 'enforced' (contracts / SGACLs
    applied between EPGs) or 'unenforced' (NO enforcement -- default-permit, every EPG in the VRF talks
    freely). The tenant is parsed from the dn (uni/tn-<tenant>/ctx-<name>). [] when no ACI export is present.
    Tolerant; never raises."""
    out = []
    for a in _aci_imdata(output, "fvCtx"):
        dn = a.get("dn", "")
        mt = re.search(r"/tn-([^/]+)/", dn)
        out.append({"name": a.get("name", ""), "tenant": mt.group(1) if mt else "", "dn": dn,
                    "pc_enf_pref": (a.get("pcEnfPref", "") or "").lower(),
                    "pc_enf_dir": (a.get("pcEnfDir", "") or "").lower()})
    return out


def parse_aci_tenants(output: str) -> list:
    """APIC 'moquery -c fvTenant' -> [{name, dn}] per tenant (the top-level ACI admin/policy container and a
    coarse migration move-group boundary). CENSUS only -- pure inventory, no broken-state (a tenant is not
    'wrong'). [] when no ACI export. Tolerant; never raises."""
    return [{"name": a.get("name", ""), "dn": a.get("dn", "")} for a in _aci_imdata(output, "fvTenant")]


def parse_aci_bds(output: str) -> list:
    """APIC 'moquery -c fvBD' -> [{name, tenant, dn, unicast_route, arp_flood}] per Bridge Domain (the ACI L2
    forwarding domain, ~ a VLAN/segment; a migration move-group unit). CENSUS; the route/flood flags are
    informational context. [] when no ACI export. Tolerant; never raises."""
    out = []
    for a in _aci_imdata(output, "fvBD"):
        dn = a.get("dn", "")
        mt = re.search(r"/tn-([^/]+)/", dn)
        out.append({"name": a.get("name", ""), "tenant": mt.group(1) if mt else "", "dn": dn,
                    "unicast_route": (a.get("unicastRoute", "") or "").lower(),
                    "arp_flood": (a.get("arpFlood", "") or "").lower()})
    return out


def parse_aci_epgs(output: str) -> list:
    """APIC 'moquery -c fvAEPg' -> [{name, tenant, dn}] per EPG (Endpoint Group -- the ACI segmentation unit
    that groups endpoints by policy; the FINEST migration move-group unit). CENSUS. [] when no ACI export.
    Tolerant; never raises."""
    out = []
    for a in _aci_imdata(output, "fvAEPg"):
        dn = a.get("dn", "")
        mt = re.search(r"/tn-([^/]+)/", dn)
        out.append({"name": a.get("name", ""), "tenant": mt.group(1) if mt else "", "dn": dn})
    return out


def _sdwan_data(output: str) -> list:
    """Catalyst SD-WAN Manager (vManage) /dataservice/* responses wrap their rows in {"data":[...]} -- flat
    JSON objects, NOT the ACI imdata/attributes envelope. The JSON-ingestion front door for the SD-WAN
    controller fabric (the overlay state lives in the Manager's NMS database, not the edge CLI). Tolerant:
    [] on empty / non-JSON / missing-'data'; never raises."""
    try:
        obj = json.loads(output or "")
    except (ValueError, TypeError):
        return []
    rows = obj.get("data") if isinstance(obj, dict) else None
    # Coerce values to strings defensively (no-op on real vManage data) so a malformed export with a
    # non-string state/reachability can never make a downstream .lower() raise; int reads re-parse the string.
    return [{k: ("" if v is None else str(v)) for k, v in r.items()} for r in (rows or []) if isinstance(r, dict)]


def parse_sdwan_control_connections(output: str) -> list:
    """vManage GET /dataservice/device/control/connections JSON -> [{system_ip, host_name, peer_type, state,
    local_color, expected, actual}] per control connection. state is up|down; a down connection (or
    actual-connections < expected-connections) to a Validator/vBond or Controller/vSmart means the WAN edge
    is losing its overlay control plane (no OMP routes / policy). expected/actual are ints (None if absent).
    [] when no SD-WAN export is present. Tolerant; never raises."""
    out = []
    for r in _sdwan_data(output):
        try:
            exp = int(r.get("expected-connections"))
        except (TypeError, ValueError):
            exp = None
        try:
            act = int(r.get("actual-connections"))
        except (TypeError, ValueError):
            act = None
        out.append({"system_ip": r.get("system-ip", ""), "host_name": r.get("host-name", ""),
                    "peer_type": r.get("peer-type", ""), "state": (r.get("state", "") or "").lower(),
                    "local_color": r.get("local-color", ""), "expected": exp, "actual": act})
    return out


def parse_sdwan_devices(output: str) -> list:
    """vManage GET /dataservice/device JSON -> [{system_ip, host_name, reachability, model, version}] per
    fabric device. reachability is reachable|unreachable -- the controller's own verdict on each WAN edge; an
    unreachable device is one the Manager has lost management/control contact with. [] when no SD-WAN export.
    Tolerant; never raises."""
    out = []
    for r in _sdwan_data(output):
        out.append({"system_ip": r.get("system-ip", ""), "host_name": r.get("host-name", ""),
                    "reachability": (r.get("reachability", "") or "").lower(),
                    "model": r.get("device-model", ""), "version": r.get("version", "")})
    return out


def parse_sdwan_omp_counters(output: str) -> list:
    """vManage GET /dataservice/device/counters JSON -> [{system_ip, host_name, omp_up, omp_down}] per WAN
    edge. The Manager's OWN count of OMP (Overlay Management Protocol) peers up vs down. OMP runs OVER the
    control connections and distributes the overlay routes / TLOCs / service routes between edges and the
    controllers; an edge with OMP peers DOWN is missing overlay routing even when its control connections are
    up (so traffic to the affected prefixes blackholes). [] when no SD-WAN counters export is present.
    Tolerant; never raises."""
    out = []
    for r in _sdwan_data(output):
        def _i(k):
            try:
                return int(r.get(k))
            except (TypeError, ValueError):
                return None
        out.append({"system_ip": r.get("system-ip", ""), "host_name": r.get("host-name", ""),
                    "omp_up": _i("ompPeersUp"), "omp_down": _i("ompPeersDown")})
    return out


def parse_nve_peers(output: str) -> list:
    """'show nve peers' (NX-OS AND IOS-XE Catalyst 9000 VXLAN) -> [{interface, peer_ip, state, learn_type}].
    State Up/Down; learn-type CP (control-plane / BGP-EVPN) vs DP (flood-and-learn). A down VTEP peer partitions
    the overlay. Two on-wire layouts: NX-OS 'Interface Peer-IP State LearnType ...' (the local IP is column 2)
    and IOS-XE 'Interface VNI Type(L2/L3CP) Peer-IP RMAC/Num_RTs eVNI state flags uptime' (column 2 is the VNI,
    the IP is column 4). [] when the device runs no NVE/VXLAN. Tolerant; never raises."""
    out = []
    ip = r"(?:\d+\.\d+\.\d+\.\d+|[0-9A-Fa-f:]*:[0-9A-Fa-f:]+)"
    for raw in (output or "").splitlines():
        # NX-OS: 'Interface Peer-IP State [LearnType] ...' -- the peer IP is the 2nd token
        m = re.match(r"^\s*(nve\d+)\s+(" + ip + r")\s+(\w+)(?:\s+(\w+))?", raw, re.IGNORECASE)
        if m:
            out.append({"interface": m.group(1).lower(), "peer_ip": m.group(2),
                        "state": m.group(3).capitalize(), "learn_type": (m.group(4) or "").upper()})
            continue
        # IOS-XE Catalyst 9000: 'Interface VNI Type(L2/L3CP) Peer-IP RMAC/Num_RTs eVNI state flags uptime'
        m2 = re.match(r"^\s*(nve\d+)\s+\d+\s+L[23]CP\s+(" + ip + r")\s+\S+\s+\d+\s+(\w+)", raw, re.IGNORECASE)
        if m2:
            out.append({"interface": m2.group(1).lower(), "peer_ip": m2.group(2),
                        "state": m2.group(3).capitalize(), "learn_type": "CP"})
    return out


def parse_hsrp_detail(output: str) -> Dict[tuple, dict]:
    """Full 'show standby [all]' DETAIL -> {(ifname, group): {state, priority, cfg_priority, preempt,
    preempt_delay, vip, vmac, hello, hold, standby_ip, track:[{obj,decrement}], version}}. The brief
    parser (parse_hsrp_summary) keeps only state+VIP; this captures the fields a senior FHRP audit needs
    -- election (priority/preempt), failure-awareness (tracking) -- the AJ fleet (no FHRP) never exercised.
    Tolerant: {} on empty / non-detail input; never raises."""
    res: Dict[tuple, dict] = {}
    cur = None
    for raw in (output or "").splitlines():
        s = raw.strip()
        h = re.match(r"^(\S+)\s+-\s+Group\s+(\d+)\b", s)             # 'Gi0/1 - Group 10' / 'Vlan50 - Group 50 (version 2)'
        if h:
            cur = (normalize_ifname(h.group(1)), h.group(2))
            ver = re.search(r"\(version\s+(\d+)\)", s)               # HSRPv2 headers carry a '(version N)' suffix
            res[cur] = {"state": "", "priority": None, "cfg_priority": None, "preempt": False,
                        "preempt_delay": None, "vip": "", "vmac": "", "hello": None, "hold": None,
                        "standby_ip": "", "track": [], "version": int(ver.group(1)) if ver else 1}
            continue
        if cur is None:
            continue
        r = res[cur]
        m = re.match(r"^State is (\w+)", s)
        if m: r["state"] = m.group(1); continue
        m = re.search(r"Virtual IP address is (\d+\.\d+\.\d+\.\d+)", s)
        if m: r["vip"] = m.group(1); continue
        m = re.search(r"virtual MAC address is ([0-9a-fA-F.]+)", s)
        if m and not r["vmac"]: r["vmac"] = m.group(1); continue
        m = re.search(r"Hello time (\d+) sec, hold time (\d+) sec", s)
        if m: r["hello"], r["hold"] = int(m.group(1)), int(m.group(2)); continue
        if s.startswith("Preemption enabled"):
            r["preempt"] = True
            md = re.search(r"delay min (\d+)", s)
            if md: r["preempt_delay"] = int(md.group(1))
            continue
        if s.startswith("Preemption disabled"):
            r["preempt"] = False; continue
        m = re.match(r"^Priority (\d+)(?:\s*\(configured (\d+)\))?", s)
        if m:
            r["priority"] = int(m.group(1))
            r["cfg_priority"] = int(m.group(2)) if m.group(2) else int(m.group(1)); continue
        m = re.search(r"Track object (\S+) state \w+ decrement (\d+)", s)
        if m: r["track"].append({"obj": m.group(1), "decrement": int(m.group(2))}); continue
        m = re.search(r"Standby router is (\d+\.\d+\.\d+\.\d+)", s)
        if m: r["standby_ip"] = m.group(1); continue
    return res


def parse_hsrp_summary(output: str) -> Dict[str, str]:
    res: Dict[str, str] = {}
    if not output:
        return res
    current_intf = ''
    current_grp = ''
    current_state = ''
    current_vip = ''
    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        # show standby brief / show hsrp brief tabular format:
        #   Interface  Grp  Pri P State  Active  Standby  Virtual-IP   (last IP = VIP)
        bm = re.match(r"^(Vl(?:an)?\d+|\S+)\s+(\d+)\s+\d+\s+[P\s]?\s*"
                      r"(Active|Standby|Listen|Speak|Init|Learn)\b", line, re.IGNORECASE)
        if bm:
            intf = re.sub(r"^Vl(\d)", r"Vlan\1", bm.group(1), flags=re.IGNORECASE)  # Vl10 -> Vlan10
            intf = normalize_ifname(intf)
            grp, state = bm.group(2), bm.group(3).capitalize()
            ips = re.findall(r"\b(\d+\.\d+\.\d+\.\d+)\b", line)
            vip = ips[-1] if ips else ''
            res[intf] = f'HSRP grp {grp} {state}' + (f' VIP {vip}' if vip else '')
            current_intf, current_grp, current_state = intf, grp, state
            continue
        m1 = re.match(r"^(Vlan\d+|\S+)\s+-?\s*Group\s*(\d+)\b.*?\b(Active|Standby|Listen|Speak|Init|Learn)\b", line, re.IGNORECASE)
        m2 = re.match(r"^(Vlan\d+|\S+)\s+(\d+)\s+(Active|Standby|Listen|Speak|Init|Learn)\b", line, re.IGNORECASE)
        m = m1 or m2
        if m:
            current_intf = normalize_ifname(m.group(1))
            current_grp = m.group(2)
            current_state = m.group(3).capitalize()
            # V14.11: VIP = last IP on the line (same heuristic as the brief branch),
            # instead of the old weak trailing optional capture that usually missed it.
            ips = re.findall(r"\b(\d+\.\d+\.\d+\.\d+)\b", line)
            current_vip = ips[-1] if ips else ''
            behavior = f'HSRP grp {current_grp} {current_state}' + (f' VIP {current_vip}' if current_vip else '')
            res[current_intf] = behavior
            continue
        if current_intf and 'virtual ip address is' in line.lower():
            m = re.search(r"virtual ip address is\s+(\d+\.\d+\.\d+\.\d+)", line, re.IGNORECASE)
            if m:
                vip = m.group(1)
                base = res.get(current_intf, f'HSRP grp {current_grp} {current_state}'.strip())
                if 'VIP' not in base:
                    res[current_intf] = base + f' VIP {vip}'
    return res

def parse_vrrp_summary(output: str) -> Dict[str, str]:
    """Parse 'show vrrp brief' (IOS + NX-OS) -> {ifname: 'VRRP grp N State VIP x'}.

    IOS:   Vlan10  1  100 3609   Y  Master  10.10.10.1   10.10.10.254  (last IP = VIP/Group addr)
    NX-OS: Vlan10  1  IPV4  100  100  Y  Master  10.10.10.254          (last IP = VIP)
    """
    res: Dict[str, str] = {}
    if not output:
        return res
    for raw in output.splitlines():
        s = raw.strip()
        if not s or s.lower().startswith("interface"):
            continue
        m = re.match(r"^(\S+)\s+(\d+)\b", s)
        if not m or not is_valid_iface(m.group(1)):
            continue
        st = re.search(r"\b(Master|Backup|Init|Listen)\b", s, re.IGNORECASE)
        if not st:
            continue
        ips = re.findall(r"\b(\d+\.\d+\.\d+\.\d+)\b", s)
        vip = ips[-1] if ips else ''
        ifn = normalize_ifname(m.group(1))
        res[ifn] = f'VRRP grp {m.group(2)} {st.group(1).capitalize()}' + (f' VIP {vip}' if vip else '')
    return res

def parse_glbp_summary(output: str) -> Dict[str, str]:
    """Parse 'show glbp brief' -> {ifname: 'GLBP grp N State VIP x'} (group rows only).

    Group row has Fwd column '-' and an IP in the Address column (the virtual IP):
      Vlan10  1  -  100  Active  10.10.10.254  local  10.10.10.3
    Forwarder rows (Fwd = 1/2/3, Address = a MAC) are ignored.
    """
    res: Dict[str, str] = {}
    if not output:
        return res
    for raw in output.splitlines():
        s = raw.strip()
        if not s or s.lower().startswith("interface"):
            continue
        m = re.match(r"^(\S+)\s+(\d+)\s+-\s+\S+\s+"
                     r"(Active|Standby|Listen|Init|Disabled)\b\s+(\d+\.\d+\.\d+\.\d+)",
                     s, re.IGNORECASE)
        if not m or not is_valid_iface(m.group(1)):
            continue
        ifn = normalize_ifname(m.group(1))
        res[ifn] = f'GLBP grp {m.group(2)} {m.group(3).capitalize()} VIP {m.group(4)}'
    return res


def parse_show_interface_status(output: str) -> Dict[str, Dict[str, str]]:
    res: Dict[str, Dict[str, str]] = {}
    col = None
    for line in output.splitlines():
        if ("Port" in line and "Name" in line and "Status" in line and
                "Vlan" in line and "Duplex" in line and "Speed" in line and "Type" in line):
            col = extract_fixed_cols(line, [
                ("Port","port"),("Name","name"),("Status","status"),("Vlan","vlan"),
                ("Duplex","duplex"),("Speed","speed"),("Type","type")])
            continue
        if not col or not line.strip() or "----" in line: continue
        port = normalize_ifname(slice_col(line, *col["port"]))
        if not port or not is_valid_iface(port): continue
        raw_duplex = slice_col(line, *col["duplex"])
        raw_speed  = slice_col(line, *col["speed"])
        if raw_speed.startswith("-") and raw_duplex.endswith(" a"):
            raw_speed  = "a" + raw_speed
            raw_duplex = raw_duplex[:-2].strip()
        res[port] = {
            "name":   slice_col(line, *col["name"]),
            "status": normalize_status(slice_col(line, *col["status"])),
            "vlan_raw": slice_col(line, *col["vlan"]),
            "duplex": normalize_duplex(raw_duplex),
            "speed":  normalize_speed(raw_speed),
            "type":   slice_col(line, *col["type"]),
        }
    return res

def parse_show_interface_switchport(output: str) -> Dict[str, Dict[str, str]]:
    res: Dict[str, Dict[str, str]] = {}
    current = None
    block: List[str] = []

    def commit(intf, lines):
        if not intf: return
        intf_n = normalize_ifname(intf)
        if not is_valid_iface(intf_n): return
        d = {"mode":"","access_vlan":"","access_vlan_name":"",
             "native_vlan":"","native_vlan_name":"","allowed_vlans":""}
        admin_mode = oper_mode = ""
        allowed_capture = False
        for ln in lines:
            low = ln.strip().lower()
            if low.startswith("administrative mode:"):
                admin_mode = ln.split(":",1)[1].strip()
            if low.startswith("operational mode:"):
                oper_mode = ln.split(":",1)[1].strip()
            if "access mode vlan:" in low:
                m = re.search(r"access mode vlan:\s*([0-9]+)\s*(?:\(([^)]+)\))?", ln, re.IGNORECASE)
                if m:
                    d["access_vlan"]      = m.group(1)
                    d["access_vlan_name"] = (m.group(2) or "").strip()
            if "trunking native" in low and "vlan" in low:
                m = re.search(r"vlan:\s*([0-9]+)\s*(?:\(([^)]+)\))?", ln, re.IGNORECASE)
                if m:
                    d["native_vlan"]      = m.group(1)
                    d["native_vlan_name"] = (m.group(2) or "").strip()
            if "trunking vlans allowed" in low:
                tail = ln.split(":",1)[1].strip() if ":" in ln else ""
                if tail: d["allowed_vlans"] = tail
                allowed_capture = True; continue
            if allowed_capture:
                if ":" in ln: allowed_capture = False
                else:
                    cont = ln.strip()
                    if cont: d["allowed_vlans"] = (d["allowed_vlans"]+","+cont).strip(",")
        mode = ""
        if "trunk" in (oper_mode or "").lower() or "trunk" in (admin_mode or "").lower():
            mode = "Trunk"
        elif "access" in (oper_mode or "").lower() or "access" in (admin_mode or "").lower():
            mode = "Access"
        d["mode"] = mode
        res[intf_n] = d

    for line in output.splitlines():
        m = re.match(r"^\s*Name:\s*(\S+)", line)
        if m:
            if current is not None: commit(current, block)
            current = m.group(1); block = []; continue
        if current is not None: block.append(line)
    if current is not None: commit(current, block)
    return res

def parse_show_interface_trunk_table(output: str) -> Dict[str, Dict[str, str]]:
    res: Dict[str, Dict[str, str]] = {}
    section = None
    nxos_top = False   # FIX-V3.23.9 (F841): ios_top was write-only; IOS is the implicit else
    for raw in output.splitlines():
        line = raw.strip()
        if not line or set(line) == {"-"}: continue
        if line.startswith("%"): continue
        low = line.lower()
        if low.startswith("port") and "mode" in low and "encapsulation" in low:
            section = "top"; nxos_top = False; continue
        if low.startswith("port") and "native" in low and "status" in low and "channel" in low:
            section = "top"; nxos_top = True; continue
        if low.startswith("port") and "native" in low and "status" in low:
            section = "top"; nxos_top = False; continue
        if low.startswith("port") and "vlans allowed on trunk" in low:
            section = "allowed"; nxos_top = False; continue
        if low.startswith("port") and ("vlans allowed" in low or "vlans in spanning" in low):
            section = "other"; continue
        if section == "top":
            parts = line.split()
            if len(parts) < 3: continue
            intf = normalize_ifname(parts[0])
            if not is_valid_iface(intf): continue
            res.setdefault(intf, {"native_vlan":"","status":"","port_channel":"","allowed_vlans":""})
            if nxos_top:
                res[intf]["native_vlan"] = parts[1] if parts[1].isdigit() else ""
                res[intf]["status"]      = parts[2] if len(parts) > 2 else ""
                po = parts[3] if len(parts) > 3 else "--"
                res[intf]["port_channel"] = "" if po in ("--","") else normalize_ifname(po)
            else:
                if len(parts) >= 5:
                    res[intf]["status"]      = parts[3]
                    res[intf]["native_vlan"] = parts[4] if parts[4].isdigit() else ""
                elif len(parts) == 4:
                    res[intf]["status"]      = parts[2]
                    res[intf]["native_vlan"] = parts[3] if parts[3].isdigit() else ""
                res[intf]["port_channel"] = ""
        if section == "allowed":
            parts = line.split(None, 1)
            if len(parts) == 2:
                intf  = normalize_ifname(parts[0])
                if not is_valid_iface(intf): continue
                vlans = parts[1].strip()
                if "feature vtp is not enabled" in vlans.lower(): vlans = ""
                res.setdefault(intf, {"native_vlan":"","status":"","port_channel":"","allowed_vlans":""})
                res[intf]["allowed_vlans"] = "" if vlans.lower() == "none" else vlans
    return res


def parse_show_mac_address_table(output: str) -> Dict[str, List[str]]:
    res: Dict[str, List[str]] = {}
    seen: Dict[str, set] = {}
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith(("VLAN","Legend","----","Total","Note")): continue
        parts = line.split()
        if len(parts) < 4: continue
        idx = 0
        if not parts[0].isdigit(): idx = 1
        if idx + 2 >= len(parts): continue
        mac   = parts[idx + 1]
        typ   = parts[idx + 2].lower()
        iface = parts[-1]
        if typ != "dynamic": continue
        mac_n = normalize_mac(mac)
        if_n  = normalize_ifname(iface)
        if not mac_n or not if_n: continue
        res.setdefault(if_n, []);  seen.setdefault(if_n, set())
        if mac_n not in seen[if_n]:
            res[if_n].append(mac_n); seen[if_n].add(mac_n)
    return res

def parse_spanning_tree_blockedports(output: str) -> Dict[str, bool]:
    blocked: Dict[str, bool] = {}
    for line in output.splitlines():
        for t in IFACE_TOKEN_RE.findall(line):
            blocked[normalize_ifname(t)] = True
    return blocked

def parse_vlan_brief(output: str) -> Dict[str, Dict[str, object]]:
    """Parse 'show vlan brief' (IOS + NX-OS) -> {vlan_id: {'name': str, 'ports': [ifnames]}}.

    Primary row: '<id> <name> <status> <ports...>'; port lists may wrap onto indented
    continuation lines, which are appended to the last VLAN seen.
    """
    res: Dict[str, Dict[str, object]] = {}
    cur: Optional[str] = None
    for raw in output.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        m = re.match(r"^(\d+)\s+(\S+)\s+(active|suspended|act/lshut|act/unsup|sus/lshut|\S+)\s*(.*)$", line)
        if m:
            cur = m.group(1)
            res[cur] = {"name": m.group(2), "ports": []}
            for t in IFACE_TOKEN_RE.findall(m.group(4) or ""):
                res[cur]["ports"].append(normalize_ifname(t))
        elif cur and re.match(r"^\s+\S", raw) and not re.match(r"^\s*(VLAN|----)", line, re.IGNORECASE):
            for t in IFACE_TOKEN_RE.findall(line):
                res[cur]["ports"].append(normalize_ifname(t))
    return res

_STP_STS_NAME = {"FWD": "Forwarding", "BLK": "Blocked", "BKN": "Blocked",
                 "LIS": "Listening", "LRN": "Learning", "DIS": "Disabled"}

def parse_spanning_tree_detail(output: str) -> Dict[str, Dict[str, List[str]]]:
    """Parse full 'show spanning-tree' -> {ifname: {state_name: [vlan/instance ids]}}.

    The output is organized per VLAN (Rapid-PVST) or per instance (MST):
        VLAN0010
        Interface  Role Sts Cost  Prio.Nbr Type
        Gi1/0/1    Root FWD 4     128.1    P2p
        Gi1/0/24   Altn BLK 19    128.24   P2p
    Each port row's status (FWD/BLK/...) is recorded under the current VLAN/instance.
    Under MST the captured ids are MST instance numbers, not VLAN ids.
    """
    detail: Dict[str, Dict[str, List[str]]] = {}
    if not output:
        return detail
    vhdr = re.compile(r"^(?:VLAN0*(\d+)|MST0*(\d+))\b", re.IGNORECASE)
    row  = re.compile(
        r"^(\S+)\s+(?:Root|Desg|Altn|Back|Boun|Mstr)\*?\s+(FWD|BLK|LIS|LRN|DIS|BKN)\b",
        re.IGNORECASE)
    cur: Optional[str] = None
    for raw in output.splitlines():
        s = raw.strip()
        if not s:
            continue
        vm = vhdr.match(s)
        if vm:
            cur = vm.group(1) or vm.group(2)
            continue
        m = row.match(s)
        if m and cur is not None and is_valid_iface(m.group(1)):
            ifn = normalize_ifname(m.group(1))
            st  = _STP_STS_NAME.get(m.group(2).upper())
            if st:
                lst = detail.setdefault(ifn, {}).setdefault(st, [])
                if cur not in lst:
                    lst.append(cur)
    return detail

def parse_spanning_tree_states(output: str) -> Dict[str, str]:
    """{ifname: collapsed STP state}. Blocked-wins summary, derived from the per-VLAN
    detail so the two views never disagree. NOT inferred from link-up."""
    out: Dict[str, str] = {}
    for ifn, st in parse_spanning_tree_detail(output).items():
        if st.get("Blocked"):      out[ifn] = "Blocked"
        elif st.get("Forwarding"): out[ifn] = "Forwarding"
        elif st.get("Learning"):   out[ifn] = "Learning"
        elif st.get("Listening"):  out[ifn] = "Listening"
        elif st.get("Disabled"):   out[ifn] = "Disabled"
    return out

# ----------------------------------------------------------------------------- #
# STP ROOT BRIDGE (NEW-V3.23.62) - parse the per-VLAN 'Root ID' / 'Bridge ID'
# blocks of 'show spanning-tree' (already collected) so the explorer can flag two
# design smells migrations love to inherit: (1) an ACCIDENTAL root -- a VLAN whose
# root runs the default priority (32768 + sys-id-ext), i.e. nobody deliberately
# elected a root, so it was won on a MAC tiebreak and can move unexpectedly; and
# (2) a root that is NOT the switch hosting the VLAN's gateway (suboptimal L2
# hairpinning). is_root is true when this switch's Root ID == its own Bridge ID.
# Tolerant; never raises. The interface-table rows are handled by the detail parser.
# ----------------------------------------------------------------------------- #
def parse_spanning_tree_root(output: str) -> Dict[str, dict]:
    """'show spanning-tree' -> {vlan: {root_priority:int|None, root_address:str,
    bridge_priority:int|None, is_root:bool}}; {} when none. is_root = this switch is the
    root for that VLAN (Root ID address == Bridge ID address, or an explicit root line)."""
    if not output:
        return {}
    vhdr = re.compile(r"^(?:VLAN0*(\d+)|MST0*(\d+))\b", re.IGNORECASE)
    raw_recs: Dict[str, dict] = {}
    cur: Optional[str] = None
    section: Optional[str] = None
    for raw in output.splitlines():
        s = raw.strip()
        if not s:
            continue
        vm = vhdr.match(s)
        if vm:
            cur = vm.group(1) or vm.group(2)
            raw_recs.setdefault(cur, {})
            section = None
            continue
        if cur is None:
            continue
        mroot = re.match(r"^Root\s+ID\s+Priority\s+(\d+)", s, re.IGNORECASE)
        if mroot:
            raw_recs[cur]["root_priority"] = int(mroot.group(1)); section = "root"; continue
        mbridge = re.match(r"^Bridge\s+ID\s+Priority\s+(\d+)", s, re.IGNORECASE)
        if mbridge:
            raw_recs[cur]["bridge_priority"] = int(mbridge.group(1)); section = "bridge"; continue
        maddr = re.match(r"^Address\s+([0-9A-Fa-f][0-9A-Fa-f.:]+)\s*$", s, re.IGNORECASE)
        if maddr and section in ("root", "bridge"):
            raw_recs[cur][section + "_address"] = normalize_mac(maddr.group(1)); continue
        if re.match(r"^This\s+bridge\s+is\s+the\s+root", s, re.IGNORECASE):
            raw_recs[cur]["is_root"] = True; continue
    out: Dict[str, dict] = {}
    for vlan, r in raw_recs.items():
        if not r:
            continue
        ra, ba = r.get("root_address"), r.get("bridge_address")
        is_root = bool(r.get("is_root")) or (bool(ra) and ra == ba)
        rec: dict = {"root_priority": r.get("root_priority"),
                     "root_address": ra or "", "is_root": is_root}
        if "bridge_priority" in r:
            rec["bridge_priority"] = r["bridge_priority"]
        out[vlan] = rec
    return out


def parse_vpc(output: str) -> dict:
    """'show vpc' (NX-OS) -> the device's vPC / MLAG status:
    {domain_id:int|None, role, peer_status, keepalive_status, consistency, num_vpcs:int,
     peer_link:{id,port,status,vlans}|None, vpcs:[{id,port,status,consistency,vlans}]}; {} when the
    device runs no vPC (command absent / errored / 'vPC is not configured'). Defensive: an unexpected
    NX-OS variant degrades to {} rather than raising. CONFIRMS MLAG/vPC peer pairs (vs the
    topology-inferred guess) for the flow simulator."""
    if not output or re.search(r"vPC\s+(?:feature\s+)?is\s+not\s+(?:enabled|configured)",
                               output, re.IGNORECASE):
        return {}

    def _kv(label: str) -> str:
        m = re.search(rf"^\s*{label}\s*:\s*(.+?)\s*$", output, re.IGNORECASE | re.MULTILINE)
        return m.group(1).strip() if m else ""

    out: dict = {"domain_id": None, "role": _kv(r"vPC role"),
                 "peer_status": _kv(r"Peer status"),
                 "keepalive_status": _kv(r"vPC keep-alive status"),
                 "consistency": _kv(r"Configuration consistency status"),
                 "num_vpcs": 0, "peer_link": None, "vpcs": []}
    dom = _kv(r"vPC domain id")
    if dom.isdigit():
        out["domain_id"] = int(dom)
    nv = _kv(r"Number of vPCs configured")
    if nv.isdigit():
        out["num_vpcs"] = int(nv)
    # peer-link table (single data row): "id  Port  Status  Active vlans"
    pl = re.search(r"vPC[ ]Peer-link[ ]status.*?\n(.*?)(?:\n[ \t]*\n|vPC[ ]status|\Z)",
                   output, re.IGNORECASE | re.DOTALL)
    if pl:
        for line in pl.group(1).splitlines():
            m = re.match(r"^\s*(\d+)\s+(Po\S+)\s+(\S+)\s+(.*)$", line, re.IGNORECASE)
            if m:
                out["peer_link"] = {"id": m.group(1), "port": m.group(2),
                                    "status": m.group(3).lower(), "vlans": m.group(4).strip()}
                break
    # vPC member table: "id  Port  Status  Consistency  Reason  Active vlans"
    vs = re.search(r"vPC[ ]status\b.*?\n(.*)$", output, re.IGNORECASE | re.DOTALL)
    if vs:
        for line in vs.group(1).splitlines():
            m = re.match(r"^\s*(\d+)\s+(Po\S+)\s+(\S+)\s+(\S+)\s+\S+\s+(.*)$", line, re.IGNORECASE)
            if m:
                out["vpcs"].append({"id": m.group(1), "port": m.group(2), "status": m.group(3).lower(),
                                    "consistency": m.group(4).lower(), "vlans": m.group(5).strip()})
    if out["domain_id"] is None and not out["vpcs"] and not out["peer_link"]:
        return {}
    return out


def _compress_vlans(vlans: List[str]) -> str:
    """[10, 20, 21, 22, 23] -> '10,20-23'. Non-numeric ids are appended as-is."""
    nums = sorted({int(v) for v in vlans if str(v).isdigit()})
    extra = [str(v) for v in vlans if not str(v).isdigit()]
    out: List[str] = []
    if nums:
        start = prev = nums[0]
        for v in nums[1:]:
            if v == prev + 1:
                prev = v; continue
            out.append(f"{start}-{prev}" if start != prev else f"{start}")
            start = prev = v
        out.append(f"{start}-{prev}" if start != prev else f"{start}")
    return ",".join(out + extra)

def parse_show_vrf_interface(output: str) -> Dict[str, str]:
    m: Dict[str, str] = {}
    for line in output.splitlines():
        line = line.strip()
        if not line or line.lower().startswith(("interface","vrf","----")): continue
        parts = line.split()
        if len(parts) >= 2 and is_valid_iface(parts[0]):
            m[normalize_ifname(parts[0])] = parts[1]
    return m

def parse_show_power_inline(output: str) -> Dict[str, str]:
    m: Dict[str, str] = {}
    for line in output.splitlines():
        if not line.strip(): continue
        it = IFACE_TOKEN_RE.search(line)
        if not it: continue
        intf = normalize_ifname(it.group(0))
        low  = line.lower()
        if "not supported" in low:   m[intf] = "Not Supported"
        elif "delivering" in low:    m[intf] = "Delivering"
        elif re.search(r"\bon\b", low): m[intf] = "Delivering"
        elif "searching" in low:     m[intf] = "Searching"
        elif "fault" in low:         m[intf] = "Fault"
        elif "deny" in low or "denied" in low: m[intf] = "Deny"
        elif "disabled" in low:      m[intf] = "Disabled"
        elif "off" in low:           m[intf] = "Off"
    return m

def parse_neighbors_cdp(output: str) -> Dict[str, Dict[str, str]]:
    res: Dict[str, Dict[str, str]] = {}
    for sec in re.split(r"-{5,}", output):
        sec = sec.strip()
        if not sec: continue
        device_id = platform_s = mgmt_ip = local_intf = remote_port = ""
        for line in sec.splitlines():
            line = line.strip()
            if line.lower().startswith("device id:"):
                device_id  = line.split(":",1)[1].strip()
            if line.lower().startswith("platform:"):
                platform_s = line.split(":",1)[1].strip()
                platform_s = re.split(r",\s*Capabilities", platform_s, 1)[0].strip()
            ipm = re.search(r"\bip address:\s*(\d+\.\d+\.\d+\.\d+)\b", line, re.IGNORECASE)
            if ipm: mgmt_ip = ipm.group(1)
            if line.lower().startswith("interface:"):
                mv = re.search(r"Interface:\s*([^,]+)", line, re.IGNORECASE)
                if mv: local_intf = normalize_ifname(mv.group(1).strip())
                pm = re.search(r"Port ID\s*\(outgoing port\):\s*(\S+)", line, re.IGNORECASE)
                if pm: remote_port = normalize_ifname(pm.group(1).strip())
        if local_intf:
            res[local_intf] = {"device_id": device_id, "platform": platform_s,
                               "mgmt_ip": mgmt_ip, "remote_port": remote_port}
    return res

def parse_neighbors_lldp(output: str) -> Dict[str, Dict[str, str]]:
    res: Dict[str, Dict[str, str]] = {}
    for ch in re.split(r"\n\s*Local Intf:\s*", "\n" + output):
        ch = ch.strip()
        if not ch: continue
        local   = normalize_ifname(ch.splitlines()[0].strip().split()[0])
        sysname = mgmt = remote_port = ""
        for line in ch.splitlines():
            ls = line.strip()
            if ls.lower().startswith("system name:"):
                sysname = ls.split(":",1)[1].strip()
            if ls.lower().startswith("port id:"):
                remote_port = normalize_ifname(ls.split(":",1)[1].strip())
            if ls.lower().startswith("management address:"):
                ipm = re.search(r"(\d+\.\d+\.\d+\.\d+)", ls)
                if ipm: mgmt = ipm.group(1)
        if local:
            res[local] = {"device_id": sysname, "platform": "", "mgmt_ip": mgmt,
                          "remote_port": remote_port}
    return res

_DESC_EP_PATTERNS = [
    (re.compile(r"\b(ap|access.?point|wap|aironet|wifi)\b",          re.I), "Access Point"),
    (re.compile(r"\b(ip.?phone|phone|voip|7[0-9]{3})\b",             re.I), "IP Phone"),
    (re.compile(r"\b(server|srv|esxi|vmware|ucs|blade)\b",            re.I), "Server"),
    (re.compile(r"\b(camera|cctv|ipcam|nvr)\b",                       re.I), "Camera"),
    (re.compile(r"\b(printer|mfp|copier)\b",                          re.I), "Printer"),
    (re.compile(r"\b(ups|pdu|apc|power.?supply)\b",                   re.I), "UPS/PDU"),
    (re.compile(r"\b(router|rtr|gateway|gw)\b",                       re.I), "Router"),
    (re.compile(r"\b(firewall|fw|asa|ftd|fortigate|palo)\b",          re.I), "Firewall"),
    (re.compile(r"\b(switch|sw|catalyst|nexus)\b",                    re.I), "Switch"),
    (re.compile(r"\b(storage|san|nas|emc|netapp|ds3|ds4)\b",          re.I), "Storage"),
]

def infer_endpoint_type(platform: str, device_id: str, description: str = "") -> str:
    p = (platform or "").lower(); d = (device_id or "").lower()
    if any(x in p for x in ["nexus","catalyst","cisco","ws-c"]): return "Switch"
    if any(x in p for x in ["asr","isr","csr","ncs"]):           return "Router"
    if any(x in p for x in ["asa","firepower","ftd"]):            return "Firewall"
    if any(x in d for x in ["esx","ucs","vm","srv","server"]):   return "Server"
    if platform or device_id: return "Neighbour"
    desc = (description or "").lower()
    for pat, label in _DESC_EP_PATTERNS:
        if pat.search(desc): return label
    return ""


def parse_run_config_interfaces(output: str) -> Dict[str, Dict[str, str]]:
    res: Dict[str, Dict[str, str]] = {}
    current = None
    global_bpduguard = False
    for line in output.splitlines():
        if re.search(r"spanning-tree portfast bpduguard default", line, re.IGNORECASE):
            global_bpduguard = True; continue
        m = re.match(r"^\s*interface\s+(\S+)", line, re.IGNORECASE)
        if m:
            current = normalize_ifname(m.group(1))
            res.setdefault(current, {"bpduguard":"","rootguard":"","pc_mode":"","pc_id":"","vrf":"","desc":"","portfast":"","ip_addr":"","acl_in":"","acl_out":"","mtu":"","helpers":""})
            if global_bpduguard:
                res[current]["bpduguard"] = "Enable"
            continue
        if not current: continue
        low = line.strip().lower()
        if low.startswith("description "):
            res[current]["desc"] = line.strip()[len("description "):].strip()
        # SVI / L3 interface IP. IOS: 'ip address 10.10.10.1 255.255.255.0'
        # NX-OS: 'ip address 10.10.10.1/24'. Skip secondary/dhcp/negotiated.
        if low.startswith("ip address ") and "secondary" not in low and "dhcp" not in low and "negotiated" not in low:
            mip = re.search(r"ip address\s+(\d+\.\d+\.\d+\.\d+)(?:\s+(\d+\.\d+\.\d+\.\d+)|/(\d+))",
                            line.strip(), re.IGNORECASE)
            if mip and not res[current].get("ip_addr"):
                ip = mip.group(1)
                if mip.group(3):                       # NX-OS prefix form
                    res[current]["ip_addr"] = f"{ip}/{mip.group(3)}"
                elif mip.group(2):                     # IOS dotted-mask form
                    res[current]["ip_addr"] = f"{ip} {mip.group(2)}"
                else:
                    res[current]["ip_addr"] = ip
        # L4/ACL flagging: SVI / L3 'ip access-group <name> {in|out}' (NOT L2 'ip port access-group')
        if low.startswith("ip access-group ") or low.startswith("ipv4 access-group "):
            ma = re.search(r"(?:ipv4|ip)\s+access-group\s+(\S+)\s+(in|out)\b", line.strip(), re.IGNORECASE)
            if ma:
                if ma.group(2).lower() == "in":  res[current]["acl_in"]  = ma.group(1)
                else:                            res[current]["acl_out"] = ma.group(1)
        if "spanning-tree bpduguard" in low:
            if "enable" in low:                         res[current]["bpduguard"] = "Enable"
            elif "disable" in low or low.endswith("no"): res[current]["bpduguard"] = "Disable"
        if "spanning-tree guard root" in low:
            res[current]["rootguard"] = "Disable" if low.startswith("no ") else "Enable"
        if "spanning-tree portfast" in low and "disable" not in low:
            res[current]["portfast"] = "Enable"
        if "channel-group" in low and "mode" in low:
            cm = re.search(r"channel-group\s+(\d+)\s+mode\s+(\S+)", low)
            if cm:
                res[current]["pc_id"]   = f"Po{cm.group(1)}"
                res[current]["pc_mode"] = cm.group(2)
        if low.startswith("vrf member "):    res[current]["vrf"] = line.strip().split()[-1]   # NX-OS
        if low.startswith("vrf forwarding "): res[current]["vrf"] = line.strip().split()[-1]   # IOS-XE
        if low.startswith("ip vrf forwarding "): res[current]["vrf"] = line.strip().split()[-1]   # legacy IOS
        # NEW-V3.23.49 (path-MTU mismatch): interface MTU (jumbo-frame detection). Prefer the L2/system
        # 'mtu N'; fall back to 'ip mtu N' only when no plain mtu is set. Default (1500, unset) stays blank.
        if low.startswith("mtu "):
            mm = re.match(r"mtu\s+(\d+)", low)
            if mm: res[current]["mtu"] = mm.group(1)
        elif low.startswith("ip mtu ") and not res[current].get("mtu"):
            mm = re.match(r"ip mtu\s+(\d+)", low)
            if mm: res[current]["mtu"] = mm.group(1)
        # DHCP relay: 'ip helper-address [vrf NAME|global] X' (IOS/IOS-XE) or 'ip dhcp relay address X'
        # (NX-OS). Multiple servers are allowed per interface, so accumulate them (de-duped, order-kept).
        mh = (re.match(r"ip helper-address\s+(?:vrf\s+\S+\s+|global\s+)?(\d+\.\d+\.\d+\.\d+)", low)
              or re.match(r"ip dhcp relay address\s+(\d+\.\d+\.\d+\.\d+)", low))
        if mh:
            cur = [h for h in res[current].get("helpers","").split(",") if h]
            if mh.group(1) not in cur: cur.append(mh.group(1))
            res[current]["helpers"] = ",".join(cur)
    return res

# ----------------------------------------------------------------------------- #
# ACL DEFINITIONS (L4 allow/deny sim) - parse 'ip access-list' / 'access-list'
# rule bodies out of the already-collected 'show running-config'. Normalizes each
# address to {ip, wild} (IOS wildcard form; NX-OS prefixes converted) so the JS
# evaluator in the explorer can match a 5-tuple. Rules it can't fully model
# (object-groups, unknown port names) carry 'unevaluable': True so the evaluator
# stays honest (INDETERMINATE, never a false PERMIT/DENY).
# ----------------------------------------------------------------------------- #
_ACL_PORT_NAMES = {
    "ftp-data":20,"ftp":21,"ssh":22,"telnet":23,"smtp":25,"domain":53,"tftp":69,"www":80,"http":80,
    "https":443,"pop3":110,"ntp":123,"snmp":161,"snmptrap":162,"bgp":179,"ldap":389,"ldaps":636,
    "isakmp":500,"syslog":514,"rip":520,"sip":5060,"bootps":67,"bootpc":68,"finger":79,"kerberos":88,
    "netbios-ns":137,"netbios-dgm":138,"netbios-ss":139,"msrpc":135,"rdp":3389,"sqlnet":1521,"mysql":3306,
}
_IPV4_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")

def _acl_portnum(tok: Optional[str]) -> Optional[int]:
    """Service name or numeric string -> int port; None if unknown (-> rule unevaluable)."""
    if tok is None: return None
    t = tok.strip().lower()
    if t.isdigit(): return int(t)
    return _ACL_PORT_NAMES.get(t)

def _acl_prefix_to_wild(plen: int) -> str:
    """CIDR length -> IOS wildcard dotted string. 24 -> '0.0.0.255'."""
    plen = max(0, min(32, plen))
    mask = (0xFFFFFFFF << (32 - plen)) & 0xFFFFFFFF if plen else 0
    wild = (~mask) & 0xFFFFFFFF
    return ".".join(str((wild >> s) & 0xFF) for s in (24, 16, 8, 0))

def _acl_addr(toks: List[str], i: int):
    """Consume one src/dst address spec at toks[i]. -> (addr|None, next_i, unevaluable)."""
    if i >= len(toks): return None, i, True
    t = toks[i]; tl = t.lower()
    if tl == "any":  return {"ip":"0.0.0.0","wild":"255.255.255.255"}, i+1, False
    if tl == "host":
        if i+1 < len(toks) and _IPV4_RE.match(toks[i+1]): return {"ip":toks[i+1],"wild":"0.0.0.0"}, i+2, False
        return None, i+2, True
    if tl in ("object-group","addrgroup","addr-group"):
        return {"group": toks[i+1] if i+1 < len(toks) else ""}, i+2, True
    m = re.match(r"^(\d{1,3}(?:\.\d{1,3}){3})/(\d{1,2})$", t)        # NX-OS prefix form
    if m: return {"ip":m.group(1),"wild":_acl_prefix_to_wild(int(m.group(2)))}, i+1, False
    if _IPV4_RE.match(t):
        if i+1 < len(toks) and _IPV4_RE.match(toks[i+1]): return {"ip":t,"wild":toks[i+1]}, i+2, False  # IOS addr+wildcard
        return {"ip":t,"wild":"0.0.0.0"}, i+1, False                  # bare host (standard ACL)
    return None, i+1, True

def _acl_port(toks: List[str], i: int):
    """Consume an optional port operator at toks[i]. -> (port|None, next_i)."""
    if i >= len(toks): return None, i
    op = toks[i].lower()
    if op in ("eq","neq","gt","lt"):
        return {"op":op,"val":_acl_portnum(toks[i+1] if i+1 < len(toks) else None)}, i+2
    if op == "range":
        return {"op":"range","val":_acl_portnum(toks[i+1] if i+1 < len(toks) else None),
                "val2":_acl_portnum(toks[i+2] if i+2 < len(toks) else None)}, i+3
    return None, i

_ANY_ADDR = {"ip":"0.0.0.0","wild":"255.255.255.255"}

def _acl_rule(action: str, rest: str, extended: bool) -> dict:
    """Parse one rule body (text after permit|deny) into a normalized rule dict."""
    toks = rest.split()
    rule: dict = {"action": action, "raw": (action + " " + rest).strip()}
    uneval = False
    if not extended:                                                  # standard: src only, proto=ip, dst=any
        src, _, u = _acl_addr(toks, 0)
        rule.update(proto="ip", src=src or dict(_ANY_ADDR), dst=dict(_ANY_ADDR), sport=None, dport=None)
        uneval = u or src is None
    elif not toks:
        rule.update(proto="ip", src=dict(_ANY_ADDR), dst=dict(_ANY_ADDR), sport=None, dport=None)
        uneval = True
    else:
        rule["proto"] = toks[0].lower(); i = 1
        src, i, u1 = _acl_addr(toks, i)
        sport, i = _acl_port(toks, i)
        dst, i, u2 = _acl_addr(toks, i)
        dport, i = _acl_port(toks, i)
        rule.update(src=src or dict(_ANY_ADDR), dst=dst or dict(_ANY_ADDR), sport=sport, dport=dport)
        uneval = u1 or u2 or src is None or dst is None
        if rule["proto"] == "icmp" and i < len(toks):                 # J: trailing icmp type/message token (echo, echo-reply, numeric, ...)
            rule["icmp_type"] = toks[i].lower()
    for p in (rule.get("sport"), rule.get("dport")):                  # unknown port name -> can't evaluate
        if p is not None and (p.get("val") is None or (p.get("op") == "range" and p.get("val2") is None)):
            uneval = True
    # NEW-V3.23.52 (stateful-ACL): trailing keywords. 'established' = TCP return-only (won't match a
    # NEW/forward connection); reflexive 'reflect' permits forward + auto-permits the return; a
    # 'time-range' makes the rule time-conditional (its match is indeterminate offline).
    low = rest.lower()
    if re.search(r"\bestablished\b", low): rule["established"] = True
    if re.search(r"\breflect\b", low):     rule["reflexive"] = True
    mt = re.search(r"\btime-range\s+(\S+)", rest, re.IGNORECASE)
    if mt: rule["time_range"] = mt.group(1)
    if uneval: rule["unevaluable"] = True
    return rule

def parse_acls(output: str) -> Dict[str, List[dict]]:
    """Parse ACL definitions from 'show running-config' -> {acl_name: [rule,...]}.

    Handles IOS numbered standard/extended one-liners, IOS named
    'ip access-list {standard|extended} NAME' blocks, and NX-OS
    'ip access-list NAME' blocks. Tolerant: unrecognized lines are skipped,
    never raises. The 'ip access-group' APPLICATION lines are NOT touched here
    (parse_run_config_interfaces handles those)."""
    acls: Dict[str, List[dict]] = {}
    if not output: return acls
    cur: Optional[str] = None       # current named ACL
    cur_ext = True
    STD_EXT_RE = re.compile(r"^\s*ip\s+access-list\s+(standard|extended)\s+(\S+)", re.IGNORECASE)
    NXOS_RE    = re.compile(r"^\s*ip\s+access-list\s+(\S+)\s*$", re.IGNORECASE)
    NUM_RE     = re.compile(r"^\s*access-list\s+(\d+)\s+(permit|deny)\s+(.*)$", re.IGNORECASE)
    CHILD_RE   = re.compile(r"^\s*(?:\d+\s+)?(permit|deny)\s+(.*)$", re.IGNORECASE)
    for raw in output.splitlines():
        line = raw.rstrip()
        if not line.strip(): continue
        mnum = NUM_RE.match(line)                                     # numbered one-liner (col 0)
        if mnum:
            num, action, rest = mnum.group(1), mnum.group(2).lower(), mnum.group(3)
            n = int(num); ext = (100 <= n <= 199) or (2000 <= n <= 2699)
            acls.setdefault(num, []).append(_acl_rule(action, rest, ext)); cur = None; continue
        msx = STD_EXT_RE.match(line)                                  # IOS named header
        if msx:
            cur_ext = msx.group(1).lower() == "extended"; cur = msx.group(2); acls.setdefault(cur, []); continue
        mnx = NXOS_RE.match(line)                                     # NX-OS header (no standard/extended kw)
        if mnx:
            cur = mnx.group(1); cur_ext = True; acls.setdefault(cur, []); continue
        if cur is not None and raw[:1].isspace():                     # indented child rule
            mc = CHILD_RE.match(line)
            if mc: acls[cur].append(_acl_rule(mc.group(1).lower(), mc.group(2), cur_ext)); continue
            continue                                                  # remark / other indented line -> skip
        cur = None                                                    # any col-0 non-ACL line ends the block
    return acls

# ----------------------------------------------------------------------------- #
# OBJECT-GROUPS (L4 depth) - parse 'object-group network|service' (IOS) and
# 'object-group ip address|ip port' (NX-OS) definitions so the explorer can
# resolve ACL rules that reference them (addrgroup/object-group), turning what
# was INDETERMINATE into a definite allow/deny. Network members normalize to the
# same {ip,wild} form ACL addresses use (IOS subnet mask -> wildcard).
# ----------------------------------------------------------------------------- #
def _mask_to_wild(mask: str) -> str:
    """IOS subnet mask (255.255.255.0) -> wildcard (0.0.0.255), per-octet inverse."""
    try: return ".".join(str(255 - int(o)) for o in mask.split("."))
    except (ValueError, TypeError): return mask

def _objgrp_net_member(toks: List[str]):
    """One 'object-group network' member -> {ip,wild} | {rangeStart,rangeEnd} | {group} | None."""
    t0 = toks[0].lower()
    if t0 == "host" and len(toks) >= 2 and _IPV4_RE.match(toks[1]): return {"ip": toks[1], "wild": "0.0.0.0"}
    if t0 == "group-object" and len(toks) >= 2: return {"group": toks[1]}
    if t0 == "range" and len(toks) >= 3 and _IPV4_RE.match(toks[1]) and _IPV4_RE.match(toks[2]):
        return {"rangeStart": toks[1], "rangeEnd": toks[2]}
    m = re.match(r"^(\d{1,3}(?:\.\d{1,3}){3})/(\d{1,2})$", toks[0])     # NX-OS prefix
    if m: return {"ip": m.group(1), "wild": _acl_prefix_to_wild(int(m.group(2)))}
    if _IPV4_RE.match(toks[0]):
        if len(toks) >= 2 and _IPV4_RE.match(toks[1]): return {"ip": toks[0], "wild": _mask_to_wild(toks[1])}  # IOS subnet+mask
        return {"ip": toks[0], "wild": "0.0.0.0"}                       # bare host
    return None

def _objgrp_svc_member(toks: List[str]):
    """One 'object-group service|ip port' member -> {proto?, op?, val?, val2?} | None."""
    proto = None; i = 0
    if toks[0].lower() in ("tcp", "udp", "ip", "icmp", "tcp-udp"): proto = toks[0].lower(); i = 1
    mem: dict = {"proto": proto} if proto else {}
    p, _ = _acl_port(toks, i)
    if p:
        mem["op"] = p["op"]; mem["val"] = p.get("val")
        if "val2" in p: mem["val2"] = p["val2"]
    return mem or None

def parse_object_groups(output: str) -> Dict[str, dict]:
    """Parse object-group definitions from 'show running-config'
    -> {name: {kind:'network'|'service', members:[...]}}. Tolerant; never raises."""
    groups: Dict[str, dict] = {}
    if not output: return groups
    cur: Optional[str] = None; kind = "network"
    HDR = re.compile(r"^\s*object-group\s+(network|service|ip\s+address|ip\s+port)\s+(\S+)", re.IGNORECASE)
    for raw in output.splitlines():
        line = raw.rstrip()
        if not line.strip(): continue
        m = HDR.match(line)
        if m:
            t = m.group(1).lower().replace(" ", "")
            kind = "service" if t in ("service", "ipport") else "network"
            cur = m.group(2); groups.setdefault(cur, {"kind": kind, "members": []}); continue
        if cur is None: continue
        if not raw[:1].isspace(): cur = None; continue                  # col-0 line ends the group
        toks = line.strip().split()
        if not toks: continue
        if toks[0].isdigit() and len(toks) > 1: toks = toks[1:]         # strip NX-OS sequence number
        if toks[0].lower() in ("description", "remark"): continue
        mem = _objgrp_net_member(toks) if kind == "network" else _objgrp_svc_member(toks)
        if mem: groups[cur]["members"].append(mem)
    return groups

# ----------------------------------------------------------------------------- #
# NAT inventory (NEW-V3.23.50) - parse IOS NAT configuration from the already-collected
# 'show running-config'. A migration must recreate every NAT rule on the new platform, so
# this is an inventory first; the explorer's flow-flagging consumes it next. Tolerant: any
# unrecognized line is skipped, never raises. Handles per-interface 'ip nat inside|outside',
# static 1:1 + static PAT (port forward), dynamic NAT/PAT (list -> pool|interface [overload]),
# and 'ip nat pool' definitions. Inside-source statics map LOCAL->GLOBAL; outside-source swap.
# ----------------------------------------------------------------------------- #
def parse_nat(output: str) -> dict:
    """Parse NAT config -> {static:[{direction,proto,local,global[,local_port,global_port]}],
    dynamic:[{acl,kind,via,overload}], pools:{name:{start,end}}, inside:[iface], outside:[iface]};
    {} when no NAT is configured. Tolerant; never raises."""
    if not output:
        return {}
    static: List[dict] = []
    dynamic: List[dict] = []
    pools: Dict[str, dict] = {}
    inside: List[str] = []
    outside: List[str] = []
    cur: Optional[str] = None
    STATIC = re.compile(
        r"^\s*ip\s+nat\s+(inside|outside)\s+source\s+static\s+(?:(tcp|udp)\s+)?"
        r"(\d{1,3}(?:\.\d{1,3}){3})(?:\s+(\d+))?\s+(\d{1,3}(?:\.\d{1,3}){3})(?:\s+(\d+))?", re.IGNORECASE)
    DYN = re.compile(
        r"^\s*ip\s+nat\s+inside\s+source\s+list\s+(\S+)\s+(?:pool\s+(\S+)|interface\s+(\S+))(\s+overload)?",
        re.IGNORECASE)
    POOL = re.compile(
        r"^\s*ip\s+nat\s+pool\s+(\S+)\s+(\d{1,3}(?:\.\d{1,3}){3})\s+(\d{1,3}(?:\.\d{1,3}){3})", re.IGNORECASE)
    for raw in output.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        indented = raw[:1].isspace()
        mi = re.match(r"^\s*interface\s+(\S+)", line, re.IGNORECASE)
        if mi and not indented:
            cur = normalize_ifname(mi.group(1)); continue
        if indented:
            if cur is not None:
                low = line.strip().lower()
                if low == "ip nat inside":  inside.append(cur)
                elif low == "ip nat outside": outside.append(cur)
            continue                                                    # indented line stays within the interface block
        cur = None                                                      # any col-0 line ends the interface block
        ms = STATIC.match(line)
        if ms:
            direction, proto, a, ap, b, bp = ms.groups()
            rule: dict = {"direction": direction.lower(), "proto": (proto or "").lower()}
            # inside-source: LOCAL GLOBAL ; outside-source: GLOBAL LOCAL (swap)
            if direction.lower() == "inside":
                rule["local"], rule["global"] = a, b
                if proto: rule["local_port"], rule["global_port"] = (ap or ""), (bp or "")
            else:
                rule["global"], rule["local"] = a, b
                if proto: rule["global_port"], rule["local_port"] = (ap or ""), (bp or "")
            static.append(rule); continue
        md = DYN.match(line)
        if md:
            dynamic.append({"acl": md.group(1),
                            "kind": "pool" if md.group(2) else "interface",
                            "via": md.group(2) or normalize_ifname(md.group(3) or ""),
                            "overload": bool(md.group(4))}); continue
        mp = POOL.match(line)
        if mp:
            pools[mp.group(1)] = {"start": mp.group(2), "end": mp.group(3)}; continue
    if not (static or dynamic or pools or inside or outside):
        return {}
    return {"static": static, "dynamic": dynamic, "pools": pools,
            "inside": sorted(set(inside)), "outside": sorted(set(outside))}


# ----------------------------------------------------------------------------- #
# SECURITY / COMPLIANCE posture (NEW-V3.23.59) - CIS Cisco-benchmark-aligned config
# hardening checks parsed from the already-collected 'show running-config'. A migration is
# the moment to remediate (or consciously carry) config technical debt, and these gaps are
# invisible to the connectivity engine. Tolerant: any unrecognized line is skipped, never
# raises. CRITICAL: records the *presence/type* of a secret, NEVER its value -- SNMP
# community strings, keys and password hashes are redacted before they reach the snapshot
# (the single-file HTML must be safe to share). {} when no run-config; otherwise
# {findings:[{id,title,severity,status,detail,cis_ref,remediation}], summary:{fail,pass,na,grade}}.
# ----------------------------------------------------------------------------- #
# id -> (title, severity-when-failing, cis_ref, remediation)
_SEC_CHECKS: Dict[str, Tuple[str, str, str, str]] = {
    "password-encryption": ("Password encryption service", "medium", "CIS 1.1.1",
        "Configure 'service password-encryption' and migrate Type-7 secrets to Type-8/9."),
    "weak-enable": ("Privileged-EXEC secret", "high", "CIS 1.2.1",
        "Use 'enable secret' (Type-8/9), not 'enable password' (Type-0/7)."),
    "weak-user-pw": ("Local user password storage", "high", "CIS 1.3",
        "Store local users with 'secret' (Type-8/9); remove Type-0/7 'password' entries."),
    "no-aaa": ("AAA new-model", "medium", "CIS 1.4",
        "Enable 'aaa new-model' for centralized authentication / authorization / accounting."),
    "insecure-snmp": ("SNMP access", "high", "CIS 3.1",
        "Remove SNMPv1/v2c communities; use SNMPv3 with auth+priv (SHA/AES)."),
    "telnet-enabled": ("VTY transport (telnet)", "high", "CIS 2.1",
        "Set 'transport input ssh' on every VTY line; disable telnet."),
    "risky-services": ("Unused / risky services", "medium", "CIS 1.5",
        "Disable HTTP server, Smart Install, source-route, bootp, finger and 'service config'."),
    "no-ntp": ("NTP time synchronization", "low", "CIS 6.1",
        "Configure an authenticated 'ntp server' so logs and certificate validity are trustworthy."),
    "no-logging": ("Logging / audit trail", "low", "CIS 6.2",
        "Configure 'logging host' / 'logging buffered' to retain an audit trail."),
    "no-banner": ("Login banner", "low", "CIS 1.6",
        "Configure a 'banner login' / 'banner motd' legal-notice banner."),
    "vty-hardening": ("VTY line hardening", "medium", "CIS 2.2",
        "Apply an 'access-class' ACL and a non-zero 'exec-timeout' on every VTY line."),
}


def parse_security(output: str) -> dict:
    """'show running-config' -> CIS-aligned security/compliance posture
    {findings:[{id,title,severity,status,detail,cis_ref,remediation}], summary:{fail,pass,na,grade}};
    {} when output is empty. Tolerant; never raises. Secret values (SNMP communities, password
    hashes) are NEVER stored -- only their presence/type, with the value redacted to '<redacted>'."""
    if not output:
        return {}
    low = [ln.strip().lower() for ln in output.splitlines()]

    def has(pat: str) -> bool:
        return any(re.search(pat, ln) for ln in low)

    svc_pwenc = has(r"^service password-encryption\b")
    enable_secret = has(r"^enable secret\b")
    enable_pw = has(r"^enable password\b")
    # NOS-aware: IOS/IOS-XE use 'aaa new-model'; NX-OS / IOS-XR enable central AAA via
    # 'aaa authentication login default group ...' / 'aaa group server tacacs+|radius' (no 'new-model').
    aaa = (has(r"^aaa new-model\b")
           or has(r"^aaa authentication login default group\b")
           or has(r"^aaa group server (tacacs\+|radius)\b"))
    ntp = has(r"^ntp (server|peer)\b")
    logging_on = has(r"^logging (host|buffered|server)\b")
    banner = has(r"^banner (motd|login|exec)\b")
    snmpv3 = has(r"^snmp-server (group|user)\b")

    weak_users: List[str] = []
    for ln in low:
        m = re.match(r"^username\s+(\S+)\s+.*\bpassword\b", ln)
        if m and " secret " not in (" " + ln + " "):
            weak_users.append(m.group(1))

    snmp_comm: List[dict] = []
    for ln in low:
        m = re.match(r"^snmp-server community\s+(\S+)(?:\s+(ro|rw))?", ln)
        if m:
            snmp_comm.append({"access": m.group(2) or "ro",
                              "default": m.group(1) in ("public", "private")})

    risky: List[str] = []
    if has(r"^ip http server\b") and not has(r"^no ip http server\b"):
        risky.append("HTTP server (cleartext)")
    if has(r"^vstack\b") and not has(r"^no vstack\b"):
        risky.append("Smart Install (vstack)")
    if has(r"^service config\b"):
        risky.append("service config (network boot)")
    if has(r"^ip source-route\b") and not has(r"^no ip source-route\b"):
        risky.append("ip source-route")
    if has(r"^ip bootp server\b") and not has(r"^no ip bootp server\b"):
        risky.append("ip bootp server")
    if has(r"^service finger\b"):
        risky.append("service finger")

    vty: List[dict] = []
    cur: Optional[dict] = None
    for raw in output.splitlines():
        s = raw.strip().lower()
        if re.match(r"^line vty\b", s):
            cur = {"transport": "", "access_class": False, "timeout0": False}
            vty.append(cur)
            continue
        if re.match(r"^line\b", s):                              # a different line block ends the vty block
            cur = None
            continue
        if cur is not None and raw[:1].isspace():
            if s.startswith("transport input"):
                cur["transport"] = s.replace("transport input", "").strip()
            elif s.startswith("access-class"):
                cur["access_class"] = True
            elif re.match(r"^exec-timeout\s+0\s+0\b", s):
                cur["timeout0"] = True
    telnet = any("telnet" in b["transport"] or b["transport"] == "all" for b in vty)
    vty_weak = any((not b["access_class"]) or b["timeout0"] for b in vty)

    findings: List[dict] = []

    def add(cid: str, status: str, detail: str, severity: Optional[str] = None) -> None:
        title, sev, ref, rem = _SEC_CHECKS[cid]
        findings.append({"id": cid, "title": title,
                         "severity": (severity or sev) if status == "fail" else "info",
                         "status": status, "detail": detail, "cis_ref": ref, "remediation": rem})

    # Absence-of-a-control -> fail (the hardening baseline is missing).
    add("password-encryption", "pass" if svc_pwenc else "fail",
        "'service password-encryption' is set." if svc_pwenc
        else "no 'service password-encryption' -- passwords can be stored in cleartext (Type-0).")
    add("no-aaa", "pass" if aaa else "fail",
        "central AAA (TACACS+/RADIUS) is configured." if aaa
        else "no central AAA ('aaa new-model' / 'aaa authentication login default group') -- "
             "authentication is local-only / line-based.")
    add("no-ntp", "pass" if ntp else "fail",
        "NTP server configured." if ntp
        else "no NTP server -- clock drift makes logs and certificate validity untrustworthy.")
    add("no-logging", "pass" if logging_on else "fail",
        "syslog / buffered logging configured." if logging_on
        else "no syslog / buffered logging -- no audit trail across the migration.")
    add("no-banner", "pass" if banner else "fail",
        "login / MOTD banner present." if banner
        else "no login / MOTD legal-notice banner.")

    # Presence-of-a-bad-pattern -> fail.
    if enable_pw:
        add("weak-enable", "fail",
            "'enable password' is reversible (Type-0/7) -- use 'enable secret'.")
    elif enable_secret:
        add("weak-enable", "pass", "'enable secret' configured.")
    else:
        add("weak-enable", "na", "no enable password / secret found in this config.")

    if weak_users:
        names = ", ".join(sorted(set(weak_users)))
        add("weak-user-pw", "fail",
            f"{len(set(weak_users))} local user(s) use a reversible / cleartext password: "
            f"{names} (hashes redacted).")
    else:
        add("weak-user-pw", "pass", "no Type-0/7 local user passwords.")

    if snmp_comm:
        rw = any(c["access"] == "rw" for c in snmp_comm)
        dflt = any(c["default"] for c in snmp_comm)
        bits: List[str] = []
        if dflt:
            bits.append("a default community (public/private)")
        if rw:
            bits.append("a read-write community")
        bits.append(f"{len(snmp_comm)} v1/v2c community string(s) '<redacted>'")
        add("insecure-snmp", "fail",
            "; ".join(bits) + " -- v1/v2c carry the community in cleartext.",
            severity="high" if (rw or dflt) else "medium")
    elif snmpv3:
        add("insecure-snmp", "pass", "SNMPv3 (auth/priv) only -- no v1/v2c communities.")
    else:
        add("insecure-snmp", "na", "no SNMP configured.")

    if not vty:
        add("telnet-enabled", "na", "no VTY lines in this config.")
        add("vty-hardening", "na", "no VTY lines in this config.")
    else:
        add("telnet-enabled", "fail" if telnet else "pass",
            "a VTY line permits telnet (cleartext management)." if telnet
            else "VTY transport restricted to SSH.")
        add("vty-hardening", "fail" if vty_weak else "pass",
            "a VTY line is missing an 'access-class' ACL or never times out (exec-timeout 0 0)."
            if vty_weak else "VTY lines carry an access-class and a non-zero exec-timeout.")

    if risky:
        add("risky-services", "fail", "enabled: " + ", ".join(risky) + ".")
    else:
        add("risky-services", "pass", "no risky / unused services enabled.")

    nfail = sum(1 for f in findings if f["status"] == "fail")
    npass = sum(1 for f in findings if f["status"] == "pass")
    nna = sum(1 for f in findings if f["status"] == "na")
    high = any(f["status"] == "fail" and f["severity"] == "high" for f in findings)
    grade = "weak" if high else ("partial" if nfail else "hardened")
    return {"findings": findings,
            "summary": {"fail": nfail, "pass": npass, "na": nna, "grade": grade}}


# ----------------------------------------------------------------------------- #
# CONFIG HYGIENE (NEW-V3.23.61) - Batfish-style static cross-reference over the
# already-collected 'show running-config': (1) UNDEFINED references -- a named
# ACL / route-map / object-group / prefix-list that is *referenced* but never
# *defined* (silently does nothing -> a classic migration-breaker), and (2) UNUSED
# structures -- a named structure *defined* but never *referenced* (cruft to drop
# at cutover). Order-independent (all defs gathered, then all refs). Tolerant: any
# unrecognized line is skipped, never raises. Conservative on purpose -- only the
# four well-bounded structure kinds and high-confidence reference forms, so it does
# not 'cry wolf'. {} when the config defines/references none of them.
# ----------------------------------------------------------------------------- #
_HYGIENE_KINDS = ("acl", "route-map", "object-group", "prefix-list")
# A captured name equal to one of these is a mis-parse of a keyword, not a real reference.
_HYGIENE_RESERVED = {"in", "out", "prefix", "prefix-list", "route-map", "network",
                     "service", "ip", "ipv6", "gateway", "interface", "any", "host"}


def parse_config_hygiene(output: str) -> dict:
    """'show running-config' -> {undefined:[{kind,name,context}], unused:[{kind,name}],
    summary:{undefined,unused,structures}}; {} when no ACL/route-map/object-group/prefix-list
    is defined or referenced. Tolerant; never raises.

    undefined = referenced-but-not-defined (a real bug). unused = defined-but-not-referenced
    (advisory: 'no reference found in this running-config')."""
    if not output:
        return {}
    defs: Dict[str, set] = {k: set() for k in _HYGIENE_KINDS}
    refs: List[dict] = []

    D_ACL_NAMED = re.compile(r"^\s*ip\s+access-list\s+(?:standard|extended)\s+(\S+)", re.IGNORECASE)
    D_ACL_NX    = re.compile(r"^\s*ip\s+access-list\s+(\S+)\s*$", re.IGNORECASE)
    D_ACL_V6    = re.compile(r"^\s*ipv6\s+access-list\s+(\S+)", re.IGNORECASE)
    D_ACL_NUM   = re.compile(r"^\s*access-list\s+(\d+)\s+", re.IGNORECASE)
    D_RMAP      = re.compile(r"^\s*route-map\s+(\S+)", re.IGNORECASE)
    D_OBJG      = re.compile(r"^\s*object-group\s+(?:network|service|ip\s+address|ip\s+port)\s+(\S+)", re.IGNORECASE)
    D_PLIST     = re.compile(r"^\s*ip(?:v6)?\s+prefix-list\s+(\S+)", re.IGNORECASE)

    # (regex, kind) -- high-confidence reference forms only.
    REF_RX = [
        (re.compile(r"\bip\s+access-group\s+(\S+)\s+(?:in|out)\b", re.IGNORECASE), "acl"),
        (re.compile(r"\baccess-class\s+(\S+)\s+(?:in|out)\b", re.IGNORECASE), "acl"),
        (re.compile(r"\bipv6\s+traffic-filter\s+(\S+)\s+(?:in|out)\b", re.IGNORECASE), "acl"),
        (re.compile(r"\bip\s+nat\s+(?:inside|outside)\s+source\s+list\s+(\S+)", re.IGNORECASE), "acl"),
        (re.compile(r"\bmatch\s+ip\s+address\s+(?!prefix-list\b)(\S+)", re.IGNORECASE), "acl"),
        (re.compile(r"\bredistribute\b.*\broute-map\s+(\S+)", re.IGNORECASE), "route-map"),
        (re.compile(r"\bneighbor\s+\S+\s+route-map\s+(\S+)\s+(?:in|out)\b", re.IGNORECASE), "route-map"),
        (re.compile(r"\bip\s+policy\s+route-map\s+(\S+)", re.IGNORECASE), "route-map"),
        (re.compile(r"\bmatch\s+ip\s+address\s+prefix-list\s+(\S+)", re.IGNORECASE), "prefix-list"),
        (re.compile(r"\bneighbor\s+\S+\s+prefix-list\s+(\S+)\s+(?:in|out)\b", re.IGNORECASE), "prefix-list"),
        (re.compile(r"\bdistribute-list\s+prefix\s+(\S+)", re.IGNORECASE), "prefix-list"),
    ]
    OBJG_REF = re.compile(r"\bobject-group\s+(\S+)", re.IGNORECASE)
    GRPOBJ_REF = re.compile(r"\bgroup-object\s+(\S+)", re.IGNORECASE)

    ctx = ""
    for raw in output.splitlines():
        line = raw.rstrip()
        s = line.strip()
        if not s:
            continue
        if not raw[:1].isspace():                                   # col-0 stanza header = context for any ref below it
            ctx = s[:60]
        if s.lower().startswith(("remark ", "description ")):       # free text -> never a def/ref
            continue
        # --- definitions ---
        md = D_ACL_NAMED.match(line) or D_ACL_NX.match(line) or D_ACL_V6.match(line)
        if md:
            defs["acl"].add(md.group(1))
        else:
            mn = D_ACL_NUM.match(line)
            if mn:
                defs["acl"].add(mn.group(1))
        mr = D_RMAP.match(line)
        if mr:
            defs["route-map"].add(mr.group(1))
        mo = D_OBJG.match(line)
        if mo:
            defs["object-group"].add(mo.group(1))
        mp = D_PLIST.match(line)
        if mp:
            defs["prefix-list"].add(mp.group(1))
        # --- references ---
        for rx, kind in REF_RX:
            for m in rx.finditer(line):
                nm = m.group(1)
                if nm.lower() not in _HYGIENE_RESERVED:
                    refs.append({"kind": kind, "name": nm, "context": ctx})
        for m in OBJG_REF.finditer(line):                           # 'object-group NAME' inside an ACL rule (not a def header)
            nm = m.group(1)
            if nm.lower() not in _HYGIENE_RESERVED:
                refs.append({"kind": "object-group", "name": nm, "context": ctx})
        for m in GRPOBJ_REF.finditer(line):                         # nested 'group-object NAME'
            nm = m.group(1)
            if nm.lower() not in _HYGIENE_RESERVED:
                refs.append({"kind": "object-group", "name": nm, "context": ctx})

    referenced: Dict[str, set] = {k: set() for k in _HYGIENE_KINDS}
    for r in refs:
        referenced[r["kind"]].add(r["name"])
    undefined_map: Dict[tuple, dict] = {}
    for r in refs:
        if r["name"] not in defs[r["kind"]]:
            undefined_map.setdefault((r["kind"], r["name"]), r)     # first context wins
    undefined = sorted(undefined_map.values(), key=lambda x: (x["kind"], x["name"]))
    unused = sorted(
        ({"kind": k, "name": nm} for k in _HYGIENE_KINDS for nm in defs[k] if nm not in referenced[k]),
        key=lambda x: (x["kind"], x["name"]))
    total_defs = sum(len(v) for v in defs.values())
    if not total_defs and not refs:
        return {}
    return {"undefined": undefined, "unused": unused,
            "summary": {"undefined": len(undefined), "unused": len(unused), "structures": total_defs}}


# ----------------------------------------------------------------------------- #
# REDISTRIBUTION (protocol-to-protocol analysis) - parse the 'router <proto>' /
# 'redistribute' stanzas out of the already-collected 'show running-config'. Each
# 'redistribute' under a 'router X' block is one protocol-to-protocol edge
# (from_proto -> into_proto on this device), which lets the explorer flag
# redistribution points and mutual (two-way) redistribution risk. IOS-flat form;
# NX-OS address-family nesting keeps the same indented 'redistribute' lines.
# ----------------------------------------------------------------------------- #
def parse_redistribution(output: str) -> List[dict]:
    """'show running-config' -> [{into_proto, into_id, from_proto, from_id, route_map, raw}], one row per
    'redistribute' statement found under a 'router <ospf|bgp|eigrp|rip|isis>' block. [] when none. Tolerant."""
    out: List[dict] = []
    into: Optional[tuple] = None                                     # (proto, id) of the current 'router' block
    ROUTER = re.compile(r"^router\s+(ospf|bgp|eigrp|rip|isis)\b\s*(\S+)?", re.IGNORECASE)
    REDIST = re.compile(
        r"^\s+redistribute\s+(connected|static|ospf|bgp|eigrp|rip|isis)\b\s*(\d+)?(.*)$", re.IGNORECASE)
    for raw in output.splitlines():
        m = ROUTER.match(raw)
        if m:
            into = (m.group(1).lower(), (m.group(2) or "").strip()); continue
        if raw[:1] and not raw[:1].isspace():                       # any col-0 line ends the router block
            into = None; continue
        if into is None:
            continue
        rd = REDIST.match(raw)
        if rd:
            rmap = re.search(r"route-map\s+(\S+)", rd.group(3) or "", re.IGNORECASE)
            out.append({"into_proto": into[0], "into_id": into[1],
                        "from_proto": rd.group(1).lower(), "from_id": (rd.group(2) or "").strip(),
                        "route_map": rmap.group(1) if rmap else "", "raw": raw.strip()})
    return out

def _proto_from_token(tok: str) -> str:
    t = (tok or "").strip().upper()
    if t == "LACP": return "Active"
    if t == "PAGP": return "Active"
    if t in ("NONE","-","ON"): return "On"
    return ""

def parse_portchannel_protocol_from_summary(output: str) -> Dict[str, str]:
    proto: Dict[str, str] = {}
    for line in output.splitlines():
        m = re.search(r"\b(Po\d+)\b\s*(?:\(\w+\))?\s+(?:\w+\s+)*(LACP|PAgP|NONE|-)\b",
                      line, re.IGNORECASE)
        if m:
            po = normalize_ifname(m.group(1))
            p  = _proto_from_token(m.group(2))
            if p: proto[po] = p
    return proto

def parse_etherchannel_protocol_ios(output: str) -> Dict[str, str]:
    proto: Dict[str, str] = {}
    for line in output.splitlines():
        m = re.search(r"\b(Po\d+)\b.*?\b(LACP|PAgP|NONE|-)\b", line, re.IGNORECASE)
        if m:
            po = normalize_ifname(m.group(1))
            p  = _proto_from_token(m.group(2))
            if p: proto[po] = p
    return proto

def parse_etherchannel_summary_members(output: str) -> Dict[str, str]:
    members: Dict[str, str] = {}
    current_po = ""
    for line in output.splitlines():
        pm = re.search(r"\b(Po\d+)\b", line, re.IGNORECASE)
        if pm: current_po = normalize_ifname(pm.group(1))
        if not current_po: continue
        for tok in IFACE_TOKEN_RE.findall(line):
            n = normalize_ifname(tok)
            if not n.startswith("Po"): members[n] = current_po
    return members

def parse_show_ip_arp(output: str) -> Dict[str, str]:
    """FIX-R2+FIX-R8: token-scan based, tolerates any column order, skips VRF banners."""
    result: Dict[str, str] = {}
    _IP_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
    _SKP   = re.compile(
        r"^(protocol|address|ip address|ip arp|arp|total|vrf|context|flags|"
        r"hardware addr|incomplete|age|interface|#|--|===)", re.IGNORECASE)
    for line in output.splitlines():
        line = line.strip()
        if not line: continue
        if _SKP.match(line): continue
        if "incomplete" in line.lower(): continue
        parts = line.split()
        if len(parts) < 3: continue
        ip_addr = mac_addr = ""
        for tok in parts:
            if not ip_addr and _IP_RE.match(tok):
                ip_addr = tok
            if not mac_addr:
                mn = normalize_mac(tok)
                if mn: mac_addr = mn
        if ip_addr and mac_addr:
            result.setdefault(mac_addr, ip_addr)
    return result

def parse_vtp_status(output: str) -> str:
    if not output:
        return ""
    for line in output.splitlines():
        m = re.search(r"(?:vtp\s+domain\s+name|domain name)\s*:?\s*(.+)$", line.strip(), re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            if val and val.lower() not in ("not configured", "none", "null"):
                return val
    return ""

def _parse_ip_int_brief(blob: str) -> Dict[str, Tuple[str, bool]]:
    """Parse 'show ip interface brief' (IOS + NX-OS) -> {ifname: (ip, is_up)}.

    IOS line:   GigabitEthernet0/0  10.99.0.5  YES NVRAM  up  up
    NX-OS line: mgmt0               10.99.0.5  protocol-up/link-up/admin-up
    'unassigned' / no-IP lines are skipped.
    """
    res: Dict[str, Tuple[str, bool]] = {}
    if not blob:
        return res
    for raw in blob.splitlines():
        s = raw.strip()
        if not s or s.lower().startswith(("interface", "ip interface status")):
            continue
        m = re.match(r"^(\S+)\s+(\d+\.\d+\.\d+\.\d+)\b(.*)$", s)
        if not m:
            continue
        ifn = normalize_ifname(m.group(1))
        ip  = m.group(2)
        rest = m.group(3).lower()
        # up if NX-OS 'protocol-up' & 'link-up', or IOS trailing 'up   up' (proto up)
        if "protocol-up" in rest or "link-up" in rest:
            is_up = ("protocol-up" in rest) and ("admin-up" in rest or "link-up" in rest)
        else:
            toks = rest.split()
            is_up = len(toks) >= 2 and toks[-1] == "up"   # IOS: last col = protocol
        if ifn not in res or (is_up and not res[ifn][1]):
            res[ifn] = (ip, is_up)
    return res

def parse_switch_mgmt_ip(ipbrief_blob: str, run_iface: Optional[Dict[str, Dict[str, str]]] = None) -> str:
    """Best-effort 'this switch's own management IP', NOT a neighbor's.

    Priority: OOB mgmt port (mgmt0 / Management* / Gi0/0 / Fa0/0) > lowest Loopback >
    a sole management SVI > lowest-numbered up SVI. Prefers up interfaces within a tier.
    Falls back to run-config 'ip address' lines if ip-int-brief is unavailable.
    Returns a bare address (no mask/prefix), or '' if nothing qualifies.
    """
    ifs = _parse_ip_int_brief(ipbrief_blob)

    # Fallback: derive {ifname: (ip, up?)} from run-config-captured ip_addr (up unknown -> True)
    if not ifs and run_iface:
        for ifn, v in run_iface.items():
            raw_ip = (v.get("ip_addr") or "").strip()
            if not raw_ip:
                continue
            ipv = raw_ip.split()[0].split("/")[0]
            if ipv:
                ifs[normalize_ifname(ifn)] = (ipv, True)
    if not ifs:
        return ""

    def bare(ip: str) -> str:
        return ip.split()[0].split("/")[0]
    def num(ifn: str) -> int:
        m = re.search(r"(\d+)", ifn);  return int(m.group(1)) if m else 0
    def pick(cands: List[str]) -> str:
        if not cands:
            return ""
        cands.sort(key=lambda i: (not ifs[i][1], num(i)))  # up first, then lowest index
        return bare(ifs[cands[0]][0])

    oob  = [i for i in ifs if re.match(r"^(mgmt|management|gigabitethernet0/0|fastethernet0/0|gi0/0|fa0/0)", i, re.IGNORECASE)]
    if oob:  return pick(oob)
    loop = [i for i in ifs if i.lower().startswith(("lo", "loop"))]
    if loop: return pick(loop)
    svis = [i for i in ifs if re.match(r"^Vlan\d+$", i, re.IGNORECASE)]
    if len(svis) == 1:        # sole SVI with an IP == the management SVI
        return bare(ifs[svis[0]][0])
    if svis:                  # L3 switch with many gateway SVIs: best-effort, lowest up SVI
        return pick(svis)
    return pick(list(ifs.keys()))

def parse_multicast_info(mroute_out: str, pim_out: str) -> Dict[str, str]:
    """Per-interface multicast state from 'show ip pim interface' + 'show ip mroute'.

    V14.11: parse the real PIM table (Address / Interface / Ver/Mode / ...) instead of the
    incorrect 'X is up' assumption, and capture VlanN interfaces in mroute IIF/OIL (the global
    IFACE_TOKEN_RE deliberately excludes Vlan, so a local Vlan-aware token regex is used here).
    """
    # Vlan-aware token regex, scoped to this function only. Matches both abbreviated
    # (Gi1/0/1) and full (GigabitEthernet1/0/1) names, plus Vlan/Port-channel.
    tok_re = re.compile(
        r"\b(?:Vlan\d+|(?:Port-?channel|Po)\d+|[A-Za-z]{2,}\d+/\d+(?:/\d+)?)\b",
        re.IGNORECASE)
    res: Dict[str, List[str]] = {}

    if pim_out:
        _MODE = {"s": "Sparse", "d": "Dense", "sd": "Sparse-Dense", "ss": "Sparse"}
        for line in pim_out.splitlines():
            s = line.strip()
            if not s or s.lower().startswith(("address", "interface")):
                continue
            # Table row: '<ip> <interface> <ver/mode> ...'  (interface may be VlanN)
            mt = re.match(r"^(\d+\.\d+\.\d+\.\d+)\s+(\S+)\s+v?\d?\s*/?\s*([A-Za-z]+)?", s)
            if mt and is_valid_iface(mt.group(2)):
                intf = normalize_ifname(mt.group(2))
                mode = _MODE.get((mt.group(3) or "").lower(), "")
                res.setdefault(intf, []).append("PIM" + (f" {mode}" if mode else ""))
                continue
            # Some platforms: '<interface> is up, ... PIM ...'
            mi = re.match(r"^(Vlan\d+|\S+)\s+is\s+(?:up|down)", s, re.IGNORECASE)
            if mi and is_valid_iface(mi.group(1)):
                res.setdefault(normalize_ifname(mi.group(1)), []).append("PIM enabled")

    if mroute_out:
        for line in mroute_out.splitlines():
            low = line.lower()
            tag = "Mroute IIF" if "incoming interface" in low else (
                  "Mroute OIL" if ("outgoing" in low or line.startswith((" ", "\t"))) else "Mroute")
            for tok in tok_re.findall(line):
                res.setdefault(normalize_ifname(tok), []).append(tag)

    return {k: " / ".join(dict.fromkeys(v)) for k, v in res.items()}


# ----------------------------------------------------------------------------- #
# Multicast / PTP / ACL-hit collection parsers (NEW-V3.23.102). These read the
# new commands (show ip igmp groups / snooping groups / snooping querier / ptp
# clock / ptp parent / ip access-lists). Tolerant: empty/absent -> []/{}. They
# light up the broadcast-fabric intelligence (multicast group census, PTP lock,
# active-traffic evidence) on the next data re-collection; inert until then.
# ----------------------------------------------------------------------------- #
_MCAST_IP_RE = re.compile(r"\b(2(?:2[4-9]|3[0-9])\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")  # class D 224-239


def parse_igmp_groups(output: str) -> List[str]:
    """'show ip igmp groups' / 'show ip igmp snooping groups' -> sorted distinct multicast group IPs
    (class-D 224.0.0.0-239.255.255.255). Reporter/querier unicast addresses are ignored. [] when none."""
    if not output:
        return []
    groups = {m for ln in output.splitlines() for m in _MCAST_IP_RE.findall(ln)}
    return sorted(groups, key=lambda ip: tuple(int(o) for o in ip.split(".")))


def parse_igmp_snooping_querier(output: str) -> List[dict]:
    """'show ip igmp snooping querier' -> [{vlan, querier}] (the L2 querier per VLAN -- critical for
    broadcast: no querier => multicast floods or is pruned). Tolerant of table + 'detail' forms."""
    out: List[dict] = []
    if not output:
        return out
    cur_vlan = ""
    for raw in output.splitlines():
        s = raw.strip()
        if not s:
            continue
        # detail form: 'Vlan 10: IGMP snooping querier status' ... 'IP address    : 10.0.10.1'
        mv = re.match(r"^Vlan\s+(\d+)\b", s, re.IGNORECASE)
        if mv:
            cur_vlan = mv.group(1)
        mip = re.search(r"IP address\s*[:=]\s*(\d+\.\d+\.\d+\.\d+)", s, re.IGNORECASE)
        if mip and cur_vlan:
            out.append({"vlan": cur_vlan, "querier": mip.group(1)}); cur_vlan = ""; continue
        # table form: '10    10.0.10.1    v2    ...'
        mt = re.match(r"^(\d+)\s+(\d+\.\d+\.\d+\.\d+)\b", s)
        if mt:
            out.append({"vlan": mt.group(1), "querier": mt.group(2)})
    # de-dup (vlan,querier)
    seen, uniq = set(), []
    for r in out:
        k = (r["vlan"], r["querier"])
        if k not in seen:
            seen.add(k); uniq.append(r)
    return uniq


def parse_ptp_clock(output: str) -> dict:
    """'show ptp clock' (+ optionally 'show ptp parent', concatenated) -> a PTP health summary:
    {device_type, profile, domain, clock_identity, num_ports, grandmaster, offset_ns,
    mean_path_delay_ns, locked, operational}. {} when no PTP output.

    `operational` distinguishes a switch acting as a real PTP boundary/transparent clock (a known
    device type with >=1 active PTP port) from one where `show ptp clock` reports Device Type=Unknown
    / 0 ports / no parent -- i.e. PTP is available but the switch is NOT in an active timing hierarchy
    (PTP would be flowing as plain multicast, not boundary-clocked -- a real ST 2110/AES67 finding).
    `locked` is inferred from a small offset-from-master (|offset| < 1us) when present."""
    if not output or "ptp" not in output.lower():
        return {}
    r: dict = {"device_type": "", "profile": "", "domain": "", "clock_identity": "", "num_ports": None,
               "grandmaster": "", "offset_ns": None, "mean_path_delay_ns": None,
               "locked": None, "operational": None}
    for raw in output.splitlines():
        s = raw.strip()
        m = re.search(r"PTP Device Type\s*[:=]\s*(.+)$", s, re.IGNORECASE)
        if m:
            r["device_type"] = m.group(1).strip()
        m = re.search(r"PTP Device Profile\s*[:=]\s*(.+)$", s, re.IGNORECASE)
        if m:
            r["profile"] = m.group(1).strip()
        m = re.search(r"(?:Clock )?Domain(?: Number)?\s*[:=]\s*(\d+)", s, re.IGNORECASE)
        if m and not r["domain"]:
            r["domain"] = m.group(1)
        m = re.search(r"Clock Identity\s*[:=]\s*(\S+)", s, re.IGNORECASE)
        if m and not r["clock_identity"] and "grandmaster" not in s.lower() and "parent" not in s.lower():
            r["clock_identity"] = m.group(1)
        m = re.search(r"Number of PTP ports\s*[:=]\s*(\d+)", s, re.IGNORECASE)
        if m:
            r["num_ports"] = int(m.group(1))
        m = re.search(r"Grandmaster Clock Identity\s*[:=]\s*(\S+)", s, re.IGNORECASE)
        if m:
            r["grandmaster"] = m.group(1)
        m = re.search(r"Offset From Master\s*\(ns\)\s*[:=]\s*(-?\d+)", s, re.IGNORECASE)
        if m:
            r["offset_ns"] = int(m.group(1))
        m = re.search(r"Mean Path Delay\s*\(ns\)\s*[:=]\s*(-?\d+)", s, re.IGNORECASE)
        if m:
            r["mean_path_delay_ns"] = int(m.group(1))
    if r["offset_ns"] is not None:
        r["locked"] = abs(r["offset_ns"]) < 1000   # < 1 microsecond from master => effectively locked
    # operational = a real boundary/transparent clock. A known device type that is NOT explicitly
    # 0-port (num_ports unparsed/None is treated as unknown, NOT dormant -- so a known clock on a
    # platform whose output omits the port count is not false-flagged), OR positive sync evidence
    # (a grandmaster identity or a measured offset). The AJ case (Device Type Unknown / 0 ports /
    # no parent) stays correctly dormant.
    dt = r["device_type"].lower()
    r["operational"] = bool((dt and dt != "unknown" and r["num_ports"] != 0)
                            or r["grandmaster"] or r["offset_ns"] is not None)
    return r


def parse_acl_hitcounts(output: str) -> List[dict]:
    """'show ip access-lists' -> [{acl, proto, port, matches}], one per ACE that reports hit counts
    ('(N matches)'). Turns an ACL reference from design-intent (Inferred) into active-traffic evidence
    (Confirmed). port is the 'eq <port>' destination port when present, else None. [] when none."""
    out: List[dict] = []
    if not output:
        return out
    cur = ""
    HDR = re.compile(r"^(?:Standard|Extended|Reflexive)?\s*IP access list\s+(\S+)", re.IGNORECASE)
    for raw in output.splitlines():
        h = HDR.match(raw.strip())
        if h:
            cur = h.group(1); continue
        mm = re.search(r"\((\d+)\s+match(?:es)?\)", raw)
        if not (mm and cur):
            continue
        matches = int(mm.group(1))
        proto = ""
        mp = re.search(r"\b(permit|deny)\s+(tcp|udp|ip|icmp)\b", raw, re.IGNORECASE)
        if mp:
            proto = mp.group(2).lower()
        port = None
        me = re.search(r"\beq\s+(\S+)", raw, re.IGNORECASE)
        if me:
            port = _acl_portnum(me.group(1))
        out.append({"acl": cur, "proto": proto, "port": port, "matches": matches})
    return out


def parse_show_version(output: str) -> Dict[str, str]:
    """Parse 'show version' for IOS/IOS-XE and NX-OS."""
    r: Dict[str, str] = {"model": "", "serial_number": "", "sw_version": "",
                          "uptime": "", "system_mac": "", "hostname_reported": ""}
    if not output:
        return r
    for line in output.splitlines():
        low = line.strip().lower()
        m = re.match(r"^cisco\s+(\S+)\s*(?:\(|processor|chassis|with)", line.strip(), re.IGNORECASE)
        if m and not r["model"]:
            cand = m.group(1).strip().rstrip(",")
            if len(cand) > 3 and not cand.lower().startswith(("ios","xe","nx")):
                r["model"] = cand
        m2 = re.match(r"^\s*cisco\s+(Nexus\S*|N\d[Kk]-\S+|\S+)\s+(?:chassis|switch)", line, re.IGNORECASE)
        if m2 and not r["model"]:
            r["model"] = m2.group(1).strip()
        m3 = re.search(r"(?:system serial number\s*[:=]|processor board id)\s*(\S+)", low)
        if m3 and not r["serial_number"]:
            r["serial_number"] = line.split()[-1].strip()
        m3b = re.match(r"^\s*Processor Board ID\s+(\S+)", line, re.IGNORECASE)
        if m3b and not r["serial_number"]:
            r["serial_number"] = m3b.group(1).strip()
        m4 = re.search(r"version\s+([\d\.()A-Za-z]+)", line, re.IGNORECASE)
        if m4 and not r["sw_version"] and any(k in low for k in ("ios","nx-os","nxos","software")):
            r["sw_version"] = m4.group(1).strip().rstrip(",")
        m4b = re.match(r"^\s*system:\s+version\s+(\S+)", line, re.IGNORECASE)
        if m4b:
            r["sw_version"] = m4b.group(1).strip()
        m5 = re.search(r"uptime is\s+(.+)", line, re.IGNORECASE)
        if m5 and not r["uptime"]:
            r["uptime"] = m5.group(1).strip().rstrip(".")
        m5b = re.search(r"kernel uptime is\s+(.+)", line, re.IGNORECASE)
        if m5b:
            r["uptime"] = m5b.group(1).strip()
        m6 = re.search(
            r"(?:base ethernet mac address|system mac address|mac address)\s*[:\-]?\s*"
            r"([0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}|(?:[0-9a-fA-F]{2}[:\-]){5}[0-9a-fA-F]{2})",
            line, re.IGNORECASE)
        if m6 and not r["system_mac"]:
            r["system_mac"] = normalize_mac(m6.group(1))
        m7 = re.match(r"^(\S+)\s+uptime is", line)
        if m7 and not r["hostname_reported"]:
            r["hostname_reported"] = m7.group(1).strip()
    return r


def _inv_commit(entry: Dict[str, str], result: Dict) -> None:
    """Classify one inventory entry and accumulate into result dict."""
    name  = (entry.get("name")  or "").lower().strip()
    descr = (entry.get("descr") or "").lower()
    pid   = (entry.get("pid")   or "")
    sn    = (entry.get("sn")    or "")
    pid_l = pid.lower()

    # Power supply: highest priority
    is_ps = (
        any(k in name  for k in ("power supply","psu","ps ","power-supply","power module")) or
        any(k in descr for k in ("power supply","psu","power-supply","power module"))       or
        bool(re.match(r"^(pwr-|n[0-9][kk]-pac|c[0-9]+-pwr|pwrs-|pwr[0-9])", pid_l))
    )

    # Module / linecard: check before chassis to avoid C9300-NM-* matching chassis
    _module_pid = bool(re.match(
        r"^(n[0-9][kk]-[mx]|n[0-9][kk]-lc|n[0-9][kk]-sup|"
        r"c[0-9]+-nm-|c[0-9]+-uadp|nm-|spa-|sm-)", pid_l))
    is_module = (
        not is_ps and (
            any(k in name  for k in ("module","linecard","line card","supervisor","sup","fabric")) or
            any(k in descr for k in ("linecard","supervisor","fabric",
                                     "uplink module","switching module","ethernet module",
                                     "network module")) or
            _module_pid
        )
    )

    # Chassis: the main switch body
    _chassis_pid = (
        bool(re.match(r"^(ws-c|n[0-9][kk]-c[0-9])", pid_l)) or
        bool(re.match(r"^c[0-9]{4}-[0-9]+[pg]", pid_l)) or
        bool(re.match(r"^n[0-9]{4}-[0-9]", pid_l)) or
        bool(re.match(r"^(n9k-c|n7k-c|n6k-c|n5k-c)", pid_l))
    )
    is_chassis = (
        not is_ps and not is_module and (
            name in ("1","switch","switch 1","chassis") or
            ("chassis" in name and "module" not in name) or
            ("chassis" in descr and "module" not in descr) or
            _chassis_pid
        )
    )

    if is_chassis and not result["chassis_model"]:
        result["chassis_model"]  = pid
        result["chassis_serial"] = sn
    if is_ps:
        result["num_power_supplies"] += 1
        if pid: result["ps_pids"].append(pid)
        if sn:  result["ps_serials"].append(sn)
    if is_module:
        result["num_modules"] += 1
        if pid: result["module_pids"].append(pid)


def parse_show_inventory(output: str) -> Dict[str, object]:
    """Parse 'show inventory' NAME/DESCR/PID/SN blocks (IOS + NX-OS)."""
    result = {"chassis_model":"","chassis_serial":"",
              "num_power_supplies":0,"ps_pids":[],"ps_serials":[],
              "num_modules":0,"module_pids":[]}
    if not output:
        return result
    current: Dict[str, str] = {}
    for line in output.splitlines():
        line = line.strip()
        if not line:
            if current: _inv_commit(current, result)
            current = {}
            continue
        m_name = re.match(r'NAME:\s*"([^"]*)"\s*,?\s*DESCR:\s*"([^"]*)"', line, re.IGNORECASE)
        if m_name:
            if current: _inv_commit(current, result)
            current = {"name": m_name.group(1), "descr": m_name.group(2), "pid":"", "sn":""}
            continue
        m_pid = re.match(r'PID:\s*(\S*)\s*,\s*VID:\s*\S*\s*,\s*SN:\s*(\S*)', line, re.IGNORECASE)
        if m_pid:
            current["pid"] = m_pid.group(1).strip()
            current["sn"]  = m_pid.group(2).strip()
    if current: _inv_commit(current, result)
    return result


def parse_show_environment_power(output: str) -> Dict[str, object]:
    """Parse power capacity, draw, remaining and PS status lines."""
    r: Dict[str, object] = {"total_capacity_w":"","total_drawn_w":"",
                             "total_remaining_w":"","num_ps":0,"ps_status_list":[]}
    if not output:
        return r
    ps_list: List[str] = []
    for line in output.splitlines():
        low = line.strip().lower()
        # IOS one-liner: "Available:1100.0(w)  Used:207.4(w)  Remaining:892.6(w)"
        m = re.search(
            r"available\s*:\s*([\d\.]+)\s*\(w\).*?used\s*:\s*([\d\.]+)\s*\(w\).*?remaining\s*:\s*([\d\.]+)\s*\(w\)",
            low)
        if m:
            r["total_capacity_w"]  = m.group(1)
            r["total_drawn_w"]     = m.group(2)
            r["total_remaining_w"] = m.group(3)
        mc = re.search(r"(?:total power capacity|capacity)[^:]*:\s*([\d\.]+)\s*[wW]", low)
        if mc and not r["total_capacity_w"]: r["total_capacity_w"] = mc.group(1)
        mc2 = re.search(r"\bcapacity\s*:\s*([\d\.]+)\s*[wW]", low)
        if mc2 and not r["total_capacity_w"]: r["total_capacity_w"] = mc2.group(1)
        md = re.search(r"(?:total power output|used)[^:]*:\s*([\d\.]+)\s*[wW]", low)
        if md and not r["total_drawn_w"]: r["total_drawn_w"] = md.group(1)
        me = re.search(r"(?:total power available|remaining)[^:]*:\s*([\d\.]+)\s*[wW]", low)
        if me and not r["total_remaining_w"]: r["total_remaining_w"] = me.group(1)
        # PS status rows: lines starting with slot number or PS label
        if re.match(r"^\s*\d[AB]?\s+\S", line) or re.match(r"^\s*[Pp][Ss]\d?\s", line):
            if "ok" in low:                               ps_list.append("OK")
            elif "fail" in low:                           ps_list.append("FAIL")
            elif "absent" in low or "not present" in low: ps_list.append("ABSENT")
    if r["total_capacity_w"] and r["total_drawn_w"] and not r["total_remaining_w"]:
        try:
            r["total_remaining_w"] = str(round(
                float(r["total_capacity_w"]) - float(r["total_drawn_w"]), 1))
        except Exception as e:
            logger.debug(f"remaining-power calc failed (cap={r['total_capacity_w']} drawn={r['total_drawn_w']}): {e}")  # NEW-V3.23.1
    r["ps_status_list"] = ps_list
    r["num_ps"] = len(set(ps_list))
    return r


def parse_show_environment(output: str) -> Dict[str, str]:
    """Parse fan, temperature AND power-supply health from 'show environment' (IOS + NX-OS).

    On Catalyst 4948E / 4500-X(-VSS) the PS health + fan-sensor live in the 'show environment'
    Power-Supply table, NOT in 'show environment power' (which returns '% Invalid input' there),
    so this also recovers ps_status / num_ps for the build layer to fall back on."""
    r = {"fan_status":"","temperature_status":"","ps_status":"","num_ps":"0"}
    if not output:
        return r
    fan_states: List[str]  = []
    temp_states: List[str] = []
    ps_states: List[str]   = []
    n_ps = 0
    for line in output.splitlines():
        low = line.strip().lower()
        if not low: continue
        mt = re.search(r"temperature\s+is\s+(ok|normal|warning|critical|alert)", low)
        if mt:
            temp_states.append({"ok":"OK","normal":"OK","warning":"Warning",
                                 "critical":"Critical","alert":"Warning"}.get(mt.group(1),""))
        mf = re.search(r"fan\s+is\s+(ok|normal|warning|failed|fault)", low)
        if mf:
            fan_states.append({"ok":"OK","normal":"OK","warning":"Warning",
                                "failed":"Failed","fault":"Failed"}.get(mf.group(1),""))
        if re.match(r"^\s*fan\d*\s+\S", low):
            if "ok" in low or "good" in low:       fan_states.append("OK")
            elif "fail" in low or "fault" in low:  fan_states.append("Failed")
            elif "warn" in low or "minor" in low:  fan_states.append("Warning")
        # Catalyst 'Fantray : Good' (4948E) / 'Fantray 1 : ... status : Good' (4500-X) - only a
        # line that actually carries a health word (skips 'removal timeout', 'consumed by').
        if "fantray" in low and re.search(r"\b(good|ok|failed|fail|fault|bad)\b", low):
            if "good" in low or re.search(r"\bok\b", low):        fan_states.append("OK")
            elif "fail" in low or "fault" in low or "bad" in low: fan_states.append("Failed")
        # Catalyst Power-Supply table row: 'PS1  PWR-C49E-300AC-R  AC 300W  good  good  n.a.'
        # Columns: Supply | Model | Type(=watts) | Status | Fan Sensor | Inline. Split on 2+ spaces
        # and key off the watts column so leading-column drift doesn't matter.
        if re.match(r"^\s*ps\d+\b", low):
            cols = re.split(r"\s{2,}", line.strip())
            watt_idx = next((i for i, c in enumerate(cols) if re.search(r"\d+\s*w\b", c.lower())), None)
            if watt_idx is not None:
                n_ps += 1
                ps_tok  = cols[watt_idx + 1].lower() if watt_idx + 1 < len(cols) else ""
                fan_tok = cols[watt_idx + 2].lower() if watt_idx + 2 < len(cols) else ""
                if "good" in ps_tok or "ok" in ps_tok:                    ps_states.append("OK")
                elif "fail" in ps_tok or "fault" in ps_tok or "bad" in ps_tok: ps_states.append("FAIL")
                if "good" in fan_tok or "ok" in fan_tok:                  fan_states.append("OK")
                elif "fail" in fan_tok or "fault" in fan_tok:             fan_states.append("Failed")
            elif any(t in low for t in ("absent", "not present", "none")):
                n_ps += 1; ps_states.append("ABSENT")
        if re.match(r"^\s*\d+\s+\S", low) and any(k in low for k in ("inlet","outlet","sensor")):
            if "ok" in low or "normal" in low or "green" in low:        temp_states.append("OK")
            elif "critical" in low or "major" in low or "red" in low:   temp_states.append("Critical")
            elif "warn" in low or "minor" in low or "yellow" in low:    temp_states.append("Warning")
        # IOS-XE 'show environment all' (Catalyst 9300/3850) markers - this command form is what
        # those platforms accept ('show environment' alone returns '% Incomplete command'):
        #   'Temperature State: GREEN'  +  fan table '1  1  8160  OK  front to back'  +  'FAN PS-1 is OK'
        mts = re.search(r"temperature\s+state\s*:\s*(green|yellow|red)", low)
        if mts:
            temp_states.append({"green":"OK","yellow":"Warning","red":"Critical"}[mts.group(1)])
        mfan = re.match(r"^\s*\d+\s+\d+\s+\d+\s+(ok|fail|faulty|fault|warn|warning|red)\b", low)
        if mfan:
            st = mfan.group(1)
            if st == "ok":                                  fan_states.append("OK")
            elif st in ("warn", "warning"):                 fan_states.append("Warning")
            else:                                           fan_states.append("Failed")
        mfps = re.search(r"fan\s+ps-?\d+\s+is\s+(ok|fail|faulty|fault)", low)
        if mfps:
            fan_states.append("OK" if mfps.group(1) == "ok" else "Failed")
    def _worst(states: List[str]) -> str:
        if "Critical" in states or "Failed" in states: return "Critical/Failed"
        if "Warning"  in states: return "Warning"
        if "OK"       in states: return "OK"
        return ""
    r["fan_status"]         = _worst(fan_states)
    r["temperature_status"] = _worst(temp_states)
    r["ps_status"]          = " / ".join(dict.fromkeys(ps_states))   # distinct, e.g. 'OK' or 'OK / FAIL'
    r["num_ps"]             = str(n_ps)
    return r


def parse_show_module_count(output: str) -> int:
    """Count occupied module slots from 'show module' (NX-OS)."""
    count = 0
    for line in output.splitlines():
        m = re.match(r"^\s*(\d+)\s+\d+\s+(\S+)", line)
        if m and m.group(2).upper() not in ("N/A","--","NONE","EMPTY"):
            count += 1
    return count


def parse_show_interface_counters(output: str) -> Dict[str, Dict[str, object]]:
    """Per-interface error/health counters from IOS 'show interfaces' or NX-OS
    'show interface'. Tolerant across both; unknown values stay blank. Returns
    {port: {oper, input_errors, crc, output_drops, last_input, last_output}}."""
    res: Dict[str, Dict[str, object]] = {}
    cur = None
    buf: List[str] = []

    def _flush(name, lines):
        if not name or not lines:
            return
        text = "\n".join(lines)
        rec: Dict[str, object] = {"oper": "", "input_errors": "", "crc": "",
                                  "output_errors": "", "late_collisions": "", "runts": "", "giants": "",
                                  "output_drops": "", "last_input": "", "last_output": ""}
        mhdr = re.match(r"^\S+\s+is\s+([A-Za-z ]+?)(?:,|$)", lines[0])
        if mhdr: rec["oper"] = mhdr.group(1).strip()
        m = re.search(r"(\d+)\s+input error", text)
        if m: rec["input_errors"] = int(m.group(1))
        m = re.search(r"(\d+)\s+CRC", text)
        if m: rec["crc"] = int(m.group(1))
        # output-side L1 health (was collected but discarded): TX errors, late collisions (duplex mismatch),
        # runts/giants (framing) — preserved so the explorer interface view + future detectors can read them.
        for _fld, _pat in (("output_errors", r"(\d+)\s+output error"),
                           ("late_collisions", r"(\d+)\s+late collision"),
                           ("runts", r"(\d+)\s+runts"), ("giants", r"(\d+)\s+giants")):
            _m = re.search(_pat, text)
            if _m:
                rec[_fld] = int(_m.group(1))
        m = re.search(r"Total output drops:\s*(\d+)", text)
        if m:
            rec["output_drops"] = int(m.group(1))
        else:
            m = re.search(r"(\d+)\s+output discard", text)   # NX-OS
            if m: rec["output_drops"] = int(m.group(1))
        m = re.search(r"Last input\s+(\S+?),\s*output\s+(\S+?)[,\s]", text)
        if m:
            rec["last_input"] = m.group(1).rstrip(",")
            rec["last_output"] = m.group(2).rstrip(",")
        res[name] = rec

    for line in output.splitlines():
        mh = re.match(r"^(\S+)\s+is\s+(up|down|administratively down)\b", line)
        if mh:
            nm = normalize_ifname(mh.group(1))
            if VALID_IFACE_RE.match(nm):
                _flush(cur, buf)
                cur, buf = nm, [line]
                continue
        if cur is not None:
            buf.append(line)
    _flush(cur, buf)
    return res

def parse_port_security(output: str) -> Dict[str, Dict[str, str]]:
    """IOS 'show port-security' summary: per-port max/current/violations/action.
    Handles both short (Gi1/0/5) and full (GigabitEthernet1/0/5) names."""
    res: Dict[str, Dict[str, str]] = {}
    for line in output.splitlines():
        toks = line.split()
        if not toks:
            continue
        p = normalize_ifname(toks[0])
        if not PHYSICAL_IFACE_RE.match(p):
            continue
        nums = re.findall(r"\b\d+\b", " ".join(toks[1:]))
        act = ""
        ma = re.search(r"\b(Shutdown|Restrict|Protect)\b", line, re.IGNORECASE)
        if ma: act = ma.group(1).capitalize()
        if len(nums) >= 3:
            res[p] = {"max": nums[0], "current": nums[1], "violations": nums[2], "action": act}
    return res

def parse_auth_sessions(output: str) -> Dict[str, Dict[str, str]]:
    """IOS 'show authentication sessions': per-port 802.1X/MAB method+status+MAC.
    Handles both short and full interface names."""
    res: Dict[str, Dict[str, str]] = {}
    for line in output.splitlines():
        port = ""
        for t in line.split():
            n = normalize_ifname(t)
            if PHYSICAL_IFACE_RE.match(n):
                port = n
                break
        if not port:
            continue
        mac = ""
        mm = re.search(r"\b([0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4})\b", line)
        if mm: mac = mm.group(1)
        method = ""
        mt = re.search(r"\b(dot1x|mab|webauth)\b", line, re.IGNORECASE)
        if mt: method = mt.group(1).lower()
        status = ""
        ms = re.search(r"\b(Authz?|Authc|Authorized|Authenticated|Unauth\w*|Running|Idle|No[- ]?resp\w*)\b",
                       line, re.IGNORECASE)
        if ms: status = ms.group(1)
        if method or mac or status:
            res[port] = {"method": method, "status": status, "mac": mac}
    return res

def parse_dhcp_snooping_binding(output: str) -> Dict[str, int]:
    """'show ip dhcp snooping binding': count of bindings per interface (full or short names)."""
    res: Dict[str, int] = {}
    for line in output.splitlines():
        if not re.search(r"[0-9a-fA-F]{2}[:.\-][0-9a-fA-F]{2}", line):
            continue
        if not re.search(r"\d+\.\d+\.\d+\.\d+", line):
            continue
        port = ""
        for t in line.split():
            n = normalize_ifname(t)
            if PHYSICAL_IFACE_RE.match(n):
                port = n
        if not port:
            continue
        res[port] = res.get(port, 0) + 1
    return res


def _parse_fhrp(behavior: str):
    """('HSRP grp 1 Active VIP 10.0.10.1') -> (proto, role, vip, group). Blank tuple if none.
    NEW-V3.23.26 (PHASE 2.7 step 16): the FHRP behaviour-string parser, shared by the
    protocol-health analyzer and the monolith's L3-forwarding sheet."""
    if not behavior:
        return ("", "", "", "")
    m = re.match(r"(HSRP|VRRP|GLBP)\s+grp\s+(\d+)\s+(\w+)(?:\s+VIP\s+(\S+))?", behavior.strip(), re.IGNORECASE)
    if m:
        return (m.group(1).upper(), m.group(3).capitalize(), m.group(4) or "", m.group(2))
    return ("", "", "", "")


# Physical-port / media parsers (PHASE 2.7 step 17). Logical (non-physical) interfaces
# excluded from the per-physical-port sheet.
_NON_PHYSICAL_RE = re.compile(
    r"^(Vlan\d+|Lo\d+|Loopback\d+|Po\d+|Port-channel\d+|Tu\d+|Tunnel\d+|"
    r"Null\d*|mgmt0|Bundle-Ether\d+|BE\d+)$", re.IGNORECASE)

def _is_physical_port(port: str) -> bool:
    p = (port or "").strip()
    return bool(p) and not _NON_PHYSICAL_RE.match(p)

def _classify_media(s: str) -> str:
    """Map a 'media type is ...' / port-type string to copper / SFP-fiber / QSFP / unknown."""
    low = (s or "").lower()
    if not low:
        return "unknown"
    if "qsfp" in low:
        return "QSFP"
    if ("sfp" in low or "base-sx" in low or "base-lx" in low or "base-sr" in low
            or "base-lr" in low or "base-er" in low or "1000basesx" in low or "fiber" in low):
        return "SFP/fiber"
    if ("basetx" in low or "baset" in low or "10/100" in low or "rj45" in low or "copper" in low):
        return "copper"
    return s.strip()[:24] or "unknown"

def parse_interface_phy(output: str) -> Dict[str, Dict[str, str]]:
    """Best-effort negotiated duplex/speed/media per interface from IOS 'show interfaces' /
    NX-OS 'show interface' DETAIL. Returns {port: {'duplex','speed','media'}}; values stay
    blank when the platform format omits the line (some NX-OS) -> caller marks unknown."""
    res: Dict[str, Dict[str, str]] = {}
    cur = None
    buf: List[str] = []

    def _flush(name, lines):
        if not name or not lines:
            return
        text = "\n".join(lines)
        rec = {"duplex": "", "speed": "", "media": ""}
        m = re.search(r"\b(Full|Half|Auto)-duplex\b", text, re.IGNORECASE)
        if m:
            rec["duplex"] = m.group(1).capitalize()
        m = re.search(r"-duplex,\s*([^,]+?)\s*,", text)        # token between duplex and next comma
        if m:
            rec["speed"] = m.group(1).strip()
        m = re.search(r"media type is\s+(.+)", text, re.IGNORECASE)
        if m:
            rec["media"] = _classify_media(m.group(1).strip())
        res[name] = rec

    for line in output.splitlines():
        mh = re.match(r"^(\S+)\s+is\s+(?:up|down|administratively down)\b", line)
        if mh:
            nm = normalize_ifname(mh.group(1))
            if VALID_IFACE_RE.match(nm):
                _flush(cur, buf)
                cur, buf = nm, [line]
                continue
        if cur is not None:
            buf.append(line)
    _flush(cur, buf)
    return res

def _parse_poe_watts(output: str) -> Dict[str, float]:
    """Best-effort per-port PoE watts (consumed) from 'show power inline'. {port: watts}.
    Reads the first decimal on each interface line (the consumed-watts column)."""
    res: Dict[str, float] = {}
    for line in output.splitlines():
        it = IFACE_TOKEN_RE.search(line)
        if not it:
            continue
        intf = normalize_ifname(it.group(0))
        if not _is_physical_port(intf):
            continue
        m = re.search(r"\b(\d+\.\d+)\b", line[it.end():])
        if m:
            try:
                res[intf] = float(m.group(1))
            except ValueError:
                pass
    return res


def _parse_poe_inline_budget(output: str) -> Dict[str, float]:
    """Total PoE budget from the 'show power inline' Module-summary rows (one per stack member):
    '<module>  <available>  <used>  <remaining>' watts, e.g. '1   1120.0   0.0   1120.0'. Sums across
    modules; 'n/a' rows (a non-PoE module) are skipped. Returns {'available','used'} only when at least
    one real module row was seen, else {} -- so an n/a-only / non-PoE switch stays UNBUDGETED (poe_util
    blank) rather than reading a false 0/0. (DET-poe-001: the budget the per-port parse never captured.)"""
    avail = used = 0.0
    seen = False
    for line in output.splitlines():
        m = re.match(r"^\s*\d+\s+(\d+\.\d+)\s+(\d+\.\d+)\s+(\d+\.\d+)\s*$", line)
        if m:
            avail += float(m.group(1)); used += float(m.group(2)); seen = True
    return {"available": round(avail, 1), "used": round(used, 1)} if seen else {}


# =============================================================================
# SYSLOG EVENT PARSER (NEW-V3.23.164). Structures already-collected 'show logging'
# output for the syslog-intelligence axis (the NOS-style operational log analysis).
# Handles both line shapes: IOS  '000123: *Jun  9 12:00:01.123: %LINK-3-UPDOWN: ...'
# and             NX-OS  '2026 Jun  9 12:00:01 host %ETHPORT-5-IF_DOWN_LINK_FAILURE: ...'
# including stacked/module facility prefixes ('%SPANTREE-SP-2-...'). Non-event lines
# (the 'Syslog logging: enabled ...' header etc.) are skipped, never errors.
# =============================================================================
_SYSLOG_EVENT_RE = re.compile(
    r"%([A-Z][A-Z0-9_]*(?:-[A-Z][A-Z0-9_]*)*)-(\d)-([A-Z0-9_]+)\s*:\s*(.*)")


def parse_syslog_events(text: str) -> List[dict]:
    """Parse 'show logging' output -> [{facility, severity, mnemonic, msg, raw}, ...].
    `severity` is the numeric syslog level 0-7 (int). Lines without a %FAC-SEV-MNEMONIC
    event are skipped. Empty/None input -> []. Tolerant; never raises."""
    events: List[dict] = []
    for raw in (text or "").splitlines():
        m = _SYSLOG_EVENT_RE.search(raw)
        if not m:
            continue
        events.append({"facility": m.group(1), "severity": int(m.group(2)),
                       "mnemonic": m.group(3), "msg": m.group(4).strip(),
                       "raw": raw.strip()})
    return events


# =============================================================================
# QoS CONFIG PARSER (NEW-V3.23.165). Structures the QoS-relevant slice of an
# already-collected full 'show running-config' for the QoS-audit axis: global
# enablement ('mls qos'), MQC objects (class-map / policy-map, incl. NX-OS
# 'type qos|queuing|network-qos'), and per-interface QoS attributes (voice VLAN,
# trust statements, auto-QoS macros, attached service-policies). Pure config
# evidence -- no live queue counters. Tolerant; never raises.
# =============================================================================
_QOS_CLASS_MAP_RE = re.compile(
    r"^class-map\s+(?:type\s+(\S+)\s+)?(?:match-(?:any|all)\s+)?(\S+)\s*$")
_QOS_POLICY_MAP_RE = re.compile(r"^policy-map\s+(?:type\s+(\S+)\s+)?(\S+)\s*$")
_QOS_SERVICE_POLICY_RE = re.compile(
    r"^\s*service-policy\s+(?:type\s+\S+\s+)?(input|output)\s+(\S+)\s*$")
# non-interface attachments (NX-OS 'system qos', control-plane) may omit the direction
_QOS_SERVICE_POLICY_ANY_RE = re.compile(
    r"^\s*service-policy\s+(?:type\s+\S+\s+)?(?:(?:input|output)\s+)?(\S+)\s*$")
_QOS_IF_ATTR_KEYS = ("voice_vlan", "trust", "auto_qos", "policy_in", "policy_out")


def parse_qos_config(text: str) -> dict:
    """Parse a full running-config -> the device's QoS posture facts:
    {mls_qos, class_maps, policy_maps, interfaces:{if:{voice_vlan,trust,auto_qos,
    policy_in,policy_out}}, global_attach:[policy names attached outside interfaces],
    child_policies:[policy names referenced INSIDE a policy-map (hierarchical MQC) --
    definition-time references, NOT live attachments]}.
    Only interfaces with at least one QoS-relevant attribute are listed.
    Empty/None input -> the same shape with empty members. Tolerant; never raises."""
    res: dict = {"mls_qos": False, "class_maps": [], "policy_maps": [],
                 "interfaces": {}, "global_attach": [], "child_policies": []}
    cur: Optional[str] = None          # current interface block, else None
    in_iface = False
    in_pmap = False                    # inside a policy-map definition block (HQoS children live here)
    for raw in (text or "").splitlines():
        if raw[:1] not in (" ", "\t"):                     # a new top-level stanza
            line = raw.strip()
            im = re.match(r"^interface\s+(\S+)\s*$", line)
            in_iface = bool(im)
            cur = normalize_ifname(im.group(1)) if im else None
            if line == "mls qos":
                in_pmap = False
                res["mls_qos"] = True
                continue
            cm = _QOS_CLASS_MAP_RE.match(line)
            if cm:
                in_pmap = False
                if cm.group(2) not in res["class_maps"]:
                    res["class_maps"].append(cm.group(2))
                continue
            pm = _QOS_POLICY_MAP_RE.match(line)
            in_pmap = bool(pm)
            if pm and pm.group(2) not in res["policy_maps"]:
                res["policy_maps"].append(pm.group(2))
            continue
        # indented: an attribute of the enclosing block
        sp = _QOS_SERVICE_POLICY_RE.match(raw)
        if not in_iface:
            ga = _QOS_SERVICE_POLICY_ANY_RE.match(raw)
            if ga:
                if in_pmap:
                    # hierarchical MQC: 'policy-map PARENT / class X / service-policy CHILD' is a
                    # DEFINITION-TIME reference, not an attachment -- recording it as global_attach
                    # would suppress the inert-policy / no-trust-boundary doctrine findings.
                    if ga.group(1) not in res["child_policies"]:
                        res["child_policies"].append(ga.group(1))
                # service-policy under system qos / control-plane / line / etc. = attachment in use
                # (may be directionless, e.g. NX-OS 'service-policy type network-qos NQ-8E')
                elif ga.group(1) not in res["global_attach"]:
                    res["global_attach"].append(ga.group(1))
            continue
        line = raw.strip()
        attrs = res["interfaces"].setdefault(
            cur, {k: (False if k == "auto_qos" else None) for k in _QOS_IF_ATTR_KEYS})
        vm = re.match(r"^switchport voice vlan\s+(\d+)", line)
        if vm:
            attrs["voice_vlan"] = vm.group(1)
        elif re.match(r"^(mls\s+)?qos trust\s+\S+", line) or line.startswith("trust device "):
            attrs["trust"] = line.split("trust", 1)[1].strip() or "trusted"
        elif line.startswith("auto qos"):
            attrs["auto_qos"] = True
        elif sp:
            attrs["policy_in" if sp.group(1) == "input" else "policy_out"] = sp.group(2)
        # drop the entry again if nothing QoS-relevant was ever set on it
        if all(attrs[k] in (None, False) for k in _QOS_IF_ATTR_KEYS):
            del res["interfaces"][cur]
    return res


# =============================================================================
# PLATFORM HEALTH PARSERS (NEW-V3.23.167). Control-plane capacity facts for the
# platform-health axis: CPU utilization ('show processes cpu' header line, IOS and
# NX-OS share the shape), processor-pool memory ('show processes memory', IOS) and
# NX-OS 'show system resources' (CPU idle + memory usage + load average). Each
# returns {} on absent/unrecognized output. Tolerant; never raises.
# =============================================================================
_CPU_UTIL_RE = re.compile(
    r"CPU utilization for five seconds:\s*(\d+)%(?:/(\d+)%)?;\s*"
    r"one minute:\s*(\d+)%;\s*five minutes:\s*(\d+)%", re.I)
_MEM_POOL_RE = re.compile(
    r"(?:Processor\s+Pool\s+)?Total:\s*(\d+)\s+Used:\s*(\d+)\s+Free:\s*(\d+)", re.I)
_SYSRES_CPU_RE = re.compile(r"CPU states\s*:.*?([\d.]+)%\s*idle", re.I)
_SYSRES_MEM_RE = re.compile(
    r"Memory usage\s*:\s*(\d+)K?\s+total,\s*(\d+)K?\s+used,\s*(\d+)K?\s+free", re.I)
_SYSRES_LOAD_RE = re.compile(r"Load average\s*:\s*1 minute:\s*([\d.]+)", re.I)


def parse_cpu_utilization(text: str) -> dict:
    """Parse the 'CPU utilization for five seconds: A%/B%; one minute: C%; five
    minutes: D%' header (IOS + NX-OS 'show processes cpu') ->
    {five_sec, interrupt, one_min, five_min} (ints; interrupt 0 when absent).
    {} when not found. Tolerant; never raises."""
    m = _CPU_UTIL_RE.search(text or "")
    if not m:
        return {}
    return {"five_sec": int(m.group(1)), "interrupt": int(m.group(2) or 0),
            "one_min": int(m.group(3)), "five_min": int(m.group(4))}


def parse_memory_stats(text: str) -> dict:
    """Parse the IOS 'show processes memory' processor-pool header
    ('Processor Pool Total: N Used: N Free: N') -> {total, used, free} (bytes).
    {} when not found. Tolerant; never raises."""
    m = _MEM_POOL_RE.search(text or "")
    if not m:
        return {}
    return {"total": int(m.group(1)), "used": int(m.group(2)), "free": int(m.group(3))}


def parse_system_resources(text: str) -> dict:
    """Parse NX-OS 'show system resources' -> {cpu_idle (float %), mem_total_kb,
    mem_used_kb, mem_free_kb, load_1m (float)}; keys present only when their line
    parsed. {} when nothing recognized. Tolerant; never raises."""
    out: dict = {}
    t = text or ""
    m = _SYSRES_CPU_RE.search(t)
    if m:
        out["cpu_idle"] = float(m.group(1))
    m = _SYSRES_MEM_RE.search(t)
    if m:
        out["mem_total_kb"] = int(m.group(1))
        out["mem_used_kb"] = int(m.group(2))
        out["mem_free_kb"] = int(m.group(3))
    m = _SYSRES_LOAD_RE.search(t)
    if m:
        out["load_1m"] = float(m.group(1))
    return out
