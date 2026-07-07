# The Autonomous Senior-Engineer Brain — Self-Improvement, Autonomy & External Senses

**A v3 delta plan · 2026-07-06 · reconciles against `docs/MASTER_PLAN_2026-07-05.md` (does not replace it)**

> **One-line verdict:** You have not built a weak system. You have built an *exceptional cortex with no nervous system* — a superb brain that has no clock, no feedback nerve, no external senses, and amnesia between sessions. Nothing here is a rebuild. It is the wiring of four missing nerves onto a foundation that is already, measurably, top-tier.

---

## How to read this document

- **Audience:** you (the operator/Engagement Lead) + a second AI reviewer ("full-power" re-review). It is self-contained: every claim is grounded in either a repo file (audited today) or a web source (researched today, cited inline).
- **It is a DELTA, not a rewrite.** The settled thesis ("analysis surface is saturated; the frontier is trust / provability / execution-grade output") is inherited, not re-argued. MASTER_PLAN §7's "traps" (no rewrite, no ntc-templates default, no DuckDB, no PyPI-by-reflex, no scrapli/Nornir) remain binding. This plan targets **only the genuinely-open frontier**.
- **Structure:** §1 the honest verdict → §2 the diagnosis (why it *feels* inert) → §3 the reframe → §4 principles → §5 the strategic fork, resolved → §6 the four nerves (the architecture) → §7 the six-angle mind → §8 attacking the systemic failure classes → §9 field state-of-the-art → §10 phased roadmap → §11 cost & bounded-autonomy → §12 red-team → §13 metrics → §14 decision register.

**Table of contents**

1. The honest verdict — is your setup "the best"?
2. The diagnosis — why it feels like it's "always missing something"
3. The reframe — brain vs. nervous system
4. Design principles (carried forward + newly enforced)
5. The one open strategic fork — resolved
6. The four missing nerves (the architecture)
   - 6.1 The CLOCK — autonomous daily cadence & the morning briefing
   - 6.2 The FEEDBACK NERVE — closed-loop calibration & the deliverable scorecard
   - 6.3 The EYES — the egress-isolated research lane
   - 6.4 RECALL — connect-the-dots memory & doctrine-safe vault recall
7. The SIX-ANGLE MIND — refutation-first validation as default
8. Attacking the five systemic failure classes
9. Field state-of-the-art (researched 2026-07-06, cited)
10. Phased roadmap — 6 phases, each with acceptance criteria
11. Cost, risk & bounded-autonomy guardrails
12. Red-team — how this plan could fail, and the mitigations
13. Metrics — how you will *know* it's improving
14. Decision register — the 5 forks I need you to settle

---

## 1. The honest verdict — is your setup "the best"?

**Your instinct that "this isn't the best we have" is half right, and the half that's right is precise.**

What the audit found — verified today, with file evidence:

| Capability | State | Evidence |
|---|---|---|
| Code knowledge graph | **5,905 nodes / 10,392 edges / 438 communities, 96% AST-extracted, 0% ambiguous, auto-refreshed on `.py` edits** | `graphify graph_stats` (live); `graphify-out/GRAPH_REPORT.md:1,8` |
| Specialist agents | 8 role-scoped subagents, read-only-by-default, **proposer≠verifier enforced** | `.claude/agents/*.md` |
| Single source of truth | CI-enforced: one snapshot → one canonical fact → `reconcile()` re-derives from raw evidence → render-lock tests | `cisco_toolkit/ssot.py:37-52,286-408`; `docs/ssot-contract.md:62-76` |
| Deliverable standard | 10-Law "Deliverable Excellence Standard" + a *ratcheting* test gate (build fails unless every writer carries the furniture) | `docs/deliverable-excellence-plan.md:3`; `tests/test_deliverable_excellence.py` |
| Knowledge architecture | Two-store (repo vs. vault), sanitized one-way bridge, ADR-governed | `docs/decisions/0001-two-store-knowledge-architecture.md` |
| Safety rails | Verify-green pytest Stop-hook (blocks turn until green), vault-guard, default permission mode | `.claude/settings.json:44-54`; `.claude/hooks/` |

**This is better than almost any single-user AI-engineering setup in existence, and better than many funded teams.** The tools you chose — Claude Code + graphify + Obsidian — are not just adequate, they are exactly what the field's best practice converges on (see §9): a code **graph** as the entity layer (GraphRAG), an Obsidian **wiki** as the persistent second brain (the "Karpathy LLM-Wiki" pattern), and Claude Code as the **orchestrator**. You do not need to switch tools. You picked right.

**So what's the half that's right?** The system is **reactive, internal, and un-measured.** It only thinks when you prompt it. It cannot see the outside world. It does not measure its own quality, so it cannot know — and neither can you — whether it is improving. And it forgets: of 8 agents only 3 are configured to keep memory and just one (release-captain) has ever actually written one — the 5 read-only analysts keep none — while a backlog of captured `!lesson` / `bridge-candidate` entries sits un-promoted. That is why it *feels* inert even though it is powerful. **You are not missing capability. You are missing animation.**

---

## 2. The diagnosis — why it feels like it's "always missing something"

The audit pinned each missing piece to a file. These are not vibes; they are structural absences:

