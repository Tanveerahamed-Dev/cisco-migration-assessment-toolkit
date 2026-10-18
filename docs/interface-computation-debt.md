# ADR 0008 interface computation ratchet

PR-0 (#673) merged as `92490340` after independent MERGE-READY on `cfa0b72d`.
The machine-readable register is `interface-computation-debt.json`. PR-0b adds
schema **`interface-computation-debt/4`** under the
[supervisor's boundary ruling](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/pull/667#issuecomment-6243152958).
Its `sites` debt records are unchanged from merged main, as are the immutable
source ceiling, roles and detector forms. The separate `boundary` list starts
**empty**: PR-0b admits no boundary site and reclassifies no debt.

The dated proposal/capture sections below preserve their original failures,
counts and then-pending decisions. They are history, not the current admission
policy or an instruction to regenerate a register. The current policy is below;
the executing owner is `tests/interface_computation_guard.py :: check / validate`.

## Exact boundary admissions (PR-0b)

ADR 0008 forbids interface computation of engine-owned facts. Transport safety
and UI state that derive no network fact have a separate exact-site admission
class. A boundary record has exactly `path`, `symbol`, `rule`, `fingerprint`,
`occurrence` and one `category`. The identity is the same detector-normalized
file/qualified-symbol/rule/SHA-256/occurrence tuple as a debt record. There are
no file, symbol, category or glob exemptions; every finding is still scanned.

| Closed category | Eligible purpose |
|---|---|
| `transport-bound` | Caps on response bytes, stream chunks or element counts |
| `response-identity` | Binding a response to the request that produced it |
| `cancellation` | Cancellation state and control |
| `ui-state` | Selection, pin or collapse state that derives no network fact |

**Admission is per PR and independently reviewed.** The PR description lists
each proposed exact tuple, its category and a one-line justification. The
independent reviewer must sign off on each record by that exact name. A blanket
approval of a category, module or function does not admit another site. A record
that reads snapshot/projection facts to produce a user-facing count, verdict,
threshold or ratio is **never** a boundary site; the reviewer blocks it. Moving
or rewriting an engine calculation does not make it eligible. A category string
and green CI are not review approval, proof of fact-free code or merge authority.

The guard checks the immutable GitHub PR event's base SHA and binds the checkout
to that PR head or its exact GitHub merge parents, for this repository's `main`
base. It compares new boundary identities with detections in the base's source.
Even a base file outside the old import closure is read and parsed for this
comparison: adding an import or editing another symbol cannot launder an
unchanged helper. A new record must identify a site introduced or moved by this
PR under the detector's normalized identity; comments, whitespace and line moves
alone are not new sites. Retained base records need no repeat admission, but
their categories cannot change. Main-push validation rechecks the merged delta
against its `before` SHA. Outside a main-PR or main-push event (including stacked
PRs, local runs and manual dispatch), the comparison is `git merge-base HEAD
origin/main`, with **retention only**. An older checkout is not compared with
later main removals. Introduced records still refuse there; a missing comparison
ref or malformed/mismatched main event fails closed. An admission PR must target
`main` (including #667 before its admission push). Direct main pushes can pass
structural admission: branch protection and independent review, not this event
reader, enforce the prohibition on unreviewed direct publication.

Debt remains **strictly shrink-only** against its immutable source ceiling and
every active ancestor. No debt record, including a deleted historical record
from an earlier schema, may move into `boundary`. For each introduced
substantive AST record, the guard rejects a `(rule, fingerprint)` match
against **all** current, base, active-ancestor and historic debt, independent of
path, symbol or occurrence. Under the [supervisor's option (b)](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/pull/682#issuecomment-6247503468),
name-only `verdict-symbol` / `analysis-symbol` rows and bare-literal
`verdict-return` rows are excluded **only from this location-independent check**.
They carry no computation alone; exact-tuple transfers and same-symbol checks
still apply. Literal exceptions are proved with the unchanged fingerprint
producers. Full live source supplies literals beyond the truncated expression
preview; an unproved preview never creates an exception. A second check rejects
a `(path, symbol, rule)` match to a
debt row removed by this PR, catching rewrites in the same symbol. There is no
same-file narrowing. Exact-tuple debt transfers still refuse for every rule.

The location-independent and removed-symbol checks deliberately exclude only
**producer-qualified lexical rows**: the symbol must be `<forbidden-pattern>` or
`<generated-payload>` **and** the rule must be in the closed vocabulary derived
from the frozen lexer/payload emitters: `raw-count`, `raw-threshold`,
`filter-count`, `graph-worklist`, `dynamic-code`, `opaque-generated-source`.
The guard extracts those emission sites; an independent Node-backed producer
control and the existing detector pins bind that vocabulary. It is not a
hand-maintained exemption list. Short lexical token spans collide across
unrelated code. A marker symbol with any other boundary rule **refuses**: the
JS/TS AST producer can emit that same symbol for a string-literal method name.
Both the debt index and removed-symbol index use this same classification.
`dynamic-code` is **never** a boundary record in either namespace or any category;
no purpose admits eval, exec or Function. **Reviewer-only provenance
checks remain mandatory** for rewritten debt whose fingerprint changes,
including a rewritten copy that retains the original debt row in the same symbol.
Only replacements matching a debt row removed by this PR receive the same-symbol
mechanical refusal; changed-location rewrites also require review. Engine-role
computations moved into the interface and sites detected only by lexical
tripwires likewise require reviewer provenance checks. Reviewers must reject these when
they compute engine-owned facts; syntactic eligibility is not semantic admission.
No category mechanically certifies a detector rule fact-free. Boundary records
must also match current detections exactly, so removal of code requires removal of its
record. Full Git history and every merge parent expose boundary removals;
restoring a removed identity, even with another category, refuses. An admission
proposal preserves existing boundary metadata only for still-observed sites and
retains **every** raw detection; it does not authorize a new record or debt growth.

V3 registry-change history is bounded at merged
`92490340e3c55c34c7a8d26e878ee5de7c729601`. A later commit may carry unchanged
v3 bytes from a parent, but cannot downgrade a v4/unknown parent through another
parent. Every register-change event in the full HEAD and PR-base histories is
checked, even when it reuses an already-read blob. This is a schema migration,
not a new debt ceiling. The older v1/v2 and initial-observation cutoffs stay fixed;
later schema reintroductions and inactive v4 records refuse. The frozen detector
functions/constants are compared with that merged source, while the lexer,
source discovery and TypeScript/HTML detector files remain byte-identical.

Synthetic controls in `tests/test_interface_computation_debt.py` cover each
category, malformed/missing categories and identities, duplicates, additional
findings in the same symbol, unchanged base code, outside-closure helpers,
unrelated-symbol edits, legitimate new/moved sites, missing/base context,
category changes, current/base/ancestor/historical debt transfers, moves to a
new file, symbol renames, copied occurrences, renamed historic debt and in-place
rewrites, boundary removal/resurrection on either merge parent, register deletion
and restoration, retained-only contexts and forbidden later v3/observation resets.
A temporary-repo `check()` control proves v2-only historical debt cannot return
as either an exact tuple or a moved boundary form. The hosted-only control binds
the real event base even when the boundary is empty, and requires `allow_new` to
match the actual event and its main-base/ref policy. Forged-marker controls use
both validate-level records and the real Node-backed AST producer. Name/literal
controls keep the exact and same-symbol refusals and substantive-copy refusal.
They also pin the unchanged detector. Runtime execution and final-head evidence
belong to GitHub; PR-0b requires 15/15 and maximum-depth independent review.

## Reuse, never clone

A new site's substantive form that matches registered debt must **call the
existing owner**, rather than clone it. A rename or reshaping made only to clear
the check is laundering; the independent reviewer blocks it. The name/literal
exceptions do not authorize a substantive copy or any engine-owned user fact.
The mechanical guard is a closed form ratchet, not proof of provenance or absence.
Changed-fingerprint rewrites/copies, engine-to-interface moves and lexical-only
findings still need the reviewer checks above.

For #667 before its admission push: retarget to `main`; `api.ts :: planKeys`
must export/call the existing `projectionEmbed.ts :: closed` owner;
`SavedPlan.tsx :: samePin` must reuse `projection.ts :: sameIdentity` or
`sameProjectionIdentity` if its semantics match. Only a genuinely different
comparison with an accepted justification may be admitted. `planResponseChunks`
remains a `transport-bound` candidate; these instructions admit no record here.

## What the gate checks

The guard ratchets a **closed, named set of detected computation forms**. It is
**not proof of absence of computation**. Undetected forms require review and are
not certified absent. ADR 0008 point 4's mechanical claim is: every detected form
appears exactly once in strict shrink-only debt or the separately reviewed
boundary class. This does not turn a boundary label into semantic verification.

Discovery is class-derived rather than a prefix/special-file selector:

- Every repository browser HTML/HTM/XHTML/SVG entry document (case-insensitive suffix class), including inline scripts,
  event/URL bodies, nested srcdoc and local script imports.
- Frontend projects identified by their package metadata; authored modules and
  the complete repository-local module closure, including reexports, relative
  imports and TypeScript configuration aliases. An imported helper outside the
  project's source directory is still inspected. Generated authored TypeScript is included; compiled imports require the byte gate below.
- API modules identified by their API-library imports; registered SPECS writer
  modules and library-backed DOCX/PPTX/workbook/HTML writers; their repository-local
  Python import closure, including relative imports and unregistered helpers, stopping only at declared engine roles.

Test/fixture directories are not initial production seeds; a runtime import into
one is still followed. Third-party package/CDN modules and non-executable asset
imports are terminals, not a claim about their code. Unknown local module edges
refuse. Dynamic selectors conservatively expand the applicable repository source
class; opaque external/generated runtime behavior still requires review.
Remote HTML script references additionally emit `opaque-script-source`, so an
uninspected remote script is never treated as an empty/clean code unit. Existing
references require exact source identities; new ones refuse the closed register.

Python's AST and the locked TypeScript AST parser identify named analysis
functions, counts, reductions, key counts, counter updates, numeric thresholds,
fact arithmetic and graph worklists. Additional named forms are:

- `returned-comparison`: a comparison involving a non-literal operand in an
  explicit or implicit return, including `n === 0` and `value <= limit`;
- `ratio-arithmetic`: division of two non-literal operands, including `100 * a / b`;
- `verdict-symbol` / `verdict-return`: verdict-shaped function/declaration names
  or returns (the closed vocabularies and name patterns live in the detector),
  including readiness/gate predicates, named decision values and Boolean returns.

A separate token-grammar tripwire covers dynamic evaluation, graph worklists,
filter/count operations and numeric comparisons, including generated string
payloads. Python/TypeScript tokenizers discard comments and normalize spellings;
lexical identity does not hash raw whitespace. HTML uses its parsed executable
fragments, so inert markup comments do not become detections. Source is parsed as data; inspected
application code is never imported or evaluated. Parse failures refuse.

Every allowance is one file, qualified symbol, operation rule, normalized
expression digest and occurrence. Within the interface closure there are no module-wide or symbol-wide
allowances. Explicit engine roles are traversal terminals, not legacy debt allowances. Comments/formatting do not change AST identities; altered thresholds,
new counts and a second identical call remain refused until removed, moved to
their engine owner, or (only for eligible new transport/UI state) independently
admitted as exact boundary records.
The detector conservatively includes existing presentation/infrastructure
calculations: an entry is an exact legacy footprint, not an assertion that every
length check is a network fact. This does not prove arbitrary program semantics
or eliminate the independent review requirement.

### Historical v2 ceiling rationale

Version 2's source ceiling is initial boundary `7d9f83639eccb12915f2686aae13a47b44d50df1` (foundation main `5f1e067c` plus this PR's guard, role metadata and existing build-proof binding). This explicitly widens
the proposed v1 footprint and changes lexical identities; its before/after counts
must be disclosed with the hosted admission evidence. This permission applies
only to the still-unmerged PR-0 proposal, not future feature exemptions.
The active register must equal current detections, be a subset of that source,
and be a subset of **every v2 active ancestor register**. A v1 record is historical
only if its commit is an ancestor of `3d3bca01`, the authorized F0 integration
which carries the reviewed `db5f5675` v1 register unchanged. A later v1 reset or
an unknown schema refuses. Removing code requires
removing its entries in the same PR. Restoring both code and a removed allowance
still fails against history. Synthetic controls prove growth, duplicate-site,
changed-disposition, stale-entry and resurrection refusal. This first ceiling
does not authorize future exemptions or changing the detector to hide a finding.

## Version 2 hosted regeneration

`interface_computation_guard.py --observe` runs on every required matrix leg,
binding the proposal to its Git commit/tree and all detector digests. It writes
the full observation to the runner's temporary directory and publishes a
gzip/base64 **source-only proposal** in bounded `DEBT_PROPOSAL_CHUNK` log lines
between `DEBT_PROPOSAL_BEGIN/END`. Decode the hosted log to import the proposal;
do not run the inspector locally. The proposal contains source identities, not
client snapshots. This transport adds no artifact upload before the existing
distribution confidentiality/source-binding audits. It does not waive them.

The bootstrap must pass the new helper/move/entry refusal controls, named normal
form controls and harmless-edit controls. Admit matching captures from all six
platform/interpreter legs, then require fresh 15/15, CodeQL and applicable
complete workflows on the final head. The same independent reviewer re-reviews
the fix map; no merge or release is authorized.

## Audited domains and repair ownership

The exact file/symbol sites are held in the JSON register. These domain mappings
explain their intended repair, without duplicating a second site census:

| Audited computation | Interface/report symbols | Owner or disposition |
|---|---|---|
| Health/finding/readiness recounts | `webapp/backend/summary.py :: _count_by / summarize` | Overview/Findings projection; PR-1 |
| HTML trend headline recounts | `cisco_toolkit/html.py :: _trend_point` | Canonical facts and finding facet owner; existing report sites remain explicit debt/allowances |
| KPI thresholds and readiness verdicts | `webapp/frontend/src/pages/Snapshot.tsx :: HEALTH_TONE / GAUGE_COLOR / SnapshotPage` | Engine facts, with the Atlas App frontend lead; PR-1 |
| Second topology and browser failure BFS | `webapp/backend/graph.py :: build_graph`; `TopologyGraph.tsx :: counterfactualFailure` | Projected topology/device impact; PR-1 |
| Divergent pre-change gate | Retired `_gate` and `_worst_readiness`; `_join_group_records` delegates to the engine | `cisco_toolkit/analyze.py :: compute_wave_cutover_gate / rollup_wave_cutover_gates / join_wave_group_records`; PR-2 local, hosted debt closure pending |
| Deck/workbook local counts, bands and lifecycle share | `cisco_toolkit/deck.py`, `cisco_toolkit/excel.py`, exact symbols in JSON | Canonical facts, partitions, published axis shares; PR-3 |
| Explorer path, flow, ACL, failure, carriage, causal and health engines | `blast_radius_explorer.html :: tracePath / flowBetween / evalAcl / failureImpact / linkCarries / causalFlows / fleetHealthState / scoreToken` | **Retired-with-surface**; product serving/link retirement pending PR-4; source retained |
| Scope forwarding, blast, graph and band qualification | `atlas-scope/src/forwarding/engine.ts`, `analysis/blast.ts`, `core/band-qualification.ts`, exact symbols in JSON | **Retired-with-surface**; hub product/packaging retirement pending PR-4; source retained |
| Scope compiler-owned coverage denominators | `atlas-scope/tools/lib/compile-model.mjs :: compileFabric` | **Retired-with-surface**; its counts must not supply the Atlas App's coverage banner |

The retirement disposition is an owner decision, not a claim that the current
routes are already removed. These engines are not future parity-pinning targets.
PR-4 must verify route/link/package/selftest/release contract changes without
weakening any surviving check. Saved plans #666/#667 retain their own changes;
the frontend lead owns `webapp/frontend` and H does not edit it concurrently.

Current projection inventory rows already publish health, lifecycle, findings and
coverage envelopes; device pages publish their exact failure-impact selections.
The topology node contract does not yet supply combined overlay presentation.
The endpoint owner publishes per-port identity summaries, not a complete multi-MAC
lookup, and failure impact publishes bounded counts rather than stranded endpoint
identities. The frontend lead was given these source boundaries and will withhold
the missing capabilities. No new overlay or identity support is claimed here.

The current transport has only Overview, Trust, Inventory, Findings, Topology and
Device views (plus path/carriage operations). The native-tab migration also needs
owned adapters for design details, saved-plan basis/revision, wave gates,
execution/NRFU records and comparison. Existing legacy owners remain available:
`/design` and `/design/nrfu` read stored engine sections with engine fallbacks;
`/deliverable/{kind}` uses SPECS for MOP/runbook; `/api/compare` calls
`engine.compare_bound_pair`; execution reads use `execution.with_progress`.
Overview's readiness groups are validated owner records. PR-2 locally implements the unified
per-wave gate in `analyze.compute_wave_cutover_gate`; hosted closure and publication are pending. Saved-plan list/revision/select/export belongs to
unmerged #666/#667. These are identified integration gaps, not newly implemented
projection contracts. Classic React workflows and their gates remain until the
frontend lead moves equal-or-stronger assertions with each native replacement.

## Canonical fact checks

The real pipeline test calls `require_canonical_checks`. For each registry path
it clones the assembled snapshot, changes only that value, and requires a
reconcile violation naming that exact path. Missing publication or raw basis is
a failing producer-fixture obligation. A newly registered fact with no real
check fails; a synthetic negative proves this guard is not a tautological
comparison with `RECONCILED_PATHS`. The positive real snapshot must also reconcile
cleanly. No existing assertion, sample/golden byte, budget or timeout is relaxed.

## Source-bound bootstrap evidence

The first published subject `3496db19` is deliberately unadmitted. CI run
`38871181375`, Python 3.13 job `116875383167`, reported **27 passed / 2 failed**
at the two active-register admission assertions. Windows job `116875383224`
reported the same **27 passed / 2 failed**. This preserves the real failing
baseline; neither source qualifies an active debt inventory or the later tests.

CodeQL check `116878334766` on that subject found one high-severity
`Bad HTML filtering regexp` alert at the script-element end-tag matcher: an HTML
end tag with whitespace/attributes could escape that regular expression.
The first correction used `HTMLParser`, scanning entity-decoded event bodies, JavaScript
URL bodies and nested srcdoc, and refuses external, unclosed or self-closing
script sources. Dedicated malformed-end-tag and attribute controls accompany it.
CodeQL passes on `32c858fb`, but Windows job `116893331963` reports **91 passed / 3 failed**: the two intentional admission failures and the retained malformed-end-tag count assertion. The real-producer canonical mutation step passes in **20.18 s** on that source. Python's CDATA parser retained the malformed end tag as JavaScript, so the current correction uses the already locked `parse5` **8.0.1** HTML5 parser alongside TypeScript **5.9.3**, with no dependency change. Script, decoded attribute, URL and srcdoc controls remain intact. Fresh hosted evidence is required; no alert is dismissed and no checker is suppressed.

The corrected observation must bind its source commit/tree and both detector
digests before its candidate inventory is reviewed. Initial observations are not
silently transferred across detector revisions. All 15 protected contexts and
applicable complete workflows remain required before the independent-review stop.


## Initial inventory admission (2026-10-16)

Hosted CI `38883822945`, PR head `61d64c43`, tested source
`be797fd56ed28308bf7db916ccfb630e200c4d98`, tree
`9c2c1bcf28b56213ce5113cda53728d3cda8df7e`, captured **20,619** exact static
operation records. All six legs report the same proposal fingerprint:
`0877ef77fe780fed4506ddc3a6543dd17c1a6dd226fbb8b0581dc63e968239cf`.

| Platform / Python | Capture artifact | Guard controls |
|---|---|---|
| Linux 3.10.22 | `12039690209` | 108 passed; only the two deliberate admission assertions failed |
| Linux 3.11.17 | `12039191151` | 108 passed; same two admission failures |
| Linux 3.12.15 | `12039595045` | 108 passed; same two admission failures |
| Linux 3.13.16 | `12038606651` | 108 passed; same two admission failures |
| Linux 3.14.8 | `12038876576` | 108 passed; same two admission failures |
| Windows 3.12.10 | `12038937291` | 108 passed; same two admission failures |

Every leg also passed the real-pipeline canonical-fact mutation check. The
candidate includes every audited summary/KPI/topology/gate symbol and the Scope
coverage compiler. 13,040 records are source-retained retired-with-surface
entries; 7,579 are conservative legacy operation/debt allowances. These are
tripwire records, often overlapping on one expression, not counts of semantic
SSOT defects and not an assertion that presentation/infrastructure operations
are network analyses. Source review and the independent audit still determine
which operation must move to an engine owner. No whole function/file exemption
is introduced: even a second identical occurrence must fit the exact recorded
footprint, and a retired allowance cannot return after removal.

The register imports that reviewed hosted proposal with one site per line.
No local inspector/test/engine execution or local receipt-verification
controller supplied its result. Its active current/origin/history comparison
and the complete default suites must now pass on the admission head; none of
the deliberately failing bootstrap runs is final validation.

CodeQL on `61d64c43` separately found incomplete URL scheme handling
(`116916820453`): only JavaScript URLs were inspected. The admission source
uses a closed scheme dispatcher, explicitly refusing data/VBScript and unknown
URL languages while retaining JavaScript-body inspection. Negative controls
remain executable. This only tightens source admission, leaving the inspected
application/report corpus unchanged. Fresh CodeQL and all protected/applicable
checks are required on the final combined head; no alert is waived.


## Complete-suite archive-order regression

Admission head `df239f4b`, CI `38885820994`, Python 3.11 job `116923345485`,
completed with **1 failed / 19,239 passed / 288 skipped / 3 xfailed** plus
26 passing subtests in **3,241.59 s**. The failure is the existing
`test_distribution_confidentiality_audit_stays_in_every_archive_workflow`:
the temporary census artifact upload preceded the required distribution audit
in `ci.yml`. Focused census passes did not close this broader failure.

The bootstrap captures above remain retained and the active inventory is
committed. The correction removes only that temporary early upload. Every
matrix leg still executes census observation (including its log fingerprint),
the active current/origin/history comparison, canonical mutations and the
complete default suite. The original package build/audit/source-binding,
pre-preservation recheck and archive upload remain unchanged. The two existing
archive-order/source-binding assertions now also run early, without changing
their bodies. No audit is bypassed, mocked or relocated to satisfy a text check.
Fresh full validation is required on the corrected head.

## Merge-parent resurrection control

Source review on `fc2ef115` found that Git's default path-history simplification
could omit a removal on one merge parent when the merged register matches the
other parent. The history check now uses `--full-history`. An executed synthetic
Git merge removes an allowance on one branch, restores it at the merge, and
requires the real history reader to reject that resurrection. Existing
current/origin/ancestor comparisons and every CI gate remain intact. Fresh
exact-head hosted evidence is required for this correction.

## Version 2 first hosted refusal

Capture head `d00643a3`, CI `38949368912`, Linux Python 3.12 job
`117136578321` (and Python 3.10 job `117136578039`) stops at discovery before
producing a proposal. Node exits nonzero; Python's captured stderr was not exposed
by the CLI traceback, so no root cause or valid capture is established. The next
diagnostic source prints that stderr and rethrows the same failure, retaining the
original 90-second parser limit. No source edge is waived, and no timeout or test
is relaxed. The malformed-source control also requires the diagnostic to surface.

Diagnostic head `a53e2ba9`, CI `38951026502`, Linux Python 3.12 job
`117142571364`, identifies the exact refusal:
`atlas-scope/review/a11y-ax-rows.mjs -> playwright`. The module is a transitive
npm dependency rather than a repository-local source edge. Discovery now reads
the canonical package locks as well as direct manifests. Locked third-party
packages are terminals; file-linked workspace dependencies are traversed as
repository source. Positive transitive-terminal and negative file-linked-helper
controls accompany the correction. No file-name exception, skipped edge, raised
limit or valid-capture claim replaces this failed evidence.

Head `324c5341`, CI `38953846389`, Linux Python 3.12 job `117152253379`,
passes discovery and then fails Python token normalization with an indentation
error before `cisco_toolkit/html.py :: redact_snapshot._mac`. The source itself
is unchanged and valid. F-string masks could reuse overlapping/equal format-spec
spans and splice a range repeatedly. The correction unions those spans before
masking; a nested formatted literal plus following function, with deliberately
overlapping AST locations, must retain the same token stream. Normalization
errors now name their source file. No producer/redactor or timeout is changed;
fresh hosted capture/control evidence is still required.

Synthetic refusal/stability controls now also execute **before** repository
observation, so a refused real-source edge cannot hide their results. This
additional selection excludes only the two real-register admission assertions
and the real-repository discovery assertion. The original unconditional full
guard, real producer mutation check, complete default suite and all limits remain
unchanged afterward. Interpolated HTML templates are stitched into one static
payload with opaque interpolation markers before inspection; their static code
is not dropped or misread as separate unclosed documents.

Head `c92989f6`, CI `38956633278`, Python 3.14 job `117161179308`, passes
**162 synthetic controls / 3 deselected**, but the real `html.py` normalization
still raises the same indentation error. This preserves the narrower pass and
the broader failure: the overlap control did not close the real-file failure.
Source inspection identifies literal Unicode U+2028/U+2029 data at `html.py`
lines 4645/4647. `str.splitlines()` counted them as source lines, unlike Python's
parser, shifting all later masks. The correction shares a physical-newline-only
offset map between lexical masking and AST diagnostics, preserving Unicode data
inside strings. Its regression places those characters before a formatted
literal and following function, and requires stable detected identities. Hosted
real-source evidence is still required; no producer source or limit changes.

Head `8dea129b`, CI `38958193538`, Linux Python 3.12 job `117166434807`,
passes **163 synthetic controls / 3 deselected** and gets beyond Python
normalization, but JavaScript inspection exceeds the existing **90-second**
subprocess limit. The limit remains unchanged. The next source replaces repeated
subtree spelling rescans with cached structural AST Merkle fingerprints and
cached identifier/literal feature bits, while lexical identities remain token
normalized. File/phase stderr markers identify the active unit if a refusal or
timeout remains. The v2 fingerprints are reindexed before initial admission;
no old observation is transferred as validation of this implementation.

Head `bfd58a9b`, CI `38960141939`, Python 3.11 job `117173253303`, retains
**163 synthetic passes / 3 deselected** but still times out at 90 seconds.
The phase markers show `ArchReviewPanel.tsx` completing and the lexer stopping
inside `.design-sync/previews/Bars.tsx`. A whitespace-only JSX text node can
have `getStart()` at its end, producing a zero-width mask and rewinding the
scanner indefinitely. Masks now use actual JSX text ranges, discard zero-width
ranges and advance only to an end strictly beyond the current token. A multiline
JSX control covers whitespace-only text and inert displayed `len(rows)` text.
The original timeout stays in force; no source file is skipped or waived.

Head `d50d2ced`, CI `38961770546`, Linux Python 3.12 job `117178532167`,
passes **164 synthetic controls / 3 deselected** and traverses the real JavaScript
files without the prior stall. It then refuses the generated-string payload at
`webapp/backend/app.py:2205`: a diagnostic message mentioning `<script src=…>`,
not an entry document. Real documents remain strict. Unknown/incomplete markup
inside used string payloads is instead represented by exact
`opaque-generated-source` records; static script/event code beside it remains
token-inspected. New opaque forms refuse the closed register, and their code is
not certified absent. Controls pin both the diagnostic-string case and a static
count beside an opaque script reference. No payload/file is silently discarded.


## Owner-approved role and compiled-output boundary (2026-10-16)

The six captures at head `56f79667`, CI `38963784801`, agree on **74,434**
records, proposal digest
`b376f6aa0e8b97457863cbc6619a89c4f1bf93d0cdcac1652a2f7f2e1cfc8d1c`.
All six execute 166 early synthetic controls and the real producer mutation
check; the full guard reports 167 passes and the two intentional unadmitted
register failures. These are superseded bootstrap observations, **not admission**:
they included pure engine computations and minified bundle identities. The owner
then required explicit module roles and source-to-dist coverage instead. The
uncommitted proposal was discarded; no active v2 register was published.

Every Python module under `cisco_toolkit/` and `webapp/backend/`, and the CLI
orchestrator, declares exactly one engine/interface role. Its module-owned
`<module>.py.atlas-role` companion is a closed JSON declaration; a literal
`__atlas_role__` constant is also recognized, but two declarations refuse.
Missing, ambiguous, computed, duplicate-key or orphan declarations refuse.
The application uses companions so frozen executable bytes remain intact. Every interface-role module
is a seed, and imports traverse all repository helpers until an engine-role
module. Pure owners such as `analyze.py`, `parse.py`, `ssot.py` and
`ui_projection.py` are terminals. Every engine's full local import closure is
checked for an interface dependency, including an unregistered intermediate
helper. Registered writers and report/API-library-backed writers cannot declare
engine role. The role assignments are explicit reviewable module metadata in this PR, not a
curated exclusion filename list. The module denominator comes from Git source
classes; a newly added module without its declaration fails. Future role changes are reviewed diffs; an interface
module becomes engine only after a reviewed extraction removes interface-side
computation and the corresponding register entries shrink.

Mixed modules remain interface and their detections remain visible debt:

| Mixed module | Pending extraction owner / named follow-up |
|---|---|
| `cisco_toolkit/html.py`, `cisco_toolkit/excel.py`, `cisco_toolkit/deck.py` | RC8-P1-H PR-3: move fact helpers to engine owners; keep rendering interface |
| `COLLECT_PARSE_V3_23_0.py` | RC8-P1-H follow-up `CLI fact assembly extraction`: separate fact assembly from collection/report orchestration |
| `webapp/backend/engine.py` | RC8-P1-H follow-up `AssessHub engine adapter extraction`: move fact/view ownership out of the renderer adapter |
| `cisco_toolkit/comparison.py` | RC8-P1-H PR-3 / follow-up `Comparison fact-owner extraction`: move delta and cutover fact helpers out of `html.py`; preserve the canonical comparison composer |
| `cisco_toolkit/attestation.py` | RC8-P1-H follow-up `Attestation registry input extraction`: remove the dynamic CLI import used to derive command claims |
| `cisco_toolkit/archreview.py`, `design.py`, `mop.py`, `crd.py`, `engagement.py`, `runbook.py`, `ops.py` | RC8-P1-H PR-2/PR-3 and follow-up `Document fact helper extraction`: separate mixed planning/fact helpers from their writers |
| `webapp/backend/summary.py`, `graph.py`, `cutover.py` | RC8-P1-H PR-1/PR-2: remove audited local facts; adapter remains interface |
| `webapp/backend/app.py`, `gates.py`, `protocol_portfolio.py`, `storage.py`, `execution.py`, `ingest.py`, `serve.py` | RC8-P1-H follow-up `AssessHub orchestration extraction`: isolate remaining computations from API/persistence/orchestration |

Other interface modules are renderer/metadata/export utilities or interface
adapters; their conservative exact detections remain allowances, not approval.
These named follow-ups are scope records, not new active branches or build streams.

### Named source-to-dist dependency

Every browser entry document, including checked-in compiled HTML, remains
inspected for inline/event/URL computations. The only covered generated tree is
`webapp/frontend/dist/`. Its imported minified modules are excluded from debt
identities only through the existing required **Distribution contract** job in
`.github/workflows/ci.yml`. Its steps **Capture the immutable source identity**,
**Rebuild the bundled AssessHub SPA**, and **Prove the SPA build reproduced the
immutable source** bind the commit/tree, install the locked source dependencies,
run frontend tests/build, and execute `.github/scripts/verify_checkout_immutable.py`.
The verifier compares every tracked file's mode and bytes against immutable HEAD,
requires index/tree equality, and refuses all unapproved untracked output,
including ignored output. Only `webapp/frontend/node_modules` is exempted as an
installation tree; compiled output is not allowlisted. Thus extra, removed or
changed compiled members fail, including an out-of-project source helper changed
during the build. Its existing refusal controls are in
`tests/test_release_supply_chain.py`; no verifier or gate is weakened.

The existing **Full source and frontend gate (unprivileged runner)** and
**Build and qualify Atlas.exe** in `.github/workflows/portable-release.yml` also
rebuild the tracked SPA and compare it with Git on Windows. These are additional
required evidence; the computation guard's mechanical compiled exclusion relies
on Distribution contract's stricter complete checkout inventory proof. No new
build job, frontend build policy or handoff protocol is introduced here.

The guard requires that named job/proof to be unconditional, after the immutable
identity capture and locked source build, with only its existing node_modules
installation allowance. Missing/conditional proof, changed build/source binding
or allowing compiled output refuse. Any checked-in executable under another
`dist`, `dist-hub`, `.next` or compiler-declared output tree fails as uncovered; new roots require a
reviewed source-to-dist gate. Third-party bundle contents follow the source's
package-lock terminal rule. Their minified identities never enter the register.
Negative controls cover uncovered bundles/entries, absent/conditional gates,
a changed build or output allowance, and inline computation in a compiled entry.
Fresh hosted captures and final-head gates remain required.

Initial role metadata, including the mixed comparison correction and module-owned
companion migration, is frozen in `2efe2fd77a1e67ea3c298408141a466e65cf3945`.
`ORIGIN` pins the initial application fact source; `ROLE_ORIGIN` independently
pins the reviewed role assignments. The actual detector bytes are bound separately
in every observation, rather than inferred from the source ceiling revision. The source ceiling
contains the foundation code, role metadata and this CI guard; engine-owned
values and golden/sample bytes remain unchanged. After admission every active v2
ancestor constrains the register, with all merge parents retained.

Generated-output discovery also reads TypeScript compiler `outDir` metadata.
An authored build-tool folder is not classified as compiled merely because it is
named `build` (the reference project has such source). Those authored modules
remain fully scanned; a declared `outDir: "build"` still requires its byte gate.
Controls exercise both sides, so this distinction is not a filename exception.


Head `7bed352b`, CI `38969214299`, Linux 3.12 job `117203575813`,
stops before census: **658 passed / 2 failed** in the existing client artifact
census. The role-only declarations invalidate the exact source blob binding for
`webapp/backend/app.py`, `webapp/backend/deliverables.py`, and
`cisco_toolkit/docmeta.py`. Their diffs against `56f79667` contain only the role
constant and blank lines. The full caller/import/URL/catalogue/route/header chain
is unchanged. The three Git blob pins are reconciled to those inspected sources;
no browser source, response suffix, catalogue member, classification, exemption
or refusal control changes. All source-drift mutations remain mandatory. This
failed bootstrap supplies no v2 capture or admission evidence.


Head `3e11a4dc`, CI `38970458240`, Linux 3.12 job `117207414176`,
passes all **660** client artifact controls and **201 synthetic controls / 3
deselected**, then refuses the real census because `external_import.py` imports
`load_workbook`. Source inspection shows a literal `read_only=True` input reader,
not a report writer; it remains engine-role. The class detector now recognizes
only the closed read-only call form: direct imported reader bindings, every call
with literal `read_only=True`, no keyword expansion, alias escape, constructor
or save operation. All other report-library imports remain conservative writer
seeds, including unused/ambiguous imports. Registered writers still refuse
engine role independently of libraries. Controls prove both the valid engine
reader and missing/false/dynamic read-only flags, saves, escapes and constructors.
No filename exception, role downgrade, production calculation or existing
refusal assertion changes. No capture/admission is claimed from this failed run.


Head `20f025a9`, CI `38971719812`, Linux 3.12 job `117211579325`,
passes **660** artifact controls and **209 synthetic controls / 3 deselected**,
then the engine direction check refuses `comparison.py -> html.py`. This is a
real mixed dependency: `compare_bound_pair` calls `_html.compute_snapshot_delta`
and `_html.compute_cutover_gate`. The owner-approved initial role correction
keeps `comparison.py` interface until its named fact-owner extraction; those
computations enter the register instead of gaining an engine exception. The
initial role basis is repinned to include this correction. No function body or
fact value changes, and this failed census supplies no admission evidence.


## V2 admission evidence (2026-10-17)

CI **38972829234**, head `34d62535c816b8af0e00709b864a4a156db4ea19`,
produced six identical proposals of **45,940** records. The tested synthetic merge
was `d573b5fb8a260574a5cd882282097386554a383a`, tree
`b7813c97286b857ae00fa1c563ba16b73e23a5d4`, identical to the PR head's tree.
Proposal SHA-256:
`4f8f0458786a89f2ea1152ec2b2346463f0938d72658734b3b7f32c030341cb0`.

| Hosted interpreter/platform | Job | Early synthetic controls | Real producer mutation | Full focused bootstrap |
|---|---|---|---|---|
| Linux 3.10.22 | 117215561327 | 209 passed / 3 deselected | pass | 210 passed / 2 admission failures |
| Linux 3.11.17 | 117215561545 | 209 passed / 3 deselected | pass | 210 passed / 2 admission failures |
| Linux 3.12.15 | 117215561484 | 209 passed / 3 deselected | pass | 210 passed / 2 admission failures |
| Linux 3.13.16 | 117215561492 | 209 passed / 3 deselected | pass | 210 passed / 2 admission failures |
| Linux 3.14.8 | 117215561346 | 209 passed / 3 deselected | pass | 210 passed / 2 admission failures |
| Windows 3.12.10 | 117215561360 | 209 passed / 3 deselected | pass | 210 passed / 2 admission failures |

The only focused failures are the deliberately inactive current-register and
active-entry assertions. Real class discovery and every refusal/stability control
pass. These bootstrap results are **not full-suite validation or 15/15**; importing
the proposal requires a fresh complete exact-head run, including origin/history
checks that the inactive stage had not reached.

The reviewed initial proposal grows/reindexes from v1's **20,619** records to
**45,940** (**+25,321**). This is a conservative detector-footprint count, not
25,321 new semantic defects. The wider class closure, named forms and normalized
identities explain the supervised reindex. Pure engine roles and compiled module
identities are excluded under the approved boundary; mixed modules remain visible
debt. This growth permission applies only to this unmerged proposal. Every active
v2 ancestor constrains subsequent data, including removals on all merge parents.

### Detector byte custody

The six proposals and source Git identities agree. Windows' four **raw detector**
digests differ because its checkout used CRLF. The bootstrap hash columns below are hosted observations. A local import-time
comparison attributed the difference to LF-to-CRLF conversion; that comparison
was outside the broader custody-verification rule and is **not accepted
validation**. Closing byte/source custody relies on the executed hosted gates,
not the local comparison. The admission
adds four exact `text eol=lf` attributes and a CI check deriving the byte-owner
set from the observer's actual metadata producer. Both HEAD/worktree attribute
policy must forbid filters, ident and encoding transformations, and every
executing detector must equal its raw committed bytes. No existing R1/R2 policy,
fixture, budget or timeout changes. The final head must demonstrate this stronger
byte gate and matching raw observations on every required leg.

| Detector | Canonical Git/LF SHA-256 | Bootstrap Windows/CRLF SHA-256 |
|---|---|---|
| `tests/interface_computation_guard.py` | `189ff4404e7c74a5506091175669d155cc332c000ae8b80f756f81da8a3bff3e` | `9bdce5e14c0fd9336204190d64f0b3b77e942aeeebeeebef760ad2f188f2525e` |
| `tests/interface_computation_lex.py` | `9bb4ac362db65f5da10f37a3c9c26766afe3f9956e4e46104fae2feaa6f4658c` | `0518e718deeeb7c7ac1842df4fefc2f1621fc7a2193d01244eef5803535e316e` |
| `tests/interface_computation_sources.py` | `3899f64555b04c0a5159cd5dfe34c07df50548a479a085b41577b2e6959d79ee` | `0c4b44a16dc22b263b1dd30b2d8452389571ea7c3f1f458cc3e83f99994eca0a` |
| `.github/scripts/interface_computation_ast.mjs` | `bc76ad9baddabf1b63611ad916812283d00cf8008c19df2a4aad205c8a26e2f9` | `0c7c6bf888f38c8142cf96936ad0d2893ac0364be2f2df62ccc037f0575131ff` |


## Frozen source-custody correction and declaration representation

On admission head `ab2d9d39`, CI `38974719516`, all six matrix legs pass the
synthetic controls, source observation, real-producer mutation and full active
register check, including the new detector-byte custody assertion. This is
focused hosted evidence, not 15/15. The installed Windows smoke, job
`117222809936`, fails with `PROTOTYPE_SOURCE_DIGEST_MISMATCH`: the role-only
statements altered eight source owners bound by the packaged experimental DSL
TCB. Its structural census separately binds `transition_legacy.py`. No frozen
asset, budget, digest validator, authority state or test is relaxed.

The implementation uses mandatory **module-owned companion declarations** as a
reversible representation assumption while the owner's format preference remains
open. All 125 application Python files are restored to their original foundation
source. Their roles live at the deterministic companion path
`<module path>.atlas-role`, with exactly the single JSON key `role` and enum value
`engine` or `interface`. This is CI source metadata, not a runtime dependency or
new application fact. No manual engine exception set selects the scanned scope.
A constant and companion together, unknown fields, duplicate keys, bad values,
orphan companions, missing declarations and an engine-tagged report writer all
refuse. Engine/interface direction and full helper traversal are unchanged.

The original download-source blob pins are retained again because the app,
deliverables and docmeta source bytes are restored. The TCB/data chain, every
frozen fixture, golden/sample byte and original source-custody check stays intact;
no regeneration or new measurement/qualification is claimed. A hosted migration
control compares the immutable initial role snapshot with the previous literal
assignments, requires every companion, and proves every application Python blob
in that initial migration equals the foundation source. It does not freeze later
application edits or prevent reviewed role changes with corresponding debt
removal. The current live module class must always have exactly one declaration.

Local metadata comparisons performed during the earlier import are recorded as
process-boundary mistakes, not validation. No local test/build/engine or formal
verification controller was run; nevertheless the standing doctrine also bars
local custody verification. All closing custody and receipt checks are hosted.
The complete exact-head gates and the same independent reviewer remain required.

The immutable companion/unchanged-source migration snapshot is `2efe2fd77a1e67ea3c298408141a466e65cf3945`; its role values are compared with literal-assignment snapshot `97813d79` by a hosted control.


Head `1d468ecc`, CI `38978164332`, passes the installed transition smoke
(job `117233534144`) and Distribution contract, preserving the frozen source
bindings without TCB regeneration. Every required matrix leg also passes the
complete active debt guard with companions. Required compiler/reference run
`38978164321`, job `117232584447`, then fails the existing architecture ownership
check because exact Python-module path rules did not yet name their new
companions. The downstream compiler/capacity walls remain **unmeasured**, not
passed or waived. The correction adds each companion beside its source in the
same existing component record; prefix-owned files already retain their owner.
No broad exclusion, new component, source edge permission, gate or budget change
is introduced. A Git-derived companion class parity control refuses missing,
unowned, ambiguous or different component mappings; unknown files remain
unmapped. Fresh complete exact-head evidence is required.


Head `b6da61f9`, compiler/reference run `38981238964`, job `117242334184`,
reduces the ownership failures to the CLI companion. Its Python entry module
already belongs to an explicit existing governance exclusion in the architecture
contract, not a runtime component. The parity check's component-only assumption
was incorrect. The correction compares the exact unique disposition **kind and
id**, adds the CLI companion to that same existing exclusion record, and retains
all previous refusal cases. Additional controls prove existing exclusion
inheritance while refusing a component-owned module's metadata-only exemption.
No source module is newly excluded, no blanket rule or edge permission is added,
and unknown metadata stays unmapped. Downstream capacity walls in the failed run
remain unmeasured; no bound or timeout changes. Fresh full validation is required.


Current main advanced to saved-plan merge `fdd6a7de` (#666), making head
`15bba79f` conflicted and preventing normal PR workflows. Local integration
`2920e79b` preserves the saved-plan source and both SSOT registry rows; main's
`docs/NOW.md` is restored in the same integration. Existing role declarations
remain mandatory; fresh hosted observations must determine the updated source
footprint. No earlier source-ceiling result certifies the new main.

Separately, prior webapp run `38981238995`, backend job `117244082337`, reports
the Scope workflow-contract failure: the synthetic command's quoted `-k` value
hid its trailing test path from the shared invocation reader, which therefore
conservatively inferred the default suite and demanded the markup-oracle switch.
The correction places the unchanged exact target before `-k`, and its workflow
control asserts the shared reader returns only that target. The full debt gate
is identified by its exact complete command. No Scope test, browser requirement,
command selection, oracle switch, budget or timeout is weakened or skipped.


## Initial source refresh after main #666 (v3, 2026-10-17)

Head `ffcce816`, CI `38984167554`, Linux 3.10 job `117251895072`, passes
**222 synthetic controls / 3 deselected** and the real producer mutation, then
fails the active v2 equality gate: newly merged saved-plan source adds and removes
exact sites. The hosted observation reports **46,135** records, fingerprint
`e31da8612c2631be2ffa1ba36cc817174d8badf340c78058e7cd416af25edd47`
under the old v2/origin metadata. This is not an admitted register or a new
semantic-defect count. The old 45,940 source snapshot cannot certify the new main.

The supervisor explicitly permits initial register growth in this unmerged PR.
Version 3 therefore binds its immutable initial application source to current
main `fdd6a7de`, preserving all detector forms and refusal controls. The initial
role assignment/migration stays pinned separately at `2efe2fd7`. Version 2 is
historical **only** for commits ancestral to main-integration anchor `2920e79b`;
a later v2 reset fails even if a subsequent commit restores v3. Version 1 keeps
its original `3d3bca01` cutoff. Unknown policies still refuse. Every active v3
ancestor, including all merge parents, is a strict subset ceiling; removals and
resurrection remain enforced. No application/schema version is changed.

This does not waive a gate to accept feature-branch computations. Fresh matching
six-leg source-bound observations and real-producer/refusal controls must precede
admission, then every protected/applicable full workflow must pass on the exact
admission head. After this proposal merges its register may only shrink; this
initial-development migration is not available to a future old-policy reset.


## V3 updated-main admission proposal (2026-10-17)

CI `38985178207`, head `7e0c540a8959fa51a4e3f498c19c727273f08855`,
reports the same **46,135** records and proposal fingerprint on all six legs:
`61e173d9f59819a66420f7c8b49cdb21c9ba9f8d3c5caaba3d418d070b88c705`.
Every leg passes **223 early controls / 3 deselected**, the real producer mutation,
and **224 full focused controls**, with only the two deliberately inactive
register assertions failing. No complete default/UTC or whole-workflow pass is
claimed from this bootstrap. The active proposal is formatted directly from the
hosted Windows output; all admission/source/history/custody checks execute on
hosted runners, not in a local receipt/controller comparison.

| Hosted interpreter/platform | Job |
|---|---|
| Linux 3.10.22 | 117255214895 |
| Linux 3.11.17 | 117255214861 |
| Linux 3.12.15 | 117255214892 |
| Linux 3.13.16 | 117255214735 |
| Linux 3.14.8 | 117255214870 |
| Windows 3.12.10 | 117255215021 |

The Windows producer reports checkout `1cd16bf8cbda00de30cfe5c580db3884eb5667e2`,
tree `3d99a8952c06374c55cd516ba7707ca2af7945c3`, and the following raw detector
observations. Their Git-byte/attribute equality control is part of the executed
hosted suite; local metadata comparisons are not used as closing evidence.

- `tests/interface_computation_guard.py`: `f50146ef6cb92f37c44682d37d75b4af809e6a88ef3e0f45aa29b4bf9bce1f03`
- `tests/interface_computation_lex.py`: `9bb4ac362db65f5da10f37a3c9c26766afe3f9956e4e46104fae2feaa6f4658c`
- `tests/interface_computation_sources.py`: `36e6e9f85de7803901b6979ec25d29d986440142428a4128f95444a17e23686e`
- `.github/scripts/interface_computation_ast.mjs`: `bc76ad9baddabf1b63611ad916812283d00cf8008c19df2a4aad205c8a26e2f9`

Disclosed initial footprint: v1 **20,619** -> v2 **45,940** -> current-main v3
**46,135**, a net **+25,516** over v1 and **+195** over the earlier main snapshot.
These are conservative detected-site totals with additions/removals/reindexing,
not counts of new semantic defects. This supervised initial refresh is confined
to this still-unmerged PR. No application/schema version, budget, timeout,
qualification state or frozen/golden/sample byte is changed. Main #666 is
preserved and its board restored. Fresh exact-head all-15, CodeQL and applicable
complete workflows, then same-reviewer re-review, remain mandatory. No PR merge
or release is authorized by these observations.


Admission head `2090a81e`, compiler/reference run `38986647728`, job
`117259695658`, passes the Python compiler/governance test stage, then the exact
tracked-tree compile refuses `.atlas-role` because the format is not yet in its
strict text/language vocabulary (root CLI companion and extension errors).
The correction registers only this JSON metadata extension and its deterministic
`application/json` media type. It is structured data, never executable source;
all paths still require architecture ownership, source/Git binding, privacy,
and the full module-role schema/cardinality/orphan checks. Unrelated unknown
extensions continue to refuse. A real mini-repository compiler control checks
both the module and declaration records end-to-end. No census-depth deferral,
privacy bypass, gate, budget or timeout change is introduced. Downstream
capacity walls from the failed compile remain unmeasured, not accepted.


## Full source/frontend timeout evidence and immutable-read correction

Head `f70dbc23`, portable run `38988920400`, full source/frontend job
`117266732235`, is **cancelled at the unchanged 120-minute limit**. The complete
Python command returned successfully; all **537 frontend tests / 38 files** then
passed. The job entered the production build and was cancelled before that build
and its final Git comparison could finish. This is cancellation/timeout evidence,
not a passed whole gate or a test assertion failure. No narrower run replaces it.
The independent full Windows matrix job `117266989522` passed **19,965 tests**;
its active debt test took **115.82 s** and its initial role migration **25.23 s**.
The cancelled whole-gate migration took **33.79 s**. Those are scoped hosted
observations, not a recovered gate or a claimed runtime saving.

The new guard had launched a Git process for each immutable source/role file and
for each of the initial migration's byte comparisons. It now reads the complete
Git name/type/object census once and fetches selected immutable blobs through a
strict `cat-file --batch` exchange. Unrelated large data/graph blobs are not
materialized. Object identity, type, declared size, separators and trailing bytes
must match; selected symlinks/gitlinks refuse. No file is extracted, imported,
evaluated, content-normalized or cached from mutable worktree state. Current
workspace inputs remain live and uncached. Hosted controls compare batch bytes
with independent Git reads over Unicode/space paths and shared blobs, prove a
dirty worktree cannot alter an immutable result, and refuse malformed objects,
framing and symlinks. The same initial role/value/source assertions remain.

This is an implementation efficiency correction, not a timeout change or waiver.
The complete original Python/frontend/build/source-comparison commands and the
120-minute job limit remain literal. The original Node parser limit stays 90 s.
Fresh exact-head hosted evidence must measure the effect and pass the entire
gate; no local timing, custody controller or runtime probe is performed. The
board-only main update `d3c79ae0` is integrated with this substantive correction,
and main's `docs/NOW.md` restored in that same push, not as a standalone board
push while checks run. No application source or frozen/golden/sample byte changes.

## Browser document suffix closure

Static review of `f25e53a5` found that the discovery class covered `.html` but
would miss the same inline computation in a newly added `.htm` or `.xhtml`
entry. The class now includes case-insensitive HTML/HTM/XHTML/SVG documents,
through immutable source reads, discovery, local script closure, AST/lexical
inspection and compiled-output coverage. SVG entries can execute scripts or
event handlers when opened as documents, so they cannot be treated as inert
image assets merely by suffix. New controls exercise alternate-case document
entry calculations and uncovered compiled XHTML/SVG refusal; immutable-reader
parity includes these formats. Existing registered footprints and all original
gates, assertions, budgets and timeouts remain unchanged. This correction
requires fresh exact-head hosted evidence; the superseded `f25e53a5` results
are not final validation.

## Windows Python identities and registered package writers

The module class also includes case variants of `.py` and of the owned directory
names. Repository import lookup conservatively follows Windows case-insensitive
identities while retaining the actual Git path in every debt record. Case-colliding
Python files refuse rather than depending on which platform resolves them. This
closes uppercase `.PY` helper/missing-role escapes and mixed-case engine-to-interface
edges. Immutable reads, closure discovery and Python AST/lexical dispatch use the
same Python-file predicate; hosted controls cover each boundary.

Static review also found that excluding every package initializer from the
registered-writer obligation could mistake a registered package's own `__init__.py`
writer for an engine terminal. The registered leaf is now explicitly required,
whether it is a module file or package initializer; parent initializers cannot
substitute for an absent leaf. Normal/mixed-case package-writer refusal controls
join the existing absent-leaf controls. No module role, existing exact allowance,
source ceiling, test, gate, budget or timeout is relaxed. The already-green focused
controls on `0a4d2937` remain earlier-head evidence; this correction needs fresh
exact-head execution and complete workflows.

## Inactive-history refusal

Static review of `b7e0ceb6` found an actual ratchet loophole: historical v3
records with a non-active stage did not constrain the active register. A later
commit could set `observation_required`, remove an entry, then restore the entry
and active stage before the final CI run. Unknown historical stages were also
silently ignored. This is not closed by requiring only the final head to be active.

Only the immutable ancestry through initial empty v3 capture `7e0c540a` may use
`observation_required`. A later inactive capture fails its ancestry check;
unknown/non-active stages and foreign source origins fail the historical policy
check. Every remaining v3 record must be active and constrain removals. The
existing v1/v2 ancestry cutoffs and all-parent history traversal remain intact.
New pure refusal controls and real-Git positive-bootstrap/disable-delete-restore
controls exercise this boundary. The existing active register, source ceiling,
module roles, detector forms, whole-suite commands, budgets and timeouts stay
unchanged. Fresh exact-head hosted execution is required; preceding successful
guards alone do not certify this correction.

## Complete-command success is not a passed job

On `b7e0ceb6`, portable run `39001989988`, job `117306891888`, the complete
Python/frontend/build/source-comparison step is **SUCCESS** (ended 06:18:23 UTC).
Python returned successfully, all **537 frontend tests / 38 files** passed, and
the production build completed. The job is nevertheless **CANCELLED** at its
unchanged 120-minute window during post-job cleanup (ended 06:18:28 UTC).
This remains negative whole-gate evidence, not a green required context or
recovered budget. The original commands and cleanup still have to fit the window.

The immutable role-origin/migration consumers had fetched all browser/helper
source blobs despite using only the complete module-role class. They now fetch
that class while retaining the entire Git name census, every owned Python module,
every declaration, and all previous role/value/raw-byte assertions. Full fact
discovery keeps the full source mode; current workspace reads stay uncached.
Hosted byte-parity controls compare both modes, cover collector/backend/toolkit
roles, retain outside helpers in full mode, and prove dirty worktree changes
cannot alter either immutable result. The effect on the complete job remains
unverified until a fresh required context succeeds; no local timing is used.

The preceding head's reference workflow `39001989991` succeeded with measured
**WARN** capacity: release census **94.19%**, expanded projection **92.36%**, longest
JSON token **85.00%**; zero walls at/above the unchanged **95%** failure threshold
and zero unmeasured. These warnings remain capacity risk for review, not waivers.
Fresh corrected-head capacity evidence is still required.

## Relative and unresolved Python loads — remaining P1-1

The independent re-review of `0dfa372f` verified P1-2 and P2 closed but found
one remaining P1-1 edge: `import_module('.metrics', package='report_helpers')`
ignored its package and omitted the helper. A moved count could disappear from
inspection, and an engine could load an interface without the direction check.
The earlier 15/15 and the board-only `630a0fe8` integration do not close this edge.

`tests/interface_computation_sources.py :: dynamic_imports` now resolves literal
relative names against their actual positional or keyword package, before both
closure and engine-to-interface validation. Import aliases, named function
aliases and literal `getattr` spellings retain the same target. Missing packages,
invalid relative levels, argument expansions, computed names and nonliteral
packages refuse, including a nonliteral package supplied with an absolute name.
`__import__`, spec factories, module-from-spec calls and loader operations refuse
unless the exact call site has an explicit target allowance. Importer references
escaping into callbacks, returns or containers also refuse. A refused load is
never silently represented as an empty dependency set or an arbitrary-production
fallback. These checks apply to every reached helper and every engine owner,
including engines not reached by any interface.

The exception owner is `DYNAMIC_IMPORT_ALLOWANCES` in that same source module.
Each row binds the actual repository path, enclosing symbol, normalized call
expression, a single occurrence and the exact dependency targets. It exempts
neither a file nor a function from scanning; its targets enter the ordinary
closure and direction checks. A moved/changed/duplicated call is refused. The
allowance inventory test requires every proposed site to exist exactly once,
with non-wildcard targets; the writer selector's targets must exactly equal the
registered writer modules. These are author proposals for the same independent
review, not a claim of prior reviewer approval or runtime input confinement.

The proposed sites are the attestation collector selector and source probe;
the AssessHub registered-writer selector and optional-library probes; the
cryptography distribution probe; Graphify's pinned module selectors and overlay
specs; and the existing R2, historical-database and browser-E2E file loaders.
Their exact targets are code-owned in the allowance rows, not duplicated here.
The two backend package spellings resolve to the same repository writer owners.
File-loader targets name the repository source they load, including the synthetic
fixture rather than its temporary runtime module alias. A broader runtime input
or different target requires a reviewed allowance change; this static guard does
not execute or certify those selectors' runtime input validation.

New controls require an outside-role relative helper to be scanned, refuse a
registered count moved there even after its original allowances are deleted,
and require the specific engine-to-interface direction error for a relative
engine load. Both roles have unresolved-name/package, builtin-import, spec and
loader refusal controls. Alias, reflection, callback, exact-allowance target,
move/duplicate refusal and inert-edit controls cover the same boundary.

Replacing the old arbitrary-production fallback with exact targets can change
the source census. The fact register remains shrink-only against every active
ancestor; no reset, new historical cutoff, weaker assertion, source exemption,
budget increase or timeout increase is authorized by this correction. A closing
claim requires the corrected hosted census and all fifteen required checks on
the final head. Until then the correction is implemented but not verified.

### Hosted correction observation and pending admission

On correction head `84b4d8070250234d76e7037b7915d33ab21d5633`, CI run
`39027083619` produced the same census on Linux Python 3.13 and 3.14:
**36,891** detected sites, fingerprint
`c522b7abc383fcfc188b6144f8e5f06471ae228b72e47831fca8930d0e5cec80`.
Both executed **325 early controls**. Their complete focused guard reported
**327 passed, one failed**; the sole failure was the unchanged register's stale
entries, with an empty unregistered/resurrected-site difference. The real-producer
canonical-fact mutation also passed on the 3.14 leg. Jobs `117380234143` and
`117380234186` are the hosted evidence; this is a failed head, not admission or
15/15. The earlier review finding and all prior failures remain negative evidence.

The prepared register update copies the proposal from that hosted 3.14 job. Its
Git diff is **9,244 deletions and zero additions**, shrinking 46,135 to 36,891.
These removals reflect elimination of the arbitrary-production import fallback;
they are not claims that 9,244 duplicate engine facts were fixed. All interface
role seeds, registered/API/library-backed writer discovery, helper traversal and
engine direction checks remain enforced. No application or role changes supply
these removals, and the source ceiling/history validators are unchanged.
The proposal was decoded only to edit the register; no local census or custody
controller supplied validation. Final admission and all required checks must be
executed on the next hosted head. An additional push remains subject to the
supervisor's answer to the explicit one-push constraint.

### Per-allowance refusal controls and removal categories

The supervisor authorized `26b9a978` and narrow repair/admission pushes through
15/15, with no unrelated work. Each row of `DYNAMIC_IMPORT_ALLOWANCES` now has
its own parameterized control: its exact target set is returned, deleting its
allowance refuses, and changing its path, symbol, call argument or occurrence
refuses. A second per-row control follows those actual targets through a helper
and requires the engine-to-interface error, even for a nominal third-party name
when repository source exists. Allowances do not bypass the direction check.

The admission-specific hosted control compares the fixed `84b4d807` and
`26b9a978` registries, asserts a strict subset, and requires every removed path to
be outside the corrected snapshot's interface closure and outside the mandatory
role-declaration class. It pins that admission, not the size of future registers.
No role or token/AST identity change explains any of these removals; their cause
is replacement of the arbitrary-production dynamic-import fallback. Computation
forms themselves, the current source ceiling and every active-ancestor ratchet
remain unchanged.

The patch's removal categories are:

| Source category | Removed rows |
|---|---:|
| Master Reference compiler/governance/release helpers outside the reviewed app/report import closure | 4,652 |
| `.github` CI and qualification scripts outside that closure | 1,780 |
| `tools` maintenance/qualification helpers outside that closure | 1,720 |
| `portable` packaging/release helpers outside that closure | 860 |
| `research_lane` helpers | 148 |
| Root embedding/local-model research scripts (`embed_qbank.py`, `ollama_judge.py`, `ollama_recall.py`, `ollama_retrieval_judge.py`) | 55 |
| `webapp/dev.py` development launcher | 7 |
| `webapp/frontend/e2e-real/serve_real_backend.py` fixture server | 9 |
| `.claude` hook | 10 |
| `setup.py` packaging | 3 |
| **Total** | **9,244** |

These are structural census removals, not claims of no computation in those
modules or of 9,244 repaired application facts. For example, the removed Master
Reference rows include `master-reference/release/pdf_report.py`; the app's
registered report writers remain fully scanned. The reviewer can check both the
boundary and the exact negative controls rather than infer product remediation
from the smaller count. No `cisco_toolkit/`, `webapp/backend/` or CLI-orchestrator
row was removed by this admission. Exact sampled row identities are included in
the completion comment; the full deletions remain in the Git diff.

### Opaque loader receivers remain recognized operations

Static follow-up inspection found an additional shape of the same P1-1 class:
`make_loader().exec_module(module)` could lose the known loader method because
its receiver had no statically qualified name. Discovery now retains the named
import/loader operation even when a factory or subscript receiver is opaque.
Literal `getattr` and named aliases retain that operation too. These forms must
refuse outside an exact allowance; no unresolved receiver becomes no dependency.
Both roles have factory, subscript and literal-getattr refusal controls, with
additional alias controls. This changes no allowance target, role, application
source, fact-register entry, budget or timeout. Hosted validation remains required.

### Discovery lifetime and the unchanged carriage timing gate

On `4e9b28f6`, the complete Linux 3.12 default suite failed only the cold first-page
budget: 912.1 ms versus its unchanged 300 ms ceiling; 20,026 other tests passed.
The same job's earlier G14 run measured 195.3 ms at the same gate, and the failing
run's following page measured 188.9 ms. This is real negative evidence. The
application/test sources on that path are unchanged; process/host timing effects
remain a hypothesis, not a confirmed cause. PR comment 6237191013 records the
full-job retry rationale. GitHub did not accept that retry while CI was active;
no rerun was accepted and no narrow test replaced the complete job.

Follow-up code inspection identified a separate guard-owned retention hazard:
recursive visitor/qualifier function-cell cycles could retain their captured
AST/alias dictionaries until cyclic garbage collection. Discovery now breaks
those bindings after their last use. No manual collection, cache priming, request
warm-up, timer change or application change is added. The parser's source reads,
closure decisions and returned targets remain the same.

An isolated hosted subprocess control disables cyclic GC only inside that child,
uses an immutable `4e9b28f6` discovery module as a negative control, and requires
the current module to release an unreachable input AST without cyclic GC. It
cannot collect or warm the main test process. This proves the lifetime property
if it passes; it does not establish that retention caused the observed 912.1 ms
budget violation. The original timing failure remains recorded even if subsequent
complete jobs pass. All original assertions, budgets and timeouts remain intact.

### Repeated timing violation and detector payload lifetime

The `453ed3b1` full Linux 3.12 suite reproduced the same first-page budget failure:
744.7 ms versus the unchanged 300 ms limit, with 20,027 other tests passed. Its
earlier G14 first page measured 142.5 ms; its following page measured 148.4 ms.
The isolated discovery AST-lifetime control passed. Therefore that repair did
not establish a resolution of the timing violation. No blind retry or claim of
contention is justified by these observations; the timing cause remains open.

Further source inspection found the Python fact detector's local visitor class
captured each source buffer and emitted-fact collection in a type/closure cycle.
The detector now uses one module-level visitor class with per-source instance
state and a module-level recursive verdict helper. All detection conditions,
normalization, source evidence and identities are intended to remain identical;
the current register and existing mutation controls still require that. No
application, timing test, timer, warm-up, collection policy or budget is changed.

A separate isolated subprocess probe disables cyclic GC only inside that child,
loads the immutable `453ed3b1` detector as a negative control, and requires exact
emitted-output parity while the current detector releases normalized source
buffers and caller-discarded facts without cyclic collection. It cannot collect
or prime the main pytest process. A passing probe establishes that payload
lifetime property, not the cause or resolution of either timing violation. Both
full-suite budget failures remain negative evidence for independent review.

## PR-1 presentation-only JSX footprints

The owner approved extracting exactly three inline `display: "block"` declarations
into one dedicated stylesheet rule. These CSS values are presentation, not engine
computations. In hosted CI `39079414845`, job `117533311971`, the unchanged detector
conservatively captured each complete JSX return because it contained the exact
verdict-vocabulary literal `"block"`. The checkout `ed8349b6` has the exact
`b4ecd442` tree, `52c9cb080067792b1e61a0d526ad9791924c7d35`.

These are the **unadmitted candidate** footprints removed by that presentation
refactor; they were never added to the register. Lines below refer to `b4ecd442`.

| File and symbol | JSX return line / CSS trigger line | Old `fact-decision` fingerprint (occurrence 1) |
|---|---|---|
| `webapp/frontend/src/components/TopologyGraph.tsx :: TopologyGraph` | 305 / 388 | `d6b8a1719cdef1f47139aa6121410599e4509375bb0639466a8009ad6c925838` |
| `webapp/frontend/src/pages/Campaign.tsx :: CampaignPage` | 672 / 693 | `9d9e32e0e90a3bea4a8c2031d5602556b283aa5ee7886a85ccfa9bbe5f420be7` |
| `webapp/frontend/src/pages/Snapshot.tsx :: SnapshotPage` | 997 / 1078 | `6ce0ceb560899b0b7747e611089b7133e0a21906247472896d84031c8f7884db` |

`styles.css` ends with one rule for `svg.atlas-ssot-block`,
`a.atlas-ssot-block` and `iframe.atlas-ssot-block`: `display: block`. The dedicated
class is used only at those three sites; no other markup is restructured. Each
selector has specificity `(0,1,1)`. The three authored stylesheets contain no
competing display declaration matching these elements: the campaign link's
existing `panel` class does not set display, and the projection-specific display
selectors do not match. No `!important` or runtime style override is introduced.
Independent review must explicitly verify the unchanged rendering/cascade,
three-site-only scope, old fingerprint/file/line disclosures and zero additions.

This refactor leaves every detector, boundary-register rule and engine
computation byte-unchanged. It admits no boundary record and adds **zero** debt
identities. From main `0491291c`, PR-1 deletes the separate 107 stale registered
identities identified by that hosted census: **36,891 to 36,784, 107 removals,
zero additions**. The final post-#682 census and shrink-only checks must still
execute on GitHub. Tracked frontend dist is rebuilt and received through the
existing hosted handoff, never locally.

## PR-2 local wave-gate handoff

`docs/rc8-p1-h-pr2-wave-gate.md` records the engine owner, closed vocabulary, consumer scopes,
stronger restriction policy, byte expectations and pending hosted tests. The current deletion-only
edit removed 26 retired-symbol rows; local review of `8b0d10dd` removes four further stale verdict-symbol
occurrences (`fleet_gate` and `combined_gate`, occurrences 2 and 3). The cumulative edit is 30 deletions,
zero additions, with 36,861 rows provisionally retained. This is not a current detected census:
retained functions also lose expressions and lexical occurrences, whose stale register rows must
be removed from the authorized hosted observation after the #682 schema rebase. No detector,
role, boundary, assertion, budget or timeout is changed to manufacture a subset. No local
inspector or tests run, and no push/CI is authorized by this handoff.
