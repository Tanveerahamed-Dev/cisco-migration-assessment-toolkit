"""In-process end-to-end test: drive the real pipeline through ``main()`` (no subprocess) and assert
the three deliverables are produced and well-formed.

This complements ``test_pipeline_golden.py`` (which runs the pipeline in a SUBPROCESS to freeze the
snapshot/Excel-schema byte-for-byte). Running in-process instead buys two things the subprocess can't:

  * **Coverage** — the workbook writers (``excel.py``), the orchestration (``build.py``), and the
    HTML-embed path (``html.py``) are exercised IN THIS PROCESS, so ``pytest --cov`` actually credits
    them. Under the subprocess golden they run in a child the coverage tool never sees (which made
    ``excel.py`` read as ~18% covered when it is in fact exercised end to end).
  * **Debuggability** — a workbook-build regression surfaces here as a real Python traceback at the
    failing writer, instead of a stdout/stderr diff from a dead child process.

It deliberately asserts only STRUCTURAL properties (the files exist, the workbook opens and carries its
lead sheets, the snapshot carries its computed keys, the explorer embeds the snapshot) — never the
byte-exact golden, which stays the subprocess test's job, so the two don't duplicate each other.
"""
import json
import os
import sys

from openpyxl import Workbook, load_workbook

import synthetic_fixtures as fx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import COLLECT_PARSE_V3_23_0 as cp   # noqa: E402  (the entry module; main() is the console entry point)


