# W2c: core projection endpoint and screens

Status: **candidate held for a final JSON-value boundary refutation; unpublished**.
The frontend and portable-resource repair have focused and independent verification; a later
backend probe below supersedes the earlier passing boundary evidence for nonfinite numbers.
This record belongs
to the existing `codex/core-screens` branch and `ui-projection-2` checkout, created from main
`a0c727bd` after W2b merged. `docs/NOW.md` remains the live queue.

## Backend contract

The two declared-response-model routes serve `ui_projection_transport/1` over the unchanged
`ui_projection/1` owner. The view route returns bounded first pages; the list route accepts only
schema-derived primary-list pointers. Both read one exact bound store snapshot, validate the
whole engine document before selection, and validate the returned transport object. They retain
all six evidence states, withheld lists with items, owner ordering/indexes/pointers, engine cap
disclosures, engine metadata and the common limitations registry. Device host strings are passed
unchanged; missing snapshots are 404 and unknown hosts retain the owner's withheld document.

Pagination bounds primary lists, not total projection computation or nested row bytes. Page
totals count projected rows and are distinct from the engine's census facts. The schema adapter
mechanically hoists owner definitions into OpenAPI; independent reverse-mapping proves equality
with a fresh owner schema. The offline exporter creates only a temporary empty store, emits
deterministic UTF-8/LF JSON, and has a nonwriting drift check.

Observed test-first negatives: three missing-route/model/schema failures, then four forged-page
metadata failures (returned count, total, `has_more`, pointer). The corrections retain strict
validation rather than coercing or dropping fields. Focused API/raw/expensive-GET selection:
**70 passed**, both on the existing host runtime and on an isolated overlay with FastAPI
**0.141.1**, Pydantic **2.13.5** and Starlette **1.6.0**. The latter reads other installed host
test dependencies; it is not claimed to be the fully hash-locked portable environment.
An initial root invocation named a nonexistent raw-test file and exited 4 without running tests;
the correctly named selection is the separate passing result.

The full backend selection then passed **1,262 tests / one existing Windows symlink-privilege
skip** in 404.246 seconds, with all three Scope real-toolchain, hub-build and browser-markup
requirements enabled. JUnit reports zero errors/failures. The pinned Starlette runtime emits
its existing TestClient/httpx deprecation warning; it was retained, not suppressed.

Independent review on API source SHA-256
`5f0090eaaa0c78957adb6faeaa82e9c134a31eb159ddc7bcb87decffbd1c194c` passed **115 preservation
and paging probes** across five views and 28 primary lists, plus **11 adversarial probes**.
Malformed complete source outside the requested page/view is rejected, and corrupt-store
authority returns 409. No actionable endpoint defect remained in that bounded review.

Actual app OpenAPI exports from the host FastAPI/Pydantic versions and the portable hash-locked
versions are byte-identical at SHA-256
`7c1240ee7338740f182510435e74aa6563525670db7a00bedf862216d231c333`.
CI now exports that live contract before the frontend's nonwriting generated-type check; the
exporter itself participates in the fail-closed webapp path policy. Its two initial guard
failures were followed by **39 passing scope/generation-wiring tests**.

Three sequential TestClient requests per view and limit measured the following sample-only
medians, including source parsing, whole-document validation, response validation and serialization:

| View | Limit 1 seconds / bytes | Limit 50 seconds / bytes |
|---|---:|---:|
| Overview | 0.624 / 25,257 | 0.604 / 33,911 |
| Trust | 0.622 / 33,314 | 0.613 / 40,855 |
| Inventory | 0.590 / 34,999 | 0.683 / 263,907 |
| Findings | 0.591 / 19,909 | 0.746 / 284,757 |
| Device | 0.159 / 51,842 | 0.241 / 274,133 |

All three payload hashes agreed within each case. This is 30 requests over the checked-in
synthetic sample, not a load test, worst-case bound or network-server latency claim.

## Portable runtime closure

`jsonschema==4.26.0` moved from development-only to the canonical base runtime and both
compatibility requirement files. The dependency contract now requires the exact runtime/release
pin and rejects missing, duplicate, widened or indirect declarations. The existing portable
hash lock already contains the needed distributions; it was not regenerated.

