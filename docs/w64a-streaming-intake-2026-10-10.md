# W64a master-reference streaming release intake

Branch `claude/w64a-streaming-intake`, cut from the W64-0 head `2ac65468`
(`claude/w64-capacity-guard`, PR #635, since merged as `ffc269f1`). No local compiler, `cli build`,
pytest, npm or other build ran, because the owner's rule is GitHub-hosted only. Locally there were
only static checks (in-memory compilation, ruff with the workflow's path set, an AST collection
scan) and pure-function probes on synthetic input:

- the streamed ZIP equals the original in-memory `deterministic_zip`;
- the piecewise canonical JSON equals the one-shot form over 3,000 random values, including astral
  and control characters;
- the bounded privacy scan returns exactly the whole-text findings over 4,000 adversarial texts
  with random slice and piece sizes;
- the traced peaks of one-shot and streamed serialization of an astral-character document.

## Why

On the final W64-0 head (Master reference run `38004875653`), the release census was
2,155,136,802 B, 89.2 % of the 2.25 GiB `_MAX_COMPILER_CHUNK_BYTES`, and `cli build` peaked at
12.06 GB RSS, 73.7 % of the 16 GB runner. The census ceiling exists only to bound `cli build`
memory. That memory was about 5.7 times the census for four reasons:

1. `load_compiler_bundle` kept the parsed records of all 23 groups.
2. `_compiler_preservation_entries` re-read every chunk into memory and kept it to the end.
3. Both ZIPs were built in memory and then copied.
4. The symbol index was serialised as one string, then decoded again as one string for the
   privacy scan.

The first round removed the first three. Round 2 removes the fourth. Both keep the release family
byte-identical.

## What changed

**Intake (`release/compiler_bundle.py`).** `load_compiler_bundle` still reads, scans and
validates every chunk of every group in sorted order, with every check unchanged. Retention now
only decides what the returned bundle keeps:

- **Validator groups.** The groups the cross-group validators read are held in full during
  validation, whether the caller retains them or not (`_VALIDATION_RECORD_GROUPS`, line 319). These
  are `files`, `symbols`, `structural_entities`, `routes`, `components`, `binaries`, `claims`,
  `consequential_claim_facets` and the two graph groups.
- **Guarded reads.** The validators read them through `_ValidatorRecords` (line 1379), which raises
  on any group it does not hold, so a group that is not held can never read as empty. A test scans
  every literal validator read against the held set.
- **`lines`** is reduced to one mapping tuple per record: path, line, semantic entity, mapping
  basis, file id and explanation depth, each exactly as `item.get` returned it. Repeated strings
  share one object (lines 1925-1936).
- **`source_text`** is reduced to one custody tuple per record: path, source basis, blob, digest and
  byte count. It also keeps the full records of the fixed validator paths, which are the
  consequential-claim contract, its content paths and the binary-review receipt
  (`_SOURCE_TEXT_VALIDATION_PATHS`, line 336; lines 1937-1952). Those records are passed to the
  two validators that read them explicitly, as `validator_source_texts` (lines 2056 and 2065). They
  never stand in for the whole group under its name.
- **Stable IDs.** Every stable ID of every group enters one global set (lines 1919-1922).
- **One chunk at a time.** Each chunk's bytes and parse are released before the next chunk is
  read (line 1955).
- **Unretained groups.** A group that is not retained raises if it is read through
  `bundle.records`. It never reads as empty: `RetainedRecords`, line 1401.
- **`CompilerBundle.iter_records(group)`** (line 1471) re-reads a group from disk through
  `_receipt_json`. That re-checks the canonical path with no symlink component, the bytes, the
  SHA-256 and the canonical JSON bytes, against the intake snapshot.
- **The intake snapshot** is read-only (`MappingProxyType`). It holds `chunk_receipts`,
  `input_receipts` (every validated input except the manifest) and the exact manifest bytes,
  `manifest_raw` (lines 2207-2230).
- **New refusal.** A ledger that declares `parsing.line_records` different from the `lines` group's
  `record_count` is refused: "compiler completeness line-record count differs from the line group"
  (line 1762). The PDF renders that value. This predates W64a.

**Pipeline (`release/pipeline.py`).** `build_release` loads with `RELEASE_RETAINED_GROUPS`
(line 91), the groups the builders read:

- `files`: `validate_exact_source`, `read_bound_source_blob`, `_dependency_sources`,
  `_bind_tracked_inputs`, `source_symbol_index` and the PDF's tracked-file row;
- `symbols`, `routes`, `components`, `tests`, `workflows`, `datasets` and `binaries`:
  `source_symbol_index`;
- `consequential_claim_facets`: the three rendered-sink lineages.

This map was checked against the code, and it differs from the design's list.
`structural_entities` and the graph groups are read only by validators, which hold them anyway. A
test scans every literal `bundle.records` read in `release/` against this list.

**Preservation and packaging:**

- `_compiler_preservation_entries` (line 1612) is one streaming verify pass before
  `prepare_output`. It keeps the same allowlist check and the same two refusals.
  - It binds to the intake snapshot: the manifest entry is `manifest_raw`, and every other input is
    checked against `input_receipts`, never against the mutable manifest dictionary.
  - Each input becomes a `VerifiedFile` receipt instead of bytes.
- `VerifiedFile.read` (`model.py:205`) refuses a size that differs from its receipt before reading
  any byte. It then reads at most `byte_count + 1` bytes, requires a stable size and mtime, and
  checks the SHA-256.
- The generated members are verified the same way by `verified_output_entries`.
- **ZIPs.** Both are written by `_zip_artifact` (line 1155), entry by entry, straight to disk
  through one `xb+` handle (`model.py:329`).
  - That same handle then computes the receipt.
  - It re-reads every member against its entry's name, byte count and SHA-256
    (`_verify_written_archive`, `model.py:300`), so no file can be substituted between writing and
    hashing.
  - A failure removes only the partial file this call created, and a failure during that cleanup
    never masks the original refusal.
- **Symbol index (round 2, design item 4).** It is written by `_streamed_json_artifact` (line 1099):
  - `canonical_json_text_pieces` (`model.py:42`) yields the canonical text one top-level member
    key, and one list element, at a time;
  - each piece is scanned, hashed and written before the next exists;
  - the bytes, the refusal message and the artifact row equal `_artifact`'s on
    `canonical_json(index)`.

**Bounded privacy scan (`atlas_privacy.py`).** `ForbiddenContentScan` (line 99) scans text
supplied in pieces. `forbidden_byte_findings` (line 164) now decodes its bytes in 8 MiB slices
instead of as one string.

The proof of equivalence:

- A segment boundary is placed only immediately after one of `\n " { } [ ] , :`
  (`_SCAN_SEGMENT_SEPARATORS`, line 80).
- None of the six reviewed rules can match any of these characters, and none of them is a regular
  expression word character. So no match can straddle a boundary, and every `\b` sees the same
  character class on both sides.
- Byte slices end immediately after an ASCII byte, where a UTF-8 decoder is always between
  characters, including with `errors="ignore"`.
- Findings are collected rule by rule in text order, with the same line numbers as before.
- The proof holds for exactly the reviewed rule sources pinned beside the separators. If the rules
  change, segmenting switches off (`_segmenting_reviewed`, line 92) and the whole text is buffered
  and scanned once, as before.

**Canonical JSON (`model.py:35`).** `canonical_json` now encodes and then appends `b"\n"`. The
bytes are the same.

**Measured: this alone does not lower the peak.** A probe on Python 3.12 shows that the one-shot
encoder itself already holds about 8 bytes per output byte for an astral-character document: its
accumulated text plus the join, at 4 bytes per character. Only streaming the index removes that
term. Measured on an 8.5 MB synthetic index:

| Form | Traced peak per output byte |
|---|---:|
| One-shot, pre-W64a | 7.99 |
| One-shot, round 2 | 7.99 |
| Streamed | 0.005 |

**PDF (`release/pdf_report.py`).** The "Source line records" fallback uses the validated manifest
`record_count` (`_manifest_line_record_count`, line 1994) instead of `len(records["lines"])`.
Intake proves the two equal.

## Invariants kept

Line numbers refer to this head.

| Invariant | Where it holds |
|---|---|
| Exhaustive privacy scan of every chunk byte, refusing rather than sampling | `compiler_bundle.py:1856-1879`, unchanged except that the decoded text is now a temporary instead of a local |
| Exhaustive privacy scan of every identity-depth blob | `compiler_bundle.py:525-588`, `2029` |
| Receipt check before parsing: path, bytes, SHA-256, canonical bytes | `_receipt_json`, `compiler_bundle.py:1534-1576` |
| Re-reads re-verify the receipt | `iter_records` (`compiler_bundle.py:1471`); preservation `VerifiedFile.read` (`model.py:205`) at `pipeline.py:1640`, again at every archive write (`model.py:287`), and every written member re-read (`model.py:300`) |
| Per-chunk `records_digest` | `compiler_bundle.py:1913` |
| Group digest and strictly ascending IDs | `compiler_bundle.py:1956-1961` |
| Global ID uniqueness across all 23 groups, retained or not | set at 1919-1922; refused at 1997, after the graph checks, with the same message as before |
| Canonical packing | `compiler_bundle.py:1818-1848`, through `compiler/packing.py :: effective_chunk_size` (W64c, the one owner of per-group caps; W64a reads no chunk size of its own) |
| Envelope, key fence, tracked schema | `compiler_bundle.py:1880-1900` |
| Structural denominators | `compiler_bundle.py:1751-1774` |
| `source_text` custody, for every record | `compiler_bundle.py:2038-2048`, over the custody tuples |
| Structural roots | `compiler_bundle.py:2067-2133` |
| GUI dossiers | `compiler_bundle.py:2135-2154` |
| Line mapping | `compiler_bundle.py:2156-2189`, over the mapping tuples |
| Exact source before, after and at the end | `pipeline.py:1772`, `2210`, `2303` |
| Full validation before the output directory exists | load at `pipeline.py:1765`, preservation verify pass at `2040`, `prepare_output` at `2045` |
| Preservation allowlist equals the validated inputs | `pipeline.py:1630`, now over the intake snapshot |
| Byte-identical ZIPs and bundle receipts | `model.py:263-369`; `_bundle_receipt` `pipeline.py:1645` (`entry_receipt` gives the same row for both entry kinds) |
| Generated-text scan | `_artifact`, `pipeline.py:1082`, for every text member (bounded, same findings); `_streamed_json_artifact`, `pipeline.py:1099`, for the symbol index. ZIPs keep the "binary container not content scanned" label. |

**Two refusals changed shape:**

- `"retained compiler groups omit records required for structural denominator validation"` is
  gone. Validation no longer depends on retention, so there is nothing for it to guard. No test
  asserted it.
- The per-record `"compiler {group} record lacks a stable id"` branch of the uniqueness loop could
  not be reached. Every ID is first proven a non-empty string by its chunk's check (lines
  1901-1912), so it was removed along with the loop.

