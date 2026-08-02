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

from cisco_toolkit.model import Verdict


# --------------------------------------------------------------------------- defensive coercers
# The house guards (ssot._as_dict / docmeta.as_dict / design_advisor._dict_rows). This module reads
# `snap['acls']` / `snap['object_groups']` -- two of the most deeply NESTED snapshot sections, and both
# arrive from an UNTRUSTED source (a `--no-collect` re-analysis file, a webapp upload, a foreign tool).
# `x or {}` / `x or []` guards None/empty but keeps a TRUTHY non-dict/non-list, and the next
# `.items()` / `.get()` / `for ... in` then raises -- aborting compute_filter_line_reachability, which
# runs on EVERY snapshot the engine analyses.
def _as_dict(v: Any) -> dict:
    return v if isinstance(v, dict) else {}


def _as_list(v: Any) -> list:
    return v if isinstance(v, list) else []


# --------------------------------------------------------------------------- proto dimension
# A co-finite set over protocol tokens: ("only", {…}) = exactly these; ("allexcept", {…}) = all but these.
PROTO_FULL: Tuple[str, frozenset] = ("allexcept", frozenset())

# Cisco accepts BOTH the keyword and the IANA protocol NUMBER in an ACE's protocol field, and the parser
# stores whichever the config used, verbatim (parse.py `rule["proto"] = toks[0].lower()` -> 'proto': '6').
# Compared as RAW STRINGS, `deny 6 any host X` and `permit tcp any host X` model as DISJOINT protocol sets:
# the permit is not reported shadowed, and search_filters hands back a witness asserting a packet is
# permitted when the earlier numeric deny drops it — the unsafe direction. Canonicalising the number onto
# its keyword is what makes the two intersect. Numbers per the IOS/NX-OS ACL protocol-keyword table; an
# unlisted token stays itself (it still compares equal to the same token, so nothing is lost).
_PROTO_ALIASES = {
    "1": "icmp", "2": "igmp", "4": "ipinip", "6": "tcp", "9": "igrp", "17": "udp", "41": "ipv6",
    "46": "rsvp", "47": "gre", "50": "esp", "51": "ahp", "58": "icmpv6", "88": "eigrp", "89": "ospf",
    "94": "nos", "103": "pim", "108": "pcp", "112": "vrrp", "115": "l2tp", "132": "sctp",
    "ah": "ahp", "ip-in-ip": "ipinip", "ipinip-in-ip": "ipinip",     # cross-platform keyword spellings
}


def _canon_proto(tok: Any) -> str:
    """One protocol token -> its canonical form ('6' -> 'tcp'), lower-cased and stripped. Never raises."""
    t = str(tok if tok is not None else "").strip().lower()
    return _PROTO_ALIASES.get(t, t)


def _proto_of(tok: Any) -> Tuple[str, frozenset]:
    t = _canon_proto(tok) or "ip"
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


def _bounds(n):
    """(first_addr_int, last_addr_int, version) -- the containment test `subnet_of` performs, precomputed.

    `ipaddress.subnet_of` is a richly-guarded stdlib call (functools total-ordering, isinstance checks) and
    these two functions are the innermost loop of the whole box algebra: resolving object-group ACEs (each
    side a prefix SET) turns one line-pair into |A|x|B| of them, so a 60-member group over 200 lines was
    ~5.6M subnet_of calls / ~23s. The integer form is the same predicate at a fraction of the cost, and it
    is total across families (subnet_of RAISES on a v4/v6 pair)."""
    return int(n.network_address), int(n.broadcast_address), n.version


def _pref_inter(A, B):
    if not A or not B:
        return []
    Bb = [(_bounds(b), b) for b in B]
    out = []
    for a in A:
        (an, ax, av) = _bounds(a)
        for (bn, bx, bv), b in Bb:
            if bv != av:
                continue                                  # different family -> no overlap (never a raise)
            if an >= bn and ax <= bx:
                out.append(a)
            elif bn >= an and bx <= ax:
                out.append(b)
    return _collapse(out)


