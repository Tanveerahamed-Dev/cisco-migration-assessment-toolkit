"""The snapshot-reporting layer: build the pre/post-cutover snapshot (snapshot_state - the JSON
contract embedded in the HTML and written beside every workbook) and render outputs from it - the
Blast-Radius Explorer HTML (write_html_explorer) and the '--compare OLD NEW' diff workbook
(write_diff_workbook). Extracted verbatim from COLLECT_PARSE_V3_23_0.py across PHASE 2.7 steps
29-30 (behaviour byte-identical). Depends on openpyxl + stdlib + the package's model/__version__."""
import json
import logging
import os
import re
from datetime import datetime
from typing import Dict, List

from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from cisco_toolkit import __version__
from cisco_toolkit.model import DevicePhysical, InterfaceData

logger = logging.getLogger(__name__)


_DIFF_FIELDS = ["status", "switchport_mode", "vlan", "trunk_native_vlan",
                "trunk_allowed_vlans", "stp_blocked", "port_channel",
                "svi_ip", "hsrp_behavior", "subnet_primary_route"]

def _macset(s: str) -> set:
    return set(t for t in re.split(r"[,\s;]+", s or "") if t)


# Pre/post-cutover VALIDATION (NEW-V3.23.106). Beyond the raw interface/SVI/MAC diff, compare the
# COMPUTED analysis between two snapshots so an operator can answer "did the cutover make anything
# worse?": per-switch health-band shifts and the consolidated punch-list findings that OPENED vs
# RESOLVED (the punch-list already rolls up all finding sources, deduped + severity-ranked). Pure
# read of two snapshot_state() dicts; tolerant of older snapshots that lack the computed keys.
_BAND_RANK = {"Excellent": 0, "Good": 1, "Fair": 2, "Poor": 3, "Critical": 4, "Insufficient Data": 5}
_FIND_SEV_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}


def _finding_key(f: dict) -> tuple:
    """Stable identity for a punch-list finding across two runs: (category, FULL title, device-set).
    The title is intentionally NOT digit-normalized: stripping digits collapsed DISTINCT per-identifier
    findings that differ only by an embedded id (e.g. 'Fake FHRP redundancy (VLAN 20)' vs '(VLAN 21)'
    on the same gateways) into one key, which could hide a real fix-and-new-break swap as 'no change'
    in the cutover-validation verdict. Device order is normalized so the same finding on the same
    devices matches regardless of listing order; an aggregated finding whose count changes honestly
    shows as resolved+opened (its scope genuinely changed)."""
    devs = tuple(sorted(str(d) for d in (f.get("devices") or [])))
    return (str(f.get("category", "")), str(f.get("title", "")), devs)


def compute_snapshot_delta(old: dict, new: dict) -> dict:
    """Migration-validation delta between two snapshots: switch/interface counts, per-switch health-band
    shifts (regressed vs improved), punch-list findings opened vs resolved, and an overall verdict.
    Returns a dict; every section degrades to empty when a snapshot lacks the computed keys."""
    od, nd = old.get("devices", {}) or {}, new.get("devices", {}) or {}
    oi, ni = old.get("interfaces", {}) or {}, new.get("interfaces", {}) or {}

    # ---- health-band shifts (per switch present in BOTH runs) ----
    oh = {r.get("switch"): r for r in (old.get("health_scores") or [])}
    nh = {r.get("switch"): r for r in (new.get("health_scores") or [])}
    regressed: List[dict] = []
    improved: List[dict] = []
    for sw in sorted(set(oh) & set(nh)):
        ob, nb = oh[sw].get("band", ""), nh[sw].get("band", "")
        orank, nrank = _BAND_RANK.get(ob, 9), _BAND_RANK.get(nb, 9)
        if nrank == orank:
            continue
        row = {"switch": sw, "old_band": ob, "new_band": nb,
               "old_score": oh[sw].get("score", ""), "new_score": nh[sw].get("score", "")}
        (regressed if nrank > orank else improved).append(row)
    regressed.sort(key=lambda r: -_BAND_RANK.get(r["new_band"], 0))

    # ---- punch-list findings opened vs resolved ----
    o_find = {_finding_key(f): f for f in (old.get("punchlist") or [])}
    n_find = {_finding_key(f): f for f in (new.get("punchlist") or [])}
    # fully-deterministic order (set-difference iteration order is unstable): severity, then the
    # finding's stable identity, so two runs of the diff workbook are byte-reproducible.
    def _fsort(f: dict) -> tuple:
        return (_FIND_SEV_RANK.get(f.get("severity", ""), 9), _finding_key(f))
    opened = sorted((n_find[k] for k in (set(n_find) - set(o_find))), key=_fsort)
    resolved = sorted((o_find[k] for k in (set(o_find) - set(n_find))), key=_fsort)
    n_opened_high = sum(1 for f in opened if f.get("severity") in ("Critical", "High"))

    # ---- verdict ----
    removed_sw = sorted(set(od) - set(nd))
    if n_opened_high or regressed:
        verdict = "REGRESSED"
        note = (f"{n_opened_high} new High/Critical finding(s); {len(regressed)} switch(es) dropped a "
                "health band. Investigate before declaring the cutover good.")
    elif opened or removed_sw:
        verdict = "REVIEW"
        note = (f"{len(opened)} new finding(s); {len(removed_sw)} switch(es) no longer present. "
                "Confirm these are expected.")
    else:
        verdict = "CLEAN"
        note = "No health-band regressions and no new findings — post-cutover state is no worse than pre."

    def _scn(s):  # SSOT: canonical device count (one source); raw len() only as the pre-brief fallback
        return ((s.get("executive_brief") or {}).get("scale") or {}).get("n_devices")
    return {
        "switches": {"old": _scn(old) or len(od), "new": _scn(new) or len(nd),
                     "added": sorted(set(nd) - set(od)), "removed": removed_sw},
        "interfaces": {"old": sum(len(v) for v in oi.values()), "new": sum(len(v) for v in ni.values())},
        "health": {"regressed": regressed, "improved": improved,
                   "n_regressed": len(regressed), "n_improved": len(improved)},
        "findings": {"opened": opened, "resolved": resolved, "n_opened": len(opened),
                     "n_resolved": len(resolved), "n_opened_high": n_opened_high},
        "verdict": verdict, "verdict_note": note,
    }

