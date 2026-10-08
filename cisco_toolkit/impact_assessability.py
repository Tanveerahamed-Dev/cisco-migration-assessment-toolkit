"""Engine-owned assessability of the stored failure-impact rows (W33, follow-up F5).

``analyze.compute_failure_impact`` writes one row per scanned switch: a severity band, five counts and a detail
sentence. Several kinds of row are not measurements, and nothing in a row's own numbers says so:

* the producer's own INDETERMINATE detail (it could not simulate the switch) still carries Info and zero counts;
* a row older than the producer's ``off_scan_gw_vlans`` marker may hold a clean bill written for a switch the
  engine could not simulate;
* a device whose scoped interface running-config was never captured (no interface carries
  ``run_config_observed: true``) entered the simulation without its own gateway addresses;
* a row that simulated only some of its VLANs counts the rest in ``off_scan_gw_vlans``;
* a switch that the stored cable map cables to an uncollected peer able to carry endpoints (anything but
  positively identified edge gear) has endpoints behind that peer which the scanned-only simulation never counted;
* two rows naming one host cannot both be the producer's row.

This module is the ONE owner of those row-level rules. It never re-simulates: each predicate is a selection over
stored snapshot values (the row, the device's interface records, the stored cable map). The ui_projection shared
row builder (the fleet topology and the device page) and every engine deliverable that renders failure_impact
rows or ranks keystones from them consume it. A row therefore cannot be withheld on a screen while a document
publishes it as "Info / 0 stranded".

Per stored row the verdict is one of :data:`VERDICTS`:

* ``published``: the row's values are the producer's measurements;
* ``lower_bound``: a bound applies (off-scan VLANs, an uncollected neighbour, or a cable map that cannot be
  read). The worst band and each positive count are lower bounds. A band below the worst, a zero count and a
  detail that names no simulated VLAN are not measurements;
* ``not_assessed``: a hold applies, so none of the row's blast-radius values is a measurement. The producer's
  INDETERMINATE detail stays readable as its own disclosure;
* ``ambiguous``: two or more rows name this exact host, so no single row can be chosen.

The withheld states (:data:`NOT_COLLECTED`, :data:`UNVERIFIED`, :data:`ANALYSIS_UNAVAILABLE`) are the abstention
codomain of ``ssot`` plus the projection's domain token, so the projection can carry them unchanged.

Pure and total: no I/O, no clock, never mutates its input, and never raises on a malformed snapshot.
"""
from __future__ import annotations

import math
from types import MappingProxyType
from typing import Any, Callable, Dict, FrozenSet, List, Mapping, NamedTuple, Optional, Sequence, Tuple

from cisco_toolkit import ssot

SCHEMA = "failure_impact_assessability/1"

PUBLISHED = "published"
LOWER_BOUND = "lower_bound"
NOT_ASSESSED = "not_assessed"
AMBIGUOUS = "ambiguous"
#: The row verdicts, from a measurement to no single row at all.
VERDICTS: Tuple[str, ...] = (PUBLISHED, LOWER_BOUND, NOT_ASSESSED, AMBIGUOUS)
#: The reader-facing words for each verdict.
VERDICT_LABELS: Mapping[str, str] = MappingProxyType({
    PUBLISHED: "published", LOWER_BOUND: "lower bound", NOT_ASSESSED: "not assessed", AMBIGUOUS: "ambiguous"})

#: The withheld-cell states: two of the ssot abstention codomain plus the projection's unverified domain token.
ANALYSIS_UNAVAILABLE = ssot.ANALYSIS_UNAVAILABLE
NOT_COLLECTED = "not_collected"
UNVERIFIED = "unverified"
_COLLECTED_BUT_EMPTY = "collected_but_empty"

#: analyze.compute_failure_impact's severity bands, worst first (its sev_rank order).
IMPACT_SEVERITIES: Tuple[str, ...] = ("High", "Medium", "Low", "Info")
#: The producer's worst band: the one severity a partial simulation cannot understate.
IMPACT_WORST = IMPACT_SEVERITIES[0]
#: analyze.compute_failure_impact's own opening for a switch whose blast radius it could not simulate (a VLAN it
#: carries has an off-scan gateway, or its inter-switch links carry no VLAN evidence). Its Info severity and zero
#: counts are then not measurements. Pinned to the real producer by tests/test_impact_assessability.py.
IMPACT_INDETERMINATE_PREFIX = "Blast radius INDETERMINATE"
#: The failure-impact cells that measure the simulated blast radius; host, off_scan_gw_vlans and detail do not.
IMPACT_MEASURES: Tuple[str, ...] = ("severity", "vlans_impacted", "stranded", "hard", "backup", "fhrp")
#: The stored row's fields in the producer's write order.
IMPACT_FIELDS: Tuple[str, ...] = ("host",) + IMPACT_MEASURES + ("off_scan_gw_vlans", "detail")
#: analyze.compute_cable_map's kinds for an uncollected peer it POSITIVELY identifies as edge gear: its fabric-only
#: declutter may hide only these, and 'unknown' always stays visible. _node_kind ranks infra first across every
#: observer (_KIND_RANK puts switch, router and firewall before ap, phone and endpoint) and lets platform evidence
#: outrank endpoint type, so a peer carries one of these kinds only when no observer's evidence says switch, router or
#: firewall; build_network_model likewise never admits a CDP-speaking phone or AP as an uplink
#: (_is_offscan_uplink_port). What hangs off an AP or a phone depends on the removed switch's own port, the case the
#: simulation excludes by its declared scope (the removed switch's own endpoints move with it). Every other kind --
#: switch, router, firewall, unknown, a missing or unrecognised kind, or the collected-device kind on a node marked
#: uncollected -- can carry endpoints or transit that the scanned model never saw.
IMPACT_EDGE_KINDS = frozenset({"ap", "phone", "endpoint"})
#: The largest integer a browser holds exactly: a count above it is not readable (the projection's slot rule).
JS_MAX_SAFE_INT = 2 ** 53 - 1

