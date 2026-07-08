# Session log

Append-only, one entry per working session. Newest first. This is `CHAT_SUMMARY.md`'s lightweight successor
(that file froze at 2026-06-12): a line here costs nothing and keeps the narrative queryable by graphify.
Format: `## [YYYY-MM-DD] — <headline>` + 3–6 bullets. Failures worth remembering get a `!lesson` tag.

## [2026-07-07] — [HISTORY-REDACTED] DC HLD → v7.5 full-family rebuild (research → audit → mining → figures → content → resync → independent QA)

- Rebuilt the [HISTORY-REDACTED] Qatar-DC deliverable set to a best-possible v7.5 across a ~50-agent marathon: a research wave
  (cited HLD/diagram best-practices brief), an audit wave (14 figures + document + family-skew), and a mining wave
  (every v3–v7 HLD/LLD for content dropped along the way → 32-recovery plan) fed a ground-up rebuild. Shipped a NEW
  reusable figure generator (`[HISTORY-REDACTED]_DC_Design/figgen/`: `svgkit.py` vector engine + `figdata.py` SSOT →
  editable SVG + 600-DPI PNG), 14 rebuilt figures, an elevated 78-page HLD (18 content recoveries + Appendices E–I),
  and the whole companion family (LLD/ConfigPack/MOP/NRFU/NIP) resync'd to v7.5 via their generators. docx→PDF via Word COM.
- !lesson **A single wrong "canonical fact" in a generation spec propagates silently across an entire
  multi-document family — and only an INDEPENDENT adversarial QA catches it, not mechanical greps.** I
  over-simplified the routerless internet edge to "FTD takes a static default toward the CPE VIP .225" in an HLD
  appendix and fed that into the family-resync spec; taken literally it routes ALL internet egress over a 10 Mbps
  leased circuit, violating the design's own acceptance criterion. The correct model (default via broadband; the
  VIP is a PBR next-hop for the published-return+telemetry classes only) was in the HLD body and the figure all
  along. Grep-verification reported the WRONG pattern as "consistent"; a fresh proposer≠verifier QA found the
  contradiction. After a large multi-agent build, run an independent adversarial QA — greps confirm known
  patterns but miss new contradictions and prose. bridge-candidate
- !lesson **A .docx built by a non-python-docx tool (here docx-js) exposes no style-name lookup:
  `add_heading(...)` / `add_paragraph(style="Heading 1")` raises `KeyError: no style with name 'Heading 1'` even
  though the body paragraphs use that style. Fix: capture the style OBJECT from an existing paragraph (`p.style`)
  and assign it to the new paragraph — never look it up by name.** bridge-candidate
- !lesson **A static (non-field) Table of Contents silently rots the instant pagination shifts.** The v7.x HLD's
  TOC is baked text, not a TOC field, so resizing figures + inserting content left its page numbers 1–5 pages
  wrong (appendices off by 5). Re-measure each Heading-1's real page (Word COM `Range.Information(3)`) and patch
  the trailing `\t<page>` run; a live TOC field (as the companion generators use) auto-updates on open instead. bridge-candidate
- !lesson **A multi-step build pipeline that spans two file locations will silently process a STALE copy — pin
  ONE working path.** I edited the project docx but ran the TOC-patch + PDF-export stage on a scratchpad copy; the
  re-exported PDF came out BYTE-IDENTICAL to the previous one (the tell) because it rendered the stale file.
  Route every stage through the same path, or assert the output actually changed. bridge-candidate
- !lesson **"Editable, no-overlap" figures come from a data model, not from patching rasters.** One
  register-sourced model → clean SVG (real `<text>` + shapes, editable in draw.io/Inkscape) → 600-DPI PNG via
  PyMuPDF (`fitz`) for the doc (python-docx cannot embed SVG — `add_picture` raises). Auto-sized boxes + opaque
  label chips make overlap impossible by construction, retiring the stale-label / tofu-glyph / overprint class
  that fragile PIL raster-surgery kept re-introducing. bridge-candidate

