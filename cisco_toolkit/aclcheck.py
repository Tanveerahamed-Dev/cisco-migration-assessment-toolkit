"""ACL line-reachability / shadow PROOF (roadmap G1) — an offline header-space algebra over parsed ACLs.

The offline, coverage-honest recast of Batfish `filterLineReachability` + `searchFilters`: pure stdlib
`ipaddress`, no network, read-only over the already-collected snapshot. Each ACL line is modelled as a
5-dimensional **box** — proto (a co-finite set) × src/dst (IPv4 prefix-sets) × sport/dport (integer
interval-sets) — and a line is declared dead only when its box is *provably* covered by the union of the
earlier lines (computed by exact guillotine box-subtraction). The doctrine is in the abstentions:

  * `BLOCKING_LINES`            — provably covered by earlier lines (with `different_action` set when a
                                  PERMIT is shadowed by a DENY, or vice-versa: a silently-broken intent).
  * `INDEPENDENTLY_UNMATCHABLE` — the line's own box is empty (e.g. a port range with lo > hi).
  * `UNDEFINED_REFERENCE` / `CYCLICAL_REFERENCE` — a bad object-group reference.
  * `INDETERMINATE`             — an earlier line is unevaluable (non-contiguous wildcard, unknown port,
                                  `time-range`, stateful `established`) and *might* overlap; we never
                                  claim "dead" or "reachable" when we cannot prove it.

`compute_filter_line_reachability(snap)` runs it over `snap['acls'][host][name]`; `search_filters` answers
"is there a packet that gets <action> here?" with a concrete witness 5-tuple OR a proof that none exists.
"""
from __future__ import annotations

import ipaddress
from typing import Any, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------- proto dimension
# A co-finite set over protocol tokens: ("only", {…}) = exactly these; ("allexcept", {…}) = all but these.
PROTO_FULL: Tuple[str, frozenset] = ("allexcept", frozenset())


def _proto_of(tok: Any) -> Tuple[str, frozenset]:
    t = str(tok or "ip").lower()
    return PROTO_FULL if t == "ip" else ("only", frozenset({t}))


def _proto_inter(a, b):
    (ka, sa), (kb, sb) = a, b
    if ka == "only" and kb == "only":
        return ("only", sa & sb)
    if ka == "only":
        return ("only", sa - sb)
    if kb == "only":
        return ("only", sb - sa)
    return ("allexcept", sa | sb)


def _proto_diff(a, b):
    k, s = b
    compl = ("allexcept", s) if k == "only" else ("only", s)
    return _proto_inter(a, compl)


def _proto_empty(a) -> bool:
    return a[0] == "only" and not a[1]


# --------------------------------------------------------------------------- address dimension (IPv4 prefix-set)
_FULL_NET = [ipaddress.ip_network("0.0.0.0/0")]


def _collapse(nets):
    return list(ipaddress.collapse_addresses(nets)) if nets else []


def _pref_inter(A, B):
    out = []
    for a in A:
        for b in B:
            if a.subnet_of(b):
                out.append(a)
            elif b.subnet_of(a):
                out.append(b)
    return _collapse(out)


def _pref_diff(A, B):
    res = list(A)
    for b in B:
        new = []
        for r in res:
            if r.subnet_of(b):
                continue                                  # r removed entirely
            elif b.subnet_of(r):
                new.extend(r.address_exclude(b))          # b strictly inside r -> split
            else:
                new.append(r)                             # disjoint
        res = new
    return _collapse(res)


def _pref_empty(A) -> bool:
    return not A


def _addr_prefixes(spec, ogs, host) -> Tuple[Optional[list], str]:
    """{ip,wild} | {group} | {rangeStart,rangeEnd} -> ([IPv4Network], 'ok') or (None, status)."""
    if not isinstance(spec, dict):
        return None, "unevaluable"
    if spec.get("group") is not None:
        return _group_prefixes(spec["group"], ogs, host, set())
    if spec.get("rangeStart") and spec.get("rangeEnd"):
        try:
            a = ipaddress.ip_address(spec["rangeStart"])
            b = ipaddress.ip_address(spec["rangeEnd"])
            if a.version != 4 or b.version != 4:           # IPv6 is not modeled by this v4 box algebra -> abstain
                return None, "unevaluable"
            return _collapse(list(ipaddress.summarize_address_range(a, b))), "ok"
        except (ValueError, TypeError):
            return None, "unevaluable"
    ip, wild = spec.get("ip"), spec.get("wild")
    if ip is None or wild is None:
        return None, "unevaluable"
    try:
        ipa, wilda = ipaddress.ip_address(ip), ipaddress.ip_address(wild)
    except (ValueError, TypeError):
        return None, "unevaluable"
    if ipa.version != 4 or wilda.version != 4:            # IPv6 -> abstain, never mangle into a wrong v4 prefix
        return None, "unevaluable"
    ipi, wi = int(ipa), int(wilda)
    if (wi & (wi + 1)) != 0:                               # non-contiguous wildcard -> can't model as a prefix
        return None, "unevaluable"
    plen = 32 - wi.bit_length()
    return [ipaddress.ip_network((ipi & (~wi & 0xFFFFFFFF), plen))], "ok"