1. **No clock.** Every mechanism — `Stop`, `SessionStart`, `UserPromptSubmit` — fires only on *your* turn. There is literally **no scheduler wired in** (grep-clean across the repo; the `scheduled-tasks` MCP is available in the harness but unused). → Nothing can ever greet you in the morning. This is the direct cause of "*every time I log in I should get something good* — but I don't."

2. **No feedback nerve — the improvement loop is OPEN.** Nothing scores a deliverable's quality over time, nothing feeds QA findings back into prompts or memory, nothing tracks a trend. QA emits APPROVE/BLOCK per cycle and the verdict is **consumed and discarded**. The one loop designed to change tool behavior — the **calibration loop** (MASTER_PLAN §4.5 / memory Track D: join real PIR/war-room outcomes against pre-cutover verdicts to tune `ScoringConfig`) — is **specced but unbuilt**. → Mechanically, the system genuinely is **not** improving between sessions. Your instinct is *correct*, and now it's proven.

3. **No eyes.** The no-egress doctrine (correctly) keeps the graph and the assessment engine from phoning home. But there is no *separate* lane bringing the outside world in — no daily research, no PSIRT/advisory sweep, no "what did the field ship this week." → The brain cannot answer "what's the best current approach" because it structurally cannot look.

4. **No recall.** The vault (`C:\Vaults\brain` — "everything he knows") is **write-only from the repo's view** (ADR-0001 forbids repo→vault reads). → The brain cannot recall its own accumulated career knowledge during an assessment. Combined with under-adopted agent-memory (only 3 of 8 agents are configured for it, and only release-captain has actually written one), the system starts most tasks amnesiac. This is the opposite of "he already knows everything in the back of his mind."

**These four map exactly onto what you asked for.** "Improving on its own" = the feedback nerve. "Research everywhere every day" = the eyes. "Every time I log in, something good" = the clock. "Knows everything, connects the dots" = recall. You diagnosed your own system correctly in plain language; this plan just gives each nerve a name, a file, and a build order.

---

## 3. The reframe — brain vs. nervous system

> **The "singularity feeling" you're chasing does not come from a bigger brain. It comes from a *closed, compounding loop that you can see move.***

Two honest truths, because you asked me to understand, validate, *and* refute:

- **What you can have (and should build):** a **bounded, compounding system** that provably gets a little better every week — because it measures itself, learns from real outcomes, watches the field, and remembers — and that *shows you the movement* every morning. That visible compounding **is** the feeling of singularity. It is real, it is safe, and it is ~6 phases away.

