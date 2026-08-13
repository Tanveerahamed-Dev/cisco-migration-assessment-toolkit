# Atlas agent-native continuity

This package is a local, deterministic, read-only interface over an exact Atlas compiler bundle and Git worktree. It performs no network calls, test execution, file writes, staging, commits, device access, Vault access, client-data ingestion, or publication.

Run from `master-reference/` so the package is importable as `continuity`:

```powershell
python -m continuity query --compiler-output .atlas-compiler/<commit> --id urn:atlas:symbol:...
python -m continuity query --compiler-output .atlas-compiler/<commit> --path cisco_toolkit/ssot.py --line 42
python -m continuity query --compiler-output .atlas-compiler/<commit> --impact urn:atlas:symbol:...
python -m continuity enhance --repo-root .. --compiler-output .atlas-compiler/<commit> --id urn:atlas:symbol:...
python -m continuity enhance --repo-root .. --compiler-output .atlas-compiler/<commit> --file cisco_toolkit/ssot.py
python -m continuity enhance --repo-root .. --compiler-output .atlas-compiler/<commit> --gap gap.catalog-ui
python -m continuity validate-envelope --repo-root .. --compiler-output .atlas-compiler/<baseline> --envelope task-envelope.json
python -m continuity validate-completion --repo-root .. --compiler-output .atlas-compiler/<completion> --envelope task-envelope.json --receipt completion-receipt.json
```

All output is canonical, sorted JSON. A missing query result returns `status: "abstained"`; the tool never invents an answer. Impact traversal is one-hop structural evidence and is not runtime truth.

## Deterministic enhancement package

`enhance` accepts exactly one seed:

- `--id` for a stable compiler record, including an entity or symbol.
- `--file` for an exact tracked path, resolved to its stable compiler file ID.
- `--gap` for a stable gap ID in the exact tracked
  `master-reference/content/delivery-governance.json`.

The command independently reconciles the compiler file census, Git index and
selected commit tree; verifies a clean current HEAD/tree; rejects hidden index
flags; and reconstructs architecture and governance only from compiler-approved
raw Git blobs. Git observation is intentionally tracked-only: untracked paths
are never enumerated, opened, hashed or included in the state digest. CR-only,
LF and CRLF source terminators are all preserved exactly. The tracked Git state
is observed again after traversal, and any mutation or source-binding change
fails the request. Restricted or metadata-only source never becomes enhancement
evidence.

Payload-omitting consequential-claim facet records remain available through
the full release-backed `query` command, including `--path` via their
`source_path`. They are deliberately not valid `enhance --id` seeds and are not
part of enhancement impact traversal: the lazy enhancement reader does not
independently reconstruct their complete subject census from the five selected-Git
source blobs. Treating a merely re-chained facet record as an exact subject
would otherwise launder unverified source pointers or fingerprints into an
exact-commit-looking scaffold.

`enhance` accepts only an exact, clean compiler schema `1.2.0` corpus. It
requires unique, exact-denominator invariants for every safe structural line,
every GUI route/component dossier and every parsed-source structural root, plus
non-empty acceptance gates and current source-bound Graphify and static
architecture receipts. Stale schemas, missing or duplicate gates, denominator
drift and failed architecture conformance are rejected before traversal.

The resulting package contains:

- the exact seed record and source citation;
- a typed dependency/impact closure across file membership, explicit compiler
  references, static import/call candidates, Graphify, claims, tests, routes,
  components and workflows;
- affected architecture owners and known GUI/artifact surfaces;
- explicit unresolved impact categories and compiler evidence limits;
- a smallest-safe-slice scaffold, existing tests/workflows, current compiler
  gates, and unfilled test/rollback/kill-condition placeholders;
- exact source binding and a canonical package digest.

