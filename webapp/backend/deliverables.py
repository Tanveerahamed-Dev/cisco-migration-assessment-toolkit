"""Generate registry-declared snapshot deliverables for download from AssessHub.

Engine-backed entries reuse the engine writer. Cutover and NRFU are explicitly AssessHub-owned
syntheses; the conditional PIR has a separate execution-report route and is intentionally absent
from this snapshot catalogue. Optional dependencies remain fail-soft: an unavailable renderer is
reported as unavailable instead of becoming a generation failure.
"""

from __future__ import annotations

import copy
import importlib
import importlib.util
import ipaddress
import json
import logging
import os
import re
import tempfile
from collections.abc import Mapping
from typing import Any, Dict

from . import engine  # noqa: F401  (import bootstraps sys.path so cisco_toolkit.* resolves)
from cisco_toolkit import docmeta  # noqa: E402
from cisco_toolkit.docmeta import (  # noqa: E402  (engine establishes package path in portable mode)
    ASSESSHUB_DOWNLOAD_SPECS,
    ArtifactSpec,
)
from cisco_toolkit.ssot import PLAN_SECTION_KEYS  # noqa: E402

logger = logging.getLogger(__name__)

_GATE_NOT_SUPPLIED = object()
_DISCLOSED_GATE_STATUSES = frozenset(
    {"bad_root", "unreadable", "ownership_mismatch", "ownership_unbound", "pending"}
)
_GATED_DOCUMENT_KINDS = frozenset({"design", "mop"})
_APPROVAL_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _document_gate_projection(disclosure: object) -> dict[str, object] | None:
    """Return the bounded gate facts safe to place inside a forwarded document.

    Filesystem paths, engagement identifiers and free-form ledger/error text are deliberately
    excluded.  The HTTP header and DOCX are projections of this one immutable read.
    """
    if not isinstance(disclosure, Mapping):
        return None
    status = str(disclosure.get("status") or "")
    if status not in _DISCLOSED_GATE_STATUSES:
        return None

    def keys(name: str) -> list[str]:
        value = disclosure.get(name)
        if not isinstance(value, list):
            return []
        return sorted(
            {str(item) for item in value if isinstance(item, str) and _APPROVAL_KEY.fullmatch(item)}
        )

    return {"status": status, "missing": keys("missing"), "revoked": keys("revoked")}


def _stamp_unapproved_draft(path: str, kind: str, disclosure: object) -> None:
    """Embed an unsatisfied AssessHub gate in visible DOCX text and core metadata."""
    gate = _document_gate_projection(disclosure)
    if gate is None or kind not in {"design", "mop"}:
        return

    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    status = str(gate["status"]).upper()
    missing = ", ".join(gate["missing"]) if gate["missing"] else "UNCONFIRMED"
    revoked = ", ".join(gate["revoked"]) if gate["revoked"] else "NONE RECORDED"
    marker = (
        f"UNAPPROVED DRAFT | gate status: {status} | missing approvals: {missing} | "
        f"revoked approvals: {revoked}"
    )

    doc = Document(path)
    banner = doc.paragraphs[0].insert_paragraph_before() if doc.paragraphs else doc.add_paragraph()
    banner.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = banner.add_run(marker)
    run.bold = True
    run.font.size = Pt(14)
    run.font.color.rgb = RGBColor(192, 0, 0)

    # Repeat the state in every section header so pages separated from the cover remain honest.
    for section in doc.sections:
        paragraph = section.header.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        header_run = paragraph.add_run(f"UNAPPROVED DRAFT | {status}")
        header_run.bold = True
        header_run.font.color.rgb = RGBColor(192, 0, 0)

    # Replace the generic draft row in the existing Document Control table when present.
    replaced = False
    for table in doc.tables:
        for row in table.rows:
            if len(row.cells) >= 2 and row.cells[0].text.strip().casefold() == "status":
                row.cells[1].text = marker
                replaced = True
                break
        if replaced:
            break

    # Standard OOXML core properties are independently readable from docProps/core.xml.
    doc.core_properties.content_status = "UNAPPROVED DRAFT"
    doc.core_properties.keywords = (
        f"atlas_gate_status={gate['status']};"
        f"missing={','.join(gate['missing'])};revoked={','.join(gate['revoked'])}"
    )[:255]
    doc.save(path)


