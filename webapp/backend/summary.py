"""Derive a dashboard summary from a raw engine snapshot.

This is a *read-only projection* of the snapshot the engine already computed — it never re-runs
analysis. It rolls the headline numbers (re-using the engine's own `_trend_point`) plus the
breakdowns the cockpit needs: health bands, punch-list by severity/category, keystone devices by
blast radius, readiness, and which detail sections actually carry data (so the UI hides empty tabs).
Failure impact is read from the engine-owned projection (``impact_view``), never from the raw stored rows.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from . import engine  # noqa: F401  (also bootstraps sys.path for the cisco_toolkit import below)
from . import protocol_portfolio
from cisco_toolkit import registry_integrity

SEVERITY_ORDER = ["Critical", "High", "Medium", "Low", "Info"]
_SEV_RANK = {s: i for i, s in enumerate(SEVERITY_ORDER)}
BANDS = ["Excellent", "Good", "Fair", "Poor", "Critical"]


def _as_list(v: Any) -> List[Any]:
    """Coerce a snapshot section to a list. `(snap.get(k) or [])` only guards falsy values; a truthy
    NON-list (an int/str/dict in a malformed or hostile upload) would flow into a list-comprehension and
    raise TypeError -- summarize() runs on every upload, so that escapes as an HTTP 500. Returning [] for a
    non-list degrades gracefully, honouring this function's `Every field degrades gracefully` contract."""
    return v if isinstance(v, list) else []


def _hkey(v: Any) -> Any:
    """A HASHABLE form of a snapshot leaf that is about to be used as a dict key or as the left operand
    of an `in <dict>` / `<dict>.get(...)` lookup.

    The container and per-element guards above check the SHAPE of a section; this guards the LEAF. A
    dict/list where a label is expected (`severity`, `readiness`) is unhashable, and `_SEV_RANK.get(...)`
    / `... in readiness` then raises `TypeError: unhashable type: 'dict'` -- an unhandled HTTP 500. This
    is not academic: `_keystones` is the shared choke point behind THREE unauthenticated read routes
    (summarize -> the dashboard, cutover.build_plan -> /cutover, execution.start_run -> /executions), and
    the snapshot is STORED, so the same upload re-crashes every later read of it.

    Anything already hashable passes through UNCHANGED (real labels are untouched, so no count, order or
    lookup over valid data changes); only an unhashable dict/list is stringified, which no canonical label
    matches -- so it degrades to 'unknown', exactly as an unrecognised string already does."""
    try:
        hash(v)
        return v
    except TypeError:
        return str(v)

# Detail sections the web UI can render as tabs, in display order. (key, human label)
SECTION_LABELS: List[tuple] = [
    ("punchlist", "Punch-list"),
    ("device_dossiers", "Risk register"),     # NEW-V3.23.174 (per-asset compound-risk register)
    ("health_scores", "Health scores"),
    ("failure_impact", "Failure impact"),
    ("link_centrality", "Chokepoints"),
    ("causality", "Causality"),
    ("cross_layer", "Cross-layer"),
    ("migration_readiness", "Readiness"),
    ("wave_sequencing", "Wave sequencing"),
    ("application_intelligence", "Application domains"),
    ("segmentation", "Segmentation"),
    # Release-1 Protocol Assurance is synthesized from the exact persisted snapshot blob at read
    # time.  It is always available as a coverage-honest receipt, including when every family is
    # not verified; the count is the closed executable profile set, never the capability catalog.
    (protocol_portfolio.SECTION_KEY, "Protocol Assurance"),
    ("protocol_health", "Protocols"),
    ("multicast_intelligence", "Multicast / timing"),
    ("remediation_plan", "Remediation"),
    ("validation_plan", "Validation plan"),
    ("golden_drift", "Config drift"),
    # NEW (orchestration-peer wave): the three always-on engines the pipeline now emits. Each is a dict
    # {findings|features:[...], summary} so _section_index counts its inner list (an empty/clean section
    # hides its own tab, the platform convention). capture_integrity with zero findings = a clean estate.
    ("feature_compliance", "Feature compliance"),   # I2 — golden-drift decomposed per policy area
    ("acl_line_reachability", "ACL shadow"),         # G1 — offline ACL line-reachability / shadow proof
    ("capture_integrity", "Capture integrity"),      # K1 — truncation / pager / CLI-error guard
    # the four OPT-IN engines (present only when a flag supplies their input, so a default run hides them):
    ("state_assertions", "State assertions"),        # A1 — declarative check-pack (--assert-pack)
    ("path_intents", "Path intents"),                # G3 — named REACHES/ISOLATED intents (--path-intents)
    ("external_reconcile", "SoT reconcile"),         # B  — declared inventory vs observed (--import-inventory)
    ("whatif", "Failure what-if"),                   # G4 — failure-injection scenarios (--scenario); a LIST
    # NEW-V3.23.176: the V3.23.164-.167 NOS analytic quartet landed after this list was
    # authored and was unreachable from the web platform (neither tab nor whitelist) --
    # the one-source-of-truth audit's only real gap.
    ("syslog_intelligence", "Syslog"),
    ("qos_audit", "QoS posture"),
    ("software_risk", "Software risk"),
    ("platform_health", "Platform health"),
    ("capacity", "Capacity"),
    ("endpoint_identity", "Endpoints"),
    ("lifecycle_risk", "Lifecycle / EoL"),
    ("collection_completeness", "Collection completeness"),
    # Plan A / Tier-1 #3: the zero-parse yield ledger (cmdio.parse_yield_report, published in every
    # snapshot). Lives under the Collection Completeness sheet in the workbook -- same adjacency here.
    # Dict {summary, per_parser, events, events_truncated}: _section_index counts `events` (its first
    # inner list), so a run where every content-bearing command parsed hides the tab (the platform
    # convention) -- telemetry about the PARSER, never a device verdict.
    ("parse_yield", "Parse yield"),
]


def _count_by(items: List[dict], key: str, order: List[str] | None = None) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for it in items:
        v = str(it.get(key, "") or "—")
        out[v] = out.get(v, 0) + 1
    if order:
        ordered = {k: out.get(k, 0) for k in order if k in out}
        for k, v in out.items():  # any value not in the canonical order, appended
            ordered.setdefault(k, v)
        return ordered
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


