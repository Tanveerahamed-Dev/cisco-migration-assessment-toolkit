# Atlas browser projection

`build.mjs` converts a completed whole-repository compiler corpus into native
ES modules that work with Atlas's `connect-src 'none'` runtime policy.

Publishable build:

```text
node build/projection/build.mjs --input <compiler-output> --output public/atlas-projection
```

The command accepts only the compiler's exact `1.2.0` contract. It fails unless
the manifest declares `release_class` as `exact_commit`, the tracked worktree is
clean, all required record groups and named completeness invariants are present,
the completeness ledger has no hard/fatal failure, every consumed chunk matches
its manifest digest, and every safe source record round-trips to its declared
file, byte, physical-line, nonblank-line, and semantic-line denominators.

For an explicitly labelled local-only preview, add `--allow-preview`. Preview
state remains embedded in `index.mjs`; it is not made publishable by the flag.

Output layout:

- `identity.mjs` — an independently capped (8 KiB raw) exact-source and
  semantic-verdict receipt used by the landing page without loading explorer
  registries.
- `index.mjs` — the complete source-bound manifest and static lazy-loader
  registry. It is loaded only by workspaces that request repository records;
  its size is reported rather than described as an initial-page payload.
- `metadata/<group>/*.mjs` — content-hashed lazy chunks for every compiler
  metadata group except per-line and source-text records. This includes claims,
  imports, calls, dependencies, Markdown, structured data and manifests.
- `search/index-*.mjs` and `search/shards/*.mjs` — a bounded exact-token index.
  Stable IDs make every indexed record directly reachable; broad postings are
  deterministically capped and disclose their complete match denominator.
- `source/index-*.mjs` and `source/chunks/*.mjs` — bounded line/UTF-8-fragment
  chunks. Ordered chunks reconstruct every safe file byte-for-byte, while a
  stable line link loads only the chunk containing that line.
- `graph/summary-*.mjs`, `graph/index-*.mjs`, and `graph/shards/*.mjs` — a
  bounded initial graph overview plus complete community partitions loaded only
  after selection.
- `records/{symbol,data,test,workflow,claim}/*.mjs` — deterministic, recursively
  split stable-ID dossier buckets. Every ID routes through the same exported
  prefix map used to write the leaf module. Test assertion groups and workflow
  job/step/permission/artifact entities retain their adapter fields.
- `projection-manifest.json` — digests for every generated module.
- `.atlas-projection-generated` — ownership marker required before replacement.

The generated directory is a release product, not authored source. Ignore only
`/master-reference/public/atlas-projection/`; do not ignore the adapter itself.

The projection manifest records executable raw-byte ceilings for the landing
identity module, every metadata module, every dossier module, search shards and
indexes, source chunks and indexes, and graph summaries/shards/indexes. Metadata and dossier modules split
recursively at 256 KiB. A single record above the ceiling is serialized once,
split into content-hashed UTF-8 fragment modules, and reassembled only when its
metadata group or stable-ID dossier is requested. Metadata and dossier views
share the same fragment set, preserve the complete projected record, and fail
closed if any fragment or fragment-loader index cannot satisfy the ceiling.
