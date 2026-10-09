# W63 compiler census headroom

Branch `claude/w63-compiler-census-headroom`, from `origin/main` `ddac90e3`. No local compiler,
`cli build`, pytest or other build was run, because the owner's rule is GitHub-hosted only. The
measured numbers below come from hosted Master reference run `37985453718`, job `114006196334`,
which ran on tested merge `67237220` of the first head `18664cf0`. Estimates are labelled as
estimates.

## The defect

`master-reference/release/compiler_bundle.py :: _MAX_COMPILER_CHUNK_BYTES` was 2 GiB (from
`719d91da`). `load_compiler_bundle` adds up the raw bytes of every compiler chunk it reads. It then
adds the exact Git blob of every identity-depth source (`_scan_identity_depth_sources`). The build is
refused when that sum passes the bound. Both refusals had the same text and no numbers, and nothing
printed the census, so nobody could see main approaching the wall.

- Main `ddac90e3` passed (run `37967469519`) with 1,960 chunks.
- PR #633 (W62) failed `cli build` (run `37972187439`, job `113961748491`) at 1,972 chunks, after
  adding about 237 KB of tracked bytes.
- **Measured:** this branch's first hosted run read a census of **2,146,489,257 bytes**. That is
  2,135,212,468 bytes from 1,962 chunks plus 11,276,789 bytes of identity-depth sources. It is
  **994,391 bytes under** the old 2,147,483,648-byte ceiling. Main, which is this tree without
  W63's few kilobytes, was therefore within about 1 MB of the wall.
- On 2026-10-01, `1300da6d` recorded a compiler output of 1.85 GB. The output has grown by about
  36 MB a day since then, during the train period.

### Measured census by group

| Group | Bytes | Share | Chunks |
|---|---:|---:|---:|
| `lines` | 1,099,282,127 | 51 % | 380 |
| `symbols` | 494,324,055 | 23 % | 21 (about 23.5 MB each; the per-chunk bound is 32 MiB) |
| `source_text` | 227,127,121 | 11 % | 1,262 |
| `structured` | 148,646,516 | 7 % | 150 |
| `calls` | 94,094,033 | 4 % | 116 |
| `components` | 43,829,966 | 2 % | 3 |
| everything else | about 28 MB | 1 % | |

The largest single contributors, estimated from Git blob line counts at about 1.6 KB per line record
plus source text, are:

- `webapp/sample_data/sample_fleet.snapshot.json`: about 160 MB, plus its structured values
- `reference-data/official-sources/ieee/oui.csv`: about 78 MB
- `tests/golden/snapshot.json`: about 33 MB
- the IANA service-names CSV: about 30 MB
- `cisco_toolkit/blast_radius_explorer.html`: about 26 MB
- `cisco_toolkit/analyze.py`: about 24 MB

The minified frontend dist assets come to only about 10 MB. Overall the census is about 37 times
the 57.6 MB of full-depth tracked text.

## What the bound protects

It is a resource ceiling, and it is not a privacy rule. The scan reads, decodes and checks every
chunk byte and every identity-depth source byte. If the census passes the ceiling, the build is
refused rather than sampled or skipped. So changing the ceiling never narrows the scan.

What the ceiling actually bounds is memory. `load_compiler_bundle` keeps every group's parsed
records, and the release family is then built from them; the step wrote about 1.78 GB. The required
check runs on `ubuntu-24.04`. GitHub's runner reference gives a standard Linux runner for a public
repository 4 CPUs, 16 GB of RAM and 14 GB of SSD
(<https://docs.github.com/en/actions/reference/runners/github-hosted-runners>).

**Measured peak RSS** (GNU `time -v`, run `37985453718`):

| Step | Peak RSS | Wall time |
|---|---:|---:|
| `python -m compiler` | 3,718,252 KiB (3.5 GiB) | 2:03 |
| `python -m cli build` | 12,004,760 KiB (11.45 GiB) | 11:50 |

The `cli build` peak is about 5.7 times the census. My first estimate, about 2.0-2.6 times from a
synthetic retained-records probe, was wrong: it missed the release-family construction.

## The chosen ceiling: 2.25 GiB (2,415,919,104 bytes)

The table assumes peak RSS scales linearly with the census, from that one measurement:

| Ceiling | Predicted `cli build` peak | Headroom over today | Verdict |
|---|---:|---:|---|
| 2 GiB | 11.45 GiB (measured at 99.95 %) | about 1 MB | reached |
| **2.25 GiB** | **about 12.9 GiB** | **about 269 MB** | **chosen**: leaves about 2.7 GiB for the OS and runner |
| 2.375 GiB | about 13.6 GiB | about 404 MB | rejected: too thin a margin for a one-point model |
| 3 GiB | about 17.2 GiB | about 1.07 GB | rejected: memory exhaustion would come before this refusal |

At 2.25 GiB the census sits at 88.9 %, with about 269 MB of headroom. That is roughly 7 days at the
last week's growth, or several G14-sized PRs (estimated at 25-35 MB each). **W63 unblocks main; it
does not create lasting room.** The lasting fix is to cut bytes or memory, as below.

## The change

1. The ceiling is now 2.25 GiB, and the code comment records the measurement and the reasoning.
2. There are two distinct refusals. Each carries `scanned_bytes` and `limit`:
   - "compiler chunk byte census exceeds the exhaustive privacy scan's resource ceiling" also names
     its group and index.
   - "compiler identity-depth source byte census exceeds the exhaustive privacy scan's resource
     ceiling".
3. `CompilerBundle.chunk_census` records chunk count and bytes, identity-depth bytes, scanned
   bytes, the limit, the headroom, utilisation, per-group chunks and bytes, and whether the
   local-identity scan ran. `build_release(observations=...)` passes it to the caller only; it never
   enters the release family. `python -m cli build` prints it in its success JSON.
4. CI prints `free -b`. It wraps the compiler and `cli build` in `/usr/bin/time -v` (GNU `time` 1.9
   is preinstalled on ubuntu-24.04), and prints the chunk count and bytes after compiling.

## Rejected alternatives, and the lasting fix

- **Sampling or skipping chunks.** This would break the exhaustive scan.
- **Deferring more prefixes to identity depth** (for example `webapp/sample_data/` or
  `reference-data/official-sources/`). It would save an estimated 0.3-0.4 GB, but it narrows line
  coverage. It also needs an owner decision and a BLOCK category under
  `compiler/policy.py :: CENSUS_DEPTH_DECLARATIONS`.
- **A compact per-line and per-symbol record encoding.** This is the policy's named follow-up owner
  and the real structural fix: `lines` and `symbols` hold 74 % of the bytes, largely repeated
  file-level and symbol-level fields. It is a record-schema change across the projection, release
  and continuity, so it is not a small fix.
- **Lowering `cli build` memory** (not retaining every group through family construction) would
  raise the safe ceiling directly. It needs hosted profiling first.

## Unverified, and the next walls

- The linear RSS model rests on one data point.
- Whether the hosted runner has swap is not documented; `free -b` now records it each run.
- **Expanded-projection wall:** `build/deployment-manifest.mjs :: MAX_EXPANDED_PROJECTION_BYTES` is
  also 2 GiB. On 2026-10-01 the expanded projection was 1.69 GB at 1.85 GB of output; scaled to
  today, that is about 1.96 GB (about 91 %). Nothing prints it, and W63 does not change it.
- **Per-chunk wall:** `symbols` chunks average about 23.5 MB against the 32 MiB per-chunk bound,
  which the release reader and `build/projection/build.mjs` both enforce.
