"""Pure show-command parsers + column primitives. Depends only on `re`, stdlib
typing, and cisco_toolkit.textutils (the leaf layer). Extracted verbatim from
COLLECT_PARSE_V3_23_0.py in PHASE 2.7 step 2 (behaviour byte-identical)."""
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
            res.setdefault(current, {"bpduguard":"","rootguard":"","pc_mode":"","pc_id":"","vrf":"","desc":"","portfast":"","ip_addr":""})
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
        if low.startswith("vrf member "):    res[current]["vrf"] = line.strip().split()[-1]
        if low.startswith("vrf forwarding "): res[current]["vrf"] = line.strip().split()[-1]
    return res

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
    """Parse fan and temperature health from 'show environment' (IOS + NX-OS)."""
    r = {"fan_status":"","temperature_status":""}
    if not output:
        return r
    fan_states: List[str]  = []
    temp_states: List[str] = []
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
        if re.match(r"^\s*\d+\s+\S", low) and any(k in low for k in ("inlet","outlet","sensor")):
            if "ok" in low or "normal" in low:        temp_states.append("OK")
            elif "critical" in low or "major" in low: temp_states.append("Critical")
            elif "warn" in low or "minor" in low:     temp_states.append("Warning")
    def _worst(states: List[str]) -> str:
        if "Critical" in states or "Failed" in states: return "Critical/Failed"
        if "Warning"  in states: return "Warning"
        if "OK"       in states: return "OK"
        return ""
    r["fan_status"]         = _worst(fan_states)
    r["temperature_status"] = _worst(temp_states)
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
                                  "output_drops": "", "last_input": "", "last_output": ""}
        mhdr = re.match(r"^\S+\s+is\s+([A-Za-z ]+?)(?:,|$)", lines[0])
        if mhdr: rec["oper"] = mhdr.group(1).strip()
        m = re.search(r"(\d+)\s+input error", text)
        if m: rec["input_errors"] = int(m.group(1))
        m = re.search(r"(\d+)\s+CRC", text)
        if m: rec["crc"] = int(m.group(1))
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
