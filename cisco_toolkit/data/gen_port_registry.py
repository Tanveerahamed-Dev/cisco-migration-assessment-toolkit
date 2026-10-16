"""Regenerate the shipped offline port/protocol/multicast registry.

Builds `data/port_registry.tsv.gz` consumed by `cisco_toolkit.portdb`. Run once, rarely:

    python -m cisco_toolkit.data.gen_port_registry            # retained IANA + overlay
    python -m cisco_toolkit.data.gen_port_registry --offline --out /tmp/overlay.tsv.gz \
        --allow-overlay-only

The registry has two record kinds, distinguished by the ``proto`` column. Both
use the v2 twelve-column schema documented by ``cisco_toolkit.portdb``.

Authority is intentionally split:
  * IANA Service Name and Transport Protocol Port Number Registry (RFC 6335) -- the long tail.
    Its first retained row is the primary label and every additional official
    alias is preserved in source order.
  * a non-authoritative broadcast/AV + OT/ICS + IT-infra overlay. It can add
    explicitly labelled semantics, but never replaces an official IANA label.
  * a non-authoritative curated IPv4 multicast table containing only bounded,
    defensible scopes; no generic 232/8 or 239/8 AV/on-air inference.

The authoritative generator is no-egress: it verifies and reads the exact
hash-pinned official IANA CSV retained under ``reference-data``. The shipped
``.tsv.gz`` is fully offline at runtime."""
import argparse
import csv
import gzip
import ipaddress
import io
import json
import os
import re
import sys

from cisco_toolkit.registry_integrity import (
    PackIntegrityError,
    SOURCE_INVENTORY_RELATIVE_PATH,
    enforce_non_regression,
    load_retained_source,
    metadata_for_bytes,
    paths_refer_to_same_file,
    publish_pack_and_manifest,
)

_HERE = os.path.dirname(os.path.abspath(__file__))
_OUT = os.path.join(_HERE, "port_registry.tsv.gz")
_IANA_URL = ("https://www.iana.org/assignments/service-names-port-numbers/"
             "service-names-port-numbers.csv")
_IANA_HEADER = (
    "Service Name",
    "Port Number",
    "Transport Protocol",
    "Description",
    "Assignee",
    "Contact",
    "Registration Date",
    "Modification Date",
    "Reference",
    "Service Code",
    "Unauthorized Use Reported",
    "Assignment Notes",
)
_MINIMUM_PORT_RETAINED_RATIO = 0.95
_MINIMUM_MULTICAST_COUNT = 21

