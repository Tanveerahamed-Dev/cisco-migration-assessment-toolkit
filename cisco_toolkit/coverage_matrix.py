"""Coverage-as-a-first-class row (Plan-A #5) — the one idea worth stealing from the rejected
DuckDB plan, without a columnar engine.

Coverage-honesty is tracked today in FOUR differently-keyed artifacts, and "covered" is
expressed three different ways (mostly as *silence* — no row = covered):
  * collection_completeness  — was the device COLLECTED?           (per host; blind-spots only)
  * capture_integrity        — was the CAPTURE verified/untruncated? (per (host,command) finding)
  * parse_yield              — was the command PARSED to entities?   (per parser; best-effort host)
  * architecture_coverage    — was the ARCH CLASS observed?          (per axis; explicit status)

You cannot today SELECT a (device, axis) pair and read its coverage verdict. `compute_coverage_matrix`
COMPOSES the four published sources into ONE per-(device, axis) table — it recomputes NO device state,
it projects the existing verdicts and quotes their own evidence. Coverage-honest by construction:
`covered` is emitted only when a source POSITIVELY proves it; every blind spot is an explicit
abstention state (`not_collected` / `partial` / `unverified` / `unparsed` / `not_observed`) with
`is_abstention=True`, never silently a pass.
"""
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple, TypeGuard

# capture-integrity statuses, worst first — IMPORTED from the owner, not restated (Law 1). This was a
# hand-written tuple ("error", "incomplete", "unverified_prompt", "empty") and had drifted twice: it
# never learned `unreadable` (the owner's WORST status, so an unreadable capture ranked as unknown =
# least severe and `_worst_capture` cited a lesser `empty` finding instead), and it ordered `empty` and
# `unverified_prompt` the opposite way round from the owner. A matrix whose whole job is coverage
# honesty was quoting the wrong evidence for the blind spot it reported.
from cisco_toolkit.capture_integrity import STATUS_ORDER as _CAPTURE_STATUS_ORDER

_CAPTURE_WORST = tuple(sorted(_CAPTURE_STATUS_ORDER, key=_CAPTURE_STATUS_ORDER.get))

_AXIS_ORDER = ("collection", "capture", "parse")

# the synthetic device key for a fleet-level (not-observed architecture) abstention row -- NOT a real device,
# so it is emitted as a row but deliberately kept OUT of the per-device by_device view / n_devices count.
_FLEET = "(fleet)"

# Conservative evidence-limit precedence for a DEVICE rollup, not a risk or health ranking.
# A covered cell remains only the matrix producer's published verdict: capture/parse silence
# is not positive proof that those owners ran, and projection publication retains that caveat.
COVERAGE_STATE_ORDER = ("not_collected", "unverified", "unparsed", "partial", "not_observed", "covered")
COVERAGE_DIMENSIONS = ("collection", "capture", "parse", "architecture")
COVERAGE_VERDICT_SOURCES = ("collection_completeness", "capture_integrity", "parse_yield", "architecture_coverage")


@dataclass
class CoverageRowIndex:
    """One pure stored-row index; unreadable identities cannot be assigned to any safe subject."""
    problem: Optional[str]
    by_key: Dict[Tuple[str, str], List[Tuple[int, Dict[str, Any]]]]
    axes_by_device: Dict[str, Set[str]]
    unreadable_indices: Tuple[int, ...] = ()


def _coverage_identity(value: Any) -> TypeGuard[str]:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        value.encode("utf-8")
    except UnicodeError:
        return False
    return True


def index_coverage_rows(raw: Any) -> CoverageRowIndex:
    """Index exact device/axis identities once, retaining duplicates and original row indices.

    Payload validation belongs to the exact cell match. A known different subject's bad payload
    need not poison this one; an unreadable subject or non-record row might be this one and makes
    the whole index unusable. Nothing is recomputed or persisted, and no identity is normalized.
    """
    by_key: Dict[Tuple[str, str], List[Tuple[int, Dict[str, Any]]]] = {}
    axes_by_device: Dict[str, Set[str]] = {}
    if not isinstance(raw, list):
        return CoverageRowIndex("coverage rows are missing or not a list", by_key, axes_by_device)
    unreadable: List[int] = []
    for index, record in enumerate(raw):
        host = record.get("device") if isinstance(record, dict) else None
        axis = record.get("axis") if isinstance(record, dict) else None
        if not _coverage_identity(host) or not _coverage_identity(axis):
            unreadable.append(index)
            continue
        # Copy only the row dictionary, never arbitrary unvalidated subtrees. The index retains
        # source metadata for refusals; matched output contains only admitted scalar fields below.
        copied = dict(record)
        by_key.setdefault((host, axis), []).append((index, copied))
        axes_by_device.setdefault(host, set()).add(axis)
    problem = (f"coverage rows have {len(unreadable)} unreadable device/axis identities or non-record rows"
               if unreadable else None)
    return CoverageRowIndex(problem, by_key, axes_by_device, tuple(unreadable))


