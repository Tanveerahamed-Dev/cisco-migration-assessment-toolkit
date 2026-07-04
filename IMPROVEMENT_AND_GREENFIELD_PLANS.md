# Project Analysis & Two Plans — Cisco Migration-Assessment Toolkit

*Plan-only deliverable. No code changed. Produced 2026-07-02 via a 3-wave multi-domain agent analysis (30 agents): Wave 1 = 13 parallel subsystem deep-maps; Wave 2 = 8 expert critique angles + 3 independent greenfield candidates; Wave 3 = 4 adversarial refuters + 2 evaluators. Every load-bearing claim below was re-verified against real code (file:line) or a primary web source. Verdict tally on the 28 spot-checked claims: 22 CONFIRMED, 5 refined, 1 refuted.*

---

## 0. What this project is (orientation)

An offline, air-gapped, evidence-led **Cisco / multi-vendor L1–L4 brownfield network migration-assessment engine** plus a web cockpit. One read-only SSH (or controller-REST) collection is parsed into an ~85-key snapshot dict, run through ~41 `compute_*` analysis axes + 82 design-decision detectors + 11 proof engines, and fanned out to 12 deliverables (62-sheet Excel workbook, a single-file HTML "blast radius explorer", 7 DOCX + 1 PPTX, diff/campaign workbooks). Alongside sit **AssessHub** (FastAPI + React), a `.claude/` "Automated Senior Network Engineer" agent rig, and a docs/research corpus.

**Scale:** ~65k LOC Python + a 9,989-line single-file HTML explorer + ~7k LOC webapp. 1,150 tests + a golden byte-contract. 474 commits in 28 days, **single author, exactly 1 refactor commit**. Real fleet under assessment: 303 devices / 253 collected / 64 MB snapshot.

**The doctrine (its genuine moat, preserve at all costs):** read-only against devices; no-egress runtime; **coverage-honest abstention** (absence of evidence is never health — `[NOT OBSERVED]` / `INDETERMINATE` / `lower_bound`); proposer ≠ verifier; single source of truth for every shared fact.

---

## 1. The honest scorecard

### 1a. Strengths to preserve (do not regress these)
- **Systemic coverage-honesty** wired into both engines *and* renderers (abstention is an explicit state everywhere, not a convention).
- **Fail-open pipeline**: `_run_phase` guards 109 phases; one bad axis never loses the workbook.
- **Golden contract + additive-only discipline**: per-section snapshot + sheet-schema (order + headers) frozen; `UPDATE_GOLDEN=1` escape hatch. This is a real byte-level equivalence oracle.
- **Proof-based verify engines** with explicit abstention: `aclcheck` 5-D box-algebra shadow proofs, `fib` RIB→FIB longest-prefix multi-hop with `reach > lower_bound > drop` ranking, `ssot.reconcile` against *independent* bases, `manifest` sha256 hash-chain custody.
- **Doctrine-as-tests**: read-only/no-egress enforced by AST-walking the import graph and re-deriving the command allowlist from the actual registries.
- **Decision → principle → citation → evidence traceability** over a 307-principle design KB (0 orphan citations).
- **Wheel-relocatable packaging** with exactly 2 runtime deps (netmiko, openpyxl).
- **Test-first culture**: 64% of commits touch `tests/`; 59% record the golden-diff outcome in the commit body.

### 1b. The real problems (ranked, all verified in Wave 3)

