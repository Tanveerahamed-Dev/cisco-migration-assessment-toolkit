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

`6822242` deleted references to a `pending_approvals()` API that does not exist. #439 still carries
the pre-correction text. But #439 ALSO carries the real feature. You must watch both, because a
resolution that scores perfectly on the first can have destroyed the second:

```bash
grep -c 'pending_approvals' cisco_toolkit/gate_state.py   # prose correction
grep -c 'GateVerdict'       cisco_toolkit/gate_state.py   # #439's feature
```

| `pending_approvals` | Meaning |
|---|---|
| **1** | correct — only #448's corrected reference |
| **6** | the stale copy came back (naive keep-both) |
| **0** | you dropped #448's fix entirely |

| `GateVerdict` | Meaning |
|---|---|
| **>0** (13 in the replay) | #439's feature is present |
| **0** after #439 | **you deleted the whole PR** — this is what a file-level `--ours/--theirs` does |

Baseline: `main` today has `pending_approvals=0`, `GateVerdict=0`. #448 adds the single corrected
mention (→1). #439 adds the feature (→13). **Before #439, `GateVerdict=0` is expected and fine.**

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
grep -c 'pending_approvals' cisco_toolkit/gate_state.py     # expect 0 until #448, then 1

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
* grep → **must now read 1**. If it reads 0 you discarded #448's contribution — redo this step.

### 5. PR #439 — `claude/amazing-bardeen-5c7e30`  ← the landmine, and the only genuinely manual step
Conflicts: `cisco_toolkit/gate_state.py` (**12 hunks**), `COLLECT_PARSE_V3_23_0.py`, `docs/ssot.md`,
`portable/README-FIELD.txt`, `tests/test_gate_state.py`, `webapp/backend/ingest.py`,
`webapp/backend/serve.py`

> **DO NOT use `git checkout --ours/--theirs` on `cisco_toolkit/gate_state.py`.** A file-level flag
> takes the whole file. #439 rewrites that file by **+623/−31** — it adds the `GateVerdict`
> dataclass, `STATUSES` / `UNEVALUATED` / `ENGAGEMENT_KEY`, and changes `enforce()` to return a
> verdict object instead of a bare `bool`. Taking the file wholesale **silently deletes the entire
> PR's feature** while still leaving `pending_approvals` reading a healthy `1`. Measured: file-level
> `--ours` → `pending_approvals=1` (looks right) but `GateVerdict=0` (**feature gone**).

Resolve `cisco_toolkit/gate_state.py` **hunk by hunk, in an editor**. The 12 hunks are a mix:

* **Prose/docstring hunks** — take the side that says *"be listed in the guard's documented
  exemptions"* and drop the side that reintroduces the `pending_approvals()` list. That list is the
  stale pre-`6822242` text; `6822242` deleted it because the API does not exist.
* **Code hunks** (`GateVerdict`, `STATUSES`, the `enforce()` signature change, the new imports) —
  **keep #439's code**. That is the feature this PR exists to deliver, and it is what unblocks the
  open `deliverables.py` item.

Everything else in this PR — keep BOTH.

**Verify with BOTH metrics — either alone is misleading:**

```bash
grep -c 'pending_approvals' cisco_toolkit/gate_state.py   # want 1  (6 = stale copy returned)
grep -c 'GateVerdict'       cisco_toolkit/gate_state.py   # want >0 (0 = you deleted the feature)
python -c "import ast; ast.parse(open('cisco_toolkit/gate_state.py',encoding='utf-8').read()); print('compiles')"
```

---

## Phase 6 — final verification on main

```bash
git checkout main && git pull
grep -c 'pending_approvals' cisco_toolkit/gate_state.py            # 1
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