def match_coverage_cell(index: Optional[CoverageRowIndex], host: Any, axis: Any,
                        expected_state: Any) -> Optional[Tuple[int, Dict[str, Any]]]:
    """One unambiguous, producer-compatible row for the stored by-device cell, or no usable join."""
    if (not isinstance(index, CoverageRowIndex) or index.problem is not None
            or not _coverage_identity(host) or not _coverage_identity(axis) or host == _FLEET
            or not isinstance(expected_state, str) or expected_state not in COVERAGE_STATE_ORDER):
        return None
    matches = index.by_key.get((host, axis), [])
    if len(matches) != 1:
        return None
    position, record = matches[0]
    state, dimension, source = record.get("state"), record.get("dimension"), record.get("verdict_source")
    abstained = record.get("is_abstention")
    if (record.get("device") != host or record.get("axis") != axis
            or not isinstance(state, str) or state not in COVERAGE_STATE_ORDER or state != expected_state
            or not isinstance(dimension, str) or dimension not in COVERAGE_DIMENSIONS
            or not isinstance(source, str) or source not in COVERAGE_VERDICT_SOURCES
            or type(abstained) is not bool or abstained is not (state != "covered")):
        return None
    # The current producer's exact state/source combinations. A capture/parse cell may cite the
    # collection owner only when it explicitly says this device was never collected.
    if dimension == "collection":
        valid = axis == "collection" and source == "collection_completeness" and state in (
            "covered", "partial", "not_collected")
    elif dimension == "capture":
        valid = axis == "capture" and (
            (source == "capture_integrity" and state in ("covered", "unverified"))
            or (source == "collection_completeness" and state == "not_collected"))
    elif dimension == "parse":
        valid = axis == "parse" and (
            (source == "parse_yield" and state in ("covered", "unparsed"))
            or (source == "collection_completeness" and state == "not_collected"))
    else:
        valid = (axis not in _AXIS_ORDER and source == "architecture_coverage"
                 and state == "covered")
    if not valid:
        return None
    return position, {key: record[key] for key in (
        "device", "axis", "state", "dimension", "verdict_source", "is_abstention")}


def compute_device_coverage(by_device: Any, index: Optional[CoverageRowIndex],
                            host: Any) -> Optional[Dict[str, Any]]:
    """Pure unpersisted rollup of one exact nonempty, fully reconciled stored device mapping.

    Require all three core axes and exactly the source row universe for this host. Zero abstained
    axes and worst=covered are mathematical folds of nominal stored states, not proof of complete
    collection; the projection must withhold/qualify them under its existing silence caveat.
    """
    if (not isinstance(by_device, dict) or not isinstance(index, CoverageRowIndex)
            or index.problem is not None or not _coverage_identity(host) or host == _FLEET):
        return None
    cells = by_device.get(host)
    if (not isinstance(cells, dict) or not cells
            or not all(_coverage_identity(axis) for axis in cells)
            or not set(_AXIS_ORDER).issubset(cells)
            or set(cells) != index.axes_by_device.get(host, set())):
        return None
    rows: List[Tuple[int, Dict[str, Any]]] = []
    for axis, state in cells.items():
        match = match_coverage_cell(index, host, axis, state)
        if match is None:
            return None
        rows.append(match)
    states = {record["state"] for _position, record in rows}
    worst = next(state for state in COVERAGE_STATE_ORDER if state in states)
    return {"worst": worst, "n_abstained": sum(record["state"] != "covered" for _position, record in rows),
            "row_indices": sorted(position for position, _record in rows)}

_NOTE = ("Each row is one (device, axis) coverage verdict COMPOSED from the four published coverage "
         "sources; no device state is recomputed. 'not_collected' / 'partial' / 'unverified' / "
         "'unparsed' / 'not_observed' are ABSTENTIONS — the engine did not prove the evidence, which "
         "is NOT the same as healthy. 'covered' is emitted only where a source positively proves it.")


def _d(v) -> dict:
    return v if isinstance(v, dict) else {}


