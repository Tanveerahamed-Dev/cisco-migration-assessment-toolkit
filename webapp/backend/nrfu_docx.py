"""Render a **Network Ready-For-Use (NRFU) / Acceptance Test Plan (ATP)** as a .docx deliverable.

AssessHub renders the engine-owned ``nrfu_document_view`` without re-deriving its rows, coverage or
counts, matching the engine writers' python-docx conventions (Calibri body, navy headings, "Light Grid Accent
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

_AMBER = (0x9A, 0x67, 0x00)
_RED = (0xCF, 0x22, 0x2E)

# Document-control metadata tolerates malformed stored containers. The engine export owner
# handles row construction and all plan coverage/count computations.


def _as_dict(v: Any) -> Dict[str, Any]:
    """Coerce a snapshot section/sub-section to a dict. `... or {}` only guards FALSY values; a truthy
    NON-dict (an int/str/list in a malformed or hostile upload) survives it and raises on the very next
    `.get`. This writer is reached by a plain `GET /api/snapshots/{id}/deliverable/nrfu` over a snapshot
    that the upload path stores verbatim, so that raise escapes as an HTTP 500 on every later read -- a
    STORED denial of service. Returning {} degrades gracefully; for a well-formed value (dict or None)
    the result is identical to the `or {}` it replaces."""
    return v if isinstance(v, dict) else {}


def write_nrfu_docx(
        output_path: str,
        snap_dict: Dict[str, Any],
        label: str,
        *,
        protocol_assurance_bundle=None) -> None:
    """Write the NRFU / Acceptance Test Plan to ``output_path`` as a .docx."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    from cisco_toolkit.nrfu_export import nrfu_document_view
    from cisco_toolkit.textutils import xml_safe, xml_safe_deep

    # Deep-sanitize ALL device-derived text up front, exactly like the engine writers (design/crd/
    # archreview/engagement). `add_table` sanitizes every cell, but this writer also emits device text on
    # DIRECT paragraph paths that bypass the table helper (the §2 "Phase II tests by category" join reads
    # `validation_plan` categories straight from the snapshot), and one U+FFFE/U+FFFF/lone surrogate/C0
    # control char there still aborts `doc.save()` with "All strings must be XML compatible" — a 500 that
    # repeats on every later read of a snapshot the upload path stores verbatim (stored DoS, see docx_style).
    snap_dict = xml_safe_deep(snap_dict if isinstance(snap_dict, dict) else {})
    label = xml_safe(label) if isinstance(label, str) else (str(label) if label is not None else "")

    doc = new_document()

    def table(headers: List[str], rows: List[List[Any]], widths: List[float] | None = None):
        return add_table(doc, headers, rows, widths)

    # Guard document-control metadata; the engine owns row construction and coverage/counts.
    devices = _as_dict(snap_dict.get("devices"))
    coll = _as_dict(_as_dict(snap_dict.get("collection_completeness")).get("summary"))
    # SSOT: the fleet-scale header reads the canonical executive_brief.scale (the published single
    # source the explorer/deck/HLD read), with len(devices) only as a pre-brief fallback (C9 fix —
    # the web-layer NRFU writer was the last surface recomputing fleet scale from the raw array).
    scale = _as_dict(_as_dict(snap_dict.get("executive_brief")).get("scale"))
    raw_validation_plan = snap_dict.get("validation_plan")
    current_baseline = engine.compute_current_baseline_gate(raw_validation_plan)
    view = nrfu_document_view(snap_dict)

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
        ["Devices in scope", scale.get("n_devices") if isinstance(scale.get("n_devices"), int) else len(devices)],
    ], widths=[2.2, 4.3])
    doc.add_heading("Sign-off", level=2)
    table(["Role", "Name", "Signature", "Date"], [
        ["Test lead", "", "", ""],
        ["Network engineer", "", "", ""],
        ["Change manager", "", "", ""],
        ["Customer acceptance", "", "", ""],
    ], widths=[1.8, 2.0, 1.7, 1.0])
    # Shared family cross-reference (imported here, after the engine sys.path bootstrap).
    from cisco_toolkit.docmeta import add_protocol_assurance_receipt, add_related_documents
    add_related_documents(
        doc, exclude=("nrfu",),
        audience="the test lead and network engineers executing the acceptance tests, and the "
                 "customer signatories accepting the network for production.")
    add_protocol_assurance_receipt(doc, protocol_assurance_bundle)

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
    doc.add_heading("2. Test summary", level=1)
    table(["Phase", "Coverage", "Tests"], view["summary_rows"], widths=[3.0, 2.7, 0.8])
    if view["categories"]:
        doc.add_paragraph("Phase II tests by category: " + view["categories"])

    # ---- 2.1 design-decision coverage & scope limits (N30 traceability + N29 coverage-honesty) ----
    if view["trace"] or view["limits"]:
        doc.add_heading("2.1 Design-decision coverage & scope limits", level=2)
        doc.add_paragraph(
            "Traceability back to the persisted target-state design: 'Tested' denotes a complete "
            "rendered acceptance case with description, setup, pass criteria and device scope. "
            "It is test coverage, not an executed result or approval; record execution results below.")
        if view["trace"]:
            table(["Target-state design decision", "Priority", "NRFU coverage"], view["trace"],
                  widths=[3.4, 0.9, 2.2])
            if view["omitted_trace"]:
                doc.add_paragraph(f"… and {view['omitted_trace']} more decision(s); full set in the design blueprint.")
        if view["limits"]:
            doc.add_paragraph("Scope limits — NOT validated in this NRFU:")
            for limit in view["limits"]:
                doc.add_paragraph(limit, style="List Bullet")

    # ---- 3. Phase I — device readiness ----
    doc.add_heading("3. Phase I — Device readiness (per-device standalone)", level=1)
    if coll:
        doc.add_paragraph(
            f"Collection completeness at assessment: {coll.get('complete', 0)} of "
            f"{coll.get('inventory', len(devices))} device(s) fully collected, "
            f"{coll.get('partial', 0)} partial, {coll.get('not_collected', 0)} not collected. "
            "Re-run the inventory check below on every device post-cutover.")
    rows1 = view["rows1"]
    if rows1:
        table(["ID", "Device", "Check", "Command", "Expected", "Result", "Notes"], rows1,
              widths=[0.7, 0.8, 1.6, 1.7, 1.4, 0.5, 1.0])
    else:
        doc.add_paragraph("No per-device lifecycle data in this snapshot.")

    # ---- 4. Phase II — logical config & connectivity ----
    doc.add_heading("4. Phase II — Logical configuration & connectivity", level=1)
    doc.add_paragraph(
        "These are the engine's own post-cutover validation checks. Compare the observed result with "
        "the captured baseline and its evidence authority. A degraded, review, or not-verified "
        "pre-cutover observation is an acceptance blocker; matching that observation is not a PASS."
    )
    gate_verdict = str(current_baseline.get("verdict") or "INDETERMINATE")
    gate_summary = _as_dict(current_baseline.get("summary"))
    n_gate_blockers = gate_summary.get("n_blockers")
    n_gate_blockers = n_gate_blockers if isinstance(n_gate_blockers, int) else 0
    if gate_verdict != "CLEAR":
        banner = doc.add_paragraph()
        banner_label = banner.add_run(f"CURRENT BASELINE {gate_verdict} — ")
        banner_label.bold = True
        banner_label.font.color.rgb = ink(_RED if gate_verdict == "BLOCKED" else _AMBER)
        if n_gate_blockers:
            banner.add_run(
                f"{n_gate_blockers} blocker occurrence(s) require resolution, recollection, or "
                "explicit disposition before acceptance. Matching a blocker observation is not acceptance."
            )
        else:
            banner.add_run(
                "the validation-plan receipt did not establish a reconciled all-clear. Recollect or "
                "repair the evidence contract before acceptance."
            )
    rows2 = view["rows2"]
    if rows2:
        table(
            ["ID", "Device", "Category / sev", "Check", "Command",
             "Observed baseline / acceptance", "Evidence state", "Custody / source", "Result"],
            rows2,
            widths=[0.55, 0.6, 0.75, 0.9, 0.9, 1.25, 0.7, 1.05, 0.45],
        )
    else:
        doc.add_paragraph("No validation_plan in this snapshot.")

    # ---- 5. Phase III — service & traffic ----
    doc.add_heading("5. Phase III — Service & traffic verification (end-to-end)", level=1)
    rows3 = view["rows3"]
    if rows3:
        table(["ID", "Scope", "Check", "Command", "Expected", "Result"], rows3,
              widths=[0.7, 1.5, 1.5, 1.6, 1.5, 0.5])
    else:
        doc.add_paragraph("No service-map / application-domain data in this snapshot.")

    doc.add_heading("5.1 Persisted design-driven acceptance", level=2)
    doc.add_paragraph("These are the saved engine acceptance instructions. Missing fields remain explicit "
                      "coverage limits; a blank Result cell is not evidence of a passing test.")
    table(["Decision ID", "Title / priority / source", "Phase", "Description", "Setup", "Pass criteria", "Device scope", "Result"],
          view["design_rows"], widths=[0.6, 0.8, 0.6, 1.1, 1.1, 1.1, 0.8, 0.4])
    doc.add_heading("5.2 Persisted EVPN migration acceptance", level=2)
    table(["Guardrail ID", "Title / priority / source", "Phase", "Description", "Setup", "Pass criteria", "Device scope", "Result"],
          view["evpn_rows"], widths=[0.6, 0.8, 0.6, 1.1, 1.1, 1.1, 0.8, 0.4])

    # ---- 6. results & acceptance ----
    doc.add_heading("6. Results summary & acceptance", level=1)
    doc.add_paragraph("Record the outcome of each phase. The network is accepted for production only "
                      "when the exit criteria in §1 are met.")
    table(["Phase", "Total", "Pass", "Fail", "Deviations / notes"], view["result_rows"],
          widths=[3.0, 0.7, 0.7, 0.7, 1.7])
    acc = doc.add_paragraph()
    kv(acc, "Acceptance:", "The undersigned confirm the exit criteria are met and accept the network "
                           "for production use. (See the Sign-off table on page 1.)")

    doc.save(output_path)
