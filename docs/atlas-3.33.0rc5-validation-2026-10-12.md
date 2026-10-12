# Atlas 3.33.0rc5 preparation and validation

**Status at authorship: prepared; publication scans and final hosted validation pending.**
The prep PR's exact head, terminal Checks and closing summary own the final verdict.

- Base: `c543f0a181e8db2700007f1658ae0d856dfbbbcd`, live `origin/main` after W60b/#656.
- Branch: `codex/release-3.33.0rc5`, held by Codex in its own isolated checkout.
- Product owner: `pyproject.toml`, `3.33.0rc5`; draft mapping: `v3.33.0-rc.5`.
- Schema owner: `cisco_toolkit/__init__.py`, unchanged at `3.23.0`.
- Reference preparation: `1d786416c6d8ba228b5e0db13b4a67cf3489db50` (rc4). Live release
  inventory has rc1/rc2/rc3 drafts and no rc4 draft. Prior dispatch is not candidate success.
- Scope: the seven rc4 metadata/example/board surfaces requested by the owner, plus this fresh
  note. Historical rc4 validation notes, product code, dependencies, generated outputs, tests
  and gates are preserved. Release notes derive from the merge range since `1d786416` through
  the base above; W60c P1-3/P1-4/P2-5/P2-6/P3-7 and compound logging arity remain open.

## Step 1: prep PR only

Run the Rule-7 repository privacy verifier and independent canonical marker scan over every
new commit message/per-parent patch, `git log -p origin/main..HEAD` and each publication body
before pushing or posting. Require all 15 live protected-main contexts on the exact PR head;
record broader failures, cancellations or missing checks alongside any passing result.
The supervisor independently checks and merges. Stop after green checks and the summary comment.
No local tests, builds, engine, Graphify or verification-controller runs are authorized here.

## Step 2: only after the owner reports the prep PR merged

Re-read live merged main and its terminal checks. Dispatch `portable-release.yml` on `main`
with `source_commit` equal to that exact full SHA, `draft_tag=v3.33.0-rc.5` and
`attach_draft=true`. Wait for success, then receive all draft assets into a fresh empty
directory. Independently check the closed release set with `portable/verify_release.py`,
the expected source/material binding and full CycloneDX schema validation; verify GitHub
provenance and SBOM attestations against the exact assets, source digest and signer workflow.
Keep receiver execution on GitHub-hosted runners under the standing owner rule. Report the
actual ZIP name, byte size, SHA-256, draft URL and exact qualification `external_pending` list.

The gate denominator is `portable/release_contract.py :: REQUIRED_EXTERNAL_GATES`:
production Authenticode/RFC3161; clean managed Windows SmartScreen/Smart App Control;
managed AppLocker/App Control; physical USB full/read-only tests; physical unplug during
update/database writes; BitLocker To Go recovery custody/restore; a Python-absent and
NIC-disconnected host; 100/150 percent display scaling; live AAA rotation; independent human
peer review; third-party dataset redistribution legal review; physical-drive Unicode/full
workflow pilot; physical database recovery/rollback; and field-operator acceptance.
The produced receipt decides the actual pending rows; preparation does not close any gate.

This is an owner-authorized draft prerelease for later real-infrastructure execution.
The portable v1 set remains `draft_only`; no public promotion or other tag push is authorized.