R_INDETERMINATE = ("not collected: analyze.compute_failure_impact could not simulate this switch's blast "
                   "radius (its detail says why), so its severity and counts are not measurements")
R_LEGACY = ("not collected: this stored row carries no off_scan_gw_vlans, so it predates the producer's "
            "assessability marker (analyze.compute_failure_impact). An engine that old wrote 'No reachability "
            "impact' with Info and zero counts for a switch it could not simulate, so this row's severity and "
            "counts are not measurements")
R_OFF_SCAN_ONLY = ("not collected: every VLAN analyze.compute_failure_impact found on this switch has an "
                   "off-scan gateway ({n} counted in off_scan_gw_vlans), so it simulated none of them and its "
                   "severity and counts are not measurements")
R_OFF_SCAN_UNREAD = ("unverified: off_scan_gw_vlans is not a count, so whether the simulation covered this "
                     "switch's whole blast radius cannot be read")
R_NO_HOST = ("unverified: the row names no readable host, so whether its device's interface running-config "
             "was captured cannot be checked")
R_DUP = ("unverified: {n} rows in failure_impact name this exact host, but analyze.compute_failure_impact "
         "writes one row per host, so no single row can be chosen")
R_NO_RUN_CONFIG = ("not collected: no interface of this device carries run_config_observed: true. build.py "
                   "marks every interface its scoped interface running-config capture ('show running-config "
                   "interface' or '| section ^interface') parsed, and takes SVI gateway addresses (svi_ip) "
                   "only from that capture, so this device's own gateways never reached the simulation and "
                   "its severity and counts are not measurements. A snapshot that predates the marker, or "
                   "drops it as false (html.sparsify_interfaces), reads the same: not captured")
R_UNDERSTATED = ("not collected: this severity may understate the blast radius: {n} VLAN(s) on this switch "
                 "have an off-scan gateway the simulation could not assess (off_scan_gw_vlans), and only the "
                 "worst band ({worst}) cannot be understated")
R_ZERO_BOUND = ("not collected: this 0 is only a lower bound: {n} VLAN(s) on this switch have an off-scan "
                "gateway the simulation could not assess (off_scan_gw_vlans), so it is not a measurement of "
                "none")
R_OFF_SCAN_BOUND = ("not collected: {n} VLAN(s) on this switch have an off-scan gateway the simulation could not "
                    "assess (off_scan_gw_vlans), so its severity and counts are lower bounds")
R_PEERS = ("this row cannot account for endpoints behind {n} uncollected neighbour(s): the stored cable map "
           "cables this switch to {n} peer(s) it does not show as collected that can carry endpoints or "
           "transit (a cable_map.nodes row with collected: false and a kind other than ap, phone or endpoint, "
           "or a cable end that does not join exactly one node){closed}, and analyze.compute_failure_impact "
           "counts only endpoints on scanned switches")
R_PEERS_CLOSED = ("; {k} of them fail closed because their cable row cannot be read or their cable end does "
                  "not join exactly one node, so they are never assumed collected")
R_PEERS_UNREAD = ("whether this switch faces an uncollected neighbour cannot be checked, because the stored "
                  "cable map's cables cannot be read ({why}), and analyze.compute_failure_impact counts only "
                  "endpoints on scanned switches")
R_PEER_SEVERITY = ("{word}: {clause}, so this severity may understate the blast radius, and only the worst "
                   "band ({worst}) cannot be understated")
R_PEER_ZERO = "{word}: {clause}, so this 0 is only a lower bound, not a measurement of none"
R_PEER_DETAIL = ("{word}: {clause}, so this detail, which names no simulated VLAN, is not a clean bill: it was "
                 "never checked against what lies behind them")
R_NOT_OBJECT = "unverified: the engine row is not an object, so none of its fields can be read"
R_SECTION_UNAVAILABLE = ("analysis unavailable: the failure-impact phase failed this run, so none of its rows is a "
                         "measurement")
R_SECTION_FAULT = ("unverified: the abstention owner raised on this snapshot, so whether the failure-impact phase "
                   "completed cannot be read")
#: The default cable-map reading's reasons (ui_projection supplies its own, from its envelope reading).
R_CABLES_UNAVAILABLE = "analysis unavailable: the cable-map phase failed this run"
R_CABLES_UNVERIFIED = "unverified: the stored cable map cannot be read as a list of cables"
R_CABLES_ABSENT = "not collected: this snapshot carries no cable map"

#: The leading word of a withheld state's reason.
STATE_WORD: Mapping[str, str] = MappingProxyType({
    ANALYSIS_UNAVAILABLE: "analysis unavailable", UNVERIFIED: "unverified", NOT_COLLECTED: "not collected"})