| # | Problem | Evidence (verified) | Class |
|---|---------|---------------------|-------|
| 1 | **Format-fidelity bug class** — an unseen platform variant parses to `[]`/`{}`, byte-identical to "feature absent" everywhere downstream; no zero-parse telemetry | `parse.py` worst fix density in repo (36 fixes / 83 touches); `cmdio.py:22-48` returns `''`/`{}` for absent≡error≡empty; recurred across 4+ audit waves; once zeroed a whole real NX-OS RIB | Correctness (crown jewel) |
| 2 | **Client-data confidentiality gap** — zero-auth localhost API + `CORS *`, plaintext secrets at rest | `app.py:136-139` `allow_origins=['*']`, no auth (confirmed); `devices.json` = 303 plaintext passwords (real value seen at line 5); raw 416 MB collection dir with cleartext running-config secrets is **never** touched by `--redact` (`COLLECT_PARSE:901`, `:1886-1888`) | Security (reachable) |
| 3 | **Golden auto-bless hole** — a *missing* golden regenerates + skips, silently re-baselining the contract | `test_pipeline_golden.py:102-109` (confirmed) | Test integrity |
| 4 | **Wiring tax, no registries** — new axis = 3–4 hand-parallel sites; new explorer mode = 7 sites; new webapp tab = 2 parallel lists (this exact miss made the "NOS quartet" unreachable for months) | 40 hand-declared `all_*` accumulators (`COLLECT_PARSE:1661-1700`) ↔ 33 hand-keyed `snap_dict[...]` (`:2413-2446`); `summary.py:56-58` documents the months-long miss | Maintainability |
| 5 | **God-functions never consolidated** — 1 refactor commit in 474 | `main()` ~1375 ln / 109 `_run_phase` sites; `_signals` ~1200 ln / 399 `sig[...]` consume-sites; `analyze.py` 6090 ln; explorer 9989 ln | Maintainability |
| 6 | **One genuinely superlinear perf term** | `compute_failure_impact` measured **23.16 s** on the real [HISTORY-REDACTED] fleet — O(H×V×link-scan) with an *uncached* per-call VLAN-range `re.split` (`analyze.py:885-926`, `:595`); projects to tens of minutes at ~1000 devices. (Topology rebuilt at 9 sites + network-model at 6 + `link_centrality` twice are real duplication but only ~0.13–0.16 s each — SSOT wins, not perf levers.) | Performance |
| 7 | **The client-facing 9,989-line explorer has 0 executed JS tests** (only regex-presence guards); 3 hand-maintained JS ports of Python engines, only `fib` drift-guarded | `test_explorer_fib_ssot.py` is regex-only; the "622-pair harness" its docstring cites is not git-tracked | Test coverage |
| 8 | **Snapshot bloat** — 64 MB, `indent=2`, interfaces = 29.7 MB (~46% of the file / the single largest section) and **74% empty fields** fleet-wide | measured exactly in Wave 3 | Performance / scale |
| 9 | **Dead / half-wired engines** | `manifest.verify_chain` has no production consumer; `external_import` IP_DRIFT is dead (reads `lifecycle_risk.per_device[].mgmt_ip`, which `analyze.py` never emits); `capture_integrity` only checks running-config (`COLLECT_PARSE:2241`) | Correctness |
| 10 | **Product surface froze 2026-06-12** — README says "8 modes / Cisco-only" (reality: 13 modes, multi-vendor, 8 verify-engines); 0 release tags in ~220 commits; demo sample 33 keys stale; no Dockerfile; no LICENSE file; webapp ingest hard-requires a repo checkout | README:19/209, `git tag`, `sample_fleet.snapshot.json` 56 vs 85 keys, `ingest.py:43-44` | Adoption |
| 11 | **KB staleness risk** — OUI generator script doesn't exist (57k-row pack frozen); `eoldb` 10 "active" rows are an undated false-health time-bomb; no provenance/date headers in the packs | `cisco_toolkit/data/` has only `gen_port_registry.py`; `eoldb.py:70-77` | Data freshness |
| 12 | **CI/rig gaps** — webapp's 59 tests excluded from the default suite *and* the Stop hook; coverage excludes the 2705-line entry module; `settings.json` has 0 permission rules; all 8 agents hold Bash | `pytest.ini:2`, `verify-green.sh:28`, `pyproject.toml:84` | Verification integrity |

---

## PLAN A — Improve it (EVOLVE). The recommended path.

