# #445 ↔ #439 reconciliation — the 7-hunk `enforce()` collision

> ## STATUS 25-Jul-2026 — CLOSED. All five merged: #448, #441, #444, #439, #445 (main `a3f921b`).
> ## Option **A** was taken. This note is kept as the RECORD of why, not as open work.
>
> Post-merge main verifies the outcome: `GateVerdict` 18, `_VERDICTS` 5, `VERDICTS` tuple **0**
> (retired), `UNEVALUATED` still carries both ownership statuses, `if False:` 0.
>
> **What it cost to land, all of it found by running rather than reading** — three defects in the
> reconciliation itself, each caught by #445's own tests: sealing absolute `store`/`detail` broke
> `chain_root` determinism; the engine's end-of-run summary filtered `verdict.startswith("refused")`,
> which **no** status in `STATUSES` satisfies, so every withheld deliverable would have silently
> vanished from the operator's last line; and a test dict keyed by verdict name collapsed three
> scenarios into one. An independent refuter then found a fourth — the `missing` nullable was
> **unpinned** for the two ownership statuses #439 added, so dropping them from `UNEVALUATED` left the
> ENTIRE gate suite green while a run refused because the ledger belongs to another client sealed as
> evaluated-with-nothing-missing. Pinned, and the pin was proved to fail under that mutation.
>
> **Process failure worth keeping:** the refuter was pointed at the same worktree the merge was being
> committed from, so a `git add -A` captured its live `if False: gate_reset_verdicts()` into a pushed
> commit — which would have meant run 2's manifest sealing run 1's verdicts. Rebuilt from the verified
> tree before merge. The mutation survived because the only guard on that property is a source grep,
> which stays green against exactly that edit.
>
> ---
>
> ### The conflict this note existed to resolve (retained for the reasoning)
>
> Ten of #445's 18 tests failed against the chokepoint — a real API conflict, not a merge error:
>
> | | #445 | #439 (now on main) |
> |---|---|---|
> | vocabulary | `VERDICTS` — flat: `approved` / `refused` / `refused_no_reason` / `refused_unreadable` / `overridden` / `ungated` | `STATUSES` — `bad_root` / `ungated` / `unreadable` / `ownership_mismatch` / `ownership_unbound` / `clear` / `pending`, **plus** `overridden` / `proceed` / `recorded` flags |
> | how it is guarded | `test_VERDICTS_lists_every_value_record_can_emit` STATICALLY SCANS the source for `_record(g, "<literal>")` and asserts the literals equal `VERDICTS` | `STATUSES` is pinned as the ONE vocabulary shared by `enforce` and `pending_approvals` |
>
> Three things collide:
> 1. **A chokepoint defeats the static scan by construction.** `_emit` passes `v.status` — a
>    variable — so the literal scan finds zero verdicts (`only-in-code=[]`). The guarantee doesn't
>    vanish, it MOVES: the vocabulary is now enforced by `STATUSES` + #439's own test rather than by
>    grepping literals. But #445's guard cannot express that.
> 2. **The vocabularies are not 1:1.** `refused`, `refused_no_reason` and `overridden` all map to
>    `pending` (distinguished by `overridden` / `detail`), so #445's
>    `test_every_enforce_outcome_records_a_verdict` — which keys a dict by verdict name and expects
>    6 distinct keys — collapses to 3 and cannot be fixed by renaming.
> 3. **#439 argues Law 1 against keeping both**: *"a second enum for the same situations is a copy
>    that drifts, and the two surfaces would then disagree about the same ledger."* #445's author
>    saw this coming — that test's docstring names **"PR #439's two new refusal arms"** explicitly.
>
> ### The Law-2 hazard this raised, and how it was handled
> Landing it meant rewriting the ~10 tests that are the ONLY independent check on this very merge —
> the same agent authoring both the reconciliation and its verification is proposer == verifier on a
> security control. That was not hypothetical: this task had already produced three cases where a
> metric the agent controlled hid a real defect (a file-level `--ours` deleting a +623-line feature
> while `GateVerdict` read 0; keep-both stacking a dead `--reuse-out` branch; a `list(...) or None`
> that would have inverted evaluated-clean into never-evaluated). Resolution: the rewritten tests
> were handed to an **independent refuter** to break by fault injection rather than review. It killed
> 34 of 37 mutations, and the three survivors became the fixes listed at the top.
>
> ### The decision that was taken (both were defensible; **A** was chosen)
> * **A — STATUSES wins (CHOSEN; follows Law 1).** Retire `VERDICTS`; `_emit` keeps recording
>   `v.status`. Rewrite `test_every_enforce_outcome_records_a_verdict` to key on
>   `(status, overridden)` rather than a flat name, and replace
>   `test_VERDICTS_lists_every_value_record_can_emit` with an assertion that every recorded status
>   is in `STATUSES` (stronger than the literal scan, and it survives refactors).
> * **B — keep #445's flat vocabulary.** Drop the chokepoint, restore per-arm
>   `_record(g, "<literal>")` calls beside each `GateVerdict` return, and extend `VERDICTS` with
>   `bad_root` / `ownership_mismatch` / `ownership_unbound`. Keeps #445's tests nearly intact, at
>   the cost of two enums that can drift — exactly what #439 warns about.