def _pref_diff(A, B):
    res = list(A)
    for b in B:
        bn, bx, bv = _bounds(b)
        new = []
        for r in res:
            rn, rx, rv = _bounds(r)
            if rv != bv:
                new.append(r)                             # different family -> disjoint
            elif rn >= bn and rx <= bx:
                continue                                  # r removed entirely
            elif bn >= rn and bx <= rx:
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
    tbl = _as_dict(ogs)
    try:
        og = tbl.get(name)
    except TypeError:                       # an UNHASHABLE group name (a dict/list leaf) can never
        return None, "undefined"            # name a real object-group -> undefined, not a crash
    if og is None:
        return None, "undefined"
    if not isinstance(og, dict):            # a truthy non-dict group body (str/int/list) is not a
        return None, "undefined"            # readable definition -> abstain exactly like an absent one
    if name in seen:
        return None, "cyclic"
    seen = seen | {name}
    prefixes = []
    for m in _as_list(og.get("members")):
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


def _port_num(v):
    """A port operand coerced to an int in [0, 65535], or None (= unevaluable) for anything else.

    THE choke point for the port dimension: every branch of _port_intervals feeds `v`/`v2` straight into
    integer arithmetic and then into `_iv_norm`'s `lo <= hi` / `_iv_inter`'s `max()/min()`. A parsed rule
    read back from an UNTRUSTED snapshot can carry a str, a list or a float there (a foreign-tool export,
    an older schema, a hand-trim), and the comparison raises
    `TypeError: '<=' not supported between instances of 'str' and 'int'` -- aborting
    compute_filter_line_reachability for the whole fleet over one malformed ACE.

    Returning None routes that line to the SAME abstention an unknown port name already takes
    (-> INDETERMINATE), never a narrower box: a line whose ports could not be read must never be used to
    "prove" a later line dead. bool is rejected explicitly -- True would silently model port 1."""
    if isinstance(v, bool) or not isinstance(v, int):
        return None
    return v if 0 <= v <= 65535 else None


def _port_intervals(p) -> Optional[list]:
    """{op,val,val2?} -> [(lo,hi)] interval-set over [0,65535]; None for the whole space; [] when empty."""
    if p is None:
        return [(0, 65535)]
    if not isinstance(p, dict):
        return None
    op, v, v2 = p.get("op"), _port_num(p.get("val")), _port_num(p.get("val2"))
    if v is None:
        return None                                        # unknown / unreadable port operand -> unevaluable
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


def _is_group_spec(spec) -> bool:
    return isinstance(spec, dict) and spec.get("group") is not None


def _rule_box(rule, ogs, host) -> Tuple[dict, str]:
    """Parsed rule -> (over-approximating box, status). Unevaluable dims fall back to FULL."""
    # A non-dict ELEMENT in the rules list (a bare string / int / None from a hand-trimmed or
    # foreign-tool snapshot) must degrade to the FULL, UNEVALUABLE box -- never a `.get` AttributeError,
    # and never a narrow box, which would let the algebra "prove" a later line dead against a rule it
    # could not actually read (a false BLOCKING_LINES verdict is worse than an abstention).
    rule = _as_dict(rule)
    src_spec, dst_spec = rule.get("src"), rule.get("dst")
    src, st_s = _addr_prefixes(src_spec, ogs, host)
    dst, st_d = _addr_prefixes(dst_spec, ogs, host)
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
        elif src is None or dst is None or sport is None or dport is None:
            status = "unevaluable"                          # a dimension THIS module could not resolve
        elif rule.get("unevaluable") and not (_is_group_spec(src_spec) or _is_group_spec(dst_spec)):
            # The parser's own flag, MINUS the one cause this module resolves natively. parse.py's
            # _acl_addr returns unevaluable=True for EVERY object-group address spec (it cannot expand
            # them), so honoring the flag unconditionally made _group_prefixes/_addr_prefixes DEAD CODE
            # on real snapshots: every object-group ACE landed in n_indeterminate with a reason blaming
            # a "non-contiguous wildcard". When the rule's group reference RESOLVED (undefined/cyclic
            # were caught above, and a bad member leaves src/dst None), the flag is fully explained and
            # the exact box stands. Every OTHER cause still abstains: an unknown port name (val None ->
            # the dim is None) and an address token the parser could not read — for that one the parser
            # substitutes `any`, so this flag is the ONLY signal and it must never be dropped.
            # Residual (documented, not silent): an ACE carrying BOTH a resolvable object-group AND an
            # unreadable address token is indistinguishable from `object-group X ... any` and would be
            # treated as evaluable; the two shapes are not separable from the parser's output.
            status = "unevaluable"
    return box, status


