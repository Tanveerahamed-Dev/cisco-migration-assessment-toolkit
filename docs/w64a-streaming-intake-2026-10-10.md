# W64a master-reference streaming release intake

Branch `claude/w64a-streaming-intake`, cut from the W64-0 head `2ac65468`
(`claude/w64-capacity-guard`, PR #635), so the capacity guard and its workflow wiring are present.
No local compiler, `cli build`, pytest, npm or other build ran, because the owner's rule is
GitHub-hosted only. Locally there were only static checks (in-memory compilation, ruff with the
workflow's path set, an AST collection scan) and one pure-function probe: on synthetic entries, the
streamed ZIP equals the original in-memory `deterministic_zip` byte for byte.

## Why

On the final W64-0 head (Master reference run `38004875653`), the release census was
2,155,136,802 B, 89.2 % of the 2.25 GiB `_MAX_COMPILER_CHUNK_BYTES`, and `cli build` peaked at
12.06 GB RSS, 73.7 % of the 16 GB runner. The census ceiling exists only to bound `cli build`
memory. That memory was about 5.7 times the census for four reasons:

1. `load_compiler_bundle` kept the parsed records of all 23 groups.
2. `_compiler_preservation_entries` re-read every chunk into memory and kept it to the end.
3. Both ZIPs were built in memory and then copied.
4. The symbol index is serialised as one string.

W64a removes the first three and leaves the release family byte-identical. The first commit kept
the ceiling. A second commit re-derives it from that commit's hosted peak-RSS measurement, as W63
did (see "Measured on the hosted run").

## What changed

**Intake (`release/compiler_bundle.py`).** `load_compiler_bundle` still reads, scans and
validates every chunk of every group in sorted order, with every check unchanged. Retention now
only decides what the returned bundle keeps:

- The groups the cross-group validators read are held in full during validation, whether the
  caller retains them or not (`_VALIDATION_RECORD_GROUPS`, line 305). These are `files`,
  `symbols`, `structural_entities`, `routes`, `components`, `binaries`, `claims`,
  `consequential_claim_facets` and the two graph groups.
- `lines` is reduced to one mapping tuple per record: path, line, semantic entity, mapping basis,
  file id and explanation depth, each exactly as `item.get` returned it. Repeated strings share one
  object (lines 1867-1878).
- `source_text` is reduced to one custody tuple per record: path, source basis, blob, digest and
  byte count. It also keeps the full records of the fixed validator paths, which are the
  consequential-claim contract, its content paths and the binary-review receipt
  (`_SOURCE_TEXT_VALIDATION_PATHS`, line 322; lines 1879-1894).
- Every stable ID of every group enters one global set (lines 1858-1864).
- Each chunk's bytes and parse are released before the next chunk is read (line 1897).
- A group that is not retained raises if it is read through `bundle.records`. It never reads as
  empty: `RetainedRecords`, line 1361.
- `CompilerBundle.iter_records(group)` (line 1423) re-reads a group from disk through
  `_receipt_json`. That re-checks the canonical path with no symlink component, the bytes, the
  SHA-256 and the canonical JSON bytes, against a snapshot of the receipts taken at intake rather
  than the mutable manifest dictionary.

**Pipeline (`release/pipeline.py`).** `build_release` loads with `RELEASE_RETAINED_GROUPS`
(line 88), the groups the builders read:

- `files`: `validate_exact_source`, `read_bound_source_blob`, `_dependency_sources`,
  `_bind_tracked_inputs`, `source_symbol_index` and the PDF's tracked-file row;
- `symbols`, `routes`, `components`, `tests`, `workflows`, `datasets` and `binaries`:
  `source_symbol_index`;
- `consequential_claim_facets`: the three rendered-sink lineages.

This map was checked against the code, and it differs from the design's list.
`structural_entities` and the graph groups are read only by validators, which hold them anyway. A
test scans every literal `bundle.records` read in `release/` against this list.

Preservation and packaging:

- `_compiler_preservation_entries` (line 1549) is now one streaming verify pass before
  `prepare_output`. It keeps the same allowlist check and the same two refusals. Each input becomes
  a `VerifiedFile` receipt instead of bytes.
- The generated members are verified the same way by `verified_output_entries`.
- Both ZIPs are written by `_zip_artifact` (line 1092), entry by entry, straight to disk. Each
  entry is re-read and re-checked against its receipt as it is written.

**Archive writer (`release/model.py`).** `deterministic_zip` and `write_deterministic_zip` share
one writer, `_write_deterministic_zip` (line 216). The order, timestamps, permissions, flags,
compression and `writestr` call are unchanged, so the bytes do not depend on whether the
destination is memory or a file.

**PDF (`release/pdf_report.py`).** The "Source line records" fallback now uses the validated
manifest `record_count` (`_manifest_line_record_count`, line 1994) instead of
`len(records["lines"])`. The value is the same, because intake proves the two equal.

**Not done: streaming the symbol index (optional item 4).** It would remove the last
census-proportional transient, the one-string `canonical_json(index)` and its scan. It is
deferred until the hosted measurement shows whether it matters. Doing it needs its own proof that
a per-record forbidden-content scan (`atlas_privacy.py:14-21`) and the canonical assembly are
equivalent.

## Invariants kept

Line numbers refer to this head.

| Invariant | Where it holds |
|---|---|
| Exhaustive privacy scan of every chunk byte, refusing rather than sampling | `compiler_bundle.py:1799-1821`, unchanged except that the decoded text is now a temporary instead of a local |
| Exhaustive privacy scan of every identity-depth blob | `compiler_bundle.py:511-574`, `1969` |
| Receipt check before parsing: path, bytes, SHA-256, canonical bytes | `_receipt_json`, `compiler_bundle.py:1486-1528` |
| Re-reads re-verify the receipt | `iter_records` (`compiler_bundle.py:1423`); preservation `VerifiedFile.read` (`model.py:172`) at `pipeline.py:1579`, and again at every archive write (`model.py:240`) |
| Per-chunk `records_digest` | `compiler_bundle.py:1855` |
| Group digest and strictly ascending IDs | `compiler_bundle.py:1900-1903` |
| Global ID uniqueness across all 23 groups, retained or not | set at 1861-1864, refused at 1937 with the same message, at the same point (after the graph checks) |
| Canonical packing | `compiler_bundle.py:1763-1790` |
| Envelope, key fence, tracked schema | `compiler_bundle.py:1822-1842` |
| Structural denominators | `compiler_bundle.py:1703-1719` |
| `source_text` custody, for every record | `compiler_bundle.py:1976-1988`, over the custody tuples |
| Structural roots | `compiler_bundle.py:2005-2071` |
| GUI dossiers | `compiler_bundle.py:2073-2092` |
| Line mapping | `compiler_bundle.py:2094-2127`, over the mapping tuples |
| Exact source before, after and at the end | `pipeline.py:1711`, `2149`, `2242` |
| Full validation before the output directory exists | load at `pipeline.py:1704`, preservation verify pass at `1979`, `prepare_output` at `1984` |
| Preservation allowlist equals the validated inputs | `pipeline.py:1569` |
| Byte-identical ZIPs and bundle receipts | `model.py:216-281`; `_bundle_receipt` `pipeline.py:1584` (`entry_receipt` gives the same row for both entry kinds) |
| Generated-text scan | `_artifact`, `pipeline.py:1074`, unchanged for every text member. ZIPs keep the "binary container not content scanned" label. |

Two refusals changed shape and say so:

- `"retained compiler groups omit records required for structural denominator validation"` is
  gone. Validation no longer depends on retention, so there is nothing for it to guard. No test
  asserted it.
- The per-record `"compiler {group} record lacks a stable id"` branch of the uniqueness loop could
  not be reached. Every ID is first proven a non-empty string by its chunk's check (lines
  1843-1854), so it was removed along with the loop.

Uniqueness is now stricter for a caller that retains a subset: it spans every group. Before, it
spanned only the retained ones. For the default "retain all" callers (continuity,
`verify-claim-review`, the standalone PDF) it is unchanged.

A chunk changed after intake was refused only before preservation. It is now also refused while
packaging and on `iter_records`, where the in-memory path would have packed the earlier verified
bytes.

## Tests

`master-reference/tests/release/test_streaming_intake.py`:

- **Byte identity.** Each of four fixtures builds the family twice and requires every member,
  every receipt and the census to be equal. One build is streamed. The other is the pre-W64a path,
  reproduced verbatim as an oracle: all groups retained, preservation and archives in memory. The
  fixtures are synthetic, synthetic re-chunked at 64, synthetic with the generated PDF, and the real
  compiler on the declared-claim repository with the generated PDF. Each streamed ZIP must equal
  the verbatim original `deterministic_zip` over its own entries, its bundle receipt must match its
  entries, and its compiler entries must equal the compiler output.
- **Streamed ZIP.** The streamed ZIP equals the original `deterministic_zip` for in-memory and file
  entries: empty, repetitive, 3 MiB incompressible, and a non-ASCII name. It refuses an existing
  target, an entry changed after verification, and a missing entry.
- **Retention boundary.** Retained groups and the census are equal to "retain all". Every group's
  `iter_records` equals its full records. Every streamed group raises on `[]` and `.get`. The PDF
  count comes from the manifest.
- **Changed chunk.** A chunk changed after intake is refused before any output exists. A chunk
  changed after the verify pass is refused while packaging. `iter_records` refuses a changed or
  missing chunk, and it ignores a tampered manifest dictionary.
- **Exact refusal messages.** Six refusals on streamed groups give the same exact message in both
  retention modes and through `build_release`: a duplicate line coordinate, an unmapped line, the
  line chunk digest, a non-canonical line chunk, the line chunk receipt, and `source_text` custody.
  A consistent `source_text` record on a non-validator path is the positive control.
- **Duplicate IDs.** Three duplicates are refused in both modes: inside `lines`, between `lines`
  and `structured` (neither retained nor a validator group, so only the global set can see it), and
  between `lines` and `structural_entities`.
- **Memory.** The test doubles the line bytes, with the doubling measured from the receipts, and
  compares tracemalloc peaks. The streamed intake peak must move by less than 10 %. The control,
  "retain everything", must grow by more than that same 10 %, so the bound has teeth.
- **Consumer map.** Every literal `bundle.records` read in `release/` must be a retained group,
  except the PDF's documented partial-bundle fallback.

## Workflow (temporary, now removed)

The first commit (`44883b07`) added one step after the capacity guard: "Prove the streamed family
equals the pre-W64a build". It extracted the pre-W64a `master-reference/` at `2ac65468` with
`git archive`, ran its `cli build` on the same compiler output, printed both peak RSS lines, and
required `diff -r` of the two families to be empty. The ceiling commit removes it, so the workflow
is again exactly W64-0's.

An independent review noted that the step mixed the legacy `master-reference/` code with the
workspace's `release/schemas/`. It was sound for this run only because the PR merge tree equals
`2ac65468` outside the W64a files. A future A/B should archive `HEAD` and overlay only the changed
files from the old commit.

## Measured on the hosted run

Master reference run `38011273370` (job `114091608712`) tested the PR merge of `44883b07`. Every step
passed, the CI, webapp and portable workflows also passed, and the hosted pytest step ran 823
items (W64-0: 802), with 0 failures and 1 skip.

| Measure | W64-0 baseline (run `38004875653`) | W64a streamed | Pre-W64a code, same runner, same input |
|---|---:|---:|---:|
| `cli build` peak RSS | 12.06 GB (73.7 %) | **6,093,292 KiB, 5.81 GiB (37.21 % of `MemTotal`)** | 12,122,188 KiB, 11.56 GiB |
| Ratio to the census | 5.6x | **2.89x** | 5.74x |
| `cli build` wall time | 22:43 | 22:26 | 22:51 |
| Release census | 2,155,136,802 B | 2,161,159,133 B (89.45 % WARN at 2.25 GiB) | same input |

- **Byte identity at full scale.** `diff -r` of the streamed and pre-W64a families was empty.
  Both `release-manifest.json` files have SHA-256 `2d1d080fcf65d21d61ff21d8ffe38d5440c6fb4cbd730482e15633830e7fd74a`,
  so every artifact receipt is equal.
- **Peak RSS** dropped 49.7 % against the same-runner pre-W64a build, and 49.5 % against the W64-0
  baseline.
- **Wall time** did not change. The build is dominated by validation, serialisation and
  compression, not by memory.
- **Guard.** It measured all 45 walls: WARN on 3 (the census at 89.45 %, the largest `symbols`
  chunk at 86.46 %, the 8 MiB string token at 85.00 %), 0 at 95 % or above, 0 unmeasured.

### The re-derived ceiling: 3 GiB

`_MAX_COMPILER_CHUNK_BYTES` becomes 3,221,225,472 B (`3072 * 1024 * 1024`). Today's census is
67.09 % of it, with 1,060,066,339 B of headroom. W63's budget was a predicted peak of about
12.9 GiB of the runner's 15.61 GiB `MemTotal`. Two models predict the peak at the new ceiling:

- **The whole peak scales with the census** (2.89x measured): about 8.66 GiB, 55.5 % of `MemTotal`.
- **Worst case: every added byte is a retained `symbols` byte.** Such a byte is parsed (about 3x)
  and serialised again for the symbol index (string, bytes and scan copy, about 3-4x), so about 7x:
  5.81 GiB + 7 x 0.99 GiB, about 12.72 GiB, 81.5 % of `MemTotal`.

Both stay within W63's budget. (W63's 5.7x had predicted 17.2 GiB at 3 GiB.) The ceiling is no
longer the nearest wall. By W64-0's ratio the projection's 2 GiB expanded bound (73.93 %) refuses
first, at a census of about 2.9 GB, and the `symbols` per-chunk bound (86.46 %) sooner still.
W64b's compaction owns both.

### Residuals (independent review, recorded rather than changed)

- **What still scales with the census.** Memory is now independent of per-record *payload* bytes
  in the streamed groups. It still grows with record *count*: the global ID set, the per-line
  tuples, `combined_ids` and its digest. It also grows with the retained `symbols` and the
  one-string symbol index (item 4).
- **`RetainedRecords` refuses only some reads.** It refuses `records[g]` and `.get(g)`. Iteration,
  `in`, `keys()` and `items()` list only the retained groups, which is honest for those groups. A
  caller must not read the absence of a group there as "empty". The consumer-map test scans
  literal reads only.
- **`_read_bounded_owner_bytes` asks for 32 MiB + 1 bytes on every bounded read.** The buffered
  reader allocates that up front, so each chunk read carries a transient 32 MiB. It is bounded and
  freed per chunk, and it is unchanged by W64a.
- **`write_deterministic_zip` now removes its own partial archive** when an entry is refused. Within
  `build_release`, the staging cleanup already did this.