def _reconcile_gate(snap: dict, _kind: str | None = None) -> dict | None:
    """Fail-soft SSOT pre-emission check (universal-best roadmap W3-5): never SILENTLY emit a deliverable from
    a snapshot whose published facts disagree with the raw evidence. Individual violations can contain uploaded
    snapshot values, so the log carries only a fixed pointer while the exact owner-produced disclosure is embedded
    into the snapshot copy passed to the writer. It never blocks the emit -- a single benign drift must not wedge
    the whole deliverable set. Total/fail-open."""
    try:
        from cisco_toolkit import ssot
        drift = ssot.audit(snap if isinstance(snap, dict) else {})
    except Exception:
        return None
    if drift:
        logger.warning(
            "[SSOT] snapshot deliverable generated with unreconciled facts; "
            "bounded reconciliation details are embedded in the artifact"
        )
    return drift


def _snapshot_with_ssot_disclosure(snap: dict, drift: object) -> dict:
    """Return a shallow snapshot copy carrying the owner-produced drift without mutating storage."""
    if not isinstance(snap, dict) or not isinstance(drift, dict):
        return snap
    rendered = dict(snap)
    current = snap.get("assessment_integrity")
    integrity = dict(current) if isinstance(current, dict) else {}
    integrity.update(drift)
    rendered["assessment_integrity"] = integrity
    return rendered


def _bounded_ssot_violation_lines(drift: object) -> list[str]:
    """Return XML-safe, single-line, bounded reconciliation details for generated artifacts."""
    if not isinstance(drift, dict) or not isinstance(drift.get("violations"), list):
        return []
    from cisco_toolkit.textutils import xml_safe

    lines = []
    for value in drift["violations"][:20]:
        raw = str(value)
        bounded = (
            raw[:464] + " [truncated; inspect source snapshot]"
            if len(raw) > 512 else raw
        )
        rendered = " ".join(str(xml_safe(bounded)).split())
        lines.append(rendered or "[unrenderable violation; inspect source snapshot]")
    return lines


def _stamp_ssot_integrity(path: str, spec: ArtifactSpec, drift: object) -> None:
    """Make a fresh SSOT failure visible in every AssessHub document type.

    Writers consume the snapshot for their domain, but not all of them render
    ``assessment_integrity``.  Post-processing only the exceptional drift case keeps normal bytes
    unchanged while ensuring the artifact carrying a fixed log pointer also carries the bounded,
    actionable findings.  The original uploaded snapshot remains unchanged.
    """
    lines = _bounded_ssot_violation_lines(drift)
    if not lines:
        return
    if spec.ext == "docx":
        from docx import Document
        from docx.shared import RGBColor

        doc = Document(path)
        paragraph = (
            doc.paragraphs[0].insert_paragraph_before()
            if doc.paragraphs else doc.add_paragraph()
        )
        title = paragraph.add_run("ASSESSMENT INTEGRITY WARNING\n")
        title.bold = True
        title.font.color.rgb = RGBColor(192, 0, 0)
        paragraph.add_run(
            "Published facts did not reconcile to their evidence. Review these bounded findings "
            "against the source snapshot before using this deliverable:\n"
            + "\n".join(f"• {line}" for line in lines)
        )
        doc.save(path)
        return
    if spec.ext == "pptx":
        from pptx import Presentation
        from pptx.util import Inches

        deck = Presentation(path)
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        box = slide.shapes.add_textbox(Inches(0.7), Inches(0.6), Inches(8.6), Inches(6.1))
        frame = box.text_frame
        frame.text = "ASSESSMENT INTEGRITY WARNING"
        frame.paragraphs[0].font.bold = True
        intro = frame.add_paragraph()
        intro.text = (
            "Published facts did not reconcile to their evidence. Review these bounded findings "
            "against the source snapshot before using this deliverable."
        )
        for line in lines:
            row = frame.add_paragraph()
            row.text = line
            row.level = 0
        deck.save(path)


