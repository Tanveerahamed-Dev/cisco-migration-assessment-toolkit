# Atlas Release 1 GitHub state

Status date: 2026-09-05 (Asia/Qatar). This record distinguishes repository configuration, technical verification, owner authority, peer review, qualification, and publication.

## Verified baseline

- Repository: `Tanveerahamed-Dev/cisco-migration-assessment-toolkit`.
- Visibility: `PUBLIC`; the owner explicitly confirmed public visibility is intentional for this task.
- Default branch: `main`; live start commit `b9cb2c3d27ed6652ad6f98b75fa99ba9d2ed7ab6`.
- Viewer permission used for authorized changes: `ADMIN` as the sole owner.
- Latest published release at task start: `v3.32.1` (2026-08-03); it contains no Atlas portable ZIP and is not relabelled by this work.
- Main protection at task start required one approval and 13 named checks, but `strict=false`, `enforce_admins=false`, `require_last_push_approval=false`, `required_conversation_resolution=false`, and signatures were not required. No repository ruleset existed.
- PRs 547-552 were merged with zero formal reviews and retained `REVIEW_REQUIRED`. Those merges remain technical integration, not peer review.

## Security controls enabled in scope

- GitHub secret scanning: enabled.
- Secret-scanning push protection: enabled.
- Dependabot vulnerability alerts: enabled.
- Dependabot security updates: enabled and not paused.
- CodeQL default setup: configured with the extended suite for Actions, Python, and JavaScript/TypeScript discovery. Initial run `33960295013` passed all three analysis jobs.
- Main required checks are now strict/up-to-date and conversation resolution is required. The
  original 13 exact contexts were preserved and the two new portable contexts (`Build and qualify
  Atlas.exe`; `Full source and frontend gate (unprivileged runner)`) were added, for 15 total. The
  one-approval rule was preserved.
- Non-provider-pattern scanning and validity checks remained disabled after the repository update; no unsupported/paid capability is claimed enabled.

These controls improve detection. They do not certify the code, supply review, sign binaries, qualify a portable product, or authorize publication.

## Review and release boundary

The sole owner cannot produce a non-author GitHub approval. Administrator enforcement and latest-push
approval therefore remain disabled rather than pretending that a peer exists; any authorized owner
merge must be recorded as an administrator exception and technical integration only. Codex/subagent
review, GitHub CodeQL, tests, attestations, an owner-approved admin merge, and a signed Git commit must
each retain their real labels. The closed `external_pending` denominator and field-test packet own
the full gate list, including production Authenticode/timestamp, managed Windows policy, physical
USB/BitLocker/update/database recovery, Python-absent disconnected-host and display/drive/workflow
pilots, live AAA rotation, dataset redistribution review, independent human review, and operator
acceptance. The authorized intermediate is a draft prerelease with explicit
unsigned/external-gates-pending receipts. The v1 portable contract defines no public-promotion lane.

## Pending reconciliation fields

- Release implementation PR/head: `null`
- Portable workflow exact-head result: `null`
- Formal non-author reviews: `0`
- Merge commit: `null`
- Draft candidate tag/release URL: `null`
- Final publication: `false`