def write_diff_workbook(old: dict, new: dict, out_path: str) -> None:
    """Write a diff workbook (Summary / Interface Changes / Endpoint Changes /
    SVI Changes) comparing two snapshot_state() dicts."""
    from openpyxl import Workbook
    HF = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
    FILL = PatternFill("solid", fgColor="1F497D")
    AL = Alignment(horizontal="left", vertical="top", wrap_text=True)
    DF = Font(name="Calibri", size=10)
    NONE = "\u2205"  # empty marker

    wb = Workbook(); wb.remove(wb.active)
    from cisco_toolkit.excel import harden_workbook
    harden_workbook(wb)   # sanitize control chars in device-derived text -> no IllegalCharacterError abort

    def sheet(title, cols):
        ws = wb.create_sheet(title)
        for c, h in enumerate(cols, 1):
            cell = ws.cell(row=1, column=c, value=h)
            cell.font = HF; cell.fill = FILL
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.freeze_panes = "A2"
        return ws

    def autofit(ws, ncols):
        for col in range(1, ncols + 1):
            mx = len(str(ws.cell(row=1, column=col).value or ""))
            for row in range(2, ws.max_row + 1):
                v = ws.cell(row=row, column=col).value
                if v is not None: mx = max(mx, len(str(v)))
            ws.column_dimensions[get_column_letter(col)].width = min(max(mx + 2, 12), 60)

    oi, ni = old.get("interfaces", {}), new.get("interfaces", {})
    od, nd = old.get("devices", {}), new.get("devices", {})
    delta = compute_snapshot_delta(old, new)   # NEW-V3.23.106: migration-validation analysis

    # Summary (leads with the cutover-validation VERDICT)
    ws = sheet("Summary", ["Metric", "Old", "New", "Delta"])
    added_sw = sorted(set(nd) - set(od)); removed_sw = sorted(set(od) - set(nd))
    o_if = sum(len(v) for v in oi.values()); n_if = sum(len(v) for v in ni.values())
    _VERDICT_FILL = {"CLEAN": "C6EFCE", "REVIEW": "FFEB9C", "REGRESSED": "FFC7CE"}
    metrics = [
        ("CUTOVER VERDICT", "", delta["verdict"], delta["verdict_note"]),
        ("Switches", len(od), len(nd), len(nd) - len(od)),
        ("Switches added", "", "", ", ".join(added_sw) or "0"),
        ("Switches removed", "", "", ", ".join(removed_sw) or "0"),
        ("Interfaces (total)", o_if, n_if, n_if - o_if),
        ("Health bands regressed", "", delta["health"]["n_regressed"],
         ", ".join(r["switch"] for r in delta["health"]["regressed"]) or "0"),
        ("Health bands improved", "", delta["health"]["n_improved"], delta["health"]["n_improved"]),
        ("Findings opened", "", delta["findings"]["n_opened"],
         f"{delta['findings']['n_opened_high']} High/Critical"),
        ("Findings resolved", "", delta["findings"]["n_resolved"], delta["findings"]["n_resolved"]),
    ]
    r = 2
    for m in metrics:
        for c, v in enumerate(m, 1):
            cell = ws.cell(row=r, column=c, value=v); cell.font = DF; cell.alignment = AL
        if m[0] == "CUTOVER VERDICT":
            vc = ws.cell(row=r, column=3)
            vc.fill = PatternFill("solid", fgColor=_VERDICT_FILL.get(delta["verdict"], "FFFFFF"))
            vc.font = Font(name="Calibri", bold=True, size=11)
        r += 1
    autofit(ws, 4); ws.column_dimensions["D"].width = 70

    # Interface Changes
    ws = sheet("Interface Changes", ["Hostname", "Port", "Change", "Field: Old -> New"])
    r = 2
    for host in sorted(set(oi) | set(ni)):
        op, npp = oi.get(host, {}), ni.get(host, {})
        for port in sorted(set(op) | set(npp)):
            o, n = op.get(port), npp.get(port)
            if o is None and n is None:
                continue
            if o is None:
                change, deltas = "Added port", []
            elif n is None:
                change, deltas = "Removed port", []
            else:
                change = "Modified"
                deltas = [f"{f}: {o.get(f, '') or NONE} -> {n.get(f, '') or NONE}"
                          for f in _DIFF_FIELDS if (o.get(f, "") or "") != (n.get(f, "") or "")]
                if not deltas:
                    continue
            for c, v in enumerate([host, port, change, " | ".join(deltas)], 1):
                cell = ws.cell(row=r, column=c, value=v); cell.font = DF; cell.alignment = AL
            r += 1
    autofit(ws, 4); ws.column_dimensions["D"].width = 70

    # Endpoint (MAC) Changes
    ws = sheet("Endpoint Changes", ["Hostname", "Port", "Change", "MAC"])
    r = 2
    for host in sorted(set(oi) | set(ni)):
        op, npp = oi.get(host, {}), ni.get(host, {})
        for port in sorted(set(op) | set(npp)):
            om = _macset((op.get(port) or {}).get("end_host_mac", ""))
            nm = _macset((npp.get(port) or {}).get("end_host_mac", ""))
            for mac in sorted(nm - om):
                for c, v in enumerate([host, port, "MAC appeared", mac], 1):
                    cell = ws.cell(row=r, column=c, value=v); cell.font = DF; cell.alignment = AL
                r += 1
            for mac in sorted(om - nm):
                for c, v in enumerate([host, port, "MAC gone", mac], 1):
                    cell = ws.cell(row=r, column=c, value=v); cell.font = DF; cell.alignment = AL
                r += 1
    autofit(ws, 4)

    # SVI / Gateway Changes
    ws = sheet("SVI Changes", ["Hostname", "SVI", "Change", "Detail"])
    r = 2
    for host in sorted(set(oi) | set(ni)):
        op, npp = oi.get(host, {}), ni.get(host, {})
        svis = sorted({p for p in (set(op) | set(npp)) if re.match(r"^Vlan\d+$", p, re.I)})
        for p in svis:
            o, n = op.get(p), npp.get(p)
            if o is None and n is not None:
                ch = "SVI added"
                detail = f"IP {n.get('svi_ip', '') or NONE}, FHRP {n.get('hsrp_behavior', '') or NONE}"
            elif n is None and o is not None:
                ch = "SVI removed"
                detail = f"was IP {o.get('svi_ip', '') or NONE}"
            else:
                diffs = [f"{f}: {o.get(f, '') or NONE} -> {n.get(f, '') or NONE}"
                         for f in ("svi_ip", "hsrp_behavior", "subnet_primary_route")
                         if (o.get(f, "") or "") != (n.get(f, "") or "")]
                if not diffs:
                    continue
                ch, detail = "SVI changed", " | ".join(diffs)
            for c, v in enumerate([host, p, ch, detail], 1):
                cell = ws.cell(row=r, column=c, value=v); cell.font = DF; cell.alignment = AL
            r += 1
    autofit(ws, 4); ws.column_dimensions["D"].width = 60

    # Health Shifts (NEW-V3.23.106) — per-switch health-band change, regressions first
    ws = sheet("Health Shifts", ["Switch", "Direction", "Old band", "New band", "Old score", "New score"])
    r = 2
    for direction, rows in (("REGRESSED", delta["health"]["regressed"]),
                            ("improved", delta["health"]["improved"])):
        for d in rows:
            vals = [d["switch"], direction, d["old_band"], d["new_band"], d["old_score"], d["new_score"]]
            for c, v in enumerate(vals, 1):
                cell = ws.cell(row=r, column=c, value=v); cell.font = DF; cell.alignment = AL
            if direction == "REGRESSED":
                ws.cell(row=r, column=2).fill = PatternFill("solid", fgColor="FFC7CE")
            r += 1
    if r == 2:
        ws.cell(row=2, column=1, value="No health-band changes between the two snapshots.").font = DF
    autofit(ws, 6)

    # Findings Delta (NEW-V3.23.106) — consolidated punch-list items opened vs resolved by the cutover
    ws = sheet("Findings Delta", ["State", "Severity", "Category", "Devices", "Finding"])
    r = 2
    for state, items in (("OPENED", delta["findings"]["opened"]),
                         ("resolved", delta["findings"]["resolved"])):
        for f in items:
            vals = [state, f.get("severity", ""), f.get("category", ""),
                    ", ".join(str(d) for d in (f.get("devices") or []))[:60], f.get("title", "")]
            for c, v in enumerate(vals, 1):
                cell = ws.cell(row=r, column=c, value=v); cell.font = DF; cell.alignment = AL
            ws.cell(row=r, column=1).fill = PatternFill(
                "solid", fgColor="FFC7CE" if state == "OPENED" else "C6EFCE")
            r += 1
    if r == 2:
        ws.cell(row=2, column=1, value="No punch-list findings opened or resolved.").font = DF
    autofit(ws, 5); ws.column_dimensions["E"].width = 70

    wb.save(out_path)