#: The reader-facing phrase for each reason code (no engine-internal names: deliverables quote these).
CODE_PHRASES: Mapping[str, str] = MappingProxyType({
    "section_unavailable": "the failure-impact analysis did not complete this run",
    "row_unreadable": "the stored row cannot be read",
    "duplicate_host": "{n} rows name this switch, so no single result can be chosen",
    "indeterminate": "the simulation could not assess this switch (its detail says why)",
    "legacy_row": "the row predates the engine's assessability marker",
    "off_scan_unreadable": "its off-scan VLAN count cannot be read",
    "no_host": "the row names no readable switch",
    "no_run_config": "its interface running-config, the only source of its gateway addresses, was not captured",
    "off_scan_only": "every VLAN on it has a gateway outside the scan ({n} VLAN(s))",
    "off_scan_partial": "{n} VLAN(s) on it have a gateway outside the scan that was not simulated",
    "uncollected_neighbours": "it faces {n} uncollected neighbour(s) that can carry endpoints",
    "neighbours_unreadable": "the cable map cannot be read to check its neighbours",
})

_OWNER_FAULTS = (RecursionError, TypeError, ValueError, AttributeError, KeyError, IndexError, OverflowError)
_FAULT = "\x00owner-fault"
_MISSING = object()

#: One witness: ``(ref role, snapshot tokens)``, the shape ui_projection resolves into a ref.
Entry = Tuple[str, Tuple[Any, ...]]


class Hold(NamedTuple):
    """Withholds every blast-radius measure of one row (state, reason and witnesses lead, as the projection reads)."""
    state: str
    reason: str
    witnesses: List[Entry]
    code: str
    n: int = 0


class Bound(NamedTuple):
    """Qualifies a row's understatable values: a band below the worst, a zero count and, where ``detail_reason`` is
    set, a detail that names no simulated VLAN. Its witnesses are cited by every measure, the lower bounds
    included."""
    state: str
    severity_reason: str
    zero_reason: str
    detail_reason: Optional[str]
    witnesses: List[Entry]
    code: str
    n: int
    reason: str


class Doubt(NamedTuple):
    """Two or more rows name this exact host: every cell is unverified, with a witness to each such row."""
    state: str
    reason: str
    witnesses: List[Entry]
    n: int


class RowFacts(NamedTuple):
    """The owner's facts about one stored row, in the order the projection applies them."""
    doubt: Optional[Doubt]
    hold: Optional[Hold]
    bounds: Tuple[Bound, ...]


class CableSource(NamedTuple):
    """One reading of the stored cable map. ``state`` is ``None`` when the cable list can be read; otherwise it is
    the withheld state, ``why`` the reason and ``witnesses`` what witnesses it. ``by_end``, ``unjoinable`` (ascending)
    and ``node_index`` are the exact-text joins over the readable lists (``nodes`` is ``None`` when the node list
    cannot be read, so no far end joins a node); ``unjoinable_set`` is ``unjoinable`` for membership tests."""
    state: Optional[str]
    why: str
    witnesses: Tuple[Entry, ...]
    cables: Sequence[Any]
    nodes: Optional[Sequence[Any]]
    by_end: Mapping[str, Sequence[int]]
    unjoinable: Sequence[int]
    node_index: Mapping[str, Sequence[int]]
    unjoinable_set: FrozenSet[int] = frozenset()


# ---------------------------------------------------------------------------------------------------
# value checks (the projection's slot rules for text and counts, held equal by the parity tests)
# ---------------------------------------------------------------------------------------------------
def _is_text(value: Any) -> bool:
    """A string a UTF-8 encoder can write (a lone surrogate is not text)."""
    if not isinstance(value, str):
        return False
    if value.isascii():
        return True
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _count(raw: Any) -> Tuple[bool, Any]:
    """``(readable, value)`` of a count: a non-bool integer, or an integral finite float, in [0, 2**53-1]."""
    if isinstance(raw, bool):
        return False, None
    if isinstance(raw, int):
        return (0 <= raw <= JS_MAX_SAFE_INT), (int(raw) if 0 <= raw <= JS_MAX_SAFE_INT else None)
    if isinstance(raw, float) and math.isfinite(raw) and raw.is_integer() and 0 <= raw <= JS_MAX_SAFE_INT:
        return True, int(raw)
    return False, None


def json_pointer(*tokens: Any) -> str:
    """RFC 6901: ``~`` -> ``~0`` first, then ``/`` -> ``~1``; list indices are decimal."""
    return "".join("/" + str(tok).replace("~", "~0").replace("/", "~1") for tok in tokens)


def _get(doc: Any, tokens: Sequence[Any]) -> Any:
    """Follow str tokens through dicts and int tokens through lists; ``_MISSING`` when it does not resolve."""
    cur = doc
    for tok in tokens:
        if isinstance(cur, dict) and isinstance(tok, str):
            if tok not in cur:
                return _MISSING
            cur = cur[tok]
        elif isinstance(cur, list) and isinstance(tok, int) and not isinstance(tok, bool):
            if not 0 <= tok < len(cur):
                return _MISSING
            cur = cur[tok]
        else:
            return _MISSING
    return cur


def index_rows(rows: Any, fields: Tuple[str, ...]) -> Dict[str, List[int]]:
    """Exact text -> every row index naming it in one of `fields` (a row names a value once even when two fields
    carry it). Rows that are not objects, and fields that are not text, name nothing. Duplicates stay visible."""
    out: Dict[str, List[int]] = {}
    for i, row in enumerate(rows if isinstance(rows, list) else ()):
        if not isinstance(row, dict):
            continue
        names = [row[f] for f in fields if _is_text(row.get(f))]
        for name in dict.fromkeys(names):
            out.setdefault(name, []).append(i)
    return out


def unjoinable_rows(rows: Any, fields: Tuple[str, ...]) -> List[int]:
    """The rows an exact-key join over text `fields` cannot read: not an object, or a key field that is missing or
    not text. Any of them could name the host being joined."""
    return [i for i, row in enumerate(rows if isinstance(rows, list) else ())
            if not (isinstance(row, dict) and all(_is_text(row.get(f)) for f in fields))]


