"""The data model - the two record dataclasses every layer passes around.
Leaf layer: depends only on `dataclasses` (no project imports, no I/O). Extracted
verbatim from COLLECT_PARSE_V3_23_0.py in PHASE 2.7 step 9 (behaviour
byte-identical). `InterfaceData` is the per-port record; `DevicePhysical` is the
per-switch physical inventory record. The scoring tunables (`ScoringConfig`) stay
with the analyze layer - they are not part of the passed-around data model."""
from dataclasses import dataclass


# =============================================================================
# DATA MODEL - InterfaceData
# =============================================================================
@dataclass
class InterfaceData:
    port: str = ""
    status: str = ""
    switchport_mode: str = ""
    vlan: str = ""
    vlan_name: str = ""
    vrf: str = ""
    duplex: str = ""
    speed: str = ""
    port_type: str = ""
    link_type: str = ""
    description: str = ""
    end_host_mac: str = ""
    end_host_ip: str = ""
    port_channel: str = ""
    port_channel_protocol: str = ""
    stp_blocked: str = ""
    stp_bpduguard: str = ""
    stp_rootguard: str = ""
    poe_status: str = ""
    system_owner: str = ""
    endpoint_type: str = ""
    endpoint_location: str = ""
    dual_connection: str = ""
    trunk_native_vlan: str = ""
    trunk_allowed_vlans: str = ""
    trunk_status: str = ""
    arp_source_switch: str = ""  # NEW-V11
    cdp_neighbor: str = ""       # NEW-V11
    # NEW-V14 (defined in V3.14.2; previously read/written but missing from the model)
    current_switch_serial: str = ""
    current_switch_ip: str = ""
    current_switch_vtp_domain: str = ""
    neighbor_switch_serial: str = ""
    neighbor_switch_ip: str = ""
    neighbor_switch_vtp_domain: str = ""
    subnet_primary_route: str = ""
    subnet_secondary_routes: str = ""
    route_next_hop: str = ""
    routing_source: str = ""
    hsrp_behavior: str = ""
    multicast_info: str = ""
    svi_ip: str = ""  # NEW-V14.3 (the SVI's own 'ip address' = gateway IP; for SVI/Gateway sheet)
    # NEW-V14.7 per-VLAN STP detail (compressed VLAN/instance ranges) for the STP Detail sheet
    stp_fwd_vlans: str = ""
    stp_blk_vlans: str = ""
    stp_other_vlans: str = ""
    # NEW-V14.10 neighbor remote port + platform (for the Topology / Links sheet)
    neighbor_port: str = ""
    neighbor_platform: str = ""
    # NEW-V3.23.x (L4/ACL flagging): ACL name applied to this interface/SVI (from run-config 'ip access-group')
    acl_in: str = ""
    acl_out: str = ""


# =============================================================================
# DATA MODEL - DevicePhysical (NEW-V12)
# =============================================================================
@dataclass
class DevicePhysical:
    """Switch-level physical inventory for site survey sheet."""
    hostname: str = ""
    platform: str = ""
    model: str = ""
    serial_number: str = ""
    chassis_serial: str = ""
    sw_version: str = ""
    uptime: str = ""
    system_mac: str = ""
    num_power_supplies: int = 0
    ps_status: str = ""
    power_capacity_w: str = ""
    power_drawn_w: str = ""
    power_remaining_w: str = ""
    num_modules: int = 0
    total_ports: int = 0
    active_ports: int = 0
    fan_status: str = ""
    temperature_status: str = ""