- **What you cannot have (and shouldn't want):** literal unbounded, unsupervised self-improvement. The research is blunt here: agents that grade themselves **coast and degrade** ("stores 'great progress,' reads it next run, coasts" — [kjetilfuras.com](https://kjetilfuras.com/run-claude-agent-on-schedule/)); LLMs that critique their own *reasoning* without an external signal can flip **correct → wrong** ([MIT TACL](https://direct.mit.edu/tacl/article/doi/10.1162/tacl_a_00713/125177/)); multi-agent debate left ungrounded **amplifies** hallucinations ([arXiv 2606.03032](https://arxiv.org/pdf/2606.03032)); and Databricks (Apr 2026) found agents **reusing wrong results with more confidence** over time ([mem0.ai](https://mem0.ai/blog/state-of-ai-agent-memory-2026)). "Always running, always improving on its own" with no ground truth is precisely the failure mode the field has catalogued.

The synthesis: **animate the brain, but nail every nerve to ground truth.** Every loop closes on something real — a passing test, a reconciled fact, a labeled PIR outcome, a byte-matched citation — never on the model's opinion of itself. That is the difference between a system that compounds and one that confabulates.

---

## 4. Design principles (carried forward + newly enforced)

**Carried forward (unchanged, binding):**
- Read-only by default; production change only via human PR + CAB in a window with rollback.
- **Proposer ≠ verifier** on every consequential output.
- Evidence-grounded & coverage-honest; "not observed" never silently becomes "healthy."
- One source of truth; reconcile every shared fact.
- No-egress for the graph + assessment engine (reproducible on an air-gapped host).

**Newly enforced by this plan (each earns its place from the research):**
- **P-A · Ground every loop.** No self-scoring. Refinement gates on tools/tests/evidence, never on the model's self-rating. *(Grounded critique beats intrinsic critique — [MIT TACL](https://direct.mit.edu/tacl/article/doi/10.1162/tacl_a_00713/125177/).)*
- **P-B · Store verifiable facts, never self-assessments.** Memory holds test pass-rates, QA counterexamples, labeled outcomes — not "good progress." *(The coasting trap — [kjetilfuras.com](https://kjetilfuras.com/run-claude-agent-on-schedule/).)*
- **P-C · Bounded autonomy.** Every unattended run has a hard budget cap, a max-turns cap, a **circuit breaker (disable after 3 consecutive failures)**, and is **propose-only** (writes a PR/briefing, never acts). *(Gartner 2025 failure modes: runaway cost, unclear value, weak controls — [cio.com](https://www.cio.com/article/4082609/).)*
- **P-D · Offline-first, API-later.** Anything needing egress (web research, prompt-optimization model calls) runs in a **fenced connected lane**; only *frozen, sanitized artifacts* cross into the air-gapped repo. This is your own §4.4 doctrine, now load-bearing.
- **P-E · Enforce forgetting.** Memory is compressed/superseded on a schedule; stale facts are timestamped and retired, not accumulated. *(Temporal supersession — [Graphiti/Zep](https://www.agenticwire.news/article/mem0-zep-letta-agent-memory); anti-accumulation — [mem0.ai](https://mem0.ai/blog/state-of-ai-agent-memory-2026).)*

---

## 5. The one open strategic fork — resolved

The audit surfaced exactly one unreconciled strategic fork in your own docs:

- **Breadth-first** (`docs/absolute-universal-roadmap.md`): chase vendor breadth (Axis A — non-Cisco), five universality axes.
- **Depth/trust-first** (the saturation thesis, cross-validated across 5 docs): "analysis is saturated; make the existing analysis provably trustworthy and execution-grade; add breadth only when a real client needs it."

**Recommendation: commit to depth/trust-first.** Rationale: (1) it's what your own evidence already concluded; (2) this plan's entire value — a system that *provably improves* — is a depth/trust play; (3) breadth is demand-shaped and better pulled by a real engagement than pushed speculatively. **Breadth becomes client-gated:** a new vendor/class is built when an engagement requires it, not before. *(This is a decision I recommend but flag in §14 for your sign-off — it's genuinely yours to make.)*

---

## 6. The four missing nerves (the architecture)

```
                         ┌───────────────────────── THE EYES (egress-fenced) ─────────────────────────┐
                         │  research-lane session (separate worktree, connected)                      │
                         │  • daily web sweep: PSIRT/advisories, field practice, tool releases         │
                         │  • GEPA/DSPy prompt-optimization (model calls)                              │
                         │  → distills → sanitizes (Rule-3) → signs → writes intel/feed.md + prompts/  │
                         └───────────────────────────────────┬───────────────────────────────────────┘
                                                             │  (frozen, sanitized artifacts ONLY)
                                                             ▼
  ┌────────────────────────────────── THE AIR-GAPPED REPO (no-egress, unchanged doctrine) ──────────────────────────────┐
  │                                                                                                                      │
  │   THE CLOCK ─────────────►  nightly `claude -p` (bounded, propose-only)                                             │
  │   (local cron)             • run golden-snapshot evals   • consume intel/feed.md   • check rot-watch actions        │
  │                            • assemble MORNING BRIEFING (a PR + a digest you read at login)                          │
  │                                          │                                                                           │
  │                                          ▼                                                                           │
  │   THE FEEDBACK NERVE ────►  calibration loop (Track D): PIR outcomes → ScoringConfig                                │
  │                            + deliverable SCORECARD (persisted JSONL) + trend                                        │
  │                            + learnings.md (verifiable facts only) ── feeds ──► agent prompts/memory                 │
  │                                          │                                                                           │
  │                                          ▼                                                                           │
  │   RECALL ────────────────►  RRF hybrid retrieval: graphify (graph) ⊕ docs (vector) ⊕ vault-digest (local RAG)      │
  │                            CoALA-labeled stores · temporal fact-supersession                                        │
  │                                          │                                                                           │
  │                                          ▼                                                                           │
  │   THE SIX-ANGLE MIND ────►  grounded N-verifier panel on consequential outputs (refutation-first)                  │
  │                                                                                                                      │
  └──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 6.1 The CLOCK — autonomous daily cadence & the morning briefing

**Goal:** the thing you actually asked for — "every time I log in, something good."

**Mechanism (verified adoptable):** local `cron`/Windows Task Scheduler → **headless `claude -p`** running a bounded, propose-only nightly routine. (Not Anthropic cloud Routines — those are cloud-hosted and a poor fit for your air-gap; [code.claude.com/scheduled-tasks](https://code.claude.com/docs/en/scheduled-tasks). Local cron is the right substrate — [kjetilfuras.com](https://kjetilfuras.com/run-claude-agent-on-schedule/).)

**What the nightly run does (all read-only / propose-only):**
1. Run the **golden-snapshot eval suite** (§6.2) → record pass-rate + any regressions.
2. Consume the morning's `intel/feed.md` from the research lane (§6.3) → surface anything relevant to open engagements (e.g., a new PSIRT touching an assessed platform).
3. Read `session-brief` **rot-watch** and, where a threshold is crossed, *act* (refresh graph, flag stale vault) instead of only displaying.
4. Surface open **GI/REC items** (e.g., the Syntys HLD open items) and un-promoted `!lesson` bridge-candidates.
5. Assemble a **MORNING BRIEFING**: a short digest + (optionally) a draft PR. Verifiable facts only — pass-rates, counts, diffs, named advisories. **No self-congratulation** (P-B).

**Acceptance:** you open the laptop and a `briefing-YYYY-MM-DD.md` is waiting, ≤1 screen, every line backed by a number or a link, produced under a hard budget cap, and it **never touched a device or pushed a branch**.

**Guardrails:** `--max-turns`, `--max-budget-usd` per run; a daily spend ceiling; a **circuit breaker** that disables the cron after 3 consecutive failed runs and notifies you. (§11.)

### 6.2 The FEEDBACK NERVE — closed-loop calibration & the deliverable scorecard

**This is the single highest-leverage build in the entire plan.** It is what converts "I *feel* it's not improving" into "here is the graph of it improving."

Three components, in dependency order:

**(a) Golden-snapshot eval suite** — a fixed set of known-good deliverables + a scorer, run inside your existing `pytest` harness. Tiered like the field does it: a small smoke set per change, the full set on merge/release ([futureagi.com](https://futureagi.com/blog/ai-llm-prompts-model-evaluation-2025/)). This is the *measuring stick* — without it, "improvement" is unfalsifiable. Scoring blends deterministic checks (SSOT reconcile clean, all 10 Laws present, citations byte-match) with an **LLM-as-judge rubric** for prose quality, run by an *independent* critic agent (exploits the self-critique asymmetry: models judge others better than themselves — [arXiv 2606.05976](https://arxiv.org/html/2606.05976)).

**(b) Persisted deliverable scorecard** — every QA cycle appends a row to `docs/quality/scorecard.jsonl`: timestamp, deliverable, eval score, QA verdict, counterexample count, which Laws tripped. **The verdict is no longer discarded.** A tiny `scorecard trend` command renders the line going up (or not). *This is the artifact that will give you the feeling you're missing.*

**(c) The calibration loop (Track D / MASTER_PLAN §4.5)** — build `cisco_toolkit/calibration.py`: join **real PIR/war-room outcomes** against the pre-cutover verdicts the engine produced, and tune `ScoringConfig` to reduce the gap. This is the only loop that changes *tool behavior* rather than accumulating prose (memory Track D, still open). It closes the "over time" half of "best-possible deliverables that provably improve over time."

**How findings feed back (the compounding step):** a `SubagentStop`/`SessionEnd` hook distills each QA cycle into `learnings.md` (<100 lines, read at every session start) — **verifiable facts only** (P-B) — and, for prompt-level fixes, queues them for the offline **GEPA prompt-optimization** pass in the research lane (§6.3), which ships back *frozen, improved agent/judge prompts*. GEPA is the verified state-of-the-art here: reflective prompt evolution, beats RL by up to 20% with **35× fewer rollouts**, and it consumes your QA *error text* as the gradient ([arXiv 2507.19457](https://arxiv.org/abs/2507.19457)).

**Acceptance:** (1) a regression in any generator fails a pytest eval *before* release; (2) `scorecard.jsonl` has ≥2 weeks of rows and the trend renders; (3) one `ScoringConfig` parameter has been moved by a *labeled outcome*, not by hand.

### 6.3 The EYES — the egress-isolated research lane

**Goal:** "research everywhere, every day" — *without* breaking the air-gap.

**The key architectural insight (this dissolves the tension you've been stuck on):** the no-egress doctrine protects **two specific things** — the knowledge *graph* (no LLM/URL-derived nodes) and the assessment *engine* (reproducible offline, never phones a device). It does **not** require *you* to be blind. The field's answer is a **fenced connected lane**: research + model-heavy optimization run in a *separate session/worktree that is allowed egress*; only **frozen, sanitized, signed artifacts** cross into the air-gapped repo. This is identical to your documented "offline-first, API-later" §4.4 stance — we're just operationalizing it.

**The lane (a separate `research-lane` worktree, connected, run manually or on its own cron):**
- **Daily sweep:** PSIRT/vendor advisories touching assessed platforms; NetDevOps field practice; new tool/technique releases; relevant arXiv/GitHub/blog signal. (Your existing `WebSearch`-enabled agents already do the reactive version; this makes it scheduled.)
- **Prompt optimization:** GEPA/DSPy runs here (needs model calls = egress) and emits frozen prompt files.
- **Output:** a distilled, **Rule-3-sanitized** (client identifiers stripped, per ADR-0001 bridge discipline), **provenance-tagged**, signed `intel/feed.md` + `prompts/*.frozen.md`.
- **The air-gapped repo CONSUMES these read-only.** It never fetches. The graph stays AST-only. The doctrine holds, verifiably.

**Why this is safe and honest:** the crossing is one-way, sanitized, signed, and *auditable* — the same trust model as your repo→vault bridge, run in reverse for curated intel. Nothing LLM-derived enters the *graph*; intel lives in `docs/intel/` as ordinary cited markdown (which graphify may index as docs, exactly as it already indexes `docs/research/`).

**Acceptance:** a dated `docs/intel/feed-YYYY-MM-DD.md` exists, every item carries a source URL + a "relevant-to" pointer, and the air-gapped repo's graph/engine reproduce **byte-identical** on a disconnected host (the no-egress invariant still passes).

### 6.4 RECALL — connect-the-dots memory & doctrine-safe vault recall

**Goal:** "he already knows everything; he connects the dots" — make the brain *recall* across code + engagement + career + intel.

Four moves, each validated by research:

1. **RRF hybrid retrieval** — the literal "connect-the-dots" mechanic. One query runs **both** graph traversal (graphify) **and** vector search (docs + vault-digest), then fuses ranks via **Reciprocal Rank Fusion**. GraphRAG beats vector-only on the multi-hop, entity-heavy questions your domain is made of; your AST graph *is* the entity layer, so you add a vector store *beside* it, not instead ([arXiv 2507.03226](https://arxiv.org/abs/2507.03226); [puppygraph.com](https://www.puppygraph.com/blog/graphrag-knowledge-graph)).

2. **Doctrine-safe vault recall (resolves the read-barrier).** Today the vault is write-only from the repo. Local offline RAG over Obsidian is a **solved, zero-egress** problem (Ollama/LM-Studio-backed — [ObsidianRAG](https://github.com/Vasallo94/ObsidianRAG)). Build a **one-way, sanitized, read-only "vault digest"** the repo *may* read. Not raw vault access — a curated, client-scrubbed semantic index. **Be honest that this reverses a *settled decision*, not a default:** ADR-0001 states "nothing flows vault→repo" as a deliberate choice, so this requires a proper **ADR-0001 amendment with its own sanitization guard** (flagged as D3 in §14) — not a quiet toggle. The brain finally recalls its own domain knowledge during an assessment, without violating the two-store separation.

3. **CoALA-label the stores** — tag each memory store **episodic** (`docs/log.md` retros), **semantic** (`docs/ssot.md`, vault-digest), **procedural** (`.claude/agents`, skills). This immediately exposes the current gap: **no procedural-skill memory**, and although 3 of 8 agents declare `memory: project` only release-captain has actually written one — the 5 read-only analysts (assessment / audit / topology / nrfu / qa) keep none ([atlan.com](https://atlan.com/know/types-of-ai-agent-memory/); [arXiv 2603.29194](https://arxiv.org/html/2603.29194v1)). Fix: adopt agent-memory on the read-only analysts too (they benefit most from remembered engagement context), and add a **self-improving-skills loop** (a Stop-hook distills each session and patches the relevant `SKILL.md`; a skill is "proven" at `use_count ≥ 3` — [github/self-improving-skills](https://github.com/UniM0cha/claude-self-improving-skills)).

4. **Temporal fact-supersession** — timestamp every remembered fact so a newer value **supersedes** rather than **duplicates** the old (the Graphiti/Zep model — [agenticwire](https://www.agenticwire.news/article/mem0-zep-letta-agent-memory)). This directly kills your **version-drift / SSOT-drift** bug class (§8): the same fact carrying different values across surfaces because old copies never retire.

**Acceptance:** a single `/ask` question returns an answer that visibly fuses a code-graph fact + a doc + a (sanitized) vault-digest recall; and a superseded fact (e.g., a fleet count) no longer resurfaces from stale memory.

---

## 7. The SIX-ANGLE MIND — refutation-first validation as default

You asked for answers "looked at from six different angles, validated, refuted, dependencies understood" — *by default, every time.* The research says this works **only if grounded**, and can backfire if not.

**The pattern:** for **consequential** outputs (a design decision, a cutover step, a headline claim), the orchestrator spawns an **N-verifier panel**, each verifier given a *distinct evidence-grounded lens* and told to **refute first** (default to "refuted" unless evidence proves otherwise). Majority + confidence-weighting decides. N-verifier majority achieves near-perfect recall of fabricated claims ([mdpi 3676](https://www.mdpi.com/2076-3417/15/7/3676)); grounded debate beats a single model on hard tasks ([arXiv 2510.12697](https://arxiv.org/html/2510.12697v1)).

**The six lenses (for a network deliverable):**
1. **Correctness** vs. the raw evidence/snapshot.
2. **Coverage-honesty** — is any "healthy" actually "not observed"? (attacks your #1 bug class, §8).
3. **Dependency/blast-radius** — what breaks if this is wrong? (`graphify affected()` + reachability).
4. **Consistency/SSOT** — does this value match every other surface?
5. **Change-safety** — is there a rollback; does it fit the window; is proposer≠verifier intact?
6. **Adversarial/refutation** — actively try to disprove; find the counterexample.

**The hard guardrail (from the research):** ungrounded debate *amplifies* hallucinations and homogenizes into a false consensus ("deliberative illusion," "factual attrition" — [arXiv 2606.03032](https://arxiv.org/pdf/2606.03032)). So **every lens must cite evidence**, verifiers must be **independent** (separate context, no shared draft to anchor on), and the panel **reports counterexamples, not consensus vibes.** This is your existing proposer≠verifier doctrine, widened from one QA reviewer to a grounded panel — packaged as a `/council` command so you can invoke it on demand and the nightly loop can invoke it automatically on anything it's about to put in the briefing.

**Acceptance:** `/council <claim>` returns a verdict with ≥3 grounded lenses, each citing a file/field, and at least one genuine attempted refutation — not six agents agreeing.

---

## 8. Attacking the five systemic failure classes

The retro-mining agent found what the system "keeps missing" — five recurring, *systemic* (not one-off) defects. A plan about "best-possible deliverables" must attack these at the root, not per-incident:

1. **Absence is not a first-class state (the dominant class).** Empty/uncollected silently renders as "healthy/green." It recurred in *every* recent adversarial wave — even the anti-false-health features shipped with their own false-health gaps. **Fix:** a shared **3-state abstention type** (`NOT_COLLECTED` / `COLLECTED_EMPTY` / `NOT_APPLICABLE`) used structurally across detectors, so "no evidence" can *never* resolve to "OK" by silence. (Enforces Law 3 mechanically instead of per-detector discipline.)

2. **Verification shares the artifact's assumptions.** Self-authored fixtures, root-token-only assertions, and text-only extraction all validate the mechanism *against itself*. **Fix:** *real-format* fixtures (captured from actual device output, not hand-written), **byte-match citation verifiers**, and **rendered-pixel** checks (the figure-raster eyeballing added 2026-07-06 — generalize it). This is the "independent channel" principle: never verify a thing with a copy of its own assumptions.

3. **Guards that don't run look identical to guards that pass.** The JS↔Python FIB parity gate *silently skipped* when `node` wasn't on PATH; the golden shrink-guard cried wolf. **Fix:** every guard carries a **non-vacuity self-check** and **fails loudly** when it cannot run. (A skipped guard is a *red*, not a green.)

4. **One-fact-many-owners drift.** The same fact (target platform, fleet count, confidence) diverges across surfaces because it's restated, not sourced. The `reconcile` gate exists but isn't universally wired (the CLI path lacks the webapp's pre-emission gate). **Fix:** wire the CLI generation path through the *same* `ssot.reconcile` pre-emission gate; add **temporal supersession** (§6.4) so old values retire.

5. **The rendered/binary surface has the weakest ratchet.** DOCX/PDF/figures/TOC live *outside* the frozen-snapshot golden contract, so regressions ship by hand (stale figure labels, hardcoded TOC page numbers). **Fix:** extend the golden contract to rendered artifacts — render → hash/inspect the *output*, not just the model. Bring the binary surface under the same ratchet as the code.

**These five are the concrete, unglamorous core of "best-possible deliverables."** They're also the highest-ROI reliability work, because each has *already* cost rework.

---

## 9. Field state-of-the-art (researched 2026-07-06, cited)

What the outside world is doing that you should adopt (filtered to single-user, mostly-offline fit). Full citations inline above; condensed here:

- **Self-improvement only works grounded.** Intrinsic self-correction of reasoning can flip correct→wrong; gains come from tool/execution/evidence feedback ([MIT TACL](https://direct.mit.edu/tacl/article/doi/10.1162/tacl_a_00713/125177/)). Reflexion (verbal RL, no weight updates) works as a critique→fix retry loop ([Reflexion](https://github.com/Zesearch/self-improvement-llm)). → Your pytest/reconcile/`affected()` are exactly the right verifiers.
- **Eval-driven development is mainstream.** Tiered regression evals + LLM-as-judge rubrics are how serious teams close the loop ([futureagi](https://futureagi.com/blog/ai-llm-prompts-model-evaluation-2025/)). **GEPA** is the verified prompt-optimization SOTA (ICLR 2026 oral; 35× fewer rollouts; consumes text feedback) — egress-only, freeze to air-gap ([arXiv 2507.19457](https://arxiv.org/abs/2507.19457)).
- **Scheduled agents:** cron → headless `claude -p`; 3-layer memory (`learnings.md` / daily logs / JSON snapshots); nightly promotes **only validated** patterns; **store verifiable facts, never self-assessments**; budget caps + circuit breaker ([kjetilfuras](https://kjetilfuras.com/run-claude-agent-on-schedule/)).
- **Memory:** CoALA taxonomy (episodic/semantic/procedural) is the settled frame; consolidation > accumulation; Letta-style *agent-decides-what-to-write* fits you; temporal graphs (Graphiti/Zep) model state-change ([atlan](https://atlan.com/know/types-of-ai-agent-memory/), [arXiv 2603.29194](https://arxiv.org/html/2603.29194v1), [agenticwire](https://www.agenticwire.news/article/mem0-zep-letta-agent-memory)). Claude-native memory + offline "Dreaming" consolidation now exist ([anthropic skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)).
- **Retrieval:** RRF hybrid (vector ⊕ graph), multi-granular embeddings, GraphRAG for multi-hop ([arXiv 2507.03226](https://arxiv.org/abs/2507.03226)). Karpathy "LLM-Wiki" on Claude Code + Obsidian is your exact stack, validated ([mindstudio](https://www.mindstudio.ai/blog/andrej-karpathy-llm-wiki-obsidian-codeex-second-brain)). Fully-offline Obsidian RAG exists ([ObsidianRAG](https://github.com/Vasallo94/ObsidianRAG)).
- **Network-engineering SOTA:** the digital-twin stack = **Batfish + Containerlab + Suzieq** wired into CI; Batfish gives a *vendor-independent, no-live-traffic* formal model for routing/ACL/what-if — the read-only, offline-safe "**prove it**" layer *beside* `cisco-assess` ([dev.to](https://dev.to/firstpasslab/building-a-network-digital-twin-with-batfish-containerlab-and-suzieq-a-practical-guide-17ol); [batfish.org](https://batfish.org/)). Cisco's own agentic-AI position: feed *structured* context (inventory/topology/standards) into the LLM via MCP — "engineers who feed real context into LLMs will dominate" ([blogs.cisco.com](https://blogs.cisco.com/learning/a-new-frontier-for-network-engineers-agentic-ai-that-understands-your-network)) — which validates your graphify-MCP + SSOT approach. SoT (NetBox/Nautobot) + pyATS/Genie anchor the deterministic layer.
- **Claude Code capabilities you under-use:** headless `claude -p` for scheduled runs; hooks you haven't wired (`PostToolUse`, `SessionEnd`, `PreCompact`, `SubagentStop`); Skills frontmatter + plugin packaging; `/memory` auto-memory; CLAUDE.md `@imports` + path-scoped `.claude/rules/*.md` ([code.claude.com/hooks](https://code.claude.com/docs/en/hooks.md), [/skills](https://code.claude.com/docs/en/skills.md), [/memory](https://code.claude.com/docs/en/memory.md)). *(A few of these — e.g. a `FileChanged` hook — are blog-sourced; verify against official docs before building.)*

**The most important external validation:** *you don't need new tools.* Every SOTA pattern maps onto Claude Code + graphify + Obsidian + your existing engine. The gap is wiring, not acquisition. **Batfish** is the one genuinely new component worth evaluating — as an offline, read-only formal verifier that adds a "prove it" layer your assessment currently lacks.

---

## 10. Phased roadmap — 6 phases, each with acceptance criteria

Sequenced so **safety rails precede autonomy** (you must be able to *measure* before you let it run). Each phase is independently valuable and independently shippable — you can stop after any phase and be better off.

### Phase 0 — Foundations & honesty (days)
*Make improvement measurable and fix the cheap stuff before turning on any loop.*
- Build the **golden-snapshot eval harness** (§6.2a) in `tests/` — the measuring stick.
- Adopt **`learnings.md`** discipline (verifiable-facts-only, <100 lines, read at SessionStart).
- Wire a **`SessionEnd`/`SubagentStop` hook** that auto-appends QA outcomes to the scorecard + tags bridge-candidates (removes manual promotion friction).
- Doc hygiene, **SSOT-safe**: the live graph is **5,905 nodes** (verified via `graph_stats` today). Do **not** hardcode that into `CLAUDE.md` — its soft "~5.4k" hint deliberately defers to `GRAPH_REPORT.md` as the authoritative owner (SSOT Law 1); at most nudge the soft hint and keep the pointer. Reconcile this plan's prose against MASTER_PLAN's already-executed §6.
- **Acceptance:** `pytest` includes an eval tier; a scorecard file exists and gains its first rows; no stale counts remain.

### Phase 1 — The feedback nerve (Weeks 1–2) · *highest leverage*
- Persisted **deliverable scorecard** + `scorecard trend` renderer.
- Build **`cisco_toolkit/calibration.py`** — the Track D PIR→`ScoringConfig` loop.
- **Acceptance:** a generator regression fails an eval before release; ≥2 weeks of scorecard rows; one `ScoringConfig` value moved by a labeled outcome (not by hand).

### Phase 2 — The clock (Weeks 2–4)
- Local cron → **headless `claude -p`** nightly, **propose-only**, budget-capped, circuit-broken.
- Assemble the **morning briefing** (evals + intel + rot-actions + open GI/REC + un-promoted lessons).
- **Acceptance:** a dated briefing appears at login; the run provably touched no device and pushed no branch; the circuit breaker trips correctly on 3 induced failures.

### Phase 3 — The eyes (Weeks 3–6)
- Stand up the **`research-lane`** worktree (egress-fenced): daily sweep + **GEPA** prompt-optimization.
- Emit **sanitized, signed `docs/intel/feed-*.md`** + `prompts/*.frozen.md`; repo consumes read-only.
- **Acceptance:** dated intel feed with sourced+scoped items; the air-gapped graph/engine reproduce byte-identical disconnected (no-egress invariant still green); one agent prompt improved by a frozen GEPA artifact.

### Phase 4 — Recall & connect-the-dots (Weeks 4–8)
- **RRF hybrid retrieval** over graphify ⊕ docs ⊕ **local vault-digest RAG** (Ollama, zero egress).
- **ADR-0001 amendment** for a one-way sanitized vault-digest the repo may read; **CoALA-label** stores; adopt agent-memory on the read-only analysts; **temporal fact-supersession**.
- **Acceptance:** an `/ask` answer visibly fuses graph + doc + vault-digest; a superseded fact stops resurfacing.

### Phase 5 — The six-angle mind + failure-class hardening (ongoing)
- **`/council`** grounded N-verifier panel (§7); orchestrator + nightly loop invoke it on consequential outputs.
- Attack the **five systemic failure classes** (§8): 3-state abstention type; independent-channel verification (byte-match citations + rendered-pixel); guard non-vacuity; CLI-path SSOT gate; rendered-output golden contract.
- **Evaluate Batfish** as an offline read-only formal verifier beside `cisco-assess`.
- **Acceptance:** `/council` returns grounded, refutation-first verdicts; each failure class has a mechanical guard that fails loudly; a Batfish spike report exists with a go/no-go.

---

## 11. Cost, risk & bounded-autonomy guardrails

**Cost posture (you flagged token spend explicitly):**
- The nightly loop is the only new *recurring* cost. Cap it: `--max-turns`, `--max-budget-usd` per run, a **daily ceiling**, and a **weekly report** of spend vs. value (briefings that led to action).
- Research-lane + GEPA are **bursty, not daily** — run on demand or weekly; GEPA's whole selling point is **35× fewer rollouts** than RL, so optimization is cheap relative to its lift.
- Parallel subagent fan-out (like the 8-agent audit that built this plan) is **token-efficient by design**: scouts read wide and return *distilled* briefs, keeping the orchestrator context lean. Use it deliberately; it's cheaper than one context reading everything.

**Hard guardrails (non-negotiable, from P-C):**
- **Propose-only.** Unattended runs write a PR/briefing; they never write a device, never `git push`, never merge.
- **Budget cap + circuit breaker** (disable after 3 consecutive failures) + process isolation.
- **Default permission mode** stays (never `bypassPermissions`) — the OS sandbox remains the only hard enforcement of read-only, per your existing trust-boundary note.
- **Egress stays fenced** to the research lane; the repo/graph/engine never fetch.

---

## 12. Red-team — how this plan could fail, and the mitigations

*(Refuting my own plan, because you asked for it.)*

- **The morning briefing becomes noise you stop reading.** → Ruthless relevance filter; verifiable-facts-only; ≤1 screen; every line links to an action or a number. Kill it if the weekly value-report shows no action taken.
- **The calibration loop overfits to a handful of PIRs.** → Require a minimum labeled-outcome count before it's allowed to move a parameter; keep changes small and reversible; keep a human in the release gate.
- **Autonomy drift / runaway cost.** → Caps + circuit breaker + propose-only (§11). Start the cron *manual-trigger* for a week before scheduling.
- **The eyes leak client data across the egress fence.** → Rule-3 sanitization on the crossing (identical to your vault bridge), one-way, signed, auditable; the repo consumes, never emits.
- **The vault amendment erodes the two-store separation.** → Only a *sanitized, read-only digest* crosses — not raw vault access; it's an *amendment with a guard*, not a repeal. If it feels wrong on review, Phase 4's recall still works on graph+docs alone.
- **The six-angle panel becomes theater** (six agents agreeing). → Independence (separate context), refutation-first default, evidence-cited lenses, report counterexamples not consensus. If a panel never dissents, it's miscalibrated — treat unanimous approval as suspicious.
- **You build all this and still don't *feel* the singularity.** → The feeling is the *scorecard trending up* + the *briefing landing every morning*. If Phases 1–2 don't produce that felt signal, stop and re-scope before Phases 3–5. Ship the feeling early.

---

## 13. Metrics — how you will *know* it's improving

The antidote to "it's always missing something" is a number that moves. Track, and put on the morning briefing:
- **Deliverable quality score** (eval suite) — trend line. *The headline.*
- **QA counterexamples per cycle** — should fall over time.
- **Calibration gap** (predicted verdict vs. real PIR outcome) — should shrink.
- **Regression escapes** (bugs that reached a deliverable) — should approach zero.
- **Lessons captured → promoted** (episodic → semantic) — the learning throughput.
- **Recall hit-rate** — % of `/ask` answers that fused ≥2 stores.
- **Nightly value** — briefings that led to an action / spend.

When these are visible and moving, the system *is* the compounding senior-engineer brain — and you can prove it, not just feel it.

---

## 14. Decision register — the 5 forks I need you to settle

*(I did not block on these — you asked to re-review before spending tokens. Each has my recommendation; settle them on your re-read and I'll proceed.)*

| # | Decision | My recommendation | Why it matters |
|---|---|---|---|
| **D1** | Strategic fork: depth/trust-first vs. breadth-first | **Depth/trust-first**, breadth client-gated | Aligns with your own saturation thesis; this whole plan is a depth/trust play |
| **D2** | Stand up the **egress-fenced research lane** (separate connected session for web + GEPA, frozen artifacts cross in)? | **Yes** — it's the only way to get "eyes," and it preserves the air-gap for repo/graph/engine | Unblocks daily research + prompt optimization without violating no-egress |
| **D3** | **Amend ADR-0001** to allow a one-way, sanitized, read-only **vault-digest** the repo may recall? | **Yes**, with the sanitization guard (not raw vault access) | Resolves the "he can't recall what he knows" barrier; recall still works without it, just weaker |
| **D4** | Add a **local LLM** (Ollama/LM-Studio) for offline embeddings/RAG? | **Yes** — zero egress, unlocks vault + doc retrieval | Required for Phase 4 recall; keeps everything offline |
| **D5** | Autonomy scope: **propose-only + hard budget cap + 3-fail circuit breaker**, manual-trigger for week 1? | **Yes** — start conservative, schedule once trusted | Bounds cost/risk; this is the safe on-ramp to "always running" |

---

### The bottom line

You asked whether this is the best you have. **The foundation is genuinely elite and the tools are the right ones — but it is not yet the best it can be, and the gap is small, specific, and buildable.** You don't need a bigger brain or a different stack. You need to give the brain you built a **clock, a feedback nerve, eyes, and recall** — each grounded in ground truth so it compounds instead of confabulates. Do Phases 0–2 and you will, for the first time, *see it improve every morning.* That is the feeling you've been missing — and it's weeks away, not years.

---

## Verification record

Independently adversarially reviewed 2026-07-06 (proposer≠verifier — the reviewer did not author this plan). **Core judged sound and confirmed against the repo:** the no-egress preservation argument (§6.3) holds; MASTER_PLAN §7 traps are respected (Ollama/Batfish are additive *offline* components, not trap-listed); the §8.4 CLI-path reconcile-gate gap is real (`_reconcile_gate` exists only in `webapp/backend/deliverables.py`; no `ssot.reconcile(` in any `cisco_toolkit/` generator); "no scheduler wired in" and "calibration.py / scorecard.jsonl unbuilt" confirmed. **Corrections applied after review:** (1) agent-memory adoption was understated → corrected to "3 of 8 configured, 1 written" (was "1 of 8"); (2) dropped an unverifiable "26 lessons" count; (3) removed a Phase-0 recommendation to hardcode the graph node-count into `CLAUDE.md`, which would itself have violated SSOT Law 1 — the soft hint must keep deferring to `GRAPH_REPORT.md`; (4) strengthened the honesty that the D3 vault-digest reverses a *settled* ADR-0001 decision, not a default. Remaining open items are operator decisions (§14), not errors.
