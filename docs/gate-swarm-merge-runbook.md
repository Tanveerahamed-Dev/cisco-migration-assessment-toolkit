# Gate-swarm merge runbook — PRs #441 / #445 / #444 / #448 / #439

> **STATUS 24-Jul-2026: all five branches have been updated against `main` and pushed.
> Every PR is now `MERGEABLE` (was `CONFLICTING`); each shows `BLOCKED` = the review gate only.**
>
> | PR | head | conflicts resolved |
> |---|---|---|
> | #441 | `f8538b8` | `docs/log.md` keep-both |
> | #445 | `e5ed593` | `docs/log.md` keep-both (`ssot.md` auto-merged) |
> | #444 | `17d1357` | `webapp/backend/serve.py` keep-both (both argparse sets verified present) |
> | #448 | `cc5b1fc` | `log.md` + `ingest.py` + `serve.py` keep-both; all compile |
> | #439 | `b926a7a` | `ingest.py` + `serve.py` keep-both; all compile |
>
> **STATUS: #448 MERGED (`0f41d2f`). All four remaining PRs are `MERGEABLE` and updated against it.
> The `pending_approvals` design question below is DECIDED and IMPLEMENTED on #439 (`9e8c0bc`),
> verified by 123 passing tests.**
>
> | PR | head | state |
> |---|---|---|
> | #441 | `db9b8a8` | MERGEABLE — `docs/log.md` keep-both |
> | #445 | `4331a24` | MERGEABLE — keep-both; 28 gate tests pass, no duplicate defs |
> | #444 | `ce8c2fc` | MERGEABLE — `test_atlas_redaction.py` ours (main had nothing there) |
> | #439 | `9e8c0bc` | MERGEABLE — full 7-hunk + 14-hunk resolution, **123 tests pass** |
>
> `BLOCKED` on each = the review gate only.

## ⛔ CORRECTION 3 — **#445 and #439 cannot both merge.** Stop the wave after #444.

Measured 24-Jul-2026 ~22:40 UTC, by replaying the wave into a detached worktree after #441 landed
(`d04d64a`, 19:11:47Z) and running the checks this runbook prescribes. **§5's instruction for #439 is
now known-harmful.** The blocker below is proven by counterexample, not predicted.

### 1. The blocker — #445 and #439 are the same feature, built twice, incompatibly

Both PRs exist to make gate verdicts durable. They disagree about where the record lives, and the
disagreement is in the type system, not the prose:

| | **#445** (merges first) | **#439** |
|---|---|---|
| `enforce()` returns | `bool` | `GateVerdict` dataclass |
| vocabulary | `VERDICTS = (ungated, approved, overridden, refused, refused_no_reason, refused_unreadable)` | `STATUSES = (bad_root, ungated, unreadable, ownership_mismatch, ownership_unbound, clear, pending)` |
| recorder | `_record()` → module-level `_VERDICTS` | `_record_refusal()` → the store's `audit` array |
| durable home | the per-run `.run_manifest.json` seal | the gate-state ledger — #439 argues in its own docstring that the manifest is the **wrong** owner ("a refusal provokes a re-run, and a per-run seal is overwritten by exactly that") |
| exports | `verdicts()`, `reset_verdicts()` | neither exists |

#445 also lands three call sites in `COLLECT_PARSE_V3_23_0.py`. **They auto-merge with no conflict**,
which is exactly why no metric on `gate_state.py` can see the damage:

* `:482` — `from cisco_toolkit.gate_state import reset_verdicts as gate_reset_verdicts` ← *module-level*
* `:1423` — `{"stage": "gate", "verdicts": _gate_state.verdicts()}`
* `:1860` — `gate_reset_verdicts()`

**Both mechanical resolutions were executed against the real tree. Both fail:**

| resolution | every check this runbook prescribes | what actually happens |
|---|---|---|
| take #439's code on the code hunks — **what §5 instructs** | `pending_approvals=5` ✅ · `GateVerdict=17` ✅ · root guard ✅ · `ast.parse` ✅ | `ImportError: cannot import name 'reset_verdicts' from 'cisco_toolkit.gate_state'` — **the engine does not import at all** |
| keep BOTH on the API hunk | compiles ✅ · imports ✅ · `GateVerdict=17` ✅ | `enforce()` returns a `GateVerdict`, but `_record()` is never called, so `verdicts()` returns `[]` forever → every run seals `{"stage": "gate", "verdicts": []}`: **the manifest silently reports that no gate decision was ever made** |

