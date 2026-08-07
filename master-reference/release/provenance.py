"""Deterministic provenance statement rendering."""

from __future__ import annotations

from typing import Any, Iterable

from .compiler_bundle import CompilerBundle
from .model import canonical_json, sha256_bytes


def provenance_statement(
    bundle: CompilerBundle,
    content_receipts: Iterable[dict[str, Any]],
    dependency_receipts: Iterable[dict[str, Any]],
    artifact_subjects: Iterable[dict[str, Any]],
    *,
    pdf_status: str,
) -> dict[str, Any]:
    materials = [
        {
            "uri": "git+repository@" + bundle.source_commit,
            "digest": {
                "gitCommit": bundle.source_commit,
                "sha256": bundle.source_tree_digest,
            },
        },
        {
            "uri": "atlas-compiler:manifest.json",
            "digest": {"sha256": sha256_bytes(canonical_json(bundle.manifest))},
        },
    ]
    for item in sorted([*content_receipts, *dependency_receipts], key=lambda value: value["path"]):
        materials.append({"uri": item["path"], "digest": {"sha256": item["sha256"]}})
    return {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [
            {"name": item["path"], "digest": {"sha256": item["sha256"]}}
            for item in sorted(artifact_subjects, key=lambda value: value["path"])
        ],
        "predicateType": "https://atlas.local/provenance/core-artifacts/v1",
        "predicate": {
            "scope": (
                "Core-artifact provenance only. Outer archives, family attestation, artifact inventory, "
                "release manifest, and any detached owner signature are closed by later family receipts."
            ),
            "buildDefinition": {
                "buildType": "https://atlas.local/build-types/master-reference/v1",
                "externalParameters": {
                    "sourceCommit": bundle.source_commit,
                    "sourceTreeDigest": bundle.source_tree_digest,
                    "pdfGate": pdf_status,
                    "network": "not-used",
                },
                "internalParameters": {
                    "canonicalJson": "sorted-keys-compact-utf8-lf",
                    "archiveProfile": "sorted-fixed-epoch-0644-deflate9",
                    "repositoryInputBasis": "raw-selected-commit-git-blobs",
                },
                "resolvedDependencies": materials,
            },
            "runDetails": {
                "builder": {"id": "https://atlas.local/builders/master-reference-release/1.0.0"},
                "metadata": {
                    "invocationId": f"urn:atlas:release:{bundle.source_commit}:{bundle.source_tree_digest}",
                    "startedOn": None,
                    "finishedOn": None,
                    "reproducible": False,
                    "reproducibilityClass": (
                        "bounded deterministic JSON/HTML/ZIP/PDF payloads for pinned declared inputs; "
                        "toolchain wheelhouse, host-independent PDF equivalence, and clean-room rebuild remain external gates"
                    ),
                },
                "byproducts": [
                    {"name": "completeness-ledger", "digest": {"sha256": bundle.manifest["completeness"]["sha256"]}}
                ],
            },
            "privacy": {
                "corpus": "compiler allowlist plus curated contracts and dependency declarations",
                "vault": "not-read",
                "clientData": "not-read",
                "highConfidenceCredentialScan": (
                    "blocked-external-pdf-binary-not-inspected"
                    if pdf_status == "externally_supplied_visual_review_pending"
                    else "textual-outputs-passed-binary-containers-not-content-scanned"
                ),
                "machineLocalMemory": "not-read",
            },
        },
    }
