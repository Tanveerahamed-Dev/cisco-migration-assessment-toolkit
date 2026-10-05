# Atlas Scope — Acceptance Report

Graded 2026-10-02/03 against `docs/acceptance.md`. First-pass graders measured HEAD `de6b9b76`; the
refuters measured `ad3d7c25` and `2dd95d74`, which only merge `origin/main` into this branch.
`git diff --stat de6b9b76 HEAD -- .` inside `atlas-scope/` printed nothing for every refuter, and printed
nothing again when this report was written at `2dd95d74`, so every reading below is of the same
`atlas-scope` tree. `git status --short` was clean before and after each grader and refuter. No product
file was edited by any of them; their scratch lives in the git-ignored `.local-data/` and in session
scratchpads.

The data under test is the compiled sample bound to `webapp/sample_data/sample_fleet.snapshot.json`:
`sourceSha256 e63d7fac…9dd7`, 3,333,301 bytes, git blob `e01fd01b`. The F5 grader recompiled it and
`cmp` found all four compiled files byte-identical to the tracked ones. That snapshot is not the one the
previous grade used (`3934281b…`). It now has RIBs on 4 hosts, a reachable depth-2 path (dist1 → core1),
140 findings and 587 engine evidence pointers.

**How the grade ran.** One first-pass grader per criterion for groups A–D and F, and one grader for all
of E. Then one independent refuter attacked every first-pass PASS. All 28 PASS verdicts were attacked; the
list of PASS verdicts never attacked is empty. One refuter (A2's) died and returned nothing; its retry ran
and returned, and only the retry is used. Refuters attack PASS verdicts only, so the 9 first-pass FAILs and
2 first-pass UNPROVENs stand as graded.

**Where the first pass and the refutation disagree, this report applies the refutation.** Every overturn
below came with its own proof: a named script, its printed output, and the source lines or frames it rests
on. None is applied on argument alone.

**Host contention was severe and is part of the evidence.** Up to ~40 graders and refuters shared one
Windows host (Intel iGPU, ANGLE/D3D11). Refuters recorded 48–51 node processes and 12 headless Chromium
shells at once, and another session's `pytest -n auto` ran at ~85 % CPU for part of the E window. This
matters for F2, F6, C2, C5 and the E group; each entry says where a verdict depends on it. Timing figures in
group E are LABORATORY figures and are only cited as acceptance evidence where `host-env` printed
"ACCEPTANCE EVIDENCE".

## Verdict

**Atlas Scope is not ready for acceptance at `2dd95d74`.** 24 of 39 criteria FAIL and 3 are UNPROVEN.
12 PASS, and every one of those 12 survived an independent attack. There is no averaged score.

The failures are not concentrated in one place. Every group has at least one:

- **A (the task loop): 5 of 6 FAIL.** At the reference machine's own 1280×800 panel, 203 of 587
  engine-record activations need a scroll (A1). A named blocking ACL line can depend on which gateway the
  flow enters, while the product says it does not (A3). At 768 and 390 the selected row is left off screen
  (A4). Every core2 → core1 trace frames itself so that both hosts and the verdict mark are off-canvas
  (A5). At 390×844 the blast-radius marks are covered or scrolled away while the HUD says "all 9 marked"
  (A6).
- **B (honesty): 6 of 8 FAIL.** Each is a case of absence or uncertainty shown as something firmer:
  - B1: never-collected routing-protocol health is folded into core2's "Good (partial)" band without being
    named.
  - B2: the 3-D "✓ DELIVERED HERE" label carries neither scope nor caveats.
  - B3: a snapshot whose RIB is `null` or `[]` compiles to a "collected" empty table, and traces through it
    come out "dropped", not indeterminate.
  - B5: the trace names the wrong blocking line.
  - B6: "N bindings observed" cites a table that holds no binding field.
  - B7: a host the engine itself marks "not collected" is counted as "answered the collector".
- **C (craft): 4 of 6 FAIL, 1 UNPROVEN.**
  - C2: state 08 shows an amber over-budget chip, "Quality high · 181/176 draw calls".
  - C4: the 3-D state rings keep the previous theme's colours after a live theme switch (1.87:1 against the
    light ground).
  - C6: stepping hops restarts the "bounded" packet loop.
  - C1: no blind-panel verdict counts.
- **D (accessibility): 5 of 8 FAIL, 1 UNPROVEN.**
  - D1: 122 cite buttons cannot be reached by keyboard.
  - D2: `aria-sort` flips between ascending and descending over an identical row order.
  - D4: receded "ghost" chassis drop to about 1.9:1.
  - D5: 44 of 44 cable pick targets are under 24 px, with no stated exemption.
  - D3: still has no complete audit run.
- **F (engineering): 3 of 6 FAIL, 1 UNPROVEN.**
  - F3: `mutation-check.mjs` exits 1.
  - F4: the 3-D chunk loads below 768 px at a 12 px default font, and does not load above 768 px at 20 px.
  - F6: `twice 5` exits 3, because the tier and frame-rate chrome depend on the host clock.
  - F2: no fully green run of both legs was obtained on this tree.
- **E (performance): 3 of 5 FAIL.**
  - E3: the quiet-run verdict across runs is FAIL.
  - E4: the fabric can present about 1 fps while every signal reports 60 fps.
  - E5: with 8 cold loads, keystrokes reach 312 ms.

**Read the movement since the last grade carefully.** The previous grade had 6 FAILs; this one has 24. That
does **not** show 18 regressions, and this grade did not test the earlier tree, so it cannot say how many
are new. Three things changed together:

1. **The data.** The new snapshot opens depth-2 paths and core2 ingress. That is what made A2 and B8
   gradable, so both now PASS, and it is also what exposes A5's core2 framing and A3's ingress-dependent
   line.
2. **The grading.** Each criterion had its own grader and its own refuter, where the last grade used one
   per group.
3. **The attacks.** Refuters went outside the denominators the earlier grades measured: other viewports
   (A6 at 390, A1 at 1280×800), other input spellings (B3 `routes: null`, B7 an empty capture folder, B5
   protocol `ip`), live state changes (C4 theme switch, C6 hop stepping, E4 typing during a flight), user
   settings (F4 browser font size), and more samples (E5 `ATLAS_RUNS=8`, F6 `twice 5` on a busy host).

