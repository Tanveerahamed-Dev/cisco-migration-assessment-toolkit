# Session log

Append-only, one entry per working session. Newest first. This is `CHAT_SUMMARY.md`'s lightweight successor
(that file froze at 2026-06-12): a line here costs nothing and keeps the narrative queryable by graphify.
Format: `## [YYYY-MM-DD] — <headline>` + 3–6 bullets. Failures worth remembering get a `!lesson` tag.

## [2026-07-06] — Session-brief made worktree-aware: graphify rot-watch + memory slug (PRs #295/#296)

- Fixed the PR-#293 SessionStart brief for git-worktree sessions: `_graph_age()` read `graphify-out/graph.json`
  relative to cwd, but `graphify-out/` is untracked so worktrees have none → false "graphify graph missing"
  despite a fresh 5.9k-node graph in the main checkout. New `_main_root()` resolves the main checkout via
  `git rev-parse --git-common-dir` (trailing `.git` stripped, fail-open to cwd); the graphify line reads from
  there. PR #295, merged same day — confirmed live when this very session's own startup brief showed
  "graphify graph 0d old" from inside a worktree.
- Verified the hook manually in four states: worktree (missing → 0d old), main checkout (unchanged 0d old),
  non-git dir (exit 0 + valid JSON + honest "missing"), garbage `ASNE_GIT_COMMON` (cwd fallback). The fail-open
  and pure-ASCII/`json.dumps` output contracts held in all four.
- Scope discipline on reviewed rig code worked: the same bug class in `_auto_memory()` (project slug computed
  from cwd → "dir 0KB" misreport in worktrees) was found mid-fix but kept OUT of the reviewed change — handed
  off as a task chip, delivered by a separate session as PR #296 (merged 5 min after #295) reusing `_main_root()`.
- `!lesson` **cwd-relative reads in hooks/statuslines silently break in git-worktree sessions — but only for
  artifacts that don't exist per-worktree.** Decision rule per metric: tracked file → cwd is correct (agent-memory
  post-#294); untracked output or per-project global store (graphify-out/, the auto-memory slug) → resolve the
  main checkout via `git rev-parse --git-common-dir`, abspath it first (it returns relative `.git` in the main
  checkout, absolute from a worktree), strip the `.git` basename, and keep a cwd fallback so the hook stays
  fail-open. bridge-candidate
- `!lesson` **git-bash `/tmp` is MSYS-private on Windows** — a file a bash pipeline writes there is invisible to
  native Windows Python (`FileNotFoundError`), which cost one verification round-trip. When mixing git-bash and
  Windows Python in one pipeline, pass data via stdin pipes or a real Windows path, never `/tmp`. bridge-candidate

## [2026-07-05] — v3.30 "deliverable release" wave: MOP / Ops-Handbook / CRD excellence (§3.6 / DE-01)

