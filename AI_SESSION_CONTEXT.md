# AI Session Context — Cisco Migration-Assessment Toolkit

> **Purpose of this file:** Load this document at the start of any new AI session to instantly inherit full project understanding, architectural decisions, verified findings, known problems, and improvement priorities. No re-analysis needed. All claims below are verified against the actual source code.

---

## 1. Project Identity

| Property | Value |
|---|---|
| **Name** | cisco-migration-assessment-toolkit |
| **Author** | Tanveerahamed-Dev (solo, Network Engineer, Doha QA) |
| **Language** | Python 3.10–3.14 (CI-tested, Linux + Windows) |
| **Scale** | ~65k LOC Python + 9,989-line single-file HTML explorer + ~7k LOC webapp |
| **Tests** | 1,150+ tests, golden byte-contract |
| **Velocity** | 474 commits in 28 days (single author) |
| **Last pushed** | 2026-07-21 (actively developed) |
| **Real fleet tested** | 303 devices / 253 collected / 64 MB snapshot |
| **Runtime deps** | Only 2: `netmiko`, `openpyxl` (wheel-relocatable) |
| **Entry point** | `COLLECT_PARSE_V3_23_0.py` → installed as `cisco-assess` CLI |

---

## 2. What This Project Does (One Paragraph)

An **offline, air-gapped, evidence-led, multi-vendor network migration assessment engine** plus a web cockpit. It SSH-collects `show` command output from Cisco IOS / IOS-XE / NX-OS devices (and REST-ingests ACI/APIC, vManage, ISE, FMC, Arista EOS, Juniper SRX, Fortinet FortiGate, AWS security groups), parses every relevant layer from L1→L4, runs ~41 `compute_*` analysis axes + 82 design-decision detectors + 11 proof engines, and fans the results out to 12 deliverables: a 62-sheet Excel workbook, a single-file interactive HTML "blast-radius explorer" (14 analysis modes), 7 DOCX documents (runbook, MOP, design doc, CRD, engagement plan, architecture review, ops handbook), a PPTX executive deck, a snapshot JSON, and diff/campaign workbooks.

Alongside the CLI sits **AssessHub** (`webapp/`) — a FastAPI + React full-stack platform for multi-campaign management, gated cutover planning, a war-room execution console, and an "Ask the Engineer" AI interface.

---

## 3. The Doctrine (Non-Negotiable Invariants)

These are the soul of the project. Any change that violates them is wrong regardless of how clean it looks:

1. **Read-only against devices.** Never sends a write command over SSH.
2. **No-egress runtime.** Zero external network calls at analysis time. Works fully offline/air-gapped.
3. **Coverage-honest abstention.** Absence of evidence is NEVER reported as health. `[NOT OBSERVED]` / `INDETERMINATE` / `lower_bound` are explicit, first-class states — not fallback defaults.
4. **Proposer ≠ verifier.** The engine that produces a finding is never the same engine that verifies it.
5. **Single source of truth (SSOT).** Every shared fact has exactly one owner in the snapshot dict. Renderers read; they do not recompute.
6. **Fail-open pipeline.** `_run_phase` guards ~109 phases. One bad axis never loses the workbook.

---

## 4. Repository Structure

