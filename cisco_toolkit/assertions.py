"""Deterministic, offline state-assertion check-pack evaluator — roadmap A1 PROOF SPIKE.

Evaluates a committed JSON check-pack over a parsed snapshot. NO LLM, NO network, READ-ONLY: it
reads the static ``snapshot.json`` and writes nothing to any device. This is the offline,
coverage-honest analog of Itential's Command-Template grammar / NetBrain's Network Intents — NRFU
and pre/post checks expressed as **data** instead of hard-coded ``compute_*`` prose.

Coverage-honesty is the whole point: an assertion whose subject was never collected (a blind spot)
returns :data:`NOT_OBSERVED` and is **excluded from the pass/fail denominator** — "not observed"
never silently becomes a pass (the ``show logging``-on-NX-OS false-health class). The 3-state
distinction is delegated to :func:`cisco_toolkit.ssot.abstention_reason`, the engine's single source
of truth for it.

Pack shape (committed to the repo, air-gap-friendly)::

    {"assertions": [
        {"id": "ntp", "title": "authenticated NTP", "severity": "medium",
         "subject": "executive_brief.scale.n_devices",   # dotted snapshot path (optionally "device": "<host>")
         "all_of": [{"type": "comparison", "op": ">=", "value": 1}],
         "any_of": [{"type": "regex", "value": "ntp server", "ignorecase": true}]}
    ]}

Rule types: ``contains / not_contains / regex / not_regex`` (string match over the stringified
subject) and ``comparison`` (``op`` in ``== != > >= < <=`` over the first number in the subject).
``all_of`` must all hold; ``any_of`` needs one. A rule that cannot be evaluated (e.g. a numeric
comparison on a non-numeric subject) is skipped; if nothing can be evaluated the result is
:data:`NOT_OBSERVED` rather than a fabricated pass/fail.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

try:                                  # normal package import
    from . import ssot
except Exception:                     # pragma: no cover - allow standalone import
    import ssot  # type: ignore

PASS = "pass"
FAIL = "fail"
NOT_OBSERVED = "not_observed"

_OPS = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
}


def _dotted(snap: Dict[str, Any], path: Optional[str]) -> Any:
    """Read a dotted snapshot path; None if any hop is missing/not a dict (mirrors ssot._dotted)."""
    if not path:
        return None
    cur: Any = snap
    for hop in str(path).split("."):
        if not isinstance(cur, dict) or hop not in cur:
            return None
        cur = cur[hop]
    return cur


def _as_text(value: Any) -> str:
    """Stringify a subject value for text rules — deterministic (sorted keys) so a pack is reproducible."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, default=str)