# -----------------------------------------------------------------------------
# Migration CAMPAIGN trend (NEW-V3.23.145). Where compute_snapshot_delta diffs a PAIR (pre/post a single
# cutover), the campaign tracker ingests a SERIES of collections taken across the whole migration and shows
# the trajectory: is the network actually getting healthier wave by wave? It extracts the headline metrics
# per collection (avg health, band mix, punch-list size + Critical/High count, NOT-READY groups, past-EoS),
# computes the first->last trajectory per metric + an overall IMPROVING/MIXED/REGRESSING verdict, and reuses
# compute_snapshot_delta for the per-step findings burndown (opened vs resolved). Pure read of N snapshot
# dicts; tolerant of older snapshots that lack a metric (it is simply omitted from the trajectory).
# -----------------------------------------------------------------------------
def _trend_point(snap: dict) -> dict:
    """Headline metrics for one snapshot in the campaign timeline."""
    hs = snap.get("health_scores") or []
    scores = [r.get("score") for r in hs if isinstance(r.get("score"), (int, float))]
    bands: Dict[str, int] = {}
    for r in hs:
        bands[r.get("band", "")] = bands.get(r.get("band", ""), 0) + 1
    pl = snap.get("punchlist") or []
    readiness = {"READY": 0, "CAUTION": 0, "NOT READY": 0}
    for r in (snap.get("migration_readiness") or []):
        if r.get("readiness") in readiness:
            readiness[r["readiness"]] += 1
    lr = (snap.get("lifecycle_risk") or {}).get("summary") or {}
    _eb = snap.get("executive_brief") or {}
    _scale = _eb.get("scale") or {}
    _posture = _eb.get("posture") or {}
    avg = _posture.get("avg_health")
    if avg is None and scores:
        avg = round(sum(scores) / len(scores), 1)
    ts = snap.get("generated_at") or ""
    return {
        "date": ts[:10], "generated_at": ts, "version": snap.get("script_version", ""),
        # SSOT: prefer the engine's canonical scale / posture; the local len()/band-tally is a fallback only.
        "n_switches": _scale.get("n_devices") if _scale.get("n_devices") is not None else len(snap.get("devices") or {}),
        "avg_health": avg if avg is not None else "",
        "n_critical": _posture.get("n_critical") if _posture.get("n_critical") is not None else bands.get("Critical", 0),
        "n_punchlist": len(pl),
        "n_crit_high": sum(1 for f in pl if f.get("severity") in ("Critical", "High")),
        "n_not_ready": readiness["NOT READY"],
        # "Past end-of-support" = Past-LDoS (no TAC / no fixes) — the migration-critical count the
        # brief/deck/explorer/workbook all headline. NOT Past-EoS (end-of-SALE, still supported): reading
        # n_past_eos here showed 0 while 152 boxes were past support (the EoS/LDoS silent-drop class).
        "past_ldos": lr.get("n_past_ldos", "") if lr else "",
    }


