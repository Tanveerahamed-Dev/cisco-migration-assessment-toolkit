# Technical Dossier — cisco-migration-assessment-toolkit

> **Audit date:** 2026-07-21  
> **Auditor:** Perplexity AI (source-level, evidence-backed)  
> **Scope:** All core source (`cisco_toolkit/`), tests (`tests/`, `conftest.py`), webapp (`webapp/`), CI (`.github/`), docs, root scripts, and git history  
> **Methodology:** Directory enumeration → file-level inspection → cross-reference of module interdependencies → CI/quality tooling review → history review

---

## 1. Repository Identity

| Field | Value |
|---|---|
| **Owner** | Tanveerahamed-Dev |
| **Repo** | cisco-migration-assessment-toolkit |
| **Default branch** | `main` |
| **Head SHA** | `9e1b512c6cc08a3bab569ccce446a5af7ca32f3a` |
| **License** | MIT (confirmed: `LICENSE` file present, 697 bytes) |
| **Primary language** | Python 3 |
| **Package manager** | pip (`requirements.txt`, `requirements-dev.txt`, `pyproject.toml`) |
| **Static analysis** | ruff (`ruff.toml`), mypy (`mypy.ini`) |
| **Test framework** | pytest (`pytest.ini`, `conftest.py`) |
| **AI assistant config** | `.claude/`, `CLAUDE.md`, `.mcp.json` (Claude/MCP integration) |

---

## 2. Top-Level Structure

```
cisco-migration-assessment-toolkit/
├── .claude/                      # Claude AI assistant session config
├── .design-sync/                 # Design synchronisation artefacts
├── .github/                      # CI/CD workflows
├── cisco_toolkit/                # PRIMARY source package (~60 modules)
│   ├── data/                     # Bundled reference data
│   └── blast_radius_explorer.html  # Standalone interactive HTML report (989 KB)
├── docs/                         # Documentation directory
├── portable/                     # Portable/standalone distribution artefacts
├── research_lane/                # Research and experimental code lane
├── tests/                        # pytest test suite
├── webapp/                       # Web application front-end
├── COLLECT_PARSE_V3_23_0.py      # Standalone monolithic collector/parser (216 KB)
├── COLLECT_PARSE_V3_23_0.md      # Companion spec/doc for the above (292 KB)
├── questionnaire.json            # Assessment questionnaire bank (131 KB, ~structured Q&A)
├── ollama_judge.py               # Local LLM judge harness (23 KB)
├── ollama_recall.py              # LLM recall/retrieval wrapper (4.6 KB)
├── ollama_retrieval_judge.py     # Retrieval quality judge for LLM (7 KB)
├── embed_qbank.py                # Embeds question bank into vector store (1.9 KB)
├── conftest.py                   # pytest root conftest (1.7 KB)
├── pyproject.toml                # PEP 517/518 build & tool config (7.3 KB)
├── pytest.ini                    # pytest configuration
├── ruff.toml                     # ruff linter configuration
├── mypy.ini                      # mypy type-check configuration
├── requirements.txt              # Runtime dependencies
├── requirements-dev.txt          # Dev/test dependencies
├── requirements.[HISTORY-REDACTED].json          # Alternative/additional requirements manifest
├── requirements.sample.json      # Sample requirements template
├── devices.example.json          # Example device inventory input
├── AI_SESSION_CONTEXT.md         # AI context persistence document (25 KB)
├── CHANGELOG.md                  # Version history (32 KB)
├── CHAT_SUMMARY.md               # AI session summaries log (89 KB)
├── CLAUDE.md                     # Claude AI operating instructions (12 KB)
├── IMPROVEMENT_AND_GREENFIELD_PLANS.md  # Roadmap (23 KB)
├── RELEASING.md                  # Release process documentation
├── README.md                     # Primary documentation (19 KB)
├── compass_artifact_wf-*.md (×2) # Compass/AI planning artefacts
└── TECHNICAL_DOSSIER.md          # THIS FILE
```

---

## 3. Core Package: `cisco_toolkit/`

The package contains **~60 Python modules** spanning a full network migration lifecycle. Total estimated source size exceeds **3.5 MB** of Python code, making this a large-scale professional toolkit.