# ---- failure impact: read from the engine-owned projection, never from the raw stored rows (W27) ----------
# analyze.compute_failure_impact writes Info with zero counts and a clean-bill detail for a switch it could not
# simulate, and a partial simulation or an uncollected neighbour makes a low band or a zero only a lower bound.
# ui_projection's shared failure-impact row builder (the row the fleet topology and the device page publish)
# withholds exactly those cells, each with its state and reason. Every AssessHub surface that shows or ranks
# failure impact (the keystones below, cutover's worst-case blast radius, the snapshot "Failure impact" tab and
# the /graph keystone badge) reads that projection through impact_view, so a withheld cell is never shown as a
# measurement and never feeds a ranking.
#
# A PUBLISHED measure can still be a lower bound. On a row the simulation covered only in part (a positive
# off_scan_gw_vlans), whose switch has inter-switch links with no trunk/STP evidence (a positive blind_links, W32) or
# whose stored row predates that count, or that the stored cable map shows cabled to an uncollected neighbour -- the
# bounds of the engine owner cisco_toolkit/impact_assessability.py (off_scan_bound, blind_bound, neighbour_bound) --
# ui_projection._topology_impact withholds what that bound cannot vouch for (a band below High, a zero) and publishes
# the worst band and each positive count "as lower bounds", citing every bound's witnesses on every measure (its
# `cite`, passed to _cell as the cell's witness refs; limitation impact_scanned_scope). That witness ref is the
# projection's one machine-readable mark of a published lower bound: no other path puts a witness on a published
# failure-impact measure (_cell adds a pre-check's refs only when it withholds the cell, a failure_impact row carries
# no row-level extra refs, and failure records carry the role failure_record). So impact_view reads a published
# measure that cites a witness as "at least" its value, names the bound from the pointers it cites, and every
# surface shows it as a lower bound, never as an exact measurement.

#: ui_projection's one published state: an envelope carries a ``value`` only in this state. Compared for equality
#: only, so any other state, an unknown one included, or a cell that is not an envelope, is withheld.
_PUBLISHED = "published"
#: ui_projection's state for a list it read and found empty (a published list is never empty).
_COLLECTED_BUT_EMPTY = "collected_but_empty"
#: ui_projection's state for a value it cannot read; the state this module reports when the projection itself faults.
_UNVERIFIED = "unverified"
#: ui_projection's ref role (REF_ROLES) for the record that says why a value is qualified.
_WITNESS_ROLE = "witness"
#: The failure-impact cells, in the order the projection builds them (ui_projection._topology_impact), which is
#: also the producer's own field order.
IMPACT_FIELDS = ("host", "severity", "vlans_impacted", "stranded", "hard", "backup", "fhrp",
                 "off_scan_gw_vlans", "detail")
#: The cells that measure the simulated blast radius (ui_projection._IMPACT_MEASURES): the only cells a published
#: lower bound sits on.
IMPACT_MEASURES = ("severity", "vlans_impacted", "stranded", "hard", "backup", "fhrp")
#: A row enters a ranking (the keystones, a wave's worst case) only when the projection publishes all three.
_IMPACT_RANK_FIELDS = ("host", "severity", "stranded")
#: What a surface shows where the engine withholds every blast radius it could rank: the cutover module's own
#: not-assessed token (cutover.GATE_NOT_ASSESSED), which the SPA's chips and the documents colour neutral.
IMPACT_NOT_ASSESSED = "NOT ASSESSED"
#: The fleet qualifier ui_projection puts on the failure-impact list while collection_completeness lists a blind
#: spot: every row was computed over the scanned model without that device's evidence. It also cites a record it
#: cannot read as a blind spot (a row that is not an object or states no status of its owner's vocabulary, or a list
#: or section of the wrong type), which its owner would have read as collected, and (W51) a record that is absent,
#: failed or whose summary does not reconcile with its rows or the roster; the two kinds are told apart by the
#: projection's own classifier (engine.fleet_blind_spot_rows), never by re-reading the stored rows. The engine owner
#: reads both counts (impact_assessability.fleet_blind, W48), so the cutover plan and the MOP take the same fact into
#: the wave rule.
_IMPACT_BLIND_CAVEAT = engine.IMPACT_FLEET_BLIND_CAVEAT
#: The keystone ranking's contract. 2: ranked only from engine-published failure-impact cells (W27). 3: a ranked
#: row the engine publishes only as a lower bound is flagged as one (lower_bound, its reasons and pointers), and an
#: executive_brief.keystones list is no longer read. 4: a cable-row bound is worded by what the projection's own
#: reason says of it (an uncollected neighbour, or cable evidence that cannot be read or is ambiguous), never as an
#: uncollected neighbour alone. 5: a bound from inter-switch links with no trunk/STP evidence (W32, through the
#: engine owner impact_assessability.blind_bound) is flagged and worded by its witness: the row's blind_links count,
#: or the row itself when it predates that count. 6: the blind-spot note counts only the rows the projection reads as
#: partial or not collected as such, and words every other record its qualifier cites as one that cannot be read
#: (W43; W45 and W43 each moved the contract to 5 independently, so the combined contract is 6). A cached summary from
#: an older contract is recomputed on read (app._summary_freshened).
KEYSTONE_CONTRACT_VERSION = 6
#: Cap on the names one disclosure sentence lists per reason, so a fleet-wide hold stays one readable sentence.
_IMPACT_NAME_CAP = 10
_R_IMPACT_FAULT = ("unverified: the engine failure-impact projection (ui_projection) could not be built for this "
                   "snapshot, so no row's severity or counts can be read")
_R_IMPACT_NO_REASON = "withheld by the engine projection, which published no reason"
_R_IMPACT_NO_ROW = ("not collected: no failure_impact row names this switch. analyze.compute_failure_impact writes one "
                    "row per scanned host, so its blast radius was never simulated, and an absent row is not 'no "
                    "impact'")