def gate_disclosure(kind: str, gate_root: str = ".", engagement: str | None = None) -> dict | None:
    """The PPDIOO document-gate verdict for `kind`, as a DISCLOSURE — never a refusal.

    None means "nothing to say": an ungated deliverable, a legacy direct caller that supplied no
    engagement identity and has no store, or approvals verified for the declared engagement. The
    AssessHub route always supplies its campaign engagement ID, so no store becomes
    `ownership_unbound` rather than silent brownfield. A dict means the ledger says this document's
    upstream approvals are missing/revoked, or that gate state/ownership could not be determined;
    see `generate` for why AssessHub discloses where the CLI refuses.

    The status token is NOT computed here. `gate_state.pending_approvals` owns the gate-posture
    fact (SSOT Law 1) and is the read-only counterpart of the deciding path `enforce()` — same
    `STATUSES` vocabulary, never writes, never raises, which is exactly this surface's contract.
    Re-deriving the token locally is what inverted it: a LOCATED ledger with missing/revoked
    approvals was labelled `ungated`, a token `gate_state.UNEVALUATED` reserves for "the approvals
    were NEVER EVALUATED". So an AssessHub MOP download for an engagement whose LLD a peer review
    had actively REVOKED disclosed `X-Gate-Status: ungated` — the one word that reads as "no gates
    are tracked here, nothing to worry about" — while `enforce()` and `pending_approvals()` both
    called the same ledger `pending`. Three computations of one fact, and the third disagreed.

    Not `enforce()`, for two reasons that both still hold: it is the BLOCKING api, and its override
    arm APPENDS an audit line, which a read for a download header must never do. Total/fail-open
    like `_reconcile_gate` — a gate ledger problem must never be able to withhold a deliverable,
    which is the whole point of this mode."""
    if kind not in _GATED_DOCUMENT_KINDS:
        return None
    try:
        from cisco_toolkit import gate_state
        if kind not in gate_state.GENERATOR_REQUIRES:
            raise RuntimeError("gated document registry drift")
        posture = gate_state.pending_approvals(kind, gate_root, engagement=engagement)
        if posture["status"] in ("ungated", "clear"):
            # ungated occurs only for a caller that declared no engagement; AssessHub declares one.
            # clear here means the owner verified every required upstream approval.
            return None
        # Everything else is disclosed — `pending`, and also the remaining UNEVALUATED statuses
        # (`unreadable`, `bad_root`). Unknown ≠ absent: the CLI fails CLOSED there, we cannot, so we
        # say so loudly rather than let an operator read silence as "gates are fine". On those,
        # `missing == []` means UNKNOWN, not "nothing missing", which is why `status` leads the
        # header. `detail` mirrors `summary` for the pre-existing key shape.
        return {**posture, "detail": posture.get("summary", "")}
    except Exception:                         # noqa: BLE001 - a broken ledger never blocks a download
        # Do not interpolate the request-derived kind or an exception whose message can contain
        # ledger content.  Either can contain control characters and forge adjacent log records.
        logger.warning("[GATE UNREADABLE] gated document disclosure evaluation failed")
        return {
            "generator": kind,
            "status": "unreadable",
            "verified": False,
            "missing": [],
            "revoked": [],
            "summary": "gate state evaluation failed; approvals are unconfirmed",
            "detail": "gate state evaluation failed; approvals are unconfirmed",
        }


# Compatibility name retained for callers that used the old web-local dataclass. Membership,
# labels, media, dependencies and producers now all come from docmeta.ARTIFACT_SPECS.
Spec = ArtifactSpec
SPECS: Dict[str, ArtifactSpec] = {spec.key: spec for spec in ASSESSHUB_DOWNLOAD_SPECS}
_LIB_MODULE = {spec.needs: spec.dependency_module for spec in ASSESSHUB_DOWNLOAD_SPECS
               if spec.needs and spec.dependency_module}


def _have(lib: str) -> bool:
    return importlib.util.find_spec(_LIB_MODULE[lib]) is not None


def availability() -> Dict[str, bool]:
    """Which deliverables can be generated on this server (depends on the optional libs)."""
    by_library = {lib: _have(lib) for lib in _LIB_MODULE}
    return {key: bool(spec.needs and by_library.get(spec.needs, False))
            for key, spec in SPECS.items()}


def have_docx() -> bool:
    """Whether python-docx is installed — for docx producers outside SPECS (e.g. the PIR)."""
    return _have("python-docx")


def resolve_writer(spec: ArtifactSpec):
    """Resolve a registry-owned writer through the backend package that is actually running.

    AssessHub supports both ``backend.*`` (the documented Uvicorn/dev entry) and
    ``webapp.backend.*`` (the installed/production entry). Importing the registry's absolute
    ``webapp.backend.*`` owner while ``backend.*`` is live creates a second module object, so
    patches and module state attach to a producer the route never calls. Keep the registry's
    production owner for packaging, but bind web-local writers to this module's package identity.
    """
    module_name = spec.writer_module or ""
    web_prefix = "webapp.backend."
    if module_name.startswith(web_prefix):
        module_name = __package__ + "." + module_name.removeprefix(web_prefix)
    module = importlib.import_module(module_name)
    return getattr(module, spec.writer_name or "")


def catalogue() -> list:
    """Canonical snapshot-download metadata plus live renderer availability, for the UI."""
    avail = availability()
    return [{"key": s.key, "label": s.label, "ext": s.ext, "available": avail[s.key],
             "producer": s.producer, "engine_cli_member": s.cli_produced, "stage": s.stage}
            for s in SPECS.values()]


