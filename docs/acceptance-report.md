# Atlas Scope — Acceptance Report

Graded 2026-09-22 against `docs/acceptance.md`, on the **uncommitted working tree** (HEAD `857b520`),
not a commit. Six first-pass graders covered groups A–F. Independent refuters then attacked the PASS
verdicts. **Where the first pass and the refutation disagree, the refutation is applied.** All four
overturns below carry a reproducible proof (command plus output), so none was set aside. No grader or
refuter ran a git write or edited product source.

This report replaces the earlier report at this path. Its figures (for example "1370 passed") describe
an earlier tree and are superseded.

## Verdict

**Atlas Scope is not ready for acceptance.** Seven criteria fail outright:

- **F2:** the unit suite is red.
- **A1:** evidence for a finding reaches configuration for 12 of 146 findings, not "any finding".
- **B1:** the `is:healthy` filter answers yes for five hosts whose favourable band partly measures missing evidence.
- **D3:** a focus-loss path drops keyboard focus to `<body>`.
- **C2:** captured states show a broken identifier wrap and a tab hidden off the pane edge.
- **C5:** z-fighting and label popping appear at both quality tiers.
- **C6:** the fade animations run far past 300 ms (overturned by refutation).

Nine more are UNPROVEN, and an UNPROVEN criterion is not a pass:

- Four cannot be exercised on the shipped data (A2, B8) or with the recorded evidence (C1, F3).
- Four performance criteria (E2–E5) have no measurement on a host the harness accepts. Two of them, E2 and E4, passed for one grader and failed for the refuter on the same build.
- F5 holds only for bytes on this host's disk, and its own companion gate is red.

Some things are well evidenced and survived attack:

- The forwarding engine's honesty (B2–B5, B7): about 9,840 refuter traces and more than 9,000 grader traces, with zero unscoped claims.
- Blocked-flow attribution (A3) and re-aiming without losing context (A4–A6).
- Keyboard and assistive semantics (D1, D2, D4–D8).
- Type-checking, code-splitting and deterministic capture (F1, F4, F6).

These strengths do not offset the failures. No count below is a score.

## Scorecard

Key:
- **PASS (upheld):** a refuter attacked the pass and could not break it.
- **PASS (unattacked):** the refuter returned, but did not examine this criterion.
- **Overturned:** the refutation replaced the first-pass verdict.

