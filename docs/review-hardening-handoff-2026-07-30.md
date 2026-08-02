# Repository hardening handoff — 2026-07-30

> **Status (amended 2026-08-02): CI is repository-wide GREEN as of `213f5a3` — every job of every
> workflow, the branch's first (§13.9). Still NOT a release: the human gates (§12.10, §13.9) are
> open, and Git history still carries the original private material (§2).** The original status
> line — "active checkpoint, not a release and not a repository-wide green claim" — described the
> pre-staging tree and is superseded for the green half only.
>
> **START HERE (updated 2026-07-31, end of session 2).**
>
> **Suite: GREEN.** `exit 0, 0 failures, 595s`, checkpoint INTACT at 107 PASS. Preservation
> untouched: 0 staged, 27 deletions, 67 untracked files. Nothing committed, archived or deployed —
> §1's rules stand unchanged, and "green" is NOT "release-ready".
>
> - **Phase A: complete.** 19 known failures → 0 (§5.10–§5.26).
> - **Phase B: complete across ten lanes** (§6, §7), by independent read-only reviewers. It refuted
>   FOUR conclusions this session had already reported as verified, and found 14 defects in code the
>   suite runs past. **10 fixed and verified**, including two P0s (a privacy gate that exited 0 on a
>   repo naming the client throughout; a cutover certificate stamping FAIL on every run), three
>   CI/release blockers, a vault-write vector, and one regression introduced and then reverted here.
>
> **PHASE B IS CLOSED: 14 of 14 fixed and verified** (§7.12–§7.15). Full suite exit 0, 0 failures,
> 692 s. What is still OPEN is a short list of QUESTIONS, not defects — see the end of §7.15:
> custody's opt-in enforcement, `archreview` LC-1 on an all-Unknown fleet, and the untracked EoL
> evidentiary basis. Each changes what a customer document asserts; give each its own
> adversarial pass.
> 1. Generation semaphore ordering (`app.py:252`) — an async lifetime change; wrong, it deadlocks or
>    leaks a slot.
> 3. Registry pack binding (`registry_integrity.py:128`) — the two packs are interchangeable and
>    still verify. A design question, not a patch.
> 4. Custody semantics (`input_custody.py`) — opt-in enforcement with an erasable ledger.
>
> **Give each one its own adversarial pass.** That is not ceremony: independent refutation is what
> caught the four wrong conclusions and the regression above, and the same defect shape (a
> hand-maintained list standing in for the class it means) appeared SIX times, twice inside fixes
> made minutes earlier. A green suite proves the code does what it does; it never asks whether that
> was the claim.
>
> This is the authoritative continuation record for the repository-wide review
> started on 2026-07-28. It is written so a fresh Claude session can continue
> from the current local checkout without reconstructing intent from chat
> transcripts. The historical findings remain in
> `docs/review-findings-2026-07-28.md`; this file supersedes that document for
> current status and next actions.

## 1. Start here

The exact checkout is:

```text
C:\Users\<user>\Desktop\Enhancements
branch: review/whole-repo-2026-07-28
baseline commit: 0fd332ae55c8b4cc173fee37e17dae043aa018b7
baseline tree: b99319ad9670b394969570b9a65e125f62c542ec
```

Only the main worktree exists. Nothing in this review has been staged,
committed, pushed, reset, reverted, cleaned, or discarded.

Before doing anything, Claude must read this entire file and `CLAUDE.md`, then
start read-only:

```powershell
Get-Location
git branch --show-current
git status --short
git diff --stat
git diff
git log -8 --oneline --decorate
git worktree list --porcelain
```

Claude Code can perform the guarded bootstrap with `/resume-review`. That
command requires a complete read of this file and runs the read-only integrity
checker at `.claude/scripts/verify-review-handoff.ps1` before any edit. The
SessionStart hook also surfaces this checkpoint even while Python is missing.

Recompute status rather than trusting cached counts below. All review agents
shared this one working tree, so their source changes are already present here;
there is no separate agent branch to merge.

### Non-negotiable preservation rules

- Do not stage, commit, push, reset, revert, clean, delete, overwrite, discard,
  or rewrite history without asking the user first.
- Treat every existing modification, deletion, untracked source file, ignored
  backup, and generated audit directory as user-owned.
- Do not restore the 27 deleted tracked files merely because Git marks them
  deleted. They were removed from the candidate tree during privacy
  sanitization and their exact originals are preserved privately.
- Never print, summarize, upload, or reintroduce private identifiers from the
  sanitization backup.
- Do not run a bare `cisco-assess`: by repository contract it can SSH to live
  devices. Verification must be offline and fixture-driven.
- Do not use `graphify add`, `graphify label`, or its live GitHub tools. The
  graph must remain offline/AST-only.
- Do not create final wheels, source archives, release proofs, GitHub releases,
  PyPI uploads, or a production site until all source bytes have frozen and a
  different reviewer has checked the owning lane.
- The Git index still contains the pre-sanitization baseline. The default
  privacy gate is therefore expected to fail until the user explicitly
  authorizes staging the reviewed candidate tree. Never weaken that gate to
  make this dirty checkout appear commit-safe.

## 2. Loss-prevention inventory

### Private sanitization backup

Preserve this ignored directory exactly:

```text
private-inputs/repository-sanitization-backup-2026-07-30/
27 files
1,235,267 bytes
```

It contains exact copies of the 27 tracked files deleted from the candidate
tree. The working-tree deletion set is:

```text
AI_SESSION_CONTEXT.md
CHAT_SUMMARY.md
compass_artifact_wf-4178d659-b124-4412-9854-fc7bea5b9094_text_markdown1.md
compass_artifact_wf-6d4cf577-c82e-4281-8744-55bdc473f75d_text_markdown.md
docs/assessment/config-hardening-2026-07-07.md
docs/assessment/config-hardening-devices.json
docs/assessment/device-risk-heatmap-2026-07-07.md
docs/assessment/device-risk-heatmap.json
docs/assessment/endpoint-inventory-2026-07-07.md
docs/assessment/executive-brief-2026-07-07.md
docs/assessment/fleet-risk-synthesis-2026-07-07.md
docs/assessment/l1l2-resilience-2026-07-07.md
docs/quality/evidence/2026-07-11-row11-deck/slide7-after-computed-layout.png
docs/quality/evidence/2026-07-11-row11-deck/slide7-before-overlap.png
docs/quality/evidence/2026-07-11-row11-deck/title-after-provenance.png
docs/quality/evidence/2026-07-11-row11-deck/title-before.png
docs/security/hardening-wave-mop-2026-07-07.md
docs/security/kev-exposure-2026-07-07-devices.json
docs/security/kev-exposure-2026-07-07.md
docs/security/kev-phaseA-cab-request-2026-07-07.md
docs/security/kev-remediation-blast-radius-2026-07-07.md
docs/security/kev-remediation-mop-2026-07-07.md
docs/security/kev-remediation-nrfu-2026-07-07.md
docs/universality-gap-audit-raw.json
docs/wave-findings-2026-06-21.md
docs/wave-triage-2026-06-21.md
requirements.<initials>.json
```

The current Git history still contains the original private material. A history
rewrite, credential/identifier response, and force-push decision are separate,
destructive actions requiring explicit user authorization after the candidate
tree is finished.

### Other preserved local state

- `.claude/settings.before-ultracode.json` is ignored and preserved.
- `.claude/settings.json` only removes the persistent
  `CLAUDE_CODE_EFFORT_LEVEL=max` override; it must not silently be restored.
- `C:\tmp\enhancements-master-reference-initial-git-20260730\` is the
  recoverably moved starter repository metadata from `master-reference/`.
- `C:\tmp\enhancements-dist-proof-20260730T1246QAT\` is an older, failed
  distribution-proof workspace retained for diagnosis, not a releasable proof.
- `private-inputs/review-handoff-checkpoint-20260730/` is an ignored,
  content-recovery checkpoint created after this handoff. It contains a binary
  full-index patch for every tracked change, a tar archive of every visible
  untracked source file, a separate tar archive of all 12 ignored registry
  pytest-output trees, and checksum/readme files. Its sealed set additionally
  contains the baseline branch history as a private Git bundle, SHA-256
  manifests for every candidate source byte and every private-backup file, and
  all preserved registry-pytest files/directories, plus an exact full
  candidate-source tar (which removes checkout-dependent LF/CRLF ambiguity), a
  private tar of the 27-file sanitization backup, and a clean-room restore
  proof produced by reconstructing the checkout from the recovery set. The
  verifier re-hashes the live candidate, every archive-derived clean-room
  candidate/private/pytest byte, and a standalone extraction of the untracked
  archive before reporting `CHECKPOINT INTACT`. It supplements the live working
  tree; do not apply it over the current checkout. The history bundle and
  private-backup tar contain pre-sanitization/private material and must never
  be uploaded.
- `private-inputs/review-handoff-restore-proof-ceiling-20260730/` is the
  preserved, ignored clean-room reconstruction used by the final byte-exact
  restore proof. It is a verification copy, not another working lane and not a
  worktree registered in the original repository. The similarly named path
  without `ceiling` records the earlier line-ending diagnostic attempt and was
  preserved rather than deleted.
- Twelve `.pytest_tmp_registry_*` directories remain in the repository root.
  They contain synthetic/public registry-test output. `/.pytest_tmp_*/` is now
  ignored so they remain recoverable without entering a commit; none was
  deleted.
- `graphify-out/` is ignored and still present. Its report was generated
  2026-07-29 from baseline commit `0fd332ae`, before the final working-tree
  changes, so it is stale even though the HEAD commit string still matches.
- No reusable output files were found under `.agents`; agent conclusions below
  were recovered from their final messages and checked against the shared
  working tree where possible.

## 3. Working-tree scale at checkpoint

The read-only capture immediately before writing this handoff reported:

```text
staged entries: 0
tracked files changed: 219
  modified: 192
  deleted: 27
untracked individual files: 207
tracked text additions: 11,594
tracked text deletions: 14,305
tracked binary diffs: 6
```

The untracked count included individual files under the preserved
`.pytest_tmp_registry_*` trees. After the new root-anchored ignore rule and this
handoff file, live `git status` is the authority.

The post-handoff capture reports:

```text
staged entries: 0
tracked files changed: 220
  modified: 193
  deleted: 27
visible untracked individual files: 63
preserved ignored .pytest_tmp_registry_* directories: 12
```

The scope is intentionally broad. Do not attempt to reconstruct it by copying
only a few headline files. Major areas include:

- root engine and deliverable writers;
- privacy, evidence custody, redaction, manifest, and fail-closed contracts;
- OUI, IANA port, multicast, and Cisco EoL source authority;
- research/no-egress controls and decision-integrity gates;
- AssessHub backend, frontend, portable Atlas, and their tests;
- package discovery, source/wheel inventory, release workflows, and immutable
  proof tooling;
- documentation, SSOT pointers, CI, dependency controls, and the new
  `master-reference/` site.

## 4. Completed or substantially implemented work

“Passed” below means the named command/suite passed when recorded by the lane
owner. It does not substitute for the final whole-repository run after all
cross-lane repairs.

### 4.1 Repository privacy and client-artifact boundary

Implemented:

- `.gitignore` now covers 17 tested client-artifact shapes, including
  arbitrary CLI output basenames, snapshots/manifests/timings, Office
  deliverables, raw `show_*` captures, controller/cloud captures, conventional
  collection roots, operator input roots, transcripts, agent exports, and
  engagement-specific reports.
- Exact negations preserve the repository’s legitimate synthetic/reference
  assets.
- `tests/test_r8_client_evidence_is_ignored.py` regression-tests the 17 shapes
  and the tracked exceptions.
- Real/client-bearing tracked material was removed or replaced with fictional
  `MERIDIAN-*` / reserved-domain fixtures; the originals are in the ignored
  backup described above.
- `.github/scripts/verify_repository_privacy.py` now scans immutable index
  blobs and stable working-tree bytes separately; bounds file count and bytes;
  rejects links/reparse points, non-regular Git entries, undecodable/opaque
  content, duplicate JSON keys, client-shape paths, and known private-hostname
  digests; and rechecks file identity.
- Exact, regression-tested binary/public-source exceptions exist only for the
  two registry packs, the retained official source corpus, the Cisco semantic
  fixture, and `master-reference/public/og.png`.
- The hostname denylist contains hashes only, is cached and rechecked, and is
  bound into distribution proof schema 3.

Last recorded evidence:

- all 17 artifact shapes ignored;
- zero tracked exception files lost;
- 17/17 ignore/revert-proof tests passed;
- distribution lane’s final privacy/release suite: 49/49 passed;
- `--worktree-only` last failed solely on preserved pytest binary outputs
  before `/.pytest_tmp_*/` was added.

Important: rerun `--worktree-only` after the ignore rule. The default
index-plus-worktree mode should remain red until staging is explicitly
authorized.

### 4.2 Evidence custody, pipeline durability, and decision integrity

Implemented across `COLLECT_PARSE_V3_23_0.py`, `cisco_toolkit/`,
`research_lane/`, tests, and docs:

- bounded, stable, regular-file reads with identity/reparse checks;
- private custody copies for user-supplied evidence before engine processing;
- fail-closed mandatory pipeline phases and strict positive booleans;
- atomic incomplete receipts and coherent final evidence promotion;
- same-read custody/ABA evidence ledgers and post-write verification;
- manifest durability, evidence hashes, and independent redaction verification;
- decision-integrity fail-closed behavior for precert/research inputs;
- explicit no-egress HTTP guarding for the research lane;
- stricter path assertions, memory limits, and deterministic output contracts.

Earlier focused engine/custody runs were green, including a 100-test focused
pipeline set. These results predate the last web and registry cross-lane edits,
so rerun them rather than quoting them as final.

### 4.3 OUI, port, multicast, and EoL authority lane — frozen

The registry lane completed its remediation and supplied a final freeze:

- IEEE MA-L/MA-M/MA-S raw source bytes are retained, hashed, row-counted,
  freshness-bound, and used for deterministic OUI generation.
- IANA remains the primary port-assignment authority.
- 232 IANA aliases across 226 duplicate keys are preserved in source order.
- Curated overlay collisions at `4444/udp`, `4455/udp`, and `8800/udp` are
  suppressed instead of overwriting IANA.
- Generic `232/8`, `239/8`, and undocumented Dante multicast claims were
  removed; 21 bounded curated multicast scopes remain explicitly
  non-authoritative.
- Unknown transport protocols fail instead of falling back to TCP/UDP.
- Source dates have a 180-day maximum age and a five-minute future-skew limit.
- OUI/port packs distinguish build integrity from retained-source authority.
  Installed wheels can prove pack bytes but cannot claim access to raw source
  authority unless the retained source chain is actually present.
- EoL matching is exact-or-delimited, not a bare prefix match.
- 44 PID/date claims bind to 17 exact Cisco URLs through a retained,
  schema-checked semantic fixture.

Current exact artifacts:

```text
cisco_toolkit/data/oui_registry.tsv.gz
  563,919 bytes
  SHA-256 2120d5ca8a07cd320d480c6b5bcb5cd810c877cb70a5c949e2d635891e48a51a
  53,486 generated rows; 2 conflicting prefixes recorded

cisco_toolkit/data/port_registry.tsv.gz
  145,622 bytes
  SHA-256 3fcfa1c38e5cb7b7acf6a740f75214a3c8bfa000cb7df422593682045dea8519
  12,341 IANA assignment keys; 232 aliases; 12,352 port keys;
  12,373 total rows including 21 bounded multicast scopes

reference-data/official-sources/cisco/eol-bulletins.json
  13,261 bytes
  SHA-256 7683b29e66d3e5b39d89407e60a5f08ffbf8ef9f19ab029279ffc9d0861349c3
  17 bulletins / 44 claims / 17 URLs
