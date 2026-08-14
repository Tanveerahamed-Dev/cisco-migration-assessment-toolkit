# Enhancements master reference

This directory contains the static, interactive reference surface for the
Enhancements repository. It explains the evidence pipeline, major engineering
decisions, data-authority model, trust boundaries, lifecycle gates, repository
areas, verification matrix, and operator entry points.

The site is deliberately not an operational interface. It accepts no evidence,
stores no state, calls no runtime API, uses no analytics or cookies, and does
not become another source of truth. The repository's code, schemas, manifests,
tests, and immutable release evidence remain authoritative.

## Local development

Requires Node.js `>=22.13.0`.

```powershell
npm ci
npm run dev
```

The local preview is served at `http://localhost:3000`.

## Verification

```powershell
npm test
npm run lint
npm audit --audit-level=high
```

`npm test` type-checks the source, performs a production build, renders the
Worker response, checks the semantic content contract, and asserts the surface
remains static and dependency-light. Oxlint enforces correctness,
accessibility, import, Node.js, React, and Next.js rules with warnings treated
as failures. The audit covers runtime and build-time dependencies.

Production builds also create a lossless Sites packaging profile. The canonical
projection and compression JSON receipts remain byte-for-byte reconstructable,
but `dist` stores only their deterministic `.json.gz` representations; the
outer deployment receipt uses the same representation and excludes only itself
from its exact physical member census. Every generated `.mjs` payload in `dist`
is likewise replaced by a deterministic, receipt-bound `.mjs.gz` member. The
Worker serves that member at the original virtual module URL with explicit gzip
and JavaScript response headers. Build tests require fixed-header single-member bounded expansion,
exact raw/representation SHA-256 joins, exact module census, module gunzip
equivalence, no uncompressed deployment duplicate, and a complete expanded
`dist` below the Sites limit. For body-bearing GETs
whose asset binding omits encoding metadata—including when it infers
JavaScript from the compound suffix—the Worker accepts the response only after
replay-safe validation against the
[`CANONICAL_GZIP_HEADER_BYTES`](build/gzip-contract.js) owner registered in
[`docs/ssot.md`](../docs/ssot.md); ambiguous plaintext remains a categorical
failure. Metadata-only HEAD accepts an encoded-asset MIME but refuses the
ambiguous JavaScript/no-encoding tuple. Full-member hash and gunzip proof
remains a build/deployment receipt rather than a runtime-prefix claim. The
authored `public` projection and offline reference corpus remain uncompressed
and source-bound.

The Python side is independently gated:

```powershell
python -m pytest tests -q
python -m ruff check atlas_privacy.py compiler governance continuity release cli tests
```

## Whole-repository compiler

The exact tracked Git tree is the census. From this directory, compile a clean
commit and validate every emitted envelope against the tracked schemas:

```powershell
python -m compiler --repo-root .. --output C:\tmp\atlas-compiler
python -m compiler.schema_validation --input C:\tmp\atlas-compiler
node build/projection/build.mjs --input C:\tmp\atlas-compiler --output public\atlas-projection
```

`manifest.json` binds the commit, HEAD tree, index census, derived source-tree
digest, every record group and every chunk. Exact-clean compilation reads each
fully exposed file from its raw selected-commit Git blob; checkout filters such
as `core.autocrlf` therefore cannot change source, line, or tree digests. A
separate worktree snapshot plus before/after Git checks still detects local
changes. Restricted payloads are never read.

Compiler corpus contract `1.2.0` keeps hard structural invariants separate from
semantic acceptance gates. Every successfully parsed safe source has exactly
one typed, parser-owned `structural_entities` root (for example a Python module,
TypeScript SourceFile, stylesheet, template, configuration, workflow, structured
document, or plain-text document). Every safe nonblank line must resolve to a
same-file symbol or that structural root; a file census ID can never satisfy
Level 1. Roots carry exact source range, parser/language/role and raw-Git
provenance plus explicit generated-origin uncertainty, but never claim runtime
behavior. The compiler may therefore prove 100% tracked-file, exact-line, root,
and structural-mapping coverage while still blocking behavioral, runtime,
executed-coverage, binary-review, or Level-4 claims.

The required `consequential_claim_facets` group emits one schema-validated,
payload-omitting fingerprint record for each field-atomic candidate in the bounded
curated-content census. Its manifest receipt is the count owner; the records
carry stable facet identity, selected-commit Git-blob provenance, an RFC 6901
source pointer, classification and review state, and only grounding/value
digests. They contain no claim values, but their unsalted fingerprints are
staleness bindings rather than confidentiality; low-entropy values may be
dictionary-recoverable. They provide no independent review, rendered-sink
closure, sentence-level completeness, or global claim closure. The bounded
census therefore remains explicitly incomplete and its global
closure gate remains false.

