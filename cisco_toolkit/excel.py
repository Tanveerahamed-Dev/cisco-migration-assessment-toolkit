"""The Excel layer's shared helpers: the openpyxl header / sheet-formatting utilities
every write_* sheet uses (`_census_header`, `_census_autofit`), plus the template
header-matching primitives (`norm_header` / `HEADER_TO_FIELD` / `find_header_row` /
`ensure_headers`) and the port-row sort key (`sortkey`). Depends on openpyxl, stdlib,
and cisco_toolkit.textutils (a clean layer above analyze). Extracted verbatim from
COLLECT_PARSE_V3_23_0.py in PHASE 2.7 step 20 (behaviour byte-identical). The sheet
writers themselves follow in later steps; the monolith imports these back meanwhile."""
import ipaddress
import logging
import os
import re
from typing import Dict, List, Optional, Tuple

from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE, MergedCell
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from cisco_toolkit.analyze import (
    _health_band, _physical_uplink_index, _poe_device_util, build_network_model,
    compute_findings, compute_move_groups, compute_topology_links,
)
from cisco_toolkit.cmdio import _load_cmd_output
from cisco_toolkit.model import DevicePhysical, InterfaceData
from cisco_toolkit.parse import (
    _classify_media, _is_physical_port, _parse_fhrp, _parse_poe_watts,
    parse_auth_sessions, parse_bgp_summary, parse_dhcp_snooping_binding,
    parse_eigrp_neighbors, parse_interface_phy, parse_ospf_neighbors,
    parse_port_security, parse_show_interface_counters,
)
from cisco_toolkit.textutils import (
    PHYSICAL_IFACE_RE, _TRUNK_STATUS_WORDS, _split_macs, normalize_ifname, normalize_speed,
)

logger = logging.getLogger(__name__)


def _xls_sanitize(value):
    """Strip the control characters openpyxl rejects (IllegalCharacterError: 0x00-0x08, 0x0B-0x0C, 0x0E-0x1F)
    from a string; pass non-strings through unchanged. Device-derived free-text (a CDP/LLDP-advertised neighbour
    name, an interface description, a banner) can carry a BEL/VT/ESC -- collected with errors='ignore', which
    passes valid-UTF-8 control bytes through -- and a single one aborts the ENTIRE workbook, the one deliverable
    produced unconditionally (there is no --no-excel)."""
    return ILLEGAL_CHARACTERS_RE.sub("", value) if isinstance(value, str) else value


def _harden_ws(ws):
    """Wrap one worksheet's cell()/append() so every written string value is sanitized (no IllegalCharacterError)."""
    _orig_cell, _orig_append = ws.cell, ws.append

    def _cell(*args, **kwargs):
        if "value" in kwargs:
            kwargs["value"] = _xls_sanitize(kwargs["value"])
        elif len(args) >= 3:
            args = (args[0], args[1], _xls_sanitize(args[2])) + args[3:]
        return _orig_cell(*args, **kwargs)

    def _append(iterable):
        if isinstance(iterable, (list, tuple)):
            iterable = [_xls_sanitize(v) for v in iterable]
        return _orig_append(iterable)

    ws.cell, ws.append = _cell, _append


def harden_workbook(wb):
    """Make EVERY worksheet in wb sanitize string cell values, so a control character in any device-derived
    free-text field cannot abort the workbook. Covers every existing sheet (the template's own) AND every sheet
    created later via wb.create_sheet -- one chokepoint over all ~329 cell-write sites + any future one, so the
    safety can't drift the way a per-site helper would. Returns wb. Call once right after load_workbook()."""
    for ws in wb.worksheets:
        _harden_ws(ws)
    _orig_create = wb.create_sheet

    def _create(*args, **kwargs):
        ws = _orig_create(*args, **kwargs)
        _harden_ws(ws)
        return ws

    wb.create_sheet = _create
    return wb

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
    """One row per access/SVI VLAN -- the subset of the in-use VLANs that have an access port and/or a
    collected SVI, aggregated across all devices: where it lives, access-port and endpoint (MAC) counts,
    and its gateway/SVI. NOTE: this is a labelled SUBSET, not the in-use total -- the canonical "VLANs in
    use" count (executive_brief.scale.n_vlans, from analyze.vlan_inventory) also includes querier-only
    VLANs whose gateway sits on an uncollected device, which cannot populate a per-VLAN row here."""
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
            "# Endpoint MACs (per-switch sum)", "Gateways", "Redundant (STP-blocked) Paths", "Notes"]
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

def compute_capacity(all_device_physical: List[DevicePhysical]) -> List[dict]:
    """Per-switch port + PoE headroom for consolidation decisions (the single source of truth for the
    'Capacity' sheet AND the explorer's capacity card). One record per device, sorted by hostname:
    {hostname, model, total_ports, active_ports, free_ports, port_util, poe_capacity_w, poe_drawn_w,
     poe_remaining_w, poe_util, flags}. Numeric fields are "" when unknown (so the sheet renders blanks
     exactly as before); flags is a list of "Port-bound (>=90%)" / "PoE-bound (>=80%)"."""
    out: List[dict] = []
    for dp in sorted(all_device_physical, key=lambda d: d.hostname.lower()):
        total = dp.total_ports or 0
        active = dp.active_ports                              # None = active-port count NOT observed (distinct from 0)
        # honesty: a device whose active-port count was not observed must NOT read 0% utilization — it would
        # then rank first as "most consolidation headroom". Leave util/free blank when active_ports is unknown.
        free = max(total - active, 0) if (total and active is not None) else ""
        putil = round(100.0 * active / total, 1) if (total and active is not None) else ""
        cap, drawn = _to_float(dp.power_capacity_w), _to_float(dp.power_drawn_w)
        if dp.power_remaining_w:
            rem = dp.power_remaining_w
        elif cap is not None and drawn is not None:
            rem = round(cap - drawn, 1)
        else:
            rem = ""
        poe_util = round(100.0 * drawn / cap, 1) if (cap and drawn is not None and cap > 0) else ""
        flags = []
        if putil != "" and putil >= 85: flags.append("Port-bound (>=85%)")   # match design_advisor._PORT_UTIL_HOT=85 so workbook + design narrative agree (DET-capacity-04)
        if poe_util != "" and poe_util >= 80: flags.append("PoE-bound (>=80%)")
        out.append({"hostname": dp.hostname, "model": dp.model,
                    "total_ports": total or "", "active_ports": active or "", "free_ports": free,
                    "port_util": putil, "poe_capacity_w": dp.power_capacity_w,
                    "poe_drawn_w": dp.power_drawn_w, "poe_remaining_w": rem,
                    "poe_util": poe_util, "flags": flags})
    return out


