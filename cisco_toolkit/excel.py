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

from cisco_toolkit.analyze import (
    _health_band, _physical_uplink_index, _poe_device_util, build_network_model,
    compute_causality_chains, compute_failure_impact, compute_findings,
    compute_move_groups, compute_topology_links,
)
from cisco_toolkit.cmdio import _load_cmd_output
from cisco_toolkit.model import DevicePhysical, InterfaceData
from cisco_toolkit.parse import (
    _classify_media, _is_physical_port, _parse_fhrp, _parse_poe_watts,
    parse_auth_sessions, parse_bgp_summary, parse_dhcp_snooping_binding,
    parse_eigrp_neighbors, parse_interface_phy, parse_ospf_neighbors,
    parse_port_security, parse_show_interface_counters,
)
from cisco_toolkit.textutils import _split_macs, normalize_ifname, normalize_speed

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


# =============================================================================
# Health / analysis sheet writers (PHASE 2.7 step 23): render already-computed
# records (main() computes via the analyze layer and passes them in). _SEV_FILL is
# the shared severity fill-colour map (also used by the causality/failure/physical
# writers still in the monolith, which import it back).
# =============================================================================
_SEV_FILL = {"High": "F4CCCC", "Medium": "FCE5CD", "Low": "FFF2CC", "Info": "EFEFEF"}

CROSS_LAYER_SHEET_NAME = "Cross-Layer Analysis"
_CL_FILL = {"Critical": "FF5775", "High": "F4CCCC", "Medium": "FCE5CD", "Low": "FFF2CC", "Info": "EFEFEF"}