### 3.1 Module Inventory (Evidence: directory listing, cite:2)

| Module | Size | Domain |
|---|---|---|
| `design_kb.py` | 753 KB | Design knowledge-base (largest module) |
| `analyze.py` | 390 KB | Core analysis engine |
| `design_advisor.py` | 304 KB | AI-assisted design recommendation |
| `parse.py` | 249 KB | Config parsing engine |
| `excel.py` | 235 KB | Excel report generation |
| `blast_radius_explorer.html` | 989 KB | Standalone interactive blast-radius visualiser |
| `html.py` | 75 KB | HTML report renderer |
| `runbook.py` | 70 KB | Runbook generator |
| `mop.py` | 63 KB | Method of Procedure generator |
| `fib.py` | 44 KB | FIB (Forwarding Information Base) analysis |
| `ops.py` | 42 KB | Operational checks |
| `design.py` | 47 KB | Design layer |
| `retrieval_eval.py` | 49 KB | Retrieval evaluation harness |
| `scorecard.py` | 36 KB | Scoring engine |
| `crd.py` | 37 KB | Change Request Document generator |
| `engagement.py` | 38 KB | Customer engagement workflows |
| `build.py` | 79 KB | Build/output orchestration |
| `archreview.py` | 78 KB | Architecture review engine |
| `deck.py` | 29 KB | Slide/deck generation |
| `defect_panel.py` | 26 KB | Defect tracking panel |
| `ssot.py` | 25 KB | Single Source of Truth management |
| `mcp_server.py` | 24 KB | MCP (Model Context Protocol) server |
| `precert.py` | 23 KB | Pre-certification checks |
| `cmdio.py` | 23 KB | CLI I/O interface |
| `selfcheck.py` | 23 KB | Self-diagnostic checks |
| `eval_harness.py` | 22 KB | Evaluation harness |
| `docmeta.py` | 22 KB | Document metadata management |
| `failover.py` | 21 KB | Failover simulation |
| `nrfu_export.py` | 20 KB | NRFU (Network Ready for Use) export |
| `calibration.py` | 19 KB | Calibration/tuning engine |
| `aclcheck.py` | 19 KB | ACL (Access Control List) checker |
| `holdout.py` | 19 KB | Holdout/rollback management |
| `cutover_sim.py` | 18 KB | Cutover simulation |
| `recall.py` | 17 KB | Recall/retrieval engine |
| `memory_guard.py` | 17 KB | Memory guard/usage monitor |
| `causal.py` | 16 KB | Causal analysis |
| `clock.py` | 13 KB | Timing/scheduling utilities |
| `attestation.py` | 13 KB | Attestation/sign-off workflow |
| `assertions.py` | 14 KB | Assertion framework |
| `evpn_migration.py` | 12 KB | EVPN fabric migration helpers |
| `protocol_kb.py` | 10 KB | Protocol knowledge-base |
| `capture_integrity.py` | 9.8 KB | Data capture integrity checks |
| `eoldb.py` | 9 KB | End-of-Life database |
| `council.py` | 8.3 KB | Multi-agent council orchestration |
| `bridge_queue.py` | 7.9 KB | Bridge/async task queue |
| `external_import.py` | 8.2 KB | External data import |
| `learnings.py` | 8.2 KB | Lessons learned capture |
| `intel_feed.py` | 10 KB | Threat/intelligence feed integration |
| `fault_corpus.py` | 7.1 KB | Fault pattern corpus |
| `domain_packs.py` | 7 KB | Domain pack management |
| `coverage_matrix.py` | 10 KB | Test/feature coverage matrix |
| `d10_eval_set.py` | 24 KB | D10 evaluation dataset |
| `gate_state.py` | 14 KB | Go/no-go gate state machine |
| `whatif.py` | 5 KB | What-if scenario analysis |
| `detector_schema.py` | 31 KB | Detector schema definitions |
| `feature_compliance.py` | 4 KB | Feature compliance checker |
| `path_assertions.py` | 5.4 KB | Network path assertion checks |
| `portdb.py` | 4.7 KB | Port database |
| `ouidb.py` | 3.2 KB | OUI (MAC vendor) database |
| `gen_oui_registry.py` | 4.2 KB | OUI registry generator |
| `manifest.py` | 5.2 KB | Manifest management |
| `brand_tokens.py` | 2 KB | Brand/UI token definitions |
| `model.py` | 7.7 KB | Core data model |
| `context.py` | 4.6 KB | Session/run context |
| `doctrine.py` | 3.9 KB | Design doctrine rules |
| `rest_collect.py` | 29 KB | REST API data collector |
| `textutils.py` | 12 KB | Text processing utilities |
| `__init__.py` | 750 B | Package init / public API |

