"""Cross-language contract for the Master Reference protocol-depth workspace.

The browser-facing matrix is a derived navigation view.  These tests bind its
finite denominator and advice claims back to the Python engine owners so the
JSON cannot silently drift into a second protocol-support authority.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from cisco_toolkit import (
    analyze,
    bgp_intent,
    fhrp_intent,
    fhrp_redundancy,
    ipv6_routing,
    protocol_kb,
    vtp_safety,
)
from cisco_toolkit.analyze import (
    _EC_ADVISORY_FLAGS,
    _extract_protocol_states,
    PROTOCOL_ASSESSABILITY_FAMILIES,
    compute_protocol_intelligence,
)


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_DEPTH_PATH = ROOT / "master-reference" / "app" / "atlas" / "protocol-depth.json"
ATLAS_CORE_PATH = ROOT / "master-reference" / "content" / "atlas-core.json"
CAPABILITY_CATALOG_PATH = ROOT / "master-reference" / "content" / "capability-catalog.json"

EXPECTED_HEALTH_FAMILIES = (
    "STP",
    "EtherChannel",
    "VTP",
    "OSPF",
    "BGP",
    "EIGRP",
    "FHRP",
)
EXPECTED_FAMILIES = EXPECTED_HEALTH_FAMILIES + ("IPv6 Routing",)
EXPECTED_STAGES = (
    "collection",
    "parsing",
    "normalization",
    "assessment",
    "design-advice",
    "simulation",
    "validation",
    "output",
)
EXPECTED_CAPABILITY_BY_FAMILY = {
    "STP": "cap.protocol.stp",
    "EtherChannel": "cap.protocol.etherchannel-lacp-pagp",
    "VTP": "cap.protocol.vtp",
    "OSPF": "cap.protocol.ospf",
    "BGP": "cap.protocol.bgp",
    "EIGRP": "cap.protocol.eigrp",
    "FHRP": "cap.protocol.fhrp",
    "IPv6 Routing": "cap.protocol.ipv6-nd-routing",
}


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), f"{path.relative_to(ROOT)} must contain one JSON object"
    return value


def _one(records: list[dict], identifier: str) -> dict:
    matches = [record for record in records if record.get("id") == identifier]
    assert len(matches) == 1, f"expected exactly one {identifier!r} record, found {len(matches)}"
    return matches[0]


def test_protocol_depth_binds_the_exact_baseline_stage_and_capability_denominators():
    depth = _load(PROTOCOL_DEPTH_PATH)
    core = _load(ATLAS_CORE_PATH)
    catalog = _load(CAPABILITY_CATALOG_PATH)

    denominator = depth["denominator"]
    baseline = _one(core["current_baseline"], denominator["baseline_ref"])
    protocol_domain = _one(catalog["domains"], denominator["catalog_domain_ref"])
    catalog_capability_ids = {entry["id"] for entry in protocol_domain["entries"]}
    families = depth["families"]

    # The owner baseline is intentionally repeated here as an exact regression
    # contract: adding a family is scope growth and must update both owners.
    assert tuple(baseline["value"]) == EXPECTED_HEALTH_FAMILIES
    assert tuple(family["protocol"] for family in PROTOCOL_ASSESSABILITY_FAMILIES) == EXPECTED_HEALTH_FAMILIES
    assert tuple(family["health_label"] for family in families) == EXPECTED_FAMILIES
    assert denominator["health_family_count"] == len(EXPECTED_HEALTH_FAMILIES) == 7
    assert denominator["family_count"] == len(families) == 8

    assert tuple(stage["id"] for stage in depth["stages"]) == EXPECTED_STAGES
    assert tuple(stage["order"] for stage in depth["stages"]) == tuple(range(1, 9))
    assert denominator["stage_count"] == len(depth["stages"]) == 8
    assert denominator["cell_count"] == sum(len(family["cells"]) for family in families) == 64

    assert denominator["catalog_cell_count"] == len(protocol_domain["entries"]) == 38
    assert {
        family["health_label"]: family["capability_ref"] for family in families
    } == EXPECTED_CAPABILITY_BY_FAMILY
    for family in families:
        assert tuple(family["cells"]) == EXPECTED_STAGES, (
            f"{family['health_label']} must carry each exact stage once and in canonical order"
        )
        assert family["capability_ref"] in catalog_capability_ids


def test_protocol_depth_assessment_and_output_cells_bind_the_runtime_receipt():
    depth = _load(PROTOCOL_DEPTH_PATH)
    witness = _one(depth["witnesses"], "witness.protocol.assessability")
    assert witness["path"] == "cisco_toolkit/analyze.py"
    assert set(witness["symbols"]) == {
        "PROTOCOL_ASSESSABILITY_FAMILIES", "compute_protocol_assessability"
    }
    assert witness["test_refs"] == ["tests/test_protocol_assessability.py"]

    for family in depth["families"]:
        if family["health_label"] not in EXPECTED_HEALTH_FAMILIES:
            continue
        for stage in ("assessment", "output"):
            assert "witness.protocol.assessability" in family["cells"][stage]["witness_refs"], (
                f"{family['health_label']} {stage} must disclose its current-run denominator"
            )


def test_stp_validation_binds_the_shared_consistency_truth_and_operator_hold():
    depth = _load(PROTOCOL_DEPTH_PATH)
    witness = _one(depth["witnesses"], "witness.protocol.stp-consistency-baseline")
    assert witness["path"] == "cisco_toolkit/analyze.py"
    assert witness["symbols"] == [
        "summarize_stp_consistency_baseline",
        "compute_migration_readiness",
        "compute_validation_plan",
        "compute_current_baseline_gate",
    ]
    assert witness["test_refs"] == [
        "tests/test_stp_consistency_truth.py",
        "tests/test_stp_validation_surfaces.py",
    ]
    for symbol in witness["symbols"]:
        assert callable(getattr(analyze, symbol))

    stp = next(family for family in depth["families"] if family["health_label"] == "STP")
    validation = stp["cells"]["validation"]
    assert {
        "witness.protocol.assessability",
        "witness.protocol.stp-consistency-baseline",
        "witness.protocol.current-baseline-gate",
        "witness.protocol.nrfu",
    } <= set(validation["witness_refs"])
    assert "state and inconsistent_ports inputs are usable" in validation["prerequisite"]
    assert "exactly one matching well-formed STP health row" in validation["prerequisite"]
    assert "blocked_ports is a separate observed/not-collected disclosure" in validation["prerequisite"]
    assert "topology_changes/detail is optional" in validation["prerequisite"]
    assert "prevents a migration-readiness pass" in validation["boundary"]
    assert "typed Cutover Validation blocker" in validation["boundary"]
    assert "current-baseline workflow on HOLD" in validation["boundary"]
    assert "unchanged blocker" in validation["boundary"] and "clean delta" in validation["boundary"]
    assert "Missing blockedports evidence is never rendered as zero blocked" in validation["boundary"]
    assert "Clean no-subject hosts are omitted without an applicability or health claim" in validation["boundary"]
    assert "configured-STP applicability" in validation["boundary"]
    assert "complete VLAN/MST-instance" in validation["boundary"]

    output_refs = set(stp["cells"]["output"]["witness_refs"])
    assert {
        "witness.protocol.stp-consistency-baseline",
        "witness.protocol.current-baseline-gate",
        "witness.protocol.nrfu",
        "witness.protocol.output.excel",
        "witness.protocol.output.runbook",
        "witness.protocol.output.explorer",
        "witness.protocol.output.current-baseline-workflow",
    } <= output_refs

    nrfu = _one(depth["witnesses"], "witness.protocol.nrfu")
    assert nrfu["path"] == "cisco_toolkit/nrfu_export.py"
    assert nrfu["symbols"] == ["compute_nrfu_commands"]
    assert "shared consistency baseline" in nrfu["proves"]
    assert "tests/test_stp_nrfu_truth.py" in nrfu["test_refs"]


def test_protocol_workspace_shows_the_stp_consistency_scope_notice():
    component = (
        ROOT / "master-reference" / "app" / "atlas" / "ProtocolDepthExplorer.tsx"
    ).read_text(encoding="utf-8")
    assert "data-runtime-stp-consistency-contract" in component
    assert "STP consistency cutover contract" in component
    assert "usable <code>state</code>" in component
    assert "<code>inconsistent_ports</code> inputs" in component
    assert "exactly one matching, well-formed STP health row" in component
    assert "<code>blocked_ports</code> is disclosed" in component
    assert "missing evidence is never rendered as zero blocked" in component
    assert "<code>topology_changes</code>/detail is optional" in component
    assert "clean no-subject host is omitted without a" in component
    assert "configured STP applicability" in component


def test_etherchannel_validation_cell_binds_the_shared_receipt_gated_baseline():
    depth = _load(PROTOCOL_DEPTH_PATH)
    witness = _one(depth["witnesses"], "witness.protocol.etherchannel-baseline")
    assert witness["path"] == "cisco_toolkit/analyze.py"
    assert witness["symbols"] == [
        "compute_etherchannel_projection", "summarize_etherchannel_baseline",
    ]
    assert witness["test_refs"] == ["tests/test_etherchannel_cutover_truth.py"]

    etherchannel = next(
        family for family in depth["families"] if family["health_label"] == "EtherChannel"
    )
    validation = etherchannel["cells"]["validation"]
    assert "witness.protocol.etherchannel-baseline" in validation["witness_refs"]
    assert "protocol_assessability/1 receipt cell is assessed" in validation["prerequisite"]
    assert "PRE-CUTOVER DEGRADED — BLOCKER" in validation["boundary"]
    assert "matching a degraded baseline is not acceptance" in validation["boundary"]
    assert "projection custody remains embedded_unverified" in validation["boundary"]
    assert "complete configured-bundle" in validation["boundary"]


def test_routing_output_cells_bind_the_observed_adjacency_change_gate():
    depth = _load(PROTOCOL_DEPTH_PATH)
    witness = _one(depth["witnesses"], "witness.protocol.adjacency-delta")
    assert witness["path"] == "cisco_toolkit/html.py"
    assert witness["symbols"] == ["compute_protocol_adjacency_delta", "compute_snapshot_delta"]
    assert witness["test_refs"] == ["tests/test_protocol_adjacency_delta.py"]

    for family in depth["families"]:
        refs = family["cells"]["output"]["witness_refs"]
        if family["health_label"] in {"OSPF", "BGP", "EIGRP"}:
            assert "witness.protocol.adjacency-delta" in refs
        else:
            assert "witness.protocol.adjacency-delta" not in refs


def test_current_baseline_gate_prevents_an_unchanged_blocker_from_becoming_acceptance():
    depth = _load(PROTOCOL_DEPTH_PATH)
    witness = _one(depth["witnesses"], "witness.protocol.current-baseline-gate")
    assert witness["path"] == "cisco_toolkit/analyze.py"
    assert witness["symbols"] == ["compute_current_baseline_gate"]
    assert witness["test_refs"] == [
        "tests/test_current_baseline_gate.py",
        "tests/test_compare_cutover_gate_cli.py",
    ]

    for health_label in (
        "STP", "EtherChannel", "OSPF", "BGP", "EIGRP", "FHRP", "IPv6 Routing",
    ):
        family = next(
            item for item in depth["families"] if item["health_label"] == health_label
        )
        validation = family["cells"]["validation"]
        assert "witness.protocol.current-baseline-gate" in validation["witness_refs"]
        assert "unchanged blocker" in validation["boundary"]
        assert "clean delta" in validation["boundary"]


def test_protocol_depth_advice_cells_cover_the_live_protocol_doctrine():
    depth = _load(PROTOCOL_DEPTH_PATH)
    family_by_health = {family["health_label"]: family for family in depth["families"]}
    kb_states: dict[str, set[str]] = defaultdict(set)
    for protocol, state in protocol_kb._PROTOCOL_STATES:
        kb_states[protocol].add(state)

    # Every doctrine-bearing engine family is represented, while EIGRP remains
    # visibly missing rather than gaining advice from catalog presence alone.
    assert set(kb_states) == set(EXPECTED_HEALTH_FAMILIES) - {"EIGRP"}
    assert {
        family["health_label"]
        for family in depth["families"]
        if family["cells"]["design-advice"]["state"] == "missing"
    } == {"EIGRP", "IPv6 Routing"}

    for health_label in EXPECTED_HEALTH_FAMILIES:
        family = family_by_health[health_label]
        listed = family["advice_states"]
        assert len(listed) == len(set(listed)), f"{health_label} repeats an advice state"
        listed_states = set(listed)
        owned_doctrine = kb_states.get(health_label, set())
        assert owned_doctrine <= listed_states, (
            f"{health_label} omits protocol_kb states {sorted(owned_doctrine - listed_states)}"
        )

        extras = listed_states - owned_doctrine
        if health_label == "EtherChannel":
            # Every health-to-intelligence token is now owned by protocol_kb; the
            # reference must not retain the former M/f NOT ASSESSED fallback gap.
            assert extras == set(_EC_ADVISORY_FLAGS) - owned_doctrine == set()
        else:
            assert extras == set(), f"{health_label} claims non-doctrine advice states {sorted(extras)}"

        advice_cell = family["cells"]["design-advice"]
        if owned_doctrine:
            assert advice_cell["state"] == "partial"
            assert {
                "witness.protocol.intelligence",
                "witness.protocol.doctrine",
            } <= set(advice_cell["witness_refs"])
        else:
            assert listed_states == set()
            assert advice_cell["state"] == "missing"
            assert advice_cell["witness_refs"] == []


def test_fhrp_advice_retains_hsrp_specific_tokens_and_never_borrows_the_doctrine():
    depth = _load(PROTOCOL_DEPTH_PATH)
    fhrp = next(family for family in depth["families"] if family["health_label"] == "FHRP")
    hsrp_doctrine = {
        state for protocol, state in protocol_kb._PROTOCOL_STATES if protocol == "FHRP"
    }

    assert hsrp_doctrine == set(fhrp["advice_states"]) == {"HSRP:INIT", "HSRP:LEARN"}
    assert protocol_kb.advise("FHRP", "VRRP:INIT") is None
    assert protocol_kb.advise("FHRP", "GLBP:LEARN") is None

    detail = "Vlan10 HSRP Init; Vlan20 HSRP Learn; Vlan30 VRRP Init; Vlan40 GLBP Learn"
    tokens = _extract_protocol_states("FHRP", "", detail)
    assert tokens == ["GLBP:LEARN", "HSRP:INIT", "HSRP:LEARN", "VRRP:INIT"]

    records = compute_protocol_intelligence(
        [{"switch": "edge1", "protocol": "FHRP", "summary": "", "detail": detail}]
    )
    by_state = {record["state"]: record for record in records}
    assert set(by_state) == set(tokens)
    for token in hsrp_doctrine:
        assert "NOT ASSESSED" not in by_state[token]["likely_cause"]
        assert "Inferred" in by_state[token]["confidence"]
    for token in {"VRRP:INIT", "GLBP:LEARN"}:
        assert "NOT ASSESSED" in by_state[token]["likely_cause"]
        assert "NOT ASSESSED" not in by_state[token]["remediation"]


def test_vtp_cells_bind_the_safety_owner_heuristic_custody_and_operator_projection():
    depth = _load(PROTOCOL_DEPTH_PATH)
    witness = _one(depth["witnesses"], "witness.protocol.vtp-safety")
    assert witness["path"] == "cisco_toolkit/vtp_safety.py"
    assert witness["symbols"] == [
        "compute_vtp_safety_baseline",
        "validate_vtp_safety_baseline",
        "embedded_vtp_safety_baseline",
        "compute_vtp_safety_subject_scope",
        "scope_vtp_safety_subjects",
    ]
    assert witness["test_refs"] == [
        "tests/test_vtp_safety_baseline.py",
        "tests/test_vtp_operator_surfaces.py",
    ]
    for symbol in witness["symbols"]:
        assert callable(getattr(vtp_safety, symbol))
    assert "summary.by_status" in witness["proves"]
    assert "summary.by_coverage_status" in witness["proves"]
    assert "conservative REVIEW heuristic" in witness["proves"]
    assert "not proof that overwrite or propagation will occur" in witness["proves"]
    assert "NOT ACCEPTANCE" in witness["proves"]
    assert "embedded_unverified" in witness["proves"]

    vtp = next(family for family in depth["families"] if family["health_label"] == "VTP")
    for stage in ("collection", "parsing", "normalization", "assessment", "validation", "output"):
        assert "witness.protocol.vtp-safety" in vtp["cells"][stage]["witness_refs"]
    assert vtp["cells"]["assessment"]["state"] == "partial"
    assert vtp["cells"]["validation"]["state"] == "partial"
    assert "summary.by_coverage_status" in vtp["cells"]["assessment"]["prerequisite"]
    assert "threshold heuristic" in vtp["cells"]["assessment"]["boundary"]
    assert "matching it is NOT ACCEPTANCE" in vtp["cells"]["assessment"]["boundary"]
    assert "every REVIEW and NOT VERIFIED row plus the first 50 assessed rows" in (
        vtp["cells"]["output"]["prerequisite"]
    )
    assert "current_run_source_bound JSON fails closed" in vtp["cells"]["output"]["boundary"]
    combined = json.dumps(vtp, sort_keys=True)
    for exclusion in (
        "VLAN-database equality", "contents", "propagation", "version", "pruning",
        "password/authentication", "revision-reset", "cutover authorization",
    ):
        assert exclusion in combined

    excel = _one(depth["witnesses"], "witness.protocol.output.excel")
    runbook = _one(depth["witnesses"], "witness.protocol.output.runbook")
    explorer = _one(depth["witnesses"], "witness.protocol.output.explorer")
    assert "write_vtp_safety_sheet" in excel["symbols"]
    assert "vtp_safety_baseline" in runbook["symbols"]
    for symbol in (
        "vtpSafetyReceiptValid", "vtpSafetySection", "vtpSafetyCoverageStats",
        "vtpSafetyCoverageRows",
    ):
        assert symbol in explorer["symbols"]

    component = (
        ROOT / "master-reference" / "app" / "atlas" / "ProtocolDepthExplorer.tsx"
    ).read_text(encoding="utf-8")
    assert "data-runtime-vtp-safety-contract" in component
    assert "VTP safety gate — observed local status" in component
    assert "conservative REVIEW heuristic" in component
    assert "not proof that an overwrite or" in component
    assert "matching it is NOT ACCEPTANCE" in component
    assert "serialized <code>current_run_source_bound</code> claim is rejected" in component
    assert "first 50 assessed subjects" in component
    assert "VLAN-database equality or contents" in component
    assert "password/authentication" in component


def test_bgp_cells_bind_the_configured_peer_gate_and_keep_the_family_partial():
    depth = _load(PROTOCOL_DEPTH_PATH)
    witness = _one(depth["witnesses"], "witness.protocol.bgp-configured-peer")
    assert witness["path"] == "cisco_toolkit/bgp_intent.py"
    assert witness["symbols"] == [
        "compute_bgp_configured_peer_baseline",
        "validate_bgp_configured_peer_baseline",
    ]
    assert witness["test_refs"] == ["tests/test_bgp_configured_peer_baseline.py"]
    assert callable(bgp_intent.compute_bgp_configured_peer_baseline)
    assert callable(bgp_intent.validate_bgp_configured_peer_baseline)
    assert "summary.by_coverage_status" in witness["proves"]
    assert "coverage rows reserved for host detail" in witness["proves"]

    bgp = next(family for family in depth["families"] if family["health_label"] == "BGP")
    for stage in ("collection", "assessment", "validation", "output"):
        assert "witness.protocol.bgp-configured-peer" in bgp["cells"][stage]["witness_refs"]
    assert bgp["cells"]["assessment"]["state"] == "partial"
    assert bgp["cells"]["validation"]["state"] == "partial"
    assert "configured-active literal peer absent from a usable summary" in bgp["cells"]["validation"]["boundary"]
    assert "observed-peer-only comparison" in bgp["cells"]["validation"]["boundary"]
    assert "summary.by_coverage_status" in bgp["cells"]["assessment"]["prerequisite"]
    assert "summary.by_status" in bgp["cells"]["assessment"]["boundary"]
    assert "missing, extra, boolean, negative, or non-reconciling" in bgp["cells"]["validation"]["boundary"]
    assert "coverage rows are host detail only" in bgp["cells"]["output"]["prerequisite"]
    assert (
        "NOT_APPLICABLE means no in-scope literal peer subject was identified; it is not proof "
        "that BGP is absent or that configuration coverage is complete."
    ) in bgp["cells"]["output"]["boundary"]

    combined = json.dumps(bgp, sort_keys=True)
    for exclusion in (
        "VRFs", "IPv6", "VPNv4/EVPN", "peer groups/templates", "dynamic peers",
        "policy", "routes", "best path", "RPKI", "convergence",
    ):
        assert exclusion in combined


def test_protocol_workspace_shows_the_configured_bgp_scope_notice_and_output_writers():
    depth = _load(PROTOCOL_DEPTH_PATH)
    component = (
        ROOT / "master-reference" / "app" / "atlas" / "ProtocolDepthExplorer.tsx"
    ).read_text(encoding="utf-8")
    assert "data-runtime-bgp-configured-peer-contract" in component
    assert "Configured BGP peer gate — default/global IPv4 unicast" in component
    assert "summary.by_status" in component
    assert "summary.by_coverage_status" in component
    assert "coverage[]" in component
    assert (
        "NOT_APPLICABLE means no in-scope literal peer subject was identified; it is not proof that BGP"
        in component
    )
    for exclusion in (
        "VRFs", "IPv6", "VPNv4/EVPN", "peer groups/templates", "dynamic peers",
        "policy", "routes", "best path", "RPKI", "convergence",
    ):
        assert exclusion in component

    excel = _one(depth["witnesses"], "witness.protocol.output.excel")
    runbook = _one(depth["witnesses"], "witness.protocol.output.runbook")
    explorer = _one(depth["witnesses"], "witness.protocol.output.explorer")
    assert "write_bgp_configured_peer_sheet" in excel["symbols"]
    assert "bgp_configured_peer_baseline" in runbook["symbols"]
    assert "bgpConfiguredPeerSection" in explorer["symbols"]
    assert "bgpConfiguredCoverageStats" in explorer["symbols"]
    assert "bgpConfiguredPeerCoverageRows" in explorer["symbols"]


def test_ipv6_routing_family_binds_separate_owner_census_custody_and_direct_outputs():
    depth = _load(PROTOCOL_DEPTH_PATH)
    witness = _one(depth["witnesses"], "witness.protocol.ipv6-routing-adjacency")
    assert witness["path"] == "cisco_toolkit/ipv6_routing.py"
    assert witness["symbols"] == [
        "compute_ipv6_routing_adjacency_baseline",
        "validate_ipv6_routing_adjacency_baseline",
        "embedded_ipv6_routing_adjacency_baseline",
        "compute_ipv6_routing_subject_scope",
    ]
    assert witness["test_refs"] == [
        "tests/test_ipv6_routing_adjacency_baseline.py",
        "tests/test_ipv6_routing_operator_surfaces.py",
    ]
    for symbol in witness["symbols"]:
        assert callable(getattr(ipv6_routing, symbol))
    assert "three route-summary/OSPFv3/BGPv6 coverage cells" in witness["proves"]
    assert "summary.by_status" in witness["proves"]
    assert "summary.by_coverage_status alone owns" in witness["proves"]
    assert "embedded_unverified" in witness["proves"]
    assert "serialized current_run_source_bound claim" in witness["proves"]

    parser = _one(depth["witnesses"], "witness.protocol.parser.ipv6-routing")
    assert parser["path"] == "cisco_toolkit/parse.py"
    assert parser["symbols"] == [
        "parse_ipv6_route_summary", "parse_ospfv3_neighbors", "parse_bgp_ipv6_summary",
    ]

    family = next(
        item for item in depth["families"] if item["id"] == "protocol.ipv6-routing"
    )
    assert family["health_label"] == "IPv6 Routing"
    assert family["capability_ref"] == "cap.protocol.ipv6-nd-routing"
    assert family["cells"]["assessment"]["state"] == "partial"
    assert family["cells"]["validation"]["state"] == "partial"
    assert family["cells"]["output"]["state"] == "covered"
    for stage in ("collection", "parsing", "normalization", "assessment", "validation", "output"):
        assert "witness.protocol.ipv6-routing-adjacency" in family["cells"][stage]["witness_refs"]
    assert "witness.protocol.assessability" not in json.dumps(family, sort_keys=True)
    assert "summary.by_coverage_status" in family["cells"]["assessment"]["prerequisite"]
    assert "No configured/expected-peer denominator" in family["cells"]["assessment"]["boundary"]
    assert "matching a degraded state is NOT ACCEPTANCE" in family["cells"]["assessment"]["boundary"]
    assert "protocol_adjacency_delta/1 owner remains IPv4 OSPF/BGP/EIGRP-only" in (
        family["cells"]["validation"]["boundary"]
    )
    output = family["cells"]["output"]
    assert "Workbook and runbook retain every degraded, review, and not-verified row" in (
        output["prerequisite"]
    )
    assert "Explorer initially renders at most 200 blocker rows" in output["prerequisite"]
    assert "reports exact rendered/total/omitted counts" in output["prerequisite"]
    assert "exports every validated blocker row" in output["prerequisite"]
    assert "exact observed peer/state" in output["prerequisite"]
    assert "serialized current_run_source_bound receipts fail closed" in output["boundary"]
    for excluded in (
        "configured/expected peers", "VRF/other-AF", "route/prefix correctness",
        "RIB/FIB/path selection", "policy/best path", "convergence", "freshness",
        "simultaneity", "interoperability", "cutover authorization",
    ):
        assert excluded in json.dumps(family, sort_keys=True)

    excel = _one(depth["witnesses"], "witness.protocol.output.excel")
    runbook = _one(depth["witnesses"], "witness.protocol.output.runbook")
    explorer = _one(depth["witnesses"], "witness.protocol.output.explorer")
    assert "write_ipv6_routing_adjacency_sheet" in excel["symbols"]
    assert "ipv6_routing_adjacency_baseline" in runbook["symbols"]
    for symbol in (
        "ipv6RoutingAdjacencyReceiptValid", "ipv6RoutingAdjacencySection",
        "ipv6RoutingAdjacencyCoverageStats", "ipv6RoutingAdjacencyCoverageRows",
        "ipv6RoutingAdjacencyBlockerExportRows",
        "exportIpv6RoutingAdjacencyBlockers",
    ):
        assert symbol in explorer["symbols"]

    component = (
        ROOT / "master-reference" / "app" / "atlas" / "ProtocolDepthExplorer.tsx"
    ).read_text(encoding="utf-8")
    assert "data-runtime-ipv6-routing-adjacency-contract" in component
    assert "IPv6 routing adjacency gate — observed default/global runtime" in component
    assert "summary.by_status" in component and "summary.by_coverage_status" in component
    assert "host-family/input drilldown" in component
    assert "coverage-only host visible" in component
    assert "matching a degraded state is NOT ACCEPTANCE" in component
    assert "serialized <code>current_run_source_bound</code> claim" in component
    assert "Workbook and runbook retain every blocker plus the first 50 assessed" in component
    assert "Explorer initially renders at most 200 blockers" in component
    assert "reports exact" in component and "rendered/total/omitted counts" in component
    assert "exports every validated blocker row" in component
    assert "exact observed peer/state" in component
    assert "never render raw" in component and "SHA values" in component
    assert "does not yet include the separately owned OSPFv3/BGPv6 receipt" in component
    assert "current-state" in component and "shared current-baseline gate" in component


def test_fhrp_cells_bind_the_configured_group_gate_and_keep_denominators_distinct():
    depth = _load(PROTOCOL_DEPTH_PATH)
    witness = _one(depth["witnesses"], "witness.protocol.fhrp-configured-group")
    assert witness["path"] == "cisco_toolkit/fhrp_intent.py"
    assert witness["symbols"] == [
        "compute_fhrp_configured_group_baseline",
        "validate_fhrp_configured_group_baseline",
    ]
    assert witness["test_refs"] == [
        "tests/test_fhrp_configured_group_baseline.py",
        "tests/test_fhrp_election_reconciliation.py",
        "tests/test_fhrp_decision_consumer_parity.py",
        "tests/test_fhrp_configured_group_operator_surfaces.py",
        "tests/test_fhrp_election_operator_surfaces.py",
    ]
    assert callable(fhrp_intent.compute_fhrp_configured_group_baseline)
    assert callable(fhrp_intent.validate_fhrp_configured_group_baseline)
    assert "three-cells-per-host" in witness["proves"]
    assert "summary.by_status" in witness["proves"]
    assert "summary.by_coverage_status" in witness["proves"]
    assert "exact default/IPv4 + subtype + normalized interface + group" in witness["proves"]
    assert "sequential election-consistency review" in witness["proves"]
    assert "not proof of simultaneous election health" in witness["proves"]
    assert "does not infer expected peers or member count" in witness["proves"]

    fhrp = next(family for family in depth["families"] if family["health_label"] == "FHRP")
    for stage in ("collection", "normalization", "assessment", "validation", "output"):
        assert "witness.protocol.fhrp-configured-group" in fhrp["cells"][stage]["witness_refs"]
    assert fhrp["cells"]["assessment"]["state"] == "partial"
    assert fhrp["cells"]["validation"]["state"] == "partial"
    assert "configured-active local group absent from usable subtype runtime evidence" in (
        fhrp["cells"]["validation"]["boundary"]
    )
    assert "three-cells-per-host" in fhrp["cells"]["validation"]["prerequisite"]
    assert "summary.by_status" in fhrp["cells"]["assessment"]["boundary"]
    assert "summary.by_coverage_status" in fhrp["cells"]["assessment"]["prerequisite"]
    assert "coverage rows are host detail only" in fhrp["cells"]["output"]["prerequisite"]
    assert "unbound blockers as (unscheduled)" in fhrp["cells"]["validation"]["boundary"]
    assert "election_no_leader_observed" in fhrp["cells"]["assessment"]["boundary"]
    assert "election_multiple_leaders_observed" in fhrp["cells"]["assessment"]["boundary"]
    assert "Matching the conflicting or unresolved sequential roles is NOT ACCEPTANCE" in (
        fhrp["cells"]["validation"]["boundary"]
    )
    assert "candidate scope may be incomplete" in fhrp["cells"]["validation"]["boundary"]
    assert "not a split-brain diagnosis" in fhrp["cells"]["validation"]["boundary"]
    assert "Existing typed review rows" in fhrp["cells"]["output"]["prerequisite"]
    assert (
        "For the configured-group owner, NOT_APPLICABLE means no in-scope literal local group "
        "subject was identified; it is not "
        "proof that FHRP is absent or that configuration coverage is complete."
    ) in fhrp["cells"]["output"]["boundary"]

    combined = json.dumps(fhrp, sort_keys=True)
    for exclusion in (
        "VRFs", "IPv6", "templates/inheritance/dynamic constructs", "secondary VIPs",
        "expected peer/member count or identity", "timers", "authentication", "preemption",
        "tracking behavior", "simultaneous election health", "split brain", "failover",
        "convergence", "freshness", "interoperability",
    ):
        assert exclusion in combined


def test_fhrp_cells_bind_the_exact_redundancy_domain_owner_and_operator_projection():
    depth = _load(PROTOCOL_DEPTH_PATH)
    witness = _one(depth["witnesses"], "witness.protocol.fhrp-redundancy-domain")
    assert witness["path"] == "cisco_toolkit/fhrp_redundancy.py"
    assert witness["symbols"] == [
        "compute_fhrp_redundancy_domain_baseline",
        "validate_fhrp_redundancy_domain_baseline",
        "embedded_fhrp_redundancy_domain_baseline",
        "scope_fhrp_redundancy_domains",
    ]
    assert witness["test_refs"] == [
        "tests/test_fhrp_redundancy_domain_baseline.py",
        "tests/test_fhrp_redundancy_domain_engine.py",
        "tests/test_fhrp_domain_operator_surfaces.py",
    ]
    for symbol in witness["symbols"]:
        assert callable(getattr(fhrp_redundancy, symbol))
    assert "exact VLAN + normalized VRF + observed IPv4 subnet" in witness["proves"]
    assert "protocol + group + virtual IP" in witness["proves"]
    assert "intended membership is unresolved" in witness["proves"]
    assert "embedded_unverified" in witness["proves"]

    fhrp = next(family for family in depth["families"] if family["health_label"] == "FHRP")
    for stage in ("normalization", "assessment", "validation", "output"):
        assert "witness.protocol.fhrp-redundancy-domain" in (
            fhrp["cells"][stage]["witness_refs"]
        )
    output = fhrp["cells"]["output"]
    assert "Every degraded, review, and not-verified row survives ordinary caps" in (
        output["prerequisite"]
    )
    assert "legacy FHRP Consistency view is qualified compatibility output" in (
        output["boundary"]
    )
    assert "cannot independently say clean, unprotected, fake, or complete" in (
        output["boundary"]
    )
    assert (
        "For the redundancy-domain owner, NOT_APPLICABLE means no subject was identified; it is "
        "not proof that FHRP is absent or that intended membership is complete."
    ) in output["boundary"]

    excel = _one(depth["witnesses"], "witness.protocol.output.excel")
    runbook = _one(depth["witnesses"], "witness.protocol.output.runbook")
    explorer = _one(depth["witnesses"], "witness.protocol.output.explorer")
    assert "write_fhrp_redundancy_domain_sheet" in excel["symbols"]
    assert "write_fhrp_consistency_sheet" in excel["symbols"]
    assert "fhrp_redundancy_domain_baseline" in runbook["symbols"]
    assert "fhrpRedundancyDomainReceiptValid" in explorer["symbols"]
    assert "fhrpRedundancyDomainBaselineFrom" in explorer["symbols"]
    assert "fhrpRedundancyDomainSection" in explorer["symbols"]


def test_protocol_workspace_shows_fhrp_scope_and_global_current_gate_workflow():
    depth = _load(PROTOCOL_DEPTH_PATH)
    component = (
        ROOT / "master-reference" / "app" / "atlas" / "ProtocolDepthExplorer.tsx"
    ).read_text(encoding="utf-8")
    assert "data-runtime-fhrp-configured-group-contract" in component
    assert "Configured FHRP group gate — default/global IPv4" in component
    assert "exact three-cells-per-host census" in component
    assert "summary.by_status" in component and "summary.by_coverage_status" in component
    assert "coverage[]" in component
    assert "NOT_APPLICABLE means no in-scope" in component
    assert "NX-OS configured-group parsing is" in component
    assert "sequential election-consistency review" in component
    assert "not proof of simultaneous dual leadership or split brain" in component
    assert "does not invent a peer or infer an" in component
    assert "expected peer/member count" in component
    assert "Matching the conflicting or unresolved sequential roles" in component
    assert "is NOT ACCEPTANCE" in component
    assert "Candidate scope may be incomplete" in component
    assert "data-runtime-fhrp-redundancy-domain-contract" in component
    assert "FHRP redundancy-domain composition contract" in component
    assert "VLAN, normalized VRF, and observed subnet" in component
    assert "protocol, group, and virtual IP" in component
    assert "intended membership is unresolved" in component
    assert "not a proven unprotected" in component
    assert "Missing subtype capture/parser evidence is not verified" in component
    assert "disjoint or subset candidate sets require review" in component
    assert "Matching unresolved composition is NOT ACCEPTANCE" in component
    assert "embedded_unverified" in component
    assert "NOT_APPLICABLE means no subject was identified" in component
    assert "intended membership is complete" in component
    assert "off-scan or" in component and "intended member count" in component

    excel = _one(depth["witnesses"], "witness.protocol.output.excel")
    runbook = _one(depth["witnesses"], "witness.protocol.output.runbook")
    explorer = _one(depth["witnesses"], "witness.protocol.output.explorer")
    workflow = _one(depth["witnesses"], "witness.protocol.output.current-baseline-workflow")
    assert "write_fhrp_configured_group_sheet" in excel["symbols"]
    assert "fhrp_configured_group_baseline" in runbook["symbols"]
    assert "fhrpConfiguredGroupSection" in explorer["symbols"]
    assert "fhrpConfiguredGroupCoverageStats" in explorer["symbols"]
    assert "fhrpConfiguredGroupCoverageRows" in explorer["symbols"]
    assert workflow["path"] == "cisco_toolkit/mop.py"
    assert workflow["symbols"] == ["write_mop_docx", "_current_baseline_context"]
    assert workflow["test_refs"] == ["tests/test_mop.py", "tests/test_explorer_parse_yield.py"]
    assert "global gate is CLEAR" in workflow["proves"]
    assert "render HOLD for BLOCKED, INDETERMINATE, and" in component
    assert "retain blockers outside a scheduled wave under (unscheduled)" in component
