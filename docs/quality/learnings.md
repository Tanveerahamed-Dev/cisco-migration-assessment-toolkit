# Learnings — the distilled, verifiable engine facts (read at SessionStart)

The feedback nerve's distilled store: durable, **verifiable** facts about this codebase/engine that should
shape every session. Discipline (enforced by `cisco_toolkit/learnings.py` + `tests/test_learnings.py`): **under 100 lines · every entry cited · verifiable facts only, never a self-assessment** (a store that records "great progress" and reads it back is the coasting trap).

This is NOT the raw session log (`docs/log.md`, the `/retro` source) nor the career/domain vault (promoted
via `/ingest`). It is the repo/engine facts worth remembering. To add one: state a falsifiable fact and cite where it is checkable (a file, a test, or a commit).

## Engine / SSOT

- `ssot.reconcile(snap)` returns `[]` both when facts are clean AND when none are published — a non-vacuous
  "clean" gate must also require `ssot.summary(snap)["n_facts"] > 0`. Evidence: `cisco_toolkit/eval_harness.py::_check_reconcile`.
- `analyze.vlan_inventory` unions three evidence sources (access-port `.vlan`, `l3_forwarding[].vlan`, IGMP
  queriers), so a fixture publishing `n_vlans=N` must supply N distinct VLANs to reconcile. Evidence: `cisco_toolkit/analyze.py:1573`.
- Older-but-good snapshots predate `attestation`/`schema_census`; a coverage-honest check treats an
  absent signal as UNVERIFIED, never a fail. Evidence: `cisco_toolkit/eval_harness.py::_check_provenance`.
- An evidence-content digest must distinguish malformed structure from absence: coercing an unexpected dict/list
  to `""` or `{}` creates a same-hash mutation seam that can restore a hard verdict. Evidence: `cisco_toolkit/traffic_assurance.py::_content_binding_payload` + `tests/test_traffic_assurance.py`.
- A reference-only failure projection can be a required gate input without claiming survival when its complete receipt is bound to canonical authority, applicability is evidence-driven, and local eligibility stays below convergence/traffic/service assurance. Evidence: `cisco_toolkit/l2_rehearsal.py::validate_l2_failure_rehearsal` + `tests/test_l2_failure_rehearsal.py`.
- An offline renderer may claim a single-snapshot receipt only after the final emitted snapshot bytes are reread and frozen; rebuild the portfolio from that exact `BoundSnapshot`, publish the canonical uncapped export, and revalidate source + owner rebuild + export immediately before and after each atomic BOUND replacement. Post-freeze failures belong in custody/manifest metadata, never back in the bound snapshot. NRFU is AssessHub-only because the normal CLI has no NRFU writer. Evidence: `COLLECT_PARSE_V3_23_0.py::_stage_finalize/_atomic_receipt_refresh` + `tests/test_custody_pipeline.py`.

## Fixtures / goldens

- The frozen `tests/golden/snapshot.json` is stripped of
  `executive_brief`/`lifecycle_risk`/ `design_blueprint` (date-relative) → it has 0 canonical facts, so it is NOT a Law-scoring fixture; build a synthetic fully-published one. Evidence: `tests/test_eval_harness.py` (`known_good_snapshot`).
