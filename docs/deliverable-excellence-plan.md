# Deliverable Excellence — consolidation plan & status

Folding the **Deliverable Excellence Standard** (10 Laws + the agentic verify-gate ratchet) into the
engine's own generated deliverables, so every artifact the toolkit produces clears the same
best-in-industry bar. Grounded in a 4-way parallel audit of all 11 generators (every gap below is
file:line-verified). This doc is the single owner of the initiative's scope — see `docs/ssot.md`.

## The framing
This is a **presentation/explanation** upgrade, **not** new analysis (the analysis surface is
saturated). It attacks the recurring "half-baked / reader still has questions" gap, turned on our
*own* output. The engine was already strong on the analytical Laws (SSOT machinery in `ssot.py`,
coverage-honesty/`[NOT OBSERVED]`, traceability) and weak on orientation/explanation (no glossary,
no anticipated-questions register, hand-recounted headline numbers).

## P0 — Foundation ✅ SHIPPED (commit `1eed14c`, branch `feat/deliverable-excellence-sections`)
Fix-once in the shared `cisco_toolkit/docmeta.py`, wired into all 7 DOCX writers
(design/crd/archreview/mop/runbook/ops/engagement):
- **`add_excellence_front(doc, snap)`** — an "At a Glance" anticipated-questions register (Law 6)
  reading `ssot.canonical_facts` (Law 1, never a recount) + the `ssot.summary` self-verified badge
  (Law 10); coverage-honest `[NOT OBSERVED]` on absent blocks (Law 8).
- **`add_glossary(doc)`** — shared term/convention glossary incl. the coverage-honesty legend (T2).
- **`add_document_control`** now emits a **Distribution list** (Law 2) for the whole family.
- **Ratchet**: `tests/test_deliverable_excellence.py` fails the build unless every writer carries the
  furniture (reuses the `test_docx_family_xml_safe` WRITERS fan-out); `test_docmeta.py` gains
  coverage-honesty mutation tests. **DOCX are golden-free** (`test_pipeline_golden.py` renders only
  JSON + Excel) so no golden re-bless was needed.
- Also fixed a **latent `ssot.reconcile` crash** on a truthy non-dict `design_blueprint` (the
  `x or {}` idiom doesn't guard a non-dict) — surfaced by wiring the first `ssot.summary` caller.
- **Verified on the real AJ snapshot**: the register renders true canonical facts (253/303 collected,
  152 past-LDoS, 202 VLANs, 5127 endpoints, 39 decisions) + "14 figures self-verified".

## P1 — Client-facing depth (remaining; DOCX = golden-free, low risk)
- **crd.py — Inputs-Required register (marquee gap).** A CRD is made of `<placeholders>` (crd.py:209-217,
  261-268, 336-343) with no consolidated "Customer must provide/confirm" table. Add `add_inputs_required`
  (a docmeta helper to write) after the "How to use" note (~crd.py:183), fed by the unconfirmed
  `req_ids` (crd.py:149) + each `<...>` field, with Owner/Due columns.
- **mop.py — Executive Summary BLUF** between cover and §1 (~mop.py:266), fed by
  `executive_brief.top_gating` + `migration_scenarios.fleet_recommendation` + wave count. Plus an
  explicit rollback-trigger boolean under each §x.7 (mop.py:594), a per-window pre-implementation
  checklist (~mop.py:424), and a comms plan (~mop.py:311).
- **crd.py** — Constraints + Out-of-scope sections; theory-of-operation prose per requirement block.

## P2 — Remaining deliverables
- **archreview.py:1091** — replace the `len(devices)` recount on the cover with
  `ssot.canonical_facts(snap)['n_devices']`; add a named Availability/SPOF section.
- **engagement.py:538-547** — decision-log freshness via the `gate_record` param; add
  Alternatives/Rationale columns from `design_blueprint.decisions[*]`.
- **ops.py** — add Backup-&-Recovery (§4.x) + Known-Issues (from `snap['migration_punchlist']`) sections.
- **runbook.py** — already the strongest; just Inputs-Required.

## P3 — Non-DOCX surfaces (excel/deck/explorer — already strong; Law-2 provenance is the gap)
- **excel.py** — set `wb.properties` (CoreProperties: creator/created/keywords=version — **golden-safe**,
  metadata only) + a provenance block on the Exec-Summary sheet; a Read-Me tab-1 + Glossary tab
  (**these add sheets → one sheet-schema golden re-bless**, gated by `test_golden_guard.py`).
- **deck.py:184** — add version/date/snapshot to the title-slide footer (deck is golden-free). NOTE the
  `text()` run-format differs between single- and multi-line calls — check the helper before editing.
- **explorer** (`blast_radius_explorer.html`) — show `SNAP.script_version`/`generated_at` in the header
  (`#src`, ~2406); optionally default the side-panel to `briefCard()` as an answer-first landing.

## P4 — Independent verification (Law 10)
`/qa` is the standing proposer≠verifier pass each deliverable cycle; the in-doc `ssot` self-verified
badge (shipped in P0) is the machine signal. (The `deliverable-qa-reviewer` agent type may be
unavailable in some sessions; the `/qa` command + `.claude/agents/deliverable-qa-reviewer.md` remain.)

## Discipline
Ships as `feat:` PRs; pyproject bump only at release-tag time. Any NEW headline number surfaced in the
At-a-Glance register must be added to `ssot.CANONICAL_FACTS` + a `reconcile()` check (per
`docs/ssot-contract.md`), never computed inline.
