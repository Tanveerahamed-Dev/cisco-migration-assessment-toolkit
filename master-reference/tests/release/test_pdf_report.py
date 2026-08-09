from __future__ import annotations

import hashlib
import shutil
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from pypdf import PdfReader


MASTER_REFERENCE = Path(__file__).resolve().parents[2]
if str(MASTER_REFERENCE) not in sys.path:
    sys.path.insert(0, str(MASTER_REFERENCE))

from release.compiler_bundle import CompilerBundle  # noqa: E402
from release.content_bundle import ContentBundle, load_content_bundle  # noqa: E402
from release.pdf_report import (  # noqa: E402
    _load_architecture,
    build_master_reference_pdf,
    inspect_pdf_report,
    render_pdf_for_visual_qa,
)


COMMIT = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
TREE = "9" * 64
RAW_SOURCE_SENTINEL = "RAW-SOURCE-MUST-NEVER-ENTER-THE-PDF-7e3c86c4"


def _bundle(tmp_path: Path) -> CompilerBundle:
    groups = {
        name: {"record_count": count, "chunk_count": 1 if count else 0, "chunks": []}
        for name, count in {
            "files": 12,
            "lines": 87,
            "source_text": 10,
            "symbols": 9,
            "structural_entities": 10,
            "routes": 4,
            "components": 5,
            "tests": 7,
            "workflows": 2,
            "datasets": 3,
            "binaries": 2,
            "dependencies": 11,
            "claims": 6,
        }.items()
    }
    manifest = {
        "schema_version": "1.1.0",
        "status": "complete",
        "source_commit": COMMIT,
        "head_tree_oid": "8" * 40,
        "index_digest": "7" * 64,
        "source_tree_digest": TREE,
        "tracked_worktree_dirty": False,
        "groups": groups,
    }
    completeness = {
        "id": "urn:atlas:completeness:fixture",
        "schema_version": "1.1.0",
        "source_commit": COMMIT,
        "source_tree_digest": TREE,
        "tracked_worktree_dirty": False,
        "hard_failure": False,
        "fatal_errors": [],
        "census": {
            "tracked_files": 12,
            "classified_files": 12,
            "full_exposure_files": 10,
            "metadata_only_files": 2,
        },
        "parsing": {
            "status_counts": {"parsed": 12},
            "expected_nonblank_lines": 87,
            "line_records": 87,
            "lines_with_explicit_unresolved_reasons": 45,
        },
        "semantic_accounting": {
            "symbol_records": 9,
            "symbol_dossiers": 9,
            "safe_parsed_sources": 10,
            "structural_root_entities": 10,
            "structural_root_kind_counts": {"documentation_document": 10},
            "structurally_mapped_lines": 87,
            "line_explanation_depth_counts": {"0": 0, "1": 87, "2": 0, "3": 0, "4": 0},
            "symbol_explanation_depth_counts": {"0": 0, "1": 9, "2": 0, "3": 0, "4": 0},
            "critical_or_public_symbols": 4,
            "critical_level_four_reviews": 0,
            "gui_surface_records": 9,
            "gui_dossiers": 9,
            "gui_dossier_evidence_state_counts": {"structural_only": 9},
            "gui_dossier_field_state_counts": {"not_evidenced": 135},
            "runtime_trace_state": "not_collected",
            "coverage_evidence_state": "structural_links_only",
        },
        "graphify": {
            "schema_version": "1.1.0",
            "source_commit": COMMIT,
            "source_tree_digest": TREE,
            "available": True,
            "status": "current",
            "stale": False,
            "projected_nodes": 42,
            "projected_edges": 71,
        },
        "privacy": {
            "primary_corpus": "git_ls_files_only",
            "obsidian_vault": "outside_repository_not_read",
            "client_state": "not_read",
            "network": "not_used",
        },
        "invariants": [
            {"name": "every_tracked_file_classified", "passed": True, "expected": 12, "actual": 12},
            {"name": "every_nonblank_text_line_has_one_record", "passed": True, "expected": 87, "actual": 87},
            {"name": "every_safe_parsed_source_has_one_structural_root", "passed": True, "expected": 10, "actual": 10},
            {"name": "every_safe_line_structurally_mapped", "passed": True, "expected": 87, "actual": 87},
            {"name": "every_gui_surface_has_standardized_evidence_honest_dossier", "passed": True, "expected": 9, "actual": 9},
            {"name": "no_silent_parser_failure", "passed": True, "expected": 0, "actual": 0},
        ],
        "acceptance_gates": [
            {"name": "every_symbol_has_dossier_fields", "passed": True, "expected": 9, "actual": 9},
            {"name": "every_safe_line_behaviorally_explained", "passed": False, "expected": 87, "actual": 0},
            {
                "name": "every_critical_or_public_symbol_level_four_reviewed",
                "passed": False,
                "expected": 4,
                "actual": 0,
            },
            {"name": "exact_clean_commit_binding", "passed": True, "expected": False, "actual": False},
        ],
    }
    # The generator receives records but must never read raw source or previews.
    records = {
        "source_text": [{"id": "source.fixture", "text": RAW_SOURCE_SENTINEL}],
        "lines": [{"id": "line.fixture", "text_preview": RAW_SOURCE_SENTINEL}],
        "symbols": [{"id": "symbol.fixture", "docstring": RAW_SOURCE_SENTINEL}],
    }
    return CompilerBundle(
        root=tmp_path / "compiler",
        manifest=manifest,
        completeness=completeness,
        records=records,
        input_files=("manifest.json", "completeness.json"),
    )