**Stricter for a caller that retains a subset of groups:**

- **Uniqueness** now spans every group. Before, it spanned only the retained ones.
- **Graph validation** (`_validate_graph_projection`, line 591, and the Graphify local-identity
  scan) now always reads the real `graph_nodes` and `graph_edges` records. Before, a caller that
  did not retain them was validated against `[]`.
- **Unchanged for the default "retain all" callers:** continuity, `verify-claim-review` and the
  standalone PDF.

A chunk changed after intake was refused only before preservation. It is now also refused while
packaging and on `iter_records`, where the in-memory path would have packed the earlier verified
bytes.

## Tests

`master-reference/tests/release/test_streaming_intake.py`:

- **Byte identity.** Each of five fixtures builds the family twice and requires every member,
  every receipt and the census to be equal.
  - **Fixtures:** synthetic; synthetic re-chunked at 64; synthetic with an astral character in an
    indexed record; synthetic with the generated PDF; and the real compiler on the declared-claim
    repository with the generated PDF.
  - **The oracle and its scope.** One build is streamed. The other is the oracle, which replaces
    every packaging and serialization function W64a changed with a verbatim pre-W64a copy:
    canonical JSON, the generated-output scan, preservation, bundle receipts, the ZIPs and the
    one-shot symbol index. Its intake, though, is W64a's own `load_compiler_bundle` with every
    group retained. So the oracle proves the family does not depend on retention or streaming. It
    does not prove the intake equals the pre-W64a intake. The workflow's A/B step proves that at
    full scale, and the exact-message cases prove it for refusals.
  - Each streamed ZIP must equal the verbatim original `deterministic_zip` over its own entries, and
    its bundle receipt and compiler entries must match.
