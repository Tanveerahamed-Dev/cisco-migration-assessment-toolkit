"""Engine-owned assessability of the stored failure-impact rows (W33, follow-up F5).

``analyze.compute_failure_impact`` writes one row per scanned switch: a severity band, five counts and a detail
sentence. Several kinds of row are not measurements, and nothing in a row's own numbers says so:

* the producer's own INDETERMINATE detail (it could not simulate the switch) still carries Info and zero counts;
* a row older than the producer's ``off_scan_gw_vlans`` marker may hold a clean bill written for a switch the
  engine could not simulate;
* a device whose scoped interface running-config was never captured (no interface carries
  ``run_config_observed: true``) entered the simulation without its own gateway addresses;
* a row that simulated only some of its VLANs counts the rest in ``off_scan_gw_vlans``;
* a switch with inter-switch links that carry no trunk/STP evidence on either end (the row's ``blind_links``, W32)
  never had a VLAN it transits only over them simulated, and a row older than that per-row count cannot say whether
  it had any;
* a switch that the stored cable map cables to an uncollected peer able to carry endpoints (anything but
  positively identified edge gear) has endpoints behind that peer which the scanned-only simulation never counted;
* two rows naming one host cannot both be the producer's row.

This module is the ONE owner of those row-level rules. It never re-simulates: each predicate is a selection over
stored snapshot values (the row, the device's interface records, the stored cable map). The ui_projection shared
row builder (the fleet topology and the device page) and every engine deliverable that renders failure_impact
rows or ranks keystones from them consume it. A row therefore cannot be withheld on a screen while a document
publishes it as "Info / 0 stranded".

It also owns the WAVE rule (:func:`wave_blast`): how a migration wave's rows add up to one worst-case figure. The
figure is exact only when every device of the wave has a row that is a measurement, no stored row names no readable
host, and the projection carries no fleet qualifier (no partial or never-collected device, and no collection record
it cannot read as one). Otherwise it is a lower bound, and a lower bound of 0 is not assessed. The MOP
(``mop._blast_for``) applies it to this module's own verdicts and the AssessHub cutover plan
(``cutover._worst_blast_radius``) to the projection's rows, which the projection builds from those verdicts and whose
every bound cites a witness that resolves (``ui_projection._impact_witnessed``). So both classify a wave by one rule;
they are still two readings of the rows, not one computation, and their agreement is pinned per variant (a fully
published fleet, a row naming no host, a blind spot, an unreadable collection record, no cable map, a zero lower
bound: ``webapp/tests/test_impact_surfaces.py``), not guaranteed for an input those pins do not cover.

Per stored row the verdict is one of :data:`VERDICTS`:

* ``published``: the row's values are the producer's measurements;
* ``lower_bound``: a bound applies (off-scan VLANs, evidence-less inter-switch links or a row older than their
  count, an uncollected neighbour, or a cable map that cannot be read). The worst band and each positive count are
  lower bounds. A band below the worst, a zero count and a detail that names no simulated VLAN are not
  measurements;
* ``not_assessed``: a hold applies, so none of the row's blast-radius values is a measurement. The producer's
  INDETERMINATE detail stays readable as its own disclosure;
* ``ambiguous``: two or more rows name this exact host, so no single row can be chosen.

The withheld states (:data:`NOT_COLLECTED`, :data:`UNVERIFIED`, :data:`ANALYSIS_UNAVAILABLE`) are the abstention
codomain of ``ssot`` plus the projection's domain token, so the projection can carry them unchanged.

Pure and total: no I/O, no clock, never mutates its input, and never raises on a malformed snapshot.
"""
from __future__ import annotations

import math
import re
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
R_PEER_DETAIL = "{word}: {clause}, so this detail, which names no simulated VLAN, is not a clean bill: {tail}"
#: What a neighbour bound's clean-bill detail was never checked against (the default `tail` of :func:`make_bound`).
R_PEER_TAIL = "it was never checked against what lies behind them"
#: analyze.compute_failure_impact's per-row ``blind_links`` (W32): the switch's inter-switch links with no trunk/STP
#: evidence on either end. Each is absent from every forwarding graph out of ignorance, so a VLAN the switch transits
#: only over one is never simulated for it -- the same understatement as an off-scan VLAN, but invisible in the
#: other fields. A row without the field predates the per-row count.
R_BLIND_UNREAD = ("unverified: blind_links is not a count, so whether this switch has inter-switch links the "
                  "simulation could not see cannot be read")
R_BLIND_ONLY = ("not collected: {n} inter-switch link(s) of this switch carry no trunk/STP evidence (counted "
                "in blind_links) and analyze.compute_failure_impact simulated none of its VLANs, so its "
                "severity and counts are not measurements")
R_BLIND = ("{n} inter-switch link(s) of this switch carry no trunk/STP evidence on either end (blind_links), "
           "so analyze.compute_failure_impact left them out of every forwarding graph and never simulated a "
           "VLAN this switch transits only over them")
R_BLIND_LEGACY = ("this stored row carries no blind_links, so it predates the producer's per-row count of "
                  "inter-switch links with no trunk/STP evidence: an engine that old disclosed such links at "
                  "most in the INDETERMINATE detail of a switch it simulated nothing for, so a switch it "
                  "simulated in part, or wrote a clean bill for, may have had some, and a VLAN it transits "
                  "only over them was never simulated")