The recurring shape is the one the last report named: **every overturn sits just outside the denominator of
the gate or the sample that reported green.**

## Scorecard

Overturns applied, all from PASS: A3, A5, A6, B2, B3, B5, B7, C4, C6, D2, D4, F4, F6, E4 and E5 to
**FAIL**, and F2 to **UNPROVEN**. Upheld after attack: A2, B4, B8, C3, C5, D6, D7, D8, F1, F5, E1, E2.

| Criterion | Verdict | Evidence | Note |
|---|---|---|---|
| A1 | **FAIL** | Own Playwright probe, 3 interactions per finding with no auto-scroll. 1920×1080: 140 of 140 findings and 587 of 587 activations reach the record. **1280×800: 203 of 587 activations across 11 findings fail** (F122, F124, F126–F128, F130, F136–F140); "F136 chip 'access1 Gi0/1' leaves 9 px of a 566 px record visible". 1280×720: 426 of 587 fail. | First-pass FAIL, not refuted. Contradicts R120's "the verifier reproduced 1280×800 (0 failures)". Literal configuration text is reachable for 3 of 140 findings; 83 reach only rows the pane labels "not configuration". |
| A2 | PASS | Path form, tcp 10.0.40.50→10.0.10.50:22: "Hops (2)", dist1 Gi1/0/3 → 10.0.140.1 → core1 (`routes.dist1[1]`), then core1 delivered on Vlan10 (`routes.core1[2]`). Ratchet `{0:2574, 1:343, 2:332}` reproduced. | Upheld (retry refuter). 54 of 54 endpoint-to-endpoint traces name every hop's decider. 0 loop or TTL verdicts and 0 cable-map next-host resolutions on this data. |
| A3 | **FAIL** | Refuter: tcp 10.0.20.50→10.0.30.10:22 names "PROTECT_SERVERS line 4 of 4 (acls.core1.PROTECT_SERVERS[3])" and says the core1-ingress alternate "ends the same way there … so this result does not rest on that choice". `evaluateAcls("core1", …, {ingress:"Vlan20", egress:"Vlan30"})` gives "VOICE_FILTER line 3 of 3 … acls.core1.VOICE_FILTER[2]". | Overturned. `engine.ts:2741` compares only `at.outcome === t.outcome`. The flow is labelled PARTIAL; the decided multi-hop denial is correct. |
| A4 | **FAIL** | 1920 and 1440: "55 ok, 0 bad". Tracked probe: "22 applicable step(s), 0 OUT, 5 with the queue off screen … verdict: FAIL". At 768 the selected F026 row is at y 1153 in a 1024 px viewport after the Queue radio; at 390 it is at y 9702. | First-pass FAIL, not refuted. O49 (owner decision) is still open. |
| A5 | **FAIL** | Refuter `r7-frame-sweep.mjs`: "flows 74 with a hop host off-canvas 20". Every 10.0.20.x source: `{"hosts":{"core2":false,"core1":false},"labelsShown":1}`. After a reset, the UNDECIDED ring sits on core1 (last hop) and the "? UNDECIDED" chip on core2 (first unresolved hop). | Overturned on the trace clause only. Selection, hover, focus and reset reproduced (reset error 0 px). |
| A6 | **FAIL** | Refuter at 390×844, `d=core1`: `CUT core1 … unoccluded=0/10 … fabric3d__hud\|fabric3d__quality`, access10 and access12 stranded marks 0/10, while the HUD reads "core1 strands 9 … · all 9 marked". A core2 canvas click scrolls 2,325 px: `"canvasOnScreenPx":0`. | Overturned. At 1440×900 the rule holds: smallest articulation-point diff 2.863 % against largest non-articulation diff 1.354 %. |
| B1 | **FAIL** | core2 Summary reads "88 Good (partial) — score does not reflect: ACLs (none collected)", while `rib-evidence.json` marks core2's OSPF, BGP and EIGRP `not_collected` (`protocol_assessability.rows[129–131]`). | First-pass FAIL, not refuted. `band-qualification.ts unassessedScoringDomains` asks whether a host has *any* protocol_health row. |
| B2 | **FAIL** | Refuter at 1000×800 on the Evidence surface: label "core1 C ✓ DELIVERED HERE", card `display=none hidden inert`, `scopeVis 0`, `cavVis 0`. The only scope text left is the 1-px `#sr-log`. | Overturned. R69 lists "the 3-D chips" as outside its guard. The criterion text still says "2 of 26"; the data has 4 of 26. |
| B3 | **FAIL** | Refuter: `routes.core1: null` (also `[]`, prefix-less entries, `"not_collected"`) compiles to `routes.core1 = []` and `hasRib(core1) = true`. Traces give "outcome=dropped … unmodelled=[]". In the static-router variant, 30 decided drops through `isDecidedOutcome`. | Overturned. "Never delivered" still holds. `validate-snapshot.mjs` does not check `routes`, and the in-app upload path accepts the input. |
| B4 | PASS | Owner test 3 of 3 including the golden tier. Refuter: 120,144 off-subnet flows gave `{"out-of-scope\|outside-observed-subnets\|true":120144}`; the "lies in no subnet" sentence is visible at 375/768/1280/1920 in both themes. | Upheld. |
| B5 | **FAIL** | Refuter: ip flow 10.0.10.50→10.0.30.20 gives "decidedBy=acls.core1.PROTECT_SERVERS[0] … line 1 of 4 cannot be evaluated", but `lineEvaluability` says [0] is evaluable. The unevaluable echo-reply line [2] is "mentions PROTECT_SERVERS[2]: false". | Overturned. `runLists`' `poisonedBy ??=` treats an underspecified flow the same as an unevaluable line. The first-pass oracle repeated that logic. |
| B6 | **FAIL** | "dist1: 0 interface ACL bindings were observed across its 8 interface records (interfaces.dist1)" opens `fabric.interfaces.dist1`, whose keys hold no ACL binding field. The counted records are `acl-bindings.json#hosts.dist1` and are not reachable. | First-pass FAIL, not refuted. `engine.ts:1141` filters per-interface cites through the model-path-only `resolveCite`. Secondary: 5 cites skip the R95 projection caveat. |
| B7 | **FAIL** | Refuter ran the real engine `--no-collect` with an empty capture folder (`deadsw`): `collection_completeness … "complete": 23, "partial": 1, "not_collected": 1`. The app shows "coverage 25/28 collected" and "25 of 28 devices answered the collector". | Overturned. `compile-model.mjs:975` sets collected from record presence; `StatusBar.tsx:121` counts it. The RIB, ACL and visibility halves hold (720 checks, 0 fails). |
| B8 | PASS | Multi-hop denial shows "Counterexample — the nearest flow that behaves differently", tcp 10.0.40.50 → 10.0.20.10:22 DELIVERED (`routes.core1[4]`). Sweep: 492 decided refusals, `counterexample().found` 492/492. Refuter's 13×62×6 sweep: 322/322, `notFound: 0`. | Upheld. O13's "never renders on real data" is now false. |
| C1 | **UNPROVEN** | `node review/blind-pair.mjs --validate`, exit 0, 171 self-tests ok, RULE v8 (`6066a0400b1a`). Every pairing: "UNPROVEN … 4 uncounted verdict(s) may pick the reference". "C1 overall: UNPROVEN". | First pass, not refuted. 20 of 20 critics recognised a reference product; every line has `reasons` as a string; the panel was bound to `14f81dc4`. Side-mapped picks: the reference 4-0 on composition, typographic craft and colour discipline (12 losses); ours 4-0 on information density and network visualisation. |
| C2 | **FAIL** | `capture.mjs text`: "PASS text 90 of 90". In all 8 frames of 08-path-indeterminate the HUD reads "Quality high · 181/176 draw calls" in amber. `index.json` drawCalls 179–181. | First-pass FAIL, not refuted. Contradicts R14's "Re-measured after the fix, all states: `overBudget: false`". The F2 and F6 refuters saw state 08 also step down to tier "balanced". |
| C3 | PASS | 03 capture "PASS capture app 4 of 4". DOM probe over 102 Critical+High rows: 1440 → 79 clamped, 39 lose over 20 %, 0 over 50 %, worst 25–27 % (F077–F084 keep "OSPFv3 10.0.0.9 state EXSTART/- degraded"). | Upheld. Compact density fails (O17). The refuter found a new defect with all Display columns on (see Known issues). |
| C4 | **FAIL** | Refuter: after the real Light/Dark control, a ring pixel reads fresh (100,118,111), toggled (161,179,171), reloaded (100,118,111): 4.1:1 against 1.87:1 on the light ground. Canvas diffs in every one of the 8 states, only in the device rings. | Overturned. `scene.ts applyTheme` sets `instanceColor.needsUpdate` on `stateRings` but never calls `stateTint()` again. |
| C5 | PASS | Motion run 2 EXIT=0: z-fighting 0 clusters over 1,236 steps, sparkle worst 35 px (bar 120), 0 pops over 2,655 pairs, 24/24 fades. `probe-fabric.mjs --hairline`: "VERDICT: no sub-2 px hairline on the fabric". | Upheld. Motion run 1 on a contended host exited 4 (AO UNPROVEN, no FAIL), so the motion gate depends on host load. |
| C6 | **FAIL** | Refuter `hop-probe.mjs`: "AFTER-] (next hop) changes: 80 first 30 last 4142". Alternating `]`/`[` every 1.5 s kept the canvas moving for 14 s. `flow.setTrace` re-arms the packet and draw-on on every `hopIndex` change (lines 642, 652–654). | Overturned. Contradicts `flow.ts:634-635` ("never re-runs the draw-on") and design-brief §4.8. |
| D1 | **FAIL** | `multi.mjs` at `?d=core1&tab=ports`: from the cell, none of Tab, arrows, Shift+Tab, Enter, Space or F2 reaches "Open source record physical_health[78]". A mouse click opens it. 122 such cells on 23 devices. | First-pass FAIL, not refuted. `DevicePane.tsx:414` focuses only a cell's first control. A1 and A2 can be completed by keyboard. |
| D2 | **FAIL** | Refuter `r5.mjs`: Severity Enter #1 `Sev=ascending … rowOrderHash=1a80434a95`, #2 `Sev=descending … rowOrderHash=1a80434a95 (identical)`. Control: ID descending → `a34e419127`. | Overturned. Groups come out in fixed `SEVERITY_ORDER`; `DataGrid.tsx:2136` still sets `aria-sort`. PageDown skips 3–12 rows unseen. |
| D3 | **UNPROVEN** | The latest `audit-d3-focus.mjs --sweep` (at `14f81dc4`): "STOPPED" after ~78.5 min with no EXIT line. Bounded probes on this head: palette and help modal cycles, escaped=0, focus returns to the invoker. | First pass, not refuted. Needs a complete sweep with an exit code (O68); an owner instruction bars further runs on this host. |
| D4 | **FAIL** | Refuter, light 1440×900, median fill against ground: ghost AP-floor3-01 4.30 with nothing selected, **1.98** with `d=core1`, **1.89** on an indeterminate path. Collected dist2 4.42 → 1.72. Dark lowest ghost 3.13. | Overturned on non-text state indicators. Text reproduces: lowest 4.60:1 light, 4.71:1 dark. render-decisions §9 calls the ghost fill a D4 indicator. |
| D5 | **FAIL** | `picks.mjs` at 1440: "70 distinct pick targets hit (26 devices, 44 links); targets whose hit area cannot contain a 24x24 square: 46 (devices 2, links 44)". Largest testable square 2–18 px. | First-pass FAIL, not refuted. `LINK_PICK_THRESHOLD_PX = 9`, and no stated exemption. The DOM side meets the bar. |
| D6 | PASS | Picks 26 devices and 44 links; tree 26/44; "picked but not in tree: none". 114/114 tree rows select; 70/70 canvas clicks select exactly one tree row. | Upheld at 4 more viewports, the golden snapshot, an edge snapshot and an 87-node fleet (124 clicked, 0 fail). |
| D7 | PASS | `capture.mjs reduced`: "PASS D7: camera lands in one frame under reduce, 24 poses without it". Unit 8/8. | Upheld. Refuter: hover, select and tier fade happen in one step; real keys give 1 change frame against 17–52 in the control; CSS over 1 ms only for a 2 ms drawer. |
| D8 | PASS | Greyscale 03/06 at 1440, both themes: band letters, rim line styles, glyphs ✕ ? ✓ ⚠ ⊘ ≠, doubled bridge rails. The DOM sweep found 0 meaning-bearing attributes with empty text. | Upheld. Refuter repeated it across 9 states × 2 themes. |
| F1 | PASS | `npm run typecheck` exit 0; bare `npx tsc --noEmit` exit 0. Probe configs that extend the tree's configs exit 2 on deliberate TS2322/TS7006 errors. | Upheld. The refuter corrected the evidence: 20 JSDoc `any` annotations, not 1. Hand-written `.d.mts` declarations hide 45 mismatches against the `.mjs` they declare. |
| F2 | **UNPROVEN** | Grader: run 1 "1 failed \| 7141 passed", EXIT=1, rerun green. Refuter: "Test Files 5 failed \| 225 passed", EXIT=1, plus capture delegate "FAIL capture app 30 of 32" (EXIT=3) and 3 of 4 runs red, always on 08 at 1440. | Overturned to UNPROVEN, not FAIL. Every red is a timeout or a tier step-down under load; no fully green pair of both legs exists on this tree. |
| F3 | **FAIL** | `node review/mutation-check.mjs` EXIT=1: "INVALID layout-clearance-quadratic: the guard text occurs 0 time(s)"; `compiler-drops-unevaluable` and `compiler-drops-established` MISATTRIBUTED. `--history` exits 0 with false "untracked" output. | First-pass FAIL, not refuted. O34 and this file's predecessor still cite "21 of 21 KILLED". |
| F4 | **FAIL** | Refuter, headed Chromium with a real profile: `default_font_size=12`, width 700 px → `"three":[2134],"fabric":"on"`; `default_font_size=20`, width 900 px → `"three":[],"fabric":"off"`. | Overturned. The gate is `(min-width: 48rem)`, and that rem follows the browser's font setting. At 16 px the split and the post-FCP fetch hold. |
| F5 | PASS | `compile-all` exit 0; `cmp` identical for all 4 files; `meta.sourceGitBlob` = `git rev-parse HEAD:…` = `e01fd01b`; digest `e63d7fac` shown in the header and status bar. | Upheld, including a fresh `autocrlf=true` clone, a production build and 390 px. |
| F6 | **FAIL** | Refuter `capture.mjs twice 5` on a private build: runs 31/29/29/30/31 of 32, "verdict: F6 NOT ESTABLISHED: 10 frame(s) did not render properly", EXIT=3. Four 08 frames have 2–3 distinct hashes. | Overturned. The tier and the "below frame-rate bar" chrome are derived from rAF timing, so pixels depend on the host clock. The grader's `twice 5` passed on a quieter host. |
| E1 | PASS | `journey-scope.test.ts` 36/36. `measure-inp.mjs` printed exactly the 8 declared ids. | Upheld. Refuter: warm J5 really opened the palette 25 of 25 times. |
| E2 | PASS | Acceptance-grade run (host 23 %, "ACCEPTANCE EVIDENCE"): worst-per-rep p95 J1 32, J2 80, J3 32, J3b 32, J4 48, J5 32, J2-first 48 (21/21), J5-first 48 (80/80) ms. | Upheld, but thinly: none of the refuter's 3 runs was acceptance-grade (44 %, 28 %, 25.3 % busy). All of them still passed, worst J2 p95 192 ms. The acceptance run's raw `inp.json` was overwritten and is not preserved. |
| E3 | **FAIL** | Across quiet runs of build `ca13e2147866a70b`: "FAIL — J1-select-finding UNSTABLE (2/3 measured runs clean) … J5-first-open-palette UNSTABLE (2/3 measured runs clean)". | First-pass FAIL, not refuted. Two of the three quiet runs are another grader's on the same build hash. |
| E4 | **FAIL** | `measure-fps.mjs` reproduced (median 60). Refuter `e4probe3.mjs`, typing in the query bar during a focus flight: "nonConvergedTicks 52/52 … drawnTicks 1 drawnFpsWhileNonConverged 1.1 … longestOwedUndrawn 49–52 ticks (~817–867 ms) \| stats.fps min 59.9 belowBar false tier high", `acceptanceEvidence=true`. | Overturned. The `panelInput.ts` deferral is deliberate but unreported, and `rateBar.push(raw)` sees rAF deltas, not drawn frames. |
| E5 | **FAIL** | Default 3 runs: PASS. Refuter `ATLAS_RUNS=8 node review/audit-e5-coldload.mjs`: "FAIL E5 … 3 keystroke(s) over 200 ms (worst 216 ms)", then "… 5 keystroke(s) over 200 ms (worst 312 ms)", both with `acceptanceEvidence=true`. | Overturned. The sweep half re-ran PASS (worst 88.7 ms). Whether 8 runs is an allowed way to run the command is not stated; the bar says "any keystroke". |