def _group_prefixes(name, ogs, host, seen) -> Tuple[Optional[list], str]:
    tbl = ogs or {}
    og = tbl.get(name)
    if og is None:
        return None, "undefined"
    if name in seen:
        return None, "cyclic"
    seen = seen | {name}
    prefixes = []
    for m in (og.get("members") or []):
        if not isinstance(m, dict):
            continue
        if m.get("group") is not None:
            sub, st = _group_prefixes(m["group"], ogs, host, seen)
            if st != "ok":
                return None, st
            prefixes.extend(sub)
        else:
            pl, st = _addr_prefixes(m, ogs, host)
            if st != "ok":
                return None, st
            prefixes.extend(pl)
    return _collapse(prefixes), "ok"


# --------------------------------------------------------------------------- port dimension (interval-set)
def _iv_norm(ivs):
    ivs = sorted((lo, hi) for lo, hi in ivs if lo <= hi)
    out = []
    for lo, hi in ivs:
        if out and lo <= out[-1][1] + 1:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def _iv_inter(A, B):
    out = []
    for al, ah in A:
        for bl, bh in B:
            lo, hi = max(al, bl), min(ah, bh)
            if lo <= hi:
                out.append((lo, hi))
    return _iv_norm(out)


def _iv_diff(A, B):
    res = list(A)
    for bl, bh in B:
        new = []
        for lo, hi in res:
            if bh < lo or bl > hi:
                new.append((lo, hi))
            else:
                if lo < bl:
                    new.append((lo, bl - 1))
                if hi > bh:
                    new.append((bh + 1, hi))
        res = new
    return _iv_norm(res)


def _iv_empty(A) -> bool:
    return not A


def _port_intervals(p) -> Optional[list]:
    """{op,val,val2?} -> [(lo,hi)] interval-set over [0,65535]; None for the whole space; [] when empty."""
    if p is None:
        return [(0, 65535)]
    if not isinstance(p, dict):
        return None
    op, v, v2 = p.get("op"), p.get("val"), p.get("val2")
    if v is None:
        return None                                        # unknown port name -> unevaluable
    if op == "eq":
        return _iv_norm([(v, v)])
    if op == "neq":
        return _iv_norm([(0, v - 1), (v + 1, 65535)])
    if op == "lt":
        return _iv_norm([(0, v - 1)])
    if op == "gt":
        return _iv_norm([(v + 1, 65535)])
    if op == "range":
        if v2 is None:
            return None
        return _iv_norm([(v, v2)])                          # lo>hi collapses to [] -> INDEPENDENTLY_UNMATCHABLE
    return None


# --------------------------------------------------------------------------- the 5-D box
_DIMS = ("proto", "src", "dst", "sport", "dport")
_OPS = {
    "proto": (_proto_inter, _proto_diff, _proto_empty),
    "src": (_pref_inter, _pref_diff, _pref_empty),
    "dst": (_pref_inter, _pref_diff, _pref_empty),
    "sport": (_iv_inter, _iv_diff, _iv_empty),
    "dport": (_iv_inter, _iv_diff, _iv_empty),
}
_MAX_BOXES = 4000                                          # residual cap -> bail to INDETERMINATE, never wrong


def _box_empty(box) -> bool:
    return any(_OPS[d][2](box[d]) for d in _DIMS)


def _box_inter(a, b):
    return {d: _OPS[d][0](a[d], b[d]) for d in _DIMS}


def _box_subtract(A, B):
    """A \\ B as a list of disjoint boxes (guillotine split)."""
    inters = {d: _OPS[d][0](A[d], B[d]) for d in _DIMS}
    if any(_OPS[d][2](inters[d]) for d in _DIMS):
        return [A]                                          # disjoint in some dim -> nothing removed
    out = []
    for i, d in enumerate(_DIMS):
        diff_d = _OPS[d][1](A[d], B[d])
        if _OPS[d][2](diff_d):
            continue
        nb = {}
        for j, e in enumerate(_DIMS):
            nb[e] = diff_d if e == d else (inters[e] if j < i else A[e])
        if not _box_empty(nb):
            out.append(nb)
    return out