def generate(kind: str, snap: dict, label: str, *, gates: dict | None = None,
             gate_root: str = ".", protocol_assurance_bundle: dict | None = None,
             document_gate: object = _GATE_NOT_SUPPLIED,
             gate_engagement: str | None = None) -> str:
    """Write the deliverable to a temp file; return its path. Caller streams it and deletes it.
    `gates` is the campaign's recorded gate sign-offs — consumed only by the engagement plan of
    record (its §4.3 as-signed trail); every other writer is a pure snapshot read.

    **DECISION (2026-07-22): the PPDIOO document gates DISCLOSE here; they do not block.**

    `design` and `mop` are gated deliverables (P0-3/DEC-003), and this path is not a re-render of
    something already approved — it calls the same writers the CLI does, against a snapshot whose
    engine version and detector set may have moved since anything was peer-reviewed. So the gates
    are RELEVANT here; the earlier reading that this is a mere "additive-compatibility surface"
    covered only half the truth. The valid half survives: `write_design_doc_docx` /
    `write_mop_docx` themselves stay ungated (they are pure writers, and ~62 direct-call tests in
    tests/test_design.py + tests/test_mop.py depend on that). Gating a CALLER — which is exactly
    what the CLI's `gate_enforce` is — costs those tests nothing.

    Why disclose rather than refuse, unlike the CLI and unlike `ingest.run_redaction_folder`:
    `gate_state` resolves ONE `docs/engagement-state.json` from a directory root, but an AssessHub
    campaign is a DB row with no filesystem home (`storage.py`: campaigns(id, name, description,
    created_at)). A server-root ledger would therefore govern EVERY campaign — engagement A's
    revoked LLD would withhold campaign B's MOP, a refusal that is simply wrong about B. There is
    also no `--override-gate` on this surface, and Atlas makes AssessHub the one door in the
    field, so a wrongly-refused engineer has no recourse at all. A control with a wrong-refusal
    mode and no override gets routed around, which costs more enforcement than it buys. Disclosure
    has no wrong-refusal mode, and it matches this subsystem's own doctrine: `gates.py`
    (`annotate_out_of_order`) already DISCLOSES an out-of-order sign-off rather than blocking it,
    and `_reconcile_gate` above is fail-soft for the same reason.

    Not-silent is the part that changed. "The CLI is the enforcement point" was defensible when
    the browser was a developer convenience; ADR-0004 made AssessHub the primary field interface,
    where that reads as "the enforcement point is the door nobody uses" — an engineer refused at
    the CLI can click Download and invoke the same writer. That bypass is now visible in the
    log and on the response (`X-Gate-Status`, set by the route) instead of being invisible.

    The disclosure now travels inside Design/MOP DOCX bytes as `UNAPPROVED DRAFT` plus bounded
    machine-readable core metadata. This does not establish campaign ownership: a per-campaign
    document-gate axis still needs a schema migration and precedence rule against the filesystem
    ledger. The in-document state therefore never claims approval.
    """
    spec = SPECS[kind]
    ssot_drift = _reconcile_gate(snap, kind)
    render_snap = _snapshot_with_ssot_disclosure(snap, ssot_drift)
    disclosure = (
        gate_disclosure(kind, gate_root, engagement=gate_engagement)
        if document_gate is _GATE_NOT_SUPPLIED
        else document_gate
    )
    if disclosure:
        safe_gate = _document_gate_projection(disclosure)
        if safe_gate is None:
            logger.warning(
                "[GATE UNREADABLE] snapshot deliverable generated with an unavailable bounded "
                "gate projection -- disclosed, not blocked"
            )
        else:
            logger.warning(
                "[GATE UNSATISFIED] snapshot deliverable generated with unsatisfied document "
                "gates -- exact status is disclosed in the response and document, not blocked"
            )
    # Producer dispatch is registry-owned too. validate_artifact_registry refuses any listed
    # download without a module/function, so catalogue membership cannot become an orphan.
    write = resolve_writer(spec)

    # The request-selected key has already resolved to a closed registry entry.  It does not need
    # to become part of a filesystem expression: a fixed prefix plus the registry-owned extension
    # leaves the OS-generated path wholly independent of request bytes.
    fd, path = tempfile.mkstemp(suffix="." + spec.ext, prefix="assesshub_")
    os.close(fd)
    try:
        if kind == "engagement":
            # The writer treats None and {} identically (its own gr filter), so no `and gates`
            # second branch — one call shape per kind (V3.23.159 review simplification).
            write(path, render_snap, label, gate_record=gates)
        elif kind in docmeta.PROTOCOL_ASSURANCE_DOCUMENT_KINDS:
            # The writers are pure renderers and cannot establish exact-byte custody from a parsed
            # snapshot. AssessHub supplies the separately built portfolio-owner sidecar; direct/CLI
            # calls leave it absent and the documents state NOT VERIFIED rather than minting one.
            write(
                path,
                render_snap,
                label,
                protocol_assurance_bundle=protocol_assurance_bundle,
            )
        else:
            write(path, render_snap, label)
        _stamp_ssot_integrity(path, spec, ssot_drift)
        _stamp_unapproved_draft(path, kind, disclosure)
    except Exception:
        if os.path.exists(path):
            os.unlink(path)
        raise
    return path


