# Atlas Scope — Acceptance Report

Graded 2026-09-26 against `docs/acceptance.md`, at HEAD `7f67013` ("fix: close acceptance repair wave 8
(A4, C2, D3, F4) and the J2 harness aim"). Every grader found the same tree. `git status --short` showed
only ` M docs/open-issues.md`, an uncommitted documentation edit. `git diff HEAD --stat` touches no other
file, so `src/`, `tools/`, `review/` and the configs are byte-for-byte `7f67013`.

Six first-pass graders covered groups A–F. Independent refuters then attacked every PASS verdict. Every
grader and every refuter returned. No group is marked "grader did not run", and no PASS is listed as
unrefuted: all 28 surviving PASS verdicts were attacked and upheld.

**Where the first pass and the refutation disagree, this report applies the refutation.** Five PASS
verdicts were overturned, and in every case the refuter supplied its proof (a named script, its printed
output, and the frames or source lines it rests on):

| Criterion | First pass | Applied | Proof the refuter supplied |
|---|---|---|---|
| C2 | PASS | **FAIL** | Frames `{light,dark}/1440/06-path-blocked.png`, crops `tabclip-{light,dark}.png`, and a live measurement: `"t":"Trace a flow","top":65,"bottom":97,"portTop":84,"scrollTop":19,"visibleFrac":0.40625`. |
| D3 | PASS | **FAIL** | `drawer.mjs` output at 1100, 1024 and 1270 px: `after e (inside drawer) drawer=null \| ... [BODY] inRailB=false`, plus the palette path in `drawer3.mjs`. |
| E2 | PASS | **FAIL** | `first.mjs` under `review/host-env.mjs`: "J5 FIRST after load, 1280x800 dark: 20 trials; worst-interaction p50 224 p95 320 max 352", "HOST-ENV VERDICT: ACCEPTANCE EVIDENCE", with a J4 control at p95 32. |
| E3 | PASS | **FAIL** | The same two accepted runs: J5's first Ctrl+K ran `#document.onkeydown` as a long task of 51–83 ms, in 6 of 20 (dark) and 9 of 20 (light) fresh loads. |
| F2 | PASS | **UNPROVEN** | The grader's own recorded red run on the same tree ("Tests 286 failed \| 3480 passed (3766)", exit=1), plus a reading of `vitest.config.ts:4-15`. The refuter did not reproduce the red itself. |

The F2 overturn is to UNPROVEN, not FAIL. It rests on the grader's recorded output rather than a
reproduction, and it establishes that a stable green verdict does not exist, not that the tree is red.

One refuter did not overturn a grade but replaced its evidence. The F6 grader diffed two `app`
captures, and the harness's own PASS line for that mode says "(render check only; NOT an F6 determinism
result: run `twice 5`)". The refuter ran the prescribed `twice 5`. F6 stands on the refuter's run, not
the grader's.

C5 was graded FAIL by the first pass. Refuters attack PASS verdicts only, so it was not re-examined. It
stands as graded.

This report replaces the grade of `34bd435` at this path. Figures from that grade appear here only where
they are labelled as history.

**Where each group was graded:**

| Group | Server and tree |
|---|---|
| A | The :4180 dev server, 1920×1080, light theme, in background Browser-pane tabs (another agent drove the fronted tab, so every reading was redone and the URL checked before each read). The A4 probe and the A6 pixel diff ran in headless Playwright Chromium (SwiftShader, tier low). |
| B | The :4180 dev server, in the grader's own headless Chromium, importing the app's `?t=` module URLs. The shared Browser pane was abandoned after another agent took over tab-13. |
| C | A fresh release build served by `vite preview` on :4181. `review/build-freshness.mjs`: "fresh: true, served page is this checkout's dist/, and nothing in the source is newer". |
| D | The :4180 dev server only. **No production build was measured for D.** |
| E | `npm run build` (exit 0), served by one `npx vite preview --port 4181 --strictPort`, build hash `5ccb42f6a09ed652`, "build: fresh" in every harness. **On mains power for the whole session** (`Win32_Battery BatteryStatus=2` at eight readings, 10:48–11:15 +0300, charge 36 % → 65 %); saver=Disabled, supply=Adequate. ANGLE Intel D3D11, tier high, 60 Hz. |
| F | The working checkout, a scratch `vite build` served on :4190, and a fresh `git clone` of `7f67013` for F5 (parent blob `1ed99404` at `../webapp`). |
| Refuters | A/B on :4180 and headless Chromium. C/D on :4180. D7/F on a private frozen `vite build` served on :4197. E on a rebuilt :4181 preview (same hash `5ccb42f6a09ed652`). |

**Host contention.** Several graders and refuters shared one host and one dev server. It had visible
effects: one Vite reload killed the D grader's first D3 audit run ("Execution context was destroyed");
the F grader's first full vitest run went red at 85–100 % CPU; a refuter's `reaim-tab-and-restore` run
failed once at 16.4 s under load and passed on reruns. Those effects are reported where they bear on a
verdict.

**The tracked-sources gate is a precondition, not a criterion.** `src/core/tracked-sources.test.ts`
passed 9 of 9 in every group, inside green multi-file runs: A (6 files, 179 of 179), B (6 files, 109 of
109), C (4 files, 125 of 125), D (9 of 9), E (2 files, 23 of 23), F (both full runs). F counted 255
files under `src/`, all tracked (`find src -type f | wc -l` = 255 = `git ls-files src | wc -l`). No
grader found an untracked build input.

## Verdict

**Atlas Scope is not ready for acceptance at `7f67013`.** Six criteria FAIL:

- **A1:** configuration evidence is reachable for only 12 of 146 findings.
- **C2 (overturned from PASS):** in captured state 06 at 1440 px, both themes, the path panel's own
  tab strip ("Trace a flow" / "Verify an intent") is sliced through its glyphs; only 40.6 % of each
  label shows.
- **C5:** one of 24 tier cross-fades cut instead of fading: "opacity fell 0.36 in one frame (frame 34;
  bar 0.25)".
- **D3 (overturned from PASS):** at the drawer widths (1024–1279 px), closing the evidence drawer from
  the keyboard while focus is inside it drops focus to `<body>`, with no visible focus and no return.
- **E2 (overturned from PASS):** the first Ctrl+K after load, in a fresh browser at the reference
  machine's 1280×800 panel, has a lab INP p95 of 320 ms (bar 200 ms).
- **E3 (overturned from PASS):** that same first Ctrl+K runs its keydown handler as a 51–83 ms task in
  6–9 of 20 fresh loads.

Five more are UNPROVEN, and UNPROVEN is not a pass:

- **A2** and **B8** need producer data that this snapshot does not have (O34, O13).
- **C1** needs an owner decision (O19).
- **F2 (overturned from PASS):** one full run of this tree was red and one green. The repository's own
  gate policy says such a gate is not a gate.
- **F3** lacks red-before-fix history for 13 of its 21 guards, which predate the root commit.

The other 28 criteria PASS, and every one of them survived an independent attack.

