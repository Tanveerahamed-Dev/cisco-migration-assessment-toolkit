"""Offline port / protocol / multicast -> service lookup  (NEW-V3.23.99).

The twin of `ouidb.py`: ships a compact, gzipped registry at `data/port_registry.tsv.gz` so L4
service resolution and IPv4 multicast-group classification are fully OFFLINE / air-gapped at run time
-- no internet, no live lookup. The registry merges the IANA Service Name and Transport Protocol Port
Number Registry (the long tail) with a curated broadcast/AV + OT/ICS + IT-infra overlay (the high-signal
semantics IANA lacks: Dante, AES67, SMPTE ST 2110, NDI, NMOS, PTP, Modbus, DNP3, BACnet, OPC-UA, ...).

Each port maps to {service, category, broadcast, note}; `broadcast` flags ports/groups central to
broadcast / pro-AV / media-over-IP fabrics. Multicast groups are matched longest-prefix so a specific
reserved address (224.0.1.129 = PTP) wins over its enclosing block (224.0.1.0/24).

To refresh the shipped data (rarely needed): `python -m cisco_toolkit.data.gen_port_registry`
(see that module). Pure stdlib (gzip + ipaddress)."""
import functools
import gzip
import ipaddress
import logging
import os
from typing import List, Optional, Tuple

_LOG = logging.getLogger(__name__)

_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "port_registry.tsv.gz")


@functools.lru_cache(maxsize=1)
def _registry() -> Tuple[dict, List[tuple]]:
    """Returns (ports, mcast):
        ports : {(port:int, proto:str): {service, category, broadcast, note}}
        mcast : [(ipaddress.IPv4Network, {group, category, broadcast, note}), ...] sorted most-specific first.
    Missing/corrupt data -> empty tables (lookups return None)."""
    ports: dict = {}
    mcast: List[tuple] = []
    try:
        with gzip.open(_DATA, "rt", encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) != 6:
                    continue
                key, proto, service, category, broadcast, note = parts
                rec = {"service": service, "category": category,
                       "broadcast": broadcast == "1", "note": note}
                if proto == "mcast":
                    try:
                        net = ipaddress.ip_network(key, strict=False)
                    except ValueError:
                        continue
                    rec["group"] = service
                    mcast.append((net, rec))
                else:
                    try:
                        ports[(int(key), proto)] = rec
                    except ValueError:
                        continue
    except (OSError, EOFError, UnicodeDecodeError) as e:
        # Surface a load failure ONCE (the empty result is then lru_cached for the whole process): a missing or
        # corrupt shipped pack silently disabling the entire L4-service / multicast axis is worse than loud.
        # Narrowed from a bare `except Exception` so an UNEXPECTED bug is no longer swallowed as 'no data'.
        _LOG.warning("portdb: could not load %s (%s) -- L4-service/multicast lookups will be empty", _DATA, e)
    mcast.sort(key=lambda nr: nr[0].prefixlen, reverse=True)  # longest-prefix first
    return ports, mcast


def service_for_port(port: int, proto: str = "tcp") -> Optional[dict]:
    """{service, category, broadcast, note} for a (port, proto), or None if unknown.
    `proto` is tcp/udp/sctp/dccp (case-insensitive); unknown protos fall back to a tcp/udp probe."""
    try:
        p = int(port)
    except (TypeError, ValueError):
        return None
    ports, _ = _registry()
    pr = str(proto or "tcp").strip().lower()      # coerce: tolerate a non-string proto, like the rest of the module
    rec = ports.get((p, pr))
    if rec is None and pr not in ("tcp", "udp", "sctp", "dccp"):
        rec = ports.get((p, "tcp")) or ports.get((p, "udp"))
    return rec


def classify_multicast(group_ip: str) -> Optional[dict]:
    """{group, category, broadcast, note} for an IPv4 multicast address via longest-prefix match over the
    reserved/well-known group table, or None if it is not multicast / not in the table."""
    try:
        addr = ipaddress.ip_address(str(group_ip or "").strip())   # coerce: tolerate a non-string arg
    except ValueError:
        return None
    if not addr.is_multicast:
        return None
    _, mcast = _registry()
    for net, rec in mcast:
        if addr in net:
            return rec
    return None


def is_broadcast_av_port(port: int, proto: str = "udp") -> bool:
    """True if the port is flagged as central to a broadcast / pro-AV / media-over-IP fabric."""
    rec = service_for_port(port, proto)
    return bool(rec and rec.get("broadcast"))
