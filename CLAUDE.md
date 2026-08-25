## Repository-review record (CLOSED 2026-08-03)

The whole-repository hardening review is **complete and merged to `main`**. There is nothing to
resume: the review branch, its checkpoint verifier, and `/resume-review` were retired when it
closed. `docs/review-hardening-handoff-2026-07-30.md` is now a **historical record**, not a live
checkpoint — read it for *why* something is the way it is (§7–§13 carry the reasoning behind most
coverage-honesty guards), not for instructions to follow.

What it concluded: CI repository-wide green on every supported interpreter and both platforms;
the archives source-bound; the Git history rewritten marker-free on every branch and tag (old
shas translate via the commit-map preserved in `private-inputs/history-rewrite-20260802/` —
ledger shas predating §13.11 refer to superseded history); the master reference deployed.

**Carried forward — the only genuinely open review-tail items:**
- GitHub Support ticket `#4624412` — server-side purge of pre-rewrite objects and stale
  `refs/pull/*`. Until they act, superseded SHAs still resolve by direct URL on this private repo.
- The master-reference site is deployed **private**; publishing it publicly is an open decision.

**Closed carried questions, retained for context:** §13.9's EoL registry `evidence_method` claim
  is CLOSED (2026-08-03, handoff
  §13.15: reworded to offline-honest transcription provenance everywhere unpinned; the
  byte-pinned fixture's frozen sentence is superseded in interpretation and ratchet-guarded by
  `tests/test_eoldb_provenance.py` until the next evidence refresh), and the 3.14
  leading-dot-run name-shape question is CLOSED (2026-08-03, handoff §13.14: stdlib-following
  semantics accepted; measured — on 3.14 semantics `os.path.splitext` and `PurePath.suffix`
  agree on every legal directory-entry name, so the splitext restatement is harmless there and
  the ≤3.13 legs guard the divergence exactly where it exists), and react-router v7 is CLOSED
  (2026-08-03, handoff §13.16: migrated to `react-router@7.18.2` — the future flags were
  already live in production, so the swap was the package rename; verified through unit,
  build and real-browser E2E). **Every carried question is now closed.** The subsequent frontend
  platform migration is also complete: Node 24, React/React DOM 19.2.8, React Router 8.3.0,
  Vite 8.2.1, and `@vitejs/plugin-react` 6.0.5. It removed the temporary RSC-only npm-audit
  exception; this is current repository state, not a reopened item from the historical review.

The 2026-08-07 lifecycle-authority closure is also complete. Repository installs, wheels, sdists,
and Atlas bundles carry and verify the exact 13,261-byte `eol-bulletins.json` fixture; self-test and
release smoke gates fail closed when it is absent or altered. Every lifecycle consumer now uses the
canonical Past-LDoS / Near-LDoS / Past-EoS / Active / Unknown bands with entitlement-neutral date
semantics, and future, unrecognized, or missing lifecycle rows remain Unknown rather than being
  rendered as healthy. The golden snapshot, engine-owned sample fleet, and checked frontend distribution were
  regenerated from that final source state.

### Cross-agent synchronization receipt (2026-08-07)

Codex audited local branches, reflogs, stashes, registered and abandoned Claude worktrees, preserved refs,
and surviving dangling histories. No recoverable Claude product/design change is missing from local `main`;
the remaining old artifacts are committed equivalents or obsolete conflict state. Local `main` is ahead of
`origin/main`; publishing it is a separate explicit action, so inspect live Git rather than caching an ahead count.
Root `AGENTS.md` now routes Codex into this shared doctrine and `docs/ssot.md`; Claude memory and hooks remain
platform-specific aids, never the sole cross-agent owner.

The audit also read the project-scoped Claude transcripts through their latest local event (2026-08-05) and
the six newer, uncommitted Claude memory updates. Their durable host/release lessons are now represented in
root `AGENTS.md` and `docs/quality/learnings.md`; the machine-local memory repository remains a cache, not a
required source for a future Codex session. A fresh `git fetch` on 2026-08-07 proved local `main` was zero
commits behind `origin/main` at that receipt; re-fetch rather than treating that observation as permanent.