#: What a blind-link bound's clean-bill detail was never checked against.
R_BLIND_TAIL = "whether this switch transits a VLAN over those links was never determined"
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
    "blind_links_unreadable": "its count of inter-switch links without VLAN evidence cannot be read",
    "no_host": "the row names no readable switch",
    "no_run_config": "its interface running-config, the only source of its gateway addresses, was not captured",
    "off_scan_only": "every VLAN on it has a gateway outside the scan ({n} VLAN(s))",
    "blind_links_only": ("{n} inter-switch link(s) on it carry no VLAN evidence, and none of its VLANs could be "
                         "simulated"),
    "off_scan_partial": "{n} VLAN(s) on it have a gateway outside the scan that was not simulated",
    "blind_links": ("{n} inter-switch link(s) on it carry no VLAN evidence, so what it carries over them was not "
                    "simulated"),
    "blind_links_legacy": "the row predates the engine's count of inter-switch links without VLAN evidence",
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
    cannot be read, so no far end joins a node); ``unjoinable_set`` is ``unjoinable`` for membership tests.
    ``node_unjoinable`` (ascending) are the node rows the host join cannot read (W43/F6): any of them could be a second
    node for a far end, so while one exists no far end joins exactly one node."""
    state: Optional[str]
    why: str
    witnesses: Tuple[Entry, ...]
    cables: Sequence[Any]
    nodes: Optional[Sequence[Any]]
    by_end: Mapping[str, Sequence[int]]
    unjoinable: Sequence[int]
    node_index: Mapping[str, Sequence[int]]
    unjoinable_set: FrozenSet[int] = frozenset()
    node_unjoinable: Sequence[int] = ()


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
def run_config_captured(interfaces: Any, host: str) -> Tuple[bool, bool]:
    """``(the device has an interface record, one of its interfaces carries run_config_observed: true)``: the scan
    :func:`row_hold` reads for `host`. A pure function of the host and the stored interfaces, so a reader of many rows
    runs it once per host (:meth:`ImpactSnapshot.captured`)."""
    ports = interfaces.get(host) if isinstance(interfaces, dict) else None
    if not isinstance(ports, dict):
        return False, False
    return True, any(isinstance(port, dict) and port.get("run_config_observed") is True for port in ports.values())


def row_hold(rec: Any, toks: Sequence[Any], interfaces: Any, *,
             captured: Optional[Callable[[str], Tuple[bool, bool]]] = None) -> Optional[Hold]:
    """The hold on every blast-radius measure of one stored row, with a witness to the evidence that says why. First
    match wins: the producer's INDETERMINATE detail -> no off_scan_gw_vlans (a row older than that marker) -> an
    unreadable off-scan count -> a ``blind_links`` that is present but not a count -> no readable host -> no
    interface of the row's device carrying ``run_config_observed: true`` (its gateway SVIs never reached the
    simulation; absent is never read as captured) -> a positive off-scan count with no VLAN simulated -> a positive
    ``blind_links`` with no VLAN simulated (each the INDETERMINATE case, read from the count rather than the prose).
    ``None``: the measures are the producer's (a partial row's are then qualified per value by
    :func:`measure_withheld`). An ABSENT ``blind_links`` is no hold: the row predates that count, and
    :func:`blind_bound` bounds what it may hide. `captured` answers :func:`run_config_captured` for a host (a
    per-host memo); without it the scan runs here."""
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
    blind_ok, blind = _count(rec["blind_links"]) if "blind_links" in rec else (True, 0)
    if not blind_ok:
        return Hold(UNVERIFIED, R_BLIND_UNREAD, [("witness", toks + ("blind_links",))], "blind_links_unreadable")
    host = rec.get("host")
    if not _is_text(host):
        return Hold(UNVERIFIED, R_NO_HOST, [("witness", toks)], "no_host")
    has_ports, observed = captured(host) if captured is not None else run_config_captured(interfaces, host)
    if not observed:
        where = ("interfaces", host) if has_ports else ("interfaces",)
        return Hold(NOT_COLLECTED, R_NO_RUN_CONFIG, [("witness", where)], "no_run_config")
    simulated_ok, simulated = _count(rec.get("vlans_impacted"))
    if n and not (simulated_ok and simulated):
        return Hold(NOT_COLLECTED, R_OFF_SCAN_ONLY.format(n=n), [("witness", toks + ("off_scan_gw_vlans",))],
                    "off_scan_only", n)
    if blind and not (simulated_ok and simulated):
        return Hold(NOT_COLLECTED, R_BLIND_ONLY.format(n=blind), [("witness", toks + ("blind_links",))],
                    "blind_links_only", blind)
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


def make_bound(state: str, clause: str, wit: List[Entry], code: str, n: int, *, tail: str = R_PEER_TAIL) -> Bound:
    """One :class:`Bound` from a reason clause (an uncollected neighbour, or evidence-less inter-switch links): it
    reaches the detail too (a detail naming no simulated VLAN is the producer's clean bill, and `tail` says what it
    was never checked against)."""
    word = STATE_WORD[state]
    return Bound(state, R_PEER_SEVERITY.format(word=word, clause=clause, worst=IMPACT_WORST),
                 R_PEER_ZERO.format(word=word, clause=clause),
                 R_PEER_DETAIL.format(word=word, clause=clause, tail=tail), wit, code, n, f"{word}: {clause}")


def blind_bound(rec: Any, toks: Sequence[Any]) -> Optional[Bound]:
    """The bound a row's evidence-less inter-switch links put on it (W32). analyze.compute_failure_impact writes
    ``blind_links`` on every row: the switch's links with no trunk/STP evidence on either end, which it leaves out of
    every forwarding graph, so a VLAN the switch transits only over one is never simulated for it however many others
    were. A positive count therefore bounds the row as a positive off_scan_gw_vlans does (:func:`off_scan_bound`),
    and also reaches the detail (a detail naming no simulated VLAN is then not a clean bill). A row WITHOUT the field
    predates the per-row count: the producer before it disclosed such links at most in the INDETERMINATE detail of a
    switch it simulated nothing for, and a row alone cannot say which engine wrote it, so an absent count never
    vouches for a clean bill -- it bounds the row the same way, witnessed by the row itself. A count that is present
    but unreadable is a hold (:func:`row_hold`), never a bound; zero bounds nothing. ``None``: no bound."""
    if not isinstance(rec, dict):
        return None
    toks = tuple(toks)
    if "blind_links" not in rec:
        return make_bound(NOT_COLLECTED, R_BLIND_LEGACY, [("witness", toks)], "blind_links_legacy", 0,
                          tail=R_BLIND_TAIL)
    ok, n = _count(rec["blind_links"])
    if not (ok and n):
        return None
    return make_bound(NOT_COLLECTED, R_BLIND.format(n=n), [("witness", toks + ("blind_links",))], "blind_links", n,
                      tail=R_BLIND_TAIL)


def readable_cables(cables: Sequence[Any], nodes: Optional[Sequence[Any]] = None, *,
                    by_end: Optional[Mapping[str, Sequence[int]]] = None,
                    unjoinable: Optional[Sequence[int]] = None,
                    node_index: Optional[Mapping[str, Sequence[int]]] = None,
                    node_unjoinable: Optional[Sequence[int]] = None) -> CableSource:
    """A readable cable list (and the node list, ``None`` when it cannot be read). Joins not supplied by the caller
    are built here with :func:`index_rows` / :func:`unjoinable_rows`."""
    cables = cables if isinstance(cables, list) else []
    nodes = nodes if isinstance(nodes, list) else None
    bad = sorted(set(unjoinable if unjoinable is not None else unjoinable_rows(cables, ("a", "b"))))
    nbad = (sorted(set(node_unjoinable if node_unjoinable is not None else unjoinable_rows(nodes, ("host",))))
            if nodes is not None else [])
    return CableSource(
        None, "", (), cables, nodes,
        by_end if by_end is not None else index_rows(cables, ("a", "b")), bad,
        (node_index if node_index is not None else index_rows(nodes, ("host",))) if nodes is not None else {},
        frozenset(bad), nbad)


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
    with that reading's own state. A node row the host join cannot read (W43/F6) could be a second node for any far
    end, so beside one no far end joins exactly one node and every neighbour fails closed, citing those node rows.
    ``None``: no such neighbour (or no readable host).

    The witnesses are every bounding cable row in ascending index order, then (beside a node row the join cannot
    read, when a neighbour fails closed) those node rows. A cable row the join cannot read bounds
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
    nbad = list(src.node_unjoinable)         # node rows the host join cannot read: each could be any far end's node
    own: List[int] = []                      # bounding rows the join CAN read, ascending
    peers: Dict[str, bool] = {}              # far end -> whether it fails closed (joins no single node)
    for j in sorted(set(src.by_end.get(host, [])) - bad):
        ends = (cables[j]["a"], cables[j]["b"])
        far = ends[1] if ends[0] == host else ends[0]
        found = src.node_index.get(far, []) if far else []
        single = len(found) == 1 and nodes is not None and not nbad
        if single:
            node = nodes[found[0]]
            kind = node.get("kind")
            if node.get("collected") is True or (
                    node.get("collected") is False and _is_text(kind) and kind in IMPACT_EDGE_KINDS):
                continue
        own.append(j)
        peers[far] = peers.get(far, False) or not single
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
    node_hits = _first(nbad, witness_cap) if nbad and any(peers.values()) else []
    return make_bound(NOT_COLLECTED, clause, [("witness", toks + (j,)) for j in hits]
                      + [("witness", ("cable_map", "nodes", i)) for i in node_hits], "uncollected_neighbours", n)


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
    hold, a bound that reaches the detail (an uncollected neighbour, or evidence-less inter-switch links, counted or
    older than the count) withholds a detail that names no simulated VLAN (no readable positive vlans_impacted):
    that is the producer's clean bill. A per-VLAN detail stays published as the list of what was simulated; a
    mistyped detail is left to the caller's type check."""
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
    for a reader that renders none (:func:`neighbour_bound`, :func:`duplicate_doubt`); ``None`` keeps every one.

    The two per-host predicates -- the interface running-config scan (:func:`run_config_captured`) and the
    uncollected-neighbour join (:func:`neighbour_bound`) -- are pure functions of the host and the cached sources, so
    each runs once per host however many rows name it: R rows naming one host cost one scan of its interfaces and one
    join over its cables, never R of each."""

    def __init__(self, snap: Any, *, rows_by_host: Optional[Callable[[], Mapping[str, Sequence[int]]]] = None,
                 cables: Optional[Callable[[], CableSource]] = None, witness_cap: Optional[int] = None) -> None:
        self.snap: Dict[str, Any] = snap if isinstance(snap, dict) else {}
        self._rows_by_host_fn = rows_by_host
        self._rows_by_host: Optional[Mapping[str, Sequence[int]]] = None
        self._cables_fn = cables
        self._cables: Optional[CableSource] = None
        self.witness_cap = witness_cap
        self._captured: Dict[str, Tuple[bool, bool]] = {}
        self._peers: Dict[str, Optional[Bound]] = {}

    def rows_by_host(self) -> Mapping[str, Sequence[int]]:
        if self._rows_by_host is None:
            self._rows_by_host = (self._rows_by_host_fn() if self._rows_by_host_fn is not None
                                  else index_rows(self.snap.get("failure_impact"), ("host",)))
        return self._rows_by_host

    def cable_source(self) -> CableSource:
        if self._cables is None:
            self._cables = self._cables_fn() if self._cables_fn is not None else read_cable_source(self.snap)
        return self._cables

    def captured(self, host: str) -> Tuple[bool, bool]:
        """:func:`run_config_captured` for `host`, scanned once per host."""
        got = self._captured.get(host)
        if got is None:
            got = self._captured[host] = run_config_captured(self.snap.get("interfaces"), host)
        return got

    def neighbour(self, host: str) -> Optional[Bound]:
        """:func:`neighbour_bound` for `host`, joined once per host. Each call returns its own copy of the witness
        list, so no caller can change what another row reads from the cache."""
        if host not in self._peers:
            self._peers[host] = neighbour_bound(host, self.cable_source(), witness_cap=self.witness_cap)
        bound = self._peers[host]
        return None if bound is None else bound._replace(witnesses=list(bound.witnesses))

    def row(self, i: int, raw: Any) -> RowFacts:
        """The facts of stored row `i`: the duplicate doubt, the hold, then the bounds (off-scan first, then the
        evidence-less inter-switch links, both stated beside a hold too so every measure cites them, then the
        neighbour bound, which is read only for a row without a hold)."""
        toks = ("failure_impact", i)
        host = raw.get("host") if isinstance(raw, dict) else None
        doubt = (duplicate_doubt(raw, self.rows_by_host(), witness_cap=self.witness_cap) if _is_text(host)
                 else None)
        hold = row_hold(raw, toks, self.snap.get("interfaces"), captured=self.captured)
        bounds: List[Bound] = []
        scan = off_scan_bound(raw, toks)
        if scan is not None:
            bounds.append(scan)
        blind = blind_bound(raw, toks)
        if blind is not None:
            bounds.append(blind)
        if hold is None and _is_text(host):
            peers = self.neighbour(host)
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
    def readable(self) -> bool:
        """Whether the stored row is an object, so its fields can be read at all. The one rule for an UNREADABLE
        row: it holds whatever the verdict or reason codes say (a failed section words a non-object row as
        ``section_unavailable``, not ``row_unreadable``), so a census of unreadable rows and a list of them read
        this, never a reason code (W50)."""
        return isinstance(self.raw, dict)

    @property
    def code_counts(self) -> List[Tuple[str, int]]:
        """``(code, n)`` per reason, in :attr:`codes` order: each stable reason identifier (a key of
        :data:`CODE_PHRASES`) with the count its phrase quotes (0 where it quotes none). A display that words the
        reasons itself reads these (W50: AssessHub's live ``impacts_view`` of an execution receipt's bound evidence,
        whose phrase table is held equal to :data:`CODE_PHRASES`)."""
        return list(self._ns)

    @property
    def state(self) -> Optional[str]:
        """The owner's withheld state of the row as a whole: ``None`` for a measurement; otherwise
        :data:`ANALYSIS_UNAVAILABLE`, :data:`UNVERIFIED` or :data:`NOT_COLLECTED`, read in the verdict's own
        precedence (a failed section or owner fault, an unreadable row, a duplicated host, the hold, then the bounds
        by :func:`bound_state`). It keeps those three states apart for a reader that would otherwise collapse every
        non-measurement into "not assessed"."""
        if self.assessable == PUBLISHED:
            return None
        if self._section is not None:
            return self._section[0]
        if not isinstance(self.raw, dict):
            return UNVERIFIED
        if self.facts.doubt is not None:
            return self.facts.doubt.state
        if self.facts.hold is not None:
            return self.facts.hold.state
        return bound_state(self.facts.bounds)

    def withheld_state(self, field: str) -> Optional[str]:
        """The state of the owner's withholding of `field` (``None`` when :meth:`withholds` is False): the state the
        projection gives that cell, from the same rule :meth:`withholds` applies."""
        if not self.withholds(field):
            return None
        if self._section is not None:
            return self._section[0]
        if not isinstance(self.raw, dict):
            return UNVERIFIED
        if self.facts.doubt is not None:
            return self.facts.doubt.state
        hold, bounds = self.facts.hold, self.facts.bounds
        if field in IMPACT_MEASURES:
            found = measure_withheld(hold, field, self.raw.get(field), bounds)
        elif field == "detail":
            found = detail_withheld(hold, self.raw.get("detail"), self.raw, bounds)
        else:
            found = None
        return found[0] if found is not None else UNVERIFIED

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


def section_state(snap: Any) -> Optional[str]:
    """The withheld state of the stored ``failure_impact`` section as a whole, for a reader that must tell "no row"
    from "no readable section": ``None`` when the section is a list (each row then carries its own verdict, and an
    empty list holds no row); :data:`ANALYSIS_UNAVAILABLE` when its phase failed this run (its rows, if any, are each
    not assessed); :data:`UNVERIFIED` when the abstention owner faults or the section is present but not a list;
    :data:`NOT_COLLECTED` when it is absent. Never "none found": an absent or unreadable section is not a zero."""
    s = snap if isinstance(snap, dict) else {}
    token = _abst(s, "failure_impact")
    if token == ANALYSIS_UNAVAILABLE:
        return ANALYSIS_UNAVAILABLE
    if token == _FAULT:
        return UNVERIFIED
    if isinstance(s.get("failure_impact"), list):
        return None
    return NOT_COLLECTED if token == NOT_COLLECTED else UNVERIFIED


def count_value(raw: Any) -> Optional[int]:
    """A stored count as the integer the owner reads it as (a non-bool integer, or an integral finite float, in
    [0, 2**53-1]), else ``None``: a value that is not a readable count is never a zero."""
    ok, n = _count(raw)
    return n if ok else None


def rows_with_verdicts(snap: Any) -> List[Tuple[Dict[str, Any], RowVerdict]]:
    """``(row, verdict)`` for every stored row that is an object, in stored order: the pairs a deliverable renders
    or ranks from."""
    return [(v.raw, v) for v in assess_failure_impact(snap) if v.readable]


def assessment_document(snap: Any) -> Dict[str, Any]:
    """The JSON document of every row's verdict (``failure_impact_assessability/1``), aligned with the stored list,
    with the count per verdict in :data:`VERDICTS` order."""
    rows = [v.as_dict() for v in assess_failure_impact(snap)]
    return {"schema": SCHEMA, "rows": rows,
            "counts": {k: sum(1 for r in rows if r["assessable"] == k) for k in VERDICTS}}


def unavailable_document() -> Dict[str, Any]:
    """The verdict document a caller substitutes when :func:`assessment_document` could not be computed (the
    pipeline's phase fallback): it carries no row verdict, so a consumer reads every row as one with no verdict --
    not assessed, never published by default. ``counts`` is not a census here; ``unavailable`` says so."""
    return {"schema": SCHEMA, "rows": [], "counts": {k: 0 for k in VERDICTS}, "unavailable": True}


#: What a deliverable table writes for a value the owner withholds (never the stored Info or 0).
NOT_ASSESSED_CELL = "not assessed"
#: What a ranking appends to a lower-bound row's count it ranks: the count is a floor, not a measurement.
LOWER_BOUND_MARK = "(lower bound)"


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


#: How a display may read one cell of a row (:func:`cell_reading`): the stored value is a measurement (or the
#: producer's detail the owner still publishes), the owner's lower bound, withheld, or not a readable value of its kind.
CELL_PUBLISHED = "published"
CELL_FLOOR = "floor"
CELL_WITHHELD = "withheld"
CELL_UNREADABLE = "unreadable"
CELL_KINDS: Tuple[str, ...] = (CELL_PUBLISHED, CELL_FLOOR, CELL_WITHHELD, CELL_UNREADABLE)
#: The cells :func:`cell_reading` reads: every blast-radius measure, then the producer's detail.
CELL_FIELDS: Tuple[str, ...] = IMPACT_MEASURES + ("detail",)


class CellReading(NamedTuple):
    """One cell as the owner publishes it to a display that words it itself. ``kind`` is one of :data:`CELL_KINDS`;
    ``text`` is the display text for a published value or a floor (the owner's own :func:`table_value` wording,
    ``"≥ 45"`` / ``"High (lower bound)"``) and ``None`` otherwise; ``state`` is the state of a withholding
    (:meth:`RowVerdict.withheld_state`) and ``None`` otherwise."""
    kind: str
    text: Optional[str]
    state: Optional[str]


def cell_reading(verdict: RowVerdict, field: str) -> CellReading:
    """How a display reads `field` (one of :data:`CELL_FIELDS`) of the verdict's row (W50). The owner decides, the
    display only words it: a cell the owner withholds is :data:`CELL_WITHHELD` with its state; on a lower-bound row a
    published measure is :data:`CELL_FLOOR` with :func:`table_value`'s text; a published value that is not readable as
    its kind (a band outside :data:`IMPACT_SEVERITIES`, a count :func:`count_value` cannot read, a detail that is not
    non-blank text) is :data:`CELL_UNREADABLE`, never a zero; anything else is :data:`CELL_PUBLISHED` with its text."""
    if field not in CELL_FIELDS:
        raise ValueError(f"not a failure-impact display cell: {field!r}")
    if verdict.withholds(field):
        return CellReading(CELL_WITHHELD, None, verdict.withheld_state(field))
    raw = verdict.raw.get(field) if isinstance(verdict.raw, dict) else None
    floor = verdict.assessable == LOWER_BOUND and field in IMPACT_MEASURES
    text: Any
    if field == "detail":
        readable, text = _is_text(raw) and bool(raw.strip()), raw
    elif field == "severity":
        readable = isinstance(raw, str) and raw in IMPACT_SEVERITIES
        text = table_value(verdict, field) if floor else raw
    else:
        ok, n = _count(raw)
        readable = ok
        text = table_value(verdict, field) if floor else str(n)
    if not readable or not isinstance(text, str):
        return CellReading(CELL_UNREADABLE, None, None)
    return CellReading(CELL_FLOOR if floor else CELL_PUBLISHED, text, None)


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


# ---------------------------------------------------------------------------------------------------
# keystone rankings (the per-cell decision, not the row verdict)
# ---------------------------------------------------------------------------------------------------
def ranking_floor(verdict: RowVerdict) -> Optional[int]:
    """The stranded count a keystone ranking orders a LOWER-BOUND row by: its readable positive ``stranded``, which
    the owner publishes as the floor it is (``withholds('stranded')`` is False). A ranker that dropped such a row
    because its verdict is not ``published`` would rank a smaller measured switch above a switch that strands at
    least that many. ``None`` for every other row: a published row ranks by its own measurement, and a held,
    ambiguous or zero-floor row (a bound withholds a zero) is disclosed, never ranked."""
    if verdict.assessable != LOWER_BOUND or not isinstance(verdict.raw, dict) or verdict.withholds("stranded"):
        return None
    ok, n = _count(verdict.raw.get("stranded"))
    return n if ok and n > 0 else None


def ranks(verdict: RowVerdict) -> bool:
    """Whether a keystone ranking may place the row at all: a published measurement, or a lower bound whose positive
    stranded floor the owner publishes (:func:`ranking_floor`). Every other row is disclosed with :func:`disclose`."""
    return verdict.published or ranking_floor(verdict) is not None


def ranking_order(verdict: RowVerdict) -> Tuple[int, int, int]:
    """The sort key of a display that lists EVERY row in ranking order (W50): each row :func:`ranks` places, by its
    stranded floor (:func:`ranking_floor`) or its measured count, largest first; then a ranked row with no readable
    count; then every row it does not rank (each of those is also in :func:`unranked`, which a capped display names in
    full). Stored order breaks every tie."""
    if not ranks(verdict):
        return 2, 0, verdict.index
    floor = ranking_floor(verdict)
    if floor is not None:
        return 0, -floor, verdict.index
    ok, n = _count(verdict.raw.get("stranded")) if isinstance(verdict.raw, dict) else (False, None)
    return (0, -n, verdict.index) if ok else (1, 0, verdict.index)


def unranked(verdicts: Sequence[RowVerdict]) -> List[RowVerdict]:
    """The rows a ranking must DISCLOSE rather than place, in stored order: every row :func:`ranks` refuses (held,
    ambiguous, a lower bound whose stranded floor is withheld or zero, an unreadable row, a failed section). These are
    the rows :func:`disclose` names; a display that caps its ranked list names every one of them regardless of the
    cap, because they sort after every ranked row (:func:`ranking_order`)."""
    return [v for v in verdicts if not ranks(v)]


def ranked_value(verdict: RowVerdict, field: str) -> Any:
    """What a ranking table writes for `field` of a row it ranks: the stored value on a published row; on a
    lower-bound row the owner's :func:`table_value` marked as a floor (``"≥ 300 (lower bound)"``, ``"High (lower
    bound)"``), and :data:`NOT_ASSESSED_CELL` for a value the owner withholds (a band below the worst, a zero)."""
    value = table_value(verdict, field)
    if (verdict.assessable == LOWER_BOUND and field in IMPACT_MEASURES and field != "severity"
            and isinstance(value, str) and value.startswith("≥ ")):
        return f"{value} {LOWER_BOUND_MARK}"
    return value


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


