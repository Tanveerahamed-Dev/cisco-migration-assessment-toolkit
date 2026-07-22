# Session log

Append-only, one entry per working session. Newest first. This is `CHAT_SUMMARY.md`'s lightweight successor
(that file froze at 2026-06-12): a line here costs nothing and keeps the narrative queryable by graphify.
Format: `## [YYYY-MM-DD] — <headline>` + 3–6 bullets. Failures worth remembering get a `!lesson` tag.

## [2026-07-22] — Hardening the run manifest: the task's premise was false, my "fix" was a regression, and the audit record I added sealed a lie

- Task: make the sealed run manifest's write atomic, decide the overwrite policy, consider an exit
  code for gate refusals — all premised on the manifest being "the durable record of PPDIOO gate
  verdicts". It was not: `build_run_manifest` sealed only `collect`/`analyze`/`deliver`, and
  `{"stage": "gate", ...}` existed in no branch, worktree, stash or open PR. Shipped (`b8d4ec3`) is
  the durability half only — crash-safe write with a logged fallback, `.tmp` excluded from the
  sealed artifact set, overwrite policy DECIDED as a per-run seal with `manifest.py` + `docs/ssot.md`
  corrected (they claimed "append-only" unqualified), 9 tests, full suite green. The gate-verdict
  record was reverted and re-scoped onto PR #439.
- `!lesson` **`tmp + os.replace` is not a free upgrade over a truncate-write on Windows.**
  `os.replace` must DELETE its destination, so it raises `PermissionError [WinError 5]` while ANY
  process holds a handle — including an ordinary reader, because the CRT opens with
  `FILE_SHARE_READ|FILE_SHARE_WRITE`. The plain `open(path,"w")` succeeds in exactly that case
  (verified with a share-mode matrix; `FILE_SHARE_DELETE` does not save it). Real triggers: AV
  on-access scan, search indexer, a viewer left open. Fix = retry briefly (~4x100ms absorbs
  transient scanners), then fall back in-place and LOG it — never worse than before, atomic when
  the FS allows, degradation never silent. bridge-candidate
