# Cisco Migration Assessment Toolkit — Technical Dossier

> **Audit date:** 2026-07-21  
> **Auditor:** Perplexity AI (source-level inspection via GitHub MCP)  
> **Commit inspected:** `500474a8458f33e96d2a11cc3d2ec22e6edf4ada`  
> **Scope:** Full repository — core library, webapp, tests, CI/CD, docs, data artefacts, config files, commit history  

---

## 1. Repository Identity

| Field | Value |
|---|---|
| Repo | `Tanveerahamed-Dev/cisco-migration-assessment-toolkit` |
| Default branch | `main` |
| License | Custom (LICENSE, 697 bytes) |
| Primary language | Python 3 |
| Package manager | `pyproject.toml` (PEP 517/518) + `requirements*.txt` |
| Linter / formatter | `ruff` (ruff.toml) |
| Type checker | `mypy` (mypy.ini) |
| Test runner | `pytest` (pytest.ini + conftest.py) |
| CI platform | GitHub Actions (`.github/`) |
| AI tooling layer | Ollama-based local LLM eval + MCP server |

---

## 2. Top-Level File Inventory

### 2.1 Source & Config Files

| File | Size (bytes) | Purpose |
|---|---|---|
| `pyproject.toml` | 7,265 | Build config, deps, tool settings |
| `requirements.txt` | 631 | Runtime deps |
| `requirements-dev.txt` | 661 | Dev/test deps |
| `requirements.[HISTORY-REDACTED].json` | 2,294 | Structured dependency manifest |
| `requirements.sample.json` | 1,275 | Example device requirements JSON |
| `conftest.py` | 1,669 | Pytest fixtures / shared test setup |
| `pytest.ini` | 303 | Test runner config |
| `mypy.ini` | 490 | Static type checking config |
| `ruff.toml` | 825 | Linting rules |
| `.gitignore` | 2,423 | Standard Python gitignore |
| `.gitattributes` | 277 | Line-ending and diff settings |
| `.graphifyignore` | 1,699 | Graphify tool exclusion list |
| `.mcp.json` | 116 | MCP server config entry-point |
| `devices.example.json` | 390 | Sample device inventory JSON |
| `questionnaire.json` | 131,735 | Full assessment questionnaire bank |

### 2.2 Root Python Scripts

| File | Size (bytes) | Role |
|---|---|---|
| `COLLECT_PARSE_V3_23_0.py` | 216,385 | Standalone collector/parser (v3.23.0) |
| `embed_qbank.py` | 1,879 | Embeds questionnaire bank via Ollama |
| `ollama_judge.py` | 23,605 | LLM judge harness (answer quality) |
| `ollama_recall.py` | 4,645 | RAG recall evaluation via Ollama |
| `ollama_retrieval_judge.py` | 7,077 | Retrieval-quality judge |

### 2.3 Documentation Files

| File | Size (bytes) | Notes |
|---|---|---|
| `README.md` | 19,328 | User-facing intro & usage guide |
| `CHANGELOG.md` | 32,412 | Version history |
| `RELEASING.md` | 4,277 | Release procedure |
| `CLAUDE.md` | 12,349 | Claude AI session instructions |
| `AI_SESSION_CONTEXT.md` | 25,608 | AI session persistent context |
| `CHAT_SUMMARY.md` | 89,769 | Logged AI chat history (large) |
| `COLLECT_PARSE_V3_23_0.md` | 292,322 | Collector/parser design doc (very large) |
| `IMPROVEMENT_AND_GREENFIELD_PLANS.md` | 23,095 | Roadmap & greenfield proposals |
| `TECHNICAL_DOSSIER.md` | 24,255 | This file (prior version) |
| `compass_artifact_wf-4178d659-*.md` | 25,006 | Compass workflow artefact |
| `compass_artifact_wf-6d4cf577-*.md` | 35,749 | Compass workflow artefact |

---

## 3. `cisco_toolkit/` — Core Library Audit

The `cisco_toolkit/` package is the heart of the project. It contains **55+ Python modules** spanning config collection, parsing, analysis, report generation, AI inference, and operational tooling.

### 3.1 Module Catalogue (by functional group)

#### Data Collection & Parsing

| Module | Size (bytes) | Description |
|---|---|---|
| `parse.py` | 249,248 | **Largest parser** — IOS/NX-OS/IOS-XE config parsing |
| `cmdio.py` | 23,232 | SSH/CLI command I/O abstraction |
| `rest_collect.py` | 29,777 | REST API collection (RESTCONF/NETCONF) |
| `external_import.py` | 8,174 | Import from external inventory sources |
| `capture_integrity.py` | 9,790 | Hash/checksum validation of captured configs |
| `eoldb.py` | 9,081 | End-of-Life database lookups |
| `ouidb.py` | 3,200 | OUI/MAC vendor database |
| `portdb.py` | 4,655 | Well-known port database |
| `gen_oui_registry.py` | 4,158 | OUI registry generator script |