def _rule_box(rule, ogs, host) -> Tuple[dict, str]:
    """Parsed rule -> (over-approximating box, status). Unevaluable dims fall back to FULL."""
    src, st_s = _addr_prefixes(rule.get("src"), ogs, host)
    dst, st_d = _addr_prefixes(rule.get("dst"), ogs, host)
    sport = _port_intervals(rule.get("sport"))
    dport = _port_intervals(rule.get("dport"))
    box = {
        "proto": _proto_of(rule.get("proto")),
        "src": src if src is not None else list(_FULL_NET),
        "dst": dst if dst is not None else list(_FULL_NET),
        "sport": sport if sport is not None else [(0, 65535)],
        "dport": dport if dport is not None else [(0, 65535)],
    }
    status = "ok"
    for st in (st_s, st_d):                                 # undefined/cyclic win over a plain unevaluable
        if st in ("undefined", "cyclic"):
            status = st
    if status == "ok":
        if rule.get("time_range"):
            status = "timerange"
        elif rule.get("unevaluable") or src is None or dst is None or sport is None or dport is None:
            status = "unevaluable"
    return box, status


def _finding(idx, rule, reason, blocking_lines=None, different_action=False, detail=""):
    return {"line_index": idx, "action": rule.get("action"), "raw": rule.get("raw", ""),
            "reason": reason, "blocking_lines": blocking_lines or [],
            "different_action": bool(different_action), "detail": detail}


def analyze_acl(rules: List[dict], object_groups: Optional[dict] = None, host: Optional[str] = None) -> List[dict]:
    """One ACL's rules -> a list of findings (one per non-REACHABLE line). Pure; never raises."""
    ogs = object_groups or {}
    meta = []
    for r in (rules or []):
        box, st = _rule_box(r, ogs, host)
        est = bool(r.get("established") or r.get("reflexive"))
        meta.append((box, st, (r.get("action") or "").lower(), est, r))

    findings: List[dict] = []
    for i, (box, st, action, est, r) in enumerate(meta):
        if st == "undefined":
            findings.append(_finding(i, r, "UNDEFINED_REFERENCE", detail="references an object-group not in the snapshot"))
            continue
        if st == "cyclic":
            findings.append(_finding(i, r, "CYCLICAL_REFERENCE", detail="object-group reference is cyclic"))
            continue
        if est:
            findings.append(_finding(i, r, "INDETERMINATE", detail="stateful established/reflexive — forward match depends on connection state"))
            continue
        if st in ("unevaluable", "timerange"):
            why = "time-range — active only in a window" if st == "timerange" else "unparseable address/port (e.g. non-contiguous wildcard)"
            findings.append(_finding(i, r, "INDETERMINATE", detail=why))
            continue
        if _box_empty(box):
            findings.append(_finding(i, r, "INDEPENDENTLY_UNMATCHABLE", detail="own match-space is empty (no packet can ever match)"))
            continue

        residual = [box]
        blockers: List[int] = []
        capped = False
        for j in range(i):
            bjbox, bjst, bjaction, bjest, bjr = meta[j]
            if bjest or bjst != "ok":
                continue                                    # established / unevaluable handled in the overlap pass
            if any(not _box_empty(_box_inter(rb, bjbox)) for rb in residual):
                blockers.append(j)
                new_res = []
                for rb in residual:
                    new_res.extend(_box_subtract(rb, bjbox))
                residual = [b for b in new_res if not _box_empty(b)]
                if len(residual) > _MAX_BOXES:
                    capped = True
                    break
                if not residual:
                    break
        if capped:
            findings.append(_finding(i, r, "INDETERMINATE", detail="match-space too fragmented to decide exactly"))
            continue
        if not residual:
            diff_act = any(meta[j][2] != action for j in blockers)
            nb = next((j for j in sorted(blockers) if meta[j][2] != action), None)   # the FIRST different-action blocker
            detail = ("a %s shadowed by an earlier %s" % (action, meta[nb][2])) if (diff_act and nb is not None) else "fully covered by earlier line(s)"
            findings.append(_finding(i, r, "BLOCKING_LINES", blocking_lines=sorted(set(blockers)),
                                     different_action=diff_act, detail=detail))
            continue
        # residual non-empty: could an unevaluable earlier line overlap what's left?
        for j in range(i):
            bjbox, bjst, bjaction, bjest, bjr = meta[j]
            if bjest or bjst == "ok":
                continue
            if any(not _box_empty(_box_inter(rb, bjbox)) for rb in residual):
                findings.append(_finding(i, r, "INDETERMINATE", detail="an earlier unevaluable line may overlap — cannot prove reachable or dead"))
                break
        # else REACHABLE -> no finding
    return findings