- `!lesson` **Check what the CALLER does with a write failure before "hardening" the write.** Both
  call sites wrap the write in `except Exception: logger.warning(...)`, so the new failure mode was
  swallowed: the run ships and the PREVIOUS manifest stays on disk beside freshly rewritten
  artifacts — a stale seal that still passes `verify_manifest` while every hash in it is wrong (and
  a fresh manifest can seal a stale snapshot as this run's evidence). A torn write announces
  itself; a stale seal certifies a lie. Making a write "safer" in isolation made the system less
  honest. bridge-candidate
- `!lesson` **Agreement between reviewers is not evidence when they share a blind spot.** Three
  independent refuters reviewed the change; two explicitly called the atomic-write half "sound".
  Only the third — whose assigned lens was crash-safety specifically — reproduced the regression.
  Assign at least one refuter a lens aimed squarely at the thing you are most confident about, and
  do not treat 2-of-3 corroboration as confirmation. bridge-candidate
- `!lesson` **Never re-derive a decision you can read off the decider — and distrust a test you
  wrote for the code you wrote.** My gate record inferred `disposition="overridden"` from the
  `--override-gate` flag, but `enforce()` returns True at its `if not missing` branch BEFORE the
  override branch and appends no audit line — so an override flag on an already-approved ledger
  sealed a governance breach that never happened, tamper-evidently, with no matching ledger line.
  My own test asserted that lie as correct, while the repo already pinned the true invariant one
  layer down (`test_approved_upstream_proceeds_and_override_is_inert`: "a redundant
  `--override-gate` must NOT log a phantom override"). Grep for an existing invariant before
  encoding a new one. bridge-candidate

## [2026-07-22] — Refuting my own merged code twice in one day (#429–#433): both times the verification, not the feature, was the defect

- After P3 shipped, independent refuters were pointed at code I had written AND self-verified.
  Wave 1 (boot backups, #429) found four ways the feature DESTROYED the client evidence it exists
  to protect. Wave 2 (`--redact-folder`, #432) found the verification licensing "share-safe"
  certified ~3× what it checked. Both features' happy paths were sound; the checking was not.
  Also shipped: `--redact-folder` itself (#430 — the field guide had documented a redaction
  command that could not run, because the engine needs a template + devices.json the bundle never
  carried), CLAUDE.md's first mention of Atlas + the restore procedure drilled into a test (#431),
  and a both-edges calibration test for the checker (#433).
- `!lesson` **Verify the artifact that fails FIRST, not the most convenient one.** A pipeline
  emitting many artifacts does not redact them by one mechanism: the snapshot came from a DIRECT
  call, the workbook from phases wrapped in a "log and continue" guard. I checked the snapshot —
  structurally the one artifact that CANNOT fail — and called the set verified. Fault injection
  (not reading) proved a failed phase ships real serials and private IPs in the workbook while the
  checked file stays spotless and the run exits 0. Ask which output fails first, and check that
  the transform RAN (phase ledger / logs), not only that its output looks clean. bridge-candidate
- `!lesson` **A fix to a checker needs its own adversarial pass — the failure modes are two-sided.**
  Correcting a false positive (advisory copy citing `e.g. 10.0.0.0/16`) blinded the checker to 28%
  of the data, including real evidence. Correcting THAT exposed a bug in the sentence splitter:
  splitting on any period severs `e.g.` from the address it introduces, so the example loses its
  exemption. A check that always fires is as useless as one that never does — pin BOTH edges
  against realistic data (here: real fixtures through the real transform, asserting no false
  positive AND a coverage floor). bridge-candidate
- `!lesson` **A success message is a safety claim; make it name its own limits.** The banner said
  "Every IP/MAC/serial is pseudonymized and this was verified" while the code matched RFC1918 IPv4
  in one file — and hostnames are kept BY DESIGN (a client FQDN survived in 9 of 15 artifacts).
  The engineer's post-run mental model, "this is anonymous", was the likeliest route to a real
  data incident — not any code path. State what was checked, what was not, and what is kept on
  purpose. bridge-candidate
- `!lesson` **Refuter output is a proposal, not a verdict — verify before fixing.** Of the reported
  findings I could not reproduce one (a journal-mixing restore) across three trials and both backup
  methods, and recorded it unverified rather than fix a phantom; two more were REFUTED by their own
  measurements (timeout headroom, orphaned children) and written down so nobody re-litigates. Their
  most severe finding, meanwhile, understated the problem — fixing it exposed a second layer
  neither reviewer saw. Adversarial review earns its keep only when its output is itself checked.
  bridge-candidate
- `!lesson` **Narrow local verification hides what the gate catches.** Ruff failed CI on an unused
  variable because my local lint targeted only the files I had touched while the job lints the
  tree; and a single-device end-to-end fixture was too thin to expose either edge of the checker
  (the repo's own golden + 23-device snapshots were). Match the gate's scope locally, and prefer
  the project's realistic fixtures over a synthetic one you sized yourself. bridge-candidate

## [2026-07-21] — Atlas P3 shipped (#426/#427) + real stick updated — and the restick exposed a 5-hour silent hang (#428)

- P3 planned from the artifact §15 row with a code-verified gap analysis (which found ADR-0004 D4's
  "AssessKit one-prompt fleet flow" was never built — `app.py` has no collection route at all, so the
  console chain IS the certified field path; deferred with the reasoning recorded rather than silently
  skipped). Two slices: boot unplug-safety (`quick_check` refusing corrupt stores non-destructively,
  rotating `data\backups\`, rollback-journal pinned, friendly write-locked-stick refusal) and the shipped
  `README-FIELD.txt` with ratchet tests. Stacked-PR order held again: retarget #427 to main BEFORE merging
  its base, delete branches last. Post-merge gate on merged main green. Bundle rebuilt, physical stick
  updated, on-stick `--selftest` PASS 9/9, client DB byte-identical throughout.
- `!lesson` **Robocopy's DEFAULTS are `/R:1000000 /W:30` — a million retries 30s apart (~347 days).**
  Paired with quiet switches (`/NFL /NDL /NJH /NJS /NP | Out-Null`) that is a *silent* hang: the stick
  update looked alive for ~5 hours having written 32.5 MB with 1.9s of CPU. Always pin small `/R` `/W` on
  any unattended copy and print which file failed. Diagnosis kit that settled slow-vs-hung in one minute:
  a `Win32_Process.WriteTransferCount` delta over 20s (0 B/s = hung, not slow); find the lock holder by
  scanning every process's **`.Modules`**, not `.Path`, because the holder has the file open as a loaded
  DLL; and note robocopy's error line prints the **source** path while the lock is on the **destination**
  (`Copy-Item`'s message named the real culprit). bridge-candidate
- `!lesson` **A portable app that auto-opens a browser hands that browser its own directory as the working
  directory** — Windows then resolves DLLs (`VCRUNTIME140.dll`) out of the app folder, and the browser's
  child processes keep them open *long after the app exits*. On removable media that blocks both update
  ("file in use") and safe-eject, with no visible culprit. Fix is documentation + fail-fast, not code:
  "close the browser too" now sits in the eject AND update sections of the field guide. bridge-candidate
- `!lesson` **Verify a packaging change in the ARTIFACT, and pick a verification signal whose *value*
  distinguishes the code under test from the installed copy.** Unit tests pinned the bundle manifest but
  could not prove the packaged app behaves; building and driving the real exe caught that a post-build
  step had never actually run (PyInstaller ≥6 buries spec `datas` under `_internal\`, where no field user
  would look). The selftest's **check count** (9 vs main's 8) was the tell that the branch's code — not
  the editable-installed one — was really bundled; a boolean pass/fail would have proven nothing.
  bridge-candidate
- `!lesson` **Three test traps, all of which made a test lie green or fail wrongly.** (a) A ratchet that
  reads a value out of a file must read it from the *invocation*, not the prose — my retry-bound test
  regexed the first `/R:\d+` and matched the number inside my own comment quoting robocopy's bad defaults,
  passing while the script hung. (b) A plain Python `open()` does NOT reproduce a Windows file lock
  (opens with full sharing) — reproducing an in-use file needs a real `msvcrt.locking` byte-range lock.
  (c) Faking SQLite corruption by stomping bytes mid-page does not fail `quick_check`: cells pack from each
  page's **tail** and the middle is free space, so damage the tails. bridge-candidate

## [2026-07-21] — Webapp motion engagement end-to-end: adversarially-verified 25-unit plan fully landed (21 PRs, #403 + #407–#423) + DS re-sync (PR #424)

- Three-day arc: grounded audit → 23-unit plan → two ceiling probes (self re-verify caught one arithmetic
  drift) → escalated adversarial round (three blind re-audits, a source-tracing mechanism refuter, a blind
  independent designer, a decomposition stress-test) → v2 with 25 units → units 1/3/16/5 implemented inline
  with real-browser verification, the other 21 via 12 background worktree agents in three waves, every diff
  personally reviewed pre-merge; combined-main gate run after every merge wave, green each time. 3D fabric
  measured 11→19-20 FPS (mesh merge 7→2 + disclosed particle cap); phase-2 InstancedMesh correctly gated
  OFF by the numbers. Atlas Design System re-synced: 19 components (3 new Skel*), motion conventions
  header, live anchor verified byte-identical post-upload.
- `!lesson` **Self-review false-ceilings; blind refuters with source access do not.** Re-verifying my own
  plan found one wrong count; fresh agents told to REFUTE (not confirm) found two real shipped bugs, a
  strictly better mechanism (keep the WebGL engine mounted-but-paused instead of cross-fading a rebuild),
  and two missing units — and a designer given only the problems, not the plan, re-derived the same core
  mechanisms independently, which is corroboration you cannot get from re-reading yourself. bridge-candidate
- `!lesson` **Two rAF-tween bug classes, both invisible to assert-stable-state tests.** (a) rAF callback
  timestamps and `performance.now()` need not share a clock origin (measured ~90 min apart under
  jsdom/vitest) — anchor a tween's start to the FIRST rAF callback's own timestamp, never a
  `performance.now()` read at setup. (b) A tween that writes its from-ref only on COMPLETION restarts from
  a stale value when retargeted mid-flight (0→100 interrupted by →50 visibly snaps to 0) — mirror the shown
  value into the ref every frame. Both hid for months because the house test convention never asserts an
  animated value. bridge-candidate
- `!lesson` **react-force-graph-3d treats a changed `nodeThreeObject` function identity as "rebuild every
  node"** — an inline closure over selection state disposes and reallocates the whole fleet's meshes on
  every click/hover; keep the factory reference-stable and mutate materials directly via `node.__threeObj`.
  Related, proven from the installed three.js source: `Raycaster` never consults `.visible` (render and
  pick are separate traversals), so invisible hit-proxies raycast fine. And measure before instancing: the
  cheap mesh-merge exposed the residual co-dominant cost as library-rendered link cylinders that node
  instancing would never touch — the big rewrite would have missed. bridge-candidate
- `!lesson` **An append-at-EOF convention on a shared file is not conflict-free** — two branches appending
  at the same EOF collide on identical context. Cheap handling: predict it, then rebase B onto rebased-A as
  a stack and merge the head PR — GitHub auto-marks the contained PR MERGED, collapsing two rebase+CI
  cycles into one. Adjacent trap: `gh pr merge --delete-branch` run FROM a worktree checked out on that
  branch silently switches that worktree to the default branch, and a later `git switch main` elsewhere
  fails "already used by worktree". bridge-candidate
- `!lesson` **Playwright `getByText` is case-insensitive SUBSTRING matching by default** — asserting
  "ACCESS · 2" strict-mode-collided with a node whose text began "access · 20"; pass `{ exact: true }` for
  any label that can prefix another. Companion pane traps now in project memory: the browser-preview tool
  resolves launch.json against the MAIN checkout (worktree copies are ignored), and its tab runs
  `visibilityState:"hidden"` so rAF/CSS animation freezes and WebGL screenshots time out — verify computed
  styles and network traffic there, never live motion. bridge-candidate

- The #385–#388 merge wave landed; #387's PR-level Frontend-E2E red was pure runner infra (the job
  passed untouched on main). Post-merge main went red on ONE cross-PR semantic conflict → one-line
  fixture fix (PR #389). The full deliverable set was regenerated on 3.30.0 and independently QA'd →
  REAL scorecard row 13: the **first all-APPROVE full set** (6 Low, 0 Critical/High/Medium; all five
  regression-watch items verified fixed in rendered pixels; judge gating at TNR 0.6) — recorded with
  the handoff refresh as PR #390. All six Low findings were then fixed + test-pinned the same session
  (deck ×4, MOP sub-wave host-split slice, engagement per-port relabel) as PR #391, render-verified
  against the real snapshot (the 7 sub-wave splits sum exactly to the parent's 107+144).
- `!lesson` **PRs that are each green alone can break main where they meet.** A merge wave's PRs each
  ran CI on their own merge-ref without the siblings (#386's new bare-`TestClient` test file never met
  #388's Host allowlist until main). Textually MERGEABLE ≠ semantically compatible. After ANY multi-PR
  wave lands: pull and run the FULL gate on merged main immediately; the fix is usually applying the
  combined PR's sibling reconciliation pattern to the orphan file; fix forward, never revert the wave.
  bridge-candidate
- `!lesson` **A CI job that dies inside actions/checkout with `Invalid username or token` after a long
  stall is infrastructure, not a red diff.** Under 52-jobs-on-2-runners contention, `git submodule
  status` (repo has no submodules) hung ~28 min and the job's checkout credential went stale before
  the fetch. Zero tests ran — re-run once the queue drains; never debug the branch when the log never
  reaches the test runner. bridge-candidate
- `!lesson` **PowerShell 5.1 splits a native command's argument at embedded double quotes even inside a
  single-quoted here-string** — a `git commit -m @'...'@` whose message contained `"board clean"` broke
  at the quote and git parsed the remainder as a pathspec. For any commit/PR body with quotes or
  markup, write a UTF-8 file and use `git commit -F <file>` / `gh pr create --body-file`. bridge-candidate
- `!lesson` **When main is red and your own open PR is the fix, base dependent work on that PR's branch**
  (stack), not on main — the stacked branch's full local gate and CI run green, and GitHub retargets
  the dependent PR to main automatically when the fix merges. Merge order stays fix-first. bridge-candidate
- MOP slice-fix guard worth remembering in-repo: the joined cutover host split is sliced to the wave's
  members ONLY when the wave covers a proper subset of its groups' membership — a whole-group wave
  keeps the raw union, so an inconsistent uploaded snapshot can never silently lose a single-homed
  member from the procedure (fail-soft beats aggressive normalization).

## [2026-07-10] — P0-3 human-gate mechanization: PPDIOO document gates now refuse, not advise (branch `feat/p0-3-gate-enforcement`, PR #313 merged)

- Executed P0-3 (G-003/DEC-003) end-to-end: new `cisco_toolkit/gate_state.py` — per-engagement
  `docs/engagement-state.json` store (append-only `DOC_GATES` keys; the *document-approval* axis
  complementing `engagement.GATE_SEQUENCE`'s per-wave cadence, reusing the webapp board's record model) —
  and the engine's design/MOP blocks now REFUSE on a missing upstream approval (design ← `assessment_approved`;
  MOP ← `lld_approved` + `baseline_captured`), overridable only by `--override-gate "<reason>"` which appends a
  who/when/why audit line. Fail-safe: absent store = warn-and-proceed, so it ships DORMANT (no store in-repo;
  first `approve` opts an engagement in). SSOT-registered; 14 tests incl. both plan acceptance criteria;
  12/12 CI green; human-merged same morning. Clean session — nothing broke that wasn't a designed pin firing.
- Blast-radius-first paid off as a *design input*, not paperwork: `python -m graphify affected` on the two
  writers showed ~63 direct test call-sites + the webapp path, which DECIDED the enforcement point (CLI
  orchestration layer, where a flag can live; writer signatures untouched → zero drift for every caller).
  Worktree note: `graphify-out/graph.json` is untracked so it doesn't exist in worktrees — run graphify from
  the main checkout (same class as the gitignored vault-digest absence).
- `!lesson` **Adding ANY new module under `cisco_toolkit/` fails `test_pipeline_golden` by design** — the
  attestation claim re-derives "0 LLM/GenAI SDK imports across N modules" (64→65 here) against the frozen
  golden. That's the no-egress pin working, not corruption: re-bless with `UPDATE_GOLDEN=1 python -m pytest
  tests/test_pipeline_golden.py` (grow-only; refuses to shrink), then verify the golden diff is EXACTLY the
  census lines before committing.
- `!lesson` **An override whose entire purpose is to leave an audit line must fail CLOSED when the ledger
  itself is unreadable.** A corrupt/unparseable gate-state store refuses generation even WITH
  `--override-gate` — the who/when/why line has nowhere trustworthy to land, so the bypass would be
  unaudited by construction. Distinguish the three states explicitly: absent (proceed, warn), unapproved
  (refuse, overridable+audited), unreadable (refuse, not overridable). bridge-candidate
- `!lesson` **CI-watch scripting traps, twice in one session:** (a) `gh pr checks` exits 8 while checks are
  merely PENDING — a background poll surfaced as "failed with exit code 8" when nothing was wrong; script
  for exit 8 explicitly. (b) A Monitor poll loop whose error arm is `|| { sleep; continue; }` produced ZERO
  events then timed out — the `gh ... --json | jq` pipeline failed every iteration and the fallback swallowed
  it, making hard failure indistinguishable from "still pending". A poll loop must emit at least one error
  event before continuing; silence is not success. bridge-candidate
- `!lesson` **Every CI check "failing" in ~2s with zero failed steps and `log not found` = the jobs never
  STARTED — read the check-run annotations API, don't debug the code.** This PR's own docs-only run showed
  10/10 instant fails; `gh api .../check-runs/<id>/annotations` surfaced the real cause: "recent account
  payments have failed or your spending limit needs to be increased" (Actions billing exhausted after a
  9-PR day). With required-checks branch protection, billing exhaustion silently makes EVERY merge
  impossible until fixed (or human admin bypass). bridge-candidate

- Built `.claude/commands/architect-plan.md` through 4 adversarial iterations (self-verify → self-adversarial →
  independent refuter fan-out → consistency audit; each round found real defects the prior round missed, incl. a
  doctrine-3 violation in the prompt itself and the D10 paired-power erratum). Ran it: Stage A = 9 parallel
  read-only workers (A–H + R), Stage B master plan, 2-round independent QA (round-1 BLOCK on a provenance defect
  → remediated → APPROVE ×3). Phase 0 then EXECUTED same day: G-001..G-006 all closed
  (#307/#308/#311/#312/#313 + protection-live proof via red PR #306), P0-7 local allowlist narrowed, P0-8 vault
  shell-lane merged (#314), HR-005 residuals ratified by user delegation. Scorecard 3→6 rows incl. the first
  real BLOCK (cx=8) — the feedback nerve fed by its own planning process.
- `!lesson` `/goal` conditions MUST be declarative claims — an interrogative deadlocks the Stop hook evaluator
  into an infinite block loop; worse, async task-start reminders splice into a mid-typed command's arguments
  (a `/goal clear` became a new corrupted goal). Submit control commands into an EMPTY input box. `bridge-candidate`
- `!lesson` Parallel chip PRs touching one module (scorecard.py ×2) need an integration owner: the merge-union
  must be re-verified semantically (schema-set equality test caught `to_scorecard_row` missing the other PR's
  keys) — a test pinning `set(row) == set(SCHEMA_KEYS)` is exactly the tripwire you want. `bridge-candidate`
- `!lesson` Append-only jsonl logs conflict trivially across parallel sessions — resolve as an ordered UNION
  (never pick a side), and keep the latest judge-baseline row last so `latest_judge_baseline` semantics hold.
- `!lesson` Fast-moving multi-session days: `git fetch` before EVERY merge decision (a stale `origin/main` made a
  clean-looking local merge lie about conflicts), and `gh pr checks --watch` right after a push can report "no
  checks" before runs register — wait ~60s or re-arm.

## [2026-07-10] — P0-5 registry de-rot + freshness guard, adversarially reviewed and merged (PR #307, branch `claude/beautiful-mcnulty-0f67af`)

- Executed P0-5 (gap G-005): fixed the four verified-stale registry/ADR lines (release-version cache 3.26.0→3.30.0;
  "no live feed yet" vs the TRACKED `feed-2026-07-07.jsonl`; "no digest data yet" → clean-clone-honest wording; the
  ADR-0001 "planned, not installed" heading → dated status update) + the CLAUDE.md local-Ollama carve-out (ADR 0001
  Am. 1). NEW `tests/test_registry_freshness.py` guards both rot modes — status-vs-tracked-tree and cached-value-vs-
  owner — proven red before the fixes (3 failures, one per stale claim), green after. Then a max-effort 10-angle
  adversarial review of my own PR found 15 confirmed issues (all fixed, `91e81d1`): the guard is now enrolled in
  `selfcheck.GUARD_FILES` (13→14), reconciles the feed count against `verify_feed`'s VERIFIED entries, scans table
  rows only, and skips on unobservable reality instead of a CI env-var proxy. Merged with an explicitly named
  `--admin` bypass after CI green (10 checks incl. py3.10 exercising the fallback parser). The plan doc itself
  (`architect-master-plan-2026-07-10.md`) is untracked here — proceeded by re-verifying every inline task claim
  against the tree first; all held.
- `!lesson` **A freshly written policy carve-out needs an adversarial read for unintended licenses — the exception you
  word for one mechanism will be read as licensing neighbors.** My first carve-out ("a local Ollama on 127.0.0.1 is
  not egress") accidentally read as re-authorizing `graphify label` via a localhost backend — regenerating the very
  LLM-derived node layer the de-pollution removed — because the AST-only invariant had only ever been justified BY
  egress. Refuter fan-out caught it; self-review had not. Fix: state the surviving invariant separately from the
  exception ("licenses local INFERENCE only; AST-only is a provenance invariant, not an egress one"). bridge-candidate
- `!lesson` **Never cache machine state in docs — name the read path instead; and when a review flags a cached value,
  PROBE it live before trusting either side.** The registry row cached "Ollama 0.31.1"; a finder flagged the rot
  class, and the live probe showed the install was ALREADY 0.31.2 — the drift had happened before the ink dried.
  Docs now say "read `ollama --version`, never cache it here". Same class as device state: "not observed" ≠ current.
  bridge-candidate
- `!lesson` **An artifact's self-declared header fields are NOT attestations unless the signature covers them —
  reconcile against verified content, not the header.** The feed manifest's `n: 93` is outside the SHA-256 (which
  covers entry lines only) and `verify_feed` never cross-checks it; my first guard trusted `n`. A tampered or
  mis-produced feed could assert any count while the gate loads a different one. Fix: require the provenance gate to
  ACCEPT the artifact and reconcile to `len(verified entries)`. bridge-candidate
- `!lesson` **An env-var is a proxy for "which runner", not "which data is present" — gate owner-machine tests on
  whether the reality is observable, not on `CI`.** The digest existence check under `skipif(CI)` would hard-fail any
  contributor clone (no CI var, no gitignored digest — a state the registry row itself documents as designed), and
  `bool(os.environ.get("CI"))` is truthy for `CI=false`. Fix: skip exactly when zero digests are visible; assert only
  where the data exists. bridge-candidate
- `!lesson` **Windows Git-Bash piping can eat pytest's final summary line (`N passed in Xs`) — trust the exit code +
  file redirect, not the piped tail.** `python -m pytest -q 2>&1 | tail` repeatedly ended at the warnings block with
  the count line missing; `grep -c` on the same stream returned 0. Redirect to a file and read exit status; also
  pytest 9's `--collect-only -q` emits per-file counts (`file.py: N`), not node ids — `grep -c "::"` counts zero.
  bridge-candidate

- Turned a "is Perplexity Brain better than us?" research request into an agent-brain planning arc. Deep-research
  found Brain = self-improving *agent-work* memory (context graph + overnight synthesis), **cloud-only → non-adoptable
  for the air-gapped core** → decision (ADR 0003): skip the product, port patterns, hybrid markdown+SQLite substrate
  *gated* behind real data. Then verified TWO externally-run Perplexity design docs against primary source and folded
  the survivors into plans — the SelfMem "True Ceiling" → ADR 0003 + `agent-brain-selfmem-upgrade-plan`; the retrieval
  "Pass 4" → `d10-retrieval-eval-design`. Executed the *built* frontier: recorded the baseline judge-TNR (reproduced
  `ollama_judge` cross-family 0.2 / deterministic 1.0 → the design.docx APPROVE is now explicitly PROVISIONAL), cleared
  the binary phantom-health audit (0 violations across 9 AUTOFILLED deliverables), and BUILT
  `precert.compute_readiness_freeze` (single-snapshot readiness cert, schema `precert-readiness/1`, +7 tests,
  shadow-validated NOT READY on the AJ snapshot). 8 commits, whole suite green. *(Honest slip: dated the new planning
  docs `2026-07-08` by anchoring on a sibling filename; the system clock was `2026-07-10` — git timestamps are the truth.)*
- `!lesson` **An external planner blind to the codebase re-derives instruments you already ship — map every proposal to
  a shipped symbol BEFORE building.** Twice now (two Fable plans earlier, two Perplexity passes here) the "build this"
  list was ~80% already-shipped: the "independent verifier" = `ollama_judge`, the "red-team panel" = `defect_panel`
  D-01…D-12, the "calibration loop" = `calibration.py`, the "safety tier" = `memory_guard`. A polished spec pulls hard
  toward re-building; the honest delta is usually small. Fix: grep/graphify each proposal to its owner first, adopt only
  the residual. bridge-candidate
- `!lesson` **Verify an external doc's citations against primary source — they can be REAL even when the doc looks
  confabulation-shaped — but a real citation ≠ a build-worthy proposal, and existence ≠ attribution ≠ figures.** All ~10
  cited papers (SelfMem `2607.03726`, HTC `2601.15778`, overconfidence `2602.06948`, Fiedler `2605.06939`, R-GPL
  `2501.14434`, UDCG EACL-2026, Fröbe SIGIR-2025) checked out on WebFetch — skepticism resolved in the doc's favor. But
  (a) exact figures inside a real paper still need a PDF check before quoting (Fröbe's κ/τ numbers weren't extractable),
  and (b) some refs were MIS-attached (a dev.to blog + an IETF draft cited for "RRF k=60 sensitivity") — drop those.
  Verify the three separately. bridge-candidate
- `!lesson` **Perplexity renders markdown footnote markers (`[^1]`) INTO its code blocks, so its Python is never
  drop-in.** `embeddings.shape[^1]` / `sorted(..., key=lambda x: x[^1])` are corruption of `[1]`; seen in BOTH uploaded
  docs. Treat any Perplexity code as reference-only and re-implement clean — a naive paste crashes on the first line. bridge-candidate
- `!lesson` **Under a vague "proceed / take the best decision", the best decision is sometimes to NOT act — outward or
  gated actions still need an explicit instruction.** Held all session: never pushed off a vague "proceed" (only on an
  explicit "push"), kept REAL calibration row #1 operator-owned (it needs a live cutover + sign-off — unforgeable), and
  refused to pull gated work (the SQLite substrate, the D10 retriever) forward as busywork. "Feed real data, don't build
  more" survives sustained pressure to manufacture motion. bridge-candidate
- `!lesson` **A background workflow can WEDGE while its task-registry status still reads `running` — detect it by
  filesystem staleness, not the status field.** The deep-research workflow stalled between phases; the status API said
  `running` for ~1h45m while the journal + agent files had ZERO new writes (newest mtime vs wall-clock `date`). Fix:
  check the transcript dir's newest-file mtime against now — a long flat-line = wedged; `TaskStop` the zombie and
  synthesize from the completed phases (every returned agent's output was already in `journal.jsonl`). bridge-candidate

## [2026-07-08] — Judge-trust + calibration nerve: guard the guard, feed it honest data (branch `chore/scorecard-first-real-rows`)

- Continued the "measure the judge, don't assume it" arc. A QA verdict is a Claude judge on Claude's work, and
  LLM judges default to TNR < 25% (agreeableness bias, `2510.11822`) — so an all-`APPROVE` scorecard is the
  predicted output of a *broken* instrument. Moves 1–2 (prior commits) built the apparatus to MEASURE it
  (`defect_panel` deterministic 12/12 floor + cross-family `ollama_judge`) and to validate the readiness scorer
  (`fault_corpus`, 6/6 injected faults flip non-READY). This session HARDENED + completed the arc: wired the three
  new instruments into the self-check immune system (`GUARD_FILES` 10→13), made `check_pir_substrate` REAL-aware
  (`X/5 toward the D11 floor`, surrogate never reads tune-eligible), fed the 7 fault-injected rows into the empty
  `pir_outcomes.jsonl`, and documented Move 1/2 in `docs/quality/README.md`. Full suite green.
- `!lesson` **A branch that builds a guard must also guard the guard — else the immune system is blind to its own
  newest instrument.** Moves 1–2 built the defect-panel TNR floor + fault-corpus discrimination (the whole thesis),
  but neither test was in selfcheck's `GUARD_FILES`; gutting the TNR floor would still read GREEN — the exact
  "silently gone" failure selfcheck exists to prevent. The branch contradicted its own thesis until the guards were
  registered (10→13, verified RED-on-gut by the existing non-vacuity test). bridge-candidate
- `!lesson` **A true-negative-rate harness that only tests REJECTING bad work is half a test — a "rejects
  everything" judge scores rejection 1.0 and looks perfect while being worthless.** The clean-control (judge a
  known-GOOD deliverable FIRST; `rejection_rate` is meaningful ONLY when `approves_clean` is True) separates a
  *specific* judge from a paranoid one. Measured qwen3:4b: `approves_clean`=True but rejection ≈ 0.2 —
  specific-but-insensitive, a supplement not a replacement on 16GB-CPU hardware. bridge-candidate
- `!lesson` **The strongest HONEST calibration source at N≈0 is ground truth by construction, never a fabricated
  PIR.** Injecting one real fault into an all-pass scenario yields a labeled row (clean vs incident) with zero
  fabrication; tagged `source_class=fault-injected` it populates the DESCRIPTIVE gap but the D11 gate (REAL-only)
  keeps it out of tuning. Result: the calibration nerve is proven end-to-end (`N=7, accuracy=1.0, false-confidence
  0.0`) while still correctly `[GATED]` at 0 REAL — data fed without loosening the no-fabrication law. bridge-candidate

## [2026-07-07] — Syntys DC HLD → v7.5 full-family rebuild (research → audit → mining → figures → content → resync → independent QA)

- Rebuilt the Syntys Qatar-DC deliverable set to a best-possible v7.5 across a ~50-agent marathon: a research wave
  (cited HLD/diagram best-practices brief), an audit wave (14 figures + document + family-skew), and a mining wave
  (every v3–v7 HLD/LLD for content dropped along the way → 32-recovery plan) fed a ground-up rebuild. Shipped a NEW
  reusable figure generator (`Syntys_DC_Design/figgen/`: `svgkit.py` vector engine + `figdata.py` SSOT →
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

## [2026-07-06] — Syntys HLD v7.1: integrity reissue + FCSLA-delivery + firewall-terminated-edge deltas (side engagement)

- Side-engagement session only — produced Syntys DC HLD v7.1 from v7.0 in three stacked deltas: an integrity/completeness
  reissue (~27 fixes: ACP rule off-by-one, FPR3105 copper-port media, C9400 SVL single-active-supervisor behaviour,
  figure renumber, consolidated 39-REQ + 10-OQ Appendix A, reinstated §12.6/§14.4, S-30, REC-6 optics gap), then the
  Ooredoo FCSLA delivery as a design variation, then the resolved firewall-terminated eBGP edge (D-14 topology /
  D-15 C-2 evolution). No tracked repo code touched — `Syntys_DC_Design/` is gitignored with its own SSOT, so `git log`
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
