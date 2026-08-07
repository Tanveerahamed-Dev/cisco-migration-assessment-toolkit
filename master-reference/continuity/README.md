# Atlas agent-native continuity

This package is a local, deterministic, read-only interface over an exact Atlas compiler bundle and Git worktree. It performs no network calls, test execution, file writes, staging, commits, device access, Vault access, client-data ingestion, or publication.

Run from `master-reference/` so the package is importable as `continuity`:

```powershell
python -m continuity query --compiler-output .atlas-compiler/<commit> --id urn:atlas:symbol:...
python -m continuity query --compiler-output .atlas-compiler/<commit> --path cisco_toolkit/ssot.py --line 42
python -m continuity query --compiler-output .atlas-compiler/<commit> --impact urn:atlas:symbol:...
python -m continuity validate-envelope --repo-root .. --compiler-output .atlas-compiler/<baseline> --envelope task-envelope.json
python -m continuity validate-completion --repo-root .. --compiler-output .atlas-compiler/<completion> --envelope task-envelope.json --receipt completion-receipt.json
```

All output is canonical, sorted JSON. A missing query result returns `status: "abstained"`; the tool never invents an answer. Impact traversal is one-hop structural evidence and is not runtime truth.

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
