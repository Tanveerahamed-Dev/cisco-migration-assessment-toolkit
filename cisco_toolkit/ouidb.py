"""Offline IEEE OUI -> vendor lookup (NEW-V3.23.95).

Ships a compact, gzipped registry at ``data/oui_registry.tsv.gz``, generated
directly from retained official IEEE Registration Authority MA-L, MA-M, and
MA-S CSV inputs. MAC -> vendor resolution is fully offline at runtime. The
registry is lazy-loaded and cached; lookups do a longest-prefix match across
36-bit (MA-S), 28-bit (MA-M), and 24-bit (MA-L) allocations.

Refreshes are explicit, deterministic evidence updates. See
``reference-data/official-sources/README.md`` and
``python -m cisco_toolkit.gen_oui_registry --help``."""
import functools
import logging
import os
import re

from .registry_integrity import (
    PackIntegrityError,
    source_authority_details,
    verified_text,
)

_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "oui_registry.tsv.gz")
_AUTHORITATIVE_PROVENANCE_STATES = frozenset(
    {"generated-from-retained-ieee-primary-sources"}
)
_LOG = logging.getLogger(__name__)
_HEALTH: dict = {
    "status": "not-loaded",
    "integrity_verified": False,
    "source_authoritative": False,
    "authoritative": False,
    "path": _DATA,
    "error": "",
}


@functools.lru_cache(maxsize=1)
def _registry() -> dict:
    """Return verified OUI tables; any defect invalidates the complete authority."""

    global _HEALTH
    candidate: dict = {24: {}, 28: {}, 36: {}}
    try:
        text, metadata = verified_text(_DATA)
        for row_number, line in enumerate(text.splitlines(), 1):
            parts = line.split("\t")
            if len(parts) != 3:
                raise PackIntegrityError(f"malformed OUI row {row_number}")
            hexp, bits, vendor = parts
            try:
                bit_count = int(bits)
            except ValueError as exc:
                raise PackIntegrityError(f"invalid OUI width at row {row_number}") from exc
            if (
                bit_count not in (24, 28, 36)
                or len(hexp) != bit_count // 4
                or not re.fullmatch(r"[0-9A-F]+", hexp)
                or not vendor.strip()
            ):
                raise PackIntegrityError(f"invalid OUI record at row {row_number}")
            if hexp in candidate[bit_count]:
                raise PackIntegrityError(f"duplicate OUI prefix at row {row_number}")
            candidate[bit_count][hexp] = vendor
        authority = source_authority_details(
            metadata,
            allowed_provenance_states=_AUTHORITATIVE_PROVENANCE_STATES,
        )
        source_ok = bool(authority["source_authoritative"])
        source_reason = str(authority["authority_error"])
        public_authority = {
            key: value
            for key, value in authority.items()
            if key not in {"authority_error", "verified_artifacts"}
        }
        _HEALTH = {
            "status": (
                "verified-authoritative"
                if source_ok
                else (
                    "integrity-verified-build-provenance"
                    if authority["build_provenance_verified"]
                    else "integrity-verified-source-unverified"
                )
            ),
            "integrity_verified": True,
            "source_authoritative": source_ok,
            "authoritative": source_ok,
            "path": _DATA,
            "error": "" if source_ok else source_reason,
            "row_count": metadata["row_count"],
            "compressed_sha256": metadata["compressed_sha256"],
            "provenance_status": metadata.get("provenance_status", "unknown"),
            **public_authority,
        }
        if not source_ok:
            _LOG.warning(
                "ouidb: pack bytes/schema verified, but source is not authoritative (%s)",
                source_reason,
            )
        return candidate
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
            "ouidb: rejected non-authoritative registry %s (%s) -- MAC->vendor evidence is unavailable",
            _DATA,
            exc,
        )
        return {24: {}, 28: {}, 36: {}}


def registry_health(load: bool = True) -> dict:
    """Machine-readable authority status for snapshots, self-tests, and health gates."""

    if load:
        _registry()
    return dict(_HEALTH)


def _clean(mac: str) -> str:
    raw = str(mac or "").strip()
    if not raw or not re.fullmatch(r"[0-9A-Fa-f.:\-\s]+", raw):
        return ""
    cleaned = re.sub(r"[.:\-\s]", "", raw).upper()
    return cleaned if len(cleaned) in (12, 16) else ""


def is_locally_administered(mac: str) -> bool:
    """True if the MAC is locally-administered (bit 0x02 of the first octet) -- i.e. NOT vendor-assigned:
    a randomized/privacy MAC, a hypervisor-synthesised MAC (e.g. QEMU/KVM 52:54:00), or a virtual
    protocol MAC. Such addresses have no IEEE registry owner, so the classifier treats them as a signal,
    not a vendor."""
    h = _clean(mac)
    if len(h) < 2:
        return False
    try:
        return bool(int(h[:2], 16) & 0x02)
    except ValueError:
        return False


@functools.lru_cache(maxsize=8192)
def vendor_for_mac(mac: str) -> str:
    """Registered vendor for a MAC via longest-prefix match (36 -> 28 -> 24 bits), or '' if the MAC is
    unknown / locally-administered / too short. Cached (the same OUIs recur thousands of times)."""
    h = _clean(mac)
    if len(h) < 6 or is_locally_administered(h):
        return ""
    reg = _registry()
    for bits in (36, 28, 24):
        n = bits // 4
        if len(h) >= n:
            v = reg.get(bits, {}).get(h[:n])
            if v:
                return v
    return ""