Measured against the grade of `34bd435`, wave 8 did what it said on its four named items: A4 now passes
(R106 holds at 1920 and 1440), F4 now passes (R103; the breakpoint is one shared 48rem query), the C2
wrap licence is gone ("PASS wrap 0 unjustified token-break licence(s)"), and the 390 D3 hidden stop is
gone (the D3 audit reports 0 failures). But C2 and D3 each fail again in a different shape the named
fix did not reach, and E2, E3 and C5, which passed at `34bd435`, fail here. The E2/E3 failure is in a
condition no harness ever measured (a cold palette open at 1280×800), not a regression that the
harness saw: the tracked `measure-inp` still reports all seven journeys clean. That is the recurring
shape in this grade: **every new FAIL sits just outside the denominator of the gate that reported
green** — a text detector that cannot see scroll-edge cuts, a focus audit with no drawer case, and an
INP harness that times J5 only warm at 1920.

## Scorecard

Refutation overturns applied: **C2 PASS→FAIL, D3 PASS→FAIL, E2 PASS→FAIL, E3 PASS→FAIL, F2
PASS→UNPROVEN.** F6's evidence replaced by the refuter's `twice 5` run. No other verdict changed.

| Criterion | Verdict | Evidence | Note |
|---|---|---|---|
| A1 | **FAIL** | Census over F001–F146 (pushState+popstate, each read waiting until `.ev__id` matched, 0 stale reads): named 6 (F002, F136–F140), matched 6 (F099, F102, F106, F107, F109, F126), context 133 ("Browse <host>'s collected records (context, not this finding's evidence)"), none 1 (F142). F099: Ctrl+K, Enter, one click, camera identical at all three steps. | "Any finding": 134 of 146 have no configuration route. Matches O12. Not closable in Atlas Scope. |
| A2 | **UNPROVEN** | tcp 10.0.10.50→10.0.30.10:3389: `.hop` count 1, "Hop 1 of 1: core1", "THIS IS WHAT DECIDED THE HOP: PROTECT_SERVERS line 4 of 4 on core1 denies this flow", cite `acls.core1.PROTECT_SERVERS[3]`. Depth ratchet `engine.test.ts:1051` `toBe(1)` green. | The multi-hop half has never run on product data (O34). |
| A3 | PASS | `<code class=hop__raw>` "deny ip any any"; hop reads "PROTECT_SERVERS line 4 of 4 / on core1 / denies this flow / deny ip any any / acls.core1.PROTECT_SERVERS[3]"; compiled data index 3 agrees. | Upheld at 4 widths × 2 themes. An engine sweep of 1,210 flows found exactly two deny classes; the second, "INET_RETURN line 3 of 3 … acls.core1.INET_RETURN[2]", renders the same way, labelled "ACL · HYPOTHESIS". Residual: at 1920 that line sits at y=695 in a panel clipped at 537 (a scroll is needed). |
| A4 | PASS | Device (core2 from canvas), finding (F054), link (L28) and hop ("Hop 1 of 1: core1") each re-aimed without narrowing, camera unchanged, queue row revealed (e.g. scrollTop 1000→2885, F054 at 888–944 in port 750–1054). Tracked probe IN at every step at 1920 and 1440; 768 preview "6 applicable steps, 0 OUT". | Upheld over palette, tree, canvas and flow-link selections. Scope limits: 768 on the dev server gave 1 OUT at a 700 ms settle, IN at 3000 ms; at 768/390 the queue port is off screen after a surface switch (O49, owner decision); 390 cannot select a link (O48). Refuter lead: F001 switches the Device pane to a Findings tab that does not list F001. |
| A5 | PASS | Canvas click core2 → `d=core2`; hover `dataset.hovering="true"`, cursor pointer; double-click dist1 (923,828)→(705,410), core1 off view; Reset view → dist1 (736,444), access13 (528,444), the home pose. Trace on fabric: "core1 · C · ? undecided". | Upheld in SwiftShader: Reset restored exactly (736.24,443.84)/(529.08,443.95). On shipped data the fabric trace is a single-node marker, not a drawn path. |
| A6 | PASS | "core1 strands 9 (uncertain; 0 under the all-nodes projection) · all 9 marked"; "⚠ cut point" and "⊘ stranded?" labels; access9 "DISAGREEMENT … Both are shown. Neither is suppressed." Pixel diff: articulation pairs 2.72–3.62 %, non-partition pairs 0.31–1.13 %. | Upheld and extended to all 26 devices: all 48 articulation pairs (2.595–4.129 %) exceed every collected non-partition pair (max 1.140 %). Dark theme on 8 devices: 2.952 % vs 1.182 %. |
| B1 | PASS | 26 devices × 5 tabs, 130 pages (after discarding a 700 ms fixed-wait pass that caught 56 loading screens). Never-collected hosts read "not observed — the device was never reached"; no-RIB hosts "a hop through it is unmodelled, which is neither a delivery nor a drop"; `is:healthy` "0 of 146 findings match, 14 undecided". | Upheld: the only bare "ok" (core1 Gi1/0/24, `physical_health[80]`) sits over measured zeros; 19 all-null "ok" rows render "not assessed". Latent O36 `?? "Info"` never fires (no Info severity in compiled data). |
| B2 | PASS | 5 suggested flows each open "Under the collected RIBs of core1 and core2 only (2 of 26 hosts in this topology)" with 13/13/10/11/8 caveats. Sweeps of 6,336, 960 and 3,080 traces: 0 missing scope or caveats. | Upheld: 28,090 traces including invalid inputs ('', 'abc', '10.0.10.256', '::1', gre, port 70000/-1): 0 throws, 0 missing scope, 0 empty caveats. All 5 "Verify an intent" results carry the scope. |
| B3 | PASS | "✓ unmodelled forwarding is never delivery > stops at the host whose forwarding table we do not hold". 336 of 960 traces cross a no-RIB host: `{indeterminate: 336}`. Rendered "Hop 1 of 1: dist1 / not modelled / — undetermined". | Upheld: 456 such traces in 28,090, all indeterminate; 0 delivered with a non-empty `unmodelledHosts`. |
| B4 | PASS | "✓ … each (source, flow) is out-of-scope, consults no device, and carries the 'lies in no subnet' sentence"; 285 of 285 out-of-scope traces carry it. Rendered "198.51.100.7 lies in no subnet this collection observed". | Upheld on 16 edge sources × 3 flows (0.0.0.0, 255.255.255.255, 224.0.0.5, 127.0.0.1, subnet edges). Zero-padded input is "invalid-address", a different refusal. |
| B5 | PASS | icmp: "cannot model ACL match qualifier(s): icmp_type (acls.core1.PROTECT_SERVERS[2])", decidedBy that line. tcp→203.0.113.9:443: caveat names INET_RETURN[0] "permit tcp any any established". udp bypasses it. | Upheld: 6,500 traces, 0 violations. MGMT_IN[0] is unreachable by any real trace; the engine override of its `unevaluable:true` is O47's latent item. |
| B6 | PASS | 825 clicks over 111 distinct cites in 14 states: "0 Broken-evidence-chain alerts", 0 data-cite mismatches. 10 random mouse clicks: 10/10 resolved to sha `9580aa092d49…7f13089`, re-computed with `git cat-file blob … \| sha256sum`. | Upheld: census over 357 states, 733 distinct cites, "101 model, 632 bearer, 0 unresolved"; 52 path-addressable model cites match the source. Lead: collection-level cites get no projection qualifier (see Known issues). |
| B7 | PASS | "coverage \| 23/26 collected \| RIBs 2/26 (both shown incomplete) \| ACLs 1/26 \| centrality 25/44", inView and onTop at 1920, 1024, 768 and 390; under the palette the dialog restates the figures. | Upheld over 8 states × 9 viewports down to 320×640. |
| B8 | **UNPROVEN** | 3,080 traces: `counterexample().found` = 0, `isDefiniteDelivery` = 0, all UNDETERMINED. Rendered: "NEARBY FLOW WITH A DIFFERENT OUTCOME — NONE OFFERED". | The positive state exists only in fixture tests (O13). |
| C1 | **UNPROVEN** | `review/blind/KEY.json`: 12 entries whose keys are exactly `[id, sheetName, A, B, ours, reference, question, sheet]`; 8 of 20 sheets unkeyed; the craft sheet's reference shows "Forward AI" and a Storylane "Start" modal. `grep 'winner\|verdict'` under `review/blind`: nothing. | No blind verdict exists. Owner decision (O19). |
| C2 | **FAIL** (overturned) | First pass: "PASS capture app 32 of 32 frames rendered…", "PASS text 72 of 72 states free of clipped/broken text…", "PASS wrap 0 unjustified token-break licence(s)". Refuter: state 06 at 1440, both themes: "Trace a flow" and "Verify an intent" `visibleFrac 0.40625` under `scrollTop 19`; `l3_forwarding[3]` cut at the bottom edge. At 1920, `scrollTop 0`, `visibleFrac 1`. | A primary control sliced in half in a captured state. The app causes it: the panel scrolls itself 19 px on load and the tab strip is not pinned. The text gate does not measure this class (O17/O41/O44). |
| C3 | PASS | 03-finding-drill at 1920 and 1440: badge, id, device, title, category on every row. DOM census of 107 titles: at 1440, 78 clipped, 39 lose >20 %, worst 25 %; every clipped title keeps its subject. | Upheld on the refuter's own 03 capture. Narrow margin (O47's C3 depth). |
| C4 | PASS | Dark/light sheets of all 8 states; light severity badges `--sev-critical #8c1111` vs dark `#ff6b6b` (the inverse would be `#009494`); stage rgb(238,241,245) vs rgb(10,13,20); per-theme palettes in `tokens.css:134–167`/`289–310`. | Upheld. |
| C5 | **FAIL** | `node review/capture-motion.mjs` exit 3: every static and motion item PASS except "**FAIL** … dark/tier-fade-high-to-low-r3-nocopy: opacity fell 0.36 in one frame (frame 34; bar 0.25)". Frame 33 at t=400 ms opacity 1, frame 34 at t=516.6 ms (a 116.6 ms frame) opacity 0.64; that fade lasted 8 frames. | 1 of 24 fades. Not attacked (a FAIL). Not re-run to measure recurrence. Harness gaps: 12 light fades `compositeJudged:false`; log prints "drop@34 undefinedms". |
| C6 | PASS | `motion-inventory`, `tracked-sources`, `emphasis`, `stepdown.fadehold`: "Test Files 4 passed (4), Tests 125 passed (125)". 0 `@keyframes`; 13 transitions at 80/140/240 ms; `getAnimations()` `[]` at rest; idle canvas screenshots byte-identical (1874688 = 1874688). Tier fades 250–266.7 ms. | Upheld: frame-by-frame census at 1440 and 390 found at most 140 ms and 0 infinite animations. |
| D1 | PASS | Keyboard-only A1 (Ctrl+K, F099, Enter, 9 Tabs, Enter → "access13 Gi0/11 (err-disabled)") and A2 (trace 3389, focus to the ACL decider, Inspector opened and closed). `audit-d3-focus.mjs`: "2416 tab stop(s) walked, … 3044 operable element(s) censused by behaviour (0 with no role and no tabindex) … 0 failure(s)". | Upheld at 390×844. Every double-click handler has a keyboard equivalent. |
| D2 | PASS | Key-by-key at 1440 and 390: arrows, Home/End, PageUp/PageDown (7→17→27), Ctrl+Home/End (row 1 / 152), edge clamping, one `tabindex=0`, Tab leaves in one stop, Shift+Tab re-enters on the remembered cell. | Upheld; collapse 152→149 with contiguous `aria-rowindex`. |
| D3 | **FAIL** (overturned) | First pass: "547 case(s), 0 failed." / "1089 focus stop(s) checked for visibility, 0 not visible." Refuter, keyboard only at 1100/1024/1270: `in drawer at tab 20 drawer=open \| Finding [radio] inRailB=true` → `after e (inside drawer) drawer=null \| ... [BODY] inRailB=false y=0 x=0 w=1100`. Palette path: `drawer=null active=BODY inRailB=false`. | Focus is lost, invisible and not returned on both keyboard close paths; Escape does not close the drawer. The audit has no drawer case, so it passes (reproduced: 547, 0 failed, EXIT=0) with the defect present. |
| D4 | PASS | Rendered-pixel text contrast: 3,655 measurements over 28 state×theme runs, 0 below the requirement; lowest medians 4.60 light / 4.71 dark. All 36 selected states ≥64 px changing by ≥3:1. Form edges 3.85–4.09:1. | Upheld by a computed-style probe: 0 text under 4.5:1 (or 3:1 large); placeholders 5.70/5.91; sort glyphs 3.39/4.12. |
| D5 | PASS | 60 runs, 50,796 target measurements over 15 states × 4 viewports: no control under 24 px; only grid cells (rows ≥28 px, design-brief §3.2) and hidden SR treeitems. | Upheld. The cell exemption rests on the design argument; a stricter 2.5.8 reading could contest it. |
| D6 | PASS | `scene.pick()` every 3 px (66,539 calls) hit 26 devices and 44 links = `fabric.json`; the tree has 119 treeitems covering all of them; Space on L27 → `?l=L27`, Enter on access13 → `?d=access13`. | Upheld. Chromium AX tree only, no real screen reader. |
| D7 | PASS | `capture.mjs reduced` exit 0: "PASS D7: camera lands in one frame under reduce, 23 poses without it." A1+A2 under reduce: 0 running animations after 34 key presses; max duration 1 ms (control: 140 ms). | Upheld on a frozen production build ("cameraPoses=24"); source sweep found no ungated motion. The packet half is fixture-only. |
| D8 | PASS | Greyscale 03 and 06, both themes: C/H letters plus "Critical"/"High"; C/P/G*/E* bands; "?" + "not collected"; dashed vs solid links; "? UNDECIDED"; hatch + "not observed". | Upheld: bridges are double rails, port channels thick bands, down/unknown links distinct dashes. |
| E1 | PASS | Journey list in acceptance.md equals the `JOURNEYS` array (`measure-inp.mjs:425-815`); `journey-scope` + `tracked-sources`: 23/23. "acts with a verified effect 25 of 25" for J1–J4; J2-first 21/21; J2 anchors "26 of 26". | Upheld (23/23 again). |
| E2 | **FAIL** (overturned) | First pass: three `measure-inp` runs, each "7 pass, 0 fail, 0 NOT MEASURED" and "ACCEPTANCE EVIDENCE", worst p95 64 ms (J2-first). Refuter, J5 first open, fresh browser per trial, 1280×800: dark "p50 224 p95 320 max 352; over 200 ms in 11"; light "p50 272 p95 320 max 328; over 200 ms in 14"; both "HOST-ENV VERDICT: ACCEPTANCE EVIDENCE". | LABORATORY. J5 was only ever timed at 1920 in one browser already warmed by J1–J4. Control J4 first at 1280: p95 32, max 48. `ATLAS_ONLY=J5` (cold) rep 0: 96 and 80 ms vs 64 in the full run. |
| E3 | **FAIL** (overturned) | First pass: "E3 (no task over 50 ms on the interaction path): PASS — 7 clean, 0 violating"; across runs "(4 run(s), need 3): PASS". Refuter: trial 17 long tasks `[{"s":5,"d":83}]`, LoAF script `#document.onkeydown` in `mount-CKPrKj5u.js`, dur 54, forced style/layout 37; long task >50 ms in 6/20 (dark) and 9/20 (light) fresh loads, 3–9 ms after the Ctrl+K press. | LABORATORY. Ctrl+K is J5's own input. The grader independently saw the frame-level shape at 1920 (LoAF 54–66 ms, 0 blocking, O40). |
| E4 | PASS | `measure-fps.mjs` ×2, "PASS E4 focus flights: PASS — median 60 fps across 10 windows, worst window 60 fps (floor 45), host busy 6%"; orbit median 60, worst 60; canvas 1161×962, tier high, `acceptanceEvidence=true`. qualityReasons disclose the AO suspension. | LABORATORY, 60 Hz cap. Upheld (reproduced; full-bleed also PASS at 1021×497). "With a trace animating" cannot be established on this snapshot; the named substitute condition was used. |
| E5 | PASS | `audit-e5-coldload.mjs`: "PASS E5 3 cold loads: every animation frame over 200 ms coincided with a visible working affordance, and no keystroke exceeded 200 ms"; worst keystroke 168 ms. `audit-e5-sweep.mjs`: "PASS E5 sweep all 13 actions stayed under 200 ms in every one of 3 repetitions". | LABORATORY. Upheld (worst frame 108 ms); "Show the 3-D fabric" at 767 px added: no LoAF over 200 ms. |
| F1 | PASS | `tsc -p tsconfig.json`, `-p tsconfig.scripts.json` (with and without `--noImplicitAny`), `-p tsconfig.config.json`, all `--noEmit`, exit 0, no diagnostics. `comm -13` of tracked TS vs listed files: 0. | Upheld; 0 `@ts-nocheck/@ts-ignore/@ts-expect-error`. `review/*.mjs` excluded (O27). |
| F2 | **UNPROVEN** (overturned) | RUN 1 (09:24, host 85–100 % CPU): "Test Files 5 failed \| 158 passed (163)", "Tests 286 failed \| 3480 passed (3766)", exit=1. RUN 2 (10:02): "Test Files 163 passed (163)", "Tests 3766 passed (3766)", exit=0. Delegate: "PASS capture app 32 of 32 frames rendered…" twice. | One red and one green on the same bytes. `vitest.config.ts:12-13` rejects "re-run until green". One 37 s timeout in `self-removing-focus.test.tsx` cascaded into 277 failures ("the seeded flow had not been traced after 50 flush turns"). |
| F3 | **UNPROVEN** | `mutation-check.mjs` exit 0, 21 KILLED, no SURVIVED/MISATTRIBUTED/INVALID; "LIMIT: this does NOT recreate pre-fix history". `--history`: 13 of 21 guards "in root (no pre-fix commit)". | Red-before-fix unprovable for blast, layout, query, the compiler, forwarding §1.1/R19 and claims C3 (O34). |
| F4 | PASS | Scratch `vite build` "✓ built in 1.12s"; entry `index-oprldBec.js` 3.63 kB has no static import; `index.html` has no modulepreload; three only in `Fabric3D`'s dynamic import. 767×900: no three request in 6 s; clicking "Show the 3-D fabric" requested it at 15522 ms. | Upheld: identical chunk names; 15 cold loads at 767/390 px, 0 three requests; 12 at 1920/1024/768 request three after FCP (e.g. fcp=60, three@413). CSS and `useAtLeast` share one 48rem query. |
| F5 | PASS | `node tools/compile-snapshot.mjs` exit 0, `fabric.json` `a1a599b8…d251` before and after (mtime moved). Fresh clone of `7f67013`: all 4 compilers byte-identical; negative control `WS-C3850-XXX` changed the output to `b20c40f2…` and back. | Upheld: `provenance` + `tracked-sources` 32/32. Needs the parent blob at `../webapp` (O23). |
| F6 | PASS (refuter's evidence) | Refuter, frozen `vite build` on :4197: `node review/capture.mjs twice 5` → "verdict: F6 PASS: 32 of 32 frames byte-identical across 5 runs.", exit 0. | The grader's two-`app` diff (0 of 32 differ) did not meet the criterion's own `twice 5` rule; the refuter's run does. Dev server not measured. |

## What is proven

These 28 criteria were graded PASS and then survived a named, independent attack. Group E is
**laboratory** evidence on one reference host.

**Investigation (A3–A6).**
- **A3.** A blocked flow names the device, the list, the line (ordinal and 0-based cite) and the literal
  text, cross-checked against `fabric.json`. The refuter's 1,210-flow sweep found the only other denying
  line, INET_RETURN[2], and it renders the same way.
- **A4.** Device, finding, link and hop selections re-aim the other surfaces without narrowing the
  corpus, moving the camera or losing the queue row, at 1920 and 1440 (R106 holds). The refuter
  repeated it through the palette, the fabric tree, the canvas and a flow link.
- **A5.** Hover, selection, focus-to-device and Reset view are measured by the scene's own projections;
  Reset returns exactly to the fresh-load pose.
- **A6.** Blast radius is marked, cross-checked against `failure_impact`, and disagreements are stated.
  Across all 26 devices every articulation-point pixel diff (min 2.595 %) exceeds every collected
  non-partition diff (max 1.140 %), and the separation holds in the dark theme.

**Claim honesty (B1–B7).**
- **B1.** No absence renders as health: 130 device pages, never-collected hosts, no-RIB hosts, links
  and the palette predicates. Every display-relevant `?? 0` is unreachable or guarded.
- **B2.** Every verdict carries the "2 of 26 hosts" scope and caveats: 0 exceptions over 6,336 + 960 +
  3,080 (grader) and 28,090 (refuter) traces, and in the "Verify an intent" surface.
- **B3.** No trace through a no-RIB host is delivered (336 and 456 such traces, all indeterminate).
- **B4.** Off-subnet sources are out of scope in words (285 of 285; 16 edge sources × 3 flows).
- **B5.** An unevaluable line that could match is named and blocks the decision: 0 violations over
  6,500 traces.
- **B6.** Every displayed cite resolves: 825 clicks with 0 broken chains; 733 distinct cites with 0
  unresolved; the source digest re-computed from `git cat-file`.
- **B7.** The coverage figures stay on screen or are restated, from 1920×1080 down to 320×640.

**Craft (C3, C4, C6).**
- **C3.** Titles keep their subject; the worst loss is 25 % at 1440.
- **C4.** Both themes are separately authored, not inverted.
- **C6.** No keyframes, no transition over 240 ms, byte-identical idle frames, tier fades 250–267 ms.

**Accessibility (D1, D2, D4–D8).**
- **D1.** A1 and A2 complete keyboard-only at 1440 and 390; "3044 operable element(s) … 0 with no role
  and no tabindex".
- **D2.** The APG grid contract walked key by key at 1440 and 390.
- **D4.** Rendered-pixel text contrast and selected-state indicators meet their floors in both themes.
- **D5.** 50,796 target measurements: no control under 24 px outside the row-target exemption.
- **D6.** Every canvas-pickable device and link is in the DOM tree and keyboard-selectable.
- **D7.** "PASS D7: camera lands in one frame under reduce", on the dev server and on a production
  build.
- **D8.** Every encoding keeps a non-colour channel in greyscale.

**Responsiveness (E1, E4, E5). LABORATORY, on mains power, quiet host, build `5ccb42f6a09ed652`.**
- **E1.** The declared journeys equal the harness's journey ids, and every act had a verified effect.
- **E4.** Median 60 fps, worst window 60 fps, at 1.12 MPix, tier high; the AO suspension is disclosed in
  `qualityReasons`.
- **E5.** No cold-load frame over 200 ms; worst keystroke 168 ms; 13 sweep actions under 200 ms in 3 of
  3 repetitions.

**Engineering integrity (F1, F4, F5, F6).**
- **F1.** All type-check projects are clean and cover every tracked source file.
- **F4.** three.js is not on the first-paint path and never loads below 768 px without a reader action.
- **F5.** The compiled outputs are byte-reproducible from a fresh clone of `7f67013`, with a negative
  control.
- **F6.** "F6 PASS: 32 of 32 frames byte-identical across 5 runs" on a production build.

## What is not

### FAIL

**A1: configuration evidence for any finding.** Census over all 146 findings, classified by the first
evidence button: 6 "Show the configuration this finding names", 6 "Show the record that matches this
finding", 133 "Browse <host>'s collected records (context, not this finding's evidence)", 1 with no
button (F142). The 12 reach configuration in ≤3 interactions with no camera move and no scroll.
**Gap:** 134 of 146 findings have no configuration-evidence route, and the app itself says the route it
offers for 133 of them is not evidence. Not closable in Atlas Scope without per-finding record pointers
from the producer (O12).

