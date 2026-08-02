# The Best‑Possible Plan — ground‑truth synthesis of the two Fable‑5 plans

*Authored 2026‑07‑08. Synthesises the two one‑shot Fable‑5 plans — `ceiling-order-90-day-proof-campaign.md`
and `compass_artifact…` — by verifying every load‑bearing claim against the actual repo and the live‑market
facts. Fable wrote both plans **blind to this code and the live web**; the value added here is the ground‑truth
correction that only the code can supply. This is a plan‑only deliverable — no code changed by authoring it.*

---

## 0. Verdict in one line

Both Fable plans share the correct spine — **proof before build · judge before corpus · don't arm the clock ·
freeze breadth/recall** — and that spine survives ground‑truth scrutiny. But **both spend their first 3–5 weeks
telling you to *build* a trust instrument you have already built.** The best‑possible plan is therefore not
*build* — it is **MEASURE · FREEZE · VOID · AUDIT**: four runs and decisions (~2 focused days) that convert
built‑but‑unproven infrastructure into your first trustworthy numbers, led by the one **perishable** action
neither more building nor more reasoning can substitute for.

## 1. The correction Fable could not make — the instrument is already built

| Both plans say **BUILD** (Weeks 1–5) | Actual repo state | Evidence |
|---|---|---|
| Seeded known‑bad **defect panel** (~12 defects) | ✅ Built — the exact 12 | `cisco_toolkit/defect_panel.py` `D‑01…D‑12`; classes map 1:1 to `ceiling-order` Order‑2 |
| **Cross‑family** judge (dodge self‑preference) | ✅ Built + Ollama running | `ollama_judge.py` (repo root, outside the no‑egress fence) |
| `judge_tnr` **trust field** on the scorecard | ✅ Built — cites the exact paper | `scorecard.py`; `docs/quality/README.md` cites Jain et al. `2510.11822` |
| `calibration.py` readiness→outcome join, descriptive until N≥5 | ✅ Built, D11‑gated | `cisco_toolkit/calibration.py` |
| **Fault‑injected** calibration rows ("strongest class, run first") | ✅ Built — 7 rows | `docs/quality/pir_outcomes.jsonl`, all `source_class: fault-injected` |
| **Prediction Certificate** (`precert`) | ✅ Built (diff form) | `cisco_toolkit/precert.py`, schema `precert/1` |

**Consequence:** `compass` Phase 0 + half of Phase 1, and `ceiling-order` Orders 2–3's *instruments*, already
exist. The current branch is literally `chore/scorecard-first-real-rows`. The plans tell you to build an
instrument you are holding.

## 2. The genuinely‑pending frontier

| # | Pending action | Why it is the real work now | Effort |
|---|---|---|---|
| **1** | **RUN `defect_panel` → record the baseline TNR** on the ledger | Harness exists; the *number* was never written to the scorecard (`judge_tnr` null → every verdict PROVISIONAL by your own README). `compass` §9‑#3 / `ceiling-order` Order‑2: "measure the baseline first." | ½ day |
| **2** | **Freeze the live prediction** — extend `precert` to a *pre‑window readiness* cert, sign+commit **before** the maintenance window | `precert` today is a before⋈after **diff** cert; Order 1 needs the **single‑snapshot prediction freeze** = REAL calibration **row #1** (you have **0** REAL; 7 are surrogates). **Perishable, unsubstitutable.** | 8–16 h |
| **3** | **VOID the 2‑row all‑APPROVE scorecard** as instrument‑unvalidated | Both rows `APPROVE`, `judge_tnr` absent. Keeping them as data is confidence‑theater in your own ledger until #1 lands. | ~1 h |
| **4** | **Phantom‑health audit** — grep every "healthy/redundant" claim vs the collection manifest | Fleet is **303/253/50**; the ~50 uncollected core/dist tier is real. A "healthy" claim over an uncollected node is a standing law‑violation in a client's hands. | 2–4 h |

Everything past this — calibration corpus to N≥20 public rows, the blind head‑to‑head, freeze/void the
self‑scored matrix, the clock arm‑decision — is real but genuinely later and already well‑specified by both
plans. Do not pull it forward.

## 3. Two sharpenings latent in the code (neither plan could see them)