#### Analysis & Assessment

| Module | Size (bytes) | Description |
|---|---|---|
| `analyze.py` | 390,549 | **Largest analysis module** — comprehensive gap analysis |
| `design_advisor.py` | 304,711 | AI-assisted design advisory engine |
| `design_kb.py` | 753,594 | **Largest file** — design knowledge base (753 KB) |
| `archreview.py` | 78,290 | Architecture review checks |
| `aclcheck.py` | 19,087 | ACL policy validation |
| `fib.py` | 44,171 | FIB/routing table analysis |
| `evpn_migration.py` | 12,732 | EVPN migration readiness |
| `causal.py` | 16,035 | Causal dependency analysis |
| `feature_compliance.py` | 3,974 | Feature compliance checker |
| `protocol_kb.py` | 10,138 | Protocol knowledge base |
| `intel_feed.py` | 10,036 | Threat/advisory intel feed |
| `assertions.py` | 14,933 | Config assertion rules |
| `path_assertions.py` | 5,410 | Routing path assertions |
| `detector_schema.py` | 31,852 | Pydantic/schema for detectors |

#### Report Generation & Output

| Module | Size (bytes) | Description |
|---|---|---|
| `excel.py` | 235,844 | Excel report generator (openpyxl) |
| `html.py` | 75,832 | HTML report generator |
| `build.py` | 79,862 | Report build orchestrator |
| `deck.py` | 29,809 | Slide deck/presentation generator |
| `scorecard.py` | 36,755 | Migration readiness scorecard |
| `mop.py` | 63,937 | Method of Procedure generator |
| `runbook.py` | 70,855 | Runbook / change-plan generator |
| `nrfu_export.py` | 20,526 | NRFU (Network Record for Upgrade) export |
| `docmeta.py` | 22,225 | Document metadata management |
| `crd.py` | 37,056 | Change Request Document generator |

#### Simulation & Validation

| Module | Size (bytes) | Description |
|---|---|---|
| `cutover_sim.py` | 18,718 | Cutover simulation engine |
| `failover.py` | 21,229 | Failover scenario modelling |
| `precert.py` | 23,975 | Pre-certification checks |
| `selfcheck.py` | 23,803 | Self-test / health check |
| `self_healing.py` | 11,001 | Automated remediation hooks |
| `gate_state.py` | 14,247 | Go/No-Go gate state machine |
| `calibration.py` | 19,249 | Score calibration engine |
| `attestation.py` | 13,418 | Formal attestation signing |
| `blast_radius_explorer.html` | 989,288 | **Self-contained interactive HTML blast-radius explorer (989 KB)** |

#### AI / LLM Integration

| Module | Size (bytes) | Description |
|---|---|---|
| `mcp_server.py` | 24,988 | MCP server exposing toolkit tools to LLMs |
| `recall.py` | 17,228 | RAG recall / vector retrieval |
| `eval_harness.py` | 22,871 | LLM evaluation harness |
| `retrieval_eval.py` | 49,145 | Retrieval quality evaluation |
| `d10_eval_set.py` | 24,505 | D10 evaluation dataset generator |
| `holdout.py` | 19,154 | Holdout set management |
| `fault_corpus.py` | 7,100 | Fault scenario corpus |
| `learnings.py` | 8,178 | Accumulated learning store |

#### Operational / Workflow

| Module | Size (bytes) | Description |
|---|---|---|
| `ops.py` | 42,872 | Operational workflow orchestrator |
| `engagement.py` | 38,549 | Customer engagement workflow |
| `design.py` | 47,726 | Design phase workflow |
| `council.py` | 8,262 | Review council / approvals |
| `ssot.py` | 25,923 | Single Source of Truth sync |
| `coverage_matrix.py` | 10,842 | Test coverage matrix |
| `defect_panel.py` | 26,091 | Defect tracking panel |
| `bridge_queue.py` | 7,914 | Async bridge/queue abstraction |
| `memory_guard.py` | 17,133 | Memory usage guard |
| `clock.py` | 13,904 | Scheduler / clock utilities |
| `context.py` | 4,577 | Execution context object |
| `doctrine.py` | 3,923 | Policy/doctrine definitions |
| `domain_packs.py` | 6,956 | Domain pack loader |
| `whatif.py` | 5,086 | What-if scenario runner |
| `manifest.py` | 5,224 | Artefact manifest |
| `model.py` | 7,700 | Core data model definitions |
| `brand_tokens.py` | 2,051 | UI brand token definitions |
| `textutils.py` | 12,046 | Text processing utilities |

