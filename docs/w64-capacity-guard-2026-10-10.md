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

## Unverified until the hosted run

- Every measured number. The PR's hosted job summary and `capacity.json` are the first real
  values, including the first measurement of the projection walls.
- That the field census reconciles byte for byte on the real 1.37 million records, and the guard
  step's wall time.
- That a `main` push uploads the record and the next run reads it. This can only be observed after
  merge; a PR run reports "no baseline" until then.
