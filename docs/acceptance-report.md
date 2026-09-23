# Atlas Scope — Acceptance Report

Graded 2026-09-23 against `docs/acceptance.md`, at HEAD `443a05a` (`443a05a4ce596d4e6eaa0c67ab646d4d00c5fa5a`).
The working tree matched HEAD except for an uncommitted edit to `docs/open-issues.md` made by a
parallel session. `git ls-files --others --exclude-standard` returned nothing, so the build imports
no untracked file. Six first-pass graders covered groups A–F. Independent refuters then attacked
every PASS.

**Where the first pass and the refutation disagree, this report applies the refutation.** Five
verdicts were overturned: B1, B6, D3, E1 and F2. Each overturn came with a reproducible proof (a
command and its output), so none was set aside. All 23 surviving PASS verdicts were attacked and
upheld, so no verdict here is "PASS, unrefuted". Every group returned a grade.

Where each group was graded:

- **A, B and D:** the Vite dev server on :4180. That is not the shipped bundle.
- **C:** a fresh `vite build`, byte-identical to `dist/` apart from source maps, served on :4181. Some C probes also ran on :4180.
- **E:** a fresh `npm run build` (served `index.html` sha `c88fe27230004123`) on :4181.
- **F:** the working checkout, `git archive HEAD` sandboxes, a private :4197 preview and, for F5, a real `git clone`.

**The tracked-sources gate (a precondition, not a criterion).** Every grader ran
`src/core/tracked-sources.test.ts` and it passed, for example "6 of 6 passed, exit 0" in groups B,
E and F. The F grader also found every one of the 69 repo-local sourcemap sources in
`git ls-tree HEAD`. No refuter attacked the gate this round, so it is recorded here and not under
"What is proven".

This report replaces the re-grade of `1d19e22` at this path. Figures in that report are history, not
evidence for `443a05a`.

## Verdict

**Atlas Scope is not ready for acceptance.** Six criteria fail and ten are UNPROVEN. An UNPROVEN
criterion is not a pass.

The six failures:

- **A1:** a finding reaches its own evidence in only 12 of 146 cases.
- **A4:** a finding listed under two groups throws the queue about 3,200 px when a visible copy is clicked.
- **B1:** the Path panel renders a null administrative distance as "0" while the Device pane renders the same record as "not observed". This is overturned.
- **B6:** the link inspector shows the snapshot's centrality claims with no citation. This is overturned.
- **C5:** a history-blend pop, and a frame that freezes for about 1 s when the tier steps down mid-orbit.
- **D3:** four keyboard-activated controls drop focus to `<body>`, where no focus is visible. This is overturned.

Four of the ten UNPROVEN criteria cannot be decided with what exists today:

- **A2 and B8** need a snapshot with depth-2 flows and a decided refusal.
- **C1** has no blind verdict, and cannot get one against these references.
- **F3** has no history before the root commit to show red-before-fix.

The other six UNPROVEN criteria:

- **E2–E5:** every run was withheld by the harness as NOT ACCEPTANCE EVIDENCE, because the host was 46–59% busy against a 25% bar.
- **E1:** the declared journeys contradict the out-of-journey classification that `acceptance.md` builds on them. This is overturned.
- **F2:** one full `vitest` run went red under load, with a 30 s timeout and a wall-clock bound failing. This is overturned.

Some things are well evidenced and survived attack:

- the forwarding engine's honesty (B2–B5, B7);
- blocked-flow attribution, on-fabric operation and cut-point marking (A3, A5, A6);
- craft of settled frames, themes and motion durations (C2, C3, C4, C6);
- keyboard, contrast, target size and assistive semantics (D1, D2, D4–D8);
- type-checking, code-splitting, reproducible compilation and deterministic capture (F1, F4, F5, F6).

**Movement since the `1d19e22` re-grade.**

- **Now PASS:** C2, C4 and D5. The tracked-sources gate is green.
- **Still FAIL:** A4, B1 and D3, each on a path the wave-3 fixes did not cover.
- **New FAIL:** B6.
- **PASS to UNPROVEN (host):** E1, E2, E4 and E5. This reflects the host, not a regression the graders could attribute to the product.
- **FAIL to UNPROVEN (host):** E3 has no quiet run.
- **UNPROVEN to PASS:** C6.

## Scorecard

"Overturned" means the refutation's verdict replaced the first pass. "Upheld" means a refuter attacked
the PASS and could not break it.