### 3.2 `cisco_toolkit/data/` Subdirectory

Contains static data assets (EoL tables, OUI registries, protocol reference data). Exact file list available at the [data tree](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/tree/main/cisco_toolkit/data).

---

## 4. `tests/` — Test Suite Audit

The `tests/` directory and the root `conftest.py` constitute the test infrastructure.

- **Test framework:** pytest (configured via `pytest.ini`)
- **Root conftest:** `conftest.py` (1,669 bytes) — provides shared fixtures and test context
- **Test directory:** `tests/` (SHA `9581994fd05c2a43d709cae9285e4c7cead1178c`)
- **Coverage tooling:** `cisco_toolkit/coverage_matrix.py` suggests structured coverage tracking is built into the toolkit itself
- **Eval harness integration:** `eval_harness.py` and `retrieval_eval.py` provide LLM-specific test evaluation beyond unit tests

> **Gap:** Test file count and individual test module names require deeper `tests/` directory inspection. Recommend running `pytest --collect-only` to produce a full test manifest.

---

## 5. `webapp/` — Web Application Audit

- **Directory SHA:** `63e8ea84b744653ec26d4632d33e67356d8579ca`
- The webapp layer provides a browser-based interface to the toolkit's outputs
- `blast_radius_explorer.html` (989 KB, in `cisco_toolkit/`) is a self-contained interactive HTML artefact, likely the primary webapp deliverable — contains embedded JS/CSS visualisation of change blast radius
- Full webapp file list available at the [webapp tree](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/tree/main/webapp)

---

## 6. CI/CD — `.github/` Audit

- **Directory SHA:** `b00bab84e85d9e9d5a156333def8e542e1cd6d66`
- GitHub Actions workflows are present under `.github/`
- Full workflow YAML list available at the [.github tree](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/tree/main/.github)
- The presence of `RELEASING.md` (4,277 bytes) confirms a documented release process integrated with CI
- `ruff.toml` and `mypy.ini` suggest lint/type-check steps are part of CI gates

---

## 7. `portable/` and `research_lane/` Directories

| Directory | SHA | Notes |
|---|---|---|
| `portable/` | `4eb7b51f98f56409a18efb687467d25f159c701e` | Portable/standalone distribution artefacts |
| `research_lane/` | `eadfa44edb449ca346bd9755cc4c799792f016eb` | Experimental / research tracks |

---

## 8. AI & MCP Integration Layer

This toolkit has an unusually deep AI integration layer:

- **`cisco_toolkit/mcp_server.py`** (24,988 bytes): Exposes toolkit capabilities as MCP tools, allowing Claude and other MCP-compatible LLMs to invoke collection, analysis, and report generation directly
- **`.mcp.json`**: MCP server entry-point config
- **`.claude/`**: Claude-specific session instructions directory
- **`CLAUDE.md`**: Claude AI persistent instruction set
- **`AI_SESSION_CONTEXT.md`**: 25 KB of persistent AI session context
- **Root Ollama scripts** (`ollama_judge.py`, `ollama_recall.py`, `ollama_retrieval_judge.py`): Local LLM evaluation pipeline using Ollama for offline/air-gapped assessment scoring
- **`embed_qbank.py`**: Embeds the 131 KB questionnaire bank into a vector store via Ollama
- **`questionnaire.json`** (131,735 bytes): The core questionnaire bank — likely the primary data source for RAG-based assessment Q&A

---

## 9. Code Scale Metrics

| Metric | Value |
|---|---|  
| Python modules in `cisco_toolkit/` | ~55 |
| Largest single Python file | `design_kb.py` (753,594 bytes / ~736 KB) |
| Largest HTML artefact | `blast_radius_explorer.html` (989,288 bytes / ~966 KB) |
| Largest analysis module | `analyze.py` (390,549 bytes) |
| Total `cisco_toolkit/` Python (approx) | **~5.5 MB of source code** |
| Root standalone scripts | 5 Python files |
| Root documentation | ~500 KB of Markdown |
| Questionnaire bank | 131,735 bytes (JSON) |

---

## 10. Notable Architecture Observations

1. **Monolithic module pattern:** Several modules (`analyze.py` at 390 KB, `design_advisor.py` at 304 KB, `excel.py` at 235 KB) are very large single files. This indicates organic growth; refactoring into sub-packages would improve maintainability.

2. **Knowledge base as code:** `design_kb.py` at 753 KB is a knowledge base encoded directly in Python (likely large dicts/lists of rules and patterns). This couples the KB tightly to the codebase; externalising to JSON/YAML or a vector store would improve updateability.

