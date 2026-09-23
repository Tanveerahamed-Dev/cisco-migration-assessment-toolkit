# Atlas Scope — Acceptance Report

Graded 2026-09-23/24 against `docs/acceptance.md`, at HEAD `70bea72`
(`70bea7250af46ed530e98478157b0ca7a095de6b`, "fix: pin a caller-requested quality tier even when it is
already in force (C5)"). Every grader found the same tree: `git status --short` showed only
` M docs/open-issues.md`, an uncommitted edit by a parallel session, and
`git ls-files --others --exclude-standard` printed nothing, so the build imports no untracked file.
Six first-pass graders covered groups A–F. Independent refuters then attacked every PASS.

**Where the first pass and the refutation disagree, this report applies the refutation.** Four PASS
verdicts were overturned: A6 → FAIL, D1 → FAIL, E2 → UNPROVEN and F4 → UNPROVEN. Each overturn came
with a reproducible proof (scripts, commands and their output), so none was set aside. The other 25
PASS verdicts were attacked and upheld, so no verdict here is "PASS, unrefuted". Every group returned
a grade; no group is marked "grader did not run".

Where each group was graded:

- **A:** the Vite dev server on :4180 (Browser pane for A1–A3), then an isolated headless Chromium for
  A4–A6, because the shared Browser pane tab was taken over by another agent mid-probe.
- **B:** the dev server on :4180, plus engine sweeps under a scratch vitest config.
- **C:** a private `vite build --outDir <scratch>/dist-c` served by `vite preview` on :4293.
- **D:** a scratch `vite build` served on :4297; early grid probes on :4180.
- **E:** `npm run build` served by `vite preview --port 4181 --strictPort`; every harness reported
  "build: fresh".
- **F:** the working checkout (byte-identical to `70bea72` under `src/`, `tools/`, `review/`),
  `git archive` sandboxes, and private previews on :4183 and :4190.

None of it was run from a fresh `git clone` of `70bea72` (O23).

**The tracked-sources gate (a precondition, not a criterion).** Every group ran
`src/core/tracked-sources.test.ts` and it passed: 6 of 6 in groups A, B and F (F: "no file the build
loads or the compilers import is missing from HEAD"), and inside green multi-file runs in C
("Test Files 2 passed (2) / Tests 33 passed (33)"), D (5 files, 82 tests, exit 0) and E
("Test Files 2 passed (2) Tests 20 passed (20)"). The F grader also parsed every `dist/assets/*.map`:
70 repo-local sources, all under `src/`, 0 untracked. No refuter attacked the gate, so it is recorded
here and not under "What is proven".

This report replaces the re-grade of `443a05a` at this path. Figures in that report are history, not
evidence for `70bea72`.

## Verdict

**Atlas Scope is not ready for acceptance.** Seven of the 39 criteria FAIL and seven are UNPROVEN. An
UNPROVEN criterion is not a pass. The failures: a finding reaches its configuration evidence in only
12 of 146 cases (A1); with a trace active, the fabric does not show a selected device's blast radius
(A6, overturned); the Ctrl+K palette states forwarding verdicts with no scope claim or caveat, and
calls an undecided denial "the blocking-hop answer" (B2); a sub-2 px dashed hairline is drawn in the
link bundle at both tiers and in both themes (C5); the Path surface's Queue/Evidence switch at 768 px
cannot be reached by keyboard (D1, overturned); at 390 px the focused status-bar buttons are painted
over by the side rail, so focus is not visible (D3); and in the first acceptance-grade cold-load run
since `1d19e22`, keystrokes during load took 240–400 ms against a 200 ms bar (E5). Four UNPROVEN
criteria cannot be moved with this snapshot or this reference set: A2 and B8 need depth-2 flows and a
decided refusal, C1 has no valid blind verdict, and F3 has no history before `50a3dc5`. E2 and E3 each
lack acceptance-grade evidence for the declared journey `J2-first-select-device-3d`, partly because of
a newly found load-meter defect in `review/measure-inp.mjs`. F4 is proven only below 768 px. What
survived attack is substantial: the forwarding engine's honesty (B3–B5), citations and provenance
(B6, F5), stated coverage (B7), null handling (B1), blocked-flow attribution (A3), re-aiming (A4), the
settled render and themes (C2–C4, C6), most of accessibility (D2, D4–D8), frame rate (E4), and the
type-check, suite and determinism gates (F1, F2, F6).

Totals, without compression: **25 PASS, 7 FAIL, 7 UNPROVEN.** This is a count, not a score.

## Scorecard

Overturns applied: A6, D1 (PASS → FAIL); E2, F4 (PASS → UNPROVEN). All other verdicts are the first
pass's, upheld under attack where PASS.

| Criterion | Verdict | Evidence | Note |
|---|---|---|---|
| A1 | **FAIL** | F099 took 3 interactions (Ctrl+K, type + Enter, click "Show the record that matches this finding: access13 Gi0/11 (err-disabled)"); camera unmoved. F088: "No configuration evidence route: the finding names no configuration line and nothing we hold matches its words." `EvidencePane.namedconfig.test.ts` 12/12 re-measures the census 6/146 named, 2/143/1 literal, noTarget=[F142]. | 134 of 146 have no configuration-evidence route. O12: not closable in Atlas Scope. |
| A2 | **UNPROVEN** | Depth-1 trace of tcp 10.0.10.50→10.0.30.10:3389 names host, egress `Vlan30`, next hop, route `routes.core1[6]` and ACL `acls.core1.PROTECT_SERVERS[3]`. Hop-depth ratchet: 4 tests passed, asserts maximum depth 1. | The multi-hop half never ran on real data (O34). |
| A3 | PASS | "denied at core1 by ACL PROTECT_SERVERS line 4 of 4 (acls.core1.PROTECT_SERVERS[3]: \"deny ip any any\")". Refuter: 346 denied traces in a 4,800-flow SSR sweep, every one with ACL decider, raw text and cite. | Verdict is labelled "? UNDECIDED"; no truly decided block exists in this snapshot. |
| A4 | PASS | Six selection sources (fabric device, fabric link, path hop, queue finding, evidence-pane finding, palette device) each re-aimed the other surfaces with camera, flow and queue context preserved; restored links keep `d` and `hop`. | Refuter: queue `aria-current` lagged the URL by 0.5–3 s under load; always converged. |
| A5 | PASS | Hover sets `data-hovering='true'`; clicks select; double-click frames access13; "Reset view" returns to the load pose (`equalsLoad: true`); on-fabric ring marker and "core1 C ? UNDECIDED". | On-fabric trace is a one-node marker; `flow.ts` path geometry never ran on real data. |
| A6 | **FAIL** (overturned) | First pass: 9 stranded on core1, 8 on core2, pixel diffs, disagreement text. Refuter: `?d=core2&flow=…3389&hop=0` marks 5 of 8 (access3, access5, access17 off-canvas, `visible:false`), no count or off-screen notice; core1 marks 0 of 9 until an extra button is pressed. | Refutation applied: proof present (ui7–ui9.mjs). |
| B1 | PASS | 26-device, 5-tab sweep; uncollected devices, no-RIB hosts, links, `is:healthy` and unmodelled hops all read "not observed" or undetermined; every flagged 0 is a real 0 in the source (sha `9580aa09…`). | Latent: `tools/compile-snapshot.mjs:332/:350` compile a null severity to `"Info"`; no null reaches it today. |
| B2 | **FAIL** | `traceFlow` for all 5 `suggestedFlows()` entries: every claim starts "Under the collected RIBs of core1 and core2 only (2 of 26 hosts …)", caveats 8–13; 4,160-flow sweep, 0 unscoped. But the palette reads "10.0.10.50 -> 10.0.30.10:3389 \| trace a path — this one ends denied" and "…the blocking-hop answer with its exact configuration line." | The palette (`commands.ts:404-409`, `:734-739`) carries no scope or caveat, and contradicts the trace's "That denial is not decided". |
| B3 | PASS | `engine.test.ts …` 112/112, exit 0; 400 of 4,160 traces touch a no-RIB host, all indeterminate. Refuter re-ran 81/81 and swept 4,800: 0 delivered through a non-RIB host. | — |
| B4 | PASS | `engine.off-subnet.test.ts` green; 1,456/1,456 out-of-scope traces carry "lies in no subnet". Refuter: 2,440 random off-collection sources, all out-of-scope. | — |
| B5 | PASS | Unit tests against real `PROTECT_SERVERS[2]` and `INET_RETURN[0]`; refuter re-ran "Tests 10 passed \| 69 skipped" and a 630-flow sweep with 0 violations. | Established-line test is weak alone (the flow is indeterminate for other reasons); `evaluateAcls` tests isolate it. Object-group only synthetic. |
| B6 | PASS | 10 random + 5 targeted citations clicked, 0 unresolved; 796/796 model citations resolve; 770 identity cross-checks, 0 mismatches. Refuter: 589 field comparisons against source, 0 mismatches. | O9: the Inspector shows the compiled record, not raw source bytes, and says so. |
| B7 | PASS | "23/26 collected", "RIBs 2/26 (both shown incomplete)", "ACLs 1/26", "centrality 25/44" visible; refuter: 72 state × viewport combinations, all four visible and hit-testable. | Transient modals cover it (O32; help dialog at 320x568). |
| B8 | **UNPROVEN** | Only the negative state renders: "None of the 8 nearby variations … so no counterexample is offered." 924 denied/dropped traces, 0 counterexamples. Positive state only under `vi.mock`. | O13. Heading "Nearby flow with a different outcome" sits over a body saying none was offered. |
| C1 | **UNPROVEN** | `review/blind/KEY.json`: 12 entries, no verdict/winner field; 8 orphan sheets; the "-craft" sheet still shows "Forward AI" and the Storylane modal. | No valid blind verdict exists or can exist against these references (O19). |
| C2 | PASS | `capture.mjs app`: "PASS capture app 32 of 32 frames rendered, settled on screen and at tier high"; `capture.mjs text`: "PASS text 72 of 72 states free of clipped/broken text"; 34,030-node sweep, only real finding titles matched. Refuter's wider sweep: only legitimate hits. | Descender clipping has no detector (O17). |
| C3 | PASS | 1920: 10 rows, 0 clamped. 1440: 6 rows, 1 clamped (F002 loses "gateway"). | Compact density not graded (O17). |
| C4 | PASS | All 8 states × both themes; 0 of 35 tokens within 8/255 of an inversion; refuter found no dark-only surface in light. | First paint not re-measured (R40). |
| C5 | **FAIL** | Static items 1, 2, 3, 5, 6 pass at high and low; motion: "PASS every recorded motion frame rendered at its leg's declared tier (24 sequences, 4 of 4 legs)", 0 z-fight clusters, 0 pops, 24/24 fades 266.6–266.8 ms. Item 8 fails: a 1-device-px dashed stroke about 450 device px long in the core2→access9/access3 bundle, identical at dark/high and dark/low. | Drawing object not identified. Harness exit 4 was an mtime freshness flag; content matched HEAD. |
| C6 | PASS | 54 transition events, max `transitionend` 140 ms; `getAnimations()` `[]` after idle; constants match §4.8; motion-inventory test green. | Refuter: two rAF loops (`scene.ts:2768`, `FabricLabels.tsx:320`) run at idle with no visible change. |
| D1 | **FAIL** (overturned) | A1 and A2 completed with real keys at 1440 and 390; canvas orbit by keys. Refuter: at 768 on `?s=path` both `Queue`/`Evidence` radios are `tabindex="-1"`; "paneswitch focused during 60 Tabs: 0"; a mouse click still operates it. | Refutation applied: proof present (d1scan, pane, pane2, pane3.mjs). |
| D2 | PASS | Key-by-key on "Findings, ranked": arrows, Home/End, Ctrl+Home/End, PageUp/Down, sort, collapse, selection, one tab stop. Refuter also passed "Cross-layer records, ranked". | — |
| D3 | **FAIL** | Focus return correct for every dialog and popover tested; intentional modal traps 20/20 Tabs. At 390x844 `?d=core1&s=fabric`, focused status-bar buttons are under `.rail--b`: `elementFromPoint` returns `LI.dp-list__row` at 9 of 9 points; "'23/26 collected' 0/4400 pixels changed". | Not O32. Also at 600x900 and states 06/09. |
| D4 | PASS | Text minimum 4.60 light / 4.71 dark, pixel-verified; non-text at least 3.24. Refuter extended to 390 and 768: 0 text under 4.5. | 1440 pixel pass only; hover state not tested. |
| D5 | PASS | 929 targets at 1440/01, minimum 24.0x24.0 outside grid sub-cells (exempt: the row is the target). Refuter found only clipped 1x1 tree items. | — |
| D6 | PASS | `pick()` sweep: 26 devices, 44 links; 114/114 tree rows selected by keyboard. | Tree names do not carry trace/stranded marks. No real screen reader. |
| D7 | PASS | "PASS  D7: camera lands in one frame under reduce, 23 poses without it." (reproduced by the refuter). | Packet half fixture-only. |
| D8 | PASS | Greyscale 03/06: letters on 114/151 chips, band letters, "? UNDECIDED", dash patterns. | — |
| E1 | PASS | `journey-scope.test.ts` + `tracked-sources.test.ts`: "Test Files 2 passed (2) Tests 20 passed (20)"; "acts with a verified effect 25 of 25". Refuter: 26/26 palette opens by probe. | §8.1 wording is looser than the harness ids. |
| E2 | **UNPROVEN** (overturned) | Quiet runs: "ACCEPTANCE EVIDENCE: release build, hardware renderer, quiet host." p95 J1 32–48, J2 88–96, J3 32, J3b 32, J4 48, J5 32 ms. J2-first p95 64 ms only in refused runs: "NOT ACCEPTANCE EVIDENCE … host was 35% busy". | Refutation applied: a declared E2 subject has no accepted run. |
| E3 | **UNPROVEN** | "E3 across runs … PASS — J1 … J2 … J3 … J3b … J4 … J5 … STABLE PASS (3/3)". J2-first: "INSUFFICIENT RUNS (0/0 measured runs clean)". | Load-meter defect: `hostLoadMeter.sample()` only at `:1556`. |
| E4 | PASS | `measure-fps.mjs` ×3: "focus flights: PASS — median 60 fps … worst window 58.89 fps (floor 45) … Orbit drag: PASS — orbit median 59.05 fps". Refuter: CPU throttle ×6 gave explicit "below frame-rate bar", then step-down to balanced. | AO is suspended while the camera moves under "tier high"; disclosed in `qualityReasons`, not in the report. Canvas 1161x962. |
| E5 | **FAIL** | `audit-e5-coldload.mjs` ×2, `acceptanceEvidence=true`: "FAIL E5 … 8 keystroke(s) over 200 ms (worst 400 ms)" and "5 keystroke(s) over 200 ms (worst 280 ms)", all after FCP. Sweep: "PASS E5 sweep all 13 actions stayed under 200 ms in every one of 3 repetitions". | Keystroke failure does not depend on the O20 pre-FCP carve-out. |
| F1 | PASS | `tsc` main, scripts (`--noImplicitAny`) and config: EXIT 0 each; 214 files listed; 0 `@ts-*` suppressions. Refuter reproduced. | `review/*.mjs` declared excluded (O27). |
| F2 | PASS | "Test Files 136 passed (136) / Tests 2106 passed (2106)", EXIT 0; refuter reproduced under load. `capture.mjs app` exit 0 twice. | `acceptance.md` "Timing is not asserted" is false (O26); "45 of 135" is stale (46 of 136). |
| F3 | **UNPROVEN** | `mutation-check.mjs`: 18 KILLED, "not pre-fix history". Real red-before-fix only for claims (`Tests 2 failed \| 37 passed`) and provenance (`Tests 8 failed \| 10 passed`). | About 10 confirmed defects have no executable red check of any kind (O34). |
| F4 | **UNPROVEN** (overturned) | Build: `three-Dyx6ntnn.js 828.00 kB (gzip 239.65 kB)`, imported only by Fabric3D; entry has no static import. Refuter: at 768/1024/1920 three is fetched unprompted (1,013,596 of 1,970,906 decoded JS bytes); at 767 and 375 it is not. | Refutation applied: proven only below 768 px. |
| F5 | PASS | `compile-snapshot.mjs` → `sha256(source, lf-normalised) = 9580aa09…3089 (3072771 bytes)`, `fabric.json` byte-identical `a1a599b8…d251`. Refuter: all four compilers in a `git archive` sandbox byte-identical. App shows `9580aa09`. | Not from a fresh clone of `70bea72` (O23). |
| F6 | PASS | "verdict: F6 PASS: 32 of 32 frames byte-identical across 5 runs." Refuter reproduced on :4190, plus 375x812 DPR 2: 0 of 16 frames varied over 3 launches. | One host, CPU raster; O22 not re-probed. |

## What is proven

Each of these 25 criteria passed the first pass and then survived an independent refuter whose job
was to overturn it.

- **A3.** The engine's `traceFlow` for tcp 10.0.10.50→10.0.30.10:3389 returns outcome `denied`,
  decidedBy acl, raw `deny ip any any`, cite `acls.core1.PROTECT_SERVERS[3]`, which matches the source
  snapshot's raw text. A 4,800-flow sweep found 346 denied traces, every one with an ACL decider, its
  raw text and cite (328 on `PROTECT_SERVERS[3]`, 18 on `INET_RETURN[2]`). The UI names device, list,
  "line 4 of 4", the cite and the literal text, and the INET_RETURN case says "line 3 of 3".
- **A4.** Six selection sources were measured in isolated headless Chromium with URL, queue scroll,
  tab, flow, path scroll and camera read after each. The refuter added palette selections of F140,
  F120 and AP-floor1 during a trace, and Back/Forward restoring `d=core1` with flow and hop.
- **A5.** Hover, click selection, double-click focus and exact reset were measured by camera
  projection; the refuter reproduced each, with reset within 0.3 px after a settled orbit.
- **B1.** A sweep of all 26 devices across five tabs, plus links, queue and path, found no
  null-as-healthy; every rendered 0 was checked against the source. The refuter spot-checked links,
  the palette and blast fields and found nothing beyond the disclosed latent compile site.
- **B3.** `npx vitest run src/forwarding/engine.test.ts …` 112/112 (refuter: 81/81), including
  "unmodelled forwarding is never delivery > stops at the host whose forwarding table we do not hold ✓".
  400 of 4,160 traces touch a no-RIB host, all indeterminate; the refuter's 4,800-flow sweep found
  0 deliveries through one.
- **B4.** `engine.off-subnet.test.ts` green; all 1,456 out-of-scope traces carry "lies in no subnet";
  the refuter's 2,480 random sources confirmed it, except sources that really are in observed subnets.
- **B5.** Unit tests against the real `PROTECT_SERVERS` and `INET_RETURN` data; the refuter re-ran
  them ("Tests 10 passed | 69 skipped") and swept 630 flows with 0 violations and 0 unnamed blockers.
- **B6.** 796 of 796 distinct model citations resolve; 770 identity cross-checks and the refuter's
  589 field comparisons against the source show 0 mismatches. The Provenance tab names the source file
  and its LF-normalised sha.
- **B7.** The four coverage buttons are permanent and visible at 1920, 1440 and 390; the refuter
  checked 72 state × viewport combinations and found all four visible and hit-testable.
- **C2.** `capture.mjs app` "PASS capture app 32 of 32 frames rendered, settled on screen and at tier
  high"; `capture.mjs text` "PASS text 72 of 72 states free of clipped/broken text"; two independent
  DOM sweeps found only real data.
- **C3.** Measured row visibility at 1920 and 1440; viewed by both first pass and refuter.
- **C4.** All 8 states in both themes; token analysis shows no inversion; the refuter's scan found no
  dark-only surface in light.
- **C6.** Runtime transition events (maximum 140 ms), `getAnimations()` `[]` at idle, source constants
  matching §4.8, and the motion-inventory test; the refuter's idle screenshot hashes were identical.
- **D2.** The APG grid contract on the findings grid, key by key at 1440 and 390; the refuter also
  passed the Cross-layer grid.
- **D4.** Computed and pixel-verified contrast at 1440 in both themes; the refuter added 390 and 768.
- **D5.** `getBoundingClientRect` over 929+ targets and a cursor-based scan, confirmed by the refuter
  across 13 states and 3 widths.
- **D6.** A 66,539-sample `pick()` sweep equals the fabric's 26 devices and 44 links, and all 114 tree
  rows selected the right object by keyboard.
- **D7.** `capture.mjs reduced`: "PASS  D7: camera lands in one frame under reduce, 23 poses without
  it.", reproduced by the refuter; 0 transitions over 1.5 ms under reduce.
- **D8.** Greyscale captures of 03 and 06 in both themes; the refuter found no colour-only channel.
- **E1.** `journey-scope.test.ts` ties `acceptance.md` to the harness ids; every journey actuated with
  a verified effect ("25 of 25"); the refuter probed J5's act directly (26/26).
- **E4.** Three `measure-fps.mjs` runs with `acceptanceEvidence=true` on a quiet, on-AC host; the
  refuter reproduced it (orbit median 59.03 fps, worst window 58.07) and drove the degradation path
  under CPU throttling, which read "below frame-rate bar" and stepped down to balanced explicitly.
- **F1.** All three `tsc` projects exit 0 under `strict` + `noUncheckedIndexedAccess` (scripts with
  `noImplicitAny`); reproduced by the refuter.
- **F2.** "Test Files 136 passed (136) / Tests 2106 passed (2106)", EXIT 0, reproduced by the refuter
  under load; exactly the 10 declared mock files; the zero-assertion guard active.
- **F5.** The compiler reproduces `fabric.json` byte-for-byte; the refuter ran all four compilers in a
  `git archive` sandbox against the parent blob `1ed99404` and matched every output.
- **F6.** `capture.mjs twice 5`: "F6 PASS: 32 of 32 frames byte-identical across 5 runs.", reproduced
  by the refuter, who also added 375x812 at DPR 2 (0 of 16 frames varied).

## What is not

### FAIL (7)

- **A1 — evidence behind a finding.** 134 of 146 findings (133 context-only landings plus F142) have
  no configuration-evidence route. For F088 the pane says "No configuration evidence route: the
  finding names no configuration line and nothing we hold matches its words." Where a route exists it
  takes 3 interactions and lands on parsed fields. None of the 6 findings that name configuration
  reaches literal configuration text; F099's record says "Its surrounding configuration block was not
  kept, so there is no literal text". Not closable in Atlas Scope: the producer publishes no
  per-finding record pointers (O12).
- **A6 — blast radius on the fabric (overturned from PASS; refutation applied).** With a trace active,
  which A4 requires to survive a device selection, the camera stays framed on the trace. Selecting
  core2 then marks 5 of its 8 stranded hosts (`access11, access13, access15, access7, access9`);
  access3, access5 and access17 are off-canvas (`visible:false`) with no mark. Nothing on the fabric
  gives a count or says marks are out of view. The toolbar reads only "Stranded marks are uncertain;
  0 under the all-nodes projection", and the fabric list shows "access3 | Poor" with no mark. For core1
  in the same state, `data-stranded=yes` count is 0 of 26 until the button "Blast radius: core1
  strands 9 (uncertain; 0 under the all-nodes projection)" is pressed (`Fabric3D.tsx:916-952`). The
  refuter reproduced this through a real palette interaction (ui9.mjs).
- **B2 — scope claim and caveats on every verdict.** The engine meets it. The Ctrl+K palette does not:
  it renders "10.0.10.50 -> 10.0.30.10:3389 | trace a path — this one ends denied" and "…— denied.
  … which is the blocking-hop answer with its exact configuration line", with no 2-of-26 scope and no
  caveat. That flow's own trace says "That denial is not decided". Cause: the `suggestedFlows()`
  "denied" rationale in `engine.ts` `buildSuggestions`, rendered by `commands.ts:404-409` and
  `:734-739`. The palette's no-route row does say "so the drop is not decided" (`engine.ts:3056`).
- **C5 — cheap-render tells, item 8 (1 px hairline links).** A dashed stroke 1 device px wide
  (0.5 CSS px at DSF 2) runs about 450 device px down the access9/access3 bundle from core2, at both
  tiers and in both themes (dark +15/+69/+37 luma at (806,400)/(808,450)/(812,500); light −8/−42/−31).
  design-brief §4.5 sets 2 CSS px as the minimum painted stroke. `scene.pick` at those pixels returns
  L33, but selecting L33 leaves the stroke unchanged, and no dashed core2→access link exists in
  `fabric.json`. The owner must identify what draws it. Every other C5 item passed, the motion items
  included.
- **D1 — keyboard reachability (overturned from PASS; refutation applied).** At 768 px on the Path
  surface the visible "Which panel to show" radiogroup renders
  `<button role="radio" aria-checked="false" tabindex="-1">Queue</button><button role="radio"
  aria-checked="false" tabindex="-1">Evidence</button>`. The refuter's output: "paneswitch focused
  during 60 Tabs: 0" and "after 60 Shift+Tabs, paneswitch hits: 0". A mouse click on Queue works.
  Cause: `src/app/surfaces.tsx` PaneSwitch gives `tabIndex={value === p.id ? 0 : -1}`, the value is
  `path`, and the pane list omits `path` because `pathAvailable` is false. The state is reached by an
  ordinary keyboard journey (More → Path), not only by deep link.
- **D3 — focus visible.** At 390x844 with `?d=core1&s=fabric`, Tabbing to "23/26 collected", "RIBs
  2/26 (both shown incomplete)", "ACLs 1/26", "centrality 25/44" and "claim strength" leaves each box
  inside the viewport, but `elementFromPoint` returns `LI.dp-list__row` / `SPAN.dp-list__main` /
  `DIV.dp-panel` at all 9 sample points, and pixel diffs show "'23/26 collected' 0/4400", "'claim
  strength' 0/2112", "'centrality 25/44' 0/4440": no focus ring is painted. Measured cause: the status
  bar is `position:sticky` with z-index 5, and `.rail--b` (z-index 30) paints over it once the document
  scrolls far enough (10537; not at 2000 or 6000). Reproduced at 390 in states 06 and 09 in both themes
  and at 600x900 state 09. Focus return and modal trapping passed. The recorded
  `audit-d3-focus.mjs` reported "0 not visible" for this; it was not re-run.
- **E5 — responsive during load.** Two acceptance-grade invocations (`acceptanceEvidence=true`, busy
  0.241 and 0.24 against 0.25, on AC). Invocation 1: "FAIL E5 5 animation frame(s) over 200 ms with
  NOTHING on screen … (worst 277.9 ms at 224.1 ms, run 1); 8 keystroke(s) over 200 ms (worst 400 ms)".
  Invocation 2: "FAIL E5 5 animation frame(s) over 200 ms … (worst 316.4 ms at 224.1 ms); 5
  keystroke(s) over 200 ms (worst 280 ms)". The keystrokes landed after first paint (FCP 652–800 ms),
  about 1.1–1.3 s into the load: keydown 400 ms at 1114.8 ms (input delay 87 ms), keydown 280 ms at
  1192.5 ms. `acceptance.md` fails E5 "on any keystroke over 200 ms during the load", so this does not
  depend on the owner's pre-FCP carve-out decision (O20). The out-of-load sweep passed.

### UNPROVEN (7)

- **A2 — hop-by-hop result.** Only depth 1 ran. The ratchet asserts maximum observed depth `toBe(1)`,
  so the second hop's decider, hop-to-hop navigation, the cable-map branch, the TTL cut and the loop
  detector never executed on real data. The criterion itself forbids grading a depth-1 capture PASS.
  Needs a snapshot with depth-2 flows (O34).
- **B8 — counterexample.** Only the negative state renders on this snapshot: 924 denied or dropped
  traces, 0 counterexamples, `isDefiniteDelivery` 0 of 4,160. The positive state runs only under
  `vi.mock('./rib-completeness')` and `vi.mock('./bindings')`. Needs a snapshot with a decided refusal
  and a definite delivery (O13).
- **C1 — blind critic verdicts.** `review/blind/KEY.json` has 12 entries and no verdict, winner, critic
  or reasons field; 8 sheet PNGs are orphans the key cannot decode; the brand-cropped
  `sheet-d808251b311c.png` still shows "Forward AI" and the Storylane modal. `review/REFERENCES.md`
  withdraws the round 1–3 win tables. There is no valid blind verdict, and none can be obtained
  against these references. Owner decision (O19).
- **E2 — INP ≤ 200 ms on the declared journeys (overturned from PASS; refutation applied).**
  `acceptance.md` names `J2-first-select-device-3d` as an E2 subject. Its figures (p95 64 ms,
  max 80 ms over 21/21 trials) come only from runs the harness refused: "NOT ACCEPTANCE EVIDENCE …
  host was 35% busy across the run excluding this harness" with "(gross 36%, harness 0%, idle baseline
  before launch 17%)". The harness itself says J2's rep 0 cannot stand in ("one sample per run is not
  a distribution"). The latencies are well under the bar, so this is not a FAIL; it needs an accepted
  J2-first run.
- **E3 — no long task over 50 ms on a journey's path, stable across runs.** Six of seven ids are
  "STABLE PASS (3/3 measured runs clean)" on quiet hosts. `J2-first-select-device-3d` reads
  "INSUFFICIENT RUNS (0/0 measured runs clean)" across all 7 runs, though it was E3-clean in every
  (busy) one. Newly found cause, not in `open-issues.md`: `review/measure-inp.mjs` calls
  `hostLoadMeter.sample()` only at `:1556`, not before the 21 `fresh.close()` calls (`:1490`), the
  scout browser's close (`:940`) or per-journey `ctx.close()`. `host-env.mjs:292–296` says a child
  that exits "takes its CPU counters with it", so the harness's own browsers are booked as external
  load. An independent sidecar measured Playwright Chromium at 7.2% (full run, harness reported 1%)
  and ≥9.3% (J2-first run, harness reported 0%). Even corrected, a J2-first run sits near 28%, above
  the 25% bar, so its quiet gate is not reachable on this host without a harness fix or an owner
  decision.
- **F3 — regression test that failed before each fix.** Real pre-fix red exists only for the R34
  claims fix (`Tests 2 failed | 37 passed`, `AssertionError: expected 'SCOPED' to be 'INDETERMINATE'`)
  and the O15 provenance tests (`Tests 8 failed | 10 passed`). History starts at `50a3dc5`; the
  original forwarding (5), blast (7), layout (4), query (1 class) and compiler (4) defects predate it.
  `mutation-check.mjs` shows today's tests catch reverted guards, which is not history, and covers
  forwarding 4 of 5, blast 2 of 7, layout 2 of 4 and compiler 2 of 4, leaving about 10 confirmed
  defects with no executable red check of any kind. `refutation.md` §7 leaves the compiler's
  "field survives with changed meaning" attack open (O34).
- **F4 — three.js not in the initial payload (overturned from PASS; refutation applied).** The split
  exists and the build facts reproduce. But at 768 px and wider, which includes every viewport the
  product's captures use, the first load fetches three with no user action: at 1920x1080 `/`, three
  was requested at 1515 ms (transfer 238,949 B) with jsDecoded 1,970,906, against 957,310 at 767 and
  375 px. `acceptance.md`'s evidence column narrows the scope to "only below 768 px", but the
  criterion's wording is broader. Proven: code-split, and absent from the initial payload below 768 px.

## What was not examined

Collected from each grader's and refuter's own statements.

**Group A.** None of the 6 named-configuration findings (e.g. F102) or F106/F107's literal MGMT_IN
landing was opened in the UI; they rest on `EvidencePane.namedconfig.test.ts`. The A1 census was not
driven through all 146 findings (O28 keystroke race). The queue-row route for rows already in view was
measured only on F088. A6's "Blast radius" toolbar button during a trace was not pressed by the first
pass. The evidence-chain "Select <host>" chip was not found by the selector, so that A4 surface is
untested; the refuter also skipped path-panel hop selection and the evidence-chain chips. The
Device-pane Findings list as a selection source, and camera preservation after a prior flight, were
not measured. Nothing below 1920x1080, no dark theme and no production build for A. The refuter did
not re-sweep B1 across all 26 devices, did not reproduce A6's pixel diffs or FHRP/backup disagreement
text, and did not execute the latent `?? "Info"` path against a mutated snapshot.

**Group B.** The WebGL colour and state of uncollected and partial-band nodes were not pixel-probed.
The Raw tab, the Evidence pane for all 146 findings, palette coverage of the status bar at 390 px
(O32), the production build, invalid-flow refusals in the UI (engine code only), and "failed before
the fix" history were not examined. The refuter replaced the 10 random click-throughs with an offline
field-identity comparison.

**Group C.** C4 first paint (the probe fired too early, R40) and the dev-server residual. C2 descender
clipping (no detector, O17) and compact density. C6 per-frame canvas ease timing; the packet loop never
runs on this snapshot. C5: the object behind the hairline, the "balanced" tier, the dev server,
`fabric-preview.html`, and an organic mid-motion step-down. The motion run was one run on one contended
host (Intel iGPU, ANGLE D3D11). The refuter did not rebuild :4293 or rerun `capture.mjs app`/`text`,
and viewed C3 at 1440 only.

**Group D.** No real screen reader (NVDA, JAWS, Narrator). Forced-colors / High Contrast, 200–400%
zoom, text-spacing reflow, touch input and hover-state contrast. D4: severity-chip letters by computed
style only; text under the palette scrim excluded; pixel pass at 1440 only; the current-hop indicator
(semibold only, bottom border 1.30 light / 1.46 dark) could not be judged with single-hop data. D3
traversals covered states 01, 02, 04, 06, 09 at 1440, 390, 768, 1000, 600. D2 first pass covered the
Findings grid only (the refuter added Cross-layer). `review/audit-d3-focus.mjs` and the E harnesses
were not re-run by D. The refuter did not re-run the A1/A2 keyboard journeys, the canvas orbit pixel
test, the 66k pick sweep or the D4 pixel pass; its D1 scan covered 9 URL states, not dialog-open
states, and ran on the dev server.

**Group E.** Laboratory figures only; no field INP. The dev server and `fabric-preview.html` were not
used. The E4 "trace animating" condition was checked for one flow only. A full 1920x1080 render
target (`ATLAS_FULLBLEED=1`) was not measured (canvas 1161x962). No other machine. The first pass saw
no explicit degradation fire; the refuter drove it under CPU throttling.

**Group F.** No F result was re-run from a fresh `git clone` of `70bea72`, especially under
`core.autocrlf=true` (O23); the refuter used `git archive`, which applies `.gitattributes` but is not
a clone. The first pass ran only `compile-snapshot.mjs` directly (the refuter ran all four). The
hollow-test audit read 9 heuristic hits and the mock files, not all 136 files. Historical red-before-
fix was attempted only for R34 and O15. The faithfulness of each mutation's `find` text was not
judged. F6 dev-server runs were `app` ×2, not `twice 5`. O22 was not re-probed. `refutation.md` was
read only in part. No second host or GPU, and no GPU tile raster.

**Environment and side effects.** The shared Browser pane tab "seed" was driven by another agent
during grading (resized to 390x844, navigated, "F099" typed into its palette); groups A and D took no
evidence from it after that. The E harnesses overwrote `review/reports/inp.json`, `fps.json`,
`e5-coldload.json` and `e5-sweep.json` and appended `inp-e3-history` records; C's motion run
overwrote `review/shots/motion/report.json`. The F grader's `npm run build` rewrote `dist/` with the
same chunk hashes and removed the untracked `dist/.atlas-source-stamp.json`. The B grader overwrote
four stale probe files other graders had left in `scratchpad/probe/`. No grader or refuter edited
product source or made a git write. Probe scripts and captures are in the orchestrating session's
scratchpad (a per-session temporary directory outside this repository; not preserved).

**Open issues not examined by anyone this round:** O6, O7, O8, O11, O14, O29, O33.

## Known issues carried forward

Reconciled against `docs/open-issues.md` (the uncommitted working copy at `70bea72`).

### Confirmed unchanged

- **O12 (A1).** Confirmed again: still 12 of 146; not closable in Atlas Scope.
- **O13 (B8)** and **O34 (A2, F3).** Confirmed: depth 1, 0 counterexamples, no pre-`50a3dc5`
  history. The F3 grader adds the per-engine coverage gap (about 10 confirmed defects with no
  executable red check).
- **O19 (C1).** Confirmed: no verdicts; the references identify themselves.
- **O26.** Confirmed: `layout.test.ts:945` still asserts a `performance.now()` median under 50 ms, so
  `acceptance.md` F2's "Timing is not asserted in the unit suite" is false, and its "45 of 135" count is
  stale (now 46 of 136).
- **O27.** `review/*.mjs` remains outside every type-checked project (declared).
- **O23.** Still open: nothing was run from a clone of `70bea72`.
- **O17.** Descender clipping and compact density still unmeasured. The new D1 finding is at 768 px,
  which O17 says no guard measures.
- **O20.** The pre-FCP carve-out is still an owner decision; the E5 keystroke FAIL stands without it.
- **O16.** The C5 motion items passed in this round's independent run; the owner decisions (a caller's
  tier change mid-motion, the cluster-rule wording) remain open.

### Superseded or not reproduced by this round

- **O25.** Partly superseded: E1, E2 (six ids), E3 (six ids), E4 and E5 now have acceptance-grade runs
  at `70bea72`. What remains is J2-first, blocked by the load-meter defect below.
- **O30.** Not reproduced on a quiet host: J5 was E3-clean in 3 of 3 quiet runs; its one 51 ms
  on-path task ("style/layout/paint-only; no script over 5 ms") was in a busy run.
- **O31.** Not reproduced: J2's effect was verified 25/25 in every run.
- **O21.** Partly reproduces: navigation seeding ("path trace: seed a flow by navigation") measured
  70.8–82.1 ms; resizes showed 0 ms of the app's own work.
- **O32.** Extended by the B7 refuter: with the Keyboard-shortcuts dialog open at 320x568 the dialog
  body fully covers "23/26 collected", "RIBs" and "ACLs". Still treated as a transient modal, not a
  B7 failure; the owner has not decided.
- **R32.** Its fix said light-theme links no longer read as ~1 px, with the width figures "reported,
  not verified". The C5 hairline is a sub-2 px stroke in both themes; whether it is the same class is
  unestablished.

### New this round, not yet recorded in `docs/open-issues.md`

1. **A6 blast marks with a trace active.** Off-canvas stranded hosts get no mark or count; the trace's
   own hop withholds marks behind a button (`Fabric3D.tsx:916-952`).
2. **B2 palette verdicts without scope or caveat.** `buildSuggestions`' "denied" rationale calls an
   undecided denial "the blocking-hop answer" (`commands.ts:404-409`, `:734-739`).
3. **C5 0.5 CSS px dashed hairline** in the core2→access9/access3 bundle, both tiers and themes;
   drawing object unidentified.
4. **D1 PaneSwitch at 768 px on Path.** No radio matches `value='path'`, so both take `tabindex=-1`
   (`src/app/surfaces.tsx`).
5. **D3 status bar under `.rail--b` at narrow widths.** Sticky z-index 5 vs rail z-index 30 once
   scrolled; also a recorded-audit blind spot (`audit-d3-focus.mjs` reported "0 not visible").
6. **E5 keystrokes 240–400 ms during load**, after FCP, in two acceptance-grade invocations.
7. **`measure-inp.mjs` load-meter accounting.** `hostLoadMeter.sample()` only at `:1556`; closed
   browsers are booked as external contention, contrary to `host-env.mjs`'s own contract.
8. **F4 scope.** At ≥768 px three.js (1,013,596 of 1,970,906 decoded JS bytes) is fetched on first
   load; the criterion's wording and its evidence column disagree. Owner decision: narrow the
   criterion or defer the fabric mount.
9. **B1 latent laundering.** `tools/compile-snapshot.mjs:332/:350` (`severity: val(...) ?? "Info"`)
   and `:352` (`title ?? ""`) would render a future null severity as a benign Info finding.
10. **Observations, not failures:**
    - The B8 heading "Nearby flow with a different outcome" sits over a body that says none was
      offered.
    - The A4 queue `aria-current` lags the URL by 0.5–3 s under load.
    - A5 reset does not cancel the OrbitControls damping tail (`camera.ts`), so a reset pressed 0.3 s
      after a drag release landed at 547,54 instead of 474,82.
    - Two idle rAF loops run continuously (`scene.ts:2768`, `FabricLabels.tsx:320`, 241 calls each in
      4 s).
    - E4's "tier high" suspends ambient occlusion while the camera moves (`postfx.ts` `setMotion`),
      disclosed in `qualityReasons` but not in `acceptance.md` or `measure-fps`'s report.
    - The B5 established-line test would pass without isolating that line.
    - The fabric tree's item names do not carry trace or stranded marks (D6).
    - Status-bar buttons partly overflow at 768, 1000 and 390 px (D3 leads).
    - The palette search input has no boundary of its own (1.38 on an inner divider).