Totals: **12 PASS, 24 FAIL, 3 UNPROVEN.**

## What is proven (survived an attack)

Each of these was graded PASS, then independently attacked, and the attack failed. Each is proven only as
far as the attacks reached, so the limits are stated with it.

- **A2: multi-hop forwarding is explained hop by hop.**
  - The refuter (a retry; the first refuter died) re-drove the Path form on a fresh build:
    - "Hops (2)" for tcp 10.0.40.50→10.0.30.10:22, decided by `routes.dist1[3]` and then
      `acls.core1.PROTECT_SERVERS[3]` "deny ip any any".
    - The reverse direction, core1 Gi1/0/40 → dist1, also traces hop by hop.
    - `hop=1` survives a reload.
  - The ratchet loop over 3,249 traces reproduced the golden histogram. 54 of 54 endpoint-to-endpoint traces
    name an egress interface and a route or ACL decider at every hop. Route and ACL citation indices match
    the source snapshot (38 of 38 and 16 of 16).
  - **Limits:**
    - Loop detection, TTL expiry and the cable-map next-host branch never run on this data. Every hop
      crosses the one dist1–core1 cable.
    - In 487 of the 675 traces with a hop, some hop names no decider. These are mostly router-addressed or
      VIP flows, which the engine reports as undecided.
