# W7 Atlas candidate validation (2026-10-04)

Status: candidate metadata prepared; final construction and artifact verification
are pending. Source owners are `pyproject.toml`, the portable release contract
and `.github/workflows/portable-release.yml`; this record is source-scoped evidence.

W2e merged as `583552ad888d73f51eaf28181c17f127cc285b2a`, with its tree equal
to the approved and tested source. W7 uses the reserved
`codex/atlas-release-candidate` branch in the existing checkout. Fresh release
and tag-ref checks found `3.33.0rc4` / `v3.33.0-rc.4` unused. The project version,
SSOT cache, current release mapping, current stick example, workflow description
and a candidate-preparation changelog entry are updated. Historical RC3 text,
existing RC1-RC3 drafts/assets, schema `3.23.0`, runtime code, dependency pins,
installer logic and workflow behavior remain unchanged.

Seven focused existing version, schema, example and PE checks passed with no
heavy local work. Independent metadata review found no concrete issue. Existing
W2e receipts and packages do not qualify the new candidate source. The prior
root Vitest cache was preserved externally with exact bytes/hash before removal
from the source checkout; no ignore rule or source-custody gate is changed.

The delegated owner supervisor requires the heavy canonical release build and
frozen smoke on GitHub-hosted runners while W10 uses this laptop. Local work
stays light; any necessary heavy local step must wait while free RAM is below
1.5 GB. No local frozen build is planned.

Before publication of this branch, run fresh stable-tree/index privacy, complete
new commit/message/per-parent-patch and proposed PR-body scans. Merge only
after every protected exact-head check passes. The final candidate is built
from freshly selected current merged main through `portable.build_release` in
the existing hosted workflow with `attach_draft=false`. Independently verify
API/archive/member/source/material custody against separately selected source
and reverify current-main required checks, because that build-only choice skips
the workflow's separate receiver and draft jobs. Preserve all negative or
incomplete evidence, and regenerate receipts for changed source.

The deliverable is the verified unsigned candidate plus stick-update
instructions. Tag creation, release attachment/publication, attestation, signing,
deployment, device and vault writes are outside authority. External qualification
and operator/physical-media acceptance gates remain explicit and pending.