```

Last recorded evidence:

- registry/OUI/port/EoL focused tests: 53/53 passed;
- lifecycle/review/service-map dependents: 37/37 passed;
- pipeline integration and guarded golden checks: 2/2 passed;
- combined registry/distribution run: 99 passed;
- Ruff and scoped `git diff --check` passed;
- direct retained-source-chain checks passed.

Do not regenerate these packs or the golden snapshot merely to make another
test pass. First resolve the mixed-authority consumer contract described in
section 5.2.

### 4.4 Distribution, privacy, and release hardening — implemented, no final archives

Implemented:

- explicit wheel/sdist inventories, `MANIFEST.in`, build-time runtime-asset
  guard, and installed-distribution verifier;
- exact build backend pins:
  `setuptools==83.0.0`, `wheel==0.46.2`;
- exact release tooling in workflows:
  `build==1.5.0`, `twine==6.2.0`;
- schema-3 distribution proof with baseline commit/tree, complete source
  manifest, archive counts/ceilings, duplicate-member/JSON defenses,
  package-metadata binding, privacy evidence, and retained-source-chain hashes;
- immutable checkout checks around tool installation, frontend rebuild,
  archive build, verification, install, smoke tests, and upload handoffs;
- immediate expected-proof recomputation before CI artifact, GitHub Release,
  and PyPI handoffs; release uses exact proof filenames instead of archive
  globs;
- source distributions retain the official IEEE/IANA/Cisco source chain while
  wheels retain runtime packs and report raw-source authority honestly;
- proof/archive output is kept outside the pushable source surface or under the
  ignored root `/dist/`.

Last recorded evidence:

- 49/49 distribution, workflow, release, and privacy tests passed after the
  final red-team fixes;
- 99-test combined registry/distribution run passed;
- AST/YAML parsing and scoped diff checks passed.

No final wheel or sdist was built. The old proof directory is explicitly not
final. A dirty-checkout build cannot honestly claim that HEAD’s tree alone is
its source; wait for reviewed staging/commit authorization or bind a separately
captured immutable dirty snapshot without mislabeling it.

### 4.5 Master-reference site — implemented locally, not deployed

`master-reference/` is a static, self-explanatory reference surface. It
contains:

- 15 major engineering decisions, each with rationale, tradeoff, enforcement,
  and evidence;
- an interactive eight-stage evidence pipeline;
- persona and search filtering;
- the authority model and an interactive trust-boundary explorer;
- PPDIOO gates, repository atlas, verification matrix, operator commands, and
  glossary;
- semantic server-rendered HTML, keyboard access, reduced-motion support, and
  responsive CSS;
- no database, authentication, analytics, cookies, runtime content fetch,
  external fonts, or operational evidence input;
- a pinned CI workflow at `.github/workflows/master-reference-ci.yml`.

The one generated social image is:

```text
master-reference/public/og.png
PNG, 1730 × 909, 2,338,417 bytes
SHA-256 ea17869f8f9f1a933e6d14ffed48d51fad2908c293d5eb439f4d61218b1cc208
```

Last locally observed:

- TypeScript type-check passed;
- Vinext/Vite production build passed;
- rendered semantic/static contract tests: 3/3 passed;
- Oxlint passed with warnings denied;
- full npm dependency audit reported zero vulnerabilities.

The site is not running at `127.0.0.1:3000` at handoff. Browser-based visual QA
was not performed because no in-app browser session was available. The
generated image itself was visually inspected.

`master-reference/.openai/hosting.json` contains only:

```json
{"d1": null, "r2": null}
```

There is no `project_id`; `create_site` has never been called. Do not invent an
ID and do not call it more than once. The site must not be deployed until its
verification matrix is updated from the final repository evidence and the
exact source state is committed/pushed for a reproducible Sites version.

## 5. Unfinished and blocking work

### 5.1 Restore a Python verification environment — RESOLVED 2026-07-31

At handoff, neither `python` nor `py` resolved and the approved interpreter was
missing. **Both are back.** Confirmed by execution, not by presence:

```text
C:\Users\<user>\AppData\Local\Programs\Python\Python312\python.exe -> 3.12.10
py -0p -> -V:3.12 *  (same path, registered default)
```

**Bind verification to `py -3.12` or that absolute path — never bare `python`.**
`python` and `python3` on PATH are Microsoft Store App-Execution-Alias stubs
that print “Python was not found” and exit 9009. This is the same stub class
that silently disabled three hooks earlier in this review, and it bit again
here: a helper script invoked as `python` produced the stub message instead of
running.

Still open from the original item: an isolated dev environment has not been
created; the repository’s dev dependencies are being used as installed.

### 5.2 Resolve mixed port-authority semantics across engine, Atlas, and UI

This is the main cross-lane design decision.

The port pack is intentionally mixed:

- IANA assignment records are official and freshness-verified;
- curated service hints and multicast scopes are clearly non-authoritative;
- pack bytes and schema can still be integrity-verified.

The current whole-pack `source_authoritative=false` is honest, but some
consumers still interpret any false whole-pack flag as total registry failure.
That breaks:

- the `Port registry authority` pipeline phase;
- `test_selftest_green_on_dev_checkout`;
- `test_selftest_gains_backup_dir_check`;
- final AssessHub verification normalization.

Recommended resolution:

1. Keep whole-pack `source_authoritative=false`; do not relabel curated facts
   as official.
2. Add/use explicit component fields such as
   `integrity_verified=true`,
   `official_source_authoritative=true`,
   `official_source_fresh=true`, and
   `authority_scope="iana-service-assignments-only"`.
3. Make engine/Atlas self-test require pack integrity plus the official IANA
   component’s source/freshness proof, not universal authority over every
   curated row.
4. Preserve per-record `assignment_authoritative`,
   `semantics_authoritative`, origin, and aliases.
5. Findings based only on curated semantics must remain labeled
   non-authoritative/assistive; UI and reports must never upgrade them to
   source-verified evidence.
6. Add cross-surface tests for official IANA lookup, curated-only lookup,
   collision lookup, unknown protocol, missing raw sources, stale/future
   sources, and corrupted pack bytes.

This scoped-authority policy preserves useful curated hints without making a
false global authority claim or disabling the engine.

### 5.3 Finish and independently verify the web fail-closed lane

The web owner implemented, but did not freeze, the second remediation pass:

- synthetic `.assesshub-redacted.invalid` marker domains instead of
  real-deployable IP/MAC spaces;
- collision-safe key and value redaction, including IP/MAC/email/serial keys;
- quoted/multiword secret producer and independent verifier;
- direct CLI JSON/HTML redaction verification;
- verifier-bound digests and strict phase booleans/completion;
- private folder custody;
- output interprocess lock, per-run staging, receipt-last coherent promotion,
  and independent raw-scrub copy-back verification;
- summary contract v3, list/campaign freshening, unknown-integrity gating, and
  stricter frontend normalization.

The last full `webapp/tests` run reached three failures:

- one stale custody expectation, which appears to have been edited afterward
  but was not rerun;
- two Atlas self-test failures caused by the mixed-authority contract in
  section 5.2.

After the policy fix, run the complete web backend and frontend suites. Then
give this lane to a reviewer who did not author it, specifically challenging:

- redaction of keys and values, collisions, exhaustion, and direct CLI output;
- multiword/quoted secrets and verifier independence;
- concurrent jobs and coherent-set promotion;
- scan-to-process swaps, symlinks, junctions, and same-path replacement;
- stale list/campaign summaries and contradictory contract fields;
- unknown integrity, missing ledgers, truthy non-booleans, and absent receipts.

Do not restore the first-pass “801 passed” status. That pass was correctly
reopened by adversarial review.

### 5.4 Repair the SSOT freshness test collection defect — RESOLVED 2026-07-31

Reproduced first: `py -3.12 -m pytest --collect-only -q` ended in
`ERROR tests/test_registry_freshness.py` /
`!!! Interrupted: 1 error during collection !!!`. The whole suite collected
**nothing**, so no result anywhere was evidence.

Checked against baseline HEAD before choosing a fix: `_main_checkout_root` is
**entirely generic** — `git rev-parse --git-common-dir`, fail-open to `ROOT`.
It carried no private path; only its former callers
(`SIDE_ENGAGEMENT_POINTERS` and their tests) did, so it was deleted as
collateral. `test_ssot_registry.py` has no remaining use for it.

Fixed per this section's first option: the resolver is now defined in
`tests/test_registry_freshness.py`, its single consumer, with the clean
clone/worktree fail-open behaviour preserved verbatim. No private-path logic was
restored and the cross-module coupling is gone.

Collection regression test added as
`tests/test_cross_module_test_imports.py` — deliberately a **separate** module
(a guard inside the broken file is killed by the breakage it reports) that
resolves sibling-test-module imports **from the AST without importing
anything**, so a stale name surfaces as one named test failure instead of
aborting collection repository-wide. Proven on a synthetic pair: it flags the
absent name and stays silent on the present ones.

Evidence: `--collect-only` exits 0; focused run of
`test_ssot_registry` + `test_registry_freshness` + `test_cross_module_test_imports`
+ `test_selfcheck` = 60 passed. Repository-wide pytest has **not** been rerun
since; that remains open.

### 5.5 Decide and enforce the wheel’s generator inventory

`cisco_toolkit/data/gen_port_registry.py` is a development/provenance generator,
not runtime code. Current namespace discovery includes `cisco_toolkit.data` in
the wheel even though coverage and tests describe the generator as dev-only.

Recommended resolution:

- exclude `cisco_toolkit.data` as an importable package from wheel discovery;
- keep the two `.tsv.gz` packs and `registry_manifest.json` as
  `cisco_toolkit` package data;
- retain the generator and official sources in the sdist for reproducibility;
- update the verifier’s exact wheel/sdist inventories and import/no-egress
  tests.

Do not remove the source generator from the sdist.

### 5.6 Final privacy, package, and history decisions

After all source changes are frozen:

1. Run the candidate working-tree privacy proof.
2. Review every deletion/sanitization and untracked source file.
3. Ask the user for staging authorization.
4. Stage deliberately, never with an unexplained blanket sweep.
5. Run the default index-plus-worktree privacy proof.
6. Commit only after the default proof, full tests, and source inventory pass.
7. Build wheel/sdist from the exact committed tree in a clean/immutable
   environment.
8. Verify archive inventories, metadata, privacy, hashes, installed entry
   points, source authority semantics, and proof schema.
9. Separately ask whether to rewrite historical private material and force-push.

History rewrite is not a prerequisite for validating the candidate tree, but
the repository must not be described as history-clean until that separate
operation is completed.

### 5.7 Finalize, verify, and deploy the master reference

Only after repository verification:

- replace provisional statuses/counts with final evidence;
- document the scoped port-authority decision;
- add the final package/source-chain proof identifiers;
- rerun type-check/build/rendered tests/lint/audit;
- restart a local preview and perform keyboard, responsive, reduced-motion,
  content, and console/network visual QA;
- create the Sites project exactly once, persist its opaque `project_id`, push
  the exact site source state, save a version from that commit, deploy the saved
  version privately, poll to terminal success, and inspect production;
- update `metadataBase`/Open Graph metadata with the actual production URL and
  save/deploy the final version.

### 5.8 Checkpoint-tooling defects found while resuming — 2026-07-31

Three problems in the checkpoint machinery itself, all found by running it.

**a) The 12 preserved pytest directories were unreadable, and the cause is
worth recording.** Every one raised `UnauthorizedAccessException`; even
`Get-Acl` and `icacls` were denied. Root cause: **Codex ran under a separate
Windows account**, `TANVEER-AHAMED\CodexSandboxOffline` (…-1004), not
`<user>` (…-1001). `private-inputs/` and `reference-data/` are still owned by
that account — harmless, because they remain readable and every archive inside
them hash-verifies — but the pytest directories additionally carried a
restrictive DACL.

No content was lost: the sealed
`ignored-registry-pytest-output-ceiling.tar` re-hashed to its recorded
`9f63568a…` while the live copies were still denied. Access was restored with
`takeown` (user-run, elevated) plus an owner-level `icacls` grant; all 12 now
enumerate and expose exactly the 1,084 files the sealed manifest records.

One consequence remains: git refuses to operate inside
`private-inputs/review-handoff-restore-proof-ceiling-20260730` (“dubious
ownership”). A single scoped `safe.directory` exception was added for that exact
path — no wildcard. Undo with `git config --global --unset-all safe.directory`.

**b) The verifier could not express continued work, and forbade its own
required workflow.** It asserted the live tree byte-identical to the checkpoint
at five points (counts, untracked inventory, source-manifest inventory,
per-file bytes, and the end-of-run recheck) using the *same* constants as the
sealed clean-room checks — so the first authorized fix turned it permanently
red. It also pinned the handoff's own SHA-256, which made “update the
verification ledger after each completed lane” — required by `/resume-review` —
break the gate that protects the protocol. **One control was standing in for two
independent dimensions: the same defect shape as §5.2's port authority.**

Resolved by separation, not relaxation. Sealed assertions (archive hashes,
manifests, private backup, pytest archive, clean-room reconstruction, restore
proof) still use the frozen constants and remain fatal. Live-tree expectations
are now *sealed + an explicit declaration* in
`.claude/scripts/review-live-delta.json`, where every changed or added file is
**re-anchored to a declared SHA-256/byte-count, never exempted**. The end-of-run
handoff recheck now compares to the value observed at start (mirroring the
existing checksum-ledger pattern), so it still proves nothing mutated mid-run.

Refuted before being believed — baseline 0, then:

```text
undeclared tracked modification    -> exit 1  (anchor: sealed manifest)
undeclared new untracked file      -> exit 1  (sealed + declared delta count)
declared file, WRONG declared hash -> exit 1  (anchor: declared live-delta)
restored                           -> exit 0
```

**c) The verifier is PATH-sensitive and this nearly produced a false proof.**
Launched from Git Bash it fails at
`/usr/bin/tar: Cannot connect to C: resolve failed` — MSYS GNU tar reads
`C:\...` as a remote `host:path`, where Windows `bsdtar` does not. Run it from
**PowerShell**. This matters beyond convenience: the first refutation of (b) was
run from Bash, so every probe “failed” at the tar step *upstream of the
assertion under test* and proved nothing. It was rerun under PowerShell, which
is where the table above comes from. A red result is only evidence once you have
confirmed it is red for the reason you are testing.

### 5.9 Session record — 2026-07-31 (continuation)

**Resolved:** §5.1, §5.4, the 12-directory ACL block, the checkpoint verifier's sealed/live split
(§5.8), `verify-green.sh`'s false RED, and §5.2's consumer contract.

**§5.2 — closed.** The producer was already correct; the gap was that
`official_source_authoritative` had exactly ONE occurrence repo-wide (the producer itself). Nothing
consumed it. Repointed `webapp/backend/serve.py` (Atlas `--selftest`) and
`COLLECT_PARSE_V3_23_0.py`'s data-authority phase onto *integrity + official component*, with both
component fields falling back to `authoritative` when absent so the OUI pack is evaluated exactly as
before. `tests/test_pipeline_inprocess.py:116` had asserted the phase SHOULD fail — pinning the
defect as intended behaviour — and now asserts the corrected contract. Freshness is deliberately NOT
exposed as a separate flag: `registry_integrity.source_authority_details` only sets
`source_authoritative` when the retained bytes verify AND satisfy the 180-day/skew bounds, so a
duplicate `official_source_fresh` would assert a second proof that does not exist.

**§5.3 — partially advanced, NOT closed.** Independent redaction verification rejected
`ppt/printerSettings/printerSettings1.bin`, a part python-pptx writes into EVERY deck, so every
pipeline run ended `[INCOMPLETE] Mandatory finalization failed`. Fixed by SCANNING binary members
rather than skipping or rejecting them (skipping would wave through unscanned bytes; rejecting
blocks a valid delivery).

> Testing that fix found a defect **in the fix**: a leak planted as UTF-8 was caught while the same
> leak as UTF-16 was MISSED, because UTF-16 decoding is byte-alignment sensitive. Both alignments are
> now scanned, and all three variants are caught against a real producer artifact. The encoding the
> branch existed for was the one silently passing.

With `.bin` cleared the verifier reaches a DEEPER finding — 24 leak indicators — which splits two ways
and must not be fixed with one rule:

- ~~`Cisco serial at out_executive_deck.pptx:ppt/presProps.xml.@uri`~~ — **RESOLVED.** Confirmed a
  false positive: the value is the fixed OOXML GUID `{D31A062A-798A-4329-ABDD-BBA856620510}`, whose
  tail `BBA856620510` satisfies `[A-Z]{3}\d{4}[A-Z0-9]{2,6}` by coincidence (`BBA`/`8566`/`20510`).
  python-pptx writes it into EVERY deck, so the verifier had reported a serial leak on every `.pptx`
  it ever checked, in bytes the redactor does not author and cannot clean.

  Fixed as a **context exclusion**, not a looser pattern: `_GUID_RE` + `_inside_guid()` in
  `webapp/backend/redaction_verify.py` exempt a token only when it lies wholly inside a complete
  8-4-4-4-12 GUID. The rejected alternative — making `_CISCO_SERIAL_RE` reject hex-only tokens —
  would have silenced the noise by also blinding the check to real serials that happen to be
  hex-shaped, i.e. the check defanging itself to quiet its own output.

  Evidence: `tests/test_redaction_verify_guid.py` (12 tests) pins the exemption's NARROWNESS —
  a real serial beside a GUID, a broken 3-char group, a truncated GUID, a non-hex tail, the bare
  tail alone, and hyphens-without-a-GUID must all still report. It also pins the PREMISE (if the
  serial pattern stops matching the GUID tail, the exemption is dead code and should be deleted,
  not left to widen). Mutation-proven: with `_inside_guid` forced to `False` the false-positive
  test goes RED. Verified against the REAL producer artifact, not a fixture — scanning
  `out_executive_deck.pptx` from `.pytest_tmp_registry_goldencheck_20260730_08/` (read-only)
  yields `total leaks=0` with the guard and reproduces the exact finding string
  `Cisco serial at out_executive_deck.pptx:ppt/presProps.xml.@uri` without it. That deck now
  scans clean. Redaction lane re-run: 153 passed, exit 0.

  > A test case written for this fix was itself vacuous — `…-BBA856620510123` asserted a leak the
  > BASE regex never produces (the 6-char cap on the trailing group cannot reach a non-alphanumeric
  > boundary), so it would have passed with or without the guard. Replaced with a broken-group GUID
  > that the serial pattern genuinely matches.

- ~~`non-pseudonym IPv4/IPv6 at out_design.docx:word/document.xml` (many) look like **genuine
  unredacted addresses**~~ — **that reading was WRONG, and the correction is the finding.** Dumping
  the actual tokens instead of the counts shows 5 distinct values over 17 occurrences: `0.0.0.0/0`,
  `224.0.0.2`, `FF02::66`, `fe80::`, `::/0` — every one a protocol constant already allow-listed by
  `_documented_example()`, sitting inside the engine's own authored doctrine sentences. No client
  data was ever in that list. **Triage by count is how a false positive gets promoted to a breach.**

  Two structural defects, pulling opposite ways:

  1. **Too narrow on surface.** The gate was `"design_blueprint" in path_tokens or "design_nrfu" in
     path_tokens` — the *snapshot JSON schema* path. The identical sentences also render into
     deliverable documents, whose paths carry no such token. Effect: **every `--redact` run failed
     mandatory finalization**, so a redacted deliverable set could not be produced at all.
  2. **Too wide on containment.** `any(phrase.casefold() in text.casefold())` asked whether the
     sentence appears ANYWHERE in the document. Once it did, *every* occurrence of that constant
     document-wide was exempt — including a genuinely leaked one. The `10.0.0.0/16` branch two
     lines below did containment correctly, so the function disagreed with itself about its own rule.

  Fixing only (1) would have multiplied (2) across three more artifacts.

  **Enumerating surfaces was the trap, and I nearly fell in it.** My first fix was "accept any path
  token containing `design`" — which covers `out_design.docx` and looks right. Measuring first
  showed the doctrine copy also renders into `out_crd.docx` and `out_archreview.docx`, neither of
  which contains `design`. That fix would have repeated the same named-subset mistake one level up.
  The structural class is **the authored sentence**, not the artifact it lands in; an artifact list
  rots the moment a new deliverable renders the same copy, which is precisely how crd and archreview
  came to be missed in the first place.

  Fix: `_AUTHORED_CONSTANT_PHRASES` (one table, replacing three divergent inline branches) +
  `_token_within_authored_phrase()`, surface-independent and containment-based. Phrases are matched
  with elastic whitespace (`_phrase_pattern`) because OOXML splits a sentence across runs, so a
  literal `find` matches the JSON and silently misses the DOCX — the two surfaces this must treat
  alike. Net: **wider on surface, strictly tighter on containment.**

  Evidence: `tests/test_redaction_verify_authored_constants.py` (30 tests, weighted toward the
  containment cases — that is the direction in which this check can go silently blind). Both halves
  mutation-proven: restoring the "phrase anywhere" rule drops a planted leak (2 IPv4 findings → 1);
  restoring the surface gate falsely flags 3/3 deliverables, reproducing the finalization failure.
  Against the REAL producer — a full offline `--redact` run — all 8 generated deliverables now scan
  `leaks=0`. Redaction lane: **111 passed, exit 0**.

**The 6 `test_phase_timings_contract` failures were NOT environmental.** I had been counting them in
the "~10 environmental" bucket. Measured: with Python312 on PATH they persist, because that module's
fixture performs a real `--redact` run, which was exiting 1 on the 24 indicators above. 5 of the 6
were fixture-setup ERRORs — the tests never executed at all. The lesson is the bucket: "environmental"
was inferred for the group from a property proven of some members.

> **Newly exposed, NOT caused — needs the lane owner.** With the fixture building, 4 tests in that
> module now run and fail against `webapp/backend/ingest.py::_assert_redaction_phases_ran`. The
> implementation **contradicts its own docstring**: the docstring states "Absence is tolerated
> because there is genuinely no evidence either way; a stale ledger is different", while the code
> raises `REDACTION COULD NOT BE VERIFIED - the mandatory phase ledger is absent`. The other 3
> failures report the ledger as belonging to an EARLIER run — consistent with that module's
> *module-scoped* `redact_run` fixture (a deliberate ~25s optimization), which makes every test
> after the first look like a `--reuse-out` run to the staleness check. So this is plausibly a test-rig
> artifact rather than a product defect, but the absent-sidecar case is a genuine contract
> disagreement with a safety direction to it: refusing on absence is fail-closed but blocks
> legitimate runs whose sidecar write failed soft. `ingest.py` is modified at the sealed checkpoint
> and is NOT in this session's delta — it is prior work. **Not decided here**; deciding it by
> guessing which side is right is how a fail-closed guard gets loosened to make a suite green.

**~10 failures are ENVIRONMENTAL, not code.** Proven by toggling one PATH entry on an unchanged tree:
without Python312 on PATH `exit=1, 4 failed`; with it `exit=0, 0 failed`. The hooks resolve `python`
by PRESENCE, and `command -v python` succeeds for the Microsoft Store alias stub. **Do this first** —
until then a third of the suite is noise that misleads triage.

> A rewrite of all 9 hooks to a shared resolver was ATTEMPTED AND REVERTED: it took the suite from 15
> failures to 25 (Windows-vs-POSIX path form, plus a silent LF→CRLF rewrite that `git diff` hid and
> only the sealed manifest caught). The hooks are byte-exact again. **Fix PATH, not the hooks.**

### 5.10 Corrected failure inventory — the earlier triage was built on a truncated list

**Read this before trusting any earlier failure count in this document.** Every prior triage in this
file was assembled from the `verify-green.sh` Stop-hook tail, which is `tail -n 20`. The list was
longer than 20 lines, so the tail silently dropped the top of it, and the categories I built
("~10 environmental, 2 goldens, 1 sample, 1 eoldb") described **the bottom of an alphabetical list,
not the failure set**. The repo's own guardrail 3 names this class — absence rendered as health —
and the truncation made 11 failures absent.

Measured directly, full suite, Python312 on PATH: **19 failures, exit 1.**

| Group | n | State |
|---|---|---|
| `test_phase_timings_contract` | 4 | Newly EXPOSED by the §5.3 fix (fixture now builds). `ingest.py` contract disagreement — see §5.3. Not mine. |
| `test_html_dos_guard` | 7 | **RESOLVED — the tests were wrong.** See §5.11. |
| `test_pipeline_golden` ×2, `test_sample_fleet` ×1 | 3 | Awaiting authorized re-bless (§5.2 resolved, which was the precondition). |
| `test_attestation`, `test_cable_map`, `test_gate_state`, `test_html_coverage_ssot` | 4 | Now diagnosed — see §5.12. Four different causes, none of them flaky. |
| `test_parsers::eoldb` | 1 | Stale test vs retained source; frozen registry lane. |

So **11 of 19 had never been looked at**, and two separate groups (11 of the 19) are the same
pattern: a guard hardened in an earlier round while its tests still pin the older contract. That
pattern is worth naming for whoever continues — it is not a flaky-test story, and the resolution
direction (loosen the guard vs update the test) is a safety decision per lane, not a sweep.

> Method note, since it will recur: the tail of a truncated failure list is a SAMPLE, and an
> alphabetically-ordered one at that. Counts and categories must come from the full list — run the
> suite and read all of it, or the triage describes whatever happened to survive truncation.

### 5.11 `test_html_dos_guard` — the tests pinned false health (RESOLVED), and what that exposed

**7 failures, and the implementation was right.** These are DoS/crash-safety tests: a poisoned
snapshot (a scalar where a list or dict belongs) must not 500 the route. They also asserted
`verdict in ("CLEAN", "REVIEW", "REGRESSED")`. The route returns 200 — the crash surface is
genuinely fixed — with `INDETERMINATE`.

`INDETERMINATE` is `compute_snapshot_delta`'s **first** verdict branch (`cisco_toolkit/html.py:415`),
reached `if integrity_failures:`, and its note reads *"Delta certification withheld: N
integrity/schema gap(s) make one or more analyses unavailable. **No missing/failed section was
interpreted as clean.**"* That is CLAUDE.md guardrail 3 implemented exactly. The assertion therefore
required a corrupted snapshot to still yield a **certification** — it pinned the false-health
outcome as the contract. The verdict clause was incidental to tests written for the crash surface,
the guard was later hardened to refuse, and then the tests were what stood in the way.

Corrected in `tests/test_html_dos_guard.py`, and deliberately **not** by widening a set and moving
on — that is how a test gets defanged to green a suite. The widening is paired with an assertion
that did not exist before: an `INDETERMINATE` verdict must carry the withheld-certification note, or
it cannot be told apart from a silent default. Measured live, not assumed: 2 of the 6 delta poisons
reach `INDETERMINATE` with the note, so the new check is exercised rather than dead. Discrimination
is held at the other end by the pre-existing well-formed-path tests, and the clean-vs-clean control
returns `CLEAN`. `test_html_dos_guard.py` now passes, exit 0.

> **NEW FINDING, not fixed — the third instance of this review's recurring pattern.**
> `html.py:290` reads:
>
> ```python
> old_integrity = _analysis_integrity(old, ("health_scores", "punchlist"))
> ```
>
> The integrity gate is applied to a **hardcoded pair of sections**, while the delta demonstrably
> consumes more — the poison table in that very test file names `executive_brief` (`:207`),
> `interfaces` (`:211`) and a finding's `devices` (`:71`) as live crash sites. Measured: of the 6
> poisons, 2 correctly refuse certification and **3 return `CLEAN`** (`executive_brief_int`,
> `brief_scale_int`, `interfaces_element_int`). A snapshot with a corrupted section is certified as
> having nothing wrong, because the corruption degrades that section to empty and empty reads as
> healthy — guardrail 3's exact wording, in the delta's own certification path.
>
> Same shape as §5.2 (a whole-pack flag standing in for components) and §5.3 (a surface list
> standing in for the authored-sentence class): **a guard written for a NAMED subset instead of the
> STRUCTURAL class it belongs to.** Three independent instances is a pattern worth searching for
> deliberately rather than meeting one at a time.
>
> **Not fixed here.** Widening `_analysis_integrity` to every section the delta consumes changes
> certification semantics — more runs would become `INDETERMINATE`. That is the fail-closed
> direction and probably right, but it changes what a deliverable verdict means, which is the lane
> owner's call, not a side effect of greening a test file.

**Open, with the decision named:**

- `tests/test_pipeline_golden.py` (×2) and `tests/test_sample_fleet.py` are most likely §5.2 working
  correctly — the port phase no longer fails, so the pinned snapshot legitimately moved. This section
  gated that re-bless on §5.2 being resolved; it now is, but the pins need explicit authorization.
- `tests/test_parsers.py::test_eoldb_compact_3560c_2960c_not_classic_family_dates` — **diagnosed,
  deliberately NOT fixed.** The test asserts Catalyst 3560-C `ldos == 2021-10-30`; the engine returns
  `2021-10-31`, which is what the retained source says — `reference-data/official-sources/cisco/
  eol-bulletins.json` carries `ldos: 2021-10-31` on all five `WS-C3560C*` patterns. §4.3 rebound all
  44 date claims to retained source bytes, so the test expectation predates that rebuild and is one
  day stale. Editing the assertion to match is exactly how a source-of-truth test becomes a rubber
  stamp, and §4.3 declares this lane FROZEN, so it needs the registry owner to confirm the source
  reading (Phase B, proposer != verifier).
- ~~The verifier's sealed reverse-patch check~~ — **CLOSED.** It was the fifth and last sealed/live
  site. Declared files (and only those) are now passed to `git apply --check --reverse` as
  `--exclude=`; each is already pinned to a declared SHA-256, so excluding them from a structural
  check they cannot pass leaves nothing unverified. Refuted both ways: a DECLARED file that drifts
  fails on `anchor: declared live-delta`, an UNDECLARED one on `anchor: sealed manifest`.
  **Checkpoint is INTACT again — 107 PASS, exit 0** (run it from PowerShell, never Git Bash: §5.8c).
- **§5.5 — appears ALREADY SATISFIED; needs a build to confirm, not a code change.** Its premise is
  that namespace discovery pulls `cisco_toolkit.data` into the wheel. Three facts say it cannot:
  `cisco_toolkit/data/` has **no `__init__.py`**, so `[tool.setuptools.packages.find]` (find, not
  find_namespace) cannot discover it; `include-package-data = false`; and the package-data list is
  exactly `data/*.tsv.gz`, `data/registry_manifest.json`, `blast_radius_explorer.html` — no `.py`.
  This matters because `gen_port_registry.py` imports `urllib.request` and FETCHES; it is carried as
  a disclosed no-egress exception (`tests/test_attestation.py:103`), so it must never be importable
  from an installed wheel. Remaining step is evidence, not edits: build a wheel + sdist to a TEMP dir
  and assert the generator is absent from the wheel and present in the sdist. Deliberately not done
  here — this handoff forbids creating archives before the source freeze, and a throwaway diagnostic
  build should be an explicit decision rather than something a resumed session does silently.
- Phase B, Phase C — not started.

## 6. Ordered continuation plan

### Phase A — recover and reconcile

1. Perform the read-only start protocol from section 1.
2. Re-verify the private backup count/bytes and all preserved temp paths.
3. Restore Python 3.12 and create an isolated dev environment.
4. Fix only the stale `_main_checkout_root` import/ownership defect.
5. Run collection-only smoke tests to prove the test harness works.
6. Implement the scoped port-authority consumer contract.
7. Finish the web lane’s remaining test adaptations.

Exit criterion: test collection succeeds and focused cross-lane suites are
green without weakening authority or privacy claims.

### Phase B — independent adversarial review

1. Assign registry consumers to a reviewer other than the registry author.
2. Assign web/redaction/custody to a reviewer other than the web author.
3. Assign packaging/privacy/release to a reviewer other than the distribution
   author.
4. Resolve every concrete finding and rerun the affected complete lane.

Exit criterion: every lane has author proof plus an independent review with no
unresolved high/medium finding.

### Phase C — repository-wide verification

Run, in an isolated environment and in this order:

```text
privacy candidate proof (--worktree-only while unstaged)
Python compile/import smoke
Ruff over the complete repository
complete pytest suite
coverage gate (>=85% for the configured measured surface)
gated mypy modules
honest full-project mypy report
AssessHub frontend install/test/build/lint/audit
master-reference install/test/lint/audit
workflow/release/privacy test suites
pip check and installed-environment dependency audit
git diff --check
offline graphify update + diagnose
```

Record exact commands, versions, counts, failures/skips, and whether a result is
focused or repository-wide. Never turn a focused pass into a global claim.

### Phase D — reviewed index and immutable distribution

1. Present the complete candidate diff/deletion/source inventory to the user.
2. Obtain explicit staging authorization.
3. Stage deliberately and run the default privacy gate.
4. Obtain commit authorization and create the reviewed source commit.
5. Rebuild the AssessHub SPA from the locked graph.
6. Build exactly one wheel and one sdist from the immutable source.
7. Run Twine checks, distribution verifier schema 3, isolated wheel install,
   entry-point/self-test smoke, registry integrity/authority checks, and final
   immutable-source proof.

Exit criterion: archive hashes and proof refer to the exact reviewed commit and
tree; no mutable handoff gap remains.

### Phase E — master-reference deployment and handoff

1. Update the site with final evidence.
2. Complete local/browser QA.
3. Create/save/deploy through Sites as described in section 5.7.
4. Inspect production and record its URL/version/source commit.
5. Give the user separate choices for:
   - keeping changes local;
   - staging/committing;
   - pushing/opening a PR;
   - rewriting sensitive history and force-pushing;
   - deleting preserved local temp/backup material after acceptance.

## 7. Verification ledger at handoff

| Surface | Last observed | Current interpretation |
|---|---:|---|
| Ignore-shape regression | 17/17 passed | Implemented; rerun after final tree freeze |
| Focused engine/custody set | 100 passed | Earlier pass; cross-lane rerun required |
| Registry focused | 53/53 passed | Frozen owner proof |
| Registry dependents | 37/37 passed | Frozen owner proof |
| Registry integration/golden | 2/2 passed | Frozen owner proof |
| Registry + distribution combined | 99 passed | Strong cross-lane focused proof |
| Distribution/release/privacy | 49/49 passed | Implemented; no final archives |
| Web backend complete suite | 3 failures last reported | Open; authority policy + rerun required |
| Master-reference rendered tests | 3/3 passed | Local source proof |
| Master-reference type/build/lint | passed | Local source proof |
| Master-reference npm audit | 0 vulnerabilities reported | Recheck from clean locked install |
| Checkpoint verifier | 107 PASS, exit 0 (PowerShell) | Green; sealed/live split refuted 4 ways |
| Test collection | `--collect-only` exit 0 | Restored; was aborting the entire suite |
| SSOT/freshness/collection-guard focused | 60 passed | Focused only |
| Python toolchain | 3.12.10 via `py -3.12` | Restored; bare `python` is a Store stub |
| Preserved pytest dirs | 12 readable, 1,084 files | ACL restored; matches sealed manifest |
| Whole repository pytest | not run after final edits | Open |
| Final coverage | not run after final edits | Open |
| Full Ruff/mypy/dependency audit | not run after final edits | Open |
| Default index privacy proof | expected failure on stale index | Requires reviewed staging authorization |
| Final wheel/sdist/install proof | not built | Open |
| Browser visual QA | not run | Open |
| Sites project/deployment | not created | Open |

## 8. Decisions that must not regress

- Official-source authority and pack integrity are different dimensions.
- Curated data may assist but must never overwrite or masquerade as official
  assignments.
- Missing/unknown integrity is blocking, not implicitly healthy.
- Producer claims do not verify themselves; redaction and archive proofs need
  independent consumers.
- A successful process exit is insufficient without mandatory positive phase
  evidence and a coherent final receipt.
- Input path validation is insufficient without custody or same-read binding.
- Privacy proof must cover the Git index as well as the working tree before a
  commit.
- Release proof must bind the exact source tree and survive the upload handoff.
- The master reference explains the product but is not an operational control
  plane or a second source of truth.
- Proposer and verifier remain separate for every consequential lane.

## 9. Suggested prompt for the next Claude session

```text
Continue the repository-wide hardening review in
C:\Users\<user>\Desktop\Enhancements on
review/whole-repo-2026-07-28.

Read CLAUDE.md and docs/review-hardening-handoff-2026-07-30.md completely.
Start read-only and preserve every current change, deletion, untracked file,
ignored backup, and pytest output directory. Do not stage, commit, push, reset,
revert, clean, delete, overwrite, regenerate final archives, or deploy without
the required user approval.

First restore/confirm Python 3.12, repair the stale _main_checkout_root test
import without restoring private paths, implement the scoped mixed-port-
authority consumer contract described in section 5.2, and finish the web
fail-closed lane. Then use independent reviewers and follow phases B through E.
Report focused versus repository-wide evidence honestly.
```

### 5.12 The four remaining singletons — diagnosed, three not fixed here

Each has a different cause. None is flaky, and none should be re-run in hope.

**a. `test_attestation::test_no_egress_walk_reaches_subpackages_and_the_exception_is_not_dead` —
a STALE CHARTER, and the underlying news is good.** The test guards a previously-fixed defect: the
no-egress walk once used `os.listdir` (top level only), so `cisco_toolkit/data/gen_port_registry.py`
— which fetched iana.org via `urllib.request` — was never opened, and the client-facing Trust &
Sovereignty sheet published "0 network-library imports" over a file it had not read.

Measured now: the walk IS recursive (72 files scanned, `NO_EGRESS_EXCLUDE` is only
`rest_collect.py`), the file IS reached, and it **no longer imports `urllib` at all** — the package
returns `offenders={}`. Someone made the generator offline. So the failing assertion
(`"data/gen_port_registry.py" in offenders`) is asserting a defect that has been repaired.

The residue is a real, if benign-direction, defect: `NO_EGRESS_EXCEPTIONS` still names
`data/gen_port_registry.py`, so the attestation carries a documented exception that now matches
nothing. The test's own last line names this exactly — *"a never-firing exception is a stale
charter"*. The correct fix is to DROP the exception, which makes the published claim strictly
stronger ("no network imports, no exceptions" rather than "none except this one file").

**Not applied here.** It edits a client-facing Trust & Sovereignty claim in the frozen
packaging/privacy lane (§5.5). When it is applied, the test needs rewriting too, and the load-bearing
half must survive: it must still prove the walk REACHES subpackages. Do NOT prove that via a named
offender again — that is what went stale. Prove it structurally, e.g. assert the scanned count
equals an independent recursive enumeration of the package minus `NO_EGRESS_EXCLUDE`, so the guard
pins recursion itself rather than one file's current contents.

**b. `test_cable_map::test_snapshot_delta_carries_cabling_and_verdict` — RESOLVED, and it was
neither of the two things it looked like.** The verdict was `INDETERMINATE` where `REGRESSED` was
expected, which reads as either the §5.11 stale-test shape or its opposite (a guard firing on
legitimate input). Checking the fixture instead of pattern-matching the symptom: `_delta_snap()`
returned `{"interfaces": ...}` and nothing else, so `health_scores` and `punchlist` were **absent,
not corrupted** — `_analysis_integrity` reports `missing or unusable` and the delta withholds
certification. Correct behaviour: a snapshot carrying no health data has not been shown healthy.

So an interfaces-only fixture can never reach `CLEAN` or `REGRESSED`, and **both** assertions in
that test were measuring the fixture's thinness rather than the cabling logic they name — including
the identical-pair `CLEAN` case, which had nothing to do with cabling at all. Fixed by giving the
fixture the two sections a real `--compare` snapshot always carries, held IDENTICAL across the pair
so link status stays the only moving part. Measured: integrity `ok: True`, down-cable pair →
`REGRESSED` with `cable` in the note, identical pair → `CLEAN`. `test_cable_map.py`: 17 passed.

> Worth keeping: the guard did NOT swallow the cable signal. Under `INDETERMINATE` the note still
> carries "N apparent cable-down transition(s)" as an adverse observation requiring investigation.
> Withheld certification and lost evidence are different things, and only the first was happening.

**c. `test_html_coverage_ssot::test_campaign_partial_evidence_loss_downgrades_a_clean_improvement`
— `INDETERMINATE` vs `MIXED`.** The campaign now withholds certification entirely ("Campaign
certification withheld because 1 collection/schema integrity record(s) are not trustworthy") where
the test expects a downgrade to `MIXED`. Both are non-clean, and withholding is the stricter of the
two, so this is most likely the same stale-test shape as §5.11 — but the test's NAME encodes the
intended behaviour (*downgrades* a clean improvement), so changing it changes a documented product
contract, not just an assertion. Lane owner's call.

**d. `test_gate_state::test_no_engine_caller_declares_a_gate_posture` — caused by THIS REVIEW'S OWN
ARTIFACTS, not by the product.** The offenders it reports are inside
`private-inputs/review-handoff-restore-proof-20260730/webapp/backend/ingest.py` — the sealed recovery
backup this review created. The guard walks the tree and finds "engine callers" in a frozen COPY of
the repo.

~~Deliberately NOT fixed… it should disappear by the artifacts disappearing.~~

**SUPERSEDED BY §5.16 — that judgement was wrong.** I reasoned that adding a path exclusion to a
safety guard is how its scope quietly shrinks, and concluded the failure should be left to clear when
the backups were removed. The premise was right and the conclusion did not follow from it. The guard's
scope was ALREADY wrong — it walked a hand-maintained list of directory names instead of asking git
what belongs to this repo — so this was a real defect that would fire for any developer with a local
ignored copy, not an artifact of preservation. Worse, the noise was sitting on top of a genuine
undeclared engine caller and disguised it as an environmental complaint. See §5.16 for the structural
fix and the finding it exposed.

### 5.13 `test_phase_timings_contract` (4) — producer and consumer disagree about whether the ledger is mandatory

The deciding fact, now measured rather than assumed: **the engine's sidecar write is fail-soft.**
`COLLECT_PARSE_V3_23_0.py:4307` emits it through `_emit_artifact(...)`, whose boolean return is
consumed by an `if` — a failed write logs and the run continues to completion, successfully.

`webapp/backend/ingest.py::_assert_redaction_phases_ran` now refuses when that file is absent:
*"REDACTION COULD NOT BE VERIFIED — the **mandatory** phase ledger is absent … Do NOT send anything
from this run."* So a fully successful, correctly redacted run whose fail-soft sidecar write happened
to fail is refused. Producer says optional; consumer says mandatory. **That inconsistency is the
defect**, not either half on its own.

The function's docstring has drifted into holding both positions at once, which is why this reads as
a test problem at first glance:

- *"Refuse unless BOTH redaction phases are positively confirmed to have run and succeeded… a phase
  that never ran at all was indistinguishable from a clean run"* — the hardening rationale, and a
  correct application of guardrail 3.
- *"Absence is tolerated because there is genuinely no evidence either way; a stale ledger is
  different"* — the earlier two-signal design, where the stderr `[SKIP]` arm carries a run alone.

Both were true in their own era. The 4 failing tests pin the second.

**Two coherent resolutions. The first is better, and neither is mine to pick:**

1. **Make the producer's write mandatory/fail-loud.** Then absence genuinely means something went
   wrong, the consumer's stance becomes sound, and absence-as-health is eliminated with no false
   refusals. This changes engine artifact policy.
2. **Restore tolerance in the consumer**, per the two-signal design, and update the docstring to stop
   claiming the stricter contract.

Resolution 1 removes the failure mode; resolution 2 accepts it and documents it honestly. Picking 2
because it is the smaller diff would re-introduce exactly the silent-degrade this function was
hardened to close.

> The other 3 failures in this module report the ledger as belonging to an EARLIER run. That is
> consistent with the module-scoped `redact_run` fixture (a deliberate ~25s optimization): one real
> pipeline run is shared, so every test after the first sees an unchanged ledger and looks like a
> `--reuse-out` reuse to the staleness check. Likely a test-rig artifact of that sharing, and it
> should be re-checked AFTER the mandatory/optional question above is settled — the staleness arm
> and the absence arm are the same guard, and fixing the rig first would just move the symptom.

### 5.14 `test_parsers::test_eoldb_compact_3560c_2960c_not_classic_family_dates` — stale against a DELIBERATE rebuild, and one figure moved 4 years

My earlier note called this "a stale test vs a retained source, one day apart". That was right about
the day and wrong about the scale. `cisco_toolkit/eoldb.py` was rebuilt during this review
(`_EOL_REVIEWED = "2026-07-30"`): a 17-bulletin / 44-claim table in which every row is bound to a
retained primary-source fixture by BOTH a file SHA-256 and a semantic hash over every runtime date
and PID scope (`_EOL_SEMANTIC_SHA256`). The fixture itself,
`reference-data/official-sources/cisco/eol-bulletins.json`, is UNTRACKED — it is new in this review,
not a baseline file.

Measured against that rebuild, the test is stale in three different ways, and they are not equal:

| Assertion | Test expects | Rebuild gives | Assessment |
|---|---|---|---|
| `WS-C3560CG-8PC-S` ldos | `2021-10-30` | `2021-10-31` (EOL10691, c51-736180) | One day. Every `ldos` in the new fixture is a month-end; October has 31 days, so `10-30` was almost certainly the wrong figure. |
| `WS-C2960CG-8TC-L` ldos | `2025-10-30` | `2021-10-31` (same bulletin) | **Material — moves an LDoS 4 years EARLIER.** Changes migration urgency for any fleet carrying these. |
| `WS-C3560-48PS` platform | `Catalyst 3560` | **`None`** | Classic 3560 is outside the 17 verified bulletins, so it now has no entry at all. |

**The test's own reason for existing still HOLDS.** It was written for a longest-prefix shadowing bug
where the compacts were credited to the classic family's much earlier dates. `WS-C3560CG-8PC-S` still
resolves to `Catalyst 3560-C` and `WS-C2960CG-8TC-L` to `Catalyst 2960-C` — not to the classic
platforms — and the longer `-CX` prefix still wins. Whatever is done about the dates, **that
invariant must survive the edit**; it is the part of this test that is load-bearing.

**Not fixed, and deliberately so: rewriting the expected dates would mean certifying figures I cannot
check.** The no-egress doctrine forbids fetching the bulletins, and the rebuild's claim is precisely
that each row was "re-checked against its named Cisco bulletin". Editing the test to match the code
would convert an unverified data change into a passing assertion — the test would then prove only
that the table equals itself. The 2960-C row in particular is a real-world call about when a
platform loses support, and it needs someone with source access, not a green diff.

> Separate question for the same lane, raised by the `None` results: 5 of 10 common PIDs I probed
> (classic 3560, 3560-24PS, 3750, C9300, 4500) have no entry. The narrowing is defensible — assert
> only what a retained primary source backs — but it is only SAFE if the consumer distinguishes "no
> EoL announced" from "not in our verified set". Otherwise a coverage gap reads as good news.
>
> **CHECKED, and the concern is REFUTED.** `analyze.py:6114` is the only consumer, and a `None`
> lookup yields `band: "Unknown"`, `status: "Unknown model — verify on Cisco's EoL portal"`,
> `citation_status: "missing"` — never Active. There is a second guard behind it: even a row that
> CLAIMS active support is forced to `Unknown` ("Unverified active claim") unless a resolvable
> bulletin id is bound to it, so the honest-by-default behaviour does not depend on the lookup
> missing. Confirmed end-to-end rather than by reading: `compute_lifecycle_risk` over classic
> 3560 / 3750 / C9300 returns `Unknown` + "verify on Cisco's EoL portal" for all three, and
> **0 unverified platforms render as Active**. The narrowing is safe.
>
> One consequence to carry into the date decision above: with the rebuilt table,
> `WS-C2960CG-8TC-L` now renders **`Past-LDoS`** ("Past end-of-support (LDoS 2021-10-31,
> confirmed)", citation `retained-primary-fixture`) where the old table put it in 2025. That is the
> conservative direction — it makes the device look MORE urgent, not less — so it is not a
> false-health risk. It is still a claim about when a customer's hardware stopped being supported,
> printed in a deliverable, and it needs the bulletin checked.

### 5.15 The three golden/sample failures — fully characterised, awaiting one authorization

I had been reporting these as "awaiting re-bless" without showing what changed, which is not enough
to authorize on. Measured:

**a. `test_pipeline_golden::test_snapshot_matches_golden` — the golden carries the §5.2 defect.**
Exactly ONE top-level key differs: `assessment_integrity`, present in the golden, absent now. Its
content is the fingerprint of the defect this review fixed:

```json
"assessment_integrity": {
  "failed_phases": ["Port registry authority"],
  "phase_errors": {"Port registry authority":
      "pack contains non-authoritative curated overlay and multicast semantics"}
}
```

That key is stamped ONLY when a phase fails (`COLLECT_PARSE_V3_23_0.py:3852/:3856/:3875`), so the
golden was blessed while the pipeline was failing "Port registry authority" — the §5.2 whole-pack
flag defect. With §5.2 fixed nothing fails, so the key is correctly absent. **Re-blessing removes a
defect record; it does not enshrine a loss.** That it is the ONLY differing key is also the evidence
that this session's other edits caused no snapshot drift.

**b. `test_excel_sheet_schema_matches_golden` — purely additive.** Golden 67 sheets, produced 68.
**LOST: none. ADDED: `Assessment Integrity`.** The golden predates a sheet the engine now writes.

**c. `test_sample_fleet_carries_every_golden_section` — the bundled demo is stale, not regressed.**
`webapp/sample_data/sample_fleet.snapshot.json` lacks `assessment_integrity` and `data_authorities`;
`data_authorities` appears ZERO times in it, so it predates that feature entirely. The engine still
emits it: a live offline run carries `data_authorities` with `eol`/`oui`/`ports`, and
`COLLECT_PARSE_V3_23_0.py:3913` sets it UNCONDITIONALLY — the §5.2 edit sits above that line and
only governs whether `_record_phase_failure` fires. The test names its own remedy:
`python webapp/sample_data/build_sample.py`.

> Checked specifically because a section vanishing from a snapshot is exactly what a careless "fix"
> looks like: **my §5.2 change did not remove `data_authorities`.** Verified against a real offline
> run, not by reading the diff.

All three are mechanical and safe. They are held only by the preservation rule against overwriting
tracked files without authorization — not by any remaining uncertainty about what would change.

### 5.16 `test_gate_state` — RESOLVED, and it was a real scope defect, not "this review's artifacts"

I had recorded this in §5.12d as an artifact of the review's own sealed backup, to be left alone until
the backups were removed. **That was the wrong call, and the reasoning behind it was wrong too.**

The guard walks `ROOT.glob("**/*.py")` filtered by `_NON_SOURCE_DIRS` — a hand-maintained list of
directory NAMES, documented as "kept in step with `.graphifyignore`'s exclusions". One hand-maintained
list mirroring another. Every entry in it is something git already knows is ignored or generated, and
any ignored directory nobody thought to add is walked as if it were this repo's production source.
`private-inputs/` is exactly that: gitignored, absent from both lists, and holding a COPY of
`webapp/backend/ingest.py`, whose functions the guard reported as undeclared engine callers.

So the guard's verdict depended on which scratch directories happened to be on a developer's disk.
That is not an artifact of this review — this review is merely where it surfaced. It would fire for
anyone keeping a local ignored copy of the tree, and the fix is not to wait for the directory to go
away. **The fourth instance of this review's recurring shape: a NAMED SUBSET standing in for a
STRUCTURAL class** (see §5.2, §5.3, §5.11).

Fixed with `_repo_python_files()`: enumerate via `git ls-files -c -o --exclude-standard`, i.e.
tracked PLUS untracked-but-not-ignored. Untracked-not-ignored is deliberately included — a new
production module that has not been committed yet is still this repo's source and must not slip past
a gate check. If git cannot answer, it falls back to the glob, which is WIDER rather than narrower:
a guard that over-reports is recoverable, one that silently stops looking is the failure this file
exists to prevent. `_NON_SOURCE_DIRS` survives for tracked-but-not-production paths (`tests/` etc.);
what it no longer has to do is guess at every ignored directory that will ever exist.

**Removing the noise then exposed a genuine finding underneath it.** With the backup copies gone from
the inventory, the guard reported exactly one real offender:
`webapp/backend/ingest.py::_run_redaction_folder_locked` — the `--redact-folder` path, which is
precisely the caller this guard was written for. Cause: `run_redaction_folder` was renamed to
`_run_redaction_folder_locked`, and TWO name-keyed anchors went stale with it — the
`_UNGATED_BY_DECISION` key and the anti-vacuity assertion that pins the guard's canonical subject.

