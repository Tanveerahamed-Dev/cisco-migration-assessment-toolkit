# Session log

Append-only, one entry per working session. Newest first. This is `CHAT_SUMMARY.md`'s lightweight successor
(that file froze at 2026-06-12): a line here costs nothing and keeps the narrative queryable by graphify.
Format: `## [YYYY-MM-DD] — <headline>` + 3–6 bullets. Failures worth remembering get a `!lesson` tag.

## [2026-07-25] — Emptied the PR queue (#476/#477/#478 + #479 closed) and swept the repo to zero merged branches; the sweep's own tooling was the least trustworthy thing in it

- Second half of the gate-swarm session. Merged the three remaining fixes — **#476** (a plan doc that
  re-opened a decision closed on 2026-07-11 and recommended a lever already measured-REFUTED),
  **#477** (the Trunk Native-VLAN sheet printed "across the 303 collected device(s)" when 253 were
  collected, inside the very sentence meant to BOUND the claim; the fix restates it in LINKS and
  discloses a 50% blind spot), and **#478** (`INCOMPLETE-SET.txt` opened with "Everything in this
  folder IS redacted and safe to share" while a stale UNREDACTED file from a failed run sat under the
  canonical name). Closed **#479** as superseded — its premise ("#445 is red, #445/#439 cannot both
  merge") was true when written and false once the `_emit()` chokepoint landed both. Then swept the
  repo: **37→13** remote branches, **33→17** local, **10→1** worktrees, **0** open PRs, **0** merged
  branches left. Final `main` `bd6ad5a`.
- `!lesson` **State changes between the check and the act — re-verify immediately before anything
  destructive.** Asked to delete a retro branch, I checked it: 0 commits beyond main, no worktree, an
  empty ref created minutes earlier. By the time the instruction to delete it arrived, a CONCURRENT
  session had committed a 49-line retro to it, pushed, and opened a PR. Deleting on the earlier
  reading would have destroyed that work and orphaned its PR. The window was minutes. Re-run the
  containment/emptiness check as the FIRST step of the deletion itself, never rely on a reading taken
  one exchange ago — and in a shared checkout assume another session is writing right now.
  bridge-candidate
