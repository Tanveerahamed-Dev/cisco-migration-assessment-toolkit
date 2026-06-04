"""The analyze layer's scoring foundation: the health-score / migration-readiness
tunables (`ScoringConfig` + the module-default `SCORING`) plus the two small pure
helpers every `compute_*` leans on (`_health_band`, `_host_role`). Depends only on
`dataclasses`, stdlib `re`/`typing`, and `cisco_toolkit.model`. Extracted verbatim
from COLLECT_PARSE_V3_23_0.py in PHASE 2.7 step 10 (behaviour byte-identical).

The `compute_*` functions themselves follow in later steps (they entangle with the
`_load_cmd_output` I/O helper that still lives in the monolith). The Excel
fill-colour maps (`_READY_FILL`/`_STATUS_FILL`) and sheet-name constants stay
behind too - they belong to the excel layer, not the data analysis."""
import re
from dataclasses import dataclass, field as _dcfield   # aliased: 'field' is a common loop var elsewhere (avoids F402 shadowing)
from typing import Dict, List, Tuple

from cisco_toolkit.model import InterfaceData


# score band -> (label, fill)
_HEALTH_BANDS = [(90, "Excellent", "36E08A"), (75, "Good", "7ADB8F"),
                 (60, "Fair", "FFE566"), (40, "Poor", "FF9F45"), (0, "Critical", "FF5775")]


@dataclass(frozen=True)
class ScoringConfig:
    """NEW-V3.23.4: every health-score + migration-readiness tunable in one typed
    place (these were hard-coded as function-local dicts). The defaults reproduce
    the prior behaviour byte-for-byte; build a ScoringConfig(...) to recalibrate
    and pass it to compute_health_scores / compute_migration_readiness. The .md
    flags these as 'a defensible default, not calibrated - tune to taste.'"""
    # Per-finding deduction weights, by layer/category.
    l1_weights: Dict[str, int] = _dcfield(default_factory=lambda: {
        "err-disabled": 8, "single-fiber-uplink": 10, "error-rate-high": 5, "half-duplex": 8})
    l3_weights: Dict[str, int] = _dcfield(default_factory=lambda: {
        "single-gateway": 10, "no-FHRP": 3, "tracked-object-down": 12})
    xl_weights: Dict[str, int] = _dcfield(default_factory=lambda: {
        "Critical": 18, "High": 10, "Medium": 4, "Low": 2})
    proto_weights: Dict[str, int] = _dcfield(default_factory=lambda: {
        "High": 10, "Medium": 4})
    # Per-category cap (max total deduction a single category can contribute).
    caps: Dict[str, int] = _dcfield(default_factory=lambda: {
        "L1": 30, "L3": 30, "XL": 45, "PROTO": 25})
    # Score -> (band label, fill); first row whose threshold the score meets wins.
    bands: List[Tuple[int, str, str]] = _dcfield(default_factory=lambda: list(_HEALTH_BANDS))
    # Status a readiness check emits when its risk condition fires ('fail' ->
    # NOT READY for the group, 'warn' -> CAUTION).
    readiness: Dict[str, str] = _dcfield(default_factory=lambda: {
        "redundant_uplinks": "warn", "gateway_redundancy": "fail",
        "no_xl_critical": "fail", "no_errdisabled": "warn",
        "stp_consistency": "warn", "portchannels_healthy": "warn",
        "routing_adjacencies": "fail", "no_orphan_vlans": "warn",
        "clean_uplinks": "warn", "health_floor_critical": "fail",
        "health_floor_poor": "warn"})
    # NEW-V3.23.5: per-role multiplier on a switch's deductions (a fault on a
    # core/distribution switch has wider blast radius than on an access closet).
    # Defaults are 1.0 for every role, so scores stay byte-identical until tuned.
    criticality_factors: Dict[str, float] = _dcfield(default_factory=lambda: {
        "core": 1.0, "distribution": 1.0, "access": 1.0})
    # NEW-V3.23.7: a switch whose collection covers less than this fraction of the
    # essential command set is reported 'Insufficient Data' instead of a
    # misleadingly-high band, so a partial collection can't look healthy (audit C3).
    data_quality_threshold: float = 0.5


# Module-default scoring configuration. Replace/extend by passing a custom
# ScoringConfig to the compute_* functions; the defaults keep behaviour identical.
SCORING = ScoringConfig()


def _health_band(score: int, bands=None):
    for thr, label, fill in (bands if bands is not None else SCORING.bands):
        if score >= thr:
            return label, fill
    return "Critical", "FF5775"


def _host_role(ifaces: Dict[str, InterfaceData]) -> str:
    """Infer a switch's migration-criticality role from already-parsed data: a
    switch that hosts an L3 gateway SVI carries wider blast radius -> 'distribution';
    otherwise 'access'. ('core' is reserved for manual tuning via
    ScoringConfig.criticality_factors.) Only affects scores when factors != 1.0."""
    for port, d in (ifaces or {}).items():
        if re.match(r"^Vlan\d+$", port, re.IGNORECASE) and (getattr(d, "svi_ip", "") or "").strip():
            return "distribution"
    return "access"
