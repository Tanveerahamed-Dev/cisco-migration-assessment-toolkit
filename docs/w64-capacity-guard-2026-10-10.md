# W64-0 master-reference capacity guard

Branch `claude/w64-capacity-guard`, cut from the W63 head `4b66806c`
(`claude/w63-compiler-census-headroom`, PR #634), so the workflow edits stack on W63's
instrumentation instead of conflicting with it. No local compiler, `cli build`, pytest, npm or
other build was run, because the owner's rule is GitHub-hosted only. Only static checks ran
locally: in-memory compilation, ruff with the workflow's path set, an AST scan of the new test
module, and a read of the workflow.

## Why

W63 showed main's master-reference pipeline sitting just under several hard walls, and only one of
them (the release census) was printed:

- the release intake census, 2,146,489,257 B against the 2.25 GiB ceiling (88.9 %);
- `cli build` peak RSS, 12,004,760 KiB on a 16 GB runner;
- the projection's 2 GiB expanded and 512 MiB compressed bounds, estimated near 91 % and never
  printed;
- `symbols` chunks averaging about 23.5 MB against the 32 MiB per-chunk bound.

A wall that is not measured is found by the PR that crosses it, as #633 found the census. W64-0
measures every wall on every run, warns at 85 %, fails at 95 % with an actionable message, and
keeps a trend.

## What it measures

`master-reference/cli/capacity.py` (run as `python -m cli.capacity`) reads each limit on every run
from its one code owner and never restates it: an AST read of a Python module constant, or the
single top-level `const` of an ES module, which must be a product of integer literals. Anything else
fails closed. Runner walls read `/proc/meminfo` and `statvfs`.

| Wall id | Value | Limit owner |
|---|---|---|
| `release.census_bytes` | `cli build` success JSON `compiler_chunk_census.scanned_bytes`; on a refusal, the refusal's `scanned_bytes` (a lower bound, since the scan stops at the crossing) | `release/compiler_bundle.py::_MAX_COMPILER_CHUNK_BYTES` (the census JSON's `limit_bytes` must equal it) |
| `chunk_bytes.<group>`, one per manifest group | the largest chunk receipt, checked against the file's size | the stricter of `release/compiler_bundle.py::_MAX_COMPILER_JSON_BYTES` and `build/projection/build.mjs::COMPILER_JSON_MAX_BYTES` (both enforce it) |
| `compiler.owner_json_bytes` | the largest of `manifest.json` and the manifest's file receipts | the same pair |
| `compiler.json_values` | the most JSON values in one compiler file, counted as `parseCanonicalCompilerJson` counts (every value, never keys) | `build/projection/build.mjs::COMPILER_JSON_MAX_VALUES` |
| `compiler.json_string_bytes` | the longest canonical string token, quotes, escapes and keys included | `build/projection/build.mjs::COMPILER_JSON_MAX_STRING_BYTES` |
| `release.graph_scan_values`, `release.graph_scan_bytes` | the release intake's Graphify local-identity scan, counted as `_scan_generated_local_identities` counts (keys included) | `release/compiler_bundle.py::_LOCAL_SCAN_MAX_VALUES`, `::_LOCAL_SCAN_MAX_TOTAL_BYTES` |
| `projection.expanded_bytes`, `projection.compressed_bytes` | the compression receipt's aggregates, which must equal its module sums; without a receipt, the expanded wall is measured from the `build.mjs` output tree | `build/deployment-manifest.mjs::MAX_EXPANDED_PROJECTION_BYTES`, `::MAX_COMPRESSED_PROJECTION_BYTES` |
| `projection.module_max_expanded_bytes`, `projection.module_max_compressed_bytes` | the largest module in the compression receipt | `build/deployment-manifest.mjs::MAX_EXPANDED_MODULE_BYTES`, `::MAX_COMPRESSED_MODULE_BYTES` |
| `receipt.{compression,projection,deployment}.bytes` and `.values` | each gzip receipt, gunzipped, and its value count | `build/deployment-manifest.mjs::MAX_JSON_RECEIPT_BYTES`, `::MAX_JSON_STRUCTURE_VALUES` |
| `deployment.member_max_bytes` | the largest direct deployment member | `build/deployment-manifest.mjs::MAX_DEPLOYMENT_MEMBER_BYTES` |
| `peak_rss.{compiler,projection,npm_test,cli_build}` | GNU `time -v` maximum RSS of each step | runner `MemTotal` |
| `disk.runner_temp` (also holds the workspace when they share a file system) | used bytes at guard time, the end of the job | used plus space available to unprivileged writers |