# ---------------------------------------------------------------------------------------------------
# the row-level predicates
# ---------------------------------------------------------------------------------------------------
def row_hold(rec: Any, toks: Sequence[Any], interfaces: Any) -> Optional[Hold]:
    """The hold on every blast-radius measure of one stored row, with a witness to the evidence that says why. First
    match wins: the producer's INDETERMINATE detail -> no off_scan_gw_vlans (a row older than that marker) -> an
    unreadable off-scan count -> no readable host -> no interface of the row's device carrying
    ``run_config_observed: true`` (its gateway SVIs never reached the simulation; absent is never read as
    captured) -> a positive off-scan count with no VLAN simulated (the INDETERMINATE case, read from the count
    rather than the prose). ``None``: the measures are the producer's (a partial row's are then qualified per value
    by :func:`measure_withheld`)."""
    if not isinstance(rec, dict):
        return None
    toks = tuple(toks)
    detail = rec.get("detail")
    if _is_text(detail) and detail.startswith(IMPACT_INDETERMINATE_PREFIX):
        return Hold(NOT_COLLECTED, R_INDETERMINATE, [("witness", toks + ("detail",))], "indeterminate")
    if "off_scan_gw_vlans" not in rec:
        return Hold(NOT_COLLECTED, R_LEGACY, [("witness", toks)], "legacy_row")
    ok, n = _count(rec["off_scan_gw_vlans"])
    if not ok:
        return Hold(UNVERIFIED, R_OFF_SCAN_UNREAD, [("witness", toks + ("off_scan_gw_vlans",))],
                    "off_scan_unreadable")
    host = rec.get("host")
    if not _is_text(host):
        return Hold(UNVERIFIED, R_NO_HOST, [("witness", toks)], "no_host")
    ports = interfaces.get(host) if isinstance(interfaces, dict) else None
    if not (isinstance(ports, dict) and any(isinstance(port, dict) and port.get("run_config_observed") is True
                                            for port in ports.values())):
        where = ("interfaces", host) if isinstance(ports, dict) else ("interfaces",)
        return Hold(NOT_COLLECTED, R_NO_RUN_CONFIG, [("witness", where)], "no_run_config")
    simulated_ok, simulated = _count(rec.get("vlans_impacted"))
    if n and not (simulated_ok and simulated):
        return Hold(NOT_COLLECTED, R_OFF_SCAN_ONLY.format(n=n), [("witness", toks + ("off_scan_gw_vlans",))],
                    "off_scan_only", n)
    return None


def off_scan_count(rec: Any) -> int:
    """The row's readable, positive off-scan VLAN count (0 otherwise)."""
    ok, n = _count(rec.get("off_scan_gw_vlans")) if isinstance(rec, dict) else (False, None)
    return n if ok else 0


def off_scan_bound(rec: Any, toks: Sequence[Any]) -> Optional[Bound]:
    """The bound a positive off-scan count puts on a row: the simulation covered only its VLANs with an in-scan
    gateway. It reaches no detail (a per-VLAN detail lists only what was simulated). ``None``: no such count."""
    n = off_scan_count(rec)
    if not n:
        return None
    wit: List[Entry] = [("witness", tuple(toks) + ("off_scan_gw_vlans",))]
    return Bound(NOT_COLLECTED, R_UNDERSTATED.format(n=n, worst=IMPACT_WORST), R_ZERO_BOUND.format(n=n), None, wit,
                 "off_scan_partial", n, R_OFF_SCAN_BOUND.format(n=n))


def make_bound(state: str, clause: str, wit: List[Entry], code: str, n: int) -> Bound:
    """One neighbour :class:`Bound` from a reason clause: it reaches the detail too (a detail naming no simulated VLAN
    is the producer's clean bill, never checked against what lies behind the neighbour)."""
    word = STATE_WORD[state]
    return Bound(state, R_PEER_SEVERITY.format(word=word, clause=clause, worst=IMPACT_WORST),
                 R_PEER_ZERO.format(word=word, clause=clause), R_PEER_DETAIL.format(word=word, clause=clause), wit,
                 code, n, f"{word}: {clause}")


def readable_cables(cables: Sequence[Any], nodes: Optional[Sequence[Any]] = None, *,
                    by_end: Optional[Mapping[str, Sequence[int]]] = None,
                    unjoinable: Optional[Sequence[int]] = None,
                    node_index: Optional[Mapping[str, Sequence[int]]] = None) -> CableSource:
    """A readable cable list (and the node list, ``None`` when it cannot be read). Joins not supplied by the caller
    are built here with :func:`index_rows` / :func:`unjoinable_rows`."""
    cables = cables if isinstance(cables, list) else []
    nodes = nodes if isinstance(nodes, list) else None
    bad = sorted(set(unjoinable if unjoinable is not None else unjoinable_rows(cables, ("a", "b"))))
    return CableSource(
        None, "", (), cables, nodes,
        by_end if by_end is not None else index_rows(cables, ("a", "b")), bad,
        (node_index if node_index is not None else index_rows(nodes, ("host",))) if nodes is not None else {},
        frozenset(bad))


def unreadable_cables(state: str, why: str, witnesses: Sequence[Entry]) -> CableSource:
    """A cable list that cannot be read: every row with a readable host is bounded with this state and reason."""
    return CableSource(state, why, tuple(witnesses), [], None, {}, [], {}, frozenset())


def _first(indices: List[int], cap: Optional[int]) -> List[int]:
    return indices if cap is None else indices[:cap]