- Adding ANY new `cisco_toolkit/*.py` module changes `tests/golden/snapshot.json`: the golden's
  attestation block pins the re-derived module-census strings ("0 LLM/GenAI SDK imports across N
  modules", "0 network-library imports across N analysis modules"). Sanctioned refresh:
  `UPDATE_GOLDEN=1 python -m pytest tests/test_pipeline_golden.py`; the reviewed diff must show ONLY
  the census strings changing, violation counts still 0. Precedent: PR #329 (P2-1) added
  `cisco_toolkit/d10_eval_set.py` → census 66→67, analysis modules 64→65. Evidence:
  `cisco_toolkit/attestation.py` + `tests/test_pipeline_golden.py::test_snapshot_matches_golden`.
- The real assessment snapshot (`Migration_Assessment_*.snapshot.json`) is untracked / absent from git → not a
  reliable committed fixture; score it opportunistically and SKIP when absent (coverage-honest). Evidence: `tests/test_eval_harness.py::test_real_on_disk_snapshot_scores_clean_if_present`.

## Tooling / workflow

- Piping pytest through `| tail` masks its exit code (the pipe returns tail's 0), hiding real failures; run
  `python -m pytest` unpiped or capture `$?` before any pipe. Evidence: `.claude/hooks/verify-green.sh` (the Stop gate runs pytest unpiped for exactly this reason).
- The local full suite and `.github/workflows/main-selfhosted.yml` share one Windows host; check the live workflow before a local full run. Evidence: run `30980535490` + `docs/review-hardening-handoff-2026-07-30.md` section 5.17.
- Adding a tracked path under a ratcheted LF glob changes the complete path-set receipt even when it is not a derived byte owner; recompute `lf_scope` and `broader_declared_lf_scope` from the final tree. Evidence: `tests/test_transition_schema_assets.py::test_byte_bound_checkout_owners_are_lf_exactly_attributed` + `tests/fixtures/atlas-r2-byte-custody-policy.v1.json`.
- Release provenance, privacy, correctness, and reproducibility are separate proof axes. The old release gate
  proved origin exhaustively but never ran the tagged code's suite, so v3.32.0 shipped from a red commit; the current gate tests the tag's own content. Evidence: `.github/workflows/release-selfhosted.yml`.
- A Sites asset binding can return a stored `.mjs.gz` body with JavaScript MIME and no
  `Content-Encoding`; MIME and compound suffix alone therefore cannot prove whether the body is encoded.
  Validate the registered canonical gzip prefix before replaying a missing-encoding GET, and exercise the
  exact tuple across the Workerd HTTP boundary. Evidence: `master-reference/worker/index.ts` +
  `master-reference/tests/rendered-html.test.mjs` (`serves the exact live Sites-inferred metadata tuple`).
- Large generated JSON receipts can dominate Sites expanded size even when every payload module is already
  compressed. Preserve their canonical raw bytes as the conceptual digest basis, store only a deterministic
  gzip representation, and bind raw and representation byte/hash receipts across a noncircular outer census.
  When a fully validated inner receipt already owns a very large physical-member ledger, the outer receipt
  should store that authority representation as a direct member plus an exact count/bytes/full-ledger-digest
  summary, then compute its overall census from the sorted reconstructed union; duplicating all rows can itself
  exhaust the deployment budget.
  A header check alone is insufficient: bounded loaders must use the same opened file handle, require exactly
  one fixed-header member and EOF after its CRC/ISIZE trailer, then enforce strict UTF-8, canonical JSON, and
  exact raw/physical digests. Same-handle reads close only their individual read windows; a verifier that reads
  member classes in phases also needs exact pre/post physical-tree identity, size, and timestamp snapshots to
  reject inter-phase replacement. Pin the producer profile explicitly (currently level 9, memLevel 8 and `Z_FILTERED`) and reject receipt algorithm drift, but keep that declaration separate from portable proof:
  deflate bytes are producer-runtime-dependent, so verification must not recompress locally and compare bytes; the producer runtime and physical representation are disclosed and receipt-bound instead. Evidence:
  `master-reference/build/deterministic-gzip.mjs`, `compress-projection.mjs`, and
  `deployment-manifest.mjs` plus their focused source tests.
- Memory consolidation deletes "superseded" facts on a schedule, so a rarely-referenced safety constraint survives
  only via the protected tier marker `protected: true`. Evidence: `cisco_toolkit/memory_guard.py` (D12) + the out-of-repo `anthropic-skills:consolidate-memory` skill.
- A transcript-scraping hook keyed on keywords fires on the MAIN agent's own prose that *describes* a verdict
  (a summary with "verdict"/"BLOCK" + a markdown table once fabricated a scorecard row); gate on the reviewer's
  structural signature — a per-artifact `X — BLOCK` line — not keyword co-occurrence. Evidence: `cisco_toolkit/scorecard.py` (`_ARTIFACT_VERDICT_RE`) + `tests/test_scorecard.py`.

## Deliverable docx / figure generation

- Editable, overlap-free figures come from a register-sourced data model → clean SVG (real `<text>` + shapes,
  editable in draw.io/Inkscape) → 600-DPI PNG via PyMuPDF (`fitz`), never hand-patched raster; auto-sized boxes +
  opaque label chips make overlap impossible by construction. Evidence: `Reference_DC_Design/figgen/svgkit.py`
  (+ `figdata.py` SSOT + `build/swap_figures.py`).
- `python-docx` cannot embed SVG (`add_picture` raises); a programmatically-assembled `.docx` needs raster PNG, so
  the SVG stays the editable master and the PNG is the embed. Evidence: `Reference_DC_Design/figgen/build/swap_figures.py`.
- A `.docx` authored by a non-python-docx tool (docx-js) exposes no style-name lookup: `add_paragraph(style="Heading 1")`
  raises `KeyError` though the body uses that style — capture the style OBJECT from an existing paragraph and assign
  it. Evidence: `Reference_DC_Design/figgen/build/build_v75_content.py` (`capture()`).
- A static (non-field) TOC does not auto-update; after any pagination change re-measure each Heading-1 page (Word COM
  `Range.Information(3)`) and patch the trailing `\t<page>` run — a live TOC field auto-updates on open instead. No
  LibreOffice/pandoc → docx→PDF via Word COM `ExportAsFixedFormat(path, 17)`. Evidence:
  `Reference_DC_Design/figgen/build/patch_toc.py` + `export_measure.py`.
- The repo-wide review (2026-07-28, 98 findings) found ONE dominant class across every subsystem: an
  **empty/absent input treated as a clean one**. Its shapes are stable — `if not flags: flags = ["ok"]`;
  `.get(host, 1.0)` defaulting an unmeasured quality to perfect; a coverage guard keyed on a counter that reads 0
  both when everything was collected and when the census is MISSING; `any(...)`/`all(...)` over an empty list going
  vacuously the safe-looking way; a verifier gated on raw evidence that returns "no violations" having checked
  nothing. Grep those shapes before trusting any "pass"/"ok"/"verified". Evidence:
  `docs/review-findings-2026-07-28.md`; `cisco_toolkit/ssot.summary` (published 14 facts, reconciled 0, reported
  `verified: True`) and `selfcheck.check_guards_nonvacuous` (15 skipped suites read GREEN) are the two cleanest cases.
- A guard asserted only against its own SOURCE TEXT is not a guard. `verify-green.sh` — the Stop hook every other
  test's meaning rests on — was pinned by two substring greps and never executed; running it immediately exposed a
  change detector that missed any path git has to QUOTE. Execute the gate against a fixture whose outcome you chose,
  and mutate it to prove the assertion can fail. Evidence: `tests/test_ci_gates.py::test_stop_hook_BLOCKS_on_a_red_suite`.
- A DENYLIST pin cannot see a wildcard. The read-only analyst roster forbade four tool names, so `tools: *` — which grants every tool including Edit/Write — passed every parametrized case. Pin the property with an ALLOWLIST. Evidence: `tests/test_proposer_verifier_guard.py` (`READONLY_TOOLS`).