```
cisco-migration-assessment-toolkit/
├── COLLECT_PARSE_V3_23_0.py     # CLI entry point (~216 KB, ~6k LOC) — orchestrator
├── cisco_toolkit/               # The core Python package (55+ modules)
│   ├── parse.py                 # Show-command parser — all platforms (~249 KB)
│   ├── analyze.py               # Analysis engine — 41 compute_* axes (~390 KB, 6090 LOC)
│   ├── excel.py                 # Excel workbook writer — 62 sheets (~235 KB)
│   ├── html.py                  # HTML explorer renderer (~75 KB)
│   ├── design_kb.py             # Static design knowledge base (~753 KB — LARGEST FILE)
│   ├── design_advisor.py        # Design advisor engine (~304 KB)
│   ├── runbook.py               # DOCX runbook generator (~70 KB)
│   ├── mop.py                   # Method of Procedure generator (~63 KB)
│   ├── archreview.py            # Architecture Review — 24 checks, 8 domains (~78 KB)
│   ├── scorecard.py             # Per-device health score 0–100 (~36 KB)
│   ├── fib.py                   # RIB→FIB path trace engine (~44 KB)
│   ├── aclcheck.py              # ACL shadow/conflict proof engine (~19 KB)
│   ├── causal.py                # Causal chain builder (SPOF trigger→impact→mitigation)
│   ├── blast_radius_explorer.html  # 9,989-line interactive single-file explorer
│   ├── mcp_server.py            # MCP (Model Context Protocol) server (~24 KB)
│   ├── ssot.py                  # Single-source-of-truth reconciliation engine
│   ├── capture_integrity.py     # Chain-of-custody hash manifest
│   ├── cmdio.py                 # SSH command I/O (netmiko wrapper)
│   ├── rest_collect.py          # REST ingestion — ACI, vManage, ISE, FMC
│   ├── external_import.py       # Arista / Juniper / Fortinet / AWS import
│   ├── eoldb.py                 # End-of-life/support database
│   ├── engagement.py            # Engagement Workflow & Plan of Record (~38 KB)
│   ├── deck.py                  # PowerPoint executive deck (~29 KB)
│   ├── crd.py                   # Customer Requirements Document (~37 KB)
│   ├── design.py                # As-Built HLD+LLD design document (~47 KB)
│   ├── ops.py                   # Operations Handbook (~42 KB)
│   ├── assertions.py            # State-correctness proof assertions
│   ├── attestation.py           # Chain-of-custody attestation
│   ├── calibration.py           # Score weight tuning
│   ├── cutover_sim.py           # Cutover simulation
│   ├── whatif.py                # What-if remediation simulator
│   ├── recall.py                # RAG retrieval
│   ├── retrieval_eval.py        # RAG evaluation harness
│   ├── evpn_migration.py        # EVPN/VXLAN migration module
│   └── data/                    # Offline KB data (OUI, port, EoL packs)
├── ollama_judge.py              # Offline LLM judge (root — should be in cisco_toolkit/ai/)
├── ollama_recall.py             # LLM recall (root — should be in cisco_toolkit/ai/)
├── ollama_retrieval_judge.py    # Retrieval judge (root — should be in cisco_toolkit/ai/)
├── embed_qbank.py               # Question bank embedder
├── questionnaire.json           # 240-question interview / 20 go/no-go gates
├── webapp/                      # AssessHub — FastAPI + React full-stack platform
├── tests/                       # 1,150+ tests + golden byte-contract
├── docs/                        # Documentation
├── portable/                    # Portable distribution
├── research_lane/               # Research artifacts
├── IMPROVEMENT_AND_GREENFIELD_PLANS.md  # Deep prior analysis (30-agent, Wave 1-3)
├── CHANGELOG.md
├── CLAUDE.md                    # Claude AI agent instructions
├── pyproject.toml
└── devices.example.json         # Example device inventory format
```

---

## 5. Data Flow (End-to-End)

```
[devices.json]
      ↓
[cmdio.py] ─── SSH via netmiko ──→ Cisco IOS/IOS-XE/NX-OS
[rest_collect.py] ── REST ──→ ACI / vManage / ISE / FMC
[external_import.py] ──→ Arista / Juniper / Fortinet / AWS
      ↓
[parse.py] — regex/heuristic parser for all show commands
      ↓
[analyze.py] — 41 compute_* axes (L1→L4, cross-layer, protocol, security)
      ↓
[scorecard.py] — per-device health score 0–100 + 10-check readiness verdict
      ↓
[snapshot dict] — ~85-key SSOT dict (~64 MB for 303 devices)
      ↓
  ┌──────────────────────────────────────────┐
  │ excel.py   → Migration_Assessment.xlsx   │
  │ html.py    → blast_radius_explorer.html  │
  │ runbook.py → runbook.docx                │
  │ mop.py     → mop.docx                   │
  │ design.py  → design.docx                │
  │ deck.py    → executive_deck.pptx         │
  │ crd.py     → crd.docx                   │
  │ engagement.py → engagement.docx          │
  │ archreview.py → archreview.docx          │
  │ ops.py     → ops_handbook.docx           │
  └──────────────────────────────────────────┘
```