Traversal is streaming, bounded and deterministic. Stable URN kinds route to a
single compiler group; the command does not construct an all-record index or a
global graph. It lazily validates only scanned content-hashed chunks and
discloses logical group passes separately from physical receipt reads, bytes,
cache hits and cache bytes in `scan_counts`. A request-scoped immutable snapshot
caches validated raw chunks only for impact groups, so reference multiplicity
and traversal depth cannot reread the same chunk from disk. The hard request
budgets are 512 physical compiler receipts, 1 GiB of validated compiler-receipt
bytes (including the one-byte overrun probe) and 512 MiB of cached raw chunks;
a request fails before the read that would exceed a budget. Manifest and tracked
Git-state/tree/blob observation use separate bounded readers and are explicitly
outside these compiler-receipt counters. Source text is never cached. Source-text URN seeds abstain because they
can be unbounded; use a file or line query.
Defaults are depth 4, 250 records and 2,000 edges; hard maxima are depth 8,
2,000 records and 10,000 edges. Seed values are capped at 4 KiB, serialized seed
records at 256 KiB and serialized packages at 8 MiB. Override traversal bounds
with `--max-depth`, `--max-records` and `--max-edges`. Reaching a bound is
reported as truncation and blocks the slice scaffold. Missing seeds or gap
evidence abstain. Stale, dirty, preview, malformed or census-divergent inputs
fail closed.

The raw snapshot bounds physical I/O; it does not make repeated JSON decoding
or record scans interactive. The emitted scan ledger remains the performance
evidence, and this CLI does not claim the browser's sub-100 ms search/impact
budget. A future receipt-bound sharded ID/reverse-reference/name index is still
required for that class of latency.

The package is not a code proposal or authorization. Static/name/import and
Graphify edges remain possible dependencies, a gap does not imply code impact,
tests are not executed, and rollback commands or success thresholds are never
invented. The command writes nothing; canonical JSON is emitted only to stdout.

## TaskEnvelope 1.0.0

Required fields:

```json
{
  "schema_version": "1.0.0",
  "id": "task-atlas-example",
  "baseline_commit": "<exact HEAD commit>",
  "baseline_tree": "<exact HEAD tree>",
  "objective": "A concrete bounded objective",
  "allowed_owners": ["master_reference", "verification_source"],
  "allowed_paths": ["master-reference/continuity/", "master-reference/tests/continuity/"],
  "allowed_actions": ["read-repository", "edit-repository", "run-tests", "commit-git"],
  "prohibited_actions": ["device-write", "vault-write", "client-data-ingest", "public-publish"],
  "required_tests": [{"id": "continuity", "command": "python -m pytest tests/continuity -q"}],
  "authority": {"actor_id": "agent-id", "grant_id": "owner-grant-id", "granted_by": "owner-id"},
  "expires_at": "2026-08-08T00:00:00Z"
}
```

Allowed paths are exact files or directory prefixes ending in `/`; globs and traversal are refused. Owners are component or explicit-exclusion IDs from the tracked architecture contract. The exact compiler bundle must bind to the baseline commit and tree.

The following constraints are unwaivable and must be explicitly prohibited:

- `device-write`
- `vault-write`
- `client-data-ingest`
- `public-publish`

## CompletionReceipt 1.0.0

Required fields:

```json
{
  "schema_version": "1.0.0",
  "id": "completion-atlas-example",
  "envelope_digest": "<canonical TaskEnvelope SHA-256>",
  "baseline_commit": "<TaskEnvelope baseline commit>",
  "baseline_tree": "<TaskEnvelope baseline tree>",
  "completion_commit": "<current exact HEAD commit>",
  "completion_tree": "<current exact HEAD tree>",
  "diff_digest": "<continuity material-state digest>",
  "changed_paths": ["master-reference/continuity/query.py"],
  "changed_owners": ["master_reference"],
  "actions_performed": ["edit-repository", "run-tests", "commit-git"],
  "tests": [{"id": "continuity", "command": "python -m pytest tests/continuity -q", "exit_code": 0}],
  "artifacts": [],
  "conflicts": [],
  "exceptions": [],
  "external_actions": [],
  "actor_id": "agent-id"
}
```

Validation recomputes the baseline-to-current material diff, changed paths, architecture owners, current commit/tree, artifact hashes, required test receipts, actions, authority, and expiry. It also requires an exact compiler bundle for the clean completion commit. A declared exit code is checked as evidence syntax; the validator does not execute the command.

This package does **not** claim a populated bitemporal ledger, an MCP server, cryptographic identity, test correctness, or runtime coverage. It validates local declarations against exact observable state and abstains or fails when proof is unavailable.