| Criterion | Verdict | Evidence | Note |
|---|---|---|---|
| A1 | **FAIL** | Ctrl+K census of all 146 findings, typed after a 250 ms settle (O28): `{matched:6, named:6, context:133, none:1, wrongSel:0}`. For F099: 3 interactions to "access13 Gi0/11 (err-disabled)", and the core1 box stayed `[447,82,503,111]`. For F057 the only button is "Browse podacc1's collected records (context, not this finding's evidence)". F142 has no button. | Confirms O12 exactly. Not closable in Atlas Scope: it needs per-finding record pointers from the producer. |
| A2 | **UNPROVEN** | "Hop 1 of 1: core1 … ACL — THIS IS WHAT DECIDED THE HOP: PROTECT_SERVERS line 4 of 4". The depth ratchet asserts max depth `toBe(1)` and resolvedNextHops `toBe(0)`, and it passed. | No flow on the shipped snapshot takes a second hop. The criterion forbids grading a depth-1 capture PASS. |
| A3 | PASS | "denied at core1 by ACL PROTECT_SERVERS line 4 of 4 (acls.core1.PROTECT_SERVERS[3]: \"deny ip any any\"); the list is applied outbound on core1 Vlan30 (interfaces.core1.Vlan30)". | Upheld. The refuter found only two distinct denial deciders; the second, "INET_RETURN line 3 of 3", also names the device, ACL, line and text. |
| A4 | **FAIL** | Device, link, hop and finding re-aims all preserved scroll and camera (queue 5080 → 5080, row 102 in view). Counterexample: with GROUP set to "Device health band", F144 appears as row 92 (Poor) and row 167 (Critical). Clicking the visible row 167 at scrollTop 7879 jumped the queue to 4655, and focus went to row 92. Reproduced in the Browser pane: 8330 → 4666. | New; not in open-issues. R39 fixed the no-finding path; this is a different path. |
| A5 | PASS | Hover: pointer cursor, 4.22% pixel change against a 0.00% baseline. Select: `?d=core2`, 1 outline. Focus: `[328,280,412,325]`. "Reset view" restored `[447,82,503,111,760,888]` exactly. Trace marker on core1 `data-alarm=undetermined`, `undrawnHops []`. | Upheld: the refuter's re-run of `a56.mjs` reproduced it exactly. On real data the trace is a single-node verdict mark, not path geometry. |
| A6 | PASS | core1: "⚠ cut point" plus 9 hosts "⊘ STRANDED?" in the indeterminate token, never `--state-down`. The two measures' disagreement is surfaced ("THE TWO MEASURES DISAGREE"). Canvas pixel diff: core1 vs dist1 3.056%, core1 vs podacc1 2.807%; non-partitioning pairs 0.418–0.652%. | Upheld and widened: all 17 access switches carry "IMPACT DISPUTED"; bridges L18, L19 and L28 agree with `link_centrality`; both themes checked. |
| B1 | **FAIL** | First pass: all 26 devices × 6 tabs swept, 0 laundered zeros. Refutation: the Path panel renders `routes.core1[6]` as `"0 — a connected route's administrative distance by definition; the record carries no value"`. The Device pane Routing tab renders the same record as `"administrative distance: / not observed"`. Source: `"adminDistance":null`. | **Overturned PASS → FAIL.** R44 unified the HopList and the Inspector, but not the Device pane. |
| B2 | PASS | 25,536-trace sweep: `noScope=0, emptyCaveats=0`. All 5 suggested flows open with "Under the collected RIBs of core1 and core2 only (2 of 26 hosts in this topology)". | Upheld: the refuter's 68,600-trace sweep found 0 missing "2 of 26" and 0 empty caveat lists. |
| B3 | PASS | 3,072 no-RIB traversals, all `indeterminate`. `vitest` "Tests 93 passed (93)", exit 0. Mutating `engine.ts:2081` to `"delivered"` failed 2 tests. | Upheld: 9,912 dist1 hop-visits in the refuter's sweep, 0 violations. |
| B4 | PASS | 14 off-subnet sources × 116 flows = 1,624 traces, all `out-of-scope` with 0 hops. The claim reads "lies in no subnet this collection observed … no forwarding claim is made". | Upheld. The "lies in no subnet" sentence is not pinned by any test (mutating it left 430/430 green). The words half survives through other text: "no ingress device can be named", caveat 1 and the badge. |
| B5 | PASS | icmp vs `PROTECT_SERVERS[2]` "echo-reply" → indeterminate, "cannot model ACL match qualifier(s): icmp_type". `INET_RETURN[0]` "established" → indeterminate. Mutation (every line evaluable) failed 12+ tests. | Upheld with an adjacent defect: the not-applied-list caveat (`engine.ts:868-899`) says a TCP-only line "matches this flow" for udp/icmp flows, in 50 of 3,968 traces. New. |
| B6 | **FAIL** | First pass: 20 clicked citations, 0 unresolved; source sha256 `9580aa09…3089` recomputed. Refutation: `?l=L7` shows "Cutting it partitions yes / Betweenness 22.0000 / Pairs cut 22 / Centrality rank 4" with `secButtons = []`. The only reference, "Source record cable_map.cables[7]", is a non-button span, and that record holds none of those fields. `grep -c link_centrality src/data/fabric.json` → `0`. | **Overturned PASS → FAIL.** Affects all 25 links with centrality. The sample could only reach claims that already carried a citation. New. |
| B7 | PASS | Footer: "coverage 23/26 collected \| RIBs 2/26 (both shown incomplete) \| ACLs 1/26 \| centrality 25/44". Topmost via `elementFromPoint` at 1440, 390 and 1920, and with the Inspector open. | Upheld across 9 viewports × 4 surfaces (36 combinations). The Ctrl+K palette covers it at 390 while open (a transient modal). |
| B8 | **UNPROVEN** | 11,988 traces: decided refusals 0, `isDefiniteDelivery` 0, counterexamples 0. UI: "so no counterexample is offered. That is not proof that none exists". | Confirms O13. The positive state renders only under `vi.mock('./rib-completeness')`. |
| C1 | **UNPROVEN** | `review/blind/KEY.json`: 12 entries with no verdict, winner or critic field. 8 of 20 sheets are orphans. The `-craft` sheet still shows "Forward AI" and the Storylane modal. | Confirms O19; an owner decision. |
| C2 | PASS | `capture.mjs text`: "PASS text 72 of 72 states free of clipped/broken text … no form split by its scroll port". "PASS wrap 0 unjustified token-break licence(s)". "PASS selftest 23 of 23 detector cases". `capture.mjs app`: 32 of 32 frames at tier high. | Upheld on 4 viewed frames. Descender clipping is still undetectable (O17). |
| C3 | PASS | Release build, `?s=findings&sev=CH`: 6 fully visible rows at 1440, only F002 clamped ("…uplink to a sole…"); 10 rows at 1920, none clamped. Across 107 C+H rows, every clamped title keeps at least 0.75 of its height. | Upheld. Comfortable density only (O17). O24 is separate. |
| C4 | PASS | Two authored palettes: stage backdrop (7,10,15) dark vs (234,237,241) light. First-paint probe on the release build, OS light / no preference: boot bg `rgb(255,255,255)`; OS dark / no preference: `rgb(8,10,14)`. | Upheld. The dev-server residual reported in R40 was not measured. |
| C5 | **FAIL** | `node review/capture-motion.mjs` exit 3. (a) dark "high" reset-fly frame 59, actually rendered at LOW: 46,569 px changed with the camera still, consistent with `historyWeightFor` dropping 0.75 → 0 in one frame (`postfx.ts:188`). (b) light/high orbit frame 407: a 6.08× change at the balanced → low step-down; the overlay held opacity 1 for about 1,000 ms while 126 of 282 moving frames changed nothing. Z-fighting and sparkle PASS: flip px 0–37 against a 120 bar, 0 clusters. AO: 3 restores against a minimum of 4 (UNPROVEN). | Contended host (CPU 83–100%). Both pops are product behaviour under slow frames. The harness never fails on `tiersSeen`. New. |
| C6 | PASS | `transitionrun`: every event 80 ms or 140 ms; 0 CSS animations; `document.getAnimations()` empty after 3 s idle. Scene eases at most about 283 ms. Tier cross-fade 266.5–283.3 ms. | Upheld. `motion-inventory.test.ts:661` regressed to `/@keyframess+([w-]+)/g`, which is vacuous. The packet loop never runs on this data. The tier step-down hold has no §4.8 bound. |
| D1 | PASS | Tab cycles close with no trap in 6 states at 1440 and at 390 and 768; 0 unreachable controls. A1 (F099 → "access13 Gi0/11 (err-disabled)") and A2 ("Hop 1 of 1: core1 denied by ACL PROTECT_SERVERS…") done by keyboard only. | Upheld: every element with a pointer handler is focusable or inside a composite. |
| D2 | PASS | `role=grid`, `aria-rowcount=171` = 171 DOM rows. Arrows, Home/End, PageUp/Down, Ctrl+Home/End, sort and group collapse (171 → 168) verified. "exactly one tabindex=0 exists in the grid, and it is the focused element". | Upheld at 1440 and 390. |
| D3 | **FAIL** | First pass: `audit-d3-focus.mjs` 964 PASS / 0 FAIL, focus return 11/11. Refutation, reached by real Tab presses: `reached "Remove the Critical severity filter" after 7 Tabs (focus-visible=true)` / `after Enter + 2.5s: {"tag":"BODY","isBody":true,"fv":false}` / `elements matching :focus/:focus-visible: 0`. The same happened for "Clear scope", "Deselect device core1" and "Stop investigating the flow …". | **Overturned PASS → FAIL.** A control that removes itself drops focus. New. |
| D4 | PASS | Rendered-pixel contrast, both themes, 12 states: minimum 4.60 light / 4.71 dark (`span.pq-meta` "Compound risk"). Canvas labels ≥ 6.42. Non-text boundaries ≥ 3.48. | Upheld: placeholders ≥ 5.05, the pinned Fabric list's 170 texts ≥ 5.0. |
| D5 | PASS | Minima: theme options 24.0×24.0, sort buttons 24×24, Inspector divider 760×24 (was 8 px at `1d19e22`), path splitter 339×24. The three sub-24 cases are inside larger operable targets or a screen-reader-only tree. | Upheld at 1440, 768 and 390. |
| D6 | PASS | `scene.pick()` sweep: 26 devices and 44 links pickable, equal to `fabric.json`. The Fabric list has 119 treeitems (5 tiers, 26 devices, 88 link items). Enter selects 26/26 devices and 88/88 links. | Upheld. |
| D7 | PASS | `capture.mjs reduced`: "PASS D7: camera lands in one frame under reduce, 24 poses without it." Under reduce, 0 transitions above 1.5 ms. | Upheld: the re-run gave `cameraPoses=1` vs 23, and 0 animations above 1.5 ms. The packet half is fixture-only. |
| D8 | PASS | Greyscale 03/06 in both themes: severity letters (C/H/M/L/I), band letters (C, P, G*, E*, ?), "? UNDECIDED" wording, dashed cables, "✕ blocked / ? undecided / ✓ delivered here / ⚠ cut point". | Upheld. |
| E1 | **UNPROVEN** | First pass: design-brief §8.1–8.2 names the five journeys; `measure-inp` "acts with a verified effect 25 of 25" for J1–J4 and J3b. Refutation: `audit-e5-sweep.mjs:5` "drives the interactions the journeys do NOT cover" runs `"path trace: swap + submit"` (`:362`) with the same URL and `.pt-form__swap` selector as `measure-inp.mjs:684` J4. `acceptance.md` then lists swap+submit, palette open and the first finding selection as "outside the five declared journeys". | **Overturned PASS → UNPROVEN.** The declaration cannot say whether J4's own action is in scope. |
| E2 | **UNPROVEN** | 3 × `measure-inp`, p95 (LABORATORY): J1 40/72/40, J2 104/144/176, J3 80/128/184, J3b 64/64/48, J4 80/160/NOT MEASURED, J5 80/80/80 ms. Every run printed "NOT ACCEPTANCE EVIDENCE — host was 47%/58%/53% busy … (bar 25%)". | Every measured p95 was ≤ 200 ms even on this host, but none of it is acceptance evidence. Confirms O25. |
| E3 | **UNPROVEN** | "E3 across runs of build c88fe27230004123 (0 run(s), need 3): INSUFFICIENT RUNS … 6 busy run(s) of this build excluded". J5 violated in 3 of 3 runs (worst 94 ms, `#document.onkeydown @ mount-CEm90sv4.js … forced layout 41ms`). J2-first was E3-clean in all 3 runs. | Leans FAIL on J5-open-palette. It needs 3 quiet on-AC runs. |
| E4 | **UNPROVEN** | "FAIL E4 focus flights: median 48 fps across 10 windows … worst window 42.54fps (floor 45)"; the second run gave a 49.28 median. Both had `acceptanceEvidence=false` (host 48–49% busy). The degradation is explicit: "fabric tier high below frame-rate bar refining". | Not acceptance evidence either way. The "trace animating" condition is unreachable on this snapshot. |
| E5 | **UNPROVEN** | Cold load: "FAIL E5 4 animation frame(s) over 200 ms with NOTHING on screen … (worst 393.1 ms …) [NOT ACCEPTANCE EVIDENCE]", host 55% busy. Sweep: "NOT MEASURED E5 sweep 1 action(s) could not be actuated (path trace: swap + submit)". | The sweep's ~1,000 ms, 0 ms-blocking rows match the window-not-presenting signature. The pre-FCP carve-out is still unsanctioned (O20). |
| F1 | PASS | `tsc -p tsconfig.json --noEmit` exit 0; `tsconfig.scripts.json --noImplicitAny` exit 0; `tsconfig.config.json` exit 0. No `@ts-ignore`, `@ts-nocheck` or `@ts-expect-error`. | Upheld: `npm run typecheck` exit 0, no tracked file outside a project except `review/*.mjs` (O27). |
| F2 | **UNPROVEN** | First pass: "Test Files 128 passed (128) / Tests 1714 passed (1714)". Refutation, same HEAD: "Tests 3 failed \| 1711 passed (1714)". `CommandPalette.test.tsx:717` "expected 533.2958999999992 to be less than 400". The two EvidencePane real-data tests timed out at 30,472 and 33,534 ms. A second run: 1714/1714, exit 0. | **Overturned PASS → UNPROVEN.** `vitest.config.ts:17`'s premise ("slowest solo: 2 266 ms") is false: 13.5 s and 15.7 s even on the green run. |
| F3 | **UNPROVEN** | `mutation-check.mjs`: 18 of 18 KILLED, exit 0. History: `254694b` provenance tests "14 failed" (for example "expected undefined to be lf-normalised"), then green at `1d19e22`. | Red-before-fix for the other five engines rests on today's-code mutations ("this does NOT recreate pre-fix history"). §6 lacks its "not examined" record. |
| F4 | PASS | `npm run build` exit 0. `three-Dyx6ntnn.js 828.00 kB`; `WebGLRenderer` 38× in three, 0× in index, mount or Fabric3D. The entry reaches mount only through `import()`. | Upheld: same chunk hashes, and three appears only in mount's dynamic-import mapDeps. `acceptance.md`'s "only the preload helper" is false: mount imports 4 bindings. |
| F5 | PASS | `compile-snapshot.mjs`: "sha256(source, lf-normalised) = 9580aa09…3089 (3072771 bytes)". `fabric.json` `2f558c38…a308` before and after. Mutating the input changed the output. | Upheld and gap closed: a real `git clone` under autocrlf=true reproduced all four outputs byte-identically. |
| F6 | PASS | "verdict: F6 PASS: 32 of 32 frames byte-identical across 5 runs." 224 frames hashed by the grader, one sha per name. | Upheld: `twice 3` on a private :4263 build, "32 of 32 frames byte-identical across 3 runs". On the dev server, 31 of 32 matched (1 frame failed to load on `ERR_NETWORK_CHANGED`). |