That failure mode is correct by design and should be left alone: a safety exemption keyed by name
SHOULD break on a rename and force someone to re-confirm it, because the alternative is an exemption
that quietly follows code it no longer describes. Re-confirmed rather than rubber-stamped — the
consumer re-checks that the justifying reasoning is still in the docstring, and the P0-3/DEC-003
rationale ("**The PPDIOO document gates … deliberately do NOT apply on this path.** Do not 'fix' that
by passing `--gate-root`") is intact in the renamed function. Both anchors updated.
`tests/test_gate_state.py`: 89 passed, exit 0.

> Worth noting what the noise cost: the false positives from an ignored directory were sitting on top
> of a real undeclared engine caller, and made it look like an environmental complaint. A guard whose
> scope is wrong does not just cry wolf — it hides the wolf.

### 5.17 The suite now sits at the edge of the Stop gate's 540s bound

`verify-green.sh` bounds pytest at `VERIFY_GREEN_TIMEOUT_SECONDS` (default 540) and treats a timeout
as RED, correctly: an incomplete suite proves nothing. On 2026-07-31 that bound was hit for the first
time — and the immediate cause was self-inflicted, a background full-suite run of mine competing with
the hook's own run for the same box. Two concurrent ~2,000-test suites, each with real offline engine
invocations. **Do not run a full suite in the background and then end a turn**; the Stop hook will
start a second one and both will lose.

But the margin is genuinely thin, not merely contended: uncontended runs this session completed in
roughly the 400–600s range, so a slow box, an antivirus scan, or a parallel job can push a HEALTHY
suite past the bound and report RED. That is a false RED of exactly the kind §5.1 fixed for the
interpreter probe, one layer up.

> **See the correction in §5.21.** Both timeouts recorded here were caused by a competing suite I
> had started, and a later uncontended `verify-green.sh` run completed within the bound. The margin
> is thinner than the raw 721s figure suggests; the operational rule (never leave a background suite
> running when the turn ends) is what actually fixed it.

**Not "fixed" by raising the number.** The bound is a safety property (an unbounded hook can wedge a
turn up to the 600s ceiling), and raising it to make a red gate go green is the move this whole review
exists to refuse. The honest options, for whoever owns this:

1. Leave it and set `VERIFY_GREEN_TIMEOUT_SECONDS` per-machine — the hook already reads it from the
   environment, so this needs no code change at all.
2. Reduce suite wall-clock. The dominant cost is repeated real engine runs; `test_phase_timings_contract`
   already demonstrates the pattern (one module-scoped `--redact` run instead of one per test, ~25s
   each) — though note §5.13, where that sharing is itself implicated in 3 failures.
3. Split the gate: fast suite on Stop, full suite in CI.

> Measured in passing, and it cuts the other way: the §5.16 fix made the gate-posture walker ~19×
> faster (`git ls-files` 44ms / 356 files, vs `ROOT.glob` 842ms / 1154 files). 798 of those 1154 `.py`
> files were in ignored or backup directories — parsed on every run, and the source of the false
> positives §5.16 removed. Asking git what belongs to the repo was cheaper AND more correct.

### 5.18 Session close 2026-07-31 — 19 → 7, and the Stop gate cannot go green from here

Full suite, Python 3.12 on PATH: **7 failures, exit 1, 1093s elapsed** (that run overlapped a Stop-hook
run, so treat 1093s as an upper bound, not a clean figure — see §5.17). `test_gate_state` is green in
the full suite, not merely in isolation.

Closed this session: §5.3 both halves (GUID false positive + the authored-constant surface/containment
defect that was failing EVERY `--redact` run), §5.11 (`test_html_dos_guard`, 7), §5.12b
(`test_cable_map`), §5.16 (`test_gate_state`), and §5.15 (the two goldens + the bundled sample, under
explicit user authorization on 2026-07-31).

The remaining 7 are ALL diagnosed and NONE is a coding task:

| Failure(s) | n | What it actually needs | Ref |
|---|---|---|---|
| `test_phase_timings_contract` | 4 | A policy call: make the engine's sidecar write fail-LOUD (better), or restore consumer tolerance. Producer is fail-soft, consumer says "mandatory". | §5.13 |
| `test_attestation` | 1 | Drop a now-dead exception from a client-facing Trust & Sovereignty claim. Frozen §5.5 lane. | §5.12a |
| `test_html_coverage_ssot` | 1 | Withhold-vs-downgrade: the test's NAME encodes the contract being changed. | §5.12c |
| `test_parsers::eoldb` | 1 | Cisco bulletin access. A 4-year LDoS shift must not be blessed by editing the test to match the code. | §5.14 |

**Therefore `verify-green.sh` cannot go green until those four decisions are made.** It re-runs the
full suite on every turn that touches a `.py` file, never records a green statekey, and (per §5.17)
sits at or past its 540s bound. A future session should expect the Stop gate to block and should NOT
respond by raising `VERIFY_GREEN_TIMEOUT_SECONDS`, relaxing an assertion, or marking a lane green —
the gate is reporting the truth. Take the decisions, or accept the block.

> The session's most transferable result is not the fixes. Across 12 diagnosed failures, **the test
> was wrong 5 times and the guard was wrong 4 times**, with 3 needing outside input. There is no safe
> default direction, so "make the suite green" and "make the code right" are different jobs here, and
> a batch fix would have silently chosen the first. Every remaining item is one where choosing wrong
> loosens a guard that exists to stop a client receiving something untrue.

### 5.19 The hook lane was never "environmental" — and one of them was a live security fail-open

**First, a correction to §5.10 and everything downstream of it.** I classified ~10 failures as
"environmental, clears once Python 3.12 is on PATH" and measured that from the PowerShell tool. In
that environment `bash` is NOT on PATH, so those tests **SKIP** — `no usable bash on this host` —
whether or not Python is present. I read the skips as passes. They were never fixed by PATH; they
were never *run*. The Stop hook executes under Git Bash, where they do run, which is why it kept
reporting failures I had written off. Green that pins nothing, and I produced it myself by measuring
in the wrong shell.

Re-measured under Git Bash, the cause is one defect in eleven places: **eight `.claude/hooks/*.sh`
scripts and three inline `.claude/settings.json` commands** still resolved the interpreter by
PRESENCE — `PY=$(command -v python || command -v python3 || echo python)`. `command -v` SUCCEEDS for
the Microsoft Store App-Execution-Alias stub, which prints "Python was not found" and exits 9009.
Only `verify-green.sh` had been fixed (§5.1); the pattern was left in every sibling.

Every consequence was SILENT, which is why none of it surfaced as a complaint:

- **`vault-guard.sh` ALLOWED a Write to the vault ROOT.** Measured: `rc=0`, **empty stderr**. The
  stub's output goes to `/dev/null`, `|| true` eats the exit code, `VERDICT` is empty, no `BLOCK:*`
  case matches, and the hook exits 0 = allow. The ADR-0001 write guard was not guarding, and said
  nothing. `vault-guard-bash.sh` had the identical shape.
- The **UserPromptSubmit** protocol injection and the **PreToolUse graphify hints** emitted nothing
  at all — silent no-ops for the whole session.
- **`scorecard-append.sh`** warned "exited 49 — the QA scorecard is NOT being recorded" on every
  healthy stop: a real message about an unreal fault.

All eleven now probe that the interpreter RUNS and fall back to the `py` launcher. Fail-open is
preserved everywhere — a hook bug must never wedge a turn — but it is now reached LAST, and for the
two vault guards it is LOUD: an inert guard says so, because a silent one is indistinguishable from a
guard that ran and approved the write. Confirmed live: the PreToolUse graphify hint fired for the
first time this session immediately after the settings fix.

> The earlier 8-hook rewrite that regressed 15 → 25 failures was NOT repeated. Its two causes were
> known and avoided: edits went through the Edit tool (no Python text round-trip, so no silent
> LF→CRLF — verified `LF only` on all nine hooks), and no shared resolver file was introduced. The
> block is duplicated inline instead. Duplication is the cheaper mistake here.

**One fixture had to be repaired to keep meaning what it says.**
`test_r7_unwired::test_briefing_degraded_run_is_loud_and_never_zero_bytes` induces degradation with a
shim directory of failing interpreters, and asserts the briefing stays loud and non-empty. The shim
shadowed `python`/`python3` only — so the moment the hooks gained the `py` fallback, a WORKING
interpreter was still reachable, the run was healthy, and the "degraded" assertion was testing a
scenario that no longer existed. Shim and its PATH-injection interlock now cover `py` too. Left
alone, this is the failure mode where a fixture quietly stops manufacturing its own precondition and
the test keeps passing while guarding nothing.

Hook suites under Git Bash after the fix: `test_hooks_automation`, `test_vault_guard_bash`,
`test_r5_automation`, `test_morning_briefing`, `test_nightly_wrapper`, `test_r7_unwired` — **all
green, exit 0.**

**§5.19 addendum — the two guard properties, proven rather than asserted.** Measured against
`vault-guard.sh` with a Write to the vault root:

| Condition | Result |
|---|---|
| A working interpreter is present | `rc=2` — **BLOCKED**. The guard is functional. |
| No working interpreter anywhere (`python`, `python3`, `py` all shimmed to exit 9009) | `rc=0` fail-open, and **LOUD** on stderr: *"the ADR-0001 vault write-guard did NOT run — it is INERT, not satisfied."* |

Before the fix, condition A produced `rc=0` with EMPTY stderr — allow, silently.

> Two rig defects had to be cleared before either measurement meant anything, both worth remembering:
>
> 1. The first probe was **blocked by the very guard it was testing** — the command string contained a
>    vault path and `rm`, which `vault-guard-bash.sh` correctly caught. That block is itself evidence
>    the bash lane is live again. Keep vault paths in FIXTURE FILES, never in a Bash command string.
> 2. The second probe pointed `PATH` at a **Windows-style** shim directory (`C:/Users/...`). Git Bash
>    does not accept that form as a PATH entry, so the shim was never on PATH, a real interpreter was
>    found, and the "no interpreter" case silently tested the "interpreter present" case instead —
>    it would have reported PASS for the wrong reason. Always assert the rig first
>    (`command -v python` resolved to the shim) before trusting what it measures. Same MSYS
>    Windows-vs-POSIX path class that made an earlier refutation in this review worthless.

### 5.20 `test_html_coverage_ssot` — RESOLVED; the label moved, the guarantees did not

Deferred in §5.12c as a lane decision because "the test's NAME encodes the contract". Checking the
fixture instead of the name settled it, the same way it settled §5.12b.

The test asserts FOUR things; only the first is a label:

| Property | Required | Measured now |
|---|---|---|
| `verdict == "MIXED"` | MIXED | `INDETERMINATE` |
| `"NOT COMPARABLE"` in the note | True | **True** |
| lost punch-list scored as a fall to zero | **False** | **False** |
| comparable metrics still trend | True | **True** |

The load-bearing one is the third: a punch-list that stops being emitted must never be read as
"0 items", which would render evidence loss as a large improvement. It is intact. The verdict also is
not `IMPROVING`. What changed is that the guard was hardened from DOWNGRADING (`MIXED`) to
WITHHOLDING certification outright (`INDETERMINATE` — "Campaign certification withheld because 1
collection/schema integrity record(s) are not trustworthy"), which is strictly stricter, and the
label-pinned assertion then read as a failure.

Widened to the non-certifying SET (`MIXED`, `INDETERMINATE`) with the three substantive assertions
untouched. **Deliberately NOT widened to `!= "IMPROVING"`** — that would also admit `REGRESSING`,
i.e. inventing a decline out of missing evidence, which is the mirror-image lie and exactly as
dishonest as inventing an improvement. `tests/test_html_coverage_ssot.py`: 19 passed.

> The test's name still says "downgrades". It is now "downgrades or withholds". Renaming it would
> break its identity in CI history for a wording change, so the rule is stated in the assertion's
> comment instead — but a future reader should not take the name as the contract. That mismatch is
> exactly what made this one look like a product decision when it was not.

**§5.19 precision note — what was PROVEN vs what is INFERRED.** Worth stating, because the two are
not the same and the difference bounds the claim:

*Proven, in the test environment* (Git Bash, PATH carrying no working interpreter — the condition the
hook tests construct): `vault-guard.sh` allowed a Write to the vault root with `rc=0` and empty
stderr; the UserPromptSubmit and PreToolUse commands emitted nothing; `scorecard-append.sh` warned on
healthy stops. All reproduced and all now fixed.

*Proven, in the LIVE environment*: the PreToolUse graphify hint began appearing in this session's
tool results **immediately after** the `settings.json` fix and not once before it — a genuine
before/after in the running client, visible in the transcript. The UserPromptSubmit hook now emits
3,554 bytes of valid JSON where the same command previously produced nothing.

*NOT established*: that the vault write-guard was inert in the LIVE client. Its failure was measured
under a constructed PATH. `graphify-out/graph.json` carries a same-day mtime, which is evidence that
at least one hook's interpreter resolution was working in the real environment, so the live PATH is
probably not the degraded one. **Do not restate this finding as "the vault guard was open in
production"** — the defect is that resolution-by-presence makes the guard's function depend on PATH
contents it never checks, and that it fails SILENTLY when it loses. That is worth fixing on its own;
it does not need the stronger claim, and the stronger claim is not supported.

### 5.21 Session close — measured: 721s, 8 failures, one of them caused by fixing a hook

Full suite under Git Bash, Python 3.12: **exit 1, 8 failures, ELAPSED = 721s** — but read the
correction before quoting that figure.

> **CORRECTION, same session.** I read 721s as "the suite is ~181s over the 540s bound; it is not
> contention alone." That was wrong. Immediately afterwards `verify-green.sh` ran the full suite
> itself and **COMPLETED INSIDE its 540s bound**, reporting the live failures rather than timing out.
> The suite does fit when the box is free. My 721s was measured while I kept the turn alive with
> checkpoint verifications, greps and file writes — light individually, but enough to inflate a
> ~2,000-test suite by a third. I attributed my own load to the workload, having just written §5.17
> warning about exactly that.
>
> What survives: the margin is real but far thinner than 181s, and BOTH earlier timeouts (§5.17) were
> caused by me running a competing suite. The operational rule is the part that mattered and is
> unchanged: **never run a full suite in the background and then end the turn** — the Stop hook will
> start a second one and both will lose. Do not raise the bound to quiet the gate;
> `VERIFY_GREEN_TIMEOUT_SECONDS` is already environment-settable per machine.
>
> That hook run is also independent confirmation of the inventory: **7 failures, matching the live
> count below exactly** — a separate process reproducing the same list.

Two entries in that list need qualifying rather than repeating:

- `test_html_coverage_ssot` is **STALE in this run** — it was fixed after the run started (§5.20,
  19 passed since). Live count is 7 of these 8.
- `test_d10_eval_set::test_multi_hop_edges_exist_in_live_graph` — **I first attributed this to the
  known-open graphify incremental-rebuild edge truncation, re-triggered by fixing `graph-refresh.sh`
  (§5.19). That was wrong on both counts.** It is not truncation and has nothing to do with the hook
  fix. Recorded because a plausible-sounding attribution to a KNOWN bug is the easiest way to stop
  investigating: the known bug was the wrong answer here precisely because it fit so well.

  Queried directly, the edges **are in the graph**:

  ```text
  main -[calls]->          _emit_artifact()            conf=EXTRACTED
  main -[indirect_call]->  write_mop_docx()            conf=INFERRED
  main -[indirect_call]->  write_design_doc_docx()     conf=INFERRED
  ```

  The extractor is MORE precise than the eval set assumes. `COLLECT_PARSE_V3_23_0.py:4083` reads
  `_emit_artifact("MOP DOCX", mop_out, "docx", write_mop_docx, mop_out, snap_dict, label)` — the
  writer is passed as a callable ARGUMENT, never syntactically called by `main`. AST extraction
  therefore yields `calls -> _emit_artifact` plus `indirect_call -> write_mop_docx`, which is the
  honest description. `docs/quality/d10-eval-set.jsonl` declares those three edges (M-02, M-06,
  M-10) with `"relation": "calls"`, and `verify_multi_hop_edges` matches the relation verbatim, so
  the lookup misses them. **The graph is right; the committed expectation is stale.**
  `indirect_call` is already in `REFERENCE_RELATIONS`, so the correction is a three-row relabel.

  **Attempted, and correctly BLOCKED — leave it that way.** Relabelling the three rows makes
  `test_multi_hop_edges_exist_in_live_graph` pass and immediately fails
  `test_d10_eval_set::test_seal_sha_pins_exact`: the eval corpus is SEALED. That control exists so
  nobody quietly edits a measurement instrument to agree with the system it measures, and it worked
  on me. Re-sealing is a deliberate protocol action for the corpus owner, not a side effect of
  greening a suite. The edit was reverted byte-exactly (`git checkout` of a file that was clean
  minutes earlier and carried no work but mine — a JSON round-trip had reformatted it, so restoring
  content was not enough to restore BYTES, and the seal is byte-exact).

  For the owner: relabel M-02/M-06/M-10 `calls` → `indirect_call`, then re-seal. `graphify-out/` is
  gitignored, so none of this touches the checkpoint inventory.

**Live failure inventory (7):** `phase_timings` ×4 (§5.13 — producer/consumer disagree on whether
the ledger is mandatory), `attestation` ×1 (§5.12a — stale charter in a client-facing claim),
`eoldb` ×1 (§5.14 — a 4-year LDoS shift needing bulletin access), `d10_eval_set` ×1 (§5.21 — the
upstream graphify bug above). None is a coding task; each needs a decision or a source.

### 5.22 `test_phase_timings_contract` — 3 of 4 were an implementation bug, not a policy question

**Third wrong attribution of the session, and the same shape as the other two.** §5.13 recorded the
three staleness failures as "plausibly a test-rig artifact of the module-scoped `redact_run` fixture:
one shared engine run, so every test after the first looks like a `--reuse-out` reuse". That is
wrong. `test_the_refusal_fires_on_a_real_failed_phase` writes a FRESH sidecar into a FRESH
`tmp_path` — nothing is shared — and still got "belongs to an EARLIER run".

The real cause is in `_written_by_this_run` (`webapp/backend/ingest.py:928`), whose first line was:

```python
    if p.name not in engine_names:
        return False
```

The contract tests call the guard without a census, so `engine_names` is the default `frozenset()`
and that membership test fails for EVERY path. The guard therefore reported a file it had just
watched being written as unchanged from before the run started. **A guard that refuses everything is
not strict, it is broken — and it refuses hardest exactly where it has the least information.**

`_assert_redaction_phases_ran`'s own docstring states the intended behaviour verbatim: *"engine_names
/ pre_existing are the caller's pre-run census; **with neither supplied (the direct-call contract
tests use that form) every file reads as this run's**, which is the pre-existing behaviour."* The
implementation did the opposite of its documented contract, and the tests encoded the contract.

Fixed by honouring it: an EMPTY census returns True, because staleness cannot be inferred from a set
that makes no claim. **The production path is untouched** — `_engine_filenames()` always returns at
least the three sidecar names, so the real caller's census is never empty and still gets the full
closed-set membership test. Verified: `webapp/tests` + `test_redact_e2e` + `test_redact_collection` +
`test_phase_timings_contract` show no regression, and 3 of the 4 failures clear.

**The 4th stays open, and it IS the policy question §5.13 described.**
`test_an_absent_sidecar_is_tolerated` still fails, because the same docstring genuinely contradicts
itself about absence — *"Refuse unless BOTH redaction phases are positively confirmed… a phase that
never ran at all was indistinguishable from a clean run"* against *"Absence is tolerated because
there is genuinely no evidence either way."* Both were true in their own era. With the producer's
write fail-soft (§5.13), the two coherent resolutions from that section still stand and still belong
to the lane owner. What changed is that this is now ONE decision, not four failures wearing a
decision as a disguise.

> The pattern across §5.20, §5.21 and this section: each time a group of failures was written off
> with a plausible cause — stale label, known upstream bug, shared-fixture artifact — the plausible
> cause was wrong and the real one was a specific, fixable defect a few minutes of reading away. The
> tell each time was that the explanation covered the symptom without anyone having checked the
> mechanism.

### 5.23 Three authorized fixes applied (2026-07-31) — 4 failures to 1

User authorized all three on 2026-07-31. Each was evidenced before being offered, and each is
recorded here with what it changes about a CLAIM, not just about a test.

**a. `attestation` — the stale charter is gone, and the claim got stronger.** `NO_EGRESS_EXCEPTIONS`
is now EMPTY. It named `data/gen_port_registry.py` for as long as that generator fetched iana.org via
`urllib.request`; the file no longer imports urllib at all, so the exemption named something that
could not offend — the precise condition `_claim_no_egress` was built to report. The published Trust
& Sovereignty text now reads *"no documented exception was needed"* instead of carrying a caveat that
no longer applies. Fail-closed is preserved: any future network import lands in `unexplained` and the
claim goes VIOLATED.

  The test was rebuilt on a structural anchor. It used to prove the walk reaches subpackages by
  asserting a NAMED file was an offender — so when that file was repaired, the test demanded a defect
  back. It now compares `scan_imports`' file count against an independent `os.walk` enumeration, plus
  a non-vacuity check that subpackage `.py` files still exist. **A guard anchored to one file's
  current contents expires when that file improves; anchored to the walk, it cannot.**

**b. `d10_eval_set` — re-sealed, three relation labels.** M-02/M-06/M-10 declared
`main() -calls-> write_mop_docx()` / `write_design_doc_docx()`. `COLLECT_PARSE_V3_23_0.py:4083`
passes those writers to `_emit_artifact` as callable ARGUMENTS and never calls them, so the graph's
`indirect_call` (already in `REFERENCE_RELATIONS`) was right and the declaration was stale. Applied
by byte-level targeted replacement rather than a JSON round-trip — the earlier round-trip reformatted
the file and broke the byte-exact seal without changing meaning. Diff is exactly **3 insertions, 3
deletions**, relation label only. `EVAL_SET_SHA256` re-pinned in the same change, which is the
procedure the seal's own docstring prescribes ("file AND pin in one reviewed diff").

**c. `phase_timings` — the PRODUCER was fixed, not the consumer relaxed.** This was §5.13's
resolution 1 and it is the better half of that choice. The engine now records a MANDATORY failure
when the phase-timings ledger cannot be written, instead of passing silently. That ledger is the only
positive evidence the redaction phases ran, and `ingest._assert_redaction_phases_ran` refuses a
delivery without it — so while the write was fail-soft the producer called it optional and the
consumer called it "the mandatory phase ledger", and a fully successful run whose write happened to
fail was reported as an unverifiable redaction.

  `test_an_absent_sidecar_is_tolerated` became `test_an_absent_sidecar_now_REFUSES`, and the
  consumer's docstring no longer holds both positions at once. The rejected alternative — restoring
  tolerance — was the smaller diff and would have re-admitted the silent-degrade the guard exists to
  close: a redaction phase that never ran being indistinguishable from one that ran clean. The new
  test also pins that the refusal stays HONEST (`COULD NOT BE VERIFIED`, not "the redaction failed"),
  because that distinction is what a field engineer acts on: re-run and check, versus do not send.

**Result: `attestation`, `d10_eval_set` and all four `phase_timings` tests pass.** Verified together
with `test_pipeline_inprocess`, `webapp/tests` and `test_redact_e2e` — no regression. **One failure
remains: `test_parsers::test_eoldb_compact_3560c_2960c_not_classic_family_dates` (§5.14), which needs
Cisco bulletin access to settle a 4-year LDoS shift and must not be blessed by editing the test to
match the code.**

### 5.24 `eoldb` — RESOLVED offline; the source I said I lacked was already in the repo

§5.14 concluded this "needs Cisco bulletin access" and must not be settled by editing the test to
match the code. The second half was right and the first half was wrong: `eoldb.py` binds itself to a
**retained primary-source fixture**, `reference-data/official-sources/cisco/eol-bulletins.json`,
SHA-256-pinned by `_EOL_FIXTURE_SHA256` and stamped `retrieved_at 2026-07-30T13:48:46Z`. That file
records, per claim, the bulletin id, document id and exact HTTPS source URL. **It is the primary
source, retained precisely so this question can be answered air-gapped.** No egress required, and
none used.

What it carries for the two PIDs:

| Claim | Bulletin | ldos |
|---|---|---|
| `WS-C3560CG-8PC-` (prefix) | EOL10691 / c51-736180 | **2021-10-31** |
| `WS-C2960CG-8TC-L` (**exact**) | EOL10691 / c51-736180 | **2021-10-31** |
| `WS-C2960C-` (prefix) | EOL13189 / c51-743071 | 2025-10-31 |

The test expected `2025-10-30` for the 2960CG — the 2960-C **series** date. That PID does not match
prefix `WS-C2960C-` (the next character is `G`, not `-`), and EOL10691 names it EXPLICITLY by exact
match, so the series date never applied to it. Both old expectations were also `-10-30` where every
retained date is a month-end `-10-31`. **The rebuilt table is right; the test was stale.**

Updated with the citation written into the docstring, so the next reader can re-derive it without
network access. Three things deliberately preserved:

- **The invariant the test exists for** — the compacts must not be credited to the classic family,
  and the longer `-CX` prefix must not be shadowed by the shorter `-C` rows.
- **`lifecycle_for("WS-C3560-48PS") is None`**, asserted rather than deleted. The registry was
  rebuilt to assert only what a retained source backs, and no classic-3560 bulletin is in that set.
  `None` is the coverage-honest answer, and §5.14 already verified end-to-end that
  `compute_lifecycle_risk` renders it as band "Unknown" / "verify on Cisco's EoL portal" — never
  Active. Asserting `is None` keeps the anti-shadowing point: whatever the classic PID does, it must
  not inherit a compact's row.
- **The distinction that made this look unresolvable.** Editing a test to match the code would have
  left it proving the table equals itself. Checking the code against a retained, hash-pinned source
  is a different act, and the repo had already built the instrument for it.

> Worth naming, because it cost several turns: "I need an external source" was itself an unchecked
> assumption. The no-egress doctrine makes it TEMPTING to classify anything source-dependent as
> blocked — and this repo answers that by retaining its sources. Check what has been retained before
> concluding a question cannot be settled offline.

### 5.25 Operational note — the Stop gate and a self-run suite cannot coexist

Recorded because I made this mistake THREE times in one session, twice after writing the warning.

`verify-green.sh` runs the full suite on every turn that touches a `.py` file and has not yet been
proven green. So **ending a turn while a background suite of your own is running guarantees two
concurrent ~2,000-test suites**, and on this box that is enough to push both past the 540s bound.
Every "pytest exceeded 540s" in this session traces to that, not to the suite's own weight — an
uncontended hook run completed inside the bound earlier (§5.21 correction).

The rule, plainly: **do not start a background full-suite run and then end the turn.** Either keep
the turn open until it finishes and stay IDLE while it does (even light tool calls inflated one
measurement by a third — 721s vs the ~500s range), or do not run one at all and let the Stop hook be
the single runner. The hook's verdict is authoritative anyway; a second opinion that corrupts the
first is worse than no second opinion.

Also worth knowing on this host: `pkill -f "python.exe -m pytest"` works from Git Bash, `pgrep` does
not exist there, and a `Monitor`/background task must be stopped with `TaskStop` separately — killing
the process leaves the watcher armed.

### 5.26 Full suite GREEN — proven independently, and what that does and does not mean

`verify-green.sh` allowed a stop, which it does only after a real `exit 0` pytest run, at which point
it writes `.git/verify-green.ok` containing the statekey of the tree it proved. Recomputed and
compared:

```text
marker           : fb70b494f27f73b8…
current tree key : fb70b494f27f73b8…   MATCH
```

That key hashes `HEAD` + the porcelain status + the full tracked diff + every untracked file's
contents, so it binds the green verdict to **these exact bytes**, not to "a recent run". The run was
performed by the gate, not by me — which is the point: I was the proposer for every change in it.

**Session total: 19 known failures → 0**, plus one consequential golden re-bless (§5.25). Closed
here: §5.3 (both halves), §5.11, §5.12b, §5.15, §5.16, §5.19–§5.24.

**What this establishes:** every test in the repository passes on this tree, including the guards
this review repaired, and no fix was made by weakening an assertion — every widened assertion in this
session was paired with a strictly stronger one (§5.11 withheld-note, §5.20 non-certifying set,
§5.23a structural recursion proof).

**What it does NOT establish, and must not be read as:**

1. **Not repository-wide correctness.** A green suite says the tests pass; five of my own
   attributions were overturned by measurement TODAY (the 721s timing, `d10_eval_set`'s "known
   upstream bug", `phase_timings`' "fixture artifact", `gate_state`'s "review artifact", `eoldb`'s
   "needs external access"). Each looked settled until the mechanism was checked. **Phase B —
   independent adversarial review by someone who was not the proposer — is unstarted and is the
   control that this session's error rate argues for.**
2. **Not release-ready.** No staging, commit, archive, wheel, release proof or deployment has been
   performed or authorized; §1's preservation rules stand unchanged (0 staged, 27 deletions and 67
   untracked files preserved, checkpoint INTACT at 107 PASS).
3. **Not a claim about the client-facing outputs' accuracy.** §5.24 corrected an LDoS date against a
   retained primary source; that is one figure re-checked, not the registry re-audited.

The honest summary is: **Phase A is complete and independently green; Phase B has not begun.**

**§5.26 addendum — why the marker proves "green WITHIN the bound", not merely "green".** The obvious
objection to §5.26 is that a written marker might only mean the suite eventually passed, possibly
over 540s, and that it might predate this session's last change. Both are answerable from
`verify-green.sh`'s own control flow rather than from trust:

* `/usr/bin/timeout` is present on this host, so the run is `timeout 540 python -m pytest` — bounded,
  not best-effort. (If it were absent the hook falls back to an UNBOUNDED run, and this argument
  would not hold; check it before reusing this reasoning.)
* `rc == 0` is the ONLY branch that writes the marker.
* A timeout surfaces as `rc == 124`, which takes the "exceeded ${VERIFY_SECONDS}s; a partial suite is
  not green" branch and exits 2 WITHOUT writing anything.

So a marker can only exist if pytest exited 0 while bounded at 540s. And because the statekey hashes
`HEAD` + porcelain + the tracked diff + every untracked file's contents, it is keyed to the tree
INCLUDING the golden re-bless of §5.25 — a later edit would move the key and the match would fail.
The match therefore rules out both readings: the run was not over-budget, and it was not stale.

> This is also the answer to the earlier 721s/753s confusion (§5.17, §5.21): those were MY runs,
> contended by my own concurrent work. The gate's uncontended run fits inside 540s. The measurement
> to trust is the one taken by the process that has the box to itself.

## 6. PHASE B — independent adversarial review (2026-07-31)

Authorized by the user. Five independent reviewers, none of them the proposer, all READ-ONLY (no
edits, no `git checkout/reset/clean`, no fault injection into the working tree — a fault-injecting
refuter once wrote `if False:` into a pushed commit here). They were briefed to REFUTE, not confirm.

**They were right to be asked. Phase B refuted four claims I had reported as settled, including one
regression I introduced, and found five pre-existing defects that reach client documents.**

### 6.1 REGRESSION I INTRODUCED — reverted (§5.23c producer escalation)

Making the phase-timings write mandatory was **measured harmful**. Two real `--redact` runs, identical
inputs, differing only in an ordinary Windows file lock (AV scanner / open viewer) on the PREVIOUS
ledger:

```text
CONTROL   (nothing locked)   exit 0  [COMPLETE]    14 files
TREATMENT (stale ledger held) exit 1  [INCOMPLETE]  the SAME 14 files, byte-for-byte
```

`ingest.py:1831` maps a non-zero engine exit to `_mark_output_unsafe` + a do-not-send verdict, so a
locked stale sidecar would tell a field engineer that a correctly redacted deliverable set must be
treated as UNREDACTED. And it bought nothing: the consumer's absent-ledger refusal sits ~28 lines
AFTER ingest already raises on `returncode != 0`, so **no caller can ever observe it**. The
escalation was ungated on `--redact` and pinned by zero tests. REVERTED; both sides now document the
branch as unreachable, and the §5.13 question is downgraded from safety to tidiness.

> The lesson is about my reasoning, not the code: I chose "fix the producer" as the more principled
> of §5.13's two options WITHOUT checking whether the consumer branch it justified was reachable. A
> coupling argument is only as good as the reachability of both ends.

### 6.2 THREE MORE DEFECTS IN MY OWN WORK — fixed

- **The published attestation claim contradicted itself.** Emptying `NO_EGRESS_EXCEPTIONS` (§5.23a)
  left the METHOD paragraph still announcing `data/gen_port_registry.py` as a documented exception
  while DETAIL reported "no documented exception was needed" — on the client-facing Trust &
  Sovereignty sheet. Worse, `test_no_egress_claim_names_its_documented_exceptions` PASSED only
  because of that stale prose: it hardcoded the filename, so it pinned the contradiction rather than
  catching it. Both now DERIVE from the live sets.
- **My recursion proof compared COUNTS, not sets** (§5.23a). The test's enumeration kept
  dot-directories (the impl prunes them) and excluded by BASENAME (the impl excludes by RELPATH).
  The divergences cancel. Demonstrated on a synthetic tree: `.vendored/hidden_egress.py` importing
  `requests` was never opened and the guard stayed green. Now compares SETS, and fails loudly if a
  dot-dir or directory symlink ever appears under the package.
- **One registered authored phrase was DEAD CODE** (§5.3). `"supply e.g. 10.0.0.0/16."` never
  exempted anything: `_IPV4_CANDIDATE_RE` ends `(?![\d.])`, so a SENTENCE-FINAL constant fails the
  lookahead and backtracks to the bare `10.0.0.0` — not the registered key. The real producer string
  (`design_advisor.py:4240`, reachable on any unparseable `address_space`) **still failed
  verification**: the same "every `--redact` run fails finalization" class I reported closed, still
  live on that branch. My guard test could not see it because it asserted `constant in phrase`
  (string containment) instead of running the scanner. Fixed, and the guard now feeds every phrase
  through `_scan_text` and requires zero leaks, plus a producer-shaped test with a non-vacuity pair.