An isolated Python 3.12.10 environment installed that exact hash lock and passed `pip check`.
PyInstaller **6.22.2** with hooks **2026.7** inferred **62 bundled distributions**: the existing
46 plus 16 schema/format dependencies at their locked versions. The reviewed inventory now
matches that observed set. Independent inspection matched all 20 JSON Schema specification
resources to their frozen bytes and confirmed the native `rpds` extension.

**Preserved failure:** the first physical frozen executable failed before its self-test because
`rfc3987_syntax/syntax_rfc3987.lark` was absent. A correct module/distribution inventory did not
prove resource closure. The pure bundle manifest now names that package's data, and the thin
PyInstaller spec collects it. The new resource-seam regression was observed failing first.
Lark's four grammars and the dateutil zoneinfo archive were independently found in the original
bundle; no format dependency was excluded to obtain a pass.

The repaired locked executable passed all **12 self-tests**, version-resource checks, frozen
engine-child dispatch, and the temporary field-layout HTTP/SPA smoke. The strengthened smoke
seeds only synthetic data in the temporary copy, hashes the exact raw response, compares the
entire projected owner payload and source envelope, and checks a later list page. Immutable
application-member and cleanup checks remain enforced. Independent review rejected **11** smoke
mutations/network failures and passed **178 focused packaging/CI tests with seven existing
skips**, plus the resource-seam test. This closes the observed missing-grammar failure; a final
build with the completed frontend is still required.

## Frontend review in progress

Generated TypeScript is derived from the actual OpenAPI using the pinned local generator.
Independent early review reproduced a device-page custody error: two devices in the same
snapshot can share list metadata and totals, so snapshot identity alone cannot bind a device
page. The author is closing that counterexample with exact host/document binding before fetch
and navigation-race tests. A separate actual React/jsdom probe also retained an old drawer
subject after the provider received a new source identity; the author is binding or clearing
that selection so old evidence cannot be presented under a new digest. No final frontend or
combined application pass is claimed yet.

Golden, sample-data and Scope fixture bytes remain at W2b's single reviewed generation. Scope's
ignored hub build was refreshed for backend mount/browser tests; no data compiler was run.

### Frontend closure and browser verification

The early counterexamples above are now closed test-first. Further independent probes exposed
and closed failed-next-page retry using the current offset, changed engine/limitations context
accepted on a continuation page, and interface cells following object-key order rather than the
owner's explicit column vector. Exact host, whole source identity and engine/registry context
now bind page requests; obsolete requests are aborted and stale responses cannot replace a
new view. Drawer selection is source-bound. Missing or reordered reference targets are never
joined by array position: a bounded page hint is checked against both pointer and original
index, with an explicit reference-only disclosure when no exact match is present.

The generator initially rejected external `$ref` but Redocly could resolve an example's
`externalValue`. Two attempted fetches were intercepted by a deny-network review harness;
no network request escaped. URL, file and relative `externalValue`, dynamic/recursive references
and nonfragment `$ref` are now rejected before the generator starts. Independent black-box
replay confirms zero intercepted network attempts after the fix and no writes on failed checks.
Missing, stale, forged and malformed inputs fail closed. Independent TypeScript compilation
proved closed states/keys, non-`any` values, withheld null/reason requirements and published
nonempty lists across **32 Fact and 28 FactList schemas**.

Final author validation passed **306 Vitest tests + nine generator-policy tests**, the
nonwriting API type-drift check, TypeScript and Vite build. Independent final renderer/client
selection passed **32 tests**. The normalized same-origin Scope capability check also rejects
encoded traversal outside `/scope/`. Root's final production-build E2E run passed **six tests /
one existing opt-in performance skip**; legacy WebGL coverage still runs under Tools. Visual
type checking and all **22 existing visual comparisons** passed without baseline promotion.
The mocked-API E2E lane retains its API-unavailable fallback log; the separate live-server check
below exercises real responses.