- `!lesson` **A red required check is not evidence of a defect — on an old branch it is usually the
  branch's own STALE DEBT.** #477 and #439 both showed `Ruff lint FAIL`, and in both cases it was the
  identical unused `import pytest` that main had already fixed (`3f7fb6a`, via #444); the branches were
  47 and 21 commits behind. The fix is `git merge origin/main` (0 conflicts both times), not debugging
  the lint. Before investigating a failing check on a stale branch, ask whether MAIN already fixed it —
  measure `git rev-list --count <branch>..origin/main` first. Same family as the runner-contention
  `cancelled` flakes: on this fleet a red X is more often infrastructure or staleness than code.
  bridge-candidate
- `!lesson` **Verify a correction PR's own citations — the genre invites unverified authority.** #476
  corrected a plan by asserting the decision was already recorded in an owner-doc. That is exactly the
  claim that would be embarrassing to take on trust, so all three citations were checked against
  `docs/quality/README.md` on main before merging (the ladder section, the accept-PARTIAL decision, the
  not-more-models ruling) — all resolved. Likewise #477 claimed it re-derived no canonically-owned
  fact: `CANONICAL_FACTS` holds 14 keys and none is link-scoped, so the claim held. A PR whose purpose
  is fixing stale claims is the one where an unchecked citation does the most damage. bridge-candidate
- **Where the day's defects actually were.** Across every code PR merged today the failing CI check was
  stale lint debt, while the real defects were all in ASSERTIONS: a banner overstating device coverage,
  a note declaring a folder safe over an unredacted file, a docstring citing a deleted API, an
  end-of-run filter matching no status that exists, and this session's own runbook confidently
  instructing the operator to delete a working feature. The concurrent session's retro reached the
  same conclusion independently — *the code was fine; every defect was in a claim.*
- **Closing verification, and one revival the sweep paid for.** The 31 `refs/preserved/*` were pushed
  to origin (`refs/preserved/*`, NOT `refs/heads/*` — durable without reappearing as branches) and then
  audited BY CONTENT rather than by commit count: per ref, per file, `comm -23` the added lines against
  **main's version of that same file**. That reduced 31 candidates to exactly ONE genuinely-unlanded,
  still-relevant piece — and caught two claims of mine that were wrong in the dangerous direction
  (`fix-coverage-honesty-fmc-rest-pagination` read as unlanded while main held a HARDENED SUPERSET, its
  guard wrapping `urlsplit().port` in try/except because that RAISES ValueError on a non-integer port;
  reopening it would have REGRESSED a security guard. `harden-security-expensive-get-cross-site` read
  as unlanded while main had the guard 11× over, its single "absent" line the boilerplate
  `with TestClient(app) as c:`). The one real candidate was rebased 101 commits onto main, its tests
  proved live by fault injection (stub `gate_disclosure` → `None`, 3 tests go red), and merged as
  **#487** — closing the hole #448 recorded as its own open item (b): `deliverables.py::generate`
  served design/MOP over HTTP with no gate check. It landed only because #439's per-campaign ledger
  merged the same day, which is what the earlier attempt (#437) was refuted for lacking. Then the
  checks that per-PR CI structurally cannot do: the **full gate on final `main`** (`3617272`) — Ruff
  clean, suite `PYTEST_EXIT=0` — because each of the day's PRs was verified against a `main` that then
  moved 14 times, and `webapp/backend/serve.py` alone absorbed changes from **13** of those merges
  while `gate_state.py` was refactored twice before #487 landed on top; and a full offline graphify
  re-extract from the main checkout (**9443 nodes / 16118 edges**, both UP from 9422/16083 — the
  shrink-guard signal that it was a healthy full rebuild, not a truncating incremental).

## [2026-07-25] — `--redact-folder` claimed a folder was "safe to share" over an UNREDACTED file (#478); every defect I shipped this session was in a CLAIM, never in the code

- Built the deliverable-completeness feature, then found **#438 already shipping it** and conceded —
  but salvaged the orthogonal half as **#440**: `_assert_redaction_phases_ran` read `.phase_timings.json`
  as a list while the engine writes a dict, so `str.get` raised `AttributeError` into a defensive
  `except` and that arm was **dead on every real run**. Then closed the successor defect as **#478**:
  a run whose redaction check FAILS leaves `DO-NOT-SEND-NOT-REDACTED.txt` and its unredacted documents
  on disk; re-running with `--reuse-out` and losing one writer leaves that UNREDACTED file under the
  canonical name, reported only as `stale` — while `INCOMPLETE-SET.txt` asserted *"Everything in this
  folder IS redacted and safe to share."* Reproduced byte-identical against main before fixing.
- `!lesson` **A hand-fabricated fixture makes the stub AGREE with the parser bug.** The test covering
  the dead arm faked the sidecar as `json.dumps([{...}])` — exactly the shape the buggy parser expected.
  Stub and bug agreed, test stayed green, guard was dead. A fixture encodes the author's belief about
  the producer's format, which is the same belief that produced the bug, so it can only ever confirm it.
  **Feed at least one test the REAL producer's output**, and assert the VALUES it keys on actually occur
  (the watched phase names exist only under `--redact`; without that flag the ratchet passes vacuously).
  bridge-candidate
- `!lesson` **Fixing a parse is not fixing the guard — enumerate what else still produces silence.**
  Normalising the shape made the arm fire and left every other unreadable ledger silent: renamed key,
  rows keyed by name, tuples, `null`, `ok: 0`, `ok: "false"`, or a watched phase with NO row. The bug
  had moved up one level, not gone. For a safety gate, "cannot confirm" must REFUSE with its own
  message, distinct from "confirmed failed". Never test a JSON flag with `is False` — `0`, `"false"`,
  `null` and a missing key all have to count. bridge-candidate
- `!lesson` **A CLAIM has exits too — grep the sentence's wording, not the function.** After fixing the
  note, `grep -rn "safe to share"` across `*.py/*.txt/*.md` found the same promise twice in
  `README-FIELD.txt`, the engineer's ONLY on-site documentation. Code-only would have left the guide
  contradicting the folder. Prose copies of a safety claim live in READMEs, exit-code tables and console
  strings — none of which appear in a call graph. Corollary: the ratchet I added to protect that guide
  asserted a 9-word phrase against a hard-wrapped file as a NEGATIVE assertion — one word of re-wrap and
  it passes having checked nothing. Match on `" ".join(text.split())` and prove BOTH directions.
  bridge-candidate
- `!lesson` **During a wait, query the field that would prove the wait UNNECESSARY.** The user merged
  #478 at 01:10Z; its queued CI kept running (GitHub does not cancel it), so I polled `check-runs` until
  05:19 waiting to "merge when green" on something already on main. At 04:49 I ran
  `gh pr view --json mergeable,mergeStateStatus,reviewDecision` — picking exactly the fields that fit my
  mental model and omitting **`.state`**, which read MERGED the whole time. A merged PR returns
  `mergeable=UNKNOWN` and keeps `reviewDecision=REVIEW_REQUIRED` if admin-merged, so every field I DID
  query looked like "still waiting". Always include `state,mergedAt`; a persistent `UNKNOWN` is itself
  the tell. bridge-candidate
- `!lesson` **`busy=true` + 0 jobs is a real wedge; `in_progress: 0` at RUN level is not.** The fleet
  genuinely wedged once (8 stacked `Runner.Listener` processes — each restart ADDS a pair without
  stopping the old, so repeated restarts made it worse; fix is kill-all then ONE relaunch, and the
  relaunch must be the human's because this harness's `NoDefaultCurrentDirectoryInExePath` leaks into
  every job). But I then called it wedged a second time on the run-level `in_progress: 0` reading while
  both runners were executing jobs fine — run status lags job status. Check for a live job by
  `runner_name` across recent runs before touching anything; I nearly killed two healthy jobs. Also: of
  27 queued runs, 19 belonged to already-MERGED PRs and were pure starvation — cancelling those (never
  `main`'s) unblocked all four open PRs. bridge-candidate

## [2026-07-25] — Landed the 5-PR gate swarm (#448/#441/#444/#439/#445): three of my own "verified" resolutions were wrong, and the metric I was watching hid each one

- Merged all five PRs that had been pairwise-conflicting on `cisco_toolkit/gate_state.py` (main
  `a3f921b`). The last pair was not a merge conflict at all: **#439 and #445 independently implemented
  the SAME feature** — audit every gate verdict, not just overrides — as a rich `GateVerdict` return
  vs a module-level `_VERDICTS` ledger sealed into the run manifest. Reconciled with a single
  `_emit()` chokepoint so the sealed row and the return value are built from one object and cannot
  disagree, and retired #445's flat `VERDICTS` enum in favour of #439's `STATUSES` (Law 1: a second
  enum for the same situations is the copy that drifts). Post-merge main: `GateVerdict` 18,
  `_VERDICTS` 5, `VERDICTS` 0, `if False:` 0.
- `!lesson` **Three automated conflict resolutions I had "verified" were wrong, and each passed the
  check I happened to be watching.** (a) A file-level `git checkout --ours` on the shared file scored
  a perfect `pending_approvals=1` while silently deleting the PR's entire +623-line feature
  (`GateVerdict=0`) — a file-level flag takes the WHOLE file. (b) Keep-both on a `serve.py` dispatch
  stacked two `if args.redact_folder` guards where the first (`is not None`) made the second dead;
  the dead copy was the only one forwarding `--reuse-out`, so the flag was silently dropped —
  **valid Python, `ast.parse` clean**, caught only by the other PR's tests. (c) My own
  `list(v.missing) or None` would have collapsed `[]` (evaluated, nothing missing) into `None`
  (never evaluated) — the "never-checked run scores as a clean zero" inversion. Rule: after a
  keep-both on any `if`/dispatch region, assert every flag the union claims is REACHED (AST-walk the
  guards), not merely present; and pair every count-based check with a second metric that would move
  in the opposite direction. bridge-candidate
- `!lesson` **A count proves a difference, not its meaning — check the merge-base before calling it
  staleness.** I measured `pending_approvals` = 5 on one branch vs 1 on main, concluded "stale
  references to a deleted API", and wrote a runbook telling the user to drive it to 1. At the
  merge-base the function did not exist: that branch **BUILDS** it (1 def + 4 prose refs + 13
  references in its own test file) while the other independently documented the opposite design. The
  delta was a live design divergence between two coherent PRs. Before reading a count as decay, ask
  what the merge-base had and whether the "extra" side DEFINES what it references
  (`grep -c '^def <name>'` + check the test file). bridge-candidate
- `!lesson` **Never point a fault-injecting refuter at a worktree you are still committing from.**
  I spawned an independent refuter to mutate a security control, gave it the SAME detached worktree
  I was working in, and a later `git add -A` captured its live injection —
  `if False: gate_reset_verdicts()` — into a PUSHED commit. Effect if merged: the per-run ledger
  never resets, so run 2's manifest seals run 1's verdicts — a FALSE audit record, worse than the
  missing one the PR existed to fix. It survived because the only guard on that property is a SOURCE
  GREP (`assert "gate_reset_verdicts()" in src`), which stays green against `if False:`. Give a
  mutating refuter its own checkout; before committing after any parallel agent,
  `grep -rn 'if False:' --include=*.py`; and never let a source-grep be the sole guard on a runtime
  property. bridge-candidate
- `!lesson` **A background task's "completed (exit code 0)" is the SHELL's status, not the tool's.**
  A full-suite run that died on `--timeout=900` (no `pytest-timeout` installed → pytest exit **4**,
  usage error, zero tests run) notified as exit 0, and I nearly merged four PRs on it. An
  unrecognised-flag failure looks nothing like a test failure: no `FAILED` line to grep, short
  output, fast finish — which reads as "clean run". Judge by the `PIPESTATUS[0]` you echoed INTO the
  output; treat pytest exits 4/5 as RED; and sanity-check that the run actually executed (progress
  dots, `[100%]`, plausible duration) — a sub-minute pass on a ~2200-test suite is a lie.
  bridge-candidate
- `!lesson` **In a squash-merge repo, every quick "is this branch merged?" check lies — only content
  settles it.** Cleaning up after the swarm, three standard tools each answered WRONG on branches whose
  work was fully in `main`: `git cherry` marked them `+` (absent) because squash-merging rewrites the
  patch-id; `git branch -d` refused them as "not fully merged" because it tests containment in the
  CURRENT HEAD, not `origin/main` — the checkout sat on an unrelated feature branch; and
  `git diff main...branch` showed a fat diff because 3-dot compares against the MERGE-BASE, so it
  displays content `main` already has. I also mis-read my own evidence, grepping the PRODUCTION file
  for TEST function names and taking the 0 hits as "tests missing from main". What actually settled
  it: per file, extract the added lines from the 3-dot diff and check each against **main's version of
  that same file** — all six scratch branches came back 0-absent (208/198/43/27/66/76 lines) and were
  safe to delete. Rules: use `git merge-base --is-ancestor <branch> origin/main` for containment (never
  `branch -d`'s verdict, never `--merged` from an unrelated HEAD), and fall back to content comparison
  whenever history was rewritten — and preserve anything genuinely absent as a ref before deleting.
  bridge-candidate
- **The independent refuter earned the whole exercise.** Beyond catching my contamination it found a
  real gap in the merge: `missing` is nullable ON PURPOSE (`None` = never evaluated, `[]` =
  evaluated-clean), but nothing pinned the two ownership statuses #439 added — dropping them from
  `UNEVALUATED` left the ENTIRE gate suite green while a run refused because the ledger belongs to
  another client sealed as evaluated-with-nothing-missing. Added the pin and proved it fails under
  that mutation. It also flagged that the widened WITHHELD filter told operators to `approve` /
  `--override-gate` for statuses documented non-overridable (and where `approve` would sign another
  engagement's ledger). Merging surfaced three more defects **none of which reading would have
  found**: sealing absolute paths broke `chain_root` determinism; the engine's end-of-run summary
  filtered `verdict.startswith("refused")`, which NO status in the new vocabulary satisfies, so every
  withheld deliverable would have vanished from the operator's last line; and a test dict keyed by
  verdict name collapsed three scenarios into one.

## [2026-07-24] — Closed a 3-class stored-DoS series (16 PRs), then consolidated 141 branches to 32 — the cleanup found the bug the hardening missed

- Closed the **truthy-non-container** falsy-guard class across every deliverable generator (#462-#471),
  then its two siblings: the **unhashable-key** class (#464/#466) and the **non-str leaf** class (#473).
  ~110 attacker-reachable sites, each proven by executed repro (500 -> 200 through the real route),
  non-vacuous against the pre-fix module, and behaviour-preserving on well-formed input. A 6-unit
  parallel batch did the bulk; every unit got an audited site list AND an explicit leave-alone list.
- `!lesson` **Fix at the PRODUCER, not the expression the fuzz names.** Proven by string-patching the
  pre-fix module: guarding `mop.py:707` alone made `:837` fire; guarding `:609` alone made `:111` fire
  (and `:111` needed a fixture shape the headline snapshot lacked, so it was invisible twice over). The
  fix that actually closed the class was at three producers (`_waves`, `_wave_sections`,
  `_join_group_records`). **After guarding a site, re-run the fuzz — a newly-revealed site means you
  patched a symptom.** Also: one fixture cannot enumerate a class (`:909`/`:912` are mutually exclusive
  branches of the same `if multi:`; the union across bases was 8 sites, not the 7 any single run showed).
  bridge-candidate
- `!lesson` **A recursive sweep can be green because of its CAP, not the code.** My own #457 sweep capped
  at `depth<=3` — exactly one level short of `collection_completeness.devices[i].missing`. After the
  section was un-excluded the sweep still passed while the bug was live. Raise the cap until the path set
  stops growing, then pin the deepest paths as asserted members so a future cap shrink fails loudly.
  bridge-candidate
- `!lesson` **A "provably safe / leave alone" verdict must come from an executed repro, never reasoning.**
  I wrote off `runbook.py:586` in the plan as "a deliberate fallback on an already-coerced list" — correct
  about the CONTAINER, blind to the ELEMENTS: `"risks": [5]` is a well-formed list with a scalar row and
  still crashes. A worker overrode me with a repro and was right. Across the batch my plan was wrong five
  times, each corrected by evidence, never by argument. bridge-candidate
- `!lesson` **Measurement instruments lie, and a green number is the dangerous kind.** Three times in one
  session: `pytest -rs` reports skips but NOT XPASS (a stale non-strict xfail was silently absorbing a
  regression on main until `-rX` exposed it); a `grep -ci xpass` matched my own shell echo line; a
  `wc -l` of `git status` sampled a parallel session's mid-merge tree and read 57 instead of 1. Re-measure
  before believing, especially when the number is good. bridge-candidate
- Consolidation: **141 -> 32 remote branches.** Delete-safe criterion was `merge-base --is-ancestor
  <branch> main` MINUS open-PR heads MINUS other sessions' `claude/*` MINUS the current branch.
- `!lesson` **Never delete a branch that heads an OPEN PR — it closes the PR.** My first "verified-safe"
  list (built from merge/absorption analysis) contained 4 open-PR heads and would have silently closed
  #442/#447/#449/#458. One of them, ADR-0005 + the Cognee utilization plan (149 lines), existed on NO
  other ref. The cleanup ALSO surfaced a live bug the whole hardening series missed: an orphaned branch
  from 07-14 held two unguarded `.strip()` leaves (`design_advisor.py` `device_id`/`next_hop`) that 500
  four untrusted GET routes — revived as #474 after its own test failed on main. **Orphan branches are
  where the bugs your current sweep cannot see are hiding.** bridge-candidate
- `!lesson` **"It merged" and "it is correct" are different claims.** #442's `docs/log.md` conflict would
  have merged cleanly with a naive marker-drop and passed every test, while silently placing a 07-22
  entry above a 07-23 one and corrupting the log's reverse-chronological order. Read the surrounding
  structure, not just the hunk. bridge-candidate

## [2026-07-23] — "best decision" on a finished branch: mapped a 5-session gate swarm, landed an orphaned ADR, added no sixth change

- The `fix/redaction-gate-posture` branch's code was done and its three recorded OPEN items were all already
  covered by parallel work: (a) the ledger-identifier fix is #439's ADR-0006; (b) the webapp design/MOP HTTP
  hole had its disclosure fix refuted and closed as #437, and is blocked on #439's per-campaign ledger; (c) the
  `test_d10_eval_set` concurrent-rebuild false-red was fixed by merged #446 (`load_graph_settled`). So the best
  decision was explicitly NOT to write more gate code into a swarm of five sessions (#439/#441/#444/#445 + this).
- Delivered the cross-session integration map the orchestrator alone can see: all four open gate/manifest PRs
  are CONFLICTING vs main; merge-tree-safe order #441→#445→#444→#448(this)→#439, and opened this branch as #448
  carrying that note. The rebase of #448 is human-owned: its conflict is inside `run_redaction_folder`, the exact
  function the merged #438/#440 also reshaped, so a mechanical rebase risks re-introducing the silent ungating —
  that resolution is the slot-4 merge, not a pre-tidy.
- Landed a genuinely orphaned artifact: the Cognee evaluation (ADR-0005 + utilization plan + two docstring
  citations) had sat uncommitted on NO git ref for four days. Committed as #447 off main in an isolated worktree,
  after web-re-verifying every external citation against primary sources (2601.07978 v4 numbers exact — pinned
  because v1/v2 lack the Cognee row; Cognee v1.0's remember/recall/forget/improve verbs confirmed literal).
- `!lesson` **A "best decision" probe on a branch whose work is done is usually an integration/hygiene call, not
  a new feature.** The reflex is to find code to write; when the territory is already claimed by parallel sessions
  the right move is to map the swarm, sequence the merges, and land the one orphaned clean thing. Adding a sixth
  change to contested code is how #437 got refuted. bridge-candidate
- `!lesson` **"Formalized as ADR-000X" in memory did not mean committed.** My own memory said the Cognee eval was
  "formalized as ADR-0005"; git showed the files existed on no ref — working-tree-only for four days. A future
  session would have assumed it was on main. Verify a "recorded/formalized" claim actually reached a commit
  before relying on it. bridge-candidate
- `!lesson` **Don't rebase a safety-critical branch to tidy a PR when the conflict is in the safety logic.**
  #448's conflict is in `run_redaction_folder`; resolving it mechanically could re-introduce the silent-ungating
  the branch exists to fix, which renders identically in output. Measure where a conflict lands before deciding a
  rebase is cheap. bridge-candidate

## [2026-07-22] — Gate refusals were unauditable, and the log they belonged in had been truncating itself since PHASE 2.7

- `cisco_toolkit.gate_state` logs `[GATE REFUSED]` on its own logger, but `setup_logging` configured
  only `CiscoMigrationAutofillV3_14_6` and root has no handlers — so verdicts fell through to
  `logging.lastResort` (WARNING+ to bare stderr, INFO discarded entirely) and grepping
  `cisco_migration_autofill_*.log` after a refused run returned nothing. An OVERRIDE always persisted
  (it appends an audit line to the store); a REFUSAL and the brownfield-ungated case left nothing at
  all — for a control whose overrides DEC-003 says are reviewed weekly. Fixed both halves: the
  `cisco_toolkit` tree now shares the engine's handlers (`propagate=False`), and every verdict is
  recorded structurally and sealed into the run manifest's hash chain as a `{"stage":"gate"}` step,
  where editing a refusal out breaks `chain_root`. Added a closing `[GATE] … WITHHELD` line because
  every finalize phase signed off `[OK]` even when both gates refused. Commits 845f388 + c85ca3d.
- `!lesson` **Judge measured output by EXPECTED MAGNITUDE, not presence.** My own end-to-end proof
  printed `[OK] sheet lines -> 3 hit(s)` and I reported it as success; ~66 were emitted. The engine
  re-imports itself by name for attestation, so under `python <script>.py` the module identity is
  `__main__`, the module body RE-EXECUTES, and a second `FileHandler(mode="w")` truncated the log near
  the end of every script-path run. A module-level "already configured" flag cannot fix that — the
  re-executed copy gets fresh globals; the process-global logging registry is the only reliable
  witness. The disproof was sitting in my own output: "N > 0" is not verification, ask "N of how
  many?" bridge-candidate
- `!lesson` **Moving code between modules silently moves it to a different logger tree.** The
  per-sheet `[OK]` confirmations left the engine and arrived in `cisco_toolkit.excel` in the SAME
  commit (8aa9a4e); `getLogger(__name__)` put them outside the configured tree and they vanished from
  the log with no error, for a year, while ~49 later call sites were born mute. When a refactor
  relocates logging code, check where its records now land — `git log -S` on a log string dates the
  disappearance precisely. bridge-candidate
- `!lesson` **Attaching any handler stops `lastResort` firing — so "file-only" silences your
  warnings.** The tempting quiet-console option (attach the FileHandler, not the StreamHandler) would
  have removed the WARNING/ERROR lines that currently DO reach stderr, producing a run that refused
  both gated deliverables and ended in five consecutive `[OK]` lines: "not observed" rendering as
  healthy, on the last thing the operator sees. Decide handler routing from the failure case, not the
  happy path. bridge-candidate
- `!lesson` **Refuters audit MY new diff, not only the pre-existing code — and they contradict each
  other.** Round 2 found four defects in code I had just written (a re-entry guard that would reuse a
  CLOSED handler and silently drop every later record; a `verdicts()` "deep copy" that shared nested
  values; a conftest in `tests/` when `testpaths` also covers `webapp/tests`; a `basicConfig()` call
  that no-ops when root already has a handler), plus two confidently-worded FALSE claims in my own
  comments. Two refuters then disagreed on log volume; the source settled it (both per-device sites
  are conditional). Adjudicate against the code — an accepted-but-wrong criticism is as bad as a
  shipped defect. bridge-candidate
- Repo-specific: the durable win is a STRUCTURAL guard that every `return` in `enforce()` is preceded
  by a `_record(...)`, plus one deriving `VERDICTS` from the source. Enumerating today's outcomes
  cannot catch tomorrow's; PR #439 adds two unrecorded refusal arms (mis-set `--gate-root`, ledger
  ownership) and both tests are designed to fail when it rebases, putting the naming decision with
  the author who knows the semantics. Merge this branch first, then #439.
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
## [2026-07-22] — `--redact-folder` silently ungated the PPDIOO gates; four refuter rounds reversed my answer twice and then found my own tests couldn't fail

- The bug: `run_redaction_folder` launches the engine with `cwd=mkdtemp()`, so `gate_state.enforce`
  resolved `docs/engagement-state.json` to nothing, took its "no store → brownfield" branch and
  returned True unconditionally. The As-Built Design and per-wave MOP rendered for ANY engagement,
  including one with approvals REVOKED. P0-3/DEC-003 was inert on that path for its whole life.
- Shipped (`fix/redaction-gate-posture`, 099ac65 + 6822242): that path stays UNGATED **by decision**,
  documented in `run_redaction_folder` + `gate_state.py`; engine `--gate-root` added for the CLI
  path where blocking is right; a mis-set root now REFUSES in enforce/record/show instead of reading
  as brownfield (the write side used to `makedirs` a phantom ledger and return a success receipt);
  and a caller inventory pins every synthetic-cwd engine launch to a declared posture.
- **OPEN, and this is the durable record of it** — the ledger has no engagement identifier, so
  ownership rests entirely on which root the caller passes. Until that is fixed: (a) the MOP cannot
  be gated here even though it is the one deliverable where blocking WOULD contain something (its
  cutover procedure, quantified rollback triggers, RACI and sign-off exist in no other artifact);
  (b) `webapp/backend/deliverables.py::generate` still renders design/MOP with no gate check and no
  redaction, served over HTTP — the larger hole; (c) `tests/test_d10_eval_set.py`'s edge test false-
  reds during a background graphify rebuild.
- `!lesson` **Blocking one renderer contains nothing if the content ships in another.** Refusing
  design/MOP looked like enforcement, but the engine writes the snapshot (:2817), explorer (:2831)
  and deck (:2853) — all carrying `design_blueprint.target_state`/`wave_plan` — BEFORE the gates run
  (:2864/:2879), and the gate a design fails on is `assessment_approved`, which that path ships
  regardless. Before gating a deliverable, ask which OTHER artifacts carry the same payload and
  when they are written; a partial block that reports "withheld" is worse than an honest ungated
  set. bridge-candidate
- `!lesson` **A control test whose control expects the broken outcome cannot fail.** My e2e for
  `--gate-root` had two arms — flag passed / flag omitted — but BOTH used an empty cwd, and the
  omitted-flag arm expected ungated, which is exactly what a broken default produces. Mutating the
  parser default (`"."` → `$HOME`) killed gating for every ordinary CLI run with the whole suite
  green. Mutate the DEFAULT, not just the explicit value, and make sure one arm exercises the
  ordinary un-flagged path. bridge-candidate
- `!lesson` **Once the logic is right, the defects move into the prose about it.** Rounds 1–2
  reversed the decision twice on evidence I hadn't looked for; rounds 3–4 found the logic sound and
  my claims wrong — an inverted reason, a false universal surviving in the exact docstring a guard
  pins as its justification, a prescribed `pending_approvals()` I had deleted, and a "measured, not
  guessed" limits list that was half guessed. Confidence did not fall as errors moved from code to
  comments. Audit your own assertions as a separate pass, and never predict what a refuter round
  will find — I called one "largely moot" and it returned live HIGHs. bridge-candidate
## [2026-07-22] — `--redact-folder` now says when the set is SHORT (#438) — and a second refuter, aimed at the decision rather than the code, overturned my design

- Closed the last silent-success hole in the redaction command: every engine deliverable writer is
  fail-soft (logs a warning, continues, exits 0 — deliberate, and left unchanged), so a run that
  rendered all but two documents reported the survivors as the whole family. Detection is a
  produced-vs-expected filename DIFF derived from `docmeta.FAMILY` (new `CLI_ARTIFACT_SUFFIX`,
  reconciled against the engine source by a ratchet test), not a log scan — chosen on evidence:
  the real engine with `--no-docx --no-pptx` drops two documents and logs NOTHING about either.
  Incomplete WARNS (exit 3), because a missing document is not a leak and the existing hard-fail
  path would print "treat this as UNREDACTED" over correctly-redacted files. Refuted twice before
  merge: 14 defects from a code-aimed pass, a design reversal from a judgement-aimed one.
- `!lesson` **Existence is not delivery.** Writers truncate their target and THEN write, so a full
  disk leaves a 0-byte `.docx`/`.html` carrying a brand-new timestamp; a name-and-mtime check
  certified it as delivered — the very bug the check existed to close, re-armed behind a "you have
  all of them" banner. Worse on a re-run, where the truncate destroys the good previous copy.
  Validate BYTES: size, plus the zip central directory, which sits at the END of a docx/pptx/xlsx
  and is precisely what an interrupted write loses. bridge-candidate
- `!lesson` **A comparison DIRECTION is an assumption — state it or lose to it.** `mtime > previous`
  silently assumes the clock only moves forward. On an air-gapped field laptop (manual time
  correction) or a FAT32 stick crossing a DST/timezone boundary, previously-written files read back
  as NEWER, and every document of a flawless run reported missing — the alarm-fatigue failure this
  repo has already paid for once. Inequality, not ordering; compare size alongside mtime so a
  rewrite inside one coarse timestamp tick is still seen. bridge-candidate
- `!lesson` **Prevention at second zero beats repair after the work — and count how often each
  fires.** A leftover deliverable from an earlier job sat under the canonical name of a document
  this run failed to write (and redaction keeps hostnames, so it identifies another client). I
  chose to MOVE it aside. Wrong: the engine seals a hash manifest over the folder BEFORE the move,
  so moving broke the audit trail it ships; the next successful run deleted the note and left the
  foreign file with zero disclosure; and it fired on the SAME-job re-run too, ripping a good
  document out of a complete set. The hazard needed three preconditions, the mitigation fired on a
  one-precondition case — the signature of the wrong altitude. Replaced with a pre-flight REFUSAL
  (output folder already holds a set) plus an explicit `--reuse-out` escape: milliseconds instead
  of ten minutes, and the precondition is removed rather than the symptom. bridge-candidate
- `!lesson` **Put field warnings on ONE stream, LAST.** Redirecting a long run to a log
  (`app.exe … > run.log 2>&1`) is the natural thing to do. Python block-buffers stdout and
  line-buffers stderr, so a warning on stderr was hoisted ABOVE the command banner — reading as if
  it belonged to a previous command — and the log ENDED on the reassurance block, so `tail` showed
  a clean success. Single stream, warning after the thing it qualifies. bridge-candidate
- `!lesson` **Reviewing the JUDGEMENT is a different activity from reviewing the CODE.** One
  refuter aimed at the implementation found 14 real defects and left the design intact; a second,
  aimed only at the decision, reversed it. Two habits came out of it: rank every rejected
  alternative with an argued verdict instead of dismissing it in passing (the option I had waved
  off as friction was the right one), and watch for "X is bad because it prints message Y" — I
  rejected a non-zero exit code on the strength of a message I could simply have changed.
  bridge-candidate

## [2026-07-22] — Shipped the wrong answer to a doctrine question through green CI, then reverted it under refutation (#437 closed)

- The question: should AssessHub's on-demand `deliverables.generate("design"|"mop")` consult the
  PPDIOO gate ledger, and if so which — `gate_state`'s per-engagement `DOC_GATES` or the webapp's
  per-campaign board? Answered "consult `gate_state`, but DISCLOSE rather than block", implemented
  it (an `X-Gate-Status` header), tested it, rebased, opened #437, got 13/13 CI green. Then ran
  three independent refuters, who dismantled it: **closed as REVERTED, unmerged.** The real answer
  is *don't gate this surface at all*; #439 (`pending_approvals`, with `ownership_mismatch`) is the
  right home, and the sibling `--gate-root` work landed independently as `099ac65`.
- `!lesson` **Before marking ONE artifact, enumerate every exit its content has — by request, not
  by reading.** I stamped the design/MOP DOCX. A refuter's harness showed the same
  `design_blueprint` leaving *unmarked* through seven other doors, including two sibling
  DOCX/PPTX off the very route I edited — 185 KB stamped while 460 KB of JSON and a 2.28 MB
  explorer walked out clean. Reading the code never revealed this; one `curl` sweep did. Marking a
  minority of the exits is theatre that reads as coverage. bridge-candidate
- `!lesson` **A scope argument that disqualifies BLOCKING equally disqualifies ASSERTING.** I
  rejected refusing-on-the-gate because a cwd-rooted ledger governs one engagement while campaigns
  are DB rows, so it could wrongly refuse a different campaign — then disclosed off that same
  ledger and wrote "disclosure has no wrong-refusal mode". True and irrelevant: it has a
  wrong-*assertion* mode in both polarities, and the harness fired it (an unrelated campaign got a
  governance verdict computed from a third party's ledger). If a record is too wrongly-scoped to
  refuse on, it is too wrongly-scoped to make claims from. bridge-candidate
- `!lesson` **Green tests proved nothing, in two ways a revert-proof cannot catch.** (a) My tests
  `monkeypatch.chdir`'d into a synthetic engagement root so the ledger resolved — production never
  chdirs and the Atlas stick wipes that folder every update, so the shipped feature returned `None`
  always. *The suite manufactured the one precondition production never satisfies.* (b) I "pinned"
  non-blocking with a 600-char source grep for `raise`; measured afterwards, the first `raise` sat
  at offset **1602** — a total reversal to blocking passed every assertion. Run the feature once in
  a production-shaped environment, and print the actual offset of whatever a windowed grep claims
  to exclude. bridge-candidate
- `!lesson` **Adjudicate refuters against the code — accepting a criticism that doesn't hold is
  its own failure.** Refuters 2 and 3 contradicted each other, and I had already published #2's
  version as a confirmed error of mine in the PR record; #3 was right. The distinction was scope:
  my literal claim ("no `--override-gate` on this surface") was true, the stronger clause I built
  on it ("no recourse at all") was false. Under adversarial pressure the pull is to over-confess.
  Verify *which sentence* fails before conceding, and post a correction if you already did. Related
  trap from the same session: I argued at length from a guard test I had already noted was not on
  my base — grep returned exactly one hit, my own docstring. bridge-candidate
- `!lesson` **Preserve another session's uncommitted work with `git stash create` + `update-ref`,
  never by branching it.** The task cited a fix that existed only as unstaged edits in the shared
  main checkout — one `git checkout --` from gone. `stash create` builds the commit object without
  stashing (nothing for them to `pop`, no branch switch), and `update-ref refs/preserved/<slug>`
  makes it GC-proof with their working tree untouched. Captures tracked files only — report the
  untracked ones you did not capture. Don't PR their work as yours. bridge-candidate

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
  shadow-validated NOT READY on the [HISTORY-REDACTED] snapshot). 8 commits, whole suite green. *(Honest slip: dated the new planning
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