SAVED_PLAN_PROJECTION_SCHEMA = "atlas.saved_plan_projection/2"
SAVED_PLAN_DERIVATION_SCHEMA = "atlas.saved_plan_derivation/2"
SAVED_PLAN_REQUIREMENTS_BYTES = 64 * 1024
_PLAN_DERIVED_KINDS = frozenset({"design", "crd", "mop", "nrfu", "deck"})
_PLAN_DERIVATION_OWNERS = (
    "cisco_toolkit.design_advisor.requirements_from_interview",
    "cisco_toolkit.ssot.derive_late_snapshot_sections",
    "cisco_toolkit.design_advisor.compute_design_blueprint",
    "cisco_toolkit.design_advisor.compute_design_nrfu",
)
_PLAN_DERIVATION_KEYS = frozenset({
    "schema", "profile", "owners", "engine_schema_version", "implementation_identity",
    "implementation_identity_status", "authority", "note",
})
_PLAN_ASSESSMENT_KEYS = frozenset({
    "source", "sha256", "bytes", "snapshot_id", "campaign_id", "engagement_id",
    "label", "script_version",
})
_PLAN_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_SQLITE_INTEGER_MAX = (1 << 63) - 1


class SavedPlanError(ValueError):
    """An invalid or mismatched selected-plan context; messages contain no submitted values."""


def _saved_plan_json(value: Any) -> bytes:
    from .storage import SavedPlanLimitError, saved_plan_json_bytes

    try:
        return saved_plan_json_bytes(value)
    except SavedPlanLimitError:
        # The API owns the 413 response for bounded projection allocation failures.
        raise
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as exc:
        raise SavedPlanError("Saved plan contains unsupported JSON values") from exc


def _saved_plan_integer(value: Any) -> bool:
    return type(value) is int and 0 < value <= _SQLITE_INTEGER_MAX


def _saved_plan_requirements(requirements: Any) -> dict:
    """Validate the field profile, then use the existing engine's one normalization bridge."""
    from cisco_toolkit.design_advisor import (
        REQUIREMENTS_AVAILABILITY_TIERS, REQUIREMENTS_FABRIC_MODELS, REQUIREMENTS_KEYS,
        REQUIREMENTS_LIST_KEYS, REQUIREMENTS_VLAN_MIN, REQUIREMENTS_VLAN_MAX,
        requirements_from_interview,
    )

    if type(requirements) is not dict:
        raise SavedPlanError("Saved plan requirements must be an object")
    if len(_saved_plan_json(requirements)) > SAVED_PLAN_REQUIREMENTS_BYTES:
        raise SavedPlanError("Saved plan requirements exceed the 64 KiB limit")
    if any(type(key) is not str or key not in REQUIREMENTS_KEYS for key in requirements):
        raise SavedPlanError("Saved plan requirements contain an unsupported field")
    for key, value in requirements.items():
        if value is None or value == "":
            continue
        if key in REQUIREMENTS_LIST_KEYS:
            if not (type(value) is str or (
                    type(value) is list and all(type(item) is str for item in value))):
                raise SavedPlanError("Saved plan list requirement has an unsupported value")
        elif key == "convergence_budget_ms":
            if type(value) is str and re.fullmatch(r"[0-9]{1,19}", value.strip()):
                value = int(value.strip())
            if type(value) is not int or not 0 <= value <= _SQLITE_INTEGER_MAX:
                raise SavedPlanError("Saved plan convergence must be a nonnegative integer")
        elif key == "vlan_zones":
            if type(value) is not dict:
                raise SavedPlanError("Saved plan VLAN zones must be an object")
            seen = set()
            grouped = any(type(item) is list for item in value.values())
            for zone_key, zone_value in value.items():
                if grouped:
                    if (type(zone_key) is not str or not zone_key.strip()
                            or type(zone_value) is not list or not zone_value):
                        raise SavedPlanError("Saved plan VLAN zones have an unsupported shape")
                    vids = zone_value
                else:
                    if type(zone_value) is not str or not zone_value.strip():
                        raise SavedPlanError("Saved plan VLAN zones have an unsupported shape")
                    vids = [zone_key]
                for vid in vids:
                    if (type(vid) is str
                            and re.fullmatch(rf"[0-9]{{1,{len(str(REQUIREMENTS_VLAN_MAX))}}}", vid.strip())):
                        vid = int(vid.strip())
                    if (type(vid) is not int
                            or not REQUIREMENTS_VLAN_MIN <= vid <= REQUIREMENTS_VLAN_MAX or vid in seen):
                        raise SavedPlanError("Saved plan VLAN zones contain an invalid or duplicate VLAN")
                    seen.add(vid)
        elif type(value) is not str:
            raise SavedPlanError("Saved plan requirement has an unsupported value")
        elif key == "availability_tier" and value.strip().lower() not in REQUIREMENTS_AVAILABILITY_TIERS:
            raise SavedPlanError("Saved plan availability tier is unsupported")
        elif key == "address_space":
            try:
                network = ipaddress.ip_network(value.strip(), strict=False)
            except ValueError as exc:
                raise SavedPlanError("Saved plan address space is invalid") from exc
            if network.version != 4:
                raise SavedPlanError("Saved plan address allocation supports IPv4 only")
    register = {
        key: value for key, value in requirements_from_interview(requirements).items()
        if value is not None and value != "" and value != [] and value != {}
    }
    if requirements.get("fabric_operating_model") and "fabric_operating_model" not in register:
        raise SavedPlanError("Saved plan fabric operating model is unsupported")
    if ("fabric_operating_model" in register
            and register["fabric_operating_model"] not in REQUIREMENTS_FABRIC_MODELS):
        raise SavedPlanError("Saved plan fabric operating model is unsupported")
    # A persisted JSON object has string keys, including the normalizer's integer VLAN keys.
    if "vlan_zones" in register:
        register["vlan_zones"] = {str(vid): zone for vid, zone in register["vlan_zones"].items()}
    encoded = _saved_plan_json(register)
    if len(encoded) > SAVED_PLAN_REQUIREMENTS_BYTES:
        raise SavedPlanError("Normalized saved plan requirements exceed the 64 KiB limit")
    return json.loads(encoded)