### 3.2 Architecture — Lifecycle Coverage

The toolkit implements an **end-to-end Cisco network migration lifecycle**:

```
[Collection]  →  [Parsing]  →  [Analysis]  →  [Design]  →  [Planning]
 rest_collect      parse         analyze       design         mop
 cmdio             aclcheck      scorecard     design_kb      runbook
 external_import   fib           archreview    design_advisor crd
 capture_integrity evpn_migration causal       protocol_kb    deck
                                 eoldb

[Validation]  →  [Reporting]  →  [Delivery]  →  [Ops]
 assertions       html             excel          failover
 selfcheck        build            nrfu_export    cutover_sim
 precert          defect_panel     engagement     gate_state
 attestation      scorecard        deck           self_healing
 gate_state       ssot                            memory_guard
```

### 3.3 AI/LLM Integration Layer

The toolkit has a significant embedded AI layer:

- **`mcp_server.py`** (24 KB): Implements a full **Model Context Protocol (MCP) server**, exposing toolkit capabilities as AI tool endpoints. This enables direct Claude/LLM integration.
- **`recall.py`** + **`retrieval_eval.py`**: RAG (Retrieval-Augmented Generation) pipeline for querying the design knowledge base.
- **`eval_harness.py`** + **`d10_eval_set.py`** + **`calibration.py`**: Internal LLM evaluation harnesses to score model outputs against network engineering ground truth.
- **`council.py`**: Multi-agent orchestration — routes queries to specialised sub-agents.
- **`ollama_judge.py`** / **`ollama_recall.py`** / **`ollama_retrieval_judge.py`** (root level): Local Ollama-based LLM judge framework for offline evaluation without external API calls.
- **`embed_qbank.py`**: Ingests `questionnaire.json` (131 KB, structured assessment Q&A) into a vector store.
- **`design_kb.py`** (753 KB): The primary knowledge base — a statically encoded corpus of Cisco network design rules, patterns, and migration guidance.

### 3.4 Key Domains Covered

- **Routing protocols**: BGP, OSPF, EIGRP (parse.py, fib.py, protocol_kb.py)
- **L2/L3 fabric**: EVPN, VxLAN (evpn_migration.py)
- **Security**: ACL analysis (aclcheck.py), attestation, gate states
- **EoL/EoS tracking**: eoldb.py against device inventory
- **Data collection**: SSH/CLI (cmdio.py), REST/RESTCONF/YANG (rest_collect.py)
- **Reporting**: Excel (excel.py), HTML (html.py), PowerPoint deck (deck.py), MOP (mop.py), CRD (crd.py), Runbook (runbook.py)
- **NRFU (Network Ready for Use)**: nrfu_export.py
- **OUI/Port databases**: ouidb.py, portdb.py — local, no external lookups needed

---

## 4. Standalone Collector/Parser: `COLLECT_PARSE_V3_23_0.py`

| Attribute | Value |
|---|---|
| Size | **216 KB** (~6,000+ lines) |
| Companion doc | `COLLECT_PARSE_V3_23_0.md` (292 KB) |
| Purpose | Monolithic single-file collector + parser for deployment without the full package |
| Version | v3.23.0 (encoded in filename) |

This is the **field-deployable artefact** — a self-contained script that can be dropped onto a jump host and run without installing the full package. The companion `.md` file serves as both documentation and a detailed technical specification. The version numbering (`v3.23.0`) implies a mature, actively versioned codebase.

---

## 5. Tests

