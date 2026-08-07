# Atlas browser projection

`build.mjs` converts a completed whole-repository compiler corpus into native
ES modules that work with Atlas's `connect-src 'none'` runtime policy.

Publishable build:

```text
node build/projection/build.mjs --input <compiler-output> --output public/atlas-projection
```

The command fails unless the compiler manifest declares `release_class` as
`exact_commit`, the tracked worktree is clean, the completeness ledger has no
hard/fatal failure, every consumed chunk matches its manifest digest, and every
safe source record round-trips to its declared byte and line digests.

For an explicitly labelled local-only preview, add `--allow-preview`. Preview
state remains embedded in `index.mjs`; it is not made publishable by the flag.

Output layout:

- `index.mjs` — small source-bound manifest plus static lazy-loader maps.
- `metadata/<group>/*.mjs` — content-hashed lazy chunks for every compiler
  metadata group except per-line and source-text records. This includes claims,
  imports, calls, dependencies, Markdown, structured data and manifests.
- `source/*.mjs` — one exact-text payload per allowed safe text file.
- `records/{symbol,data,test,workflow,claim}/*.mjs` — small deterministic
  dossier buckets. Test assertion groups and workflow job/step/permission/
  artifact entities retain the fields emitted by their structural adapters.
- `projection-manifest.json` — digests for every generated module.
- `.atlas-projection-generated` — ownership marker required before replacement.

The generated directory is a release product, not authored source. Ignore only
`/master-reference/public/atlas-projection/`; do not ignore the adapter itself.