def _content(tmp_path: Path) -> ContentBundle:
    content_root = tmp_path / "master-reference" / "content"
    content_root.mkdir(parents=True)
    core = {
        "schema_version": "1.0.0",
        "id": "atlas.core.fixture",
        "as_of": "2026-08-07",
        "scope": "Repository-owned, client-free Atlas reference fixture.",
        "truth_contract": {
            "support_rule": "Catalog presence is not implementation support.",
            "client_data_rule": "No client or device evidence enters this layer.",
        },
        "outcomes": [
            {
                "id": "outcome.evidence",
                "title": "Evidence to decision",
                "success_signal": "Every decision can reach owned evidence.",
                "limitations": "Synthetic proof is not field validation.",
            }
        ],
        "non_goals": [{"id": "non-goal.write", "statement": "No device writes."}],
    }
    capabilities = {
        "schema_version": "1.0.0",
        "id": "atlas.capabilities.fixture",
        "denominator_rule": "Every declared cell is classified; expansion changes the denominator.",
        "domains": [
            {
                "id": "domain.outcomes",
                "entries": [
                    {
                        "id": "cap.outcomes.traceability",
                        "title": "Evidence traceability",
                        "state": "current",
                        "current_scope": "Owned evidence reaches a decision record.",
                        "owner_refs": ["owner.ssot"],
                    },
                    {
                        "id": "cap.outcomes.field-validation",
                        "title": "Field validation",
                        "state": "missing",
                        "current_scope": "No client evidence is admitted in this repository fixture.",
                        "gap_refs": ["gap.field-validation"],
                    },
                ],
            },
            {
                "id": "domain.security",
                "entries": [
                    {
                        "id": "cap.security.read-only",
                        "title": "Read-only boundary",
                        "state": "current",
                        "current_scope": "Reference surfaces cannot collect or mutate estate evidence.",
                        "owner_refs": ["owner.architecture"],
                    }
                ],
            },
        ],
    }
    governance = {
        "schema_version": "1.0.0",
        "id": "atlas.governance.fixture",
        "gaps": [
            {
                "id": "gap.field-validation",
                "title": "Field validation is absent",
                "priority": "P1",
                "disposition": "evidence-first",
                "problem": "Synthetic fixtures cannot establish production outcomes.",
                "next_actions": ["Define an owner-approved evidence contract.", "Collect only after explicit authority."],
                "acceptance_evidence": ["Sanitized field receipt.", "Independent outcome review."],
                "owner_role": "network owner",
            }
        ],
        "decision_queue": [
            {
                "id": "decision.field-evidence",
                "title": "Choose the field evidence boundary",
                "status": "open",
                "authority": "human network owner",
                "options": ["Do nothing", "Approve a bounded sanitized pilot"],
                "current_recommendation": "Approve nothing until the evidence contract is reviewed.",
                "evidence_needed": ["Privacy review", "Custody test"],
            }
        ],
        "opportunity_portfolio": {
            "ranking_rule": "Keep value, effort, uncertainty, and risk as separate axes.",
            "items": [
                {
                    "id": "opportunity.evidence",
                    "title": "Bounded evidence pilot",
                    "gap_refs": ["gap.field-validation"],
                    "horizon": "later",
                    "axes": {"user_value": 5, "implementation_effort": 3},
                    "axis_notes": "A candidate, not an approved commitment.",
                }
            ],
        },
        "invariants": [
            {
                "id": "invariant.no-write",
                "statement": "No device writes.",
                "scope": "All reference and analysis paths.",
                "residual_risk": "A future collector must remain separately authorized and read-only.",
                "owner_refs": ["owner.architecture"],
            }
        ],
    }
    horizon = {
        "schema_version": "1.0.0",
        "id": "atlas.horizon.fixture",
        "promise": "Open-world signals remain advisory and retain an unknown bucket.",
        "support_claim": "none",
        "watch_families": [
            {
                "id": "watch.official",
                "name": "Official standards source",
                "source_url": "https://example.invalid/official",
                "authority_scope": "Fixture primary-source lane.",
                "review_cadence": "quarterly",
                "content_role": "advisory",
                "engine_ingestion": "none",
            }
        ],
        "signals": [
            {
                "id": "signal.one",
                "title": "Emerging candidate",
                "disposition": "watch",
                "maturity": "research",
                "why_it_matters": "It may affect future architecture breadth.",
                "promotion_gate": "Owner, evidence, tests, and catalog denominator update.",
            }
        ],
    }
    return ContentBundle(
        root=content_root,
        core=core,
        capabilities=capabilities,
        governance=governance,
        horizon=horizon,
        output_contract={"schema_version": "1.0.0", "catalog_version": "fixture", "members": []},
        receipts=(),
        raw_files={},
    )


