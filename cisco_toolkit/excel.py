"""The Excel layer's shared helpers: the openpyxl header / sheet-formatting utilities
every write_* sheet uses (`_census_header`, `_census_autofit`), plus the template
header-matching primitives (`norm_header` / `HEADER_TO_FIELD` / `find_header_row` /
`ensure_headers`) and the port-row sort key (`sortkey`). Depends on openpyxl, stdlib,
and cisco_toolkit.textutils (a clean layer above analyze). Extracted verbatim from
COLLECT_PARSE_V3_23_0.py in PHASE 2.7 step 20 (behaviour byte-identical). The sheet
writers themselves follow in later steps; the monolith imports these back meanwhile."""
import logging
import os
import re
from typing import Dict, List, Optional, Tuple

from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from cisco_toolkit.analyze import compute_findings, compute_move_groups, compute_topology_links
from cisco_toolkit.model import DevicePhysical, InterfaceData
from cisco_toolkit.textutils import _split_macs, normalize_ifname

logger = logging.getLogger(__name__)

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
    "system owner ([HISTORY-REDACTED] to confirm)": "system_owner", "system owner": "system_owner",
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


# =============================================================================
# Census / inventory sheet writers (PHASE 2.7 step 21). One row per switch / SVI /
# STP port / VLAN / endpoint - pure renders of the parsed model (no analyze compute).
# =============================================================================
INVENTORY_SHEET_NAME = "Switch Inventory"

INVENTORY_COLUMNS = [
    ("Hostname",            "hostname"),
    ("Platform",            "platform"),
    ("Model / PID",         "model"),
    ("Serial Number",       "serial_number"),
    ("Chassis Serial",      "chassis_serial"),
    ("SW Version",          "sw_version"),
    ("Uptime",              "uptime"),
    ("System MAC",          "system_mac"),
    ("# Power Supplies",    "num_power_supplies"),
    ("PS Status",           "ps_status"),
    ("Power Capacity (W)",  "power_capacity_w"),
    ("Power Drawn (W)",     "power_drawn_w"),
    ("Power Remaining (W)", "power_remaining_w"),
    ("# Modules",           "num_modules"),
    ("Total Ports",         "total_ports"),
    ("Active Ports",        "active_ports"),
    ("Fan Status",          "fan_status"),
    ("Temperature Status",  "temperature_status"),
]

def write_device_inventory_sheet(wb, all_device_physical: List[DevicePhysical]) -> None:
    """Write (or replace) 'Switch Inventory' sheet with one row per switch."""

    if INVENTORY_SHEET_NAME in wb.sheetnames:
        del wb[INVENTORY_SHEET_NAME]
    ws = wb.create_sheet(INVENTORY_SHEET_NAME)

    HDR_FONT  = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
    HDR_FILL  = PatternFill("solid", fgColor="1F497D")
    HDR_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
    DAT_FONT  = Font(name="Calibri", size=10)
    DAT_L     = Alignment(horizontal="left",   vertical="center")
    DAT_C     = Alignment(horizontal="center", vertical="center")
    _NUM      = {"num_power_supplies","num_modules","total_ports","active_ports"}

    for col, (header, _) in enumerate(INVENTORY_COLUMNS, 1):
        c = ws.cell(row=1, column=col, value=header)
        c.font = HDR_FONT; c.fill = HDR_FILL; c.alignment = HDR_ALIGN
    ws.row_dimensions[1].height = 30

    for row, dp in enumerate(all_device_physical, 2):
        for col, (_, field) in enumerate(INVENTORY_COLUMNS, 1):
            val = getattr(dp, field, "")
            if val == 0: val = ""
            c = ws.cell(row=row, column=col, value=val)
            c.font = DAT_FONT
            c.alignment = DAT_C if field in _NUM else DAT_L

    for col, (header, _) in enumerate(INVENTORY_COLUMNS, 1):
        mx = len(header)
        for row in range(2, len(all_device_physical) + 2):
            v = ws.cell(row=row, column=col).value
            if v: mx = max(mx, len(str(v)))
        ws.column_dimensions[get_column_letter(col)].width = min(max(mx + 2, 12), 48)

    ws.freeze_panes = "A2"
    logger.info(f"  [OK] '{INVENTORY_SHEET_NAME}' sheet: {len(all_device_physical)} device(s)")

# =============================================================================
# NEW-V14.3: SVI / Gateway sheet (one row per SVI) - surfaces the per-SVI routing,
# HSRP and multicast data that the interface sheet excludes by design.
# =============================================================================
SVI_SHEET_NAME = "SVI Gateway"