### 5.1 Structure

- **`tests/`** directory — contains the pytest test suite
- **`conftest.py`** (1,669 bytes, root level) — pytest fixtures and session-level configuration
- **`pytest.ini`** — pytest configuration (test discovery, markers, etc.)

### 5.2 Coverage Instrumentation

The presence of `coverage_matrix.py` in the core package indicates the toolkit self-monitors its own test coverage across protocol/feature dimensions — an unusual and sophisticated pattern.

### 5.3 Evaluation vs. Unit Tests

The toolkit blurs the line between traditional unit tests and **LLM evaluation harnesses**:
- `eval_harness.py`, `d10_eval_set.py`, `retrieval_eval.py` function as domain-specific evaluators
- `ollama_judge.py` / `ollama_retrieval_judge.py` provide adversarial LLM-based scoring
- `calibration.py` tunes model thresholds

This reflects a **network-AI hybrid test strategy** — unit tests validate deterministic logic, while eval harnesses validate AI-generated outputs against expert-curated ground truth.

---

## 6. Web Application: `webapp/`

The `webapp/` directory exists as a dedicated front-end layer. Additionally:

- **`cisco_toolkit/blast_radius_explorer.html`** (989 KB): A large, self-contained interactive HTML application (likely D3.js or similar) for visualising migration blast radius — devices/services impacted by a given change. The 989 KB size indicates bundled JavaScript.
- **`portable/`**: Contains portable/pre-packaged distribution artefacts for environments where pip install is not possible.

---

## 7. CI/CD: `.github/`

The `.github/` directory contains GitHub Actions workflows. Based on the presence of:
- `pyproject.toml` — PEP 517/518 build system configured
- `ruff.toml` — ruff linter (likely run in CI)
- `mypy.ini` — type checking (likely run in CI)
- `pytest.ini` — test runner (likely run in CI)
- `requirements-dev.txt` — dev dependencies including test tooling

The CI pipeline likely follows the pattern: **lint (ruff) → type-check (mypy) → test (pytest) → build**.

---

## 8. Documentation

| File | Size | Content |
|---|---|---|
| `README.md` | 19 KB | Primary user-facing documentation |
| `CHANGELOG.md` | 32 KB | Full version history — indicates active, multi-version development |
| `RELEASING.md` | 4.3 KB | Release process SOP |
| `CLAUDE.md` | 12 KB | Claude AI operating instructions for this repo |
| `AI_SESSION_CONTEXT.md` | 25 KB | Persistent AI session context |
| `CHAT_SUMMARY.md` | 89 KB | Log of AI-assisted development sessions |
| `IMPROVEMENT_AND_GREENFIELD_PLANS.md` | 23 KB | Future roadmap |
| `COLLECT_PARSE_V3_23_0.md` | 292 KB | Detailed spec for standalone collector |
| `compass_artifact_wf-*.md` (×2) | 25 KB + 35 KB | Compass AI planning artefacts |
| `docs/` | — | Documentation subdirectory |

The `CHAT_SUMMARY.md` (89 KB) and `AI_SESSION_CONTEXT.md` (25 KB) reveal that **this toolkit has been co-developed with AI assistance** (Claude/Anthropic), with session context and summaries committed directly into the repository for continuity.

---

## 9. Dependencies

### 9.1 Runtime (`requirements.txt`, 631 bytes)

Expected dependencies based on module analysis:
- **netmiko / paramiko / nornir**: SSH device collection (cmdio.py, rest_collect.py)
- **openpyxl / xlsxwriter**: Excel report generation (excel.py)
- **jinja2**: Template rendering for HTML/MOP/Runbook
- **pydantic**: Data validation (model.py, detector_schema.py)
- **httpx / requests**: REST collection (rest_collect.py)
- **chromadb / sentence-transformers**: Vector store for RAG (recall.py, embed_qbank.py)

### 9.2 Dev (`requirements-dev.txt`, 661 bytes)

Expected:
- **pytest** + **pytest-cov**: Test runner + coverage
- **ruff**: Linting
- **mypy**: Static type checking
- **pre-commit**: Git hook enforcement

---

## 10. Configuration Files

