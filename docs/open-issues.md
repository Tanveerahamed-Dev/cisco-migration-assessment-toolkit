# Atlas Scope — open issues found during the build

Tracked here so they cannot be lost between agent waves. Each entry says how it was found and what
evidence exists, because an issue asserted without evidence is a rumour.

## Resolved

> **Repair wave 4 (reconciled 2026-09-23, committed as `8e873d2` and `70bea72`).** Entries R54–R66
> and the moved O24 below, the status notes added to R44, R49, O10, O12, O15 and O18, and the
> rewritten O9, O12–O14, O16, O17, O19–O23 and O25–O28 plus the new O29–O34 under Open, and notes on
> R39 and R51, record two things
> that had not been written here: the "new" items 1–13 and the status changes of the independent
> re-grade of `443a05a` (`docs/acceptance-report.md`, committed beside the wave-3 record in
> `1c829c9`), and what the five wave-4 repair clusters (W4-R1 citations and nulls: B6, B1; W4-R2
> journey scope and test hygiene: E1, the E harness, F2–F4; W4-R3 queue: A4, D3, O24; W4-R4 motion:
> C5, C6; W4-R5 forwarding: the B5-adjacent caveat, B4, the engine tripwire, the stale-card lead),
> the merged-tree gate and the C5 tier-pin commit reported. **Every FIXED below was checked by the
> reconciler before it was written:** the code named was read at the line given, and the named tests
> were re-run at `70bea72` in one invocation (32 files, `976` tests, 976 passed, 0 failed, exit 0,
> with the zero-assertion guard live), plus `src/app/self-removing-focus.test.tsx` and
> `src/fabric3d/stepdown.test.ts` in a second (2 files, 26 tests, exit 0, 152 s).
> `src/core/tracked-sources.test.ts` is green (6 of 6): `src/core/route-fields.ts`, the one file the
> gate left red, is tracked in `8e873d2`. Against `vite preview` of a scratch `vite build` of
> `70bea72` (its own out-dir, port 4287, stopped afterwards) the reconciler also re-ran
> `node review/layout-guard.mjs`: `layout-guard: all five invariants hold at every viewport.`, exit 0
> (O24). `sha256sum src/data/fabric.json` is `a1a599b8…d251` (R54). **Verified by the orchestrator
> at `70bea72`:** `tsc` (app, scripts `--noImplicitAny`, config) all exit 0; `vitest` 136 files,
> 2106 tests, exit 0; `npm run build` exit 0; the content and message marker scans clean; no
> capture-motion threshold changed (consistent with the reconciler's
> `git diff 443a05a 70bea72 -- review/capture-motion.mjs`, which changes no threshold-constant line).
> **Not re-run by the reconciler, and cited as "reported" wherever it appears:** `capture.mjs app`,
> `text`, `reduced` and `twice 5`; `capture-motion.mjs` (the agents' runs, the gate's at `8e873d2`
> and the independent verifier's at `70bea72`); `measure-inp.mjs`, `measure-fps.mjs` and the E5
> harnesses; both `audit-d3-focus.mjs` passes; `mutation-check.mjs`; the agents' browser probes and
> screenshots (orchestrating session's scratchpad); and every wave-4 mutation. A fixed defect does
> not by itself move its criterion; nothing here is a re-grade.
>
> **History since the wave-3 record.** `1c829c9` (docs only: the wave-3 record and the re-grade of
> `443a05a`) → `2d9712c` (checkpoint of an interrupted wave-4 run: the session process ended about
> 13 minutes in, before any of the five agents returned; their partial edits were committed as they
> stood so that the restarted agents could verify them rather than assume them, `tsc` red at that
> commit on an unused import mid-edit — its message — and a scratch probe the interrupted agent
> left, `engine.zz-probe-tmp.test.ts`, was deleted, not committed) → `8e873d2` (repair wave 4, 53
> files) → `70bea72` (the C5 tier pin, 5 files; R60 (d)). `git status` was clean at `70bea72`
> before this edit.

### R54. B6 — the link inspector's centrality figures had no citation, and 2,064 device and link rows cited nothing — FIXED (re-grade of `443a05a`, new item 3)
Found by the re-grade of `443a05a` (B6 overturned PASS → FAIL): `?l=L7` showed "Cutting it partitions
yes / Betweenness 22.0000 / Pairs cut 22 / Centrality rank 4" with no cite control,
`grep -c link_centrality src/data/fabric.json` gave 0, and the pane's only reference,
`cable_map.cables[7]`, holds none of those fields. The refuter did not check other rows; W4-R1's class
walk did, and on the unfixed tree reported 2,064 rows with no citation and no declared derivation
(Host, Model, Serial, Software, Score, Criticality …).

**Fix, verified in code.** `tools/compile-snapshot.mjs` compiles the source records the figures are
read from under the paths their citations name — `link_centrality[k]` (`:232–245`),
`health_scores[switch=…]` (`:218–226`) and `cable_map.nodes[host=…]` — appended at the end of
`fabric.json`, so earlier model paths are unchanged; each link carries `centralityCite` (`:289`) and
each device `fieldCites` (`:197`), naming the record each compiled field was READ from.
`DevicePane.tsx:1943–1947` cites `link.centralityCite` on all four rows, and every Device-pane
key/value row is typed `EvidenceRow` (cite | derived) (reported). `sha256sum src/data/fabric.json` is
`a1a599b8…d251` (reconciler); the source digest `9580aa09…3089` is unchanged, and the gate moved
`acceptance.md` F5's fabric digest (verified: `:200` names `a1a599b8…d251` at the 2026-09-23 recompile
and keeps `2f558c38…a308` as the 2026-09-22 value). **Pinned by** `src/panels/DevicePane.cite.test.tsx`
— 6 of 6 re-run green, including "walks every device and every link, and every row it finds is cited
or declares its derivation" (no list of labels) and "a health figure cites the health_scores record,
not the inventory record that holds no score". Reported: two mutations (the four cites replaced by a
derived label; `link_centrality` removed from the compiler output), each 2 red then restored;
recompiling twice is byte-identical. **Observation, not verified as a defect:** a link with no
centrality row (`centralityCite` null) falls back to `link.cite` on those four rows, whose values then
read "not observed". O9 (the raw source record) is unchanged. B6 is not re-graded here.

### R55. B1 — one null administrative distance read three ways across four surfaces — FIXED, with one owner the engine shares and a type-checker guard for the class (re-grade new item 2; closes R44's residual)
Found by the re-grade of `443a05a` (B1 overturned PASS → FAIL): `routes.core1[6]`
(`"adminDistance":null`) read "0 — a connected route's administrative distance by definition…" on the
Path panel and "administrative distance: / not observed" on the Device pane's Routing tab. W4-R1's
type-checker guard then found two readers the grading had not: the evidence pane's route row
(`EvidencePane.tsx:654/660`, "not observed" for a connected route's null next hop and AD — a fourth
surface) and the engine's `adminDistanceOf`, a second, case-sensitive owner of the null-ranks-as-0
rule that also printed that convention's 0 into the tie-break caveat as though the record carried it.

**Fix, verified in code.** `src/core/route-fields.ts` (new, tracked in `8e873d2`) is the one owner —
`routeFieldReading` (`:77`), `adminDistanceRank`, `isRouteRecord` — and imports types only;
`claims.ts:692` re-exports it. The owner cannot live in `claims.ts`: `claims.ts` imports the engine and
evaluates an engine binding at load, so an engine importing it back hits a TDZ (reported seen live
during a mutation: "Cannot access 'NOT_OBSERVED_TEXT' before initialization"). Every surface renders
the one `HopList.tsx:426` `RouteFieldValue`: the hop list, `DevicePane.tsx:1545–1546`,
`Inspector.tsx:305` and `EvidencePane.tsx:655`/`:661` (the last applied by the gate). `engine.ts:1597`
is `const adminDistanceOf = adminDistanceRank;`, and the caveat at `:1622` prints
`routeFieldReading(winner, "adminDistance").text`. **Decision changed** (recorded in the owner's
header): "0 — … by definition" put a digit in the value slot of a record that carries none; a
connected or local route's null AD now reads "not recorded — the record carries no value; a connected
route's administrative distance is zero by platform convention, so nothing collectable is missing",
and its null next hop "n/a — a connected route has no next hop". **Pinned by**
`src/panels/HopList.admin-distance.test.tsx` — 11 of 11 re-run green: `routes.core1[6]` "identical on
all three surfaces, and never a bare 0"; every route record on every Routing tab against the
Inspector; and the guard — "finds no read of RouteEntry.adminDistance outside the owner", "finds no
render module (.tsx) reading RouteEntry.nextHop outside the owner", "the owner is a module the
forwarding engine can import: its runtime imports never reach the engine", and a planted self-test
(the owner is resolved by the type checker, never a hard-coded path). `claims.test.ts` (41) and
`Inspector.test.tsx` (50) re-run green. Reported: 2 failed / 9 passed before the gate's EvidencePane
and engine edits, 11/11 after; mutations of the Device-pane AD column (3 red) and of the owner's text
(5 red). **Stated residuals:** a function returning the owner-free number can launder the value (the
limit `band-read.guard` has); the nextHop half covers `.tsx` render modules only, so a `.ts`
formatter would escape it; the Inspector's dynamic field walk is covered by DOM tests, not the guard.

**The re-grade's cosmetic lead** ("No routing table was collected for AP-floor1 2 of 26 hosts have
one") was not reproduced in the Device pane, whose text keeps its punctuation (reported). The
run-together text was `NotObserved`'s accessible text ("not observedno RIB was collected…"): the gate
added a visually-hidden " — " before the reason (`primitives.tsx:124`, non-compact form). **Pinned
by** `src/ui/primitives.test.tsx` "separates the words from the visible reason in the accessible text,
not only by layout" — 38 of 38 re-run green. B1 is not re-graded here.

### R56. A4 — clicking the visible copy of a finding listed under two groups threw the queue to its first copy — FIXED (re-grade new item 1)
Found by the re-grade of `443a05a` (A4 FAIL): under GROUP "Device health band", F144 is row 92 (Poor)
and row 167 (Critical); clicking row 167 at scrollTop 7879 jumped to 4655 with focus on row 92. The
grading ran band grouping only. The interrupted run's edit in `2d9712c` was checked by W4-R3 rather
than assumed: with `DataGrid.tsx` and `PriorityQueue.tsx` put back to `443a05a`, 9 of 18 a4-scroll
cases failed under band, host and role grouping (e.g. "scrollTop 3795 -> 94") (reported).

**Fix, verified in code.** A row's identity in the grid is its per-group copy key
(`DataGrid.tsx:578` `rowKeyOf`: roving cell, reveal, hold, activated copy); a re-aim from another
surface prefers a copy already on screen, and the queue opens a collapsed group only when every group
holding the row is collapsed (reported). **Pinned by** `src/panels/PriorityQueue.a4-scroll.test.tsx` —
18 of 18 re-run green, 9 of them the duplicate-row cases; `PriorityQueue.test.tsx` (37),
`PriorityQueue.reveal-hold.test.tsx` (6) and `PriorityQueue.folded-columns.test.tsx` (5) also green.
Reported browser figure (private production build, 1920x1080, band grouping): clicking F144 at row 167
kept scrollTop 7879 → 7879, with focus and `aria-current` on row 167. R39 (the no-finding path) is
unaffected. A4 is not re-graded here.

### R57. D3 — a control that removes itself dropped focus to `<body>` — FIXED through one owner, with a class test that presses every tab stop (re-grade new item 4)
Found by the re-grade of `443a05a` (D3 overturned PASS → FAIL): "Remove the Critical/High severity
filter", "Clear scope", "Deselect device core1" and "Stop investigating the flow …" each left
`document.activeElement` on `<body>`, no ring anywhere. W4-R3 wrote the class test first:
`src/app/self-removing-focus.test.tsx` mounts App with one of every kind of scope token and presses
every tab stop (103) with Enter and, separately, Space; on the unfixed tree it reported 27 failures per
key — the grading's five plus Remove access role, Stop restricting, Deselect finding/link, the queue's
own chips and its empty-state "Clear the filter text".

**Fix, verified in code.** `src/app/focus-return.ts:241` `handOffFocus(control, action, stated)` plans
a successor structurally before the action runs (the next surviving stop in the control's labelled
set, else the previous, else the caller's stated successors, else the set's label, else the region
landmark) and acts only if focus was actually lost. Callers: the Chip primitive's remove control
(`primitives.tsx:324`, optional `removeSuccessor`), Clear scope (`App.tsx:178`), the URL-notice
Dismiss (`App.tsx:492`) and the queue's empty-state reset (`PriorityQueue.tsx:2085`). The new pass
found two more at 390x844, both fixed (reported): "Skip to the fabric" targeted a `display:none`
`#stage` (it now falls back to the first control of the body through `returnFocus`), and
`.qbar__tokens` let "Clear scope" paint over the handed-to chip (now `flex: none`; the bar scrolls).
**Pinned by** `src/app/self-removing-focus.test.tsx` — 2 of 2 re-run green (Enter and Space; per-test
timeout 1,200,000 ms, `:306`). Reported browser evidence, not re-run by the reconciler:
`node review/audit-d3-focus.mjs --self-removing` (new mode; real Tab presses at 1440, 768 and 390, one
page per width and key) — 94 failures on a build with the hand-off disabled, and `154
self-removing/BODY case(s), 0 failed … 0 not visible`, exit 0, on the fixed build (29 min 47 s); the
default pass `332 case(s), 0 failed … 666 focus stop(s) … 0 not visible`, exit 0 (21 min 33 s).
**Runtime note for graders (W4-R3):** run `--self-removing` on its own against a private
`vite preview`, not inside the default pass; the jsdom class test takes 6–11 min on a loaded host.
**Not stated as covered:** self-removing controls inside an open Inspector or evidence pane (an area
the re-grade left unchecked). D3 is not re-graded here.

### O24. The findings queue's chrome starved its rows whenever the path panel shared rail A — FIXED in wave 4 by a fold decided from measured space (moved from Open, 2026-09-23)
**Original entry (wave 3).** Found by the R2 cluster at session start and re-found by the merged-tree
gate; verified by the reconciler's `layout-guard.mjs` run on the `443a05a` build ("1280x800 / with
trace: only 2 of 146 finding rows are hit-testable (need >= 4). Clicks land on BUTTON.sb__cov
instead."; 4 of 146 at 1440x900). Pre-existing at `d3e2a1c`. Cause, measured by the gate: at the
280 px rail the queue's chrome above its grid was 330 px (corpus switch 64, query 34,
Group/Order/Display 145, count/scope lines 70). The wave-3 gate refused the proposed fold as the
queue owner's design decision.

**Fix (W4-R3), verified in code.** `PriorityQueue.tsx:613` `MIN_UNFOLDED_ROWS = 6`: when fewer than
six finding rows are in view at rest, Group, Order and Display fold behind one "View" disclosure
beside the filter field (`:859`), decided from measured space (the data rows whose laid-out centres
fall in the grid's port, clipped by every clipping ancestor), not from a width, and kept only while it
actually adds rows: at 1440 and 1920 with a trace folding showed the same 4 rows, because the path
track absorbs the freed space, so it is undone there (reported). Group/Order state and the Display
popover stay mounted. `layout-guard.mjs` gained invariant 2c: the disclosure must be a labelled,
described tab stop with `aria-expanded=false` and `aria-controls` naming the hidden block, and Enter
must show every control it hid. **Verified by the reconciler's layout-guard run** on a scratch build
of `70bea72` (:4287): "1280x800 / with trace: view controls folded under "View" (3 controls,
disclosure tab-reachable)", "1280x800 / with trace: doc 800/800, 4/146 rows hit-testable, path panel
present", 1440x900 with trace 4/146, and "layout-guard: all five invariants hold at every viewport.",
exit 0. There is no unit test of the fold; the guard is the evidence. Reported: with
`MIN_UNFOLDED_ROWS = 0` the guard returns the original violation (2 of 146); a keyboard probe (Tab
reaches View, Enter expands, the next Tab lands on Group, Space closes); D2 in the browser
`role:grid, tabStops:1` folded and unfolded. **Stated limits:** 4 rows at 1440x900 and 1280x800 with a
trace is exactly the invariant's floor, and at 1440x900 on `?s=path` the rows still start below rail
A's fold (R46); the fold was verified in headless Playwright, not in the Browser pane, whose hidden
tab fires no ResizeObserver callbacks (W4-R3).

### R58. B5-adjacent — the not-applied-list caveat said a TCP-only line "matches" a udp or icmp flow — FIXED (re-grade new item 5)
Found by the re-grade of `443a05a` (B5 upheld, with this adjacent defect): the caveat matched candidate
lines by address only, 50 of 3,968 traces. The interrupted run's fix in `2d9712c` was checked by W4-R5
and kept. **Fix, verified in code.** `notAppliedCaveat` (`engine.ts:867`) asks every candidate line of
the engine's one matcher, `matchTri`: "matches" for yes, "could match" for maybe, excluded lines
omitted, and a list whose every addressed line is excluded is described with its first exclusion and
its implicit deny. The audit covers every sentence form that says a cited line (could) match a flow —
the not-applied and catch-all parentheticals, an applied list's undecidable-line caveat, not-applied
undecidable-line hop evidence and suggested-flow rationales — and every protocol in `FLOW_PROTOCOLS`
(the old coverage assertion was tautological). **Pinned by**
`src/forwarding/engine.not-applied-caveat.test.ts` — 6 of 6 re-run green. Reported: with the fix
removed, 5 of 6 red ("3269 traces; protocol-excluded "matches" citations: expected 78 to be +0").
**Latent, not proven:** the guard W4-R5 added to `buildSuggestions` survives its own removal (O33).

### R59. B4 — the "lies in no subnet this collection observed" sentence was unpinned — FIXED (re-grade new item 6)
Found by the re-grade of `443a05a` (mutating the sentence left 430/430 green). **Pinned by**
`src/forwarding/engine.off-subnet.test.ts` (from `2d9712c`, checked and kept by W4-R5): 14 sources
decided off-subnet independently of the engine (SVI addresses, connected routes, endpoint records) ×
every suggested and SVI-subnet destination × every protocol must each be out-of-scope with 0 hops,
refusal kind `outside-observed-subnets`, and the full sentence (`engine.ts:1507`, verified). 2 of 2
re-run green. Reported: mutating the sentence to "is outside the collection" turns it red.

### R60. C5 — a history-blend pop, a step-down that froze a moving view, a harness blind to the tier it graded, and a caller's tier pin that did not pin — FIXED; every C5 motion item PASS in one independent laboratory run at `70bea72` (reported)
Found by the re-grade of `443a05a` (C5 FAIL, new item 7): (a) dark "high" reset-fly frame 59 changed
46,569 px with the camera still — `historyWeightFor` dropped 0.75 → 0 in one frame after a slow frame;
(b) an automatic step-down mid-orbit held a frozen overlay for about 1,000 ms (light/high orbit frame
407, a 6.08× change); (c) `capture-motion.mjs` recorded `tiersSeen` but no verdict used it.

**(a), verified in code.** `postfx.ts:220` `nextHistoryWeight` moves the weight at most
`HISTORY_AA.maxStepPerFrame = 0.125` (`:198`) per presented frame, in and out; a still-frame drain
takes 6 frames and ends before `MOTION_HOLD_MS` (140 ms); a tween's arrival is ramped out over
max(150 ms, 6 frames) and the landing frame is plain; a content change still gives 0 at once; the
tier-fade snapshot re-render is weighted the same way. **Pinned by** `render-c5-r4.test.ts` (25,
including "a 0.465 px creep, a 166.6 ms gap, then a stop: no presented frame moves the weight by
more than…") and `scene.test.ts`'s source tripwires (44) — re-run green. Reported: live probe, largest
one-frame weight change 0.75 at `2d9712c`, 0.125 after, 0 on every still frame.

**(b), verified in code.** The automatic step-down lands only with the camera at rest: `scene.ts`
`landHeldStepDown` checks it before the gesture gate (`:3183`), so the gate's 6 s backstop cannot land
it mid-orbit. The tier-fade hold ends on the first frame after the new tier presents if the camera
moved or the content changed (`stepdown.ts:670` `createTierFadeHold`); the calm wait applies only to a
still view, bounded by `TIER_FADE_HOLD_DEFAULTS.maxHoldMs = 1200` (`:659`). **Pinned by**
`stepdown.fadehold.test.ts` (4) and the `scene.test.ts` tripwire "a held step-down lands only with the
camera at rest — before the gate…" — re-run green.

**(c), verified in code.** `capture-motion.mjs:881` `tierHeldBy` and `:908` `declaredTierFails`: a
sequence with any frame off its leg's declared tier — or, since `70bea72`, any frame whose
`stats().qualityAuto` is not false — is a leg problem (every other item UNPROVEN) and FAILS "every
recorded motion frame rendered at its leg's declared tier" (exit 3); a missing record fails closed.
**Pinned by** `render-c5-repairs.test.ts` (22, its "capture-motion: a sequence is graded only at the
tier its leg declares" block) — re-run green.

**(d) A product defect found while closing C5 — FIXED in `70bea72`, verified in code.**
`scene.setQuality` returned early when the requested tier equalled the tier in force
(`if (q === decision.tier) return;`), so asking for the auto-selected tier left it adaptive and the
step-down could still move it — contradicting `scene.ts`'s documented promise that a caller-pinned
tier is never moved. The gate's `capture-motion` run at `8e873d2` showed it (reported): the harness
pinned its HIGH legs that way and both stepped down to balanced after their orbit sequences (exit 3 on
the declared-tier item, four items UNPROVEN with no pop, flicker or blink measured, cross-fade PASS
24/24). `quality.ts` `pinQuality` now always yields `auto: false` and rebuilds only on a real tier
change; `tierIsAdaptive` is the one predicate both step-down sites gate on; `stats().qualityAuto`
(`scene.ts:3595`) exposes the pin; `capture-motion` pins each render-quality leg at rest before its
first sequence. **Pinned by** `src/fabric3d/quality.pin.test.ts` — 8 of 8 re-run green, including a
control (an auto-selected high tier IS stepped down by the below-bar series), "pinning the tier
already in force makes it a pin: not auto, no rebuild…" and "a pinned high tier holds high on every
frame of a sustained below-bar series".

**What is measured, and by whom (reported; not re-run by the reconciler).** An independent verifier
re-ran `capture-motion.mjs` alone on a production preview of `70bea72`: exit 0, all six C5 motion
items PASS — edge-sparkle share 0.000057 against 0.0002; 0 z-fighting clusters; 0 pops, 0 spikes and 0
label blinks over 2,666 still pairs; 8 AO restores at 16.6–150 ms; 24 of 24 tier fades at
266.6–266.8 ms; 24 of 24 sequences held their pinned tier. No threshold changed (see the banner).
Earlier wave-4 runs are history, on a host 84–100 % busy: W4-R4's run 2 exited 3 (9 high-leg sequences
rendered at balanced; one cross-fade opacity step of 0.48 during an 83.3 ms host frame; 0 still pops
and 0 spikes in 24 of 24). **Stated caveats.** The app itself passes no pin, so an ordinary session
runs on the adaptive tier and can step down; the HIGH-leg evidence is about a pinned high tier.
`capture-motion` no longer observes an organic mid-motion step-down (it formerly failed such a leg
rather than passing it); the step-down logic is covered by `stepdown*.test.ts` and the cross-fade
item. One hold in the gate's run (light r1, high → low) read 1,816.6 ms: the harness's `holdMs` runs
from the overlay's appearance to the fade's start (`capture-motion.mjs:1082`), which includes the
re-warm-up that §4.8 counts apart from the 1,200 ms hold, so it does not by itself contradict the
stated bound; not investigated further. Residuals: O16. C5 is not re-graded here.

### R61. C6 — the `@keyframes` scan was vacuous again, and a timer-started hold had no §4.8 bound — FIXED (re-grade new item 8)
Found by the re-grade of `443a05a` (C6 PASS upheld, with two notes): `motion-inventory.test.ts:661` was
`/@keyframess+([w-]+)/g`, which returns `[]` against the planted spinner (it had lost its escapes
between `1d19e22` and `443a05a`, so R49's and O18's "scanner proven live" did not hold at `443a05a`),
and the tier step-down hold had no §4.8 bound. **Fix, verified in code.** `keyframeNamesIn`
(`motion-inventory.test.ts:231`) uses `/@(?:-[a-z]+-)?keyframes\s+([\w-]+)/g`, strips comments and also
reads root-HTML `<style>` blocks (from `2d9712c`, checked by W4-R4, who reported listing every regex
literal in the file through the TypeScript AST and finding no other de-escaped one). The script scan
now finds, as a class, every `setTimeout` whose callback starts inline motion, resolves its delay
across `src/` and fails an unresolvable one; it finds exactly one, the tier-fade hold, and
`design-brief.md:832` states its bound (**1200 ms** at most, counted from the new tier's first
presented frame, only over a still view; no hold under reduced motion). **Pinned by**
`src/core/motion-inventory.test.ts` — 27 of 27 re-run green, including "the @keyframes scan is live:
it finds planted names, including the deleted spinner's", "the script scan finds a DELAYED start…"
and "every hold before script-set motion is BOUNDED, and §4.8 states the bound the code has".
Reported: the de-escaped regex turns the first red; deleting the §4.8 hold row turns 2 red. C6 is not
re-graded here.

### R62. E1 — the journey declaration contradicted the harnesses — FIXED (re-grade new item 9)
Found by the re-grade of `443a05a` (E1 overturned PASS → UNPROVEN): `audit-e5-sweep.mjs` ("drives the
interactions the journeys do NOT cover") timed "path trace: swap + submit" with J4's own selector, and
`acceptance.md` listed swap+submit, the palette open and the first finding selection as outside the
journeys while calling the last "inside J1". **Fix (W4-R2 and the gate), verified.** A declared
journey is exactly what `measure-inp.mjs` times: `acceptance.md:84–98` lists "Inside the declared
journeys" as the harness's journey ids (J1 includes the first selection after load; J4 is swap then
submit; J5 is Ctrl+K open and Escape close) and "Outside" as the sweep's action names;
`audit-e5-sweep.mjs` is importable (an `IS_MAIN` guard; exported `ACTIONS` with untimed `setup`) and
no longer times a journey's input; the gate brought `design-brief.md` §8.1/§8.2 into line. **Pinned
by** `src/core/journey-scope.test.ts` — 14 of 14 re-run green: it executes every journey act and sweep
action against a recording page and fails on a shared input (its red branch executed), requires
`acceptance.md`'s two lists to equal the harnesses' ids and action names, and reads §8.1/§8.2 with
whitespace normalised. Reported: re-adding the old sweep actions turns it red, naming each journey's
act. **Consequence:** the 2026-09-22 sweep figures for the first selection (93.4 ms), swap+submit
(52.8 ms) and the palette open (98.3 ms) are now E3 signals against J1, J4 and J5 (O21, O30). The
refactored sweep has not run headed under acceptance conditions (a headless dev-server smoke
actuated 13 of 13 actions twice, reported). E1 is not re-graded here.

### R63. E harness defects (re-grade new item 12) — anchor discovery swallowed its errors, a cited pin did not exist, NOT MEASURED counted as a violation, and the sweep could not tell a stalled window from the app — FIXED
- **`discoverJ2Anchors`** is exported and names every failure on the anchors line and in J2's NOT
  MEASURED reason (report field `j2AnchorDiscovery`). **Pinned by** `Fabric3D.test.tsx`'s
  "measure-inp: anchor discovery names its failures…" block — re-run green (66 of 66 in the file).
- **A nonexistent cited pin.** `measure-inp.mjs` cited `src/fabric3d/measure-inp.harness.test.ts`;
  it now cites `Fabric3D.test.tsx` and `journey-scope.test.ts`. **Pinned, as a class, by**
  `src/core/acceptance-gates.test.ts` "every test a tracked review harness cites as its pin exists"
  (with a non-empty-scan precondition) — 13 of 13 re-run green.
- **`e3StableVerdict`** counts NOT MEASURED apart ([PASS, PASS, NOT MEASURED, PASS] → STABLE PASS over
  3 measured; an unmeasured run cannot make up the run count; one E3-FAIL still decides it). Pinned in
  the same `Fabric3D.test.tsx` block (`:1845`, verified) — green.
- **Window-not-presenting frames.** The sweep's `judgeFrames`/`frameKind` count a frame with 0
  blocking time and under half reported script as `not-presenting`, apart from the application's;
  over the bar it makes its repetition NOT MEASURED, naming the frame. **Pinned by**
  `journey-scope.test.ts`'s "the E5 sweep separates window-not-presenting frames…" block (4) — green.
- **The sweep's un-actuatable "path trace: swap + submit"** is removed (it is J4's act, R62).