Three additive rendered-sink lineage contracts currently join bounded subsets
of those immutable facet subjects to actual presentation slots: Open Horizon in
the PDF and canonical `/gaps` route, the Capability Catalog in the PDF and
canonical unfiltered `/capabilities` route, and the nine Atlas Core outcome
success signals in the PDF outcomes section and `/product#core-outcome-contracts`.
The PDF gate carries their
payload-omitting mapping receipts, while PDF text extraction and rendered-DOM
tests independently reconcile visible observations. None of these slices is a global
rendered-claim universe: undeclared sources, routes and renderer states, as well
as fixed, computed, joined and conditional claims, remain unresolved. A local
mapping PASS never changes review state, supplies claim evidence, authorizes
publication, or closes the global consequential-claim gate.

Safe UTF-8 source is emitted only in per-file content-hashed chunks. Each source
record carries its Git blob OID and byte basis. Restricted paths, symlinks, Git
links and all decoded binary payloads remain metadata-only; their size comes
from Git object metadata without reading the payload. Binary records retain Git
object identity, size and media type, and explicitly remain pending format-aware
or manual privacy review.

## Read-only continuity CLI

The continuity package reads an exact compiler bundle without mutating the
repository or making network calls:

```powershell
python -m continuity query --compiler-output C:\tmp\atlas-compiler --id urn:atlas:...
python -m continuity query --compiler-output C:\tmp\atlas-compiler --path cisco_toolkit/ssot.py --line 1
python -m continuity validate-envelope --repo-root .. --compiler-output C:\tmp\atlas-compiler --envelope task-envelope.json
python -m continuity validate-completion --repo-root .. --compiler-output C:\tmp\atlas-compiler --envelope task-envelope.json --receipt completion-receipt.json
```

Device writes, Vault writes, client-data ingestion and public publication are
unwaivable. See `continuity/README.md` for the schemas and abstention behavior.

## Exact-source release outputs

The deterministic release builder consumes a **complete, clean** output from
`master-reference/compiler` plus the five curated content contracts. It
revalidates every manifest receipt and chunk before emitting the machine
reference, owner handbook, engineering dossier, source/symbol indexes,
capability and decision reports, enhancement brief, agent pack, CycloneDX
SBOM, provenance, self-contained HTML, offline ZIP, preservation pack,
preservation-coverage ledger and family attestation. `content/output-contract.json`
is the shared denominator for UI labels and emitted member names.

Run from `master-reference` after producing the compiler output:

```powershell
python -m cli build `
  --repo-root .. `
  --compiler-output C:\path\to\compiler-output `
  --output C:\path\to\new-empty-release-directory
```

The release command generates the deterministic source-bound Master Reference
PDF by default and records its renderer/input receipt. `--no-pdf` is an
explicitly incomplete preview; `--pdf` accepts a separately rendered input.
Successful PDF generation is not independent visual approval. An external PDF
also leaves binary-container privacy review explicitly blocked.

The builder revalidates HEAD, tree, clean tracked status, index mode/blob/path
census and every full-exposure file hash before, after and at finalization.
Metadata-only content is never opened. Artifacts are assembled in a sibling
staging directory and atomically published only after schema, privacy, output
contract and exact-source reconciliation succeeds; a failed build leaves no
plausible partial family.

The builder never generates keys or stores secrets. An owner may separately
sign the exact canonical manifest with an existing off-repository Ed25519 key:

```powershell
python -m cli sign --manifest C:\release\release-manifest.json `
  --private-key D:\offline-owner-key\atlas-ed25519.pem `
  --signature C:\release\release-manifest.sig.json --prompt-passphrase

python -m cli verify --manifest C:\release\release-manifest.json `
  --signature C:\release\release-manifest.sig.json `
  --public-key C:\trusted\atlas-ed25519.pub

# Unsigned previews can still be checked for byte-for-byte internal integrity:
python -m cli verify-family --manifest C:\release\release-manifest.json
```

Verification checks the signature, the independently trusted public-key
fingerprint, and every artifact byte count/SHA-256 receipt in the manifest; it
also rejects undeclared sibling files and inventory divergence. It does not
convert an unsigned or visually unreviewed preview into an approved publication.

Without that signature, the family remains a blocked unsigned preview. Failed
semantic acceptance, missing/current Graphify, omitted PDF, or pending
independent review keeps the manifest at `unsigned_preview_incomplete` and the
corresponding gate explains why. Public publication and private-key recovery
remain separate explicit owner decisions.

## Design contract

- repository-owned content; no runtime content fetch
- server-rendered semantic HTML with one small interactive client surface
- system fonts and CSS-native visuals; no font or media CDN
- keyboard-operable controls and reduced-motion support
- responsive from narrow mobile screens through large review displays
- exact verification wording: focused proof never implies whole-repository proof
- deployment configuration belongs in `.openai/hosting.json`