## [2026-07-07] — Autonomous-brain plan Phases 1–6 wired + demonstrated end-to-end (KEV remediation package)

- Continued the v4 plan from Phase-0: shipped the feedback nerve (`scorecard trend` + PIR `calibration.py`,
  D11-gated descriptive-only until N≥5), the clock safety rails + dry-run nightly wrapper (3-fail breaker +
  daily-spend ceiling, propose-only, nothing scheduled/spent), the domain packs + `/council` (D6/D8 —
  retrieval-selected lenses keyed to `architecture_coverage`, independent refute-first majority), the
  self-check immune system + self-healing drift-triage, and (in compacted work) the Phase-5 eyes/recall +
  Phase-6 Batfish GO. Then demonstrated the whole loop on the real fleet: live CISA-KEV intel → verified
  exposure finding → propose-only remediation package (MOP + independent NRFU + blast-radius annex +
  adversarial QA), all in `docs/security/`. Every new module re-blessed the no-egress attestation (0 LLM +
  0 network imports); full suite green throughout.
- !lesson **An IOS-oriented software-advisory/surface detector over-flags on NX-OS — reconcile advisory
  exposure to the CVE's actual platform before you count it.** `software_risk` raised `smart-install`/
  `http-server` "verify" flags on 151/63 devices, but 55 of each were NX-OS where `vstack` / IOS `ip http
  server` don't exist; CVE-2018-0171 and CVE-2023-20198 are IOS/IOS-XE. True CVE-applicable exposure = 96
  Smart-Install + 8 Web-UI + 3 confirmed-`exposed`. An advisory-hit count is not an exposure count until it
  is platform-filtered to the CVE's affected OS. bridge-candidate
- !lesson **Proposer≠verifier earns its keep on security findings, and the verifier must RECOMPUTE, not
  review.** Two independent agents (MOP author + NRFU) each caught the NX-OS over-count before it reached a
  change window; the QA verifier re-derived every count/split/blast-radius value against the SSOT + snapshot
  (zero mismatches) and re-ran the reproduce command rather than eyeballing — which is what surfaced the one
  real reconciliation nit. A verifier that recomputes catches what a verifier that reads misses. bridge-candidate
- !lesson **A blast-radius / SPOF model is only as strong as the redundancy it collected — report worst-case
  and certify nothing when FHRP/STP aren't parsed.** The model returned "Hard-partition for all 21" reload
  targets, but FHRP was parsed for 0/52 multi-gateway VLANs and STP-backup for 2/303 devices, so that verdict
  is coverage-bounded, not proven SPOF; the analyst refused to certify redundancy and deferred to a per-device
  pre-check. Corollaries: overlapping `stranded` endpoint counts must never be summed (one VLAN's 667
  endpoints get attributed to every cut point), and a VLAN-1 "hard partition" on 226 devices holding 1
  endpoint is noise. bridge-candidate
- !lesson **A fail-open automation hook can silently never fire in a different runtime — verify the loop
  actually produces output, don't trust the wiring.** The `SubagentStop` scorecard appender is correctly
  registered (`.claude/settings.json:66` → `scorecard-append.sh`) and `parse_qa_verdict` parses a real
  reviewer verdict (tested), yet a genuine independent `/qa` verdict appended no row (`selfcheck` still shows
  "0 entries") — the hook is fail-open, so nothing surfaced. In the Claude Agent SDK env, SubagentStop
  doesn't fire for Agent-tool subagents. Flagged as task_dcf0043c (needs a fallback recording path that
  records only a real subagent verdict, never main-agent prose). bridge-candidate

## [2026-07-06] — [HISTORY-REDACTED] HLD v7.1: integrity reissue + FCSLA-delivery + firewall-terminated-edge deltas (side engagement)

