## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

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
- **Deliverable generators** (`cisco_toolkit/`): design, mop, crd, engagement, archreview, ops, runbook, deck, html (explorer/diff/campaign), excel (workbook). Toggle with `--no-html` (explorer), `--no-docx` (runbook), `--no-pptx` (deck), and `--no-design`/`--no-mop`/`--no-crd`/`--no-engagement`/`--no-opshandbook`/`--no-archreview`; the workbook is always produced (there is no `--no-runbook`/`--no-deck`/`--no-excel`).
- **Tests:** `python -m pytest -q` (385). **graphify here:** `python -m graphify query|explain|path|"update ."` (not on PATH — use `python -m`). Bump the release version in `pyproject.toml` only at tag time; never bump the decoupled schema version `cisco_toolkit.__version__`.

> **Automation already wired in `.claude/`:** a `Stop` hook (`verify-green.sh`) runs `pytest` and blocks the turn until green after any `.py` change; a second `Stop` hook refreshes graphify after code edits; a `SessionStart` hook prints this engagement's state; a status line shows version/branch/model. All are fail-open (a timeout or error never wedges a turn) — disable via `/hooks` if needed.

> **Trust boundary — "read-only" is a trust model, not a sandbox.** The four analyst agents are constrained by their tool allowlist (no `Edit`/`Write` tools) + interactive permission prompts + their prompt mandate. But any agent holding `Bash` can run arbitrary python, and per Claude Code docs per-command Bash scoping can't be expressed in `tools:` while Bash deny-rules are bypassable — the OS `sandbox` is the only hard enforcement. So **keep the default permission mode (never `bypassPermissions`)** for these agents, so risky Bash (device writes, `git push`) still prompts you. The agents are designed to never attempt those; this is the backstop if one misreads intent.
