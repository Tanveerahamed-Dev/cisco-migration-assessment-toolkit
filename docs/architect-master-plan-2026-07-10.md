# Architect Master Plan — 2026-07-10 @ e3b2bd5

> Stage B artifact of `/architect-plan` (v5). Upstream gate input: docs/architect-understanding-2026-07-10.md
> (Stage A dimensions A–G+R, PLUS the Dimension H report appended to that same artifact after the
> engine-scope answer — H was dispatched at Stage B start per the command) + the P0 interview
> answers of 2026-07-10:
> **engine IN scope · mission = all four rungs (see DEC-001) · GitHub upgraded to Pro (CI/branch
> protection now available) · Phase-1 data policy = hybrid (floors now, sealed 70/30 activates at
> N≥50 REAL)**. Unanswered P0s carried as explicit assumptions (DEC-009, NEEDS_HUMAN_REVIEW).
> Every count in this plan was re-derived from files at e3b2bd5 and is volatile — re-derive, never
> quote forward. This plan is a cache; owners are cited inline (docs/ssot.md Law 1).

---

## 1. Doctrine audit table

Rungs (strong→weak): OS sandbox/permission mode → tool allowlist → code+CI-gated test → hook →
prompt text → absent. TARGET = strongest rung FEASIBLE for the constraint's nature.

| # | Constraint | Rung TODAY (evidence) | TARGET rung | Gap | Sev |
|---|---|---|---|---|---|
| 1 | No-egress | code+test on pipeline source (attestation.py AST-walk; test_readonly_and_no_egress.py) | same + CI-required check (Pro) | CI re-attach (P0-4); agent-runtime Bash egress tops out at permission mode — residual, human-accept (P0-9) | MEDIUM |
| 2 | Read-only devices | code+test + analyst tool allowlists | same + un-eroded permission mode | settings.local.json pre-approves `python -c '*'`, `cat > *` — backstop eroded (P0-7) | HIGH |
| 3 | Proposer≠verifier | **prompt-only** (roster prose) | code check at record time (provenance fields) + guard test; full enforcement infeasible → declared residual | **BLOCKER** → P0-2 |
| 4 | Protected memory tier | code+test, **mechanism only** (synthetic stores; guard imported by no runtime path) | runtime selfcheck artifact reconcile + consolidation-path wiring | artifact unpinned; 3 unguarded bypass routes | **BLOCKER** → P0-1 |
| 5 | Coverage-honesty / never-fabricate | code+test, strong (precert tri-state; calibration REAL-only; registry-owns-count) | same + registry-freshness guard | the SSOT registry itself carries false status lines | HIGH → P0-5 |
| 6 | SSOT | code+test, locally enforced; "CI-enforced" claim currently unbacked | CI-required check (Pro) | P0-4 + P0-5 | MEDIUM |
| 7 | Human-gated transitions | **prompt-only** (no generator refuses a missing upstream; gates.py records, blocks nothing) | gate-state artifact + generator refusal with logged human override | **BLOCKER** → P0-3 |
| 8 | Two-store boundary | hook (vault-guard.sh — Write/Edit/NotebookEdit only) | hook extended to Bash writes | `cat > /c/Vaults/brain/…` bypasses; `cat > *` pre-approved | MEDIUM → P0-8 |

Human-process constraints (2, 7, 8) top out at hook/test-assisted human process — the plan says so
rather than pretending code can hold them alone.

## 2. Architectural assessment (per dimension; full evidence in the understanding doc)

- **A Knowledge — sound core, unguarded periphery.** Graph healthy (6,974 nodes, AST-only doctrine
  holds); SSOT machinery layered and real. Liabilities: graph.json has zero tests and only an
  mtime staleness check; the registry's own status lines rotted (intel feed, digest) — Law 1
  failing inside Law 1's index. Must change: P0-5, P3-K1/K2.