- Side-engagement session only — produced [HISTORY-REDACTED] DC HLD v7.1 from v7.0 in three stacked deltas: an integrity/completeness
  reissue (~27 fixes: ACP rule off-by-one, FPR3105 copper-port media, C9400 SVL single-active-supervisor behaviour,
  figure renumber, consolidated 39-REQ + 10-OQ Appendix A, reinstated §12.6/§14.4, S-30, REC-6 optics gap), then the
  Ooredoo FCSLA delivery as a design variation, then the resolved firewall-terminated eBGP edge (D-14 topology /
  D-15 C-2 evolution). No tracked repo code touched — `[HISTORY-REDACTED]_DC_Design/` is gitignored with its own SSOT, so `git log`
  is unchanged. Built via an idempotent, assertion-guarded XML-transform script re-runnable from a pristine `.orig` unpack.
- !lesson **The Windows git-bash docx toolchain is missing the obvious binaries — reach for pip wheels and Python
  stdlib instead.** `pandoc`, `pdftoppm`/poppler, and `zip` are all absent; the console is cp1252. Fixes that worked:
  PyMuPDF (`pip install pymupdf`) to render PDF→PNG in place of pdftoppm; Python `zipfile` (write `[Content_Types].xml`
  first) in place of `zip`; `sys.stdout.reconfigure(encoding='utf-8')` or `PYTHONIOENCODING=utf-8` before printing any
  `→`/`✓`/`§`/`⇄`; and `pip install defusedxml` for the docx skill's `merge_runs.py`. bridge-candidate
- !lesson **Assert an exact occurrence count before every string-replace edit, and never hand-count XML tag offsets.**
  Wrapping each edit in `assert doc.count(old)==n` caught stale anchors immediately (e.g. a table-row anchor that didn't
  contain the expected phrase) instead of silently corrupting the doc. But a hand-written splice offset
  `find("</w:tr>") + 7 + 1` left a stray `<` before the next `<w:tr>` → "StartTag: invalid element name" at XSD
  validation. Use `len("</w:tr>")`, never a magic number. bridge-candidate
- !lesson **Raster text in documents is a QA blind spot that text-extraction verification cannot see.** Embedded figure
  PNGs literally drew stale labels — a "single CPE" box, out-of-order "Figure N" chips, and deep-dive titles with event
  IDs ("S-05/S-11/S-17") that disagreed with the renumbered failure matrix ("S-6/S-9/…"). Fix: render pages, eyeball the
  figures, patch the PNGs with PIL — detect the box/chip bbox by scanning **outside-in** for the border (an inside-out
  scan hits the dark title glyphs and mis-measures), erase with a sampled fill colour, redraw with matplotlib's bundled
  DejaVu TTF — and back up the media first (the build pipeline kept no per-file `.orig` for images). bridge-candidate
- !lesson **A Word static TOC (from a prior Ctrl+A/F9) has hardcoded page numbers that never auto-update, and the
  title↔number tab separator is fragile.** Render → measure real pages (PyMuPDF `page.search_for`) → patch the number
  run. The first patch replaced the whole run text and ate the leading `\t`, so titles ran into their page numbers with
  no gap — a regression the independent verifier caught. Substitute only the numeric text and preserve the leading
  tab/whitespace prefix. bridge-candidate
- !lesson **Proposer≠verifier pays off on prose deliverables, and a contradictory design brief is a stop-and-confirm
  signal, not a guess.** An independent extraction-diff subagent caught a mis-registered management IP and the TOC-tab
  regression that the builder's own gates missed. And when the brief self-contradicted ("CPEs connect to firewalls"
  while also "keep the routers"), resolving the active-edge role with an explicit question before the large §6 rewrite
  avoided rebuilding the wrong topology; the reserved decision number (D-14) was then reused rather than left dangling
  beside a new D-15. Run an independent verifier after any large document delta; confirm contradictory briefs first. bridge-candidate

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

- 3-agent isolated-worktree wave built the client-facing DOCX upgrades for the [HISTORY-REDACTED] engagement: MOP BLUF +
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
  analog that answers the [HISTORY-REDACTED] access-only "filler" problem: it's an uncollected tier, not a code bug),
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
  when the incumbent is off-scan**, which is the COMMON case on the [HISTORY-REDACTED] fleet (every uplink → uncollected core).
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
  leak from [HISTORY-REDACTED] device CS01; the K2 registry copied them). Cross-checked all 513 real collection secrets against
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
