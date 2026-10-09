# W44 host-independent capture bytes in the live and REST collectors (F10)

Branch `claude/f10-capture-bytes`, from `origin/main` `a06d1d27`. This is a source checkpoint. No
local test, engine run, build or reproduction was made, because the owner's rule is
GitHub-hosted only. The tests below are written, not run; every runtime verdict is pending
hosted evidence.

## The defect

Both live collectors wrote evidence in text mode without `newline=`:

- `COLLECT_PARSE_V3_23_0.py :: collect` wrote each SSH capture with
  `open(p, "w", encoding="utf-8")`.
- `cisco_toolkit/rest_collect.py :: _write` wrote each controller export the same way, through
  `json.dump(obj, f, indent=2)`.

A default text-mode write translates every `"\n"` to `os.linesep`. On a Windows collecting host
(Atlas runs there), a capture the session delivered with `"\n"` was stored with `"\r\n"`, and a
delivered `"\r\n"` was stored as `"\r\r\n"`. Nothing downstream undoes this:

- `cisco_toolkit/input_custody.py :: read_bytes` / `read_text` read the raw bytes and decode them
  with no newline translation.
- `COLLECT_PARSE_V3_23_0.py :: _evidence_records` hashes those bytes into the run's raw-evidence
  receipts (`evidence.analysis_input`: per-file size and SHA-256, plus `root_sha256`).
  `input_custody` then enforces those bindings on every parser read.
- The parsers receive the decoded raw text through `cmdio._load_cmd_output`,
  `cmdio._resolve_capture` and `detect_platform_from_files`, all of which go through
  `input_custody.read_text`.

