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
row, never by weakening a gate. Hosted export evidence and the supervisor handoff are recorded below; final-head results live on #632. Graphify is unverified under the standing hosted-only rule.

## Status

Implementation and independent static review are complete; no unresolved static must-fix finding. Runtime validation is **not verified**. The first privacy scan refused because the index changed during scanning; publication requires a fresh stable-source scan.
Rule-7 repository privacy, all new commit/per-parent patches, and publication-body marker scans
are required before every push. Supervisor review and merge remain the closing human action.

## Hosted export and supervisor handoff

PR #632 publishes `60bf94d8`. Scope run `37925731720` / job `113804081241`
passed export, source-bound capture, upload and typecheck. Artifact `11613958434`
(`scope-compiler-handoff-60bf94d88dc4d642e75d159bb8b214b253dfc481-37925731720-1`)
records tested merge `4a7908b4` and the unchanged sample digest `dbc229cfdcd676bb07e99bdace7e26ea429de087715ebf1727064b4e373a26c1`.
All four members were copied as review input using the owner output paths. Git reports a change
only in fabric; no sample or GOLDEN_SHA edit is made. No local receipt/controller verification
is claimed. The final hosted reproduction gate must independently reproduce every committed
member, and all applicable gates must pass on the final head. The bootstrap unit/freshness run
and any failed or cancelled observations remain visible in the Actions history; an export or
typecheck PASS does not qualify those later gates.

Independent applied-source review found no unresolved must-fix after resolving both-source
metric citations and the held clean-bill detail leak. Compiler, real-pane and comparison
counterexamples cover exact zero, lower-bound positive/zero, holds, unavailable ownership,
exact pointer/host admission and raw-detail disclosure. No assertion or gate is relaxed.
Supervisor review and merge follow the latest exact-head results on
[PR #632](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/pull/632).
Coordination remains on #630; its branch and the G14/#631 branch were not edited.