## What is proven

Every criterion here was graded PASS by the first pass and then survived an independent refuter.

- **A3.** Grader: the live Path UI names core1, PROTECT_SERVERS, "line 4 of 4" and the literal "deny ip any any". The refuter found only two denial deciders in the whole engine sweep, confirmed the second (INET_RETURN line 3 of 3) in the live UI, and found no flow reaching an implicit deny that has no text.
- **A5.** Grader: Playwright measurement of hover (4.22% pixel change vs 0.00% baseline), select, double-click focus, exact reset and the trace marker. The refuter re-ran `a56.mjs` to a separate directory and reproduced every coordinate.
- **A6.** Grader: canvas-only pixel diffs (cut point 4.7× the no-partition noise) and the disputed-impact surfacing. Refuter: all 17 access switches, bridges L18, L19 and L28, and both themes use the indeterminate token, never `--state-down`.
- **B2 and B3.** Grader sweep of 25,536 traces and the 93-test engine run, with mutation red-before-fix. Refuter sweep of 68,600 traces: 0 missing scope phrases, 0 empty caveats, and 9,912 no-RIB hop-visits all indeterminate.
- **B4.** 1,624 off-subnet traces, all `out-of-scope`. The refuter confirmed the "says so in words" half holds through the claim's other sentences and the badge, even though the specific sentence is unpinned.
- **B5.** Direct `evaluateAcls` on real lines, a 12-test mutation kill, and the live UI (`?s=path&d=core1&flow=10.0.10.7>10.0.30.2>icmp>`). It is upheld on the literal criterion. The adjacent defect is listed below.
- **B7.** Grader at 1440, 390 and 1920. Refuter across 9 viewports × 4 surfaces, all topmost and unclipped.
- **C2, C3 and C4.** Grader: the `capture.mjs text` and `app` gates, DOM clamp probes and a first-paint probe across 6 scheme × preference combinations on the release build. Refuter: viewed 4 captures; none showed placeholder content, and palettes are separately toned.
- **C6.** Grader: runtime `transitionrun` probe (80 or 140 ms only), canvas-pixel ease timing (≤ about 283 ms), and 22 tier fades of 266.5–283.3 ms. Refuter: a source sweep found no `@keyframes` anywhere and only 80, 140, 240 and 620 ms tokens. The only loop over 300 ms is the bounded packet loop.
- **D1, D2, D4, D5, D6 and D7.** Grader: keyboard-only A1 and A2 flows, the grid key matrix, rendered-pixel contrast, a `getBoundingClientRect` target sweep, pick-vs-tree parity and the reduced-motion gate. Refuter: a pointer-handler inventory, grid keys at 390, placeholder and Fabric-list contrast, a 3-width target sweep, and a `capture.mjs reduced` re-run (`cameraPoses=1` vs 23).
- **D8.** Greyscale captures of 03 and 06 in both themes. The refuter independently found no information carried by colour alone.
- **F1.** Three `tsc` projects, exit 0, reproduced with `npm run typecheck`.
- **F4.** The chunk graph was read from the emitted files. The refuter's own build gave the same hashes and the same split.
- **F5.** Byte-identical compilation from `git archive HEAD`, then from a real `git clone` under autocrlf=true. The source digest `9580aa09…3089` equals the parent blob `1ed99404`.
- **F6.** `twice 5` plus two `app` runs, 224 frames, one sha per name. The refuter's `twice 3` ran on a separate private build.

