# v3.32.0 draft release notes — NOT TAGGED YET

> Working draft for the next release cut. Per repo doctrine the `pyproject.toml` version bump
> happens only at tag time; this file exists so the cut is a mechanical step, not an archaeology
> session. Delete this file as part of the release commit (its content moves into the GitHub
> release body and the CHANGELOG heading).

## Proposed version: v3.32.0

Minor bump: additive surface (master reference, source binding) plus a large fix wave; no
breaking change to the CLI contract, snapshot schema (`cisco_toolkit.__version__` untouched), or
deliverable formats.

## Headline

The review release. A whole-repository adversarial review (98 register findings + the
matrix-hardening wave) closed the defect class that dominated every subsystem — **absence of
evidence rendered as health** — and rebuilt the proof chain around the release itself: the
archives are source-bound, the support floor is exercised (CI green on CPython 3.10–3.14 ubuntu
+ 3.12 windows), and the repository ships a self-explanatory master reference.

## For the field

- `--redact-folder` completeness is honest: exit 3 = produced-but-short with per-document
  ABSENT/UNUSABLE/STALE reasons and an INCOMPLETE-SET.txt marker; `--out` is one-job-per-folder.
- Custody no longer falsely refuses alias-spelled collection roots (8.3 short paths, junctions).
- Uploads work on Python 3.10.

## For reviewers

- CHANGELOG `[Unreleased]` carries the full fix inventory; the engineering-grade history stays in
  `COLLECT_PARSE_V3_23_0.md → Change Log`; the review's reasoning record is
  `docs/review-hardening-handoff-2026-07-30.md` (closed, historical).
- Release verification: `distribution_verify --require-source-binding` exit 0 on the built pair.

## Pre-tag checklist (release captain)

1. Hosted-runner billing restored, full hosted matrix green on the tag candidate.
2. `pyproject.toml` version → 3.32.0 (the ONLY place; schema version stays frozen).
3. CHANGELOG: retitle `[Unreleased]` → `[v3.32.0] — <date>`; start a fresh `[Unreleased]`.
4. Build + `distribution_verify` on the frozen source; archives attached to the GitHub release;
   `publish.yml` promotes the tagged assets (it never rebuilds).
5. Delete this draft file in the release commit.
