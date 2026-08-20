"""Single-manifest deterministic release family builder."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from atlas_privacy import forbidden_byte_findings
from governance.capability_sink_lineage import (
    evaluate_capability_sink_lineage,
    load_capability_sink_lineage_contract,
    unavailable_capability_sink_lineage,
)
from governance.core_sink_lineage import (
    evaluate_core_sink_lineage,
    load_core_sink_lineage_contract,
    unavailable_core_sink_lineage,
)
from governance.rendered_sink_lineage import (
    evaluate_rendered_sink_lineage,
    load_rendered_sink_lineage_contract,
    unavailable_rendered_sink_lineage,
)

from .compiler_bundle import CompilerBundle, load_compiler_bundle
from .content_bundle import load_content_bundle
from .documents import (
    agent_pack,
    capability_gap_report,
    decisions_opportunities,
    engineering_dossier,
    enhancement_brief,
    machine_reference,
    owner_handbook,
    self_contained_html,
    source_symbol_index,
    source_symbol_markdown,
)
from .model import (
    ReleaseInputError,
    canonical_json,
    collect_output_bytes,
    deterministic_zip,
    prepare_output,
    read_bytes,
    receipt,
    sha256_bytes,
    stable_id,
    write_bytes,
)
from .provenance import provenance_statement
from .sbom import NPM_LOCKFILES, PYTHON_DECLARATIONS, build_cyclonedx
from .schema_validation import validate_release_object
from .source_binding import read_bound_source_blob, validate_exact_source


class ReleaseError(RuntimeError):
    """The release family was refused rather than emitted incompletely."""


MEDIA_TYPES = {
    ".json": "application/json",
    ".md": "text/markdown; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".zip": "application/zip",
    ".pdf": "application/pdf",
}

TEXT_SCAN_SUFFIXES = frozenset({".json", ".md", ".html", ".txt"})

_BOUNDED_IMAGE_LOCKFILE = "master-reference/package-lock.json"
_BOUNDED_IMAGE_MANIFEST = "master-reference/package.json"
_BOUNDED_IMAGE_TARGET = "vendor/bounded-image-size"
_BOUNDED_IMAGE_SOURCE_PREFIX = "master-reference/vendor/bounded-image-size/"
# Updated only after reviewing every tracked file under the source prefix.
_BOUNDED_IMAGE_PACKAGE_SOURCE_DIGEST = "65078d74a80fed5bc34cace43cbe0fc1103c11abc86cf90a08dcbf9e8d980f7f"
_BOUNDED_IMAGE_PACKAGE_SOURCE_FILES = "4"
_BOUNDED_IMAGE_PACKAGE_SOURCE_BYTES = "6787"

PLANNED_ALWAYS_MEMBERS = frozenset(
    {
        "atlas-reference.json",
        "owner-handbook.md",
        "engineering-dossier.md",
        "source-symbol-index.json",
        "source-symbol-index.md",
        "capability-gap-report.md",
        "decisions-opportunities.md",
        "enhancement-brief-template.md",
        "agent-pack.md",
        "bom.cdx.json",
        "master-reference.html",
        "pdf-gate.json",
        "provenance.json",
        "preservation-coverage.json",
        "atlas-master-reference-offline.zip",
        "atlas-master-reference-preservation.zip",
        "family-attestation.json",
        "artifact-inventory.json",
        "release-manifest.json",
    }
)

_IMAGE_SIZE_HIGH_ADVISORIES = (
    "GHSA-5p2g-fcmc-qvqq",
    "GHSA-w3rx-r6r6-pgpr",
)
_NANOID_HIGH_ADVISORY = "GHSA-2v37-7h3g-55p8"
_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)

RENDERED_SINK_LINEAGE_CONTRACT_PATH = "master-reference/governance/rendered-sink-lineage-contract.json"
OPEN_HORIZON_SOURCE_PATH = "master-reference/content/open-horizon-register.json"
CAPABILITY_SINK_LINEAGE_CONTRACT_PATH = (
    "master-reference/governance/rendered-sink-lineage-capability-contract.json"
)
CAPABILITY_SOURCE_PATH = "master-reference/content/capability-catalog.json"
CORE_SINK_LINEAGE_CONTRACT_PATH = "master-reference/governance/rendered-sink-lineage-core-contract.json"
CORE_SOURCE_PATH = "master-reference/content/atlas-core.json"

_GENERATED_PDF_OBSERVATION_BINDINGS = (
    ("horizon_sink_observations", "horizon_sink_verification"),
    ("capability_sink_observations", "capability_sink_verification"),
    ("core_sink_observations", "core_sink_verification"),
)


def _validate_generated_pdf_observation_bindings(result: Any) -> None:
    """Bind each mechanical digest to the exact observation envelope it attests."""

    try:
        for observations_name, verification_name in _GENERATED_PDF_OBSERVATION_BINDINGS:
            observations = getattr(result, observations_name)
            verification = getattr(result, verification_name)
            digest = verification.observation_digest
            if type(digest) is not str or digest != sha256_bytes(canonical_json(observations)):
                raise ReleaseError("generated PDF sink observation digest differs from producer observations")
    except ReleaseError:
        raise
    except Exception:
        raise ReleaseError("generated PDF sink observation binding could not be evaluated") from None


def _semver_compare_to_stable(value: object, stable: tuple[int, int, int]) -> int | None:
    """Compare a SemVer value with a stable boundary; invalid input fails closed upstream."""

    match = _SEMVER_RE.fullmatch(str(value))
    if match is None:
        return None
    version = tuple(int(match.group(index)) for index in range(1, 4))
    if version < stable:
        return -1
    if version > stable:
        return 1
    return -1 if match.group(4) is not None else 0


def _is_affected_nanoid(value: object) -> bool:
    before_3_3_17 = _semver_compare_to_stable(value, (3, 3, 17))
    from_4_0_0 = _semver_compare_to_stable(value, (4, 0, 0))
    before_5_1_6 = _semver_compare_to_stable(value, (5, 1, 6))
    if None in (before_3_3_17, from_4_0_0, before_5_1_6):
        return True
    return before_3_3_17 < 0 or (from_4_0_0 >= 0 and before_5_1_6 < 0)


def _sbom_component_properties(component: dict[str, Any]) -> dict[str, str]:
    properties: dict[str, str] = {}
    for item in component.get("properties", []):
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        if isinstance(name, str) and isinstance(value, str) and name not in properties:
            properties[name] = value
    return properties


def _verified_bounded_image_replacement_aliases(sbom: dict[str, Any]) -> set[str]:
    components = {
        component.get("bom-ref"): component
        for component in sbom.get("components", [])
        if isinstance(component, dict) and isinstance(component.get("bom-ref"), str)
    }
    dependencies = {
        row.get("ref"): row.get("dependsOn")
        for row in sbom.get("dependencies", [])
        if isinstance(row, dict) and isinstance(row.get("ref"), str) and isinstance(row.get("dependsOn"), list)
    }
    inbound: dict[str, set[str]] = {}
    for source_ref, target_refs in dependencies.items():
        if not isinstance(target_refs, list):
            continue
        for target_ref in target_refs:
            if isinstance(target_ref, str):
                inbound.setdefault(target_ref, set()).add(source_ref)
    verified: set[str] = set()
    for alias_ref, component in components.items():
        properties = _sbom_component_properties(component)
        if not (
            component.get("name") == "image-size"
            and "version" not in component
            and properties.get("atlas:lockfile") == "master-reference/package-lock.json"
            and properties.get("atlas:lockfilePath") == "node_modules/image-size"
            and properties.get("atlas:recordKind") == "local-link-record"
            and properties.get("atlas:resolution") == "lockfile-local-link"
        ):
            continue
        target_refs = dependencies.get(alias_ref)
        if not isinstance(target_refs, list) or len(target_refs) != 1 or not isinstance(target_refs[0], str):
            continue
        target = components.get(target_refs[0])
        if target is None:
            continue
        vinext_refs = {
            ref
            for ref, candidate in components.items()
            if candidate.get("name") == "vinext"
            and candidate.get("version") == "0.0.50"
            and candidate.get("externalReferences")
            == [{"type": "distribution", "url": "https://registry.npmjs.org/vinext/-/vinext-0.0.50.tgz"}]
            and _sbom_component_properties(candidate).get("atlas:lockfile")
            == "master-reference/package-lock.json"
            and _sbom_component_properties(candidate).get("atlas:lockfilePath") == "node_modules/vinext"
            and _sbom_component_properties(candidate).get("atlas:recordKind")
            == "resolved-third-party-component"
            and _sbom_component_properties(candidate).get("atlas:npmIntegrity")
            == "sha512-uo72YNnq94NtogETWnhMdFSrkMLwWgeXh5PS6qh8ksajuvAaZX50bXYJ4a6dERQ/AnnXAlNByAGHCjjNxQrvig=="
        }
        if len(vinext_refs) != 1 or inbound.get(alias_ref, set()) != vinext_refs:
            continue
        if inbound.get(target_refs[0], set()) != {alias_ref}:
            continue
        target_properties = _sbom_component_properties(target)
        if not (
            target.get("group") == "@atlas"
            and target.get("name") == "bounded-image-size"
            and target.get("version") == "1.0.0"
            and target_properties.get("atlas:lockfile") == "master-reference/package-lock.json"
            and target_properties.get("atlas:lockfilePath") == "vendor/bounded-image-size"
            and target_properties.get("atlas:recordKind") == "local-package-record"
            and target_properties.get("atlas:resolution") == "lockfile-local-package"
            and target_properties.get("atlas:localPackageSourceDigest")
            == _BOUNDED_IMAGE_PACKAGE_SOURCE_DIGEST
            and target_properties.get("atlas:localPackageSourceFiles")
            == _BOUNDED_IMAGE_PACKAGE_SOURCE_FILES
            and target_properties.get("atlas:localPackageSourceBytes")
            == _BOUNDED_IMAGE_PACKAGE_SOURCE_BYTES
            and target.get("licenses") == [{"expression": "LicenseRef-Proprietary"}]
        ):
            continue
        verified.add(alias_ref)
    return verified if len(verified) == 1 else set()


def _dependency_vulnerability_assessment(sbom: dict[str, Any]) -> tuple[str, list[str]]:
    """Describe the tracked dependency state without pretending an SBOM is a VEX."""

    components = sbom.get("components", [])
    bounded_image_aliases = _verified_bounded_image_replacement_aliases(sbom)
    next_vendored_image_parser = any(
        isinstance(component, dict)
        and component.get("name") == "next"
        and component.get("version") == "16.2.12"
        and component.get("externalReferences")
        == [{"type": "distribution", "url": "https://registry.npmjs.org/next/-/next-16.2.12.tgz"}]
        and _sbom_component_properties(component).get("atlas:lockfile")
        == "master-reference/package-lock.json"
        and _sbom_component_properties(component).get("atlas:lockfilePath") == "node_modules/next"
        and _sbom_component_properties(component).get("atlas:recordKind")
        == "resolved-third-party-component"
        and _sbom_component_properties(component).get("atlas:npmIntegrity")
        == "sha512-iD59eYQWmbFcEbX7v/acG5DRym9iw1DdaPoD0WTA920naWsE25wShzJW4+UvAs8MK9EC2kBfIH6vtto1H1PHGw=="
        for component in components
    )
    affected_image_size_versions = sorted(
        {
            (
                str(component.get("version"))
                if component.get("version") is not None
                else "<unversioned-local-link>"
            )
            for component in components
            if isinstance(component, dict)
            and component.get("name") == "image-size"
            and component.get("bom-ref") not in bounded_image_aliases
            and (
                (comparison := _semver_compare_to_stable(component.get("version"), (2, 0, 2))) is None
                or comparison <= 0
            )
        }
    )
    affected_nanoid_versions = sorted(
        {
            str(component.get("version"))
            for component in components
            if isinstance(component, dict)
            and component.get("name") == "nanoid"
            and _is_affected_nanoid(component.get("version"))
        }
    )
    limits: list[str] = []
    if affected_image_size_versions:
        advisories = ", ".join(_IMAGE_SIZE_HIGH_ADVISORIES)
        limits.append(
            "The whole-repository SBOM contains image-size version(s) "
            f"{', '.join(affected_image_size_versions)} within the affected <=2.0.2 range for "
            f"high-severity advisories {advisories}; no patched npm version was available at "
            "this source state. "
            "The package is currently pulled through the Vinext build tool rather than the "
            "deployed runtime, but that reachability boundary is not a vulnerability waiver. "
            "Public release remains blocked pending a patched upstream or independently "
            "verified replacement and a fresh applicability review."
        )
    if affected_nanoid_versions:
        limits.append(
            "The whole-repository SBOM contains vulnerable Nano ID version(s) "
            f"{', '.join(affected_nanoid_versions)} affected by {_NANOID_HIGH_ADVISORY}. "
            "Build-time-only reachability does not waive the finding; update every owning lockfile "
            "to a patched version before treating the dependency assessment as current."
        )
    if bounded_image_aliases:
        limits.append(
            "The Vinext image-size dependency edge resolves to the tracked local "
            "@atlas/bounded-image-size 1.0.0 package. That package bounds its accepted buffer and "
            "dimensions, validates PNG IHDR metadata, recognizes only a bounded SVG prefix, and "
            "rejects every other image family. It removes the advisory-named HEIF, JXL and ICNS "
            "parsers from that Vinext edge; JP2 and JPEG are independently unsupported. The tracked "
            "source/lock binding and tests exercise the local replacement behavior, but they are not "
            "an externally source-authenticated current advisory or applicability/VEX review."
        )
    if next_vendored_image_parser:
        limits.append(
            "Next 16.2.12 contains a separate compiled image-size implementation outside npm override "
            "resolution, including the zero-progress ICNS parser covered by GHSA-w3rx-r6r6-pgpr. "
            "Current source contracts reject next/image imports, but reachability is not a vulnerability "
            "waiver; replace or independently assess "
            "the vendored parser before release."
        )
    if affected_image_size_versions and affected_nanoid_versions:
        return "blocked_multiple_unremediated_high_dependency_advisories", limits
    if affected_image_size_versions:
        return "blocked_image_size_unpatched_build_time_high_advisories", limits
    if affected_nanoid_versions:
        return "blocked_nanoid_unremediated_high_advisory", limits
    limits.append(
        "SBOM inventory does not assert vulnerability absence; a current source-authenticated "
        "advisory and applicability/VEX review is not embedded in this release."
    )
    if next_vendored_image_parser:
        return "blocked_next_vendored_image_parser_and_external_review_required", limits
    return "blocked_external_current_advisory_applicability_review_required", limits


def _artifact(root: Path, relative: str, value: bytes, role: str) -> dict[str, Any]:
    suffix = PurePosixPath(relative).suffix
    if suffix in TEXT_SCAN_SUFFIXES:
        findings = forbidden_byte_findings(relative, value)
        if findings:
            labels = ", ".join(f"{item['path']}:{item['line']}:{item['rule']}" for item in findings)
            raise ReleaseInputError(f"generated-output privacy scan failed: {labels}")
        privacy_scan = "high_confidence_utf8_text_scan_passed"
    else:
        privacy_scan = "binary_container_not_content_scanned"
    item = write_bytes(root, relative, value)
    item.update(
        {
            "role": role,
            "media_type": MEDIA_TYPES.get(suffix, "application/octet-stream"),
            "privacy_scan": privacy_scan,
        }
    )
    return item


def _bound_architecture(repo_root: Path, bundle: CompilerBundle) -> bytes:
    relative = "master-reference/governance/architecture.json"
    value = read_bound_source_blob(repo_root, bundle, relative)
    _bind_tracked_inputs(
        bundle,
        [{"path": relative, "sha256": sha256_bytes(value), "bytes": len(value)}],
    )
    return value


def _contract_members(content: Any, *, pdf_included: bool) -> set[str]:
    expected: set[str] = set()
    for item in content.output_contract["members"]:
        emission = item["emission"]
        if emission == "always" or (emission == "when_pdf" and pdf_included):
            expected.add(str(item["manifest_member"]))
    return expected


def _validate_output_contract(content: Any, *, pdf_included: bool) -> set[str]:
    expected = _contract_members(content, pdf_included=pdf_included)
    planned = set(PLANNED_ALWAYS_MEMBERS)
    if pdf_included:
        planned.add("master-reference.pdf")
    if expected != planned:
        raise ReleaseInputError(
            "output contract differs from release producers "
            f"(contract_only={sorted(expected - planned)}, producer_only={sorted(planned - expected)})"
        )
    return expected


def _dependency_sources(repo_root: Path, bundle: CompilerBundle) -> dict[str, bytes]:
    sources = {
        relative: read_bound_source_blob(repo_root, bundle, relative)
        for relative in sorted(set(NPM_LOCKFILES + PYTHON_DECLARATIONS))
    }
    try:
        lock = json.loads(sources[_BOUNDED_IMAGE_LOCKFILE].decode("utf-8", errors="strict"))
        packages = lock.get("packages") if isinstance(lock, dict) else None
        alias = packages.get("node_modules/image-size") if isinstance(packages, dict) else None
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseInputError("could not inspect the bounded image replacement lock binding") from exc
    if isinstance(alias, dict) and alias.get("link") is True and alias.get("resolved") == _BOUNDED_IMAGE_TARGET:
        manifest_raw = read_bound_source_blob(repo_root, bundle, _BOUNDED_IMAGE_MANIFEST)
        try:
            manifest = json.loads(manifest_raw.decode("utf-8", errors="strict"))
            overrides = manifest.get("overrides") if isinstance(manifest, dict) else None
            vinext_override = overrides.get("vinext@0.0.50") if isinstance(overrides, dict) else None
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReleaseInputError("could not inspect the bounded image replacement manifest binding") from exc
        if not (
            isinstance(overrides, dict)
            and isinstance(vinext_override, dict)
            and vinext_override == {"image-size": "file:vendor/bounded-image-size"}
            and "image-size" not in overrides
        ):
            raise ReleaseInputError("bounded image replacement override is not scoped to exact Vinext 0.0.50")
        sources[_BOUNDED_IMAGE_MANIFEST] = manifest_raw
        source_paths = sorted(
            str(item.get("path"))
            for item in bundle.records["files"]
            if isinstance(item, dict)
            and isinstance(item.get("path"), str)
            and str(item["path"]).startswith(_BOUNDED_IMAGE_SOURCE_PREFIX)
        )
        if not source_paths:
            raise ReleaseInputError("bounded image replacement has no source-bound package files")
        for relative in source_paths:
            sources[relative] = read_bound_source_blob(repo_root, bundle, relative)
    return sources


def _dependency_receipts(source_files: dict[str, bytes]) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for relative, value in sorted(source_files.items()):
        rows.append({"path": relative, "sha256": sha256_bytes(value), "bytes": len(value)})
    return tuple(rows)


def _bind_tracked_inputs(bundle: CompilerBundle, receipts: Iterable[dict[str, Any]]) -> None:
    files = {str(item.get("path")): item for item in bundle.records["files"]}
    failures: list[str] = []
    for item in receipts:
        path = str(item["path"])
        record = files.get(path)
        if record is None:
            failures.append(f"release input is absent from the compiled Git tree: {path}")
        elif record.get("privacy_exposure") != "full":
            failures.append(f"release input is not approved for full exposure: {path}")
        elif record.get("content_digest") != item["sha256"]:
            failures.append(f"release input differs from exact compiler source: {path}")
        elif record.get("classification_errors"):
            failures.append(f"release input has compiler classification errors: {path}")
    if failures:
        raise ReleaseInputError("; ".join(sorted(failures)))


def _pdf_input(path: Path | None) -> tuple[str, bytes | None, dict[str, Any]]:
    if path is None:
        status = "pending_external_renderer"
        gate = {
            "schema_version": "1.0.0",
            "status": status,
            "included": False,
            "required_for_verified_release": True,
            "binary_privacy_coverage": "not_applicable_no_pdf",
            "claim": "No PDF was generated or supplied by this deterministic release builder.",
            "next_gate": "Render the complete Master Reference with an approved external renderer, visually verify it, then rebuild with --pdf.",
        }
        return status, None, gate
    absolute = path.resolve(strict=True)
    if absolute.is_symlink() or not absolute.is_file():
        raise ReleaseInputError("PDF input must be a regular non-symlink file")
    before = absolute.stat(follow_symlinks=False)
    value = absolute.read_bytes()
    after = absolute.stat(follow_symlinks=False)
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise ReleaseInputError("PDF input changed while read")
    if len(value) < 8 or not value.startswith(b"%PDF-"):
        raise ReleaseInputError("PDF input does not have a PDF header")
    status = "externally_supplied_visual_review_pending"
    gate = {
        "schema_version": "1.0.0",
        "status": status,
        "included": True,
        "required_for_verified_release": True,
        "binary_privacy_coverage": "blocked_external_binary_content_not_inspected",
        "sha256": sha256_bytes(value),
        "bytes": len(value),
        "claim": "External renderer output was supplied and hash-bound; this builder did not inspect its compressed object streams for private content and did not visually approve it.",
        "next_gate": "Perform an approved PDF-aware privacy inspection, then record independent page rendering, overflow, accessibility, and content reconciliation evidence.",
    }
    return status, value, gate


def _rendered_sink_lineage_inputs(
    repo_root: Path,
    bundle: CompilerBundle,
    content: Any,
) -> tuple[dict[str, Any], bytes, str, bool]:
    """Load the exact contract and Horizon blob for sink reconciliation."""

    contract_raw = read_bound_source_blob(repo_root, bundle, RENDERED_SINK_LINEAGE_CONTRACT_PATH)
    contract = load_rendered_sink_lineage_contract(contract_raw)
    validate_release_object(repo_root, "rendered-sink-lineage-contract", contract)
    horizon_raw = content.raw_files.get("open-horizon-register.json")
    if type(horizon_raw) is not bytes:
        raise ReleaseInputError("rendered-sink lineage retained no exact Horizon source blob")
    facet_records = bundle.records.get("consequential_claim_facets")
    if not isinstance(facet_records, list):
        raise ReleaseInputError("rendered-sink lineage retained no compiler facet subjects")
    source_oids = {
        str(row.get("source_blob_oid")) for row in facet_records if row.get("source_path") == OPEN_HORIZON_SOURCE_PATH
    }
    summary = bundle.completeness.get("consequential_claim_denominator")
    scope = contract.get("source_scope")
    if not isinstance(scope, dict):
        raise ReleaseInputError("rendered-sink lineage contract has no source scope")
    if summary.get("state") == "not_declared":
        if source_oids:
            raise ReleaseInputError("rendered-sink lineage has subjects while its denominator is not declared")
        return contract, horizon_raw, str(scope.get("git_blob_oid") or ""), False
    if len(source_oids) != 1:
        raise ReleaseInputError("rendered-sink lineage Horizon facet source binding is not unique")
    source_oid = next(iter(source_oids))
    receipts = summary.get("source_receipts") if isinstance(summary, dict) else None
    receipt = (
        next((row for row in receipts if row.get("path") == OPEN_HORIZON_SOURCE_PATH), None)
        if isinstance(receipts, list)
        else None
    )
    if (
        not isinstance(receipt, dict)
        or source_oid != scope.get("git_blob_oid")
        or receipt.get("git_blob_oid") != source_oid
        or receipt.get("candidate_count") != scope.get("expected_candidates")
        or receipt.get("candidate_digest") != scope.get("candidate_digest")
        or summary.get("expected_candidates") != 2138
        or summary.get("independently_reviewed_candidates") != 0
        or summary.get("unresolved_candidates") != 2138
        or summary.get("contract_digest") != contract["global_denominator"]["claim_contract_digest"]
        or summary.get("classification_digest") != contract["global_denominator"]["classification_digest"]
        or summary.get("source_receipts_digest") != contract["global_denominator"]["source_receipts_digest"]
        or summary.get("candidate_set_digest") != contract["global_denominator"]["candidate_set_digest"]
        or summary.get("closed") is not False
    ):
        raise ReleaseInputError("rendered-sink lineage differs from the compiler claim denominator")
    return contract, horizon_raw, source_oid, True


def _capability_sink_lineage_inputs(
    repo_root: Path,
    bundle: CompilerBundle,
    content: Any,
) -> tuple[dict[str, Any], bytes, str, bool]:
    """Load the exact contract and capability blob for sink reconciliation."""

    contract_raw = read_bound_source_blob(repo_root, bundle, CAPABILITY_SINK_LINEAGE_CONTRACT_PATH)
    contract = load_capability_sink_lineage_contract(contract_raw)
    validate_release_object(repo_root, "rendered-sink-lineage-capability-contract", contract)
    capability_raw = content.raw_files.get("capability-catalog.json")
    if type(capability_raw) is not bytes:
        raise ReleaseInputError("capability sink lineage retained no exact source blob")
    facet_records = bundle.records.get("consequential_claim_facets")
    if not isinstance(facet_records, list):
        raise ReleaseInputError("capability sink lineage retained no compiler facet subjects")
    source_oids = {
        str(row.get("source_blob_oid")) for row in facet_records if row.get("source_path") == CAPABILITY_SOURCE_PATH
    }
    summary = bundle.completeness.get("consequential_claim_denominator")
    scope = contract.get("source_scope")
    if not isinstance(scope, dict):
        raise ReleaseInputError("capability sink lineage contract has no source scope")
    if not isinstance(summary, dict):
        raise ReleaseInputError("capability sink lineage has no claim denominator")
    if summary.get("state") == "not_declared":
        if source_oids:
            raise ReleaseInputError("capability sink lineage has subjects while its denominator is not declared")
        return contract, capability_raw, str(scope.get("git_blob_oid") or ""), False
    if len(source_oids) != 1:
        raise ReleaseInputError("capability sink lineage facet source binding is not unique")
    source_oid = next(iter(source_oids))
    receipts = summary.get("source_receipts")
    receipt = (
        next((row for row in receipts if row.get("path") == CAPABILITY_SOURCE_PATH), None)
        if isinstance(receipts, list)
        else None
    )
    if (
        not isinstance(receipt, dict)
        or source_oid != scope.get("git_blob_oid")
        or receipt.get("git_blob_oid") != source_oid
        or receipt.get("candidate_count") != scope.get("expected_candidates")
        or receipt.get("candidate_digest") != scope.get("candidate_digest")
        or summary.get("expected_candidates") != 2138
        or summary.get("independently_reviewed_candidates") != 0
        or summary.get("unresolved_candidates") != 2138
        or summary.get("contract_digest") != contract["global_denominator"]["claim_contract_digest"]
        or summary.get("classification_digest") != contract["global_denominator"]["classification_digest"]
        or summary.get("source_receipts_digest") != contract["global_denominator"]["source_receipts_digest"]
        or summary.get("candidate_set_digest") != contract["global_denominator"]["candidate_set_digest"]
        or summary.get("closed") is not False
    ):
        raise ReleaseInputError("capability sink lineage differs from the compiler claim denominator")
    return contract, capability_raw, source_oid, True


def _core_sink_lineage_inputs(
    repo_root: Path,
    bundle: CompilerBundle,
    content: Any,
) -> tuple[dict[str, Any], bytes, str, bool]:
    """Load the exact contract and Atlas Core blob for sink reconciliation."""

    contract_raw = read_bound_source_blob(repo_root, bundle, CORE_SINK_LINEAGE_CONTRACT_PATH)
    contract = load_core_sink_lineage_contract(contract_raw)
    validate_release_object(repo_root, "rendered-sink-lineage-core-contract", contract)
    core_raw = content.raw_files.get("atlas-core.json")
    if type(core_raw) is not bytes:
        raise ReleaseInputError("Core sink lineage retained no exact source blob")
    facet_records = bundle.records.get("consequential_claim_facets")
    if not isinstance(facet_records, list):
        raise ReleaseInputError("Core sink lineage retained no compiler facet subjects")
    source_oids = {
        str(row.get("source_blob_oid")) for row in facet_records if row.get("source_path") == CORE_SOURCE_PATH
    }
    summary = bundle.completeness.get("consequential_claim_denominator")
    scope = contract.get("source_scope")
    if not isinstance(scope, dict):
        raise ReleaseInputError("Core sink lineage contract has no source scope")
    if not isinstance(summary, dict):
        raise ReleaseInputError("Core sink lineage has no claim denominator")
    if summary.get("state") == "not_declared":
        if source_oids:
            raise ReleaseInputError("Core sink lineage has subjects while its denominator is not declared")
        return contract, core_raw, str(scope.get("git_blob_oid") or ""), False
    if len(source_oids) != 1:
        raise ReleaseInputError("Core sink lineage facet source binding is not unique")
    source_oid = next(iter(source_oids))
    receipts = summary.get("source_receipts")
    receipt = (
        next((row for row in receipts if row.get("path") == CORE_SOURCE_PATH), None)
        if isinstance(receipts, list)
        else None
    )
    if (
        not isinstance(receipt, dict)
        or source_oid != scope.get("git_blob_oid")
        or receipt.get("git_blob_oid") != source_oid
        or receipt.get("candidate_count") != scope.get("expected_candidates")
        or receipt.get("candidate_digest") != scope.get("candidate_digest")
        or summary.get("expected_candidates") != 2138
        or summary.get("independently_reviewed_candidates") != 0
        or summary.get("unresolved_candidates") != 2138
        or summary.get("contract_digest") != contract["global_denominator"]["claim_contract_digest"]
        or summary.get("classification_digest") != contract["global_denominator"]["classification_digest"]
        or summary.get("source_receipts_digest") != contract["global_denominator"]["source_receipts_digest"]
        or summary.get("candidate_set_digest") != contract["global_denominator"]["candidate_set_digest"]
        or summary.get("closed") is not False
    ):
        raise ReleaseInputError("Core sink lineage differs from the compiler claim denominator")
    return contract, core_raw, source_oid, True


def _compiler_preservation_entries(bundle: CompilerBundle) -> dict[str, bytes]:
    entries: dict[str, bytes] = {"compiler/manifest.json": canonical_json(bundle.manifest)}
    expected: dict[str, dict[str, Any]] = {
        bundle.manifest["completeness"]["path"]: bundle.manifest["completeness"],
        bundle.manifest["graphify_metadata"]["path"]: bundle.manifest["graphify_metadata"],
        bundle.manifest["architecture_conformance"]["path"]: bundle.manifest["architecture_conformance"],
    }
    for group in bundle.manifest["groups"].values():
        for chunk in group["chunks"]:
            expected[chunk["path"]] = chunk
    if set(expected) | {"manifest.json"} != set(bundle.input_files):
        raise ReleaseInputError("compiler preservation allowlist differs from validated inputs")
    for relative, item in sorted(expected.items()):
        try:
            value = read_bytes(bundle.root, relative)
        except (OSError, ReleaseInputError):
            raise ReleaseInputError("compiler input could not be reread before preservation") from None
        if len(value) != item["bytes"] or sha256_bytes(value) != item["sha256"]:
            raise ReleaseInputError(f"compiler input changed before preservation: {relative}")
        entries[f"compiler/{relative}"] = value
    return entries


def _bundle_receipt(entries: dict[str, bytes], source_commit: str, kind: str) -> bytes:
    return canonical_json(
        {
            "schema_version": "1.0.0",
            "kind": kind,
            "source_commit": source_commit,
            "entries": [{"path": name, **receipt(value)} for name, value in sorted(entries.items())],
            "receipt_exclusion": "This receipt cannot include its own digest.",
        }
    )


def _preservation_coverage(bundle: CompilerBundle) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "id": stable_id("preservation-coverage", bundle.source_commit, bundle.source_tree_digest),
        "source_commit": bundle.source_commit,
        "status": "blocked_missing_external_recovery_materials",
        "present_in_preservation_pack": [
            "validated compiler manifest, ledgers, and complete safe projection chunks",
            "curated Atlas content contracts",
            "repository dependency declarations and npm lockfiles",
            "core generated reference artifacts and core-artifact provenance",
            "deterministic bundle receipt and recovery instructions",
        ],
        "intentionally_outside_pack": [
            "the preservation ZIP itself",
            "the sibling offline ZIP",
            "family-attestation.json",
            "artifact-inventory.json",
            "release-manifest.json",
            "release-manifest.sig.json when separately owner-signed",
        ],
        "missing_required_for_recovery_claim": [
            "Python wheelhouse",
            "npm package cache",
            "toolchain installers and verified checksums",
            "bare-machine recovery receipt",
            "schema-upcaster recovery exercise receipt",
            "annual checksum and key-loss exercise receipts",
        ],
        "external_human_custody": [
            "owner Ed25519 private key and encrypted recovery copies",
            "separately trusted owner public key",
            "human-controlled 3-2-1 copies",
        ],
        "gate": "BLOCK",
        "claim_boundary": (
            "This ledger inventories preservation coverage. The emitted ZIP is a deterministic partial "
            "preservation pack, not proof of bare-machine or key-loss recovery."
        ),
    }


def _family_attestation(
    bundle: CompilerBundle,
    content: Any,
    receipts: Iterable[dict[str, Any]],
    expected_members: set[str],
) -> dict[str, Any]:
    rows = sorted(
        (
            {
                "path": item["path"],
                "sha256": item["sha256"],
                "bytes": item["bytes"],
            }
            for item in receipts
        ),
        key=lambda item: item["path"],
    )
    return {
        "schema_version": "1.0.0",
        "id": stable_id("family-attestation", bundle.source_commit, bundle.source_tree_digest),
        "kind": "complete-family-membership-and-pre-manifest-receipt",
        "source_commit": bundle.source_commit,
        "source_tree_digest": bundle.source_tree_digest,
        "output_contract": {
            "id": content.output_contract.get("id"),
            "catalog_version": content.output_contract["catalog_version"],
            "expected_members": sorted(expected_members),
        },
        "covered_receipts": rows,
        "self_exclusions": [
            "family-attestation.json",
            "artifact-inventory.json",
            "release-manifest.json",
            "release-manifest.sig.json",
        ],
        "closure": (
            "release-manifest.json hash-binds this attestation and artifact-inventory.json; the offline "
            "verifier enforces the exact sibling set. A detached owner signature remains absent unless supplied externally."
        ),
    }


def build_release(
    repo_root: Path,
    compiler_output: Path,
    output: Path,
    *,
    pdf_path: Path | None = None,
    generate_pdf: bool = False,
    enhancement_gap: str | None = None,
) -> dict[str, Any]:
    """Validate all required inputs and emit one deterministic release family.

    The destination must be absent or empty.  Inputs are fully validated before
    the destination is created, so an integrity failure does not leave a
    plausible partial release.
    """

    staged = None
    try:
        repo_root = repo_root.resolve(strict=True)
        bundle = load_compiler_bundle(compiler_output, repository_root=repo_root)
        source_before = validate_exact_source(repo_root, bundle)
        content = load_content_bundle(
            repo_root / "master-reference" / "content",
            source_reader=lambda name: read_bound_source_blob(
                repo_root,
                bundle,
                f"master-reference/content/{name}",
            ),
        )
        validate_release_object(repo_root, "output-contract", content.output_contract)
        lineage_contract, horizon_raw, horizon_source_oid, lineage_declared = _rendered_sink_lineage_inputs(
            repo_root,
            bundle,
            content,
        )
        (
            capability_lineage_contract,
            capability_raw,
            capability_source_oid,
            capability_lineage_declared,
        ) = _capability_sink_lineage_inputs(repo_root, bundle, content)
        core_lineage_contract, core_raw, core_source_oid, core_lineage_declared = _core_sink_lineage_inputs(
            repo_root,
            bundle,
            content,
        )
        dependency_sources = _dependency_sources(repo_root, bundle)
        dependency_receipts = _dependency_receipts(dependency_sources)
        architecture_bytes = _bound_architecture(repo_root, bundle)
        _bind_tracked_inputs(bundle, [*content.receipts, *dependency_receipts])
        sbom = build_cyclonedx(dependency_sources, bundle.source_commit, bundle.source_tree_digest)
        if _dependency_receipts(_dependency_sources(repo_root, bundle)) != dependency_receipts:
            raise ReleaseInputError("dependency inputs changed during SBOM generation")
        if pdf_path is not None and generate_pdf:
            raise ReleaseInputError("choose either an external PDF or deterministic PDF generation, not both")
        generated_pdf_provenance: dict[str, Any] | None = None
        if generate_pdf:
            from . import pdf_report

            architecture, _ = pdf_report._load_architecture(  # noqa: SLF001 - producer owner
                content,
                None,
                architecture_bytes,
            )
            expected_input_digest = pdf_report._input_digest(  # noqa: SLF001 - producer owner
                bundle,
                content,
                architecture,
                None,
            )
            expected_reportlab_version = str(pdf_report.REPORTLAB_VERSION)

            with tempfile.TemporaryDirectory(prefix="atlas-pdf-") as temporary:
                generated_path = Path(temporary) / "master-reference.pdf"
                result = pdf_report.build_master_reference_pdf(
                    bundle,
                    content,
                    generated_path,
                    architecture_bytes=architecture_bytes,
                )
                pdf_value = generated_path.read_bytes()
                _validate_generated_pdf_observation_bindings(result)
                if (
                    len(pdf_value) != result.bytes
                    or sha256_bytes(pdf_value) != result.sha256
                    or result.sha256 != result.horizon_sink_verification.pdf_sha256
                    or result.sha256 != result.capability_sink_verification.pdf_sha256
                    or result.sha256 != result.core_sink_verification.pdf_sha256
                ):
                    raise ReleaseError("generated PDF changed after mechanical verification")
                inspection = pdf_report.inspect_pdf_report(
                    generated_path,
                    expected_commit=bundle.source_commit,
                    expected_tree_digest=bundle.source_tree_digest,
                )
                inspected_sha256 = inspection.sha256
                inspected_bytes = inspection.bytes
                inspected_page_count = inspection.page_count
                if (
                    generated_path.read_bytes() != pdf_value
                    or inspected_sha256 != result.sha256
                    or inspected_bytes != result.bytes
                    or inspected_page_count != result.page_count
                    or result.input_digest != expected_input_digest
                    or result.reportlab_version != expected_reportlab_version
                ):
                    raise ReleaseError("generated PDF provenance differs from verified producer owners")
                generated_pdf_provenance = {
                    "sha256": sha256_bytes(pdf_value),
                    "bytes": len(pdf_value),
                    "page_count": inspected_page_count,
                    "input_digest": expected_input_digest,
                    "renderer": f"ReportLab {expected_reportlab_version}",
                }
            lineage = (
                evaluate_rendered_sink_lineage(
                    contract=lineage_contract,
                    claim_facet_records=bundle.records["consequential_claim_facets"],
                    horizon=content.horizon,
                    source_raw=horizon_raw,
                    source_blob_oid=horizon_source_oid,
                    sink_observations={"pdf.open-horizon": result.horizon_sink_observations},
                )
                if lineage_declared
                else unavailable_rendered_sink_lineage(
                    contract=lineage_contract,
                    source_raw=horizon_raw,
                    source_blob_oid=horizon_source_oid,
                    reason_code="rendered_sink_lineage_compiler_subjects_not_declared",
                )
            )
            capability_lineage = (
                evaluate_capability_sink_lineage(
                    contract=capability_lineage_contract,
                    claim_facet_records=bundle.records["consequential_claim_facets"],
                    capability=content.capabilities,
                    source_raw=capability_raw,
                    source_blob_oid=capability_source_oid,
                    sink_observations={
                        "pdf.capability-catalog": result.capability_sink_observations,
                    },
                )
                if capability_lineage_declared
                else unavailable_capability_sink_lineage(
                    contract=capability_lineage_contract,
                    source_raw=capability_raw,
                    source_blob_oid=capability_source_oid,
                    reason_code="capability_sink_lineage_compiler_subjects_not_declared",
                )
            )
            core_lineage = (
                evaluate_core_sink_lineage(
                    contract=core_lineage_contract,
                    claim_facet_records=bundle.records["consequential_claim_facets"],
                    core=content.core,
                    source_raw=core_raw,
                    source_blob_oid=core_source_oid,
                    sink_observations={
                        "pdf.product-purpose-and-outcomes": result.core_sink_observations,
                    },
                )
                if core_lineage_declared
                else unavailable_core_sink_lineage(
                    contract=core_lineage_contract,
                    source_raw=core_raw,
                    source_blob_oid=core_source_oid,
                    reason_code="core_sink_lineage_compiler_subjects_not_declared",
                )
            )
            pdf_status = "generated_visual_review_pending"
            pdf_gate = {
                "schema_version": "1.0.0",
                "status": pdf_status,
                "included": True,
                "required_for_verified_release": True,
                "binary_privacy_coverage": "source_bound_inputs_scanned_pdf_container_not_content_scanned",
                "sha256": generated_pdf_provenance["sha256"],
                "bytes": generated_pdf_provenance["bytes"],
                "page_count": generated_pdf_provenance["page_count"],
                "input_digest": generated_pdf_provenance["input_digest"],
                "renderer": generated_pdf_provenance["renderer"],
                "independent_verification_verdict": result.independent_verification_verdict,
                "horizon_sink_mechanical_verification": {
                    "verdict": result.horizon_sink_verification.verdict,
                    "observation_digest": result.horizon_sink_verification.observation_digest,
                    "verification_digest": result.horizon_sink_verification.verification_digest,
                    "pdf_sha256": result.horizon_sink_verification.pdf_sha256,
                    "rendered_observation_count": result.horizon_sink_verification.rendered_observation_count,
                    "safety_observation_count": result.horizon_sink_verification.safety_observation_count,
                },
                "rendered_sink_lineage": lineage,
                "capability_sink_mechanical_verification": {
                    "verdict": result.capability_sink_verification.verdict,
                    "observation_digest": result.capability_sink_verification.observation_digest,
                    "verification_digest": result.capability_sink_verification.verification_digest,
                    "pdf_sha256": result.capability_sink_verification.pdf_sha256,
                    "rendered_observation_count": result.capability_sink_verification.rendered_observation_count,
                    "safety_observation_count": result.capability_sink_verification.safety_observation_count,
                },
                "capability_sink_lineage": capability_lineage,
                "core_sink_mechanical_verification": {
                    "verdict": result.core_sink_verification.verdict,
                    "observation_digest": result.core_sink_verification.observation_digest,
                    "verification_digest": result.core_sink_verification.verification_digest,
                    "pdf_sha256": result.core_sink_verification.pdf_sha256,
                    "rendered_observation_count": result.core_sink_verification.rendered_observation_count,
                    "safety_observation_count": result.core_sink_verification.safety_observation_count,
                },
                "core_sink_lineage": core_lineage,
                "claim": "The deterministic renderer produced and structurally inspected this source-bound PDF; independent page review remains required.",
                "next_gate": "Render every page with Poppler and record independent overflow, accessibility, and content-reconciliation evidence.",
            }
        else:
            pdf_status, pdf_value, pdf_gate = _pdf_input(pdf_path)
            if lineage_declared:
                pdf_gate["rendered_sink_lineage"] = evaluate_rendered_sink_lineage(
                    contract=lineage_contract,
                    claim_facet_records=bundle.records["consequential_claim_facets"],
                    horizon=content.horizon,
                    source_raw=horizon_raw,
                    source_blob_oid=horizon_source_oid,
                    sink_observations={},
                )
            else:
                pdf_gate["rendered_sink_lineage"] = unavailable_rendered_sink_lineage(
                    contract=lineage_contract,
                    source_raw=horizon_raw,
                    source_blob_oid=horizon_source_oid,
                    reason_code="rendered_sink_lineage_compiler_subjects_not_declared",
                )
            if capability_lineage_declared:
                pdf_gate["capability_sink_lineage"] = evaluate_capability_sink_lineage(
                    contract=capability_lineage_contract,
                    claim_facet_records=bundle.records["consequential_claim_facets"],
                    capability=content.capabilities,
                    source_raw=capability_raw,
                    source_blob_oid=capability_source_oid,
                    sink_observations={},
                )
            else:
                pdf_gate["capability_sink_lineage"] = unavailable_capability_sink_lineage(
                    contract=capability_lineage_contract,
                    source_raw=capability_raw,
                    source_blob_oid=capability_source_oid,
                    reason_code="capability_sink_lineage_compiler_subjects_not_declared",
                )
            if core_lineage_declared:
                pdf_gate["core_sink_lineage"] = evaluate_core_sink_lineage(
                    contract=core_lineage_contract,
                    claim_facet_records=bundle.records["consequential_claim_facets"],
                    core=content.core,
                    source_raw=core_raw,
                    source_blob_oid=core_source_oid,
                    sink_observations={},
                )
            else:
                pdf_gate["core_sink_lineage"] = unavailable_core_sink_lineage(
                    contract=core_lineage_contract,
                    source_raw=core_raw,
                    source_blob_oid=core_source_oid,
                    reason_code="core_sink_lineage_compiler_subjects_not_declared",
                )
        validate_release_object(
            repo_root,
            "pdf-gate",
            pdf_gate,
            pdf_provenance=generated_pdf_provenance,
        )
        expected_output_members = _validate_output_contract(content, pdf_included=pdf_value is not None)
        graph = bundle.completeness.get("graphify", {})
        graph_gate = (
            "passed"
            if graph.get("available") is True and graph.get("stale") is False and graph.get("status") == "current"
            else "pending_exact_commit_graphify_refresh"
        )
        acceptance_gates = list(bundle.completeness["acceptance_gates"])
        failed_acceptance_gates = sorted(
            str(item["name"]) for item in acceptance_gates if item.get("passed") is not True
        )
        semantic_gate = "passed" if not failed_acceptance_gates else "blocked"
        release_status = (
            "unsigned_preview_incomplete"
            if pdf_value is None or graph_gate != "passed" or semantic_gate != "passed"
            else "unsigned_preview"
        )
        # Validate a requested gap before any output is created.
        enhancement_value = enhancement_brief(content, enhancement_gap)
        compiler_preservation = _compiler_preservation_entries(bundle)
        curated_preservation = dict(content.raw_files)
        dependency_preservation = _dependency_sources(repo_root, bundle)
        if _dependency_receipts(dependency_preservation) != dependency_receipts:
            raise ReleaseInputError("dependency inputs changed before preservation")
        staged = prepare_output(output)
        target = staged.staging

        primary: list[dict[str, Any]] = []
        index = source_symbol_index(bundle)
        reference = machine_reference(bundle, content, sbom, release_status)
        primary.append(
            _artifact(target, "atlas-reference.json", canonical_json(reference), "machine-readable-reference")
        )
        primary.append(
            _artifact(
                target,
                "owner-handbook.md",
                owner_handbook(bundle, content, pdf_status, release_status).encode("utf-8"),
                "owner-handbook",
            )
        )
        primary.append(
            _artifact(
                target,
                "engineering-dossier.md",
                engineering_dossier(bundle, content, sbom, pdf_status, release_status).encode("utf-8"),
                "engineering-dossier",
            )
        )
        primary.append(
            _artifact(target, "source-symbol-index.json", canonical_json(index), "source-symbol-index-machine")
        )
        primary.append(
            _artifact(
                target,
                "source-symbol-index.md",
                source_symbol_markdown(index).encode("utf-8"),
                "source-symbol-index-human",
            )
        )
        primary.append(
            _artifact(
                target,
                "capability-gap-report.md",
                capability_gap_report(content).encode("utf-8"),
                "capability-gap-report",
            )
        )
        primary.append(
            _artifact(
                target,
                "decisions-opportunities.md",
                decisions_opportunities(content).encode("utf-8"),
                "decision-opportunity-report",
            )
        )
        primary.append(
            _artifact(target, "enhancement-brief-template.md", enhancement_value.encode("utf-8"), "enhancement-brief")
        )
        primary.append(
            _artifact(target, "agent-pack.md", agent_pack(bundle, content).encode("utf-8"), "agent-continuity-pack")
        )
        primary.append(_artifact(target, "bom.cdx.json", canonical_json(sbom), "cyclonedx-sbom"))
        primary.append(
            _artifact(
                target,
                "master-reference.html",
                self_contained_html(bundle, content),
                "self-contained-executive-navigation-html",
            )
        )
        primary.append(_artifact(target, "pdf-gate.json", canonical_json(pdf_gate), "pdf-gate"))
        if pdf_value is not None:
            pdf_role = (
                "deterministically-rendered-master-reference-pdf"
                if pdf_status == "generated_visual_review_pending"
                else "externally-rendered-master-reference-pdf"
            )
            primary.append(_artifact(target, "master-reference.pdf", pdf_value, pdf_role))
        preservation_coverage = _preservation_coverage(bundle)
        validate_release_object(repo_root, "preservation-coverage", preservation_coverage)
        primary.append(
            _artifact(
                target,
                "preservation-coverage.json",
                canonical_json(preservation_coverage),
                "preservation-coverage-ledger",
            )
        )
        provenance = provenance_statement(
            bundle,
            content.receipts,
            dependency_receipts,
            primary,
            pdf_status=pdf_status,
        )
        primary.append(_artifact(target, "provenance.json", canonical_json(provenance), "provenance-statement"))

        core_bytes = collect_output_bytes(target, primary)
        offline_entries = dict(core_bytes)
        offline_entries.update(compiler_preservation)
        offline_entries["OFFLINE-README.md"] = (
            "# Atlas Master Reference offline bundle\n\n"
            f"Exact source: `{bundle.source_commit}`. Open `master-reference.html` locally for the executive navigation view. "
            "The complete machine line/source/symbol projection is under `compiler/`; use `source-symbol-index.json` to locate records. "
            "Verify entries with `bundle-receipt.json`. The artifact inventory, outer release manifest, and optional detached "
            "owner signature are sibling family members and are not embedded in this ZIP. No network connection is required.\n"
        ).encode("utf-8")
        offline_entries["bundle-receipt.json"] = _bundle_receipt(
            offline_entries, bundle.source_commit, "offline-bundle"
        )
        offline = _artifact(
            target, "atlas-master-reference-offline.zip", deterministic_zip(offline_entries), "offline-zip"
        )

        preservation_entries = dict(core_bytes)
        preservation_entries.update(compiler_preservation)
        for name, value in sorted(curated_preservation.items()):
            preservation_entries[f"curated/{name}"] = value
        for name, value in sorted(dependency_preservation.items()):
            preservation_entries[f"dependency-inputs/{name}"] = value
        preservation_entries["RECOVERY.md"] = (
            "# Atlas preservation recovery\n\n"
            "This archive does not contain the artifact inventory, outer release manifest, detached signature, owner keys, "
            "package caches, wheelhouse, or toolchain installers. See `preservation-coverage.json` for the exact blocked denominator.\n\n"
            "1. If the owner separately signed the sibling release manifest, verify that detached signature against the separately trusted owner key.\n"
            "2. Verify this archive digest against the sibling release manifest; neither file is embedded here.\n"
            "3. Verify `bundle-receipt.json`, then extract with path traversal protections.\n"
            "4. Read compiler/manifest.json and completeness.json before treating the projection as complete.\n"
            "5. Serve master-reference.html from an offline static origin or open it directly.\n"
            "6. Do not claim bare-machine recovery until the missing/external materials and exercises in preservation-coverage.json are satisfied.\n"
        ).encode("utf-8")
        preservation_entries["bundle-receipt.json"] = _bundle_receipt(
            preservation_entries, bundle.source_commit, "preservation-pack"
        )
        preservation = _artifact(
            target,
            "atlas-master-reference-preservation.zip",
            deterministic_zip(preservation_entries),
            "preservation-pack",
        )

        pre_attestation = primary + [offline, preservation]
        attestation = _family_attestation(
            bundle,
            content,
            pre_attestation,
            expected_output_members,
        )
        validate_release_object(repo_root, "family-attestation", attestation)
        family_attestation_receipt = _artifact(
            target,
            "family-attestation.json",
            canonical_json(attestation),
            "complete-family-attestation",
        )
        inventoriable = pre_attestation + [family_attestation_receipt]
        inventory = {
            "schema_version": "1.0.0",
            "id": stable_id("artifact-inventory", bundle.source_commit, bundle.source_tree_digest),
            "status": release_status,
            "source_commit": bundle.source_commit,
            "source_tree_digest": bundle.source_tree_digest,
            "artifacts": sorted(inventoriable, key=lambda item: item["path"]),
            "signature_coverage": "Not currently signed. A future owner Ed25519 signature over the exact sibling release-manifest.json would transitively cover this inventory and every listed digest.",
            "self_exclusions": ["artifact-inventory.json", "release-manifest.json", "release-manifest.sig.json"],
        }
        validate_release_object(repo_root, "artifact-inventory", inventory)
        inventory_receipt = _artifact(
            target, "artifact-inventory.json", canonical_json(inventory), "artifact-inventory"
        )
        source_after_build = validate_exact_source(repo_root, bundle)
        if source_after_build != source_before:
            raise ReleaseInputError("exact repository source state changed during release build")
        generated_privacy_gate = (
            "blocked_external_pdf_binary_not_content_inspected"
            if pdf_status == "externally_supplied_visual_review_pending"
            else "passed_text_outputs_binary_containers_not_content_scanned"
        )
        dependency_vulnerability_gate, dependency_vulnerability_limits = _dependency_vulnerability_assessment(sbom)
        manifest = {
            "schema_version": "1.0.0",
            "id": stable_id("release-manifest", bundle.source_commit, bundle.source_tree_digest),
            "release_status": release_status,
            "publication_status": "not_authorized",
            "source_binding": {
                "source_commit": bundle.source_commit,
                "head_tree_oid": bundle.manifest["head_tree_oid"],
                "index_digest": bundle.manifest["index_digest"],
                "source_tree_digest": bundle.source_tree_digest,
                "repository_input_basis": "raw_selected_commit_git_blobs",
                "tracked_worktree_dirty": False,
                "before_build": source_before.as_dict(),
                "after_build": source_after_build.as_dict(),
            },
            "compiler": {
                "schema_version": bundle.manifest["schema_version"],
                "completeness_id": bundle.completeness["id"],
                "all_structural_invariants_passed": all(
                    item.get("passed") is True for item in bundle.completeness["invariants"]
                ),
                "all_semantic_acceptance_gates_passed": not failed_acceptance_gates,
                "failed_semantic_acceptance_gates": failed_acceptance_gates,
                "manifest_sha256": sha256_bytes(canonical_json(bundle.manifest)),
            },
            "gates": {
                "whole_repository_compiler": "passed",
                "architecture_conformance": "passed",
                "semantic_acceptance": semantic_gate,
                "self_contained_complete_viewer": "blocked_executive_navigation_only",
                "graphify_exact_commit": graph_gate,
                "privacy_allowlist": "passed",
                "generated_output_high_confidence_secret_scan": generated_privacy_gate,
                "binary_output_privacy_review": (
                    "blocked_external_pdf"
                    if pdf_status == "externally_supplied_visual_review_pending"
                    else "pending_contextual_and_container_review"
                ),
                "deterministic_archives": "passed",
                "preservation_recovery": "blocked_missing_external_materials_and_exercises",
                "python_transitive_dependency_lock": "blocked_declarations_only",
                "dependency_license_completeness": "blocked_unknown_licenses_present",
                "dependency_vulnerability_assessment": dependency_vulnerability_gate,
                "pdf": pdf_status,
                "independent_visual_review": "pending",
                "ed25519_signature": "pending_external_owner_key",
                "public_publication_authority": "absent",
            },
            "independent_verification_verdict": "BLOCK",
            "artifacts": sorted(inventoriable + [inventory_receipt], key=lambda item: item["path"]),
            "signing": {
                "algorithm": "Ed25519",
                "signature_target": "release-manifest.json",
                "signature_envelope": "release-manifest.sig.json",
                "key_policy": "owner-supplied external private key; no key generation or secret storage by this builder",
            },
            "privacy": bundle.completeness.get("privacy", {}),
            "honest_limits": [
                "Unsigned previews are not verified releases.",
                "PDF remains incomplete or independently unreviewed according to pdf-gate.json.",
                *dependency_vulnerability_limits,
                "Python dependency declarations are not a transitive resolution lock.",
                "Static and Graphify edges are not runtime truth.",
                "Structural line mapping is not behavioral or Level 4 understanding; failed semantic acceptance gates remain explicit.",
                "The generated-output scanner covers high-confidence credential forms; privacy review remains required for contextual or encoded sensitive data.",
                "PDF and ZIP compressed binary containers are not treated as UTF-8 privacy-scan proof; external PDF privacy coverage is explicitly blocked.",
                "Preservation caches, installers, recovery keys, and exercise receipts are missing or externally custodied as detailed in preservation-coverage.json.",
                "The self-contained HTML is an executive navigation view; complete safe source and line records are carried in the offline ZIP compiler projection, not embedded in the page.",
                "Cryptographic verification does not grant publication authority.",
            ],
            "manifest_self_exclusion": "A manifest cannot contain its own digest; sign these exact canonical bytes externally.",
        }
        validate_release_object(repo_root, "release-manifest", manifest)
        _artifact(target, "release-manifest.json", canonical_json(manifest), "release-manifest")
        actual_output_members = {path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file()}
        if actual_output_members != expected_output_members:
            raise ReleaseInputError(
                "emitted release members differ from output contract "
                f"(missing={sorted(expected_output_members - actual_output_members)}, "
                f"extra={sorted(actual_output_members - expected_output_members)})"
            )
        source_final = validate_exact_source(repo_root, bundle)
        if source_final != source_before:
            raise ReleaseInputError("exact repository source state changed after release finalization")
        staged.publish()
        return manifest
    except (ReleaseInputError, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ReleaseError(str(exc)) from None
    finally:
        if staged is not None:
            staged.cleanup()
