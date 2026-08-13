"""Deterministic, source-bound Atlas Master Reference PDF rendering.

The PDF is a human navigation and decision artifact.  It deliberately does not
embed source text: the compiler's content-hashed source chunks remain the owner
for line-level inspection.  This module consumes already validated
``CompilerBundle`` and ``ContentBundle`` objects, or loads them through the
strict release readers, and renders only accounting metadata and curated
repository-owned knowledge.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import unicodedata
from collections import Counter
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from reportlab import Version as REPORTLAB_VERSION
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfdoc import PDFName, PDFString
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Flowable,
    Frame,
    KeepTogether,
    LongTable,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

from governance.architecture import validate_contract

from .compiler_bundle import CompilerBundle, load_compiler_bundle
from .content_bundle import ContentBundle, load_content_bundle
from .model import canonical_json, sha256_bytes


_NAVY = colors.HexColor("#07131E")
_NAVY_2 = colors.HexColor("#0D2030")
_INK = colors.HexColor("#17212B")
_MUTED = colors.HexColor("#526575")
_LINE = colors.HexColor("#D5DFE6")
_PAPER = colors.HexColor("#F7FAFC")
_CYAN = colors.HexColor("#16C5D7")
_AMBER = colors.HexColor("#F5B942")
_RED = colors.HexColor("#B83B4A")
_GREEN = colors.HexColor("#1B7F65")
_WHITE = colors.white
_PAGE_WIDTH, _PAGE_HEIGHT = A4
_LEFT = 17 * mm
_RIGHT = 17 * mm
_TOP = 20 * mm
_BOTTOM = 17 * mm
_FRAME_WIDTH = _PAGE_WIDTH - _LEFT - _RIGHT


@dataclass(frozen=True)
class PdfCoreSinkVerification:
    """Mechanical proof that every declared core outcome slot reached the PDF."""

    verdict: str
    observation_digest: str
    verification_digest: str
    pdf_sha256: str
    rendered_observation_count: int
    safety_observation_count: int


@dataclass(frozen=True)
class PdfHorizonSinkVerification:
    """Mechanical proof that every declared horizon sink slot reached the PDF."""

    verdict: str
    observation_digest: str
    verification_digest: str
    pdf_sha256: str
    rendered_observation_count: int
    safety_observation_count: int


@dataclass(frozen=True)
class PdfCapabilitySinkVerification:
    """Mechanical proof that every capability sink slot reached the PDF."""

    verdict: str
    observation_digest: str
    verification_digest: str
    pdf_sha256: str
    rendered_observation_count: int
    safety_observation_count: int


@dataclass(frozen=True)
class PdfReportResult:
    """Stable receipt for a generated report."""

    path: Path
    sha256: str
    bytes: int
    page_count: int
    source_commit: str
    source_tree_digest: str
    input_digest: str
    reportlab_version: str
    independent_verification_verdict: str
    core_sink_observations: dict[str, tuple[dict[str, Any], ...]]
    core_sink_verification: PdfCoreSinkVerification
    capability_sink_observations: dict[str, tuple[dict[str, Any], ...]]
    capability_sink_verification: PdfCapabilitySinkVerification
    horizon_sink_observations: dict[str, tuple[dict[str, Any], ...]]
    horizon_sink_verification: PdfHorizonSinkVerification


@dataclass(frozen=True)
class PdfInspection:
    """Machine checks that complement, but never replace, visual review."""

    path: Path
    sha256: str
    bytes: int
    page_count: int
    title: str
    author: str
    subject: str
    keywords: str
    source_commit_present: bool
    source_tree_digest_present: bool


def _ascii(value: object) -> str:
    """Return deterministic ReportLab-safe text using the built-in fonts."""

    text = str(value if value is not None else "")
    replacements = {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u2192": "->",
        "\u2190": "<-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
        "\u00a0": " ",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def _plain(value: object) -> str:
    return " ".join(_ascii(value).split())


def _markup(value: object) -> str:
    return html.escape(_plain(value), quote=True)


def _items(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_plain(item) for item in value if _plain(item)]


_CORE_OUTCOME_COUNT = 9
_CORE_SCHEMA_VERSION = "1.0.0"
_CORE_ROOT_ID = "atlas.core.2026-08-07"
_CORE_OUTCOME_FIELDS = frozenset({"id", "title", "success_signal"})
_CORE_RENDERED_OBSERVATION_FIELDS = frozenset(
    {"rule_id", "record_identity", "facet_path", "disposition", "slot_id", "transform_id", "observed_value"}
)
_CORE_SECTION_MARKER_TITLE = "Outcome lineage boundary"
_CORE_SECTION_MARKER_BODY = (
    "Only the source-derived Success signal for each outcome is a lineage subject in this bounded PDF sink; "
    "identifiers and titles are labels, not candidate evidence."
)
_CORE_SECTION_MARKER = f"{_CORE_SECTION_MARKER_TITLE} {_CORE_SECTION_MARKER_BODY}"


class _PdfCoreInputError(ValueError):
    """Static, non-echoing rejection for invalid core-outcome PDF inputs."""


def _core_keys(record: object, label: str) -> frozenset[str]:
    if type(record) is not dict:
        raise _PdfCoreInputError(f"PDF core {label} must be an exact object")
    keys = tuple(record)
    if any(type(key) is not str for key in keys):
        raise _PdfCoreInputError(f"PDF core {label} keys must be exact strings")
    return frozenset(keys)


def _core_calendar_date(value: object, separator: str, label: str) -> str:
    pattern = rf"\d{{4}}\{separator}\d{{2}}\{separator}\d{{2}}"
    if type(value) is not str or re.fullmatch(pattern, value) is None:
        raise _PdfCoreInputError(f"PDF core {label} must be a calendar date")
    try:
        from datetime import date

        year, month, day = (int(part) for part in value.split(separator))
        parsed = date(year, month, day)
    except ValueError as exc:
        raise _PdfCoreInputError(f"PDF core {label} must be a calendar date") from exc
    if parsed.strftime(f"%Y{separator}%m{separator}%d") != value:
        raise _PdfCoreInputError(f"PDF core {label} must be a calendar date")
    return value


def _core_plain_text(record: dict[str, Any], field: str, label: str, *, limit: int = 4_096) -> str:
    value = record[field]
    if type(value) is not str or not value.strip() or len(value) > limit:
        raise _PdfCoreInputError(f"PDF core {label} requires bounded non-empty {field}")
    if any(ord(character) < 0x20 or ord(character) > 0x7E for character in value):
        raise _PdfCoreInputError(f"PDF core {label} requires lossless portable {field}")
    normalized = _plain(value)
    if not normalized:
        raise _PdfCoreInputError(f"PDF core {label} requires lossless portable {field}")
    return normalized


def _validated_outcomes_impl(content: ContentBundle) -> tuple[dict[str, Any], ...]:
    if type(content) is not ContentBundle:
        raise _PdfCoreInputError("PDF core outcome validation requires an exact ContentBundle")
    core = content.core
    core_keys = _core_keys(core, "registry envelope")
    if not {"schema_version", "id", "catalog_version", "as_of", "outcomes"}.issubset(core_keys):
        raise _PdfCoreInputError("PDF core registry envelope requires live root metadata and outcomes")
    schema_version = core["schema_version"]
    if type(schema_version) is not str or schema_version != _CORE_SCHEMA_VERSION:
        raise _PdfCoreInputError(f"PDF core schema_version must be {_CORE_SCHEMA_VERSION}")
    catalog_version = _core_calendar_date(core["catalog_version"], ".", "catalog_version")
    as_of = _core_calendar_date(core["as_of"], "-", "as_of")
    core_id = core["id"]
    if (
        type(core_id) is not str
        or core_id != _CORE_ROOT_ID
        or catalog_version.replace(".", "-") != as_of
        or core_id != f"atlas.core.{as_of}"
    ):
        raise _PdfCoreInputError("PDF core root metadata does not identify the live Atlas Core contract")
    raw_outcomes = core["outcomes"]
    if (
        type(raw_outcomes) is not list
        or len(raw_outcomes) != _CORE_OUTCOME_COUNT
        or any(type(item) is not dict for item in raw_outcomes)
    ):
        raise _PdfCoreInputError(f"PDF core outcomes must contain exactly {_CORE_OUTCOME_COUNT} exact objects")

    outcomes: list[dict[str, Any]] = []
    identities: set[str] = set()
    for item in raw_outcomes:
        if _core_keys(item, "outcome record") != _CORE_OUTCOME_FIELDS:
            raise _PdfCoreInputError("PDF core outcome record shape mismatch")
        record_id = item["id"]
        if (
            type(record_id) is not str
            or len(record_id) > 160
            or re.fullmatch(r"outcome\.[a-z0-9]+(?:-[a-z0-9]+)*", record_id) is None
        ):
            raise _PdfCoreInputError("PDF core outcome id must be a bounded semantic identifier")
        if record_id in identities:
            raise _PdfCoreInputError("PDF core outcome ids must be unique")
        identities.add(record_id)
        _core_plain_text(item, "title", "outcome record", limit=512)
        _core_plain_text(item, "success_signal", "outcome record")
        outcomes.append(item)
    return tuple(outcomes)


def _validated_outcomes(content: ContentBundle) -> tuple[dict[str, Any], ...]:
    """Validate the exact outcome registry without invoking hostile producer values."""

    try:
        return _validated_outcomes_impl(content)
    except _PdfCoreInputError:
        raise
    except Exception:
        raise _PdfCoreInputError("PDF core outcome source validation failed") from None


def _validate_core_observation_envelope(
    observations: Mapping[str, Sequence[Mapping[str, Any]]],
) -> None:
    try:
        if _core_keys(observations, "observation envelope") != frozenset(
            {"rendered_observations", "safety_observations"}
        ):
            raise _PdfCoreInputError("PDF core observation envelope shape mismatch")
        rendered = observations["rendered_observations"]
        safety = observations["safety_observations"]
        if type(rendered) is not tuple or len(rendered) != _CORE_OUTCOME_COUNT or type(safety) is not tuple or safety:
            raise _PdfCoreInputError("PDF core observation envelope rows must be exact tuples")
        for row in rendered:
            if _core_keys(row, "observation row") != _CORE_RENDERED_OBSERVATION_FIELDS:
                raise _PdfCoreInputError("PDF core observation row shape mismatch")
            for value in row.values():
                if (
                    type(value) is not str
                    or not value
                    or len(value) > 4_096
                    or any(ord(character) < 0x20 or ord(character) > 0x7E for character in value)
                    or _plain(value) != value
                ):
                    raise _PdfCoreInputError("PDF core observation values must be exact portable plain text")
    except _PdfCoreInputError:
        raise
    except Exception:
        raise _PdfCoreInputError("PDF core observation validation failed") from None


def pdf_core_sink_observations(
    content: ContentBundle,
) -> dict[str, tuple[dict[str, Any], ...]]:
    """Return the exact nine source-ordered outcome success-signal slots."""

    outcomes = _validated_outcomes(content)
    rendered = tuple(
        {
            "rule_id": "core.outcome",
            "record_identity": item["id"],
            "facet_path": "success_signal",
            "disposition": "rendered_labeled",
            "slot_id": (
                "pdf.product-purpose-and-outcomes.core.outcome."
                f"{item['id']}.success_signal"
            ),
            "transform_id": "pdf.core_outcome_success_signal_plain_text/1",
            "observed_value": _plain(item["success_signal"]),
        }
        for item in outcomes
    )
    return {"rendered_observations": rendered, "safety_observations": ()}


_CAPABILITY_STATES = frozenset({"current", "partial", "missing", "gated", "excluded", "unknown"})
_CAPABILITY_ROOT_FIELDS = frozenset(
    {"schema_version", "id", "catalog_version", "kind", "denominator_rule", "entry_contract", "domains"}
)
_CAPABILITY_CONTRACT_FIELDS = ("current", "partial", "incomplete", "catalog_presence")
_CAPABILITY_ENTRY_REQUIRED_FIELDS = frozenset({"id", "title", "state", "current_scope"})
_CAPABILITY_ENTRY_OPTIONAL_FIELDS = frozenset(
    {"owner_refs", "gap_refs", "traffic_plane_refs", "content_role", "mutates_assessment_truth"}
)
_CAPABILITY_TRAINING_ID = "cap.engine.training-curriculum"
_CAPABILITY_REGISTRY_COUNTS = {
    "domain": 12,
    "owner": 29,
    "gap": 41,
    "traffic plane": 8,
}
_CAPABILITY_RENDERED_OBSERVATION_FIELDS = frozenset(
    {"rule_id", "record_identity", "facet_path", "disposition", "slot_id", "transform_id", "observed_value"}
)
_CAPABILITY_SAFETY_OBSERVATION_FIELDS = frozenset(
    {"rule_id", "record_identity", "boundary_field", "slot_id", "transform_id", "observed_value"}
)


class _PdfCapabilityInputError(ValueError):
    """Static, non-echoing rejection for invalid capability PDF inputs."""


def _capability_keys(record: object, label: str) -> frozenset[str]:
    if type(record) is not dict:
        raise _PdfCapabilityInputError(f"PDF capability {label} must be an exact object")
    keys = tuple(record)
    if any(type(key) is not str for key in keys):
        raise _PdfCapabilityInputError(f"PDF capability {label} keys must be exact strings")
    return frozenset(keys)


def _capability_text_is_portable(value: str) -> bool:
    return all(
        ord(character) >= 0x20
        and not 0x7F <= ord(character) <= 0x9F
        and not 0xD800 <= ord(character) <= 0xDFFF
        for character in value
    )


def _required_capability_text(record: dict[str, Any], field: str, record_label: str) -> str:
    value = record.get(field)
    if type(value) is not str or not value.strip() or len(value) > 4_096:
        raise _PdfCapabilityInputError(f"PDF capability {record_label} requires non-empty {field}")
    if not _capability_text_is_portable(value) or not _plain(value):
        raise _PdfCapabilityInputError(f"PDF capability {record_label} requires portable non-empty {field}")
    return value


def _capability_identifier(value: object, prefix: str, label: str) -> str:
    if (
        type(value) is not str
        or not value.startswith(prefix)
        or len(value) > 160
        or re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+(?:-[a-z0-9]+)*)+", value) is None
    ):
        raise _PdfCapabilityInputError(f"PDF capability {label} must be a bounded semantic identifier")
    return value


def _capability_catalog_version(value: object) -> str:
    if type(value) is not str or re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", value) is None:
        raise _PdfCapabilityInputError("PDF capability catalog_version must be a calendar date")
    try:
        from datetime import date

        year, month, day = (int(part) for part in value.split("."))
        parsed = date(year, month, day)
    except ValueError as exc:
        raise _PdfCapabilityInputError("PDF capability catalog_version must be a calendar date") from exc
    if parsed.strftime("%Y.%m.%d") != value:
        raise _PdfCapabilityInputError("PDF capability catalog_version must be a calendar date")
    return value


def _capability_registry_ids(
    value: object,
    *,
    label: str,
    prefix: str,
) -> frozenset[str]:
    expected_count = _CAPABILITY_REGISTRY_COUNTS[label]
    if type(value) is not list or len(value) != expected_count:
        raise _PdfCapabilityInputError(
            f"PDF capability {label} registry must contain exactly {expected_count} objects"
        )
    identifiers: list[str] = []
    for item in value:
        keys = _capability_keys(item, f"{label} registry record")
        if "id" not in keys:
            raise _PdfCapabilityInputError(f"PDF capability {label} registry record requires id")
        identifiers.append(_capability_identifier(item["id"], prefix, f"{label} registry id"))
    if len(identifiers) != len(set(identifiers)):
        raise _PdfCapabilityInputError(f"PDF capability {label} registry ids must be unique")
    return frozenset(identifiers)


def _capability_registries(
    content: ContentBundle,
) -> tuple[frozenset[str], frozenset[str], frozenset[str], frozenset[str]]:
    core_keys = _capability_keys(content.core, "core registry envelope")
    governance_keys = _capability_keys(content.governance, "governance registry envelope")
    for field in ("domain_registry", "owners", "traffic_model"):
        if field not in core_keys:
            raise _PdfCapabilityInputError(f"PDF capability core registry envelope requires {field}")
    if "gaps" not in governance_keys:
        raise _PdfCapabilityInputError("PDF capability governance registry envelope requires gaps")

    traffic_model = content.core["traffic_model"]
    traffic_keys = _capability_keys(traffic_model, "traffic_model registry envelope")
    if "planes" not in traffic_keys:
        raise _PdfCapabilityInputError("PDF capability traffic_model registry envelope requires planes")
    return (
        _capability_registry_ids(content.core["domain_registry"], label="domain", prefix="domain."),
        _capability_registry_ids(content.core["owners"], label="owner", prefix="owner."),
        _capability_registry_ids(content.governance["gaps"], label="gap", prefix="gap."),
        _capability_registry_ids(traffic_model["planes"], label="traffic plane", prefix="traffic."),
    )


def _validate_capability_refs(
    entry: dict[str, Any],
    field: str,
    prefix: str,
    registry_ids: frozenset[str],
) -> tuple[str, ...]:
    if field not in entry:
        return ()
    value = entry[field]
    if (
        type(value) is not list
        or len(value) > 64
        or any(type(item) is not str for item in value)
    ):
        raise _PdfCapabilityInputError(f"PDF capability entry {field} must be a unique string array")
    identifiers = tuple(_capability_identifier(item, prefix, f"entry {field}") for item in value)
    if len(identifiers) != len(set(identifiers)):
        raise _PdfCapabilityInputError(f"PDF capability entry {field} must be a unique string array")
    if any(identifier not in registry_ids for identifier in identifiers):
        raise _PdfCapabilityInputError(f"PDF capability entry {field} contains an unresolved registry reference")
    return identifiers


def _validated_capabilities_impl(
    content: ContentBundle,
) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    capabilities = content.capabilities
    if _capability_keys(capabilities, "catalog root") != _CAPABILITY_ROOT_FIELDS:
        raise _PdfCapabilityInputError("PDF capability catalog root shape mismatch")
    schema_version = capabilities.get("schema_version")
    if type(schema_version) is not str or schema_version != "1.0.0":
        raise _PdfCapabilityInputError("PDF capability schema_version must be 1.0.0")
    catalog_version = _capability_catalog_version(capabilities.get("catalog_version"))
    root_id = _capability_identifier(capabilities.get("id"), "atlas.capability-catalog.", "catalog id")
    if root_id != f"atlas.capability-catalog.{catalog_version.replace('.', '-')}":
        raise _PdfCapabilityInputError("PDF capability catalog id does not bind catalog_version")
    _required_capability_text(capabilities, "denominator_rule", "catalog root")
    kind = capabilities.get("kind")
    if type(kind) is not str or kind != "closed-world-capability-catalog":
        raise _PdfCapabilityInputError("PDF capability catalog kind mismatch")

    domain_registry, owner_registry, gap_registry, traffic_registry = _capability_registries(content)

    entry_contract = capabilities.get("entry_contract")
    if _capability_keys(entry_contract, "entry_contract") != frozenset(_CAPABILITY_CONTRACT_FIELDS):
        raise _PdfCapabilityInputError("PDF capability entry_contract shape mismatch")
    for field in _CAPABILITY_CONTRACT_FIELDS:
        _required_capability_text(entry_contract, field, "entry_contract")

    raw_domains = capabilities.get("domains")
    if (
        type(raw_domains) is not list
        or len(raw_domains) != 12
        or any(type(domain) is not dict for domain in raw_domains)
    ):
        raise _PdfCapabilityInputError("PDF capability catalog must contain exactly 12 domain objects")
    domains = tuple(raw_domains)
    domain_ids: set[str] = set()
    entries: list[dict[str, Any]] = []
    entry_ids: set[str] = set()
    observed_states: set[str] = set()
    training_seen = False
    for domain in domains:
        if _capability_keys(domain, "domain") != frozenset({"id", "entity_role", "entries"}):
            raise _PdfCapabilityInputError("PDF capability domain shape mismatch")
        domain_id = _capability_identifier(domain.get("id"), "domain.", "domain id")
        if domain_id in domain_ids:
            raise _PdfCapabilityInputError("PDF capability domain ids must be unique")
        if domain_id not in domain_registry:
            raise _PdfCapabilityInputError("PDF capability domain id contains an unresolved registry reference")
        domain_ids.add(domain_id)
        entity_role = domain.get("entity_role")
        if type(entity_role) is not str or entity_role != "reference":
            raise _PdfCapabilityInputError("PDF capability domain entity_role must be reference")
        raw_entries = domain.get("entries")
        if (
            type(raw_entries) is not list
            or not raw_entries
            or len(raw_entries) > 64
            or any(type(item) is not dict for item in raw_entries)
        ):
            raise _PdfCapabilityInputError("PDF capability domain entries must be a non-empty array of objects")
        for entry in raw_entries:
            fields = _capability_keys(entry, "entry")
            if not _CAPABILITY_ENTRY_REQUIRED_FIELDS <= fields or fields - (
                _CAPABILITY_ENTRY_REQUIRED_FIELDS | _CAPABILITY_ENTRY_OPTIONAL_FIELDS
            ):
                raise _PdfCapabilityInputError("PDF capability entry shape mismatch")
            record_id = _capability_identifier(entry.get("id"), "cap.", "entry id")
            _required_capability_text(entry, "title", "entry")
            _required_capability_text(entry, "current_scope", "entry")
            if record_id in entry_ids:
                raise _PdfCapabilityInputError("PDF capability entry ids must be unique")
            entry_ids.add(record_id)
            state = entry.get("state")
            if type(state) is not str or state not in _CAPABILITY_STATES:
                raise _PdfCapabilityInputError("PDF capability entry state is outside the controlled vocabulary")
            observed_states.add(state)
            owners = _validate_capability_refs(entry, "owner_refs", "owner.", owner_registry)
            gaps = _validate_capability_refs(entry, "gap_refs", "gap.", gap_registry)
            _validate_capability_refs(entry, "traffic_plane_refs", "traffic.", traffic_registry)
            if state == "current" and not owners:
                raise _PdfCapabilityInputError("PDF current capability requires owner_refs")
            if state == "current" and gaps:
                raise _PdfCapabilityInputError("PDF current capability cannot carry gap_refs")
            if state == "partial" and (not owners or not gaps):
                raise _PdfCapabilityInputError("PDF partial capability requires owner_refs and gap_refs")
            if state in {"missing", "gated", "excluded", "unknown"} and not gaps:
                raise _PdfCapabilityInputError("PDF incomplete capability requires gap_refs")
            if record_id == _CAPABILITY_TRAINING_ID:
                training_seen = True
                content_role = entry.get("content_role")
                if (
                    type(content_role) is not str
                    or content_role != "advisory"
                    or entry.get("mutates_assessment_truth") is not False
                ):
                    raise _PdfCapabilityInputError(
                        "PDF training capability boundary must be content_role=advisory and "
                        "mutates_assessment_truth=false"
                    )
            elif "content_role" in entry or "mutates_assessment_truth" in entry:
                raise _PdfCapabilityInputError("PDF capability boundary fields are reserved for the training entry")
            entries.append(entry)

    if len(entries) != 211:
        raise _PdfCapabilityInputError("PDF capability catalog must contain exactly 211 entries")
    if domain_ids != domain_registry:
        raise _PdfCapabilityInputError("PDF capability domains do not exactly bind the domain registry")
    if observed_states != _CAPABILITY_STATES:
        raise _PdfCapabilityInputError("PDF capability catalog must exercise the complete controlled-state vocabulary")
    if not training_seen:
        raise _PdfCapabilityInputError("PDF capability catalog requires the advisory training entry")
    return domains, tuple(entries)


def _validated_capabilities(
    content: ContentBundle,
) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    """Validate the catalog and its exact registry envelope without echoing hostile inputs."""

    if type(content) is not ContentBundle:
        raise _PdfCapabilityInputError("PDF capability validation requires an exact ContentBundle")
    try:
        return _validated_capabilities_impl(content)
    except _PdfCapabilityInputError:
        raise
    except Exception:
        raise _PdfCapabilityInputError("PDF capability source validation failed") from None


def _validate_capability_observation_envelope(
    observations: Mapping[str, Sequence[Mapping[str, Any]]],
) -> None:
    try:
        if _capability_keys(observations, "observation envelope") != frozenset(
            {"rendered_observations", "safety_observations"}
        ):
            raise _PdfCapabilityInputError("PDF capability observation envelope shape mismatch")
        for field, row_fields, expected_count in (
            ("rendered_observations", _CAPABILITY_RENDERED_OBSERVATION_FIELDS, 422),
            ("safety_observations", _CAPABILITY_SAFETY_OBSERVATION_FIELDS, 7),
        ):
            rows = observations[field]
            if type(rows) is not tuple or len(rows) != expected_count:
                raise _PdfCapabilityInputError("PDF capability observation envelope rows must be an exact tuple")
            for row in rows:
                if _capability_keys(row, "observation row") != row_fields:
                    raise _PdfCapabilityInputError("PDF capability observation row shape mismatch")
                for key, value in row.items():
                    if key == "observed_value":
                        if type(value) is bool:
                            continue
                    if (
                        type(value) is not str
                        or len(value) > 4_096
                        or not _capability_text_is_portable(value)
                    ):
                        raise _PdfCapabilityInputError(
                            "PDF capability observation envelope values must be exact portable scalars"
                        )
    except _PdfCapabilityInputError:
        raise
    except Exception:
        raise _PdfCapabilityInputError("PDF capability observation validation failed") from None


def pdf_capability_sink_observations(
    content: ContentBundle,
) -> dict[str, tuple[dict[str, Any], ...]]:
    """Return the exact candidate and safety slots rendered by the capability PDF sink."""

    _, entries = _validated_capabilities(content)
    capabilities = content.capabilities
    rendered: list[dict[str, Any]] = []
    safety: list[dict[str, Any]] = []
    for entry in entries:
        record_id = entry["id"]
        for field, transform_id in (
            ("state", "pdf.capability_heading_state/1"),
            ("current_scope", "pdf.capability_scope_plain_text/1"),
        ):
            rendered.append(
                {
                    "rule_id": "capability.entry",
                    "record_identity": record_id,
                    "facet_path": field,
                    "disposition": "rendered_labeled",
                    "slot_id": f"pdf.capabilities.capability.entry.{record_id}.{field}",
                    "transform_id": transform_id,
                    "observed_value": entry[field],
                }
            )

    def observe_safety(
        rule_id: str,
        record_identity: str,
        boundary_field: str,
        transform_id: str,
        value: object,
    ) -> None:
        safety.append(
            {
                "rule_id": rule_id,
                "record_identity": record_identity,
                "boundary_field": boundary_field,
                "observed_value": value,
                "slot_id": f"pdf.capabilities.{rule_id}.{record_identity}.{boundary_field}",
                "transform_id": transform_id,
            }
        )

    observe_safety(
        "capability.root",
        "@root",
        "denominator_rule",
        "pdf.capability_support_contract/1",
        capabilities["denominator_rule"],
    )
    entry_contract = capabilities["entry_contract"]
    for field in _CAPABILITY_CONTRACT_FIELDS:
        observe_safety(
            "capability.entry_contract",
            "@root",
            field,
            "pdf.capability_support_contract/1",
            entry_contract[field],
        )
    training = next(entry for entry in entries if entry["id"] == _CAPABILITY_TRAINING_ID)
    for field in ("content_role", "mutates_assessment_truth"):
        observe_safety(
            "capability.entry",
            _CAPABILITY_TRAINING_ID,
            field,
            "pdf.capability_entry_boundary/1",
            training[field],
        )
    return {"rendered_observations": tuple(rendered), "safety_observations": tuple(safety)}


def _required_horizon_text(record: Mapping[str, Any], field: str, record_label: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"PDF horizon {record_label} requires non-empty {field}")
    return value


def _required_horizon_records(
    horizon: Mapping[str, Any],
    field: str,
) -> tuple[Mapping[str, Any], ...]:
    value = horizon.get(field)
    if not isinstance(value, list) or not value or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"PDF horizon {field} must be a non-empty array of objects")
    return tuple(value)


def _validated_horizon(
    horizon: Mapping[str, Any],
) -> tuple[tuple[Mapping[str, Any], ...], tuple[Mapping[str, Any], ...]]:
    """Validate every source value the PDF promotes into its horizon section."""

    _required_horizon_text(horizon, "promise", "root")
    root_role = _required_horizon_text(horizon, "content_role", "root")
    root_support = _required_horizon_text(horizon, "support_claim", "root")
    if root_role != "advisory" or root_support != "none" or horizon.get("mutates_assessment_truth") is not False:
        raise ValueError(
            "PDF horizon root boundary must be content_role=advisory, "
            "support_claim=none, mutates_assessment_truth=false"
        )

    watches = _required_horizon_records(horizon, "watch_families")
    signals = _required_horizon_records(horizon, "signals")
    identities: set[tuple[str, str]] = set()
    for watch in watches:
        record_id = _required_horizon_text(watch, "id", "watch family")
        identity = ("watch family", record_id)
        if identity in identities:
            raise ValueError("PDF horizon watch family ids must be unique")
        identities.add(identity)
        for field in ("name", "source_url", "authority_scope", "review_cadence", "engine_ingestion"):
            _required_horizon_text(watch, field, "watch family")
        if _required_horizon_text(watch, "content_role", "watch family") != root_role:
            raise ValueError("PDF horizon watch family content_role boundary mismatch")

    signal_ids: set[str] = set()
    for signal in signals:
        record_id = _required_horizon_text(signal, "id", "signal")
        if record_id in signal_ids:
            raise ValueError("PDF horizon signal ids must be unique")
        signal_ids.add(record_id)
        for field in (
            "title",
            "disposition",
            "maturity",
            "business_relevance",
            "current_coverage",
            "rationale",
            "next_review_rule",
        ):
            _required_horizon_text(signal, field, "signal")
        criteria = signal.get("promotion_criteria")
        if (
            not isinstance(criteria, list)
            or not criteria
            or any(not isinstance(item, str) or not item.strip() for item in criteria)
        ):
            raise ValueError("PDF horizon signal requires non-empty promotion_criteria")
        if _required_horizon_text(signal, "content_role", "signal") != root_role:
            raise ValueError("PDF horizon signal content_role boundary mismatch")
        if _required_horizon_text(signal, "support_claim", "signal") != root_support:
            raise ValueError("PDF horizon signal support_claim boundary mismatch")
    if "horizon.unknown" not in signal_ids:
        raise ValueError("PDF horizon signals must include horizon.unknown")
    return watches, signals


def pdf_horizon_sink_observations(
    horizon: Mapping[str, Any],
) -> dict[str, tuple[dict[str, Any], ...]]:
    """Return deterministic semantic slots rendered by the PDF horizon sink.

    Values remain in memory for a future lineage evaluator to digest and omit;
    this helper performs no ID derivation and writes no observation artifact.
    """

    watches, signals = _validated_horizon(horizon)
    rendered: list[dict[str, Any]] = []
    safety: list[dict[str, Any]] = []

    def observe(
        rule_id: str,
        record_identity: str,
        facet_path: str,
        disposition: str,
        transform_id: str,
        observed_value: object,
    ) -> None:
        rendered.append(
            {
                "rule_id": rule_id,
                "record_identity": record_identity,
                "facet_path": facet_path,
                "disposition": disposition,
                "slot_id": f"pdf.horizon.{rule_id}.{record_identity}.{facet_path}",
                "transform_id": transform_id,
                "observed_value": observed_value,
            }
        )

    def observe_safety(
        rule_id: str,
        record_identity: str,
        boundary_field: str,
        transform_id: str,
        observed_value: object,
    ) -> None:
        safety.append(
            {
                "rule_id": rule_id,
                "record_identity": record_identity,
                "boundary_field": boundary_field,
                "observed_value": observed_value,
                "slot_id": f"pdf.horizon.{rule_id}.{record_identity}.boundary.{boundary_field}",
                "transform_id": transform_id,
            }
        )

    observe(
        "horizon.root",
        "@root",
        "promise",
        "rendered_labeled",
        "pdf.callout_plain_text/1",
        horizon["promise"],
    )
    for field in ("content_role", "support_claim", "mutates_assessment_truth"):
        observe_safety(
            "horizon.root",
            "@root",
            field,
            "pdf.source_boundary_table/1",
            horizon[field],
        )
    for watch in watches:
        record_id = str(watch["id"])
        for field in ("authority_scope", "review_cadence", "engine_ingestion"):
            observe(
                "horizon.watch_family",
                record_id,
                field,
                "rendered_labeled",
                "pdf.labeled_plain_text/1",
                watch[field],
            )
        observe_safety(
            "horizon.watch_family",
            record_id,
            "content_role",
            "pdf.source_boundary_table/1",
            watch["content_role"],
        )
    for signal in signals:
        record_id = str(signal["id"])
        for field in (
            "disposition",
            "maturity",
            "next_review_rule",
            "business_relevance",
            "current_coverage",
            "rationale",
        ):
            observe(
                "horizon.signal",
                record_id,
                field,
                "rendered_labeled",
                "pdf.labeled_plain_text/1",
                signal[field],
            )
        observe(
            "horizon.signal",
            record_id,
            "promotion_criteria",
            "rendered_ordered_array",
            "pdf.ordered_numbered_list/1",
            list(signal["promotion_criteria"]),
        )
        for field in ("content_role", "support_claim"):
            observe_safety(
                "horizon.signal",
                record_id,
                field,
                "pdf.source_boundary_table/1",
                signal[field],
            )
    return {
        "rendered_observations": tuple(rendered),
        "safety_observations": tuple(safety),
    }


def _unique_pdf_segment(text: str, anchor: str, next_anchor: str) -> str | None:
    start = text.find(anchor)
    if start < 0 or text.find(anchor, start + len(anchor)) >= 0:
        return None
    end = text.find(next_anchor, start + len(anchor))
    if end < 0:
        return None
    return text[start:end]


def _core_pdf_body_text(pages: Sequence[Any]) -> str:
    """Strip only exact page-furniture prefixes, never body-equivalent text."""

    body_pages: list[str] = []
    privacy_footer = "PRIVATE / READ-ONLY / CLIENT-DATA INGESTION PROHIBITED"
    for page_number, page in enumerate(pages, start=1):
        raw_lines = (page.extract_text() or "").splitlines()
        lines: list[str] = []
        for raw_line in raw_lines:
            normalized = _plain(raw_line)
            if raw_line.strip() and _ascii(raw_line) != raw_line:
                raise ValueError("PDF core sink verification failed: core_outcome_extracted_text_not_lossless")
            if normalized:
                lines.append(normalized)
        cursor = 0
        if (
            page_number > 1
            and len(lines) >= 2
            and lines[0] == "ATLAS / MASTER REFERENCE"
            and re.fullmatch(r"SOURCE [0-9a-f]{12}", lines[1]) is not None
        ):
            cursor = 2
        if (
            len(lines) >= cursor + 2
            and lines[cursor] == privacy_footer
            and lines[cursor + 1] == f"Page {page_number}"
        ):
            cursor += 2
        body_pages.append(" ".join(lines[cursor:]))
    return _plain(" ".join(body_pages))


def verify_pdf_core_sink_observations(
    pdf_path: Path,
    content: ContentBundle,
    *,
    observations: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> PdfCoreSinkVerification:
    """Fail closed unless each outcome success signal is visible exactly once."""

    expected = pdf_core_sink_observations(content)
    if observations is not None:
        _validate_core_observation_envelope(observations)
        try:
            matches_source = canonical_json(observations) == canonical_json(expected)
        except Exception:
            raise _PdfCoreInputError("PDF core observation validation failed") from None
        if not matches_source:
            raise ValueError("PDF core observation envelope differs from validated source")
    outcomes = _validated_outcomes(content)
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - explicit environment error
        raise RuntimeError("pypdf is required to verify PDF core observations") from exc

    resolved = pdf_path.resolve(strict=True)
    raw = resolved.read_bytes()
    reader = PdfReader(BytesIO(raw))
    text = _core_pdf_body_text(reader.pages)
    errors: list[str] = []
    section = _unique_pdf_segment(text, _CORE_SECTION_MARKER, "4. Closed Capability Catalog")
    if section is None:
        errors.append("core_outcome_section_missing_or_ambiguous")
        section = ""

    anchors = [f"{item['id']} - {_plain(item['title'])}" for item in outcomes]
    positions = [section.find(anchor) for anchor in anchors]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        errors.append("core_outcome_record_order_or_anchor_missing")
    if any(section.count(anchor) != 1 for anchor in anchors):
        errors.append("core_outcome_record_anchor_ambiguous")

    rendered_rows = expected["rendered_observations"]
    if len(rendered_rows) != _CORE_OUTCOME_COUNT:
        errors.append("core_outcome_candidate_observation_count_mismatch")
    if section.count("Success signal:") != _CORE_OUTCOME_COUNT:
        errors.append("core_outcome_physical_slot_count_mismatch")
    expected_section_text = _plain(
        " ".join(
            [
                _CORE_SECTION_MARKER,
                *[
                    (
                        f"{item['id']} - {_plain(item['title'])} "
                        f"Success signal: {row['observed_value']}"
                    )
                    for item, row in zip(outcomes, rendered_rows, strict=True)
                ],
            ]
        )
    )
    if _plain(section) != expected_section_text:
        errors.append("core_outcome_section_visible_text_not_exact")
    if not errors:
        for index, (item, row) in enumerate(zip(outcomes, rendered_rows, strict=True)):
            start = positions[index]
            end = positions[index + 1] if index + 1 < len(positions) else len(section)
            segment = section[start:end]
            expected_fragment = f"Success signal: {row['observed_value']}"
            if (
                row["record_identity"] != item["id"]
                or row["facet_path"] != "success_signal"
                or segment.count("Success signal:") != 1
                or segment.count(expected_fragment) != 1
                or segment.count(str(row["observed_value"])) != 1
            ):
                errors.append("core_outcome_success_signal_projection_missing_or_ambiguous")

    if expected["safety_observations"]:
        errors.append("core_outcome_safety_observation_count_mismatch")
    if errors:
        raise ValueError("PDF core sink verification failed: " + ", ".join(sorted(set(errors))))

    observation_digest = sha256_bytes(canonical_json(expected))
    pdf_digest = sha256_bytes(raw)
    verification_material = {
        "verdict": "PASS",
        "pdf_sha256": pdf_digest,
        "observation_digest": observation_digest,
        "rendered_observation_count": len(rendered_rows),
        "safety_observation_count": 0,
    }
    return PdfCoreSinkVerification(
        verdict="PASS",
        observation_digest=observation_digest,
        verification_digest=sha256_bytes(canonical_json(verification_material)),
        pdf_sha256=pdf_digest,
        rendered_observation_count=len(rendered_rows),
        safety_observation_count=0,
    )


def verify_pdf_capability_sink_observations(
    pdf_path: Path,
    content: ContentBundle,
    *,
    observations: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> PdfCapabilitySinkVerification:
    """Fail closed unless every capability observation is visibly projected."""

    expected = pdf_capability_sink_observations(content)
    if observations is not None:
        _validate_capability_observation_envelope(observations)
        try:
            matches_source = canonical_json(observations) == canonical_json(expected)
        except Exception:
            raise _PdfCapabilityInputError("PDF capability observation validation failed") from None
        if not matches_source:
            raise ValueError("PDF capability observation envelope differs from validated source")
    _, entries = _validated_capabilities(content)
    capabilities = content.capabilities
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - explicit environment error
        raise RuntimeError("pypdf is required to verify PDF capability observations") from exc

    resolved = pdf_path.resolve(strict=True)
    raw = resolved.read_bytes()
    reader = PdfReader(BytesIO(raw))
    text = _plain("\n".join(page.extract_text() or "" for page in reader.pages))
    errors: list[str] = []

    anchors = [
        _plain(f"{entry['id']} - {entry['title']} [{str(entry['state']).upper()}]")
        for entry in entries
    ]
    positions = [text.find(anchor) for anchor in anchors]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        errors.append("capability_record_order_or_anchor_missing")
    if any(text.count(anchor) != 1 for anchor in anchors):
        errors.append("capability_record_anchor_ambiguous")

    segments: dict[str, str] = {}
    for index, entry in enumerate(entries):
        next_anchor = anchors[index + 1] if index + 1 < len(entries) else "5. Delivery governance, gaps, and decisions"
        segment = _unique_pdf_segment(text, anchors[index], next_anchor)
        if segment is None:
            errors.append("capability_record_segment_missing_or_ambiguous")
        else:
            segments[str(entry["id"])] = segment

    rendered_rows = expected["rendered_observations"]
    if len(rendered_rows) != 422:
        errors.append("capability_candidate_observation_count_mismatch")
    for index, entry in enumerate(entries):
        state_row, scope_row = rendered_rows[index * 2 : index * 2 + 2]
        if (
            state_row.get("record_identity") != entry["id"]
            or state_row.get("facet_path") != "state"
            or scope_row.get("record_identity") != entry["id"]
            or scope_row.get("facet_path") != "current_scope"
        ):
            errors.append("capability_candidate_observation_order_mismatch")
            continue
        segment = segments.get(str(entry["id"]), "")
        if anchors[index] not in segment:
            errors.append("capability_state_projection_missing")
        if segment.count(f"Current scope: {_plain(entry['current_scope'])}") != 1:
            errors.append("capability_scope_projection_missing")

    denominator_value = _plain(capabilities["denominator_rule"])
    denominator_fragment = f"Finite denominator {denominator_value}"
    support_segment = _unique_pdf_segment(text, denominator_fragment, anchors[0])
    if support_segment is None:
        errors.append("capability_support_contract_missing_or_ambiguous")
    else:
        support_fragments = [
            denominator_fragment,
            *[
                f"entry_contract {field}: {_plain(capabilities['entry_contract'][field])}"
                for field in _CAPABILITY_CONTRACT_FIELDS
            ],
        ]
        if any(
            support_segment.count(fragment) != 1 or text.count(fragment) != 1
            for fragment in support_fragments
        ) or support_segment.count(denominator_value) != 1 or text.count(denominator_value) != 1:
            errors.append("capability_support_contract_projection_missing")

    training_segment = segments.get(_CAPABILITY_TRAINING_ID, "")
    training = next(entry for entry in entries if entry["id"] == _CAPABILITY_TRAINING_ID)
    training_boundary = (
        f"Entry safety boundary: content_role={_plain(training['content_role'])}; "
        f"mutates_assessment_truth={_plain(training['mutates_assessment_truth']).lower()}"
    )
    if training_segment.count(training_boundary) != 1 or text.count(training_boundary) != 1:
        errors.append("capability_training_boundary_projection_missing")

    safety_rows = expected["safety_observations"]
    if len(safety_rows) != 7:
        errors.append("capability_safety_observation_count_mismatch")
    if errors:
        raise ValueError("PDF capability sink verification failed: " + ", ".join(sorted(set(errors))))

    observation_digest = sha256_bytes(canonical_json(expected))
    pdf_digest = sha256_bytes(raw)
    verification_material = {
        "verdict": "PASS",
        "pdf_sha256": pdf_digest,
        "observation_digest": observation_digest,
        "rendered_observation_count": len(rendered_rows),
        "safety_observation_count": len(safety_rows),
    }
    return PdfCapabilitySinkVerification(
        verdict="PASS",
        observation_digest=observation_digest,
        verification_digest=sha256_bytes(canonical_json(verification_material)),
        pdf_sha256=pdf_digest,
        rendered_observation_count=len(rendered_rows),
        safety_observation_count=len(safety_rows),
    )


def verify_pdf_horizon_sink_observations(
    pdf_path: Path,
    horizon: Mapping[str, Any],
    *,
    observations: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> PdfHorizonSinkVerification:
    """Fail closed unless every horizon observation is visibly projected.

    This is a deterministic mechanical sink check, not semantic or independent
    review. It anchors each candidate to its named record section and each
    safety input to the source-derived boundary table.
    """

    expected = pdf_horizon_sink_observations(horizon)
    if observations is not None and canonical_json(observations) != canonical_json(expected):
        raise ValueError("PDF horizon observation envelope differs from validated source")
    watches, signals = _validated_horizon(horizon)
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - explicit environment error
        raise RuntimeError("pypdf is required to verify PDF horizon observations") from exc

    resolved = pdf_path.resolve(strict=True)
    raw = resolved.read_bytes()
    reader = PdfReader(BytesIO(raw))
    text = _plain("\n".join(page.extract_text() or "" for page in reader.pages))
    errors: list[str] = []

    watch_segments: dict[str, str] = {}
    watch_anchors = [f"{watch['id']} - {watch['name']}" for watch in watches]
    for index, watch in enumerate(watches):
        next_anchor = watch_anchors[index + 1] if index + 1 < len(watches) else "Tracked horizon signals"
        segment = _unique_pdf_segment(text, watch_anchors[index], next_anchor)
        if segment is None:
            errors.append("watch_record_segment_missing_or_ambiguous")
        else:
            watch_segments[str(watch["id"])] = segment

    signal_segments: dict[str, str] = {}
    signal_anchors = [f"{signal['id']} - {signal['title']}" for signal in signals]
    for index, signal in enumerate(signals):
        next_anchor = (
            signal_anchors[index + 1] if index + 1 < len(signals) else "10. Limitations and acceptance disposition"
        )
        segment = _unique_pdf_segment(text, signal_anchors[index], next_anchor)
        if segment is None:
            errors.append("signal_record_segment_missing_or_ambiguous")
        else:
            signal_segments[str(signal["id"])] = segment

    signal_labels = {
        "disposition": "Disposition",
        "maturity": "Maturity",
        "next_review_rule": "Next review rule",
        "business_relevance": "Business relevance",
        "current_coverage": "Current coverage",
        "rationale": "Rationale",
    }
    rendered_rows = expected["rendered_observations"]
    for row in rendered_rows:
        rule_id = row["rule_id"]
        facet_path = row["facet_path"]
        value = row["observed_value"]
        if rule_id == "horizon.root" and facet_path == "promise":
            if f"Advisory only {_plain(value)}" not in text:
                errors.append("root_promise_projection_missing")
        elif rule_id == "horizon.watch_family":
            segment = watch_segments.get(str(row["record_identity"]), "")
            label = {
                "authority_scope": "Authority scope",
                "review_cadence": "Review cadence",
                "engine_ingestion": "Engine ingestion",
            }.get(str(facet_path))
            if label is None or f"{label}: {_plain(value)}" not in segment:
                errors.append("watch_observation_projection_missing")
        elif rule_id == "horizon.signal" and facet_path == "promotion_criteria":
            segment = signal_segments.get(str(row["record_identity"]), "")
            criteria = value if isinstance(value, list) else []
            positions = [segment.find(f"{index}. {_plain(item)}") for index, item in enumerate(criteria, start=1)]
            if not positions or any(position < 0 for position in positions) or positions != sorted(positions):
                errors.append("signal_ordered_array_projection_missing")
        elif rule_id == "horizon.signal":
            segment = signal_segments.get(str(row["record_identity"]), "")
            label = signal_labels.get(str(facet_path))
            if label is None or f"{label}: {_plain(value)}" not in segment:
                errors.append("signal_observation_projection_missing")
        else:
            errors.append("unrecognized_rendered_observation")

    root_role = _plain(horizon["content_role"])
    root_support = _plain(horizon["support_claim"])
    root_mutates = _plain(horizon["mutates_assessment_truth"]).lower()
    safety_fragments: dict[tuple[str, str], str] = {
        ("horizon.root", "@root"): f"root {root_role} {root_support} {root_mutates}"
    }
    safety_fragments.update(
        {
            ("horizon.watch_family", str(watch["id"])): (
                f"watch: {_plain(watch['id'])} {_plain(watch['content_role'])} "
                f"{root_support} (root-bound) {root_mutates} (root-bound)"
            )
            for watch in watches
        }
    )
    safety_fragments.update(
        {
            ("horizon.signal", str(signal["id"])): (
                f"signal: {_plain(signal['id'])} {_plain(signal['content_role'])} "
                f"{_plain(signal['support_claim'])} {root_mutates} (root-bound)"
            )
            for signal in signals
        }
    )
    for row in expected["safety_observations"]:
        fragment = safety_fragments.get((str(row["rule_id"]), str(row["record_identity"])))
        if fragment is None or fragment not in text:
            errors.append("safety_observation_projection_missing")

    if errors:
        raise ValueError("PDF horizon sink verification failed: " + ", ".join(sorted(set(errors))))
    observation_digest = sha256_bytes(canonical_json(expected))
    pdf_digest = sha256_bytes(raw)
    verification_material = {
        "verdict": "PASS",
        "pdf_sha256": pdf_digest,
        "observation_digest": observation_digest,
        "rendered_observation_count": len(rendered_rows),
        "safety_observation_count": len(expected["safety_observations"]),
    }
    return PdfHorizonSinkVerification(
        verdict="PASS",
        observation_digest=observation_digest,
        verification_digest=sha256_bytes(canonical_json(verification_material)),
        pdf_sha256=pdf_digest,
        rendered_observation_count=len(rendered_rows),
        safety_observation_count=len(expected["safety_observations"]),
    )


def _state_color(state: str) -> colors.Color:
    return {
        "current": _GREEN,
        "partial": colors.HexColor("#9A6810"),
        "missing": _RED,
        "gated": colors.HexColor("#7357A8"),
        "excluded": _MUTED,
        "unknown": colors.HexColor("#6F5B4B"),
        "pass": _GREEN,
        "passed": _GREEN,
        "blocked": _RED,
        "fail": _RED,
        "failed": _RED,
    }.get(state.lower(), _MUTED)


def _styles() -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    body = ParagraphStyle(
        "AtlasBody",
        parent=sample["BodyText"],
        fontName="Helvetica",
        fontSize=8.7,
        leading=12,
        textColor=_INK,
        spaceAfter=5,
        splitLongWords=True,
        allowWidows=False,
        allowOrphans=False,
    )
    return {
        "body": body,
        "small": ParagraphStyle(
            "AtlasSmall",
            parent=body,
            fontSize=7.3,
            leading=9.4,
            textColor=_MUTED,
            spaceAfter=3,
        ),
        "bullet": ParagraphStyle(
            "AtlasBullet",
            parent=body,
            leftIndent=11,
            firstLineIndent=-7,
            spaceAfter=3,
        ),
        "micro": ParagraphStyle(
            "AtlasMicro",
            parent=body,
            fontSize=6.2,
            leading=7.7,
            textColor=_MUTED,
            spaceAfter=0,
        ),
        "mono": ParagraphStyle(
            "AtlasMono",
            parent=body,
            fontName="Courier",
            fontSize=6.6,
            leading=8.3,
            textColor=_INK,
            splitLongWords=True,
            spaceAfter=0,
        ),
        "h1": ParagraphStyle(
            "AtlasHeading1",
            parent=sample["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=21,
            textColor=_NAVY,
            spaceBefore=10,
            spaceAfter=9,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "AtlasHeading2",
            parent=sample["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12.5,
            leading=15,
            textColor=_NAVY_2,
            spaceBefore=9,
            spaceAfter=5,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "AtlasHeading3",
            parent=sample["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=9.4,
            leading=12,
            textColor=_INK,
            spaceBefore=7,
            spaceAfter=3,
            keepWithNext=True,
        ),
        "cover_kicker": ParagraphStyle(
            "AtlasCoverKicker",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            tracking=1.4,
            textColor=_CYAN,
            alignment=TA_LEFT,
        ),
        "cover_title": ParagraphStyle(
            "AtlasCoverTitle",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=30,
            leading=33,
            textColor=_WHITE,
            alignment=TA_LEFT,
            spaceAfter=12,
        ),
        "cover_subtitle": ParagraphStyle(
            "AtlasCoverSubtitle",
            parent=body,
            fontSize=11,
            leading=15,
            textColor=colors.HexColor("#C7D6E0"),
        ),
        "cover_meta": ParagraphStyle(
            "AtlasCoverMeta",
            parent=body,
            fontName="Courier",
            fontSize=7.2,
            leading=10,
            textColor=_WHITE,
        ),
        "callout": ParagraphStyle(
            "AtlasCallout",
            parent=body,
            fontSize=8.4,
            leading=11.4,
            textColor=_INK,
        ),
        "toc": ParagraphStyle(
            "AtlasTOC",
            parent=body,
            fontSize=9,
            leading=13,
            leftIndent=0,
            firstLineIndent=0,
        ),
        "toc2": ParagraphStyle(
            "AtlasTOC2",
            parent=body,
            fontSize=8,
            leading=11,
            leftIndent=14,
            firstLineIndent=0,
            textColor=_MUTED,
        ),
        "table_head": ParagraphStyle(
            "AtlasTableHead",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=7.2,
            leading=9,
            textColor=_WHITE,
            spaceAfter=0,
        ),
        "table": ParagraphStyle(
            "AtlasTable",
            parent=body,
            fontSize=7.1,
            leading=9,
            spaceAfter=0,
        ),
        "table_mono": ParagraphStyle(
            "AtlasTableMono",
            parent=body,
            fontName="Courier",
            fontSize=6.2,
            leading=7.7,
            splitLongWords=True,
            spaceAfter=0,
        ),
        "center": ParagraphStyle(
            "AtlasCenter",
            parent=body,
            alignment=TA_CENTER,
        ),
    }


class _InvariantCanvas(canvas.Canvas):
    def __init__(self, *args: Any, metadata: dict[str, str], **kwargs: Any) -> None:
        kwargs["invariant"] = 1
        kwargs["pageCompression"] = 1
        super().__init__(*args, **kwargs)
        self.setTitle(metadata["title"])
        self.setAuthor(metadata["author"])
        self.setSubject(metadata["subject"])
        self.setKeywords(metadata["keywords"])
        self.setCreator(metadata["creator"])
        self._doc.Catalog.Lang = PDFString("en-US")
        self._doc.Catalog.PageMode = PDFName("UseOutlines")


class _AtlasDocTemplate(BaseDocTemplate):
    def __init__(
        self,
        filename: str,
        *,
        source_commit: str,
        metadata: dict[str, str],
        **kwargs: Any,
    ) -> None:
        super().__init__(
            filename,
            pagesize=A4,
            leftMargin=_LEFT,
            rightMargin=_RIGHT,
            topMargin=_TOP,
            bottomMargin=_BOTTOM,
            title=metadata["title"],
            author=metadata["author"],
            subject=metadata["subject"],
            keywords=metadata["keywords"],
            creator=metadata["creator"],
            **kwargs,
        )
        self.source_commit = source_commit
        self._bookmark_counts: dict[str, int] = {}
        frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            id="atlas-body",
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        )
        self.addPageTemplates([PageTemplate(id="atlas", frames=[frame], onPage=self._draw_page)])

    def beforeDocument(self) -> None:  # noqa: N802 - ReportLab hook name
        self._bookmark_counts = {}

    def _draw_page(self, canv: canvas.Canvas, doc: BaseDocTemplate) -> None:
        canv.saveState()
        if doc.page > 1:
            canv.setStrokeColor(_LINE)
            canv.setLineWidth(0.45)
            canv.line(_LEFT, _PAGE_HEIGHT - 13 * mm, _PAGE_WIDTH - _RIGHT, _PAGE_HEIGHT - 13 * mm)
            canv.setFillColor(_MUTED)
            canv.setFont("Helvetica-Bold", 6.7)
            canv.drawString(_LEFT, _PAGE_HEIGHT - 10.2 * mm, "ATLAS / MASTER REFERENCE")
            canv.setFont("Courier", 6.2)
            canv.drawRightString(
                _PAGE_WIDTH - _RIGHT,
                _PAGE_HEIGHT - 10.2 * mm,
                f"SOURCE {self.source_commit[:12]}",
            )
        canv.setStrokeColor(_LINE)
        canv.setLineWidth(0.45)
        canv.line(_LEFT, 11.5 * mm, _PAGE_WIDTH - _RIGHT, 11.5 * mm)
        canv.setFillColor(_MUTED)
        canv.setFont("Helvetica", 6.5)
        canv.drawString(
            _LEFT,
            7.5 * mm,
            "PRIVATE / READ-ONLY / CLIENT-DATA INGESTION PROHIBITED",
        )
        canv.drawRightString(_PAGE_WIDTH - _RIGHT, 7.5 * mm, f"Page {doc.page}")
        canv.restoreState()

    def afterFlowable(self, flowable: Flowable) -> None:  # noqa: N802 - ReportLab hook name
        if not isinstance(flowable, Paragraph):
            return
        levels = {"AtlasHeading1": 0, "AtlasHeading2": 1}
        level = levels.get(flowable.style.name)
        if level is None:
            return
        title = flowable.getPlainText()
        stem = hashlib.sha256(f"{level}:{title}".encode("utf-8")).hexdigest()[:16]
        occurrence = self._bookmark_counts.get(stem, 0)
        self._bookmark_counts[stem] = occurrence + 1
        key = f"atlas-{stem}-{occurrence}"
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(title, key, level=level, closed=level > 0)
        self.notify("TOCEntry", (level, title, self.page, key))


def _paragraph(value: object, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_markup(value), style)


def _rich(value: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(value, style)


def _heading(value: object, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_markup(value), style)


def _callout(title: str, body: str, styles: dict[str, ParagraphStyle], *, color: colors.Color = _CYAN) -> Table:
    content = _rich(
        f"<b>{_markup(title)}</b><br/>{_markup(body)}",
        styles["callout"],
    )
    table = Table([["", content]], colWidths=[3.2 * mm, _FRAME_WIDTH - 3.2 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 0), color),
                ("BACKGROUND", (1, 0), (1, 0), _PAPER),
                ("BOX", (0, 0), (-1, -1), 0.5, _LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LEFTPADDING", (1, 0), (1, 0), 9),
                ("RIGHTPADDING", (1, 0), (1, 0), 9),
            ]
        )
    )
    return table


def _table(
    headers: Sequence[str],
    rows: Sequence[Sequence[object]],
    widths: Sequence[float],
    styles: dict[str, ParagraphStyle],
    *,
    monospace_columns: Iterable[int] = (),
) -> LongTable:
    if len(headers) != len(widths) or any(len(row) != len(headers) for row in rows):
        raise ValueError("table shape does not match headers")
    if sum(widths) > _FRAME_WIDTH + 0.01:
        raise ValueError("table widths exceed the document frame")
    mono = set(monospace_columns)
    data: list[list[Paragraph]] = [[_paragraph(header, styles["table_head"]) for header in headers]]
    for row in rows:
        data.append(
            [
                _paragraph(value, styles["table_mono"] if column in mono else styles["table"])
                for column, value in enumerate(row)
            ]
        )
    table = LongTable(
        data,
        colWidths=list(widths),
        repeatRows=1,
        hAlign="LEFT",
        splitByRow=1,
        spaceAfter=7,
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _NAVY_2),
                ("TEXTCOLOR", (0, 0), (-1, 0), _WHITE),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_WHITE, _PAPER]),
                ("GRID", (0, 0), (-1, -1), 0.35, _LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _bullet_lines(values: Iterable[object], styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    rows: list[Flowable] = []
    for value in values:
        clean = _plain(value)
        if clean:
            rows.append(_paragraph(f"- {clean}", styles["bullet"]))
    if not rows:
        rows.append(_paragraph("None declared.", styles["small"]))
    return rows


def _numbered_lines(values: Sequence[str], styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    return [_paragraph(f"{index}. {value}", styles["bullet"]) for index, value in enumerate(values, start=1)]


def _load_json_object(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8", errors="strict"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _load_architecture(
    content: ContentBundle,
    architecture_path: Path | None,
    architecture_bytes: bytes | None = None,
) -> tuple[dict[str, Any] | None, str]:
    if architecture_bytes is not None:
        if architecture_path is not None:
            raise ValueError("choose architecture_path or architecture_bytes, not both")
        try:
            value = json.loads(architecture_bytes.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("architecture bytes are not valid UTF-8 JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("architecture contract is not an object")
        if value.get("schema_version") != "2.0.0":
            raise ValueError("architecture contract has an unsupported schema")
        errors = validate_contract(value)
        if errors:
            raise ValueError(f"architecture contract is invalid: {'; '.join(errors)}")
        return value, sha256_bytes(architecture_bytes)
    candidate = architecture_path
    if candidate is None:
        discovered = content.root.parent / "governance" / "architecture.json"
        if discovered.is_file():
            candidate = discovered
    if candidate is None:
        return None, "not supplied"
    candidate = candidate.resolve(strict=True)
    raw = candidate.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("architecture contract is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("architecture contract is not an object")
    if value.get("schema_version") != "2.0.0":
        raise ValueError("architecture contract has an unsupported schema")
    errors = validate_contract(value)
    if errors:
        raise ValueError(f"architecture contract is invalid: {'; '.join(errors)}")
    return value, sha256_bytes(raw)


def _load_release_context(release_dir: Path | None, bundle: CompilerBundle) -> dict[str, Any] | None:
    if release_dir is None:
        return None
    root = release_dir.resolve(strict=True)
    manifest = _load_json_object(root / "release-manifest.json")
    binding = manifest.get("source_binding")
    if not isinstance(binding, dict):
        raise ValueError("release manifest has no source binding")
    if (
        binding.get("source_commit") != bundle.source_commit
        or binding.get("source_tree_digest") != bundle.source_tree_digest
    ):
        raise ValueError("release directory does not match the compiler source binding")
    inventory_path = root / "artifact-inventory.json"
    inventory = _load_json_object(inventory_path) if inventory_path.is_file() else None
    if inventory is not None and (
        inventory.get("source_commit") != bundle.source_commit
        or inventory.get("source_tree_digest") != bundle.source_tree_digest
    ):
        raise ValueError("artifact inventory does not match the compiler source binding")
    sbom_path = root / "bom.cdx.json"
    sbom = _load_json_object(sbom_path) if sbom_path.is_file() else None
    return {"manifest": manifest, "inventory": inventory, "sbom": sbom}


def _validate_bindings(bundle: CompilerBundle) -> None:
    if bundle.manifest.get("status") != "complete":
        raise ValueError("compiler bundle is not complete")
    if bundle.manifest.get("tracked_worktree_dirty") is not False:
        raise ValueError("PDF requires an exact clean compiler projection")
    if bundle.completeness.get("source_commit") != bundle.source_commit:
        raise ValueError("completeness ledger commit differs from compiler manifest")
    if bundle.completeness.get("source_tree_digest") != bundle.source_tree_digest:
        raise ValueError("completeness ledger tree differs from compiler manifest")
    invariants = _items(bundle.completeness.get("invariants"))
    if not invariants or any(item.get("passed") is not True for item in invariants):
        raise ValueError("PDF requires all hard completeness invariants to pass")


def _input_digest(
    bundle: CompilerBundle,
    content: ContentBundle,
    architecture: dict[str, Any] | None,
    release_context: dict[str, Any] | None,
) -> str:
    value = {
        "compiler_manifest": bundle.manifest,
        "completeness": bundle.completeness,
        "curated": {
            "core": content.core,
            "capabilities": content.capabilities,
            "governance": content.governance,
            "horizon": content.horizon,
        },
        "architecture": architecture,
        "release_manifest": release_context["manifest"] if release_context else None,
        "artifact_inventory": release_context["inventory"] if release_context else None,
    }
    return sha256_bytes(canonical_json(value))


def _cover(
    bundle: CompilerBundle,
    content: ContentBundle,
    input_digest: str,
    styles: dict[str, ParagraphStyle],
) -> list[Flowable]:
    as_of = _plain(content.core.get("as_of") or content.core.get("catalog_version") or "undated")
    acceptance = _items(bundle.completeness.get("acceptance_gates"))
    failed = [item for item in acceptance if item.get("passed") is not True]
    status = f"BLOCK - {len(failed)} semantic acceptance gate(s) open; independent verification pending"
    hero = Table(
        [
            [_paragraph("ATLAS / WHOLE-REPOSITORY ACCOUNTING", styles["cover_kicker"])],
            [_paragraph("Master Reference", styles["cover_title"])],
            [
                _paragraph(
                    "A source-bound owner, engineering, assurance, and enhancement reference. "
                    "Structural completeness is shown separately from behavioral proof.",
                    styles["cover_subtitle"],
                )
            ],
            [Spacer(1, 13 * mm)],
            [_paragraph(f"INDEPENDENT VERIFICATION VERDICT: {status}", styles["cover_kicker"])],
            [
                _rich(
                    f"Source commit&nbsp;&nbsp;{_markup(bundle.source_commit)}<br/>"
                    f"Source tree&nbsp;&nbsp;&nbsp;&nbsp;{_markup(bundle.source_tree_digest)}<br/>"
                    f"Input digest&nbsp;&nbsp;&nbsp;{_markup(input_digest)}<br/>"
                    f"Catalog as-of&nbsp;&nbsp;{_markup(as_of)}",
                    styles["cover_meta"],
                )
            ],
        ],
        colWidths=[_FRAME_WIDTH],
        rowHeights=[None, None, None, 17 * mm, None, None],
        hAlign="LEFT",
    )
    hero.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _NAVY),
                ("BOX", (0, 0), (-1, -1), 0.8, _NAVY_2),
                ("LEFTPADDING", (0, 0), (-1, -1), 15),
                ("RIGHTPADDING", (0, 0), (-1, -1), 15),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return [
        Spacer(1, 19 * mm),
        hero,
        Spacer(1, 12 * mm),
        _callout(
            "Reading contract",
            "This PDF is a navigational projection, not a second source of truth. It intentionally omits raw source text. "
            "Use the content-hashed Source Explorer for line-level content, and treat every BLOCKED or unknown state as real.",
            styles,
            color=_AMBER,
        ),
        PageBreak(),
    ]


def _contents(styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    toc = TableOfContents()
    toc.levelStyles = [styles["toc"], styles["toc2"]]
    return [
        _heading("Contents", styles["h1"]),
        _paragraph(
            "The bookmarks and table of contents are generated from this exact document. Major sections and domain dossiers are linkable in compatible readers.",
            styles["body"],
        ),
        Spacer(1, 4 * mm),
        toc,
        PageBreak(),
    ]


def _source_and_truth(
    bundle: CompilerBundle,
    content: ContentBundle,
    architecture_digest: str,
    input_digest: str,
    styles: dict[str, ParagraphStyle],
) -> list[Flowable]:
    story: list[Flowable] = [
        _heading("1. Source identity and truth contract", styles["h1"]),
        _callout(
            "Exact-source boundary",
            "The tracked Git tree is the project universe. Hard census invariants passing does not mean behavioral explanations, runtime traces, field evidence, or Level 4 human review are complete.",
            styles,
        ),
        Spacer(1, 3 * mm),
    ]
    source_rows = [
        ("Source commit", bundle.source_commit),
        ("HEAD tree object", bundle.manifest.get("head_tree_oid", "unknown")),
        ("Git index digest", bundle.manifest.get("index_digest", "unknown")),
        ("Source-tree digest", bundle.source_tree_digest),
        ("Tracked worktree", "clean" if bundle.manifest.get("tracked_worktree_dirty") is False else "dirty"),
        ("Compiler schema", bundle.manifest.get("schema_version", "unknown")),
        ("Architecture contract", architecture_digest),
        ("PDF input digest", input_digest),
        ("Renderer", f"ReportLab {REPORTLAB_VERSION}; invariant mode"),
    ]
    story.append(
        _table(("Binding", "Value"), source_rows, (43 * mm, _FRAME_WIDTH - 43 * mm), styles, monospace_columns=(1,))
    )
    truth = content.core.get("truth_contract", {})
    if isinstance(truth, dict):
        story.append(_heading("Truth rules", styles["h2"]))
        for key, value in sorted(truth.items()):
            story.append(_rich(f"<b>{_markup(key.replace('_', ' ').title())}:</b> {_markup(value)}", styles["body"]))
    story.extend(
        [
            _heading("Purpose and protected boundary", styles["h2"]),
            _paragraph(content.core.get("scope", "No scope declared."), styles["body"]),
            _paragraph(
                "Policy boundary: raw Vault pages and machine-local agent memory are outside the compiler corpus; restricted and binary payloads remain opaque. High-confidence allowlisted-text and generated-output scans found no matching credential patterns, while contextual, encoded, client/device, and container review remains pending. The reference is private, read-only, offline-capable, and cannot mutate the assessed estate.",
                styles["body"],
            ),
        ]
    )
    non_goals = _items(content.core.get("non_goals"))
    if non_goals:
        block: list[Flowable] = [_heading("Non-goals", styles["h2"])]
        block.extend(
            _bullet_lines(
                (item.get("statement", item.get("title", item.get("id"))) for item in non_goals),
                styles,
            )
        )
        story.append(KeepTogether(block))
    return story


def _completeness(bundle: CompilerBundle, styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    ledger = bundle.completeness
    census = ledger.get("census", {}) if isinstance(ledger.get("census"), dict) else {}
    parsing = ledger.get("parsing", {}) if isinstance(ledger.get("parsing"), dict) else {}
    semantic = ledger.get("semantic_accounting", {}) if isinstance(ledger.get("semantic_accounting"), dict) else {}
    graph = ledger.get("graphify", {}) if isinstance(ledger.get("graphify"), dict) else {}
    privacy = ledger.get("privacy", {}) if isinstance(ledger.get("privacy"), dict) else {}
    story: list[Flowable] = [
        _heading("2. Whole-repository completeness ledger", styles["h1"]),
        _callout(
            "Honest verdict",
            "The compiler may pass hard structural invariants while semantic acceptance remains blocked. This report preserves that distinction and never upgrades Level 1 mapping into Level 4 understanding.",
            styles,
            color=_AMBER,
        ),
        Spacer(1, 3 * mm),
    ]
    story.append(
        _table(
            ("Measure", "Actual"),
            [
                ("Tracked files", census.get("tracked_files", len(bundle.records.get("files", [])))),
                ("Classified files", census.get("classified_files", "unknown")),
                ("Safe full-exposure files", census.get("full_exposure_files", "unknown")),
                ("Metadata-only files", census.get("metadata_only_files", "unknown")),
                ("Expected nonblank safe lines", parsing.get("expected_nonblank_lines", "unknown")),
                ("Source line records", parsing.get("line_records", len(bundle.records.get("lines", [])))),
                ("Lines with explicit uncertainty", parsing.get("lines_with_explicit_unresolved_reasons", "unknown")),
                ("Symbol dossiers", semantic.get("symbol_dossiers", "unknown")),
                ("Critical/public symbols", semantic.get("critical_or_public_symbols", "unknown")),
                ("Critical Level 4 reviews", semantic.get("critical_level_four_reviews", "unknown")),
            ],
            (60 * mm, _FRAME_WIDTH - 60 * mm),
            styles,
        )
    )
    story.append(_heading("Machine record groups", styles["h2"]))
    group_rows = [
        (name, receipt.get("record_count", "unknown"))
        for name, receipt in sorted(bundle.manifest.get("groups", {}).items())
        if isinstance(receipt, dict)
    ]
    story.append(_table(("Record group", "Records"), group_rows, (90 * mm, _FRAME_WIDTH - 90 * mm), styles))
    story.append(_heading("Hard structural invariants", styles["h2"]))
    invariant_rows = [
        (
            item.get("name", "unnamed"),
            "PASS" if item.get("passed") is True else "FAIL",
            item.get("expected", ""),
            item.get("actual", ""),
        )
        for item in _items(ledger.get("invariants"))
    ]
    story.append(
        _table(
            ("Invariant", "Status", "Expected", "Actual"),
            invariant_rows,
            (84 * mm, 22 * mm, 28 * mm, _FRAME_WIDTH - 134 * mm),
            styles,
        )
    )
    acceptance = _items(ledger.get("acceptance_gates"))
    story.append(_heading("Semantic acceptance gates", styles["h2"]))
    if acceptance:
        acceptance_rows = [
            (
                item.get("name", "unnamed"),
                "PASS" if item.get("passed") is True else "BLOCKED",
                item.get("expected", ""),
                item.get("actual", ""),
            )
            for item in acceptance
        ]
        story.append(
            _table(
                ("Gate", "Status", "Expected", "Actual"),
                acceptance_rows,
                (84 * mm, 22 * mm, 28 * mm, _FRAME_WIDTH - 134 * mm),
                styles,
            )
        )
    else:
        story.append(
            _callout(
                "BLOCKED", "No semantic acceptance gates were emitted by this compiler bundle.", styles, color=_RED
            )
        )
    story.append(_heading("Semantic depth", styles["h2"]))
    line_depths = semantic.get("line_explanation_depth_counts", {})
    symbol_depths = semantic.get("symbol_explanation_depth_counts", {})
    depth_rows = []
    for depth in range(5):
        depth_rows.append(
            (
                f"Level {depth}",
                line_depths.get(str(depth), 0) if isinstance(line_depths, dict) else "unknown",
                symbol_depths.get(str(depth), 0) if isinstance(symbol_depths, dict) else "unknown",
                (
                    "inventoried"
                    if depth == 0
                    else "structurally mapped"
                    if depth == 1
                    else "behaviorally explained"
                    if depth == 2
                    else "verified by executable evidence"
                    if depth == 3
                    else "independently human-reviewed critical logic"
                ),
            )
        )
    story.append(
        _table(
            ("Depth", "Lines", "Symbols", "Meaning"),
            depth_rows,
            (22 * mm, 22 * mm, 24 * mm, _FRAME_WIDTH - 68 * mm),
            styles,
        )
    )
    story.append(_heading("Graphify projection", styles["h2"]))
    story.append(
        _table(
            ("Property", "Value"),
            [(key, value) for key, value in sorted(graph.items()) if not isinstance(value, (dict, list))],
            (58 * mm, _FRAME_WIDTH - 58 * mm),
            styles,
        )
    )
    story.append(
        _paragraph(
            "Graphify is structural advisory evidence. Extracted or inferred edges never become runtime truth without conformance evidence.",
            styles["small"],
        )
    )
    story.append(_heading("Privacy boundary", styles["h2"]))
    story.append(
        _table(
            ("Boundary", "Disposition"),
            [(key.replace("_", " "), value) for key, value in sorted(privacy.items())],
            (62 * mm, _FRAME_WIDTH - 62 * mm),
            styles,
        )
    )
    return story


def _outcomes(content: ContentBundle, styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    outcomes = _validated_outcomes(content)
    story: list[Flowable] = [
        PageBreak(),
        _heading("3. Product purpose and outcomes", styles["h1"]),
        _callout(
            _CORE_SECTION_MARKER_TITLE,
            _CORE_SECTION_MARKER_BODY,
            styles,
        ),
        Spacer(1, 3 * mm),
    ]
    for item in outcomes:
        story.append(CondPageBreak(35 * mm))
        story.append(_heading(f"{item['id']} - {item['title']}", styles["h2"]))
        story.append(_rich(f"<b>Success signal:</b> {_markup(item['success_signal'])}", styles["body"]))
    return story


def _capabilities(content: ContentBundle, styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    domains, entries = _validated_capabilities(content)
    counts = Counter(_plain(entry["state"]) for entry in entries)
    story: list[Flowable] = [
        PageBreak(),
        _heading("4. Closed Capability Catalog", styles["h1"]),
        _callout(
            "Finite denominator",
            _plain(
                content.capabilities.get(
                    "denominator_rule", "Catalog inclusion is a classification, not a support promise."
                )
            ),
            styles,
        ),
        Spacer(1, 3 * mm),
        _heading("Source-derived capability support contract", styles["h2"]),
        *[
            _rich(
                f"<b>entry_contract {field}:</b> {_markup(content.capabilities['entry_contract'][field])}",
                styles["small"],
            )
            for field in _CAPABILITY_CONTRACT_FIELDS
        ],
        Spacer(1, 2 * mm),
        _table(
            ("State", "Cells", "Interpretation"),
            [
                (state, count, "Truth classification; never an aggregate score")
                for state, count in sorted(counts.items())
            ],
            (38 * mm, 25 * mm, _FRAME_WIDTH - 63 * mm),
            styles,
        ),
    ]
    for domain in domains:
        domain_id = _plain(domain["id"])
        story.extend([PageBreak(), _heading(domain_id, styles["h2"])])
        domain_entries = domain["entries"]
        story.append(
            _paragraph(
                f"Declared cells: {len(domain_entries)}. Every cell remains linked to current owners or an explicit gap/disposition.",
                styles["small"],
            )
        )
        for entry in domain_entries:
            story.append(CondPageBreak(31 * mm))
            state = _plain(entry["state"])
            title = f"{entry['id']} - {entry['title']} [{state.upper()}]"
            story.append(_heading(title, styles["h3"]))
            story.append(
                _rich(f"<b>Current scope:</b> {_markup(entry['current_scope'])}", styles["body"])
            )
            if entry["id"] == _CAPABILITY_TRAINING_ID:
                story.append(
                    _rich(
                        "<b>Entry safety boundary:</b> "
                        f"content_role={_markup(entry['content_role'])}; "
                        f"mutates_assessment_truth={_markup(str(entry['mutates_assessment_truth']).lower())}",
                        styles["small"],
                    )
                )
            refs: list[str] = []
            owners = _strings(entry.get("owner_refs"))
            gaps = _strings(entry.get("gap_refs"))
            if owners:
                refs.append(f"Owners: {', '.join(owners)}")
            if gaps:
                refs.append(f"Gaps: {', '.join(gaps)}")
            if refs:
                story.append(_paragraph(" | ".join(refs), styles["small"]))
            bar = Table([[""]], colWidths=[_FRAME_WIDTH], rowHeights=[1.4])
            bar.setStyle(
                TableStyle(
                    [("BACKGROUND", (0, 0), (-1, -1), _state_color(state)), ("LINEBELOW", (0, 0), (-1, -1), 0, _WHITE)]
                )
            )
            story.append(bar)
    return story


def _governance(content: ContentBundle, styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    gaps = _items(content.governance.get("gaps"))
    decisions = _items(content.governance.get("decision_queue"))
    portfolio = content.governance.get("opportunity_portfolio", {})
    opportunities = _items(portfolio.get("items")) if isinstance(portfolio, dict) else []
    priorities = Counter(_plain(item.get("priority", "unprioritized")) for item in gaps)
    story: list[Flowable] = [
        PageBreak(),
        _heading("5. Delivery governance, gaps, and decisions", styles["h1"]),
        _table(
            ("Queue", "Count", "Meaning"),
            [
                ("Gaps", len(gaps), "Incomplete or explicitly excluded work with a disposition"),
                ("Decisions", len(decisions), "Human authority queue; recommendations do not self-approve"),
                ("Opportunities", len(opportunities), "Transparent multi-axis candidates; no opaque aggregate score"),
            ],
            (42 * mm, 22 * mm, _FRAME_WIDTH - 64 * mm),
            styles,
        ),
        _heading("Gap priority distribution", styles["h2"]),
        _table(
            ("Priority", "Gaps"),
            [(key, value) for key, value in sorted(priorities.items())],
            (60 * mm, _FRAME_WIDTH - 60 * mm),
            styles,
        ),
        _heading("Complete gap register", styles["h2"]),
    ]
    for gap in gaps:
        block = [
            _heading(f"{gap.get('id', 'gap.unknown')} - {gap.get('title', 'Untitled gap')}", styles["h3"]),
            _rich(
                f"<b>Priority:</b> {_markup(gap.get('priority', 'unprioritized'))} &nbsp; "
                f"<b>Disposition:</b> {_markup(gap.get('disposition', 'unknown'))} &nbsp; "
                f"<b>Owner:</b> {_markup(gap.get('owner_role', 'unassigned'))}",
                styles["small"],
            ),
            _paragraph(gap.get("problem", "No problem statement."), styles["body"]),
            _rich("<b>Smallest next actions</b>", styles["body"]),
        ]
        block.extend(_bullet_lines(_strings(gap.get("next_actions")), styles))
        block.append(_rich("<b>Acceptance evidence</b>", styles["body"]))
        block.extend(_bullet_lines(_strings(gap.get("acceptance_evidence")), styles))
        story.append(KeepTogether(block))
    for index, decision in enumerate(decisions):
        block = [
            _heading(
                f"{decision.get('id', 'decision.unknown')} - {decision.get('title', 'Untitled decision')}",
                styles["h3"],
            )
        ]
        for key in ("status", "authority", "current_recommendation"):
            block.append(
                _rich(
                    f"<b>{_markup(key.replace('_', ' ').title())}:</b> {_markup(decision.get(key, 'unknown'))}",
                    styles["body"],
                )
            )
        block.append(_rich("<b>Options</b>", styles["body"]))
        block.extend(_bullet_lines(_strings(decision.get("options")), styles))
        block.append(_rich("<b>Evidence needed</b>", styles["body"]))
        block.extend(_bullet_lines(_strings(decision.get("evidence_needed")), styles))
        if index == 0:
            block.insert(0, _heading("Human decision queue", styles["h2"]))
        story.append(KeepTogether(block))
    if not decisions:
        story.append(_heading("Human decision queue", styles["h2"]))
    story.append(_heading("Opportunity portfolio", styles["h2"]))
    if isinstance(portfolio, dict) and portfolio.get("ranking_rule"):
        story.append(_callout("Ranking rule", _plain(portfolio["ranking_rule"]), styles))
    for opportunity in opportunities:
        story.append(CondPageBreak(35 * mm))
        story.append(
            _heading(
                f"{opportunity.get('id', 'opportunity.unknown')} - {opportunity.get('title', 'Untitled opportunity')}",
                styles["h3"],
            )
        )
        axes = opportunity.get("axes", {})
        axes_text = (
            ", ".join(f"{key}={value}" for key, value in sorted(axes.items()))
            if isinstance(axes, dict)
            else "not declared"
        )
        story.append(
            _paragraph(
                f"Horizon: {opportunity.get('horizon', 'unknown')} | Axes: {axes_text} | Gaps: {', '.join(_strings(opportunity.get('gap_refs'))) or 'none'}",
                styles["small"],
            )
        )
        if opportunity.get("axis_notes"):
            story.append(_paragraph(opportunity["axis_notes"], styles["body"]))
    return story


def _architecture_and_invariants(
    content: ContentBundle,
    architecture: dict[str, Any] | None,
    styles: dict[str, ParagraphStyle],
) -> list[Flowable]:
    story: list[Flowable] = [PageBreak(), _heading("6. Architecture and protected invariants", styles["h1"])]
    if architecture is None:
        story.append(
            _callout(
                "Architecture contract unavailable",
                "No validated architecture.json was supplied. This is an explicit limitation, not an empty architecture.",
                styles,
                color=_RED,
            )
        )
    else:
        components = _items(architecture.get("components"))
        story.append(_heading("Components and trust zones", styles["h2"]))
        story.append(
            _table(
                ("Component", "Layer", "Trust zone", "Owned paths"),
                [
                    (
                        item.get("id", "unknown"),
                        item.get("layer", ""),
                        item.get("trust_zone", "unknown"),
                        ", ".join(_strings(item.get("paths"))),
                    )
                    for item in components
                ],
                (39 * mm, 15 * mm, 35 * mm, _FRAME_WIDTH - 89 * mm),
                styles,
                monospace_columns=(0, 3),
            )
        )
        story.append(_heading("Runtime phases", styles["h2"]))
        story.append(
            _table(
                ("Order", "Phase", "Required"),
                [
                    (item.get("order", ""), item.get("id", "unknown"), "yes" if item.get("required") is True else "no")
                    for item in _items(architecture.get("runtime_phases"))
                ],
                (22 * mm, 86 * mm, _FRAME_WIDTH - 108 * mm),
                styles,
            )
        )
        story.append(_heading("Forbidden dependencies", styles["h2"]))
        forbidden = _items(architecture.get("forbidden_edges"))
        story.append(
            _table(
                ("From", "To", "Reason"),
                [
                    (item.get("from", "unknown"), item.get("to", "unknown"), item.get("reason", "No reason declared."))
                    for item in forbidden
                ],
                (38 * mm, 38 * mm, _FRAME_WIDTH - 76 * mm),
                styles,
                monospace_columns=(0, 1),
            )
        )
        story.append(
            _paragraph(
                f"Allowed dependency edges declared: {len(architecture.get('allowed_edges', []))}. Edge semantics: {architecture.get('edge_semantics', 'not declared')}.",
                styles["small"],
            )
        )
    invariants = _items(content.governance.get("invariants"))
    story.append(_heading("Invariant catalog", styles["h2"]))
    if invariants:
        for invariant in invariants:
            block = [_heading(f"{invariant.get('id', 'invariant.unknown')}", styles["h3"])]
            for key in ("statement", "intent", "scope", "formal_rule", "residual_risk"):
                if invariant.get(key) is not None:
                    block.append(
                        _rich(
                            f"<b>{_markup(key.replace('_', ' ').title())}:</b> {_markup(invariant[key])}",
                            styles["body"],
                        )
                    )
            owners = _strings(invariant.get("owner_refs"))
            if owners:
                block.append(_paragraph(f"Owners: {', '.join(owners)}", styles["small"]))
            story.append(KeepTogether(block))
    else:
        story.append(_paragraph("No curated invariants were emitted.", styles["body"]))
    return story


def _source_explorer(bundle: CompilerBundle, styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    counts = {
        name: item.get("record_count", 0)
        for name, item in bundle.manifest.get("groups", {}).items()
        if isinstance(item, dict)
    }
    routes = [
        ("/source", "Complete tracked file tree, classification, depth, and uncertainty"),
        ("/source/[path]", "Content-hashed safe line view with semantic breadcrumbs"),
        ("/symbol/[id]", "Symbol purpose, callers, callees, effects, proof, and impact"),
        ("/data/[id]", "Structured dataset schema, provenance, denominator, and consumers"),
        ("/test/[id]", "Proof dossier, fixture provenance, asserted invariants, and limits"),
        ("/workflow/[id]", "Trigger, permissions, steps, artifacts, secrets boundary, and failure effects"),
    ]
    return [
        _heading("7. Whole-repository Source Explorer", styles["h1"]),
        _callout(
            "Why source text is not printed here",
            "The PDF preserves repository accounting without duplicating hundreds of thousands of source lines. Safe source is loaded only from content-hashed per-file chunks; restricted content remains opaque. This keeps the document usable and avoids a second, stale source corpus.",
            styles,
            color=_AMBER,
        ),
        Spacer(1, 3 * mm),
        _table(
            ("Route", "Question answered"), routes, (48 * mm, _FRAME_WIDTH - 48 * mm), styles, monospace_columns=(0,)
        ),
        _heading("Line and symbol traversal", styles["h2"]),
        _paragraph(
            "A line link resolves its containing syntax unit, symbol, owner, behavior group, inputs and outputs, influenced claims, callers and dependencies, tests, runtime-trace state, GUI or artifact consumers, security/privacy effect, historical status, explanation depth, and unresolved reasons.",
            styles["body"],
        ),
        _paragraph(
            "Impact traversal is evidence-bounded. Missing runtime or coverage data is shown as not collected or structural-only; it is never inferred as verified.",
            styles["body"],
        ),
        _heading("Explorer denominators", styles["h2"]),
        _table(
            ("Entity", "Records"),
            [
                (name, counts.get(name, 0))
                for name in (
                    "files",
                    "lines",
                    "symbols",
                    "routes",
                    "components",
                    "tests",
                    "workflows",
                    "datasets",
                    "binaries",
                    "dependencies",
                    "claims",
                )
            ],
            (70 * mm, _FRAME_WIDTH - 70 * mm),
            styles,
        ),
    ]


def _release_section(
    bundle: CompilerBundle,
    release_context: dict[str, Any] | None,
    styles: dict[str, ParagraphStyle],
) -> list[Flowable]:
    story: list[Flowable] = [PageBreak(), _heading("8. Release, export, and preservation", styles["h1"])]
    if release_context is None:
        story.append(
            _callout(
                "Release context not supplied",
                "This PDF is bound to the validated compiler and curated content. It was generated before or independently of an emitted release directory, so artifact receipts and signing state must be read from the eventual release-manifest.json.",
                styles,
                color=_AMBER,
            )
        )
        story.append(
            _paragraph(
                "Independent verification verdict: BLOCK. Signature, visual review, and publication authority are not established by PDF generation.",
                styles["body"],
            )
        )
        return story
    manifest = release_context["manifest"]
    inventory = release_context.get("inventory")
    sbom = release_context.get("sbom")
    story.append(
        _table(
            ("Property", "Value"),
            [
                ("Release status", manifest.get("release_status", "unknown")),
                ("Publication status", manifest.get("publication_status", "unknown")),
                ("Independent verification", manifest.get("independent_verification_verdict", "BLOCK")),
                ("Source commit", bundle.source_commit),
                ("Source-tree digest", bundle.source_tree_digest),
                ("SBOM components", len(sbom.get("components", [])) if isinstance(sbom, dict) else "not supplied"),
            ],
            (56 * mm, _FRAME_WIDTH - 56 * mm),
            styles,
            monospace_columns=(1,),
        )
    )
    gates = manifest.get("gates", {})
    if isinstance(gates, dict):
        story.append(_heading("Executable release gates", styles["h2"]))
        story.append(
            _table(
                ("Gate", "State"),
                [(key, value) for key, value in sorted(gates.items())],
                (83 * mm, _FRAME_WIDTH - 83 * mm),
                styles,
            )
        )
    artifacts = _items(inventory.get("artifacts")) if isinstance(inventory, dict) else []
    story.append(_heading("Artifact inventory", styles["h2"]))
    if artifacts:
        story.append(
            _table(
                ("Path", "Role", "Bytes", "SHA-256"),
                [
                    (
                        item.get("path", "unknown"),
                        item.get("role", "unknown"),
                        item.get("bytes", ""),
                        item.get("sha256", "unknown"),
                    )
                    for item in artifacts
                ],
                (54 * mm, 33 * mm, 20 * mm, _FRAME_WIDTH - 107 * mm),
                styles,
                monospace_columns=(0, 3),
            )
        )
    else:
        story.append(_paragraph("No validated artifact inventory was supplied.", styles["body"]))
    story.append(_heading("Signing and preservation boundary", styles["h2"]))
    story.extend(
        _bullet_lines(
            [
                "Unsigned builds remain previews; a PDF digest is not an owner signature.",
                "An offline owner-controlled Ed25519 private key must remain outside the repository.",
                "Public publication requires separate explicit authority even after cryptographic verification.",
                "Preservation includes source, schemas/upcasters, manifest/ledger, signatures, offline viewer, dependency caches, fixtures, and recovery instructions.",
            ],
            styles,
        )
    )
    return story


def _horizon(content: ContentBundle, styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    horizon = content.horizon
    watches, signals = _validated_horizon(horizon)
    root_role = str(horizon["content_role"])
    root_support = str(horizon["support_claim"])
    root_mutates = str(horizon["mutates_assessment_truth"]).lower()
    boundary_rows: list[tuple[str, str, str, str]] = [
        ("root", root_role, root_support, root_mutates),
    ]
    boundary_rows.extend(
        (
            f"watch: {watch['id']}",
            str(watch["content_role"]),
            f"{root_support} (root-bound)",
            f"{root_mutates} (root-bound)",
        )
        for watch in watches
    )
    boundary_rows.extend(
        (
            f"signal: {signal['id']}",
            str(signal["content_role"]),
            str(signal["support_claim"]),
            f"{root_mutates} (root-bound)",
        )
        for signal in signals
    )
    story: list[Flowable] = [
        PageBreak(),
        _heading("9. Open-world Horizon Register", styles["h1"]),
        _callout(
            "Advisory only",
            str(horizon["promise"]),
            styles,
            color=_AMBER,
        ),
        Spacer(1, 3 * mm),
        _heading("Source-derived safety boundary", styles["h2"]),
        _paragraph(
            "Every row below is bound to the root or named source record. "
            "Root-bound cells inherit the displayed root value; missing or mixed boundaries refuse PDF generation.",
            styles["small"],
        ),
        _table(
            ("Source record", "Content role", "Support claim", "Mutates assessment truth"),
            boundary_rows,
            (67 * mm, 28 * mm, 31 * mm, _FRAME_WIDTH - 126 * mm),
            styles,
            monospace_columns=(0,),
        ),
        _heading("Watch families", styles["h2"]),
    ]
    for watch in watches:
        story.append(
            KeepTogether(
                [
                    _heading(f"{watch['id']} - {watch['name']}", styles["h3"]),
                    _rich(f"<b>Authority scope:</b> {_markup(watch['authority_scope'])}", styles["body"]),
                    _paragraph(
                        f"Review cadence: {watch['review_cadence']} | Content role: {watch['content_role']} | Engine ingestion: {watch['engine_ingestion']}",
                        styles["small"],
                    ),
                    _paragraph(f"Primary source: {watch['source_url']}", styles["mono"]),
                ]
            )
        )
    story.extend([PageBreak(), _heading("Tracked horizon signals", styles["h2"])])
    for signal in signals:
        block: list[Flowable] = [
            _heading(f"{signal['id']} - {signal['title']}", styles["h3"]),
            _paragraph(
                f"Disposition: {signal['disposition']} | Maturity: {signal['maturity']} | "
                f"Next review rule: {signal['next_review_rule']}",
                styles["small"],
            ),
        ]
        for field, label in (
            ("business_relevance", "Business relevance"),
            ("current_coverage", "Current coverage"),
            ("rationale", "Rationale"),
        ):
            block.append(_rich(f"<b>{label}:</b> {_markup(signal[field])}", styles["body"]))
        block.append(_rich("<b>Promotion criteria (source order)</b>", styles["body"]))
        block.extend(_numbered_lines(signal["promotion_criteria"], styles))
        story.append(KeepTogether(block))
    return story


def _limitations(
    bundle: CompilerBundle,
    content: ContentBundle,
    release_context: dict[str, Any] | None,
    styles: dict[str, ParagraphStyle],
) -> list[Flowable]:
    failed = [item for item in _items(bundle.completeness.get("acceptance_gates")) if item.get("passed") is not True]
    limits = [
        "Structural line mapping is not behavioral or human-reviewed understanding.",
        "Coverage percentages and static reachability are not correctness proof.",
        "Graphify extraction or inference is not runtime truth.",
        "Synthetic evidence is not field validation.",
        "Catalog inclusion is not an implementation claim.",
        "Missing evidence is never rendered as zero, healthy, or not applicable.",
        "The PDF intentionally contains no raw source text and is not a substitute for Source Explorer.",
        "Deterministic bytes require the same validated inputs and compatible ReportLab/toolchain version.",
        "Visual review, assistive-technology review, signature, and publication authority remain separate gates.",
    ]
    if release_context:
        limits.extend(_strings(release_context["manifest"].get("honest_limits")))
    story: list[Flowable] = [
        PageBreak(),
        _heading("10. Limitations and acceptance disposition", styles["h1"]),
        _callout(
            "Final document verdict: BLOCK",
            "This generated reference is a review artifact. It cannot self-approve its semantic explanations, visual quality, accessibility, signature, or publication authority.",
            styles,
            color=_RED,
        ),
        Spacer(1, 3 * mm),
        _heading("Open semantic gates", styles["h2"]),
    ]
    if failed:
        for item in failed:
            story.append(
                _rich(
                    f"<b>BLOCKED - {_markup(item.get('name', 'unnamed gate'))}</b>: expected {_markup(item.get('expected', 'unknown'))}; actual {_markup(item.get('actual', 'unknown'))}.",
                    styles["body"],
                )
            )
    else:
        story.append(
            _paragraph(
                "No failed compiler semantic gate is recorded, but independent PDF, security, accessibility, release-signing, and publication reviews still prevent self-approval.",
                styles["body"],
            )
        )
    story.append(_heading("Standing truth limits", styles["h2"]))
    story.extend(_bullet_lines(dict.fromkeys(limits), styles))
    story.append(_heading("Independent review required", styles["h2"]))
    story.extend(
        _bullet_lines(
            [
                "File/line census and exclusion challenge.",
                "Authority, claim, and current-versus-historical reconciliation.",
                "Architecture conformance and forbidden-edge challenge.",
                "Protocol/design breadth and capability-gap honesty.",
                "Security, privacy, accessibility, and performance review.",
                "Offline/export receipts, signing, agent-envelope, and recovery exercises.",
            ],
            styles,
        )
    )
    story.append(Spacer(1, 6 * mm))
    story.append(
        _paragraph(
            f"End of source-bound Master Reference for commit {bundle.source_commit}. Unknowns remain explicit.",
            styles["small"],
        )
    )
    return story


def build_master_reference_pdf(
    bundle: CompilerBundle,
    content: ContentBundle,
    output_path: Path,
    *,
    release_dir: Path | None = None,
    architecture_path: Path | None = None,
    architecture_bytes: bytes | None = None,
) -> PdfReportResult:
    """Render a deterministic PDF from validated inputs without source text.

    Existing outputs and in-progress files are never overwritten.  The result
    remains a non-releaseable review artifact until independent visual review,
    semantic acceptance, signing, and publication gates clear elsewhere.
    """

    _validate_bindings(bundle)
    core_sink_observations = pdf_core_sink_observations(content)
    capability_sink_observations = pdf_capability_sink_observations(content)
    horizon_sink_observations = pdf_horizon_sink_observations(content.horizon)
    architecture, architecture_digest = _load_architecture(
        content,
        architecture_path,
        architecture_bytes,
    )
    release_context = _load_release_context(release_dir, bundle)
    digest = _input_digest(bundle, content, architecture, release_context)
    output_path = output_path.resolve()
    if output_path.exists():
        raise FileExistsError(f"PDF output already exists: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.building")
    if temporary.exists():
        raise FileExistsError(f"PDF build path already exists: {temporary}")

    styles = _styles()
    metadata = {
        "title": "Atlas Master Reference - Whole-Repository Accounting",
        "author": "Atlas repository",
        "subject": f"Source commit {bundle.source_commit}; source-tree digest {bundle.source_tree_digest}; independent verification BLOCK",
        "keywords": "Atlas, master reference, whole repository, source bound, read only, non-releaseable",
        "creator": f"Atlas deterministic PDF renderer / ReportLab {REPORTLAB_VERSION}",
    }
    story: list[Flowable] = []
    story.extend(_cover(bundle, content, digest, styles))
    story.extend(_contents(styles))
    story.extend(_source_and_truth(bundle, content, architecture_digest, digest, styles))
    story.extend(_completeness(bundle, styles))
    story.extend(_outcomes(content, styles))
    story.extend(_capabilities(content, styles))
    story.extend(_governance(content, styles))
    story.extend(_architecture_and_invariants(content, architecture, styles))
    story.extend(_source_explorer(bundle, styles))
    story.extend(_release_section(bundle, release_context, styles))
    story.extend(_horizon(content, styles))
    story.extend(_limitations(bundle, content, release_context, styles))

    document = _AtlasDocTemplate(
        str(temporary),
        source_commit=bundle.source_commit,
        metadata=metadata,
    )
    canvasmaker = lambda *args, **kwargs: _InvariantCanvas(*args, metadata=metadata, **kwargs)  # noqa: E731
    inspection: PdfInspection
    core_sink_verification: PdfCoreSinkVerification
    capability_sink_verification: PdfCapabilitySinkVerification
    horizon_sink_verification: PdfHorizonSinkVerification
    try:
        document.multiBuild(story, canvasmaker=canvasmaker)
        raw = temporary.read_bytes()
        if not raw.startswith(b"%PDF-"):
            raise RuntimeError("ReportLab did not produce a PDF")
        inspection = inspect_pdf_report(
            temporary,
            expected_commit=bundle.source_commit,
            expected_tree_digest=bundle.source_tree_digest,
        )
        horizon_sink_verification = verify_pdf_horizon_sink_observations(
            temporary,
            content.horizon,
            observations=horizon_sink_observations,
        )
        horizon_verified_raw = temporary.read_bytes()
        if (
            inspection.sha256 != horizon_sink_verification.pdf_sha256
            or sha256_bytes(horizon_verified_raw) != horizon_sink_verification.pdf_sha256
            or len(horizon_verified_raw) != inspection.bytes
        ):
            raise RuntimeError("PDF changed between structural and rendered-sink verification")
        capability_sink_verification = verify_pdf_capability_sink_observations(
            temporary,
            content,
            observations=capability_sink_observations,
        )
        capability_verified_raw = temporary.read_bytes()
        if (
            inspection.sha256 != capability_sink_verification.pdf_sha256
            or sha256_bytes(capability_verified_raw) != capability_sink_verification.pdf_sha256
            or capability_verified_raw != horizon_verified_raw
        ):
            raise RuntimeError("PDF changed between structural and rendered-sink verification")
        core_sink_verification = verify_pdf_core_sink_observations(
            temporary,
            content,
            observations=core_sink_observations,
        )
        verified_raw = temporary.read_bytes()
        if (
            inspection.sha256 != horizon_sink_verification.pdf_sha256
            or inspection.sha256 != capability_sink_verification.pdf_sha256
            or inspection.sha256 != core_sink_verification.pdf_sha256
            or sha256_bytes(verified_raw) != horizon_sink_verification.pdf_sha256
            or sha256_bytes(verified_raw) != capability_sink_verification.pdf_sha256
            or sha256_bytes(verified_raw) != core_sink_verification.pdf_sha256
            or verified_raw != capability_verified_raw
            or len(verified_raw) != inspection.bytes
        ):
            raise RuntimeError("PDF changed between structural and rendered-sink verification")
        os.replace(temporary, output_path)
        published_raw = output_path.read_bytes()
        if published_raw != verified_raw:
            raise RuntimeError("PDF changed during atomic publication")
    finally:
        if temporary.exists():
            temporary.unlink()

    raw = published_raw
    return PdfReportResult(
        path=output_path,
        sha256=sha256_bytes(raw),
        bytes=len(raw),
        page_count=inspection.page_count,
        source_commit=bundle.source_commit,
        source_tree_digest=bundle.source_tree_digest,
        input_digest=digest,
        reportlab_version=str(REPORTLAB_VERSION),
        independent_verification_verdict="BLOCK",
        core_sink_observations=core_sink_observations,
        core_sink_verification=core_sink_verification,
        capability_sink_observations=capability_sink_observations,
        capability_sink_verification=capability_sink_verification,
        horizon_sink_observations=horizon_sink_observations,
        horizon_sink_verification=horizon_sink_verification,
    )


def generate_master_reference_pdf(
    compiler_root: Path,
    content_root: Path,
    output_path: Path,
    *,
    release_dir: Path | None = None,
    architecture_path: Path | None = None,
) -> PdfReportResult:
    """Strict path-oriented entry point used by release orchestration."""

    bundle = load_compiler_bundle(compiler_root)
    content = load_content_bundle(content_root)
    return build_master_reference_pdf(
        bundle,
        content,
        output_path,
        release_dir=release_dir,
        architecture_path=architecture_path,
    )


def inspect_pdf_report(
    pdf_path: Path,
    *,
    expected_commit: str,
    expected_tree_digest: str,
) -> PdfInspection:
    """Verify PDF structure, metadata, and exact-source binding with pypdf."""

    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - explicit environment error
        raise RuntimeError("pypdf is required to inspect the Master Reference PDF") from exc

    pdf_path = pdf_path.resolve(strict=True)
    raw = pdf_path.read_bytes()
    if not raw.startswith(b"%PDF-"):
        raise ValueError("file does not have a PDF header")
    reader = PdfReader(BytesIO(raw))
    if not reader.pages:
        raise ValueError("PDF has no pages")
    metadata = reader.metadata or {}
    title = _plain(metadata.get("/Title", ""))
    author = _plain(metadata.get("/Author", ""))
    subject = _plain(metadata.get("/Subject", ""))
    keywords = _plain(metadata.get("/Keywords", ""))
    commit_present = expected_commit in subject
    tree_present = expected_tree_digest in subject
    if title != "Atlas Master Reference - Whole-Repository Accounting":
        raise ValueError("PDF title metadata is absent or unexpected")
    if author != "Atlas repository":
        raise ValueError("PDF author metadata is absent or unexpected")
    if not commit_present or not tree_present:
        raise ValueError("PDF metadata is not bound to the expected source")
    return PdfInspection(
        path=pdf_path,
        sha256=sha256_bytes(raw),
        bytes=len(raw),
        page_count=len(reader.pages),
        title=title,
        author=author,
        subject=subject,
        keywords=keywords,
        source_commit_present=commit_present,
        source_tree_digest_present=tree_present,
    )


def render_pdf_for_visual_qa(
    pdf_path: Path,
    output_dir: Path,
    *,
    dpi: int = 144,
) -> tuple[Path, ...]:
    """Render every page to PNG using Poppler without modifying the PDF.

    ``output_dir`` must be absent or empty so visual evidence from another build
    cannot be mistaken for the current document.  The caller must inspect the
    returned PNGs; successful rendering alone is not visual approval.
    """

    if not 72 <= dpi <= 300:
        raise ValueError("visual QA DPI must be between 72 and 300")
    pdf_path = pdf_path.resolve(strict=True)
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"visual QA directory must be empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    executable = shutil.which("pdftoppm")
    if executable is None:
        raise RuntimeError("pdftoppm is required for visual PDF QA")
    # The Codex Windows runtime exposes a .cmd shim.  Some distributions of
    # that shim cannot resolve their nested executable when launched by
    # subprocess, so prefer the bounded native target when it is present.
    executable_path = Path(executable).resolve()
    if executable_path.suffix.lower() in {".cmd", ".bat"}:
        for parent in executable_path.parents[:5]:
            native = parent / "native" / "poppler" / "Library" / "bin" / "pdftoppm.exe"
            if native.is_file():
                executable_path = native
                break
    prefix = output_dir / "atlas-master-reference"
    args = [str(executable_path), "-r", str(dpi), "-png", str(pdf_path), str(prefix)]
    if executable_path.suffix.lower() in {".cmd", ".bat"}:
        command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", subprocess.list2cmdline(args)]
    else:
        command = args
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        detail = _plain(completed.stderr or completed.stdout or "unknown Poppler error")
        raise RuntimeError(f"pdftoppm failed: {detail}")
    rendered = tuple(sorted(output_dir.glob("atlas-master-reference-*.png")))
    if not rendered:
        raise RuntimeError("pdftoppm produced no page images")
    return rendered