# (metric label, timeline key, lower-is-better) for the trajectory + the timeline columns.
_TREND_METRICS = (("Avg health / 100", "avg_health", False),
                  ("Critical-band switches", "n_critical", True),
                  ("Punch-list items", "n_punchlist", True),
                  ("Critical/High findings", "n_crit_high", True),
                  ("NOT READY groups", "n_not_ready", True),
                  ("Past end-of-support", "past_ldos", True))


def compute_campaign_trend(snapshots: List[dict]) -> dict:
    """Trajectory of a migration campaign across a SERIES of snapshots. Returns
    {timeline, steps, trajectory, verdict, verdict_note}; degrades gracefully when a metric is absent."""
    snaps = list(snapshots or [])
    timeline = [dict(_trend_point(s), collection=f"C{i + 1}") for i, s in enumerate(snaps)]

    steps: List[dict] = []
    for i in range(len(snaps) - 1):
        d = compute_snapshot_delta(snaps[i], snaps[i + 1])
        steps.append({
            "from": timeline[i]["collection"], "to": timeline[i + 1]["collection"],
            "from_date": timeline[i]["date"], "to_date": timeline[i + 1]["date"],
            "opened": d["findings"]["n_opened"], "opened_high": d["findings"]["n_opened_high"],
            "resolved": d["findings"]["n_resolved"], "net": d["findings"]["n_opened"] - d["findings"]["n_resolved"],
            "regressed": d["health"]["n_regressed"], "improved": d["health"]["n_improved"],
            "verdict": d["verdict"],
        })

    trajectory: List[dict] = []
    verdict, note = "INSUFFICIENT", "Need at least two collections to show a trend."
    if len(timeline) >= 2:
        first, last = timeline[0], timeline[-1]
        for metric, key, good_down in _TREND_METRICS:
            a, b = first.get(key), last.get(key)
            if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
                continue
            delta = b - a
            direction = "flat" if delta == 0 else (
                "improving" if ((delta < 0) if good_down else (delta > 0)) else "worsening")
            trajectory.append({"metric": metric, "first": a, "last": b,
                               "delta": round(delta, 1), "direction": direction})
        better = sum(1 for r in trajectory if r["direction"] == "improving")
        worse = sum(1 for r in trajectory if r["direction"] == "worsening")
        if trajectory:                                    # comparable metrics exist -> a real verdict
            if better == 0 and worse == 0:
                verdict = "FLAT"
            elif better > worse:
                verdict = "IMPROVING"
            elif worse > better:
                verdict = "REGRESSING"
            else:
                verdict = "MIXED"
        hr = next((r for r in trajectory if r["metric"].startswith("Avg health")), None)
        cr = next((r for r in trajectory if r["metric"].startswith("Critical/High")), None)
        note = (f"Across {len(timeline)} collections: {better} metric(s) improving, {worse} worsening. "
                + (f"Avg health {hr['first']}→{hr['last']}. " if hr else "")
                + (f"Critical/High findings {cr['first']}→{cr['last']}." if cr else "")).strip()

    return {"timeline": timeline, "steps": steps, "trajectory": trajectory,
            "verdict": verdict, "verdict_note": note}