The tracked Claude Design inputs are locally reconciled and the 21-card bundle builds, validates, renders, and
grades with no pending local card. The authenticated Claude Design inventory/re-sync is also complete; exact
local/remote anchors, the preservation check for remote-only `templates/**`, and the upload receipt live in
`.design-sync/NOTES.md`. One external handoff remains before claiming end-to-end Design synchronization:
promotion of the six intentional card pixel changes from the GitHub `windows-2025` capture artifact.
Workstation candidates are reviewed evidence only and must not replace the canonical hosted-runner baselines.

A future whole-repo review should start fresh rather than reopening this one. Its most reusable
output is the defect *shapes*, not its findings: absence rendered as health, a guard scoped to a
hand-maintained list standing in for the class it means, and gates whose success path was never
executed.

### Atlas whole-repository master reference (candidate 2026-08-07)

`master-reference/` now owns the private, read-only Atlas reference implementation: the exact-Git-tree
compiler, line/symbol/entity projection, executable architecture and claim contracts, closed capability
and gap catalogs, Source Explorer/Ask Atlas/labs, deterministic PDF and offline/release family, SBOM,
preservation coverage, and the local read-only continuity validator. `docs/ssot.md` names each derivative
and its live owner. The compiler manifest for the selected commit is the only valid census; do not cache
its file, line, symbol, Graphify, dependency, or artifact counts in this doctrine.

A structurally complete compiler run is deliberately not semantic approval. Behavioral depth, runtime
and branch evidence, field validation, format-aware binary privacy review, independent Level-4 review,
the owner Ed25519 ceremony/recovery materials, complete Python/toolchain preservation, and public
publication authority remain explicit acceptance gates. The release manifest must remain `BLOCK` while
any of those gates is absent. The self-contained HTML is an executive navigation view; complete safe
source records live in lazy hosted modules and the offline compiler projection. Neither the reference nor
its continuity CLI may collect client evidence, write devices or the Vault, call runtime external AI, or
grant publication authority.

The read-only `verify-claim-review` command is the first authenticated external-evidence boundary. It
accepts an exact canonical review payload, detached signature, separately supplied trust policy, and
separately supplied reviewer public key; it rejoins every row to the immutable compiler claim subjects.
It does not write a family member or mutate compiler/release gates. No accepted review envelope is
currently present, so the bounded reviewed count remains zero and global closure remains false.

The additive `verify-pdf-review` boundary applies the same fail-closed custody model to one immutable
generated-PDF family without consulting mutable compiler output or current Git state. Its PDF-specific
schemas require exact manifest, attestation, PDF-gate, source and PDF bindings; a fixed Poppler render
profile; and one ordered, digest-bound signed row for every page. The external reviewer policy must assert
independence from both the PDF producer and release builder. Its stdout-only result is explicitly
nonpromoting: family mutation, current/global gate closure, owner-manifest signature, accessibility,
binary privacy and publication authority remain false. Prior conversational visual QA is not silently
converted into signed evidence, and no accepted PDF-review envelope is currently present. The signed PNG
hashes and render profile are reviewer assertions: v1 does not ingest PNG bytes or independently rerender
the PDF, so it does not establish PDF-to-PNG provenance.

The dependency audit is also an explicit release boundary, not a silent waiver. Nano ID is locked to the
patched 3.3.18 line through both the Master Reference and AssessHub npm overrides. Vinext 0.0.50's exact
`image-size` edge is now scoped to the tracked `@atlas/bounded-image-size` package, whose source-bound
PNG/SVG-only parser rejects the advisory-named HEIF, JXL and ICNS families and every other unsupported
format. The source contract rejects static image imports, numbered metadata-route images and `next/image`
entry points until they have a bounded owner. This removes the affected registry package from that Vinext
edge, but it is not release closure: Next 16.2.12 independently embeds compiled parser code outside npm
override resolution, including an image-size implementation for which mutation-effective watchdogs
preserve the known ICNS/JXL zero-progress finding. The release gate therefore remains blocked pending removal or authoritative assessment of that
vendored residual plus a fresh source-authenticated applicability/VEX review. A zero-result npm audit does
not supersede this owner. Do not suppress the gate or downgrade the framework as a substitute for evidence.