1. **Report the baseline TNR as *two* numbers.** `defect_panel` tags each defect `detect: deterministic | both`.
   The deterministic classes are already caught bias‑free by `eval_harness` — so the **LLM judge's *marginal*
   TNR is tested only by the `both`‑class defects.** Report `deterministic‑arm TNR` (≈1.0 by construction)
   separately from `LLM‑judge incremental TNR on the *both* classes`. Sharper than either plan specified.
2. **Order 1 is a *small, precise* extension, not a new module.** Because `precert.py` already exists as a diff
   cert, freezing the prediction reuses its sign/stamp/coverage‑manifest plumbing in a single‑snapshot readiness
   variant — bounded, not the multi‑day build "extend precert" implies.

## 4. Keep `compass`'s strategic frame (it is sound)

`ceiling-order` is the better **operating order** (gate/kill discipline, the 72‑h freeze). `compass` is the
better **strategy**; keep its spine:

- **Primary axis = validation/generalization (~60%)**, career as the *distribution wrapper* (~25%), autonomy
  (~10%), commercial (~5%). Autonomy/commercial are downstream of proof — no 90‑day budget.
- **Endgame = evidentiary credibility per dollar**: CAB‑signable, coverage‑honest L1–L4 **migration
  deliverables** a senior engineer would sign, provably, cheaper than any node‑priced incumbent. Cisco
  AgenticOps "Trusted Validation" + Forward Predict own *change‑validation on running gear*; **neither generates
  migration HLD→NRFU** — that is the wedge.
- **Non‑obvious move:** publish the negative result — open the TNR harness + coverage‑honesty audit as a public
  credential incumbents can't copy without exposing their own true‑negative rates.

## 5. The merged sequence

- **Act 0 — this week (~2 days, unblocks everything):** (1) run `defect_panel` → record the two‑number baseline
  TNR; (2) void the 2‑row scorecard; (3) phantom‑health audit vs the 50 uncollected nodes.
- **Act 1 — 72 h, perishable, the headline:** extend `precert` → frozen pre‑window readiness cert → sign+commit
  before the window; close/record the ~50‑node collection gap as explicit `UNKNOWN`. The only path to REAL row #1.
- **Act 2 — Weeks 2–5:** feed the built calibration corpus with public labelled rows (Batfish fault‑injection →
  Kathará → `--compare` pairs → shadow‑PIRs) to N≥20 *descriptive*; run the buyer test (`compass` assumption #1,
  the cheapest catastrophic falsifier) in parallel.
- **Act 3 — Weeks 4–7:** blind, source‑masked head‑to‑head (needs a small new harness).
- **Act 4 — Weeks 6–8:** freeze the 278‑item breadth register + recall/RRF (behind a flag); relabel every
  self‑scored competitive‑matrix ● as *measured* or *unverified*.
- **Act 5 — Week 8+:** clock arm‑or‑not, gated on TNR ≥ 0.75 ∧ calibration separation; shadow‑first, ROI‑killed.

## 5b. Act 0 — executed 2026‑07‑08 (this session)

- **Baseline TNR MEASURED (not assumed).** Deterministic arm: **localized TNR = 1.0** (12/12 by
  construction). Cross‑family qwen3:4b arm (local, air‑gapped): **TNR = 0.2**, `approves_clean = True` — caught
  only D‑12; approved D‑01/D‑03/D‑06/D‑11. Empirically confirms the plans' thesis: the unaided LLM judge is a
  weak detector (0.2 ≪ 0.75 gate, matches Jain et al. `<25%`). **The deterministic arm is the load‑bearing
  instrument; every LLM `APPROVE` is provisional.** Reproduced the README's prose characterization exactly.
- **Phantom‑health audit: 0 violations** on shipped text deliverables. Assessment docs consistently scope to
  253 and explicitly exclude the 50 uncollected ("excluded, not resilient" / "not assessed, not clean"). The
  `compass` §7 coverage‑honesty‑audit metric is satisfied for text deliverables. *Caveat: binary DOCX/XLSX
  deliverables were not grep‑auditable and remain unscanned.*
- **Deliberately NOT done autonomously (need a decision / the live path):** (a) **void the provisional
  `design.docx` APPROVE row** — the scorecard is append‑only, so voiding wants a *superseding* entry or a
  `judge_tnr`/status field, a ledger‑semantics choice for the operator, not a history rewrite; (b) **Order 1 —
  freeze the live prediction** — needs the live‑engagement snapshot and a sign‑off, and is the one perishable,
  irreversible‑adjacent action.