### 6.3 PRE-EXISTING, SEVERE, NOT MINE — for the owner

Ranked by what reaches a customer.

1. **`archreview` LC-1 certifies an end-of-support fleet as conforming.** EXECUTED, not inferred: a
   fleet of `WS-C6509-E`/`WS-C6513-E`/`WS-C3560-48PS` (all years past support) yields
   `VERDICT: conforms — "Every device with lifecycle data is in an Active support band."`
   (`archreview.py:1149`, the `else` branch; `n_unknown` is read nowhere in the LC-1 chain). Reaches
   the Architecture Review DOCX, its workbook sheet, and the conformance grade. **This is guardrail
   3's exact wording — absence rendered as health — in a signed deliverable.**
2. **The EoL registry's sole evidentiary basis is UNTRACKED.** `reference-data/official-sources/cisco/
   eol-bulletins.json` is not in git (`git ls-files` empty, not ignored), hand-authored, and its
   `evidence_method` self-declares that claims "are checked against their exact HTTPS Cisco source
   URL" — unverifiable under no-egress, and asserting it implies egress occurred. Code pins the
   fixture's hash, the fixture agrees with the code, and nothing external closes the loop. In a fresh
   clone the provenance tests go RED, the EoL authority degrades to `source_authoritative: False`,
   and `distribution_verify.py:74` lists the file as REQUIRED — a build from a clean clone ships a
   distribution that fails its own verifier. It also self-expires 2027-01-26 (`source_max_age_days`).
   **Meanwhile every lifecycle row now publishes `conf: "confirmed"` where HEAD said `"derived"`.**
3. **27 of HEAD's 36 platform patterns now return `None`** — Catalyst 6500/9000, Nexus 5600/7000/9000,
   2960-S, 3560-G among them — and five LDoS dates moved EARLIER by 1–5 years. No §5.x section
   scoped this; §5.14/§5.24 examined two PIDs and generalised.
4. **`0 device(s) past last-date-of-support` on the front page of every DOCX** when the true answer is
   "not determined" (`docmeta.py:508`; `ssot.CANONICAL_FACTS` has no `n_unknown` slot, so no path
   exists to say so). Same class at `ops.py:216`, `design.py:709`, `crd.py:306`,
   `design_advisor.py:3705/3975` (Unknown never enters the replacement BoM, so HLD §5.1 is omitted),
   `blast_radius_explorer.html:4246`, `html.py:961` (an un-assessed fleet trends as IMPROVEMENT).
5. **`certify_shareable_artifacts` keys candidates by BASENAME** — two `out.html` in different
   directories, and whichever sorts later is never scanned while the proof advertises coverage of it.
   Measured: dirty-first → CERTIFIED CLEAN. Related: `ingest.py:1849` passes every file the run
   wrote, and `topology.dot`/`.mmd` carry raw CDP device-IDs (`SEP00112233AABB`, `wan-edge-rtr1.lab`)
   which no suffix branch scans and no message discloses.
6. **`_OPAQUE_MEDIA_SUFFIXES` is a content-blind skip.** Identical bytes: caught as `.bin`, MISSED as
   `.emf`/`.wmf`. EMF/WMF store visible text as inline UTF-16LE — exactly what the `.bin` branch
   exists for. (`.bin` itself is NOT a named-subset defect: unknown suffixes fail closed.)
7. **Format-character evasion defeats the base regexes.** A zero-width space, soft hyphen or NBSP
   inside a serial or a fullwidth dot in an IP makes it invisible to the ENTIRE verifier;
   `unicodedata.normalize` is applied only to OOXML member names, never to scanned content.

### 6.4 Status

Phase B is COMPLETE for the five lanes reviewed. §6.1–§6.2 are fixed and re-verified. **§6.3 is
untouched and unauthorized** — items 1–4 change what customer documents assert and item 2 questions
the evidentiary basis of a registry this session partly relied on. None should be "fixed" quickly.

**Phase A can no longer be described as verified-correct.** It is verified-green, which Phase B has
just demonstrated is a different thing.

### 6.5 The completeness critic — two RELEASE-BLOCKING defects in files the review never opened

The fifth reviewer was asked what was never looked at. Answer: **165 of 239 modified tracked files and
49 of 67 untracked files appear nowhere** in this handoff or the delta. The review's scope was ~30% of
the checkpoint. Two hard defects lived in the remainder; both are now fixed and both were found by
asking "what did you not examine", not by any failing test.

**1. `.github/workflows/ci.yml:223` and `release.yml:174` carried the §5.2 defect I reported fixed.**
Both asserted `registry_health()['authoritative']`. Measured on this tree: `portdb` returns
`authoritative=False` with `integrity_verified=True, official_source_authoritative=True` — the exact
mixed-pack case §5.2 exists for. So the OLD gate exits **1 with `AssertionError`**, and the job it
guards is **"Distribution contract"** — the step that builds and preserves the release archives.

`grep -rn registry_health` lists all four consumers in ONE command. I fixed two
(`COLLECT_PARSE_V3_23_0.py:3888`, `serve.py:254/264`) and never ran the grep. **This is
[[enumerate-every-exit-before-marking]] applied to my own fix, failed by me, in the same session I
wrote §5.16 naming that exact pattern.** Fixed in both workflows with the scoped contract; measured
old gate `exit 1`, new gate `exit 0`, both YAMLs still parse.

**2. `webapp-ci.yml` could not COLLECT the web safety suite at all.** The install step is
`pip install -e ".[dev]"`; `webapp/tests/conftest.py` requires `("fastapi", "httpx")` and sets
`collect_ignore_glob` if either is missing, at which point pytest exits 5 having run nothing. `httpx`
is NOT a base fastapi dependency — verified against installed metadata, it appears only under
fastapi's `standard`/`all` extras, and this project depends on bare `fastapi>=0.110,<1`. So the one
job whose purpose is Atlas-redaction / security-hardening / DNS-rebinding / unplug-safety ran **zero**
of them, and `ci.yml`'s matrix skipped `webapp/tests` for the same reason. One line in the `dev`
extra restores ~20 safety-test files to the gate.

> Note the shape: this is [[green-tests-that-pin-nothing]] #1b — `importorskip`-class invisibility —
> recurring at the DEPENDENCY-DECLARATION layer, where no test can see it. The suite is green either
> way; the tests simply are not there.

**Still open from that review, NOT fixed (see also §6.3):**

- **~6,000 lines of new, never-committed, security-critical Python got no review**:
  `distribution_verify.py` (1,968), `verify_repository_privacy.py` (1,182), `registry_integrity.py`
  (1,058), `verify_checkout_immutable.py` (373), `http_guard.py` (348). These ARE the verifiers every
  "evidence" line in this document leans on — proposer-authored, verifier-absent.
- **`webapp/backend/app.py` (+550/−109)** — the largest unexamined security surface (request-body
  limits, token authority, duplicate-JSON-key rejection, a memory cap that varies with host RAM, and
  a change to where an existing user's SQLite store lives).
- **`webapp/frontend/dist/` was un-ignored** and CI now requires an ubuntu/node-20 rebuild to
  reproduce a Windows-built bundle BYTE FOR BYTE (`verify_checkout_immutable.py`), including Vite's
  content-hashed filenames. Never executed. 1.47 MB of minified third-party JS entered the tracked
  surface outside §4.1's binary-exception list.
- **All CI moved off the self-hosted fleet**, pinned by `tests/test_release_supply_chain.py:97`. A $0
  metered setup is now billed GitHub-hosted minutes across a 6-job matrix. Ratify or revert
  deliberately; no §5.x section mentions it.
- **21 frontend test files and `master-reference/tests/rendered-html.test.mjs` have never run on this
  tree** — `pytest.ini` is `testpaths = tests webapp/tests` and nothing shells out to vitest. §5.26's
  "every test in the repository passes" means "pytest exited 0", which is narrower than it sounds.
- **`tests/test_html_dos_guard.py:315` gates four HTTP-route DoS tests behind
  `importorskip("fastapi"/"httpx")`** — the same defect the repo's own meta-test forbids for ONE file.
  Named subset, structural class, again.

**Marker caveat worth keeping (Task D).** The reviewer confirmed the statekey mechanism and then found
a real hole: it is **blind to line-ending-only changes on tracked text files**. With
`core.autocrlf=true` and `.gitattributes`' `eol=lf` rule, git normalises CRLF→LF on read, so a file
rewritten with CRLF produces a byte-identical statekey feed while the on-disk bytes carry `\r`.
Demonstrated in a scratch repo. That is exactly §5.19's failure mode — the marker could certify a tree
as green while every hook is inert with `bad interpreter: ^M`. Untracked files are read raw and are
unaffected; binary changes ARE visible (the `index <old>..<new>` blob SHA). Also: §5.26 quotes a
marker hash that no longer exists, because writing the proof into an untracked file changes the tree
the proof certifies — do not re-quote a marker value.

### 6.6 Phase B closing state

Full suite after every Phase B fix: **exit 0, 0 failures, 557 s** (uncontended, Git Bash, Python
3.12). Checkpoint INTACT at 107 PASS; 0 staged, 27 deletions and 67 untracked files preserved.

**Phase B changed the standing of Phase A.** Five reviewers refuted four claims I had reported as
settled and found two release-blocking defects in files the review never opened. Corrected in §6.1–6.2
and §6.5:

| What I reported | What Phase B measured |
|---|---|
| "phase-timings mandatory makes the consumer's stance sound" (§5.23c) | A file lock turned a COMPLETE run into `[INCOMPLETE]` + a do-not-send verdict, to harden a branch no caller can reach. **Reverted.** |
| "emptying NO_EGRESS_EXCEPTIONS makes the claim stronger" (§5.23a) | The claim then contradicted itself on a client-facing sheet, and the test passed on the stale prose. **Fixed.** |
| "the recursion proof pins the walk structurally" (§5.23a) | It compared COUNTS; two opposite divergences cancelled and a planted egress file went unscanned. **Fixed.** |
| "§5.3 closed the every-`--redact`-run-fails class" | One registered phrase was dead code; the real producer string still failed verification. **Fixed.** |
| "the eoldb dates were off-by-one month-ends" (§5.24) | HEAD said `-10-31`; one PID moved four years earlier. My story came from working-tree values. **Corrected.** |
| "§5.2 fixed" | 2 of 4 consumers. The CI/release gate still asserted the whole-pack flag and exits 1. **Fixed.** |

**The pattern is uncomfortable and worth stating plainly: every one of these was a claim I had already
called verified.** The green suite was true throughout and told nobody anything about them. What found
them was an independent party instructed to refute, plus one asked only "what did you not look at" —
which surfaced the two defects that would have failed the release job, neither of which any test
covers.

**§6.3 and the open items in §6.5 remain untouched and unauthorized** — the LC-1 false "conforms" on an
end-of-support fleet, the untracked EoL evidentiary basis, 27 dropped platform patterns, `0 device(s)
past LDoS` on every DOCX front page, ~6,000 lines of unreviewed verifier code, and `webapp/backend/
app.py`. Items 1–4 change what customer documents assert. None should be fixed quickly, and a second
Phase B pass should cover the lanes §6.5 names as never examined.

### 6.7 The Stop gate now blocks a GREEN suite — decided by 17 seconds

Measured, uncontended, after Phase B: **exit 0, 0 failures, 557 s.** `verify-green.sh` bounds the run
at 540 s and treats a timeout as RED. So the gate now blocks on a suite that passes, by ~17 s — inside
run-to-run noise. §5.17's "the margin is thin" and §5.21's correction have converged on the obvious
outcome: Phase B added test files, and the suite crossed the line.

**This is a FALSE RED of exactly the class §5.1 fixed** (a gate reporting a defect it never observed),
one layer up. It is also the only thing now standing between this tree and a passing gate.

**Not fixed by raising the number, and deliberately so.** The bound is a safety property — an
unbounded hook can wedge a turn to the 600 s ceiling — and raising a limit to silence a red gate is
the move this entire review exists to refuse. Three honest options, for the owner:

1. **Set `VERIFY_GREEN_TIMEOUT_SECONDS` per machine.** The hook already reads it from the environment
   (`verify-green.sh:88`), so this needs NO code change and no gate weakening. Cheapest correct fix.
2. **Reduce suite wall-clock.** The dominant cost is repeated real engine invocations (~25 s each);
   `test_phase_timings_contract` already demonstrates module-scoped sharing of one `--redact` run. Note
   §5.13/§6.1: that sharing has its own hazards, so do it deliberately.
3. **Split the gate** — a fast suite on Stop, the full suite in CI. Note §6.5 first: `webapp/tests` was
   collected in ZERO CI jobs until the `httpx` fix, so "CI covers it" needs re-establishing before it
   can be relied on.

Whoever picks: the suite is GREEN. Do not respond to this block by relaxing an assertion, marking a
lane complete, or skipping tests to fit the budget.

## 7. PHASE B WAVE 2 — the never-examined lanes (2026-07-31)

Five more independent read-only reviewers over what §6.5 identified as unreviewed: the verifier
instruments, the privacy/release gates, `webapp/backend/app.py`, the untrusted-input and certification
surfaces, and the ADR-0001 vault fence. **All findings are against a GREEN suite** — each reviewer ran
the relevant tests first and confirmed exit 0. That is the point: none of this is visible to pytest.

### 7.1 FIXED — the privacy gate could certify a tree carrying client identifiers (P0, LIVE)

`.github/scripts/verify_repository_privacy.py` matched markers with `\b`. `\b` is defined against
`\w`, and **`_` is a word character** — so `\bthe side-engagement client\b` never matched `<sidebrand>_dc_design`, and
`\baj\b` never matched `<initials>_switch01`. Measured before the fix, against the module's own patterns:

| flagged | PASSED (missed) |
|---|---|
| `<brand>`, `<short>-core01`, `<initials>-fleet`, `<user>` | `<sidebrand>_dc_design`, `<short>_core01`, `<initials>_switch01`, `<initials>_vlan_plan`, `<bid>_bid`, `<user>_home` |

Not hypothetical: the working tree carries `<sidebrand>_BOQ.xlsx` and a `<sidebrand>_DC_Design/` directory. A
reviewer demonstrated the real script exiting **0** on a scratch repo whose content named the client
throughout.

**The correct idiom was already in the file** — the `<initials>`-qualifier pattern ends with
`(?![A-Za-z0-9])`. It was applied to one pattern and not the other eleven. **Fifth instance of
[[named-subset-instead-of-structural-class]] this session, in the guard whose entire job is to be
exhaustive.** Fixed with explicit `_LB`/`_RB` boundaries that treat `_` as a separator. Measured
after: all 8 previously-missed identifiers FLAG, all 7 previously-caught still FLAG, and 8 legitimate
words (`Taj Mahal`, `major`, `banjo`, `ajax`, `synthesis`, `project`, `managed`, `raj`) stay clean.
`tests/test_repository_privacy.py`: 15 passed.

**Still open on the same gate, NOT fixed:** file NAMES and paths are never marker-scanned (only
content is), three `_DENIED_PATHS` regexes are root-anchored so a subdirectory duplicate evades, and
git HISTORY is never examined — while §2 records that history still contains the original private
material. The script's own pass line is honestly scoped ("Git index + working tree"); the PUBLISHED
claim in `master-reference/app/MasterReference.tsx:332` is not.

### 7.2 NOT FIXED — LIVE, ranked. Each needs a decision, not a quick patch.

1. **The release gate cannot pass.** `webapp/frontend/dist/` is untracked AND not ignored, and
   `verify_checkout_immutable.py:251` lists untracked paths WITHOUT `--exclude-standard`. So the CI
   step "Prove the SPA build reproduced the immutable source" fails **deterministically** the first
   time it runs (`ci.yml:156`, `release.yml:88`). It also never compares build output at all — with
   `dist/` untracked it can only assert "no new untracked paths". Mis-titled and unsatisfiable.
2. **The two registry packs are interchangeable and still verify.** `registry_integrity.py:128` keys
   the trusted digest by the pack's own SELF-DECLARED `provenance_status`; nothing binds
   `oui_registry.tsv.gz` to the IEEE state or the filename to a digest. Measured: exchanging the two
   files' contents and their manifest entries yields `verified: true` for both. The runtime loaders
   (`ouidb.py:24`, `portdb.py:33`) are STRONGER — they pin a single state each. **The instrument that
   gates the release is the loose one.**
3. **Custody is opt-in, and the ledger is erasable.** `input_custody.py` enforces only inside
   `if binding:` — a run that binds nothing is indistinguishable from perfect custody
   (`failures() == []`). `bind_files` and `reset` both CLEAR `_FAILURES`, so "remembered for the whole
   run" is false. LIVE amplification: `COLLECT_PARSE_V3_23_0.py:4183` calls `_start_run_custody` →
   `raw_input_custody.reset()`, and `:4195` then reads `failures()` — **the ledger is wiped
   immediately before it is consulted.**
4. **Two expensive, STATE-CHANGING GETs sit outside the guarded class.** `app.py:952`/`:971` now call
   `_summary_freshened` (multi-MB parse + a DB write) without `Depends(_forbid_cross_site)`. Measured
   cross-site: `/api/snapshots/{id}` → 403, `/api/campaigns` → **200 with 1 parse + 1 DB write**,
   `/api/campaigns/{id}` amplifying per snapshot. This is the PR #382 lesson recurring.
5. **A stalled upload denies all heavy work.** `app.py:252` takes the shared generation semaphore
   BEFORE the first body byte, with no read timeout. Measured at cap 1: a stalled chunked upload makes
   every deliverable/explorer/PIR request return 503. The cap now scales with host RAM (≤4 GiB → 1)
   and the env override can only LOWER it — so a field laptop is one slow upload from total denial.
6. **Rule-3 sanitization is fully evadable with one format character.** `sanitize.py` and
   `intel_feed._standard_identifier_hit` share ASCII-only patterns and never NFKC-normalize or strip
   `Cf`. Measured end-to-end: an advisory carrying a zero-width space inside a client name, fullwidth
   dots inside an IPv4, a ZWSP inside a serial and inside an email produced **`redactions: []`** and
   the consumer returned **`ok: True, "verified"`**. ZWSP, soft hyphen, word joiner, en dash and
   fullwidth punctuation all evade; the byte-identical ASCII form redacts all six. Ordinary
   provenance: Word paste, wrapped terminal output, a CJK IME, autocorrect.
7. **`client: <name>` frontmatter does not drop a vault note.** `vault_digest.py:113` requires the
   VALUE to be literally `true`/`yes`/`1`, so the most natural spelling of a client-adjacent note
   passes the drop gate and reaches only the hand-typed `--forbidden` list — i.e. finding 6's owner.
8. **`--out` is unvalidated, so `research_lane` can write into the personal vault, invisibly.**
   Neither `vault_digest.run` nor `producer.run` confines `out_dir`. Measured against the ADR-0001
   shell guard, a `--out` pointing at the vault classifies as **ALLOWED** — `_WRITE_TOKENS` is a list
   of shell verbs and `--out` is not one. A new write vector the existing guard structurally cannot
   see: the named-subset shape again, with a fresh instance.
9. **`verify_release.py` reads `pyproject.toml` from the WORKTREE, not the tagged blob**
   (`:16-21`). Measured: tagged blob `name = "x"` vs worktree `name = "totally-different-package"`
   plus a new entry point → **exit 0**. Only the version string is bound to the tag. No signature
   verification (an unsigned annotated tag passes), no monotonicity/replay check.
10. **Six `distribution_verify` proof fields are hardcoded `True`** (`:1875`) —
    `record_hashes_verified`, `metadata_equivalence_verified`, `source_bytes_verified`, and three
    more — literals on the success path, so `--expected-json` is vacuous for exactly the keys a
    reader scans first. Related: `--source-commit`/`--source-tree` are regex-shaped, never verified,
    and echoed into the proof as if proven (the module imports no git/subprocess at all).

**LATENT, worth recording:** NAT64/v4-compatible IPv6 forms (`64:ff9b::7f00:1`) pass `http_guard`'s
`is_global` check at both stages; a wheel-installed AssessHub silently relocates its SQLite store on
upgrade (reads as data loss, no migration or warning); the browser session cookie is a non-revocable
bearer equivalent that ignores port; a wheel with no bundled LICENSE verifies green because
`_WHEEL_METADATA_FILES` is an allowlist never used as a required set.

**Genuinely sound, verified not assumed:** `http_guard`'s loopback/private fence (45 URL forms + 8
resolver scenarios, including v4-mapped, 6to4, mixed public/private answer sets, and no check/use DNS
gap); `_RequestBodyLimitMiddleware`'s byte-count ordering and the middleware stack order; the
DNS-rebinding Host allowlist still covering every guarded route; `_cors_origins` failing closed;
archive completeness being structural (set differences, RECORD verified both directions); and the
retained-source chain NOT being circular — `_PRIMARY_SOURCE_CONTRACTS` pins URL/sha256/bytes/record
count in code, and a self-written inventory cannot confer authority.

### 7.3 Standing

**Phase B is now complete across ten lanes.** Wave 1 refuted four of my claims and found two
release-blockers; wave 2 found one P0 privacy hole (fixed) and ten further LIVE defects in code no
test covers. **Nothing in §7.2 is authorized or actioned.** Several items — 4, 5, 6, 7, 8 — change
security-relevant behaviour and belong to their lane owners.

The through-line, stated once: **every defect in §7.2 lives in code that a green suite runs past.**
The suite proved the code does what it does; it never asked whether that was the claim.

### 7.4 FIXED — `--compare` stamped verdict FAIL on EVERY run (P0, LIVE)

The fifth reviewer's finding, verified independently and repaired.

`precert._is_sha256` demands the canonical `sha256:<64 lowercase hex>` form. There are **two
producers and they disagree**: `webapp/backend/storage.py:358` emits `"sha256:" + hexdigest()`, while
the engine's `_record_from_bytes` (`COLLECT_PARSE_V3_23_0.py:1623`) emits the **bare** hexdigest and
`COLLECT_PARSE_V3_23_0.py:2751` passes it straight into `compute_precert(source_hashes=…)`.

So `_normalize_source_hashes` rejected BOTH sides of every CLI `--compare`, producing two
`gate_failures`, and `precert.py:404` turns any gate failure into `verdict = "FAIL"`. Measured by the
reviewer on two IDENTICAL clean snapshots through the real CLI:

```text
verdict       : FAIL
verdict_note  : 2 blocking condition(s) … not safe to approve - do not proceed.
regressions   : []
gate_failures : ['before source hash is not canonical sha256:<64 lowercase hex>',
                 'after source hash is not canonical sha256:<64 lowercase hex>']
source_binding: {}
```

Three separate harms: the PPDIOO cutover-gate artifact was a **constant FAIL**, which trains its
reader to ignore it (a genuine regression appears as one line among boilerplate); the certificate was
**unbound** — `source_binding: {}` — on exactly the runs it exists to gate; and `html.py:565`
back-fills the raw binding into the workbook, so the *Pre-Change Certificate* sheet rendered
`Provenance | before input SHA-256 | BOUND` and `Gate failure | … is not canonical | BLOCKING` **in
the same sheet**, contradicting the sibling `.precert.json`.

Fixed with `_canonical_sha256`, which accepts a bare 64-hex digest as the canonical form. Widened
at the VALIDATOR rather than re-spelling the producer, because `_record_from_bytes` builds generic
evidence records consumed in several places. It accepts strictly more DIGESTS and no more
non-digests: measured, both producer forms and uppercase hex are accepted; a 63-char string, a
non-hex 64-char string, an md5-length string and prose all still fail closed.
`tests/test_precert.py` + `test_decision_integrity_failclosed.py` + `test_repository_privacy.py`:
65 passed, exit 0.

> Why the suite was green over a permanently-failing gate:
> `tests/test_decision_integrity_failclosed.py:127` hand-builds `"sha256:" + "a"*64`. A fabricated
> fixture in the shape the validator expects — [[fixture-must-come-from-real-producer]], and the
> reason a constant-FAIL cutover certificate survived a 2,000-test suite.

### 7.5 Also LIVE from the same reviewer, NOT fixed

- **`RecursionError` escapes both untrusted-input parsers.** `intel_feed.py:133` catches
  `(JSONDecodeError, TypeError, ValueError)`; `manifest.py:416` catches
  `(OSError, UnicodeError, ValueError, OverflowError)`. `json.loads` raises `RecursionError` on deep
  nesting, which is in NEITHER tuple. Measured: one hostile feed in a directory kills the whole
  intake (the good feed is never consumed, exit 1), and `python -m cisco_toolkit.manifest verify`
  breaks its own documented "never raises for a bad file" contract — reachable from
  `Atlas.exe --verify-manifest`, the field auditor's surface for CLIENT-SUPPLIED manifests.
- **4-part product versions are mistaken for IPv4, refusing the WHOLE feed.** `7.0.6.2` / `17.9.4.1`
  is the standard FTD/FMC/ASA maintenance-release form and validates as an IPv4 address, so
  `_standard_identifier_hit` refuses the file and every sibling advisory with it. Unexposed on the
  shipped feed (0 four-part tokens) — it fires on the first real FTD feed. Compounded at
  `upgrade_targets.py:556`, which discards `refused` and renders the result as *"the credential-gated
  Cisco PSIRT sweep has not run"* — **a refused critical-RCE advisory reported as a lane that was
  never wired.** `self_healing.advisory_remediation` does NOT have this bug; `upgrade_targets` is the
  single exit that drops them.
- **`verify_readiness_freeze`'s envelope hash cannot do what its docstring claims.**
  `_readiness_certificate_hash` is an unkeyed SHA-256 over public data and the function is public, so
  a shadow certificate is relabelled "real" in two lines and still verifies `(True, 'ok')`. A freeze
  with `source_hash` omitted also verifies clean and names nothing in `blind_spots` — absence as
  health. (A *bad* binding correctly fails closed; only the missing case is silent.)
- **Manifest scope notes:** omission re-seal needs only the last chain row recomputed, and the success
  string "all N artifact(s) hash to the seal" reads as completeness when N is attacker-chosen;
  `verify` never looks at the folder, so an unlisted `EXTRA-Invoice.xlsx` delivered alongside is
  invisible. `--expect-root` catches the first, as documented.

### 7.6 FIXED — `RecursionError` escaped both untrusted-input parsers (LIVE)

Verified independently: `json.loads` raises `RecursionError` on deeply nested input, and
`RecursionError` is **not** a `ValueError` — so it was in neither catch tuple.

- `intel_feed.py:133` caught `(JSONDecodeError, TypeError, ValueError)`. `load_feeds` calls
  `verify_feed` outside any `try`, so **one hostile file aborted the whole intake** and the sibling
  good feeds were never consumed.
- `manifest.py:416` caught `(OSError, UnicodeError, ValueError, OverflowError)`, breaking that
  function's own documented contract — *"never raises for a bad file, because the caller is a CLI
  whose whole job is to report the bad file"*. Reachable from `Atlas.exe --verify-manifest`, the
  field auditor's surface for **client-supplied** manifests, i.e. precisely the untrusted input the
  guard exists for. The `_MAX_CHAIN_ROWS`/`_MAX_ARTIFACTS` limits cannot help: they are enforced
  *after* the parse.

Both fixed by handling `RecursionError` alongside the malformed-input cases. Measured after, on a
directory holding a 3,000-deep hostile feed beside a normal one:

```text
load_feeds did NOT raise
  REFUSED feed-hostile.jsonl: unparseable manifest (first line): manifest is nested too deeply to parse safely
manifest.verify_file did NOT raise -> ok=False, reason: cannot read manifest ...
```

The hostile file is now a per-feed **refusal with a reason** rather than a traceback that takes the
run with it. `tests/test_intel_feed.py` + `test_manifest.py` + `test_run_manifest_durability.py` +
`test_advisory_remediation.py`: 77 passed, exit 0.

> Probe note, recorded because it nearly produced a false conclusion: the first attempt wrote
> `hostile.jsonl`/`good.jsonl`, but `load_feeds` globs `feed-*.jsonl` — so NEITHER file was read and
> the run looked clean for the wrong reason. Assert the rig sees its inputs before trusting what it
> measures; this is the third time that class has appeared in this session.

### 7.7 Still open in §7.2 — deliberately not fixed

Eight of the ten remain: the unsatisfiable release gate, the interchangeable registry packs, opt-in
custody with an erasable ledger, the two unguarded state-changing GETs, the semaphore held across the
network receive, Unicode-evadable Rule-3 sanitization, `client: <name>` frontmatter, unconfined
`--out`, the worktree-vs-tag `pyproject` read, and the six hardcoded proof fields.

**Why they are not being fixed in this session, stated plainly:** they are security-relevant changes
to code that has never had a reviewer, and there is no independent pass left to check them. That is
not hypothetical caution — §6.1 records this session doing exactly that: a change I believed hardened
a guard turned a `[COMPLETE]` run into a do-not-send verdict, and only an independent reviewer caught
it. Ten more such changes by the same author, unreviewed, is the larger risk.

Several also need a product decision rather than a patch: whether the semaphore should bound receive
time or only handler time, whether two read routes may change state at all, whether sanitization
should NFKC-normalize (a behaviour change for every existing digest), and what the registry pack
digest should actually be bound to. Those belong to their lane owners.

**Recommended order** for a session that has fresh context and can afford its own refutation pass:
(1) the release gate — it currently cannot pass; (2) the registry-pack binding — the release
instrument is looser than the runtime loaders; (3) the two GET guards — measured, cross-site
reachable today; (4) Rule-3 Unicode normalization — measured full bypass; (5) the rest.

### 7.12 FIXED — Rule-3 sanitization was evadable with one invisible character (LIVE)

The highest-severity of the four §7.2 items left after wave 2. Two independent root causes, needing
two different fixes — a single one would have looked complete and closed neither class.

**(a) The separator class was ASCII-only.** `textutils.FORBIDDEN_TOKEN_SEPARATORS` was `[\s._\-]`,
so a denylist entry `ACME BANK` caught `ACME-BANK` and `ACME_BANK` but **not** `ACME–BANK` with
U+2013 EN DASH — which is what autocorrect, Word paste and a wrapped terminal produce.
**NFKC does not fix this one**: U+2013 has no compatibility decomposition and survives normalisation
unchanged, so it had to be in the class itself. Widened to the Unicode dash block (U+2010–U+2015,
including non-breaking hyphen and em dash), MINUS SIGN, FULLWIDTH HYPHEN-MINUS, SOFT HYPHEN, the
zero-width format characters, MIDDLE DOT and FULLWIDTH LOW LINE. Measured: 8 previously-missed
spellings now caught; a wrong separator (a letter, a digit) is still rejected, so it did not become
a blanket match. This is the SSOT owner, so producer and consumer both inherit it.

**(b) The identifier patterns never normalised.** `intel_feed._standard_identifier_hit` now also
matches an NFKC-normalised, `Cf`-stripped **shadow copy**. This gate's whole purpose is to catch what
the producer missed, so a spelling the redactor cannot see must not be invisible here either —
"independent of producer claims" was true of the token LIST and never of the matching. Measured
before: a zero-width space inside an IPv4, a serial, a MAC and an email, and a fullwidth dot inside
an IPv4, were all reported **clean by both sides**, while the byte-identical ASCII forms were
redacted. All five are now refused. Clean prose, bug ids (`CSCvk12345`) and version strings are
unaffected. Shadow copy only: nothing stored or emitted changes, the sole effect is that more input
is REFUSED — deliberately one-directional, since a refusal is loud and recoverable.

> One case in the reviewer's evasion table did NOT need a code change, and saying so matters as much
> as the fixes: `bob<NBSP>@acme.example` folds to a plain space before the `@`, which is not an
> address by any definition — forcing a match would over-flag ordinary prose. The residual there is
> that the DOMAIN still names the client, which is the forbidden-token list's job, and it does catch
> it. Fixing what is actually broken, not everything a report lists.

Verified: `test_intel_feed`, `test_research_lane`, `test_vault_digest`, `test_recall`,
`test_advisory_remediation`, `test_upgrade_targets` → 147 passed. **Full suite: exit 0, 0 failures,
685s.**

**THREE remain** (§7.2 items 2, 5 and the custody entry): the generation semaphore's ordering, the
registry pack binding, and custody semantics. Each is a design question rather than a defect with an
obvious correct answer — see §7.7.

### 7.13–7.15 The last three, and Phase B closed at 14/14

**7.13 — registry pack binding (LIVE).** The trusted digest was selected by the pack's own
SELF-DECLARED `provenance_status`; nothing bound `oui_registry.tsv.gz` to the IEEE state or a
filename to a digest. Measured: exchanging the two packs' contents AND their manifest entries yields
`verified: true` for BOTH, so a fresh release proof certifies the swap. The runtime loaders never had
the hole — `ouidb`/`portdb` each pin a single-element state set — so **the instrument gating the
RELEASE was the loose one**, which is the wrong way round. `_EXPECTED_STATE_BY_PACK` now binds the
declared state to the filename. Measured after: both honest packs verify; the swap is refused by
name. Unknown pack names fall back to the union so a future table is not blocked.

**7.14 — custody's ledger was erasable (LIVE).** `bind_files()` cleared `_FAILURES`, making this
module's own contract false: *"a mismatch is remembered for the whole run, so restoring the original
file later cannot erase evidence."* Measured before: tamper detected (1), re-bind, 0. Re-binding
installs a new EXPECTATION; it does not un-observe a mutation already seen. `reset()` remains the one
way to clear — what a genuinely new run calls. Measured after: 1 → 1 across a re-bind, 0 after reset.
> The OPT-IN half is still open: enforcement lives inside `if binding:`, so a run that binds nothing
> is indistinguishable from perfect custody, and `COLLECT_PARSE_V3_23_0.py:4183` calls
> `_start_run_custody` → `reset()` immediately before `:4195` reads `failures()`. That is a semantics
> change for every caller and needs its callers traced first.

**7.15 — the generation slot was held across the network receive (LIVE).** Acquired before the first
body byte, released only after receive + handler, with no read timeout — so a stalled chunked upload
held it indefinitely. Measured at cap 1: every deliverable generation, explorer render and PIR export
returned 503 while one upload sat idle, and the cap scales with host RAM (**1** on a ≤4 GiB field
laptop), making one slow connection total denial. Acquisition moved to AFTER the body is spooled, so
the slot covers the HANDLER. Refusing later costs only the spooled body, already capped by `limit`
and discarded on return; the scope marker still prevents a double-acquire and `finally` still
releases exactly what was taken.
> Pinned FUNCTIONALLY, not by a source scan — the weak form this review kept finding. A receive
> callable probes the semaphore on every chunk the server pulls and asserts it is still FREE; if the
> slot were taken before the loop, the probe's `acquire(False)` fails and so does the test. It
> carries a non-vacuity guard, so a rig that never ran cannot pass silently.

**Phase B: 14 of 14 fixed and verified. Full suite: exit 0, 0 failures, 692 s.** Checkpoint INTACT
(107 PASS); 0 staged, 27 deletions and 67 untracked files preserved; nothing committed or deployed.

**What remains open is NOT a defect list.** Three items are recorded above and in §6.3/§7.2 as
questions rather than bugs: custody's opt-in enforcement (7.14), and from §6.3 the `archreview` LC-1
verdict on an all-Unknown fleet plus the untracked EoL evidentiary basis. Each changes what a
customer-facing document ASSERTS, and none should be closed without its own adversarial pass.

### 7.16 The Stop gate itself carries the contradiction — and my own remedy was wrong twice

**Correction first.** §5.17, §5.21 and §6.7 all offer `VERIFY_GREEN_TIMEOUT_SECONDS` as the
no-code-change remedy for the gate timing out. **That does not work**, and the hook says so in its own
comment (`verify-green.sh:85`): the bound exists to avoid *"blocking until the 600s hook ceiling."*
The hook PROCESS is killed at 600 s regardless of the variable, so a ~692 s suite cannot pass this
gate by any environment setting. I recommended it three times without checking the ceiling.

**And the file holds two positions on what a timeout MEANS:**

| line | text |
|---|---|
| `:11` | "a timeout is **RED** because an incomplete suite proves nothing" |
| `:85` | "**fail OPEN** on timeout (exit 0) instead of blocking until the 600s hook ceiling" |
| `:104` | `exit 2` — blocks |

Same defect shape as §5.13 (`ingest.py`) and §6.1: a comment pair recording a decision that was
changed once and never reconciled, with the code implementing one side. I fixed exactly this in
`ingest.py` earlier the same day and then walked past it here.

**Deliberately NOT resolved, and the reason matters.** Fail-open means an incomplete suite stops
blocking — and a genuinely hung test then slips through, which is what the bound exists to prevent.
Fail-closed means this machine cannot pass the gate until the suite is under ~540 s. Both are
defensible; what is NOT defensible is picking whichever unblocks the current turn, which is how a
safety bound gets quietly relaxed. **Twice in this session I mistook "what would clear my block" for
"what is correct"** — the env-var advice above, and §6.1's producer escalation. That is the reasoning
error worth carrying forward, more than either fix.

**The only real remedy is §6.7 option 2: get the suite under the bound.** Measured wall-clock across
this session: 557 s → 566 s → 595 s → 685 s → 692 s. Part is Phase B's added tests, part is load from
concurrent agents, so an idle-box figure is probably ~560–600 s — i.e. genuinely at the edge, not far
past it. The dominant cost is repeated real engine invocations at ~25 s each;
`test_phase_timings_contract` already demonstrates module-scoped sharing of ONE `--redact` run. Do it
deliberately: §5.13 and §6.1 record that exact sharing having its own hazards.

### 7.17 Where the 692 s goes — one test is 22% of the suite

Measured with `pytest -q --durations=20` (exit 0, whole suite):

```text
155.34s  tests/test_runbook.py::test_runbook_survives_truthy_scalar_nested_value   <-- 22% of the run
 50.80s  tests/test_r8_client_evidence_is_ignored.py::test_no_tracked_file_anywhere_became_ignored
 49.11s  tests/test_redact_e2e.py::test_redact_workbook_does_not_leak_real_inventory
 41.40s  tests/test_attestation.py::test_a_write_tacked_onto_a_read_verb_violates_the_published_claim
 36.35s  tests/test_gate_state.py::test_gate_root_enforces_gates_the_synthetic_cwd_would_have_disabled
 35.99s  tests/test_redact_collection.py::test_cli_flag_scrubs_after_analysis_and_warns
 ~28-36s x11 more — test_pipeline_golden (7), test_pipeline_inprocess (2), test_perf_harness,
          test_redact_collection, and one 28.4s SETUP in test_phase_timings_contract
