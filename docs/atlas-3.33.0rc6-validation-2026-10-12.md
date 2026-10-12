# Atlas 3.33.0rc6 preparation and validation

**Status at authorship: prepared; Rule-7 publication scans and final hosted checks pending.**
The prep PR's exact head, terminal Checks and closing summary own the final verdict.

- Base: `c39b706da3dc6fbb2be8dfd4b68c4084de139e5f`, latest `origin/main` after #660.
- Branch: `codex/release-3.33.0rc6`, Codex, isolated checkout.
- Product owner: `pyproject.toml`, `3.33.0rc6`; draft mapping: `v3.33.0-rc.6`.
- Schema owner: `cisco_toolkit/__init__.py`, unchanged at `3.23.0`.
- Prep reference: rc5 eight-file commit `be3924326a595bb9b3b599d829b40e5553e1e84e`,
  followed by board-only handoff `bf0e818c2ba70162637fcbc37405344ecd078a97`.
- Change log derives from `git log --merges 0dc2f5d6..origin/main` through the base:
  #659 hosted receiver, #661 RC5 closeout, #655 W65b census, #660 W60c repairs.
  W60c P2-6/P3-7, inherited creator marker-alias escape and Scope A6 remain open.

## Step 1: stop at the green prep PR

Run Rule-7 repository privacy plus canonical marker scans over every new commit message,
per-parent patch, `git log -p origin/main..HEAD` and publication body before publication.
Require all 15 live protected-main contexts on the final PR head, post the summary and STOP
for owner review and merge. Prior-head passes and RC5 receipts do not qualify this source.
No local tests, builds, engine, Graphify or receipt-controller execution.

## Step 2: only after the owner says merged

Resolve the exact merged main SHA. Wait for main's OWN post-merge CI on that SHA to have
ALL 15 required contexts terminal green before dispatch: RC5's first dispatch failed its
reverify while main CI was still running; that failure remains negative evidence.
Dispatch `portable-release.yml` on `main` with `source_commit=<exact merged full SHA>`,
`draft_tag=v3.33.0-rc.6`, `attach_draft=true`; watch through completion. Then dispatch
`portable-receiver.yml` on `main` with the same source SHA and draft tag and watch it.
Report the draft URL, actual ZIP name, byte size, SHA-256 and receiver receipt status on the PR.
All build/runtime and receiver verification stays on GitHub-hosted runners.

## Owner-held external gates

All 14 gates from `portable/release_contract.py :: REQUIRED_EXTERNAL_GATES` remain
`external_pending`; the actual RC6 receipt must enumerate their resulting status:

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