Two denominators are restated, each pinned by a test to its owner's source: the release scan's
group tuple `("graph_nodes", "graph_edges")` and the receipt file names.

## Thresholds, messages and exit codes

Thresholds are exact rationals: below 85 % is ok, 85 % to below 95 % warns, 95 % and above fails.
The displayed percentage is truncated, never rounded up across a threshold.

- A warning prints `::warning::` and a summary row.
- A failure prints `::error::` naming the wall, the value, the limit, the owning constant and the
  remedy, and the guard exits 1.
- An absent or malformed measurement input leaves its wall **unmeasured**, which fails closed with
  exit 2. A wall that was not measured is never reported as headroom.

Every run writes `capacity.json` and appends a Markdown job summary, even when it fails.

## The per-field byte census (input for W64b)

For every record group, the guard attributes each chunk byte to a record field (`"key":value` in
canonical JSON), to record structure (braces and commas) or to the chunk envelope. It is computed
after the fact from the canonical chunks, so no compiler artifact, receipt or digest changes. It is
exact by construction: each chunk's reconstruction must equal its byte size, or the census is
refused and the guard exits 2. The job summary shows the four largest groups; `capacity.json`
carries every group.

## Trend

- On a push to `main`, the workflow uploads `capacity.json` as the artifact
  `master-reference-capacity` (90-day retention; a re-run overwrites it).
- Every run first fetches the newest readable record from a completed `main` push run with `gh`
  and the default `GITHUB_TOKEN`. The job gains `actions: read` for this; it grants no write.
- The guard keeps at most 30 history rows, one per run. It reports the delta since that main
  record, and days to 85 % and to 100 % from a least-squares growth rate over at least six hours of
  history.
- No baseline (a fork, the first run, an expired artifact) is reported as "no baseline". A
  malformed baseline is refused and reported. Neither ever changes the guard's exit code.

## Workflow wiring

Every existing step and gate in `.github/workflows/master-reference-ci.yml` is kept:

- The compiler, projection, `npm test` and `cli build` steps now write their GNU `time -v` report
  to `$RUNNER_TEMP/atlas-capacity` with `-o`, print it, and still exit with the command's own
  status.
- `cli build` keeps its stdout (the census JSON) and stderr (a refusal) as files and prints both
  after the command ends.
- Three steps follow `verify-family`: the advisory baseline fetch, the guard, and the main-only
  upload.

The baseline fetch and the guard run under `if: ${{ !cancelled() }}` rather than `always()`. They
still run after a failed step, so a failing step's numbers are reported, but they do not hold a
cancelled run (for example one superseded by `cancel-in-progress`) for another scan of the
compiler output.

## Tests

`master-reference/tests/release/test_capacity_guard.py` covers:

- the threshold boundaries (84.99, 85, 94.99 and 95 %, and exact rationals on the real census
  ceiling);
- the content of the fail, warn and unmeasured messages, and their annotation escaping;
- the exit codes;
- reading the owner constants, cross-checked against the imported Python owners, with refusals for
  absent, duplicated and non-literal constants;
- the release-scan and receipt-name pins;
- value, string-token and release-scan counting against independent recursive reference
  implementations;
- the field census's exact reconciliation;
- malformed, partial, missing and non-canonical inputs failing closed;
- the census refusal path, projection receipt aggregates, the projection-tree fallback and a
  corrupt gzip;
- GNU time and meminfo parsing, and RSS and disk walls;
- the trend arithmetic, the 30-row history and one row per run;
- the missing and malformed baseline paths;
- two end-to-end runs, the second using the first's record as its baseline;
- the workflow wiring.

The tests were written and statically checked, but not run locally (owner rule). The hosted
Master reference job runs them.

## Measured on the first hosted run

Hosted Master reference run `37996600752`, job `114044161386`, on PR #635's tested merge of head
`54149d65` (W63 plus W64-0 on main `ddac90e3`). Every step passed. The guard measured all 45 walls
(0 unmeasured) and reported **WARN**: 3 walls from 85 % to below 95 %, none at 95 % or above. The
field census reconciled byte for byte on every chunk. The guard step took 62 s, and the trend
reported "no baseline", as expected before the first `main` record exists. The 71 new test items
ran in the hosted pytest step: 802 items against W63's 731.