# --- curated port overlay: (port, proto-or-'both') -> (service, category, broadcast, note) ----------
# broadcast=1 marks ports central to broadcast / pro-AV / media-over-IP fabrics (the Meridian goldmine).
_OVERLAY = {
    # ---- Routing / control-plane ----
    (179, "tcp"): ("BGP", "Routing", 0, "Border Gateway Protocol peering"),
    (646, "both"): ("LDP", "Routing", 0, "MPLS Label Distribution Protocol"),
    (3784, "udp"): ("BFD-control", "Routing", 0, "Bidirectional Forwarding Detection control"),
    (3785, "udp"): ("BFD-echo", "Routing", 0, "Bidirectional Forwarding Detection echo"),
    (4784, "udp"): ("BFD-multihop", "Routing", 0, "BFD multihop control"),
    (520, "udp"): ("RIP", "Routing", 0, "Routing Information Protocol v1/v2"),
    (521, "udp"): ("RIPng", "Routing", 0, "RIP next generation (IPv6)"),
    (1985, "udp"): ("HSRP", "FHRP", 0, "Cisco Hot Standby Router Protocol (v1)"),
    (3222, "both"): ("GLBP", "FHRP", 0, "Cisco Gateway Load Balancing Protocol"),
    # ---- Management / AAA / infra ----
    (22, "tcp"): ("SSH", "Management", 0, "Secure Shell device admin"),
    (23, "tcp"): ("Telnet", "Management", 0, "Cleartext device admin (legacy)"),
    (161, "udp"): ("SNMP", "Management", 0, "SNMP polling"),
    (162, "udp"): ("SNMP-trap", "Management", 0, "SNMP traps/informs"),
    (514, "udp"): ("syslog", "Management", 0, "Syslog"),
    (123, "udp"): ("NTP", "Management", 0, "Network Time Protocol"),
    (49, "tcp"): ("TACACS+", "Management", 0, "Cisco TACACS+ AAA"),
    (1812, "udp"): ("RADIUS-auth", "Management", 0, "RADIUS authentication"),
    (1813, "udp"): ("RADIUS-acct", "Management", 0, "RADIUS accounting"),
    (53, "both"): ("DNS", "Infra", 0, "Domain Name System"),
    (67, "udp"): ("DHCP-server", "Infra", 0, "DHCP/BOOTP server (relay target)"),
    (68, "udp"): ("DHCP-client", "Infra", 0, "DHCP/BOOTP client"),
    (69, "udp"): ("TFTP", "Infra", 0, "Trivial FTP (image/config transfer)"),
    (80, "tcp"): ("HTTP", "Web", 0, "Web / device GUI"),
    (443, "tcp"): ("HTTPS", "Web", 0, "TLS web / device GUI / REST/NETCONF-over-TLS"),
    (830, "tcp"): ("NETCONF", "Management", 0, "NETCONF over SSH"),
    # ---- Discovery ----
    (5353, "udp"): ("mDNS", "Discovery", 1, "Multicast DNS (Bonjour) - Dante/NDI/AV discovery"),
    (1900, "udp"): ("SSDP", "Discovery", 0, "UPnP Simple Service Discovery"),
    (5355, "udp"): ("LLMNR", "Discovery", 0, "Link-Local Multicast Name Resolution"),
    # ---- File / storage / database ----
    (445, "tcp"): ("SMB", "Storage", 0, "SMB/CIFS file sharing"),
    (2049, "both"): ("NFS", "Storage", 0, "Network File System"),
    (3260, "tcp"): ("iSCSI", "Storage", 0, "iSCSI target (block storage)"),
    (111, "both"): ("portmapper", "Storage", 0, "RPC portmapper (NFS/NIS)"),
    (1433, "tcp"): ("MS-SQL", "Database", 0, "Microsoft SQL Server"),
    (1521, "tcp"): ("Oracle", "Database", 0, "Oracle DB listener"),
    (3306, "tcp"): ("MySQL", "Database", 0, "MySQL/MariaDB"),
    (5432, "tcp"): ("PostgreSQL", "Database", 0, "PostgreSQL"),
    (6379, "tcp"): ("Redis", "Database", 0, "Redis"),
    (27017, "tcp"): ("MongoDB", "Database", 0, "MongoDB"),
    # ---- Directory / remote access ----
    (389, "tcp"): ("LDAP", "Management", 0, "LDAP directory"),
    (636, "tcp"): ("LDAPS", "Management", 0, "LDAP over TLS"),
    (88, "both"): ("Kerberos", "Management", 0, "Kerberos authentication"),
    (3389, "tcp"): ("RDP", "RemoteAccess", 0, "Microsoft Remote Desktop"),
    (5900, "tcp"): ("VNC", "RemoteAccess", 0, "VNC remote framebuffer"),
    # ---- Voice / collaboration ----
    (5060, "both"): ("SIP", "Voice", 0, "SIP signalling"),
    (5061, "tcp"): ("SIP-TLS", "Voice", 0, "SIP over TLS"),
    (2000, "tcp"): ("SCCP", "Voice", 0, "Cisco Skinny call control"),
    # ---- Broadcast / pro-AV / media-over-IP (the differentiator) ----
    (319, "udp"): ("PTP-event", "Broadcast-AV", 1, "IEEE 1588 PTP event (sync/delay) - ST2110/AES67/Dante"),
    (320, "udp"): ("PTP-general", "Broadcast-AV", 1, "IEEE 1588 PTP general (announce/follow-up)"),
    (5004, "udp"): ("RTP-media", "Broadcast-AV", 1, "RTP media (SMPTE ST 2110 / AES67 default)"),
    (5005, "udp"): ("RTCP-media", "Broadcast-AV", 1, "RTCP control for ST 2110 / AES67"),
    (554, "both"): ("RTSP", "Broadcast-AV", 1, "Real Time Streaming Protocol"),
    (4440, "udp"): ("Dante-audio", "Broadcast-AV", 1, "Audinate Dante audio routing (unicast)"),
    (4444, "udp"): ("Dante-audio", "Broadcast-AV", 1, "Audinate Dante audio routing"),
    (4455, "udp"): ("Dante-audio", "Broadcast-AV", 1, "Audinate Dante audio routing"),
    (8700, "udp"): ("Dante-ctrl", "Broadcast-AV", 1, "Dante control & monitoring"),
    (8751, "udp"): ("Dante-ctrl", "Broadcast-AV", 1, "Dante Controller metering"),
    (8800, "udp"): ("Dante-ctrl", "Broadcast-AV", 1, "Dante control & monitoring (unicast)"),
    (5959, "tcp"): ("NDI-discovery", "Broadcast-AV", 1, "NDI Discovery Server"),
    (5960, "both"): ("NDI-query", "Broadcast-AV", 1, "NDI source query / reliable-UDP base"),
    (5961, "tcp"): ("NDI-stream", "Broadcast-AV", 1, "NDI stream connection (base; 5961+)"),
    (6960, "both"): ("NDI-multi", "Broadcast-AV", 1, "NDI multi-TCP / UDP receive (6960+)"),
    (7960, "both"): ("NDI-send", "Broadcast-AV", 1, "NDI multi-TCP / unicast+multicast send (7960+)"),
    (1935, "tcp"): ("RTMP", "Broadcast-AV", 1, "Real-Time Messaging Protocol (Flash/contribution)"),
    (3478, "both"): ("STUN/WebRTC", "Broadcast-AV", 0, "STUN/TURN (WebRTC contribution)"),
    # ---- OT / ICS / building (broadcast plants carry these too) ----
    (502, "tcp"): ("Modbus", "OT-ICS", 0, "Modbus/TCP industrial control"),
    (20000, "tcp"): ("DNP3", "OT-ICS", 0, "DNP3 SCADA"),
    (47808, "udp"): ("BACnet", "OT-ICS", 0, "BACnet/IP building automation"),
    (44818, "tcp"): ("EtherNet/IP", "OT-ICS", 0, "EtherNet/IP (CIP) explicit messaging"),
    (2222, "udp"): ("EtherNet/IP-IO", "OT-ICS", 0, "EtherNet/IP implicit I/O"),
    (4840, "tcp"): ("OPC-UA", "OT-ICS", 0, "OPC Unified Architecture"),
    (102, "tcp"): ("S7comm", "OT-ICS", 0, "Siemens S7 / ISO-on-TCP"),
}