def write_campaign_workbook(snapshots: List[dict], out_path: str) -> None:
    """Write a migration-campaign trend workbook (Campaign Summary verdict + per-metric trajectory /
    Timeline w/ a trajectory line chart / Burndown of findings opened-vs-resolved per step) from a SERIES
    of snapshot_state() dicts."""
    from openpyxl import Workbook
    HF = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
    FILL = PatternFill("solid", fgColor="1F497D")
    AL = Alignment(horizontal="left", vertical="top", wrap_text=True)
    CEN = Alignment(horizontal="center", vertical="center", wrap_text=True)
    DF = Font(name="Calibri", size=10)

    trend = compute_campaign_trend(snapshots)
    wb = Workbook(); wb.remove(wb.active)
    from cisco_toolkit.excel import harden_workbook
    harden_workbook(wb)   # sanitize control chars in device-derived text -> no IllegalCharacterError abort

    def sheet(title, cols):
        ws = wb.create_sheet(title)
        for c, h in enumerate(cols, 1):
            cell = ws.cell(row=1, column=c, value=h); cell.font = HF; cell.fill = FILL; cell.alignment = CEN
        ws.freeze_panes = "A2"
        return ws

    def autofit(ws, ncols):
        for col in range(1, ncols + 1):
            mx = len(str(ws.cell(row=1, column=col).value or ""))
            for row in range(2, ws.max_row + 1):
                v = ws.cell(row=row, column=col).value
                if v is not None:
                    mx = max(mx, len(str(v)))
            ws.column_dimensions[get_column_letter(col)].width = min(max(mx + 2, 12), 60)

    _DIR_FILL = {"improving": "C6EFCE", "worsening": "FFC7CE", "flat": "FFEB9C"}
    _VERDICT_FILL = {"IMPROVING": "C6EFCE", "MIXED": "FFEB9C", "FLAT": "DDEBF7",
                     "REGRESSING": "FFC7CE", "INSUFFICIENT": "EFEFEF"}

    # ---- Campaign Summary (leads with the trajectory verdict) ----
    ws = sheet("Campaign Summary", ["Metric", "First", "Last", "Delta", "Trajectory"])
    vc = ws.cell(row=2, column=1, value="CAMPAIGN VERDICT"); vc.font = Font(name="Calibri", bold=True, size=11)
    vv = ws.cell(row=2, column=2, value=trend["verdict"])
    vv.font = Font(name="Calibri", bold=True, size=11)
    vv.fill = PatternFill("solid", fgColor=_VERDICT_FILL.get(trend["verdict"], "FFFFFF"))
    ws.cell(row=2, column=3, value=trend["verdict_note"]).alignment = AL
    ws.merge_cells(start_row=2, start_column=3, end_row=2, end_column=5)
    r = 4
    for t in trend["trajectory"]:
        for c, v in enumerate([t["metric"], t["first"], t["last"], t["delta"], t["direction"]], 1):
            cell = ws.cell(row=r, column=c, value=v); cell.font = DF; cell.alignment = AL
        ws.cell(row=r, column=5).fill = PatternFill("solid", fgColor=_DIR_FILL.get(t["direction"], "FFFFFF"))
        r += 1
    if not trend["trajectory"]:
        ws.cell(row=4, column=1, value="Not enough comparable metrics across the snapshots.").font = DF
    autofit(ws, 5); ws.column_dimensions["A"].width = 26

    # ---- Timeline (one row per collection) + a trajectory line chart ----
    cols = ["Collection", "Date", "Version", "Switches", "Avg Health", "Critical",
            "Punch-list", "Crit/High", "NOT READY", "Past end-of-support"]
    ws = sheet("Timeline", cols)
    keys = ["collection", "date", "version", "n_switches", "avg_health", "n_critical",
            "n_punchlist", "n_crit_high", "n_not_ready", "past_ldos"]
    for i, pt in enumerate(trend["timeline"], start=2):
        for c, k in enumerate(keys, 1):
            cell = ws.cell(row=i, column=c, value=pt.get(k, "")); cell.font = DF
            cell.alignment = CEN if c >= 4 else AL
    autofit(ws, len(cols))
    if len(trend["timeline"]) >= 2:
        try:
            from openpyxl.chart import LineChart, Reference
            n = len(trend["timeline"])
            chart = LineChart(); chart.title = "Migration trajectory"; chart.style = 12
            chart.y_axis.title = "count / score"; chart.x_axis.title = "collection"; chart.height = 8; chart.width = 16
            for col in (5, 8, 7):   # Avg Health, Crit/High, Punch-list
                chart.add_data(Reference(ws, min_col=col, min_row=1, max_row=1 + n), titles_from_data=True)
            chart.set_categories(Reference(ws, min_col=1, min_row=2, max_row=1 + n))
            ws.add_chart(chart, get_column_letter(len(cols) + 2) + "2")
        except Exception as e:
            logger.warning(f"  Campaign trend chart skipped: {e}")

    # ---- Burndown (findings opened vs resolved per consecutive step) ----
    ws = sheet("Burndown", ["Step", "Opened", "Opened High/Crit", "Resolved", "Net", "Health regressed",
                            "Health improved", "Step verdict"])
    for i, st in enumerate(trend["steps"], start=2):
        vals = [f"{st['from']} → {st['to']}", st["opened"], st["opened_high"], st["resolved"],
                st["net"], st["regressed"], st["improved"], st["verdict"]]
        for c, v in enumerate(vals, 1):
            cell = ws.cell(row=i, column=c, value=v); cell.font = DF
            cell.alignment = CEN if 2 <= c <= 7 else AL
        nf = ws.cell(row=i, column=5)
        nf.fill = PatternFill("solid", fgColor="FFC7CE" if (st["net"] or 0) > 0 else "C6EFCE")
    if not trend["steps"]:
        ws.cell(row=2, column=1, value="Need at least two snapshots for a burndown.").font = DF
    autofit(ws, 8)

    wb.save(out_path)
    logger.info(f"[OK] Campaign trend: {trend['verdict']} across {len(trend['timeline'])} collections")