def prepare_saved_plan(snapshot: dict, requirements: dict) -> dict:
    """Derive once from an isolated copy; callers persist this exact non-authoritative projection."""
    from cisco_toolkit import ssot

    if not isinstance(snapshot, dict):
        raise SavedPlanError("Saved plan assessment must be an object")
    # A selected MOP/NRFU must retain the existing original-assessment portfolio contract.
    # That contract requires an explicit script owner; reject before a revision can be saved,
    # rather than accepting a plan whose later exports could only invent an owner or drop custody.
    if type(snapshot.get("script_version")) is not str or not snapshot["script_version"].strip():
        raise SavedPlanError("Selected plans require an explicit assessment script owner")
    register = _saved_plan_requirements(requirements)
    # dict() deliberately strips BoundSnapshot's process-local source marker; deepcopy protects
    # the original nested observations even if a future owner starts updating an input container.
    rendered = copy.deepcopy(dict(snapshot))
    ssot.derive_late_snapshot_sections(rendered, register, profile="saved_plan")
    projection = {
        "schema": SAVED_PLAN_PROJECTION_SCHEMA,
        "requirements": register,
        "sections": {key: rendered[key] for key in sorted(PLAN_SECTION_KEYS)},
        "derivation": {
            "schema": SAVED_PLAN_DERIVATION_SCHEMA,
            "profile": "saved_plan",
            "owners": list(_PLAN_DERIVATION_OWNERS),
            "engine_schema_version": engine.ENGINE_SCHEMA_VERSION,
            "implementation_identity": None,
            "implementation_identity_status": "not_established",
            "authority": "none",
            "note": "Persisted requirements, blueprint and NRFU only; observed assessment sections "
                    "remain the original baseline. Not assessment bytes or approval. The engine schema "
                    "version does not identify the planner implementation; exact source identity "
                    "is not established here. Reopening consumes the persisted projection.",
        },
    }
    return json.loads(_saved_plan_json(projection))