# These three reviewed collisions were the concrete fail-open case: the local
# overlay called the ports Dante while IANA assigns other services. Preserve
# the IANA primary/aliases and disclose the conflicting overlay label, but do
# not apply its AV category/broadcast inference.
_SUPPRESSED_OVERLAY_CONFLICTS = {
    (4444, "udp"): ("krb524", "nv-video"),
    (4455, "udp"): ("prchat-user",),
    (8800, "udp"): ("sunwebadmin",),
}

# --- curated reserved/well-known IPv4 multicast table: cidr -> (name, category, broadcast, note) -----
_MCAST = {
    "224.0.0.0/24": ("Local Network Control", "Routing", 0, "link-local control (TTL 1, not routed)"),
    "224.0.0.1/32": ("all-hosts", "Routing", 0, "all systems on this subnet"),
    "224.0.0.2/32": ("all-routers", "Routing", 0, "all routers on this subnet"),
    "224.0.0.5/32": ("OSPF-AllSPF", "Routing", 0, "OSPF all SPF routers"),
    "224.0.0.6/32": ("OSPF-AllDR", "Routing", 0, "OSPF designated routers"),
    "224.0.0.9/32": ("RIPv2", "Routing", 0, "RIP version 2"),
    "224.0.0.10/32": ("EIGRP", "Routing", 0, "Cisco EIGRP"),
    "224.0.0.13/32": ("PIM", "Routing", 0, "PIM all routers"),
    "224.0.0.18/32": ("VRRP", "FHRP", 0, "Virtual Router Redundancy Protocol"),
    "224.0.0.22/32": ("IGMPv3", "Routing", 0, "IGMPv3 membership reports"),
    "224.0.0.102/32": ("HSRPv2/GLBP", "FHRP", 0, "HSRPv2 and GLBP hellos"),
    "224.0.0.251/32": ("mDNS", "Discovery", 1, "multicast DNS (Bonjour) - AV discovery"),
    "224.0.0.252/32": ("LLMNR", "Discovery", 0, "link-local name resolution"),
    "224.0.1.0/24": ("Internetwork Control", "Infra", 0, "routed control block"),
    "224.0.1.1/32": ("NTP", "Management", 0, "Network Time Protocol multicast"),
    "224.0.1.129/32": ("PTP-primary", "Broadcast-AV", 1, "IEEE 1588 PTP (default/event domain)"),
    "224.0.1.130/32": ("PTP-alt1", "Broadcast-AV", 1, "IEEE 1588 PTP alternate"),
    "224.0.1.131/32": ("PTP-alt2", "Broadcast-AV", 1, "IEEE 1588 PTP alternate"),
    "224.0.1.132/32": ("PTP-alt3", "Broadcast-AV", 1, "IEEE 1588 PTP alternate"),
    "233.0.0.0/8": ("GLOP", "Infra", 0, "AS-derived global multicast"),
    "239.255.255.250/32": ("SSDP", "Discovery", 0, "UPnP/SSDP discovery"),
}