**C2: no obviously-unfinished UI in any captured state (overturned from PASS).** The grader's gates were
green: "PASS capture app 32 of 32 frames rendered, settled on screen and at tier high", "PASS text 72
of 72 states free of clipped/broken text…". The grader looked at all 32 frames and excused one cut at
the bottom of state 06. The refuter found a worse cut at the top of the same panel. In
`{light,dark}/1440/06-path-blocked.png` the path panel's tab strip, "Trace a flow" / "Verify an
intent", shows only the lower part of its glyphs, directly under the SCOPE bar:

```
[{"t":"Trace a flow","top":65,"bottom":97,"portTop":84,"scrollTop":19,"visibleFrac":0.40625},
 {"t":"Verify an intent",…"visibleFrac":0.40625}]
```

At 1920, `scrollTop 0` and `visibleFrac 1`. In the same 1440 frame the citation `l3_forwarding[3]` is cut
at the bottom edge and `protocol_assessability.rows[123]` partly cut.

**Gap:**
- The panel scrolls itself 19 px on load to reveal the hop, and its tab strip is not pinned, so the
  panel's primary navigation is left unreadable in a captured state.
- The text gate does not measure scroll-edge cuts. O17/O41/O44 record the class as open with no
  detector, which is why its "72 of 72" is green.