def _validated_saved_plan(snapshot: dict, plan: Any) -> tuple[dict, dict]:
    from cisco_toolkit.protocol_assurance import bound_snapshot_source
    from .storage import SavedPlanLimitError, saved_plan_digest

    if not isinstance(snapshot, dict) or type(plan) is not dict:
        raise SavedPlanError("Saved plan context is invalid")
    if (plan.get("schema") != "atlas.saved_plan/1"
            or plan.get("status") != "UNAPPROVED_DRAFT"
            or not _saved_plan_integer(plan.get("revision"))
            or not _saved_plan_integer(plan.get("selection_id"))):
        raise SavedPlanError("Saved plan revision or selection is invalid")
    if (type(plan.get("label")) is not str or not plan["label"].strip()
            or type(plan.get("created_at")) is not str or not plan["created_at"].strip()):
        raise SavedPlanError("Saved plan identity is incomplete")
    digest = plan.get("sha256")
    try:
        digest_matches = type(digest) is str and bool(_PLAN_SHA256.fullmatch(digest)) \
            and digest == saved_plan_digest(plan)
    except SavedPlanLimitError:
        raise
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as exc:
        raise SavedPlanError("Saved plan digest cannot be verified") from exc
    if not digest_matches:
        raise SavedPlanError("Saved plan digest does not match its immutable record")
    assessment = plan.get("assessment")
    if (type(assessment) is not dict or set(assessment) != _PLAN_ASSESSMENT_KEYS
            or assessment.get("source") != "persisted snapshots.snapshot_json blob"
            or type(assessment.get("sha256")) is not str
            or not _PLAN_SHA256.fullmatch(assessment["sha256"])
            or not _saved_plan_integer(assessment.get("bytes"))
            or not _saved_plan_integer(assessment.get("snapshot_id"))
            or not _saved_plan_integer(assessment.get("campaign_id"))
            or any(type(assessment.get(key)) is not str or not assessment[key].strip()
                   for key in ("engagement_id", "label", "script_version"))):
        raise SavedPlanError("Saved plan assessment binding is invalid")
    source = bound_snapshot_source(snapshot)
    if (source.get("source_bound") is not True
            or source.get("sha256") != assessment["sha256"]
            or source.get("bytes") != assessment["bytes"]
            or snapshot.get("script_version") != assessment["script_version"]):
        raise SavedPlanError("Saved plan does not match the original bound assessment")
    projection = plan.get("projection")
    if (type(projection) is not dict
            or set(projection) != {"schema", "requirements", "sections", "derivation"}
            or projection.get("schema") != SAVED_PLAN_PROJECTION_SCHEMA):
        raise SavedPlanError("Saved plan projection is unsupported")
    normalized = _saved_plan_requirements(projection.get("requirements"))
    if _saved_plan_json(normalized) != _saved_plan_json(projection["requirements"]):
        raise SavedPlanError("Saved plan requirements are not canonical")
    sections = projection.get("sections")
    if (type(sections) is not dict or set(sections) != PLAN_SECTION_KEYS
            or any(type(value) is not dict for value in sections.values())
            or _saved_plan_json(sections.get("requirements_register")) != _saved_plan_json(normalized)):
        raise SavedPlanError("Saved plan derived sections are invalid")
    derivation = projection.get("derivation")
    if (type(derivation) is not dict or set(derivation) != _PLAN_DERIVATION_KEYS
            or derivation.get("schema") != SAVED_PLAN_DERIVATION_SCHEMA
            or derivation.get("profile") != "saved_plan"
            or derivation.get("owners") != list(_PLAN_DERIVATION_OWNERS)
            or any(type(derivation.get(key)) is not str or not derivation[key].strip()
                   for key in ("engine_schema_version", "note"))
            or derivation.get("authority") != "none"
            or derivation.get("implementation_identity") is not None
            or derivation.get("implementation_identity_status") != "not_established"):
        raise SavedPlanError("Saved plan derivation authority is unsupported")
    blueprint = sections["design_blueprint"]
    nrfu = sections["design_nrfu"]
    decisions, items = blueprint.get("decisions"), nrfu.get("items")
    model = blueprint.get("requirements_model")
    if (type(decisions) is not list or type(items) is not list or type(model) is not dict
            or type(model.get("fields")) is not list
            or any(type(row) is not dict or type(row.get("id")) is not str for row in decisions)
            or any(type(row) is not dict or type(row.get("decision_id")) is not str for row in items)):
        raise SavedPlanError("Saved plan design or acceptance projection is malformed")
    values = {row.get("key"): row.get("value") for row in model["fields"]
              if type(row) is dict and type(row.get("key")) is str}
    from cisco_toolkit.design_advisor import REQUIREMENTS_KEYS
    if (set(values) != set(REQUIREMENTS_KEYS) or len(model["fields"]) != len(values)
            or _saved_plan_json(values) != _saved_plan_json({key: normalized.get(key) for key in REQUIREMENTS_KEYS})
            or model.get("provided") is not bool(normalized)):
        raise SavedPlanError("Saved plan blueprint requirements do not reconcile")
    recommended = [row["id"] for row in decisions if row.get("status") == "recommended"]
    acceptance = [row["decision_id"] for row in items]
    if (len(set(recommended)) != len(recommended) or len(set(acceptance)) != len(acceptance)
            or set(recommended) != set(acceptance)
            or type(nrfu.get("n_items")) is not int or nrfu["n_items"] != len(items)):
        raise SavedPlanError("Saved plan acceptance items do not reconcile with its design")
    return assessment, projection