## Shared Git and host operating doctrine

- This repository currently preserves PR work with merge commits. Do not assume squash semantics;
  inspect `git log --merges origin/main` and preserve the established method unless the user explicitly
  chooses another. When hosted required checks are structurally dead (`steps: 0`), an admin bypass still
  requires exact-head scope review, the relevant local gate with recorded evidence, and explicit user
  authority; then read the merged-main `main-selfhosted` verdict.
- `main-selfhosted` runs on the same physical Windows development host as local verification. Before
  starting a full local pytest run, check whether that workflow is active; concurrent suites can starve
  an otherwise healthy job into a timeout. A long step with a null conclusion is cancellation/timeout
  evidence, not a test assertion failure.
- Commands handed to the user are normally pasted into Windows PowerShell 5.1 from an arbitrary
  directory. Prefer performing authorized actions directly; otherwise provide one command at a time,
  avoid `&&`, and establish the repository with an absolute `cd` or `git -C`.
- On this host, the Microsoft Store `python` alias can satisfy a PATH probe but cannot import graphify.
  The tracked Stop hook probes the full guard and may use a POSIX-form path to the real interpreter from
  `graphify-out/.graphify_python`; verify a positive rebuild by graph mtime/log rather than the absence of a
  warning. The upstream-generated `.git/hooks/post-commit` imports `graphify.watch` directly and bypasses the
  tracked guard. Replacing/reactivating that local hook requires a separately authorized one-time action after
  merge; do not treat a generated hook as guarded merely because its interpreter is pinned.

## graphify

This project has a knowledge graph at graphify-out/ (12,881 nodes / 22,851 edges as of 2026-08-07 — this figure is only a dated cache; the machine-readable owner is `graphify-out/graph.json`, so read it rather than copying this line; after the 2026-07-03 de-pollution that also
excluded untracked scratch + side-engagement dirs — `ds-bundle/`+`.ds-sync/` (design-sync output), `*_DC_Design/`,
`compass_artifact_*`, `scratch_*` — which had diluted it ~27%; the earlier 2026-06-25 pass excluded the stale `_ref/`
engine copy + ordinary graph-output dumps — see `.graphifyignore` and the installed-producer exceptions below). The live graph is
**AST-only / no-egress** (the offline `update` re-extract): it is reproducible on an air-gapped host and contains
NO LLM-derived nodes — the de-pollution rebuild intentionally dropped a prior LLM-semantic "rationale" layer
(~434 nodes — NB: a DIFFERENT thing from the current extractor's ~2.9k `file_type: rationale` nodes, which
are AST-extracted docstrings/comments carrying `_origin: ast`, no egress; same word, not a
regression. Scope that precisely: **zero** nodes anywhere carry an LLM origin, which is the invariant that
matters, but a handful — 11 of ~9.5k, 3 of them rationale — carry NO `_origin` at all. Those are the
hand-CURATED layer that survives re-extraction, which `update` reports as "backed up curated graph";
curated ≠ LLM-derived, so the doctrine holds, but "every node is `_origin: ast`" would be the wrong check —
assert no LLM origin instead) because regenerating the LLM layer needs an LLM call = egress, which the no-egress doctrine forbids
(sole carve-out: a **local** Ollama on 127.0.0.1 is on-host compute, not egress — ADR 0001 Amendment 1;
`ollama_recall.py` + `ollama_judge.py`. The carve-out licenses local INFERENCE only — it does NOT
re-authorize `graphify label` or any LLM-derived graph nodes: the graph stays AST-only for
reproducibility/provenance, a separate invariant from egress. Cloud LLM calls stay forbidden). It fuses code with
the repo's **structural** Markdown layer: page/frontmatter, headings, and links from CLAUDE.md and docs/ (including
docs/research/). Paragraph bodies are not indexed; retrieve the raw document for body content or semantic freshness.
Use the graph FIRST for codebase questions AND impact analysis before a change — a scoped subgraph beats broad grep.
graphify is NOT on PATH. On this owner host, read-only query/navigation verbs use `py -3.12 -m graphify`.
Source extraction has exactly three guarded forms: `py -3.12 -I -B tools/graphify_guarded.py update <local-path> [--force] [--no-cluster]`,
`py -3.12 -I -B tools/graphify_guarded.py watch <local-path>`, or
`py -3.12 -I -B tools/graphify_guarded.py extract <local-path> --code-only [--no-cluster]`, **from the main
checkout (repo root), never a linked worktree**: `graphify-out/` is untracked AND `.graphifyignore` excludes
`.claude/worktrees/`, so a worktree carries no owner graph. The guard refuses `update`/`watch` without an
established `graphify-out/graph.json`, rejects linked worktrees and Git subdirectories, canonicalizes the validated
root passed to Graphify, and rejects top-level output indirection. Explicit code-only `extract` is the reviewed
bootstrap/testing surface; use it only in the intended standalone canonical/proof checkout, never to create an
alternate production graph. An unguarded `graphify update .` from a worktree builds a degenerate PARTIAL graph.
(That is the P3-E1 trap: the
"122-node / file-granular / `affected "fn()"` returns No node match" reading came from a worktree run;
the real main-checkout graph is thousands of nodes and **function-granular** — `affected "parse_qos_config()"`,
`explain`, `path` all resolve function symbols as advertised. Verified Graphifyy 0.9.47.) NB the
extractor indexes functions, classes and docstrings, NOT module-level assignments: a constant such as
`_RACE_RETRIES` is not a node, so `affected` on one returns nothing and that is a scope limit, not a stale graph.

