"""Typed pipeline carrier (Plan-A #15). `AnalysisContext` is the strangler seam for
COLLECT_PARSE.main(): one named, typed object that the pipeline STAGES take and populate,
replacing the wide positional-parameter call syntheses (the 19/15/14-arg compute_* calls) one
move at a time.

This is the additive FIRST landing: the type exists and the leaf finalize stage
(_stage_finalize) reads it; every remaining stage migrates onto it move by move, each guarded by
the golden + the in-process pipeline test. Mutable by design -- stages fill it in place, mirroring
today's local-variable flow with zero behaviour change. Leaf module: depends only on stdlib
dataclasses/typing (no project imports), so it can be imported anywhere without a cycle.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class AnalysisContext:
    """Carrier for the pipeline's threaded state. Fields are added as stages are extracted; today it
    holds the config/output handles + the collect/parse/snapshot state the finalize stage needs."""
    # --- config / output handles (argparse + setup) ---
    args: Any = None
    out_xlsx: str = ""
    root_dir: str = ""
    collected_at: str = ""
    workers: int = 1
    # --- stage 1: collect ---
    all_cmd_to_files: Dict[str, Dict[str, str]] = field(default_factory=dict)
    all_devices_meta: List[Any] = field(default_factory=list)
    # --- stage 2: parse / build (the core evidence) ---
    all_interfaces: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    all_device_physical: List[Any] = field(default_factory=list)
    # --- stage 3: analyze (the synthesis feeds for the three WIDE compute_* calls) ---
    # main() populates these as each analyze phase computes its output, then reads them back through
    # the thin ctx-adapters (_device_dossiers / _punchlist / _executive_brief) so the wide positional
    # _run_phase syntheses collapse to one carrier arg -- ending the 15/19/14-positional threading that
    # a silent reorder could corrupt. The public compute_* keep their explicit-arg signatures (the
    # webapp / excel / ~40 tests still call them directly); ONLY main() reads from ctx. Defaults are
    # empty containers (falsy -> each compute treats them exactly like its Optional[...] = None).
    #   shared feeds (read by two or three of the syntheses):
    health_scores: List[Any] = field(default_factory=list)
    failure_impact: List[Any] = field(default_factory=list)
    lifecycle_risk: Dict[str, Any] = field(default_factory=dict)
    software_risk: Dict[str, Any] = field(default_factory=dict)
    platform_health: Dict[str, Any] = field(default_factory=dict)
    syslog_intelligence: Dict[str, Any] = field(default_factory=dict)
    qos_audit: Dict[str, Any] = field(default_factory=dict)
    golden_drift: Dict[str, Any] = field(default_factory=dict)
    all_security: Dict[str, Any] = field(default_factory=dict)
    all_config_hygiene: Dict[str, Any] = field(default_factory=dict)
    all_stp_roots: Dict[str, Any] = field(default_factory=dict)
    all_vpc: Dict[str, Any] = field(default_factory=dict)
    physical_health: List[Any] = field(default_factory=list)
    protocol_health: List[Any] = field(default_factory=list)
    move_groups: List[Any] = field(default_factory=list)
    #   punch-list-only feeds:
    cross_layer: List[Any] = field(default_factory=list)
    l3_forwarding: List[Any] = field(default_factory=list)
    stp_findings: Dict[str, Any] = field(default_factory=dict)
    l2: Dict[str, Any] = field(default_factory=dict)
    hostname_mismatches: List[Any] = field(default_factory=list)
    drift: List[Any] = field(default_factory=list)
    ptp_readiness: List[Any] = field(default_factory=list)
    media_risks: List[Any] = field(default_factory=list)
    #   executive-brief-only feeds:
    migration_readiness: List[Any] = field(default_factory=list)
    multicast_intelligence: Dict[str, Any] = field(default_factory=dict)
    remediation_plan: Dict[str, Any] = field(default_factory=dict)
    endpoint_identity: List[Any] = field(default_factory=list)
    application_intelligence: Dict[str, Any] = field(default_factory=dict)
    segmentation: Dict[str, Any] = field(default_factory=dict)
    #   intermediate outputs fed forward (dossiers -> punchlist + brief; punchlist -> brief):
    device_dossiers: Dict[str, Any] = field(default_factory=dict)
    punchlist: List[Any] = field(default_factory=list)
    # --- stage 4: the assembled snapshot ---
    snap_dict: Dict[str, Any] = field(default_factory=dict)
    snap_path: str = ""