---

## 6. Key Inputs & Outputs

### Inputs
- `--devices-file devices.json` — device inventory (ip, hostname, username, platform)
- `--template Migration_Assessment_Template_Updated.xlsx` — ⚠️ NOT included in repo (see Problem #5 below)
- `--golden-config FILE` — optional golden config for drift detection
- `--flow-src IP / --flow-dst IP` — optional flow trace endpoints

### Output Files (per run)
- `*_AUTOFILLED_<timestamp>.xlsx` — 62-tab workbook
- `*_explorer.html` — interactive network explorer (single file, offline)
- `*_snapshot.json` — the data contract / re-loadable state
- `*_runbook.docx`, `*_mop.docx`, `*_design.docx`, `*_archreview.docx`
- `*_crd.docx`, `*_engagement.docx`, `*_ops_handbook.docx`
- `*_executive_deck.pptx`

### Key CLI Flags
```bash
--workers N          # parallel SSH workers (default 5)
--compare old new    # diff two snapshots — no SSH, no template needed
--trend s1 s2 s3     # campaign trend across multiple snapshots
--redact             # pseudonymize IPs/MACs/serials in ALL deliverables
--redact-collection  # scrub secrets from the raw collection dir (opt-in)
--no-html / --no-docx / --no-pptx  # skip specific outputs
--output FILE        # override workbook filename
```

---

## 7. The Explorer — 14 Analysis Modes

The `blast_radius_explorer.html` is a 9,989-line, zero-dependency, offline single-file application. Modes:

1. **Blast Radius** — simulate device removal, see what gets stranded
2. **Path Trace** — L2/L3 path between two switches with articulation points
3. **Compare** — diff two snapshots (pre/post-cutover regressions)
4. **Flow** — L1→L3 flow trace with ACL / NAT / MTU / VRF awareness
5. **Health** — Risk cockpit: risk-by-tier matrix, keystone devices, Asset Risk Register, CR-pattern chips, punch-list triage
6. **Protocols** — routing-protocol topology, redistribution boundaries, adjacency health
7. **Cross-Layer** — findings that compound across layers into single migration risks
8. **Causality** — SPOF trigger → mechanism → impact → mitigation chains
9. **Waves** — migration move-groups with readiness verdict and cutover scenario
10. **Apps** — application domains with footprint, criticality, inter-domain coupling
11. **Review** — architecture review: A–F conformance grade, 24 leading-practice checks
12. **Design** — as-built design visualization
13. **Cable Map** — physical cable/interface mapping
14. **3D** — 3D topology visualization

---

## 8. Health Scoring

- Score: **0–100**, starts at 100 with weighted, per-category-capped deductions
- Bands: **Excellent / Good / Fair / Poor / Critical**
- Migration readiness: **10-check checklist per move group** → `READY / CAUTION / NOT READY`
- Hard-fail on any check → `NOT READY`; any warn → `CAUTION`
- ⚠️ Weights and thresholds are **defensible defaults, NOT calibrated against labeled data**

---

## 9. Verified Problems (from Prior 30-Agent Analysis + Current Analysis)

Ranked by severity. All verified against actual source code:

### 🔴 P1 — Format-Fidelity Bug Class (CORRECTNESS — CROWN JEWEL)
- **What:** An unseen platform variant silently parses to `[]`/`{}` — byte-identical to "feature absent" everywhere downstream. No zero-parse telemetry exists.
- **Evidence:** `parse.py` has the highest fix density (36 fixes / 83 touches); `cmdio.py:22-48` returns `''`/`{}` for absent ≡ error ≡ empty; once zeroed an entire real NX-OS RIB silently; recurred in 4+ audit waves.
- **Fix:** Zero-parse yield telemetry at the `cmdio` chokepoint — `(host, cmd, parser, lines_in, entities_out)` published as additive `snap['parse_yield']` + Collection-Completeness workbook row.

### 🔴 P2 — Security: Client Data Confidentiality Gap
- **What:** Zero-auth localhost API + `CORS *` + plaintext secrets at rest.
- **Evidence:** `app.py:136-139` has `allow_origins=['*']`, no authentication; `devices.json` can contain plaintext passwords; raw 416 MB collection dir with cleartext running configs is **never** touched by `--redact`.
- **Fix:** Optional bearer token (localhost dev unchanged); `sandbox="allow-scripts allow-downloads"` on explorer iframe (critically WITHOUT `allow-same-origin`); loudly warn + add `--redact-collection` for the raw dir.

### 🔴 P3 — Golden Auto-Bless Hole (TEST INTEGRITY)
- **What:** A *missing* golden silently regenerates and skips the test — re-baselining the contract without any red test.
- **Evidence:** `test_pipeline_golden.py:102-109` confirmed.
- **Fix:** Fail (not skip) when golden is missing and `UPDATE_GOLDEN` is unset; reject shrinking goldens via `git show HEAD:...` diff.

### 🟠 P4 — Wiring Tax: No Registries
- **What:** Adding a new analysis axis requires 3–4 hand-parallel edits; a new explorer mode requires 7; a new webapp tab requires 2 parallel lists. This exact gap made the "NOS quartet" features unreachable for months.
- **Evidence:** 40 hand-declared `all_*` accumulators in `COLLECT_PARSE:1661-1700` ↔ 33 hand-keyed `snap_dict[...]` at `:2413-2446`.
- **Fix:** `AxisSpec` registry following the `_DETECTORS` precedent already in the repo; derive webapp section labels from it.

### 🟠 P5 — Excel Template Not Shipped
- **What:** `Migration_Assessment_Template_Updated.xlsx` is a required `--template` input that is NOT in the repo. New users cannot run the tool without it.
- **Fix:** Generate the template programmatically via `openpyxl` so zero-configuration works, OR ship a minimal starter template as package data.

### 🟠 P6 — God-Functions / File Size
- **What:** `main()` is ~1,375 lines; `_signals()` is ~1,200 lines; `analyze.py` is 6,090 lines; the explorer is 9,989 lines. Only 1 refactor commit in 474.
- **Fix:** Strangler decomposition of `main()` into ~5 stages. Use typed `AnalysisContext`. Do NOT rewrite — evolve with golden contract as safety net.

### 🟠 P7 — Superlinear Performance: `compute_failure_impact`
- **What:** Measured **23.16 seconds** on the real 303-device AJ fleet — O(H×V×link-scan) with an uncached per-call VLAN-range `re.split`. Projects to tens of minutes at ~1000 devices.
- **Evidence:** `analyze.py:885-926`, `:595`.
- **Fix:** `lru_cache` the range parse + per-VLAN precompute + articulation-point pruning. Ship as parallel impl behind a differential test vs. old function on golden.

### 🟠 P8 — Zero JS Tests on the 9,989-line Explorer
- **What:** The HTML explorer has 0 executed JS tests. It contains 3 hand-maintained JS ports of Python engines. Only `fib` has a regex-presence guard — not a behavioral test.
- **Fix:** Commit the existing 622-pair `fib` harness; add `node --test` execution; extend to `causalFlows` + `cableMap`.

### 🟡 P9 — Snapshot Bloat
- **What:** 64 MB snapshot, `indent=2`, interfaces subtree = 29.7 MB (46% of total), 74% empty fields fleet-wide.
- **Fix (Phase 1):** Drop `indent=2` — provably free (all consumers compare parsed objects). **Phase 2:** Sparse-encode the interfaces subtree. Optional Phase 3: `gzip` sidecar.

### 🟡 P10 — Dead / Half-Wired Engines
- **What:** ~~`manifest.verify_chain` has no production consumer~~ (**CLOSED 2026-07-22**); `external_import` IP_DRIFT is dead (reads a key `analyze.py` never emits); `capture_integrity` only checks running-config.
- **Fix:** ~~Wire `manifest.verify_chain` into the pipeline~~ — **rejected, and deliberately not done.** A run that verifies the manifest it just wrote only proves the bytes survived a write→read round trip; the seal exists for the RECEIVER, who is a different party at a later time. Closed instead by shipping the check to them: `python -m cisco_toolkit.manifest verify <path>` / `Atlas.exe --verify-manifest` (exit 4 on a broken chain, `--expect-root` / `--artifacts`), proven against the real pipeline's manifest in `tests/test_pipeline_golden.py`. Still open: fix the dead `IP_DRIFT` key reference; widen `capture_integrity` to all ~160 collected commands.

### 🟡 P11 — Ollama/LLM Layer Is Not Integrated
- **What:** `ollama_judge.py`, `ollama_recall.py`, `ollama_retrieval_judge.py` live at the repo root, outside the `cisco_toolkit` package. They are experiments, not features.
- **Fix:** Move to `cisco_toolkit/ai/` subpackage; define a clean `LLMJudge` interface; make swappable (Ollama locally, cloud API optionally).

### 🟡 P12 — MCP Server Undocumented
- **What:** `cisco_toolkit/mcp_server.py` (24 KB) exists but has zero documentation. Enormous potential for AI-driven assessments.
- **Fix:** Add `MCP_SERVER.md`; register as `cisco-assess-mcp` entry point in `pyproject.toml`; consider read-only stdio transport (stronger than HTTP, zero-egress by construction).

### 🟡 P13 — KB / EoL Data Staleness
- **What:** `eoldb.py` has 10 "active" rows with no dates; OUI generator script doesn't exist (registry pack frozen); no provenance headers in KB packs.
- **Fix:** Add provenance/date headers; write `gen_oui_registry.py`; add a staleness-check CI step.

### 🟡 P14 — Product Surface Froze
- **What:** README says "8 modes / Cisco-only" (reality: 14 modes, multi-vendor, 11 proof engines). 0 release tags in ~220 commits. Demo sample has 33 keys (reality: 85). No Dockerfile.
- **Fix:** Regenerate sample fleet via `build_sample.py`; update README; resume tagging (`v3.24.0`); add a docs-parity test.

---

## 10. What Is Already Excellent (Do Not Regress)

- **Coverage-honesty** wired into both engines AND renderers — abstention is an explicit state everywhere
- **Fail-open pipeline** — 109 `_run_phase` guards; one bad axis never loses the workbook
- **Golden byte-contract** — per-section snapshot + sheet-schema frozen; `UPDATE_GOLDEN=1` escape hatch; real behavior-preservation oracle
- **Proof-based verify engines** with explicit abstention: `aclcheck` 5-D box-algebra shadow proofs, `fib` RIB→FIB longest-prefix multi-hop with `reach > lower_bound > drop` ranking, `ssot.reconcile` against independent bases, `manifest` sha256 hash-chain custody
- **Doctrine-as-tests** — read-only/no-egress enforced by AST-walking the import graph
- **307-principle design KB** with 0 orphan citations — decision → principle → citation → evidence traceability
- **`--redact`** — consistent, subnet-preserving pseudonymization across ALL deliverables
- **Air-gap first** — single-file HTML explorer, zero external dependencies
- **`--compare` and `--trend`** — snapshot diff and campaign-across-time are standout capabilities
- **Blast-radius simulation** — genuinely pre-migration useful, click-a-device failure simulation
- **Wheel-relocatable packaging** — HTML template and offline KB ship inside the package as package-data

---

## 11. Prioritized Improvement Roadmap

### Move-0 (Do Before Anything Else)
1. Close the golden auto-bless hole (`test_pipeline_golden.py:102-109`) — fail loud on missing goldens, reject shrinkage
2. Add `webapp/tests` to `pytest.ini` testpaths; add `COLLECT_PARSE_V3_23_0` to coverage source

### Tier 1 — Now (Correctness + Security, ~1 week)
3. Zero-parse yield telemetry at `cmdio` chokepoint → additive `snap['parse_yield']` + workbook row
4. Kill `CORS *`; add optional bearer token; sandbox explorer iframe (WITHOUT `allow-same-origin`)
5. `--redact-collection` + loud `[SENSITIVE]` warning for raw collection dir

### Tier 2 — Next (~2–4 weeks)
6. Widen `capture_integrity` from run-config-only to all ~160 collected commands
7. Commit 622-pair JS `fib` harness + execute under `node --test`; extend to `causalFlows` + `cableMap`
8. `AxisSpec` registry in `COLLECT_PARSE` (following `_DETECTORS` precedent); derive webapp sections from it
9. MODES registry in the explorer (one table → all 14 modes + keyboard shortcuts)
10. Product/adoption pass: regenerate sample fleet; rewrite README; resume tagging `v3.24.0`; add `LICENSE` file

### Tier 3 — Later (Real Value, No Fire)
11. Measure-first perf harness (`perf_counter` in `_run_phase` sidecar JSON) → then restructure `compute_failure_impact`
12. Snapshot size: drop `indent=2` (provably free) → sparse-encode interfaces subtree
13. Move `ollama_*.py` → `cisco_toolkit/ai/`; define `LLMJudge` interface; make model-swappable
14. Generate starter Excel template programmatically so zero-config works
15. Document and register `mcp_server.py` as `cisco-assess-mcp` entry point
16. Typed `AnalysisContext` + strangler decomposition of `main()` into ~5 stages
17. Add EVPN/VXLAN readiness as a first-class analysis pillar (dedicated Excel sheets + Explorer mode)
18. `PARSER_CONTRACTS` registry — typed default per parser, fixing the `{}`-vs-`[]` hazard at 94 sites

---

## 12. TRAP-AVOID (Do NOT Do)

- ❌ **Any from-scratch rewrite** — 65k LOC / 1,150 tests is not fungible volume; it encodes 4 adversarial audit waves of platform truth
- ❌ **Making ntc-templates/TextFSM the default parse lane** — use it only as an independent CI referee
- ❌ **Mass table-driven rewrite of `excel.py` sheet writers up front** — risks the client deliverable for cosmetic tidiness
- ❌ **DuckDB** — its extension autoloader defaults to fetching from `extensions.duckdb.org`, a live egress vector against the no-egress moat
- ❌ **SQLite → PostgreSQL migration before abstracting the storage interface** — abstract first, then swap

---

## 13. AssessHub (webapp/) Summary

| Aspect | Detail |
|---|---|
| **Stack** | FastAPI (backend) + React (frontend) + SQLite (storage) |
| **Auth** | ⚠️ Currently zero-auth, `CORS *` (P2 above) |
| **Capabilities** | Campaign management, multi-snapshot tracking, trajectory verdicts, force-directed topology, gated cutover planner, war-room execution console, on-demand deliverables |
| **Two ingestion paths** | Upload `*.snapshot.json` OR upload ZIP of raw show outputs (runs real engine server-side) |
| **AI interface** | "Ask the Engineer" — A–F conformance grade, deterministic question chips, per-domain drill-down |
| **Scale limit** | SQLite — fine for solo/small team; will hit limits at enterprise scale (100s of snapshots, concurrent users) |
| **Tests** | 59 tests — excluded from default pytest suite (fix: add to `pytest.ini`) |

---

## 14. AI Integration Points

| Module | Location | Status | Purpose |
|---|---|---|---|
| `mcp_server.py` | `cisco_toolkit/` | Exists, undocumented | MCP server exposing toolkit as AI-callable tools |
| `ollama_judge.py` | Repo root | Unintegrated experiment | LLM-based assessment evaluation |
| `ollama_recall.py` | Repo root | Unintegrated experiment | Semantic recall over assessment data |
| `ollama_retrieval_judge.py` | Repo root | Unintegrated experiment | RAG quality judgment |
| `design_kb.py` | `cisco_toolkit/` | Integrated | 307-principle static KB powering design advisor |
| `recall.py` | `cisco_toolkit/` | Integrated | RAG retrieval engine |
| `retrieval_eval.py` | `cisco_toolkit/` | Integrated | RAG evaluation harness |
| `embed_qbank.py` | Repo root | Utility | Embeds `questionnaire.json` for semantic search |
| `questionnaire.json` | Repo root | Integrated | 240-question interview, 20 go/no-go gates |

**Recommendation for AI sessions:** The `mcp_server.py` is the cleanest AI integration point. Load `AI_SESSION_CONTEXT.md` (this file) + `IMPROVEMENT_AND_GREENFIELD_PLANS.md` + `CLAUDE.md` for full context before any code change.

---

## 15. Cross-Repo Lineage

This project evolved from earlier repos (also private, same author):

| Repo | Status | Relationship |
|---|---|---|
| `CiscoMigrationCollector` | Archived (v1) | Original proof-of-concept |
| `CiscoMigrationCollectorenhanced` | Archived (v2) | Enhanced version |
| `CiscoMigrationExtractor` | Archived (v3 pre-package) | Pre-package extraction experiment |
| `cisco-migration-assessment-toolkit` | **Active (v3.23+)** | Current production codebase |
| `claude-memory-enhancements` | Separate | AI memory tooling experiment |

All Cisco migration learning from prior repos has been folded into the current toolkit.

---

## 16. Quick-Reference: Files an AI Session Should Read First

For any meaningful code change, read these files in order:

1. **`AI_SESSION_CONTEXT.md`** (this file) — full orientation
2. **`IMPROVEMENT_AND_GREENFIELD_PLANS.md`** — prior deep analysis (30-agent, Wave 1–3), verified claims
3. **`CLAUDE.md`** — agent-specific instructions and workflow rules
4. **`COLLECT_PARSE_V3_23_0.py`** — the CLI orchestrator and pipeline
5. **`cisco_toolkit/parse.py`** — the parser (touch with extreme care)
6. **`cisco_toolkit/analyze.py`** — the analysis engine
7. **`tests/`** — golden contract; run `UPDATE_GOLDEN=0 pytest` before and after any change

---

## 17. Session Handoff Protocol

When starting a new AI session on this project:

1. Load this file (`AI_SESSION_CONTEXT.md`) — gives you full project understanding
2. Check `CHANGELOG.md` for changes since this file was last updated
3. Run `git log --oneline -20` to see the 20 most recent commits
4. Ask the user: "Which problem (P1–P14) or improvement tier do you want to work on?"
5. Before writing any code: confirm the golden test passes (`pytest tests/` with no `UPDATE_GOLDEN`)
6. After writing code: confirm the golden still passes; if a golden changes, explain why and get explicit approval before `UPDATE_GOLDEN=1`

---

*This document was produced by Perplexity AI (Sonnet 4.6) on 2026-07-21 via full repository analysis including README, directory structure, all module names/sizes, prior IMPROVEMENT_AND_GREENFIELD_PLANS.md analysis, and cross-repo lineage. It supersedes ad-hoc re-analysis — load it to skip the analysis phase.*
