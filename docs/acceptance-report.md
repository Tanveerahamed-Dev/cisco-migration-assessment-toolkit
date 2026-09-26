# Atlas Scope — Acceptance Report

Graded 2026-09-26 against `docs/acceptance.md`, at HEAD `34bd435` ("fix: close the B6 citation-census
residuals without stating absence (B6)"). Every grader found the same tree. `git status --short` showed
only ` M docs/open-issues.md`, an uncommitted documentation edit. `git ls-files --others
--exclude-standard` printed nothing, so the build imports no untracked file.

Six first-pass graders covered groups A–F. Independent refuters then attacked every PASS verdict. Every
grader and every refuter returned. No group is marked "grader did not run", and no PASS is listed as
unrefuted.

**Where the first pass and the refutation disagree, this report applies the refutation.** One PASS
verdict was overturned to FAIL: **F4**. The overturn came with a reproducible proof: a named script
(`frac-headed.mjs`), its printed output, a control run, a screenshot and the source lines. I re-read the
cited source for this report and it says what the refuter said:

- `src/app/surfaces.tsx:128` has `stacked = useMediaQuery("(max-width: 47.9375rem)")`.
- `src/app/shell.css:458` opens `@media (min-width: 48rem)`.
- `src/app/App.tsx:217` seeds `useState(!ladder.stacked)`.

A viewport between 767.0 and 768.0 CSS px matches neither rule. The overturn was not set aside. Every
other PASS was attacked and upheld. Two refuters corrected a line of a grader's evidence without
changing the grade (B1 and D4, see the scorecard).

This report replaces the grade of `8eac055` at this path. Figures from that grade appear here only where
they are labelled as history.

**Where each group was graded:**

| Group | Server and tree |
|---|---|
| A | The :4180 dev server, 1920×1080 emulated viewport, light theme. Canvas pick, hover, focus and reset ran in the hardware-GPU Browser pane. The A6 pixel diff ran in headless Chromium on SwiftShader (tier low). |
| B | The :4180 dev server. Engine and claims modules were imported in the page through the app's own module URLs (`engine.ts?t=…`). |
| C | `npm run build` (exit 0) of the working checkout, stamped with `build-freshness --stamp` and served by `vite preview` on :4181. `capture-motion` reported "build fresh: true". |
| D | The :4180 dev server only. No release build or preview was measured. |
| E | `npm run build`, served by one `npx vite preview --port 4181 --strictPort`, served build hash `d67f4ef7a4b4530b`, "build: fresh" in every harness. **The host was on AC for the whole session** (`Win32_Battery BatteryStatus=2`, saver=Disabled, supply=Adequate, throttled=false). |
| F | The working checkout plus a fresh `git clone` of `34bd435` in the scratchpad (parent blob `1ed99404` at `../webapp`). F4 and F6 were measured on that clone's build, served by `vite preview` on :4191. |
| Refuters | A/B on the :4180 dev server and headless Chromium. C on the :4181 build. D on the :4180 dev server. E in a scratchpad mirror of the harnesses against :4181. F on a private `vite preview` of `dist/` on :4197 and in a `git archive` sandbox. |

**The tracked-sources gate is a precondition, not a criterion.** `src/core/tracked-sources.test.ts`
passed 9 of 9 in every group, alone (D) or inside green multi-file runs: A (8 files, 231 of 231), B (6
files, 113 of 113), C (2 files, 111 of 111), E (2 files, 23 of 23), and F (the full suite). No group
found an untracked or ignored build input under `src`, `tools`, `public`, the HTML entry pages or the
configs.

## Verdict

**Atlas Scope is not ready for acceptance at `34bd435`.** Five criteria FAIL:

- **A1:** configuration evidence is reachable for only 12 of 146 findings.
- **A4:** after a trace's hop selection, the queue's selected finding sits 187 px below the queue
  viewport and nothing brings it back. The trigger is switching to the Path surface after interactive
  selections.
- **C2:** the project's own text gate is red. `34bd435` reintroduced an unjustified `overflow-wrap:
  anywhere` on the prose `.palette__matched`.
- **D3:** at 390×844, Tab out of the "What the collection gap means for this result" popover puts focus
  on a grid cell that the status bar's coverage button covers completely (0 of 9 points visible). This
  is deterministic.
- **F4 (overturned from PASS):** at fractional viewport widths between 767 and 768 CSS px, which Windows
  display scaling produces, three.js loads on first paint with no reader action.

Four more are UNPROVEN, and UNPROVEN is not a pass:

- **A2** and **B8** need producer data that this snapshot does not have.
- **C1** needs an owner decision (O19).
- **F3** lacks red-before-fix history for blast, layout, query and the compiler.

The other 30 criteria PASS, and every one of them survived an independent attack. Measured against the
grade of `8eac055`:

- **Three of that grade's FAILs now hold.** B6 (wave 7, R92–R94), B7 (R96) and D4 (R97) all passed and
  were upheld under attack.
- **Group E now has acceptance-grade evidence at `34bd435`**, including E3 across runs and E4, which O25
  held open.
- **The engine's honesty held again under large sweeps.** B1–B5 held against sweeps of up to 4,536
  (grader) and 3,701 (refuter) traces with zero counterexamples.

Three of the five FAILs are new shapes in areas an earlier wave declared closed:

- **A4:** a surface switch, where R91 fixed a bottom-band pick.
- **C2:** a wrap licence reintroduced by the very commit under grade.
- **D3:** a fully hidden stop at 390, where O45 recorded "0 not visible".

F4 fails at a boundary that every earlier measurement probed only at an integer 767 px.

## Scorecard

Refutation overturn applied: **F4 PASS→FAIL.** No other verdict changed.

| Criterion | Verdict | Evidence | Note |
|---|---|---|---|
| A1 | **FAIL** | Census of all 146 findings (pushState+popstate per id, waiting for `.ev__id` to match): named 6 (F002, F136–F140), matched 6 (F099, F102, F106, F107, F109, F126), context 133, none 1 (F142: "this finding names no device, so it cannot be traced to one"). F099 reaches access13 Gi0/11 in 3 interactions, and core1 stays at (474.4, 82.2) before and after. | Criterion is "any finding": 134 of 146 have no configuration route. The grader's first census used a fixed 700 ms wait and read F139 stale; the re-measure shows it named. Matches O12. Not closable in Atlas Scope. |
| A2 | **UNPROVEN** | tcp 10.0.10.50→10.0.30.10:3389: `document.querySelectorAll('.hop').length === 1`, "Hop 1 of 1: core1", decider "ACL — THIS IS WHAT DECIDED THE HOP: PROTECT_SERVERS line 4 of 4". `engine.test.ts` 79/79, including the depth ratchet at `:1051` (`toBe(1)`). | The multi-hop half has never run on shipped data (O34). `multihop.test.tsx` (7/7) is a fixture. |
| A3 | PASS | "PROTECT_SERVERS line 4 of 4 / on core1 denies this flow / deny ip any any / acls.core1.PROTECT_SERVERS[3]", with the literal in `<code class="hop__raw">`. Matches `fabric.json` index 3. | Upheld. The refuter also rendered udp/53→8.8.8.8, denied by "INET_RETURN line 3 of 3". An 8×14×9 probe found only these two denying lines. No denial is DECIDED (all are UNDECIDED). |
| A4 | **FAIL** | Each of the four selection kinds re-aims correctly in isolation. Failing sequence (reproduced twice): queue at scrollTop 1000, orbit, click F026 → access5 → core1 → L33 → access5, then the Path surface button. scrollTop went 1000 → 1015, and the selected row F026 (`data-active`) sat at 1241–1297 in a queue viewport of 786–1054. The flow submit's hop-0 selection left it there, and so did a later double-click on dist1. | Arguably a surface switch is outside A4's four kinds. It is graded FAIL because the state is measured immediately after a hop selection. The same switch re-anchors the row after a URL load (1136 → 1399). No A4 test pins this path. Also recorded, not graded: a new trace submit moved the camera (core1 (474,82) → (552,237)). |
| A5 | PASS | Canvas click on access5 → `d=access5`. Hover over dist1: cursor "pointer", camera unmoved. Double-click dist1: core1 went from (495,260) to (64,-149). "Reset view" returned access5 to (632,551), the same after 2.5 s and 4 s. | Upheld. Refuter: Reset restores (632,551)/(474,82)/(736,444)/(590,113) exactly, unchanged 3 s later. On real data the on-fabric trace is a verdict marker ("core1 ? UNDECIDED"), not a drawn path. |
| A6 | PASS | "core1 strands 9 (uncertain; 0 under the all-nodes projection) · all 9 marked". Teal "⚠ CUT POINT". access9: "DISAGREEMENT: our computed blast radius for access9 (0 hosts stranded, at least 2 endpoints) differs from the snapshot's own failure_impact (30 endpoints across 2 VLANs)". Pixel diff: core1 vs access9 4.36 %, access9 vs access11 0.65 %. | Upheld and extended: across 9 devices, every articulation-vs-non-partition pair is 3.41–3.84 %, and every non-partition pair is 0.49–1.01 % (all 21 non-partition pairs). 17 qualitative disagreements are headed "The two measures disagree". |
| B1 | PASS | Sweeps covered 26 devices × 6 tabs and 190 finding and link panes. The only null hits are literal `"uptime": null` lines inside the Raw JSON dump. "interfaces: not observed — … its port inventory is unknown rather than empty". | Upheld. **Correction applied:** the grader's "link_centrality[0..24].pairs_cut is really 0" is false. 20 of 25 rows carry 22. The grade stands because `DevicePane.tsx:1980` renders `link.pairsCut` from the record, and the 0s shown are the 5 genuine zeros. |
| B2 | PASS | Sweep of 4,536 traces: `noScope=0, no2of26=0, noCaveats=0, claimNotStartScope=0`. The 5 preset cards carry 13/13/10/11/8 caveats and "Under the collected RIBs of core1 and core2 only (2 of 26 hosts in this topology)". | Upheld: 3,701-trace sweep including 127.0.0.1, 0.0.0.0, 224.0.0.5 and FHRP VIPs, `NOSCOPE=0, NO2of26=0, NOCAV=0`. |
| B3 | PASS | "Test Files 6 passed (6) / Tests 113 passed (113)". 1,152 traces through a no-RIB host: `throughNoRibDelivered=0, throughNoRibNotIndet=0`. The hop reads "dist1 · not modelled — undetermined". | Upheld: `DELIV-THRU-NORIB=0 NORIB-NOT-INDET=0` over 3,701. Only dist1 is reachable as a no-RIB hop on this data. |
| B4 | PASS | "✓ … each (source, flow) is out-of-scope, consults no device, and carries the 'lies in no subnet' sentence". 1,296 out-of-scope traces: `oosNoWords=0, offSubnetNotOos=0, oosButObserved=0`. | Upheld: 1,761 out-of-scope traces, `OFFSUB-NOT-OOS=0 OOS-NOWORDS=0`. |
| B5 | PASS | icmp hop `decidedBy` `acls.core1.PROTECT_SERVERS[2]`, "cannot model ACL match qualifier(s): icmp_type". Splicing [2] out flips the verdict to 'denied' by [3], and restoring it brings back indeterminate. Mutations `compiler-drops-unevaluable` and `compiler-drops-established` KILLED. | Upheld: 700-flow fuzz, 110 ACL-decided hops, "0 HIDDEN, 0 DECIDED-DESPITE, 0 UNNAMED". The object-group branch is synthetic-only. |
| B6 | PASS | 11 random cite clicks across 5 surfaces, 0 unresolved. Census with the app's `resolveCitation`: 726 distinct cites, "model 98, bearer 628, unresolved 0". Digest `9580aa09…3089` verified with `git cat-file blob … \| sha256sum`. | Upheld: for all 97 model-path cites, the resolved record's own `cite` equals the citation (0 mismatches). 755 traces: 0 genuinely unresolved. |
| B7 | PASS | Status bar: "coverage \| 23/26 collected \| RIBs 2/26 (both shown incomplete) \| ACLs 1/26 \| centrality 25/44 \| snapshot 9580aa09 2026-08-07". At 390×844, `elementFromPoint` hits `sb__cov`. With the palette open, `.ui-overlay-cov` restates the figures and is the top element. | Upheld at 320×640, with the More and Display popovers and after "Show the 3-D fabric". The figures match the source snapshot (23, 2, 1). R96 holds. |
| B8 | **UNPROVEN** | The negative state renders: "None of the 8 nearby variations derived from the evidence at core1 … traced as a delivery with nothing on its path left undecided, so no counterexample is offered. That is not proof that none exists". Sweep of 1,820 traces: `counterexample().found = 0`. | The positive state exists only under `vi.mock` (O13). |
| C1 | **UNPROVEN** | `review/blind/KEY.json`: 12 entries, and the only keys are `id, sheetName, A, B, ours, reference, question, sheet`. 8 of 20 sheet PNGs are unkeyed. The craft sheet's reference panel still shows "Forward AI" and a Storylane "Start" modal. The sheets are dated 2026-09-20 and 09-22, which predates waves 3–7. | No blind verdicts, fewer than 2 critics per pairing, and the references identify themselves. Owner decision (O19). |
| C2 | **FAIL** | `node review/capture.mjs text`: "PASS selftest 23 of 23 detector cases gave their known answer", then "BAD wrap licence without justification: src/app/CommandPalette.css:276 .palette__matched { overflow-wrap: anywhere }" and "FAIL text 72 of 72 states free of clipped/broken text ...; wrap licences UNJUSTIFIED", exit 3. | Introduced by `34bd435`: `git show ba7b456:src/app/CommandPalette.css` has 0 `overflow-wrap: anywhere`, HEAD has 1 (I re-counted both). `.palette__matched` can hold a raw `hit.field` identifier (`CommandPalette.tsx:329`). No visible split was found in any capture or probe. Not recorded in open-issues. |
| C3 | PASS | State 03, comfortable density: 1920×1080, 10 rows in view, 0 clamped. 1440×900, 6 in view, 1 clamped (F002 shows 39 of 46 characters, "VLAN 30: single-fiber uplink to a sole…"). | Upheld, but the evidence is narrower than the claim. Across the whole queue at 1440, 79 of 107 rows are clipped and 39 lose over 20 % (worst F141, 32 % hidden). Every clipped title keeps its subject and is under the harness's 50 % bar. |
| C4 | PASS | 32 of 32 frames in both themes. `tokens.css`: all 35 light colour tokens are overridden in dark, 0 identical (e.g. `--sev-critical #8c1111 / #ff6b6b`). Canvas mode colour (13,16,23) dark vs (241,244,248) light. | Upheld: 0 identical colour properties across all 8 states; WCAG text census 0 failures in 16 cases, and a 7:1 control flags 48 texts, so the probe was not blind. |
| C5 | PASS | Grader's full `capture-motion` run exited 3 on one fade stall ("opacity fell 0.5 in one frame (frame 40; bar 0.25)") under 93 % host CPU; all 12 copy-off control fades passed. Quiet 2-leg re-run: 24/24 fades at 266.6–266.8 ms. `probe-fabric.mjs --hairline`: "VERDICT: no sub-2 px hairline", exit 0. 0 pure-black pixels. | Upheld: the refuter's full 4-leg run exited 0 (tier-held 24 sequences, 0 z-fight clusters over 1218 steps, 0 pops over 2664 pairs, 8 AO restores, 24/24 fades 266.5–266.7 ms). Hardware hairline probe: 0 chains at DSF 2. The DSF 1 hits were the Legend button's border. |
| C6 | PASS | `motion-inventory.test.ts` + tracked-sources: 111 passed. Shipped CSS: 0 `@keyframes`, 13 transitions at 80/140/240 ms, collapsing to 1 ms under reduce. Idle: 5 screenshots over 5 s byte-identical, `getAnimations()` `[]` in 6 of 6 cases. | Upheld on all 8 states × 2 themes (1 distinct hash each). The 1600 ms packet loop cannot run on this data. |
| D1 | PASS | `audit-d3-focus.mjs`: "198 composite widget(s) counted, 2416 tab stop(s) walked, 2776 nine-point hit test(s), 3 More -> Path journey(s), 3048 operable element(s) censused by behaviour (0 with no role and no tabindex) ... 0 failure(s)." A1 and A2 walked keyboard-only at 1440. | Upheld (3046 on the refuter's run), plus A1 and A2 walked at 768 and 390. Every pointer drag has a keyboard equivalent. |
| D2 | PASS | Real keys: Right/Left/Home/End, Ctrl+Home/End (r1, r152), PageUp/PageDown in steps of 7, aria-sort cycling, group collapse (152 → 149 → 152), Shift+Space/Shift+Down "3 rows selected", Escape clears, Ctrl+A 146. Exactly one `tabindex=0` throughout. | Upheld: aria-rowindex 1..152 with no gaps, AX tree row 152 / gridcell 589 / rowheader 146, edge keys stay put. `DataGrid.test.tsx` and reduced-motion 51/51. |
| D3 | **FAIL** | Full run exited 1: "547 case(s), 0 failed ... 1089 focus stop(s) checked for visibility, 1 not visible". "FAIL phone/inspector (citation) popover 'What the collection gap means for this result' :: open → Tab → Escape -> NOT VISIBLE [popover after Tab] DIV.ag__cell 'core1CR-01: End-of-support keystone': elementFromPoint over its visible box [76,754,261,788]: 0/9 points on the element; the rest on BUTTON.sb__cov". | `--vp=390` reproduced it identically (1 of 289 not visible, exit 1). It is a separate, fully hidden stop, not O41's partly covered 768 ring. Return-to-invoker 547/547; the 1920 sweep had 0 failures. Dev server only. |
| D4 | PASS | Own rendered-pixel probe: 10 states × 4 widths × 2 themes. Light: 3107 runs, lowest median 4.60:1. Dark: 3108 runs, lowest median 4.71:1. Every on/off state pair outside a modal scrim has pixels changing by ≥3:1 (`.paneswitch__btn` max 5.67 light, 9.98 dark). | Upheld, with **a correction applied:** the grader's probe kept no on-fabric label (its `elementFromPoint` filter lands on the canvas for `pointer-events:none` labels: "kept by auditor's elementFromPoint filter=0"). The refuter measured 808 label runs, 0 below the floor (lowest 6.42), plus placeholders (5.70 / 5.05) and 2240 hover runs (0 real failures). |
| D5 | PASS | Harness: "3048 operable element(s) censused by behaviour (0 with no role and no tabindex)". Own census, 3738 measurements: the only sub-24 px boxes are `div.ag__cell` (row ≥ 32 px is the target) and treeitems while the tree is clipped away. | Upheld over 8 states × 6 widths, including resizers found by cursor: every sub-24 box is a 24 px control scrolled past a scrollable container's edge. |
| D6 | PASS | `scene.pick()` at 3 px steps: 26 devices and 44 links. Tree walk: 119 treeitems. `missingDev=[], missingLink=[], treeOnlyDev=[], treeOnlyLinks=[]`. Enter on L18 announced "Link L18 selected. core1 Gi1/0/24 to access1 Gi0/1 …". | Upheld. The AX tree exposes 31 treeitems, none ignored, with state in their names. Chromium AX tree only. |
| D7 | PASS | "PASS D7: camera lands in one frame under reduce, 23 poses without it." exit 0. 0 elements with a transition or animation over 10 ms under reduce vs 338 without. `reduced-motion.test.ts` 8/8. | Upheld ("24 poses without it"). The packet half is fixture-only. |
| D8 | PASS | Greyscale 03 and 06 at 1440, both themes: C/H/P/G* letter badges, dashed "? UNDECIDED", hatch + "not observed", "? not collected", dashed vs solid links. | Upheld on dark L18, light 08, dark 02 and the legend. Bridge vs port-channel rails differ by thickness and gap, not colour alone. |
| E1 | PASS | 7 journey ids at `measure-inp.mjs` lines 361–751, equal to acceptance.md (`journey-scope.test.ts`). J1–J4 "acts with a verified effect 25 of 25". J5 checked separately: "palette dialog opened 25 of 25 reps". | Upheld. |
| E2 | PASS | 3 runs, each "7 pass, 0 fail, 0 NOT MEASURED" and "ACCEPTANCE EVIDENCE: release build, hardware renderer, quiet host." worstPerRep p95: J1 32, J2 40/48/48, J3 32, J3b 32, J4 48, J5 32, J2-first 64 over 21/21. Positive control: "worstPerRep p95=144ms … max=160ms". | LABORATORY. Upheld: J2 64 ms on the refuter's run. All 7 passed at the reference machine's native 1266×658 @1.5 in a run host-env refused on a 2 px window check. |
| E3 | PASS | "E3 (no task over 50 ms on the interaction path): PASS — 7 clean, 0 violating". "E3 across runs of build d67f4ef7a4b4530b (3 run(s), need 3): PASS". Positive control: "E3-FAIL … longTasks>50ms=25 (max 128ms, ON-PATH 25 …)". | LABORATORY. Upheld at 4/4 runs. The refuter also measured first selection of the 3 "not collected" devices, including AP-floor1 (degree 17), "on-path task >50 ms in 0 of 15". |
| E4 | PASS | "PASS E4 focus flights: PASS — median 59.99 fps across 10 windows, worst window 59.98 fps (floor 45) … Orbit drag: PASS — orbit median 60 fps, worst window 59.99 fps". Canvas 1161×962 (1.12 MPix), tier high, `acceptanceEvidence=true`. Under 8× CPU throttle the status bar read "tier high / below frame-rate bar", then "tier balanced / reduced". | LABORATORY, capped at 60 Hz. Upheld at native 1266×658 @1.5 and at 1000×625 @1.92 (1.18 MPix). A 4.47 MPix stress case outside the declared target FAILED (see Known issues). |
| E5 | PASS | "PASS E5 3 cold loads: every animation frame over 200 ms coincided with a visible working affordance, and no keystroke exceeded 200 ms". Worst keystroke 168 ms. "PASS E5 sweep all 13 actions stayed under 200 ms in every one of 3 repetitions". The positive control went red. | LABORATORY, thin margin. Upheld: aimed keystrokes into the Fabric3D warm-up frame gave a worst of 184 ms over 19 more cold loads. 19 added sweep actions all stayed under 200 ms. |
| F1 | PASS | `tsc -p tsconfig.json`, `-p tsconfig.scripts.json --noImplicitAny` and `-p tsconfig.config.json`, all `--noEmit`, exit 0. `--listFiles` covers all 234 `.ts/.tsx` under src; the scripts project covers all 5 `tools/*.mjs`. The clean clone's `npm run build` exits 0. | Upheld: 0 `@ts-nocheck`/`@ts-ignore`/`@ts-expect-error`, no `as any` in non-test source. `review/*.mjs` is excluded (O27). |
| F2 | PASS | "Test Files 159 passed (159) / Tests 3699 passed (3699)", VITEST_EXIT=0. No skip, only or todo. The 10 mocking files match the declared list. Non-behavioural tests are all in declared classes (54 of 159 source/filesystem readers). | Upheld (3699/3699 again). The grader's latent vacuity (`band-qualification` `if (mesh === null) continue`) is not vacuous today: every banded device is `collected:true`. Working checkout, not a clone (O23). |
| F3 | **UNPROVEN** | `mutation-check.mjs` exit 0: 21 of 21 KILLED, "(not pre-fix history — see LIMIT above)". R17 reproduced from history: `50a3dc5` + the test gave "Tests 5 failed \| 1 passed (6)", and `254694b` gave "Tests 6 passed (6)". | `--history` shows blast, layout, query and compiler guards "in root (no pre-fix commit)" (O34). |
| F4 | **FAIL** (overturned) | First pass: entry names no three, `index.html` has no modulepreload, "three.js requested at 1816.4 ms, first paint 760 ms — after first paint", "F4 at 767 px … three.js never requested". Refuter: `dsf 1.5 window 781: {"innerWidth":767,"mediaWidth":"767.3490","dpr":1.5,"le767":false,"ge768":false,"lt768":true,"fabricAttr":"on","canvases":1,"showBtn":false}` then `985ms three-Dyx6ntnn.js`. | Parts (a) and (b) hold. Part (c) fails in the (767.0, 768.0) gap, where no ladder rung matches. Control at mediaWidth 766.0: `fabricAttr off`, `showBtn true`, no three request. The gap layout is also broken (controls overlap the first grid row, and the status bar is clipped). |
| F5 | PASS | `node tools/compile-snapshot.mjs` exit 0; `fabric.json` `a1a599b8…d251` before and after. All 4 compilers byte-identical from a fresh clone under `core.autocrlf=true`. Source "9580aa09…3089 (3072771 bytes)" equals the parent blob `1ed99404`. | Upheld: `git archive` sandbox under `TZ=Pacific/Kiritimati` gave cmp-identical outputs for all 4 files. |
| F6 | PASS | Clone preview :4191: two `app` runs, 0 of 32 PNGs differ. "verdict: F6 PASS: 32 of 32 frames byte-identical across 5 runs." TWICE_EXIT=0. | Upheld: `twice 3` on :4197, and `twice 2` on the :4180 dev server ("F6 PASS: 32 of 32 frames byte-identical across 2 runs"). This closes the dev-server gap R15 had carried. |

## What is proven

These 30 criteria were graded PASS and then survived a named, independent attack. The evidence that
established each one is listed here. Group E is **laboratory** evidence on one reference host.

**Investigation (A3, A5, A6).**
- **A3.** The blocked flow names device, list, line index and literal text ("PROTECT_SERVERS line 4 of
  4 … deny ip any any … acls.core1.PROTECT_SERVERS[3]"), cross-checked against `fabric.json`. The
  refuter found the only other denying line, INET_RETURN line 3 of 3, rendered the same way.
- **A5.** Hover does not move the camera, double-click focuses, and Reset returns to the exact fresh-load
  framing with no damping tail (R83 holds), measured by the scene's own projections.
- **A6.** Blast radius is marked on the fabric and cross-checked against `failure_impact`, and
  disagreements are surfaced in words. Every articulation-point pixel diff (3.41–4.36 %) exceeds every
  non-partition diff (0.49–1.20 %) across all 21 non-partition pairs.

**Claim honesty (B1–B7).**
- **B1.** No null renders as healthy or zero. This held across 26 devices × 6 tabs, 146 evidence chains
  and 44 cable tabs, plus a refuter's targeted sweep of null-bearing records. Every display-relevant
  `?? 0` was judged unreachable or guarded.
- **B2.** Every verdict carries the "2 of 26 hosts" scope clause and caveats: 0 exceptions over 4,536
  and 3,701 traces, and on the palette, preset cards and Path result.
- **B3.** A trace through a no-RIB host is never delivered (0 of 1,152, and 0 over 3,701).
- **B4.** An off-subnet source is out-of-scope in words (0 exceptions over 1,296 and 1,761).
- **B5.** An unevaluable line is named and blocks the decision. The isolation control and a 700-flow
  fuzz both confirm it, and two compiler mutations were KILLED.
- **B6.** Every cite resolves: 726 distinct cites with 0 unresolved, and for model paths the resolved
  record's own `cite` equals the citation. The wave-7 fixes (R92–R94) hold.
- **B7.** The coverage figures stay visible or are restated at 390 and 320 px, under the palette, the
  keyboard reference and the popovers (R96 holds).

**Craft (C3–C6).**
- **C3.** Titles survive at comfortable density; the worst in-view loss is one word (F002).
- **C4.** Both themes are separately authored, with 0 identical colour properties.
- **C5.** Every cheap-render tell was checked. The refuter's full 4-leg `capture-motion` run exited 0,
  and the hardware hairline probe found 0 chains.
- **C6.** No keyframes, no transition over 240 ms, and byte-identical idle frames across 16 state×theme
  cases.

**Accessibility (D1, D2, D4–D8).**
- **D1.** "3048 operable element(s) … 0 failure(s)". A1 and A2 completed keyboard-only at 1440, 768 and
  390.
- **D2.** The APG grid contract was walked key by key, and the ARIA structure was independently
  validated.
- **D4.** Rendered-pixel contrast: text lowest median 4.60:1 light and 4.71:1 dark. On-fabric labels
  lowest 6.42 (refuter). Selected-state pairs reach ≥3:1 (R97 holds).
- **D5.** No control measures under 24 px except grid cells whose row is the target and controls
  partly scrolled past a container edge.
- **D6.** Every canvas-pickable device and link (26 and 44) is in the DOM tree and keyboard-selectable.
- **D7.** "PASS D7: camera lands in one frame under reduce", with 0 transitions over 10 ms under reduce.
- **D8.** Every encoding keeps a non-colour channel in greyscale, across 7 checked states.

**Responsiveness (E1–E5). LABORATORY, on AC, quiet host, build `d67f4ef7a4b4530b`.**
- **E1.** The 7 journey ids match acceptance.md, and every act had a verified effect.
- **E2.** Every p95 is at most 64 ms against a 200 ms bar, with a positive control that reads 144 ms.
- **E3.** "STABLE PASS (4/4 measured runs clean)" for every journey, with a positive control that goes
  red.
- **E4.** Median 60 fps and worst window 59.98 fps at 1.12 MPix. Also held at the native 1.2 MPix and
  the 1.18 MPix full-bleed rung, and degradation is displayed, not silent.
- **E5.** No cold-load frame over 200 ms. Worst accepted keystroke 168 ms (grader) and 184 ms
  (refuter). All 13 sweep actions, and 19 more, stayed under 200 ms.

**Engineering integrity (F1, F2, F5, F6).**
- **F1.** All three `tsc` projects are clean and cover every source file.
- **F2.** 3699 of 3699 tests passed, twice, with no skips.
- **F5.** The compiled outputs are byte-reproducible from a fresh clone of `34bd435`, and in a
  different time zone.
- **F6.** 32 of 32 frames are byte-identical across 5 runs on the clone's build, and across 2 runs on
  the dev server.

## What is not

### FAIL

**A1: configuration evidence for any finding.** The census recorded named 6, matched 6, context 133,
none 1. F001 reads "No configuration evidence route: the finding names no configuration line and
nothing we hold matches its words...". F142 reads "this finding names no device, so it cannot be traced
to one". The 12 reach configuration in 3 interactions without a camera move or scroll. **Gap:** 134 of
146 findings have no configuration-evidence route. This cannot be closed in Atlas Scope without
per-finding record pointers from the producer (O12).

**A4: re-aiming without losing selection context.** Queue, device, link and hop selections each re-aim
correctly when measured alone. The grader then followed this sequence twice:

1. fresh load, queue at scrollTop 1000, orbit;
2. click F026, then access5, core1, L33 and access5 (F026 visible at 844–900 in viewport 389–1054);
3. click the Path surface button.

The queue viewport shrank to 786–1054 and scrollTop moved only 1000 → 1015. That left the selected row
F026 (`data-active`) at 1241–1297, off screen, with nothing visible marking F026 as selected.
Submitting the flow (a hop-0 selection, device becomes core1) left it at 1241–1297. A later
double-click on dist1 left it at 1205–1261 in 750–1054.

**Gap:**
- After a hop selection the selected finding is 187 px below the queue viewport, and nothing reveals
  it.
- The same switch re-anchors the row after a URL load (`?d=access5&f=F026&tab=ports`, 1136 → 1399), so
  the fault depends on how the state was reached.
- The grader notes one could argue a surface switch is outside A4's four kinds. It is graded FAIL
  because the measurement is taken immediately after a hop selection, which the criterion requires to
  leave the selected row in view.
- The A4 regression tests pass and do not pin this path.
- Not traced to a cause. Not checked at other viewports. Not recorded in `open-issues.md`, where R91 is
  marked FIXED.

**C2: no clipped, broken or placeholder text.** The project's gate is red:

```
PASS selftest 23 of 23 detector cases gave their known answer
BAD wrap licence without justification: src/app/CommandPalette.css:276 .palette__matched { overflow-wrap: anywhere }
FAIL text 72 of 72 states free of clipped/broken text ...; wrap licences UNJUSTIFIED
```

The run exited 3. `src/ui/primitives.css:41–70` names this licence on a prose block as the cause of the
earlier "(num_power_supplie / s)" identifier split and says "No prose block sets it any more".
`.palette__matched` is prose, and it prints the raw `hit.field` whenever `FIELD_WORDS` has no entry
(`CommandPalette.tsx:329`).

**Gap:**
- The regression was introduced by `34bd435`, the commit under grade. I re-counted it: `ba7b456` has 0
  occurrences and HEAD has 1.
- No visible split was found in any captured state or in live palette probes at 390, 768 and 1440 (18
  and 12 match-reason spans). The failure is the gate verdict plus a latent licence for identifiers to
  split mid-letter.
- The gate is failing and the regression is not recorded in `open-issues.md` (no entry names
  `palette__matched` or the wrap licence).
- Everything else in C2 is clean: "PASS capture app 32 of 32 frames rendered", and the detector found
  no clipping in any of the 72 states.

**D3: focus is always visible and returns to its invoker.** Full run, exit 1:

```
547 case(s), 0 failed ... 1089 focus stop(s) checked for visibility, 1 not visible
FAIL phone/inspector (citation) popover 'What the collection gap means for this result' :: open → Tab → Escape -> NOT VISIBLE [popover after Tab] DIV.ag__cell 'core1CR-01: End-of-support keystone': elementFromPoint over its visible box [76,754,261,788]: 0/9 points on the element; the rest on BUTTON.sb__cov
```

`--vp=390` reproduced it with the same box and 0 of 9 points, "1 of 289 stops not visible", exit 1.

**Gap:**
- At 390×844 a focused grid cell is completely covered by the sticky status bar's coverage button
  (WCAG 2.4.7 / 2.4.11).
- This is not O41's partly covered ring at 768 (216 of 1,188 ring pixels). It is a separate, fully
  hidden stop.
- It contradicts O45's recorded W7-B7 390 run ("289 focus stop(s) … 0 not visible").
- Measured on the dev server only. Not checked on a preview build.

**F4: three.js is not requested before the reader asks for the fabric below 768 px (overturned from
PASS; refutation applied).** The first pass verified (a) and (b) and measured (c) only at integer 767
and at 1920. The refuter loaded the built app in headed Chromium with `--force-device-scale-factor=1.5
--window-size=781,900`:

```
dsf 1.5 window 781: {"innerWidth":767,"mediaWidth":"767.3490","dpr":1.5,"le767":false,"ge768":false,"lt768":true,"fabricAttr":"on","canvases":1,"showBtn":false}
119ms index-ZyHImrb3.js … 190ms mount-1IRE6Asy.js … 985ms Fabric3D-UGqUC_sq.js / 985ms three-Dyx6ntnn.js / 992ms Fabric3D-4_JDHqSR.css
```

`dsf 1.75 window 780` (mediaWidth 767.44) behaved the same, with three requested at 1236 ms. The
control, `dsf 1.5 window 780` at mediaWidth 766.0, gave `le767 true`, `fabricAttr off`, `showBtn true`
and no three request.

**Gap:**
- The JS ladder's `stacked` rule `(max-width: 47.9375rem)` and the CSS `(min-width: 48rem)` rungs leave
  (767.0, 768.0) unmatched. There `stacked` is false, the fabric is seeded visible, and three.js is
  fetched on load with no "Show the 3-D fabric" control.
- The same gap puts the layout in no rung. The Finding/Device controls overlap the first grid row, and
  the status bar is clipped (screenshot `headed-1.5-781.png`).
- This is reachable on Windows displays at 125/150/175 % scaling. Every earlier F4 measurement,
  including `audit-e5-coldload.mjs`, probed only integer widths.
- Not tested on a physical scaled display or in another browser.

### UNPROVEN

**A2: hop-by-hop result.** Every reachable trace is 1 hop (`.hop` count 1, "Hop 1 of 1: core1"), and
`engine.test.ts:1051` ratchets max depth `toBe(1)`. **Gap:** none of these has run on shipped data: the
second hop's decider, hop-to-hop navigation, `resolveNextHost`'s cable-map branch, the TTL cut and the
loop detector. `multihop.test.tsx` is a fixture. Closing this needs a snapshot with depth-2 flows (O34).

**B8: counterexample where one exists.** The negative state renders honestly. Across 1,820 traces
(462 denied or dropped), `counterexample().found = 0` and `isDefiniteDelivery = 0`. **Gap:** the positive
state renders only under `vi.mock('./rib-completeness')` and `vi.mock('./bindings')`. It needs producer
data with a decided nearby delivery (O13).

**C1: blind critic panel.** No blind verdict is recorded anywhere in the tree, and there are fewer than 2
critics per pairing. `review/REFERENCES.md` withdraws its own aggregate wins because "in every verdict
the critic's loser was the REFERENCE panel". The reference captures identify themselves, and the
sheets predate waves 3–7. **Gap:** a valid blind panel is not possible against these references. This
is an owner decision (O19).

**F3: regression tests that failed before the fix.** Reports (`refutation.md` §1–§7) and 21 of 21
KILLED mutations are present. Red-before-fix history exists for forwarding R17 (reproduced from
`50a3dc5`), claims C1/C2/C3 and O15. **Gap:** blast, layout, query and the compiler, and forwarding's
§1.1 and R19, have no pre-fix commit. For them "failed before the fix" can be shown only on today's code
with the guard reverted, which is not history (O34).

## What was not examined

Collected from each grader's and refuter's own statements. Nothing below is a finding. Each item marks
where the evidence stops.

**Whole grade**
- Nothing in A–E ran from a clone of `34bd435`. F ran F1 (through `npm run build`: `tsconfig.json` and
  `tsconfig.config.json`, not the scripts project), F4, F5 and F6 from a clone. F2's vitest did not run
  from a clone (O23).
- One host, one session: Intel iGPU, ANGLE D3D11, a 60 Hz display. Several agents shared that host.
  Graders reported load from each other (93 % CPU during one C5 leg, 53 % during one F cold load).
- No real screen reader (NVDA, JAWS or VoiceOver) was used. Forced-colors mode was not checked. No
  fresh blind panel was run.
- The dev server (:4180) was graded for A, B and D. The grader for A saw a tab reload of unknown cause.
  The grader for B saw an HMR recompile at 02:19 that left two module instances of `Inspector.tsx` and
  `DevicePane.tsx` in the open page. Until a fresh navigation, Device-pane cite clicks appeared to "do
  nothing" (dev-server only).
- The grader for A sent one navigate to another grader's tab (tab-8), and the grader for B navigated a
  tab it had not created (tab-9). Either may have disturbed another grader's state. A refuter wrote
  a probe config into a shared scratchpad directory before moving its work.

**A**
- No production build or `vite preview`. A1 was not verified at 390, 768 or 1440.
- The A4 failing sequence was not re-checked at other viewports, and its cause was not traced.
- The A6 pixel diff ran on SwiftShader at tier low, light theme, 1920×1080 only (grader and refuter).
- A5 hover was verified by cursor and camera invariance only; the hover rim was not measured.
- A3's capture note in `review/capture.mjs` still says "BLOCKED verdict marker on core1" while the frame
  shows "? UNDECIDED". The note is stale; it does not affect the criterion.

**B**
- Dark theme for B1 and B7. The production build. The 3-D canvas pixels for B1 (the tab was hidden;
  `scene.test.ts`'s null-band test was relied on).
- B3 on any no-RIB host other than dist1, and B5's object-group branch on real data. Neither is
  reachable on this snapshot.
- B2 on the timeline and the live-region announcement. URL-restore wording.
- Only 6 of the 21 mutations were run by B. The refuter sampled B1 over 8 states and did not re-sweep all
  146 evidence chains, all 44 cable tabs, the Cross-layer tab or the palette. The refuter did not repeat
  the B6 click-through and did not look for displayed claims on non-Path surfaces that carry no cite
  button. B7 was not checked under browser zoom or text scaling.
- B3: physically traversed L2 switches are not treated as traversed hosts. The refuter judged this
  within the criterion's L3 meaning and the "L2 forwarding … not simulated" caveat.

**C**
- No fresh blind panel (C1).
- C2–C4 at compact density, and at 390, 768 and 1024 pixel by pixel (only the text detector and a word
  sweep at 390 covered those). No detector for descender clipping (O17). C3's one-line mode.
- C5: a caller's mid-motion `setQuality` and an organic step-down (O16). One GPU. The refuter did not
  re-review banding, lighting or aliasing stills by eye. The dolly sequences move the camera in only
  5–7 discrete frames. Light-theme fades report composite share 41.1, which the harness does not judge.
- C6's packet loop never runs on this data. AO restore and history blend were judged only through C5.
- C's runs rebuilt `dist/` and overwrote the gitignored `review/shots/motion/report.json`. Backups are
  in the scratchpad `cgroup/`.

**D**
- The preview/release build on :4181. Whether the D3 failure occurs there.
- Text drawn inside the WebGL canvas itself. Forced-colors mode. Widths other than 390/768/1000/1440 for
  D4/D5 (1920 only through the D3 harness).
- D8 frames beyond 03, 06 and the refuter's four extra states.
- The D3 harness's later surface passes: the refuter's 1500 s timeout cut them off after the SWEEP line.
  The grader's first full run crashed with "Execution context was destroyed".
- D1 walks at 1000 and 1920.

**E**
- All E evidence is laboratory: scripted input, one machine, 60 Hz cap, no field INP. Frame-rate
  headroom above 60 fps is unmeasured.
- INP at 390, 768 and 1280 and in the dark theme. A second machine. Displays at 50 Hz or over remote
  desktop.
- `measure-fps` was one invocation (10+8 windows), not repeated across invocations.
- O31 was not examined in code. O40 was checked only for J2-first. The `review/*.mjs` harnesses remain
  outside type-checking (O27), and were audited only through their positive controls.
- The E runs overwrote `review/reports/inp.json`, `fps.json`, `e5-coldload.json` and `e5-sweep.json`
  and added 4 `inp-e3-history` records for build `d67f4ef7a4b4530b` (3 grader, 1 refuter).

**F**
- About 20 of 159 test files were read; the rest were checked by grep. Hollow tests outside the declared
  classes were only sampled.
- `fabric-preview.html` and `window.__atlasScene` were not checked for shader-compile or console errors.
- Historical red was reproduced only for R17. The claims and O15 history comes from `mutation-check
  --history`.
- The F4 refuter used the existing `dist/`, whose chunk names match the clone build, and did not rerun
  the cold-load harness.
- F6 samples: 5+2 on the clone build, 3 on :4197 and 2 on :4180, all through the harness's fixed frame
  list at its fixed DPR, CPU raster.
- The grader's F4 cold-load run exited 1 on its own E5 verdict ("[NOT ACCEPTANCE EVIDENCE]", host 53 %
  busy). The F4(c) ordering held in 3 of 3 of those loads.

## Known issues carried forward

Reconciled against `docs/open-issues.md` (working-tree version, uncommitted; its Open section begins
at line 2832).

**New; not yet recorded in `open-issues.md`**

1. **A4 surface-switch reveal (FAIL).**
   - Symptom: after interactive selections, switching to the Path surface shrinks the queue viewport
     (389–1054 → 786–1054) while scrollTop moves only 1000 → 1015. The selected row F026 ends at
     1241–1297, and the trace's hop selection does not reveal it.
   - Contrast: after a URL load the same switch re-anchors the row (1136 → 1399).
   - Evidence: the grader for A, reproduced twice at 1920×1080.
   - This reopens the A4 class that R91 marked FIXED. Owner: the queue / DataGrid and the surface
     switch.
2. **C2 wrap licence regression (FAIL).** `src/app/CommandPalette.css:276` `.palette__matched {
   overflow-wrap: anywhere }`, introduced by `34bd435` (R94's palette change), contradicting
   `src/ui/primitives.css:41–70`. `capture.mjs text` exits 3. The fix is a space-only break rule, or a
   justification per primitives.css. Owner: `CommandPalette.css`.
3. **D3 fully hidden stop at 390 (FAIL).** In phone/inspector (citation), the popover "What the
   collection gap means for this result" → Tab lands on `DIV.ag__cell` at [76,754,261,788], covered by
   `BUTTON.sb__cov` (0/9 points). Deterministic across two runs. It contradicts O45's "0 not visible"
   note for 390. Owner: the status bar and R72's scroll padding (the O41 family, but a full hide).
4. **F4 fractional-width gap (FAIL).**
   - Cause: `surfaces.tsx:128` `(max-width: 47.9375rem)` and the CSS `(min-width: 48rem)` rungs
     (`shell.css:458`) leave (767.0, 768.0) unmatched.
   - Effect: `App.tsx:217` seeds the fabric visible and three.js loads at 985 ms with no reader action,
     and the layout is in no rung (overlapping controls, clipped status bar).
   - Evidence: `frac-headed.mjs` and `headed-1.5-781.png` (refuter scratchpad).
   - Owner: the ladder (`useLadder`) and every stylesheet using the pair. A structural fix is to derive
     one rule as the complement of the other rather than adding another width.
5. **E4 stress beyond the declared target (lead, not graded).**
   - Result: at 1920×1080 viewport, DSF 2, dark theme (buffer 2322×1924, 4.47 MPix): "focus flights
     median 53.33 fps ... Orbit drag: FAIL — orbit median 46.24 fps (worst window 42.58 fps)". Host-env
     judged the host fit.
   - The scene reported `belowBar true`, but the tier stayed `high` although the worst window was below
     the 45 fps step-down floor.
   - Not an overturn: acceptance.md's restated E4 fixes DPR 1, and the reference panel cannot produce
     that canvas. It shows that an external HiDPI monitor on the reference machine would fall below the
     bar. Owner: `stepdown.ts` and the E4 owner.
6. **E harness: J2 anchor discovery cannot aim at the 3 "not collected" devices.** The "? not collected"
   text widens the label, so the aim misses by about 46 px ("NOT MEASURED ... only 9 of 25 trials",
   AP-floor1 0 of 0). With the aim shifted by dx −46, all three were E3-clean. AP-floor1 has the highest
   link degree (17). The last grade recorded the symptom; this is the cause. Owner:
   `review/measure-inp.mjs`.
7. **Latent B6 and B5 observations (no instance on shipped data).**
   - `blast.ts`'s fallback cites `cable_map.cables[id=…]`, which would not resolve because
     `fabric.cable_map` has only `nodes`, and a null cite for an absent link.
   - The engine ignores the compiled `unevaluable: true` on `MGMT_IN[0]` and resolves the group itself.
   - Owners: `blast.ts` and `engine.ts`.
8. **F2 latent branch.** `band-qualification.surfaces.test.tsx`'s `if (mesh === null) continue` would
   skip a qualified host in a chassis group with no collected device. The refuter showed no current
   qualified host reaches it; only `toBeDefined()` guards it. Owner: that test.
9. **Grading-method notes.**
   - The D4 grader's contrast probe filters by `elementFromPoint` and so measures no
     `pointer-events:none` fabric label.
   - The grader for B's statement "link_centrality[0..24].pairs_cut is really 0" is wrong (20 of 25
     rows carry 22).
   - The dev server's HMR can split `Inspector.tsx` and `DevicePane.tsx` into two module instances during
     a data recompile, so cites appear dead until a fresh navigation.
   - Fixed waits in the A1 census read stale panes (F139 at 700 ms).
10. **C3 depth.** Across the whole queue at 1440 × state 03, 79 of 107 titles are clipped and 39 lose over
    20 % (F141 32 %, F082 25 %) in a 122 px title column. This is within the bar, and every title keeps
    its subject. Owner: the queue layout (the O17 family).

**Existing items: status after this grading**

- **O12 (A1):** confirmed exactly: named 6, matched 6, context 133, none 1. Still not closable in Atlas
  Scope.
- **O34 (A2 and F3):** both confirmed UNPROVEN. R17's red was reproduced from `50a3dc5` ("Tests 5 failed
  | 1 passed (6)") and its green from `254694b` ("Tests 6 passed (6)").
- **O13 (B8):** confirmed UNPROVEN: 0 counterexamples in 1,820 traces.
- **O19 (C1):** confirmed unchanged. Owner decision.
- **O25 (E evidence):** its open need at `34bd435`, E3 across runs and E4, **now exists**. "E3 across
  runs of build d67f4ef7a4b4530b … PASS", STABLE PASS at 4/4, and `measure-fps` exit 0 with
  `acceptanceEvidence=true`. The owner can close it.
- **O30 (J5):** E3-clean in 3 of 3 quiet grader runs at `34bd435` (4 of 4 with the refuter). The
  grader reports this settles O30.
- **O35 (E5):** not reproduced. Worst accepted keystrokes were 168 ms (grader) and 184 ms (refuter,
  aimed into the warm-up frame). Keep it open as a margin watch.
- **O21 (E3 outside the journeys):** "path trace: seed a flow by navigation" measured 98.1, 65.9 and
  74.4 ms (grader) and 73–87.5 ms (refuter). It is still the only sweep action over 50 ms. The Path
  surface click reached 61.5 ms in the refuter's added actions (an E5 subject).
- **O40 (long task vs LoAF):** J2-first now reports the worst overlapping LoAF. Whether the other
  journeys judge LoAF was not checked.
- **O31:** the symptom did not recur (25/25 verified effects in every run). The code was not examined.
- **O23 (clean clone):** advanced. F1 (partly), F4, F5 and F6 ran from a clone of `34bd435`. A–E, F2,
  F3 and the scripts `tsc` project did not. The `../webapp` parent-blob dependency is unchanged.
- **O36:** confirmed latent. `tools/compile-snapshot.mjs:332/350` `?? "Info"` is not reached (source
  severities Critical 3, High 104, Medium 33, Low 6; cross_layer Critical 2, High 40, Medium 1).
- **O14:** confirmed still true. The compiled `fabric` is not frozen, and the grader for B spliced an
  ACL line in the page for the B5 control.
- **O41:** the 768 partial-ring lead was not re-checked. A separate full hide at 390 is now a D3 FAIL
  (new item 3). The C2 scroll-edge cut is still reproduced in state 06 (light/1920: "Under the collected
  RIBs of core1 and core2 only (2 of 26"). The stale "BLOCKED verdict marker" manifest note stands.
- **O44:** the C2 placeholder-ink observation is reproduced: #5f6775 light and #828da0 dark. The
  scroll-edge cut is reproduced. The E-margin figures are superseded by this grade's 168/184 ms.
- **O45:** the note "W7-B7's run there read … 289 focus stop(s) … 0 not visible" does not hold on this
  server (1 not visible, new item 3). The A4 transient was not re-examined.
- **O16:** the mid-motion `setQuality` freeze and organic step-down were not exercised. Owner decision.
- **O17:** compact density was not graded. No descender detector exists.
- **O22:** still open (name-keyed determinism gate). No failing case.
- **O27:** still open. `review/*.mjs` is in no type-checked project, including every harness this grade
  relied on.
- **O9:** unchanged. The Inspector shows the compiled record for bearer cites and says so. R95's
  wording held under the B6 attack.
- **O28:** not exercised. The A1 census used pushState+popstate, not typed keystrokes.
- **R91 (A4), R94 (B6/palette), R79 (F4), all marked FIXED:** A4 fails in a new shape (new item 1).
  R94's commit introduced the C2 regression (new item 2). F4 fails at a boundary R79's build-output test
  does not reach (new item 4).
- **R92–R97 hold:** B6, B7 and D4 PASS and were upheld under attack.
- **Not examined by this grading:** O6, O7, O8, O11, O29, O33, O42, O43 and O46. On O42, no grader
  compared the changed recorded frames against the local baseline.