- **Index multiplier pin.** On an 8.5 MB astral-character index:
  - one-shot `canonical_json` (round 2 and pre-W64a) peaks between 4 and 10 bytes per output byte;
  - the streamed artifact peaks below a quarter of a byte per output byte;
  - the streamed artifact's bytes and row equal `_artifact`'s;
  - a refused streamed document gives the one-shot message, leaves no file, and is not masked by a
    failing cleanup.
- **Bounded scan.** Over 2,000 adversarial texts (secrets with separators spliced in, astral and
  invalid bytes, random slice and piece sizes), the slice and piece scans equal the verbatim
  whole-text scan. An unreviewed rule that can match a separator switches segmenting off and is
  still found across a piece boundary.
- **Streamed ZIP.** The streamed ZIP equals the original `deterministic_zip` for in-memory and file
  entries. It refuses an existing target, an entry changed after verification (removing its
  partial file) and a missing entry. A `VerifiedFile` of the wrong size is refused without being
  opened. A written archive whose members differ from its entries, or which is truncated, is
  refused.
- **Retention boundary.** Retained groups and the census are equal to "retain all". Every group's
  `iter_records` equals its full records. Every streamed group raises on `[]` and `.get`. The PDF
  count comes from the manifest.
- **Changed chunk.** A chunk changed after intake is refused before any output exists. A chunk
  changed after the verify pass is refused while packaging. `iter_records` refuses a changed or
  missing chunk and ignores a tampered manifest dictionary.
