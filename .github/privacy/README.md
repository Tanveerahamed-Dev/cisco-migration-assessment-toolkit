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
Project images have two code-pinned exceptions. `master-reference/public/og.png`
is pinned by exact path, `image/png` media type, 2,338,417-byte length, SHA-256,
PNG signature, IHDR position, and 1730x909 dimensions. The synthetic
Windows/Chromium visual-regression set is the sentinel-bounded
`_SYNTHETIC_VISUAL_BASELINES` mapping in `verify_repository_privacy.py`. Its
canonical contract is exactly two reviewed PNGs for every component registered
in `.design-sync/config.json`: `<Name>.png` at its configured primary viewport
(900 CSS pixels by default) and `<Name>-728.png` at the product-pane bound, all under
`webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/` (21 components,
42 files at the time this contract was introduced). They are generated only
from the tracked fictional `MERIDIAN-*` preview data and individually pinned by
exact path, media type, byte length, SHA-256, PNG structure, width, and height.
This is not a directory allowlist: a partial set, an extra sibling image, or a
changed byte without a matching reviewed pin is rejected.

After `test:visual:update`, inspect every changed PNG before refreshing its
privacy pin. Then run:

```text
python .github/scripts/refresh_visual_baseline_pins.py --write --reviewed
python .github/scripts/refresh_visual_baseline_pins.py
python .github/scripts/verify_repository_privacy.py
python -m pytest -q tests/test_repository_privacy.py
```

The refresh helper derives the exact 2× component path set and primary widths from the design-sync
config, refuses missing/extra/malformed/linked files and linked/reparse ancestors, validates complete
CRC-correct PNG chunk/IDAT streams, and rewrites only the
sentinel-bounded generated mapping. CI and ordinary reviews use its read-only
default check; `--write --reviewed` is an explicit human-review acknowledgement,
never an automatic CI step. While a baseline migration is incomplete, the
existing code-pinned mapping remains the only exception and the helper fails
closed instead of blessing a partial new set.
The Master Reference public social images (`og.png` and
`atlas-social-card.png`) are separate, path-exact project assets pinned in the
same verifier by media type, byte length, SHA-256, complete PNG structure,
width, and height. No other image or generic binary path is allowed.
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