def _uneval_detail(rule, ogs, host) -> str:
    """NAME the dimension that could not be modelled, instead of blaming a non-contiguous wildcard for
    every abstention (the reason string is surfaced on the shipped 'ACL Shadow Analysis' sheet)."""
    bits = []
    for key in ("src", "dst"):
        pl, _st = _addr_prefixes(rule.get(key), ogs, host)
        if pl is None:
            bits.append("%s address (IPv6, a non-contiguous wildcard, or a token the parser could not read)" % key)
    for key in ("sport", "dport"):
        if _port_intervals(rule.get(key)) is None:
            bits.append("%s (unknown port name or malformed operator)" % key)
    if bits:
        return "cannot model " + "; ".join(bits)
    if rule.get("unevaluable"):
        return "the parser flagged this line unevaluable — an address/port form it could not model"
    return "unparseable address/port"


def _finding(idx, rule, reason, blocking_lines=None, different_action=False, detail=""):
    return {"line_index": idx, "action": rule.get("action"), "raw": rule.get("raw", ""),
            "reason": reason, "verdict": Verdict.from_acl_reason(reason).value,
            "blocking_lines": blocking_lines or [],
            "different_action": bool(different_action), "detail": detail}


def analyze_acl(rules: List[dict], object_groups: Optional[dict] = None, host: Optional[str] = None) -> List[dict]:
    """One ACL's rules -> a list of findings (one per non-REACHABLE line). Pure; never raises."""
    ogs = _as_dict(object_groups)
    meta = []
    for r in _as_list(rules):
        box, st = _rule_box(r, ogs, host)
        rd = _as_dict(r)                 # a non-dict rule ELEMENT degrades to an unevaluable line
        est = bool(rd.get("established") or rd.get("reflexive"))
        meta.append((box, st, str(rd.get("action") or "").lower(), est, rd))

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
            why = "time-range — active only in a window" if st == "timerange" else _uneval_detail(r, ogs, host)
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
    # _as_dict at every hop, not `or {}`: acls / object_groups is a THREE-level nested section
    # (host -> acl-name -> rules), and a truthy non-dict at ANY hop -- the whole section, one host's
    # table, one group's body -- survives `or {}` and dies on the next `.items()` / `.get()`. This
    # runs over every snapshot the engine analyses, so one malformed host aborted the whole run.
    acls_by_host = _as_dict(_as_dict(snap).get("acls"))
    ogs_by_host = _as_dict(_as_dict(snap).get("object_groups"))
    findings: List[dict] = []
    for host, acls in acls_by_host.items():
        ogs = _as_dict(ogs_by_host.get(host))
        for name, rules in _as_dict(acls).items():
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
    """Query headers -> (5-D box, [header keys this IPv4 algebra cannot model]).

    The IPv4-family guard the RULE side has carried since the first review wave (`_addr_prefixes`
    ~:106/:118, "IPv6 -> abstain, never mangle into a wrong v4 prefix") applies identically here — the
    header side was simply missing it, and it fails two ways: an IPv6 CIDR reaches `_pref_inter` and
    raises TypeError ("not of the same version") out of search_filters, while a BARE v6 address (no '/')
    fell through `str(v) + "/32"` into the except branch and was silently answered over the WHOLE IPv4
    space (0.0.0.0/0) — a wrong answer being worse than a crash."""
    h = h or {}
    unmodelled = []

    def addr(key):
        v = h.get(key)
        if not v:
            return list(_FULL_NET)
        s = str(v).strip()
        try:
            if "/" in s:
                net = ipaddress.ip_network(s, strict=False)
            else:
                ip = ipaddress.ip_address(s.split("%", 1)[0])       # tolerate a zone-id, like fib._ip
                net = ipaddress.ip_network("%s/%d" % (ip, 32 if ip.version == 4 else 128))
        except (ValueError, TypeError):
            return list(_FULL_NET)                                  # unreadable value -> no constraint
        if net.version != 4:
            unmodelled.append(key)                                  # IPv6 -> abstain (never a v4 answer)
            return list(_FULL_NET)
        return [net]

    def prt(key):
        v = h.get(key)
        return [(int(v), int(v))] if v is not None else [(0, 65535)]

    proto = _proto_of(h.get("proto")) if h.get("proto") else PROTO_FULL
    return ({"proto": proto, "src": addr("src"), "dst": addr("dst"),
             "sport": prt("sport"), "dport": prt("dport")}, unmodelled)


