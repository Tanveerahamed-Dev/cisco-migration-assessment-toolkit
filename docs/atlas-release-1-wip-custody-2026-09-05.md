# Atlas Release 1 protected-WIP custody ledger

Status: reconciled on 2026-09-05 against live GitHub `main`; this is an evidence record, not a future work queue.

## Custody identity

- Protected checkout: `%USERPROFILE%\Desktop\Enhancements` (read-only during this reconciliation;
  the user-specific home segment is intentionally omitted from public source).
- Base commit: `08f745ff7e12ff14ec84dee500b016292870aaa5`; tree `4bb6e150d40f49beb84c541cf9856a6f92262cd8`.
- Anchored WIP commit: `b2f466bb6ba2d2bb1e6c44ba06968a00b0aaf4b7`; tree `633892a3863a648de96760fedb640646d69f3c6a`.
- Reconciliation main: `b9cb2c3d27ed6652ad6f98b75fa99ba9d2ed7ab6`; tree `dba59899f759973ce28ab66139635b1aecb34241`.
- The 15 protected on-disk files match the anchored WIP tree byte-for-byte; `git diff desktop-root-wip --` is empty.
- The stored binary patch is exactly `git diff --binary --full-index base..wip`: 201,594 bytes, SHA-256 `ab1b8b49e234b49e3e7f9f08111a2086175214f9f5f461026f3575ebb93fca40`.
- Protected status at reconciliation: 15 unstaged tracked changes, zero staged files, zero untracked files. All 17 `refs/continuity/20260903/*` refs resolve.

No WIP commit was merged or cherry-picked. Eight paths changed on both sides and a blind low-level merge produces 30 conflict markers.

## Path-by-path disposition

| Protected path | Classification | Reviewed disposition |
|---|---|---|
| `.gitattributes` | obsolete | Do not port the merge driver for ignored/untracked `graphify-out/graph.json`. |
| `.graphifyignore` | unique product value | Port only the `.codex-worktrees/` corpus exclusion and its rationale. |
| `CLAUDE.md` | obsolete | Keep current Graphifyy 0.9.51 guard doctrine; do not restore the older 0.9.47/upstream-hook text or remove the incremental-edge residual. |
| `cisco_toolkit/d10_eval_set.py` | unique wording only | Current executable behavior is retained. The accurate atomic-JSON-writer wording may be reconciled separately; the incremental cross-file-edge residual remains. |
| `master-reference/build/projection/build.mjs` | unique product value, partial | Add controlled relations `cites`, `dynamic_import`, and `extends`; retain current projection v2 and incremental-edge disclosure. |
| `master-reference/compiler/graphify.py` | unique product value, partial | Add the same three controlled relations; retain current fail-closed metadata and residuals. |
| `master-reference/schema/atlas-records.schema.json` | unique product value | Add the same three graph-edge relation tokens. |
| `master-reference/schema/graphify-metadata.schema.json` | obsolete | Do not delete the still-applicable incremental-edge unresolved reason. |
| `master-reference/tests/compiler/test_compiler.py` | unique product value, partial | Exercise every controlled relation and require exact round-trip preservation. |
| `master-reference/tests/source/projection.test.mjs` | obsolete as a patch | Keep current projection-v2 coverage; add a current-tree relation-owner reconciliation test instead. |
| `tests/test_d10_eval_set.py` | obsolete as a patch | Keep the current explicitly named incremental-edge failure test referenced by doctrine. |
| `tests/test_graph_invariants.py` | already integrated and evolved | Keep current 0.9.51 receipts, relation counts, and provenance controls. |
| `tests/test_graph_report_verifier.py` | already integrated and evolved | Keep current membership, navigation, bounded-read, and hostile-input coverage. |
| `tests/test_shared_agent_context.py` | obsolete | Keep the tracked guarded-producer boundary; do not pin the unguarded upstream installer. |
| `tools/verify_graph_report.py` | already integrated and evolved | Keep the current 0.9.51 verifier and zero allowed report residuals. |

## Line-ending and validation boundary

The protected WIP copies of `CLAUDE.md`, `cisco_toolkit/d10_eval_set.py`, `tests/test_d10_eval_set.py`, and `tests/test_graph_invariants.py` contain mixed CRLF/LF. No non-EOL trailing spaces or tabs were found. Selected ports are authored as LF and must pass `git diff --check`.

The desktop Graphify graph is not current-release evidence. Any final graph refresh must use the guarded clean standalone-checkout workflow, never the protected dirty checkout or a linked worktree.
