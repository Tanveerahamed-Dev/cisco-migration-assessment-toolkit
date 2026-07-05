## graphify

This project has a knowledge graph at graphify-out/ (~5.4k nodes — `graphify-out/GRAPH_REPORT.md` header is the authoritative count; after the 2026-07-03 de-pollution that also
excluded untracked scratch + side-engagement dirs — `ds-bundle/`+`.ds-sync/` (design-sync output), `Syntys_DC_Design/`,
`compass_artifact_*`, `scratch_*` — which had diluted it ~27%; the earlier 2026-06-25 pass excluded the stale `_ref/`
engine copy + the graph's own `graphify-out/` dumps — see `.graphifyignore`). The live graph is
**AST-only / no-egress** (the offline `update` re-extract): it is reproducible on an air-gapped host and contains
NO LLM-derived nodes — the de-pollution rebuild intentionally dropped a prior LLM-semantic "rationale" layer
(~434 nodes) because regenerating it needs an LLM call = egress, which the no-egress doctrine forbids. It fuses
the code + the repo's markdown (CLAUDE.md, docs/, incl. the deep-research corpus under docs/research/). Use it
FIRST for codebase questions AND for impact analysis before a change — a scoped subgraph beats grep/file-browsing.
graphify is NOT on PATH — always invoke as `python -m graphify`.

Rules:
- For codebase questions, run `python -m graphify query "<question>"` first. Use `python -m graphify path "<A>" "<B>"`
  for relationships and `python -m graphify explain "<concept>"` for a focused node + its neighbors. These return a
  scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep.
- Use the ADVANCED surface (it is underused — reach for it, don't default to grep sweeps), ALL offline/AST-only:
  **`python -m graphify affected "<symbol>()"`** is the highest-value verb — reverse blast-radius BEFORE editing a
  parser / detector / shared symbol, so every downstream caller + deliverable is shown FIRST (directly attacks the
  recurring parser↔detector / format-fidelity drift bug class). Plus the MCP tools: `god_nodes` (the core
  abstractions before a refactor), `query_graph`/`shortest_path` (enumerate every call/render site before a
  cross-surface change so it isn't applied to only some), `graph_stats` + `diagnose multigraph` (health),
  `benchmark` (the 5–15× token-reduction win).
- Offline NAVIGATION (replaces the never-existent wiki): `python -m graphify tree` → graphify-out/GRAPH_TREE.html
  (D3 collapsible tree) and `python -m graphify export callflow-html` (Mermaid call-flow); `GRAPH_REPORT.md` for the
  broad architecture review; `god_nodes` is the fastest map of the core abstractions.
- EGRESS — do NOT use in this air-gapped repo (they break the no-egress doctrine): `graphify add <url>` (fetches
  URLs), `graphify label` (calls an LLM), and the MCP `get_pr_impact` / `list_prs` / `triage_prs` (hit live
  api.github.com — and GitHub is paused). Every other verb (query/path/explain/affected/tree/export/diagnose/
  update/cluster-only) is fully offline.
- Keeping the graph current: a Stop hook re-extracts incrementally after .py edits (AST-only, no API cost) — this
  is what keeps graph.json fresh (it also picks up new docs/*.md alongside a code change). A MANUAL
  `python -m graphify update .` may REFUSE ("fewer nodes than existing — missing chunk files from a previous
  session"); that is graphify's SAFETY GUARD, not corruption — do NOT `--force` past an ACCIDENTAL shrink (it
  would drop good nodes). The one legit `--force` is an INTENTIONAL de-pollution: after adding non-source dirs
  to `.graphifyignore` (the tool's own "use after refactors that delete code" case), back up graph.json, run
  `update . --force`, then verify the only nodes dropped are the excluded paths (precedent: 2026-07-03 cleanup
  removed ~1.9k scratch/side-engagement nodes; 2026-06-25 removed the `_ref/` copy).

## Single source of truth (SSOT)

Before hardcoding or restating ANY shared fact (device counts, VLANs, versions, #decisions, prices),
consult **`docs/ssot.md`** — the project-wide registry mapping every fact-domain to its ONE authoritative
owner ("one index, many owners", not a mega-file). Read the fact from its owner; a copy is a *cache* and
must cite the owner. Assessment headline facts carry the mechanical contract (`cisco_toolkit/ssot.py` +
`docs/ssot-contract.md`, CI-enforced via `ssot.reconcile`); `tests/test_ssot_registry.py` guards the
registry's own pointers from rotting. Adding a new source of truth = register it in `docs/ssot.md`, and
add a reconcile guard if it overlaps an existing fact. This is Law 1 of the Deliverable Excellence Standard.

## Automated Senior Network Engineer (operating doctrine)

This repo operates as an automated senior Cisco network engineer for L1–L4 brownfield assessment & migration. The main session is the **Engagement Lead / orchestrator**: it owns the PPDIOO gate sequence and delegates specialist work to the subagents below (in `.claude/agents/`).

### Engagement gate sequence (PPDIOO / Cisco AS) — don't skip a gate
Assess → *(approve)* → Design HLD/LLD → *(peer review)* → MOP + rollback → *(dry-run + CAB)* → NRFU acceptance → cutover → PIR. Each arrow is a **human checkpoint**; never advance a gate without its upstream artifact.

### Specialist roster — delegate, don't do it all yourself
- **assessment-analyst** — current-state, inventory, gap analysis *(read-only)*
- **config-security-auditor** — CIS/hardening + software-advisory surface *(read-only)*
- **topology-reachability-analyst** — L1–L4 reachability, SPOF, blast radius *(read-only)*
- **design-author** — HLD/LLD, move-groups *(authors artifacts)*
- **mop-change-author** — MOP/cutover + rollback *(authors; change is a PR, never a device write)*
- **nrfu-validator** — NRFU/ATP + pre/post diff validation *(independent of the authors)*
- **deliverable-qa-reviewer** — adversarial cross-artifact QA *(independent; never edits what it reviews)*
- **release-captain** — version/changelog/PIR/audit trail
- Commands: `/assess` `/deliverables` `/audit` `/reachability` `/qa` `/release` `/ask`

### Non-negotiable guardrails (network-automation safety)
1. **Read-only by default.** No writes to devices, ever. Production change only via a human-owned PR + CAB, inside a maintenance window, with a defined rollback.
2. **Proposer ≠ verifier.** An independent pass checks every consequential output against evidence/baseline (use deliverable-qa-reviewer / nrfu-validator).
3. **Evidence-grounded & coverage-honest.** Ground every device claim in collected evidence (cite the field/line); never infer state from memory. "Not observed" never silently becomes "healthy" (the bare `show logging`-on-NX-OS false-health class).
4. **Counterexamples over vibes; one source of truth** — reconcile every shared fact (device counts, VLANs, IPs) to a single source.

### Engine entrypoints (the source of truth — run it, don't reinvent it)
- **Assess:** `cisco-assess --devices-file devices.json --template <tmpl>.xlsx --output <out>.xlsx` (entry `COLLECT_PARSE_V3_23_0:main`). Re-analyze offline: add `--no-collect --collection-dir <dir>`. **A bare `cisco-assess` SSHes to live gear — only run a live collection when explicitly asked.**
- **Validate cutover:** `cisco-assess --compare OLD.snapshot.json NEW.snapshot.json --output Diff.xlsx`; campaign trend: `--trend snap1 snap2 …`.
- **Universal architecture coverage** (both ingestion channels — see `docs/universal-architecture-coverage.md`): 40 coverage-honest architecture-class detectors across 23 classes (the in-code `_ARCH_COVERAGE_REGISTRY` is the authoritative count) spanning SSH `show`-text (SD-Access/LISP, TrustSec/CTS, DMVPN, IPsec, BFD, IPv6, SP/MPLS, + switch-native) **and** JSON controller-REST (Cisco ACI/APIC, Catalyst SD-WAN/vManage). Controller fabrics: collect read-only via `python -m cisco_toolkit.rest_collect apic|vmanage --url https://… --user <ro> --password <pw> --out-dir <dir>` (GET-only, dedicated read-only RBAC account, opt-in, never auto-runs), then analyze with `--no-collect`. Coverage map is published as `snap['architecture_coverage']` (read by the explorer ✎Design + webapp); ACI migration move-groups in `design_blueprint.target_state.aci_move_groups`.
- **Deliverable generators** (`cisco_toolkit/`): design, mop, crd, engagement, archreview, ops, runbook, deck, html (explorer/diff/campaign), excel (workbook). Toggle with `--no-html` (explorer), `--no-docx` (runbook), `--no-pptx` (deck), and `--no-design`/`--no-mop`/`--no-crd`/`--no-engagement`/`--no-opshandbook`/`--no-archreview`; the workbook is always produced (there is no `--no-runbook`/`--no-deck`/`--no-excel`).
- **Tests:** `python -m pytest -q` (~1,390 test functions across `tests/` + `webapp/tests` — both in the default gate; don't restate the count, run the suite). **graphify here:** `python -m graphify query|explain|path|"update ."` (not on PATH — use `python -m`). Bump the release version in `pyproject.toml` only at tag time; never bump the decoupled schema version `cisco_toolkit.__version__`.

> **Automation already wired in `.claude/`:** a `Stop` hook (`verify-green.sh`) runs `pytest` and blocks the turn until green after any `.py` change; a second `Stop` hook refreshes graphify after code edits; a `SessionStart` hook prints this engagement's state; a status line shows version/branch/model. All are fail-open (a timeout or error never wedges a turn) — disable via `/hooks` if needed.

> **Trust boundary — "read-only" is a trust model, not a sandbox.** The four analyst agents are constrained by their tool allowlist (no `Edit`/`Write` tools) + interactive permission prompts + their prompt mandate. But any agent holding `Bash` can run arbitrary python, and per Claude Code docs per-command Bash scoping can't be expressed in `tools:` while Bash deny-rules are bypassable — the OS `sandbox` is the only hard enforcement. So **keep the default permission mode (never `bypassPermissions`)** for these agents, so risky Bash (device writes, `git push`) still prompts you. The agents are designed to never attempt those; this is the backstop if one misreads intent.