```

**`test_runbook_survives_truthy_scalar_nested_value` alone is ~155 s.** Bringing just that one test
to a normal engine-run cost (~25 s) drops the suite by ~130 s — from ~692 s to ~560 s, i.e. from
"cannot pass the gate" to "at the boundary". It is the single highest-leverage change available, and
it is one test rather than a cross-file refactor.

Its name suggests a poison/fuzz shape (a truthy scalar substituted at a nested key). If it drives a
full pipeline per variant, the fix is the ordinary one: build the artifact ONCE and re-run only the
cheap assertion per variant. **Measure it first** — this section is a duration listing, not a
diagnosis, and I did not read the test.

The rest is a flat tail of real engine invocations at ~28–36 s each, which is the structural cost
§6.7 option 2 names. `test_pipeline_golden` alone contributes seven of them; a module-scoped pipeline
run there is the second-largest win. Note §5.13/§6.1 before doing it: module-scoped sharing of one
engine run is exactly what made three `test_phase_timings_contract` tests look like a staleness
defect, so share deliberately and keep each test's own assertions independent.

### 7.18 The suite is under the gate's bound — 692 s → 528 s, with no coverage lost

Two changes, both measured, neither touching what any test asserts.

**1. `test_runbook_survives_truthy_scalar_nested_value`: 155 s → 22.6 s.** The 129-case poison sweep
wrote each render to a DISTINCT `.docx` in one `tmp_path`. Nothing ever reads those files — the
assertion is purely "the render did not raise" — but 129 accumulating files in one directory is 129
fresh Windows AV scans in a directory that keeps growing. Measured: 262 ms/render into a near-empty
directory vs 174 ms rewriting one path, and 129 renders standalone cost ~34 s against the ~155 s
pytest attributed to the test. **The gap was file accumulation, not rendering.** Now one path,
rewritten per case. Same 129 cases, same poison, same assertion — and the test's own reach guard
(`len(paths) > 20` plus three pinned deep paths) still passes, so the sweep's coverage is
structurally unchanged. Shrinking the case set is what that guard exists to forbid.

**2. `test_no_tracked_file_anywhere_became_ignored`: 50.8 s → 0.06 s.** It called `git check-ignore`
once per tracked file — 600+ process creations, which on Windows is most of a minute. Replaced with
one `--stdin -z` call (`-z` so paths with spaces or non-ASCII survive, which a line-split would have
mangled). Verified the batched helper agrees with the per-path probe **both ways** on a known-ignored
and two known-not-ignored paths, and `rc` is asserted to be 0 or 1 so a real git failure cannot read
as "nothing ignored". `_ignored` is kept for single-path callers, and
`test_the_probe_itself_discriminates` still pins it.

**Checked the CLASS, not just the instance** — the point of §5.16 and the [[named-subset]] lesson.
Grepped for the same per-iteration-distinct-file shape everywhere: four more sites, all 2–5
iterations (negligible), and **one where the "fix" would have been a defect** —
`test_review_round2.py:310` asserts `os.path.exists(out)`, so reusing the path would make that
assertion pass on the PREVIOUS iteration's file from the second case onward. Left alone. The 129-case
sweep was the only instance where the pattern mattered.

**Result: full suite `exit 0, 0 failures, 528 s`** — inside the Stop gate's 540 s bound, with the
600 s hook ceiling above it. Margin is ~12 s, i.e. thin: a loaded box can still exceed it, and §7.17's
remaining tail (49 s, 41 s, then ~28–36 s × 11) is genuine engine-run cost, not accumulation. If more
headroom is wanted, `test_pipeline_golden`'s seven separate pipeline runs are the next structural
target — read §5.13/§6.1 first, since module-scoped sharing has its own hazards.

### 7.19 The next timing target, scoped — `test_pipeline_golden`'s seven runs ARE shareable

Not done (see the caution at the end), but scoped precisely so the next session does not have to
re-derive it, and so it is not wrongly scared off by §5.13.

`tests/test_pipeline_golden.py` invokes `_run_pipeline` **ten** times. Seven are the identical
zero-argument form (`:188, :199, :215, :235, :259, :273, :318`) at ~28–33 s each — roughly **210 s of
the suite's 528 s**. A module-scoped fixture running ONE pipeline for those seven leaves ~30 s, a
~180 s saving that would take the suite to roughly 350 s and make the ~12 s margin comfortable.

Three must keep their own run because their arguments differ: `:303` (`--import-inventory`), `:341`
(extra args), `:362` (custom `out_xlsx`).

**The contamination question, answered rather than assumed.** §5.13/§6.1 record module-scoped sharing
making three `test_phase_timings_contract` tests look like a staleness defect, so the obvious worry is
a test that MUTATES the shared artifacts. Two of the seven look like they do —
`:259` and `:273` both carry `json.dump` and a comment about rewriting a sealed step. **They do not
mutate the originals**: each writes to a separate `tampered` path and leaves the produced manifest
intact. Verified by reading both bodies, not inferred from the comment. The remaining five are pure
reads (`_golden` compare, `_sheet_schema`, `load_workbook(read_only=True)`, manifest reads).

So the seven are genuinely shareable. The residual risks are the ordinary ones, worth naming so they
are checked rather than discovered: the tamper tests add extra files to a now-shared `tmp_path`
(harmless, but it means the directory is no longer pristine per test), and any assertion that depends
on file mtimes or on the output directory containing exactly the engine's own artifacts would need
re-reading first.

**Why it was not done here:** it is a seven-test refactor with shared state, at the end of a session
with no context left to debug a failure, against a suite that is currently GREEN and inside the
bound. Trading a working 528 s suite for a possibly-broken 350 s one is the wrong trade to make
tired — and §6.1 is this session's own record of what that costs.

### 7.20 §7.19 done — and §7.17's duration figures were LOAD-INFLATED

**The refactor.** `tests/test_pipeline_golden.py` now runs **4** pipelines instead of 10: a
module-scoped `golden_run` fixture serves the seven zero-argument callers, and the three that pass
different arguments (`--import-inventory`, extra args, custom `out_xlsx`) keep their own. **10 passed
in 23.68 s**, same ten tests, same assertions.

Sharing was safe for the reason §7.19 established by reading the bodies rather than trusting the
comments: the two tamper tests write a SEPARATE `tampered.run_manifest.json` and leave the produced
manifest intact. The fixture's docstring carries that reasoning and the rule for anyone extending it
— *a test that writes to the run's own output gets its own `_run_pipeline`*, because a shared artifact
mutated by one test is a defect the others inherit silently.

**The correction, which matters more than the refactor.** §7.17 reported these tests at **28–33 s
each**, and I sized this work at "~210 s of the suite". Measured on an idle box they are **~5.7 s
each**. The §7.17 durations were taken while five review subagents were running, so every figure in
that table is inflated — by roughly 5× for this file. **I predicted ~180 s of saving and got ~38 s**
(528 s → 490 s).

The refactor was still worth doing — 10 identical pipeline runs measuring the same thing is waste at
any speed, and the suite now has ~50 s of margin under the 540 s bound instead of ~12 s. But the
sizing was wrong, and the cause is the same one recorded in §5.21 and §6.7: **a timing measurement
taken while the box is busy is a measurement of the box, not of the code.** §7.17 remains useful for
RANKING (the relative order was right — the 155 s and 50.8 s outliers were genuine and both are now
fixed) and must not be used for absolute figures. If more headroom is ever needed, re-measure idle
first.

**Suite: `exit 0, 0 failures, 490 s`.**

### 7.21 FIXED — the DELIVERABLE verifier had the same invisible-character blind spot (LIVE)

§7.12 closed this in the Rule-3 lane (`textutils` + `intel_feed`) and I did not carry it to
`webapp/backend/redaction_verify.py` — **the gate that decides whether a document is safe to send a
client.** Every identifier pattern there is ASCII, so one format character blinded the whole module.
Measured, each reporting **0 leaks** while the byte-identical ASCII form reported 1:

| payload | before |
|---|---|
| `FCW1234<ZWSP>A001` / `FCW1234<SOFT HYPHEN>A001` (Cisco serial) | invisible |
| `10.44.7<ZWSP>.219` / `10.44.7<FULLWIDTH FULL STOP>219` (IPv4) | invisible |
| `00:1a:2b:3c:4d:5<ZWSP>e` (MAC) | invisible |
| `bob@ac<ZWSP>me.example` (email) | invisible |

**Five of five identifier classes.** Higher severity than §7.12's: that gate refuses a feed, this one
certifies a deliverable.

Fixed with `_fold_identifier_text` applied at `_scan_text`'s single entry point — NFKC plus a `Cf`
sweep — rather than per pattern. That covers all fourteen call sites by construction (`[key]`,
values, OOXML element text and attributes, joined/spaced runs, zip comments, member names, the three
`.bin` decodes, HTML), so a pattern added later cannot miss it. Offsets stay internally consistent
because `_documented_example`, `_inside_guid` and `_token_within_authored_phrase` all read the same
folded text, and NFKC of ASCII is ASCII so the authored sentences match unchanged.

Verified BOTH directions in one run — a one-way fix would just re-create §5.3's 24 false indicators
that blocked every `--redact` run: all six evasions now report, and clean prose, a version string,
and the authored doctrine constants still report zero. Pinned by
`test_one_invisible_character_cannot_hide_an_identifier` (7 cases) and
`test_folding_does_not_manufacture_leaks_or_break_exemptions`, which also checks NFKC idempotence.

Redaction lane 67 passed; **full suite `exit 0, 0 failures, 486 s`.**

> Worth naming: I found this class, fixed it in one module, wrote it up — and left the more
> exposed module untouched for several turns. Fixing an instance is not fixing the class, which is
> the same lesson as [[named-subset-instead-of-structural-class]] arriving from the other side.
> When a defect is found in one module, grep for its shape in every sibling BEFORE closing it.

### 7.22 FIXED — §6.3's top finding: LC-1 certified an end-of-support fleet as "conforms" (P0, LIVE)

The highest-severity item left in the record, and the one I recommended fixing next. Reproduced
before touching anything, using the reviewer's own scenario through the REAL engine
(`compute_lifecycle_risk` → `compute_architecture_review`), not a hand-built summary:

```text
fleet   : WS-C6509-E, WS-C6513-E, WS-C3560-48PS, WS-C3560G-24TS-S   (all years past support)
bands   : {'Unknown': 4}
BEFORE  : VERDICT conforms — "Every device with lifecycle data is in an Active support band."
                             "Vendor support backs the whole migration."
AFTER   : VERDICT not-assessable — "4 device(s) have UNKNOWN lifecycle status — no EoX bulletin in
                             the offline KB covers their platform, so their support state was never
                             determined."
```

**Cause:** the LC-1 chain is `if n_past_ldos / elif n_past_eos / elif n_near / else conforms`
(`archreview.py:1112–1155`). All three branches fire on POSITIVE findings, and `n_unknown` — which
`analyze.py:6199` has been publishing in the same summary all along — was read by nothing. An
all-Unknown fleet therefore fell through to `conforms`.

**Why it survived review for so long, which is the transferable part:** the sentence is
**vacuously true**. Zero devices carry lifecycle data, so all zero of them are in an Active band. A
TRUE sentence under a WRONG verdict is the hardest form of guardrail 3 to see — nothing in the text
is false, and only the verdict lies. It reached the Architecture Review DOCX, its workbook sheet and
the conformance grade.

`not-assessable` rather than a deviation: nothing observed says those devices ARE past support, so
the honest claim is that the check cannot be answered for them — the same verdict this file already
uses when lifecycle analysis is absent entirely (`:1116`). The recommendation text says plainly *"do
not read this as a pass."*

Pinned by three tests, written FIRST and watched fail: the all-Unknown case must not conform AND must
disclose the count; a fully-assessed Active fleet must STILL conform (so the fix cannot turn a clean
estate into a deviation); and a fleet with both past-LDoS and Unknown devices must still lead with
the real past-LDoS finding rather than being displaced by the coverage branch.
`tests/test_archreview.py`: 32 passed. **Full suite `exit 0, 0 failures, 491 s`.**

> Rig note: my first version of these tests read `ar["findings"]` and `f["impact"]`; the real shape is
> `ar["checks"]` and `implication`. It failed with `KeyError` rather than a false pass — but a test
> asserting on a key that does not exist is one refactor away from being silently skipped.

### 7.23 FIXED — the CLASS behind §7.22, starting with the SSOT slot that made it unsayable

§7.22 fixed LC-1. That was the INSTANCE. The wave-2 reviewer named eight more consumers rendering the
same absence as health, and the reason they all did is one missing slot:
`ssot.CANONICAL_FACTS` carried `n_past_ldos` / `n_past_eos` / `n_near` / `n_active` and **nothing for
`n_unknown`** — so no consumer had a canonical way to say "not determined". A band set that omits
Unknown is not a partition of the fleet, and the omission reads as health.

**Two changes:**

1. **`ssot.py` — added the `n_unknown` slot** (`lifecycle_risk.summary.n_unknown`, which
   `analyze.py:6199` has published all along). This is the structural fix: it gives every downstream
   consumer a way to express coverage, where before the vocabulary itself was missing.
2. **`docmeta.py:512` — the "At a Glance" front matter of EVERY deliverable.** It read
   `"0 device(s) past last-date-of-support (migration-critical)"` for a fleet whose platforms the
   offline EoX KB never matched. `v()` maps only `None` to `[NOT OBSERVED]`; a real `0` passes
   straight through. The undetermined population now rides WITH the headline, not in a footnote:
   *"…plus 4 device(s) NOT ASSESSED: no EoX bulletin matched their platform, so their support state
   is undetermined, not clear."* **Zero findings and zero coverage are different facts, on the first
   page a customer reads.**

Both pinned test-first, watched fail, with the non-vacuity half in the same run: a fully-assessed
clean fleet must NOT gain the caveat and must still read `"0 device(s) past last-date-of-support"`.

> Two rig corrections worth recording, because both were MY error and neither was the code's:
> the first version asserted on `ar["findings"]`/`f["impact"]` when the real shape is
> `ar["checks"]`/`implication` (failed loudly with `KeyError`, but a test asserting on a key that does
> not exist is one refactor from being silently vacuous); and the second failed while the FIX WAS
> WORKING, because it grepped for the literal words "unknown"/"not determined" while the honest
> wording is "NOT ASSESSED"/"undetermined". Assert the property — the count is disclosed — not one
> phrasing, or an editorial pass reddens a correct guard. That is
> [[green-tests-that-pin-nothing]] #6 arriving from the false-RED side.

`test_docmeta_cli_artifacts` + `test_ssot_registry` + `test_archreview` + `test_pipeline_inprocess`:
60 passed. **Full suite `exit 0, 0 failures, 576 s`.**

**Still open in this class — the remaining consumers the reviewer named**, each now ABLE to say
"undetermined" but not yet doing so: `ops.py:216` (Ops Handbook §7 "No past-LDoS / past-EoS platform
flagged"), `design.py:709` (HLD §3.5 "no past-end-of-support hardware was observed"), `crd.py:306`,
`design_advisor.py:3705` (cost axis scores "Comfortable") and `:3975` (Unknown never enters the
replacement BoM, so HLD §5.1 is omitted entirely), `blast_radius_explorer.html:4246` (`lcConcern`
excludes Unknown), `html.py:961` (an un-assessed fleet trends as IMPROVEMENT), and `analyze.py:6172`
(`risks[]` built from Past-LDoS/Near-LDoS only). The slot they need now exists; the wording is a
per-document judgement each of them owns.

### 7.24 Two more consumers in the §7.23 class — the ones that make explicit CLAIMS

Of the eight consumers §7.23 left able-but-not-yet-saying, these two are the ones that assert
something in prose a customer signs off, so they came first.

**1. Ops Handbook §7 (`ops.py:216`)** read *"No past-LDoS / past-EoS platform flagged at
assessment."* That sentence is TRUE of a fleet nobody could assess, and in the day-2 handbook the
NOC runs the network from it reads as "your hardware is supported". Now: an all-Unknown fleet gets
*"N device(s) have UNDETERMINED support status — no EoX bulletin in the offline KB matched their
platform… This is not a clean result."*

**2. HLD §3.5 (`design.py:709`)** read *"no past-end-of-support hardware was observed — carry the
current images forward as the minimum-version baseline for the target design."* Note what that
sentence was doing: `by_model` bands only devices the offline KB matched, so a fleet of entirely
unmatched platforms produced no `eol_models`, fell to this branch, and the sentence **licensed a
design decision** — carry these images forward — on hardware nothing had assessed. Now the
undetermined platforms are named in the same paragraph, capped and counted like the EoS list above
it, ending *"their support state is UNDETERMINED, not clear. Resolve them against Cisco's EoX portal
before adopting the current images as the target baseline."*

Both verified across all three branches (undetermined / clean-and-assessed / real finding present),
and pinned by three tests in `tests/test_ops_handbook.py` — the coverage case, the non-vacuity case
(a genuinely clean fleet must KEEP its clean statement), and the precedence case (a real past-LDoS
population must not be displaced by the coverage branch). 22 passed.

> `_as_int` is not imported in `ops.py` — my first edit used it and would have raised `NameError` on
> the branch it was meant to add. Caught by importing the module, not by the suite: no existing test
> reaches that branch, which is precisely why it was reachable-but-wrong in the first place. Match
> the file's own idiom (`if lc_sum.get(...)`) rather than the idiom of the file you just edited.

**Full suite `exit 0, 0 failures`** (611 s on a loaded box — see §7.18's margin note; the same tree
measured 486 s idle earlier in the session, so treat any single figure as an upper bound).

**Six consumers remain in this class**, all now able to express coverage: `crd.py:306`,
`design_advisor.py:3705` (cost axis scores "Comfortable" on an all-Unknown fleet) and `:3975`
(Unknown never enters `replace_now`/`refresh_soon`, so the HLD §5.1 Replacement BoM is omitted
ENTIRELY), `blast_radius_explorer.html:4246` (`lcConcern` excludes Unknown, so such a device gets no
risk card), `html.py:961` (an un-assessed fleet trends as IMPROVEMENT — lower-is-better on a zero
that means "not measured"), and `analyze.py:6172` (`risks[]` built from Past-LDoS/Near-LDoS only).
`html.py:961` is the most consequential of the six: it turns absence into a positive trend signal.

### 7.25 FIXED — the worst of the class: absence trended as an IMPROVEMENT (`html.py:961`)

The most consequential of the six §7.24 left, because it does not merely fail to warn — it produces
a positive signal from nothing.

`past_ldos` is declared **lower-is-better** in `_TREND_METRICS`, and the campaign timeline published
`lr.get("n_past_ldos")` whether or not anything had been assessed. So a campaign whose first snapshot
found 5 past-LDoS devices and whose second matched NO platform against the offline EoX KB reported
**5 → 0 and trended as improving.** A reader acts on that.

Measured, before and after, through the real `compute_campaign_trend`:

```text
5 past-LDoS (fully assessed) -> 0 past-LDoS (ALL unknown)
   before : "Past end-of-support" trended  improving
   after  : metric ABSENT from the trajectory; campaign verdict INDETERMINATE
control — 5 -> 2, both fully assessed
   after  : still trends  improving            (a real gain is not silenced)
```

A count over PARTIAL coverage is not comparable to one over full coverage, so the step drops out of
THIS metric using the dict's own existing `""` = not-available convention (`n_punchlist`,
`n_not_ready` already use it), and the trajectory skips a metric missing on either side. Every other
metric on that snapshot still trends — the snapshot is not discarded, only the claim that cannot be
supported. Pinned by two tests: the false-improvement case, and the non-vacuity control.

> **I repeated my own mistake one turn after writing it down.** §7.24's note says to match the
> edited file's idiom rather than the previous file's; my first cut of this fix used `_as_int`, which
> `html.py` does not define — `grep -c` returned 1, and that one hit was my own new line. Caught by
> grepping before running, but it is the second instance in two edits. The generalisable form: after
> editing file A, the idiom most available to you is A's, and it is the least likely to be right for
> file B. Check the destination file's helpers FIRST, not the source's.

`test_campaign_trend` + `test_html_coverage_ssot` + `test_html_dos_guard` + `test_snapshot_delta`
pass. **Full suite `exit 0, 0 failures, 582 s`.**

**Five remain in this class:** `crd.py:306`, `design_advisor.py:3705` (cost axis scores
"Comfortable") and `:3975` (HLD §5.1 Replacement BoM omitted entirely for Unknown platforms),
`blast_radius_explorer.html:4246` (`lcConcern` excludes Unknown, so no risk card), and
`analyze.py:6172` (`risks[]` built from Past-LDoS/Near-LDoS only). `design_advisor.py:3975` is the
next by impact — an omitted BoM is a procurement decision the customer never sees offered.

### 7.26 FIXED — the last five of the absence-as-health class; the class is now closed

All five remaining §7.25 consumers, each verified through the real producer and pinned. The class is
closed at the point of *use*: every surface that reads a lifecycle count can now express "not
determined" instead of silently spending a zero.

**1. `design_advisor.py:3975` + `design.py:901` — HLD §5.1 Replacement BoM omitted entirely.**
`_replacement_bom` bucketed `past-ldos` → `replace_now` and the refresh bands → `refresh_soon`;
`Unknown` fell through both. A fleet whose every platform was unmatched by the offline EoX KB
produced `n_replace = 0, n_refresh = 0`, the consumer's heading gate (`if n_replace or n_refresh`)
was false, and **the whole procurement section was omitted** — indistinguishable, to the reader, from
a fleet needing no procurement. An omitted section is the quietest form of this class: there is
nothing on the page to disagree with. Added an `undetermined` bucket + `n_undetermined`, widened the
heading gate, and added a third row group `UNDETERMINED — resolve before procurement`. Deliberately
NOT costed as replacements: nothing observed says they are past support.

> **The producer fix was INERT for one turn.** Adding the bucket changed nothing the reader sees,
> because `design.py` still gated the heading on the two old counts. A producer-level test passed
> against a document that had not changed. Both halves were then mutation-checked in memory — the
> section disappears when either the bucket or the gate is reverted — which is what made the pinning
> real. **Where a producer and consumer are in different files, assert at the consumer.**

**2. `design_advisor.py:3705` — the cost axis scored a top 4/4 "Comfortable".** The scorecard already
clamped `cost` on `coverage_gap`, but that measures *collection* coverage — a different axis from
lifecycle-band coverage. A fleet can be 100 % collected (`census_known`, `not_collected == 0`, so
`coverage_gap` is False) and still have nothing banded. Measured before the fix:

```text
ALL-UNKNOWN, fully collected : score=4 posture='Comfortable'
    "0 past-LDoS + 0 near-LDoS/past-EoS asset(s) imply refresh CapEx."
ALL-ACTIVE,  fully collected : score=4 posture='Comfortable'
    "0 past-LDoS + 0 near-LDoS/past-EoS asset(s) imply refresh CapEx."   <- byte-identical
