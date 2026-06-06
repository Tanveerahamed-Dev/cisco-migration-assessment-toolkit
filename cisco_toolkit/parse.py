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
    aaa = has(r"^aaa new-model\b")
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
        "'aaa new-model' is enabled." if aaa
        else "no 'aaa new-model' -- authentication is local-only / line-based.")
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
