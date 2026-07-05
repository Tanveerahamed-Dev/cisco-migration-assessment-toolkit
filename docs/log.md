# Session log

Append-only, one entry per working session. Newest first. This is `CHAT_SUMMARY.md`'s lightweight successor
(that file froze at 2026-06-12): a line here costs nothing and keeps the narrative queryable by graphify.
Format: `## [YYYY-MM-DD] — <headline>` + 3–6 bullets. Failures worth remembering get a `!lesson` tag.

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