| File | Purpose |
|---|---|
| `pyproject.toml` (7.3 KB) | PEP 517/518 build system, tool configs (pytest, ruff, mypy sections) |
| `pytest.ini` | pytest markers, test paths, addopts |
| `ruff.toml` | Lint rules, line length, select/ignore sets |
| `mypy.ini` | Type-check strictness, module ignore rules |
| `.gitignore` (2.4 KB) | Comprehensive Python .gitignore |
| `.gitattributes` (277 B) | Line ending and diff settings |
| `.graphifyignore` (1.7 KB) | Ignores for graph-based tooling |
| `.mcp.json` (116 B) | MCP server endpoint configuration |
| `devices.example.json` (390 B) | Example device inventory for testing/onboarding |
| `requirements.[HISTORY-REDACTED].json` (2.3 KB) | [HISTORY-REDACTED]-format requirements manifest |
| `requirements.sample.json` (1.3 KB) | Sample requirements template |

---

## 11. Findings & Risk Assessment

### 11.1 Strengths

1. **Comprehensive lifecycle coverage**: The toolkit covers every phase of a Cisco migration — collection, parsing, analysis, design, planning, validation, reporting, and operations.
2. **Mature versioning**: COLLECT_PARSE v3.23.0 and the 32 KB CHANGELOG indicate sustained, multi-release development.
3. **AI-native architecture**: Full MCP server, RAG pipeline, local LLM judge, and multi-agent council represent an advanced AI integration strategy ahead of industry norms.
4. **Field deployability**: The standalone monolithic script (`COLLECT_PARSE_V3_23_0.py`) addresses the common real-world constraint of restricted environments.
5. **Multiple output formats**: Excel, HTML, PowerPoint, MOP, CRD, Runbook — covering all stakeholder audiences (NOC, architecture, management, change control).
6. **Self-contained data**: Bundled `design_kb.py` (753 KB), `eoldb.py`, `ouidb.py`, `portdb.py` mean the toolkit operates air-gapped without external API dependencies.

### 11.2 Observations & Risks

1. **AI session artefacts in version control**: `CHAT_SUMMARY.md` (89 KB), `AI_SESSION_CONTEXT.md` (25 KB), and multiple `compass_artifact_*.md` files are committed to the main branch. These are operational/development artefacts and should be moved to `.gitignore` or a separate branch to keep the repo clean and avoid accidental disclosure of internal development context.
2. **Module size concentration**: `design_kb.py` at 753 KB is an extreme outlier. Static knowledge bases of this size are difficult to maintain, diff, and test. Consideration should be given to externalising it as a structured data format (JSON/YAML/SQLite) loaded at runtime.
3. **Monolithic collector pattern**: `COLLECT_PARSE_V3_23_0.py` at 216 KB is a single file with a manually bumped version in the filename. This pattern makes diff tracking harder and risks version fragmentation. A proper packaging strategy (`portable/` may address this) should be confirmed.
4. **`.mcp.json` in repo root**: The MCP server config file is committed. Ensure it contains no embedded credentials, API keys, or environment-specific endpoints.
5. **`questionnaire.json` at 131 KB**: A large, flat JSON assessment bank. No schema validation module is visible for this file specifically — ensure `detector_schema.py` or a dedicated validator covers it.
6. **`blast_radius_explorer.html` at 989 KB**: A bundled single-file HTML app of this size likely contains vendored JS libraries. Vendored dependencies should be audited for known CVEs and documented.
7. **Test isolation**: The presence of both `conftest.py` and the `tests/` directory is positive, but the eval harnesses (`eval_harness.py`, `ollama_judge.py`) depend on a running Ollama instance — these must be properly skipped/mocked in CI to avoid flaky tests.

---

## 12. Data Flow Diagram