None of these harness changes has run under acceptance conditions (O25).

### R64. F2 — wall-clock bounds and a 30 s timeout that measured the host (re-grade new item 10; O26's engine and palette halves) — FIXED; `layout.test.ts`'s bound is not
Found by the re-grade of `443a05a` (F2 overturned PASS → UNPROVEN): under load
`CommandPalette.test.tsx:717` read 533 ms against 400, two real-data EvidencePane tests hit the 30 s
timeout while not hung, and `vitest.config.ts`'s "slowest solo: 2 266 ms" was false. No timeout or
threshold was raised.
- **CommandPalette.** Wall-clock bounds replaced by counts: 0 dataset reads per keystroke and per warm
  open (a Proxy over the dataset), at most 2 row renders per cursor move; time is logged "not gated"
  (`:731–732`, verified). `CommandPalette.test.tsx` 39 of 39 re-run green. Reported killed mutations:
  an un-memoised row, an un-memoised index, a search on every open.
- **EvidencePane.** The all-finding loops are one test per finding over the snapshot's own list, with
  non-empty-denominator and "every per-finding test ran" preconditions; the cost was profiled as
  React-dev + jsdom per mount, not product code (reported). `EvidencePane.source.test.tsx` (151) and
  `EvidencePane.targets-cap.test.tsx` (149) re-run green.
- **The engine tripwires** (`engine.test.ts`, median-of-7 under 50 ms for a trace and a counterexample
  search — the shape O26 condemns) are structural work bounds: `engineWork()` counts traces, hops and
  `lineMatches` (`engine.ts:76–78`); `ACL_PASSES_PER_HOP = 5` (`:89`) with its derivation stated;
  counterexample work is bounded by `COUNTEREXAMPLE_CANDIDATE_CAP` × the ingress count; time goes out
  through annotations only. **Pinned by** `engine.test.ts` (79) and the new
  `engine.work-bound.test.ts` (5: 341 sweep flows, 90 counterexample searches, memo-warm tight forms,
  long-list ACL cases) — re-run green. Reported killed mutations: double-traced candidates, a nested
  ACL pass (caught only once the long-list case was added), a self-re-tracing trace; not killable on
  this data: removing the 48-candidate cap (O33).
- **`vitest.config.ts`'s header** states measured figures and a rule instead of a number ("a unit test
  asserts no wall-clock time"; large units split one record per test; never raise the limit) and names
  `measure-inp.mjs` and `audit-e5-sweep.mjs` as the latency instruments (verified, `:16–30`).
- **`env.test.ts`** no longer presents a gitignored scratch script as re-runnable evidence (5 of 5
  green); the class is O29.
- **`mock-classification.test.ts`** went red when two new test files mocked modules; both are declared
  in F2's list — 3 of 3 re-run green.

**Not closed:** `src/fabric3d/layout.test.ts:952` still asserts a median-of-7 layout time under 50 ms,
against the header's rule (O26). Reported full runs on a host 84–86 % busy: 1 failed of 2,089, in
another cluster's file; one earlier run lost four files to Vitest's fixed 60 s worker-start timeout, an
environment limit the header now records. F2 is not re-graded here.

### R65. F3/F4 documentation drift (re-grade new item 11) — FIXED in the documents
Verified by the reconciler's reading: `acceptance.md:197` recounts the source-reading test files
(**45 of 135**, 44 of the 131 tracked, with the grep stated) instead of "roughly a fifth"; `:198`
records `mutation-check.mjs` at **18 of 18 mutations killed** and marks "16 of 16" superseded, as does
`refutation.md:351`; `refutation.md` §6 carries a "Not examined" record (`:313`, added 2026-09-23);
`acceptance.md:199` F4 says mount imports 4 bindings from the entry, 3 of them the theme-preference
functions. Reported, not re-run: `mutation-check.mjs` exit 0 with 18 of 18 KILLED (three clusters),
and the F4 re-measure from a `vite build`. Historical red-before-fix for the other engines still rests
on today's-code mutations (O34). F3 and F4 are not re-graded here.

### R66. The hidden-tab stale PARTIAL card under a refused shared link (re-grade lead, `PathTrace.tsx:1090`) — REPRODUCED and FIXED
The re-grade of `443a05a` listed it as an unconfirmed lead. W4-R5 reproduced it on the dev server
(reported): a real `history.back()` in a background tab (rAF not firing) to a refused link left the
PARTIAL card of the flow just left, and it stayed after the tab drew. The restore effect showed the
flow from a local `pending` whose store write the next Back cancelled, and nothing released it; `run`'s
deferred commit was not cancellable either. **Fix, verified in code:** `pending` is only an
acknowledgement, released when the store's flow or refusal moves elsewhere, and `run` commits through
`deferPastPaint` with its cancel kept in `runCommit` (`PathTrace.tsx:1139`). **Pinned by**
`src/panels/PathTrace.test.tsx`'s "history Back while no frame has been painted (hidden tab)" block
(3 cases) — 66 of 66 in the file re-run green. Reported: all 3 red before the fix; disabling the
supersede effect reds all 3, removing the run-commit cancel reds 1.

> **Repair wave 3 (reconciled 2026-09-23, committed as `443a05a`).** Entries R39–R53 below, the
> status notes added to O10, R10, R24, R28 and R29, and the rewritten O16, O17, O20, O21 and O23 plus
> the new O24–O28 under Open, record two things: the independent re-grade of `1d19e22`
> (`docs/acceptance-report.md`), whose "new" items 1–15 and status changes had not been written here,
> and what the five wave-3 repair clusters (R1 regressions: A4, C4, D5, the D3 status-bar lead, item
> 13; R2 path trace: B1, item 14, the A2 hop header, C2; R3 focus visibility: D3, the not-observed
> box; R4 gate honesty: tracked-sources, F2, C6, F1; R5 canvas: E3, C5) and the merged-tree gate
> reported. **Every FIXED below was checked by the reconciler before it was written:** the code named
> was read at the line given, and the named tests were re-run at `443a05a` in one invocation
> (27 files, `Tests 515 passed (515)`, exit 0, with the wave-3 zero-assertion guard live in every
> file). Against `vite preview` of the `dist/` built from `443a05a` (its own port, stopped
> afterwards) the reconciler also re-ran `node review/layout-guard.mjs` (exit 1 on exactly one
> violation, the pre-existing O24; invariants 4 and 5 hold at every size) and
> `node review/audit-d3-focus.mjs` (`341 case(s), 0 failed.`, `681 focus stop(s) checked for
> visibility, 0 not visible.`, exit 0; R42). **Verified by the orchestrator at `443a05a`:**
> `tsc -p tsconfig.json`, `tsc -p tsconfig.scripts.json --noImplicitAny` and
> `tsc -p tsconfig.config.json` all exit 0; `vitest` 128 files, 1714 tests, exit 0 (so
> `tracked-sources.test.ts` is green once the commit tracks `src/app/theme-preference.ts`);
> `npm run build` exit 0; the commit's content and message scan clean against the parent repository's
> 12 client-marker patterns. **Not re-run by the reconciler, and cited as "reported" wherever it
> appears:** `capture.mjs app`, `text`, `reduced` and `twice 5`, `capture-motion.mjs`,
> `measure-inp.mjs`, `measure-fps.mjs`, the E5 harnesses, the agents' in-page probes and screenshots
> (orchestrating session's scratchpad, not this repository), and every wave-3 mutation (none of them
> is among those `mutation-check.mjs` executes). A fixed defect does not by itself move its
> criterion; nothing here is a re-grade.
>
> **History as of wave 3** (it continues in the wave-4 banner above). `50a3dc5` (root) → `254694b`
> (wave-2 checkpoint, red on purpose) → `1d19e22` (repair wave 2c) → `d3e2a1c` (docs only: the
> wave-2c record and the re-grade of `1d19e22`) → `443a05a` (repair wave 3, 73 files). `git status`
> was clean at `443a05a`.

### R39. A4 — a device pick with no finding selected reset the queue's scroll — FIXED
Found by the re-grade of `1d19e22` (A4 FAIL, its new item 2): with no finding selected and the queue at
scrollTop 3200 with F060 and F069 (both naming access13) in view, clicking access13 left 3200 after
80 ms, then 0 once settled; core2 went 3200 → 2681, and dist1 likewise. Origin, traced by the R1
cluster in history: the "no finding → reveal the FIRST row naming the device" rule dates from
`50a3dc5`; `254694b` added the reveal key `d|device|link|hop`, which re-runs that reveal on every
device pick. The earlier PASS was measured with a finding active, so this path was never graded.

**Fix.** With no finding selected, the queue skips the representative reveal when a naming row is
already fully visible, and puts the roving tab stop on that visible row, so a dialog returning focus
cannot page the list — verified in code: `DataGrid.tsx:175` (`revealUnlessVisible`), `:873`
(`firstVisibleRow` over it), and `PriorityQueue.tsx:1941`, which passes it only while
`activeRowId === null`. With no naming row in view, F002 is still revealed. **Pinned by**
`src/panels/PriorityQueue.a4-scroll.test.tsx` — 9 of 9 re-run green, including "the grid OWNS focus
when the selection's marks commit…", "focus returning to the grid after the pick (the palette
closing) stays on the answer in view" and the with-finding control. Reported red before: 9 failed
(`expected +0 to be 975`); reported mutations: three, each red then restored. Reported browser
figures (1920x1080, `?s=queue`): Fabric list, palette and canvas picks all 3200 → 3200 (was → 0);
core2 held at 5800. A4 is not re-graded here. **Status after the re-grade of `443a05a`:** holds for
the no-finding path; A4 failed there on the duplicate-row path instead, fixed in wave 4 (R56).

### R40. C4 — a light-OS reader got a dark first paint — FIXED on the release build; one dev-server residual reported
Found by the re-grade (C4 overturned PASS → FAIL, its new item 5): `index.html` opened
`<html lang="en" data-theme="dark">`, so a light OS with nothing stored painted `rgb(8, 10, 14)` at
the boot line. Origin (R1, from history): the attribute has been in all three HTML pages since
`50a3dc5`; `254694b`'s wait-for-paint entry exposed it.

