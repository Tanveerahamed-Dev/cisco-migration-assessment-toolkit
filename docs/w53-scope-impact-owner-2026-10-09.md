# W53: Atlas Scope failure-impact owner consumption

Scope starts from owner-merged main `6390b66c` (#629), on `codex/scope-impact-owner`.
This work changes Scope only. The projection counterparts remain on `claude/train-contract`
(#630), and G14/#631 remains with the main Codex chat. Coordination is recorded in
#630 comment `6080011056`.

## Source and behavior

`cisco_toolkit/analyze.py::compute_device_dossiers` persists the result of
`cisco_toolkit/impact_assessability.py` as each dossier's `impact_assessability`:
`assessable`, `why`, and the exact `failure_impact` row pointer. It does **not** persist
reason codes or per-cell severity eligibility. Scope preserves the owner's reason;
it does not manufacture codes or repeat the simulation's assessability predicates.

The compiler selects a unique dossier and its canonical indexed pointer, verifies the
pointed row's exact host, and holds measurements when ownership cannot be admitted.
Published counts retain exact zero. Positive lower bounds remain floors; bound zero
is held. Categorical severity is conservatively held for every lower-bound row because
the stored owner lacks per-cell eligibility. The selected raw row remains inspectable,
with its own citation separate from the owner's verdict and reason. Held recorded
detail remains an unverified source disclosure, not a clean bill.

The device pane qualifies every displayed bound and hold, including its comparison
summary. It consumes the owner's reason instead of computing an independent FHRP or
backup contradiction verdict. Scope's connectivity analysis remains a separate measure;
an owner-held row cannot certify no engine impact.

## Validation and output custody

No local tests, builds, browser checks, Graphify runs, measurements or receipt controllers
are authorized. Compiler and pane counterexamples are authored for GitHub-hosted CI.
The existing `atlas-scope-ci` captures the canonical four-output compile-all family on
the hosted source before freshness tests, allowing a review-input copy into this branch.
Final hosted CI must reproduce all four committed outputs from the final source and pass
the full applicable gates; artifact capture alone is not validation or merge authority.

The engine-built sample is unchanged. Its existing `GOLDEN_SHA` remains unchanged.
Any moving expectation must be justified by the persisted verdict and the selected source
row, never by weakening a gate. Hosted results and the final supervisor handoff will be
recorded here before completion. Graphify is unverified under the standing hosted-only rule.

## Status

Implementation and independent static review are complete; no unresolved static must-fix finding. Runtime validation is **not verified**. The first privacy scan refused because the index changed during scanning; publication requires a fresh stable-source scan.
Rule-7 repository privacy, all new commit/per-parent patches, and publication-body marker scans
are required before every push. Supervisor review and merge remain the closing human action.