- **B4: an off-subnet source is out of scope, and the product says so.** 120,144 refuter flows, including
  every off-prefix literal in the data, gave out-of-scope with the "lies in no subnet" sentence. That
  sentence is visible, unclipped, at 375, 768, 1280 and 1920 px in both themes. **Limit:** an endpoint
  record or an owned /32 outside every subnet would be traced instead. Neither exists in this data.
- **B8: the counterexample affordance renders on real data.**
  - 492 of 492 decided refusals offer a counterexample.
  - The 100 that offer only an undecided neighbour are honestly headed "its own outcome is UNDECIDED, so not
    a counterexample". A brute-force search found no decided one-field neighbour for any of them, including
    by source, which the grader never searched.
  - Confirmed in a production build at 390×844, dark theme, and on the renamed snapshot.
- **C3: dense rows carry real information.** At the 03 capture's viewports, every row shows severity, ID,
  host, title and category. The worst title loss is 25–27 % at 1440, and 32 % in the unfiltered queue, where
  F136 still names its condition. **Limits:** compact density fails (O17), and so does the all-columns
  Display view (see Known issues). Both are non-default reader settings.
- **C5: no named render tell.**
  - Hairlines: 0 chains at DSF 2. At DSF 1 the only chain is the Legend button's CSS border.
  - No black frame during load. Smooth light/high contrast stretch. No coplanar flicker at the closest
    zoom.
  - A grazing far view gave one 16-device-px sparkle cluster, about 2×2 CSS px.
  - **Limits:**
    - The motion half passed in one of two grader runs and failed to judge AO in the refuter's run: exit 4,
      UNPROVEN on AO, with no FAIL. AO is not one of the eight named tells.
    - Tested on one Intel iGPU only.
