# Atlas 3.33.0rc7 preparation and validation

**Status at authorship: prepared; Rule-7 publication scans and final hosted checks pending.**
The prep PR's exact head, terminal Checks and closing summary own the final verdict.

- Base/current main: `89d214ea698e8cb48c124f3d5acb4ad2af101a3c`, G14 #652,
  supervisor-merged on 2026-10-15 at 07:01:36Z.
- Branch: `codex/release-3.33.0rc7`, Codex, isolated checkout.
- Product owner: `pyproject.toml`, `3.33.0rc7`; draft mapping: `v3.33.0-rc.7`.
- Schema owner: `cisco_toolkit/__init__.py`, unchanged at `3.23.0`.
- Exact prep template: [PR #662](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/pull/662),
  the same eight files with the new dated validation record replacing its RC6 counterpart.
- First-parent merge range from RC6 source `7fa74f53efea860773a284e50e525ffcb3f47065`
  to the base contains #663 RC6 closeout and #652 G14. Changelog claims follow current
  `docs/ssot.md` carriage/preparation owners and the final G14 summary/review, not its stale PR body.
- Golden, sample, schema and frontend bytes remain identical to the merged base throughout
  this preparation. This does not claim equality with RC6's pre-G14 outputs.
- W60c P2-6/P3-7, inherited creator marker-alias escape and Scope A6 remain open.

## Prerequisite main workflows: SUCCESS before preparation

Each run below is bound to full base SHA `89d214ea698e8cb48c124f3d5acb4ad2af101a3c`:

| Workflow | Run | Terminal conclusion |
|---|---|---|
| CI | [38696029644](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/actions/runs/38696029644) | SUCCESS |
| webapp-ci | [38696029640](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/actions/runs/38696029640) | SUCCESS |
| atlas-scope-ci | [38696029665](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/actions/runs/38696029665) | SUCCESS |
| Master reference | [38696029650](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/actions/runs/38696029650) | SUCCESS |
| CodeQL | [38696029529](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/actions/runs/38696029529) | SUCCESS |

These prerequisites do not qualify the changed RC7 head or the future merged source.

## Step 1: stop at the green prep PR

Run Rule-7 repository privacy plus all canonical raw/decoded marker patterns over every new
commit message, per-parent patch, `git log -p origin/main..HEAD` and publication body before
publication. Require all 15 live protected-main contexts on the final PR head to be SUCCESS,
post the summary and STOP for independent review and supervisor merge. No PR merge by the author.
Prior-head passes and RC6 receipts do not qualify this source. No local tests, builds, engine,
Graphify or receipt-controller execution; no test, gate, budget or timeout changes.

## Step 2: only after the supervisor confirms merge

Freeze other merges. Resolve and retain the exact merged main SHA. Wait for main's own
post-merge workflows/checks on that SHA to finish green before dispatch; do not reuse PR-head
or earlier-main results. RC5's first dispatch failed reverify while main CI was running;
that failure remains negative evidence.

Dispatch `portable-release.yml` on `main` with `source_commit=<exact merged full SHA>`,
`draft_tag=v3.33.0-rc.7`, `attach_draft=true`; watch through terminal SUCCESS. Then dispatch
`portable-receiver.yml` on `main` with the same source SHA and draft tag and require SUCCESS.
Report the draft URL, actual ZIP name, byte size, SHA-256, release and receiver run IDs, and
actual signing/qualification/external-gate receipt status. All build/runtime and receiver
verification stays on GitHub-hosted runners. No release publication.

## Owner-held external gates

All 14 gates from `portable/release_contract.py :: REQUIRED_EXTERNAL_GATES` remain
`external_pending`; the actual RC7 receipt must enumerate their resulting status:

- `production_authenticode_certificate_and_rfc3161_timestamp`
- `clean_managed_windows_smartscreen_smart_app_control_policy_run`
- `managed_applocker_or_app_control_policy_run`
- `physical_usb_full_and_read_only_media_tests`
- `physical_unplug_during_update_and_database_write`
- `bitlocker_to_go_recovery_key_custody_and_restore_drill`
- `actual_host_with_python_not_installed_and_nic_disconnected`
- `display_scaling_100_and_150_percent`
- `live_aaa_credential_rotation_confirmation`
- `independent_human_peer_review`
- `third_party_dataset_redistribution_legal_review`
- `physical_drive_unicode_and_full_workflow_pilot`
- `physical_database_recovery_and_rollback_drill`
- `field_operator_acceptance`

The owner will execute on real infrastructure. Automated integrity is not field qualification.
The v1 set stays permanently `draft_only`, `UNSIGNED_RELEASE_CANDIDATE`,
`AUTOMATED_PASS_EXTERNAL_GATES_PENDING`, `field_qualified=false`. No public promotion,
manual asset replacement, other tag push, signing claim or external-gate closure is authorized.