## 5c. Act 0 continued — binary phantom-health audit executed 2026-07-08 (this session)

- **Section 2 #4 CLOSED (binary residual).** The 9 AUTOFILLED binary deliverables (7 DOCX + workbook XLSX +
  executive PPTX, snapshot 20260613_063201) were text-extracted (stdlib zip/XML, no deps, offline) and
  audited for phantom-health: **0 violations.** No health / redundancy / clean claim covers the 50 uncollected
  nodes or the full 303 without an exclusion caveat. The binaries hold section 5b's text-deliverable line
  exactly - consistent "253 of 303" scoping; the 50 framed as "role and redundancy are UNKNOWN ... absence of
  evidence is not redundancy" (design/crd/deck); runbook labels them "assessment blind spots (Unknown state)";
  control-plane "247 OK, 56 Unknown"; "a device without a full capture is declared not assessable"; the risk
  register scopes 250 Severe + 3 Elevated over all 303 (conservative - treats uncollected as risk-bearing,
  never healthy).
- **Heuristic scope (honest limit).** A regex co-occurrence check (health-token x fleet-total token, minus an
  exclusion caveat) over extracted paragraphs. It would not catch a phantom-health claim that names a specific
  uncollected device WITHOUT a fleet-total token - but that is structurally unlikely: the engine has no
  collected data for the 50, so it cannot emit per-device health for them (UNKNOWN by construction). Auditor:
  `scratchpad/audit_phantom_health.py` (throwaway analysis tool, not committed).
- **Net:** section 2 #4 complete across BOTH text (5b) and binary (here). The Meridian reference fleet AUTOFILLED deliverable
  set is phantom-health-clean. (The `Reference_*` DC files are a different engagement/fleet - out of scope; they
  carry their own QA. Both sets are gitignored generated outputs, present on disk but never committed.)

## 5d. Frontier #2 (Order 1) — the readiness-FREEZE mechanism built + shadow-validated 2026-07-08

- **`precert` extended to a single-snapshot readiness freeze** (`compute_readiness_freeze`, schema
  `precert-readiness/1`; CLI `python -m cisco_toolkit.precert <snap> --mode shadow|real`). It reads the
  snapshot's precomputed per-move-group `migration_readiness` (no re-analysis), takes the WORST-of verdict,
  NAMES every uncollected device as a blind spot, and HASHES the prediction (sha256) so a committed cert
  cannot be retrofitted after the outcome is known. Reuses `precert._stamp` provenance — plan §3.2's "small
  precise extension" (+~115 lines, 7 tests, precert suite 25/25 green).
- **Shadow-validated on the Meridian reference snapshot:** verdict NOT READY (Group 1; 52 CAUTION, 0 READY of 53), coverage
  253/303 with all 50 uncollected named, `prediction_hash sha256:ea6f2048...`. Tagged `mode=shadow` — it
  validates the mechanism and is explicitly NOT a REAL calibration input (0 REAL unchanged; nothing fabricated;
  the shadow cert artifact is gitignored, not committed).
- **Still pending (unchanged, operator-owned):** REAL row #1 = `--mode real` + commit the cert BEFORE a genuine
  maintenance window + record the actual outcome post-cutover. The mechanism is now ready; only the live
  cutover event is missing — the perishable half that no code can manufacture.

## 6. The honest ceiling

Past the instrument, the next unit of insight is a **measurement, not a token** — and the ground truth makes
that sharper than Fable knew: the baseline TNR is *an afternoon away because the harness already exists*, and
REAL calibration row #1 is *perishable and due before the maintenance window*. Everything else waits on those
two numbers. The single first move: **run the baseline TNR and record it.**

---

*Verification basis: file:line checks across `defect_panel.py`, `ollama_judge.py`, `precert.py`,
`calibration.py`, `scorecard.py`, `pir_outcomes.jsonl`, `scorecard.jsonl`, `docs/quality/README.md`, and the
canonical fleet 303/253/50; live‑market claims (Cisco AgenticOps, Forward Predict, Jain et al. `2510.11822`)
taken from the two Fable plans and not independently re‑fetched here (air‑gapped session). Guardrails intact —
read‑only, no‑egress, no device writes.*