_R_IMPACT_BLIND = engine.IMPACT_R_FLEET_BLIND   # the engine owner's words, which the MOP prints too
_R_IMPACT_BLIND_UNREAD = engine.IMPACT_R_FLEET_BLIND_UNREAD   # likewise (W51's wording, moved into the owner)
_R_IMPACT_NOT_LIST = "unverified: the stored failure_impact section is not a list, so no row can be read"
#: Why a published measure is only a lower bound, by the kind of record its witness ref points at. A cable-row witness
#: has three wordings, picked by what the projection's own reason on the row says of it (:func:`_impact_peers_said`):
#: an uncollected neighbour, cable evidence that cannot be read or is ambiguous, or either (the reason names both
#: kinds, or no withheld cell on the row states it).
_R_BOUND_OFF_SCAN = ("{n} VLAN(s) on this switch have an off-scan gateway the simulation could not assess "
                     "(off_scan_gw_vlans), so it counts only the VLANs whose gateway was scanned")
_R_BOUND_PEERS = ("the stored cable map cables this switch to a neighbour it does not show as collected ({k} cable "
                  "row(s)), and the simulation counts only endpoints on scanned switches")
_R_BOUND_PEERS_UNREAD = ("the stored cable map has {k} cable row(s) that cannot be read, or whose far end joins no "
                         "single cable-map node, so each could cable this switch to a neighbour the collection never "
                         "reached and none is assumed collected, and the simulation counts only endpoints on scanned "
                         "switches")
_R_BOUND_PEERS_EITHER = ("the stored cable map has {k} cable row(s) that cable this switch to a neighbour it does not "
                         "show as collected, or that cannot be read or whose far end joins no single cable-map node "
                         "and so could; none of them is assumed collected, and the simulation counts only endpoints "
                         "on scanned switches")
_R_BOUND_CABLE_MAP = ("whether this switch faces an uncollected neighbour cannot be checked, because the stored cable "
                      "map cannot be read, and the simulation counts only endpoints on scanned switches")
#: The two blind-link bounds of impact_assessability.blind_bound, by their witness: the row's own blind_links count
#: (a positive count) or the row itself (a row stored before the producer wrote that count).
_R_BOUND_BLIND = ("this switch has inter-switch links with no trunk/STP evidence on either end (blind_links), and "
                  "the simulation never ran a VLAN this switch transits only over them")
_R_BOUND_BLIND_LEGACY = ("this stored row predates the engine's per-row count of inter-switch links with no "
                         "trunk/STP evidence (blind_links), so it cannot rule such links out, and the simulation "
                         "never ran a VLAN a switch transits only over them")
_R_BOUND_CITED = "the engine cites {pointer} as a bound on this row"
#: How the tab marks a published lower bound in place of its bare value (cf. a withheld cell's reason).
IMPACT_BOUND_MARK = "≥"
_R_BOUND_LEAD = "a lower bound, not an exact measurement: "
#: The witness pointers the owner's neighbour bound (impact_assessability.neighbour_bound) cites: one cable row, or
#: the cable list / map it cannot read.
_IMPACT_CABLE_WITNESS = "/cable_map/cables/"
_IMPACT_CABLE_LIST_WITNESSES = ("/cable_map/cables", "/cable_map")
#: The projection's own words for a cable-row bound (impact_assessability.R_PEERS and R_PEERS_CLOSED), as a
#: withheld cell of the same row states them: how many neighbours the bound counts, and how many of them fail closed
#: (a cable row the join cannot read, so it could name this switch, or a far end that joins no single node). The ref a
#: published measure cites names a cable row but not which kind it is, so the kind is read from these words, never
#: re-derived from the stored cable rows.
_IMPACT_PEERS_SAID = re.compile(r"cannot account for endpoints behind (\d+) uncollected neighbour\(s\)")
_IMPACT_PEERS_CLOSED_SAID = re.compile(r"; (\d+) of them fail closed because their cable row cannot be read or their "
                                       r"cable end does not join exactly one node")

#: One projected cell: ``(published, value, reason)``. ``value`` is set only when published; ``reason`` only when not.
ImpactCell = Tuple[bool, Any, str]


def _impact_cell(fact: Any) -> ImpactCell:
    """One projection envelope as ``(published, value, reason)``; anything not published is withheld with the
    projection's own reason (which opens with its state)."""
    if isinstance(fact, dict) and fact.get("state") == _PUBLISHED:
        return True, fact.get("value"), ""
    reason = fact.get("reason") if isinstance(fact, dict) else None
    if isinstance(reason, str) and reason.strip():
        return False, None, reason
    state = fact.get("state") if isinstance(fact, dict) else None
    return False, None, (f"{state}: {_R_IMPACT_NO_REASON}" if isinstance(state, str) and state else _R_IMPACT_NO_REASON)


def impact_view(snap: Dict[str, Any]) -> Dict[str, Any]:
    """The engine-owned failure-impact rows (engine.failure_impact_projection), ready for a table or a ranking.

    ``rows``: one entry per projected row, in stored order, each with ``pointer``; ``key``, the stored row's exact
    host text when it is text (used only to say which device a withheld row may describe, never shown as a
    measurement); ``cells``, field -> :data:`ImpactCell`; ``ranked``, true when the list is published and the
    projection publishes the row's host, severity and stranded count; ``reason``, why it is not ranked; and
    ``lower_bound``, true when the projection publishes any of the row's measures only as a lower bound (a published
    measure that cites a witness, see the note above), with ``bound_fields`` (those measures), ``bound_pointers``
    (every witness they cite, in the order cited) and ``bound_reasons`` (one sentence per kind of bound named).
    ``state``: the list's own projection state (``unverified`` when the projection faults). ``withheld``: the list's
    own reason when the list is not published (a failed phase, a malformed or absent section, or an owner fault),
    else "". ``blind``: the blind-spot rows the projection's fleet qualifier cites and reads as partial or not
    collected; ``blind_unread``: every other record that qualifier cites, which it cannot read as one
    (:func:`impact_blind_counts`)."""
    try:
        listing = engine.failure_impact_projection(snap)
    except Exception:   # noqa: BLE001 -- the projection is total by contract; a fault withholds every row
        listing = None
    if not isinstance(listing, dict) or not isinstance(listing.get("items"), list):
        return {"rows": [], "state": _UNVERIFIED, "withheld": _R_IMPACT_FAULT, "blind": 0, "blind_unread": 0}
    items = listing["items"]
    state = listing.get("state")
    withheld = ""
    if state != _PUBLISHED and not (state == _COLLECTED_BUT_EMPTY and not items):
        withheld = _impact_cell(listing)[2]
    blind, blind_unread = impact_blind_counts(snap, listing)
    stored = _as_list(snap.get("failure_impact")) if isinstance(snap, dict) else []
    rows: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        i = item.get("index")
        src = stored[i] if type(i) is int and 0 <= i < len(stored) else None
        key = src.get("host") if isinstance(src, dict) and isinstance(src.get("host"), str) else None
        cells = {field: _impact_cell(item.get(field)) for field in IMPACT_FIELDS}
        held = [cells[f][2] for f in _IMPACT_RANK_FIELDS if not cells[f][0]]
        ranked = not withheld and not held
        pointer = item["pointer"] if isinstance(item.get("pointer"), str) else ""
        bound_fields, bound_pointers, bound_reasons = _impact_bounds(item, cells, pointer)
        rows.append({"pointer": pointer, "key": key, "cells": cells, "ranked": ranked,
                     "reason": "" if ranked else (held[0] if held else withheld),
                     "lower_bound": bool(bound_fields), "bound_fields": bound_fields,
                     "bound_pointers": bound_pointers, "bound_reasons": bound_reasons})
    return {"rows": rows, "state": state if isinstance(state, str) and state else _UNVERIFIED,
            "withheld": withheld, "blind": blind, "blind_unread": blind_unread}