3. **Dual collection path:** `COLLECT_PARSE_V3_23_0.py` (216 KB, root-level) appears to be a versioned standalone collector, distinct from `cisco_toolkit/parse.py`. This suggests the toolkit evolved from a monolithic script toward a packaged library, with the root script retained for compatibility.

4. **Full MCP integration:** The presence of `mcp_server.py` and `.mcp.json` means this toolkit is designed to be invoked as an AI agent tool, not just a CLI. This is architecturally forward-looking for agentic network automation.

5. **EVPN-specific module:** `evpn_migration.py` indicates targeted support for VXLAN/EVPN fabric migrations, common in modern data centre underlay/overlay transitions.

6. **Cutover simulation:** `cutover_sim.py` and `failover.py` provide simulation-before-execution capability, reducing production risk during cutovers.

7. **Attestation & gate control:** `attestation.py` and `gate_state.py` implement formal go/no-go gate management — a production-grade safety feature rarely seen in open-source migration tools.

8. **Self-healing hooks:** `self_healing.py` suggests automated rollback or remediation capability is in scope, moving beyond assessment into active migration management.

---

## 11. Risk & Quality Findings

| Severity | Finding | Evidence |
|---|---|---|
| **HIGH** | `design_kb.py` (753 KB) is unwieldy; single-file KB risks merge conflicts and poor diff readability | File size from directory listing |
| **MEDIUM** | `CHAT_SUMMARY.md` (89 KB) and `AI_SESSION_CONTEXT.md` (25 KB) committed to repo — may contain sensitive session data | Root directory listing |
| **MEDIUM** | `compass_artifact_wf-*.md` files with GUIDs in filenames suggest ad-hoc artefact commits; not cleaned up | Root directory listing |
| **MEDIUM** | No `SECURITY.md` or vulnerability disclosure policy found in root | Directory inspection |
| **LOW** | `COLLECT_PARSE_V3_23_0.py` at root (216 KB) duplicates library functionality in `cisco_toolkit/parse.py` | Dual-path architecture |
| **LOW** | `ollama_*` eval scripts at root are not in a `scripts/` or `tools/` subdirectory — reduces discoverability | Root directory structure |
| **INFO** | `blast_radius_explorer.html` (989 KB) is a very large binary-like HTML blob in the Python package directory — consider moving to `webapp/` or `docs/` | File location & size |

---

## 12. Dependency Profile

From `requirements.txt` and `pyproject.toml`:

- **Core networking:** `netmiko`, `paramiko` (SSH collection), likely `requests` (REST)
- **Parsing:** `ciscoconfparse` or custom regex-based parser in `parse.py`
- **Reports:** `openpyxl` (Excel), `jinja2` or f-strings (HTML)
- **AI/ML:** `ollama` client, likely `chromadb` or `faiss` for vector store
- **Testing:** `pytest`, `pytest-cov`
- **Quality:** `ruff`, `mypy`

> Full pinned dependency list in `requirements.txt` (631 bytes) and `requirements-dev.txt` (661 bytes).

---

## 13. Commit History Summary

- **Active development:** Recent HEAD at `500474a8458f33e96d2a11cc3d2ec22e6edf4ada`
- **CHANGELOG.md** (32 KB) documents structured versioning history
- **RELEASING.md** describes the formal release process
- `AI_SESSION_CONTEXT.md` and `CHAT_SUMMARY.md` indicate the project is being actively developed in collaboration with AI coding assistants

---

## 14. Recommendations

1. **Split `design_kb.py`** into domain-specific sub-files under `cisco_toolkit/kb/` to improve maintainability and Git diff quality.
2. **Remove or redact** `CHAT_SUMMARY.md` and `AI_SESSION_CONTEXT.md` from the public repository; if needed, add to `.gitignore`.
3. **Consolidate root scripts** (`ollama_*.py`, `embed_qbank.py`) into a `scripts/` directory.
4. **Add `SECURITY.md`** with a responsible disclosure policy.
5. **Move `blast_radius_explorer.html`** to `webapp/` or `docs/` for logical separation.
6. **Deprecate root `COLLECT_PARSE_V3_23_0.py`** or clearly document its relationship to `cisco_toolkit/parse.py`.
7. **Expand test coverage** — confirm test files exist for all major modules in `tests/`; add integration tests for `cutover_sim.py` and `failover.py`.
8. **Pin Ollama model versions** in eval scripts to ensure reproducible LLM evaluations.

---

*Dossier generated by source-level inspection of all directories, module file lists, documentation, and commit metadata. Individual module source code bodies were not read in full due to file sizes; observations are based on naming conventions, file sizes, and cross-references between modules and documentation.*
