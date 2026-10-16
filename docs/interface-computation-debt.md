# ADR 0008 interface computation ratchet

RC8-P1-H PR-0 implements the owner's binding foundation direction in #672.
The machine-readable register is `interface-computation-debt.json`; it is not
an approval of the computations it records. Initial admission requires the
hosted observation and review. The initial `observation_required` stage fails CI; the captured inventory is now admitted as the first active ceiling, pending fresh whole-suite validation.

## What the gate checks

The scanner discovers authored modules under `webapp/frontend/src`,
`webapp/backend` (excluding the engine adapter), and `atlas-scope/src`.
Generated TypeScript is scanned too; test modules/fixtures have explicit path/type exclusions.
It also scans the Explorer HTML script, workbook writer, document metadata and
all `writer_module` owners declared in the artifact SPECS registry, plus Scope's
`tools/lib/compile-model.mjs` coverage compiler and the Python HTML report writer.
A new module
under a root enters without a hand-kept file list.

Python's AST and the locked TypeScript AST parser identify named analysis
functions, counts, reductions, key counts, counter updates, numeric thresholds,
fact arithmetic and graph worklists. A separate forbidden-pattern scan also
covers generated code inside templates. Source is parsed as data; inspected
application code is never imported or evaluated. Parse failures refuse.

Every allowance is one file, qualified symbol, operation rule, normalized
expression digest and occurrence. There are no module-wide or symbol-wide
exemptions. Comments/formatting do not change AST identities; altered thresholds,
new counts and a second identical call require admission and fail this ratchet.
The detector conservatively includes existing presentation/infrastructure
calculations: an entry is an exact legacy footprint, not an assertion that every
length check is a network fact. This does not prove arbitrary program semantics
or eliminate the independent review requirement.

The original reviewed source `9112a16e` is an immutable maximum footprint.
The active register must equal current detections, be a subset of that source,
and be a subset of **every active ancestor register**. Removing code requires
removing its entries in the same PR. Restoring both code and a removed allowance
still fails against history. Synthetic controls prove growth, duplicate-site,
changed-disposition, stale-entry and resurrection refusal. This first ceiling
does not authorize future exemptions or changing the detector to hide a finding.

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