def impact_blind_counts(snap: Dict[str, Any], listing: Dict[str, Any]) -> Tuple[int, int]:
    """``(blind, unread)`` for the fleet qualifier on the failure-impact list: of the ``/collection_completeness``
    witnesses it cites, those naming a row the projection's own classifier reads as a partial or not-collected device
    (engine.fleet_blind_spot_rows), and every other one (a row, list or section it cannot read as such, or the
    record's summary). ``(0, 0)`` without the qualifier. The qualifier with no such witness is a record the snapshot
    does not carry (W51: the projection's coverage verdict qualifies the list for it, and nothing of it resolves), so
    it is one record that cannot be read, never a blind device the owner lists. The rule is the engine owner's
    (impact_assessability.fleet_blind, which the MOP's wave rule reads too); this only supplies the classifier."""
    if not (isinstance(listing.get("caveats"), list) and _IMPACT_BLIND_CAVEAT in listing["caveats"]):
        return 0, 0
    try:
        readable = engine.fleet_blind_spot_rows(snap)
    except Exception:   # noqa: BLE001 -- total by contract; a fault reads no row as a blind device
        readable = []
    counts = engine.failure_impact_fleet_blind(listing, readable)
    return counts if counts is not None else (0, 1)   # a list the owner cannot read: one record, fail closed


def _impact_bounds(item: Dict[str, Any], cells: Dict[str, ImpactCell],
                   pointer: str) -> Tuple[Tuple[str, ...], List[str], List[str]]:
    """The projection's published lower bounds on one row, ``(fields, pointers, reasons)``, read from the projected
    cells' refs only, never from the stored row. ``fields``: the measures it publishes with a witness ref, each a
    lower bound and never an exact measurement; ``pointers``: every witness those cells cite, de-duplicated in the
    order cited; ``reasons``: one sentence per kind of record those pointers name (the row's off-scan count, its
    blind_links count or the row itself when it predates that count, a cable row worded by what the projection's own
    reason says of it, an unreadable cable list or map, anything else by its pointer)."""
    fields: List[str] = []
    pointers: List[str] = []
    for field in IMPACT_MEASURES:
        fact = item.get(field)
        if not (cells[field][0] and isinstance(fact, dict)):
            continue
        cited = [ref["pointer"] for ref in _as_list(fact.get("refs")) if isinstance(ref, dict)
                 and ref.get("role") == _WITNESS_ROLE and isinstance(ref.get("pointer"), str)]
        if not cited:
            continue
        fields.append(field)
        for cite in cited:
            if cite not in pointers:
                pointers.append(cite)
    n_cables = sum(1 for cite in pointers if cite.startswith(_IMPACT_CABLE_WITNESS))
    said = _impact_peers_said(cells) if n_cables else None
    if said is not None and said[1] == 0 < said[0]:
        cables_why = _R_BOUND_PEERS                 # the owner names only uncollected neighbours
    elif said is not None and 0 < said[1] == said[0]:
        cables_why = _R_BOUND_PEERS_UNREAD          # every one fails closed: unreadable or ambiguous cable evidence
    else:
        cables_why = _R_BOUND_PEERS_EITHER          # both kinds, or no withheld cell on the row says which
    reasons: List[str] = []
    for cite in pointers:
        if pointer and cite == f"{pointer}/off_scan_gw_vlans":
            ok, n, _ = cells["off_scan_gw_vlans"]
            why = _R_BOUND_OFF_SCAN.format(n=n if ok and type(n) is int else "some")
        elif pointer and cite == f"{pointer}/blind_links":
            why = _R_BOUND_BLIND
        elif pointer and cite == pointer:
            why = _R_BOUND_BLIND_LEGACY             # only the blind-link bound cites the row on a published measure
        elif cite.startswith(_IMPACT_CABLE_WITNESS):
            why = cables_why.format(k=n_cables)
        elif cite in _IMPACT_CABLE_LIST_WITNESSES:
            why = _R_BOUND_CABLE_MAP
        else:
            why = _R_BOUND_CITED.format(pointer=cite)
        if why not in reasons:
            reasons.append(why)
    return tuple(fields), pointers, reasons


def _impact_peers_said(cells: Dict[str, ImpactCell]) -> Optional[Tuple[int, int]]:
    """What the projection's own reason on one row says of its cable-row bound: ``(neighbours, of them failing
    closed)``, read from the first withheld cell whose reason states that bound (:data:`_IMPACT_PEERS_SAID`). The
    bound withholds a severity below the worst band, each zero count and a clean-bill detail, so a row with any of
    those carries it. ``None`` when no withheld cell on the row states it (every cell the bound reaches is published
    as a lower bound): the cited cable rows alone do not say which kind each is."""
    for ok, _value, reason in cells.values():
        said = None if ok else _IMPACT_PEERS_SAID.search(reason)
        if said:
            closed = _IMPACT_PEERS_CLOSED_SAID.search(reason, said.end())
            return int(said.group(1)), (int(closed.group(1)) if closed else 0)
    return None