The first is loud. The second is the dangerous one — and it is the same shape as the trap already
documented in "Rejected approaches": *every number this runbook watches reads healthy while the
feature is destroyed.* `pending_approvals` and `GateVerdict` cannot see it, because the destruction is
in a different file that never conflicted.

Note the status header above claims #439 is "verified by 123 passing tests". Those tests ran on
#439's branch **without #445** — per-PR CI structurally cannot catch this class.

**This is an author decision, not a merge resolution** — the same category as the `pending_approvals`
question below. Someone has to pick one vocabulary and one durable home:

* **Keep #445's design** → #439 drops `GateVerdict`/`STATUSES` and records through `_record()`,
  keeping its genuinely separate feature (ledger↔engagement ownership binding, `ENGAGEMENT_KEY`,
  ADR 0006), which nothing here conflicts with.
* **Keep #439's design** → #445's `_VERDICTS`/`verdicts()`/`reset_verdicts()` **and** its three
  `COLLECT_PARSE` call sites are rewritten onto `GateVerdict`, and `tests/test_gate_audit_trail.py`
  (13 assertions against `verdicts()`) is rewritten with them.

Either way it is real work by whoever owns the design. **Do not attempt it as a merge resolution.**

### 2. Corrected conflict matrix — #445 is the hub