def neighbour_bound(host: Any, src: CableSource, *, witness_cap: Optional[int] = None) -> Optional[Bound]:
    """The bound an uncollected neighbour puts on the row of `host`. analyze.compute_failure_impact simulates only
    scanned switches, so endpoints behind a peer the collection never reached count nowhere: not as stranded, not
    as an off-scan VLAN. A SELECTION of stored rows, never a re-simulation: the stored cable_map.cables rows naming
    the host as one end (exact text) whose far end joins exactly one cable_map.nodes row that does not carry
    ``collected: true``, unless that node is ``collected: false`` with a kind the producer positively marks as edge
    gear (:data:`IMPACT_EDGE_KINDS`). It fails closed: a cable row that cannot be read could name the host, a far
    end that joins no single node is never assumed collected, and a cable list that cannot be read bounds the row
    with that reading's own state. ``None``: no such neighbour (or no readable host).

    The witnesses are every bounding cable row in ascending index order. A cable row the join cannot read bounds
    EVERY row, so a hostile list of them makes the witnesses grow with rows x cables: `witness_cap` keeps only the
    first ones for a reader that renders no witness list (the counts and reasons are unchanged); the projection
    passes none."""
    if not _is_text(host):
        return None
    if src.state is not None:
        return make_bound(src.state, R_PEERS_UNREAD.format(why=src.why), list(src.witnesses),
                          "neighbours_unreadable", 0)
    toks = ("cable_map", "cables")
    cables, nodes, bad = src.cables, src.nodes, src.unjoinable_set
    own: List[int] = []                      # bounding rows the join CAN read, ascending
    peers: Dict[str, bool] = {}              # far end -> whether it fails closed (joins no single node)
    for j in sorted(set(src.by_end.get(host, [])) - bad):
        ends = (cables[j]["a"], cables[j]["b"])
        far = ends[1] if ends[0] == host else ends[0]
        found = src.node_index.get(far, []) if far else []
        if len(found) == 1 and nodes is not None:
            node = nodes[found[0]]
            kind = node.get("kind")
            if node.get("collected") is True or (
                    node.get("collected") is False and _is_text(kind) and kind in IMPACT_EDGE_KINDS):
                continue
        own.append(j)
        peers[far] = peers.get(far, False) or len(found) != 1
    unreadable = len(src.unjoinable)         # the join cannot read these rows, so each could name this switch
    if not own and not unreadable:
        return None
    closed = unreadable + sum(peers.values())
    n = len(peers) + unreadable
    clause = R_PEERS.format(n=n, closed=R_PEERS_CLOSED.format(k=closed) if closed else "")
    if not unreadable:
        hits = _first(own, witness_cap)
    elif witness_cap is None:
        hits = sorted(own + list(src.unjoinable))
    else:                                    # the first `witness_cap` of the ascending union, without building it
        hits = sorted(own[:witness_cap] + list(src.unjoinable[:witness_cap]))[:witness_cap]
    return make_bound(NOT_COLLECTED, clause, [("witness", toks + (j,)) for j in hits], "uncollected_neighbours", n)


def duplicate_doubt(raw: Any, rows_by_host: Mapping[str, Sequence[int]], *,
                    witness_cap: Optional[int] = None) -> Optional[Doubt]:
    """The doubt on a failure_impact row whose exact host text another row also names. analyze.compute_failure_impact
    writes one row per host of its network model, so two rows naming one host (an exact copy or a contradicting
    record) cannot each be the producer's row, and no single one can be chosen. The witnesses are every such row
    (only the first `witness_cap` for a reader that renders no witness list). ``None``: no readable host, or no other
    row names it."""
    if not (isinstance(raw, dict) and _is_text(raw.get("host"))):
        return None
    same = rows_by_host.get(raw["host"], [])
    if len(same) < 2:
        return None
    shown = same if witness_cap is None else same[:witness_cap]
    return Doubt(UNVERIFIED, R_DUP.format(n=len(same)), [("witness", ("failure_impact", j)) for j in shown], len(same))


def bound_state(bounds: Sequence[Bound]) -> str:
    """The withheld state of several bounds: unavailable, then unverified, then not collected."""
    states = {bound[0] for bound in bounds}
    return ANALYSIS_UNAVAILABLE if ANALYSIS_UNAVAILABLE in states else UNVERIFIED if UNVERIFIED in states \
        else NOT_COLLECTED


def understatable_severity(raw: Any) -> bool:
    """A band a bound cannot vouch for: one of the producer's bands below the worst (it may understate)."""
    return isinstance(raw, str) and raw in IMPACT_SEVERITIES and raw != IMPACT_WORST


def understatable_count(raw: Any) -> bool:
    """A count a bound cannot vouch for: a readable zero (a lower bound of zero is not a measurement of none)."""
    ok, value = _count(raw)
    return ok and value == 0


def measure_withheld(hold: Optional[Hold], field: str, raw: Any,
                     bounds: Sequence[Bound]) -> Optional[Tuple[Any, ...]]:
    """One measure's withholding: the row's hold, else, on a bounded row, the values that bound cannot vouch for (a
    severity below the worst band and a zero count). The worst band and a positive count stay published as the lower
    bounds they are, citing each bound's witnesses; a mistyped value is left to the caller's type check. ``None``:
    the value is published. Otherwise ``(state, reason, witness entries)``."""
    if hold is not None:
        return hold
    if not bounds:
        return None
    if field == "severity":
        if not understatable_severity(raw):
            return None
        reasons = [bound[1] for bound in bounds]
    else:
        if not understatable_count(raw):
            return None
        reasons = [bound[2] for bound in bounds]
    return bound_state(bounds), "; ".join(reasons), [w for bound in bounds for w in bound[4]]