## What is not

### FAIL

- **A1.** "Any finding" holds for 12 of 146. 133 findings reach only context that the app itself labels "not this finding's evidence", and F142 reaches nothing. This needs per-finding record pointers from the parent engine (O12) and cannot be fixed inside Atlas Scope.
- **A4.** When a finding is listed under two groups (any multi-valued group key: band, host or role), clicking the visible copy moves the queue to the first copy: 7879 → 4655 here, 8330 → 4666 in the Browser pane. The clicked row ends up out of the viewport, and focus goes to the other copy. `PriorityQueue.test.tsx` and `PriorityQueue.a4-scroll.test.tsx` do not cover it. Only band grouping was run; host and role are inferred from the code comment "lists one item under every group".
- **B1 (overturned).** The null `adminDistance` of `routes.core1[6]` renders as "0 — … by definition" on the Path panel (from `claims.ts:709` `notApplicableReason`) and as "not observed" on the Device pane's Routing tab. The criterion allows no inference exemption, and the product's two readings of one null show that the value is not settled. `HopList.tsx:419`'s "cannot disagree about any field" covers only the HopList and the Inspector.
- **B6 (overturned).** On the link inspector, "Cutting it partitions", "Betweenness", "Pairs cut" and "Centrality rank" have no citation. The values come from `link_centrality[i]`, which the compiler reads (`tools/compile-snapshot.mjs:166`) but never cites. The pane's only reference, `cable_map.cables[7]`, is plain text and does not contain those fields. `DevicePane.tsx:1857-1870` builds these Kv rows without `cite`. This affects all 25 links that have centrality. The refuter did not check whether other rows have the same gap, such as the Identity rows (Model, Serial, Software).
- **C5.** "LOD / effect / label popping" fails for two reasons. (a) The history blend switches off in one frame when the camera stops after a slow frame (0.465 px → 0 px after a 166.6 ms gap), contradicting the comment that switching it "is never itself a visible step". (b) An automatic tier step-down mid-orbit holds a frozen overlay for about 1,000 ms (700 ms at high → balanced), so the orbit visibly stops. AO drop/restore (3 of the 4 required restores) and the tier cross-fade (22 of 24 established) are UNPROVEN. Only one motion sequence ran wholly at high. **Harness defect:** `capture-motion.mjs` records `tiersSeen` (line 828) but no verdict uses it, and it checks the tier only at leg start (line 1112). A "high" leg that ran at low reports `legProblems []`.
- **D3 (overturned).** "Remove the Critical severity filter", "Remove the High severity filter", "Clear scope", "Deselect device core1" and "Stop investigating the flow …" each leave `document.activeElement` on `<body>` with 0 elements matching `:focus` or `:focus-visible`. Screenshot `focuslost-s_findings_s-1440.png` shows no ring anywhere. The first-pass audit traced only surfaces that open and close. Not checked: 390 and 768 px, and the Inspector and evidence panes.

