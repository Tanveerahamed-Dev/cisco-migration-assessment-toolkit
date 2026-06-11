"""As-Built Network Design Document — HLD + LLD (.docx).

NEW-V3.23.148: the Design-phase twin of the workbook / explorer / runbook / deck. Cisco Advanced
Services engagements produce a High-Level Design (architecture intent) and a Low-Level Design
(device-by-device build detail) in the PPDIOO Design phase. This module reconstructs BOTH from the
SAME snapshot the other deliverables read — i.e. an *as-built* design recovered from collected
configuration + CDP/LLDP evidence, not a greenfield design — and folds in the assessment's findings
as target-state design recommendations.

One source of truth: every number agrees with the workbook/explorer because it is the same
snap_dict. Evidence discipline is preserved (this is config-/neighbour-derived, not live telemetry):
gateway PLACEMENT is Confirmed where an SVI is configured; the active forwarding owner is Unknown;
inter-switch links are Inferred-high; endpoint presence is Confirmed at snapshot time only.

python-docx is an OPTIONAL dependency (like the runbook): imported inside the function so the package
imports fine without it, and a missing library is a warning + skip, never a crash. Every snapshot read
is defensive (.get / tolerant of missing keys) so an older snapshot degrades gracefully. Deterministic
content; no network, no device data beyond the snapshot.
"""
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime

from cisco_toolkit.docmeta import add_acceptance, add_document_control, add_table, add_toc

logger = logging.getLogger(__name__)

_LC_BAND_RANK = {"Past-LDoS": 0, "Past-EoS": 1, "Near-LDoS": 2, "Active": 3, "Unknown": 4}


def _is_l3(host: str, l3_forwarding, routing_neighbors) -> bool:
    """A device participates in L3 if it owns an SVI (appears in l3_forwarding) or runs a routing
    protocol (has any adjacency record). Used for the core/distribution vs access tiering — honest,
    evidence-based (a configured SVI / a routing neighbour is Confirmed), not a guess from hostname."""
    if any((r.get("switch") == host) for r in (l3_forwarding or [])):
        return True
    rn = (routing_neighbors or {}).get(host) or {}
    return any(rn.get(p) for p in ("ospf", "eigrp", "bgp"))


def _vlan_inventory(snap: dict):
    """Distinct VLAN ids in use across all access/trunk ports + SVIs, with the best-known name.
    Returns an ordered list of (vid:int, name:str). Pure read of the interfaces + l3_forwarding."""
    names: dict = {}
    vids: set = set()
    for host, ports in (snap.get("interfaces") or {}).items():
        for d in (ports or {}).values():
            v = (d.get("vlan") or "").strip()
            if v.isdigit():
                vids.add(int(v))
                nm = (d.get("vlan_name") or "").strip()
                if nm and int(v) not in names:
                    names[int(v)] = nm
    for r in (snap.get("l3_forwarding") or []):
        v = str(r.get("vlan") or "").strip()
        if v.isdigit():
            vids.add(int(v))
    return [(v, names.get(v, "")) for v in sorted(vids)]


def _segmentation_facts(snap: dict):
    """Derive a segmentation posture directly from the interfaces (known shape), so the section is
    accurate regardless of the segmentation compute's internal layout: the set of non-default VRFs in
    use, and the count of SVIs carrying an ingress/egress ACL. Returns (vrfs:set, n_acl_svis:int,
    n_svis:int)."""
    vrfs: set = set()
    n_acl_svis = 0
    n_svis = 0
    for host, ports in (snap.get("interfaces") or {}).items():
        for p, d in (ports or {}).items():
            vrf = (d.get("vrf") or "").strip()
            if vrf and vrf.lower() not in ("default", "global"):
                vrfs.add(vrf)
            if re.match(r"^Vlan\d+$", p, re.IGNORECASE) and (d.get("svi_ip") or ""):
                n_svis += 1
                if (d.get("acl_in") or "").strip() or (d.get("acl_out") or "").strip():
                    n_acl_svis += 1
    return vrfs, n_acl_svis, n_svis


