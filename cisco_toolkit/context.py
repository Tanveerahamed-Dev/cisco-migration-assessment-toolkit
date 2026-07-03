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
    # --- stage 4: the assembled snapshot ---
    snap_dict: Dict[str, Any] = field(default_factory=dict)
    snap_path: str = ""