- Measured on the :4180 dev server (the working tree equals HEAD for code). Whether a sliced tab strip is
  "obviously unfinished" is a judgement; the refuter holds that it is and this report applies it.
- Not recorded in `open-issues.md`.

**C5: the tier cross-fade (one item of the cheap-render checklist).** `node review/capture-motion.mjs`
against the fresh :4181 build exited 3. Every other item passed ("PASS z-fighting (1157 slow-motion
frame steps, 0 clusters ≥ ZF_CLUSTER)", "PASS LOD/effect/label popping (2695 still-frame pairs, 0 still
pops, 0 label blinks)", AO restores, edge sparkle, and every static tell at both tiers). The failing
line:

```
FAIL … dark/tier-fade-high-to-low-r3-nocopy: opacity fell 0.36 in one frame (frame 34; bar 0.25)
```

Frame 33 at t=400 ms read opacity 1; frame 34 at t=516.6 ms, a 116.6 ms frame, read 0.64. The fade
lasted 8 frames (250 ms), so it cut rather than faded. The other 23 fades took 250–266.7 ms with steps
≤0.2.

**Gap:**
- The product's hold, which should wait for ordinary frames before starting the fade, did not stop a
  heavy frame from landing on the fade's first frame.
- 1 of 24 fades, coinciding with two 116 ms host frames. The grader did not run a second pass, so
  recurrence is unmeasured. At `34bd435` a similar stall under 93 % CPU was set aside by a quiet rerun
  (O16); no such rerun exists here, and a FAIL is not attacked, so it stands.
