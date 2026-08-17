"""[Plan A / Tier-1 #3] Sentinel guard for the explorer's Parse Yield card.

snap['parse_yield'] (the zero-parse yield ledger cmdio.parse_yield_report() publishes and the
workbook's Collection Completeness sheet renders as its Parse Yield section) must be surfaced
read-only on the explorer too. Guards the recurring cross-surface drift class: the card function
exists, is back-compat guarded (no key -> no card), is actually MOUNTED in the Health view's
data-quality run (between the collection and capture-integrity cards), and the embedded demo
snapshot carries the ledger with the engine's coverage-honest note VERBATIM -- a wording change
in cmdio.py must turn up here, not drift silently between surfaces.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


def _html():
    return (ROOT / "cisco_toolkit" / "blast_radius_explorer.html").read_text(encoding="utf-8")


def test_parse_yield_card_wired_and_mounted():
    html = _html()
    assert "function parseYieldCard()" in html, "explorer is missing the Parse Yield card"
    assert "SNAP&&SNAP.parse_yield" in html, "card must be back-compat guarded (no key -> no card)"
    # mounted in the Health render's data-quality run: collection -> parse yield -> capture integrity
    # (what wasn't collected -> what was collected but didn't parse -> whether captures are trustworthy)
    assert re.search(r"\$\{collectionCard\(\)\}\s*\$\{parseYieldCard\(\)\}\s*\$\{captureIntegrityCard\(\)\}",
                     html), "parseYieldCard() must be mounted between collectionCard() and captureIntegrityCard()"


def test_parse_yield_demo_carries_engine_note_verbatim():
    """The demo ledger ships cmdio's own note VERBATIM (never a paraphrase) -- the same
    coverage-honest wording every real snapshot publishes. If cmdio.py rewords the note this
    fails, forcing the demo (and a reviewer's eyes) to move with the engine."""
    from cisco_toolkit import cmdio
    note = cmdio.parse_yield_report()["summary"]["note"]
    assert "never a device" in note          # the contract phrase itself (engine side)
    assert note in _html(), "explorer demo snapshot must carry the engine's coverage-honest note verbatim"


def test_parse_yield_card_never_verdicts_a_device():
    """The card's static wording keeps the collected-but-unparsed framing: a zero-yield row is a
    possible parser format gap, NEVER a device health verdict (the workbook section's wording)."""
    html = _html()
    assert "NEVER a device health verdict" in html
    # the suspect class is named like the workbook's red rows, so the two surfaces read identically
    assert "SUSPECT format gap" in html and "expected-empty" in html


def test_demo_fhrp_validation_requires_bounded_review_of_its_group_difference():
    """The embedded demo observes VLAN 20 as HSRP group 20 vs group 21.  Its own
    validation row must preserve that review baseline instead of presenting an
    ideal Active/Standby pair as an acceptance target."""
    html = _html()
    row = next(
        line for line in html.splitlines()
        if 'category:"FHRP"' in line and 'VLAN 20' in line
    )
    assert "First-hop redundancy evidence review for VLAN 20" in row
    assert "PRE-CUTOVER REVIEW — BLOCKER" in row
    assert "group 20 Active" in row and "group 21 Standby" in row
    assert "cannot distinguish independent elections from a mismatched pair" in row
    assert "Verify all intended members simultaneously before acceptance" in row
    assert "First-hop redundancy healthy for VLAN 20" not in row

    vlan10 = next(
        line for line in html.splitlines()
        if 'category:"FHRP"' in line and 'VLAN 10' in line
    )
    assert "Observed HSRP baseline for VLAN 10 on DIST-1" in vlan10
    assert "local role Active, VIP 10.0.10.1" in vlan10
    assert "exactly one Active + one Standby" not in vlan10
    assert "without inferring peer count or simultaneity" in vlan10

    banner = next(line for line in html.splitlines() if "banner:\"Run these AFTER" in line)
    assert "PRE-CUTOVER DEGRADED — BLOCKER:" in banner
    assert "PRE-CUTOVER REVIEW — BLOCKER:" in banner
    assert "never invents a healthy count" in banner


def test_demo_routing_validation_matches_its_actual_degraded_neighbor_projection():
    """The demo's validation gate must tell the same routing story as its own
    routing_neighbors block instead of substituting unrelated ideal FULL peers."""
    html = _html()
    row = next(
        line for line in html.splitlines()
        if 'category:"Routing"' in line and 'OSPF observed adjacency baseline' in line
    )
    assert "PRE-CUTOVER DEGRADED — BLOCKER" in row
    assert "10.0.99.3 FULL/DR" in row
    assert "10.0.40.9 EXSTART/DROTHER" in row
    assert "10.0.20.5 INIT" in row
    assert "no expected-neighbor denominator is inferred" in row
    assert 'evidence_state:"degraded"' in row
    assert 'projection_custody:"embedded_unverified"' in row
    assert 'source_key:"routing_neighbors.DIST-1.ospf"' in row
    assert "10.0.0.2" not in row and "10.0.0.3" not in row


def test_wave_validation_block_separates_blockers_from_unexecuted_checks():
    """The wave card must present producer-declared blockers as current pre-cutover
    state, while ordinary High/Critical checks remain neutral until somebody runs them."""
    html = _html()
    block = html[html.index("function wavesValidationBlock(wave)"):
                 html.index("function drawWaves()")]

    # Producer-owned blocker markers and evidence states are protocol-neutral. Definite
    # degradation is ranked ahead of review/identity ambiguity, and all precede ordinary checks.
    assert "/^PRE-CUTOVER (DEGRADED|REVIEW) — BLOCKER:/i" in block
    assert "(?:ROUTING|ETHERCHANNEL) BASELINE NOT VERIFIED" in block
    assert "FHRP CONFIGURED GROUP NOT VERIFIED" in block
    assert 'blockerKind(it)==="DEGRADED"?2:blockerKind(it)==="REVIEW"?1:0' in block
    assert "blockerRank(b.it)-blockerRank(a.it)" in block
    assert 'state==="degraded"?"DEGRADED"' in block
    assert '(state==="review"||state==="not_verified")?"REVIEW"' in block
    assert "isRoutingBlocker" not in block
    assert "blockers.concat(ordinary.slice(0,3))" in block

    # A blocker gets an explicit red/amber row and pill; an unexecuted check is
    # deliberately neutral rather than looking like it already passed.
    assert "border-left:2px solid var(--${tone})" in block
    assert "background:var(--${tone}-soft)" in block
    assert "PRE-CUTOVER ${esc(kind)} BLOCKER" in block
    assert "BASELINE NOT VERIFIED" in block
    assert '<span class="pill pl-neutral">not executed</span>' in block
    assert '"var(--text-faint)"' in block
    assert "var(--ok)" not in block

    # The summary counts actual producer-declared blockers; severity is execution
    # priority, not evidence that an unexecuted check is already failing.
    assert "blockers.length" in block
    assert "pre-cutover blocker" in block
    assert "high.length" not in block
    assert " critical</span>" not in block
    assert "<b>baseline / acceptance</b>" in block
    assert "<b>expect</b>" not in block
    assert "<b>evidence</b>" in block
    assert "<b>custody</b>" in block
    assert "embedded projection — unverified" in block
    assert "<b>source</b>" in block


def test_protocol_runtime_receipt_is_mounted_and_fails_closed():
    html = _html()
    assert "function protocolAssessability()" in html
    assert "SNAP&&SNAP.protocol_assessability" in html
    assert "function protoAssessDetailSection(host)" in html
    assert "${protoAssessDetailSection(host)}" in html
    assert "issues / gaps" in html
    assert "Runtime assessability receipt unavailable" in html
    assert "No supported issue in observed scope is not a fleet-wide protocol health certification" in html

    runtime_block = html[html.index("function protocolAssessability()"):
                         html.index("/* Protocol INTELLIGENCE")]
    assert '>clean</span>' not in runtime_block
    assert "coverage incomplete" in runtime_block
    assert "observed scope clear" in runtime_block
    assert 'gaps.length?' in runtime_block, "green status must require a zero-gap current-run receipt"
    assert 'pa.summary.n_families!==7' in runtime_block
    assert 'pa.rows.length!==byHost.size*7' in runtime_block
    for family in ("STP", "EtherChannel", "VTP", "OSPF", "BGP", "EIGRP", "FHRP"):
        assert f'"{family}"' in runtime_block


def test_protocol_receipt_keeps_sparse_health_and_evidence_state_orthogonal():
    html = _html()
    receipt_block = html[html.index("function protocolAssessability()"):
                         html.index("/* Protocol INTELLIGENCE")]
    assert "health_row_emitted" not in receipt_block, (
        "the explorer must render the producer-owned assessment state, not reconstruct it from health rows"
    )
    assert 'r.state!=="assessed"' in receipt_block
    assert "input_states" in receipt_block
    assert "Sparse health rows do not prove coverage for this device" in receipt_block


def test_protocol_effective_issue_union_prevents_vtp_advisory_false_green():
    """VTP HIGH-REVISION is Info in health but High in intelligence; either source must block green."""
    html = _html()
    issue_block = html[html.index("function protocolEffectiveIssues()"):
                       html.index("function protoAssessRow(r)")]
    assert "VTP HIGH-REVISION" in html
    assert "const byCell=new Map()" in issue_block
    assert r'const key=String(r.switch||"")+"\u0000"+String(r.protocol||"");' in issue_block
    assert 'health.forEach(r=>add(r,"health"))' in issue_block
    assert 'intelligence.forEach(r=>add(r,"intelligence"))' in issue_block

    health_block = html[html.index("function protoHealthSection()"):
                        html.index("function protoAssessDetailSection(host)")]
    assert "const issues=protocolEffectiveIssues()" in health_block
    assert "issues.length?" in health_block
    assert "observed health or protocol intelligence" in health_block

    draw_block = html[html.index("function drawProtocols()"):
                      html.index("function drawProtocolsDetail(host)")]
    assert "const protoIssueRows=protocolEffectiveIssues()" in draw_block
    assert "protoIssues=protoIssueRows.length" in draw_block
    assert 'ph.filter(r=>r.severity==="High"||r.severity==="Medium").length' not in draw_block


def test_protocol_detail_host_union_opens_l2_only_receipt_hosts():
    html = _html()
    host_block = html[html.index("function protocolDetailHosts("):
                      html.index("function drawProtocols()")]
    assert "new Set((routingHosts||[])" in host_block
    assert "[receiptRows,healthRows,intelligenceRows]" in host_block
    assert "hosts.add(row.switch)" in host_block

    draw_block = html[html.index("function drawProtocols()"):
                      html.index("function drawProtocolsDetail(host)")]
    assert "protocolDetailHosts(withProto,paRows,ph,pi)" in draw_block
    assert "detailHosts.includes(SEL)" in draw_block
    assert "withProto.includes(SEL)" not in draw_block


def test_protocol_jump_rows_and_generic_wiring_are_keyboard_operable():
    html = _html()
    for name in ("protoAssessRow", "protoHealthRow", "protoIntelRow"):
        start = html.index(f"function {name}(r)")
        end = html.index("\nfunction ", start + 1)
        block = html[start:end]
        assert 'data-jump="${esc(r.switch)}"' in block
        assert 'role="button"' in block
        assert 'tabindex="0"' in block

    start = html.index('p.querySelectorAll("[data-jump]")')
    jump_wiring = html[start:html.index("// wire endpoint-row clicks", start)]
    assert "const jump=()=>" in jump_wiring
    assert "r.onclick=jump" in jump_wiring
    assert "r.onkeydown=ev=>" in jump_wiring
    assert 'ev.key==="Enter"||ev.key===" "' in jump_wiring
    assert "ev.preventDefault();jump()" in jump_wiring


def test_compare_retains_second_snapshot_and_mounts_protocol_change_gate():
    """The topology diff remains intact, but comparison must also retain the
    second snapshot so the receipt-gated protocol owner can inspect both sides."""
    html = _html()
    assert "let SNAP_B=null, MODEL_B=null, CMP=null" in html
    assert "function computeProtocolAdjacencyDelta(oldSnap,newSnap,sourceBinding)" in html
    assert "function setComparisonSnapshot(snapB)" in html
    assert "cmp.protocolAdjacencies=computeProtocolAdjacencyDelta(SNAP,snapB)" in html
    assert html.count("setComparisonSnapshot(snapB);repaint();renderDrawer()") == 2, (
        "both the file-B loader and demo remediation path must supply the full second snapshot"
    )
    assert "${protocolCompareSection(c.protocolAdjacencies)}" in html

    section = html[html.index("function protocolCompareSection(p)"):
                   html.index("function drawCompare()")]
    for label in ("preserved", "regressed", "no longer observed", "new", "recovered", "coverage gaps"):
        assert label in section
    assert "embedded_unverified" in section
    assert "No expected peers are inferred" in section
    assert "Compared scope:" in section
    assert "s.n_baseline_peers" in section and "s.n_comparable_cells" in section and "s.n_scoped_cells" in section
    assert 'const outcome=n=>(p.assessed||Number(n)>0)?String(Number(n)||0):"—"' in section, (
        "positive partial-scope findings must remain visible, while unknown zeroes render as em dashes"
    )
    assert '<button type="button" class="checkrow protocol-compare-jump"' in section
    assert 'data-protocol-jump="${esc(r.switch)}"' in section
    assert ' aria-label="Open ${esc(r.protocol)} protocol detail for ${esc(r.switch)}"' in section
    assert ' data-jump=' not in section, "Compare protocol rows need their dedicated cross-mode drill-through"

    nav_start = html.index('p.querySelectorAll("[data-protocol-jump]")')
    nav = html[nav_start:html.index("// wire row jumps", nav_start)]
    assert "b.onclick=()=>" in nav, "native buttons supply Enter/Space activation through click"
    assert "const h=b.dataset.protocolJump;SEL=h;EPSEL=null;setMode(\"protocols\")" in nav
    assert "if(POS[h])centerOn(h)" in nav
    assert "Protocols detail for" in nav

    core = html[html.index("function _padReceiptView(snap)"):
                html.index("/* REASONING-CORE-PORT END")]
    assert 'state==="assessed"&&row.health_row_emitted!==true' in core
    assert "protocol assessability marks a cell assessed without an emitted health row" in core
    assert "routing-neighbor projection has zero peers" in core


_PAD_FAMILIES = ("STP", "EtherChannel", "VTP", "OSPF", "BGP", "EIGRP", "FHRP")


def _pad_receipt(host, states):
    rows = []
    for family in _PAD_FAMILIES:
        state = states.get(family, "not_collected")
        rows.append({
            "switch": host,
            "protocol": family,
            "state": state,
            "health_row_emitted": state == "assessed",
        })
    return {
        "schema": "protocol_assessability/1",
        "families": [{"protocol": family} for family in _PAD_FAMILIES],
        "rows": rows,
        "summary": {"n_devices": 1, "n_families": 7, "n_cells": 7},
    }


def _pad_snap(*, ospf=None, bgp=None, eigrp=None, states=None):
    host = "core1"
    routing = {"ospf": list(ospf or []), "bgp": list(bgp or []), "eigrp": list(eigrp or [])}
    inferred = {
        family: "assessed"
        for family, key in (("OSPF", "ospf"), ("BGP", "bgp"), ("EIGRP", "eigrp"))
        if routing[key]
    }
    inferred.update(states or {})
    return {
        "routing_neighbors": {host: routing},
        "protocol_assessability": _pad_receipt(host, inferred),
    }


def _ospf(peer, state="FULL/DR", interface="Po1"):
    return {"neighbor": peer, "state": state, "address": peer, "interface": interface}


def _bgp(peer, state="12", remote_as="65002"):
    return {"neighbor": peer, "state": state, "as": remote_as}


def _eigrp(peer, state="up 12", interface="Gi0/1"):
    return {"neighbor": peer, "state": state, "interface": interface}


def _protocol_delta_cases():
    unchanged = _pad_snap(ospf=[_ospf("10.0.0.2")])
    degraded = _pad_snap(ospf=[_ospf("10.0.0.2", "EXSTART/DROTHER")])
    bgp_before = _pad_snap(bgp=[_bgp("192.0.2.2", "12")])
    eigrp_before = _pad_snap(eigrp=[_eigrp("10.0.0.3", "up 12")])
    two_peers = _pad_snap(ospf=[_ospf("10.0.0.2"), _ospf("10.0.0.3", interface="Po2")])
    one_peer = _pad_snap(ospf=[_ospf("10.0.0.2")])
    no_peer = _pad_snap(ospf=[], states={"OSPF": "captured_no_record"})
    legacy_before = _pad_snap(ospf=[_ospf("10.0.0.2")])
    legacy_after = _pad_snap(ospf=[_ospf("10.0.0.2")])
    legacy_before.pop("protocol_assessability")
    legacy_after.pop("protocol_assessability")
    malformed_after = _pad_snap(ospf=[_ospf("10.0.0.2")])
    malformed_after["protocol_assessability"] = {
        "schema": "protocol_assessability/1",
        "rows": "not-a-row-list",
    }
    contradictory_receipt = _pad_snap(ospf=[_ospf("10.0.0.2")])
    next(
        row for row in contradictory_receipt["protocol_assessability"]["rows"]
        if row["protocol"] == "OSPF"
    )["health_row_emitted"] = False
    assessed_zero_projection = _pad_snap(ospf=[], states={"OSPF": "assessed"})
    ipv6_compressed = _pad_snap(bgp=[_bgp("2001:db8::2", "12")])
    ipv6_expanded = _pad_snap(bgp=[_bgp("2001:0db8:0000:0000:0000:0000:0000:0002", "37")])
    mapped_compressed = _pad_snap(bgp=[_bgp("::ffff:192.0.2.1", "12")])
    mapped_expanded = _pad_snap(bgp=[_bgp("0000:0000:0000:0000:0000:ffff:c000:0201", "37")])
    mixed_before = _pad_snap(ospf=[_ospf("10.0.0.2")], bgp=[_bgp("192.0.2.2")])
    mixed_after = _pad_snap(
        ospf=[_ospf("10.0.0.2", "EXSTART/DROTHER")],
        bgp=[],
        states={"BGP": "assessed"},
    )
    return {
        "unchanged": [unchanged, unchanged],
        "ospf_degraded": [unchanged, degraded],
        "ospf_two_way_acceptable": [unchanged, _pad_snap(ospf=[_ospf("10.0.0.2", "2WAY/DROTHER")])],
        "bgp_prefix_count_churn": [bgp_before, _pad_snap(bgp=[_bgp("192.0.2.2", "37")])],
        "bgp_idle_degraded": [bgp_before, _pad_snap(bgp=[_bgp("192.0.2.2", "Idle")])],
        "eigrp_uptime_churn": [eigrp_before, _pad_snap(eigrp=[_eigrp("10.0.0.3", "up 7")])],
        "eigrp_prefix_collision": [eigrp_before, _pad_snap(eigrp=[_eigrp("10.0.0.3", "upside-down")])],
        "metadata_changed": [unchanged, _pad_snap(ospf=[_ospf("10.0.0.2", interface="Po2")])],
        "one_peer_no_longer_observed": [two_peers, one_peer],
        "last_peer_coverage_gap": [one_peer, no_peer],
        "recovered": [degraded, unchanged],
        "added": [one_peer, two_peers],
        "legacy": [legacy_before, legacy_after],
        "malformed_receipt": [unchanged, malformed_after],
        "assessed_without_health_row": [unchanged, contradictory_receipt],
        "assessed_zero_projection": [assessed_zero_projection, assessed_zero_projection],
        "ipv6_text_form_churn": [ipv6_compressed, ipv6_expanded],
        "ipv4_mapped_ipv6_text_form_churn": [mapped_compressed, mapped_expanded],
        "regression_with_gap": [mixed_before, mixed_after],
    }


def _extract_reasoning_core():
    html = _html()
    match = re.search(r"REASONING-CORE-PORT START.*?REASONING-CORE-PORT END", html, re.S)
    assert match, "explorer is missing its executable reasoning-core markers"
    block = match.group(0)
    return block[block.index("*/") + 2:block.rindex("/*")]


@pytest.mark.skipif(not NODE, reason="node is not installed — protocol compare parity gate skipped")
def test_protocol_compare_js_matches_python_public_semantics(tmp_path):
    """Execute the offline comparator, not merely regex-check it.  Exact result
    equality holds state normalization, receipt failure behavior, gate precedence,
    qualifiers, and the embedded-unverified custody boundary to the Python owner."""
    from cisco_toolkit.html import compute_protocol_adjacency_delta

    cases = _protocol_delta_cases()
    expected = {
        name: compute_protocol_adjacency_delta(before, after)
        for name, (before, after) in cases.items()
    }
    payload = tmp_path / "protocol-cases.json"
    payload.write_text(json.dumps(cases), encoding="utf-8")
    driver = tmp_path / "protocol-driver.js"
    driver.write_text(
        _extract_reasoning_core()
        + "\nconst fs=require('fs');"
          "const cases=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));"
          "const out={};"
          "for(const [name,pair] of Object.entries(cases))"
          "out[name]=computeProtocolAdjacencyDelta(pair[0],pair[1]);"
          "process.stdout.write(JSON.stringify(out));\n",
        encoding="utf-8",
    )
    proc = subprocess.run([NODE, str(driver), str(payload)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, f"node execution of protocol comparator failed:\n{proc.stderr[:3000]}"
    assert json.loads(proc.stdout) == expected

    partial = expected["regression_with_gap"]
    assert partial["gate"] == "REGRESSED" and partial["assessed"] is False
    assert partial["summary"]["n_state_regressed"] == 1
    assert partial["summary"]["n_coverage_gaps"] == 1

    contradiction = expected["assessed_without_health_row"]
    assert contradiction["gate"] == "REVIEW" and contradiction["assessed"] is False
    assert "without an emitted health row" in contradiction["coverage_gaps"][0]["reason"]

    zero_projection = expected["assessed_zero_projection"]
    assert zero_projection["gate"] == "REVIEW" and zero_projection["assessed"] is False
    assert zero_projection["summary"]["n_coverage_gaps"] == 1
    assert "zero peers" in zero_projection["coverage_gaps"][0]["reason"]

    for name in ("ipv6_text_form_churn", "ipv4_mapped_ipv6_text_form_churn"):
        ipv6 = expected[name]
        assert ipv6["gate"] == "PASS" and ipv6["summary"]["n_preserved"] == 1
        assert ipv6["summary"]["n_added"] == ipv6["summary"]["n_no_longer_observed"] == 0

    eigrp_prefix = expected["eigrp_prefix_collision"]
    assert eigrp_prefix["gate"] == "REVIEW"
    assert eigrp_prefix["summary"]["n_state_regressed"] == 0
    assert eigrp_prefix["changes"][0]["result"] == "state_changed"


def test_protocol_compare_eigrp_up_state_is_anchored_not_prefix_matched():
    core = _extract_reasoning_core()
    assert r'/^up(?:\s+\S+)?$/i.test(text)' in core
    assert '{state:text.toUpperCase(),healthy:null}' in core
    assert 'startsWith("up")' not in core


def _baseline_item(index=1, *, state="assessed", wave="Group 1", expect="Observed baseline is available"):
    row = {
        "device": f"DIST-{index}",
        "platform": "ios",
        "wave": wave,
        "category": "Routing",
        "severity": "High",
        "check": f"OSPF observed adjacency baseline {index}",
        "command": "show ip ospf neighbor",
        "expect": expect,
        "why": "Preserve the observed routing baseline.",
        "projection_custody": "source_bound_embedded_unverified",
        "source_key": f"routing_neighbors.DIST-{index}.ospf",
    }
    if state is not None:
        row["evidence_state"] = state
    return row


def _baseline_plan(items):
    by_wave = {}
    by_category = {}
    for row in items:
        by_wave.setdefault(row["wave"], []).append(dict(row))
        by_category[row["category"]] = by_category.get(row["category"], 0) + 1
    return {
        "items": [dict(row) for row in items],
        "by_wave": by_wave,
        "summary": {
            "n_items": len(items),
            "n_waves": len(by_wave),
            "n_high": sum(row["severity"] in ("Critical", "High") for row in items),
            "by_category": by_category,
        },
        "banner": "Run after each wave.",
    }


def _current_baseline_cases():
    clear = _baseline_plan([_baseline_item(1), _baseline_item(2, wave="Group 2")])
    blocked = _baseline_plan([
        _baseline_item(1, state="degraded", expect=(
            "PRE-CUTOVER DEGRADED — BLOCKER: 10.0.0.2 EXSTART/DR. "
            "Matching this degraded state is NOT ACCEPTANCE."
        )),
        _baseline_item(2, state="review", wave="Group 10", expect=(
            "PRE-CUTOVER REVIEW — BLOCKER: peer identity requires live verification."
        )),
        _baseline_item(3, state="not_verified", wave="Group 2", expect=(
            "ROUTING BASELINE NOT VERIFIED — BLOCKER: re-collect before acceptance."
        )),
        _baseline_item(4, state="assessed", wave="Pilot"),
    ])
    legacy = _baseline_plan([_baseline_item(
        5, state=None, expect="PRE-CUTOVER REVIEW — BLOCKER: legacy FHRP identity ambiguity.",
    )])
    fhrp_legacy = _baseline_plan([_baseline_item(
        10, state=None, expect=(
            "FHRP CONFIGURED GROUP NOT VERIFIED — BLOCKER: re-collect subtype evidence."
        ),
    )])
    capped = _baseline_plan([
        _baseline_item(i, state="degraded", wave=f"Group {10 if i % 2 else 2}", expect=(
            "PRE-CUTOVER DEGRADED — BLOCKER: " + ("💥" * 620)
        ))
        for i in range(1, 56)
    ])
    conflict = _baseline_plan([_baseline_item(
        6, state="assessed", expect="PRE-CUTOVER DEGRADED — BLOCKER: contradictory typed state.",
    )])
    summary_mismatch = _baseline_plan([_baseline_item(7)])
    summary_mismatch["summary"]["n_items"] = 99
    bucket_mismatch = _baseline_plan([_baseline_item(8)])
    bucket_mismatch["by_wave"] = {"Group 2": [dict(bucket_mismatch["items"][0])]}
    non_text_state = _baseline_plan([_baseline_item(9)])
    non_text_state["items"][0]["evidence_state"] = ["degraded"]
    non_text_state["by_wave"]["Group 1"][0]["evidence_state"] = ["degraded"]
    return {
        "missing": None,
        "empty_object": {},
        "valid_empty": _baseline_plan([]),
        "clear": clear,
        "blocked_mixed_and_numeric_wave_sort": blocked,
        "legacy_marker": legacy,
        "fhrp_legacy_marker": fhrp_legacy,
        "fifty_row_cap_and_unicode_bounds": capped,
        "typed_marker_conflict": conflict,
        "summary_mismatch": summary_mismatch,
        "bucket_mismatch": bucket_mismatch,
        "non_text_state": non_text_state,
        "malformed_contract": "not-an-object",
    }


def test_explorer_compare_mounts_current_baseline_gate_before_delta_results():
    html = _html()
    set_compare = html[html.index("function setComparisonSnapshot(snapB)"):
                       html.index("/* ---- entry point", html.index("function setComparisonSnapshot(snapB)"))]
    assert "cmp.currentBaseline=computeCurrentBaselineGate(snapB)" in set_compare

    compare = html[html.index("function drawCompare()"):
                   html.index("/* ---- FLOW ----", html.index("function drawCompare()"))]
    assert compare.index("${currentBaselineCompareSection(c.currentBaseline)}") < compare.index(
        '<div class="stat ok"><div class="v">${c.improvements}'
    )

    section = html[html.index("function currentBaselineCompareSection(g)"):
                   html.index("function protocolCompareSection(p)")]
    assert "An unchanged blocker is still a blocker" in section
    assert "it is not cutover authorization" in section
    assert "observed baseline / acceptance" in section
    assert "projection_custody" in section and "source_key" in section
    assert "blockers.map(" in section
    assert "blockers.slice(" not in section, "returned blockers must not disappear behind a presentation cap"


@pytest.mark.skipif(not NODE, reason="node is not installed — current-baseline parity gate skipped")
def test_current_baseline_gate_js_matches_python_public_semantics(tmp_path):
    from cisco_toolkit.analyze import compute_current_baseline_gate

    cases = _current_baseline_cases()
    expected = {name: compute_current_baseline_gate(plan) for name, plan in cases.items()}
    payload = tmp_path / "baseline-cases.json"
    payload.write_text(json.dumps(cases), encoding="utf-8")
    driver = tmp_path / "baseline-driver.js"
    driver.write_text(
        _extract_reasoning_core()
        + "\nconst fs=require('fs');"
          "const cases=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));"
          "const out={};"
          "for(const [name,plan] of Object.entries(cases))out[name]=computeCurrentBaselineGate(plan);"
          "process.stdout.write(JSON.stringify(out));\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [NODE, str(driver), str(payload)], capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert proc.returncode == 0, f"node execution of current-baseline gate failed:\n{proc.stderr[:3000]}"
    actual = json.loads(proc.stdout)
    assert actual == expected

    assert actual["blocked_mixed_and_numeric_wave_sort"]["verdict"] == "BLOCKED"
    assert actual["fhrp_legacy_marker"]["verdict"] == "INDETERMINATE"
    assert actual["fhrp_legacy_marker"]["summary"]["by_state"]["not_verified"] == 1
    assert list(actual["blocked_mixed_and_numeric_wave_sort"]["summary"]["by_wave"]) == [
        "Group 1", "Group 2", "Group 10",
    ]
    assert actual["fifty_row_cap_and_unicode_bounds"]["summary"]["n_blockers"] == 55
    assert actual["fifty_row_cap_and_unicode_bounds"]["summary"]["n_blockers_returned"] == 50
    assert actual["fifty_row_cap_and_unicode_bounds"]["summary"]["blockers_capped"] is True
    for name in ("typed_marker_conflict", "summary_mismatch", "bucket_mismatch", "non_text_state"):
        assert actual[name]["verdict"] == "INDETERMINATE"
        assert actual[name]["blockers"] == []
        assert actual[name]["summary"]["n_blockers"] == 0


def _extract_current_baseline_workflow():
    html = _html()
    return html[
        html.index("function currentBaselineWorkflowState(waveData)"):
        html.index("function wavesValidationBlock(wave)")
    ]


@pytest.mark.skipif(not NODE, reason="node is not installed — current-baseline workflow gate skipped")
def test_explorer_waves_holds_for_uncapped_unscheduled_baseline_blockers(tmp_path):
    blockers = [
        {
            **_baseline_item(i, state="degraded", wave="(unscheduled)", expect=(
                f"PRE-CUTOVER DEGRADED — BLOCKER: unscheduled baseline {i}."
            )),
            "device": f"EDGE-UNSCHEDULED-{i}",
            "check": f"UNBOUND-CURRENT-BASELINE-{i}",
        }
        for i in range(1, 53)
    ]
    plan = _baseline_plan(blockers)
    payload = tmp_path / "waves-current-baseline.json"
    payload.write_text(json.dumps(plan), encoding="utf-8")
    driver = tmp_path / "waves-current-baseline.js"
    driver.write_text(
        _extract_reasoning_core()
        + "\nfunction esc(v){return String(v??'');} function shortName(v){return String(v??'');}"
          "const fs=require('fs');const SNAP={validation_plan:JSON.parse(fs.readFileSync(process.argv[2],'utf8'))};\n"
        + _extract_current_baseline_workflow()
        + "\nconst state=currentBaselineWorkflowState([{idx:0,g:{switches:['DIST-CORE']}}]);"
          "const panel=currentBaselineWorkflowPanel(state);"
          "process.stdout.write(JSON.stringify({verdict:state.gate.verdict,unbound:state.unbound.length,panel}));\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [NODE, str(driver), str(payload)], capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert proc.returncode == 0, proc.stderr[:3000]
    actual = json.loads(proc.stdout)
    assert actual["verdict"] == "BLOCKED" and actual["unbound"] == 52
    assert "HOLD — current baseline BLOCKED" in actual["panel"]
    assert "all 52 unbound blocker(s) are retained" in actual["panel"]
    assert "UNBOUND-CURRENT-BASELINE-1" in actual["panel"]
    assert "UNBOUND-CURRENT-BASELINE-52" in actual["panel"]

    draw = _html()[_html().index("function drawWaves()"):_html().index("function paintWaves()")]
    assert 'baselineWorkflow.gate.verdict==="CLEAR"' in draw
    assert "this group is not clear to schedule" in draw
    assert "this group is clear to schedule" not in draw
    workflow = _extract_current_baseline_workflow()
    assert "unbound.map(" in workflow and "unbound.slice(" not in workflow


@pytest.mark.skipif(not NODE, reason="node is not installed — unchanged-degraded compare gate skipped")
def test_unchanged_ospf_exstart_is_delta_pass_but_current_baseline_blocked(tmp_path):
    """Unchanged degradation is intentionally not called a new regression, but it can
    never disappear from the current-state acceptance decision."""
    from cisco_toolkit.analyze import compute_current_baseline_gate
    from cisco_toolkit.html import compute_protocol_adjacency_delta

    unchanged = _pad_snap(ospf=[_ospf("10.0.0.2", "EXSTART/DR")])
    plan = _baseline_plan([_baseline_item(
        1, state="degraded", expect=(
            "PRE-CUTOVER DEGRADED — BLOCKER: 10.0.0.2 EXSTART/DR → 10.0.0.2 EXSTART/DR. "
            "Matching this degraded state is NOT ACCEPTANCE."
        ),
    )])
    payload = tmp_path / "unchanged-degraded.json"
    payload.write_text(json.dumps({"before": unchanged, "after": unchanged, "plan": plan}), encoding="utf-8")
    driver = tmp_path / "unchanged-degraded.js"
    driver.write_text(
        _extract_reasoning_core()
        + "\nconst fs=require('fs');"
          "const p=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));"
          "process.stdout.write(JSON.stringify({"
          "delta:computeProtocolAdjacencyDelta(p.before,p.after),"
          "current:computeCurrentBaselineGate(p.plan)}));\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [NODE, str(driver), str(payload)], capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert proc.returncode == 0, proc.stderr[:3000]
    actual = json.loads(proc.stdout)
    assert actual["delta"] == compute_protocol_adjacency_delta(unchanged, unchanged)
    assert actual["current"] == compute_current_baseline_gate(plan)
    assert actual["delta"]["gate"] == "PASS"
    assert actual["delta"]["summary"]["n_state_regressed"] == 0
    assert actual["current"]["verdict"] == "BLOCKED"
    assert actual["current"]["blockers"][0]["evidence_state"] == "degraded"