**Status:** CLOSED — all five merged (main `a3f921b`, 25-Jul-2026). Retained as the record of the
design decision and of the traps measured on this swarm; the recipe below is reusable the next time
two PRs implement one feature two ways. Session retro: `docs/log.md`, 2026-07-25.

## What collides

Both PRs implement the SAME goal — *"every verdict is audited, not just the override"* — by
different mechanisms, and both touch the same 6-8 exit points inside `gate_state.enforce()`.

| | mechanism | consumer |
|---|---|---|
| **#445** | module-level `_VERDICTS: List[dict]` + `_record(...)` at each disposition; `verdicts()` returns a deepcopy; a reset clears it | `COLLECT_PARSE_V3_23_0.build_run_manifest` seals it as `{"stage": "gate", "verdicts": …}` in the hash chain |
| **#439** | `enforce()` returns a rich frozen `GateVerdict` instead of a bare `bool` | the CALLER, so no downstream code re-derives the decision |

They are **complementary, not competing**: #445 is a cross-call ledger for the sealed manifest,
#439 is a per-call return contract. Keep BOTH.

## The decision: one chokepoint, not six hand-merged pairs

#439 already constructs a `GateVerdict` at every exit, and that object carries every field
`_record()` needs (`generator`, `status`, `missing`, `overridden`, `store`, `detail`). So do not
merge the two sets of call sites pairwise — route the recording THROUGH the verdict:

```python
def _emit(v: GateVerdict) -> GateVerdict:
    """Single exit for enforce(): seal the disposition into the run-manifest ledger (#445) and
    hand the caller the verdict (#439). One chokepoint means the sealed row and the returned
    verdict can never disagree — which is the invariant
    test_enforce_and_pending_approvals_share_one_status_vocabulary exists to protect.

    `missing` is NULLABLE ON PURPOSE (#445): None = the approvals were NEVER EVALUATED, [] =
    evaluated and nothing was missing. #439 encodes the same distinction as a status set, so map
    through THAT — never `list(v.missing) or None`, which collapses [] to None and reports a
    clean evaluated run as never-checked."""
    _record(v.generator, v.status,
            None if v.status in UNEVALUATED else list(v.missing),
            overridden=v.overridden, store=v.store, detail=v.detail)
    return v
```