### UNPROVEN

- **A2.** Maximum depth on the shipped data is 1, with 0 resolved next hops. None of these has run on real data: the second hop's decider, hop-to-hop navigation, `resolveNextHost`'s cable-map branch, the TTL cut and the loop detector. `multihop.test.tsx` is a one-line fixture mutation.
- **B8.** No flow is a decided denial and none is a definite delivery (11,988 traces). The positive counterexample has rendered only under mocked RIB completeness (O13).
- **C1.** No blind verdict exists. The references identify themselves ("Forward AI", the Storylane modal), and `REFERENCES.md` withdraws the R1–R3 win tables. This is an owner decision (O19).
- **E1 (overturned).** The five journeys are named, but whether J4's swap+submit is inside the journey is contradicted three ways: `measure-inp.mjs` (J4), `audit-e5-sweep.mjs` ("NOT cover") and `acceptance.md` ("outside the five declared journeys"). `acceptance.md` also says the first finding selection is "now inside J1 itself" in the same paragraph that lists it as outside. The only guard, `Fabric3D.test.tsx:1741`, checks that the five ids exist. A second refuter confirmed the list exists and that the journeys actuate (25/25; J5 mounted its dialog 25 of 25). That does not resolve the scope contradiction.
- **E2.** No acceptance-grade run: the host was on AC and presenting at 60 Hz, with 47–58% excess load against a 25% bar. The `1d19e22` figures (J1 32 … J5 32 ms) are history, not evidence for `443a05a`.
- **E3.** INSUFFICIENT RUNS: 0 quiet runs of the 3 needed. It leans FAIL. J5-open-palette violated in 3 of 3 of these runs and in 5 of the 6 records for this build in `review/reports/inp-e3-history/`. J3b violated in 2 of 3.
- **E4.** No acceptance-grade run. On the contended host the fabric did not hold 55 fps: flight medians 48 and 49.28, orbit medians 52.24 and 49.53, and the tier stepped to low. The degradation was stated on screen. The earlier AC 60 fps run cited in O25 can no longer be re-checked, because `review/reports/fps.json` has been overwritten.
- **E5.** No acceptance-grade run. The cold-load FAIL (worst 393.1 ms pre-FCP, judged because the carve-out is unsanctioned) is laboratory only. The sweep could not actuate path-trace swap+submit, and it does not separate a window that stopped presenting from main-thread work.
- **F2 (overturned).** One green `vitest` run is a measurement of host load. Under load: CommandPalette's worst-of-N bound failed (533 ms against 400), and two real-data EvidencePane tests hit the 30 s `testTimeout` while not hung (they take 13.5 s and 15.7 s even when green). Also found:
  - `acceptance.md`'s "roughly a fifth" of test files reading source is now about 30% (39 of 128).
  - Six weak-assertion tests were never read.
  - `env.test.ts` cites `review/_repair_r3d_corners.mjs`, which now exists only as the gitignored `review/_scratch/` copy.