- **Preservation snapshot.** It ignores a tampered manifest dictionary. The snapshot is read-only.
- **Exact refusal messages.** Six refusals on streamed groups keep their exact message in both
  retention modes and through `build_release`, with a positive control. A declared `line_records`
  that differs from the line group (larger, smaller, a string or a boolean) is refused in both
  modes.
- **Duplicate IDs.** Three duplicates are refused in both modes: inside `lines`, between `lines`
  and `structured`, and between `lines` and `structural_entities`.
- **Memory.** Doubling the line bytes moves the streamed intake's traced peak by less than 10 %. The
  retain-everything control grows past that bound.
- **Consumer maps.**
  - Every literal `bundle.records` read in `release/` must be a retained group, except the PDF's
    documented partial-bundle fallback.
  - Every literal validator `records` read in `compiler_bundle.py` must be a held group. Neither
    `source_text` nor `lines` may be among them.
  - `_ValidatorRecords` raises on any group it does not hold.

## Workflow (temporary A/B step)

The first commit (`44883b07`) added a step after the capacity guard: "Prove the streamed family
equals the pre-W64a build". It ran the pre-W64a `cli build` on the same compiler output and
required `diff -r` of the two families to be empty. The 3 GiB commit removed it.

Round 2 re-adds it in the shape the independent review asked for. It extracts this head's
`master-reference/` with `git archive` and overlays only main's version (`2c927d02`: W64c's packing,
no W64a) of each production file W64a changes:

- `atlas_privacy.py`
- `release/compiler_bundle.py`
- `release/model.py`
- `release/pipeline.py`
- `release/pdf_report.py`

It then required byte identity again, and passed on run `38040021909`. The follow-up commit
removes the step, so the workflow again equals main's, apart from the corrected comment (it had
said `cli build` holds every compiler record in memory).

## Measured on the hosted runs

### Round 1 (run `38011273370`, head `44883b07`)

Every step passed, and the CI, webapp and portable workflows also passed. The hosted pytest step ran
823 items (W64-0: 802), with 0 failures and 1 skip.

| Measure | W64-0 baseline (run `38004875653`) | W64a round 1 | Pre-W64a code, same runner, same input |
|---|---:|---:|---:|
| `cli build` peak RSS | 12.06 GB (73.7 %) | **6,093,292 KiB, 5.81 GiB (37.21 % of `MemTotal`)** | 12,122,188 KiB, 11.56 GiB |
| Ratio to the census | 5.6x | **2.89x** | 5.74x |
| `cli build` wall time | 22:43 | 22:26 | 22:51 |
| Release census | 2,155,136,802 B | 2,161,159,133 B (89.45 % WARN at 2.25 GiB) | same input |

- **Byte identity at full scale.** `diff -r` was empty. Both `release-manifest.json` files have
  SHA-256 `2d1d080fcf65d21d61ff21d8ffe38d5440c6fb4cbd730482e15633830e7fd74a`.
- **Final round-1 head.** On `589ddb82` (main `ffc269f1` merged in, 3 GiB ceiling, run
  `38027702426`), `cli build` peaked at 6,169,688 KiB (37.68 %), with a census of
  2,176,891,984 B.

### The ceiling: 3 GiB withdrawn, 2,720 MiB set

Round 1 set 3 GiB from a model that charged an added retained `symbols` byte about 7x. An
independent max-effort refutation showed that marginal is about 10.3 to 10.9x:

- about 2.27x for the parsed record;
- about 8x for the one-shot symbol index, because the encoder holds two copies of a text that is 4
  bytes per character. The real index carries U+1F4A3 from a parametrize decorator in
  `tests/release/test_pdf_report.py`, which `ast.unparse` writes literally into `decorators`.

That model reconciles both hosted peaks (6.24 GB streamed and 12.41 GB pre-W64a). Under it,
symbols-heavy growth exceeds `MemTotal` below a 3 GiB census, which would be exhaustion before
refusal, W63's failure.

