"""Generate the engine's narrative deliverables (runbook / design doc / MOP / exec deck) from a stored
snapshot, for download from the web UI.

Each generator in the engine is a pure snapshot-reader with the same shape as the explorer writer
(`write_*(output_path, snap_dict, label)`), so this re-uses them verbatim — the file a user downloads
here is byte-identical to what the CLI pipeline emits. python-docx / python-pptx are optional engine
deps; if a lib is absent the matching deliverable reports unavailable rather than erroring.
"""

from __future__ import annotations

import importlib.util
import os
import tempfile
from dataclasses import dataclass
from typing import Dict

from . import engine  # noqa: F401  (import bootstraps sys.path so cisco_toolkit.* resolves)

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


@dataclass(frozen=True)
class Spec:
    key: str
    label: str
    ext: str
    media: str
    needs: str  # the optional library it requires


SPECS: Dict[str, Spec] = {
    "engagement": Spec("engagement", "Engagement Workflow & Plan of Record", "docx", _DOCX, "python-docx"),
    "crd": Spec("crd", "Customer Requirements Document (CRD)", "docx", _DOCX, "python-docx"),
    "runbook": Spec("runbook", "Assessment & Migration Runbook", "docx", _DOCX, "python-docx"),
    "design": Spec("design", "As-Built Network Design Document", "docx", _DOCX, "python-docx"),
    "mop": Spec("mop", "Per-Wave Method of Procedure", "docx", _DOCX, "python-docx"),
    "cutover": Spec("cutover", "Cutover Plan (Run-of-Show)", "docx", _DOCX, "python-docx"),
    "nrfu": Spec("nrfu", "Network Ready-For-Use (NRFU) Test Plan", "docx", _DOCX, "python-docx"),
    "deck": Spec("deck", "Executive Presentation Deck", "pptx", _PPTX, "python-pptx"),
}

_LIB_MODULE = {"python-docx": "docx", "python-pptx": "pptx"}


def _have(lib: str) -> bool:
    return importlib.util.find_spec(_LIB_MODULE[lib]) is not None


def availability() -> Dict[str, bool]:
    """Which deliverables can be generated on this server (depends on the optional libs)."""
    return {key: _have(spec.needs) for key, spec in SPECS.items()}


def have_docx() -> bool:
    """Whether python-docx is installed — for docx producers outside SPECS (e.g. the PIR)."""
    return _have("python-docx")


def catalogue() -> list:
    """Spec + availability, for the UI."""
    avail = availability()
    return [{"key": s.key, "label": s.label, "ext": s.ext, "available": avail[s.key]}
            for s in SPECS.values()]


def generate(kind: str, snap: dict, label: str) -> str:
    """Write the deliverable to a temp file; return its path. Caller streams it and deletes it."""
    spec = SPECS[kind]
    if kind == "engagement":
        from cisco_toolkit.engagement import write_engagement_docx as write
    elif kind == "crd":
        from cisco_toolkit.crd import write_crd_docx as write
    elif kind == "runbook":
        from cisco_toolkit.runbook import write_runbook_docx as write
    elif kind == "design":
        from cisco_toolkit.design import write_design_doc_docx as write
    elif kind == "mop":
        from cisco_toolkit.mop import write_mop_docx as write
    elif kind == "cutover":
        # AssessHub synthesis — written in the web layer, not the engine (see cutover_docx).
        from .cutover_docx import write_cutover_docx as write
    elif kind == "nrfu":
        # AssessHub synthesis — NRFU / Acceptance Test Plan in the web layer (see nrfu_docx).
        from .nrfu_docx import write_nrfu_docx as write
    elif kind == "deck":
        from cisco_toolkit.deck import write_executive_deck_pptx as write
    else:  # pragma: no cover - guarded by the caller
        raise KeyError(kind)

    fd, path = tempfile.mkstemp(suffix="." + spec.ext, prefix=f"assesshub_{kind}_")
    os.close(fd)
    try:
        write(path, snap, label)
    except Exception:
        if os.path.exists(path):
            os.unlink(path)
        raise
    return path