def write_capacity_sheet(wb, all_device_physical: List[DevicePhysical]) -> None:
    """Write (or replace) 'Capacity': per-switch port and PoE headroom for
    consolidation decisions. Flags switches that are port- or PoE-bound.
    Renders the records from compute_capacity (one source of truth with the explorer)."""
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
    for rec in compute_capacity(all_device_physical):
        flags = rec["flags"]
        vals = [rec["hostname"], rec["model"], rec["total_ports"], rec["active_ports"], rec["free_ports"],
                rec["port_util"], rec["poe_capacity_w"], rec["poe_drawn_w"], rec["poe_remaining_w"],
                rec["poe_util"], "; ".join(flags)]
        for col, v in enumerate(vals, 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT_FONT
            c.alignment = DAT_C if 3 <= col <= 10 else DAT_L
            if flags and col in (6, 10): c.fill = warn_fill
        r += 1
    _census_autofit(ws, len(cols), r - 1)
    logger.info(f"  [OK] '{CAPACITY_SHEET_NAME}' sheet: {len(all_device_physical)} device(s)")


ENDPOINT_INTEL_SHEET_NAME = "Endpoint Intelligence"   # vendor + class per endpoint (NEW-V3.23.95)

def write_endpoint_intelligence_sheet(wb, identity: list) -> None:
    """Write (or replace) 'Endpoint Intelligence': one row per access-port endpoint with its VENDOR
    (MAC OUI -- a fact) and an inferred migration CLASS + confidence + the evidence that drove it.
    NEW-V3.23.95: renders the precomputed compute_endpoint_identity records (one source of truth with
    the snapshot / runbook / explorer). A class-distribution summary is written above the table."""
    cols = ["Switch", "Port", "VLAN", "Endpoint IP", "MACs", "Vendor (OUI fact)",
            "Class (inferred)", "Confidence", "Evidence"]
    if ENDPOINT_INTEL_SHEET_NAME in wb.sheetnames:
        del wb[ENDPOINT_INTEL_SHEET_NAME]
    ws = wb.create_sheet(ENDPOINT_INTEL_SHEET_NAME)
    _census_header(ws, cols)
    DAT_FONT = Font(name="Calibri", size=10)
    DAT_L = Alignment(horizontal="left", vertical="center")
    DAT_C = Alignment(horizontal="center", vertical="center")
    low_fill = PatternFill("solid", fgColor="F2F2F2")   # shade Unknown rows so eyes go to classified ones
    r = 2
    for rec in (identity or []):
        vals = [rec.get("host"), rec.get("port"), rec.get("vlan"), rec.get("ip"),
                rec.get("mac_count"), rec.get("vendor"), rec.get("endpoint_class"),
                rec.get("confidence"), rec.get("evidence")]
        unknown = rec.get("confidence") == "Unknown"
        for col, v in enumerate(vals, 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT_FONT
            c.alignment = DAT_C if col in (3, 5, 8) else DAT_L
            if unknown:
                c.fill = low_fill
        r += 1
    _census_autofit(ws, len(cols), r - 1)
    ws.column_dimensions["I"].width = 42
    logger.info(f"  [OK] '{ENDPOINT_INTEL_SHEET_NAME}' sheet: {len(identity or [])} endpoint(s)")


ENDPOINT_DEPS_SHEET_NAME = "Endpoint Dependencies"   # cohesive units / clusters (NEW-V3.23.96)

def write_endpoint_dependencies_sheet(wb, dependencies: dict) -> None:
    """Write (or replace) 'Endpoint Dependencies': the migration 'cohesive units' -- per (vendor, class)
    distributed system with its endpoint count and switch/VLAN spread, then the dual-homed endpoints
    (NIC-team / redundant legs to sequence make-before-break) and the per-VLAN app tiers. NEW-V3.23.96:
    renders the precomputed compute_endpoint_dependencies dict (one source of truth)."""
    if ENDPOINT_DEPS_SHEET_NAME in wb.sheetnames:
        del wb[ENDPOINT_DEPS_SHEET_NAME]
    ws = wb.create_sheet(ENDPOINT_DEPS_SHEET_NAME)
    cols = ["Section", "Vendor / detail", "Class", "Endpoints", "Switches", "VLANs", "Note"]
    _census_header(ws, cols)
    DAT = Font(name="Calibri", size=10)
    AL = Alignment(horizontal="left", vertical="center")
    CN = Alignment(horizontal="center", vertical="center")
    warn = PatternFill("solid", fgColor="FCE5CD")
    r = 2
    dep = dependencies or {}

    def row(vals, flag=False):
        nonlocal r
        for col, v in enumerate(vals, 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT
            c.alignment = CN if col in (4, 5, 6) else AL
            if flag and col == 7:
                c.fill = warn
        r += 1

    for c in (dep.get("clusters") or []):
        row(["Cluster", c.get("vendor", ""), c.get("endpoint_class", ""), c.get("count", ""),
             c.get("switches", ""), c.get("vlans", ""),
             "spans multiple move-groups — coordinate the waves" if c.get("spans_groups") else ""],
            flag=c.get("spans_groups"))
    for d in (dep.get("dual_homed") or []):
        row(["Dual-homed", f"{d.get('mac', '')}  [{', '.join(d.get('switches', []))}]",
             d.get("endpoint_class", ""), 1, len(d.get("switches", [])), "",
             "split across move-groups — sequence make-before-break" if d.get("split_across_groups")
             else "NIC-team / redundant legs — make-before-break"],
            flag=d.get("split_across_groups"))
    for a in (dep.get("affinity") or []):
        cls = ", ".join(f"{k} ({v})" for k, v in (a.get("classes") or {}).items())
        row(["VLAN tier", f"VLAN {a.get('vlan', '')}: {cls}", a.get("dominant", ""),
             a.get("total", ""), "", a.get("vlan", ""), ""])
    _census_autofit(ws, len(cols), r - 1)
    ws.column_dimensions["B"].width = 48; ws.column_dimensions["G"].width = 46
    n = len(dep.get("clusters") or []) + len(dep.get("dual_homed") or []) + len(dep.get("affinity") or [])
    logger.info(f"  [OK] '{ENDPOINT_DEPS_SHEET_NAME}' sheet: {n} dependency row(s)")


SUBNET_REACH_SHEET_NAME = "Subnet Reachability"   # per-device subnet source/destination (NEW-V3.23.97)

def write_subnet_reachability_sheet(wb, subnet_intelligence: dict) -> None:
    """Write (or replace) 'Subnet Reachability': per device, which subnets it is the DESTINATION for
    (terminates / gateways) vs can REACH (route table) vs -- for an L2 access switch -- which subnets
    its endpoints live in (via the SVI that gateways their VLAN). NEW-V3.23.97: renders the precomputed
    compute_subnet_intelligence (one source of truth). Route depth is from the full 'show ip route';
    BGP-received is populated only when the new 'show ip bgp' collection is present."""
    if SUBNET_REACH_SHEET_NAME in wb.sheetnames:
        del wb[SUBNET_REACH_SHEET_NAME]
    ws = wb.create_sheet(SUBNET_REACH_SHEET_NAME)
    cols = ["Switch", "Role", "Destination subnets (terminates)", "# Dest", "Reachable (#)",
            "Reachable sources", "Default next-hop", "L2: subnets via gateway", "BGP recv (#)"]
    _census_header(ws, cols)
    DAT = Font(name="Calibri", size=10)
    AL = Alignment(horizontal="left", vertical="top", wrap_text=True)
    CN = Alignment(horizontal="center", vertical="center")
    r = 2
    for rec in (subnet_intelligence or {}).get("per_device", []):
        dest = rec.get("destination_subnets", [])
        srcs = ", ".join(f"{k}:{v}" for k, v in (rec.get("reachable_sources") or {}).items())
        served = "; ".join(f"{s.get('subnet')} (gw {s.get('gateway')})" for s in rec.get("served_subnets", [])[:8])
        vals = [rec.get("host"), "L3" if rec.get("is_l3") else "L2",
                ", ".join(dest[:12]) + (f" (+{len(dest) - 12})" if len(dest) > 12 else ""),
                rec.get("destination_count", 0), rec.get("reachable_count", 0), srcs,
                rec.get("default_next_hop", ""), served, rec.get("bgp_received_count", 0)]
        for col, v in enumerate(vals, 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT
            c.alignment = CN if col in (2, 4, 5, 9) else AL
        r += 1
    _census_autofit(ws, len(cols), r - 1)
    ws.column_dimensions["C"].width = 40; ws.column_dimensions["H"].width = 44
    logger.info(f"  [OK] '{SUBNET_REACH_SHEET_NAME}' sheet: "
                f"{len((subnet_intelligence or {}).get('per_device', []))} device(s)")


MIGRATION_SCENARIO_SHEET_NAME = "Migration Scenarios"   # per-group cutover scenario (NEW-V3.23.98)

def write_migration_scenarios_sheet(wb, scenarios: dict) -> None:
    """Write (or replace) 'Migration Scenarios': per move-group, the recommended cutover scenario
    (phased / parallel-run / greenfield / big-bang) + rationale + dual-homing split, with the
    fleet-level recommendation in row 1. NEW-V3.23.98: renders compute_migration_scenarios."""
    if MIGRATION_SCENARIO_SHEET_NAME in wb.sheetnames:
        del wb[MIGRATION_SCENARIO_SHEET_NAME]
    ws = wb.create_sheet(MIGRATION_SCENARIO_SHEET_NAME)
    sc = scenarios or {}
    fleet = sc.get("fleet_recommendation", "")
    if fleet:
        ws.cell(row=1, column=1, value="Fleet recommendation:").font = Font(bold=True, size=10)
        c = ws.cell(row=1, column=2, value=fleet); c.font = Font(size=10)
        c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    hdr_row = 3 if fleet else 1
    cols = ["Move group", "Switches", "Endpoint MACs (per-switch sum)", "Readiness", "Dual-homed %", "Hard cutovers",
            "At-risk eps", "Recommended scenario", "Rationale"]
    for i, h in enumerate(cols, 1):
        cell = ws.cell(row=hdr_row, column=i, value=h)
        cell.font = Font(bold=True, color="FFFFFF", size=10); cell.fill = PatternFill("solid", fgColor="434343")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.freeze_panes = ws.cell(row=hdr_row + 1, column=1)
    SCFILL = {"parallel-run": "D9EAD3", "phased": "FFF2CC", "greenfield": "CFE2F3", "big-bang": "F4CCCC"}
    DAT = Font(name="Calibri", size=10)
    r = hdr_row + 1
    for g in sc.get("per_group", []):
        vals = [g.get("group") or "(group)", g.get("switches"), g.get("endpoints"), g.get("readiness"),
                g.get("dual_homed_pct"), g.get("hard_cutover"), g.get("hard_cutover_endpoints"),
                g.get("recommended_scenario"), g.get("rationale")]
        for col, v in enumerate(vals, 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT
            c.alignment = Alignment(horizontal="center" if 2 <= col <= 8 else "left",
                                    vertical="top", wrap_text=(col == 9))
            if col == 8:
                c.fill = PatternFill("solid", fgColor=SCFILL.get(v, "FFFFFF"))
        r += 1
    for colL, w in (("A", 16), ("I", 70)):
        ws.column_dimensions[colL].width = w
    logger.info(f"  [OK] '{MIGRATION_SCENARIO_SHEET_NAME}' sheet: {len(sc.get('per_group', []))} group(s)")


APPLICATION_INTEL_SHEET_NAME = "Application Intelligence"   # application-domain synthesis (NEW-V3.23.112)

def write_application_intelligence_sheet(wb, ai: dict) -> None:
    """Write (or replace) 'Application Intelligence' from compute_application_intelligence(): the
    application DOMAINS (workloads) with footprint, criticality tier, health rollup, migration-wave
    span, top migration risk + standard + the evidence that placed each switch, followed by a
    cross-domain (IGMP querier continuity / RFC 4541) risk block. NEW-V3.23.112."""
    if APPLICATION_INTEL_SHEET_NAME in wb.sheetnames:
        del wb[APPLICATION_INTEL_SHEET_NAME]
    ws = wb.create_sheet(APPLICATION_INTEL_SHEET_NAME)
    a = ai or {}
    s = a.get("summary") or {}
    summ = (f"{s.get('n_domains', 0)} domain(s)  ·  {s.get('n_on_air_critical', 0)} on-air-critical  ·  "
            f"{s.get('n_high_risk', 0)} with High/Critical risk  ·  {s.get('n_spanning_waves', 0)} span >1 wave  ·  "
            f"{s.get('n_cross_domain_risks', 0)} cross-domain risk(s)")
    ws.cell(row=1, column=1, value="Application & network intelligence:").font = Font(bold=True, size=10)
    c0 = ws.cell(row=1, column=2, value=summ); c0.font = Font(size=10)
    c0.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

    hdr_row = 3
    cols = ["Domain", "Tier", "Switches", "VLANs", "Endpoints", "Top endpoint classes", "PTP",
            "Worst health", "Waves", "Risks", "Top risk", "Standard", "Why (evidence)"]
    for i, h in enumerate(cols, 1):
        cell = ws.cell(row=hdr_row, column=i, value=h)
        cell.font = Font(bold=True, color="FFFFFF", size=10); cell.fill = PatternFill("solid", fgColor="434343")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.freeze_panes = ws.cell(row=hdr_row + 1, column=1)
    TIERFILL = {"On-air critical": "F4CCCC", "Production": "FFF2CC", "Support": "D9EAD3"}
    DAT = Font(name="Calibri", size=10)
    r = hdr_row + 1
    for d in a.get("domains", []):
        classes = ", ".join(f"{k} ({v})" for k, v in (d.get("classes") or {}).items())
        ptp = ("boundary-clocked" if d.get("ptp_boundary_clocked")
               else "present, NOT BC" if d.get("ptp_present") else "—")
        hh = d.get("health") or {}
        hstr = (hh.get("worst_band", "") or "—") + (
            f" ({hh.get('n_critical', 0)}C/{hh.get('n_poor', 0)}P)"
            if (hh.get("n_critical") or hh.get("n_poor")) else "")
        waves = ", ".join(d.get("waves") or []) or "—"
        risks = d.get("risks") or []
        toprisk = f"{risks[0]['severity']}: {risks[0]['title']}" if risks else "—"
        vals = [d.get("domain"), d.get("tier"), d.get("switch_count"), d.get("vlan_count"),
                d.get("endpoint_count"), classes or "—", ptp, hstr, waves, len(risks), toprisk,
                d.get("standard", "") or "—", d.get("evidence", "")]
        for col, v in enumerate(vals, 1):
            cc = ws.cell(row=r, column=col, value=v); cc.font = DAT
            cc.alignment = Alignment(horizontal="center" if col in (3, 4, 5, 7, 9, 10) else "left",
                                     vertical="top", wrap_text=col in (6, 11, 13))
            if col == 2:
                cc.fill = PatternFill("solid", fgColor=TIERFILL.get(v, "FFFFFF"))
        r += 1

    cross = a.get("cross_domain_risks") or []
    r += 1
    ws.cell(row=r, column=1,
            value="Cross-domain risks — IGMP querier continuity (RFC 4541)").font = Font(bold=True); r += 1
    if not cross:
        ws.cell(row=r, column=1, value="None detected."); r += 1
    else:
        for i, h in enumerate(["Severity", "Kind", "VLAN", "Detail", "Remediation", "Standard"], 1):
            cell = ws.cell(row=r, column=i, value=h); cell.font = Font(bold=True, size=10)
        r += 1
        for cr in cross:
            vals = [cr.get("severity"), cr.get("kind"), cr.get("vlan"), cr.get("detail"),
                    cr.get("remediation"), cr.get("standard")]
            for col, v in enumerate(vals, 1):
                cc = ws.cell(row=r, column=col, value=v); cc.font = DAT
                cc.alignment = Alignment(horizontal="left", vertical="top", wrap_text=col in (4, 5))
            r += 1

    # Inter-domain dependency block (NEW-V3.23.113): the coupling edges + the keystone domain.
    edges = a.get("edges") or []
    keystones = a.get("keystones") or []
    r += 1
    ws.cell(row=r, column=1, value="Inter-domain dependencies (couplings)").font = Font(bold=True); r += 1
    if keystones:
        k = keystones[0]
        ws.cell(row=r, column=1, value="Keystone (widest blast radius):").font = Font(size=10)
        ws.cell(row=r, column=2,
                value=f"{k.get('domain')} — degree {k.get('degree')}, {len(k.get('neighbors') or [])} neighbour(s)")
        r += 1
    if not edges:
        ws.cell(row=r, column=1, value="No cross-domain couplings detected."); r += 1
    else:
        for i, h in enumerate(["Domain A", "Domain B", "Weight", "Kinds", "Confidence", "Migration note"], 1):
            cell = ws.cell(row=r, column=i, value=h); cell.font = Font(bold=True, size=10)
        r += 1
        for e in edges:
            vals = [e.get("source"), e.get("target"), e.get("weight"), ", ".join(e.get("kinds") or []),
                    e.get("confidence"),
                    e.get("migration_note") or ("media-adjacent" if e.get("media") else "")]
            for col, v in enumerate(vals, 1):
                cc = ws.cell(row=r, column=col, value=v); cc.font = DAT
                cc.alignment = Alignment(horizontal="left" if col in (1, 2, 4, 5, 6) else "center",
                                         vertical="top", wrap_text=col in (4, 6))
            r += 1

    # Recommended cutover order block (NEW-V3.23.114): the domains ordered lowest-risk pilot first.
    order = a.get("cutover_order") or []
    if order:
        r += 1
        ws.cell(row=r, column=1,
                value="Recommended cutover order (lowest-risk pilot first)").font = Font(bold=True); r += 1
        for i, h in enumerate(["#", "Band", "Domain", "Tier", "Score", "Rationale"], 1):
            cell = ws.cell(row=r, column=i, value=h); cell.font = Font(bold=True, size=10)
        r += 1
        BANDFILL = {"Pilot": "D9EAD3", "Early": "E2EFDA", "Mid": "FFF2CC", "Late": "FCE4D6", "Last": "F4CCCC"}
        for c in order:
            vals = [c.get("order"), c.get("band"), c.get("domain"), c.get("tier"), c.get("score"),
                    c.get("rationale")]
            for col, v in enumerate(vals, 1):
                cc = ws.cell(row=r, column=col, value=v); cc.font = DAT
                cc.alignment = Alignment(horizontal="center" if col in (1, 5) else "left",
                                         vertical="top", wrap_text=col == 6)
                if col == 2:
                    cc.fill = PatternFill("solid", fgColor=BANDFILL.get(v, "FFFFFF"))
            r += 1

    for i, w in enumerate([34, 15, 9, 7, 10, 26, 16, 14, 12, 7, 40, 24, 34], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    logger.info(f"  [OK] '{APPLICATION_INTEL_SHEET_NAME}' sheet: {len(a.get('domains', []))} domain(s), "
                f"{len(cross)} cross-domain risk(s), {len(edges)} dependency edge(s), "
                f"{len(order)} cutover step(s)")


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


PROTOCOL_INTELLIGENCE_SHEET_NAME = "Protocol Intelligence"   # NEW-V3.23.100

def write_protocol_intelligence_sheet(wb, records: List[dict]) -> None:
    """Write the 'Protocol Intelligence' sheet from compute_protocol_intelligence(): each abnormal
    protocol state turned into meaning + likely cause + remediation (the observed state is a fact;
    the cause is Inferred per Cisco doctrine)."""
    ws = wb.create_sheet(PROTOCOL_INTELLIGENCE_SHEET_NAME)
    headers = ["Switch", "Protocol", "State", "Severity", "Meaning",
               "Likely cause (Inferred)", "Remediation"]
    for col, h in enumerate(headers, 1):
        c = ws.cell(1, col, h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="434343")
        c.alignment = Alignment(horizontal="center")
    if not records:
        ws.cell(2, 1, "No abnormal protocol states detected (control plane healthy).")
    for r, rec in enumerate(records, 2):
        vals = [rec["switch"], rec["protocol"], rec["state"], rec["severity"],
                rec["meaning"], rec["likely_cause"], rec["remediation"]]
        for col, v in enumerate(vals, 1):
            c = ws.cell(r, col, v)
            c.alignment = Alignment(vertical="top", wrap_text=col >= 5)
            if col == 4 and rec["severity"] in _SEV_FILL:
                c.fill = PatternFill("solid", fgColor=_SEV_FILL[rec["severity"]])
                c.font = Font(bold=True)
    for i, w in enumerate([22, 13, 8, 10, 44, 46, 50], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"
    n_high = sum(1 for x in records if x["severity"] == "High")
    logger.info(f"  [OK] '{PROTOCOL_INTELLIGENCE_SHEET_NAME}' sheet: {len(records)} advisory row(s), {n_high} High")


SERVICE_MAP_SHEET_NAME = "Service Map"   # NEW-V3.23.101

def write_service_map_sheet(wb, sm: dict) -> None:
    """Write the 'Service Map' sheet from compute_service_map(): L4 services referenced in ACLs
    (design intent -- Inferred, not active traffic) + fleet multicast activity."""
    ws = wb.create_sheet(SERVICE_MAP_SHEET_NAME)
    headers = ["Port", "Proto", "Service", "Category", "Broadcast/AV", "ACL refs", "Switches", "Evidence"]
    for col, h in enumerate(headers, 1):
        c = ws.cell(1, col, h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="434343")
        c.alignment = Alignment(horizontal="center")
    services = (sm or {}).get("services") or []
    r = 2
    if not services:
        ws.cell(r, 1, "No L4 service ports referenced in ACLs (rules are mostly permit-ip source allowlists)."); r += 1
    for s in services:
        vals = [s["port"], s["proto"], s["service"], s["category"], "yes" if s["broadcast"] else "",
                s["refs"], s["host_count"], s["evidence_class"]]
        for col, v in enumerate(vals, 1):
            ws.cell(r, col, v)
        r += 1
    # multicast activity block (Confirmed forwarding presence; per-group classification awaits richer collection)
    mc = (sm or {}).get("multicast") or {}
    r += 1
    ws.cell(r, 1, "Multicast activity").font = Font(bold=True); r += 1
    ws.cell(r, 1, "PIM/mroute-active interfaces"); ws.cell(r, 3, mc.get("active_interfaces", 0)); r += 1
    ws.cell(r, 1, "switches running multicast"); ws.cell(r, 3, mc.get("active_switch_count", 0)); r += 1
    note = ("per-group (S,G) / IGMP membership NOT collected (Unknown) -- re-run with 'show ip igmp groups'"
            if not mc.get("group_level_collected") else "per-group membership collected")
    ws.cell(r, 1, "group-level detail"); ws.cell(r, 3, note); r += 1
    for g in (mc.get("classified_groups") or []):
        ws.cell(r, 1, "multicast group"); ws.cell(r, 3, f"{g['group']} = {g['name']} ({g['category']})"); r += 1
    for i, w in enumerate([8, 8, 16, 14, 12, 9, 9, 52], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"
    logger.info(f"  [OK] '{SERVICE_MAP_SHEET_NAME}' sheet: {len(services)} service(s), "
                f"{mc.get('active_interfaces', 0)} multicast iface(s)")


MULTICAST_INTEL_SHEET_NAME = "Multicast Intelligence"   # NEW-V3.23.115 (media-fabric deep-dive)

def write_multicast_intelligence_sheet(wb, mi: dict) -> None:
    """Write 'Multicast Intelligence' from compute_multicast_intelligence(): MAC-address aliasing (RFC 4541),
    IGMP querier coverage, the PTP timing tree (ST 2059), and the per-group media census (with L2 MAC)."""
    if MULTICAST_INTEL_SHEET_NAME in wb.sheetnames:
        del wb[MULTICAST_INTEL_SHEET_NAME]
    ws = wb.create_sheet(MULTICAST_INTEL_SHEET_NAME)
    m = mi or {}
    s = m.get("summary") or {}
    HDR = Font(bold=True, color="FFFFFF", size=10); HFILL = PatternFill("solid", fgColor="434343")
    DAT = Font(name="Calibri", size=10)
    ws.cell(1, 1, "Multicast / media-fabric intelligence:").font = Font(bold=True, size=10)
    summ = (f"{s.get('n_groups', 0)} group(s) ({s.get('n_av_groups', 0)} broadcast/AV) · "
            f"{s.get('n_mac_clashes', 0)} MAC-alias clash(es) · {s.get('n_querier_gaps', 0)} querier gap(s) · "
            f"{s.get('n_ptp_dormant', 0)}/{s.get('n_ptp_clocks', 0)} PTP dormant · "
            f"{s.get('n_active_interfaces', 0)} mcast iface(s) / {s.get('n_active_switches', 0)} switch(es)")
    c0 = ws.cell(1, 2, summ); c0.font = Font(size=10)
    c0.alignment = Alignment(horizontal="left", wrap_text=True)
    r = [3]   # boxed row counter so the nested helpers can advance it

    def section(title):
        ws.cell(r[0], 1, title).font = Font(bold=True); r[0] += 1

    def header(cols):
        for i, h in enumerate(cols, 1):
            c = ws.cell(r[0], i, h); c.font = HDR; c.fill = HFILL
            c.alignment = Alignment(horizontal="center")
        r[0] += 1

    section("MAC-address aliasing (RFC 4541 — IPv4 multicast is 32:1 into L2 MACs)")
    aliases = m.get("mac_aliases") or []
    if not aliases:
        ws.cell(r[0], 1, "None — no two groups collapse to the same multicast MAC."); r[0] += 1
    else:
        header(["L2 MAC", "Overlapping groups", "On-air involved"])
        for a in aliases:
            ws.cell(r[0], 1, a.get("mac")).font = DAT
            ws.cell(r[0], 2, ", ".join(a.get("groups") or [])).font = DAT
            ws.cell(r[0], 3, "yes" if a.get("has_av") else "").font = DAT
            r[0] += 1
    r[0] += 1

    q = m.get("querier") or {}
    section("IGMP querier coverage (RFC 4541)")
    ws.cell(r[0], 1, "Multicast SVI VLANs"); ws.cell(r[0], 3, len(q.get("multicast_vlans") or [])); r[0] += 1
    ws.cell(r[0], 1, "VLANs with a querier"); ws.cell(r[0], 3, q.get("n_querier_vlans", 0)); r[0] += 1
    gaps = q.get("gap_vlans") or []
    ws.cell(r[0], 1, "Multicast VLANs WITHOUT a querier")
    ws.cell(r[0], 3, ", ".join(gaps) if gaps else "none (all covered)"); r[0] += 2

    p = m.get("ptp") or {}
    section("PTP timing tree (SMPTE ST 2059)")
    ws.cell(r[0], 1, "PTP clocks"); ws.cell(r[0], 3, p.get("n_clocks", 0)); r[0] += 1
    ws.cell(r[0], 1, "Operational boundary clocks"); ws.cell(r[0], 3, p.get("n_operational", 0)); r[0] += 1
    ws.cell(r[0], 1, "Dormant (not boundary-clocked)"); ws.cell(r[0], 3, p.get("n_dormant", 0)); r[0] += 1
    gms = p.get("grandmasters") or []
    ws.cell(r[0], 1, "Grandmaster(s)"); ws.cell(r[0], 3, ", ".join(gms) if gms else "none observed"); r[0] += 2

    section(f"Group census ({len(m.get('groups') or [])})")
    header(["Group", "L2 MAC", "Category", "On-air", "Source", "Name"])
    for g in (m.get("groups") or []):
        vals = [g.get("group"), g.get("mac"), g.get("category"), "yes" if g.get("on_air") else "",
                g.get("source"), g.get("name")]
        for i, v in enumerate(vals, 1):
            ws.cell(r[0], i, v).font = DAT
        r[0] += 1

    for i, w in enumerate([20, 18, 16, 8, 16, 26], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"
    logger.info(f"  [OK] '{MULTICAST_INTEL_SHEET_NAME}' sheet: {s.get('n_groups', 0)} group(s), "
                f"{s.get('n_mac_clashes', 0)} MAC clash(es), {s.get('n_querier_gaps', 0)} querier gap(s)")


COLLECTION_COMPLETENESS_SHEET_NAME = "Collection Completeness"   # NEW-V3.23.109

def write_collection_completeness_sheet(wb, cc: dict) -> None:
    """Write the 'Collection Completeness' sheet from compute_collection_completeness(): the
    pre-assessment blind-spot list -- inventory devices that were not collected / only partially
    collected, and which essential commands are missing. Lead row is the summary."""
    ws = wb.create_sheet(COLLECTION_COMPLETENESS_SHEET_NAME)
    s = (cc or {}).get("summary") or {}
    ws.cell(1, 1, "Inventory").font = Font(bold=True)
    ws.cell(1, 2, s.get("inventory", 0))
    ws.cell(1, 3, f"complete {s.get('complete', 0)} · partial {s.get('partial', 0)} · "
                  f"NOT collected {s.get('not_collected', 0)} — these are assessment blind spots, "
                  "re-collect before relying on the report").font = Font(italic=True)
    headers = ["Status", "Device", "Data quality", "Missing essential commands"]
    for col, h in enumerate(headers, 1):
        c = ws.cell(3, col, h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="434343")
        c.alignment = Alignment(horizontal="center")
    fill = {"not collected": "F4CCCC", "partial": "FCE5CD"}
    rows = (cc or {}).get("devices") or []
    if not rows:
        ws.cell(4, 1, "All inventory devices fully collected — no blind spots.")
    for r, d in enumerate(rows, 4):
        vals = [d.get("status", ""), d.get("host", ""), f"{d.get('data_quality', 0)}%",
                ", ".join(d.get("missing", []))]
        for col, v in enumerate(vals, 1):
            c = ws.cell(r, col, v)
            if col == 1 and d.get("status") in fill:
                c.fill = PatternFill("solid", fgColor=fill[d["status"]])
                c.font = Font(bold=True)
    for i, w in enumerate([15, 34, 13, 46], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A4"
    logger.info(f"  [OK] '{COLLECTION_COMPLETENESS_SHEET_NAME}' sheet: {len(rows)} blind spot(s) "
                f"of {s.get('inventory', 0)} inventory device(s)")


HEALTH_SCORES_SHEET_NAME = "Health Scores"
MIGRATION_READINESS_SHEET_NAME = "Migration Readiness"
SCORE_SENSITIVITY_SHEET_NAME = "Score Sensitivity"   # NEW-V3.23.5
_READY_FILL = {"READY": "36E08A", "CAUTION": "FFE566", "NOT READY": "FF5775"}
_STATUS_FILL = {"pass": "36E08A", "warn": "FFE566", "fail": "FF5775"}

def write_health_scores_sheet(wb, records: List[dict]) -> None:
    ws = wb.create_sheet(HEALTH_SCORES_SHEET_NAME)
    headers = ["Switch", "Score", "Band", "Criticality", "Data Quality", "Top Deductions"]
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
        role = rec.get("role"); crit = rec.get("criticality")   # asset-criticality weighting (transparency)
        ws.cell(r, 4, f"{role} x{crit:g}" if role else "")
        dq = rec.get("data_quality")
        ws.cell(r, 5, "" if dq is None else f"{int(round(dq * 100))}%")
        ws.cell(r, 6, "; ".join(rec["deductions"]) if rec["deductions"] else "healthy")
    for i, w in enumerate([16, 8, 11, 15, 13, 80], 1):
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


SCORE_CALIBRATION_SHEET_NAME = "Score Calibration"   # NEW-V3.23.47

def write_calibration_sheet(wb, report: dict) -> None:
    """Write the 'Score Calibration' sheet from compute_calibration_report() -- a
    fleet-level key/value diagnostic (band distribution, score spread, discrimination,
    and a quantile re-banding suggestion when the bands don't discriminate)."""
    ws = wb.create_sheet(SCORE_CALIBRATION_SHEET_NAME)
    for col, h in enumerate(["Metric", "Value"], 1):
        c = ws.cell(1, col, h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="434343")
        c.alignment = Alignment(horizontal="center")
    n = report.get("n", 0)
    rows: List[Tuple[str, object]] = [("Switches scored", n)]
    if n:
        st = report.get("score_stats", {})
        rows += [
            ("Score range", f"{st.get('min', '')}-{st.get('max', '')}"),
            ("Median / Mean", f"{st.get('median', '')} / {st.get('mean', '')}"),
            ("Std dev", st.get("stdev", "")),
            ("p25 / p75", f"{st.get('p25', '')} / {st.get('p75', '')}"),
            ("Band distribution", "  ".join(f"{d['band']}:{d['count']} ({d['pct']}%)"
                                            for d in report.get("band_distribution", []))),
            ("Modal band", f"{report.get('modal_band', '')} ({report.get('modal_pct', 0)}%)"),
            ("Discrimination", f"{report.get('discrimination', '')} ({report.get('discrimination_quality', '')})"),
        ]
        if report.get("suggested_bands"):
            rows.append(("Suggested re-banding (relative)",
                         "  ".join(f"{s['band']}>={s['threshold']}" for s in report["suggested_bands"])))
    rows.append(("Summary", report.get("note", "")))
    for r, (k, v) in enumerate(rows, 2):
        ws.cell(r, 1, k).font = Font(bold=True)
        ws.cell(r, 2, v)
    for i, w in enumerate([32, 80], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"
    logger.info(f"  [OK] '{SCORE_CALIBRATION_SHEET_NAME}' sheet: {n} switch(es), "
                f"discrimination {report.get('discrimination_quality', '?')}")


NAT_INVENTORY_SHEET_NAME = "NAT Inventory"   # NEW-V3.23.50

def write_nat_sheet(wb, all_nat: dict) -> None:
    """Write the 'NAT Inventory' sheet from {host: parse_nat()} -- every static / dynamic NAT rule,
    pool, and inside/outside interface role, so the migration can recreate them on the new platform."""
    ws = wb.create_sheet(NAT_INVENTORY_SHEET_NAME)
    for col, h in enumerate(["Switch", "Type", "Detail"], 1):
        c = ws.cell(1, col, h); c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="434343"); c.alignment = Alignment(horizontal="center")
    r = 2; total = 0
    for host in sorted(all_nat):
        nat = all_nat[host] or {}
        for s in nat.get("static", []):
            pp = f" {s['proto']}" if s.get("proto") else ""
            lp = f":{s['local_port']}" if s.get("local_port") else ""
            gp = f":{s['global_port']}" if s.get("global_port") else ""
            ws.cell(r, 1, host); ws.cell(r, 2, f"static{pp}")
            ws.cell(r, 3, f"local {s.get('local', '')}{lp}  <->  global {s.get('global', '')}{gp}"); r += 1; total += 1
        for d in nat.get("dynamic", []):
            ws.cell(r, 1, host); ws.cell(r, 2, "dynamic" + (" (PAT)" if d.get("overload") else ""))
            ws.cell(r, 3, f"list {d.get('acl', '')} via {d.get('kind', '')} {d.get('via', '')}"); r += 1; total += 1
        for name, p in (nat.get("pools") or {}).items():
            ws.cell(r, 1, host); ws.cell(r, 2, "pool")
            ws.cell(r, 3, f"{name}: {p.get('start', '')} - {p.get('end', '')}"); r += 1; total += 1
        if nat.get("inside") or nat.get("outside"):
            ws.cell(r, 1, host); ws.cell(r, 2, "interfaces")
            ws.cell(r, 3, f"inside: {', '.join(nat.get('inside', [])) or '-'}  |  "
                          f"outside: {', '.join(nat.get('outside', [])) or '-'}"); r += 1
    for i, w in enumerate([16, 16, 90], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"
    nhosts = len([h for h in all_nat if all_nat[h]])
    logger.info(f"  [OK] '{NAT_INVENTORY_SHEET_NAME}' sheet: {total} NAT rule(s) across {nhosts} switch(es)")


CONFIG_COMPLIANCE_SHEET_NAME = "Config Compliance"   # CIS-aligned config-hardening checks (NEW-V3.23.59); distinct from the operational 'Security Posture' sheet

def write_security_sheet(wb, all_security: dict) -> None:
    """Write the 'Config Compliance' sheet from {host: parse_security()} -- one row per CIS-aligned
    config-hardening check (pass / fail / na) with severity + remediation, so the migration can
    remediate (or consciously carry) config technical debt. Secret values were redacted by the parser."""
    ws = wb.create_sheet(CONFIG_COMPLIANCE_SHEET_NAME)
    for col, h in enumerate(["Switch", "Severity", "Status", "Check", "Finding", "CIS / Remediation"], 1):
        c = ws.cell(1, col, h); c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="434343"); c.alignment = Alignment(horizontal="center")
    sev_fill = {"high": "F4CCCC", "medium": "FCE5CD", "low": "FFF2CC"}
    r = 2; total = 0; nfail = 0
    for host in sorted(all_security):
        sec = all_security[host] or {}
        for f in sec.get("findings", []):
            ws.cell(r, 1, host)
            ws.cell(r, 2, (f.get("severity") or "").upper() if f.get("status") == "fail" else "-")
            ws.cell(r, 3, (f.get("status") or "").upper())
            ws.cell(r, 4, f.get("title", ""))
            ws.cell(r, 5, f.get("detail", ""))
            ws.cell(r, 6, f"{f.get('cis_ref', '')} - {f.get('remediation', '')}")
            if f.get("status") == "fail":
                fill = PatternFill("solid", fgColor=sev_fill.get(f.get("severity"), "F4CCCC"))
                for col in range(1, 7):
                    ws.cell(r, col).fill = fill
                nfail += 1
            r += 1; total += 1
    for i, w in enumerate([14, 10, 8, 26, 72, 60], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"
    nhosts = len([h for h in all_security if all_security[h]])
    logger.info(f"  [OK] '{CONFIG_COMPLIANCE_SHEET_NAME}' sheet: {nfail} fail / {total} check(s) "
                f"across {nhosts} switch(es)")


CONFIG_HYGIENE_SHEET_NAME = "Config Hygiene"   # Batfish-style undefined refs + unused structures (NEW-V3.23.61)

def write_config_hygiene_sheet(wb, all_hygiene: dict) -> None:
    """Write the 'Config Hygiene' sheet from {host: parse_config_hygiene()} -- undefined references
    (a referenced-but-undefined ACL/route-map/object-group/prefix-list silently does nothing: a real
    migration-breaker) and unused structures (defined-but-never-referenced cruft), so each can be fixed
    or dropped before cutover."""
    ws = wb.create_sheet(CONFIG_HYGIENE_SHEET_NAME)
    for col, h in enumerate(["Switch", "Issue", "Kind", "Name", "Where / note"], 1):
        c = ws.cell(1, col, h); c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="434343"); c.alignment = Alignment(horizontal="center")
    undef_fill = PatternFill("solid", fgColor="F4CCCC"); unused_fill = PatternFill("solid", fgColor="FFF2CC")
    r = 2; nundef = 0; nunused = 0
    for host in sorted(all_hygiene):
        hyg = all_hygiene[host] or {}
        for u in hyg.get("undefined", []):
            ws.cell(r, 1, host); ws.cell(r, 2, "undefined reference"); ws.cell(r, 3, u.get("kind", ""))
            ws.cell(r, 4, u.get("name", "")); ws.cell(r, 5, u.get("context", ""))
            for col in range(1, 6): ws.cell(r, col).fill = undef_fill
            r += 1; nundef += 1
        for u in hyg.get("unused", []):
            ws.cell(r, 1, host); ws.cell(r, 2, "unused (no reference found)"); ws.cell(r, 3, u.get("kind", ""))
            ws.cell(r, 4, u.get("name", "")); ws.cell(r, 5, "defined but never referenced in the running-config")
            for col in range(1, 6): ws.cell(r, col).fill = unused_fill
            r += 1; nunused += 1
    for i, w in enumerate([14, 26, 16, 26, 64], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"
    nhosts = len([h for h in all_hygiene if all_hygiene[h]])
    logger.info(f"  [OK] '{CONFIG_HYGIENE_SHEET_NAME}' sheet: {nundef} undefined ref(s), "
                f"{nunused} unused across {nhosts} switch(es)")


STP_ROOTS_SHEET_NAME = "STP Root Bridges"   # root-bridge placement analysis (NEW-V3.23.62)

def write_stp_roots_sheet(wb, all_stp_roots: dict, all_interfaces: dict) -> None:
    """Write the 'STP Root Bridges' sheet: per VLAN, which switch is the spanning-tree root, its
    bridge priority, whether that root is ACCIDENTAL (default priority -> elected on a MAC tiebreak,
    not by design) and whether it ALIGNS with the VLAN's L3 gateway (root != gateway -> the path to
    the default gateway hairpins through the root). Migration-relevant L2 design hygiene."""
    from cisco_toolkit.analyze import stp_root_findings
    f = stp_root_findings(all_stp_roots, all_interfaces)
    acc = {(x["vlan"], x["host"]) for x in f["accidental"]}
    mis = {x["vlan"]: x["gateways"] for x in f["misaligned"]}
    ws = wb.create_sheet(STP_ROOTS_SHEET_NAME)
    for col, h in enumerate(["VLAN", "Root switch", "Root priority", "Accidental root?",
                             "VLAN gateway(s)", "Aligned?"], 1):
        c = ws.cell(1, col, h); c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="434343"); c.alignment = Alignment(horizontal="center")
    root_of: dict = {}
    for host in sorted(all_stp_roots or {}):
        for vlan, r in (all_stp_roots[host] or {}).items():
            if r.get("is_root"):
                root_of.setdefault(vlan, (host, r.get("root_priority")))
    warn = PatternFill("solid", fgColor="FCE5CD")
    r = 2; nrows = 0
    for vlan in sorted(root_of, key=lambda v: int(v)):
        host, prio = root_of[vlan]
        is_acc = (vlan, host) in acc
        gws = mis.get(vlan)
        ws.cell(r, 1, vlan); ws.cell(r, 2, host)
        ws.cell(r, 3, prio if prio is not None else "")
        ws.cell(r, 4, "yes (default priority)" if is_acc else "no")
        ws.cell(r, 5, ", ".join(gws) if gws else "(root hosts gateway / none collected)")
        ws.cell(r, 6, "no - root != gateway" if gws else "yes")
        if is_acc or gws:
            for col in range(1, 7):
                ws.cell(r, col).fill = warn
        r += 1; nrows += 1
    for i, w in enumerate([8, 16, 14, 20, 28, 22], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"
    logger.info(f"  [OK] '{STP_ROOTS_SHEET_NAME}' sheet: {nrows} rooted VLAN(s), "
                f"{len(f['accidental'])} accidental, {len(f['misaligned'])} misaligned")


PUNCHLIST_SHEET_NAME = "Migration Punch-List"   # consolidated severity-ranked roll-up (NEW-V3.23.63)

def write_punchlist_sheet(wb, punchlist: list) -> None:
    """Write the 'Migration Punch-List' sheet: the consolidated, severity-ranked, per-device,
    per-wave roll-up of every actionable finding (cross-layer SPOFs, security, config hygiene,
    L1/L3, protocol, STP, device health) with remediation -- the executive 'fix-this-first, in
    this order' one-pager. Rows are colour-banded by severity (Critical -> Low)."""
    ws = wb.create_sheet(PUNCHLIST_SHEET_NAME)
    headers = ["#", "Severity", "Category", "Device(s)", "Wave", "Issue", "Detail", "Remediation"]
    for col, h in enumerate(headers, 1):
        c = ws.cell(1, col, h); c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="434343"); c.alignment = Alignment(horizontal="center")
    sev_fill = {"Critical": "F4CCCC", "High": "FCE5CD", "Medium": "FFF2CC", "Low": "EFEFEF"}
    r = 2
    for it in (punchlist or []):
        ws.cell(r, 1, it.get("priority", r - 1))
        ws.cell(r, 2, it.get("severity", ""))
        ws.cell(r, 3, it.get("category", ""))
        ws.cell(r, 4, ", ".join(it.get("devices", [])))
        ws.cell(r, 5, it.get("wave", ""))
        ws.cell(r, 6, it.get("title", ""))
        ws.cell(r, 7, it.get("detail", ""))
        ws.cell(r, 8, it.get("remediation", ""))
        fill = PatternFill("solid", fgColor=sev_fill.get(it.get("severity"), "FFFFFF"))
        for col in range(1, 9):
            ws.cell(r, col).fill = fill
        r += 1
    for i, w in enumerate([5, 10, 14, 22, 16, 34, 60, 50], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"
    ncrit = sum(1 for it in (punchlist or []) if it.get("severity") == "Critical")
    logger.info(f"  [OK] '{PUNCHLIST_SHEET_NAME}' sheet: {len(punchlist or [])} item(s), {ncrit} critical")


REMEDIATION_PLAN_SHEET_NAME = "Remediation Plan"   # NEW-V3.23.116 (assess->act: generated config snippets)

def write_remediation_plan_sheet(wb, rp: dict) -> None:
    """Write 'Remediation Plan' from compute_remediation_plan(): per-device, platform-tagged Cisco config
    snippets generated FOR REVIEW from the structured findings. Row 1 carries the review banner."""
    if REMEDIATION_PLAN_SHEET_NAME in wb.sheetnames:
        del wb[REMEDIATION_PLAN_SHEET_NAME]
    ws = wb.create_sheet(REMEDIATION_PLAN_SHEET_NAME)
    p = rp or {}
    items = p.get("items") or []
    s = p.get("summary") or {}
    b = ws.cell(1, 1, "⚠ " + (p.get("banner") or "GENERATED FOR REVIEW — validate before applying."))
    b.font = Font(bold=True, color="9C0006", size=10)
    b.alignment = Alignment(horizontal="left", wrap_text=True)
    ws.cell(2, 1, f"{s.get('n_items', 0)} item(s) across {s.get('n_devices', 0)} device(s) · "
                  f"{s.get('n_high', 0)} High/Critical · by category: "
                  + ", ".join(f"{k} {v}" for k, v in (s.get("by_category") or {}).items())).font = Font(size=10)
    hdr_row = 4
    cols = ["#", "Device", "Platform", "Category", "Severity", "Issue",
            "Config (review before applying)", "Verify", "Caution"]
    for i, h in enumerate(cols, 1):
        c = ws.cell(hdr_row, i, h); c.font = Font(bold=True, color="FFFFFF", size=10)
        c.fill = PatternFill("solid", fgColor="434343")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.freeze_panes = ws.cell(hdr_row + 1, 1)
    SEVFILL = {"Critical": "F4CCCC", "High": "FCE4D6", "Medium": "FFF2CC", "Low": "D9EAD3", "Info": "EFEFEF"}
    DAT = Font(name="Calibri", size=10); MONO = Font(name="Consolas", size=9)
    r = hdr_row + 1
    for n, it in enumerate(items, 1):
        vals = [n, it.get("device"), it.get("platform"), it.get("category"), it.get("severity"),
                it.get("title"), "\n".join(it.get("commands") or []), it.get("verify"), it.get("caution")]
        for col, v in enumerate(vals, 1):
            c = ws.cell(r, col, v); c.font = (MONO if col == 7 else DAT)
            c.alignment = Alignment(horizontal="center" if col in (1, 3, 5) else "left",
                                    vertical="top", wrap_text=col in (6, 7, 9))
            if col == 5:
                c.fill = PatternFill("solid", fgColor=SEVFILL.get(v, "FFFFFF"))
        r += 1
    for i, w in enumerate([5, 28, 9, 15, 10, 34, 54, 28, 40], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    logger.info(f"  [OK] '{REMEDIATION_PLAN_SHEET_NAME}' sheet: {len(items)} item(s), "
                f"{s.get('n_devices', 0)} device(s)")


VALIDATION_PLAN_SHEET_NAME = "Cutover Validation"   # NEW-V3.23.143 (per-wave post-cutover verification checklist)

def write_validation_plan_sheet(wb, vp: dict) -> None:
    """Write 'Cutover Validation' from compute_validation_plan(): the per-wave checks to run AFTER each
    cutover, each with the command + the expected good result captured from the pre-cutover state. Row 1
    carries the how-to-use banner."""
    if VALIDATION_PLAN_SHEET_NAME in wb.sheetnames:
        del wb[VALIDATION_PLAN_SHEET_NAME]
    ws = wb.create_sheet(VALIDATION_PLAN_SHEET_NAME)
    p = vp or {}
    items = p.get("items") or []
    s = p.get("summary") or {}
    b = ws.cell(1, 1, "✓ " + (p.get("banner") or "Run after each wave's cutover to confirm it succeeded."))
    b.font = Font(bold=True, color="1F6E43", size=10)
    b.alignment = Alignment(horizontal="left", wrap_text=True)
    ws.cell(2, 1, f"{s.get('n_items', 0)} check(s) across {s.get('n_waves', 0)} wave(s) · "
                  f"{s.get('n_high', 0)} High/Critical · by category: "
                  + ", ".join(f"{k} {v}" for k, v in (s.get("by_category") or {}).items())).font = Font(size=10)
    hdr_row = 4
    cols = ["#", "Wave", "Device", "Platform", "Category", "Severity", "Check",
            "Command", "Expect (good result)", "Why it matters"]
    for i, h in enumerate(cols, 1):
        c = ws.cell(hdr_row, i, h); c.font = Font(bold=True, color="FFFFFF", size=10)
        c.fill = PatternFill("solid", fgColor="1F6E43")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.freeze_panes = ws.cell(hdr_row + 1, 1)
    SEVFILL = {"Critical": "F4CCCC", "High": "FCE4D6", "Medium": "FFF2CC", "Low": "D9EAD3", "Info": "EFEFEF"}
    DAT = Font(name="Calibri", size=10); MONO = Font(name="Consolas", size=9)
    r = hdr_row + 1
    for n, it in enumerate(items, 1):
        vals = [n, it.get("wave"), it.get("device"), it.get("platform"), it.get("category"),
                it.get("severity"), it.get("check"), it.get("command"), it.get("expect"), it.get("why")]
        for col, v in enumerate(vals, 1):
            c = ws.cell(r, col, v); c.font = (MONO if col in (8, 9) else DAT)
            c.alignment = Alignment(horizontal="center" if col in (1, 4, 6) else "left",
                                    vertical="top", wrap_text=col in (7, 8, 9, 10))
            if col == 6:
                c.fill = PatternFill("solid", fgColor=SEVFILL.get(v, "FFFFFF"))
        r += 1
    for i, w in enumerate([5, 12, 22, 9, 14, 10, 40, 34, 40, 50], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    logger.info(f"  [OK] '{VALIDATION_PLAN_SHEET_NAME}' sheet: {len(items)} check(s), "
                f"{s.get('n_waves', 0)} wave(s)")


GOLDEN_DRIFT_SHEET_NAME = "Golden-Config Drift"   # NEW-V3.23.146 (per-device config drift vs a baseline)

def write_golden_drift_sheet(wb, gd: dict) -> None:
    """Write 'Golden-Config Drift' from compute_golden_drift(): per-device compliance vs the baseline
    (a supplied golden-config file, else the auto-derived majority baseline) + the missing required
    directives. Row 1 states which baseline was used."""
    if GOLDEN_DRIFT_SHEET_NAME in wb.sheetnames:
        del wb[GOLDEN_DRIFT_SHEET_NAME]
    ws = wb.create_sheet(GOLDEN_DRIFT_SHEET_NAME)
    p = gd or {}
    pdev = p.get("per_device") or []
    s = p.get("summary") or {}
    mode = s.get("mode", p.get("mode", "majority"))
    src = ("a supplied golden-config file" if mode == "golden-file"
           else "the fleet's de-facto MAJORITY baseline (auto-derived)")
    b = ws.cell(1, 1, f"Baseline: {src} — {s.get('n_baseline', 0)} required directive(s). "
                      "A device is flagged when it is MISSING one.")
    b.font = Font(bold=True, color="7030A0", size=10)
    b.alignment = Alignment(horizontal="left", wrap_text=True)
    ws.cell(2, 1, f"{s.get('n_devices', 0)} device(s) · {s.get('n_drifting', 0)} drifting · "
                  f"avg compliance {s.get('avg_compliance_pct', 0)}%").font = Font(size=10)
    hdr_row = 4
    cols = ["Device", "Compliance %", "Missing", "Missing required directives"]
    for i, h in enumerate(cols, 1):
        c = ws.cell(hdr_row, i, h); c.font = Font(bold=True, color="FFFFFF", size=10)
        c.fill = PatternFill("solid", fgColor="7030A0")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.freeze_panes = ws.cell(hdr_row + 1, 1)
    DAT = Font(name="Calibri", size=10); MONO = Font(name="Consolas", size=9)
    r = hdr_row + 1
    for d in pdev:
        pct = d.get("compliance_pct", 0)
        fill = "C6EFCE" if pct >= 100 else ("FFEB9C" if pct >= 80 else "FFC7CE")
        vals = [d.get("host"), pct, d.get("n_missing", 0), "\n".join(d.get("missing") or [])]
        for col, v in enumerate(vals, 1):
            c = ws.cell(r, col, v); c.font = (MONO if col == 4 else DAT)
            c.alignment = Alignment(horizontal="center" if col in (2, 3) else "left",
                                    vertical="top", wrap_text=col == 4)
            if col == 2:
                c.fill = PatternFill("solid", fgColor=fill)
        r += 1
    if not pdev:
        ws.cell(hdr_row + 1, 1, "No running-configs available to compare.").font = DAT
    for i, w in enumerate([24, 14, 9, 80], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    logger.info(f"  [OK] '{GOLDEN_DRIFT_SHEET_NAME}' sheet: {len(pdev)} device(s), "
                f"{s.get('n_drifting', 0)} drifting ({mode})")


# Shared severity palette for the V3.23.164-.167 axis sheets (V3.23.171). The four writers each
# carried a private copy whose High had drifted to F4CCCC -- the colour every ESTABLISHED writer
# (punch-list, remediation, validation, exec summary) reserves for Critical. One constant, and
# High renders FCE4D6 here exactly as it does everywhere else in the workbook.
_AXIS_SEV_FILL = {"Critical": "F4CCCC", "High": "FCE4D6", "Medium": "FFF2CC", "Low": "D9EAD3"}

SYSLOG_SHEET_NAME = "Syslog Intelligence"   # NEW-V3.23.164 (NOS-style operational log analysis)

def write_syslog_intelligence_sheet(wb, si: dict) -> None:
    """Write 'Syslog Intelligence' from compute_syslog_intelligence(): the operational
    detections (MAC flap / err-disable / link flap / environmental / ...) with the
    senior-engineer doctrine per finding, then the per-device log profile. Devices whose
    'show logging' was not collected are declared, never scored."""
    if SYSLOG_SHEET_NAME in wb.sheetnames:
        del wb[SYSLOG_SHEET_NAME]
    ws = wb.create_sheet(SYSLOG_SHEET_NAME)
    p = si or {}
    dets = p.get("detections") or []
    pdev = p.get("per_device") or []
    s = p.get("summary") or {}
    b = ws.cell(1, 1, f"Operational log analysis: {s.get('total_events', 0)} event(s) parsed on "
                      f"{s.get('n_collected', 0)} of {s.get('n_devices', 0)} device(s) -> "
                      f"{s.get('n_detections', 0)} detection(s). The log buffer is a bounded recent "
                      "window, so counts are floors; absence of logs is never scored as absence of problems.")
    b.font = Font(bold=True, color="7030A0", size=10)
    b.alignment = Alignment(horizontal="left", wrap_text=True)
    ws.cell(2, 1, f"{s.get('crit_0_2', 0)} critical (sev 0-2) · {s.get('err_3', 0)} error (sev 3) · "
                  f"{s.get('n_not_collected', 0)} device(s) without 'show logging' output").font = Font(size=10)
    SEVFILL = _AXIS_SEV_FILL
    HDRF = Font(bold=True, color="FFFFFF", size=10)
    DAT = Font(name="Calibri", size=10); MONO = Font(name="Consolas", size=9)

    hdr_row = 4
    cols = ["Device", "Finding", "Severity", "Count", "Detail", "Evidence (first event)", "Recommendation"]
    for i, h in enumerate(cols, 1):
        c = ws.cell(hdr_row, i, h); c.font = HDRF
        c.fill = PatternFill("solid", fgColor="7030A0")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.freeze_panes = ws.cell(hdr_row + 1, 1)
    r = hdr_row + 1
    for d in dets:
        vals = [d.get("host"), d.get("label"), d.get("severity"), d.get("count", 0),
                d.get("detail"), d.get("example"), d.get("recommendation")]
        for col, v in enumerate(vals, 1):
            c = ws.cell(r, col, v); c.font = (MONO if col == 6 else DAT)
            c.alignment = Alignment(horizontal="center" if col in (3, 4) else "left",
                                    vertical="top", wrap_text=col in (5, 6, 7))
            if col == 3 and v in SEVFILL:
                c.fill = PatternFill("solid", fgColor=SEVFILL[v])
        r += 1
    if not dets:
        ws.cell(r, 1, "No operational detections in the collected logs." if s.get("n_collected")
                else "No 'show logging' output collected -- log evidence unavailable.").font = DAT
        r += 1

    r += 2
    ws.cell(r, 1, "Per-device log profile").font = Font(bold=True, color="7030A0", size=10)
    r += 1
    cols2 = ["Device", "Collected", "Events", "Crit (0-2)", "Err (3)", "Warn (4)",
             "Info (5-7)", "Config changes", "Top messages"]
    for i, h in enumerate(cols2, 1):
        c = ws.cell(r, i, h); c.font = HDRF
        c.fill = PatternFill("solid", fgColor="7030A0")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    r += 1
    for d in pdev:
        bs = d.get("by_severity") or {}
        top = ", ".join(f"{m['msg']} ({m['count']}x)" for m in (d.get("top_messages") or []))
        vals = [d.get("host"), "yes" if d.get("collected") else "NOT COLLECTED",
                d.get("events", 0), bs.get("crit_0_2", 0), bs.get("err_3", 0),
                bs.get("warn_4", 0), bs.get("info_5_7", 0), d.get("config_changes", 0), top]
        for col, v in enumerate(vals, 1):
            c = ws.cell(r, col, v); c.font = (MONO if col == 9 else DAT)
            c.alignment = Alignment(horizontal="center" if col in (2, 3, 4, 5, 6, 7, 8) else "left",
                                    vertical="top", wrap_text=col == 9)
            if col == 2 and not d.get("collected"):
                c.fill = PatternFill("solid", fgColor="EFEFEF")
            if col == 4 and bs.get("crit_0_2", 0):
                c.fill = PatternFill("solid", fgColor="F4CCCC")
        r += 1
    # shared column widths: table 1 (A-G) needs wide Detail/Evidence/Recommendation;
    # table 2 (A-I) tolerates wide numeric columns.
    for i, w in enumerate([22, 24, 11, 9, 36, 42, 46, 13, 42], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    logger.info(f"  [OK] '{SYSLOG_SHEET_NAME}' sheet: {len(dets)} detection(s) on "
                f"{s.get('n_collected', 0)}/{s.get('n_devices', 0)} device(s) with logs")


QOS_AUDIT_SHEET_NAME = "QoS Audit"   # NEW-V3.23.165 (configured QoS posture + doctrine findings)

def write_qos_audit_sheet(wb, qa: dict) -> None:
    """Write 'QoS Audit' from compute_qos_audit(): the doctrine findings (voice edge
    without QoS, missing trust boundary, inert/dangling policy, fleet consistency),
    then the per-device configured posture. Devices without a full running-config
    capture are declared not assessable, never scored."""
    if QOS_AUDIT_SHEET_NAME in wb.sheetnames:
        del wb[QOS_AUDIT_SHEET_NAME]
    ws = wb.create_sheet(QOS_AUDIT_SHEET_NAME)
    p = qa or {}
    finds = p.get("findings") or []
    pdev = p.get("per_device") or []
    s = p.get("summary") or {}
    modes = s.get("modes") or {}
    mode_txt = ", ".join(f"{k}: {v}" for k, v in modes.items()) or "none assessable"
    b = ws.cell(1, 1, f"Configured QoS posture from the captured running-configs of "
                      f"{s.get('n_assessable', 0)} of {s.get('n_devices', 0)} device(s) -> "
                      f"{s.get('n_findings', 0)} finding(s). Config evidence only (no live queue "
                      "counters); a device without a full capture is declared not assessable.")
    b.font = Font(bold=True, color="7030A0", size=10)
    b.alignment = Alignment(horizontal="left", wrap_text=True)
    ws.cell(2, 1, f"Posture by mode — {mode_txt} · {s.get('n_voice_ports', 0)} voice-VLAN port(s) "
                  f"· {s.get('n_not_assessable', 0)} not assessable").font = Font(size=10)
    SEVFILL = _AXIS_SEV_FILL
    HDRF = Font(bold=True, color="FFFFFF", size=10)
    DAT = Font(name="Calibri", size=10)

    hdr_row = 4
    cols = ["Device", "Finding", "Severity", "Detail", "Recommendation"]
    for i, h in enumerate(cols, 1):
        c = ws.cell(hdr_row, i, h); c.font = HDRF
        c.fill = PatternFill("solid", fgColor="7030A0")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.freeze_panes = ws.cell(hdr_row + 1, 1)
    r = hdr_row + 1
    for f in finds:
        vals = [f.get("host"), f.get("label"), f.get("severity"), f.get("detail"),
                f.get("recommendation")]
        for col, v in enumerate(vals, 1):
            c = ws.cell(r, col, v); c.font = DAT
            c.alignment = Alignment(horizontal="center" if col == 3 else "left",
                                    vertical="top", wrap_text=col in (4, 5))
            if col == 3 and v in SEVFILL:
                c.fill = PatternFill("solid", fgColor=SEVFILL[v])
        r += 1
    if not finds:
        ws.cell(r, 1, "No QoS findings on the assessable devices." if s.get("n_assessable")
                else "No full running-config captures -- QoS posture not assessable.").font = DAT
        r += 1

    r += 2
    ws.cell(r, 1, "Per-device configured posture").font = Font(bold=True, color="7030A0", size=10)
    r += 1
    cols2 = ["Device", "Assessable", "Mode", "Class-maps", "Policy-maps", "Attached if",
             "Trust if", "Auto-QoS if", "Voice if", "Posture"]
    for i, h in enumerate(cols2, 1):
        c = ws.cell(r, i, h); c.font = HDRF
        c.fill = PatternFill("solid", fgColor="7030A0")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    r += 1
    for d in pdev:
        vals = [d.get("host"), "yes" if d.get("assessable") else "NOT ASSESSABLE",
                d.get("mode"), d.get("n_class_maps", 0), d.get("n_policy_maps", 0),
                d.get("n_attached_if", 0), d.get("n_trust_if", 0), d.get("n_auto_if", 0),
                d.get("n_voice_if", 0), d.get("posture")]
        for col, v in enumerate(vals, 1):
            c = ws.cell(r, col, v); c.font = DAT
            c.alignment = Alignment(horizontal="center" if col in (2, 4, 5, 6, 7, 8, 9) else "left",
                                    vertical="top", wrap_text=col == 10)
            if col == 2 and not d.get("assessable"):
                c.fill = PatternFill("solid", fgColor="EFEFEF")
        r += 1
    # shared widths: table 1 (A-E) needs wide Detail/Recommendation; table 2 spreads A-J.
    for i, w in enumerate([22, 30, 11, 48, 48, 12, 10, 12, 10, 46], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    logger.info(f"  [OK] '{QOS_AUDIT_SHEET_NAME}' sheet: {len(finds)} finding(s), "
                f"{s.get('n_assessable', 0)}/{s.get('n_devices', 0)} device(s) assessable")


SOFTWARE_RISK_SHEET_NAME = "Software Risk"   # NEW-V3.23.166 (advisory-surface screening + train lifecycle)

def write_software_risk_sheet(wb, sr: dict) -> None:
    """Write 'Software Risk' from compute_software_risk(): the attack-surface screening
    findings (each joined to its landmark advisory) and the per-device software-train
    lifecycle bands. Screening, not a vulnerability scan -- the banner says so."""
    if SOFTWARE_RISK_SHEET_NAME in wb.sheetnames:
        del wb[SOFTWARE_RISK_SHEET_NAME]
    ws = wb.create_sheet(SOFTWARE_RISK_SHEET_NAME)
    p = sr or {}
    finds = p.get("findings") or []
    pdev = p.get("per_device") or []
    s = p.get("summary") or {}
    bands = s.get("train_bands") or {}
    band_txt = ", ".join(f"{k}: {v}" for k, v in bands.items()) or "—"
    b = ws.cell(1, 1, f"Software risk SCREENING: {s.get('n_findings', 0)} exposed surface(s) on "
                      f"{s.get('n_config_assessable', 0)} of {s.get('n_devices', 0)} config-assessable "
                      "device(s), joined to landmark public advisories. This is configuration-evidence "
                      "screening, NOT a vulnerability scan — validate every running release with the "
                      "Cisco PSIRT Software Checker.")
    b.font = Font(bold=True, color="7030A0", size=10)
    b.alignment = Alignment(horizontal="left", wrap_text=True)
    ws.cell(2, 1, f"Software trains — {band_txt} · {s.get('n_version_known', 0)} of "
                  f"{s.get('n_devices', 0)} version(s) captured").font = Font(size=10)
    SEVFILL = _AXIS_SEV_FILL
    BANDFILL = {"Replace/Upgrade": "F4CCCC", "Verify EoL": "FFF2CC",
                "Current-era": "C6EFCE", "Unknown": "EFEFEF"}
    HDRF = Font(bold=True, color="FFFFFF", size=10)
    DAT = Font(name="Calibri", size=10); MONO = Font(name="Consolas", size=9)

    hdr_row = 4
    cols = ["Device", "Exposed surface", "Severity", "Evidence", "Landmark advisory",
            "Why it matters", "Recommendation"]
    for i, h in enumerate(cols, 1):
        c = ws.cell(hdr_row, i, h); c.font = HDRF
        c.fill = PatternFill("solid", fgColor="7030A0")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.freeze_panes = ws.cell(hdr_row + 1, 1)
    r = hdr_row + 1
    for f in finds:
        advs = "\n".join(f"{a.get('id')} ({a.get('cve')}) — {a.get('note')}"
                         for a in (f.get("advisories") or [])) or "—"
        vals = [f.get("host"), f.get("surface"), f.get("severity"), f.get("evidence"),
                advs, f.get("why"), f.get("recommendation")]
        for col, v in enumerate(vals, 1):
            c = ws.cell(r, col, v); c.font = (MONO if col in (4, 5) else DAT)
            c.alignment = Alignment(horizontal="center" if col == 3 else "left",
                                    vertical="top", wrap_text=col in (4, 5, 6, 7))
            if col == 3 and v in SEVFILL:
                c.fill = PatternFill("solid", fgColor=SEVFILL[v])
        r += 1
    if not finds:
        ws.cell(r, 1, "No exposed advisory surfaces on the config-assessable devices."
                if s.get("n_config_assessable")
                else "No full running-config captures -- surface screening not assessable.").font = DAT
        r += 1

    r += 2
    ws.cell(r, 1, "Per-device software train (lifecycle screening)").font = Font(bold=True, color="7030A0", size=10)
    r += 1
    cols2 = ["Device", "Platform", "Version", "Train", "Band", "Guidance", "Config captured"]
    for i, h in enumerate(cols2, 1):
        c = ws.cell(r, i, h); c.font = HDRF
        c.fill = PatternFill("solid", fgColor="7030A0")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    r += 1
    for d in pdev:
        vals = [d.get("host"), d.get("platform"), d.get("sw_version"), d.get("train"),
                d.get("train_band"), d.get("train_note"),
                "yes" if d.get("config_assessable") else "NO"]
        for col, v in enumerate(vals, 1):
            c = ws.cell(r, col, v); c.font = (MONO if col == 3 else DAT)
            c.alignment = Alignment(horizontal="center" if col in (2, 5, 7) else "left",
                                    vertical="top", wrap_text=col == 6)
            if col == 5 and v in BANDFILL:
                c.fill = PatternFill("solid", fgColor=BANDFILL[v])
            if col == 7 and not d.get("config_assessable"):
                c.fill = PatternFill("solid", fgColor="EFEFEF")
        r += 1
    # shared widths: findings table (A-G) wide prose; train table tolerates them.
    for i, w in enumerate([22, 30, 11, 34, 44, 44, 46], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    logger.info(f"  [OK] '{SOFTWARE_RISK_SHEET_NAME}' sheet: {len(finds)} exposed surface(s), "
                f"bands {band_txt}")


PLATFORM_HEALTH_SHEET_NAME = "Platform Health"   # NEW-V3.23.167 (control-plane CPU/memory capacity)

def write_platform_health_sheet(wb, ph: dict) -> None:
    """Write 'Platform Health' from compute_platform_health(): control-plane capacity
    findings (hot/elevated CPU, low memory) and the per-device sample table. The banner
    states the single-sample honesty rule; not-collected devices are declared."""
    if PLATFORM_HEALTH_SHEET_NAME in wb.sheetnames:
        del wb[PLATFORM_HEALTH_SHEET_NAME]
    ws = wb.create_sheet(PLATFORM_HEALTH_SHEET_NAME)
    p = ph or {}
    finds = p.get("findings") or []
    pdev = p.get("per_device") or []
    s = p.get("summary") or {}
    bands = s.get("bands") or {}
    band_txt = ", ".join(f"{k}: {v}" for k, v in bands.items()) or "—"
    b = ws.cell(1, 1, f"Control-plane capacity screening: {s.get('n_findings', 0)} finding(s) on "
                      f"{s.get('n_collected', 0)} of {s.get('n_devices', 0)} device(s) with capacity "
                      "output. SINGLE point-in-time sample (a snapshot, not a trend) — correlate with "
                      "the Syslog Intelligence sheet and re-sample before the migration window.")
    b.font = Font(bold=True, color="7030A0", size=10)
    b.alignment = Alignment(horizontal="left", wrap_text=True)
    ws.cell(2, 1, f"Bands — {band_txt} · {s.get('n_not_collected', 0)} device(s) without capacity "
                  "output").font = Font(size=10)
    SEVFILL = _AXIS_SEV_FILL   # V3.23.171: this copy had also dropped the Low entry
    BANDFILL = {"Hot": "F4CCCC", "Elevated": "FFF2CC", "OK": "C6EFCE", "Unknown": "EFEFEF"}
    HDRF = Font(bold=True, color="FFFFFF", size=10)
    DAT = Font(name="Calibri", size=10)

    hdr_row = 4
    cols = ["Device", "Finding", "Severity", "Detail", "Recommendation"]
    for i, h in enumerate(cols, 1):
        c = ws.cell(hdr_row, i, h); c.font = HDRF
        c.fill = PatternFill("solid", fgColor="7030A0")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.freeze_panes = ws.cell(hdr_row + 1, 1)
    r = hdr_row + 1
    for f in finds:
        vals = [f.get("host"), f.get("label"), f.get("severity"), f.get("detail"),
                f.get("recommendation")]
        for col, v in enumerate(vals, 1):
            c = ws.cell(r, col, v); c.font = DAT
            c.alignment = Alignment(horizontal="center" if col == 3 else "left",
                                    vertical="top", wrap_text=col in (4, 5))
            if col == 3 and v in SEVFILL:
                c.fill = PatternFill("solid", fgColor=SEVFILL[v])
        r += 1
    if not finds:
        ws.cell(r, 1, "No capacity findings on the sampled devices." if s.get("n_collected")
                else "No capacity output collected -- platform health not assessable.").font = DAT
        r += 1

    r += 2
    ws.cell(r, 1, "Per-device sample (point-in-time)").font = Font(bold=True, color="7030A0", size=10)
    r += 1
    cols2 = ["Device", "Collected", "CPU 5-min %", "CPU 1-min %", "CPU 5-sec %",
             "Mem total (MB)", "Mem free %", "Band", "Status"]
    for i, h in enumerate(cols2, 1):
        c = ws.cell(r, i, h); c.font = HDRF
        c.fill = PatternFill("solid", fgColor="7030A0")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    r += 1
    for d in pdev:
        vals = [d.get("host"), "yes" if d.get("collected") else "NOT COLLECTED",
                d.get("cpu_5min"), d.get("cpu_1min"), d.get("cpu_5sec"),
                d.get("mem_total_mb"), d.get("mem_free_pct"), d.get("band"), d.get("status")]
        for col, v in enumerate(vals, 1):
            c = ws.cell(r, col, v if v is not None else "—"); c.font = DAT
            c.alignment = Alignment(horizontal="center" if col in (2, 3, 4, 5, 6, 7, 8) else "left",
                                    vertical="top", wrap_text=col == 9)
            if col == 8 and v in BANDFILL:
                c.fill = PatternFill("solid", fgColor=BANDFILL[v])
            if col == 2 and not d.get("collected"):
                c.fill = PatternFill("solid", fgColor="EFEFEF")
        r += 1
    # shared widths: findings table (A-E) wide prose; sample table spreads A-I.
    for i, w in enumerate([22, 28, 12, 40, 48, 14, 12, 12, 46], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    logger.info(f"  [OK] '{PLATFORM_HEALTH_SHEET_NAME}' sheet: {len(finds)} finding(s), "
                f"bands {band_txt}")


DEVICE_RISK_SHEET_NAME = "Device Risk Register"   # NEW-V3.23.172 (per-asset compound-risk synthesis)

def write_device_risk_sheet(wb, dd: dict) -> None:
    """Write 'Device Risk Register' from compute_device_dossiers(): one row per asset with the
    composite risk index (topology impact x stacked exposure), the per-axis red/watch counts and
    the engineer's verdict, then the compound-pattern detail table. The rows arrive pre-ranked
    (riskiest first) -- the sheet preserves that order so row 5 IS the scariest box."""
    if DEVICE_RISK_SHEET_NAME in wb.sheetnames:
        del wb[DEVICE_RISK_SHEET_NAME]
    ws = wb.create_sheet(DEVICE_RISK_SHEET_NAME)
    d0 = dd or {}
    pdev = d0.get("per_device") or []
    s = d0.get("summary") or {}
    bands = s.get("bands") or {}
    b = ws.cell(1, 1, f"Device Risk Register: {bands.get('Severe', 0)} Severe, "
                      f"{bands.get('Elevated', 0)} Elevated of {s.get('n_devices', 0)} asset(s) · "
                      f"{s.get('n_compound', 0)} compound pattern(s). "
                      "Risk index = topology impact (1-10) × stacked exposure (0-10) — the senior-"
                      "engineer read: independent risks coinciding on one box outrank any single finding.")
    b.font = Font(bold=True, color="9C0006", size=10)
    b.alignment = Alignment(horizontal="left", wrap_text=True)
    ws.cell(2, 1, d0.get("note", "")).font = Font(size=9, italic=True, color="808080")
    BANDFILL = {"Severe": "F4CCCC", "Elevated": "FCE4D6", "Guarded": "FFF2CC", "Low": "D9EAD3"}
    SEVFILL = _AXIS_SEV_FILL
    HDRF = Font(bold=True, color="FFFFFF", size=10)
    DAT = Font(name="Calibri", size=10)

    hdr_row = 4
    cols = ["Device", "Model", "Software", "Wave", "Risk index", "Band", "Impact", "Exposure",
            "Red axes", "Watch axes", "Health", "HW EoL", "SW train", "Control plane",
            "Compound patterns", "Engineer's verdict"]
    for i, h in enumerate(cols, 1):
        c = ws.cell(hdr_row, i, h); c.font = HDRF
        c.fill = PatternFill("solid", fgColor="9C0006")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.freeze_panes = ws.cell(hdr_row + 1, 1)
    r = hdr_row + 1
    for d in pdev:
        comp = ", ".join(f"{c.get('code', '')}" for c in (d.get("compound") or [])) or "—"
        vals = [d.get("host"), d.get("model") or "—", d.get("sw_version") or "—",
                d.get("wave") or "—", d.get("risk_index"), d.get("risk_band"),
                d.get("impact_score"), d.get("exposure_score"),
                d.get("n_risk"), d.get("n_watch"),
                d.get("health_band") or "—", d.get("eol_band"), d.get("train_band"),
                d.get("platform_band"), comp, d.get("verdict")]
        for col, v in enumerate(vals, 1):
            c = ws.cell(r, col, v); c.font = DAT
            c.alignment = Alignment(horizontal="center" if col in (4, 5, 6, 7, 8, 9, 10) else "left",
                                    vertical="top", wrap_text=col in (15, 16))
            if col == 6 and v in BANDFILL:
                c.fill = PatternFill("solid", fgColor=BANDFILL[v])
        r += 1
    if not pdev:
        ws.cell(r, 1, "No per-device axes were computed -- nothing to register.").font = DAT
        r += 1

    r += 2
    ws.cell(r, 1, "Compound patterns (independent risks coinciding on one asset)").font = \
        Font(bold=True, color="9C0006", size=10)
    r += 1
    cols2 = ["Device", "Code", "Pattern", "Severity", "Why it multiplies the concern"]
    for i, h in enumerate(cols2, 1):
        c = ws.cell(r, i, h); c.font = HDRF
        c.fill = PatternFill("solid", fgColor="9C0006")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    r += 1
    n_comp = 0
    for d in pdev:
        for cp in (d.get("compound") or []):
            vals = [d.get("host"), cp.get("code"), cp.get("title"), cp.get("severity"),
                    cp.get("basis")]
            for col, v in enumerate(vals, 1):
                c = ws.cell(r, col, v); c.font = DAT
                c.alignment = Alignment(horizontal="center" if col in (2, 4) else "left",
                                        vertical="top", wrap_text=col == 5)
                if col == 4 and v in SEVFILL:
                    c.fill = PatternFill("solid", fgColor=SEVFILL[v])
            r += 1
            n_comp += 1
    if not n_comp:
        ws.cell(r, 1, "No compound patterns -- no asset stacks independent risks. "
                      "Single-axis findings live on their own sheets and the punch-list.").font = DAT
    for i, w in enumerate([22, 20, 16, 10, 10, 10, 8, 9, 9, 10, 12, 12, 14, 13, 22, 60], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    logger.info(f"  [OK] '{DEVICE_RISK_SHEET_NAME}' sheet: {len(pdev)} asset(s), "
                f"{n_comp} compound pattern(s)")


LIFECYCLE_RISK_SHEET_NAME = "Lifecycle Risk"   # NEW-V3.23.117 (hardware EoL / end-of-support)

def write_lifecycle_risk_sheet(wb, lr: dict) -> None:
    """Write 'Lifecycle Risk' from compute_lifecycle_risk(): per-device hardware EoL / end-of-support band +
    a platform rollup. Row 1 is a static (date-free) title so the golden sheet schema stays stable."""
    if LIFECYCLE_RISK_SHEET_NAME in wb.sheetnames:
        del wb[LIFECYCLE_RISK_SHEET_NAME]
    ws = wb.create_sheet(LIFECYCLE_RISK_SHEET_NAME)
    L = lr or {}
    s = L.get("summary") or {}
    ws.cell(1, 1, "Hardware lifecycle (EoL / End-of-Support) — replacement urgency").font = Font(bold=True, size=11)
    ws.cell(2, 1, f"Lifecycle bands as of collection date {L.get('asof', '')}: {s.get('n_past_ldos', 0)} past end-of-support · "
                  f"{s.get('n_near', 0)} within 1yr · {s.get('n_active', 0)} active · "
                  f"{s.get('n_unknown', 0)} unknown (of {s.get('n_devices', 0)}).").font = Font(size=10)
    ws.cell(3, 1, L.get("note", "")).font = Font(size=9, italic=True, color="808080")
    BANDFILL = {"Past-LDoS": "F4CCCC", "Near-LDoS": "FCE4D6", "Past-EoS": "FFF2CC",
                "Active": "D9EAD3", "Unknown": "EFEFEF"}
    DAT = Font(name="Calibri", size=10)
    r = 5
    ws.cell(r, 1, "By platform").font = Font(bold=True); r += 1
    for i, h in enumerate(["Platform", "Devices", "Band", "LDoS"], 1):
        c = ws.cell(r, i, h); c.font = Font(bold=True, color="FFFFFF", size=10)
        c.fill = PatternFill("solid", fgColor="434343")
    r += 1
    for p in s.get("by_platform", []):
        vals = [p.get("platform"), p.get("count"), p.get("band"), p.get("ldos") or "—"]
        for col, v in enumerate(vals, 1):
            c = ws.cell(r, col, v); c.font = DAT
            if col == 3:
                c.fill = PatternFill("solid", fgColor=BANDFILL.get(v, "FFFFFF"))
        r += 1
    r += 1
    ws.cell(r, 1, "By device").font = Font(bold=True); r += 1
    cols = ["Device", "Model", "Platform", "SW version", "Band", "Status", "EoS", "LDoS", "Source"]
    for i, h in enumerate(cols, 1):
        c = ws.cell(r, i, h); c.font = Font(bold=True, color="FFFFFF", size=10)
        c.fill = PatternFill("solid", fgColor="434343")
        c.alignment = Alignment(horizontal="center", wrap_text=True)
    ws.freeze_panes = ws.cell(r + 1, 1); r += 1
    for d in L.get("per_device", []):
        vals = [d.get("host"), d.get("model"), d.get("platform"), d.get("sw_version"), d.get("band"),
                d.get("status"), d.get("eos") or "—", d.get("ldos") or "—", d.get("source") or "—"]
        for col, v in enumerate(vals, 1):
            c = ws.cell(r, col, v); c.font = DAT
            c.alignment = Alignment(vertical="top", wrap_text=col == 6)
            if col == 5:
                c.fill = PatternFill("solid", fgColor=BANDFILL.get(v, "FFFFFF"))
        r += 1
    for i, w in enumerate([28, 18, 16, 14, 11, 40, 12, 12, 22], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    logger.info(f"  [OK] '{LIFECYCLE_RISK_SHEET_NAME}' sheet: {s.get('n_devices', 0)} device(s), "
                f"{s.get('n_past_ldos', 0)} past-LDoS")


ARCHREVIEW_SHEET_NAME = "Architecture Review"   # NEW-V3.23.161 (leading-practice conformance scorecard)

# verdict -> (display label, fill) — the SAME labels the Architecture Review DOCX renders, so the
# workbook sheet and the report read identically.
_AR_VERDICTS = {"critical": ("CRITICAL DEVIATION", "F4CCCC"), "deviation": ("DEVIATION", "FCE4D6"),
                "advisory": ("ADVISORY", "FFF2CC"), "conforms": ("CONFORMS", "D9EAD3"),
                "not-assessable": ("NOT ASSESSABLE", "EFEFEF")}


def write_architecture_review_sheet(wb, ar: dict) -> None:
    """Write 'Architecture Review' from compute_architecture_review(): the conformance grade, the
    per-domain rollup, the full leading-practice check scorecard and the priority remediation
    queue — the workbook (evidence) twin of the Architecture Review & Conformance Report DOCX.
    Row 1 is a static (date-free) title so the golden sheet schema stays stable."""
    if ARCHREVIEW_SHEET_NAME in wb.sheetnames:
        del wb[ARCHREVIEW_SHEET_NAME]
    ws = wb.create_sheet(ARCHREVIEW_SHEET_NAME)
    A = ar or {}
    s = A.get("summary") or {}
    HDR = Font(bold=True, color="FFFFFF", size=10); HFILL = PatternFill("solid", fgColor="434343")
    DAT = Font(name="Calibri", size=10)
    score = s.get("score_pct")
    ws.cell(1, 1, "Architecture Review — leading-practice conformance scorecard").font = \
        Font(bold=True, size=11)
    ws.cell(2, 1, f"Conformance grade {s.get('grade', 'N/A')}"
                  + (f" ({score}%)" if score is not None else "")
                  + f" — {s.get('grade_label', '')}: {s.get('n_conforms', 0)} conform · "
                    f"{s.get('n_advisory', 0)} advisory · {s.get('n_deviation', 0)} deviation · "
                    f"{s.get('n_critical', 0)} critical · "
                    f"{s.get('n_not_assessable', 0)} not assessable.").font = Font(size=10)
    ws.cell(3, 1, s.get("statement", "")).font = Font(size=9, italic=True, color="808080")

    r = 5
    ws.cell(r, 1, "By domain").font = Font(bold=True); r += 1
    for i, h in enumerate(["Domain", "Verdict", "Score"], 1):
        c = ws.cell(r, i, h); c.font = HDR; c.fill = HFILL
    r += 1
    for d in (A.get("domains") or []):
        d = d if isinstance(d, dict) else {}
        label, fill = _AR_VERDICTS.get(d.get("verdict"), (str(d.get("verdict") or "—"), "FFFFFF"))
        sc = d.get("score_pct")
        for col, v in enumerate([d.get("key"), label, f"{sc}%" if sc is not None else "—"], 1):
            c = ws.cell(r, col, v); c.font = DAT
            if col == 2:
                c.fill = PatternFill("solid", fgColor=fill)
        r += 1

    r += 1
    ws.cell(r, 1, "All checks").font = Font(bold=True); r += 1
    cols = ["Check", "Domain", "Title", "Verdict", "Evidence", "Observed", "Recommendation",
            "Reference"]
    for i, h in enumerate(cols, 1):
        c = ws.cell(r, i, h); c.font = HDR; c.fill = HFILL
        c.alignment = Alignment(horizontal="center", wrap_text=True)
    ws.freeze_panes = ws.cell(r + 1, 1); r += 1
    for ck in (A.get("checks") or []):
        ck = ck if isinstance(ck, dict) else {}
        label, fill = _AR_VERDICTS.get(ck.get("verdict"), (str(ck.get("verdict") or "—"), "FFFFFF"))
        vals = [ck.get("id"), ck.get("domain"), ck.get("title"), label,
                ", ".join(str(x) for x in (ck.get("evidence") or [])) or "—",
                ck.get("observed"), ck.get("recommendation"), ck.get("reference")]
        for col, v in enumerate(vals, 1):
            c = ws.cell(r, col, v); c.font = DAT
            c.alignment = Alignment(vertical="top", wrap_text=col >= 5)
            if col == 4:
                c.fill = PatternFill("solid", fgColor=fill)
        r += 1

    queue = A.get("top_actions") or []
    if queue:
        r += 1
        ws.cell(r, 1, "Priority remediation queue (severity, then blast radius)").font = \
            Font(bold=True); r += 1
        for i, h in enumerate(["#", "Check", "Severity", "Action", "Evidence"], 1):
            c = ws.cell(r, i, h); c.font = HDR; c.fill = HFILL
        r += 1
        for a in queue:
            a = a if isinstance(a, dict) else {}
            label, fill = _AR_VERDICTS.get(a.get("verdict"), (str(a.get("verdict") or "—"), "FFFFFF"))
            vals = [a.get("rank"), a.get("id"), label, a.get("action"),
                    ", ".join(str(x) for x in (a.get("evidence") or [])) or "—"]
            for col, v in enumerate(vals, 1):
                c = ws.cell(r, col, v); c.font = DAT
                c.alignment = Alignment(vertical="top", wrap_text=col == 4)
                if col == 3:
                    c.fill = PatternFill("solid", fgColor=fill)
            r += 1

    for i, w in enumerate([9, 26, 38, 19, 34, 60, 60, 44], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    logger.info(f"  [OK] '{ARCHREVIEW_SHEET_NAME}' sheet: grade {s.get('grade', 'N/A')}, "
                f"{s.get('n_checks', 0)} check(s), {s.get('n_critical', 0)} critical")


SEGMENTATION_SHEET_NAME = "Segmentation"   # NEW-V3.23.118 (L3 isolation posture)

def write_segmentation_sheet(wb, seg: dict) -> None:
    """Write 'Segmentation' from compute_segmentation(): VRF inventory, gateway-ACL coverage, per-domain
    isolation, and the findings. Row 1 is a static title."""
    if SEGMENTATION_SHEET_NAME in wb.sheetnames:
        del wb[SEGMENTATION_SHEET_NAME]
    ws = wb.create_sheet(SEGMENTATION_SHEET_NAME)
    g = seg or {}
    s = g.get("summary") or {}
    ga = g.get("gateway_acl") or {}
    HDR = Font(bold=True, color="FFFFFF", size=10); HFILL = PatternFill("solid", fgColor="434343")
    DAT = Font(name="Calibri", size=10)
    flat = bool(s.get("flat"))
    ws.cell(1, 1, "L3 Segmentation & Isolation posture").font = Font(bold=True, size=11)
    ws.cell(2, 1, ("FLAT L3 — " if flat else "") + f"{s.get('n_vrfs', 0)} VRF(s); gateway ACL coverage "
                  f"{ga.get('n_with_acl', 0)}/{ga.get('n_gateways', 0)} ({ga.get('coverage_pct', 0)}%); "
                  f"{s.get('n_oncrit_exposed', 0)} on-air-critical domain(s) not isolated.").font = Font(
        size=10, bold=flat, color="9C0006" if flat else "000000")
    r = [4]

    def section(t):
        ws.cell(r[0], 1, t).font = Font(bold=True); r[0] += 1

    def header(cols):
        for i, h in enumerate(cols, 1):
            c = ws.cell(r[0], i, h); c.font = HDR; c.fill = HFILL
            c.alignment = Alignment(horizontal="center", wrap_text=True)
        r[0] += 1

    section("VRF inventory")
    header(["VRF", "Gateways"])
    for v in g.get("vrfs", []):
        ws.cell(r[0], 1, v.get("vrf")).font = DAT
        ws.cell(r[0], 2, v.get("gateway_count")).font = DAT
        r[0] += 1
    r[0] += 1

    section("Per-domain isolation")
    header(["Domain", "Tier", "Gateways", "VRF(s)", "Gateway ACLs", "Isolated", "Exposure"])
    ISOFILL = {True: "D9EAD3", False: "F4CCCC"}
    for d in g.get("domains", []):
        vals = [d.get("domain"), d.get("tier"), d.get("gateways"), ", ".join(d.get("vrfs") or []),
                d.get("gateways_with_acl"), "yes" if d.get("isolated") else "no", d.get("exposure")]
        for col, v in enumerate(vals, 1):
            c = ws.cell(r[0], col, v); c.font = DAT
            c.alignment = Alignment(vertical="top", wrap_text=col == 7)
            if col == 6:
                c.fill = PatternFill("solid", fgColor=ISOFILL.get(bool(d.get("isolated")), "FFFFFF"))
        r[0] += 1
    r[0] += 1

    section("Findings")
    risks = g.get("risks") or []
    if not risks:
        ws.cell(r[0], 1, "No segmentation findings.").font = DAT; r[0] += 1
    else:
        header(["Severity", "Finding", "Detail", "Remediation"])
        for x in risks:
            vals = [x.get("severity"), x.get("title"), x.get("detail"), x.get("remediation")]
            for col, v in enumerate(vals, 1):
                c = ws.cell(r[0], col, v); c.font = DAT
                c.alignment = Alignment(vertical="top", wrap_text=col in (3, 4))
            r[0] += 1

    for i, w in enumerate([34, 15, 9, 16, 12, 9, 50], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"
    logger.info(f"  [OK] '{SEGMENTATION_SHEET_NAME}' sheet: {s.get('n_gateways', 0)} gateway(s), flat={flat}")


PROTOCOL_BOUNDARIES_SHEET_NAME = "Protocol Boundaries"   # protocol-to-protocol analysis (workbook surfacing)

def write_protocol_boundaries_sheet(wb, all_routing_neighbors: dict, all_redistribution: dict) -> None:
    """Write the 'Protocol Boundaries' sheet: per device, the routing protocols it runs, its redistribution
    edges (from -> into, + route-map), and a MUTUAL-redistribution risk flag -- so a migration can recreate
    every protocol-to-protocol boundary. One row per device that runs a dynamic protocol or redistributes."""
    ws = wb.create_sheet(PROTOCOL_BOUNDARIES_SHEET_NAME)
    for col, h in enumerate(["Switch", "Protocols", "Redistribution (from -> into)", "Route-map(s)", "Mutual"], 1):
        c = ws.cell(1, col, h); c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="434343"); c.alignment = Alignment(horizontal="center")
    dyn = ("ospf", "eigrp", "bgp", "rip", "isis")
    r = 2; nrows = 0
    for host in sorted(set(all_routing_neighbors) | set(all_redistribution)):
        rn = all_routing_neighbors.get(host) or {}
        edges = all_redistribution.get(host) or []
        protos = {p for p in ("ospf", "eigrp", "bgp") if rn.get(p)}
        for e in edges:
            for p in (e.get("into_proto"), e.get("from_proto")):
                if p in dyn: protos.add(p)
        if not protos and not edges:
            continue
        pairs = {(e.get("into_proto"), e.get("from_proto")) for e in edges}
        mutual = sorted({"/".join(sorted([a, b])) for (a, b) in pairs if a != b and (b, a) in pairs})
        rmaps = sorted({e["route_map"] for e in edges if e.get("route_map")})
        ws.cell(r, 1, host)
        ws.cell(r, 2, ", ".join(sorted(protos)).upper() or "-")
        ws.cell(r, 3, "; ".join(f"{e.get('from_proto', '')} -> {e.get('into_proto', '')}" for e in edges) or "-")
        ws.cell(r, 4, ", ".join(rmaps) or "-")
        mc = ws.cell(r, 5, ", ".join(m.upper() for m in mutual) or "-")
        if mutual:
            mc.font = Font(bold=True, color="C00000")
        r += 1; nrows += 1
    for i, w in enumerate([16, 22, 46, 22, 16], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"
    logger.info(f"  [OK] '{PROTOCOL_BOUNDARIES_SHEET_NAME}' sheet: {nrows} routing device(s)")


def _svi_ip_net(svi: str) -> Tuple[str, str]:
    """('10.0.10.2 255.255.255.0' | '10.0.10.2/24' | '10.0.10.2') -> (ip, 'net/plen' or '')."""
    parts = (svi or "").split()
    if not parts:
        return ("", "")
    first = parts[0]
    try:
        if "/" in first:
            iface = ipaddress.ip_interface(first)
        elif len(parts) >= 2:
            iface = ipaddress.ip_interface(f"{first}/{parts[1]}")
        else:
            ipaddress.ip_address(first); return (first, "")   # bare IP, no subnet
        return (str(iface.ip), str(iface.network))
    except ValueError:
        return ("", "")


def compute_addressing_conflicts(all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> dict:
    """Fabric-wide L3 addressing conflicts (mirrors the explorer's addressingConflicts): the same physical IP
    on >=2 interfaces (duplicate L3 address -- the FHRP virtual IP lives in hsrp_behavior, not svi_ip, so a
    shared svi_ip is always a real clash), and the same subnet behind >=2 VLANs in the SAME VRF (overlapping
    addressing; different VRFs may intentionally overlap, so they're excluded). Returns
    {"dup_ip":[{ip,where:[(host,port,vid)]}], "dup_subnet":[{net,vrf,where:[...]}]}."""
    by_ip: Dict[str, list] = {}
    by_sub: Dict[tuple, list] = {}
    for host in sorted(all_interfaces):
        for port, d in all_interfaces[host].items():
            svi = (getattr(d, "svi_ip", "") or "").strip()
            if not svi:
                continue
            ip, net = _svi_ip_net(svi)
            if not ip:
                continue
            m = re.match(r"^Vlan(\d+)$", port or "", re.IGNORECASE)
            vid = int(m.group(1)) if m else None
            vrf = (getattr(d, "vrf", "") or "").strip().lower()
            vrf = "" if vrf in ("", "default", "global") else vrf
            by_ip.setdefault(ip, []).append((host, port, vid))
            if net and vid is not None:
                by_sub.setdefault((vrf, net), []).append((host, port, vid))
    dup_ip = [{"ip": ip, "where": w} for ip, w in sorted(by_ip.items())
              if len({(h, p) for (h, p, v) in w}) > 1]
    dup_subnet = [{"net": net, "vrf": vrf, "where": w} for (vrf, net), w in sorted(by_sub.items())
                  if len({v for (h, p, v) in w}) > 1]
    return {"dup_ip": dup_ip, "dup_subnet": dup_subnet}


ADDRESSING_CONFLICTS_SHEET_NAME = "Addressing Conflicts"

def write_addressing_conflicts_sheet(wb, all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> None:
    """Write the 'Addressing Conflicts' sheet: duplicate L3 IPs and overlapping subnets across the fabric --
    the classic silent outage when two domains merge or a move-group cuts over. Surfaces the reachability
    explorer's addressing-integrity finding in the workbook."""
    c = compute_addressing_conflicts(all_interfaces)
    ws = wb.create_sheet(ADDRESSING_CONFLICTS_SHEET_NAME)
    for col, h in enumerate(["Type", "Address / Subnet", "VRF", "Configured on"], 1):
        cell = ws.cell(1, col, h); cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="434343"); cell.alignment = Alignment(horizontal="center")

    def _loc(where):
        return ", ".join(f"{h} {('VLAN ' + str(v)) if v is not None else p}" for (h, p, v) in where)
    r = 2
    for d in c["dup_ip"]:
        ws.cell(r, 1, "duplicate IP"); ws.cell(r, 2, d["ip"]); ws.cell(r, 3, "-"); ws.cell(r, 4, _loc(d["where"]))
        for col in (1, 2): ws.cell(r, col).font = Font(bold=True, color="C00000")
        r += 1
    for d in c["dup_subnet"]:
        ws.cell(r, 1, "overlapping subnet"); ws.cell(r, 2, d["net"]); ws.cell(r, 3, d["vrf"] or "global"); ws.cell(r, 4, _loc(d["where"]))
        for col in (1, 2): ws.cell(r, col).font = Font(bold=True, color="C00000")
        r += 1
    if r == 2:
        ws.cell(2, 1, "clean"); ws.cell(2, 2, "No duplicate IPs or overlapping subnets detected")
    for i, w in enumerate([18, 26, 14, 60], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"
    logger.info(f"  [OK] '{ADDRESSING_CONFLICTS_SHEET_NAME}' sheet: "
                f"{len(c['dup_ip'])} dup-IP, {len(c['dup_subnet'])} overlap")


def compute_fhrp_consistency(all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> List[dict]:
    """Fabric-wide first-hop-redundancy (FHRP) consistency (mirrors the explorer's fhrpConsistency): for each
    VLAN with >=2 gateways (SVIs), flag FAKE redundancy -- a gateway running no FHRP, different FHRP groups,
    different virtual IPs, mixed protocols, or two actives (split-brain). Reuses parse._parse_fhrp. Returns
    [{vid, issues:[str], members:[{host,proto,group,vip,role,fhrp}]}] for VLANs with an issue (empty when clean)."""
    from cisco_toolkit.parse import _parse_fhrp
    by_vid: Dict[int, list] = {}
    for host in sorted(all_interfaces):
        for port, d in all_interfaces[host].items():
            m = re.match(r"^Vlan(\d+)$", port or "", re.IGNORECASE)
            if not m:
                continue
            if not ((getattr(d, "svi_ip", "") or "").strip() or (getattr(d, "hsrp_behavior", "") or "").strip()):
                continue                                                 # only real gateways (SVI with an IP or FHRP)
            by_vid.setdefault(int(m.group(1)), []).append((host, d))
    out: List[dict] = []
    for vid in sorted(by_vid):
        gws = by_vid[vid]
        if len(gws) < 2:                                                 # single gateway -> SPOF, handled elsewhere
            continue
        det = []
        for host, d in gws:
            proto, role, vip, group = _parse_fhrp(getattr(d, "hsrp_behavior", "") or "")
            det.append({"host": host, "proto": (proto or "").upper(), "group": group or "",
                        "vip": vip or "", "role": (role or "").lower(), "fhrp": bool(proto)})
        withf = [x for x in det if x["fhrp"]]
        without = [x for x in det if not x["fhrp"]]
        issues: List[str] = []
        if not withf:
            issues.append(f"{len(gws)} gateways but no FHRP — no first-hop redundancy")
            out.append({"vid": vid, "issues": issues, "members": det}); continue
        protos = {x["proto"] for x in withf}
        groups = {x["group"] for x in withf if x["group"]}
        vips = {x["vip"] for x in withf if x["vip"]}
        actives = [x for x in withf if x["role"] == "active"]
        if without:
            issues.append(f"{', '.join(x['host'] for x in without)} runs no FHRP — unprotected, independent gateway")
        if len(protos) > 1:
            issues.append(f"mixed FHRP protocols ({' vs '.join(sorted(protos))})")
        if len(groups) > 1:
            issues.append(f"different FHRP groups (grp {' vs '.join(sorted(groups))}) — not one redundancy group")
        elif len(vips) > 1:
            issues.append(f"same group but different virtual IPs ({' vs '.join(sorted(vips))})")
        if len(groups) == 1 and len(actives) > 1:
            issues.append(f"two active routers ({', '.join(x['host'] for x in actives)}) — split-brain")
        if issues:
            out.append({"vid": vid, "issues": issues, "members": det})
    return out


FHRP_CONSISTENCY_SHEET_NAME = "FHRP Consistency"

def write_fhrp_consistency_sheet(wb, all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> None:
    """Write the 'FHRP Consistency' sheet: VLANs whose >=2 gateways have MISconfigured first-hop redundancy
    (fake redundancy that fails silently at failover). Surfaces the explorer's FHRP-consistency finding."""
    rows = compute_fhrp_consistency(all_interfaces)
    ws = wb.create_sheet(FHRP_CONSISTENCY_SHEET_NAME)
    for col, h in enumerate(["VLAN", "Issue", "Gateways"], 1):
        cell = ws.cell(1, col, h); cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="434343"); cell.alignment = Alignment(horizontal="center")
    r = 2
    for row in rows:
        mem = "; ".join(
            f"{x['host']} " + (f"{x['proto']} grp {x['group']} {x['role']}".strip() if x["fhrp"] else "no FHRP")
            for x in row["members"])
        ic = ws.cell(r, 1, f"VLAN {row['vid']}"); ic.font = Font(bold=True, color="C00000")
        ws.cell(r, 2, "; ".join(row["issues"])); ws.cell(r, 3, mem)
        r += 1
    if r == 2:
        ws.cell(2, 1, "clean"); ws.cell(2, 2, "No FHRP misconfigurations on multi-gateway VLANs")
    for i, w in enumerate([12, 70, 50], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"
    logger.info(f"  [OK] '{FHRP_CONSISTENCY_SHEET_NAME}' sheet: {len(rows)} VLAN(s) with FHRP issues")


def compute_trunk_native_mismatches(all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> List[dict]:
    """Native-VLAN mismatches on inter-switch trunks (mirrors the explorer's trunkConsistency native check):
    the two ends of a CDP/LLDP link disagree on the native (untagged) VLAN -> a silent L2 leak between those
    VLANs and a VLAN-hopping exposure. The default native VLAN is 1, so an explicit native on only one end is
    still a mismatch. Reuses analyze.compute_topology_links. Returns [{a_host,a_port,a_native,b_host,b_port,b_native}]."""
    from cisco_toolkit.analyze import compute_topology_links, _canon_host, _canon_host_map
    cmap = _canon_host_map(all_interfaces)
    out: List[dict] = []
    for L in compute_topology_links(all_interfaces):
        a = all_interfaces.get(str(L["a_host"]), {}).get(str(L["a_port"]))
        bh = cmap.get(_canon_host(str(L["b_host"])))
        b = all_interfaces.get(bh, {}).get(str(L["b_port"])) if bh else None
        if a is None or b is None:
            continue
        an = (getattr(a, "trunk_native_vlan", "") or "").strip() or "1"
        bn = (getattr(b, "trunk_native_vlan", "") or "").strip() or "1"
        if an != bn:
            out.append({"a_host": str(L["a_host"]), "a_port": str(L["a_port"]), "a_native": an,
                        "b_host": bh, "b_port": str(L["b_port"]), "b_native": bn})
    return out


TRUNK_NATIVE_SHEET_NAME = "Trunk Native-VLAN"

def write_trunk_native_sheet(wb, all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> None:
    """Write the 'Trunk Native-VLAN' sheet: inter-switch trunks whose two ends disagree on the native
    (untagged) VLAN -- a silent L2 leak / VLAN-hopping exposure. Surfaces the explorer's trunk-consistency
    native-VLAN finding (allowed-VLAN asymmetry stays explorer-only for now)."""
    rows = compute_trunk_native_mismatches(all_interfaces)
    ws = wb.create_sheet(TRUNK_NATIVE_SHEET_NAME)
    for col, h in enumerate(["End A", "Native A", "End B", "Native B"], 1):
        cell = ws.cell(1, col, h); cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="434343"); cell.alignment = Alignment(horizontal="center")
    r = 2
    for d in rows:
        ws.cell(r, 1, f"{d['a_host']} {d['a_port']}")
        ca = ws.cell(r, 2, d["a_native"]); ca.font = Font(bold=True, color="C00000")
        ws.cell(r, 3, f"{d['b_host']} {d['b_port']}")
        cb = ws.cell(r, 4, d["b_native"]); cb.font = Font(bold=True, color="C00000")
        r += 1
    if r == 2:
        ws.cell(2, 1, "clean"); ws.cell(2, 2, "No native-VLAN mismatches on inter-switch trunks")
    for i, w in enumerate([34, 12, 34, 12], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"
    logger.info(f"  [OK] '{TRUNK_NATIVE_SHEET_NAME}' sheet: {len(rows)} mismatch(es)")


def _norm_duplex(s: str) -> str:
    s = (s or "").lower()
    return "half" if "half" in s else "full" if "full" in s else ""

def _norm_speed_mbps(s: str) -> int:
    m = re.search(r"(\d+)\s*(g|m)?", (s or "").lower())
    return int(m.group(1)) * (1000 if m and m.group(2) == "g" else 1) if m else 0

def compute_duplex_speed_mismatches(all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> List[dict]:
    """Duplex / speed mismatches on inter-switch links (mirrors the explorer's linkPhyConsistency): the two
    ends report a different OPERATIONAL duplex (one full, the other half -- the classic 'up but slow/flaky')
    or speed. 'auto-...' that hasn't resolved is skipped. Reuses analyze.compute_topology_links. Returns
    [{a_host,a_port,b_host,b_port, duplex:(ad,bd)|None, speed:(asp,bsp)|None}] (speeds in Mbps)."""
    from cisco_toolkit.analyze import compute_topology_links, _canon_host, _canon_host_map
    cmap = _canon_host_map(all_interfaces)
    out: List[dict] = []
    for L in compute_topology_links(all_interfaces):
        a = all_interfaces.get(str(L["a_host"]), {}).get(str(L["a_port"]))
        bh = cmap.get(_canon_host(str(L["b_host"])))
        b = all_interfaces.get(bh, {}).get(str(L["b_port"])) if bh else None
        if a is None or b is None:
            continue
        ad, bd = _norm_duplex(getattr(a, "duplex", "")), _norm_duplex(getattr(b, "duplex", ""))
        asp, bsp = _norm_speed_mbps(getattr(a, "speed", "")), _norm_speed_mbps(getattr(b, "speed", ""))
        dup = (ad, bd) if (ad and bd and ad != bd) else None
        spd = (asp, bsp) if (asp and bsp and asp != bsp) else None
        if dup or spd:
            out.append({"a_host": str(L["a_host"]), "a_port": str(L["a_port"]),
                        "b_host": bh, "b_port": str(L["b_port"]), "duplex": dup, "speed": spd})
    return out


LINK_PHY_SHEET_NAME = "Link Duplex-Speed"

def write_link_phy_sheet(wb, all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> None:
    """Write the 'Link Duplex-Speed' sheet: inter-switch links whose two ends disagree on operational duplex
    or speed -- the classic 'link is up but slow/flaky' (late collisions, CRC errors). Surfaces the explorer's
    link L1 finding."""
    rows = compute_duplex_speed_mismatches(all_interfaces)
    ws = wb.create_sheet(LINK_PHY_SHEET_NAME)
    for col, h in enumerate(["Link", "Issue", "End A", "End B"], 1):
        cell = ws.cell(1, col, h); cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="434343"); cell.alignment = Alignment(horizontal="center")

    def _spd(mb):
        return (f"{mb // 1000}G" if mb >= 1000 else f"{mb}M") if mb else "?"
    r = 2
    for d in rows:
        kind = "duplex" if d["duplex"] else "speed"
        ws.cell(r, 1, f"{d['a_host']} {d['a_port']} <-> {d['b_host']} {d['b_port']}")
        ws.cell(r, 2, kind).font = Font(bold=True, color="C00000")
        if d["duplex"]:
            ws.cell(r, 3, f"duplex {d['duplex'][0]}"); ws.cell(r, 4, f"duplex {d['duplex'][1]}")
        else:
            ws.cell(r, 3, f"speed {_spd(d['speed'][0])}"); ws.cell(r, 4, f"speed {_spd(d['speed'][1])}")
        r += 1
    if r == 2:
        ws.cell(2, 1, "clean"); ws.cell(2, 2, "No duplex/speed mismatches on inter-switch links")
    for i, w in enumerate([46, 12, 18, 18], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"
    logger.info(f"  [OK] '{LINK_PHY_SHEET_NAME}' sheet: {len(rows)} mismatch(es)")


def write_migration_readiness_sheet(wb, readiness: List[dict]) -> None:
    ws = wb.create_sheet(MIGRATION_READINESS_SHEET_NAME)
    headers = ["Group / Check", "Status", "Phase", "Detail"]
    for col, h in enumerate(headers, 1):
        c = ws.cell(1, col, h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="434343")
        c.alignment = Alignment(horizontal="center")
    r = 2
    for g in readiness:
        c = ws.cell(r, 1, f"{g['group']}  ({len(g['switches'])} switch(es), {g['endpoints']} endpoint-MAC(s))")
        c.font = Font(bold=True)
        cs = ws.cell(r, 2, g["readiness"])
        cs.font = Font(bold=True)
        if g["readiness"] in _READY_FILL:
            cs.fill = PatternFill("solid", fgColor=_READY_FILL[g["readiness"]])
        ws.cell(r, 4, ", ".join(g["switches"]))
        r += 1
        for chk in g["checks"]:
            ws.cell(r, 1, "    " + chk["check"])
            sc = ws.cell(r, 2, chk["status"].upper())
            if chk["status"] in _STATUS_FILL:
                sc.fill = PatternFill("solid", fgColor=_STATUS_FILL[chk["status"]])
            ws.cell(r, 3, chk.get("phase", ""))
            ws.cell(r, 4, chk["note"])
            r += 1
        r += 1   # blank row between groups
    for i, w in enumerate([40, 9, 18, 70], 1):
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

def write_causality_chains_sheet(wb, chains: list) -> None:
    """Write (or replace) 'Causality Chains': cause -> mechanism -> blast radius reasoning.
    NEW-V3.23.91: takes the precomputed chains (compute_causality_chains, run once in main and
    shared with the snapshot) instead of recomputing -- the heavy host x VLAN articulation walk
    ran twice per report. Same (severity, trigger, mechanism, impact, mitigation) tuples."""
    cols = ["Severity", "Trigger (root cause)", "Mechanism (why it propagates)",
            "Impact (blast radius)", "Mitigation"]
    if CAUSALITY_SHEET_NAME in wb.sheetnames:
        del wb[CAUSALITY_SHEET_NAME]
    ws = wb.create_sheet(CAUSALITY_SHEET_NAME)
    _census_header(ws, cols)
    chains = chains or []
    DAT_FONT = Font(name="Calibri", size=10)
    DAT_L = Alignment(horizontal="left", vertical="top", wrap_text=True)
    r = 2
    for sev, trig, mech, impact, mit, *_hosts in chains:   # V3.23.92: chains carry a trailing hosts tuple (sheet ignores it)
        for col, v in enumerate([sev, trig, mech, impact, mit], 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT_FONT; c.alignment = DAT_L
            if col == 1 and sev in _SEV_FILL:
                c.fill = PatternFill("solid", fgColor=_SEV_FILL[sev])
        r += 1
    _census_autofit(ws, len(cols), r - 1)
    for colL, w in (("B", 34), ("C", 46), ("D", 46), ("E", 40)):
        ws.column_dimensions[colL].width = w
    logger.info(f"  [OK] '{CAUSALITY_SHEET_NAME}' sheet: {len(chains)} chain(s)")


def write_failure_impact_sheet(wb, rows: list) -> None:
    """Write (or replace) 'Failure Impact': per-switch migration blast-radius simulation.
    NEW-V3.23.91: takes the precomputed records (compute_failure_impact, run once in main and
    shared with the snapshot + executive summary) instead of recomputing the per-switch removal
    simulation a third time."""
    cols = ["Severity", "Switch (remove / migrate)", "VLANs Impacted", "Stranded Endpoints",
            "Hard Partitions", "Backup-Covered", "FHRP-Covered", "Per-VLAN Detail"]
    if FAILURE_SHEET_NAME in wb.sheetnames:
        del wb[FAILURE_SHEET_NAME]
    ws = wb.create_sheet(FAILURE_SHEET_NAME)
    _census_header(ws, cols)
    rows = rows or []
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


LINK_CENTRALITY_SHEET_NAME = "Link Centrality"

def write_link_centrality_sheet(wb, all_interfaces: Dict[str, Dict[str, InterfaceData]]) -> None:
    """Write (or replace) 'Link Centrality': structural chokepoint ranking of the inter-switch links --
    edge betweenness (share of all-pairs shortest-path flow that crosses each link) + bridge detection
    (links whose failure partitions the fabric). The LINK twin of the per-switch 'Failure Impact' sheet;
    same compute_link_centrality the explorer's chokepoint card consumes (one source of truth)."""
    from cisco_toolkit.analyze import compute_link_centrality
    cols = ["Rank", "Link", "Betweenness", "Bridge / SPOF", "Switch-Pairs Severed", "Assessment"]
    if LINK_CENTRALITY_SHEET_NAME in wb.sheetnames:
        del wb[LINK_CENTRALITY_SHEET_NAME]
    ws = wb.create_sheet(LINK_CENTRALITY_SHEET_NAME)
    _census_header(ws, cols)
    rows = compute_link_centrality(all_interfaces)
    DAT_FONT = Font(name="Calibri", size=10)
    DAT_L = Alignment(horizontal="left", vertical="center")
    DAT_C = Alignment(horizontal="center", vertical="center")
    warn_fill = PatternFill("solid", fgColor="F4CCCC")
    r = 2
    for rec in rows:
        link = f"{rec['a_host']} {rec['a_port']} <-> {rec['b_host']} {rec['b_port']}".strip()
        bridge = "YES" if rec["is_bridge"] else ""
        cut = rec["pairs_cut"] if rec["is_bridge"] else ""
        if rec["is_bridge"]:
            note = "Bridge — its failure partitions the fabric (true single point of failure)"
        elif int(rec["rank"]) <= 3:
            note = "High betweenness — a large share of east-west paths funnel through this link"
        else:
            note = ""
        vals = [rec["rank"], link, rec["betweenness"], bridge, cut, note]
        for col, v in enumerate(vals, 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT_FONT
            c.alignment = DAT_C if col in (1, 3, 4, 5) else DAT_L
            if rec["is_bridge"] and col in (4, 5):
                c.fill = warn_fill
        r += 1
    if r == 2:
        ws.cell(2, 1, "-"); ws.cell(2, 2, "No inter-switch links detected")
    _census_autofit(ws, len(cols), r - 1)
    ws.column_dimensions["B"].width = 48
    ws.column_dimensions["F"].width = 62
    logger.info(f"  [OK] '{LINK_CENTRALITY_SHEET_NAME}' sheet: {len(rows)} link(s), "
                f"{sum(1 for x in rows if x['is_bridge'])} bridge(s)")


WAVE_SEQUENCING_SHEET_NAME = "Wave Sequencing"

def write_wave_sequencing_sheet(wb, all_interfaces: Dict[str, Dict[str, InterfaceData]],
                                move_groups: List[Dict[str, object]]) -> None:
    """Write (or replace) 'Wave Sequencing': per move-group cutover plan -- which member switches are HARD
    CUTOVERS (single-homed, need a maintenance window) vs MAKE-BEFORE-BREAK (dual-homed, migrate live).
    Same compute_wave_sequencing the explorer's Waves mode consumes (one source of truth)."""
    from cisco_toolkit.analyze import compute_wave_sequencing
    cols = ["Group", "Cutover Plan", "Hard Cutover (window)", "Make-Before-Break", "Endpoints at Risk"]
    if WAVE_SEQUENCING_SHEET_NAME in wb.sheetnames:
        del wb[WAVE_SEQUENCING_SHEET_NAME]
    ws = wb.create_sheet(WAVE_SEQUENCING_SHEET_NAME)
    _census_header(ws, cols)
    rows = compute_wave_sequencing(all_interfaces, move_groups)
    DAT_FONT = Font(name="Calibri", size=10)
    DAT_L = Alignment(horizontal="left", vertical="top", wrap_text=True)
    DAT_C = Alignment(horizontal="center", vertical="center")
    warn_fill = PatternFill("solid", fgColor="FCE5CD")
    r = 2
    for rec in rows:
        hard = ", ".join(str(h) for h in rec["hard_cutover"])
        mbb = ", ".join(str(h) for h in rec["make_before_break"])
        vals = [rec["group"], rec["sequence"], hard, mbb, rec["hard_cutover_endpoints"]]
        for col, v in enumerate(vals, 1):
            c = ws.cell(row=r, column=col, value=v); c.font = DAT_FONT
            c.alignment = DAT_C if col == 5 else DAT_L
            if rec["hard_cutover"] and col in (3, 5):
                c.fill = warn_fill
        r += 1
    if r == 2:
        ws.cell(2, 1, "-"); ws.cell(2, 2, "No move groups")
    _census_autofit(ws, len(cols), r - 1)
    ws.column_dimensions["B"].width = 54
    ws.column_dimensions["C"].width = 34
    ws.column_dimensions["D"].width = 34
    logger.info(f"  [OK] '{WAVE_SEQUENCING_SHEET_NAME}' sheet: {len(rows)} group(s)")


EXEC_SUMMARY_SHEET_NAME = "Executive Summary"

def write_executive_summary_sheet(wb, health_scores: list, punchlist: list,
                                  migration_readiness: list,
                                  failure_impact: list, brief=None) -> None:
    """Write the 'Executive Summary' landing sheet (moved to the FRONT of the workbook): a one-page
    synthesis -- fleet posture, the keystone devices the fleet most depends on (migration blast radius),
    the punch-list severity / category breakdown, and per-group migration readiness -- so a reader knows
    where to start without opening all 30+ detail tabs. This is the workbook twin of the explorer's Risk
    cockpit: pure presentation of already-computed data; every detail tab remains the source of record."""
    ws = wb.create_sheet(EXEC_SUMMARY_SHEET_NAME)
    TITLE = Font(name="Calibri", bold=True, size=15, color="1F3864")
    SUB   = Font(name="Calibri", bold=True, size=11, color="1F3864")
    KEY   = Font(name="Calibri", bold=True, size=10)
    DAT   = Font(name="Calibri", size=10)
    HDR   = Font(name="Calibri", bold=True, size=10, color="FFFFFF")
    HFILL = PatternFill("solid", fgColor="434343")
    WRAP  = Alignment(horizontal="left", vertical="top", wrap_text=True)
    CEN   = Alignment(horizontal="center")
    r = 1
    def _sub(t):
        nonlocal r
        ws.cell(r, 1, t).font = SUB; r += 1
    def _kv(k, v):
        nonlocal r
        ws.cell(r, 1, k).font = KEY; ws.cell(r, 2, v).font = DAT; r += 1
    def _hdr(cols):
        nonlocal r
        for i, h in enumerate(cols, 1):
            c = ws.cell(r, i, h); c.font = HDR; c.fill = HFILL; c.alignment = CEN
        r += 1

    ws.cell(r, 1, "Network Migration Assessment — Executive Summary").font = TITLE
    r += 2

    # --- migration brief (cross-axis synthesis) NEW-V3.23.120 ---
    eb = brief or {}
    if eb.get("axes"):
        _sub("Migration brief")
        ps = eb.get("posture_statement", "")
        if ps:
            c = ws.cell(r, 1, ps); c.font = Font(name="Calibri", bold=True, size=10, color="9C0006")
            c.alignment = WRAP; r += 1
        tg = eb.get("top_gating") or []
        if tg:
            ws.cell(r, 1, "Address first").font = KEY
            c = ws.cell(r, 2, " · ".join(tg[:6])); c.font = DAT; c.alignment = WRAP; r += 1
        _hdr(["Axis", "Severity", "Headline"])
        SEVFILL = {"Critical": "F4CCCC", "High": "FCE4D6", "Medium": "FFF2CC", "Low": "D9EAD3", "Info": "EFEFEF"}
        for a in eb["axes"]:
            ws.cell(r, 1, a.get("axis")).font = DAT
            sc = ws.cell(r, 2, a.get("severity")); sc.font = DAT
            sc.fill = PatternFill("solid", fgColor=SEVFILL.get(a.get("severity"), "FFFFFF"))
            hc = ws.cell(r, 3, a.get("headline")); hc.font = DAT; hc.alignment = WRAP
            r += 1
        r += 1

    # --- fleet posture (health band distribution) ---
    hs = health_scores or []
    n = len(hs)
    bands = {"Excellent": 0, "Good": 0, "Fair": 0, "Poor": 0, "Critical": 0}
    for x in hs:
        b = x.get("band", "")
        if b in bands:
            bands[b] += 1
    avg = round(sum((x.get("score") or 0) for x in hs) / n) if n else 0
    # SSOT (QA F1/F2): read the canonical executive_brief block every narrative surface uses -- the local
    # arithmetic mean overstates vs posture.avg_health (criticality-weighted), and "assessed = 303" overstates
    # coverage by the 50 not-collected devices vs scale.n_collected. Fall back to the local recompute only if
    # the brief is absent (legacy snapshot).
    _ebp = (brief or {}).get("posture") or {}
    _ebs = (brief or {}).get("scale") or {}
    _ncoll = _ebs.get("n_collected"); _avgc = _ebp.get("avg_health")
    _sub("Fleet posture")
    _kv("Switches collected / inventoried", f"{_ncoll if isinstance(_ncoll, int) else n} / {n}")
    _kv("Average health score", f"{_avgc if isinstance(_avgc, (int, float)) else avg} / 100")
    _kv("Critical band", bands["Critical"])
    _kv("Poor / Fair", bands["Poor"] + bands["Fair"])
    _kv("Good / Excellent", bands["Good"] + bands["Excellent"])
    r += 1

    # canonical scope/scale from the published brief (one source — not a raw-array recompute). The sheet
    # showed band counts but never the fleet scale (the endpoints / VLANs the other deliverables headline).
    _sc = eb.get("scale") or {}
    if _sc:
        _sub("Scope / scale")
        _kv("Devices inventoried", _sc.get("n_devices"))
        _kv("Endpoints (evidenced)", _sc.get("n_endpoints"))
        _kv("VLANs in use", _sc.get("n_vlans"))
        r += 1

    # --- punch-list severity / category breakdown ---
    pl = punchlist or []
    sev = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
    cats: Dict[str, int] = {}
    for it in pl:
        s = it.get("severity", "")
        if s in sev:
            sev[s] += 1
        cat = it.get("category", "Other")
        cats[cat] = cats.get(cat, 0) + 1
    _sub(f"Migration punch-list — {len(pl)} item(s)")
    _kv("Critical / High", f"{sev['Critical']} / {sev['High']}")
    _kv("Medium / Low", f"{sev['Medium']} / {sev['Low']}")
    top_cats = sorted(cats.items(), key=lambda t: -t[1])[:5]
    _kv("Top categories", ", ".join(f"{k} ({v})" for k, v in top_cats) or "—")
    r += 1

    # --- keystone devices (the few the fleet actually depends on; works when scores saturate) ---
    fi = failure_impact or []                          # NEW-V3.23.91: precomputed once in main
    _sub("Keystone devices — fix-first (by migration blast radius)")
    _hdr(["Rank", "Device", "Severity", "Endpoints stranded", "VLANs impacted"])
    for i, rec in enumerate(fi[:10], 1):
        ws.cell(r, 1, i).font = DAT
        ws.cell(r, 2, rec.get("host", "")).font = DAT
        ws.cell(r, 3, rec.get("severity", "")).font = DAT
        ws.cell(r, 4, rec.get("stranded", 0)).font = DAT
        ws.cell(r, 5, rec.get("vlans_impacted", 0)).font = DAT
        r += 1
    r += 1

    # --- per-group migration readiness ---
    mr = migration_readiness or []
    if mr:
        _sub("Migration readiness (per move group)")
        _hdr(["Group", "Verdict", "Switches", "Endpoints", "Fail", "Warn"])
        for g in mr:
            ws.cell(r, 1, g.get("group", "")).font = DAT
            ws.cell(r, 2, g.get("readiness", "")).font = DAT
            ws.cell(r, 3, len(g.get("switches", []) or [])).font = DAT
            ws.cell(r, 4, g.get("endpoints", 0)).font = DAT
            ws.cell(r, 5, g.get("n_fail", 0)).font = DAT
            ws.cell(r, 6, g.get("n_warn", 0)).font = DAT
            r += 1
        r += 1

    # --- headline: where to start ---
    _sub("Where to start")
    lines = []
    if fi:
        top = fi[0]
        lines.append(f"• {top.get('host')} is the top keystone — its loss strands "
                     f"{top.get('stranded', 0)} endpoint(s). Harden it first (FHRP / a redundant path).")
    if n and bands["Critical"] == n:
        lines.append(f"• All {n} switches land in the Critical band — the per-switch score is "
                     f"saturated, so prioritise by blast radius (above), not by score.")
    lines.append(f"• {sev['Critical']} critical + {sev['High']} high punch-list item(s) — see the "
                 f"'Migration Punch-List' tab for the full ranked, per-device action list.")
    for ln in lines:
        c = ws.cell(r, 1, ln); c.font = DAT; c.alignment = WRAP
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
        r += 1

    for i, w in enumerate([26, 30, 16, 20, 16, 12], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    # land the summary as the first tab in the workbook
    wb.move_sheet(ws, -wb.index(ws))
    logger.info(f"  [OK] '{EXEC_SUMMARY_SHEET_NAME}' sheet: {n} switch(es); "
                f"top keystone {fi[0]['host'] if fi else '-'}")


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
            oe = cnt.get("output_errors", "")            # output-side L1 (TX errors)
            lc = cnt.get("late_collisions", "")          # late collisions = duplex mismatch
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
            if oper_up and (_intpos(ie) or _intpos(crc) or _intpos(od) or _intpos(oe) or _intpos(lc)):
                flags.append("error-rate-high")
                if sev != "High": sev = "Medium"
            if not flags:
                flags = ["ok"]

            records.append({"switch": host, "port": port, "status": status or "",
                            "speed": speed or "unknown", "duplex": duplex or "unknown",
                            "media": media or "unknown", "input_errors": ie, "crc_errors": crc,
                            "output_errors": oe, "late_collisions": lc,
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


FLOW_PATHS_SHEET_NAME = "Flow Paths"


def write_flow_paths_sheet(wb, flow_paths: dict) -> None:
    """NEW-V3.23.126: the workbook twin of the explorer's Flow Simulator — representative end-to-end
    flow paths (one per consecutive-VLAN pair, lowest-IP endpoint each) with their L1-L3 hops, SPOFs
    and risk. From compute_flow_paths(). Pure presentation; the explorer remains the interactive view."""
    fp = flow_paths or {}
    flows = fp.get("flows") or []
    ws = wb.create_sheet(FLOW_PATHS_SHEET_NAME)
    bold = Font(bold=True)
    ws.cell(1, 1, "Representative Flow Paths").font = Font(bold=True, size=14, color="1F3864")
    s0 = fp.get("summary") or {}
    ws.cell(2, 1, f"{s0.get('n_flows', 0)} representative flow(s) · {s0.get('n_at_risk', 0)} at-risk "
                  f"(HIGH/CRITICAL) · {s0.get('n_partitioned', 0)} partitioned. Static twin of the explorer "
                  f"Flow Simulator: the lowest-IP endpoint per VLAN, traced L1-L3 end to end.").font = \
        Font(italic=True, size=9)
    r = 4
    if not flows:
        ws.cell(r, 1, "No endpoint IPs in scope to trace (endpoint identity empty).").font = bold
        for i, w in enumerate([5, 10, 18, 18, 16, 60, 7], 1):
            ws.column_dimensions[chr(64 + i)].width = w
        logger.info("  [OK] 'Flow Paths' sheet: 0 flow(s)")
        return
    headers = ["#", "Layer", "From", "To", "Interface", "Detail", "SPOF"]
    for flow in flows:
        s = flow["summary"]
        ws.cell(r, 1, flow["label"]).font = Font(bold=True, size=11, color="1F3864"); r += 1
        ws.cell(r, 1, "Verdict").font = bold
        vc = ws.cell(r, 2, f"{s.get('flow_type', '')} · risk {s.get('risk', '')}"
                           + (f" · SPOFs: {', '.join(s.get('spofs') or [])}" if s.get("spofs") else " · no SPOF"))
        if s.get("risk") in _RISK_FILL:
            vc.fill = PatternFill("solid", fgColor=_RISK_FILL[s["risk"]]); vc.font = bold
        r += 1
        for col, h in enumerate(headers, 1):
            hc = ws.cell(r, col, h); hc.font = Font(bold=True, color="FFFFFF")
            hc.fill = PatternFill("solid", fgColor="434343"); hc.alignment = Alignment(horizontal="center")
        r += 1
        for hop in flow["hops"]:
            vals = [hop["n"], hop["layer"], hop["from"], hop["to"], hop["iface"], hop["detail"],
                    "YES" if hop["spof"] else ""]
            for col, v in enumerate(vals, 1):
                hc = ws.cell(r, col, v)
                if hop["spof"]:
                    hc.fill = PatternFill("solid", fgColor="F4CCCC")
            r += 1
        r += 1
    for i, w in enumerate([5, 10, 18, 18, 16, 60, 7], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    logger.info(f"  [OK] 'Flow Paths' sheet: {len(flows)} flow(s), {s0.get('n_at_risk', 0)} at-risk")


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


# =============================================================================
# The main interface template filler (PHASE 2.7 step 26). Writes one row per
# physical port into the 'Migration Assessment' template sheet, matching existing
# host/port rows or appending. This produces the golden's interface sheet, so the
# logic is byte-exact. Uses find_header_row/ensure_headers/sortkey (above) + the
# template header map.
# =============================================================================
def append_interface_rows(ws, header_row: int, col_map: Dict[str,int],
                          hostname: str, interfaces: Dict[str, InterfaceData]):
    required_cols = [col_map["hostname"], col_map["port"], col_map["status"]]

    def row_is_writable(r):
        return not any(isinstance(ws.cell(row=r, column=c), MergedCell) for c in required_cols)

    existing_rows: Dict[Tuple[str,str],int] = {}
    for r in range(header_row+1, ws.max_row+1):
        if not row_is_writable(r): continue
        hv = ws.cell(row=r, column=col_map["hostname"]).value
        pv = ws.cell(row=r, column=col_map["port"]).value
        if hv and pv:
            existing_rows[(str(hv).strip(), normalize_ifname(str(pv).strip()))] = r

    def next_empty_row(start):
        r = start
        while True:
            if not row_is_writable(r): r += 1; continue
            if ws.cell(row=r, column=col_map["hostname"]).value not in (None,""): r += 1; continue
            return r

    append_row = next_empty_row(header_row+1)

    for port in sorted(interfaces.keys(), key=sortkey):
        d      = interfaces[port]
        norm_p = normalize_ifname(port)
        if norm_p.lower().startswith(("vlan","lo","loop","null","tunnel","mgmt0")): continue
        if port.strip().startswith("%"): continue
        if not PHYSICAL_IFACE_RE.match(norm_p):
            if not re.match(r"^(Fa|mgmt)\d", norm_p, re.IGNORECASE): continue

        key = (hostname, normalize_ifname(port))
        if key in existing_rows:
            row = existing_rows[key]
        else:
            row = next_empty_row(append_row)
            append_row = row + 1

        ws.cell(row=row, column=col_map["hostname"], value=hostname)
        ws.cell(row=row, column=col_map["port"],     value=d.port)
        ws.cell(row=row, column=col_map["status"],   value=d.status)

        def w(field, val):
            if field not in col_map: return
            cell = ws.cell(row=row, column=col_map[field])
            if isinstance(cell, MergedCell): return
            cell.value = val if val else (cell.value or None)

        def w_po(field, val):
            if field not in col_map: return
            cell = ws.cell(row=row, column=col_map[field])
            if isinstance(cell, MergedCell): return
            existing = str(cell.value or "").strip().lower()
            if existing in _TRUNK_STATUS_WORDS: cell.value = val if val else None
            else: cell.value = val if val else (cell.value or None)

        w("switchport_mode",      d.switchport_mode)
        w("vlan",                 d.vlan)
        w("vlan_name",            d.vlan_name)
        w("vrf",                  d.vrf)
        w("duplex",               d.duplex)
        w("speed",                d.speed)
        w("port_type",            d.port_type)
        w("link_type",            d.link_type)
        w("description",          d.description)
        w("end_host_mac",         d.end_host_mac)
        w("end_host_ip",          d.end_host_ip)
        w_po("port_channel",      d.port_channel)
        w("port_channel_protocol",d.port_channel_protocol)
        w("stp_blocked",          d.stp_blocked)
        w("stp_bpduguard",        d.stp_bpduguard)
        w("stp_rootguard",        d.stp_rootguard)
        w("poe_status",           d.poe_status)
        w("system_owner",         d.system_owner)
        w("endpoint_type",        d.endpoint_type)
        w("endpoint_location",    d.endpoint_location)
        w("dual_connection",      d.dual_connection)
        w("trunk_native_vlan",    d.trunk_native_vlan)
        w("trunk_allowed_vlans",  d.trunk_allowed_vlans)
        w("trunk_status",         d.trunk_status)
        w("arp_source_switch",    d.arp_source_switch)   # NEW-V11
        w("cdp_neighbor",         d.cdp_neighbor)        # NEW-V11
        # NEW-V14.2
        w("current_switch_serial",      d.current_switch_serial)
        w("current_switch_ip",          d.current_switch_ip)
        w("current_switch_vtp_domain",  d.current_switch_vtp_domain)
        w("neighbor_switch_serial",     d.neighbor_switch_serial)
        w("neighbor_switch_ip",         d.neighbor_switch_ip)
        w("neighbor_switch_vtp_domain", d.neighbor_switch_vtp_domain)
        w("subnet_primary_route",       d.subnet_primary_route)
        w("subnet_secondary_routes",    d.subnet_secondary_routes)
        w("route_next_hop",             d.route_next_hop)
        w("routing_source",             d.routing_source)
        w("hsrp_behavior",              d.hsrp_behavior)
        w("multicast_info",             d.multicast_info)