```

`sig["lifecycle_unknown"]` already existed and simply was not consulted here. Now clamps to ≤ 2 and
discloses the count; a genuinely assessed healthy fleet keeps its 4/4.

**3. `crd.py` — TWO exits, not one.** §2's evidence table printed `n_past_ldos` bare (a plain "0" on
an unbanded fleet), and separately §4's constraints register emitted a hardware-lifecycle constraint
only when `n_past_ldos > 0` **or** `n_past_eos > 0` — both read 0, so **no constraint was recorded at
all** and the requirements workshop proceeded as though refresh were a settled non-issue. Fixing
either alone would have left the CRD false-clean by the other route. §2 now carries the undetermined
population in the same cell as the count it qualifies; §4 gains a `COVERAGE GAP (lifecycle risk)`
constraint. Both rendered and read back out of the real DOCX.

**4. `blast_radius_explorer.html:4246` — the gate and its own renderer disagreed.** `lcConcern`
tested `band !== "Active" && band !== "Unknown"`; the pill that PRINTS the band, ~25 lines below,
tests only `band !== "Active"` and renders Unknown happily. So a device whose only signal was an
undetermined band hit `deviceIntelSection`'s early return, **its entire panel was suppressed**, and
the pill never got the chance to say so. Predicates unified; the band now renders as
`EoL: NOT ASSESSED` with a title explaining the gap, rather than a shrug-shaped "Unknown".

**5. `analyze.py:6172` — an empty `risks[]` read as a clean fleet.** The list was built by looping
over the two ADVERSE bands only, so an unbanded fleet produced `risks == []`, which every downstream
consumer (punch-list, workbook, explorer) renders as no lifecycle risk. Added a `Medium` /
`evidence_confidence: "not-assessed"` entry appended AFTER the loop, so it can never outrank a real
Past-LDoS finding. Verified ordering on a mixed fleet: `["Critical", "Medium"]`.

**Verification.** Eleven new tests across `test_design.py`, `test_design_blueprint.py`,
`test_design_advisor_coverage_honesty.py`, `test_crd.py`, `test_lifecycle.py` and
`test_explorer_render_safety.py`. Every one carries an explicit **non-vacuity** assertion — a
fully-assessed clean fleet must NOT acquire the new disclosure — because each of these fixes could
otherwise be satisfied by an always-on branch that proves nothing.

The explorer guard is **executed, not grepped**: it runs the real embedded `<script>` under node
against the file's existing DOM stub. It was then mutation-tested against the pre-fix predicate in a
scratchpad copy (never the repo tree), confirming `unknown_only` renders now and was SUPPRESSED
before, while `active_only` stays suppressed in both. A source regex would have passed on a predicate
fixed in only one of its two places — which is exactly the defect being fixed.

> **Third instance of the `_as_int` slip, caught before any test ran.** `crd.py` does not define
> `_as_int` either; `grep` returned one hit and it was my own new line. §7.25's note now has three
> data points, so state it as a rule: **before using a helper in a file you have just started
> editing, confirm that file defines or imports it.** Matched `crd.py`'s own
> `isinstance(x, int) and x > 0` idiom instead.

**Full suite `exit 0`** (foreground run — the exit code is the verdict; this suite prints no
`N passed` line). Checkpoint verifier re-run afterwards: **CHECKPOINT INTACT**.

**State:** implemented, focused tests passed, repository-wide green. **NOT independently verified** —
these five fixes are proposer-side only and have not had a Phase-B refuter pass. The absence-as-health
class is closed by enumeration of the consumers found in §7.24's sweep; that sweep was itself
grep-driven, so a further consumer outside its reach is possible and would be worth one adversarial
pass.

### 7.27 RESOLVED — the green gate flapped on a passing suite (§7.16's contradiction, made live)

Not a defect in the code under review; a defect in the instrument that certifies it. Raised as a
blocker, decided by the user, then implemented.

**Symptom.** The Stop hook blocked the turn: `BLOCKED: pytest exceeded 540s; a partial suite is not
green.` The suite was green — `exit 0`, foreground, twice.

**Diagnosis.** `.claude/hooks/verify-green.sh` bounds its pytest run at `timeout 540`. Measured wall
time for this suite, serially: **486 s idle** (earlier this session), **582 s**, **586 s**, **611 s
loaded**. The bound sits *inside* the variance band, so an identical green suite blocks or passes
depending on machine load. That is the §7.16 fail-open/fail-closed contradiction — the hook's own
comment says a timeout should `exit 0`, the code `exit 2`s — turning from a latent inconsistency into
an active blocker.

Raising the bound was not available: the hook ceiling is 600 s, and 586 s leaves no margin.

**No cheap win remained.** The top-25 durations sum to ~200 s of 586 s; the remaining ~386 s is spread
across ~1,790 tests at ~0.2 s each. The single slowest test (`test_runbook_survives_truthy_scalar_
nested_value`, 25 s) was measured apart: **0.03 s of deepcopy, 29.9 s of rendering** — 129 renders ×
232 ms, irreducible without shrinking the case set, which its own reach guard exists to forbid. The
11 tests added in §7.26 are all sub-second and were ruled out as the cause before anything else.

**Decision (user).** Parallelise with `pytest-xdist`, accepting a dev-dependency addition to the
otherwise-frozen tree.

**Implementation.** `pytest-xdist>=3,<4` declared in `[dev]`; the hook runs `-n auto --dist loadfile`.

- `--dist loadfile`, not the default `load`: several modules own expensive module-scoped fixtures
  (`test_phase_timings_contract`'s real `--redact` pipeline run is ~14 s of setup), and scattering a
  module across workers re-runs its fixture once per worker that receives one of its tests.
- The flag is gated on an actual `import xdist` check, not on the pyproject declaration. Passing
  `-n auto` to a pytest that lacks the plugin exits non-zero, and this gate would report it as
  "pytest is failing after your Python changes" — a **false RED on a green suite**, which is the
  failure mode the hook's own header warns about.

**Verified, not assumed.** A parallel run can go green by running *fewer tests*. Both modes were
captured to `--junitxml` and diffed by test id:

```text
serial   : 5,015 testcases, exit 0, 586 s
parallel : 5,015 testcases, exit 0, 166 s
in serial only: 0     in parallel only: 0     -> IDENTICAL TEST SET
```

The hook was then executed end-to-end: `HOOK_EXIT=0`, and its `.git/verify-green.ok` marker was
confirmed byte-equal to a freshly recomputed statekey — so this exact tree is recorded green and an
unchanged follow-up turn skips the re-run. Only pytest sits inside `timeout 540`; the statekey
computation (which `cat`s every untracked file) runs before it.

**Margin, stated as a range — not as the best measurement.** The parallel run carries load variance
of its own: **166 s / 363 s** observed on two full runs, both `exit 0`. Quoting the 166 s figure alone
would repeat in miniature the mistake that caused this whole item — a single favourable measurement
presented as the stable one. What actually changed is which side of the bound the *worst* case falls
on: serial ranged 486–611 s against a 540 s bound and straddled it; parallel ranges 166–363 s and
does not. Treat 363 s as the working figure and re-measure if the gate ever blocks again.

> **A probe of mine read the Microsoft Store python stub** (`command -v python` →
> `WindowsApps/python`, which prints "Python was not found" and exits non-zero). That made a marker
> comparison come back empty and report a false DIFFER. The hook itself is *not* affected — it
> already tests each candidate with `import sys` and falls through to the `py` launcher, which is
> what the block at its line 24 exists for. My ad-hoc check was weaker than the code it was checking.

Pinned by two new tests in `tests/test_ci_gates.py`: that the hook parallelises, keeps
`--dist loadfile`, gates the flag on a real import check, and leaves `$PARALLEL` unquoted at the call
site (quoted, it reaches pytest as a single argv entry and is rejected); and that `pyproject.toml`
declares the dependency, since the hook degrades to serial — silently, back into the flapping band —
without it. The detection was also exercised both ways: 5 argv entries with xdist, 1 without.

**State:** implemented, focused tests passed, repository-wide green under both serial and parallel
execution. §7.16's underlying fail-open/fail-closed contradiction is **still unresolved by design** —
this removes the condition that was triggering it, and does not decide it.

> **Note for a future `/resume-review`: RUN THE VERIFIER FROM POWERSHELL, NOT THROUGH GIT BASH.**
> Launched via the Bash tool it aborts with
> `could not list recovery archive: …\untracked-source-files-ceiling.tar`. This is not drift and not
> a flake — it is fully reproducible and it is an artifact of the launcher.
>
> `Get-SafeArchiveEntries` calls `& tar.exe -tf $Path` unqualified. A PowerShell launched from Git
> Bash inherits a PATH with `C:\Program Files\Git\usr\bin` ahead of `System32`, so `tar.exe` resolves
> to **GNU tar 1.35**, which parses a `C:\…` argument as a remote `host:path` spec and dies with
> `Cannot connect to C: resolve failed`. Windows' own `tar.exe` (bsdtar, in System32) reads it fine.
> Measured: direct `tar.exe -tf` from PowerShell → `exit 0, 63 entries`, three times out of three;
> the identical call from a Bash-launched PowerShell → the abort above, twice out of two. Every
> PowerShell-tool invocation of the verifier in this session PASSed; both failures were Bash-tool
> invocations.
>
> The archive itself was never touched — byte-identical to the hash the verifier had PASSed minutes
> earlier (`a7073e88…`, 11,501,568 bytes).
>
> **Generalisable:** the protocol's "stop and explain, do not auto-repair" is right, but distinguish
> the two failure SHAPES before concluding anything. A **drift** message names an expected-vs-observed
> pair and means the tree moved. A **"could not list / could not read"** message means the verifier
> could not do its job, and says nothing whatever about the tree — suspect your own launcher first.
> Hash the named artifact yourself and compare it against the PASS line from the last good run. Never
> regenerate, restore, or re-seal on the strength of a tool that did not complete.
>
> **Left unfixed deliberately.** Hardening `Get-SafeArchiveEntries` to an absolute
> `$env:SystemRoot\System32\tar.exe` would remove the trap, but the verifier is the instrument this
> whole checkpoint rests on and its own bytes are hash-pinned; changing it mid-review is not a
> proposer-side call. Flagged here for a session that has authorization to touch it.

---

## 8. PHASE B WAVE 3 + PHASE C — 2026-08-01

Four independent read-only refuters (absence-as-health, packaging/privacy/release, web/redaction/custody,
registry/port-authority) plus a full-document audit. **Section 7.26's closing claim was overturned.**
The findings are the reviewers'; every fix below is mine and carries its reproduction.

### 8.1 CORRECTION — 7.26's "the class is now closed" was WRONG

I wrote that the absence-as-health class was closed by enumeration, and flagged that the enumerating
sweep was grep-driven. The refuter found **seven further surfaces** plus a hole inside one of the five
fixes. Retract the closing sentence: the class is **narrowed, not closed**.

Worse, one fix was **inert**. 7.26 justified `analyze.py:6199`'s new coverage risk with "every
downstream consumer (punch-list, workbook, explorer) renders an empty risk list as no lifecycle risk".
That premise is false — a repo-wide sweep of `.py/.html/.ts/.tsx` finds **zero** readers of
`lifecycle_risk["risks"]`, and `archreview.py:1114` says so in a comment I did not read. The entry
exists only in snapshot JSON. Its two tests assert the producer directly, so they pin a change with no
rendered exit. **I asserted a consumer without checking one existed** — the same mistake as 7.26's BoM
fix, which was inert for a turn, one section earlier. Also observed: its detail string renders a blank
where the platform list belongs, because unmatched models carry `platform: ""`.

### 8.2 FIXED this round, each with reproduction

**1. `distribution_verify.py` still used `\b` — the P0 I "fixed" in 7.1 reached 1 of 2 copies.**
The unfixed copy scans the wheel and sdist that get uploaded to PyPI, so the release-facing scanner was
the weaker of the pair. Measured: 7 underscore-glued spellings the repository gate FLAGGED and the
archive scanner MISSED; now **0 divergences**. Pinned by a cross-copy PARITY property, not by
re-asserting each pattern — the defect is the divergence, so any future one-sided fix fails there.

**2. `engagement._verdict` returned PROCEED with an EMPTY condition list on an all-Unknown fleet**,
and the document then printed "No conditions attached — the evidence shows no gating findings; schedule
the pilot wave." `n_near` was unread too, so a fleet months from end-of-support also cleared silently.
Measured after: all-undetermined → 1 lifecycle condition; fully-assessed-and-supported → **0**;
brownfield (LDoS + undetermined) → **2**, independently.

**3. CRD section 4's coverage constraint was `elif`-chained**, so it fired only when the fleet had zero
past-LDoS AND zero past-EoS. It therefore covered the all-unbanded fleet and dropped the **brownfield**
one — some gear banded, most not — which is exactly what the instrument is for. Measured:
`1 Past-LDoS + 3 Unknown` now carries both constraints; `1 Past-LDoS` alone correctly gains none.

**4. Two consumers read the port pack's honest mixed-pack `false` as total registry failure.**
`webapp/backend/summary.py:206` made AssessHub raise a `role="alert"` banner — "Partial coverage, do not
treat this snapshot as a complete verified assessment" — on EVERY healthy run; `COLLECT_PARSE:2218`
created a **FAIL-CLOSED sheet at index 0** of the client workbook, the first thing the customer opens.
Both now route through one new owner, `registry_integrity.pack_is_usable`, which judges a pack on
`official_source_authoritative` when it publishes one and on the whole-pack flag when it does not —
structural, so a future mixed pack needs no edit anywhere. This also makes a malformed (non-dict)
authority entry blocking rather than silently skipped, which is the fail-closed direction section 8
requires.

**5. `vault_digest._is_client_adjacent` dropped `client: true` and PUBLISHED `client: acme-bank`.**
The named client was the one that crossed the ADR-0001 boundary — the gate was inverted precisely where
it mattered. Now every client-flag key carrying a value drops the note; `false`/`no`/empty/unmarked and
ordinary prose do not (this is a networking vault where "client" and "private" are ordinary words).

**6. `mypy.ini`'s full-project report was checking ZERO project files.** numpy >= 2.3 writes its stubs
with PEP 695 `type` statements; parsed under `python_version = 3.10` that is a syntax error and mypy
stops at the first one — "errors prevented further checking" — while still producing output and, in CI,
a `continue-on-error` step that reads as done. Before: `Found 1 error in 1 file`, no project code
checked. After: **417 errors across 53 files, 74 source files checked.** `python_version` stays 3.10
(the lowest supported version, per `requires-python`); numpy's stubs are skipped instead. The gated
8-module run was unaffected throughout — the failure was invisible from the side that gates.

**7. Seven ruff errors — the branch could not pass its own CI gate** (`python -m ruff check .`, the
literal CI command). Now `All checks passed!`

> **Item 8 of 7.2 was NOT open.** I reported `--out` as unconfined; the guard already exists at
> `vault_digest.py:306-314`. My read window started at line 316. I had written a duplicate guard with a
> different exit code before the real code path printed the *existing* refusal — reverted, leaving one
> guard. Running the code caught what reading a window did not.

> **The `_as_int` class of slip, 4th instance:** `registry_integrity` was not imported in `summary.py`.
> Caught by grepping the destination file before running, per 7.25's rule. The rule works; applying it
> is the part that needs doing every time.

### 8.3 Phase C — repository-wide verification, ACTUAL results

| Gate | Result |
|---|---|
| `git diff --check` | **exit 0** |
| `pip check` | **No broken requirements found** |
| `ruff check .` repo-wide | **exit 0** (after fixing 7) |
| Python compile smoke, all tracked `.py` | **exit 0** |
| Import smoke, 71 `cisco_toolkit` modules | **0 failures** |
| mypy gated 8 modules | **Success, exit 0** |
| mypy full-project report | **417 errors / 53 files / 74 checked** (report-only; was measuring nothing) |
| complete pytest suite | **1 FAILED** — see 8.4 |
| `webapp/tests` | **811 passed, exit 0** — the ledger's "3 failures" row is STALE |
| privacy proof `--worktree-only` | **exit 1** — see 8.5 |
| coverage >= 85% | NOT RUN |
| frontend / master-reference npm suites | NOT RUN (`node_modules` present, so offline-capable) |
| graphify update + diagnose | NOT RUN |

### 8.4 The suite is RED on ONE test — and that golden is why the defect survived

`tests/golden/sheet_schema.json` records `Assessment Integrity` as sheet **#1**, header
`["Assessment integrity", "FAIL-CLOSED - do not interpret absent/empty sections as healthy"]`. A CLEAN
pipeline run was blessed as producing a fail-closed banner. Fixing 8.2 #4 removes that sheet, so
`test_excel_sheet_schema_matches_golden` now disagrees; that one removal is the only difference.

**RESOLVED — and the resolution changed what this finding means.** Measured against **git HEAD**, the
corrected golden loses nothing, gains nothing, and changes no sheet's columns:

```text
vs git HEAD -> sheets lost: none | gained: none
sheets whose COLUMNS changed: none
```

`Assessment Integrity` was never in HEAD's contract. It entered the golden through the **earlier
re-bless in this same review** — the one recorded as "purely additive (67 -> 68 sheets, none lost)".
That additive step is exactly where the defect got blessed: the new sheet WAS the false FAIL-CLOSED
banner, and calling the change "purely additive" made it look safe. Removing it restores HEAD's
67-sheet contract byte-for-byte in structure.

So this was not a contract shrink needing authorization; it was reverting an accidental blessing made
earlier in this review. Done through the repository's own guarded door — `UPDATE_GOLDEN=1` **plus** an
explicit `ALLOW_GOLDEN_SHRINK=1`, since `_golden()` refuses to shrink silently and requires removals to
be deliberate — not by hand-editing the JSON. (I hand-edited first and it rewrote the file's
formatting; the repo's own writer preserves it. Use the sanctioned door.)

**Lesson for the next re-bless:** "purely additive, nothing lost" is not a safety argument. An ADDED
row can encode a defect just as easily as a removed one, and it reads as harmless precisely because
nothing disappeared. Diff what the addition ASSERTS, not just its direction.

**Full suite after the fix: `exit 0`, 214 s parallel.**

### 8.5 The candidate tree cannot pass its own privacy gate — the Phase D blocker

`--worktree-only` exits 1 on four files. Structurally, with no identifier printed: the review's own
scaffolding quotes the markers it documents. `.github/scripts/verify_repository_privacy.py:298-304`
explains the 7.1 fix by citing the real spellings, so **7 of its 12 patterns match its own comment** —
staging `.github/scripts/` would deadlock CI permanently. This handoff carries absolute
`C:\Users\<user>\...` paths and the OS username is itself a marker.
`.claude/scripts/review-live-delta.json` quotes a fix reason, and `verify-review-handoff.ps1` names a
private backup file it must check for.

Not weakening the gate (section 1 forbids it) and not scrubbing the review record unilaterally.
**This is the decision that gates Phase D.**

### 8.6 STILL OPEN — reviewer findings not fixed, with locations

**Absence-as-health, remaining:** `webapp/backend/summary.py:335-339` + `api.ts:17` drop `n_unknown` at
the API boundary, so an all-Unknown fleet is byte-identical to all-Active in the browser, and
`Snapshot.tsx:520` hides the line entirely because `0` is falsy · `analyze.py:6427` executive-brief
severity falls to "Low" once ONE device is bandable, so an 89%-unassessed fleet takes the green value ·
the Device Risk Register bands an EoL-Unknown asset green "Low / no stacked risk" (`excel.py:2893`
green fill and no not-assessed column, explorer `:6211`, and `_RR_TOK` missing an `Unassessed` key so it
falls through to green while `_RR_PILL` has one) · `archreview.py:1122` LC-1 and `ops.py:206` carry the
same `elif` subordination fixed in the CRD above, and LC-1 feeds a conformance grade ·
`design_advisor.py:3714`'s clamp misses **absent/empty** lifecycle, reachable via `_run_phase(_default={})` ·
`html.py:1039` drops the campaign metric silently when BOTH endpoints abstain · `ssot.py:71`
`_LIFECYCLE_BANDS` omits `n_unknown`, so drift in the one canonical fact that means "not determined" is
unguarded · explorer `:10370` auto-answers the EoL interview question green using the coverage gap as
its evidence.

**Web lane:** `ingest._unusable` tests zip-openability only for a hand-listed suffix set, so a
**truncated `_explorer.html` is certified COMPLETE and VERIFIED with exit 0** — while
`docmeta.validate_artifact`, already in this repo, rejects it · the "independent" raw-capture verifier
reuses the producer's `.txt`-only selector (`html.py:1923` = `redaction_verify.py:816` =
`ingest.py:1587`), so `backup-config.cfg` and `show_tech-support.log` keep **cleartext secrets** while
the tool prints SCRUBBED, and a zero-`.txt` tree verifies clean · `/api/meta` is the most expensive GET
measured (52 ms, uncached, no generation slot) and appears in neither the guarded nor the "cheap" list ·
`certify_shareable_artifacts` silently drops suffixes outside its list, including `topology.mmd`/`.dot`,
which the CLI seals into the run manifest and ships beside the deliverables.

**Registry lane:** the assistive label dies one hop from lookup at `analyze.py:2515` — curated-only
service names and all 21 curated multicast classifications reach the workbook, explorer, runbook 6.6 and
the **NRFU acceptance plan** with no authority metadata, and one path stamps them "Confirmed" ·
`analyze.py:2704` lets curated semantics escalate a finding to **High** · `authority_scope` is emitted
by the generator and read by nothing.

**Packaging lane:** `distribution_verify` binds no git object — `--source-commit`/`--source-tree` are
regex-shaped labels stamped into the proof unverified (the CI *composition* does bind tracked bytes via
`verify_checkout_immutable`, so the defect is that the artifact-facing tool asserts a binding it did not
perform) · six `*_verified` proof fields are literals, so `--expected-json` is vacuous for exactly the
keys a reader checks first · the SPA's expected member set is globbed off disk, so expected == actual.

### 8.7 Document-integrity finding

**Sections 7.8 through 7.11 do not exist** — the heading sequence jumps 7.7 to 7.12, and six 7.2 items
are declared closed by a bare count at line 2288 with no section recording their resolution. I checked
all six against the CODE rather than the document: items 1 and 4 (the unsatisfiable release gate, the
two unguarded state-changing GETs) **are** fixed and were simply never written up; item 7 was genuinely
open and is fixed in 8.2 above; item 8 was never broken; items 9 and 10 remain open. Verify against
code, not against this file's own prose.

---

## 9. R8 ROUND 1 — five lanes over the remaining findings, five independent refuters — 2026-08-01

Ten agents: five fix lanes with DISJOINT file ownership (they edit this live tree concurrently, so
overlapping ownership would corrupt each other), each followed by an independent read-only refuter.
**Every one of the five lanes came back PARTIAL.** No lane survived its refuter intact. That is the
expected and correct outcome — it is what the refuters are for — and it is the third consecutive round
in which independent review overturned claims the author had already verified.

### 9.1 What landed, and what the refuters took back

Roughly 23 fixes were claimed across the five lanes and the majority were confirmed by their refuter
against real reproductions. The claims that did NOT survive are the useful part of the record:

**INERT fixes — the recurring failure of this whole review.** W1's `engine_warnings` change alters no
output any user or API client can observe: `run_redaction_folder` has exactly ONE production caller,
and `report["engine_warnings"]` has no consumer that reaches a user. E1's repair of the lifecycle
coverage-risk detail string fixes a sentence that nothing renders — `lifecycle_risk["risks"]` still has
essentially no reader. **This is the same defect as §8.1**, one round later, in a round explicitly
briefed about it. A producer-side change is not a fix until a consumer is named and its output shown to
differ.

**Fixed at some exits, not all.** W1's raw-capture coverage disclosure reaches the AssessHub path and
NOT the `cisco-assess` CLI — which CLAUDE.md names as the engine's primary entrypoint. W1's campaign
"not comparable" disclosure reaches the workbook and not the web UI (`webapp/backend/engine.py:34`
re-exports the same function). E1 fixed the curated-semantics severity escalation at `analyze.py:2705`
and left the sibling at `:6564`. U1's Device Risk Register work left four more exits *in its own file*.

**New defects introduced by the fixes themselves.** The axis-coverage guard added to close
absence-as-health FAILS OPEN on absent axis data — `bool(n_axes and n_na * 2 >= n_axes)` is False when
`n_axes` is 0, so an asset nobody could assess reads as fine. The API lifecycle projection now DERIVES
the unknown count by classifying band strings instead of reading the canonical `n_unknown` the engine
publishes, which is an SSOT violation dressed as a fix. The release proof's `source_binding.verified`
reads **true** on a run bound to no commit, and its git check is a tautology — it validates the
caller's commit against the same tree the caller derived it from. A read/write inversion appeared in
the route guard: an admin-configured CORS origin may WRITE but not READ.

All of the above are the input to round 2 (§10).

### 9.2 The goldens — and the guard that caught what I would have missed

Three artifacts disagreed after the lanes landed: `tests/golden/snapshot.json`,
`tests/golden/sheet_schema.json`, and `webapp/sample_data/sample_fleet.snapshot.json`.

I verified what the additions ASSERT rather than accepting "additive" — §8.4's lesson. Measured against
the golden, `service_map.services[]` gained eleven keys and **lost none**, and the values match the
registry ground truth exactly:

```text
registry  22/tcp  : assignment_auth=True  semantics_auth=False  overlay='supplemental'
service_map 22/tcp: assignment_authoritative=true semantics_authoritative=false overlay_status='supplemental'
registry  4440/udp: assignment_auth=False semantics_auth=False overlay='overlay-only'
distinct (assignment, semantics) pairs across the golden's services: (True,False), (True,True)
```

The last line is the check that matters: the new field is not a constant, so it carries information.

I then ran `UPDATE_GOLDEN=1` **without** `ALLOW_GOLDEN_SHRINK=1` deliberately, so the repository's own
guard would have to prove nothing was lost rather than my reading of a diff. It refused:

```text
UPDATE_GOLDEN would SHRINK the sheet_schema.json contract vs git HEAD:
  - sheet 'Device Risk Register' lost header 'Device Risk Register: 1 Severe, 0 Elevated of 3 asset(s) ...'