The round-2 ceiling is set from that corrected multiplier. It is a **model estimate**, not a
measured bound:

- 5.81 GiB + 10.9 x (C − 2.01 GiB) ≤ 12.9 GiB, W63's budget;
- so C is about 2.66 GiB: `_MAX_COMPILER_CHUNK_BYTES = 2720 * 1024 * 1024` (2,852,126,720 B,
  line 158).

It holds even without the round-2 streaming of the index. Today's 2,176,891,984-byte census is
76.3 % of it. Because round 2 removes the 8x term, the ceiling may be re-derived upward, but only
from a hosted peak-RSS measurement of the round-2 head, using W63's method.

### Round 2 (run `38040021909`, head `6f9ee887`, main `2c927d02` merged in)

Every step passed, including the temporary A/B step, and the CI, webapp and portable workflows also
passed. Pytest ran 849 items, with 0 failures and 1 skip. (The first round-2 head, `63ec357f`,
failed the compile step: the test file carried two literal private-key headers, which the
compiler's forbidden-content scan of the tree refuses. They are now assembled at run time.)

| Measure | Round 2, streamed | Pre-W64a code, same runner and input | Round 1 (`38011273370`) |
|---|---:|---:|---:|
| `cli build` peak RSS | **2,511,136 KiB, 2.39 GiB (15.33 % of `MemTotal`)** | 12,292,532 KiB, 11.72 GiB | 6,093,292 KiB |
| Ratio to the census | **1.18x** | 5.77x | 2.89x |
| `cli build` wall time | 16:33 | 16:53 | 22:26 |
| Release census | 2,183,272,402 B (76.54 % of 2,720 MiB) | same input | 2,161,159,133 B |

- **Byte identity at full scale.** `diff -r` of the streamed and pre-W64a families was empty, with
  the A/B step running main's pre-W64a files on the same compiler output. Both
  `release-manifest.json` files have SHA-256
  `edc2ecbf519a281b21f5f08726cf058cf896a2360bf60ef54a94c0d8de192deb`.
- **Peak RSS** dropped 79.6 % against the same-runner pre-W64a build, and 58.8 % against round 1.
  Streaming the symbol index removed about 3.5 GiB.
- **Guard.** It measured all 45 walls: WARN on 1 (the 8 MiB string token at 85.00 %), 0 at 95 % or
  above, 0 unmeasured. The census is at 76.54 %, the largest `symbols` chunk at 29.73 % (W64c), and
  the projection's expanded bytes at 75.14 %.

### The ceiling after round 2: 2,720 MiB kept

W63's method on the measured peak (2.39 GiB at 2.03 GiB of census) bounds the ceiling C by
2.39 GiB + m x (C − 2.03 GiB) ≤ 12.9 GiB, for a marginal cost m per added census byte:

| Marginal m | Basis | Allowed C |
|---|---|---:|
| 2.27x | retained `symbols` parse only | about 6.7 GiB |
| 4.3x | plus whole-file reads of the index | about 4.5 GiB |
| 10.9x | the superseded one-shot index model | about 3.0 GiB |

So the measurement allows a higher ceiling. It is **kept at 2,720 MiB** anyway, because the
census ceiling is no longer the nearest wall. The projection's 2 GiB expanded bound is at 75.14 %,
and by the same ratio it refuses at a census of about 2.9 GB (about 2.7 GiB). A higher census
ceiling would buy no capacity. At 2,720 MiB the predicted `cli build` peak is about 3.8 to 5.1
GiB on the measured models, and at most about 9.2 GiB even at 10.9x. Raising it belongs with
whoever moves the projection wall (W64b).

### Residuals (recorded rather than changed)

- **What still scales.** Memory is independent of per-record payload bytes in the streamed groups.
  It still grows with:
  - record count: the global ID set, the per-line tuples, `combined_ids` and its digest;
  - the retained `symbols`;
  - the full reads of the index file for hashing and for each archive entry, which are bytes, not
    4-byte text.
- **`RetainedRecords` refuses only some reads.** It refuses `records[g]` and `.get(g)`. Iteration,
  `in`, `keys()` and `items()` list only the retained groups, which is honest for those groups.
- **`_read_bounded_owner_bytes` asks for 32 MiB + 1 bytes on every bounded read.** That is a
  bounded transient, freed per chunk, and unchanged by W64a.
- **No frozen copy of the pre-W64a intake** is kept as a differential oracle (optional P3-7). The
  full-scale A/B step runs the real pre-W64a files instead.
