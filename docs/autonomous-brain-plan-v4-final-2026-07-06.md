# The Autonomous Senior-Engineer Brain — v4 FINAL (decisions closed)

**Supersedes the open questions in** [`autonomous-brain-plan-2026-07-06.md`](autonomous-brain-plan-2026-07-06.md) (v3) · **grounded by** [`autonomous-brain-plan-v3-validation-2026-07-06.md`](autonomous-brain-plan-v3-validation-2026-07-06.md)
**Date:** 2026-07-06 · **Status:** APPROVED FOR BUILD — every fork resolved below; no sign-off pending.

> **The system in one sentence:** wire **six nerves** — a clock, a feedback nerve, eyes, recall, a **remediation nerve** (self-healing), and a **domain-knowledge layer** (the DC/Enterprise/SP/Security "team") — onto the existing top-tier foundation, each nerve nailed to ground truth, each unattended action propose-only.

---

## 1. Decision ledger — all forks closed

| # | Decision | **Resolution** | Rationale (evidence in the validation doc) |
|---|---|---|---|
| D1 | Strategic fork | **Depth/trust-first; breadth client-gated** | Your own saturation thesis; this whole plan is a depth play. |
| D2 | Egress-fenced research lane | **YES** — Phase 5 | Only way to get "eyes" without breaking no-egress for graph/engine. |
| D3 | ADR-0001 vault-digest amendment | **YES, with sanitization guard** — Phase 5 | Recall works on graph+docs first; the vault digest is additive, one-way, read-only. |
| D4 | Local LLM (Ollama) for offline RAG | **YES** — Phase 5, when recall needs it | Zero-egress; ObsidianRAG proves it's off-the-shelf. |
| D5 | Autonomy scope | **Propose-only + budget cap + max-turns + 3-fail breaker; manual-trigger week 1** | Confirmed production pattern; safe on-ramp. |
| **D6** | **Domain "team": standing agents vs. retrieval-packs** | **Retrieval-selected skill-packs + on-demand `/council` lenses. NOT standing agents.** | MAS-PromptBench: coordination/optimization go **negative at 8–10 agents**; you are at 8. Packs scale to N domains at ~zero coordination cost. |
| **D7** | GEPA scope | **One prompt at a time, golden-eval-gated. Never roster-wide.** | Multi-agent prompt-opt swings +24 to **−16 pp** by config; no topology beat single-agent. |
| **D8** | `/council` shape | **Independent, separately-contexted, refute-first lenses + majority. No cross-critique / no debate.** | Debate underperforms independent-sample majority; deliberation erased up to 72% of critical facts. |
| **D9** | Batfish scope | **CLI/SSH half only; check parse-status per config. Controller-REST (ACI/vManage) stays on existing detectors.** | ACI/APIC has zero Batfish coverage; "platform supported" ≠ "feature parsed." |
| **D10** | RRF hybrid retrieval | **Ship as an experiment with its own eval, not as proven SOTA.** | 2026 survey calls multi-signal hybrid "largely unexplored." |
| **D11** | `calibration.py` activation | **Descriptive-only until N ≥ 5 labeled PIR outcomes; then small, reversible, human-gated moves.** | Few engagements → overfitting risk; don't let 2 PIRs re-tune the engine. |
| **D12** | Memory compression | **Add a protected, never-compressible tier for safety constraints.** | Consolidation silently deletes rare-but-vital facts by the 3rd pass. |
| **D13** | Cost posture | **Treat nightly `claude -p` as real metered money (separate pool); daily ceiling + weekly spend-vs-action report.** | Headless bills outside the interactive subscription (mid-2026). |

---

## 2. Architecture — six nerves on the existing foundation