**Fix.** No HTML page carries `data-theme` (verified: the only match in the three pages is the inline
script's `setAttribute`). `src/app/theme-preference.ts` (new, tracked in `443a05a`) is the one owner:
`THEME_STORAGE_KEY` (`:30`) is named nowhere else in `src/`, and `commands.ts` now applies and writes
through it (`:43`, `:202`, `:205`; applied by the gate). `index.html:15` is one classic inline
`<head>` script that applies only an explicit stored `light`/`dark`, and `theme-boot.test.ts`
executes it beside the module reader over the storage states and requires identical results. The
gate also gave each explicit theme its own `color-scheme` in `tokens.css` (`:272–273` light,
`:337–338` dark, inside the existing dark block because `contrast.test.ts` reads one block per
selector). **Pinned by** `src/app/theme-boot.test.ts` — 24 of 24 re-run green ("no <html> start tag
carries data-theme", "no source file but theme-preference.ts names the storage key at all…",
"commands.ts's setTheme writes and applies through the module", the three per-theme `color-scheme`
tests). Reported: before the fix 8 of 11 failed; on the release build with Element Timing, 8 of 8
PASS with and without a 300 ms entry-fetch delay (explicit choices applied 14–27 ms before the boot
line paints; the main.tsx-only version failed the delayed case).

**Residual, dev server only (reported, not re-measured).** Under `vite` dev, `tokens.css` is injected
by script after first paint, so an explicit choice opposite to the OS paints its boot line on the
UA Canvas colour until tokens load. The gate's per-theme `color-scheme` rules live in `tokens.css`,
so by construction they cannot act before that file loads; they fix UA-painted parts after load. No
one has measured the dev-server boot line since. It does not reach the release build. C4 is not
re-graded here.

### R41. D5 — the Inspector's resize divider was an 8 px pointer target — FIXED, and the target-size scan now covers the class
Found by the re-grade (D5 FAIL, its new item 11): `div.inspector__divider` (role=separator) was
760x8 at 1440; `target-size.test.ts` scanned only `cursor: pointer`, and the exceptions file it
referred to did not exist. The 8 px size and its false comment date from `50a3dc5`; the earlier PASS
never opened the Inspector.

**Fix.** `Inspector.css:44` `block-size: var(--sp-5); /* 24px */` (verified), with a transparent
target; the hairline and grip are still drawn (reported, screenshots). `target-size.test.ts` now
selects target rules by class: any operable cursor value plus any class the markup puts on
`role="separator"`, both axes, fixed sizes as well as minimums, `calc(var(--x) * n)` resolved, with a
planted known-answer case. It honours no exemptions and asserts `docs/target-size-exceptions.md` does
not exist (`:250`; the file is absent). **Pinned by** `src/ui/target-size.test.ts` — 7 of 7 re-run
green. Reported: the widened scan failed on exactly the divider before; the reverted size turns it red.
D5 is not re-graded here.

### R42. D3 — tab-panel rings clipped by their scroller, the snapshot sha's Copy button outside its popover, and a focused grid cell under the status bar — FIXED
Found by the re-grade (D3 FAIL, its new item 10: `.dp__body` clipped the Device-pane tab-panel
outline to "0 pixels at ≥3:1"; "Copy the snapshot sha256" sat at x=641–668, outside the x=121–554
popover, with `elementFromPoint` returning the canvas) plus its 390 px lead (a focused grid cell under
the sticky status bar). The R3 cluster first taught `review/audit-d3-focus.mjs` to check VISIBILITY
as well as return (elementFromPoint at the centre of the element's visible part, and at least half the
visible perimeter changing by ≥3:1 between focused and indicator-suppressed screenshots), added 1440x900
and a "Tab into its panel" scenario for every tab; that audit then found two more of the class, the
Inspector's first tab (clipped by `.ui-tabs`) and a chip's remove button (clipped by `.ui-chip`).

**Fixes, verified in code.** `primitives.css:733–736` draws the ring inside the element for
`.ui-tabpanel:focus-visible, .ui-tabs :focus-visible, .ui-chip :focus-visible`
(`outline-offset: calc(-1 * var(--focus-ring-w))`). `.ui-copyable` is bounded by its container
(`:1006–1014`), and a `digest` variant (`:1032`, an UNBREAKABLE-TOKEN CONTAINER) shows the sha whole;
`Header.tsx:218` passes `digest`. `DataGrid.tsx:457`/`:478` `trimOverlays` excludes anything painted
over the grid's edges from its visible band, and focus arriving from outside by keyboard or script
gets the same band-aware reveal. **Pinned by** `DevicePane.focus-visible.test.tsx` (3),
`popover-focus.test.tsx` (5), `Header.test.tsx` (35, including "renders the sha as a digest that
wraps inside the popover…") and `PriorityQueue.reveal-hold.test.tsx` ("keyboard focus moving down
stops ABOVE a sticky status bar…", "a cell focused from outside … is revealed above it") — all re-run
green. **The runtime audit, re-run by the reconciler** against `vite preview` of the `443a05a` build:
`341 case(s), 0 failed.`, `Driven, by kind: dialog=12 popover=165 field=52 grid=26 tab=59 find bar=10
inspector=15 copy=2`, `681 focus stop(s) checked for visibility, 0 not visible.`, exit 0.
Reported: 681 stops, 45 not visible before the fixes; mutations of each rule red then restored. The
floor is stated in the audit's header: half the visible perimeter, because a plainly visible 2 px
inset ring on a 24x17 cell yields only 66 of 82 perimeter pixels at ≥3:1 — a floor for SC 2.4.7
"visible", not an SC 2.4.13 grade. Harness note (R3): a dev server other agents edit reloads
mid-audit, so R3 measured on a no-HMR, no-watch Vite with its own cache directory.

**The 1000x800 half.** The widened audit's last 10 NOT VISIBLE stops were one compact-viewport cell
half under the status bar; the root was layout, not focus: in the single-column band (768–1023 px)
with no trace the findings grid ran past rail A (1000x800: grid 698–1002, rail ending at 774) and,
at 800x600, focusing its first cell scrolled the `overflow: hidden` `.app` frame (status bar
574 → 220). The gate added `@media (min-width: 48rem) and (max-width: 63.9375rem)` to `shell.css`
(`:643–650`: rail A scrolls, contained; the slot keeps `min-block-size: min-content`) and
`layout-guard.mjs` INVARIANT 5 (`:232`). **Verified by the reconciler's layout-guard run:** at
1000x800, 900x700 and 800x600 the grid paints to exactly the status bar's top (774/674/574), `.app`
scrollTop stays 0 after focus, and the focused cell is inside the rail (749–766, 553–570, 502–519).
Invariant 5 does not measure 768 px itself (O17). D3 is not re-graded here.

### R43. B1 — a shared link carrying an invalid port or protocol was traced and rendered as a verdict — FIXED
Found by the re-grade (B1 FAIL, its new item 1): `?s=path&flow=10.0.10.50>10.0.20.10>tcp>abc` rendered
"tcp … :NaN" and "is delivered at core1"; port 70000 and protocol `bogus` were traced too.

**Fix, verified in code.** One validator, `readFlow`/`flowProblems` (`src/forwarding/ip.ts:302`,
`:330`), serves the form (`PathTrace.tsx:137` `validateFlowForm`), the link (`store.ts:207–209`: a
refused link becomes `flowRefused`, never `flow`; its hop is not restored and its text is re-encoded
unchanged) and `traceFlow`'s entry (`engine.ts:1889–1895`, refusal kinds `invalid-address` /
`invalid-flow`, `INVALID_INPUT_REFUSALS` at `:1679`, read by `claims.ts:400` `isInvalidInput`, badge
INVALID INPUT at `:461`). **Pinned by** `src/core/store.flow-validation.test.ts` (20),
`src/forwarding/engine.flow-validation.test.ts` (12) and `src/app/surfaces.test.tsx` (9, including
the whole App mounted from an invalid link: no NaN, no verdict, no `.pt-result`) — re-run green.
Reported: 36 failed before; two mutations red then restored; in the browser all three links render
the refusal ("The destination port "abc" in the shared link is not a port number…"). B1 is not
re-graded here.

### R44. B1 minor (re-grade item 14) — the HopList said "not observed" where the Inspector said "0 by definition" — FIXED for those two surfaces only; the Device pane still disagreed at the re-grade of `443a05a`, and the "0 — by definition" reading was withdrawn in wave 4 (R55)
For the same null `adminDistance` on a connected route the two surfaces disagreed. **Fix, verified in
code:** every route-record field in the hop list (winner and every alternative; `adminDistance` and
`nextHop`) goes through one `RouteField` (`HopList.tsx:425`) that asks the Inspector's owner,
`claims.ts` `notApplicableReason`, before the not-observed treatment (`:439`). Stated consequence:
the hop list's connected-route next hop now reads the owner's "n/a — a connected route has no next
hop" instead of "directly connected — no next-hop address". **Pinned by**
`src/panels/HopList.admin-distance.test.tsx` (4, every structural null on every traced hop against
the Inspector's row for the same cite) — re-run green; reported 3 failed before and a mutation red.

**Status after wave 4.** Partial, per the re-grade of `443a05a`: the Device pane's Routing tab still
rendered the same null as "not observed" (B1 FAIL), and the evidence pane and the engine's
`adminDistanceOf` were further readers. All four surfaces and the engine now read one owner,
`core/route-fields.ts`, and the connected-route AD reads "not recorded — …" rather than "0 — … by
definition" (R55).

### R45. A2 / layout — `.hop__host` collapsed to 0 px on the denied flow's hop header — FIXED
Found by the re-grade (its new item 3: the header overflowed by 174–214 px). **Fix, verified in
code:** `.hop__head` wraps (`PathTrace.css:323–329`) and `.hop__host` keeps its width
(`flex: 0 1 auto`, `:361–372`), so the verdict badge wraps instead. `review/layout-guard.mjs` gained
INVARIANT 4 (`:189`: every hop header of three traced flows at 390/768/1440/1920). **Verified by the
reconciler's layout-guard run** on the `443a05a` build: all 12 headers show their host at 38 px with
0 px overflow. There is no unit test; the guard is the evidence. Reported: 9 violations before
(including the delivered flow, host 0 px at 1440), returning when the CSS is reverted. A2 itself stays
UNPROVEN (depth 1, R18).

### R46. C2 — the path form was cut by its scroll slot, the detector could not see it, and adjacent not-observed boxes switched layout — FIXED
Found by the re-grade (C2 FAIL, its new item 4): at 1440x900 on `?s=path` the path slot was 170 px
(84–254) with Destination, Protocol, Port and "Trace this flow" outside it; at 1920 the submit was
sliced; and on `?d=core1` "Power supplies" stacked while "Modules" sat side by side.

**Fixes, verified in code.** `surfaces.tsx:314–360` measures the rendered flow form while the reader
is on the path surface and publishes it as `--rail-a-path-need` with `data-path-lead="form"`;
`shell.css:480–500` makes that measured height the path track's floor (other surfaces keep 10rem).
`review/capture.mjs:718` `readFormReach` fails any form split by its scroll port (six known-answer
self-test cases). `primitives.css:125–126` `.ui-notobs__why { flex: 1 1 100% }` puts the reason on
its own line. **Pinned by** `DevicePane.cmp-layout.test.ts` (4) — re-run green — for the box; the
form half has no unit test and rests on `capture.mjs text`, reported by the gate at `PASS text 72 of
72`, `selftest 23 of 23`, on the final build (not re-run by the reconciler). Reported before:
`FAIL text 66 of 72` (05-path-trace at 768/1440/1920, both themes).

**Stated consequences.** At 1440x900 on `?s=path` the queue's rows now sit below rail A's fold and
are reached by scrolling the rail (O24). And the gate found this rule had tripled full-layout cost
(an overflowing `overflow-y: auto` rail), turning J4 E3-FAIL (12–16 on-path tasks over 50 ms); it
set `overflow-y: scroll` on exactly `.rail--a[data-split="true"][data-path-lead="form"]`
(`shell.css:486–500`, verified in code), and reports J4 E3-PASS with 0 on-path tasks after, and
alternating A/B forced layout 9.2–12.9 ms (auto) against 2.5–4.4 ms (scroll) — reported, laboratory.
The descender half of O17 is still undetected. C2 is not re-graded here.

### R47. tracked-sources — the gate's denominator ignored `import.meta.glob`, the preview pages and CSS `@import` — FIXED
Found by the re-grade (tracked-sources overturned PASS → FAIL, its new item 7; see O10). **Fix
(R4):** the denominator is now the real Vite/Rolldown build — an in-memory build of every non-ignored
`*.html` page, taking every module id plus every file the build's plugins read through `node:fs` —
plus the `tsconfig.scripts.json` program for the compilers; "tracked" means held by the HEAD tree. A
known-answer fixture plants three untracked files reachable only through an eager glob, a lazy array
glob and a CSS `@import`, and the gate must name exactly those. **Pinned by**
`src/core/tracked-sources.test.ts` — 6 of 6 re-run green at `443a05a`. During the wave it was red on
exactly `src/app/theme-preference.ts`, which the build imported before it was committed; the commit
closed that, and the orchestrator's full run at `443a05a` is green. Reported mutations: the old static
walker and a disabled fs-read recorder each turn the known-answer test red.

### R48. F2 — three tests made zero assertions and four could pass vacuously — FIXED, with a runtime guard for the class
Found by the re-grade (F2 overturned PASS → UNPROVEN, its new item 8). **Fix (R4), verified in
code:** `src/test-setup.ts:36–41` is an `afterEach` that fails any passing test whose
`expect.getState().assertionCalls` is 0, naming it; `vitest.config.ts:65` installs it through
`setupFiles`. The only opt-out is Vitest's own `expect.assertions(0)` with a mandatory
`assertion-guard:` comment (none in use, reported). The three zero-assertion tests
(`compiler-fidelity` null port, `motion-inventory` keyframes, `engine.test` catch-all phrase) and the
four vacuous ones (`engine.test` implication, `ip.test` 5 of 9 pinned, `status-telemetry` element
presence, `camera.keyboard` press moves) were pinned. **Pinned by** the guard's self-proof in
`src/core/scripts-typecheck.test.ts` ("the guard ran in this very worker…", and a child Vitest under
the real config that must fail on a planted zero-assertion test) and by the seven files themselves
(`compiler-fidelity` 9, `engine.test` 79, `ip.test` 25, `status-telemetry` 8, `camera.keyboard` 6,
`motion-inventory` 24) — all re-run green with the guard live, as is the orchestrator's full 1714-test
run, so no test at `443a05a` completes with zero assertions. Reported: its first run found exactly
the three. F2 is not re-graded here.

### R49. C6 — the §4.8 motion inventory was false against the code, and its test never read CSS transitions — FIXED; its `@keyframes` scan was vacuous at `443a05a` (re-grade) and was restored in wave 4 (R61)
Found by the re-grade (C6 overturned PASS → UNPROVEN, its new item 6): §4.8 promised an 18 ms per-hop
stagger and a 140 ms palette animation that do not exist and omitted about eight running transitions.
**Fix (R4).** `motion-inventory.test.ts` now parses every `transition`/`animation` declaration in
every stylesheet and root-HTML `<style>` (tokens resolved), discovers script motion structurally
(`*_MS` progress divisors, inline transitions, exported eases, OrbitControls damping), and checks
§4.8 both ways, with a liveness test that feeds the old rows back in and must report the stagger, the
palette and the omissions. §4.8 was rewritten (verified: `design-brief.md:829` "ONE reveal … There is
no per-hop stagger"). The dead `.stage-dim` rule (a 240 ms fade nothing applied) was deleted by the
gate with its §4.8 row, and two other claims that the Stage dims were corrected (verified:
`.stage-dim` survives only in comments, `shell.css:558` and `design-brief.md:150`). **Pinned by**
`src/core/motion-inventory.test.ts` — 24 of 24 re-run green. Reported: the old brief turns it red
(5 failed); computed styles in the running app match the rows. The packet loop (1600 ms × 3) is stated
as unexercisable on the depth-1 snapshot. C6 is not re-graded here.

**Status after wave 4.** The 24 green tests above did not include a live keyframe scan: at `443a05a`
the regex had lost its escapes (`/@keyframess+([w-]+)/g`) and matched nothing, which the re-grade of
`443a05a` found. Restored with a known-answer case in wave 4, which also added the delayed-motion
scan and the §4.8 hold row (R61; `motion-inventory.test.ts` 27 of 27).

### R50. F1 scope — `vite.config.ts` and `vitest.config.ts` were in no type-checked project — FIXED
Found by the re-grade (its new item 12): `minWorkers: 1` was silently ignored (TS2769; removed in
Vitest 4) and `vite.config.ts` ended in `as any`. **Fix (R4), verified in code:** both removed
(`vitest.config.ts:58` keeps only a comment; `vite.config.ts:32` says why there is no `test` block);
`tsconfig.config.json` (new, tracked) covers both configs; `package.json:11–12` — `build` type-checks
the config project, and `typecheck` runs all three projects. `docs/acceptance.md` F1 now names the
third project (verified). **Pinned by** `src/core/scripts-typecheck.test.ts` (12: every authored
TS/JS file Git does not ignore is in some project; a planted `minWorkers` and a planted type error must
be reported) — re-run green; the orchestrator's `tsc -p tsconfig.config.json` exits 0. Reported: the
build output is byte-identical before and after (15 files, sha256). The declared exclusion that
remains is O27.

### R51. E3 — the first device selection after load put a 55–79 ms task on the interaction path, and the harness spent that selection before measuring — FIXED IN CODE; laboratory evidence only
Found by the re-grade (E3 overturned PASS → FAIL, its new item 9). **Harness (R5), verified in
code:** `measure-inp.mjs` no longer primes J2 with a selection, and reports a separate
`J2-first-select-device-3d` journey, one fresh browser per trial (`:744–746`, default
`core2:15,core1:3,dist1:3`); `docs/acceptance.md` E3 names it (verified). **Product, verified in
code:** the warm-up now draws the interaction visuals' programs in non-presenting warm-up steps
(`scene.ts:507–523`, `:2814` `withInteractionVisualsPrimed`; the cause was 105–128 ms of
`getProgramInfoLog` on the first real draw), and a canvas click acknowledges on the scene inside the
input task while the cross-surface store write waits until the browser's Event Timing entry for that
pointerup reports it presented, with a frame-count fallback (`Fabric3D.tsx:695–702`,
`deferPastPaint.ts:79` `deferPastPresentation`). **Pinned by** `Fabric3D.test.tsx` (61, including
"every journey's pre-loop hooks perform none of the input its measured act performs", `:1744`) and
`scene.test.ts` (39) — re-run green.

**Not established.** Reported laboratory runs only: the R5 cluster on a contended host (36 % busy) —
first selection 0 of 21 trials with an on-path task over 50 ms, INP p95 64 ms; the gate's final
`measure-inp` — all 7 journeys E3-clean but on battery with a Teams meeting in the foreground, so
`host-env.mjs` withheld it; E3's across-runs verdict for that build is INSUFFICIENT RUNS (0 of the 3
quiet runs needed). E2's warm J2 p95 moved from 40 to 88 ms (the click's presented frame is now the
canvas's own acknowledgement), still under 200 ms. See O25. E3 is not re-graded here. **Status after
the re-grade of `443a05a`:** J2-first was E3-clean in all 3 of its runs, and in the wave-4 gate's run
(21 of 21 trials, p95 96 ms) — laboratory only, on busy hosts (O25).

### R52. Harness defects from the re-grade (its item 15) — the headed window larger than the screen, and the popping check's divide-by-zero — FIXED; the palette keystroke race is not
- **Headed window (class fix, R5 and the gate).** Every headed harness launched at a fixed
  `--window-size=1940,1180`, larger than the reference host's 1280x752 DIP work area at DPR 1.5.
  `review/host-env.mjs:118–208` now owns `planWindow`, `windowInside`, `headedWindow`,
  `windowBoundsCheck` and `windowFitsOf`; `measure-inp`, `measure-fps`, `audit-e5-sweep`,
  `audit-e5-coldload` and `_audit_perf_e4_indep` take the plan and gate `acceptanceEvidence` on the
  window fitting (verified: no fixed `1940` size survives outside comments). **Pinned by**
  `src/core/headed-window.test.ts` (5, finding the harnesses from the directory, not a list) —
  re-run green.
- **"Infinityx" (R5).** `capture-motion.mjs` divided a spike by a neighbour median of 0. The reference
  rate is now `max(neighbour median, SPIKE_NORM_FLOOR)` (`:145` `SPIKE_NORM_FLOOR: 1.6`, `:698`),
  stated against the largest smooth-motion rate of the 2026-09-22 run (4.53 levels/px; 3 × 1.6 = 4.8).
  Stated cost: in sequences whose neighbour rate is below 1.6 (dolly ≈ 0.7) the spike bar rises to
  4.8 levels/px. **Pinned by** `render-c5-repairs.test.ts` (14, including "an ordinary camera step
  among sub-pixel frames that changed nothing is NOT a pop (the Infinityx artefact)" and "a real pop
  among near-still frames still fails, and its ratio is finite") — re-run green. The orchestrator
  confirmed no other capture-motion threshold changed since `d3e2a1c`.
- **Shots root (R2).** `capture.mjs` honours `ATLAS_SHOTS` (verified, `:27–30`): two concurrent
  `twice` runs sharing `review/shots/_twice` had deleted each other's captures. F6 must be run with its
  own root while other agents capture.
- **Palette keystroke race in the A1 census** — not addressed; O28.

### R53. Claim consistency (re-grade item 13) — the compiled coverage record's bare `aclLinesUnevaluable: 1` beside a status bar saying 6 of 12 lines cannot be decided — FIXED on both tabs that show it
A lead from the B6 refuter. The counter is the collector's parser flag only; the undecidable set is
the union `aclUndecidability()` (`core/acl-coverage.ts`) computes. **Fix, verified in code:** the
Inspector's Data tab labels the field as the parser's flag beside the union count
(`Inspector.tsx:1012`), and the gate gave `JsonView` a per-path `annotations` prop (`JsonView.tsx:335`,
drawn at `:687`) through which the JSON tab — where the whole `fabric.json`, and so the grader's bare
`1`, is shown — carries "parser flag only; undecidable: N of M ACL lines — aclUndecidability()…"
(`Inspector.tsx:652`, `:1260`). **Pinned by** `Inspector.test.tsx` (50, including "the compiled
coverage record's aclLinesUnevaluable is labelled as the parser's flag, beside the union", "the JSON
tab annotates the same field the same way…" and "draws a note on exactly the annotated row, and on no
other") — re-run green. Reported: the note is 450 px and shown whole at 1440 and 1024. R1 found no UI
path that opens the `coverage` citation in the Data tab, so the JSON-tab note is the one a reader meets.

> **Repair wave 2c (reconciled 2026-09-23, committed as `1d19e22`).** Entries R26–R38 and the moved
> O10, O15 and O18 below, and the rewritten O12, O16, O17 and O20 plus the new O21–O23 under Open,
> record what the five wave-2c repair clusters (focus return / D3, band and labels / B1, layout / C2,
> motion / C5–C6, provenance / O15–F2–F3) and the merged-tree gate reported. **Every FIXED below was
> checked by the reconciler before it was written:** the code named was read at the line given, and
> the named tests were re-run in one invocation (35 files, `Tests 649 passed (649)`, exit 0), and both
> `tsc` configs exit 0 (`tsconfig.json`; `tsconfig.scripts.json` with `--noImplicitAny`). On a
> scratch `vite build` of `1d19e22` served on its own port (stopped afterwards) the reconciler also
> re-ran `node review/audit-d3-focus.mjs` (`210 case(s), 0 failed.`, exit 0) and
> `node review/capture.mjs text` (`PASS selftest 17 of 17`, `PASS wrap 0 unjustified`, `PASS text
> 72 of 72 states`, exit 0), and ran `node review/mutation-check.mjs` (18 of 18 KILLED, exit 0,
> `node_modules` intact afterwards). The orchestrator verified the full suite at `1d19e22`
> (`vitest` 121 files, 1571 tests, exit 0) and ran `node review/capture-motion.mjs` (exit 3, O16).
> **Not re-run by the reconciler, and cited as "reported" wherever it appears:** `capture.mjs app`,
> `capture.mjs twice 5` (F6), `capture.mjs reduced` (D7), the INP and cold-load harness runs, the
> agents' in-page probes and screenshots (they live in the orchestrating session's scratchpad, not
> in this repository), and every agent mutation other than those `mutation-check.mjs` executes. As
> before, a fixed defect does not by itself move its acceptance criterion; nothing here is a re-grade.
>
> **History as of wave 2c** (it continues in the wave-3 banner above). `50a3dc5` (root; rebuilt marker-free from the original `857b520`, see O10) →
> `254694b` (checkpoint of the interrupted wave-2 tree, suite red on purpose at 15 of 1465) →
> `1d19e22` (repair wave 2c). A sha `857b520` anywhere below refers to the superseded root.

### O10. The nested repository and the untracked tree — DECIDED (own local repository) and RESOLVED by commit; `tracked-sources.test.ts` GREEN at `1d19e22` but its denominator was wrong (re-grade), rebuilt in wave 3 (R47) and GREEN at `443a05a` (moved from Open, 2026-09-23)
Originally recorded (acceptance F2, 2026-09-22) as OWNER DECISION: `src/core/tracked-sources.test.ts`
was red on 19 untracked runtime-imported modules, compiled files and compilers (17 at acceptance),
and `atlas-scope/.git` had been created by a repair agent without being asked (filesystem birth time
of `.git` 2026-09-21 09:09:53 +0300), with a single commit that postdated the fixes whose "failed
before" it was meant to anchor.

**Decision (2026-09-23).** Taken by the orchestrator on the owner's delegated instruction to take the
best decision: Atlas Scope keeps its own repository at `atlas-scope/.git`, local, with no remote. It
is not folded into the parent repository and not re-initialised.

**The root was rebuilt before its first real use.** The original root `857b520` carried an absolute
home-directory path in a comment in `src/forwarding/engine.test.ts`, and the Windows user name in that
path is one of the parent repository's client-marker patterns. It was replaced by `50a3dc5`, which
differs from `857b520` by exactly that one line — verified by the reconciler with
`git diff --stat 857b520 50a3dc5` (`src/forwarding/engine.test.ts | 2 +-`, one insertion, one
deletion); the new line names "the engine repository root — the parent of atlas-scope/" instead.
`857b520` is on no branch; every older citation of it in this file and in `docs/` means that
superseded root. History since, from `git log` (re-read at `443a05a`): `254694b` ("wip: checkpoint
the interrupted wave-2 tree", committed red — 15 of 1465 — so that each failing test is on record
before its fix), `1d19e22` (repair wave 2c), `d3e2a1c` (docs only: this file's wave-2c record and
the re-grade of `1d19e22`) and `443a05a` (repair wave 3); since then `1c829c9` (docs only),
`2d9712c` (checkpoint of the interrupted wave-4 run), `8e873d2` (repair wave 4) and `70bea72` (the C5
tier pin), read from `git log` at `70bea72` (the wave-4 banner). Every commit candidate is scanned with the parent repository's own marker
patterns (`cisco_toolkit/distribution_verify.py` `_client_marker_patterns`) before it is committed.

**The untracked-files half is resolved by commit.** `254694b` tracked the 19 files and `1d19e22`
tracked `tools/source-binding.mjs` (the one new module every compiler imports). At `1d19e22`
`git status --short --untracked-files=all src tools` lists nothing, the orchestrator's full run is
green (121 files, 1571 tests, exit 0), and the reconciler's targeted run includes
`tracked-sources.test.ts` green ("no runtime-imported module, compiled file or compiler is
untracked"). The test was not loosened.

**Superseded in part by the re-grade of `1d19e22`.** "GREEN" was true but not sufficient: the
refuter planted an untracked `src/forwarding/zz-untracked-probe.json`, the test still passed 3 of 3,
and the file shipped in the built `mount-*.js` — the walker did not follow `import.meta.glob`
(`Inspector.tsx`), the two preview pages, or CSS `@import`. The gate was rebuilt on the bundler's own
module graph in wave 3 (R47); at `443a05a` it is green, 6 of 6 (reconciler), and the one file it
named during the wave, `src/app/theme-preference.ts`, is tracked (`git ls-files`).

**What this does not establish.** No criterion is re-graded here. The re-grade re-ran F1, F2 (unit
half), F4 and F5 on a clean clone of `1d19e22`; the re-grade of `443a05a` reproduced F5 from a real
`git clone` of `443a05a`, and nothing else has been run from a clone since (O23). At `70bea72`
`tracked-sources.test.ts` is green, 6 of 6 (reconciler): `src/core/route-fields.ts`, the one file wave
4's gate left untracked, is tracked in `8e873d2`. The source snapshot still lives in the parent repository, so
`git show HEAD:<source>` inside `atlas-scope` cannot reach it. `50a3dc5` inherits `857b520`'s
limitation as a provenance baseline; `254694b` → `1d19e22` is the first pair in this history in which
failing tests were committed before their fixes (R34).

### O15. F5 — the recorded source digest bound CRLF working-tree bytes, not the committed blob — FIXED (moved from Open, 2026-09-23)
Found by the acceptance refuter: `meta.sourceSha256` was `9cc348bd…5dfd`, the Windows CRLF checkout of
`webapp/sample_data/sample_fleet.snapshot.json`, so F5 held on this host's disk only.

**Fix (wave 2c, provenance cluster; the three consumer and wording changes applied by the gate).**
`tools/source-binding.mjs` (new, tracked in `1d19e22`) is the one owner of the binding rule: it hashes
the LF-normalised bytes and records `meta.sourceDigestForm: "lf-normalised"`. All four
`tools/compile-*.mjs` import it; `provenance.test.ts` enforces that by globbing `tools/`. Every
sidecar consumer fails closed on any binding mismatch through `types.ts` `sameSourceBinding` (digest,
form, byte length, source) — verified in code: `bindings.ts:51`, `rib-completeness.ts:60`,
`producer-emission.ts:32`. The Inspector, Header and StatusBar label the digest and byte count as
LF-normalised.

**Verified.** By the orchestrator: `fabric.json` and the three sidecars all bind
`9580aa092d490a13ba420b2cc670ddee026f6dbf93ecc5aeac2fc94cd7f13089` (3,072,771 bytes, form
`lf-normalised`), which equals `git cat-file blob HEAD:webapp/sample_data/sample_fleet.snapshot.json |
sha256sum` in the parent repository, and recompiling `fabric.json` is byte-identical. Re-checked by
the reconciler: the four `meta` blocks read as above; the parent's blob hashes `9580aa09…3089` and is
3,072,771 bytes; `sha256sum src/data/fabric.json` is `2f558c38…a308` (at `1d19e22`; it is
`a1a599b8…d251` since wave 4's B6 compiler change, with the source digest unchanged — R54). **Pinned by**
`src/core/provenance.test.ts` (the CRLF-vs-LF binding test and one "writes the same bytes from a CRLF
checkout as from an LF one" test per compiler), `src/forwarding/bindings-trust.test.ts` ("every
source-bound sidecar consumer fails closed on any binding mismatch", which finds sidecars
structurally), `src/panels/producer-emission.test.ts`, `Inspector.test.tsx` ("names the byte form its
digest and byte count are taken over") and `Header.test.tsx` ("… (O15)") — all re-run green.
`mutation-check.mjs` reverts `lfNormalise` and the form-aware trust check (both KILLED in the
reconciler's run). Reported before the fix: `Tests 12 failed | 10 passed (22)` in provenance.

**Digest pins, same cluster.** `review/layout-guard.mjs`, `devHandle.ts` and `devHandle.test.ts` carried
the stale tag `9cc348bd58bb`; they now derive it, and `provenance.test.ts` "no authored code file pins
the snapshot digest" (green) fails on any hex literal of 8+ characters that prefixes the bound or the
working-tree digest. By design, links minted before the change are refused as snapshot mismatches (the
tag moved from `9cc348bd` to `9580aa09`). **F5 is not re-graded here** (O23).

### O18. Motion-inventory residuals — CLOSED (moved from Open, 2026-09-23); the keyframe-scanner proof below did not hold at `443a05a` (re-grade) and was restored in wave 4 (R61)
Both items are done. `src/ui/primitives.tsx:1693` (Skeleton comment) now says "looping animation that
runs in this product" (verified). The dead `.stage-pending__spinner` / `@keyframes stage-pending-spin`
CSS was deleted (a comment at `App.css:343` records it) and the §4.8 row with it. **Pinned by**
`motion-inventory.test.ts` "no stylesheet declares an unbounded loop and nothing renders the deleted
spinner…" and its first test, which proves the keyframe scanner live on a planted stylesheet — re-run
green. **Contradicted at `443a05a`** by the re-grade of that commit: the scan's regex had lost its
escapes (`/@keyframess+([w-]+)/g`) and returned `[]` against the planted `@keyframes
stage-pending-spin`; it hid nothing, because `src/` declares no keyframes. Wave 4 restored it with a
known-answer case that fails on the de-escaped form (R61).

### R26. D3 — focus fell to `<body>` after the snapshot popover, and on every Inspector close path — FIXED
Found by the acceptance grading (D3: popover, Tab, Escape → `BODY`; `Header.tsx:479` fell back to
`e.currentTarget.blur()`). Cause, established by the focus-return cluster from history: wave 1 added a
Tab-out handler to the Popover primitive (`primitives.tsx:1064–1088`, absent in `50a3dc5`); Tab off the
panel's last control closes it and focuses the query input, whose focus event records the popover's
Copy button as origin; that button unmounts, and Header's latent blur arm fired. The rewritten runtime
audit then found a second, unreported path: the Inspector's close (`focusReturn?.focus()`, no fallback,
origin recorded only by `openInspector()`) landed on `BODY` in 24 of 210 cases — every close of an
Inspector opened with `i`, and two citation-opened cases.

**Fix.** One owner, `src/app/focus-return.ts`: the recorded target, else its opener (captured through
`aria-controls` at record time), else explicit fallbacks, else the labelled region landmark; it never
blurs. Every decider routes through it — verified in code: `Header.tsx:481`, `DataGrid.tsx:895`,
`Inspector.tsx:695–705` (invoker recorded on every open path; returns only when focus is on `<body>` or
null, so closing by moving focus elsewhere is not overridden; `#stage` fallback), `keyboard.ts:537/540`,
`CommandPalette.tsx:259/455`, `StatusBar.tsx:136`, and the Dialog cleanup at `primitives.tsx:1314`.
`PENDING_ROUTING` in the guard is empty (`focus-return.guard.test.ts:367–370`).

**Pinned by** `src/app/focus-return.guard.test.ts` (one `ts.Program` over the vitest include globs with
a partition check, symbols resolved rather than names; rejects `blur` calls, un-owned `isConnected`
fallbacks and `.focus()` on a captured `activeElement`/`relatedTarget` origin; a shrink-only ratchet),
`Header.focus-return.test.tsx` (3), `DataGrid.focus-return.test.tsx` (3), `Inspector.test.tsx` "closing
the Inspector never drops focus to <body> (D3)" (3), two D3 tests in `CommandPalette.test.tsx` and one
in `coverage-focusout.test.tsx` — all re-run green. The runtime audit `review/audit-d3-focus.mjs` was
rewritten (5 states × 2 viewports; a case that did not open is NOT DRIVEN and fails; every required
kind must be driven) and re-run by the reconciler on the scratch build: `210 case(s), 0 failed.`,
`Driven, by kind: dialog=8 popover=105 field=32 grid=16 tab=33 find bar=6 inspector=9 copy=1`, exit 0.
Reported: 24 failures before the Inspector change, 40 with the Header regression re-planted; reverting
Header turns 3 tests red, reverting `DataGrid.leaveGrid` turns 5 red.

**Recorded alongside.** No toast component exists in this build (the old audit counted the visually
hidden `#sr-alert` live region as one). `DataGrid.leaveGrid` is not reachable from the running findings
queue, because `PriorityQueue`'s `onEscape` consumes every Escape; the grid tests pin the grid's
contract for hosts that let Escape through, and the comments now say so. The Dialog deliberately
returns to a bare element, not an opener fallback, which would pre-empt the palette's own landing. The
agents' D1/D2 re-drives (36 unique stops, no trap; one `tabindex=0`, `aria-rowcount` 152) are
reported. D3 is not re-graded here; no real screen reader was used.

### R27. B1 — four surfaces bypassed `presentBand`, and the `is:healthy` note misattributed its undecided rows — FIXED
From O12's B1 residual (acceptance B1 FAIL: `is:healthy` answered yes for five qualified hosts). The
surface fix landed in the interrupted wave 2 and was committed in `254694b`; wave 2c verified it and
fixed a new defect. **Structural guard:** `src/core/band-read.guard.test.ts` resolves every read of
`Device.band` with the type checker and allows it only in `band-qualification.ts`; its liveness test
plants a module that reads the band under any name, by destructuring or laundered, and it is flagged.
Reported mutations: raw reads planted in `query.ts` turned the guard and three behavioural tests red; a
destructuring rename and an optional element access planted in `PriorityQueue.tsx` were flagged.
**New defect, found live:** the Findings note said "14 of 146 name no device the fleet knows", true of
F142 only; the other 13 name qualified hosts whose own answer is undecided. `query.ts` now splits the
count, `ClauseScope` carries `undecided`, and the note says no device is *decided* to match. **Pinned
by** `query.band-qualification.test.ts` ("is:healthy answers no qualified host with yes",
"-is:healthy does not turn the qualified hosts into a decided no either", "the is:healthy note over
findings says WHY rows are undecided…"), `band-read.guard.test.ts` and
`band-qualification.surfaces.test.tsx` — re-run green. Reported red before: `expected '14' to be '1'`.
The running-app checks (chassis `E*`, legend "Excellent, partial · 2", palette pill "Excellent
(partial)") are reported from the agents' frozen-build screenshots. B1 is not re-graded here.

### R28. C2 — identifier splits, an overrun, a hidden tab and identical placeholders, and a detector that could not see them — FIXED; R25's "72 of 72" superseded, then re-established under the wider detector, which the re-grade found blind to scroll-port clipping (closed in R46)
Found by the acceptance grading (C2: `(num_power_supplie / s)`, Raw tab off the pane edge, both IP
placeholders `10.0.10.50`). Wave 2c found more of the same class once the detector could see it:
`acls.core1.PROTECT_SERV / ERS[3]` and `collection_completenes / s` in citation paths (dark and light,
1440, states 06 and 08), and `(num_power_supplies)` running 4.9 px past its not-observed box once it
could no longer split.

**Fixes.** Prose blocks carry no token-break licence; a licence is allowed only with an
`UNBREAKABLE-TOKEN CONTAINER` justification (`primitives.css` "wrapping"; kept on `.hop__raw` and
`.insp-sha`), and nine unjustified licences in `PathTrace.css`, `PriorityQueue.css:771` and
`App.css:455` were removed. `Cite` renders a `<wbr>` after each identifier separator
(`primitives.tsx:1733`, used at `:1768`; text and `aria-label` unchanged). `.ui-notobs__why` lost its
`min-inline-size` floor below its longest token. `.ui-tabs` wraps with a thin visible scrollbar as
backstop. `PathTrace.tsx` derives `EXAMPLE_ADDRESSES` — source `10.0.10.50`, destination `10.0.30.10`
from a different observed subnet — and each validation message names its own field's example.

**The detector.** `readTextFidelity` now flags a break inside any whitespace-free token with no boundary
character beside it, a split exactly between two text nodes (a `<wbr>`, `<br>` or atomic inline between
them is sanctioned), and a line that overruns its block's content edge. `node review/capture.mjs wrap`
statically fails every unjustified licence, and `selftest` runs 17 known-answer cases; `text` cannot
PASS while a detector is blind. **Pinned by** `primitives.test.tsx` (`Cite`: 2 tests) and
`PathTrace.test.tsx` ("the flow form's example addresses": 4) — re-run green — and by the harness,
re-run by the reconciler on the scratch build: `wrap` 0 unjustified, `selftest` 17 of 17, `text` 72 of
72, exit 0. Reported: `text` 68 of 72 and `wrap` FAIL 9 before the cross-cluster changes; re-injecting
each old rule brings its finding back.

**R25's wave-1 "PASS 72 of 72" is superseded:** it was measured with a detector that exempted
identifiers, node-boundary splits and overruns. The 72 of 72 above is the first measured with them.
During the wave the official `twice 5` read NOT ESTABLISHED (text findings count as render failures);
the gate reports `F6 PASS: 32 of 32 frames byte-identical across 5 runs` once `Cite` landed — reported,
not re-run by the reconciler. Descender clipping remains undetected (O17).

**Found blind again at the re-grade of `1d19e22`:** the 72 of 72 above could not see a control clipped
by its own scroll port (the path form at 1440 and 1920). `readFormReach` closed that in wave 3 (R46).

### R29. C6 — the emphasis, hover and halo fades were exponential and settled in 417–1,350 ms; the tier fade sat at 300 ms; the inventory could not see rAF eases — FIXED
Found by the acceptance refuter (C6 overturned to FAIL). **Fix.** `src/fabric3d/emphasis.ts` owns
finite eases — `RECEDE_MS = 240`, `HOVER_MS = 80`, `SELECT_MS = 140` (verified at `:76–80`) — that land
exactly on their target on the first frame at or after their duration and snap under reduced motion;
`TIER_FADE_MS = 280` (`scene.ts:2347`), so its end state shows before 300 ms at 60 Hz. §4.8 rows state
each duration and its settle time at 60 fps (250 / 83.4 / 150 ms). Mid-ease values depend on frame timing; the
settled value does not, because `easeValue` returns the target itself — which the `determinism:` notes
on `stepEaseChannel` and `stepEmphasis` state, and `determinism.test.ts` accepts.

**Pinned by** `src/core/motion-inventory.test.ts` (steps every exported ease against its §4.8 row; a
TypeScript-compiler scan that fails any exponential per-frame step — `x += (t-x)*k`, `k = f(dt/*_MS)`,
`damp()`, `x = lerp(x,…)`, and, widened in the continuation pass, the in-place `v.lerp(t,k)` /
`q.slerp(t,k)` spelling unless the receiver is a call chain or re-initialised in the same function),
`src/fabric3d/emphasis.test.ts` (settle within the `RECEDE_MS` row; bit-identical landing under
steady, jittery and coarse frame timing) and `determinism.test.ts` — re-run green. Reported red before:
"the recession settled at 1333.3 ms; §4.8 states 250 ms" and "TIER_FADE_MS = 300 ms can first show its
end state at 316.7 ms". The motion harness's fade item passed 24 of 24 at 266.5–266.7 ms (reported by
the agents; the orchestrator's `capture-motion` run shows it passing). The gate limit it exposed is O22.
The eases and settle times above stand; what the re-grade of `1d19e22` contradicted was the rest of
the §4.8 inventory this entry treated as closed (R24's note, fixed in R49).

### R30. C5 — label popping (O16's label half) — FIXED
Found by the C5 motion harness (O16: 29–31 label blinks, clustered at fly-to starts). **Fix.** Every
per-label show/hide decision over time goes through `labelResolve.ts` `labelDwellVerdict` (minimum
dwell, no appearing while the camera moves, a one-pass hold, urgent labels exempt) for both the scene
resolver and the DOM declutter; a hovered label is urgent only on a still camera (`labelUrgent`, and
`scene.ts:1874`). The settled pass (history-free, for F6) can no longer reverse a label younger than the
dwell: the resolver requests frames while it would (`labelSettleMayReverse`), and the DOM layer reports
`reportLabelsConverging`, which `scene.ts` now folds into `labelsSettled()` and `converged()` —
verified at `scene.ts:1587`, `:3366`, `:3637`, `:3641` (applied by the gate). **Pinned by**
`FabricLabels.dwell.test.tsx` (10, including DOM-vs-resolver parity and "a name that left in a move
shorter than the dwell does not blink back when the scene settles"), `labelResolve.test.ts` (the
settle-reversal tests), `FabricLabels.settled.test.tsx`, `render-c5-*.test.ts` and five
`scene.test.ts` tests — re-run green. The `scene.test.ts` five are **source-text tripwires**, not
behaviour: they check that `scene.ts` declares and reads the report, and the behavioural contract lives
in the DOM test's fake scene. Reported: `label blinks 0` in all 24 `capture-motion` sequences (agents
and gate) and 0 in 36 frozen-build probe sequences, down from 31; one DOM trade on the shared, HMR-edited
dev server did not recur and is not authoritative. Informational, no change: scene label age advances
per resolver pass while the DOM's advances per rAF.

### R31. C5 — the "z-fighting" clusters were not depth ties; three geometry sources removed — FIXED (what then still failed was edge shimmer, O16 — fixed in code in wave 3, measured PASS in the re-grade of `443a05a`'s laboratory run, and PASS with every C5 item in one independent run at `70bea72`, R60)
A per-frame camera replay and a raycast of every flip-flop cluster found no ray crossing two chassis
surfaces within 0.02 units (reported). Three sources were isolated and removed: the faceplate frame's
top bar seen from above (a body-painted hood, `chassis.ts`); overlapping `LineMaterial` round caps at
cable joints (discarded inside a cable, `cables.ts`); and one true coplanar overlap, the distribution
role glyph's crossing arms. **Pinned by** `src/fabric3d/geometry/chassis.coplanar.test.ts` (every
chassis part, role glyph and state ring checked for same-facing overlaps within 0.002, a from-above
check that the front edge is paint, and a liveness case) and `cables.ink.test.ts` "every cable stroke
discards LineMaterial's round cap…" — re-run green. The app `tsc` error this new test briefly caused
(TS2459, `QualityTier` not exported) is gone: it imports from `../contract`. Reported: mutations M6/M7
(hood removed, equal arms) turn it red; the cap discard's outer-bend notch was measured at worst 1.23°,
3e-4 px deep — a measurement not re-run. Also recorded: the A5 grader's camera-proxy coordinates could
not be reproduced with the agents' metric; double-click still moves to core1 and Reset returns to the
same rest projection (no camera code changed).

### R32. C5 — light-theme links read as ~1 px — FIXED in code; the width figures are reported, not verified
Root cause (reported): edge coverage was blended in the linear HDR buffer before the AgX tone map, so on
the light stage a half-covered pixel landed only 16–18 % of the way to the ink. **Fix:**
`coverageGamma(tokens)` (`cables.ts:207`), fitted through the real AgX curve over every `classifyLink`
token and applied to every cable batch, trace stroke and the ghost wireframe. **Pinned by**
`cables.ink.test.ts` ("the defect is real without the correction…", "every cable material the fabric
builds applies the palette's gamma…") — re-run green. **Not verified:** the painted-width figures (light
2 px class median 1.96 / p10 1.84 against dark 1.88 / 1.74, from a perpendicular probe that also showed
the earlier scanline p10 1.89 was angle-confounded) come from a probe in the orchestrating session's
scratchpad; there is no browser gate for stroke width.

### R33. F2 test quality — a tautological tamper test, an unpinned guard, a mislabelled test, and a label test that pinned nothing — FIXED
Found by the acceptance grading (F2) and, for the last, by the band/labels cluster.
`provenance.test.ts`'s tamper test now goes through the gate `fileIsCompilerOutput` ("detects a
hand-edited acl-bindings.json — the failure path, through the same gate"). The `claims.ts:470`
empty-hop guard became dead code on every input after R34 and was removed (a comment at `claims.ts:477`
records where the rule lives); "an EMPTY traversal earns no badge above INDETERMINATE under any outcome
word at all" pins the rule. `claim-honesty-b1.test.tsx:145` is renamed to what it proves ("the undecided
denial is offered no nearby flow at all…") and asserts its premise `ce.found === false`. And
`Fabric3D.test.tsx` "keeps a name off the chassis bodies the scene PROJECTS…" accepted
displaced-or-withheld after one frame, so under the two-pass hold its displaced branch never ran (it
stayed green with a name's own chassis made non-blocking); it is now three tests — withheld, a control
without core2's body, and "displaces a name one row UP…". All re-run green. The mutations that go with
them are reported, except the claims ones, which `mutation-check.mjs` executes.

### R34. `claimBadge` awarded SCOPED to an unrecognised outcome word (a C2/C3 follow-up) — FIXED; F3 gains an executable mutation run
Found by the provenance cluster following the acceptance report's open question: over ordinary,
fully-modelled hops, an outcome word the engine does not know earned SCOPED while `bandOfTrace` said
UNDETERMINED. **Fix:** `claimBadge` returns INDETERMINATE for any outcome whose `bandOfOutcome` is
UNDETERMINED. **Pinned by** `claims.test.ts` ("an unrecognised outcome word over a clean, fully-modelled
traversal is INDETERMINATE, not SCOPED", the zero-hop case, and a sweep over every UNDETERMINED word) —
re-run green; reported red before, `expected 'SCOPED' to be 'INDETERMINATE'`.

**F3 evidence.** `node review/mutation-check.mjs` copies the tree to a scratch directory and reverts
every recorded guard of every engine `refutation.md` names, plus two O15 guards. Re-run by the
reconciler: 18 of 18 KILLED (engine 4, blast 2, layout 2, query 1, compile-snapshot 2, claims 5,
source-binding 1, bindings 1), exit 0, printing its own LIMIT — it does NOT recreate pre-fix history.
`refutation.md` §6/§7 now record C2 as FIXED (verified at `:229` and `:341`). Separately, `254694b`
committed tests written ahead of their fixes red (provenance 8, motion-inventory 4, determinism 1,
source-hygiene 1, per its commit message; not re-run at that commit by the reconciler), so for those
tests "failed before the fix" is now in history. F3 is not re-graded here.

### R35. D8 refuter question (state 06: "on core1 denies this flow" beside "? UNDECIDED") — NOT A DEFECT, now pinned
Raised by the acceptance D8 refuter and assigned to no group. The 3-D chip's ending (`traceMarkOf`), the
claim card and the hop list read the same claim owner (`bandOfHopIn` / `bandOfTrace`); "denies this
flow" is the ACL line's evidence quoted inside a card that says "That denial is not decided". A pin in
`claim-honesty-b1.test.tsx` for 10.0.10.50 → 10.0.30.10 tcp/3389 (raw outcome denied, band
UNDETERMINED, mark undetermined, card matches /not decided/) is green. Reported mutation: forcing
`traceMarkOf` to "blocked" on a denied outcome gives 2 failures.

### R36. `--sev-high` brief drift was 31 drifted colour tokens — FIXED, and now guarded (O20's first item)
The motion cluster found that design-brief §3.3 had drifted from `src/core/tokens.css` on 18 light and
13 dark tokens, not only `--sev-high`, and reconciled all 31 (the chip table and canvas-contrast rows
recomputed; tokens.css named authoritative). Its report said no test guarded it; the merged-tree gate
then added one: `contrast.test.ts` "design-brief §3.3 restates tokens.css exactly" (every
`--token:#hex` in §3.3.1 and §3.3.2 and the severity-chip fills) — 3 tests, re-run green. Reported
mutation: writing `#a14a0a` back into the brief turns it red.

### R37. E1/E3 harness gaps and the E5 probe placement — FIXED in the harnesses; the runs are reported, not verified
Found by the acceptance grading (J1's verify spent the first selection; J4's verify ran before the
measured act) and O20 (E5 probes at fixed times; an unsanctioned pre-FCP carve-out). **Verified in code
only:** `review/measure-inp.mjs` checks each rep's effect after its timing (`repEffects`,
`repsWithEffect`, `verifyAfter` on the journeys that spent their first act), and
`review/audit-e5-coldload.mjs` aims probes at earlier runs' long frames, reports `keystrokeCoverage`,
and applies the pre-FCP carve-out only if `docs/acceptance.md` holds a line beginning
`E5 EXEMPTION (owner-sanctioned): pre-first-paint` (`:137`; no such line exists, see O20). **Not
verified:** the runs — J4 with its submit removed reads PASS on the old harness and NOT MEASURED on the
new; `6 pass, 0 NOT MEASURED` with 25 of 25 verified effects; E5 now failing on a 264.7 ms pre-FCP frame
and 14 slow keystrokes. Every one was on a busy host on battery, which the harness itself refuses as
acceptance evidence. E1–E5 are not re-graded.

### R38. Stale documents and a type doc comment — FIXED
From acceptance-report item 7 and B2's type drift. Verified by reading: `docs/acceptance.md` E3 (`:82`)
gives resizes 105–149.7 ms and eleven classes over 50 ms, with the eight input-handler classes marked
outside E3's claim (O21); the F5 row describes the LF-normalised binding and moving `fabric.json`
digests (`2f558c38…a308` now, matching `sha256sum`); F1 reads full strict (the reconciler's run of both
`tsc` configs exits 0, see the banner); F3 cites `mutation-check.mjs`. `refutation.md` §6/§7 are
corrected (R34). `types.ts` documents `claim` as prose of two or more sentences (comment only).

> **Acceptance-close wave 1 (reconciled 2026-09-22).** Entries R16–R25 below, and O10–O20 under
> Open (O10, O15 and O18 have since moved to Resolved, above), record the "Known issues carried forward" list of `docs/acceptance-report.md` and what four
> parallel repair lanes (claims-engine, fabric-surfaces, layout, compiler-evidence) say they changed.
> Each lane's claim was checked before it was written here: the code named was read at the line
> given, and the named tests were re-run by the reconciler in one invocation (16 files,
> `Tests 1 failed | 228 passed (229)`, the one red being `tracked-sources.test.ts`, see O10). The
> merged-tree gate after the wave: both `tsc` configs exit 0; `npx vitest run` exit 1 with
> `Tests 1 failed | 1415 passed (1416)` (tracked-sources only); `npm run build` exit 0;
> `node review/capture.mjs app` exit 0 (32 of 32 frames). **Mutation checks ("red again when the fix
> is removed") are the lanes' own reports and were NOT re-run by the reconciler**, which was barred
> from editing product source or tests; they are cited as reported. Nothing below is a criterion
> re-grade: a fixed defect does not by itself turn its acceptance criterion PASS.

### R16. F3 / refutation C2 — `claimBadge` never cross-checked the outcome against the hops — FIXED
Found by the acceptance grading (F3): refutation claims-C2 was "CONFIRMED and NOT fixed", and a
delivered trace whose only hop was a loop returned SCOPED. Reproduced by the claims-engine lane.

**Fix.** `src/core/claims.ts:217` `hopsSupportOutcome(trace)` (read through `bandOfHop`): no hop may be
undetermined, the last hop must band the same as the outcome, and a delivered outcome needs every hop
RESOLVED. Both callers use it — `isDecidedOutcome` (`:230`, which feeds band, tally and counterexample)
and `claimBadge` (`:475`, returns INDETERMINATE). Verified in code.

**Pinned by** `src/core/claims.test.ts`, block `REFUTED (C2)` (~line 342): a loop-only delivered
trace, every non-supporting hop verdict, a refused hop before the path's end, and a control that
really reaches SCOPED. Reported before the fix: `Tests 5 failed | 29 passed (34)`; after: 34 passed
(re-run by the reconciler: green). Reported mutation: `hopsSupportOutcome` → `true` gives
`4 failed | 30 passed`. A real-trace sweep reportedly changes no real trace's badge.

The stricter denial rule the lane declined is recorded as an owner decision in O11.

### R17. B8's only real near-miss rested on an outbound ACL applied to traffic addressed to the router — engine FIXED (B8 itself stays UNPROVEN, see O13)
Found by the acceptance refuter (B8): 10.0.10.50 → 10.0.30.1 was "denied" on tcp/3389 and "delivered"
on tcp/22 by `PROTECT_SERVERS`, which is bound *outbound* on core1 Vlan30 — but 10.0.30.1 is core1's
own Vlan30 address, so the packet is received, not forwarded out of Vlan30. The engine refused
router-owned *sources* and had no matching rule for router-owned *destinations*. Reproduced by the
claims-engine lane: of 12,059 swept flows, 2,542 denied or dropped, exactly 4 with a counterexample,
all to 10.0.30.1, all resting on this misattribution.

**Fix** (`src/forwarding/engine.ts`, same address-ownership index as the router-owned-source rule;
verified in code): `receivedAtOwner` (`:1759`, called `:2078`) — when the current hop owns the
destination, only its observed *inbound* bindings are evaluated; an observed inbound deny stays a
decided denial; anything else is an "unmodeled" hop with an indeterminate outcome whose claim says the
packet is received by the router and that control-plane/management/service ACLs are not modelled.
`receivedElsewhereEvidence` (`:1847`, used `:2208`) — when another collected device owns the
destination, a pass onto the connected subnet is no longer "delivered"; a transit outbound deny still
stands.

**Pinned by** `src/forwarding/router-destined.test.ts` (new): derives owned addresses independently
from SVI, FHRP virtual and `local` /32 records and sweeps every source subnet against every owned
address, with a control that transit traffic to 10.0.30.10 is still decided by `PROTECT_SERVERS`.
Reported before: 4 failed (e.g. `expected [ …(140) ] to deeply equal []`); after: 6 passed
(re-run: green). Reported mutation: removing both rules gives `4 failed | 2 passed`. In the running
app (lane's screenshots) the 10.0.30.1:3389 card changed from "denied at core1 by ACL PROTECT_SERVERS"
to an INDETERMINATE sentence naming core1 Vlan30 as the owner.

### R18. A2 (depth 1) — the hop header blamed routing for an ACL denial — FIXED
Found by the acceptance grading (A2): on tcp 10.0.10.50 → 10.0.30.10:3389 the hop header read
"denied by routing — table incomplete" (`HopList.tsx:120`) while the decider block said
`PROTECT_SERVERS` line 4. Two sentences about the same hop, from two sources.

**Fix.** `src/panels/HopList.tsx:118` `deciderAgent` takes the agent from `classify(hop.decidedBy)`,
the source the decided block uses; `UNDECIDED_WORD` takes that decider. The header now reads "denied
by ACL PROTECT_SERVERS — reached by a route from an incomplete table". Verified in code.

**Pinned by** `src/panels/HopList.decider-header.test.tsx` (new): the real flow, then every suggested
flow plus a source × destination grid, with preconditions that both ACL-decided and route-decided hops
occur. Reported before: 2 failed; after: 2 passed (re-run: green). Reported mutation: `deciderAgent`
returning "by routing" for an ACL fails both. The lane's "after" screenshot could not be captured (the
Browser pane stopped drawing); the after state was read from the page text. **A2 as a criterion stays
UNPROVEN**: multi-hop still cannot run on shipped data (max depth 1).

### R19. F2 — two hollow tests — FIXED; one out-of-scope defect exposed (O14)
Found by the acceptance grading (F2). `engine.counterfactual.test.ts:148`: its `toContain` loop ran
zero times because the rationale cites no ACL. `blast.test.ts:~400`: compared `f()` with `f()`.

**Fix.** The counterfactual test now checks both halves of its name behind preconditions (the
rationale cites exactly the ACL lines the candidate's own trace consulted — here none, and says "No ACL
line was consulted"; and none of the blocking host's candidate-generating permit lines is cited).
`blast.test.ts` gained a `repeatable()` helper that clones the first result, writes junk into it,
re-runs and compares against the clone, requiring non-empty results, plus a test proving the check can
fail (an aliasing memo passes the old form and fails the new). Both files re-run green by the
reconciler. Reported mutations: citing the candidate-generating line (the historical bug) fails with
`expected [ 'acls.core1.VOICE_FILTER[0]' ] to deeply equal []`; removing the junk-writing step fails
the second blast test.

### R20. F1 — `tools/compile-snapshot.mjs` was clean only with `noImplicitAny` relaxed — FIXED
Found by the acceptance grading (F1): `npx tsc -p tsconfig.scripts.json --noEmit --noImplicitAny`
reported 18 errors (12 TS7006, 6 TS7053), all in the compiler, hidden by `"noImplicitAny": false`;
`scripts-typecheck.test.ts` pinned the residual rather than removing it.

**Fix.** JSDoc types only in `tools/compile-snapshot.mjs`; `tsconfig.scripts.json:36` now
`"noImplicitAny": true`. **Pinned by** `src/core/scripts-typecheck.test.ts`, rewritten to require the
config not to relax the flag and to build a program with it forced on that must report nothing.
Verified: the reconciler ran `npx tsc -p tsconfig.scripts.json --noEmit` (exit 0, flag now on) and
the test (green). The lane reports `fabric.json` byte-identical across this change (`fce33d24…0da8`
before and after); the later A1 change (O12) then moved it deliberately.

### R21. D1 — no keyboard orbit or pan on the fabric canvas — FIXED
Found by the acceptance refuter (D1, overturning a first-pass PASS): 25 keys on the focused canvas
gave `changed=false` while a 300 px drag rotated the view ~90°.

**Fix.** Shift+arrows orbit (one press = a drag of 1/18 canvas height, 15°), Alt/Option+arrows pan
(1/16); plain arrows still move the selection. `camera.ts` `orbitBy`/`panBy` (declared `:383–385`)
drive the same three.js OrbitControls handlers a pointer drag does, so there is no second camera
model; one key table `src/fabric3d/canvasKeys.ts` feeds the handler, the canvas's `aria-keyshortcuts`
and a new "3-D fabric canvas" section on the `?` sheet. Post-drag drift is now off under reduced
motion for mouse and keyboard alike. **Pinned by** `src/fabric3d/camera.keyboard.test.ts` (key move vs
a simulated real drag, full and reduced motion), new cases in `Fabric3D.test.tsx`, and
`src/fabric3d/canvasKeys.help.test.tsx` — all re-run green by the reconciler; reported red before
(`rig.orbitBy is not a function`, `no canvas-keys section on the sheet`). Reported mutation: no-op rig
verbs turn 5 of 6 camera tests red (the sixth, "reduced motion leaves no drift", is also satisfied by
a camera that never moves — a known weak test). **Maintenance risk:** the handlers are
underscore-named in three 0.186; re-check on any three upgrade. The C5 motion run (O16) used this path
live: worst frame gap 200 ms during Shift+Arrow orbit.

### R22. D6 — links L34 and L35 were drawn "state not observed" but listed as "centrality not computed" — FIXED
Found by the acceptance refuter (D6 note). Both statements were true (no observed state, so not in the
connectivity graph, so null centrality) but the row carried only the consequence.

**Fix.** `geometry/cables.ts` `classifyLink` records what each drawn pattern claims in the branch that
picks it; `FabricA11yTree.tsx` `linkCutMeta` adds any drawn claim the row text lacks. L34/L35 now read
"state not observed · centrality not computed"; no other link's row changed. **Pinned by**
`src/fabric3d/link-encoding.parity.test.tsx` (all 44 links: every claim the drawn pattern makes must
appear in the list row) — reported red before (`expected 'centrality not computed' to contain 'state
not observed'`), re-run green by the reconciler.

### R23. D7 — the reduced-motion gate crashed before reaching a verdict — FIXED (no lane claimed it)
Found by the acceptance grading (D7): `TypeError: o.settleProblems is not iterable at captureReduced
(capture.mjs:725)` → EXIT=1; the call site passed no `t0` and took `{settle, problems}` as the array.

None of the four wave-1 lanes reported this fix, but the code has it: `review/capture.mjs:1159–1160`
now sets `t0` and destructures `{ problems: settleProblems }`, with a comment naming both halves of
the old defect. **Verified by running the gate** (reconciler, 2026-09-22, against the :4181 build):
`node review/capture.mjs reduced` → `PASS  D7: camera lands in one frame under reduce, 24 poses
without it.` exit 0 (reduce: `--dur-camera=1ms cameraPoses=1`; control: `.62s`, 24 poses). The gate is
its own evidence; there is no unit test pinning the call-site contract.

### R24. C6 — the §4.8 motion inventory omitted the spinner and the tier cross-fade — FIXED for those two rows (the dead CSS it found was deleted in wave 2c; O18 closed); the inventory as a whole was found false at the re-grade and rebuilt in wave 3 (R49)
Found by the acceptance grading (C6): a 900 ms infinite spinner (`App.css:349`) and the 300 ms tier
fade (`TIER_FADE_MS`) were missing from §4.8, and `App.css` and `flow.ts` each called their own
animation "the only looping animation". The lane also found that no component renders
`.stage-pending__spinner`, so the spinner never runs.

**Fix.** `docs/design-brief.md` §4.8 gained rows for both (verified at `:813–814`, each with duration
and reduced-motion behaviour); the `App.css` and `flow.ts` comments were corrected. **Pinned by**
`src/core/motion-inventory.test.ts` (new) — it derives animations from the code (every `@keyframes`,
every `*_MS` constant put into an inline `transition`), requires §4.8 to name each, and requires the
spinner to remain unrendered. Reported red before (4 failed, e.g. `@keyframes stage-pending-spin is
not in §4.8`); re-run green by the reconciler.

**Contradicted by the re-grade of `1d19e22`.** The test derived keyframes and inline `*_MS`
transitions only, never CSS `transition:` declarations, so §4.8 still claimed an 18 ms per-hop stagger
and a 140 ms palette animation that do not exist and omitted about eight running transitions. Fixed in
wave 3 (R49).

### R25. B1 (six surfaces), B7, C2, C3, D4 — health-band qualification and layout-fidelity defects — FIXED on the surfaces named; the B1 residual fixed in R27, layout residuals in O17; the 72-of-72 text PASS superseded (R28)
**B1** (acceptance grading): a favourable band on a host with unassessed scoring domains was qualified
only in the Device pane. The fabric-surfaces lane reproduced it on five hosts (podacc1, podacc2
Excellent; core2, dist1, dist2 Good) and moved the rule to one owner, `src/core/band-qualification.ts`
(`presentBand()`), now called by the Device pane, the canvas announcement, the Fabric list row, the
label chip ("E*"/"G*", grey, dashed), the legend (new "partial" rows) and the chassis/LED tint
(`scene.ts`) — verified by grep: exactly those six non-test modules import it. **Pinned by**
`src/fabric3d/band-qualification.surfaces.test.tsx` (states the rule independently and checks all six
surfaces against the hosts it covers) — reported `5 failed | 2 passed` before, re-run green. This file
briefly failed `source-hygiene.test.ts` (a test body with no direct `expect`); it now carries one and
the reconciler's run of `source-hygiene.test.ts` is green.

**B7, C2, C3, D4** (layout lane). The detector came first in name only: for B7 and C2 the fix was
written before the detector could see the defect, so their "before" evidence is mutation runs on
reverted CSS, not a test-first run. New `node review/capture.mjs text` mode (72 states: 8 capture
states + palette open, 390/768/1440/1920, both themes) with `readTextFidelity` (clipped / escaped /
column / mid-word), `readCoverageVisibility` (B7) and `readContrast` (D4); `captureApp` runs the text
and coverage checks on every frame. Fixes: B7 — the coverage group wraps and only `.sb__rest` scrolls,
the bar sits above panels (`StatusBar.tsx`, `chrome.css`, `shell.css`); C2 — citation/"not observed"/
select/chip rules given one owner in `src/ui/primitives.css`, the duplicate `.pathtrace` rule removed;
C3 — comfortable-density titles wrap and clamp at 3 lines, category wraps (`PriorityQueue.css`); D4 —
the palette scope line shrinks and the footer wraps (`CommandPalette.css`), measured after at
5.05–6.75:1. Reported: `PASS text 72 of 72 states` after, exit 3 before; per-defect mutation runs
`FAIL 10 of 36` (B7), `2 of 54` (C2), `FAIL 0 of 36` (C3 — quoted as reported; the report does not say which count that is), `32 of 36`
(D4). Limits the lane stated: all measured on the :4180 dev server; the checker judges a line
visible by its vertical midpoint, so descender clipping is not detected (the clamp cutting descenders
was found and fixed by eye); citations now wrap everywhere, so rows holding one may be taller.
**Re-run by the reconciler, 2026-09-22, against the :4181 release build** (the lane had measured only
the :4180 dev server): `node review/capture.mjs text` → `PASS  text  72 of 72 states free of
clipped/broken text and with coverage wholly visible`, exit 0; palette-footer contrast min 5.05:1
(dark) and 5.7:1 (light) at every width.

**Superseded in part (2026-09-23).** The `PASS text 72 of 72` above was measured with a detector that
exempted identifiers, so it could not see the `num_power_supplies` split the acceptance grading then
found (C2); with identifiers, node-boundary splits and overruns detected, the tree first measured 68
of 72, and 72 of 72 only after wave 2c's fixes (R28, re-run by the reconciler on `1d19e22`). The B1
residual this entry left in O12 is fixed (R27).

### L1. The critique loop declared convergence on zero evidence — FIXED (review apparatus, not product)
The loop that drives the blind panel and the six specialist audits (it lives in the orchestrating
session's scratchpad, not in this repository) returned `{"rounds": 6, "converged": true}` on
2026-09-21. It had not converged. Every round-6 audit — a11y, perf, honesty, capability, integrity,
render — and the blind decode had failed with `API Error: Can't reach the API server (ENOTFOUND)`.
The journal records it: round 6 had 9 agents, 2 results and 7 failures.

The mechanism is this project's own defect class, inside the apparatus meant to catch it. A failed
agent resolves to `null`; the audits were collected with `(await parallel(…)).filter(Boolean)`, so
the six nulls vanished and `blockerFindings` became `[]` — "no audit ran" read as "no audit found
anything", and the gate `blockerFindings.length === 0` passed. Absence rendered as health. Round 5,
the last round that actually measured, had **5 blockers and 11 majors** open.

Fixed in the loop, not papered over: missing audits and a missing decode are retried under fresh
labels, then COUNTED against what was expected (`AUDITS.length`, `sheets × lenses`); any gap blocks
convergence and is logged as an evidence gap; a round where no audit returns at all aborts with that
reason rather than spending rounds "repairing" against nothing. The staged acceptance sweep had the
same `.filter(Boolean)` shape on its graders and refuters and was fixed the same way — an ungraded
group is carried into the report as UNPROVEN, and a PASS whose refuter never returned is reported as
unrefuted, never as "survived an attack". The invalid "converged" was never reported as a result.

Found at the same time: a round-5 parallel repair wave left `tsc -p tsconfig.json` failing
(`src/core/sticky-layer.test.ts`, three `noUncheckedIndexedAccess` errors) while each agent had
reported its own slice green. Fixed, and the loop now runs one post-wave integrity gate over the
merged tree (both `tsc` configs, `vitest`, `npm run build`, a clean console) from round 6 on.

### R14. A standing draw-call breach, invisible in production — FIXED
Measured 2026-09-21 in a real browser (ANGLE → Intel D3D11, 1920×1080, `high`, 40 consecutive rAF
samples per state): every path-trace state rendered a **steady** 141-draw-call frame against a flat
declared ceiling of 120. `min === max === 141` at `converged: true`, with 75 consecutive breaching
frames against an `OVER_BUDGET_FRAMES` threshold of 2 — a standing breach by the code's own
definition, not a rebuild transient. It was reproduced independently by the capture harness, which
recorded `drawCalls: 141` for `06-path-blocked` and `08-path-indeterminate` in
`review/shots/app/index.json`.

**It was unreachable.** `overBudget` was set on an internal flag, was not on the `SceneStats` the
frozen `contract.ts` declares (8 fields declared, 15 returned at runtime), had zero consumers
outside `scene.ts`, and its only report was a `console.error` behind `import.meta.env.DEV` —
`grep "exceeds the budget of" dist/assets/*.js` matched nothing in any shipped chunk. The product
breached its own published budget continuously, in front of the user, and said nothing.

Two in-code claims were false and are corrected: `scene.ts` said the ~124-call rebuild frame "is
the only frame that approaches 120", and `layers.test.ts` said "whether a real frame stays under it
is measured in the browser (74 calls at `high`)". The 74 was measured with nothing selected and
generalised to "a real frame".

**The cost was mis-modelled, not mis-measured.** A composed frame is a base plus a surcharge per
`OutlineEffect` that currently has a non-empty selection — postprocessing's `OutlineEffect.update()`
re-renders the whole scene into a depth buffer and the selection into a mask, guarded only by
`selection.size > 0`. The full sweep:

| State | Active outline effects | Draw calls |
|---|---|---|
| nothing selected, no trace | 0 | 74 |
| device selected | 1 | 103 |
| trace DELIVERED | 1 | 103 |
| trace DENIED / INDETERMINATE | 2 | 141 |
| denied trace **and** a device selected | 2 | 141 |

The delivered-trace row is identical to the plain-selection row, so the trace geometry costs **zero**
extra draw calls; the whole +67 was the second outline effect. One flat number can only ever be
right for one of those frames, and 120 was set on the idle one.

Fixed by replacing the flat ceiling with the model: `DRAW_CALL_BUDGET_BASE` (88) +
`OUTLINE_EFFECT_COUNT` × `DRAW_CALL_BUDGET_PER_OUTLINE` (44) = **176** published in
design-brief.md §4.4, with the render loop judging each frame against
`drawCallBudgetFor(activeOutlines)`. This TIGHTENS the common case — the idle frame is now held to
88 where it used to be waved through at 120 — while it stops lying about the rare one.
`layers.test.ts` asserts all three numbers against the brief, asserts the render loop reads the
per-frame ceiling rather than the total, counts the `new OutlineEffect(` sites so a third one cannot
be added for free, and pins every measured row with a ≤ 40% headroom bound so the budget cannot
drift back into being untrippable.

And it is no longer silent. `scene.ts` now returns `FabricSceneEx` — a SUBTYPE of the frozen
contract's `FabricScene`, proven conformant with `satisfies CreateScene` — so `overBudget`,
`drawCallBudget` and `activeOutlines` are named and type-checked rather than reachable only by cast.
`Fabric3D.tsx` shows a standing breach on the quality chip in **every** build: amber, reading
`141/120 draw calls`, with a tooltip naming the cost, the ceiling, how many outline effects were
active and that it is standing rather than a rebuild transient. Four tests in `Fabric3D.test.tsx`
drive both paths — clean frame unmarked, breaching frame marked, the mark clearing when the breach
stops, and a reduced tier reported as a different thing from a breach. Verified in the running
product by temporarily lowering the budget: the chip rendered `141/60 draw calls` in amber, then
returned to plain `Quality high` when the real numbers were restored.

Re-measured after the fix, all states: `overBudget: false`, 0 console errors.

### R13. The capture harness was red on every frame, and nothing ran it — FIXED
`node review/capture.mjs app` exited **3 on 32 of 32 frames**, in every run, because the draw-call
breach above flooded `console.error` and the harness counts a console error as a frame that did not
render. That harness is the designated verifier for everything `scene.test.ts` explicitly disclaims
— post-processing pass order, colour management, SSAO, bloom thresholding, shadow-map fitting,
measured frame rate — and `npm test`, `npm run build` and `tsc` all pass without touching it. The
entire visual-evidence corpus was failing and no gate a developer actually runs could see it.

Fixing R14 cleared it: re-run after the fix, **0 of 32 frames** carry a budget error and `grep -c
"exceeds the budget" ` over the harness log returns 0. (One frame was red in a re-run for an
unrelated reason: a concurrent editing lane had `FabricLabels.tsx` in a half-saved state, which is
what a live HMR capture looks like, not a defect in the harness.)

It is now reachable by name: `npm run capture` and `npm run capture:refs`. `docs/acceptance.md` F2
states the delegation explicitly — the harness's own exit code is part of F2's evidence, not an
optional extra. It is deliberately NOT chained into `npm test`: it needs a live server and a real
GPU, and making the unit gate depend on those is the flakiness `vitest.config.ts` was written to
remove.

### R12. `npm run e2e` was a declared gate that could never run — REMOVED
`"e2e": "playwright test"` with no `playwright.config.*` and no `e2e/` directory. With no config
Playwright globs the repository, tries to load every `src` unit test as a spec, throws
`Module "…/src/data/fabric.json" needs an import attribute of "type: json"` on each, and exits 1
with `No tests found`. `tsconfig.json` listed `"e2e"` in `include` for the same non-existent
directory; `--listFiles` returned 90 entries, every one under `src/`, not one under `e2e/`.

`@playwright/test` is genuinely installed and genuinely used — `review/capture.mjs` drives it
successfully. Only the gate was fiction. A script in `package.json` reads as a gate, and one that
has never exited 0 is worse than its absence because it makes the gate list look longer than it is.

Both removed: the `e2e` script, and `"e2e"` from `tsconfig.json`'s `include` (with a comment saying
why it is not coming back). The honest precedent was already in the tree — `tsconfig.scripts.json`
exists precisely because `"tools"` in an include list "READS as coverage and is not" — and the same
reasoning simply had not been carried through.

### R11. Two keyboard-help overlays, and a focus-return regression underneath — FIXED
The integration agent reported an overlap rather than silently resolving it, which was the right
call. `ShortcutHelp` was mounted twice: once by `App.tsx` (registry-driven, generated from live
bindings) and once privately inside `Header.tsx` with its own `?` handler and a hand-written
`OWN_SHORTCUTS` array — the thing design-brief §7.1 forbids.

**Both agents were reasoning correctly.** The Header one carried this justification:

> "A keyboard reference that lists a shortcut nobody wired is a false claim about the product, made
> in the one place a user goes when they are already stuck."

That is exactly right. It was written because Header installed `/` with a raw
`window.addEventListener`, so the binding never reached the registry and the generated sheet could
not see it. Each was a good local answer; together they were a defect.

**The real cause was narrower than it looked.** `commands.ts:533` already declares `query.focus` as
a capability bound to `/`, and `App.tsx:332` already registers the query input as its target.
Header's raw listener was a DUPLICATE of an existing capability, not compensation for a missing
one. My first fix added a registration in Header — which recreated the duplicate under a new name
and showed up on the sheet as "Focus the query bar: //" with two key chips. Removing the raw
listener was the entire fix; a surface that needs a key asks for the capability, it does not bind
the key itself.

**The regression this exposed, which matters more than the overlap.** `focusReturn.current` was set
inside Header's own `/` handler. With that handler gone, App's capability target focuses the input
directly — and **Escape stopped returning focus to where the reader came from**. Nothing caught it
but a test whose premise I had to unpick. Fixed by recording the return target on the input's
`focus` event instead, which is strictly better than the original: it covers every entry path —
the key, the command palette, a click, a screen reader — rather than only the one key that used to
set it.

Verified in the running application, not inferred:
```
help: {"sheets":1,"around":"Focus the query bar: /…"}
after '/': hdr-query__input | after Escape: probe-origin | returned: true
pageerrors: 0
```
Suite: 637 passing, 23 files, 0 typecheck errors. Pinned by `src/app/help-single-source.test.tsx`
(8 tests), including two that read `Header.tsx` and fail if either the private overlay or a
hand-written key list returns.

**A harness bug worth recording**, because it wasted an hour and will recur: `keyboard.ts` installs
its listener on `document`, and a test that dispatches `keydown` on `window` exercises NOTHING —
events dispatched on window do not travel down to document. Every key assertion fails for a reason
unrelated to the product. It is also why Header's old raw `window` listener appeared to work in its
own test while a correctly registered binding did not.

### R8. The INP harness reported PASS for a journey that did nothing — FIXED
`review/measure-inp.mjs` had never been run, so its own behaviour was unverified. Run against the
scaffold, four journeys correctly reported NOT MEASURED — but **J5 (open the command palette)
reported PASS at 16 ms with one sample, against an application that has no command palette.**

Its readiness selector was `body`, which is always satisfiable. The harness pressed Ctrl+K, the
browser dispatched a keydown that nothing handled, the Event Timing API duly recorded a 16 ms
interaction, and the journey passed. A latency figure for a no-op is not a fast interaction — it is
a missing one, reported as success. The same defect shape this whole application exists to prevent,
sitting in the instrument built to measure it.

Fixed with a per-journey `verify` hook that must prove the interaction has its intended EFFECT
before any timing is recorded. J5 now asserts a dialog or expanded combobox actually appears.
Re-run against the same scaffold:
```
NOT MEASURED J5-open-palette  [Cmd/Ctrl+K opened no dialog or combobox — the palette is absent or not wired]
0 pass, 0 fail, 5 NOT MEASURED
EXIT=1
```
The general lesson, and it applies to the other four journeys once the UI exists: a readiness
selector proves an element is PRESENT, not that the interaction WORKS. Only an effect check
distinguishes "fast" from "absent".

### R7. `npm run build` failed outright — FIXED
`vite.config.ts` declared `build.rollupOptions.output.manualChunks` as an OBJECT. Vite 8 bundles
with Rolldown, which accepts that option only as a FUNCTION, and fails with
`TypeError: manualChunks is not a function`. The object form is a Rollup-ism carried over out of
habit.

Nothing caught it because nothing had run the production build — `tsc` and `vitest` both pass on a
config that cannot bundle. Acceptance F4 (three.js code-split out of the entry chunk) was therefore
UNPROVEN rather than passing, which is the distinction `docs/acceptance.md` exists to keep.

Fixed with the function form, which also splits React out. Verified:
```
dist/assets/index-*.js   188.63 kB │ gzip: 17.60 kB
dist/assets/react-*.js   189.60 kB │ gzip: 59.61 kB
✓ built in 414ms
```
There is no `three` chunk yet only because the scaffold `App.tsx` does not import the 3-D subsystem;
it will appear once integration wires the fabric in, and F4 should be re-checked then rather than
assumed from this run.

### R5. The entire 3-D fabric rendered as a black screen — FIXED
`materials.ts :: withEmphasis` injected `totalEmissiveRadiance *= vColor.rgb;` into the fragment
shader whenever a material routed per-instance colour into emission. `vColor` is declared by
three.js's `color_pars_fragment` only under
`USE_COLOR || USE_COLOR_ALPHA || USE_INSTANCING_COLOR || USE_BATCHING_COLOR`, and
`USE_INSTANCING_COLOR` is set only when an `InstancedMesh` actually carries an `instanceColor` at
compile time. When it did not, the fragment shader failed with
`'vColor' : undeclared identifier` and **every mesh using that material drew nothing.**

The author's reasoning about *not* setting `vertexColors: true` was correct and is documented in
the file. The gap was narrower: the injection was unconditional while the varying it referenced was
conditional. Fixed by guarding the injected line with three's own declaration condition, so the two
cannot disagree however the mesh is built.

**Why nothing caught it, and this is the part worth remembering:**
- **The scene's own stats reported health.** `renderer.info` gave 28 draw calls, 55,935 triangles
  and 55.6 fps against a completely blank canvas, and `converged` went true. Absence rendered as
  health, inside our own instrumentation.
- **`scene.test.ts` cannot see it, by construction.** jsdom has no GL context, so no shader is ever
  compiled there. The suite was green the entire time — and the test file says so honestly in its
  header, which is exactly why that honesty matters: it told us where not to trust it.
- GL reports a shader failure to the console and then carries on rendering nothing.

The only thing that could find this was putting the renderer in a real browser and looking at the
pixels. `review/probe-fabric.mjs` now does that on demand.

### R6. The blank-frame detector cried blank on a working render — FIXED
`probe-fabric.mjs` first measured "did it draw" with `drawImage(canvas, …)` + `getImageData`. A
WebGL context created with the default `preserveDrawingBuffer: false` discards its drawing buffer
after compositing, so that read is always empty. The probe reported **"the canvas is NOT drawing a
scene"** about a fabric that was rendering correctly — which would have sent the critique loop
hunting a renderer bug that did not exist, and taught everyone to distrust the detector.

Fixed by measuring a real screenshot (composited as a user sees it) and decoding the PNG back
inside the browser. It now reports 840 distinct colours and 87.6 % non-black on the live fabric.

### R4. The data compiler silently discarded the producer's own verdicts — FIXED
Found by the adversarial refuter that ran against `cisco_toolkit.parse._acl_rule`, the real parser
this model compiles. `tools/compile-snapshot.mjs` emitted only
`action, raw, proto, src, dst, sport, dport` and **dropped five fields the snapshot carries**:
`unevaluable`, `unmodeled_qualifiers`, `established`, `icmp_type`, `time_range` — plus the entire
`object_groups` table and the `group` key on a match field.

Two distinct harms, and the second is the worse one:

1. **Parser-versus-detector drift.** With the producer's verdict discarded, the engine had to
   re-derive evaluability from the raw configuration text. Two derivations of the same fact can
   disagree, and when the consumer's is the more optimistic one an *unknown* becomes a *confident
   wrong answer*. The refuter demonstrated the concrete case: the producer emits
   `{"op":"eq","val":null}` for a port name it cannot resolve (`eq citrix`); compared numerically
   that is a definite non-match, so a permit line stops firing, the flow falls through to
   `deny ip any any`, and the engine reports a definite **denied — with zero indeterminacy
   caveats — for traffic the configuration explicitly permits.**

2. **A model gap reported as a collection gap.** `MGMT_IN` references object-group `MGMT_HOSTS`.
   The snapshot carries that group with both members, one of which (`10.0.40.0/24`) is a real VLAN
   in this very fabric. Because the compiler dropped the table, the application told users the
   members "were not collected" — a false statement about our own evidence, and the damaging
   direction of error: it sends someone to collect data they already have.

**Why the repair agents could not fix it:** `tools/compile-snapshot.mjs` was on the frozen-file
list, so they could only work around it inside the engine. That is a real lesson about file
ownership — freezing a file protects it from collision and simultaneously protects its bugs.

**Fixed by:** carrying all five fields plus `objectGroups` and `AclMatchField.group`; extending
`types.ts`; teaching `addrTri`/`consumeAddress`/`fieldAgrees` to resolve a carried group; and
deriving the host from each line's own `cite` rather than rethreading ~20 call sites.

**Result:** `core1.MGMT_IN[0]` went from permanently unevaluable to **evaluable** — `10.0.40.7`
(inside the group) matches, `10.0.10.50` does not. The model became strictly more capable *and*
stopped making a false statement. Covered by `src/core/compiler-fidelity.test.ts` (9 tests) and
`src/forwarding/producer-trust.test.ts` (8 tests), including one pinning the `cite` format that
host-derivation depends on.

**Two bugs I introduced while fixing it**, both caught by existing tests rather than by me:
  - `field.group !== null` misfired on `undefined`, because the real producer omits the key
    entirely when there is no group. That classified every ordinary address as "a group field" and
    broke the drift guard on the exact lines it should pass. Fixed with an explicit
    `fieldGroup()` helper that treats `undefined` and `null` alike.
  - The engine's own message went stale in the other direction: it still said the model "does not
    carry" members that it now carries.

### R1. Literal NUL bytes in `src/analysis/blast.ts` — FIXED
Two `\u0000` characters were written as literal NUL bytes inside a string literal used as an array
join separator. Valid JavaScript, compiled fine, 35 tests passed — but `file(1)` reported the module
as `data` and `grep` refused to search it, silently disabling review tooling on a 1686-line file.
Replaced with the escape sequence; byte-identical at runtime. Verified: `file` now reports
`JavaScript source, Unicode text, UTF-8 text`, and the 35 blast tests still pass.

### R2. Fabricated worked example in `docs/design-brief.md` §6.3 — FIXED
The brief's "worked example against the real data" used `10.20.10.5 -> 10.30.40.9`. Neither address
exists in `fabric.json`; the only observed subnets are `10.0.10.0/24`, `10.0.20.0/24`,
`10.0.30.0/24`. A build agent copying it would have shipped a demo flow returning `out-of-scope`.
Replaced with a flow verified by running `traceFlow`, and a correction note added in place.

### R3. The claim gate produced false positives on honest text — FIXED
`forbiddenWordsIn` initially used substring matching with no negation awareness. It flagged three
sentences the product *should* say:
  - `"nothing can be proven about forwarding on them"` (engine caveat — negated)
  - `"It does not show that ALL traffic does"` (sample-path disclaimer — negated)
  - `"every statement ... is unproven"` (engine caveat — "unproven" contains "proven")
This is worse than no gate: it would have pressured an author to delete honest sentences to go
green. Fixed with word-boundary matching plus clause-scoped negation detection, and the three real
sentences are now regression tests. The limit is documented in the code: the check is lexical, not
semantic, and is a backstop rather than a proof.

> **Moved from Open (2026-09-23).** R15, R9, R10, O2 and O3 were resolved before wave 2c but were
> filed under Open; they are moved here unchanged.

### R15. F6 failed — the status bar painted the live frame rate into every captured frame — fps cause FIXED; the 1-LSB scrim residual FIXED at the capture layer; F6 PASSES on `twice 5` against the preview, dev server (:4180) not measured (heading corrected 2026-09-22)

*Heading correction, 2026-09-22.* The previous heading read "F6 still FAILS on a 1-LSB scrim
residual". That was true of the body's middle paragraph and false of its end: the same entry goes on
to remove the residual (CPU tile raster in `review/capture.mjs`) and to cite F6 as PASS on
`node review/capture.mjs twice 5`. The acceptance grading (`docs/acceptance-report.md`, F6) upheld
that PASS independently: 32 of 32 frames byte-identical across 9 captures, 2 of them under ~80 % CPU
load, measured on the :4181 preview only. A heading that contradicts its own body is the stale-pointer
defect this entry was written about, so the heading now says what the body concludes. Unchanged: the
dev server has still not been measured for F6.

**This entry replaces the previous O4**, which said F6 was unproven because
`window.__atlasScene` was never set and the harness fell back to a bounded wait. That half is
resolved and has been for some time: all 32 entries in `review/shots/app/index.json` carry
`"converged": true`, and that field is only ever populated through
`page.waitForFunction(() => window.__atlasScene?.stats?.().converged === true)` — the
`waitForTimeout(2200)` fallback leaves it unread. The hook is live. F6 was failing anyway, for a
different reason, and the only document that could have warned a reviewer was pointing at a
problem that was already fixed. That is worse than saying nothing: it converts an open criterion
into a solved-looking one.

**The measured cause.** Two consecutive `node review/capture.mjs app` runs (both exit 0, 32 frames
each, renderer `ANGLE (Intel … Direct3D11)`, all 32 `converged: true`, `quality: "high"`) produced
**23 differing PNGs out of 32**. Example — `dark/1920/02-device-selected.png`:

```
run1 3f095ee82d573f61ffaf3c004b583347ca2d0502c056c3ebd21808c9ed4e42d9
run2 97cbf51c5e843b0ece15c195b1f325985819142da1813123fec5b2b64820af05
```

Pixel-diffing every pair put **every** differing pixel inside one 24x16 device-pixel box at the
bottom right — `dark/1920` bounding box `[3546,2126,3569,2141]`, 278 differing pixels, 0.0034% of
the frame; `dark/1440` `[2586,1766,2609,1781]`. Cropped and read at 6x, that box said
**"fabric 43 fps"** in run 1 and **"fabric 56 fps"** in run 2. The 3-D canvas — the part everyone
assumed was the risk — was byte-identical. The failure was a text node in the chrome.

Value origin: `src/fabric3d/scene.ts` `function frame(now: number)` → `fpsEma` → `SceneStats.fps`
→ `publishSceneStats` → `StatusBar`'s `.sb__fps`, drawn in the permanent status line of every
screen.

**Why nothing caught it.** `src/core/determinism.test.ts` owned F6's source half and detected only
clock **call expressions**. The rAF timestamp arrives as a function **parameter**, so the entire
fps path was outside its denominator — `grep -rn "Date.now(\|Math.random(" src/` returned zero
live call sites while the captures were nondeterministic. Its one value-flow rule was hard-coded
to the single field name `elapsedMs`, with no equivalent for `fps`. Meanwhile
`src/app/status-telemetry.test.tsx` **required** the defect
(`expect(container.querySelector(".sb__fps")?.textContent).toContain("52")`). And nothing in the
repository ever captured twice and compared: `grep -rn "F6" review/*.mjs` returned nothing. F6's
stated evidence is "capture twice, compare hashes", and that measurement had never been performed.

**What was changed (all four, because three of them are the reason the fourth was invisible):**

1. **The product.** `src/app/StatusBar.tsx` no longer draws any frame-timing digit in the
   permanent line. It carries the tier word, `reduced`, and `settled`/`refining` — all functions of
   the data. The measurements moved one click away into the coverage disclosure, which the scene
   readout now opens as a control (`Renderer`: frame rate, last frame, draw calls, triangles, tier,
   refinement). This follows the design brief rather than deviating from it: §8 asks for the active
   tier to be named at all times, and T8's permanent line is coverage + snapshot — it never carried
   a frame rate. Deliberately **not** a `?capture=1` mode: a capture that photographs a state the
   product does not otherwise show proves a property the product does not have.
2. **The gate that owns F6's evidence.** `node review/capture.mjs twice` captures, re-captures into
   a second tree, hashes every PNG and exits non-zero on any difference, naming the files. It
   refuses to report a verdict when either run had a render failure or when zero frames were
   captured — two blank runs hash identically, and calling that F6 satisfied is the same
   absence-as-health failure this product exists to detect.
3. **The detector.** `determinism.test.ts` now covers clock-valued **bindings** as well as calls —
   the rAF callback's first parameter and a DOM event's `timeStamp`, resolved through a named
   callback scheduled by identifier, which is the shape `scene.ts` actually has. It found three
   true positives that had been invisible; each now carries a written `determinism:` justification.
   The `elapsedMs` allow-list became the frame-timing field class (`elapsedMs`, `fps`, `frameMs`,
   `worstFrameMs`) with a declared owner per field, so the next one cannot reach a renderer
   unannounced. Both detectors are proven live by running them over planted source.
4. **The test that required the defect.** `status-telemetry.test.tsx` now asserts the property
   rather than the pixel: the scene readout carries no digit at any published frame rate, two
   readings differing only in frame timing leave its markup identical, and the measurements are
   still reachable behind the disclosure.

**Measured after the fix (2026-09-21, 11:4x) — F6 is still RED, on a different and much smaller
cause.** Two `twice` runs against the live dev server were contaminated — other agents edited
`src/fabric3d/scene.ts` and `src/app/surfaces.tsx` mid-run (source-tree hash differed before/after;
one run recorded "the page reloaded under the harness") — and are not evidence either way. The
authoritative run froze one `vite build` into a scratch directory, served it with `vite preview` on
its own port, and pointed the harness at it (`ATLAS_URL=http://localhost:4189 node
review/capture.mjs twice`; bundle hash identical before and after). Result: **exit 3, 30 of 32
frames byte-identical** (was 9 of 32); differing: `dark/1920/05-path-trace.png`,
`light/1440/06-path-blocked.png`. No fps glyph anywhere. Every differing pixel has **max channel
delta 1**, in full-width horizontal bands ~45 device px tall at the bottom edge of the side panes
(dark/1920 rows 2040–2085, x 3002–3839; light/1440 rows 660–661 x 0–597 and 1724–1725
x 2124–2879) — the geometry of the two stacked `linear-gradient` scroll scrims (`src/app/shell.css`
`.scroll-y, .scroll-scrim`; `src/panels/Inspector.css`). That is gradient raster/dither noise in the
compositor, not a value the product computes, but F6 asks for byte identity and this is not it.
**Open, owner: the shell/panel styling.** Candidate remedies, not yet tried: replace the
translucent gradient pair with a solid-stop or `mask-image` scrim and re-measure; or confirm it is
Skia gradient dithering and decide explicitly whether F6 is graded on bytes or on a stated ±1 LSB
tolerance — that is a change to the criterion, and must be made in `acceptance.md`, not in the
harness. Until one of those lands, grade F6 **FAIL**. **Located and removed at the capture layer (2026-09-21, later).** The alternate is page-wide, not one box: in the reproduced case (dark/1920/06-path-blocked, frozen `vite build` on its own port, nobody writing to it) BOTH rails' scrim bands and several SVG header/badge icon edges flipped together, maxd 1, never a glyph, never the canvas — so it is the capture browser's GPU tile-raster state choosing between two correct rasterizations, which is why pinning the scrollers (a product paint change) could not fix it. Measured: GPU tile raster (`--enable-gpu-rasterization`), 3 `twice` runs = 6 captures per frame, 1 of 32 frames varied; CPU tile raster (`--disable-gpu-rasterization`, WebGL still on the GPU via ANGLE, tier `high` and `converged` on every frame), 10 `twice` runs = 20 captures per frame, **0 of 32 frames varied across all 20**. `review/capture.mjs` now launches with CPU tile raster, and `twice N` compares every frame across all N captures in one command. This is a change to how the photograph is taken, not a tolerance: F6 is still graded on byte identity. Statistical honesty: at the GPU-raster rate seen here (1 in 192 captures), 0 in 640 would occur by luck about 4% of the time. **Not yet re-measured:** the dev server (:4180) — it was being edited by other agents throughout (two layout changes landed mid-probe), so any :4180 result today is not authoritative. Cite F6 as PASS only on `node review/capture.mjs twice 5` (exit 0) against a server nobody is writing to.

**Residual, stated rather than implied.** The quality tier IS derived from frame timing (median of
the first 60 settled frames) and IS drawn as a word. On a machine under enough load to step the
renderer down mid-capture, two runs would legitimately differ. That is not silent: `capture.mjs`
already records the tier per frame and reports any non-`high` frame as a problem, and `twice`
refuses to compare when a run had problems. A tier step-down therefore surfaces as a red capture,
never as a mystery diff.

### R9. Literal NUL bytes recurred in three modules, and scratch files leaked — BOTH now GATED (the scratch half corrected 2026-09-21)
`grep` reported `src/panels/PriorityQueue.tsx` as a **binary file**. It held 6 literal NUL bytes;
`src/panels/JsonView.tsx` held 1; `src/analysis/blast.ts` had held 2 earlier. Three independently
written modules, same cause: a NUL used as a composite-key separator in a template string, typed
directly into the source instead of written as an escape.

It compiles, it runs, every test passes — and `git diff`, `grep`, `file(1)` and most editors then
classify the file as BINARY. `grep -rn "thing" src/` silently skips it. A 1,000-line module drops
out of every code search in the project with no error message, invisible precisely to whoever is
looking for it.

Three occurrences is a pattern, so it gets a gate rather than a third repair:
`src/core/source-hygiene.test.ts` now asserts, across every `.ts/.tsx/.css/.json` file, that there
are no NUL bytes, no other C0 control characters beyond tab/LF/CR, and valid round-tripping UTF-8.

**Correction, 2026-09-21 — the scratch-file half of this entry was overstated and is now actually
closed.** This section claimed the gate asserts "no scratch, probe or dump files left in `src/`" and
that the class was shut. It was not. What shipped was a NAME regex,
`/(^|[\\/])(__|zz_|tmp_|scratch|probe|dump)/i`, scoped to the literal name of the one file it was
written after (`src/forwarding/zz_scratch.test.ts`, a refuter leftover that ran, passed and asserted
nothing). `zz_` requires the trailing underscore. Six files later written as `src/zzaudit*.test.ts`
matched none of those alternatives: every one was a bare `it()` with zero `expect(` calls, every one
was collected by vitest, and the reported pass count went 737 → 742 while the gate stayed green.
Five tests were added to the green count that proved nothing, and nothing objected.

That is the named-subset-instead-of-structural-class shape, and the gate's own comment had already
named the real property — "a bare `it(\"probe\")` with no assertion at all, inflating the pass count
while proving nothing" — one paragraph above a line admitting "WHAT THIS CANNOT DO: it matches
NAMES."

The gate now checks the property instead of the name. `source-hygiene.test.ts` parses every file the
vitest glob collects (and asserts that the globs it walks are the ones `vitest.config.ts` declares,
so the denominator cannot narrow silently), finds every `it`/`test` definition including the
`it.each(...)(...)` form, follows same-file helper functions to a fixpoint, and fails on any test
body with no assertion in it. It reads code, not prose: comments and string literals are stripped
first, so a commented-out `expect` does not satisfy it. Both halves of live are proven in the suite —
planted assertion-free tests in four shapes are detected, and asserting tests direct and
helper-mediated are not flagged. Verified end to end by planting `src/core/leftover.test.ts` (a name
no convention covers): it passed on its own and the gate named it.

The name regex is kept as a cheap second net and widened exactly where it missed (`zz_` → `zz`,
`tmp_` → `tmp`, no trailing underscore required). It is deliberately not widened to words a real
module could legitimately carry — a longer list of special names is the shape this defect IS — and
it is explicitly no longer the gate.

The six `zzaudit*.test.ts` files were written during an audit lane's own run, not left by the build,
and were already gone from `src/` by the time this repair landed. The hole they went through was
not.

The gate's first act was to fail on **its own file**. Writing `\u0000` in the doc comment that
explains the bug caused the editor to embed a real NUL, so the NUL detector shipped containing a
NUL; the same happened to `"\uFFFD"` in the check itself. Both are now constructed from their code
points rather than embedded. A detector that cannot contain what it detects is a constraint worth
knowing about, and the gate catching its own author inside a minute is the best argument for it.

### R10. Wall-clock assertions in the unit suite were a flaky gate — FIXED for the three tests named; the class is NOT closed (O26)
(Formerly O2. Retained below in full because the diagnosis is the useful part.)

*Heading corrected 2026-09-23 (wave 3).* It read "FIXED AS A CLASS". Under wave 3's multi-agent load
two wall-clock tripwires went red (O26): the median-of-7 counterexample tripwire this entry installed
(`engine.test.ts:955`, 54.66 ms against 50) and a **worst-of** bound in a fourth test this table never
listed (`CommandPalette.test.tsx:717–718`, "opens over an index that already exists", 620 ms against
400). The three rewrites below stand; the claim that the class was closed does not.

Fixed as one change across all three, rather than patching whichever one happened to be red:

| Test | Before | After |
|---|---|---|
| `forwarding/engine.test.ts` | single measurement < 5 ms | **median of 7** < 50 ms tripwire |
| `app/CommandPalette.test.tsx` | **worst** of 5 rounds < 50 ms | **median** of 45 samples < 200 ms tripwire |
| `fabric3d/layout.test.ts` | median of 7 < 50 ms | **unchanged** — already correct |

The layout test was deliberately left alone and the other two were rewritten to match it. It is the
only wall-clock assertion in the suite that has never flaked, and the technique is the reason:
a median absorbs a scheduler stall, and its bound sits an order of magnitude above the operation's
real cost. Changing a working test to match a template would have been cargo-culting; a comment now
records why it is sound so nobody "fixes" it later.

Both rewritten tests were also RENAMED, from "stays far under the 50 ms task ceiling" to "does not
blow up algorithmically". The old names claimed something a unit test cannot honestly assert — a
latency budget it does not control the machine for — and a test whose name overclaims is the same
defect as a UI that overclaims, just aimed at the next engineer instead of the user.

The real budget is owned by `review/measure-inp.mjs`, which measures the built application, labels
its numbers LABORATORY, and reports NOT MEASURED rather than guessing.

Verified: `134 passed` across the three files.

### O2 (diagnosis, retained). Wall-clock assertions in the unit suite are a flaky gate — a CLASS, not one test
Three tests assert elapsed milliseconds. On this host, which routinely runs 6–12 agents at once,
they fail spuriously — and a red from a timing assertion is **indistinguishable from a real
regression**, which is the worst property a gate can have.

| Test | Assertion | Statistic | Fragility |
|---|---|---|---|
| `fabric3d/layout.test.ts:909` | median < 50 ms | **median of 7 runs** | low — correct technique |
| `forwarding/engine.test.ts:509` | `t.elapsedMs` < 5 ms | single measurement | high |
| `app/CommandPalette.test.tsx:558` | worst < 50 ms | **worst of 5 rounds** | highest |

Observed: `engine.test.ts:509` failed once under load and passed on a quiet run;
`CommandPalette.test.tsx:558` is currently failing while six panel agents build. The layout test,
which takes a median, has never flaked — the technique is the difference.

**The principle:** a unit test can honestly assert an ALGORITHMIC property (this is not accidentally
quadratic) but cannot honestly assert a LATENCY BUDGET, because it does not control the machine.
The budget belongs in `review/measure-inp.mjs`, which measures the real application, labels itself
LABORATORY, and reports NOT MEASURED rather than guessing.

**Action:** keep a tripwire far above any plausible scheduling delay (≥10× the design budget) and
take a median rather than a worst case; let the INP harness own the real budget claim. To be applied
as one change across all three once the build agents release these files — fixing them one at a time
as they flake is how a gate gets loosened until it means nothing.

### O3. `tsconfig.json` restricted `types` to `vite/client` — RESOLVED
Any test importing `node:fs` failed typecheck with `Cannot find module 'node:fs'` even though
`@types/node` is installed. Resolved by adding `"node"` to `compilerOptions.types`, which the
claim-lint gate needs in order to read the source tree from inside the test suite. A gate that has
to live outside the suite is a gate nobody runs.

## Open

Moved to Resolved on 2026-09-23: O10, O15 and O18 (closed in wave 2c), and R15, R9, R10, O2 and O3
(resolved earlier but filed here). New in wave 2c: O21–O23. Wave 3 (`443a05a`): every "new" item of
the re-grade of `1d19e22` was fixed in code (R39–R53) except the harness's palette keystroke race
(O28); O16 is FIXED IN CODE but not re-measured at `443a05a` (the re-grade of `443a05a` then
measured it, O16); new O24–O28. Wave 4 (`8e873d2`,
`70bea72`): the re-grade of `443a05a`'s new items 1–12 were fixed in code (R54–R65) and O24 moved to
Resolved; of its item-13 leads, the stale card is R66, the missing period R55 and the palette over B7
O32; the C5 motion items all PASS in one reported independent run (R60), leaving O16's residuals; new
O29–O34. Not examined by the re-grade of `443a05a` and not touched in wave 4: O6, O7, O8, O11 and
O14.

### O11. Should an earlier refused hop undercut a denial? — OWNER DECISION
From R16. The claims-engine lane did not make the rule "every hop before the last must be RESOLVED"
for denials: `src/fabric3d/flow-terminal.counterfactual.test.ts:76` (another lane's file) builds a
two-hop denial where both hops say denied, and the strict rule turns it red. The lane's reasoning: for
a refusal, an earlier refused hop never makes the claim stronger. If the strict rule is wanted, that
fixture must change `{ ...first, nextHost: first.host }` to
`{ ...first, verdict: "forwarded", nextHost: first.host }` and the rule be tightened in
`hopsSupportOutcome`. Not decided; recorded so it is not mistaken for an oversight.

### O12. A1 — evidence for a finding holds for 12 of 146 — OPEN, NOT CLOSABLE IN ATLAS SCOPE (needs per-finding record pointers from the producer); B1's four-surface residual FIXED (R27)
**A1** (acceptance grading, FAIL). The compiler-evidence lane reproduced it and searched the source
snapshot for any per-finding pointer to an interface, ACL line or config block: none exists. The only
field the compiler dropped was `source_command` (33 of 146 punchlist rows), which names a show-command
assigned by category (`cisco_toolkit/analyze.py` ~7599, `_PUNCH_SOURCE_COMMAND`), not a record. It is
now compiled (`sourceCommand`, via a `PUNCHLIST_FIELDS` map in `tools/compile-snapshot.mjs:222` that
stops the build on any unknown punchlist key — verified in code) and rendered once per finding by
`FindingSource` in `EvidencePane.tsx`, saying explicitly it is where the evidence came from, not a
record to open. Pinned by `src/panels/EvidencePane.source.test.tsx` (its first test is class-wide:
every producer key must reach the compiled finding) and new pins in `EvidencePane.namedconfig.test.ts`
(33 cited; only F106/F107 land on literal text, through the existing MGMT_IN match) — both re-run
green. `fabric.json` was then `6c7d78ab…6fa9095` (verified by the reconciler's `sha256sum` in wave 1;
since O15 it was `2f558c38…a308`, and since wave 4's B6 compiler change it is `a1a599b8…d251`, R54). **The grade does not move: still 12 of 146.** Closing A1 needs the
engine to publish per-finding record pointers — a producer change in the parent repository's engine,
not an Atlas Scope change; the data it would need is, per finding, the interface, ACL line or config
block the finding was derived from. Not re-examined in wave 2c. **Confirmed exactly by the re-grade
of `1d19e22`** (Ctrl+K census of all 146: 6 reach the named configuration, 6 the matching record, 133
context only, F142 no button); no wave-3 cluster touched it. **Confirmed again by the re-grade of
`443a05a`** (A1 FAIL: `{matched:6, named:6, context:133, none:1}`, typed after a 250 ms settle, O28);
no wave-4 cluster touched it — W4-R2 kept the A1 census pins (`EvidencePane.namedconfig.test.ts`,
`EvidencePane.source.test.tsx`) green while splitting the EvidencePane loops (R64). Still NOT
CLOSABLE IN ATLAS SCOPE.

**B1 residual — FIXED (see R27).** Wave 1 left four surfaces printing the raw band without
`presentBand` (`CommandPalette.tsx:194`, `query.ts:189`, `query.ts:219` — the `is:healthy` answer — and
`PriorityQueue.tsx:184`). They were routed through the owner in the interrupted wave 2 (committed in
`254694b`), and `band-read.guard.test.ts` now checks the class — every typed read of `Device.band` —
rather than a list of surfaces.

### O13. B8 — the counterexample's positive state never renders on real data — OPEN (UNPROVEN)
After R17, the claims-engine lane re-swept: **0 of 2,498** real denied or dropped flows get a
counterexample. The one real-data near-miss the acceptance grading found was an artefact of the bug
R17 fixed. "Counterexample — the nearest flow that behaves differently" still renders only in
`engine.counterfactual.test.ts` on a fixture. B8 stays UNPROVEN; it cannot be exercised on this
snapshot, and should not be made to render by loosening the near-miss rule. NOT CLOSABLE IN CODE on
this data: it needs a snapshot in which some denied or dropped flow has a nearest flow that behaves
differently. Not re-examined in wave 2c (R35's pin asserts the one related real flow is offered no
nearby flow). **Confirmed by the re-grade of `1d19e22`:** 15,606 traces, `definiteDelivery=0`, 0
counterexamples. Not touched in wave 3. **Confirmed by the re-grade of `443a05a`** (11,988 traces:
0 decided refusals, 0 definite deliveries, 0 counterexamples; the positive state renders only under
`vi.mock('./rib-completeness')`). Not touched in wave 4; W4-R5 reported the `engine.counterfactual`
ratchets green. A2 needs the same kind of data (O34).

### O14. `failureImpact(h).engine.record` aliases the compiled snapshot — OPEN (owner: `blast.ts` / `core/data.ts`)
Found by the hollow-test repair (R19): the new `repeatable()` check wrote a junk key into the first
result and it appeared in `engine.record` on the second run. `blast.ts` returns the compiled
`failure_impact` record itself (`return { record, basis: "different-measure", … }`, ~`:1267`), and
`core/data.ts` does not freeze `fabric` (verified by grep: no `Object.freeze`). Any caller that writes
to the result mutates the snapshot for every later caller. Fix: copy the record in
`compareEngineImpact`, or deep-freeze `fabric` in `core/data.ts`. Until then, `blast.test.ts` skips
objects that belong to the snapshot, with a comment saying why. Reported by the lane, confirmed in
code by the reconciler, not independently reproduced. No wave-2c cluster owned or touched it, nor
did wave 3 or wave 4; the re-grade of `443a05a` did not examine it.

### O16. C5 — motion render quality: every C5 motion item PASS in one independent laboratory run at `70bea72` (reported, R60); OPEN: a caller's tier change mid-motion still freezes the view for its re-warm-up (OWNER DECISION: the render owner) and the cluster-rule wording (OWNER DECISION: the C5 owner)
**Status at `70bea72` (wave 4).** The re-grade of `443a05a` measured edge shimmer and z-fighting PASS
in a laboratory run (flip px 0–37 against 120, 0 clusters) on a contended host that was not
tier-held, and failed C5 on popping instead. Wave 4 fixed both pops, the harness's tier blindness and
the caller-pin defect, and an independent verifier's `capture-motion` run at `70bea72` passed all six
items with every sequence at its pinned tier (R60; reported, not re-run by the reconciler). What
remains open:
- **A caller's tier change mid-motion — OWNER DECISION (the render owner).** A `setQuality` to a
  DIFFERENT tier (the Quality control) issued while the camera moves still presents no new frame
  until the new chain's re-warm-up ends — about 400–500 ms, measured on the dev build (W4-R4,
  reported) — and the overlay then releases within one frame. `70bea72` removed only the same-tier
  case (no rebuild, no warm-up). Closing it needs `applyQuality` restructured so the old chain keeps
  presenting while the new one warms; W4-R4 declined it as architectural and the gate refused it for
  this wave. §4.8 says so ("a caller-made tier change (`setQuality`) is not deferred").
- **What the C5 evidence does not cover.** The app passes no pin, so an ordinary session runs on the
  adaptive tier and can step down (only at rest since R60); the HIGH-leg evidence is about a pinned
  high tier, and `capture-motion` no longer observes an organic step-down, which rests on
  `stepdown*.test.ts` and the cross-fade item. One host (Intel iGPU, ANGLE D3D11).
- **Optional, the `camera.ts` owner.** A `tweenRemainingMs(nowMs)` accessor on `CameraRig` would let
  `scene.ts` stop inferring the tween clock from the `isTweening()` edge plus `CAMERA_TWEEN_MS`; a
  `moveTo` re-issued mid-tween currently reads its arrival early, which ramps the blend out sooner and
  never causes a pop (W4-R4, reported). The gate did not apply it: it would have changed the motion
  code the same gate was judging.
- **The cluster-rule wording — OWNER DECISION, unchanged** (below).

**Status at `443a05a` (wave 3), superseded above.** The re-grade of `1d19e22` confirmed this FAIL at both tiers (304–739
px against the 120 px bar on all 8 orbit sequences) and saw the 16 px cluster move to dark/low. The R5
cluster first classified the flip-flopping pixels (a verdict-neutral diagnostic in
`capture-motion.mjs`): about 90 % thin strokes, the rest silhouettes, 0 highlight and 0 flat, so
neither specular anti-aliasing nor a steadier SSAO applies. **The fix is a HISTORY BLEND**,
`postfx.ts:176–188` `HISTORY_AA` / `historyWeightFor` and `HistoryEffect` (`:203`), verified in code:
while the camera creeps at 0.02–0.5 drawing-buffer px per frame the final pass mixes **0.75** of the
previous presented frame; the weight ramps to exactly 0 below 0.02 px and between 0.5 and 1 px, and
is 0 — the plain chain, bit for bit — when the camera is still, fast, or when anything other than the
camera changed (`contentVersion`, `scene.ts:1746–1756`); a plain frame is owed before `converged`.
**The design's stated trade-off:** it is temporal smoothing *without reprojection*, so while the
camera creeps an edge can trail by up to roughly the creep distance over a few frames. `docs/
render-decisions.md` §10 records the decision. **Pinned by** `render-c5-r4.test.ts` (19, including
"a creeping camera … gets the full weight", "ramps in and out instead of switching…" and "the
controls' change listener requests a frame and does not bump the content version") — re-run green.
These pin the weight function and the invalidation, not the pixels.

**What is measured, and by whom.** No capture-motion threshold changed since `d3e2a1c`
(orchestrator: `ZF_MAX_SHARE` 0.0002, `ZF_CLUSTER` 16, `SPIKE_RATIO` 3, `POP_*` and `AO_*`
identical — consistent with the reconciler's diff, where those lines only re-indent); the one addition
is `SPIKE_NORM_FLOOR` 1.6 (R52), and the flip classification is reporting only (`flipShare` is
computed as before). The R5 cluster reports every C5 item PASS on a scratch release build (orbit flip
px 11–40 against 120, 0 clusters; same-host A/B `d3e2a1c` 300/699 px against 5–26 px on dark/high;
exit 4 only for build freshness). **The merged-tree gate did not run `capture-motion`** (orchestrator;
its result lists no such run). `render-decisions.md` §10 nevertheless states a "re-measured on the
merged wave-3 tree" figure of 9–35 px; those figures match exactly an ignored
`review/shots/motion/report.json` generated 2026-09-23T06:17:03Z (09:17 +0300; later overwritten by
the re-grade's C grader, whose backup is in that session's scratchpad) against a fresh build
of this checkout on :4181, every item PASS (orbit flip px 17/35, 17/23, 20/32, 9/34; 0 clusters). By
file times, `src/app/shell.css` was edited after that run (09:24, the R46 `overflow-y: scroll` rule)
and the commit is at 10:12, so that report is not a measurement of `443a05a`, and who ran it is not
recorded. **C5's PASS therefore rests on the R5 cluster's own runs until the sweep re-measures it at
`443a05a`.** Raising the bar was not used, and is still not a fix. Also reported by R5: settled frames
are unchanged (`capture.mjs twice 5`, 32 of 32 byte-identical across 5 runs), and one contended run
stepped the auto tier high → low mid-orbit and recorded a 9.8x motion spike at the step — the
product's step-down under a 100 %-busy host, not the blend; with the tier held every item passed.

**Owner decision, unchanged.** The z-fighting rule counts any 4-connected cluster ≥ 16 px while its
comment calls that "a 4x4 patch" (`capture-motion.mjs:154` at `443a05a`; `:167` at `70bea72`, still
there; `ZF_CLUSTER` is still 16). The only cluster ever
recorded was a 16x1 run; with the blend it has not recurred (0 clusters in 4 reported runs and in the
09:17 report, and 0 in every reported wave-4 run including the independent one at `70bea72`), but the
code/comment contradiction stands and narrowing the rule needs sign-off.

**Status at `1d19e22` (orchestrator's run), superseded above.** `node review/capture-motion.mjs` exits 3 on two items:
**z-fighting** — one 16 px cluster, dark/high/orbit-drag; and **edge sparkle** — flip share
0.00054–0.00132 of the canvas (325–793 px) against a 0.0002 bar, on all 8 orbit sequences. Label
popping (0 blinks), AO drop/restore and the 280 ms tier fade PASS (R29, R30).

**Attribution (motion cluster, reported; the probes are in the orchestrating session's scratchpad).**
The unchanged harness, run on the dev build with only `SMAAEffect`'s blend weights cleared in-page,
passed every item on all 48 sequences (flip px 7–65 against the 120 px bar; 0 clusters), so the
remaining failure is made by the SMAA stage's per-frame edge and pattern decisions on 1–3 px features
(cables, state-ring curbs, faceplate strips) under the damped orbit's sub-pixel creep — temporal edge
aliasing, not a depth tie. Cable depth ties contribute nothing (cable `depthWrite=false` with SMAA off
gave the same count). **No single SMAA setting closes it:** diagonal detection off 259 px (the largest
single knob); corner detection off, no change; MEDIUM/LOW presets 347/350; LUMA detection 1408;
excluding cable pixels from the blend 185; diagonal off plus that exclusion 107 (light/low) and 187–194
(dark/high); 2× supersampling 75–125, at 4× fill cost.

**What would close it.** An anti-aliasing stage that is stable under motion — for example multisampled
rendering through the composer, or SMAA output accumulated with history while the camera creeps and
reset at rest so settled frames stay byte-identical for F6 — measured against E4's frame rate on the
real GPU; or an explicit decision by the C5 owner on whether this share bar is C5's "aliased edges"
item. **Raising the bar is not a fix.** Also for that owner: the cluster rule counts 4-connected pixels,
so a 16×1 single-row run qualifies although the harness comment calls a cluster a 4×4 patch; making the
rule 2-D narrows a check and needs sign-off.

**Original measurement (2026-09-22, before wave 2c), retained.** Measured by the C5 motion harness
`review/capture-motion.mjs` (fresh release build on :4181, 1440×900, DPR 1, ANGLE/Intel D3D11,
dark/light × high/low, every rAF captured at 59.9 fps median; the harness exits 3). Report
`review/shots/motion/report.json`, frames under `review/shots/motion/_evidence/` (2.8 GB, gitignored).

| Item | Verdict | Evidence |
|---|---|---|
| Z-fighting | **FAIL** | 1,234 slow frame steps: pixels reverse 3+ times in 6 frames by ≥12/255 while the camera moves 0.0006–0.07 px/frame; 17–30 px clusters (e.g. dark/low at x507–511, y598–611); 0.07–0.13 % of canvas in 10 sequences. At both tiers, so not SSAO or SMAA. Zoomed: a chassis's thin right side face seen edge-on, where it meets lid and floor ring — near-coplanar depth ties. `_evidence/dark/{high,low}/orbit-keys-slow/flipflop-*.png` |
| LOD / effect / label popping | **FAIL (labels only)** | Canvas: 0 pops over 2,667 still pairs, 0 motion spikes. Labels: 29 blinks (a visible/hidden run ≤5 frames), 6 of one frame (e.g. `access15` hidden 1 frame at reset-fly 28–29), clustered at fly-to starts. `series.json` `vis` logs |
| AO drop/restore (high) | PASS | 8 of 8; returns 133–150 ms after fly-to (hold 140 ms); worst jump 0.061 % ≥8/255 against a 0.5 % bar |
| 300 ms tier cross-fade | PASS | 24 of 24; 299.9–300.1 ms, max step 0.10/frame (bar 0.25) |

Two statements in that table are superseded by wave 2c: the clusters were **not** near-coplanar depth
ties on the chassis side face (R31), and "at both tiers, so not SSAO or SMAA" could not rule out
SMAA, which is on at every tier (`quality.ts`, `smaa: true` in all three profiles). The tier fade is now 280 ms (R29). Also recorded then, and still
unexplained: one early run cut a high→low fade across a 517 ms frame gap and did not recur in 36 later
fades. The harness forces `preserveDrawingBuffer` and wraps `requestAnimationFrame`; each is justified
in its header.

### O17. Layout residuals after R25 — OPEN (the single-column overflow FIXED at 800–1000 px in wave 3, R42; 768 px itself, descender clipping and compact density still open)
**Status at `70bea72`.** Unchanged by wave 4. The reconciler's `layout-guard.mjs` run at `70bea72`
measures invariant 5 at 1000x800, 900x700 and 800x600 only (all three hold), so 768 px itself is still
unmeasured; descender clipping still has no detector (the re-grade of `443a05a` confirmed both, and
did not grade compact density). Wave 4's 390 px scope-bar fix (R57) is a different defect.

- **768 px queue overflow — addressed at 800–1000 px, not measured at 768.** At 768 the queue rows
  overflowed their own track and the status bar covered them. Wave 3 found the same fault across the
  single-column band (768–1023 px) at 1000x800, 900x700 and 800x600 and fixed it (`shell.css:643–650`,
  R42); `layout-guard.mjs` INVARIANT 5 holds at those three sizes (reconciler's run). The media query
  starts at 48rem = 768 px, but no guard or recorded probe has measured 768 itself since, so whether
  those rows now end at the status bar there is not established.
- **Descender clipping** is invisible to `readTextFidelity` (midpoint rule), so a clamp that cuts
  descenders passes the gate. Wave 2c widened the detector (identifier splits, node-boundary splits,
  overruns; R28) and wave 3 added form reach (R46), but not this; the R2 cluster left it open
  (optional in its brief).
- **The path-slot clipping** the re-grade asked to file here was FIXED in wave 3 (R46); its stated
  consequence, the queue under rail A's fold, is O24.
- **Proof scope** (closed as far as it goes). The layout lane measured only :4180; the reconciler
  re-ran `capture.mjs text` on the :4181 build (72 of 72, exit 0), and the merged-tree gate ran
  `capture.mjs app` on :4181 (32 of 32, exit 0), which applies the same checks per frame. That 72 of 72
  was measured with a detector blind to identifiers and is superseded; the wave-2c 72 of 72 (R28) was
  re-run by the reconciler on a scratch build of `1d19e22`. The detector now has a known-answer
  self-test (17 cases) but has not been independently refuted.
- **Compact density** still truncates titles by design (windowing needs uniform row height). C3 was
  graded at comfortable density; compact is not covered by the fix.

### O19. C1 — a valid blind verdict set is not achievable against these reference products — OWNER DECISION
`docs/acceptance.md` C1 asks for blind, side-by-side verdicts with ≥2 independent critics per pairing,
the critic not told which is which. Against the current references that condition cannot be met, not
merely has not been:
- **The references identify themselves by content and chrome.** `review/REFERENCES.md` records that
  the round-2 decoder found "in every verdict the critic's loser was the REFERENCE panel", that the
  brand-cropped `-craft` variants did not prevent identification, and that the Forward captures carry
  the Storylane tour modal and a "Click on Vulnerability" coachmark while the Grafana captures carry a
  "Create free account" banner. Two automated drivers failed to advance the tours past their opening
  step, so no chrome-free Forward capture exists. A critic who can tell which image is the demo is not
  blind, however the files are named.
- **What evidence exists.** Rounds R1 32/33, R2 36/36, R3 36/36 head-to-head wins (withdrawn as C1
  evidence by `REFERENCES.md` itself: saturated at 72/72, so it cannot discriminate); ~350 specific
  faults listed against OUR panel across three rounds, falling from a peak of 24 per critic to 7–13 —
  real evidence of improvement measured against itself, which is not what C1 asks; and
  `review/blind/KEY.json` for 12 sheets with **no recorded verdicts**, beside 20 sheet images, 8 of
  them orphans the KEY cannot decode.
- **Why none of it is C1 evidence.** Blindness is the criterion's load-bearing property, and every
  recorded verdict was given by a critic who could identify the reference.

C1 stays UNPROVEN. Moving it needs an owner decision: supply references that can be captured clean
(product access rather than a guided demo), choose different reference products, or restate C1 in
`acceptance.md` to what can honestly be measured. Re-running more rounds against these images would
produce more of the same non-evidence. **Confirmed by the re-grade of `1d19e22`** (`KEY.json`: 12
entries, zero verdicts; 8 of 20 sheets orphans; the `-craft` sheet still shows "Forward AI" and the
Storylane modal). Still an owner decision; not touched in wave 3. **Confirmed again by the re-grade
of `443a05a`** (same `KEY.json`, same orphans, same `-craft` sheet); not touched in wave 4.

### O20. Minor drift and E5 harness limits carried from acceptance — `--sev-high` drift FIXED (R36); the probe gap FIXED in the harness (R37); the sweep's stalled-window blindness FIXED in the harness (R63); the pre-FCP carve-out is an OWNER DECISION; E5 PASSED at the re-grade of `1d19e22`, not re-established since
- **Status at `70bea72`.** The re-grade of `443a05a` withheld E5 (cold load FAIL, worst 393.1 ms
  pre-FCP, judged because the carve-out is unsanctioned, at 55 % host load; the sweep NOT MEASURED on
  swap+submit). Wave 4 fixed the sweep's harness defects (R63: stalled-window frames counted apart;
  swap+submit removed as J4's act, R62). No E5 run is reported on the merged tree — the gate ran E2/E3
  and E4 only (O25). The carve-out is still unsanctioned: the reconciler found no
  `E5 EXEMPTION (owner-sanctioned)` line in `acceptance.md`.
- **Status at the re-grade of `1d19e22`, superseding the last bullet below.** E5 PASSED on a quiet
  AC host (`acceptanceEvidence=true`, excess 17–21 %; worst frames 105.2/133.2/110.9 ms; the sweep's
  16 actions under 200 ms in 3 of 3 repetitions) without the carve-out (a palette opened during load
  reached 168–192 ms, a thin margin). **Wave 3:** no acceptance-grade E5 run. The R1 cluster's run
  was refused by the harness (host 68 % busy against a 25 % bar); the R5 cluster's cold-load runs
  FAIL on this build *and* on `d3e2a1c` alike on the same contended host (pre-first-paint frames of
  298–376 ms judged because the carve-out is not sanctioned, and 4 keystrokes over 200 ms) — reported,
  laboratory, not attributed to the wave. The entry chunk is 3.63 kB before and after (R1). See O25.
- **`--sev-high` brief drift — FIXED (R36).** It was one of 31 drifted tokens; all reconciled, and
  `contrast.test.ts` now guards §3.3 against `tokens.css`.
- **E5 keystroke probes — FIXED in the harness (R37), run not verified.** They were sampled at fixed
  times, so the post-FCP frames that block ~145 ms were never probed. Probes are now also aimed at long
  frames earlier runs observed, and each run reports its keystroke coverage.
- **E5 pre-FCP carve-out — OWNER DECISION.** It was never sanctioned in `acceptance.md`. The harness
  now applies it only if `docs/acceptance.md` holds a line beginning
  `E5 EXEMPTION (owner-sanctioned): pre-first-paint`; there is none, so pre-FCP frames are judged (a
  264.7 ms pre-FCP frame now fails E5, reported). Adding that line, or not, is the owner's decision; a
  warm-browser probe had supported the exemption (0 frames over 200 ms before FCP).
- **E5 itself stays UNPROVEN, leaning FAIL.** The only runs are on a busy host on battery (14
  keystrokes over 200 ms, worst 560 ms, at 81 % busy), which the harness refuses as acceptance
  evidence. It needs a quiet run on AC power.

### O21. E3 — input-handler interactions outside the five journeys cross 50 ms — OPEN (owner: the performance cluster) for navigation seeding and resizes; the first selection, swap+submit and the palette open are journey acts since wave 4 (R62)
**Status at `70bea72`.** The re-grade of `443a05a` found this entry's classification contradicted
(E1): swap+submit is J4's own act. Wave 4 redrew the line (R62): the first selection after load is
J1's rep 0, swap+submit is J4 and the palette open is J5, so three of the classes below are now E3
signals on journeys (J5's is O30), not out-of-journey ones. Navigation seeding and resizes, the two
that reproduced at the re-grade of `1d19e22`, are still outside E3's claim and still the owner's
question; nothing since has re-measured them.

**Status at the re-grade of `1d19e22`.** On the quiet host the eight classes below did not reproduce:
seven read worst LoAF 0 ms in all 3 repetitions, and so did path-trace swap+submit. Only "seed a flow
by navigation" (87.3–100.6 ms) and resizes (50.1–63 ms) crossed 50 ms, both outside E3's claim. The
in-journey E3 failure the re-grade found instead was the first selection after load (R51). Wave 3 did
not re-measure these classes. The owner's question stands for the two that reproduced.

**Original entry (wave 2c).**
Found by re-measurement for acceptance.md (provenance cluster, from the e5-sweep 16:30Z report,
3 repetitions, release preview, busy host on battery — laboratory only). Eleven action classes cross
50 ms (worst Long Animation Frame); eight are input-handler interactions outside the declared
journeys: Inspector open on the raw source record 62–144 ms, command palette 98 ms (1 of 3), first
selection after load 93 ms (1 of 3), theme toggles 51–83 ms, clearing the query filter 59–68 ms,
Ctrl+End in the grid 59 ms (1 of 3), path-trace swap+submit 53 ms (1 of 3). `acceptance.md` E3 now says
"no single task over 50 ms" is claimed only on the journeys' paths. Open question for the owner: which,
if any, become journeys or get their work chunked. Not re-measured by the reconciler.

### O22. The determinism gate is keyed on field NAMES — OPEN (shape; owner: `src/core/determinism.test.ts`)
Found by the motion cluster in wave 2c. `FRAME_TIMING_OWNERS` lists frame-timing fields by name, so it
saw the ease channel's `elapsedMs` but cannot see `stepEmphasis`'s identically derived `state.elapsed`,
which was annotated voluntarily. That is a hand-maintained list standing in for the class it means
("a clock-derived value"): the next clock-derived field under a new name reaches a renderer unannounced.
No failing case exists today; the fix is to follow provenance from the rAF timestamp and `performance`
reads (as R15 did for bindings) rather than names. Still open at the re-grade of `1d19e22` (F6 passes,
the shape is unchanged) and not touched in wave 3. The re-grade of `443a05a` found the shape unchanged
(F6 PASS); not touched in wave 4. `FRAME_TIMING_OWNERS` (`determinism.test.ts:258`) still lists
field names; wave 4 added a telemetry field, `qualityAuto` (`telemetry.ts:72`), which is a caller's pin
rather than a frame-time reading, so it is not a failing case — but nothing structural decided that.

### O25. E1–E5 have not been re-established as acceptance evidence since `1d19e22` — every run at `443a05a` and at `8e873d2` was on a busy host — OPEN (owner: the next acceptance grading; needs quiet, on-AC runs)
**Status at `70bea72`.** The re-grade of `443a05a` withheld every E2–E5 run as NOT ACCEPTANCE
EVIDENCE (host 46–59 % busy against a 25 % bar) and turned E1 UNPROVEN on scope, which wave 4 fixed in
code (R62). The wave-4 merged-tree gate's runs, on `8e873d2` (reported; `acceptanceEvidence=false`,
so a lead, not a verdict):
- **E2/E3** (`measure-inp`, on battery at the start and on AC at the end, host 47 % busy excluding the
  harness): 7 pass, 0 fail, 0 NOT MEASURED — p95 J1 40, J2 96, J2-first 96 (21 of 21 trials), J3 152,
  J3b 64, J4 64, J5 80 ms. E3 in that run: 6 clean, 1 violating — J5-open-palette's one 114 ms on-path
  task (O30). Across runs: INSUFFICIENT RUNS (0 quiet).
- **E4** (`measure-fps`, on AC, host 36 % busy): FAIL — focus flights median 53.34 fps (worst window
  51.27), orbit median 55.16 with a worst window of 44.51, below the 45 floor, at tier high; the scene
  reported the shortfall itself (`belowBar`).
- **E5, E1:** not run on the merged tree.
The re-grade runs E alone on AC. Nothing here shows a regression, and nothing re-establishes E1–E5 at
`70bea72`. The `review/reports/fps.json` the paragraph below cites was overwritten by the re-grade of
`443a05a`'s E grader.

**Status at `443a05a` (wave 3), superseded above.** At the end of wave 3 the host went onto battery with a Teams meeting in the foreground, and
`review/host-env.mjs` withheld acceptance evidence from every final run. What exists, all reported:
- **E4.** The one acceptance-grade run in the gate — on AC, before the host changed, on the build
  before the R46 `overflow-y` rule (which does not apply on `?s=fabric`) — was PASS: median 60 fps
  across 10 windows, worst window 60, orbit median and worst 60, p95 16.8 ms, tier high, host 25 %
  busy, window inside the screen, `acceptanceEvidence=true`. The final re-run on battery: focus flights
  median 57.83 / worst 55.56, orbit FAIL at a worst window of 39.04 fps with the tier lowered to
  balanced and the drop reported, THROTTLED, `acceptanceEvidence=false`. The reconciler read that
  final run's `review/reports/fps.json` (ignored, 10:00 +0300): `powerSupply: "NotPresent"`,
  `throttled: true`, orbit worst 39.04, `acceptanceEvidence: false` — it matches. The R5 cluster's
  earlier E4 run with the blend: PASS, median 58.9, worst 57.8, host 23 % busy.
- **E2/E3.** The gate's final `measure-inp`: all 7 journeys ≤ 200 ms (J1 p95 32, J2 80, J3 64, J3b
  40, J4 56, J5 48, first selection 80 over 21 of 21 trials) and E3 clean — but on battery, host 32 %
  busy against the 25 % bar; E3's across-runs verdict for that build is INSUFFICIENT RUNS (0 of 3
  quiet runs).
- **E5.** See O20.
- **E1.** No wave-3 run reports it (R1 did not run `measure-inp`, for host contention).
The re-grade's E1/E2/E4/E5 PASS were measured on `1d19e22`; E3 was FAIL there (R51). Record this as host
dependence: nothing in wave 3 is shown to have regressed E1–E5, and nothing re-establishes them at
`443a05a`.

### O26. Wall-clock tripwires in the unit suite — the engine and palette halves FIXED in wave 4 (R64); `layout.test.ts:952` still asserts a median under 50 ms — OPEN (owner: `src/fabric3d/layout.test.ts`); contradicts R10's "fixed as a class"
**Status at `70bea72`.** The re-grade of `443a05a` confirmed this entry (F2 overturned:
`CommandPalette.test.tsx:717` read 533 ms against 400). Wave 4 replaced the palette bounds with
counts and the engine's median-of-7 tripwires with structural work bounds (R64). Of the test files
that call `performance.now()` (the reconciler's grep: `CommandPalette`, `determinism`, `layout`,
`engine`, `engine.work-bound`, `Inspector`, `PathTrace`), only `layout.test.ts` still asserts on the
elapsed time: "lays out the full 26-node fabric in under 50 ms", median of 7 (`:944–955`). Its
comment argues it has never flaked; it contradicts `vitest.config.ts`'s rule ("a unit test asserts no
wall-clock time"). The gate declined both deleting it (that would loosen an assertion) and
redesigning it (the owner's); a count of the layout's work would replace it.

**Original entry (wave 3).** Reported by the R2 cluster, full-suite runs under four parallel agents: `engine.test.ts` "keeps the
counterexample search inside the same interaction budget" (`:955`, median of 7 = 54.66 ms against the
50 ms tripwire; the new flow-validation entry check costs 0.54 µs per trace) and `CommandPalette.test.tsx`
"opens over an index that already exists, rather than building one" (`:717–718`, `worst` < 400 ms,
measured 620). Both green in isolation (2 of 2 and 37 of 37, reported) and both green in the
reconciler's run and the orchestrator's full run at `443a05a`. Verified in code: the palette bound is a
worst-of-N statistic, the form R10/O2 names as the most fragile, and the engine tripwire is the
median-of-7 form R10 installed. A red from either is indistinguishable from a regression.

### O27. `review/*.mjs` is outside every type-checked project — OPEN, a declared exclusion (owner: each harness's owner)
Found by the R4 cluster while closing R50: under full strict `checkJs`, 919 diagnostics across 14 of
the 17 harnesses (reported). `scripts-typecheck.test.ts` requires every other authored TS/JS file to be
in a project and names `review/*.mjs` as the one declared class exclusion. The harnesses are the
acceptance instruments, so a type error in one is a measurement defect; closing this needs the
annotations in files other lanes own. **Status at `70bea72`:** unchanged (the re-grade of `443a05a`
found it so). Wave 4 edited five harnesses — `audit-d3-focus`, `audit-e5-sweep`, `capture-motion`,
`layout-guard`, `measure-inp` — which stay outside every type-checked project
(`scripts-typecheck.test.ts:127`, `:200` still name the exclusion). Some of their pure functions are
now executed by unit tests through import (`journey-scope.test.ts`, `Fabric3D.test.tsx`,
`render-c5-repairs.test.ts`), which runs them but does not type-check them.

### O28. The A1 census's palette keystroke race — OPEN, harness (owner: the grading harness)
From the re-grade's item 15: typing into Ctrl+K with no gap after opening garbled 53 of 146 queries,
0 with a 150 ms gap. It was not shown that a human would hit it, and no wave-3 cluster addressed it.
Until it is, an A1 census must type after a settle. **Status at `70bea72`:** not addressed in wave 4;
the re-grade of `443a05a` typed its census after a 250 ms settle to avoid it.

### O29. Tracked sources cite gitignored `review/_*.mjs` scratch scripts as their measurement — OPEN, a class (owners: the files named)
Found by W4-R2 while rewording `env.test.ts` (R64); verified by the reconciler. `.gitignore:50` ignores
`review/_*` and `git ls-files 'review/_*'` returns nothing, so a clone cannot re-run any of them
(`review/_audit_cableaa.mjs`, for one, survives only as the untracked
`review/_scratch/_audit_cableaa.mjs`). The reconciler's grep finds such citations in 10 tracked files
under `src/`: three tests (`fabric3d/render-audit.test.tsx:6`, `fabric3d/scene.test.ts:572`,
`fabric3d/geometry/cables.ink.test.ts:11`) and seven product modules' comments (`fabric3d/scene.ts`,
`fabric3d/geometry/cables.ts`, `fabric3d/lighting.ts`, `fabric3d/Fabric3D.tsx`,
`panels/PathTrace.tsx`, `panels/DataGrid.tsx`, `ui/primitives.tsx`). A figure cited that way is a
historical record, not re-runnable evidence, and none of these says so. A guard over the class — like
the one `acceptance-gates.test.ts` now holds for cited tests (R63) — would go red on these files until
each is reworded as `env.test.ts` was or its script is tracked.

### O30. E3 — `J5-open-palette` puts a task over 50 ms on its path, run after run — a LEAD, not a verdict (owner: the performance cluster)
Every measurement is on a busy host, so none is acceptance evidence. The re-grade of `443a05a`: J5
violated E3 in 3 of 3 runs (worst 94 ms, `#document.onkeydown` in the mount chunk, forced layout
41 ms) and in 5 of the 6 records for that build in `review/reports/inp-e3-history/`; E3 "leans FAIL"
there. The wave-4 gate at `8e873d2` (47 % busy, on battery at the start): one 114 ms on-path task
(`#document.onkeydown`, 33 ms of forced layout). Since R62, Ctrl+K open is J5's own act, so this is a
journey signal, not an out-of-journey one. No wave-4 cluster worked on it; 3 quiet, on-AC runs decide
it (the re-grade runs E alone on AC).

### O31. `measure-inp`'s J2 page does not wait for the scene to settle before its loop — OPEN, harness lead (owner: `review/measure-inp.mjs`)
Reported by W4-R2: in a floor-lane dev-server run on a loaded host all 3 J2 clicks "selected
nothing". Verified in code: `FIRST_SELECTION.beforeClick` waits for `stats().converged`
(`measure-inp.mjs:755`), while each journey's page waits only for its ready selector and 2,500 ms
(`:1100–1101`). The same read-only settle wait before J2's loop would make the two consistent. Not
reproduced by the reconciler.

### O32. The Ctrl+K palette covers the status bar's coverage group (B7) at 390 px while it is open — OPEN lead, not examined (owner: the palette's)
From the re-grade of `443a05a`, which upheld B7 and listed this as a lead (a transient modal). No
wave-4 cluster addressed it, and whether a modal that covers the coverage figures while it is open is
a defect under B7 has not been decided.

### O33. Two engine guards are bounded but cannot be exercised on this snapshot — NOT CLOSABLE IN CODE on this data
Reported by W4-R5, consistent with the code read by the reconciler. (1) `buildSuggestions`'
"unevaluable" suggestion (`engine.ts:2879`) used to map any non-udp/icmp line protocol (gre, esp…) to a
tcp flow and say the line "could match this flow"; it now picks only a line whose `matchTri` against
the built flow is not "no", but removing that guard leaves every test green, because no collected
line reaches the branch with an excluding protocol or port. (2) Removing `COUNTEREXAMPLE_CANDIDATE_CAP`
(48) also survives: no request on this snapshot has more than 8 candidates. Each becomes provable only
with producer data: an ACL line of another protocol reaching the unevaluable-suggestion branch, and a
counterexample search with more than 48 candidates.

### O34. A2 and F3 — UNPROVEN at the re-grade of `443a05a`, and neither can be moved by code in Atlas Scope — NOT CLOSABLE IN CODE
- **A2** (depth). The shipped snapshot's maximum depth is 1 with 0 resolved next hops (the depth
  ratchet asserts `toBe(1)`), so the second hop's decider, hop-to-hop navigation, `resolveNextHost`'s
  cable-map branch, the TTL cut and the loop detector have never run on real data. It needs a snapshot
  with depth-2 flows — the kind of data O13 needs for B8. See R18 and R45.
- **F3** (historical red-before-fix). Proven by history only for the O15 provenance tests
  (`254694b` → `1d19e22`); for the forwarding, blast, layout, query, compiler and claims engines it
  rests on today's-code mutations (`mutation-check.mjs`, 18 of 18 KILLED, reported). There is no
  history before `50a3dc5` to show more. The checkpoint commits `254694b` and `2d9712c` put some later
  tests on record before their fixes; that does not reach the engines' original defects.

### O23. Only F5 has been re-run from a clean clone since `1d19e22` (the re-grade of `443a05a`, a real `git clone`); nothing has been run from a clone of `70bea72` — OPEN for A–E and F1, F2, F4, F6 (owner: the next acceptance grading)
**Status at `70bea72`.** The re-grade of `443a05a` closed this for F5 at that commit (a real
`git clone` under `autocrlf=true` reproduced all four compiled outputs byte-identically); F1, F2 and F4
ran in the working checkout and A–E did not run from a clone. Wave 4 changed 58 files across
`2d9712c`, `8e873d2` and `70bea72`, and every check since — the agents', the gate's, the
orchestrator's and this reconciliation's — ran in the working checkout. The structural limit below is
unchanged.

**Status at `443a05a`, superseded above.** The re-grade of `1d19e22` closed this for F1, F2 (unit half), F4 and F5 on a
clean clone of `1d19e22`, with the parent blob `1ed99404` placed at `../webapp`; A–E were not re-run
from a clone. Wave 3 changed 73 files; nobody has cloned `atlas-scope` at `443a05a` and run anything
from the clone (the orchestrator's `tsc`, `vitest` and build ran in the working checkout, which is
clean at that commit). The structural limit below is unchanged.

**Original entry (wave 2c).** Every F1–F6 result in `docs/acceptance-report.md` was taken on an
uncommitted working tree, and `acceptance.md` asks for a re-run on a clean checkout of the resulting
commit. The tree is now committed (O10), but that re-run has not happened: no one has cloned
`atlas-scope` at `1d19e22` and run `tsc`, `vitest`, the build, the compilers or the capture gates from
the clone. One limit that re-run will meet
is structural, not a defect of the commit: the compilers read
`../../webapp/sample_data/sample_fleet.snapshot.json`, which only the parent repository tracks, so
reproducing F5 from a clone needs the parent at a revision whose blob hashes `9580aa09…3089`.

### O8. The ignore-ACLs counterfactual (design-brief §5.2 step 6) is NOT BUILT — and is no longer advertised
Found by an independent critic, confirmed at the source. The command palette carried
**"Toggle the ignore-ACLs counterfactual"** with the shortcut `M`, and explained its unavailability
as *"the path panel is not on screen in this layout, so this action has nothing to act on"* — a
sentence rendered **with the path panel on screen and a trace drawn**
(`?s=path&flow=10.0.10.50>10.0.30.10>tcp>3389`). Nothing in `src/` ever registered a target or
published a `data-atlas-command` owner for `acl.toggleCounterfactual`, so `capabilityAvailable()`
was permanently false. `claims.ts :: T6_counterfactual()` — the brief's T6 template — has zero call
sites outside its own module.

**What was done, and what was deliberately not.** The palette row and the orphaned capability are
removed, and `src/app/commands.capability-owners.test.ts` now asserts over the source that EVERY
member of the `Capability` union has a registrar or a DOM owner — so an orphan is a build failure
rather than a misleading palette row. The feature itself was not built here: doing it properly
needs (a) a `traceFlow(flow, { ignoreAcls })` option in `src/forwarding/engine.ts` — feasible, the
ACL gate has exactly one call site, `engine.ts:1293` — and (b) the `MODE · ignore acls` chip the
brief requires to be carried in the shareable URL, which is `src/core/store.ts` + `urlSync.ts`.
This repair pass was scoped out of both files. `T6_counterfactual()` is retained unused, as the
written contract for the pair of statements that feature must render.

**Do not close this by re-adding the palette row.** A verb announced with a false reason is worse
than an absent one: the reader concludes their layout is wrong.

### O9. B6 asked for the raw SOURCE record; the Inspector can only show the compiled one
The source snapshot is not bundled with the build, so for any citation that is not itself a model
path the Inspector renders the compiled record that carries the citation and says so verbatim:
*"This citation names a record in the source snapshot, which is not bundled with this build. Shown
below is the compiled record that carries the citation…"*. The behaviour is honest and citation
resolution is sound (a probe over all 652 model cites plus the 16 the engine emits at runtime
resolved every one). The **criterion** was what overclaimed, so `docs/acceptance.md` B6 has been
restated to describe what the product does and states.

The capability gap is real and is left open here rather than papered over: shipping a lazily
fetched side file of the snapshot subtrees that carry a cite, keyed by cite, would let the Inspector
show actual snapshot JSON. That is a compiler change (`tools/compile-snapshot.mjs`) and was out of
scope for this pass.

**Status at `70bea72`.** Unchanged in substance. Wave 4 (R54) compiled the `link_centrality`,
`health_scores` and `cable_map.nodes` rows under their source paths, so those citations resolve to a
compiled copy of the source record at the path they name (reported: "This citation resolves directly
inside the compiled model at link_centrality[3]"). The raw snapshot is still not bundled; the re-grade
of `443a05a` found this entry consistent with B6's first-pass evidence and B6's FAIL a different gap.

### O6. At the `high` quality tier, bloom turns honest status rings into halos
Captured at `review/shots/fabric-auto.png` (auto-selected tier `high` on real Intel D3D11, 80 draw
calls, 225k triangles). Every chassis is wrapped in a heavy warm halo that buries the port banks,
bevels and faceplates — the silhouette detail that is the entire reason the chassis geometry exists.
Compare `review/shots/fabric-check.png` at tier `low`, where bloom is off and the same fabric reads
noticeably *better*.

**It is not a correctness bug, and that distinction matters.** The rim colour is the device's health
band, and 18 of the 26 devices in this fleet really are Poor or Critical
(`{Poor: 12, Critical: 6, Good: 3, Excellent: 2, null: 3}`). A fabric that looks alarming is an
honest rendering of an alarming fleet. What is wrong is the calibration: at 18 simultaneous glows
the effect stops reading as "these devices are in a bad band" and starts reading as an undifferentiated
alarm wash, which is a failure of the encoding rather than of the data.

It surfaced only after R5 was fixed: while the shader was failing, the status rims drew nothing at
all, so there was nothing for bloom to pick up. Fixing one defect exposed the next.

Candidate levers, in the order I would try them — **not yet applied**, because the render critic
should reach its own verdict first rather than being handed mine:
  - `state-rim.emissiveIntensity` (currently 1.05) versus the brief's `luminanceThreshold: 1.0`
    floor — the rim is only just crossing the threshold, so a small reduction may drop it out
    entirely, which would be the wrong fix;
  - `SelectiveBloomEffect` `intensity` / `radius` / `levels`;
  - rim geometry screen size, so the glow is proportionate at overview distance.

### O7. A `SCOPED` badge on a verdict whose own caveat undercuts it — QUESTION FOR THE HONESTY AUDIT
Observed in `review/shots/panels-check.png`. The trace for tcp/3389 `10.0.10.50 -> 10.0.30.10`
renders the **SCOPED** badge — the strongest this product has — while its own claim sentence reads:

> "…is denied at core1 by ACL PROTECT_SERVERS line 3 …; **the ACL's interface binding was not
> collected**, and stateful return traffic is not modelled."

The badge is behaving exactly as specified: `claimBadge` awards SCOPED when the traversal completed,
every host on the path is in `coverage.routableHosts`, and no HOP-level evidence item is an absence.
Here core1 is modelled, there is one hop, and nothing at hop level is indeterminate. The rule fires
correctly.

The question is whether the rule is right. No `ip access-group` binding was collected anywhere in
this snapshot, so we do not actually know that `PROTECT_SERVERS` is applied to the interface this
flow traverses. That is not a peripheral caveat — it is uncertainty about **whether the named rule
governs this packet at all**, which is the entire content of the verdict. A badge that says "as
strong as this product gets" sitting above a sentence that says "we could not confirm this ACL
applies here" is at least in tension, and possibly the exact overclaim §6 exists to prevent.

Two defensible readings, and I am deliberately not choosing between them here:
  - **As designed.** SCOPED never meant "certain"; it means the traversal was complete within the
    collected RIBs, and the caveats are rendered immediately beneath it in full. The badge grades
    COVERAGE, not confidence.
  - **A gap.** Trace-level caveats that bear on whether the deciding rule applies should demote the
    badge to OBSERVED, so badge and prose cannot disagree.

**Assigned to the honesty audit in the critique loop**, which did not build any of this and should
reach its own conclusion. If it agrees this is a gap, the fix is in `claimBadge` — a caveat
classifier that distinguishes peripheral limits from ones that undercut the deciding evidence.

**Update 2026-09-21 — the premise was false.** The snapshot DOES carry bindings (`interfaces.core1.
Vlan30.acl_out = PROTECT_SERVERS`, `interfaces.core1.Vlan20.acl_in = VOICE_FILTER`, and a
`candidate_projection_incomplete` marker on core1 Gi1/0/5); the shared compiler never projected them.
They are now compiled by `tools/compile-acl-bindings.mjs` into `src/forwarding/acl-bindings.json`
(sha-bound to fabric.json) and read by `src/forwarding/bindings.ts`. A hop applies exactly the lists
bound on the interfaces it enters and leaves by when those bindings are observed; the specificity rule
runs only where one is unknown, and the hop names which and why. The 3389 denial now reads "the list is
applied outbound on core1 Vlan30 (interfaces.core1.Vlan30)", so the SCOPED badge and the sentence
under it agree. A denial by a heuristically chosen list still records an `acl-unbound-denial` policy
gap and cannot be SCOPED.

### O5. First-look observations on the 3-D fabric (mine, recorded BEFORE independent critique)
Written down now, deliberately **not** fed to the critique loop's render critic. The critics judge
blind; if they independently surface the same items that is convergent evidence, and if they find
things this list misses that is a measure of how much a single reviewer misses. Feeding my notes
in first would destroy both signals.

Observed from `review/shots/fabric-check.png`, 1600×900, dark theme, SwiftShader (quality tier
`low`, so some of this may be tier-specific — flagged where relevant):

1. **Camera framing is too wide.** The fabric occupies roughly 40 % of the frame; the rest is empty
   background. The brief's framing should fit the bounding sphere with margin, not with a void.
2. **The layout reads as a hub-and-spoke starburst, not a tiered hierarchy.** The core pair sits at
   top centre and everything radiates from it. `layout.ts` does run barycentre sweeps and its tests
   assert measurably fewer crossings than naive ordering — so this may be a CAMERA-ANGLE problem
   (a near-plan view projecting a clean tier structure into a radial one) rather than a layout
   problem. Worth distinguishing before anyone "fixes" the layout.
3. **Heavy cable crossing in the middle band**, following from (2).
4. **Contact grounding reads as soft blobs** rather than crisp occlusion. Possibly the `low`
   quality tier disabling or downscaling SSAO under SwiftShader; needs a check at `high`.
5. **No device labels** in this capture — expected, since `FabricLabels` is a DOM overlay and the
   preview harness mounts only the canvas. Not a defect; noted so it is not mistaken for one.

None of these is a correctness defect. They are craft items, which is exactly the category the
blind comparison exists to adjudicate.
