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

W64a removes the first three and leaves the release family byte-identical. It does not raise the
ceiling. The ceiling is re-derived in a separate commit from the hosted peak-RSS measurement on
this head, as W63 did.

## What changed

**Intake (`release/compiler_bundle.py`).** `load_compiler_bundle` still reads, scans and
validates every chunk of every group in sorted order, with every check unchanged. Retention now
only decides what the returned bundle keeps:

- The groups the cross-group validators read are held in full during validation, whether the
  caller retains them or not (`_VALIDATION_RECORD_GROUPS`, line 303). These are `files`,
  `symbols`, `structural_entities`, `routes`, `components`, `binaries`, `claims`,
  `consequential_claim_facets` and the two graph groups.
- `lines` is reduced to one mapping tuple per record: path, line, semantic entity, mapping basis,
  file id and explanation depth, each exactly as `item.get` returned it. Repeated strings share one
  object (lines 1865-1876).
- `source_text` is reduced to one custody tuple per record: path, source basis, blob, digest and
  byte count. It also keeps the full records of the fixed validator paths, which are the
  consequential-claim contract, its content paths and the binary-review receipt
  (`_SOURCE_TEXT_VALIDATION_PATHS`, line 320; lines 1877-1892).
- Every stable ID of every group enters one global set (lines 1856-1862).
- Each chunk's bytes and parse are released before the next chunk is read (line 1895).
- A group that is not retained raises if it is read through `bundle.records`. It never reads as
  empty: `RetainedRecords`, line 1359.
- `CompilerBundle.iter_records(group)` (line 1421) re-reads a group from disk through
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
| Exhaustive privacy scan of every chunk byte, refusing rather than sampling | `compiler_bundle.py:1797-1819`, unchanged except that the decoded text is now a temporary instead of a local |
| Exhaustive privacy scan of every identity-depth blob | `compiler_bundle.py:509-572`, `1967` |
| Receipt check before parsing: path, bytes, SHA-256, canonical bytes | `_receipt_json`, `compiler_bundle.py:1484-1526` |
| Re-reads re-verify the receipt | `iter_records` 1421; preservation `VerifiedFile.read` (`model.py:172`) at `pipeline.py:1579`, and again at every archive write (`model.py:240`) |
| Per-chunk `records_digest` | `compiler_bundle.py:1853` |
| Group digest and strictly ascending IDs | `compiler_bundle.py:1898-1901` |
| Global ID uniqueness across all 23 groups, retained or not | set at 1859-1862, refused at 1935 with the same message, at the same point (after the graph checks) |
| Canonical packing | `compiler_bundle.py:1761-1788` |
| Envelope, key fence, tracked schema | `compiler_bundle.py:1820-1840` |
| Structural denominators | `compiler_bundle.py:1701-1717` |
| `source_text` custody, for every record | `compiler_bundle.py:1974-1986`, over the custody tuples |
| Structural roots | `compiler_bundle.py:2003-2069` |
| GUI dossiers | `compiler_bundle.py:2071-2090` |
| Line mapping | `compiler_bundle.py:2092-2125`, over the mapping tuples |
| Exact source before, after and at the end | `pipeline.py:1711`, `2149`, `2242` |
| Full validation before the output directory exists | load at `pipeline.py:1704`, preservation verify pass at `1979`, `prepare_output` at `1984` |
| Preservation allowlist equals the validated inputs | `pipeline.py:1569` |
| Byte-identical ZIPs and bundle receipts | `model.py:216-274`; `_bundle_receipt` `pipeline.py:1584` (`entry_receipt` gives the same row for both entry kinds) |
| Generated-text scan | `_artifact`, `pipeline.py:1074`, unchanged for every text member. ZIPs keep the "binary container not content scanned" label. |

Two refusals changed shape and say so:

- `"retained compiler groups omit records required for structural denominator validation"` is
  gone. Validation no longer depends on retention, so there is nothing for it to guard. No test
  asserted it.
- The per-record `"compiler {group} record lacks a stable id"` branch of the uniqueness loop could
  not be reached. Every ID is first proven a non-empty string by its chunk's check (lines
  1841-1852), so it was removed along with the loop.

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

## Workflow (temporary)

One step was added after the capacity guard: "Prove the streamed family equals the pre-W64a build".
It extracts the pre-W64a `master-reference/` at `2ac65468` with `git archive`, runs its `cli build`
on the same compiler output, prints both peak RSS lines, and requires `diff -r` of the two families
to be empty. That gives the at-scale byte-identity proof and a same-runner RSS baseline in one
job. The follow-up ceiling commit removes the step.

## Measured on the hosted run

Pending.