def detail_withheld(hold: Optional[Hold], raw: Any, rec: Any,
                    bounds: Sequence[Bound]) -> Optional[Tuple[Any, ...]]:
    """The detail's withholding. The producer's INDETERMINATE detail is its own disclosure that the switch could not be
    assessed, never a clean bill, so it stays published. Any other detail is withheld with the row's hold: its text
    ('No reachability impact', or per-VLAN results) states what the held measures could not. On a row without a
    hold, a bound that reaches the detail (an uncollected neighbour) withholds a detail that names no simulated VLAN
    (no readable positive vlans_impacted): that is the producer's clean bill. A per-VLAN detail stays published as
    the list of what was simulated; a mistyped detail is left to the caller's type check."""
    if _is_text(raw) and raw.startswith(IMPACT_INDETERMINATE_PREFIX):
        return None
    if hold is not None:
        return hold
    reach = [bound for bound in bounds if bound[3] is not None]
    if not reach or not _is_text(raw):
        return None
    ok, simulated = _count(rec.get("vlans_impacted")) if isinstance(rec, dict) else (False, None)
    if ok and simulated:
        return None
    return bound_state(reach), "; ".join(bound[3] for bound in reach), [w for b in reach for w in b[4]]


# ---------------------------------------------------------------------------------------------------
# the default reading of the stored cable map (ui_projection injects its own envelope reading instead)
# ---------------------------------------------------------------------------------------------------
def _abst(snap: Dict[str, Any], subject: str) -> str:
    try:
        return ssot.abstention_reason(snap, subject)
    except _OWNER_FAULTS:
        return _FAULT


def _list_state(snap: Dict[str, Any], section: str, key: str) -> Tuple[Optional[str], Any]:
    """``(withheld state or None, the list)`` of ``snap[section][key]``, read in the projection's order: a failed
    section (unavailable) or an owner fault (unverified), then an absent list (not collected), then a list that is
    not one, or that the abstention core calls empty while it holds rows (unverified), then a parent that is not an
    object (unverified, unless the section failed)."""
    path = f"{section}.{key}"
    parent = snap.get(section)
    raw = _get(snap, (section, key))
    tokens = (_abst(snap, path), _abst(snap, section))
    if ANALYSIS_UNAVAILABLE in tokens:
        return ANALYSIS_UNAVAILABLE, None
    if _FAULT in tokens:
        state: Optional[str] = UNVERIFIED
    elif tokens[0] == NOT_COLLECTED:
        state = NOT_COLLECTED
    elif not isinstance(raw, list):
        state = UNVERIFIED
    elif raw and tokens[0] == _COLLECTED_BUT_EMPTY:
        state = UNVERIFIED
    else:
        state = None
    if parent is not None and not isinstance(parent, dict):
        state = UNVERIFIED
    return state, (raw if state is None else None)


def read_cable_source(snap: Any) -> CableSource:
    """The engine's own reading of the stored cable map, for a consumer without the projection's envelope reading.
    It follows the projection's list states (pinned equal by the parity tests); its reasons are its own."""
    s = snap if isinstance(snap, dict) else {}
    state, cables = _list_state(s, "cable_map", "cables")
    if state is not None:
        toks = ("cable_map", "cables")
        where = toks if _get(s, toks) is not _MISSING else ("cable_map",)
        why = {ANALYSIS_UNAVAILABLE: R_CABLES_UNAVAILABLE, UNVERIFIED: R_CABLES_UNVERIFIED}.get(
            state, R_CABLES_ABSENT)
        return unreadable_cables(state, why, [("witness", where)])
    nstate, nodes = _list_state(s, "cable_map", "nodes")
    return readable_cables(cables, nodes if nstate is None else None)


# ---------------------------------------------------------------------------------------------------
# one snapshot's rows
# ---------------------------------------------------------------------------------------------------
class ImpactSnapshot:
    """The stored inputs one snapshot gives the row-level predicates, each read once and only on first use. A caller
    with its own exact-key index or cable-map reading (ui_projection) passes them as zero-argument callables, so
    both readings stay the caller's; otherwise the owner builds its own. `witness_cap` bounds each row's witness list
    for a reader that renders none (:func:`neighbour_bound`, :func:`duplicate_doubt`); ``None`` keeps every one."""

    def __init__(self, snap: Any, *, rows_by_host: Optional[Callable[[], Mapping[str, Sequence[int]]]] = None,
                 cables: Optional[Callable[[], CableSource]] = None, witness_cap: Optional[int] = None) -> None:
        self.snap: Dict[str, Any] = snap if isinstance(snap, dict) else {}
        self._rows_by_host_fn = rows_by_host
        self._rows_by_host: Optional[Mapping[str, Sequence[int]]] = None
        self._cables_fn = cables
        self._cables: Optional[CableSource] = None
        self.witness_cap = witness_cap

    def rows_by_host(self) -> Mapping[str, Sequence[int]]:
        if self._rows_by_host is None:
            self._rows_by_host = (self._rows_by_host_fn() if self._rows_by_host_fn is not None
                                  else index_rows(self.snap.get("failure_impact"), ("host",)))
        return self._rows_by_host

    def cable_source(self) -> CableSource:
        if self._cables is None:
            self._cables = self._cables_fn() if self._cables_fn is not None else read_cable_source(self.snap)
        return self._cables

    def row(self, i: int, raw: Any) -> RowFacts:
        """The facts of stored row `i`: the duplicate doubt, the hold, then the bounds (off-scan first, then the
        neighbour bound, which is read only for a row without a hold)."""
        toks = ("failure_impact", i)
        host = raw.get("host") if isinstance(raw, dict) else None
        doubt = (duplicate_doubt(raw, self.rows_by_host(), witness_cap=self.witness_cap) if _is_text(host)
                 else None)
        hold = row_hold(raw, toks, self.snap.get("interfaces"))
        bounds: List[Bound] = []
        scan = off_scan_bound(raw, toks)
        if scan is not None:
            bounds.append(scan)
        if hold is None and _is_text(host):
            peers = neighbour_bound(host, self.cable_source(), witness_cap=self.witness_cap)
            if peers is not None:
                bounds.append(peers)
        return RowFacts(doubt, hold, tuple(bounds))


