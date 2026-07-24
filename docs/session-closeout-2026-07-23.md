# Session Closeout — 2026-07-23

Single durable record of the state of every prior/parallel session as of 2026-07-23. **Every open PR has a
disposition; no work was lost.** After this, resume from a clean baseline: merge the ready PRs, work the swarm
runbook, and revive-or-discard the preserved orphans at your leisure.

> `main` is branch-protected (required checks + review). Merges are **your** admin-bypass action — nothing
> below was merged. The goal here was a clean, review-ready, correctly-sequenced state + cleared cruft.

## 1. Open PRs (17) — disposition

### A. Ready to merge — 11, all MERGEABLE, mine, verified test-first
| PR | Branch | What |
|----|--------|------|
| #447 | docs/adr-0005-cognee-evaluation | ADR-0005: evaluated Cognee, don't adopt; 2 cited docstrings (CI green) |
| #449 | docs/retro-2026-07-23-best-decision | Session retro |
| #450 | fix/ipv6-global-addr-multiline | **High** — IPv6 multi-line global-addr dropped → DAD false-health |
| #451 | fix/design-advisor-robustness | SD-WAN state=red false-health + `_fallback_blueprint` 500 |
| #452 | fix/ssot-summary-crash-hardening | malformed summary crashes reconcile/summary + all 7 generators |
| #453 | fix/design-docx-crash-hardening | As-Built Design .docx crash-harden |
| #454 | fix/webapp-read-route-500-guard | stored-500 DoS on read routes (section-level) |
| #455 | fix/deck-crash-hardening | deck .pptx crash-harden |
| #456 | fix/cutover-wave-helper-dos | stored-500 in cutover wave helpers (per-item) |
| #457 | fix/runbook-crash-hardening | runbook .docx crash-harden (26 sections) |
| #458 | docs/scorecard-0718-qa-row | commits the orphaned 2026-07-18 QA APPROVE audit row |

**Merge freely, any order — two adjacencies:** #451↔#453 and #454↔#456 touch related code in *different*
functions; if siblings land close together, run the full `pytest -q` gate on merged `main` once.

**CI note:** the self-hosted 2-runner fleet was saturated by this batch; some checks show cancelled-as-"fail"
(contention) and **py3.13/py3.14** legs fail even on the docs-only #449 → **environmental, not defects**.
Once the queue drains, `gh run rerun --failed` on any red PR before merging.

### B. Gate/manifest swarm — 5, CONFLICTING — merge with the runbook in §2
#441, #445, #444, #448 (mine), #439. These are the bulk of the "unfinished sessions" cluster. They conflict
in **safety-critical** code (gate_state.py three-way; a wrong resolution silently re-disables a PPDIOO gate,
invisible in output), so they were **not** auto-reconciled — see the step-by-step runbook below.

### C. #442 — retro, CONFLICTING on `docs/log.md` only
Docs-only ordering conflict (competing log entries). Resolve at merge, or rebase onto `main` first.

## 2. Swarm merge runbook (merge-tree-verified order)

Merge **in this order**, running `python -m pytest -q` on merged `main` after each (exit 0, no FAILED/ERROR):

1. **#441** (crash-safe manifest seal) — smallest, foundational; only vs-main conflict is `docs/log.md`.
2. **#445** (durable gate verdicts) — lands `enforce()` verdict instrumentation before #439's rewrite.
3. **#444** (verify verb) — resolve the `manifest.py`/`build_run_manifest` docstring collision with #441 in
   favor of #444's honest-scope wording; fold in #441's append-only-scope paragraph.
4. **#448** (redaction-gate `--gate-root`) — rebase over the above.
5. **#439** (ADR-0006 ledger identifier) **last** — the schema-v2 rewrite must re-express #445's `_record()`
   calls and #448's root guard inside its shapes.

**The one thing that will bite if missed:** #439 embeds a **stale copy** of #448's `--gate-root` work
(`COLLECT_PARSE_V3_23_0.py:1574` + the gate call sites), and #448's commit **6822242** *corrects false claims*
in that same 099ac65-era text. **Treat 6822242 as authoritative** over #439's snapshot — otherwise the
correction (and a green-suite feature-killer fix) silently regresses. All five also edit `docs/ssot.md` — leave
one reconciled row set.

## 3. Preserved orphaned work — `refs/preserved/*` (nothing lost)

Recover any with: `git switch -c revive/<name> refs/preserved/<name>`

| ref | verdict |
|-----|---------|
| **kev-phase-b-upgrade-targets** | **REVIVED → #460.** The tested comparator (`cisco_toolkit/upgrade_targets.py` + 57-test suite) is landed on a branch and green on current main (deps `intel_feed`/`research_lane` already merged). Still **unwired** — nothing calls `build_upgrade_targets`; surfacing it in the KEV MOP/NRFU (static docs) or the snapshot is the remaining follow-up (product call). Preserved ref kept until #460 merges. |
| **deliverable-records-81bffa4** | Overlaps #438's landed deliverable-completeness work — **diff-review** to salvage anything novel before reviving. |
| webapp-csrf-hardening | Superseded by the merged Sec-Fetch/Host guards (#382/#388). Discard unless a gap is found. |
| ssot-qatar-repoint / masterplan-hygiene-table / scorecard-record-msg-arm | Stale/superseded 07-06–07-08 tweaks. Preserved for reference; likely discard. |

## 4. Cleaned this session
- **All merged local branch mirrors pruned: 132 → 32 local branches** (the 31 no-upstream stale ones — 23
  `claude/*` + 8 `worktree-agent-*` wrappers — plus the merged upstream-tracking mirrors; local-only, git
  auto-protected unmerged + checked-out). The 32 remaining = the 11 open-PR branches + the swarm PRs + the 6
  preserved orphans + a few unmerged-with-upstream branches (safe on origin).
- **2 done worktrees** removed (`atlas-p1`, `atlas-p3`).
- **Scorecard QA row** committed → #458; **main checkout is clean.**
- 6 orphan branches preserved as `refs/preserved/*` before any deletion.

## 5. Residual cruft — documented, deliberately not force-removed
- **4 lock-held worktree dirs** (`admiring-chatterjee`, `dazzling-mirzakhani`, `magical-jang`, `admiring-mendel`)
  — on merged branches (no unmerged work); git registrations were auto-pruned but a live process holds the
  files (Windows lock). Remove once that process exits: `rm -rf .claude/worktrees/<name>`.
- **~6 more stale unregistered worktree dirs** (`agent-*`, `clever-*`, `unruffled-*`, `zealous-*`, `zen-*`) — same.
- **Merged local branch mirrors: PRUNED** (132 → 32 local branches; see §4). What remains are only open-PR +
  orphan + a few unmerged-with-upstream branches (the last are safe on `origin`). Stale **remote** branches on
  `origin` from merged/closed PRs remain the real clutter — clean deliberately (shared-repo op), not here.
- The `amazing-bardeen` worktree still carries the same stray scorecard row uncommitted (that session's copy;
  now redundant with #458) — not touched (not my worktree).

## 6. What remains yours
- Merge the **11 ready PRs** (§1A) + work the **swarm runbook** (§2).
- **Rerun** contention-flaked CI after the fleet drains; then merge.
- **Revive-or-discard** KEV Phase-B (recommended revive) + deliverable-records (§3).
- Rebase/merge **#442**; clean the residual cruft (§5) when the locks clear.
