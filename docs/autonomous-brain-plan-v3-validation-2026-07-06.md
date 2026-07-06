# Validation & best-possible-plan delta — the Autonomous Senior-Engineer Brain (v3)

**Reviews:** [`docs/autonomous-brain-plan-2026-07-06.md`](autonomous-brain-plan-2026-07-06.md) (the v3 plan)
**Date:** 2026-07-06 · **Method:** deep-research fan-out (5 angles, 19 sources, 94 extracted claims) + repo grounding + operator-goal reconciliation
**Verdict in one line:** The plan's **spine is confirmed** against current (mid-2026) evidence. Six corrections and two genuine gaps — **self-healing** and the **DC/Enterprise/SP/Security team** — are what stand between it and "best-possible." None are rebuilds.

---

## 0. Provenance & honesty note (read this first — coverage-honest, per Law 3)

This validation ran the `deep-research` workflow. **What completed:** the scope, search, fetch, and claim-extraction phases — 5 research angles, 19 sources (11 primary papers/docs, 8 practitioner blogs), 94 candidate claims, each fetched with **verbatim quotes** from the primary source. **What did NOT complete:** the workflow's independent 3-vote adversarial verifier panel died entirely on a Fable-5 rate limit — **0 of 25 claims received a single verification vote.** So these claims are *primary-source-grounded with quotes*, but were **not** independently cross-examined by the panel.

To avoid "not-verified silently becoming confirmed," the two findings that most **change** the plan — the MAS-PromptBench team-size result and the Cisco closed-loop self-healing direction — were **re-verified by hand** (Opus 4.8, off the rate limit) against their primary sources. Confidence is tiered below: **[V]** = I personally re-read the primary source; **[Q]** = verbatim quote captured in the fetch phase from a primary source; **[B]** = blog/practitioner source; **[?]** = asserted but single-sourced or unresolved.

---

## 1. CONFIRMED — the plan's spine holds

These are the load-bearing premises. Every one survived.