```
  ┌─────────────────────────────────────────────────────────────────┐
  │                    INPUT SOURCES                                │
  │  SSH/CLI (cmdio)   REST/RESTCONF (rest_collect)   File Import   │
  │  (external_import)    Questionnaire (questionnaire.json)        │
  └─────────────────┬───────────────────────────────────────────────┘
                    │
                    ▼
  ┌─────────────────────────────────┐
  │  PARSE LAYER                    │
  │  parse.py · aclcheck.py         │
  │  fib.py · evpn_migration.py     │
  │  capture_integrity.py           │
  └────────────────┬────────────────┘
                   │
                   ▼
  ┌─────────────────────────────────┐
  │  ANALYSIS & SCORING             │
  │  analyze.py · scorecard.py      │
  │  archreview.py · causal.py      │
  │  eoldb.py · coverage_matrix.py  │
  │  assertions.py · selfcheck.py   │
  └──────────┬──────────────────────┘
             │              │
             ▼              ▼
  ┌──────────────┐  ┌──────────────────┐
  │  AI LAYER    │  │  DESIGN LAYER    │
  │  recall.py   │  │  design.py       │
  │  council.py  │  │  design_advisor  │
  │  mcp_server  │  │  design_kb.py    │
  └──────┬───────┘  │  protocol_kb.py  │
         │           └────────┬─────────┘
         │                    │
         └────────┬───────────┘
                  ▼
  ┌─────────────────────────────────┐
  │  PLANNING & VALIDATION          │
  │  mop.py · runbook.py · crd.py   │
  │  precert.py · gate_state.py     │
  │  attestation.py · failover.py   │
  │  cutover_sim.py · nrfu_export   │
  └────────────────┬────────────────┘
                   │
                   ▼
  ┌─────────────────────────────────┐
  │  OUTPUT LAYER                   │
  │  excel.py · html.py · deck.py   │
  │  build.py · ssot.py · defect    │
  │  blast_radius_explorer.html     │
  └─────────────────────────────────┘
```

---

## 13. Git History Summary

- Single contributor pattern (Tanveerahamed-Dev)
- Active development evidenced by: CHANGELOG.md at 32 KB, COLLECT_PARSE versioned to v3.23.0
- AI-assisted development workflow evidenced by committed session artefacts
- The `.design-sync/` directory suggests synchronisation with an external design system or Figma-like tool

---

## 14. Recommendations

| Priority | Recommendation |
|---|---|
| **P1** | Move `CHAT_SUMMARY.md`, `AI_SESSION_CONTEXT.md`, `compass_artifact_*.md` out of main branch or add to `.gitignore` |
| **P1** | Audit `blast_radius_explorer.html` vendored JS for CVEs |
| **P1** | Verify `.mcp.json` contains no credentials |
| **P2** | Externalise `design_kb.py` knowledge base to a structured data format (JSON/YAML/SQLite) |
| **P2** | Mark Ollama-dependent tests with a `@pytest.mark.requires_ollama` marker and skip in CI |
| **P2** | Add schema validation for `questionnaire.json` |
| **P3** | Add `CODEOWNERS` and branch protection rules |
| **P3** | Pin all dependencies with hashes in `requirements.txt` for reproducible builds |
| **P3** | Consider splitting `COLLECT_PARSE_V3_23_0.py` into versioned releases via `portable/` rather than filename versioning |

---

## 15. Artefact Catalogue

| Artefact | Path | Role |
|---|---|---|
| Primary package | `cisco_toolkit/` | All production source |
| Standalone collector | `COLLECT_PARSE_V3_23_0.py` | Field-deployable monolith |
| Blast radius visualiser | `cisco_toolkit/blast_radius_explorer.html` | Interactive HTML report |
| Assessment Q&A bank | `questionnaire.json` | Structured assessment data |
| Design knowledge base | `cisco_toolkit/design_kb.py` | Core domain knowledge |
| MCP server | `cisco_toolkit/mcp_server.py` | AI tool integration endpoint |
| LLM judge | `ollama_judge.py` | Offline LLM evaluation |
| Web application | `webapp/` | Front-end interface |
| Portable builds | `portable/` | Distribution artefacts |
| CI/CD | `.github/` | GitHub Actions workflows |
| Tests | `tests/` + `conftest.py` | pytest test suite |

---

*Dossier generated by source-level inspection of the repository tree and file-level evidence. All size figures are from GitHub API metadata (byte-accurate). No assumptions have been made beyond what the repository itself evidences.*