**Governing principle:** the tool works and ships real client deliverables; the golden byte-contract turns "suite green, no `UPDATE_GOLDEN`" into a behavior-preservation proof. So evolve strangler-style — every step golden-byte-stable or additive-and-blessed — and attack the crown jewels (format-fidelity + false-health) and the confidentiality gap first. **Sequence is the whole game.**

### Tier 0 — MOVE-0 (do before any structural churn)
1. **Close the golden auto-bless hole** (~40 LOC). Fail (not skip) when a golden is missing and `UPDATE_GOLDEN` is unset; reject shrinking goldens (removed keys/sheets/headers) via `git show HEAD:...` diff unless `ALLOW_GOLDEN_SHRINK=1`. *This is the hard predecessor of every registry/decomposition/perf-swap item — without it, refactors lose their equivalence proof.*
2. **Gate the assets that already exist**: add `webapp/tests` to `pytest.ini` testpaths (or to `verify-green.sh` on webapp changes), and add `COLLECT_PARSE_V3_23_0` to the coverage source. Near-zero effort; closes the exact blind spot behind the months-dead NOS quartet.

### Tier 1 — NOW (correctness crown jewel + confidentiality; ~1 week)
3. **Zero-parse yield telemetry** at the `cmdio` chokepoint (~1 day, highest-ROI correctness item). Record `(host, cmd, parser, lines_in, entities_out)`; publish an additive `snap['parse_yield']` + a Collection-Completeness row; coverage-honest ("collected-but-unparsed", never a device verdict) with a per-parser `may_be_empty` flag to avoid cry-wolf. One chokepoint covers all 94 `_safe_parse` sites and makes the next NX-OS-RIB-class zero a **red workbook row on its first real run** instead of a silent `[]` surviving four audits.
4. **Kill `CORS *` + gate writes** behind an optional bearer token (localhost dev unchanged; token required only when bound non-loopback), and **sandbox the explorer iframe** (`sandbox="allow-scripts allow-downloads"` — critically *without* `allow-same-origin`). Confirmed: any open browser tab can currently cross-origin read client topology/IPs/serials/parsed configs and forge gate sign-offs on the default localhost bind; the unsandboxed same-origin iframe is the `innerHTML → parent → zero-auth-API` escape path.
5. **Secrets at rest**: emit a loud "SENSITIVE — cleartext" log line for the raw collection dir + add opt-in `--redact-collection` (reuse `_scrub_secrets`); do **not** auto-delete (it's the `--compare` source). Make `password_env`/`$CISCO_PASS` the documented default and ship `devices.example.json`. Near-zero new code — the env-chain already exists, just unused.

### Tier 2 — NEXT (structural protection + adoption; ~2–4 weeks)
6. **Widen `capture_integrity`** from run-config-only to all ~160 collected commands + flag `send_command_timing` truncation fallbacks as `unverified_prompt` findings. Gives the zero-parse telemetry its explanation channel (zero-yield + incomplete capture = collection problem vs. parser gap).
7. **Executed-JS parity gate** (node, `skipif` absent): commit the existing 622-pair `fib` harness and extend sentinels to `causalFlows` + `cableMap` — upgrade regex-presence to behavioral equality. This is the frontend twin of the #1 bug class (a silently divergent JS port ships wrong-but-plausible client output). *Prerequisite for the MODES-registry refactor.*
8. **AxisSpec registry** collapsing the 3–4-site per-axis wiring in `COLLECT_PARSE` (accumulator + build-loop + snap-assign) following the `_DETECTORS` precedent the repo already trusts; add a uniqueness / real-builder unit test; then **derive webapp `SECTION_LABELS`/`_ALLOWED_SECTIONS` from it**. Golden-safe by construction; kills the drift generator at its root.
9. **MODES registry** in the explorer (one table → `HASH_MODES`/repaint/renderDrawer/setHint/setLegend/keyboard) with a Python conformance test; the 5 missing keyboard shortcuts fall out for free. *After #7.*
10. **Product/adoption pass** (all sub-day): regenerate the AssessHub sample fleet (`build_sample.py` drives the real pipeline) + a `sample ⊇ golden − opt-in` test; rewrite the README to the actual product (13 modes, multi-vendor, 8 engines, wheel-install works); resume tagging (**v3.24.0**); start a `CHANGELOG.md`; add a docs-parity test; add a `LICENSE` file (formalize all-rights-reserved). *After the golden gate so the new tests ride a trusted contract.*
11. **Measure-first perf harness** — `perf_counter` in `_run_phase` (sidecar JSON, golden-neutral) + a parametric N-device scale-fixture builder run at 100/300/600/1000. *Hard predecessor of any perf work — no perf harness exists today, so all scaling claims are extrapolation.*
12. **Restructure `compute_failure_impact`** — `lru_cache` the range parse + per-VLAN precompute + articulation-point pruning; ship as a parallel impl with a differential test vs the old fn on golden + real snapshot, then swap. The single superlinear term (measured 23 s). *After #11.*
13. **Redaction adversarial leak corpus (K4)** — committed multi-vendor configs seeded with known secret shapes, asserted zero-surviving-secrets after `--redact`, as a regression gate. Two audit waves already found real misses (55 serials survived once); test-enforce the share-safe promise.

### Tier 3 — LATER (slack-time; real value, no fire today)
14. **Snapshot size**: Phase-1 compact separators (drop `indent=2`) is *provably free* — verified that all consumers compare parsed objects, not bytes, so the golden passes with **no** `UPDATE_GOLDEN`. Phase-2 sparse-encode the interfaces subtree only (74% empty fields) with a reviewed golden bump. Optional Phase-3 `gzip` sidecar via magic-byte sniffing. *Keep sparse-encoding confined to interfaces — `DevicePhysical` has non-`''` defaults.*
15. **Typed `AnalysisContext`** co-landed with a strangler decomposition of `main()` into ~5 stages under the coverage gate (replaces the 19/15/14-positional-param syntheses).
16. **`PARSER_CONTRACTS` registry** (typed default per parser matching its return annotation, fixing the `{}`-vs-`[]` hazard at 94 sites) + **mine the 416 MB real collection into a redacted committed fixture corpus** (attacks the self-authored-fixture root cause) + a `hypothesis` property harness (totality + anchored-non-zero-parse).
17. **Widen the ntc-templates cross-check** from 3 commands to ~15–20 across IOS *and* NX-OS, run over the real-capture corpus — as an **independent CI referee**, not a replacement for the hand-rolled parsers.
18. **Read-only stdio MCP server** (`cisco_toolkit.mcp_server`, behind an `[mcp]` extra, **no HTTP listener** — stronger than localhost and no-egress by construction) exposing ~8 read-only tools over existing functions. Lets any MCP client drive assessments; shrinks the Bash escape hatch.
19. **Rig/KB hygiene**: `settings.json` permissions block (deny device-write/exfil, ask for live collection, allow read-only verbs); prune `.claude/worktrees/` (146 MB) + `.graphifyignore` it; add provenance/review-by headers to the KB packs (esp. the 10 undated `eoldb` "active" rows); write the missing `gen_oui_registry.py`.

### TRAP-AVOID — do NOT do these for this project
- **Any from-scratch rewrite (greenfield A/B/C as a clean-slate replacement)** — a 65k-LOC / 1,150-test parity march that stalls into two half-products for a solo maintainer mid-engagement.
- **Making vendored ntc-templates/TextFSM the DEFAULT parse lane** — trades a fixture-hardened parser for a *proven* NX-OS misread surface. Use it as a referee.
- **A mass table-driven rewrite of the ~66 `excel.py` sheet writers up front** — risks the actual client deliverable for cosmetic tidiness. Convert as-touched.
- **A mutation-testing project + a from-scratch frontend test suite as priorities** — low defect-per-hour vs. the telemetry/parity gates that catch the real classes. (Vitest for the coverage-honesty KPI mappers is a fine slack-time add; not a priority.)
- **DuckDB anywhere** (see Plan B) — its extension autoloader defaults to fetching from `extensions.duckdb.org`, a live egress vector against the no-egress moat.

---

## PLAN B — If I built it from scratch (verification-first), and why you should EVOLVE toward it instead

If a clean slate were the mandate, the right architecture is **candidate A — verification-first**: the engine is a *proof system over a typed model*, not a report generator with analysis bolted on. It wins because it makes the two chronic cost centers **structurally unrepresentable** rather than disciplined-against.

### Organizing idea
Every fact is `Fact[T] = { value: T, provenance: Provenance, verdict: Verdict }`, where `Verdict` is a **closed tagged union** `Proven | Refuted | NotObserved(reason) | Indeterminate(reason)`. Coverage-honesty becomes a type-system property the decoder enforces — a zero-entity parse is a first-class `ZeroParse` value that *must* be rendered, never a silent empty dict. An axis exists only as one registry entry that generates its snapshot key, sheet, explorer mode, webapp tab, and doc section.

### Layer law
`evidence → parse → model → verify → project`. Each stage reads only the *sealed* artifact of the previous one; no layer may reach back to raw text (today `excel.py` re-parses raw output for 3 sheets — that bypass becomes impossible).

### Stack (Wave-3 web-verified, 2026 state)
- **Python 3.12** (matrix 3.10–3.14 + a Windows cell), stdlib `sqlite3`/`gzip`/`ipaddress`; **zero JVM**.
- **Typed model via incremental dataclass/pydantic-v2 typing behind one serde module** — *not* msgspec-as-foundation. (msgspec is real: v0.21.1, Apr 2026, ~12× faster than pydantic v2 by its own benchmark — but strict decode would *reject* weird-but-real captures that today's lenient dicts absorb, i.e. a crash mid-engagement, the opposite of the fail-open doctrine. Isolate any serde choice behind one swappable module.)
- **netmiko 4.x default SSH collector** — the *only* Windows-supported option. Verified disqualifiers: **scrapli** native/system transport is POSIX-only (WSL/Cygwin on Windows, unofficial); **pyATS/Genie** is officially "Windows not yet supported." These are Windows-laptop-fatal.
- **ntc-templates 9.1.0** (Apr 2026, Apache-2.0, actively maintained) vendored for air-gap as an **independent referee**, with the hand-rolled parsers as the fidelity overlay for the ~15 commands where community templates provably miss (NX-OS ubest/mbest RIB, HSRPv2, BFD state-token, Twe/Tw).
- **openpyxl / python-docx / python-pptx** (optional extras) for the deliverable projections — ported.
- **FastAPI + uvicorn** localhost workbench with token-auth default-on, no `CORS *`, authenticated + rate-limited ingest.
- **hypothesis + mutmut (dev-only)** for the verify kernel; **uv + uv.lock + pip-audit** in CI (closes the no-lockfile/no-scan gap).
- **Batfish REJECTED at runtime** (config-centric, can't ingest operational show-state, JVM/docker breaks air-gapped Windows, abstention not typed) — kept only as a dev-only differential ACL oracle. **DuckDB REJECTED** (candidate B) — extension autoloader defaults to network fetch from `extensions.duckdb.org`; self-contradictory in a no-egress product. **Its one great idea — coverage-as-a-first-class-row — is worth stealing and needs no columnar engine.**

### Data model
Content-addressed evidence store (sha256 blobs + hash-chain manifest, redaction **at write time** so secrets never persist plaintext). One portable model file (sparse-encoded, gzipped). `RouteEntry` is **VRF-keyed from day 1** (kills the `fib #19` blind spot at the schema). `AclEntry` carries interface binding + direction (so FIB × ACL compose into end-to-end path verdicts — today they never combine). Envelope stamps schema semver **and producing engine release** (fixes the frozen `collect_parse_snapshot/1` + `V3.23.0`-forever stamp). The **parse ledger is a golden-frozen model table**, so a parser silently going to zero on a variant fails CI instead of shipping as feature-absent.

### Testing doctrine (from day 1)
Real captures only (self-authored fixtures rejected in review — that class hid the zeroed NX-OS RIB); differential lanes (ntc-templates vs. overlay, superset assertions on *all* shared commands); zero-parse telemetry golden-frozen; `hypothesis` property/metamorphic tests on the box algebra + FIB; doctrine-as-tests ported verbatim; the golden harness **fails loudly on a missing golden and mechanically rejects shrinkage** (no auto-bless); explorer JS executed under `node --test` against shared verdict fixtures; an [HISTORY-REDACTED]-scale perf golden so 303-device regressions are visible before an engagement.

### Port verbatim (the irreplaceable capital)
The 11 verify engines + their 174 tests; `design_kb` (307 cited principles, 0 orphans) + `doctrine.py` invariants + the traceability schema; `questionnaire.json` (240-question interview, 20 go/no-go gates); the KB packs; the real-capture fixture corpus and *every* format-fidelity fix lesson; `rest_collect`'s threat model (no-downgrade/cross-host redirect refusal, RBAC-fault rejection, ERS pagination); `netmiko` collection semantics (auth-never-retried, union-collect + platform self-correction); the coverage-honest renderer phrase pack and the explorer's a11y + design tokens.

### THE VERDICT ON PLAN B
**Evolve, don't rewrite. Treat candidate A as the design north-star and reach it via Plan A's strangler PRs — never a from-scratch build.** Three facts decide it:
1. **Bus factor 1.** Every greenfield candidate's own build order *ends* at "parallel-run the old engine until diff-clean, keep it shipping" — an admission that the destination is the evolved current repo plus types, reached the expensive way, while one person maintains two engines through months of parity.
2. **The 65k LOC is not fungible volume** — it's four adversarial audit waves of encoded platform truth (`parse.py`'s 365 fix-provenance comments, the 174-test verify kernel, the NX-OS-RIB lesson). A rewrite *will* re-derive and thus re-introduce fixed bugs.
3. **Every greenfield win is reachable incrementally** — the Verdict ADT can start at the verify layer + snapshot envelope; zero-parse-as-first-class is one additive golden-frozen table; the AxisSpec registry follows the `_DETECTORS` precedent; VRF-keyed routes are a bounded change. "Structurally impossible in a codebase that won't ship for months" is worth less to a solo practitioner than "disciplined against with a red test in the repo shipping today."

Candidate **B** (DuckDB warehouse) is architecturally self-contradictory for a no-egress product; harvest only its coverage-as-a-row idea. Candidate **C** (product-first, "delete a frontend") is largely refuted because the webapp already iframes the explorer and its React lenses are render-only over engine SSOT — the drift it wants to kill is already dead.

---

## Bottom line & first-week actions

**Recommendation: Plan A. The tool is release-grade; it doesn't need a rewrite, it needs hardening + instrumentation, sequenced behind a trustworthy golden.** Adopt candidate A's *ideas* (typed Verdict/Fact ADT, zero-parse as first-class, VRF-keyed routes, one axis registry) as additive PRs; never pay the rewrite's re-derivation tax.

**Do this first, in this order:**
1. Close the golden auto-bless hole + gate the webapp tests / entry-module coverage. *(Move-0 — unlocks everything else safely.)*
2. Zero-parse yield telemetry at the `cmdio` chokepoint. *(Highest-ROI attack on the #1 recurring bug class.)*
3. Kill `CORS *` + optional bearer token + sandbox the explorer iframe. *(Reachable client-data exposure on the default localhost bind.)*
4. Warn-and-purge path for the raw collection dir + make the credential env-chain the documented default. *(Highest data-at-rest blast radius on an air-gapped consulting laptop.)*

Everything past that (registries, `failure_impact` rewrite behind a measure-first harness, product/README/tags, MCP surface) is real value but not on fire — do it in the NEXT/LATER order above, each step golden-safe.

*Awaiting your review before any code changes.*
