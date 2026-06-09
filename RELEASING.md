# Releasing

Releases are cut by **pushing a version tag**. A GitHub Actions workflow
([`.github/workflows/release.yml`](.github/workflows/release.yml)) then creates the GitHub Release
automatically, with notes generated from the merged PRs since the previous tag.

## Two version numbers (intentional)

This project deliberately keeps two distinct versions — don't try to unify them:

| Where | Value | Meaning |
|------|-------|---------|
| `pyproject.toml` → `[project].version` | the **release** version (e.g. `3.23.142`) | tracks the change log and the git tags; what `pip` reports |
| `cisco_toolkit.__version__` | pinned at **`3.23.0`** | the **snapshot-schema** version baked into the data contract (`script_version` in every snapshot). Bumping it would change the frozen golden snapshot (`tests/golden/snapshot.json`), so it stays put. The change log records "In-code version `3.23.0`" for every entry. |

So a release bumps **`pyproject.toml`**, never `__version__`.

## Cutting a release

1. Make sure `main` is green in CI and the change log
   ([`COLLECT_PARSE_V3_23_0.md`](COLLECT_PARSE_V3_23_0.md)) has an entry for the work.
2. Bump `version` in [`pyproject.toml`](pyproject.toml) to the new release number (match the latest
   `V3.23.x` in the change log), commit, and merge to `main`.
3. Tag the release commit and push the tag:

   ```bash
   git checkout main && git pull
   git tag -a v3.23.143 -m "v3.23.143"
   git push origin v3.23.143
   ```

4. The **Release** workflow fires on the tag and creates the GitHub Release with auto-generated notes.
   Nothing else to do. (The job is idempotent — re-running or pre-creating the Release by hand is safe.)

## Notes

- Tags use a leading `v` (`v3.23.143`); the workflow triggers on `v*`.
- The first release (`v3.23.142`) was bootstrapped with a concise hand-written note pointing at the
  change log (the auto-generated "everything since the first commit" would have listed ~200 PRs); every
  subsequent tag gets a tidy auto-generated diff against the previous tag.
- No build artifacts are attached: the deliverables (workbook / explorer / runbook) are generated at
  runtime from a live collection, not shipped in the repo. A future enhancement could attach a built
  wheel once the explorer-HTML template is relocatable inside the package (see the note in
  `pyproject.toml`).