- O16's heading says every C5 motion item passed at every earlier re-grade. This run contradicts that
  for `7f67013`.
- Harness gaps: all 12 light-theme fades report `compositeJudged:false`, so only their opacity trace was
  judged; the log prints "drop@34 undefinedms".

**D3: focus visible and returned on close (overturned from PASS).** At 1024–1279 px, Rail B is an overlay
drawer opened and closed by the `e` shortcut and the palette's "Toggle the evidence rail" command. With
focus inside the drawer, either close path hides the focused control and drops focus to `<body>`:

```
after e drawer=open | ...snapshot BUTTON inRailB=false
in drawer at tab 20 drawer=open | Finding [radio] inRailB=true
after Escape drawer=open | Finding [radio] inRailB=true
after e (inside drawer) drawer=null | ... [BODY] inRailB=false y=0 x=0 w=1100
```

The output was identical at 1100, 1024 and 1270 px. The palette path printed `after palette "Toggle the
evidence rail" (+1.5s): drawer=null active=BODY inRailB=false`. `drawer-1100.png` shows no focus
indicator anywhere.

**Gap:**
- Both keyboard close paths lose focus; Escape does not close the drawer at all.
- `review/audit-d3-focus.mjs` has no drawer case (a grep finds only ladder and layout commentary). The
  refuter re-ran it: "547 case(s), 0 failed", "1089 focus stop(s) checked for visibility, 0 not
  visible", EXIT=0, with the defect present. The audit's denominator is a hand-built case list that
  omits this surface.
- Dev server only. Not recorded in `open-issues.md`.

**E2: lab INP ≤200 ms at p95 per journey (overturned from PASS).** The tracked harness is green: three
runs, each "7 pass, 0 fail, 0 NOT MEASURED" and "ACCEPTANCE EVIDENCE: release build, hardware renderer,
quiet host.", worst p95 64 ms. But J5 (Ctrl+K, then Escape) is only ever timed at 1920×1080 in one
browser that has already run J1–J4 (`measure-inp.mjs:1114` launches one browser for every journey), so
its one first-open sample is warm and 24 warm reps dominate its p95. The refuter ran J5's exact act in
a fresh browser per trial at 1280×800, the reference machine's physical panel (`acceptance.md:137`),
under `review/host-env.mjs`:

