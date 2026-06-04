"""Pure show-command parsers + column primitives. Depends only on `re`, stdlib
typing, and cisco_toolkit.textutils (the leaf layer). Extracted verbatim from
COLLECT_PARSE_V3_23_0.py in PHASE 2.7 step 2 (behaviour byte-identical)."""
import re
from typing import Dict, List, Optional, Tuple

from cisco_toolkit.textutils import normalize_ifname


def extract_fixed_cols(header_line: str, keys: List[Tuple[str,str]]) -> Dict[str, Tuple[int, Optional[int]]]:
    pos = {}
    for needle, name in keys:
        p = header_line.find(needle)
        if p >= 0: pos[name] = p
    items = sorted(pos.items(), key=lambda x: x[1])
    ranges = {}
    for i, (name, start) in enumerate(items):
        end = items[i+1][1] if i < len(items)-1 else None
        ranges[name] = (start, end)
    return ranges

def slice_col(line: str, start: int, end: Optional[int]) -> str:
    return line[start:].strip() if end is None else line[start:end].strip()


def parse_ospf_neighbors(output: str) -> List[Dict[str, str]]:
    """'show ip ospf neighbor' -> [{neighbor, state, address, interface}]."""
    rows = []
    for line in output.splitlines():
        m = re.match(r"\s*(\d+\.\d+\.\d+\.\d+)\s+\d+\s+(\S+)\s+\S+\s+(\d+\.\d+\.\d+\.\d+)\s+(\S+)", line)
        if m:
            rows.append({"neighbor": m.group(1), "state": m.group(2),
                         "address": m.group(3), "interface": normalize_ifname(m.group(4))})
    return rows

def parse_eigrp_neighbors(output: str) -> List[Dict[str, str]]:
    """'show ip eigrp neighbors' -> [{neighbor, interface, state}]."""
    rows = []
    for line in output.splitlines():
        m = re.match(r"\s*\d+\s+(\d+\.\d+\.\d+\.\d+)\s+(\S+)\s+\d+\s+(\S+)", line)
        if m:
            rows.append({"neighbor": m.group(1), "interface": normalize_ifname(m.group(2)),
                         "state": f"up {m.group(3)}"})
    return rows

def parse_bgp_summary(output: str) -> List[Dict[str, str]]:
    """'show ip bgp summary' / 'show bgp summary' -> [{neighbor, as, state}].
    Last column (State/PfxRcd) is the established state or the prefix count."""
    rows = []
    for line in output.splitlines():
        m = re.match(r"\s*(\d+\.\d+\.\d+\.\d+|[0-9A-Fa-f:]+:[0-9A-Fa-f:]+)\s+\d+\s+(\d+)\s+.*\s(\S+)\s*$", line)
        if m:
            rows.append({"neighbor": m.group(1), "as": m.group(2), "state": m.group(3)})
    return rows
