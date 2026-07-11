# Learnings — the distilled, verifiable engine facts (read at SessionStart)

The feedback nerve's distilled store: durable, **verifiable** facts about this codebase/engine that
should shape every session. Discipline (enforced by `cisco_toolkit/learnings.py` +
`tests/test_learnings.py`): **under 100 lines · every entry cited · verifiable facts only, never a
self-assessment** (a store that records "great progress" and reads it back is the coasting trap).

This is NOT the raw session log (`docs/log.md`, the `/retro` source) nor the career/domain vault
(promoted via `/ingest`). It is the repo/engine facts worth remembering. To add one: state a
falsifiable fact and cite where it is checkable (a file, a test, or a commit).

## Engine / SSOT

- `ssot.reconcile(snap)` returns `[]` both when facts are clean AND when none are published — a
  non-vacuous "clean" gate must also require `ssot.summary(snap)["n_facts"] > 0`. Evidence:
  `cisco_toolkit/eval_harness.py::_check_reconcile`.
- `analyze.vlan_inventory` unions three evidence sources (access-port `.vlan`, `l3_forwarding[].vlan`,
  IGMP queriers), so a fixture publishing `n_vlans=N` must supply N distinct VLANs to reconcile.
  Evidence: `cisco_toolkit/analyze.py:1573`.
- Older-but-good snapshots predate `attestation`/`schema_census`; a coverage-honest check treats an
  absent signal as UNVERIFIED, never a fail. Evidence: `cisco_toolkit/eval_harness.py::_check_provenance`.

## Fixtures / goldens

- The frozen `tests/golden/snapshot.json` is stripped of `executive_brief`/`lifecycle_risk`/
  `design_blueprint` (date-relative) → it has 0 canonical facts, so it is NOT a Law-scoring fixture;
  build a synthetic fully-published one. Evidence: `tests/test_eval_harness.py` (`known_good_snapshot`).
- Adding ANY new `cisco_toolkit/*.py` module changes `tests/golden/snapshot.json`: the golden's
  attestation block pins the re-derived module-census strings ("0 LLM/GenAI SDK imports across N
  modules", "0 network-library imports across N analysis modules"). Sanctioned refresh:
  `UPDATE_GOLDEN=1 python -m pytest tests/test_pipeline_golden.py`; the reviewed diff must show ONLY
  the census strings changing, violation counts still 0. Precedent: PR #329 (P2-1) added
  `cisco_toolkit/d10_eval_set.py` → census 66→67, analysis modules 64→65. Evidence:
  `cisco_toolkit/attestation.py` + `tests/test_pipeline_golden.py::test_snapshot_matches_golden`.
- The real assessment snapshot (`Migration_Assessment_*.snapshot.json`) is untracked / absent from git
  → not a reliable committed fixture; score it opportunistically and SKIP when absent (coverage-honest).
  Evidence: `tests/test_eval_harness.py::test_real_on_disk_snapshot_scores_clean_if_present`.

## Tooling / workflow

- Piping pytest through `| tail` masks its exit code (the pipe returns tail's 0), hiding real failures;
  run `python -m pytest` unpiped or capture `$?` before any pipe. Evidence: `.claude/hooks/verify-green.sh`
  (the Stop gate runs pytest unpiped for exactly this reason).
- Memory consolidation deletes "superseded" facts on a schedule, so a rarely-referenced safety
  constraint survives only via the protected tier marker `protected: true`. Evidence:
  `cisco_toolkit/memory_guard.py` (D12) + the out-of-repo `anthropic-skills:consolidate-memory` skill.
- A transcript-scraping hook keyed on keywords fires on the MAIN agent's own prose that *describes* a
  verdict (a summary with "verdict"/"BLOCK" + a markdown table once fabricated a scorecard row); gate
  on the reviewer's structural signature — a per-artifact `X — BLOCK` line — not keyword co-occurrence.
  Evidence: `cisco_toolkit/scorecard.py` (`_ARTIFACT_VERDICT_RE`) + `tests/test_scorecard.py`.

## Deliverable docx / figure generation

- Editable, overlap-free figures come from a register-sourced data model → clean SVG (real `<text>` + shapes,
  editable in draw.io/Inkscape) → 600-DPI PNG via PyMuPDF (`fitz`), never hand-patched raster; auto-sized boxes +
  opaque label chips make overlap impossible by construction. Evidence: `[HISTORY-REDACTED]_DC_Design/figgen/svgkit.py`
  (+ `figdata.py` SSOT + `build/swap_figures.py`).
- `python-docx` cannot embed SVG (`add_picture` raises); a programmatically-assembled `.docx` needs raster PNG, so
  the SVG stays the editable master and the PNG is the embed. Evidence: `[HISTORY-REDACTED]_DC_Design/figgen/build/swap_figures.py`.
- A `.docx` authored by a non-python-docx tool (docx-js) exposes no style-name lookup: `add_paragraph(style="Heading 1")`
  raises `KeyError` though the body uses that style — capture the style OBJECT from an existing paragraph and assign
  it. Evidence: `[HISTORY-REDACTED]_DC_Design/figgen/build/build_v75_content.py` (`capture()`).
- A static (non-field) TOC does not auto-update; after any pagination change re-measure each Heading-1 page (Word COM
  `Range.Information(3)`) and patch the trailing `\t<page>` run — a live TOC field auto-updates on open instead. No
  LibreOffice/pandoc → docx→PDF via Word COM `ExportAsFixedFormat(path, 17)`. Evidence:
  `[HISTORY-REDACTED]_DC_Design/figgen/build/patch_toc.py` + `export_measure.py`.