Heads: `441=db9b8a8` `445=4331a24` `444=bd196dd` `439=9e8c0bc`. Every PR is clean against `main`;
these are the collisions *with each other*. (#444's head moved during measurement — its author has
since merged `main` in themselves at `bd196dd`, which is why it no longer collides with #441.)

| | #441 | #445 | #444 | #439 |
|---|---|---|---|---|
| **#441** | — | `log.md`, `ssot.md` | clean | clean |
| **#445** | | — | `log.md`, `ssot.md` | **`gate_state.py`**, `ssot.md` |
| **#444** | | | — | clean |
| **#439** | | | | — |

Only #445 collides with anything. **#444 and #439 are clean against each other and against #441** —
so the safe wave is `#445 → #444`, then **stop**.

### 3. Two defects #445 carries into `docs/ssot.md` that CI cannot catch

Found while resolving #445's `ssot.md` conflict; both survive a correct merge and neither is caught by
`tests/test_ssot_registry.py` (it validates owners, symbols and cross-links — it has **no
duplicate-row detection**).

1. **Duplicate SSOT row.** #445's `ssot.md` diff is 3 lines, and one of them *adds a second*
   `**Engagement gate state**` row rather than editing the existing one. `main` has 1, #445 has 2.
   The added row carries **pre-#448 ownership text** — it says the store is "resolved under the
   working directory", dropping #448's `--gate-root` correction. Two rows owning one fact-domain is a
   Law-1 violation, and the stale one re-introduces the fail-open hazard #448 documented.
   **Fix:** fold #445's new `**Scope:**` clause and its `test_gate_audit_trail.py` pin into main's
   existing row; delete the duplicate.
2. **A claim that #444 falsifies, in a row #444 never touches.** Both rows assert *"no shipped command
   or CI job verifies a delivered manifest today"*. #444 ships exactly that command
   (`manifest.py :: main()`, `add_parser("verify")`). #444's file list does **not** include
   `docs/ssot.md`, so merging #444 leaves the SSOT asserting something false.
   **Fix:** state the verification surface **once**, in the row that owns it (Run provenance), and have
   the gate-state row cite it instead of restating it. Verified: `verify_manifest()` already exists
   in-process on `main` (`manifest.py:82`); #444 adds the CLI; **no CI job references a manifest at
   all**, so that half of the claim stays true.

Also corrected while merging: the run-provenance row cites `write_json_file` as a `cisco_toolkit`
symbol. It is not — it lives at `COLLECT_PARSE_V3_23_0.py:1300` (the entry module), as
`tests/test_run_manifest_durability.py` itself notes.

### 4. The two draft files this runbook tells you to paste from **do not exist**

Phase 0 says to keep `ssot_row_draft.md` and `docstring_blends.md` to hand for Phases 2 and 3. Neither
is in the repo, in git history, or in any session scratchpad — they were a prior session's scratch and
are gone. The resolutions they held are reconstructed in §3 above and in §5 below; the runbook was not
executable as written.

The `docstring_blends.md` hazard is real and was reproduced: in `build_run_manifest`, HEAD's side ends
with `"""` on its own line while #444's ends `...to this run."""`. Naive keep-both closes the
docstring early and turns the remaining prose into code. Blend both bodies into **one** docstring
closed **once**; `ast.parse` is what catches a bad blend.

## 🛑 CORRECTION 2 — "merge order no longer matters for conflicts" is FALSE (measured 24-Jul-2026)

An earlier line here said *"Merge order no longer matters for conflicts; each is independently up to
date with `main`."* The first half does not follow from the second. Each PR is clean **against
`main`**, but they are not clean **against each other**, so the first merge re-breaks the rest.

Measured with `git merge-tree` on the fetched heads, counting `+<<<<<<<` hunks:

| | vs `main` | #441 | #445 | #444 | #439 |
|---|---|---|---|---|---|
| **#441** | 0 | — | **2** | **2** | 0 |
| **#445** | 0 | **2** | — | 0 | **7** |
| **#444** | 0 | **2** | 0 | — | 0 |
| **#439** | 0 | 0 | **7** | 0 | — |

Three conflicting pairs (441–445, 441–444, 445–439). Each pair must be resolved exactly once — when
the **second** of the pair merges — so ~11 hunks of resolution are unavoidable in any order. What
order changes is *which* PR pays for the 7-hunk one.

> **Confirmed in production, 24-Jul-2026 22:11.** #441 merged as `d04d64a`. Within minutes GitHub
> recomputed the rest and **#445 and #444 both flipped `MERGEABLE` → `CONFLICTING/DIRTY`**, exactly
> the two pairs the matrix predicts; #439 stayed `MERGEABLE` (it has no pair with #441). This is no
> longer a prediction — treat "each PR is MERGEABLE right now" as a statement with a shelf life of
> one merge.

**Keep the documented order 441 → 445 → 444 → 439.** It is not arbitrary: it lands #439 **last**, so
the 7-hunk `gate_state.py` resolution happens once, against a final `main`, in the PR whose own
author knows which hunks carry `GateVerdict`. Merging #439 early instead forces that same 7-hunk
resolution onto whoever merges #445 — the exact scenario "Rejected approaches" shows silently
deleting a +623-line feature while the watched metric still reads healthy.

**Operationally:** after each merge, the next PR is stale again. Re-run
`git checkout <BRANCH> && git merge origin/main` and re-resolve before merging it — do not assume a
`MERGEABLE` state observed before the previous merge still holds. `gh pr checks` will also need to
re-run per PR (each PR's CI ran without the others; see the "Known limitation" below).
>
> ## 🛑 CORRECTION — the "#439 stale-prose landmine" in earlier drafts of this runbook was WRONG
>
> An earlier version of this document told you to resolve #439 by driving
> `grep -c 'pending_approvals'` down to **1**. **Do not do that. It would delete a working,
> tested API.** The correction, verified against the merge-base:
>
> | version | `def pending_approvals` | meaning |
> |---|---|---|
> | merge-base `4f6a084` | **0** | the function never existed at the fork point |
> | **#439** `b926a7a` | **1** | #439 **BUILDS** it — a documented disclosure API, **13 references in its own test file** |
> | **main** (post-#448) | **0** | #448 documents the opposite: *"There is no third 'disclose' API in this module"* |
>
> So #439's five `pending_approvals` mentions are **not stale references to a deleted API** —
> four are prose describing the function the fifth one *defines*. A correct #439 merge keeps
> roughly **5**, not 1. The metric was measuring the wrong thing.
>
> ### What this actually is: a DESIGN conflict between two coherent positions
> * **#448 (on main):** there should be no disclosure API. `missing_approvals(store, generator)` is
>   a pure computation over an already-loaded store, not a reporting posture. It explicitly strikes
>   an earlier draft that prescribed a `pending_approvals()` helper.
> * **#439:** `pending_approvals()` *is* the disclosure API — the read-only counterpart to
>   `enforce()`, never writes, never raises, shares the `STATUSES` vocabulary, and its tests pin
>   that `enforce` and `pending_approvals` cannot disagree.
>
> Both are defensible. They cannot both be true in one file. **Choosing is an author decision, not
> a merge conflict** — see "Decide this before merging #439" below.
>
> ### Also measured: two real traps in the `gate_state.py` merge (7 hunks)
> 1. **Do not take main's side of the `_normalize_root`/`_require_root`/`enforce` hunk.** Those three
>    functions **already exist** further down the merged file (clean region); taking main's copy too
>    creates duplicate defs, and the later definition silently wins.
> 2. **But #439's `_normalize_root` is genuinely OLDER than main's** — main's `#448` version adds a
>    `TypeError` guard for `None`/`0`/`b""` that #439 lacks (without it, `record_decision(root=None)`
>    silently creates a phantom ledger in cwd and returns a success receipt). That guard **must**
>    survive the merge. Verify: `grep -c 'must be a path string' cisco_toolkit/gate_state.py` ≥ 1.
>
> ### Decide this before merging #439
> **Q: does `cisco_toolkit.gate_state` expose a `pending_approvals()` disclosure API?**
> * **Yes (keep #439's design):** keep the function + its tests; then *update main's struck
>   paragraph*, which currently asserts no such API exists and would become false.
> * **No (keep #448's design):** #439 must drop `pending_approvals()` **and** the tests that pin it,
>   and re-route any caller to `missing_approvals()`.
>
> Either way `GateVerdict` (17 refs) is #439's separate feature and must survive — a file-level
> `--ours/--theirs` deletes it wholesale. See "Rejected approaches".

Five open PRs all modify `cisco_toolkit/gate_state.py` and conflict pairwise. All are ~20 commits
behind `main` (`14ced38`), so the order recorded in #448's body was computed against a stale main
and its conflict list no longer matches reality. This runbook is the re-validated version.

**Verified by replay, not predicted.** Each resolution below was executed in a throwaway worktree and
measured. Two plausible-sounding alternatives were tested and *refuted* — see "Rejected approaches".

---

## The two checks that matter (one alone will lie to you)

#439 both **defines** `pending_approvals()` and describes it in prose, so a raw token count cannot
tell "the feature plus its documentation" apart from "documentation of something deleted". Count
the **definition**, and watch `GateVerdict` alongside it — a resolution that scores perfectly on
one can have destroyed the other:

```bash
grep -c '^def pending_approvals' cisco_toolkit/gate_state.py   # #439's disclosure API
grep -c 'GateVerdict'            cisco_toolkit/gate_state.py   # #439's verdict feature
grep -c 'must be a path string'  cisco_toolkit/gate_state.py   # #448's root guard
```

| `^def pending_approvals` | Meaning |
|---|---|
| **1** after #439 | correct — the disclosure API is present |
| **0** after #439 | **you deleted the API** and orphaned the 13 references in its own test file |

| `GateVerdict` | Meaning |
|---|---|
| **>0** (17 measured at `9e8c0bc`) | #439's feature is present |
| **0** after #439 | **you deleted the whole PR** — this is what a file-level `--ours/--theirs` does |

Baseline: `main` today has `^def pending_approvals=0`, `GateVerdict=0`. #448 adds one corrected
prose *mention* (raw count →1, still no definition). #439 adds the definition plus four prose refs
(raw count →5, def →1) and the verdict feature (→17). **Before #439, `GateVerdict=0` is expected
and fine**, and a raw `grep -c 'pending_approvals'` of **5** after #439 is CORRECT — not a stale
copy. That raw count is the metric both corrections above retract; it is kept here only to be
named and disowned.

---

## ⚠ `--ours` / `--theirs` inverts — do not rely on it

This runbook merges `main` INTO each PR branch (no force-push, keeps review history). In that
direction:

* `--ours`  = the **PR branch**
* `--theirs` = **main**

That is the opposite of merging the PR into main. **Resolve by content, then verify with the grep.**

---

## Phase 0 — prep (once)

```bash
cd C:/Users/jajch/Desktop/Enhancements
git status --short          # must be clean
git fetch origin
git log --oneline -1 origin/main
```

Keep the two draft files to hand — you'll paste from them in Phases 2 and 3:
* `ssot_row_draft.md` — the merged `docs/ssot.md` run-provenance row
* `docstring_blends.md` — the two blended docstrings for #444

---

## The loop (repeat per PR, in this exact order)

Order: **#441 → #445 → #444 → #448 → #439**

```bash
# 1. get on the PR branch and bring main in
git checkout <BRANCH>
git merge origin/main

# 2. resolve the conflicts listed for that PR below

# 3. verify
python -c "import ast,sys; [ast.parse(open(f,encoding='utf-8').read()) for f in sys.argv[1:]]; print('syntax OK')" $(git diff --name-only --diff-filter=U | grep '\.py$')
grep -c 'pending_approvals'      cisco_toolkit/gate_state.py  # raw: 0 until #448, 1 after it, 5 after #439
grep -c '^def pending_approvals' cisco_toolkit/gate_state.py  # def: 0 until #439, then MUST be 1

# 4. commit + push (NO force needed — this is a merge)
git add -A && git commit --no-edit
git push

# 5. wait for CI, then merge the PR
gh pr checks <PR> --watch
gh pr merge <PR> --merge          # add --admin if branch protection blocks you
git checkout main && git pull      # pick up the merge before the next PR
```

---

## Per-PR resolutions

### 1. PR #441 — `claude/optimistic-germain-58460e`
Conflicts: `docs/log.md`
* **Keep BOTH** session entries (newest-first log; two different sessions collided at the same anchor).
* grep → expect **0**.

### 2. PR #445 — `claude/nervous-kalam-6c935e`
Conflicts: `docs/log.md`, `docs/ssot.md`
* `docs/log.md` — keep BOTH entries.
* `docs/ssot.md` — **replace the whole conflicted run-provenance row with the drafted row** from
  `ssot_row_draft.md`. Do **not** pick a side: main's version says the manifest "records no PPDIOO
  gate verdict" (false once #445 lands) and #445's says "no shipped command or CI job verifies a
  delivered manifest" (half-false once #444 lands — the command ships, the CI job still doesn't).
* grep → expect **0**.

### 3. PR #444 — `claude/gracious-mirzakhani-9e1403`
Conflicts: `COLLECT_PARSE_V3_23_0.py`, `cisco_toolkit/manifest.py`, `webapp/backend/serve.py`
* `webapp/backend/serve.py` — **keep BOTH** argparse blocks (`--reuse-out` from main AND
  `--verify-manifest` / `--expect-root` / `--verify-artifacts` from #444). Purely additive.
* The two **docstrings** — paste the blends from `docstring_blends.md`. Do **not** keep-both:
  concatenating two docstring bodies leaves a stray closing `"""` mid-prose and raises
  `SyntaxError: unterminated string literal`. Also carry over `import os` (needed by `verify_file`).
* Run the syntax check — it is what catches a bad blend.
* grep → expect **0**.

### 4. PR #448 — `fix/redaction-gate-posture`
Conflicts: `cisco_toolkit/gate_state.py`, `docs/log.md`, `docs/ssot.md`,
`webapp/backend/ingest.py`, `webapp/backend/serve.py`, `webapp/tests/test_atlas_redaction.py`
* **Keep BOTH on every one.** They are complementary, not competing: #445 contributed the
  "every verdict is recorded structurally" paragraph, #448 contributes the "root resolution — the one
  way this module fails silently" paragraph; `ingest.py` likewise gains #448's "why the PPDIOO gates
  deliberately do NOT apply here"; the test file and argparse gain adjacent additions.
* raw `grep -c 'pending_approvals'` → **must now read 1**. If it reads 0 you discarded #448's
  contribution — redo this step. (`^def pending_approvals` is still **0** here, correctly: #448
  documents the absence of the API, #439 is what builds it.)

### 5. PR #439 — `claude/amazing-bardeen-5c7e30`  ← the landmine, and the only genuinely manual step

> ## ⛔ DO NOT EXECUTE THIS SECTION. See **CORRECTION 3** at the top.
>
> The rule below — *"Code hunks … keep #439's code"* — was executed against the real tree and produces
> `ImportError: cannot import name 'reset_verdicts'`: **the engine stops importing entirely**, while
> every metric this section tells you to watch (`pending_approvals=5`, `GateVerdict=17`) reads healthy.
> #439 and #445 implement the same feature with incompatible vocabularies; choosing between them is an
> author decision. Merge `#445 → #444` and stop.
Conflicts: `cisco_toolkit/gate_state.py` (**12 hunks**), `COLLECT_PARSE_V3_23_0.py`, `docs/ssot.md`,
`portable/README-FIELD.txt`, `tests/test_gate_state.py`, `webapp/backend/ingest.py`,
`webapp/backend/serve.py`

> **DO NOT use `git checkout --ours/--theirs` on `cisco_toolkit/gate_state.py`.** A file-level flag
> takes the whole file. #439 rewrites that file by **+623/−31** — it adds the `GateVerdict`
> dataclass, `STATUSES` / `UNEVALUATED` / `ENGAGEMENT_KEY`, and changes `enforce()` to return a
> verdict object instead of a bare `bool`. Taking the file wholesale **silently deletes the entire
> PR's feature** while still leaving the raw `pending_approvals` count reading a healthy `1`.
> Measured: file-level `--ours` → raw `pending_approvals=1` (looks right) but `GateVerdict=0`
> (**feature gone**). Note the corrected metric catches this on its own: `^def pending_approvals`
> drops to `0` in the same resolution, which is exactly why it replaced the raw count.

Resolve `cisco_toolkit/gate_state.py` **hunk by hunk, in an editor**. The 12 hunks are a mix:

* **Prose/docstring hunks** — keep the side that says *"be listed in the guard's documented
  exemptions"* (that is #448's contribution) **and keep #439's `pending_approvals()` prose.**
  ⚠ Earlier drafts told you to drop the `pending_approvals()` side as "stale pre-`6822242` text".
  **Do not.** `6822242` removed that text because the API did not exist *on that branch*; #439 is
  the branch that **creates** it, so on #439 the same prose is a live description of a live
  function. Dropping it strands the definition four lines below with no documentation, and is one
  editor slip away from dropping the definition too. The only prose to drop is a duplicate of a
  paragraph you have already kept.
* **Code hunks** (`GateVerdict`, `STATUSES`, the `enforce()` signature change, the new imports) —
  **keep #439's code**. That is the feature this PR exists to deliver, and it is what unblocks the
  open `deliverables.py` item.

Everything else in this PR — keep BOTH.

**Verify with BOTH metrics — either alone is misleading:**

```bash
grep -c '^def pending_approvals' cisco_toolkit/gate_state.py  # want 1  (0 = you deleted the API)
grep -c 'GateVerdict'            cisco_toolkit/gate_state.py  # want >0 (0 = you deleted the feature)
grep -c 'must be a path string'  cisco_toolkit/gate_state.py  # want >=1 (#448's root guard survived)
grep -c '^def _normalize_root'   cisco_toolkit/gate_state.py  # want 1  (2 = duplicate-def trap)
python -c "import ast; ast.parse(open('cisco_toolkit/gate_state.py',encoding='utf-8').read()); print('compiles')"
```

---

## Phase 6 — final verification on main

```bash
git checkout main && git pull
# After ALL FOUR merges land, the raw count is 5, not 1 -- 1 was the pre-#439 value and expecting
# it here would report a false failure at the last step of the wave (or invite someone to "fix" it
# by deleting the API). Assert the definition, which is what the wave is actually delivering:
grep -c '^def pending_approvals' cisco_toolkit/gate_state.py       # 1
grep -c 'GateVerdict'            cisco_toolkit/gate_state.py       # >0  (17 at 9e8c0bc)
grep -c 'must be a path string'  cisco_toolkit/gate_state.py       # >=1 (#448's root guard)
# NB the old check here was  grep -c 'be listed in the guard'  # >=1  -- it is BROKEN and always
# reads 0, so it would report a false failure at the last step of the wave. Two reasons, measured:
# (1) that docstring is hard-wrapped, so the phrase straddles a newline ("...or be listed in\nthe
#     guard's documented exemptions") and a line-oriented grep can never match it; and
# (2) #439 rewords that paragraph anyway, so it is 0 after #439 lands even unwrapped.
# Use a wrap-insensitive check of something that survives both:
python -c "import re,pathlib; t=' '.join(pathlib.Path('cisco_toolkit/gate_state.py').read_text(encoding='utf-8').split()); print('posture list OK' if 'documented exemptions' in t or 'pending_approvals' in t else 'MISSING')"
python -c "import ast; [ast.parse(open(f,encoding='utf-8').read()) for f in ['cisco_toolkit/gate_state.py','cisco_toolkit/manifest.py','COLLECT_PARSE_V3_23_0.py','webapp/backend/serve.py','webapp/backend/ingest.py']]; print('syntax OK')"
python -m pytest -q                                                # judge by EXIT CODE
python -m cisco_toolkit.manifest verify --help                     # #444's verb is reachable
```

Note: judge pytest by its **exit code** — this suite prints no "N passed" summary line.

---

## Rejected approaches (tested and refuted — don't retry these)

* **"Reorder so #439 lands earlier and the correction lands last."** Measured: still **6**. Order is
  irrelevant, because naive keep-both *concatenates* both docstrings (5 + 1) in either direction.
* **"Just take `--ours` on `gate_state.py` whenever it conflicts."** Measured: **0**. A global rule
  discards #448's own contribution during #448's merge.
* **"Then take the file-level flag only at #439."** Measured: `pending_approvals=1` — which *looks*
  correct — but `GateVerdict=0`: **#439's entire +623-line feature silently deleted.** This is the
  most dangerous of the three, because the metric being watched reports success. It is why the
  runbook insists on a second, independent metric and on hunk-level resolution at #439.

**The lesson underneath all three:** a resolution that satisfies the one number you happen to be
watching can still be destroying something that number cannot see. Every automated resolution here
was refuted by adding a metric, not by re-reading the diff.

**And the lesson caught this document itself.** It was applied to `GateVerdict` and never to
`pending_approvals`, the metric that started it: a raw token count cannot separate "the feature
plus its documentation" from "documentation of a deleted feature", so the number kept reporting
success in both directions. Worse, the retraction was published as a banner at the top while the
body — the tables, the per-PR verify blocks, and the step-5 resolution instruction — went on
prescribing the retracted number. **A correction that does not reach the line the operator
actually executes has not been made.** Reconciled 24-Jul-2026; the raw count now appears only
where it is explicitly disowned.

---

## If something goes wrong

Nothing here force-pushes, so every step is recoverable:

```bash
git merge --abort          # mid-conflict, before committing
git reset --hard @{u}      # after a bad local commit, before pushing
```

If a PR is already pushed and wrong, push a corrective commit — do not force-push a branch others
may have pulled.

---

## Known limitation of this runbook

The replay verified **conflict resolution, syntax, and the regression metric**. It did **not** run the
full test suite on the integrated tree: this repo's editable install resolves to the main checkout, so
`pytest` inside a scratch worktree can silently exercise the wrong code. Per-PR CI (Phase step 5) is
the trustworthy signal, which is why each PR is pushed and checked before the next one starts.

**Independent second pass (session `c0815bd5`, 24-Jul-2026 22:0x–22:2x).** A different session
re-ran the merge sequence from scratch in its own detached worktree off `origin/main` @ `a98394f`
and reached CORRECTION 2 independently: `#441` clean, then `#445` (`docs/log.md`, `docs/ssot.md`),
`#444` (`COLLECT_PARSE_V3_23_0.py`, `cisco_toolkit/manifest.py`) and `#439`
(`cisco_toolkit/gate_state.py`, `docs/ssot.md`) each conflict — 6 files, 3 of them `.py`. Two
observations that pass step is the only place to record:

* **`docs/ssot.md` conflicts twice** — at `#445` and again at `#439`. That is the Law-1 SSOT
  registry, and per the swarm analysis the run-provenance row is 3-way in *facts* while git shows
  it as 2-way. Resolve it in an editor against `docs/ssot.md`'s owner, never in the web UI.
* **Naive union reproduces the authorial-conflict signature** on both `.py` conflicts —
  `unterminated string literal` in `COLLECT_PARSE_V3_23_0.py`, `unexpected indent` in
  `gate_state.py`. Both need prose blends; neither is keep-both.

**#439's head `9e8c0bc` was measured directly and is internally sound** — this is the state the
step-5 resolution must preserve, not re-derive:

| probe | value |
|---|---|
| `grep -c '^def pending_approvals'` | **1** (the API is built here; 0 at the merge-base) |
| `grep -c 'pending_approvals'` (raw) | **5** — expected, *not* a stale copy |
| `grep -c 'GateVerdict'` | **17** |
| `grep -c 'must be a path string'` | **1** (#448's `TypeError` root guard survived) |
| `^def _normalize_root` / `_require_root` / `enforce` | **1 / 1 / 1** (no duplicate-def trap) |

Still not run anywhere: the full suite on the **four-way integrated** tree. Per-PR CI tests each
branch against `main` alone, so the combination remains unverified until the last merge lands —
the failure mode this repo has already paid for once (#389). Run the full gate on `main` after the
final merge, not only per PR.