def _l(v) -> list:
    return v if isinstance(v, list) else []


def _row(device, axis, dimension, state, source, evidence="") -> Dict[str, Any]:
    return {"device": device, "axis": axis, "dimension": dimension, "state": state,
            "verdict_source": source, "evidence": evidence, "is_abstention": state != "covered"}


def _worst_capture(findings: List[dict]) -> dict:
    def rank(f):
        st = str(f.get("status", "")).lower()
        return _CAPTURE_WORST.index(st) if st in _CAPTURE_WORST else len(_CAPTURE_WORST)
    return sorted(findings, key=rank)[0]


def compute_coverage_matrix(snap: Dict[str, Any]) -> Dict[str, Any]:
    """Compose snap's four coverage sources into a per-(device, axis) matrix. Pure over the
    snapshot, deterministic, fail-soft (a missing source just yields fewer rows)."""
    snap = _d(snap)
    rows: List[Dict[str, Any]] = []

    # collection_completeness lists only the blind spots (partial / not-collected hosts).
    cc_by_host: Dict[str, dict] = {}
    for _rec in _l(_d(snap.get("collection_completeness")).get("devices")):
        _h = _rec.get("host") if isinstance(_rec, dict) else None
        if isinstance(_h, str) and _h:
            cc_by_host[_h] = _rec
    # Join key 1 = the INVENTORY universe = collected devices UNION the collection_completeness blind spots.
    # snap['devices'] is built only from hosts that collected (COLLECT_PARSE: `if cmd_to_file is None: continue`),
    # so a device the collection never reached (unreachable / auth-fail) is absent there yet present in
    # collection_completeness as 'not collected'. Joining on snap['devices'] alone silently dropped it -> zero
    # rows -> it read as fully covered (the coverage-honesty inversion this module exists to prevent, PR #279).
    _dev = snap.get("devices")
    dev_keys = {k for k in _dev if isinstance(k, str)} if isinstance(_dev, dict) else set()
    devices = sorted(dev_keys | set(cc_by_host))
    device_set = set(devices)                                 # hoisted: membership-tested throughout
    # A host the collection never reached is a blind spot on EVERY axis (nothing was captured or parsed
    # either) -> its capture/parse 'covered-by-silence' inference is invalid (PR #279).
    not_collected = {h for h, rec in cc_by_host.items() if "not" in str(rec.get("status", "")).lower()}

    # --- collection axis: present-with-status in collection_completeness -> abstain; absent -> covered
    for host in devices:
        rec = cc_by_host.get(host)
        if rec is None:
            state, ev = "covered", ""
        else:
            st = str(rec.get("status", "")).lower()
            state = "not_collected" if "not" in st else ("partial" if "partial" in st else "covered")
            miss = rec.get("missing")
            ev = ", ".join(miss) if isinstance(miss, list) else str(miss or "")
        rows.append(_row(host, "collection", "collection", state, "collection_completeness", ev))

    # --- capture axis: any non-ok capture finding for the host -> unverified (worst); else covered
    ci_by_host: Dict[str, list] = {}
    for f in _l(_d(snap.get("capture_integrity")).get("findings")):
        # isinstance(str): the host is used as a dict KEY here and matched against `devices` below, so an
        # unhashable dict/list leaf (a malformed / foreign-tool snapshot) raised
        # `TypeError: unhashable type: 'list'`. A non-str can never match an inventory hostname anyway,
        # so dropping it loses nothing -- and the host it would have flagged still reads 'covered' from
        # its own axis rather than the whole matrix failing to build.
        if isinstance(f, dict) and isinstance(f.get("host"), str) and f["host"]:
            ci_by_host.setdefault(f["host"], []).append(f)
    for host in devices:
        if host in not_collected:                             # never reached -> nothing to verify (never a fake 'covered')
            rows.append(_row(host, "capture", "capture", "not_collected", "collection_completeness"))
            continue
        finds = ci_by_host.get(host)
        if finds:
            w = _worst_capture(finds)
            rows.append(_row(host, "capture", "capture", "unverified", "capture_integrity",
                             f"{w.get('command', '')}: {w.get('reason', '')}".strip(": ")))
        else:
            rows.append(_row(host, "capture", "capture", "covered", "capture_integrity"))

    # --- parse axis: a SUSPECT zero-parse/error event for the host -> unparsed; else covered.
    # Suspect = an error, or a zero-yield whose parser is NOT in the may-be-empty exemption set.
    try:
        from cisco_toolkit.cmdio import MAY_BE_EMPTY_PARSERS
    except Exception:                                          # pragma: no cover
        MAY_BE_EMPTY_PARSERS = frozenset()
    # events attribute the device by its on-disk collection-dir basename = safe_fs_name(hostname); map that
    # back to the RAW inventory key so a host whose name carries an FS-reserved char (':' '/' '\' ...) still
    # attributes its suspect event instead of silently reading 'covered' (a coverage-honesty false-health).
    try:
        from cisco_toolkit.textutils import safe_fs_name
        fs_to_dev = {safe_fs_name(h): h for h in devices}
    except Exception:                                          # pragma: no cover
        fs_to_dev = {}
    py_suspect: Dict[str, list] = {}
    for ev in _l(_d(snap.get("parse_yield")).get("events")):
        if not isinstance(ev, dict):
            continue
        # `x not in <frozenset>` HASHES x, so an unhashable dict/list `parser` raised TypeError here.
        # A non-str parser name can never be in the exemption set -> treat it as suspect (the
        # coverage-honest direction: an unreadable parse event is never silently exempted).
        _p = ev.get("parser")
        if ev.get("error") or not isinstance(_p, str) or _p not in MAY_BE_EMPTY_PARSERS:
            raw = ev.get("device")
            if not isinstance(raw, str):
                continue
            dev = raw if (raw in device_set or raw in cc_by_host) else fs_to_dev.get(raw)
            if dev is not None and (dev in cc_by_host or dev in device_set):   # a real inventory device
                py_suspect.setdefault(dev, []).append(ev)
    for host in devices:
        if host in not_collected:                             # never reached -> nothing to parse (never a fake 'covered')
            rows.append(_row(host, "parse", "parse", "not_collected", "collection_completeness"))
            continue
        sus = py_suspect.get(host)
        if sus:
            rows.append(_row(host, "parse", "parse", "unparsed", "parse_yield",
                             f"{sus[0].get('parser', '')} on {sus[0].get('cmd', '')}".strip()))
        else:
            rows.append(_row(host, "parse", "parse", "covered", "parse_yield"))

    # --- architecture axes: observed class -> a covered row per host (a fired detector still means the
    # axis WAS observed; coverage != health); not-observed class -> one fleet-level abstention row.
    for c in _l(_d(snap.get("architecture_coverage")).get("classes")):
        if not isinstance(c, dict):
            continue
        key = c.get("key") or "?"
        if c.get("observed"):
            ev = ", ".join(_l(c.get("findings"))) if c.get("status") == "finding" else ""
            # Coverage-honest join: a class's `hosts` are trustworthy device ids only when they are inventory
            # members. A malformed / bare struct-keyed axis ({faults:.., nodes:..}) would otherwise leak its
            # STRUCTURAL FIELDS as fake 'covered' device rows; emit per-host only for a real device, else
            # collapse the observed class to one (fleet) covered row (observed -> coverage != health) (PR #282).
            real_hosts = [h for h in _l(c.get("hosts")) if h in device_set]
            if real_hosts:
                for host in real_hosts:
                    rows.append(_row(host, key, "architecture", "covered", "architecture_coverage", ev))
            else:
                rows.append(_row(_FLEET, key, "architecture", "covered", "architecture_coverage", ev))
        else:
            rows.append(_row(_FLEET, key, "architecture", "not_observed", "architecture_coverage",
                             str(c.get("label", ""))))

    # by_device is the per-DEVICE view -> exclude the synthetic _FLEET rows (fleet-level abstentions are in
    # `rows`, but they are not a device and must not appear as a phantom host or inflate a device count).
    by_device: Dict[str, Dict[str, str]] = {}
    for r in rows:
        if r["device"] == _FLEET:
            continue
        by_device.setdefault(r["device"], {})[r["axis"]] = r["state"]
    n_abstained = sum(1 for r in rows if r["is_abstention"])
    return {
        "rows": rows,
        "by_device": by_device,
        "summary": {
            "n_devices": len(devices),
            # count the coverage DIMENSIONS (collection/capture/parse/architecture), NOT each architecture key
            # -- keying on r["axis"] would inflate this to ~1 + n_arch_classes and misread as 'axes assessed'.
            "n_axes": len({r["dimension"] for r in rows}),
            "n_rows": len(rows),
            "n_covered": len(rows) - n_abstained,
            "n_abstained": n_abstained,
            "by_state": dict(Counter(r["state"] for r in rows)),
            "note": _NOTE,
        },
    }