| Criterion | Verdict | Evidence | Note |
|---|---|---|---|
| A1 | **FAIL** | For F099, 3 interactions lead to "Show the record that matches this finding: access13 Gi0/11 (err-disabled)". For F004 the pane says "No configuration evidence route: the finding names no configuration line and nothing we hold matches its words." | Works for 12 of 146 findings. For the other 134 it reaches context only. O12. |
| A2 | UNPROVEN | Depth 1: "Hop 1 of 1: core1 … THIS IS WHAT DECIDED THE HOP: PROTECT_SERVERS line 4 of 4". 86 tests pass. | Maximum real depth is 1 (`expect(Math.max(...depths.keys())).toBe(1)`). Multi-hop is covered by a fixture only. |
| A3 | PASS (upheld) | "denied at core1 by ACL PROTECT_SERVERS line 4 of 4 (acls.core1.PROTECT_SERVERS[3]: \"deny ip any any\")" | The refuter checked 3,000+ traces: every denied hop names the host, ACL, line and raw text. |
| A4 | PASS (upheld) | Queue stays at scrollTop 2400 with F047 in view. Camera proxy unchanged at core1 474,82. | The refuter closed the grader's tab and canvas-link gaps. `hop=` above 0 is unreachable. |
| A5 | PASS (upheld) | Hover cursor `pointer`. Double-click moves the proxy to core1 284,-166. Reset returns 474,82. The fabric shows the "? UNDECIDED" marker. | A single-node marker only. The path renderer is not exercised on real data. |
| A6 | PASS (upheld) | Pixel diff core1~podacc1 46,401 vs podacc1~dist1 8,222 | Uses the refuter's cleaner control pair. The core1 hub-cable effect is not isolated. |
| B1 | **FAIL** | `applyToDevices(..., parseQuery('is:healthy'))` returns [core2, dist1, dist2, podacc1, podacc2], all qualified. | CommandPalette.tsx:194, query.ts:189/:219 and PriorityQueue.tsx:184 bypass `presentBand`. O12. |
| B2 | PASS (upheld) | Sweeps of 3,250 + 1,950 (grader) and 9,840 (refuter) traces: 0 claims missing "2 of 26". | Type drift: `claim` is documented as "One sentence" but has 2+ sentences on every decided verdict. |
| B3 | PASS (upheld) | "forwarding past dist1 is unmodelled — not clear, and not blocked." No decided outcome has an unmodelled hop. | |
| B4 | PASS (upheld) | "198.51.100.7 lies in no subnet this collection observed … no forwarding claim is made" | 29 out-of-subnet sources all refused. |
| B5 | PASS (upheld) | "core1 ACL PROTECT_SERVERS line 3 of 4 cannot be evaluated — cannot model ACL match qualifier(s): icmp_type (acls.core1.PROTECT_SERVERS[2])" | The object-group variant is synthetic-only. |
| B6 | PASS (unattacked) | `resolveCitation`: model=25, bearer=628, unresolved=0 of 653. 10 of 10 random clicks resolved. | The refuter did not re-run it. Shows the compiled record, not the source (O9). The sha binds to CRLF bytes (O15). |
| B7 | PASS (upheld) | "coverage \| 23/26 collected \| RIBs 2/26 (both shown incomplete) \| ACLs 1/26 \| centrality 25/44" | The refuter checked 6 viewports × 4 surfaces × 2 themes: all visible and unoccluded. |
| B8 | UNPROVEN | 0 of 9,324 denied or dropped flows have a counterexample. | The positive state renders only in a fixture. O13. |
| C1 | UNPROVEN | `review/blind/KEY.json` holds 12 entries with no verdict fields. 8 of 20 sheets are orphans. | The recorded rounds were not blind (the sheets show brand and demo chrome). O19. |
| C2 | **FAIL** | "(num_power_supplie" / "s)" wraps across line-tops [665, 680]. The Raw tab spans left=1440 to right=1488 against innerWidth 1440. Both IP placeholders read "10.0.10.50". | Contradicts R25's "PASS 72 of 72" text-fidelity claim. Not in open-issues. |
| C3 | PASS (unattacked) | 03-finding-drill: glyph, ID, device, full title and category shown. At 1440 only F002 is clamped. | Compact density is not graded (O17). |
| C4 | PASS (unattacked) | Light background (241,244,248), not the inverted value (242,239,232). Chips and links are re-authored. | 1440 light was spot-checked only. |
| C5 | **FAIL** | The motion harness exits 3. "3 flip-flop clusters ≥16px (largest 27px at x507–511, y598–609)". "31 blinks". | Reproduced O16 independently. Light-theme links are ~1 CSS px. |
| C6 | **FAIL** (overturned from PASS) | `stepEmphasis`: `pctReachedAtMs: { '0.5': 167, '0.9': 533, '0.95': 700, '0.99': 1067 }, settledAtMs: 1350`. "fraction of recede completed at 300 ms: 0.726" | The RECEDE/HOVER/SELECT constants are exponential time constants, not durations. The tier fade is 300.1 ms, not under 300. |
| D1 | PASS (upheld) | 36-stop Tab cycle with no trap. A1 and A2 flows completed by keyboard only. | The refuter's DOM scan found 0 pointer-only controls. |
| D2 | PASS (upheld) | Exactly one tabindex=0 after every key. `aria-rowcount` tracks the DOM row count. | The refuter saw 152 rows; the grader saw 322. Both held the contract. |
| D3 | **FAIL** | Snapshot popover, then Tab, then Escape: "One second later document.activeElement is BODY." | `src/app/Header.tsx:479` falls back to `e.currentTarget.blur()`. Not in open-issues. |
| D4 | PASS (upheld) | Minimum text contrast 4.71 dark, 4.60 light (composited). Placeholders 5.91 / 5.70. | There is no per-pixel proof for every 3-D encoding. |
| D5 | PASS (upheld) | 0 hit-testable targets under 24 px across 12 states (221–259 measured). | |
| D6 | PASS (upheld) | 60 pickable objects, `notInTree = []`. The tree holds 26 devices and 44 links. | |
| D7 | PASS (upheld) | Under reduce: 1 pose over 30 frames, fling 1 pose over 40, `getAnimations()` empty. | The named gate `node review/capture.mjs reduced` was not run. An equivalent was run instead. |
| D8 | PASS (upheld) | Greyscale 03/06/01: letter chips, dashed links, "? UNDECIDED" in words. | Dark only on the refuter's pass. |
| E1 | PASS (upheld) | J1–J5 plus J3b declared and measured: "6 pass, 0 fail, 0 NOT MEASURED". | J4's verify runs before the measured act. |
| E2 | UNPROVEN (overturned from PASS) | Grader worst: 120 ms. Refuter: "FAIL J2-select-device-3d worstPerRep p95=280ms", "FAIL J3-type-query worstPerRep p95=216ms". | Every run has `acceptanceEvidence=false`. The result depends on host state. |
| E3 | UNPROVEN | "E3 across runs of build 4076548118cfef43 (0 run(s), need 3): INSUFFICIENT RUNS" | J1's first selection is unmeasured. It carried a ~65 ms task in 1 of 3 sweep reps. |
| E4 | UNPROVEN (overturned from PASS) | Grader: "median 60 fps". Refuter: "FAIL — median 46.42 fps … worst window 43.93fps (floor 45)". | Both runs `acceptanceEvidence=false`. Bimodal, as recorded. |
| E5 | UNPROVEN (leans FAIL) | Cold load exit 1: "2 keystroke(s) over 200 ms (worst 424 ms) [NOT ACCEPTANCE EVIDENCE]" | The unsanctioned pre-FCP carve-out hides a 294.5 ms no-affordance frame. O20. |
| F1 | PASS (upheld) | Both `tsc --noEmit` runs exit 0, including `--noImplicitAny`. | vite and vitest configs are in neither project. acceptance.md F1 text is stale. |
| F2 | **FAIL** | "Test Files 1 failed \| 113 passed (114); Tests 1 failed \| 1415 passed (1416)" | tracked-sources.test.ts:145 lists 19 untracked files (O10). Also a tautological test and an unpinned guard. |
| F3 | UNPROVEN | Claims mutation run: removing guards gives 5 failures, 4 failures, 2 failures. | No pre-fix source exists in Git. Five engines rest on prose only. refutation.md is stale on C2. |
| F4 | PASS (upheld) | `three-DcNJC9c1.js 827.80 kB`. `WebGLRenderer` appears 38 times in three and 0 in every other chunk. At 375 px, three is never fetched. | At 768 px and wider, three loads on every visit (disclosed). |
| F5 | UNPROVEN (overturned from PASS) | fabric.json is byte-identical after recompile (`6c7d78ab…9095`). `tracked-sources.test.ts` is red. | Source-bound only on this host's disk. The CRLF digest issue (O15) is still open. |
| F6 | PASS (upheld) | "verdict: F6 PASS: 32 of 32 frames byte-identical across 5 runs" (grader and refuter both) | :4181 preview build under CPU tile raster only. The dev server was not measured. |

