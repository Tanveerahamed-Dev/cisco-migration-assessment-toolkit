# ADR 0008 interface computation ratchet

RC8-P1-H PR-0 implements the owner's binding foundation direction in #672.
The machine-readable register is `interface-computation-debt.json`; it is not
an approval of the computations it records. Initial admission requires the
hosted observation and review. The initial `observation_required` stage fails CI.

## What the gate checks

The scanner discovers authored modules under `webapp/frontend/src`,
`webapp/backend` (excluding the engine adapter), and `atlas-scope/src`.
Generated types and test fixtures are excluded by explicit path/type rules.
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
The correction uses `HTMLParser`, scans entity-decoded event bodies, JavaScript
URL bodies and nested srcdoc, and refuses external, unclosed or self-closing
script sources. Dedicated malformed-end-tag and attribute controls accompany it.
Its resolution remains **not verified** until the corrected head's CodeQL and
hosted controls pass. No alert is dismissed and no checker is suppressed.

The corrected observation must bind its source commit/tree and both detector
digests before its candidate inventory is reviewed. Initial observations are not
silently transferred across detector revisions. All 15 protected contexts and
applicable complete workflows remain required before the independent-review stop.