# ---------------------------------------------------------------------------------------------------
# one migration wave's blast radius: the MOP (mop._blast_for) and the AssessHub cutover plan
# (cutover._worst_blast_radius) read this one rule
# ---------------------------------------------------------------------------------------------------
#: ui_projection's fleet qualifier on its failure_impact list while collection_completeness cannot show every inventory
#: device collected (W51: the record's one coverage verdict, ``ui_projection._cc_coverage``), and the pointer under
#: which every ``/collection_completeness`` witness it cites lies. A witness naming a devices row the projection's own
#: classifier reads as a partial or not-collected device (``ui_projection.fleet_blind_spot_rows``) is a blind device;
#: every other one is a record the projection cannot read as one (a row, list or section of the wrong shape, or a
#: record that is absent, failed or whose summary does not reconcile). :func:`fleet_blind` reads them from a projected
#: list and that classifier's rows; the projection stays their owner and this module never imports it.
FLEET_BLIND_CAVEAT = "fleet_lists_exclude_blind_devices"
FLEET_BLIND_WITNESS = "/collection_completeness"
_FLEET_BLIND_ROW = re.compile(r"/collection_completeness/devices/(\d+)")

R_WAVE_FLEET_BLIND = ("collection_completeness lists {n} device(s) as partial or not collected: every failure-impact "
                      "row was computed without their evidence, and a device the collection never reached has no row")