def write_design_doc_docx(output_path: str, snap_dict: dict, label: str) -> None:
    """Emit the As-Built Network Design Document (HLD + LLD) to `output_path`. Fail-soft: a missing
    python-docx is a warning + skip; any unexpected render error is logged, never raised."""
    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Pt, RGBColor
    except ImportError:
        logger.warning("  Design document (DOCX) skipped: python-docx not installed "
                       "(pip install python-docx to enable the HLD/LLD design deliverable).")
        return

    snap = snap_dict or {}
    NAVY = RGBColor(0x1F, 0x38, 0x64)
    GREY = RGBColor(0x59, 0x59, 0x59)
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)

    def _label_run(p, label_text, value, color=NAVY):
        r = p.add_run(label_text); r.bold = True; r.font.color.rgb = color
        p.add_run(" " + (str(value) if value not in (None, "") else "—"))

    def table(headers, rows, widths=None):
        # Delegates to the family's single table builder (docmeta.add_table) — V3.23.152 dedup.
        return add_table(doc, headers, rows, widths, fixed=False)

    # ---- snapshot-derived facts (reconciled to the workbook) ----
    devices = snap.get("devices") or {}
    l3f = snap.get("l3_forwarding") or []
    rn = snap.get("routing_neighbors") or {}
    stp_roots = snap.get("stp_roots") or {}
    redist = snap.get("redistribution") or {}
    fhrp = snap.get("fhrp") or []
    capacity = snap.get("capacity") or []
    lifecycle = snap.get("lifecycle_risk") or {}
    vpc = snap.get("vpc") or {}
    failure_impact = snap.get("failure_impact") or []
    punchlist = snap.get("punchlist") or []
    subnet_intel = snap.get("subnet_intelligence") or {}
    svc = snap.get("service_map") or {}
    eb = snap.get("executive_brief") or {}

    lc_by_host = {}
    for r in (lifecycle.get("per_device") or []):
        h = r.get("host") or r.get("hostname")
        if h:
            lc_by_host[h] = r
    cap_by_host = {r.get("hostname"): r for r in capacity}

    l3_hosts = [h for h in devices if _is_l3(h, l3f, rn)]
    l2_hosts = [h for h in devices if h not in l3_hosts]
    vlans = _vlan_inventory(snap)
    vrfs, n_acl_svis, n_svis = _segmentation_facts(snap)

    # ---- title page ----
    title = doc.add_paragraph(); title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    tr = title.add_run("As-Built Network Design Document"); tr.bold = True
    tr.font.size = Pt(26); tr.font.color.rgb = NAVY
    sub2 = doc.add_paragraph(); sub2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    s2 = sub2.add_run("High-Level Design (HLD) + Low-Level Design (LLD)")
    s2.font.size = Pt(14); s2.font.color.rgb = GREY
    sub = doc.add_paragraph(); sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sr = sub.add_run(label); sr.font.size = Pt(13); sr.font.color.rgb = GREY
    meta = doc.add_paragraph(); meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta.add_run(f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}  ·  "
                 f"{len(devices)} devices in scope  ·  script {snap.get('script_version', '')}"
                 ).font.color.rgb = GREY
    status = doc.add_paragraph(); status.alignment = WD_ALIGN_PARAGRAPH.CENTER
    st = status.add_run("DRAFT — as-built design recovered from collected evidence; review before reuse.")
    st.italic = True; st.font.color.rgb = GREY
    doc.add_paragraph()
    note = doc.add_paragraph()
    _label_run(note, "Design basis:",
               "This document reconstructs the current (as-built) design from collected configuration "
               "and CDP/LLDP neighbour data, not from live forwarding telemetry. It is intended as the "
               "design baseline for the migration: the HLD captures architecture intent recovered from "
               "the fleet, the LLD captures per-device build detail, and §4 lists the target-state "
               "design changes the assessment recommends. Gateway PLACEMENT is Confirmed where an SVI "
               "is configured; the active forwarding owner is Unknown. Inter-switch links are "
               "Inferred-high. Endpoint presence is Confirmed at snapshot time only.", GREY)
    doc.add_page_break()

    # ---- document control (AS-style front matter; unnumbered so §1–§4 are untouched) ----
    add_document_control(
        doc, document="As-Built Network Design Document (HLD + LLD)", label=label,
        engine_version=str(snap.get("script_version", "")), generated_at=snap.get("generated_at"),
        audience="Customer architecture and engineering owners, and the build engineers who derive "
                 "device configurations from the LLD detail.",
        exclude=("design",))
    doc.add_page_break()

    # ---- table of contents (shared field-code helper, V3.23.171) ----
    add_toc(doc)

    # ===== 1. Executive design summary =====
    doc.add_heading("1. Executive Design Summary", level=1)
    posture = eb.get("posture_statement") or (
        f"{len(devices)} devices, {len(vlans)} VLANs and {n_svis} gateway SVIs across the assessed fabric.")
    doc.add_paragraph(posture)
    table(["Design attribute", "As-built value"], [
        ("Devices in scope", len(devices)),
        ("L3 nodes (own an SVI or a routing adjacency)", len(l3_hosts)),
        ("L2-only access nodes", len(l2_hosts)),
        ("VLANs in use", len(vlans)),
        ("Gateway SVIs", n_svis),
        ("Routing VRFs (non-default)", len(vrfs) if vrfs else "0 (single global table)"),
        ("Gateway SVIs with an ACL applied", f"{n_acl_svis} of {n_svis}"),
        ("FHRP gateway groups", len(fhrp)),
        ("vPC / MLAG peerings", len([h for h, v in vpc.items() if v])),
    ], widths=[4.6, 2.2])

    # ===== 2. High-Level Design (HLD) =====
    doc.add_heading("2. High-Level Design (HLD)", level=1)

    doc.add_heading("2.1 Topology tiers", level=2)
    doc.add_paragraph(
        "Devices are tiered by their L3 participation recovered from the configuration: a node that owns "
        "a gateway SVI or forms a routing adjacency is treated as a core/distribution (L3) node; the "
        "remainder are L2 access nodes. This is an evidence-based tiering, not an assumption from naming.")
    table(["Tier", "Count", "Devices"], [
        ("Core / Distribution (L3)", len(l3_hosts), ", ".join(sorted(l3_hosts)[:30]) or "—"),
        ("Access (L2-only)", len(l2_hosts), ", ".join(sorted(l2_hosts)[:30]) or "—"),
    ], widths=[2.2, 0.8, 4.0])
    # keystone devices (concentrated dependency) from failure_impact
    keystones = sorted((r for r in failure_impact if int(r.get("stranded") or 0) > 0),
                       key=lambda r: -int(r.get("stranded") or 0))[:5]
    if keystones:
        _label_run(doc.add_paragraph(), "Concentrated dependency:",
                   "the fabric leans on " + ", ".join(
                       f"{r.get('host')} ({r.get('stranded')} endpoints)" for r in keystones) +
                   " — protect and sequence these first.")

    doc.add_heading("2.2 Layer-2 domain", level=2)
    root_count: Counter = Counter()
    for host, vmap in stp_roots.items():
        for vid, info in (vmap or {}).items():
            if isinstance(info, dict) and info.get("is_root"):
                root_count[host] += 1
    doc.add_paragraph(
        f"The fabric carries {len(vlans)} VLANs. Spanning-tree root placement is recovered from "
        f"'show spanning-tree': " + (
            "; ".join(f"{h} roots {n} VLAN(s)" for h, n in root_count.most_common(6))
            if root_count else "no explicit root bridge was observed in the collected output") + ".")
    if vlans:
        table(["VLAN", "Name"], [(v, nm or "—") for v, nm in vlans[:40]], widths=[1.0, 4.5])
        if len(vlans) > 40:
            doc.add_paragraph(f"… and {len(vlans) - 40} more VLAN(s); full list in the workbook.")

    doc.add_heading("2.3 Layer-3 design", level=2)
    proto_use: Counter = Counter()
    for host, d in rn.items():
        for proto in ("ospf", "eigrp", "bgp"):
            if (d or {}).get(proto):
                proto_use[proto.upper()] += 1
    doc.add_paragraph(
        "Routing protocols recovered from neighbour state: " + (
            ", ".join(f"{p} on {n} device(s)" for p, n in proto_use.most_common())
            if proto_use else "no dynamic-routing adjacencies were observed (static / connected only)") + ".")
    n_redist = sum(len(v or []) for v in redist.values())
    if n_redist:
        _label_run(doc.add_paragraph(), "Redistribution boundaries:",
                   f"{n_redist} route-redistribution edge(s) across the fleet — each is a protocol "
                   "boundary the migration must preserve or consciously retire.")
    if l3f:
        rows = [(r.get("vlan"), r.get("svi_ip") or "—", r.get("switch"),
                 r.get("fhrp") or "—", r.get("risk") or "—") for r in l3f[:40]]
        table(["VLAN", "Gateway IP", "Owner", "FHRP", "Risk"], rows, widths=[0.7, 1.4, 1.4, 1.6, 1.4])
        if len(l3f) > 40:
            doc.add_paragraph(f"… and {len(l3f) - 40} more gateway(s); full register in the workbook.")

    doc.add_heading("2.4 Resilience & redundancy", level=2)
    n_single_gw = sum(1 for r in l3f if "single-gateway" in (r.get("risk") or ""))
    n_fhrp_issue = sum(1 for g in fhrp if g.get("issues"))
    table(["Resilience attribute", "As-built value"], [
        ("FHRP gateway groups", len(fhrp)),
        ("FHRP groups with a consistency issue", n_fhrp_issue),
        ("Single-gateway VLANs (no FHRP peer)", n_single_gw),
        ("vPC / MLAG peerings", len([h for h, v in vpc.items() if v])),
        ("Keystone devices (strand endpoints if lost)", len([r for r in failure_impact
                                                             if int(r.get("stranded") or 0) > 0])),
    ], widths=[4.6, 2.2])

    doc.add_heading("2.5 Multicast & timing design", level=2)
    mc = (svc.get("multicast") or {}) if isinstance(svc, dict) else {}
    groups = mc.get("classified_groups") or []
    queriers = mc.get("igmp_queriers") or []
    ptp = mc.get("ptp") or {}
    ptp_active = sum(1 for v in ptp.values() if isinstance(v, dict) and v.get("operational"))
    # Render the section only when there is actual activity to report; a multicast dict that exists
    # but carries all-zero counts (a non-media fabric, or commands not collected) gets the fallback
    # instead of an all-zeros paragraph that reads as filler in a client deliverable.
    if mc.get("active_switch_count") or mc.get("active_interfaces") or groups or queriers or ptp:
        doc.add_paragraph(
            f"Active multicast was observed on {mc.get('active_switch_count', 0)} switch(es) across "
            f"{mc.get('active_interfaces', 0)} interface(s); {len(groups)} group(s) were classified and "
            f"{len(queriers)} IGMP-snooping querier(s) were found. PTP (IEEE 1588): {ptp_active} of "
            f"{len(ptp)} device(s) report an operational clock — the rest are not boundary-clocked. "
            "On a broadcast fabric these are the production media, Dante/AES67 and ST-2110/PTP flows; "
            "the migration design must preserve querier coverage and the PTP clock hierarchy.")
        if groups:
            table(["Group", "Name", "Category"],
                  [(g.get("group"), g.get("name") or "—", g.get("category") or "—") for g in groups[:15]],
                  widths=[1.6, 2.2, 1.8])
    else:
        doc.add_paragraph("No multicast/PTP activity was classified in the collected output "
                          "(either not a media fabric, or the relevant show commands were not captured).")

    doc.add_heading("2.6 Segmentation & security posture", level=2)
    doc.add_paragraph(
        ("The fabric uses a single global routing table (no non-default VRFs were observed); "
         if not vrfs else
         f"The fabric uses {len(vrfs)} non-default VRF(s): {', '.join(sorted(vrfs)[:10])}. ") +
        f"{n_acl_svis} of {n_svis} gateway SVIs carry an ingress/egress ACL. "
        "Where neither a dedicated VRF nor a gateway ACL is present, inter-VLAN traffic is openly "
        "routed — the migration is an opportunity to introduce intended segmentation.")

    # NEW-V3.23.165: QoS is a named HLD design domain; render the audited CONFIGURED posture
    # when the snapshot carries the qos_audit axis (older snapshots simply skip the section).
    qa = snap_dict.get("qos_audit") or {}
    qsum = qa.get("summary") or {}
    if qsum.get("n_devices"):
        doc.add_heading("2.7 Quality of service (configured posture)", level=2)
        if not qsum.get("n_assessable"):
            doc.add_paragraph(
                "QoS posture is not assessable — no full running-config captures were available. "
                "The target design must state the QoS intent (trust boundary, marking, queuing) "
                "explicitly rather than inherit an unknown current state.")
        else:
            qmodes = qsum.get("modes") or {}
            mtxt = ", ".join(f"{v} device(s) {k}" for k, v in qmodes.items())
            doc.add_paragraph(
                f"Configured posture across the {qsum.get('n_assessable', 0)} assessable device(s): "
                f"{mtxt}. {qsum.get('n_voice_ports', 0)} voice-VLAN port(s) observed. The campus "
                "leading practice is a trust boundary at the access edge (trust detected phones/APs, "
                "mark at ingress) with consistent per-hop queuing fleet-wide; the table below lists "
                "where the observed configuration departs from that intent.")
            qrows = [(f.get("host"), f.get("label"), f.get("severity"))
                     for f in (qa.get("findings") or [])[:12]]
            if qrows:
                table(["Device", "Departure from leading practice", "Severity"],
                      qrows, widths=[1.6, 4.0, 1.0])
            else:
                doc.add_paragraph("No departures: the configured posture is consistent on every "
                                  "assessable device.")

    # ===== 3. Low-Level Design (LLD) =====
    doc.add_heading("3. Low-Level Design (LLD)", level=1)

    doc.add_heading("3.1 Device inventory & roles", level=2)
    inv_rows = []
    for h in sorted(devices):
        d = devices[h] or {}
        lc = lc_by_host.get(h, {})
        role = "Core/Dist (L3)" if h in l3_hosts else "Access (L2)"
        cap = cap_by_host.get(h, {})
        ports = (f"{d.get('active_ports', cap.get('active_ports', '—'))}/"
                 f"{d.get('total_ports', cap.get('total_ports', '—'))}")
        inv_rows.append((h, d.get("model") or "—", d.get("serial_number") or d.get("chassis_serial") or "—",
                         d.get("sw_version") or "—", role, lc.get("band") or "—", ports))
    table(["Hostname", "Model", "Serial", "SW version", "Role", "EoL band", "Active/Total ports"],
          inv_rows, widths=[1.3, 1.3, 1.2, 0.9, 1.1, 0.9, 0.9])

    doc.add_heading("3.2 Addressing & VLAN plan", level=2)
    # vlan -> subnet from subnet_intelligence served_subnets; vlan -> gateway/fhrp from l3_forwarding
    subnet_by_vlan: dict = {}
    for pd in (subnet_intel.get("per_device") or []):
        for s in (pd.get("served_subnets") or []):
            v = str(s.get("vlan") or "")
            if v and s.get("subnet"):
                subnet_by_vlan.setdefault(v, s.get("subnet"))
    addr_rows = []
    for r in l3f:
        v = str(r.get("vlan") or "")
        nm = next((nm for vv, nm in vlans if str(vv) == v), "")
        addr_rows.append((v or "—", nm or "—", subnet_by_vlan.get(v, "—"),
                          r.get("svi_ip") or "—", r.get("switch") or "—", r.get("fhrp") or "—"))
    if addr_rows:
        table(["VLAN", "Name", "Subnet", "Gateway IP", "Gateway device", "FHRP"],
              addr_rows[:50], widths=[0.7, 1.4, 1.3, 1.2, 1.3, 1.2])
        if len(addr_rows) > 50:
            doc.add_paragraph(f"… and {len(addr_rows) - 50} more; full plan in the workbook.")
    else:
        doc.add_paragraph("No gateway SVIs were observed — addressing is delegated off-fabric (pure L2).")

    doc.add_heading("3.3 Per-device build detail", level=2)
    doc.add_paragraph(
        "Per device: the gateway SVIs it owns (with FHRP role), the trunk uplinks to neighbours, and the "
        "port-channels it terminates — the build facts a re-implementation must reproduce.")
    shown = 0
    for h in sorted(l3_hosts) + sorted(l2_hosts):
        ports = (snap.get("interfaces") or {}).get(h) or {}
        svis, uplinks, pos = [], [], []
        for p, d in ports.items():
            if re.match(r"^Vlan\d+$", p, re.IGNORECASE) and (d.get("svi_ip") or ""):
                svis.append(f"{p} {d.get('svi_ip')}" + (f" [{d.get('hsrp_behavior')}]"
                                                        if d.get("hsrp_behavior") else ""))
            if (d.get("switchport_mode") or "").lower() == "trunk" and d.get("cdp_neighbor"):
                uplinks.append(f"{p}→{d.get('cdp_neighbor')}")
            if p.startswith("Po"):
                pos.append(p)
        if not (svis or uplinks or pos):
            continue
        doc.add_heading(h, level=3)
        if svis:
            _label_run(doc.add_paragraph(), "Gateway SVIs:", "; ".join(sorted(svis)[:12]))
        if uplinks:
            _label_run(doc.add_paragraph(), "Trunk uplinks:", ", ".join(sorted(uplinks)[:14]))
        if pos:
            _label_run(doc.add_paragraph(), "Port-channels:", ", ".join(sorted(set(pos))))
        shown += 1
        if shown >= 40:
            doc.add_paragraph(f"… per-device detail truncated at {shown} devices; full per-port data "
                              "is in the workbook.")
            break

    doc.add_heading("3.4 Equipment list (Bill of Materials)", level=2)
    by_model = defaultdict(lambda: {"count": 0, "band": "Unknown"})
    for h, d in devices.items():
        m = (d or {}).get("model") or "Unknown"
        by_model[m]["count"] += 1
        b = lc_by_host.get(h, {}).get("band")
        if b and _LC_BAND_RANK.get(b, 9) < _LC_BAND_RANK.get(by_model[m]["band"], 9):
            by_model[m]["band"] = b
    bom_rows = sorted(((m, v["count"], v["band"]) for m, v in by_model.items()),
                      key=lambda r: (-r[1], r[0]))
    table(["Model", "Qty", "Worst EoL band"], bom_rows, widths=[3.0, 1.0, 2.0])

    doc.add_heading("3.5 Software plan & recommendations", level=2)
    doc.add_paragraph(
        "Per AS low-level-design convention, software versions are recorded as the MINIMUM for the "
        "solution, and images per platform should vary as little as possible — consistent software "
        "eases troubleshooting and root-cause analysis. The table reads the observed (as-built) image "
        "per model; where a model runs mixed versions, the most widely deployed image is the natural "
        "standardization candidate.")
    sw_by_model: dict = defaultdict(Counter)
    for h, d in devices.items():
        m = (d or {}).get("model") or "Unknown"
        sw_by_model[m][((d or {}).get("sw_version") or "").strip() or "—"] += 1
    sw_rows, mixed = [], []
    for m, cnt in sorted(sw_by_model.items(), key=lambda kv: (-sum(kv[1].values()), kv[0])):
        images = ", ".join(f"{v} ×{n}" for v, n in cnt.most_common())
        known = [v for v, _ in cnt.most_common() if v != "—"]
        if len(known) > 1:
            status = f"MIXED — standardize on {known[0]}"
            mixed.append((m, known[0]))
        elif known:
            status = "Consistent"
        else:
            status = "No version data"
        sw_rows.append((m, images, status, by_model[m]["band"]))
    table(["Model", "Images observed", "Status", "Worst EoL band"],
          sw_rows[:30], widths=[1.7, 2.2, 1.8, 1.0])
    recs = []
    for m, cand in mixed[:8]:
        recs.append(f"{m}: consolidate to one image. The most widely deployed ({cand}) is the "
                    "standardization candidate; validate it against Cisco's published recommended "
                    "release for the platform before adoption.")
    eol_models = sorted(m for m, v in by_model.items() if v["band"] in ("Past-EoS", "Past-LDoS"))
    if eol_models:
        recs.append("Hardware past end-of-support gets replacement, not an image upgrade: "
                    + ", ".join(eol_models[:8])
                    + ". Plan these as new-platform builds in the target design (§4).")
    if recs:
        for r_ in recs:
            doc.add_paragraph(r_, style="List Bullet")
    else:
        doc.add_paragraph(
            "Software is consistent per platform and no past-end-of-support hardware was observed — "
            "carry the current images forward as the minimum-version baseline for the target design.")

    # ===== 4. Target-state design recommendations =====
    doc.add_heading("4. Target-State Design Recommendations", level=1)
    doc.add_paragraph(
        "The assessment's consolidated punch-list, read as design intent: the changes the target design "
        "should adopt so the rebuilt fabric does not inherit the current gaps. Severity-ranked; full "
        "evidence and per-device scope are in the runbook and the Migration Punch-List workbook sheet.")
    sev_rank = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}
    top = sorted(punchlist, key=lambda i: sev_rank.get(i.get("severity"), 5))[:12]
    if top:
        table(["Severity", "Category", "Design recommendation", "Devices"],
              [(i.get("severity"), i.get("category") or "—", i.get("title") or "—",
                ", ".join(str(x) for x in (i.get("devices") or [])[:4]) +
                ("" if len(i.get("devices") or []) <= 4 else f" +{len(i['devices']) - 4}"))
               for i in top], widths=[0.9, 1.3, 3.0, 1.6])
    else:
        doc.add_paragraph("No punch-list items — the as-built design carries no flagged gaps to redesign.")

    # ---- closing acceptance gate (AS-style back matter) ----
    add_acceptance(
        doc, scope_note="Acceptance confirms the as-built record as the design baseline for the "
                        "migration; the §4 target-state items proceed to detailed design under "
                        "their own approvals.")

    n_sections = len([p for p in doc.paragraphs if p.style.name == "Heading 1"])
    doc.save(output_path)
    logger.info(f"[Phase 33] Design document (DOCX) written: {output_path} ({n_sections} sections)")