def impact_row_label(row: Dict[str, Any]) -> str:
    """How a disclosure names a projected row: its stored host text, else its pointer."""
    return row["key"] if row["key"] else (row["pointer"] or "a failure_impact row")


def impact_disclosure(entries: List[Tuple[str, str]]) -> str:
    """``name, name (+N more) -- reason; ...``: rows grouped by the projection's exact reason, in first-seen order."""
    groups: Dict[str, List[str]] = {}
    for name, reason in entries:
        groups.setdefault(reason, []).append(name)
    parts = []
    for reason, names in groups.items():
        more = f" (+{len(names) - _IMPACT_NAME_CAP} more)" if len(names) > _IMPACT_NAME_CAP else ""
        parts.append(f"{', '.join(names[:_IMPACT_NAME_CAP])}{more} — {reason}")
    return "; ".join(parts)


def impact_blind_note(view: Dict[str, Any]) -> str:
    """The projection's fleet qualifier as one clause ("" when the failure-impact list carries none): the blind devices
    it reads, then the records it cannot read as one, each worded as what it is."""
    parts = [_R_IMPACT_BLIND.format(n=view["blind"])] if view["blind"] else []
    if view.get("blind_unread"):
        parts.append(_R_IMPACT_BLIND_UNREAD.format(n=view["blind_unread"]))
    return "; ".join(parts)


def impact_rank_key(row: Dict[str, Any]) -> Tuple[int, float]:
    """Worst first: the published severity's rank, then the published stranded count, descending."""
    return (_SEV_RANK.get(_hkey(row["cells"]["severity"][1]), 99), -engine.as_num(row["cells"]["stranded"][1]))


def impact_bound_reason(row: Dict[str, Any]) -> str:
    """Why a row's published measures are only lower bounds, as one clause ("" for a row with none)."""
    return "; ".join(row["bound_reasons"])


def impact_bound_cell(value: Any, row: Dict[str, Any]) -> str:
    """A published lower-bound cell as the tab shows it in place of its bare value, the way a withheld cell shows its
    reason: ``≥ 42 — a lower bound, not an exact measurement: why``."""
    return f"{IMPACT_BOUND_MARK} {value} — {_R_BOUND_LEAD}{impact_bound_reason(row)}"


def impact_entry(row: Dict[str, Any]) -> Dict[str, Any]:
    """A ranked row in the keystone / blast-radius shape: its published values; a withheld VLAN count is None
    (rendered as absent), and a withheld detail shows the projection's reason instead of the stored text.
    ``lower_bound`` says whether the engine publishes the row's counts only as lower bounds. When it does, the entry
    also carries ``lower_bound_reasons`` and ``lower_bound_pointers``, and its detail opens with ``LOWER BOUND, at
    least N endpoint(s) stranded: why``, so every surface that shows the detail reads the count as "at least N"."""
    cells = row["cells"]
    vlans_ok, vlans, _ = cells["vlans_impacted"]
    detail_ok, detail, detail_reason = cells["detail"]
    out = {"host": cells["host"][1], "severity": cells["severity"][1], "stranded": cells["stranded"][1],
           "vlans_impacted": vlans if vlans_ok else None, "detail": detail if detail_ok else detail_reason,
           "lower_bound": bool(row["lower_bound"])}
    if row["lower_bound"]:
        stranded_ok, stranded, _ = cells["stranded"]
        counts = f", at least {stranded} endpoint(s) stranded" if stranded_ok else ""
        out["lower_bound_reasons"] = list(row["bound_reasons"])
        out["lower_bound_pointers"] = list(row["bound_pointers"])
        out["detail"] = f"LOWER BOUND{counts}: {impact_bound_reason(row)}. {out['detail']}"
    return out


def _impact_table_cell(row: Dict[str, Any], field: str) -> Any:
    ok, value, reason = row["cells"][field]
    if not ok:
        return reason
    return impact_bound_cell(value, row) if field in row["bound_fields"] else value


def failure_impact_table(snap: Dict[str, Any]) -> Any:
    """The snapshot's "Failure impact" tab: one row per stored row, in stored order, with the producer's fields in
    :data:`IMPACT_FIELDS` order. A cell the engine projection publishes keeps its value, unless the projection
    publishes it only as a lower bound: it then reads ``≥ value`` with why (:func:`impact_bound_cell`). A withheld
    cell shows the projection's reason, which opens with its state, instead of the stored Info, zero or clean-bill
    text. A section that is not a list, and an empty list the projection withholds, has no row to show: the tab
    shows the projection's own disclosure of the list, ``{"state", "reason"}``, never the stored object."""
    raw = snap.get("failure_impact")
    view = impact_view(snap)
    if not isinstance(raw, list) or (not raw and view["withheld"]):
        return {"state": view["state"], "reason": view["withheld"] or _R_IMPACT_NOT_LIST}
    if len(view["rows"]) != len(raw):     # an owner fault: withhold every row, never fall back to the raw values
        why = view["withheld"] or _R_IMPACT_FAULT
        return [{field: why for field in IMPACT_FIELDS} for _ in raw]
    return [{field: _impact_table_cell(row, field) for field in IMPACT_FIELDS} for row in view["rows"]]


