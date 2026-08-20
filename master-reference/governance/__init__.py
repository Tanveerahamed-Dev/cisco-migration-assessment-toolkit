"""Executable, offline governance contracts for Atlas reference releases."""

from .policy import Evaluation, evaluate_transition
from .architecture import (
    build_architecture_conformance,
    load_contract,
    validate_path_dispositions,
    validate_runtime_trace,
    validate_static_edges,
)
from .thread import append_event, replay_events, verify_events

__all__ = [
    "Evaluation",
    "append_event",
    "build_architecture_conformance",
    "evaluate_transition",
    "load_contract",
    "replay_events",
    "validate_path_dispositions",
    "validate_runtime_trace",
    "validate_static_edges",
    "verify_events",
]