SVI_COLUMNS = [
    ("Hostname",               "hostname"),
    ("SVI",                    "port"),
    ("Description",            "description"),
    ("VLAN",                   "vlan"),
    ("VRF",                    "vrf"),
    ("Gateway IP (configured)","svi_ip"),
    ("Subnet / Primary Route", "subnet_primary_route"),
    ("Routing Source",         "routing_source"),
    ("Route Next Hop",         "route_next_hop"),
    ("Secondary Routes",       "subnet_secondary_routes"),
    ("FHRP Behavior",          "hsrp_behavior"),
    ("Multicast Info",         "multicast_info"),
    ("Switch Serial",          "current_switch_serial"),
    ("Switch Mgmt IP",         "current_switch_ip"),
    ("VTP Domain",             "current_switch_vtp_domain"),
]

def _is_svi(port: str) -> bool:
    return bool(re.match(r"^Vlan\d+$", (port or "").strip(), re.IGNORECASE))

def write_svi_gateway_sheet(wb, all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> None:
    """Write (or replace) 'SVI Gateway' sheet: one row per SVI across all devices.

    This is the home for the per-SVI fields (routing / HSRP / multicast) that
    append_interface_rows() intentionally skips, since the interface sheet drops
    Vlan/loopback/tunnel rows. Physical-port rows are unaffected.
    """

    if SVI_SHEET_NAME in wb.sheetnames:
        del wb[SVI_SHEET_NAME]
    ws = wb.create_sheet(SVI_SHEET_NAME)

    HDR_FONT  = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
    HDR_FILL  = PatternFill("solid", fgColor="1F497D")
    HDR_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
    DAT_FONT  = Font(name="Calibri", size=10)
    DAT_L     = Alignment(horizontal="left",   vertical="center")

    for col, (header, _) in enumerate(SVI_COLUMNS, 1):
        c = ws.cell(row=1, column=col, value=header)
        c.font = HDR_FONT; c.fill = HDR_FILL; c.alignment = HDR_ALIGN
    ws.row_dimensions[1].height = 30

    # Collect SVIs, sorted by hostname then numeric VLAN id for a stable, readable sheet.
    rows: List[Tuple[str, InterfaceData]] = []
    for hostname, ifaces in all_interfaces.items():
        for port, d in ifaces.items():
            if _is_svi(port):
                rows.append((hostname, d))
    def _vlan_id(p: str) -> int:
        m = re.search(r"(\d+)", p or "")
        return int(m.group(1)) if m else 0
    rows.sort(key=lambda hd: (hd[0].lower(), _vlan_id(hd[1].port)))

    r = 2
    for hostname, d in rows:
        for col, (_, field) in enumerate(SVI_COLUMNS, 1):
            val = hostname if field == "hostname" else getattr(d, field, "")
            c = ws.cell(row=r, column=col, value=val)
            c.font = DAT_FONT; c.alignment = DAT_L
        r += 1

    for col, (header, _) in enumerate(SVI_COLUMNS, 1):
        mx = len(header)
        for row in range(2, r):
            v = ws.cell(row=row, column=col).value
            if v: mx = max(mx, len(str(v)))
        ws.column_dimensions[get_column_letter(col)].width = min(max(mx + 2, 12), 48)

    ws.freeze_panes = "A2"
    logger.info(f"  [OK] '{SVI_SHEET_NAME}' sheet: {len(rows)} SVI(s)")


# =============================================================================
# NEW-V14.7: STP Detail sheet (one row per STP port) - shows WHICH VLANs each port
# forwards vs blocks, instead of the single collapsed state on the interface sheet.
# =============================================================================
STP_SHEET_NAME = "STP Detail"

STP_COLUMNS = [
    ("Hostname",          "hostname"),
    ("Port",              "port"),
    ("STP Summary",       "_summary"),       # computed: Forwarding / Blocked / Mixed (FWD+BLK)
    ("Forwarding VLANs",  "stp_fwd_vlans"),
    ("Blocked VLANs",     "stp_blk_vlans"),
    ("Other (Lis/Lrn/Dis)", "stp_other_vlans"),
]

def write_stp_detail_sheet(wb, all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> None:
    """Write (or replace) 'STP Detail': one row per port that appears in 'show spanning-tree',
    with the per-VLAN forwarding/blocking breakdown. Ports with no STP data are omitted.
    Under MST the VLAN columns hold MST instance numbers (see header note in the docs)."""

    if STP_SHEET_NAME in wb.sheetnames:
        del wb[STP_SHEET_NAME]
    ws = wb.create_sheet(STP_SHEET_NAME)

    HDR_FONT  = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
    HDR_FILL  = PatternFill("solid", fgColor="1F497D")
    HDR_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
    DAT_FONT  = Font(name="Calibri", size=10)
    DAT_L     = Alignment(horizontal="left", vertical="center")

    for col, (header, _) in enumerate(STP_COLUMNS, 1):
        c = ws.cell(row=1, column=col, value=header)
        c.font = HDR_FONT; c.fill = HDR_FILL; c.alignment = HDR_ALIGN
    ws.row_dimensions[1].height = 30

    rows: List[Tuple[str, InterfaceData]] = []
    for hostname, ifaces in all_interfaces.items():
        for d in ifaces.values():
            if d.stp_fwd_vlans or d.stp_blk_vlans or d.stp_other_vlans:
                rows.append((hostname, d))

    def _natkey(hd):
        host, d = hd
        m = re.findall(r"\d+", d.port or "")
        return (host.lower(), d.port[:2].lower(), [int(x) for x in m])
    rows.sort(key=_natkey)

    def _summary(d: InterfaceData) -> str:
        f, b = bool(d.stp_fwd_vlans), bool(d.stp_blk_vlans)
        if f and b: return "Mixed (FWD+BLK)"
        if b:       return "Blocked"
        if f:       return "Forwarding"
        return d.stp_other_vlans and "Transitional" or ""

    r = 2
    for hostname, d in rows:
        for col, (_, field) in enumerate(STP_COLUMNS, 1):
            if field == "hostname":  val = hostname
            elif field == "_summary": val = _summary(d)
            else:                     val = getattr(d, field, "")
            c = ws.cell(row=r, column=col, value=val)
            c.font = DAT_FONT; c.alignment = DAT_L
        r += 1

    for col, (header, _) in enumerate(STP_COLUMNS, 1):
        mx = len(header)
        for row in range(2, r):
            v = ws.cell(row=row, column=col).value
            if v: mx = max(mx, len(str(v)))
        ws.column_dimensions[get_column_letter(col)].width = min(max(mx + 2, 12), 48)

    ws.freeze_panes = "A2"
    logger.info(f"  [OK] '{STP_SHEET_NAME}' sheet: {len(rows)} STP port(s)")


# =============================================================================
# NEW-V14.8: VLAN Census + Endpoint Census sheets (aggregations of the interface DB).
# =============================================================================
VLAN_CENSUS_SHEET_NAME = "VLAN Census"
ENDPOINT_CENSUS_SHEET_NAME = "Endpoint Census"

def write_vlan_census_sheet(wb, all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> None:
    """One row per in-use VLAN (has access ports and/or an SVI), aggregated across all
    devices: where it lives, access-port and endpoint (MAC) counts, and its gateway/SVI."""
    cols = ["VLAN ID", "Name", "# Switches", "Switches", "# Access Ports", "# Endpoints",
            "Gateway Switch(es)", "Gateway IP", "Subnet", "FHRP"]
    if VLAN_CENSUS_SHEET_NAME in wb.sheetnames:
        del wb[VLAN_CENSUS_SHEET_NAME]
    ws = wb.create_sheet(VLAN_CENSUS_SHEET_NAME)
    _census_header(ws, cols)

    agg: Dict[int, Dict[str, object]] = {}
    def fresh():
        return {"name": "", "switches": set(), "access_ports": 0, "macs": set(),
                "gw_switches": set(), "gw_ip": "", "subnet": "", "fhrp": ""}
    for hostname, ifaces in all_interfaces.items():
        for port, d in ifaces.items():
            # access ports in this VLAN
            if (d.switchport_mode or "") == "Access" and d.vlan.isdigit():
                vid = int(d.vlan); a = agg.setdefault(vid, fresh())
                a["switches"].add(hostname); a["access_ports"] += 1
                if d.vlan_name and not a["name"]: a["name"] = d.vlan_name
                for mac in _split_macs(d.end_host_mac): a["macs"].add(mac)
            # SVI = the gateway for this VLAN
            m = re.match(r"^Vlan(\d+)$", port, re.IGNORECASE)
            if m:
                vid = int(m.group(1)); a = agg.setdefault(vid, fresh())
                a["gw_switches"].add(hostname)
                if d.vlan_name and not a["name"]: a["name"] = d.vlan_name
                if d.svi_ip and not a["gw_ip"]: a["gw_ip"] = d.svi_ip
                if d.subnet_primary_route and not a["subnet"]: a["subnet"] = d.subnet_primary_route
                if d.hsrp_behavior and not a["fhrp"]: a["fhrp"] = d.hsrp_behavior

    DAT_FONT = Font(name="Calibri", size=10)
    DAT_L = Alignment(horizontal="left", vertical="center")
    r = 2
    for vid in sorted(agg.keys()):
        a = agg[vid]
        vals = [vid, a["name"], len(a["switches"]), ", ".join(sorted(a["switches"])),
                a["access_ports"], len(a["macs"]),
                ", ".join(sorted(a["gw_switches"])), a["gw_ip"], a["subnet"], a["fhrp"]]
        for col, v in enumerate(vals, 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT_FONT; c.alignment = DAT_L
        r += 1
    _census_autofit(ws, len(cols), r - 1)
    logger.info(f"  [OK] '{VLAN_CENSUS_SHEET_NAME}' sheet: {len(agg)} VLAN(s)")

def write_endpoint_census_sheet(wb, all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> None:
    """Flat list of endpoints across all devices: one row per port that has a learned MAC."""
    cols = ["Hostname", "Port", "VLAN", "VLAN Name", "MAC Address", "IP Address",
            "Endpoint Type", "Location", "CDP/LLDP Neighbor"]
    if ENDPOINT_CENSUS_SHEET_NAME in wb.sheetnames:
        del wb[ENDPOINT_CENSUS_SHEET_NAME]
    ws = wb.create_sheet(ENDPOINT_CENSUS_SHEET_NAME)
    _census_header(ws, cols)

    rows: List[Tuple[str, InterfaceData]] = []
    for hostname, ifaces in all_interfaces.items():
        for d in ifaces.values():
            if d.end_host_mac and (d.switchport_mode or "") != "Trunk":
                rows.append((hostname, d))
    def _key(hd):
        host, d = hd
        vid = int(d.vlan) if d.vlan.isdigit() else 0
        nums = [int(x) for x in re.findall(r"\d+", d.port or "")]
        return (host.lower(), vid, d.port[:2].lower(), nums)
    rows.sort(key=_key)

    DAT_FONT = Font(name="Calibri", size=10)
    DAT_L = Alignment(horizontal="left", vertical="center")
    r = 2
    for hostname, d in rows:
        vals = [hostname, d.port, d.vlan, d.vlan_name, d.end_host_mac, d.end_host_ip,
                d.endpoint_type, d.endpoint_location, d.cdp_neighbor]
        for col, v in enumerate(vals, 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT_FONT; c.alignment = DAT_L
        r += 1
    _census_autofit(ws, len(cols), r - 1)
    logger.info(f"  [OK] '{ENDPOINT_CENSUS_SHEET_NAME}' sheet: {len(rows)} endpoint(s)")


# =============================================================================
# Analysis sheet writers (PHASE 2.7 step 22): move-group / topology / findings /
# capacity sheets + the Mermaid/Graphviz topology diagram. These call the analyze
# layer's compute_* (excel sits above analyze, so excel -> analyze is one-way).
# =============================================================================
MOVEGROUP_SHEET_NAME = "Move Groups"

def write_move_group_sheet(wb, all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> None:
    """Write (or replace) 'Move Groups': one row per migration wave (connected component
    of the shared-VLAN graph), ordered largest-coupling first."""
    cols = ["Group", "# Switches", "Switches", "# Spanning VLANs", "Spanning VLANs",
            "# Endpoints", "Gateways", "Redundant (STP-blocked) Paths", "Notes"]
    if MOVEGROUP_SHEET_NAME in wb.sheetnames:
        del wb[MOVEGROUP_SHEET_NAME]
    ws = wb.create_sheet(MOVEGROUP_SHEET_NAME)
    _census_header(ws, cols)

    groups = compute_move_groups(all_interfaces)
    DAT_FONT = Font(name="Calibri", size=10)
    DAT_L = Alignment(horizontal="left", vertical="top", wrap_text=True)

    r = 2
    for i, g in enumerate(groups, 1):
        span_txt = ", ".join(f"{vid}{'('+name+')' if name else ''}[x{n}]"
                             for vid, name, n in g["spanning_vlans"])
        notes = []
        if len(g["switches"]) == 1:
            notes.append("Standalone — migrate independently, any order")
        else:
            notes.append("Migrate together — shared L2 broadcast domain(s)")
        if g["vlan1_spans"]:
            notes.append("VLAN 1 also spans group (default, excluded from grouping)")
        if g["blocked_paths"]:
            notes.append("Has redundant blocked path(s) — verify before cutover")
        vals = [f"Group {i}", len(g["switches"]), ", ".join(g["switches"]),
                len(g["spanning_vlans"]), span_txt, g["endpoints"],
                ", ".join(g["gateways"]), "; ".join(g["blocked_paths"]), " | ".join(notes)]
        for col, v in enumerate(vals, 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT_FONT; c.alignment = DAT_L
        r += 1
    _census_autofit(ws, len(cols), r - 1)
    # widen the two free-text columns
    ws.column_dimensions["E"].width = 40
    ws.column_dimensions["I"].width = 48
    logger.info(f"  [OK] '{MOVEGROUP_SHEET_NAME}' sheet: {len(groups)} group(s)")


TOPOLOGY_SHEET_NAME = "Topology Links"

def write_topology_sheet(wb, all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> None:
    """Write (or replace) 'Topology Links': one row per physical inter-switch link,
    discovered from CDP/LLDP and de-duplicated across both endpoints' views."""
    cols = ["Switch A", "Port A", "Switch B", "Port B", "Neighbor Platform",
            "Link Speed", "Confirmation"]
    if TOPOLOGY_SHEET_NAME in wb.sheetnames:
        del wb[TOPOLOGY_SHEET_NAME]
    ws = wb.create_sheet(TOPOLOGY_SHEET_NAME)
    _census_header(ws, cols)

    DAT_FONT = Font(name="Calibri", size=10)
    DAT_L = Alignment(horizontal="left", vertical="center")
    ordered = compute_topology_links(all_interfaces)   # V3.15.0: shared link builder
    r = 2
    for rec in ordered:
        vals = [rec["a_host"], rec["a_port"], rec["b_host"], rec["b_port"],
                rec["platform"], rec["speed"], rec["confirmation"]]
        for col, v in enumerate(vals, 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT_FONT; c.alignment = DAT_L
        r += 1
    _census_autofit(ws, len(cols), r - 1)
    logger.info(f"  [OK] '{TOPOLOGY_SHEET_NAME}' sheet: {len(ordered)} link(s)")


FINDINGS_SHEET_NAME = "Findings"

def write_findings_sheet(wb, all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> None:
    """Write (or replace) 'Findings': a risk register cross-referenced from the
    interface DB. Empty when nothing notable is found."""
    cols = ["Severity", "Category", "Scope", "Finding"]
    if FINDINGS_SHEET_NAME in wb.sheetnames:
        del wb[FINDINGS_SHEET_NAME]
    ws = wb.create_sheet(FINDINGS_SHEET_NAME)
    _census_header(ws, cols)
    findings = compute_findings(all_interfaces)
    DAT_FONT = Font(name="Calibri", size=10)
    DAT_L = Alignment(horizontal="left", vertical="top", wrap_text=True)
    sev_fill = {"High": PatternFill("solid", fgColor="F4CCCC"),
                "Medium": PatternFill("solid", fgColor="FCE5CD"),
                "Low": PatternFill("solid", fgColor="FFF2CC"),
                "Info": PatternFill("solid", fgColor="EFEFEF")}
    r = 2
    for sev, cat, scope, detail in findings:
        for col, v in enumerate([sev, cat, scope, detail], 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT_FONT; c.alignment = DAT_L
            if col == 1 and sev in sev_fill: c.fill = sev_fill[sev]
        r += 1
    _census_autofit(ws, len(cols), r - 1)
    ws.column_dimensions["D"].width = 70
    logger.info(f"  [OK] '{FINDINGS_SHEET_NAME}' sheet: {len(findings)} finding(s)")


CAPACITY_SHEET_NAME = "Capacity"

def _to_float(s) -> Optional[float]:
    m = re.search(r"-?\d+(?:\.\d+)?", str(s or ""))
    return float(m.group(0)) if m else None

def write_capacity_sheet(wb, all_device_physical: List[DevicePhysical]) -> None:
    """Write (or replace) 'Capacity': per-switch port and PoE headroom for
    consolidation decisions. Flags switches that are port- or PoE-bound."""
    cols = ["Hostname", "Model", "Total Ports", "Active Ports", "Free Ports",
            "Port Util %", "PoE Capacity (W)", "PoE Drawn (W)", "PoE Remaining (W)",
            "PoE Util %", "Flag"]
    if CAPACITY_SHEET_NAME in wb.sheetnames:
        del wb[CAPACITY_SHEET_NAME]
    ws = wb.create_sheet(CAPACITY_SHEET_NAME)
    _census_header(ws, cols)
    DAT_FONT = Font(name="Calibri", size=10)
    DAT_L = Alignment(horizontal="left", vertical="center")
    DAT_C = Alignment(horizontal="center", vertical="center")
    warn_fill = PatternFill("solid", fgColor="FCE5CD")
    r = 2
    for dp in sorted(all_device_physical, key=lambda d: d.hostname.lower()):
        total, active = dp.total_ports or 0, dp.active_ports or 0
        free = max(total - active, 0) if total else ""
        putil = round(100.0 * active / total, 1) if total else ""
        cap, drawn = _to_float(dp.power_capacity_w), _to_float(dp.power_drawn_w)
        if dp.power_remaining_w:
            rem = dp.power_remaining_w
        elif cap is not None and drawn is not None:
            rem = round(cap - drawn, 1)
        else:
            rem = ""
        poe_util = round(100.0 * drawn / cap, 1) if (cap and drawn is not None and cap > 0) else ""
        flags = []
        if putil != "" and putil >= 90: flags.append("Port-bound (>=90%)")
        if poe_util != "" and poe_util >= 80: flags.append("PoE-bound (>=80%)")
        vals = [dp.hostname, dp.model, total or "", active or "", free, putil,
                dp.power_capacity_w, dp.power_drawn_w, rem, poe_util, "; ".join(flags)]
        for col, v in enumerate(vals, 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT_FONT
            c.alignment = DAT_C if 3 <= col <= 10 else DAT_L
            if flags and col in (6, 10): c.fill = warn_fill
        r += 1
    _census_autofit(ws, len(cols), r - 1)
    logger.info(f"  [OK] '{CAPACITY_SHEET_NAME}' sheet: {len(all_device_physical)} device(s)")


def _mermaid_id(name: str, idmap: Dict[str, str]) -> str:
    if name not in idmap:
        idmap[name] = f"n{len(idmap)}"
    return idmap[name]

def write_topology_diagram(all_interfaces: Dict[str, Dict[str, InterfaceData]],
                           out_dir: str, basename: str = "topology") -> List[str]:
    """Emit the inter-switch link map as Mermaid (.mmd) and Graphviz (.dot) files.
    One-end-only links are drawn dashed. Returns the two file paths."""
    links = compute_topology_links(all_interfaces)
    os.makedirs(out_dir, exist_ok=True)
    nodes = set()
    for L in links:
        nodes.add(str(L["a_host"])); nodes.add(str(L["b_host"]))

    idmap: Dict[str, str] = {}
    mm = ["graph LR"]
    for n in sorted(nodes):
        mm.append(f'    {_mermaid_id(n, idmap)}["{n}"]')
    for L in links:
        a, b = _mermaid_id(str(L["a_host"]), idmap), _mermaid_id(str(L["b_host"]), idmap)
        lbl = f'{L["a_port"]} - {L.get("b_port") or "?"}'
        edge = "-.-" if str(L["confirmation"]).startswith("One end") else "---"
        mm.append(f'    {a} {edge}|"{lbl}"| {b}')
    mm_path = os.path.join(out_dir, basename + ".mmd")
    with open(mm_path, "w", encoding="utf-8") as f:
        f.write("\n".join(mm) + "\n")

    dot = ["graph topology {", "    rankdir=LR;", "    node [shape=box, fontsize=10];"]
    for L in links:
        style = ' style="dashed"' if str(L["confirmation"]).startswith("One end") else ""
        lbl = f'{L["a_port"]}\\n{L.get("b_port") or "?"}'
        dot.append(f'    "{L["a_host"]}" -- "{L["b_host"]}" [label="{lbl}"{style}];')
    dot.append("}")
    dot_path = os.path.join(out_dir, basename + ".dot")
    with open(dot_path, "w", encoding="utf-8") as f:
        f.write("\n".join(dot) + "\n")

    logger.info(f"  [OK] Topology diagram: {mm_path} , {dot_path} "
                f"({len(links)} link(s), {len(nodes)} node(s))")
    return [mm_path, dot_path]
