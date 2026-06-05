"""The Excel layer's shared helpers: the openpyxl header / sheet-formatting utilities
every write_* sheet uses (`_census_header`, `_census_autofit`), plus the template
header-matching primitives (`norm_header` / `HEADER_TO_FIELD` / `find_header_row` /
`ensure_headers`) and the port-row sort key (`sortkey`). Depends on openpyxl, stdlib,
and cisco_toolkit.textutils (a clean layer above analyze). Extracted verbatim from
COLLECT_PARSE_V3_23_0.py in PHASE 2.7 step 20 (behaviour byte-identical). The sheet
writers themselves follow in later steps; the monolith imports these back meanwhile."""
import re
from typing import Dict, Tuple

from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from cisco_toolkit.textutils import normalize_ifname

_CENSUS_HDR_FILL = "1F497D"

def _census_header(ws, columns):
    hf = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
    fill = PatternFill("solid", fgColor=_CENSUS_HDR_FILL)
    al = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for col, header in enumerate(columns, 1):
        c = ws.cell(row=1, column=col, value=header)
        c.font = hf; c.fill = fill; c.alignment = al
    ws.row_dimensions[1].height = 30

def _census_autofit(ws, ncols, nrows):
    for col in range(1, ncols + 1):
        mx = len(str(ws.cell(row=1, column=col).value or ""))
        for row in range(2, nrows + 1):
            v = ws.cell(row=row, column=col).value
            if v: mx = max(mx, len(str(v)))
        ws.column_dimensions[get_column_letter(col)].width = min(max(mx + 2, 12), 48)
    ws.freeze_panes = "A2"

def norm_header(h: str) -> str:
    h = (h or "").strip().lower()
    return re.sub(r"\s+", " ", h)

HEADER_TO_FIELD = {
    "hostname": "hostname", "ports": "port", "status": "status",
    "swqitchport mode": "switchport_mode",
    "swqitchport mode (access/trunk)": "switchport_mode",
    "switchport mode": "switchport_mode",
    "switchport mode (access/trunk)": "switchport_mode",
    "vlan": "vlan", "vlan name": "vlan_name",
    "vrf name": "vrf", "vrf name ": "vrf",
    "duplex": "duplex", "duplex (full/half/auto)": "duplex",
    "speed": "speed", "port type": "port_type",
    "link type (copper/fiber)": "link_type", "link type (copper/fibre)": "link_type",
    "link type": "link_type", "description": "description",
    "end host mac address": "end_host_mac", "end host ip address": "end_host_ip",
    "port-channel": "port_channel",
    "port-channel protocol (active/on/none)": "port_channel_protocol",
    "port-channel protocol": "port_channel_protocol",
    "spanning tree block ports status": "stp_blocked",
    "spanning tree bpdu (enable/disable)": "stp_bpduguard",
    "spanning tree bpdu": "stp_bpduguard",
    "spanning tree rootguard (enable/disable)": "stp_rootguard",
    "spanning tree rootguard": "stp_rootguard",
    "poe status": "poe_status",
    "system owner (ajmn to confirm)": "system_owner", "system owner": "system_owner",
    "end point type": "endpoint_type",
    "end point location rack-unit": "endpoint_location", "end point location": "endpoint_location",
    "dual connection": "dual_connection",
    "trunk native vlan": "trunk_native_vlan",
    "trunk allowed vlans": "trunk_allowed_vlans",
    "trunk status": "trunk_status",
    # NEW-V11
    "arp source switch": "arp_source_switch",
    "arp source":        "arp_source_switch",
    "cdp neighbor":      "cdp_neighbor",
    "cdp/lldp neighbor": "cdp_neighbor",
    "connected device":  "cdp_neighbor",
    "neighbor device":   "cdp_neighbor",
    # NEW-V14.2 (keys must match the header text written by ensure_headers in main())
    "current switch serial":      "current_switch_serial",
    "current switch mgmt ip":     "current_switch_ip",
    "current switch vtp domain":  "current_switch_vtp_domain",
    "neighbor switch serial":     "neighbor_switch_serial",
    "neighbor switch mgmt ip":    "neighbor_switch_ip",
    "neighbor switch vtp domain": "neighbor_switch_vtp_domain",
    "subnet primary route":       "subnet_primary_route",
    "subnet secondary routes":    "subnet_secondary_routes",
    "route next hop":             "route_next_hop",
    "routing source":             "routing_source",
    "hsrp behavior":              "hsrp_behavior",
    "fhrp behavior":              "hsrp_behavior",  # NEW-V14.6 canonical (HSRP/VRRP/GLBP)
    "multicast info":             "multicast_info",
    # Aliases
    "port": "port", "interface": "port", "state": "status",
}

def find_header_row(ws, must_have=("hostname","port","status")) -> Tuple[int, Dict[str,int]]:
    for r in range(1, 301):
        col_map: Dict[str,int] = {}
        for c in range(1, ws.max_column+1):
            val = ws.cell(row=r, column=c).value
            if not isinstance(val, str): continue
            nh = norm_header(val)
            if nh in HEADER_TO_FIELD:
                field = HEADER_TO_FIELD[nh]
                if field not in col_map: col_map[field] = c
        if all(k in col_map for k in must_have):
            return r, col_map
    raise RuntimeError("Could not find header row. Try --debug-headers")

def ensure_headers(ws, header_row, col_map, new_headers):
    for header_text, field in new_headers.items():
        if field in col_map: continue
        new_col = ws.max_column + 1
        ws.cell(row=header_row, column=new_col, value=header_text)
        col_map[field] = new_col
    return col_map

def sortkey(portname: str):
    pn = normalize_ifname(portname or "")
    m  = re.match(r"^Po(\d+)$", pn, re.IGNORECASE)
    if m: return (0, int(m.group(1)), 0, 0)
    m = re.match(r"^(Eth|Fa|Gi|Te|Tw|Fo|Hu)(\d+)(?:/(\d+))?(?:/(\d+))?$", pn, re.IGNORECASE)
    if m:
        pref = m.group(1).capitalize()
        rank = {"Eth":1,"Fa":2,"Gi":3,"Te":4,"Tw":5,"Fo":6,"Hu":7}.get(pref, 9)
        return (rank, int(m.group(2)), int(m.group(3) or 0), int(m.group(4) or 0))
    return (99, pn)