def _proto_witness(bp, header_proto):
    """A concrete protocol token admitted by the box's proto set (so the witness actually achieves the verdict)."""
    kind, s = bp if (isinstance(bp, tuple) and len(bp) == 2) else ("allexcept", frozenset())
    if kind == "only":
        return sorted(s)[0] if s else (_canon_proto(header_proto) or "ip")
    for cand in (header_proto, "icmp", "tcp", "udp", "gre", "esp", "ospf", "ip"):   # allexcept S: one not excluded
        c = _canon_proto(cand)                     # canonical, so '6' is not offered when 'tcp' is excluded
        if c and c not in s:
            return c
    return _canon_proto(header_proto) or "ip"


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

    Returns {result:'WITNESS', flow:{…}, matched_by} with a concrete 5-tuple, {result:'PROVEN_NONE',
    detail} when no packet in the space gets `action`, or {result:'INDETERMINATE', detail} when the query
    cannot be decided (an unevaluable line overlaps the undecided space, or the query itself is outside
    the model — an IPv6 header). Coverage-honest: never a false PROVEN_NONE.

    The terminating **implicit `deny ip any any`** every Cisco ACL carries IS modelled: whatever the
    explicit lines leave unmatched is DENIED, so `action='deny'` on an all-permit ACL yields a witness
    rather than "proven to deny nothing" — a formal proof of 'no' for a filter that in reality blocks
    everything but its permits. (An empty rule list therefore models an ACL that exists with no ACEs:
    the implicit deny still terminates it.)"""
    # the same guards analyze_acl carries -- search_filters is the second public entry into the
    # same rule algebra and read the SAME untrusted snapshot sections without them.
    ogs = _as_dict(object_groups)
    action = str(action or "permit").lower()
    q_box, unmodelled = _headers_box(headers)
    if unmodelled:                                     # IPv6 query vs an IPv4-only algebra -> abstain
        return {"result": "INDETERMINATE",
                "detail": "query header %s is IPv6; this filter algebra models IPv4 only (the rule side "
                          "abstains identically) — an IPv4 answer would not be about the packet asked "
                          "about" % ", ".join(sorted(set(unmodelled)))}
    q_remaining = [q_box]
    hits: List[dict] = []
    for i, r in enumerate(_as_list(rules)):
        if not q_remaining:
            break
        box, st = _rule_box(r, ogs, host)
        r = _as_dict(r)                                     # a non-dict rule ELEMENT degrades to an
        if r.get("established") or r.get("reflexive"):      # unevaluable line (see _rule_box), never a .get crash
            continue                                        # never matches a forward flow
        overlaps = [o for o in (_box_inter(b, box) for b in q_remaining) if not _box_empty(o)]
        if not overlaps:
            continue
        if st != "ok":
            if hits:                                       # a witness already matched an earlier first-match line -> sound
                return {"result": "WITNESS", "flow": _witness(hits[0], headers), "matched_by": "explicit line"}
            return {"result": "INDETERMINATE", "detail": "line %d (%s) is unevaluable and overlaps the query space" % (i, r.get("raw", ""))}
        if (r.get("action") or "").lower() == action:
            hits.extend(overlaps)
        new_q = []
        for b in q_remaining:
            new_q.extend(_box_subtract(b, box))
        q_remaining = [b for b in new_q if not _box_empty(b)]
    if hits:
        return {"result": "WITNESS", "flow": _witness(hits[0], headers), "matched_by": "explicit line"}
    if action == "deny" and q_remaining:
        # The implicit `deny ip any any` that terminates EVERY Cisco ACL: the query space the explicit
        # lines did not consume is denied by it. Without this the function "proved" (PROVEN_NONE) that an
        # ACL with no explicit deny denies nothing.
        return {"result": "WITNESS", "flow": _witness(q_remaining[0], headers),
                "matched_by": "implicit deny ip any any"}
    return {"result": "PROVEN_NONE",
            "detail": "no packet in the query space resolves to '%s' (the terminating implicit "
                      "`deny ip any any` is included in the model)" % action}
