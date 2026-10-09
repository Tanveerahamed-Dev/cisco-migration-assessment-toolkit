# W63 compiler census headroom

Branch `claude/w63-compiler-census-headroom`, from `origin/main` `ddac90e3`. No local compiler,
`cli build`, pytest or other build was run, because the owner's rule is GitHub-hosted only. Every
runtime number below is an estimate until the first hosted run on this branch prints the census and
peak RSS.

## The defect

`master-reference/release/compiler_bundle.py :: _MAX_COMPILER_CHUNK_BYTES` was 2 GiB (from
`719d91da`). `load_compiler_bundle` adds up the raw bytes of every compiler chunk it reads. It then
adds the exact Git blob of every identity-depth source (`_scan_identity_depth_sources`). The build is
refused when that sum passes the bound. Both refusals had the same text and no numbers, and nothing
printed the census, so nobody could see main approaching the wall.

- Main `ddac90e3` passed (run `37967469519`): 1,960 chunks. Records: 757,842 `lines`, 299,433
  `structured`, 231,691 `calls`, 40,237 `symbols` and 1,261 `source_text` files.
- PR #633 (W62) failed in `cli build` (run `37972187439`, job `113961748491`). It had 1,972 chunks
  (+3,153 lines, +1,396 calls, +266 symbols, +9 source files) from about 237 KB of new tracked bytes.
  That growth adds an estimated 8-12 MB of chunk bytes. So main was within roughly 10 MB of
  2,147,483,648.
- On 2026-10-01, `1300da6d` recorded a compiler output of 1.85 GB. Main is now about 2.14 GB, which
  is about 36 MB a day during the train period.

## What the bound protects

It is a resource ceiling, and it is not a privacy rule. The scan reads, decodes and checks every
chunk byte and every identity-depth source byte. If the census passes the ceiling, the build is
refused rather than sampled or skipped. So raising the ceiling never narrows the scan.

The ceiling does bound memory. Every caller retains all record groups, and the release pipeline
needs all of them. A synthetic CPython 3.12 probe parsed record shapes copied from the compiler and
measured them with tracemalloc. Retained records take about 2.6 times their canonical JSON bytes
for `lines` and `structured`, and about 2.0 times for `source_text`. Each chunk is separately capped
at 32 MiB, so the transient cost of one chunk stays small.

The required check runs on `ubuntu-24.04`. GitHub's runner reference gives a standard Linux runner
for a public repository 4 CPUs, 16 GB of RAM and 14 GB of SSD
(<https://docs.github.com/en/actions/reference/runners/github-hosted-runners>). GNU `time` 1.9 is an
installed apt package on that image (`actions/runner-images`, `Ubuntu2404-Readme.md`).

| Ceiling | Retained records (estimated) | Verdict |
|---|---|---|
| 2 GiB | 4.3-5.6 GB | already reached |
| **3 GiB** | **6.4-8.4 GB** | **chosen**: leaves about 6-9 GB for the interpreter, ID sets, the PDF stage and the OS |
| 4 GiB | 8.6-11.2 GB | rejected: too close to 16 GB before the later stages are measured |

At 3 GiB the headroom is about 1.07 GB. At about 2.8 KB of census per nonblank line, that is
roughly 380k more nonblank lines, or about 30 days at the last eight days' pace.

## Where the bytes come from (estimates)

A synthetic `lines` record is about 1.4-2.0 KB (1.62 KB is typical): 30 fields, several of them
digests, repeated IDs and a text preview of up to 240 characters. Each `source_text` line entry is
about 210 bytes plus its text. The estimated split is:

- `lines`: about 1.2-1.3 GB, about 60 % of the census
- `source_text`: about 0.23 GB
- `structured`: about 0.13 GB
- `calls`, `symbols`, `tests` and components together: about 0.4 GB
- identity-depth sources: 11.3 MB of raw `atlas-scope/` bytes

Overall the census is about 37 times the 57.6 MB of full-depth tracked text.

The largest estimated contributors, counting line and source-text records only:

| Contributor | Estimated census |
|---|---|
| `webapp/sample_data/sample_fleet.snapshot.json` | about 160 MB, plus its structured values |
| `reference-data/official-sources/ieee/oui.csv` | about 78 MB |
| `tests/golden/snapshot.json` | about 33 MB |
| the IANA service-names CSV | about 30 MB |
| `cisco_toolkit/blast_radius_explorer.html` | about 26 MB |
| `cisco_toolkit/analyze.py` | about 24 MB |
| `webapp/frontend/src/generated/openapi.ts` | about 20 MB |

By directory: `tests` about 299 MB, `cisco_toolkit` about 288 MB, `webapp/sample_data` about
161 MB, `reference-data/official-sources` about 136 MB, and `webapp/frontend` about 82 MB (the
minified dist assets are only about 10 MB of that). G14's roughly 12.9k sample lines would add an
estimated 25-35 MB.

## The change

1. The ceiling is now 3 GiB, and the code comment records the reasoning above.
2. There are two distinct refusals. Each carries `scanned_bytes` and `limit`:
   - "compiler chunk byte census exceeds the exhaustive privacy scan's resource ceiling" names its
     group and index.
   - "compiler identity-depth source byte census exceeds the exhaustive privacy scan's resource
     ceiling".
3. `CompilerBundle.chunk_census` records chunk count and bytes, identity-depth bytes, scanned bytes,
   the limit, the headroom, utilisation, per-group chunks and bytes, and whether the local-identity
   scan ran. `build_release(observations=...)` passes it to the caller only; it never enters the
   release family. `python -m cli build` prints it in its success JSON.
4. CI wraps the compiler and `cli build` in `/usr/bin/time -v`, which reports peak RSS on success
   or failure. After compiling, CI prints the chunk count and bytes.

## Rejected alternatives

- **Sampling or skipping chunks.** This would break the exhaustive scan.
- **Deferring more prefixes to identity depth** (for example `webapp/sample_data/` or
  `reference-data/official-sources/`). It would save about 0.3-0.4 GB, but it narrows line coverage.
  It also needs an owner decision and a BLOCK category under
  `compiler/policy.py :: CENSUS_DEPTH_DECLARATIONS`. That is a coverage change, not a capacity fix.
- **A compact per-line record encoding.** This is the policy's named follow-up owner and the real
  structural fix, because about 60 % of the bytes are per-line records repeating file-level and
  symbol-level fields. It changes the record schema that the projection, release and continuity read,
  so it is not a small, independently reviewable change.

## Unverified, and the next wall

- Record sizes and the retained-memory ratio come from synthetic probes. The exact main census and
  both peak RSS figures are unknown until the first hosted run. Revisit the ceiling with those
  numbers, not with these estimates.
- **Sibling wall (not changed here):** `build/deployment-manifest.mjs :: MAX_EXPANDED_PROJECTION_BYTES`
  is also 2 GiB. On 2026-10-01 the expanded projection was 1.69 GB at 1.85 GB of compiler output.
  Scaled to today, it is about 1.95 GB (about 91 %), and nothing prints it. It will refuse `npm test`
  at roughly 2.35 GB of compiler output.
