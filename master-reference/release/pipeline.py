"""Single-manifest deterministic release family builder."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from atlas_privacy import forbidden_byte_findings

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


def _dependency_vulnerability_assessment(sbom: dict[str, Any]) -> tuple[str, list[str]]:
    """Describe the tracked dependency state without pretending an SBOM is a VEX."""

    components = sbom.get("components", [])
    affected_image_size_versions = sorted(
        {
            str(component.get("version"))
            for component in components
            if isinstance(component, dict)
            and component.get("name") == "image-size"
            and (
                (comparison := _semver_compare_to_stable(component.get("version"), (2, 0, 2)))
                is None
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
    if affected_image_size_versions and affected_nanoid_versions:
        return "blocked_multiple_unremediated_high_dependency_advisories", limits
    if affected_image_size_versions:
        return "blocked_image_size_unpatched_build_time_high_advisories", limits
    if affected_nanoid_versions:
        return "blocked_nanoid_unremediated_high_advisory", limits
    return (
        "blocked_external_current_advisory_applicability_review_required",
        [
            "SBOM inventory does not assert vulnerability absence; a current source-authenticated "
            "advisory and applicability/VEX review is not embedded in this release."
        ],
    )


def _artifact(root: Path, relative: str, value: bytes, role: str) -> dict[str, Any]:
    suffix = PurePosixPath(relative).suffix
    if suffix in TEXT_SCAN_SUFFIXES:
        findings = forbidden_byte_findings(relative, value)
        if findings:
            labels = ", ".join(
                f"{item['path']}:{item['line']}:{item['rule']}" for item in findings
            )
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
    return {
        relative: read_bound_source_blob(repo_root, bundle, relative)
        for relative in sorted(set(NPM_LOCKFILES + PYTHON_DECLARATIONS))
    }


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


def _compiler_preservation_entries(bundle: CompilerBundle) -> dict[str, bytes]:
    entries: dict[str, bytes] = {"compiler/manifest.json": canonical_json(bundle.manifest)}
    expected: dict[str, dict[str, Any]] = {
        bundle.manifest["completeness"]["path"]: bundle.manifest["completeness"],
        bundle.manifest["graphify_metadata"]["path"]: bundle.manifest["graphify_metadata"],
        bundle.manifest["architecture_conformance"]["path"]: bundle.manifest[
            "architecture_conformance"
        ],
    }
    for group in bundle.manifest["groups"].values():
        for chunk in group["chunks"]:
            expected[chunk["path"]] = chunk
    if set(expected) | {"manifest.json"} != set(bundle.input_files):
        raise ReleaseInputError("compiler preservation allowlist differs from validated inputs")
    for relative, item in sorted(expected.items()):
        value = read_bytes(bundle.root, relative)
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
            "entries": [
                {"path": name, **receipt(value)} for name, value in sorted(entries.items())
            ],
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
        bundle = load_compiler_bundle(compiler_output)
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
        dependency_sources = _dependency_sources(repo_root, bundle)
        dependency_receipts = _dependency_receipts(dependency_sources)
        architecture_bytes = _bound_architecture(repo_root, bundle)
        _bind_tracked_inputs(bundle, [*content.receipts, *dependency_receipts])
        sbom = build_cyclonedx(dependency_sources, bundle.source_commit, bundle.source_tree_digest)
        if _dependency_receipts(_dependency_sources(repo_root, bundle)) != dependency_receipts:
            raise ReleaseInputError("dependency inputs changed during SBOM generation")
        if pdf_path is not None and generate_pdf:
            raise ReleaseInputError("choose either an external PDF or deterministic PDF generation, not both")
        if generate_pdf:
            from .pdf_report import build_master_reference_pdf

            with tempfile.TemporaryDirectory(prefix="atlas-pdf-") as temporary:
                generated_path = Path(temporary) / "master-reference.pdf"
                result = build_master_reference_pdf(
                    bundle,
                    content,
                    generated_path,
                    architecture_bytes=architecture_bytes,
                )
                pdf_value = generated_path.read_bytes()
            pdf_status = "generated_visual_review_pending"
            pdf_gate = {
                "schema_version": "1.0.0",
                "status": pdf_status,
                "included": True,
                "required_for_verified_release": True,
                "binary_privacy_coverage": "source_bound_inputs_scanned_pdf_container_not_content_scanned",
                "sha256": result.sha256,
                "bytes": result.bytes,
                "page_count": result.page_count,
                "input_digest": result.input_digest,
                "renderer": f"ReportLab {result.reportlab_version}",
                "independent_verification_verdict": result.independent_verification_verdict,
                "claim": "The deterministic renderer produced and structurally inspected this source-bound PDF; independent page review remains required.",
                "next_gate": "Render every page with Poppler and record independent overflow, accessibility, and content-reconciliation evidence.",
            }
        else:
            pdf_status, pdf_value, pdf_gate = _pdf_input(pdf_path)
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
        primary.append(_artifact(target, "atlas-reference.json", canonical_json(reference), "machine-readable-reference"))
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
        primary.append(_artifact(target, "source-symbol-index.json", canonical_json(index), "source-symbol-index-machine"))
        primary.append(_artifact(target, "source-symbol-index.md", source_symbol_markdown(index).encode("utf-8"), "source-symbol-index-human"))
        primary.append(
            _artifact(target, "capability-gap-report.md", capability_gap_report(content).encode("utf-8"), "capability-gap-report")
        )
        primary.append(
            _artifact(target, "decisions-opportunities.md", decisions_opportunities(content).encode("utf-8"), "decision-opportunity-report")
        )
        primary.append(
            _artifact(target, "enhancement-brief-template.md", enhancement_value.encode("utf-8"), "enhancement-brief")
        )
        primary.append(_artifact(target, "agent-pack.md", agent_pack(bundle, content).encode("utf-8"), "agent-continuity-pack"))
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
        offline_entries["bundle-receipt.json"] = _bundle_receipt(offline_entries, bundle.source_commit, "offline-bundle")
        offline = _artifact(target, "atlas-master-reference-offline.zip", deterministic_zip(offline_entries), "offline-zip")

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
        inventory_receipt = _artifact(target, "artifact-inventory.json", canonical_json(inventory), "artifact-inventory")
        source_after_build = validate_exact_source(repo_root, bundle)
        if source_after_build != source_before:
            raise ReleaseInputError("exact repository source state changed during release build")
        generated_privacy_gate = (
            "blocked_external_pdf_binary_not_content_inspected"
            if pdf_status == "externally_supplied_visual_review_pending"
            else "passed_text_outputs_binary_containers_not_content_scanned"
        )
        dependency_vulnerability_gate, dependency_vulnerability_limits = (
            _dependency_vulnerability_assessment(sbom)
        )
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
        actual_output_members = {
            path.relative_to(target).as_posix()
            for path in target.rglob("*")
            if path.is_file()
        }
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
        raise ReleaseError(str(exc)) from exc
    finally:
        if staged is not None:
            staged.cleanup()