def render_saved_plan(snapshot: dict, plan: dict) -> dict:
    """Return a plain rendering projection; never rederive or mint snapshot-source authority."""
    _assessment, projection = _validated_saved_plan(snapshot, plan)
    rendered = copy.deepcopy(dict(snapshot))
    rendered.update(copy.deepcopy(projection["sections"]))
    return rendered


def _stamp_saved_plan(path: str, spec: ArtifactSpec, plan: dict, *, derived: bool) -> None:
    assessment = plan["assessment"]
    identity = (
        f"atlas.plan/1;a={assessment['sha256'][7:]};p={plan['sha256'][7:]};"
        f"r={plan['revision']};s={plan['selection_id']}"
    )
    scope = (
        "Plan-derived output: the persisted selected requirements and design projection are used."
        if derived else
        "Original assessment baseline/reference associated with this selected plan. Its operational "
        "waves, gates and recorded campaign sign-offs are not regenerated from selected requirements "
        "and do not approve this plan revision."
    )
    lines = [
        "UNAPPROVED DRAFT — selected plan; saving or selecting is not approval.",
        f"Assessment snapshot {assessment['snapshot_id']} · campaign {assessment['campaign_id']}",
        f"Original assessment SHA-256: {assessment['sha256']}",
        f"Revision {plan['revision']} · Selection {plan['selection_id']}",
        f"Selected plan SHA-256: {plan['sha256']}",
        scope,
        "Original assessment protocol evidence, where shown, retains its own source-bound receipt. "
        "It does not certify the derived plan or bind this rendering projection as assessment bytes.",
        "Original assessment integrity failures remain in force. A saved plan does not repair failed "
        "assessment phases; affected sections may remain withheld or unverified.",
        "The planner implementation's exact source identity is not established by its schema version.",
    ]

    def core(properties: Any) -> None:
        properties.identifier = identity
        existing = properties.content_status or ""
        if "UNAPPROVED DRAFT" not in existing.upper():
            properties.content_status = ("UNAPPROVED DRAFT" + (" | " + existing if existing else ""))[:255]
        # Gate keywords/comments remain owned by _stamp_unapproved_draft; do not replace them.

    if spec.ext == "docx":
        from docx import Document
        from docx.shared import RGBColor

        doc = Document(path)
        paragraph = doc.paragraphs[0].insert_paragraph_before() if doc.paragraphs else doc.add_paragraph()
        paragraph.add_run(lines[0]).bold = True
        for line in lines[1:]:
            paragraph.add_run("\n" + line)
        for section in doc.sections:
            run = section.header.add_paragraph().add_run(
                f"UNAPPROVED DRAFT | Revision {plan['revision']} | Selection {plan['selection_id']}"
            )
            run.bold = True
            run.font.color.rgb = RGBColor(192, 0, 0)
        core(doc.core_properties)
        doc.save(path)
    elif spec.ext == "pptx":
        from pptx import Presentation
        from pptx.util import Inches

        deck = Presentation(path)
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        frame = slide.shapes.add_textbox(Inches(0.5), Inches(0.5), Inches(9), Inches(6.5)).text_frame
        frame.text = lines[0]
        for line in lines[1:]:
            frame.add_paragraph().text = line
        core(deck.core_properties)
        deck.save(path)
    else:
        raise SavedPlanError("Selected plan output format is unsupported")


def generate_saved_plan(kind: str, snapshot: dict, label: str, plan: dict, *,
                        gates: dict | None = None, protocol_assurance_bundle: dict | None = None,
                        document_gate: object = _GATE_NOT_SUPPLIED) -> str:
    """Render one selected revision without changing original source, protocol or approval authority."""
    from cisco_toolkit.docmeta import protocol_assurance_receipt_view

    if kind not in SPECS:
        raise SavedPlanError("Selected plan deliverable is unsupported")
    assessment, projection = _validated_saved_plan(snapshot, plan)
    if protocol_assurance_bundle is not None or kind in docmeta.PROTOCOL_ASSURANCE_DOCUMENT_KINDS:
        view = protocol_assurance_receipt_view(protocol_assurance_bundle)
        if not view["valid"] or _saved_plan_json(view["source_binding"]) != _saved_plan_json(assessment):
            raise SavedPlanError("Original assessment protocol sidecar does not match the selected plan")
    rendered = copy.deepcopy(dict(snapshot))
    derived = kind in _PLAN_DERIVED_KINDS
    if derived:
        rendered.update(copy.deepcopy(projection["sections"]))
    path = generate(
        kind, rendered, label, gates=gates, protocol_assurance_bundle=protocol_assurance_bundle,
        document_gate=document_gate, gate_engagement=assessment["engagement_id"],
    )
    try:
        _stamp_saved_plan(path, SPECS[kind], plan, derived=derived)
    except Exception:
        if os.path.exists(path):
            os.unlink(path)
        raise
    return path