def _parse_iana_csv(text: str) -> tuple[dict, dict]:
    """Parse one verified IANA CSV and preserve every duplicate-key alias."""

    rows: dict = {}
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    header = next(reader, None)
    if not isinstance(header, list) or tuple(header) != _IANA_HEADER:
        raise ValueError("IANA CSV header/schema is unsupported")
    source_rows = 0
    for row in reader:
        if not row or not any(str(cell).strip() for cell in row):
            continue
        source_rows += 1
        if len(row) != len(_IANA_HEADER):
            raise ValueError("IANA CSV contains a truncated or extended row")
        name = row[0].strip()
        port = row[1].strip()
        proto = row[2].strip().lower()
        desc = row[3].strip()
        if not re.fullmatch(r"\d+", port) or proto not in (
            "tcp",
            "udp",
            "sctp",
            "dccp",
        ):
            continue
        port_number = int(port)
        if not 0 <= port_number <= 65535:
            raise ValueError(f"IANA CSV contains an out-of-range port: {port}")
        svc = name or (desc[:24] if desc else "")
        if not svc:
            continue
        note = re.sub(r"\s+", " ", desc)[:90]
        rows.setdefault((port_number, proto), []).append((svc, note))

    duplicate_keys = {
        key: records for key, records in rows.items() if len(records) > 1
    }
    return rows, {
        "source_row_count": source_rows,
        "iana_source_record_count": sum(len(records) for records in rows.values()),
        "iana_assignment_count": len(rows),
        "iana_duplicate_key_count": len(duplicate_keys),
        "iana_alias_record_count": sum(
            len(records) - 1 for records in duplicate_keys.values()
        ),
        "iana_max_records_per_key": max(
            (len(records) for records in rows.values()), default=0
        ),
    }


def _expand(proto: str):
    return ("tcp", "udp") if proto == "both" else (proto,)