```
                    ┌──────────── EYES (egress-fenced research-lane worktree) ────────────┐
                    │  daily PSIRT/advisory + field sweep · GEPA (1 prompt/run, eval-gated)│
                    │  → Rule-3-sanitized, signed docs/intel/feed-*.md + prompts/*.frozen  │
                    └───────────────────────────────┬────────────────────────────────────┘
                                                     │  frozen sanitized artifacts ONLY
  ┌──────────────────────────────────────────────── AIR-GAPPED REPO (no-egress doctrine intact) ─────────────┐
  │                                                                                                            │
  │  CLOCK ───────►  nightly claude -p (propose-only, metered-budget-capped, 3-fail breaker)                  │
  │                  runs evals · agent-system SELF-CHECK · consumes intel · assembles MORNING BRIEFING       │
  │                                                                                                            │
  │  FEEDBACK ────►  golden-snapshot evals ⊕ scorecard.jsonl(+trend) ⊕ calibration.py (gated N≥5)             │
  │                  distills → learnings.md (verifiable facts only) → GEPA queue                             │
  │                                                                                                            │
  │  RECALL ──────►  RRF hybrid: graphify(graph) ⊕ docs(vector) ⊕ vault-digest(local Ollama)                  │
  │                  CoALA labels · temporal supersession · PROTECTED constraint tier (never compressed)      │
  │                                                                                                            │
  │  DOMAIN LAYER ►  DC/ACI · Enterprise/SD-Access · SP/MPLS-SR · Security/ISE-TrustSec skill-packs           │
  │  (the "team")    selected by architecture_coverage · surfaced as on-demand /council lenses                │
  │                                                                                                            │
  │  REMEDIATION ─►  drift → root-cause → MOP(+rollback) → twin-verify → PR+CAB → human → NRFU-confirm         │
  │  (self-healing)  PROPOSE-ONLY. never a device write. your existing MOP+NRFU loop, drift-triggered.        │
  │                                                                                                            │
  │  /council ────►  grounded N-verifier panel (independent lenses + majority) on consequential outputs       │
  └────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Carried, unchanged, binding:** read-only by default; proposer ≠ verifier; evidence-grounded & coverage-honest ("not observed" ≠ "healthy"); one source of truth; no-egress for graph + engine; default permission mode (never `bypassPermissions`).

---

## 3. Roadmap — sequenced by leverage → dependency → risk

Each phase is independently shippable and independently valuable. Safety/measurement precede autonomy; cheap-additive precede egress-heavy; the **domain "team" and self-healing you explicitly asked for are prioritized ahead of the research/recall machinery.**

### Phase 0 — Measurement foundations *(in progress on this branch — finish it)*
**Already live:** `/briefing` ([`morning-briefing.sh`](../.claude/hooks/morning-briefing.sh)); scorecard **schema** ([`docs/quality/README.md`](quality/README.md)); `docs/briefings/` populating.
**Build:**
- Golden-snapshot eval harness in `pytest` (deterministic checks: SSOT reconcile clean, all 10 Laws present, citations byte-match) + tiered (smoke per change, full on release).
- **Wire the scorecard appender** — a `SessionEnd`/`SubagentStop` hook that appends each `/qa` verdict to `scorecard.jsonl`.
- `learnings.md` discipline (< 100 lines, verifiable facts only, read at SessionStart).
- **Protected-constraint memory tier** (D12): a pinned, never-compressible store for safety rules.
**Guardrail:** absence reported as absence (empty scorecard says "no entries," never "healthy").
**Acceptance:** `pytest` has an eval tier; a `/qa` run appends a real row; a pinned constraint survives a simulated compression pass.

### Phase 1 — The feedback nerve *(highest leverage)*
- Scorecard **trend renderer** (`scorecard trend`) — the line you watch go up.
- `cisco_toolkit/calibration.py` — join real PIR/war-room outcomes vs. pre-cutover verdicts → tune `ScoringConfig`. **Gated: descriptive-only until N ≥ 5 labeled outcomes** (D11).
**Acceptance:** a generator regression fails an eval *before* release; ≥ 2 weeks of scorecard rows render a trend; calibration refuses to move a parameter below the N-floor and says so.

### Phase 2 — The clock
- Local Task Scheduler → **headless `claude -p`**, propose-only nightly: run evals, run the Phase-4 self-check, consume intel, surface open GI/REC + unpromoted lessons, assemble the **morning briefing** (≤ 1 screen, every line a number or link).
- **Cost-honest (D13):** `--max-turns`, `--max-budget-usd`, daily ceiling, weekly spend-vs-action report; **3-fail circuit breaker + 30-min cooldown**; **manual-trigger for week 1**, schedule only once trusted.
**Acceptance:** a dated briefing appears at login; the run provably touched no device and pushed no branch; the breaker trips on 3 induced failures; week-1 spend is within ceiling.

### Phase 3 — The domain "team" as retrieval-packs *(your core ask — ahead of the research lane)*
**The decision (D6): function agents are the *workflow*; domain expertise is a *retrieval/skill layer* they pull in — not a parallel headcount.**
- Build four **skill-packs**, each a `SKILL.md` + domain detector knowledge + a domain review checklist:
  **DC/ACI** · **Enterprise/SD-Access** · **SP/MPLS-SR** · **Security/ISE-TrustSec-firewalls**.
- **Wire pack-selection to `_ARCH_COVERAGE_REGISTRY`** (`architecture_coverage`): the snapshot already knows which fabrics are present — load the DC pack iff ACI is present, the SP pack iff MPLS/SR is present, etc. The team that shows up is the one the network needs.
- Expose each pack as an **on-demand `/council` lens**, invoked only for consequential outputs touching that domain.
- **Promotion rule:** a pack becomes a standing sub-agent *only* when a real engagement sustains the load **and** the eval shows the pack alone is insufficient (client-gated, per D1).
**Guardrail:** the standing roster stays at 8 (D6); no new always-on agents.
**Acceptance:** an assessment of an ACI+ISE snapshot auto-loads the DC and Security packs and nothing else; a `/council` on a security-touching claim shows a grounded Security lens citing evidence.

### Phase 4 — Self-healing *(propose-only, both kinds)*
- **Network remediation nerve:** **detect** (snapshot / `--compare` drift, or an intel-feed PSIRT hit) → **root-cause** (topology + audit agents) → **author remediation MOP with rollback** (`mop-change-author`) → **twin-verify** (Batfish for the CLI half, Phase 6) → **propose as PR + CAB** → **human approves** → **NRFU confirms recovery** (`nrfu-validator`). Never a device write; the change is always a reviewable artifact.
- **Agent-system self-check** (runs in the nightly clock): every guard/hook is **non-vacuous** (a *skipped* test is **red**), graph freshness within threshold, scorecard is being written, protected constraints intact. Failures lead the briefing.
**Guardrail:** proposer ≠ verifier — the remediation author never certifies its own fix (NRFU is independent).
**Acceptance:** an induced drift produces a proposed remediation PR (never applied) that NRFU can check; a deliberately-broken guard shows **red**, not green, in the next briefing.

### Phase 5 — Eyes + Recall *(egress-dependent; heaviest, so last)*
- **Research lane** (egress-fenced worktree): daily sweep + **GEPA one prompt/run, eval-gated (D7)**; emits sanitized, signed `docs/intel/feed-*.md` + `prompts/*.frozen.md`; repo consumes read-only; no-egress invariant stays byte-identical-reproducible disconnected.
- **RRF hybrid retrieval** (D10, as an experiment with its own eval) over graphify ⊕ docs ⊕ **local vault-digest RAG (Ollama, D4)**.
- **ADR-0001 amendment (D3)** for the one-way sanitized vault digest; **CoALA-label** stores; adopt agent-memory on the read-only analysts; **temporal fact-supersession**.
**Acceptance:** a dated intel feed with sourced+scoped items; the air-gapped graph/engine reproduce byte-identical disconnected; one agent prompt improved by a frozen GEPA artifact *that passed the eval gate*; an `/ask` answer visibly fuses graph + doc + vault-digest; a superseded fleet-count stops resurfacing.

### Phase 6 — Batfish spike *(parallel; feeds Phase-4 twin-verify)*
- Evaluate Batfish as an **offline read-only formal verifier for the CLI/SSH half only (D9)**; check parse-status / ignored-lines per config; ACI/vManage explicitly out of scope.
**Acceptance:** a go/no-go spike report; if go, it plugs into the remediation nerve's twin-verify step for CLI-config changes.

### Threaded throughout — the five systemic failure-class guards
3-state abstention type (`NOT_COLLECTED`/`COLLECTED_EMPTY`/`NOT_APPLICABLE`); real-format fixtures + byte-match citation + rendered-pixel checks; guard non-vacuity self-checks; CLI generation path through the same `ssot.reconcile` pre-emission gate as the webapp; extend the golden contract to rendered artifacts (DOCX/PDF/figures/TOC).

---

## 4. Metrics — definition of "it's improving"

On the morning briefing, every value a number or a link:
- **Deliverable quality score** (eval suite) — the headline trend line.
- **QA counterexamples/cycle** ↓ · **calibration gap** (predicted vs. real PIR) ↓ · **regression escapes** → 0.
- **Lessons captured → promoted** (episodic → semantic throughput).
- **Recall hit-rate** — % of `/ask` answers fusing ≥ 2 stores.
- **Nightly value** — briefings that led to an action / spend (kill the briefing if this stays zero).
- **Self-heal health** — guards green, drift proposals raised vs. accepted.

---

## 5. Explicitly NOT building *(the anti-scope — as important as the scope)*

- **No standing DC/SP/Security agents** (D6) — packs + lenses instead.
- **No roster-wide GEPA** (D7) — one prompt at a time, eval-gated.
- **No debate/round-table `/council`** (D8) — independent lenses + majority only.
- **No Batfish for ACI/vManage** (D9) — CLI half only.
- **No auto-apply anything** — every unattended action is propose-only: a PR or a briefing, never a device write, never `git push`, never a merge.
- **No self-scoring loop** — every loop closes on a test, a reconciled fact, a labeled outcome, or a byte-matched citation.
- **The MASTER_PLAN §7 traps stay binding** — no rewrite, no ntc-templates default, no DuckDB, no PyPI-by-reflex, no scrapli/Nornir. Ollama + Batfish are the only new components, both additive and offline.

---

## 6. The first move

Phase 0 is two-thirds done. The single highest-impact next build is the **golden-snapshot eval harness + wiring the scorecard appender** — until a `/qa` verdict persists a row, "improvement" is unfalsifiable and nothing downstream can be trusted to compound. Everything else waits on being able to measure.
