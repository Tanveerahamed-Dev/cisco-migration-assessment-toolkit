"""Render a **Network Ready-For-Use (NRFU) / Acceptance Test Plan (ATP)** as a .docx deliverable.

This is an AssessHub synthesis (no engine writer), written in the web layer like ``cutover_docx`` and
matching the engine writers' python-docx conventions (Calibri body, navy headings, "Light Grid Accent
1" tables) so it reads as one family with the rest of the deliverable set.

It follows the standard Cisco NRFU/ATP shape: document-control + sign-off front matter, a two-part /
three-phase test structure, and a per-test row carrying an ID, the scope, the command to run, the
EXPECTED result, and a blank Result cell for the tester. The three phases map to Cisco's NRFU model:

  * **Phase I — Device readiness** (per-device standalone): inventory / software / lifecycle, built
    from ``lifecycle_risk.per_device`` and ``collection_completeness``.
  * **Phase II — Logical config & connectivity**: the engine's own ``validation_plan`` checks (FHRP,
    gateway, reachability, routing, STP, link) — each a ready-to-run command with an 'expect' baseline.
  * **Phase III — Service & traffic verification** (end-to-end): the detected services and application
    domains from ``service_map`` / ``application_intelligence`` / multicast.

Signature mirrors the engine writers — ``write_nrfu_docx(output_path, snap_dict, label)`` — so it slots
into ``deliverables.generate`` exactly like the others.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from . import engine
from .docx_style import GREY as _GREY
from .docx_style import NAVY as _NAVY
from .docx_style import add_table, ink, kv, new_document


def write_nrfu_docx(output_path: str, snap_dict: Dict[str, Any], label: str) -> None:
    """Write the NRFU / Acceptance Test Plan to ``output_path`` as a .docx."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    doc = new_document()

    def table(headers: List[str], rows: List[List[Any]], widths: List[float] | None = None):
        return add_table(doc, headers, rows, widths)

    devices = snap_dict.get("devices") or {}
    per_device = [d for d in ((snap_dict.get("lifecycle_risk") or {}).get("per_device") or [])
                  if isinstance(d, dict)]
    coll = (snap_dict.get("collection_completeness") or {}).get("summary") or {}
    # SSOT: the fleet-scale header reads the canonical executive_brief.scale (the published single
    # source the explorer/deck/HLD read), with len(devices) only as a pre-brief fallback (C9 fix —
    # the web-layer NRFU writer was the last surface recomputing fleet scale from the raw array).
    scale = (snap_dict.get("executive_brief") or {}).get("scale") or {}
    val_items = [i for i in ((snap_dict.get("validation_plan") or {}).get("items") or []) if isinstance(i, dict)]
    services = [s for s in ((snap_dict.get("service_map") or {}).get("services") or []) if isinstance(s, dict)]
    domains = [d for d in ((snap_dict.get("application_intelligence") or {}).get("domains") or [])
               if isinstance(d, dict)]
    mcast = (snap_dict.get("multicast_intelligence") or {})
    # design-decision coverage + scope limits (N29/N30): trace the ATP back to the target-state design
    bp_decisions = [d for d in ((snap_dict.get("design_blueprint") or {}).get("decisions") or [])
                    if isinstance(d, dict)]
    nrfu_items = [i for i in ((snap_dict.get("design_nrfu") or {}).get("items") or []) if isinstance(i, dict)]
    swrisk = (snap_dict.get("software_risk") or {}).get("summary") or {}

    # ---- title page ----
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    tr = title.add_run("Network Ready-For-Use (NRFU)")
    tr.bold = True
    tr.font.size = Pt(26)
    tr.font.color.rgb = ink(_NAVY)
    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sr = sub.add_run(f"Acceptance Test Plan · {label}")
    sr.font.size = Pt(13)
    sr.font.color.rgb = ink(_GREY)
    stamp = doc.add_paragraph()
    stamp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    st = stamp.add_run("DRAFT — test cases derived from the assessment snapshot; review and time each "
                       "case against your change-control before execution.")
    st.italic = True
    st.font.color.rgb = ink(_GREY)

    # ---- document control + sign-off ----
    doc.add_heading("Document control", level=1)
    gen = snap_dict.get("generated_at") or datetime.now().strftime("%Y-%m-%d %H:%M")
    table(["Field", "Value"], [
        ["Document", "Network Ready-For-Use / Acceptance Test Plan"],
        ["Subject", label],
        ["Version", "0.1 (DRAFT)"],
        ["Generated", datetime.now().strftime("%Y-%m-%d %H:%M")],
        ["Snapshot captured", gen],
        ["Engine", engine.ENGINE_SCHEMA_VERSION],
        ["Devices in scope", scale.get("n_devices") or len(devices)],
    ], widths=[2.2, 4.3])
    doc.add_heading("Sign-off", level=2)
    table(["Role", "Name", "Signature", "Date"], [
        ["Test lead", "", "", ""],
        ["Network engineer", "", "", ""],
        ["Change manager", "", "", ""],
        ["Customer acceptance", "", "", ""],
    ], widths=[1.8, 2.0, 1.7, 1.0])
    # Shared family cross-reference (imported here, after the engine sys.path bootstrap).
    from cisco_toolkit.docmeta import add_related_documents
    add_related_documents(
        doc, exclude=("nrfu",),
        audience="the test lead and network engineers executing the acceptance tests, and the "
                 "customer signatories accepting the network for production.")

    # ---- 1. introduction & scope ----
    doc.add_heading("1. Introduction, scope & test approach", level=1)
    doc.add_paragraph(
        "This Network Ready-For-Use (NRFU) plan — also an Acceptance Test Plan (ATP) — verifies that the "
        "migrated fleet is ready for production. It is organised in two parts (per-device standalone "
        "checks and end-to-end service checks) across the three standard NRFU phases. Each test states "
        "the command to run and the EXPECTED result captured from the assessment baseline; a deviation "
        "is a regression to investigate before acceptance.")
    p = doc.add_paragraph()
    kv(p, "Entry criteria:", "the wave/site cutover is complete, target configuration is applied, and "
                             "management plane is reachable on every in-scope device.")
    p = doc.add_paragraph()
    kv(p, "Exit criteria:", "every High-severity test passes, zero Critical tests fail, and any "
                            "deviation is logged and dispositioned (accepted or remediated) before sign-off.")

    # ---- 2. test summary ----
    val_by_cat: Dict[str, int] = {}
    for it in val_items:
        c = str(it.get("category", "") or "—")
        val_by_cat[c] = val_by_cat.get(c, 0) + 1
    n_p1, n_p2 = len(per_device), len(val_items)
    n_p3 = len({(s.get("service"), s.get("category")) for s in services}) + len(domains) + (1 if mcast else 0)
    doc.add_heading("2. Test summary", level=1)
    table(["Phase", "Coverage", "Tests"], [
        ["Phase I — Device readiness", "Per-device inventory, software & lifecycle", n_p1],
        ["Phase II — Logical config & connectivity", "FHRP / gateway / reachability / routing / STP / link", n_p2],
        ["Phase III — Service & traffic", "Detected services, application domains, multicast/timing", n_p3],
        ["Total", "", n_p1 + n_p2 + n_p3],
    ], widths=[3.0, 2.7, 0.8])
    if val_by_cat:
        doc.add_paragraph("Phase II tests by category: "
                          + " · ".join(f"{k} {v}" for k, v in sorted(val_by_cat.items(), key=lambda kv: -kv[1])))

    # ---- 2.1 design-decision coverage & scope limits (N30 traceability + N29 coverage-honesty) ----
    rec = [d for d in bp_decisions if d.get("status") == "recommended"]
    needs = [d for d in bp_decisions if d.get("status") == "needs-requirement"]
    nc = coll.get("not_collected") or 0
    n_na = swrisk.get("n_config_not_assessable") or 0
    limits = []
    if nc:
        limits.append(f"{nc} device(s) were not collected at assessment — their post-cutover state is NOT "
                      "validated here; re-collect and run Phase I against them before sign-off.")
    if n_na:
        limits.append(f"{n_na} device(s) had configuration that could not be assessed for software-advisory "
                      "exposure — NOT validated here.")
    if needs:
        limits.append(f"{len(needs)} target-state design area(s) still need a requirement before they can be "
                      "designed and acceptance-tested — see the design blueprint's open questions.")
    if rec or needs or limits:
        doc.add_heading("2.1 Design-decision coverage & scope limits", level=2)
        doc.add_paragraph(
            "Traceability back to the assessment's target-state design: each RECOMMENDED design decision is "
            "covered by an acceptance test in the phase shown; a decision that still needs a requirement is "
            "not yet testable and is an explicit coverage boundary, not a silent gap.")
        if rec or needs:
            phase_by = {i.get("decision_id"): i.get("phase", "") for i in nrfu_items}
            trace = [(d.get("title", d.get("id", "")), d.get("priority", ""),
                      "Tested — " + (phase_by.get(d.get("id")) or "post-cutover-functional")) for d in rec]
            trace += [(d.get("title", d.get("id", "")), d.get("priority", ""),
                       "Not testable until the requirement is supplied") for d in needs]
            table(["Target-state design decision", "Priority", "NRFU coverage"], trace[:40],
                  widths=[3.4, 0.9, 2.2])
            if len(trace) > 40:
                doc.add_paragraph(f"… and {len(trace) - 40} more decision(s); full set in the design blueprint.")
        if limits:
            doc.add_paragraph("Scope limits — NOT validated in this NRFU:")
            for lm in limits:
                doc.add_paragraph(lm, style="List Bullet")

    # ---- 3. Phase I — device readiness ----
    doc.add_heading("3. Phase I — Device readiness (per-device standalone)", level=1)
    if coll:
        doc.add_paragraph(
            f"Collection completeness at assessment: {coll.get('complete', 0)} of "
            f"{coll.get('inventory', len(devices))} device(s) fully collected, "
            f"{coll.get('partial', 0)} partial, {coll.get('not_collected', 0)} not collected. "
            "Re-run the inventory check below on every device post-cutover.")
    rows1: List[List[Any]] = []
    for n, d in enumerate(per_device, start=1):
        host = d.get("host", "")
        model = d.get("model", "") or "—"
        ver = d.get("sw_version", "") or "—"
        band = d.get("band", "")
        note = "Past end-of-support — replacement, not just verification" if "Past" in str(band) else (band or "")
        rows1.append([f"NRFU-I-{n:03d}", host,
                      "Device reachable; model & software match the as-built baseline",
                      "show version | i Model number|Version|System image",
                      f"Model {model}; IOS {ver}", "", note])
    if rows1:
        table(["ID", "Device", "Check", "Command", "Expected", "Result", "Notes"], rows1,
              widths=[0.7, 0.8, 1.6, 1.7, 1.4, 0.5, 1.0])
    else:
        doc.add_paragraph("No per-device lifecycle data in this snapshot.")

    # ---- 4. Phase II — logical config & connectivity ----
    doc.add_heading("4. Phase II — Logical configuration & connectivity", level=1)
    doc.add_paragraph("These are the engine's own post-cutover validation checks. Run each and compare "
                      "to the Expected baseline captured pre-cutover.")
    rows2: List[List[Any]] = []
    for n, it in enumerate(val_items, start=1):
        rows2.append([f"NRFU-II-{n:03d}", it.get("device", ""), it.get("category", ""),
                      it.get("severity", ""), it.get("check", ""), it.get("command", ""),
                      it.get("expect", ""), ""])
    if rows2:
        table(["ID", "Device", "Category", "Sev", "Check", "Command", "Expected", "Result"], rows2,
              widths=[0.7, 0.7, 0.8, 0.5, 1.3, 1.2, 1.6, 0.5])
    else:
        doc.add_paragraph("No validation_plan in this snapshot.")

    # ---- 5. Phase III — service & traffic ----
    doc.add_heading("5. Phase III — Service & traffic verification (end-to-end)", level=1)
    rows3: List[List[Any]] = []
    seen: set = set()
    n3 = 0
    for s in services:
        key = (s.get("service"), s.get("category"), s.get("port"))
        if key in seen:
            continue
        seen.add(key)
        n3 += 1
        svc = s.get("service", "") or "service"
        port = s.get("port", "")
        proto = s.get("proto", "")
        rows3.append([f"NRFU-III-{n3:03d}", f"{svc} ({s.get('category', '') or '—'})",
                      f"{svc} reachable end-to-end on {proto}/{port}",
                      f"telnet <server> {port}  /  show ip access-list (verify {svc} permitted)",
                      f"{svc} session establishes; permitted by ACL", ""])
    for d in domains:
        n3 += 1
        dom = d.get("domain", "") or d.get("id", "")
        sw = d.get("switches") or []
        rows3.append([f"NRFU-III-{n3:03d}", f"App domain: {dom}",
                      "Intra-domain reachability after cutover",
                      "ping / traceroute between two endpoints in the domain",
                      f"Endpoints across the {len(sw)} switch(es) in this domain reach each other", ""])
    if mcast:
        n3 += 1
        rows3.append([f"NRFU-III-{n3:03d}", "Multicast / timing",
                      "Multicast forwarding & clock health (if in use)",
                      "show ip mroute / show ip pim neighbor / show ptp clock",
                      "PIM neighbors up; mroutes present; clock locked (if PTP/NTP in use)", ""])
    if rows3:
        table(["ID", "Scope", "Check", "Command", "Expected", "Result"], rows3,
              widths=[0.7, 1.5, 1.5, 1.6, 1.5, 0.5])
    else:
        doc.add_paragraph("No service-map / application-domain data in this snapshot.")

    # ---- 6. results & acceptance ----
    doc.add_heading("6. Results summary & acceptance", level=1)
    doc.add_paragraph("Record the outcome of each phase. The network is accepted for production only "
                      "when the exit criteria in §1 are met.")
    table(["Phase", "Total", "Pass", "Fail", "Deviations / notes"], [
        ["Phase I — Device readiness", n_p1, "", "", ""],
        ["Phase II — Logical config & connectivity", n_p2, "", "", ""],
        ["Phase III — Service & traffic", n_p3, "", "", ""],
        ["Overall", n_p1 + n_p2 + n_p3, "", "", ""],
    ], widths=[3.0, 0.7, 0.7, 0.7, 1.7])
    acc = doc.add_paragraph()
    kv(acc, "Acceptance:", "The undersigned confirm the exit criteria are met and accept the network "
                           "for production use. (See the Sign-off table on page 1.)")

    doc.save(output_path)