def _keystones(snap: Dict[str, Any], top: int = 8,
               view: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """The few devices the fleet most depends on, by migration blast radius.

    Ranked from the engine-owned failure-impact projection alone (severity, then stranded endpoints). Only rows whose
    host, severity and stranded count the projection publishes are ranked: a row it withholds (could not simulate,
    predates its marker, lacks the scoped running-config, a partial simulation below High, an uncollected neighbour,
    a duplicated host) is never shown as Info or zero and never ranked. A ranked row the projection publishes only as
    a lower bound keeps its measured place and is flagged (:func:`impact_entry`). When any row is not ranked, a
    lower-bound row below the ones shown could rank among them, the list is not published, or a blind spot qualifies
    it, one last ``NOT ASSESSED`` entry with no host says so and why, so an all-withheld fleet never reads as "no
    keystone".

    An ``executive_brief.keystones`` list is never read: no engine producer writes one (compute_executive_brief takes
    no failure-impact input), so a stored one is uploaded or hand-made, and taking it would bypass every hold the
    projection applies (summary, the /graph badge and the cutover plan's wave tags all read this function)."""
    view = impact_view(snap) if view is None else view
    # stable sort over the stored order, as before: only the engine's published severity and stranded count rank
    ranked = sorted((row for row in view["rows"] if row["ranked"]), key=impact_rank_key)
    out = [impact_entry(row) for row in ranked[:top]]
    unranked = [(impact_row_label(row), row["reason"]) for row in view["rows"] if not row["ranked"]]
    # a lower bound's true value can exceed what it reads, so one below the cut could belong above it
    below = [(impact_row_label(row), impact_bound_reason(row)) for row in ranked[top:] if row["lower_bound"]]
    parts = []
    if view["withheld"] and not view["rows"]:
        parts.append(f"No failure-impact row could be ranked: {view['withheld']}")
    if unranked:
        parts.append(f"{len(unranked)} failure-impact row(s) were not ranked because the engine withholds their "
                     "host, severity or stranded count, so any of them could rank above the devices shown: "
                     + impact_disclosure(unranked))
    if below:
        parts.append(f"{len(below)} ranked row(s) below the devices shown publish only lower bounds, so any of them "
                     "could rank among them: " + impact_disclosure(below))
    blind_note = impact_blind_note(view)
    if blind_note:
        parts.append(f"The ranking is a lower bound: {blind_note}")
    if parts:
        out.append({"host": "", "severity": IMPACT_NOT_ASSESSED, "stranded": None, "vlans_impacted": None,
                    "detail": ". ".join(parts) + ".", "n_not_ranked": len(unranked)})
    return out


def _section_index(snap: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Which detail sections carry data + a count, for tab visibility."""
    out = []
    for key, label in SECTION_LABELS:
        if key == protocol_portfolio.SECTION_KEY:
            out.append({
                "key": key,
                "label": label,
                "count": protocol_portfolio.supported_family_count(),
            })
            continue
        v = snap.get(key)
        if isinstance(v, list):
            count = len(v)
        elif isinstance(v, dict):
            # dict sections: count the most meaningful list inside, else number of keys
            inner = next((x for x in v.values() if isinstance(x, list)), None)
            count = len(inner) if inner is not None else len(v)
        else:
            count = 0
        if count:
            out.append({"key": key, "label": label, "count": count})
    return out


_REQUIRED_DATA_AUTHORITIES = ("oui", "ports", "eol")
SNAPSHOT_PROVENANCE_KEY = "_assesshub_provenance"
LOCAL_ENGINE_ORIGIN = "local-engine"
DIRECT_UPLOAD_ORIGIN = "direct-upload"
VERIFICATION_CONTRACT_VERSION = 3


def snapshot_verification(snap: Dict[str, Any]) -> Dict[str, Any]:
    """Coverage-honest trust state for an engine or uploaded snapshot.

    ``verified`` is intentionally a narrow claim: the server must have stamped the snapshot as the
    result of a locally executed engine run, every required authority must carry the current explicit
    ``source_authoritative: true`` contract, and no analysis phase may have failed.  Client-uploaded
    booleans remain self-reported evidence, never a server attestation.
    """
    provenance_raw = snap.get(SNAPSHOT_PROVENANCE_KEY)
    provenance = provenance_raw if isinstance(provenance_raw, dict) else {}
    origin = provenance.get("origin")
    if origin not in {LOCAL_ENGINE_ORIGIN, DIRECT_UPLOAD_ORIGIN}:
        origin = "legacy-or-unknown"
    locally_attested = origin == LOCAL_ENGINE_ORIGIN
    run_integrity_raw = provenance.get("integrity_verified")
    run_integrity = (
        "verified" if run_integrity_raw is True
        else "failed" if run_integrity_raw is False
        else "unknown"
    )

    integrity_raw = snap.get("assessment_integrity")
    integrity = integrity_raw if isinstance(integrity_raw, dict) else {}
    failed_raw = integrity.get("failed_phases")
    malformed_integrity = failed_raw not in (None, []) and not isinstance(failed_raw, list)
    failed_phases = [
        str(value)[:160]
        for value in (failed_raw if isinstance(failed_raw, list) else [])
        if str(value).strip()
    ][:100]

    authorities_raw = snap.get("data_authorities")
    authorities = authorities_raw if isinstance(authorities_raw, dict) else {}
    missing: List[str] = []
    non_authoritative: List[str] = []
    integrity_failed: List[str] = []
    integrity_unknown: List[str] = []
    for name in _REQUIRED_DATA_AUTHORITIES:
        health = authorities.get(name)
        if not isinstance(health, dict) or "source_authoritative" not in health:
            missing.append(name)
            continue
        # Was `source_authoritative is not True`, which reads the port pack's HONEST mixed-pack
        # false as total registry failure. Effect measured on the real sample snapshot: status
        # "partial", verified false, reason "Known non-source-authoritative data packs: ports."
        # -> VerificationStatus.tsx renders a role="alert" telling the reader not to treat the
        # snapshot as a complete verified assessment, on EVERY healthy run. The §5.2 scoped-
        # authority fix reached serve.py and the engine self-test and missed this exit.
        # One shared predicate now, so the next consumer cannot disagree with the others.
        if not registry_integrity.pack_is_usable(health):
            non_authoritative.append(name)
        if health.get("integrity_verified") is False:
            integrity_failed.append(name)
        elif health.get("integrity_verified") is not True:
            integrity_unknown.append(name)

    reasons: List[str] = []
    if not locally_attested:
        reasons.append(
            "Snapshot origin was not a locally executed engine run; authority fields are "
            "self-reported and cannot establish verified coverage."
        )
    if run_integrity == "unknown":
        reasons.append(
            "Producer run integrity is unknown; no current positive completion attestation was "
            "persisted for this snapshot."
        )
    elif run_integrity == "failed":
        reasons.append(
            "Producer run integrity failed; this snapshot cannot support a verified claim."
        )
    if failed_phases:
        reasons.append(
            f"{len(failed_phases)} analysis phase(s) failed; empty or absent results are not "
            "evidence of health."
        )
    if malformed_integrity:
        reasons.append("assessment_integrity.failed_phases is malformed and cannot be trusted.")
    if missing:
        reasons.append(
            "Missing current source-authority evidence for: " + ", ".join(missing) + "."
        )
    if non_authoritative:
        reasons.append(
            "Known non-source-authoritative data packs: " + ", ".join(non_authoritative) + "."
        )
    if integrity_failed:
        reasons.append(
            "Data-pack byte/schema integrity failed for: " + ", ".join(integrity_failed) + "."
        )
    if integrity_unknown:
        reasons.append(
            "Data-pack integrity is unknown for: " + ", ".join(integrity_unknown) + "."
        )

    if (
        not locally_attested
        or run_integrity != "verified"
        or malformed_integrity
        or missing
        or integrity_unknown
    ):
        status = "unverified"
    elif failed_phases or non_authoritative or integrity_failed:
        status = "partial"
    else:
        status = "verified"
    labels = {
        "verified": "Verified coverage",
        "partial": "Partial coverage",
        "unverified": "Unverified coverage",
    }
    return {
        "contract_version": VERIFICATION_CONTRACT_VERSION,
        "origin": origin,
        "integrity_status": run_integrity,
        "status": status,
        "label": labels[status],
        "verified": status == "verified",
        "coverage_honest": True,
        "reasons": reasons,
        "failed_phases": failed_phases,
        "missing_authorities": missing,
        "non_authoritative_authorities": non_authoritative,
        "integrity_failed_authorities": integrity_failed,
        "integrity_unknown_authorities": integrity_unknown,
    }


# The lifecycle bands the engine publishes as a DETERMINATION. `compute_lifecycle_risk`
# (cisco_toolkit/analyze.py, _LIFECYCLE_BAND_RANK) emits exactly Past-LDoS / Near-LDoS / Past-EoS / Active
# when it could decide, plus "Unknown" when no exact EoX row matched or retained source/date authority
# was insufficient to support a date band.
#
# review r8 F4 -- STRUCTURAL INVERSION. This used to be a regex over not-assessed SPELLINGS
# (unknown|undetermined|insufficient data|n/a|...). That is this repo's most recurrent defect shape: a
# hand-maintained list of NAMES standing in for the class it means. The most likely FUTURE spelling is the
# one nobody wrote down -- and under a spelling list it fell through to "assessed" and was banked as
# health. Classifying against the KNOWN-GOOD vocabulary inverts the default in the safe direction: any
# band this projection does not recognise is NOT ASSESSED, so an unanticipated band is DISCLOSED rather
# than silently counted clean. (CLAUDE.md guardrail 3 -- "not observed" never becomes "healthy".)
_ASSESSED_BANDS = frozenset(("past-ldos", "near-ldos", "past-eos", "active"))


def _is_assessed_band(name: Any) -> bool:
    """True only for a band name the engine emits as a lifecycle DETERMINATION.

    Everything else -- today's "Unknown", a future "Undetermined"/"Not assessed", a typo, a band added by
    a newer engine than this projection knows about -- is not-assessed. Over-disclosure is the safe
    direction here; the reverse is false health."""
    return str(name).strip().lower() in _ASSESSED_BANDS


def _int0(v: Any) -> int:
    """A census count coerced to a non-negative int; anything non-numeric (a malformed upload) is 0."""
    if isinstance(v, bool):
        return 0
    if isinstance(v, int):
        return max(0, v)
    if isinstance(v, float):
        return max(0, int(v)) if v == v and v not in (float("inf"), float("-inf")) else 0
    try:
        return max(0, int(str(v).strip()))
    except Exception:
        return 0


def _census_int(v: Any) -> Optional[int]:
    """A census count if the value is USABLE as one, else ``None`` -- "no basis", never a silent 0.

    The sibling of `_int0` for the one place the difference matters: deciding whether a figure was
    MEASURED. `_int0` is a renderer's coercion -- it must always yield a number -- but using it to
    answer "did the producer report this?" turns every malformed value into a confident zero, and a
    zero that means "not measured" reading as "nothing wrong" is the exact false-health class this
    module's lifecycle projection exists to close. `None` here is honest ignorance; the caller
    discloses it rather than counting it as a clean result.
    """
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v if v >= 0 else None
    if isinstance(v, float):
        return int(v) if (v == v and v not in (float("inf"), float("-inf")) and v >= 0) else None
    try:
        parsed = int(str(v).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _lifecycle(lr: Dict[str, Any]) -> Dict[str, Any]:
    """Project the engine's hardware-lifecycle census for the dashboard.

    HISTORY (audit U1-1, CRITICAL false-health): this projected exactly three named rollups --
    past_eos / near_eos / past_ldos -- and DROPPED `n_unknown`, the count of devices whose platform
    had no exact EoX row or whose matched row lacked retained source/date authority. An all-Unknown
    fleet therefore serialised to
    `{"past_eos":0,"near_eos":0,"past_ldos":0}`, BYTE-IDENTICAL to a fully-assessed all-Active fleet:
    the browser was structurally incapable of disclosing the gap because the gap never crossed the
    API boundary. The whole `by_band` census now crosses it, so a band the projection does not know
    by name still reaches the UI, and `unknown` is summed over the NOT-ASSESSED CLASS (above)
    rather than off the single `n_unknown` key."""
    _bb = lr.get("by_band")
    by_band: Dict[str, int] = ({str(k): _int0(v) for k, v in _bb.items()}
                               if isinstance(_bb, dict) else {})
    # bands OUTSIDE the engine's assessed vocabulary -- structural, see _is_assessed_band()
    gap_bands = sorted(k for k in by_band if not _is_assessed_band(k))
    derived = sum(by_band[k] for k in gap_bands)

    # SSOT (review r8 F2/F3): `lifecycle_risk.summary.n_unknown` is the OWNER of "how many assets could
    # not be lifecycle-assessed" (docs/ssot.md -- read a fact from its owner; a copy is a cache and must
    # cite the owner). This used to read the owner ONLY when `by_band` was empty and otherwise RE-DERIVE
    # the count by classifying band-name strings, i.e. it ignored the canonical field exactly when that
    # field was best evidenced; and the `if not by_band and not n_unknown:` line that followed was dead,
    # the preceding ternary having already handled it. Owner first, classification as a labelled
    # FALLBACK, and `unknown_source` names which read produced this row's figure.
    # Keyed on whether the owner's value is USABLE, not on whether the key is PRESENT. `_int0` maps
    # null / a string / a dict / a negative to 0, so `"n_unknown" in lr` accepted a malformed value as
    # a measurement of zero: the row then read "assessed, nothing undetermined" off a section that had
    # measured nothing. That is the same fail-open this projection was changed to close, one layer in.
    # An unusable value is NO BASIS -- identical to the key being absent -- and is named as such below.
    owner: Optional[int] = _census_int(lr.get("n_unknown"))
    if owner is None:
        n_unknown = derived
        source = "derived:by_band — owner field lifecycle_risk.summary.n_unknown is absent"
    elif derived > owner:
        # The owner's own census carries not-assessed bands its count does not cover (a newer engine
        # emitting a band this projection has never seen). FAIL CLOSED on the larger gap and name both
        # figures, so the disclosure is never smaller than the evidence in front of us.
        n_unknown = derived
        source = (f"lifecycle_risk.summary.n_unknown={owner}, RAISED to {derived} by by_band band(s) "
                  f"outside the engine's assessed vocabulary: {', '.join(gap_bands)}")
    else:
        n_unknown = owner
        source = "lifecycle_risk.summary.n_unknown"

    n_devices = _int0(lr.get("n_devices")) or sum(by_band.values())
    # Was there any basis at all for counting un-assessed assets? A section publishing neither a band
    # census nor the owner field gives none -- and a 0 that means "NOT MEASURED" must not read as
    # "nothing wrong" (review r8 F6, the silence-as-health half of U1-1). Fail CLOSED: no basis == gap.
    measured = bool(by_band) or owner is not None
    return {
        "past_eos": lr.get("n_past_eos", ""),
        "near_eos": lr.get("n_near", ""),      # canonical Near-LDoS count (was a non-existent n_near_eos -> always blank)
        "past_ldos": lr.get("n_past_ldos", ""),
        "active": lr.get("n_active", ""),
        # --- the coverage-honest half the UI could not previously see ---
        "unknown": n_unknown,
        # provenance of the figure above: the owner's own value, and which read produced `unknown`
        "unknown_reported": owner if owner is not None else "",
        "unknown_source": source,
        "n_devices": n_devices,
        "by_band": by_band,
        "not_assessed_bands": gap_bands,
        # False == the section gave NO basis to count un-assessed assets; `unknown` is then 0 because
        # nothing was measured, not because nothing is wrong.
        "coverage_measured": measured,
        # True == at least one asset's support state was NOT determined, OR nothing was measurable at
        # all. An empty lifecycle risk list is then a COVERAGE GAP, not a clean fleet, and the UI must
        # say so.
        "coverage_gap": bool(n_unknown > 0 or not measured),
        "assessed": max(0, n_devices - n_unknown) if measured else 0,
    }


def summarize(snap: Dict[str, Any]) -> Dict[str, Any]:
    """Headline + breakdowns used by the dashboard cards. Every field degrades gracefully."""
    hs = [r for r in _as_list(snap.get("health_scores")) if isinstance(r, dict)]
    pl = [r for r in _as_list(snap.get("punchlist")) if isinstance(r, dict)]
    mr = [r for r in _as_list(snap.get("migration_readiness")) if isinstance(r, dict)]
    # isinstance-guard, not `or {}`: a TRUTHY non-dict 'devices' (an int in a malformed/hostile upload) survives
    # `or {}` and 500s the eagerly-evaluated `len(...)` default below -- and summarize() runs on EVERY upload
    # (POST /snapshots) and on the /snapshots/{id} read (freshen), so that TypeError escapes as an HTTP 500.
    _dev = snap.get("devices")
    n_devices = len(_dev) if isinstance(_dev, dict) else 0

    try:
        head = engine.trend_point(snap)  # re-use the engine's headline extractor
    except Exception:
        head = {}                        # a malformed upload must degrade, not 500 the dashboard summary

    readiness = {"READY": 0, "CAUTION": 0, "NOT READY": 0}
    for r in mr:
        rd = _hkey(r.get("readiness"))     # an unhashable dict/list readiness label must not 500 the `in`
        if rd in readiness:
            readiness[rd] += 1

    _lr = snap.get("lifecycle_risk")
    _lrs = (_lr if isinstance(_lr, dict) else {}).get("summary")    # a truthy NON-dict summary (e.g. an older
    lr = _lrs if isinstance(_lrs, dict) else {}                     # engine's "not computed" string) must not 500

    return {
        "version": snap.get("script_version", ""),
        # Provenance of THIS projection (the engine build that computed it), distinct from `version`
        # (the snapshot's own collection-time script_version). A cached summary whose stamp trails the
        # running engine is recomputed on read so the headline cards never disagree with a live
        # section tab (app._summary_freshened).
        "engine_schema": engine.ENGINE_SCHEMA_VERSION,
        "n_switches": head.get("n_switches", n_devices),
        "avg_health": head.get("avg_health", ""),
        "bands": _count_by(hs, "band", BANDS),
        # n_critical must reconcile with the bands chart (both from health_scores): trend_point can silently
        # yield 0 when executive_brief is a corrupt non-dict (the try/except above swallows the AttributeError),
        # contradicting the bands chart on the SAME screen -- fall back to the band count (audit-5 cross-artifact #4).
        "n_critical": head.get("n_critical") if isinstance(head.get("n_critical"), int)
        else _count_by(hs, "band", BANDS).get("Critical", 0),
        "punchlist": {
            "total": len(pl),
            "by_severity": _count_by(pl, "severity", SEVERITY_ORDER),
            "by_category": _count_by(pl, "category"),
            "crit_high": head.get("n_crit_high", 0),
        },
        "readiness": readiness,
        "keystones": _keystones(snap),
        # Which keystone ranking produced the list above; a cached summary from an older one is recomputed on
        # read (app._summary_freshened), so a stored raw-row ranking cannot outlive the fix.
        "keystone_contract": KEYSTONE_CONTRACT_VERSION,
        "lifecycle": _lifecycle(lr) if lr else {},
        "verification": snapshot_verification(snap),
        "sections": _section_index(snap),
    }