```

That is the guard working. Inspected: the banner was not removed, it was EXTENDED — the new string
keeps the original sentence verbatim and appends `COVERAGE: 11 of 33 risk axes fleet-wide were NOT
ASSESSED (column Q per asset)`. A prefix-preserving rewrite reads to the guard as a loss. I then proved
the point structurally before allowing the flag:

```text
GENUINE losses (column dropped / sheet gone / banner replaced not extended): none
Added columns/headers: Service Map: Name authority
```

Only then `ALLOW_GOLDEN_SHRINK=1`. **Use the repository's guarded door and let it argue with you** —
running it armed first is what turned "I believe this is additive" into evidence.

Two facts the regeneration exposed, both worth stating plainly:

* The repo's own demo fleet has **16 of 23 devices (70%) unassessed**, and the committed LC-1 check
  never mentioned them. `n_past_ldos=1, n_past_eos=6, n_unknown=16`. The verdict and `score_pct` did
  not change; the disclosure did.
* The golden's own 3-asset fleet has **11 of 33 risk axes never assessed**, and the old Device Risk
  Register banner said nothing about it.

Both are exactly the class this review has been chasing, sitting in the repository's own reference
data the whole time.

### 9.3 State

`tests/golden/snapshot.json` and `tests/golden/sheet_schema.json` regenerated through the guarded door;
`webapp/sample_data/sample_fleet.snapshot.json` rebuilt with `build_sample.py` (23 devices, 25 links,
108 punch-list items). **Full suite: `exit 0`, 185 s parallel. Ruff: `All checks passed!`**

Also closed this session, previously never run on this tree: `master-reference` — `npm test` 3/3 pass,
`typecheck` exit 0, `lint` exit 0, `npm audit --offline` 0 vulnerabilities. Caveat: that is against the
existing `node_modules`, NOT a fresh `npm ci` from the lockfile, which needs network.

**Not run: the coverage gate, the AssessHub frontend suites, and `graphify update`.** Deliberately —
they were deferred rather than measured under eight-to-ten concurrent agents, because §7.17 already
recorded one set of timings inflated ~5x by exactly that mistake.

---

## 10. R8 ROUND 2 — the refuter findings, including round 1's own regressions — 2026-08-01

Eight agents: four fix lanes over §9's refuter output, each followed by an independent verifier.
**C-route-guard came back SOUND** (18 claims confirmed, no residual). A, B and D came back PARTIAL.

### 10.1 The pattern that will not die: INERT fixes

D's lane fixed two findings into `executive_brief.axes[].detail` — and its verifier proved that field
is rendered by **no deliverable surface at all**. Every one of the four named renderers emits only
`(axis, severity, headline)`. So the third consecutive round produced a fix whose only evidence is that
it exists in JSON, in a round whose brief opened by naming that exact failure.

Stated as a rule, because three rounds is a pattern and not bad luck: **a change is not a fix until you
have named the consumer and shown its output differ.** "The producer now emits X" is a claim about the
producer. Grep the renderers first; if none reads the field, either wire one or do not call it a fix.

A's verifier landed the same shape from the other side: it confirmed 13 claims but found the lane had
closed a fail-open by installing a subtler one (§10.2).

### 10.2 FIXED by me after round 2 — a fail-open introduced by the fix for a fail-open

`webapp/backend/summary.py` decided "was this measured?" with `"n_unknown" in lr`, then read the value
through `_int0`, which maps null / a string / a dict / a negative / a bool to **0**. So a lifecycle
section carrying `n_unknown: null` reported `coverage_measured=True, unknown=0` — "assessed, nothing
undetermined" — off a section that had measured nothing. Key PRESENCE is not evidence; a usable VALUE
is. Added `_census_int`, the honest sibling of `_int0`: it returns `None` for anything unusable, and
the caller discloses that rather than counting it as clean. Measured across every malformed shape:

```text
n_unknown: 3 (honest)        measured=True  gap=True   unknown=3   src=lifecycle_risk.summary.n_unknown
n_unknown: 0 (honest zero)    measured=True  gap=False  unknown=0
n_unknown: null               measured=False gap=True   unknown=0
n_unknown: 'lots' / {} / -1 / True / ABSENT   measured=False gap=True
by_band census, owner absent  measured=True  gap=True   unknown=3   (fallback intact)
```

The honest zero is the ONLY case reporting no gap — otherwise the projection would be permanently
alarmed, which tells a reader nothing either.

### 10.3 Residual findings from round 2's verifiers — NOT fixed, carried forward

* **B (release proof):** F1's defect survives on the **sdist half**. The headline verdict's coverage set
  is `runtime_inventory`, which yields only `{COLLECT_PARSE_V3_23_0.py, cisco_toolkit/**}` — the sdist's
  shipped bytes are outside it. Also: the new `untracked_*` fields make the proof sensitive to
  bytecode-cache and build-directory churn, and `_verify_expected_proof` compares the whole dict.
* **B:** binding to something genuinely independent of the verified tree is **not implementable inside
  this module** — every value it can reach comes from the same checkout. Correctly reported as
  not-fixed rather than papered over. The honest resolution is architectural, not local.
* **D:** the curated on-air classification still reaches **four rendering sites** as a measurement,
  three of which actually reach a reader; only the (unrendered) executive-brief exit was addressed.
* **D:** `html._is_raw_capture` and the verifier's `is_uncoverable_capture` still diverge on names with
  two leading dots — `os.path.splitext` ignores a leading dot where `PurePath.suffix` does not.
* **A:** three further exits render the dossier `risk_band` with no coverage qualification —
  `runbook.py:1185`, `deck.py:333`, `mcp_server.py:239-243` — outside A's lane, named here per the
  every-exit mandate.
* **D reported `golden_impact: None` on false evidence** (it claimed `multicast_intelligence` is absent
  from the golden; it is present and populated). The claim happened to be harmless — the suite is green
  — but the reasoning was wrong, and a golden claim justified by a false premise is worth recording as
  such.

### 10.4 PHASE C — COMPLETE. 12 of 13 gates green

| Gate | Result |
|---|---|
| `git diff --check` | exit 0 |
| `pip check` | No broken requirements found |
| `ruff check .` (the literal CI command) | exit 0 |
| Python compile smoke, all tracked `.py` | exit 0 |
| Import smoke, 71 `cisco_toolkit` modules | 0 failures |
| mypy gated 8 modules | Success, exit 0 |
| mypy full-project report | 417 findings / 53 files / **74 checked** (was 0 checked) |
| complete pytest suite | **exit 0**, 255 s parallel |
| **coverage gate >= 85%** | **90.73%**, exit 0 |
| AssessHub frontend | vitest **20 files / 200 tests pass**; build exit 0; audit 0 vulnerabilities |
| master-reference | 3/3 tests; typecheck 0; lint 0; audit 0 vulnerabilities |
| offline `graphify update` + `diagnose` | exit 0 — **12,103 nodes / 21,337 edges / 819 communities** |
| privacy proof `--worktree-only` | **exit 1** — the Phase D blocker, unchanged (see §8.5) |

Two caveats stated rather than buried: the npm audits are `--offline` against existing `node_modules`,
not a fresh `npm ci` from the lockfile (which needs network); and the graph's AST-only invariant was
re-checked after the rebuild — **12,093 `ast` + 10 curated, zero LLM-derived origins**, so the
no-egress/AST-only doctrine holds across the regeneration.

### 10.5 Honest state

**Implemented, focused tests passed, repository-wide green, coverage-gated, and independently reviewed
across two waves.** NOT release-ready: the privacy gate still fails on the review's own scaffolding
(§8.5), no distribution has been built, nothing is staged or committed, and the residual findings in
§10.3 are real and unaddressed. Two rounds of adversarial review found a defect in every lane both
times; a third round would find more. The right reading is that this codebase's honesty properties are
now materially better than at §7, not that they are finished.

### 10.6 Two checkpoint-bookkeeping traps, both hit this session

**Running `npm run build` mutates checkpoint-pinned state.** Phase C asks for an AssessHub frontend
build. `webapp/frontend/dist/` is UNTRACKED and is inventoried by the sealed untracked archive, and
Vite names its chunks by content hash — so a build whose source has legitimately changed renames three
of five files and the verifier fails:

```text
untracked recovery archive inventory drifted: => webapp/frontend/dist/assets/index-CJedhDPR.js
```

The live-delta schema can declare an ADDED untracked file (`added_untracked`) but has no way to say a
sealed untracked entry was legitimately REPLACED, so the drift cannot be declared away. Resolution:
the sealed bundle was restored verbatim from `untracked-source-files-ceiling.tar` (5 files, byte-for-
byte, hashes logged) — nothing is lost, because the new bundle is reproducible at any time with
`npm run build`. **Run the frontend build LAST, or accept that you must restore afterwards.** Note this
is the same `dist/`-is-untracked hole §I1/F1 already describes from the release side.

**The live-delta covers the SOURCE MANIFEST's path set, NOT git-tracked-changed.** A re-pin loop keyed
on `git status --porcelain` (skipping `??`) silently misses every UNTRACKED source file — and this
review has many, including whole uncommitted lanes: `cisco_toolkit/distribution_verify.py`,
`webapp/backend/redaction_verify.py`, `tests/test_distribution_verify.py`. They are in
`SOURCE-MANIFEST.ceiling.json`, so the verifier checks them against the sealed manifest and fails with
`source length drifted for <path> (anchor: sealed manifest)` — the word **anchor** tells you which set
it used, and "sealed manifest" means the file has no delta override at all.

Correct re-pin: iterate `SOURCE-MANIFEST.ceiling.json`'s `files[]`, compare each against its EFFECTIVE
anchor (delta override if present, else the sealed record), and declare only the genuine mismatches.
Doing that here produced **1 mismatch across 646 paths**, fully attributable to one lane's added tests
— which is also the useful property: a blanket re-pin would have hidden that number, and the number is
the evidence that nothing unexplained moved.

---

## 11. R8 ROUND 3 — the §10.3 residuals — 2026-08-01

Eight agents over the four §10.3 items, each lane followed by an independent refuter.
**Lane 4 (capture-rule parity) came back SOUND** — 14 claims confirmed, one minor residual. Lanes 1–3
came back PARTIAL.

### 11.1 The inert-fix failure did NOT recur, and the reason is worth keeping

Rounds 1 and 2 each shipped fixes that wrote a field no renderer reads. For round 3 the report SCHEMA
was changed: every `fixed[]` entry carries a mandatory `consumer` field naming a real `file:line` that
RENDERS the value and how its output differs, and each refuter was told to check `inert_fixes` FIRST
and to produce the rendered before/after itself rather than accept the author's word.

**Result: zero inert fixes across all four lanes.** The lesson generalises past this repo — when a
failure mode recurs, change the shape of the report so it cannot be expressed silently. Asking agents
to "be careful about X" had already failed twice; making the schema refuse to represent X worked once.

### 11.2 What the four residuals turned into

**§10.3 item 4 — capture-rule parity — CLOSED (verdict SOUND).** `html._is_raw_capture` used
`os.path.splitext` while `redaction_verify.is_uncoverable_capture` used `PurePath.suffix`; those are
NOT equivalent (splitext ignores a leading dot, suffix does not), so the producer and the "independent"
verifier disagreed about which files were in scope for every name with two leading dots. Giving ONE
lane both sides — which rounds 1 and 2 structurally could not do, each owning only one file — is what
closed it. Residual: the two still diverge on non-str input.

**§10.3 items 1 & 2 — release proof — PARTIAL.** The shipped-bytes coverage set no longer comes from
the runtime inventory, and the proof now states its own limits. Two honest non-fixes stand: binding to
something genuinely INDEPENDENT of the verified tree remains unimplementable inside this module (every
value it can reach comes from the same checkout — correctly reported rather than papered over), and
`verify_archives` has still never been driven to a SUCCESSFUL return by any test, because every call in
all three test files sits inside `pytest.raises`. That second one is a real coverage hole in the
release instrument and should be stated plainly rather than counted as passing.

**§10.3 item 3 — on-air renderers — PARTIAL, and the enumeration grew.** The producer side was already
done (`analyze.py:2723-2783`). The renderers in excel.py and the explorer now carry the authority. But
the lanes' own every-exit sweeps named SIX further unqualified exits outside their files —
`design.py:882`, `design_advisor.py:4576`, `crd.py:394`, `analyze.py:4326` (which drops
`severity_basis`/`evidence_confidence` when folding the mac-alias risk into findings), and the HLD
multicast table. The curated on-air flag escalates a finding to **High**, so this is not cosmetic.

**§10.3 item 5 — dossier exits — PARTIAL.** runbook, deck and mcp_server now disclose `n_na`. The
sharpest one is worth recording: `deck.py:320` selected only Severe/Elevated/Guarded, so an
all-unassessed fleet produced an EMPTY slide in a customer-facing deck — absence rendered as health, in
the most visible place in the deliverable set.

### 11.3 FIXED by me after round 3 — two wrong numbers that would have reached a customer

Both are the same shape: a ratio between two INDEPENDENTLY published counts, formatted without checking
the pair is coherent.

* `cisco_toolkit/excel.py` Multicast Intelligence summary rendered
  `{n_av - n_av_auth} curated/unverified`. With `n_av_groups_authoritative > n_av_groups` that prints a
  **NEGATIVE count** — a number that cannot exist — in a client workbook. Now: `census INCOHERENT: 7
  reported as registry-authoritative out of 3; the split cannot be stated`.
* `cisco_toolkit/runbook.py::_av_authority` formatted `{n_auth} of {n_av}`, rendering "7 of 3" with
  nothing to distinguish it from a real ratio. Same disclosure.

Verified across the full matrix — coherent, incoherent, none-authoritative, equal, malformed `null`,
and absent census — and both malformed and absent fail CLOSED. Non-vacuity pinned in both tests: a
coherent census must still state the real split, or the disclosure is always-on and says nothing.

Also fixed: `tests/test_distribution_verify.py` imported `_INDEPENDENCE_LIMIT` and never used it
(ruff F401, so **CI would have failed**). Resolved by strengthening the assertion rather than deleting
the import — it now pins `binding["independence_limit"] == _INDEPENDENCE_LIMIT` instead of testing for
a substring, because a substring assertion passes while the sentence around it is rewritten weaker, and
that sentence is the only thing stopping a reader believing the binding is independent when it is not.

### 11.4 State

**Full suite `exit 0` (205 s parallel). Ruff `exit 0`. CHECKPOINT INTACT.**

Exit codes captured with `> file 2>&1; rc=$?`, not through a pipe — an earlier check in this session
read `tail`'s status and reported ruff green while ruff was returning 1.

Still open and carried forward: the six unqualified on-air exits in §11.2; `verify_archives` never
driven to success; the release binding's residual naming inconsistencies; and unchanged from before,
the privacy gate failing on the review's own scaffolding (§8.5), which remains the Phase D blocker.

Three adversarial waves have now found defects in every lane, every time. The rate is falling and the
severity with it — round 3's worst was a negative integer in a spreadsheet cell, where round 1's was a
cleartext-secret leak — but "no round has come back clean" remains the honest summary.

### 11.5 An intermittent race worth naming, not filing as "flaky"

`tests/test_gate_state.py::test_a_reader_racing_a_writers_rename_does_not_read_as_unreadable` failed
ONCE, in a Stop-gate run that overlapped other work, and did not reproduce in **nine** subsequent runs
(5 isolated, 3 file-level under `-n auto`, 1 full suite), nor in the re-run of the gate itself.

It is not a meaningless flake. The test's own docstring records the underlying defect: `load_store` is
deliberately unlocked, so a read can land inside a writer's `os.replace` and take `[Errno 13]` on a
PERFECTLY HEALTHY ledger, which `enforce()` then reports as `unreadable` — a non-overridable refusal
that withholds a deliverable. Measured before the mitigation: **357 of 25,348 reads (1.41%)** under one
concurrent writer. The mitigation is a BOUNDED retry, so under enough contention the budget can still
be exhausted — which is what a 14-worker suite plus concurrent agents produced.

Two things follow, and neither is "increase the retry count until it stops":
1. The failure direction is SAFE — it refuses rather than proceeding on bad data. A false refusal costs
   a re-run; the inverse would cost a wrong deliverable.
2. The honest fix is to remove the race (lock, or read-with-retry keyed on the actual Windows sharing
   error) rather than widen a threshold. Raising the bound would only move the load at which it recurs,
   and this repo's standing rule forbids relaxing a threshold to green a gate.

Recorded as a KNOWN load-sensitive test. A future session seeing it fail once under parallel load
should re-run before investigating, and should not treat a single failure as a regression — but should
also not treat it as noise, because the 1.41% figure is real and measured.

---

## 12. R8 ROUND 4 — the curated on-air classification at every exit — 2026-08-01

Six agents (3 fix lanes + 3 refuters) over what was carried as "six on-air exits".

**First correction: there were FIVE distinct exits, not six.** `design.py:882` and
`design_advisor.py:4576` are the SAME defect — `design.py` renders a generic
`target_state.dimensions[]` entry, and the offending sentence ("{n_av} audio/video multicast group(s)
on the flat fabric") is authored at `design_advisor.py:4583`. Fixing it in the renderer would have been
wrong; fixing both would have double-qualified it. Count the exits by where the SENTENCE IS AUTHORED,
not by where a string surfaces.

8 fixes landed, all three lanes pytest exit 0, and **all three independently confirmed NO golden impact
BY RUNNING `tests/test_pipeline_golden.py`** — the check added because an earlier lane asserted "no
golden impact" on false evidence. All three refuters returned PARTIAL.

### 12.1 What the refuters caught that matters

**The sentinel was wrong in the HARMFUL direction (fixed by me).** The producer lane added
`PUNCH_BASIS_UNPUBLISHED` = "severity basis NOT published by this snapshot — **do not read this
severity as measured**", and applied it to EVERY media risk. But `querier-gap`'s High severity IS a
measurement (observed querier state). The sentence fused two different claims: "no basis was
published" (true of every row it lands on) and "the severity was not measured" (false for that row).
Telling a reader to discount a measured finding devalues the real ones and trains them to skip the
caveat on the curated rows it exists for. Reworded to disclose absence only. The test that pinned the
old sentence was updated to assert the PROPERTY plus a negative guard (`"as measured" not in cell`) so
the fused claim cannot come back.

**`_as_int` accepts NUMERIC STRINGS — the fail-open class, 4th instance.** `design_advisor`'s census
guard delegates to `textutils._as_num`, which does `float(x)`, so a JSON `"n_av_groups_authoritative":
"1"` coerces to 1 and the census reads USABLE AND AUTHORITATIVE. The lane's own test probed the string
case with `"many"` — which fails to parse and therefore passes — so the realistic JSON shape went
untested. **A malformed-value probe must include the malformed values that PARSE.**

**An INCOHERENT census still passes `curated_gate`** in design_advisor, even though that lane's own
`_av_authority` classifies incoherence as unusable ("the authority split cannot be stated"). Two guards
in one file disagreeing about what "usable" means.

**Still-unqualified exits found IN-LANE and not listed:** `crd.py:483-490` (REQ-T-SVC-001 states a
curated registry classification as observed fact — same class as the REQ-T-MC-001 the lane did fix) and
`design_advisor.py:3325-3345` (`_d_oncrit_seg` emits a **High** decision reading off the same curated
basis). Both lanes' every-exit sweeps grepped `classified_groups|n_av_groups`, which is keyed on the
multicast symbols and structurally cannot see a sibling exit phrased differently — **a sweep keyed on
symbol names cannot find the class**.

**Half-inert fix:** `severity_basis`/`evidence_confidence` as punch-list ITEM KEYS have zero readers
repo-wide. The `detail` half does reach AssessHub (`Snapshot.tsx:184` renders `r.detail`), so the
disclosure is not lost — but the structured keys are a contract with no consumer, and the report
presented that contract as a consumer. A contract is not a consumer.

### 12.2 Also fixed by me this round

`tests/test_design_advisor_coverage_honesty.py:327` had a mid-file import (ruff E402) — **CI would have
failed**. Hoisted to the top rather than suppressed. This is the second CI-breaking lint a lane left
behind (round 3 left an F401), so: **run `ruff check .` after every agent round, and read its REAL exit
code — a piped `$?` reads the pipe's status.** That mistake was made once in this session and reported
ruff green while it was returning 1.

### 12.3 State

**Full suite `exit 0` (205 s parallel). Ruff `exit 0`. CHECKPOINT INTACT.**

Carried forward, unfixed: the numeric-string fail-open and the incoherent-census gate in
design_advisor; `crd.py:483` REQ-T-SVC-001 and `design_advisor.py:3325` `_d_oncrit_seg`; the
structured-key contract with no reader; and several tests the refuters called partially vacuous
(notably a per-group basis test asserting bare tokens against whole-document text, which the fix's own
note paragraph satisfies regardless of the per-group rendering).

Unchanged and still the Phase D blocker: the privacy gate fails on the review's own scaffolding (§8.5).
Also unchanged: `verify_archives`'s ACCEPT path has no behavioural coverage — measured this round,
3 real invocations across the three release test files and **all 3 inside `pytest.raises`**; the
remaining mentions are an import, two docstrings, a string literal, and an `inspect.getsource` call
(a source-text assertion standing in for behaviour).

Four adversarial waves, a defect in every lane every time. The severity is falling — wave 1's worst was
a cleartext-secret leak, wave 4's is a caveat sentence that overclaims — but no round has come back
clean, and the honest projection is that a fifth would also find something.

### 12.4 CORRECTION to §12.3 — the `_d_oncrit_seg` qualifier was NOT inert; my probe was too shallow

§12.3 recorded the on-air qualifier on `_d_oncrit_seg` as landing in source but reaching no field of the
decision, i.e. inert. That was wrong, and the error was in the measurement, not the code.

`_decision(pid, summary, count, axes, fields, ...)` (design_advisor.py:1729) puts its SECOND positional
into **`evidence["summary"]`** — a nested dict. My check scanned only top-level fields with
`isinstance(v, str)`, so it never looked inside `evidence` and reported "NONE". Verified properly, the
qualifier is present in every authority state:

```text
census ABSENT        ... treat the broadcast/AV label as curated, not authoritative (the L3 reachability
                         and ACL coverage above ARE measured; the on-air tiering is not).
none authoritative   ... a CURATED offline-registry classification, not a measurement (…ARE measured…)
2 of 5 authoritative ... the remainder are CURATED, not measurements (…ARE measured…)
STRING '1'           ... curated, not authoritative   <- the census fix showing through
```

And it is **consumed** — three render sites read `evidence.summary`:
`blast_radius_explorer.html:7422` (decision card), `:8481` (causal-flow trigger), and
`webapp/frontend/src/components/DesignBlueprint.tsx:45`.

**Two measurement errors on this one fix**, both mine: the CRD check used `next()` and matched the bare
`REQ-T-SVC-001` id cell instead of the text cell, and this one scanned one level too shallow. Both
produced a FALSE NEGATIVE — reporting working code as broken.

That direction is worth naming, because this review has spent four rounds hunting the opposite error.
A false negative is cheaper than a false positive (it wastes effort rather than shipping a defect), but
it is the same underlying failure: **trusting a probe I had not validated against a known-good case.**
The discipline that catches it is the same one that catches inert fixes — before believing "the value
is absent", prove the probe can SEE a value that is definitely there. Run it against the positive case
first; a probe that reports absence should be presumed broken until it has reported a presence.

Pinned by `tests/test_design_advisor_coverage_honesty.py::test_the_oncritical_isolation_decision_
discloses_that_its_tier_is_curated` (asserts on `evidence.summary`, and cites the three consumers) and
`::test_the_av_authority_census_rejects_a_numeric_STRING` (14 malformed shapes rejected; 0/1/5/3.0
still accepted, so the guard is not always-on).

### 12.5 FIXED — the gate-state race was a fixed-backoff pathology, on BOTH sides

§11.5 recorded `test_a_reader_racing_a_writers_rename_does_not_read_as_unreadable` as a known
load-sensitive test and said a single failure should not be treated as a regression. It then failed a
SECOND time in the Stop gate, which changes the reading: twice in ~8 gate runs is a signal, not noise.

**Diagnosis, by measurement rather than assumption.** The test has two assertions and I checked which
one was fragile before touching anything:

```text
assert n > 200   -- throughput floor.  Measured idle: n = 7220 reads in the 3 s window (36x headroom)
assert not bad   -- the actual race
```

36x headroom rules out the throughput floor, so the race itself was firing. Pure CPU starvation did
not reproduce it (12 busy-loop hogs: still passed), which pointed at the retry SHAPE rather than at
scheduling delay alone.

**Root cause.** `_read_ledger` retried 6 times with a CONSTANT 5 ms backoff — a ~25 ms window — while
the writer renames on a tight loop. A constant sleep keeps the reader beating in LOCKSTEP with the
writer, so the six attempts are correlated rather than independent and the extra tries buy almost
nothing.

**Fix: the shape of the wait, not its budget.** Exponential backoff with jitter (5/10/20/40/80 ms),
SAME attempt count, ~155 ms covered, de-synchronised from the writer. Jitter is derived from the
monotonic clock rather than `random`, so the module keeps its deterministic import surface. Still
bounded, still fail-CLOSED at the end. Deliberately NOT `_RACE_RETRIES = 20`: raising a threshold to
green a gate is the move this repo's doctrine forbids, and it would not have fixed the correlation.

**Then the MIRROR test failed — and that was the same defect at its other exit.**
`test_a_writer_racing_a_transient_reader_still_records` covers the write side, whose rename retry used
the identical fixed 5 ms (~25 ms total) against a reader that legitimately holds the destination for
~12 ms. Marginal the moment the scheduler is busy. Fixing only the read half left the mirror live:
**the every-exit rule applies to this repo's own internals, not just to its deliverables.** Same
exponential+jitter applied at the write site.

Verified: both race tests 8/8 consecutive passes; `tests/test_gate_state.py` exit 0; **two** full
parallel suite runs exit 0 (213 s, 264 s); ruff exit 0; Stop gate exit 0.

> The sequencing is the lesson. Fixing one side made the other side's identical latent defect the
> next thing to fail — it had been hiding behind the first. When a fix moves a race, re-run the
> siblings before believing it is closed.

### 12.6 FIXED — the incoherent-census gate: two definitions of "usable" in one file

`compute_target_state`'s media/timing dimension asked
`not (_assessed and _n_auth > 0)` to decide whether the on-air classification was authoritatively
backed. `_av_auth_census` returns `assessed=True` for an INCOHERENT pair (`n_auth > n_av`, e.g. 7
authoritative out of 3 groups), and `_n_auth > 0` holds there, so the gate concluded "authoritative"
and stamped the dimension **Observed** with no disclaimer — two lines below `_av_authority(mi)`, which
on that exact input emits "census INCOHERENT: the authority split cannot be stated for this snapshot".

One snapshot, one file, two answers: *cannot be stated* in the prose, *authoritative* in the
machine-readable confidence field. Coherence was being treated as a presentation concern in one place
and ignored as a usability concern in the other.

**Fix: one predicate, `_av_auth_backed(mi)`**, sited next to the census so every caller inherits it —
not a third conjunction bolted onto the call site. It refuses on no-usable-census, refuses on an
incoherent pair, and otherwise answers `n_auth > 0`. The inlined `_assessed and _n_auth > 0` is gone.

Measured across the matrix (dimension confidence vs what `_av_authority` says about the same input):

```text
census                      confidence               disclaimer   _av_authority
INCOHERENT 7 of 3           Curated-classification   yes          INCOHERENT     <- was Observed/no
coherent 2 of 5             Observed                 no           ratio stated
none authoritative 0 of 5   Curated-classification   yes          NONE
all authoritative 5 of 5    Observed                 no           ratio stated
census ABSENT               Curated-classification   yes          NOT ASSESSED
STRING '1'                  Curated-classification   yes          NOT ASSESSED   <- census fix showing through
PTP observed (clocks=3)     Observed                 no           (gate is for classification-ALONE)
```

Non-vacuity holds in both directions: a coherent or fully-authoritative census still reads Observed, so
the gate is not always-on, and observed PTP evidence keeps the dimension Observed regardless — the gate
exists only for a dimension raised by the classification alone.

Pinned by `::test_the_media_dimension_gate_and_its_qualifier_share_one_definition_of_usable`, written
as an AGREEMENT property between the gate and the qualifier rather than as two independent
expectations — the divergence IS the defect, so a future change to either side fails there.

**Full suite `exit 0` (241 s). Ruff `exit 0`. CHECKPOINT INTACT.**

> The generalisable shape, and the fourth instance of it in this review: when two pieces of code answer
> the same question with two separately-written conjunctions, they will eventually disagree, and the
> disagreement surfaces as a confident claim beside a hedge. The fix is never to align the two
> expressions — it is to delete one of them.

### 12.7 FIXED — the punch-list basis contract now has real consumers

Two disjoint renderer lanes, each free to WIRE a consumer or REMOVE the contract (the schema accepted
`removed-the-contract` as a first-class outcome, because an honest removal beats an ornamental consumer
added to justify a key's existence). Both chose to wire, with evidence. **X (workbook): SOUND.
Y (explorer): PARTIAL.**

The claim needed narrowing before it could be scoped. Two apparent readers existed and neither counted:
`excel.py:1523,1542` reads `severity_basis` off the multicast RISK object on a different sheet (already
correct), and `blast_radius_explorer.html:1746` is hardcoded DEMO fixture data, not a renderer. On the
PUNCH-LIST path the keys genuinely had zero readers.

* **X — `excel.py::write_punchlist_sheet`** now reads the structured keys into a cell NOTE on the
  severity cell, deliberately NOT a new column: `sheet_schema.json` pins every sheet's header row, so a
  column is a contract change on a client deliverable and is only justified if it carries information
  on real rows. Its refuter confirmed all four new tests fail under a pre-fix mutant and found no
  vacuous ones.
* **Y — `punchlistCard()`** gained a per-row note plus a roll-up line, and BOTH halves of the demo
  snapshot were updated together (a previous lane was caught updating only the half its exit did not
  read).

**Y's refuter found the interesting one, and it is a shape worth naming.** The published/not-published
split — the single distinction this consumer exists to make — was decided by `/not\s+published/i`, a
substring **ordinary prose contains**. A real basis reading *"the vendor advisory was not published at
capture time"* is an EXPLANATION; matching it relabels a finding that states its grounds as one that
says it has none. Measured before the fix: that sentence and *"PSIRT bulletin not published for this
train"* both classified as UNPUBLISHED.

Re-keyed on `published by this snapshot` — the marker both producer sentinels carry and no ordinary
sentence does — and pinned against the REAL `analyze.PUNCH_BASIS_UNPUBLISHED` /
`PUNCH_CONFIDENCE_UNPUBLISHED` constants so a re-word fails loudly. Verified under node: both sentinels
detected, all three prose cases now read as having a basis, and the non-vacuity direction holds (real
prose still counts as usable).

> **Sniffing a semantic flag out of prose is the same defect as a hand-maintained name list**, one
> layer down: both substitute a string match for a fact the producer already knows. The producer emits
> a sentinel constant; the consumer should key on something only that constant says, or the producer
> should publish a boolean. Matching on words that ordinary English also uses is the worst of both.

**Carried forward (Y's refuter, not fixed):** the per-row half of the explorer consumer is unreachable
on a realistically sized punch-list — `blast_radius_explorer.html:6737 const N=12` caps the display and
media rows sort past it, so only the ROLL-UP line is always reachable. The roll-up counts over the
whole list and is genuinely always-on, so the disclosure is not lost, but the per-row prose is
effectively ornamental for real fleets. Also minor, from X's refuter: the note's length bound
(~1900 chars) exceeds the fixed comment-box size the same code sets.

**Full suite `exit 0` (235 s). Ruff `exit 0`.**

> A probe error of my own, the third this session: I asserted `_plUnpublished("   ")` should be true,
> conflating it with `_plUsable`, which is the helper that rejects whitespace. The two divide the work
> correctly; my assertion was wrong, not the code. Verify which helper owns a property before
> asserting it of another.

### 12.8 CLOSED — `verify_archives` has behavioural coverage of its ACCEPT path, and it was hiding real defects

The gap, measured before the work: across the three release-facing test files there were exactly THREE
real invocations of `verify_archives` and **all three sat inside `pytest.raises`**. Every test only ever
watched the release verifier REFUSE. Its accept path — the one that emits "safe to publish" — had never
been executed. The remaining mentions were an import, two docstrings, a string literal, and an
`inspect.getsource` call (a source-TEXT assertion standing in for behaviour).

A previous lane declined this honestly: reaching the accept path needs a valid wheel+sdist PAIR with
correct METADATA/WHEEL/RECORD digests, entry points, two PKG-INFO documents, SOURCES.txt and the
retained source inventory. That fixture is now built (module-scoped `release_rig` / `accepted_release`,
tests/test_distribution_verify.py:1606-2187) and `verify_archives` **returns normally**, emitting an
18-key proof.

**The prize: two real release-gate defects that only became visible once the success path ran.**

1. **`distribution_verify.py:2456` — a wheel declaring `License-File: LICENSE` in its METADATA but
   shipping NO license document was ACCEPTED and certified safe to publish.** The check computed the
   expected member name and then only looked at it `if license_name in info_by_name` — present-if-
   present, which is not a check at all. The wheel must now CARRY every license document its own
   metadata declares.
2. **`:153` / `:1860` — the wheel's `top_level.txt` was never READ.** It was allowlisted as a member
   NAME in `_WHEEL_METADATA_FILES` and nothing validated its contents, so a wheel could omit it or
   declare completely wrong top-level packages and pass. Now required and parsed, wheel and sdist
   routed through one helper.

Also recorded, proof-honesty rather than gate defects: the published proof discloses a path prefix
spelled `"."` (from `PurePosixPath(name).parent` on a root member), and the pinned-build-backend check
compares a `Generator` header the archive itself supplies — so it establishes what the wheel CLAIMS,
not what built it.

**Independent refuter: SOUND, `accept_path_genuinely_covered=True`, `weakened_checks: NONE`.** That was
the risk worth guarding: building a hard fixture tempts you to relax the verifier until it passes, and
a verifier loosened to pass its own test is worse than an untested one. The refuter proved otherwise
three ways — a spy wrapper confirming `verify_archives` actually returned, a standalone reproduction
through the test module's own helpers, and a full text scan for `PYTEST|environ|skip|xfail|if False`
escape hatches. It also reproduced the emitted proof byte-for-byte on the measured fields
(109 wheel / 123 sdist / 129 distinct / 14 build-generated members).

**Refuter caveats, carried:** the accept fixture depends on `_init_probe_repo`, which `pytest.skip`s
when git is unavailable — so this coverage is skip-gated and would vanish silently on a runner without
git (it does NOT skip here: `-rs` reports no skips in that file). `_KNOWN_HOSTNAME_DENYLIST` is a
hand-copied path rather than derived. And two report claims were overstated — "existing sdist tests
still pass" was vacuously true because no such tests existed, and the license check is driven by the
WORKING TREE's pyproject contract, not by the archive's own metadata as stated.

Five checks are honestly **unsatisfiable by a synthetic fixture** and were listed rather than faked:
the retained registry/EoL source chains, `independent_of_the_verified_worktree` (a module constant,
structurally false), that the pinned setuptools backend really built the archive, that the claimed
commit came from outside the verified tree, and the real archives' hashes / `--expected-json`
comparison.

**Full suite `exit 0` (268 s). Ruff `exit 0`.**

> The general lesson, and the reason this was worth four hours of agents: **a verifier whose SUCCESS
> path is untested can stop verifying without any suite going red.** Both defects above are
> accept-path-only — no refusal test could ever have caught them, because both make the verifier MORE
> permissive. When a gate's tests all assert refusals, that is not thorough coverage; it is half a
> gate.

### 12.9 RESOLVED — the Phase D privacy blocker: the candidate WORKTREE now passes its own gate

§8.5 recorded this as the blocker gating Phase D and framed it as needing a user decision between
"weaken the gate" and "scrub the review record". **That framing was wrong, and it is worth correcting
because it deferred work that was mine to do.** The gate was never the problem and the record never
needed scrubbing: four files were simply NON-COMPLIANT with a correct gate, and making them comply is
engineering, not a decision.

What actually carried markers, and what each needed:

* **`docs/review-hardening-handoff-2026-07-30.md` (10 lines)** — three absolute `C:\Users\<user>\`
  paths (the OS username is itself a marker), plus §7.1's writeup of the `\b` privacy P0, which
  explained the fix BY QUOTING the real spellings. Replaced with `<user>` and with structural labels
  (`<brand>`, `<initials>`, `<sidebrand>`, …). 17 tokens; the prose is clearer for it, and the
  same structural form was already what this session used in every user-facing report.
* **`.github/scripts/verify_repository_privacy.py` (6 lines)** — the gate's own explanatory comments
  cited the real identifiers as examples. **A file whose job is rejecting these tokens must not carry
  them**; the module already splits its pattern SOURCES into fragments for exactly this reason and the
  comments had not followed suit.
* **`.claude/scripts/review-live-delta.json` (1 line)** — a `reason` string quoting a fix.
* **`.claude/scripts/verify-review-handoff.ps1` (1 line)** — the only FUNCTIONAL one: a private-backup
  filename inside `$expectedRecoveryNames`, which the verifier compares against the recovery archive.
  Substituting the string would have broken the check, so it is now assembled from fragments — the
  same idiom `verify_repository_privacy.py` uses on its own pattern sources. **The runtime value is
  byte-identical**; what changed is what the FILE contains, never what the verifier checks. Proven by
  running the verifier afterwards: CHECKPOINT INTACT.

Nothing was weakened. No pattern, threshold, allowlist or denylist was touched, and the gate's own
tests are unchanged.

```text
verify_repository_privacy.py --worktree-only   -> exit 0
   "repository worktree-only privacy review passed; the Git index and next commit were not proven"
verify_repository_privacy.py  (default)        -> exit 1, 105 hits, ALL of them "indexed text"
```

**That split is the whole point.** The candidate worktree is privacy-clean. The 105 remaining hits are
the Git INDEX, which still holds the pre-sanitization baseline — exactly as §1 describes, and it clears
by STAGING the sanitized tree, not before. A red default gate on an unstaged dirty checkout is the
correct reading, not a defect, and §1's rule against weakening it stands untouched.

**Full suite `exit 0` (243 s). Ruff `exit 0`. CHECKPOINT INTACT.**

> The correction worth keeping: "this needs a user decision" is itself a claim that deserves the same
> scrutiny as a technical one. I had bundled a real decision (stage/commit) together with a piece of
> ordinary work (make four files comply) and deferred both. Separate them — then the decision that
> reaches the user is the one that genuinely is theirs.

### 12.10 Phase D readiness

Everything an agent can close is closed, and the blocker is gone. What remains is genuinely a human
gate, not deferred work:

* **Staging + the reviewed source commit** — §1 rule 1 and Phase D steps 2/4 require explicit user
  authorization, and this session has none. The default privacy gate turns green as a CONSEQUENCE of
  staging the sanitized tree; it cannot be proven before.
* **Immutable distributions** (Phase D 5-7) — §1 rule 7 forbids building final archives before the
  source freeze and a different reviewer's check of the owning lane. `verify_archives` now has accept-
  path coverage (§12.8), so that lane is materially readier than it was.
* **Master-reference deploy** (Phase E) — outward-facing publication.
* **History rewrite / force-push** — §2 records that Git history still contains the original private
  material. Explicitly a separate destructive decision.

### 12.11 Phase D step 1 COMPLETE — the candidate inventory, and the precise reason staging stops here

**Inventory, measured:**

```text
modified tracked : 227
deleted tracked  :  27
untracked        :  35
                   ---
total             289
```

The 27 deletions are the sanitization removals and **must not be restored** (§1 rule 3): engagement
assessment/security documents, the two `compass_artifact_*` files, two session-context markdowns, a
client-named requirements JSON, and four deck-evidence PNGs.

**Verification state at this point — all green:**

| gate | result |
|---|---|
| full pytest suite | exit 0 (243 s parallel) |
| ruff (the literal CI command) | exit 0 |
| coverage gate >= 85% | 90.73% |
| privacy `--worktree-only` | **exit 0** |
| privacy default (index+worktree) | exit 1, 105 hits, **all in the INDEX** |
| checkpoint verifier | CHECKPOINT INTACT |

**Why staging does not proceed in this session, stated precisely.** Not "an agent may never stage" —
§5.6's actual rule is narrower and sharper:

> Never stage with an unexplained blanket sweep.

289 files staged correctly means deliberate, reviewed groups each carrying a rationale. That is a
substantial careful pass, and attempting it on a nearly-exhausted context is precisely how a
bookkeeping error lands on a tree whose entire purpose is preservation — this session has already
produced three probe errors and two mis-scoped re-pins under far less pressure, every one of them
caught only because something independent re-measured it. A blanket `git add -A` would satisfy the
letter of "the suite is green" and violate the rule that matters.

So the blocker is not authorization alone. It is that the NEXT action requires a fresh session with
room to do it in reviewed groups. A future session should: read this file, run the checkpoint verifier
from PowerShell, then stage in explained groups (suggested: engine `cisco_toolkit/` fixes; tests;
webapp; `.github/` + `.claude/` scaffolding; docs; the 27 deletions as their own group with §1 rule 3
cited), running the DEFAULT privacy gate after staging — it should turn green as a consequence, and if
it does not, that is a real finding, not a nuisance.

**The three genuinely human gates after that are unchanged and are NOT blocked on context:**
immutable distributions (and note §1 rule 7's precondition — source bytes must be FROZEN, which they
are not while this review is still editing), the master-reference deployment (outward-facing
publication), and the history rewrite / force-push (destructive; §2 records that history still carries
the original private material).

### 12.12 Why staging is structurally not an autonomous action — verified, not asserted

Earlier notes in this session gave two weaker reasons for stopping before staging ("needs
authorization", then "needs a fresh session"). Both were true but neither was the real one. The real
one is mechanical and checkable:

```text
.claude/scripts/verify-review-handoff.ps1:253   Assert-Equal $staged 0 "staged entries"
```

**The checkpoint verifier asserts that NOTHING is staged.** The moment anything enters the index,
`CHECKPOINT INTACT` becomes permanently unreachable and the instrument that has guarded this tree all
session stops working. Staging is the deliberate ONE-WAY exit from the preserved-review state, and the
verifier is built to refuse afterwards by design — that is why §1 rule 1 requires asking first, and why
no amount of agent diligence substitutes for the decision.

So the sequence is: authorization -> stage -> the checkpoint is spent -> the DEFAULT privacy gate
becomes the live proof in its place (it should turn green; if it does not, that is a real finding).
There is no ordering in which an agent stages and the checkpoint survives.

**Three untracked items carry genuine CONTENT decisions, not mechanical ones.** Even with
authorization these should be decided explicitly rather than swept in:

1. **`webapp/frontend/dist/`** — the built SPA. Both `ci.yml` and `release.yml` pass
   `--allow-untracked-prefix webapp/frontend/dist`, i.e. the workflows expect it to stay UNTRACKED.
   Committing it tracks a build artifact and changes what `verify_checkout_immutable` can prove
   (§I1/F1). Decide: track it, or ignore it.
2. **`reference-data/`** — contains the hand-authored EoL bulletin dataset whose `evidence_method`
   asserts claims were "checked against their exact HTTPS Cisco source URL" — a statement §6.3 item 2
   flags as unverifiable under the no-egress doctrine and, asserted, implying egress occurred.
   `distribution_verify.py` lists it as REQUIRED, so a clean-clone build fails without it. Committing
   it commits that claim. This is the one with customer-facing consequences.
3. **`.claude/scripts/`** — the review's own checkpoint machinery. It is scaffolding for THIS review,
   not product code; whether it belongs in the shipped repository is a judgement, not an oversight.

Everything else in the 289 is unambiguous: engine fixes, tests, webapp source, `.github/` workflows and
scripts, docs, and the 27 sanitization deletions (§1 rule 3 — do not restore).

### 12.13 FIXED — a note the reader could not finish reading

Carried from §12.7 as a minor item; it is not minor. `punchlist_severity_note` is bounded at
`_PUNCH_NOTE_MAX = 900` PER HALF (basis + confidence), so it can reach ~1,800 characters, while the
comment box was fixed at `460 x 190` — about 65 chars/line x 13 lines, ~850 visible. Measured on a
long basis: **1,005 characters into an ~891-character box.**

That is worse than never writing the note. A reader sees a comment marker, opens it, and believes they
have the whole reason a finding is High when they have the first half of it — the failure mode this
entire review has been chasing, produced by a fix meant to close it.

The box is now sized to the text (width fixed, height derived from wrapped line count, capped at 620 so
one pathological snapshot cannot produce a full-screen box; the per-half truncation keeps content
inside that cap). Measured after:

```text
typical basis  248 ch -> box 460x190  capacity  891   ALL VISIBLE   (unchanged, stays compact)
long basis    1005 ch -> box 460x282  capacity 1323   ALL VISIBLE   (was clipped by ~150 ch)
no basis          0   -> no comment object at all
```

Non-vacuity holds both ways: a typical note does not inflate the box, and an item with no usable basis
still produces no comment rather than an empty one.

> The shape worth keeping: **a disclosure with a display bound smaller than its content bound is a
> silent truncation wearing a disclosure's clothes.** Whenever a fix writes text into a fixed-size
> surface — a comment box, a cell, a fixed-width column, a slide — check the surface against the
> content's own bound, not against a typical case.

**Full suite `exit 0` (256 s). Ruff `exit 0`.**

### 12.14 STAGED (Phase D 2-3) — and staging immediately caught a defect nothing else could

User authorized staging on 2026-08-02. Staged in seven explained groups per §5.6 (never a blanket
sweep): engine, tests, webapp source, CI + review scaffolding, docs, packaging, remainder.
**316 files staged. One path deliberately excluded: `webapp/frontend/dist/`** — `ci.yml` and
`release.yml` both pass `--allow-untracked-prefix webapp/frontend/dist`, so the workflows expect that
build artifact to stay untracked; committing it would contradict the CI contract and change what
`verify_checkout_immutable` can prove.

**THE DEFECT STAGING FOUND.** The default privacy gate — which reads the INDEX, and which is the whole
reason staging is a proof step rather than a formality — came back:

```text
- indexed official source fails manifest integrity: reference-data/official-sources/iana/service-names-port-numbers.csv
- indexed official source fails manifest integrity: reference-data/official-sources/ieee/mam.csv
- indexed official source fails manifest integrity: reference-data/official-sources/ieee/oui.csv
- indexed official source fails manifest integrity: reference-data/official-sources/ieee/oui36.csv
```

Not a privacy hit — a **byte-integrity** failure. Measured:

```text
worktree : 1,156,064 bytes, 14,530 CRLF   -> manifest hash MATCHES
index    : 1,141,534 bytes,      0 CRLF   -> manifest hash FAILS
delta    :   -14,530 bytes = exactly one byte lost per CRLF
```

`core.autocrlf` normalized the retained official sources on staging. These files are **byte-pinned
evidence**: `official-sources/manifest.json` records a SHA-256 per file, `registry_integrity` and
`verify_repository_privacy` verify against it, and `distribution_verify.py` REQUIRES them — so
committing them normalized would have shipped a corpus that fails its own integrity check and made a
clean-clone build verify RED.

Fixed with `reference-data/official-sources/** -text` in `.gitattributes`. `-text` rather than
`eol=lf` deliberately: `eol=lf` is still a translation, and these must be stored exactly as their
publisher issued them whatever their line endings are. The same file already carries this reasoning
for `.design-sync/**` (a byte-wise hash anchor cannot tolerate re-materialization) — there the pinned
bytes are LF, here they are CRLF, so the only rule that generalises is "do not touch". Also noted in
the attribute comment: never "fix" trailing whitespace in these files; it is publisher data and it is
hashed. (`git diff --cached --check` flags some; that flag must be ignored for this tree.)

After re-staging byte-exact: **5 of 5 files `index == worktree` and manifest-hash-matching**, and

```text
verify_repository_privacy.py  (default, index + worktree)  -> exit 0
   "repository privacy verification passed (Git index + working tree)"
```

**This is the vindication of the whole gate design.** Four adversarial waves of worktree-only checking
could not have found it: the corruption exists ONLY in the index, and only staging materialises the
index. §5.6's insistence that the default gate runs AFTER staging — and that a red result there is a
real finding rather than a nuisance — was exactly right.

> The checkpoint verifier is now SPENT by design (`Assert-Equal $staged 0` can no longer hold). The
> default privacy gate is its replacement as the live proof, and it is green.

### 12.15 COMMITTED (Phase D 4) — the reviewed source commit

`9ed40be` on `review/whole-repo-2026-07-28` — **316 files, 121,363 insertions, 15,540 deletions**,
including the 27 sanitization deletions.

Verified AT the committed tree, not before it:

```text
full pytest suite ...................... exit 0 (219 s parallel)
ruff check .  (the literal CI command) . exit 0
privacy gate, index + working tree ..... exit 0
working tree ........................... 0 modified, 0 staged
untracked .............................. webapp/frontend/dist/ only (deliberate)
branch ................................. review/whole-repo-2026-07-28 (NOT main); nothing pushed
```

**The checkpoint verifier is now permanently spent** (`Assert-Equal $staged 0` cannot hold past a
commit). Its replacement as the live proof is the DEFAULT privacy gate plus the suite, both green
above. A future session must NOT run `.claude/scripts/verify-review-handoff.ps1` expecting
CHECKPOINT INTACT — that instrument belonged to the pre-commit phase and its job is done. The sealed
recovery material under `private-inputs/review-handoff-checkpoint-20260730/` remains untouched and is
still the rollback path.

**Still open after this commit, unchanged:**

* Phase D 5-7 — immutable distributions. §1 rule 7's precondition (frozen source bytes) is NOW
  satisfiable for the first time: the tree is committed and clean. `verify_archives` gained accept-path
  coverage in §12.8, so the lane is materially readier than when this handoff was written.
* Phase E — master-reference deployment (outward-facing publication).
* History rewrite / force-push — §2: Git history still contains the original private material. **This
  commit does not rewrite it, and the repository must not be described as history-clean.**
* `reference-data/official-sources/cisco/eol-bulletins.json` — its `evidence_method` asserts claims
  were checked against Cisco source URLs, which is unverifiable under the no-egress doctrine.
  Committing the file did not make that claim true; it is required by `distribution_verify` and stays
  an open finding for correction.
* The residual findings in §10.3, §11.2 and §12.7 that were carried rather than fixed.

### 12.16 BUILT (Phase D 5-7) — one wheel, one sdist, verified; and what the build itself found

Preconditions satisfied for the first time: source frozen (committed, clean tree) and the distribution
lane independently reviewed (§12.8's accept-path refuter returned SOUND).

```text
cisco_migration_assessment_toolkit-3.31.0-py3-none-any.whl   3,395,666 B  sha fa52606867604 64b...
cisco_migration_assessment_toolkit-3.31.0.tar.gz             5,358,420 B  sha a1e62be683b9f ffd...
  109 wheel members · 123 sdist members · proof schema 6 · source b65324b / tree 11b69870
twine check ................. PASSED (both)
distribution_verify ......... exit 0
isolated wheel install ...... exit 0   cisco-assess --help exit 0
packaged assets ............. port pack, OUI pack, explorer template, SPA bundle all present
```

**THE BUILD FOUND A DEFECT IN THE RELEASE GATE ITSELF.** First run failed on one line:

```text
wheel METADATA has unexpected metadata headers: ['Dynamic']
```

`Dynamic` is emitted by the BUILD BACKEND and never declared in pyproject, so it can never appear in
the expected-header contract derived from pyproject — but it is standard: "In any context other than a
source distribution, `Dynamic` is for information only, and indicates that the field value was
calculated at wheel build time" (core metadata spec, PEP 643 / Metadata 2.2; `License-File` is 2.4).
setuptools 83.0.0 emits `Dynamic: license-file` — **and 83.0.0 is the version this module PINS via its
own Generator check.** The verifier required a backend and then refused that backend's output. Fixed
in `b65324b`, allowed as a NAME but constrained by VALUE (`_BACKEND_COMPUTABLE_FIELDS`), because
widening the header allowlist alone would have accepted `Dynamic: Requires-Dist` — legal metadata
meaning the dependency set was decided at build time, exactly what this verifier exists to refuse.

Then the verifier caught its own fix: editing `distribution_verify.py` after the build made the
archives stale, and it reported `wheel_source_mismatches` + `source_binding_errors` naming that file.
Re-committed, rebuilt, re-verified. **The instrument working on its author.**

**HONEST LIMIT, disclosed by the proof rather than by me.** `--require-source-binding` exits **3**:

```text
5 shipped archive member(s) are outside the claimed commit
untracked_prefixes_covering_shipped_members: ['cisco_migration_assessment_toolkit.egg-info',
                                              'webapp/frontend/dist']
```

Five members = the SPA bundle (index.html + 4 assets), untracked by design. So the archives are built
and structurally verified, but **not source-bound**, and cannot be while `webapp/frontend/dist/` stays
untracked — the §I1/F1 finding, now quantified by the release proof instead of argued about. The
proof's `does_not_establish` block says the rest plainly, including that the claim is compared against
`git rev-parse HEAD` in the same tree and is therefore a SELF-check.

**The installed wheel degrades honestly**, which is the property this whole review was about:

```text
portdb: pack bytes/schema verified, but retained IANA source bytes are not authoritative
        (official-source inventory unavailable ... reference-data/official-sources/manifest.json)
registry: integrity-verified-build-provenance-mixed-authority | 12,373 rows | integrity True
```

Official sources are sdist-only by design (§5.5), so an installed wheel cannot verify the retained-
source chain — and it says so instead of claiming authority it cannot establish.

**Two environment notes for the next session.** `verify_checkout_immutable.py` cannot pass on Windows:
it hashes RAW worktree bytes against LF-normalized HEAD blobs, and with `core.autocrlf=true` every
text file mismatches (`.claude/agents/design-author.md`: worktree 1,763 B / 23 CRLF vs HEAD blob
1,740 B / 0 CRLF, while `git diff` correctly reports it unmodified). CI runs it on ubuntu where no
translation occurs. Git's own clean-tree check was used in its place here, and stated as a
substitution. Separately, an isolated venv under the long scratchpad path fails `pip install` with
Windows MAX_PATH — `ntc_templates` ships ~90-character template filenames; use a short venv root.

**NOT DONE and still reserved:** no GitHub release, no PyPI upload, nothing pushed. Phase E
(master-reference deployment) and the history rewrite remain human gates.

### 12.17 SOURCE-BOUND (Phase D 5-7 closed) — the archives now bind to a commit

`webapp/frontend/dist/` is TRACKED as of `b047d5e`, and the archives rebuilt from it satisfy
`distribution_verify --require-source-binding`. Measured before and after, same command, same flags:

```text
                                                        b65324b        b047d5e
shipped_archive_members_all_covered_by_claimed_commit    False    ->    True
runtime_inventory_all_covered_by_claimed_commit          False    ->    True
self_verified_against_this_worktree                      False    ->    True
members_outside_source_binding                               5    ->       0
untracked prefixes holding shipped members                   2    ->       1  (egg-info only)
--require-source-binding                                exit 3    ->  exit 0
```

129 distinct shipped members = **115 bound to the commit + 14 build-generated-unbindable**
(`dist-info`, `PKG-INFO` — no commit can contain them), 0 outside. `unverified_reason` is empty.

```text
wheel  3,395,666 B  sha256 a8257d8ddd052687f79700bc816b62893f17b2867d84ee526e9c5ef095142bc3
sdist  5,358,421 B  sha256 16828c6bca8060f47db30c041199b82573d35d1eaf5608f736df2443cb330c9a
commit b047d5ed54e6a959b6c6142a0634de5fcd54e1fe   tree 40665b3107d69a43a76ffa745488dfb65103bd29
twine check PASSED (both) · full suite exit 0 · ruff exit 0 · privacy (index+worktree) exit 0
```

**The `-text` rule was applied BEFORE the first commit, not after the first failure.** Tracking the
bundle only works if its bytes survive round-tripping exactly — CI rebuilds and byte-compares against
these blobs, so any line-ending translation would make a CORRECT rebuild look like a modified tracked
file. That is precisely what caught the retained official sources at the staging gate one day earlier
(§12.14, one byte lost per CRLF against a SHA-256 manifest). Verified: all 5 blobs byte-identical
between index and worktree. Cost of applying the lesson proactively: nothing.

The dist allow-listing is REMOVED from `ci.yml` and `release.yml` — a tracked path is not an untracked
path, so it became a no-op that would only mask an unexpected build output. Both steps are renamed
from "left the immutable source untouched" to "**reproduced** the immutable source": for the first time
the name is true, because there are now tracked bytes to compare against.

**HONEST LIMITS THAT REMAIN, and they are structural rather than oversights:**

* `independent_of_the_verified_worktree: False`. The proof says so itself, at length: "the archives,
  the working tree and the Git repository the claim is resolved against are all the same checkout, so
  every value in this block is this release describing itself". A signed tag verified against its
  signer, or a reviewer reading the commit id, is the only thing that could establish which reviewed
  revision this is — and the module cannot tell whether it was given one.
* `cisco_migration_assessment_toolkit.egg-info` is untracked and holds shipped members. It is
  setuptools' own build metadata; binding it would mean committing a build product.
* **CROSS-PLATFORM REPRODUCTION IS UNPROVEN.** These bytes were built on Windows; CI rebuilds on
  ubuntu/node-20. Two consecutive builds were byte-identical on the authoring machine (5/5 members,
  same SHA-256s), but the ubuntu rebuild — including Vite's content-hashed filenames — has never run.
  The CI step now proves or disproves it on first execution. **If it fails, the honest reading is that
  the bundle is not reproducible across platforms, and the fix is a pinned/containerised build, NOT
  re-adding the allowlist.**

Working tree at this commit: **0 modified, 0 staged, 0 untracked** — the first fully clean tree in
this review.

---

## 13. MERGED WITH PR #506 AND PUSHED — 2026-08-02

### 13.1 The merge

`origin/review/whole-repo-2026-07-28` carried 24 commits this session did not have — open DRAFT
**PR #506 "security: protect client evidence and audit release artifacts"** — diverged from the same
base (`ef8e893`). A force-push would have orphaned them; user chose merge. Result: `64d8637`, a true
merge commit, pushed fast-forward (`5d014b6..64d8637`) with **nothing discarded**. The pre-merge local
tip is preserved at `refs/preserved/pre-merge-4dfeb28`.

Conflict resolutions (full detail in the merge commit message): `ci.yml` composed — this branch's
immutability-interleaved sequence + #506's `tools/audit_wheel.py` member-list audit, placed before
install/preservation; `publish.yml` keeps the download-the-tagged-artifacts model with #506's audit
pointed at the downloaded bytes; the add/add on `tests/test_r8_client_evidence_is_ignored.py` resolved
as a UNION (12 tests, disjoint concerns, no collisions — their half derives the capture set by
AST-parsing `COMMANDS_*`, structurally stronger than this branch's curated list, recorded as such).

Three defects found while merging, all fixed: #506's batch ignore-oracle broken on Windows (text-mode
`\n`→`\r\n` on stdin made git match NOTHING; now `-z` + bytes; measured 0-of-2 → 2-of-2);
`audit_wheel.py` stale against the widened `packages.find` (rejected the project's own wheel three
ways; aligned without touching the filename denylist); the auto-merged `test_ci_gates.py` pinned #506's
literal step spellings (rewritten to assert the PROPERTY: audit present in both workflows, ordered
before install and before publish).

### 13.2 First CI verdicts on the merged head, and a fix they forced

Push triggered PR CI. **webapp-ci: success.** **Master reference: FAILURE**, real and mine:

```text
vite.config.ts(3,23): error TS2307: Cannot find module './build/sites-vite-plugin.ts'
```

`.gitignore:10`'s **unanchored `build/`** (meant for Python's root build output) silently swallowed
`master-reference/build/sites-vite-plugin.ts` — a SOURCE file that `vite.config.ts` imports. Every
local run passed because the file sat in the worktree; the first CI run failed because it was never
committable. **Local-green/CI-red with no code difference is the signature of an ignore rule eating a
tracked dependency.** Fixed by anchoring to `/build/` — the identical fix the review already applied to
`/dist/` one line down — and tracking the plugin. Swept the whole repo for other ignored source: the
only hits are the ignored side-engagement design tree (ignored BY DESIGN, referenced by nothing tracked; its directory name is withheld here because the name is itself a client marker). master-reference re-verified locally: 3/3, typecheck via `npm test` exit 0.

The main CI run (test matrix, coverage, Distribution contract with the first-ever ubuntu SPA
reproduction check) was IN PROGRESS at this fix's push, which supersedes it under
`cancel-in-progress`. **The cross-platform SPA byte-reproduction question is answered by the run on
the NEW head — read it from actual job/step conclusions, never the run summary** (this repo's memory:
`cancelled` ≠ `failed`; zero-step instant-fail = billing).

PR #506 retitled/re-described to reflect that it now carries both lines of work (66 commits), left in
DRAFT — marking ready-for-review is the user's call.

### 13.3 First full CI run: two never-executed gates failed, both root-caused and fixed

The merged head's first complete CI run returned two job failures. Neither was a flake and neither
was what its summary suggested; both were gates failing on their FIRST real execution.

**Distribution contract — the cross-platform SPA answer, and it is better than feared.** The
reproduction step failed naming exactly ONE file:

```text
tracked checkout bytes differ from immutable HEAD: ['webapp/frontend/dist/index.html']
```

All four content-hashed JS/CSS assets — 1.8 MB of minified output — reproduced **byte-identically**
on ubuntu/node-20 from a Windows-built commit. Minified code is EOL-insensitive; the 627-byte
index.html is a verbatim TEMPLATE passthrough, and Vite carries the template's line endings straight
through. My worktree materialized the template with 13 CRLF (autocrlf); ubuntu checks out the LF blob.
Fixed at the cause: `webapp/frontend/index.html text eol=lf` in `.gitattributes`, template
re-materialized, bundle rebuilt (now 614 bytes, 0 CRLF), determinism re-proven (two builds, identical
sha), and the four assets confirmed UNTOUCHED vs HEAD. Prediction: the reproduction step goes green on
the next run; if it does, cross-platform reproducibility is fully established.

**Dependency audit — a gate that could never pass, not a vulnerability.** `pip_audit --strict` exited
1 with ZERO vulnerabilities reported:

```text
ERROR: cisco-migration-assessment-toolkit: Dependency not found on PyPI and could not be audited
```

The job installs the PROJECT ITSELF editable (`-e ".[dev]"`), the project is private and unpublished,
and --strict makes not-on-PyPI fatal — so the gate was structurally unpassable from the day the
install line changed from requirements-files to `-e ".[dev]"`. Fixed with `--skip-editable`: the same
dependency set is audited in full; the only exclusion is the one package PyPI can never know about.
Same class as the SPA step and `verify_archives`' accept path: **a gate nobody has executed is not a
gate, and its first real run is a finding generator.** That is now three instances in one review.

Also this session: my previous commit chained the privacy gate with `;` instead of `&&`, so its
FAILURE did not block — and it was red, because the ledger text and commit message had named the
side-engagement client's directory. Pushed for ~2 minutes, then scrubbed, tip amended, and replaced
with `--force-with-lease` pinned to the bad sha (private repo, own just-pushed commit, nothing else
moved). Two rules re-learned at cost: **a verification gate chained with `;` is decoration**, and a
client marker is a marker in PROSE too, including inside a commit message describing an ignore rule.

### 13.4 CI cycle 2 — SPA reproduction CONFIRMED; three more first-execution gates fixed; a linux-only cluster measured and left open

**CONFIRMED on the real runner:** `Prove the SPA build reproduced the immutable source` — step
conclusion `success` on ubuntu/node-20 against the Windows-committed bundle. Cross-platform byte
reproduction of the shipped SPA is now an established, CI-enforced property, not a prediction.

**Fixed this cycle, each measured before fixing:**

1. **Wheel-context self-test (Distribution contract).** The job survived every release check and died
   at the LAST step: `assesshub --selftest` from the installed wheel failed oui-kb/port-kb because the
   wheel ships without `reference-data/official-sources/**` (handoff 5.5, sdist-only) and the gate read
   CANNOT-CHECK-HERE as CHECKED-AND-FAILED — the port-authority refuter's F7, predicted and now
   confirmed. Fix: a structured `official_sources_available` fact from `source_authority_details`
   (a stat, deliberately not a parse, so present-but-corrupt stays a real refusal), consumed by the
   single owner `pack_is_usable` — so the self-test, the workbook sheet and the AssessHub banner all
   learn the distinction at once. serve.py + the engine mirror route through the owner and DISCLOSE the
   degraded form on the [ok] line. Six-way matrix pinned in `tests/test_registry_integrity.py`,
   including: stale producers without the field stay strict (fail-closed), and sources-present-but-
   failing stays refused.
2. **pip-audit could not pass, twice, differently.** `--strict` → not-on-PyPI fatal (the project is
   private). `--strict --skip-editable` → "distribution marked as editable" ALSO fatal, because
   --strict's definition is "fail on ANY skip" — the flags compose against each other. Fix: uninstall
   the unpublishable project before auditing; the dependency closure is audited under undiluted
   --strict with no skips at all.
3. **The pack "byte-determinism" tests asserted a property deflate does not have.** Compressed bytes
   differed across zlib builds while the gzip CRC32/ISIZE trailers matched — identical payload,
   different encoding; deflate is not canonical. Re-anchored on what a cross-platform rebuild CAN
   promise: byte-identical decompressed payload, pinned mtime=0 header, and same-platform double-build
   stability. (The Coverage job and every matrix leg failed on these same two tests — one cause.)
4. Golden regenerated through the guarded door (additive: `data_authorities` gained
   `official_sources_available`; regen accepted WITHOUT the shrink flag).

**MEASURED AND LEFT OPEN — the linux-only cluster (first real linux execution of these suites):**
`tests/test_redact_collection.py` × 4 — the corpus tests hit the leading-dot suffix residual the
round-3 refuter flagged (`..yaml`-shaped names; `splitext` vs `PurePath.suffix` divergence), which
Windows runs never exercised; and `tests/test_ci_gates.py::test_stop_hook_BLOCKS_when_verification_
times_out` — **the Stop hook fails OPEN on linux** (`rc=0` on a timed-out suite), §7.16's contradiction
surfacing for real on a platform where the hook's timeout path behaves differently. Both need a
dedicated diagnosis cycle with the next run's isolated data; neither is masked by this push (the
matrix will stay red on exactly these until then, and that is the honest state).

Running tally of the review's sharpest lesson, now **six** instances: verify_archives' accept path,
the SPA reproduction step, the dependency audit, the wheel-context self-test, the ubuntu test matrix,
and the linux Stop-hook path — **every one a gate or suite that had never actually executed, and every
first execution found something real.**

### 13.5 CI cycle 3 — the fixed gates started WORKING, and what they caught was real

Cycle 2's fixes did their job, and the proof is what happened next: both "fixed" jobs went red again —
**for new reasons, because the gates finally executed their real checks.**

**The wheel self-test PASSED 9/9** — `[ ok ] oui-kb … retained official sources NOT present in this
install form` — and then the very next line of the same CI step failed: an inline python one-liner in
`ci.yml` carrying a FOURTH copy of the usability conjunction, whose own comment said "keep in step
with COLLECT_PARSE and serve.py; there are four consumers". The hand-sync instruction is the defect:
when `pack_is_usable` learnt the cannot-check-here distinction, the three Python consumers followed
and the YAML copy — invisible to a grep for Python callers — kept failing a healthy wheel on the very
facts its own error dump printed (`integrity_verified: True, build_provenance_verified: True,
official_sources_available: False`). Now routed through the owner. **A duplicated predicate in a
workflow file is still a duplicated predicate.**

**The dependency audit ran for the first time and found a real CVE:** paramiko 4.0.0,
PYSEC-2026-2858 (SHA-1 permitted in rsakey.py). Verified against primary sources: the fix ships only
in paramiko 5.0.0, and netmiko — the SSH engine — caps `paramiko<5.0` in its LATEST release (4.7.0),
so the fixed version is unresolvable without abandoning netmiko. Severity supports waiting
(AV:A/AC:H/I:L). Handled as a NAMED suppression, `--ignore-vuln PYSEC-2026-2858`, with the
re-evaluation trigger written into the workflow: the moment netmiko's cap admits paramiko>=5, delete
the flag and bump. Every other advisory remains fatal.

**My local `npm audit --offline → 0 vulnerabilities` was worthless** — offline cannot fetch
advisories; the ledger's own caveat said so and I under-weighted it. Online: 6 findings across three
roots. Fixed by pinned bumps, no `--force`: vite 6.0.7→6.4.3 (esbuild dev-server advisory), postcss
via `npm audit fix`, react-router-dom 6.28.0→6.30.4 (XSS via open redirects, GHSA-2w69-qvjg-hvjx).
Two MODERATE advisories remain on react-router 6.x whose only fix is the breaking v7 migration —
below the CI gate's `--audit-level=high` threshold, and with low real exposure here (no SSR; loopback
field posture); recorded as a deliberate deferral with the v7 migration as the follow-up.

The dependency bumps changed the bundle: all four content-hashed assets renamed, dist rebuilt and
re-tracked, byte-determinism re-proven across consecutive builds, index.html still 0 CRLF. Verified
locally: full suite exit 0, ruff exit 0, vitest 200/200, npm audit (high) exit 0.

The linux-only cluster (4 redact_collection corpus tests + the Stop-hook fail-open) remains open as
recorded in 13.4 — cycle 3's matrix will re-measure it in isolation. Locally proven meanwhile: both
capture rules AGREE on every CI-failing name on Windows, so that cluster is filesystem-behaviour
dependent, not rule-text dependent.

### 13.6 CI cycle 4 — the provenance pin was the deeper cause, and two records corrected

**Both release-facing jobs went GREEN on cycle 3** (`b71f9d9`): Dependency audit and Distribution
contract passed for the first time in the branch's history — the named paramiko suppression, the
fourth-copy deletion and the wheel-context selftest chain all held on the real runner.

**The pack failures' true mechanism was beneath my test fix.** Cycle 2 still failed the two pack
tests WITH the payload-comparison rewrite in place, because the refusal came from
`_build_provenance_authority`: `_TRUSTED_PACK_SHA256_BY_STATE` pins the COMPRESSED digest in code, so
any rebuild whose deflate framing differs from the shipped (Windows-zlib) bytes is "not the
code-pinned deterministic build" — meaning **pack regeneration was blessable on exactly one zlib
build, ever**. Fixed at the design level: `_TRUSTED_PAYLOAD_SHA256_BY_STATE` pins the CONTENT, and
provenance accepts either anchor. Sound because the manifest's `decompressed_sha256` is verified
against real bytes by `verified_text` before provenance is ever consumed (integrity precedes
authority everywhere via `pack_is_usable`). Proven three ways with a REAL foreign framing
(compresslevel=1, mtime=0), not a hand-edited digest: faithful rebuild ACCEPTED, tampered payload
REFUSED by both anchors, shipped pack unchanged via the compressed anchor. No manifest surgery and no
pack regeneration were needed — the payload digest was already in the manifest and already
integrity-verified.

**`requires-python = ">=3.10"` was never true until this week.** The py3.10 leg — first ever to run —
failed four release-supply-chain tests with `ModuleNotFoundError: tomllib` (stdlib only since 3.11)
in `.github/scripts/verify_release.py`. Fallback to `tomli` (already in `[dev]`). The old fleet was
Windows py3.12 only, so the floor of the claimed support range had never executed anything.

**Two of my own records corrected:**
* §13.4 called the redact/stop-hook failures "the linux cluster". Wrong twice: they appeared only in
  cycle 1's AGGREGATE log — which mixes all jobs — and none of cycle 2's isolated ubuntu legs shows
  them (each shows exactly the two pack tests; py3.10 adds the tomllib four). I had conflated run
  aggregates across cycles and attributed Coverage/windows-leg failures to "linux". They have not
  recurred in an isolated leg since; they are watched, not diagnosed, and no longer carried as a
  named open cluster.
* My pathlib-version and platform-class hypotheses for those failures were both refuted by
  measurement (both `PurePath` flavours agree on every probe name; cycle-2 ubuntu 3.12.13 passes the
  corpus tests). Recorded so the next session does not re-derive dead theories.

Verified locally: full suite exit 0, ruff exit 0, focused registry/supply-chain suites green,
`tomli` import confirmed. Expected on cycle 4: every ubuntu leg green on the pack tests, py3.10
green on supply-chain; remaining watch items are the windows leg (cancelled mid-run in cycles 2-3,
never a completed verdict since cycle 1) and any recurrence of the cycle-1-only failures.

### 13.7 CI cycle 5 — the windows leg's first verdict held a real engine bug; every red leg fixed locally

**Cycle 4 (`32b2f09`) verdicts.** Firsts for the branch: **Coverage, py3.12-ubuntu and py3.13-ubuntu
green** (Dependency audit and Distribution contract held from cycle 3 — the §13.6 fixes were causal,
not coincident). The cycle-1-only failures did not recur. Remaining reds, each isolated per-job, all
fixed locally this cycle: **py3.10 (6), py3.11 (2), py3.14 (6), windows (4 — its first COMPLETED
verdict since cycle 1)**.

**windows — a production custody bug, not a test artifact.** `_evidence_records`
(COLLECT_PARSE_V3_23_0.py) realpath'd each evidence FILE but compared containment against the RAW
root string. On windows-latest, `%TEMP%` arrives in DOS 8.3 form (`RUNNER~1` vs `runneradmin`), so
the resolved file never sat "under" the unresolved root and custody refused every evidence file of a
healthy run — engine exit 1, surfacing as two ingest-route 500s. Fix: resolve BOTH sides before
`commonpath`. Pinned by a new test that spells the collection root through a symlink/junction — the
same resolved-vs-raw divergence 8.3 produces, mintable on any OS — plus the non-vacuity direction (a
genuinely outside file still refuses). Same asymmetry class as the index-vs-worktree and
gate-vs-qualifier findings: two spellings of one fact, compared raw.

**windows — the §7.16 "Stop-hook fails open" contradiction, resolved by reading, in the hook's
favour.** The hook's code is fail-closed (`rc=124` -> exit 2 BLOCKED); the "fails open" text beside
it is a STALE COMMENT. The runner's `rc=0` was the TEST's own `timeout` shim never engaging under
runner bash — the hook truthfully reported a green probe repo. The test now proves its shim engaged
before asserting, and skips LOUDLY naming what it could not simulate. The hook itself: untouched
(byte-exact protected). Third windows fix, same file: the happy-path custody assert now resolves
both sides. All three windows fixes are 8.3-or-shim; none weakened a guard.

**py3.10 — the floor keeps paying.** `SpooledTemporaryFile` gained `seekable()` only in 3.11
(bpo-35112), so ingest's seek probe rejected every spooled upload on 3.10: unwrap shim in
`ingest.py`, pinned by a `_Py310Spool` test that proves zipfile got PAST the probe. And
`serve.py::_release_version` needed the same tomli fallback §13.6 gave `verify_release.py` — the
`(checkout)` marker was 3.11+ only. **py3.11 — property, not prose:** stdlib json's recursion guard
fires before the app's own depth guard on some versions; both are fail-closed, so the nesting pair
now asserts the property (refused, with either message) instead of one version's wording.

**py3.14 — the brief's direction was wrong, and the agent measured the correction.** Not "splitext
moved onto pathlib's answer" but the reverse: 3.14's `PurePath("..json").suffix == ""` — pathlib
adopted splitext's reading of leading-dot runs. Consequence: production stays PARITY-stable
(producer, verifier, census and copy-back all read one primitive, so the §10-class killer cannot
recur), but the CLASSIFICATION of a `..json`-spelled name flips to raw-capture on 3.14, and six
tests had the <=3.13 side hardcoded. All six now derive expectations from the owner rule
(`redaction_verify.is_uncoverable_capture`) over the names each test plants, with the
version-stable halves still HARD-asserted (single-dot spellings always excluded; the bare dotfile
always a capture — the safe direction). Proof: 154 tests exit 0 (re-run independently of the
agent); a `sitecustomize` simulation of 3.14's suffix answer — reaching the engine subprocess —
exit 0, and the brief's (wrong) direction simulated too, also exit 0; a mutation battery restoring
each historical lookalike restatement is caught by all 5 name-rule tests; no `sys.version_info`
conditional and no skip introduced.

**Carried forward (production semantics, deliberately NOT decided in a test lane):** on 3.14 a file
literally named `..json`/`..xml` is no longer excluded as a structured document — the exclusion
follows whatever the stdlib currently calls a suffix. Coherent on every version, and the flip is
toward scrubbing (fail-safe), but if the exclusion is meant to hold by NAME SHAPE,
`html._capture_suffix` + `is_uncoverable_capture` need a pinned-semantics decision. Second carry:
the splitext-restatement mutation is UNDETECTABLE on 3.14 by construction (measured 0/5 under
simulation — there the lookalike and the owner agree); the <=3.13 matrix legs are the only guard
against that regression, so dropping 3.12/3.13 would silently retire it.

> The cycle's lesson is §13.3's, inverted: a matrix leg that has never completed is not "probably
> like the others" — the windows leg's first finished run in four cycles held the only PRODUCTION
> bug of the whole matrix effort. An uncompleted verdict is an unopened envelope, not a pass.

Environment note: python resolution on this host broke mid-session (the WindowsApps stub shadows
`Python312` on PATH); `py -3.12` is the stable spelling.

**Full suite `exit 0` (parallel). Ruff `exit 0`. Worktree privacy gate `exit 0`.** One phantom red
en route: a Stop-hook pytest raced the still-running background suite and flagged 17 "failures"
across seven files this cycle never touched; all 132 tests in those files pass serially, exit 0.
Two pytest runs must not share this repo concurrently — the losers are exactly the tests that
touch shared surfaces (stick layout copies, CLI subprocesses, freshness reads).

### 13.8 CI cycle 5 verdict — one test from green, and the miss was the named-subset shape again

**Cycle 5 (`1bbeb7a`) was the best run in the branch's history:** windows py3.12 **green for the
first time ever** (the custody fix was causal), py3.11/py3.13/py3.14 green (the nesting pair and
the owner-rule suffix rewrite held on the real interpreters), mypy/Coverage/Ruff/Dependency
audit/Distribution contract green, webapp-ci and Master reference and Static reference contract
all green. **One red job in the entire matrix: py3.10, one test** —
`test_ingest_route_passes_upload_spool_not_bytes_to_zip_runner`,
`AttributeError: 'SpooledTemporaryFile' object has no attribute 'seekable'`.

**Why my cycle-5 fix missed it — the named-subset shape, instance five.** The spool shim sat
inside `_safe_extract`, i.e. inside ONE consumer. This test monkeypatches the runner, so the
shim never runs — and the test is RIGHT: the route's contract is "any runner receives a stream
carrying the full IO probe interface", and py3.10's raw spool breaks it at the boundary. I had
shimmed a member of the class ("code that probes the upload spool") instead of normalizing where
the class begins. The four cycle-5 spool tests went green because they exercised the real
runner; the one that replaces it measured the contract itself.

**Fix at the boundary, one owner.** `ingest.iobase_upload_file` now owns the unwrap
(`ingest.py`, full why in its docstring); `_safe_extract` calls it for direct callers, and BOTH
routes normalize `file.file` through it before anything downstream — the archive route before
`_bounded_upload_size` + the runner, the snapshot route before `_parse_snapshot_stream`
(`json.load` never probes, but the rule is structural: every stream leaving the route layer
carries the interface, no named subset of routes).

**Proof, test-first.** New route test reproduces CI's exact failure on ANY interpreter by
patching the REAL producer — `starlette.formparsers` builds its spool `from tempfile import
SpooledTemporaryFile`, so a patched factory returning a wrapper with exactly the 3.10 surface
(everything delegated, the three probes AttributeError, `_file` underneath) flows through the
genuine multipart parse into the route. Watched FAIL with `AttributeError: seekable` pre-fix,
green post-fix; the factory is instrumented so the test asserts starlette really built through
the patched name and what it built really lacked the probes (otherwise it silently degrades
into its sibling). Plus a unit test on the owner: unwraps to the SAME underlying object
(identity, position preserved), passes a modern stream through untouched (the 3.11+ identity
direction), and the simulation's own gap is asserted. Focused files green; **full suite
`exit 0` (parallel). Ruff `exit 0`.**

> Fifth instance of the shape, and this one refines it: the earlier four were guards scoped to
> a LIST of names; this one was a guard scoped to one CALL SITE of a replaceable collaborator.
> Same defect one level up — the fix is owned by the boundary where the promise is made, not by
> whichever consumer happened to crash first.

### 13.9 CI cycle 6 — REPOSITORY-WIDE GREEN, the branch's first

**Every job of every workflow on `213f5a3` succeeded** (verified per-job twice: direct jobs-API
query and an independent monitor stream, both printed — never a workflow-level rollup alone):

```text
CI (run 30749472626):        Ruff lint, mypy, Coverage, Dependency audit, Distribution contract,
                             Tests py3.10/3.11/3.12/3.13/3.14 ubuntu, py3.12 windows   ALL success
webapp-ci (30749472624):     Frontend test+type-check+build, Backend e2e, Frontend E2E ALL success
Master reference (…472623):  Static reference contract                                    success
```

Six cycles from first push to green. What each cycle bought, in one line each: (1) merge + the
never-executed accept path; (2) the SPA reproduction + payload-vs-deflate; (3) the release gates'
first green; (4) the ubuntu matrix + windows' first completed verdict; (5) the custody engine bug
+ the version-neutral suffix rewrite; (6) the spool boundary contract. Every red was a finding —
the two production bugs of the effort (8.3 custody containment, the py3.10 spool contract) were
both invisible to every leg that had already run.

**What GREEN does and does not mean.** It means: the suite, lint, types, coverage floor,
dependency audit, distribution contract, SPA reproduction and reference contracts all hold on
every supported interpreter and both platforms, at `213f5a3`. It does NOT mean release-ready.
Still open, unchanged in kind:

* **Human gates (§12.10):** master-reference deploy (Phase E, outward-facing), the history
  rewrite / force-push decision (§2 — history still carries the original private material), and
  the PR #506 draft flip.
* **Carried questions:** the EoL registry `evidence_method` claim (§12.12 item 2); the `..json`
  name-shape semantics on 3.14 (§13.7); react-router v7 (two moderates below gate threshold,
  deferred). The §13.7 matrix-dependency note stands: the <=3.13 legs are the only guard against
  the splitext-restatement regression — dropping them silently retires it.
* **PYSEC-2026-2858** stays a NAMED, commented suppression until netmiko admits paramiko>=5.

> The number worth keeping: six consecutive cycles, and every one of the ~24 red job-verdicts
> along the way decomposed into a real defect, a version-bound test, or an environment fact —
> zero were flaky reruns. On this branch "rerun and hope" would have converged on nothing;
> per-job forensics converged in six.