| # | Plan premise | Evidence | Tier |
|---|---|---|---|
| 1 | **Ground every loop; intrinsic self-scoring is unreliable (P-A)** | MIT TACL *When Can LLMs Actually Correct Their Own Mistakes*: "no prior work demonstrates successful self-correction … [when feedback comes only from] prompting the model itself"; self-correction **does** work "when reliable external feedback is available (e.g. code executors)." Your pytest/`reconcile()`/`affected()` are exactly the right verifiers. | [Q] |
| 2 | **Store verifiable facts, never self-assessments (P-B)** | Databricks *Memory scaling for AI agents* (primary, the real source behind the plan's mem0.ai citation): "a stored mistake gets retrieved later as evidence, and agents reuse previously wrong results with increased confidence." | [Q] |
| 3 | **Consolidation > accumulation (P-E)** | Same Databricks source: keeping memory tractable "requires periodically distilling episodic memories into compressed semantic rules, plus active … deduplication, pruning … and resolving old-vs-new conflicts." | [Q] |
| 4 | **Bounded autonomy: budget cap + max-turns + 3-fail circuit breaker (P-C)** | Claude Code headless has native `--max-turns` (hard cap, exits with error) and `--max-budget-usd` (per-run ceiling). The exact "3 consecutive failures → cooldown" pattern is running in production (`MAX_FAILURES = 3; COOLDOWN_MS = 30*60*1000`). | [Q][B] |
| 5 | **Temporal fact-supersession (RECALL-4)** | Zep/Graphiti (arXiv 2501.13956): temporally-aware KG; **+18.5%** on LongMemEval, **−90%** latency vs baseline. Real and as described. | [Q] |
| 6 | **RRF hybrid retrieval graph⊕vector (RECALL-1)** | arXiv 2507.03226: RRF fusion of vector + graph beats vector-only by **up to 15%** (65.83% vs 50.80%, CCM Chat). | [Q] |
| 7 | **CoALA episodic/semantic/procedural taxonomy** | 2026 memory survey (arXiv 2603.07670) still organizes agent memory into working/episodic/semantic/procedural — the frame is settled. | [Q] |
| 8 | **Offline vault RAG is feasible (D4)** | ObsidianRAG: fully local, Ollama/LM-Studio-backed, zero cloud dependency. Falsifiable by running it air-gapped and watching for egress. | [Q] |
| 9 | **`/council` = independent grounded lenses + majority** | Consistent with the debate literature *only in this exact shape* — see §2.2 for the sharp caveat. | [V] |

**GEPA headline — confirmed verbatim but re-scope the number.** arXiv 2507.19457: *"Across six tasks, GEPA outperforms GRPO by 6% on average and by up to 20%, while using up to 35× fewer rollouts."* [Q] The plan's "20% / 35×" are **best-case bounds**; the honest average is **6%**. GEPA is real, ICLR-2026-accepted, and the right tool — just don't quote its ceiling as its expectation.

---

## 2. REFUTED / OVERCLAIMED — six corrections

### 2.1 GEPA does **not** safely transfer to your 8-agent roster — *[V], the biggest correction*
**MAS-PromptBench: When Does Prompt Optimization Improve Multi-Agent LLM Systems?** (Bai & Shi, arXiv 2606.23664, 23 Jun 2026 — paper identity and conditional framing personally verified). Multi-agent prompt optimization is **highly configuration-dependent**: gains **up to +24.0 pp** in some task/topology setups, **losses as large as −16.0 pp** in others; the average gain is **smaller than the single-agent baseline in every topology tested**; and gains **shrink with team size, turning negative at 8–10 agents.**

→ **Consequence:** the plan's assumption that GEPA's single-agent wins carry over to the roster is unsafe. **Optimize one prompt at a time, each gated by the golden-snapshot eval (§1 feedback nerve), never roster-wide.** This finding also directly constrains the "add DC/SP/Security agents" ask — see §3.2.

### 2.2 Kill any "debate" framing in `/council`; keep only independent-sample majority — *[Q]*
ICLR source (openreview `IkmD3fKBPQ`): multi-agent **debate/critique underperforms simple self-consistency** (majority vote over independent samples); its apparent gains "come from consistency rather than mutual correction." Combined with the plan's own cited *Deliberative Illusion* (arXiv 2606.03032: deliberation erased up to **72%** of issue-critical facts). → `/council` is sound **only** as *independent, separately-contexted, refute-first lenses aggregated by majority* — exactly as the plan specifies. **Explicitly forbid** the round-table variant where agents read and critique each other's drafts. Independence is the whole value.

### 2.3 Batfish is a **CLI-only, partial** verifier — scope the Phase-5 spike accordingly — *[V]*
Batfish's official supported-devices list covers Cisco **IOS, IOS-XE, IOS-XR, NX-OS, ASA** (so no NX-OS *platform* gap, contrary to a common worry) — **but ACI/APIC appears nowhere**, not even in limited-support. Your **controller-REST channel (ACI/APIC, Catalyst SD-WAN/vManage) gets zero Batfish coverage.** And "platform supported" ≠ "every feature parsed" — the docs concede unsupported config features exist with no per-feature list. → Batfish can be a "prove-it" formal layer for the **SSH/CLI half** of the fleet only; you must check its parse-status / ignored-lines per config; and your existing controller-REST detectors remain the *sole* verifier for fabric controllers. Scope the go/no-go spike to that reality.

### 2.4 RRF-hybrid retrieval is **ahead of**, not behind, the field — *[Q]*
The 2026 survey (arXiv 2603.07670) calls rich multi-signal hybrid retrieval "**largely unexplored**," not settled practice. The plan's RRF choice is a *reasonable bet*, but frame it as an **experiment with its own eval**, not proven SOTA. Also honest-scoping: the 2507.03226 evidence is two SAP enterprise datasets, not general multi-hop benchmarks — "beats vector-only on multi-hop" is true *in spirit for entity-heavy corpora*, mildly overstated as a general result.

### 2.5 The nightly clock is **real metered money**, billed separately — *[B]*
As of mid-June 2026, headless/scheduled `claude -p` bills from a **separate metered pool, outside** the interactive subscription. The CLOCK is not "free under my plan" — it is a recurring $ line. This *reinforces* the plan's budget-cap/daily-ceiling design; just budget it as cash and put spend-vs-action on the weekly report as the plan already says.

### 2.6 Memory consolidation can **silently delete a rare, critical constraint** — *[Q], add a guard*
2026 survey: repeated summarization "silently destroy[s] rare-but-vital facts (e.g. a 'never call the production database' constraint vanishing by the third compression pass)," and memory failures are **silent** (no exception, no log). For a network engineer this is lethal — a "never touch device X in business hours" or a rollback-trigger could be compressed away. → **Add to P-E: a protected, never-compressible tier** for safety constraints, with a nightly non-vacuity check that they still exist (this *is* failure-class 3 applied to memory).

---

## 3. MISSING — the two things your goal adds that the plan under-serves

Your stated goal: *"self improving, self healing, automation expert, a team of Cisco advanced-services engineers — DC, enterprise, SP, security."* The plan nails **self-improving**. It under-delivers on **self-healing** and barely touches the **domain team**.

### 3.1 SELF-HEALING — name it, and bound it to propose-only

Cisco's own flagship direction (Cloud Control, newsroom Jun 2026 — verified [V]) is a full closed loop: *"spotting trouble, identifying causes, carrying out fixes, testing changes before deployment, and confirming the user experience has recovered"* — but crucially *"while humans stay in control"* and *"keeping actions visible and governed."* Even the vendor pushing hardest keeps a human gate and pre-deployment verification. That is the ceiling to aim at, and it maps cleanly onto what you already have.

**Two kinds of self-healing, both propose-only:**

- **(a) Network self-healing = a drift-triggered remediation loop.** You already own every piece: **detect** (snapshot / `--compare` diff surfaces drift or a new PSIRT hit from the intel feed) → **root-cause** (topology-reachability + audit agents) → **generate a remediation MOP** (the `mop-change-author` agent already authors MOPs with rollback) → **verify on a digital twin** (Batfish for the CLI half; §2.3) → **propose as PR + CAB** → **human approves** → **NRFU confirms recovery** (`nrfu-validator`). This *is* self-healing inside your read-only doctrine — the change is always a reviewable artifact, never a device write. The plan should add this as an explicit **REMEDIATION nerve**: it is your existing MOP+NRFU loop, *triggered by drift* instead of by a human typing `/deliverables`.

- **(b) Agent-system self-healing.** The plan has the parts but never frames them as healing: failure-class 3 (guards fail loudly), the circuit breaker, hook health. Make the nightly clock run a **self-check**: every guard/hook is non-vacuous (a *skipped* test is **red**, not green), graph freshness within threshold, the scorecard is actually being written, and the protected memory tier (§2.6) is intact. When a check fails, the briefing leads with it. That is the system noticing and repairing its own drift.

### 3.2 The "team of DC / Enterprise / SP / Security engineers" — the biggest gap

Your roster is **function-scoped** (assess / audit / topology / design / MOP / NRFU / QA / release). You asked for **domain specialists** — the Cisco Advanced Services practice-team model (DC/ACI, Enterprise/SD-Access, SP/MPLS-SR, Security/ISE-TrustSec-firewalls). The plan doesn't address this at all.

**Do not solve it by adding four standing agents.** §2.1's MAS-PromptBench result is decisive here: coordination and optimization **degrade with team size and go negative at 8–10 agents** — and you are already at 8. A 12-agent standing roster walks straight into the zone the evidence flags as harmful, and every standing agent is metered $.

**The right decomposition — the key insight of this review:**
> **Function agents are the *workflow*; domain expertise is a *retrieval/skill layer* they pull in — not a parallel headcount.** This is mixture-of-experts by *retrieval*, which scales to N domains at ~zero coordination cost, versus MoE by *standing agents*, which the evidence says breaks down exactly at your size.

Concretely, in dependency order:
1. **Encode each domain as a skill-pack** — `DC/ACI`, `Enterprise/SD-Access`, `SP/MPLS-SR`, `Security/ISE-TrustSec-FW` — each a `SKILL.md` + domain detector knowledge + a domain review checklist. The function agents retrieve the pack via the RECALL nerve.
2. **Wire pack-selection to `architecture_coverage`.** Your `_ARCH_COVERAGE_REGISTRY` *already knows* which domains a snapshot contains (SD-Access/LISP, TrustSec/CTS, ACI, SD-WAN…). Load the DC pack **iff** ACI is present, the SP pack iff MPLS/SR is present, etc. The "team that shows up" is the one the network actually needs — the practice-team model, implemented as data.
3. **Add domain lenses to `/council`**, invoked **on demand** for consequential outputs touching that domain (a "Security lens," an "SP/MPLS lens"), drawn from the same packs. On-demand, not standing.
4. **Promote a pack to a full standing sub-agent only when a real engagement sustains the load** *and* the eval shows the pack alone is insufficient. This is **client-gated**, matching your own depth-first D1 resolution — build breadth when an engagement pulls it, not speculatively.

This gives you the DC/Enterprise/SP/Security "team" you asked for, keyed to the actual network, at the cost of markdown + retrieval rather than four more metered agents fighting the coordination ceiling.

### 3.3 One more gap: calibration ground-truth is scarce
`calibration.py` needs labeled PIR/war-room outcomes to move `ScoringConfig`, and a single operator has few engagements. The plan's red-team flags overfitting; make it a **hard gate**: calibration is **descriptive-only until N labeled outcomes exist** (pick a floor, e.g. N ≥ 5), and parameter moves stay small, reversible, and human-gated at the release. Don't let two PIRs re-tune the engine.

---

## 4. The ranked, best-possible plan delta (reconciled with what's already built)

**Already live on `feat/autonomy-phase0-briefing` (verified in-repo):** `/briefing` works ([`.claude/hooks/morning-briefing.sh`](../.claude/hooks/morning-briefing.sh), no-egress, fail-open, dated output under `docs/briefings/`); the scorecard **schema** exists ([`docs/quality/README.md`](quality/README.md)) but the **appender is unwired**; `docs/briefings/briefing-2026-07-06.md` is populating. So the sequence starts mid-Phase-0:

| Rank | Action | Why here | Source of the correction |
|---|---|---|---|
| **1** | **Finish the FEEDBACK NERVE:** build the golden-snapshot eval suite + **wire the scorecard appender** (SessionEnd/SubagentStop hook) so `/qa` verdicts persist. Add the **protected-constraint memory tier**. Gate `calibration.py` behind **N labeled outcomes**. | Highest leverage; the plan agrees; it's the half-built piece on this branch. | §2.6, §3.3 |
| **2** | **CLOCK:** nightly propose-only briefing, budgeted as **real metered $** (separate pool), daily ceiling, 3-fail breaker + cooldown. | Confirmed pattern; just cost-honest. | §2.5, §1 |
| **3** | **DOMAIN PACKS (your "team") — before the research lane.** Build DC/Enterprise/SP/Security skill-packs; wire selection to `architecture_coverage`; add domain lenses to `/council`. **Do not expand the standing roster.** | It's what you actually asked for, and cheaper/safer than more agents. | §3.2, §2.1 |
| **4** | **SELF-HEALING, named:** add the drift→MOP→twin-verify→PR→NRFU **remediation nerve** (propose-only) + the nightly **agent-system self-check**. | Your explicit goal; you already own the parts. | §3.1 |
| **5** | **EYES (research lane) + GEPA** — but GEPA **one prompt at a time, eval-gated, never roster-wide.** | Research lane is right; GEPA transfer is not safe. | §2.1 |
| **6** | **RECALL:** RRF hybrid + offline vault digest (Ollama) — ship as an **experiment with its own eval**; ADR-0001 amendment as planned. | Ahead of the field, not proven. | §2.4 |
| **7** | **Batfish spike — CLI/SSH half only.** Check parse-status; ACI/vManage stay on your controller-REST detectors. | Genuine coverage gap. | §2.3 |

---

## 5. Bottom line

The v3 plan is **not overbuilt and not naive** — its grounding thesis, bounded-autonomy guardrails, feedback-first sequencing, temporal supersession, RRF retrieval, and independent-verifier `/council` all hold against mid-2026 evidence. The delta to "best-possible" is six refinements and two additions:

- **Refine:** GEPA one-prompt-at-a-time (not roster-wide); `/council` independent-only (no debate); Batfish CLI-only; RRF-as-experiment; metered-cost honesty; pin critical constraints against compression.
- **Add:** a **propose-only self-healing remediation loop** (you own every part), and the **DC/Enterprise/SP/Security "team" as retrieval-selected skill-packs + council lenses** keyed to `architecture_coverage` — *not* four more standing agents, which the evidence says would make your already-8-strong roster worse.

None of this is a rebuild. It is the same four nerves you specified, wired with two more — a **remediation nerve** and a **domain-knowledge layer** — and corrected at six points where the field's evidence is sharper than the plan assumed.

---

### Sources (19; primary unless noted)
- GEPA — arXiv 2507.19457 · MAS-PromptBench — arXiv 2606.23664 (Bai & Shi, Jun 2026) · Self-correction — MIT TACL `tacl_a_00713`; openreview `IkmD3fKBPQ` · Deliberative Illusion — arXiv 2606.03032
- Memory — Databricks `memory-scaling-ai-agents`; 2026 survey arXiv 2603.07670; Zep/Graphiti arXiv 2501.13956; mem0.ai (blog) · Retrieval — arXiv 2507.03226; ObsidianRAG (github)
- Scheduled agents — kjetilfuras.com (blog); hidekazu-konishi.com (blog); dev.to/mjmirza (blog); mindstudio.ai (blog)
- Network — Batfish supported-devices (readthedocs); Cisco Cloud Control newsroom (Jun 2026); firstpasslab digital-twin (blog)

*Verification caveat (§0): the workflow's independent 3-vote panel did not run (rate limit); claims are primary-source-quoted, and the two plan-altering findings (MAS-PromptBench, Cisco Cloud Control) were re-verified by hand.*
