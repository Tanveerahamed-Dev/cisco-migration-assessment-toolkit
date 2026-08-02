# Repository privacy boundary

`known_client_hostname_sha256.txt` is a one-way denylist for private hostname
tokens. The repository guard lowercases each hyphenated token as UTF-8, hashes it
with SHA-256, and compares only the digest. Raw hostnames and the alias mapping
must never be stored in the pushable tree.

The current set contains 253 canonical private-estate hostnames plus three
observed inventory/reporting variants. Public fixtures use deterministic
`MERIDIAN-*` aliases and reserved `example.net` domains.

The guard inspects both tracked files and non-ignored untracked files—the exact
set that could enter the next commit. Ordinary files must be bounded, strict
UTF-8 text; opaque/binary content is refused even when it contains no NUL byte.
In default mode, "tracked" means the immutable stage-zero Git index blobs as
well as stable working-tree copies. The two are scanned separately so a
sensitive staged version cannot hide behind a clean working-tree version, and
an unstaged deletion cannot hide the blob that the next commit would retain.
The only binary exceptions are the OUI and port registry packs, whose exact
size and SHA-256 must match `cisco_toolkit/data/registry_manifest.json`.
The sole project-asset exception is `master-reference/public/og.png`; its exact
path, `image/png` media type, 2,338,417-byte length, SHA-256, PNG signature,
IHDR position, and 1730x909 dimensions are hard-coded and regression-tested.
No other image or generic binary path is allowed.
The four retained IEEE/IANA CSV corpora are a separate, path-exact public-data
exception: their URL, schema, row count, byte length, and SHA-256 must match
`reference-data/official-sources/manifest.json`; they remain strict UTF-8
ordinary files. The retained Cisco EoL semantic fixture is the fifth public
source exception. Its manifest record, path, 13,261-byte length, SHA-256,
JSON schema, 17 unique Cisco HTTPS bulletin URLs, and 44 unique model scopes
are code-pinned and checked exactly; generic JSON or arbitrary extra public
sources are not allowed. Every read pins a regular non-link filesystem identity
before, during, and after the bounded read. Per-file, aggregate-byte,
file-count, denied-path, generated-artifact, symlink/reparse-point, and
non-regular Git-entry checks keep the scan finite and fail closed.

When the private inventory changes, regenerate the sorted digest set in a
private workspace, review the working-tree replacements, and run:

```text
python .github/scripts/verify_repository_privacy.py
python -m pytest -q tests/test_repository_privacy.py
```

During a review whose sanitizing changes have deliberately not been staged,
`--worktree-only` validates the candidate working-tree bytes without reporting
the stale index. Its success message explicitly states that it does **not**
prove the Git index or next commit. CI, release jobs, and pre-commit use must
always run the default index-plus-worktree mode.

SHA-256 here is a detection mechanism, not encryption or authentication.