- **F3.** Historical red-before-fix is proven only for the O15 provenance tests (`254694b` → `1d19e22`). For the forwarding, blast, layout, query, compiler and claims engines, it rests on today's-code mutations and refuter prose. `refutation.md` §6 (claims) has no "what was NOT examined" record, although `acceptance.md` says each section has one. §7 leaves the compiler unrefuted for fields it transforms. `acceptance.md`'s "16 of 16" is stale: the run now executes 18.

## What was not examined

Collected from each grader's and refuter's own statements.

**Environment and scope**

- A, B and D ran only against the :4180 dev server, not the shipped bundle. D's headless Chromium rendered the fabric at tier "low" (SwiftShader).
- No criterion in A–E was re-graded from a clean clone of `443a05a`. Only F5 was run from a real clone. F1, F2 and F4 ran in the working checkout (src and tools identical to HEAD).
- The host was shared with concurrent graders and the user's own applications throughout. CPU was 83–100% during C. The :4180 dev server (pid 8692) used about 1.5 cores continuously, and nobody investigated why.
- There was no screen reader, no forced-colours mode, no macOS key mapping, and no human keyboard user.
- One host only (Intel iGPU, ANGLE D3D11, 60 Hz). No field INP data exists.
- The shared Browser pane was taken over mid-run by another agent. The A grader's JavaScript ran once on that agent's tab, and its coordinate mapping broke. All A measurements after that point are from private Playwright contexts.

