# ADR 0008 interface computation ratchet

RC8-P1-H PR-0 implements the owner's binding foundation direction in #672.
The machine-readable register is `interface-computation-debt.json`; it is not
an approval of the computations it records. Initial admission requires the
hosted observation and review. The v1 proposal at `db5f5675` passed 15/15 but
independent review blocked discovery, detection and lexical identities. The
supervisor's ruling in #673 comment `6218966243` authorizes a wider, reindexed
initial register in this PR. Version 2 is currently `observation_required`;
this deliberately fails admission until fresh hosted captures are imported.

## What the gate checks

The guard ratchets a **closed, named set of detected computation forms**. It is
**not proof of absence of computation**. Undetected forms require review and are
not certified absent. ADR 0008 point 4's mechanical claim is: every detected form
is registered and shrink-only after this proposal merges.

Discovery is class-derived rather than a prefix/special-file selector:

- Every repository browser `*.html` entry document, including inline scripts,
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
new counts and a second identical call require admission and fail this ratchet.
The detector conservatively includes existing presentation/infrastructure
calculations: an entry is an exact legacy footprint, not an assertion that every
length check is a network fact. This does not prove arbitrary program semantics
or eliminate the independent review requirement.

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
| Divergent pre-change gate | `webapp/backend/cutover.py :: _gate`; `cisco_toolkit/mop.py :: _join_group_records / _worst_readiness` | One engine-owned wave gate; PR-2 |
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
Overview's readiness groups are validated owner records, but no unified per-wave
gate exists yet (PR-2). Saved-plan list/revision/select/export belongs to
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
orchestrator, declares exactly one module-level literal `__atlas_role__`.
Missing, ambiguous or computed declarations refuse. Every interface-role module
is a seed, and imports traverse all repository helpers until an engine-role
module. Pure owners such as `analyze.py`, `parse.py`, `ssot.py` and
`ui_projection.py` are terminals. Every engine's full local import closure is
checked for an interface dependency, including an unregistered intermediate
helper. Registered writers and report/API-library-backed writers cannot declare
engine role. The role assignments are reviewed source in this PR, not a curated
exclusion filename list. Future role changes are reviewed diffs; an interface
module becomes engine only after a reviewed extraction removes interface-side
computation and the corresponding register entries shrink.

Mixed modules remain interface and their detections remain visible debt:

| Mixed module | Pending extraction owner / named follow-up |
|---|---|
| `cisco_toolkit/html.py`, `cisco_toolkit/excel.py`, `cisco_toolkit/deck.py` | RC8-P1-H PR-3: move fact helpers to engine owners; keep rendering interface |
| `COLLECT_PARSE_V3_23_0.py` | RC8-P1-H follow-up `CLI fact assembly extraction`: separate fact assembly from collection/report orchestration |
| `webapp/backend/engine.py` | RC8-P1-H follow-up `AssessHub engine adapter extraction`: move fact/view ownership out of the renderer adapter |
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

Initial role metadata is frozen in `7117ca872198c412ff664f0b32d715aaac3bd3ab`.
The complete class boundary is pinned by `ORIGIN` before its hosted capture;
`ROLE_ORIGIN` independently pins the reviewed role assignments. The source ceiling
contains the foundation code, role metadata and this CI guard; engine-owned
values and golden/sample bytes remain unchanged. After admission every active v2
ancestor constrains the register, with all merge parents retained.

Generated-output discovery also reads TypeScript compiler `outDir` metadata.
An authored build-tool folder is not classified as compiled merely because it is
named `build` (the reference project has such source). Those authored modules
remain fully scanned; a declared `outDir: "build"` still requires its byte gate.
Controls exercise both sides, so this distinction is not a filename exception.