def _coerce_num(value: Any):
    """(kind, number): kind 'num' (a clean numeric token / int / float -> the number), 'ambig' (has digits
    but is not a clean token, e.g. 'Gi0/1, 5 errors' -> can't pin a value), or 'none' (no digit at all ->
    definitively non-numeric). The strict token rule refuses to guess a number from messy text."""
    if isinstance(value, bool):
        return ("ambig", None)
    if isinstance(value, (int, float)):
        return ("num", float(value))
    s = str(value).strip()
    if re.fullmatch(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", s):
        try:
            return ("num", float(s))
        except ValueError:
            return ("ambig", None)
    return ("ambig", None) if re.search(r"\d", s) else ("none", None)


def _as_number(value: Any) -> Optional[float]:
    """A value as a number ONLY when it is a single clean numeric token (or an int/float), else None.
    Refuses to grab the first partial number from a multi-number string (the false-health class)."""
    kind, num = _coerce_num(value)
    return num if kind == "num" else None


def _re_search(pattern: Any, text: str, flags: int = 0) -> Optional[bool]:
    """re.search guarded against a malformed pack-supplied pattern: True/False, or None when it won't compile."""
    try:
        return re.search(str(pattern), text, flags) is not None
    except re.error:
        return None


def _first_num(pattern: Any, text: str, flags: int = 0) -> Optional[float]:
    """First number captured by ``pattern`` in ``text`` (group 1 if present, else whole match); None on a bad pattern."""
    if pattern is None:
        return None
    try:
        m = re.search(str(pattern), text, flags)
    except re.error:
        return None
    if not m:
        return None
    return _as_number(m.group(1) if m.groups() else m.group(0))


def _rule_holds(rule: Dict[str, Any], text: str, raw: Any) -> Optional[bool]:
    """Evaluate ONE rule. Returns True/False, or None when the rule cannot be evaluated (skip)."""
    rtype = (rule.get("type") or "").strip()
    val = rule.get("value")
    flags = re.IGNORECASE if rule.get("ignorecase") else 0
    if rtype == "contains":
        return str(val) in text
    if rtype == "not_contains":
        return str(val) not in text
    if rtype == "regex":
        return _re_search(val, text, flags)
    if rtype == "not_regex":
        hit = _re_search(val, text, flags)
        return None if hit is None else (not hit)
    if rtype == "comparison":
        num = _as_number(raw)
        if num is None:
            return None
        try:
            target = float(val)
        except (TypeError, ValueError):
            return None
        op = _OPS.get(rule.get("op") or "==")
        return None if op is None else op(num, target)
    if rtype == "contains1":              # Itential 'contains1' — present exactly once
        return text.count(str(val)) == 1
    if rtype == "ratio":                  # Itential '#comparison %' — extract two operands, compare a percentage
        num = _first_num(rule.get("numerator"), text, flags)
        den = _first_num(rule.get("denominator"), text, flags)
        if num is None or den is None or den <= 0:
            return None                   # zero/negative/garbage denominator -> abstain, never a false pass
        try:
            target = float(val)
        except (TypeError, ValueError):
            return None
        op = _OPS.get(rule.get("op") or "<=")
        return None if op is None else op(100.0 * num / den, target)
    return None                           # unknown/typo'd rule type -> unevaluable -> the assertion abstains (never aborts the pack)


def evaluate_assertion(snap: Dict[str, Any], a: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate one assertion against the snapshot -> a coverage-honest result dict.

    ``status`` is one of :data:`PASS` / :data:`FAIL` / :data:`NOT_OBSERVED`. ``citation`` is the
    snapshot path that backs the verdict (deterministic grounding). ``abstention`` records the SSOT
    3-state reason. A subject (or device) that was never collected is :data:`NOT_OBSERVED` — a blind
    spot, never a silent pass.
    """
    subject = a.get("subject")
    device = a.get("device")
    if subject is None:                                   # nothing to ground a verdict on -> abstain, never a vacuous pass
        return {"id": a.get("id"), "title": a.get("title"), "severity": a.get("severity", "medium"),
                "subject": None, "device": device, "citation": None, "abstention": "indeterminate",
                "status": NOT_OBSERVED, "detail": "no subject — nothing to ground a verdict on"}
    abst = ssot.abstention_reason(snap, subject, device)
    out: Dict[str, Any] = {
        "id": a.get("id"),
        "title": a.get("title"),
        "severity": a.get("severity", "medium"),
        "subject": subject,
        "device": device,
        "citation": subject,
        "abstention": abst,
    }
    if abst == "not_collected":
        out["status"] = NOT_OBSERVED
        out["detail"] = "subject not collected — blind spot (not asserted, never assumed healthy)"
        return out

    raw = _dotted(snap, subject)
    text = _as_text(raw)
    group_results: List[Optional[bool]] = []
    had_unevaluable = False
    for mode, key in (("all", "all_of"), ("any", "any_of")):
        rules = a.get(key) or []
        if not rules:
            continue
        if not isinstance(rules, list):
            rules = [rules]
        evaluated = [_rule_holds(rule, text, raw) if isinstance(rule, dict) else None for rule in rules]
        had_unevaluable = had_unevaluable or any(r is None for r in evaluated)
        evals = [r for r in evaluated if r is not None]
        if not evals:
            group_results.append(None)
        else:
            group_results.append(all(evals) if mode == "all" else any(evals))

    decided = [g for g in group_results if g is not None]
    if not decided:
        out["status"] = NOT_OBSERVED
        out["abstention"] = "indeterminate"
        out["detail"] = "no rule could be evaluated against the collected value"
        return out
    if any(g is False for g in decided):
        out["status"] = FAIL
        out["detail"] = "one or more rules failed"
        return out
    if had_unevaluable:
        # A known-true rule cannot launder a typo, malformed regex, or unsupported sibling rule
        # into PASS.  The assertion remains unknown until every declared rule is understood.
        out["status"] = NOT_OBSERVED
        out["abstention"] = "indeterminate"
        out["detail"] = "one or more declared rules could not be evaluated; PASS withheld"
        return out
    ok = all(decided)
    out["status"] = PASS if ok else FAIL
    out["detail"] = "all rule groups satisfied" if ok else "one or more rules failed"
    return out


def _rows_for_each(snap: Dict[str, Any], path: Any) -> Optional[List[Dict[str, Any]]]:
    """Resolve a for-each collection, including the common host->object-map snapshot shapes."""
    if not isinstance(path, str) or not path.strip():
        return None
    raw = _dotted(snap, path)
    if isinstance(raw, list):
        # Preserve malformed elements as explicit unknown rows. Dropping them would let the
        # well-formed subset certify the whole declared collection.
        return [dict(r) if isinstance(r, dict) else {"_invalid_object": True} for r in raw]
    if not isinstance(raw, dict):
        return None
    rows: List[Dict[str, Any]] = []
    for host, value in raw.items():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    rows.append(dict(item, **({"host": host} if "host" not in item else {})))
                else:
                    rows.append({"host": host, "_invalid_object": True})
        elif isinstance(value, dict):
            # ``interfaces`` is host -> ifname -> record; a shallower host -> record map is
            # handled by the fallback row below.
            nested = [(name, item) for name, item in value.items() if isinstance(item, dict)]
            if nested and len(nested) == len(value):
                for name, item in nested:
                    row = dict(item)
                    row.setdefault("host", host)
                    row.setdefault("ifname", name)
                    rows.append(row)
            else:
                row = dict(value)
                row.setdefault("host", host)
                rows.append(row)
        else:
            rows.append({"host": host, "_invalid_object": True})
    return rows


def _evaluate_object_assertion(snap: Dict[str, Any], spec: Dict[str, Any]) -> Dict[str, Any]:
    """Adapt :func:`evaluate_for_each` into the ordinary pack result contract."""
    path = spec.get("for_each") or spec.get("collection")
    if isinstance(path, dict):
        path = path.get("subject") or path.get("collection")
    rows = _rows_for_each(snap, path)
    base = {
        "id": spec.get("id"), "title": spec.get("title"),
        "severity": spec.get("severity", "medium"), "subject": path,
        "device": None, "citation": path, "kind": "for_each",
    }
    if rows is None:
        return dict(base, status=NOT_OBSERVED, abstention="not_collected",
                    detail="for_each collection missing or unusable", object_evaluation=None)
    detail = evaluate_for_each(rows, spec)
    summary = detail["summary"]
    if not spec.get("field_rules") and not spec.get("unique_by"):
        status = NOT_OBSERVED
        text = "for_each declaration has no field_rules or unique_by constraint; PASS withheld"
        abstention = "indeterminate"
    elif summary["n_fail"] or summary["n_uniqueness_violations"]:
        status = FAIL
        text = (f"{summary['n_fail']} row failure(s), "
                f"{summary['n_uniqueness_violations']} uniqueness violation(s)")
        abstention = None
    elif not summary["n_rows"] or (spec.get("field_rules") and summary["n_not_observed"]) \
            or (spec.get("unique_by") and summary["unique_by_observed_rows"] < summary["n_rows"]):
        status = NOT_OBSERVED
        text = "per-object proof incomplete; one or more rows/fields were not observed"
        abstention = "indeterminate"
    else:
        status = PASS
        text = f"all {summary['n_rows']} object row(s) satisfied the declared constraints"
        abstention = None
    return dict(base, status=status, abstention=abstention, detail=text,
                object_evaluation=detail)


def evaluate_pack(snap: Dict[str, Any], pack: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate a whole check-pack -> ``{results: [...], summary: {...}}``.

    The summary's ``n_assessed`` denominator EXCLUDES :data:`NOT_OBSERVED` results (coverage-honest:
    a blind spot is neither pass nor fail). ``grade`` is ``fail`` if any assertion failed, else
    ``pass`` if anything was assessable, else ``na``.
    """
    pack = pack if isinstance(pack, dict) else {}
    items = pack.get("assertions") or []
    if not isinstance(items, list):
        items = [items]
    object_items = pack.get("for_each") or []
    if isinstance(object_items, dict):
        object_items = [object_items]
    elif not isinstance(object_items, list):
        object_items = []
    specs = [a for a in list(items) + list(object_items) if isinstance(a, dict)]
    results = [
        (_evaluate_object_assertion(snap, a)
         if a.get("for_each") or a.get("collection") or a in object_items
         else evaluate_assertion(snap, a))
        for a in specs
    ]
    n_pass = sum(1 for r in results if r["status"] == PASS)
    n_fail = sum(1 for r in results if r["status"] == FAIL)
    n_not_observed = sum(1 for r in results if r["status"] == NOT_OBSERVED)
    n_assessed = n_pass + n_fail
    grade = "na" if n_assessed == 0 else ("fail" if n_fail else "pass")
    return {
        "results": results,
        "object_results": [r for r in results if r.get("kind") == "for_each"],
        "summary": {
            "n_pass": n_pass,
            "n_fail": n_fail,
            "n_not_observed": n_not_observed,
            "n_assessed": n_assessed,
            "grade": grade,
        },
    }


# --------------------------------------------------------------------------- per-object for_each (roadmap H2)
def _row_key(row: Dict[str, Any], idx: int) -> str:
    host = row.get("host")
    sub = row.get("ifname") or row.get("name") or row.get("interface")
    if host and sub:
        return "%s::%s" % (host, sub)
    if host:
        return "%s#%d" % (host, idx)       # disambiguate multiple host-only rows (VLAN/SVI/port-channel) so none collide
    return "row%d" % idx


def _field_pred(op: str, value: Any, present: bool, target: Any) -> str:
    """One per-field rule over one row's field -> PASS / FAIL / NOT_OBSERVED. A value-comparing rule over a
    field that was never collected returns NOT_OBSERVED (never a silent pass)."""
    op = (op or "").strip()
    if op == "required":
        return PASS if present else FAIL
    if op == "prohibited":
        return PASS if not present else FAIL
    if not present:
        return NOT_OBSERVED
    s = str(value)
    if op in ("min", "max"):
        try:
            t = float(target)
        except (TypeError, ValueError):
            return NOT_OBSERVED
        kind, n = _coerce_num(value)
        if kind == "num":
            return PASS if (n >= t if op == "min" else n <= t) else FAIL
        if kind == "none":                # a collected non-numeric value can't satisfy a numeric bound -> observed negative
            return FAIL
        return NOT_OBSERVED               # ambiguous multi-number -> can't pin a value -> abstain
    if op in ("eq", "neq"):
        na, nb = _as_number(value), _as_number(target)
        eq = (na == nb) if (na is not None and nb is not None) else (s == str(target))
        return (PASS if eq else FAIL) if op == "eq" else (FAIL if eq else PASS)
    if op == "regex":
        hit = _re_search(target, s)
        return NOT_OBSERVED if hit is None else (PASS if hit else FAIL)
    if op == "in":
        opts = target if isinstance(target, (list, tuple)) else [target]
        nv = _as_number(value)
        for o in opts:
            no = _as_number(o)
            if (nv is not None and no is not None and nv == no) or s == str(o):
                return PASS
        return FAIL
    return NOT_OBSERVED


def evaluate_for_each(rows: List[Dict[str, Any]], spec: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate per-row field predicates + a cross-row uniqueness constraint over a snapshot collection.

    `spec` = {id, field_rules:[{field, op, value?}], unique_by?}. ops: required / prohibited / min / max /
    eq / neq / regex / in. A row's verdict is FAIL if any rule fails, else NOT_OBSERVED if any rule abstains
    (a missing field), else PASS. `unique_by` flags duplicate values across rows. Pure; coverage-honest."""
    spec = spec or {}
    rules = spec.get("field_rules") or []
    if not isinstance(rules, list):
        rules = [rules]
    out_rows: List[dict] = []
    for idx, row in enumerate(rows or []):
        row = row if isinstance(row, dict) else {}
        rule_results = []
        for r in rules:
            if not isinstance(r, dict):
                rule_results.append({"field": None, "op": None, "status": NOT_OBSERVED})
                continue
            field = r.get("field")
            present = isinstance(field, str) and field in row and row.get(field) not in (None, "")
            rule_results.append({"field": field, "op": r.get("op"),
                                 "status": _field_pred(r.get("op"), row.get(field), present, r.get("value"))})
        statuses = [rr["status"] for rr in rule_results]
        if FAIL in statuses:
            rv = FAIL
        elif NOT_OBSERVED in statuses or not statuses:
            rv = NOT_OBSERVED
        else:
            rv = PASS
        out_rows.append({"key": _row_key(row, idx), "status": rv, "rules": rule_results})

    uniq_viol: List[dict] = []
    uniq_field = spec.get("unique_by")
    uniq_observed = 0
    if uniq_field:
        groups: Dict[str, List[str]] = {}
        for idx, row in enumerate(rows or []):
            row = row if isinstance(row, dict) else {}
            if uniq_field in row and row.get(uniq_field) not in (None, ""):
                uniq_observed += 1
                groups.setdefault(str(row[uniq_field]), []).append(_row_key(row, idx))
        for val, keys in sorted(groups.items()):
            if len(keys) > 1:
                uniq_viol.append({"value": val, "keys": sorted(keys), "count": len(keys)})

    summary = {
        "n_rows": len(out_rows),
        "n_pass": sum(1 for r in out_rows if r["status"] == PASS),
        "n_fail": sum(1 for r in out_rows if r["status"] == FAIL),
        "n_not_observed": sum(1 for r in out_rows if r["status"] == NOT_OBSERVED),
        "n_uniqueness_violations": len(uniq_viol),
        # how many rows actually carried unique_by, so "0 violations" over 0 observed rows isn't read as 'verified unique'
        "unique_by_observed_rows": uniq_observed,
    }
    return {"rows": out_rows, "uniqueness_violations": uniq_viol, "summary": summary}