**Group A**

- No link cut that actually strands something was examined.
- The keyboard routes to A5's focus and reset were not run.
- A4 re-aiming was not tested from evidence-chain device chips, the Fabric list tree or palette device entries.
- The duplicate-row jump was not run under host or role grouping.
- Dark theme and viewports other than 1920×1080 were not run.

**Group B**

- The canvas pixel encoding of unmodelled hops, uncollected devices and null-bridge links was not checked.
- EvidencePane rendering was not checked across all 146 findings. The Cross-layer table was not checked.
- Themes were not checked.
- Red-before-fix was shown by mutation, not history.
- B1 surfaces other than routing, ports and summary were not checked on dist1, dist2, core1, core2 and access1.
- The stale-card lead (`PathTrace.tsx:1090`) was not reproduced through a real Back press.
- For B6, rows other than centrality were not enumerated for missing citations.
- The unresolvable-object-group fallback was not exercised through a constructed flow.

**Group C**

- No new blind panel was run.
- Not all 32 captures were viewed at full resolution: the grader viewed 5 plus contact sheets, the refuter 4.
- 390 and 768 px were covered only by `capture.mjs text`, and descenders have no detector.
- Compact density was not graded.
- The dev-server boot residual and contrast beyond the text harness were not checked.
- C5 had no quiet-host, tier-held re-run, and high tier was established for only 1–2 sequences.
- For C6, the packet loop, trace draw-on, drawer, switch and disclosure transitions were not fired at runtime, and reduced motion was not tried.

**Group D**

- D4 was measured at 1440×900 only. Pressed, dragging and node-hover states were not measured, nor were canvas-drawn rings against the canvas.
- The palette input draws no border of its own (1.0:1 on 3 of 4 sides). It was not counted as a failure because of its 2988 px focus ring.
- The project D3 audit was killed by the grader's 1500 s timeout during its 1000×800 pass: `EXIT=124`, 176 compact cases, all PASS.
- D3 focus loss was not checked at 390 or 768 px, or in the Inspector and evidence panes.
- `reduced-motion.test.ts` was not re-examined by the refuter.
- D8 was not converted to greyscale by the refuter, and was not checked at 390 or 768 px.

**Group E**

- There was no quiet-host run. `ATLAS_FULLBLEED=1`, the headless floor lane and field INP were not run.
- The one-off "J2 anchors …: none" failure was not root-caused. `discoverJ2Anchors` swallows `beforeClick` errors with `.catch(() => null)` and logs nothing.
- The design-brief §8.2 "how it stays under budget" claims were not probed.

**Group F**

- 6 of 11 weak-assertion tests were not read.
- The 39 source-text tests were classified by grep, not read.
- Historical red-before-fix was checked only for O15.
- `fabric-preview.html` and `window.__atlasScene` were not opened.
- The F grader did not build into the repository's own `dist/`. The in-repo `dist/` was rewritten at 10:46 by someone else.
- The <768 px network log for F4 was not re-measured.
- F2's flake rate was not measured beyond two full runs.

**Side effects the graders disclosed**

- The C grader's `capture-motion` run overwrote the ignored `review/shots/motion/` tree and `report.json`, the 06:17Z report that O16 cites. A backup is at the session scratchpad `motion-report-prior-0917.json`.
- The E grader overwrote the ignored `review/reports/inp.json` and `fps.json`. The latter held the O25 AC run.
- The D grader set and removed three `atlas-scope.*` localStorage keys in the shared Browser pane. It did not restore a pre-existing theme value it never read.
- The E grader stopped 4 leftover `vite preview` processes, and an E refuter stopped 2 more (ports including 4263).
- No grader or refuter edited product source or ran a git write in the project repository.

## Known issues carried forward

This section reconciles the grades against `docs/open-issues.md` as it stands in the working tree,
including the parallel session's uncommitted edit. This report does not edit that file. The entries
marked **new** and the status changes below should be recorded there.

**Confirmed still open by this grading**

- **O12 (A1):** 6/6/133/1 confirmed exactly. Still not closable in Atlas Scope.
- **O13 (B8):** 0 decided refusals and 0 definite deliveries in 11,988 traces.
- **O19 (C1):** `KEY.json` has 12 entries and no verdicts; 8 of 20 sheets are orphans.
- **O25 (E1–E5 not re-established at `443a05a`):** confirmed. Every E run was withheld at 46–59% host load.
- **O26 (wall-clock tripwires):** confirmed by the F2 overturn. `CommandPalette.test.tsx:717` measured 533 ms against 400.
- **O27 (`review/*.mjs` untyped):** unchanged.
- **O28 (palette keystroke race):** not fixed. The census typed after a 250 ms settle to avoid it.
- **O17:** compact density and descender clipping are still uncovered. 768 px was not re-measured.
- **O24:** cited by the C grader as still open; not re-measured.
- **O22 (determinism keyed on names):** F6 passes; the shape is unchanged.
- **O20:** the pre-FCP carve-out is still unsanctioned; E5 is not re-established.