class RowVerdict:
    """One stored row's assessability, as a deliverable reads it: the verdict, the reason codes, the owner's
    reasons, the evidence pointers (each resolves in the snapshot), and which of the row's cells it withholds."""
    __slots__ = ("index", "raw", "host", "assessable", "codes", "reasons", "pointers", "facts", "_section", "_ns")

    def __init__(self, snap: Dict[str, Any], index: int, raw: Any, facts: RowFacts,
                 section: Optional[Tuple[str, str]]) -> None:
        self.index = index
        self.raw = raw
        self.facts = facts
        self._section = section
        host = raw.get("host") if isinstance(raw, dict) else None
        self.host: Optional[str] = host if _is_text(host) else None
        entries: List[Entry] = []
        self._ns: List[Tuple[str, int]] = []
        if section is not None:
            self.assessable, self.reasons = NOT_ASSESSED, [section[1]]
            self._ns = [("section_unavailable", 0)]
            entries.append(("witness", ("failure_impact", index)))
        elif not isinstance(raw, dict):
            self.assessable, self.reasons = NOT_ASSESSED, [R_NOT_OBJECT]
            self._ns = [("row_unreadable", 0)]
            entries.append(("witness", ("failure_impact", index)))
        else:
            reasons: List[str] = []
            if facts.doubt is not None:
                reasons.append(facts.doubt.reason)
                self._ns.append(("duplicate_host", facts.doubt.n))
                entries += facts.doubt.witnesses
            if facts.hold is not None:
                reasons.append(facts.hold.reason)
                self._ns.append((facts.hold.code, facts.hold.n))
                entries += facts.hold.witnesses
            else:
                for bound in facts.bounds:
                    reasons.append(bound.reason)
                    self._ns.append((bound.code, bound.n))
            for bound in facts.bounds:
                entries += bound.witnesses
            self.reasons = reasons
            self.assessable = (AMBIGUOUS if facts.doubt is not None else NOT_ASSESSED if facts.hold is not None
                               else LOWER_BOUND if facts.bounds else PUBLISHED)
        self.codes: List[str] = [code for code, _n in self._ns]
        pointers: List[str] = []
        for _role, toks in entries:
            pointer = json_pointer(*toks)
            if pointer not in pointers and _get(snap, toks) is not _MISSING:
                pointers.append(pointer)
        self.pointers = pointers

    @property
    def published(self) -> bool:
        return self.assessable == PUBLISHED

    @property
    def why(self) -> str:
        """The reader-facing reasons alone (``""`` for a measurement), one phrase per reason code."""
        return "; ".join(CODE_PHRASES[code].format(n=n) for code, n in self._ns)

    @property
    def summary(self) -> str:
        """The reader-facing phrase: the verdict, then why (``published`` alone for a measurement)."""
        label = VERDICT_LABELS[self.assessable]
        if self.assessable == PUBLISHED:
            return label
        return label + " — " + self.why

    def withholds(self, field: str) -> bool:
        """Whether the row's `field` is not a measurement here (the projection's per-cell rule). The host itself is
        withheld only when the row cannot be read; a deliverable still names a doubted host to identify its rows."""
        if self.assessable == PUBLISHED:
            return False
        if self._section is not None or not isinstance(self.raw, dict):
            return True
        if field == "host":
            return False
        if self.facts.doubt is not None:
            return field in IMPACT_MEASURES or field == "detail"
        hold, bounds = self.facts.hold, self.facts.bounds
        if field in IMPACT_MEASURES:
            return measure_withheld(hold, field, self.raw.get(field), bounds) is not None
        if field == "detail":
            return detail_withheld(hold, self.raw.get("detail"), self.raw, bounds) is not None
        return False

    def as_dict(self) -> Dict[str, Any]:
        """The JSON form: ``{index, host, assessable, codes, why, summary, reasons, pointers, withheld}``."""
        return {"index": self.index, "host": self.host, "assessable": self.assessable, "codes": list(self.codes),
                "why": self.why, "summary": self.summary, "reasons": list(self.reasons),
                "pointers": list(self.pointers), "withheld": [f for f in IMPACT_FIELDS if self.withholds(f)]}


