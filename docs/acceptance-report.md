# Atlas Scope — Acceptance Report

Graded 2026-09-25 against `docs/acceptance.md`, at HEAD `8eac055` ("fix: close acceptance repair wave 6
(A4, A5, B6, D1, D3, D5, F2)"). Every grader found the same tree. `git status --short` showed only
` M docs/open-issues.md`, an uncommitted documentation edit. `git ls-files --others --exclude-standard`
printed nothing, so the build imports no untracked file.

Six first-pass graders covered groups A–F. Independent refuters then attacked every PASS verdict. Every
grader and every refuter returned. No group is marked "grader did not run", and no PASS is listed as
unrefuted.

**Where the first pass and the refutation disagree, this report applies the refutation.** Two PASS
verdicts were overturned to FAIL: **B6** and **D4**. Each overturn came with a reproducible proof: a
named script, its printed output, pixel samples or a screenshot, and a source line. I re-read both
cited source locations for this report, and they say what the refuters said they say
(`src/panels/PathTrace.tsx:926–940` and `src/app/App.css:259–277`). Neither overturn was set aside.
Every other PASS was attacked and upheld.

This report replaces the grade of `78bdba5` at this path. Figures from that grade appear here only where
they are labelled as history.

**Where each group was graded:**

| Group | Server and tree |
|---|---|
| A | The :4180 dev server, driven by the grader's own headless Playwright Chromium (ANGLE, 1920×1080). Other agents were driving the shared Browser pane at the same time. The grader's first A1 census attempt in that pane was abandoned when another agent reloaded and resized the tab. |
| B | The :4180 dev server. Engine and claims modules were imported in the page from the app's own module instances (see the method note under B8). |
| C | A scratch production build of `8eac055` served on :4191. Its `index.html` is byte-identical to the repository's `dist/index.html` (`cmp`: IDENTICAL). |
| D | The :4180 dev server. No release build or preview was measured. |
| E | `npm run build`, served by `npx vite preview --port 4181 --strictPort`, served build hash `8666bd0772acf8a5`. **The host was on AC for the whole session** (`Win32_Battery BatteryStatus=2`, saver=Disabled, supply=Adequate). |
| F | The working checkout, a private `vite preview` on :4197, and a sandbox holding the parent blob `1ed99404`. The F refuter re-ran F5 from a fresh `git clone` of `8eac055`. |
| Refuters | Mostly the :4180 dev server. The E refuter used a `vite preview` of the same build hash on :4181, and the F refuter used a scratch `vite preview`. |

**The tracked-sources gate is a precondition, not a criterion.** `src/core/tracked-sources.test.ts`
passed 9 of 9 in groups B, D, E and F. It also passed inside green multi-file runs in A (2 files, 21 of
21) and C (4 files, 125 tests). No group found an untracked or ignored build input under `src`,
`public`, the three HTML entry pages or `vite.config.ts`.

## Verdict

**Atlas Scope is not ready for acceptance at `8eac055`.** Five criteria FAIL:

- **A1:** configuration evidence is reachable for only 12 of 146 findings.
- **A4:** the first device pick throws the findings queue to the top when the only visible row naming
  that device sits in the bottom ~38 px of the queue. This is R39's defect, back in a narrower band.
- **B6:** the "Other questions this snapshot can answer" preset cards print 5 citations as inert text
  inside a run-this-flow button. Clicking one runs a different trace and never opens the Inspector.
- **B7:** at 390 px with the command palette open, none of the three coverage figures is visible.
- **D4:** the Queue/Evidence pane switch marks its selected option only with a fill of 1.17:1 (light) or
  1.20:1 (dark) and an ink shift of 2.52:1 or 2.2:1. Nothing distinguishing the selected option reaches
  3:1.

Four more are UNPROVEN, and UNPROVEN is not a pass:

- **A2** and **B8** need producer data that this snapshot does not have.
- **C1** needs an owner decision (O19).
- **F3** lacks red-before-fix history for four engines.

The other 30 criteria PASS, and every one of them survived an independent attack. This grade has three
real improvements on `78bdba5`:

- **Group E now has acceptance-grade evidence.** The runs are quiet and on AC, and every E criterion
  passes.
- **Every item wave 6 targeted now holds except B6 and A4.** A5, D1, D3, D5 and F2 all passed and were
  upheld under attack.
- **The engine's honesty held under large sweeps.** B1–B5 held against sweeps of up to 16,560 traces
  with zero counterexamples.

Two of this grade's five FAILs are in areas wave 6 declared closed. A4 and B6 each fail in a new shape of
the same defect class. B7 fails on a lead (O32) that had been deferred as an owner decision about B7's
scope. As written, "stated permanently and visibly" does not hold while the palette is open at phone
width.

## Scorecard

Refutation overturns applied: **B6 PASS→FAIL, D4 PASS→FAIL.** No other verdict changed.

| Criterion | Verdict | Evidence | Note |
|---|---|---|---|
| A1 | **FAIL** | Real-keystroke palette census of all 146 findings: `{"context":133,"named":6,"matched":6,"none":1}`, 0 URL mismatches. F001's pane reads "No configuration evidence route: the finding names no configuration line and nothing we hold matches its words". | The ≤3-step route works for the 12. F099 takes 3 interactions, and core1 projects to (474.446, 82.233) before and after, so the camera does not move. 133 findings reach context only, and F142 reaches nothing. Matches O12. |
| A2 | **UNPROVEN** | The trace renders "Hops (1)", "Hop 1 of 1: core1", with route and ACL citations. The depth ratchet `engine.test.ts:1051` asserts `toBe(1)`, and engine plus multihop tests pass 86/86. | Depth 1 is all the data reaches. The second hop's decider, hop navigation, the TTL cut and the loop detector never run on real data (O34). |
| A3 | PASS | "ACL PROTECT_SERVERS line 4 of 4", "on core1 denies this flow", `deny ip any any`, `acls.core1.PROTECT_SERVERS[3]`. Matches `fabric.json` index 3. | Upheld. The refuter found the INET_RETURN denial also named, the text legible at 1280×800, and exactly 2 denying lines across a 14,760-trace sweep. The verdict word is "? UNDECIDED" (0 decided denials exist). |
| A4 | **FAIL** | With F099 visible at row 999–1041 in grid 352–1054 (scrollTop 4777), one canvas click on access13 gave scrollTop **0** at +300 ms, +1.2 s and +4 s, with F099 now at y=5814. Repeated with access5 and F094: 4511 → 0. | The rail's new sentence "19 of 146 shown findings name access13 — marked on the row's trailing edge" moves the grid top from 352 to 389.7 *before* the `revealUnlessVisible` check runs. The other paths tested re-aim correctly: hop, link, queue, Device-pane finding and filtered palette. No test pins this, and the 6 A4–A6 files pass 181/181. |
| A5 | PASS | Hover: `data-hovering='true'`, label `data-state='hover'`. Select: `activeOutlines 1`. Focus moved access5 from (632,551) to (700,561). Reset: "error 0.00 px from home", including reset while coasting at 1, 3, 8 and 20 s, and under 10× CPU throttle. | R83 holds. Upheld on dist2. On real data the on-fabric trace is a single-node verdict marker, not a drawn path. |
| A6 | PASS | core1: "core1 strands 9 (uncertain; 0 under the all-nodes projection) · all 9 marked". Cut mark rgb(99,72,140) vs --state-down rgb(140,17,17). Snapshot disagreements are surfaced ("FAILURE_IMPACT.FHRP IS CONTRADICTED BY THIS DEVICE'S OWN RECORDS"). | Upheld, and made stronger. With the 3 uncollected devices correctly excluded, "0 of 210 non-partitioning pairs exceed the smallest cut-point pair". Stranded hosts keep their luminance while others dim. |
| B1 | PASS | Sweeps covered 156 device panes, 132 link panes and 146 findings. The only null hits are the literal `"uptime": null` inside the Raw JSON dump. Uncollected devices read "Health score: not observed", "port inventory is unknown rather than empty". | Upheld (AP-floor1, L34, `wave` null on all 146 findings). Latent and unreachable today: O36, and copied traces launder "not decided" (WeakMap side tables). |
| B2 | PASS | All 5 `suggestedFlows()` carry "Under the collected RIBs of core1 and core2 only (2 of 26 hosts in this topology)…" with 8–13 caveats. Sweeps of 16,560 and 11,988 traces: `noClaim=0, no2of26=0, noCaveats=0`. | Upheld: 14,760-trace matched sweep, `nBad=0`, and the intent-search verdicts carry the bound too. |
| B3 | PASS | `vitest` "Tests 90 passed", including "stops at the host whose forwarding table we do not hold". Live sweep: 0 non-indeterminate traces through a no-RIB host, `isDefiniteDelivery` 0. | Upheld. Only dist1 is reachable as a no-RIB hop on this data. |
| B4 | PASS | "✓ B4: a source in no observed subnet is out of scope and the claim says so in words". 6,120 out-of-scope traces, `oosNoWords=0 outsideNotOos=0`. | Upheld. 2,160 out-of-scope traces exactly equal the out-of-scope tally. |
| B5 | PASS | Unit tests against real core1 data. Removing `PROTECT_SERVERS[2]` in isolation flips the verdict to deny, decided by [3]. The claim reads "…cannot model ACL match qualifier(s): icmp_type (acls.core1.PROTECT_SERVERS[2])". | Upheld: 480-flow oracle sweep. The object-group branch is exercised only by a synthetic group. |
| B6 | **FAIL** (overturned) | First pass: 10 seeded cite clicks, 0 broken, source sha `9580aa09…3089` verified. Refuter, on the preset cards: `citeButtons 0` for `acls.core1.PROTECT_SERVERS[2]`, `l3_forwarding[5]` ×2 and `l3_forwarding[4]` ×2. Clicking the cite sentence gave "url after …flow=10.0.40.50%3E10.0.30.10%3Etcp%3E443…", "inspector open? no .inspector". | The cite strings sit in `span.pt-preset__why` and `span.pt-preset__prov` inside `button.pt-preset__btn`, which runs a flow (`PathTrace.tsx:937–939`). This is R81's inert-citation shape on a surface the grader never checked. Three cards also state verdicts with no citation control. |
| B7 | **FAIL** | At 390×844 with the palette open, `elementFromPoint` returns `palette__foot` over "23/26 collected" and "RIBs 2/26", and `palette__scope` over "ACLs 1/26". The palette footer says only "Searching 26 devices · 146 findings · 43 cross-layer · 135 interfaces · 50 endpoints". | Every other state probed passes. This was O32, recorded as an owner decision on B7's scope. As written ("permanently and visibly"), it fails. |
| B8 | **UNPROVEN** | The negative affordance renders: "…None of the 8 nearby variations … traced as a delivery with nothing on its path left undecided, so no counterexample is offered." Sweep of 11,988 traces: `counterexample().found = 0`, `isDefiniteDelivery = 0`. | The positive state exists only in a `vi.mock` fixture (O13). |
| C1 | **UNPROVEN** | `review/blind/KEY.json` has 12 entries, and none has a verdict, winner or critic field. 8 of 20 sheets are unkeyed. The "craft" sheet still shows "Forward AI" and a Storylane "Start" modal. | No blind verdicts exist, and the references are identifiable. Owner decision (O19). |
| C2 | PASS | `capture.mjs app`: 32 of 32 frames, exit 0. `capture.mjs text`: "PASS text 72 of 72 states free of clipped/broken text". Own sweep: 3 regex hits, all real data (e.g. "Undefined acl '7'"). | Upheld. Residuals: a scroll-port edge cuts a line in half (O17/O41), and path-form placeholders look like entered values. |
| C3 | PASS | At 1920, 10 of 10 rows unclamped. At 1440, 1 of 6 clamped: F002 loses one word ("a sole…"). | Graded at comfortable density only (O17). |
| C4 | PASS | 32 of 32 captures. Separately authored palettes in `tokens.css` (e.g. light `--sev-critical #8c1111` vs dark `#ff6b6b`). The canvas background is (13,17,23) dark and (241,244,248) light. | Upheld. |
| C5 | PASS | `capture-motion.mjs` exit 0 over 4 legs: z-fighting 0 clusters, sparkle 0–43 px vs 120 bar, popping "0 of 2604 still-pair pops", 24 of 24 tier fades at 266.6–266.8 ms. `probe-fabric.mjs --hairline`: 0 chains in all 4 legs. 0 pure-black pixels. | Upheld. The refuter re-ran the hairline detector at DSF 1 and found only the Legend button's border. One host (Intel iGPU). |
| C6 | PASS | Shipped CSS: 0 `@keyframes`, 13 transitions all ≤ `.24s`. Constants match §4.8 (`CAMERA_TWEEN_MS 620` exempt). Idle: 4 screenshots SHA-1-identical in 8 of 8 cases, `getAnimations()` empty. | Upheld. The packet-loop bound comes from code; no packet ever runs on this data. |
| D1 | PASS | `audit-d3-focus.mjs --sweep`: "3036 operable element(s) censused by behaviour (0 with no role and no tabindex) … 0 failure(s)." A1 and A2 walked keyboard-only at 1920, 768 and 390. The off-view pointer is a BUTTON "→◆ F094 access5 off view" (R84 holds). | Upheld: "3040 operable element(s) censused ... 0 failure(s)", plus an A1 walk at 768. |
| D2 | PASS | Key-by-key on both grids: Right/Left/Home/End, Ctrl+Home/End (r49, r152), PageDown r3→r11→…→r43, Shift+Space and Shift+Down "3 rows selected", aria-sort toggles. `DataGrid.test.tsx` 43/43. | Upheld by an independent ARIA-structure validator (rowcount 152, and 149 after a collapse). |
| D3 | PASS | "547 case(s), 0 failed." "1089 focus stop(s) checked for visibility, 0 not visible." `--self-removing`: "160 self-removing/BODY case(s), 0 failed." The palette trap is intentional, and Escape returns focus to the invoker. | Upheld. The D3 harness never sets a colour scheme. |
| D4 | **FAIL** (overturned) | First pass: text minimum 5.00:1 light and 5.05:1 dark, measured on 2,828 + 6,248 text runs. Refuter, on `.paneswitch__btn`: `"fillOnVsGround":1.17,"fillOnVsOff":1.17,"inkOnVsOff":2.52,"borderSameBothStates":true` (light) and `1.2 / 1.2 / 2.2` (dark), at 768 and 1000 px. | The selected-state indicator of a visible radio group is below 3:1 in both themes. `App.css:273–276` restates the same `border-strong` for the checked state. The first pass also disclosed a light-theme scroll-shadow residual of 3.92:1 on edge-clipped text. |
| D5 | PASS | Browser census over 15 states and 4 widths: the only elements under 24 px are `div.ag__cell` grid cells, whose row carries the action. The off-view pointer is 149.23×24. `target-size.test.ts` 12/12. | Upheld. `docs/target-size-exceptions.md`, cited by `design-brief.md:1453`, does not exist. The row-is-the-target argument is written nowhere. |
| D6 | PASS | `scene.pick()` at 3 px steps: 26 devices and 44 links, all found in the 119-item tree (`missingDev=[] missingLink=[]`). Enter on a tree item selects the device or link. | Upheld. Chromium AX tree only; no real screen reader was used. |
| D7 | PASS | "PASS  D7: camera lands in one frame under reduce, 23 poses without it." 0 transitions over 10 ms under reduce vs 325 in the control. The keyboard A1 route still completes. | Upheld on re-run. The packet half is fixture-only. |
| D8 | PASS | Greyscale captures of 03 and 06 in both themes: letter badges, band chips, "? UNDECIDED", hatch + "not observed", and a trailing bar with a count sentence. | Upheld. The refuter also checked states 02 and 08, the legend and forced-colors on state 06. |
| E1 | PASS | `grep 'id: "J'` in `measure-inp.mjs` finds exactly 7 ids, and they match acceptance.md. `journey-scope.test.ts` 14/14. J1–J4 "acts with a verified effect 25 of 25". | Upheld. J5 opened the palette in 75 of 75 reps. |
| E2 | PASS | 3 runs: "7 pass, 0 fail, 0 NOT MEASURED" and "ACCEPTANCE EVIDENCE: release build, hardware renderer, quiet host." Worst p95 48 ms (J4), and J2-first p95 64 ms over 21 of 21. | LABORATORY. Upheld across all 146 findings, 23 first-device selections and the native 1240×620 @1.5 viewport. |
| E3 | PASS | "E3 across runs of build 8666bd0772acf8a5 (3 run(s), need 3): PASS", ON-PATH 0 for every journey. An independent LoAF probe found 0 frames over 50 ms, and a 120 ms control handler read `[..,125]`, so the probe works. | LABORATORY. Upheld at 4 runs. One native-viewport J5 lead (52–85 ms) came from a run host-env refused as evidence and did not repeat in 2 valid runs. |
| E4 | PASS | "focus flights: PASS — median 60 fps across 10 windows, worst window 59.98 fps (floor 45) ... Orbit drag: PASS". Canvas 1.12 MPix, tier high, `acceptanceEvidence=true`. | LABORATORY, capped by the 60 Hz display. The refuter's 2.51 MPix stress run passed on median with single windows of 53.36 and 51.15 fps. Headroom is thin above 2 MPix. |
| E5 | PASS | Cold load ×2: "PASS E5 3 cold loads…", no frame over 200 ms, worst keystroke 160 ms. Sweep: "PASS E5 sweep all 13 actions stayed under 200 ms in every one of 3 repetitions". | LABORATORY, thin margin. The refuter's worst keystroke was 184 ms (native DPR, `?s=fabric&d=core1`). An F-group run printed "2 keystroke(s) over 200 ms (worst 224 ms)  [NOT ACCEPTANCE EVIDENCE]" because its build was flagged NOT FRESH. That run is not counted, but it is recorded. |
| F1 | PASS | All three `tsc` projects exit 0 with no output. The positive control printed "error TS2322: Type 'number \| undefined' is not assignable to type 'number'", exit 2. | Upheld. 0 `@ts-ignore`/`@ts-nocheck` in src or tools. `review/*.mjs` is excluded (O27). |
| F2 | PASS | "Test Files 153 passed (153) / Tests 3459 passed (3459)", exit 0, twice. The 10 mocking files match the declared list. | Upheld (3459/3459). Working checkout, not a clone of `8eac055`. Hollow or overclaiming tests: O38, and the `targets-cap` test name (116 of 145 cases make 1 assertion). |
| F3 | **UNPROVEN** | `mutation-check.mjs`: 21 of 21 mutations KILLED. Forwarding R17 is red from root `50a3dc5`: "Tests 5 failed \| 1 passed (6)". | "Failed before the fix" cannot be established for blast, layout, query or the compiler. Their guards predate the root commit (O34). |
| F4 | PASS | `npm run build` exit 0. The entry chunk names no three and no Fabric3D, and `index.html` has no modulepreload. "three.js requested at 825.2 ms, first paint 396 ms — after first paint". At 767 px: "three.js never requested". | Upheld across 40 cold loads at 8 widths. The 768 px boundary behaves as stated. |
| F5 | PASS | Compiler re-run: `fabric.json` sha256 `a1a599b8…d251` before and after. Sandbox outputs are byte-identical to `git show HEAD:` for all 4 files. Renaming core1→coreZ changes the output. | Upheld from a fresh `git clone` of `8eac055`: `git status --short` was empty after all 4 compilers ran. It still needs the parent blob `1ed99404`. |
| F6 | PASS | "verdict: F6 PASS: 32 of 32 frames byte-identical across 5 runs." Two further `app` runs gave "ALL PNG IDENTICAL", with 32 distinct hashes. | Upheld: `twice 3` plus a reversed-order run matched hash for hash. The O22 name-keyed gate stands. |

## What is proven

These 30 criteria were graded PASS and then survived a named, independent attack. The evidence that
established each one is listed here. Group E is **laboratory** evidence on one reference host.

**Investigation (A3, A5, A6).**
- **A3.** The blocked flow names its device, ACL, line and literal text: "ACL PROTECT_SERVERS line 4 of
  4 … on core1 denies this flow … deny ip any any … acls.core1.PROTECT_SERVERS[3]". That matches the
  compiled ACL. The refuter swept 14,760 traces and found only two denying lines on this snapshot,
  PROTECT_SERVERS[3] and INET_RETURN[2]. Both render with their cite, and every cite index matches the
  compiled text.
- **A5.** Hover, select, focus and reset all work on the fabric. Reset lands at "error 0.00 px from
  home", including mid-coast at 1, 3, 8 and 20 s and under 10× CPU throttle, so R83's fix holds.
- **A6.** Blast radius is drawn on the fabric and cross-checked against the snapshot's
  `failure_impact`, with contradictions surfaced in words. The refuter corrected the grader's own caveat:
  with the 3 uncollected devices excluded, "0 of 210 non-partitioning pairs exceed the smallest
  cut-point pair".

**Claim honesty (B1–B5).**
- **B1.** No null renders as healthy or zero. The sweep covered 156 device panes, 132 link panes and 146
  findings, and every `?? 0` site that reaches rendered text was checked and found unreachable or
  guarded.
- **B2.** Every verdict carries the "2 of 26 hosts" scope clause and a non-empty caveat list
  (`noClaim=0, no2of26=0, noCaveats=0` over 16,560 traces). The same holds on the palette, the live
  region, the preset card and the intent search.
- **B3.** A no-RIB hop is never delivered: 0 of 11,988 traces, and 0 of 672 dist1-crossing traces in the
  16,560 sweep.
- **B4.** An out-of-subnet source is out-of-scope, in words ("lies in no subnet this collection
  observed"): 6,120 and 2,160 traces with zero exceptions.
- **B5.** An unevaluable line is named and blocks the decision. The isolation control (remove
  PROTECT_SERVERS[2], and the verdict becomes deny by [3]) and a 480-flow oracle sweep confirm it.

**Craft (C2–C6).**
- **C2.** "PASS text 72 of 72 states free of clipped/broken text", and the grader's own regex sweep found
  only real data.
- **C3.** Titles survive at real density; at worst F002 loses one word.
- **C4.** Both themes are separately authored and complete.
- **C5.** Every cheap-render tell was checked: `capture-motion` passed on 4 legs, the hairline probe
  found 0 chains at DSF 2 (and again at DSF 1 in the attack), and 0 pure-black pixels were found.
- **C6.** No keyframes and no transition over .24 s ship. The idle frames are byte-identical and
  `getAnimations()` is empty.

**Accessibility (D1–D3, D5–D8).**
- **D1.** "3036 operable element(s) censused by behaviour … 0 failure(s)" (3040 on the refuter's
  re-run). A1 and A2 were completed keyboard-only at 1920, 768 and 390.
- **D2.** The APG grid contract was walked key by key on both grids, and the ARIA structure was
  independently validated.
- **D3.** "547 case(s), 0 failed", "1089 focus stop(s) … 0 not visible", and "160 self-removing/BODY
  case(s), 0 failed".
- **D5.** No control measures under 24 px. The only sub-24 boxes are grid cells whose row is the target.
- **D6.** Every canvas-pickable device and link (26 and 44) is in the DOM tree and selectable by
  keyboard.
- **D7.** "PASS  D7: camera lands in one frame under reduce, 23 poses without it", with 0 CSS
  transitions under reduce.
- **D8.** Every encoding carries a non-colour channel in greyscale, and on state 06 in forced-colors.

**Responsiveness (E1–E5). LABORATORY, on AC, quiet host, build `8666bd0772acf8a5`.**
- **E1.** The 7 journey ids are derived from the harness and match acceptance.md.
- **E2.** p95 is at most 48 ms per journey and 64 ms for J2-first, against a 200 ms bar. The refuter
  reproduced it across every finding, 23 first-device selections and the native viewport.
- **E3.** "E3 across runs … PASS" over 3 and then 4 runs. Independent LoAF probes with a working
  positive control found 0 frames over 50 ms.
- **E4.** Median 60 fps and worst window 59.98 fps while rendering at 1.12 MPix. The native 1.2 MPix
  viewport also passed.
- **E5.** No cold-load frame over 200 ms. The worst accepted keystroke was 160 ms (grader) and 184 ms
  (refuter). All 13 sweep actions stayed under 200 ms.

**Engineering integrity (F1, F2, F4, F5, F6).**
- **F1.** `tsc` is clean on all three projects, and a positive control shows the gate can go red.
- **F2.** 3459 of 3459 tests passed, twice, with no pending or todo tests.
- **F4.** three.js is split out of the entry and fetched only after first paint, at or above 768 px (40
  cold loads).
- **F5.** The compiled outputs are byte-reproducible **from a fresh clone of `8eac055`**, and the
  displayed digest is the source's. This closes O23 for F5 at this commit.
- **F6.** 32 of 32 frames are byte-identical across 5 runs, and again across a reversed-order run.

## What is not

### FAIL

**A1: configuration evidence for any finding.** The census recorded
`{"context":133,"named":6,"matched":6,"none":1}`. The 12 named or matched findings reach configuration in
3 interactions without moving the camera. The other 133 reach only "Browse <host>'s collected records
(context, not this finding's evidence)", and F142 is fleet-wide, so it has no record to open. The
criterion says "any finding". **Gap:** 134 of 146. This cannot be closed in Atlas Scope without
per-finding record pointers from the producer (O12).

**A4: re-aiming without losing scroll context.** With nothing selected and the queue scrolled so that
F099 is fully visible at the bottom (row 999–1041 in grid 352–1054, scrollTop 4777), one canvas click on
access13 left scrollTop at **0** at +300 ms, +1.2 s and +4 s. F099 ended up 5,800 px below the fold. The
access5/F094 repeat went from 4511 to 0. The control holds: with F099 centred (scrollTop 5094), the queue
stayed at 5094.

The cause is ordering. The count sentence "19 of 146 shown findings name access13 — marked on the row's
trailing edge" appears first and moves the grid's top edge from 352 to 389.7. The already-visible check
(`revealUnlessVisible` / `firstVisibleRow`, R39's fix) runs after that shift, finds the bottom row
partly hidden, and jumps to the first naming row.

**Gap:**
- The defect fires on the first device pick whenever the only visible naming row sits within about 38 px
  of the queue's bottom edge.
- No test pins it: `PriorityQueue.a4-scroll` and `PriorityQueue.test` are green.
- It is not recorded in `open-issues.md`, where R39 is marked FIXED.
- Untested: device-to-device switching, selection from the Fabric list, the palette and evidence-chain
  chips, and browser Back.

**B6: every displayed claim resolves to a citation (overturned from PASS; refutation applied).** The
first pass verified 10 seeded cite clicks, 0 broken, and the source sha. It never checked the preset
cards ("Other questions this snapshot can answer"), which are on screen in graded states 06 and 08.

`src/panels/PathTrace.tsx:937–939` renders `s.rationale` and `s.srcProvenance.note` as plain `<span>`s
inside `<button className="pt-preset__btn" onClick={() => onPick(s.flow)}>`. The refuter's `preset.mjs`
found `citeButtons 0` on cards carrying `acls.core1.PROTECT_SERVERS[2]`, `l3_forwarding[5]` (twice) and
`l3_forwarding[4]` (twice). Clicking the l3_forwarding[5] sentence printed:

```
url after …flow=10.0.40.50%3E10.0.30.10%3Etcp%3E443…
inspector open? no .inspector
```

**Gap:**
- 5 citations are inert text, the exact shape R81 fixed in `cited-text.tsx`.
- 3 of the 5 cards state verdict words ("denied by list text — not decided…", "indeterminate", "13
  caveats on its card") with no citation control.
- Secondary finding, not needed for the overturn: 97 model-resolvable cites also name source-snapshot
  records whose bodies differ from the model's projection. For example, source `routes.core1[6]`
  `{next_hop:"",out_intf:"Vlan30"}` is modelled as `{nextHop:null,…}`. The Inspector says the cite
  "resolves directly inside the compiled model" and never says that the cited source record differs.
  This bears on O9.
- Surfaces beyond Path were not swept for the same shape. Examples: the blast-radius stage button, the
  status-bar denominators, and DevicePane/EvidencePane prose.

**B7: coverage stated permanently and visibly.** At 390×844 with the Ctrl+K palette open,
`elementFromPoint` returns `palette__foot` over "23/26 collected" and "RIBs 2/26 …", and `palette__scope`
over "ACLs 1/26". The palette footer reads only "Searching 26 devices · 146 findings · 43 cross-layer ·
135 interfaces · 50 endpoints". Verdict rows repeat "2 of 26 hosts" for RIBs only.

**Gap:**
- In this state, collected-host and ACL coverage are stated nowhere on screen.
- Every other probed state passes. At 1600 px the scrim covers the figures, but they stay legible.
- This was O32, deferred as an owner decision on whether a modal is inside B7's scope. Graded against
  B7 as written, it fails. The owner may restate B7; until then it is a FAIL.
- Not probed: the keyboard-help dialog, which the `70bea72` re-grade saw fully covering the figures at
  320×568, and the list and legend popovers.

**D4: state indicators ≥ 3:1 in both themes (overturned from PASS; refutation applied).** The first pass
measured text thoroughly: minimum 5.00:1 light and 5.05:1 dark from DOM colours, plus glyph-pixel
measurement. Its non-text list did not include the Queue/Evidence pane switch (`.paneswitch__btn`,
`role=radio`), which is on screen at 768 and 1000 px. The refuter's `states.mjs` printed:

```
light 768 {"on":"Queue","off":"Evidence","cls":"paneswitch__btn","fillOnVsGround":1.17,"fillOnVsOff":1.17,"inkOnVsOff":2.52,"borderOnVsGround":3.85,"borderSameBothStates":true,"diffKeys":"backgroundColor,color"}
dark 768 {... "paneswitch__btn","fillOnVsGround":1.2,"fillOnVsOff":1.2,"inkOnVsOff":2.2,"borderSameBothStates":true,"diffKeys":"backgroundColor,color"}
```

The pixel samples agree: selected vs unselected is 1.17 in light and 1.2 in dark. `App.css:273–276` sets
`border-color: var(--border-strong)` for `[aria-checked="true"]`, the same value as the unchecked state.
The border is therefore present but carries no state.

**Gap:**
- No channel that marks the selected pane reaches 3:1 in either theme.
- The sibling widgets `.pq-corpus__btn` and `.railb__switch-btn` follow the project's own "filled ground
  AND a border" rule, and they pass.
- The first pass's own disclosed residual also stands, and a stricter reading could fail on it: the
  light-theme 4 px scroll shadow darkens edge-clipped text to 3.92:1 (5th percentile) and 3.62:1 on an
  Inspector key.

### UNPROVEN

**A2: hop-by-hop result.** Every reachable trace is 1 hop ("Hops (1)", "Hop 1 of 1: core1"). The depth
ratchet `engine.test.ts:1051` asserts `expect(Math.max(...depths.keys())).toBe(1)`. **Gap:** these never
run on real data:
- the second hop's decider;
- hop-to-hop navigation;
- `resolveNextHost`'s cable-map branch;
- the TTL cut;
- the loop detector.

`multihop.test.tsx` is a fixture and cannot be borrowed for the grade (O34). This is not closable in
code on this snapshot.

**B8: counterexample where one exists.** The negative state renders honestly ("…so no counterexample is
offered. That is not proof that none exists…"). Across 11,988 traces, `counterexample().found = 0` and
`isDefiniteDelivery = 0`: no decided delivery exists near any denial. **Gap:** the positive state
renders only under `vi.mock` in `engine.counterfactual.test.ts` (O13). It needs a snapshot with a
decided delivery.

Method warning for future graders: importing `claims.ts` without the app's `?t=` suffix splits the
WeakMap side tables across module copies. It manufactured 384, 216 and 918 false "decided" denials in
two separate sweeps.

**C1: blind critic panel.** `review/blind/KEY.json` records 0 verdicts: every entry has only `id,
sheetName, A, B, ours, reference, question, sheet`. 8 of 20 sheets are not keyed. The reference panel
on the craft sheet still shows "Forward AI" and a Storylane "Start" modal. `review/REFERENCES.md`
withdraws its own 32/36/36 head-to-head wins as C1 evidence. `review/blind/` is gitignored. **Gap:**
there are no blind verdicts, and the references cannot be made blind as captured. This is an owner
decision (O19): obtain clean references or restate C1.

**F3: regression tests that failed before the fix.** The reports half is present (`refutation.md`
§1–§7). `mutation-check.mjs` exited 0 with 21 of 21 KILLED, but it prints "(not pre-fix history — see
LIMIT above)". The grader reproduced forwarding R17's red from root `50a3dc5`: "Tests 5 failed | 1
passed (6)". One of the 5 reds is a TRANSIT control failing on wording. **Gap:**
- For blast, layout, query and the compiler, the guards predate the root commit, so "failed before the
  fix" cannot be shown from history.
- The `layout-nonfinite-option` mutation is killed only by an error-message mismatch.

## What was not examined

Collected from each grader's and refuter's own statements. Nothing below is a finding. Each item marks
where the evidence stops.

**Whole grade**
- Nothing except F5 was run from a fresh clone of `8eac055` (O23). A–D ran against the :4180 dev server
  or a scratch build of the working checkout. D measured nothing on the release build.
- Every measurement comes from one host and one session: Intel iGPU, ANGLE D3D11, and a 60 Hz display.
  Several agents shared that host, and the :4180 server fired HMR invalidations mid-session
  (`?t=1790339423998`) with no git-visible change.
- No real screen reader (NVDA or JAWS) was used. Forced-colors mode was checked only on state 06, by
  the F/D8 refuter. Touch and pointer-drag operation were not tested, and neither was 400% zoom.
- No grader ran a fresh blind panel for C1.

**A**
- A1 was checked only at 1920×1080 in the light theme. The "Browse" landings for the 133 were checked
  only for F001's wording.
- A4 device selection was not driven from the Fabric list, the palette or the evidence-chain chips. The
  bottom-band defect was measured only with nothing selected and at 1920×1080. Device-to-device
  switching and browser Back were not tested.
- A5 did not look for a hover tooltip or use the isolated `fabric-preview.html`. The refuter did not
  repeat the coasting or throttle runs.
- A6's diff metric is the grader's own, and link blast radius was first graded on L18 only (the refuter
  swept 11 links). The 9-host stranded set was not re-derived from the graph, and the cut-mark colours
  were checked on core1 only.
- A3: the refuter notes that `a3-blocked.png` is in the shared root `shots/`, not `gradeA0925/shots` as
  the evidence says. The refuter's own re-run reproduced it.
- The grader's abandoned first A1 attempt sent synthetic keys into a tab another agent was using, and
  may have disturbed that agent's run.

**B**
- The full vitest suite and `npm run build` were not run by B (F ran both).
- The dark theme was not checked for B1 or B7. Neither were the ShortcutHelp dialog and the list and
  legend popovers at narrow width.
- Null-band chassis colour was checked through `presentBand` and the "?" label, not by pixels.
- B3 could be exercised only on dist1.
- B5's object-group branch is exercised only by a synthetic group.
- B6 did not exercise non-`ui-cite` affordances, including the Raw tab's cable_map link, the
  CoverageBar table's cites and surfaces other than Path.
- The URL-restore path for B2 wording was not checked, nor "failed before the fix" history for any B
  test.
- The B1 refuter did not re-sweep all device and link panes or open palette rows for null-valued
  devices.

**C**
- Compact density was not graded.
- Viewports 390, 768 and 1024 were not graded for C2–C4, and no detector covers descender or
  scroll-port-edge clipping.
- No GPU other than the host's was used.
- The O16 mid-motion `setQuality` freeze and the organic step-down were not exercised.
- Interaction feel was checked against source constants, not measured.
- The C refuter viewed 5 of 32 frames, compared only states 04 and 06 across themes, and did not re-run
  `capture-motion`. The first run's AO dropped on a stationary frame, and light/low reset-fly had an
  800 ms frame gap at arrival. Both are sub-visible, and the harness passed them.
- `capture-motion` overwrote the gitignored `review/shots/motion/report.json`. The prior report is
  backed up in the scratchpad.

**D**
- Not measured: WebGL link and status-ring contrast, and contrast with a finding selected (the receded
  cables).
- The in-app theme toggle overriding the OS theme was not tested, and neither were the legend and
  fabric at 390 px.
- The O41 ring-under-status-bar lead was checked once at 768 and did not reproduce.
- The D refuter did not re-run the 33-minute and 23-minute D3 harnesses.
- The D grader changed the shared localStorage `atlas-scope.queue.corpus` and the legend flag, then
  restored them. The legend flag's prior value was not recorded.

**E**
- All E evidence is laboratory data: scripted Playwright input and a 60 Hz cap, so uncapped headroom is
  unmeasured. There is no field INP.
- Not tested:
  - dark-theme and reduced-motion journeys;
  - E4 at a render target over 1.2 MPix under the reference DPR;
  - a genuinely animating multi-hop trace, which is unreachable on this data.
- The refuter's J2-first scope probe could not hit 3 of the 26 devices from their labels, so those 3
  had no first-selection measurement of their own.
- The cold-load keystroke probes covered 5–6 of 8 post-paint blocking frames per invocation.
- O31 and O40 were covered only by the absence of their symptom and by an independent LoAF probe. The
  harness itself is unchanged.
- The refuter's `measure-inp` run appended a 4th record to `inp-e3-history`.

**F**
- The hollow-test search was mechanical: a per-test assertion counter. It does not catch
  constant-value pins.
- F4(c)'s "Show the 3-D fabric" at 767 px was not pressed by anyone.
- F3 history was re-checked for forwarding R17 only.
- `review/*.mjs` type errors (O27) and O29's scratch-script citations were not re-audited.
- F6 used 7 captures per frame from the grader and 4 from the refuter.

## Known issues carried forward

Reconciled against `docs/open-issues.md` (working-tree version; its Open section begins at line 2455).

**New; not yet recorded in `open-issues.md`**

1. **A4 bottom-band reveal (FAIL).**
   - Symptom: the first device pick scrolls the queue to 0 when the only visible naming row sits in the
     bottom ~38 px.
   - Cause: the count sentence shifts the grid *before* `revealUnlessVisible` checks visibility.
   - Evidence: `a4-r39-access13-F099-before.png` and `-after.png`, and `a4-r39-access5-F094-*.png`
     (grader scratchpad `gradeA0925/shots`).
   - This reopens R39's shape. Owner: the queue / DataGrid.
2. **B6 preset-card inert citations (FAIL).**
   - Symptom: 5 cites print as text inside `pt-preset__btn`, and 3 verdict words have no cite.
   - Evidence: `preset.mjs`, `preset-dist1.png`.
   - Owner: `src/panels/PathTrace.tsx`, which should route the rationale and provenance note through
     `cited-text.tsx`.
3. **D4 pane-switch state indicator (FAIL).**
   - Symptom: `.paneswitch__btn[aria-checked="true"]` differs only by a 1.17–1.20:1 fill and a 2.2–2.52:1
     ink shift.
   - Evidence: `states.mjs`, `seg.mjs` crops.
   - Owner: `src/app/App.css:259–277`, which should adopt the checked-only border used by `pq-corpus` and
     `railb__switch`.
4. **B6 secondary (bears on O9).** For 97 cites, the Inspector says "resolves directly inside the
   compiled model" while the cited source record differs from the model projection (e.g. `role:""`
   vs `role:null`, and `ports` dropped). Evidence: `both.js`, which printed "cites 723
   model-resolvable 97 also-in-source 97".
5. **B1 latent: copied traces launder "not decided".** `JSON.parse(JSON.stringify(t))`, `structuredClone`
   or a spread copy of a trace reads `decided=true, band REFUTED` where the original reads
   UNDETERMINED, because `isDecidedOutcome` reads WeakMaps keyed by object identity (`PARTIAL_ROUTE_BASIS`,
   `GAPS`). No shipped clone, worker or postMessage path reaches it today. Owner: `src/core/claims.ts`
   and `src/forwarding/engine.ts`.
6. **F2 test-name overclaim.** In `src/panels/EvidencePane.targets-cap.test.tsx:77` ("every access list is
   on screen…"), 116 of 145 cases make exactly 1 assertion, and the "on screen" half is vacuous for them.
   The composite-tabstop census (`composite-tabstop.test.tsx:465`) pins non-vacuity only for idle at
   1440 px.
7. **D5 documentation.** `docs/target-size-exceptions.md`, cited by `docs/design-brief.md:1453`, does not
   exist. The grid-cell "row is the target" argument is not written down as an exemption.
8. **D4 residual.** The light-theme 4 px scroll shadow (`rgba(0,0,0,.22)`) darkens edge-clipped text to
   3.92:1 (5th percentile) and 3.62:1 on an Inspector key.
9. **C2 observations.**
   - Path-form placeholders ("10.0.10.50", "10.0.30.10", "443") look like entered values; value is `''`.
   - The queue placeholder "severity:Critical" sits beside active Critical+High chips.
   - In state 06, the "Other questions" card's last line is cut in half at the scroll edge (the O17/O41
     family, now reproduced by eye).
10. **Thin E margins (laboratory, all PASS).**
    - The E5 worst accepted keystroke is 184 ms against a 200 ms bar (native DPR, `?s=fabric&d=core1`).
    - An F-group cold load printed "2 keystroke(s) over 200 ms (worst 224 ms)  [NOT ACCEPTANCE
      EVIDENCE]" on a build flagged NOT FRESH by an mtime artefact.
    - E4 windows reach 51–53 fps at 2.51 MPix.
    - A J5 on-path lead of 52–85 ms appeared in a native-viewport run that host-env refused (`fits=false`)
      and did not repeat in 2 valid runs.
11. **Harness notes.**
    - The D3 harness never sets a colour scheme.
    - `capture-motion`'s fixed output path overwrites the prior report.
    - The pick-based link-contrast scan is unreliable, because pick areas are wider than the strokes.
    - Graders must import engine and claims modules with the app's own `?t=` URLs (see B8).

**Existing items: status after this grading**

- **O12 (A1):** confirmed exactly at {6, 6, 133, 1}. Still not closable in Atlas Scope.
- **O13 (B8):** confirmed UNPROVEN, with 0 counterexamples found in 11,988 traces.
- **O19 (C1):** confirmed. Still an owner decision.
- **O32 (B7):** now graded **FAIL** at 390 px with the palette open. The owner decision on B7's scope
  stands. Until it is made, B7 fails as written.
- **O34 (A2 and F3):** both confirmed UNPROVEN. Forwarding R17's red was reproduced from `50a3dc5` ("Tests
  5 failed | 1 passed (6)"). Blast, layout, query and the compiler still have no pre-fix history.
- **O25 (E evidence):** its stated need, "quiet, on-AC runs at `8eac055`", **now exists**: 3 grader
  runs plus 1 refuter run of build `8666bd0772acf8a5`, all ACCEPTANCE EVIDENCE. The owner can close it.
- **O30 (J5):** not reproduced in quiet runs. J5 was E3-clean in 3 of 3 grader runs and 4 of 4 overall.
- **O35 (E5):** not reproduced at `8eac055`. The worst accepted keystrokes were 160, 144, 168 and 184 ms.
  The history of 240–464 ms FAILs and the non-evidence 224 ms run mean it is not proven gone. Keep it
  open, as a margin watch.
- **O21 (E3 outside the journeys):** "path trace: seed a flow by navigation" measured 97.8, 62.8 and
  74.3 ms (grader) and 76.8–78.4 ms (refuter). It is still the only sweep action over 50 ms.
- **O40 (long task vs LoAF):** the harness is unchanged. An independent LoAF probe found 0 frames over
  50 ms on J1–J5, with a working positive control.
- **O31:** the symptom was not reproduced (25 of 25 verified effects in every run). The code
  inconsistency stands.
- **O23 (clean clone):** advanced for F5. The F refuter ran all 4 compilers from a fresh clone of
  `8eac055`, and the tree stayed clean. A–E, F1–F4 and F6 have still not run from a clone of `8eac055`.
  The `../webapp` parent-blob dependency is unchanged.
- **O36:** confirmed latent. `tools/compile-snapshot.mjs:332/350` `?? "Info"` is not triggered: the source
  severities are Critical 3, High 104, Medium 33 and Low 6.
- **O38:** confirmed still hollow. `scene.test.ts:122` made exactly 1 assertion at run time.
- **O39:** confirmed. `mutation-check.mjs` still says "The only commit of this tree already contains every
  fix" against a 13-commit history. acceptance.md F2's "45 of 135" is now 51 of 153.
- **O22:** still open (FRAME_TIMING_OWNERS at `determinism.test.ts:282` is a name map). There is no failing
  case.
- **O27:** still open. `review/*.mjs` is in no type-checked project.
- **O16:** the mid-motion `setQuality` freeze was not exercised. Owner decision.
- **O17:** compact density was not graded. Scroll-edge clipping was seen again in state 06.
- **O41:** the D3 ring-under-status-bar lead did not reproduce at 768 (one check, not swept). The
  C2 scroll-edge lead was reproduced (new item 9). The pointer/label and rail-overlap leads were not
  examined.
- **O37:** the D6 lead stands: the tree carries no trace marks, and the refuter judged a marker not
  selectable. The idle rAF loop still ticks at about 70 frames/s with no pixel change (C6). The other
  leads were not re-measured.
- **O43:** R90's fix holds in the browser (D3: "9 of 9 hit points" on "Hide the legend"). It still has no
  unit pin. The `target-size.test.ts` limits are unchanged.
- **O9:** the Inspector still shows the compiled record for source cites and says so. New item 4 widens
  this to model-path cites.
- **O28:** the A1 census used real keystrokes with a 250 ms settle and recorded 0 URL mismatches. The race
  was not triggered.
- **R39, R81 (marked FIXED):** A4 and B6 now fail in new shapes of each (new items 1 and 2).
- **Not examined by this grading:** O6, O7, O8, O11, O14, O29, O33 and O42. On O42, no grader compared
  the 12 changed path frames against the local baseline.