R_WAVE_FLEET_BLIND_UNREAD = ("collection_completeness carries {n} record(s) the engine cannot read as a partial or "
                             "not-collected device or as listing every such device (a row that is not an object or "
                             "states no status of its owner's vocabulary, a list or section of the wrong type, or a "
                             "record that is absent, failed, or whose summary does not reconcile with its rows or the "
                             "roster), and each could be or hide one: a failure-impact row may have been computed "
                             "without that device's evidence")
R_WAVE_FLEET_UNREAD = ("whether the collection reached every device cannot be read (the engine's failure-impact "
                       "projection could not be built), so no failure-impact row is known to cover the whole fleet")
R_WAVE_NO_ROW = "{n} device(s) with no failure-impact row, so their removal was never simulated ({names})"
R_WAVE_NO_FIGURE = "{n} row(s) with no readable stranded figure ({names})"
R_WAVE_HOSTLESS = ("{n} failure-impact row(s) name no readable switch, so each could describe any device in this "
                   "wave: {names}")
#: Why a wave figure that is not assessed is not one: no device contributes a count, or the largest is a zero floor.
R_WAVE_NONE = ("no device in this wave has a stranded count the engine publishes as a measurement or as a positive "
               "lower bound")
R_WAVE_ZERO = ("the largest stranded count the engine publishes for this wave is 0, and here it is only a lower bound, "
               "which is not a measurement of none")


