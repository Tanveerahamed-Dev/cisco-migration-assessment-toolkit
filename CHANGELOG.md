# Changelog

Release-level highlights. The complete, engineering-grade change history (one dated row
per change, with verification evidence) lives in
[`COLLECT_PARSE_V3_23_0.md → Change Log`](COLLECT_PARSE_V3_23_0.md#change-log).

## [Unreleased]

### Added
- **`docs/prototypes/fabric/` — a coverage-honest topology engine prototype.** One
  self-contained WebGL2 file that re-solves the fabric *without* a selected device to show what
  its failure strands, instead of only what it can reach (one BFS, ~0.3 ms at 5,000 devices).
  Its reason for existing was the gap it made visible: `webapp/backend/graph.py` publishes
  `bridge_assessed`, `link_centrality_assessed` and `offscan_peers` (graph.py:105,127,128) and
  the shipped frontend previously read none of them — so a picture could render "not measured"
  identically to "measured redundant", which is exactly the failure guardrail 3 forbids. The
  shipped integration below now closes that gap. Absence is drawn *louder* than health and counts
  are scoped to the resolved topology rather than advertised as fleet-wide bounds. The prototype
  runs on a wholly fictional synthetic fleet and is deliberately **not** bound to
  `/api/snapshots/{id}/graph`, and is parked under `docs/` so it cannot be mistaken for a
  product surface. Its own gate is `node docs/prototypes/fabric/verify.mjs` (18 checks). The
  prototype itself remains docs-only; the separately listed shipped integration changes SPA bytes.
- **`VerificationBadge` and `VerificationWarning` now reach the design system** (19 → 21
  components). Both ship in the app and are used by three pages, but the hand-maintained
  `webapp/frontend/ds.entry.ts` barrel never re-exported them, so the design agent could not
  build with them and would hand-roll lookalikes that bypass `normalizedVerification` — the
  guard that forces absent, legacy or self-contradicting coverage metadata *down* to unverified.
  Nothing detected the omission, which `.design-sync/NOTES.md` had already recorded as a
  standing risk of a manually maintained barrel.

### Changed
- **The release suite gate no longer leaves debris in the tagged checkout.** Running the suite
  mutates the working tree (pytest's cache, the editable install's `egg-info`, and an engine log
  a test writes into the CWD), which the release workflows' immutability proofs correctly
  refused. Fixed by prevention (`-p no:cacheprovider`) plus an explicit restore-and-verify step,
  and the allow-list entries added while diagnosing were **removed**: an immutability proof
  loosened to tolerate its own test debris stops being able to detect the tampering it exists
  for. CI-only; no shipped bytes are affected, so v3.32.1's artifacts are unchanged.

### Fixed
- **The shipped topology no longer renders unmeasured redundancy as healthy.** The graph API's
  `bridge_assessed`, `link_centrality_assessed`, and `offscan_peers` evidence now reaches both the
  2D and 3D fabric views: unassessed links are loud and explicit, peers outside the collected
  snapshot are disclosed, and clicking a non-reference device re-solves the resolved topology
  without it to name which baseline-reached devices lose their path to a deterministic reference
  anchor. Selecting the anchor itself or a node outside its baseline fails closed instead of
  publishing a tautological catastrophe or a false zero. Counts are deliberately scoped to the
  resolved graph; missing alternate links can make real impact smaller, while uncollected downstream
  devices can make it larger.
- **Fabric's prototype copy no longer calls resolved-topology chokepoint counts fleet-wide upper
  bounds.** A missing leaf/device can add an articulation point or bridge, so the old claim was
  mathematically unsafe. The 18-check verifier now ratchets the corrected scope, both uncertainty
  directions, and rendered fail-closed reference/outside-baseline states; it also tries every
  installed Playwright candidate until one can actually launch its matching Chromium rather than
  stopping at a stale package.
- **Design-system component registration can no longer drift silently across hand-maintained
  surfaces.** A static parity gate now reconciles the public barrel, `componentSrcMap`,
  `dtsPropsFor`, authored docs, and previews; rejects empty or generic props contracts; and discovers
  exported source components omitted from that set. `Topology3D` is recorded as the sole deliberate
  internal exception, while `DemoDataProvider` remains a required public contract.
- **The design-system sync had been failing outright, not drifting.**
  `.design-sync/providers/demo.tsx` still imported `MemoryRouter` from `react-router-dom`, which
  the react-router 7 migration removed, so the converter died in its bundle step
  (`[UNRESOLVED_IMPORT]`) and every stage after it was skipped — no re-sync could complete at
  all. That file is the only durable design-sync input importing an app dependency by bare name,
  now recorded in `.design-sync/NOTES.md` as the thing to check whenever the frontend's
  dependencies move.
- **Every component was publishing an empty API contract.** The design agent reads
  `<Name>.d.ts` as a component's props interface, and all 21 emitted
  `{ [key: string]: unknown }` — six syncs' worth of no prop information for the entire design
  system, including long-standing components. The cause is a single build-log line,
  `[DTS] parsed 0 .d.ts files`: the extractor reads props out of an emitted `.d.ts` tree and this
  DS is a private app with no library build, so there was nothing to parse. All 21 bodies are now
  hand-written into `cfg.dtsPropsFor` from the real source signatures and verified by compiling
  every emitted `.d.ts` under `strict`.
- **The verification components' own documentation made their states unreachable.** Their only
  example was `value={snapshot.verification}` — and the design agent has no snapshot. The
  13-field contract-v3 object actually required appeared nowhere it is told to look, so any
  shorthand mock normalised *down* to unverified and `VerificationWarning`'s documented "renders
  `null` when verified" read as broken. Both docs now publish a copy-pasteable literal. Proven by
  rendering the literal transcribed from the `.md` (not from the preview source, which uses
  known-good props by construction).

  All three fixes above touch design-system sync inputs only; no shipped bytes are affected.

## [v3.32.1] — 2026-08-03 — release-integrity fix

**Supersedes v3.32.0, which was released from a commit that failed its own test suite.** The
defect was confined to release metadata — `docs/ssot.md` still cached the previous release
version and the changelog had no open `[Unreleased]` section — so the v3.32.0 artifacts are
functionally sound, but re-verifying that tag reports RED and its provenance claim cannot be
reproduced. v3.32.1 is the same content from a commit whose suite is green.

### Fixed
- The release-metadata caches the v3.32.0 cut missed: a fresh `[Unreleased]` section, and
  `docs/ssot.md`'s release-version cache reconciled to its owner (`pyproject.toml`), which
  `tests/test_registry_freshness.py` verifies.

### Changed
- **A release now proves the tagged code passes its own suite.** Both release workflows ran an
  exhaustive *provenance* gate — annotated tag, version match, main ancestry, privacy boundary,
  immutability proofs between every step, archive metadata, clean-environment installability,
  registry health — and none of it asked whether the code works. `RELEASING.md` carried that as
  a documented precondition with no mechanical enforcement, and it failed the first time it was
  stressed. The suite now runs against the tagged source before anything is built or attached,
  in both the hosted and self-hosted paths.

## [v3.32.0] — 2026-08-03 — the review release (whole-repo coverage-honesty hardening + source-bound archives + proven support floor)

### Fixed
- **Whole-repo code review — 98 findings closed** (`docs/review-findings-2026-07-28.md` is the
  register, with per-row status and a limits section). One class dominated every subsystem:
  **absence of evidence rendered as health**. The workbook stamped `ok` on ports whose
  `show interfaces` counters were never collected; readiness passed STP and port-channel checks on
  evidence that was never gathered; an access switch homed to an *uncollected* core reported "no
  single-homed switch"; an unmeasured host was published with a fabricated `data_quality: 1.0`;
  `ops.py` counted a null FHRP as first-hop-*redundant*. Two findings invert the same fabrication —
  the design advisor reported every endpoint port as UNGUARDED when the run-config channel simply
  had not landed.
- **The instruments that certify were certifying nothing.** `ssot.summary` reported
  `verified: True` having reconciled zero facts (it now returns `n_checked`, and `verified` requires
  it); `selfcheck.check_guards_nonvacuous` grepped for the substring `"assert"`, so all 15 guard
  suites could be `pytest.mark.skip`-ped and still read GREEN (now AST-parsed); the no-egress
  attestation published "0 network-library imports" from a walk that never entered subpackages —
  which is why its documented exception was dead code.
- **The meta-gate was never executed.** `verify-green.sh`, the Stop hook every other test's meaning
  rests on, was pinned by two substring greps and never run. Executing it exposed a change detector
  that missed any path git has to quote. Both fixed and mutation-tested.
- **Share-safety.** `--redact-collection` reported the *flag* rather than whether the scrub ran, so
  exit 0 told a field engineer secrets were gone from the stick; an earlier run's snapshot and phase
  ledger could certify a later one; three failure exits left partial `*_redacted*` files with no
  DO-NOT-SEND marker; `make_stick.ps1` pinned its `data\` exclusion only on the destination, so a
  source `data\` mirrored the dev box's store over the field evidence and purged the backups.
- **Security.** Stored XSS in the explorer label (reachable from an unsanitized upload label that
  falls back to the filename); the SPA catch-all called `Path.resolve()` on a raw URL path, so a UNC
  path triggered a live outbound SMB lookup (measured 42.3s, leaking NTLMv2); `/ingest-folder` read
  any server directory with no containment; `OLLAMA_HOST` was unvalidated, turning the ADR-0001
  on-host carve-out into real egress; `load_devices` formatted the device password into a ValueError
  that reaches the AssessHub error body; 17 controller-REST strings were being typed at live device
  exec prompts.
- **Wrong answers an engineer acts on.** Two-token IOS route codes (`O IA`, `O E2`, `D EX`, `i L1`)
  matched nothing, so those routes vanished from the RIB *and* their next-hops grafted onto the
  previous prefix as phantom ECMP; an unparseable entry in a CVE's fixed-list was dropped, shipping a
  remediation MOP whose target release is still vulnerable; ECMP was a pure existential, so a
  destination with one blackholing leg certified reached; the MOP's rollback cited a configuration
  capture the document never told anyone to take.
- **Atlas `--redact-folder` no longer reports a short deliverable set as success** (#438): every
  engine deliverable writer is fail-soft (logs a warning, continues, exits 0 — deliberate, and
  unchanged), so a run that rendered all but two documents printed the survivors as though they
  were the whole family and the engineer could send a partial set. The command now diffs
  produced-vs-expected — derived from `docmeta.CLI_ARTIFACT_SUFFIX`, reconciled against the engine
  source so a new writer cannot slip past it — and reports each gap as `ABSENT`, `UNUSABLE`
  (0-byte or truncated: existence is not delivery) or `STALE`, on the console and in an
  `INCOMPLETE-SET.txt` note. New exit code **3** = produced but short; `0` keeps meaning complete
  and verified, `1` stays redaction-failed.
- **`--out` folders are one-job-per-folder** (#438): a destination already holding a deliverable
  set is refused before the engine starts, because a failed writer would otherwise leave another
  engagement's document under this run's filename — and redaction keeps hostnames by design.
  `--reuse-out` is the explicit escape for re-running the same job.
- **Evidence custody no longer falsely refuses on an alias-spelled collection root.** The sealer
  resolved each evidence FILE but compared containment against the RAW root string, so any
  environment where the two spell the same directory differently — DOS 8.3 short paths
  (`RUNNER~1`), junctions, symlinks — refused every file of a healthy run and failed the whole
  collection. Both sides now resolve before comparison; pinned by a junction-spelled-root test
  plus the still-refuses-outside-files direction.
- **Uploads work on Python 3.10.** `tempfile.SpooledTemporaryFile` lacks `seekable()` before 3.11
  (bpo-35112), so every archive upload died with `AttributeError` before validation ran. The
  ingest route now normalizes the spool at its boundary (`ingest.iobase_upload_file`) so any
  consumer — including a replaced zip runner — receives the full IO probe interface. The claimed
  `requires-python >= 3.10` floor is now actually exercised: CI runs the full suite on
  CPython 3.10–3.14 (ubuntu) and 3.12 (windows), all green.

### Added
- **Master reference** (`master-reference/`): a static, self-explanatory reference site for the
  repository — the evidence pipeline, 16 major engineering decisions with rationale/tradeoff/
  enforcement/evidence, the data-authority model, an interactive trust-boundary explorer, PPDIOO
  gates, repository atlas, verification matrix, operator commands, and glossary. Server-rendered
  semantic HTML, keyboard access, reduced-motion support; no database, analytics, cookies, or
  runtime content fetch. Deployed privately; its own CI (typecheck + build + rendered-contract
  tests + lint + audit) gates changes.

### Changed
- **The release chain is source-bound.** `webapp/frontend/dist/` is tracked (byte-pinned,
  `-text`), and `distribution_verify --require-source-binding` proves 115 of 129 shipped archive
  members bind to the release commit (the other 14 are build-generated and declared as such).
  A release archive can no longer silently diverge from its claimed source.
- **Build backend pinned forward**: `wheel 0.46.2 → 0.47.0` (audited by the dependency-audit
  gate; the exact-pin guard test moved with it). Dependency ranges widened: `ntc-templates <10`,
  `mcp <3`. GitHub Actions moved to the v7 line (checkout / setup-python / setup-node /
  upload-artifact), each proven by an executed green matrix before merge.
- **react-router 6 → 7** (`react-router@7.18.2`, closing the review's last carried question).
  The v6 future flags (`v7_startTransition`, `v7_relativeSplatPath`) had already been enabled
  in production, so every run since had exercised v7 semantics — including the startTransition
  interaction with the view-transition machinery; the swap itself is the package rename
  (`react-router-dom` → `react-router` across 16 files) with zero API changes: the app is
  all-declarative (no data routers) and its only splat is a single-segment root 404, outside
  the one behavioral change v7 ships. Verified: typecheck, 200/200 unit tests, production
  build, real-browser E2E including router navigation. (v8 exists but requires React 19 —
  deliberately not taken; React 19 remains a planned migration.)

## [v3.31.0] — 2026-07-18 — the hardening release (security audit + fail-soft totality + verified deliverable quality)

109 merged PRs since v3.30.0, in five arcs: a full security audit of the untrusted-input surfaces, a
recursive-poison fail-soft campaign over every ingestion path, frontend/backend/engine test-coverage
completion, the Phase-3 quality-instrument closures, and a QA loop that went finding → fix → re-verified
in rendered pixels (scorecard rows 11 → 13, the first all-APPROVE full-set row).

### Security (audit series — one PR per untrusted surface, every fix proven non-vacuous)
- **SPA path traversal (Critical) + ISE `nextPage` credential-leak (High)** (#368): the webapp static
  server no longer serves outside the dist root; ISE REST pagination fails closed on malformed/off-host
  `nextPage.href` (follow-up red-team hardening included).
- **xlsx formula injection (High)** (#369): workbook cells beginning `=`/`+`/`-`/`@` are neutralized —
  0 unescaped formula-leading cells across all 67 sheets, verified per release QA.
- **Latent SQL-injection sink (Low)** (#370): the JSON path in `get_snapshot_section` is bound, never
  interpolated.
- **Stored XSS via device hostname (High)** (#374): the 3D-topology tooltip label is escaped.
- **Combined webapp API guard** (#388, reconciling #382/#383/#384): blind-CSRF write block on
  state-changing routes (fail-closed on unknown `Sec-Fetch-Site`), a concurrency cap + 503/Retry-After
  on the compute-heavy GET generators, and a DNS-rebinding exact-match `Host` allowlist for no-token
  loopback mode.

### Coverage honesty & correctness
- **An authorization-denial banner is not clean logs** (#371): denied `show logging` output now reads
  not-collected, never a clean-logs verdict.
- **FMC REST pagination** (#385): the collector follows pagination — a >25-FTD inventory is a full
  census, off-host and malformed-port safe.
- **Migration-scenario denominator** (#372): uncollected devices are excluded from the Poor/Critical %.
- **Deck slide-6 lifecycle %** (#339) uses the assessable denominator (SSOT) and **"wave" noun overload**
  (#340) is disambiguated across exec-summary + runbook.

### Fail-soft totality (the recursive-poison campaign)
- Dict/str/inf/NaN-poisoned snapshot leaves can no longer 500 the untrusted endpoints or crash the
  generators: audit-6 string-op/float class (#377, #381), audit-7 unhashable class across
  `/design`, `/architecture_coverage`, `/archreview` (#386), design-advisor `_signals` leaf sites, and
  a durable whole-class recursive-poison fuzz guard committed as a test.
- The #386×#388 cross-PR fixture conflict found post-merge was fixed forward same-day (#389).

### Deliverables & webapp features
- **Per-VLAN cutover workbook: endpoint COMPOSITION column** (#364) — device-type mix per VLAN, not
  just a count, with `[NOT OBSERVED]` honesty.
- **Out-of-order gate sign-offs surfaced on the campaign board** (#387) + **PPDIOO gate-order
  enforcement + disclosure** in the engine (#376).
- **QA row-13 polish batch** (#393): deck slide-8 leads with the total decision count; MOP sub-wave
  rows carry slice-scoped cutover splits (never the parent group's 107+144); slide-2 breadcrumb
  geometry on-slide (EMU-pinned); word-safe ellipsis truncation; slide-9 truncation disclosure;
  engagement §4.2 relabeled `Endpoint MACs (per-port)` with the overlap note.

### Quality instruments (Phase 2/3 closures)
- **D10 retrieval eval**: frozen 60-query eval set + sealed anchors (P2-1, #332), falsification run
  recorded as an honest PARTIAL (#333, DEC-010 closes Phase 2 identifier-only), cross-family rung
  (#338); judge rung-5 defect-panel promotion — TNR 0.6 clears the floor, /qa APPROVEs stamp gating
  (#335).
- **Phase-3**: parser↔detector field contract (#342), diff schema-version gate + webapp (#344),
  Exec-Summary provenance (#346), graph AST-only invariant guard (#345), graph commit-currency
  selfcheck (#348), bridge-candidate queue module (#347) + semantic count fix (#375).
- **Scorecard REAL rows 11→13**: first full-pipeline BLOCK → deck fix → APPROVE bookend, then the
  first **all-APPROVE full-set row** (13; 6 Low findings, all fixed in #393 above).

### Test hardening
- **Frontend: zero → complete coverage** (#352–#360): Vitest harness (jsdom-safe), api client, UI
  primitives, component logic, page tiers, App shell, 3D logic headless, + a real-browser WebGL
  Playwright E2E lane wired into webapp-ci (#356).
- **Backend API robustness** (#361) and **engine low-coverage tiers** (#365–#367); `pir_docx`
  renderer smoke + formatter pins (#350/#351).

### Docs & process
- P3 hygiene bundle (#363), SelfMem write-operator vocabulary for learnings (#362), Phase-2 close +
  Phase-3 handoff refreshes, session retros with bridge-candidate lessons throughout.

## [v3.30.0] — 2026-07-05 — the deliverable release (MOP / Ops-Handbook / CRD excellence)

The `docs/deliverable-excellence-plan.md` P1-remainder/P2 tranche + the Cisco Advanced-Services deliverable-
standard gaps — the client-facing DOCX deliverables a senior engineer hands a change board. Built as a
3-agent isolated-worktree wave (golden-neutral by construction — DOCX is not in the frozen snapshot contract)
and hardened by a 3-lens adversarial review (find → independent refutation) that confirmed 5 HIGH + several
MEDIUM/LOW, all fixed.

### Added
- **MOP rigor** (`mop.py`): a Bottom-Line-Up-Front executive summary (wave count, go/no-go gate = worst
  readiness across the waves via the single-source reducer, one-line rollback, window estimate); a
  per-step **quantified** rollback trigger on every wave (Cisco-AS standard — ">0.1% validation failures" /
  "no convergence within N minutes", not "if something breaks"); a pre-implementation checklist (evidence-gated
  vs human-attested preconditions); a communications/escalation plan (roles, T-minus cadence, Cisco-TAC tier);
  PRE/DURING/POST phase labels; NX-OS EVPN cutover guardrails gated on an EVPN target.
- **Operations Handbook** (`ops.py`): a Backup-&-Recovery section (strategy/cadence/retention, the restore-TEST
  discipline — "a backup never restore-tested is not a backup", NDFC config-backup on the EVPN target); a
  Known-Issues register synthesized from the assessment's OWN axes (syslog signatures, software/PSIRT surface,
  hot control planes, past-LDoS/EoS platforms, QoS doctrine, CIS failures) — each citing its source axis +
  affected devices, each uncollected axis DECLARED not-assessable.
- **CRD completeness** (`crd.py`): a Constraints & Assumptions section (register-confirmed vs surfaced as OPEN
  QUESTIONS when no requirements register), an Out-of-Scope boundary statement, and a **Requirements Traceability
  Matrix** mapping each REQ-ID forward to HLD → LLD → MOP → NRFU (the Cisco-AS chain; honest "to be traced"
  placeholders, never fabricated section numbers).

### Fixed — adversarial-review findings (client-safety / coverage-honesty)
- The ops Known-Issues **Security axis** had no not-assessable branch — silently dropped when uncollected or
  clean, so the §7.1 census read as complete when security was never assessed (false-health by silence). Now
  always represented; and its "Affected" set names ONLY devices that actually failed a CIS check (was: every
  device with a security block — asserting open failures on clean boxes to a change board).
- The Syslog Known-Issues row aggregates by distinct signature CLASS before the top-N cut (one signature on
  many devices no longer crowds every other class off a real fleet's list); QoS gained its collected-clean row.
- The MOP/ops **EVPN framing** now matches the CRD's confidence: "the target IS EVPN" is asserted only when the
  requirements register confirms it, else framed as an engine assessment to confirm — never a settled
  plan-of-record from an engine default. MOP/comms `§x.N` placeholder cross-refs reworded to plain language.
- Two vacuous coverage-honesty tests hardened (asserted a heading substring always present; now assert the
  specific axis structurally), plus the MOP BLUF gate test now asserts the gate ROW, not the whole doc.

## [v3.29.0] — 2026-07-05 — the schema release (coverage-honesty as a queryable schema)

The third `docs/MASTER_PLAN_2026-07-05.md` tranche (§3.5, "deepen the actual moat"): make coverage-honesty a
*queryable schema property*, not just a runtime convention. Built as a parallel isolated-worktree agent wave and
hardened by a 4-lens adversarial review (find → independent refutation) that confirmed 1 HIGH + 3 LOW.

### Added
- **`ssot.compute_schema_census` (J3)** — the snapshot self-describes what it actually SAW: a per-section
  census projecting the coverage-honest 3-state token (`published` / `collected_but_empty` / `not_collected`)
  onto every top-level block (the SuzieQ `describe` analog). For an access-only collection this is the map that
  answers *what was seen vs what is a blind spot* — the real cause of a "filler"-feeling output is an
  uncollected tier, not a code bug. New `schema_census` key + a **Coverage Schema** sheet (blind spots red,
  collected-but-empty amber, seen green — an absent axis can never render as a clean/green result).
- **`ssot.compute_fact_lineage` (J2)** — attribute-level provenance (value / dotted-path / coverage-state /
  basis) for every canonical headline fact. New `fact_lineage` key (date-relative, golden-excluded + pinned).
- **`detector_schema.compute_detector_schema` (J1)** — a declarative registry of 32 per-detector descriptors
  (`checks` / `healthy_value` / `threshold` / `cited_fields` / `abstains_when` / `source_command`) that makes
  "not-observed ≠ healthy" a **schema property**: every evidence-gated detector carries a non-empty
  `abstains_when`. New `detector_schema` key + a **Detector Schema** sheet.

### Fixed — integration + adversarial-review findings (coverage-honesty)
- **The census had a coverage-honesty bug of its own** (HIGH): `abstention_reason` gated emptiness with a
  shallow `not val`, so a *wrapper of empty payloads* (a compute that always returns its keys but found
  nothing — e.g. `addressing_conflicts {'dup_ip': [], 'dup_subnet': []}`) was truthy and mislabelled
  `published` — a green "seen" row for a genuinely-empty result. Fixed at the single owner with a deep-empty
  check (a container all of whose leaves are empty carries no evidence), short-circuiting on the first real
  leaf; three zero-result sections on the demo fleet correctly flip green→amber.
- **The Coverage Schema sheet's row-1 banner carried live counts** — every future section added would re-trip
  the additive-only golden shrink guard, desensitising a load-bearing safety mechanism. The banner is now
  static and the roll-up moved to an `(all sections)` totals data row (locked by a test that the header carries
  no digits).
- A detector descriptor cited the bare section `trunk_native` (a *different* detector's output); fixed to the
  real backing field, and the `cited_fields` test strengthened to require a field path (never a bare section)
  and resolve simple leaves against the sample fleet — the gap that let the mis-citation ship. The SSOT
  registry-integrity guard learned the three new J3/J2/J1 owners.

The second `docs/MASTER_PLAN_2026-07-05.md` tranche (§3.4 / §4.1 / §4.2): the market-gap capabilities the
L3-centric verification tools (Batfish, Forward) do not cover, built as a parallel isolated-worktree agent
wave and hardened by a 3-lens adversarial review (find → independent refutation) that surfaced and closed
11 findings — all one class: false-health when the true incumbent is off-scan (the common case on an
access-only collection).

### Added
- **`failover.py` — the L2 failover twin** (§4.1): deterministic STP root re-election and FHRP (HSRP/VRRP/GLBP)
  takeover recomputed from `stp_roots` + `fhrp_detail`, with split-brain detection when preempt is off and a
  target-free `compute_failover_readiness` rollup ("for every observed root/active, is there a PROVABLE
  backup?"). Coverage-honest: the incumbent and the re-election winner are named ONLY when the collected
  evidence proves them — an off-scan root/active, a missing bridge priority, or an unbreakable priority tie
  all abstain (INDETERMINATE) rather than fabricate a confident answer. Exposed via 2 new read-only MCP tools.
- **`cutover_sim.py` — the cutover dry-run simulator** (§4.2): applies an ordered wave of mutations
  (`fail_node` / `fail_site` / `shut_link` / `move_fhrp_active`) step-by-step on a deep copy, and at each step
  reports the marginal reachability delta + failover recompute + a plain-English narrative ("after step 3,
  VLAN 40 loses its only path until step 5"). The input snapshot is never mutated.
- **FIB path verdicts** (§3.4): `trace_fib_path` gains an MTU / jumbo-blackhole dimension (min path MTU +
  bottleneck hop + optional required-MTU flag; a missing MTU abstains, never assumes 1500 — the check the
  EVPN underlay most needs); `trace_bidirectional` classifies RPF / return-path symmetry (symmetric /
  asymmetric / INDETERMINATE); `ecmp_consistency` is the Batfish multipathConsistency analog.

### Fixed — adversarial-review findings (11, all coverage-honesty)
- The L2 twin no longer fabricates an incumbent from the advertised root vector (identical across non-root
  bridges) or from a priority fallback over Standby-only members; it abstains when the root/active is off-scan.
- The STP survivor election abstains on an uncollected survivor priority (no `1<<30` sentinel laundered into a
  fabricated default-election) and on a genuine bridge-priority tie (the 802.1D MAC tiebreak is not collected).
- `ecmp_consistency` treats a leg whose record exists but whose MTU was uncollected as an MTU blind spot →
  INDETERMINATE, instead of reading "consistent" by omission (new `mtu_unobserved_legs` disclosure).
- `move_fhrp_active` cutover steps now report the takeover they perform.
- The executed JS↔Python FIB parity gate now projects to the shared reachability core (the wave-2 MTU keys are
  Python-only by design) with a non-vacuity guard — closing a latent break that a node-equipped CI runner
  would have hit and that a node-less environment silently skipped past.

## [v3.27.0] — 2026-07-05 — the trust release (verification-deliverable trio + K2 + cutover matrix)

The first tranche of `docs/MASTER_PLAN_2026-07-05.md` (the frontier per the saturated-analysis thesis:
turn strong analysis into audit-grade, provably-trustworthy output). Built as a parallel isolated-worktree
agent wave, then swept by a 5-lens adversarial review (find → independent refutation) that surfaced and
closed two HIGH findings before merge.

### Added — the Verification-Deliverable trio (next-best-improvements 2026-07-04 do-first #2)
- **`precert.py` — Pre-Change Validation Certificate** (roadmap C1): packages `fib.reachability_delta` into a
  decision-grade `PASS` / `CONDITIONAL` / `FAIL` / `INDETERMINATE` gate artifact on the `--compare` path —
  never `PASS` with open blind spots; each changed flow cited old→new, each inconclusive pair named. Emits
  `<out>.precert.json`, a diff-workbook sheet, and a diff-HTML block. The offline peer of Forward Predict /
  NDI pre-change analysis.
- **`attestation.py` — zero-egress attestation panel** (roadmap D3): re-derives the four trust claims
  (read-only command surface, no-egress import graph, GET-only `rest_collect`, no-LLM runtime) at build time
  with the SAME mechanics as `tests/test_readonly_and_no_egress.py` — a falsifiable proof, never a hardcoded
  badge. The doctrine test now imports the shared grammar from the module so panel and CI guard cannot diverge.
  New `attestation` snapshot key + **Trust & Sovereignty** workbook sheet.
- **`nrfu_export.py` — offline four-phase NRFU command export** (roadmap frontier :233): per-wave, per-device
  READ-ONLY verification commands with EXPECTED values pre-filled from the snapshot (`NRFU-W<w>-P<phase>-NNN`
  cases across the canonical four NRFU phases; `[NOT OBSERVED]` abstention where evidence is absent). New
  `nrfu_commands` key + **NRFU Commands** sheet + `write_nrfu_pack` per-device `.txt` packs.

### Added — cutover & tooling
- **Per-VLAN cutover workbook** (MASTER_PLAN §4.3): `compute_vlan_cutover_matrix` + **VLAN Cutover Matrix**
  sheet — one row per VLAN (STP root + default-election flag, FHRP group/VIP/priorities, gateway SVIs,
  endpoint census, app-domain criticality, dependencies, wave/scenario/readiness, blank human window +
  rollback-owner fields), coverage-honest `[NOT OBSERVED]` for absent evidence.
- **Five new read-only MCP tools** (MASTER_PLAN §4.4.1): `get_finding`, `search_devices`, `get_move_groups`,
  `whatif_node`, `get_health` join the existing seven — the snapshot becomes a first-class MCP data source.
- **K2 `PARSER_EXAMPLES` registry** (next-best do-first #3): the inline real-line fixtures become a per-parser
  committed registry replayed forever (the anchored-non-zero-parse guard against the #1 recurring
  format-fidelity bug class). Building it caught and fixed **two genuine NX-OS parser bugs** — the 2-line
  trunk-table header dropped the native-VLAN/port-channel columns, and `Kernel uptime` was misread as a
  hostname — so the golden now surfaces a previously-invisible native-VLAN-1 exposure on the NX-OS device
  (a false-health miss, now caught).

### Fixed — adversarial-review findings (both HIGH, verified by execution)
- **NRFU read-only enforcement**: snapshot strings are attacker-controllable on the `--no-collect` path (JSON
  carries `\n`); an embedded newline in an interpolated value could emit EXECUTABLE continuation lines
  (`configure terminal` / `shutdown`) into the shipped `.txt` pack — a device write, defeating guardrail #1.
  Closed with a two-layer defense (`_one_line` chokepoint + writer-side read-only refusal) and a regression test.
- **`redact_snapshot` IPv4 collision**: the JSON/explorer `--redact` path still used the in-band
  `10.{i//256}.{i%256}` scheme where a real /24 could draw a pseudonym equal to another real net (re-emitting
  a real gateway into a share-safe deliverable). Pseudonyms move to IANA-reserved Class E `240.0.0.0/4` with an
  already-240.x identity rule that preserves idempotency.

### Security
- Scrubbed two real Type-5 (MD5crypt) client password hashes that had been committed verbatim in
  `tests/test_audit5_parse_fidelity.py` (pre-existing) and copied into the new parser registry — replaced with
  length-preserving synthetic tokens. A repo-wide cross-check against 513 real collection secrets confirmed
  these were the only such leak in any tracked file.

## [v3.26.0] — 2026-07-03 — true 3D topology

### Added
- **True 3D topology** — a new `3D` explorer mode (keyboard `o` = orbit) renders the fabric as an
  orbitable 3-D scene: device tiers stacked as rings (core / distribution on the upper rings, access
  below), each switch chassis tinted by health — drawn by a **self-contained canvas-2D projector** (no
  external deps; offline / CSP-safe, like the rest of the single-file explorer). The AssessHub webapp
  gains a **2D/3D toggle** backed by a lazy-loaded `Topology3D` component. Re-expressed as one entry in
  main's table-driven MODES-registry when the 3-week-stale branch was brought current (PR #264).

## [v3.25.2] — 2026-07-03 — SSOT sweep + Plan-A #15 Stage-3 refactor

### Fixed
- **SSOT sweep (post-v3.25.1)** — a project single-source-of-truth verification found and closed three drifts:
  - **Ops-Handbook + MOP titles recomputed the inventoried device count** as a bare `len(snap['devices'])`
    (the *collected* subset on a fresh run) instead of the canonical `executive_brief.scale.n_devices` — the
    same drift class CROSS-01/02 fixed in crd/runbook/engagement, never extended to `ops.py`/`mop.py`. Both
    now read canonical-first (`len()` only pre-brief). (CROSS-03/04)
  - **Stale demo corpora** — the bundled `sample_fleet.snapshot.json` and the explorer's baked demo froze on
    2026-07-02 and missed the 2026-07-03 waves: ACL findings lacked the new `verdict` field and the
    `coverage_matrix` block was absent. Regenerated the sample (`build_sample.py`, now re-dumped
    pretty-printed so the demo stays a reviewable git diff) and hand-added `verdict` to the explorer demo's
    ACL rows.
  - **Freshness guard hardened** — `test_sample_fleet.py` now also asserts `coverage_matrix` presence and a
    `verdict` on every ACL finding (the sub-field / golden-excluded drift the key-superset check was blind to).

### Refactor
- **Plan-A #15 Stage-3 (positional collapse)** — the three wide analyze-stage syntheses in
  `COLLECT_PARSE.main()` (`compute_device_dossiers` / `compute_migration_punchlist` / `compute_executive_brief`,
  formerly 15/19/14 positional args threaded through `_run_phase`) now forward through the typed
  `AnalysisContext` carrier **by keyword** (reorder-proof) via thin ctx-adapters. The public `compute_*` keep
  their explicit signatures (webapp / excel / ~40 direct-call tests untouched); only `main()` reads from the
  carrier. Behavior-preserving — golden byte-unchanged, arg-mapping AST-verified 1:1, pinned by a
  distinct-sentinel `test_context_adapters`.

## [v3.25.1] — 2026-07-03 — post-review coverage-honesty fixes + hardening

Adversarial review of the v3.25.0 wave (PR #277 + #278). One live cloud false-health
(BUILD-02) plus a cluster of coverage_matrix false-health / correctness fixes and
type/tool hardening — every fix test-first, `tests/golden/snapshot.json` byte-unchanged.

### Fixed
- **`build_cloud` coverage-honesty on a parser crash**: the v3.25.0 typed-parser-defaults change made
  `_safe_parse` return a list parser's registered empty shape (`[]`) on a raise — which slips past
  `build_cloud`'s `isinstance(sgs, list)` guard and reports `{security_groups: []}` ("cloud observed,
  nothing world-open" = false-health) instead of not-observed `{}`. `build_cloud` now pins `_default={}`
  (a non-list crash sentinel the guard converts back to not-observed), while a genuine clean `[]` on the
  happy path is preserved. Latent today (`parse_aws_security_groups` never raises) → **golden byte-
  unchanged**. The `build.py` call-site anti-drift test learns the one intentional off-registry sentinel
  (a `shape-sentinel` marker + a pin-test scoping the exemption to exactly that site), and a pre-existing
  crash test whose `lambda` mock masked the real list-shape fallback (so it passed regardless) is made
  faithful. Found by adversarial review of the v3.25.0 wave.
- **`coverage_matrix` false-health — a not-collected device no longer vanishes** (PR #279): the matrix joined
  the (device × axis) grid on `snap['devices']`, which is built only from hosts that COLLECTED — so a device
  the collection never reached (unreachable / auth-fail) emitted zero rows and read as fully covered (on the
  Meridian reference fleet, all 50 of 303/253 not-collected devices would disappear). The join is now the inventory UNION
  (`snap['devices'] ∪ collection_completeness`), and a never-reached host abstains `not_collected` on every
  base axis (its capture/parse "covered-by-silence" inference is invalid).
- **`coverage_matrix` inventory join hardened** (PR #282): an architecture-coverage row is emitted only for a
  host that IS an inventory device; an observed class contributing no inventory device collapses to one
  `(fleet)` covered row — guarding a malformed/bare struct-keyed controller axis (`{faults:.., nodes:..}`)
  from leaking fake `device='faults'` rows into `by_device` and the covered count.
- **`coverage_matrix` correctness**: the synthetic `(fleet)` row no longer pollutes `by_device` (it is
  not a device); `summary.n_axes` counts the coverage *dimensions* (collection/capture/parse/architecture),
  not each architecture key (was ~32 on a real fleet); a parse-axis event keyed by the FS-sanitized
  collection-dir basename is mapped back to the raw inventory host, so a hostname with an FS-reserved char
  no longer silently reads "covered"; and `set(devices)` is hoisted out of the per-event loop.
- **`Verdict` string-safety**: `__str__`/`__format__` pinned to `str`'s, so `str()`/f-string/`%s` yield the
  bare value (`"proven"`) not `"Verdict.PROVEN"` — safe for any future surface that interpolates a raw member.
- **`gen_oui_registry`**: a bare-filename `--out` no longer crashes on `os.makedirs('')`, and a leading
  space no longer defeats the no-egress URL refusal.
- **Test hardening**: two coverage guards that silently asserted nothing on the shipped fixtures are now
  synthetic and always-run — the `_carry` `''`-cache sentinel and the collection false-health guard.

## [v3.25.0] — 2026-07-03 — Plan-A remainder wave (8 items) + project SSOT registry

The tail of the Plan-A backlog (Tier-2/3 remainder + the greenfield north-star's additive first
steps), plus a project-wide single-source-of-truth registry.

### Correctness & types
- **Typed parser defaults**: `_safe_parse` returns each parser's OWN empty shape via a frozen
  `PARSER_RETURN_SHAPE` (55 dict / 47 list / 2 str / 1 int) — closing the `{}`-vs-`[]` hazard at its
  root; a totality + `build.py` call-site anti-drift test keeps it from ever drifting.
- **`Verdict` ADT** (`Proven | Refuted | NotObserved | Indeterminate`, a str-mixin enum in `model.py`)
  makes abstention a TYPE, not a per-module string convention; threaded additively into the ACL
  shadow-proof findings (the other verify surfaces migrate behind it next).
- **ntc-templates CI referee** widened from 3 IOS commands to 7 across IOS **and** NX-OS
  (superset-only; a TextFSM error on an off-shape fixture → skip, never a false fail).

### Coverage & footprint
- **Coverage-as-a-first-class row**: `snap['coverage_matrix']` composes the four coverage sources
  (collection / capture / parse / architecture) into one per-(device, axis) table — coverage-honest
  (abstention explicit, never a fabricated "covered").
- The on-disk snapshot's `interfaces` subtree is **sparse-encoded** (~70% of its fields are empty
  defaults), losslessly restored via `InterfaceData.from_sparse` on read; the workbook and every
  consumer are unaffected (the in-memory snapshot stays dense).

### Performance & structure
- The shared `_link_carries` primitive on the failure-impact / causality hot path is **memoized
  per-model** (`_carry`) — a provably output-neutral drop from O(H·V·L) to O(V·L).
- **Typed `AnalysisContext`** (`cisco_toolkit/context.py`) is introduced as the strangler seam for
  the 1300-line `main()`; the leaf finalize stage is extracted onto it (`_stage_finalize`),
  golden-neutral. The remaining stages migrate move by move.
- **Rig/KB hygiene**: an offline `gen_oui_registry.py` (parses a local Wireshark `manuf`; refuses a
  URL — no-egress), an `eoldb` provenance/review-vintage guard, and `.claude/worktrees/` excluded
  from graphify.

### Governance
- **Project SSOT registry** at `docs/ssot.md` — "one index, many owners": the single map of where
  the authoritative truth for every fact lives (reference, never restate), with a
  `test_ssot_registry.py` integrity gate that fails if a pointer rots, folded into graphify, and
  referenced from `CLAUDE.md`.

## [v3.24.0] — 2026-07-02 — Plan A (EVOLVE) Move-0 + Tier-1 + Tier-2 + Tier-3

Hardening + instrumentation tranche executed in the load-bearing order of
`IMPROVEMENT_AND_GREENFIELD_PLANS.md`.

### Test-oracle & gate integrity (Move-0)
- The golden harness can no longer silently re-baseline: a missing golden FAILS, and
  `UPDATE_GOLDEN=1` rejects contract shrinkage vs git HEAD without `ALLOW_GOLDEN_SHRINK=1`.
- `webapp/tests` joined the default pytest gate; the entry module joined coverage
  (`source_pkgs`); CI coverage floor raised 80 → 85.

### Correctness instrumentation (Tier-1/2)
- `snap['parse_yield']`: zero-parse yield telemetry at the `cmdio` chokepoint —
  "collected-but-unparsed" is now a visible ledger row, never silently "feature absent";
  surfaced in the workbook, the explorer and AssessHub.
- Capture integrity widened from run-config-only to every collected capture, streaming;
  new `unverified_prompt` class for prompt-unconfirmed (timing-fallback) captures.
- Executed JS↔Python parity gate: the explorer's embedded FIB port runs under node
  against a 119-pair corpus and must match `fib.trace_fib_path` exactly.

### Confidentiality (Tier-1)
- AssessHub: CORS wildcard removed (localhost-origin regex), loopback-or-`ASSESSHUB_TOKEN`
  guard on all `/api`, explorer iframe sandboxed without `allow-same-origin`.
- Raw collection dir: unconditional `[SENSITIVE]` warning + opt-in `--redact-collection`
  in-place secret scrub; `password_env`/`$CISCO_PASS` is the documented credential default
  (`devices.example.json`).

### Structure (Tier-2)
- `_PER_DEVICE_AXES` registry: all 40 per-device evidence axes are one entry each
  (golden-byte-stable refactor — proven with no golden regeneration).
- Explorer `MODES` registry: one table drives mode wiring; the five historically
  shortcut-less modes gained keyboard shortcuts (x/w/p/v/d).
- Product surface: README describes the actual product (13 explorer modes, multi-vendor,
  proof engines); `LICENSE` and this `CHANGELOG.md` added; sample fleet regenerated with
  the full current snapshot schema.

### Confidentiality (Tier-1) — hardened further
- Explorer CSP pinned against silent regression: a test asserts the direct-open template
  and the snapshot-embedded HTML both keep `default-src` / `connect-src` / `object-src` /
  `base-uri` at `'none'` with no external origin ever allowed (Plan-A #9).
- Adversarial redaction leak corpus: 20 seeded-sentinel secret shapes across
  IOS / NX-OS / FortiGate / Junos — which caught and fixed a real miss, the
  `snmp-server host … version 1|2c <community>` trap community that survived the scrub
  (Plan-A #13).

### Performance (Tier-2)
- `compute_failure_impact` / topology: the VLAN-range parse is memoized — the one measured
  superlinear term (the same trunk-allowed / STP lists were re-split per VLAN per link).
  Membership-only and cached; a 23-case differential contract plus a cache-hit proof keep
  every output byte-identical (Plan-A #12).

### Structure (Tier-2) — webapp half of the axis pin
- A conformance test ties the webapp's `_ALLOWED_SECTIONS` (the section endpoint's
  allowlist) to what the engine actually emits and to the live `_PER_DEVICE_AXES` keys, so
  a renamed / removed section can no longer leave a dead 404 tab — the "months-dead NOS
  quartet" bug class (Plan-A #8 remainder).

### Contracts & interfaces (Tier-3)
- `cmdio.PARSER_CONTRACTS`: an as-built command → parser contract for the SSH `show`
  channel, reconciled against `build.py`'s own source by a totality test (every named
  parser exists; no phantom command; every inline dispatch is registered) — the recurring
  parser ↔ command drift class now fails the suite. Writing it immediately caught one
  unregistered dispatch (`show policy-map interface control-plane` → `parse_copp_drops`)
  (Plan-A #16).
- Snapshot JSON is written compact (tight separators, no indent) — a size win with
  round-trip and golden-neutral guarantees (Plan-A #14).
- Optional read-only MCP server (`cisco_toolkit.mcp_server`; `cisco-mcp-server` entry
  point; `[mcp]` extra): seven query tools over a produced snapshot — overview, inventory,
  device dossier, findings, failure impact, chokepoints, architecture coverage. Offline,
  no egress, import-guarded so the base package never depends on `mcp` (Plan-A #18).

## [v3.23.176] — 2026-06-11

Last tagged release before the Plan A tranche: the multi-vendor + controller-REST
assessment engine (Cisco IOS/IOS-XE/NX-OS + ACI/SD-WAN/ISE/FMC via REST, Arista,
Juniper SRX, FortiGate, AWS security groups), 12-document deliverable family,
Device Risk Register, AssessHub web platform, and the offline explorer.
See `COLLECT_PARSE_V3_23_0.md` for the full history.
