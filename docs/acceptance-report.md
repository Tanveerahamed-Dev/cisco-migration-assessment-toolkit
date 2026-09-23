# Atlas Scope — Acceptance Report

Graded 2026-09-23 against `docs/acceptance.md`, at HEAD `1d19e22`. `src/`, `tools/`, `public/` and
the HTML entry points are clean at that commit. Only four `docs/*.md` files are modified in the working
tree, and `git status --short --untracked-files=all` lists nothing untracked. Six first-pass graders
covered groups A–F, and independent refuters then attacked every PASS.

**Where the first pass and the refutation disagree, this report applies the refutation.** Five
verdicts were overturned (C4, C6, tracked-sources, F2, E3). Each overturn comes with a reproducible
proof (a command plus its output), so none was set aside. Every one of the 24 surviving PASS verdicts
was attacked and upheld; none is "PASS, unrefuted". Every group returned a grade. No grader or refuter
ran a git write in the project repository or edited product source.

Where each group was graded:

- A–D: the dev server on :4180, where the task specified it.
- E: a fresh production build on :4181.
- C2 and C5: a fresh build on :4183.
- F: the working tree and a clean clone of `1d19e22`.

This report replaces the 2026-09-22 report at this path. That report graded an uncommitted tree
(HEAD `857b520`), and its figures, such as "the unit suite is red", are superseded.

## Verdict

**Atlas Scope is not ready for acceptance.** Ten criteria fail:

| Criterion | Failure |
|---|---|
| A1 | Evidence reaches configuration for 12 of 146 findings, not "any finding". |
| A4 | Selecting a device resets the queue's scroll position. |
| B1 | A shared URL carrying an invalid port or protocol is rendered as a forwarding verdict, including "delivered". |
| C2 | The default path-trace layout hides three form fields and the submit button at 1440, and slices the button at 1920. |
| C4 | A light-OS reader gets a dark first paint (overturned). |
| C5 | Edge sparkle under orbit and a z-fighting patch still fail the motion harness. |
| D3 | Focus is invisible on the Device-pane tab panels and on the snapshot popover's first control. |
| D5 | The Inspector's resize handle is an 8 px pointer target. |
| E3 | The first device selection after load puts a 55–79 ms task on the interaction path (overturned). |
| tracked-sources | The gate lets an untracked `import.meta.glob` file ship while it stays green (overturned). |

Six more are UNPROVEN. An UNPROVEN criterion is not a pass:

- A2 and B8 cannot be exercised on this snapshot: every trace has depth 1 or less, and no flow is a definite delivery.
- C1 has no blind verdict, and cannot get one against these references.
- C6's motion inventory, the evidence the criterion names, is materially false (overturned).
- F2: three green tests execute zero assertions (overturned).
- F3 cannot show red-before-fix for five engines whose fixes predate the root commit.

Some things are well evidenced and survived attack:

- The forwarding engine's honesty (B2–B7). Among others, a 192,035-trace refuter sweep found 0 claims without the "2 of 26 hosts" scope clause, and 0 no-RIB traversals had an outcome other than indeterminate.
- Blocked-flow attribution (A3), plus on-fabric focus and cut-point marking (A5, A6).
- Keyboard and assistive semantics (D1, D2, D4, D6–D8).
- Laboratory responsiveness on the journeys' steady state (E1, E2, E4, E5).
- Type-checking, code-splitting, reproducible compilation and deterministic capture (F1, F4–F6). These were also reproduced on a clean clone.

## Scorecard

"Overturned" means the refutation's verdict replaced the first pass. "Upheld" means a refuter attacked
the PASS and could not break it.