class WaveRow(NamedTuple):
    """One stored failure-impact row as the wave rule reads it. ``key``: the stored row's exact host text (``None`` or
    ``""`` names no readable host, so the row could describe any device in a wave). ``ranked``: the reader may place
    the row (the owner's own rows: its stranded count is published as a measurement or as a positive floor; a reader
    that orders by severity, such as the cutover plan, also needs its band). ``lower_bound``: a ranked row whose counts
    are only floors. ``stranded``: a ranked row's published count or floor. ``row``: the reader's handle (a
    :class:`RowVerdict` for :func:`wave_rows`, a projected row for the cutover plan)."""
    key: Optional[str]
    ranked: bool
    lower_bound: bool
    stranded: Any
    row: Any


class WaveBlast(NamedTuple):
    """One wave's blast radius (:func:`wave_blast`).

    ``assessable``: :data:`PUBLISHED` when ``complete`` (every device of the wave has a ranked row that is not a lower
    bound, no row names no readable host, and the collection reached every device); else :data:`LOWER_BOUND` when the
    largest count or floor is positive; else :data:`NOT_ASSESSED` (no device contributes a count, or the largest is a
    zero that is only a lower bound, which is not a measurement of none). ``value``: the largest published stranded
    count or floor (``None`` when no ranked row has one). ``ranked`` (stored order), ``unranked`` (``(device, its
    first row or None)``, by device), ``hostless`` and ``bounded`` are the rows behind it; ``blind`` is the fleet's
    partial or never-collected device count and ``blind_unread`` the collection records the projection cannot read as
    one (:func:`fleet_blind`; ``None`` for either: unknown, which fails closed)."""
    assessable: str
    value: Optional[int]
    complete: bool
    ranked: Tuple[WaveRow, ...]
    unranked: Tuple[Tuple[str, Optional[WaveRow]], ...]
    hostless: Tuple[WaveRow, ...]
    bounded: Tuple[WaveRow, ...]
    blind: Optional[int]
    blind_unread: Optional[int]

    @property
    def n_not_ranked(self) -> int:
        """The devices with no ranked row plus the rows that name no readable host."""
        return len(self.unranked) + len(self.hostless)

    @property
    def observed(self) -> bool:
        """Whether any failure-impact row could describe a device of the wave: a row naming one of them, or a row that
        names no readable host and so could describe any of them (W51, the W48 re-verification: such a wave is not
        assessed, with the row named, never unobserved)."""
        return (bool(self.ranked) or bool(self.hostless)
                or any(row is not None for _device, row in self.unranked))

    @property
    def zero_bound(self) -> bool:
        """The largest count is a zero that is only a lower bound (not assessed, never a threshold of zero)."""
        return not self.complete and self.value == 0


