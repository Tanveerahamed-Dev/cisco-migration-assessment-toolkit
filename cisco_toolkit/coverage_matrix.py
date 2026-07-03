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
from typing import Any, Dict, List

# capture-integrity statuses, worst first (mirrors capture_integrity's own severity ordering)
_CAPTURE_WORST = ("error", "incomplete", "unverified_prompt", "empty")

_AXIS_ORDER = ("collection", "capture", "parse")

# the synthetic device key for a fleet-level (not-observed architecture) abstention row -- NOT a real device,
# so it is emitted as a row but deliberately kept OUT of the per-device by_device view / n_devices count.
_FLEET = "(fleet)"

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
        if isinstance(f, dict) and f.get("host"):
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
        if ev.get("error") or ev.get("parser") not in MAY_BE_EMPTY_PARSERS:
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