def _architecture(tmp_path: Path) -> Path:
    path = tmp_path / "master-reference" / "governance" / "architecture.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        """{
  "schema_version": "2.0.0",
  "edge_semantics": "caller_depends_on_provider",
  "components": [
    {"id": "repo_source", "layer": 0, "trust_zone": "repository", "paths": ["docs/"]},
    {"id": "evidence_intake", "layer": 1, "trust_zone": "boundary", "paths": ["input/"]},
    {"id": "master_reference", "layer": 10, "trust_zone": "private_read_only", "paths": ["master-reference/"]}
  ],
  "exclusions": [],
  "allowed_edges": [["master_reference", "repo_source"]],
  "forbidden_edges": [
    {"from": "master_reference", "to": "evidence_intake", "reason": "Reference accepts no client evidence."}
  ],
  "runtime_phases": [
    {"id": "intake", "order": 1, "required": true},
    {"id": "verify", "order": 2, "required": true}
  ]
}
""",
        encoding="utf-8",
    )
    return path


def _text(pdf: Path) -> str:
    reader = PdfReader(str(pdf))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_tracked_architecture_contract_is_supported_and_validated(tmp_path: Path) -> None:
    content = _content(tmp_path)
    architecture, digest = _load_architecture(
        content,
        MASTER_REFERENCE / "governance" / "architecture.json",
    )
    assert architecture is not None
    assert architecture["schema_version"] == "2.0.0"
    assert len(digest) == 64


def test_pdf_is_deterministic_source_bound_polished_and_never_embeds_source(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    content = _content(tmp_path)
    architecture = _architecture(tmp_path)
    first = tmp_path / "atlas-a.pdf"
    second = tmp_path / "atlas-b.pdf"

    result_a = build_master_reference_pdf(bundle, content, first, architecture_path=architecture)
    result_b = build_master_reference_pdf(bundle, content, second, architecture_path=architecture)

    assert first.read_bytes().startswith(b"%PDF-")
    assert first.read_bytes() == second.read_bytes()
    assert result_a.sha256 == hashlib.sha256(first.read_bytes()).hexdigest()
    assert result_a.sha256 == result_b.sha256
    assert result_a.independent_verification_verdict == "BLOCK"
    assert result_a.page_count >= 10

    reader = PdfReader(str(first))
    metadata = reader.metadata or {}
    assert metadata.get("/Title") == "Atlas Master Reference - Whole-Repository Accounting"
    assert metadata.get("/Author") == "Atlas repository"
    assert COMMIT in str(metadata.get("/Subject"))
    assert TREE in str(metadata.get("/Subject"))
    assert "non-releaseable" in str(metadata.get("/Keywords"))
    assert "Atlas deterministic PDF renderer" in str(metadata.get("/Creator"))
    assert reader.trailer["/Root"].get("/Lang") == "en-US"
    assert reader.trailer["/Root"].get("/Outlines") is not None

    extracted = _text(first)
    assert COMMIT in extracted
    assert "BLOCKED" in extracted
    assert "every_safe_line_behaviorally_explained" in extracted
    assert "/source/[path]" in extracted
    assert "CLIENT-DATA INGESTION PROHIBITED" in extracted
    assert "NO CLIENT DATA" not in extracted
    assert "\x7f" not in extracted
    assert "\ufffd" not in extracted
    assert RAW_SOURCE_SENTINEL not in extracted

    inspected = inspect_pdf_report(first, expected_commit=COMMIT, expected_tree_digest=TREE)
    assert inspected.page_count == result_a.page_count
    assert inspected.source_commit_present is True
    assert inspected.source_tree_digest_present is True


def test_curated_pdf_keeps_complete_records_together_and_extracts_clean_ascii(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    content = load_content_bundle(MASTER_REFERENCE / "content")
    pdf = tmp_path / "atlas-curated.pdf"

    build_master_reference_pdf(
        bundle,
        content,
        pdf,
        architecture_path=MASTER_REFERENCE / "governance" / "architecture.json",
    )

    raw_pages = [page.extract_text() or "" for page in PdfReader(str(pdf)).pages]
    pages = [" ".join(page.split()) for page in raw_pages]
    anchors = (
        (
            "Non-goals",
            "A lab, protocol primer, vendor page, or external link never establishes current product support",
        ),
        ("gap.white-label", "Contrast and localization checks"),
        ("Human decision queue", "decision.product-boundary"),
        ("decision.outcome-measurement", "uncertainty reporting"),
        ("invariant.horizon-separate", "A manual summary can overstate a watched technology"),
    )
    for start, end in anchors:
        assert any(start in page and end in page for page in pages), f"record split across pages: {start}"
    horizon_index = next(
        index
        for index, page in enumerate(pages)
        if "Open-world Horizon Register" in page and "Advisory only" in page
    )
    assert (
        "Support claim state: none - no current product support is claimed by this advisory register."
        in pages[horizon_index]
    )
    assert "none" not in {line.strip() for line in raw_pages[horizon_index].splitlines()}
    assert all("\x7f" not in page and "\ufffd" not in page for page in pages)


def test_pdf_preserves_decision_section_when_queue_is_empty(tmp_path: Path) -> None:
    content = load_content_bundle(MASTER_REFERENCE / "content")
    content = replace(content, governance={**content.governance, "decision_queue": []})
    pdf = tmp_path / "atlas-empty-decision-queue.pdf"

    build_master_reference_pdf(
        _bundle(tmp_path),
        content,
        pdf,
        architecture_path=MASTER_REFERENCE / "governance" / "architecture.json",
    )

    pages = [" ".join((page.extract_text() or "").split()) for page in PdfReader(str(pdf)).pages]
    assert any("Human decision queue" in page and "Opportunity portfolio" in page for page in pages)


def test_pdf_refuses_overwrite_and_rejects_nonclean_or_unbound_compiler(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    content = _content(tmp_path)
    architecture = _architecture(tmp_path)
    output = tmp_path / "atlas.pdf"
    output.write_bytes(b"owner content")
    with pytest.raises(FileExistsError, match="already exists"):
        build_master_reference_pdf(bundle, content, output, architecture_path=architecture)
    assert output.read_bytes() == b"owner content"

    dirty_manifest = {**bundle.manifest, "tracked_worktree_dirty": True}
    dirty = CompilerBundle(bundle.root, dirty_manifest, bundle.completeness, bundle.records, bundle.input_files)
    with pytest.raises(ValueError, match="exact clean"):
        build_master_reference_pdf(dirty, content, tmp_path / "dirty.pdf", architecture_path=architecture)

    stale_ledger = {**bundle.completeness, "source_commit": "f" * 40}
    stale = CompilerBundle(bundle.root, bundle.manifest, stale_ledger, bundle.records, bundle.input_files)
    with pytest.raises(ValueError, match="commit differs"):
        build_master_reference_pdf(stale, content, tmp_path / "stale.pdf", architecture_path=architecture)


@pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="Poppler is not available")
def test_visual_qa_helper_renders_every_page_without_mutating_pdf(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    content = _content(tmp_path)
    pdf = tmp_path / "atlas.pdf"
    result = build_master_reference_pdf(bundle, content, pdf, architecture_path=_architecture(tmp_path))
    before = hashlib.sha256(pdf.read_bytes()).hexdigest()

    pages = render_pdf_for_visual_qa(pdf, tmp_path / "qa", dpi=96)

    assert len(pages) == result.page_count
    assert all(path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n") for path in pages)
    assert hashlib.sha256(pdf.read_bytes()).hexdigest() == before