def wave_row(verdict: RowVerdict) -> WaveRow:
    """A stored row as the wave rule reads it, from the owner's verdict: a published row ranks by its readable
    stranded count, a lower-bound row by the positive floor the owner publishes (:func:`ranking_floor`), and a held,
    ambiguous or zero-floored row does not rank."""
    raw = verdict.raw if isinstance(verdict.raw, dict) else {}
    if verdict.published:
        ok, n = _count(raw.get("stranded"))
        return WaveRow(verdict.host, ok, False, n if ok else None, verdict)
    floor = ranking_floor(verdict)
    return WaveRow(verdict.host, floor is not None, verdict.assessable == LOWER_BOUND, floor, verdict)


def wave_rows(snap: Any) -> List[WaveRow]:
    """Every stored row of `snap` as the wave rule reads it (:func:`wave_row`), aligned with the stored list."""
    return [wave_row(v) for v in assess_failure_impact(snap)]


def fleet_blind(listing: Any, blind_rows: Any) -> Optional[Tuple[int, int]]:
    """``(blind, unread)`` for the projection's fleet qualifier on a projected failure_impact list
    (``ui_projection.project_topology(snap)['failure_impact']``), given the devices rows the projection's own
    classifier reads as a partial or not-collected device (``ui_projection.fleet_blind_spot_rows(snap)``): of the
    :data:`FLEET_BLIND_WITNESS` witnesses the qualifier cites, those naming such a row, and every other one (a row,
    list or section it cannot read as one, or the record's summary). ``(0, 0)`` when the list carries no
    :data:`FLEET_BLIND_CAVEAT`; the qualifier with no such witness is a record the snapshot does not carry, so
    ``(0, 1)``: one record that cannot be read, never a blind device. `blind_rows` that is not a list of row indices
    reads no row as a blind device (every witness is then unread). ``None`` when `listing` is not a projected list,
    which the wave rule reads as unknown and fails closed on."""
    if not isinstance(listing, dict) or not isinstance(listing.get("items"), list):
        return None
    caveats = listing.get("caveats")
    if not (isinstance(caveats, list) and FLEET_BLIND_CAVEAT in caveats):
        return 0, 0
    readable = ({i for i in blind_rows if isinstance(i, int) and not isinstance(i, bool)}
                if isinstance(blind_rows, (list, tuple)) else set())
    blind = unread = 0
    for ref in (listing.get("refs") if isinstance(listing.get("refs"), list) else []):
        pointer = ref.get("pointer") if isinstance(ref, dict) else None
        if not (isinstance(pointer, str) and (pointer == FLEET_BLIND_WITNESS
                                              or pointer.startswith(FLEET_BLIND_WITNESS + "/"))):
            continue
        row = _FLEET_BLIND_ROW.fullmatch(pointer)
        if row is not None and int(row.group(1)) in readable:
            blind += 1
        else:
            unread += 1
    return (blind, unread) if blind or unread else (0, 1)