**Status changes**

- **O16:** at `443a05a`, the edge-shimmer and z-fighting items now **PASS in a laboratory run** (flip px 0–37 against 120, 0 clusters). That run was on a contended host, not tier-held, with high tier covering only 1–2 sequences. C5 still FAILS, now on popping: the history blend's one-frame switch-off and the step-down freeze. The report that O16's "9–35 px" figure cites was overwritten (see side effects).
- **O18 / R49 ("keyframe scanner proven live"):** contradicted. `motion-inventory.test.ts:661` is `/@keyframess+([w-]+)/g`, which returns `[]` against the planted `@keyframes stage-pending-spin`. `1d19e22` had `/@keyframes\s+([\w-]+)/g`. It hides nothing today, because src has no keyframes.
- **R44:** partial. The HopList and the Inspector agree, but the Device pane's Routing tab still says "not observed" for the same null (B1 FAIL).
- **R39:** holds for the no-finding path. A4 fails on the duplicate-row path instead.
- **R51:** J2-first was E3-clean in all 3 runs, but that is laboratory only.
- **O21:** its classification is what the E1 overturn contradicts. Swap+submit is J4's own action.
- **O23:** closed for F5, which a real `git clone` of `443a05a` reproduced. It is still open for A–E. F1, F2 and F4 ran in the checkout, not a clone.
- **O9:** unchanged, and consistent with B6's first-pass evidence. The B6 FAIL is a different gap: claims with no citation at all.

**Not examined by anyone in this grading; carried as they stand**

- O6 (bloom halos at `high`)
- O7 (SCOPED badge; premise found false 2026-09-21)
- O8 (ignore-ACLs counterfactual not built)
- O11 (owner decision on an earlier refused hop)
- O14 (`failureImpact().engine.record` aliases the snapshot)

**New: not in `docs/open-issues.md`**

1. **A4:** a finding listed under several groups sends the queue to its first copy when a visible copy is clicked (7879 → 4655).
2. **B1:** the Path panel and the Device pane disagree on a null `adminDistance` ("0 — by definition" vs "not observed").
3. **B6:** link centrality values (`link_centrality[i]`) are shown with no citation. The compiler emits no `link_centrality` cite, and `DevicePane.tsx:1857-1870` sets no `cite` on those rows.
4. **D3:** five self-removing controls drop focus to `<body>`: two severity-chip removes, "Clear scope", "Deselect device", and "Stop investigating the flow".
5. **B5-adjacent:** the not-applied-ACL caveat (`engine.ts:868-899`) matches lines by address only and ignores protocol, so it states a TCP-only line "matches this flow" for udp/icmp flows (50 of 3,968 traces).
6. **B4:** the "lies in no subnet this collection observed" sentence is not pinned by any test.
7. **C5:** (a) the history blend drops 0.75 → 0 in one frame when the camera stops after a slow frame; (b) the automatic step-down holds a frozen frame for 700–1,000 ms mid-orbit, and §4.8 gives no bound for that hold; (c) harness: `capture-motion.mjs` never fails a leg on `tiersSeen`.
8. **C6:** the vacuous keyframe regex at `motion-inventory.test.ts:661`.
9. **E1:** the journey declaration, `audit-e5-sweep.mjs` and `acceptance.md` disagree on whether swap+submit, palette open and the first finding selection are inside the journeys.
10. **F2:**
    - `vitest.config.ts:17`'s "slowest solo: 2 266 ms" is false (13.5 s and 15.7 s), so a 30 s timeout is not evidence of a hang.
    - The "roughly a fifth" classification in `acceptance.md` is stale (about 30%).
    - `env.test.ts` cites a provenance script that now exists only under the ignored `review/_scratch/`.
11. **F3 / F4 documentation drift:**
    - `refutation.md` §6 lacks its "not examined" record.
    - `acceptance.md` still says "16 of 16"; the run is now 18.
    - `acceptance.md` F4's "mount's only import from the entry is that preload helper" is false: mount imports 4 bindings, 3 of them the theme-preference functions.
12. **E harness:**
    - `discoverJ2Anchors` swallows errors and logs no reason for "anchors: none".
    - `measure-inp.mjs` cites a nonexistent `src/fabric3d/measure-inp.harness.test.ts`.
    - `verdictOf` counts a NOT MEASURED run as not clean (a conservative error).
    - `audit-e5-sweep.mjs` does not separate window-not-presenting from main-thread LoAFs.
13. **Leads, unconfirmed or cosmetic:**
    - The hidden-tab stale PARTIAL card under a refused shared link (`PathTrace.tsx:1090`).
    - A missing period on uncollected devices' Routing tab ("No routing table was collected for AP-floor1 2 of 26 hosts have one").
    - Ctrl+K's palette covers the B7 coverage group at 390 px while it is open.
