"""Offline port / protocol / multicast lookup with field-level authority.

The v2 pack never conflates IANA assignments with repository curation. Each
row has twelve tab-separated fields::

    key, proto, service, alias_records_json, category, broadcast, note,
    assignment_source, semantics_source, overlay_service, overlay_note,
    overlay_status

IANA's first retained row is the primary ``service`` and every additional
official row is preserved in ``alias_records``. Curated AV/OT/IT semantics and
multicast scopes stay useful but are explicitly non-authoritative. A curated
label never replaces an IANA service assignment.

To refresh the shipped data (rarely needed): `python -m cisco_toolkit.data.gen_port_registry`
(see that module)."""
import functools
import ipaddress
import json
import logging
import os
from typing import List, Optional, Tuple

from .registry_integrity import (
    PackIntegrityError,
    source_authority_details,
    verified_text,
)

_LOG = logging.getLogger(__name__)

_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "port_registry.tsv.gz")
_AUTHORITATIVE_PROVENANCE_STATES = frozenset(
    {"generated-from-retained-iana-primary-source"}
)
_HEALTH: dict = {
    "status": "not-loaded",
    "integrity_verified": False,
    "source_authoritative": False,
    "authoritative": False,
    "path": _DATA,
    "error": "",
}


@functools.lru_cache(maxsize=1)
def _registry() -> Tuple[dict, List[tuple]]:
    """Returns (ports, mcast):
        ports : {(port:int, proto:str): {service, category, broadcast, note}}
        mcast : [(ipaddress.IPv4Network, {group, category, broadcast, note}), ...] sorted most-specific first.
    Any integrity or schema defect invalidates the complete registry."""

    global _HEALTH
    ports: dict = {}
    mcast: List[tuple] = []
    try:
        text, metadata = verified_text(_DATA)
        if metadata.get("port_schema_version") != 2:
            raise PackIntegrityError("port registry schema is unsupported")
        mcast_keys: set[str] = set()
        for row_number, line in enumerate(text.splitlines(), 1):
            parts = line.split("\t")
            if len(parts) != 12:
                raise PackIntegrityError(f"malformed port row {row_number}")
            (
                key,
                proto,
                service,
                aliases_json,
                category,
                broadcast,
                note,
                assignment_source,
                semantics_source,
                overlay_service,
                overlay_note,
                overlay_status,
            ) = parts
            if not service.strip() or broadcast not in ("0", "1"):
                raise PackIntegrityError(f"invalid port record at row {row_number}")
            try:
                aliases = json.loads(aliases_json)
            except json.JSONDecodeError as exc:
                raise PackIntegrityError(
                    f"invalid alias inventory at row {row_number}"
                ) from exc
            if (
                not isinstance(aliases, list)
                or any(
                    not isinstance(alias, list)
                    or len(alias) != 2
                    or any(not isinstance(value, str) for value in alias)
                    or not alias[0]
                    for alias in aliases
                )
            ):
                raise PackIntegrityError(
                    f"invalid alias inventory at row {row_number}"
                )
            rec = {
                "service": service,
                "aliases": [alias[0] for alias in aliases],
                "alias_records": [
                    {"service": alias[0], "description": alias[1]}
                    for alias in aliases
                ],
                "category": category,
                "broadcast": broadcast == "1",
                "note": note,
                "assignment_source": assignment_source,
                "semantics_source": semantics_source,
                "overlay_service": overlay_service,
                "overlay_note": overlay_note,
                "overlay_status": overlay_status,
            }
            if proto == "mcast":
                if (
                    aliases
                    or assignment_source != "curated-multicast"
                    or semantics_source != "curated-multicast"
                    or overlay_status != "curated-only"
                ):
                    raise PackIntegrityError(
                        f"invalid multicast authority fields at row {row_number}"
                    )
                try:
                    net = ipaddress.ip_network(key, strict=True)
                except ValueError as exc:
                    raise PackIntegrityError(
                        f"invalid multicast network at row {row_number}"
                    ) from exc
                if (
                    not isinstance(net, ipaddress.IPv4Network)
                    or not net.network_address.is_multicast
                ):
                    raise PackIntegrityError(
                        f"non-IPv4-multicast record at row {row_number}"
                    )
                canonical = str(net)
                if canonical in mcast_keys:
                    raise PackIntegrityError(
                        f"duplicate multicast record at row {row_number}"
                    )
                mcast_keys.add(canonical)
                rec["group"] = service
                mcast.append((net, rec))
            else:
                if proto not in ("tcp", "udp", "sctp", "dccp"):
                    raise PackIntegrityError(f"unsupported protocol at row {row_number}")
                if assignment_source not in ("iana", "curated-overlay"):
                    raise PackIntegrityError(
                        f"invalid assignment authority at row {row_number}"
                    )
                if semantics_source not in ("iana", "curated-overlay"):
                    raise PackIntegrityError(
                        f"invalid semantics authority at row {row_number}"
                    )
                if overlay_status not in (
                    "none",
                    "supplemental",
                    "overlay-only",
                    "conflict-suppressed",
                ):
                    raise PackIntegrityError(
                        f"invalid overlay status at row {row_number}"
                    )
                if assignment_source == "curated-overlay" and (
                    aliases
                    or semantics_source != "curated-overlay"
                    or overlay_status != "overlay-only"
                ):
                    raise PackIntegrityError(
                        f"invalid curated-only port at row {row_number}"
                    )
                if overlay_status == "conflict-suppressed" and (
                    category
                    or broadcast != "0"
                    or semantics_source != "iana"
                    or not overlay_service
                ):
                    raise PackIntegrityError(
                        f"unsafe overlay conflict at row {row_number}"
                    )
                if overlay_status == "none" and (
                    overlay_service or overlay_note or semantics_source != "iana"
                ):
                    raise PackIntegrityError(
                        f"invalid absent-overlay fields at row {row_number}"
                    )
                try:
                    port = int(key)
                except ValueError as exc:
                    raise PackIntegrityError(f"invalid port at row {row_number}") from exc
                if not 0 <= port <= 65535 or (port, proto) in ports:
                    raise PackIntegrityError(
                        f"invalid or duplicate port at row {row_number}"
                    )
                ports[(port, proto)] = rec
        mcast.sort(key=lambda nr: nr[0].prefixlen, reverse=True)
        if metadata.get("port_count") not in (None, len(ports)):
            raise PackIntegrityError("port-record count disagrees with registry manifest")
        if metadata.get("multicast_count") not in (None, len(mcast)):
            raise PackIntegrityError("multicast-record count disagrees with registry manifest")

        observed_counts = {
            "iana_assignment_count": sum(
                record["assignment_source"] == "iana" for record in ports.values()
            ),
            "iana_alias_record_count": sum(
                len(record["alias_records"]) for record in ports.values()
            ),
            "iana_duplicate_key_count": sum(
                bool(record["alias_records"]) for record in ports.values()
            ),
            "overlay_enriched_iana_count": sum(
                record["overlay_status"] == "supplemental"
                for record in ports.values()
            ),
            "overlay_only_port_count": sum(
                record["overlay_status"] == "overlay-only"
                for record in ports.values()
            ),
            "overlay_conflict_count": sum(
                record["overlay_status"] == "conflict-suppressed"
                for record in ports.values()
            ),
        }
        for field, observed in observed_counts.items():
            if metadata.get(field) != observed:
                raise PackIntegrityError(
                    f"{field} disagrees with registry manifest"
                )

        authority = source_authority_details(
            metadata,
            allowed_provenance_states=_AUTHORITATIVE_PROVENANCE_STATES,
        )
        official_source_ok = bool(authority["source_authoritative"])
        source_reason = str(authority["authority_error"])
        all_records = list(ports.values()) + [
            record for _, record in mcast
        ]
        for record in all_records:
            record["assignment_authoritative"] = bool(
                official_source_ok and record["assignment_source"] == "iana"
            )
            record["semantics_authoritative"] = bool(
                official_source_ok and record["semantics_source"] == "iana"
            )
            record["source_authoritative"] = bool(
                record["assignment_authoritative"]
                and record["semantics_authoritative"]
            )
        all_authoritative = bool(
            all_records
            and all(record["source_authoritative"] for record in all_records)
        )
        mixed_authority_reason = (
            "pack contains non-authoritative curated overlay and multicast "
            "semantics"
        )
        public_authority = {
            key: value
            for key, value in authority.items()
            if key not in {
                "authority_error",
                "source_authoritative",
                "verified_artifacts",
            }
        }
        _HEALTH = {
            "status": (
                "integrity-verified-mixed-authority"
                if official_source_ok
                else (
                    "integrity-verified-build-provenance-mixed-authority"
                    if authority["build_provenance_verified"]
                    else "integrity-verified-source-unverified"
                )
            ),
            "integrity_verified": True,
            # The pack intentionally contains non-authoritative curated rows,
            # so pack-wide source authority must remain false.
            "source_authoritative": all_authoritative,
            "official_source_authoritative": official_source_ok,
            "curated_overlay_authoritative": False,
            "curated_multicast_authoritative": False,
            "authoritative": all_authoritative,
            "path": _DATA,
            "error": (
                source_reason
                if not official_source_ok
                else ("" if all_authoritative else mixed_authority_reason)
            ),
            "authority_note": (
                "IANA assignments are source-authoritative; curated overlay "
                "and multicast semantics are explicitly non-authoritative"
                if official_source_ok
                else "retained IANA source bytes were not verified"
            ),
            "row_count": metadata["row_count"],
            "port_count": len(ports),
            "multicast_count": len(mcast),
            **observed_counts,
            "source_authoritative_record_count": sum(
                record["source_authoritative"] for record in all_records
            ),
            "mixed_authority_record_count": sum(
                record["assignment_authoritative"]
                and not record["semantics_authoritative"]
                for record in all_records
            ),
            "curated_only_record_count": sum(
                record["assignment_source"] != "iana" for record in all_records
            ),
            "compressed_sha256": metadata["compressed_sha256"],
            "provenance_status": metadata.get("provenance_status", "unknown"),
            **public_authority,
        }
        if not official_source_ok:
            _LOG.warning(
                "portdb: pack bytes/schema verified, but retained IANA source "
                "bytes are not authoritative (%s)",
                source_reason,
            )
        return ports, mcast
    except (PackIntegrityError, OSError, EOFError, UnicodeDecodeError, ValueError) as exc:
        _HEALTH = {
            "status": "invalid",
            "integrity_verified": False,
            "source_authoritative": False,
            "authoritative": False,
            "path": _DATA,
            "error": str(exc),
        }
        _LOG.error(
            "portdb: rejected non-authoritative registry %s (%s) -- L4-service/multicast evidence is unavailable",
            _DATA,
            exc,
        )
        return {}, []


def registry_health(load: bool = True) -> dict:
    """Machine-readable authority status for snapshots, self-tests, and health gates."""

    if load:
        _registry()
    return dict(_HEALTH)


def service_for_port(port: int, proto: str = "tcp") -> Optional[dict]:
    """Return a source-labelled service record, or ``None`` if unknown.

    ``service`` and ``aliases`` preserve IANA assignment order when available;
    every curated field carries separate authority flags. ``proto`` is
    case-insensitive and an unknown protocol falls back to a TCP/UDP probe.
    """
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