def wave_blast(switches: Any, rows: Sequence[WaveRow], *, blind: Any, blind_unread: Any) -> WaveBlast:
    """One wave's blast radius over `rows` (every stored row, as :func:`wave_rows` or a reader's own reading gives
    them). A device of the wave (each non-empty text in `switches`) is covered by a ranked row naming it exactly.
    The figure is exact only when every device is covered by a row that is not a lower bound, no stored row names
    no readable host (such a row could describe any device here), and both fleet counts (:func:`fleet_blind`: `blind`
    devices, `blind_unread` records) are readable zeros. Neither count has a default (W51, the W48 re-verification):
    a caller states the fleet, and ``None`` or any other unreadable value means unknown, which is never exact.
    Otherwise the largest count or floor is a lower bound, and a lower bound of 0, or no count at all, is not
    assessed. Pure; never re-simulates."""
    members = {s for s in (switches if isinstance(switches, (list, tuple, set, frozenset)) else ())
               if isinstance(s, str) and s}
    rows = [r for r in rows if isinstance(r, WaveRow)]
    ranked = tuple(r for r in rows if r.ranked and r.key and r.key in members)
    covered = {r.key for r in ranked}
    first: Dict[str, WaveRow] = {}
    for r in rows:
        if isinstance(r.key, str) and r.key:
            first.setdefault(r.key, r)
    unranked = tuple((device, first.get(device)) for device in sorted(members - covered))
    hostless = tuple(r for r in rows if not r.key)
    bounded = tuple(r for r in ranked if r.lower_bound)
    blind_ok, n_blind = _count(blind)
    unread_ok, n_unread = _count(blind_unread)
    counts = [n for ok, n in (_count(r.stranded) for r in ranked) if ok]
    value = max(counts) if counts else None
    complete = (bool(ranked) and not (unranked or hostless or bounded)
                and blind_ok and n_blind == 0 and unread_ok and n_unread == 0)
    assessable = (PUBLISHED if complete and value is not None else LOWER_BOUND if not complete and value
                  else NOT_ASSESSED)
    return WaveBlast(assessable, value, complete, ranked, unranked, hostless, bounded,
                     n_blind if blind_ok else None, n_unread if unread_ok else None)


