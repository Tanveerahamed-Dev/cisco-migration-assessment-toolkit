# Releasing

Releases are immutable promotions of one reviewed Git commit. The tag workflow
builds and verifies the wheel and source archive once, attaches those exact
files to a GitHub Release, and records their SHA-256 digests in
`dist-verification.json`. PyPI publishing is a separate, protected manual
promotion of those assets; it never rebuilds them.

## Version contract

The repository intentionally has two version axes:

| Location | Meaning |
|---|---|
| `pyproject.toml` → `project.version` | Product release and Git tag version |
| `cisco_toolkit.__version__` | Snapshot-schema version embedded in assessment data |

Only the product release changes for an ordinary release. Change the snapshot
schema version only with an explicit data-contract migration and updated
compatibility tests.

## Preconditions

Before tagging:

1. Merge the release commit to `main`.
2. Confirm all required CI checks are green, including the full Python matrix,
   coverage, frontend/backend tests, dependency audit, privacy gate, and
   distribution contract. **This is now also enforced mechanically**: both
   release workflows run the complete test suite against the tagged source
   before building or attaching anything, so a tag cut from a red commit fails
   the release instead of producing assets. It became a step because it failed
   as a promise — v3.32.0 was released from a commit whose own suite was red
   (a version-cache reconcile test), caught only afterwards.
3. Ensure `pyproject.toml` contains the intended release version.
4. Review the change log and the master reference for user-visible changes.
5. Confirm the GitHub `pypi` environment still requires the intended approval
   policy before any public package promotion.

## Create the release

Create an **annotated** tag whose value is exactly `v` plus the
`pyproject.toml` version:

```bash
git switch main
git pull --ff-only
git tag -a v3.31.0 -m "v3.31.0"
git push origin v3.31.0
```

The `Release` workflow fails closed unless:

- the ref is an annotated `vX.Y.Z` tag;
- its version exactly matches `pyproject.toml`;
- the checked-out commit is the tagged commit; and
- that commit is an ancestor of `origin/main`.

For a new tag, the workflow rebuilds and tests the AssessHub SPA, creates
exactly one wheel and one source archive, validates metadata, entry points,
runtime assets, wheel `RECORD` hashes, archive path safety, and the privacy
boundary, installs the wheel outside the checkout, runs entry-point and
authoritative-registry smoke tests, and attaches the verified archives plus
`dist-verification.json` to the GitHub Release.

Re-running an existing release downloads and re-verifies its existing assets.
It does not replace them with a fresh build.

### Hosted-minutes outage: the self-hosted release path

When GitHub-hosted minutes are unavailable (billing exhaustion), the tag-triggered `Release`
workflow cannot execute. **Release (self-hosted)** (`release-selfhosted.yml`) is the sanctioned
alternative: dispatch it manually with the existing tag. It replicates the same fail-closed gate
sequence (annotated-tag/version/ancestry verification, privacy boundary, immutability proofs
between every step, single build, trusted distribution proof, clean-venv smoke test) on the
self-hosted fleet, and attaches the assets to the GitHub Release. It is deliberately
dispatch-only — never `pull_request` — per the runner-isolation rule in the `ci.yml` header, and
it is idempotent the same way the hosted workflow is: re-running an existing release re-verifies
the published assets rather than rebuilding. When hosted minutes return, the tag-triggered
workflow resumes as the canonical path; both paths verify rather than rebuild on re-runs, so
they cannot disagree about a release's contents.

## Promote the exact release to PyPI

> **DECIDED 2026-08-03 — this project is NOT published to the public PyPI.**
> The open question below ("decide explicitly whether public installability is
> appropriate") is now answered: **no**. `LICENSE` is all-rights-reserved
> proprietary — "No permission is granted to use, copy, modify, merge, publish,
> distribute... except with the prior written consent of the copyright holder" —
> and PyPI is a public distribution channel whose versions can be yanked but
> never deleted or reused. Publishing there would make the full source
> permanently world-downloadable and `pip install`-able by anyone, which the
> license forbids. **Distribution is the GitHub Release**, which already carries
> the verified wheel, source archive and `dist-verification.json` source-binding
> proof for authorized recipients.
>
> `publish.yml` is retained, unused, and still correct: if a private index or a
> licensing change ever makes promotion appropriate, it is the reviewed path.
> Reopening this requires an explicit, recorded decision — not a convenience call.

The procedure below applies only if that decision is ever revisited. Publishing
is intentionally manual because a PyPI version cannot be replaced.
Run **Publish verified release to PyPI** and supply the existing tag, for
example `v3.31.0`.

The workflow:

1. checks out that exact tag and repeats the tag/version/main-ancestry gate;
2. downloads the wheel and source archive from the GitHub Release;
3. re-runs archive and metadata verification without rebuilding;
4. publishes with PyPI trusted publishing (OIDC); and
5. requests PyPI attestations for the uploaded files.

One-time repository administration:

- Configure the PyPI trusted publisher for
  `Tanveerahamed-Dev/cisco-migration-assessment-toolkit`,
  workflow `publish.yml`, environment `pypi`.
- Protect the `pypi` GitHub environment with a required reviewer.
- Decide explicitly whether public installability is appropriate. The package
  is proprietary (`LicenseRef-Proprietary`); publication grants no additional
  rights beyond the `LICENSE`.

## Local release-candidate verification

From a clean checkout with Node 24 LTS (24.18.0 or newer) and Python 3.12:

```bash
cd webapp/frontend
npm ci
npm test
npm run build
cd ../..
source_commit="$(git rev-parse 'HEAD^{commit}')"
source_tree="$(git rev-parse 'HEAD^{tree}')"
python -m pip install "build==1.5.0" "twine==6.2.0"
python -m build --sdist --wheel --outdir dist
python -m twine check dist/*
python tools/audit_wheel.py dist
python -m cisco_toolkit.distribution_verify dist \
  --source-commit "$source_commit" \
  --source-tree "$source_tree" \
  --require-source-binding \
  --json-out dist-verification.json
```

Do not publish locally. The protected workflow is the authoritative promotion
path and is the only path that binds the reviewed tag to the released bytes.