| Criterion | Verdict | Evidence | Note |
|---|---|---|---|
| A1 | **FAIL** | Census of all 146 findings through Ctrl+K: 6 reach "Show the configuration this finding names", 6 reach "Show the record that matches this finding", 133 get only "Browse <host>'s collected records (context, not this finding's evidence)", and F142 gets no button. For F099 the route took 3 interactions and the topology did not reset (core1 stayed at 474,82 throughout). | Confirms O12 (12/146). Fixing it needs per-finding record pointers from the producer. |
| A2 | **UNPROVEN** | Depth 1 is correct: "ACL — THIS IS WHAT DECIDED THE HOP: PROTECT_SERVERS line 4 of 4 on core1". The depth ratchet `never exceeds the cap, and records the depth it actually reaches` passed (23 passed) and asserts max depth = 1. | The multi-hop half cannot run on this data. New defect: `.hop__host` is 0 px wide on the denied flow's header. |
| A3 | PASS | "denied at core1 by ACL PROTECT_SERVERS line 4 of 4 (acls.core1.PROTECT_SERVERS[3]: \"deny ip any any\")". | Upheld. The refuter's 192,035-trace sweep found 21,230 denials, every one resolving to a line text plus an indexed cite. A second ACL was checked live: "INET_RETURN line 3 of 3". |
| A4 | **FAIL** | With a finding active, the four surfaces re-aim and the camera stays put. Counterexample: with no finding selected and the queue at scrollTop 3200 (F060 and F069, which name access13, both visible), clicking access13 left it at 3200 after 80 ms, then 0 once settled. | New; not in open-issues. |
| A5 | PASS | Hover changes 0.073% of pixels and the camera does not move. Click gives `?d=access13`. Double-click eases access13 from 529,444 to 567,398. "Reset view" restores 474,82 590,113 529,444 736,444 exactly. `undrawnHops` is `[]`. | Upheld on podacc2 plus 5 more flows. The trace is a single-node verdict mark, not path geometry (disclosed). |
| A6 | PASS | core1 draws "⚠ cut point" and "⊘ stranded?" on 9 hosts. The two measures' disagreement is surfaced ("THE TWO MEASURES DISAGREE", "≠ IMPACT DISPUTED"). Pixel diff: articulation pair ≥ 2.481, non-partitioning pair ≤ 1.069. | Upheld: core1 vs podacc1 = 3.634; non-partitioning pairs ≤ 1.339; L34 reads "NEITHER MEASURE EXISTS FOR THIS CABLE". |
| B1 | **FAIL** | `?s=path&flow=10.0.10.50>10.0.20.10>tcp>abc` renders "tcp 10.0.10.50 → 10.0.20.10:NaN" and "a tcp/NaN flow from 10.0.10.50 to 10.0.20.10 is delivered at core1 on connected route 10.0.20.0/24". Port 70000 and protocol `bogus` are also traced. The null-field sweep was otherwise clean. | New; not in open-issues. `store.ts:183-190` skips the form's 1–65535 check. |
| B2 | PASS | All 5 `suggestedFlows()` carry the scope clause (caveats 13/13/10/11/8). 7,168- and 33,708-trace sweeps found `noScope=0 emptyCaveats=0`. | Upheld (192,035 traces). |
| B3 | PASS | "traversedNoRib=2940, all indeterminate, violations=0". Vitest: "unmodelled forwarding is never delivery … ✓". | Upheld (27,630 no-RIB traversals, 0 violations). |
| B4 | PASS | 8 off-subnet sources → `out-of-scope`, 0 hops. "no ingress device can be named and no forwarding claim is made". | Upheld. |
| B5 | PASS | `evaluateAcls` on real lines: `established`, `time-range` and `echo-reply` lines are indeterminate, each with its cite and line text. | Upheld: an independent Cisco-semantics oracle over 6,664 flows gave 0 disagreements. |
| B6 | PASS | 10 random citations, 0 unresolved; LF-normalised sha256 `9580aa09…3089` matches the source. 668 citations checked programmatically, `unresolved=0`. | Upheld. The refuter notes the "every cite in fabric.json" half is tautological; only the trace-emitted cites were a real test. |
| B7 | PASS | "coverage 23/26 collected \| RIBs 2/26 (both shown incomplete) \| ACLs 1/26 \| centrality 25/44". Topmost and in the viewport at 390x844 and 1440x900. | Upheld at 1920x1080, 768x1024, 320x568 and 568x320. |
| B8 | **UNPROVEN** | 15,606 traces: `definiteDelivery=0`, 0 counterexamples. UI: "no counterexample is offered. That is not proof that none exists". | Confirms O13. The positive state renders only in jsdom fixtures. |
| C1 | **UNPROVEN** | `review/blind/KEY.json`: 12 entries and zero verdicts; 8 of the 20 sheets are orphans. The `-craft` sheet still shows "Forward AI" and the Storylane modal. | Confirms O19; needs an owner decision. |
| C2 | **FAIL** | `capture.mjs text`: "PASS text 72 of 72 states". But at 1440x900 on `?s=path` the path slot is 170 px (84–254), and Destination, Protocol, Port and "Trace this flow" (463–491) all lie outside it. At 1920 the slot ends at 466 while the submit spans 449–477. The not-observed box also switches layout between adjacent rows. | New; not in open-issues. The 72-of-72 gate cannot see a control clipped by its scroll slot. |
| C3 | PASS | 1440: 1 of 7 visible rows clamped (F002 loses one word); 1920: 0 of 11. Every row keeps its glyph, ID, device and category. | Upheld, but over the whole C+H list 79/107 titles are clamped at 1440 and 34/107 at 1920. Comfortable density only (O17). |
| C4 | **FAIL** | First pass: two authored palettes and all 8 settled states themed. Refutation: `index.html` line 2 is `<html lang="en" data-theme="dark">`. With a light OS and no stored preference: `{t:36,boot-line-painted,themeAtCallback:"dark",bg:"rgb(8, 10, 14)"}`, then `{t:225..368,theme:null}`. | **Overturned PASS → FAIL.** New; not in open-issues. |
| C5 | **FAIL** | `capture-motion.mjs` exit 3. Edge sparkle fails on all 8 orbit sequences at both tiers (304–739 px against a 120 px bar). The z-fighting 16 px run fails at dark/low (x372–387, y343). Label blinks 0; AO 8/8; tier fade 24/24 at 266.5–266.7 ms. | Confirms O16. The popping FAIL (light/high dolly frame 59, "Infinityx") reads as a harness normalisation artefact. |
| C6 | **UNPROVEN** | Runtime: "OVER 300ms or infinite: 0". Refutation: the design-brief §4.8 inventory claims "staggered 18 ms per hop" (`flow.ts` has one 240 ms reveal and no stagger) and a "Command palette 140 ms" that does not exist (80 ms). It omits skip-link, stage-dim, drawer, switch, chevron, label and progress transitions. The packet loop was never exercised. | **Overturned PASS → UNPROVEN.** Contradicts R24/R29's closure of the inventory. |
| tracked-sources | **FAIL** | First pass: 20 tests passed; `git ls-files --others` empty. Refutation, in a copy: an untracked `src/forwarding/zz-untracked-probe.json` gave "Tests 3 passed (3)", and then `grep -l UNTRACKED_GLOB_PROBE_7f3a -r dist-probe` printed `dist-probe/assets/mount-B_bg_vzD.js`. | **Overturned PASS → FAIL.** The walker does not follow `import.meta.glob` (`Inspector.tsx:136`). The tree is clean today, but the gate cannot guarantee it. |
| D1 | PASS | Tab cycle with no trap in all 8 states; 0 unreachable controls. A1 and A2 work by keyboard only. The canvas supports ArrowRight select, Shift+Arrow orbit and Alt+Arrow pan. | Upheld at 390, 768 and 1920; the column resizer has a working keyboard equivalent. |
| D2 | PASS | `role=grid`, `aria-rowcount=152`. Arrows, Home/End, PageUp/PageDown, Ctrl+Home/End and sort all verified; one `tabindex=0` after every key. | Upheld. At 390x844 the focused cell can sit under the sticky status bar (D3 lead, not graded). |
| D3 | **FAIL** | `audit-d3-focus.mjs`: "210 case(s), 0 failed." (focus *return*). But the Device-pane tabpanel outline is clipped by `.dp__body`: "0 pixels at ≥3:1". "Copy the snapshot sha256" sits at x=641–668, outside the x=121–554 popover; `elementFromPoint` returns `CANVAS.fabric3d__canvas`. | New; neither case is in open-issues. |
| D4 | PASS | 3,116 text items: 0 failures; minimum 4.71 dark / 4.60 light. Cable dashes 8.88:1 / 6.75:1. | Upheld: 197 hovered elements, 0 failures. |
| D5 | **FAIL** | `div.inspector__divider` (role=separator) is 760x8 at 1440 and 1160x8 at 1920. A 60 px drag changed the Inspector height 316 → 376. `target-size.test.ts` scans only `cursor: pointer`, and `docs/target-size-exceptions.md` does not exist. | New; not in open-issues. The prior PASS never opened the Inspector. |
| D6 | PASS | The Fabric list tree has 119 treeitems: 26 devices and 44 links, equal to `fabric.json`. 26/26 canvas picks match the tree. | Upheld: a dense pick sweep found exactly 26 devices and 44 links. |
| D7 | PASS | `capture.mjs reduced`: "PASS D7: camera lands in one frame under reduce, 24 poses without it." | Upheld: under reduce Home gives 1 pose vs 23 and orbit 1 vs 32. The packet half is fixture-only. |
| D8 | PASS | Greyscale 03/06 in both themes: severity letters, band letters, "? UNDECIDED" wording, and dashed cable patterns. | Upheld. |
| E1 | PASS | "acts with a verified effect 25 of 25" for J1–J4 and J3b; 6 pass / 0 NOT MEASURED. | Upheld: J5's palette was visible within 8–15 ms on all 25 reps. |
| E2 | PASS | p95 of worst interaction per rep: J1 32, J2 40, J3 32, J3b 32, J4 48, J5 32 ms. "ACCEPTANCE EVIDENCE: release build, hardware renderer, quiet host." | Upheld; the first selection in a fresh browser takes 104–144 ms, still < 200. Laboratory figures. |
| E3 | **FAIL** | First pass: "E3 … PASS — J1…J5 and J3b STABLE PASS (3/3 clean)". Refutation: in a fresh browser, the first canvas click on core2 gave `ONPATH>50` in 15 of 15 trials (d = 55–79 ms), attributed to `CANVAS.onpointerup@Fabric3D` and then a React/rAF frame. | **Overturned PASS → FAIL.** The harness uses up the first J2 selection in `prime`. |
| E4 | PASS | "PASS E4 focus flights: median 60 fps across 10 windows, worst window 60 fps (floor 45) … orbit median 60fps". | Upheld. Passes the **restated** criterion only: the "trace animating" condition is unreachable, the canvas is 1160x962, and the panel caps at 60 Hz. |
| E5 | PASS | `audit-e5-coldload.mjs`: "PASS E5 3 cold loads …"; worst frames 105.2/133.2/110.9 ms. The sweep: "all 16 actions stayed under 200 ms in every one of 3 repetitions". The carve-out was not applied (`grep -c` = 0). | Upheld (a palette opened during load reached 168–192 ms: a thin margin). The "communicated/cancellable" half was never exercised. |
| F1 | PASS | `tsc -p tsconfig.json --noEmit` EXIT 0; the scripts project with `--noImplicitAny` EXIT 0. Same on the clean clone. | Upheld. `vite.config.ts` and `vitest.config.ts` are outside both projects. |
| F2 | **UNPROVEN** | "Test Files 121 passed (121) / Tests 1571 passed (1571)", EXIT 0 (working tree and clean clone). Refutation: a per-test `assertionCalls` probe found 3 tests with **0** assertions: `motion-inventory.test.ts:89`, `compiler-fidelity.test.ts:101`, `engine.test.ts:840`. | **Overturned PASS → UNPROVEN.** The suite is green, but it violates the criterion's own precondition-pin clause. |
| F3 | **UNPROVEN** | `mutation-check.mjs`: 18 of 18 KILLED. From history: 1d19e22's `claims.test.ts` on 254694b's `claims.ts` gave "2 failed \| 37 passed". | Forwarding, blast, layout, query and compile-snapshot fixes predate root `50a3dc5`, so there is no red-before-fix revision to show. |
| F4 | PASS | `npm run build` EXIT 0; `three-DcNJC9c1.js 827.80 kB`; `WebGLRenderer` appears 0 times outside the three chunk. | Upheld: at 767 and 375 px three is never requested; at 1440 it loads after the load event. |
| F5 | PASS | `fabric.json` sha256 `2f558c38…a308` before and after; the compilers exit 0. The clean clone reproduces all four hashes. | Upheld in an isolated `tools/`-only sandbox. Reproduction needs the parent blob. |
| F6 | PASS | "verdict: F6 PASS: 32 of 32 frames byte-identical across 5 runs." The dev server gave byte-identical frames across its 2 runs. | Upheld on an unshared :4191 server; 10 captures from two servers agree. |