Root inspected the actual served application with a temporary synthetic-fleet store. Overview,
Trust, Inventory, device details, Findings, the evidence drawer and the return path through Tools
worked. The drawer showed exact values, basis, subjects, ordered references and full qualifications;
Tab stayed inside it and Escape returned focus. A device's `/punchlist/139` reference selected
the exact original record on rows 126–140, with no positional join. Repeated long caveats were
replaced by visible qualification indicators opening their complete source text; withheld
reasons remain visible. Labels preserve the owner's denominator rather than showing code
expressions as metric captions.

An initial 390-pixel browser test exposed top-bar overflow; the shell now wraps its navigation.
The final live check reports a 375-pixel document inside the 390-pixel viewport (the remaining
width is the vertical scrollbar), in light and dark themes. The mobile drawer fits, and the
desktop layout remains usable. The temporary viewport override was reset. The live browser
reported no console errors. AssessHub intentionally indexes immutable frontend bytes at startup;
the private server was restarted after builds, and the final browser loaded `index-C7bPXL4x.js`.

Frozen source hashes:

| File | SHA-256 |
|---|---|
| `CoreSnapshot.tsx` | `d5016c529defbb704aa4623e17f83deb679e5a672da0bc928901e2b533a46ee1` |
| `ProjectionEvidence.tsx` | `bca716c74f7680329ac3ecf4bf57bab6c07588a952c2ad9bc9b902c2aebfc810` |
| `ProjectionList.tsx` | `f589296c3338169e90c98f7fd8c406079a0f982abe17ab4dfce4df4a9db09edd` |
| `projection.ts` | `67096943d4f5acdd4b1e95dfcb72ab926f204cd5ae2f014b7c7fae9b48510cff` |
| `generated/openapi.ts` | `2481934ef8985911166ad57ae8a013d6cfe2d289fc813f13f712c1025c73d7eb` |
| `dist/index.html` | `85830f785deb7fd4e027121389eb1530d22dccba0b4688a2613c48c781069e32` |

Repository-wide Ruff and diff checks pass. One independent Vitest invocation from the repository
root missed the frontend jsdom configuration and produced 12 `document is not defined` failures;
the correct-directory replay passed without source changes. Its generated root test cache stays
untracked: automatic approval review rejected cleanup with `blocked by policy`. The failed
receipt is preserved privately, and the cache is excluded from commits.

### Later JSON-value boundary refutation

The UI-bearing frozen build also passed all 12 self-tests and the complete temporary field-layout
smoke with frontend index hash `85830f78...69e32` and API hash `5f0090ea...1c194c`. A subsequent
independent producer-fault probe found a gap those successful paths did not cover. Replacing a
published score in inventory row 22 with `NaN` passed the Python JSON Schema validator; both an
unrelated Overview request and an off-page Inventory request returned 200. A request selecting
that row also returned 200, with the invalid score silently serialized as `null` while retaining
the `published` state. Direct Pydantic model validation rejected the same number, so its config
flags alone did not enforce the actual HTTP boundary.

The candidate is held locally while explicit, noncoercing JSON-native/finite checks are added
before whole-document schema validation and at the response boundary. Actual HTTP regression
tests, independent replay, a fresh backend gate and a rebuilt frozen runtime must close this
case. No schema widening, frontend fallback or fixture regeneration is allowed for this repair.

The guard is now implemented on API SHA-256
`235e83202f405b631dafc36fbacb1bc4058f307f572c84ad853da2090d945293`. Four actual-HTTP
regressions were observed failing first, then passing. The expanded API/raw/access-guard
selection passed **89 tests**. Validation walks the entire producer document before selection
and the raw response before Pydantic conversion; it rejects nonfinite numbers, nonnative
containers/keys and cycles without coercion, while allowing shared acyclic aliases. The actual
OpenAPI bytes still equal `7c1240ee...c333`, so the reviewed frontend types and build stay frozen.
The guard alone measured a 9.06 ms median over the 1,234,865-byte synthetic projection (50
checks; no load or worst-case claim). Independent replay and fresh full-backend/frozen gates
are still in progress at this checkpoint.