def snapshot_state(all_interfaces: Dict[str, Dict[str, InterfaceData]],
                   all_device_physical: List[DevicePhysical]) -> dict:
    import dataclasses
    return {
        "schema": "collect_parse_snapshot/1",
        "script_version": f"V{__version__}",   # NEW-V3.23.8 (M2): was hard-coded "V3.23.0"
        "generated_at": datetime.now().isoformat(),
        "devices": {dp.hostname: dataclasses.asdict(dp) for dp in all_device_physical},
        "interfaces": {host: {port: dataclasses.asdict(d) for port, d in ifaces.items()}
                       for host, ifaces in all_interfaces.items()},
    }


# -----------------------------------------------------------------------------
# NEW-V3.23.90: shrink the snapshot copy EMBEDDED in the single-file explorer.
# The on-disk snapshot.json stays full-fidelity (it is the data contract and the
# `--compare` input); this only trims the in-page payload, which on a real fleet
# (the 254-device [HISTORY-REDACTED] scan embedded a 52 MB blob) is dominated by two things the
# explorer never renders verbatim:
#   * interfaces  - hundreds of ports/device, ~50 fields each, most empty strings.
#     The explorer reads every interface field defensively (`d.x||""`, `d.x&&...`,
#     `(d.x||"").trim()`), so an ABSENT key is indistinguishable from an empty one
#     -> dropping empty/placeholder field VALUES is display-neutral. The port entry
#     itself is always kept so buildModel's `Object.keys(ifaces[host])` is unchanged.
#   * physical_health - tens of thousands of Info/OK rows; the sole consumer
#     (deviceIntelSection) filters severity to non-Info/non-OK, so they are dead weight.
# Everything else (already aggregated per-host in analyze, V3.23.90) passes through.
# -----------------------------------------------------------------------------
_EMBED_DROP_VALUES: tuple = ("", None, [], {}, "--")


def _slim_for_embed(snap_dict: dict) -> dict:
    """Return a display-neutral, size-reduced copy of the snapshot for embedding in the
    explorer HTML. Pure (input not mutated); see the block comment above for why each
    transform is safe. Defensive: tolerates missing/oddly-typed sections."""
    out = dict(snap_dict)
    intf = snap_dict.get("interfaces")
    if isinstance(intf, dict):
        out["interfaces"] = {
            host: {port: {k: v for k, v in (rec or {}).items() if v not in _EMBED_DROP_VALUES}
                   for port, rec in (ports or {}).items()}
            for host, ports in intf.items()}
    ph = snap_dict.get("physical_health")
    if isinstance(ph, list):
        out["physical_health"] = [
            r for r in ph
            if not (isinstance(r, dict) and r.get("severity") in ("Info", "OK", None))]
    return out


