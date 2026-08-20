"""Read-only agent continuity queries and authorization validation."""

from .enhance import build_enhancement_package
from .query import query_by_id, query_by_path, query_impact
from .validation import (
    PROTECTED_ACTIONS,
    validate_completion_receipt,
    validate_task_envelope,
)

__all__ = [
    "PROTECTED_ACTIONS",
    "build_enhancement_package",
    "query_by_id",
    "query_by_path",
    "query_impact",
    "validate_completion_receipt",
    "validate_task_envelope",
]
