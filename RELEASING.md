# Releasing

Releases are immutable promotions of one reviewed Git commit. The tag workflow
builds and verifies the wheel and source archive once, attaches those exact
files to a **draft** GitHub Release, and records their SHA-256 digests in
`dist-verification.json`. Draft creation is technical staging, not publication.
PyPI publishing is a separate, protected manual promotion of those assets; it
never rebuilds them.

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
`dist-verification.json` to a draft GitHub Release. The workflow never publishes
that draft. Publication requires the separate accountable decision after every
applicable archive, portable, signing, policy, physical-media, review, and field
gate has closed.

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
it is idempotent the same way the hosted workflow is: re-running an existing draft/release re-verifies
the staged or published assets rather than rebuilding. When hosted minutes return, the tag-triggered
workflow resumes as the canonical path; both paths verify rather than rebuild on re-runs, so
they cannot disagree about a release's contents.

## Build the Windows x64 portable release candidate

`.github/workflows/portable-release.yml` is the only portable candidate lane. On pull requests it
runs the Windows x64 actual-binary build without a write-capable repository token. A manual run
must name an exact full commit already on `main` and a unique candidate tag matching the PEP 440
project version (`3.33.0rc1` maps to `v3.33.0-rc.1`). It:

1. pins Python, PyInstaller, Node, npm, and a hash-locked Windows dependency set;
2. runs broad source/frontend tests on a separate read-only runner, while the artifact runner
   executes only hash-checked Python/npm inputs and reproduces the tracked SPA;
3. builds and executes the real `Atlas.exe`;
4. runs the four-step smoke plus offline-boundary, sanitized-Python-path, Unicode-path,
   drive-letter, database-copy, and frozen-redaction checks;
5. emits and reopens a closed release set: ZIP, member manifest, SHA-256 lists, file/dependency
   CycloneDX SBOM, runtime license/dataset notices, toolchain, signing, qualification, and
   provenance receipts; unkeyed `SELF_CONSISTENCY_PASS` is not authentication;
6. uploads one exact Actions artifact and, only on an authorized manual run, creates a new draft
   prerelease without overwriting existing assets; and
7. on a separate read-only runner, rebinds material hashes to exact current source and requires the
   latest live protected-main checks; the write/OIDC job executes no candidate source code, emits
   GitHub provenance and CycloneDX attestations, and verifies both against the exact source digest
   and signer workflow before attachment. Attestation still does not prove safety or qualification.

Without a production Authenticode certificate the receipt is `UNSIGNED_RELEASE_CANDIDATE`, the
physical/external qualification fields remain open, and the draft must stay unpublished. Follow
`docs/atlas-release-1-field-test-packet-2026-09-05.md` for the exact closing evidence.
This v1 portable release set is permanently `draft_only`; the repository currently defines no
public-promotion or protected signed-candidate upload lane. `prepare_signing` / `sign_release` /
`package_signed_release` are local, fail-closed qualification tooling only. Even after every field
row (including IEEE/Cisco dataset redistribution review) closes, public attachment requires a new
reviewed contract that ingests the unchanged signed ZIP, binds a separately custodied exact-asset
promotion decision, verifies it in a write-separated workflow, and preserves the original draft
receipts as historical facts. Do not manually upload or change this candidate's draft status.

## Promote the exact release to PyPI

> **DECIDED 2026-08-03 — this project is NOT published to public PyPI.**
> The repository itself is intentionally public, so source visibility is not the distinction.
> PyPI is avoided as an additional globally discoverable/installable package-index channel whose
> versions cannot be deleted or reused. The all-rights-reserved owner may choose a distribution
> channel; the license constrains recipient rights rather than the copyright owner's authority.
> A published GitHub Release in this public repository would also be publicly downloadable; only a
> draft remains collaborator-visible. No text here describes a public release as recipient-restricted.
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
