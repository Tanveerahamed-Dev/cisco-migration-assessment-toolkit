"""Offline regenerator for `data/oui_registry.tsv.gz` (the pack `ouidb` loads). Plan-A #19.

Parses a LOCAL Wireshark `manuf` file (the IEEE MA-L / MA-M / MA-S allocations) into the compact
`PREFIX<TAB>bits<TAB>vendor` gzipped TSV `ouidb` expects. OFFLINE / no-egress BY CONSTRUCTION: it
reads a path you already downloaded on a trusted host and NEVER fetches a URL (it refuses one) --
regenerating the pack must not become a live-egress vector against the air-gapped doctrine. Refresh
is rare; when needed, fetch https://www.wireshark.org/download/automated/data/manuf on an
internet-connected machine, then run this against the local copy and commit the regenerated pack.

    python -m cisco_toolkit.gen_oui_registry /path/to/manuf [--out cisco_toolkit/data/oui_registry.tsv.gz]

Pure stdlib (gzip, re, argparse). The emitted prefix is UPPERCASE hex truncated to bits/4 nibbles,
matching ouidb's uppercased longest-prefix lookup (36 -> 28 -> 24 bits).
"""
from __future__ import annotations

import argparse
import gzip
import os
import re
import sys
from typing import Iterator, Tuple

_DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "oui_registry.tsv.gz")
_VALID_BITS = (24, 28, 36)   # MA-L / MA-M / MA-S — the only blocks ouidb tables


def parse_manuf(lines) -> Iterator[Tuple[str, int, str]]:
    """Yield ``(prefix_hex_upper, bits, vendor)`` from Wireshark ``manuf`` lines.

    A manuf row is ``<MAC prefix>[/<bits>]<TAB><short>[<TAB><long comment>]``. The MAC prefix is
    colon/dash-separated hex; an optional ``/bits`` marks a MA-M (28) / MA-S (36) block, default 24
    (MA-L, the classic OUI). Vendor is the long name when present, else the short name. Comment
    (``#``) lines, blank lines, out-of-family masks and malformed rows are skipped."""
    for raw in lines:
        line = raw.rstrip("\n")
        if not line or line.lstrip().startswith("#"):
            continue
        parts = [p for p in line.split("\t") if p != ""]
        if len(parts) < 2:
            continue
        macfield, short = parts[0], parts[1]
        long_ = parts[2] if len(parts) >= 3 else ""
        if "/" in macfield:
            mac, _, bits_s = macfield.partition("/")
            try:
                bits = int(bits_s)
            except ValueError:
                continue
        else:
            mac, bits = macfield, 24
        if bits not in _VALID_BITS:
            continue
        hexp = re.sub(r"[^0-9A-Fa-f]", "", mac).upper()
        nib = bits // 4
        if len(hexp) < nib:
            continue
        vendor = (long_ or short).strip()
        if not vendor:
            continue
        yield hexp[:nib], bits, vendor


def write_registry(rows: Iterator[Tuple[str, int, str]], out_path: str) -> int:
    """Write ``(prefix, bits, vendor)`` rows to a gzipped TSV. Returns the row count written."""
    out_dir = os.path.dirname(out_path)
    if out_dir:                                     # bare filename -> dirname is '' -> os.makedirs('') raises
        os.makedirs(out_dir, exist_ok=True)
    n = 0
    with gzip.open(out_path, "wt", encoding="utf-8", newline="\n") as f:
        for hexp, bits, vendor in rows:
            f.write(f"{hexp}\t{bits}\t{vendor}\n")
            n += 1
    return n


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(
        prog="cisco-gen-oui-registry",
        description="Regenerate the offline OUI registry from a LOCAL Wireshark manuf file (no egress).")
    ap.add_argument("manuf", help="path to a local Wireshark 'manuf' file (already downloaded; NOT a URL)")
    ap.add_argument("--out", default=_DEFAULT_OUT, help="output tsv.gz (default: the shipped pack)")
    args = ap.parse_args(argv)
    if re.match(r"^\s*[a-zA-Z][a-zA-Z0-9+.-]*://", args.manuf):     # \s*: a leading space must not defeat the refusal
        sys.exit("refusing a URL — download 'manuf' on a trusted host and pass the LOCAL path (no-egress doctrine).")
    with open(args.manuf, encoding="utf-8", errors="replace") as f:
        n = write_registry(parse_manuf(f), args.out)
    print(f"wrote {n} OUI rows -> {args.out}")


if __name__ == "__main__":
    main()