def build(
    offline: bool = False,
    *,
    out_path: str | None = None,
    allow_overlay_only: bool = False,
    repository_root: str | os.PathLike[str] | None = None,
    inventory_path: str | os.PathLike[str] | None = None,
) -> int:
    """Build a registry without ever replacing the authoritative pack on degraded input."""

    destination = os.path.abspath(out_path or _OUT)
    # key (port:int, proto:str) -> explicitly source-labelled record
    rows: dict = {}
    source_artifact: dict | None = None
    generated_at: str | None = None
    iana_stats = {
        "source_row_count": 0,
        "iana_source_record_count": 0,
        "iana_assignment_count": 0,
        "iana_duplicate_key_count": 0,
        "iana_alias_record_count": 0,
        "iana_max_records_per_key": 0,
    }

    if not offline:
        try:
            _, text, source_artifact = load_retained_source(
                "iana-service-names-port-numbers",
                repository_root=repository_root,
                inventory_path=inventory_path,
            )
            iana_rows, iana_stats = _parse_iana_csv(text)
            if iana_stats["source_row_count"] != source_artifact["record_count"]:
                raise ValueError(
                    "IANA parsed row count does not match the retained-source contract"
                )
            for key, official_records in iana_rows.items():
                primary_service, primary_note = official_records[0]
                rows[key] = {
                    "service": primary_service,
                    "alias_records": [
                        [service, note]
                        for service, note in official_records[1:]
                    ],
                    "category": "",
                    "broadcast": 0,
                    "note": primary_note,
                    "assignment_source": "iana",
                    "semantics_source": "iana",
                    "overlay_service": "",
                    "overlay_note": "",
                    "overlay_status": "none",
                }
            generated_at = source_artifact["retrieved_at"]
        except Exception as exc:
            raise RuntimeError(
                "IANA retained-source verification/parse failed; authoritative "
                "registry was not modified: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
    elif not allow_overlay_only:
        raise ValueError(
            "overlay-only generation requires --allow-overlay-only and a non-authoritative --out path"
        )
    elif paths_refer_to_same_file(destination, _OUT):
        raise ValueError("refusing to replace the authoritative registry with overlay-only data")

    overlay_enriched_iana_count = 0
    overlay_only_port_count = 0
    overlay_conflict_count = 0
    for (oport, oproto), (svc, cat, bc, note) in _OVERLAY.items():
        for p in _expand(oproto):
            key = (oport, p)
            if key not in rows:
                rows[key] = {
                    "service": svc,
                    "alias_records": [],
                    "category": cat,
                    "broadcast": int(bc),
                    "note": note,
                    "assignment_source": "curated-overlay",
                    "semantics_source": "curated-overlay",
                    "overlay_service": svc,
                    "overlay_note": note,
                    "overlay_status": "overlay-only",
                }
                overlay_only_port_count += 1
                continue

            record = rows[key]
            record["overlay_service"] = svc
            record["overlay_note"] = note
            expected_official = _SUPPRESSED_OVERLAY_CONFLICTS.get(key)
            if expected_official is not None:
                actual_official = tuple(
                    [record["service"]]
                    + [alias[0] for alias in record["alias_records"]]
                )
                if actual_official != expected_official:
                    raise ValueError(
                        f"IANA assignment changed for reviewed overlay conflict {key!r}: "
                        f"{actual_official!r}"
                    )
                record["overlay_status"] = "conflict-suppressed"
                overlay_conflict_count += 1
                continue

            # The curated semantics remain separately labelled and never
            # replace the official primary service, aliases, or description.
            record["category"] = cat
            record["broadcast"] = int(bc)
            record["semantics_source"] = "curated-overlay"
            record["overlay_status"] = "supplemental"
            overlay_enriched_iana_count += 1

    for (port, proto), record in rows.items():
        service = record["service"]
        category = record["category"]
        broadcast = record["broadcast"]
        note = record["note"]
        aliases = record["alias_records"]
        string_fields = (
            service,
            category,
            note,
            record["assignment_source"],
            record["semantics_source"],
            record["overlay_service"],
            record["overlay_note"],
            record["overlay_status"],
        )
        if (
            type(port) is not int
            or not 0 <= port <= 65535
            or proto not in ("tcp", "udp", "sctp", "dccp")
            or not isinstance(service, str)
            or not service.strip()
            or broadcast not in (0, 1)
            or any(not isinstance(value, str) for value in string_fields)
            or any(
                any(ord(char) < 32 or ord(char) == 127 for char in value)
                for value in string_fields
            )
            or not isinstance(aliases, list)
            or any(
                not isinstance(alias, list)
                or len(alias) != 2
                or any(not isinstance(value, str) for value in alias)
                or not alias[0]
                or any(
                    any(ord(char) < 32 or ord(char) == 127 for char in value)
                    for value in alias
                )
                for alias in aliases
            )
        ):
            raise ValueError(f"invalid generated port record: {(port, proto)!r}")

    lines = [
        "\t".join(
            (
                str(port),
                proto,
                record["service"],
                json.dumps(
                    record["alias_records"],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                record["category"],
                str(record["broadcast"]),
                record["note"],
                record["assignment_source"],
                record["semantics_source"],
                record["overlay_service"],
                record["overlay_note"],
                record["overlay_status"],
            )
        )
        for (port, proto), record in sorted(rows.items())
    ]
    # multicast records (proto column = 'mcast', port column = cidr)
    for cidr, (name, cat, bc, note) in sorted(_MCAST.items()):
        try:
            network = ipaddress.ip_network(cidr, strict=True)
        except ValueError as exc:
            raise ValueError(f"invalid generated multicast record: {cidr!r}") from exc
        if (
            not isinstance(network, ipaddress.IPv4Network)
            or not network.network_address.is_multicast
            or not name.strip()
            or bc not in (0, 1)
            or any(
                any(ord(char) < 32 or ord(char) == 127 for char in value)
                for value in (name, cat, note)
            )
        ):
            raise ValueError(f"invalid generated multicast record: {cidr!r}")
        lines.append(
            "\t".join(
                (
                    cidr,
                    "mcast",
                    name,
                    "[]",
                    cat,
                    str(int(bc)),
                    note,
                    "curated-multicast",
                    "curated-multicast",
                    name,
                    note,
                    "curated-only",
                )
            )
        )

    if not offline:
        try:
            enforce_non_regression(
                {"port_count": len(rows), "multicast_count": len(_MCAST)},
                baseline_pack_path=_OUT,
                minimum_ratios={
                    "port_count": _MINIMUM_PORT_RETAINED_RATIO,
                    # Four broad AV/on-air claims were intentionally removed
                    # from the previous 25-row pack. The absolute floor below
                    # keeps that reviewed reduction from weakening later runs.
                    "multicast_count": 0.84,
                },
            )
        except PackIntegrityError as exc:
            raise RuntimeError(
                f"IANA source failed the current-manifest non-regression contract; "
                f"authoritative registry was not modified: {exc}"
            ) from exc
    if len(_MCAST) < _MINIMUM_MULTICAST_COUNT:
        raise RuntimeError(
            "curated multicast table fell below its reviewed absolute floor"
        )

    payload = ("\n".join(lines) + "\n").encode("utf-8")
    compressed = gzip.compress(payload, compresslevel=9, mtime=0)

    entry = metadata_for_bytes(
        compressed,
        source={
            "name": (
                "IANA Service Name and Transport Protocol Port Number Registry; "
                "repository-curated overlay is separately labelled non-authoritative"
                if not offline
                else "repository-curated overlay only"
            ),
            "inventory": (
                SOURCE_INVENTORY_RELATIVE_PATH if not offline else None
            ),
            "inventory_schema_version": 1 if not offline else None,
            "artifacts": [source_artifact] if source_artifact is not None else [],
        },
        generator="cisco_toolkit.data.gen_port_registry",
        provenance_status=(
            "generated-from-retained-iana-primary-source"
            if not offline
            else "overlay-only-non-authoritative"
        ),
        generated_at=generated_at,
        extra={
            "port_schema_version": 2,
            "port_count": len(rows),
            "multicast_count": len(_MCAST),
            **iana_stats,
            "overlay_expanded_count": sum(
                len(tuple(_expand(proto))) for _, proto in _OVERLAY
            ),
            "overlay_enriched_iana_count": overlay_enriched_iana_count,
            "overlay_only_port_count": overlay_only_port_count,
            "overlay_conflict_count": overlay_conflict_count,
            "authority_scope": (
                "iana-service-assignments-only"
                if not offline
                else "curated-overlay-non-authoritative"
            ),
            "alias_selection_policy": (
                "first retained IANA CSV row is primary; every subsequent "
                "row is preserved in source order"
            ),
            "curated_overlay_authoritative": False,
            "curated_multicast_authoritative": False,
        },
    )
    publish_pack_and_manifest(destination, compressed, entry)
    print(f"wrote {destination}: {len(rows)} port records + {len(_MCAST)} multicast records "
          f"({len(compressed)} bytes)")
    return len(rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="build only the curated overlay")
    parser.add_argument("--out", default=_OUT, help="destination registry path")
    parser.add_argument(
        "--allow-overlay-only",
        action="store_true",
        help="acknowledge that an offline output is incomplete and non-authoritative",
    )
    parser.add_argument(
        "--repository-root",
        default=None,
        help="repository root containing retained official source bytes",
    )
    parser.add_argument(
        "--inventory",
        default=None,
        help="optional official-source inventory path (primarily for verification tests)",
    )
    args = parser.parse_args(argv)
    try:
        build(
            offline=args.offline,
            out_path=args.out,
            allow_overlay_only=args.allow_overlay_only,
            repository_root=args.repository_root,
            inventory_path=args.inventory,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
