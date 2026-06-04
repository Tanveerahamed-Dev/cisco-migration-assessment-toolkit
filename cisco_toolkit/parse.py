"""Pure show-command parsers + column primitives. Depends only on `re`, stdlib
typing, and cisco_toolkit.textutils (the leaf layer). Extracted verbatim from
COLLECT_PARSE_V3_23_0.py in PHASE 2.7 step 2 (behaviour byte-identical)."""
import re
from typing import Dict, List, Optional, Tuple

from cisco_toolkit.textutils import normalize_ifname, is_valid_iface


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