```
J5 FIRST after load, 1280x800 dark: 20 trials; worst-interaction p50 224 p95 320 max 352; over 200 ms in 11; trials with a long task >50 ms: 6
HOST-ENV VERDICT: ACCEPTANCE EVIDENCE
J5 FIRST after load, 1280x800 light: … worst-interaction p50 272 p95 320 max 328; over 200 ms in 14; trials with a long task >50 ms: 9
HOST-ENV VERDICT: ACCEPTANCE EVIDENCE
```

Example: "trial 17: worst 352 ms (keydown delay 1 proc 2 pres 349)". Control with the same scaffolding:
J4 first swap+submit at 1280×800 gave p95 32, max 48, 0 over 200. `ATLAS_ONLY=J5 node
review/measure-inp.mjs` (J5 alone, cold browser) gave rep 0 of 96 and 80 ms against the full run's 64.

**Gap:**
- The first palette open after load is a journey act whose cost is hidden inside a warm p95. E3's
  evidence column created `J2-first` for exactly this shape; J5 never got the treatment.
- The probe (`scratchpad/refE/first.mjs`) is not the tracked harness, but it uses the harness's own
  host gating and was accepted by it. A third run was refused by host-env and is not counted.
- Whether the slow first open also occurs at 1920 in fresh browsers is unknown: two such runs were
  refused by host-env.
- LABORATORY. Not recorded in `open-issues.md` (O30 watches J5 under busy runs only).

**E3: no task over 50 ms on the interaction path (overturned from PASS).** The tracked verdict is green:
"E3 (no task over 50 ms on the interaction path): PASS — 7 clean, 0 violating", "(4 run(s), need 3):
PASS". In the same two accepted fresh-browser runs, J5's first Ctrl+K ran its keydown handler as a
long task:

```
trial 1:  long tasks [{"s":8,"d":53}]  LoAF {"d":65,"blk":7,"scripts":[{"inv":"#document.onkeydown","dur":53,"fsl":36,"src":"mount-CKPrKj5u.js"}]}
trial 17: long tasks [{"s":5,"d":83}]  LoAF blk 19, onkeydown dur 54, fsl 37
```

A long task over 50 ms occurred in 6 of 20 dark and 9 of 20 light fresh loads, each 3–9 ms after the
Ctrl+K press, with 34–37 ms of it forced style/layout inside the handler.

**Gap:**
- Ctrl+K is J5's own input, so this is on the journey's interaction path. The tracked harness cannot
  see it: it times J5 only at 1920 and only warm, and printed "J5-open-palette … longTasks>50ms=0" in
  the refuter's reproduction.
- The grader saw the same handler at 1920 as a 54–66 ms zero-blocking long frame (O40's shape); at
  1280 in a fresh browser it becomes a long task.
- LABORATORY.

### UNPROVEN

**A2: follow a flow hop by hop.** Depth 1 is shown with citations. The multi-hop half (a second hop's
decider, hop-to-hop navigation, the cable-map next-host branch, the TTL cut, the loop detector) has
never run on product data; the ratchet `expect(Math.max(...depths.keys())).toBe(1)` confirms the
snapshot yields only depth 1. Not closable in code (O34).

**B8: a counterexample affordance.** 3,080 traces: `counterexample().found` = 0,
`isDefiniteDelivery` = 0, `isDecidedOutcome` = 0. The negative state renders honestly. The positive
state ("headed 'Counterexample' with a decided counter outcome") exists only in
`decided-surfaces.counterfactual.test.tsx` and `engine.counterfactual.test.ts`, over fixtures. Nothing
to capture on this snapshot (O13).

**C1: blind critique.** `KEY.json` holds no verdict, winner, critic or reasons field; 8 of 20 sheets are
unkeyed; the sheets and key predate waves 3–8; the reference panel identifies itself ("Forward AI", a
Storylane modal). `review/REFERENCES.md` reports R1 32/33, R2 36/36 and R3 36/36 but says the count is
"NOT offered as proof of C1". **Gap:** no blind verdict, and not ≥2 independent critics per pairing.
Owner decision (O19).

**F2: `npx vitest run` green (overturned from PASS).** Two full runs of `7f67013`:

```
RUN 1 (09:24, host 85–100 % CPU): Test Files 5 failed | 158 passed (163) / Tests 286 failed | 3480 passed (3766), exit=1
RUN 2 (10:02, lower load):        Test Files 163 passed (163) / Tests 3766 passed (3766), Duration 463.82 s, exit=0
```

Each of the 5 red files passed alone (selection-origin 8/8, a4-surface-switch 33/33, DataGrid.act-view
19/19, composite-tabstop 105/105, self-removing-focus 405/405).

**Gap:**
- The PASS rests on re-running until green. `vitest.config.ts:12-13` says a gate whose verdict depends on
  host load "is not a gate … the remedy it teaches is 're-run until green', which is how a real red gets
  waved through."
- acceptance.md says F2's earlier load overturn was fixed by making no test wait on the clock. The red
  run contradicts that: one 37 s timeout in `self-removing-focus.test.tsx` was followed by 277 failures
  "the seeded flow had not been traced after 50 flush turns". The timed-out test leaves module-level
  `current`/`seeded` state (`:160-187`) that poisons every later test in the file — an isolation defect
  in the gate itself.
- The refuter did not reproduce the red (it avoided stressing a shared host). Its solo run of
  `self-removing-focus.test.tsx` passed 405/405 in 708.93 s at host LoadPercentage 96.
- The browser delegate is green: "PASS capture app 32 of 32 frames rendered, settled on screen and at
  tier high", twice, exit 0. The hollow-test search found nothing outside the declared classes. What is
  unproven is a stable green unit suite, not the delegate.
- acceptance.md's count is stale: 57 of 163 test files read the filesystem or source text, not 54 of
  159.

**F3: each refutation's defect reproduced red before its fix.** `mutation-check.mjs`: 21 KILLED, exit 0,
"LIMIT: this does NOT recreate pre-fix history". `--history` (18 commits, root `50a3dc5`): 13 of 21
guards "in root (no pre-fix commit)" — both blast mutations, all 5 layout, query, both compiler,
`fwd-null-port-compared`, `fwd-counterfactual-cites-generator` and `claims-c3`. **Gap:** for those, a
mutation kill shows the test detects the defect's shape today, not that it was red before the fix. The
historical R17 and claims C2/C3 reds were not re-run at this grade. `refutation.md` §7 still lists "the
compiler refuted for what it drops, not what it transforms" as open (O34).

## What was not examined

Collected from each grader's and refuter's own statements.

**Cross-cutting**
- Nothing was run from a fresh clone of `7f67013` except F5's compilers. Every vitest run, every capture
  and every browser measurement used the working checkout or a build of it (O23).
- The dev server (:4180), not a production build, carried all of A, B and D, the C2 overturn and most
  of the D refutation. C, E, F4, F6 and the D7 refutation used production builds.
- Other agents shared the host, the dev server and the Browser pane throughout. Timing-sensitive
  readings in hidden or starved tabs may be affected; the drivers named above are the ones observed.
- No real screen reader, no second machine, no second browser engine, no forced-colours pass, no field
  data.

**A**
- The A1 literal-versus-parsed census (2/143/1) was not re-derived; it rests on
  `EvidencePane.namedconfig.test.ts` being green.
- Dark theme, and every viewport other than 1920 by hand (768 and 390 only through the probe). The
  refuter did not re-run the 768 dev-server settle residual or the O48/O49 limits.
- The evidence pane's own scroll position across selections.
- The colour of the cut-point mark against the down colour.
- The A6 pixel diff at tier high or on the hardware GPU (both graders used SwiftShader tier low).
- The recorded capture files; the A2 multi-hop fixture `multihop.test.tsx`.
- Whether a trace submit may move the camera (it did: core1 (474,82) → (552,237), O47; not graded).
- With a flow active the Blast radius button read "core1 strands 0 (uncertain; 0 under the all-nodes
  projection)"; without it, "core1 strands 9". Not resolved as hop scope or inconsistency.