def _section_failure(snap: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    token = _abst(snap, "failure_impact")
    if token == ANALYSIS_UNAVAILABLE:
        return ANALYSIS_UNAVAILABLE, R_SECTION_UNAVAILABLE
    if token == _FAULT:
        return UNVERIFIED, R_SECTION_FAULT
    return None


#: The witness pointers a deliverable verdict keeps per reason: deliverables render the verdict and its phrases, never
#: the witness list, so a hostile list of unreadable cable rows (each bounds every row) cannot grow rows x cables.
DELIVERABLE_WITNESS_CAP = 32


def assess_failure_impact(snap: Any) -> List[RowVerdict]:
    """One :class:`RowVerdict` per stored ``failure_impact`` row, aligned with the stored list (``[]`` when the
    section is not a list). Total: an owner fault on a malformed snapshot reads every row as not assessed. The verdict,
    codes, reasons and withheld cells are exact; each row keeps at most :data:`DELIVERABLE_WITNESS_CAP` witnesses per
    neighbour bound and duplicate doubt."""
    s = snap if isinstance(snap, dict) else {}
    rows = s.get("failure_impact")
    if not isinstance(rows, list):
        return []
    section = _section_failure(s)
    owner = ImpactSnapshot(s, witness_cap=DELIVERABLE_WITNESS_CAP)
    out: List[RowVerdict] = []
    for i, raw in enumerate(rows):
        try:
            facts = owner.row(i, raw)
            out.append(RowVerdict(s, i, raw, facts, section))
        except _OWNER_FAULTS:
            out.append(RowVerdict(s, i, raw, RowFacts(None, None, ()), (UNVERIFIED, R_SECTION_FAULT)))
    return out


def rows_with_verdicts(snap: Any) -> List[Tuple[Dict[str, Any], RowVerdict]]:
    """``(row, verdict)`` for every stored row that is an object, in stored order: the pairs a deliverable renders
    or ranks from."""
    return [(v.raw, v) for v in assess_failure_impact(snap) if isinstance(v.raw, dict)]


def assessment_document(snap: Any) -> Dict[str, Any]:
    """The JSON document of every row's verdict (``failure_impact_assessability/1``), aligned with the stored list,
    with the count per verdict in :data:`VERDICTS` order."""
    rows = [v.as_dict() for v in assess_failure_impact(snap)]
    return {"schema": SCHEMA, "rows": rows,
            "counts": {k: sum(1 for r in rows if r["assessable"] == k) for k in VERDICTS}}


#: What a deliverable table writes for a value the owner withholds (never the stored Info or 0).
NOT_ASSESSED_CELL = "not assessed"


def table_value(verdict: RowVerdict, field: str) -> Any:
    """What a deliverable table writes for `field` of the verdict's row: the stored value when the owner publishes it
    as a measurement; on a lower-bound row, the worst band and a positive count as the lower bounds they are
    (``"High (lower bound)"``, ``"≥ 42"``); :data:`NOT_ASSESSED_CELL` for a value the owner withholds."""
    raw = verdict.raw.get(field) if isinstance(verdict.raw, dict) else None
    if verdict.withholds(field):
        return NOT_ASSESSED_CELL
    if verdict.assessable == LOWER_BOUND and field in IMPACT_MEASURES:
        if field == "severity":
            return f"{raw} (lower bound)" if isinstance(raw, str) else raw
        ok, n = _count(raw)
        return f"≥ {n}" if ok else raw
    return raw


def table_detail(verdict: RowVerdict) -> Any:
    """The detail a deliverable table writes: the producer's detail on a published row; otherwise the verdict and why,
    followed by the producer's detail where the owner still publishes it (its INDETERMINATE disclosure, or a partial
    row's list of the VLANs it did simulate)."""
    raw = verdict.raw.get("detail") if isinstance(verdict.raw, dict) else None
    if verdict.published:
        return raw
    head = verdict.summary[:1].upper() + verdict.summary[1:] + "."
    if not verdict.withholds("detail") and _is_text(raw) and raw:
        return f"{head} Producer detail: {raw}"
    return head


def _disclosed(v: RowVerdict) -> str:
    name = v.host if v.host is not None else f"row {v.index}"
    if v.assessable == LOWER_BOUND and isinstance(v.raw, dict) and not v.withholds("stranded"):
        ok, n = _count(v.raw.get("stranded"))
        if ok and n:
            return f"{name} (strands at least {n} endpoint(s); {v.summary})"
    return f"{name} ({v.summary})"


def disclose(verdicts: Sequence[RowVerdict], limit: int = 5) -> str:
    """One reader-facing phrase naming the rows a ranking leaves out and why, with the cut disclosed. A lower-bound
    row keeps its published positive stranded count as the floor it is:
    ``"core2 (strands at least 42 endpoint(s); lower bound -- it faces 1 uncollected neighbour(s) that can carry
    endpoints); +2 more"``."""
    shown = [_disclosed(v) for v in verdicts[:limit]]
    more = len(verdicts) - len(shown)
    return "; ".join(shown) + (f"; +{more} more" if more > 0 else "")


__all__ = [
    "AMBIGUOUS", "ANALYSIS_UNAVAILABLE", "Bound", "CODE_PHRASES", "CableSource", "DELIVERABLE_WITNESS_CAP", "Doubt",
    "Hold", "IMPACT_EDGE_KINDS",
    "IMPACT_FIELDS", "IMPACT_INDETERMINATE_PREFIX", "IMPACT_MEASURES", "IMPACT_SEVERITIES", "IMPACT_WORST",
    "ImpactSnapshot", "JS_MAX_SAFE_INT", "LOWER_BOUND", "NOT_ASSESSED", "NOT_ASSESSED_CELL", "NOT_COLLECTED",
    "PUBLISHED", "RowFacts", "RowVerdict", "SCHEMA", "STATE_WORD", "UNVERIFIED", "VERDICTS", "VERDICT_LABELS",
    "assess_failure_impact", "assessment_document", "bound_state", "detail_withheld", "disclose", "duplicate_doubt",
    "index_rows", "json_pointer", "make_bound", "measure_withheld", "neighbour_bound", "off_scan_bound",
    "off_scan_count", "read_cable_source", "readable_cables", "row_hold", "rows_with_verdicts", "table_detail",
    "table_value", "understatable_count", "understatable_severity", "unjoinable_rows", "unreadable_cables",
]