# -----------------------------------------------------------------------------
# NEW-V3.17: HTML consolidation. Bake the live snapshot into a copy of the
# read-only Blast-Radius Explorer template so one run yields both the workbook
# and a ready-to-open, air-gapped topology explorer (no second tool, no manual
# snapshot load). Pure stdlib (os + json); no new imports.
# -----------------------------------------------------------------------------
def write_html_explorer(output_path: str, snap_dict: dict, label: str) -> None:
    """
    Emit a self-contained Blast-Radius Explorer with the live topology embedded.

    Reads 'blast_radius_explorer.html' from inside the package (with a fallback to the legacy repo-root
    location), replaces its demo bootstrap with the embedded snapshot, and writes the patched
    single-file HTML to output_path.

    The template boots on a demo via the LAST statement in its <script>:
        load(demoSnapshot(),"DEMO TOPOLOGY",false);
    That exact text also appears earlier as the demo button's onclick handler, so a
    naive str.replace() (which replaces every occurrence) would corrupt the button -
    it would inject a `const` declaration into an arrow-function body and break all
    JS on the page. We therefore replace ONLY the final occurrence (the real
    bootstrap) via rpartition(), leaving the demo button intact as a one-click way
    back to the sample topology.

    Safety / robustness:
      * Missing template -> warn and skip (never crash a run whose workbook already saved).
      * Bootstrap line absent (template changed) -> warn and skip.
      * Snapshot is minified (separators=(',',':')) to keep the embedded payload small.
      * Any literal '</' inside the data is escaped to '<\\/' so the JSON can never
        break out of the <script> block (valid JSON escape; parses back to '</').
      * label is emitted via json.dumps() -> a properly quoted/escaped JS string literal.
    """
    # The explorer template ships INSIDE the package (cisco_toolkit/blast_radius_explorer.html), so it is
    # present in a built wheel and resolves the same whether the package is run from a checkout or a
    # pip install. Fall back to the legacy repo-root location for any older layout that still keeps it there.
    _here = os.path.dirname(os.path.abspath(__file__))
    template = os.path.join(_here, "blast_radius_explorer.html")
    if not os.path.isfile(template):
        template = os.path.join(os.path.dirname(_here), "blast_radius_explorer.html")  # legacy repo-root
    if not os.path.isfile(template):
        logger.warning(f"  HTML Explorer skipped: template not found at {template}")
        return

    with open(template, encoding="utf-8") as f:
        html = f.read()

    bootstrap = 'load(demoSnapshot(),"DEMO TOPOLOGY",false);'
    if bootstrap not in html:
        logger.warning("  HTML Explorer skipped: demo bootstrap line not found in template "
                       "(template may have changed).")
        return

    slim = _slim_for_embed(snap_dict)                  # NEW-V3.23.90: shrink the in-page payload only
    embedded = json.dumps(slim, separators=(",", ":"), ensure_ascii=False)
    embedded = embedded.replace("</", "<\\/")          # cannot break out of <script>
    replacement = (f"const EMBEDDED_SNAPSHOT={embedded};\n"
                   f"load(EMBEDDED_SNAPSHOT,{json.dumps(label)},true);")

    # Replace ONLY the last occurrence (the bootstrap), not the button's onclick.
    head, _sep, tail = html.rpartition(bootstrap)
    patched = head + replacement + tail

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(patched)
    logger.info(f"[Phase 22] HTML Explorer embedded payload: {len(embedded) / 1e6:.1f} MB")
    logger.info(f"[Phase 22] HTML Explorer written: {output_path}")