Installed Graphifyy 0.9.47 also has two separately reviewed corpus/coverage residuals that local ignore syntax cannot
override. Its special saved-memory scan bypasses `.graphifyignore`/CLI excludes and can re-ingest
`graphify-out/memory/*.md`; its hard-coded noise pruning skips every directory named `build`, including authored
`master-reference/build/*.mjs` release owners. These are exact external BLOCK categories
`graph_corpus_memory_ignore_override` and `graph_corpus_authored_build_dir_pruned`, bounded by
`tests/test_graph_invariants.py`; do not treat a graph query as proof of absence across either corpus. A full forced
rebuild can remove a deliberately deleted privacy-offending node and heal incremental edges, but it cannot close
these two producer gaps. Reconcile the residual tests only when upstream makes explicit include/ignore policy
authoritative over both special scans.

Graphifyy 0.9.47's official JSON extractor applies its array branch to keys other than `extends`, producing
false `extends` edges, and its report summary counts structural-only communities as shown even though navigation
and sections exclude them. `tools/graphify_guarded.py` requires the exact distribution version, import paths, and
reviewed extractor/reporter SHA-256 identities; applies both one-line corrections only in memory; verifies both
corrected SHA-256 identities; and rebinds all five live extractor aliases plus the reporter's live `generate`
alias before entering the CLI. The official AST-cache namespace
does not bind extractor bytes, so the launcher preserves but never reads or writes JSON cache entries (including
mixed-case `.JSON` suffixes). `--probe` attests the exact overlays, isolated `-I` process, `-B` bytecode-write suppression,
case-fold-safe cache bypass, sanitized ambient `GRAPHIFY_*`/`GIT_*` controls and executable lookup, and one-worker
boundary. Every producer also holds the same OS-backed output lock; recursive reparse points and regular-file
hard links under `graphify-out/` are rejected. Any mismatch exits
before a Graphify command can mutate the graph, and the installed package remains unchanged. Because 0.9.47's
parallel AST workers reload the on-disk
module, the launcher fixes `GRAPHIFY_MAX_WORKERS=1` and rejects `--max-workers`; guarded extraction trades cache
reuse and parallel speed for semantic closure. The command allowlist also rejects generic/semantic `extract`,
`--allow-partial`, `--no-gitignore`, output/global/live-source indirection, hidden `.graphify_root` reuse, and
every producer verb not listed above. The Stop receipt is local bookkeeping for wrapper exit 0, matching observed
HEAD/status endpoints, and the final graph digest. It is not signed source-to-output provenance, producer-warning or
corpus closure, and cannot exclude a concurrent writer changing and restoring source bytes during extraction. This
bounds those two corrections only—it is not verification of the rest of the wheel or its transitive dependencies.

