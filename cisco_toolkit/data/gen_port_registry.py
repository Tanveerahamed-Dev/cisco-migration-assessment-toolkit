"""Regenerate the shipped offline port/protocol/multicast registry  (NEW-V3.23.99).

Builds `data/port_registry.tsv.gz` consumed by `cisco_toolkit.portdb`. Run once, rarely:

    python -m cisco_toolkit.data.gen_port_registry            # fetch IANA + merge overlay
    python -m cisco_toolkit.data.gen_port_registry --offline  # curated overlay only (no network)

The registry has two record kinds, distinguished by the `proto` column:
  * port records :  port<TAB>proto<TAB>service<TAB>category<TAB>broadcast<TAB>note   (proto = tcp/udp/sctp/dccp)
  * mcast records:  cidr<TAB>mcast<TAB>group_name<TAB>category<TAB>broadcast<TAB>note (proto = "mcast")

Sources merged (overlay wins for category/broadcast/note, and may relabel the service):
  * IANA Service Name and Transport Protocol Port Number Registry (RFC 6335) -- the long tail.
  * a curated broadcast/AV + OT/ICS + IT-infra overlay -- the high-signal semantics IANA lacks
    (Dante, AES67, SMPTE ST 2110, NDI, NMOS, PTP, Modbus, DNP3, BACnet, OPC-UA, iSCSI, ...).
  * a curated reserved/well-known IPv4 multicast group table.

Pure stdlib (urllib + csv + gzip). The shipped .tsv.gz is fully offline at run time."""
import csv
import gzip
import io
import os
import re
import ssl
import sys
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
_OUT = os.path.join(_HERE, "port_registry.tsv.gz")
_IANA_URL = ("https://www.iana.org/assignments/service-names-port-numbers/"
             "service-names-port-numbers.csv")

# --- curated port overlay: (port, proto-or-'both') -> (service, category, broadcast, note) ----------
# broadcast=1 marks ports central to broadcast / pro-AV / media-over-IP fabrics (the AJ goldmine).
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
    "224.2.0.0/16": ("SAP/SDP", "Broadcast-AV", 1, "session announcement (SDP) - ST2110 advertise"),
    "232.0.0.0/8": ("SSM", "Broadcast-AV", 1, "source-specific multicast (ST 2110 common)"),
    "233.0.0.0/8": ("GLOP", "Infra", 0, "AS-derived global multicast"),
    "239.0.0.0/8": ("admin-scoped", "Broadcast-AV", 1, "organization-local scope (private multicast)"),
    "239.254.0.0/16": ("Dante", "Broadcast-AV", 1, "Audinate Dante default clock/audio scope"),
    "239.255.255.250/32": ("SSDP", "Discovery", 0, "UPnP/SSDP discovery"),
}


def _fetch_iana() -> str:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(_IANA_URL, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=60, context=ctx).read().decode("utf-8", "replace")


def _expand(proto: str):
    return ("tcp", "udp") if proto == "both" else (proto,)


def build(offline: bool = False) -> int:
    # key (port:int, proto:str) -> [service, category, broadcast, note]
    rows: dict = {}

    if not offline:
        try:
            text = _fetch_iana()
            r = csv.reader(io.StringIO(text))
            next(r, None)  # header
            for row in r:
                if len(row) < 4:
                    continue
                name, port, proto, desc = row[0].strip(), row[1].strip(), row[2].strip().lower(), row[3].strip()
                if not re.fullmatch(r"\d+", port) or proto not in ("tcp", "udp", "sctp", "dccp"):
                    continue
                svc = name or (desc[:24] if desc else "")
                if not svc:
                    continue
                note = re.sub(r"\s+", " ", desc)[:90]
                rows.setdefault((int(port), proto), [svc, "", 0, note])
        except Exception as e:  # pragma: no cover - network dependent
            print(f"WARN: IANA fetch failed ({type(e).__name__}: {e}); curated overlay only", file=sys.stderr)

    # overlay wins (category/broadcast/note authoritative; relabels service)
    for (oport, oproto), (svc, cat, bc, note) in _OVERLAY.items():
        for p in _expand(oproto):
            rows[(oport, p)] = [svc, cat, int(bc), note]

    lines = ["\t".join((str(port), proto, svc, cat, str(bc), note))
             for (port, proto), (svc, cat, bc, note) in sorted(rows.items())]
    # multicast records (proto column = 'mcast', port column = cidr)
    for cidr, (name, cat, bc, note) in sorted(_MCAST.items()):
        lines.append("\t".join((cidr, "mcast", name, cat, str(int(bc)), note)))

    with gzip.open(_OUT, "wt", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {_OUT}: {len(rows)} port records + {len(_MCAST)} multicast records "
          f"({os.path.getsize(_OUT)} bytes)")
    return len(rows)


if __name__ == "__main__":
    build(offline="--offline" in sys.argv)