- The settle-time A4 probe copy and the A6 script exist only in scratchpads.

**B**
- On-fabric trace colours and label bands under motion; O6 (bloom halos).
- O44 (a copied trace reading as decided through the WeakMap identity).
- The timeline surface; the "Verify an intent" tab was swept for scope by the refuter only.
- Link citations beyond L0, L33 and L35; `blast.ts:2084`'s fallback cite was not planted.
- Device sweep and citation click-through at 1920 light only.
- Malformed `l=`/`d=` URLs.
- No planted-null mutation against the compiler (O36 judged latent by absence).
- Whether the B tests failed before their fixes.
- The refuter did not verify 48 `[key=value]` selector cites against the source, did not sweep the
  Evidence Raw tab for every device, CSV/share exports or other palette predicates, and did not drive
  B2's live region or `sharePayload` at runtime.

**C**
- Compact queue density; C2–C4 at 390, 768 and 1024 px (the text sweep covered 390 for words only).
- A mutation check of `motion-inventory.test.ts`.
- Reduced-motion behaviour for C; the packet-marker loop (never runs on this snapshot).
- Hover-rim and selection-ease durations at runtime.
- A second `capture-motion` run to measure how often the cross-fade FAIL recurs.
- The C refuters did not re-measure all 107 titles for C3 and viewed only a subset of the 32 frames for
  C4; they did not test the C6 tier cross-fade timing at runtime.

**D**
- No production build for any D criterion (the D7 refuter alone used one).
- D4 text contrast at 1440 only; overlays at 390 and 768 not re-measured.
- D4 non-text: icon glyphs and 3-D scene marks (link and cable colours, WebGL rings).
- Forced-colours mode (R99 has no unit pin).
- The D3 audit never sets a colour scheme; the dark-theme focus trace covered only the palette, the
  keyboard reference, the snapshot popover and the Inspector. The drawer was not traced by the grader.
- O41's partial ring at 768 beyond the audit's sweep.
- Cross-layer grid keys and the Inspector's record grids.
- The D refuters did not rerun the pixel-plate harness or the 66,539-call pick sweep, did not orbit to
  non-default camera poses for D6, and did not check D8 surfaces outside states 03 and 06.

**E**
- All E evidence is laboratory: one machine, scripted input, 60 Hz cap, no field INP. Headroom above
  60 fps and cost inside one vsync are invisible.
- Nothing was measured at 1920×1080 as the render target (canvas 1161×962). "With a trace animating" was
  never measured: 0 non-converged frames in 5 s with a flow active.
- E4 under the dark theme or at 1280×800 (`measure-fps` has no knob for either); reduced motion.
- J1–J3 at viewports and themes other than 1920 light and 1280 light/dark.
- Whether J5's cold first open is slow at 1920: two fresh-browser runs showed opens at 216–280 ms but
  were refused by host-env and are not counted either way.
- J5's per-rep effect cannot be checked inside the loop.
- The E3 across-runs verdict pools one earlier record of this build hash (04:15Z).
- The harnesses rewrote `review/reports/inp.json`, `fps.json`, `e5-coldload.json`, `e5-sweep.json` and
  added `inp-e3-history` records.

**F**
- A per-test audit of all 163 test files (two AST heuristic scans plus about 12 tests read).
- The exact mechanism of the flush-turn cascade.
- The historical red-before-fix checks (R17 against `50a3dc5`, claims C2/C3 against `254694b`).
- F4 at fractional widths (the refuter relied on the shared 48rem query) and a harness cold load for
  F4(c).
- F6 on the dev server.
- The F refuters did not rerun the full suite or stress the host to reproduce F2's cascade.

## Known issues carried forward

Reconciled against `docs/open-issues.md` (working-tree version, uncommitted; its Open section begins at
line 3076).

**New; not yet recorded in `open-issues.md`**

1. **C2 — the path panel's tab strip is sliced at 1440 in state 06 (FAIL).** The panel scrolls itself
   19 px on load to reveal the hop and the tab strip is not pinned: `visibleFrac 0.40625` for "Trace a
   flow" and "Verify an intent", both themes; `l3_forwarding[3]` cut at the bottom edge. Evidence:
   `scratchpad/ref2/shots/app/`, `tabclip-{light,dark}.png`, `botclip-light.png`, `tabs.mjs`. Owner: the
   path panel's reveal and `PathTrace.css`; the text detector (O17/O41/O44 class) still has no
   scroll-edge case.
2. **D3 — the evidence drawer drops focus to `<body>` on close (FAIL).** 1024–1279 px, by `e` and by
   the palette's "Toggle the evidence rail"; Escape does not close the drawer. Evidence:
   `scratchpad/r/drawer.mjs`, `drawer3.mjs`, `drawer-1100.png`. Owners: the Rail B drawer and the focus
   return owner that R57 introduced; `review/audit-d3-focus.mjs` needs a drawer case, and its case list
   is the "named subset standing in for the class" shape.
3. **E2/E3 — the first palette open after load, in a fresh browser at 1280×800 (FAIL).** p95 320 ms;
   `#document.onkeydown` long tasks 51–83 ms with 34–37 ms forced style/layout. Evidence:
   `scratchpad/refE/first.mjs`, `first-j5-1280-{dark,light}.txt`. Owners: the palette's keydown handler
   (`mount` chunk), and `review/measure-inp.mjs`, which needs a `J5-first` fresh-browser journey and a
   1280×800 leg.
4. **C5 — one tier cross-fade cut at `7f67013` (FAIL).** "opacity fell 0.36 in one frame (frame 34;
   bar 0.25)" on a 116.6 ms frame; the fade hold did not exclude it. Harness gaps: 12 light fades
   `compositeJudged:false`; "drop@34 undefinedms". Owners: the fade hold (`stepdown` / `scene.ts`) and
   `review/capture-motion.mjs`. Contradicts O16's "every C5 motion item PASS".
5. **F2 — the suite's verdict depends on host load (UNPROVEN).** One 37 s timeout cascades into 277
   failures through module-level state in `self-removing-focus.test.tsx:160-187`; the "50 flush turns"
   waits are not load-independent. acceptance.md's "54 of 159" filesystem-reader count is stale (57 of
   163). Owners: `self-removing-focus`, `selection-origin`, `composite-tabstop`, `DataGrid.act-view`,
   `PriorityQueue.a4-surface-switch`, and `vitest.config.ts`'s timeout policy. Note R85 marked the
   load-sensitive files FIXED.