# -----------------------------------------------------------------------------
# Snapshot redaction (opt-in --redact): pseudonymize IPs / MACs / serial numbers
# so a single-file HTML/JSON deliverable can be shared without leaking the real
# addressing. Mappings are CONSISTENT (same input -> same output) and IPs keep
# their /24 grouping, so ARP (MAC->IP), dual-homing, and subnet/flow-trace
# relationships the explorer relies on survive. Hostnames are intentionally kept.
# -----------------------------------------------------------------------------
_REDACT_IP_RE = re.compile(r"\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b")
_REDACT_MAC_RE = re.compile(
    r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b|\b(?:[0-9A-Fa-f]{4}\.){2}[0-9A-Fa-f]{4}\b")
_REDACT_SERIAL_KEYS = {"serial_number", "chassis_serial",
                       "current_switch_serial", "neighbor_switch_serial",
                       # controller + inventory serials reach the snapshot under other key names: ACI
                       # fabric-node 'serial' (parse_aci_fabric_nodes -> snap['aci'].nodes) and the
                       # power-supply 'ps_serials' list (parse_show_inventory). Without these they leaked
                       # verbatim under --redact (a bare serial matches no inline secret form). 'ps_serials'
                       # is a LIST -- _walk recurses each string item with the same key, so each is redacted.
                       "serial", "ps_serials", "sn"}

# Credential deny-list: conservatively match KNOWN secret-bearing config/output forms
# (IOS / IOS-XE / NX-OS, case-insensitive) and replace ONLY the secret token with a
# placeholder, keeping the surrounding keywords as context. Each pattern captures the
# prefix in group 1 and the secret in group 2; the secret is swapped for "<redacted>".
# Idempotent: re-running over an already-scrubbed string re-captures "<redacted>" and
# substitutes it for itself. We are deliberately narrow (no blanket token redaction) so
# non-secret structured fields are never corrupted.
_REDACT_PLACEHOLDER = "<redacted>"
_REDACT_SECRET_RES = [re.compile(p, re.I) for p in (
    # SNMP community strings: 'snmp-server community <VALUE>' and the bare
    # 'community <VALUE>' form (host/group/trap lines).
    r"(snmp-server\s+community\s+)(\S+)",
    r"(\bcommunity\s+)(\S+)",
    # Cisco password/secret forms: type-7/type-5 and cleartext, 'enable secret',
    # and 'username <u> password|secret <VALUE>'. The username token is preserved.
    r"(\bpassword\s+(?:\d+\s+)?)(\S+)",
    r"(\bsecret\s+(?:\d+\s+)?)(\S+)",
    r"((?:username|user)\s+\S+\s+(?:password|secret)\s+(?:\d+\s+)?)(\S+)",
    # Shared keys. Specific forms FIRST so the generic bare 'key' below cannot consume
    # their qualifier (e.g. 'pre-shared-key local <V>' must not let 'key local' match).
    # TACACS+/RADIUS server keys, 'key-string <VALUE>' (SNMPv3 / EIGRP / OSPF keychains),
    # IKE pre-shared keys, and 'crypto isakmp key <VALUE> address ...'.
    r"((?:tacacs-server|radius-server)\s+(?:host\s+\S+\s+)?key\s+(?:\d+\s+)?)(\S+)",
    r"(key-string\s+(?:\d+\s+)?)(\S+)",
    r"(pre-shared-key\s+(?:(?:local|remote)\s+)?(?:\d+\s+)?)(\S+)",
    r"(crypto\s+isakmp\s+key\s+(?:\d+\s+)?)(\S+)",
    # Generic 'key 7 <hex>' / 'key <cleartext>' (keychain key, OSPF/EIGRP authentication). The optional
    # inner group absorbs a hash-algorithm label so 'authentication-key|message-digest-key N md5|sha|
    # hmac-sha <DIGEST>' (NTP/OSPF/EIGRP) redacts the DIGEST after it, not the 'md5'/'sha' token -- the
    # latter left the real, offline-crackable digest exposed. Anchored on 'key', so a bare IKE 'hash md5'
    # algorithm choice (no key-id + secret) is never corrupted.
    r"(\bkey\s+(?:\d+\s+)?(?:(?:md5|sha\S*|hmac-\S+|cmac-\S+)\s+(?:\d+\s+)?)?)(\S+)",
    # Non-Cisco vendor config forms: FortiGate 'set passwd|psksecret|password [ENC] <VALUE>' and Junos
    # 'authentication-key|secret "<VALUE>"' -- 'passwd'/'psksecret' are not the whole words 'password'/'secret',
    # so the Cisco patterns above miss them.
    r"(set\s+(?:passwd|psksecret|password|private-key)\s+(?:ENC\s+)?)(\S+)",
)]
# JSON-VALUE secrets: the controller-REST channels (ACI / ISE / FMC / vManage) and IaC exports store a secret as
# a VALUE under a key, with no inline keyword for the deny-list regexes above to anchor on. So redact the WHOLE
# value when its key is a known secret-bearing name. Keys are normalized (lowercased, '_'/'-' stripped) before
# the lookup. 'key' is deliberately EXCLUDED -- it is a generic structural field name across the snapshot (causal
# flows, design decisions) and the inline 'key <val>' CLI form is already covered above.
_REDACT_SECRET_KEYS = {
    "password", "passwd", "pwd", "passphrase", "secret", "psksecret", "presharedkey", "psk",
    "token", "authtoken", "accesstoken", "apikey", "apisecret", "community", "snmpcommunity",
    "credential", "credentials", "privatekey", "sharedsecret", "clientsecret",
}   # 'pass' deliberately omitted -- it is a pass/fail COUNT key in security summaries, not a secret


def _norm_key(k) -> str:
    return re.sub(r"[_-]", "", str(k or "").lower())


def _scrub_secrets(s: str) -> str:
    """Replace known credential / community / key material in a config-or-output string
    with a placeholder, preserving surrounding context. Conservative (deny-list of
    compiled regexes, secret-token capture only) and idempotent."""
    for rx in _REDACT_SECRET_RES:
        s = rx.sub(r"\g<1>" + _REDACT_PLACEHOLDER, s)
    return s


def redact_snapshot(snap: dict) -> dict:
    """Return a copy of the snapshot with IPs, MACs, and serial numbers consistently
    pseudonymized for sharing the single-file deliverable. Same input maps to the same
    output and IPs keep their /24 grouping, so topology / ARP / subnet relationships
    survive; hostnames are kept. Pure (stdlib only); the input is not mutated."""
    ip_map: Dict[str, str] = {}
    mac_map: Dict[str, str] = {}
    serial_map: Dict[str, str] = {}

    def _ip(m):
        net = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
        if net not in ip_map:
            i = len(ip_map); ip_map[net] = f"10.{i // 256}.{i % 256}"   # remap /24, keep host octet
        return f"{ip_map[net]}.{m.group(4)}"

    def _mac(m):
        key = re.sub(r"[^0-9a-f]", "", m.group(0).lower())
        if key not in mac_map:
            i = len(mac_map) + 1
            mac_map[key] = "02:%02x:%02x:%02x:%02x:%02x" % (
                (i >> 32) & 255, (i >> 24) & 255, (i >> 16) & 255, (i >> 8) & 255, i & 255)
        return mac_map[key]

    def _serial(v):
        if not v:
            return v
        if v not in serial_map:
            serial_map[v] = f"SN{len(serial_map) + 1:04d}"
        return serial_map[v]

    def _scrub(s):
        # Strip credentials / community / key material first so a secret token is
        # replaced wholesale, THEN pseudonymize any remaining IPs / MACs in context.
        return _REDACT_MAC_RE.sub(_mac, _REDACT_IP_RE.sub(_ip, _scrub_secrets(s)))

    def _walk(o, key=None):
        if isinstance(o, dict):
            return {k: _walk(v, k) for k, v in o.items()}
        if isinstance(o, list):
            return [_walk(v, key) for v in o]
        if isinstance(o, str):
            if key in _REDACT_SERIAL_KEYS: return _serial(o)
            if key == "wild": return o   # ACL wildcard mask is not an address; preserve so post-redact L4 eval stays correct
            if o and _norm_key(key) in _REDACT_SECRET_KEYS:
                return _REDACT_PLACEHOLDER   # a secret stored as a JSON value under a credential-named key
            return _scrub(o)
        return o

    return _walk(snap)
