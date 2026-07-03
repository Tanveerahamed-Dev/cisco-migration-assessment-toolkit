"""The data model - the two record dataclasses every layer passes around.
Leaf layer: depends only on `dataclasses` (no project imports, no I/O). Extracted
verbatim from COLLECT_PARSE_V3_23_0.py in PHASE 2.7 step 9 (behaviour
byte-identical). `InterfaceData` is the per-port record; `DevicePhysical` is the
per-switch physical inventory record. The scoring tunables (`ScoringConfig`) stay
with the analyze layer - they are not part of the passed-around data model."""
import enum
from dataclasses import dataclass, fields


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
    # NEW-V3.23.49 (path-MTU mismatch): interface MTU from run-config (blank = default ~1500); jumbo-frame detection
    mtu: str = ""
    # NEW (DHCP-relay reachability): 'ip helper-address' / 'ip dhcp relay address' targets on this SVI/L3
    # interface (comma-joined; blank = no relay). Lets the explorer flag client subnets whose gateway has no
    # relay, or whose relay server isn't routable from the gateway (a classic silent post-cutover black-hole).
    dhcp_helpers: str = ""

    @classmethod
    def from_sparse(cls, d) -> "InterfaceData":
        """Rehydrate a possibly-sparse interface record: unknown / legacy keys are dropped, and any
        field the sparse encoder OMITTED (because it equalled the '' default) is restored to that
        default. Lossless inverse of html.sparsify_interfaces for any record dataclasses.asdict()
        produced -- the one decode SSOT the --compare delta and the webapp endpoint both go through."""
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (d or {}).items() if k in known})


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
    active_ports: int | None = None   # None = port up/down state NOT observed (distinct from a real 0)
    fan_status: str = ""
    temperature_status: str = ""
    # NEW-V3.23.68: the device's OWN configured hostname (from 'show version' "<host> uptime is").
    # Compared against `hostname` (the inventory/collection key) to flag inventory typos that
    # otherwise surface as a phantom split node in the topology (e.g. 'AS08--' vs real 'AS08-').
    reported_hostname: str = ""


# =============================================================================
# VERDICT ADT - abstention as a TYPE, not a per-module string convention
# =============================================================================
class Verdict(str, enum.Enum):
    """A four-way outcome for any verify / abstention surface. str-mixin, so
    ``json.dumps(Verdict.PROVEN) == '"proven"'`` -- a Verdict-typed field written into a
    snapshot dict is byte-identical to the hand-written string it replaces (purely additive,
    never a serialization change). Generalizes the coverage-honest ``active_ports: int | None``
    idiom above: NOT_OBSERVED is a distinct value, never silently a pass."""
    PROVEN = "proven"                 # affirmatively demonstrated from collected evidence
    REFUTED = "refuted"               # affirmatively disproven (a definitive negative)
    NOT_OBSERVED = "not_observed"     # a blind spot -- never silently a pass (the coverage-honest core)
    INDETERMINATE = "indeterminate"   # evidence present but insufficient to decide

    # A bare `str, Enum` inherits Enum.__str__/__format__ -> "Verdict.PROVEN"; override them to the str value
    # ("proven") so str() / f-string / %s all match the .value / json.dumps paths -- keeping a RAW member
    # interchangeable with the hand-written string everywhere, so a future surface that interpolates a Verdict
    # into a snapshot string / Excel cell / HTML can't silently emit "Verdict.PROVEN". (Explicit defs, not
    # `__str__ = str.__str__`, so the self-type matches the Enum override signature under mypy.)
    def __str__(self) -> str:
        return str.__str__(self)

    def __format__(self, format_spec: str) -> str:
        return str.__format__(self, format_spec)

    @classmethod
    def from_acl_reason(cls, reason: str) -> "Verdict":
        """Map an aclcheck finding ``reason`` to a Verdict: a dead / unmatchable line is REFUTED
        (its reachability is disproven), while a bad-reference / stateful / fragmented / overlap
        case is INDETERMINATE (cannot decide). A REACHABLE line emits no finding, so it never
        reaches here -- absence of a finding is the implicit PROVEN-reachable case."""
        if (reason or "").upper() in ("BLOCKING_LINES", "INDEPENDENTLY_UNMATCHABLE"):
            return cls.REFUTED
        return cls.INDETERMINATE


@dataclass(frozen=True)
class Judgment:
    """An optional evidence-carrying wrapper around a Verdict (additive; nothing must adopt it
    yet). Lets a future verify surface attach its grounding -- the native reason token + a
    snapshot / computed-path citation -- beside the typed verdict, in one audited place."""
    verdict: Verdict
    reason: str = ""       # the surface's native token, e.g. "BLOCKING_LINES"
    citation: str = ""     # snapshot path / computed-path grounding
    detail: str = ""