So the receipts, and the text the parsers saw, depended on which host collected the evidence.
A Windows collection and a Linux collection of byte-identical device output carried different
receipts. This is the same class W36 (PR #625, not yet merged) fixed for the demo writer
`webapp/sample_data/build_sample.py`, and that `tests/synthetic_fixtures.py :: write_collection`
already avoids for the golden (`newline="\n"`).

## Census of evidence writers

Every writer that stores collection evidence was looked for: text-mode `open` / `os.fdopen` /
`write_text` across `COLLECT_PARSE_V3_23_0.py`, `cisco_toolkit/`, `webapp/backend/` and `portable/`.
The only two live collection code paths are `COLLECT_PARSE_V3_23_0.py` (netmiko) and
`cisco_toolkit/rest_collect.py` (urllib); no other module opens a device session or makes a
controller request.

| Writer | Writes | Before | After |
|---|---|---|---|
| `COLLECT_PARSE_V3_23_0.py :: collect` | each SSH capture `<cmd>.txt` | host translation | `newline=""` |
| `COLLECT_PARSE_V3_23_0.py :: _write_json_atomic` and the `write_json_file` in-place fallback | the capture-metadata sidecar `_capture_meta.json` (bound raw evidence: `_evidence_records` hashes it as `<capture-metadata>`); `device_info.json` and `command_index.json` beside the captures; every other JSON the engine writes | host translation | `newline=""` |
| `cisco_toolkit/rest_collect.py :: _write` | each APIC / vManage / ISE / FMC export, including ISE's consolidated ERS export and FMC's merged pages | host translation | `newline=""` |
| `cisco_toolkit/html.py :: redact_collection_dir` | the in-place secret scrub of the captures | already `newline=""` on read and write | unchanged (the precedent) |
| `webapp/backend/ingest.py :: _safe_extract` and the staging copy | uploaded collections | binary (`"xb"`, `write_bytes`) | unchanged |
| `tests/synthetic_fixtures.py :: write_collection` | the golden collection | already `newline="\n"` | unchanged |
| `webapp/sample_data/build_sample.py :: _write_collection` | the demo collection | host translation | owned by W36 / PR #625; not touched here |

Out of scope, checked and left as they are:

- `portable/qualify_atlas.py :: _redaction` writes a synthetic canary collection with
  `write_text`. It is release-qualification input, not collected evidence. That check asserts the
  canaries are absent from the redacted output, and no capture digest is compared.
- Deliverable writers (`html.py` explorer, `excel.py` diagram text, `nrfu_export.py`,
  `precert.py`) and the engagement/telemetry stores (`gate_state.py`, `holdout.py`, `recall.py`,
  `retrieval_eval.py`, `scorecard.py`, `clock.py`) write outputs, not collected evidence. Their
  host-dependent line endings are a separate class: deliverable reproducibility across hosts. The
  engine's own reader of the explorer's embedded receipt already accepts `\r?\n`
  (`COLLECT_PARSE_V3_23_0.py`, the `EMBEDDED_PROTOCOL_ASSURANCE` / `EMBEDDED_SNAPSHOT` block
  pattern).

## Decision: `newline=""`

For a write, `newline=""` and `newline="\n"` behave identically: neither translates. `""` was
chosen for three reasons:

- It states the contract, "store what was delivered, untranslated". `"\n"` reads like LF
  normalisation, which it does not perform: a delivered `"\r\n"` is stored as `"\r\n"` either
  way.
- It is the rule `redact_collection_dir` already applies when it rewrites these same files.
- It keeps the text layer, so the encoding and its strict error handling are unchanged.

Binary writes (`out.encode("utf-8")`) would give the same bytes, but would change the shape of
three writers for no added guarantee.

What the SSH collector stores: the installed netmiko 4.7.0 (`netmiko>=4.1,<5`), inspected
statically, normalises line feeds in `BaseConnection.read_channel` (`\r\r\r\n`, `\r\r\n`,
`\r\n`, `\n\r`, then any remaining `\r`, to `\n` when the response return is `\n`, the default)
unless `disable_lf_normalization` is set. The collector's
`ConnectHandler` call does not set it. A live capture is therefore LF text, and is now stored as
exactly those bytes on every host: the bytes a Linux collector always stored. A transport that
delivers `"\r\n"` has it stored verbatim, no longer doubled.

What the REST collector stores: these exports were never the controller's wire bytes. `_write`
re-serialises the parsed response (`json.dump(obj, indent=2)`: ASCII, LF line breaks), and
pagination merges pages. F10 makes that re-serialisation host-independent; it does not make it
the wire bytes. The docstring now says so.

## Effect on readers and parsers (documented, not changed)

- **POSIX collecting host:** no byte changes anywhere. `os.linesep` is `"\n"`, so the old and new
  writers are identical there.
- **Windows collecting host, new collections:** captures, the sidecar and the archive index lose
  the translated `\r`. Their receipts become the LF receipts a Linux collector produces. The
  parsers now receive the session's LF text instead of CRLF text, which is the shape they are
  tested against (the golden fixture is LF). Many parsers already tolerate CRLF through
  `splitlines()` or `\s*$`. Two shapes did not, and no longer arise: a `(.+)` capture up to a
  `$` anchor under `re.MULTILINE` keeps a trailing `\r`, and a doubled `"\r\r\n"` yields an
  extra blank line under `splitlines()`. No individual parser was re-run to measure this (owner
  rule); the claim is that a Windows collection's parser input now equals a POSIX one's.
- **Existing collections are not rewritten.** Evidence is never mutated. A `--no-collect`
  re-analysis hashes and parses whatever bytes are on disk, exactly as before.
- **One transition across runs:** a receipt-digest comparison between a Windows collection made
  before this fix and one made after it shows a digest change for byte-identical device output.
  This is the same difference that already existed between a Windows and a Linux collection, and
  it does not recur.
- **JSON outputs on Windows:** the run manifest, phase timings, precert and comparison receipts
  written through `write_json_file` are now LF on every host too. Every reader parses them as
  JSON; the compact snapshot, the canonical protocol-assurance export and the incomplete marker
  contain no line break, so their bytes do not change anywhere.

## Tests (written, not run)

All are in `tests/test_collect_parse_live_safety.py`, which already homes both live front doors.
They simulate Windows text-mode translation on any host: the W36 simulator idea is copied, not
imported. A text-mode write that leaves `newline` at its default is given `"\r\n"`, installed as
the collector module's `open`. Each test fails on the pre-fix writers on Linux and on Windows.

1. `test_the_windows_text_simulator_really_translates_on_this_host`: the simulator is not inert
   (default newline gives CRLF and doubles a delivered `"\r\n"`; `newline=""` is verbatim).
2. `test_live_collector_stores_exactly_the_session_bytes_under_windows_translation`: drives the
   real `collect()` with a fake session.
   - Every capture is `answer.encode("utf-8")`; a delivered `"\r\n"` stays single.
   - The sidecar is `json.dumps(meta, indent=2)` bytes; the archive index rows' `bytes` and
     `sha256` equal the delivered bytes; `device_info.json` has no CR.
   - Every text write declared `newline=""`.
   - The set of files on disk equals the set the simulator saw written, so a writer on another
     code path cannot escape the check.
3. `test_raw_evidence_receipts_are_the_session_bytes_whatever_the_collecting_host`: the real
   receipt producer `_evidence_records`.
   - Native and simulated-Windows collections give identical `files` and `root_sha256`, and each
     receipt is the delivered bytes' size and SHA-256, the sidecar included.
   - `cmdio._load_cmd_output` hands the parser the session's own text.
4. `test_live_collector_writes_the_golden_fixture_bytes_on_every_host`, parametrised over the
   golden fixture hosts: real golden data.
   - A session replaying `tests/synthetic_fixtures.py :: COLLECTIONS` is stored by `collect()`,
     under simulated Windows, as exactly the bytes `write_collection` stores for the golden.
   - The `_evidence_records` receipts over the two collections are identical.
   - At least half of each host's fixture commands are issued and compared.
5. `test_every_controller_collector_stores_host_independent_json`: iterates the live
   `CONTROLLER_COLLECTORS` registry, not a hand list.
   - Every export each registered collector writes, ISE's ERS consolidation and FMC's merged pages
     included, is exactly `json.dumps(obj, indent=2)` bytes with no CR.
   - The files on disk equal the recorded writes.
6. `test_the_newline_policy_check_flags_the_pre_fix_writer_shapes` and
   `test_every_live_collector_text_write_pins_no_newline_translation`: a structural AST check over
   every module hosting a live collector. The modules are derived from `collect` and
   `CONTROLLER_COLLECTORS`, not from file names.
   - Every text-mode `open` / `os.fdopen` / `write_text` must pin `newline` to `""` or `"\n"`.
   - A non-literal mode fails closed.
   - The planted-shape test proves the check fires.

## Static checks run

- `py -3.12 -m py_compile` on the three changed Python files.
- The newline-policy AST helper, run statically. Over the pre-fix sources it reports the three
  `COLLECT_PARSE_V3_23_0.py` writers (lines 1337, 1633, 1704 on `a06d1d27`) and the
  `rest_collect.py` writer (line 160). Over the fixed sources it reports none. The planted shapes
  give 7 writes and offenders at lines 1-5.
- Fixture coverage, computed statically: the fixture commands in the static
  `COMMANDS_IOS ∪ COMMANDS_NXOS` registry are 44/45 for core1, 27/30 for core2 and 21/21 for
  access1. None of the fixture texts contains a CR.
- `tests/test_protocol_assessability.py` static helpers on the changed engine files: no
  hand-listed state collection, and no receipt-state interpretation in `COLLECT_PARSE_V3_23_0.py`.
- An AST scan for locals shadowing a called module-level name: none in the changed files.
- The attestation `rest_collect_get_only` source scan counts literal method spellings in
  `rest_collect.py`. The edit adds none, so the golden's attestation strings are unchanged.
- The privacy verifier and the rule-7 marker scan, before commit.

## Not changed

No projection, schema, transport pin, `openapi.ts`, frontend fixture, Atlas Scope file, golden or
sample changed. No new module or tracked file was added under `cisco_toolkit/` or
`webapp/backend/`, so the LF byte-custody receipt and the golden's module-count attestation do not
move. F10 has no line in `docs/one-app-contract-gaps-status-2026-10-08.md` (that register lists
the G items only), and the W36 precedent added no SSOT row, so neither file changes.

## Observed outside F10 (not fixed here)

`rest_collect.collect_ise` breaks out of the ERS list walk when a page has no `SearchResult`
dict, for example when ERS is disabled and the GET returns `None`, but leaves `nxt` set. The
following `if nxt:` then logs "stopped at the 200-page cap". When ERS is disabled, this
attributes nothing-collected to the cap. When a later page is malformed, it writes the pages
already read as the consolidated export, with no truncation marker in the evidence; only this
mis-attributed log line says the census may be truncated. This is a coverage-honesty follow-up
for its own row.
