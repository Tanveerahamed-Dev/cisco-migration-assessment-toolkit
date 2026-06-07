"""Offline IEEE OUI -> vendor lookup (NEW-V3.23.95).

Ships a compact, gzipped registry at `data/oui_registry.tsv.gz` (derived once from the Wireshark
`manuf` database, which tracks the IEEE MA-L / MA-M / MA-S allocations) so MAC -> vendor resolution
is fully OFFLINE / air-gapped at run time -- no internet, no live lookup. The registry is lazy-loaded
and cached; lookups do a longest-prefix match across 36-bit (MA-S), 28-bit (MA-M) and 24-bit (MA-L,
the classic OUI) allocations, so small vendor blocks resolve correctly, not just the first three bytes.

To refresh the shipped data (rarely needed): fetch https://www.wireshark.org/download/automated/data/manuf
and regenerate the tsv.gz (prefix<TAB>bits<TAB>vendor). Pure stdlib (gzip + re)."""
import functools
import gzip
import os
import re

_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "oui_registry.tsv.gz")


@functools.lru_cache(maxsize=1)
def _registry() -> dict:
    """{bits: {prefix_hex_upper: vendor}}. Missing/corrupt data -> empty tables (lookups return '')."""
    tables: dict = {24: {}, 28: {}, 36: {}}
    try:
        with gzip.open(_DATA, "rt", encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) != 3:
                    continue
                hexp, bits, vendor = parts
                try:
                    b = int(bits)
                except ValueError:
                    continue
                tables.setdefault(b, {})[hexp] = vendor
    except Exception:
        pass
    return tables


def _clean(mac: str) -> str:
    return re.sub(r"[^0-9A-Fa-f]", "", mac or "").upper()


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
    if len(h) < 6:
        return ""
    reg = _registry()
    for bits in (36, 28, 24):
        n = bits // 4
        if len(h) >= n:
            v = reg.get(bits, {}).get(h[:n])
            if v:
                return v
    return ""