def _make_template(path):
    """Minimal template workbook — the loader only needs a header row with hostname/port/status."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Interface Data"
    ws.append(["Hostname", "Port", "Status"])
    wb.save(path)


def test_pipeline_inprocess_builds_all_three_deliverables(tmp_path, monkeypatch):
    collection = fx.write_collection(str(tmp_path / "collection"))
    devices = tmp_path / "devices.json"
    devices.write_text(json.dumps(fx.DEVICES), encoding="utf-8")
    template = tmp_path / "template.xlsx"
    _make_template(str(template))
    out_xlsx = tmp_path / "out.xlsx"

    # Run from a clean working directory (main() writes its log file into cwd) with argv set as if
    # invoked from the command line. HTML is intentionally LEFT ON so write_html_explorer is exercised.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "cisco-assess",
        "--no-collect", "--collection-dir", collection,
        "--devices-file", str(devices), "--template", str(template),
        "--output", str(out_xlsx), "--workers", "1",
    ])

    cp.main()   # the actual console entry point — exercises build/excel/html/runbook in-process

    # ---- workbook ----
    assert out_xlsx.is_file(), "workbook was not written"
    wb = load_workbook(str(out_xlsx), read_only=True)
    sheets = wb.sheetnames
    wb.close()
    assert "Executive Summary" in sheets, f"Executive Summary sheet missing; got {sheets[:5]}…"
    assert len(sheets) >= 20, f"expected the full multi-sheet workbook, got only {len(sheets)} sheets"

    # ---- snapshot (the data contract) ----
    snap_path = os.path.splitext(str(out_xlsx))[0] + ".snapshot.json"
    assert os.path.isfile(snap_path), "snapshot.json was not written"
    snap = json.loads(open(snap_path, encoding="utf-8").read())
    for key in ("devices", "interfaces", "health_scores", "punchlist", "causality", "executive_brief"):
        assert key in snap, f"snapshot missing computed key {key!r}"
    # Provenance (wave R2-1-01 / R2-3-01): the snapshot records WHEN THE EVIDENCE WAS COLLECTED, and the
    # lifecycle EoL bands are pinned to THAT instant (not wall-clock-at-regen) so a re-render reproduces
    # them deterministically. collected_at is threaded into compute_lifecycle_risk as its asof.
    assert "collected_at" in snap, "snapshot missing collection-time provenance (collected_at)"
    # lifecycle bands are date-granular, so asof is the DATE of collection (compute_lifecycle_risk
    # normalises its asof to a date); it must equal the collection date, never the regen day.
    assert snap.get("lifecycle_risk", {}).get("asof") == snap["collected_at"][:10], \
        "lifecycle bands must be dated to the collection date (asof == collected_at[:10]), not the regen day"
    # SSOT: the brief's scale block publishes the canonical VLAN count, equal to the vlan_inventory
    # derivation the deliverables + dashboards read (one source — no JS/TS recount drift).
    from cisco_toolkit.analyze import vlan_inventory
    _scale = snap["executive_brief"]["scale"]
    assert "n_vlans" in _scale, "scale.n_vlans (canonical VLAN count) missing from the brief"
    assert _scale["n_vlans"] == len(vlan_inventory(snap)), "scale.n_vlans must equal canonical vlan_inventory"
    # SSOT: the genuinely-collected subset is published canonically too, so coverage-honesty surfaces read
    # ONE "N collected of M inventoried" instead of mislabelling inventory as assessed. (SSOT-device-deliv-06)
    assert _scale.get("n_collected") == ((snap.get("collection_completeness") or {}).get("summary") or {}).get("complete"), \
        "scale.n_collected must equal collection_completeness.summary.complete"
    # SSOT (workbook headline): the Executive Summary 'Scope / scale' block must STATE the canonical VLAN
    # count, never leave it blank. The brief's scale gets n_vlans injected BEFORE this sheet is written (the
    # snapshot's n_vlans is assembled later), so without that injection the workbook would miss 'VLANs in use'.
    _wb = load_workbook(str(out_xlsx), read_only=True)
    _es = _wb["Executive Summary"]
    _vlan_cell = "MISSING"; _coll_cell = "MISSING"
    for _row in _es.iter_rows():
        _lbl = str(_row[0].value or "").strip() if _row else ""
        if _lbl == "VLANs in use":
            _vlan_cell = _row[1].value if len(_row) > 1 else None
        elif _lbl == "Switches collected / inventoried":
            _coll_cell = _row[1].value if len(_row) > 1 else None
    _wb.close()
    assert _vlan_cell == _scale["n_vlans"], (
        f"Executive Summary 'VLANs in use' must state the canonical {_scale['n_vlans']}, got {_vlan_cell!r}")
    # SSOT (QA F1): the Fleet-posture block reads canonical scale.n_collected ("<collected> / <inventoried>"),
    # not a local recompute that would call the full inventory "assessed". n_collected is injected into the
    # brief's scale BEFORE this sheet is written (same early-injection point as n_vlans).
    assert _coll_cell == f"{_scale['n_collected']} / {len(snap.get('health_scores') or [])}", (
        f"Exec Summary 'Switches collected / inventoried' must lead with canonical n_collected, got {_coll_cell!r}")

    # SSOT: the canonical CCDE-grounded design blueprint is PUBLISHED into the snapshot (the one source the
    # design DOCX / explorer / webapp all read), and equals a fresh compute over the same snapshot — no
    # surface recomputes design intent.
    from cisco_toolkit.design_advisor import compute_design_blueprint
    assert "design_blueprint" in snap, "snapshot must publish the canonical design_blueprint"
    _bp = snap["design_blueprint"]
    assert isinstance(_bp.get("decisions"), list) and "tradeoff_scorecard" in _bp and "summary" in _bp
    # SSOT: equals a fresh compute over the snapshot WITH the same requirements register (if one was
    # supplied via --requirements, it is stored in the snapshot so the blueprint stays reproducible).
    assert _bp == compute_design_blueprint(snap, snap.get("requirements_register")), \
        "published design_blueprint must equal the canonical recompute (with the same requirements register)"
    # UNIVERSALITY (FHRP): the fixture's core1 has an untracked active HSRP gateway. The engine must PUBLISH
    # per-device FHRP detail and ASSESS it end-to-end -- the blueprint carries the FHRP-resilience decision.
    # [HISTORY-REDACTED] ran zero FHRP, so this is the first architecture coverage proven on a non-[HISTORY-REDACTED] environment.
    assert isinstance(snap.get("fhrp_detail"), dict) and snap["fhrp_detail"].get("core1"), \
        "snapshot must publish per-device FHRP detail (build_fhrp_detail -> parse_hsrp_detail)"
    assert any(d.get("id") == "fhrp-resilience-tracking-and-preempt" for d in _bp.get("decisions", [])), \
        "engine must assess FHRP: an untracked active gateway must fire _d_fhrp_resilience"
    # UNIVERSALITY (VXLAN-EVPN): core2 is a VTEP with a DOWN peer. The engine must PUBLISH snap['overlay']
    # and the blueprint must carry the VXLAN NVE-peer-down decision -- its OWN target fabric, previously blind.
    assert isinstance(snap.get("overlay"), dict) and snap["overlay"].get("core2", {}).get("nve_peers"), \
        "snapshot must publish per-device VXLAN overlay (build_overlay -> parse_nve_peers)"
    assert any(d.get("id") == "vxlan-nve-peer-down" for d in _bp.get("decisions", [])), \
        "engine must assess VXLAN: a down VTEP peer must fire _d_nve_peer_health"
    assert any(d.get("id") == "vxlan-evpn-control-plane-down" for d in _bp.get("decisions", [])), \
        "engine must assess EVPN control plane: an Idle RR session must fire _d_evpn_rr_health"
    assert any(d.get("id") == "vxlan-nve-vni-down" for d in _bp.get("decisions", [])), \
        "engine must assess VXLAN VNI: a not-Up VNI must fire _d_nve_vni_health"
    assert any(d.get("id") == "copp-control-plane-policer-dropping" for d in _bp.get("decisions", [])), \
        "engine must assess CoPP: a dropping control-plane class must fire _d_copp_drops"
    # UNIVERSALITY (architecture-coverage build wave): each new axis is PUBLISHED into the snapshot and its
    # detector fires end-to-end on the synthetic fixtures (broken state only; silent companions prove no
    # over-firing). core1 = PIM-no-RP + unsynchronized NTP + QoS LLQ drops; access1 = dual-stack-no-RA-Guard +
    # port-security Secure-shutdown + toothless storm-control; core2 = an undocumented (shadow) infra router.
    assert isinstance(snap.get("pim"), dict) and snap["pim"].get("core1", {}).get("neighbors"), \
        "snapshot must publish per-device PIM (build_pim -> parse_pim_rp_mapping / parse_pim_neighbors)"
    assert any(d.get("id") == "multicast-pim-rp-resilience" for d in _bp.get("decisions", [])), \
        "engine must assess PIM: a running PIM device with no RP must fire _d_pim_rp_health"
    assert isinstance(snap.get("ipv6_fhs"), dict) and snap["ipv6_fhs"].get("access1", {}).get("dualstack"), \
        "snapshot must publish per-device IPv6 first-hop security (build_ipv6_fhs)"
    assert any(d.get("id") == "ipv6-first-hop-security-suite-at-access-edge" for d in _bp.get("decisions", [])), \
        "engine must assess IPv6 FHS: a dual-stack access switch with no RA-Guard must fire _d_ipv6_fhs"
    assert isinstance(snap.get("ntp"), dict) and snap["ntp"].get("core1", {}).get("synchronized") is False, \
        "snapshot must publish per-device NTP clock-sync STATE (build_ntp -> parse_ntp_status)"
    assert any(d.get("id") == "mgmt-time-sync-logging-baseline" for d in _bp.get("decisions", [])), \
        "engine must assess NTP: an unsynchronized clock must fire _d_ntp_sync"
    assert isinstance(snap.get("port_security"), dict) and snap["port_security"].get("access1"), \
        "snapshot must publish per-device port-security DETAIL (build_port_security_detail)"
    assert any(d.get("id") == "security-l2-access-edge-suite" for d in _bp.get("decisions", [])), \
        "engine must assess port-security: a Secure-shutdown port must fire _d_port_security_errdisable"
    assert isinstance(snap.get("storm_control"), dict) and snap["storm_control"].get("access1"), \
        "snapshot must publish per-device storm-control (build_storm_control)"
    assert any(d.get("id") == "storm-control-action-on-edge" for d in _bp.get("decisions", [])), \
        "engine must assess storm-control: a configured action-None rule must fire _d_storm_control_action"
    assert isinstance(snap.get("qos_runtime"), dict) and snap["qos_runtime"].get("core1"), \
        "snapshot must publish per-device QoS runtime (build_qos_runtime -> parse_policymap_drops)"
    assert any(d.get("id") == "qos-runtime-egress-queue-drops" for d in _bp.get("decisions", [])), \
        "engine must assess QoS runtime: an LLQ class being congestion-dropped must fire _d_qos_runtime_drops"
    assert isinstance(snap.get("shadow_infra"), dict) and snap["shadow_infra"].get("core2"), \
        "snapshot must publish per-device shadow-infra neighbours (build_undocumented_neighbors)"
    assert any(d.get("id") == "discover-undocumented-infrastructure-before-cutover" for d in _bp.get("decisions", [])), \
        "engine must assess shadow infra: an undocumented infra neighbour must fire _d_shadow_infra"
    # SSOT: the design-driven NRFU checklist is ALSO published (the one source the explorer + webapp read,
    # so neither re-derives the phased acceptance items) and equals a fresh compute over the blueprint.
    from cisco_toolkit.design_advisor import compute_design_nrfu
    assert "design_nrfu" in snap, "snapshot must publish the canonical design_nrfu"
    assert isinstance(snap["design_nrfu"].get("items"), list)
    assert snap["design_nrfu"] == compute_design_nrfu(_bp), \
        "published design_nrfu must equal the canonical recompute from the published blueprint"

    # ---- explorer (snapshot embedded into the single-file viewer) ----
    explorer = os.path.splitext(str(out_xlsx))[0] + "_explorer.html"
    assert os.path.isfile(explorer), "explorer HTML was not written"
    html = open(explorer, encoding="utf-8").read()
    assert "EMBEDDED_SNAPSHOT" in html, "explorer did not get the live snapshot embedded"
    # SSOT (explorer dashboard): _slim_for_embed shrinks the in-page payload, so it must PRESERVE the
    # canonical executive_brief.scale — that is the one source the explorer's censusSec() reads
    # (SNAP.executive_brief.scale ?? MODEL...). If a future slim drops it, the census silently falls back
    # to a client-side MODEL recount = the 148-vs-202 drift class. Lock that the embedded payload carries
    # the same canonical scale the snapshot publishes, so python and dashboard cannot diverge.
    _embedded_json = html.split("const EMBEDDED_SNAPSHOT=", 1)[1] \
        .split("load(EMBEDDED_SNAPSHOT,", 1)[0].rstrip().rstrip(";").rstrip()
    _embedded = json.loads(_embedded_json)
    _embed_scale = (_embedded.get("executive_brief") or {}).get("scale") or {}
    for _k in ("n_vlans", "n_endpoints", "n_devices"):
        assert _embed_scale.get(_k) == _scale.get(_k), (
            f"explorer embed dropped canonical scale.{_k} "
            f"({_embed_scale.get(_k)!r} != published {_scale.get(_k)!r}) — census would drift to a client recount")

    # ---- executive deck (optional python-pptx): if the lib is present, main() must have written it ----
    try:
        import pptx  # noqa: F401
    except ImportError:
        pass
    else:
        deck = os.path.splitext(str(out_xlsx))[0] + "_executive_deck.pptx"
        assert os.path.isfile(deck), "executive deck (PPTX) was not written despite python-pptx installed"