| Wall | Value | Limit | Use |
|---|---:|---:|---:|
| `release.census_bytes` | 2,155,006,513 B | 2,415,919,104 B | **89.20 % WARN** |
| `chunk_bytes.symbols` (`chunks/symbols/00000.json`) | 28,907,964 B | 33,554,432 B | **86.15 % WARN** |
| `compiler.json_string_bytes` (`chunks/source_text/00130.json`) | 7,130,756 B | 8,388,608 B | **85.00 % WARN** |
| `projection.expanded_bytes` (16,798 modules) | 1,587,685,725 B | 2,147,483,648 B | 73.93 % |
| `peak_rss.cli_build` (wall time 22:43) | 12,063,688 KiB | 16,373,448 KiB | 73.67 % |
| `chunk_bytes.source_text` | 20,823,697 B | 33,554,432 B | 62.05 % |
| `projection.compressed_bytes` | 295,391,981 B | 536,870,912 B | 55.02 % |
| `chunk_bytes.components` | 15,460,202 B | 33,554,432 B | 46.07 % |
| `disk.runner_temp` (also the workspace) | 70,704,746,496 B | 154,877,411,328 B | 45.65 % |
| `projection.module_max_expanded_bytes` (`index.mjs`) | 3,275,387 B | 8,388,608 B | 39.04 % |
| `compiler.json_values` (`chunks/symbols/00000.json`) | 727,648 | 2,000,000 | 36.38 % |
| `peak_rss.projection` (5:49) | 4,417,980 KiB | 16,373,448 KiB | 26.98 % |
| `peak_rss.compiler` (3:41) | 3,730,840 KiB | 16,373,448 KiB | 22.78 % |
| `receipt.compression.bytes` | 5,863,752 B | 33,554,432 B | 17.47 % |
| `receipt.projection.bytes` | 5,209,006 B | 33,554,432 B | 15.52 % |
| `peak_rss.npm_test` (2:14) | 1,091,100 KiB | 16,373,448 KiB | 6.66 % |

The other 29 walls are below 10 % (the `graph_nodes` and `graph_edges` groups are empty on the
hosted runner, which has no Graphify output). The job summary and the log list all 45 walls.

### What the numbers change

- **The projection is not the nearest wall.** It is at 73.9 % expanded and 55.0 % compressed,
  not the estimated 91 %. W63's scaling from the 2026-10-01 ratio overstated it. The design's
  caveat (ship W64b's projection-only part first if the projection is at 90 % or more) does not
  apply.
- **A wall nobody printed is at 85.00 %.** `build/projection/build.mjs` refuses any compiler
  string token over 8 MiB, and `cisco_toolkit/data/atlas-r1-source-bundle.json` is one
  7,130,074-byte line. Its `source_text` token is 7,130,756 B, about 1.26 MB below refusal. Growth
  of that one file, or any new single-line file over about 8 MB, refuses the projection build.
- **The symbols per-chunk wall is nearer than reported.** The largest `symbols` chunk is 28.9 MB
  (86.15 %); W63's 23.5 MB was the average.
- **The census is at 89.20 %.** It is 2,155,006,513 B, about 8.5 MB above W63's measurement on
  this stacked tree, with about 261 MB of headroom.
- **Memory.** `cli build` peaked at 11.50 GiB (73.67 % of `MemTotal`), about 0.5 % above W63's
  measurement. Wall times on this runner were about 1.8 times W63's for every step (compiler 3:41
  against 2:03, `cli build` 22:43 against 11:50), so they vary by runner. `free -b` shows 3 GiB of
  swap.

### Per-field census (input for W64b)

`lines`: 760,427 records, 1,449.0 B per record. The largest fields are:

| Field | Bytes per record |
|---|---:|
| `inputs_and_outputs` | 162.0 |
| `security_and_privacy_effect` | 91.0 |
| `unresolved_reasons` | 90.3 |
| `line_digest` | 80.0 |
| `text_digest` | 80.0 |
| `text_preview` | 67.9 |
| `semantic_entity` | 65.7 |
| `source_commit` | 58.0 |
| `file_id` | 51.0 |
| `owner` | 49.0 |
| `test_coverage_state` | 46.8 |

Record structure adds 32.0 B per record.

`symbols`: 40,484 records, 12,304.0 B per record. **`tests` alone is 39.45 % of symbol bytes
(4,854.2 B per record)**, followed by:

| Field | Share of symbol bytes |
|---|---:|
| `known_impact_if_changed` | 18.51 % |
| `callers` | 13.38 % |
| `callees` | 5.08 % |
| `data_dependencies` | 4.78 % |

The W64b design's symbol list did not include `tests`. That field is the largest single lever.

## Still unverified

- That a `main` push uploads the record and the next run reads it, with a delta and days-to
  figures. This can only be observed after merge; a PR run reports "no baseline" until then.
- The days-to figures need at least two `main` records six hours apart.
- One run is one data point; runner speed varied about 1.8 times between this run and W63's.