## What is proven

Every criterion here was graded PASS and then survived an independent refuter.

- **A3.** Grader: live UI on the 3389 flow, naming the device, ACL, 1-based line and literal text. Refuter: a 192,035-trace sweep (all 21,230 denials resolve to a line and a cite) plus a second ACL, INET_RETURN, checked in the live UI.
- **A5.** Grader: pixel diffs and projections for hover, click, double-click focus and reset on access13. Refuter: the same on podacc2 ("equal initial: true") and 5 more flows, each with `undrawnHops` `[]`.
- **A6.** Grader: 26 devices clicked at one camera, with pixel-diff separation. Refuter: podacc and dist devices (non-partitioning under both measures). core1 vs podacc1 = 3.634 against ≤ 1.339 for non-partitioning pairs. L34 surfaces absence rather than health.
- **B2, B3, B4.** Grader sweeps of 7,168 and 33,708 traces. Refuter sweep of 192,035 traces: 0 claims missing "2 of 26 hosts", 0 empty caveat lists, 27,630 no-RIB traversals all indeterminate. Code review of `engine.ts:2038-2065`.
- **B5.** Grader: direct `evaluateAcls` against real lines. Refuter: an independent oracle over 6,664 flows, 0 disagreements on verdict or cite.
- **B6.** Grader: 10 random citations and 668 programmatic ones resolved, and the source digest matched. Refuter: confirmed resolution, and noted that only the trace-emitted cites are a non-tautological test.
- **B7.** Grader: `elementFromPoint` at 390 and 1440. Refuter: 1920, 768, 320 and 568x320, with the counts matching the source.
- **C3.** Grader and refuter both reproduced "1 of 7 visible rows clamped" at 1440 at comfortable density. The refuter judged the wider clamping (79/107 at 1440) short of "truncated to uselessness".
- **D1, D2, D4, D6, D7.** Keyboard-only A1/A2 flows, the grid key matrix and ARIA, rendered-pixel contrast, tree-vs-canvas parity and the reduced-motion gate were all reproduced and widened by the refuter: 390/768/1920 widths, hover states, a 4 px pick sweep, and per-input camera pose counts under reduce.
- **D8.** Greyscale inspection of states 03 and 06 in both themes, repeated independently.
- **E1, E2, E4, E5.** The laboratory harnesses (`measure-inp`, `measure-fps`, `audit-e5-coldload`, `audit-e5-sweep`) were reproduced by the refuter on the fresh production build and widened: 23 devices, 10 flows, fast typing, and orbit in both themes with an outline. All figures are LABORATORY: one host, headed Chromium, Intel D3D11, 60 Hz. E4 is proven only for the restated condition (camera motion, not a trace animating).
- **F1, F4, F5, F6.** Reproduced on the working tree, a clean clone of `1d19e22`, and refuter sandboxes: an isolated compile, a scratch `outDir` build, and an unshared :4191 preview.

