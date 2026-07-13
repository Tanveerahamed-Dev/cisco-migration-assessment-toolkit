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
- **`add_inputs_required(doc, snap)`** — consolidated "what's still needed" register (Law 9), not-collected
  devices as the load-bearing coverage-honest gap (commit `0ecda78`).
- **`add_document_control`** now emits a **Distribution list** (Law 2) for the whole family.
- **Net**: the universal orientation spine is COMPLETE — every DOCX deliverable carries At-a-Glance +
  Inputs-Required + Glossary + Document-Control(+Distribution) + acceptance + the SSOT self-verified badge.
- **Ratchet**: `tests/test_deliverable_excellence.py` fails the build unless every writer carries the
  furniture (reuses the `test_docx_family_xml_safe` WRITERS fan-out); `test_docmeta.py` gains
  coverage-honesty mutation tests. **DOCX are golden-free** (`test_pipeline_golden.py` renders only
  JSON + Excel) so no golden re-bless was needed.
- Also fixed a **latent `ssot.reconcile` crash** on a truthy non-dict `design_blueprint` (the
  `x or {}` idiom doesn't guard a non-dict) — surfaced by wiring the first `ssot.summary` caller.
- **Verified on the real AJ snapshot**: the register renders true canonical facts (253/303 collected,
  152 past-LDoS, 202 VLANs, 5127 endpoints, 39 decisions) + "14 figures self-verified".

## P1 — Client-facing depth
- ✅ **Inputs-Required register — SHIPPED as a UNIVERSAL helper** (commit `0ecda78`): `add_inputs_required`
  in docmeta, wired into all 7 writers' front matter, coverage-honest base rows from the snapshot
  (not-collected devices as the load-bearing gap). *Remaining refinement*: per-generator `extra_rows`
  (crd's unconfirmed `req_ids`/`<...>` fields, crd.py:149; mop's `<placeholder>` markers) so each doc's
  specific asks appear alongside the universal ones.
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

## P3 — Non-DOCX surfaces (excel/deck/explorer — already strong; Law-2 provenance CLOSED by P3-E3 / #346)

> **Status (P3-E4 refresh, 2026-07-12):** the visible Law-2 provenance gap is CLOSED — deck title-slide
> footer (`deck.py:185`) and the Exec-Summary document-control row (`excel.py:3832`) both carry engine
> `script_version` + generation timestamp, shipped as **P3-E3 (#346)**. The only remaining item below is
> the excel File>Info `wb.properties` metadata, still deferred for the flagship-save-path risk noted.
- **excel.py** — `wb.properties` (CoreProperties: creator/created/keywords=version — golden-safe metadata)
  is set at the orchestrator's `wb.save` (`COLLECT_PARSE_V3_23_0.py:2464`); **CAUTION**: that's the flagship
  save path — a stray undefined var there crashes every `cisco-assess` run, so trace the in-scope
  version/timestamp vars first (deferred for that reason — low value: File>Info metadata, and the
  visible coverage-honesty already lives in the "Collection Completeness" sheet). ✅ The **visible**
  provenance row **SHIPPED (P3-E3, #346)** — a document-control row on the Exec-Summary sheet
  (`excel.py:3832`) carrying `script_version` + `generated_at` (the writer gained the `provenance`
  signature + caller). A Read-Me tab-1 + Glossary tab add sheets → one sheet-schema re-bless.
- ✅ **deck.py:185 — SHIPPED (P3-E3, #346):** version/date/snapshot on the title-slide footer (deck is
  golden-free), following the explorer-ctx provenance pattern.
- **explorer** (`blast_radius_explorer.html`) — show `SNAP.script_version`/`generated_at` in the header
  (`#src`, ~2406); optionally default the side-panel to `briefCard()` as an answer-first landing.

## P4 — Independent verification (Law 10)
`/qa` is the standing proposer≠verifier pass each deliverable cycle; the in-doc `ssot` self-verified
badge (shipped in P0) is the machine signal. (The `deliverable-qa-reviewer` agent type may be
unavailable in some sessions; the `/qa` command + `.claude/agents/deliverable-qa-reviewer.md` remain.)

## P5 — Rendered-output fidelity (fed back from the 2026-07-06 HLD side-engagement)
Hand-authoring a 53-page client HLD surfaced two gaps in *rendered* fidelity that the text-first
pipeline and text-first QA both missed — folded back into the engine:
- ✅ **Field-code TOC now builds on open** — `docmeta.enable_update_fields` sets
  `<w:updateFields w:val="true"/>`, called from the shared `add_toc` so all 7 DOCX writers inherit it;
  ratcheted by `tests/test_docmeta.py::test_add_toc_marks_fields_to_rebuild_on_open`. Was: every
  deliverable shipped the literal placeholder *"Right-click → Update Field to build the table of
  contents"* (docmeta.py) — a client who opens-and-prints, or any headless docx→pdf render, got a
  deliverable with **no** table of contents. Now Word/LibreOffice rebuild the TOC (and all fields) on
  open. DOCX are golden-free, so no re-bless.
- ✅ **Raster is a QA blind spot — QA now renders and eyeballs the figures.** `deliverable-qa-reviewer`
  + `/qa` gained a render-to-page-images step: a diagram's title / node labels / event IDs live in the
  image, not the extractable text, so a figure can carry a stale or self-contradictory label while every
  grep-able string is correct (the session hit exactly this — out-of-order figure chips, a topology
  captioned for a superseded design, deep-dive titles with retired event IDs). Unrenderable in-env →
  report **UN-VERIFIED**, never a silent APPROVE (matches the "default to blocked" guardrail).
- ✅ **Deliverable-SET version-drift is now a QA finding.** The side-engagement folder was itself the
  evidence: an HLD reissued to v7.1 sitting on a companion LLD still at v6.0 (0 of the v7.1 markers, 15
  retired-architecture markers) — a whole family out of version-sync that no *single-document* QA pass
  flags. `deliverable-qa-reviewer` + `/qa` gained a step: reconcile the cover version / design baseline /
  snapshot across EVERY deliverable in the set; a sibling on an older baseline or rendering an
  architecture its own HLD has retired is a blocking finding; a family where only one document was
  regenerated must be called out, not approved. (The engine generates a set from one snapshot so it is
  version-consistent by construction — but a partial re-render, or a hand-authored set, drifts silently.)
- **Reusable verification recipe** (this Windows box lacks `pandoc`/`pdftoppm`/`zip`; console is cp1252):
  PyMuPDF (`pip install pymupdf`) for PDF→PNG; Word COM via `powershell.exe` (or `soffice`) for
  docx→pdf; Python `zipfile` (write `[Content_Types].xml` first) to package a hand-edited docx; assert an
  exact occurrence count before every XML string-replace and use `len("</w:tr>")` not a hand-counted
  offset; back up embedded media before PIL surgery; `PYTHONIOENCODING=utf-8` before printing `→`/`§`/`⇄`.
  Full lesson set with `bridge-candidate` tags: `docs/log.md` [2026-07-06].

## Discipline
Ships as `feat:` PRs; pyproject bump only at release-tag time. Any NEW headline number surfaced in the
At-a-Glance register must be added to `ssot.CANONICAL_FACTS` + a `reconcile()` check (per
`docs/ssot-contract.md`), never computed inline.
