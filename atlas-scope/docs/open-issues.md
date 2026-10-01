# Atlas Scope — open issues found during the build

Tracked here so they cannot be lost between agent waves. Each entry says how it was found and what
evidence exists, because an issue asserted without evidence is a rumour.

## Resolved

> **W5b of the Atlas Scope program — the follow-up of the W5 repair wave (recorded 2026-10-01; an
> UNCOMMITTED working tree on top of `22373163`, the merge that brought W5's commit `2145187a` onto this
> branch).** Six clusters, each followed by an independent verifier: **S-CI** (the successor-package test
> and the CI fetch-depth guard; upheld), **S-QF** (the /scope reader; closed PARTIAL with no code change in
> this round; verifier: two findings, both outside its files), **S-QG** (C1's KEY validator and the
> reference capture's overlay dismissal, round 2; verifier: defects, one major), **S-D3** (the focus audit's
> harness and the focus owner; upheld), **S-PB** (the portable release contract; upheld) and **S-VOCAB**
> (the engine-contract vocabularies; closed PARTIAL, verifier: defects, two major). Several reports carry
> work from an earlier W5b pass that was not recorded separately; the entries below include it as those
> reports state it. Entries R135–R141 record what the round closed, each with the test or bounded run that
> pins it; O68, O69, O70, O71 and O77 carry dated status notes on what stays open. **Not a re-grade:** no
> acceptance criterion moves, and every "PASS" or "exit 0" below is a test or harness result, not a grade.
> **C1 stays UNPROVEN** (no critic panel ran) and **D3 stays UNPROVEN** (no complete `--sweep`, `--vp=390`
> or default audit run on any tree). **The wave's gates (reported):** the engine gate DID NOT RETURN, so
> there is no full `pytest` result for this tree. The app gate reported one red,
> `src/core/tracked-sources.test.ts` ("no file the build loads or the compilers import is missing from
> HEAD") on `src/core/vocab.ts`; it turns green only when the orchestrator commits `vocab.ts` and the
> wave's other new files (`src/core/compile-kind-absence.test.ts`, `src/core/vocab.contract.test.ts`,
> `src/app/focus-return.sight.test.ts`, `tests/pytest_invocation_reader.py` and
> `tests/test_engine_contract_vocabularies.py`), a git write the gate may not make. **Applied in the
> working tree after the cluster reports (read from the diff by the record step; no cluster report names
> them and no verifier has read them):** S-VOCAB's ready absent-kind patch (`query.ts` indexes
> `d.kind ?? ""`; `Fabric3D.tsx` uses `kindWords`; `DevicePane.tsx` renders the kind through
> `orNotObserved`; `FabricLegend.tsx`, `scene.ts` and `query.test.ts` also change); `DataGrid.tsx`
> `paintedBox` now calls `containsFixedBoxes` in place of its own hand list, and
> `focus-return.sight.test.ts`'s `KNOWN_COPIES` is empty (SD3V-5's owed half); `portable/build_atlas.py`
> `scope_shell_gap` now names the reader's own refusal reason (VQF-2), and lists missing tracked assets one
> path per line; and `tests/pytest_invocation_reader.py` is the one pytest-invocation reader, imported by
> both `tests/test_ssot_registry.py` and `webapp/tests/test_scope_mount.py` (S-CI-V2), with
> `tests/test_webapp_ci_scope.py` counting it as a shared helper. **What the record step itself
> re-ran** is stated at the end of R141. **Reported, not re-run by the record step:** every cluster's
> red-before-fix, mutation and census claim, every bounded audit and browser run, both gates, and every
> Python test.

### R135. The CI history checks — the successor-package test built its subject from whatever checkout ran the suite, and the fetch-depth guard read only `ci.yml` — FIXED IN THE TESTS (W5b S-CI; verifier upheld, with two minors, O69) (closes W5-X1 and W5-X4; removes one of O71's eight expected linked-worktree reds)
**What was fixed (reported).**
- **W5-X1 — a wrong environment assumption, not a builder defect.**
  `tools/build_atlas_r2_authority_candidate.py` `_read_subject` accepts only a release-custody
  repository: a standalone `.git` (not a linked worktree), full history, LF-exact
  `autocrlf`/`eol`/`safecrlf`, and a clean tree.
  `tests/test_atlas_r2_authority_decision_binding.py::test_successor_package_binds_and_exercises_this_exact_binder_source`
  handed it whatever checkout ran the suite: before the fix, at `22373163`, a full scratch clone failed
  `LF_EXACT_GIT_CONFIG_MISSING:core.eol` and this linked worktree failed on its standalone-`.git`
  requirement. The test now builds its subject by fetching the checkout's HEAD, with full ancestry, into a
  fresh LF-exact repository. It passes in a linked worktree, in a full clone, and in a clone with
  `autocrlf=true` and a detached HEAD; on a shallow checkout it still skips visibly, because the builder
  needs full history.
- **W5-X4 — the fetch-depth guard is derived on both axes.**
  `tests/test_ssot_registry.py::test_every_ci_leg_that_runs_a_history_needing_test_fetches_the_full_history`
  replaces the `ci.yml`-only guard. The tests: `_tests_that_decline_a_shallow_history()` walks the AST of
  every test module under `pytest.ini`'s testpaths for a `pytest.skip` whose reason names "shallow" (today
  `test_ssot_registry`, `test_atlas_r2_authority_decision_binding` and
  `test_atlas_r2_authority_candidate`). The legs: `_workflow_legs_collecting()` parses every
  `.github/workflows/*.yml` and finds each job whose pytest collects one of them. Two legs fetched a
  shallow history and now use `fetch-depth: 0`: `main-selfhosted.yml` `suite` (default depth) and
  `portable-release.yml` `gate` (explicit depth 1).
**Pinned by** those two tests. Final check `python -m pytest -q -p no:cacheprovider
tests/test_ssot_registry.py tests/test_atlas_r2_authority_decision_binding.py`: exit 0 in this linked
worktree and in a full scratch clone (`core.autocrlf=false`), each with only the symlink test skipped on
this Windows host; exit 0 in a depth-1 scratch clone, with three visible skips (the renamed-away citation
check, the successor integration and the symlink test). No workflow has run on a hosted runner.
**Not closed (the verifier's minors):** S-CI-V1 — the guard finds history-needing tests by the word
"shallow" in a `pytest.skip(...)` reason, not structurally, so a `pytest.mark.skipif(..., reason=...)`, a
`from pytest import skip` alias, a skip inside a helper or `conftest.py`, or a reason that never says
"shallow" escapes it; S-CI-V2 — the pytest-invocation reader was a near-copy in `tests/test_ssot_registry.py`
and `webapp/tests/test_scope_mount.py` (the working tree now holds one shared reader; see the banner).
**Lesson (S-CI, bridge-candidate, for `docs/log.md`):** `git fetch <shallow-repo> HEAD` into a fresh
repository rejects the HEAD ("shallow roots are not allowed to be updated"), still exits 0 and writes no
`FETCH_HEAD`; pass `--update-shallow` and check that the fetched commit equals the source's HEAD instead of
trusting the exit code.

### R136. The /scope reader — a shell whose only icon link sat inside `<title>` was served ready: the shell is now read as one browser-tokenized stream, and a raw-text element left open or holding markup is refused before any presence check — FIXED IN CODE (W5b S-QF, closed PARTIAL; verifier: two findings, both outside the cluster's files, O69) (closes RQF-V2-1)
**What was fixed (reported; the fix predates this round and was re-read, not changed, in it).** In
`webapp/backend/app.py`, `_scope_html_tokens` is the ONE parse of a shell (start tags, end tags, character
data). `_scope_shell_tokens` refuses any shell in which a `_SCOPE_HTML_RAW_TEXT_ELEMENTS` member (script,
style, title, textarea, xmp, iframe, noembed, noframes, noscript, plaintext) is not closed by its own end
tag, holds a `<`, or is PLAINTEXT (`_scope_raw_text_misread`), before anything is judged present.
`_scope_shell_declares_an_icon_in_its_head` walks those same tokens, so an icon link that the browser reads
as `<title>` text no longer counts as an icon.
**Pinned by** `ATLAS_SCOPE_REQUIRE_MARKUP_ORACLE=1 python -m pytest -q -p no:cacheprovider
webapp/tests/test_scope_mount.py webapp/tests/test_snapshot_raw.py` (exit 0, no skips, `cisco_toolkit`
resolved to this worktree). **Hub-build equivalence (reported):** a scratch `vite build --mode hub` of the
current source, written outside the worktree, matches the tested `dist-hub` byte for byte in every CSS file;
its shell differs only in the module-entry hash, and both shells read exactly and declare a head icon. The
cluster deliberately did not build into `atlas-scope/dist-hub` itself, which would have baked another
cluster's in-progress source into the tracked hub build.
**Not closed:** VQF-1 / VQF-R2-1 — the `dist-hub` the oracle tested was not produced by `npm run build:hub`,
and that command could not pass when the cluster ran: `npx tsc -p tsconfig.json` exited 2 on seven errors in
S-VOCAB's absent-kind types (`tsconfig.config.json` exit 0). VQF-2 — `scope_shell_gap` named the wrong reason
for a refused shell that carries the runtime-source meta (an S-PB file; applied in the working tree after
the reports, see the banner). VQF-R2-2 — the `atlas-scope/README.md` reading claim is slightly inaccurate on
two points the verifier names. All in O69.

### R137. C1's KEY validator — RULE v8: prose read whenever nothing is filed, picks carried as object keys, `recognizedAs` read for recognition only under `recognized: true`, and the "proves" wording withdrawn — FIXED IN THE HARNESS (W5b S-QG, round 2; verifier: defects, one major, O70); no critic panel has run (closes SQG-V3 to SQG-V7 and O70's QG3-3; QG3-1 is still not closed by class)
**What was fixed (reported).** `review/blind-pair.mjs` RULE v8, ruleSha `6066a0400b1a`:
- **SQG-V3 — prose is read on any line with nothing FILED under the dimension.** `pickValues` used to read
  prose only when no value at all was found, so a misfiled "A" or a stray token hid "Panel B is much
  better". "Nothing filed" means no non-null value; a filed empty string is unreadable through `pickOf`,
  never nothing.
- **SQG-V7 — a pick carried as an object KEY is read.** Every `perDimension` key and every top-level key is
  read through `typedString`, the same reader the values use, and `leavesOf` gained an `onKey` hook, so a
  nested key is read too: `perDimension {B: null}`, top-level `{B: null}`, `{winner: {B: {}}}`,
  `{"Panel B": null}` and a key that disagrees with the values are possible losses. Schema and dimension
  keys never hold a pick token or word, so valid lines are unaffected.
- **SQG-V6 — under `recognized: true`, `recognizedAs` answers the recognition question.**
  `RECOGNITION_QUESTION` asks the critic which panel the product is in, so reading that answer as a pick
  turned a cooperating recogniser's "B" into a permanent loss. A well-typed `recognizedAs` is now read for
  recognition only (`namesOnLine`) when `recognized === true`; a malformed one is still read leaf by leaf;
  and a `recognizedAs` that names nothing but a panel is a new INVALID shape in `verdictShapeProblems`,
  beside the empty-`recognizedAs` rule. An earlier W5b row that read a recogniser's "(B)" as a loss was
  reversed on this reasoning and kept with its justification, not dropped.
- **SQG-V4 — the free-string reader's class claims pinned beyond one instance:** the whole-word class
  ("the layout of B is cramped"), NFKC (fullwidth "Ｂ"), invisible-character stripping ("ti" + U+00AD +
  "e") and the "tie" token ("tie." beside a filed A) each have a row that the verifier's surviving mutant
  turns red.
- **SQG-V5 (QG3-3's residual) — wording.** The `TASK_KINDS` doc no longer says the self-check proves the
  task: it confirms the working surface is there but cannot show the task state, which rests on the
  declared, reviewed `taskState` inside the crop. `review/capture-refs-clean.mjs`'s failure prefix is the
  neutral "declared task state problem:", and two self-check lines say a reference "declares", not "shows",
  its task kind.
RULE's text, `review/REFERENCES.md` and the `blind-pair.mjs` header ("W5b round 2 (SQG-V3..V7) — RULE v8")
state the four reading changes; the self-check list still reads 1–10 in order (W5-X7 holds).
**Pinned by** `node review/blind-pair.mjs --selftest` (166 checks, all pass; the SQG-V3 and SQG-V7 rows red
before the fix). **Sheets.** `node review/blind-pair.mjs` exited 2, the defined BLOCKED code: 8 sheets for
4 of 5 pairings, byte-identical to before, and a KEY regenerated under ruleSha `6066a0400b1a`;
`c1-network-visualisation` is still BLOCKED (`08-path-indeterminate` at tier "balanced", not recaptured).
**Not closed:** SQG-R2-1 (major) — a field whose key is an `Object.prototype` name is never read, through
the prototype-chain `FIELD_TYPE_OK` lookup in `pickValues`: `constructor` or `toString` with a non-string
value is taken as well-typed and its pick vanishes, and `__proto__`, `hasOwnProperty`, `valueOf` or
`isPrototypeOf` makes `evaluate()` throw a `TypeError`, crashing `--validate` on real `verdicts.jsonl`
input (true at `22373163` too, but inside the class the brief names). SQG-R2-4 — the punctuation-boundary
half of the whole-word class is pinned by no row. SQG-R2-5 — the SQG-V6 exemption covers all pick reading
of `recognizedAs`, not only a panel location, so "B is better" written there on a line with nothing filed
reads as no answer. All in O70. **C1 stays UNPROVEN.**

### R138. Reference capture — `capture.mjs refs` decides overlay dismissal by structure: consent and close controls in shadow roots, absolute boxes, in-flow bars, image alt text and titles are dismissed again, and product controls in fixed app chrome are left alone — FIXED IN THE HARNESS (W5b S-QG, round 2; verifier: defects, O70) (closes SQG-V1 and SQG-V2; QG3-4 is NOT met)
**Before the fix (reported):** the verifier's four narrowing cases and a dialog with a title-only close
were all BAD (`node review/capture.mjs selftest` 59 of 70, exit 3), and six product controls were clicked:
"Close sidebar" in a fixed `<header>` over a padded wrapper and in a transparent fixed `<header>` over
text, "Dismiss tips" in a fixed landmark-less bar, "Dismiss all notifications" in a fixed `<nav>`,
"Accept suggestion" in a sticky toolbar and "Allow editing" in a lone fixed toolbar.
**What was fixed (reported).** `dismissRefOverlays` is rebuilt around a self-contained in-page
`findDismissControl`. A control is clicked only in one of three places: an element with an overlay role;
a fixed or absolute box that is not a page-chrome landmark, carries a message of its own beside the
control, and is hit-tested painting over visible text or replaced content outside it; or the nearest small
box (at most 1,500 characters of text) that talks about consent. Candidates come from the document and
every open shadow root, walked recursively, with hit tests that descend through `shadowRoot`; names come
from `aria-label`, `aria-labelledby`, text, value, `title` and `img` alt. The decisions behind it: sticky
counts as in the page flow and never as layered; header, nav and the banner/navigation roles are never
themselves a layered box, though an overlay role anywhere in the chain is decisive; a lone fixed control is
not a message with a dismiss; the 1,500-character bound stops a whole page that mentions privacy from
qualifying; `[title]` joins the candidate selectors, and a role-marked overlay is never its own dismiss
control. **Residuals left to frame review:** a product's own out-of-flow popover with a message and a
Close, a product control inside a small box that talks about privacy, and consent inside iframes.
**Pinned by** `node review/capture.mjs selftest` (73 cases, all pass; 11 structural mutants killed) —
synthetic pages only; the real references were not recaptured.
**Not closed:** SQG-R2-2 — a regression introduced by this round: the candidate set takes ANY `[title]` or
`[aria-label]` element and reads its full `innerText` as a name, so a container or row whose text contains
"allow", "accept" or "got it" (everyday words in ACL and policy rows of the network products referenced)
becomes a dismiss control inside a layered box or a dialog, which neither the pre-O70 code nor `22373163`
did, against `REFERENCES.md`'s and `capture.mjs`'s claim that product controls are never clicked.
SQG-R2-3 — QG3-4 is still not met: a box over a CSS-background hero is not "layered" (only text and
replaced elements count as content), the consent test strips the control's own name and stops at 1,500
characters, and in-flow announcement bars with `aria-label="Close"`, which the pre-O70 exact selector
closed, are no longer dismissed, so the doc's "the one deliberate narrowing" is inaccurate. Both in O70.

### R139. D3 — the focus audit numbered occurrence keys over one list and resolved them over another, read a one-frame pointer as a render-mode difference, timed its watchdog on a hand-picked clock and censused containing blocks without aliases — FIXED IN THE HARNESS AND CODE (W5b S-D3; verifier upheld, with five minors, O68); render-mode equivalence shown in two page states (closes SD3V-1 to SD3V-4 and SD3V-6, and W5's V2-1 for "a finding selected"; SD3V-5 scoped)
**Carried from W5b's earlier pass (reported; confirmed by the verifier's mutations):** W5's V2-2 (the
crossing path's `releaseFocusLeftUnseen` call; mutations A and A2), V2-3 (`returnFocus`'s outward walk,
O77; B and B2, and B3 now pinned), V2-4 (`sightOf`'s containing-block rule for absolutely positioned
elements; C1 and C2), and the extraction mechanics of W5-X3 (one containing-block definition). V2-5 is
extended by SD3V-3 below.
**What was fixed this round (reported).**
- **SD3V-1 (major) — one definition of an opener's own stops.** `crossDiscover` numbered its keys over
  `own(revealed)` while `crossSurfaceJob` resolved them over the whole read, so a re-shown clean-page stop
  of the same name could take the key. `review/audit-d3-focus.mjs` now has `ownOf`, `ownKeyed` and
  `ownStopByKey`, used by the discovery (its record, its stable test and its keys) and by the surface job
  (`opened.list`, the late-mount wait and the fresh read); a moved stop is logged on an INFO line and counted
  in the render-check and crossing summaries. `keyRuleSelfCheck` runs in every mode: red on the old
  resolution, green on the new.
- **SD3V-2 (major) / W5's V2-1 — the 768 px "off view" difference was a harness race (reported cause).**
  Opening the Inspector from "Open the source record for F001 at punch" shows the fabric's off-view pointer
  for one animation frame in both render modes (per-frame probe under `.local-data/`); the fixed 400 ms
  read caught it only when frames were slow, as they are when every frame is drawn on a loaded host. Every
  activation is now read from a page whose signature holds across two frames (`crossAfterKey` /
  `crossFrameStill`), pinned by `frameStillSelfCheck`. **Bounded render checks on the current shared tree:**
  "a finding selected" EXIT=0, 549 compared, 0 differ (41.3 min); idle EXIT=0, 425 compared, 0 differ
  (30.3 min).
- **SD3V-3 — the watchdog's progress clock is every completed Playwright call.** `installRoundTripClock`
  wraps the client's one dispatch point (`_wrapApiCall` on the shared `ChannelOwner` base) and moves the
  calling job's clock through `AsyncLocalStorage`; `roundTripClockSelfCheck` fails the run if a
  `page.evaluate` inside a job does not move it. `sweepState` and `sweepJourney` note their steps so a stall
  report names them. Longest quiet stretch on the final runs: 31–40 s against a 5 min bound; a frozen page
  is still stopped (EXIT=1, NOT DRIVEN lines).
- **SD3V-4 — both halves of `returnFocus`'s outward walk pinned.** Two portal-layout tests in
  `src/app/focus-return.rule4-doors.test.ts`: with everything around the target and the menu hidden, focus
  lands on the context's outer region "Overlays", never `<body>`; with an outer region of each chain shown,
  the context's comes first (13 of 13 pass).
- **SD3V-6 — the containing-block census measures every name Chromium accepts:** 711 names (151 `-webkit-`
  aliases), each also in capitals. Widening it found `will-change: offset` (a shorthand) contains a fixed
  box; `containsFixedBoxes` is now case-insensitive, alias-aware and shorthand-aware. Census: 0 disagree
  over accepted names.
- **SD3V-5 — scoped.** `containsFixedBoxes` is the one definition for `sightOf` and the audit.
  `DataGrid.tsx` `paintedBox` held a third hand list owed by its owner (replaced in the working tree after
  the reports; see the banner). A new test in `src/app/focus-return.sight.test.ts` scans every non-test
  module under `src` and fails on a module other than `app/focus-return.ts` that reads `will-change` and is
  not on `KNOWN_COPIES` — a NEW copy that reads `will-change`, not every new copy (SD3R2-2).
**Not closed (the verifier's minors, all in O68):** SD3R2-1 — `containsFixedBoxes` treats any `-webkit-`
ident in `will-change` as its unprefixed member, wider than Chromium's real aliases, and the census cannot
see it because it probes only accepted property names; SD3R2-2 — the SD3V-5 guard is a proxy (a
`will-change` read) for the class (any containing-block decision); SD3R2-3 — the V2-1 normalisation (an
opener's own stops filtered before the "revealed nothing" check) is pinned by nothing, and its INFO line
does not name the render mode, so a one-mode difference there is invisible to the render check; SD3R2-4 —
the preserved evidence does not support the "one animation frame in both modes, 4 of 4 probes" attribution;
SD3R2-5 — the watchdog's stop path is unbounded (`Promise.all` over `context.close()`), so a wedged browser
still hangs the run after its FAIL line, and the stopped job keeps running and changes the counters.

### R140. The portable release contract — one schema id names one shape for every versioned document it writes or reads, every W5-X5 attribution guard has a refusal test that reaches it, and a relative root no longer crashes the module recorder — FIXED IN CODE (W5b S-PB; verifier upheld, with three minors, O69) (closes V-SPB-1 to V-SPB-3)
**Carried from W5b's earlier pass (reported):** the `toolchain/2` and `qualification/2` bump (W5-X2), the
build attribution and its tests (W5-X5), and tests for W5's R-PB minors PB-V1-H, -E, -J, -Q and -B.
**What was fixed this round (reported).**
- **V-SPB-1 (major) — every versioned document, not a typed pair.** W5 (`2145187a`) added the namespaced
  npm notice field `npm_project` under `atlas.portable-third-party-notices/1`, and
  `receipt_schema_shapes()` covered two ids. In `portable/release_contract.py`, `NOTICES_SCHEMA` is now
  `/2`; `/1` is in `_SUPERSEDED_SCHEMAS`, refused rather than migrated, because the Scope inventory exists
  only on the build host, and it is read before any shape check. Every key set that any of the 12 current
  ids is written with or checked against is declared once in `_SCHEMA_SHAPES`; validators read it through
  `_has_shape`, writers and expected dicts pass through `_shaped`, and `receipt_schema_shapes()`
  fingerprints the whole registry. The tests derive the id denominator from every `atlas.portable-*/N`
  literal in the module's source (AST), pin one fingerprint per id, and refuse any inline string-set key
  comparison (AST guard). The SBOM's exemption is stated in code: it follows the external CycloneDX schema,
  and its Atlas properties are recomputed from the notices. Toolchain materials are one ordered tuple,
  `_TOOLCHAIN_MATERIALS`, shared by writer and validator. The `toolchain/2` and `qualification/2`
  fingerprints were re-pinned under the same ids; neither `/2` id has ever been committed (HEAD still writes
  `/1`), so no issued document changed shape under them. The `/1` ids that stay current are unchanged.
- **V-SPB-2 — the ten unexercised W5-X5 guards (A, B, C, D, E, F, H, J, L, O)** each have a refusal test in
  `tests/test_portable_release_contract.py` that reaches it; the real-runtime verifier now checks the
  reviewed npm contract before the pinned-toolchain checks, so a self-consistent receipt that drops the
  bundler runtime is refused (all checks still run). Census: 18 of 18 mutants killed, each restored from a
  saved copy.
- **V-SPB-3 — a relative repository root.** `_record_build_modules` resolves the project root and scratch
  directory itself; `test_the_module_recorder_is_handed_absolute_paths_for_a_relative_root` was red before
  the fix (argv held the relative `atlas-scope`).
**Pinned by** `python -m pytest -q -p no:cacheprovider tests/test_portable_release_contract.py
tests/test_portable_release_workflow.py tests/test_atlas_bundle.py` (exit 0; 155 tests, 0 failures, 2
platform skips that predate the round: the POSIX FIFO test and directory symlinks without the privilege).
**Not closed (the verifier's minors, all in O69):** V2-SPB-1 — the `qualification/2` fingerprint leaves out
its second closed id set, `REQUIRED_EXTERNAL_GATES` (`external_pending`), so adding or removing an external
gate changes what `/2` accepts without moving a fingerprint (the W5-X2 shape again); V2-SPB-2 — the stated
reasons for refusing the superseded `/1` ids describe only the pre-W5 shape and are false for the `/1`
documents `2145187a` wrote; V2-SPB-3 — no test reaches the verifier-side `_check_attribution_members` in
`verify_portable_release` on its own (every such test fails first at the build-side copy). No report states
a PyInstaller run or a frozen `Atlas.exe`.
**Lesson (S-PB, bridge-candidate, for `docs/log.md`):** an id bump fixes the instance; a fingerprint over a
hand-picked subset of ids, or one that skips key sets validators write inline, repeats the defect. Derive
the id denominator from the source, keep every key set in one registry that readers and writers both use,
and refuse inline key-set comparisons with an AST guard.

### R141. Engine-contract vocabularies — the TypeScript unions are pinned to the contract inside `vitest`, and every value under a `severity` key in the golden snapshot and the engine-owned sample is pinned to the published severities — FIXED IN THE TESTS (W5b S-VOCAB, closed PARTIAL; verifier: defects, two major) (closes S-VOCAB's V4 and V5; the absent-kind repair, V1–V3, waits on files outside the cluster)
**What was fixed (reported).**
- **V4 — the union-to-contract direction inside the test runner.** With "Superb" added to the `Band` union
  and "camera" to `DeviceKind` in `core/types.ts` only, `vocab.contract.test.ts` still passed (21 of 21):
  the `Record<Union, true>` witness pinned that direction only under `tsc -p tsconfig.json`.
  `atlas-scope/src/core/vocab.contract.test.ts` now reads the `Severity`, `Band`, `NotMeasuredBand` and
  `DeviceKind` aliases with the TypeScript parser (`declaredUnion`) and compares them with
  `contracts/engine-contract.v1.json`; it refuses any alias that is not a plain union of string literals,
  and a liveness test checks that it sees an added member and refuses `| string` and `(typeof X)[number]`.
- **V5 — severities pinned against what the producers write.**
  `tests/test_engine_contract_vocabularies.py::test_every_severity_the_engine_writes_is_a_published_severity`
  walks the whole of `tests/golden/snapshot.json` (pinned to a real pipeline run by
  `test_pipeline_golden`) and `webapp/sample_data/sample_fleet.snapshot.json` (kept fresh by
  `build_sample.py --check`). Every `severity` string at any depth must be a published severity, except two
  declared foreign vocabularies, each pinned to its own set and disjoint from the contract: `security`
  (`parse.py` `_SEC_CHECKS` severities lower-cased, plus "info") and `aci` (the APIC `faultInst` severity,
  verbatim). A new section is inside the check by default. This corrects the earlier claim that severities
  were producer-pinned: they had been compared only with constants (verifier V5).
**Pinned by** those two tests; R1, R2, R4 and R6 re-verified after the last edit (the engine-contract,
pipeline-golden and protocol-assessability tests exit 0 with `cisco_toolkit` resolved to the worktree;
`build_sample.py --check` exit 0, FRESH; `compile-all` into a scratch directory, with `fabric.json`,
`acl-bindings.json`, `rib-evidence.json` and `producer-emission.json` identical).
**Not closed:** D1 (major) / V1–V2 — making `Device.kind` nullable left `npm run typecheck` red (exit 2,
seven errors, all outside the cluster: `query.test.ts:124`, `Fabric3D.tsx:521`, `FabricLegend.tsx:217`
twice, `scene.ts:876`, `DevicePane.tsx:618` and `:2289`), and on the UI paths an absent kind still showed as
"unrecognised kind null" and indexed the text "null" (the tracked sample never triggers it: all 26
cable-map nodes state a kind); the cluster's ready patch was applied in the working tree after the reports
(see the banner) and no verifier or report has typechecked it. D2 (major) / V3 — `npx vitest run
--maxWorkers=2 src/core` is red on `tracked-sources.test.ts` until `src/core/vocab.ts` is committed (the
cluster counted 58 files and 2,825 tests, 2,824 passed; the verifier's 1,637 over 57 files came from another
tree or file set). D3 — the suite pins the exported ORDER arrays, not the membership tests, so a recogniser
that ignores the contract survives. D4 / V6 — `compute_health_scores` and `compute_cable_map` in
`cisco_toolkit/analyze.py` still write the literals "Insufficient Data" and "device", and the band literal
recurs at more than ten read sites outside the cluster's slice; drift is caught by the producer tests, not
prevented by one owner. D5 — the V5 walk matches only the exact key `severity`, and the `aci` exception set
is hand-kept with no engine owner, so "every severity the engine writes" overstates. D6 — a docstring typo
in `tests/test_engine_contract_projection.py`.
**Lessons (S-VOCAB, bridge-candidate, for `docs/log.md`):** a typecheck-only witness pins its direction
only where the typecheck gate runs, and a gate red for unrelated reasons silences it, so restate the check
inside the test runner by parsing the declaration; to pin an enum against its producers, walk the
producers' whole output for the field and name the exceptions, never a list of sections to include.
**What the record step itself re-ran (2026-10-01, after its edits):** the 14 test files that read these
documents (the set the phase-3.5 banner names) in one `npx vitest run --maxWorkers=2` invocation, 1,584
passed, exit 0; `python -m pytest -q -p no:cacheprovider tests/test_ssot_registry.py` with the real
interpreter, exit 0; and the repository's client-marker scan
(`cisco_toolkit.distribution_verify._client_marker_patterns()`, imported from this worktree) over this
document, 0 hits. It also read the working tree's diff, which holds the four post-report edits the W5b
banner names. It ran none of the other pins these entries cite and did not run either gate.

> **W5 of the Atlas Scope program — the preview-scope repairs after phase 3.5 (recorded 2026-09-30; an
> UNCOMMITTED working tree on top of `3509b73c`).** Not the earlier "wave 5" (W5-K1…K4, R67–R80). Four
> clusters, each followed by an independent verifier: **R-D3** (the D3 focus owner and the focus audit's
> render check; verifier: defects), **R-QF** (the /scope reader; closed PARTIAL, verifier: defects),
> **R-QG** (C1's KEY validator and reference capture; verifier: defects) and **R-PB** (the portable
> bundle's /scope build, smoke and SBOM; verifier upheld). Entries R130–R134 below record what they
> closed, each with the test or bounded run that pins it; O68, O69, O70 and O77 carry dated status notes
> on what stays open. **Not a re-grade:** no acceptance criterion moves, and every "PASS" or "exit 0"
> below is a test or harness result, not a grade. **C1 stays UNPROVEN** (no critic panel ran) and **D3
> stays UNPROVEN** (no complete sweep, `--vp=390` or default audit run on the committed tree).
> **The wave's gates (reported):** the engine gate's full `pytest` had 11 reds — the 8 expected
> linked-worktree reds (O71), two load flakes that pass alone
> (`test_transition_runtime_inventory::test_windows_venv_redirector_pid…` and
> `test_make_stick::…[rollback_prepared]`, "A file is IN USE"), and
> `tests/test_transition_schema_assets.py::test_byte_bound_checkout_owners_are_lf_exactly_attributed`,
> red because R-QF's `webapp/backend/app.py` edit is uncommitted (it compares HEAD's blob with the
> working tree; the gate measured 0 CR bytes and filter-neutral hashes, and expects green after the
> commit — unconfirmed). `python webapp/sample_data/build_sample.py --check` exits 2 on attestation
> drift that predates this wave: `cisco_toolkit/ui_projection.py` arrived with the #577 merge after the
> sample was last regenerated (`74275919`), so the engine counts 100 analysis and 102 LLM-scan modules
> where the committed sample says 99 and 101. Regenerating it changes the sample's sha256, which
> cascades through `src/test-support/golden-sample.ts`'s `GOLDEN_SHA`, every golden expectation and the
> compiled documents, so it is routed to the base branch or the engine lane (`build_sample.py`, then
> `npm run compile:data`, then the golden re-derivation); no `pytest` or CI workflow runs `--check`. The
> app gate's last `node review/capture.mjs app` run was 32 of 32; its frame-rate flag is intermittent
> (O70). The hub build still carries the label-schema key NAMES `sourceDigestForm` and `sourceGitBlob` in
> 4 files and no compiled dataset value (O76's first decision, unchanged). **What the record step
> itself re-ran** (after its edits): the 14 test files that read these documents (the set the
> phase-3.5 banner names) in one `vitest` invocation, 1,548 passed, exit 0; `tests/test_ssot_registry.py`,
> exit 0; and the repository's client-marker scan over this document, 0 hits. It also read the working
> tree's diff, which holds edits no cluster report names (O68, O69). **Reported, not re-run by the record
> step:** every cluster's red-before-fix and mutation claim, the bounded audit and browser runs, both gates
> and every other Python test.

### R130. D3 — after 768 → 390 px the Inspector's "Copy the citation path" button held focus with no part of it on screen, a resize within one rung could leave focus unseen, and a crossing's settle step judged a still-moving skip link — FIXED IN CODE (W5 R-D3, two rounds; verifier: defects, O68) (closes QH-V2-2)
**What was fixed (reported).** The failure every recorded audit log carried (O68): focus on "Copy the
citation path", clipped by `div.app`, in all four page states. Round 1 added the owner step
`releaseFocusLeftUnseen`, run at the 400 ms settle of every rung crossing, and a shrinking
`.inspector__cite` group; the before-fix build gave EXIT=1 with that one FAIL per state. Round 2:
- **V1-5 — the citation chip no longer cuts its text.** The "citation" caption and the path (a new
  `.inspector__citetext` span) wrap as two items; the path is placed by its longest token (`flex-basis:
  min-content` with `overflow-wrap: break-word`), justified as an UNBREAKABLE-TOKEN CONTAINER under the
  `primitives.css` wrapping doctrine, like `.ui-cite__path`. A browser probe measured the chip's scroll
  width equal to its client width at 280, 320, 360, 390 and 768 px (the verifier had measured 222 against
  184 at 320). `node review/capture.mjs wrap` passes; R-D3 did not run `review/capture.mjs text`.
- **V1-4 — a resize inside one rung.** `App.tsx` calls the new owner function `keepFocusSeen` 400 ms after
  the last window resize of any kind. It scrolls an unseen focused element into view first and hands focus
  on only when no scroll reveals it; focus that is already seen is never touched.
- **Judged at rest (a new defect, found through the render check).** A crossing's pending 400 ms settle
  could fire while a newly focused element was still moving: the skip link slides in on `:focus-visible`,
  was judged unseen at top −56 px, and focus went to `MAIN#stage`. Reproduced with draws suspended in a
  scratch probe under `.local-data/`. The settle step now waits for finite running transitions and
  animations on the element or its ancestors (`movingNow` / `judgeAtRest`).
**Pinned by** `src/app/focus-return.unseen.test.tsx` (the within-rung App case and three decision cases
for `keepFocusSeen`, each mutation-killed; two judged-at-rest tests, red first and mutation-killed).
**Not closed:** the crossing path's own `releaseFocusLeftUnseen` call in `App.tsx` is pinned by no test —
`keepFocusSeen` fires at the same settle and masks its removal (V2-2, O68); `sightOf`'s containing-block
rule for absolutely positioned elements is unpinned (V2-4). No complete audit run has confirmed the fix
in the browser on the committed tree (O68).

### R131. D3 — the focus-return doors stated rule 4 separately and drifted, the third-door guard bound a release per file instead of per call site, and `aria-labelledby` was split on the letter "s" — FIXED IN CODE (W5 R-D3, two rounds; verifier: defects); the first door's outward walk is OPEN (O77) (closes O77's regex defect and V1-1, V1-2, V1-3)
**What was fixed (reported).**
- **O77's regex.** `idRefs` in `src/app/focus-return.ts` is now the only split of an ID-reference list and
  uses `/\s+/`. Pinned by `src/app/focus-return.labelledby.test.ts` (green in R-D3's final `src/app` run,
  86 files).
- **V1-1 — rule 4 ("its labelling heading, else the labelled region itself") is stated once,** in
  `namedRegionsAround`, `placesOf` and `recordedPlaces`, and used by `returnFocus`, `handOffFocus` (through
  `planHandOff`), `releaseFocusFrom` and `releaseFocusLeftUnseen`. `tryFocus` refuses any element that is
  not rendered (the owner's `isRendered`), replacing per-door filters that had drifted because jsdom
  focuses hidden elements. Pinned by `src/app/focus-return.rule4-doors.test.ts` (red 6 of 7 before the
  fix; three mutations checked).
- **V1-3 — the guard per call site.** `src/app/focus-return.guard.test.ts` shape 6 now needs a release at
  each call site: a third-door call counts only on the same access path or an ancestor's, in the site's own
  function, and before the site. Planted case `imperativeDoorPerSite` (red first: a release in another
  function, and a release after the removal); the verifier's Fabric3D/preview cleanup mutation is now
  caught; the guard is 150 of 150 on the real sources. Stated limit: this is statement order within a
  function, not a control-flow proof.
- **V1-2.** The fixed-box escape test in `focus-return.unseen.test.tsx` now depends on the escape; the
  verifier's M3 mutation fails it.
- **The `PENDING_ROUTING` debt (O68):** 9 of its 12 entries were released through the third door and
  deleted (round 1); a tenth, `scene.ts`'s, is recorded in the working tree's guard file as released by
  the W5 engine gate.
**Not closed:** the verifier found rule 4's outward walk is NOT one statement for every door (V2-3):
`handOffFocus` and `releaseFocusLeftUnseen` walk every named region outward, but `returnFocus` tries only
the nearest region's places and then the recorded region, so when those are unrendered and an outer
named region is shown it returns null with focus on `<body>`. The cluster's "every door uses it"
therefore overstates (O77). Two `PENDING_ROUTING` entries stay (O68).

### R132. The /scope reader — XML and every non-shell HTML page refused, a closed CSS accept-list, an icon required in the shell's head, shell-exact continuation joins, and a history check that does not break on a shallow checkout — FIXED IN CODE (W5 R-QF, two rounds, closed PARTIAL; verifier: defects); an icon link inside `<title>` is still served ready (O69) (closes QF-V2-1, QF-V2-2, QF-V2-3, QF-V2-4)
**Round 1 (the implementer, rechecked by round 2; reported).** XML-typed members are refused outright
(QF-V2-1; the 756-member family and its Chromium test pass in the final run); the shell is read on a
closed construct accept-list rather than a hand-kept URL-attribute list (QF-V2-3); top-level files are
citation roots for `tests/test_ssot_registry.py` (QF-V2-2); the CI-leg reader joins continuation lines
(QF-V2-4). `_vite_build` in `webapp/tests/test_scope_mount.py` now writes an icon, so the real-Vite pins
stay ready.
**Round 2 (RQF-V1-1, -3, -4, -5, -6; reported).**
- **Shallow history.** `tests/test_ssot_registry.py` `_repository_history` asks `git rev-parse
  --is-shallow-repository`, fails closed if git cannot answer, and on a shallow checkout declares the
  historical roots incomplete; the renamed-away citation test then skips visibly instead of failing
  `3 == 4` (reproduced first in a scratch `git clone --depth 1`). Pinned by a real-repository plus
  real-depth-1-clone test.
- **CSS.** Every `text/css` member of a /scope build, linked or not, is held to a closed accept-list
  (`webapp/backend/app.py` `_scope_css_refusal`): strict UTF-8, closed comments, tokenizer-exact strings
  with escapes decoded, six at-rules, a closed non-fetching function list, and the word `url` refused. A
  generated family of 36 resource-naming constructs × 3 URLs, with the hub build's own stylesheets as inert
  controls, runs in full Chromium behind a recording proxy: on the old reader 87 of 99 CSS loads were
  served ready and fetched outside /scope; after the fix, 0 violations.
- **The default icon request.** The shell must declare an icon IN ITS HEAD
  (`_scope_shell_declares_an_icon_in_its_head`): measured in full Chromium with one origin per case, an
  absent icon, or one met only after the head has ended, makes the browser request `/favicon.ico` outside
  /scope — a request only a recording proxy sees, not Playwright's page events. The request oracle now runs
  full Chromium behind a per-lane recording proxy (340 cases).
- **Continuations.** Joined exactly as each shell joins them (bash deletes an unescaped backslash before
  LF; PowerShell 5.1 reads an unescaped backtick before LF as a blank); a trailing blank or a CR breaks the
  continuation, measured in both shells, and those cases are negatives.
- **Non-shell HTML.** `index.html` is the only HTML page served under /scope; every other HTML member is
  refused (`_SCOPE_REFUSED_HTML_PAGE`), as XML is. The markup reader's own verdict, `_scope_html_refusal`,
  is still proved against Chromium over the generated markup family, because the shell is read with it.
**Pinned by** `webapp/tests/test_scope_mount.py` (run with `ATLAS_SCOPE_REQUIRE_MARKUP_ORACLE=1`, every
Chromium oracle required and passing), `tests/test_ssot_registry.py` and `tests/test_webapp_ci_scope.py`
(the `atlas-scope/**` pair, reported unchanged). **Not closed:** the cluster's claim that a build served
ready requests nothing outside /scope "by construction" is refuted — a shell whose only icon link sits
inside `<title>` is served ready and Chromium then requests `/favicon.ico` (RQF-V2-1, major, O69). The
final check `ATLAS_SCOPE_REQUIRE_MARKUP_ORACLE=1 python -m pytest webapp/tests tests/test_ssot_registry.py
tests/test_readme_field.py` was PYTEST_EXIT=1 on one test outside the cluster's files (RQF-V1-2), a stale
`docs/ssot.md` line citation since corrected in the working tree (O69).
The admitted module entry's run-time behaviour is a stated residual (`atlas-scope/README.md`).

### R133. The portable bundle and /scope — the build refused a missing or unready hub build without naming the commands, the frozen smoke never asked for /scope, and the SBOM and notices omitted atlas-scope's production graph — FIXED IN CODE (W5 R-PB; verifier upheld, with five minors, O69); not run against a frozen `Atlas.exe`
**What was fixed (reported).**
- **The build refusal.** `portable/build_atlas.py` `build_refusal(root)` refuses, before PyInstaller, an
  absent `atlas-scope/dist-hub` and a present one that AssessHub's own `_scope_file_index` does not judge
  ready, naming `cd atlas-scope`, `npm ci` and `npm run build:hub` one per line (no `&&`, so each pastes
  into PowerShell 5.1); the commands are keyed by `atlas_bundle.BUILD_OUTPUTS`.
- **The frozen smoke.** `smoke()` requires the exact selftest lines (`REQUIRED_SELFTEST_LINES`, including
  `[ ok ] atlas-scope-dist`) and `GET /scope/` 200 `text/html` whose body AssessHub's
  `_scope_shell_reading` accepts and that equals `_internal/atlas_scope_dist/index.html` byte for byte. It
  reports the new qualification check `loopback_http_scope_runtime_shell`, now in
  `release_contract.REQUIRED_AUTOMATED_CHECKS`.
- **SBOM and notices.** A lock-derived inventory `bundled_scope_frontend` (8 packages: three,
  postprocessing, react, react-dom, zustand, scheduler, and the devOptional `@types/react` and `csstype`)
  with namespaced notice keys `npm:atlas-scope/…` and license text from the installed package; the class
  guard `bundled_npm_inventories()` derives the shipped projects from `BUILD_OUTPUTS` and refuses any
  uninventoried one; a reviewed count/digest pin applies to real releases. The two type-only packages are
  over-included and disclosed in `NOTICES_INFERENCE_BOUNDARY`.
**Pinned by** `tests/test_atlas_bundle.py` (a `_SmokeHarness` driving the real `smoke()` end to end; the
`build_refuses` tests), `tests/test_portable_release_contract.py` and
`tests/test_portable_release_workflow.py` (the real-lock pin and an independent Node-resolution closure
oracle), each red before the fix and mutation-checked; `tests/test_readme_field.py` exit 0 (the
README-FIELD section needed no edit). **Not closed:** PyInstaller was not run, so the live evidence is an
unfrozen loopback serve; the verifier's five minors and two residuals stay open (O69).

### R134. C1's KEY validator — RULE v6: no recognition erases a loss on any line, a pick in a malformed field is a possible loss, an unbound line is tied to every pairing it can be, and the contrast screen's claim withdrawn — FIXED IN THE HARNESS (W5 R-QG, fix round; verifier: defects, one major, O70); no critic panel has run (closes QG-V1 to QG-V5 and O70's R2-2, R2-3, R2-4, R2-6 and R2-7; R2-5's claim is withdrawn; R2-1 is not closed by class, QG3-1)
**What was fixed (reported).** `review/blind-pair.mjs` RULE v6, ruleSha `49aa61e0b431`:
- **QG-V1 / requirement 3.** Recognition drops a WIN but never erases a LOSS, on any line, first or later;
  v5 had let a first-line `recognizedAs` naming an ordinary identity string ("a Sign in form") erase one.
  Two rows that expected PASS under the earlier D2 reading now expect UNPROVEN and are annotated; the
  owner is asked to confirm that requirement 3 supersedes D2 here (O70).
- **QG-V2 (R2-1 by class).** The leaves of a field whose type is wrong are read as possible picks, never as
  "no answer": objects and arrays recursed, the non-string elements of `reasons` and `faults`, and a reason
  or fault that is nothing but A, B or tie.
- **QG-V5.** An unbound line is tied, side unknown, to every pairing its frames name or whose dimension it
  files an answer under; its loss stands there and its re-ask never counts. A line tied to nothing still
  blocks C1 overall.
- **QG-V4.** The CLI's evaluate options come from the tested `cliEvaluateOptions()`; `--selftest` fails
  when the R2-4 real-data check cannot run (the build and `--capture-ours` print NOT RUN instead, so a
  first capture can start); the `recognized: false` + `recognizedAs` shape rule has a pinning row.
- **QG-V3 (R2-5's claim corrected).** The reference task state rests on each target's DECLARED
  `taskState`, which blind-pair requires inside the crop. `review/capture-refs-clean.mjs`'s contrast
  screen is a sanity screen only, and its self-check now reports it UNCALIBRATED for all 5 paired
  references (`contrastCalibration`). The earlier wording "proves it is content, not chrome" is withdrawn.
- **The refs close control.** `review/capture.mjs` dismissal by role and name had regressed on
  non-button close controls such as `<div aria-label="Close">`; a second pass over visible aria-labelled
  elements restores a superset of the old exact selector, with the same exclusions. Checked against the
  synthetic control page only.
**Pinned by** `node review/blind-pair.mjs --selftest` (exit 0, 137 ok, 0 FAIL; 18 new or changed checks
red on the verifier-reviewed file; 15 mutants, run one at a time, all killed with each file restored
sha-equal) and `node review/capture.mjs selftest` (59 of 59; 58 of 59 before the close-control fix).
**Sheets.** `node review/blind-pair.mjs` exited 2 (a BLOCKED pairing): 8 sheets for 4 of 5 pairings at
`3509b73c` (dirty tree), byte-identical names, a new KEY (`blind-key/4`, ruleSha `49aa61e0b431`);
`c1-network-visualisation` is still BLOCKED (`08-path-indeterminate` at tier "balanced", not recaptured).
**Not closed:** a pick token in a WELL-TYPED string field other than `reasons` and `faults` is never read —
`recognizedAs: "B"` under `recognized: false` with no filed answer still loses the loss (QG3-1, major,
O70). **C1 stays UNPROVEN.**

> **Phases 3 and 3.5 of the single-source-of-truth program — the regenerated fleet, rendered (recorded
> 2026-09-30).** Phase 3 began with its precursor `74275919` (the sample fleet regenerated by
> `webapp/sample_data/build_sample.py` from this branch's engine and the four compiled documents
> recompiled from it; the golden test tier `src/test-support/golden-sample.ts` arrived with it). Phase 3
> ran nine clusters — **P3A1** (A1's consumer half), **P3A2** (decided multi-hop traces), **P3B** (panels
> re-expressed), **P3C** (core, analysis and fabric), **P3D** (scale), **P3E** (the runtime dataset and the
> AssessHub hub build), **P3F** (the one door: AssessHub, the portable bundle, CI, SSOT, docs), **P3G**
> (C1's references and blind protocol) and **P3H** (hardening leftovers, interrupted: its full focus
> audit ran about 10 h of software-GL rendering and was stopped) — and was checkpointed as `1061fdea`
> before any merged-tree gate ran. Phase 3.5 repaired it in seven clusters — **Q-A1**, **Q-C**, **Q-D**,
> **Q-F**, **Q-G**, **Q-H** and **Q-M** (the minors of the upheld P3A2, P3B and P3E) — and was
> checkpointed as `f24b9ccb`. Entries R120–R129 below record what they closed, each with the test that
> pins it, and O68–O77 under Open what they left; O12, O13, O19, O34, O50, O53, O57, O58, O65 and O66
> carry status notes. **Verdicts, final round of each cluster:** P3A2, P3B and P3E upheld in phase 3;
> Q-A1, Q-C, Q-D and Q-M upheld (Q-D closed PARTIAL); **Q-F and Q-G verified WITH OPEN MAJOR DEFECTS**
> after their fix passes (O69, O70); **Q-H** was verified with defects, its fix agent was stopped by the
> owner instruction below before it returned (its edits are in `f24b9ccb`), and a second independent
> verification found six defects, one a blocker (O68). **Owner instruction of 2026-09-29 (binding):**
> finish phase 3.5 only; the focus audit `review/audit-d3-focus.mjs` gets NO more runs in any mode, and
> its recorded logs are the evidence; the C1 critic panel and the acceptance re-grade are NOT run in this
> phase. So **the D3 focus audit is UNPROVEN at the current tree** (O68), no criterion moves, and every
> "PASS" below is a test or harness result, not a grade. **The phase-3.5 close gates ran on an UNCOMMITTED
> working tree on top of `f24b9ccb`** (reported by the gate agents, 2026-09-30): the gate repaired the
> reds it found in 18 files (R129), and with those repairs the full `vitest` suite passed on all four legs
> — the sample (6,710 passed, 1 skipped), the same run under 12 busy loops (6,710 passed, 1 skipped), the
> isomorphic-rename leg (6,464 passed, 247 skipped) and the engine's 7-device golden leg (5,736 passed, 288
> skipped), each exit 0 — with `npm run typecheck` exit 0, `node review/capture.mjs app` 32 of 32 frames
> (exit 0), `selftest` 49 of 49, `text` 90 of 90, `wrap` 0 unjustified, `reduced` (D7) PASS,
> `review/layout-guard.mjs` all five invariants, and `review/capture-motion.mjs`'s C5 items PASS; the
> engine gate's full `pytest` was red on 9 tests, 8 of them the expected linked-worktree layout reds and
> one a real red that needs an owner decision (O71). **At `f24b9ccb` itself the suite was RED** (the
> second Q-H verifier: `npx vitest run src/app` 2 failed, 956 passed; `node review/capture.mjs selftest`
> 48 of 49), and the gate's repairs are not yet committed or independently verified. **Timing harnesses
> are not acceptance evidence here:** `review/measure-inp.mjs` ran with the host 31 % busy (E3 across
> runs INSUFFICIENT RUNS, 0 of 3) and `review/measure-scale.mjs` with it 32 % busy (`acceptanceEvidence:
> false`). **What the record step itself re-ran** is stated at the end of this banner. **Reported, not
> re-run by the record step:** every cluster's red-before-fix and mutation claims, every browser harness
> and scratch probe, the gate runs above, the AssessHub end-to-end run, and every engine-side (Python)
> test.
> **The record step (2026-09-30)** read the cluster reports, the verifier verdicts, the gate summaries,
> the four full `--sweep` logs and the `--vp=390` log (it did not run the focus audit), and the diff of
> this working tree against `f24b9ccb`; in that diff it found one defect no report names (O77). After
> its edits it re-ran the 14 test files that read these three documents (`journey-scope`,
> `motion-inventory`, `mock-classification`, `source-hygiene`, `claim-lint`, `emphasis`,
> `acceptance-gates`, `layers`, `lighting`, `stroke-floor`, `contrast`, `target-size`,
> `stepdown.fadehold`, `EvidencePane.namedconfig`) in one `vitest` invocation — 1,533 passed, exit 0 —
> and the repository's client-marker scan over the three documents (0 hits). It ran none of the pins the
> entries below cite beyond those, and no Python test.

### R120. A1, consumer half — the engine's per-finding evidence pointers are rendered, and every finding reaches every record the engine names for it in 3 interactions under A1's settled counting — FIXED IN CODE (P3A1; phase-3.5 repair Q-A1, upheld); NOT RE-GRADED, and the bar is not met at 1280×720 (O72) (closes O50)
**Phase 3 (P3A1, reported).** The Evidence pane renders `evidenceBasis`, `evidenceRefs` and
`evidenceRefsTotal` per design brief §5.1, and the compiler projects the pointed-to records into a
bounded `fabric.evidenceRecords`. Its verifier's first four defects were fixed in phase 3: section
headings counted the folded list instead of every ref the engine names (P3A1-V1-1; F142 now reads
"Absence, witnessed by 20 records (7 shown)"); in the App's own mounting the engine's record opened
under step 5's "context, not the engine's evidence" note (V1-2; it now opens in step 3 beside its
pointer); a dotted citation after a slash was swallowed (V1-3; `punchlist[0]/punchlist[1]` now yields
both); and the projection's total cap did not bound withheld stubs and admitted records in pointer order
(V1-4; stubs are reserved first and full records admitted in the engine's priority order). The
Inspector's sidecar documents now come from the active dataset (`core/dataset.ts documentsByFile`), not a
glob of the bundled sample's, and the new `.ev-rec__json` / `.ev-rec__literal` boxes wrap (a justified
UNBREAKABLE-TOKEN CONTAINER licence) instead of scrolling with no keyboard stop.
**Phase 3.5 (Q-A1, verifier upheld with three minors, O72).** P3A1's second verifier found that the
phase-3 census `{1: 82, 2: 33, 3: 31}` counted selection as one interaction for every finding and left
the move to step 3 uncounted — A1's settled model (palette for any row not in view; scrolling is a
failure) gave 4 for 30 of those 31 and for the 9 folded-only findings (P3A1-V2-1). The pane's header now
carries `EngineIndex`: one control per record the engine names, in the engine's order, never folded,
in `.ev__head`, which does not scroll; activating one opens that record in step 3 and moves focus there.
The route is palette Ctrl+K (1), id + Enter (2), the record's header control (3); for a row in view,
row (1) + control (2). Also fixed: CutText searched for its delimiter only in the last 40 characters and
showed a cut token whole when none was found, so a truncated pointer could become a control for another
record (V2-2); the reduced type literal dropped an element whose combination of facts was new (V2-3);
`writtenChars` left out the array's brackets and commas, a real 593-character overrun of `totalChars`
(V2-4). **Pinned by** `src/panels/EvidencePane.engine-refs.test.tsx` (all 146 findings through the real
CommandPalette: 583 pointer instances, golden census `{3: 146}`, the 9 folded-only findings at 3, headings
counted over every ref, the App's own path with no `onShowConfig`, and the dotted-citation case),
`src/panels/EvidencePane.cut-text.test.tsx`, `src/core/compile-evidence-records.test.ts` (`writtenChars`
equals `JSON.stringify(records).length` on the sample, the planted over-budget run and the tiny-cap run;
lower priority never displaces higher), `src/core/compile-types.test.ts` (joint facts) and
`src/core/dataset.test.ts` (no module but the one door imports a compiled document). The inert-cite
census `src/panels/inert-cite-census.test.tsx` stays green with `KNOWN_ELSEWHERE` empty. **Real browser
(reported; a scratch harness, not tracked, QA1-R1-3):** 1920×1080 and 1440×900, dev build, no actor
scroll, 146 findings and 583 records, 0 failures; the verifier reproduced 1280×800 (0 failures) and found
203 of 583 activations whose content sits below the fold at 1280×720 (O72). The fifth phase-3 verifier
defect — `src/core/tracked-sources.test.ts` still pinned the retired glob edge — was fixed by the phase-3.5
close gate (R129). **A1 is not re-graded** (owner instruction above), so its last grade stands.

### R121. A2/B8 substrate on the shipped data — decided multi-hop delivery and denial are offered from the data with a found counterexample, and the forwarding tests are re-expressed into a golden tier and invariants — FIXED IN CODE (P3A2, upheld; its three minors fixed by Q-M, upheld) (closes O65)
**P3A2 (reported).** `suggestedFlows` offers a decided multi-hop delivery, a decided multi-hop denial
that names host, ACL, line and literal text, and a counterexample search that finds one; no flow is
hard-coded, and the no-route rationale comes from the terminal hop's `decidedBy`. Every scope and caveat
list goes through `listPhrase` ("no host" when empty). The binding-coverage sentences cite what each
clause was read from (verifier D7: the untrusted-sidecar sentence names both digests and
`meta.sourceSha256`; the no-interface-record sentence cites the coverage record). Golden expectations live
in one module, `src/forwarding/golden-expectations.ts`, and `golden-expectations.test.ts` fails on any
golden key no test reads (D3). The depth ratchet is now golden-tier: over `engine.test.ts`'s flow space
(19 addresses, 3,249 traces) depths `{0: 2,574, 1: 343, 2: 332}`, 332 resolved next hops, 9 definite
deliveries, 23 decided outcomes, 70 refusals and 26 counterexamples found — all asserted. Found and fixed
on the way: `engine.counterfactual.test.ts`'s `aclCites` regex had lost its escapes and compared `[]`
with `[]`; two sidecar-reading tests judged the loaded fabric against the tracked sample's files on disk.
O65 is closed: `src/forwarding/rib-partial-route.test.ts`'s header describes the single current fleet
(the session over Vlan10, 10.0.10.2 ↔ 10.0.10.3) and its golden block asserts that interface. **Pinned
by** `src/forwarding/engine.suggestions.test.ts`, `engine.no-counterexample.counterfactual.test.ts` (the
B8 clause executed on its rejecting side; `return true` turns it red), `engine.phrases.test.ts`,
`bindings-trust.test.ts`, `golden-expectations.test.ts`, `engine.counterfactual.test.ts` and
`rib-partial-route.test.ts`; `src/forwarding/test-subjects.ts` `need()` makes an absent subject a failure
on the reference sample and a named skip elsewhere. **Q-M fixed the verifier's minors:** an early
`return` on an absent preset counted as a pass (V2-m1; new class guard
`src/forwarding/absence-skip.guard.test.ts`, which QM-V1-m1 finds narrower than its class, O75); the
flow-terminal sweep reused one overlay without checking a mark bleeding into the next draw (V2-m2; each
trace now drawn over the previous one, `src/fabric3d/flow-terminal.counterfactual.test.ts`); and a
first-comma slice checked a vacuous scope prefix once `listPhrase` put a comma inside the clause (V2-m3;
`src/panels/PathTrace.preset-cites.b6.test.tsx`, and in the gate `src/app/verdict-scope.b2.test.tsx`,
R129). **A2 and B8 are not re-graded** (O13, O34, O53).

### R122. The panels on the regenerated fleet — subjects by property, a flow universe that includes routed destinations, and exact decider and caveat pins — FIXED IN CODE (P3B, upheld; its four minors fixed by Q-M, upheld)
**P3B (reported).** The panels' flow universe (`src/panels/trace-universe.ts`) drew destinations only
from SVI subnets, a hand-picked stand-in that hid the golden fleet's only decided denial; it now adds,
for every route an ordinary host address is longest-matched to (`exercisableRoutes`, through the
engine's `rankPrefixMatches`), one such destination, appended so first-found subjects on the sample are
unchanged (V1). `HopList.admin-distance` runs one trace and one route record per test with an
"every case ran" closing check (V2). claim-honesty #6 subjects go through `need()` (V3).
`claim-honesty-scope` pins each drawn caveat's words and citation count in order, and the blank-caveat
mutant is killed (V4). Sample literals and sizes moved into `describeGolden` (V5). `HopList.decider-header`
states both cases exactly — a bound list has exactly one ACL decider block; `binding-unobserved` has
none and one "ACL · hypothesis" block (V6). **Pinned by** `src/panels/trace-universe.test.ts`,
`decided-surfaces.counterfactual.test.tsx`, `HopList.admin-distance.test.tsx`,
`claim-honesty-scope.test.tsx`, `HopList.decider-header.test.tsx` and the re-expressed panel files
(`npx vitest run src/panels`: 54 files, 1,702 tests, exit 0, reported). **Q-M fixed the verifier's
minors:** the claim-cites sweep kept its own address list (P3B-R2-m1; it is now the subject universe,
first red with "628 universe flows the sweep never checks", `src/panels/PathTrace.claim-cites.test.tsx`);
the decider census used a literal address grid and `hostIntents` looked intents up by literal id (m2;
one flow per decider shape, "36 decider shapes the census never renders" first; intents by property —
QM-V1-m3 finds the `held` subject now tautological, O75); the decided 2-hop denial was never mounted
through `<PathTrace/>`, and ClaimCard's "Not established" line cited only the last hop's decider (m3;
`src/panels/PathTrace.decided-multihop.test.tsx`, and a product fix in `ClaimCard.tsx`: every hop's
`decidedBy`, deduplicated, in hop order); the preset partial-table check skipped sentences not shown
(m4; removed, the "Filtering" row-drop mutant killed).

### R123. Core, analysis and fabric on the regenerated fleet — the role glyph, the k-core claim, the loading skeleton, the list-phrase class, the tier-fade slot and the test re-expression — FIXED IN CODE (P3C; phase-3.5 repair Q-C in two rounds, upheld with two minors, O73)
- **Role glyph (P3C R1).** `src/core/roles.ts` owns how a role reads for scene, chassis and legend; an
  observed role other than access/distribution draws the "other" single-bar glyph, and only null or blank
  draws "unobserved". Pinned by `src/fabric3d/role-glyph.test.tsx` (a synthetic `core` role; the role scan
  is read from the TypeScript AST since Q-C). Draw calls re-measured on the regenerated sample: 71 high /
  31 low, 73 / 32 with the "other" glyph present (design brief §4.4).
- **`setData`'s fast path kept stale glyphs, rings, cables and positions for a snapshot with the same
  topology** (found by P3C). Pinned by `src/fabric3d/scene.data-signature.test.ts`.
- **The k-core claim branches on `maxCore` and names the lower shells from the data (P3C R2)**, and says
  "at least k carrying links", not "neighbours", because coreness counts parallel cables (P3C-V2-4).
  Pinned by `src/analysis/blast.kcore-claim.test.ts` (a star, K4 plus a tail, an edgeless graph, a
  parallel-link known answer).
- **The loading skeleton labels every device at the tier the layout places it (P3C R3, P3C-V2-1,
  QC-R1-1; owner decision (a)).** Phase 3 labelled whole cable-map groups by their reading, so a tie
  group's members and unlisted devices with a recorded tier read "tier not observed"; the first repair
  restated the layout's rule in the caller's array order. `src/fabric3d/tier-groups.ts` now resolves in
  the layout's own `(order, id)` order (`inLayoutOrder`, `reconcileTierGroups`, `placedTiers`). Pinned
  by `src/app/surfaces.stage-pending.test.tsx` (held equal to `computeLayout().nodes[].observedTier` on
  the verifier's probes and on 300 seeded shared-host fleets) and `src/fabric3d/tier-groups.test.ts`.
- **The list-phrase class (P3C R4, P3C-V2-5, QC-R1-2).** `claims.ts`, `blast.ts` (three sites) and
  `quality.ts` join through `listPhrase`. Pinned by `src/core/claims.empty-coverage.test.ts`: an AST scan
  of every non-test source under `src/` for a comma join that is the left operand of `||`/`??`, one whole
  branch of a conditional, or a `.slice(0, -1)` join; nine sites in other owners' files are ratcheted as
  PENDING (O73).
- **The tier-fade slot's methods cannot act through a copy (P3C-V2-2; owner decision (b)).** Object
  spread defeated the phase-3 tripwire. The slot is now a non-exported class with ES-private state, so a
  spread carries no method and an extracted method throws the brand check. Pinned by
  `src/fabric3d/emphasis.test.ts` (the prototype enumerated) and `src/fabric3d/scene.test.ts` (the DOM-site
  enumerator, which also treats a spread of a DOM-carrying source as a site; the verifier's spread mutant
  is killed). With phase 3's R4-VR2 follow-ups: an `extract` site kind (VR2-1), the handover's judging
  rule at ±2E and E/2 (VR2-2, `src/fabric3d/stepdown.fadehold.test.ts`), the host keeps its scene on a
  reduced-motion toggle (VR2-3), and a toggle landing on an overlay shown under full motion finishes it at
  the cap (VR2-4, design brief §4.8). O57's status note says what this does and does not settle.
- **Every core/analysis/fabric3d test that pinned the old sample is an invariant or a golden block
  (P3C-V2-3; owner decision (c)).** `query.test.ts`'s `TOTAL_FINDINGS`/`CORE1_FINDINGS` constants are
  gone; subjects are chosen by property. Measured on the rename and golden legs after the repair: no
  failure in a Q-C file (reported). The vacuous no-RIB invariant (P3C-V2-6) became a counterfactual that
  executes (QC-R1-3, `src/core/claims.no-rib.counterfactual.test.ts`), and a new AST guard,
  `src/core/golden-preconditions.test.ts`, requires every data precondition of a `runIf`/`skipIf` in a
  file with a golden tier to be read inside an `expect()` in its golden block — its first run found 12
  unstated preconditions across 6 files (QC-R1-4).

### R124. Scale — a 300- and a 1,000-device fleet: the layout is sliced and fails loudly, its route stage is cheaper, the fabric list stays usable, and the budgets are measured in a real browser — FIXED IN CODE (P3D; phase-3.5 repair Q-D, upheld, closed PARTIAL: the quiet-host budget receipt is still missing, O74)
**P3D (reported).** `review/synth-fleet.mjs` generates engine-shaped campus fleets and refuses, with exit
2 before generating anything, a `--budget-ms` that could not fail, a `--runs` that is not a whole number
of at least 1 and a non-integer `--seed` (D4). Every indivisible layout step reports the work it does:
the embedding stage was charged 1 unit for about 25·(N+E) counted calls and the last cable's ladder
nothing (D5). The fabric list stays usable at 300+ devices. Fabric3D drops scene hover while a press is
held (the orbit drag re-rendered every label per hovered device: 3.0–3.7 s of each 6 s drag at 300). The
Fabric3D comment that claimed the old scene keeps drawing during a large relayout is corrected, and the
real behaviour — the stage releases the scene and builds a new one — is pinned. **Q-D (phase 3.5).**
A throw in ANY layout slice now reaches the "The 3-D fabric" error boundary, stating the slice and the
work done; before, a throw after the first slice was an unhandled rejection behind an endless "Building
the 3-D fabric" (P3D-V2-1). The fabric root carries `data-layout="pending"|"ready"` (P3D-V2-3, the
owned half; the wording half is open, O73). The 300-fleet frame-time figures now state their canvas was
420×508 CSS px against the sample's 1160×962 (V2-4). The route stage's curve-clearance skips chords
that cannot change an answer, with bit-identical output (the 300 and 1,000 digests unchanged). The owner's
wall-clock budgets are gated by a new tracked real-browser harness, `review/measure-scale.mjs` (the app's
own open-a-snapshot path, host gates, receipt in `review/reports/scale.json`). **Pinned by**
`src/fabric3d/scale.test.ts` (the CLI refusals; no step over 1,000 counted calls per reported unit; the
throw in slices 1, 2, the middle and the last of the 300 fleet's 16; `data-layout`; hover during a press;
the scene swap; at most 170 counted calls per chassis measured against a route, 115 at 300 and 101 at
1,000 against 281 and 285 before; a brute-force exactness check) and `src/fabric3d/layout.test.ts` (a job
whose step threw stays failed; the 11 golden digests; sliced equals whole). **Budget receipts, none of
them acceptance evidence:** 2026-09-29, 77 % busy on battery, 300 PASS at a 207.6 ms median, 1,000 PASS
at 737.4 ms (Q-D); 2026-09-30, the phase-3.5 gate at 32 % busy, 300 PASS at 68.6 ms, 1,000 PASS at 192.5
ms, exit 0, `acceptanceEvidence: false` because of the host (reported).

### R125. Any snapshot — one dataset door, open-a-snapshot, the AssessHub hub build, coded refusals and stated warnings — FIXED IN CODE (P3E, upheld; its six minors fixed by Q-M, upheld with residuals, O75)
**P3E (reported).** `src/core/dataset.ts` is the only reader of `src/core/dataset/bundled.ts`, which is the
only static importer of the four compiled documents; a hub build installs a runtime dataset before the
app loads, and a standalone build can open a snapshot file (worker validate and compile, IndexedDB,
reload, install) with a persistent banner naming the dataset, its origin and its digests. Every failure
to load is a coded refusal on the boot line (`role=alert`, `data-dataset-error`) through
`src/core/dataset/refusal.ts`; before, only one error class was coded. The validator's non-blocking
warnings (`W_COLLECTED_AT_MISSING`, `W_GENERATED_AT_MISSING`, `W_SECTION_ABSENT`, `W_SCHEMA_ASSUMED`) are
shown on the banner, "N things this snapshot does not state"; before, the golden's two missing dates
were silent. The initial payload of both builds may carry only the boot entry's own modules — an
allowlist, replacing a list of four forbidden modules (F4). **Q-M fixed the verifier's minors:** the
census's planted control ran a copy of its visitor (P3E-V1); the build test accepted any asset NAMED
`compile.worker*` (V2; every `CompileError` code must now be in the worker and none in the entry); the
banner and panel said a server-attested digest was computed "over the bytes as read" (V3; they now say
", as AssessHub stated it (not recomputed here)" — QM-V1-m4 finds the header title and `StatusBar.tsx`'s
title unpinned, O75); the zero-findings example query could return nothing (V4); `rename-snapshot.mjs
--compile` always wrote the rename leg's directory (V5, `planOutputs` — QM-V1-m2 finds a same-stem source
still overwrites it, O75); the hub build's pre-write guard checked only two signatures (V6, now AssessHub's
compiled-record, raw-snapshot, `data:` URI and compressed-stream signatures, refusing bzip2/xz). Q-M also
made `forwarding/bindings.ts` and `rib-completeness.ts` read their sidecars through the door, so an
installed dataset now supplies its own ACL bindings and RIB evidence. **Pinned by**
`src/core/dataset.test.ts` (the one-door census, green), `dataset.refusal.test.ts`,
`dataset.banner.test.ts`, `dataset.example-query.test.ts`, `dataset.build.test.ts`,
`dataset.rename.test.ts`, `dataset.hub-guard.test.ts` and `dataset.runtime.test.ts`. **End to end
(reported by the phase-3.5 gate):** AssessHub served the hub build at `/scope`, and two stored snapshots
(the demo seed and `tests/golden/snapshot.json`) rendered their own counts and digests, verified in the
browser, with a cross-site `raw` request refused 403.

### R126. The one door — AssessHub serves the hub build, the portable bundle and CI build it, and a /scope document is read only in a markup language whose reading matches the browser's — FIXED IN CODE FOR HTML (P3F; phase-3.5 repair Q-F in two rounds); the XML path is OPEN (O69)
**P3F (reported).** AssessHub serves `atlas-scope/dist-hub` at `/scope` (dev and frozen default, honest
when not built); the portable bundle ships it; `atlas-scope-ci.yml` builds and tests it and
`portable-release` builds the hub; `docs/ssot.md` registers the compiled fabric projection. Its first
verifier's defects were fixed in phase 3: the `webapp-ci` push filter had diverged from its classifier (the
edit was withdrawn; the atomic pair is routed, O69); a `noreferrer` rel token, an iframe `srcdoc` and a
duplicated attribute declared a referrer policy past the check; the four evidence signatures were not each
exercised with escaped whitespace; the SSOT row claimed every record cites back. **Q-F (phase 3.5).** The
stdlib `HTMLParser` hid a `<meta name="referrer">` Chromium applies behind `<!-->`, `<!--->`, `--!>`,
`</script x>`, `</script/>` or `</style x>` (P3F-V2-1); AssessHub now accepts the shell, every HTML
asset and `srcdoc` only in a restricted language whose tokenization matches the browser's by construction
(`webapp/backend/app.py` `_scope_html_reading`), and XML-typed members are read by expat under stated
rules (V2-3). `atlas-scope-ci.yml` runs `webapp/tests/test_scope_mount.py` against the hub build it just
made (V2-2). The `create_app` docstring names `dist-hub` (V2-4). The README-FIELD ratchet reads exactly its
own section (V2-5). The markup oracle has its own switch, `ATLAS_SCOPE_REQUIRE_MARKUP_ORACLE`, and a pin
derived from the workflows finds every CI leg that collects these tests (QF-R1-1); the abrupt-comment and
`--!>` rules are pinned by closed-comment forms, and every refusal clause was mutated one at a time (30
mutants; each red or recorded as safety-equivalent, QF-R1-2); `tests/test_ssot_registry.py` checks every
`docs/ssot.md` citation rooted at a top-level directory and resolves each `path :: symbol` to a
definition (QF-R1-3; QF-V2-2 finds file roots and a text-mention rule still uncovered, O69), with
`must_exist` pins for the atlas-scope owner paths. **Pinned by** `webapp/tests/test_scope_mount.py` (unit
forms as shell and as asset, and the generated family judged by the index and loaded in real Chromium —
"the browser is the oracle"), `tests/test_readme_field.py::test_the_scope_section_is_exactly_its_own_section`
and `tests/test_ssot_registry.py`. **Not closed:** Q-F's second verifier found the parser-differential
class still open on the XML path (QF-V2-1, major, O69), and the cluster's final `pytest` stays red on one
test that is not its defect (O71). No CI leg has run on GitHub-hosted runners.

### R127. C1's references and blind protocol — clean references with a marker self-check, task-matched pairings, neutral masks on both panels, and a pre-registered KEY rule (v4) — FIXED IN THE HARNESS (P3G; phase-3.5 repair Q-G in two rounds); the KEY validator still loses a loss in three ways (O70); no critic panel has run
**P3G (reported).** `review/capture-refs-clean.mjs` owns the reference frames — Forward demo pages
rendered offline from their server-rendered data with provenance, Grafana with its banner pre-seeded
dismissed, IP Fabric's unannotated documentation screenshots; Linear is not obtainable without an account
— with a pixel (OCR) and DOM marker self-check. `review/capture-deep.mjs` finds Storylane's real
controls. `review/blind-pair.mjs` builds symmetric crops at equal DPR, paints neutral masks on BOTH panels,
draws each critic's side fresh, asks neutral questions, makes one pairing per C1 dimension, and writes a
KEY schema its validator evaluates under a pre-registered rule. **Q-G (phase 3.5), the verifier's
findings fixed:** pairings are matched by task through one vocabulary, `TASK_KINDS` (D1; round 2 moved
colour-discipline to `07-evidence-raw` against Grafana Explore, V1, and typographic craft to a derived
capture `06b-path-hop-evidence` with the hop's evidence open, V4); the rule is now RULE v4 (ruleSha
`939de74c18c5…`) — critic ids and picks normalised for NFKC, default-ignorable characters, case and
spacing (V3, V6), recognition decided by the critic's FIRST line with a later disclosure dropping the win
but never a loss already on record (D2, V2), an answer other than A, B or tie treated as a possible loss
(V3), an unattributable line recorded and blocking when it may pick the reference (V7); our identity is
masked by DOM-measured geometry on the settled page and cross-checked by OCR (D3; a fixed wait once
measured a still-loading page); declared reference identity slots are bound to the frame they were
measured on (V8); the task check reads only inside the crop the critic sees (V5); similar reference
screens need a declared reason (D6); sheets are content-named and verdicts append-only (D8); the slot
draw uses an injectable RNG whose sequence is pinned (D4). **Pinned by** `node review/blind-pair.mjs
--selftest` (the 30-row `VALIDATOR_CASES` table) and `node review/capture-refs-clean.mjs`'s self-check,
each mutation-checked (reported). **Not closed:** Q-G's second verifier found three majors — a loss
vanishes through the key it is stored under, a sheet reference other than the exact current sha, or a
named product under `recognized: false` (O70). Current sheets: `1061fdea`, dirty tree, 8 sheets for 4 of 5
pairings; network visualisation is BLOCKED because our `08-path-indeterminate` frame rendered at tier
"balanced" on a 100 %-busy host. **No critic panel has run (owner instruction), so C1 stays UNPROVEN.**

### R128. D3 focus-audit hardening — the drawer palette case driven, surface discovery by effect, shape 6 by DOM effect, dialogs by rendered primitive, the act tripwire's aliases, and a Popover that left its panel off screen — FIXED IN CODE AND THE HARNESS (Q-H; its fix agent stopped before returning); THE AUDIT ITSELF IS UNPROVEN AT THIS TREE (O68)
**Q-H (phase 3.5, reported; phase 3's P3H never returned).** Fixed, each with its pin:
- **R5-V2-2.** A reopened palette started from the previous opening's query; `CommandPalette.tsx` resets
  it on close. Pinned by `src/app/CommandPalette.test.tsx` ("a reopened palette never starts from the
  previous opening's query"). The drawer case "open by palette → focus inside → close by palette" is
  recorded PASS at 1024, 1152 and 1270 px in `sweep-full-1` and `sweep-full-4`.
- **R5-V2-4, R5-V2-5.** Guard shape 6 classifies an imperative hide by its DOM effect, and a resize-hidden
  rail's successor no longer depends on history (the `layoutChanging` token in `focus-return.ts`). Pinned
  by `src/app/focus-return.guard.test.ts` (planted shapes, including the forms the first verifier found
  unflagged — a style-object alias, `classList`, `className` and `dataset` writes, QH-V1-5).
- **R6 VR2-2, VR2-3.** The palette pre-warm suite runs on fake timers, and modal dialogs are found by the
  rendered primitive (`review/palette-warm.mjs` `modalDialogsIn`, now including `role="alertdialog"` and a
  native `<dialog>` opened with `showModal()`, QH-V1-6). Pinned by `src/app/CommandPalette.test.tsx` (the
  planted census: `DialogFrame`, aliased and namespaced imports, `createElement`, wrappers, re-exports).
- **R7-V2-1…5.** The act tripwire flags `import a2 = React.act` and `export import`, mocks that void a
  proof, carrier literals, factory-by-name and template-`require` forms, renamed destructuring and typed
  aliases; the scripts type-check builds its programs in `beforeAll`. Pinned by
  `src/core/source-hygiene.test.ts` and `src/core/scripts-typecheck.test.ts`.
- **R9 m1, m4, manifest prose.** `node review/capture.mjs selftest` gained the sticky-footer and fixed-top-
  bar cases, measures covers with the product's own `paintedBox`, and fails on manifest notes that restate
  sample facts.
- **A Popover whose trigger scrolled out of view during a resize anchored its panel at the viewport
  edge** (found by the audit at 390→768 and 1152→768 on a traced flow). Pinned by
  `src/ui/primitives.test.tsx` ("keeps the panel inside the viewport when its trigger is BELOW/ABOVE it").
- **Harness, in `f24b9ccb`, not proved by any completed audit run:** surface discovery by effect,
  including `aria-pressed` revealers such as "Show the 3-D fabric" at 390 px (QH-V1-2); crossings at the
  shortest rung height instead of one 900 px height (QH-V1-4); a shared task pool; draws suspended in the
  geometry passes, with `--render-check` comparing modes.
The QH-V1-2, V1-4, V1-5 and V1-6 changes are the stopped fix agent's: they are in `f24b9ccb`, the second
verifier read that tree and raised no defect against them, and no verifier has stated them correct.
**R9 m3 (pointer-events:none covers counted by the navigation guard)** is closed only in the uncommitted
gate tree (R129). **The audit is UNPROVEN at the current tree** (O68).

### R129. The phase-3.5 close gate's repairs — every vitest red at `f24b9ccb` fixed, the navigation guard counts pointer-events:none covers, and source-reading tests find the dataset's source by digest — FIXED IN AN UNCOMMITTED WORKING TREE, NOT INDEPENDENTLY VERIFIED (the phase-3.5 close gate, 2026-09-30)
Reported by the gate agents; the record step read the diff against `f24b9ccb` (18 files) and did not
re-run the suite. With these repairs the full suite passed on all four legs (the banner).
- **F2's module-mocking declaration.** Eleven mocking files added in phases 3 and 3.5 were undeclared, so
  `src/core/mock-classification.test.ts` was red from `1061fdea`; `docs/acceptance.md` F2 now declares
  each with what it replaces.
- **`src/core/tracked-sources.test.ts`** pinned Inspector's `import.meta.glob` edge, which phase 3 removed
  on purpose (P3A1-V2-5); it now pins that the sidecars reach the build only through
  `core/dataset/bundled.ts` and that the glob has not come back.
- **`src/app/verdict-scope.b2.test.tsx`** cut the scope clause at the claim's first comma, inside the host
  list (QH-V2-6, P3A2-V2-m3); it now ends at the parenthetical and must equal the engine's
  `scopeClauseOf`.
- **`src/app/Header.focus-return.test.tsx`** was red from `1061fdea` because jsdom has no default Tab
  action and the provenance panel now holds three controls (QH-V2-6); its `tab()` moves focus as a browser
  does only when no handler prevented the key, and the walk's length is pinned to the panel's controls.
- **`src/panels/DataGrid.tsx` `uncovered()`** now makes every element take part in hit testing for the
  duration of its probes, so a `pointer-events: none` cover is counted (R9 m3, QH-V1-3, QH-V2-4); the
  strict `capture.mjs` selftest case passes (49 of 49 in the gate run, after this change).
- **The rename and golden legs.** `src/panels/source-snapshot.ts` and a new
  `src/test-support/dataset-source.ts` find the dataset's source by the digest the model binds, so 30
  invariant tests are no longer named skips on the rename leg; `provenance.test.ts` and
  `compile-model.test.ts` read the tracked model from disk instead of through the overridable import;
  `composite-tabstop.test.tsx`, `self-removing-focus.test.tsx` and `scale.test.ts` choose their device by
  property, not by `core1` or index 12.
- **A product fix the rename leg found:** the Evidence pane's "Select <host>" button hides its own pane,
  and the press left focus on `<body>`; it now hands focus on through `handOffFocus`, which skips
  `hidden` subtrees and walks outward to the next shown landmark (`src/app/focus-return.ts`). O77 records a
  defect in that change.
- **`review/blind-pair.mjs` typed the sample's 8-hex snapshot tag in a comment**, which
  `src/core/provenance.test.ts` refuses in authored code; the comment now says "the 8-hex snapshot tag".
- **`src/fabric3d/layout.test.ts`'s counted work budget** was exceeded on the 7-device golden; the gate moved
  it to the golden tier rather than widening it — an OPEN finding, not a fix (O74).

> **Phase 2.75 of the single-source-of-truth program — engine finalisation before the fleet
> regeneration (recorded 2026-09-28; an UNCOMMITTED working tree on top of `8bf5500b`).** Two clusters,
> each followed by an independent verifier: **T1** (the golden snapshot's calendar boundary) and **T2**
> (the sample fleet's core-to-core OSPF home, core1's BGP baseline, and three RIB-completeness test
> gaps). Entries R116–R119 below record what they closed, and O63–O67 under Open what they left; O53
> and O54 carry status notes. **Verdicts:** T1 and T2 both upheld by their verifiers, each with open
> items. **Owner decisions** (design brief, "Owner decisions of phase 2.75"): the golden has no
> wall-clock boundary; the core-to-core OSPF home is an existing SVI (Vlan10); core1's BGP baseline is
> honestly INDETERMINATE because its config capture is incomplete. **Phase 2.5 (`8bf5500b`) has no
> record of its own in this file.** Its verifier identifiers (R1V2-4, R2V-1, R2V-2, R2V-3) appear below
> only where a phase-2.75 cluster closed them; the rest of that commit message's "Known open" list —
> the D3 rung-crossing surfaces taken from a named state list and one drawer case not driven, the act
> tripwire's import-equals and `vi.mock` gaps, the tier-fade slot tripwire's indirect calls — reached
> the record step only through that commit message and is not recorded as entries here. **Not a
> re-grade:** no criterion moves, and the tracked sample fleet was NOT regenerated, so every figure
> from a regenerated fleet below is a scratch run (reported). **What the record step itself re-ran**
> (2026-09-28, on this working tree): the engine pins the entries cite —
> `tests/test_eol_registry_freshness_clock.py`, `tests/test_sample_fleet_substrate.py` and
> `tests/test_pipeline_golden.py` in one `pytest` invocation, 78 collected (21, 36, 21), 78 passed,
> exit 0 — and `src/forwarding/rib-completeness.test.ts` with `src/forwarding/rib-partial-route.test.ts`
> in one `vitest` invocation, 44 of 44, exit 0. After this record's edits, every test file under `src/`
> that reads these documents (26 files, 1,568 tests) passed in one `vitest` invocation, exit 0.
> **Reported, not re-run by the record step:** the scratch
> fleet regeneration and its forwarding sweep, the extra golden run at 2036-06-01, the mutation checks
> (MD, MF) and every red-before-fix claim. The working tree also holds changes no cluster report
> describes — `cisco_toolkit/fhrp_redundancy.py` and a new `tests/test_fhrp_member_key_order.py` — so
> they are not recorded as a fix (O67).

### R116. The golden snapshot's `data_authorities` registry-health statement was judged against the wall clock, so the golden would go red from 2027-01-26 — FIXED FOR THE GOLDEN ONLY, by pinning the registry freshness clock to the golden's evidence date in the test harness; the owner's prescribed mechanism was not used and awaits ratification (O63) (phase-2.5 verifier R1V2-4; T1)
Carried from `8bf5500b`'s "Known open": "the golden's EoL-registry freshness is judged against the
wall clock (red from 2027-01-26)". **The owner's direction** was to normalise only the now-relative
fields of `data_authorities.eol`. **What T1 measured instead** (reported; its verifier reproduced that
the deviation is needed): the five fields `registry_integrity.source_freshness` derives from "now" —
`source_age_days`, `source_fresh`, `source_stale`, `source_future_dated` and `freshness_status` —
cannot make the golden date-independent. Past the window a stale registry cascades into
`assessment_integrity` (three failed phases), every authority's status / authoritative / integrity /
error / record-count fields, `schema_census`, `service_map`'s authority flags and a new "Assessment
Integrity" workbook sheet; with exactly those five stripped, a run past the windows still differed in
four snapshot sections and one sheet. Normalising the cascade field by field would be a hand-kept
list standing in for its cause. **Fix (test-only):** the golden harness pins the one registry freshness
clock — the module clock `registry_integrity.datetime`, which `source_freshness` reads, and through it
eoldb, ouidb/portdb (via `_build_provenance_authority`) and analyze — to the golden's evidence date
(`tests/test_pipeline_golden.py` `_GOLDEN_REGISTRY_CLOCK`, derived from `_GOLDEN_COLLECTION_STAMP`), in
the pipeline subprocess's bootstrap. No `data_authorities` field is popped or normalised: every one,
the five now-relative ones included, stays frozen as a pure function of the pin. The engine's
wall-clock freshness semantics are unchanged, and no engine clock seam was added. T1 verified the
interrupted agent's partial work rather than trusting it, and created the clock test file that agent
had cited but not written. The golden was not regenerated: it already matched, and its semantic diff
against `8bf5500b` is purely additive (3 `source_age_days` values, matching the arithmetic); a
regeneration would only reshuffle the hash-seed-dependent FHRP key order (O67). **Pinned by**
`tests/test_pipeline_golden.py::test_golden_does_not_depend_on_the_wall_clock_past_every_registry_window`
(the whole process clock 30 days past the last registry window, 2027-02-25: every snapshot section
and the sheet schema equal the golden; an extra run at 2036-06-01 also differed in nothing,
reported), `::test_golden_registry_clock_is_inside_every_published_registry_window` (every published
authority is read from the run and its verdict re-derived by arithmetic; it names the refresh remedy,
O63), and the new `tests/test_eol_registry_freshness_clock.py`: fresh, exact-boundary, stale and
future-dated verdicts through an injected clock, each expected verdict derived by arithmetic from the
registry's own published retrieval time, maximum age and skew — never by calling `source_freshness` —
over every published authority rather than a hand-kept list (only the EoL-specific phase-name
assertion names a registry). Its pipeline-level cases run the process wall clock on the opposite side
of the window from the registry clock, at a mid-window instant (retrieval + 90 days), so they do not
repeat the golden's own run. The calendar test `test_golden_is_inside_the_retained_eol_registry_freshness_window`
is deleted (the record step's `git grep` finds it nowhere), and `docs/ssot.md`'s "Per-finding
evidence pointers" row now cites the tests above. **Not closed here:** the same calendar boundary in
the engine's other EoL/data-authority tests (O63).

### R117. The sample fleet's core-to-core OSPF adjacency ran over a transit VLAN (900) added only for it, which also joined the core move group — FIXED at the source by owner decision: it now runs over Vlan10, an SVI both cores already have on a VLAN Po1 already carries, and VLAN 900 is gone (T2; the phase-2.5 gate's `move_groups` stillRed item CLOSED)
The phase-2.5 substrate gave core1's FULL/DR neighbour 10.0.99.2 (O53's B1 seed) an L3 home on a new
VLAN 900 CORE-TRANSIT SVI pair on 10.0.199.0/30; `8bf5500b`'s "Known open" notes that it added VLAN
900 to the core move group. **Owner decision (phase 2.75):** home the adjacency on an SVI the cores
already have. **The choice is derived, not hand-picked:** the test derives the candidates from the
pre-substrate fixtures — an SVI on both cores, in one shared subnet, on a VLAN Po1 carries on both
sides, with no inbound ACL. Vlan10 and Vlan20 pass the first three; Vlan20 fails the last: core1
Vlan20 has `ip access-group VOICE_FILTER in`, which permits only UDP from 10.0.20.0/24 and then denies
`ip any any`, so OSPF hellos (IP protocol 89) would be dropped — consistent with the fixture's own
core1 `show logging`, which records the Vlan20 adjacency to 10.0.99.2 going down on its dead timer.
Vlan10 has no ACL on either core and keeps HSRP group 10 unchanged (core1 active at priority 110,
core2 standby); core1 is 10.0.10.2, core2 10.0.10.3; core2's router ID 10.0.99.2 is higher than
core1's 10.0.99.1, so core2 is the DR and the FULL/DR row stays consistent. **Edits
(`webapp/sample_data/build_sample.py`, reported):** every VLAN 900 trace is removed — SVI stanzas, trunk
allow-lists, switchport, `show vlan brief`, `show ip interface brief`, the 10.0.199.0/30 routes in all
four tables, and the builder constants; each core's existing Vlan10 stanza gains only its OSPF enable
(IOS `ip ospf 1 area 0`; NX-OS `ip router ospf 1 area 0.0.0.0`). With Vlan10 in area 0, dist1 and
dist2 hold 10.0.10.0/24 intra-area (`O [110/2]` and `[110/3]`) instead of `O E2`, each route type
derived by the test from core1's configuration; core2 learns core1's originations via 10.0.10.2 on
Vlan10. Only core1's `show ip route`, `show ip ospf neighbor`, `show ip interface brief`, `show
running-config`, `show running-config | section ^interface`, `show ip bgp summary` and `show ip eigrp
neighbors`, and core2's `show ip route` and `show running-config interface`, change; every L2 capture,
FHRP included, is byte-identical. One stale test comment ("far end of core1's transit SVI") now reads
"inter-core OSPF session on Vlan10"; `src/forwarding/rib-completeness.ts` needed no change
(byte-identical to `8bf5500b`). **Scratch regeneration** (reported; the tracked fleet was NOT
regenerated): `cable_map`, `move_groups`, `wave_sequencing`, `failure_impact` and `link_centrality`
byte-equal to the committed fleet; the punch list 146; core1/core2 health 3/88. **Pinned by**
`tests/test_sample_fleet_substrate.py` (36 of 36 re-run by the record step):
`test_the_home_is_an_svi_both_cores_already_have_that_po1_already_carries`,
`test_core1_inter_core_ospf_session_runs_over_the_home_svi`,
`test_core2_owns_the_far_end_of_the_home_and_holds_what_core1_advertises`,
`test_only_the_cores_l3_captures_change`,
`test_the_core_fhrp_groups_and_every_other_core_capture_line_survive` and
`test_no_trace_of_the_retired_vlan_900_transit_remains`. `move_groups`' byte-equality rests on that one
scratch run; the pytest guard stands on a named list (O64). A tracked test header still describes VLAN
900 (O65). What this unblocks for A2 and B8 is O53's status note.

### R118. core1's BGP configured-peer baseline reads INDETERMINATE on the substrate fleet — NOT A DEFECT: the coverage-honest verdict, kept by owner decision and pinned with its cause (T2; the phase-2.5 gate's `bgp_configured_peer_baseline` stillRed item CLOSED as accepted-honest)
Carried from `8bf5500b`'s "Known open": "core1's config capture lacks 'end', which leaves the BGP
baseline INDETERMINATE". **Owner decision (phase 2.75):** keep it. `end` was NOT appended to core1's
running-config; the fixtures' no-`end` convention stands, the capture is incomplete, and the baseline
says so. **Pinned by**
`tests/test_sample_fleet_substrate.py::test_core1_bgp_baseline_is_honestly_indeterminate_because_its_config_capture_is_incomplete`:
verdict INDETERMINATE with `assessed` False and exactly one row — core1, peer 10.0.10.254, ESTABLISHED,
`not_verified`, finding `capture_not_verified`, acceptance NOT VERIFIED / BLOCKER. The reason is read
from the producers' own output, not restated: the baseline's coverage `config_capture_status` equals
the capture-integrity finding's status for core1 `show running-config`, and that finding equals
`inspect_capture`'s status, reason and evidence. **Counterfactual:** the same collection with only
core1's capture terminated is CLEAR and assessed, so the capture is the whole reason.
`test_the_bgp_configured_peer_baseline_validates_over_the_substrate_collection` (the validator's "valid,
ok") is kept, and its docstring now says that is not a clean verdict. The committed fleet reads
NOT_APPLICABLE until phase 3 regenerates it.

### R119. Three RIB-completeness test gaps — the contract filter never tested through the module's own state set, an unrecorded route source untested, and a real-data sweep that never checked that the table holds the link — FIXED in the tests; R2V-3 carries a sha-bound exemption for the committed fleet that phase 3 deletes (phase-2.5 verifier R2V-1, R2V-2, R2V-3; T2)
All in `src/forwarding/rib-completeness.test.ts` (re-run by the record step, see the banner);
`src/forwarding/rib-completeness.ts` is unchanged.
- **R2V-1 — the contract filter is live.** "the contract filter is live: an absence state the engine
  retires or renames stops vouching, through RIB_ABSENCE_STATES itself (R2V-1)": `vi.doMock` of
  `contracts/engine-contract.v1.json` with one absence state renamed (`not_running`, then
  `captured_empty`), then a fresh import of the module; the renamed state leaves
  `RIB_ABSENCE_STATES`, and the synthetic host whose completeness rested on it reads incomplete, citing
  that row. This follows the verifier's alternative fix hint, so the module needed no change. Mutation
  MD now kills 2 tests (reported). Declared in acceptance F2 as a fault injection.
- **R2V-2 — an unrecorded source.** "a learned route whose source the engine recorded as nothing is an
  unknown protocol, never a known one (R2V-2)": two synthetic hosts with a learned route whose source
  is null or `''`; each is a reason citing the route, and the basis vouches for no family. A
  precondition test reads `cisco_toolkit/parse.py` and confirms that `_nxos_route_source` passes its
  normalised token through, so `''` is reachable. Mutation MF now kills 2 tests (reported).
- **R2V-3 — the held-link sweep on real hosts; closes O54's last bullet's second half.** "the held-link
  sweep reaches REAL hosts' sessions, read from the compiled file on disk -- no synthetic host counts
  (R2V-3)" reads the compiled `rib-evidence.json` from disk, counts only real hosts (none may carry a
  `t-` prefix), and requires every uncited real up session to hold its link; on any fleet other than
  the tracked pre-substrate one, at least one uncited real session with a recorded interface AND one
  without must reach the held-link branch. **The exemption:** the tracked compiled data (`sourceSha256`
  `9580aa09…`, the committed fleet), whose only real up session is core1's FULL/DR neighbour on Po1 —
  cited, not held — is exempt; the exemption is bound to that exact sha and re-checks its own reason
  (every real up session not held, none uncited). On the regenerated fleet compiled in scratch, 6 real
  sessions reach the branch (reported). Phase 3 deletes the exemption.

> **Phase 2 of the single-source-of-truth program (recorded 2026-09-27; an UNCOMMITTED working tree).**
> Atlas Scope no longer lives in its own repository: it was imported with its history as the parent
> repository's `atlas-scope/` directory (`f036ed77`), and its compilers bind to that tree's engine output
> (`docs/acceptance.md`, F section, "Updated 2026-09-27"). Phase 2 ran seven clusters, each followed by an
> independent verifier: **E1** (the engine publishes per-finding evidence pointers — the producer half
> of A1), **E2** (a forwarding substrate in the engine's sample fleet, and the RIB-completeness rule),
> **S1** (the compiler: one set, one binding, the evidence contract), **C2** (the state-06 tab strip cut
> at 1440), **C5** (the stepped, capped tier cross-fade), **D3** (Escape and the evidence drawer) and
> **E2E3** (the cold first palette open). Entries R109–R115 below record what they closed, and O50–O62
> under Open what they left; O12, O13, O16 and O34 carry status notes. **Verdicts:** E1 and C2 upheld by
> their verifiers; E2, S1, C5, D3 and E2E3 verified with defects, which are fixed where an entry says
> FIXED and open where it says OPEN. E2, S1 and E2E3 closed PARTIAL. **Not a re-grade:** no criterion
> moves here. **What the record step itself re-ran** (2026-09-27, one `vitest` invocation on this
> working tree): the 14 atlas-scope test files the entries below cite as pins — 482 tests, 477 passed,
> 5 failed, 0 skipped. The 5 failures are exactly `compile-all.test.ts`'s R6 block over the repository
> golden, which S1 left strict and red until the owner decides (O51). It also re-ran the suites that read
> these three documents (`journey-scope`, `motion-inventory`, `mock-classification`, `source-hygiene`,
> `claim-lint`, `emphasis`, `acceptance-gates`); before this record two of them were red on
> `acceptance.md` (the missing `J5-first-open-palette` bullet and the undeclared module-mocking
> `src/forwarding/rib-completeness.test.ts`). After this record's edits, those seven plus every other
> test file that reads these documents (16 files, 378 tests) passed in one invocation, 0 failed, 0
> skipped — including §4.8's settle check, now exact for `TIER_FADE_MS`. **Reported, not re-run by the
> record step:** every engine-side (Python) test, every browser
> harness (`capture-motion.mjs`, `audit-d3-focus.mjs`, `capture.mjs`, `measure-inp.mjs`), the mutation
> checks and every red-before-fix claim. **The input was cut short:** the record step's cluster reports
> ended inside E2E3's second open item; anything after that point is not recorded here (O62). The
> working tree also holds changes no report the record step received describes — for example the
> act-scope and timeout-floor notes in `vitest.config.ts`, `src/test-setup.ts` and
> `src/test-support/act-turns.ts` beyond D3-V2's use of it — so they are not recorded here either.

### R109. A1, producer half — the engine published no per-finding pointer to the record a finding was derived from; it now publishes one on every punch-list row, and E1's verifier round fixed the pointers that did not survive publication — FIXED IN THE ENGINE; A1 does not move until Atlas Scope renders them (O12, O50)
The gap O12 has carried since wave 1: "Closing A1 needs the engine to publish per-finding record
pointers." **What the engine now publishes** (E1, reported): every punch-list row carries
`evidence_basis` (`record` / `row` / `absence`) and `evidence_refs`, elements `{kind, host, ref, role,
cite}` whose `ref` is an RFC 6901 pointer into the same snapshot, with `evidence_refs_total` only when a
list is capped. **Census** (a scratch sample built by the HEAD builder, after the repair round): 146
punch rows, every one with both keys; 572 refs, at most 28 on a row, none capped; basis `record` 52 (49
through interface rows, 3 through `config_text`), `row` 88, `absence` 6 (five security absence checks
and F142 "No QoS configured anywhere", absence-only with 18 `per_device` witnesses); 0 unresolved or
wrong-record refs in the on-disk, redacted, explorer-embed and explorer-embed-redacted forms.
**Defects the verifier found and E1 fixed:**
- **V1 — an index into a list a published consumer re-filters.** The L1 fold cited
  `/physical_health/<k>`; the explorer embed re-filters `physical_health`, so the index named another
  row there. Fixed by dropping that ref (the key-addressed interface record already makes the row
  `record`). The test now checks the REAL explorer embed extracted from `write_html_explorer`'s output,
  not only `_slim_for_embed`, so any future index into a re-filtered list goes red.
- **Receipt folds pointed at the raw current-run receipt, not at what is published.** The VTP and IPv6
  folds now compute their pointers against `embedded_vtp_safety_baseline(receipt)` and
  `embedded_ipv6_routing_adjacency_baseline(receipt)`, matching rows by value and ignoring only the
  `projection_custody` stamp the embedding rewrites; on a rejected receipt the published projection is
  empty, so no witness is emitted rather than a dangling one. On valid receipts the golden's refs are
  unchanged (the only golden difference from round 1 is the two L1 `physical_health` refs).
- **V4 — `deduction_refs`** keeps the list-of-refs shape S1 compiles against, with documented
  subsequence semantics, rather than null placeholders (a null would break the `{kind, host, ref,
  role, cite}` element contract).
- **Identity is checked by class first:** the nearest device-owning node on the pointer path must name
  `ref.host`, or the host must be a path token; an own-row table is an additional check only for each
  fold's derived-from row, which the host check cannot tell from a same-host sibling.
- **V5 — CL-02 honesty, no engine change:** a test pins that every record-kind ref on a `record` CL-02
  row is `role: derived_from` and cites the graph cut.
**Pinned by** `tests/test_punchlist_evidence_refs.py` (a real pipeline run in six forms with the
identity checks; a real-producer fleet for Addressing, Trunk, Link L1, Inventory, VTP, Coverage,
Timing-PTP and Multicast-Media; the rejected-receipt and IP-literal-hostname cases) and
`tests/test_pipeline_golden.py::test_every_punchlist_evidence_pointer_resolves_on_the_published_snapshot`
(reported). **MCP exposure** (E1's decision, reported): `get_finding` returns whole rows, so the keys
reach MCP clients; they carry only pointers built from hostnames, port names, section names, VLAN ids
and indexes, and cites of the same material — no config values, and no IP other than a hostname that is
itself an IP literal (already a snapshot key, and rewritten consistently by redaction, which a test
proves); a `config_text` pointer points AT a config line and does not copy it. The golden files
`UPDATE_GOLDEN=1` wrote on Windows were CRLF and were normalised to LF; `sheet_schema.json` ends
byte-identical to HEAD. **A1 does not move:** the committed sample is not yet regenerated, and Atlas
Scope compiles the contract but does not render it (O50). The residuals are O52.

### R110. E2 — a RIB-completeness rule checked each protocol FAMILY, so one family's routes vouched for a session whose link the table did not hold, and a denial read as decided — FIXED per session (`src/forwarding/rib-completeness.ts`), with the basis no longer listing a family a reason concerns (E2-V1, E2-V3)
Found by E2's verifier (E2-V1), reproduced by the cluster: on the regenerated fleet, under the
per-family rule, `tcp/443 10.0.30.50 -> 10.0.99.2` was a decided REFUTED denial, because dist1's OSPF
routes let the rule treat core1's OSPF family as accounted for while core1's own FULL/DR adjacency with
10.0.99.2 on the L2 trunk Po1 ran over a link core1's table does not hold — the B1 seed coming back.
**Fix (reported).** Every session is checked individually: OSPF
FULL/2WAY, EIGRP up, or an Established BGP peer (any numeric State/PfxRcd, 0 included) must run over a
link the table holds — for a record that names an interface, a connected route on that interface
covering the neighbour's link address (`address`; for EIGRP and BGP, whose records name the neighbour by
address, `neighbor`); for a session with no interface (BGP), some route covering the peer. Interfaces
match by structure (`Po1` = `Port-channel1`), not from a list. A family teaches a host no routes only at
`captured_empty`; a record without its link fields leaves that session UNKNOWN, never complete. The kept
per-family rule ("exchanging, but no route of its family") runs first, so each session gets exactly one
reason. `ribCompletenessBasis` now leaves out every family any reason concerns — its row, its sessions'
routes or links, or its overlay peers — and a reason that applies to all families empties the basis
(E2-V3); the public `RibIncompleteness` shape `{label, cite}` is unchanged. The new label keeps the
phrase "FULL/DR, yet the table…", so `PathTrace.claim-cites` B6(b) still passes on the regenerated data.
Boundaries, stated in the rule: below-2WAY states imply no link; an unnumbered interface reads as
incomplete (conservative); a BGP peer covered only by the scoped table's default route counts as
reached (O54). **On the committed snapshot the change alters no label and no verdict** (reported: every
label byte-identical). **Pinned by** `src/forwarding/rib-completeness.test.ts` — 23 of 23 re-run by the
record step, including "every session a host holds implies the link it runs over — checked per
adjacency, not per family (E2-V1)" and "the basis never lists a family whose own adjacency is what makes
the table incomplete (E2-V3)" — and by `src/forwarding/rib-partial-route.test.ts` (2 of 2 re-run), the
HEAD real-data B1 assertions restored plus a pin that `routing_neighbors.core1.ospf[0]` is among
core1's reasons: green on both fleets, red with the per-family rule substituted (reported). The
implementer's counterfactual block in that file is removed: under the per-session rule it was a no-op on
both fleets, and it had hidden E2-V1. **Attribution of the regenerated-data reds** (reported): 41 tests
fail across the 24-file set on the regenerated fleet under this rule — the identical 41 that fail there
under the HEAD rule, so purely data-driven; the 14 the implementer called "premise" failures all pass
again, and the label rephrase fixed one more, so 40 remain for phase 3's regeneration. The residuals
(the fixed family vocabulary, the default-route boundary, the class sweep's unchecked half) are O54.

### R111. E2 — the sample fleet's first forwarding substrate carried routes nothing originated, a BGP peer nothing reached, and running-configs that did not end, which hid an engine defect — FIXED at the source (`webapp/sample_data/build_sample.py`) (E2-V4, E2-V5)
The substrate (`_add_forwarding_substrate`, reported) gives dist1/dist2 routing tables, ACLs and OSPF
adjacencies, with no fabricated EIGRP or BGP. **E2-V4, fixed in deep copies:** dist1/dist2 now hold
core1's VLANs 10.0.10/20/30 as `O E2 [110/20]` (core1 brings them into OSPF only by `redistribute
connected`; its one area-0 interface is Gi1/0/40); core1's config gains `default-information originate`,
so the dist pair's `O*E2` default has an originator; the BGP peer is eBGP multihop 2 behind core1's
existing upstream next hop (`ip route 203.0.113.1 255.255.255.255 10.0.10.254`, and `S 203.0.113.1 [1/0]
via 10.0.10.254` under a "203.0.113.0/32 is subnetted" header, which the parser handles). Deliberately
NOT fixed: core1's EXSTART/DROTHER neighbour 10.0.40.9 on Vlan40, a pre-existing fixture seed of a stuck
adjacency that the rule's boundary does not read (O54). **E2-V5:** `_dist_running_config` now ends with
`end`. That exposed a real engine defect the truncated v1 configs had hidden — `bgp_intent.py`'s
producer and validator disagree on a peerless host with an empty BGP summary (O54) — pinned as a strict
xfail. **E2-V2 reconciled, not changed:** `capture_integrity`'s "empty" is the same whitespace-only
observation `cmd_capture_state` classifies as empty and `compute_protocol_assessability` calls
`captured_empty` — not an independent truncation or error tripwire — and the test pins that the only
empty captures the substrate authors are the five intended neighbour tables. **Engine-side census**
(scratch HEAD engine, reported): 36 of 117 sections change against no substrate; `cable_map`,
`move_groups`, `wave_sequencing`, `failure_impact` and `link_centrality` byte-equal, `health_scores`
unchanged; the punch list stays at 146 with two rows reworded (native VLAN 1 on 27 -> 26 ports; "No QoS
configured anywhere" 18 -> 20 assessable devices); `capture_integrity` `n_incomplete` 18 (unchanged),
`n_empty` 5 (the owner-directed empty EIGRP/BGP tables on dist1/dist2 and EIGRP on core1), the dist
running-configs integrity-ok; the output has 0 CR bytes and 0 client-marker hits. **Pinned by**
`tests/test_sample_fleet_substrate.py` (reported). What the substrate does NOT yet deliver — decided
core1 outcomes — is O53.

### R112. S1 — the compiler's verifier found ten defects: tests that compiled a fabricated shape, output that could land in tracked or bundled directories, a per-file command that could leave a mixed set, rollbacks that could lose the only copy, an input blamed for a compiler bug, untracked files labelled as repository files, and refs to null accepted as evidence — FIXED (S1-V1 to S1-V10)
All reported by S1 and its verifier; the pins re-run by the record step (see the banner).
- **S1-V1 — the table tests.** They are insulated by stripping ONLY the three evidence-contract keys
  from the golden's punch rows — the pre-contract producer shape, not a fabricated fixture; the golden
  AS PUBLISHED stays under one strict R6 test, red until the owner decides (O51). Resolving pointers
  against a stripped document, or dropping unresolvable refs, was refused as a weakening.
- **S1-V2/V4 — output placement.** `--out` is judged on the canonical path by whole segments; a path
  component ending in a dot or a space is refused. For any non-sample source the refused class is "any
  repository directory Git does not ignore"; `.local-data/` is special-cased so the rule does not depend
  on Git being present; the sample keeps its freedom outside `src/` (`E_OUT_REFUSED`, exit 2). Pinned by
  `compile-all.test.ts`, "in the real repository, a Git-ignored directory is accepted and a tracked one
  refused (S1-V4)" and its neighbours.
- **S1-V3 — mixed sets.** A per-file command refuses with `E_MIXED_SET` rather than silently writing all
  four; an absent sibling is allowed (a missing file breaks the build loudly), which keeps provenance's
  per-compiler sandboxes valid. Pinned by "a per-file command refuses to leave its file bound to a
  different snapshot from its siblings (S1-V3)", with its positive control.
- **S1-V5 — rollback.** Restore renames `.prev` over the new file in one step, guards each step, and
  keeps the staging directory whenever a restore failed (`E_ROLLBACK_INCOMPLETE`, naming where the
  previous files are). Pinned by "a rollback that cannot complete keeps the previous file and names where
  it is (S1-V5)".
- **S1-V8 — blame.** Only a `TypeError` is blamed on the input, as `E_SNAPSHOT_SHAPE` worded "input
  shape or compiler defect", with the `TypeError` kept as its cause (`CompileError` gained
  `options.cause`); any other error propagates unchanged. Pinned by `compile-validate.test.ts`, "only a
  shape failure is blamed on the input (S1-V8)".
- **S1-V9 — origin.** `sourceOrigin: "repository-file"` means a file Git TRACKS in this repository;
  an untracked or ignored in-repository file is `"external-file"`, named by basename and bound to its
  bytes as read. Origin is decided by Git tracking only where Git's top level IS this repository;
  elsewhere (a copied package, a sandbox) by containment, which keeps O15's CRLF/LF sandbox tests
  valid. For a repository file `sourceExactSha256` is over the Git-stored blob, the LF form, so it equals
  `"sha256:" + sourceSha256` (O15; the conflict with R3's "exact bytes" is O55). Pinned by "an UNTRACKED
  file inside the repository is an external file, bound to its bytes as read (S1-V9)" and its tracked
  control, and by `compile-binding.test.ts`.
- **S1-V10 — producer prose and null refs.** Producer prose is carried verbatim. A ref must resolve to
  a NON-NULL value — the engine's own contract (`tests/test_punchlist_evidence_refs.py`,
  `punchlist_evidence_problems`) — because citing a present key holding null would render absence as a
  record; this supersedes the implementer's "null accepted". Pinned by `compile-evidence.test.ts`, "a
  pointer to a null value is refused; the same pointer to a value compiles (control)".
Carried forward as a contract note for E1: refs should point at records (`/interfaces/<h>/<port>`), not
at sparsifiable fields — the engine's on-disk writer drops `''` fields and `run_config_observed: false`,
and a pointer to a dropped field would not resolve in the compiled source. The residuals are O55.

### R113. C2 — in state 06 at 1440, the tab strip above the findings grid was sliced by 19 px when the priority queue restored its act view — FIXED at the root cause, "fit first", with a class guard keyed by ARIA role (acceptance-report C2, state 06)
**Cause** (C2, independently verified, reported): the queue's act-view restore went through
`DataGrid`'s `revealBelowHeader` NESTED PORTS branch and scrolled Rail A 19 px, although the grid's own
51.3 px band could hold the 40.4 px F001 row. **Fix:** the reveal fits first — the rail moves only when
the grid's band cannot hold the row. **Class guard:** no ancestor or document half of a reveal leaves a
`[role=tablist|toolbar|menubar]` partly visible — keyed by ARIA role, not by a list of panels.
**Verifier follow-ups, each fixed with red-before evidence (reported):** (V1) the generated-family test
is split into 54 per-group tests plus a denominator test, which runs any group not yet run so it is
never vacuous under `-t`; the slowest C2 test took 1.7 s in a full loaded run. (V2) The remainder a
reveal hands outward can no longer change sign — clamped, which keeps every existing case bit-for-bit —
so taking the strip out never makes the document scroll back; the family now runs inside a scrolled
document and includes the full-height rail shape, so "the document never moved" can fail. (V3) The
`landOnAnswer` call sites of `landingInset` are pinned by an integration test over the real denied
trace. (V4) The path mode panels' scrim cover is the path surface's own ground (`var(--bg)`, read from
`PathTrace.css` by the test), not the rail's `--surface-1`. **Pinned by**
`src/panels/DataGrid.c2-chrome-slice.test.tsx` (62 of 62 re-run by the record step) and
`src/panels/PathTrace.c2-landing.test.tsx` (9 of 9 re-run), and by eight C2 mutations in
`review/mutation-check.mjs` (`c2-reveal-rail-first`, `c2-reveal-cuts-nav-strip`,
`c2-landing-slices-previous-control`, `c2-mode-panel-without-scrim`, `c2-reveal-overshoot-scrolls-back`,
`c2-landing-head-fixed-pad`, `c2-landing-decided-fixed-pad`, `c2-scrim-cover-rail-fill`), all KILLED on
2026-09-26 (reported). **Harness:** `review/capture.mjs`'s `readScrollEdge` (`chrome-sliced` and
`moved-port-top-slice` blocking) runs in `text` and `app`; `text` covers one width in each ladder band,
90 states. A release server another agent held on :4181 (an isolated E2E3 build without the fix) still
showed "moved-port-top-slice routes.core1[6]", so the detector does catch the sliver (reported). The
final browser checks ran on an isolated scratch build on :4195. The residuals are O56.

### R114. C5 — the quality-tier cross-fade was a wall-clock CSS transition that one long host frame could cut; it is now frame-stepped with a per-frame cap, and the verifier's five findings are fixed — FIXED; the owner decided the cap wins (design brief §4.8)
**Owner decision (C5, 2026-09-26):** tier fades are frame-stepped with a per-frame cap — no frame moves
the overlay's opacity more than `FADE_MAX_STEP` = 0.2 — and where the cap and the 300 ms duration bar
collide, the cap wins, on the terms below. The graded failure: the CSS model stepped 0.36 across one
116.6 ms host frame (bar 0.25). **Verifier findings (all reported, all fixed):**
- **C5-V1 CONFIRMED — the envelope claim was false.** An independent run failed 2 of 24 fades on the 300
  ms bar (316.6 and 316.7 ms) because the cap bound on host stalls; the claim that only a host presenting
  fewer than about five frames in 300 ms could overrun was wrong. Modelled offline on 60 Hz frames with
  one long frame at every placement: a frame of 33 ms or more can bind the cap; it adds at most 1, 2 or
  4 frames for 83–100, 116–133 or 200–250 ms stalls; and the uncapped wall-clock fade (the old CSS one)
  already reaches 300 ms when one 50 ms frame lands among its last. The wrong wording is removed from
  `emphasis.ts` and `scene.ts`. **Resolution, stricter rather than looser:** a fade over 300 ms with no
  host stall inside it still FAILS; a fade with a host stall inside it (a frame over
  `T.FADE_HOST_STALL_MS` = 25 ms, one missed vsync) may run past 300 ms only if every frame from 300 ms
  on ends the fade or moves the full 0.2 — catching up passes, dawdling fails. The rule uses only the
  harness's own 300 ms and 0.2, never the product's; stall-extended fades are listed apart with their
  host frames, and the injected-stall item gets the same duration rule.
- **C5-V2 — the driver was untestable inside `scene.ts`.** It moved into the ease owner as a pure
  `createTierFadeDriver(host)` in `src/fabric3d/emphasis.ts`: it steps on the raw frame time through
  `stepTierFade`, writes the opacity, calls `finish` exactly once on the frame the value reaches exactly
  0, and owns the two-window no-frames watchdog; timers and the overlay are injected, so it runs under
  vitest fake timers. `scene.ts` keeps only the wiring (`frame()` calls
  `tierFade?.driver?.frame(raw, reducedMotion);` unconditionally, before its first early return); a
  source-text tripwire pins that line, the host wiring, and that `scene.ts` steps or times no fade
  itself — jsdom has no WebGL, so `frame()` cannot execute in a unit test.
- **C5-V3 — a stalled fade could pass vacuously.** A pure `stalledFadeVerdict(tag, f)` counts an
  injected-stall fade as established only when the stall was injected AND the next frame lasted at least
  `FADE_STALL_MS` minus one 60 Hz frame (103.33 ms); otherwise the item is UNPROVEN, never a vacuous
  PASS.
- **C5-V4 — the harness's rationale was wrong.** A whole-canvas SHARE is a ratio that area does not
  dilute; the real case is gradual change below 8/255 over the rest of the canvas carrying the
  whole-canvas total, pulling a small cut's share under the bar. A known-answer fixture shows it (100 px
  cut by 60/255 in one frame beside 1,500 px drifting 7/255 in 1/255 steps: the whole-canvas share
  passes, only the masked share fails).
- **C5-V5 — the settle check was driven by a hand-kept list.** The motion-inventory settle block now
  iterates `OWNER_EASES`, every exported `EaseSpec`, cross-checked against the owner's source; the
  `EASES` equality assertion is kept. `SETTLE_FIGURE_PENDING = {TIER_FADE_MS}` excused only the missing
  settle-figure text in §4.8, which the record step owns; **this record adds it** ("settles in **283.4
  ms** at 60 fps"), so the row is now checked exactly like the others. The entry itself is still in the
  set, and removing it is the test owner's edit (O57).
**Pinned by** `src/fabric3d/emphasis.test.ts` (48 of 48 re-run by the record step: "C5: every fade the
ease owner steps moves at most FADE_MAX_STEP…", "C5: the tier-fade driver: step on raw, write, remove
at exactly 0, and a two-window no-frames watchdog", "C5: when the per-frame cap delays the tier fade…"),
`src/fabric3d/scene.test.ts` (45 of 45 re-run) and `src/core/motion-inventory.test.ts`. **Browser
evidence, reported and conflicting:** C5's re-grade on a fresh stamped build on :4184 gave
`capture-motion.mjs` exit 0, all 7 items PASS, 24 of 24 fades, largest step 0.2, 266.6–283.4 ms, none
stall-extended (so the catch-up rule is exercised only by known answers), injected-stall 4 of 4 on
116.6–116.7 ms frames, z-fighting 1,516 steps, popping 2,915 still pairs, AO 8 restores; the verifier's
single final run exited 4 (UNPROVEN, 1 of 24 fades not established) — O57. `report.json` gained per-fade
`hostStallFrames`, `stallExtended` and `pastBarFrames`. The residuals are O57.

### R115. D3 — a closing evidence drawer could be re-entered during its slide, and four more verifier findings on the drawer's focus return — FIXED; Escape closes the drawer (owner decision, design brief §7.1)
**Owner decision (2026-09-26):** at the drawer rung (1024–1279 px) Escape closes the evidence drawer
when focus is inside it and no inner layer is open (the inner layer closes first); focus returns to the
drawer's opener, or follows `focus-return.ts`'s third-door chain, never `<body>`; from the commit that
closes it the drawer is `inert`; the persistent rail (≥ 1280 px) is never collapsed by Escape and never
inert. **Verifier findings (all reported, all fixed):**
- **D3-V1 — re-entry during the slide, fixed by class.** A container that is not shown is `inert` from
  the commit that hides it, not 240 ms later. `useReleaseFocusOnHide` (`src/app/focus-return.ts`) owns
  it — release focus first, then set `inert`, and remove only an `inert` it set — so Rail B's drawer
  close, Rail B's hide and Rail A's single-column hide all get it. Red before: "a closing drawer cannot
  be re-entered…" failed 3 of 3; in a release build with the `inert` line mutated out, "Tab x7 at once
  during the slide: focus landed on BODY" and "focus() into the rail during the slide: focus landed on
  BODY".
- **D3-V2** — `settle()` in `drawer-focus-return.test.tsx` is `flushTurns(20, 8)` from
  `src/test-support/act-turns.ts`, and the file is no longer a raw async `act()` offender in
  source-hygiene.
- **D3-V3 — guard shape 4 bound the door to the component, not the element.** The first argument of
  each third-door call is reduced to its root symbol, and a hide is released only when the element
  carrying it passes its `ref` a value rooted at that same symbol; new planted counterexample
  `hiddenWithTheDoorOnAnotherElement`; `surfaces.tsx` passes with no ratchet entry.
- **D3-V4 — under reduced motion the configuration button was unfocusable in its first frame.**
  `EvidencePane.css`'s `.ev *` sets a 1 ms transition over `all`, so descendants transition the
  visibility they inherit. `App.tsx`'s `config.open` now commits its store writes with `flushSync` and
  waits up to `CONFIG_OPEN_MAX_FRAMES` = 6 frames for `checkVisibility` before activating the button;
  the stylesheet fix is routed (O58).
- **D3-V5** — if the marked invoker has left the page, the audit's `drawerCase` reports NOT DRIVEN (a
  failure) instead of passing.
**The audit** (`review/audit-d3-focus.mjs`, reported) keys `ensureRailShown` on the drawer rung and on
`data-drawer`/`inert`/visibility; a new `focusOn()` makes each surface case prove focus reached its
element or report NOT DRIVEN; new REENTRY cases and a reduced-motion drawer pass; `drawerOpen` waits 8
animation frames on top of 500 ms (under load, `v`'s frame arrived 790 ms and 3.2 s after the key in 2
of 8 runs); and `ensureInspectorFromCite` re-enters its state when the citation it opened from has left
the page, so "inspector (citation)" cases no longer measure the `#stage` fallback. **Pinned by**
`src/app/drawer-focus-return.test.tsx` (18 of 18 re-run by the record step) and
`src/app/focus-return.guard.test.ts` (99 of 99 re-run). **Final checks** (this tree's release build on
:4297, index sha256 `7305733b…c262ee` matching the build; :4181 was another agent's): `--sweep` exit 0,
"DRAWER: 75 case(s) driven", 0 failures; the default `--vp=1152` run 135 of 135 cases with 0 failures,
its remaining visibility failures being the drawer-over-Inspector layering (O58), and 141 cases, 0
failed, 0 not visible with the routed rule applied in an isolated copy; `--vp=390` exit 1 only on the
existing "SWEEP NEVER EXERCISED: offViewPointers" (148 cases, 0 failed, 292 stops, 0 not visible). The
verdict belongs to the next independent grader. The residuals and the three routed fixes are O58.

> **Repair wave 8, the last full repair wave of this effort (reconciled 2026-09-26, committed as
> `7f67013`).** Entries R103–R108 below, the new O47–O49 under Open, and the status notes and
> corrected headings on R42, R72, R79, R91, R94, O6–O9, O11–O14, O16, O17, O19–O23, O25, O27–O31,
> O33–O37 and O40–O46 record two things that had not been written here: the FAILs, new items 1–10 and
> status changes of the independent re-grade of `34bd435` (`docs/acceptance-report.md`, committed in
> `fea2037`: 30 PASS, every one attacked and upheld; 5 FAIL — A1, A4, C2, D3 and F4, of which F4 was a
> PASS overturned by refutation; 4 UNPROVEN — A2, B8, C1, F3; its "Known issues" section lists items
> 1–10 as "not yet recorded in `open-issues.md`", and `fea2037`'s edit of this file recorded wave 7
> only), and what the three wave-8 repair clusters (W8-ladder-and-palette: F4 and C2, run as a first
> agent and a continuation that re-verified it; W8-queue-focus-reveal: D3 and A4; W8-inp-j2-anchor: the
> E harness's J2 aim, item 6) and the merged-tree gate (5 cross-cluster requests applied, none refused,
> and the unpinned half of one applied patch caught by attacking it and pinned, R103) reported.
> **Every FIXED below was checked by the reconciler before it was written:** the code named was read at
> `7f67013`, and the named tests were re-run on the committed tree in one invocation — 12 files, 266
> tests, 266 passed, 0 failed, 0 skipped, vitest exit 0 (JSON report `w8-reconcile.json` in the
> orchestrating session's scratchpad) — including `tracked-sources.test.ts` (9 of 9),
> `acceptance-gates.test.ts` (14 of 14) and `scripts-typecheck.test.ts` (12 of 12); and `node
> review/mutation-check.mjs --history`, which reads only git: "18 commit(s) on HEAD's first-parent line,
> root 50a3dc5". `git status` was clean before and after. The reconciler also confirmed from `git diff
> fea2037 7f67013` that `review/capture-motion.mjs`, `vitest.config.ts` and `vite.config.ts` are
> untouched; no added line calls `.skip`, `.only` or `.todo`; no module the build imports was added (the
> five added files are four tests and the probe `review/probe-a4-surface-switch.mjs`); no test file
> loses `expect(` lines — 37 added and 0 removed across the five modified test files, the orchestrator's
> figure, plus 86 in the four new ones; and no added line cites `review/_` or a scratchpad path
> (`git grep -l 'review/_' -- src` still names the same 14 files, O29). **Verified by the orchestrator
> at `7f67013`:** `tsc` (app, scripts `--noImplicitAny`, config) all exit 0; `npm run build` exit 0;
> `vitest` 163 files, 3,766 tests, exit 0 after the commit; the gated commit scans clean; no
> capture-motion threshold changed; no timeout raised; no skip/only/todo added; 37 `expect()` lines added
> and none removed. **Not re-run by the reconciler, and cited as "reported" wherever it appears:** every
> browser harness of the wave (the gate's `capture.mjs app`, `text` and `reduced`; `audit-d3-focus.mjs`
> default and `--vp=390`; `layout-guard.mjs`; `capture-motion.mjs`; `audit-e5-coldload.mjs` with its new
> fractional loads; the clusters' `measure-inp.mjs` runs and `probe-a4-surface-switch.mjs`), the gate's
> regression sweep (45 fractional widths under forced device scale factors, and D2's keys at four widths
> in both themes), the clusters' mutation checks, their Playwright probes and screenshots — in the
> orchestrating session's scratchpad except the two instruments now tracked (O48) — and the
> orchestrator's full `vitest` run. A fixed defect does not by itself move its criterion; nothing here is
> a re-grade.
>
> **How the C2 regression got in, and what this wave's gate did differently** (orchestrator's
> account). The C2 regression the wave closed (R104) was introduced by the orchestrator's own
> `34bd435`, committed after the unit tests and an honesty-only verification but WITHOUT the browser
> harnesses — and the wrap-licence scan lived only in a browser harness. Wave 8 moved that scan into the
> unit suite (`wrap-licence.test.ts`), and its gate ran `capture.mjs text` and the D3 focus audit AFTER
> its last edit.
>
> **History since the wave-7 record** (it continues the wave-7 banner below). `fea2037` (docs only: the
> wave-7 record and the re-grade of `34bd435`, 2026-09-26 04:53 +0300) → `7f67013` (repair wave 8: F4
> ladder tiling, C2 palette wrap licence, D3/A4 settled-layout reveal and the `measure-inp` J2 aim; 23
> files, 2,622 insertions and 165 deletions; 09:02 +0300). 18 commits on `main`, root `50a3dc5` (`git
> rev-list --count HEAD`; `--history` above agrees). `git status` was clean at `7f67013` before this
> edit.
>
> **Where the effort ends.** Wave 8 is intended to be the FINAL repair wave of this effort. The non-E
> PASS count was flat between the last two grades — 25 at the re-grade of `8eac055` and 25 at the
> re-grade of `34bd435` (30 PASS each, with E1–E5 all PASS in both) — and the orchestrator's stated stop
> rule ends the full-wave loop there. The end state, which the re-grade of `7f67013` measures:
> - **FIXED in code at `7f67013`, not yet re-graded:** the four code FAILs of `34bd435` — F4 (R103), C2
>   (R104), D3 (R105) and A4 at 1920 and 1440 (R106) — and the E harness's J2 aim (R107).
> - **NOT CLOSABLE IN CODE in Atlas Scope:** A1 (O12: per-finding record pointers from the producer), A2
>   and B8 (O34, O13: a snapshot with depth-2 flows and a decided nearby delivery), F3 (O34: pre-fix
>   history that does not exist).
> - **OWNER DECISIONS:** C1 (O19); A4 at 768 and 390, where the queue's whole port leaves the view (O49);
>   and the standing ones in O11, O16, O20, O35, O42 and O46.
> - **Open leads, not failures:** O14, O17, O21, O22, O27–O31, O33, O36, O37, O40, O41, O43–O45, O47
>   and O48.
> - **E:** every E criterion PASSED at `34bd435` on acceptance-grade laboratory runs; wave 8 changed code
>   on journey paths, so E at `7f67013` rests on the re-grade now starting (O25).
> A later effort should start from this list, not reopen a wave.
>
> **Host state at the start of the re-grade of `7f67013`** (orchestrator): on battery at 82 % — the E
> grader waits up to 60 minutes for AC before measuring — the :4180 dev server idle at 0 cores, host CPU
> about 0 %. The reconciler's own read before its test run (about 09:08 +0300): on battery
> (`Win32_Battery` status 1) at 82 %; no `vitest` or review-harness process was running (a scan of
> process command lines), so no other suite ran beside the reconciler's 24-second one.

### R103. F4 — at fractional viewport widths between 767 and 768 CSS px (and at 1023–1024 and 1279–1280) the frame matched no ladder rung, so the fabric mounted and three.js loaded on first paint — FIXED, with a guard that the ladder tiles the width line (re-grade of `34bd435`, F4 PASS overturned by refutation, new item 4)
Found by the re-grade's F refuter: headed Chromium with `--force-device-scale-factor=1.5
--window-size=781,900` gave a media width of 767.349, `fabricAttr on`, `showBtn false` and three.js
requested at 985 ms; DSF 1.75 (767.44) the same at 1236 ms; the 766.0 control stacked with no request.
The layout sat in no rung (controls over the first grid row, the status bar clipped). The re-grade's
cause: `surfaces.tsx:128` `(max-width: 47.9375rem)` against the CSS `(min-width: 48rem)` rungs, with
`App.tsx:217` seeding the fabric from `!ladder.stacked`. Every earlier F4 measurement, including
`audit-e5-coldload.mjs`, used integer widths, and R79's build-output test does not reach it.
W8-ladder-and-palette found the same gap at 1023–1024 and 1279–1280 (at 1023.349: no pane, no More) and
an overlap at exactly 768 (`PriorityQueue.css:892` `(max-width: 48rem)`) (reported).

**Fix, verified in code, by class — "two numbers for one boundary".** `LADDER_REM` (`surfaces.tsx:100`:
singleColumn 48, drawer 64, reference 80, wide 100) is the one owner. `useLadder` (`:163–167`) builds
every rung from `(min-width: Nrem)` edges only (`atLeast`, `:112`), chained so exactly one rung holds,
and Header's compact rung reads `useLadder` (`Header.tsx:63`; `COMPACT_QUERY` is gone). Every narrow rung
in the stylesheets is `not all and (min-width: Nrem)` (12 in `src/**/*.css`), and the reconciler's grep
finds no `max-width` media query left there; the one `max-width` condition is the `@container pathtrace
(max-width: 30rem)` query at `PathTrace.css:641`, a container ladder outside this guard (O48). The
768 overlap moved to the stacked rung (no computed value changes, reported). **Pinned by**
`src/core/breakpoint-ladder.test.ts` — 11 of 11 re-run: every `@media` width condition in
`src/**/*.css` and the root HTML, and every width-query literal in the TypeScript, is a union of owner
rungs, sampled every 0.05 px over 300–2000, at each boundary ±0.01/0.5/0.99 and at
767.349/767.44/1023.5/1279.5; every boundary is an edge of some stylesheet rule; `useLadder` puts each
sample in exactly one rung; and positive controls for a gap, an overlap, an undeclared boundary, an
unmodelled shape and a query built outside the owner — with the fractional cases in `surfaces.test.tsx`
(15 of 15) and `Header.test.tsx` (36 of 36). Reported: 4 of 11 red before the fix (12 CSS violations, 4
TypeScript) and 6 fractional `surfaces` cases red; two mutations, each red and restored from saved
copies; on a fresh build in headed Chromium, media widths 767.349 and 767.444 stacked, fabric off, the
"Show the 3-D fabric" button present and no three.js request, 1023.349 single-column, 1279.349 and
1024.016 drawer; the gate's 45 fractional widths at DSF 1.1–2.2 on both sides of 768, 1024, 1280 and
1600, each with exactly one rung matching, 0 horizontal overflow and no three.js below 768; and
`capture.mjs app` 32 of 32 frames byte-identical at 1440 and 1920 before and after.

**A consequence, caught and pinned by the gate.** The ladder change turned `sticky-layer.test.ts` red
("expected NaN to be 1023": its regex read the removed `singleColumn` literal), and its `mediaAt` read
`not all and (min-width: X)` as `(min-width: X)`, which would silently have inverted every narrow rung
the D3 layering check examines. The gate applied the cluster's patch — `NARROW_TOP` from
`LADDER_REM.drawer` (`sticky-layer.test.ts:316–317`) and the negation (`:171`, `:177`) — found the
negation half unpinned (reverted, 11 of 11 stayed green), and added "the detector reads the ladder's
complement form" (`:357`), red with the negation reverted ("expected 1 to be 3", reported); 12 of 12
re-run. **Harness:** `audit-e5-coldload.mjs` now also makes fractional cold loads (`f4FractionalLoads`,
`:447`: headed, DSF 1.5, windows 781, 780 and 1037, media width bisected), printed beside the integer
F4 load and never judged; the gate's `ATLAS_RUNS=1` validation (reported): 767.349 fabric off, button
present, no three.js; 766.0 the same; 1023.349 pane queue. F4 is not re-graded here.

### R104. C2 — `34bd435` reintroduced an unjustified `overflow-wrap: anywhere` on the prose `.palette__matched`, and the project's own text gate was red — FIXED, and the licence scan now runs in the unit suite (re-grade of `34bd435`, C2 FAIL, new item 2)
Found by the re-grade: `node review/capture.mjs text` printed "BAD wrap licence without justification:
src/app/CommandPalette.css:276 .palette__matched { overflow-wrap: anywhere }" and exited 3; `ba7b456`
has 0 such licences and `34bd435` 1 (re-counted by the grader). `.palette__matched` could print a raw
`hit.field` identifier when `FIELD_WORDS` had no entry; no visible split was found in any capture or
probe. **How it got in** (orchestrator's account): R94's palette change was committed in `34bd435`
after the unit tests and an honesty-only verification, WITHOUT the browser harnesses, and the licence
scan lived only in `capture.mjs`, which needs a running server — so the suite that was run could not see
it.

**Fix, verified in code.** `.palette__matched` (`CommandPalette.css:276–280`) sets no wrap licence, and
its comment (`:272`) says why; the reconciler's grep finds `overflow-wrap: anywhere` in `src/**/*.css`
only on declared token containers and in comments. `MatchReason` (`CommandPalette.tsx:328`) prints a
field's words from `FIELD_WORDS` (`:290`); a field it has no words for renders as an identifier in
`<code>` with a `<wbr>` after each separator (`. _ / - : +`, `:346–353`), so it breaks only there.
**Pinned by** `src/core/wrap-licence.test.ts` (1 of 1 re-run), which runs `node review/capture.mjs wrap`
— static: no server, no browser — and asserts its exit 0, its PASS line and no BAD line, so a green
suite can no longer coexist with a red wrap gate; and by `CommandPalette.test.tsx` (45 of 45), including
that `FIELD_WORDS` covers every field literal in `query.ts` and every field a `rankedSearch` sweep emits,
and that an unknown field renders as a breakable identifier. Reported: both red before; the licence put
back and `MatchReason` reverted, 2 red, restored; `capture.mjs wrap` "0 unjustified token-break
licence(s) across 13 stylesheet(s) and 75 source module(s)", `selftest` 23 of 23, `text` "72 of 72" on a
fresh build — and the gate's `capture.mjs text` after its last edit, exit 0; at 320 and 390 over 6
terms every match reason fits its row with no mid-word break. C2 is not re-graded here.

### R105. D3 — at 390 × 844, Tab out of the queue's "What the collection gap means for this result" popover left the focused grid cell wholly under the status bar's coverage button — FIXED by class, "a reveal measured against a layout that is about to change" (re-grade of `34bd435`, D3 FAIL, new item 3)
Found by the re-grade: `audit-d3-focus.mjs` "1089 focus stop(s) checked for visibility, 1 not
visible" — phone/inspector (citation), popover → Tab → Escape, `DIV.ag__cell` "core1CR-01:
End-of-support keystone" at [76,754,261,788], 0 of 9 points on it, the rest on `BUTTON.sb__cov`;
`--vp=390` the same, deterministically. It contradicted O45's W7-B7 note for 390. **Cause, traced by
W8-queue-focus-reveal (reported):** with a `scrollBy` trap, the grid's own arrival reveal (`onFocus` →
`revealBelowHeader` → `revealThroughAncestors`) measured the still-open popover as an overlay and
scrolled the page by −37.3 px; when the popover closed the cell sat under the bar. A second run showed
another route to the same place: a deferred commit re-worded the rail above the grid and moved the cell
24 px down with no scroll. Reproduced on `fea2037`, served separately.

**Fix, verified in code (`DataGrid.tsx`).** `trimOverlays` (`:583`) walks the whole `elementsFromPoint`
stack (`:608`), so a box over the whole band no longer ends the walk before the bar beneath it is
trimmed; focus arriving from outside the grid is revealed again against the settled layout
(`settleFocus`, `:1330`: after a frame and after the deferred-commit task, twice), outside the event;
and the focused cell is kept on screen through every change the reader did not make — port, header,
window and body resizes, a page or ancestor scroll with no reader input, and an IntersectionObserver
(`:1366–1465`) — while the reader's own scroll of the grid, the page or a rail that carries it releases
the keep (`focusKeptRef`, `:1108`). Every reveal is an instant scroll (D7). **Pinned by**
`src/panels/DataGrid.sticky-bar-reveal.test.tsx` — 8 of 8 re-run: a popover frame over the band, the
bar alone and a no-bar control; the page moving in the arrival's own task; a page scroll the reader did
not make; content growing above the grid; a reader-scroll control; and the traced case end to end.
Reported: 5 of 8 red against `fea2037`'s `DataGrid.tsx`; seven mutations, each red and restored from a
saved copy (`cmp`-checked; no `git checkout`); the full `audit-d3-focus.mjs` "547 case(s), 0 failed",
"1089 focus stop(s) … 0 not visible" and SWEEP "3040 operable element(s) … 0 failure(s)", exit 0, on the
dev server and on a preview build, and again in the gate after its last edit; and `--vp=390` "145
case(s), 0 failed", "289 focus stop(s) … 0 not visible", exiting 1 only on "SWEEP NEVER EXERCISED:
offViewPointers" — the off-view pointer cannot exist at 390 because the fabric is collapsed there, so
that exit is the script's diagnostic, not a failure (O45). O41's partial ring at 768 in the path-flow
state was not re-measured (O48). D3 is not re-graded here.

### R106. A4 — after interactive selections, switching to the Path surface, submitting the flow and a dist1 double-click left the selected finding's row off screen — FIXED at 1920 and 1440; at 768 and 390 the queue's whole port leaves the view, an OWNER DECISION (O49) (re-grade of `34bd435`, A4 FAIL, new item 1)
Found by the re-grade (twice, 1920 × 1080): queue at scrollTop 1000, orbit, click F026, then access5,
core1, L33 and access5, then the Path surface button — the port shrank to 786–1054, scrollTop moved
only 1000 → 1015, and F026 (`data-active`) sat at 1241–1297; the flow submit and a dist1 double-click
left it off screen; after a URL load the same switch re-anchored the row. R91 was marked FIXED here, and
no A4 test pinned the path. **Cause (W8-queue-focus-reveal, reported):** the hold the port
ResizeObserver re-reveals was armed only by a reveal that SCROLLED; a clicked row takes the activation
skip, so no hold was armed, and later device, link and hop picks do not re-key the reveal (the URL-load
path worked because its reveal had scrolled). Two more triggers of the class: a path panel growing above
the grid inside rail A moved it with no resize, and a press on "Trace this flow" or a canvas wheel
counted as reader page input and released the hold.

**Fix, verified in code (`DataGrid.tsx`).** The activation path arms the hold by nearest
(`holdAlignRef.current = "nearest"`, `:1160`) without reading layout, and a restoring reveal also holds
by nearest (`:1265`); an IntersectionObserver watches the held row and the focused cell;
`revealBelowHeader` scrolls the outer scroller first when the grid's own port already shows the row;
hold re-reveals from the watcher or a window resize never scroll the document; and reader page input
counts only on scrollers that carry the grid. **Pinned by**
`src/panels/PriorityQueue.a4-surface-switch.test.tsx` — 33 of 33 re-run: every trigger (the switch alone,
device, link, hop, the report's sequence, a store `setSurface`) at 1920, 1440, 768 and 390; the focused
cell under a shrinking port; the grid moved inside a scrolling rail; a button press that must not
release the hold; reader-scroll controls; and "E3: the click's own commit reads no more layout than the
grid did before this repair". Reported: 28 of 30 red against `fea2037`'s `DataGrid.tsx` (32 of 37 with
the sticky file); five mutations, each red and restored; the replay probe, now tracked as
`review/probe-a4-surface-switch.mjs`, "16 applicable step(s), 0 OUT" at 1920 and 1440 on the dev server
(6 OUT on `fea2037`), and "22 applicable step(s), 0 OUT, 5 with the queue off screen, 1 not
driven/failed" over four widths on a preview build. **What the probe's exit 1 means:** the five
off-screen steps are at 768 and 390, where the queue's whole port is scrolled out of the shared rail or
page while F026 stays in view inside the grid's own port (O49); the one not-driven step is link L33 at
390, which the probe cannot pick — below 768 there is no canvas, and the palette offers no link entries
(0 options for "L33" at 390 and at 1440, the gate's check; `query.ts` and the palette index are
unchanged since `fea2037`). That is a limit of the probe, recorded as such (O48), not a product
failure. A4 is not re-graded here.

### R107. E harness — `measure-inp`'s J2 anchor discovery could not aim at the three "not collected" devices, and read the selection back after a fixed sleep — FIXED in the harness, with a host-independent unit pin (re-grade of `34bd435`, new item 6)
Found by the re-grade: the "? not collected" text widens a device's label, so the label-box aim
missed AP-floor1, AP-floor3-01 and wan-edge-rtr1.lab by about 46 px (AP-floor1, the highest link
degree at 17, got 0 trials). W8-inp-j2-anchor measured it at 1920 × 1080 (reported): the label-box
centre sat 43–46 px off the chassis centre for those three and 6–12 px off for the 23 collected
devices. It found a second cause: the selection was read back after a fixed 120 ms sleep, while
`urlSync` writes `d=` once per frame, so a slow frame reported the previous click's device (6 of 26
reached on a headless dev server). **Fix, verified in code (`review/measure-inp.mjs`).** Discovery aims
every device at `window.__atlasScene.chassisScreenBox(id)` (`:381`), re-read before each click, trying
the centre and then four inner points (`chassisAimPoint`, exported, `:300`); it clicks only where
`elementFromPoint` is the canvas, so each click stays a real 3-D pick, and it waits up to 1.5 s for `d=`
to CHANGE (`:324`). J2 keeps the first 12 anchors (`J2_HITS`); every anchor goes to the new
`J2_ANCHORS` (`:247`), where the first-selection trials look up their targets; the anchors line reports
"devices a canvas click reaches: N of M" (`:1035`) and names every unreached device. **Pinned by**
`Fabric3D.test.tsx`'s "measure-inp J2: anchor discovery aims at each device's chassis, whatever its
label's width" (`:1994`, added by the gate from the cluster's scratch test) — the file 70 of 70 re-run:
a fake page with one 180 px label and two 70 px ones, where a click selects a device only inside its
projected box; every device gets an anchor on its own chassis, and `chassisAimPoint` gives `{x:460,y:307}`
on the stated box and null off the canvas. Reported: both tests red with `fea2037`'s harness swapped in
("no anchor selects wide-unobserved"; `chassisAimPoint` undefined); in a real browser 26 of 26 devices
reached (the label aim put back: 23 of 26, missing exactly the three; the 120 ms sleep put back: 0 of
26); one laboratory run on a scratch build (NOT ACCEPTANCE EVIDENCE: build not fresh, host 21 % busy):
J2 p95 104 ms with 25 of 25 verified effects, and first selection of the three devices in 15 of 15
trials, p95 96 ms, 0 on-path tasks over 50 ms; the harness's positive control (a 130 ms busy loop on
input) still turned J2 and J2-first red. It does not touch O31's settle wait (O31).

### R108. `review/capture.mjs`'s 06-path-blocked manifest note said "BLOCKED verdict marker on core1" while the frame shows "? UNDECIDED" — FIXED in the text by the gate; NO pin (O41's C2 bullet; the re-grade of `34bd435`'s A "not examined")
Recorded at the re-grade of `78bdba5` (O41) and again at the re-grade of `34bd435`. **Verified in
code:** `review/capture.mjs:86` now reads "a '? UNDECIDED' verdict marker on core1 only — the ACL line
denies the flow but the denial is not decided, and the trace is single-hop …", which agrees with R35 and
with the A5/D8 grading. Only that line changed (`git diff fea2037 7f67013 -- review/capture.mjs`: one
line in, one out). **No test pins it:** the reconciler's `git grep "verdict marker" -- src` finds
nothing.

> **Repair wave 7 (reconciled 2026-09-26, committed as `ba7b456` and `34bd435`).** Entries R91–R102
> below, O32, O38 and O39 moved here from Open, the new O44–O46 under Open, and the status notes and
> corrected headings on R39, R81, O10, O6–O9, O11–O14, O16, O17, O19–O23, O25, O27–O31, O33–O37 and
> O40–O43 record two things that had not been written here: the new items 1–11 and the status changes
> of the independent re-grade of `8eac055` (`docs/acceptance-report.md`, committed in `6a5d830`: 30
> PASS, every one attacked and upheld; 5 FAIL — A1, A4, B6, B7, D4, of which B6 and D4 were PASS
> overturned by refutation; 4 UNPROVEN — A2, B8, C1, F3; its "Known issues" section lists items 1–11 as
> "not yet recorded in `open-issues.md`", and `6a5d830`'s edit of this file recorded wave 6 only), and
> what the five wave-7 repair clusters (W7-A4 bottom-band reveal: A4; W7-B6 preset inert citations: B6;
> W7-B7 coverage under modals: B7; W7-D4 selected state: D4; W7-F3 evidence integrity: F3, F2, D5, O38,
> O39), the merged-tree gate (17 cross-cluster requests applied, 4 refused, and a defect in the new D4
> guard found by attacking its own edit) and the orchestrator's follow-up commit `34bd435` reported.
> **Every FIXED below was checked by the reconciler before it was written:** the code named was read at
> `34bd435`, and the named tests were re-run on the committed tree in one invocation — 18 files, 633
> tests, 633 passed, 0 failed, 0 skipped, vitest exit 0, 115.6 s wall, the census file alone 112.7 s
> (JSON report `reconcile-w7.json` in the orchestrating session's scratchpad) — including
> `tracked-sources.test.ts` (9 of 9) and `source-hygiene.test.ts` (17 of 17); `node
> review/mutation-check.mjs --only layout-nonfinite-option`: baseline green, KILLED "by the targeted
> assertion src/fabric3d/layout.test.ts:926:86", exit 0; and `--history`, which reads only git: "16
> commit(s) on HEAD's first-parent line, root 50a3dc5". `git status` was clean before and after (the
> script works in a scratch copy). The reconciler also confirmed from `git diff 6a5d830 34bd435` that
> `review/capture-motion.mjs` and `vitest.config.ts` are untouched; no added line calls `.skip`,
> `.only` or `.todo`; no module the build imports was added (the six added files are all tests); and no
> test file loses `expect(` lines on balance — 108 added and 6 removed across the ten modified test
> files (the removals are in `scene.test.ts`, 4, and `EvidencePane.targets-cap.test.tsx`, 2, both
> rewritten into stronger tests: O38, R102), plus 124 in the six new ones. **Verified by the
> orchestrator at `34bd435`:** `tsc` (app, scripts `--noImplicitAny`, config) all exit 0; `npm run
> build` exit 0; `vitest` 159 files, 3,699 tests, exit 0; the gated commit scans clean; no
> capture-motion threshold changed; no timeout raised; no skip/only/todo added. **Not re-run by the
> reconciler, and cited as "reported" wherever it appears:** every browser harness of the wave (the
> gate's `capture.mjs app`, `text`, `reduced` and `twice 5`; `capture-motion.mjs`; `audit-d3-focus.mjs`
> default and `--sweep`; `layout-guard.mjs`; `audit-e5-coldload.mjs`; `measure-inp.mjs`), the gate's
> 108-check regression sweep, the clusters' Playwright probes (`b7-probe2.mjs`, `w7a4-sweep.mjs`,
> `d4-rendered.mjs` and others) and screenshots — all in the orchestrating session's scratchpad, none
> tracked (O45) — the two independent verifiers of `34bd435` (R94), the full 21-mutation
> `mutation-check.mjs` run, and every wave-7 mutation other than the one above. A fixed defect does not
> by itself move its criterion; nothing here is a re-grade.
>
> **History since the wave-6 record** (it continues the wave-6 banner below). `6a5d830` (docs only:
> the wave-6 record and the re-grade of `8eac055`, 2026-09-25 18:54 +0300) → `ba7b456` (repair wave 7:
> D4, B7, A4, the B6 presets and F3 evidence integrity; 42 files, 4,443 insertions and 176 deletions;
> 2026-09-26 00:14 +0300) → `34bd435` (the three B6 census residuals, closed by the orchestrator after
> an independent refutation, R94; 9 files, 540 insertions and 64 deletions; 01:48 +0300). 16 commits
> on `main`, root `50a3dc5` (`git rev-list --count HEAD`; `--history` above agrees). `git status` was
> clean at `34bd435` before this edit.
>
> **Host state at the start of the re-grade of `34bd435`** (orchestrator): on AC at 99 %, the :4180
> dev server idle at 0 cores, host CPU 15 %. The reconciler's own read before its test run (about
> 01:50 +0300): on AC (`Win32_Battery` status 2) at 99 %, `LoadPercentage` 4 %; the only `node`
> processes were the :4180 dev server (`npm run dev` and its vite child) and the graphify MCP launcher,
> so no other suite ran beside the reconciler's.

### R91. A4 — the first device pick threw the queue to the top when the only visible naming row sat in its bottom ~38 px — FIXED (re-grade of `8eac055`, new item 1); R39's shape in a narrower band; A4 failed again at `34bd435` in another shape, a surface switch after interactive selections, fixed in wave 8 (R106)
Found by the re-grade of `8eac055` (A4 FAIL): with nothing selected and F099 fully visible at the
bottom of the queue (row 999–1041 in grid 352–1054, scrollTop 4777, 1920 × 1080), one canvas click on
access13 left scrollTop 0 at +300 ms, +1.2 s and +4 s, F099 then at y = 5,814; access5/F094 went 4511 →
0; a centred control held. No test pinned it (the six A4–A6 files passed 181 of 181), and R39 was
marked FIXED here. **Cause, measured by W7-A4 (reported):** the pick's URGENT commit mounts "N of 146
shown findings name <host> — marking the rows." above the queue (grid top 352 → 374.8); the DEFERRED
commit re-wraps it to "— marked on the row's trailing edge." (→ 389.7) and, in that same commit, takes
R39's `revealUnlessVisible`/`firstVisibleRow` decision against the moved layout, so the only visible
naming row read as hidden. W7-A4 reproduced it on `6a5d830`'s code in a new test ("scrollTop 4004 ->
0") and in a browser (4777 → 0).

**Fix, verified in code, by class — "a visibility decision taken against a layout the same state change
moves".** `DataGrid` takes an `actKey` prop (`DataGrid.tsx:196`). When it changes, a class child's
`getSnapshotBeforeUpdate` (`:679`, mounted at `:1809`) records the rows the reader could see before that
commit touches the DOM (reads only; reported 0.6 ms median, 1 ms max for 146 rows on the release build),
and every "already on screen?" decision accepts a row seen at the act (`sawAtAct`, `:1079`) and brings
it back by the nearest movement if the act pushed it out; reader input on the grid or any scroll since
voids the record. `PriorityQueue.tsx:2504` keys it on the urgent finding, device, link and hop, so the
canvas, Fabric list, palette, chain chips, hop and Back share one key. Two same-class sub-pixel defects
were found and fixed in the same wave (reported measurements): a nearest reveal now rounds `scrollTop`
away from the row (`:406`; before, `+= 37.7` snapped 0.3 px short and the hold re-centred the row, 4777
→ 5099), and "already visible" tolerates less than a pixel outside the band (`SEEN_SLACK_PX = 1`,
`:648`; before, a row 0.25 px under the header threw the list 645 px). **Pinned by**
`src/panels/PriorityQueue.a4-band.test.tsx` — 10 of 10 re-run green (the real PriorityQueue:
nothing-selected sweeps at 1920, 1440, 768 and 390 plus a re-wrapping 390 rail, device-to-device, the
report's exact case, centred and negative controls, Back through urlSync popstate) — and
`src/panels/DataGrid.act-view.test.tsx`, 19 of 19 (every whole-pixel offset at the four measured
viewports, one- and two-commit shifts, reader-input and scroll voiding, sub-pixel edges, device-pixel
rounding). Reported: six mutations, each red and restored from a saved copy (the actKey wiring removed:
"21 of 65 offsets lost the reader's place"); browser whole-band sweeps on the fixed build 0 failures of
37, 33, 23 and 33 samples at 1920, 1440, 768 and 390, and 14 of 27 with the fix disabled; the report's
case 4777 → 4802 with F099 fully visible and marked; palette and Back likewise; device-to-device
unchanged. The re-grade's untested paths are covered by the one key; of them, device-to-device and Back
are in the test file, the palette in the browser only. **A transient remains, not a scroll throw**
(O45). A4 is not re-graded here.

### R92. B6 — the path preset cards printed 5 citations as inert text inside their run-this-flow button, and 3 verdict words carried no citation — FIXED (re-grade of `8eac055`, new item 2; B6 PASS overturned by refutation)
Found by the re-grade's refuter on "Other questions this snapshot can answer" (on screen in graded
states 06 and 08): `span.pt-preset__why` and `span.pt-preset__prov` sat inside `button.pt-preset__btn`
(`PathTrace.tsx:937–939` at `8eac055`), `citeButtons 0` for `acls.core1.PROTECT_SERVERS[2]`,
`l3_forwarding[5]` (twice) and `l3_forwarding[4]` (twice), and clicking the `l3_forwarding[5]` sentence
ran another flow instead of opening the Inspector; "denied by list text — not decided…",
"indeterminate" and "13 caveats on its card" named no record. R81's inert-citation shape on a surface
its census never visited.

**Fix, verified in code.** Each card is an `<li>` holding ONE run button with the title and flow only
(`PathTrace.tsx:979–990`; `aria-describedby` names the verdict and bounds). Outside it, the verdict word
carries the record that decided the trace plus every outcome-undeciding gap's cite (`decidingCiteOf`,
`:635` — also the one rule the intent search's reason rows use — and `:926`), the bounds carry
`fabric.coverage.cite`, and the rationale and provenance note go through `CitedText` (`:1007–1015`).
**Pinned by** `src/panels/PathTrace.preset-cites.b6.test.tsx` — 9 of 9 re-run green: in both preset
lists, no citation inside the run button; every verdict word and its bounds carry the records that
decided them, derived independently from the trace; clicking the sentence runs nothing — and
`src/app/verdict-scope.b2.test.tsx` (9 of 9), whose preset assertion now reads the card and the run
button's name and description (the old button-text read no longer applies). Reported: 6 of 9 red on
`6a5d830`'s Presets and again with the JSX reverted; in a private preview (state 06, 1440), 5 citation
controls on the `l3_forwarding[5]` card, 0 controls nested in the run button, the URL unchanged by a
click on the sentence, 25 of 25 preset citations opening their own record, and the run button still
running its flow. B6 is not re-graded here.

### R93. B6 as a class — an inert-citation census of every surface found the same shape in more places; wave 7 closed all but three, and `34bd435` the rest (R94) — FIXED
The re-grade said "Surfaces beyond Path were not swept for the same shape". W7-B6 wrote the sweep as a
test: `src/panels/inert-cite-census.test.tsx` renders the real App, unmocked, at 390, 768, 1100 and
1440 over every surface and state (every suggested flow on every hop, the counterexample and palette
rows, the refused link, every intent searched to its verdict, every device × every evidence tab, all 146
findings, all 44 links, and the Inspector at one record per rendering shape — 799 records, 48 shapes,
reported), and requires every citation the Inspector's own resolver recognises, in text or in a
reader-facing attribute, to be owned by a control that, when ACTIVATED, puts the Inspector on that
record; a control inside a control is flagged; each finding is attributed to the source file of the
component that created the element (React's `_debugOwner`, no class-name map). **Found and fixed in
wave 7 (verified in code):** the intent rationale (`p.pt-intent__why`, now `CitedText`,
`PathTrace.tsx:1721`) and the Inspector's record field values (`FieldValue` through `CitedText`) by
W7-B6; and, by the gate on W7-B6's requests, the palette's suggested-flow rows (an option that runs a
flow printed its rationale's citations: `commands.ts:770` now passes the detail through
`withoutCitations`, `cited-text.tsx:103`, pinned by `CommandPalette.test.tsx`), DevicePane's raw-record
note and every cite value in its JSON dump (reported: 23 controls on access1, each at least 24 px),
ImpactSection's DISAGREEMENT sentence, LinkSummary's "Source record", and EvidencePane's evidence-chain
steps 1 and 5 (the brief named one site; the census found step 5 once step 1 was fixed). The gate
added `panels/DevicePane.tsx` and `panels/EvidencePane.tsx` to `OWNED_FILES` (`:142–148`), where any
inert citation fails outright. **Pinned by** the census — 65 of 65 re-run green in 112.7 s (64 at
`ba7b456`; `34bd435` added the planted copy controls, R94) — including "the census is not vacuous: it
opened records, and it clicked the refuter's preset citations" (more than 500 controls proven to open
their record, more than 10 Inspector shapes). Reported: the preset and intent revert and a
`FieldValue` revert each turn the owned-file test red, restored. Swept and printing no resolvable
citation (reported): the status-bar denominators, CoverageBar and the blast-radius stage button. Also in
the wave (reported, in the diff): `openInspector` no longer writes the store when the dock is already
open, and `#inspector` carries `data-cite` and `data-model-path`, which the census reads. B6 is not
re-graded here.

### R94. B6 — the census's last three classes (the palette's search-hit chip, JSON-tree rows that name a record, "Copy path") — FIXED in `34bd435`, after an independent verifier refuted a first version that stated absences as fact; its palette change also added an unjustified wrap licence, a C2 FAIL at the re-grade of `34bd435`, fixed in wave 8 (R104)
Wave 7's gate refused these three (they needed design decisions: an option or a treeitem may not
contain a control, and the alternative was a census exemption, which loosens the guard), and
`ba7b456`'s message leaves them "on its ratchet … pending design decisions". The orchestrator closed
them in `34bd435`. **Fix, verified in code.** A palette search hit no longer prints a record it cannot
open: the "Source record" chip is gone, the row states its match reason in words, and an endpoint or
interface hit selects its host and opens its Ports tab (`CommandPalette.tsx:398–430`), pinned by
`CommandPalette.test.tsx` (41 of 41; "a hit for … names no record it does not open", `:639`). A
JSON-tree row whose key or string value names a record the resolver finds opens that record on Enter
or double-click through `openInspector`, the citation control's own path, and stays one treeitem
(`JsonView.tsx:360` `rowCite`; `:376`, its description "Enter or double-click opens the record X in the
Inspector."; `:796`), pinned by `Inspector.test.tsx`'s "a row that names a record opens it (B6)" block
(62 of 62). A control named "Copy …" counts as a citation tool only when its activation writes exactly
its citation to the clipboard, observed with a recorder rather than assumed, and three planted decoys
must fail: a Copy-named control that does something else, a control that copies the citation under
another name, and a Copy-named control that copies other text (`inert-cite-census.test.tsx:717–757`).
`KNOWN_ELSEWHERE` (`:448`) is now EMPTY, so with its rot test any new inert class anywhere fails.

**The first version stated absence as fact, and the brief caused it** (orchestrator's account; the two
verifiers' runs are reported, not re-run). It made the Inspector's JSON tree say "X names no record in
this model" for any path-SHAPED text the resolver did not match. An independent verifier walked all
11,032 rows of `fabric.json` and found 78 carrying that sentence, many about data that IS in the model —
`acls.core1.PROTECT_SERVERS` and the other ACL rows, endpoint MAC addresses, the device's own host name,
`meta.scriptVersion`, the `coverage.aclSummary` counters: an absence stated as fact, introduced by the
orchestrator's own brief ("a path that does not resolve stays plain data and says so"). The corrected
design states only the positive, resolver-verified fact ("Enter or double-click opens the record X")
and otherwise says nothing. `unresolvedPathsIn` was deleted — the reconciler's grep finds it nowhere in
`src/` except the explanatory comment at `cited-text.tsx:88`, and "names no record" only in test
messages and in `Inspector.tsx:949`, the older sentence for a citation that does not resolve at all —
and `Inspector.test.tsx` walks every node of the compiled model ("over every node of the compiled
model, a row's description is either absent or a record the resolver opens") and pins the silence ("a
value that names no record stays plain data, and the tree states no absence about it"). A second
independent verifier UPHELD the corrected design: 1,269 describing rows, all resolving; 0 absence texts
across 22,064 activations; palette and census honest. Its residuals were closed in the same commit,
test-first with mutation checks (reported), each with a test in the re-run: a repeated open is
re-announced ("opening the same record twice is announced twice"); the tree's announcement clears when
another control moves the Inspector; and the hint no longer says Enter opens "a record path", since some
record paths, such as devices, do not open (it now reads "A row underlined with dots names a record:
Enter or double-click opens it.", `JsonView.tsx:716`). **Two latent residuals remain, with no instance
in this snapshot** (O45): `rowCite` opens only the first of two citations in one row, and the palette's
"on its Ports tab, where this … record is cited" would be false for an endpoint whose host has no
interface or physical records. B6 is not re-graded here.

### R95. B6 secondary — for a model path that is also a source-snapshot path, the Inspector said the citation "resolves directly inside the compiled model" and never that the source record can differ — FIXED in the wording (re-grade of `8eac055`, new item 4; bears on O9)
Found by the re-grade's refuter (`both.js`: "cites 723 model-resolvable 97 also-in-source 97"; e.g.
source `routes.core1[6]` `{next_hop:"", out_intf:"Vlan30"}` is modelled as `{nextHop:null,…}`).
**Fix, verified in code:** when a compiled record carries the citation as its source cite
(`projectsSource`, `Inspector.tsx:763`), the Data note (`:986–992`) and Provenance's "Resolved by"
(`:1137`) say it is also a path in the source snapshot and that what is shown is the compiled
projection, which "may differ from the source record"; model-only paths (`devices[0]`, `coverage`,
`links[0]`) keep the plain wording. **Pinned by** `Inspector.test.tsx` (62 of 62 re-run), including a
per-collection sweep and a model-only guard. Reported: 2 red before; `projectsSource` forced false
turns both red. No compiler or data change: the raw source record is still not viewable (O9).

### R96. B7 — the palette, the keyboard reference, the popovers and the status bar's own coverage disclosure covered the coverage figures without stating them — FIXED: every overlay now states them (re-grade of `8eac055`, B7 FAIL; closes O32)
Found by the re-grade (B7 FAIL: at 390 × 844 with Ctrl+K open, `palette__foot` over "23/26 collected"
and "RIBs 2/26", `palette__scope` over "ACLs 1/26"; O32, deferred until then as a question of B7's
scope). W7-B7's probe widened it (reported): 186 of 270 figure checks passed over 5 viewports × 2
themes × every discovered overlay — the palette and the keyboard reference failed at every width, the
Display popover at 390 and 320 — and the status bar's own disclosure (`.covpanel`, docked over the bar
at ≤ 767 px) stated the figures only as table cells. **Fix, verified in code.** `CoverageStatement`
(`primitives.tsx:1075`) is the last child of both the Dialog (`:1290`) and the Popover (`:1489`), and
the gate rendered it in the disclosure too (`StatusBar.tsx:58`, `:408`); its text is read once from
`T8_coverageLine()` with `ribCountQualifier()` on the RIB segment ("coverage 23/26 collected · RIBs 2/26
(both shown incomplete) · ACLs 1/26 · link centrality 25/44 · snapshot 9580aa09 2026-08-07",
reported), takes no tab stop, is not a live region, and is cached at module level so opening reads no
dataset record. Its styles moved to `primitives.css:1185–1215` (the gate). The probe also found the
Popover primitive clamped only its LEFT edge (6 of 20 panels partly off screen at 320, 390 and 768,
reported); it now keeps an 8 px gutter on the right and, when a panel does not fit below its trigger,
opens above if there is more room there and is otherwise capped (`primitives.tsx:1219–1246`). A new
sticky coverage line without `will-change` was caught by `sticky-layer.test.ts` during the wave and
fixed. **Pinned by** `src/app/coverage-under-modal.test.tsx` — 12 of 12 re-run green: it finds every
`<Dialog`/`<Popover` consumer by scanning `src`, requires its opener table to equal that set, opens each
(the Header in both its wide and its narrow layout), and asserts the open overlay carries the status
bar's own rendered strings and every T8 segment; its ratchet of raw overlays without the statement is
`[]` (`:346`); and a behavioural test opens the disclosure from every `#status-bar button[aria-expanded]`
(`:352`) — plus `primitives.test.tsx` (44 of 44, "Popover stays inside the viewport") and
`sticky-layer.test.ts` (11 of 11). Reported: 7 red before; each render site mutated out, red; the
gate's probe on the preview "270 of 270" figure checks and "64 of 64" panels inside the viewport; a
non-dialog popup probe 654 of 654 (which did not assert that each combobox's list opened, O45). The
palette and the keyboard reference each gained one line of height (J5: O30). B7 is not re-graded here.

### R97. D4 — the pane switch marked its selected option only by a 1.17–1.20:1 fill and a 2.2–2.52:1 ink shift, and the same shape was in the other selected-state rules a class guard found — FIXED, with that guard (re-grade of `8eac055`, new item 3; D4 PASS overturned by refutation)
Found by the re-grade's refuter (`.paneswitch__btn[aria-checked="true"]`: fill 1.17, ink 2.52 light;
1.2 and 2.2 dark; the border identical in both states, `App.css:273–276` at `8eac055`). **Fix, verified
in code.** The checked pane switch (and pressed `.paneswitch__fabric`) carries `box-shadow: inset 0 -2px
0 var(--accent)`, and under forced colours a `Highlight` border (`App.css:280–293`). A new guard,
`src/ui/selected-state-contrast.test.ts`, derives the state vocabulary from the components (the ARIA
selection states; `data-*` twins of them; `data-*` attributes named with a selection word; and, added
in the continuation, a selection word as the VALUE of an attribute a component writes), collects every
such rule in every stylesheet (forced-colors and print blocks excepted, `:246–247`), and measures fill,
ink, each border side, inset bar, `::before`/`::after` bar and outline against the unselected appearance
over every surface token in both themes, also while each co-occurring persistent state of the element
is on; the worst ground decides, against 3:1; an orphan check requires every rendered ARIA selection
state to have a rule. Its own header calls it a source-and-token tripwire, not rendered evidence. Fixed
under it by W7-D4: the pressed/active `ui-btn`, the coverage table's current row (bar on
`.cov__c-label`), the highlighted covpanel sections, the pressed `fabric3d__btn`, and the 3D label's
selected state, which lost its indicator whenever a claim outline also applied — selecting a device
makes it its own cut point, and the cut rule replaced the selection outline (reported 2.47:1 light,
1.82:1 dark; identical under a finding or trace alarm) — now a `::before` underline no claim rule paints
(`Fabric3D.css:183`). Fixed by the gate on W7-D4's figures: `.ag__cell[aria-selected]`
(`DataGrid.css:221`), `.pq-suggest__opt[aria-selected]` (`PriorityQueue.css:272`),
`.dp-list__row[data-selected]` (`DevicePane.css:480`), `.jsonview__row[data-current-match]` and the
previously unstyled `.jsonview__row[aria-selected]`, with a combination rule that keeps them apart
(`Inspector.css:564–585`), and `.hop[data-active]`, whose `border-color` had also overwritten the band's
left edge (now top, right and bottom `--text`, `PathTrace.css:350–355`). **The gate found a defect in
the guard itself** by attacking its own edit (reported): a rule that needs two selection states was
credited to each state alone, so the plain JSON-row bar mutated to `--border` (about 1.3:1) still read
4.86:1. `needsAnotherState` (`:755`) now leaves such rules out of a state that has its own, pinned by
"judges a state on its own rule, not on a rule that also needs another selected state" (`:861`); the
honest figure for that bar is 3.30 light / 3.24 dark. **Pinned by** the guard, 16 of 16 re-run green
(per-file tests over every stylesheet, the vocabulary's non-vacuity, the co-state pairing, a sibling
known to pass). Reported: guard figures after, worst ground, 4.86 light / 8.33 dark for the accent bars
and 5.67 / 9.98 for the label; in the browser the pane switch's underline 4.86–5.67 light and 8.33–9.98
dark, and the gate's bars 5.28–9.30 against their fills; checked pane switch rgb(55,0,110) against
rgb(0,0,0) under forced colours; each mutation red, restored. Not covered: under forced colours the
gate's five new bars drop, as the fills did (O45); the accent's new use needs the owner (O46); the frames
it changes are O42. D4 is not re-graded here.

### R98. D4 residual — the light-theme scroll-edge shadow darkened edge-clipped text below 4.5:1 — FIXED (re-grade of `8eac055`, new item 8)
Disclosed by the re-grade's D4 first pass: 3.92:1 at the 5th percentile and 3.62:1 on an Inspector key
under the 4 px shadow at 22 % black. **Fix, verified in code:** the ink is a theme token,
`--scroll-scrim-ink` (`tokens.css:238`, light 7 %; `:338` and `:392`, dark 52 %), read by
`shell.css:186` and `Inspector.css:161` with no fallback (the gate dropped the last dead 22 % one).
**Pinned by** `contrast.test.ts` — 24 of 24 re-run: "text scrolled under the scroll-edge shadow keeps
4.5:1" over every palette block, the two dark blocks held identical, and (the gate's) every
`var(--scroll-scrim-ink)` in `src/**/*.css` without a fallback. Reported: red at 22 % (`--text-faint`
3.17:1 on `--surface-1`, 3.37:1 on `--bg`); the new light floor 4.60:1 and 4.87:1; the only changed
pixels a 4-CSS-px band at scroll-region bottoms, in 15 light frames (O42).

### R99. D8 — under forced colours the selected tab looked like its siblings — FIXED in CSS; NO unit pin (found in passing by W7-D4)
`.ui-tab[aria-selected]`'s forced-colors `box-shadow: inset 0 -2px 0 Highlight` computed to `none` under
`forcedColors: active` (reported). **Verified in code:** `primitives.css:1163–1166` replaces it with
`border-bottom: 2px solid Highlight`, its comment recording the measurement; reported after: the
selected tab's bottom border 2 px rgb(55,0,110) against 0 px. **No test pins it:** the selected-state
guard excludes forced-colors blocks by design (`selected-state-contrast.test.ts:246–247`), and the
reconciler's grep finds no other test reading this rule. W7-D4 also gave forced-colors `Highlight` edges
to the pane switch, the pressed `ui-btn`, the `fabric3d` button, the coverage row and sections and the
3D selected label (reported). D8 was PASS at `8eac055`, checked in forced colours on state 06 only.

### R100. F3 evidence integrity — `layout-nonfinite-option` was "killed" by an error-message mismatch, and `claims.ts` cited a mutation id that does not exist — FIXED (re-grade of `8eac055`, its F3 gap; W7-F3's lead)
Found by the re-grade (F3 UNPROVEN; the mismatch is in its gap). **Fix, verified in code and by run:**
`review/mutation-check.mjs` requires every mutation to name, in `killedBy`, the assertion that exists to
catch it, and credits a kill only when that assertion fails and the failure is not a bare `toThrow`
message mismatch; anything else is MISATTRIBUTED and fails the run, and a crash is INCONCLUSIVE (header
`:22–30`). `layout.test.ts` gains "refuses every non-finite numeric option before laying anything out…",
over every numeric `LayoutOptions` key (derived through the type, so `tsc` fails on a missing or extra
key — reported, TS1360 and TS2353 in a scratch probe). The reconciler's `--only
layout-nonfinite-option`: "KILLED … by the targeted assertion src/fabric3d/layout.test.ts:926:86 …
AssertionError: a non-finite option was not refused before layout work began", exit 0; `layout.test.ts`
50 of 50. Reported: before the rule, MISATTRIBUTED against the unchanged tests; with the rule removed
the old false kill returns; the full run 21 of 21 KILLED, each by its targeted assertion. W7-F3 also
found `src/core/claims.ts` citing `claims-c1-empty-traversal`, an id `--list` never printed; the gate
replaced it with "claims-c1-decided-owner and claims-c1-both-owners" (`claims.ts:491–492`) and added a
`source-hygiene.test.ts` block requiring every id after a `mutation-check.mjs` mention in `src` to be
one of the harness's ids (17 of 17 re-run; reported red first on that file). F3 itself stays UNPROVEN
(O34).

### R101. D5 — `docs/target-size-exceptions.md` was cited by the brief but did not exist, and the "row is the target" argument was written nowhere — FIXED by rewording the brief (re-grade of `8eac055`, new item 7)
W7-F3 did not create the file: `target-size.test.ts` asserts its absence, and no spacing exception
exists to list. It offered two options and left a draft in the orchestrating session's scratchpad; the
gate chose the second — no file — and the owner committed it in `ba7b456`. **Verified:** the file is
absent; `design-brief.md` §3.2 (`:238–255`) says the file exists only while a spacing exception does
(none today) and carries the argument — a data row's click activates it (`handlers.activate`), a cell
click moves the roving focus (`handlers.move`) and bubbles to the row, a cell that holds its own control
(`GridColumn.interactive`) stops the click and is itself held to the 24 px floor, `.ag__row--data` sets
`cursor: default` and no `.ag__cell` rule declares a cursor — and the §7 2.5.8 row agrees. **Pinned
by** `target-size.test.ts`'s "the brief states why a sub-24px grid cell is not a target, and the code
still makes that true" (13 of 13 re-run), which reads §3.2 and the 2.5.8 row whitespace-normalised and
the `DataGrid.tsx`/`DataGrid.css` code they cite. The absence assertion is unchanged. The census, not the
paragraph, remains D5's evidence (reported at the draft: 518 of 740 cells 14.84–18.13 px tall in rows
of at least 32 px, dev :4180, 577 px viewport).

### R102. F2 — `EvidencePane.targets-cap.test.tsx`'s "every access list is on screen" half judged no access list in 116 of 145 cases — FIXED (re-grade of `8eac055`, new item 6, its first half)
**Fix, verified in the test:** "%s: every one of its access lists is on screen" now runs over the 29
findings whose records include an access list, each asserting at least one was judged and none cut;
"%s: a list shorter than its records states the cap in words, and a whole list states none" runs over
all 145; a precondition test checks both visit counts (`:76–114`). 178 of 178 re-run green. Reported:
the old combined test with a per-case count, 116 red; an ACL-cutting product mutant in a scratch copy
fails 31 cases. The item's second half — `composite-tabstop.test.tsx` pins non-vacuity only for idle at
1440 — was not addressed (O44).

### O32. The Ctrl+K palette covers the status bar's coverage group (B7) at 390 px while it is open — FIXED in wave 7 (R96), after the re-grade of `8eac055` graded it a B7 FAIL (moved from Open, 2026-09-26)
From the re-grade of `443a05a`, which upheld B7 and listed this as a lead (a transient modal). No
wave-4 cluster addressed it, and whether a modal that covers the coverage figures while it is open is
a defect under B7 had not been decided. **Status at `78bdba5`:** the re-grade of `70bea72` upheld B7
and extended the lead — with the Keyboard-shortcuts dialog open at 320x568 the dialog body fully covers
"23/26 collected", "RIBs" and "ACLs" — and still treated it as a transient modal. **Status at
`8eac055`:** the re-grade of `78bdba5` upheld B7 without examining modals open; not touched in wave 6.
**Status at `34bd435` — FIXED.** The re-grade of `8eac055` graded B7 as written ("permanently and
visibly") and failed it on exactly this state. Wave 7 did not need the scope decision: every Dialog and
Popover, and the status bar's own disclosure, now states the figures from the same owner (R96),
pinned by `coverage-under-modal.test.tsx` (12 of 12 re-run). B7 is not re-graded here.

### O38. B1 test quality — `scene.test.ts`'s null-band colour test asserted over no device — FIXED in wave 7 (re-grade of `78bdba5`, new item 6; moved from Open, 2026-09-26)
Found by the re-grade of `78bdba5`, verified by the reconciler at `8eac055`, and confirmed by the
re-grade of `8eac055` ("`scene.test.ts:122` made exactly 1 assertion at run time"): the loop judged
collected null-band devices only, and all 3 in `fabric.json` are uncollected. **Fix, verified in the
test:** the loop's own set is the denominator (`scene.test.ts:135–164`) — every null-band device, each
judged by the colour actually drawn (the ghost shell's material when uncollected, the body instance
colour when collected), with `judged === nullBand.length` asserted. 44 of 44 re-run green. Reported:
the non-vacuity count on the old loop red ("expected +0 to be 3"); a green-shell product mutant in a
scratch copy turns the new test red, and `6a5d830`'s version passes that same mutant — so the old test
was hollow, as recorded.

### O39. Documents that the history and the code contradicted — `mutation-check.mjs`'s "the only commit" and "no commit holds", `refutation.md`'s "attested in prose only" and its mutation counts, and `acceptance.md` F2's "45 of 135" — FIXED in wave 7 (moved from Open, 2026-09-26)
Found by the re-grade of `78bdba5` and confirmed by the re-grade of `8eac055`. **What they said at
`8eac055`** (the wave-6 record): `mutation-check.mjs:4–5`, "The only commit of this tree already
contains every fix", against 13 commits rooted at `50a3dc5`, and a printed LIMIT saying the historical
source was one "which no commit holds"; `refutation.md` §0 and the §7 table, "attested in prose only"
for forwarding too, and "2 mutations" on the layout row where `--list` held 5; `acceptance.md` F2, "45
of 135". **Verified by the reconciler at `34bd435`:** `mutation-check.mjs`'s header (`:4–13`) names the root and which guards
predate it (blast, layout, query, the compiler, forwarding §1.1 and R19), says where history exists
(R17 and claims C1/C2 in `254694b`; the C2/C3 follow-up and both O15 source-binding guards in
`1d19e22`) and points to `--history`, whose output the reconciler reproduced (16 commits, root
`50a3dc5`); its printed LIMIT scopes "no commit holds that source" to blast, layout, query, the
compiler and forwarding's §1.1 and R19 guards, and says `--history` names the commit where one does. `refutation.md`'s §7 table (`:371–375`) reads "partly" for forwarding (R17 red on the
root) and "no — guards predate the root; attested in prose only" for the other four, with layout at 5
mutations, and its §0 is rewritten per engine. `acceptance.md` F2 reads "51 of the 153 test files
tracked under `src/` at `6a5d830`, and 54 of 159 on that wave's working tree"; the reconciler's
`git grep` with F2's own pattern gives 51 of 153 at `6a5d830` and 54 of 159 at both `ba7b456` and
`34bd435`. None of the corrected statements hard-codes a commit count that will date: both documents
point to `git rev-list` or `--history`. Still not a contradiction, as recorded at `8eac055`:
`acceptance.md:146`, "the only commit is `857b520`", is dated 2026-09-21 and corrected in place the next
day, so it reads as history. Reported: W7-F3's reproduction of the history reds it cites
(R17's on `50a3dc5`, 5 failed and 1 passed; claims C2/C3's on `254694b`, 2 failed and 37 passed).

> **Repair wave 6 (reconciled 2026-09-25, committed as `8eac055`).** Entries R81–R90 below, O26
> moved here from Open, the new O38–O43 under Open, and the status notes and corrected headings on
> R10, R64, R80, O6, O9, O10, O12–O14, O16, O17, O19–O23, O25 and O27–O37 record two things that had not
> been written here: the new items 1–11 and the status changes of the independent re-grade of
> `78bdba5` (`docs/acceptance-report.md`, committed in `efc3929`: 24 PASS — 23 upheld under attack, D2
> unrefuted — 7 FAIL, 8 UNPROVEN; its "Known issues" section lists items 1–11 as "not yet recorded in
> `open-issues.md`", and `efc3929`'s edit of this file recorded wave 5 only), and what the five wave-6
> repair clusters (W6-b6 path citations: B6; W6-a4 filtered queue reveal: A4; W6-a5 reset damping:
> A5; W6-d1-d5 off-view pointer: D1, D5; W6-f2 suite load independence: F2, O26) and the merged-tree
> gate (eight cross-cluster requests applied, none refused, and a regression sweep that found and fixed
> three defects no earlier gate had probed: R87, R89, R90) reported. **Every FIXED below was checked by
> the reconciler before it was written:** the code named was read at `8eac055`, and the named tests were
> re-run on the committed tree in one invocation — 28 files, 1,667 tests, 1,667 passed, 0 failed, 0
> skipped, vitest exit 0, slowest test 3.2 s (JSON report in the orchestrating session's scratchpad) —
> including `tracked-sources.test.ts` (9 of 9), `mock-classification.test.ts` (3 of 3) and
> `source-hygiene.test.ts` (14 of 14); and `node review/mutation-check.mjs --only` the three new layout
> mutations: baseline green, 3 of 3 KILLED, exit 0 (O26), `git status` clean before and after (the
> script works in a scratch copy). The reconciler also confirmed from `git show 8eac055` that
> `review/capture-motion.mjs` is untouched; `vitest.config.ts` changes only its header comment
> (`testTimeout` and `hookTimeout` stay `30_000`); no added test line calls `.skip`, `.only` or `.todo`;
> and no test file loses `expect(` lines on balance — 126 added and 37 removed across the modified test
> files, plus 146 in the six new ones. **Verified by the orchestrator at `8eac055`:** `tsc` (app,
> scripts `--noImplicitAny`, config) all exit 0; `npm run build` exit 0; `vitest` 153 files, 3,459
> tests, exit 0 after the commit; the gated commit's tree and message scan clean; no capture-motion
> threshold changed; no `testTimeout` or `hookTimeout` changed; no skip/only/todo added; no test file
> lost `expect()` lines on balance (126 added, 37 removed across the wave — the same figures as the
> reconciler's count over the modified files). **Not re-run by the reconciler, and cited as "reported"
> wherever it appears:** every browser harness (`capture.mjs app`, `text`, `reduced` and `twice 5`;
> `capture-motion.mjs`; `audit-d3-focus.mjs`, default, `--sweep` and `--self-removing`;
> `layout-guard.mjs`), the gate's regression sweep, the agents' in-page probes and screenshots (the
> orchestrating session's scratchpad), the W6-f2 cluster's fresh-clone runs, the full 21-mutation
> `mutation-check.mjs` run, and every wave-6 mutation other than the three above. A fixed defect does
> not by itself move its criterion; nothing here is a re-grade.
>
> **History since the wave-5 record** (it continues in the wave-7 banner above). `efc3929` (docs only: the wave-5 record and the re-grade of
> `78bdba5`) → `8eac055` (repair wave 6, 44 files, 4,528 insertions and 552 deletions). An earlier
> launch of wave 6 did no work: all 11 agents were refused by the account's weekly usage limit within
> seconds, and the tree stayed at `efc3929` (orchestrator, verified clean; consistent with the
> reconciler's `git reflog`, which shows no HEAD movement between `efc3929`, 2026-09-24 11:33 +0300, and
> `8eac055`, 2026-09-25 15:03 +0300). The host also rebooted on 2026-09-24 at 14:17 — the
> orchestrator's reading is "most likely on an empty battery". **The reconciler's read of the System
> event log narrows that:** the host booted at 14:17:59 +0300 after an orderly restart requested through
> the Start menu (User32 1074 at 14:17:35, EventLog 6006, Kernel-Power 109 "Power Action Reboot"), with
> no Kernel-Power 41 or EventLog 6008 between 12:00 and 14:30, so the reboot itself was not a power
> loss; the battery shows earlier, as a sleep at 12:08:34 with "Sleep Reason: Battery", followed by
> power-source changes at 12:10, 12:41 and 14:16. `git status` was clean at `8eac055` before this edit.
>
> **Host state at the start of the re-grade of `8eac055`** (orchestrator): on AC at 99 %, the :4180 dev server
> idle at 0 cores (its watcher ignores the generated review output, R80), host CPU 43 % from the
> owner's own use. The reconciler's own reads around 15:10 +0300: on AC (`Win32_Battery` status 2) at
> 99 %; the :4180 listener at 0.000 cores over 10 s; `LoadPercentage` 9–19 %. That listener started at
> 2026-09-25 07:22:35 +0300, after `vite.config.ts`'s last write (2026-09-24 07:27:23), so it runs the
> committed ignore list — the question R80 left open.

### R81. B6 — the Path surface showed the RIB-incompleteness claim, and the core2 no-ACL caveat, without their citations — FIXED, with a per-claim guard (re-grade of `78bdba5`, new item 3); the `70bea72` PASS was a false PASS, not a code regression; B6 failed again at `8eac055` on a surface this guard did not reach, the preset cards (R92), and the class is now censused across every surface (R93, R94)
Found by the re-grade of `78bdba5` (B6 overturned PASS → FAIL): on
`?s=path&flow=10.0.10.50>10.0.30.10>tcp>3389&hop=0` "FULL/DR, yet the table" was shown 5 times and
its citations `routing_neighbors.core1.ospf[0]` and `protocol_assessability.rows[123]`/`[124]` 0
times; "240 received prefixes" likewise, and "No ACLs were collected for core2; filtering there is
unobserved, not absent." was shown uncited. (The report calls the "240 received prefixes" flow "the
icmp flow"; W6-b6 found it on the suggested no-route flow `10.0.20.50>198.51.100.7>tcp>443` — the
suggested icmp flow is a core1 trace that never shows it — and both are now tested.)

**Git history — no commit dropped the cites; verified by the reconciler.** `git log --
src/forwarding/rib-completeness.ts` names only `254694b`, `1d19e22` and `8eac055`.
`ribIncompletenessSentence` has joined each reason's `label` and dropped its `cite` since it was
introduced in `254694b` (`:134` there; `:135` at `70bea72` and at `efc3929`), and `78bdba5` does not
touch the file. So the B6 PASS at `70bea72` was a **false PASS** — that first pass counted citations
per page, not per claim — and the `78bdba5` FAIL was the first correct grade. This is not a code
regression.

**Fix, verified in code.** `rib-completeness.ts:139` writes each reason's cite in parentheses after
its label (`${x.label} (${x.cite})`), and the engine's claims, caveats and policy-gap sentences carry
the record behind each clause the same way — both no-ACL caveat sites now read "No ACLs were collected
for ${host} (${fabric.coverage.cite}); filtering there is unobserved, not absent." (`engine.ts:2169`,
`:2212`). The new `src/panels/cited-text.tsx` (`CitedText`, `:88`; `citesIn`, `:78`) renders every
in-sentence citation as the standard citation control, in place; what counts as a citation is decided
by the Inspector's own resolver, `citationCandidates` (`Inspector.tsx:204`), not by a list of names.
ClaimCard, HopList and PathTrace render the claim, caveats, Filtering row, hop notes, intent bound and
announcement through it (in the diff). `HopList.ingress-reason.test.tsx`'s NO_ACLS regex pins the
host-attribution wording; the cluster moved the gap cite after that clause rather than change the test
(reported; the file re-run green, 11 of 11). `cited-text.tsx` is the one module wave 6 added to the
build, tracked in `8eac055` (O10). **Pinned by** `src/panels/PathTrace.claim-cites.test.tsx` — 13 of
13 re-run green: on the refuter's own flows, every element showing the claim carries every citation the
model holds for it, each resolving; the core2 caveat; and a sweep of `suggestedFlows()` plus a source ×
destination grid over the snapshot's SVI and gateway addresses and four services, in which every clause
naming a device or an IPv4 address carries a resolving citation, every policy gap writes its own cite
into its label, and no rendered prose element of ClaimCard, HopList or IntentClaimCard shows inert
citation text. Reported: 8 of 9 red on the unfixed tree (440 uncited engine clauses, 26 gap labels,
5,097 rendered offenders); the `x.label`-only sentence restored, 8 of 13 red; the ClaimCard's
`CitedText` replaced by plain text, 9 red; the cite removed from both no-ACL sites, red. Live dev
server (reported): on the 3389 flow each of the three cites appears 5 times, and the
`routing_neighbors.core1.ospf[0]` control opens the Inspector at
`rib-evidence.json#hosts.core1.adjacencies[0]`, labelled as the compiled record that carries the
citation (O9). The gate's sweep (reported): 56 of 56 state × width × theme cases with 0 inert
citation-shaped tokens; an engine sweep of 16,665 traces with 0 dead printed citations, in which 6,076
claims carry no citation — all of flows rejected before any evidence was consulted — and only the 5
generic model-limit caveats carry none. **Consequences, open:** 12 recorded app frames (the 05, 06 and
08 path states, both themes, 1440 and 1920) now differ from the local, untracked `review/shots/app`
baseline because the path panel is longer — promoting them is an owner decision (O42); and in-prose
citation chips keep the 24 px hit area and 14ch minimum width, so in the ~228 px rail each often takes
its own line (O43). B6 is not re-graded here.

### R82. A4 — a finding selected from another surface was not revealed when a queue filter hid its row — FIXED (re-grade of `78bdba5`, new item 1); a grading overturn, present since `50a3dc5` (reported)
Found by the re-grade (A4 overturned PASS → FAIL): `?q=severity%3ACritical`, then Ctrl+K "F120" Enter —
the URL, status bar, scope bar, Inspector and fabric label said F120, and the queue had no row, mark or
mention of it. **Not a code regression** (W6-a4, reported; not reproduced by the reconciler): the same
store-level probe on archived trees returned 0 current rows and no F120 in the rail at `50a3dc5`,
`70bea72` (graded PASS) and `efc3929`; the `70bea72` first pass tested only an unfiltered queue.

**Fix, verified in code.** `PriorityQueue.tsx` pins a selected finding that the effective query or
scope hides above the filtered rows, in an "Outside your filter" group (`:1360`), marked current and
revealed with no interaction. The rail states "<id> is selected, but your filter hides it: <parts>
excludes it. …" (`:2306`), and a 24 px "Show <id> in place" button (`:2312`, `:2337`) removes exactly
the hiding parts and says so ("Removed … from the filter, so … shows in place.", `:1299`), leaving the
row in place, current, in view and focused. Which parts hide the row is computed by re-running each
parsed clause and text term alone over the corpus — no key list (reported). Design choices recorded by
the cluster: the pinned row counts in Ctrl+A and copy but not in "N of M shown" or the device-mark
count; a device or link selection never pins or narrows; the pinned row carries its future in-place
React key, so focus moves rather than remounts; a 5 s input-cancelled ResizeObserver hold keeps the
landed row on screen while other surfaces re-filter. **Pinned by**
`src/panels/PriorityQueue.filtered-reveal.test.tsx` — 41 of 41 re-run green, derived from `FILTER_KEYS`
(every registered clause key, positive and negated), free and excluded text, the severity, role and
uncollected chips and cross-layer clauses, with two negative controls — and `PriorityQueue.test.tsx`'s
"a selection from another surface is revealed, not merely marked", now with the filtered case (38 of
38 re-run green). Reported: 37 of 40 red before; three mutations red (38, 33 and 34 failed) and
restored from saved copies. Browser (reported): the refuter's repro at 1920 × 1080 shows F120 pinned,
one `aria-current` row, in view; after "Show F120 in place" the filter is removed and focus is on the
row. **Measurement note:** the refuter's `_ref_a4d.mjs` waits a fixed 2 s, which is not a sound oracle
on a loaded host — the palette's own URL commit measured 1.1–6.9 s after Enter, and the unfiltered
(PASS) case also missed 2 s — so a census must poll for the condition (reported). This fix unmasked
R87. A4 is not re-graded here.

### R83. A5 — Reset view and Home left the OrbitControls damping tail running — FIXED (re-grade of `78bdba5`, new item 2; promoted from O37's A5 lead)
Found by the re-grade (A5 overturned PASS → FAIL): a 240 px orbit drag, 300 ms, then Reset view left
core1 about 64 px from home for 40 s; the Home key drifted "11→22 px"; the error grows as the frame
rate falls. O37 had carried it as a lead since the re-grade of `70bea72`.

**Fix, verified in code.** `camera.ts` has one owner, `discardInertia` (`:576`), which zeroes
OrbitControls' pending `_sphericalDelta`, `_panOffset`, `_scale` and `_performCursorZoom`. It runs in
`moveTo` before the from-pose is taken (`:912`), on every tween frame including the landing (`:1026`),
and on the reduced-motion landing in `setReducedMotion` (`:985`); Home, Reset view, device focus, the
trace re-framing and the immediate jump all go through `moveTo`. `pendingInertiaOf` (`:517`) throws at
construction if a three upgrade renames those private fields, so the discard cannot silently become a
no-op. **Pinned by** `src/fabric3d/camera.reset-damping.test.ts` — 30 of 30 re-run green: home after an
orbit drag, pan drag, wheel dolly, key orbit and key pan at 60, 9 and 3 fps; `moveTo` to a device
framing at all three rates; the immediate path; reduced motion switched on mid-coast and mid-tween; a
gesture made during the tween; a normal tail after landing; the fail-loud accessor. Reported: 28 of 29
red before; five targeted mutations red, and a sixth (a discard in `snapHome`) green because that code
cannot be reached with pending inertia, so the call was removed and the reason written into the
comment; in the browser the refuter's protocol returns core1 to (474.45, 82.23) with 0.000 px error,
headless and headed, for Reset and Home, against 7.4–8.8 px and growing with the fix disabled. The
gate's sweep reports 24 of 24 at 0 px, with its own stated limit that it did not record the pose right
after the drag, so those 24 do not by themselves prove the camera moved. **Behaviour change,
recorded:** while a programmatic move (the 620 ms tween) is in flight it owns the camera — a drag, key
orbit or wheel made during it is discarded rather than knocking the landing off; gestures after the
landing behave as before, tail included (tested). Whether a gesture should instead take over from a
tween is a design decision (O42). On SwiftShader at about 4 fps one frame gap can exceed the whole
tween, so Reset shows as a jump; the landing is exact (O43). A5 is not re-graded here.

### R84. D1 and D5 — the off-view finding pointer was keyboard-unreachable, `aria-hidden`, a 16.84 px target, and could sit under the HUD — FIXED, and both censuses now find operable elements by what they do (re-grade of `78bdba5`, new item 4)
Found by the re-grade (D1 and D5 overturned PASS → FAIL): `.fabric3d-pointer` for access5 was a
`<span onClick>` inside the aria-hidden label layer, `tabindex:-1`, never reached in a 250-stop Tab
walk, 141.23 × 16.84 CSS px, and in dark theme under the blast-radius HUD. W6-d1-d5's census on the
unfixed code reproduced all three failures (reported).

**Fix, verified in code.** The pointer is a native `<button type="button">` (`FabricLabels.tsx:1299`)
in its own layer, `.fabric3d__pointers` (`FabricLabels.tsx:1294`; `Fabric3D.css:948`), a sibling of the
aria-hidden label layer. Its name is the finding, the host and "off view"; it carries `hidden` whenever
it is not drawn, so an undrawn pointer is no Tab stop; it is at least `var(--target-min)` in both axes
(`Fabric3D.css:962`); its focus ring uses `--focus` in a rule heavier than the severity outlines
(reported: at equal weight the High outline won); it is placed clear of every other stage layer
(`pointerObstacles`, `clearCentre`: `FabricLabels.tsx:341`, `:497`); and when it leaves while holding
focus, focus goes to the canvas (`onPointerFocusLost`, `Fabric3D.tsx:1263`), never `<body>`. The cluster
kept it a control rather than dropping the affordance: the brief says a finding selection never moves
the camera, so this is the only in-place answer to "where is this finding?" when the host is off view.
**Census class fixes.** `src/ui/target-size.test.ts` now finds targets by handler (any class the JSX
puts on an element with a pointer or click handler) and judges a declared block size, or one line of
the element's own text plus padding and border; groups that set neither font-size nor line-height are
printed UNDECIDED, not passed (11 today, reported), and the inline axis is still not judged from source
(O43). `review/audit-d3-focus.mjs --sweep` gains `operableCensus`, which finds elements by React
pointer handler or cursor, never by role or tabindex, and requires each to be reached by the real Tab
lap, outside aria-hidden and at least 24 × 24, plus a sweep state that pans until an off-view pointer
is drawn and fails if no width drew one (in the diff; the harness is outside every type-checked
project, O27). **Pinned by** `src/fabric3d/FabricLabels.pointer.test.tsx` — 4 of 4 re-run green (a
named button outside every aria-hidden subtree; activation frames the host and no handler cancels Enter
or Space; placed clear of the HUD's keep-out box; unfocusable once it leaves, with focus handed on) —
`Fabric3D.test.tsx` (68 of 68, its pointer test extended) and `target-size.test.ts` (12 of 12).
Reported: all 4 red before, and the widened target-size scan red on exactly the six
`.fabric3d-pointer` rules (16.85 px computed); in the browser, 149.23 × 24 in both themes, reached
after one Tab from the canvas, Enter and Space both frame access5; the gate's `--sweep` "3032 operable
element(s) censused (0 with no role and no tabindex), 4 off-view pointer(s) drawn; 0 failure(s)". D1 and
D5 are not re-graded here. The refuter's two further leads under item 4 are O41.

### R85. F2 — 12 load timeouts on a fresh clone of `78bdba5`, and the load-sensitive files behind them — FIXED by making each test cheaper and counting its work, with no timeout raised (re-grade of `78bdba5`, new item 5)
Found by the re-grade (F2 FAIL): a fresh clone of `78bdba5` at about 85 % host load went red on 12
timeouts (31–62 s against 30 s), 8 of them in `composite-tabstop.test.tsx`, which the report noted this
file did not record; the others were `tracked-sources` (35.6 and 31.4 s), `determinism` (31.5 s) and
`HopList.decider-header` (32.1 s).

**Fix (W6-f2 and, on its requests, the gate), verified in the tests.** `composite-tabstop.test.tsx`: the
keyboard walk makes one full turn of a group another walk follows and a reach for the last group,
instead of 2n presses, pinned by a press-count test; the lazy Fabric3D chunk is preloaded at
collection; the vacuity and opener proofs are asserted inside the census case that mounts the same
state; React dev's owner-stack capture is off while frames are built and restored before every
assertion. `tracked-sources.test.ts` builds the compilers' program once, with `noLib` and `types: []`,
guarded by a precondition test that the default libraries and every type directive resolve inside
`node_modules` (9 of 9 re-run green). `determinism.test.ts` parses each distinct text once and runs one
case per source file (163 of 163). `HopList.decider-header.test.tsx` renders one flow per test and
unmounts its roots, under an `afterEach` guard of at most one rendered trace per test (52 of 52). The
gate applied the same shape to the files the cluster measured failing under saturation:
`reaim-tab-and-restore` and `selection-origin` wait a bounded 50 flush turns instead of a
`Date.now()+8000` deadline (8 and 8); `focus-return.guard`, `verdict-wording.guard`, `band-read.guard`
and `HopList.admin-distance` build their program once, counted, with one case per source file (92, 80,
79 and 119); `motion-inventory` reads the tree once (102); `self-removing-focus` discovers its stops
once and runs one case per (stop, key) — 355 cases, where there were two tests of about 55 s each under
a 1,200,000 ms limit; `DevicePane.cite` and `DevicePane` split per device and link (100 and 61). All
re-run green in the reconciler's invocation, whose slowest single test was 3.2 s
(`HopList.admin-distance`'s shared program build) on a host at 9–19 % load; `testTimeout` is unchanged.
Reported: each change red first and under mutation; a fresh `git clone` of `efc3929` plus the cluster's
six files, `npm ci`, under an adaptive burner holding about 85 % CPU, twice "Tests 2439 passed (2439)",
exit 0, the cluster's slowest test 6.2 s; the gate's full suite twice, quiet and under 12 parallel
builds, with no timeout. **Limits, stated by the cluster:** earlier runs on a host that was also
memory-thrashing (commit 20–22 GB on 16 GB) failed, and "under memory thrash, no jsdom full-app test is
load-independent"; the final `composite-tabstop` has not run under that thrash; and nothing has been
run from a clone of `8eac055` (O23). The harness defect this exposed is R86; O26 is closed below. F2
is not re-graded here.

### R86. `composite-tabstop.test.tsx`'s `clean()` reset a named subset of the store, so state leaked from one census case into the next — FIXED (found by W6-f2)
A hand-maintained list standing in for its class: `clean()` called `reset()` plus three named fields,
so `evidenceTab` and `focusReturn` carried from one case into the next; the old 2n walk hid it by
turning every group back to its start (reported). **Fix, verified in the test:** `clean()` replaces
the whole store with `getInitialState()` (`composite-tabstop.test.tsx:111`), pinned by a test that
moves every field (reported red before: "fields clean() left as the previous case set them: expected [
'evidenceTab', 'focusReturn' ] to deeply equal []"). The file is 105 of 105 re-run green. Once state
stopped leaking, the census exposed a real D1 defect (R89).

### R87. At phone width a queue reveal scrolled the reader's focus off screen — FIXED by the gate (found by W6-a4; predates wave 6)
Unmasked by R82. At 390 × 844, Enter on the Evidence pane's "F002 …" button moved focus to the pane's
new title; the queue's selection reveal then scrolled the document by about −5,000 px to show the F002
row, leaving the focused `H2.ev__title` at top 5,383 — off screen (reported; reproduced unfiltered, so
it predates the wave). The `audit-d3-focus.mjs --self-removing` seed used to hide those rows, so no
reveal ran; once hidden selections were revealed it reported 24 phone FAILs on 12 Evidence-pane finding
buttons. **Fix, verified in code:** `DataGrid.tsx:414` `revealThroughAncestors` measures the focused
element outside the grid (`onScreenExtent`, `:447`) before and after each ancestor or document scroll,
undoes a scroll that leaves less of it on screen, and stops; focus inside the grid or on `<body>` does
not restrain it, and a fixed bar the scroll does not move does not block it. **Pinned by**
`src/panels/DataGrid.reveal-focus.test.tsx` — 5 of 5 re-run green (reported: 2 of 5 red before).
Reported: the probe's title at top 366 after the fix, and `--self-removing` "160 self-removing/BODY
case(s), 0 failed. 160 successor(s) checked for visibility, 0 not visible".

### R88. The grid's roving tab stop did not follow the selected row when a filter edit moved it to another index — FIXED by the gate (W6-a4's optional request)
`DataGrid` re-aimed its tab stop only when the target id changed, so after a re-order Tab entered the
grid on whatever row now held the old index (PriorityQueue had worked around it for its own widen
control; reported). **Fix, verified in code:** `DataGrid.tsx:788` `aimedRow` records the row set and
index of the last plain aim, and a new row set re-aims to the target's new index while the roving cell
is still where that aim put it (`:816`); once the reader has moved the cell, their place wins.
**Pinned by** two tests in `DataGrid.test.tsx` (43 of 43 re-run green): the re-aim ("m40 where m30 was
expected" red before, reported) and the reader's moved place winning. Browser (reported):
`severity:Medium` moves F120 to `aria-rowindex` 17 and Tab enters the grid on F120, at 4 of 4 widths.
This is D2's surface (grid keyboard contract); D2 was the one PASS left unrefuted at the re-grade of
`78bdba5`, and R87 and R88 both changed `DataGrid.tsx` since. D2 is not re-graded here.

### R89. D1 — the Device evidence Ports and Routing grids exposed 31, 2 and 9 tab stops on core1 — FIXED by the gate; the census now visits every evidence tab (found by W6-f2 once R86 stopped state leaking)
At 1440 and 390 px with `d=core1`, "Ports on core1" held 31 tab stops (the interface and physical
cells), "Endpoints on core1" 2, and "Routing table for core1" 9 (the Prefix header plus eight cite
buttons) (reported). `composite-tabstop`'s states never visited those tabs — a denominator gap. **Fix,
verified in code:** `DevicePane.tsx:331` `retireInnerStops` sets `tabIndex=-1` on every focusable
descendant of a `RecordGrid` cell — structurally, any focusable element (`FOCUSABLE`, `:327`), not a
list of components — after every commit (`:424`) and from a MutationObserver when a cell's own
component mounts a control (`:429`); Enter/F2 still reach the control and Escape returns to the cell.
`store.ts:19` `EVIDENCE_TABS` is now the one runtime list the `EvidenceTab` type, `decodeInvestigation`'s
URL parser (`:238`), the census and `reaim-tab-and-restore`'s tab list all derive from, replacing a
duplicated hand list. **Pinned by** `src/panels/RecordGrid.tabstop.test.tsx` — 3 of 3 re-run green
(reported red before) — and `composite-tabstop.test.tsx`, whose `STATES` now add one state per
evidence tab derived from `EVIDENCE_TABS` (`:411`), 105 of 105 (reported red in 8 cases on this defect
before the fix).

### R90. D3 — with the fabric list open, pressing Legend opened the legend underneath it — FIXED in CSS by the gate; NO unit pin (found by the gate's regression sweep; predates wave 6)
Both were anchored at the stage's left edge at full height, the tree at z-index 4 over the legend's
3, so the legend's focused close button had 0 of 9 hit points at 768, 1440 and 1920 px;
`audit-d3-focus.mjs --self-removing` showed 4 FAILs "NOT VISIBLE [self-removing successor] … Hide the
legend … on DIV.fabric3d__tree-head" (reported). D3 read PASS at `78bdba5` because no audit had pressed
Legend with the list open. **Fix, verified in code:** `Fabric3D.css:760–763` caps each at half the stage
while both are open (the list shown, or holding focus), the list anchored at the top and the legend at
the bottom; either alone keeps its full height. **No unit test pins it** — the reconciler's grep finds
no test naming the rule or the pairing. Its evidence is the gate's reported browser measurement, 0 of 9
hit points before and 9 of 9 after (tree 92–475, legend 483–866 at 1440), and the final
`--self-removing` run, 0 not visible. The missing pin is O43.

### O26. Wall-clock tripwires in the unit suite — FIXED: the engine and palette halves in wave 4 (R64), `layout.test.ts`'s median in wave 6 (moved from Open, 2026-09-25); R10's "fixed as a class" now holds
**Status at `8eac055` (wave 6) — FIXED.** W6-f2 replaced `layout.test.ts`'s `performance.now()`
median-of-7 under 50 ms with `primitiveOps()` (`layout.test.ts:87`): a count of every call into a
function-valued own property of `Array.prototype`, `Map.prototype`, `Set.prototype` or `Math`, derived by
reflection and wrapped only for the synchronous call. "lays out the full fabric within a counted work
budget stated in its own size, on every seed" (`:1007`) asserts that count (16,206 on every seed,
reported) against a budget stated in the fabric's size — 30,528 at the defaults — and checks each term
on its own, with a known answer that a loop run N times over is over budget and a live-counter
self-test (`:1058`). The comment is rewritten (`:980–1000`): it quotes the old "the other two were
rewritten to match it" as history and says why it was false.
The file is 49 of 49 re-run green. **The red-proof is executed:** the gate added three mutations to
`review/mutation-check.mjs` (`layout-crossings-per-node`, `layout-clearance-quadratic`,
`layout-sweeps-times-n`), and the reconciler ran them: baseline green, then KILLED at 101,088, 99,630
and 242,856 primitive operations against ≤ 30,528, "ENGINE src/fabric3d/layout.ts: PASS — 3 of 3", exit
0. The reconciler's grep finds `performance.now()` in six test files under `src/` and no elapsed-time
assertion: `CommandPalette.test.tsx:727–733`, `engine.test.ts:974–988` and
`engine.work-bound.test.ts:134–166` print their elapsed time as "reported, not asserted" and assert
counts of work, `PathTrace.test.tsx:1352` passes a rAF timestamp, `Inspector.test.tsx:792` is prose, and
`determinism.test.ts` names the call in its detector's prose and planted cases. So `acceptance.md` F2's "Timing is not asserted in the unit
suite" is now true; its "45 of 135" count is still stale (O39). F2 is not re-graded here.

**Status at `78bdba5`, superseded above.** Confirmed by the re-grade of `70bea72` (which cites the
block's `performance.now()` at `:945`); `78bdba5` did not change `layout.test.ts`, whose assertion was
`:953`. The re-grade of `78bdba5` confirmed it again (F2 note). Two statements contradicted it:
`acceptance.md` F2's "Timing is not asserted in the unit suite" and the test's own comment (`:942–943`).

**Status at `70bea72`, superseded above.** The re-grade of `443a05a` confirmed this entry (F2 overturned:
`CommandPalette.test.tsx:717` read 533 ms against 400). Wave 4 replaced the palette bounds with
counts and the engine's median-of-7 tripwires with structural work bounds (R64). Of the test files
that call `performance.now()` (the reconciler's grep: `CommandPalette`, `determinism`, `layout`,
`engine`, `engine.work-bound`, `Inspector`, `PathTrace`), only `layout.test.ts` still asserts on the
elapsed time: "lays out the full 26-node fabric in under 50 ms", median of 7 (`:944–955`). Its
comment argues it has never flaked; it contradicts `vitest.config.ts`'s rule ("a unit test asserts no
wall-clock time"). The gate declined both deleting it (that would loosen an assertion) and
redesigning it (the owner's); a count of the layout's work would replace it.

**Original entry (wave 3).** Reported by the R2 cluster, full-suite runs under four parallel agents: `engine.test.ts` "keeps the
counterexample search inside the same interaction budget" (`:955`, median of 7 = 54.66 ms against the
50 ms tripwire; the new flow-validation entry check costs 0.54 µs per trace) and `CommandPalette.test.tsx`
"opens over an index that already exists, rather than building one" (`:717–718`, `worst` < 400 ms,
measured 620). Both green in isolation (2 of 2 and 37 of 37, reported) and both green in the
reconciler's run and the orchestrator's full run at `443a05a`. Verified in code: the palette bound is a
worst-of-N statistic, the form R10/O2 names as the most fragile, and the engine tripwire is the
median-of-7 form R10 installed. A red from either is indistinguishable from a regression.

> **Repair wave 5 (reconciled 2026-09-24, committed as `78bdba5`).** Entries R67–R80 below, the new
> O35–O37 under Open, and the status notes and corrected headings on R32, O9, O10, O12–O14, O16,
> O17, O19–O23 and O25–O34 record two things that had not been written here: the new items 1–10
> and the status changes of the independent re-grade of `70bea72` (`docs/acceptance-report.md`,
> committed in `2797da3`: 25 PASS, 7 FAIL, 7 UNPROVEN), and what the four wave-5 repair clusters
> (W5-K1 fabric: A6, C5 item 8; W5-K2 verdict scope: B2, the B8 heading; W5-K3 keyboard and focus:
> D1, D3, the D3 audit; W5-K4 E harness and cold load: the load meter, F4, E5), the merged-tree gate
> (four cross-cluster requests applied, four refused, three root-cause fixes of its own) and the
> orchestrator's dev-watch fix reported. **Every FIXED below was checked by the reconciler before it
> was written:** the code named was read at the line given at `78bdba5`, and the named tests were
> re-run in one invocation — 17 files, 229 tests, 229 passed, 0 skipped, exit 0 (JSON report in the
> orchestrating session's scratchpad), including `mock-classification.test.ts` (3 of 3) and
> `tracked-sources.test.ts` (6 of 6). The reconciler also confirmed from `git diff 2797da3 78bdba5`
> that no test file lost or changed an `expect(` line, no `.skip`/`.only`/`.todo` was added, and
> `review/capture-motion.mjs` is untouched. **Verified by the orchestrator at `78bdba5`:** `tsc`
> (app, scripts `--noImplicitAny`, config) all exit 0; `vitest` 147 files, 2235 tests, exit 0;
> `npm run build` exit 0; no capture-motion threshold changed; no `expect()` line removed and no
> skip/only/todo added across the wave's test changes. **Not re-run by the reconciler, and cited as
> "reported" wherever it appears:** every browser harness (`capture.mjs app`, `text`, `reduced` and
> `twice 5`; `capture-motion.mjs`; `audit-d3-focus.mjs`, default and `--sweep`; `layout-guard.mjs`;
> `probe-fabric.mjs --hairline`; `measure-inp.mjs`, `measure-fps.mjs`, `audit-e5-coldload.mjs`), the
> agents' in-page probes and performance traces (orchestrating session's scratchpad), and every wave-5
> mutation. A fixed defect does not by itself move its criterion; nothing here is a re-grade.
>
> **History since the wave-4 record** (it continues in the wave-6 banner above). `2797da3` (docs
> only: the wave-4 record and the re-grade of `70bea72`) → `78bdba5` (repair wave 5 and the dev-watch fix, 48 files). `2797da3` is an amend: its
> first version, `f70f060`, carried the Windows user name — one of the parent repository's
> client-marker patterns — inside a scratchpad path in `docs/acceptance-report.md`. It was amended
> before any other work, never left this machine (the repository has no remote), and every reachable
> commit was then re-scanned clean (orchestrator). The reconciler's read: `git reflog` still lists
> `f70f060`, and `git branch -a --contains` / `git tag --contains` name nothing, so it is on no ref but
> the object stays in this repository until that reflog entry expires or is pruned — a write the
> reconciler did not make. Since then every commit goes through a gated wrapper that refuses to commit
> unless the tree and the message scan clean against the parent repository's 12 client-marker
> patterns; the orchestrator proved it with a planted marker (exit 3, HEAD unchanged) — reported; the
> wrapper is not in this repository. `git status` was clean at `78bdba5` before this edit.

### R67. A6 — with a trace active, the fabric withheld a selected device's blast radius and left off-canvas stranded hosts unaccounted — FIXED (re-grade of `70bea72`, new item 1)
Found by the re-grade of `70bea72` (A6 overturned PASS → FAIL): `?d=core2&flow=…3389&hop=0` marked 5
of core2's 8 stranded hosts, with no count and nothing saying access3, access5 and access17 were out
of view; core1 marked 0 of 9 until a button was pressed. **Not a code regression** (W5-K1, reported):
no commit in `443a05a..2797da3` touched the A6 path, a `git archive` of `443a05a` reproduced the
refuter's figures exactly, and `git log -S selectionIsTraceHop` names `254694b`; the `443a05a` PASS was
graded without a trace.

**Fix, verified in code.** The store records who made a device selection: `store.ts:53`
`deviceOrigin` ("explicit" | "hop"); `selectDevice` defaults to explicit (`:122`) and a restored `d=`
hydrates as explicit (`:169`); only the shell's re-aim passes "hop" (`App.tsx:335`), and a new trace
landing on an already-selected host claims it (`:332`). `Fabric3D.tsx:932–937` `selectionIsTraceHop`
now requires `deviceOrigin === "hop"`, so a reader's own selection of the hop host draws its blast
radius at once. Whenever a blast radius is drawn the stage HUD says "<subject> strands N
(<certainty>) · all N marked" or "· K out of view: <hosts>" (`:1320–1341`, `data-stranded-total`,
`data-stranded-unseen`), read from what the label layer actually drew (`onStrandedUnseen`); label marks
are now written on hidden labels too (reported). The link grammar version is unchanged:
`encodeInvestigation` omits `d=` when the trace owns the selection (`store.ts:190–196`), so a `d=`
always means a device the reader chose, and `urlSync.ts:63` adds the origin to the navigation
signature — a trace landing no longer pushes a history entry that only added `d=` (a behaviour
change, tested). **Pinned by** `src/fabric3d/selection-origin.test.tsx` — 8 of 8 re-run green (explicit
by default; a restored `d=` explicit; every earlier link decodes as before; the re-aim's link without
`d=`; no history step for the next keystroke; a new trace claiming an already-selected host) — and
`Fabric3D.test.tsx`, 68 of 68, including "draws the blast radius at once when the reader EXPLICITLY
selects the trace's own hop host (A6)" and "accounts for EVERY stranded host on the fabric: marked, or
counted and named as out of view (A6)". K1 removed the `vi.mock` its first version of
`selection-origin.test.tsx` used, so F2's mock declaration did not change (reconciler's grep: no
`vi.mock` in the file; `mock-classification.test.ts` green). Reported: those tests red before the fix
(6 selection-origin cases on `expected undefined to be 'explicit'`); eight single mutations, each red
then restored; on a production build core2 "strands 8 … · 3 out of view: access17, access3, access5"
and core1 9 with no button press; the A6 pixel-diff rule holds (3.79–4.09 % against 0.76–0.84 %).
**Not done:** the camera is deliberately not reframed (A4 keeps it across a selection); trace and
stranded marks in the fabric tree's names (D6, optional in the brief) — O37. An interim HUD build gave
`capture.mjs text` 71 of 72 (dark/768/02, HUD controls wrapped into ~4-character columns) that did not
reproduce solo; the final CSS caps the HUD to the stage and wraps it, 72 of 72 (reported). A6 is not
re-graded here.

### R68. C5 item 8 — a 0.5 CSS px dashed hairline in the core2 → access9/access3 bundle — FIXED; the drawing object identified (re-grade of `70bea72`, new item 3)
Found by the re-grade (C5 FAIL on item 8 alone, both tiers and both themes; "drawing object not
identified"). **Identified by W5-K1 (reported):** hiding scene objects one at a time in a scratch
build, only the batch `cables:solid|2|1|2x3` — unobserved-speed bridges drawn as two 2 px rails with a
3 px gap — removed the stroke. Each LineMaterial quad also covers its rail gap and anti-alias margin,
and with `depthWrite: true` those zero- and partial-coverage fragments wrote depth, so a parallel
bridge drawn later and a hair farther away failed the depth test and was cut to a one-device-pixel
sliver; which of the two was nearer flipped segment by segment, so the sliver read as dashed. Clearing
only that batch's depth write brought the rails back. That is a different mechanism from R32's
light-theme width, which the re-grade had left open as possibly the same class.

**Fix, verified in code.** `createCableMaterial`, the only stroke constructor in the fabric, floors
every rail at `MIN_STROKE_PX = 2` (`cables.ts:361`, `:715`) and sets `depthWrite: false` with the depth
test kept (`:738`), so the opaque chassis still occlude strokes. The uncollected outline
(`scene.ts:1411`) and the trace tether (`flow.ts:350`) now ask for the floor (they were 1.4 and 1.5 px),
and the label leader lines went from 1 to 2 px (`Fabric3D.css:130`, `:142`). The gate brought
`design-brief.md` §4.4 into line ("a 2 px (`MIN_STROKE_PX`) wireframe outline"; verified in the
`78bdba5` diff). **Pinned by** `src/fabric3d/stroke-floor.test.ts` — 8 of 8 re-run green: it walks every
Line* material of the built scene in both themes and at every tier, plus the trace overlay, reads the
painted width from the compiled program, asserts no depth write, finds by source scan no other
stroke-material constructor, and checks every absolute px width in the brief's §4.4/§4.5 tables and
every pseudo-element line in the fabric's stylesheets against the floor. Reported: 4 of 7 red before the
fix ("dark/high/uncollected-edges paints 1.40 CSS px"; the factory "expected 0.50001 to be ≥
1.999999"), the §4.4 case red on "1.4 px" until the brief was edited, and each half of the fix removed
turns it red. Reported: `node review/probe-fabric.mjs --hairline` (a new mode: a DSF-2 detector for
chains of one-device-pixel ink, gaps allowed) found 3 chains in each theme/tier leg before and 0 on the
dev server and on a production build after; `capture-motion` passed all six motion items on K1's build
and on the gate's final build. **Out of the class by definition:** UI-chrome hairlines (chip borders,
hover and selection outlines; design-brief §3) and the world-unit state-ring meshes. Discarding only the
zero-coverage fragments was tried and rejected: a dashed seam remained. C5 is not re-graded here; O16's
owner decisions stand.

### R69. B2 — the palette, the path presets, the trace announcement and the timeline stated a forwarding verdict without its scope or caveats — FIXED, with a type-checker guard for the class (re-grade of `70bea72`, new item 2)
Found by the re-grade (B2 FAIL): the palette rendered "trace a path — this one ends denied" and "…which
is the blocking-hop answer with its exact configuration line" for a denial whose own trace says it is
not decided. W5-K2's new guard found 8 offenders on the unfixed tree (reported): the outcome tally and
preset word tables in `PathTrace.tsx`, and the announcement, the grammar example and the suggestion
rows in `commands.ts`.

**Fix, verified in code.** `ClaimCard.tsx:152` `verdictStatement(trace)` is the one sentence-builder:
the word from the claims owner (the undecided word included), the band, the badge, the scope clause
read from the trace's own claim (`engine.ts:1677` `scopeClauseOf`) and the trace's caveat count. The
announcement (`commands.ts:341`), the grammar example (`:415`), the palette rows (`:759`), every Path
preset (`PathTrace.tsx:902`) and — applied by the gate on K2's request — the `#sr-log` timeline
(`App.tsx:281`) all use it. Reported rendered row: "10.0.10.50 → 10.0.30.10:3389 TCP — denied by list
text — not decided: … Under the collected RIBs of core1 and core2 only (2 of 26 hosts in this topology) ·
PARTIAL · 13 caveats on its card. …". The suggestion rationales in `buildSuggestions` name the question
and state no outcome; the only "blocking-hop answer" strings left under `src/` are comments and tests
that describe or forbid it (reconciler's grep). A verdict detail is drawn unclamped in the palette
(`CommandPalette.tsx:77`), so a verdict is not cut between its word and its scope. **Pinned by**
`src/forwarding/verdict-wording.guard.test.ts` — 3 of 3 re-run green: the type checker finds any
`TraceOutcome` value turned into text outside the owners (`engine.ts`, `claims.ts`, `ClaimCard.tsx`) and
any second outcome→word table; a planted module is flagged on exactly lines 3, 4, 5, 6, 8 and 13; and
its self-expiring `PENDING_OUTSIDE_OWNER` ledger is empty (`:174`) since the gate's `App.tsx` edit — and
`src/app/verdict-scope.b2.test.tsx` — 8 of 8 re-run green: every suggested flow on every surface
carries the scope clause and caveat count, the undecided word, no "blocking-hop answer", and no verdict
word in a title or rationale. Reported: 6 of 8 red before the fix; the old rationale restored, 4 red;
the command strings restored and the preset bounds removed, 5 red; the ledger entry deleted before the
`App.tsx` edit, red on `app/App.tsx:280`; `capture.mjs text` 72 of 72 after the unclamp. **Stated
scope limits, open (owner: the guard's):** per-hop `HopVerdict` words (HopList, the 3-D chips) and
strings built with `Array.join` over outcome values are outside the guard. The O33 guards and
`COUNTEREXAMPLE_CANDIDATE_CAP` (`engine.ts:2770`, 48) are unchanged. B2 is not re-graded here.

### R70. B8 observation — "Nearby flow with a different outcome" headed a card whose body said none was offered — FIXED (re-grade of `70bea72`, new item 10)
**Fix (W5-K2), verified in code.** When the bounded search offers nothing, the heading says so:
"Counterexample — none offered by the bounded search", or, for an undecided result, "Nearby flow with a
different outcome — none offered; relative to an UNDECIDED result, one would not be a counterexample"
(`ClaimCard.tsx:392–393`); the existing "relative to an UNDECIDED result" assertion is kept. **Pinned
by** `src/panels/ClaimCard.honesty.test.tsx` "every card whose search offered nothing says so in its
heading" — 6 of 6 in the file re-run green. Reported: red before (1 of 6) and with the `!result.found`
branch disabled. B8 itself stays UNPROVEN (O13).

### R71. D1 — the Path surface's Queue/Evidence switch had no tab stop at 768–1023 px, and its unchecked pane no arrow keys in any state — FIXED, with a census of every composite widget (re-grade of `70bea72`, new item 4)
Found by the re-grade (D1 overturned PASS → FAIL): at 768 on `?s=path` both radios were
`tabindex="-1"`; "paneswitch focused during 60 Tabs: 0". **Not a code regression** (W5-K3, reported):
`git diff 443a05a 70bea72 -- src/app/surfaces.tsx` is empty, the roving rule and the omission of `path`
date from `50a3dc5`, and the `443a05a` PASS came from a grading that never visited Path-with-no-flow at
768 or 1000. PaneSwitch had no arrow-key handler at all, so at 768–1023 px the unchecked pane was
keyboard-unreachable in every state.

**Fix, verified in code.** `surfaces.tsx:750` `rovingStop(ids, value)` returns the checked item, else
the first; PaneSwitch offers Path while it is the shown pane (`:779`, `pathAvailable || value ===
"path"`) and takes its stop from `rovingStop` (`:783`), as RailB's radios now do (`:480`); APG arrow keys
(Right/Down, Left/Up, Home/End) select and move focus (`:757`). **Pinned by**
`src/app/composite-tabstop.test.tsx` — 74 of 74 re-run green, with no module mocks (reconciler's grep):
the real App at 390, 768, 1000, 1100, 1440 and 1920 in 10 states, where every rendered element with a
composite role holds exactly one tab stop (zero when a combobox drives it by `aria-activedescendant`)
and every radiogroup, tablist and toolbar item is reachable by arrow keys. Reported: 17 red on
`2797da3`'s `surfaces.tsx`; the new `audit-d3-focus.mjs --sweep` (R73) red on the old build, and "175
composite widget(s) counted, 1556 tab stop(s) walked, 1871 nine-point hit test(s) … 0 failure(s)" with
More → Path "pane switch focused during 60 Tabs: 2" on the fixed one. D1 is not re-graded here.

### R72. D3 — at narrow widths the side rail painted over the focused status-bar buttons, and Tab put body controls under the sticky bar — FIXED (re-grade of `70bea72`, new item 5); a grid cell wholly under the bar at 390, reached through a popover's close, failed D3 at `34bd435` and was fixed in wave 8 (R105)
Found by the re-grade (D3 FAIL): at 390x844 `?d=core1&s=fabric`, Tab to "23/26 collected" at
y=10537, `elementFromPoint` gave `LI.dp-list__row` at 9 of 9 points, 0 of 4,400 ring pixels. **Cause,
measured by W5-K3 (reported):** the drawer rung's `.rail--b { z-index: var(--z-overlay) }` (30) was
never reset at the narrower rungs, and a flex item's z-index makes a stacking context even while
`position: static` — above the sticky status bar's 5. The same sweep found a second member of the class
(WCAG 2.4.11): at 390 Tab left body controls under the sticky bar ("Open source record
collection_completeness / coverage_matrix" 0 of 9 points; presets and a grid cell 3 or 6 of 9), because
the bar wraps to 85 px, not the 26 px token.

**Fix, verified in code.** `shell.css:624` `.rail--b { z-index: auto }` at ≤63.9375rem; `shell.css:680`
`scroll-padding-block-end: calc(var(--statusbar-block, var(--statusbar-h)) + var(--sp-2))` at
≤47.9375rem, with `StatusBar.tsx:210` publishing the bar's live, wrapped height as `--statusbar-block`
through a ResizeObserver. **Pinned (the z-index half) by** `src/core/sticky-layer.test.ts` — 11 of 11
re-run green, including "no region, and nothing scoped under one, can resolve to a layer at or above
the status bar" and "the detector flags the measured defect: an overlay z-index leaking from a wider
rung"; regions come from the TSX, widths from every media bound ±1 px, and the cascade is resolved
through `var(--z-*)` tokens. Reported: 13 violations on `2797da3`'s `shell.css`. **The scroll-padding
half has no unit pin:** the reconciler's grep finds no test naming `--statusbar-block` or
`scroll-padding-block-end`. Its evidence is the reported sweep — 58 failures on the old build, 0 on the
fixed one, 14 with only the published height removed. D3 is not re-graded here.

### R73. D3 harness — `audit-d3-focus.mjs` reported "0 not visible" over a covered ring and never counted composite tab stops — FIXED in the harness (re-grade of `70bea72`, new item 5)
The old audit drove 1920, 1440 and 1000 only, hit-tested each stop's centre and never scrolled, so it
could observe neither the 390 case nor D1. It now (reported; `review/*.mjs` is outside the unit suite,
O27) hit-tests a 3×3 grid inset 15 % into the visible box; runs a `--sweep` that walks the whole tab
order with real Tab presses at 390, 768, 1000, 1440 and 1920, judges each stop where Tab left the page
and every stop in a sticky or fixed layer at nine scroll offsets, counts each composite widget's stops
and arrow reach, and prints `SWEEP NEVER EXERCISED` when a denominator is zero; adds 768 and 390 to the
default surface passes; and counts the Inspector as open only when `getClientRects().length > 0` —
which exposed R74. `layout-guard.mjs` gained a 768x1024 row (verified in the diff; O17). Reported, the
gate's run on its final build: sweep 175 widgets, 1556 tab stops, 1871 hit tests, 0 failures; 547 cases,
0 failed; 1089 focus stops, 0 not visible; exit 0 — and exit 1 before R74–R76. Not re-run by the
reconciler.

### R74. Below 768 px the Inspector opened inside the hidden stage and was never shown — FIXED by the gate (found by the tightened D3 audit)
Found by W5-K3 (`--vp=390`: "phone/inspector (i) :: enter the state -> NOT DRIVEN", and the same from a
citation) and fixed by the merged-tree gate. The Inspector is docked in `#stage`, and `shell.css` hides
the stage below 768 px while the fabric is collapsed (the default), so `i` and Enter on any evidence
citation opened an Inspector that was in the DOM with no box, focus left on the invoker (reported:
`{inspRects:0, stageDisplay:'none'}` at 390x844; 6 of 6 narrow cases not shown). It predates the wave;
the old audit counted it as open. A phone reader could not see the record any citation named. **Fix,
verified in code:** `shell.css:733–744` (≤47.9375rem) shows the stage while it holds the Inspector
and, with the fabric off, hides every stage child except `#inspector`. **Pinned by**
`src/app/stage-inspector-narrow.test.ts` — 3 of 3 re-run green, derived from every width-conditioned
rule that hides the stage, with a positive control. Reported: red first; then 8 of 8 narrow cases shown
with focus in the tablist. K3's alternative, a bottom sheet per the brief, was not taken up; this is the
in-place fix.

### R75. At phone width, closing the Inspector dropped focus to `<body>` — FIXED by the gate
Surfaced once R74 made the Inspector visible there (reported: "close button → Enter -> BODY", "tab →
ArrowRight → Escape -> BODY"). The invoker citation had re-rendered, and the only fallback, `#stage`, is
hidden again once the Inspector closes. **Fix, verified in code:** `focus-return.ts` `ReturnRecord`
carries `region` (`:64`), the landmark captured by `recordReturn` while the invoker still exists
(`:114`); after the target, the opener, the fallbacks and the context landmark, `returnFocus` tries that
region's first focusable heading, then the region itself (`:172–175`) — the heading first because a
ring round the whole rail-clipped region measured not visible. **Pinned by**
`src/app/focus-return.region.test.ts` — 5 of 5 re-run green (a positive control; the region when the
invoker and every fallback are gone; its heading first; a stated fallback still preferred; a removed
region not used). Reported: red first; the audit then lands on H2 "Evidence" with 1,559 px at ≥3:1.

### R76. Below 768 px the queue's View fold followed page scroll — FIXED by the gate
Surfaced by the same audit ("phone/inspector (i) popover "Display" :: NOT DRIVEN"). `restingRowsInView`,
the fold's geometry key and its observers treated `<body>` as the queue's clipping port, but below
768 px body's overflow belongs to the viewport, so the count moved with page scroll and Group, Order and
Display folded behind "View" part-way through a session — contrary to the function's own contract that
its answer does not change as the reader scrolls. **Fix, verified in code:** one `clipsRows()`
predicate (`PriorityQueue.tsx:625`) serves all three walks (`:653`, `:835`, `:904`) and excludes the
document scroller when its overflow is auto or scroll; a fixed frame's `overflow: hidden` body at
≥768 px still counts, so O24's layout-guard invariant 2c still holds (the gate's run, reported). **Pinned
by** `src/panels/PriorityQueue.fold-port.test.ts` — 2 of 2 re-run green. Reported: red first ("expected
3 to be 146"). The change does not move the fold decision's timing (O35).

### R77. The fabric tree could be left with no tab stop when its active key named no rendered row — FIXED by the gate
Reported by W5-K3 as a code-reading lead, not proven (`rovingKey = activeKey ?? visibleRows[0]?.key`);
proven and fixed by the gate. **Fix, verified in code:** `FabricA11yTree.tsx:444` keeps the active key
only when it names a rendered row, else takes the first row. **Pinned by**
`src/fabric3d/FabricA11yTree.tabstop.test.tsx` — 2 of 2 re-run green ("still has one when the active
row leaves the rendered rows (the model changed under it)"). Reported: 0 tab stops before ("expected []
to have a length of 1").

### R78. E2/E3 harness — the load meter booked the harness's own closed browsers as outside load — FIXED in the harness, as a class (re-grade of `70bea72`, new item 7)
Found by the re-grade (E3 UNPROVEN): `measure-inp.mjs` sampled its meter only at `:1556`, so the CPU of
every browser closed before then left with the process; an independent sidecar measured Playwright
Chromium at 7.2 % where the harness reported 1 %. W5-K4's source guard then found 10 unmetered close
sites across four harnesses, plus `headedWindow`'s own probe browser (reported). **Fix, verified in
code:** `review/host-env.mjs` puts the harness process in a Windows job object at `start()` (`:264`,
`:292–303`, `:333`), whose accounting keeps the CPU of processes that have exited; `finish()` reads it
and subtracts its own probe; the process-tree sampler remains as a fallback with the method recorded
(`harnessMethod`); every close in a metered harness goes through `meter.close` or `closeMeasured`
(`:445`). **Pinned by** `src/core/host-load-meter.test.ts` — 5 of 5 re-run green: it imports
`host-env.mjs` and books to the harness a child that burns ~2.5 s of CPU and exits between `start()`
and `finish()`; reads the method as "job" on Windows; and, over the `review/` directory with a
non-empty-scan precondition, forbids a bare `.close(` in any harness that calls `createLoadMeter`.
Reported: both behavioural tests red with the job disabled; a bare `browser.close()` put back in
`measure-fps.mjs` red; a lab run at 63 % busy (not evidence) read the harness at 8.3 % from its job
against a sidecar lower bound of 7.8 %, where it used to read 0–1 %. **This does not make E2 or E3
PASS:** it books the harness's ~8 % as harness instead of as excess. The 25 % bar is unchanged, and
quiet, on-AC runs are still needed (O25).

### R79. F4 — the criterion claimed more than the build does, and no test checked the build output — FIXED in the documents and a build-output test (re-grade of `70bea72`, new item 8); F4 failed at `34bd435` at fractional widths this test does not reach, fixed in wave 8 (R103)
Found by the re-grade (F4 overturned PASS → UNPROVEN): at ≥768 px three.js is fetched on every load,
which "the initial payload does not carry it" does not allow. **Decision** (the orchestrator, on the
owner's delegated authority): at 768 px and wider the 3-D stage is the main view, so three.js is fetched
on every load, after first paint; below 768 px the stage starts collapsed and three.js is never fetched
unless the reader opens the 3-D fabric. `acceptance.md` F4 now says so in three measurable parts — (a)
no three.js module in the entry chunk, and the entry names no chunk that carries one; (b) no
`index.html` modulepreload names or imports one; (c) requested only after first paint at ≥768 px, and
never by a load below 768 px before the reader opens the fabric (verified in `78bdba5`). The
`vite.config.ts` comment's overstatement is corrected (verified in the diff). A K4 continuation found and
corrected its own first draft, which said "never fetched" below 768 px without qualification although
"Show the 3-D fabric" fetches it by design (reported: at 767 px, `[]` before the toggle,
`three-Dyx6ntnn.js` after). **Pinned by** `src/core/acceptance-gates.test.ts` "F4: three.js is absent
from the entry chunk and from every modulepreload (build output)" — re-run green, 14 of 14 in the file:
it builds this checkout in a child process with the project's own config and checks the entry chunks,
their static closure and every modulepreload, with a positive control that some chunk does carry
three.js; its preload parse is attribute-order independent (`:234–236`; K4's first version silently
skipped a `href`-before-`rel` link). Reported: a `WebGLRenderer` import added to `main.tsx` turns it red.
**(c) is reported, never judged:** `audit-e5-coldload.mjs` prints `threeRequest` against first paint at
1920 and a new `f4NarrowLoad` cold load at 767 px, run after the E5 verdict is fixed (`:399–403`);
reported runs read "after first paint" and "three.js never requested", and the probe width mutated to
1920 printed "REQUESTED". F4 is not re-graded here.

### R80. The "host busy" refusals of E2–E5 — the dev server was watching ~8,000 regenerated review files — ROOT CAUSE FOUND and FIXED (orchestrator, 2026-09-24)
The last three gradings withheld their E runs as NOT ACCEPTANCE EVIDENCE on host load against a 25 %
bar: the re-grade of `443a05a` at 46–59 %, the wave-4 gate at `8e873d2` at 36–47 %, and the wave-5
gate at 31–35 % with an idle baseline of 28–34 %, which named the :4180 dev server, at a steady
1.56 cores, as the main consumer (O25). **Found by the orchestrator (reported):** after about 16 h of
uptime the :4180 Vite dev server idled at 1.51 CPU cores with no client, no child process and nothing in
its log; restarted, it idled at 0.01. **Cause, verified in code:** Vite 8.2.1's default watch-ignore
list (`node_modules/vite/dist/node/chunks/node.js:13726` `resolveChokidarOptions`; version read from
`node_modules/vite/package.json`) is `.git`, `node_modules`, `test-results`, the cache directory and,
when emptied, the outDirs — so everything else under the root was watched: `review/shots` alone holds
7,997 files (reconciler's count), rewritten by every capture run, plus the agents' `.audit/` and
`.probe/` scratch. **Fix, verified in code:** `vite.config.ts` `server.watch.ignored: ["**/review/**",
"**/.audit/**", "**/.probe/**", "**/shots/**"]`. **Pinned by** `src/core/dev-watch.test.ts` — 3 of 3
re-run green: every generated-output directory is excluded, and no relative import in `src/` or the
HTML pages resolves under an ignored directory (a non-empty scan, with a live planted case), so an edit
to real source still reloads. By reading the test, a config without `watch.ignored` (the tree before the
fix) or without `**/review/**` fails its first case; the orchestrator reports both reds, and the
reconciler did not run the mutation. **After the restart with the new config (orchestrator,
reported):** the dev server used 0 cores over 10 s, host CPU 2 %, on AC at 100 %. The reconciler's own
read at 07:35 +0300: the :4180 listener used 0.000 cores over 10 s, on AC at 100 % charge — but that
process started at 07:25:16, before `vite.config.ts`'s last write at 07:27:23, and whether it runs the
committed ignore list (Vite restarts in-process on a config change) was not established by the
reconciler. **Settled at `8eac055`:** the host booted at 14:17:59 +0300 on 2026-09-24, and the :4180
listener the wave-6 reconciler read started at 2026-09-25 07:22:35, after that last write, so it runs
the committed ignore list; it read 0.000 cores over 10 s, on AC at 99 % (wave-6 banner). **Status:** FIXED, as the cause of the host-load problem the last three gradings reported.
It re-establishes nothing by itself: no E run has been made on the quiet host since (O25, O35).

> **Repair wave 4 (reconciled 2026-09-23, committed as `8e873d2` and `70bea72`).** Entries R54–R66
> and the moved O24 below, the status notes added to R44, R49, O10, O12, O15 and O18, and the
> rewritten O9, O12–O14, O16, O17, O19–O23 and O25–O28 plus the new O29–O34 under Open, and notes on
> R39 and R51, record two things
> that had not been written here: the "new" items 1–13 and the status changes of the independent
> re-grade of `443a05a` (`docs/acceptance-report.md`, committed beside the wave-3 record in
> `1c829c9`), and what the five wave-4 repair clusters (W4-R1 citations and nulls: B6, B1; W4-R2
> journey scope and test hygiene: E1, the E harness, F2–F4; W4-R3 queue: A4, D3, O24; W4-R4 motion:
> C5, C6; W4-R5 forwarding: the B5-adjacent caveat, B4, the engine tripwire, the stale-card lead),
> the merged-tree gate and the C5 tier-pin commit reported. **Every FIXED below was checked by the
> reconciler before it was written:** the code named was read at the line given, and the named tests
> were re-run at `70bea72` in one invocation (32 files, `976` tests, 976 passed, 0 failed, exit 0,
> with the zero-assertion guard live), plus `src/app/self-removing-focus.test.tsx` and
> `src/fabric3d/stepdown.test.ts` in a second (2 files, 26 tests, exit 0, 152 s).
> `src/core/tracked-sources.test.ts` is green (6 of 6): `src/core/route-fields.ts`, the one file the
> gate left red, is tracked in `8e873d2`. Against `vite preview` of a scratch `vite build` of
> `70bea72` (its own out-dir, port 4287, stopped afterwards) the reconciler also re-ran
> `node review/layout-guard.mjs`: `layout-guard: all five invariants hold at every viewport.`, exit 0
> (O24). `sha256sum src/data/fabric.json` is `a1a599b8…d251` (R54). **Verified by the orchestrator
> at `70bea72`:** `tsc` (app, scripts `--noImplicitAny`, config) all exit 0; `vitest` 136 files,
> 2106 tests, exit 0; `npm run build` exit 0; the content and message marker scans clean; no
> capture-motion threshold changed (consistent with the reconciler's
> `git diff 443a05a 70bea72 -- review/capture-motion.mjs`, which changes no threshold-constant line).
> **Not re-run by the reconciler, and cited as "reported" wherever it appears:** `capture.mjs app`,
> `text`, `reduced` and `twice 5`; `capture-motion.mjs` (the agents' runs, the gate's at `8e873d2`
> and the independent verifier's at `70bea72`); `measure-inp.mjs`, `measure-fps.mjs` and the E5
> harnesses; both `audit-d3-focus.mjs` passes; `mutation-check.mjs`; the agents' browser probes and
> screenshots (orchestrating session's scratchpad); and every wave-4 mutation. A fixed defect does
> not by itself move its criterion; nothing here is a re-grade.
>
> **History since the wave-3 record** (it continues in the wave-5 banner above). `1c829c9` (docs only: the wave-3 record and the re-grade of
> `443a05a`) → `2d9712c` (checkpoint of an interrupted wave-4 run: the session process ended about
> 13 minutes in, before any of the five agents returned; their partial edits were committed as they
> stood so that the restarted agents could verify them rather than assume them, `tsc` red at that
> commit on an unused import mid-edit — its message — and a scratch probe the interrupted agent
> left, `engine.zz-probe-tmp.test.ts`, was deleted, not committed) → `8e873d2` (repair wave 4, 53
> files) → `70bea72` (the C5 tier pin, 5 files; R60 (d)). `git status` was clean at `70bea72`
> before this edit.

### R54. B6 — the link inspector's centrality figures had no citation, and 2,064 device and link rows cited nothing — FIXED (re-grade of `443a05a`, new item 3)
Found by the re-grade of `443a05a` (B6 overturned PASS → FAIL): `?l=L7` showed "Cutting it partitions
yes / Betweenness 22.0000 / Pairs cut 22 / Centrality rank 4" with no cite control,
`grep -c link_centrality src/data/fabric.json` gave 0, and the pane's only reference,
`cable_map.cables[7]`, holds none of those fields. The refuter did not check other rows; W4-R1's class
walk did, and on the unfixed tree reported 2,064 rows with no citation and no declared derivation
(Host, Model, Serial, Software, Score, Criticality …).

**Fix, verified in code.** `tools/compile-snapshot.mjs` compiles the source records the figures are
read from under the paths their citations name — `link_centrality[k]` (`:232–245`),
`health_scores[switch=…]` (`:218–226`) and `cable_map.nodes[host=…]` — appended at the end of
`fabric.json`, so earlier model paths are unchanged; each link carries `centralityCite` (`:289`) and
each device `fieldCites` (`:197`), naming the record each compiled field was READ from.
`DevicePane.tsx:1943–1947` cites `link.centralityCite` on all four rows, and every Device-pane
key/value row is typed `EvidenceRow` (cite | derived) (reported). `sha256sum src/data/fabric.json` is
`a1a599b8…d251` (reconciler); the source digest `9580aa09…3089` is unchanged, and the gate moved
`acceptance.md` F5's fabric digest (verified: `:200` names `a1a599b8…d251` at the 2026-09-23 recompile
and keeps `2f558c38…a308` as the 2026-09-22 value). **Pinned by** `src/panels/DevicePane.cite.test.tsx`
— 6 of 6 re-run green, including "walks every device and every link, and every row it finds is cited
or declares its derivation" (no list of labels) and "a health figure cites the health_scores record,
not the inventory record that holds no score". Reported: two mutations (the four cites replaced by a
derived label; `link_centrality` removed from the compiler output), each 2 red then restored;
recompiling twice is byte-identical. **Observation, not verified as a defect:** a link with no
centrality row (`centralityCite` null) falls back to `link.cite` on those four rows, whose values then
read "not observed". O9 (the raw source record) is unchanged. B6 is not re-graded here.

### R55. B1 — one null administrative distance read three ways across four surfaces — FIXED, with one owner the engine shares and a type-checker guard for the class (re-grade new item 2; closes R44's residual)
Found by the re-grade of `443a05a` (B1 overturned PASS → FAIL): `routes.core1[6]`
(`"adminDistance":null`) read "0 — a connected route's administrative distance by definition…" on the
Path panel and "administrative distance: / not observed" on the Device pane's Routing tab. W4-R1's
type-checker guard then found two readers the grading had not: the evidence pane's route row
(`EvidencePane.tsx:654/660`, "not observed" for a connected route's null next hop and AD — a fourth
surface) and the engine's `adminDistanceOf`, a second, case-sensitive owner of the null-ranks-as-0
rule that also printed that convention's 0 into the tie-break caveat as though the record carried it.

**Fix, verified in code.** `src/core/route-fields.ts` (new, tracked in `8e873d2`) is the one owner —
`routeFieldReading` (`:77`), `adminDistanceRank`, `isRouteRecord` — and imports types only;
`claims.ts:692` re-exports it. The owner cannot live in `claims.ts`: `claims.ts` imports the engine and
evaluates an engine binding at load, so an engine importing it back hits a TDZ (reported seen live
during a mutation: "Cannot access 'NOT_OBSERVED_TEXT' before initialization"). Every surface renders
the one `HopList.tsx:426` `RouteFieldValue`: the hop list, `DevicePane.tsx:1545–1546`,
`Inspector.tsx:305` and `EvidencePane.tsx:655`/`:661` (the last applied by the gate). `engine.ts:1597`
is `const adminDistanceOf = adminDistanceRank;`, and the caveat at `:1622` prints
`routeFieldReading(winner, "adminDistance").text`. **Decision changed** (recorded in the owner's
header): "0 — … by definition" put a digit in the value slot of a record that carries none; a
connected or local route's null AD now reads "not recorded — the record carries no value; a connected
route's administrative distance is zero by platform convention, so nothing collectable is missing",
and its null next hop "n/a — a connected route has no next hop". **Pinned by**
`src/panels/HopList.admin-distance.test.tsx` — 11 of 11 re-run green: `routes.core1[6]` "identical on
all three surfaces, and never a bare 0"; every route record on every Routing tab against the
Inspector; and the guard — "finds no read of RouteEntry.adminDistance outside the owner", "finds no
render module (.tsx) reading RouteEntry.nextHop outside the owner", "the owner is a module the
forwarding engine can import: its runtime imports never reach the engine", and a planted self-test
(the owner is resolved by the type checker, never a hard-coded path). `claims.test.ts` (41) and
`Inspector.test.tsx` (50) re-run green. Reported: 2 failed / 9 passed before the gate's EvidencePane
and engine edits, 11/11 after; mutations of the Device-pane AD column (3 red) and of the owner's text
(5 red). **Stated residuals:** a function returning the owner-free number can launder the value (the
limit `band-read.guard` has); the nextHop half covers `.tsx` render modules only, so a `.ts`
formatter would escape it; the Inspector's dynamic field walk is covered by DOM tests, not the guard.

**The re-grade's cosmetic lead** ("No routing table was collected for AP-floor1 2 of 26 hosts have
one") was not reproduced in the Device pane, whose text keeps its punctuation (reported). The
run-together text was `NotObserved`'s accessible text ("not observedno RIB was collected…"): the gate
added a visually-hidden " — " before the reason (`primitives.tsx:124`, non-compact form). **Pinned
by** `src/ui/primitives.test.tsx` "separates the words from the visible reason in the accessible text,
not only by layout" — 38 of 38 re-run green. B1 is not re-graded here.

### R56. A4 — clicking the visible copy of a finding listed under two groups threw the queue to its first copy — FIXED (re-grade new item 1)
Found by the re-grade of `443a05a` (A4 FAIL): under GROUP "Device health band", F144 is row 92 (Poor)
and row 167 (Critical); clicking row 167 at scrollTop 7879 jumped to 4655 with focus on row 92. The
grading ran band grouping only. The interrupted run's edit in `2d9712c` was checked by W4-R3 rather
than assumed: with `DataGrid.tsx` and `PriorityQueue.tsx` put back to `443a05a`, 9 of 18 a4-scroll
cases failed under band, host and role grouping (e.g. "scrollTop 3795 -> 94") (reported).

**Fix, verified in code.** A row's identity in the grid is its per-group copy key
(`DataGrid.tsx:578` `rowKeyOf`: roving cell, reveal, hold, activated copy); a re-aim from another
surface prefers a copy already on screen, and the queue opens a collapsed group only when every group
holding the row is collapsed (reported). **Pinned by** `src/panels/PriorityQueue.a4-scroll.test.tsx` —
18 of 18 re-run green, 9 of them the duplicate-row cases; `PriorityQueue.test.tsx` (37),
`PriorityQueue.reveal-hold.test.tsx` (6) and `PriorityQueue.folded-columns.test.tsx` (5) also green.
Reported browser figure (private production build, 1920x1080, band grouping): clicking F144 at row 167
kept scrollTop 7879 → 7879, with focus and `aria-current` on row 167. R39 (the no-finding path) is
unaffected. A4 is not re-graded here.

### R57. D3 — a control that removes itself dropped focus to `<body>` — FIXED through one owner, with a class test that presses every tab stop (re-grade new item 4)
Found by the re-grade of `443a05a` (D3 overturned PASS → FAIL): "Remove the Critical/High severity
filter", "Clear scope", "Deselect device core1" and "Stop investigating the flow …" each left
`document.activeElement` on `<body>`, no ring anywhere. W4-R3 wrote the class test first:
`src/app/self-removing-focus.test.tsx` mounts App with one of every kind of scope token and presses
every tab stop (103) with Enter and, separately, Space; on the unfixed tree it reported 27 failures per
key — the grading's five plus Remove access role, Stop restricting, Deselect finding/link, the queue's
own chips and its empty-state "Clear the filter text".

**Fix, verified in code.** `src/app/focus-return.ts:241` `handOffFocus(control, action, stated)` plans
a successor structurally before the action runs (the next surviving stop in the control's labelled
set, else the previous, else the caller's stated successors, else the set's label, else the region
landmark) and acts only if focus was actually lost. Callers: the Chip primitive's remove control
(`primitives.tsx:324`, optional `removeSuccessor`), Clear scope (`App.tsx:178`), the URL-notice
Dismiss (`App.tsx:492`) and the queue's empty-state reset (`PriorityQueue.tsx:2085`). The new pass
found two more at 390x844, both fixed (reported): "Skip to the fabric" targeted a `display:none`
`#stage` (it now falls back to the first control of the body through `returnFocus`), and
`.qbar__tokens` let "Clear scope" paint over the handed-to chip (now `flex: none`; the bar scrolls).
**Pinned by** `src/app/self-removing-focus.test.tsx` — 2 of 2 re-run green (Enter and Space; per-test
timeout 1,200,000 ms, `:306`). Reported browser evidence, not re-run by the reconciler:
`node review/audit-d3-focus.mjs --self-removing` (new mode; real Tab presses at 1440, 768 and 390, one
page per width and key) — 94 failures on a build with the hand-off disabled, and `154
self-removing/BODY case(s), 0 failed … 0 not visible`, exit 0, on the fixed build (29 min 47 s); the
default pass `332 case(s), 0 failed … 666 focus stop(s) … 0 not visible`, exit 0 (21 min 33 s).
**Runtime note for graders (W4-R3):** run `--self-removing` on its own against a private
`vite preview`, not inside the default pass; the jsdom class test takes 6–11 min on a loaded host.
**Not stated as covered:** self-removing controls inside an open Inspector or evidence pane (an area
the re-grade left unchecked). D3 is not re-graded here.

### O24. The findings queue's chrome starved its rows whenever the path panel shared rail A — FIXED in wave 4 by a fold decided from measured space (moved from Open, 2026-09-23)
**Original entry (wave 3).** Found by the R2 cluster at session start and re-found by the merged-tree
gate; verified by the reconciler's `layout-guard.mjs` run on the `443a05a` build ("1280x800 / with
trace: only 2 of 146 finding rows are hit-testable (need >= 4). Clicks land on BUTTON.sb__cov
instead."; 4 of 146 at 1440x900). Pre-existing at `d3e2a1c`. Cause, measured by the gate: at the
280 px rail the queue's chrome above its grid was 330 px (corpus switch 64, query 34,
Group/Order/Display 145, count/scope lines 70). The wave-3 gate refused the proposed fold as the
queue owner's design decision.

**Fix (W4-R3), verified in code.** `PriorityQueue.tsx:613` `MIN_UNFOLDED_ROWS = 6`: when fewer than
six finding rows are in view at rest, Group, Order and Display fold behind one "View" disclosure
beside the filter field (`:859`), decided from measured space (the data rows whose laid-out centres
fall in the grid's port, clipped by every clipping ancestor), not from a width, and kept only while it
actually adds rows: at 1440 and 1920 with a trace folding showed the same 4 rows, because the path
track absorbs the freed space, so it is undone there (reported). Group/Order state and the Display
popover stay mounted. `layout-guard.mjs` gained invariant 2c: the disclosure must be a labelled,
described tab stop with `aria-expanded=false` and `aria-controls` naming the hidden block, and Enter
must show every control it hid. **Verified by the reconciler's layout-guard run** on a scratch build
of `70bea72` (:4287): "1280x800 / with trace: view controls folded under "View" (3 controls,
disclosure tab-reachable)", "1280x800 / with trace: doc 800/800, 4/146 rows hit-testable, path panel
present", 1440x900 with trace 4/146, and "layout-guard: all five invariants hold at every viewport.",
exit 0. There is no unit test of the fold; the guard is the evidence. Reported: with
`MIN_UNFOLDED_ROWS = 0` the guard returns the original violation (2 of 146); a keyboard probe (Tab
reaches View, Enter expands, the next Tab lands on Group, Space closes); D2 in the browser
`role:grid, tabStops:1` folded and unfolded. **Stated limits:** 4 rows at 1440x900 and 1280x800 with a
trace is exactly the invariant's floor, and at 1440x900 on `?s=path` the rows still start below rail
A's fold (R46); the fold was verified in headless Playwright, not in the Browser pane, whose hidden
tab fires no ResizeObserver callbacks (W4-R3).

### R58. B5-adjacent — the not-applied-list caveat said a TCP-only line "matches" a udp or icmp flow — FIXED (re-grade new item 5)
Found by the re-grade of `443a05a` (B5 upheld, with this adjacent defect): the caveat matched candidate
lines by address only, 50 of 3,968 traces. The interrupted run's fix in `2d9712c` was checked by W4-R5
and kept. **Fix, verified in code.** `notAppliedCaveat` (`engine.ts:867`) asks every candidate line of
the engine's one matcher, `matchTri`: "matches" for yes, "could match" for maybe, excluded lines
omitted, and a list whose every addressed line is excluded is described with its first exclusion and
its implicit deny. The audit covers every sentence form that says a cited line (could) match a flow —
the not-applied and catch-all parentheticals, an applied list's undecidable-line caveat, not-applied
undecidable-line hop evidence and suggested-flow rationales — and every protocol in `FLOW_PROTOCOLS`
(the old coverage assertion was tautological). **Pinned by**
`src/forwarding/engine.not-applied-caveat.test.ts` — 6 of 6 re-run green. Reported: with the fix
removed, 5 of 6 red ("3269 traces; protocol-excluded "matches" citations: expected 78 to be +0").
**Latent, not proven:** the guard W4-R5 added to `buildSuggestions` survives its own removal (O33).

### R59. B4 — the "lies in no subnet this collection observed" sentence was unpinned — FIXED (re-grade new item 6)
Found by the re-grade of `443a05a` (mutating the sentence left 430/430 green). **Pinned by**
`src/forwarding/engine.off-subnet.test.ts` (from `2d9712c`, checked and kept by W4-R5): 14 sources
decided off-subnet independently of the engine (SVI addresses, connected routes, endpoint records) ×
every suggested and SVI-subnet destination × every protocol must each be out-of-scope with 0 hops,
refusal kind `outside-observed-subnets`, and the full sentence (`engine.ts:1507`, verified). 2 of 2
re-run green. Reported: mutating the sentence to "is outside the collection" turns it red.

### R60. C5 — a history-blend pop, a step-down that froze a moving view, a harness blind to the tier it graded, and a caller's tier pin that did not pin — FIXED; every C5 motion item PASS in one independent laboratory run at `70bea72` (reported)
Found by the re-grade of `443a05a` (C5 FAIL, new item 7): (a) dark "high" reset-fly frame 59 changed
46,569 px with the camera still — `historyWeightFor` dropped 0.75 → 0 in one frame after a slow frame;
(b) an automatic step-down mid-orbit held a frozen overlay for about 1,000 ms (light/high orbit frame
407, a 6.08× change); (c) `capture-motion.mjs` recorded `tiersSeen` but no verdict used it.

**(a), verified in code.** `postfx.ts:220` `nextHistoryWeight` moves the weight at most
`HISTORY_AA.maxStepPerFrame = 0.125` (`:198`) per presented frame, in and out; a still-frame drain
takes 6 frames and ends before `MOTION_HOLD_MS` (140 ms); a tween's arrival is ramped out over
max(150 ms, 6 frames) and the landing frame is plain; a content change still gives 0 at once; the
tier-fade snapshot re-render is weighted the same way. **Pinned by** `render-c5-r4.test.ts` (25,
including "a 0.465 px creep, a 166.6 ms gap, then a stop: no presented frame moves the weight by
more than…") and `scene.test.ts`'s source tripwires (44) — re-run green. Reported: live probe, largest
one-frame weight change 0.75 at `2d9712c`, 0.125 after, 0 on every still frame.

**(b), verified in code.** The automatic step-down lands only with the camera at rest: `scene.ts`
`landHeldStepDown` checks it before the gesture gate (`:3183`), so the gate's 6 s backstop cannot land
it mid-orbit. The tier-fade hold ends on the first frame after the new tier presents if the camera
moved or the content changed (`stepdown.ts:670` `createTierFadeHold`); the calm wait applies only to a
still view, bounded by `TIER_FADE_HOLD_DEFAULTS.maxHoldMs = 1200` (`:659`). **Pinned by**
`stepdown.fadehold.test.ts` (4) and the `scene.test.ts` tripwire "a held step-down lands only with the
camera at rest — before the gate…" — re-run green.

**(c), verified in code.** `capture-motion.mjs:881` `tierHeldBy` and `:908` `declaredTierFails`: a
sequence with any frame off its leg's declared tier — or, since `70bea72`, any frame whose
`stats().qualityAuto` is not false — is a leg problem (every other item UNPROVEN) and FAILS "every
recorded motion frame rendered at its leg's declared tier" (exit 3); a missing record fails closed.
**Pinned by** `render-c5-repairs.test.ts` (22, its "capture-motion: a sequence is graded only at the
tier its leg declares" block) — re-run green.

**(d) A product defect found while closing C5 — FIXED in `70bea72`, verified in code.**
`scene.setQuality` returned early when the requested tier equalled the tier in force
(`if (q === decision.tier) return;`), so asking for the auto-selected tier left it adaptive and the
step-down could still move it — contradicting `scene.ts`'s documented promise that a caller-pinned
tier is never moved. The gate's `capture-motion` run at `8e873d2` showed it (reported): the harness
pinned its HIGH legs that way and both stepped down to balanced after their orbit sequences (exit 3 on
the declared-tier item, four items UNPROVEN with no pop, flicker or blink measured, cross-fade PASS
24/24). `quality.ts` `pinQuality` now always yields `auto: false` and rebuilds only on a real tier
change; `tierIsAdaptive` is the one predicate both step-down sites gate on; `stats().qualityAuto`
(`scene.ts:3595`) exposes the pin; `capture-motion` pins each render-quality leg at rest before its
first sequence. **Pinned by** `src/fabric3d/quality.pin.test.ts` — 8 of 8 re-run green, including a
control (an auto-selected high tier IS stepped down by the below-bar series), "pinning the tier
already in force makes it a pin: not auto, no rebuild…" and "a pinned high tier holds high on every
frame of a sustained below-bar series".

**What is measured, and by whom (reported; not re-run by the reconciler).** An independent verifier
re-ran `capture-motion.mjs` alone on a production preview of `70bea72`: exit 0, all six C5 motion
items PASS — edge-sparkle share 0.000057 against 0.0002; 0 z-fighting clusters; 0 pops, 0 spikes and 0
label blinks over 2,666 still pairs; 8 AO restores at 16.6–150 ms; 24 of 24 tier fades at
266.6–266.8 ms; 24 of 24 sequences held their pinned tier. No threshold changed (see the banner).
Earlier wave-4 runs are history, on a host 84–100 % busy: W4-R4's run 2 exited 3 (9 high-leg sequences
rendered at balanced; one cross-fade opacity step of 0.48 during an 83.3 ms host frame; 0 still pops
and 0 spikes in 24 of 24). **Stated caveats.** The app itself passes no pin, so an ordinary session
runs on the adaptive tier and can step down; the HIGH-leg evidence is about a pinned high tier.
`capture-motion` no longer observes an organic mid-motion step-down (it formerly failed such a leg
rather than passing it); the step-down logic is covered by `stepdown*.test.ts` and the cross-fade
item. One hold in the gate's run (light r1, high → low) read 1,816.6 ms: the harness's `holdMs` runs
from the overlay's appearance to the fade's start (`capture-motion.mjs:1082`), which includes the
re-warm-up that §4.8 counts apart from the 1,200 ms hold, so it does not by itself contradict the
stated bound; not investigated further. Residuals: O16. C5 is not re-graded here.

### R61. C6 — the `@keyframes` scan was vacuous again, and a timer-started hold had no §4.8 bound — FIXED (re-grade new item 8)
Found by the re-grade of `443a05a` (C6 PASS upheld, with two notes): `motion-inventory.test.ts:661` was
`/@keyframess+([w-]+)/g`, which returns `[]` against the planted spinner (it had lost its escapes
between `1d19e22` and `443a05a`, so R49's and O18's "scanner proven live" did not hold at `443a05a`),
and the tier step-down hold had no §4.8 bound. **Fix, verified in code.** `keyframeNamesIn`
(`motion-inventory.test.ts:231`) uses `/@(?:-[a-z]+-)?keyframes\s+([\w-]+)/g`, strips comments and also
reads root-HTML `<style>` blocks (from `2d9712c`, checked by W4-R4, who reported listing every regex
literal in the file through the TypeScript AST and finding no other de-escaped one). The script scan
now finds, as a class, every `setTimeout` whose callback starts inline motion, resolves its delay
across `src/` and fails an unresolvable one; it finds exactly one, the tier-fade hold, and
`design-brief.md:832` states its bound (**1200 ms** at most, counted from the new tier's first
presented frame, only over a still view; no hold under reduced motion). **Pinned by**
`src/core/motion-inventory.test.ts` — 27 of 27 re-run green, including "the @keyframes scan is live:
it finds planted names, including the deleted spinner's", "the script scan finds a DELAYED start…"
and "every hold before script-set motion is BOUNDED, and §4.8 states the bound the code has".
Reported: the de-escaped regex turns the first red; deleting the §4.8 hold row turns 2 red. C6 is not
re-graded here.

### R62. E1 — the journey declaration contradicted the harnesses — FIXED (re-grade new item 9)
Found by the re-grade of `443a05a` (E1 overturned PASS → UNPROVEN): `audit-e5-sweep.mjs` ("drives the
interactions the journeys do NOT cover") timed "path trace: swap + submit" with J4's own selector, and
`acceptance.md` listed swap+submit, the palette open and the first finding selection as outside the
journeys while calling the last "inside J1". **Fix (W4-R2 and the gate), verified.** A declared
journey is exactly what `measure-inp.mjs` times: `acceptance.md:84–98` lists "Inside the declared
journeys" as the harness's journey ids (J1 includes the first selection after load; J4 is swap then
submit; J5 is Ctrl+K open and Escape close) and "Outside" as the sweep's action names;
`audit-e5-sweep.mjs` is importable (an `IS_MAIN` guard; exported `ACTIONS` with untimed `setup`) and
no longer times a journey's input; the gate brought `design-brief.md` §8.1/§8.2 into line. **Pinned
by** `src/core/journey-scope.test.ts` — 14 of 14 re-run green: it executes every journey act and sweep
action against a recording page and fails on a shared input (its red branch executed), requires
`acceptance.md`'s two lists to equal the harnesses' ids and action names, and reads §8.1/§8.2 with
whitespace normalised. Reported: re-adding the old sweep actions turns it red, naming each journey's
act. **Consequence:** the 2026-09-22 sweep figures for the first selection (93.4 ms), swap+submit
(52.8 ms) and the palette open (98.3 ms) are now E3 signals against J1, J4 and J5 (O21, O30). The
refactored sweep has not run headed under acceptance conditions (a headless dev-server smoke
actuated 13 of 13 actions twice, reported). E1 is not re-graded here.

### R63. E harness defects (re-grade new item 12) — anchor discovery swallowed its errors, a cited pin did not exist, NOT MEASURED counted as a violation, and the sweep could not tell a stalled window from the app — FIXED
- **`discoverJ2Anchors`** is exported and names every failure on the anchors line and in J2's NOT
  MEASURED reason (report field `j2AnchorDiscovery`). **Pinned by** `Fabric3D.test.tsx`'s
  "measure-inp: anchor discovery names its failures…" block — re-run green (66 of 66 in the file).
- **A nonexistent cited pin.** `measure-inp.mjs` cited `src/fabric3d/measure-inp.harness.test.ts`;
  it now cites `Fabric3D.test.tsx` and `journey-scope.test.ts`. **Pinned, as a class, by**
  `src/core/acceptance-gates.test.ts` "every test a tracked review harness cites as its pin exists"
  (with a non-empty-scan precondition) — 13 of 13 re-run green.
- **`e3StableVerdict`** counts NOT MEASURED apart ([PASS, PASS, NOT MEASURED, PASS] → STABLE PASS over
  3 measured; an unmeasured run cannot make up the run count; one E3-FAIL still decides it). Pinned in
  the same `Fabric3D.test.tsx` block (`:1845`, verified) — green.
- **Window-not-presenting frames.** The sweep's `judgeFrames`/`frameKind` count a frame with 0
  blocking time and under half reported script as `not-presenting`, apart from the application's;
  over the bar it makes its repetition NOT MEASURED, naming the frame. **Pinned by**
  `journey-scope.test.ts`'s "the E5 sweep separates window-not-presenting frames…" block (4) — green.
- **The sweep's un-actuatable "path trace: swap + submit"** is removed (it is J4's act, R62).

None of these harness changes has run under acceptance conditions (O25).

### R64. F2 — wall-clock bounds and a 30 s timeout that measured the host (re-grade new item 10; O26's engine and palette halves) — FIXED; `layout.test.ts`'s bound was not, until wave 6 (O26, now FIXED)
Found by the re-grade of `443a05a` (F2 overturned PASS → UNPROVEN): under load
`CommandPalette.test.tsx:717` read 533 ms against 400, two real-data EvidencePane tests hit the 30 s
timeout while not hung, and `vitest.config.ts`'s "slowest solo: 2 266 ms" was false. No timeout or
threshold was raised.
- **CommandPalette.** Wall-clock bounds replaced by counts: 0 dataset reads per keystroke and per warm
  open (a Proxy over the dataset), at most 2 row renders per cursor move; time is logged "not gated"
  (`:731–732`, verified). `CommandPalette.test.tsx` 39 of 39 re-run green. Reported killed mutations:
  an un-memoised row, an un-memoised index, a search on every open.
- **EvidencePane.** The all-finding loops are one test per finding over the snapshot's own list, with
  non-empty-denominator and "every per-finding test ran" preconditions; the cost was profiled as
  React-dev + jsdom per mount, not product code (reported). `EvidencePane.source.test.tsx` (151) and
  `EvidencePane.targets-cap.test.tsx` (149) re-run green.
- **The engine tripwires** (`engine.test.ts`, median-of-7 under 50 ms for a trace and a counterexample
  search — the shape O26 condemns) are structural work bounds: `engineWork()` counts traces, hops and
  `lineMatches` (`engine.ts:76–78`); `ACL_PASSES_PER_HOP = 5` (`:89`) with its derivation stated;
  counterexample work is bounded by `COUNTEREXAMPLE_CANDIDATE_CAP` × the ingress count; time goes out
  through annotations only. **Pinned by** `engine.test.ts` (79) and the new
  `engine.work-bound.test.ts` (5: 341 sweep flows, 90 counterexample searches, memo-warm tight forms,
  long-list ACL cases) — re-run green. Reported killed mutations: double-traced candidates, a nested
  ACL pass (caught only once the long-list case was added), a self-re-tracing trace; not killable on
  this data: removing the 48-candidate cap (O33).
- **`vitest.config.ts`'s header** states measured figures and a rule instead of a number ("a unit test
  asserts no wall-clock time"; large units split one record per test; never raise the limit) and names
  `measure-inp.mjs` and `audit-e5-sweep.mjs` as the latency instruments (verified, `:16–30`).
- **`env.test.ts`** no longer presents a gitignored scratch script as re-runnable evidence (5 of 5
  green); the class is O29.
- **`mock-classification.test.ts`** went red when two new test files mocked modules; both are declared
  in F2's list — 3 of 3 re-run green.

**Not closed in wave 4:** `src/fabric3d/layout.test.ts:952` still asserted a median-of-7 layout time under
50 ms, against the header's rule (O26; replaced by a counted work budget in wave 6, O26 now FIXED). Reported full runs on a host 84–86 % busy: 1 failed of 2,089, in
another cluster's file; one earlier run lost four files to Vitest's fixed 60 s worker-start timeout, an
environment limit the header now records. F2 is not re-graded here.

### R65. F3/F4 documentation drift (re-grade new item 11) — FIXED in the documents
Verified by the reconciler's reading: `acceptance.md:197` recounts the source-reading test files
(**45 of 135**, 44 of the 131 tracked, with the grep stated) instead of "roughly a fifth"; `:198`
records `mutation-check.mjs` at **18 of 18 mutations killed** and marks "16 of 16" superseded, as does
`refutation.md:351`; `refutation.md` §6 carries a "Not examined" record (`:313`, added 2026-09-23);
`acceptance.md:199` F4 says mount imports 4 bindings from the entry, 3 of them the theme-preference
functions. Reported, not re-run: `mutation-check.mjs` exit 0 with 18 of 18 KILLED (three clusters),
and the F4 re-measure from a `vite build`. Historical red-before-fix for the other engines still rests
on today's-code mutations (O34). F3 and F4 are not re-graded here.

### R66. The hidden-tab stale PARTIAL card under a refused shared link (re-grade lead, `PathTrace.tsx:1090`) — REPRODUCED and FIXED
The re-grade of `443a05a` listed it as an unconfirmed lead. W4-R5 reproduced it on the dev server
(reported): a real `history.back()` in a background tab (rAF not firing) to a refused link left the
PARTIAL card of the flow just left, and it stayed after the tab drew. The restore effect showed the
flow from a local `pending` whose store write the next Back cancelled, and nothing released it; `run`'s
deferred commit was not cancellable either. **Fix, verified in code:** `pending` is only an
acknowledgement, released when the store's flow or refusal moves elsewhere, and `run` commits through
`deferPastPaint` with its cancel kept in `runCommit` (`PathTrace.tsx:1139`). **Pinned by**
`src/panels/PathTrace.test.tsx`'s "history Back while no frame has been painted (hidden tab)" block
(3 cases) — 66 of 66 in the file re-run green. Reported: all 3 red before the fix; disabling the
supersede effect reds all 3, removing the run-commit cancel reds 1.

> **Repair wave 3 (reconciled 2026-09-23, committed as `443a05a`).** Entries R39–R53 below, the
> status notes added to O10, R10, R24, R28 and R29, and the rewritten O16, O17, O20, O21 and O23 plus
> the new O24–O28 under Open, record two things: the independent re-grade of `1d19e22`
> (`docs/acceptance-report.md`), whose "new" items 1–15 and status changes had not been written here,
> and what the five wave-3 repair clusters (R1 regressions: A4, C4, D5, the D3 status-bar lead, item
> 13; R2 path trace: B1, item 14, the A2 hop header, C2; R3 focus visibility: D3, the not-observed
> box; R4 gate honesty: tracked-sources, F2, C6, F1; R5 canvas: E3, C5) and the merged-tree gate
> reported. **Every FIXED below was checked by the reconciler before it was written:** the code named
> was read at the line given, and the named tests were re-run at `443a05a` in one invocation
> (27 files, `Tests 515 passed (515)`, exit 0, with the wave-3 zero-assertion guard live in every
> file). Against `vite preview` of the `dist/` built from `443a05a` (its own port, stopped
> afterwards) the reconciler also re-ran `node review/layout-guard.mjs` (exit 1 on exactly one
> violation, the pre-existing O24; invariants 4 and 5 hold at every size) and
> `node review/audit-d3-focus.mjs` (`341 case(s), 0 failed.`, `681 focus stop(s) checked for
> visibility, 0 not visible.`, exit 0; R42). **Verified by the orchestrator at `443a05a`:**
> `tsc -p tsconfig.json`, `tsc -p tsconfig.scripts.json --noImplicitAny` and
> `tsc -p tsconfig.config.json` all exit 0; `vitest` 128 files, 1714 tests, exit 0 (so
> `tracked-sources.test.ts` is green once the commit tracks `src/app/theme-preference.ts`);
> `npm run build` exit 0; the commit's content and message scan clean against the parent repository's
> 12 client-marker patterns. **Not re-run by the reconciler, and cited as "reported" wherever it
> appears:** `capture.mjs app`, `text`, `reduced` and `twice 5`, `capture-motion.mjs`,
> `measure-inp.mjs`, `measure-fps.mjs`, the E5 harnesses, the agents' in-page probes and screenshots
> (orchestrating session's scratchpad, not this repository), and every wave-3 mutation (none of them
> is among those `mutation-check.mjs` executes). A fixed defect does not by itself move its
> criterion; nothing here is a re-grade.
>
> **History as of wave 3** (it continues in the wave-4 banner above). `50a3dc5` (root) → `254694b`
> (wave-2 checkpoint, red on purpose) → `1d19e22` (repair wave 2c) → `d3e2a1c` (docs only: the
> wave-2c record and the re-grade of `1d19e22`) → `443a05a` (repair wave 3, 73 files). `git status`
> was clean at `443a05a`.

### R39. A4 — a device pick with no finding selected reset the queue's scroll — FIXED; a narrower band of the same shape (the only visible naming row in the queue's bottom ~38 px) failed A4 at `8eac055` and was fixed in wave 7 (R91)
Found by the re-grade of `1d19e22` (A4 FAIL, its new item 2): with no finding selected and the queue at
scrollTop 3200 with F060 and F069 (both naming access13) in view, clicking access13 left 3200 after
80 ms, then 0 once settled; core2 went 3200 → 2681, and dist1 likewise. Origin, traced by the R1
cluster in history: the "no finding → reveal the FIRST row naming the device" rule dates from
`50a3dc5`; `254694b` added the reveal key `d|device|link|hop`, which re-runs that reveal on every
device pick. The earlier PASS was measured with a finding active, so this path was never graded.

**Fix.** With no finding selected, the queue skips the representative reveal when a naming row is
already fully visible, and puts the roving tab stop on that visible row, so a dialog returning focus
cannot page the list — verified in code: `DataGrid.tsx:175` (`revealUnlessVisible`), `:873`
(`firstVisibleRow` over it), and `PriorityQueue.tsx:1941`, which passes it only while
`activeRowId === null`. With no naming row in view, F002 is still revealed. **Pinned by**
`src/panels/PriorityQueue.a4-scroll.test.tsx` — 9 of 9 re-run green, including "the grid OWNS focus
when the selection's marks commit…", "focus returning to the grid after the pick (the palette
closing) stays on the answer in view" and the with-finding control. Reported red before: 9 failed
(`expected +0 to be 975`); reported mutations: three, each red then restored. Reported browser
figures (1920x1080, `?s=queue`): Fabric list, palette and canvas picks all 3200 → 3200 (was → 0);
core2 held at 5800. A4 is not re-graded here. **Status after the re-grade of `443a05a`:** holds for
the no-finding path; A4 failed there on the duplicate-row path instead, fixed in wave 4 (R56).
**Status after the re-grade of `8eac055`:** A4 FAILED on this fix's own path in a narrower band: the
rail's count sentence moved the grid before the `revealUnlessVisible` check ran, so a naming row in the
bottom ~38 px read as hidden and the queue went to 0. Fixed in wave 7 by taking the decision against
what the reader saw when they acted (R91).

### R40. C4 — a light-OS reader got a dark first paint — FIXED on the release build; one dev-server residual reported
Found by the re-grade (C4 overturned PASS → FAIL, its new item 5): `index.html` opened
`<html lang="en" data-theme="dark">`, so a light OS with nothing stored painted `rgb(8, 10, 14)` at
the boot line. Origin (R1, from history): the attribute has been in all three HTML pages since
`50a3dc5`; `254694b`'s wait-for-paint entry exposed it.

**Fix.** No HTML page carries `data-theme` (verified: the only match in the three pages is the inline
script's `setAttribute`). `src/app/theme-preference.ts` (new, tracked in `443a05a`) is the one owner:
`THEME_STORAGE_KEY` (`:30`) is named nowhere else in `src/`, and `commands.ts` now applies and writes
through it (`:43`, `:202`, `:205`; applied by the gate). `index.html:15` is one classic inline
`<head>` script that applies only an explicit stored `light`/`dark`, and `theme-boot.test.ts`
executes it beside the module reader over the storage states and requires identical results. The
gate also gave each explicit theme its own `color-scheme` in `tokens.css` (`:272–273` light,
`:337–338` dark, inside the existing dark block because `contrast.test.ts` reads one block per
selector). **Pinned by** `src/app/theme-boot.test.ts` — 24 of 24 re-run green ("no <html> start tag
carries data-theme", "no source file but theme-preference.ts names the storage key at all…",
"commands.ts's setTheme writes and applies through the module", the three per-theme `color-scheme`
tests). Reported: before the fix 8 of 11 failed; on the release build with Element Timing, 8 of 8
PASS with and without a 300 ms entry-fetch delay (explicit choices applied 14–27 ms before the boot
line paints; the main.tsx-only version failed the delayed case).

**Residual, dev server only (reported, not re-measured).** Under `vite` dev, `tokens.css` is injected
by script after first paint, so an explicit choice opposite to the OS paints its boot line on the
UA Canvas colour until tokens load. The gate's per-theme `color-scheme` rules live in `tokens.css`,
so by construction they cannot act before that file loads; they fix UA-painted parts after load. No
one has measured the dev-server boot line since. It does not reach the release build. C4 is not
re-graded here.

### R41. D5 — the Inspector's resize divider was an 8 px pointer target — FIXED, and the target-size scan now covers the class
Found by the re-grade (D5 FAIL, its new item 11): `div.inspector__divider` (role=separator) was
760x8 at 1440; `target-size.test.ts` scanned only `cursor: pointer`, and the exceptions file it
referred to did not exist. The 8 px size and its false comment date from `50a3dc5`; the earlier PASS
never opened the Inspector.

**Fix.** `Inspector.css:44` `block-size: var(--sp-5); /* 24px */` (verified), with a transparent
target; the hairline and grip are still drawn (reported, screenshots). `target-size.test.ts` now
selects target rules by class: any operable cursor value plus any class the markup puts on
`role="separator"`, both axes, fixed sizes as well as minimums, `calc(var(--x) * n)` resolved, with a
planted known-answer case. It honours no exemptions and asserts `docs/target-size-exceptions.md` does
not exist (`:250`; the file is absent). **Pinned by** `src/ui/target-size.test.ts` — 7 of 7 re-run
green. Reported: the widened scan failed on exactly the divider before; the reverted size turns it red.
D5 is not re-graded here.

### R42. D3 — tab-panel rings clipped by their scroller, the snapshot sha's Copy button outside its popover, and a focused grid cell under the status bar — FIXED; a focused grid cell under the status bar recurred at `34bd435` by another route (R105), fixed in wave 8
Found by the re-grade (D3 FAIL, its new item 10: `.dp__body` clipped the Device-pane tab-panel
outline to "0 pixels at ≥3:1"; "Copy the snapshot sha256" sat at x=641–668, outside the x=121–554
popover, with `elementFromPoint` returning the canvas) plus its 390 px lead (a focused grid cell under
the sticky status bar). The R3 cluster first taught `review/audit-d3-focus.mjs` to check VISIBILITY
as well as return (elementFromPoint at the centre of the element's visible part, and at least half the
visible perimeter changing by ≥3:1 between focused and indicator-suppressed screenshots), added 1440x900
and a "Tab into its panel" scenario for every tab; that audit then found two more of the class, the
Inspector's first tab (clipped by `.ui-tabs`) and a chip's remove button (clipped by `.ui-chip`).

**Fixes, verified in code.** `primitives.css:733–736` draws the ring inside the element for
`.ui-tabpanel:focus-visible, .ui-tabs :focus-visible, .ui-chip :focus-visible`
(`outline-offset: calc(-1 * var(--focus-ring-w))`). `.ui-copyable` is bounded by its container
(`:1006–1014`), and a `digest` variant (`:1032`, an UNBREAKABLE-TOKEN CONTAINER) shows the sha whole;
`Header.tsx:218` passes `digest`. `DataGrid.tsx:457`/`:478` `trimOverlays` excludes anything painted
over the grid's edges from its visible band, and focus arriving from outside by keyboard or script
gets the same band-aware reveal. **Pinned by** `DevicePane.focus-visible.test.tsx` (3),
`popover-focus.test.tsx` (5), `Header.test.tsx` (35, including "renders the sha as a digest that
wraps inside the popover…") and `PriorityQueue.reveal-hold.test.tsx` ("keyboard focus moving down
stops ABOVE a sticky status bar…", "a cell focused from outside … is revealed above it") — all re-run
green. **The runtime audit, re-run by the reconciler** against `vite preview` of the `443a05a` build:
`341 case(s), 0 failed.`, `Driven, by kind: dialog=12 popover=165 field=52 grid=26 tab=59 find bar=10
inspector=15 copy=2`, `681 focus stop(s) checked for visibility, 0 not visible.`, exit 0.
Reported: 681 stops, 45 not visible before the fixes; mutations of each rule red then restored. The
floor is stated in the audit's header: half the visible perimeter, because a plainly visible 2 px
inset ring on a 24x17 cell yields only 66 of 82 perimeter pixels at ≥3:1 — a floor for SC 2.4.7
"visible", not an SC 2.4.13 grade. Harness note (R3): a dev server other agents edit reloads
mid-audit, so R3 measured on a no-HMR, no-watch Vite with its own cache directory.

**The 1000x800 half.** The widened audit's last 10 NOT VISIBLE stops were one compact-viewport cell
half under the status bar; the root was layout, not focus: in the single-column band (768–1023 px)
with no trace the findings grid ran past rail A (1000x800: grid 698–1002, rail ending at 774) and,
at 800x600, focusing its first cell scrolled the `overflow: hidden` `.app` frame (status bar
574 → 220). The gate added `@media (min-width: 48rem) and (max-width: 63.9375rem)` to `shell.css`
(`:643–650`: rail A scrolls, contained; the slot keeps `min-block-size: min-content`) and
`layout-guard.mjs` INVARIANT 5 (`:232`). **Verified by the reconciler's layout-guard run:** at
1000x800, 900x700 and 800x600 the grid paints to exactly the status bar's top (774/674/574), `.app`
scrollTop stays 0 after focus, and the focused cell is inside the rail (749–766, 553–570, 502–519).
Invariant 5 does not measure 768 px itself (O17). D3 is not re-graded here.

### R43. B1 — a shared link carrying an invalid port or protocol was traced and rendered as a verdict — FIXED
Found by the re-grade (B1 FAIL, its new item 1): `?s=path&flow=10.0.10.50>10.0.20.10>tcp>abc` rendered
"tcp … :NaN" and "is delivered at core1"; port 70000 and protocol `bogus` were traced too.

**Fix, verified in code.** One validator, `readFlow`/`flowProblems` (`src/forwarding/ip.ts:302`,
`:330`), serves the form (`PathTrace.tsx:137` `validateFlowForm`), the link (`store.ts:207–209`: a
refused link becomes `flowRefused`, never `flow`; its hop is not restored and its text is re-encoded
unchanged) and `traceFlow`'s entry (`engine.ts:1889–1895`, refusal kinds `invalid-address` /
`invalid-flow`, `INVALID_INPUT_REFUSALS` at `:1679`, read by `claims.ts:400` `isInvalidInput`, badge
INVALID INPUT at `:461`). **Pinned by** `src/core/store.flow-validation.test.ts` (20),
`src/forwarding/engine.flow-validation.test.ts` (12) and `src/app/surfaces.test.tsx` (9, including
the whole App mounted from an invalid link: no NaN, no verdict, no `.pt-result`) — re-run green.
Reported: 36 failed before; two mutations red then restored; in the browser all three links render
the refusal ("The destination port "abc" in the shared link is not a port number…"). B1 is not
re-graded here.

### R44. B1 minor (re-grade item 14) — the HopList said "not observed" where the Inspector said "0 by definition" — FIXED for those two surfaces only; the Device pane still disagreed at the re-grade of `443a05a`, and the "0 — by definition" reading was withdrawn in wave 4 (R55)
For the same null `adminDistance` on a connected route the two surfaces disagreed. **Fix, verified in
code:** every route-record field in the hop list (winner and every alternative; `adminDistance` and
`nextHop`) goes through one `RouteField` (`HopList.tsx:425`) that asks the Inspector's owner,
`claims.ts` `notApplicableReason`, before the not-observed treatment (`:439`). Stated consequence:
the hop list's connected-route next hop now reads the owner's "n/a — a connected route has no next
hop" instead of "directly connected — no next-hop address". **Pinned by**
`src/panels/HopList.admin-distance.test.tsx` (4, every structural null on every traced hop against
the Inspector's row for the same cite) — re-run green; reported 3 failed before and a mutation red.

**Status after wave 4.** Partial, per the re-grade of `443a05a`: the Device pane's Routing tab still
rendered the same null as "not observed" (B1 FAIL), and the evidence pane and the engine's
`adminDistanceOf` were further readers. All four surfaces and the engine now read one owner,
`core/route-fields.ts`, and the connected-route AD reads "not recorded — …" rather than "0 — … by
definition" (R55).

### R45. A2 / layout — `.hop__host` collapsed to 0 px on the denied flow's hop header — FIXED
Found by the re-grade (its new item 3: the header overflowed by 174–214 px). **Fix, verified in
code:** `.hop__head` wraps (`PathTrace.css:323–329`) and `.hop__host` keeps its width
(`flex: 0 1 auto`, `:361–372`), so the verdict badge wraps instead. `review/layout-guard.mjs` gained
INVARIANT 4 (`:189`: every hop header of three traced flows at 390/768/1440/1920). **Verified by the
reconciler's layout-guard run** on the `443a05a` build: all 12 headers show their host at 38 px with
0 px overflow. There is no unit test; the guard is the evidence. Reported: 9 violations before
(including the delivered flow, host 0 px at 1440), returning when the CSS is reverted. A2 itself stays
UNPROVEN (depth 1, R18).

### R46. C2 — the path form was cut by its scroll slot, the detector could not see it, and adjacent not-observed boxes switched layout — FIXED
Found by the re-grade (C2 FAIL, its new item 4): at 1440x900 on `?s=path` the path slot was 170 px
(84–254) with Destination, Protocol, Port and "Trace this flow" outside it; at 1920 the submit was
sliced; and on `?d=core1` "Power supplies" stacked while "Modules" sat side by side.

**Fixes, verified in code.** `surfaces.tsx:314–360` measures the rendered flow form while the reader
is on the path surface and publishes it as `--rail-a-path-need` with `data-path-lead="form"`;
`shell.css:480–500` makes that measured height the path track's floor (other surfaces keep 10rem).
`review/capture.mjs:718` `readFormReach` fails any form split by its scroll port (six known-answer
self-test cases). `primitives.css:125–126` `.ui-notobs__why { flex: 1 1 100% }` puts the reason on
its own line. **Pinned by** `DevicePane.cmp-layout.test.ts` (4) — re-run green — for the box; the
form half has no unit test and rests on `capture.mjs text`, reported by the gate at `PASS text 72 of
72`, `selftest 23 of 23`, on the final build (not re-run by the reconciler). Reported before:
`FAIL text 66 of 72` (05-path-trace at 768/1440/1920, both themes).

**Stated consequences.** At 1440x900 on `?s=path` the queue's rows now sit below rail A's fold and
are reached by scrolling the rail (O24). And the gate found this rule had tripled full-layout cost
(an overflowing `overflow-y: auto` rail), turning J4 E3-FAIL (12–16 on-path tasks over 50 ms); it
set `overflow-y: scroll` on exactly `.rail--a[data-split="true"][data-path-lead="form"]`
(`shell.css:486–500`, verified in code), and reports J4 E3-PASS with 0 on-path tasks after, and
alternating A/B forced layout 9.2–12.9 ms (auto) against 2.5–4.4 ms (scroll) — reported, laboratory.
The descender half of O17 is still undetected. C2 is not re-graded here.

### R47. tracked-sources — the gate's denominator ignored `import.meta.glob`, the preview pages and CSS `@import` — FIXED
Found by the re-grade (tracked-sources overturned PASS → FAIL, its new item 7; see O10). **Fix
(R4):** the denominator is now the real Vite/Rolldown build — an in-memory build of every non-ignored
`*.html` page, taking every module id plus every file the build's plugins read through `node:fs` —
plus the `tsconfig.scripts.json` program for the compilers; "tracked" means held by the HEAD tree. A
known-answer fixture plants three untracked files reachable only through an eager glob, a lazy array
glob and a CSS `@import`, and the gate must name exactly those. **Pinned by**
`src/core/tracked-sources.test.ts` — 6 of 6 re-run green at `443a05a`. During the wave it was red on
exactly `src/app/theme-preference.ts`, which the build imported before it was committed; the commit
closed that, and the orchestrator's full run at `443a05a` is green. Reported mutations: the old static
walker and a disabled fs-read recorder each turn the known-answer test red.

### R48. F2 — three tests made zero assertions and four could pass vacuously — FIXED, with a runtime guard for the class
Found by the re-grade (F2 overturned PASS → UNPROVEN, its new item 8). **Fix (R4), verified in
code:** `src/test-setup.ts:36–41` is an `afterEach` that fails any passing test whose
`expect.getState().assertionCalls` is 0, naming it; `vitest.config.ts:65` installs it through
`setupFiles`. The only opt-out is Vitest's own `expect.assertions(0)` with a mandatory
`assertion-guard:` comment (none in use, reported). The three zero-assertion tests
(`compiler-fidelity` null port, `motion-inventory` keyframes, `engine.test` catch-all phrase) and the
four vacuous ones (`engine.test` implication, `ip.test` 5 of 9 pinned, `status-telemetry` element
presence, `camera.keyboard` press moves) were pinned. **Pinned by** the guard's self-proof in
`src/core/scripts-typecheck.test.ts` ("the guard ran in this very worker…", and a child Vitest under
the real config that must fail on a planted zero-assertion test) and by the seven files themselves
(`compiler-fidelity` 9, `engine.test` 79, `ip.test` 25, `status-telemetry` 8, `camera.keyboard` 6,
`motion-inventory` 24) — all re-run green with the guard live, as is the orchestrator's full 1714-test
run, so no test at `443a05a` completes with zero assertions. Reported: its first run found exactly
the three. F2 is not re-graded here.

### R49. C6 — the §4.8 motion inventory was false against the code, and its test never read CSS transitions — FIXED; its `@keyframes` scan was vacuous at `443a05a` (re-grade) and was restored in wave 4 (R61)
Found by the re-grade (C6 overturned PASS → UNPROVEN, its new item 6): §4.8 promised an 18 ms per-hop
stagger and a 140 ms palette animation that do not exist and omitted about eight running transitions.
**Fix (R4).** `motion-inventory.test.ts` now parses every `transition`/`animation` declaration in
every stylesheet and root-HTML `<style>` (tokens resolved), discovers script motion structurally
(`*_MS` progress divisors, inline transitions, exported eases, OrbitControls damping), and checks
§4.8 both ways, with a liveness test that feeds the old rows back in and must report the stagger, the
palette and the omissions. §4.8 was rewritten (verified: `design-brief.md:829` "ONE reveal … There is
no per-hop stagger"). The dead `.stage-dim` rule (a 240 ms fade nothing applied) was deleted by the
gate with its §4.8 row, and two other claims that the Stage dims were corrected (verified:
`.stage-dim` survives only in comments, `shell.css:558` and `design-brief.md:150`). **Pinned by**
`src/core/motion-inventory.test.ts` — 24 of 24 re-run green. Reported: the old brief turns it red
(5 failed); computed styles in the running app match the rows. The packet loop (1600 ms × 3) is stated
as unexercisable on the depth-1 snapshot. C6 is not re-graded here.

**Status after wave 4.** The 24 green tests above did not include a live keyframe scan: at `443a05a`
the regex had lost its escapes (`/@keyframess+([w-]+)/g`) and matched nothing, which the re-grade of
`443a05a` found. Restored with a known-answer case in wave 4, which also added the delayed-motion
scan and the §4.8 hold row (R61; `motion-inventory.test.ts` 27 of 27).

### R50. F1 scope — `vite.config.ts` and `vitest.config.ts` were in no type-checked project — FIXED
Found by the re-grade (its new item 12): `minWorkers: 1` was silently ignored (TS2769; removed in
Vitest 4) and `vite.config.ts` ended in `as any`. **Fix (R4), verified in code:** both removed
(`vitest.config.ts:58` keeps only a comment; `vite.config.ts:32` says why there is no `test` block);
`tsconfig.config.json` (new, tracked) covers both configs; `package.json:11–12` — `build` type-checks
the config project, and `typecheck` runs all three projects. `docs/acceptance.md` F1 now names the
third project (verified). **Pinned by** `src/core/scripts-typecheck.test.ts` (12: every authored
TS/JS file Git does not ignore is in some project; a planted `minWorkers` and a planted type error must
be reported) — re-run green; the orchestrator's `tsc -p tsconfig.config.json` exits 0. Reported: the
build output is byte-identical before and after (15 files, sha256). The declared exclusion that
remains is O27.

### R51. E3 — the first device selection after load put a 55–79 ms task on the interaction path, and the harness spent that selection before measuring — FIXED IN CODE; laboratory evidence only
Found by the re-grade (E3 overturned PASS → FAIL, its new item 9). **Harness (R5), verified in
code:** `measure-inp.mjs` no longer primes J2 with a selection, and reports a separate
`J2-first-select-device-3d` journey, one fresh browser per trial (`:744–746`, default
`core2:15,core1:3,dist1:3`); `docs/acceptance.md` E3 names it (verified). **Product, verified in
code:** the warm-up now draws the interaction visuals' programs in non-presenting warm-up steps
(`scene.ts:507–523`, `:2814` `withInteractionVisualsPrimed`; the cause was 105–128 ms of
`getProgramInfoLog` on the first real draw), and a canvas click acknowledges on the scene inside the
input task while the cross-surface store write waits until the browser's Event Timing entry for that
pointerup reports it presented, with a frame-count fallback (`Fabric3D.tsx:695–702`,
`deferPastPaint.ts:79` `deferPastPresentation`). **Pinned by** `Fabric3D.test.tsx` (61, including
"every journey's pre-loop hooks perform none of the input its measured act performs", `:1744`) and
`scene.test.ts` (39) — re-run green.

**Not established.** Reported laboratory runs only: the R5 cluster on a contended host (36 % busy) —
first selection 0 of 21 trials with an on-path task over 50 ms, INP p95 64 ms; the gate's final
`measure-inp` — all 7 journeys E3-clean but on battery with a Teams meeting in the foreground, so
`host-env.mjs` withheld it; E3's across-runs verdict for that build is INSUFFICIENT RUNS (0 of the 3
quiet runs needed). E2's warm J2 p95 moved from 40 to 88 ms (the click's presented frame is now the
canvas's own acknowledgement), still under 200 ms. See O25. E3 is not re-graded here. **Status after
the re-grade of `443a05a`:** J2-first was E3-clean in all 3 of its runs, and in the wave-4 gate's run
(21 of 21 trials, p95 96 ms) — laboratory only, on busy hosts (O25).

### R52. Harness defects from the re-grade (its item 15) — the headed window larger than the screen, and the popping check's divide-by-zero — FIXED; the palette keystroke race is not
- **Headed window (class fix, R5 and the gate).** Every headed harness launched at a fixed
  `--window-size=1940,1180`, larger than the reference host's 1280x752 DIP work area at DPR 1.5.
  `review/host-env.mjs:118–208` now owns `planWindow`, `windowInside`, `headedWindow`,
  `windowBoundsCheck` and `windowFitsOf`; `measure-inp`, `measure-fps`, `audit-e5-sweep`,
  `audit-e5-coldload` and `_audit_perf_e4_indep` take the plan and gate `acceptanceEvidence` on the
  window fitting (verified: no fixed `1940` size survives outside comments). **Pinned by**
  `src/core/headed-window.test.ts` (5, finding the harnesses from the directory, not a list) —
  re-run green.
- **"Infinityx" (R5).** `capture-motion.mjs` divided a spike by a neighbour median of 0. The reference
  rate is now `max(neighbour median, SPIKE_NORM_FLOOR)` (`:145` `SPIKE_NORM_FLOOR: 1.6`, `:698`),
  stated against the largest smooth-motion rate of the 2026-09-22 run (4.53 levels/px; 3 × 1.6 = 4.8).
  Stated cost: in sequences whose neighbour rate is below 1.6 (dolly ≈ 0.7) the spike bar rises to
  4.8 levels/px. **Pinned by** `render-c5-repairs.test.ts` (14, including "an ordinary camera step
  among sub-pixel frames that changed nothing is NOT a pop (the Infinityx artefact)" and "a real pop
  among near-still frames still fails, and its ratio is finite") — re-run green. The orchestrator
  confirmed no other capture-motion threshold changed since `d3e2a1c`.
- **Shots root (R2).** `capture.mjs` honours `ATLAS_SHOTS` (verified, `:27–30`): two concurrent
  `twice` runs sharing `review/shots/_twice` had deleted each other's captures. F6 must be run with its
  own root while other agents capture.
- **Palette keystroke race in the A1 census** — not addressed; O28.

### R53. Claim consistency (re-grade item 13) — the compiled coverage record's bare `aclLinesUnevaluable: 1` beside a status bar saying 6 of 12 lines cannot be decided — FIXED on both tabs that show it
A lead from the B6 refuter. The counter is the collector's parser flag only; the undecidable set is
the union `aclUndecidability()` (`core/acl-coverage.ts`) computes. **Fix, verified in code:** the
Inspector's Data tab labels the field as the parser's flag beside the union count
(`Inspector.tsx:1012`), and the gate gave `JsonView` a per-path `annotations` prop (`JsonView.tsx:335`,
drawn at `:687`) through which the JSON tab — where the whole `fabric.json`, and so the grader's bare
`1`, is shown — carries "parser flag only; undecidable: N of M ACL lines — aclUndecidability()…"
(`Inspector.tsx:652`, `:1260`). **Pinned by** `Inspector.test.tsx` (50, including "the compiled
coverage record's aclLinesUnevaluable is labelled as the parser's flag, beside the union", "the JSON
tab annotates the same field the same way…" and "draws a note on exactly the annotated row, and on no
other") — re-run green. Reported: the note is 450 px and shown whole at 1440 and 1024. R1 found no UI
path that opens the `coverage` citation in the Data tab, so the JSON-tab note is the one a reader meets.

> **Repair wave 2c (reconciled 2026-09-23, committed as `1d19e22`).** Entries R26–R38 and the moved
> O10, O15 and O18 below, and the rewritten O12, O16, O17 and O20 plus the new O21–O23 under Open,
> record what the five wave-2c repair clusters (focus return / D3, band and labels / B1, layout / C2,
> motion / C5–C6, provenance / O15–F2–F3) and the merged-tree gate reported. **Every FIXED below was
> checked by the reconciler before it was written:** the code named was read at the line given, and
> the named tests were re-run in one invocation (35 files, `Tests 649 passed (649)`, exit 0), and both
> `tsc` configs exit 0 (`tsconfig.json`; `tsconfig.scripts.json` with `--noImplicitAny`). On a
> scratch `vite build` of `1d19e22` served on its own port (stopped afterwards) the reconciler also
> re-ran `node review/audit-d3-focus.mjs` (`210 case(s), 0 failed.`, exit 0) and
> `node review/capture.mjs text` (`PASS selftest 17 of 17`, `PASS wrap 0 unjustified`, `PASS text
> 72 of 72 states`, exit 0), and ran `node review/mutation-check.mjs` (18 of 18 KILLED, exit 0,
> `node_modules` intact afterwards). The orchestrator verified the full suite at `1d19e22`
> (`vitest` 121 files, 1571 tests, exit 0) and ran `node review/capture-motion.mjs` (exit 3, O16).
> **Not re-run by the reconciler, and cited as "reported" wherever it appears:** `capture.mjs app`,
> `capture.mjs twice 5` (F6), `capture.mjs reduced` (D7), the INP and cold-load harness runs, the
> agents' in-page probes and screenshots (they live in the orchestrating session's scratchpad, not
> in this repository), and every agent mutation other than those `mutation-check.mjs` executes. As
> before, a fixed defect does not by itself move its acceptance criterion; nothing here is a re-grade.
>
> **History as of wave 2c** (it continues in the wave-3 banner above). `50a3dc5` (root; rebuilt marker-free from the original `857b520`, see O10) →
> `254694b` (checkpoint of the interrupted wave-2 tree, suite red on purpose at 15 of 1465) →
> `1d19e22` (repair wave 2c). A sha `857b520` anywhere below refers to the superseded root.

### O10. The nested repository and the untracked tree — DECIDED (own local repository) and RESOLVED by commit; `tracked-sources.test.ts` GREEN at `1d19e22` but its denominator was wrong (re-grade), rebuilt in wave 3 (R47) and GREEN at `443a05a` (moved from Open, 2026-09-23)
Originally recorded (acceptance F2, 2026-09-22) as OWNER DECISION: `src/core/tracked-sources.test.ts`
was red on 19 untracked runtime-imported modules, compiled files and compilers (17 at acceptance),
and `atlas-scope/.git` had been created by a repair agent without being asked (filesystem birth time
of `.git` 2026-09-21 09:09:53 +0300), with a single commit that postdated the fixes whose "failed
before" it was meant to anchor.

**Decision (2026-09-23).** Taken by the orchestrator on the owner's delegated instruction to take the
best decision: Atlas Scope keeps its own repository at `atlas-scope/.git`, local, with no remote. It
is not folded into the parent repository and not re-initialised.

**The root was rebuilt before its first real use.** The original root `857b520` carried an absolute
home-directory path in a comment in `src/forwarding/engine.test.ts`, and the Windows user name in that
path is one of the parent repository's client-marker patterns. It was replaced by `50a3dc5`, which
differs from `857b520` by exactly that one line — verified by the reconciler with
`git diff --stat 857b520 50a3dc5` (`src/forwarding/engine.test.ts | 2 +-`, one insertion, one
deletion); the new line names "the engine repository root — the parent of atlas-scope/" instead.
`857b520` is on no branch; every older citation of it in this file and in `docs/` means that
superseded root. History since, from `git log` (re-read at `443a05a`): `254694b` ("wip: checkpoint
the interrupted wave-2 tree", committed red — 15 of 1465 — so that each failing test is on record
before its fix), `1d19e22` (repair wave 2c), `d3e2a1c` (docs only: this file's wave-2c record and
the re-grade of `1d19e22`) and `443a05a` (repair wave 3); since then `1c829c9` (docs only),
`2d9712c` (checkpoint of the interrupted wave-4 run), `8e873d2` (repair wave 4) and `70bea72` (the C5
tier pin), read from `git log` at `70bea72` (the wave-4 banner); then `2797da3` (docs only) and
`78bdba5` (repair wave 5), read from `git log` at `78bdba5` (the wave-5 banner); then `efc3929` (docs only)
and `8eac055` (repair wave 6), read from `git log` at `8eac055` (the wave-6 banner) — 13 commits on
`main` at that point; then `6a5d830` (docs only), `ba7b456` (repair wave 7) and `34bd435` (the B6
census residuals), read from `git log` at `34bd435` (the wave-7 banner) — 16 commits on `main` in all,
`50a3dc5` the root. Every commit candidate
was to be scanned with the parent repository's own marker patterns
(`cisco_toolkit/distribution_verify.py` `_client_marker_patterns`) before it is committed. **History
contradicts that as a guarantee:** `f70f060`, the first version of the wave-4 record, was committed
carrying the Windows user name and was amended into `2797da3` (the wave-5 banner). Since then the scan
is enforced by a gated commit wrapper that refuses a dirty tree or message (orchestrator, reported).

**The untracked-files half is resolved by commit.** `254694b` tracked the 19 files and `1d19e22`
tracked `tools/source-binding.mjs` (the one new module every compiler imports). At `1d19e22`
`git status --short --untracked-files=all src tools` lists nothing, the orchestrator's full run is
green (121 files, 1571 tests, exit 0), and the reconciler's targeted run includes
`tracked-sources.test.ts` green ("no runtime-imported module, compiled file or compiler is
untracked"). The test was not loosened.

**Superseded in part by the re-grade of `1d19e22`.** "GREEN" was true but not sufficient: the
refuter planted an untracked `src/forwarding/zz-untracked-probe.json`, the test still passed 3 of 3,
and the file shipped in the built `mount-*.js` — the walker did not follow `import.meta.glob`
(`Inspector.tsx`), the two preview pages, or CSS `@import`. The gate was rebuilt on the bundler's own
module graph in wave 3 (R47); at `443a05a` it is green, 6 of 6 (reconciler), and the one file it
named during the wave, `src/app/theme-preference.ts`, is tracked (`git ls-files`).

**What this does not establish.** No criterion is re-graded here. The re-grade re-ran F1, F2 (unit
half), F4 and F5 on a clean clone of `1d19e22`; the re-grade of `443a05a` reproduced F5 from a real
`git clone` of `443a05a`, and nothing else has been run from a clone since (O23). At `70bea72`
`tracked-sources.test.ts` is green, 6 of 6 (reconciler): `src/core/route-fields.ts`, the one file wave
4's gate left untracked, is tracked in `8e873d2`. At `78bdba5` it is green, 6 of 6 (reconciler); wave 5
added no module the build imports (every cluster's `newFilesTheBuildImports` is empty, reported). At
`8eac055` it is green, 9 of 9 (reconciler; the file gained a precondition test and a single program
build in wave 6, R85). Wave 6 added one module the build imports, `src/panels/cited-text.tsx` (R81): the
gate's two full runs were red on exactly that file, untracked, until the owner's commit, and the
orchestrator's full run after `8eac055` is green. At `34bd435` it is green, 9 of 9 (reconciler); wave 7
added no module the build imports — the six files `git diff --diff-filter=A 6a5d830 34bd435` lists are
all tests. The source snapshot still lives in the parent repository, so
`git show HEAD:<source>` inside `atlas-scope` cannot reach it. `50a3dc5` inherits `857b520`'s
limitation as a provenance baseline; `254694b` → `1d19e22` is the first pair in this history in which
failing tests were committed before their fixes (R34).

### O15. F5 — the recorded source digest bound CRLF working-tree bytes, not the committed blob — FIXED (moved from Open, 2026-09-23)
Found by the acceptance refuter: `meta.sourceSha256` was `9cc348bd…5dfd`, the Windows CRLF checkout of
`webapp/sample_data/sample_fleet.snapshot.json`, so F5 held on this host's disk only.

**Fix (wave 2c, provenance cluster; the three consumer and wording changes applied by the gate).**
`tools/source-binding.mjs` (new, tracked in `1d19e22`) is the one owner of the binding rule: it hashes
the LF-normalised bytes and records `meta.sourceDigestForm: "lf-normalised"`. All four
`tools/compile-*.mjs` import it; `provenance.test.ts` enforces that by globbing `tools/`. Every
sidecar consumer fails closed on any binding mismatch through `types.ts` `sameSourceBinding` (digest,
form, byte length, source) — verified in code: `bindings.ts:51`, `rib-completeness.ts:60`,
`producer-emission.ts:32`. The Inspector, Header and StatusBar label the digest and byte count as
LF-normalised.

**Verified.** By the orchestrator: `fabric.json` and the three sidecars all bind
`9580aa092d490a13ba420b2cc670ddee026f6dbf93ecc5aeac2fc94cd7f13089` (3,072,771 bytes, form
`lf-normalised`), which equals `git cat-file blob HEAD:webapp/sample_data/sample_fleet.snapshot.json |
sha256sum` in the parent repository, and recompiling `fabric.json` is byte-identical. Re-checked by
the reconciler: the four `meta` blocks read as above; the parent's blob hashes `9580aa09…3089` and is
3,072,771 bytes; `sha256sum src/data/fabric.json` is `2f558c38…a308` (at `1d19e22`; it is
`a1a599b8…d251` since wave 4's B6 compiler change, with the source digest unchanged — R54). **Pinned by**
`src/core/provenance.test.ts` (the CRLF-vs-LF binding test and one "writes the same bytes from a CRLF
checkout as from an LF one" test per compiler), `src/forwarding/bindings-trust.test.ts` ("every
source-bound sidecar consumer fails closed on any binding mismatch", which finds sidecars
structurally), `src/panels/producer-emission.test.ts`, `Inspector.test.tsx` ("names the byte form its
digest and byte count are taken over") and `Header.test.tsx` ("… (O15)") — all re-run green.
`mutation-check.mjs` reverts `lfNormalise` and the form-aware trust check (both KILLED in the
reconciler's run). Reported before the fix: `Tests 12 failed | 10 passed (22)` in provenance.

**Digest pins, same cluster.** `review/layout-guard.mjs`, `devHandle.ts` and `devHandle.test.ts` carried
the stale tag `9cc348bd58bb`; they now derive it, and `provenance.test.ts` "no authored code file pins
the snapshot digest" (green) fails on any hex literal of 8+ characters that prefixes the bound or the
working-tree digest. By design, links minted before the change are refused as snapshot mismatches (the
tag moved from `9cc348bd` to `9580aa09`). **F5 is not re-graded here** (O23).

### O18. Motion-inventory residuals — CLOSED (moved from Open, 2026-09-23); the keyframe-scanner proof below did not hold at `443a05a` (re-grade) and was restored in wave 4 (R61)
Both items are done. `src/ui/primitives.tsx:1693` (Skeleton comment) now says "looping animation that
runs in this product" (verified). The dead `.stage-pending__spinner` / `@keyframes stage-pending-spin`
CSS was deleted (a comment at `App.css:343` records it) and the §4.8 row with it. **Pinned by**
`motion-inventory.test.ts` "no stylesheet declares an unbounded loop and nothing renders the deleted
spinner…" and its first test, which proves the keyframe scanner live on a planted stylesheet — re-run
green. **Contradicted at `443a05a`** by the re-grade of that commit: the scan's regex had lost its
escapes (`/@keyframess+([w-]+)/g`) and returned `[]` against the planted `@keyframes
stage-pending-spin`; it hid nothing, because `src/` declares no keyframes. Wave 4 restored it with a
known-answer case that fails on the de-escaped form (R61).

### R26. D3 — focus fell to `<body>` after the snapshot popover, and on every Inspector close path — FIXED
Found by the acceptance grading (D3: popover, Tab, Escape → `BODY`; `Header.tsx:479` fell back to
`e.currentTarget.blur()`). Cause, established by the focus-return cluster from history: wave 1 added a
Tab-out handler to the Popover primitive (`primitives.tsx:1064–1088`, absent in `50a3dc5`); Tab off the
panel's last control closes it and focuses the query input, whose focus event records the popover's
Copy button as origin; that button unmounts, and Header's latent blur arm fired. The rewritten runtime
audit then found a second, unreported path: the Inspector's close (`focusReturn?.focus()`, no fallback,
origin recorded only by `openInspector()`) landed on `BODY` in 24 of 210 cases — every close of an
Inspector opened with `i`, and two citation-opened cases.

**Fix.** One owner, `src/app/focus-return.ts`: the recorded target, else its opener (captured through
`aria-controls` at record time), else explicit fallbacks, else the labelled region landmark; it never
blurs. Every decider routes through it — verified in code: `Header.tsx:481`, `DataGrid.tsx:895`,
`Inspector.tsx:695–705` (invoker recorded on every open path; returns only when focus is on `<body>` or
null, so closing by moving focus elsewhere is not overridden; `#stage` fallback), `keyboard.ts:537/540`,
`CommandPalette.tsx:259/455`, `StatusBar.tsx:136`, and the Dialog cleanup at `primitives.tsx:1314`.
`PENDING_ROUTING` in the guard is empty (`focus-return.guard.test.ts:367–370`).

**Pinned by** `src/app/focus-return.guard.test.ts` (one `ts.Program` over the vitest include globs with
a partition check, symbols resolved rather than names; rejects `blur` calls, un-owned `isConnected`
fallbacks and `.focus()` on a captured `activeElement`/`relatedTarget` origin; a shrink-only ratchet),
`Header.focus-return.test.tsx` (3), `DataGrid.focus-return.test.tsx` (3), `Inspector.test.tsx` "closing
the Inspector never drops focus to <body> (D3)" (3), two D3 tests in `CommandPalette.test.tsx` and one
in `coverage-focusout.test.tsx` — all re-run green. The runtime audit `review/audit-d3-focus.mjs` was
rewritten (5 states × 2 viewports; a case that did not open is NOT DRIVEN and fails; every required
kind must be driven) and re-run by the reconciler on the scratch build: `210 case(s), 0 failed.`,
`Driven, by kind: dialog=8 popover=105 field=32 grid=16 tab=33 find bar=6 inspector=9 copy=1`, exit 0.
Reported: 24 failures before the Inspector change, 40 with the Header regression re-planted; reverting
Header turns 3 tests red, reverting `DataGrid.leaveGrid` turns 5 red.

**Recorded alongside.** No toast component exists in this build (the old audit counted the visually
hidden `#sr-alert` live region as one). `DataGrid.leaveGrid` is not reachable from the running findings
queue, because `PriorityQueue`'s `onEscape` consumes every Escape; the grid tests pin the grid's
contract for hosts that let Escape through, and the comments now say so. The Dialog deliberately
returns to a bare element, not an opener fallback, which would pre-empt the palette's own landing. The
agents' D1/D2 re-drives (36 unique stops, no trap; one `tabindex=0`, `aria-rowcount` 152) are
reported. D3 is not re-graded here; no real screen reader was used.

### R27. B1 — four surfaces bypassed `presentBand`, and the `is:healthy` note misattributed its undecided rows — FIXED
From O12's B1 residual (acceptance B1 FAIL: `is:healthy` answered yes for five qualified hosts). The
surface fix landed in the interrupted wave 2 and was committed in `254694b`; wave 2c verified it and
fixed a new defect. **Structural guard:** `src/core/band-read.guard.test.ts` resolves every read of
`Device.band` with the type checker and allows it only in `band-qualification.ts`; its liveness test
plants a module that reads the band under any name, by destructuring or laundered, and it is flagged.
Reported mutations: raw reads planted in `query.ts` turned the guard and three behavioural tests red; a
destructuring rename and an optional element access planted in `PriorityQueue.tsx` were flagged.
**New defect, found live:** the Findings note said "14 of 146 name no device the fleet knows", true of
F142 only; the other 13 name qualified hosts whose own answer is undecided. `query.ts` now splits the
count, `ClauseScope` carries `undecided`, and the note says no device is *decided* to match. **Pinned
by** `query.band-qualification.test.ts` ("is:healthy answers no qualified host with yes",
"-is:healthy does not turn the qualified hosts into a decided no either", "the is:healthy note over
findings says WHY rows are undecided…"), `band-read.guard.test.ts` and
`band-qualification.surfaces.test.tsx` — re-run green. Reported red before: `expected '14' to be '1'`.
The running-app checks (chassis `E*`, legend "Excellent, partial · 2", palette pill "Excellent
(partial)") are reported from the agents' frozen-build screenshots. B1 is not re-graded here.

### R28. C2 — identifier splits, an overrun, a hidden tab and identical placeholders, and a detector that could not see them — FIXED; R25's "72 of 72" superseded, then re-established under the wider detector, which the re-grade found blind to scroll-port clipping (closed in R46)
Found by the acceptance grading (C2: `(num_power_supplie / s)`, Raw tab off the pane edge, both IP
placeholders `10.0.10.50`). Wave 2c found more of the same class once the detector could see it:
`acls.core1.PROTECT_SERV / ERS[3]` and `collection_completenes / s` in citation paths (dark and light,
1440, states 06 and 08), and `(num_power_supplies)` running 4.9 px past its not-observed box once it
could no longer split.

**Fixes.** Prose blocks carry no token-break licence; a licence is allowed only with an
`UNBREAKABLE-TOKEN CONTAINER` justification (`primitives.css` "wrapping"; kept on `.hop__raw` and
`.insp-sha`), and nine unjustified licences in `PathTrace.css`, `PriorityQueue.css:771` and
`App.css:455` were removed. `Cite` renders a `<wbr>` after each identifier separator
(`primitives.tsx:1733`, used at `:1768`; text and `aria-label` unchanged). `.ui-notobs__why` lost its
`min-inline-size` floor below its longest token. `.ui-tabs` wraps with a thin visible scrollbar as
backstop. `PathTrace.tsx` derives `EXAMPLE_ADDRESSES` — source `10.0.10.50`, destination `10.0.30.10`
from a different observed subnet — and each validation message names its own field's example.

**The detector.** `readTextFidelity` now flags a break inside any whitespace-free token with no boundary
character beside it, a split exactly between two text nodes (a `<wbr>`, `<br>` or atomic inline between
them is sanctioned), and a line that overruns its block's content edge. `node review/capture.mjs wrap`
statically fails every unjustified licence, and `selftest` runs 17 known-answer cases; `text` cannot
PASS while a detector is blind. **Pinned by** `primitives.test.tsx` (`Cite`: 2 tests) and
`PathTrace.test.tsx` ("the flow form's example addresses": 4) — re-run green — and by the harness,
re-run by the reconciler on the scratch build: `wrap` 0 unjustified, `selftest` 17 of 17, `text` 72 of
72, exit 0. Reported: `text` 68 of 72 and `wrap` FAIL 9 before the cross-cluster changes; re-injecting
each old rule brings its finding back.

**R25's wave-1 "PASS 72 of 72" is superseded:** it was measured with a detector that exempted
identifiers, node-boundary splits and overruns. The 72 of 72 above is the first measured with them.
During the wave the official `twice 5` read NOT ESTABLISHED (text findings count as render failures);
the gate reports `F6 PASS: 32 of 32 frames byte-identical across 5 runs` once `Cite` landed — reported,
not re-run by the reconciler. Descender clipping remains undetected (O17).

**Found blind again at the re-grade of `1d19e22`:** the 72 of 72 above could not see a control clipped
by its own scroll port (the path form at 1440 and 1920). `readFormReach` closed that in wave 3 (R46).

### R29. C6 — the emphasis, hover and halo fades were exponential and settled in 417–1,350 ms; the tier fade sat at 300 ms; the inventory could not see rAF eases — FIXED
Found by the acceptance refuter (C6 overturned to FAIL). **Fix.** `src/fabric3d/emphasis.ts` owns
finite eases — `RECEDE_MS = 240`, `HOVER_MS = 80`, `SELECT_MS = 140` (verified at `:76–80`) — that land
exactly on their target on the first frame at or after their duration and snap under reduced motion;
`TIER_FADE_MS = 280` (`scene.ts:2347`), so its end state shows before 300 ms at 60 Hz. §4.8 rows state
each duration and its settle time at 60 fps (250 / 83.4 / 150 ms). Mid-ease values depend on frame timing; the
settled value does not, because `easeValue` returns the target itself — which the `determinism:` notes
on `stepEaseChannel` and `stepEmphasis` state, and `determinism.test.ts` accepts.

**Pinned by** `src/core/motion-inventory.test.ts` (steps every exported ease against its §4.8 row; a
TypeScript-compiler scan that fails any exponential per-frame step — `x += (t-x)*k`, `k = f(dt/*_MS)`,
`damp()`, `x = lerp(x,…)`, and, widened in the continuation pass, the in-place `v.lerp(t,k)` /
`q.slerp(t,k)` spelling unless the receiver is a call chain or re-initialised in the same function),
`src/fabric3d/emphasis.test.ts` (settle within the `RECEDE_MS` row; bit-identical landing under
steady, jittery and coarse frame timing) and `determinism.test.ts` — re-run green. Reported red before:
"the recession settled at 1333.3 ms; §4.8 states 250 ms" and "TIER_FADE_MS = 300 ms can first show its
end state at 316.7 ms". The motion harness's fade item passed 24 of 24 at 266.5–266.7 ms (reported by
the agents; the orchestrator's `capture-motion` run shows it passing). The gate limit it exposed is O22.
The eases and settle times above stand; what the re-grade of `1d19e22` contradicted was the rest of
the §4.8 inventory this entry treated as closed (R24's note, fixed in R49).

### R30. C5 — label popping (O16's label half) — FIXED
Found by the C5 motion harness (O16: 29–31 label blinks, clustered at fly-to starts). **Fix.** Every
per-label show/hide decision over time goes through `labelResolve.ts` `labelDwellVerdict` (minimum
dwell, no appearing while the camera moves, a one-pass hold, urgent labels exempt) for both the scene
resolver and the DOM declutter; a hovered label is urgent only on a still camera (`labelUrgent`, and
`scene.ts:1874`). The settled pass (history-free, for F6) can no longer reverse a label younger than the
dwell: the resolver requests frames while it would (`labelSettleMayReverse`), and the DOM layer reports
`reportLabelsConverging`, which `scene.ts` now folds into `labelsSettled()` and `converged()` —
verified at `scene.ts:1587`, `:3366`, `:3637`, `:3641` (applied by the gate). **Pinned by**
`FabricLabels.dwell.test.tsx` (10, including DOM-vs-resolver parity and "a name that left in a move
shorter than the dwell does not blink back when the scene settles"), `labelResolve.test.ts` (the
settle-reversal tests), `FabricLabels.settled.test.tsx`, `render-c5-*.test.ts` and five
`scene.test.ts` tests — re-run green. The `scene.test.ts` five are **source-text tripwires**, not
behaviour: they check that `scene.ts` declares and reads the report, and the behavioural contract lives
in the DOM test's fake scene. Reported: `label blinks 0` in all 24 `capture-motion` sequences (agents
and gate) and 0 in 36 frozen-build probe sequences, down from 31; one DOM trade on the shared, HMR-edited
dev server did not recur and is not authoritative. Informational, no change: scene label age advances
per resolver pass while the DOM's advances per rAF.

### R31. C5 — the "z-fighting" clusters were not depth ties; three geometry sources removed — FIXED (what then still failed was edge shimmer, O16 — fixed in code in wave 3, measured PASS in the re-grade of `443a05a`'s laboratory run, and PASS with every C5 item in one independent run at `70bea72`, R60)
A per-frame camera replay and a raycast of every flip-flop cluster found no ray crossing two chassis
surfaces within 0.02 units (reported). Three sources were isolated and removed: the faceplate frame's
top bar seen from above (a body-painted hood, `chassis.ts`); overlapping `LineMaterial` round caps at
cable joints (discarded inside a cable, `cables.ts`); and one true coplanar overlap, the distribution
role glyph's crossing arms. **Pinned by** `src/fabric3d/geometry/chassis.coplanar.test.ts` (every
chassis part, role glyph and state ring checked for same-facing overlaps within 0.002, a from-above
check that the front edge is paint, and a liveness case) and `cables.ink.test.ts` "every cable stroke
discards LineMaterial's round cap…" — re-run green. The app `tsc` error this new test briefly caused
(TS2459, `QualityTier` not exported) is gone: it imports from `../contract`. Reported: mutations M6/M7
(hood removed, equal arms) turn it red; the cap discard's outer-bend notch was measured at worst 1.23°,
3e-4 px deep — a measurement not re-run. Also recorded: the A5 grader's camera-proxy coordinates could
not be reproduced with the agents' metric; double-click still moves to core1 and Reset returns to the
same rest projection (no camera code changed).

### R32. C5 — light-theme links read as ~1 px — FIXED in code; the width figures are reported, not verified
Root cause (reported): edge coverage was blended in the linear HDR buffer before the AgX tone map, so on
the light stage a half-covered pixel landed only 16–18 % of the way to the ink. **Fix:**
`coverageGamma(tokens)` (`cables.ts:207`), fitted through the real AgX curve over every `classifyLink`
token and applied to every cable batch, trace stroke and the ghost wireframe. **Pinned by**
`cables.ink.test.ts` ("the defect is real without the correction…", "every cable material the fabric
builds applies the palette's gamma…") — re-run green. **Not verified:** the painted-width figures (light
2 px class median 1.96 / p10 1.84 against dark 1.88 / 1.74, from a perpendicular probe that also showed
the earlier scanline p10 1.89 was angle-confounded) come from a probe in the orchestrating session's
scratchpad; there is no browser gate for stroke width. **Status at `78bdba5`:** the re-grade of
`70bea72` left open whether its C5 sub-2 px hairline was this class; wave 5 identified it as a different
mechanism — depth writes from unpainted quad fragments cutting a 2 px rail, in both themes (R68). The
floor is now enforced at the factory and pinned in jsdom by `stroke-floor.test.ts`, and
`probe-fabric.mjs --hairline` is a browser detector for one-device-pixel ink (reported runs only); it
detects slivers, not the painted width these figures measured, so they are still not verified.

### R33. F2 test quality — a tautological tamper test, an unpinned guard, a mislabelled test, and a label test that pinned nothing — FIXED
Found by the acceptance grading (F2) and, for the last, by the band/labels cluster.
`provenance.test.ts`'s tamper test now goes through the gate `fileIsCompilerOutput` ("detects a
hand-edited acl-bindings.json — the failure path, through the same gate"). The `claims.ts:470`
empty-hop guard became dead code on every input after R34 and was removed (a comment at `claims.ts:477`
records where the rule lives); "an EMPTY traversal earns no badge above INDETERMINATE under any outcome
word at all" pins the rule. `claim-honesty-b1.test.tsx:145` is renamed to what it proves ("the undecided
denial is offered no nearby flow at all…") and asserts its premise `ce.found === false`. And
`Fabric3D.test.tsx` "keeps a name off the chassis bodies the scene PROJECTS…" accepted
displaced-or-withheld after one frame, so under the two-pass hold its displaced branch never ran (it
stayed green with a name's own chassis made non-blocking); it is now three tests — withheld, a control
without core2's body, and "displaces a name one row UP…". All re-run green. The mutations that go with
them are reported, except the claims ones, which `mutation-check.mjs` executes.

### R34. `claimBadge` awarded SCOPED to an unrecognised outcome word (a C2/C3 follow-up) — FIXED; F3 gains an executable mutation run
Found by the provenance cluster following the acceptance report's open question: over ordinary,
fully-modelled hops, an outcome word the engine does not know earned SCOPED while `bandOfTrace` said
UNDETERMINED. **Fix:** `claimBadge` returns INDETERMINATE for any outcome whose `bandOfOutcome` is
UNDETERMINED. **Pinned by** `claims.test.ts` ("an unrecognised outcome word over a clean, fully-modelled
traversal is INDETERMINATE, not SCOPED", the zero-hop case, and a sweep over every UNDETERMINED word) —
re-run green; reported red before, `expected 'SCOPED' to be 'INDETERMINATE'`.

**F3 evidence.** `node review/mutation-check.mjs` copies the tree to a scratch directory and reverts
every recorded guard of every engine `refutation.md` names, plus two O15 guards. Re-run by the
reconciler: 18 of 18 KILLED (engine 4, blast 2, layout 2, query 1, compile-snapshot 2, claims 5,
source-binding 1, bindings 1), exit 0, printing its own LIMIT — it does NOT recreate pre-fix history.
`refutation.md` §6/§7 now record C2 as FIXED (verified at `:229` and `:341`). Separately, `254694b`
committed tests written ahead of their fixes red (provenance 8, motion-inventory 4, determinism 1,
source-hygiene 1, per its commit message; not re-run at that commit by the reconciler), so for those
tests "failed before the fix" is now in history. F3 is not re-graded here.

### R35. D8 refuter question (state 06: "on core1 denies this flow" beside "? UNDECIDED") — NOT A DEFECT, now pinned
Raised by the acceptance D8 refuter and assigned to no group. The 3-D chip's ending (`traceMarkOf`), the
claim card and the hop list read the same claim owner (`bandOfHopIn` / `bandOfTrace`); "denies this
flow" is the ACL line's evidence quoted inside a card that says "That denial is not decided". A pin in
`claim-honesty-b1.test.tsx` for 10.0.10.50 → 10.0.30.10 tcp/3389 (raw outcome denied, band
UNDETERMINED, mark undetermined, card matches /not decided/) is green. Reported mutation: forcing
`traceMarkOf` to "blocked" on a denied outcome gives 2 failures.

### R36. `--sev-high` brief drift was 31 drifted colour tokens — FIXED, and now guarded (O20's first item)
The motion cluster found that design-brief §3.3 had drifted from `src/core/tokens.css` on 18 light and
13 dark tokens, not only `--sev-high`, and reconciled all 31 (the chip table and canvas-contrast rows
recomputed; tokens.css named authoritative). Its report said no test guarded it; the merged-tree gate
then added one: `contrast.test.ts` "design-brief §3.3 restates tokens.css exactly" (every
`--token:#hex` in §3.3.1 and §3.3.2 and the severity-chip fills) — 3 tests, re-run green. Reported
mutation: writing `#a14a0a` back into the brief turns it red.

### R37. E1/E3 harness gaps and the E5 probe placement — FIXED in the harnesses; the runs are reported, not verified
Found by the acceptance grading (J1's verify spent the first selection; J4's verify ran before the
measured act) and O20 (E5 probes at fixed times; an unsanctioned pre-FCP carve-out). **Verified in code
only:** `review/measure-inp.mjs` checks each rep's effect after its timing (`repEffects`,
`repsWithEffect`, `verifyAfter` on the journeys that spent their first act), and
`review/audit-e5-coldload.mjs` aims probes at earlier runs' long frames, reports `keystrokeCoverage`,
and applies the pre-FCP carve-out only if `docs/acceptance.md` holds a line beginning
`E5 EXEMPTION (owner-sanctioned): pre-first-paint` (`:137`; no such line exists, see O20). **Not
verified:** the runs — J4 with its submit removed reads PASS on the old harness and NOT MEASURED on the
new; `6 pass, 0 NOT MEASURED` with 25 of 25 verified effects; E5 now failing on a 264.7 ms pre-FCP frame
and 14 slow keystrokes. Every one was on a busy host on battery, which the harness itself refuses as
acceptance evidence. E1–E5 are not re-graded.

### R38. Stale documents and a type doc comment — FIXED
From acceptance-report item 7 and B2's type drift. Verified by reading: `docs/acceptance.md` E3 (`:82`)
gives resizes 105–149.7 ms and eleven classes over 50 ms, with the eight input-handler classes marked
outside E3's claim (O21); the F5 row describes the LF-normalised binding and moving `fabric.json`
digests (`2f558c38…a308` now, matching `sha256sum`); F1 reads full strict (the reconciler's run of both
`tsc` configs exits 0, see the banner); F3 cites `mutation-check.mjs`. `refutation.md` §6/§7 are
corrected (R34). `types.ts` documents `claim` as prose of two or more sentences (comment only).

> **Acceptance-close wave 1 (reconciled 2026-09-22).** Entries R16–R25 below, and O10–O20 under
> Open (O10, O15 and O18 have since moved to Resolved, above), record the "Known issues carried forward" list of `docs/acceptance-report.md` and what four
> parallel repair lanes (claims-engine, fabric-surfaces, layout, compiler-evidence) say they changed.
> Each lane's claim was checked before it was written here: the code named was read at the line
> given, and the named tests were re-run by the reconciler in one invocation (16 files,
> `Tests 1 failed | 228 passed (229)`, the one red being `tracked-sources.test.ts`, see O10). The
> merged-tree gate after the wave: both `tsc` configs exit 0; `npx vitest run` exit 1 with
> `Tests 1 failed | 1415 passed (1416)` (tracked-sources only); `npm run build` exit 0;
> `node review/capture.mjs app` exit 0 (32 of 32 frames). **Mutation checks ("red again when the fix
> is removed") are the lanes' own reports and were NOT re-run by the reconciler**, which was barred
> from editing product source or tests; they are cited as reported. Nothing below is a criterion
> re-grade: a fixed defect does not by itself turn its acceptance criterion PASS.

### R16. F3 / refutation C2 — `claimBadge` never cross-checked the outcome against the hops — FIXED
Found by the acceptance grading (F3): refutation claims-C2 was "CONFIRMED and NOT fixed", and a
delivered trace whose only hop was a loop returned SCOPED. Reproduced by the claims-engine lane.

**Fix.** `src/core/claims.ts:217` `hopsSupportOutcome(trace)` (read through `bandOfHop`): no hop may be
undetermined, the last hop must band the same as the outcome, and a delivered outcome needs every hop
RESOLVED. Both callers use it — `isDecidedOutcome` (`:230`, which feeds band, tally and counterexample)
and `claimBadge` (`:475`, returns INDETERMINATE). Verified in code.

**Pinned by** `src/core/claims.test.ts`, block `REFUTED (C2)` (~line 342): a loop-only delivered
trace, every non-supporting hop verdict, a refused hop before the path's end, and a control that
really reaches SCOPED. Reported before the fix: `Tests 5 failed | 29 passed (34)`; after: 34 passed
(re-run by the reconciler: green). Reported mutation: `hopsSupportOutcome` → `true` gives
`4 failed | 30 passed`. A real-trace sweep reportedly changes no real trace's badge.

The stricter denial rule the lane declined is recorded as an owner decision in O11.

### R17. B8's only real near-miss rested on an outbound ACL applied to traffic addressed to the router — engine FIXED (B8 itself stays UNPROVEN, see O13)
Found by the acceptance refuter (B8): 10.0.10.50 → 10.0.30.1 was "denied" on tcp/3389 and "delivered"
on tcp/22 by `PROTECT_SERVERS`, which is bound *outbound* on core1 Vlan30 — but 10.0.30.1 is core1's
own Vlan30 address, so the packet is received, not forwarded out of Vlan30. The engine refused
router-owned *sources* and had no matching rule for router-owned *destinations*. Reproduced by the
claims-engine lane: of 12,059 swept flows, 2,542 denied or dropped, exactly 4 with a counterexample,
all to 10.0.30.1, all resting on this misattribution.

**Fix** (`src/forwarding/engine.ts`, same address-ownership index as the router-owned-source rule;
verified in code): `receivedAtOwner` (`:1759`, called `:2078`) — when the current hop owns the
destination, only its observed *inbound* bindings are evaluated; an observed inbound deny stays a
decided denial; anything else is an "unmodeled" hop with an indeterminate outcome whose claim says the
packet is received by the router and that control-plane/management/service ACLs are not modelled.
`receivedElsewhereEvidence` (`:1847`, used `:2208`) — when another collected device owns the
destination, a pass onto the connected subnet is no longer "delivered"; a transit outbound deny still
stands.

**Pinned by** `src/forwarding/router-destined.test.ts` (new): derives owned addresses independently
from SVI, FHRP virtual and `local` /32 records and sweeps every source subnet against every owned
address, with a control that transit traffic to 10.0.30.10 is still decided by `PROTECT_SERVERS`.
Reported before: 4 failed (e.g. `expected [ …(140) ] to deeply equal []`); after: 6 passed
(re-run: green). Reported mutation: removing both rules gives `4 failed | 2 passed`. In the running
app (lane's screenshots) the 10.0.30.1:3389 card changed from "denied at core1 by ACL PROTECT_SERVERS"
to an INDETERMINATE sentence naming core1 Vlan30 as the owner.

### R18. A2 (depth 1) — the hop header blamed routing for an ACL denial — FIXED
Found by the acceptance grading (A2): on tcp 10.0.10.50 → 10.0.30.10:3389 the hop header read
"denied by routing — table incomplete" (`HopList.tsx:120`) while the decider block said
`PROTECT_SERVERS` line 4. Two sentences about the same hop, from two sources.

**Fix.** `src/panels/HopList.tsx:118` `deciderAgent` takes the agent from `classify(hop.decidedBy)`,
the source the decided block uses; `UNDECIDED_WORD` takes that decider. The header now reads "denied
by ACL PROTECT_SERVERS — reached by a route from an incomplete table". Verified in code.

**Pinned by** `src/panels/HopList.decider-header.test.tsx` (new): the real flow, then every suggested
flow plus a source × destination grid, with preconditions that both ACL-decided and route-decided hops
occur. Reported before: 2 failed; after: 2 passed (re-run: green). Reported mutation: `deciderAgent`
returning "by routing" for an ACL fails both. The lane's "after" screenshot could not be captured (the
Browser pane stopped drawing); the after state was read from the page text. **A2 as a criterion stays
UNPROVEN**: multi-hop still cannot run on shipped data (max depth 1).

### R19. F2 — two hollow tests — FIXED; one out-of-scope defect exposed (O14)
Found by the acceptance grading (F2). `engine.counterfactual.test.ts:148`: its `toContain` loop ran
zero times because the rationale cites no ACL. `blast.test.ts:~400`: compared `f()` with `f()`.

**Fix.** The counterfactual test now checks both halves of its name behind preconditions (the
rationale cites exactly the ACL lines the candidate's own trace consulted — here none, and says "No ACL
line was consulted"; and none of the blocking host's candidate-generating permit lines is cited).
`blast.test.ts` gained a `repeatable()` helper that clones the first result, writes junk into it,
re-runs and compares against the clone, requiring non-empty results, plus a test proving the check can
fail (an aliasing memo passes the old form and fails the new). Both files re-run green by the
reconciler. Reported mutations: citing the candidate-generating line (the historical bug) fails with
`expected [ 'acls.core1.VOICE_FILTER[0]' ] to deeply equal []`; removing the junk-writing step fails
the second blast test.

### R20. F1 — `tools/compile-snapshot.mjs` was clean only with `noImplicitAny` relaxed — FIXED
Found by the acceptance grading (F1): `npx tsc -p tsconfig.scripts.json --noEmit --noImplicitAny`
reported 18 errors (12 TS7006, 6 TS7053), all in the compiler, hidden by `"noImplicitAny": false`;
`scripts-typecheck.test.ts` pinned the residual rather than removing it.

**Fix.** JSDoc types only in `tools/compile-snapshot.mjs`; `tsconfig.scripts.json:36` now
`"noImplicitAny": true`. **Pinned by** `src/core/scripts-typecheck.test.ts`, rewritten to require the
config not to relax the flag and to build a program with it forced on that must report nothing.
Verified: the reconciler ran `npx tsc -p tsconfig.scripts.json --noEmit` (exit 0, flag now on) and
the test (green). The lane reports `fabric.json` byte-identical across this change (`fce33d24…0da8`
before and after); the later A1 change (O12) then moved it deliberately.

### R21. D1 — no keyboard orbit or pan on the fabric canvas — FIXED
Found by the acceptance refuter (D1, overturning a first-pass PASS): 25 keys on the focused canvas
gave `changed=false` while a 300 px drag rotated the view ~90°.

**Fix.** Shift+arrows orbit (one press = a drag of 1/18 canvas height, 15°), Alt/Option+arrows pan
(1/16); plain arrows still move the selection. `camera.ts` `orbitBy`/`panBy` (declared `:383–385`)
drive the same three.js OrbitControls handlers a pointer drag does, so there is no second camera
model; one key table `src/fabric3d/canvasKeys.ts` feeds the handler, the canvas's `aria-keyshortcuts`
and a new "3-D fabric canvas" section on the `?` sheet. Post-drag drift is now off under reduced
motion for mouse and keyboard alike. **Pinned by** `src/fabric3d/camera.keyboard.test.ts` (key move vs
a simulated real drag, full and reduced motion), new cases in `Fabric3D.test.tsx`, and
`src/fabric3d/canvasKeys.help.test.tsx` — all re-run green by the reconciler; reported red before
(`rig.orbitBy is not a function`, `no canvas-keys section on the sheet`). Reported mutation: no-op rig
verbs turn 5 of 6 camera tests red (the sixth, "reduced motion leaves no drift", is also satisfied by
a camera that never moves — a known weak test). **Maintenance risk:** the handlers are
underscore-named in three 0.186; re-check on any three upgrade. The C5 motion run (O16) used this path
live: worst frame gap 200 ms during Shift+Arrow orbit.

### R22. D6 — links L34 and L35 were drawn "state not observed" but listed as "centrality not computed" — FIXED
Found by the acceptance refuter (D6 note). Both statements were true (no observed state, so not in the
connectivity graph, so null centrality) but the row carried only the consequence.

**Fix.** `geometry/cables.ts` `classifyLink` records what each drawn pattern claims in the branch that
picks it; `FabricA11yTree.tsx` `linkCutMeta` adds any drawn claim the row text lacks. L34/L35 now read
"state not observed · centrality not computed"; no other link's row changed. **Pinned by**
`src/fabric3d/link-encoding.parity.test.tsx` (all 44 links: every claim the drawn pattern makes must
appear in the list row) — reported red before (`expected 'centrality not computed' to contain 'state
not observed'`), re-run green by the reconciler.

### R23. D7 — the reduced-motion gate crashed before reaching a verdict — FIXED (no lane claimed it)
Found by the acceptance grading (D7): `TypeError: o.settleProblems is not iterable at captureReduced
(capture.mjs:725)` → EXIT=1; the call site passed no `t0` and took `{settle, problems}` as the array.

None of the four wave-1 lanes reported this fix, but the code has it: `review/capture.mjs:1159–1160`
now sets `t0` and destructures `{ problems: settleProblems }`, with a comment naming both halves of
the old defect. **Verified by running the gate** (reconciler, 2026-09-22, against the :4181 build):
`node review/capture.mjs reduced` → `PASS  D7: camera lands in one frame under reduce, 24 poses
without it.` exit 0 (reduce: `--dur-camera=1ms cameraPoses=1`; control: `.62s`, 24 poses). The gate is
its own evidence; there is no unit test pinning the call-site contract.

### R24. C6 — the §4.8 motion inventory omitted the spinner and the tier cross-fade — FIXED for those two rows (the dead CSS it found was deleted in wave 2c; O18 closed); the inventory as a whole was found false at the re-grade and rebuilt in wave 3 (R49)
Found by the acceptance grading (C6): a 900 ms infinite spinner (`App.css:349`) and the 300 ms tier
fade (`TIER_FADE_MS`) were missing from §4.8, and `App.css` and `flow.ts` each called their own
animation "the only looping animation". The lane also found that no component renders
`.stage-pending__spinner`, so the spinner never runs.

**Fix.** `docs/design-brief.md` §4.8 gained rows for both (verified at `:813–814`, each with duration
and reduced-motion behaviour); the `App.css` and `flow.ts` comments were corrected. **Pinned by**
`src/core/motion-inventory.test.ts` (new) — it derives animations from the code (every `@keyframes`,
every `*_MS` constant put into an inline `transition`), requires §4.8 to name each, and requires the
spinner to remain unrendered. Reported red before (4 failed, e.g. `@keyframes stage-pending-spin is
not in §4.8`); re-run green by the reconciler.

**Contradicted by the re-grade of `1d19e22`.** The test derived keyframes and inline `*_MS`
transitions only, never CSS `transition:` declarations, so §4.8 still claimed an 18 ms per-hop stagger
and a 140 ms palette animation that do not exist and omitted about eight running transitions. Fixed in
wave 3 (R49).

### R25. B1 (six surfaces), B7, C2, C3, D4 — health-band qualification and layout-fidelity defects — FIXED on the surfaces named; the B1 residual fixed in R27, layout residuals in O17; the 72-of-72 text PASS superseded (R28)
**B1** (acceptance grading): a favourable band on a host with unassessed scoring domains was qualified
only in the Device pane. The fabric-surfaces lane reproduced it on five hosts (podacc1, podacc2
Excellent; core2, dist1, dist2 Good) and moved the rule to one owner, `src/core/band-qualification.ts`
(`presentBand()`), now called by the Device pane, the canvas announcement, the Fabric list row, the
label chip ("E*"/"G*", grey, dashed), the legend (new "partial" rows) and the chassis/LED tint
(`scene.ts`) — verified by grep: exactly those six non-test modules import it. **Pinned by**
`src/fabric3d/band-qualification.surfaces.test.tsx` (states the rule independently and checks all six
surfaces against the hosts it covers) — reported `5 failed | 2 passed` before, re-run green. This file
briefly failed `source-hygiene.test.ts` (a test body with no direct `expect`); it now carries one and
the reconciler's run of `source-hygiene.test.ts` is green.

**B7, C2, C3, D4** (layout lane). The detector came first in name only: for B7 and C2 the fix was
written before the detector could see the defect, so their "before" evidence is mutation runs on
reverted CSS, not a test-first run. New `node review/capture.mjs text` mode (72 states: 8 capture
states + palette open, 390/768/1440/1920, both themes) with `readTextFidelity` (clipped / escaped /
column / mid-word), `readCoverageVisibility` (B7) and `readContrast` (D4); `captureApp` runs the text
and coverage checks on every frame. Fixes: B7 — the coverage group wraps and only `.sb__rest` scrolls,
the bar sits above panels (`StatusBar.tsx`, `chrome.css`, `shell.css`); C2 — citation/"not observed"/
select/chip rules given one owner in `src/ui/primitives.css`, the duplicate `.pathtrace` rule removed;
C3 — comfortable-density titles wrap and clamp at 3 lines, category wraps (`PriorityQueue.css`); D4 —
the palette scope line shrinks and the footer wraps (`CommandPalette.css`), measured after at
5.05–6.75:1. Reported: `PASS text 72 of 72 states` after, exit 3 before; per-defect mutation runs
`FAIL 10 of 36` (B7), `2 of 54` (C2), `FAIL 0 of 36` (C3 — quoted as reported; the report does not say which count that is), `32 of 36`
(D4). Limits the lane stated: all measured on the :4180 dev server; the checker judges a line
visible by its vertical midpoint, so descender clipping is not detected (the clamp cutting descenders
was found and fixed by eye); citations now wrap everywhere, so rows holding one may be taller.
**Re-run by the reconciler, 2026-09-22, against the :4181 release build** (the lane had measured only
the :4180 dev server): `node review/capture.mjs text` → `PASS  text  72 of 72 states free of
clipped/broken text and with coverage wholly visible`, exit 0; palette-footer contrast min 5.05:1
(dark) and 5.7:1 (light) at every width.

**Superseded in part (2026-09-23).** The `PASS text 72 of 72` above was measured with a detector that
exempted identifiers, so it could not see the `num_power_supplies` split the acceptance grading then
found (C2); with identifiers, node-boundary splits and overruns detected, the tree first measured 68
of 72, and 72 of 72 only after wave 2c's fixes (R28, re-run by the reconciler on `1d19e22`). The B1
residual this entry left in O12 is fixed (R27).

### L1. The critique loop declared convergence on zero evidence — FIXED (review apparatus, not product)
The loop that drives the blind panel and the six specialist audits (it lives in the orchestrating
session's scratchpad, not in this repository) returned `{"rounds": 6, "converged": true}` on
2026-09-21. It had not converged. Every round-6 audit — a11y, perf, honesty, capability, integrity,
render — and the blind decode had failed with `API Error: Can't reach the API server (ENOTFOUND)`.
The journal records it: round 6 had 9 agents, 2 results and 7 failures.

The mechanism is this project's own defect class, inside the apparatus meant to catch it. A failed
agent resolves to `null`; the audits were collected with `(await parallel(…)).filter(Boolean)`, so
the six nulls vanished and `blockerFindings` became `[]` — "no audit ran" read as "no audit found
anything", and the gate `blockerFindings.length === 0` passed. Absence rendered as health. Round 5,
the last round that actually measured, had **5 blockers and 11 majors** open.

Fixed in the loop, not papered over: missing audits and a missing decode are retried under fresh
labels, then COUNTED against what was expected (`AUDITS.length`, `sheets × lenses`); any gap blocks
convergence and is logged as an evidence gap; a round where no audit returns at all aborts with that
reason rather than spending rounds "repairing" against nothing. The staged acceptance sweep had the
same `.filter(Boolean)` shape on its graders and refuters and was fixed the same way — an ungraded
group is carried into the report as UNPROVEN, and a PASS whose refuter never returned is reported as
unrefuted, never as "survived an attack". The invalid "converged" was never reported as a result.

Found at the same time: a round-5 parallel repair wave left `tsc -p tsconfig.json` failing
(`src/core/sticky-layer.test.ts`, three `noUncheckedIndexedAccess` errors) while each agent had
reported its own slice green. Fixed, and the loop now runs one post-wave integrity gate over the
merged tree (both `tsc` configs, `vitest`, `npm run build`, a clean console) from round 6 on.

### R14. A standing draw-call breach, invisible in production — FIXED
Measured 2026-09-21 in a real browser (ANGLE → Intel D3D11, 1920×1080, `high`, 40 consecutive rAF
samples per state): every path-trace state rendered a **steady** 141-draw-call frame against a flat
declared ceiling of 120. `min === max === 141` at `converged: true`, with 75 consecutive breaching
frames against an `OVER_BUDGET_FRAMES` threshold of 2 — a standing breach by the code's own
definition, not a rebuild transient. It was reproduced independently by the capture harness, which
recorded `drawCalls: 141` for `06-path-blocked` and `08-path-indeterminate` in
`review/shots/app/index.json`.

**It was unreachable.** `overBudget` was set on an internal flag, was not on the `SceneStats` the
frozen `contract.ts` declares (8 fields declared, 15 returned at runtime), had zero consumers
outside `scene.ts`, and its only report was a `console.error` behind `import.meta.env.DEV` —
`grep "exceeds the budget of" dist/assets/*.js` matched nothing in any shipped chunk. The product
breached its own published budget continuously, in front of the user, and said nothing.

Two in-code claims were false and are corrected: `scene.ts` said the ~124-call rebuild frame "is
the only frame that approaches 120", and `layers.test.ts` said "whether a real frame stays under it
is measured in the browser (74 calls at `high`)". The 74 was measured with nothing selected and
generalised to "a real frame".

**The cost was mis-modelled, not mis-measured.** A composed frame is a base plus a surcharge per
`OutlineEffect` that currently has a non-empty selection — postprocessing's `OutlineEffect.update()`
re-renders the whole scene into a depth buffer and the selection into a mask, guarded only by
`selection.size > 0`. The full sweep:

| State | Active outline effects | Draw calls |
|---|---|---|
| nothing selected, no trace | 0 | 74 |
| device selected | 1 | 103 |
| trace DELIVERED | 1 | 103 |
| trace DENIED / INDETERMINATE | 2 | 141 |
| denied trace **and** a device selected | 2 | 141 |

The delivered-trace row is identical to the plain-selection row, so the trace geometry costs **zero**
extra draw calls; the whole +67 was the second outline effect. One flat number can only ever be
right for one of those frames, and 120 was set on the idle one.

Fixed by replacing the flat ceiling with the model: `DRAW_CALL_BUDGET_BASE` (88) +
`OUTLINE_EFFECT_COUNT` × `DRAW_CALL_BUDGET_PER_OUTLINE` (44) = **176** published in
design-brief.md §4.4, with the render loop judging each frame against
`drawCallBudgetFor(activeOutlines)`. This TIGHTENS the common case — the idle frame is now held to
88 where it used to be waved through at 120 — while it stops lying about the rare one.
`layers.test.ts` asserts all three numbers against the brief, asserts the render loop reads the
per-frame ceiling rather than the total, counts the `new OutlineEffect(` sites so a third one cannot
be added for free, and pins every measured row with a ≤ 40% headroom bound so the budget cannot
drift back into being untrippable.

And it is no longer silent. `scene.ts` now returns `FabricSceneEx` — a SUBTYPE of the frozen
contract's `FabricScene`, proven conformant with `satisfies CreateScene` — so `overBudget`,
`drawCallBudget` and `activeOutlines` are named and type-checked rather than reachable only by cast.
`Fabric3D.tsx` shows a standing breach on the quality chip in **every** build: amber, reading
`141/120 draw calls`, with a tooltip naming the cost, the ceiling, how many outline effects were
active and that it is standing rather than a rebuild transient. Four tests in `Fabric3D.test.tsx`
drive both paths — clean frame unmarked, breaching frame marked, the mark clearing when the breach
stops, and a reduced tier reported as a different thing from a breach. Verified in the running
product by temporarily lowering the budget: the chip rendered `141/60 draw calls` in amber, then
returned to plain `Quality high` when the real numbers were restored.

Re-measured after the fix, all states: `overBudget: false`, 0 console errors.

### R13. The capture harness was red on every frame, and nothing ran it — FIXED
`node review/capture.mjs app` exited **3 on 32 of 32 frames**, in every run, because the draw-call
breach above flooded `console.error` and the harness counts a console error as a frame that did not
render. That harness is the designated verifier for everything `scene.test.ts` explicitly disclaims
— post-processing pass order, colour management, SSAO, bloom thresholding, shadow-map fitting,
measured frame rate — and `npm test`, `npm run build` and `tsc` all pass without touching it. The
entire visual-evidence corpus was failing and no gate a developer actually runs could see it.

Fixing R14 cleared it: re-run after the fix, **0 of 32 frames** carry a budget error and `grep -c
"exceeds the budget" ` over the harness log returns 0. (One frame was red in a re-run for an
unrelated reason: a concurrent editing lane had `FabricLabels.tsx` in a half-saved state, which is
what a live HMR capture looks like, not a defect in the harness.)

It is now reachable by name: `npm run capture` and `npm run capture:refs`. `docs/acceptance.md` F2
states the delegation explicitly — the harness's own exit code is part of F2's evidence, not an
optional extra. It is deliberately NOT chained into `npm test`: it needs a live server and a real
GPU, and making the unit gate depend on those is the flakiness `vitest.config.ts` was written to
remove.

### R12. `npm run e2e` was a declared gate that could never run — REMOVED
`"e2e": "playwright test"` with no `playwright.config.*` and no `e2e/` directory. With no config
Playwright globs the repository, tries to load every `src` unit test as a spec, throws
`Module "…/src/data/fabric.json" needs an import attribute of "type: json"` on each, and exits 1
with `No tests found`. `tsconfig.json` listed `"e2e"` in `include` for the same non-existent
directory; `--listFiles` returned 90 entries, every one under `src/`, not one under `e2e/`.

`@playwright/test` is genuinely installed and genuinely used — `review/capture.mjs` drives it
successfully. Only the gate was fiction. A script in `package.json` reads as a gate, and one that
has never exited 0 is worse than its absence because it makes the gate list look longer than it is.

Both removed: the `e2e` script, and `"e2e"` from `tsconfig.json`'s `include` (with a comment saying
why it is not coming back). The honest precedent was already in the tree — `tsconfig.scripts.json`
exists precisely because `"tools"` in an include list "READS as coverage and is not" — and the same
reasoning simply had not been carried through.

### R11. Two keyboard-help overlays, and a focus-return regression underneath — FIXED
The integration agent reported an overlap rather than silently resolving it, which was the right
call. `ShortcutHelp` was mounted twice: once by `App.tsx` (registry-driven, generated from live
bindings) and once privately inside `Header.tsx` with its own `?` handler and a hand-written
`OWN_SHORTCUTS` array — the thing design-brief §7.1 forbids.

**Both agents were reasoning correctly.** The Header one carried this justification:

> "A keyboard reference that lists a shortcut nobody wired is a false claim about the product, made
> in the one place a user goes when they are already stuck."

That is exactly right. It was written because Header installed `/` with a raw
`window.addEventListener`, so the binding never reached the registry and the generated sheet could
not see it. Each was a good local answer; together they were a defect.

**The real cause was narrower than it looked.** `commands.ts:533` already declares `query.focus` as
a capability bound to `/`, and `App.tsx:332` already registers the query input as its target.
Header's raw listener was a DUPLICATE of an existing capability, not compensation for a missing
one. My first fix added a registration in Header — which recreated the duplicate under a new name
and showed up on the sheet as "Focus the query bar: //" with two key chips. Removing the raw
listener was the entire fix; a surface that needs a key asks for the capability, it does not bind
the key itself.

**The regression this exposed, which matters more than the overlap.** `focusReturn.current` was set
inside Header's own `/` handler. With that handler gone, App's capability target focuses the input
directly — and **Escape stopped returning focus to where the reader came from**. Nothing caught it
but a test whose premise I had to unpick. Fixed by recording the return target on the input's
`focus` event instead, which is strictly better than the original: it covers every entry path —
the key, the command palette, a click, a screen reader — rather than only the one key that used to
set it.

Verified in the running application, not inferred:
```
help: {"sheets":1,"around":"Focus the query bar: /…"}
after '/': hdr-query__input | after Escape: probe-origin | returned: true
pageerrors: 0
```
Suite: 637 passing, 23 files, 0 typecheck errors. Pinned by `src/app/help-single-source.test.tsx`
(8 tests), including two that read `Header.tsx` and fail if either the private overlay or a
hand-written key list returns.

**A harness bug worth recording**, because it wasted an hour and will recur: `keyboard.ts` installs
its listener on `document`, and a test that dispatches `keydown` on `window` exercises NOTHING —
events dispatched on window do not travel down to document. Every key assertion fails for a reason
unrelated to the product. It is also why Header's old raw `window` listener appeared to work in its
own test while a correctly registered binding did not.

### R8. The INP harness reported PASS for a journey that did nothing — FIXED
`review/measure-inp.mjs` had never been run, so its own behaviour was unverified. Run against the
scaffold, four journeys correctly reported NOT MEASURED — but **J5 (open the command palette)
reported PASS at 16 ms with one sample, against an application that has no command palette.**

Its readiness selector was `body`, which is always satisfiable. The harness pressed Ctrl+K, the
browser dispatched a keydown that nothing handled, the Event Timing API duly recorded a 16 ms
interaction, and the journey passed. A latency figure for a no-op is not a fast interaction — it is
a missing one, reported as success. The same defect shape this whole application exists to prevent,
sitting in the instrument built to measure it.

Fixed with a per-journey `verify` hook that must prove the interaction has its intended EFFECT
before any timing is recorded. J5 now asserts a dialog or expanded combobox actually appears.
Re-run against the same scaffold:
```
NOT MEASURED J5-open-palette  [Cmd/Ctrl+K opened no dialog or combobox — the palette is absent or not wired]
0 pass, 0 fail, 5 NOT MEASURED
EXIT=1
```
The general lesson, and it applies to the other four journeys once the UI exists: a readiness
selector proves an element is PRESENT, not that the interaction WORKS. Only an effect check
distinguishes "fast" from "absent".

### R7. `npm run build` failed outright — FIXED
`vite.config.ts` declared `build.rollupOptions.output.manualChunks` as an OBJECT. Vite 8 bundles
with Rolldown, which accepts that option only as a FUNCTION, and fails with
`TypeError: manualChunks is not a function`. The object form is a Rollup-ism carried over out of
habit.

Nothing caught it because nothing had run the production build — `tsc` and `vitest` both pass on a
config that cannot bundle. Acceptance F4 (three.js code-split out of the entry chunk) was therefore
UNPROVEN rather than passing, which is the distinction `docs/acceptance.md` exists to keep.

Fixed with the function form, which also splits React out. Verified:
```
dist/assets/index-*.js   188.63 kB │ gzip: 17.60 kB
dist/assets/react-*.js   189.60 kB │ gzip: 59.61 kB
✓ built in 414ms
```
There is no `three` chunk yet only because the scaffold `App.tsx` does not import the 3-D subsystem;
it will appear once integration wires the fabric in, and F4 should be re-checked then rather than
assumed from this run.

### R5. The entire 3-D fabric rendered as a black screen — FIXED
`materials.ts :: withEmphasis` injected `totalEmissiveRadiance *= vColor.rgb;` into the fragment
shader whenever a material routed per-instance colour into emission. `vColor` is declared by
three.js's `color_pars_fragment` only under
`USE_COLOR || USE_COLOR_ALPHA || USE_INSTANCING_COLOR || USE_BATCHING_COLOR`, and
`USE_INSTANCING_COLOR` is set only when an `InstancedMesh` actually carries an `instanceColor` at
compile time. When it did not, the fragment shader failed with
`'vColor' : undeclared identifier` and **every mesh using that material drew nothing.**

The author's reasoning about *not* setting `vertexColors: true` was correct and is documented in
the file. The gap was narrower: the injection was unconditional while the varying it referenced was
conditional. Fixed by guarding the injected line with three's own declaration condition, so the two
cannot disagree however the mesh is built.

**Why nothing caught it, and this is the part worth remembering:**
- **The scene's own stats reported health.** `renderer.info` gave 28 draw calls, 55,935 triangles
  and 55.6 fps against a completely blank canvas, and `converged` went true. Absence rendered as
  health, inside our own instrumentation.
- **`scene.test.ts` cannot see it, by construction.** jsdom has no GL context, so no shader is ever
  compiled there. The suite was green the entire time — and the test file says so honestly in its
  header, which is exactly why that honesty matters: it told us where not to trust it.
- GL reports a shader failure to the console and then carries on rendering nothing.

The only thing that could find this was putting the renderer in a real browser and looking at the
pixels. `review/probe-fabric.mjs` now does that on demand.

### R6. The blank-frame detector cried blank on a working render — FIXED
`probe-fabric.mjs` first measured "did it draw" with `drawImage(canvas, …)` + `getImageData`. A
WebGL context created with the default `preserveDrawingBuffer: false` discards its drawing buffer
after compositing, so that read is always empty. The probe reported **"the canvas is NOT drawing a
scene"** about a fabric that was rendering correctly — which would have sent the critique loop
hunting a renderer bug that did not exist, and taught everyone to distrust the detector.

Fixed by measuring a real screenshot (composited as a user sees it) and decoding the PNG back
inside the browser. It now reports 840 distinct colours and 87.6 % non-black on the live fabric.

### R4. The data compiler silently discarded the producer's own verdicts — FIXED
Found by the adversarial refuter that ran against `cisco_toolkit.parse._acl_rule`, the real parser
this model compiles. `tools/compile-snapshot.mjs` emitted only
`action, raw, proto, src, dst, sport, dport` and **dropped five fields the snapshot carries**:
`unevaluable`, `unmodeled_qualifiers`, `established`, `icmp_type`, `time_range` — plus the entire
`object_groups` table and the `group` key on a match field.

Two distinct harms, and the second is the worse one:

1. **Parser-versus-detector drift.** With the producer's verdict discarded, the engine had to
   re-derive evaluability from the raw configuration text. Two derivations of the same fact can
   disagree, and when the consumer's is the more optimistic one an *unknown* becomes a *confident
   wrong answer*. The refuter demonstrated the concrete case: the producer emits
   `{"op":"eq","val":null}` for a port name it cannot resolve (`eq citrix`); compared numerically
   that is a definite non-match, so a permit line stops firing, the flow falls through to
   `deny ip any any`, and the engine reports a definite **denied — with zero indeterminacy
   caveats — for traffic the configuration explicitly permits.**

2. **A model gap reported as a collection gap.** `MGMT_IN` references object-group `MGMT_HOSTS`.
   The snapshot carries that group with both members, one of which (`10.0.40.0/24`) is a real VLAN
   in this very fabric. Because the compiler dropped the table, the application told users the
   members "were not collected" — a false statement about our own evidence, and the damaging
   direction of error: it sends someone to collect data they already have.

**Why the repair agents could not fix it:** `tools/compile-snapshot.mjs` was on the frozen-file
list, so they could only work around it inside the engine. That is a real lesson about file
ownership — freezing a file protects it from collision and simultaneously protects its bugs.

**Fixed by:** carrying all five fields plus `objectGroups` and `AclMatchField.group`; extending
`types.ts`; teaching `addrTri`/`consumeAddress`/`fieldAgrees` to resolve a carried group; and
deriving the host from each line's own `cite` rather than rethreading ~20 call sites.

**Result:** `core1.MGMT_IN[0]` went from permanently unevaluable to **evaluable** — `10.0.40.7`
(inside the group) matches, `10.0.10.50` does not. The model became strictly more capable *and*
stopped making a false statement. Covered by `src/core/compiler-fidelity.test.ts` (9 tests) and
`src/forwarding/producer-trust.test.ts` (8 tests), including one pinning the `cite` format that
host-derivation depends on.

**Two bugs I introduced while fixing it**, both caught by existing tests rather than by me:
  - `field.group !== null` misfired on `undefined`, because the real producer omits the key
    entirely when there is no group. That classified every ordinary address as "a group field" and
    broke the drift guard on the exact lines it should pass. Fixed with an explicit
    `fieldGroup()` helper that treats `undefined` and `null` alike.
  - The engine's own message went stale in the other direction: it still said the model "does not
    carry" members that it now carries.

### R1. Literal NUL bytes in `src/analysis/blast.ts` — FIXED
Two `\u0000` characters were written as literal NUL bytes inside a string literal used as an array
join separator. Valid JavaScript, compiled fine, 35 tests passed — but `file(1)` reported the module
as `data` and `grep` refused to search it, silently disabling review tooling on a 1686-line file.
Replaced with the escape sequence; byte-identical at runtime. Verified: `file` now reports
`JavaScript source, Unicode text, UTF-8 text`, and the 35 blast tests still pass.

### R2. Fabricated worked example in `docs/design-brief.md` §6.3 — FIXED
The brief's "worked example against the real data" used `10.20.10.5 -> 10.30.40.9`. Neither address
exists in `fabric.json`; the only observed subnets are `10.0.10.0/24`, `10.0.20.0/24`,
`10.0.30.0/24`. A build agent copying it would have shipped a demo flow returning `out-of-scope`.
Replaced with a flow verified by running `traceFlow`, and a correction note added in place.

### R3. The claim gate produced false positives on honest text — FIXED
`forbiddenWordsIn` initially used substring matching with no negation awareness. It flagged three
sentences the product *should* say:
  - `"nothing can be proven about forwarding on them"` (engine caveat — negated)
  - `"It does not show that ALL traffic does"` (sample-path disclaimer — negated)
  - `"every statement ... is unproven"` (engine caveat — "unproven" contains "proven")
This is worse than no gate: it would have pressured an author to delete honest sentences to go
green. Fixed with word-boundary matching plus clause-scoped negation detection, and the three real
sentences are now regression tests. The limit is documented in the code: the check is lexical, not
semantic, and is a backstop rather than a proof.

> **Moved from Open (2026-09-23).** R15, R9, R10, O2 and O3 were resolved before wave 2c but were
> filed under Open; they are moved here unchanged.

### R15. F6 failed — the status bar painted the live frame rate into every captured frame — fps cause FIXED; the 1-LSB scrim residual FIXED at the capture layer; F6 PASSES on `twice 5` against the preview, dev server (:4180) not measured (heading corrected 2026-09-22)

*Heading correction, 2026-09-22.* The previous heading read "F6 still FAILS on a 1-LSB scrim
residual". That was true of the body's middle paragraph and false of its end: the same entry goes on
to remove the residual (CPU tile raster in `review/capture.mjs`) and to cite F6 as PASS on
`node review/capture.mjs twice 5`. The acceptance grading (`docs/acceptance-report.md`, F6) upheld
that PASS independently: 32 of 32 frames byte-identical across 9 captures, 2 of them under ~80 % CPU
load, measured on the :4181 preview only. A heading that contradicts its own body is the stale-pointer
defect this entry was written about, so the heading now says what the body concludes. Unchanged: the
dev server has still not been measured for F6.

**This entry replaces the previous O4**, which said F6 was unproven because
`window.__atlasScene` was never set and the harness fell back to a bounded wait. That half is
resolved and has been for some time: all 32 entries in `review/shots/app/index.json` carry
`"converged": true`, and that field is only ever populated through
`page.waitForFunction(() => window.__atlasScene?.stats?.().converged === true)` — the
`waitForTimeout(2200)` fallback leaves it unread. The hook is live. F6 was failing anyway, for a
different reason, and the only document that could have warned a reviewer was pointing at a
problem that was already fixed. That is worse than saying nothing: it converts an open criterion
into a solved-looking one.

**The measured cause.** Two consecutive `node review/capture.mjs app` runs (both exit 0, 32 frames
each, renderer `ANGLE (Intel … Direct3D11)`, all 32 `converged: true`, `quality: "high"`) produced
**23 differing PNGs out of 32**. Example — `dark/1920/02-device-selected.png`:

```
run1 3f095ee82d573f61ffaf3c004b583347ca2d0502c056c3ebd21808c9ed4e42d9
run2 97cbf51c5e843b0ece15c195b1f325985819142da1813123fec5b2b64820af05
```

Pixel-diffing every pair put **every** differing pixel inside one 24x16 device-pixel box at the
bottom right — `dark/1920` bounding box `[3546,2126,3569,2141]`, 278 differing pixels, 0.0034% of
the frame; `dark/1440` `[2586,1766,2609,1781]`. Cropped and read at 6x, that box said
**"fabric 43 fps"** in run 1 and **"fabric 56 fps"** in run 2. The 3-D canvas — the part everyone
assumed was the risk — was byte-identical. The failure was a text node in the chrome.

Value origin: `src/fabric3d/scene.ts` `function frame(now: number)` → `fpsEma` → `SceneStats.fps`
→ `publishSceneStats` → `StatusBar`'s `.sb__fps`, drawn in the permanent status line of every
screen.

**Why nothing caught it.** `src/core/determinism.test.ts` owned F6's source half and detected only
clock **call expressions**. The rAF timestamp arrives as a function **parameter**, so the entire
fps path was outside its denominator — `grep -rn "Date.now(\|Math.random(" src/` returned zero
live call sites while the captures were nondeterministic. Its one value-flow rule was hard-coded
to the single field name `elapsedMs`, with no equivalent for `fps`. Meanwhile
`src/app/status-telemetry.test.tsx` **required** the defect
(`expect(container.querySelector(".sb__fps")?.textContent).toContain("52")`). And nothing in the
repository ever captured twice and compared: `grep -rn "F6" review/*.mjs` returned nothing. F6's
stated evidence is "capture twice, compare hashes", and that measurement had never been performed.

**What was changed (all four, because three of them are the reason the fourth was invisible):**

1. **The product.** `src/app/StatusBar.tsx` no longer draws any frame-timing digit in the
   permanent line. It carries the tier word, `reduced`, and `settled`/`refining` — all functions of
   the data. The measurements moved one click away into the coverage disclosure, which the scene
   readout now opens as a control (`Renderer`: frame rate, last frame, draw calls, triangles, tier,
   refinement). This follows the design brief rather than deviating from it: §8 asks for the active
   tier to be named at all times, and T8's permanent line is coverage + snapshot — it never carried
   a frame rate. Deliberately **not** a `?capture=1` mode: a capture that photographs a state the
   product does not otherwise show proves a property the product does not have.
2. **The gate that owns F6's evidence.** `node review/capture.mjs twice` captures, re-captures into
   a second tree, hashes every PNG and exits non-zero on any difference, naming the files. It
   refuses to report a verdict when either run had a render failure or when zero frames were
   captured — two blank runs hash identically, and calling that F6 satisfied is the same
   absence-as-health failure this product exists to detect.
3. **The detector.** `determinism.test.ts` now covers clock-valued **bindings** as well as calls —
   the rAF callback's first parameter and a DOM event's `timeStamp`, resolved through a named
   callback scheduled by identifier, which is the shape `scene.ts` actually has. It found three
   true positives that had been invisible; each now carries a written `determinism:` justification.
   The `elapsedMs` allow-list became the frame-timing field class (`elapsedMs`, `fps`, `frameMs`,
   `worstFrameMs`) with a declared owner per field, so the next one cannot reach a renderer
   unannounced. Both detectors are proven live by running them over planted source.
4. **The test that required the defect.** `status-telemetry.test.tsx` now asserts the property
   rather than the pixel: the scene readout carries no digit at any published frame rate, two
   readings differing only in frame timing leave its markup identical, and the measurements are
   still reachable behind the disclosure.

**Measured after the fix (2026-09-21, 11:4x) — F6 is still RED, on a different and much smaller
cause.** Two `twice` runs against the live dev server were contaminated — other agents edited
`src/fabric3d/scene.ts` and `src/app/surfaces.tsx` mid-run (source-tree hash differed before/after;
one run recorded "the page reloaded under the harness") — and are not evidence either way. The
authoritative run froze one `vite build` into a scratch directory, served it with `vite preview` on
its own port, and pointed the harness at it (`ATLAS_URL=http://localhost:4189 node
review/capture.mjs twice`; bundle hash identical before and after). Result: **exit 3, 30 of 32
frames byte-identical** (was 9 of 32); differing: `dark/1920/05-path-trace.png`,
`light/1440/06-path-blocked.png`. No fps glyph anywhere. Every differing pixel has **max channel
delta 1**, in full-width horizontal bands ~45 device px tall at the bottom edge of the side panes
(dark/1920 rows 2040–2085, x 3002–3839; light/1440 rows 660–661 x 0–597 and 1724–1725
x 2124–2879) — the geometry of the two stacked `linear-gradient` scroll scrims (`src/app/shell.css`
`.scroll-y, .scroll-scrim`; `src/panels/Inspector.css`). That is gradient raster/dither noise in the
compositor, not a value the product computes, but F6 asks for byte identity and this is not it.
**Open, owner: the shell/panel styling.** Candidate remedies, not yet tried: replace the
translucent gradient pair with a solid-stop or `mask-image` scrim and re-measure; or confirm it is
Skia gradient dithering and decide explicitly whether F6 is graded on bytes or on a stated ±1 LSB
tolerance — that is a change to the criterion, and must be made in `acceptance.md`, not in the
harness. Until one of those lands, grade F6 **FAIL**. **Located and removed at the capture layer (2026-09-21, later).** The alternate is page-wide, not one box: in the reproduced case (dark/1920/06-path-blocked, frozen `vite build` on its own port, nobody writing to it) BOTH rails' scrim bands and several SVG header/badge icon edges flipped together, maxd 1, never a glyph, never the canvas — so it is the capture browser's GPU tile-raster state choosing between two correct rasterizations, which is why pinning the scrollers (a product paint change) could not fix it. Measured: GPU tile raster (`--enable-gpu-rasterization`), 3 `twice` runs = 6 captures per frame, 1 of 32 frames varied; CPU tile raster (`--disable-gpu-rasterization`, WebGL still on the GPU via ANGLE, tier `high` and `converged` on every frame), 10 `twice` runs = 20 captures per frame, **0 of 32 frames varied across all 20**. `review/capture.mjs` now launches with CPU tile raster, and `twice N` compares every frame across all N captures in one command. This is a change to how the photograph is taken, not a tolerance: F6 is still graded on byte identity. Statistical honesty: at the GPU-raster rate seen here (1 in 192 captures), 0 in 640 would occur by luck about 4% of the time. **Not yet re-measured:** the dev server (:4180) — it was being edited by other agents throughout (two layout changes landed mid-probe), so any :4180 result today is not authoritative. Cite F6 as PASS only on `node review/capture.mjs twice 5` (exit 0) against a server nobody is writing to.

**Residual, stated rather than implied.** The quality tier IS derived from frame timing (median of
the first 60 settled frames) and IS drawn as a word. On a machine under enough load to step the
renderer down mid-capture, two runs would legitimately differ. That is not silent: `capture.mjs`
already records the tier per frame and reports any non-`high` frame as a problem, and `twice`
refuses to compare when a run had problems. A tier step-down therefore surfaces as a red capture,
never as a mystery diff.

### R9. Literal NUL bytes recurred in three modules, and scratch files leaked — BOTH now GATED (the scratch half corrected 2026-09-21)
`grep` reported `src/panels/PriorityQueue.tsx` as a **binary file**. It held 6 literal NUL bytes;
`src/panels/JsonView.tsx` held 1; `src/analysis/blast.ts` had held 2 earlier. Three independently
written modules, same cause: a NUL used as a composite-key separator in a template string, typed
directly into the source instead of written as an escape.

It compiles, it runs, every test passes — and `git diff`, `grep`, `file(1)` and most editors then
classify the file as BINARY. `grep -rn "thing" src/` silently skips it. A 1,000-line module drops
out of every code search in the project with no error message, invisible precisely to whoever is
looking for it.

Three occurrences is a pattern, so it gets a gate rather than a third repair:
`src/core/source-hygiene.test.ts` now asserts, across every `.ts/.tsx/.css/.json` file, that there
are no NUL bytes, no other C0 control characters beyond tab/LF/CR, and valid round-tripping UTF-8.

**Correction, 2026-09-21 — the scratch-file half of this entry was overstated and is now actually
closed.** This section claimed the gate asserts "no scratch, probe or dump files left in `src/`" and
that the class was shut. It was not. What shipped was a NAME regex,
`/(^|[\\/])(__|zz_|tmp_|scratch|probe|dump)/i`, scoped to the literal name of the one file it was
written after (`src/forwarding/zz_scratch.test.ts`, a refuter leftover that ran, passed and asserted
nothing). `zz_` requires the trailing underscore. Six files later written as `src/zzaudit*.test.ts`
matched none of those alternatives: every one was a bare `it()` with zero `expect(` calls, every one
was collected by vitest, and the reported pass count went 737 → 742 while the gate stayed green.
Five tests were added to the green count that proved nothing, and nothing objected.

That is the named-subset-instead-of-structural-class shape, and the gate's own comment had already
named the real property — "a bare `it(\"probe\")` with no assertion at all, inflating the pass count
while proving nothing" — one paragraph above a line admitting "WHAT THIS CANNOT DO: it matches
NAMES."

The gate now checks the property instead of the name. `source-hygiene.test.ts` parses every file the
vitest glob collects (and asserts that the globs it walks are the ones `vitest.config.ts` declares,
so the denominator cannot narrow silently), finds every `it`/`test` definition including the
`it.each(...)(...)` form, follows same-file helper functions to a fixpoint, and fails on any test
body with no assertion in it. It reads code, not prose: comments and string literals are stripped
first, so a commented-out `expect` does not satisfy it. Both halves of live are proven in the suite —
planted assertion-free tests in four shapes are detected, and asserting tests direct and
helper-mediated are not flagged. Verified end to end by planting `src/core/leftover.test.ts` (a name
no convention covers): it passed on its own and the gate named it.

The name regex is kept as a cheap second net and widened exactly where it missed (`zz_` → `zz`,
`tmp_` → `tmp`, no trailing underscore required). It is deliberately not widened to words a real
module could legitimately carry — a longer list of special names is the shape this defect IS — and
it is explicitly no longer the gate.

The six `zzaudit*.test.ts` files were written during an audit lane's own run, not left by the build,
and were already gone from `src/` by the time this repair landed. The hole they went through was
not.

The gate's first act was to fail on **its own file**. Writing `\u0000` in the doc comment that
explains the bug caused the editor to embed a real NUL, so the NUL detector shipped containing a
NUL; the same happened to `"\uFFFD"` in the check itself. Both are now constructed from their code
points rather than embedded. A detector that cannot contain what it detects is a constraint worth
knowing about, and the gate catching its own author inside a minute is the best argument for it.

### R10. Wall-clock assertions in the unit suite were a flaky gate — FIXED for the three tests named; the class was NOT closed until wave 6 (O26, now FIXED)
(Formerly O2. Retained below in full because the diagnosis is the useful part.)

*Heading corrected 2026-09-23 (wave 3).* It read "FIXED AS A CLASS". Under wave 3's multi-agent load
two wall-clock tripwires went red (O26): the median-of-7 counterexample tripwire this entry installed
(`engine.test.ts:955`, 54.66 ms against 50) and a **worst-of** bound in a fourth test this table never
listed (`CommandPalette.test.tsx:717–718`, "opens over an index that already exists", 620 ms against
400). The three rewrites below stand; the claim that the class was closed does not.

*Status at `8eac055` (wave 6).* The class is now closed as far as the reconciler's grep reaches — no
test under `src/` asserts on an elapsed time: wave 4 replaced the engine and palette bounds with counts
(R64), and wave 6 replaced the layout median below — the one this entry kept as "correct" — with a
counted work budget (O26). The paragraph defending the layout test's technique is superseded:
a median absorbs one scheduler stall, not a host that is busy for the whole run.

Fixed as one change across all three, rather than patching whichever one happened to be red:

| Test | Before | After |
|---|---|---|
| `forwarding/engine.test.ts` | single measurement < 5 ms | **median of 7** < 50 ms tripwire |
| `app/CommandPalette.test.tsx` | **worst** of 5 rounds < 50 ms | **median** of 45 samples < 200 ms tripwire |
| `fabric3d/layout.test.ts` | median of 7 < 50 ms | **unchanged** — already correct |

The layout test was deliberately left alone and the other two were rewritten to match it. It is the
only wall-clock assertion in the suite that has never flaked, and the technique is the reason:
a median absorbs a scheduler stall, and its bound sits an order of magnitude above the operation's
real cost. Changing a working test to match a template would have been cargo-culting; a comment now
records why it is sound so nobody "fixes" it later.

Both rewritten tests were also RENAMED, from "stays far under the 50 ms task ceiling" to "does not
blow up algorithmically". The old names claimed something a unit test cannot honestly assert — a
latency budget it does not control the machine for — and a test whose name overclaims is the same
defect as a UI that overclaims, just aimed at the next engineer instead of the user.

The real budget is owned by `review/measure-inp.mjs`, which measures the built application, labels
its numbers LABORATORY, and reports NOT MEASURED rather than guessing.

Verified: `134 passed` across the three files.

### O2 (diagnosis, retained). Wall-clock assertions in the unit suite are a flaky gate — a CLASS, not one test
Three tests assert elapsed milliseconds. On this host, which routinely runs 6–12 agents at once,
they fail spuriously — and a red from a timing assertion is **indistinguishable from a real
regression**, which is the worst property a gate can have.

| Test | Assertion | Statistic | Fragility |
|---|---|---|---|
| `fabric3d/layout.test.ts:909` | median < 50 ms | **median of 7 runs** | low — correct technique |
| `forwarding/engine.test.ts:509` | `t.elapsedMs` < 5 ms | single measurement | high |
| `app/CommandPalette.test.tsx:558` | worst < 50 ms | **worst of 5 rounds** | highest |

Observed: `engine.test.ts:509` failed once under load and passed on a quiet run;
`CommandPalette.test.tsx:558` is currently failing while six panel agents build. The layout test,
which takes a median, has never flaked — the technique is the difference.

**The principle:** a unit test can honestly assert an ALGORITHMIC property (this is not accidentally
quadratic) but cannot honestly assert a LATENCY BUDGET, because it does not control the machine.
The budget belongs in `review/measure-inp.mjs`, which measures the real application, labels itself
LABORATORY, and reports NOT MEASURED rather than guessing.

**Action:** keep a tripwire far above any plausible scheduling delay (≥10× the design budget) and
take a median rather than a worst case; let the INP harness own the real budget claim. To be applied
as one change across all three once the build agents release these files — fixing them one at a time
as they flake is how a gate gets loosened until it means nothing.

### O3. `tsconfig.json` restricted `types` to `vite/client` — RESOLVED
Any test importing `node:fs` failed typecheck with `Cannot find module 'node:fs'` even though
`@types/node` is installed. Resolved by adding `"node"` to `compilerOptions.types`, which the
claim-lint gate needs in order to read the source tree from inside the test suite. A gate that has
to live outside the suite is a gate nobody runs.

## Open

Moved to Resolved on 2026-09-23: O10, O15 and O18 (closed in wave 2c), and R15, R9, R10, O2 and O3
(resolved earlier but filed here). New in wave 2c: O21–O23. Wave 3 (`443a05a`): every "new" item of
the re-grade of `1d19e22` was fixed in code (R39–R53) except the harness's palette keystroke race
(O28); O16 is FIXED IN CODE but not re-measured at `443a05a` (the re-grade of `443a05a` then
measured it, O16); new O24–O28. Wave 4 (`8e873d2`,
`70bea72`): the re-grade of `443a05a`'s new items 1–12 were fixed in code (R54–R65) and O24 moved to
Resolved; of its item-13 leads, the stale card is R66, the missing period R55 and the palette over B7
O32; the C5 motion items all PASS in one reported independent run (R60), leaving O16's residuals; new
O29–O34. Not examined by the re-grade of `443a05a` and not touched in wave 4: O6, O7, O8, O11 and
O14. Wave 5 (`78bdba5`): of the re-grade of `70bea72`'s new items 1–10, items 1–5, 7, 8 and the B8
heading observation were fixed (R67–R73, R78, R79, R70); the merged-tree gate fixed three defects its
own audit run found (R74–R76) and one a cluster reported (R77); the orchestrator found and fixed the
cause of the host-load refusals (R80). Still open from that re-grade: E5 (item 6, O35), the B1 latent
laundering (item 9, O36) and the other item-10 observations (O37). Not examined by the re-grade of
`70bea72` and not touched in wave 5: O6, O7, O8, O11, O14, O29 and O33 (K2 left O33's guards
unchanged). Wave 6 (`8eac055`): of the re-grade of `78bdba5`'s new items 1–11, items 1–5 were fixed
(R82, R83, R81, R84, R85) and O26 closed and moved to Resolved; the gate's regression sweep found and
fixed three older defects (R87, R89, R90) and applied one hardening (R88), and W6-f2 found a harness
leak (R86). Still open from that re-grade: item 6 (O38), item 7 (O36, widened), item 8 (O34 corrected,
O39), item 9 (O40), and items 10–11 with item 4's leads (O41); wave 6's own owner decisions and leads
are O42 and O43. Not examined by the re-grade of `78bdba5`: O7, O8, O11, O14, O28, O29, O31 and O33;
wave 6 touched none of them (O33's file, `engine.ts`, changed without its guards). Wave 7 (`ba7b456`,
`34bd435`): of the re-grade of `8eac055`'s FAILs and new items 1–11, A4 (item 1, R91), B6 (item 2 and
the class, R92–R94), D4 (item 3, R97), items 4 (R95), 6's first half (R102), 7 (R101) and 8 (R98), and
B7 (R96) were fixed; F3's harness gap was fixed (R100) and O32, O38 and O39 closed and moved to
Resolved; W7-D4 found and fixed a forced-colours defect in passing (R99). Still open from that
re-grade: A1 (O12), A2 and F3 (O34), B8 (O13), C1 (O19), and items 5, 6's second half, 9, 10 and 11
(O44); wave 7's own leads and owner decisions are O45 and O46. Not examined by the re-grade of
`8eac055`: O6, O7, O8, O11, O14, O29, O33 and O42; wave 7 changed none of the code the first seven
name (only a comment in `claims.ts`, R100), and it changed more recorded frames (O42). Wave 8
(`7f67013`, the last full repair wave of this effort): of the re-grade of `34bd435`'s FAILs and new
items 1–10, F4 (item 4, R103), C2 (item 2, R104), D3 (item 3, R105), A4 (item 1, R106, at 1920 and
1440; at 768 and 390 an owner decision, O49) and the J2 aim (item 6, R107) were fixed, and the gate
corrected O41's stale manifest note (R108). Still open from that re-grade: A1 (O12), A2 and F3 (O34), B8
(O13), C1 (O19), and items 5, 7, 8, 9 and 10 (O47); wave 8's own leads are O48. Not examined by the
re-grade of `34bd435`: O6, O7, O8, O11, O29, O33, O42, O43 and O46; wave 8 changed none of the code the
first six name (`git diff --stat fea2037 7f67013` touches no file under `src/forwarding/`,
`src/analysis/` or `tools/`, nor `postfx.ts`, `claims.ts`, `commands.ts`, `store.ts` or `urlSync.ts`).
Phase 2 of the single-source-of-truth program (recorded 2026-09-27, an uncommitted working tree in the
parent repository): the engine now publishes per-finding evidence pointers (R109), the sample fleet has a
forwarding substrate (R111) and the RIB-completeness rule is per session (R110), the compiler is one
bound set (R112), and C2, C5 and D3 defects were fixed (R113–R115). Still open from it: A1's consumer
half (O50) and the golden's R6 decision (O51); E1's residuals (O52); A2 and B8, now blocked on an owner
decision rather than on data alone (O53); E2's residuals (O54); S1's (O55); C2's (O56); C5's (O57); D3's
routed fixes and residuals (O58); the cold first palette open (O59), scene convergence under the harness
(O60), INP elsewhere and the harness's cost (O61), and E2E3's residuals (O62). O12, O13, O16 and O34
carry phase-2 status notes. No phase-2 report the record step received addresses the other open
entries; phase 2 did change code several of them name (`DataGrid.tsx`, `PriorityQueue.tsx`,
`PathTrace.tsx`, `CommandPalette.tsx`, `App.tsx`, `scene.ts`, `postfx.ts`, `store.ts`, the compilers
and the compiled data among them), so their last status notes are not re-verified at this tree.
Phases 3 and 3.5 of that program (recorded 2026-09-30; `74275919`, `1061fdea`, `f24b9ccb` and an
uncommitted close-gate tree): the fleet was regenerated and recompiled, A1's consumer half is rendered
(R120, which closes O50), decided multi-hop traces are offered from the data (R121, which closes O65), and
the panels, core, scale, runtime-dataset, one-door, C1-protocol and focus-audit work is R122–R129. Still
open from them: the D3 focus audit, UNPROVEN at the current tree and withheld from further runs by the
owner (O68); the /scope reader's XML path (O69); three C1 validator holes (O70); the engine gate's one real
red (O71); and the clusters' residuals (O72–O75), the owner's decisions (O76) and a defect in the close
gate's own uncommitted change (O77). O12, O13, O19, O34, O53, O57, O58 and O66 carry status notes. **No
criterion moves in phases 3 and 3.5:** by the owner instruction of 2026-09-29 neither the acceptance
re-grade nor the C1 panel ran. Not examined by any phase-3 or 3.5 report: O6, O7, O8, O11, O14 and O29,
among others; phases 3 and 3.5 changed code several of them name, so their status notes are not
re-verified at this tree either.

### O11. Should an earlier refused hop undercut a denial? — OWNER DECISION
From R16. The claims-engine lane did not make the rule "every hop before the last must be RESOLVED"
for denials: `src/fabric3d/flow-terminal.counterfactual.test.ts:76` (another lane's file) builds a
two-hop denial where both hops say denied, and the strict rule turns it red. The lane's reasoning: for
a refusal, an earlier refused hop never makes the claim stronger. If the strict rule is wanted, that
fixture must change `{ ...first, nextHost: first.host }` to
`{ ...first, verdict: "forwarded", nextHost: first.host }` and the rule be tightened in
`hopsSupportOutcome`. Not decided; recorded so it is not mistaken for an oversight. **Status at
`34bd435`:** not examined by the re-grade of `8eac055`; wave 7 changed only a comment beside
`hopsSupportOutcome` (`claims.ts:491–492`, R100) and not the fixture. Still an OWNER DECISION.
**Status at `7f67013`:** not examined by the re-grade of `34bd435`; wave 8 changed neither `claims.ts`
nor the fixture. Still an OWNER DECISION.

### O12. A1 — evidence for a finding holds for 12 of 146 — OPEN, NOT CLOSABLE IN ATLAS SCOPE (needs per-finding record pointers from the producer); B1's four-surface residual FIXED (R27)
**A1** (acceptance grading, FAIL). The compiler-evidence lane reproduced it and searched the source
snapshot for any per-finding pointer to an interface, ACL line or config block: none exists. The only
field the compiler dropped was `source_command` (33 of 146 punchlist rows), which names a show-command
assigned by category (`cisco_toolkit/analyze.py` ~7599, `_PUNCH_SOURCE_COMMAND`), not a record. It is
now compiled (`sourceCommand`, via a `PUNCHLIST_FIELDS` map in `tools/compile-snapshot.mjs:222` that
stops the build on any unknown punchlist key — verified in code) and rendered once per finding by
`FindingSource` in `EvidencePane.tsx`, saying explicitly it is where the evidence came from, not a
record to open. Pinned by `src/panels/EvidencePane.source.test.tsx` (its first test is class-wide:
every producer key must reach the compiled finding) and new pins in `EvidencePane.namedconfig.test.ts`
(33 cited; only F106/F107 land on literal text, through the existing MGMT_IN match) — both re-run
green. `fabric.json` was then `6c7d78ab…6fa9095` (verified by the reconciler's `sha256sum` in wave 1;
since O15 it was `2f558c38…a308`, and since wave 4's B6 compiler change it is `a1a599b8…d251`, R54). **The grade does not move: still 12 of 146.** Closing A1 needs the
engine to publish per-finding record pointers — a producer change in the parent repository's engine,
not an Atlas Scope change; the data it would need is, per finding, the interface, ACL line or config
block the finding was derived from. Not re-examined in wave 2c. **Confirmed exactly by the re-grade
of `1d19e22`** (Ctrl+K census of all 146: 6 reach the named configuration, 6 the matching record, 133
context only, F142 no button); no wave-3 cluster touched it. **Confirmed again by the re-grade of
`443a05a`** (A1 FAIL: `{matched:6, named:6, context:133, none:1}`, typed after a 250 ms settle, O28);
no wave-4 cluster touched it — W4-R2 kept the A1 census pins (`EvidencePane.namedconfig.test.ts`,
`EvidencePane.source.test.tsx`) green while splitting the EvidencePane loops (R64). **Confirmed again
by the re-grade of `70bea72`** (A1 FAIL: 6 of 146 named, 2/143/1 literal, no target F142; F099 took 3
interactions); no wave-5 cluster touched it — R74 makes the Inspector a citation opens visible below
768 px, which does not add a route. Still NOT CLOSABLE IN ATLAS SCOPE. **Confirmed again by the
re-grade of `78bdba5`** (A1 FAIL: named 6, matched 6, context only 133, no button 1; F001 reads "No
configuration evidence route: the finding names no configuration line and nothing held matches its
words"; F099 took 3 interactions); no wave-6 cluster touched it — R81's in-sentence citations are on the
Path surface, not a finding's evidence route. Still NOT CLOSABLE IN ATLAS SCOPE. **Confirmed again by
the re-grade of `8eac055`** (A1 FAIL, a real-keystroke palette census of all 146:
`{"context":133,"named":6,"matched":6,"none":1}`, 0 URL mismatches; F099 in 3 interactions with the
camera unmoved). Wave 7 made EvidencePane's steps 1 and 5 name `finding.cite` as a working control
(R93) — a citation of the finding's own punch-list row, not a new configuration route. Still NOT
CLOSABLE IN ATLAS SCOPE. **Confirmed exactly by the re-grade of `34bd435`** (A1 FAIL: a
pushState-and-popstate census of all 146, waiting for `.ev__id` to match, gave named 6, matched 6,
context 133, none 1; F099 in 3 interactions with core1 unmoved; a first census with a fixed 700 ms wait
read F139 stale, O47). Wave 8 changed no evidence-route code (`EvidencePane.tsx`, the compiler and the
data are not in `git diff --stat fea2037 7f67013`). Still NOT CLOSABLE IN ATLAS SCOPE: it needs, per
finding, the interface, ACL line or config block it was derived from, from the producer.
**Status at phase 2 (2026-09-27): the producer half is DONE; the heading's "not closable in Atlas
Scope" no longer holds, and the grade still does not move.** The engine now publishes
`evidence_basis`, `evidence_refs` and, when capped, `evidence_refs_total` on every punch-list row (R109:
on a scratch sample, 52 rows `record`, 88 `row`, 6 `absence`), and the compiler carries them onto the
finding (R112). Two things stand between that and A1: the committed sample is not yet regenerated, so
the shipped `fabric.json` carries none of it, and nothing renders it (O50); and the repository golden
cannot compile as published (O51). A1 is re-graded only after phase 3 renders the pointers under the
contract in design brief §5.1.
**Status at phases 3 and 3.5 (2026-09-30): the consumer half is RENDERED (R120, closing O50), and the
grade does not move** — no re-grade ran (owner instruction of 2026-09-29). The shipped model is now
compiled from the regenerated sample (`74275919`), and every finding reaches every record the engine names
for it in 3 interactions under the settled counting, measured over all 146 in jsdom and, in a scratch
harness only, in a real browser at 1920×1080, 1440×900 and 1280×800; at 1280×720 203 of 583 activations
need a scroll (O72). Whether "the engine-named evidence" meets this criterion's literal "configuration
evidence" reading is the re-grade's to decide.

**B1 residual — FIXED (see R27).** Wave 1 left four surfaces printing the raw band without
`presentBand` (`CommandPalette.tsx:194`, `query.ts:189`, `query.ts:219` — the `is:healthy` answer — and
`PriorityQueue.tsx:184`). They were routed through the owner in the interrupted wave 2 (committed in
`254694b`), and `band-read.guard.test.ts` now checks the class — every typed read of `Device.band` —
rather than a list of surfaces.

### O13. B8 — the counterexample's positive state never renders on real data — OPEN (UNPROVEN)
After R17, the claims-engine lane re-swept: **0 of 2,498** real denied or dropped flows get a
counterexample. The one real-data near-miss the acceptance grading found was an artefact of the bug
R17 fixed. "Counterexample — the nearest flow that behaves differently" still renders only in
`engine.counterfactual.test.ts` on a fixture. B8 stays UNPROVEN; it cannot be exercised on this
snapshot, and should not be made to render by loosening the near-miss rule. NOT CLOSABLE IN CODE on
this data: it needs a snapshot in which some denied or dropped flow has a nearest flow that behaves
differently. Not re-examined in wave 2c (R35's pin asserts the one related real flow is offered no
nearby flow). **Confirmed by the re-grade of `1d19e22`:** 15,606 traces, `definiteDelivery=0`, 0
counterexamples. Not touched in wave 3. **Confirmed by the re-grade of `443a05a`** (11,988 traces:
0 decided refusals, 0 definite deliveries, 0 counterexamples; the positive state renders only under
`vi.mock('./rib-completeness')`). Not touched in wave 4; W4-R5 reported the `engine.counterfactual`
ratchets green. A2 needs the same kind of data (O34). **Confirmed by the re-grade of `70bea72`** (924
denied or dropped traces, 0 counterexamples, `isDefiniteDelivery` 0 of 4,160; the positive state only
under `vi.mock`). Wave 5 fixed the heading over the negative state (R70), not the state itself; still
UNPROVEN and NOT CLOSABLE IN CODE on this data. **Confirmed by the re-grade of `78bdba5`** (10,374
traces, 2,290 denied or dropped, `counterexample() found=true` 0, `isDefiniteDelivery` 0; the UI shows
"NEARBY FLOW WITH A DIFFERENT OUTCOME — NONE OFFERED"). Wave 6 changed the engine's sentences (R81),
not its search, and left `COUNTEREXAMPLE_CANDIDATE_CAP` at 48 (O33). Still UNPROVEN and NOT CLOSABLE
IN CODE on this data. **Confirmed by the re-grade of `8eac055`** (11,988 traces,
`counterexample().found = 0`, `isDefiniteDelivery = 0`; the positive state only under `vi.mock`), with a
method warning for graders: importing `claims.ts` without the app's `?t=` suffix splits its WeakMap side
tables across module copies and manufactured 384, 216 and 918 false "decided" denials (O44). Wave 7
changed nothing under `src/forwarding/` (`git diff --stat 6a5d830 34bd435`). Still UNPROVEN and NOT
CLOSABLE IN CODE on this data. **Confirmed by the re-grade of `34bd435`** (B8 UNPROVEN: 1,820 traces,
462 denied or dropped, `counterexample().found = 0`, `isDefiniteDelivery = 0`; the negative state renders
honestly; the positive state only under `vi.mock('./rib-completeness')` and `vi.mock('./bindings')`).
Wave 8 changed nothing under `src/forwarding/`. Still UNPROVEN and NOT CLOSABLE IN CODE on this data: it
needs a snapshot in which a denied or dropped flow has a decided nearby delivery. **Status at phase 2
(2026-09-27):** the data half is being built in the engine (R111's forwarding substrate), and on the
regenerated fleet it still gives 0 counterexamples of 70, because core1's own table reads incomplete;
forcing core1 complete as a counterfactual gives 26 of 70. What remains is an OWNER DECISION about the
B1 seed, not missing data alone (O53).
**Status at phases 3 and 3.5 (2026-09-30):** the owner decided the B1 seed in phase 2.75 (R117) and the
shipped data now carries it (`74275919`): the product offers a decided multi-hop denial with a counterexample
FOUND, and the golden tier asserts 26 counterexamples found over `engine.test.ts`'s 3,249-trace flow space
(R121). **B8 stays UNPROVEN** until a re-grade reads the positive state on the shipped data; none ran in
phase 3.5 (owner instruction).

### O14. `failureImpact(h).engine.record` aliases the compiled snapshot — OPEN (owner: `blast.ts` / `core/data.ts`)
Found by the hollow-test repair (R19): the new `repeatable()` check wrote a junk key into the first
result and it appeared in `engine.record` on the second run. `blast.ts` returns the compiled
`failure_impact` record itself (`return { record, basis: "different-measure", … }`, ~`:1267`), and
`core/data.ts` does not freeze `fabric` (verified by grep: no `Object.freeze`). Any caller that writes
to the result mutates the snapshot for every later caller. Fix: copy the record in
`compareEngineImpact`, or deep-freeze `fabric` in `core/data.ts`. Until then, `blast.test.ts` skips
objects that belong to the snapshot, with a comment saying why. Reported by the lane, confirmed in
code by the reconciler, not independently reproduced. No wave-2c cluster owned or touched it, nor
did wave 3 or wave 4; the re-grade of `443a05a` did not examine it. Nor did the re-grade of
`70bea72`, and `78bdba5` changes neither `blast.ts` nor `core/data.ts` (`git show --stat`). The
re-grade of `78bdba5` listed it as not examined, and `8eac055` changes neither file (`git show
--stat`). Unchanged, OPEN. **Status at `34bd435`:** the re-grade of `8eac055` lists it as not
examined; `git diff --stat 6a5d830 34bd435` touches neither `src/analysis/` nor `src/core/data.ts`.
Unchanged, OPEN. **Status at `7f67013`:** confirmed still true by the re-grade of `34bd435` — the
compiled `fabric` is not frozen, and its B grader spliced an ACL line in the page for the B5 control;
`git diff --stat fea2037 7f67013` touches neither `src/analysis/` nor `src/core/data.ts`. Unchanged,
OPEN.

### O16. C5 — motion render quality: every C5 motion item PASS at the re-grade of `70bea72`, in the wave-5 runs at `78bdba5` (reported) and at the re-grades of `8eac055` and `34bd435` (upheld); C5's one failing static item, the hairline, FIXED (R68); OPEN: a caller's tier change mid-motion still freezes the view for its re-warm-up (OWNER DECISION: the render owner) and the cluster-rule wording (OWNER DECISION: the C5 owner)
**Status at phase 2 (2026-09-27).** The tier cross-fade is now frame-stepped with a per-frame cap of
0.2 by owner decision, and the cap wins over the 300 ms bar on a host stall under a catch-up rule (R114;
design brief §4.8). Neither residual in this heading was addressed — the mid-motion `setQuality` freeze
and the cluster-rule wording remain OWNER DECISIONS — and phase 2 adds C5's own residuals (O57),
including a tier change during a running fade that removes the overlay in one frame.

**Status at `7f67013` (wave 8).** The re-grade of `34bd435` upheld C5: its grader's full `capture-motion`
run exited 3 on one fade stall ("opacity fell 0.5 in one frame") under 93 % host CPU, and a quiet 2-leg
re-run gave 24 of 24 fades at 266.6–266.8 ms; the refuter's full 4-leg run exited 0 (24 tier-held
sequences, 0 z-fight clusters over 1,218 steps, 0 pops over 2,664 pairs, 8 AO restores); the hardware
hairline probe found 0 chains. It did not exercise the mid-motion `setQuality` freeze or an organic
step-down. Wave 8 changed no render, camera, post-processing or quality code and did not touch
`review/capture-motion.mjs` (`git diff --stat fea2037 7f67013`), so no threshold moved. Reported, not
re-run: the gate's `capture-motion` exit 0 (24 sequences over 4 of 4 legs at the declared tier, 1,237
slow-motion steps, 2,673 still pairs, 8 AO restores, 24 of 24 fades at 266.6–266.7 ms). The residuals
and owner decisions below are unchanged.

**Status at `34bd435` (wave 7).** The re-grade of `8eac055` upheld C5 (`capture-motion` exit 0 over 4
legs: z-fighting 0 clusters, sparkle 0–43 px against the 120 px bar, "0 of 2604 still-pair pops", 24 of
24 tier fades at 266.6–266.8 ms; `probe-fabric.mjs --hairline` 0 chains in all 4 legs, and at DSF 1 only
the Legend button's border) and did not exercise the mid-motion `setQuality` freeze or an organic
step-down. Wave 7 changed no render, camera, post-processing or quality code and did not touch
`review/capture-motion.mjs` (`git diff --stat 6a5d830 34bd435`), so no threshold moved. Reported, not
re-run: the gate's `capture-motion` exit 0 (24 sequences at their declared tier, 1,240 slow-motion steps
with 0 clusters of 16 px or more, 2,675 still pairs with 0 pops, 8 AO restores, 24 of 24 fades, orbit
drag 428 frames at 59.88 fps). The residuals and owner decisions below are unchanged.

**Status at `8eac055` (wave 6).** The re-grade of `78bdba5` upheld C5 (`capture-motion`: z-fighting
PASS over 1,082 slow-motion steps, popping PASS over 2,641 still pairs, 8 AO restores, 24 of 24
cross-fades; `probe-fabric.mjs --hairline` 0 chains; 0 pure-black pixels), with only the black-background
item attacked, and did not exercise a caller's mid-motion `setQuality` or an organic step-down. Wave 6
changed `camera.ts` (R83: pending OrbitControls inertia discarded in `moveTo` and on every tween frame)
but not the tween clock or `applyQuality`, and `review/capture-motion.mjs` is untouched by `8eac055`, so
no threshold moved — `ZF_CLUSTER` is still 16 (`:190`) and its comment still "a 4x4 patch" (`:167`).
Reported, not re-run: the gate's final-build `capture-motion` exit 0, every C5 item PASS (1,231
slow-motion steps, 2,664 still pairs, 8 AO restores, 24 of 24 cross-fades, every motion frame at its
declared tier). The residuals and owner decisions below are unchanged.

**Status at `78bdba5` (wave 5).** The re-grade of `70bea72` passed every motion item ("every recorded
motion frame rendered at its leg's declared tier (24 sequences, 4 of 4 legs)", 0 z-fight clusters, 0
pops, 24 of 24 fades at 266.6–266.8 ms, on one contended host) and failed C5 on item 8 alone, the
hairline, which wave 5 fixed (R68). Reported and not re-run by the reconciler: W5-K1's `capture-motion`
run (all six items PASS, exit 4 only from the build-freshness flag) and the gate's run on its final
production build (exit 0, all six PASS: 24 sequences at their declared tier, 1,240 slow-motion steps,
2,667 still pairs, 8 AO restores, 24 of 24 fades at 266.6–266.8 ms). `capture-motion.mjs` is unchanged
by `78bdba5`, so no threshold moved. The residuals below are unchanged: no wave-5 cluster touched
`applyQuality`, `camera.ts`'s tween clock or `ZF_CLUSTER`.

**Status at `70bea72` (wave 4), superseded above in its C5 figures.** The re-grade of `443a05a` measured edge shimmer and z-fighting PASS
in a laboratory run (flip px 0–37 against 120, 0 clusters) on a contended host that was not
tier-held, and failed C5 on popping instead. Wave 4 fixed both pops, the harness's tier blindness and
the caller-pin defect, and an independent verifier's `capture-motion` run at `70bea72` passed all six
items with every sequence at its pinned tier (R60; reported, not re-run by the reconciler). What
remains open:
- **A caller's tier change mid-motion — OWNER DECISION (the render owner).** A `setQuality` to a
  DIFFERENT tier (the Quality control) issued while the camera moves still presents no new frame
  until the new chain's re-warm-up ends — about 400–500 ms, measured on the dev build (W4-R4,
  reported) — and the overlay then releases within one frame. `70bea72` removed only the same-tier
  case (no rebuild, no warm-up). Closing it needs `applyQuality` restructured so the old chain keeps
  presenting while the new one warms; W4-R4 declined it as architectural and the gate refused it for
  this wave. §4.8 says so ("a caller-made tier change (`setQuality`) is not deferred").
- **What the C5 evidence does not cover.** The app passes no pin, so an ordinary session runs on the
  adaptive tier and can step down (only at rest since R60); the HIGH-leg evidence is about a pinned
  high tier, and `capture-motion` no longer observes an organic step-down, which rests on
  `stepdown*.test.ts` and the cross-fade item. One host (Intel iGPU, ANGLE D3D11).
- **Optional, the `camera.ts` owner.** A `tweenRemainingMs(nowMs)` accessor on `CameraRig` would let
  `scene.ts` stop inferring the tween clock from the `isTweening()` edge plus `CAMERA_TWEEN_MS`; a
  `moveTo` re-issued mid-tween currently reads its arrival early, which ramps the blend out sooner and
  never causes a pop (W4-R4, reported). The gate did not apply it: it would have changed the motion
  code the same gate was judging.
- **The cluster-rule wording — OWNER DECISION, unchanged** (below).

**Status at `443a05a` (wave 3), superseded above.** The re-grade of `1d19e22` confirmed this FAIL at both tiers (304–739
px against the 120 px bar on all 8 orbit sequences) and saw the 16 px cluster move to dark/low. The R5
cluster first classified the flip-flopping pixels (a verdict-neutral diagnostic in
`capture-motion.mjs`): about 90 % thin strokes, the rest silhouettes, 0 highlight and 0 flat, so
neither specular anti-aliasing nor a steadier SSAO applies. **The fix is a HISTORY BLEND**,
`postfx.ts:176–188` `HISTORY_AA` / `historyWeightFor` and `HistoryEffect` (`:203`), verified in code:
while the camera creeps at 0.02–0.5 drawing-buffer px per frame the final pass mixes **0.75** of the
previous presented frame; the weight ramps to exactly 0 below 0.02 px and between 0.5 and 1 px, and
is 0 — the plain chain, bit for bit — when the camera is still, fast, or when anything other than the
camera changed (`contentVersion`, `scene.ts:1746–1756`); a plain frame is owed before `converged`.
**The design's stated trade-off:** it is temporal smoothing *without reprojection*, so while the
camera creeps an edge can trail by up to roughly the creep distance over a few frames. `docs/
render-decisions.md` §10 records the decision. **Pinned by** `render-c5-r4.test.ts` (19, including
"a creeping camera … gets the full weight", "ramps in and out instead of switching…" and "the
controls' change listener requests a frame and does not bump the content version") — re-run green.
These pin the weight function and the invalidation, not the pixels.

**What is measured, and by whom.** No capture-motion threshold changed since `d3e2a1c`
(orchestrator: `ZF_MAX_SHARE` 0.0002, `ZF_CLUSTER` 16, `SPIKE_RATIO` 3, `POP_*` and `AO_*`
identical — consistent with the reconciler's diff, where those lines only re-indent); the one addition
is `SPIKE_NORM_FLOOR` 1.6 (R52), and the flip classification is reporting only (`flipShare` is
computed as before). The R5 cluster reports every C5 item PASS on a scratch release build (orbit flip
px 11–40 against 120, 0 clusters; same-host A/B `d3e2a1c` 300/699 px against 5–26 px on dark/high;
exit 4 only for build freshness). **The merged-tree gate did not run `capture-motion`** (orchestrator;
its result lists no such run). `render-decisions.md` §10 nevertheless states a "re-measured on the
merged wave-3 tree" figure of 9–35 px; those figures match exactly an ignored
`review/shots/motion/report.json` generated 2026-09-23T06:17:03Z (09:17 +0300; later overwritten by
the re-grade's C grader, whose backup is in that session's scratchpad) against a fresh build
of this checkout on :4181, every item PASS (orbit flip px 17/35, 17/23, 20/32, 9/34; 0 clusters). By
file times, `src/app/shell.css` was edited after that run (09:24, the R46 `overflow-y: scroll` rule)
and the commit is at 10:12, so that report is not a measurement of `443a05a`, and who ran it is not
recorded. **C5's PASS therefore rests on the R5 cluster's own runs until the sweep re-measures it at
`443a05a`.** Raising the bar was not used, and is still not a fix. Also reported by R5: settled frames
are unchanged (`capture.mjs twice 5`, 32 of 32 byte-identical across 5 runs), and one contended run
stepped the auto tier high → low mid-orbit and recorded a 9.8x motion spike at the step — the
product's step-down under a 100 %-busy host, not the blend; with the tier held every item passed.

**Owner decision, unchanged.** The z-fighting rule counts any 4-connected cluster ≥ 16 px while its
comment calls that "a 4x4 patch" (`capture-motion.mjs:154` at `443a05a`; `:167` at `70bea72`, still
there; `ZF_CLUSTER` is still 16). The only cluster ever
recorded was a 16x1 run; with the blend it has not recurred (0 clusters in 4 reported runs and in the
09:17 report, and 0 in every reported wave-4 run including the independent one at `70bea72`), but the
code/comment contradiction stands and narrowing the rule needs sign-off.

**Status at `1d19e22` (orchestrator's run), superseded above.** `node review/capture-motion.mjs` exits 3 on two items:
**z-fighting** — one 16 px cluster, dark/high/orbit-drag; and **edge sparkle** — flip share
0.00054–0.00132 of the canvas (325–793 px) against a 0.0002 bar, on all 8 orbit sequences. Label
popping (0 blinks), AO drop/restore and the 280 ms tier fade PASS (R29, R30).

**Attribution (motion cluster, reported; the probes are in the orchestrating session's scratchpad).**
The unchanged harness, run on the dev build with only `SMAAEffect`'s blend weights cleared in-page,
passed every item on all 48 sequences (flip px 7–65 against the 120 px bar; 0 clusters), so the
remaining failure is made by the SMAA stage's per-frame edge and pattern decisions on 1–3 px features
(cables, state-ring curbs, faceplate strips) under the damped orbit's sub-pixel creep — temporal edge
aliasing, not a depth tie. Cable depth ties contribute nothing (cable `depthWrite=false` with SMAA off
gave the same count). **No single SMAA setting closes it:** diagonal detection off 259 px (the largest
single knob); corner detection off, no change; MEDIUM/LOW presets 347/350; LUMA detection 1408;
excluding cable pixels from the blend 185; diagonal off plus that exclusion 107 (light/low) and 187–194
(dark/high); 2× supersampling 75–125, at 4× fill cost.

**What would close it.** An anti-aliasing stage that is stable under motion — for example multisampled
rendering through the composer, or SMAA output accumulated with history while the camera creeps and
reset at rest so settled frames stay byte-identical for F6 — measured against E4's frame rate on the
real GPU; or an explicit decision by the C5 owner on whether this share bar is C5's "aliased edges"
item. **Raising the bar is not a fix.** Also for that owner: the cluster rule counts 4-connected pixels,
so a 16×1 single-row run qualifies although the harness comment calls a cluster a 4×4 patch; making the
rule 2-D narrows a check and needs sign-off.

**Original measurement (2026-09-22, before wave 2c), retained.** Measured by the C5 motion harness
`review/capture-motion.mjs` (fresh release build on :4181, 1440×900, DPR 1, ANGLE/Intel D3D11,
dark/light × high/low, every rAF captured at 59.9 fps median; the harness exits 3). Report
`review/shots/motion/report.json`, frames under `review/shots/motion/_evidence/` (2.8 GB, gitignored).

| Item | Verdict | Evidence |
|---|---|---|
| Z-fighting | **FAIL** | 1,234 slow frame steps: pixels reverse 3+ times in 6 frames by ≥12/255 while the camera moves 0.0006–0.07 px/frame; 17–30 px clusters (e.g. dark/low at x507–511, y598–611); 0.07–0.13 % of canvas in 10 sequences. At both tiers, so not SSAO or SMAA. Zoomed: a chassis's thin right side face seen edge-on, where it meets lid and floor ring — near-coplanar depth ties. `_evidence/dark/{high,low}/orbit-keys-slow/flipflop-*.png` |
| LOD / effect / label popping | **FAIL (labels only)** | Canvas: 0 pops over 2,667 still pairs, 0 motion spikes. Labels: 29 blinks (a visible/hidden run ≤5 frames), 6 of one frame (e.g. `access15` hidden 1 frame at reset-fly 28–29), clustered at fly-to starts. `series.json` `vis` logs |
| AO drop/restore (high) | PASS | 8 of 8; returns 133–150 ms after fly-to (hold 140 ms); worst jump 0.061 % ≥8/255 against a 0.5 % bar |
| 300 ms tier cross-fade | PASS | 24 of 24; 299.9–300.1 ms, max step 0.10/frame (bar 0.25) |

Two statements in that table are superseded by wave 2c: the clusters were **not** near-coplanar depth
ties on the chassis side face (R31), and "at both tiers, so not SSAO or SMAA" could not rule out
SMAA, which is on at every tier (`quality.ts`, `smaa: true` in all three profiles). The tier fade is now 280 ms (R29). Also recorded then, and still
unexplained: one early run cut a high→low fade across a 517 ms frame gap and did not recur in 36 later
fades. The harness forces `preserveDrawingBuffer` and wraps `requestAnimationFrame`; each is justified
in its header.

### O17. Layout residuals after R25 — OPEN for descender clipping and compact density; the single-column overflow FIXED at 800–1000 px in wave 3 (R42), and 768 px itself measured by `layout-guard.mjs` since wave 5 (reported, not re-run by the reconciler)
**Status at `7f67013` (wave 8).** The re-grade of `34bd435` again graded C3 at comfortable density
only and found its evidence narrower than its claim: across the whole queue at 1440 in state 03, 79 of
107 titles are clipped and 39 lose over 20 % (F141 32 %) in a 122 px title column, within the bar and
each keeping its subject (its item 10, O47). It did not grade compact density or C2–C4 pixel by pixel at
390, 768 and 1024, and reproduced the scroll-edge cut in state 06 (O41, O44). Wave 8 changed the width
ladder (R103: every narrow rung is now the complement of one boundary, so a fractional width can no
longer fall between the single-column and stacked layouts, and `PriorityQueue.css`'s rule that overlapped
at exactly 768 moved to the stacked rung) but not the queue's title column or density. Descender and
scroll-port-edge clipping still have no detector. Reported, not re-run: the gate's `layout-guard.mjs`
"all five invariants hold at every viewport", exit 0 (the single-column grid paints to the status bar at
1000, 900, 800 and 768).

**Status at `34bd435` (wave 7).** The re-grade of `8eac055` graded C3 at comfortable density only (at
1920, 10 of 10 titles unclamped; at 1440, F002 loses one word), did not grade compact density or the
390, 768 and 1024 widths for C2–C4, and saw scroll-edge clipping again in state 06 (O44, whose W7-B6
note says the cut line is now a citation line). Descender and scroll-port-edge clipping still have no
detector. Reported, not re-run: the gate's `layout-guard.mjs` "all five invariants hold at every
viewport", exit 0, with hop rows 38 px and 0 px overflow at 390, 768, 1440 and 1920. W7-A4's
observation that the queue grid's BOX runs 24 px past a 768 × 1024 viewport is O45.

**Status at `8eac055` (wave 6).** The re-grade of `78bdba5` upheld C3 at the 03 capture and
comfortable density only, and found it fragile at nearby widths: 80 of 107 titles clamped live at 1440
on the dev server without the Inter font. W6-a4 measured state 03 directly after its queue changes:
0 clamped queue titles at 1440 (7 visible) and at 1920 (11 visible) (reported). Compact density was
not graded; descender clipping still has no detector, and the re-grade's "scroll ports cut a text line
in half at their lower edge" is the same family (O41). The gate's `layout-guard` run on its final build:
"all five invariants hold at every viewport", exit 0 (reported).

**Status at `78bdba5` (wave 5).** W5-K3 added a 768x1024 row to invariant 5's sizes
(`layout-guard.mjs:305–306`, verified in the diff) and reported "grid paints to 998 (status 998); after
focus .app scrollTop 0, status 998, focused cell 809-826", exit 0; the gate's final-build run reports
"all five invariants hold at every viewport", exit 0. So the 768 px bullet below is measured, by a
reported run only. The re-grade of `70bea72` confirmed descender clipping and compact density
unmeasured (C2 and C3 PASS with those notes) and found its D1 failure at 768, which O17 had said no
guard measured (R71). Descender clipping still has no detector; compact density is still not graded.

**Status at `70bea72`, superseded above for 768 px.** Unchanged by wave 4. The reconciler's `layout-guard.mjs` run at `70bea72`
measures invariant 5 at 1000x800, 900x700 and 800x600 only (all three hold), so 768 px itself is still
unmeasured; descender clipping still has no detector (the re-grade of `443a05a` confirmed both, and
did not grade compact density). Wave 4's 390 px scope-bar fix (R57) is a different defect.

- **768 px queue overflow — addressed at 800–1000 px, not measured at 768.** At 768 the queue rows
  overflowed their own track and the status bar covered them. Wave 3 found the same fault across the
  single-column band (768–1023 px) at 1000x800, 900x700 and 800x600 and fixed it (`shell.css:643–650`,
  R42); `layout-guard.mjs` INVARIANT 5 holds at those three sizes (reconciler's run). The media query
  starts at 48rem = 768 px, but no guard or recorded probe has measured 768 itself since, so whether
  those rows now end at the status bar there is not established.
- **Descender clipping** is invisible to `readTextFidelity` (midpoint rule), so a clamp that cuts
  descenders passes the gate. Wave 2c widened the detector (identifier splits, node-boundary splits,
  overruns; R28) and wave 3 added form reach (R46), but not this; the R2 cluster left it open
  (optional in its brief).
- **The path-slot clipping** the re-grade asked to file here was FIXED in wave 3 (R46); its stated
  consequence, the queue under rail A's fold, is O24.
- **Proof scope** (closed as far as it goes). The layout lane measured only :4180; the reconciler
  re-ran `capture.mjs text` on the :4181 build (72 of 72, exit 0), and the merged-tree gate ran
  `capture.mjs app` on :4181 (32 of 32, exit 0), which applies the same checks per frame. That 72 of 72
  was measured with a detector blind to identifiers and is superseded; the wave-2c 72 of 72 (R28) was
  re-run by the reconciler on a scratch build of `1d19e22`. The detector now has a known-answer
  self-test (17 cases) but has not been independently refuted.
- **Compact density** still truncates titles by design (windowing needs uniform row height). C3 was
  graded at comfortable density; compact is not covered by the fix.

### O19. C1 — a valid blind verdict set is not achievable against these reference products — OWNER DECISION
`docs/acceptance.md` C1 asks for blind, side-by-side verdicts with ≥2 independent critics per pairing,
the critic not told which is which. Against the current references that condition cannot be met, not
merely has not been:
- **The references identify themselves by content and chrome.** `review/REFERENCES.md` records that
  the round-2 decoder found "in every verdict the critic's loser was the REFERENCE panel", that the
  brand-cropped `-craft` variants did not prevent identification, and that the Forward captures carry
  the Storylane tour modal and a "Click on Vulnerability" coachmark while the Grafana captures carry a
  "Create free account" banner. Two automated drivers failed to advance the tours past their opening
  step, so no chrome-free Forward capture exists. A critic who can tell which image is the demo is not
  blind, however the files are named.
- **What evidence exists.** Rounds R1 32/33, R2 36/36, R3 36/36 head-to-head wins (withdrawn as C1
  evidence by `REFERENCES.md` itself: saturated at 72/72, so it cannot discriminate); ~350 specific
  faults listed against OUR panel across three rounds, falling from a peak of 24 per critic to 7–13 —
  real evidence of improvement measured against itself, which is not what C1 asks; and
  `review/blind/KEY.json` for 12 sheets with **no recorded verdicts**, beside 20 sheet images, 8 of
  them orphans the KEY cannot decode.
- **Why none of it is C1 evidence.** Blindness is the criterion's load-bearing property, and every
  recorded verdict was given by a critic who could identify the reference.

C1 stays UNPROVEN. Moving it needs an owner decision: supply references that can be captured clean
(product access rather than a guided demo), choose different reference products, or restate C1 in
`acceptance.md` to what can honestly be measured. Re-running more rounds against these images would
produce more of the same non-evidence. **Confirmed by the re-grade of `1d19e22`** (`KEY.json`: 12
entries, zero verdicts; 8 of 20 sheets orphans; the `-craft` sheet still shows "Forward AI" and the
Storylane modal). Still an owner decision; not touched in wave 3. **Confirmed again by the re-grade
of `443a05a`** (same `KEY.json`, same orphans, same `-craft` sheet); not touched in wave 4.
**Confirmed again by the re-grade of `70bea72`** (12 entries, no verdict, winner, critic or reasons
field; 8 orphan sheets; `sheet-d808251b311c.png` still shows "Forward AI" and the Storylane modal); not
touched in wave 5. **Confirmed again by the re-grade of `78bdba5`** (12 entries with no verdict,
winner, critic or reasons field; 8 of 20 sheets not in `KEY.json`; the "craft" sheet still shows "Forward
AI" and a Storylane "Start" button); not touched in wave 6. **Confirmed again by the re-grade of
`8eac055`** (C1 UNPROVEN: 12 entries, none with a verdict, winner or critic field; 8 of 20 sheets
unkeyed; the craft sheet still shows "Forward AI" and a Storylane "Start" modal); not touched in wave 7.
Still an OWNER DECISION. **Confirmed again by the re-grade of `34bd435`** (C1 UNPROVEN: `KEY.json` 12
entries whose only keys are `id, sheetName, A, B, ours, reference, question, sheet`; 8 of 20 sheets
unkeyed; the craft sheet still shows "Forward AI" and a Storylane "Start" modal; the sheets are dated
2026-09-20 and 09-22, before waves 3–8); not touched in wave 8. Still an OWNER DECISION.
**Status at phases 3 and 3.5 (2026-09-30) — restated, not closed.** P3G found the premise false: a
valid verdict set is achievable for Forward (its demo pages rendered offline from their server-rendered
data, with provenance), Grafana (the banner pre-seeded dismissed) and IP Fabric (unannotated documentation
screenshots); Linear is not obtainable without an account and is out of C1's scope unless the owner
supplies a signed-in capture. The old wrapped references came from a selector miss and an exact
`aria-label="Close"` match, not from uncapturable products. The references, masks, task-matched pairings
and a pre-registered KEY rule are R127; the rule's validator still loses a loss three ways, and the
critic panel has not run (O70). Our identity is masked by DOM-measured geometry, and declared reference
identity slots are bound to the frame they were measured on. Still an OWNER DECISION: the "3-D render"
dimension (O76).

### O20. Minor drift and E5 harness limits carried from acceptance — `--sev-high` drift FIXED (R36); the probe gap FIXED in the harness (R37); the sweep's stalled-window blindness FIXED in the harness (R63); the pre-FCP carve-out is an OWNER DECISION; E5 PASSED at the re-grade of `1d19e22`, FAILED in acceptance-grade runs at the re-grade of `70bea72` on post-first-paint keystrokes, which the carve-out does not touch (O35), and PASSED in acceptance-grade laboratory runs at the re-grades of `8eac055` and `34bd435` with a thin margin
- **Status at `7f67013`.** The re-grade of `34bd435` ran E5 on AC on a quiet host (build
  `d67f4ef7a4b4530b`): "PASS E5 3 cold loads", worst accepted keystroke 168 ms (grader) and 184 ms
  (refuter, aimed into the Fabric3D warm-up frame over 19 more cold loads); the sweep's 13 actions, and
  19 the refuter added, all under 200 ms. The carve-out is still unsanctioned: the reconciler's grep finds
  no `E5 EXEMPTION (owner-sanctioned)` line in `acceptance.md`, which wave 8 does not touch, and the PASS
  did not need one. Wave 8 added fractional-width cold loads to `audit-e5-coldload.mjs`, reported and
  never judged (R103), and changed code in the first frame (O35). Reported, not re-run: the gate's
  `ATLAS_RUNS=1` validation of that harness, "E5 PASS", exit 0 — one run, not acceptance evidence.
- **Status at `34bd435`.** The re-grade of `8eac055` ran E5 on AC on a quiet host: "PASS E5 3 cold
  loads", no frame over 200 ms, worst accepted keystroke 160 ms (grader) and 184 ms (refuter); the sweep
  "all 13 actions stayed under 200 ms in every one of 3 repetitions". An F-group run on a build flagged
  NOT FRESH printed "2 keystroke(s) over 200 ms (worst 224 ms)  [NOT ACCEPTANCE EVIDENCE]", not counted
  (O44). The carve-out is still unsanctioned: the reconciler's grep finds no `E5 EXEMPTION
  (owner-sanctioned)` line in `acceptance.md` at `34bd435`, and the PASS did not need one. Reported, not
  re-run: the wave-7 gate's cold load on `ba7b456` (a preview build, host 8 % busy, on AC), "PASS E5 3
  cold loads", worst frame 105.2 ms, worst keystroke 160 ms.
- **Status at `8eac055`.** The re-grade of `78bdba5` had no acceptance-grade E5 run: the host was on
  battery for the whole session. Its laboratory run printed "PASS E5 3 cold loads … [NOT ACCEPTANCE
  EVIDENCE]", worst keystroke 192 ms (8 ms under the bar) with only 3 of 9 long frames probed by a
  keystroke, and the sweep "all 13 actions stayed under 200 ms"; that cannot overturn the
  acceptance-grade FAIL at `70bea72` (O35). The carve-out is still unsanctioned: the reconciler's grep
  finds no `E5 EXEMPTION (owner-sanctioned)` line in `acceptance.md`, which `8eac055` does not touch.
  Wave 6 ran no E5 harness.
- **Status at `78bdba5`.** The re-grade of `70bea72` ran `audit-e5-coldload.mjs` twice with
  `acceptanceEvidence=true` (busy 0.241 and 0.24, on AC): FAIL on 8 and 5 keystrokes over 200 ms, all
  after first paint, so E5 fails without reference to the carve-out; the out-of-load sweep PASSED
  ("all 13 actions stayed under 200 ms in every one of 3 repetitions"). The product defect is now its
  own entry, O35. The carve-out is still unsanctioned: the reconciler's grep finds no
  `E5 EXEMPTION (owner-sanctioned)` line in `acceptance.md` at `78bdba5`, and the gate's run still
  counts pre-first-paint frames with blocking 0 (reported). W5-K4 adds a second measurement-class
  question for the owner (O35): whether "cold load" means a cold HTTP cache or a never-used browser
  profile. The sweep's harness now meters its own closes (R78); it has not been re-run on a quiet host.
- **Status at `70bea72`, superseded above.** The re-grade of `443a05a` withheld E5 (cold load FAIL, worst 393.1 ms
  pre-FCP, judged because the carve-out is unsanctioned, at 55 % host load; the sweep NOT MEASURED on
  swap+submit). Wave 4 fixed the sweep's harness defects (R63: stalled-window frames counted apart;
  swap+submit removed as J4's act, R62). No E5 run is reported on the merged tree — the gate ran E2/E3
  and E4 only (O25). The carve-out is still unsanctioned: the reconciler found no
  `E5 EXEMPTION (owner-sanctioned)` line in `acceptance.md`.
- **Status at the re-grade of `1d19e22`, superseding the last bullet below.** E5 PASSED on a quiet
  AC host (`acceptanceEvidence=true`, excess 17–21 %; worst frames 105.2/133.2/110.9 ms; the sweep's
  16 actions under 200 ms in 3 of 3 repetitions) without the carve-out (a palette opened during load
  reached 168–192 ms, a thin margin). **Wave 3:** no acceptance-grade E5 run. The R1 cluster's run
  was refused by the harness (host 68 % busy against a 25 % bar); the R5 cluster's cold-load runs
  FAIL on this build *and* on `d3e2a1c` alike on the same contended host (pre-first-paint frames of
  298–376 ms judged because the carve-out is not sanctioned, and 4 keystrokes over 200 ms) — reported,
  laboratory, not attributed to the wave. The entry chunk is 3.63 kB before and after (R1). See O25.
- **`--sev-high` brief drift — FIXED (R36).** It was one of 31 drifted tokens; all reconciled, and
  `contrast.test.ts` now guards §3.3 against `tokens.css`.
- **E5 keystroke probes — FIXED in the harness (R37), run not verified.** They were sampled at fixed
  times, so the post-FCP frames that block ~145 ms were never probed. Probes are now also aimed at long
  frames earlier runs observed, and each run reports its keystroke coverage.
- **E5 pre-FCP carve-out — OWNER DECISION.** It was never sanctioned in `acceptance.md`. The harness
  now applies it only if `docs/acceptance.md` holds a line beginning
  `E5 EXEMPTION (owner-sanctioned): pre-first-paint`; there is none, so pre-FCP frames are judged (a
  264.7 ms pre-FCP frame now fails E5, reported). Adding that line, or not, is the owner's decision; a
  warm-browser probe had supported the exemption (0 frames over 200 ms before FCP).
- **E5 itself stays UNPROVEN, leaning FAIL.** The only runs are on a busy host on battery (14
  keystrokes over 200 ms, worst 560 ms, at 81 % busy), which the harness refuses as acceptance
  evidence. It needs a quiet run on AC power.

### O21. E3 — input-handler interactions outside the five journeys cross 50 ms — OPEN (owner: the performance cluster) for navigation seeding, which reproduced at the re-grade of `70bea72`; resizes showed 0 ms of the app's own work there; the first selection, swap+submit and the palette open are journey acts since wave 4 (R62)
**Status at `7f67013`.** The re-grade of `34bd435` (acceptance-grade laboratory, on AC): "path trace:
seed a flow by navigation" measured 98.1, 65.9 and 74.4 ms (grader) and 73–87.5 ms (refuter), still the
only sweep action over 50 ms and still outside E3's claim; among the refuter's added actions the Path
surface click reached 61.5 ms (an E5 subject, under its 200 ms bar). Wave 8 changed what a surface switch
does in the queue (R106: the hold armed at activation, an IntersectionObserver on the held row and the
focused cell, re-reveals that may scroll the outer rail), and nothing has measured the switch or the
seeding since. Still the owner's question.

**Status at `34bd435`.** The re-grade of `8eac055` (acceptance-grade laboratory, quiet host on AC):
"path trace: seed a flow by navigation" measured 97.8, 62.8 and 74.3 ms (grader) and 76.8–78.4 ms
(refuter), still the only sweep action over 50 ms and still outside E3's claim. Wave 7 changed what the
path surface renders (the preset cards, R92) and nothing has re-measured it since. Still the owner's
question.

**Status at `8eac055`.** The re-grade of `78bdba5` (laboratory, on battery): the sweep's worst action
was again "path trace: seed a flow by navigation", 89.3 ms LoAF; resizes showed 0 ms. No wave-6
cluster worked on either; wave 6 changed what the path surface renders (R81), and nothing has
re-measured them since.

**Status at `78bdba5`.** The re-grade of `70bea72` (quiet host): "path trace: seed a flow by
navigation" measured 70.8–82.1 ms, still outside E3's claim and still the owner's question; resizes
showed 0 ms of the app's own work, so that half did not reproduce. No wave-5 cluster worked on either,
and nothing has re-measured them at `78bdba5`.

**Status at `70bea72`, superseded above.** The re-grade of `443a05a` found this entry's classification contradicted
(E1): swap+submit is J4's own act. Wave 4 redrew the line (R62): the first selection after load is
J1's rep 0, swap+submit is J4 and the palette open is J5, so three of the classes below are now E3
signals on journeys (J5's is O30), not out-of-journey ones. Navigation seeding and resizes, the two
that reproduced at the re-grade of `1d19e22`, are still outside E3's claim and still the owner's
question; nothing since has re-measured them.

**Status at the re-grade of `1d19e22`.** On the quiet host the eight classes below did not reproduce:
seven read worst LoAF 0 ms in all 3 repetitions, and so did path-trace swap+submit. Only "seed a flow
by navigation" (87.3–100.6 ms) and resizes (50.1–63 ms) crossed 50 ms, both outside E3's claim. The
in-journey E3 failure the re-grade found instead was the first selection after load (R51). Wave 3 did
not re-measure these classes. The owner's question stands for the two that reproduced.

**Original entry (wave 2c).**
Found by re-measurement for acceptance.md (provenance cluster, from the e5-sweep 16:30Z report,
3 repetitions, release preview, busy host on battery — laboratory only). Eleven action classes cross
50 ms (worst Long Animation Frame); eight are input-handler interactions outside the declared
journeys: Inspector open on the raw source record 62–144 ms, command palette 98 ms (1 of 3), first
selection after load 93 ms (1 of 3), theme toggles 51–83 ms, clearing the query filter 59–68 ms,
Ctrl+End in the grid 59 ms (1 of 3), path-trace swap+submit 53 ms (1 of 3). `acceptance.md` E3 now says
"no single task over 50 ms" is claimed only on the journeys' paths. Open question for the owner: which,
if any, become journeys or get their work chunked. Not re-measured by the reconciler.

### O22. The determinism gate is keyed on field NAMES — OPEN (shape; owner: `src/core/determinism.test.ts`)
Found by the motion cluster in wave 2c. `FRAME_TIMING_OWNERS` lists frame-timing fields by name, so it
saw the ease channel's `elapsedMs` but cannot see `stepEmphasis`'s identically derived `state.elapsed`,
which was annotated voluntarily. That is a hand-maintained list standing in for the class it means
("a clock-derived value"): the next clock-derived field under a new name reaches a renderer unannounced.
No failing case exists today; the fix is to follow provenance from the rAF timestamp and `performance`
reads (as R15 did for bindings) rather than names. Still open at the re-grade of `1d19e22` (F6 passes,
the shape is unchanged) and not touched in wave 3. The re-grade of `443a05a` found the shape unchanged
(F6 PASS); not touched in wave 4. `FRAME_TIMING_OWNERS` (`determinism.test.ts:258`) still lists
field names; wave 4 added a telemetry field, `qualityAuto` (`telemetry.ts:72`), which is a caller's pin
rather than a frame-time reading, so it is not a failing case — but nothing structural decided that.
The re-grade of `70bea72` did not re-probe it (F6 PASS); `78bdba5` does not change
`determinism.test.ts`. Unchanged, OPEN. **Status at `8eac055`:** the re-grade of `78bdba5` found the
shape unchanged ("keyed on names and accepts unverifiable annotations"; F6 PASS). Wave 6 rewrote
`determinism.test.ts` for load (one parse per text, one case per source file, R85) and left the shape:
`FRAME_TIMING_OWNERS` (`:282`) is still a map of field names. Still OPEN. **Status at `34bd435`:** the
re-grade of `8eac055` found it still open with no failing case (F6 PASS); `determinism.test.ts` is not
in wave 7's diff and `FRAME_TIMING_OWNERS` is still at `:282`. Still OPEN. **Status at `7f67013`:**
the re-grade of `34bd435` found it still open with no failing case (F6 PASS, 32 of 32 frames
byte-identical across 5 runs on a clone's build and 2 on the dev server); `determinism.test.ts` is not in
wave 8's diff. Still OPEN.

### O25. E1–E5 acceptance evidence — MET at `8eac055` and again at `34bd435` by their re-grades (every E criterion PASS, acceptance-grade laboratory, including the E3-across-runs and E4 evidence this entry held open at `34bd435`); wave 8 then changed code on journey paths, so E at `7f67013` rests on its re-grade, which began on battery — OPEN until that grade reports (owner: the re-grade of `7f67013`)
**Status at `7f67013` (wave 8).** The need the old heading named now exists: the re-grade of `34bd435`
ran group E with the host on AC for the whole session, on one `vite preview` of build
`d67f4ef7a4b4530b` ("build: fresh" in every harness), and every E criterion PASSED and was upheld
(laboratory, one host, 60 Hz cap): E1 7 journey ids matching, acts verified 25 of 25; E2 three runs,
each "7 pass, 0 fail, 0 NOT MEASURED", worst p95 64 ms (J2-first, 21 of 21); E3 "across runs of build
d67f4ef7a4b4530b (3 run(s), need 3): PASS", STABLE PASS at 4 of 4 with the refuter; E4 median 60 fps,
worst window 59.98, `acceptanceEvidence=true`; E5 worst keystroke 168 and 184 ms (O20). That report says
the owner can close the old need; it is met. Wave 8 then changed code on journey paths:
`DataGrid`'s reveal and keep on every selection that reaches the queue (R105, R106: a hold armed at
activation, IntersectionObservers, a settle re-check after a frame and a task), the palette's
match-reason rows (R104) and the width ladder every layout reads (R103). What measures E since, all
reported and none acceptance evidence: W8-queue-focus-reveal's one `measure-inp` run on a scratch
preview (J1 p95 32 ms, J2 48 ms, first selection 64 ms, 0 on-path tasks over 50 ms, all 7 PASS; the
harness labelled it NOT ACCEPTANCE EVIDENCE, 1 of 3 runs, build freshness unknown), the J2-only
laboratory run of R107, and the gate's one E5 validation run (O20); the gate ran no `measure-inp` or
`measure-fps`. The unit pin "E3: the click's own commit reads no more layout than the grid did before
this repair" (R106) guards one E3 cost, not E3. The re-grade of `7f67013` began with the host on battery
at 82 %, and its E grader waits up to 60 minutes for AC before measuring (the wave-8 banner).

**Status at `34bd435` (wave 7).** The heading's old wording — "needs quiet, on-AC runs at `8eac055`" —
is superseded: the re-grade of `8eac055` ran group E on AC for the whole session on build
`8666bd0772acf8a5`, 3 grader runs plus 1 refuter run, all ACCEPTANCE EVIDENCE, and every E criterion
PASSED (laboratory, one host, 60 Hz cap): E1 7 journey ids matching; E2 worst p95 48 ms (J4) and 64 ms
for J2-first over 21 of 21; E3 "across runs … (3 run(s), need 3): PASS", upheld at 4; E4 median 60 fps,
worst window 59.98; E5 worst keystroke 160 and 184 ms (O20). That report says "The owner can close"
the old need. Wave 7 then changed code on every journey's path (DataGrid and PriorityQueue, R91; the
preset cards, R92; the Inspector and the JSON tree, R93–R95; the Dialog and Popover primitives and the
palette, R96, R94). Reported, not re-run: the gate's runs on `ba7b456` — `measure-inp` "7 pass, 0 fail,
0 NOT MEASURED", p95 J1 32, J2 40, J3 32, J3b 32, J4 48, J5 32 ms, J2-first 64 ms over 21 of 21, 0 long
tasks, printed "ACCEPTANCE EVIDENCE: release build, hardware renderer, quiet host", E3 across runs
"INSUFFICIENT RUNS" (1 of 3); and the E5 cold load above. No `measure-fps` (E4) run is reported for wave
7, and `34bd435` changed the palette and the JSON tree after the gate's runs, so nothing measures E at
`34bd435` itself.

**Status at `8eac055` (wave 6).** The heading's old wording — "every run since, at `78bdba5`, was on
a busy host … needs quiet, on-AC runs at `78bdba5`" — is superseded. The re-grade of `78bdba5` had no
acceptance-grade E2–E5 run: the host was on battery for the whole session ("13 polls over 60
minutes"), and every run printed NOT ACCEPTANCE EVIDENCE — E2, three laboratory runs "7 pass, 0 fail,
0 NOT MEASURED", worst p95 64 ms (J4), J2-first 80 ms; E3, "0 run(s), need 3: INSUFFICIENT RUNS" (and
the harness judges long tasks, not long frames, O40); E4, "median 60 fps across 10 windows, worst
window 59.99", THROTTLED; E5, a laboratory PASS by 8 ms (O20, O35). E1 PASS, upheld
(`journey-scope.test.ts` 14 of 14; J1–J4 25 of 25; J2-first 21 of 21; J5's dialog watched in 6 of 6
reps). Wave 6 ran no E harness — the gate's reported runs are `capture.mjs`, `capture-motion`,
`audit-d3-focus` and `layout-guard` — and it changed code on every journey's path (the queue, DataGrid,
RecordGrid, the claim surfaces, the camera), so nothing re-establishes E2–E5 at `8eac055`. The host is
now on AC with the dev server idle (the wave-6 banner); the next grading runs E alone.

**Status at `78bdba5` (wave 5).** The heading's old claim — nothing re-established since `1d19e22` —
was superseded by the re-grade of `70bea72`, which had acceptance-grade runs for E1 (PASS), E4 (PASS),
E5 (FAIL, O35) and six of the seven E2/E3 journey ids. `J2-first` had only refused runs, partly because
of the load-meter defect fixed in wave 5 (R78), so E2 and E3 stayed UNPROVEN. The wave-5 runs at
`78bdba5` (all reported; `acceptanceEvidence=false`):
- **E5** (the gate's final build): FAIL, 9 keystrokes over 200 ms, worst 464 ms (O35); host 35 % busy
  (gross 43.6 %, harness 8.5 % by job object, idle baseline 33.5 %), on AC, not throttled.
- **E4** (the gate's regression sweep, `measure-fps` exit 1 twice at 31 % busy, idle baseline 28 %):
  run A focus flights PASS (median 56.67 fps) and orbit FAIL (median 54.2, worst 51.43); the final run
  focus FAIL (median 54.54 against the 55 bar, worst window 50) and orbit PASS (median 55.32). Which leg
  fails flips between runs and both sit on the bar, on the same contended host, so the gate did not
  establish a regression and neither does this record. E4 PASSED at `70bea72` on a quiet host; it needs
  a quiet re-run before any grade.
- **E2/E3** (W5-K4 only, a scratch build at 63 % busy): J1–J4 "acts with a verified effect 25 of 25",
  J2-first 21 of 21 trials measured; no verdict.
- **E1:** `journey-scope.test.ts` and `tracked-sources.test.ts` green in the gate (reported) and in the
  full suite (orchestrator); no headed run.

The gate named the :4180 dev server (a steady 1.56 cores) as the main contention; R80 found why and
fixed it. The accepted runs at `70bea72` predate wave 5's product changes (R67–R77), so nothing
re-establishes E1–E5 at `78bdba5`; the next grading runs E alone, on AC, with the dev server idle.

**Status at `70bea72`, superseded above.** The re-grade of `443a05a` withheld every E2–E5 run as NOT ACCEPTANCE
EVIDENCE (host 46–59 % busy against a 25 % bar) and turned E1 UNPROVEN on scope, which wave 4 fixed in
code (R62). The wave-4 merged-tree gate's runs, on `8e873d2` (reported; `acceptanceEvidence=false`,
so a lead, not a verdict):
- **E2/E3** (`measure-inp`, on battery at the start and on AC at the end, host 47 % busy excluding the
  harness): 7 pass, 0 fail, 0 NOT MEASURED — p95 J1 40, J2 96, J2-first 96 (21 of 21 trials), J3 152,
  J3b 64, J4 64, J5 80 ms. E3 in that run: 6 clean, 1 violating — J5-open-palette's one 114 ms on-path
  task (O30). Across runs: INSUFFICIENT RUNS (0 quiet).
- **E4** (`measure-fps`, on AC, host 36 % busy): FAIL — focus flights median 53.34 fps (worst window
  51.27), orbit median 55.16 with a worst window of 44.51, below the 45 floor, at tier high; the scene
  reported the shortfall itself (`belowBar`).
- **E5, E1:** not run on the merged tree.
The re-grade runs E alone on AC. Nothing here shows a regression, and nothing re-establishes E1–E5 at
`70bea72`. The `review/reports/fps.json` the paragraph below cites was overwritten by the re-grade of
`443a05a`'s E grader.

**Status at `443a05a` (wave 3), superseded above.** At the end of wave 3 the host went onto battery with a Teams meeting in the foreground, and
`review/host-env.mjs` withheld acceptance evidence from every final run. What exists, all reported:
- **E4.** The one acceptance-grade run in the gate — on AC, before the host changed, on the build
  before the R46 `overflow-y` rule (which does not apply on `?s=fabric`) — was PASS: median 60 fps
  across 10 windows, worst window 60, orbit median and worst 60, p95 16.8 ms, tier high, host 25 %
  busy, window inside the screen, `acceptanceEvidence=true`. The final re-run on battery: focus flights
  median 57.83 / worst 55.56, orbit FAIL at a worst window of 39.04 fps with the tier lowered to
  balanced and the drop reported, THROTTLED, `acceptanceEvidence=false`. The reconciler read that
  final run's `review/reports/fps.json` (ignored, 10:00 +0300): `powerSupply: "NotPresent"`,
  `throttled: true`, orbit worst 39.04, `acceptanceEvidence: false` — it matches. The R5 cluster's
  earlier E4 run with the blend: PASS, median 58.9, worst 57.8, host 23 % busy.
- **E2/E3.** The gate's final `measure-inp`: all 7 journeys ≤ 200 ms (J1 p95 32, J2 80, J3 64, J3b
  40, J4 56, J5 48, first selection 80 over 21 of 21 trials) and E3 clean — but on battery, host 32 %
  busy against the 25 % bar; E3's across-runs verdict for that build is INSUFFICIENT RUNS (0 of 3
  quiet runs).
- **E5.** See O20.
- **E1.** No wave-3 run reports it (R1 did not run `measure-inp`, for host contention).
The re-grade's E1/E2/E4/E5 PASS were measured on `1d19e22`; E3 was FAIL there (R51). Record this as host
dependence: nothing in wave 3 is shown to have regressed E1–E5, and nothing re-establishes them at
`443a05a`.

### O27. `review/*.mjs` is outside every type-checked project — OPEN, a declared exclusion (owner: each harness's owner)
Found by the R4 cluster while closing R50: under full strict `checkJs`, 919 diagnostics across 14 of
the 17 harnesses (reported). `scripts-typecheck.test.ts` requires every other authored TS/JS file to be
in a project and names `review/*.mjs` as the one declared class exclusion. The harnesses are the
acceptance instruments, so a type error in one is a measurement defect; closing this needs the
annotations in files other lanes own. **Status at `70bea72`:** unchanged (the re-grade of `443a05a`
found it so). Wave 4 edited five harnesses — `audit-d3-focus`, `audit-e5-sweep`, `capture-motion`,
`layout-guard`, `measure-inp` — which stay outside every type-checked project
(`scripts-typecheck.test.ts:127`, `:200` still name the exclusion). Some of their pure functions are
now executed by unit tests through import (`journey-scope.test.ts`, `Fabric3D.test.tsx`,
`render-c5-repairs.test.ts`), which runs them but does not type-check them. **Status at `78bdba5`:**
unchanged in kind; the re-grade of `70bea72` recorded it as declared (F1 PASS). Wave 5 edited eight
harnesses — `audit-d3-focus` (+301 lines, the sweep, R73), `audit-e5-coldload`, `audit-e5-sweep`,
`host-env` (the job-object meter, R78), `layout-guard`, `measure-fps`, `measure-inp` and
`probe-fabric` (the `--hairline` mode, R68) — all still outside every type-checked project. More of
their code now runs under the suite (`host-load-meter.test.ts` imports `host-env.mjs`;
`acceptance-gates.test.ts` reads the harness sources), which executes it and does not type-check it.
**Status at `8eac055`:** the re-grade of `78bdba5` recorded it still open ("17 review harnesses,
including F-evidence tools, are not type-checked"; F1 PASS). Wave 6 edited two more acceptance
instruments — `audit-d3-focus.mjs` (+196 lines, `operableCensus` and the off-view sweep state, R84) and
`mutation-check.mjs` (three layout mutations, O26) — both still outside every type-checked project.
**Status at `34bd435`:** the re-grade of `8eac055` recorded it still open (F1 PASS, `review/*.mjs`
excluded). Wave 7 edited one acceptance instrument, `mutation-check.mjs` (+175 / −16: the `killedBy`
rule and `--history`, R100), still outside every type-checked project; its many new browser probes were
never added to the repository at all (O45). **Status at `7f67013`:** the re-grade of `34bd435` recorded
it still open ("`review/*.mjs` is in no type-checked project, including every harness this grade relied
on"; F1 PASS). Wave 8 edited three acceptance instruments — `measure-inp.mjs` (the J2 aim, R107),
`audit-e5-coldload.mjs` (+73, the fractional loads, R103) and `capture.mjs` (one note, R108) — and added
a fourth, `probe-a4-surface-switch.mjs` (284 lines, R106), all outside every type-checked project
(`scripts-typecheck.test.ts`, 12 of 12 re-run, still names the exclusion). `Fabric3D.test.tsx` now runs
`discoverJ2Anchors` from its source text against a fake page (R107), which executes it and does not
type-check it. OPEN.

### O28. The A1 census's palette keystroke race — OPEN, harness (owner: the grading harness)
From the re-grade's item 15: typing into Ctrl+K with no gap after opening garbled 53 of 146 queries,
0 with a 150 ms gap. It was not shown that a human would hit it, and no wave-3 cluster addressed it.
Until it is, an A1 census must type after a settle. **Status at `70bea72`:** not addressed in wave 4;
the re-grade of `443a05a` typed its census after a 250 ms settle to avoid it. **Status at `78bdba5`:**
the re-grade of `70bea72` again did not drive the census through all 146 findings for this reason (its
"not examined"); not addressed in wave 5. **Status at `8eac055`:** the re-grade of `78bdba5` lists O28
as not examined, although it did run an A1 census of all 146 findings (`{6, 6, 133, 1}`); whether that census typed after a settle is not recorded. Not addressed in wave 6; the same measurement class — a fixed wait standing in for the
condition — is R82's note on `_ref_a4d.mjs`. OPEN. **Status at `34bd435`:** the re-grade of `8eac055`
typed its A1 census with real keystrokes after a 250 ms settle and recorded 0 URL mismatches, so the
race was not triggered; not addressed in wave 7. OPEN. **Status at `7f67013`:** not exercised by the
re-grade of `34bd435`, whose A1 census drove each finding by pushState and popstate rather than typed
keystrokes (its grader's first census used a fixed 700 ms wait and read F139 stale — the same
measurement class, O47); not addressed in wave 8. OPEN.

### O29. Tracked sources cite gitignored `review/_*.mjs` scratch scripts as their measurement — OPEN, a class (owners: the files named)
Found by W4-R2 while rewording `env.test.ts` (R64); verified by the reconciler. `.gitignore:50` ignores
`review/_*` and `git ls-files 'review/_*'` returns nothing, so a clone cannot re-run any of them
(`review/_audit_cableaa.mjs`, for one, survives only as the untracked
`review/_scratch/_audit_cableaa.mjs`). The reconciler's grep finds such citations in 10 tracked files
under `src/`: three tests (`fabric3d/render-audit.test.tsx:6`, `fabric3d/scene.test.ts:572`,
`fabric3d/geometry/cables.ink.test.ts:11`) and seven product modules' comments (`fabric3d/scene.ts`,
`fabric3d/geometry/cables.ts`, `fabric3d/lighting.ts`, `fabric3d/Fabric3D.tsx`,
`panels/PathTrace.tsx`, `panels/DataGrid.tsx`, `ui/primitives.tsx`). A figure cited that way is a
historical record, not re-runnable evidence, and none of these says so. A guard over the class — like
the one `acceptance-gates.test.ts` now holds for cited tests (R63) — would go red on these files until
each is reworded as `env.test.ts` was or its script is tracked. **Correction and status at
`78bdba5`:** the count above missed a stylesheet — `git grep 'review/_' -- src` also finds
`src/panels/DataGrid.css:140`, which cites `review/_audit_a11y_d4c.mjs` as its measurement, so the class
is 11 tracked files, not 10. Not examined by the re-grade of `70bea72`; not touched in wave 5, which
added no such citation (the only new `review/_` text, in `dev-watch.test.ts`, names `review/_scratch`
as a watched directory, not as evidence). **Status at `8eac055`:** not examined by the re-grade of
`78bdba5`. Wave 6 added no such citation — the reconciler's `git grep -l 'review/_' -- src` names the
same 14 files at `efc3929` and `8eac055` (the 11 above plus `acceptance-gates.test.ts`,
`dev-watch.test.ts` and `env.test.ts`, which guard, name or disclaim rather than cite), and no line
`8eac055` adds contains `review/_`. OPEN. **Status at `34bd435`:** not examined by the re-grade of
`8eac055`. Wave 7 added no such citation: `git grep -l 'review/_' -- src` names 14 files at both
`6a5d830` and `34bd435`, and no line `git diff 6a5d830 34bd435` adds contains `review/_`. The wider
form of the class — evidence that lives only in an untracked scratch location — grew in wave 7 through
its browser probes (O45). OPEN. **Status at `7f67013`:** not examined by the re-grade of `34bd435`.
Wave 8 added no such citation: `git grep -l 'review/_' -- src` names the same 14 files at `7f67013`,
and no line `git diff fea2037 7f67013` adds contains `review/_` or a scratchpad path. The wider form
shrank by two instruments — the A4 replay probe and the fractional cold loads are now tracked (R106,
R103) — and grew by the wave's other scratch probes (O48). OPEN.

### O30. E3 — `J5-open-palette` put a task over 50 ms on its path in busy runs — NOT REPRODUCED on a quiet host at the re-grade of `70bea72`, nor in the quiet runs at `8eac055`, nor in the three quiet runs at `34bd435` the last heading asked for, which its grader reports settle it; kept only as a watch because wave 8 changed the palette's match-reason rows (owner: the re-grade of `7f67013`)
**Status at `7f67013`.** The re-grade of `34bd435` (acceptance-grade laboratory, on AC): J5 E3-clean in
3 of 3 grader runs and 4 of 4 with the refuter, and its grader "reports this settles O30"; J5 p95 32 ms
in its E2 figures. Wave 8 changed what the palette renders for a search hit (`MatchReason`: the field's
words, or an identifier in `<code>` with `<wbr>` breaks, R104), not its open path; the one `measure-inp`
run since (W8-queue-focus-reveal, NOT ACCEPTANCE EVIDENCE) reports all 7 journeys PASS with 0 on-path
tasks over 50 ms. Nothing here is a defect; the re-grade of `7f67013`'s J5 runs are the check.

**Status at `34bd435`.** The quiet runs the old heading waited for exist: at the re-grade of
`8eac055` J5 was E3-clean in 3 of 3 grader runs and 4 of 4 overall (acceptance-grade laboratory). One
native-viewport lead of 52–85 ms came from a run `host-env` refused (`fits=false`) and did not repeat in
2 valid runs (O44). Wave 7 then added a coverage line to the palette (R96) and changed its rows (R93,
R94); the gate's single `measure-inp` run on `ba7b456` (reported) gives J5 p95 32 ms and no long task.
Three quiet runs at `34bd435` would settle it.

**Status at `8eac055`.** The re-grade of `78bdba5`: J5 E3-clean in 3 laboratory runs, on battery, so
not acceptance evidence. `CommandPalette.tsx` is not in `8eac055`. Still a lead until a quiet run.

**Status at `78bdba5`.** The re-grade of `70bea72` ran J5 on a quiet host: E3-clean in 3 of 3 runs;
its one 51 ms on-path task ("style/layout/paint-only; no script over 5 ms") was in a busy run. The
"run after run" of the old heading held only on busy hosts. Wave 5 did not change the palette's open
path (W5-K2, reported) but did change what its rows render (R69's unclamped verdict details), so a quiet
J5 run at `78bdba5` is still the check.

**Original entry.** Every measurement is on a busy host, so none is acceptance evidence. The re-grade of `443a05a`: J5
violated E3 in 3 of 3 runs (worst 94 ms, `#document.onkeydown` in the mount chunk, forced layout
41 ms) and in 5 of the 6 records for that build in `review/reports/inp-e3-history/`; E3 "leans FAIL"
there. The wave-4 gate at `8e873d2` (47 % busy, on battery at the start): one 114 ms on-path task
(`#document.onkeydown`, 33 ms of forced layout). Since R62, Ctrl+K open is J5's own act, so this is a
journey signal, not an out-of-journey one. No wave-4 cluster worked on it; 3 quiet, on-AC runs decide
it (the re-grade runs E alone on AC).

### O31. `measure-inp`'s J2 page does not wait for the scene to settle before its loop — the symptom NOT REPRODUCED at the re-grades of `70bea72`, `8eac055` and `34bd435`; the inconsistency in code stands at `7f67013`, where wave 8 rewrote J2's anchor discovery (R107) but not this wait — OPEN, harness lead (owner: `review/measure-inp.mjs`)
Reported by W4-R2: in a floor-lane dev-server run on a loaded host all 3 J2 clicks "selected
nothing". Verified in code: `FIRST_SELECTION.beforeClick` waits for `stats().converged`
(`measure-inp.mjs:755`), while each journey's page waits only for its ready selector and 2,500 ms
(`:1100–1101`). The same read-only settle wait before J2's loop would make the two consistent. Not
reproduced by the reconciler. **Status at `78bdba5`:** the re-grade of `70bea72` verified J2's effect
25 of 25 in every run, so the symptom did not recur; W5-K4 reported J1–J4 25 of 25 on a busy host.
Wave 5 edited `measure-inp.mjs` for the meter (R78) and left the two waits as they were (now `:757–758`
and `:1105`, re-read by the reconciler). **Status at `8eac055`:** not examined by the re-grade of
`78bdba5`, whose E runs report J1–J4 "acts with a verified effect 25 of 25" (battery, laboratory);
`8eac055` does not change `measure-inp.mjs`. OPEN. **Status at `34bd435`:** the re-grade of `8eac055`
saw 25 of 25 verified effects in every run, so the symptom did not recur; `measure-inp.mjs` is not in
wave 7's diff, so the inconsistency in code stands. OPEN. **Status at `7f67013`:** the re-grade of
`34bd435` saw 25 of 25 verified effects in every run and did not examine the code (its "not
examined"). Wave 8 rewrote J2's anchor discovery (R107), which runs in a throwaway browser through
`FIRST_SELECTION.beforeClick` — canvas, then `stats().converged`, then 2,500 ms (`measure-inp.mjs:822–826`,
and the call at `:1005`) — so the anchors are now projections of the CONVERGED scene; the measured J2
page still waits only for its ready selector and 2,500 ms (`:1188–1189`, re-read by the reconciler).
The two waits are still inconsistent, and the anchors now depend more on the pose the loop may not yet
have reached. Each rep's effect check still names the device it aimed at, so a miss would show as a
failed effect, not a silent sample. OPEN.

### O33. Two engine guards are bounded but cannot be exercised on this snapshot — NOT CLOSABLE IN CODE on this data
Reported by W4-R5, consistent with the code read by the reconciler. (1) `buildSuggestions`'
"unevaluable" suggestion (`engine.ts:2879`) used to map any non-udp/icmp line protocol (gre, esp…) to a
tcp flow and say the line "could match this flow"; it now picks only a line whose `matchTri` against
the built flow is not "no", but removing that guard leaves every test green, because no collected
line reaches the branch with an excluding protocol or port. (2) Removing `COUNTEREXAMPLE_CANDIDATE_CAP`
(48) also survives: no request on this snapshot has more than 8 candidates. Each becomes provable only
with producer data: an ACL line of another protocol reaching the unevaluable-suggestion branch, and a
counterexample search with more than 48 candidates. **Status at `78bdba5`:** not examined by the
re-grade of `70bea72`. Wave 5 reworded `buildSuggestions`' rationales (R69) and, by W5-K2's report,
left both guards untouched; the reconciler finds `COUNTEREXAMPLE_CANDIDATE_CAP = 48` at `engine.ts:2770`
and no `matchTri` or cap line in `78bdba5`'s `engine.ts` diff. Still NOT CLOSABLE IN CODE on this data.
**Status at `8eac055`:** not examined by the re-grade of `78bdba5`. Wave 6 rewrote many engine
sentences to carry their cites (R81, 116 changed lines in `engine.ts`); the reconciler finds no
`matchTri` or cap line in that diff and `COUNTEREXAMPLE_CANDIDATE_CAP = 48` now at `engine.ts:2786`.
Still NOT CLOSABLE IN CODE on this data. **Status at `34bd435`:** not examined by the re-grade of
`8eac055`; wave 7 changed nothing under `src/forwarding/`, and the cap is still at `engine.ts:2786`.
Still NOT CLOSABLE IN CODE on this data. **Status at `7f67013`:** not examined by the re-grade of
`34bd435`; wave 8 changed nothing under `src/forwarding/`, and the cap is still at `engine.ts:2786`.
Still NOT CLOSABLE IN CODE on this data: it needs an ACL line of another protocol that reaches the
unevaluable-suggestion branch, and a counterexample search with more than 48 candidates.

### O34. A2 and F3 — UNPROVEN at every re-grade since `443a05a` (last at `34bd435`), and neither can be moved by code in Atlas Scope — NOT CLOSABLE IN CODE; F3's pre-fix history is wider than this entry first said (corrected at `8eac055`), and its one harness gap was fixed in wave 7 (R100)
- **A2** (depth). The shipped snapshot's maximum depth is 1 with 0 resolved next hops (the depth
  ratchet asserts `toBe(1)`), so the second hop's decider, hop-to-hop navigation, `resolveNextHost`'s
  cable-map branch, the TTL cut and the loop detector have never run on real data. It needs a snapshot
  with depth-2 flows — the kind of data O13 needs for B8. See R18 and R45.
- **F3** (historical red-before-fix). Proven by history only for the O15 provenance tests
  (`254694b` → `1d19e22`); for the forwarding, blast, layout, query, compiler and claims engines it
  rests on today's-code mutations (`mutation-check.mjs`, 18 of 18 KILLED, reported). There is no
  history before `50a3dc5` to show more. The checkpoint commits `254694b` and `2d9712c` put some later
  tests on record before their fixes; that does not reach the engines' original defects.
- **Status at `78bdba5`.** Both confirmed by the re-grade of `70bea72`: A2 UNPROVEN (the ratchet still
  asserts depth `toBe(1)`); F3 UNPROVEN (18 mutations KILLED, real pre-fix red only for R34 and O15,
  about 10 confirmed engine defects with no executable red check). Wave 5's clusters each report their
  new tests red before the fix (R67–R80), which serves F3 going forward and not the old engines'
  history; those reds were observed in the agents' working trees, and wave 5 committed no red
  checkpoint, so none of them is in this history either. NOT CLOSABLE IN CODE.
- **Status at `8eac055`.** Both confirmed by the re-grade of `78bdba5`: A2 UNPROVEN (the ratchet
  `engine.test.ts:1051` still asserts depth `toBe(1)`, re-read by the reconciler); F3 UNPROVEN (18 of 18
  mutations KILLED). **Correction — the F3 bullet above is contradicted by history** (that re-grade's
  new item 8; its runs, not re-run by the reconciler): the forwarding R17 regression tests reproduce red
  against `50a3dc5` ("5 failed and 1 passed"), because the root holds the forwarding engine from before
  R17, and claims C2/C3 against `254694b` ("2 failed and 37 passed"). So "proven by history only for
  the O15 provenance tests" and the Status line's "real pre-fix red only for R34 and O15" were both
  too narrow. What history does not reach is blast, layout, query and the compiler (their guards
  predate the root) and forwarding §1.1, R19 and §1.2 (not checked against history). The re-grade also
  notes the compiler was refuted only for what it drops, not for fields it transforms, and that
  `layout-nonfinite-option` is killed only by an error-message mismatch. The documents that still say
  otherwise are O39. `mutation-check.mjs` now holds 21 mutations (`--list`), three of them added for O26
  and KILLED in the reconciler's `--only` run. Wave 6's clusters report their new tests red before the
  fix (R81–R89), observed in working trees; no red checkpoint was committed, so none of those reds is in
  this history. A2 is NOT CLOSABLE IN CODE; F3's remaining gap is history that does not exist.
- **Status at `34bd435`.** Both confirmed by the re-grade of `8eac055`: A2 UNPROVEN (every reachable
  trace is 1 hop; `engine.test.ts:1051` still asserts depth `toBe(1)`, re-read by the reconciler at
  `34bd435`); F3 UNPROVEN (21 of 21 KILLED; R17's red reproduced from `50a3dc5`, "Tests 5 failed | 1
  passed (6)"). Of the re-grade's F3 gap, the `layout-nonfinite-option` message-mismatch kill is FIXED
  (R100; the reconciler's `--only` run KILLED it by its targeted assertion), and the documents now say
  where history exists (O39, moved to Resolved). What stays: blast, layout, query and the compiler have
  guards older than the root, so "failed before the fix" cannot be shown for them from history. History
  is now 16 commits (`--history`); wave 7's clusters report their new tests red before each fix,
  observed in working trees, and wave 7 committed no red checkpoint, so none of those reds is in this
  history either. A2 needs depth-2 data; F3's remaining gap is history that does not exist.
- **Status at `7f67013`.** Both confirmed by the re-grade of `34bd435`: A2 UNPROVEN (`.hop` count 1,
  "Hop 1 of 1: core1"; `engine.test.ts` 79 of 79 with the depth ratchet at `:1051`, `toBe(1)`;
  `multihop.test.tsx` is a fixture); F3 UNPROVEN (`mutation-check.mjs` 21 of 21 KILLED; R17's red reproduced
  from `50a3dc5`, "Tests 5 failed | 1 passed (6)", and its green from `254694b`; `--history` shows blast,
  layout, query and compiler guards "in root (no pre-fix commit)"). Wave 8 changed nothing under
  `src/forwarding/` or `review/mutation-check.mjs`. History is now 18 commits (the reconciler's
  `--history`, root `50a3dc5`). The pre-fix code of wave 8's defects is in this history
  (`fea2037`), and the clusters report their new tests red against it, served separately or
  swapped in (R103–R107, reported) — the method that reproduced R17 from `50a3dc5`. That serves F3 for
  these defects; it does not reach the blast, layout, query and compiler guards, whose pre-fix code
  predates the root. A2 is NOT CLOSABLE IN CODE
  (it needs a snapshot with depth-2 flows); F3's remaining gap is history that does not exist.
- **Status at phase 2 (2026-09-27).** A2's data now exists in scratch: E2's substrate (R111) regenerated
  through the real compilers and engine gives, over `engine.test.ts`'s depth-ratchet set of 3,249
  traces, hop depths {0: 2,574, 1: 343, 2: 332} and 332 resolved next hops (reported) — the first depth-2
  flows — but 0 definite and 0 decided outcomes, so A2's "the route or ACL line that decided it" at hop
  2 is still not reached; that is O53's owner decision. The committed snapshot, and so the ratchet's
  `toBe(1)`, are unchanged until phase 3 regenerates it. F3 is unchanged; phase 2's clusters report
  their new tests red before each fix, observed in working trees (R109–R115), and nothing is committed.
- **Status at phases 3 and 3.5 (2026-09-30).** The shipped data now has A2's decided hop-2 outcomes:
  the depth ratchet moved into the golden tier and asserts depths {0: 2,574, 1: 343, 2: 332}, 9 definite
  deliveries and 23 decided outcomes, and the product offers decided multi-hop presets naming the deciding
  route or ACL line (R121). **A2 stays UNPROVEN** until a re-grade reads it; none ran (owner instruction).
  F3 is unchanged in kind: the phase-3 and 3.5 clusters report red-before-fix and mutation checks in their
  working trees (reported, not re-run by the record step).

### O35. E5 — keystrokes of 240–464 ms after first paint during a cold load — NOT REPRODUCED in the acceptance-grade runs at `8eac055` or `34bd435` (worst 184 ms at each); kept OPEN as a margin watch (owner: the shell, surfaces and DataGrid/PriorityQueue owners; `src/fabric3d` for `createScene`); the cost is measured and attributed, and since R80 it can be measured on a quiet host
**Status at `7f67013` (wave 8).** The re-grade of `34bd435` (acceptance-grade, on AC) did not reproduce
it: worst accepted keystrokes 168 ms (grader) and 184 ms (refuter, aimed into the Fabric3D warm-up frame
over 19 more cold loads), no frame over 200 ms; it keeps the entry open "as a margin watch". Wave 8 did
not work on the first frame, and it did change code in it: every `DataGrid` now installs, on mount, the
keep and watch machinery of R105 and R106 (an IntersectionObserver, a body ResizeObserver, window resize
and document scroll listeners), and every `useLadder` holds three `matchMedia` subscriptions
(`useAtLeast`, `surfaces.tsx:163–167`, R103). Nothing acceptance-grade has measured `7f67013`; the gate's one
`ATLAS_RUNS=1` cold load (reported, O20) validated the harness, not the margin. The attribution below is
unchanged in code: the queue still asks for windowing only in compact density (`PriorityQueue.tsx:2576`,
threshold 200 > 146), which wave 8 did not change.

**Status at `34bd435` (wave 7).** The re-grade of `8eac055`, on a quiet host on AC with acceptance
evidence, did not reproduce it: worst accepted keystrokes 160, 144, 168 and 184 ms, no frame over 200
ms. That report keeps the entry open "as a margin watch", because of the 240–464 ms history and a
non-evidence run of 224 ms on a build flagged NOT FRESH (O44). Wave 7 did not work on the first frame,
and it did change code in it: a `getSnapshotBeforeUpdate` read of the visible rows on every act
(reported 0.6 ms median, 1 ms max, R91), a coverage line in every overlay (R96), and citation controls
on the preset cards and in the device pane's raw dump (R92, R93). Reported, not re-run: the gate's cold
load on `ba7b456`, worst keystroke 160 ms (the `8eac055` figure had been 184), worst frame 105.2 ms,
first paint 172–196 ms. Nothing has measured `34bd435` itself. The attribution and the refused frame
split below are unchanged in code (the queue still asks for windowing only in compact density,
`PriorityQueue.tsx:2576` at `34bd435`, threshold 200 > 146).

**Status at `8eac055` (wave 6).** The re-grade of `78bdba5` had only a laboratory run, on battery:
worst keystroke 192 ms, first paint 204–228 ms. That contradicts "still failing at `78bdba5`" below —
which came from the wave-5 gate's run at 35 % busy — but is not acceptance evidence and cannot
overturn the acceptance-grade FAIL at `70bea72`; a quiet, on-AC run decides it. Wave 6 did not work
on the first frame, and it did change code in it: the queue's pinned group and a ResizeObserver hold
(R82), the DataGrid reveal measurement and re-aim (R87, R88), a layout effect on every RecordGrid
commit and a MutationObserver per grid (R89), and a citation control per in-sentence cite on the claim
surfaces (R81). No E5 run has measured any of it. The attribution below is unchanged in code: the queue
still asks for windowing only in compact density (`PriorityQueue.tsx:2564` at `8eac055`, threshold 200 >
146), and `useRowWindow` still returns every row while unmeasured (`DataGrid.tsx:340`).

**Found** by the re-grade of `70bea72` (E5 FAIL, new item 6) in two acceptance-grade invocations
(`acceptanceEvidence=true`, busy 0.241 and 0.24, on AC): 8 and 5 keystrokes over 200 ms, worst 400 ms
(keydown at 1114.8 ms, input delay 87 ms) and 280 ms, all after first paint (FCP 652–800 ms), so the
O20 carve-out does not bear on it. **Still failing at `78bdba5`** (the gate's final build, reported; NOT
ACCEPTANCE EVIDENCE at 35 % busy): "9 keystroke(s) over 200 ms (worst 464 ms)", plus 3 pre-first-paint
frames of 269.7–486.7 ms with blocking 0 that count only because the carve-out is unsanctioned.

**Measured attribution (W5-K4, two passes; reported — traces in the orchestrating session's scratchpad,
not re-run by the reconciler).** The keystrokes are presentation-bound — input delay ~10 ms,
processing ~0.1 ms — and wait behind the first application frame. On fresh headed loads at 1920x1080
that frame has a median of 215 ms, of which a median of 185 ms is forced style and layout of the whole
document (a first-pass trace: a 162 ms React task with ~11–15 ms of script, 44 ms of style recalc and a
105 ms forced layout). Trace stacks mapped through the build's source maps put the forcing
(UpdateLayoutTree 41–45 ms, Layout 96–99 ms) at the synchronous `decide()` that ends the queue's
fold-decision layout effect (`PriorityQueue.tsx:887` on the tree measured; `:910` at `78bdba5`, after
the gate's R76 edit), and its ResizeObserver callback (15–18 ms). **That reader is not the cost:** with
the synchronous `decide()` removed (A/B, 5 fresh headed loads each) the forcing moved to the next
geometry reader — forced median 185 → 198 ms, commit frame 215 → 223 ms, max keydown 264–352 → 296–480
ms. The cost is the size of the first frame. The grid's share (headless, 5 loads each, forced
style+layout in the commit frame): all 146 rows 116 ms, rows past the 40th hidden 90 ms, all rows hidden
71 ms — windowing the grid alone would save ~25–45 ms, and ~70 ms is the rest of the app. The DOM at
1920 is 3,867 elements, 3,032 of them the 146-row grid, which is never windowed on load: the queue asks
for windowing only in compact density (`PriorityQueue.tsx:2243`, threshold 200 > 146) and
`useRowWindow` returns every row while unmeasured (`DataGrid.tsx:339–340`), i.e. on every first commit
(both verified in code). The GPU raster of the first full paint (~140 + 90 ms in a fresh profile) falls
to 14–26 ms in a warm persistent profile with the HTTP cache cleared; even warm, keystrokes in the
first-commit frame measured 200–264 ms (4 of 6 loads over 200), so the main-thread frame alone crosses
the bar. A later cost, `createScene` called from the stage effect (`Fabric3D.tsx:589` at `78bdba5`) in
one 140–192 ms task, held one measured keystroke at 184 ms (161 ms input delay) — under the bar.

**What would close it, and why the gate refused it in wave 5.** Split the first application frame:
commit the shell and the visible regions first and hand the rest (rows beyond the first viewport, long
rail lists, anything below the fold) to a follow-up transition after the first frame is presented
(target: no frame over ~120 ms of main-thread time); with it, defer the fold's first decision past
paint, and give the grid an AT-honest progressive first mount (the first viewport of rows,
`aria-rowcount` = total, correct `aria-rowindex`); optionally split `createScene` at its four measured
boundaries. Fixed-height windowing at every density is not directly implementable (comfortable rows are
32–56 px auto-height), and `content-visibility` was removed for AT correctness (`DataGrid.css:227–237`,
verified). The gate refused all four requests (reported): the frame split is the open defect itself, an
architectural change with accessibility reach, and "no frame over ~120 ms" can be encoded only by the
headed E5 harness on a quiet host, which it did not have (the dev server at 1.56 cores, R80); deferring
`decide()` alone measured as a regression; the progressive mount alone does not bring the frame under
the bar and changes D2's row semantics (End, PageDown over unmounted rows); the `createScene` keystroke
is under the bar, and an async split changes the stage effect's unmount semantics. **Now measurable:**
R80 removed the dev server's load (the orchestrator's post-restart read: host CPU 2 %, on AC at 100 %),
so the A/B of a frame split that the gate could not measure can now be run on a quiet host (not yet
run). No pre-first-paint exemption was added or assumed.

**OWNER DECISION, recorded (W5-K4):** `audit-e5-coldload.mjs` launches a fresh browser profile per
run, so the GPU shader and program cache is always cold; K4 attributes to the same cause a 351 ms
pre-first-paint frame with no page script and blocking 0 in its lab run. Whether E5's "cold load" means a cold HTTP cache or a
never-used browser profile is the owner's to decide. It would not rescue E5: the warm-profile
keystrokes still crossed 200 ms.

### O36. B1 latent — the compiler would render a future null, "-", "N/A" or NOT OBSERVED severity as an "Info" finding — OPEN (owner: `tools/compile-snapshot.mjs`)
Found by the re-grade of `70bea72` (B1 PASS, with this latent note; new item 9). Verified in code at
`78bdba5`: `tools/compile-snapshot.mjs:332` and `:350` compile `severity: val(…) ?? "Info"`, and `:352`
`title: val(c.title) ?? ""`. No null severity reaches either site on the shipped snapshot, so nothing
renders wrong today; a producer that later emits one would get a benign Info finding — absence rendered
as health. No wave-5 cluster owned it, and the re-grade's refuter did not execute the path against a
mutated snapshot. Fix: carry the null to a "severity not recorded" reading, or stop the compile on it as
`PUNCHLIST_FIELDS` does for an unknown key (O12), with a test that plants a null. OPEN; not failing on
this data. **Wider, at `8eac055`** (the re-grade of `78bdba5`, new item 7; verified in code by the
reconciler): `val()` (`tools/compile-snapshot.mjs:32–41`) maps `""`, `"-"`, `"N/A"`, any
`NOT_OBSERVED` marker and non-finite numbers to null as well, so any of them in a severity compiles to
"Info" at `:332` and `:350`. The planted-value test should plant each of those forms. `8eac055`
changes nothing under `tools/`. OPEN; not failing on this data. **Status at `34bd435`:** confirmed
latent by the re-grade of `8eac055` (the source severities are Critical 3, High 104, Medium 33 and Low
6, so `?? "Info"` is not reached); wave 7 changed nothing under `tools/`, and both sites are still at
`:332` and `:350`. OPEN; not failing on this data. **Status at `7f67013`:** confirmed latent again by
the re-grade of `34bd435` (`:332/350` `?? "Info"` not reached: source severities Critical 3, High 104,
Medium 33, Low 6; cross_layer Critical 2, High 40, Medium 1); wave 8 changed nothing under `tools/`.
OPEN; not failing on this data.

### O37. Observations from the re-grade of `70bea72` that no wave-5 cluster addressed — the A5 lead FIXED in wave 6 (R83); the rest OPEN leads, not failures (owners as named)
**Status at `8eac055` (wave 6).** The A5 lead is FIXED (R83), after the re-grade of `78bdba5` promoted
it to a confirmed FAIL. That re-grade confirmed the D6 lead (tree names carry no trace or stranded
marks) without counting it as a D6 failure, addressed the B5 lead in grading with an isolated
`evaluateAcls` check (the unit test itself unchanged), and did not re-measure the A4 `aria-current` lag,
the idle rAF loops, the E4 AO suspension, the D3 status-bar overflow or the palette-input boundary.
Wave 6 edited `FabricLabels.tsx` (R84) without reporting on its rAF loop; W6-a4's measurement of the
palette's own URL commit at 1.1–6.9 s after Enter on a loaded host (R82) bears on the A4 lag lead but
is not a measurement of it. The remaining bullets are unchanged, OPEN leads. **Status at `34bd435`
(wave 7):** the re-grade of `8eac055` found the D6 lead standing (the tree carries no trace marks, and
its refuter judged a marker not selectable) and the idle rAF loop still ticking at about 70 frames/s with
no pixel change (C6 PASS regardless); it did not re-measure the others. Wave 7 changed none of
`scene.ts`, `FabricLabels.tsx`, `FabricA11yTree.tsx`, `postfx.ts` or `camera.ts`; its new status-bar
statement (R96) does not bear on the D3 overflow lead, which no one re-measured. **Status at `7f67013`
(wave 8):** the re-grade of `34bd435` did not re-measure these leads (D6 upheld on the AX tree, C6 upheld
with byte-identical idle frames, A4 re-graded on another shape, R106). Wave 8 changed none of the five
files above; it changed the queue grid's reveal (R105, R106), and no one measured the A4
`aria-current` lag against it.
The gate's D3 audit at 390 reports 289 of 289 stops visible (reported), which judges the visible part
of each stop and does not settle the status-bar overflow lead.

From the report's new item 10 (its first observation, the B8 heading, is R70). None was re-measured at
`78bdba5`.
- **A4:** the queue's `aria-current` lagged the URL by 0.5–3 s under load, always converging (owner: the
  queue).
- **A5:** Reset view does not cancel the OrbitControls damping tail (`camera.ts`): a reset 0.3 s after a
  drag release landed at 547,54 instead of 474,82 (owner: `camera.ts`, which `78bdba5` does not change).
- **Idle rAF loops:** `scene.ts:2768` and `FabricLabels.tsx:320` (at `70bea72`) ran 241 calls each in
  4 s at idle with no visible change (owner: the render owner). Wave 5 edited both files; no cluster
  reported touching the loops.
- **E4:** "tier high" suspends ambient occlusion while the camera moves (`postfx.ts` `setMotion`),
  disclosed in `qualityReasons` but not in `acceptance.md` or `measure-fps`'s report (owner: E4's
  criterion and harness).
- **B5:** the established-line unit test would pass without isolating that line; the `evaluateAcls`
  tests do isolate it (owner: `engine.test.ts`).
- **D6:** the fabric tree's item names carry no trace or stranded marks; W5-K1 listed it as optional and
  did not do it (owner: `FabricA11yTree.tsx`).
- **D3 leads:** status-bar buttons partly overflow at 768, 1000 and 390 px; W5-K3 measured "claim
  strength" reaching x=421 in a 390 px viewport (reported), and its sweep judges only the visible part
  (owner: the status bar).
- **The palette search input** has no boundary of its own (1.38:1 on an inner divider) (owner: the
  palette).

### O40. E3's harness judges long tasks, not long animation frames — a 51.7 ms frame overlapping J2-first was not counted — OPEN, harness (owner: `review/measure-inp.mjs`) (re-grade of `78bdba5`, new item 9)
From the re-grade's E3 row: "A 51.7 ms LoAF overlapped a first selection, but the harness does not
count frames as tasks." So E3's axis cannot see a frame over 50 ms made of shorter tasks. Laboratory,
on battery; not re-measured. `measure-inp.mjs` is not in `8eac055`. Whether E3's "task over 50 ms"
means a long task or a long animation frame is the criterion owner's to state; until then the harness
should report both. OPEN. **Status at `34bd435`:** the re-grade of `8eac055` left the harness as it was
and covered the gap with an independent LoAF probe: 0 frames over 50 ms on J1–J5, with a 120 ms
positive control that the probe caught; `measure-inp.mjs` is not in wave 7's diff. OPEN. **Status at
`7f67013`:** the re-grade of `34bd435` found that J2-first now reports the worst overlapping LoAF;
whether the other journeys judge LoAF was not checked. Wave 8 edited `measure-inp.mjs` for J2's anchor
aim only (R107) and left E3's axis as it was. OPEN.

### O41. Observations from the re-grade of `78bdba5` that no wave-6 cluster addressed — OPEN leads, not failures (owners as named) (its new items 4 (leads), 10 and 11); the stale 06 manifest note FIXED in wave 8 (R108)
**Status at `7f67013`.** The re-grade of `34bd435` did not re-check the 768 partial-ring lead; it found
a separate, FULL hide at 390 (a D3 FAIL, its new item 3), which wave 8 fixed (R105) — a different stop
from this entry's ring. It reproduced the C2 scroll-edge cut in state 06 (light/1920: "Under the collected
RIBs of core1 and core2 only (2 of 26") and recorded the stale "BLOCKED verdict marker" note, which the
wave-8 gate corrected (R108). Wave 8 did not re-measure the 768 ring in the path-flow state (W8-queue-
focus-reveal's residual; in the audit's tablet states the returned ring reads "202 px at >=3:1 (floor
52)", reported), nor the pointer/label, rail-overlap or "claim strength" leads. The bullets below other
than the manifest note stand.

**Status at `34bd435`.** The re-grade of `8eac055` checked the D3 ring-under-status-bar lead once at
768 and it did not reproduce (one check, not a sweep); reproduced the C2 scroll-edge lead by eye in
state 06 (its new item 9, O44); and did not examine the pointer/label or the rail-overlap leads. W7-B6
reports state 06's last line still cut at the scroll edge, now a citation line (`l3_forwarding[3]`)
instead of the rationale — the same shape, not worse. No wave-7 cluster worked on any of these.

None was re-measured at `8eac055`.
- **The pointer and the label both claim access5** (item 4 lead; W6-d1-d5 recorded the same as an open
  lead): at some poses `scene.project()` reports `visible:true` for an anchor slightly outside the
  canvas, so the label layer clamps the device's name to the stage edge while the off-view pointer says
  "off view" (the refuter's `ptr3-light.png`, and W6-d1-d5's before-capture). Which claim is honest when
  the anchor lies outside the stage is the owner's to decide (`FabricLabels.tsx`'s label on-screen rule
  / `scene.ts` projection visibility).
- **Right-rail text drawn over the finding list** (item 4 lead): "degraded before cutover" over the list
  in the refuter's `ptr3-light-after.png`. Not examined by any wave-6 cluster (owner: the rail layout).
- **C2** (item 10): in the 06 and 08 captures the 06 headline is scrolled 596 px out of view in its
  ~404 px scroll box — R81 made that panel longer, so this may now be worse (unmeasured); scroll ports cut
  a text line in half at their lower edge (the O17 family); "claim strength" shows as a bare legend key
  with no value; and the 06 capture's manifest note says "BLOCKED verdict marker" while the frame shows
  "? UNDECIDED" (owners: the path panel, the status-bar legend, `review/capture.mjs`'s manifest).
- **D3** (item 11): at 768 × 1024 in the path-flow state, the bottom edge of the ring on "What the
  collection gap means" is under the status bar (216 of 1,188 ring pixels). The gate's final `--sweep`
  reports 0 failures, but that sweep judges nine hit points and the visible part of a stop (O37's D3
  note), so it does not settle a partly covered ring (owner: the status bar, R72's scroll padding).

### O42. Decisions wave 6 leaves for the owner — the changed recorded frames (12 path frames in wave 6, more in wave 7), and whether a gesture may take over a programmatic camera move — OWNER DECISION
- **Status at `7f67013`.** The re-grade of `34bd435` did not compare the changed recorded frames with
  the local baseline either (its "not examined"; F6 PASS is a run-to-run comparison, not a baseline
  one). Wave 8 reports no new changed frame: W8-ladder-and-palette's `capture.mjs app` on `fea2037`'s
  build and on its fixed build, back to back, gave 32 of 32 frames byte-identical at 1440 and 1920
  (reported; the later edits in that cluster were CSS comments), and the gate's final `capture.mjs app`
  rendered 32 of 32 but is not reported as a baseline comparison. `review/shots` is still untracked, so
  the baseline exists only on this host. Promoting or rejecting the wave-6 and wave-7 frames remains the
  owner's. The camera-ownership decision is unchanged (wave 8 did not touch `camera.ts`).
- **Status at `34bd435`.** The re-grade of `8eac055` did not compare the 12 frames with the local
  baseline (its "not examined"). Wave 7 changed more frames, none re-baselined (all reported, captured
  into scratch roots, each pair of runs byte-identical): W7-D4's lighter scroll shadow (R98) changes 15
  light frames — 01–04 and 06–08 at 1440 and 1920, and 05 at 1920 — only in a 4-CSS-px band at scroll-region
  bottoms; its selected-label underline (R97) changes 19 comparable frames — states 02, 04, 06, 07 and
  08, both themes, 1440 and 1920 — only in a 2-CSS-px band at the selected label (light/1920/07 did not
  settle in the comparison build and was not compared); and W7-B6's preset restructure (R92) changes
  dark 06 and 08 at 1440 and 1920. `review/shots` is still untracked, so the baseline exists only on this
  host. Promoting or rejecting them remains the owner's.
- **The recorded app frames.** Since R81 the claim, caveats, Filtering row and hop notes carry inline
  citation controls, which lengthen the path panel, so 12 frames of `capture.mjs app` — 05-path-trace,
  06-path-blocked and 08-path-indeterminate in both themes at 1440 and 1920 — differ from the local
  `review/shots/app` baseline; the other 20 are byte-identical (W6-b6, captured into a scratch output,
  not re-baselined; reported). `review/shots` is untracked (`git ls-files review/shots` is empty), so
  that baseline exists only on this host. The re-grade of `78bdba5` graded C2 partly as "all
  byte-identical to the recorded frames"; that comparison will now differ on those 12 by design until the
  owner promotes the new frames or rejects them.
- **A programmatic camera move owns the camera (R83).** A drag, key orbit or wheel made during the
  620 ms tween is discarded; gestures after it lands behave as before. The tests pin this. If the brief
  or a grader expects a gesture to interrupt and take over a tween, that is a design change for the
  owner, not a defect in the fix.

### O43. Leads and residuals from wave 6 — OPEN, not failures (owners as named)
- **Status at `7f67013`.** Not examined by the re-grade of `34bd435`. Wave 8 did not touch
  `Fabric3D.css`, `FabricLabels.tsx`, `cited-text.tsx`, `target-size.test.ts` or `camera.ts`, so R90 still
  has no unit pin and the other bullets are as written. The F2 thrash bullet stands: the orchestrator's
  3,766 of 3,766 and the gate's two green runs (one under a parallel `npm run build`, reported) were not
  run under memory thrash.
- **Status at `34bd435`.** The re-grade of `8eac055` found R90's fix holding in the browser ("9 of 9 hit
  points" on "Hide the legend") and still without a unit pin; `Fabric3D.css` changed in wave 7 only for
  selected states (R97), and no test reads the pairing. The `target-size.test.ts` limits are unchanged:
  the file gained only the D5 brief test (R101). Wave 7 added many more in-prose and in-card citation
  controls (R92, R93), each reported at least 24 px tall; the visual choppiness was not re-judged. The
  other bullets were not re-examined.
- **R90 has no unit pin** (owner: `Fabric3D.css` and the FabricLegend tests): the legend-under-list fix
  rests on a reported browser measurement alone. jsdom cannot hit-test, but a source test over the
  stage's layers, as `sticky-layer.test.ts` does for the status bar, could pin that two left-anchored
  full-height layers cannot both be open uncapped.
- **In-prose citation chips** (owner: `cited-text.tsx` and the `Cite` primitive): they keep the 24 px
  hit area and 14ch minimum width, so in the ~228 px rail each often takes its own line inside the
  sentence — correct but visually choppy, a C-craft item (W6-b6).
- **The pointer can touch the label beneath it** (owner: `FabricLabels.tsx`'s declutter): the label
  declutter does not treat an on-screen pointer as an obstacle; with `?f=F094&d=core2` and a forced
  top-right projection the pointer sat just above core2's "CUT POINT" label. Neither is covered — the
  pointer took 9 of 9 hits (W6-d1-d5, cosmetic).
- **`target-size.test.ts` limits** (owner: the D5 scan): 11 rule groups set neither font-size nor
  line-height and are printed UNDECIDED rather than judged (e.g. `.hdr-snap`, `.pt-form__swap`,
  `.pq-viewbtn`), and the inline axis of a text box is not judged from source; both rest on the browser
  census (R84).
- **A Reset on a ~4 fps host shows as a jump** (owner: E4 and the render owner): on SwiftShader one frame
  gap can exceed the whole 620 ms tween; the landing is exact (R83).
- **F2 under memory thrash** (owner: the next F2 grading): the W6-f2 cluster's runs on a host committing
  20–22 GB on 16 GB failed across many jsdom files, and its final `composite-tabstop` has not run under
  that thrash; the clean-clone runs that passed were CPU-loaded only (R85).

### O44. Observations from the re-grade of `8eac055` that no wave-7 cluster addressed — OPEN leads, not failures (owners as named) (its new items 5, 6 (second half), 9, 10 and 11)
**Status at `7f67013`.** The re-grade of `34bd435` reproduced the C2 placeholder-ink observation
(#5f6775 light, #828da0 dark) and the state-06 scroll-edge cut, and superseded the E-margin figures
with its own (worst accepted E5 keystroke 168 ms grader, 184 ms refuter; O20, O35). Wave 8 did not touch
`claims.ts`, `engine.ts`, `composite-tabstop.test.tsx`, `PathTrace.tsx` or `audit-d3-focus.mjs`, and no
line of its `src` diff mentions a placeholder; the bullets below stand, none re-measured by the reconciler.

None was re-measured by the reconciler; each is as the report states it.
- **B1 latent: copied traces launder "not decided"** (item 5; owner: `src/core/claims.ts` and
  `src/forwarding/engine.ts`). `JSON.parse(JSON.stringify(t))`, `structuredClone` or a spread copy of a
  trace reads `decided=true, band REFUTED` where the original reads UNDETERMINED, because
  `isDecidedOutcome` reads WeakMaps keyed by object identity (`PARTIAL_ROUTE_BASIS`, `GAPS`). No shipped
  clone, worker or `postMessage` path reaches it today. The same mechanism is the report's method
  warning for graders: importing `claims.ts` without the app's `?t=` suffix manufactured 384, 216 and 918
  false "decided" denials in two sweeps (O13). Wave 7 changed only a comment in `claims.ts` and nothing
  in `engine.ts`.
- **F2: `composite-tabstop.test.tsx` pins non-vacuity only for idle at 1440 px** (item 6, second half;
  owner: that file, `:465` at `8eac055`, not in wave 7's diff). The first half is R102.
- **C2 observations** (item 9; owners: the path form, the queue's filter input, the path panel): the
  path-form placeholders ("10.0.10.50", "10.0.30.10", "443") look like entered values while the value
  is `''`; the queue placeholder "severity:Critical" sits beside active Critical and High chips; and
  state 06's "Other questions" card's last line is cut in half at the scroll edge (the O17/O41 family,
  reproduced by eye; W7-B6 reports it still cut, now on a citation line).
- **Thin E margins, all PASS** (item 10; owner: the next acceptance grading): the worst accepted E5
  keystroke 184 ms against a 200 ms bar (native DPR, `?s=fabric&d=core1`); an F-group cold load on a
  build flagged NOT FRESH printed "2 keystroke(s) over 200 ms (worst 224 ms)  [NOT ACCEPTANCE EVIDENCE]"
  (not counted); E4 windows of 51–53 fps at 2.51 MPix; and a J5 on-path lead of 52–85 ms from a
  native-viewport run `host-env` refused (O30). The wave-7 gate's reported runs on `ba7b456` sit inside
  these (O20, O25, O35).
- **Harness notes** (item 11; owners: the harnesses named): the D3 harness never sets a colour scheme;
  `capture-motion`'s fixed output path overwrites the prior report; the pick-based link-contrast scan is
  unreliable because pick areas are wider than the strokes; graders must import engine and claims
  modules with the app's own `?t=` URLs.

### O45. Leads and residuals from wave 7 — OPEN, not failures (owners as named); its 390 "0 not visible" note was contradicted at `34bd435` (a D3 FAIL, fixed in wave 8, R105)
- **Status at `7f67013`.** The re-grade of `34bd435` contradicted the last bullet: at 390 its D3 run
  found "1 of 289 stops not visible", a fully hidden grid cell (its new item 3), which wave 8 fixed
  (R105); the gate's `--vp=390` run after its last edit reads "145 case(s), 0 failed", "289 focus
  stop(s) checked, 0 not visible", SWEEP 0 failures, and exits 1 only on "SWEEP NEVER EXERCISED:
  offViewPointers" — the off-view pointer cannot exist at 390 because the fabric is collapsed there
  (reported). It did not re-examine the A4 transient; wave 8 added a settle re-check for focus that
  arrives from outside the grid (R105), which is not the pick's urgent-commit transient, and its own
  residual of the same family is in O48. The 768 grid-box overflow was not re-measured; wave 8's only
  768 change is the stacked-rung move of `PriorityQueue.css`'s overlapping rule (R103). The two latent
  B6 residuals stand: `rowCite` is at `JsonView.tsx:360`, unchanged, and the palette's "on its Ports tab,
  where this … record is cited" is now at `CommandPalette.tsx:455` (the file changed only for R104). The
  forced-colours and D4-guard bullets are unchanged. Of wave 7's untracked probes, none was adopted;
  wave 8 tracked two instruments of its own (O48).
- **A4's transient** (owner: the queue and `DataGrid`; W7-A4, reported): between the pick's urgent
  commit and the deferred marks commit (about 0.3–1.2 s, headless, release build) the bottom-band row
  sits up to ~22.8 px under the port's edge while the sentence reads "— marking the rows."; the scroll
  position is intact, and the deferred commit restores the row by the least movement (R91). Closing the
  gap needs a post-mutation layout read in the urgent commit, which is the synchronous selection-time
  layout work E3 forbids, so W7-A4 did not add it.
- **At 768 × 1024 the queue grid's box runs to 1048 px in a 1024 px viewport** (owner: the shell layout;
  W7-A4 observation, reported): the status bar cuts it at 998, so it is clipped by the viewport and the
  layout overflows by 24 px; `visibleBand` handles it. `layout-guard.mjs`'s invariant 5 reads where the
  grid PAINTS to (998 at 768, O17), not its box, so it does not see this.
- **Two latent B6 residuals, no instance in this snapshot** (orchestrator, at `34bd435`). (1)
  `rowCite` (`JsonView.tsx:360–363`) returns only the first citation the resolver finds in a row's key
  and string value, so a row carrying two citations opens only the first — verified in code; the
  orchestrator's "no instance" was not re-checked by the reconciler over every document the tree shows.
  (2) The palette announces "Selected <host>, on its Ports tab, where this <kind> record is cited."
  (`CommandPalette.tsx:428`), which would be false for an endpoint whose host has no interface or
  physical records; the reconciler's read of `src/data/fabric.json`: all 50 endpoints sit on 20 hosts,
  and each of them has both interface and physical records, so no instance today. Owner:
  `JsonView.tsx` and `CommandPalette.tsx`.
- **Forced colours drop five of the new selected-state bars** (owner: each stylesheet; the gate's
  statement, not re-attacked): the inset bars the gate added for `.ag__cell`, `.pq-suggest__opt`,
  `.dp-list__row`, `.jsonview__row[data-current-match]` and `.hop[data-active]` are dropped under
  `forced-colors: active`, as the fills they supplement were, and no forced-colors rule gives those
  states their own edge. (An older forced-colors rule draws a dashed `CanvasText` outline on both
  `[data-match]` and `[data-current-match]` JSON rows, `Inspector.css:654–657`, so a current match is
  still not told from a match there.) Not a regression; D8 was checked in forced colours on state 06
  only. R99's tab fix has no unit pin, because the guard excludes forced-colors blocks by design.
- **The D4 guard is a source-and-token tripwire** (owner: `selected-state-contrast.test.ts`): it
  measures declared colours against tokens, not pixels; the rendered D4 evidence for wave 7 is the
  clusters' and the gate's browser probes (reported).
- **Wave 7's evidence probes are not in the repository** (owners: whoever adopts them as instruments):
  `b7-probe2.mjs` (the 270-check coverage probe), `b7r2-popups.mjs` (the 654-check popup probe, which did
  not assert that each combobox's list actually opened), `w7a4-sweep.mjs` and `w7a4-repro.mjs`,
  `d4-rendered.mjs`, `gate-attack.mjs`, `preset.mjs`-style checks and the screenshots live in the
  orchestrating session's scratchpad, so a clone cannot re-run them — O29's class for harnesses rather
  than citations. No tracked file under `src/` cites the scratchpad (the reconciler's `git grep`).
- **`audit-d3-focus.mjs --vp=390` exits 1** only on "SWEEP NEVER EXERCISED: offViewPointers" (the
  off-view state is not reached at that width), which the script labels diagnostic, not an acceptance
  run; W7-B7's run there read "145 case(s), 0 failed" and "289 focus stop(s) … 0 not visible"
  (reported; owner: that harness).

### O46. Decisions wave 7 leaves for the owner — the accent's new use, and which claim owns a selected host's outline — OWNER DECISION
- **Status at `7f67013`.** Not examined by the re-grade of `34bd435`. Wave 8 did not touch
  `design-brief.md` or `Fabric3D.css`, so both decisions are as written. Still OWNER DECISIONS.
- **Accent spending** (owner: `docs/design-brief.md` §3). The brief spends the accent only on "the brand
  mark, the primary action in a dialog, link emphasis, and the active tab underline"
  (`design-brief.md:270`). Wave 7's selected-state indicator is an accent underline or bar on the pane
  switch, the pressed `ui-btn`, the pressed `fabric3d` button, the coverage table's current row, the
  highlighted covpanel sections and the selected 3D label (R97), and the gate used the same bar on grid
  cells, the queue's suggestions, the device list and the JSON tree's current match; it follows
  indicators that already shipped (`ui-tab`, header surface, theme option, treeitem, palette row, grid
  active row). The owner should add "selected-state underline or bar" to that list or choose an
  achromatic indicator; either way the D4 guard measures the result.
- **A selected host that also carries a finding draws the cut-point outline, not the finding's**
  (owner: `Fabric3D.css` claim arbitration; W7-D4 observation, reported, not changed). With
  `s=findings&f=F001&d=core1` the core1 label draws the dashed indeterminate cut outline (specificity
  0,5,0) instead of the critical-red finding outline it draws when unselected. The file arbitrates
  trace against cut explicitly ("the trace's own outline wins") but not finding against cut. The
  selection itself stays legible since R97.

### O47. Observations from the re-grade of `34bd435` that no wave-8 cluster addressed — OPEN leads, not failures (owners as named) (its new items 5, 7, 8, 9 and 10, and one "recorded, not graded" A4 note)
Each is as the report states it; the reconciler re-read the code the second and third bullets cite.
- **E4 beyond the declared target** (item 5; owner: `stepdown.ts` and the E4 owner). At a 1920 × 1080
  viewport, DSF 2, dark theme (a 2322 × 1924 buffer, 4.47 MPix): "focus flights median 53.33 fps ...
  Orbit drag: FAIL — orbit median 46.24 fps (worst window 42.58 fps)", with `host-env` judging the host
  fit. The scene reported `belowBar true`, but the tier stayed `high` although the worst window was
  below the 45 fps step-down floor. Not an overturn: `acceptance.md`'s restated E4 fixes DPR 1, and the
  reference panel cannot produce that canvas; it shows an external HiDPI monitor on the reference
  machine would fall below the bar. Wave 8 did not touch `stepdown.ts`.
- **Latent B6 and B5, no instance on shipped data** (item 7; owners: `blast.ts` and `engine.ts`).
  `blast.ts:2084` falls back to citing `cable_map.cables[id=…]` for a link with no cite of its own, which
  would not resolve — the compiled `fabric.cable_map` has only `nodes` (the reconciler's read of
  `src/data/fabric.json`) — and cites null for an absent link; and the engine ignores the compiled
  `unevaluable: true` on `MGMT_IN[0]` and resolves the group itself. Wave 8 changed neither file.
- **F2 latent branch** (item 8; owner: that test). `band-qualification.surfaces.test.tsx:239`, `if (mesh
  === null) continue`, would skip a qualified host in a chassis group with no collected device; the
  refuter showed no current qualified host reaches it, and only `toBeDefined()` guards it. Unchanged in
  wave 8.
- **Grading-method notes** (item 9; owners: the graders and harnesses). The D4 grader's contrast probe
  filters by `elementFromPoint` and so measures no `pointer-events:none` fabric label; the B grader's "link_centrality[0..24].pairs_cut
  is really 0" is wrong (20 of 25 rows carry 22); the dev server's HMR can split `Inspector.tsx` and
  `DevicePane.tsx` into two module instances during a data recompile, so cites appear dead until a
  fresh navigation (dev-server only); and fixed waits in the A1 census read stale panes (F139 at 700
  ms), the O28 class.
- **C3 depth** (item 10; owner: the queue layout, the O17 family). Across the whole queue at 1440 in
  state 03, 79 of 107 titles are clipped and 39 lose over 20 % (F141 32 %, F082 25 %) in a 122 px title
  column — within the bar, each keeping its subject. Wave 8 did not change the title column.
- **A new trace submit moved the camera** (A4 row, "recorded, not graded"; owner: the trace submit and
  `camera.ts`): core1 went from (474, 82) to (552, 237). Whether a submit may re-frame the fabric was not
  judged, and wave 8 did not examine it.

### O48. Leads and residuals from wave 8 — OPEN, not failures (owners as named)
- **The arrival reveal can still move the page once against a transient overlay** (owner: `DataGrid`;
  W8-queue-focus-reveal, reported). The settle re-check (R105) corrects it within the same frame
  sequence and no net displacement was observed, but a double scroll is possible — the shape R105 fixed,
  reduced to a transient.
- **The A4 replay probe cannot pick a link at 390** (owner: `review/probe-a4-surface-switch.mjs`). Below
  768 there is no canvas, and the palette returns no option for "L33" (0 options at 390 and at 1440, no
  link treeitems; the gate's check), so the probe exits 1 on one "not driven" step — a limit of the
  probe, not a product failure (R106). It needs another narrow-width way to select a link.
- **O41's partial ring at 768 in the path-flow state was not re-measured** (owner: the status bar);
  in the D3 audit's tablet states the returned ring reads "202 px at >=3:1 (floor 52)" (reported).
- **A container ladder outside the viewport-ladder guard** (owner: `PathTrace.css`; W8-ladder-and-palette,
  verified in code): `@container pathtrace` queries at `PathTrace.css:133` (min 34rem), `:641` (max
  30rem) and `:1037` (min 30rem) — `(max-width: 30rem)` and `(min-width: 30rem)` both match at exactly 480 px of container width. They
  style different elements (`.hop__alts`, `.pt-intent__facts`), so no rule pair falls into a gap today;
  if the container ladder gains complementary pairs it has R103's shape, and `breakpoint-ladder.test.ts`
  reads only `@media` conditions.
- **The F4 evidence is one browser at forced scale factors** (owner: the next F4 grading): every
  fractional-width measurement is headed Chromium under `--force-device-scale-factor`, not a physical
  scaled display or another engine — the re-grade's own stated gap, which wave 8 did not close.
- **Wave 8's evidence probes are mostly not in the repository** (owners: whoever adopts them). Tracked
  now: `review/probe-a4-surface-switch.mjs` (R106), the fractional cold loads in
  `review/audit-e5-coldload.mjs` (R103) and the J2 aim's unit pin (R107). In the orchestrating session's
  scratchpad only, so a clone cannot re-run them: the ladder cluster's `f4-frac.mjs` (superseded by the
  tracked loads), the gate's `gate-f4-frac*.mjs` and `gate-sweep.mjs` (the 45-width and regression
  sweeps), the queue cluster's instrumented audit copy and `mutate.cjs`, the J2 cluster's `probe.mjs`,
  `j2-reach.test.mjs` (the real-browser reach test) and `control-preload.mjs` (its positive control), and
  the screenshots — O29's class for harnesses. No tracked file under `src/` cites the scratchpad (the
  reconciler's `git grep`).
- **Wave 8's E figures are laboratory only** (owner: the re-grade of `7f67013`): the queue cluster's one
  `measure-inp` run (J1 p95 32 ms, J2 48 ms) and the J2 cluster's J2-only run each printed NOT ACCEPTANCE
  EVIDENCE (O25).

### O49. Decision wave 8 leaves for the owner — at 768 and 390, after a surface switch, the queue's whole port is scrolled out of view while the selected row stays inside it — OWNER DECISION
From W8-queue-focus-reveal (reported; the probe's preview-build run over four widths). After the Path
switch, the flow submit and the dist1 double-click at 768 (rail A: the queue's band is empty, 1083–998)
and at 390 (the page), the queue's whole scroll port is out of the shared scroller's view; F026 stays in
view inside the grid's own port, and the grid does not scroll the shared rail or page to bring the port
back, because that would move the reader away from the Path panel they just opened. The tracked probe
reports these 5 steps as "QUEUE OFF SCREEN", not IN. The re-grade of `34bd435` measured the failing
sequence at 1920 only, where R106 fixes it. Whether A4 ("re-aiming without losing selection context")
requires the queue itself on screen at the stacked and single-column rungs after the reader chose
another surface — or whether the selected row being kept inside its own port suffices there — is for
the owner and the grader of `7f67013` to decide; the code does not force either reading.

### O50. A1, consumer half — the evidence contract is compiled but NOT RENDERED — FIXED IN CODE in phases 3 and 3.5 (R120); A1 NOT RE-GRADED (kept here for its history)
From S1 (reported; confirmed by the record step: outside tests, the five field names occur under `src/`
only in `src/core/types.ts`). `Finding.severityBasis`, `evidenceConfidence`, `evidenceBasis`,
`evidenceRefs` and `evidenceRefsTotal` are compiled and rendered nowhere. The rendering contract is design brief §5.1
("Per-finding evidence pointers"): render by `evidence_basis` and each ref's `kind`/`role`, never by
basis alone or by word matching; CL-02's interface refs are `role: derived_from` graph-cut links, not
configuration, although the row's basis is `record`; `deduction_refs` pair with deductions by pointer
and cite, not by index; `severityBasis` and `evidenceConfidence` are the producer's words verbatim, even
`N/A`, `-` or `''` (null only when the key was not emitted) — disclosures, never measurements; a capped
list (`evidenceRefsTotal` greater than the refs' length) never reads as complete; a null `evidenceRefs`
means "not emitted", never "no evidence". The shipped `fabric.json` carries none of this until the
sample is regenerated and recompiled (`src/data/fabric.json`'s `meta.sourceGitBlob` still equals the
committed sample's blob, which carries no `evidence_refs` — the record step's `git rev-parse` and
`grep`). A1 is re-graded only after both.

### O51. R6 — the repository golden is a stripped derivative that cannot compile as published — OWNER DECISION
From S1 (reported; the record step's run shows `compile-all.test.ts`'s R6 block red, 5 of 5 — "exits 0
and writes the four files…", "names the golden file…", "all four outputs share one binding…", "compiles
a real network…", "carries the evidence contract exactly where the golden carries it"). The golden
(`tests/golden/snapshot.json`) cites `/device_dossiers/…` in its punch-list refs, a section the golden
harness pops, while its `schema_census` still lists that section as published. The compiler refuses it
with `E_EVIDENCE_REF_UNRESOLVED` and the plain-language reason "sections removed after the engine wrote
it". **For the owner:** keep the cited sections in the golden, or compile the engine's real on-disk
output instead. The R6 tests stay strict and red until then; resolving pointers against a stripped
document or dropping unresolvable refs was refused as a weakening (R112, S1-V1).

### O52. E1's residuals, and a likely CL-02 false-positive class in the engine — OPEN (owners: the engine's fold owners, `build_dependency_map`, `docs/ssot.md`, the COLLECT_PARSE wiring)
All from E1's verifier (reported).
- **A `record` basis the evidence does not support (R4 honesty).** The Config-hygiene fold makes a row
  `record` through a `config_text` ref with `role: subject` and the cite "referencing configuration
  line", but `config_hygiene[h].undefined[i].context` is the enclosing column-0 stanza header, cut to 60
  characters, not the line that holds the reference; for any nested reference the pointer and its cite
  name the wrong line. `software_risk` has the same shape: the ikev1 "evidence" is the synthesized text
  `crypto isakmp policy ...`, typed `config_text` and cited as a configuration line.
- **The identity check verifies an interface ref's HOST, never its PORT.** A fold pointing at the wrong
  port on the right host passes in every published form. Exact-ref unit tests cover L1, Trunk, Link,
  Addressing, CL-02/03 and health deductions; nothing pins the port for CL-01/05/06/07/08/09/10, the
  drift temp-bridge/PoE/native-VLAN-1 refs, or the index-gated FHRP/STP/L3/IPv6 SVI refs. The null-host
  `per_device` absence witnesses are checked only for resolution.
- **A success path never executed in a real run.** `interface_index` is never passed by the production
  pipeline, so the L3 SVI, STP gateway-SVI, FHRP member-SVI and IPv6 adjacency-interface refs exist only
  in unit tests. E1 called the COLLECT_PARSE wiring "optional, recommended"; it is what the per-site list
  needs for those four folds, and in the sample it would move FHRP (4 rows), L3 (1) and STP (1) from
  `row` to `record` (core1/core2/dist1 carry Vlan10/20/30/40/41 interface keys).
- **Two more upstream sections carry the contract unregistered.**
  `multicast_intelligence.risks[*].evidence_refs` and `qos_audit.findings[*].evidence_basis` are not in
  `docs/ssot.md`'s "Per-finding evidence pointers" row, and the checker's upstream-resolution loop
  (`cross_layer` / `health_scores` / `operational_drift`) does not cover `multicast_intelligence.risks`.
- **Two changes that must land together.** The always-published `deduction_refs` turns
  `tests/test_package.py::test_analyze_reexported_and_functional` red in the default gate; E1 does not own
  that file and routed it.
- **Two unstated gaps.** The brief's per-site list named "protocol_health row plus the matching
  routing_neighbors entry" for the Protocol fold; the producer does not hold `routing_neighbors`, and
  nothing records the omission. `_evidence_basis_for` labels a row with ZERO refs `row`, asserting a
  derived-from row that is not there — reached only by direct calls or poisoned inputs (a legacy
  PTP/media row with no refs, L1 rows whose ports are all non-strings), never the golden or sample runs.
- **CL-02 "only L2 transit to the gateway" — a likely false-positive class, pre-existing and unchanged.**
  On the 146-row sample, 20 of 22 such rows are raised for hosts with no forwarding link carrying their
  articulated VLANs: `build_dependency_map`'s articulation loop never compares the stranded set against
  the baseline, so endpoints already stranded make every non-gateway host an "articulation". The fix
  belongs in that predicate, and it changes the golden's and the sample's `cross_layer` and punch-list
  rows.

### O53. A2 and B8 — the forwarding substrate is in place, and decided core1 outcomes are blocked by core1's own FULL/DR OSPF neighbour on an L2 trunk — OWNER DECISION (E2's R3 BLOCKED); DECIDED in phase 2.75 (the link is modelled, on Vlan10: R117) — A2 and B8 stay UNPROVEN until phase 3 regenerates the tracked fleet
**Status (phases 3 and 3.5, 2026-09-30).** Phase 3's precursor (`74275919`) regenerated the tracked fleet
and recompiled the four documents from it, so the scratch figures below are now the shipped data's, and
the golden tier asserts them (R121). A2 and B8 are not re-graded (owner instruction; O13, O34).
**Status (phase 2.75, 2026-09-28).** The owner chose to model the link: the session now runs over
Vlan10, an SVI both cores already have (R117), without loosening the rule. **Scratch acceptance
figures** (T2, reported; the Vlan10-home fleet compiled in scratch with the worktree engine; the tracked
fleet NOT regenerated): `tcp/443 10.0.40.50 -> 10.0.10.50` is a 2-hop DECIDED DEFINITE delivery (dist1
`routes.dist1[1]` > core1 `routes.core1[2]`, no gaps); `tcp/443` and `tcp/3389 10.0.40.50 ->
10.0.30.10` are 2-hop DECIDED denials at `acls.core1.PROTECT_SERVERS[3]`, each with a counterexample
found (-> 10.0.20.10, a 2-hop definite delivery; B8). Sweep (19 addresses, 3,249 traces): depths {0:
2,574, 1: 343, 2: 332}, 332 resolved next hops, **definite 9, decided 23, counterexamples 26 of 70** —
the figures the core1-complete counterfactual below predicted, now reached without forcing anything;
`ribCountQualifier` "(1 of 4 shown incomplete)", core2 only. A2's hop-2 decider and B8's positive state
are exercised on real data only once phase 3 regenerates and recompiles the fleet and a re-grade reads
it (O13, O34); until then the committed snapshot is as below.

From E2 and its verifier (reported). Scratch end to end (HEAD engine plus E2's files, the real compilers
publishing each adjacency's `address` and `interface`, the real forwarding engine, `engine.test.ts`'s
depth-ratchet set of 3,249 traces): hop depths {0: 2,574, 1: 343, 2: 332}, 332 resolved next hops,
**definite 0, decided 0, counterexamples 0 of 70.** core1's table is incomplete by its own FULL/DR OSPF
neighbour 10.0.99.2 on the L2 trunk Po1, whose link the table does not hold
(`routing_neighbors.core1.ospf[0]`) — the fixture's B1 seed — and that alone blocks decided core1
outcomes: forcing only core1 complete, as a counterfactual, gives definite 9, decided 23, counterexamples
26 of 70. The implementer's earlier 9/23/26 came from the per-family rule letting dist1's OSPF routes
vouch for that session, which brought B1 back (R110). **The link fields:** the compiled
`rib-evidence.json`'s adjacency records carried no `address` or `interface` at E2's close, and a session
without them is unknown under the new rule (E2 measured all 4 regenerated tables incomplete that way);
the compiler in this working tree publishes both, copied from the producer record or null
(`compile-model.test.ts`, "the rib evidence carries the link each adjacency runs over", re-run green by
the record step), and the figures above were taken with them published. **For the owner:** how the B1 seed and a decided
core1 coexist — for example, whether the fixture's FULL/DR neighbour on Po1 is kept (and core1 stays
undecided, honestly) or its link is modelled — without loosening the rule. Until then A2's hop-2 decider
and B8's positive state stay unexercised on real data (O13, O34).

### O54. E2's residuals — an unknown read as complete for protocols outside {ospf, eigrp, bgp}, and five more — OPEN (owners: `src/forwarding/rib-completeness.ts`, `webapp/sample_data/build_sample.py`, `cisco_toolkit/bgp_intent.py`, the owner)
From E2's verifier (reported), except where an E2 record says otherwise.
**Status (phase 2.75, 2026-09-28).** The third bullet's section is now INDETERMINATE for a different,
accepted reason — one core1 row, NOT VERIFIED / BLOCKER, because core1's config capture is incomplete —
and the validator reports "valid, ok" over the substrate collection (R118, reported by T2); no report the
record step received says whether `bgp_intent.py`'s producer/validator disagreement over a peerless host
with an EMPTY summary is fixed, so that half stays as written. The last bullet's second half (the sweep
never checked that the table holds the link) is FIXED (R119, R2V-3). The other bullets are unchanged by
any phase-2.75 report.
- **Absence rendered as health (the most serious).** A host whose table holds routes learned by a
  protocol outside the fixed vocabulary {ospf, eigrp, bgp} — IS-IS, RIP, LISP, NHRP, mobile, which
  `parse_ip_routes` emits as `isis`, `rip`, `lisp`, `nhrp` and `mobile`, none with a collection receipt —
  is shown COMPLETE when all three vocabulary families are `captured_empty`, and `ribCompletenessBasis`
  then states that no OSPF/EIGRP/BGP-learned route is missing. The owner's rule is that a protocol with no
  positive empty-capture evidence "stays unknown"; here a family with no receipt reads complete, the
  named-set defect in reverse. Under the HEAD rule the same host read incomplete.
- **The BGP "reached by a route" check does nothing when the scoped table holds a default.** On the
  regenerated fleet core1's peer 203.0.113.1 is reached only by 0.0.0.0/0: the engine's route scoping
  drops the static /32 `build_sample.py` adds so the session would have "a route under it (not only the
  default)". That comment, and the pytest pinning the /32, hold for the collected text but not for the
  snapshot Atlas Scope reads. The rule's own boundary discloses it (R110).
- **The substrate degrades a demo section once phase 3 regenerates the fleet.**
  `bgp_configured_peer_baseline` goes from NOT_APPLICABLE (committed) to INDETERMINATE with rows `[]` and
  "The current-run BGP configured-peer baseline was unavailable" (history: no substrate NOT_APPLICABLE;
  v1 substrate INDETERMINATE with a core1 "BGP CONFIGURED PEER NOT VERIFIED — BLOCKER" row caused by
  core1's config without `end`; v2 as stated). Cause: `cisco_toolkit/bgp_intent.py`
  `compute_bgp_configured_peer_baseline` marks a non-subject host `not_applicable` when its config
  capture is ok and complete, whatever the runtime capture, while `_structural_validation` expects
  `not_verified` when the runtime capture is not in {ok, not_observed}; a peerless switch with an empty
  `show ip bgp summary` fails the whole fleet's baseline with `baseline_coverage_status_mismatch`, and the
  section projects as unavailable. Pinned as a strict xfail in `tests/test_sample_fleet_substrate.py`;
  nothing in E2 stops phase 3 regenerating before the engine fix lands.
- **Realism of the empty BGP capture (OWNER).** The owner directed an empty `show ip bgp summary` on a
  switch with no BGP process; IOS/IOS-XE prints a "% BGP not active" banner, which `cmdio._CISCO_ERRORS`
  does not screen, so a real capture would be usable, read as `captured_no_record`, and leave the table
  unknown. On real fleets dist-style peerless switches would therefore never read complete under this
  rule; the demo's decided dist tables are not field behaviour. Not verifiable here (no egress).
- **Fixture inconsistencies left as they are, outside the rule's reach:** core1 lists an EXSTART
  neighbour 10.0.40.9 on Vlan40, where it has no L3 interface; core1 Vlan30 is `vrf forwarding
  TENANT_RED`, yet 10.0.30.0/24 sits in its global table.
- **Two tests that pin less than they say.** The LF requirement is pinned only at the helper
  (`test_snapshot_writer_emits_lf_only` calls `bs._write_snapshot`; no test drives `main()`, so reverting
  its write to `open(out_path, 'w')` stays green). And `rib-completeness.test.ts`'s real-data sweep
  "every adjacency in a session state is cited as a reason unless the table holds its link" asserts only
  that an uncited session carries the address/interface keys, never that the table holds the link.

### O55. S1's residuals — a sparsify test that sparsifies nothing, Git-ignored but published directories accepted, and a looser evidence contract than the engine's — OPEN (owners: `tools/lib/compile-io.mjs`, `tools/lib/compile-model.mjs`, their tests; one OWNER DECISION)
From S1's verifier (reported).
- **R4's "engine sparse compact form -> byte-identical content" does not test sparsification.** The
  transform removes nothing from the test's base, and its only "the transform did something" check
  (compact bytes under the golden's) passes on compaction alone; a compiler that renders a
  sparsified-away field differently from the dense form still passes.
- **A Git-ignored directory is not an unpublished one.** For a non-sample source `--out` accepts any
  Git-ignored directory, including `atlas-scope/dist/` (Vite's build output, which the one-door design
  serves unguarded at `/scope/assets` and bundles onto the portable stick), `node_modules/` and
  `review/shots/`. `compile-io.mjs`'s header names the refused class "a location Git would track or Vite
  would bundle"; Git-ignored is a proxy for "not committed", not for "not published".
- **The digest form is not tied to the origin.** `checkLabel`/`bindingPreimages` let a
  `"repository-file"` labelled `"assesshub-store-blob"` get `sourceSha256` over the raw CRLF bytes and
  `sourceExactSha256` over the LF form (the "exact" digest the less exact one), and an
  `"assesshub-store"` record in `"lf-normalised"` form show a digest that is not the store's binding —
  without `E_SOURCE_LABEL`.
- **R3 against O15 (OWNER DECISION).** R3 says `sourceExactSha256` is `"sha256:"` + hex over the EXACT
  bytes; for a repository file it is over the LF-normalised Git blob, not the bytes read, so on a CRLF
  checkout it is not the sha256 of the file on disk and only restates `sourceSha256`. The reason is
  deliberate — keeping O15's CRLF/LF byte-identity test green, which R1 requires — but the two owner
  requirements conflict and the implementer resolved it with no recorded owner decision.
- **The `.d.mts` types are unchecked against the `.mjs`.** They state that `compileFabric`/`compileAll`
  return the app's `Fabric` type, and the header says one contract binds a compiled document and the UI;
  `compile-model.test.ts` compares export NAMES only, and the phase-3 loader will trust that assertion.
- **The compiled evidence contract is looser than the engine's**
  (`tests/test_punchlist_evidence_refs.py` `punchlist_evidence_problems`): the compiler accepts
  `evidence_refs_total == refs.length` (the engine writes a total only when capped, with total > len),
  refs with no `evidence_basis`, a ref whose host is not in the row's devices, and `record` with no
  record-kind ref or `absence` carrying record kinds — so a model can state a `record` basis no record
  ref backs.

### O56. C2's residuals — OPEN (owners: `DataGrid.tsx`, the shell, `review/capture.mjs`)
From C2's verifier (reported).
- `keepNavWhole`'s check that the row stays visible during a take-out is tested by nothing: removing it
  leaves every test green.
- `bandHoldsRow`'s docstring promises an empty-band case ("An empty band … cannot hold anything: only an
  ancestor can bring it back") that cannot be reached: `revealBelowHeader` returns earlier, because
  `offsetFromView` uses `visibleBand`'s layout-box fallback, so a row whose grid is scrolled wholly out of
  its rail is never revealed. Pre-existing (the same on the pre-fix build), and the same class of fault —
  a queue left off screen (compare O49).
- The navigation guard (`keepNavWhole`/`onScreenExtent`) and the harness detector (`readScrollEdge`)
  measure clips only, not overlays. Below 48rem the sticky status bar (`shell.css` `.app__status {
  position: sticky; bottom: 0 }`, about 85 px at 390) can cover part of a tablist or toolbar neither
  counts as cut; the implementer's "not examined" named a top app bar, but the overlay that exists is at
  the bottom.
- The brief's test (b) — the real `PriorityQueue` mounted in the rail model, with the path content
  growing until the row slides 19 px out of a 51 px band — was replaced by a pure geometric model of
  `revealBelowHeader`; the act-view restore chain (`BeforeCommit`, `DataGrid.tsx`'s act-view restore,
  `revealBelowHeader`) is pinned only end to end, by the browser capture.

### O57. C5's residuals — a tier change during a running fade still cuts the overlay, and the harness's own honesty gaps — OPEN (owners: `src/fabric3d/scene.ts` / `emphasis.ts`, `review/capture-motion.mjs`, `src/core/motion-inventory.test.ts`)
From C5's verifier (reported).
- **A cut by removal, against the owner decision.** A tier change that lands while a cross-fade is
  running removes the half-faded overlay in one frame. One trigger is a tab switch, which the decision
  covers explicitly ("no frame — including after … a tab switch … — can step more than the cap"). The
  driver caps its own value; the removal happens outside it. The `emphasis.ts` and `scene.ts` comments
  claim no frame, "including the one after a stall or a returning tab", moves it more than 0.2, which is
  false on this path.
- **The step rule is unpinned.** The harness says it judges the step on the opacity at full precision
  plus `FADE_STEP_EPS`; no test pins that, so judging the rounded figure with a looser tolerance passes
  every known answer.
- **"MOTION EXIT 0" did not reproduce.** The verifier's single final `capture-motion` run exited 4
  (UNPROVEN): 1 of 24 fades not established. The same log shows a harness honesty gap: the sequence's
  density was recorded as ok although the recording lost about 1.3 s of frames.
- **Prose that contradicts the code, and a ratchet that is not one.** Prose claims in C5's owned files
  contradict the code's own behaviour (the removal path above among them), and
  `SETTLE_FIGURE_PENDING` is called a ratchet that "may only shrink" but nothing enforces that; with §4.8
  now stating the settle figure (R114), its one entry excuses nothing and is the test owner's to remove.
**Status at phases 3 and 3.5 (2026-09-30).** Phase 3 closed the R4-VR2 follow-ups (the `extract` site
kind, the handover's judging rule at ±2E and E/2, the route test, and the reduced-motion toggle landing on
an overlay shown under full motion), and phase 3.5 made the tier-fade slot's methods uncopyable, so the
spread mutant that defeated the tripwire is killed (R123). The phase-3.5 close gate's laboratory
`review/capture-motion.mjs` run PASSED "a running tier cross-fade is handed over, never cut" (4 of 6
handover sequences judged, 2 not applicable) and every other C5 motion item (reported). No report the
record step received addresses this entry's step-rule pin, the "MOTION EXIT 0" reproduction or the
`SETTLE_FIGURE_PENDING` ratchet, so those bullets stand as written.

### O58. D3's routed fixes and residuals — OPEN (owners: `shell.css`, `EvidencePane.css`, `DevicePane.css`, `focus-return.ts` and its guard, `review/audit-d3-focus.mjs`; two OWNER calls)
From D3 and its verifier (reported).
- **Routed: the drawer paints over the Inspector at 1024–1279 px.** With the drawer open (z-overlay 30
  over z-inspector 20) the Inspector's close button was 0 of 9 hit-testable at 1024, 1152 and 1270. The
  fix is routed to `shell.css` — the Inspector docks to the drawer's left edge (design brief §2.5,
  PROPOSED); verified in an isolated copy at 9 of 9 at all three widths, and the default `--vp=1152`
  audit then 141 cases, 0 failed, 0 not visible. Until it lands the unnarrowed default audit stays red
  at 1152 (13 not-visible Inspector stops), a real layering defect the drawer-rung width D3 added
  exposed.
- **Routed: under reduced motion, controls in a freshly opened drawer are unfocusable for their first
  frame.** `EvidencePane.css`'s `.ev *` and `DevicePane.css`'s `.dp *` give every descendant a 1 ms
  transition over `all`, including inherited `visibility`. Measured at 1100 and 1152 px, `v` left focus
  on the grid cell (pre-existing, also on the pre-D3 build per the verifier). `App.tsx`'s `config.open`
  now waits up to 6 frames (R115); the CSS fix is routed.
- **Named subset, again: containers that UNMOUNT on a rung crossing drop focus to `<body>`.** The owner
  decision names `releaseFocusFrom` as the one owner for every container that can close while holding
  focus, "panels removed by a layout change or resize" included; only Rail A and Rail B were wired. The
  audit's resize cases are drawer-only, and guard shape 4 parses only `hidden`/`inert` attributes, not
  conditional unmounts — the class is "a container stops being rendered while it holds focus".
- **The guard test asserts that routing debt EXISTS.** "shape 4 found what it guards" requires
  `PENDING_ROUTING` to hold at least one hidden-without-release entry, while another case requires every
  entry to still be found; once the owners apply the routed fixes and delete their entries, as they are
  told to, it goes red.
- **"Complete" overstates it.** Requirement D3-audit carries a non-empty "remaining" while marked done:
  the `--vp=390` run exits 1 from the pre-existing `offViewPointers` zero-denominator rule, and the
  unnarrowed default run stays red at 1152 until the `shell.css` rule is applied.
- **Observation — the Inspector's fallback at the drawer rung.** When the Inspector was opened from a
  citation inside the drawer and that citation leaves the page (another finding selected), closing the
  Inspector falls back to the `#stage` landmark (never `<body>`); with the drawer open, `#stage` is then 6
  of 9 hit-testable because the drawer covers its right part. WCAG 2.4.11 minimum-compliant (not entirely
  hidden), stricter than the audit's visibility bar; the audit no longer mislabels this path "inspector
  (citation)".
- **OWNER call — no pointer control opens the drawer at 1024–1279 px** (keyboard `e` / `v` / `g e` and
  the palette only; carried from the implementer). The `--vp=390` `offViewPointers` zero-denominator rule
  makes that narrowed run exit 1; whether narrowed runs should exempt denominators that cannot exist at
  the listed widths is for the owner.
- **Harness note:** a narrowed audit run (`--vp` limited to widths ≥ 1024) always trips "SWEEP NEVER
  EXERCISED: journeys", because the More -> Path journey needs the header's More popover (below 1024 px)
  — the same shape as the 390/`offViewPointers` note.
**Status at phases 3 and 3.5 (2026-09-30).** The focus audit is UNPROVEN at the current tree and gets no
more runs by owner instruction (O68), so none of these bullets is re-measured. What the recorded logs do
show: the drawer case "open by palette → focus inside → close by palette" PASSES at 1024, 1152 and 1270 px
in `sweep-full-1` and `sweep-full-4`, and no recorded 1024–1279 px failure names the Inspector's close
button. The guard's `PENDING_ROUTING` now holds shape-6 entries found by DOM effect (O68 lists them). No
report the record step received says whether the `shell.css`, `EvidencePane.css` or `DevicePane.css`
routed fixes landed.

### O59. E2/E3 — the cold first palette open: a repair landed (pre-warm, then PARK); the verdict waits for a quiet host — OPEN (owners: `CommandPalette.tsx`, the E grader)
From E2E3 (reported; the owner goal is design brief §8.2 journey 5). The palette's own frame is drawn
once after the scene converges — in idle slices, in a transition, at opacity 0.001, `aria-hidden` and
`inert`, for at least 3 frames and 250 ms (`WARM_MIN_HOLD_MS`; measured mounted -> done was 13–63 ms,
shorter than the ~120 ms GPU compile the frame exists to trigger) — and then PARKED with
`visibility: hidden` until the first Ctrl+K, which flips attributes on the same laid-out nodes; after
that open closes, the palette renders nothing again. While parked its rows are frozen (`groupsEpoch =
open ? targetEpoch : -1`), and the coverage line, command list, grammar examples and scope line — and
`coverageFigures()`, found by a class-level probe counting every dataset read in the mounting slice —
are computed in idle slices, so neither the pre-warm nor the first open reads the dataset. The brief's
first design (unmount after raster) did not meet the goal: the verifier's trials showed the first open
still building DOM and forcing layout in the keydown. **Evidence so far, NOT acceptance evidence:** a
lab A/B at 1280x800 dark, default scale, 5 interleaved fresh browsers on a loaded host, worst
interaction — base 208/216/248/288/424 ms; the unmount repair 96/96/112/128/832; parked
80/96/120/120/552. The final tracked run, 10 trials per leg at 73 % busy: 1920 dark p95 200, 1920 light
p95 160; both 1280 legs NOT MEASURED, because the scene did not converge within 60 s at scale 1.261
(O60). **Residual on-path tasks:** the Escape inert-release restyle (close `onkeydown` 50–57 ms under
load) and the deferred page-wide `inertOutside` task after an open — neither a first-mount cost, both
waiting on the owner's decision on the brief's item 5 (`inert` -> `aria-hidden` in `inertOutside`),
which E2E3 did not implement because it changes a D3 design decision. Measured on isolated `git archive
f036ed77` trees plus the cluster's files, so the A/B compares only this change.

### O60. Scene convergence under the harness window — OPEN, stated CONDITIONALLY (owners: the E harnesses, the render owner)
From E2E3 (reported). With `measure-inp`'s forced 1.261 device scale on a 70–100 % busy host,
`converged` was often reported only after the step-down to balanced, 8–42 s after load, or not within 60
s — 17 of 20 1280x800 trials in the final run. At the default device scale the same build converged at
tier high in 4.2–5.2 s (the verifier's probe, 3 loads). Every instrument that waits for convergence
inherits this. Whether it is the host or the product at that scale is not established.

### O61. "No INP regression elsewhere" is NOT yet demonstrated, and the default E run is now much longer — OPEN (owner: the E grader)
From E2E3 (reported). The owner requires the palette repair to regress no other journey. The harness now
names every timed rep that overlapped the pre-warm's drawn window, and keeps those reps counted
(`docs/acceptance.md` E3). In one run at 80 % busy (not evidence): J1 rep 3 232 ms, J3 rep 0 56 ms and J4
rep 1 208 ms overlapped; J2, J3b and J5 did not. A quiet-host full `measure-inp` run plus the E5
cold-load and sweep audits are required. Until the first open, the parked frame adds about 320 hidden
elements to every page-wide restyle; not measured. **Harness cost:** the default `node
review/measure-inp.mjs` now also runs 80 fresh-browser palette trials — expect 40+ more minutes on a
quiet host, and more where the scene is slow to converge.

### O62. E2E3's residuals — the parked palette can open UNDER the keyboard-help dialog, and the cold case cannot measure 1280x800 — OPEN (owners: `CommandPalette.tsx` / `keyboard.ts`, `review/measure-inp.mjs`)
From E2E3's verifier (reported).
- **Focus obscured by design flow.** The palette is now parked in `document.body` long before its first
  open. If the reader opens ShortcutHelp after parking and then presses Ctrl+K, the first palette open is
  drawn UNDER the help dialog: both are `position: fixed` at z-index 60 (`--z-dialog`), whichever is later
  in the DOM paints on top, and the help dialog now is. Focus lands in the palette's search box, which the
  reader cannot see (WCAG 2.4.11), and the help dialog is inert, so it cannot be used either. On the base
  build the palette portal was appended at open time and always painted on top. `keyboard.ts:570–577`
  deliberately lets the palette's mod+k fire behind a modal, so this is a designed flow; no test covers
  opening one dialog over another.
- **The cold J5 case (`FIRST_PALETTE`) cannot measure 1280x800**, the viewport where E2/E3 failed (its
  1280 legs were NOT MEASURED in the final run, O59–O60). The cluster's report of this item was cut short
  in the record step's input; its remainder, and any open item or cluster after it, is not recorded here.

### O63. The golden's registry-clock pin awaits the owner's ratification, and the 2027-01-26 boundary still stands in the engine's other EoL/data-authority tests — OWNER DECISION and OPEN (owners: the owner; the engine's EoL/data-authority test owners; `tests/test_pipeline_golden.py` for the refresh remedy)
From T1 and its verifier (phase 2.75, reported).
- **Ratification (OWNER).** The owner asked for the now-relative `data_authorities.eol` fields to be
  normalised; T1 pinned the registry freshness clock instead (R116), disclosed the deviation, and
  its verifier reproduced that the prescribed mechanism cannot meet the goal. The deleted calendar
  test's own message had said "do not pin the clock to hide it". **For the owner:** ratify the pin — the
  measured cascade in R116 is the case for it — or name another mechanism that leaves the golden with
  no calendar boundary without normalising the cascade field by field.
- **The stated problem is not solved outside the golden.** The owner's problem was "every CI run fails
  from 2027-01-26". That is still true after T1: the existing EoL/data-authority tests keep the same
  boundary, and neither T1's report nor its record entries said so (its verifier). R116 is accurate
  for the golden only. The report the record step received does not name those tests.
- **Maintenance — a registry refresh moves the pin's window.** A new retrieval after 2026-08-07 moves
  that registry out of the pinned window; `test_golden_registry_clock_is_inside_every_published_registry_window`
  then fails with the remedy: move `_GOLDEN_COLLECTION_STAMP` inside every registry's window, then
  `UPDATE_GOLDEN=1`. That move also re-dates the lifecycle as-of date the golden's bands are judged at.

### O64. `move_groups` byte-equality is guarded by a named list of captures, not by the section's inputs — OPEN (owner: `tests/test_sample_fleet_substrate.py`)
From T2's verifier (phase 2.75, reported). The owner's acceptance criterion for the Vlan10 home is that
`move_groups` stays byte-equal, and only a one-off scratch regeneration proves it (R117). The pytest
guard the test file credits with keeping "the cable map, move groups, wave sequencing and failure
impact byte-equal" checks a hand-kept list of capture names allowed to change and a regex over L2
command names — a list standing in for the actual inputs of `move_groups`. `compute_move_groups`
takes gateway SVIs from interface data fed by the L3 capture `show running-config | section
^interface`, which is on the allowed-to-change list, so a future substrate edit can change
`move_groups` while the whole suite stays green. The class is "a substrate edit changes a section it
was supposed to leave alone"; a guard keyed to the sections themselves (regenerate and compare) would
be the fix, not a longer list.

### O65. A tracked test header still says the substrate fleet runs the inter-core session over "a transit SVI (VLAN 900)" — FIXED in phase 3 (R121; kept here for its history)
From T2's verifier (phase 2.75, reported); confirmed by the record step's `grep`: the header comment of
`src/forwarding/rib-partial-route.test.ts` still says that the substrate fleet gives core1's FULL/DR
session "its realistic L3 home, a transit SVI (VLAN 900) both cores' tables hold", and describes B1's
real-data home there in terms of that transit. VLAN 900 is retired (R117), so the claim is false. The
implementer's report routes the correction to no one. (The same `grep` also finds `Vlan900` with
10.0.199.0/30 in a synthetic interface fixture in `tests/test_excel.py`; that fixture states nothing
about the sample fleet and is not this defect.)

### O66. `build_sample.main()` ignores the engine's finalization result, so a failed engine run can silently regenerate the demo fleet — OPEN, pre-existing; must be fixed before phase 3 regenerates the fleet (owner: `webapp/sample_data/build_sample.py`)
From T2's verifier (phase 2.75, reported; pre-existing, not caused by T2's change, but in a file T2
owned). When `cp.main()` logs "[INCOMPLETE] Mandatory finalization failed ... exit 1", `main()` still
writes the snapshot to `--out` — the tracked path by default — prints "wrote ...", and exits 0. Phase
3's fleet regeneration runs through this entry point, so an incomplete engine run would replace the
tracked sample and report success.
**Status at phases 3 and 3.5 (2026-09-30): still OPEN.** Phase 3's precursor regenerated the tracked
fleet through this entry point (`74275919`), and its commit message reports `build_sample.py --check`
FRESH for the result; `main()` still ignores `cp.main()`'s finalization result (the record step read it),
so the hazard stands for the next regeneration.

### O67. The FHRP redundancy receipt's member key order depends on the hash seed — OPEN as reported; the working tree holds an undescribed change (owner: `cisco_toolkit/fhrp_redundancy.py`)
From T1 (phase 2.75, reported as an engine item outside T1's scope, routed in its needs from others).
`fhrp_redundancy` builds each member row by iterating a `set` of field names (about line 805), so the
row's key order depends on `PYTHONHASHSEED`. The snapshot is written without sorted keys, so written
snapshots are byte-nondeterministic across runs over identical evidence (dict-equal, textually
churned), and golden regenerations churn — which is why T1 did not regenerate the golden (R116). It
bears on phase 3: a regenerated fleet whose bytes depend on the hash seed cannot be reproduced
byte-for-byte. **Working-tree note (the record step):** this tree changes `cisco_toolkit/fhrp_redundancy.py`
to build member rows from an ordered tuple, and adds `tests/test_fhrp_member_key_order.py` (which the
record step ran: 2 of 2 passed); no cluster report the record step received describes either, so this
entry stays OPEN until one does and its verifier upholds it.

### O68. D3 — the focus audit `review/audit-d3-focus.mjs` is UNPROVEN at the current tree: no recorded run completed on it, every recorded run shows failures, and by owner instruction it gets no more runs — OPEN; the citation-path failure FIXED IN CODE in W5 (R130), render-mode equivalence still unproved (owners: `review/audit-d3-focus.mjs`; `src/app/focus-return.ts` / `App.tsx`; the owner for any further run)
From the recorded logs of phase 3.5 (read by the record step; the audit was NOT run by it) and Q-H's
second independent verification (HEAD `f24b9ccb`). **Owner instruction of 2026-09-29:** the focus audit
gets no more runs in any mode (`--sweep`, `--vp=390`, default, `--crossings` or any other); the logs
below are the evidence. **Per log:**
- **`sweep-full-1` — COMPLETE, EXIT=1, on an EARLIER state of the Q-H fix** (before the shared task
  pool). WALL 57.8 min (sweep 2.0, drawer 6.6, rung crossing 49.2). Rung crossing: 8,215 cases over 8
  directed crossings, 2,925 openers found and 2,925 activated, 1,036 surface case-sets, 224 programmatic
  landings, 2 of 2 modal-dialog owners opened; **4 landed on `<body>` or out of sight.** Sweep: 2,821 tab
  stops walked and 3,190 nine-point hit tests with 0 failures of their own; its summary line counts the 4
  crossing failures. All 4 are one failure in four page states (a finding selected, a device selected,
  idle, a traced flow): after 768 → 390 px, focus is on the Inspector's "Copy the citation path" button
  with no part of it on screen, clipped by `div.app`.
- **`sweep-full-2` — EXIT=127, died early**, 33 FAIL lines, mostly "Filter findings" combobox openers
  NOT DRIVEN.
- **`sweep-full-3` — EXIT=124, timed out**, 197 FAIL lines: 182 are harness breakdown after the browser
  closed (71 "a task threw" and 111 NOT DRIVEN at 768 → 1152 / a device selected); 14 are real (the
  citation-path failure in each of the 4 states, 10 more 768 → 390 / a device selected lines the verifier
  did not open) and 1 is a painted-over fabric pointer at 1920 → 1440 / a traced flow.
- **`sweep-full-4` — the last permitted run, on the current tree — EXIT=127, incomplete:** 6,402 PASS and
  5 FAIL lines and no TIME, WALL or RUNG CROSSING verdict line. 3 FAIL lines are the citation-path
  failure; 2 are sweep hit tests in which the fabric canvas is painted over by `fabric3d__quality` /
  `fabric3d__hud` (768×1024 and 1000×800, a device selected), which `sweep-full-1` did not have.
- **The later `--sweep --vp=390` run was STOPPED** under the owner instruction, with no verdict line and
  4 FAIL lines, all the citation-path failure.
- **The drawer case "open by palette → focus inside → close by palette" (R5-V2-2)** is recorded PASS at
  1024, 1152 and 1270 px in `sweep-full-1` and `sweep-full-4`.
**The second verifier's defects (QH-V2), as they stand:**
- **QH-V2-1 (blocker) — the owner's hard tractability requirement (TRACT: full `--sweep`, `--vp=390`
  and default each within 60 min with the final code) is NOT MET by any recorded run.** The only
  complete full sweep is `sweep-full-1`, on the earlier structure; the shared-pool design's own comment
  cites only its 57.8 min. No recorded log shows a completed default run.
- **QH-V2-2 (major) — the "Copy the citation path" failure is unfixed and was unrouted.** It fails in
  every run above and contradicts the Q-H report's "`--sweep --vp=390` … 0 failures". The control is
  `src/panels/Inspector.tsx` (the verifier's `grep` finds it only there). The phase-3.5 close gate did not
  change `Inspector.tsx`.
- **QH-V2-3 (major) — render-mode equivalence is not proved for the current harness,** and was never proved
  for the sweep's Tab walk and hit tests, which also run with draws suspended. The one passing
  `--render-check` (546 compared, 0 differ) predates the round-1 harness changes (discovery by effect, the
  shorter crossing height, the shared pool), sampled three crossings in two states, and compared only
  rung-crossing focus outcomes; `sweep-full-4`'s two new painted-over hit tests are exactly the kind of
  result a full-render run would have to confirm.
- **QH-V2-4 (major) — the navigation guard ignored `pointer-events: none` covers (R9 m3), so `node
  review/capture.mjs selftest` was 48 of 49 at `f24b9ccb`.** Fixed only in the uncommitted gate tree
  (R129); not independently verified, and not exercised by the focus audit.
- **QH-V2-5 (minor) — no recorded sweep log ran the committed harness bytes:** `audit-d3-focus.mjs` was
  written 16 s after `sweep-full-4.log`'s last write, and its content before that write was not kept.
- **QH-V2-6 (minor) — `npx vitest run src/app` was red at `f24b9ccb`** (2 failed: `Header.focus-return`,
  `verdict-scope.b2`). Fixed in the uncommitted gate tree (R129).
**Also carried from Q-H's first verification and its routing:** the `PENDING_ROUTING` debt in
`src/app/focus-return.guard.test.ts` — the Fabric3D canvas removals (Q-D), the tier-fade overlay removal in
`scene.ts` and six `FabricLabels.tsx` data-attribute writes (Q-C), the boot line's two writes in
`main.tsx` and `core/dataset/refusal.ts` (Q-M), and two in `src/dev/preview.tsx` (unowned) — each to be
released through the third door and its entry deleted. **Status: D3 is UNPROVEN at the current tree** —
no complete run exists and the partial runs show known failures. It is not PASS by inference from the
PASS lines, and it does not move until the owner authorises a run of the committed harness on the
committed tree.
**Status at W5 (2026-09-30), the preview-scope repairs after phase 3.5 — narrowed, still UNPROVEN.**
From R-D3's two rounds and its verifier (reported; the record step did not run the audit).
- **Closed in code:** QH-V2-2, the "Copy the citation path" failure, with the within-rung resize case and
  the skip-link settle race it led to (R130); the doors' rule-4 drift, the guard's per-file release and
  V1-2 (R131). The `PENDING_ROUTING` debt is down from 12 entries to 2: R-D3 released 9 and routed
  `scene.ts`'s tier-fade overlay unmount, which the working tree's guard file now records as released by
  the W5 engine gate together with a `scene.test.ts` change (read from the tree; the gate summary does not
  mention it). The two left are `main.tsx` and `core/dataset/refusal.ts`: the boot line lives in the
  entry chunk, which imports no React, so the door needs a React-free module or an owner decision.
- **QH-V2-3 (render-mode equivalence) — OPEN, contested.** R-D3 fixed three harness defects behind the
  earlier 47 differences (record keys that depended on which opener's batch finished first, a scene
  control named from the frame rate, and a settle timed on the harness's clock instead of the page's),
  made `--render-check` honour `--state=`, and ran it bounded once per state with
  `ATLAS_URL=http://localhost:4191 timeout 2700 node review/audit-d3-focus.mjs --render-check
  --state=<s>`: idle EXIT=0 in 19.1 min (421 compared, 0 differ, 2 excused, 2 pairs named differently by
  the mode with the same outcome); "a finding selected" EXIT=0 in 23.9 min (543 compared, 0 differ). Both
  ran on the build made before the final chip change. The verifier's rerun on the FINAL build did not
  reproduce that result for "a finding selected" (V2-1, major), so the cluster's "CLOSED" is not recorded
  here. The sweep's Tab walk and hit tests are still unproved under suspended draws.
- **Still open from the verifier:** V2-2 (the crossing path's `releaseFocusLeftUnseen` call in `App.tsx`
  is unpinned, masked by `keepFocusSeen`), V2-3 (`returnFocus` does not walk outward, O77), V2-4
  (`sightOf`'s containing-block rule for absolutely positioned elements is unpinned) and V2-5 (the bounded
  crossing run for "a device selected" could not be reproduced to completion; the harness failed without
  saying why).
- **Unchanged:** QH-V2-1 (TRACT) — no complete `--sweep`, `--vp=390` or default run exists on any tree, so
  **D3 stays UNPROVEN** and no criterion moves. The bounded runs above were made in W5 after the owner
  instruction of 2026-09-29; whether the owner authorised them is not stated in the reports the record
  step received, and the owner should say whether they stand as evidence.
**Status at W5b (2026-10-01), the follow-up of the W5 repair wave — narrowed again, still UNPROVEN.** From
S-D3 and its verifier (upheld, five minors; reported; the record step did not run the audit).
- **Closed in the harness and code (R139):** V2-1 for "a finding selected" (a harness race on a one-frame
  pointer; activations are now read from a page still across two frames); V2-2, V2-3 and V2-4, confirmed by
  the verifier's mutations; V2-5's silent failure, now that the watchdog's clock is every completed
  Playwright call and a stall report names its step; SD3V-1 (keys numbered and resolved over one list) and
  SD3V-6 (the containing-block census over every accepted name and alias).
- **QH-V2-3 (render-mode equivalence) — narrowed, still OPEN.** Bounded `--render-check` runs on the
  current shared tree: "a finding selected" EXIT=0, 549 compared, 0 differ (41.3 min); idle EXIT=0, 425
  compared, 0 differ (30.3 min). No W5b report states a render check for "a device selected" or "a traced
  flow", and the sweep's Tab walk and hit tests are still unproved under suspended draws.
- **New minors (SD3R2-1 to SD3R2-5, R139):** the blanket `-webkit-` stripping in `containsFixedBoxes`; the
  SD3V-5 guard is a `will-change` proxy for the class; the V2-1 normalisation is pinned by nothing and its
  INFO line does not name the render mode; the one-frame attribution is not supported by the preserved
  evidence; and the watchdog's stop path is unbounded and leaves the stopped job running.
- **The two `PENDING_ROUTING` entries** (`main.tsx`, `core/dataset/refusal.ts`): no W5b report names them;
  they stay as stated above.
- **Unchanged:** QH-V2-1 (TRACT) — no complete `--sweep`, `--vp=390` or default run exists on any tree, so
  **D3 stays UNPROVEN** and no criterion moves. The two render checks were made after the owner instruction
  of 2026-09-29, like W5's; the owner's answer on whether such bounded runs stand as evidence is still
  pending.

### O69. The /scope reader — the XML path still reads an XHTML page differently from the browser, and four more residuals — OPEN (owners: `webapp/backend/app.py`, `webapp/tests/test_scope_mount.py`, `tests/test_ssot_registry.py`, `.github/`, `portable/`)
From Q-F's second independent verifier (reported; not re-verified by the record step).
- **QF-V2-1 (major) — the parser-differential class is still open on the XML path.** AssessHub reads an
  XHTML page with expat. With an external DOCTYPE (for example the XHTML 1.0 public identifier) expat
  silently DROPS every undefined entity reference inside an attribute value and calls no handler, while
  Blink expands the full HTML named-entity table for XHTML documents: `rel="noopener&Tab;noreferrer"`
  reads as `noopenernoreferrer` in the reader and as `noopener noreferrer` in Chromium, and
  `_scope_file_index` serves that build `ready` although a `noreferrer` rel token is in the refused class.
  The verifier's probe ran the worktree's own `backend.app`, `write_scope_dist` and the test's `_oracle_run`
  harness in real Chromium. It contradicts the owner requirement never to judge a /scope document with a
  tokenizer different from the browser's, `app.py`'s header claim that XML is restricted to what every
  conforming processor reads identically, and `atlas-scope/README.md`'s "only the way a browser reads
  it". The XML side of the generated family is a hand-kept list of 10 declarations and 3 controls, with no
  DTD or entity members, which is why neither the oracle test nor the containment test catches it.
- **QF-V2-2 (minor) — the whole-tree SSOT citation checker skips every citation rooted at a top-level
  FILE** (`COLLECT_PARSE_V3_23_0.py :: …`, `pyproject.toml :: …`, `AGENTS.md`, `RELEASING.md`,
  `CHANGELOG.md`, `CLAUDE.md`, `ollama_recall.py`), and for non-Python sources a line that starts with
  `name(` — a call — counts as a definition.
- **QF-V2-3 (minor, pre-existing) — "every URL the shell loads is a startup-indexed /scope asset" is
  enforced over a hand-kept attribute list** (`src`, `href`, `srcset`, `poster`, `data`, `action`,
  `formaction`): a shell loading a third-party URL through `table background`, SVG `xlink:href` or a
  `style` attribute's `url(...)` is served `ready`.
- **QF-V2-4 (minor) — the CI-leg reader stops at the first newline**, so a `python -m pytest \` with its
  paths on the next line would not be recognised as running the /scope pins; no workflow uses that
  spelling today.
- **Carried and routed, unchanged:** the atomic pair — `"atlas-scope/**"` after `"webapp/**"` in BOTH
  `.github/scripts/classify_webapp_ci_scope.py` `RELEVANT_PATH_FILTERS` and `webapp-ci.yml`'s push paths,
  in one commit (optional now that `atlas-scope-ci` runs the /scope pins itself with the oracle required);
  `portable/build_atlas.py`'s refusal message and a frozen smoke that requires `GET /scope/` 200 with the
  runtime-source meta and `[ ok ] atlas-scope-dist`; `portable/release_contract.py`'s bundled-frontend SBOM
  and notices for atlas-scope's production graph. **No CI leg added or changed in phases 3 and 3.5 has run
  on GitHub-hosted runners** (first run = findings), and whether webapp-ci's backend leg is a required check
  is a branch-protection decision. Stated residual of the referrer rule: a hostile script setting a policy
  at run time; the primary control remains that the viewer has no write code.
**Status at W5 (2026-09-30), the preview-scope repairs after phase 3.5 — the four QF-V2 items and the
three routed portable items FIXED IN CODE; one major and the final check's red stay OPEN.** From R-QF
(closed PARTIAL), R-PB (upheld) and their verifiers (reported).
- **Closed:** QF-V2-1 (XML is refused outright), QF-V2-2 (top-level files are citation roots), QF-V2-3
  (a closed construct accept-list for the shell) and QF-V2-4 (shell-exact continuation joins), with
  round 2's shallow-history skip, CSS accept-list, icon-in-head rule and non-shell HTML refusal (R132).
  The three routed portable items — the build refusal naming its commands, the frozen smoke's
  `GET /scope/` proof with `[ ok ] atlas-scope-dist`, and the SBOM and notices for atlas-scope's
  production graph — are fixed (R133). R-QF reports the `atlas-scope/**` pair unchanged and pinned by
  `tests/test_webapp_ci_scope.py`.
- **RQF-V2-1 (major) — OPEN.** A shell whose only icon link sits inside `<title>` is served ready, and
  Chromium then requests the origin's `/favicon.ico`, outside /scope. This refutes the cluster's "by
  construction" claim that a build served ready requests nothing outside /scope, and its statement that
  the icon-in-head rule only refuses more than the browser needs; the 340-case request oracle has no such
  member.
- **RQF-V1-2 / RQF-V2-2 — FIXED IN THE WORKING TREE after the cluster reports.** R-QF's final check was
  PYTEST_EXIT=1 on one test outside its files,
  `tests/test_ssot_registry.py::test_no_registry_citation_pins_a_line_number`, because `docs/ssot.md:152`
  cited `COLLECT_PARSE_V3_23_0.py:2485/2624/2629` (one pre-existing skip, `test_security_hardening.py:1059`,
  WinError 1314). The working tree now cites `COLLECT_PARSE_V3_23_0.py :: main` there (read from the diff
  by the record step; no cluster report names the edit), and the record step's own run of
  `tests/test_ssot_registry.py` exited 0 on this full-history checkout.
- **Routed items, applied in the working tree after the cluster reports (read from the diff; no report
  names them):** both `actions/checkout` steps in `.github/workflows/ci.yml` now set `fetch-depth: 0`, so
  the renamed-owner half of the history check can run there (no hosted run yet); `portable/README.md`'s
  build-refusal and smoke prose now names the Atlas Scope hub build, `/scope/` and the atlas-scope
  inventory.
- **R-PB's open minors and residuals:** PB-V1-H (the build refusal's missing-tracked-assets branch is
  unpinned), PB-V1-E (no test pins that a scope notice's `npm_project` is `atlas-scope`), PB-V1-J (the
  `BUILD_OUTPUTS`-to-inventory guard is tested only standalone, not through `toolchain_receipt`), PB-V1-Q
  (`loopback_http_scope_runtime_shell` is missing from `release_contract`'s `no_evidence` set, so a row
  for it with arbitrary evidence is accepted — the hand-kept-list shape again) and PB-V1-B (the
  Content-Type check in `scope_shell_gap` is unpinned). PyInstaller was not run, so nothing ran against a
  frozen `Atlas.exe`. `tests/test_make_stick.py::test_release_package_longest_member_verifies_at_deep_updater_path`
  timed out (`make_stick.ps1` over 120 s) under host contention and was not re-run on an idle host.
- **Also open:** `tests/test_transition_schema_assets.py::test_byte_bound_checkout_owners_are_lf_exactly_attributed`
  is red in the engine gate until R-QF's `webapp/backend/app.py` edit is committed (the W5 banner).
- **Unchanged:** no report states a run of these legs on GitHub-hosted runners.
**Status at W5b (2026-10-01), the follow-up of the W5 repair wave — RQF-V2-1 and the R-PB minors FIXED IN
CODE; the hub build is still not produced by its own command.** From S-QF (closed PARTIAL), S-PB (upheld),
S-CI (upheld) and their verifiers (reported).
- **Closed:** RQF-V2-1, the icon link inside `<title>` (R136); W5's R-PB minors PB-V1-H, -E, -J, -Q and -B,
  each with a test (carried from W5b's earlier pass, R140); V-SPB-1 to V-SPB-3 — one schema id per shape for
  every versioned release document, a refusal test for every W5-X5 guard, and the relative-root recorder
  crash (R140); W5-X4 — every workflow leg that collects a history-needing test now fetches the full
  history, including `main-selfhosted.yml` `suite` and `portable-release.yml` `gate` (R135).
- **VQF-1 / VQF-R2-1 (BUILD-HUB-ONCE) — OPEN.** The tracked `dist-hub` the oracle tested was not produced
  by `npm run build:hub`, and when S-QF ran, that command's `tsc` step exited 2 on S-VOCAB's absent-kind
  types. A scratch hub build of the current source matched it in every CSS file and differed in the shell
  only by the module-entry hash. The absent-kind patch is now in the working tree (W5b banner), but no
  report states a `build:hub` run since.
- **VQF-2 — applied in the working tree after the reports (read from the diff; not verified):**
  `scope_shell_gap` in `portable/build_atlas.py` now names the reader's own refusal reason.
- **Still open:** VQF-R2-2 (two inaccuracies in `atlas-scope/README.md`'s reading claim); V2-SPB-1 (the
  `qualification/2` fingerprint leaves out `REQUIRED_EXTERNAL_GATES`), V2-SPB-2 (the superseded `/1`
  reasons are false for the W5-era `/1` documents) and V2-SPB-3 (the verifier-side attribution-member check
  is never reached on its own); S-CI-V1 (the history-needing tests are found by the word "shallow" in a
  `pytest.skip` reason, not structurally). S-CI-V2 (two copies of the pytest-invocation reader) has one
  shared reader in the working tree, `tests/pytest_invocation_reader.py`, read from the tree and not yet
  verified; it is uncommitted with the wave's other new files (the W5b banner).
- **Not covered by any W5b report:** `test_transition_schema_assets`'s red until R-QF's `app.py` edit is
  committed; the `test_make_stick` deep-path timeout. The engine gate did not return, so neither has a
  W5b result.
- **Unchanged:** PyInstaller was not run and nothing ran against a frozen `Atlas.exe`; no leg has run on
  GitHub-hosted runners.

### O70. C1 — the KEY validator still lets a loss vanish in three ways, and the protocol's other residuals — OPEN (owner: `review/blind-pair.mjs`, `review/capture-refs-clean.mjs`, `review/capture.mjs`); the critic panel was NOT run (owner instruction)
From Q-G's second independent verifier (reported; its probes imported the worktree's `evaluate()`). RULE v4
and `review/REFERENCES.md` both say "A LOSS IS NEVER IGNORED"; these three contradict it.
- **R2-1 (major) — a loss stored under any key other than the exact dimension id vanishes.** `pickOf` reads
  only `perDimension[P.dimension]`: a "B" under `color-discipline` (US spelling), `Colour-Discipline`, or a
  bare string `perDimension: "B"` reads as no answer, not a loss, and the pairing passes on two other
  critics. Each sheet asks exactly one question, so any pick on the line answers it.
- **R2-2 (major) — any `sheetSha` that is not exactly one current sheet's full sha is classed "stale" and
  ignored, loss included.** A loss written with the sheet NAME (the only identifier `sheets.json` gives a
  critic), a 16-hex prefix, an uppercased sha or a trailing space disappears, and the same critic's later
  re-ask on the correct sha then counts as its FIRST verdict — the re-ask converting a loss into a win that
  the owner forbade. Stale lines also do not block C1's overall result, while unparseable ones do.
- **R2-3 (major) — recognition is read only from the boolean `recognized`.** A line with `recognized:
  false` and `recognizedAs: "Grafana Explore in B"`, or whose reasons say "B is Grafana Explore", is counted
  as an unrecognising win. The KEY already holds the identity list (`identityMasked`), which the validator
  does not use.
- **R2-4 (minor)** — `derivedFrame()`'s refusal of a derived frame whose bytes or base capture changed is
  pinned by no test and has never run on real data. **R2-5 (minor)** — the reference side's task state is
  "proven" by chrome labels (Grafana's "query inspector"/"query history", Forward's "physical topology")
  that hold whatever the screen shows. **R2-6 (minor)** — the Forward AI nav glyph survives beside its mask
  on the composition sheet. **R2-7 (minor)** — a first line with `recognized: true` and an empty
  `recognizedAs` is shape-invalid yet still excludes its critic wholesale and erases that critic's loss.
- **Carried:** our panel is a crop on 3 of 4 emitted pairings (D5; needs a viewport option in
  `review/capture.mjs`, disclosed in RULE and the critic instructions); the real Grafana promo banner has
  never been served to the control session, so real-banner detection rests on the synthetic control (D7);
  `capture.mjs refs` still matches only the exact `[aria-label="Close"]`; the network-visualisation sheet
  is BLOCKED because `08-path-indeterminate` (179 draw calls, the heaviest state) rendered at tier
  "balanced" in 4 of 4 frames on a 100 %-busy host — a rendering-cost finding for the fabric owners only if
  it reproduces on an idle host.
- **Third-party imagery policy:** the Forward/Storylane, IP Fabric and Grafana frames live only under the
  Git-ignored `review/shots/` and `review/blind/`, and must never enter the master-reference site, a golden
  artefact or any published bundle.
**C1 stays UNPROVEN:** the owner instruction of 2026-09-29 defers the critic panel, and a panel run
against a validator with these three holes would not be C1 evidence.
**Status at W5 (2026-09-30), the preview-scope repairs after phase 3.5 — the three holes and four of the
minors FIXED IN THE HARNESS under RULE v6; one major stays OPEN; C1 stays UNPROVEN.** From R-QG's fix
round and its verifier (reported).
- **Closed (R134):** R2-2, R2-3 (no recognition erases a loss, on any line), R2-4, R2-6 and R2-7, and the
  verifier's QG-V1 to QG-V5. R2-5's claim is withdrawn and corrected: the reference task state rests on
  each target's declared `taskState`, and the contrast screen reports itself UNCALIBRATED for all 5 paired
  references. The carried `capture.mjs refs` exact `[aria-label="Close"]` item is replaced by a role and
  name match plus a second pass that restores a superset (synthetic control page only).
- **QG3-1 (major) — R2-1 is not closed by class.** A pick token held in a WELL-TYPED string field is never
  read, except in `reasons` and `faults`: `recognizedAs: "B"` under `recognized: false` — a shape the
  validator itself flags as uninterpretable — on a line with no filed answer is read as "no answer", and
  the loss vanishes. The pick-token rule is scoped to a hand-kept list (`{reasons, faults}`) standing in
  for the class, and that list normalises less than `pickOf` ("B." is a possible loss in `perDimension`
  but is not read as a reason).
- **Minors still open:** QG3-2 — four RULE v6 behaviours pinned by no row (tying an unbound line to the
  pairing its frames name; the unknown-side rule; the 8+-hex unique-prefix resolver branch; the
  `recognized: true` + empty `recognizedAs` shape rule), each failing safe at C1-overall level; QG3-3 —
  code comments still say the contrast screen PROVES task-state text is content, not chrome; QG3-4 —
  `capture.mjs refs` narrows the old consent matching (anchored `^(accept|allow)( all)?\b` and
  `^got it\b` no longer dismiss "I accept" or "OK, got it", which the old substring match clicked) and
  now clicks every visible matching control, not the first.
- **Owner decision:** confirm that requirement 3 (no recognition erases a loss) supersedes D2's
  first-line reading; two validator rows were changed from PASS to UNPROVEN on that reading.
- **The network-visualisation sheet** is still BLOCKED (`08-path-indeterminate` at tier "balanced", not
  recaptured; the quiet-host `--capture-ours` step is pending). The app gate found `capture.mjs app`'s
  frame-rate flag intermittent on that state at 1440 (light in one wave run, dark in another: 2 of 3 wave
  runs, 0 of 2 base runs; the last wave run 32 of 32), and it recurred with the host at 19 % load, so the
  carried "only if it reproduces on an idle host" condition is partly met; the fabric owners should
  measure it on a truly idle host with `measure-fps.mjs`.
- **Unchanged:** D5 and D7 as carried; the third-party imagery policy. No critic panel ran, so **C1 stays
  UNPROVEN** and no criterion moves.
**Status at W5b (2026-10-01), the follow-up of the W5 repair wave — RULE v8 and structural overlay
dismissal FIXED IN THE HARNESS; QG3-1 and QG3-4 stay OPEN, with one new regression; C1 stays
UNPROVEN.** From S-QG's round 2 and its verifier (defects, one major; reported).
- **Closed:** QG3-3, the "proves" wording and the misleading self-check prefix (R137); SQG-V3 to SQG-V7 —
  prose read when nothing is filed, picks carried as object keys, `recognizedAs` read for recognition only
  under `recognized: true` (a panel-only `recognizedAs` is now INVALID), and the free-string reader's class
  claims pinned (R137); SQG-V1 and SQG-V2 — dismissal decided by structure, restoring shadow, absolute,
  in-flow, image-alt and title-only consent and close controls and leaving fixed app chrome alone (R138).
  RULE v8, ruleSha `6066a0400b1a`; the KEY was regenerated, and the 8 sheets for 4 of 5 pairings are
  byte-identical to before.
- **QG3-1 (major) — still not closed by class (SQG-R2-1).** A field keyed by an `Object.prototype` name is
  never read, through the prototype-chain `FIELD_TYPE_OK` lookup in `pickValues`: under `constructor` or
  `toString` a pick vanishes and the pairing passes, and under `__proto__`, `hasOwnProperty`, `valueOf` or
  `isPrototypeOf` `evaluate()` throws a `TypeError`, so `--validate` crashes on real input. True at
  `22373163` too.
- **QG3-4 — still not met (SQG-R2-3).** The structural rule still narrows the old consent matching (a box
  over a CSS-background hero is not layered; the consent box stops at 1,500 characters and ignores the
  control's own name; in-flow announcement bars with `aria-label="Close"` are no longer dismissed), and the
  doc's "the one deliberate narrowing" is inaccurate.
- **New, introduced by this round — SQG-R2-2 (minor regression of W5-X6).** Any `[title]` or `[aria-label]`
  element whose text contains "allow", "accept" or "got it" can be clicked as a dismiss control inside a
  layered box or a dialog — an ACL or policy row in a referenced network product among them — against the
  docs' claim that product controls are never clicked.
- **Other new minors:** SQG-R2-4 (the punctuation-boundary half of the whole-word class has no row) and
  SQG-R2-5 (the SQG-V6 exemption also hides sheet-question prose written in `recognizedAs`).
- **Not named by any W5b report:** QG3-2 (four RULE v6 behaviours pinned by no row) stays as stated.
- **Owner decisions:** the pending D2 question (requirement 3 over D2's first-line reading) is unchanged;
  the owner may also want to confirm the SQG-V6 reading, which reversed an earlier W5b row from a loss to an
  invalid or no-answer line.
- **Unchanged:** the network-visualisation sheet is BLOCKED (`08-path-indeterminate` at tier "balanced",
  not recaptured); `node review/blind-pair.mjs` exits 2. No critic panel ran, so **C1 stays UNPROVEN**.

### O71. The engine gate's `pytest` is red on one real test and eight expected linked-worktree reds — OPEN (owners: the owner, for a test-only module boundary; `webapp/tests/test_scope_mount.py`; `atlas-scope/src/forwarding/`)
From the phase-3.5 engine gate (reported), confirmed by Q-F's verifier and the gate's targeted and full
runs (the record step read the logs' summary lines).
- **`webapp/tests/test_scope_mount.py::test_no_module_a_runtime_build_can_bundle_reads_as_snapshot_evidence`
  — red since `1061fdea`, on `atlas-scope/src/forwarding/golden-expectations.ts`.** That module holds the
  golden tier's literal sample citations (for example `acls.core1.PROTECT_SERVERS[3]`), is imported only by
  test files, but is not NAMED as a test file, so the scan treats it as bundleable and
  `_scope_file_carries_compiled_model` matches its citation signature. Q-F routed a rename (a name carrying
  `.test.`) to Q-M; Q-M did not apply it; the engine gate classes it as needing an **owner decision on a
  test-only module boundary**. The scan's exclusion must not be widened to make it green. It keeps Q-F's
  final check and `atlas-scope-ci`'s pytest step red.
- **Eight expected reds of the linked-worktree layout**, each confirmed by its message:
  `tests/test_atlas_r2_authority_decision_binding.py::test_successor_package_binds_and_exercises_this_exact_binder_source`
  (STANDALONE_GIT_DIRECTORY_REQUIRED); `tests/test_graph_invariants.py` ×3
  (`graph_report_summary_partition_mismatch` among them); `tests/test_graphify_guarded.py` ×4 (`guard.main`
  returns 2). They are red because this is a linked worktree, not because of phases 3 and 3.5; a clean
  checkout of the committed tree must still show them green before anything merges.
**Status at W5b (2026-10-01), the follow-up of the W5 repair wave — one of the eight expected reds removed;
the real red and the other seven unchanged by any report.** From S-CI and its verifier (upheld; reported).
- **Fixed in the test (R135, W5-X1):** `test_successor_package_binds_and_exercises_this_exact_binder_source`
  was a wrong environment assumption, not a layout red: it now fetches the checkout's HEAD with full
  ancestry into a fresh LF-exact repository and passes in a linked worktree, a full clone and an
  `autocrlf=true` detached-HEAD clone (skipping visibly on a shallow checkout).
- **Still open:** the seven remaining expected reds (`tests/test_graph_invariants.py` ×3,
  `tests/test_graphify_guarded.py` ×4) and `test_no_module_a_runtime_build_can_bundle_reads_as_snapshot_evidence`
  on `golden-expectations.ts`, which no W5b report names. The W5b engine gate did not return, so none of
  them has a W5b result.

### O72. Q-A1's residuals — A1's header design fails at 1280×720, its App-path case is slow, and the geometry proof is a scratch harness — OPEN (owners: `src/panels/EvidencePane.tsx`, `src/app/App.tsx`, a `review/` owner)
From Q-A1's verifier (upheld with three minors) and Q-A1's own record (reported).
- **QA1-R1-1 — A1 is not met at 1280×720**, inside the design brief's 1280–1599 "reference layout" rung
  and the viewport §7.6 uses for its focus-not-obscured check: the header, up to 512 px tall, leaves 45 px
  of pane body, and for 203 of 583 record activations the record's content sits below the fold, so the
  reader must scroll — which A1 counts as a failure. The implementer measured only 1440×900 (225 px of body
  left). Runs of three or more same-kind records sharing a name ending are said once (F142's 20 witnesses),
  but the engine caps a row at 64 refs, so a large fleet could make the header taller than the rail; a
  tighter design (grouping by host) is open and unmeasured on a synthetic large fleet.
- **QA1-R1-2 — the repaired App-path case for F141** clicks 27 header controls and 27 pointer controls,
  about 10 s alone against the 30 s hang detector; under heavy contention it timed out (75.7 s and 111.1 s),
  so the suite can go red on load, not logic.
- **QA1-R1-3 — the tracked test proves counting and structure, not geometry** (jsdom lays nothing out); the
  no-scroll proof at a declared viewport lives only in the implementer's scratch harness. Adopting it
  under `review/` is routed as optional.
- **Leads, not failures:** the `v` command (`App.tsx` `config.open`) still activates the first
  `.ev-cfgactions button`, which for the 91 findings with no openable engine record is a step-5 context
  record, not the engine's evidence (routed to the App.tsx owner); one console error "flushSync was called
  from inside a lifecycle method" in the 146-finding palette run at 1440×900, not attributed; P3F's
  verifier reported an `evidenceRecords` pointer `/config_hygiene/core1/undefined/0` — an "undefined" key in
  a cite — which no report the record step received confirms or refutes.

### O73. Q-C's residuals — the list-phrase guard does not follow a variable, the golden-precondition guard's "stated" is loose, and ratcheted sites in other owners' files — OPEN (owners as named)
From Q-C's round-2 verifier (upheld with two minors) and Q-C's records (reported).
- **QC-R2-V1** — the AST list-phrase scan checks only a join's immediate parent, so `const counts =
  ….join(", "); … ${counts || "none — no flow was traced"}` (`src/panels/PathTrace.tsx:809`) is neither
  flagged nor ratcheted.
- **QC-R2-V2** — in `golden-preconditions.test.ts`, "stated" means read inside some `expect()` in a golden
  block (`expect(typeof P).toBe("boolean")` would count), and a file with no golden tier is not checked;
  latent today.
- **Ratcheted as PENDING, each for its owner** (live counts in `src/core/claims.empty-coverage.test.ts`):
  `app/CoverageBar.tsx` 1, `app/StatusBar.tsx` 2, `forwarding/ip.ts` 1, `panels/ClaimCard.tsx` 1,
  `panels/DevicePane.tsx` 1, `panels/EvidencePane.tsx` 1, `panels/PathTrace.tsx` 1,
  `panels/PriorityQueue.tsx` 1; role classification outside `roles.ts` in `fabric3d/layout.ts` and
  `Fabric3D.tsx` (PENDING in `src/fabric3d/role-glyph.test.tsx`).
- **The stage still says "starting the renderer" while a large layout is pending** (P3D-V2-3's wording
  half; `src/app/surfaces.tsx` `StageWarmup`, which should read `data-layout="pending"`), and the warm-up
  sentence's "up to about a second" should say a large fleet can take longer.
- **Two implementations held equal, not one:** `layout.ts` still carries its own step-2 reconciliation
  beside `tier-groups.ts`; the 300-fleet test holds them equal.
- **Not re-measured on the regenerated sample:** the cold-load warm-up figure (the prose names the sample it
  was measured on, `9cc348bd…`).

### O74. Q-D's residuals — no quiet-host budget receipt, the reader's wait is not the gated figure, O(devices) label work, load-time long tasks, and a work budget that fails on small fleets — OPEN (owners: the owner for receipts and budgets; `src/fabric3d/FabricLabels.tsx`, `interaction.ts`, `scene.ts` / `postfx.ts`; `src/fabric3d/layout.test.ts`)
From Q-D's round-2 verifier (upheld with two minors), Q-D's records and the phase-3.5 app gate (reported).
- **The owner's wall-clock layout budgets (≤ 300 ms at 300 devices, ≤ 2 s at 1,000) have no acceptance
  receipt:** every `review/measure-scale.mjs` run so far was on a busy or battery host
  (`acceptanceEvidence: false`), although the last two PASSED (R124). Close with a quiet-host, on-AC run
  that exits 0 with `acceptanceEvidence: true`.
- **QD-V2-m2 — the gate judges median `computeMs`, the summed slice time;** the reader's wait,
  `elapsedMs`, was a 395.6 ms median at 300 on the loaded host (262.8 ms in the gate's 32 %-busy run), and
  unattributed long tasks of 193 ms and 255 ms overlapped the layout window. A claim that a 300-device
  fabric appears within 300 ms would not be supported by these receipts.
- **QD-V2-m1 — `review/measure-scale.mjs` was untracked when verified**; it is tracked at this tree.
- **O(devices) work in the orbit path:** `FabricLabels.tsx`'s per-frame tick and its full re-render on
  every hover change outside a drag; `interaction.ts`'s `flushHover` hit-tests every frame of a drag whose
  result is discarded; scene and post-chain creation cause 200–800 ms load-time long tasks at 300 devices.
- **Beyond about 1,500 campus nodes one ordering pass is longer than a slice** (reported arithmetic).
- **`src/fabric3d/layout.test.ts`'s counted work budget formula (12·E·N plus sweep and hint terms) is
  exceeded on the engine's 7-device golden** (4,084 > 3,624 ops; 1,872 > 504 with no sweeps), so "stated in
  its own size" does not hold for small fleets. The gate moved the assertion to the golden tier instead of
  widening it; the formula needs an owner-derived constant or linear term.
- Why an opened-file fleet's canvas is smaller than the sample's was not examined.

### O75. Q-M's residuals and the runtime dataset's stated limits — OPEN (owners: `src/forwarding/absence-skip.guard.test.ts`, `review/rename-snapshot.mjs`, `src/panels/decided-surfaces.counterfactual.test.tsx`, `src/app/Header.tsx` / `StatusBar.tsx`, the dataset door)
From Q-M's verifier (upheld with four minors) and P3E's records (reported).
- **QM-V1-m1** — the absence-skip class guard flags only an `===`/`==` comparison with `undefined`/`null`;
  `if (!s) { …; return; }` gets past it, and `it.each(...)(...)` bodies are not governed.
- **QM-V1-m2** — `planOutputs` compares a derived path built from the source's file STEM, so a foreign
  `sample_fleet.snapshot.json` in another directory still overwrites the rename leg's renamed file and
  `.local-data/rename-compiled`; two same-stem sources collide.
- **QM-V1-m3** — the `held` host intent is chosen by exactly the property `check()` then asserts, so that
  case cannot fail; the flipped host intents are sampled, not swept.
- **QM-V1-m4** — "every digest title and copy label" carries the server-attested clause, but only the
  banner's two titles and the panel's two copy buttons are tested; the header trigger's title is untested
  and `StatusBar.tsx`'s sha256 title does not say the value is AssessHub's statement.
- **Stated limits of the runtime dataset:** the hub fetch has no size cap (an opened file is capped at
  64 MB; `X-Snapshot-Bytes` is known before the body); opening a file needs a secure context
  (`E_NO_WEBCRYPTO` outside localhost/https).

### O76. Decisions phases 3 and 3.5 leave for the owner — OWNER DECISION
- **The phase gate's literal "no compiled-evidence key names in the hub build" criterion cannot be met by any
  hub build that compiles at run time.** Four `dist-hub` files (boot, compile worker, mount, opened) carry
  the key NAMES `sourceDigestForm` and `sourceGitBlob` — 18 occurrences, from the bundled runtime compiler
  — and none binds them as data: AssessHub's own `_scope_file_carries_compiled_model` returns False on all
  13 files, and `app.py` documents that names alone are not the signature (the app gate). Restate the
  criterion as the indexer's verdict, or say what else it should mean; product code was not changed to hide
  the names.
- **A test-only module boundary** for `src/forwarding/golden-expectations.ts` (O71).
- **The C1 "3-D render" dimension** — keep it in C1 as network visualisation (our traced path against
  Forward's 2-D topology path) or move it to C5.
- **`src/fabric3d/layout.test.ts`'s work-budget constant** for small fleets (O74).
- **Receipts that need a quiet host:** the scale budgets (O74), E3 across runs (three quiet runs of one
  build), and any further focus-audit run, which the instruction of 2026-09-29 now withholds (O68).
- **Not run in this phase by owner instruction:** the C1 critic panel (O70) and the acceptance re-grade, so
  no criterion moves on the strength of phases 3 and 3.5.

### O77. The phase-3.5 close gate's uncommitted product changes are unverified, and one of them has a regex defect — OPEN (owner: `src/app/focus-return.ts`; an independent verifier for R129)
Found by the record step reading the diff against `f24b9ccb` (not exercised by any test the record step
ran). The new outward-landmark walk in `handOffFocus`'s plan (`src/app/focus-return.ts`, line 419) splits
`aria-labelledby` with `/s+/` — the letter "s" — where the line above it uses `/\s+/`. For a region whose
labelling id contains an "s", the heading is not found and the walk falls back to focusing the region
itself, a softer landing than the heading rule 4 intends; for an id list, the split is wrong outright.
More generally, R129's product changes — this walk and the `hidden`-subtree check, the Evidence pane's
"Select <host>" hand-off, and `DataGrid.tsx`'s hit-all probe sheet — have had no independent verifier and,
by the owner instruction, no focus-audit run; the gate's full suite ran after all of them (file times
against the gate's logs), which is the only evidence they have.
**Status at W5 (2026-09-30), the preview-scope repairs after phase 3.5 — the regex defect FIXED IN CODE;
the outward walk and part of R129's verification stay OPEN.** From R-D3 and its verifier (reported).
- **Closed:** `idRefs` in `src/app/focus-return.ts` is the only split of an ID-reference list and uses
  `/\s+/`, pinned by `src/app/focus-return.labelledby.test.ts` (R131). R-D3 checked R129's
  `focus-return.ts` changes — including the `handOffFocus` walk that the Evidence pane's "Select <host>"
  hand-off uses — against rule 4, and restated rule 4 once for every door, with a rendered check in
  `tryFocus` (R131).
- **V2-3 — OPEN.** The outward walk is not one statement for every door: `returnFocus` tries only the
  nearest region's places and then the recorded region, so when those are unrendered and an outer named
  region is shown it returns null with focus on `<body>`, against the module's own "never land on
  `<body>`".
- **Not covered by any W5 report:** R129's `DataGrid.tsx` hit-all probe sheet still has no independent
  verifier. R129's repairs are now committed (`363e865e`, "close phase 3.5"); W5's own edits are
  uncommitted in this working tree.
**Status at W5b (2026-10-01), the follow-up of the W5 repair wave — V2-3 FIXED IN CODE; the `DataGrid.tsx`
probe sheet is still unverified.** From S-D3 and its verifier (upheld; reported). W5's edits are now
committed (`2145187a`); W5b's are uncommitted on top of `22373163`.
- **Closed:** V2-3 — `returnFocus` walks outward (W5b's earlier pass), and both halves of the walk, around
  the context and around the recorded target, are pinned by two portal-layout tests in
  `src/app/focus-return.rule4-doors.test.ts` (13 of 13; the verifier's mutations B, B2 and B3 fail them)
  (R139).
- **`DataGrid.tsx`:** `paintedBox`'s own containing-block hand list (SD3V-5) is replaced in the working tree
  by `containsFixedBoxes`, and `focus-return.sight.test.ts`'s `KNOWN_COPIES` is empty (read from the diff;
  no report names the edit). The guard that holds it catches only a copy that reads `will-change`
  (SD3R2-2, O68).
- **Still not covered by any report:** R129's `DataGrid.tsx` hit-all probe sheet has no independent
  verifier.

### O23. Clean-clone evidence — the re-grade of `78bdba5` ran F1, F2, F4 and F5 from a fresh clone of that commit (F1, F4, F5 PASS; F2 red, R85); the re-grade of `8eac055` ran F5 from a fresh clone of it (PASS); the re-grade of `34bd435` ran F1 in part, F4, F5 and F6 from a fresh clone of it; nothing has been run from a clone of `7f67013` — OPEN for A–E, F2, F3 and the scripts `tsc` project at `34bd435`, and for everything at `7f67013` (owner: the re-grade of `7f67013`)
**Status at `7f67013` (wave 8).** The heading's old claim — "nothing has been run from a clone of
`ba7b456` or `34bd435`" — was contradicted by the re-grade of `34bd435`, whose F group worked in the
working checkout plus a fresh `git clone` of `34bd435` (parent blob `1ed99404` at `../webapp`): F1
through the clone's `npm run build` (`tsconfig.json` and `tsconfig.config.json`, not the scripts
project), F4 and F6 on that clone's build served on :4191, and F5 (all 4 compilers byte-identical under
`core.autocrlf=true`). A–E, F2's `vitest`, F3 and the scripts `tsc` project did not run from a clone.
Every wave-8 check — the clusters', the gate's, the orchestrator's at `7f67013` and this
reconciliation's — ran in the working checkout or private builds of it (W8-queue-focus-reveal also
served a `git archive` copy of `fea2037` for its before-runs, which is not a clone and not the commit
under grade), so nothing has been run from a clone of `7f67013`. The `../webapp` parent-blob dependency
is unchanged.

**Status at `34bd435` (wave 7).** The heading's old claim — "nothing has been run from a clone of
`8eac055`" — was contradicted by the re-grade of `8eac055`, whose F refuter ran all 4 compilers from a
fresh `git clone` of `8eac055`: F5 PASS, `git status --short` empty afterwards. A–E, F1–F4 and F6 were
not run from a clone. Every wave-7 check — the clusters', the gate's, the orchestrator's at `34bd435` and
this reconciliation's — ran in the working checkout or private builds of it, so nothing has been run
from a clone of `ba7b456` or `34bd435`. The `../webapp` parent-blob dependency is unchanged.

**Status at `8eac055` (wave 6).** The heading's old claim — "nothing has been run from a clone of
`70bea72` or `78bdba5`" — was contradicted by the re-grade of `78bdba5`, whose F group ran F1, F2, F4
and F5 from a fresh `git clone` of `78bdba5`: F1, F4 and F5 PASS there, and F2 red (12 timeouts at
about 85 % load, fixed in wave 6, R85); A–E and F6 were not run from a clone. The W6-f2 cluster ran the
full suite twice from a fresh clone of `efc3929` plus its own six files (reported, R85) — neither
`78bdba5` nor `8eac055`; every other wave-6 check, the orchestrator's and this reconciliation's ran in
the working checkout. Nothing has been run from a clone of `8eac055`. The structural `../webapp`
dependency below is unchanged.

**Status at `78bdba5`.** The re-grade of `70bea72` ran nothing from a fresh clone: its F refuter used
`git archive` sandboxes, which apply `.gitattributes` but are not a clone, and every other group ran in
the working checkout or a private build of it. Wave 5 changed 48 files in `78bdba5`; the agents, the
gate, the orchestrator and this reconciliation all ran in the working checkout (W5-K1 and W5-K2 also
served `git archive` copies of older commits, for regression origins, not for grading). F4's new
build-output test builds whatever checkout runs it, so it will run in a clone; it has not yet. The
structural limit below is unchanged.

**Status at `70bea72`, superseded above.** The re-grade of `443a05a` closed this for F5 at that commit (a real
`git clone` under `autocrlf=true` reproduced all four compiled outputs byte-identically); F1, F2 and F4
ran in the working checkout and A–E did not run from a clone. Wave 4 changed 58 files across
`2d9712c`, `8e873d2` and `70bea72`, and every check since — the agents', the gate's, the
orchestrator's and this reconciliation's — ran in the working checkout. The structural limit below is
unchanged.

**Status at `443a05a`, superseded above.** The re-grade of `1d19e22` closed this for F1, F2 (unit half), F4 and F5 on a
clean clone of `1d19e22`, with the parent blob `1ed99404` placed at `../webapp`; A–E were not re-run
from a clone. Wave 3 changed 73 files; nobody has cloned `atlas-scope` at `443a05a` and run anything
from the clone (the orchestrator's `tsc`, `vitest` and build ran in the working checkout, which is
clean at that commit). The structural limit below is unchanged.

**Original entry (wave 2c).** Every F1–F6 result in `docs/acceptance-report.md` was taken on an
uncommitted working tree, and `acceptance.md` asks for a re-run on a clean checkout of the resulting
commit. The tree is now committed (O10), but that re-run has not happened: no one has cloned
`atlas-scope` at `1d19e22` and run `tsc`, `vitest`, the build, the compilers or the capture gates from
the clone. One limit that re-run will meet
is structural, not a defect of the commit: the compilers read
`../../webapp/sample_data/sample_fleet.snapshot.json`, which only the parent repository tracks, so
reproducing F5 from a clone needs the parent at a revision whose blob hashes `9580aa09…3089`.

### O8. The ignore-ACLs counterfactual (design-brief §5.2 step 6) is NOT BUILT — and is no longer advertised
Found by an independent critic, confirmed at the source. The command palette carried
**"Toggle the ignore-ACLs counterfactual"** with the shortcut `M`, and explained its unavailability
as *"the path panel is not on screen in this layout, so this action has nothing to act on"* — a
sentence rendered **with the path panel on screen and a trace drawn**
(`?s=path&flow=10.0.10.50>10.0.30.10>tcp>3389`). Nothing in `src/` ever registered a target or
published a `data-atlas-command` owner for `acl.toggleCounterfactual`, so `capabilityAvailable()`
was permanently false. `claims.ts :: T6_counterfactual()` — the brief's T6 template — has zero call
sites outside its own module.

**What was done, and what was deliberately not.** The palette row and the orphaned capability are
removed, and `src/app/commands.capability-owners.test.ts` now asserts over the source that EVERY
member of the `Capability` union has a registrar or a DOM owner — so an orphan is a build failure
rather than a misleading palette row. The feature itself was not built here: doing it properly
needs (a) a `traceFlow(flow, { ignoreAcls })` option in `src/forwarding/engine.ts` — feasible, the
ACL gate has exactly one call site, `engine.ts:1293` — and (b) the `MODE · ignore acls` chip the
brief requires to be carried in the shareable URL, which is `src/core/store.ts` + `urlSync.ts`.
This repair pass was scoped out of both files. `T6_counterfactual()` is retained unused, as the
written contract for the pair of statements that feature must render.

**Do not close this by re-adding the palette row.** A verb announced with a false reason is worse
than an absent one: the reader concludes their layout is wrong.

**Status at `34bd435`.** Not examined by the re-grade of `8eac055`. Wave 7 changed none of
`src/forwarding/engine.ts`, `src/core/store.ts` or `urlSync.ts`, and added no counterfactual palette
row (`commands.ts` changed only the flow rows' detail text, R93). Still NOT BUILT and not advertised.

**Status at `7f67013`.** Not examined by the re-grade of `34bd435`. Wave 8 changed none of
`src/forwarding/engine.ts`, `src/core/store.ts`, `src/app/urlSync.ts` or `src/app/commands.ts`; its
`CommandPalette.tsx` change is the match-reason rendering (R104), which adds no row. Still NOT BUILT and
not advertised.

### O9. B6 asked for the raw SOURCE record; the Inspector can only show the compiled one
The source snapshot is not bundled with the build, so for any citation that is not itself a model
path the Inspector renders the compiled record that carries the citation and says so verbatim:
*"This citation names a record in the source snapshot, which is not bundled with this build. Shown
below is the compiled record that carries the citation…"*. The behaviour is honest and citation
resolution is sound (a probe over all 652 model cites plus the 16 the engine emits at runtime
resolved every one). The **criterion** was what overclaimed, so `docs/acceptance.md` B6 has been
restated to describe what the product does and states.

The capability gap is real and is left open here rather than papered over: shipping a lazily
fetched side file of the snapshot subtrees that carry a cite, keyed by cite, would let the Inspector
show actual snapshot JSON. That is a compiler change (`tools/compile-snapshot.mjs`) and was out of
scope for this pass.

**Status at `70bea72`.** Unchanged in substance. Wave 4 (R54) compiled the `link_centrality`,
`health_scores` and `cable_map.nodes` rows under their source paths, so those citations resolve to a
compiled copy of the source record at the path they name (reported: "This citation resolves directly
inside the compiled model at link_centrality[3]"). The raw snapshot is still not bundled; the re-grade
of `443a05a` found this entry consistent with B6's first-pass evidence and B6's FAIL a different gap.

**Status at `78bdba5`.** Unchanged in substance: the re-grade of `70bea72` upheld B6 (796 of 796 model
citations resolve) with this entry as its note. One reach fix since: below 768 px the Inspector a
citation opens was never on screen, and now is (R74) — the compiled record is shown at every width, the
raw source record at none.

**Status at `8eac055`.** Unchanged in substance. The re-grade of `78bdba5` noted again that "Open
source record" opens the compiled record and says so. Wave 6 multiplied the routes into it: every
in-sentence citation on the Path surface is now a control (R81), and the reported example,
`routing_neighbors.core1.ospf[0]`, opens `rib-evidence.json#hosts.core1.adjacencies[0]`, "labelled as
the compiled record that carries the citation". The raw source record is still not viewable.

**Status at `34bd435`.** Unchanged in substance, and now said more exactly. The re-grade of `8eac055`
(its new item 4) widened this to model-path citations: for 97 citations that are both a model path and
a source-snapshot path, the Inspector said the citation "resolves directly inside the compiled model"
and never that the source record differs. Wave 7 fixed the wording (R95): such a record is now labelled
the compiled projection, which "may differ from the source record". Wave 7 also multiplied the routes
into the Inspector again — every preset, device-pane, evidence-chain and JSON-tree citation (R92–R94).
No compiler or data change: the raw source record is still not viewable.

**Status at `7f67013`.** Unchanged in substance. The re-grade of `34bd435` upheld B6 (726 distinct cites,
0 unresolved; for all 97 model-path cites the resolved record's own `cite` equals the citation) and found
this entry unchanged: the Inspector shows the compiled record for bearer cites and says so, and R95's
wording held under attack. Wave 8 changed no compiler, data or `Inspector.tsx` code (only
`Inspector.css`'s width rung, R103). The raw source record is still not viewable.

### O6. At the `high` quality tier, bloom turns honest status rings into halos
Captured at `review/shots/fabric-auto.png` (auto-selected tier `high` on real Intel D3D11, 80 draw
calls, 225k triangles). Every chassis is wrapped in a heavy warm halo that buries the port banks,
bevels and faceplates — the silhouette detail that is the entire reason the chassis geometry exists.
Compare `review/shots/fabric-check.png` at tier `low`, where bloom is off and the same fabric reads
noticeably *better*.

**It is not a correctness bug, and that distinction matters.** The rim colour is the device's health
band, and 18 of the 26 devices in this fleet really are Poor or Critical
(`{Poor: 12, Critical: 6, Good: 3, Excellent: 2, null: 3}`). A fabric that looks alarming is an
honest rendering of an alarming fleet. What is wrong is the calibration: at 18 simultaneous glows
the effect stops reading as "these devices are in a bad band" and starts reading as an undifferentiated
alarm wash, which is a failure of the encoding rather than of the data.

It surfaced only after R5 was fixed: while the shader was failing, the status rims drew nothing at
all, so there was nothing for bloom to pick up. Fixing one defect exposed the next.

Candidate levers, in the order I would try them — **not yet applied**, because the render critic
should reach its own verdict first rather than being handed mine:
  - `state-rim.emissiveIntensity` (currently 1.05) versus the brief's `luminanceThreshold: 1.0`
    floor — the rim is only just crossing the threshold, so a small reduction may drop it out
    entirely, which would be the wrong fix;
  - `SelectiveBloomEffect` `intensity` / `radius` / `levels`;
  - rim geometry screen size, so the glow is proportionate at overview distance.

**Status at `8eac055`.** The re-grade of `78bdba5` noted the bloom halos at the high tier again under
C5 (still open, not a C5 failure). Nothing recorded here shows a lever above applied; `8eac055` touches no
post-processing, lighting or quality file (`git show --stat`). OPEN. **Status at `34bd435`.** Not
examined by the re-grade of `8eac055`; wave 7 touched no post-processing, lighting or quality file
either (`git diff --stat 6a5d830 34bd435`). OPEN. **Status at `7f67013`.** Not examined by the re-grade
of `34bd435`; wave 8 touched no post-processing, lighting or quality file (`git diff --stat fea2037
7f67013`). OPEN.

### O7. A `SCOPED` badge on a verdict whose own caveat undercuts it — QUESTION FOR THE HONESTY AUDIT
Observed in `review/shots/panels-check.png`. The trace for tcp/3389 `10.0.10.50 -> 10.0.30.10`
renders the **SCOPED** badge — the strongest this product has — while its own claim sentence reads:

> "…is denied at core1 by ACL PROTECT_SERVERS line 3 …; **the ACL's interface binding was not
> collected**, and stateful return traffic is not modelled."

The badge is behaving exactly as specified: `claimBadge` awards SCOPED when the traversal completed,
every host on the path is in `coverage.routableHosts`, and no HOP-level evidence item is an absence.
Here core1 is modelled, there is one hop, and nothing at hop level is indeterminate. The rule fires
correctly.

The question is whether the rule is right. No `ip access-group` binding was collected anywhere in
this snapshot, so we do not actually know that `PROTECT_SERVERS` is applied to the interface this
flow traverses. That is not a peripheral caveat — it is uncertainty about **whether the named rule
governs this packet at all**, which is the entire content of the verdict. A badge that says "as
strong as this product gets" sitting above a sentence that says "we could not confirm this ACL
applies here" is at least in tension, and possibly the exact overclaim §6 exists to prevent.

Two defensible readings, and I am deliberately not choosing between them here:
  - **As designed.** SCOPED never meant "certain"; it means the traversal was complete within the
    collected RIBs, and the caveats are rendered immediately beneath it in full. The badge grades
    COVERAGE, not confidence.
  - **A gap.** Trace-level caveats that bear on whether the deciding rule applies should demote the
    badge to OBSERVED, so badge and prose cannot disagree.

**Assigned to the honesty audit in the critique loop**, which did not build any of this and should
reach its own conclusion. If it agrees this is a gap, the fix is in `claimBadge` — a caveat
classifier that distinguishes peripheral limits from ones that undercut the deciding evidence.

**Update 2026-09-21 — the premise was false.** The snapshot DOES carry bindings (`interfaces.core1.
Vlan30.acl_out = PROTECT_SERVERS`, `interfaces.core1.Vlan20.acl_in = VOICE_FILTER`, and a
`candidate_projection_incomplete` marker on core1 Gi1/0/5); the shared compiler never projected them.
They are now compiled by `tools/compile-acl-bindings.mjs` into `src/forwarding/acl-bindings.json`
(sha-bound to fabric.json) and read by `src/forwarding/bindings.ts`. A hop applies exactly the lists
bound on the interfaces it enters and leaves by when those bindings are observed; the specificity rule
runs only where one is unknown, and the hop names which and why. The 3389 denial now reads "the list is
applied outbound on core1 Vlan30 (interfaces.core1.Vlan30)", so the SCOPED badge and the sentence
under it agree. A denial by a heuristically chosen list still records an `acl-unbound-denial` policy
gap and cannot be SCOPED.

**Status at `34bd435`.** Not examined by the re-grade of `8eac055`; wave 7 changed no forwarding code
and only a comment in `claims.ts` (R100), so the rule `claimBadge` applies is as described above.

**Status at `7f67013`.** Not examined by the re-grade of `34bd435` (whose A3 grading rendered the same
3389 denial, "PROTECT_SERVERS line 4 of 4", and found no denial DECIDED); wave 8 changed no forwarding
code and not `claims.ts`. As described above.

### O5. First-look observations on the 3-D fabric (mine, recorded BEFORE independent critique)
Written down now, deliberately **not** fed to the critique loop's render critic. The critics judge
blind; if they independently surface the same items that is convergent evidence, and if they find
things this list misses that is a measure of how much a single reviewer misses. Feeding my notes
in first would destroy both signals.

Observed from `review/shots/fabric-check.png`, 1600×900, dark theme, SwiftShader (quality tier
`low`, so some of this may be tier-specific — flagged where relevant):

1. **Camera framing is too wide.** The fabric occupies roughly 40 % of the frame; the rest is empty
   background. The brief's framing should fit the bounding sphere with margin, not with a void.
2. **The layout reads as a hub-and-spoke starburst, not a tiered hierarchy.** The core pair sits at
   top centre and everything radiates from it. `layout.ts` does run barycentre sweeps and its tests
   assert measurably fewer crossings than naive ordering — so this may be a CAMERA-ANGLE problem
   (a near-plan view projecting a clean tier structure into a radial one) rather than a layout
   problem. Worth distinguishing before anyone "fixes" the layout.
3. **Heavy cable crossing in the middle band**, following from (2).
4. **Contact grounding reads as soft blobs** rather than crisp occlusion. Possibly the `low`
   quality tier disabling or downscaling SSAO under SwiftShader; needs a check at `high`.
5. **No device labels** in this capture — expected, since `FabricLabels` is a DOM overlay and the
   preview harness mounts only the canvas. Not a defect; noted so it is not mistaken for one.

None of these is a correctness defect. They are craft items, which is exactly the category the
blind comparison exists to adjudicate.
