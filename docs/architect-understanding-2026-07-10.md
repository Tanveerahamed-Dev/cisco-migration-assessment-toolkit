# Architect Understanding — 2026-07-10 @ e3b2bd5

> Stage A artifact of `/architect-plan` (v5). Scope at initial dispatch: **brain/meta layer**
> (Dimension H held — engine scope was P0 interview question 1; answered **IN SCOPE** 2026-07-10,
> and the Dimension H report is appended below, dispatched at Stage B start per the command).
> Method: 9 read-only Explore workers (A–H + R),
> graph-first, every claim cited; each worker filed a NOT-EXAMINED ledger (§ Confidence).
> In-flight while this ran: two spawned fix-sessions (D10 paired-power erratum + stale node count;
> memory_guard docstring ghost path) — their targets are flagged below, not assumed fixed.
> Severity: [BLOCKER] violates doctrine / breaks core function · [HIGH] address before feature work ·
> [MEDIUM] · [LOW].

## Consolidated blockers (the Phase 0 backlog, subject to Stage B)

- **BLK-1 [BLOCKER] Protected memory tier (D12) is bypassable with no RED test.** The guard is a
  mechanism with no live artifact: `tests/test_memory_guard.py:19-27` exercises a **synthetic
  in-memory store**; the only real-file read in the suite is CLAUDE.md (the doctrine owner), never
  the artifact. `cisco_toolkit/memory_guard.py` is imported by **no runtime path** — its only
  non-test reference is a string in `selfcheck.py:26`. Unguarded routes: (a) direct deletion of
  `protected-constraints.md` (vault-guard.sh:17 fences only `C:\Vaults\brain`); (b) the real
  consolidation pass (`anthropic-skills:consolidate-memory`, out-of-repo) never routes through
  `compact_preserving_protected`; (c) frontmatter flip `protected: true → false` — nothing inspects
  the artifact's frontmatter; (d) [HIGH] MEMORY.md index prune orphans the fact from native
  re-surfacing (session-brief.sh:76 counts, doesn't read).
- **BLK-2 [BLOCKER] Proposer ≠ verifier is prompt-text-only.** Roster convention + agent prose
  (`deliverable-qa-reviewer.md:7`, `nrfu-validator.md:18`, CLAUDE.md:80); no code prevents an
  author agent validating its own output.
- **BLK-3 [BLOCKER] Human-gated PPDIOO transitions are prose-only.** No generator refuses to run on
  a missing upstream artifact (guard-pattern grep across `cisco_toolkit/**` clean);
  `webapp/backend/gates.py:45-59` **records** go/no-go decisions, blocks nothing;
  `engagement.py:39-52` GATE_SEQUENCE is a campaign record board, not the PPDIOO phases.
- **BLK-4 [BLOCKER-for-comprehension] No merge gate exists on this machine.** `verify-green.sh`
  (settings.json:44-53) is an **agent turn-stop**: `.py`-only, fail-open on timeout, bypassable
  (touch no .py / disable hooks). `.git/hooks` = graphify rebuilds only (fail-open); no
  pre-commit/pre-push; `core.hooksPath` unset. Real merge-blocking lives off-machine (GitHub branch
  protection + CI) and is **unverifiable offline**.

## Dimension A — Knowledge layer

- Graph schema verified from `graphify-out/graph.json` directly (matches owner GRAPH_REPORT.md:8):
  **6,974 nodes / 11,887 links / 501 communities**, 12 relation kinds, `_origin=ast` on 6,962 nodes —
  **no-LLM-derived-nodes doctrine HOLDS** (the 1,962 `rationale` nodes are AST-extracted docstrings,
  a [LOW] naming collision with the removed LLM layer, not its return).
- Freshness: `built_at_commit e3b2bd5 == HEAD` (fresh today). [MEDIUM] the only mechanical
  staleness check is **mtime-based** (`selfcheck.py:152-163`, >7d RED); commit-staleness
  (`built_at_commit==HEAD`) is enforced by no code. [MEDIUM] **no test validates graph.json at
  all** (schema/count/commit) — `tests/test_doctrine_graph.py` guards a different graph (the
  doctrine/design_advisor projection).
- SSOT machinery is real and layered: `ssot.py:37-52` CANONICAL_FACTS (14), `reconcile()`
  producer guard (:286-408), `tests/test_ssot_registry.py` structural guards incl. the 46/27
  arch-coverage reconcile (:113-134).
- [HIGH] **The SSOT registry itself carries false status lines** (Law-1 rot inside Law 1's own
  index): `ssot.md:40` claims "no live feed yet (no sweep run)" while `docs/intel/feed-2026-07-07.jsonl`
  is **tracked** with 93 real CISA-KEV Cisco CVEs (produced by the fenced egress lane —
  lane-compliant, registry-stale); `ssot.md:41` "no digest data yet" while
  `docs/vault-digest/digest-2026-07-07.jsonl` exists (10 entries; gitignored, so clean-clone true —
  drift on the owner machine only) [MEDIUM for the digest, HIGH for the tracked feed].
- [HIGH] **Doctrine wording conflict confirmed**: CLAUDE.md:9 "an LLM call = egress" (unqualified)
  vs ADR-0001 Am.1:58-63 local-Ollama-in-boundary; code sides with the ADR
  (`ollama_recall.py:7-8`). Needs a one-line local-carve-out edit in CLAUDE.md.
- [MEDIUM] "Signed" overstates: feed/digest signature is a **plain SHA-256 self-hash**
  (`intel_feed.py:32-49`) — integrity, not authenticity (no key/HMAC).
- Two-store boundary: **digest pipeline is BUILT end-to-end** (producer `research_lane/vault_digest.py`
  → Rule-3 sanitizer → signer → consumer `recall.py:load_vault_digest` verify-before-use), fenced
  mechanically by PreToolUse `vault-guard.sh` (Write/Edit/NotebookEdit — see BLK-1 note and E-map #8).

## Dimension B — Memory layer

- Store = native Claude Code auto-memory (11 facts + MEMORY.md index, own git repo, outside the
  tree). Write/update/retire and session-start re-surfacing are **native**, not repo code;
  `session-brief.sh:60-78` only measures rot (KB/lines).
- Protected tier: mechanism + CLAUDE.md-anchor reconcile are real
  (`memory_guard.py:36-45,98-187`; anchors verified present in CLAUDE.md). **Artifact is unpinned**
  → BLK-1 above.
- Ghost citation confirmed 3× (`memory_guard.py:5`, `docs/quality/learnings.md:42`,
  `protected-constraints.md:36` all cite the non-existent
  `.claude/scheduled-tasks/monthly-memory-consolidation`); [LOW] docs-only, fix-session in flight —
  but it means the docstring's claimed "protected-tier rule at the compression site" points at a
  site that doesn't exist (the real plugin's behavior is unverifiable from the repo).

## Dimension C — Brain / autonomy layer

- Instrument map (all verified in code): `eval_harness.py` — 7 grounded laws (:47-55), **no
  per-dimension weights** (score = passed/applicable, :375; multi-check laws implicitly weigh
  more); coverage-honest (`unverified` excluded, never green). `defect_panel.py` — D-01…D-12
  (:35-72), deterministic arm TNR=1.0 by construction (:323-338), `unlocalized_rejection_rate`
  anti-reject-everything guard. `calibration.py` — **calibration-gap** P(incident|READY) /
  P(clean|NOT_READY) (:150-186), D11 floor N≥5 REAL (:42,226), REAL-only (:224), propose-only
  (`applied=False` always). `ollama_judge.py` (root, outside the no-egress fence by design) —
  local-Ollama cross-family judge, default qwen3:4b (:40-41).
- [HIGH] **`judge_tnr` is a passive schema slot, not a gate**: defined in SCHEMA_KEYS
  (scorecard.py:39-40) but **never emitted by any writer** (parse_qa_verdict :132-141 and
  to_scorecard_row :108-117 both omit it → always null). PROVISIONAL exists only in prose
  (quality/README.md:20); **no code path downgrades or blocks a PROVISIONAL APPROVE**.
- [HIGH] **No ECE anywhere** (grep clean). "Per-dimension ECE" in the selfmem plan §1 (and in this
  command's own KNOWN STATE) is a **mislabel** of the calibration-gap metric.
- **Data reality (counted from files, 2026-07-10):** `scorecard.jsonl` = **3 rows** — (1) one
  deterministic eval_harness row, score 100, on a real AUTOFILLED deliverable; (2) one Claude-judge
  /qa APPROVE, score null, judge_tnr absent → PROVISIONAL; (3) one judge-baseline row
  **judge_tnr = 0.2** (< the 0.25 broken-instrument threshold — the sole LLM judge currently
  self-measures as broken; the deterministic arm is the only trustworthy quality datum).
  `pir_outcomes.jsonl` = **7 rows, 0 REAL** (all `source_class="fault-injected"`).
  `nightly_runs.jsonl` = **0 rows**. Scorecard has **no source_class field** — the KNOWN-STATE
  phrase "first REAL rows" is ambiguous against disk (see Reconciliation).
- [HIGH] **70/30 split + sealed holdout: NOT FOUND anywhere** in code/docs — the requirement's only
  owner is this command itself (see Reconciliation (b)). The repo owns sealing tech
  (`manifest.py` hash-chain, `precert.py` freeze token :252) but none is applied to a brain-layer
  holdout. Latent (loop is data-starved), but any future optimisation would run unsealed.
- [HIGH] **The immune system's scope is un-pinned**: `selfcheck.check_guards_nonvacuous`
  (:127-149) asserts guard-test files exist + contain "assert"; `GUARD_FILES` (13 entries, :25-33)
  membership is asserted by no test — dropping an entry AND its file leaves selfcheck GREEN.
  `__version__` has a genuine value pin (`test_version.py:6` == "3.23.0") but that test is **not in
  GUARD_FILES**; `ollama_judge.py` has no artifact pin (deletion caught only transitively at
  suite-run time).
- D11 floor frozen at N=0 REAL **confirmed by design** (calibration.py:226; surrogate rows can
  never unlock tuning).

## Dimension D — Orchestration

- PPDIOO phases exist as **roster + prose only** → BLK-3. Agent tool allowlists are a clean
  proposer≠verifier split (5 read-only analysts without Edit/Write; 3 authors with) — but
  enforcement is convention (BLK-2).
- [MEDIUM] **No result-schema validation** of subagent returns anywhere (only `parse_qa_verdict`
  text-matching, used to record — not to gate).
- Merge gate today → BLK-4. **CI nuance:** `.github/workflows/ci.yml` is complete (ruff, py3.10–3.14
  matrix incl. Windows, mypy, `--cov-fail-under=85`, build smoke) and **local evidence shows active
  historical use** (merged PRs #302/#303 in log; tags v3.26.0–v3.30.0 pushed; origin =
  github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit) — but whether Actions currently
  executes and whether branch protection requires it are **unverifiable offline**. P0 interview item.
- [MEDIUM] Dead-but-wired config: `SubagentStop → scorecard-append.sh --hook`
  (settings.json:66-77) never fires under the Agent SDK (confirmed in code comments
  scorecard.py:501-518 and qa.md:11); the live path is the `--record` message arm (commit 4f627d3).

## Dimension E — Guardrail enforcement map (strongest rung that holds TODAY)

| # | Constraint | Rung today | Key evidence | Gap | Sev |
|---|---|---|---|---|---|
| 1 | No-egress | code+test (pipeline source) | attestation.py:48-195 AST import-walk; test_readonly_and_no_egress.py | guards shipped source, not agent runtime Bash; CI dormant → live gate = fail-open Stop hook | OK/note |
| 2 | Read-only devices | code+test + tool allowlist | attestation READ_ONLY_CMD grammar; 5 analyst agents lack Edit/Write | all agents hold Bash → floor is permission mode, **eroded** (see below) | OK/layered |
| 3 | Proposer≠verifier | **prompt-only** | roster prose only | no code enforces author≠reviewer | **BLOCKER** |
| 4 | Protected tier | code+test (**mechanism only**) | memory_guard + synthetic tests | artifact unpinned; no live consolidation routes through it | BLK-1 |
| 5 | Coverage-honesty | code+test (strong) | precert tri-state :89-101; calibration REAL-only fail-safe; registry-owns-count test | engine-mechanical; agent narration prompt-only | OK |
| 6 | SSOT | code+test (CI-defined, locally-enforced today) | ssot.reconcile; test_ssot_registry | "CI-enforced" claim depends on paused/unverifiable CI; registry status-line rot (Dim A) | OK/note |
| 7 | Human gates | **prompt-only** | CLAUDE.md:64-65 prose | nothing blocks gate advancement | **BLOCKER** |
| 8 | Two-store | hook | vault-guard.sh:17-24 (Write/Edit/NotebookEdit, exit 2) | **Bash `cat > /c/Vaults/brain/…` bypasses it** — and `cat > *` is pre-approved | OK-ish/note |

- [HIGH] **`settings.local.json` erodes the doctrine's own backstop**: `Bash(python -c '*')` and
  `Bash(cat > *)` are pre-approved (no prompt) — the CLAUDE.md:93 premise "risky Bash still
  prompts you" does not currently hold for arbitrary python or file writes (affects #1/#2/#8).

## Dimension F — Gaps & debt

- **Marker census ≈ 0** across scoped source (TODO/FIXME/HACK/XXX/stub/commented-out/bare-except all
  zero) — unusually disciplined. 35 typed `except…: pass` fail-open swallows ([LOW], doctrine-
  consistent but unlogged).
- [MEDIUM] Version relationship: pyproject 3.30.0 vs `__version__` 3.23.0 is **intended decoupling**
  (CLAUDE.md engine-entrypoints rule) — the worker's [HIGH] is downgraded with that doctrine
  context — but the *intent is not encoded*: `test_version.py` pins the schema value without
  GUARD_FILES membership, and nothing guards/documents the pyproject side mechanically.
- [MEDIUM] `webapp/frontend/` (React/TS) has **zero tests** (backend well-covered).
- [MEDIUM] The 3 largest engine modules (`analyze.py` 6467L, `design_advisor.py` 4658L,
  `design_kb.py` 4006L) have no dedicated unit harness — integration-only coverage (116/60/17
  importing test files; proxy, not line coverage).
- Config clean: all wired hooks exist; requirements ↔ pyproject aligned (extras model).

## Dimension G — Retrieval layer (built vs designed)

- [HIGH] **A built retrieval lane EXISTS — "designed-only" is false as a blanket**: `recall.py`
  ships RRF k=60 (:38-46), hybrid fusion (:164-170), TF-IDF lexical (:49-70), graphify/vault/Ollama
  lane wrappers, and an **8-query MRR experiment** (:174-215), unit-tested. This is the Phase-5
  experiment — distinct from the D10 60-query falsification eval.
- D10 eval stack **confirmed designed-only, four ways**: BM25/bm25s, sentence-transformers,
  faiss-cpu, pytrec_eval, scipy/sklearn all absent from pyproject/requirements/code; no 60-query or
  15-anchor fixture; **no pre-registered thresholds file**; **no persisted retrieval numbers**
  anywhere in docs/quality/.
- [HIGH] `ollama_judge.py` judges the **defect panel** (APPROVE/REJECT over defect classes) — the
  D10 *retrieval-relevance* judge (0-3 graded, dual-prompt-min, κ≥0.70 ∧ acc≥0.80 anchor gate) is
  designed-only.
- [HIGH] **The dense-lane precondition cannot run today**: no real-query log of any kind exists to
  classify (D10 §5 requires 30).
- [MEDIUM] **Eval-corpus ≠ retriever-corpus divergence**: D10's eval is graph+docs; the built
  retriever fuses a vault-digest lane; ADR-0001 Am.1 frames the eventual corpus as
  graph⊕docs⊕digest. The eval as designed would not measure the shipped fusion.
- [LOW] One of D10's two gates is materially met (digest exists; Ollama reachable at least once —
  judge ran, scorecard.jsonl row 3); nothing pins the Ollama install.
- graphify's ranking engine is **external to the repo** (subprocess + MCP; unauditable here).

## Dimension H — Engine & deliverables (dispatched at Stage B start; engine confirmed IN scope)

- **No [BLOCKER]s** — no-egress / read-only / coverage-honesty / SSOT / proposer≠verifier doctrine
  intact and actively guarded across the examined engine surface.
- [HIGH] **Parser↔detector FIELD contract unbound** (the repo's own named recurring bug class):
  `tests/parser_examples.py` pins spot-fact fields for **21 of 105** `parse_*` functions
  (`cisco_toolkit/parse.py`, ~4,514 lines); **82 detectors** (`def _d_` in
  `design_advisor.py`) are not field-bound. Strongest existing guard =
  `tests/test_detector_schema.py:95-121` (descriptor `cited_fields` leaf-resolution) but it binds
  only the 32 curated schema descriptors — and just 9 of those carry a leaf-resolvable
  `section[].field` citation (owner: `cisco_toolkit/detector_schema.py::compute_detector_schema`;
  count corrected by round-2 QA). Supporting guards: `test_parser_contracts.py` (dispatch),
  `test_parser_return_shapes.py` (container shape + build.py defaults), `test_parser_crosscheck.py`
  (7 commands vs ntc-templates). Net: a parser field rename can silently break an un-covered
  detector.
- **Coverage registry exemplary**: `_ARCH_COVERAGE_REGISTRY` (design_advisor.py:4590-4618) = 27
  axis rows, 46 = Σ probe-ids; `compute_architecture_coverage` (:4621-4658) publishes
  `snap['architecture_coverage']` coverage-honestly (non-dict axis → `not-observed`, never
  `clean`); SSOT-guarded (test_ssot_registry.py:113-134 — caught the live 40/23→46/27 drift);
  consumers all read the one published axis.
- **Generators**: all 10 engine generators carry dedicated tests; PIR is a **webapp** deliverable
  (`webapp/backend/pir_docx.py`) with indirect coverage only.
- [MEDIUM] **deliverable-excellence P2/P3 table is STALE in the good direction** — landed:
  archreview.py:1091-1093 (canonical_facts), engagement.py:538-550 (gate_record + rationale),
  ops.py:502-509 + :86-93, explorer provenance (html.py:539-543,:743). Genuinely open: excel
  Exec-Summary provenance row (~:3686-3691, head-only inference) + deck.py title footer (:185-187).
- [MEDIUM] **--compare/--trend has no schema-version gate** (COLLECT_PARSE_V3_23_0.py:1631-1657;
  html.py:71 names the hazard as a fail-soft comment): two snapshots of divergent schema/
  script_version diff silently; the `"/1"` schema tag is never compared between the pair.
- **Webapp**: backend covered (test_backend, test_section_registry, test_security_hardening,
  test_audit5_webapp_totality); **frontend zero tests confirmed** (package.json scripts =
  dev/build; tsc is the only gate). Section drift mechanically guarded
  (webapp/tests/test_section_registry.py:59-108). Ingest = snapshot upload + raw collection ZIP
  through the engine subprocess (size-capped); the JSON controller-REST channel is engine-side.
- **Snapshot schema**: test_version.py pins literals only (`__version__`=="3.23.0",
  script_version=="V3.23.0") — single-sourcing, not a compat guard.
- [LOW] docs/wave-slices/manifest.json per-object axis/cmd misaligned vs key (tracking artifact,
  not shipped code).
- **Debt feed**: docs/universality-gap-register.md:5 = **278 build items (140 P1 / 91 P2 / 47 P3)**
  — largely superseded by the arch-wave build-out (overlay/mpls/aci/sdwan/lisp/cts/dmvpn/ipv6/pim/
  copp now in the coverage registry); genuine residual = collection-channel gaps (ACI/SD-WAN JSON
  export, telemetry) + `parse_port_security_detail` NX-OS (parser-format-fidelity.md:71). Top-5
  historical P1 concentrations: NX-OS VXLAN-EVPN, ACI evidence channel, SP/MPLS core state,
  SD-Access LISP/CTS, Catalyst SD-WAN collection.
- **NOT-EXAMINED (H)**: write_diff_workbook/write_campaign_trend full bodies (schema-gate absence
  is grep-based inference); excel.py below :3695; the 82 detector bodies individually;
  webapp security-test internals; arch-wave slice bodies; tests/test_parsers.py.

## Known-state reconciliation (worker R; status: C=confirmed-in-code, D=designed-only, NF=not-found, S=stale)

| Known-state claim | Status | Evidence |
|---|---|---|
| defect_panel D-01…D-12 + TNR | **C** | defect_panel.py:36-69, :294-338 |
| calibration readiness→outcome, D11, propose-only | **C** | calibration.py:42,210-234 |
| calibration "per-dimension ECE" | **NF (mislabel)** | grep ECE/Brier = 0; metric is calibration-gap |
| scorecard judge_tnr field + PROVISIONAL | **C (passive)** | scorecard.py:34-40; never emitted; prose-only semantics |
| scorecard --record arm | **C** | scorecard.py:485-531; 4f627d3 |
| ollama_judge.py root + tests | **C** | tests/test_ollama_judge.py (15 hermetic tests) |
| memory_guard D12 tier | **C (mechanism) / artifact unpinned** | BLK-1 |
| "scorecard has first REAL rows" | **S/ambiguous** | 3 rows on disk; no source_class; 1 deterministic real-deliverable row, 1 PROVISIONAL, 1 judge-baseline TNR 0.2 |
| PIR N=7 surrogate / 0 REAL | **C** | pir_outcomes.jsonl (all fault-injected) |
| 50–100 REAL + 70/30 sealed holdout | **NF in repo plans — owner is this command itself** | contradicts repo's N≥5-floor discipline → P0 interview Q4 |
| ECE-reduction 28–35% (adversarial framing) | treat-as-reported (as labelled) | no in-repo backing; closest ≠ same claim (README:87) |
| D10 60-query eval | **D** (with recall.py qualification above) | Dim G table |
| D10 gated on Ollama + digest | **S in part** | digest exists; Ollama ran once; ADR Am.1 "not installed" stale vs ssot.md:41 |
| Pipeline human gates | **prose-only** | BLK-2/BLK-3 |
| Merge gate = Stop hook today | **C (and weaker than assumed)** | BLK-4; CI actively used historically, execution unverifiable |
| Prior-plan landscape | 8 docs + 3 ADRs mapped; newest sequencing = remaining-work (07-10 addendum); v4-final = standing decision ledger; MASTER_PLAN partially superseded (its §2/§4.1-4.4/§5 untouched by 07-08 plans) | worker R ledger |

## Confidence map

| Dim | Confidence | What would raise it |
|---|---|---|
| A | HIGH (graph.json + doctrine texts read directly) | git-log dating of the two SSOT status-line drifts; graphify MCP graph_stats cross-check |
| B | HIGH | reading the out-of-repo consolidate-memory SKILL.md (does it honor `protected:true`?) — would soften BLK-1 routes (b) |
| C | HIGH (counts re-derived from files) | running the guard suites; reading attestation.py scan-root line-by-line |
| D | HIGH local / MEDIUM CI-execution | `gh run list` + branch-protection query (needs network) — P0 interview |
| E | HIGH | harness-level Bash sandbox posture; whether local allowlist propagates to subagents |
| F | HIGH census / MEDIUM coverage-map (import-count proxy) | pytest-cov run for true per-module coverage |
| G | HIGH | reading graphify's external source; git-history sweep for deleted eval assets |
| H | HIGH (contracts, registry, frontend, debt feed) / MEDIUM (excel/deck open-status, diff-gate absence — grep-based) | reading write_diff_workbook + excel Exec-Summary bodies end-to-end; a suite run |
| R | HIGH spot-checks / MEDIUM exhaustive per-plan | opening deliverable-excellence P2/P3 targets; pytest green-run |

## Interview

### P0 — cannot plan without (Q1–Q4 delivered via AskUserQuestion; Q5–Q7 answer inline)
1. **Engine scope** — dispatch Dimension H or hold the plan to the brain layer?
2. **What "winning" looks like** — personal force-multiplier / client deliverable factory /
   product-platform / research testbed?
3. **Hard deadlines** — and, same breath, the real GitHub/CI status (paused? active? branch
   protection required-to-merge?) — local evidence conflicts with the "paused" narrative.
4. **Phase-1 labelled-data policy** — repo's existing N-floors vs adopt 50–100 + 70/30 sealed
   holdout vs hybrid (floors now, split activates at N≥50 REAL).
5. Resource envelope: tokens/compute ceiling per week, and human-review bandwidth (hours/week) for
   the NEEDS_HUMAN_REVIEW queue.
6. Risk appetite for Phase-0 residuals: which known bypasses (e.g. Bash-holding agents, local
   allowlist pre-approvals) are you willing to formally accept vs want closed?
7. When is the first REAL post-cutover PIR realistically expected (feeds Phase 1's unfreeze)?

### P1 — would significantly change the plan
- Should the SSOT registry's two false status lines (intel feed / digest) be fixed as Phase-0 tasks
  (they're 2-line doc edits) or batched with a registry-freshness guard?
- Is the `settings.local.json` pre-approval erosion (`python -c`, `cat > *`) intentional
  convenience or should Phase 0 remove it?
- Eval-corpus ≠ retriever-corpus (digest lane) — should D10's eval add a digest lane, or should the
  shipped retriever's digest lane be excluded from what the eval certifies?
- CLAUDE.md "LLM call = egress" carve-out edit — trivial but touches the doctrine owner; who edits it?

### P2 — refines but does not change
- Naming: rename graph "rationale" nodes to avoid collision with the removed LLM layer.
- Wire commit-staleness (built_at_commit==HEAD) into selfcheck alongside the mtime check.
- Log the 35 silent `except: pass` sites at debug level.
- webapp frontend test harness; unit harnesses for analyze/design_advisor/design_kb.

*Generated by /architect-plan Stage A, 2026-07-10, HEAD e3b2bd5. Stage B will not start until the
P0 answers land.*