## What is not

### FAIL

- **A1.** 134 of 146 findings do not reach configuration evidence in 3 or fewer interactions: 133 land on context only, and F142 gets no button. This needs per-finding record pointers from the parent engine (O12). It cannot be fixed inside Atlas Scope.
- **A4.** Selecting a device with no finding active discards the reader's queue position. For access13 it went 3200 → 0; for core2, 3200 → 2681; dist1 behaved the same. This happened even though rows naming the device were already in view.
- **B1.** Validation is missing on the URL-restore path (`store.ts:183-190`) and in `traceFlow`. A NaN port, a port outside 1–65535, or an unknown protocol in a shared link is traced and rendered as a verdict, including "is delivered at core1". The "not decided" qualifier never names the invalid input.
- **C2.** On the captured path-trace surface, `SPLIT_DEFAULT 60` and the shell's min-content rule leave the path panel a 10rem floor. At 1440 that hides Destination IP, Protocol, Port and the submit button, and at 1920 it cuts the submit button in half. Separately, adjacent not-observed boxes switch between a stacked and a side-by-side layout depending on text length (Power supplies vs Modules on `?d=core1`). The 72-of-72 text gate cannot detect either.
- **C4 (overturned).** The light theme is incomplete at first paint. The hard-coded `data-theme="dark"` defeats `ThemeToggle`'s own intent, so a light-OS reader with no stored preference sees the dark palette for about 190–330 ms. The boot state was never checked in light.
- **C5.** Edge sparkle under orbit fails at both tiers in all 8 orbit sequences (304–739 px against a 120 px bar). The z-fighting ≥16 px rule failed at dark/low this run and at dark/high in the recorded run. The harness also reports popping FAIL until its normalisation artefact is fixed.
- **D3.** Two new failures: (1) the Device-pane tabpanel focus outline is fully clipped by `.dp__body` overflow; (2) the snapshot popover's initial focus target, "Copy the snapshot sha256", is pushed outside the popover by the unwrapped sha256 and cannot be seen. Focus *return* passes, 210 of 210.
- **D5.** The Inspector resize divider is a live 8 px pointer target with no exemption and no alternative. The target-size test misses it because it scans only `cursor: pointer` rules. The exceptions document it refers to does not exist.
- **E3 (overturned).** The first device selection after load (J2's own interaction, in a fresh browser) had a 55–79 ms long task on the interaction path in 15 of 15 core2 trials. core1 did so in 1 of 3 trials and dist1 in 0 of 3. The harness hides this: `prime` uses up the first selection, and J2 runs in a warm browser. E2 still holds, at 104–144 ms.
- **tracked-sources (overturned).** `tracked-sources.test.ts` claims its denominator "cannot drift from the build", but its walker ignores `import.meta.glob`. Proof: an untracked JSON file shipped in `mount-B_bg_vzD.js` while the test passed 3 of 3. Today's clean result rests on a coincidence: the two globbed JSONs are also imported statically.

### UNPROVEN

- **A2.** The shipped data has a maximum depth of 1. The multi-hop half (a second hop's decider, next-host resolution, TTL and loop handling) cannot run, and the criterion forbids grading a depth-1 capture PASS.
- **B8.** No flow on this snapshot is a definite delivery, so "the nearest flow that would succeed" cannot render. It is exercised only by jsdom fixtures (O13).
- **C1.** There are zero recorded blind verdicts. The reference sheets identify themselves (Forward AI nav, Storylane modal), so any verdict against them would not be blind (O19; owner decision).
- **C6 (overturned).** Runtime durations stay under 300 ms, but the criterion's named evidence, the §4.8 motion inventory, is false. It describes a per-hop stagger that does not exist and a 140 ms palette animation that does not exist, and it omits about 8 running transitions. `motion-inventory.test.ts` never scans CSS `transition:` declarations. The packet loop (1.6 s × 3) is unreachable on this snapshot, so the grader's loop check proves nothing about it.
- **F2 (overturned).** The suite is green: 1571 of 1571 on both the working tree and the clean clone. But `motion-inventory.test.ts:89`, `compiler-fidelity.test.ts:101` and `engine.test.ts:840` record zero assertions against the shipped data. Four more tests can pass vacuously: `engine.test.ts:765` (the expect fires for 1 of 11 probes), `ip.test.ts:269` (5 of 9 rows, no count pin), `status-telemetry.test.tsx:191` (passes if `.sb__scene` disappears) and `camera.keyboard.test.ts:116`.
- **F3.** The mutation run proves the tests catch the defect shapes in today's code. By the script's own statement it is "not pre-fix history". Only claims (R34) and the provenance, motion, determinism and hygiene gates have history-verified red-before-fix evidence. `refutation.md` §7 also records that the compiler was never refuted for the fields it transforms.

## What was not examined

Collected from each grader's and refuter's own statements.

**Environment and scope**

- No real screen reader was used (D6 rests on `ariaSnapshot`).
- Only headed or headless Chromium was used, on one host (Intel iGPU, ANGLE D3D11, 60 Hz). No field INP data exists.
- The Browser pane could not render: `requestAnimationFrame` never fires while it is hidden, and other agents hijacked it mid-test. All visual evidence comes from Playwright.
- A–D were graded on the :4180 dev server only. Only groups F and E, plus C2 and C5, were checked against a build. Only group F was re-run on a clean clone; no clean-checkout re-run was done for A–E.
- The :4180 dev server used about 1.5 cores throughout every E measurement. The E harness's "harness 2%" CPU share was not audited, and neither was `stats().fps` against GPU present timing.

**Group A**

- A1: the evidence button was clicked for F099 and F002 only; the other 10 covered findings were checked by label. The queue-filter route was not run.
- A2: no one independently searched for a depth ≥ 2 flow; the engine ratchet was relied on.
- A5: link hover, keyboard orbit and pan, and reduced motion were not checked. The refuter's runs converged at quality `low`, so tier-specific claims were not re-checked.
- A6: the "all-nodes" projection toggle was not examined, and link selections were not pixel-diffed. Pixel diffs used one camera, one theme and one tier.
- The origin of the new A2 and A4 defects was not traced in git history.

**Group B**

- The B3–B5 tests were not checked against history for red-before-fix.
- `evaluateObservedBindings` trace-level paths were not re-attacked.
- No later-hop no-RIB case exists on real data, so every no-RIB traversal seen was at ingress.

**Group C**

- Compact density was not checked.
- Only the fabric overview pose was checked for C5 static quality, and link width was measured on two links. Motion was measured at DSF 1 only.
- The 1920 captures of states 01 and 05 were not fully viewed in light. `capture.mjs app` was not re-run after `1d19e22` (the recorded captures predate it by 44 minutes).
- The JS eases and the camera tween duration were not observed at runtime. The packet marker never ran. C4 dialogs, tooltips and the legend were not checked individually.

**Group D**

- D3: toasts, Inspector sub-tab panels beyond the first stop, and 390 px focus visibility were not checked (the D2 refuter's 390 px occlusion lead is ungraded).
- D4: pressed and focus-ring states were not re-measured; canvas cables were sampled, not measured per pixel.
- D5 at 390 px was measured only for the base states. D6: Enter was pressed on only 1 of 88 link rows. D7: canvas halo fades under reduce were not checked.
- D8: states 05 and 08, the 1920 frames and open popovers were not checked.

**Group E**

- The first-after-load J4 and J5 were not checked for E3 in a fresh browser, and nothing was checked at native DPR or with a warm shader cache.
- E4 was not checked below 1024 px, in the `ATLAS_FULLBLEED` lane, or on a panel above 60 Hz.
- E5's cold-load keystroke coverage was 4 of 7 blocking frames. Its "communicated/cancellable" half was never exercised.

**Group F**

- The F2 hollow-test hunt covered about 25 of 161 flagged tests by hand.
- Mock surfaces were not checked against the real producers.
- The `review/*.mjs` harnesses and the vite and vitest configs sit outside type-checking.
- The `fabric-preview.html` and `panels-preview.html` entry graphs are not walked by the tracked-sources gate.
- History cannot reach the pre-repository engines' defect records.

**Side effects the graders disclosed**

- Harness runs rewrote `review/reports/inp.json` and appended to `review/reports/inp-e3-history/`.
- The F grader overwrote the ignored outputs `review/shots/app`, `review/shots/_twice` and `dist/`.
- The B grader briefly wrote into the shared `scratchpad/probe/`, and may have overwritten another agent's probe config.

## Known issues carried forward

This section reconciles the grades against `docs/open-issues.md`. This report does not edit that file.
The entries marked **new** and the status changes below should be recorded there.

**Confirmed still open by this grading**

- **O12** (A1, 12/146): confirmed exactly; still not closable in Atlas Scope.
- **O13** (B8): confirmed; 0 definite deliveries in 15,606 traces.
- **O16** (C5 edge sparkle): confirmed at both tiers. The z-fighting cluster moved from dark/high to dark/low in this run, so treat it as unstable, not fixed. The cluster-rule question (4-connected vs a 4×4 patch) stands.
- **O17** (layout residuals): compact density was again not covered. The 768 px overflow and descender clipping were not re-checked. The new C2 path-slot defect belongs with it.
- **O19** (C1): confirmed; still an owner decision.
- **O22** (determinism keyed on field names): still open. F6 passes, but the shape is unchanged.

**Status changes**

- **O20:** the "E5 stays UNPROVEN" status is superseded. E5 now PASSES on a quiet AC host (acceptanceEvidence=true, excess 17–21%). The pre-FCP carve-out remains an owner decision and was not applied.
- **O21:** its eight out-of-journey classes did not reproduce on the quiet host. Seven read worstLoAF 0 ms in all 3 reps, and so does path-trace swap+submit. Only "seed a flow by navigation" (87.3–100.6 ms) and resizes (50.1–63 ms) crossed 50 ms, and both are outside E3. **E3 is nonetheless FAIL**, on a different, in-journey path: the first J2 selection after load (see new item 9).
- **O23:** closed for F1, F2 (unit half), F4 and F5, which were re-run on a clean clone of `1d19e22` (with the parent blob `1ed99404` placed at `../webapp`). It is still open for A–E.
- **O10 / R10:** "`tracked-sources.test.ts` GREEN" is true but not sufficient; see new item 7. The gate's claimed denominator is wrong.
- **R24 / R29** (C6 inventory "FIXED"): contradicted. The inventory is still inaccurate and its guard does not scan CSS transitions (new item 6).
- **R28** (C2 detector widened): the detector still cannot see a control clipped by its scroll container (new item 4).

**Not examined by anyone in this grading; carried as they stand**

- O11 (owner decision on an earlier refused hop)
- O14 (`failureImpact().engine.record` aliases the snapshot)
- O6 (bloom halos at `high`)
- O7 (SCOPED badge; premise found false 2026-09-21)
- O8 (ignore-ACLs counterfactual not built)
- O9 (B6 shows the compiled record, not source JSON; consistent with B6 as restated)

**New: not in `docs/open-issues.md`**

1. **B1:** URL-restored flows are not validated (`store.ts:183-190`, `traceFlow`). A NaN, out-of-range port or unknown protocol is rendered as a verdict.
2. **A4:** a device selection resets the queue's scroll position when no finding is active.
3. **A2 / layout:** `.hop__host` collapses to 0 px on the denied flow's hop header, which overflows by 174–214 px at every tested width.
4. **C2:** the path-trace default split hides the form and the submit button. The not-observed box layout is inconsistent between adjacent rows.
5. **C4:** `index.html` hard-codes `data-theme="dark"`, so light-OS users get a dark first paint for about 190–330 ms.
6. **C6:** the design-brief §4.8 motion inventory is false (stagger, palette 140 ms, omissions), and `motion-inventory.test.ts` does not scan CSS `transition:`.
7. **tracked-sources:** the walker ignores `import.meta.glob`, so an untracked file can ship green. It also does not walk the preview entry points or the compilers' imports.
8. **F2:** 3 zero-assertion tests and 4 conditional or vacuous ones (listed under UNPROVEN).
9. **E3:** a 55–79 ms on-path task on the first device selection after load. `measure-inp.mjs` hides it by using up that selection in `prime` and by running J2 warm.
10. **D3:** the tabpanel focus outline is clipped by `.dp__body`, and the sha256 Copy button sits outside its popover. There is also a lead at 390 px: the focused grid cell can sit under the sticky status bar.
11. **D5:** the Inspector divider is 8 px. `target-size.test.ts` scans only `cursor: pointer`, and `docs/target-size-exceptions.md` is missing.
12. **F1 (scope):** `vitest.config.ts`'s `minWorkers: 1` is silently ignored (TS2769, and it is absent from vitest 4.1.11). `vite.config.ts` ends in `as any`. Neither config is in a type-checked project.
13. **Claim consistency (lead, from the B6 refuter):** the coverage record shows `aclLinesUnevaluable 1`, while the status bar says 6 of 12 lines cannot be decided.
14. **B1 (minor):** for the same null `adminDistance`, the Inspector renders "0 — a connected route's administrative distance by definition", while the HopList renders "not observed".
15. **Harness defects (not product):**
    - The palette keystroke race in the A1 census: 53 of 146 queries were garbled with no gap after opening, 0 with a 150 ms gap. It was not shown that a human would hit it.
    - `capture-motion.mjs`'s popping check divides by a neighbour median of 0 ("Infinityx").
    - `measure-inp`'s headed window is taller than the host screen, which produced off-screen "8096 ms" keyboard artefacts.