def compute_filter_line_reachability(snap: Dict[str, Any]) -> Dict[str, Any]:
    """Run the shadow proof over every ACL in the snapshot -> {findings:[…], summary:{…}}."""
    acls_by_host = (snap or {}).get("acls") or {}
    ogs_by_host = (snap or {}).get("object_groups") or {}
    findings: List[dict] = []
    for host, acls in acls_by_host.items():
        ogs = ogs_by_host.get(host) or {}
        for name, rules in (acls or {}).items():
            for f in analyze_acl(rules, ogs, host):
                row = dict(f)
                row.update(host=host, acl=name, source_command="show running-config",
                           citation="acls.%s.%s[%d]" % (host, name, f["line_index"]))
                findings.append(row)
    summary = {
        "n_findings": len(findings),
        "n_shadowed": sum(1 for f in findings if f["reason"] == "BLOCKING_LINES"),
        "n_different_action": sum(1 for f in findings if f.get("different_action")),
        "n_unmatchable": sum(1 for f in findings if f["reason"] == "INDEPENDENTLY_UNMATCHABLE"),
        "n_indeterminate": sum(1 for f in findings if f["reason"] == "INDETERMINATE"),
        "n_bad_reference": sum(1 for f in findings if f["reason"] in ("UNDEFINED_REFERENCE", "CYCLICAL_REFERENCE")),
    }
    return {"findings": findings, "summary": summary}


# --------------------------------------------------------------------------- searchFilters (witness-or-proof)
def _headers_box(h):
    h = h or {}

    def addr(key):
        v = h.get(key)
        if not v:
            return list(_FULL_NET)
        try:
            return [ipaddress.ip_network(v, strict=False)] if "/" in str(v) else [ipaddress.ip_network(str(v) + "/32")]
        except (ValueError, TypeError):
            return list(_FULL_NET)

    def prt(key):
        v = h.get(key)
        return [(int(v), int(v))] if v is not None else [(0, 65535)]

    proto = _proto_of(h.get("proto")) if h.get("proto") else PROTO_FULL
    return {"proto": proto, "src": addr("src"), "dst": addr("dst"), "sport": prt("sport"), "dport": prt("dport")}


def _proto_witness(bp, header_proto):
    """A concrete protocol token admitted by the box's proto set (so the witness actually achieves the verdict)."""
    kind, s = bp if (isinstance(bp, tuple) and len(bp) == 2) else ("allexcept", frozenset())
    if kind == "only":
        return sorted(s)[0] if s else (header_proto or "ip")
    for cand in (header_proto, "icmp", "tcp", "udp", "1", "6", "17", "ip"):     # allexcept S: pick one not excluded
        if cand and cand not in s:
            return cand
    return header_proto or "ip"


def _witness(box, headers):
    h = headers or {}
    return {
        "proto": _proto_witness(box.get("proto"), h.get("proto")),
        "src": str(box["src"][0].network_address) if box["src"] else (h.get("src") or "0.0.0.0"),
        "dst": str(box["dst"][0].network_address) if box["dst"] else (h.get("dst") or "0.0.0.0"),
        "sport": box["sport"][0][0] if box["sport"] else None,
        "dport": box["dport"][0][0] if box["dport"] else None,
    }


def search_filters(rules: List[dict], headers: Dict[str, Any], action: str = "permit",
                   object_groups: Optional[dict] = None, host: Optional[str] = None) -> Dict[str, Any]:
    """Is there a packet in `headers`' flow-space that the ACL resolves to `action`?

    Returns {result:'WITNESS', flow:{…}} with a concrete 5-tuple, {result:'PROVEN_NONE'} when no packet
    in the space gets `action`, or {result:'INDETERMINATE', detail} when an unevaluable line overlaps the
    undecided query space (coverage-honest: never a false PROVEN_NONE)."""
    ogs = object_groups or {}
    action = (action or "permit").lower()
    q_remaining = [_headers_box(headers)]
    hits: List[dict] = []
    for i, r in enumerate(rules or []):
        if not q_remaining:
            break
        box, st = _rule_box(r, ogs, host)
        if r.get("established") or r.get("reflexive"):
            continue                                        # never matches a forward flow
        overlaps = [o for o in (_box_inter(b, box) for b in q_remaining) if not _box_empty(o)]
        if not overlaps:
            continue
        if st != "ok":
            if hits:                                       # a witness already matched an earlier first-match line -> sound
                return {"result": "WITNESS", "flow": _witness(hits[0], headers)}
            return {"result": "INDETERMINATE", "detail": "line %d (%s) is unevaluable and overlaps the query space" % (i, r.get("raw", ""))}
        if (r.get("action") or "").lower() == action:
            hits.extend(overlaps)
        new_q = []
        for b in q_remaining:
            new_q.extend(_box_subtract(b, box))
        q_remaining = [b for b in new_q if not _box_empty(b)]
    if hits:
        return {"result": "WITNESS", "flow": _witness(hits[0], headers)}
    return {"result": "PROVEN_NONE"}