> **⚠ The `missing` mapping is the one place this reconciliation can silently corrupt the audit.**
> An earlier draft of this note used `list(v.missing) or None`. That is WRONG: `[]` is falsy, so an
> *evaluated, nothing-missing* run would seal as `None` = *never evaluated*. #445's own `_record`
> docstring exists to prevent exactly that confusion ("so that counting missing approvals across
> rows cannot silently score a never-checked run as a clean zero"). The two PRs encode the SAME
> semantic in different shapes — #445 as a nullable, #439 as
> `UNEVALUATED = ("bad_root", "ungated", "unreadable", "ownership_mismatch", "ownership_unbound")`
> — so the status set is the correct, lossless bridge. That the two designs agree on this
> distinction is the strongest evidence they should both survive the merge.

Then every `return GateVerdict(...)` in `enforce()` becomes `return _emit(GateVerdict(...))`.

**Why this is better than either PR alone.** #439's status vocabulary is strictly richer than the
verdict names #445 could record, because #448/#439 added statuses that did not exist when #445 was
written:

| #445 records | #439 `status` |
|---|---|
| `refused_unreadable` | `unreadable` |
| `ungated` | `ungated` |
| `approved` | `clear` |
| `overridden` | `pending` + `overridden=True` |
| `refused_no_reason` / `refused` | `pending` + `proceed=False` |
| *(not recordable)* | **`bad_root`** |
| *(not recordable)* | **`ownership_mismatch`** / **`ownership_unbound`** |

So the sealed manifest ends up recording MORE dispositions than #445 achieves standalone — a
mis-set `--gate-root` and an ownership mismatch become auditable, which is exactly the
"unevaluated ≠ healthy" property this control exists for.

## Recipe

1. `git checkout claude/nervous-kalam-6c935e && git merge origin/main` (after #439 lands).
2. In `cisco_toolkit/gate_state.py`: keep #439's `GateVerdict` returns, keep #445's
   `_VERDICTS`/`_record`/`verdicts()`/reset, add `_emit()` above `enforce()`, and wrap each return.
   Do **not** keep #445's bare `_record(...)` statements as separate lines — that double-records.
3. Keep #445's `COLLECT_PARSE_V3_23_0` sealing call and its reset call unchanged.
4. Keep #445's **root `conftest.py`** autouse fixture as-is. It resets `_VERDICTS` between tests
   (and undoes the engine's import-time logging globals). Without it, `enforce()` rows leak into
   every later test in the session — and it must stay at the REPO ROOT, because `pytest.ini` sets
   `testpaths = tests webapp/tests`, so a `tests/conftest.py` would cover only half the gate.
5. `docs/log.md` / `docs/ssot.md`: keep-both / the drafted run-provenance row.

## Verify (all four must hold)

```bash
grep -c 'GateVerdict'      cisco_toolkit/gate_state.py   # >0  — #439's feature survives
grep -c '_VERDICTS'        cisco_toolkit/gate_state.py   # >0  — #445's ledger survives
python -c "import ast;g=ast.parse(open('cisco_toolkit/gate_state.py',encoding='utf-8').read());\
n=[f.name for f in g.body if isinstance(f,ast.FunctionDef)];\
print('dupes:', {x for x in n if n.count(x)>1} or 'none')"          # none — no duplicate defs
python -m pytest -q -p no:cacheprovider; echo EXIT=$?                # 0 — judge by EXIT CODE only
```

**One-record-per-call check** (the double-record trap): every `enforce()` exit must record exactly
once. After wrapping, assert no bare `_record(` remains inside `enforce`:

```bash
python - <<'PY'
import ast
g=ast.parse(open('cisco_toolkit/gate_state.py',encoding='utf-8').read())
enf=[f for f in g.body if isinstance(f,ast.FunctionDef) and f.name=='enforce'][0]
bare=[ast.unparse(n) for n in ast.walk(enf)
      if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
      and getattr(n.value.func,'id','')=='_record']
print('bare _record calls left in enforce():', bare or 'none (correct)')
PY
```

## Traps already measured on this swarm — do not re-discover them

* **Never** `git checkout --ours/--theirs` on `cisco_toolkit/gate_state.py` — it takes the WHOLE
  file and silently deletes the other PR's feature (measured: `GateVerdict` → 0 while the watched
  metric still read healthy).
* **Keep-both on control flow compiles clean and can be silently dead.** #444's `serve.py` ended up
  with two `if args.redact_folder` blocks; the first (`is not None`) made the second unreachable and
  the dead one was the only path forwarding `reuse_out` (fixed in `bc5f792`). After any keep-both on
  an `if`/dispatch region, verify the flag is REACHED, not merely present.
* `pending_approvals` count is **not** a staleness metric — #439 DEFINES that API (1 def + 13 test
  refs). ~5 occurrences is correct; driving it to 1 deletes a working feature.