6. **A4 lead (refuter, not graded).** From `?d=access5&tab=ports`, clicking F001 (names core1 only) left
   the Device pane on access5 and switched it to a Findings tab that does not list F001
   (`hasF001=false`), dropping the reader's Ports tab for nothing. Also: a flow link with no `d=` selects
   core1 in the pane but the URL never gains `d=`; `reaim-tab-and-restore` failed once at 16.4 s under
   load; at 768 on the dev server the reveal needs more than the probe's 700 ms settle.
7. **B6 lead — R95's fix is narrower than its title.** `projectsSource` is keyed on "some compiled record
   carries this cite", so collection-level cites (`routes.core1`, `routes.core2`, `acls.core1`; 17 of
   825 clicks) read "resolves directly inside the compiled model" with no projection qualifier, though
   they are real source paths whose shape differs (snake_case, `""` vs camelCase, null). Compiled
   `devices[].impact` drops the source's `off_scan_gw_vlans`. The Raw tab says "open it to check the
   compilation itself", but it can only open the compiled record. Owners: `Inspector` citation
   resolution and `tools/compile-snapshot.mjs` (bears on O9).
8. **A3 residual.** At 1920 the INET_RETURN[2] literal line sits at y=695 inside a panel clipped at
   y=537; the auto-scroll (scrollTop 6416) stops short. Owner: the path panel's reveal (same family as
   item 1).
9. **A6/blast lead.** With a flow active, the fabric's Blast radius button reads "core1 strands 0
   (uncertain; 0 under the all-nodes projection)"; without it, "core1 strands 9". Unresolved whether
   this is hop scope or an inconsistency. Owner: `blast.ts` and the fabric header.
10. **B1 design note.** An L3 row whose risk reads "object tracking NOT assessed" keeps the producer's
    "Info" chip (`DevicePane.tsx:160-171`, dist1 VLAN 40, `l3_forwarding[5]`), while physical rows with
    the same pattern render "not graded". Judged, not overturned.
11. **B5 wording.** For the INET_RETURN flow the claim sentence gives the unfollowable next hop as the
    reason; the blocking established line appears only in the caveat and `decidedBy`.
12. **Harness and method notes.** F6: Node's fetch refuses port 4190 as a "bad port", so the harness
    labelled the server "mode=unknown" (Chromium loaded it); pick another port. A5: in headless builds a
    canvas click took 3.4–4.0 s to reach the URL, and after Reset core1 reported `visible:false` at the
    coordinates where it read true at home. D2: the active finding is marked `aria-current=true`, not
    `aria-selected` (not a contract break). C2 observations: the queue placeholder "severity:Critical"
    sits beside the active Critical/High chips; the status bar's "claim strength" is a legend button
    (`StatusBar.tsx:315`) styled like a key label with no value.

**Existing items: status after this grading**

- **O12 (A1):** confirmed exactly: named 6, matched 6, context 133, none 1. Not closable in Atlas Scope.
- **O34 (A2, F3):** both UNPROVEN again; F3's 13 of 21 root guards confirmed.
- **O13 (B8):** confirmed: 0 counterexamples in 3,080 traces.
- **O19 (C1):** unchanged. Owner decision.
- **O25 (E evidence at `7f67013`):** its condition, "until that grade reports", is met — and the grade
  is not a pass. E1, E4 and E5 PASS with acceptance-grade laboratory evidence on mains power; E2 and E3
  FAIL on the cold J5 open (new item 3). O25 should not be closed as "met".
- **O30 (J5 watch):** the watch's premise, that quiet runs settle it, does not hold for the cold
  condition. At 1920 warm it is clean in 3 of 3 grader runs; at 1280×800 in fresh browsers it puts a
  51–83 ms task on the path in 6–9 of 20 loads (new item 3).
- **O40 (long task vs LoAF):** still open. The grader's LoAF probe found a 54–66 ms zero-blocking frame on
  J5's first open at 1920 in 3 of 3 fresh pages; the E3 axis for J1–J5 counts long tasks only.
- **O31:** the inconsistency is confirmed in code (`measure-inp.mjs:1188-1189` waits for `canvas` then
  2500 ms); the symptom did not recur (J2 25/25 in every run).
- **O16 (C5):** contradicted for `7f67013` by the cross-fade FAIL (new item 4). The mid-motion tier
  change and the cluster-rule wording remain owner decisions and were not exercised.
- **O17 / O41 / O44 (scroll-edge cut):** the bottom-edge cut in state 06 is reproduced (dark/1920:
  "Under the collected RIBs of core1 and core2 only (2 of 26"), and a top-edge cut of the tab strip at
  1440 now fails C2 (new item 1). O44's placeholder-ink observation reproduced (rgb(130,141,160) vs
  rgb(232,236,242)). Compact density still ungraded.
- **O36 (B1 latent):** confirmed latent: compiled findings Critical 3 / High 104 / Medium 33 / Low 6 and
  cross-layer Critical 2 / High 40 / Medium 1, no Info.
- **O47:** the MGMT_IN[0] override stands (B5); `blast.ts:2084`'s fallback was not planted; the camera
  move on trace submit was observed again (A) and still not graded; C3 depth consistent (39 of 107 over
  20 % at 1440; worst 25 % by the grader's method vs O47's 32 %).
- **O48:** the 390 probe still cannot select L33 (A). The F4 forced-scale limitation was not revisited;
  the refuter relied on the shared 48rem query. Wave 8's probes remain mostly untracked.
- **O49 (owner decision):** reproduced at 768 and 390 (the queue port is off screen after the Path
  switch). Not decided here.
- **O23 (clean clone):** advanced for F5 only (all 4 compilers from a clone of `7f67013`). A–E, F1–F4 and
  F6 did not run from a clone of `7f67013`. The `../webapp` parent-blob dependency is unchanged.
- **O20 / O35 (E5 margin):** not reproduced; worst keystroke 168 ms, worst frame 147.2 ms (grader) and
  108 ms (refuter). Keep open as a margin watch.
- **O21 (E3 outside the journeys):** "path trace: seed a flow by navigation" worstLoAF 83.5, 67.1 and
  83.3 ms; still the only sweep action over 50 ms, and a navigation outside E3.
- **O27:** still open; `review/*.mjs` is in no type-checked project, including every harness this grade
  relied on.
- **O29:** still open; tracked tests cite gitignored `review/_*` scripts.
- **O22:** still open (name-keyed determinism gate); no failing case.
- **O9:** unchanged in substance; new item 7 narrows R95.
- **O28:** not exercised; the A1 census used pushState+popstate.
- **D4/D6 leads already recorded:** the palette's search input has no boundary of its own (1.0:1 light /
  1.17:1 dark); the fabric tree's item names do not carry the trace verdict or stranded marks (available
  elsewhere in the DOM).
- **Wave-8 fixes marked FIXED:** R106 (A4) holds at 1920/1440; R103 (F4) holds; R104 (C2 wrap licence)
  holds ("PASS wrap 0 unjustified token-break licence(s)") but C2 fails in another shape (new item 1);
  R105 (D3 at 390) holds (0 failures in the audit) but D3 fails in another shape (new item 2); R107 (J2
  aim) holds ("26 of 26"). R108 (the 06 manifest note) was not examined.
- **Not examined by this grading:** O6, O7, O8, O11, O14, O33, O42, O43, O45 and O46.