Rules:
- For codebase questions, run `py -3.12 -m graphify query "<question>"` first. Use `py -3.12 -m graphify path "<A>" "<B>"`
  for relationships and `py -3.12 -m graphify explain "<concept>"` for a focused node + its neighbors. These return a
  scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep.
- Use the ADVANCED surface (it is underused — reach for it, don't default to grep sweeps), ALL offline/AST-only:
  **`py -3.12 -m graphify affected "<symbol>()"`** is the highest-value verb — reverse blast-radius BEFORE editing a
  parser / detector / shared symbol, so every downstream caller + deliverable is shown FIRST (directly attacks the
  recurring parser↔detector / format-fidelity drift bug class). Plus the MCP tools: `god_nodes` (the core
  abstractions before a refactor), `query_graph`/`shortest_path` (enumerate every call/render site before a
  cross-surface change so it isn't applied to only some), `graph_stats` + `diagnose multigraph` (health),
  `benchmark` (the 5–15× token-reduction win).
- Offline NAVIGATION (replaces the never-existent wiki): `py -3.12 -m graphify tree` → graphify-out/GRAPH_TREE.html
  (D3 collapsible tree) and `py -3.12 -m graphify export callflow-html` (Mermaid call-flow); `GRAPH_REPORT.md` for the
  broad architecture review; `god_nodes` is the fastest map of the core abstractions. **The report is a
  derivative, not an SSOT:** unguarded Graphifyy 0.9.47 can count structural-only communities as “shown”; the guarded
  producer corrects that summary formula in memory. Before using report summary coverage as evidence, run
  `py -3.12 -m tools.verify_graph_report graphify-out/graph.json graphify-out/GRAPH_REPORT.md` and require exact PASS.
  An older/unpatched report remains BLOCK while the separately validated `graph.json` stays available for
  query/compiler use. An input/graph-invalid receipt establishes no such validity. The verifier is
  deliberately bound to the observed 0.9.47 file/stub predicate; reconcile it explicitly when the external producer
  changes.
- EGRESS — do NOT use in this air-gapped repo (they break the no-egress doctrine): `graphify add <url>` (fetches
  URLs), `graphify label` (calls an LLM — forbidden even via a local backend: it would plant LLM-derived
  nodes, breaking the AST-only invariant above, which the local-Ollama carve-out does not license), and the
  MCP `get_pr_impact` / `list_prs` / `triage_prs` (hit live api.github.com — and GitHub is paused). Every other verb (query/path/explain/affected/tree/export/diagnose/
  update/cluster-only) is fully offline.
- Keeping the graph current: after any visible repository change, the Stop hook runs a full AST corpus scan/update
  (cache hits still apply; no API cost), because that is the only rename/removal-safe trigger across Graphify's
  mixed corpus. A persistent untracked, unsupported artifact can therefore cause a bounded redundant full scan on
  each Stop until it is ignored or removed. A MANUAL `py -3.12 -I -B tools/graphify_guarded.py update .` may REFUSE
  ("fewer nodes than existing — missing chunk files from a previous
  session"); that is graphify's SAFETY GUARD, not corruption — do NOT `--force` past an ACCIDENTAL shrink (it
  would drop good nodes). The one legit `--force` is an INTENTIONAL de-pollution: after adding non-source dirs
  to `.graphifyignore` (the tool's own "use after refactors that delete code" case), back up graph.json, run
  the guarded `update . --force`, then verify the only nodes dropped are the excluded paths (precedent: 2026-07-03 cleanup
  removed ~1.9k scratch/side-engagement nodes; 2026-06-25 removed the `_ref/` copy).

  **Known incremental-rebuild limitation (current producer residual, not a claim that the present graph is
  truncated):** Graphify's incremental `changed_paths` rebuild can retain the full node census while evicting
  cross-file edges for a re-extracted file. `built_at_commit` records the last topology write (a successful
  topology-neutral scan intentionally leaves it unchanged), and it and node count therefore do not prove edge
  completeness. Consumers must report missing declared edges, and a reference/release build must first run a
  full `py -3.12 -I -B tools/graphify_guarded.py update .`, which heals this producer state. Executable evidence:
  `cisco_toolkit/d10_eval_set.py` and
  `tests/test_d10_eval_set.py::test_verify_multi_hop_edges_reports_on_an_edge_truncated_graph`.

## Single source of truth (SSOT)

Before hardcoding or restating ANY shared fact (device counts, VLANs, versions, #decisions, prices),
consult **`docs/ssot.md`** — the project-wide registry mapping every fact-domain to its ONE authoritative
owner ("one index, many owners", not a mega-file). Read the fact from its owner; a copy is a *cache* and
must cite the owner. Assessment headline facts carry the mechanical contract (`cisco_toolkit/ssot.py` +
`docs/ssot-contract.md`, CI-enforced via `ssot.reconcile`); `tests/test_ssot_registry.py` guards the
registry's own pointers from rotting. Adding a new source of truth = register it in `docs/ssot.md`, and
add a reconcile guard if it overlaps an existing fact. This is Law 1 of the Deliverable Excellence Standard.

## Knowledge base (two-store rule — ADR 0001)

Career/domain knowledge lives in the personal vault at `C:\Vaults\brain`; this repo + graphify own code and
engagement knowledge (`docs/decisions/0001-two-store-knowledge-architecture.md`). Repo sessions NEVER write the
vault — client-generic lessons are captured via `/retro` as `!lesson` entries in `docs/log.md` tagged
`bridge-candidate`, and a separate vault-cwd session promotes them with the vault's `/ingest` (its Rule-3 gate
strips client identifiers). Engine facts on wiki pages cite the symbol and defer to graphify, never restate
behavior. Reading vault pages from repo sessions is NOT granted (would need an ADR-0001 amendment).

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
- **Traffic Assurance (opt-in):** add `--traffic-intents <flows.json>` to a full assessment run (not `--compare`/`--trend`) to evaluate a finite catalog of exact IPv4 TCP/UDP five-tuples once across the scoped RIB, stateless interface ACLs, observed per-hop MTU, ECMP consistency, requested forward/return directions, and at most one synthetic node/site/link failure. The pipeline publishes the canonical `traffic_assurance_set/1` block and projects it into the workbook; after the one global redaction transform, every surface projects the transformed precomputed result and MCP performs exact lookup only. Positive routing/configuration claims require current-run marked custody, the `scoped_route_projection/1` receipt, exact-type content bindings, and no applicable modeled or categorical-unmodeled match from `parse.FORWARDING_GATE_SYNTAX_REGISTRY`; that registry is a bounded syntax denominator, not proof that every vendor forwarding feature is modeled. A JSON-loaded custody block is audit evidence only and cannot self-certify recomputation. This is synthetic control-plane analysis—not observed traffic, a stateful firewall/NAT engine, application proof, or field validation.
- **Validate cutover:** `cisco-assess --compare OLD.snapshot.json NEW.snapshot.json --output Diff.xlsx`; campaign trend: `--trend snap1 snap2 …`.
- **Universal architecture coverage** (both ingestion channels — see `docs/universal-architecture-coverage.md`): 46 coverage-honest architecture-class detectors across 27 classes (the in-code `_ARCH_COVERAGE_REGISTRY` is the authoritative count — probe-ids across class axes, reconciled by `tests/test_ssot_registry.py`) spanning SSH `show`-text (SD-Access/LISP, TrustSec/CTS, DMVPN, IPsec, BFD, IPv6, SP/MPLS, switch-native, firewall, + multi-vendor Arista/Juniper/FortiGate) **and** JSON controller/mgmt REST (Cisco ACI/APIC, Catalyst SD-WAN/vManage, ISE, FMC, + cloud). Controller evidence: collect through the live `rest_collect.CONTROLLER_COLLECTORS` denominator (`apic|vmanage|ise|fmc`) via `python -m cisco_toolkit.rest_collect <controller> --url https://… --user <ro> --password-env CISCO_REST_PASS --out-dir <dir>` (opt-in, never auto-runs; dedicated read-only RBAC is the hard control; the only non-GET requests are authentication logins), then analyze with `--no-collect`. Coverage map is published as `snap['architecture_coverage']` (read by the explorer ✎Design + webapp); ACI migration move-groups in `design_blueprint.target_state.aci_move_groups`.
- **Deliverable generators** (`cisco_toolkit/`): design, mop, crd, engagement, archreview, ops, runbook, deck, html (explorer/diff/campaign), excel (workbook). Toggle with `--no-html` (explorer), `--no-docx` (runbook), `--no-pptx` (deck), and `--no-design`/`--no-mop`/`--no-crd`/`--no-engagement`/`--no-opshandbook`/`--no-archreview`; the workbook is always produced (there is no `--no-runbook`/`--no-deck`/`--no-excel`).
- **Atlas — the portable field app** (`portable/`, ADR-0004; P0–P3 shipped): the whole platform as a one-folder Windows bundle that runs from a USB stick with no Python on the host. `Atlas.exe` is the ONE door — it serves AssessHub *and* is the engine CLI via the `--run-engine <engine argv>` sentinel (there is no separate `cisco-assess.exe` on the stick). Build + smoke: `python portable/build_atlas.py`; lay out/update a stick: `portable/make_stick.ps1 -Dest E:\` (re-running IS the update: everything replaced except `data\`). Field commands: `Atlas.exe --selftest` (fails loud on the silent-degrade assets) and **`Atlas.exe --redact-folder <collection> --out <dir>` [`--redact-collection`] [`--reuse-out`]** — the share-safe deliverable set, synthesizing the template/devices.json the engine requires and *verifying* the result before reporting success. Verification is two-sided: the redaction actually RAN, and the document family is COMPLETE (every engine deliverable writer is fail-soft, so a short set otherwise exits 0 looking whole — `docmeta.py :: ARTIFACT_SPECS` owns the lifecycle and its derived `CLI_ARTIFACT_SUFFIX` view owns what a complete CLI run produces; `cutover`/`nrfu` are AssessHub-rendered and are NOT part of it, while conditional PIR is post-execution only). Exit `0` = complete + verified, `3` = produced but short (safe, just not all of it), `1` = failed, do not send. An `--out` folder that already holds a deliverable set is REFUSED before the engine starts (`--reuse-out` is the explicit escape) — otherwise another job's documents sit under this run's filenames, and redaction keeps hostnames. The store hardens itself at boot (integrity check + rotating backups in `data\backups\`); read `portable/README-FIELD.txt` before changing any of it — it is the engineer's only on-site documentation and is ratchet-tested (`tests/test_readme_field.py`).
- **Tests:** `python -m pytest -q` (`tests/` + `webapp/tests` are both in the default gate; run collection rather than caching a count). **graphify here:** read with `py -3.12 -m graphify query|explain|path`; source-extract only with guarded `update`, `watch`, or `extract <local-path> --code-only` forms above. Bump the release version in `pyproject.toml` only at tag time; never bump the decoupled schema version `cisco_toolkit.__version__`.

> **Automation already wired in `.claude/` for Claude Code:** a `Stop` hook (`verify-green.sh`) runs `pytest` after `.py` changes and blocks on an observed test failure or timeout; it allows the stop loudly when no working interpreter is available, while unreadable Git state remains a deliberate fail-open path. The graph refresh, session brief, recorder, and status helpers are maintenance/observability hooks and fail open. A second `Stop` hook probes the tracked producer guard, then refreshes graphify after any visible repository change; a failed probe or unreadable Git status leaves the graph untouched and warns while still allowing the turn to stop. A `SessionStart` hook prints this engagement's state; a status line shows version/branch/model. Codex does not execute these Claude hooks automatically — root `AGENTS.md` carries the shared bootstrap.

> **Trust boundary — "read-only" is a trust model, not a sandbox.** The four analyst agents are constrained by their tool allowlist (no `Edit`/`Write` tools) + interactive permission prompts + their prompt mandate. But any agent holding `Bash` can run arbitrary python, and per Claude Code docs per-command Bash scoping can't be expressed in `tools:` while Bash deny-rules are bypassable — the OS `sandbox` is the only hard enforcement. So **keep the default permission mode (never `bypassPermissions`)** for these agents, so risky Bash (device writes, `git push`) still prompts you. The agents are designed to never attempt those; this is the backstop if one misreads intent.
