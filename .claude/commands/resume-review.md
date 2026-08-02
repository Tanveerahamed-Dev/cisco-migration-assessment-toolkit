---
description: Resume the 2026-07-30 whole-repository hardening checkpoint without losing or overstating prior work.
argument-hint: [optional phase or lane]
---
Resume the active whole-repository review in the CURRENT main checkout. This is
a continuation, not a new review and not permission to normalize the dirty
tree.

Before any edit or test:

1. Read `CLAUDE.md` and
   `docs/review-hardening-handoff-2026-07-30.md` completely. Do not rely on a
   summary or a partial read.
2. Run the read-only checkpoint verifier:

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .claude/scripts/verify-review-handoff.ps1
   ```

3. If it reports drift, stop and explain the exact mismatch. Do not restore,
   delete, regenerate, stage, or otherwise “repair” the tree automatically.
4. Re-run the handoff’s read-only start protocol and inspect the complete live
   diff before changing a file.
5. Confirm that Python 3.12 is available. If it is still absent, report that
   environment blocker before attempting Python verification.

Preserve every existing modification, deletion, untracked source file, ignored
backup, recovery archive, and `.pytest_tmp_registry_*` directory. Do not stage,
commit, push, reset, revert, clean, delete, overwrite, build final archives,
rewrite history, or deploy without the user authorization required by the
handoff. Never run a bare `cisco-assess`; verification is offline and
fixture-driven.

Continue with the first incomplete item in the handoff’s ordered plan unless
`$ARGUMENTS` names a narrower lane. The default order is:

1. restore/confirm Python 3.12;
2. repair the stale `_main_checkout_root` test import without restoring private
   paths;
3. implement the scoped mixed-port-authority consumer contract;
4. finish and independently review the web fail-closed lane;
5. independently review packaging/privacy/release;
6. run repository-wide verification;
7. ask before staging/commit;
8. build immutable distributions;
9. finalize and deploy the master reference.

Keep “implemented,” “focused tests passed,” “independently verified,” and
“repository-wide green” as distinct states. Update the handoff verification
ledger after each completed lane so a later session can resume again without
reconstructing chat history.

