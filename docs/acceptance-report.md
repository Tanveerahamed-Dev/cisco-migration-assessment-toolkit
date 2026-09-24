# Atlas Scope — Acceptance Report

Graded 2026-09-24 against `docs/acceptance.md`, at HEAD `78bdba5` ("fix: close acceptance repair wave 5
(A6, B2, C5, D1, D3, F4) and the dev-watch load"). Every grader found the same tree. `git status --short`
showed only ` M docs/open-issues.md`, an uncommitted documentation edit. `git ls-files --others
--exclude-standard` printed nothing, so the build imports no untracked file.

Six first-pass graders covered groups A–F. Independent refuters then attacked the PASS verdicts. Every
group returned a grade, so no group is marked "grader did not run".

**Where the first pass and the refutation disagree, this report applies the refutation.** Five PASS
verdicts were overturned to FAIL: A4, A5, B6, D1 and D5. Each overturn came with a reproducible proof
(a named script, its printed output and a screenshot), so none was set aside. One PASS, D2, was never
attacked because its refuter did not return. It is listed below as "PASS, unrefuted", not under "What
is proven".

This report replaces the grade of `70bea72` at this path. Figures from that report appear here only
where they are labelled as history.

**Where each group was graded:**

| Group | Server and tree |
|---|---|
| A | Dev server on :4180. A1 used the shared Browser pane. A4–A6 used an isolated headless Chromium, because another agent was driving the shared pane. |
| B | Dev server on :4180. Engine modules were imported live in the page with `import('/src/...')`. |
| C | Release build served from `dist/` on :4181. A scratch rebuild's `dist/index.html` sha256 was `bca154bb…`, byte-identical to the served one. `capture-motion` reported "build fresh: true". |
| D | :4181 production preview. `checkBuildFreshness` returned `fresh:true, servesLocalDist:true`. The D2 key walk used the :4180 dev server. |
| E | `npm run build`, served by `vite preview --port 4181 --strictPort`. The harness reported "build: fresh". **The host was on battery for the whole session.** |
| F | Working tree, plus a fresh `git clone` of `78bdba5` in the scratchpad for F1, F2, F4 and F5. |
| Refuters | The :4180 dev server (the :4181 preview was down for some of them) and a private scratch build on :4191. |

**The tracked-sources gate is a precondition, not a criterion.** `src/core/tracked-sources.test.ts`
passed 6 of 6 in groups A, B, D and F. It also passed inside green multi-file runs in C ("Test Files 2
passed, Tests 33 passed") and E. One exception: in F's loaded fresh-clone suite, 2 of its tests timed out
(35.5 s and 31.4 s). They passed in the targeted re-run. F rebuilt the entry pages with a
module-recording plugin: "92 application modules, 0 are untracked and 0 differ from HEAD".

## Verdict

**Atlas Scope is not ready for acceptance at `78bdba5`.** Seven criteria FAIL:

- **A1:** configuration evidence is reachable for only 12 of 146 findings.
- **A4:** a finding selected from another surface is not revealed in a filtered queue.
- **A5:** Reset view does not reset while the orbit is still coasting.
- **B6:** the Path surface shows a RIB-incompleteness claim with its citations dropped.
- **D1:** a mouse-operable off-view pointer can never receive keyboard focus.
- **D5:** that same pointer is a 16.84 px target.
- **F2:** `npx vitest run` went red on a fresh clone: 12 timeouts under host load.

Eight more are UNPROVEN, and UNPROVEN is not a pass:

- A2 and B8 need producer data this snapshot does not have.
- C1 needs an owner decision.
- E2, E3, E4 and E5 have no acceptance-grade run, because the host never left battery power.
- F3 lacks executable red-before-fix history for four engines.

The other 24 criteria PASS: 23 survived an attack, and D2 was never attacked. The engine's honesty
under the collected data is strong. B1–B5 and B7 held against sweeps of up to 10,374 traces with zero
counterexamples. Craft, contrast, reduced motion and determinism also held. The failures are
concentrated in two places: one off-view pointer control (it causes both D1 and D5), and the edges of
camera and selection behaviour that the first pass did not probe.

## Scorecard

Verdicts are final, with every overturn applied. "Upheld" means a refuter attacked the PASS and it
survived. "Overturned" means the refutation's proof was applied in place of the first pass.

| Criterion | Verdict | Evidence | Note |
|---|---|---|---|
| A1 | **FAIL** | Census of all 146 findings: named 6, matched 6, context only 133, no button 1. For F001 the pane printed "No configuration evidence route: the finding names no configuration line and nothing held matches its words". The F099 route took 3 interactions, and the camera stayed put: core1 at (474.4, 82.2) before and after. | `acceptance.md` itself says "NOT MET for the other 134". O12. |
| A2 | **UNPROVEN** | Depth 1 works: "Hop 1 of 1: core1", "ACL — THIS IS WHAT DECIDED THE HOP: PROTECT_SERVERS line 4 of 4". The depth ratchet asserts max depth `toBe(1)` (`engine.test.ts:1051`). | Multi-hop has never run on real data. O34. |
| A3 | PASS (upheld) | "denied at core1 by ACL PROTECT_SERVERS line 4 of 4 (acls.core1.PROTECT_SERVERS[3]: \"deny ip any any\")". The refuter swept 810 flows: only PROTECT_SERVERS[3] and INET_RETURN[2] ever block, and both are named with their literal text. | |
| A4 | **FAIL (overturned from PASS)** | Refuter: `?q=severity%3ACritical`, then Ctrl+K "F120" Enter. The URL read `?f=F120&q=…` and the status bar "selection F120". Queue rows: `[header, 'Critical3', F001, F002, F003, 'High0', …]`. Grid elements with aria-current, data-active or aria-selected: `[]`. The left rail contains "F120": `false`. | The first pass tested only an unfiltered queue. Its other A4 claims reproduced. |
| A5 | **FAIL (overturned from PASS)** | Refuter: an orbit-drag of 240 px, a 300 ms wait, then Reset view. core1 settled at (410.7, 91.7) against a home pose of (474.4, 82.2), about 64 px off, and stayed there for 40 s. The control (a 20 s wait before Reset) returned (474.0, 82.3). The Home key drifted "11→22 px". | `camera.ts` `moveTo()` never clears the damped delta of OrbitControls. This was already an O37 lead and is now confirmed at `78bdba5`. The refuter ran on SwiftShader at 3–9 fps; the error grows as the frame rate falls. |
| A6 | PASS (upheld) | Selecting core1 reads "core1 strands 9 … · all 9 marked" and shows the "⚠ CUT POINT" mark in purple rgb(99,72,140), not `--state-down`. Canvas pixel diff: 5.08–5.40% for the cut point against 1.29–1.40% between non-partitioning devices. The refuter confirmed the "≠ IMPACT DISPUTED" mark (`data-disputed=yes`). | |
| B1 | PASS (upheld) | Sweep across 26 devices × 6 tabs, 44 links × 3 tabs and all 146 findings, covering innerText and the title, aria-label, aria-description, aria-valuetext, placeholder and alt attributes: "zero hits" for null, undefined, NaN, Infinity or `[object Object]`. AP-floor1 reads "Not assessed — this device was never reached". | Residuals: O36 is wider than recorded, and `scene.test.ts:122` pins nothing (see Known issues). |
| B2 | PASS (upheld) | 3,968 traces gave `noScope=0`, `emptyCaveats=0` and 0 claims missing "2 of 26". The refuter's 5,488 edge-address traces agreed. | |
| B3 | PASS (upheld) | 800 of 800 traces through dist1 were indeterminate, and 0 of 10,374 traces were `isDefiniteDelivery`. The UI reads "INDETERMINATE — THE MODEL COULD NOT DECIDE THIS FLOW" and "dist1 not modelled — undetermined". The refuter found 1,920 of 1,920 indeterminate. | dist1 is the only no-RIB host any trace can reach. |
| B4 | PASS (upheld) | 1,300 out-of-scope traces, each with 0 hops and `oosNoWords=[]`. The UI reads "198.51.100.7 lies in no subnet this collection observed". The refuter's 13 edge sources (0.0.0.0, 255.255.255.255, 127.0.0.1, 224.0.0.5 and others) agreed. | |
| B5 | PASS (upheld) | `evaluateAcls` isolated on INET_RETURN: tcp/443 to 203.0.113.9 gives `indeterminate`, decidedBy `acls.core1.INET_RETURN[0]`. On PROTECT_SERVERS, icmp is `indeterminate` on `[2]` for icmp_type. | The object-group branch holds only on a synthetic group. |
| B6 | **FAIL (overturned from PASS)** | Refuter, on the first pass's own flow `…tcp>3389&hop=0`: the text "FULL/DR, yet the table" appears 5 times in the DOM (the headline `P.claim__sentence`, the Filtering row, a caveat LI and `hop__note`). The citations that back it, `routing_neighbors.core1.ospf[0]` and `protocol_assessability.rows[123]`/`[124]`, appear 0 times each. The icmp flow shows the same pattern: "240 received prefixes" 5 times, and its citations 0 times, with `nearbyCites=[]`. | `rib-completeness.ts` `ribIncompletenessSentence()` joins `x.label` and drops `x.cite`. The first pass counted citations, not claims. |
| B7 | PASS (upheld) | "coverage 23/26 collected · RIBs 2/26 (both shown incomplete) · ACLs 1/26 · centrality 25/44 · snapshot 9580aa09 2026-08-07". `elementFromPoint` places all three figures in the viewport at 390 px, and the refuter found the same at 320×640 and 568×320. | O32 (palette open) was not examined. |
| B8 | **UNPROVEN** | 10,374 traces, of which 2,290 were denied or dropped. `counterexample() found=true: 0`, and `isDefiniteDelivery` was true for 0 traces. The UI shows the honest negative: "NEARBY FLOW WITH A DIFFERENT OUTCOME — NONE OFFERED". | The positive state never renders on real data; it is covered by fixtures only. O13. |
| C1 | **UNPROVEN** | `review/blind/KEY.json` has 12 entries with no verdict, winner, critic or reasons field. 8 of the 20 sheet PNGs are not in KEY.json. The "craft" sheet still shows "Forward AI" and a Storylane "Start" button. | No blind verdict exists, and the reference captures cannot be blinded. O19 (an owner decision). |
| C2 | PASS (upheld) | `capture.mjs app`: "32 of 32 frames rendered, settled on screen and at tier high", all byte-identical to the recorded frames. `capture.mjs text`: "PASS text 72 of 72 states free of clipped/broken text", "PASS wrap 0 unjustified token-break licence(s)". The selftest passed 23 of 23. | Observations are listed under Known issues. |
| C3 | PASS (upheld) | At the 03 state, 1920: every title is whole. At 1440 one title is clamped and loses only "gateway". | Comfortable density only. The refuter found 80 of 107 titles clamped live on the dev server at 1440 without the Inter font, so the result is fragile at nearby widths. O17. |
| C4 | PASS (upheld) | Hue histogram of the saturated pixels: 0° dominant in both themes (01: 85% dark, 60% light), with no shift towards 180°. The refuter scanned light-theme overlays and found no dark panels. | |
| C5 | PASS (upheld, one item attacked) | `capture-motion`: "PASS z-fighting — 1082 slow-motion frame steps", "PASS LOD/effect/label popping — 2641 still frame pairs", "PASS AO drop and restore (high tier) — 8 restores", "PASS 280 ms tier cross-fade — 24 of 24". `probe-fabric.mjs --hairline` found 0 chains. There are 0 pure-black pixels. | The refuter attacked only the 0x000000 item (0 of 1,115,920 canvas pixels were black). Aliasing, lighting, banding, z-fighting, popping, AO and hairline stand on the first pass alone. |
| C6 | PASS (upheld, code attack only) | Runtime durations are only 0.08, 0.14 and 0.24 s. At idle: 0 DOM mutations in 4 s, 0 `getAnimations()`, and 3 screenshots 1 s apart were byte-identical. The refuter's code attack found no undeclared long motion. | The packet loop's 3-loop bound is established by code, not observed. |
| D1 | **FAIL (overturned from PASS)** | Refuter (`ptr3.mjs`): the off-view pointer `.fabric3d-pointer` for access5 is visible and unoccluded, with 5 of 5 probes landing on it. The output read "Tab walk 250 stops, pointer reached: false". Its attributes are `tabindex:-1` and `ariaHiddenAncestor:true`, and it has an `onClick`. In dark theme it sat under the HUD, and a click there did nothing. | Mitigation: the same framing can be reached with canvas arrow keys and Enter, or through the fabric tree. The verdict follows the criterion's literal wording, "every interactive control". The first pass's census never showed this pointer. |
| D2 | PASS, **unrefuted** | Grid with `aria-rowcount=152` and exactly 1 `tabindex=0`. A full APG key trace (arrows, Home and End, Ctrl+Home and Ctrl+End, PageUp and PageDown, Enter to sort and select, Tab out and Shift+Tab back) behaved as specified. The `DataGrid.test.tsx` contract tests are green. | The refuter did not return; the only check was a code read. Walked on "Findings, ranked" only, not "Cross-layer records". |
| D3 | PASS (upheld, narrow) | `audit-d3-focus.mjs --vp=1440,1000,768,390`: "416 case(s), 0 failed", "823 focus stop(s) checked for visibility, 0 not visible", "SWEEP: 129 composite widget(s), 1156 tab stop(s), 1471 nine-point hit test(s) … 0 failure(s)". | The acceptance run was split across two invocations, and the second was narrowed with `--vp`. The refuter tested one self-removing control. |
| D4 | PASS (upheld) | 44 state, viewport and theme combinations and about 40,800 text elements: "0 computed failures". Minimum 4.60:1 light and 4.71:1 dark. The refuter added 768 and 1920 and found 0 below 4.5. | Contrast of the WebGL chassis and link colours was not measured. |
| D5 | **FAIL (overturned from PASS)** | Refuter: `settled [{"for":"access5","w":141.23,"h":16.84,…,"hits":5}]`. A click at its centre re-framed the camera on access5, so it is a working target, 16.84 CSS px tall. There is no exemption for it in docs/, review/ or src/. | The first pass's census left out clickable elements that have no role and no tabindex. `target-size.test.ts` passes because the rule declares no size. |
| D6 | PASS (upheld) | Picking every 3 px found 26 devices and 44 links. The fabric tree reached 119 items: `missingDev=[]`, `missingLink=[]`, `extraLink=[]`. Space on an item writes the same selection as the canvas. | No real screen reader was used. Tree names carry no trace or stranded marks (O37). |
| D7 | PASS (upheld) | `capture.mjs reduced`: "PASS  D7: camera lands in one frame under reduce, 23 poses without it." Transitions over 10 ms under reduce: 0, against 325–508 in the control. | The packet half is fixture-only. |
| D8 | PASS (upheld) | In greyscale: severity letters C, H, M, L, I; band letters P, C, G*, E*, ?; dashed cables for uncollected devices; the glyph and word marks ✕, ?, ✓, ⚠, ⊘ and ≠. The refuter found no information carried by colour alone. | Forced-colors mode was not tested. |
| E1 | PASS (upheld) | `journey-scope.test.ts`: "Tests 14 passed (14)". J1–J4: "acts with a verified effect 25 of 25". J2-first: 21/21. The refuter watched J5's dialog open and close in 6 of 6 reps. | |
| E2 | **UNPROVEN** | Laboratory only: 3 runs, each "7 pass, 0 fail, 0 NOT MEASURED". Worst p95 was 64 ms (J4), and J2-first p95 was 80 ms. Every run printed "NOT ACCEPTANCE EVIDENCE — … host on battery". | No on-AC run. O25. |
| E3 | **UNPROVEN** | Laboratory run: "PASS — 7 clean, 0 violating". Gated verdict: "E3 across runs of build bca154bb1e58367d (0 run(s), need 3): INSUFFICIENT RUNS". | A 51.7 ms LoAF overlapped a first selection, but the harness does not count frames as tasks. |
| E4 | **UNPROVEN** | `measure-fps`: "median 60 fps across 10 windows, worst window 59.99 fps (floor 45)", then "acceptanceEvidence=false" (THROTTLED). A synthetic 5-hop trace ran at 60 fps mean. | Battery power. No product-reachable flow animates a packet (`tracePacket=false`). |
| E5 | **UNPROVEN** | Laboratory run: "PASS E5 3 cold loads … [NOT ACCEPTANCE EVIDENCE]". Worst keystroke 192 ms, 8 ms under the bar. Sweep: "all 13 actions stayed under 200 ms". | The recorded acceptance-grade FAIL at `70bea72` (O35) stands, because a laboratory run cannot overturn it. |
| F1 | PASS (upheld) | `tsc` exited 0 for all three projects, on both the working tree and a fresh clone. There is no `@ts-nocheck`, `@ts-ignore` or `@ts-expect-error` in src or tools. | `review/*.mjs` is outside every project (O27). |
| F2 | **FAIL** | Working tree: "147 files, 2235 passed", exit 0. **Fresh clone of `78bdba5`: exit 1, 2223 passed, 12 failed**, all timeouts (31–62 s against a 30 s limit), 8 of them in `composite-tabstop.test.tsx`. A targeted re-run of those 4 files: "94 passed and 2 failed", still timeouts. | The suite's verdict depends on host load. `layout.test.ts:953` asserts timing (O26). |
| F3 | **UNPROVEN** | `mutation-check.mjs`: 18 of 18 KILLED. The history reproduced real red-before-fix for claims C2/C3 ("2 failed and 37 passed" against `254694b`) and for forwarding R17 ("5 failed and 1 passed" against `50a3dc5`). | There is no pre-fix history for blast, layout, query, the compiler or forwarding §1.1. O34. |
| F4 | PASS (upheld) | `three-Dyx6ntnn.js` is the only chunk with WebGLRenderer, and there is no modulepreload. The probe (a static import in `mount.tsx`) turned the gate red. Refuter: at 767, 390 and 320 px, three.js was never requested in 21 loads. At 1920 and 768 px, first paint came before the three request in 10 of 10 loads. | The first pass's part-(c) run was on a busy host. |
| F5 | PASS (upheld) | All four compilers are byte-identical before and after, on the working tree and the fresh clone. `sha256 9580aa092d490a13ba420b2cc670ddee026f6dbf93ecc5aeac2fc94cd7f13089`, "3 072 771 bytes (LF-normalised)". | Needs `../webapp` from the parent repository (O23). |
| F6 | PASS (upheld) | "verdict: F6 PASS: 32 of 32 frames byte-identical across 5 runs". Refuter on :4191: "32 of 32 frames byte-identical across 3 runs". | 1920 and 1440 only. O22 is still open. |

Totals, stated so that no FAIL is hidden: **7 FAIL, 8 UNPROVEN, 24 PASS** (23 upheld under attack, 1
unrefuted) out of 39 criteria.

## What is proven

These PASS verdicts survived an independent attack. Each entry lists what established it, and marks
where the attack covered only part of the criterion.

- **A3.** The first pass showed the device, ACL, line and literal text on the tcp/3389 flow. The
  refuter's 810-flow sweep found exactly two blocking lines, and both render all four elements. The
  literal text matches the source snapshot's raw field.
- **A6.** The first pass showed the HUD, stranded and cut-point marks, and a pixel diff (cut point
  5.08–5.40% against 1.29–1.40% for non-partitioning devices). The refuter confirmed the cut-point
  colour is purple, not `--state-down`. It confirmed "≠ IMPACT DISPUTED" for access13, access1 and
  access9. Link blast radius showed 23 agreeing rows and 21 engine-silent rows.
- **B1.** The first pass swept devices, links, 4 findings, and the uncollected and no-RIB panes. The
  refuter swept 26×6 device tabs, 44×3 link tabs, all 146 findings and six attribute kinds, with zero
  hits.
- **B2.** The first pass ran 3,968 traces and the refuter 5,488 edge-address traces. Every trace had a
  scope clause, caveats and "2 of 26".
- **B3.** The first pass found 800 of 800 no-RIB crossings indeterminate, and the refuter 1,920 of 1,920.
  The refuter re-ran `engine.test.ts`, `reaim-tab-and-restore.test.tsx` and
  `verdict-scope.b2.test.tsx`: 95 of 95.
- **B4.** The first pass ran 1,300 out-of-scope traces. The refuter ran the vitest files (90 of 90) and 13
  edge sources, then every IPv4 literal in `fabric.json` used as a source. No in-scope source was
  wrongly refused.
- **B5.** The first pass ran `evaluateAcls` isolated on the real lines. The refuter could not find a flow
  where an unevaluable, possibly matching line was stepped over into a decided verdict.
- **B7.** The first pass checked 1440 and 390 px. The refuter added 320×640 with a device selected and
  with the Inspector open, and 568×320. The footer stayed sticky through a scroll to 4000.
- **C2.** The first pass re-captured 32 frames byte-identical and ran the text detector (72 of 72) and
  the selftest (23 of 23). The refuter's grep and frame review found no placeholder content.
- **C3.** Proven at the criterion's 03 capture and comfortable density only. The refuter confirmed the
  capture but showed the result is fragile at nearby widths (80 of 107 titles clamped live at 1440
  without the Inter font).
- **C4.** The first pass's hue histogram and side-by-side views showed separately authored themes. The
  refuter's dark-panel scan of light-theme overlays found none.
- **C5.** Only the 0x000000-background item was attacked, and it held. The remaining items (z-fighting,
  popping, AO, cross-fade, hairline, aliasing, lighting, banding) rest on the first pass's
  `capture-motion` run and static captures on one contended Intel iGPU host.
- **C6.** The first pass measured runtime durations and idle stillness. The refuter's attack was
  code-only: no smooth scroll, no `element.animate()`, and every constant ≤300 ms except the declared
  exemptions.
- **D3.** The first pass's harness reported 0 failures across 416 cases. The refuter checked one
  self-removing control ("Clear scope") at 1440 and 390; focus landed visibly on the header query. The
  attack was narrow.
- **D4.** The first pass measured about 40,800 elements. The refuter added 768 and 1920 in 5 states: 0
  below 4.5:1. A sanity rerun reproduced the first pass's minima of 4.60 and 4.71.
- **D6.** The first pass's pick census matched the tree census. The refuter attacked at five widths and
  in the selected-device state; the stranded marks are readable in the accessibility tree. No screen
  reader was used.
- **D7.** The first pass ran `capture.mjs reduced` and a computed-style census. The refuter reproduced
  it on its own build ("cameraPoses=1" against "cameraPoses=24") and extended the census to the legend,
  provenance dialog, hover and 390 px: 0 transitions over 10 ms.
- **D8.** The first pass used greyscale captures. The refuter made its own greyscale captures of 02, 03,
  06 and 08 in both themes and checked `classifyLink`'s double-encoding of cable state.
- **E1.** The first pass had actuation verified in 3 runs. The refuter re-ran the harness with the same
  actuation figures and watched J5's palette open and close under a MutationObserver in 6 of 6 reps.
- **F1.** The first pass ran `tsc` on the working tree and a fresh clone. The refuter re-ran all four
  `tsc` invocations and grepped for suppressions: none.
- **F4.** The first pass checked chunk structure and a red probe. The refuter rebuilt with identical
  chunk hashes and ran 21 narrow cold loads with no three.js request, and 10 of 10 wide loads with first
  paint before three.js.
- **F5.** The first pass showed byte-identical compiler output on the working tree and a fresh clone. The
  refuter recomputed the LF-normalised digest (`9580aa09…3089`, 3,072,771 bytes) against the raw CRLF
  digest (`9cc348bd…`), and ran `provenance.test.ts` (23 of 23).
- **F6.** The first pass reported "32 of 32 frames byte-identical across 5 runs". The refuter reported
  "32 of 32 frames byte-identical across 3 runs" on an unshared build, and traced every `Math.random` in
  the bundle to three.js paths the product never takes.

**PASS, unrefuted (not proven by attack):** D2. The first pass's key trace is detailed and the
`DataGrid.test.tsx` contract is green, but the refuter only read the code and ran no key trace.

## What is not

### FAIL

- **A1: configuration evidence for any finding.** Only 12 of 146 findings reach configuration
  evidence: 6 named and 6 matched. 133 land on "Browse <host>'s collected records (context, not this
  finding's evidence)", and F142 has no button. None of the 6 named findings reaches literal
  configuration text; all six land on a table of parsed fields. (The matched F106 does reach the literal
  line "permit tcp object-group MGMT_HOSTS any eq 22", per D1's keyboard walk.) This cannot be closed
  inside Atlas Scope: it needs per-finding record pointers from the producer (O12).
- **A4: selection from another surface is revealed in the queue.** With a filter active, a finding
  selected from the palette has no row, no mark and no mention in the queue or rail. Meanwhile the URL,
  status bar, scope bar, Inspector and fabric label all say it is selected. `PriorityQueue.tsx` about
  line 1459 records this symptom as an A4 defect, but its fix covers only collapsed groups, not a
  filter that hides the row.
- **A5: Reset view resets the camera.** A Reset pressed while the orbit is still coasting lands about
  64 px from home and stays there. The Home key drifts the same way. `camera.ts` `moveTo()` tweens
  position and target but leaves OrbitControls' damped delta, which `controls.update()` applies after
  the tween. The first pass tested only Reset after a double-click focus, when the camera had no
  momentum.
- **B6: every displayed claim resolves to a citation.** The Path surface's RIB-incompleteness claim
  is shown in four places with no citation button and no parenthesised citation. The citations exist in
  the model (`ribIncompleteness()` returns them, and `resolveCitation` gives `bearer`), but
  `ribIncompletenessSentence()` drops them. The caveat "No ACLs were collected for core2; filtering
  there is unobserved, not absent." is also shown uncited on that surface. The citations appear only
  after navigating to Device, then the Routing tab.
- **D1: every interactive control is reachable by keyboard.** The off-view finding pointer
  (`FabricLabels.tsx` about line 1066) has an `onClick`, `tabIndex -1` and an `aria-hidden` container,
  and no key handler. A 250-stop Tab walk never reached it. In dark theme it can also sit under the
  blast-radius HUD, where a click does nothing. The outcome it offers (framing the device) is reachable
  by keyboard another way, so a WCAG 2.1.1 functionality reading could pass. The criterion's wording,
  "every interactive control", does not.
- **D5: pointer targets ≥24×24.** The same pointer measures 141.23×16.84 CSS px in both themes and is a
  working click target. No exemption for it is declared anywhere. It sits on the canvas, itself a click
  target, so the spacing exception does not apply.
- **F2: `npx vitest run` green.** Green on the working tree (2,235 passed), but red on a fresh clone of
  the same commit: 12 timeouts, then 2 more in a targeted re-run, all at about 85% host load. The
  clone's result is the one the criterion asks for, and it is red. `composite-tabstop.test.tsx` (added
  in wave 5) is a new instance of the load-dependent timeout class, and `docs/open-issues.md` does not
  record it. `acceptance.md` F2 says "Timing is not asserted in the unit suite", which
  `layout.test.ts:953` contradicts (O26). Its "45 of 135" count is stale; the count is now 51 of 147. A
  quiet-host run of the clean clone is still owed.

### UNPROVEN

- **A2: multi-hop investigation.** Every reachable flow in the snapshot is 1 hop, and the depth ratchet
  asserts `toBe(1)`. The second hop's decider, hop-to-hop navigation, `resolveNextHost`'s cable-map
  branch, the TTL cut and the loop detector have never run on real data. This needs a snapshot with
  depth-2 flows (O34).
- **B8: nearest succeeding flow for a denied flow.** Of 10,374 traces, 0 qualifying neighbours exist,
  because `isDefiniteDelivery` is true for 0 traces. The positive state is covered only by fixture or
  `vi.mock` tests (`engine.counterfactual.test.ts`). This needs producer data (O13).
- **C1: blind critique by two independent critics per pairing.** No verdict record exists for any
  pairing. The reference captures give themselves away ("Forward AI", the Storylane modal). The only
  verdict figures, in `review/REFERENCES.md`, are withdrawn there as C1 evidence. Closing this needs an
  owner decision (O19).
- **E2: INP ≤200 ms.** The laboratory figures are 3–5× under the bar, but every run printed "NOT
  ACCEPTANCE EVIDENCE". The host was on battery for 13 polls over 60 minutes and every measurement.
- **E3: no task over 50 ms on the interaction path.** "0 run(s), need 3: INSUFFICIENT RUNS". The E3 axis
  also does not see a 51.7 ms LoAF that overlapped a first selection.
- **E4: ≥45 fps during camera motion and trace animation.** 60 fps in the laboratory, but
  "acceptanceEvidence=false". The trace-animation figure uses a synthetic trace, because no product
  flow animates a packet.
- **E5: no frame or keystroke over 200 ms during load.** A laboratory PASS with an 8 ms margin, and only
  3 of 9 long frames probed by a keystroke. It cannot overturn the recorded acceptance-grade FAIL at
  `70bea72` (O35).
- **F3: each engine refuted, with red before the fix.** 18 of 18 mutations KILLED. Real red-before-fix
  history exists for the claims engine and forwarding R17 only. Blast, layout, query and the compiler
  have no pre-fix history, because their guards predate the root commit `50a3dc5`. The compiler was
  refuted only for what it drops, not for fields it transforms. The `layout-nonfinite-option` mutation
  is killed only by an error-message mismatch.

## What was not examined

Collected from every auditor's and refuter's own statements.

**Environment and provenance**

- **No acceptance-grade E run.** The host was on battery throughout. Every E2–E5 figure, the first
  pass's and the refuter's, is laboratory data. The refuter's run also had Energy Saver on ("saver=On …
  charge=19%") at 30 Hz.
- **Fresh clone.** Groups A–E and F6 were not run from a fresh clone of `78bdba5` (O23). F1, F2, F4 and
  F5 were, and F2 was red there.
- **Contended hosts.** C ran at 100% `LoadPercentage` at the start, with 100–1,750 ms frame gaps. F ran at
  85–89% load from about 08:11, when other graders were active. F4(c) and the fresh-clone F2 run were
  both taken under load.
- **Shared Browser pane.** Another agent drove the shared "seed" tab during A and D. A's first census in
  that tab was discarded. After the first F099 walkthrough, A's evidence comes from an isolated headless
  Chromium. D moved to a separate tab and headless contexts.
- **Rendering path.** The headless and SwiftShader GL paths may differ from a headed GPU. Only one Intel
  iGPU was used for C5 and E4. No HiDPI motion was tested.
- **Servers.** Several refuters worked on the :4180 dev server because :4181 was down. B6 was graded
  on the dev server only.

**Group A**

- A1 was not re-run at other viewports or in the dark theme. The 2-click in-view route was not timed. F106
  and F107 literal-text reach was not checked by A (D1 shows F106 reaching it).
- A4:
  - The evidence-chain device chip was not driven in a browser.
  - The O37 `aria-current` lag was not measured.
  - Batch preservation across a device selection was not tested.
  - Hop selection under a filter was not tested.
- A5: hover was confirmed only by a data attribute and an underline, and no hover tooltip was found. The
  refuter did not visually check the hover underline or the trace marker.
- A6: the pixel-diff figures were not recomputed by the refuter.
- The project's own capture harnesses 01, 02 and 06 were not run for A.

**Group B**

- B1:
  - Not swept: 3-D canvas pixels, the Fabric accessibility-tree item names, the timeline, and the full
    Coverage tab tables.
  - The dark theme and narrow viewports were not swept, nor was hover-only tooltip text.
  - The grouped-queue band labels were not re-derived.
- The O36 compiler latent was confirmed by reading code, not by running the compiler on a mutated
  snapshot.
- The B6 Provenance tab sha was not checked for every citation.
- B7 was not checked with modals open (O32) or at 320 px by the first pass. The refuter covered 320 px.
- The full `npx vitest run` was not run by B.
- The historical red-before-fix for the B tests was not examined.

**Group C**

- Compact queue density was not graded (O17).
- C2–C4 were not checked at viewports other than 1920 and 1440, apart from the 72-state text detector
  covering 390 and 768.
- Not every one of the 32 frames was viewed individually. The refuter did not view dark/1920 01, 02, 07
  or 08.
- A caller's mid-motion `setQuality` was not exercised (O16), nor an organic adaptive step-down.
- The narrow-layout drawer's 240 ms slide was not triggered.
- C5: the refuter did not attack z-fighting, popping, AO, the cross-fade, the hairline, aliasing or
  banding.
- C6: runtime timings were not re-run by the refuter.
- The refuter could not re-run `capture.mjs`, because :4181 was down.

**Group D**

- No real screen reader (NVDA, JAWS or VoiceOver) was used, and Windows forced-colors mode was not tested.
- D2 was not walked on the "Cross-layer records" grid, and its refuter ran no key trace.
- D4 text was not measured at 1000 px by anyone. WebGL chassis, rim and link colours were not measured
  against the 3:1 non-text floor. Hover checks covered 8 control kinds, and active or pressed states were
  not measured. The pointer chip's own text contrast was not measured.
- D3's acceptance run was split into two invocations, the second narrowed with `--vp` (the harness labels
  that "not an acceptance run"). The refuter did not re-run the harness.
- D5 sub-cell exemptions were not click-verified cell by cell.
- D7's WebGL fades under reduced motion could not be resolved frame by frame, so that evidence is at
  source level.
- D8 greyscale was captured only at 1920 by the refuter, and at no 1440, 768 or 390 layout.

**Group E**

- No run with `ATLAS_FULLBLEED=1`, no headless FLOOR-lane run, and only one `audit-e5-coldload`
  invocation.
- The single-hop claim was not independently verified.
- J5 was not instrumented inside all 25 harness reps.
- The refuter did not re-measure E2–E5.

**Group F**

- No quiet-host run of the clean-clone suite.
- Test files were not read one by one; grep classes and the runtime zero-assertion guard were used
  instead.
- Pre-fix history was not attempted for blast, layout, query or the compiler (none exists). Forwarding R19
  and §1.2 were not checked against history.
- `review/*.mjs` is not type-checked (O27).
- F6 covers 1920 and 1440 only. The refuter used `twice 3`, not `twice 5`, and did no fresh-clone rebuild.

**Side effects recorded by graders**

- `capture-motion` rewrote the gitignored `review/shots/motion/`.
- The F grader's compiler re-run rewrote four JSON files with identical bytes, which changed their
  mtimes, so `build-freshness.mjs` reports :4181 "NOT FRESH" until the next `npm run build`.
- `measure-inp` added throttled records to `review/reports/inp-e3-history/`.

## Known issues carried forward

Reconciled against `docs/open-issues.md` (working-tree version).

**New; not yet recorded in `open-issues.md`**

1. **A4:** a filtered queue does not reveal a finding selected elsewhere. Evidence: `_ref_a4d.mjs`,
   `a4c-filtered.png`. Owner: the queue.
2. **A5:** Reset view and Home do not cancel the orbit damping tail. This promotes the O37 A5 lead to a
   confirmed FAIL at `78bdba5`. Owner: `camera.ts`.
3. **B6:** `ribIncompletenessSentence()` drops the citations `ribIncompleteness()` holds. The uncited
   core2 no-ACL caveat is shown on the Path surface. Owner: `src/forwarding/rib-completeness.ts` and the
   Path surface.
4. **D1 and D5:** the off-view pointer `.fabric3d-pointer` is keyboard-unreachable, `aria-hidden`, 16.84 px
   tall, and can be occluded by the HUD. Owners: `src/fabric3d/FabricLabels.tsx` and `Fabric3D.css`. The
   refuter also saw a pointer reading "off view" while access5's label was visible at the canvas edge, and
   right-rail text "degraded before cutover" drawn over the finding list (`ptr3-light-after.png`). These are
   leads.
5. **F2:** `composite-tabstop.test.tsx` joins the load-dependent timeout class; 12 timeouts on the fresh
   clone. `acceptance.md` F2's "45 of 135" is stale (51 of 147), and its "Timing is not asserted" is false
   while `layout.test.ts:953` stands (O26).
6. **B1 test quality:** `src/fabric3d/scene.test.ts:122` loops over collected null-band devices, and there
   are none, so its colour assertion never runs.
7. **O36 is wider than recorded:** `val()` also maps "-", "N/A" and NOT OBSERVED markers to null, so any of
   them would compile to "Info" at `tools/compile-snapshot.mjs:332` and `:350`.
8. **F3 documentation understates history:** `50a3dc5` holds the forwarding engine from before R17, and
   the red reproduces from it. `mutation-check.mjs`'s LIMIT line and `refutation.md` §7 ("attested in prose
   only") need correcting. O34's F3 status should cite this.
9. **E3 harness:** it judges by long task, not LoAF. A 51.7 ms frame overlapping J2-first was not counted.
10. **C2 observations:**
    - In the 06 and 08 captures, the 06 headline is scrolled 596 px out of view in its ~404 px scroll box.
    - Scroll ports cut a text line in half at their lower edge.
    - "claim strength" shows as a bare legend key with no value.
    - The 06 capture's manifest note says "BLOCKED verdict marker" while the frame shows "? UNDECIDED".
11. **D3 observation:** at 768×1024 in the path-flow state, the bottom edge of the ring on "What the
    collection gap means" is under the status bar (216 of 1,188 ring pixels).

**Existing items: status after this grading**

- **O12 (A1):** confirmed exactly at {6, 6, 133, 1}. Still not closable in Atlas Scope.
- **O13 (B8):** confirmed. UNPROVEN.
- **O34 (A2 and F3):** both confirmed UNPROVEN. See new item 8 for the F3 history correction.
- **O19 (C1):** confirmed. Owner decision.
- **O25 (E acceptance evidence):** still open. No on-AC run exists at `78bdba5`, because the host stayed
  on battery.
- **O35 (E5):** still open. A laboratory run at `78bdba5` measured a worst keystroke of 192 ms and first
  paint at 204–228 ms, which contradicts "still failing". It is not acceptance evidence, and a quiet
  on-AC re-run decides it.
- **O21 (E3 outside the journeys):** the sweep's worst action was "path trace: seed a flow by navigation"
  at 89.3 ms LoAF (laboratory). Resizes showed 0 ms.
- **O30 (J5):** E3-clean in 3 laboratory runs. Still a lead until a quiet run.
- **O23 (clean clone):** partly advanced. F1, F4 and F5 PASS from a fresh clone of `78bdba5`, and F2 is red
  there. A–E and F6 have still not been run from a clone. The structural `../webapp` dependency is
  unchanged.
- **O37:**
  - The A5 lead is now a FAIL (new item 2).
  - The D6 lead is confirmed (tree names carry no trace or stranded marks). It is not counted as a D6
    failure.
  - The B5 lead is addressed in grading by an isolated `evaluateAcls` check; the unit test itself is
    unchanged.
  - The A4 `aria-current` lag, idle rAF loops, E4 AO suspension, D3 status-bar overflow and palette-input
    boundary leads were not re-measured.
- **O36:** confirmed by code reading, and wider (new item 7).
- **O26:** still open (`layout.test.ts:953`).
- **O27:** still open. Its 17 review harnesses, including F-evidence tools, are not type-checked.
- **O22:** still open (the determinism gate is keyed on names and accepts unverifiable annotations).
- **O16:** a caller's mid-motion tier change is not exercised by the harness. Owner decision.
- **O17:** compact density was not graded. The C3 fragility finding bears on it.
- **O32:** not examined.
- **O9:** "Open source record" opens the compiled record. The Inspector says so in words, and the raw
  source record is still not viewable.
- **O6:** bloom halos at the high tier were noted by C5. Still open.
- **Not examined by this grading:** O7, O8, O11, O14, O28, O29, O31 and O33.