The totals are given only so nothing is hidden: 23 PASS (20 upheld, 3 unattacked), 7 FAIL, 9 UNPROVEN,
out of 39. They are not a score.

## What is proven

Only criteria that a refuter attacked and could not break are listed here.

- **A3.** In the grader's trace the UI says "denied at core1 by ACL PROTECT_SERVERS line 4 of 4
  (acls.core1.PROTECT_SERVERS[3]: \"deny ip any any\")". The refuter checked it against fabric.json
  indices 0–3. Across 3,000+ refuter traces there were exactly two deciding lines (2,382 on
  PROTECT_SERVERS[3], 141 on INET_RETURN[2]), and each denied hop carried the host, ACL, "line N of M",
  raw text and cite.
- **A4.** The grader's a4.mjs was reproduced. The refuter's tabs2/link/back/reveal scripts then closed
  the grader's own gaps:
  - Ports, Routing, ACL and Raw tabs were all kept on a canvas or palette selection.
  - A real canvas click on cable L18 set `l=L18` with the camera unchanged.
  - Back navigation restored both the flow and the `d=` device.
- **A5.** The refuter reproduced it exactly: double-click moved the camera proxy to 284,-166 / 705,410,
  and Reset returned 474,82 / 529,444 / 736,444.
- **A6.** Pixel diffs were reproduced. With the refuter's clean control pair, podacc1~dist1 is 8,222
  (both 0 endpoints in failure_impact) against core1~podacc1 at 46,401.
- **B2.** The refuter swept 9,840 traces: "0 errors, 0 empty claims, 0 empty caveat lists, and 0 claims
  missing '2 of 26'".
- **B3.** 152 of 152 vitest tests pass. The refuter found 0 decided outcomes with a hop outside
  {core1, core2}.
- **B4.** 29 out-of-subnet sources, including 10.0.99.2 and 8.8.8.8, all traced as out-of-scope with
  empty hops.
- **B5.** engine.test.ts passes 85 of 85, including the icmp and INET_RETURN refusals. The object-group
  variant is synthetic only.
- **B7.** Checked across 6 viewports × 4 surfaces × 2 themes. All 41 loaded pages were visible and
  unoccluded. The 7 misses were the pre-mount loading screen.
- **D1.** The grader completed the Tab cycle and the A1 and A2 flows by key press alone. The refuter's
  DOM scan found 0 pointer-only controls on all four surfaces.
- **D2.** The refuter re-drove it independently. APG keys behaved as specified, exactly one tabindex=0
  remained, and `aria-rowcount` went 152 → 149 → 45 following the DOM.
- **D4.** The grader measured composited DOM text at minimum 4.71 dark and 4.60 light. The refuter
  added placeholders (5.91 / 5.70) and hover states (5.26 / 5.00).
- **D5.** The refuter found 0 hit-testable targets under 24 px in any of 12 states, with 221–259
  targets measured.
- **D6.** Every pickable object is in the tree (`notInTree = []`). The contract kinds are device and
  link, and the tree holds all 26 devices and 44 links.
- **D7.** Motion collapses under reduce: 1 pose over 30 frames, and the refuter's fling gave 1 pose over
  40 frames against 40 poses in the control. The criterion's own command was not run.
- **D8.** In greyscale captures, nothing depends on hue alone.
- **E1.** Six journeys are declared and measured.
- **F1.** `npx tsc -p tsconfig.json --noEmit` and
  `npx tsc -p tsconfig.scripts.json --noEmit --noImplicitAny` both exit 0, re-run by the refuter.
- **F4.** The refuter rebuilt to a scratch outDir and got identical hashes: index-Drj77SpR,
  mount-DoqxVe96, three-DcNJC9c1. Only Fabric3D imports three.
- **F6.** Both the grader and the refuter got "verdict: F6 PASS: 32 of 32 frames byte-identical across
  5 runs", and the refuter's run was on a heavily contended host.

**PASS, unattacked.** The refuter returned but did not examine these, so they are not listed above:
B6, C3, C4.

## What is not

### FAIL

- **A1.** The route to evidence works for 12 of 146 findings. For the other 134 it reaches context
  only: 133 unranked landings, plus F142, which names no device. The pane says "Browse core1's
  collected records (context, not this finding's evidence)". Closing it needs a producer change: the
  engine must publish per-finding record pointers.
- **B1.** `is:healthy` returns yes for all five favourable-band hosts, and every one of the five is
  qualified. For example podacc1 is "90 Excellent" with unassessed = ['protocol health (not assessed)',
  'routing (no RIB collected)', 'ACLs (none collected)']. Four surfaces bypass `presentBand`:
  `CommandPalette.tsx:194`, `query.ts:189`, `query.ts:219` and `PriorityQueue.tsx:184`.
- **C2.** Three visible defects:
  - At 1440 in both themes, 'num_power_supplies' breaks mid-word across two line-tops (captures
    02/06/07/08). The live DOM confirms it with `overflow-wrap:anywhere`.
  - The Device-pane tab strip has scrollWidth 427 against clientWidth 379, so the Raw tab sits off the
    pane edge with no affordance.
  - `PathTrace.tsx` uses one `EXAMPLE_ADDRESS` for both Source IP and Destination IP. The refuter saw
    the same src=dst in the 05-path-trace frame.

  This also contradicts R25's recorded "PASS 72 of 72 states free of clipped/broken text".
- **C5.** The motion harness exits 3:
  - Z-fighting at both tiers ("largest 27px at x507–511, y598–609").
  - 31 label blinks.
  - Light-theme links render 1–3 px wide on scanline y=230.
- **C6** (overturned). The dim/undim, hover and halo fades are exponential eases. In emphasis.ts:142/160
  each frame does `k = Math.min(1, dt / RECEDE_MS); cur += (tgt - cur) * k` and snaps only below
  `RECEDE_EPSILON=0.002`. The real function settles at 1,350 ms, and hover and halo settle at about
  417 ms and 917 ms. Against that, §4.8 states 240 / 80 / 140 ms and the criterion's bar is under
  300 ms.

  `motion-inventory.test.ts` stays green because it only finds CSS `transition` interpolations. The
  tier cross-fade measures 299.9–300.1 ms, which is not under 300.
- **D3.** Open the snapshot popover, press Tab, then press Escape. Focus lands on `BODY`, reproduced
  2 of 2 times. The cause is `src/app/Header.tsx:479`:
  `if (back && back.isConnected) back.focus(); else e.currentTarget.blur();`
- **F2.** `npx vitest run` exits 1 with "Tests 1 failed | 1415 passed (1416)". The failure is
  `tracked-sources.test.ts:145`, which lists 19 untracked runtime files (O10). The test is correct, and
  the fix is the owner's commit. The grader also found two test-quality defects:
  - `provenance.test.ts:272` is a tautology: it asserts sha256(tampered) !== sha256(fresh) and never
    calls a gate function.
  - The `claims.ts:470` empty-hop guard is unpinned. Deleting it leaves 34 of 34 claims tests green.

### UNPROVEN

- **A2.** Multi-hop never executes on shipped data. That leaves the second hop's decider, hop
  navigation, the cable-map branch, the TTL cut and loop detection unexercised, and the criterion
  forbids a PASS from a depth-1 capture.
- **B8.** 0 of 9,324 flows produce a counterexample. By the product's own definition none can exist on
  this snapshot. Loosening the near-miss rule is not a fix (O13).
- **C1.** There is no valid blind verdict set. KEY.json records no verdicts. One sheet shows the
  'FORWARD' logo, the Storylane modal and the "Atlas Scope" brand, so it is not blind, and it also
  pairs an out-of-date capture of ours. This needs an owner decision (O19).
- **E2** (overturned). The first pass got a worst of 120 ms. The refuter's re-run on the same build
  exited 1 with J2 p95=280 ms and J3 p95=216 ms. Every run is refused by the harness itself ("NOT
  ACCEPTANCE EVIDENCE"), with the host 27–60% busy on battery. The result depends on the host.
- **E3.** No quiet runs exist ("INSUFFICIENT RUNS … 3 busy run(s) of this build excluded"). The J1
  verify step throws away the first selection after load. When the sweep measured that selection it gave
  worstLoAF 93.4 ms in 1 of 3 reps.

  acceptance.md line 82 is also stale. It says resizes cost 51–58 ms, but they measured 105–149.7 ms,
  and six other interaction classes also crossed 50 ms.
- **E4** (overturned). The grader measured a 60 fps median. The refuter's re-run measured a 46.42 fps
  median with a worst window of 43.93 fps, and orbit "worst window 39.35 fps". Both runs are
  `acceptanceEvidence=false`. The scene did report its degradation (tier low, belowBar true). The
  "trace animating" condition is unreachable, and the canvas is 1160x962, not a full 1920x1080 target.
- **E5.** `audit-e5-coldload.mjs` exited 1. A keydown at 703.2 ms landed in a 282.1 ms frame and took
  424 ms. A 294.5 ms frame with `workingAffordancePresent=false` is excused only by the pre-FCP
  carve-out, which acceptance.md does not sanction.

  The host was 52% busy on battery, so this may be host-inflated. It leans FAIL.
- **F3.** The only commit already contains the fixes, so "failed before the fix" is prose-only for
  forwarding, blast, layout, query and compiler. For claims, the grader's own mutation run stands in as
  evidence. refutation.md §6/§7 still record C2 as open, although `hopsSupportOutcome` is in the code.
- **F5** (overturned). fabric.json recompiles byte-identical. But F5's own companion gate,
  `tracked-sources.test.ts`, is red ("Tests 1 failed | 15 passed (16)"), and acceptance.md says
  clone-and-rerun proof needs a commit.

  The source digest `9cc348bd…` binds CRLF working-tree bytes. The committed LF blob hashes
  `9580aa09…3089` (O15). 88 entries under src/ and tools/ are untracked, and `.gitattributes` is
  untracked too.

## What was not examined

Everything below is collected from each auditor's and refuter's own statement.

**Environment**
- Another agent drove the shared Browser pane: tabs navigated, scrollTop changed and the viewport was
  resized with no input from the grader. Its window was also hidden, so rAF never fired there.
- A and D figures come from isolated headless or headed Playwright against the live :4180 dev server,
  which others were editing (A was graded at about 18:45–18:55). It was not a frozen build.
- The host was on battery for the whole session (41% → 33%), 22–70% busy. About 20 leftover
  `vite preview` servers were running. No quiet or AC run of any performance harness exists.

**A**
- Dark theme and viewports other than 1920x1080.
- Keyboard-only selection paths in the A group.
- The A1 census beyond F099, F106 and F004.
- Pixel diffs for link selections.
- `hop=` above 0, and the multi-hop renderer `src/fabric3d/flow.ts` on real data.
- Stranded marks on 2 of 11 switches whose labels were hidden.
- Removing core1's incident-cable highlighting from the A6 diff.

**B**
- The full vitest suite was not run in B.
- The PriorityQueue and CommandPalette band surfaces were judged from source, not rendered.
- The Verify-an-intent surface was not swept for B2.
- Laundering idioms beyond `?? 0` / `|| 0` / `?? ""` / `|| "-"`. `blast.ts:131` `String(status ?? '')`
  was not traced.
- The O15 sha claim was not re-measured.
- The B6 sweep and its clicks were not re-run by any refuter.

**C**
- Not all 32 captures were read at full resolution. 1440 light was spot-checked.
- The trace packet's 3-loop stop was not observed in motion.
- Reduced-motion rendering of the emphasis eases (they may snap).
- `capture.mjs text` was not re-run.
- The 2.8 GB flip-flop evidence was not opened.
- No new blind panel was convened.
- C3 and C4 were not attacked.

**D**
- `review/capture.mjs reduced` (the named D7 gate) was not run by anyone.
- No real screen reader was used. D6 rests on `ariaSnapshot`, and the expansion loop there reached 82
  treeitems against 119 in the pane.
- Contrast was measured only at 1440 and 390, comfortable density, on :4180 (not :4181).
- Not audited: forced-colors, 200% zoom or reflow, touch targets.
- Per-pixel 3-D encodings (chassis tint, pads, blast marks, bloom halos).
- D3 unmount-return focus in the inspector tabs, JSON find bar and toasts.
- D2 in filtered or regrouped states.
- D6 tree-to-3-D selection was not re-driven.
- D5 and D8 were checked in the light theme by the grader only.

**E**
- The FLOOR headless lane, `ATLAS_FULLBLEED=1`, and a repeat of E4 by the grader.
- The source of `host-env.mjs`'s busy/power detection and its LoAF attribution.
- Whether J4's act produces a new trace each rep.
- Whether `frameRateBelowBar` fires below 55 fps.

**F**
- Mutation testing of the forwarding, blast, layout, query and compiler engines.
- Hand review of all 114 test files. Only 3 of 91 unguarded data loops had their preconditions run.
- The three sidecar compilers run directly.
- Dev-server F6.
- A clean-clone reproduction (needs a commit).
- `mock-classification.test.ts` beyond seeing it pass.
- Staged deletions of `review/_fix_*` by another party were left untouched.

## Known issues carried forward

Reconciled against `docs/open-issues.md`.

**Confirmed by this grading, still open:**

| Issue | Status after this grading |
|---|---|
| O10 | tracked-sources red, now 19 files. Drives F2 FAIL and F5 UNPROVEN. OWNER DECISION: commit the tree. |
| O12 | A1 12 of 146 and the B1 four-surface residual, both re-confirmed live. |
| O13 | B8: 0 of 9,324 in this sweep. |
| O15 | CRLF digest, re-confirmed: `9580aa09…3089` vs `9cc348bd…5dfd`. |
| O16 | C5 z-fighting and label popping, reproduced independently (exit 3). |
| O17 | Compact density still unexamined for C3. |
| O18 | Dead spinner CSS. See also the new C6 item below. |
| O19 | C1: KEY.json holds no verdicts, and the sheets are not blind. |
| O20 | E5. The keystroke probe has now hit a post-FCP blocking frame and failed (424 ms). The carve-out is still unsanctioned. |
| O6 | Bloom halos: not examined for D4. |
| O9 | B6 shows the compiled record, not the source record. |

**Not re-examined by this grading:** O7, O8, O11, O14.

**New in this grading, not yet in open-issues.md (should be added):**

1. **C6.** The emphasis, hover and halo eases are exponential and settle in 417–1,350 ms, against
   §4.8's 80/140/240 ms. `motion-inventory.test.ts` cannot see rAF-driven eases. The tier fade sits at
   exactly 300 ms.
2. **D3.** `Header.tsx:479` blurs to `<body>` when the return target has unmounted.
3. **C2.** Three items:
   - The `num_power_supplies` mid-word wrap. The R25 text detector misses it.
   - The Device-pane tab strip overflows with no affordance.
   - The src and dst placeholders are the same address (`PathTrace.tsx` `EXAMPLE_ADDRESS`).
4. **F2.** Two test-quality items:
   - `provenance.test.ts:272` is a tautology.
   - The `claims.ts:470` empty-hop guard is unpinned.
   - Also, `claim-honesty-b1.test.tsx:145` is mislabelled.
5. **E3/E1.** Two harness gaps:
   - The J1 verify step discards the first selection after load.
   - J4's verify runs before the measured act.
6. **B2.** `types.ts:358` documents `claim` as "One sentence", but decided claims have 2+ sentences.
7. **Stale documents:**
   - acceptance.md F1 still says "18 residual" diagnostics, but the measurement is 0.
   - acceptance.md line 82 still gives 51–58 ms resizes and two classes over 50 ms.
   - acceptance.md cites fabric digest `fce33d24…`, but the current digest is `6c7d78ab…`.
   - acceptance.md says 48 untracked entries; 88 are measured.
   - refutation.md §6/§7 still record C2 as open.
8. **A verdict-consistency question (D8 refuter).** In state 06 the path panel says "on core1 denies
   this flow" while the 3-D chip reads "? UNDECIDED". This belongs to the A5 or B group, and neither
   graded it.