def write_cross_layer_sheet(wb, findings: List[dict]) -> None:
    """Write the 'Cross-Layer Analysis' sheet from compute_cross_layer_correlations()."""

    ws = wb.create_sheet(CROSS_LAYER_SHEET_NAME)
    headers = ["CL", "Severity", "Layers", "Finding", "Detail", "Recommendation"]
    for col, h in enumerate(headers, 1):
        c = ws.cell(1, col, h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="434343")
        c.alignment = Alignment(horizontal="center")
    for r, f in enumerate(findings, 2):
        vals = [f["id"], f["severity"], f["layers"], f["title"], f["detail"], f["recommendation"]]
        for col, v in enumerate(vals, 1):
            c = ws.cell(r, col, v)
            if col == 2 and f["severity"] in _CL_FILL:
                c.fill = PatternFill("solid", fgColor=_CL_FILL[f["severity"]])
                c.font = Font(bold=True)
    for i, w in enumerate([7, 9, 8, 42, 60, 52], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"
    if not findings:
        ws.cell(2, 1, "No cross-layer correlations found (no compounded L1/L2/L3 risks detected).")
    logger.info(f"  [OK] '{CROSS_LAYER_SHEET_NAME}' sheet: {len(findings)} cross-layer finding(s)")


PROTOCOL_HEALTH_SHEET_NAME = "Protocol Health"

def write_protocol_health_sheet(wb, records: List[dict]) -> None:
    """Write the 'Protocol Health' sheet from compute_protocol_health()."""

    ws = wb.create_sheet(PROTOCOL_HEALTH_SHEET_NAME)
    headers = ["Switch", "Protocol", "Summary", "Detail", "Health"]
    for col, h in enumerate(headers, 1):
        c = ws.cell(1, col, h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="434343")
        c.alignment = Alignment(horizontal="center")
    word = {"High": "DEGRADED", "Medium": "WARNING", "Low": "MINOR", "Info": "OK"}
    for r, rec in enumerate(records, 2):
        vals = [rec["switch"], rec["protocol"], rec["summary"], rec["detail"],
                word.get(rec["severity"], rec["severity"])]
        for col, v in enumerate(vals, 1):
            c = ws.cell(r, col, v)
            if col == 5 and rec["severity"] in _SEV_FILL:
                c.fill = PatternFill("solid", fgColor=_SEV_FILL[rec["severity"]])
                c.font = Font(bold=True)
    for i, w in enumerate([16, 13, 46, 50, 11], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"
    n_bad = sum(1 for x in records if x["severity"] in ("High", "Medium"))
    logger.info(f"  [OK] '{PROTOCOL_HEALTH_SHEET_NAME}' sheet: {len(records)} row(s), {n_bad} flagged")


HEALTH_SCORES_SHEET_NAME = "Health Scores"
MIGRATION_READINESS_SHEET_NAME = "Migration Readiness"
SCORE_SENSITIVITY_SHEET_NAME = "Score Sensitivity"   # NEW-V3.23.5
_READY_FILL = {"READY": "36E08A", "CAUTION": "FFE566", "NOT READY": "FF5775"}
_STATUS_FILL = {"pass": "36E08A", "warn": "FFE566", "fail": "FF5775"}

def write_health_scores_sheet(wb, records: List[dict]) -> None:
    ws = wb.create_sheet(HEALTH_SCORES_SHEET_NAME)
    headers = ["Switch", "Score", "Band", "Data Quality", "Top Deductions"]
    for col, h in enumerate(headers, 1):
        c = ws.cell(1, col, h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="434343")
        c.alignment = Alignment(horizontal="center")
    for r, rec in enumerate(records, 2):
        _lbl, fill = _health_band(rec["score"])
        if rec.get("band") == "Insufficient Data":            # NEW-V3.23.7: neutral grey, not green
            fill = "B0B0B0"
        ws.cell(r, 1, rec["switch"])
        c = ws.cell(r, 2, rec["score"]); c.fill = PatternFill("solid", fgColor=fill); c.font = Font(bold=True)
        c2 = ws.cell(r, 3, rec["band"]); c2.fill = PatternFill("solid", fgColor=fill)
        dq = rec.get("data_quality")
        ws.cell(r, 4, "" if dq is None else f"{int(round(dq * 100))}%")
        ws.cell(r, 5, "; ".join(rec["deductions"]) if rec["deductions"] else "healthy")
    for i, w in enumerate([16, 8, 11, 13, 80], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"
    avg = round(sum(r["score"] for r in records) / len(records)) if records else 0
    logger.info(f"  [OK] '{HEALTH_SCORES_SHEET_NAME}' sheet: {len(records)} switch(es), avg score {avg}")

def write_score_sensitivity_sheet(wb, records: List[dict]) -> None:
    """Write the 'Score Sensitivity' sheet from compute_score_sensitivity()."""
    ws = wb.create_sheet(SCORE_SENSITIVITY_SHEET_NAME)
    headers = ["Perturbation", "Switches Changing Band", "Detail"]
    for col, h in enumerate(headers, 1):
        c = ws.cell(1, col, h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="434343")
        c.alignment = Alignment(horizontal="center")
    for r, rec in enumerate(records, 2):
        ws.cell(r, 1, rec["perturbation"])
        c = ws.cell(r, 2, rec["switches_changed_band"])
        if rec["switches_changed_band"]:
            c.font = Font(bold=True)
        ws.cell(r, 3, rec["detail"])
    for i, w in enumerate([20, 24, 80], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"
    flips = sum(1 for r in records if r["switches_changed_band"])
    logger.info(f"  [OK] '{SCORE_SENSITIVITY_SHEET_NAME}' sheet: {len(records)} perturbation(s), {flips} with band changes")


def write_migration_readiness_sheet(wb, readiness: List[dict]) -> None:
    ws = wb.create_sheet(MIGRATION_READINESS_SHEET_NAME)
    headers = ["Group / Check", "Status", "Detail"]
    for col, h in enumerate(headers, 1):
        c = ws.cell(1, col, h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="434343")
        c.alignment = Alignment(horizontal="center")
    r = 2
    for g in readiness:
        c = ws.cell(r, 1, f"{g['group']}  ({len(g['switches'])} switch(es), {g['endpoints']} endpoint(s))")
        c.font = Font(bold=True)
        cs = ws.cell(r, 2, g["readiness"])
        cs.font = Font(bold=True)
        if g["readiness"] in _READY_FILL:
            cs.fill = PatternFill("solid", fgColor=_READY_FILL[g["readiness"]])
        ws.cell(r, 3, ", ".join(g["switches"]))
        r += 1
        for chk in g["checks"]:
            ws.cell(r, 1, "    " + chk["check"])
            sc = ws.cell(r, 2, chk["status"].upper())
            if chk["status"] in _STATUS_FILL:
                sc.fill = PatternFill("solid", fgColor=_STATUS_FILL[chk["status"]])
            ws.cell(r, 3, chk["note"])
            r += 1
        r += 1   # blank row between groups
    for i, w in enumerate([40, 9, 70], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"
    nready = sum(1 for g in readiness if g["readiness"] == "READY")
    logger.info(f"  [OK] '{MIGRATION_READINESS_SHEET_NAME}' sheet: {len(readiness)} group(s), {nready} READY")


# =============================================================================
# Tier-2 (file-reading) + intelligence sheet writers (PHASE 2.7 step 24).
# interface-health / security / routing read collected output (cmdio._load_cmd_output)
# and call parse.py parsers; causality / failure call the analyze blast-radius computes.
# =============================================================================
INTERFACE_HEALTH_SHEET_NAME = "Interface Health"

def write_interface_health_sheet(wb, all_cmd_to_files: Dict[str, Dict[str, str]]) -> None:
    """One row per interface with a health signal worth seeing: any errors/CRC/drops,
    or oper-up with 'Last input never' (connected-but-idle, a retire candidate)."""
    cols = ["Hostname", "Port", "Oper", "Input Errors", "CRC", "Output Drops",
            "Last Input", "Last Output", "Flag"]
    if INTERFACE_HEALTH_SHEET_NAME in wb.sheetnames:
        del wb[INTERFACE_HEALTH_SHEET_NAME]
    ws = wb.create_sheet(INTERFACE_HEALTH_SHEET_NAME)
    _census_header(ws, cols)
    DAT_FONT = Font(name="Calibri", size=10)
    DAT_L = Alignment(horizontal="left", vertical="center")
    DAT_C = Alignment(horizontal="center", vertical="center")
    warn = PatternFill("solid", fgColor="F4CCCC")
    idle = PatternFill("solid", fgColor="FFF2CC")
    rows = []
    for host in sorted(all_cmd_to_files):
        out = _load_cmd_output(all_cmd_to_files[host], "show interfaces", "show interface")
        if not out:
            continue
        for port, rec in parse_show_interface_counters(out).items():
            ie = rec["input_errors"] if isinstance(rec["input_errors"], int) else 0
            cr = rec["crc"] if isinstance(rec["crc"], int) else 0
            od = rec["output_drops"] if isinstance(rec["output_drops"], int) else 0
            has_err = bool(ie or cr or od)
            is_idle = (str(rec["oper"]).lower().startswith("up")
                       and str(rec["last_input"]).lower() == "never")
            if not (has_err or is_idle):
                continue
            flag = []
            if has_err: flag.append("Errors")
            if is_idle: flag.append("Up but idle (no input)")
            rows.append((host, port, rec, "; ".join(flag), has_err, is_idle))
    def _key(t):
        host, port = t[0], t[1]
        nums = [int(x) for x in re.findall(r"\d+", port)]
        return (host.lower(), port[:2].lower(), nums)
    rows.sort(key=_key)
    r = 2
    for host, port, rec, flag, has_err, is_idle in rows:
        vals = [host, port, rec["oper"], rec["input_errors"], rec["crc"],
                rec["output_drops"], rec["last_input"], rec["last_output"], flag]
        for col, v in enumerate(vals, 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT_FONT
            c.alignment = DAT_C if 4 <= col <= 6 else DAT_L
        if has_err:
            ws.cell(row=r, column=9).fill = warn
        elif is_idle:
            ws.cell(row=r, column=9).fill = idle
        r += 1
    _census_autofit(ws, len(cols), r - 1)
    logger.info(f"  [OK] '{INTERFACE_HEALTH_SHEET_NAME}' sheet: {len(rows)} port(s) flagged")


SECURITY_SHEET_NAME = "Security Posture"

def write_security_posture_sheet(wb, all_cmd_to_files: Dict[str, Dict[str, str]]) -> None:
    """One row per port with port-security, an 802.1X session, or DHCP-snoop bindings."""
    cols = ["Hostname", "Port", "Port-Security Max", "PS Current", "PS Violations",
            "PS Action", "802.1X Method", "802.1X Status", "Auth MAC", "DHCP-Snoop Bindings"]
    if SECURITY_SHEET_NAME in wb.sheetnames:
        del wb[SECURITY_SHEET_NAME]
    ws = wb.create_sheet(SECURITY_SHEET_NAME)
    _census_header(ws, cols)
    DAT_FONT = Font(name="Calibri", size=10)
    DAT_L = Alignment(horizontal="left", vertical="center")
    rows = []
    for host in sorted(all_cmd_to_files):
        c2f = all_cmd_to_files[host]
        ps = parse_port_security(_load_cmd_output(c2f, "show port-security"))
        au = parse_auth_sessions(_load_cmd_output(c2f, "show authentication sessions"))
        ds = parse_dhcp_snooping_binding(_load_cmd_output(c2f, "show ip dhcp snooping binding"))
        for p in (set(ps) | set(au) | set(ds)):
            pv = ps.get(p, {}); av = au.get(p, {})
            rows.append((host, p, pv.get("max", ""), pv.get("current", ""),
                         pv.get("violations", ""), pv.get("action", ""),
                         av.get("method", ""), av.get("status", ""), av.get("mac", ""),
                         ds.get(p, "")))
    def _key(t):
        host, port = t[0], t[1]
        nums = [int(x) for x in re.findall(r"\d+", port)]
        return (host.lower(), port[:2].lower(), nums)
    rows.sort(key=_key)
    r = 2
    for row in rows:
        for col, v in enumerate(row, 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT_FONT; c.alignment = DAT_L
        r += 1
    _census_autofit(ws, len(cols), r - 1)
    logger.info(f"  [OK] '{SECURITY_SHEET_NAME}' sheet: {len(rows)} port(s)")


ROUTING_SHEET_NAME = "Routing Adjacencies"

def write_routing_adjacency_sheet(wb, all_cmd_to_files: Dict[str, Dict[str, str]]) -> None:
    """One row per dynamic-routing adjacency (OSPF/EIGRP neighbor, BGP peer)."""
    cols = ["Hostname", "Protocol", "Neighbor", "State / PfxRcd", "Interface / AS"]
    if ROUTING_SHEET_NAME in wb.sheetnames:
        del wb[ROUTING_SHEET_NAME]
    ws = wb.create_sheet(ROUTING_SHEET_NAME)
    _census_header(ws, cols)
    DAT_FONT = Font(name="Calibri", size=10)
    DAT_L = Alignment(horizontal="left", vertical="center")
    rows = []
    for host in sorted(all_cmd_to_files):
        c2f = all_cmd_to_files[host]
        for n in parse_ospf_neighbors(_load_cmd_output(c2f, "show ip ospf neighbor")):
            rows.append((host, "OSPF", n["neighbor"], n["state"], n["interface"]))
        for n in parse_eigrp_neighbors(_load_cmd_output(c2f, "show ip eigrp neighbors")):
            rows.append((host, "EIGRP", n["neighbor"], n["state"], n["interface"]))
        for n in parse_bgp_summary(_load_cmd_output(c2f, "show ip bgp summary", "show bgp summary")):
            rows.append((host, "BGP", n["neighbor"], n["state"], f"AS {n['as']}"))
    r = 2
    for row in sorted(rows, key=lambda t: (t[0].lower(), t[1], t[2])):
        for col, v in enumerate(row, 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT_FONT; c.alignment = DAT_L
        r += 1
    _census_autofit(ws, len(cols), r - 1)
    logger.info(f"  [OK] '{ROUTING_SHEET_NAME}' sheet: {len(rows)} adjacency(ies)")


CAUSALITY_SHEET_NAME = "Causality Chains"
FAILURE_SHEET_NAME   = "Failure Impact"

def write_causality_chains_sheet(wb, all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> None:
    """Write (or replace) 'Causality Chains': cause -> mechanism -> blast radius reasoning."""
    cols = ["Severity", "Trigger (root cause)", "Mechanism (why it propagates)",
            "Impact (blast radius)", "Mitigation"]
    if CAUSALITY_SHEET_NAME in wb.sheetnames:
        del wb[CAUSALITY_SHEET_NAME]
    ws = wb.create_sheet(CAUSALITY_SHEET_NAME)
    _census_header(ws, cols)
    chains = compute_causality_chains(all_interfaces)
    DAT_FONT = Font(name="Calibri", size=10)
    DAT_L = Alignment(horizontal="left", vertical="top", wrap_text=True)
    r = 2
    for sev, trig, mech, impact, mit in chains:
        for col, v in enumerate([sev, trig, mech, impact, mit], 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT_FONT; c.alignment = DAT_L
            if col == 1 and sev in _SEV_FILL:
                c.fill = PatternFill("solid", fgColor=_SEV_FILL[sev])
        r += 1
    _census_autofit(ws, len(cols), r - 1)
    for colL, w in (("B", 34), ("C", 46), ("D", 46), ("E", 40)):
        ws.column_dimensions[colL].width = w
    logger.info(f"  [OK] '{CAUSALITY_SHEET_NAME}' sheet: {len(chains)} chain(s)")


def write_failure_impact_sheet(wb, all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> None:
    """Write (or replace) 'Failure Impact': per-switch migration blast-radius simulation."""
    cols = ["Severity", "Switch (remove / migrate)", "VLANs Impacted", "Stranded Endpoints",
            "Hard Partitions", "Backup-Covered", "FHRP-Covered", "Per-VLAN Detail"]
    if FAILURE_SHEET_NAME in wb.sheetnames:
        del wb[FAILURE_SHEET_NAME]
    ws = wb.create_sheet(FAILURE_SHEET_NAME)
    _census_header(ws, cols)
    rows = compute_failure_impact(all_interfaces)
    DAT_FONT = Font(name="Calibri", size=10)
    DAT_L = Alignment(horizontal="left", vertical="top", wrap_text=True)
    r = 2
    for rec in rows:
        vals = [rec["severity"], rec["host"], rec["vlans_impacted"], rec["stranded"],
                rec["hard"], rec["backup"], rec["fhrp"], rec["detail"]]
        for col, v in enumerate(vals, 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT_FONT; c.alignment = DAT_L
            if col == 1 and rec["severity"] in _SEV_FILL:
                c.fill = PatternFill("solid", fgColor=_SEV_FILL[rec["severity"]])
        r += 1
    _census_autofit(ws, len(cols), r - 1)
    ws.column_dimensions["H"].width = 70
    logger.info(f"  [OK] '{FAILURE_SHEET_NAME}' sheet: {len(rows)} switch(es) analyzed")


# =============================================================================
# Fused compute-in-writer sheets (PHASE 2.7 step 25): write_physical_health_sheet
# and write_l3_forwarding_sheet compute their L1/L3 records inline AND return them to
# main() (for the snapshot); write_flow_trace_sheet renders a trace_full_flow() dict.
# =============================================================================
PHYSICAL_HEALTH_SHEET_NAME = "Physical Health"

def write_physical_health_sheet(wb, all_interfaces: Dict[str, Dict[str, InterfaceData]],
                                all_cmd_to_files: Dict[str, Dict[str, str]],
                                all_device_physical: List[DevicePhysical]) -> List[dict]:
    """Write the 'Physical Health' (L1) sheet and return its records for the snapshot.
    One row per physical port; risk flag derived purely from already-parsed data."""

    model = build_network_model(all_interfaces)
    uplink_ports, single_fiber = _physical_uplink_index(model)
    poe_util = _poe_device_util(all_device_physical)

    headers = ["Switch", "Port", "Status", "Negotiated Speed", "Duplex", "Media Type",
               "Input Errors", "CRC Errors", "Output Drops", "Port-Channel",
               "PoE Allocated (W)", "Physical Risk"]

    def _intpos(v):
        return isinstance(v, int) and v > 0

    records: List[dict] = []
    for host in sorted(all_interfaces):
        c2f = all_cmd_to_files.get(host, {})
        out = _load_cmd_output(c2f, "show interfaces", "show interface")
        counters = parse_show_interface_counters(out) if out else {}
        phy = parse_interface_phy(out) if out else {}
        poe_out = _load_cmd_output(c2f, "show power inline")
        poe_watts = _parse_poe_watts(poe_out) if poe_out else {}

        for port, d in sorted(all_interfaces[host].items()):
            if not _is_physical_port(port):
                continue
            cnt = counters.get(port, {})
            ph = phy.get(port, {})

            status = d.status or cnt.get("oper", "")
            oper_up = bool(re.search(r"up|connected", (cnt.get("oper", "") or status or ""), re.IGNORECASE))

            speed = ph.get("speed") or normalize_speed(d.speed) or d.speed or ""
            duplex = ph.get("duplex") or ""                    # DETAIL is authoritative for half
            media = ph.get("media") or (_classify_media(d.port_type) if d.port_type else "")

            ie = cnt.get("input_errors", "")
            crc = cnt.get("crc", "")
            od = cnt.get("output_drops", "")
            pc = d.port_channel or ""

            # PoE cell: per-port watts if parseable, else the status word; mark over-budget devices.
            watts = poe_watts.get(port)
            if watts is not None:
                poe_cell = f"{watts:g} W"
            elif d.poe_status:
                poe_cell = d.poe_status
            else:
                poe_cell = ""
            util = poe_util.get(host)
            if util is not None and util > 90 and (watts is not None or d.poe_status):
                poe_cell = (poe_cell + f"  (dev PoE {util:g}%)").strip()

            # ---- risk derivation (highest severity wins for the cell fill) ----
            flags: List[str] = []
            sev = "Info"
            is_uplink = (host, port) in uplink_ports
            is_trunk = (d.switchport_mode or "").strip().lower() == "trunk"

            if re.search(r"err[- ]?disab", (status or ""), re.IGNORECASE):
                flags.append("err-disabled"); sev = "High"
            if duplex == "Half" and (is_trunk or is_uplink):
                flags.append("half-duplex"); sev = "High"
            if (host, port) in single_fiber:
                flags.append("single-fiber-uplink")
                if sev != "High": sev = "Medium"
            if oper_up and (_intpos(ie) or _intpos(crc) or _intpos(od)):
                flags.append("error-rate-high")
                if sev != "High": sev = "Medium"
            if not flags:
                flags = ["ok"]

            records.append({"switch": host, "port": port, "status": status or "",
                            "speed": speed or "unknown", "duplex": duplex or "unknown",
                            "media": media or "unknown", "input_errors": ie, "crc_errors": crc,
                            "output_drops": od, "port_channel": pc, "poe": poe_cell,
                            "risk": "; ".join(flags), "severity": sev})

    # ---- write the sheet ----
    ws = wb.create_sheet(PHYSICAL_HEALTH_SHEET_NAME)
    hdr_font = Font(bold=True, color="FFFFFF")
    hdr_fill = PatternFill("solid", fgColor="434343")
    for col, h in enumerate(headers, 1):
        c = ws.cell(1, col, h)
        c.font = hdr_font
        c.fill = hdr_fill
        c.alignment = Alignment(horizontal="center")
    for r, rec in enumerate(records, 2):
        vals = [rec["switch"], rec["port"], rec["status"], rec["speed"], rec["duplex"],
                rec["media"], rec["input_errors"], rec["crc_errors"], rec["output_drops"],
                rec["port_channel"], rec["poe"], rec["risk"]]
        for col, v in enumerate(vals, 1):
            c = ws.cell(r, col, v)
            if col == len(headers) and rec["severity"] in _SEV_FILL:     # fill Physical Risk cell
                c.fill = PatternFill("solid", fgColor=_SEV_FILL[rec["severity"]])
    for i, w in enumerate([16, 16, 14, 16, 9, 14, 12, 11, 13, 13, 18, 28], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"

    n_flagged = sum(1 for x in records if x["risk"] != "ok")
    logger.info(f"  [OK] '{PHYSICAL_HEALTH_SHEET_NAME}' sheet: {len(records)} physical port(s), "
                f"{n_flagged} flagged")
    return records


FLOW_TRACE_SHEET_NAME = "Flow Trace"
_RISK_FILL = {"LOW": "36E08A", "MEDIUM": "FFE566", "HIGH": "FF9F45", "CRITICAL": "FF5775"}
_RISK_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}

def write_flow_trace_sheet(wb, flow: dict) -> None:
    """Write the 'Flow Trace' sheet from a trace_full_flow() result."""

    s = flow["summary"]
    ws = wb.create_sheet(FLOW_TRACE_SHEET_NAME)
    bold = Font(bold=True)

    ws.cell(1, 1, f"Flow Trace  {s['src_ip']}  ->  {s['dst_ip']}").font = Font(bold=True, size=13)
    meta = [("Source", s["src_location"]), ("Destination", s["dst_location"]),
            ("Flow type", s["flow_type"]),
            ("SPOFs on path", f"{s['spof_count']}" + (f"  ({', '.join(s['spofs'])})" if s["spofs"] else "")),
            ("Risk level", s["risk"])]
    r = 2
    for label, val in meta:
        ws.cell(r, 1, label).font = bold
        c = ws.cell(r, 2, val)
        if label == "Risk level" and s["risk"] in _RISK_FILL:
            c.fill = PatternFill("solid", fgColor=_RISK_FILL[s["risk"]])
            c.font = bold
        r += 1
    r += 1

    headers = ["#", "Layer", "From", "To", "Interface", "Detail", "SPOF"]
    for col, h in enumerate(headers, 1):
        c = ws.cell(r, col, h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="434343")
        c.alignment = Alignment(horizontal="center")
    r += 1
    for hop in flow["hops"]:
        vals = [hop["n"], hop["layer"], hop["from"], hop["to"], hop["iface"], hop["detail"],
                "YES" if hop["spof"] else ""]
        for col, v in enumerate(vals, 1):
            c = ws.cell(r, col, v)
            if hop["spof"]:
                c.fill = PatternFill("solid", fgColor="F4CCCC")
        r += 1

    for i, w in enumerate([5, 8, 16, 16, 16, 60, 7], 1):
        ws.column_dimensions[chr(64 + i)].width = w

    logger.info(f"  [OK] '{FLOW_TRACE_SHEET_NAME}' sheet: {len(flow['hops'])} hop(s), "
                f"risk {s['risk']}, {s['spof_count']} SPOF(s)")


L3_FORWARDING_SHEET_NAME = "L3 Forwarding Map"

def _parse_track(output: str) -> dict:
    """Best-effort 'show track' (IOS + NX-OS) -> {objects:[{id,desc,state}], up, down}.
    State is Up/Down/'' (unknown). Device-level; not bound to a specific SVI."""
    objs: List[dict] = []
    cur = None
    for line in output.splitlines():
        m = re.match(r"^Track\s+(\d+)\b", line.strip())
        if m:
            cur = {"id": m.group(1), "desc": "", "state": ""}
            objs.append(cur)
            continue
        if cur is None:
            continue
        sm = (re.search(r"\b(?:reachability|line[- ]protocol|list|threshold|state)\s+is\s+(up|down)\b", line, re.IGNORECASE)
              or re.search(r"\bis\s+(up|down)\b", line, re.IGNORECASE))
        if sm and not cur["state"]:
            cur["state"] = sm.group(1).capitalize()
        elif not cur["desc"] and line.strip() and not re.search(r"\b(up|down)\b", line, re.IGNORECASE):
            cur["desc"] = line.strip()[:40]
    down = sum(1 for o in objs if o["state"].lower() == "down")
    up = sum(1 for o in objs if o["state"].lower() == "up")
    return {"objects": objs, "up": up, "down": down}

def _track_summary(tr: dict) -> str:
    if not tr or not tr["objects"]:
        return ""
    head = f"{len(tr['objects'])} obj"
    if tr["down"]:
        head += f" ({tr['down']} DOWN)"
    detail = "; ".join(f"T{o['id']}:{o['state'] or '?'}" for o in tr["objects"][:6])
    return f"{head} - {detail}" if detail else head

def write_l3_forwarding_sheet(wb, all_interfaces: Dict[str, Dict[str, InterfaceData]],
                              all_cmd_to_files: Dict[str, Dict[str, str]]) -> List[dict]:
    """Write the 'L3 Forwarding Map' sheet and return its records for the snapshot."""

    # gateways per VLAN across all scanned switches (for the redundancy signal)
    vlan_gw: Dict[int, set] = {}
    for host in all_interfaces:
        for port, d in all_interfaces[host].items():
            m = re.match(r"^Vlan(\d+)$", port, re.IGNORECASE)
            if m and (d.svi_ip or d.hsrp_behavior or d.subnet_primary_route):
                vlan_gw.setdefault(int(m.group(1)), set()).add(host)

    # per-device object tracking (best effort)
    track_by_host: Dict[str, dict] = {}
    for host in all_interfaces:
        out = _load_cmd_output(all_cmd_to_files.get(host, {}), "show track")
        track_by_host[host] = _parse_track(out) if out else {"objects": [], "up": 0, "down": 0}

    headers = ["Switch", "VLAN", "SVI IP", "FHRP", "Role", "Virtual IP", "Routing Source",
               "Next Hop", "Primary Subnet", "Backup / Secondary", "Tracking", "L3 Risk"]

    records: List[dict] = []
    for host in sorted(all_interfaces):
        tr = track_by_host.get(host, {"objects": [], "up": 0, "down": 0})
        tsum = _track_summary(tr)
        for port, d in sorted(all_interfaces[host].items(),
                              key=lambda kv: int(re.match(r"^Vlan(\d+)$", kv[0], re.IGNORECASE).group(1))
                              if re.match(r"^Vlan(\d+)$", kv[0], re.IGNORECASE) else 1 << 30):
            m = re.match(r"^Vlan(\d+)$", port, re.IGNORECASE)
            if not m:
                continue
            if not (d.svi_ip or d.hsrp_behavior or d.subnet_primary_route):
                continue
            vid = int(m.group(1))
            proto, role, vip, _grp = _parse_fhrp(d.hsrp_behavior)
            gw_count = len(vlan_gw.get(vid, set()))

            flags: List[str] = []
            sev = "Info"
            if tr["down"] > 0:
                flags.append("tracked-object-down"); sev = "High"
            if gw_count <= 1:
                flags.append("single-gateway")
                if sev != "High":
                    sev = "Medium"
            elif not proto:
                flags.append("no-FHRP")
                if sev == "Info":
                    sev = "Low"
            if not flags:
                flags = ["ok"]

            records.append({"switch": host, "vlan": vid, "svi_ip": d.svi_ip or "",
                            "fhrp": proto or "none", "role": role or "", "vip": vip or "",
                            "routing_source": d.routing_source or "", "next_hop": d.route_next_hop or "",
                            "primary_subnet": d.subnet_primary_route or "",
                            "secondary": d.subnet_secondary_routes or "",
                            "tracking": tsum, "risk": "; ".join(flags), "severity": sev})

    ws = wb.create_sheet(L3_FORWARDING_SHEET_NAME)
    hdr_font = Font(bold=True, color="FFFFFF")
    hdr_fill = PatternFill("solid", fgColor="434343")
    for col, h in enumerate(headers, 1):
        c = ws.cell(1, col, h)
        c.font = hdr_font
        c.fill = hdr_fill
        c.alignment = Alignment(horizontal="center")
    for r, rec in enumerate(records, 2):
        vals = [rec["switch"], rec["vlan"], rec["svi_ip"], rec["fhrp"], rec["role"], rec["vip"],
                rec["routing_source"], rec["next_hop"], rec["primary_subnet"], rec["secondary"],
                rec["tracking"], rec["risk"]]
        for col, v in enumerate(vals, 1):
            c = ws.cell(r, col, v)
            if col == len(headers) and rec["severity"] in _SEV_FILL:
                c.fill = PatternFill("solid", fgColor=_SEV_FILL[rec["severity"]])
    for i, w in enumerate([16, 7, 15, 7, 9, 15, 16, 16, 18, 22, 30, 26], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"

    n_flagged = sum(1 for x in records if x["risk"] != "ok")
    logger.info(f"  [OK] '{L3_FORWARDING_SHEET_NAME}' sheet: {len(records)} gateway SVI(s), "
                f"{n_flagged} flagged")
    return records