- **B Memory — a guard with nothing to guard.** memory_guard mechanism + CLAUDE.md anchor
  reconcile are genuinely good; but no runtime imports it, the artifact is unpinned, and the real
  consolidation pass lives out-of-repo. Must change: P0-1 (the plan's single most important task).
- **C Brain — instruments built, trust chain broken at the LLM link.** Deterministic arm
  (eval_harness, defect_panel TNR=1.0) is the only trustworthy quality datum; the sole LLM judge
  self-measures TNR 0.2 (< 0.25 broken threshold); judge_tnr is a passive field no writer emits;
  PROVISIONAL is prose-only; GUARD_FILES membership un-pinned. No ECE exists (plan-doc mislabel of
  calibration-gap). Must change: P0-6, P1-1..P1-4.
- **D Orchestration — clean roster, no mechanical gates.** Allowlist split is right; PPDIOO gates
  and author≠reviewer are convention; no merge gate on-machine; SubagentStop config is dead under
  the SDK. Must change: P0-2, P0-3, P0-4; P3-D1 (dead config removal).
- **E Guardrails — engine strongly held, agent-runtime held by an eroded backstop.** See table §1.
- **F Debt — unusually clean.** Marker census ≈ 0. Real debt: webapp frontend zero tests; 3 largest
  modules integration-only; version-decoupling intent not encoded. P3 backlog.
- **G Retrieval — a built lane the design doesn't measure.** recall.py (RRF/TF-IDF/8-query MRR)
  is BUILT; the D10 60-query falsification stack is designed-only; the dense-lane precondition is
  unrunnable (no real-query log exists); eval-corpus (graph+docs) ≠ retriever-corpus
  (graph⊕docs⊕digest). Must change: P2 pre-tasks (query logging, corpus decision DEC-006).
- **H Engine — the disciplined half; one structural contract gap.** All 10 engine generators
  tested; coverage registry exemplary (46/27, SSOT-guarded, coverage-honest). Liabilities:
  parser↔detector FIELD contract unbound (21/105 parsers pinned; 82 detectors not field-bound —
  the repo's own named recurring bug class); --compare/--trend silently diffs mismatched schema
  versions; deck/excel provenance genuinely open; frontend untested. Must change: P3-E1..E5.

## 3. Prior-plan disposition (13 plan docs + 3 ADRs — this plan becomes the active work-plan index)

| Doc | Disposition | Where / boundary |
|---|---|---|
| MASTER_PLAN_2026-07-05 | **ABSORBED** | trust/calibration frontier superseded as-built; its §2 secure&tidy, §4.1–4.4, §5 platform/vault land as P3 backlog feed (P3-M*) |
| deliverable-excellence-plan | **STILL-AUTHORITATIVE** for the Excellence laws (sole owner, ssot.md:36) | implementation status reconciled 2026-08-07 (P0–P2 and visible P3 provenance shipped); law ownership unchanged |
| autonomous-brain-plan-v4-final | **STILL-AUTHORITATIVE** as the decision ledger (D1–D13) | roadmap phases ABSORBED (built); decisions bind this plan (D6 packs≠agents, D11 floor, D12 tier) |
| autonomous-brain-v3-validation | **ABSORBED** (evidence base; external figures stay treat-as-reported) | — |
| agent-brain-selfmem-upgrade | **ABSORBED** | its genuine delta (SelfMem write-vocab, deferred SQLite index per ADR-0003) → P3-B1; its "per-dimension ECE" label corrected (calibration-gap) |
| best-possible-plan | **SUPERSEDED** (its own successor is remaining-work) | historical record of Act 0 |
| remaining-work-plan (+07-10 addendum) | **ABSORBED** — its Act-1 critical path IS Phase 1 here | its 2026-08-05 shadow-PIR/lab-cutover decision date carried as R2/owner-human |
| d10-retrieval-eval-design | **STILL-AUTHORITATIVE** for the Phase 2 protocol | erratum fix in flight (spawned task); Phase 2 will not run until it lands |
| ADR-0001 (+Am.1), 0002, 0003 | **STILL-AUTHORITATIVE** (decisions of record) | Am.1's "Ollama not installed" line is stale vs ssot.md:41 — P0-5 sweep fixes the line, not the decision |
| docs/universality-gap-register.md | **STILL-AUTHORITATIVE** as the historical gap census — OWNER of the 278 figure (:5) | operationally superseded by the arch-wave build-out; frozen/annotated by P3-M0 |
| docs/absolute-universal-roadmap.md, universal-best-roadmap.md, orchestration-best-roadmap.md | **ABSORBED** (historical roadmaps; territory now owned by the coverage registry + this plan's P3 backlog) | no active claims carried |
| docs/autonomous-brain-plan-2026-07-06.md (v3 base) | **ABSORBED** via v4-final (which supersedes v3's open questions per its own header) | evidence base only |

## 4. Design decisions register

| ID | Question | Decision + trade-offs | Conf | Cheapest refuting experiment | NHR |
|---|---|---|---|---|---|
| DEC-001 | Mission = "all four" — how to plan for it? | Treat as a maturity ladder: M0 personal force-multiplier → M1 client-grade factory → M2 product/platform, with research as the standing instrument layer. Near-term phases optimize M0/M1 (shared QA/evidence spine); M2 tracked as unblocked-not-built. Trade-off: defers packaging/generality. | MED | One engagement run where a deliverable fails external scrutiny → ladder order was wrong | **YES** |
| DEC-002 | Merge gate now that GitHub is Pro? | Branch protection on main: required CI checks + 1 review; local Stop hook stays the inner loop. Trade-off: solo-dev friction on every merge. | HIGH | Open a deliberately-red PR; if it can merge, the gate is not real | no |
| DEC-003 | How to mechanize human gates (BLK-3)? | Gate-state file (extend engagement.py board) + generators REFUSE on missing upstream approval, overridable only by an explicit logged `--override-gate <reason>`; overrides reviewed weekly. Trade-off: friction; override-theatre risk (R3). | MED | Generate a MOP without an approved LLD marker — expect refusal + test proves it | no |
| DEC-004 | LLM judge at TNR 0.2? | Demote to ADVISORY-only until re-baselined TNR ≥ 0.25 on the fair subset; deterministic arm carries all gates meanwhile. Optional later: bigger local model. Trade-off: less LLM leverage short-term; avoids trusting a broken instrument. | HIGH | Re-run defect-panel baseline after any judge change; TNR row decides | no |
| DEC-005 | Protected-tier pin mechanism (BLK-1)? | selfcheck runtime reconcile of the REAL store (path via env/known location; RED on missing/drifted protected entries, explicit signal_absent when store not present) + consolidation wiring: a repo-side pre/post-consolidation check invoking missing_protected. Portable pytest cannot reference the per-machine store — say so; the runtime check is the pin. | HIGH | Locally flip `protected: true→false` in the store → selfcheck must go RED | no |
| DEC-006 | Eval-corpus ≠ retriever-corpus (digest lane)? | Recommend: eval measures what ships — add a digest lane column to the D10 eval (as a D10 amendment, owner's call). Alternative: exclude digest from the certified path. | LOW | Run the 8-query recall experiment with/without digest lane; if delta ≈ 0 the question is moot | **YES** |
| DEC-007 | Holdout policy (per interview) | Hybrid: calibration N≥5-REAL floor + N≥20 target now; a sealed 70/30 split contract written NOW (manifest.py hash-chain) that ACTIVATES at N≥50 REAL. | HIGH | At activation: tamper one holdout row → manifest verify must fail | no |
| DEC-008 | settings.local.json pre-approvals (`python -c`, `cat > *`)? | Recommend removal/narrowing — they erode the doctrine's own declared backstop. It is the operator's convenience trade; decision is theirs. | MED | Remove; count added prompts/day for one week — if intolerable, re-accept formally | **YES** |
| DEC-009 | Unanswered P0s | Assume: resource envelope generous-but-bounded (review ≈ a few hrs/wk); risk appetite conservative (close what's closable, formally accept documented residuals); first REAL PIR event-driven (no date). | LOW | The human corrects any of the three in one sentence | **YES** |
| DEC-010 | Phase-2 acceptance when the local judge cannot clear the D10 anchor gate on available hardware | ACCEPT an **identifier-stratum-only** verdict: the identifier stratum is judge-FREE and ran clean; the judged strata (semantic/multi-hop) are DEFERRED as hardware-limited, not failed. Rejected: (b) infinite laddering — 5 rungs × 2 model families did not clear anchor accuracy (0.53 vs 0.80 bar; defect-panel TNR reached 0.6 but that is a different instrument); (c) block Phase 3 on a GPU host that may not exist. | HIGH | A GPU/larger-model re-run later flips the deferred strata — the frozen set + harness make it one command, so acceptance now costs nothing later | decided |

> **Decisions log — 2026-07-10 (user delegation: "take the best possible decision"):**
> DEC-001 ladder CONFIRMED (M0 personal → M1 client → M2 product; research = instrument layer).
> DEC-006 DECIDED: add the digest lane to the D10 eval via owner amendment (execute at P2-0e).
> DEC-008 DECIDED: remove/narrow the `python -c '*'` and `cat > *` pre-approvals — EXECUTION
> DEFERRED until the two live fix-sessions complete (yanking permissions under running sessions
> is an operational hazard); lands with P0-7, revert path = re-add and formally accept.
> DEC-009 assumptions STAND as defaults until corrected in one sentence.

> **Phase-2 VERDICT — 2026-07-11 (DEC-010, user-accepted):** run 1 (`docs/quality/d10-eval-results-2026-07-11.md`,
> PARTIAL) + DEC-010. **BM25 on the identifier stratum: SUGGESTIVE-BUT-INCONCLUSIVE** — MRR@5
> 0.139→0.276 (Δ+0.137, clears the +0.05 effect bar) but p=0.107 / dz=0.38 at n=20, short of the
> pre-registered p<0.05 ∧ d>0.4 bars (the documented ~55% power limit at n=20). No re-tuning — the
> bars were pre-registered. **Judged strata (semantic/multi-hop): DEFERRED** — the local judge could
> not clear the anchor gate (accuracy 0.53 < 0.80) on CPU-class models. **Dense lane: DEFERRED** —
> 0/30 real queries logged; the traffic mix is measured, never assumed. Negatives flagged a real
> over-retrieval / no-abstention signal for Phase 3. **Phase-2 acceptance = CLOSED on this evidence;
> Phase 3 opens.** The frozen set + harness make a future GPU re-run one command — deferral is
> reversible at zero cost.

## 5. Phased execution plan

### PHASE 0 — DOCTRINE HARDENING (prerequisite for everything)
Tasks (each lands as its own human-owned PR; blast-radius note required when touching shared symbols):
- **P0-1 Protected-tier artifact pin + wiring (G-001, DEC-005).** selfcheck gains
  `check_protected_artifact` (runtime reconcile vs real store; signal_absent when absent, RED on
  drift/missing protected entries; MEMORY.md index coverage check) + a consolidation pre/post
  wrapper invoking `missing_protected`. Acceptance: local frontmatter flip → selfcheck RED;
  store-absent → explicit signal_absent, never green.
- **P0-2 Proposer≠verifier mechanical wedge (G-002).** scorecard rows gain
  `authored_by`/`reviewed_by`; `--record` refuses author==reviewer; guard test pins the analyst
  agents' read-only allowlists (frontmatter parse). Residual (an agent lying about identity) is
  declared, not hidden. Acceptance: self-review record attempt → refused + test green.
- **P0-3 Human-gate mechanization (G-003, DEC-003).** Gate-state artifact + refusal in design/mop
  generators (`--override-gate <reason>` logged). Acceptance: MOP generation without approved-LLD
  marker refuses; override writes an audit line; test proves both.
- **P0-4 Merge gate live (G-004, DEC-002).** Verify Actions runs post-Pro; enable branch
  protection on main (required: ci.yml green + 1 review). Acceptance: deliberately-red PR cannot
  merge (the DEC-002 experiment, run once for real).
- **P0-5 SSOT registry truth sweep (G-005).** Fix ssot.md:40/:41 AND :31 (cached release version
  says 3.26.0 vs owner pyproject 3.30.0 — reviewer finding) (+ ADR-Am.1:57 stale line, CLAUDE.md:9
  local-Ollama carve-out — 1-line doctrine edit, human-reviewed); add a registry-freshness guard
  covering BOTH failure modes: (a) status lines must not contradict tracked files (e.g. "no feed"
  while docs/intel/*.jsonl is tracked) and (b) cached VALUES reconcile to their owners (the :31
  version cache vs pyproject). Acceptance: guard red on today's state until lines fixed, green after.
- **P0-6 Judge-trust repairs (G-006, DEC-004).** (a) writers emit judge_tnr when a baseline
  exists; (b) PROVISIONAL enforced in code — a PROVISIONAL APPROVE cannot satisfy any gate;
  (c) GUARD_FILES membership pinned (explicit 13-entry assertion) + test_version.py added to
  GUARD_FILES; (d) LLM judge marked advisory in scorecard semantics until TNR ≥ 0.25.
  Acceptance: tests for a-c; defect-panel re-baseline recorded for d.
- **P0-7 Permission backstop restore (DEC-008, NHR).** Remove/narrow `python -c '*'` and
  `cat > *` pre-approvals — or the human formally accepts them (logged in this plan's §7).
- **P0-8 vault-guard Bash extension.** PreToolUse match on Bash commands writing to
  `C:\Vaults\brain` (best-effort pattern; residual declared). Acceptance: `cat > /c/Vaults/brain/x`
  blocked in a dry test.
- **P0-9 Residual-bypass ledger.** Enumerate what CANNOT close (Bash-holding agents, hook
  fail-open by design, external graphify, plugin consolidation behavior) → explicit human
  acceptance, recorded in session-handoff `pending_human_review`.
Phase acceptance: every §1 row at TARGET rung; residuals human-accepted (P0-9); red-PR experiment
passed; suite green under the Stop hook AND CI.

### PHASE 1 — FEEDBACK LOOP BOOTSTRAP (hybrid policy, DEC-007)
- **P1-1 Data accrual instrumentation:** every /qa run records (already live via --record);
  confirm-row-landed step enforced (parse signature or re-emit). REAL PIR rows remain event-driven
  (first real cutover); calibration floor stays frozen until N≥5 REAL — never fabricate (doctrine 5).
- **P1-2 Holdout activation contract:** write the manifest/hash tooling + a
  `docs/quality/holdout-contract.md` (owner-registered in ssot.md) stating: at N≥50 REAL labelled
  rows, a sealed 70/30 split activates; holdout reads only via a logging script; audit-trail
  review, not proof-of-non-use (none exists — said plainly).
- **P1-3 Judge re-baseline ladder:** prompt/model iterations for the local judge; each re-baseline
  appends a TNR row; promotion from advisory when TNR ≥ 0.25 (fair subset), with the n≈12-defect
  CI stated on every report (screening floor, never calibration proof).
- **P1-4 Readiness↔outcome loop:** precert freeze rows + PIR joins accumulate; D11 gate untouched.
Acceptance (sample-honest): no gate below its sample's resolution — gates are floors/refusals, not
effect claims; scorecard row-count strictly increasing across engagements; zero surrogate rows
promoted to REAL (audit: source_class only ever set by the PIR writer); protected-tier selfcheck
green throughout. The 2026-08-05 shadow-PIR/lab-cutover decision (absorbed from remaining-work) is
the human checkpoint if no REAL data has arrived by then.

### PHASE 2 — RETRIEVAL LAYER FALSIFICATION (owner: d10 design doc; runs only after P2-0f lands)
Pre-tasks: **P2-0a query logging** (instrument /ask + recall.py to log real queries — today the
30-query classification is unrunnable: no log exists); **P2-0b** eval deps into pyproject
(rank-bm25/bm25s, pytrec_eval, scipy; dense deps only if the traffic bar clears); **P2-0c** Ollama
install pinned (version + model recorded in ssot.md); **P2-0d** thresholds pre-registered to a
file BEFORE any run; **P2-0e** DEC-006 corpus ruling (human + D10 amendment); **P2-0f** land the
D10 owner-doc corrections (power erratum + stale 5k node count) — currently an in-flight spawned
session; if that session never completes, this task owns the fix (risk R10).
Protocol: build the 60-query set (identifier 20 / semantic 20 / multi-hop 10 / negative 10 +
15 anchors); judge screening floor κ≥0.70 ∧ acc≥0.80; validity Hole@10 ≤ 0.15 else INVALID re-pool;
results table over 4 strata: graph-only + graph+BM25 always, dense-offline column ONLY if ≥30% of
the logged real queries classify semantic (borderline within the ±16–17pp CI → NEEDS_HUMAN_DECISION — this plan's addition, not in
the owner; binomial SE at p̂=0.3, n=30 → ±16.4pp).
Decide with pre-registered criteria (p<0.05 paired t ∧ d>0.4). Power honesty: the owner (d10:95)
currently states "~40–50% at d=0.5" — an unpaired-figure ERRATUM; for its own pre-registered
PAIRED test, noncentrality dz·√60 ≈ 3.87 → power ≈97% overall at dz=0.5, and ≈55%/≈33%
per-stratum at n=20/10 (derivation recorded here pending the owner fix, P2-0f) — the dense
criterion is the underpowered one and that is acceptable as a falsification hurdle (under-ships,
never over-promises). No hyperparameter tuning at n=60. Ship gate: falsification pass AND decisive traffic mix → dense at
low RRF weight. The built recall.py 8-query experiment is the harness seed, not evidence.

### PHASE 3+ — FEATURE DEVELOPMENT (only after Phases 0–2 acceptance; machine-verified where
machine-verifiable, residual human-judged criteria enumerated at each gate)
Task register (one-line goal + acceptance; full atomic-steps/rollback/gate cards are cut when a
task is pulled — none may start before Phase 0–2 close; blast-radius note mandatory on shared
symbols):
- **P3-E1 Parser↔detector field contract** — extend the test_detector_schema leaf-resolution
  pattern to all 82 detectors, fanout-ranked via `python -m graphify affected` (top-20 first);
  grow parser_examples pins 21→top-50 by usage. Accept: a parser field rename breaks a test, not
  a deliverable.
- **P3-E2 Diff schema gate** — --compare/--trend warn-or-refuse on mismatched schema/script_version.
- **P3-E3 Provenance closure** — deck.py footer + excel Exec-Summary provenance row (the two
  genuinely-open excellence items).
- **P3-E4 Excellence-plan status refresh** — mark landed P2/P3 rows (Dim H evidence).
- **P3-E5 parse_port_security_detail NX-OS residual** (parser-format-fidelity.md:71).
- **P3-W1 Webapp frontend test harness** (vitest + smoke tests); **P3-W2** direct pir_docx tests.
- **P3-K1 graph.json invariant test** (schema/count sanity) + **P3-K2** commit-staleness selfcheck
  (built_at_commit==HEAD); **P3-K3** rationale-node rename consideration [LOW].
- **P3-B1 SelfMem write-vocab + deferred SQLite index** (ADR-0003 boundary).
- **P3-D1 Dead-config removal** (SubagentStop path) once the SDK behavior is confirmed permanent.
- **P3-M0 Register freeze** — freeze/annotate the 278-item universality-gap register + the
  recall/RRF flag (remaining-work Act-4 carry-over; owner universality-gap-register.md:5).
- **P3-M\*** MASTER_PLAN absorbed backlog: §2 secure&tidy sweep, §4.1 L2-twin, §4.2 cutover-sim,
  §4.3 per-VLAN workbook, §5 platform/vault items — admission gated by severity + mission-ladder
  rung (DEC-001).

## 6. Frozen set (no automated process may touch; pin status per Stage A evidence)

| Path | Invariant | Enforcing pin (today → target) |
|---|---|---|
| protected-constraints.md (agent memory store) | never-delete tier (D12) | mechanism tests only → P0-1 runtime reconcile |
| docs/ssot.md registry | SSOT integrity + freshness | tests/test_ssot_registry.py → + P0-5 freshness guard |
| cisco_toolkit/__init__.py `__version__` | frozen schema version (pyproject decoupled BY DESIGN — CLAUDE.md; the 3.23.0/3.30.0 difference is the proof) | value pin exists (test_version.py:6), not in GUARD_FILES → P0-6c |
| ollama_judge.py + selfcheck GUARD_FILES | judge-trust instruments; immune-system scope | existence/non-vacuity only; membership un-pinned → P0-6c explicit 13-entry pin |
| docs/quality/scorecard.jsonl + pir_outcomes.jsonl | append-only outcome stores; source_class set only by writers | convention → P1-1 audit check |
| sealed holdout manifest | eval integrity | created at DEC-007 activation (N≥50 REAL) |

## 7. Open risks

| Risk | L | I | Owner | Mitigation |
|---|---|---|---|---|
| R1 LLM judge stays broken (TNR 0.2) | M | M | agent | DEC-004 advisory demotion; deterministic arm carries gates; P1-3 ladder |
| R2 No REAL PIR by 2026-08-05 | M | H | human | carried decision date (remaining-work): shadow-PIR vs lab-cutover vs wait; never fabricate |
| R3 Gate overrides become routine → theatre | M | H | human | override log + weekly review; Phase-0 acceptance includes zero-silent-override |
| R4 Branch-protection assumption wrong on this repo/tier | L | H | human | DEC-002 red-PR experiment day 1 |
| R5 P3-E1 scope explosion (82×105 surface) | M | M | agent | fanout-ranked top-20 first; severity-capped admission |
| R6 graphify ranking engine external/unauditable | L | M | human | accepted residual (P0-9); eval measures it black-box in Phase 2 |
| R7 Solo-operator context/bus factor | M | M | agent | session-handoff.yaml discipline; this plan is the resumable index |
| R8 Fabrication pressure when data trickles | L | H | both | doctrine-5 corollary; surrogate quarantine audited (P1-1) |
| R9 Plugin consolidation ignores `protected:` marker | M | H | human | P0-1 wrapper + runtime reconcile detects loss after the fact; residual declared |
| R10 D10 erratum fix (spawned session) never lands | L | M | agent | P2-0f owns it in-plan; Phase 2 blocked until landed |

## 8. Adversarial self-check (refute-first)

- **Three most likely 30-day failures:** (1) P0-3 gate friction → routine overrides → doctrine
  theatre (counter: override log is itself gated by Phase-0 acceptance); (2) REAL-data drought
  stalls Phase 1 and invites surrogate promotion (counter: R2 checkpoint + audit); (3) "all four
  missions" + engine scope dilutes execution into plan-#9 sprawl (counter: DEC-001 ladder +
  severity-capped P3 admission; Phases 0–2 are mission-invariant).
- **Hardest assumption:** real engagement usage will generate REAL rows and real queries — every
  data-gated loop (P1, P2 dense precondition) hinges on it. If usage doesn't materialize, the
  correct outcome is the loops STAY frozen (that is the design, not a failure of it).
- **Alternative architecture considered and rejected:** standing multi-domain agent team —
  rejected on v4-final D6 evidence (coordination negative at 8–10 agents; retrieval skill-packs
  keyed to architecture_coverage instead).
- **Fragile numbers (all volatile, re-derived at e3b2bd5, cited in the understanding doc):**
  scorecard=3 rows · PIR=7/0 REAL · graph=6,974 nodes · judge TNR=0.2 · coverage=46/27 ·
  parser pins=21/105 · detectors=82 · registry gaps=278 (owner docs/universality-gap-register.md:5,
  historical). Any future consumer
  re-derives from owners; quoting this table forward is itself a doctrine-6 violation.
- No BLOCKER surfaced against the plan itself in this check; the §9 independent pass is the
  binding verdict.

## 9. Independent verification (doctrine 3)

Executed after saving this file: /qa-style adversarial review by the independent
deliverable-qa-reviewer (never edits what it reviews) over the two planning artifacts; DOCX/PDF
render step N/A → UN-VERIFIED-N/A; verbatim verdict recorded to docs/quality/scorecard.jsonl via
`python -m cisco_toolkit.scorecard --record` with a confirm-row-landed check. Verdict + finding
dispositions: see session-handoff.yaml (`qa_verdict`) and the QA verdict file referenced there.
A BLOCK verdict means this plan is revised and §9 re-runs — the reviewer is not argued down.
Round 1 (2026-07-10) returned BLOCK on this plan (upstream-provenance defect: the H evidence was
recorded in no artifact; + 7 advisory findings) — all dispositioned in this revision (H appended
to the understanding doc; provenance/citations corrected; P0-5 widened; P2-0f + R10 added;
§3 extended). The re-run verdict is recorded in the handoff.

*Generated by /architect-plan Stage B, 2026-07-10 @ e3b2bd5. Do not implement from this plan until
Phase 0 PRs are human-merged; production change only via human-owned PR + CAB.*