def _names(names: Sequence[str], limit: int) -> str:
    return ", ".join(names[:limit]) + (f"; +{len(names) - limit} more" if len(names) > limit else "")


def wave_why(wave: WaveBlast, *, limit: int = 5) -> str:
    """Why a wave figure over the owner's own rows (:func:`wave_rows`) is not exact, as one reader-facing phrase (""
    when it is): each lower-bound or unranked row with its verdict (:func:`disclose`), the devices with no row, the
    published rows with no readable stranded figure, the rows that name no readable host, and the fleet qualifier
    (its blind devices, then the records it cannot read as one, in the words and order AssessHub's cutover plan
    prints them)."""
    def verdict(r: Optional[WaveRow]) -> Optional[RowVerdict]:
        return r.row if r is not None and isinstance(r.row, RowVerdict) else None

    named = [verdict(r) for r in wave.bounded] + [verdict(r) for _device, r in wave.unranked]
    unpublished = [v for v in named if v is not None and not v.published]
    no_figure = [device for device, r in wave.unranked if verdict(r) is not None and verdict(r).published]
    missing = [device for device, r in wave.unranked if r is None]
    parts = []
    if unpublished:
        parts.append(disclose(unpublished, limit))
    if missing:
        parts.append(R_WAVE_NO_ROW.format(n=len(missing), names=_names(missing, limit)))
    if no_figure:
        parts.append(R_WAVE_NO_FIGURE.format(n=len(no_figure), names=_names(no_figure, limit)))
    if wave.hostless:
        hostless = [f"{json_pointer('failure_impact', v.index)} ({v.summary})" if v is not None else "a row"
                    for v in (verdict(r) for r in wave.hostless)]
        parts.append(R_WAVE_HOSTLESS.format(n=len(hostless), names=_names(hostless, limit)))
    if wave.blind is None or wave.blind_unread is None:
        parts.append(R_WAVE_FLEET_UNREAD)
    else:
        if wave.blind:
            parts.append(R_WAVE_FLEET_BLIND.format(n=wave.blind))
        if wave.blind_unread:
            parts.append(R_WAVE_FLEET_BLIND_UNREAD.format(n=wave.blind_unread))
    return "; ".join(parts)


__all__ = [
    "AMBIGUOUS", "ANALYSIS_UNAVAILABLE", "Bound", "CELL_FIELDS", "CELL_FLOOR", "CELL_KINDS", "CELL_PUBLISHED",
    "CELL_UNREADABLE", "CELL_WITHHELD", "CODE_PHRASES", "CableSource", "CellReading", "DELIVERABLE_WITNESS_CAP",
    "Doubt", "FLEET_BLIND_CAVEAT", "FLEET_BLIND_WITNESS", "Hold", "IMPACT_EDGE_KINDS", "IMPACT_FIELDS",
    "IMPACT_INDETERMINATE_PREFIX", "IMPACT_MEASURES", "IMPACT_SEVERITIES", "IMPACT_WORST", "ImpactSnapshot",
    "JS_MAX_SAFE_INT", "LOWER_BOUND", "LOWER_BOUND_MARK", "NOT_ASSESSED", "NOT_ASSESSED_CELL", "NOT_COLLECTED",
    "PUBLISHED", "RowFacts", "RowVerdict", "SCHEMA", "STATE_WORD", "UNVERIFIED", "VERDICTS", "VERDICT_LABELS",
    "WaveBlast", "WaveRow", "assess_failure_impact", "assessment_document", "blind_bound", "bound_state",
    "cell_reading", "count_value", "detail_withheld", "disclose", "duplicate_doubt", "fleet_blind", "index_rows",
    "json_pointer", "make_bound", "measure_withheld", "neighbour_bound", "off_scan_bound", "off_scan_count",
    "ranked_value", "ranking_floor", "ranking_order", "ranks", "read_cable_source", "readable_cables", "row_hold",
    "rows_with_verdicts", "run_config_captured", "section_state", "table_detail", "table_value",
    "unavailable_document", "understatable_count", "understatable_severity", "unjoinable_rows", "unranked",
    "unreadable_cables", "wave_blast", "wave_row", "wave_rows", "wave_why",
]
