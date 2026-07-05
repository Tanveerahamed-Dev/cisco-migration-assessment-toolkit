# Project Single Source of Truth — the registry

**One index, many owners.** This is the project-wide map of *where the truth for any fact lives*.
It does **not** copy the data — it points to the one authoritative owner of each domain and states
the rule: **reference, never restate.** A number that appears in two places without a reconcile
guard is a latent drift bug (this is Law 1 of the Deliverable Excellence Standard, and the
"correspondence rules" of ISO/IEC/IEEE 42010 applied at project scale).

> Why not one mega-file? Because these domains have different update cadences (code = every commit;
> assessment facts = every collection; memory = every session; version = every release), formats
> (AST graph vs JSON vs markdown vs TOML), and producers. Consolidating the *storage* would drift
> the instant any owner updates. So we consolidate the **index** (this file) and federate the
> **storage** (the owners below), with a mechanical guard on the facts that legitimately live in
> two homes.

## The map — for any fact, read it from its one owner

| Domain of truth | Authoritative owner | How to read it (never re-derive) | Enforcement |
|---|---|---|---|
| **Assessment headline facts** — device/collected/endpoint/VLAN counts, health posture, lifecycle bands, #design-decisions | `cisco_toolkit/ssot.py :: CANONICAL_FACTS` → published at `executive_brief.scale/posture`, `lifecycle_risk.summary`, `design_blueprint.summary` | `ssot.canonical_facts(snap)` | ✅ **CI-enforced** — `ssot.reconcile()` + cross-surface/dashboard/webapp locks. Detail contract: [`docs/ssot-contract.md`](ssot-contract.md) |
| **Coverage census** (J3) — per-section coverage map: what the snapshot actually SAW vs a blind spot (SuzieQ `describe` analog) | `cisco_toolkit/ssot.py :: compute_schema_census` → published at `snap['schema_census']` (`schema_census/1`) | `ssot.compute_schema_census(snap)`; each section's `state` reuses `ssot.abstention_reason` | derives from `abstention_reason` (the 3-state token owner); non-volatile (presence/absence + shape) → frozen in `tests/golden/snapshot.json`; logic pinned by `tests/test_schema_census.py` |
| **Fact lineage** (J2) — attribute-level provenance for the headline facts: WHERE each canonical number comes from (path + basis + coverage state) | `cisco_toolkit/ssot.py :: compute_fact_lineage` → published at `snap['fact_lineage']` (`fact_lineage/1`) | `ssot.compute_fact_lineage(snap)`; one row per `CANONICAL_FACTS` entry, `value` read via `ssot.canonical_facts` | reuses the `CANONICAL_FACTS` contract + `abstention_reason` (no parallel store); date-relative values → golden-excluded, logic pinned by `tests/test_fact_lineage.py` |
| **Raw assessed evidence** — the ~60 analysis blocks (routes, acls, endpoints, health_scores, architecture_coverage, cable_map, move_groups, device_dossiers, …) | the snapshot JSON (`*_AUTOFILLED_*.snapshot.json`; current: `Migration_Assessment_AUTOFILLED_20260613_063201.snapshot.json`) | `snap['<block>']`; re-analyze offline with `--no-collect --collection-dir` | producer = the engine (`COLLECT_PARSE_V3_23_0`) |
| **Code + docs structure** | graphify (`graphify-out/graph.json`) | `python -m graphify query \| explain \| affected \| path` | Stop-hook re-extract; `built_at_commit` tracks HEAD |
| **Design decisions** (→ HLD/LLD/CRD/deck) | `snap['design_blueprint'].decisions` | read the block; **count via fact #1, never restate it** | decision **count** reconciled; bodies producer-owned |
| **Architecture coverage** (29-class detector map) | `snap['architecture_coverage']` | read the block | webapp SSOT lock |
| **Per-detector descriptors** — what each analysis detector checks, its healthy value/threshold, the snapshot fields it reads, and the coverage-honest `abstains_when` guard ("not-observed != healthy" as a schema property) | `cisco_toolkit/detector_schema.py :: compute_detector_schema` → published at `snap['detector_schema']` (+ the 'Detector Schema' workbook sheet) | read the block; it DESCRIBES detection, never re-runs it | `tests/test_detector_schema.py` (every evidence-gated detector has a non-empty `abstains_when`; cited_fields are real dotted snapshot keys) |
| **Project decisions / state / lessons / how-to-work** | cross-session memory — `.claude/.../memory/*.md` + `MEMORY.md` index | read `MEMORY.md` (one-line hooks) → topic files | ⚠️ **hand-maintained — the one un-mechanized owner** |
| **Operating doctrine / PPDIOO gates / guardrails / entrypoints** | `CLAUDE.md` | read it | convention |
| **Release version** | `pyproject.toml :: version` (currently 3.26.0) — bump at **tag time only** | — | partial |
| **Schema version** | `cisco_toolkit.__version__` (currently 3.23.0) — **decoupled from release by design** | — | intentional decouple (do **not** reconcile equal to release) |
| **Release history / what shipped** | `CHANGELOG.md` | read it | convention |
| **Run provenance / chain-of-custody** | `cisco_toolkit/manifest.py` (append-only, hash-chained ledger) | the sealed run-manifest | tamper-evident by hash chain |
| **Deliverable quality bar + reusable prompts** | `…\Desktop\_Deliverable_Excellence_Kit\` (Standard + Master Prompt Library) | read the kit | the verify-gate ratchet on generated docs |
| **Generated-deliverable excellence** (furniture every docx carries) | `cisco_toolkit/docmeta.py :: add_excellence_front / add_glossary / add_document_control` + plan `docs/deliverable-excellence-plan.md` | the 7 writers call them; read the plan | ✅ **CI-enforced** — `tests/test_deliverable_excellence.py` fails the build if any deliverable lacks the At-a-Glance / Glossary / Document-Control / acceptance furniture |
| **Brand design tokens** — print navy + severity (deck/DOCX/workbook) · digital dark/light palette (explorer/webapp) | print → `cisco_toolkit/brand_tokens.py :: BRAND_NAVY_RGB` (canonical `#1F3864`); digital → `cisco_toolkit/blast_radius_explorer.html` `:root` | import the token — never hardcode a hex / `RGBColor` | ✅ **CI-enforced** — `tests/test_brand_tokens_reconcile.py` (zero stray print-navy literal) + `tests/test_theme_tokens_reconcile.py` (theme.css must not drift from the explorer; 33 shared tokens) |
| **Side engagements** (separate SSOTs, *not* this repo) | Qatar DC: `syntys/ssot.py` → `Syntys_DC_Design\` · QAG CCTV bid: `…\QAG_Alwaj_CCTV_PS_Proposal\` | their own pipelines | own verify gates |

> **Snapshot-vintage note (coverage-honest):** the three newest evidence blocks — `cable_map`,
> `architecture_coverage`, `coverage_matrix` — are published by the *current* engine
> (`COLLECT_PARSE_V3_23_0.py:2485/2624/2629`) but are **absent from the on-disk 20260613 snapshot**,
> which predates them. Regenerate the snapshot to populate them; the owner paths above are the
> contract regardless of that file's vintage.

## Facts that live in two homes — which one wins

| Fact | Authoritative owner | Legitimate copy (a *cache*) | Rule |
|---|---|---|---|
| Fleet counts (303 inventoried / 253 collected / 50 not) | `ssot.canonical_facts(snap)` | memory `canonical-aj-fleet.md` | Snapshot wins. Memory is a human-readable cache — regenerate it *from* the snapshot; never edit the number in memory alone. (They agree today.) |
| Release vs schema version | `pyproject.toml` vs `__version__` | — | **Not the same fact.** Decoupled on purpose; do not force-equal. |
| Any headline number rendered in a deliverable | fact #1 (`canonical_facts`) | the rendered DOCX/XLSX/HTML/PPTX | Already mechanically reconciled by the cross-surface lock. |
| Digital design tokens (dark/light palette) | `blast_radius_explorer.html` `:root` | `webapp/frontend/src/theme.css` (mirror; cites it, line 1) | Explorer wins. Guarded by `test_theme_tokens_reconcile.py` — the 33 shared tokens must match. |

## The federation rule (how to keep it consolidated)

1. **Reference, don't restate.** If a fact has an owner above, READ it from the owner; don't hardcode a copy.
2. **A copy is a cache and must be labelled.** If you must cache a fact for offline/human convenience
   (memory, an executive summary), cite the owner path so a reader knows where to reconcile.
3. **Two computations of one fact = a bug.** The second one is where drift will appear. Delete it, or
   guard it with a reconcile check.

## Adding a new source of truth (the ratchet)

1. **Register the domain here** — name the one owner path and how to read it.
2. **If it overlaps an existing fact**, add a `check(...)` to `ssot.reconcile` (for assessment facts)
   or the relevant guard, so the overlap can't drift.
3. **Never introduce a second computation** of a fact that already has an owner.
4. A review finding that a fact lived in two un-reconciled places → add the guard *permanently*. The
   registry's floor only rises.

---
*This registry is itself a deliverable: answer-first, complete, and coverage-honest (it names its
own weakest link — memory is the one hand-maintained owner). Governed by the Deliverable Excellence
Standard, Law 1.*