- 3-agent isolated-worktree wave built the client-facing DOCX upgrades for the AJMN engagement: MOP BLUF +
  quantified rollback triggers + pre-impl checklist + comms/escalation (mop.py); Backup-&-Recovery +
  Known-Issues from the fleet's own axes (ops.py); Constraints + Out-of-Scope + Requirements Traceability
  Matrix (crd.py). All 3 agents completed cleanly; merges conflict-free (disjoint files); GOLDEN-NEUTRAL
  (DOCX isn't in the frozen snapshot contract — lower-risk than waves 1–3, no re-bless).
- `!lesson` **The coverage-honesty feature had coverage-honesty gaps of its own** (2 HIGH, adversarial review):
  the ops Known-Issues **Security axis had no not-assessable branch** — silently dropped when uncollected/clean,
  so the "not-assessable census" read as COMPLETE when security was never assessed (false-health by silence,
  in the very section built to prevent it). And its "Affected" column listed every device with a security
  block, not just the failing ones — telling a change board that clean boxes carry open hardening failures.
  Both fixed at the source.
- `!lesson` **Confidence-framing consistency across deliverables matters:** MOP/ops asserted "the target IS
  NX-OS VXLAN BGP-EVPN" as a settled plan-of-record off the ENGINE-default applicability flag, while the CRD
  correctly treated it as an open question without a requirements register. A change board reading three docs
  with three confidence levels is a real defect. Now all gate assertive EVPN language on register-confirmation.
- `!lesson` **Two vacuous tests** asserted `"not-assessable" in text` — always true from the §7.1 heading — and
  the MOP gate test asserted "NOT READY" against the whole doc (it renders in every wave table). Both
  re-anchored structurally (specific axis in `absent`; the BLUF gate ROW). The test-vacuity lens keeps earning
  its place: a weak assertion is how a subtly-wrong CLIENT-FACING document ships.
- graphify installed this session (real package = `graphifyy`, double-y, from the 78k-star Graphify-Labs repo;
  provenance verified before install); Obsidian LLM-wiki vault fully set up (Dataview/Templater/obsidian-git).

## [2026-07-05] — v3.29 "schema release" wave: coverage-honesty as a queryable schema (J3/J2/J1)

- 2-agent isolated-worktree wave built the moat-deepening §3.5 features: `ssot.compute_schema_census` (J3 —
  the snapshot self-describes published/collected-but-empty/not-collected per section; the SuzieQ `describe`
  analog that answers the AJMN access-only "filler" problem: it's an uncollected tier, not a code bug),
  `ssot.compute_fact_lineage` (J2 provenance for canonical facts), and `detector_schema.py` (J1 — 32
  descriptors making "not-observed ≠ healthy" a schema property via a mandatory `abstains_when`).
- `!lesson` **The golden shrink-guard caught a real integration defect, not me:** the Coverage Schema sheet put
  LIVE COUNTS in its frozen row-1 header, so every future section addition would re-trip the additive-only
  guard — cry-wolf that desensitises a load-bearing mechanism. Fixed to a static banner + totals data row. The
  guard firing on a routine additive merge is exactly the signal that something's wrong with the sheet design.
- `!lesson` **The coverage-honesty feature had a coverage-honesty bug (HIGH, adversarial review):**
  `abstention_reason`'s shallow `not val` mislabelled a WRAPPER of empty payloads (`addressing_conflicts
  {'dup_ip':[], 'dup_subnet':[]}` = zero conflicts) as green "published" instead of amber "collected, nothing
  found" — the exact Law-3 inversion the arc exists to prevent. Fixed at the single owner with `_is_deep_empty`
  (short-circuits on first real leaf). 3 zero-result sections correctly flip green→amber on the demo fleet.
- `!lesson` **A weak test let a wrong fact-citation ship:** the `cited_fields` test only checked the root
  token, so a descriptor citing the bare section `trunk_native` (a different detector's output) passed.
  Strengthened to require a field path + resolve simple leaves against the sample fleet. The test-vacuity lens
  earns its place — a weak assertion is how a subtly-wrong client-facing schema ships.
- Integration discipline held: two golden re-blesses (merge + fix), each audited to be exactly the intended
  additive/flip delta with nothing removed; full suite green with node on PATH (parity gate ran, not skipped).

## [2026-07-05] — v3.28 "rehearsal release" wave: L2 failover twin + cutover sim + FIB verdicts

- 2-agent parallel wave (isolated worktrees) built the market-gap flagship features: `failover.py` (STP
  root re-election + FHRP takeover — the L2 layer Batfish/Forward don't cover), `cutover_sim.py` (step-by-step
  dry-run naming the window a VLAN loses its path), and FIB path verdicts (`trace_fib_path` MTU/jumbo-blackhole,
  `trace_bidirectional` RPF asymmetry, `ecmp_consistency`). Both agents completed cleanly (no crashes this time);
  merged golden-neutral (failover is target-actuated, not snapshot-embedded) except the attestation module-count
  re-bless (47→49 for the 2 new modules).
- `!lesson` **Adversarial review (3 lenses, find→refute) confirmed 11 real findings — ALL one class: false-health
  when the incumbent is off-scan**, which is the COMMON case on the AJMN fleet (every uplink → uncollected core).
  The twin as first built would hand a client a confident "you have a backup" verdict for switches whose real STP
  root / FHRP active were never collected. Fixed: `_current_root` names a root only on collected `is_root=True`
  (never from the identical advertised root vector); `_current_active` only trusts an explicit Active/Master;
  the STP survivor election abstains on missing bridge_priority (no 1<<30 sentinel laundering) and on genuine
  priority ties (802.1D tiebreak needs the bridge's own MAC, not collected); ecmp treats a record-exists-MTU-blank
  leg as an MTU blind spot → INDETERMINATE (the `('','')` vs `(None,None)` gap); cutover reports the FHRP move it
  performs. Plus 2 vacuous tests replaced with realistic-schema regressions.
- `!lesson` **The executed JS↔Python FIB parity gate was a latent CI-breaker**: it does full-dict equality, and
  wave-2 added Python-only MTU keys to `trace_fib_path` → it would fail on any node-equipped CI runner. It only
  stayed green locally because node wasn't on PATH and it SILENTLY SKIPPED (a guard that doesn't run looks
  identical to a guard that passes). Fixed: project both sides to the shared reachability core + a non-vacuity
  guard; verified by running it WITH node on PATH.

## [2026-07-05] — v3.27 "trust release" wave: 6 features built + adversarially reviewed

- Parallel agent wave (isolated git worktrees) built the master-plan Weeks-2–4 features: the trust trio
  (`precert.py` PPDIOO gate certificate, `attestation.py` re-derived zero-egress proof, `nrfu_export.py`
  four-phase NRFU command pack), the K2 `PARSER_EXAMPLES` real-line registry (+2 genuine NX-OS parser fixes:
  2-line trunk header, "Kernel uptime"/"Device name" hostname), `compute_vlan_cutover_matrix` (per-VLAN
  cutover workbook), and 5 new read-only MCP tools. All merged to main; goldens re-blessed additively at each
  step; full suite green after each merge.
- **Agent turbulence handled:** API connection drops + session limits killed agents mid-run twice; recovered by
  committing survivors and rebuilding from worktree git state (hardened crash rules: commit-per-increment,
  foreground tests). One rebuild (parser-examples) took 3 attempts.
- **Adversarial review wave** (5 hostile finders × independent refutation) confirmed 2 real HIGH findings before
  session limits clipped it:
  - `!lesson` **NRFU command injection (fixed):** snapshot strings are attacker-controllable on `--no-collect`
    (JSON carries `\n`); an embedded newline in an interpolated value (stp_roots VLAN key, device field, CDP
    neighbor) emitted EXECUTABLE continuation lines ("configure terminal / shutdown") into the shipped .txt
    pack — a device write, defeating guardrail #1. Fixed with a two-layer defense (`_one_line` chokepoint +
    writer-side read-only refusal) + regression test. Golden byte-unchanged.
  - `redact_snapshot` 10.x pseudonym collision (HIGH) — user is fixing in a separate session (task_e9a652d1).
  - LOW: attestation shares its read-only grammar with the doctrine CI test (single point of failure) — deferred.
- `!lesson` **Real client Type-5 password hashes were committed in `test_audit5_parse_fidelity.py`** (pre-existing
  leak from AJMN device CS01; the K2 registry copied them). Cross-checked all 513 real collection secrets against
  every tracked file: those 2 hashes were the ONLY leak repo-wide. Scrubbed to synthetic length-preserving tokens
  in the parser-examples branch (fixes both files on merge).

## [2026-07-05] — New-laptop foundation: deep analysis, master plan, bootstrap

- 18-agent deep analysis of the whole repo at `ed8bc78` + 5-angle web landscape research →
  `docs/MASTER_PLAN_2026-07-05.md` (validates the 2026-07-04 backlog — all items were still open — and adds
  new workstreams: L2 failover twin, cutover dry-run simulator, per-VLAN cutover workbook, doctrine-safe LLM
  layer, PIR→ScoringConfig calibration loop).
- Security pass: `devices.json` cleartext fleet credential stripped (303 entries → `$CISCO_PASS` env chain;
  credentialed backup quarantined to `..\Enhancements_attic_2026-07-05\` — **rotate the credential, then
  delete that backup**). GitHub repo verified private (unauthenticated API 404s). `~$*` lock files ignored.
- Hygiene: merged `feat/design-sync-assesshub` (37 files — the 16-component design library, DE plan Phase 0);
  deleted 5 dead branches; quarantined the 2-release-stale root explorer copy + `raw/` egress artifact;
  fixed CLAUDE.md stale counts (385→~1,390 tests; 29→40 detectors; graph node count → pointer).
- Machine bootstrap: Python 3.12, Node LTS, GitHub CLI, Obsidian installed (winget); git identity configured;
  editable install + full pytest run kicked off as the engagement-readiness proof.
- Knowledge platform: personal LLM-wiki vault created at `C:\Vaults\brain` (Karpathy pattern; career/domain
  knowledge only — one-way sanitized bridge from engagements; this repo + graphify stay the code/engagement
  brain). Repo side gains `docs/decisions/` (ADRs) + this log.
- `!lesson` PS 5.1 `ConvertTo-Json` wraps arrays in `{value, Count}` — devices.json scrub was redone as a
  format-preserving line filter instead.