- **D6: the accessible fabric list covers the 3-D selection set.** The refuter checked 4 more viewports, the
  golden and edge snapshots, and an 87-node fleet whose tiers start collapsed. No target can be picked in 3-D
  but not selected in the tree. The tree is a superset where 3-D cannot pick (L22 and L38 at 600 px; L7 and
  L9 on the edge set).
- **D7: reduced motion is honoured.** In-canvas eases, the tier cross-fade, history-blend ghosting, real
  keyboard and wheel input, and traces through the real form each change in one step under `reduce`. The
  only CSS duration over 1 ms is a 2 ms drawer transition. **Limit:** the AssessHub-mounted host was checked
  by source, not run.
- **D8: meaning does not depend on colour.** Greyscale frames and a chroma-split DOM sweep across 9 states
  and 2 themes found nothing that only colour encodes. **Limits:** Medium, Low and Info severities, and down
  links, do not occur on screen. They were checked in source or the legend only.
- **F1: strict type-checking is clean and effective.** All three projects exit 0. Deliberate errors are
  caught, and turning off `skipLibCheck` changes nothing. **Limits** (the refuter's corrections):
  - 20 JSDoc `any` annotations exist, not 1.
  - The hand-written `.d.mts` declarations are never checked against their `.mjs`, and 45 mismatches hide
    there.
  - No test pins `strict` or `noUncheckedIndexedAccess` on the main `tsconfig.json`.
- **F5: the compiled data is source-bound.** Byte-identical recompiles were confirmed in the tree, in a fresh
  `autocrlf=true` clone and in a production build. The bound digest is displayed at 1920 and 390.
- **E1: the five journeys are declared, and the harness times exactly them.**
- **E2: lab INP at or under 200 ms on every journey** in the one acceptance-grade run. **Limits:**
  - It is upheld by absence of contradiction, not by a quiet reproduction. The refuter's three runs were
    all over the 25 % busy bar, yet all passed.
  - The acceptance run's raw `review/reports/inp.json` was overwritten by another session's run and does
    not survive. Only the E3 history record corroborates it.
  - Warm journeys ran only at 1920×1080, DSF 1.

## What is not

### FAIL

- **A1.** The no-scroll bar fails at the reference panel size. At 1280×800, 203 of 587 engine-record
  activations (11 findings) leave less than 60 px of the opened record on screen after the third
  interaction. At 1280×720 it is 426 of 587 (41 findings).
  - The cause is that the non-scrolling `.ev__head` chip header grows with the pointer count and leaves
    about 124–160 px of body.
  - Separately, 83 of 140 findings reach only analysis rows or absence witnesses, which the pane labels
    "not configuration". Literal configuration text is reachable for 3 (F012, F013, F102). Whether that
    satisfies "configuration evidence" is undecided.
- **A3.** The blocking line named for tcp 10.0.20.50→10.0.30.10:22 is PROTECT_SERVERS line 4 at the
  modelled core2 ingress. Entering at core1 it would be VOICE_FILTER line 3. The caveat nevertheless says
  the result "does not rest on that choice". `ingressPolicyGaps` compares outcomes and never the deciding
  line.
- **A4.** At 768 and 390, after a hop selection from the Path surface, the selected row stays off screen even
  after the reader returns to the queue (row y 1153 in a 1024 px viewport; y 9702 at 390). At 390 a plain
  Path → Findings switch also loses the page scroll. This is filed as O49 (owner decision). Two related
  observations:
  - Link re-aim cannot be tested at 390, because there is no canvas and the palette lists no links.
  - Selecting a finding that names another device switches the Device pane to a findings tab that does not
    show it.
- **A5.** Every trace entering at core2 and crossing to core1 (20 of 74 sampled flows, every 10.0.20.0/24
  source) auto-frames onto the short cable. Both hosts and the verdict glyph go off-canvas, and
  `labelsShown` is 1 (0 at 1280×800). After a manual reset the trace tells two stories: `flow.ts` puts the
  glyph on the last hop, while `traceMarkOf` puts the chip on the first unresolved hop.
- **A6.** At 390×844 the cut-point mark on core1 is covered by the stage HUD and quality chip. The stranded
  marks on access10 and access12 are covered by other labels. The HUD still says "all 9 marked". Selecting
  core2 by canvas click scrolls the canvas fully off screen. At 768×1024, three stranded marks are half
  covered.
- **B1.** `unassessedScoringDomains` ignores the producer's per-protocol `not_collected` receipts and the
  app's own RIB-incomplete verdict. core2's band therefore names only "ACLs" as unassessed. The same happens
  on the renamed snapshot. No test pins the list against the producer rows.
- **B2.** The 3-D verdict label ("✓ DELIVERED HERE" / "✕ BLOCKED") states the trace-level verdict with no
  scope and no caveats. On the Evidence surface at 1000×800 it is the only visible statement of the verdict.
  Separately, criterion text drift: the row says "2 of 26", but the data has 4 of 26. The product prints the
  true denominator, and prints "2 of 26" on a 2-RIB variant.
- **B3.** An input spelling of "no RIB" other than a missing key (`null`, `[]`, `"not_collected"`,
  prefix-less entries) compiles to a collected empty table. Traces through such a host come out "dropped"
  with "no prefix in its collected RIB … matches". The `null` variant gives 30 decided drops in the intent
  tally. The upload path accepts these inputs; the Python producer omits the key instead.
- **B5.** For protocol `ip` from 10.0.10.50, the trace blames evaluable PROTECT_SERVERS line 1 as "cannot be
  evaluated" and never names the echo-reply line [2] that blocks evaluation. For portless tcp, line 4 still
  claims "an earlier unevaluable line may fire first" when none can match.
- **B6.** Binding-count and "none is bound" claims cite `interfaces.<host>`, a table with no ACL fields. The
  records counted, `acl-bindings.json#hosts.<host>[i]`, cannot be reached from the claim. In addition, five
  dual model/source paths get no projection caveat, and the Data tab shows "0" for 8- and 17-member arrays.
- **B7.** The collected count follows `snap.devices` record presence, not the engine's own
  `collection_completeness` (canonical `summary.complete`). A host whose capture is empty is shown as having
  "answered the collector". The sample, renamed and synthetic fleets all have 0 partial and 0 not-collected
  hosts, so the first pass could not see this.
- **C2.** State 08-path-indeterminate permanently shows the amber "Quality high · 181/176 draw calls" chip
  (budget 176, measured 179–181). Either the state is brought within budget, or the owner records that a
  visible breach is acceptable product UI. R14's "all states `overBudget: false`" is stale either way.
- **C4.** After a live theme switch, the per-instance colours of the 3-D state rings are not recomputed. The
  rings keep the old theme's tint until reload: 1.87:1 against the light ground, below the 3:1 non-text
  floor. Other per-instance colours (glyphs, hatches, down/unknown rings) were not checked for the same
  defect.
- **C6.** Every hop step re-runs the draw-on and re-arms the three-loop packet, so stepping hops keeps the
  "only, bounded" loop running indefinitely. The motion inventory says hop stepping "never re-runs the
  draw-on", and nothing states a reason for re-arming. The inventory is also stale where it says the packet
  is "unexercisable" on this snapshot.
- **D1.** 122 secondary cite buttons ("phys" → `physical_health[N]`) in Ports grids on 23 devices cannot be
  focused by keyboard. Neither the repository's census nor the grader's own census catches this, because
  both count anything inside a composite whose item took Tab as reached. A second observation: at 390,
  running a trace from the palette leaves focus on `<BODY>` (2 of 2 runs).
- **D2.** In the default severity-grouped grid, sorting the Severity column toggles `aria-sort` without
  changing row order. A screen reader is told the same rows are sorted both ways.
- **D4.** As soon as there is a subject (a selection or a trace), receded never-collected chassis fall back
  to about 1.9–2.2:1 in light theme. That is the defect render-decisions §9 records as fixed with nothing
  selected. Receded collected chassis read 1.6–2.5:1. Dark theme mostly holds (lowest ghost 3.13). Whether
  the owner intends recession as a D4 exemption is written nowhere; the receded-cable floor of 4.0 suggests
  it is not.
- **D5.** All 44 cable pick targets, plus AP-floor1 and AP-floor3-01 at 1440, cannot contain a 24×24 square,
  and all of them select on a real click. No exemption is stated; the brief calls an unenumerated undersized
  target a defect. The Display checkboxes (13×13) are covered only by their 24 px labels and also lack a
  stated reason. The repository's D5 census is blind to canvas picks.
- **F3.**
  - The named executable gate exits 1:
    - `layout-clearance-quadratic` is INVALID, because `f24b9ccb` moved its guard text.
    - Both compiler mutants are MISATTRIBUTED, because `c199e0f9` made `compiler-fidelity.test.ts`
      table-driven. They are detected, but not at the asserted line.
  - `--history` has given false "untracked" output under exit 0 since the subtree import.
  - Red-before-fix history exists only for forwarding R17 and the claims C2/C3 follow-up (both reproduced).
    The compiler has never been refuted for the fields it transforms.
- **F4.** The 3-D split follows `48rem`, which moves with the browser's default font size. At 12 px a 700 px
  load fetches `three` and mounts the canvas with no "Show the 3-D fabric" button. At 20 px a 900 px load
  never fetches it. At the default 16 px the build, the split and the post-first-paint fetch all hold.
- **F6.** `twice 5` exits 3 on a busy host. The adaptive tier and the "below frame-rate bar" status text are
  derived from frame timing, so state 08's pixels vary between runs (2–3 hashes per 08 frame). The other 28
  frames were byte-identical. F6's own wording ("byte-identical") holds only at a pinned tier.
- **E3.** Long tasks over 50 ms still land on the interaction path in quiet runs: J1 (one post-handler task)
  and J5-first (the cold 1280×800 palette open; its keydown forces style and layout). The rollup over six
  lab runs: J1 4/6 clean, J4 5/6, J5 5/6, J5-first 4/6. O40 still applies: the harness judges long tasks,
  not long animation frames.
- **E4.** Typing in the query bar during a focus flight defers the owed render, through `panelInput.ts` with
  `quietMs 250` and `maxDeferMs 1500`. The fabric stays non-converged but presents about 1 fps. Meanwhile
  `stats().fps` reads 60, `frameRateBelowBar` false and the tier high, and `measure-fps.mjs` would score
  those windows as 60 fps. A still-camera selection cycle draws about 54 fps while reporting 60. The
  deferral is a documented E2/E3 trade; the failure is that it is silent.
- **E5.** The cold-load command passes at its default of 3 runs, with a margin of only 24–32 ms (worst
  keystrokes 168–176 ms). At 8 runs it failed twice in a row with acceptance-grade host readings: worst
  keystroke 216 ms, then 312 ms (a keydown at 795 ms, after first paint at 444 ms). One 221 ms frame before
  first paint also counts, because the pre-paint carve-out is unsanctioned. The sweep half passes.

### UNPROVEN

- **C1.** No verdict counts under RULE v8, which needs at least 2 distinct critics per pairing who are
  unrecognising, well-formed, bound to the build, and not picking the reference.
  - All 20 critics recognised the reference products from navigation vocabulary ("NQE", "Intent", "Blast
    Radius") or toolbar layout.
  - All 20 lines are malformed (`reasons` is a string).
  - All 20 critics share the builder's model family.
  - The panel is bound to `14f81dc4`, whose compiled data predates the current snapshot.
  - On the record, 12 losses stand: composition, typographic craft and colour discipline, 4 of 4 each.
  - Moving C1 needs an owner decision (O19), plus critics who do not recognise the products and a new build
    that answers the losing reasons.
- **D3.** No complete `review/audit-d3-focus.mjs --sweep` run has ever recorded an exit code. The latest
  attempt stopped after ~78.5 minutes with whole crossing × page-state combinations undriven. The owner
  instruction recorded in O68 bars further runs. Bounded probes on this head found no counterexample, and
  they do not replace the gate. Closing D3 needs one complete sweep on a capable host or hosted runner, or an
  owner ruling that bounded runs count.
- **F2.** Neither the grader nor the refuter obtained a fully green suite together with a green capture
  delegate on this tree.
  - The grader's first suite run was red: the NUL-scan timed out, and that test walks the git-ignored
    `.local-data` (1,010 MB).
  - The refuter's suite run was red (5 files, 6 timeouts; green in isolation, 811 of 811).
  - The refuter's capture delegate was red in 3 of 4 runs, always on state 08 at 1440 (tier "balanced").
  - Every red is load-shaped. One unloaded-host run of both legs would settle it either way.

## What was not examined

Across the whole grade:

- **No real screen reader.** NVDA, JAWS and Narrator were not used. Every accessibility claim comes from DOM
  and CDP accessibility-tree reads.
- **One host, one GPU.** Intel iGPU via ANGLE/D3D11. DSF 2 was emulated, not a real DPR-2 display. The
  balanced tier and organic adaptive step-down were not judged for render quality.
- **No field data.** INP, frame rate and keystroke latency are lab figures on one machine. Headroom above
  the 60 Hz display cap was not measured. `ATLAS_FULLBLEED` was not run.
- **The AssessHub-mounted (`/scope`) build** was not exercised in any group. D7 traced its wiring by source
  only.
- **Forced-colors / high-contrast mode**, touch and pen input, and browser zoom were not tested.
- **Partial viewport and theme coverage.** Many criteria were measured at one or two viewports, or in one
  theme:
  - A1 was not measured at 1440×900, at 1281–1599 px, or below 1280.
  - B6 and B8 were graded on the dev server, not a production build.
  - D2 was not checked in compact density, an ungrouped order, or the cross-layer corpus.
  - D4 was not checked at 768, 1920, or in hover and active states.
- **Multi-hop beyond depth 2.** Loops, TTL expiry, the cable-map next-host branch, and decided no-route or
  TTL refusals as counterexample subjects do not occur in this snapshot and were not reached.
- **Per-criterion spill-overs left open by refuters:**
  - Whether any other per-instance 3-D colour goes stale after a theme switch (C4).
  - Whether a decided (SCOPED) flow shows A3's outcome-only reproduction defect; every 10.0.20.0/24 flow
    tried was PARTIAL.
  - The full 3,249-flow class count for A5's off-canvas framing (20 of 74 is a sample).
  - Whether the 2,325 px scroll after a core2 click at 390 belongs to A4's queue reveal or to A6.
  - Why the Cross-layer tab rendered 5 of its 43 rows in the C3 probe.
  - The cause of the recurring 0.5–1.4 s host frames during keyboard orbit (C5).
  - The packet start latency of about 2.1 s after `[` (C6).
- **No mutation test** of whether B4's or A3's rendered text is the line's own raw text rather than a
  reconstruction. Every deny line in the sample reads "deny ip any any", so an index-to-text mispairing among
  deny lines would be invisible.

## Known issues carried forward

Reconciled against `docs/open-issues.md` at this tree.

**Already recorded, and still open in the shape this grade measured:**

| Entry | Bears on | Status at this grade |
|---|---|---|
| O49 | A4 | The 768/390 off-screen queue row reproduces. Still an owner decision, and still a FAIL under the criterion's text until decided. |
| O72 / R120 | A1 | O72's 1280×720 failure reproduces (426 of 587). **R120's line "the verifier reproduced 1280×800 (0 failures)" is false at this tree**: 203 of 587 fail. |
| O17 | C3 | Compact density still truncates titles (95–97 of 102 rows lose over 20 %). |
| O19, O70 | C1 | Owner decision outstanding. **O70's "ours 3-1 … the reference 3-1 … 2-2" tallies are wrong.** Side-mapped through `KEY.json` they are 4-0 for ours on information density and network visualisation, and 4-0 for the reference on the other three. |
| O68 | D3 | No complete sweep. Minor: O68 says "held new work back 58 times" (the log shows 29 events) and "76 minutes" (the log spans ~78.5). |
| O34 | F3 | **Stale:** it cites "21 of 21 KILLED, exit 0", but the gate now exits 1. A2's half of O34 can close; A2 now PASSes on shipped data. |
| O13 | B8 | Can close: the positive state renders on shipped data (492 of 492). |
| O16, O57 | C5 | The tier-change-mid-motion freeze is still an owner decision. AO-restore judgement is host-sensitive (UNPROVEN in 3 of 4 motion-harness runs this grade: C5 grader run 1, the C5 refuter, and the C6 grader; PASS only in C5 grader run 2). |
| O40, O59, O62 | E3, E2 | O40 (long tasks, not LoAF) still applies. O62's "the cold case cannot measure 1280x800" did not reproduce in quiet runs (80/80), but did in a busy one (19/20). |
| R69 | B2 | Records "the 3-D chips" as outside its guard. This grade shows the trace-level 3-D verdict label is the B2 failure, not a per-hop chip. |
| R14 | C2 | **Stale:** "Re-measured after the fix, all states: `overBudget: false`" is contradicted by state 08 (179–181 of 176). |
| R40 | C4 | The dev-server first-paint residual is now measured and confirmed, dev-only (a stored theme opposite the OS paints the browser default until tokens load). The release build is unaffected. |

**Not recorded in `docs/open-issues.md` (new at this grade).** Each needs an entry and an owner:

1. A3: `engine.ts ingressPolicyGaps` (~2741) counts an alternate ingress as reproducing the result on
   outcome alone, so the caveat can say the named ACL line does not depend on ingress when it does.
2. A5: trace auto-framing (`scene.ts setTrace`, `frameSphereFromCurrentView`, radius `max(6, …)`) throws
   both hosts and the verdict glyph off-canvas on core2 → core1. Also, the glyph (`flow.ts:591`, last hop)
   and the chip (`traceMarkOf`, first unresolved hop) mark different hosts.
3. A6: at 390×844, HUD and label occlusion of the cut and stranded marks, and a core2 selection that
   scrolls the fabric away.
4. B1: `band-qualification.ts unassessedScoringDomains` ignores `protocol_assessability` and the RIB
   verdict.
5. B3: `compile-model.mjs` (~1157–1171) and `validate-snapshot.mjs` turn a declared-absent RIB into a
   collected empty table.
6. B5: `runLists`' `poisonedBy ??=` names the first undecidable line, not the unevaluable one. There is
   also a false "earlier unevaluable line may fire first".
7. B6: `bindings.ts:356` and `engine.ts:1141` cite the interface table for binding counts.
8. B7: `compile-model.mjs:975` and `StatusBar.tsx:121` count record presence as collection.
9. C3 (not a C3 failure): with every Display column on, the folded second line renders the devices and wave
   values at 0 px, overlaps "Priority" with "Rank", and overflows the row by 12 px.
10. C4: `scene.ts applyTheme` does not re-tint `stateRings`.
11. C6: `flow.setTrace` re-arms the packet and draw-on on every hop change. `flow.ts:634-635` and
    design-brief §4.8 say otherwise, and §4.8's "unexercisable" packet row is stale.
12. D1: `DevicePane.tsx:414` and `RecordGrid` give no keyboard route to a cell's second control.
13. D1 (D3-shaped, observation only): a palette-run trace at 390 leaves focus on `<BODY>`.
14. D2: Severity-column sort toggles `aria-sort` over an unchanged order (`query.ts:1899`,
    `PriorityQueue.tsx:1505-1516`, `DataGrid.tsx:2136`). Also, `pageRows()` sizes PageDown from the first
    row, so 3–12 rows are skipped unseen, contradicting `DataGrid.tsx:281-308` and its unit test.
15. D4: receded ghost and collected chassis fall below 3:1 in light theme as soon as anything is
    selected or traced.
16. D4 (side finding): the "Clear scope" focus ring is clipped by `.qbar`'s `overflow-y: hidden`
    (App.css:31–32).
17. D5: canvas cable and AP pick areas are under 24 px with no stated exemption. The repository's census
    sees only DOM boxes.
18. E4: the `panelInput.ts` deferral is invisible to `stats().fps`, `frameRateBelowBar` and
    `measure-fps.mjs`. Also, `createFrameRateBar.below()` returns false while its window is too short to
    judge, and capture records keep no fps figure.
19. E5: the cold-load keystroke margin collapses with more samples (216 ms and 312 ms at 8 runs).
20. F1: 45 unchecked mismatches between the hand-written `.d.mts` and `.mjs` files. No pin on the main
    project's strict flags.
21. F2: `source-hygiene.test.ts`'s NUL scan walks the git-ignored `.local-data` and `dist-hub`, so its
    duration depends on other agents' scratch.
22. F3: `mutation-check.mjs` targets have rotted (layout guard text, compiler `killedBy`), and
    `--history` is wrong since the subtree import. `docs/refutation.md` has not followed the compiler
    rewrite.
23. F4: the single-column gate is in `rem`, so it follows the reader's font setting rather than 768 CSS px
    (`surfaces.tsx:102-114`).
24. F6 / C2: state 08's draw-call overrun and tier sensitivity make its pixels depend on the host clock.

**Criterion and document text that this grade found stale** (documentation, not product failures):

- `docs/acceptance.md`:
  - A1's census prose says 146/583 and 2/143/1; the data has 140/587 and 2/137/1.
  - A2's row says no reachable flow takes a second hop.
  - The A5 and 06 capture notes say every trace is single-hop.
  - B2 says "2 of 26".
  - C1 says no panel has run, and cites RULE v4.
- The 06-path-blocked capture is named as A3's blocked-flow evidence, but it shows an UNDECIDED denial. The
  decided evidence is the multi-hop denial.
- The design brief still says 146 findings.
- Minor UI wording: the intent-bound sentence joins hosts with "and … and" rather than `listPhrase`
  (`PathTrace.tsx finishIntentSearch`).

## Previous grades

Graded 2026-09-26 at `7f67013`: **not ready**. Six FAILs (A1, C2, C5, D3, E2, E3), five UNPROVENs (A2, B8,
C1, F2, F3) and 28 PASSes, every PASS upheld after attack. Since then, A2, B8, C5 and E2 have moved to PASS
and D3 to UNPROVEN, while F3 has moved from UNPROVEN to FAIL. The reasons for the larger FAIL count are set
out under the Verdict.
