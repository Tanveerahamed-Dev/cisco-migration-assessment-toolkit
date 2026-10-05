# W7 Atlas candidate validation (2026-10-04)

Status: verified unsigned RC4 candidate complete from selected current main
`fa384d2d1ebb24f5eb7096e777f8d1fe87cc356b`; external qualification remains pending. Source owners are `pyproject.toml`, the portable release contract
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

## Final selected source and receiver (2026-10-05)

The first current-main candidate `d326a0d9` passed, but main advanced before
closeout/delivery. The owner's #590 changed acceptance-report.md and NOW only.
That earlier package, its verification, instructions and the unpublished
`abf8725d` closeout remain preserved solely for their own source. No receipt
transferred. W7 selected freshly reconciled main
`fa384d2d1ebb24f5eb7096e777f8d1fe87cc356b`, tree
`af1122a969176f1d1070a0fb30f76c52095e25e6`, and rebuilt through hosted
`portable.build_release` in run `37246571595` with `attach_draft=false`.
Both source/frontend and actual-binary jobs passed; receiver and publication
jobs skipped. All 15 actual current-main protected contexts from app 15368
passed, with no failed or pending checks, independently reconciled.

Expected source and all 12 materials were captured before the new artifact
was read. API artifact `11319223055` is 51,750,266 bytes, SHA-256
`3605954ae0221557e02d7c58d902efc29c4bfa4fc28668f7de34fc90d64e6d62`.
The independent receiver closed 12 delivery files, 865 runtime members
(103,629,733 bytes), eight embedded metadata files and all 12 selected materials.
Native/stock metadata, the MIT notice/upstream SBOM, toolchain and fresh twice-run
frozen selftest/native HTTP/private-resolver receipts join the selected source.
The canonical stdlib-only receiver used expected-source JSON, expected ZIP hash
and exact clean source-root; it passed in 8.484 seconds after an immediate
free-RAM reading of 2,752,471,040 bytes. Source and expectations stayed unchanged.
Strict CycloneDX is fresh source-bound hosted evidence; local omission is explicit.

Verified ZIP: `Atlas-3.33.0rc4-windows-x64.zip`, 51,578,747 bytes, SHA-256
`2f6b8130cc255a616c6f96334d2c33596bf3e1eed80b837c2bdfe17b7ceba838`.
Final independent receipt SHA-256:
`8522eabd3c98f75f29151b252524500e54b3eae0cbae8946a7a93e4280bb9453`.
Stock update/rollback instructions were regenerated with these exact paths,
source/tree, size and checksum. No update command or Atlas executable ran locally.
The complete release family and independent evidence remain preserved externally.

Status stays `UNSIGNED_RELEASE_CANDIDATE` /
`AUTOMATED_PASS_EXTERNAL_GATES_PENDING`, with all 14 external gates pending.
No tag/release, attestation, signing, deployment, device or vault write occurred.
Byte/source consistency is not externally authenticated publication or field
qualification. This later documentation record is not the evaluated source and receives no
build receipt; the frozen candidate remains pinned to `fa384d2d`. The owner
authorized a small docs PR, fresh privacy/history gates and a merge commit only
after all required exact-head checks pass. No candidate rebuild or release
promotion is implied by publishing these records.

Hosted artifact `11319223055` expires on **2026-11-04**. The API expiry is
`2026-11-04T00:18:16Z` (03:18:16 in Asia/Qatar), verified during closeout.
The verified local ZIP and complete delivery/receipt set remain preserved
independently of the hosted retention window. Tag, draft prerelease, signing
and publication remain the owner's decision after a real-fleet trial.
