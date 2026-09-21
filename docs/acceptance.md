# Atlas Scope — Acceptance Criteria

The exit condition for the build loop. Every criterion is checkable by someone who did not write
the code. A criterion is met only when its **evidence** column can be produced on demand.

Grading vocabulary: **PASS** (evidence produced), **FAIL** (evidence contradicts), **UNPROVEN**
(no evidence either way — counts as FAIL for release purposes, because an unexercised gate is not
a gate).

---

## A. Investigation capability — the Forward / IP Fabric bar

| # | Criterion | Evidence |
|---|---|---|
| A1 | From the priority queue, a user reaches the configuration evidence behind any finding in **≤ 3 interactions**, without the topology resetting. **Read "the configuration evidence behind a finding" literally: for 6 of 146 findings it is configuration the finding NAMES, and for the other 140 it is the nearest record this snapshot holds for the hosts the finding names, labelled as such in the pane.** All 6 named resolutions go through the interface branch; no finding in this data names a collected ACL or a routed prefix, so those two branches are covered by `src/panels/EvidencePane.namedconfig.test.ts` against the real records rather than by the app's own corpus. | Screen recording or an ordered screenshot sequence of the states, at a declared viewport, **with no scrolling between the interactions counted**. Plus the 6/146 ratio, which `EvidencePane.namedconfig.test.ts` re-measures from the data on every run. |
| A2 | A path question (`src`, `dst`, `proto`, `port`) returns a **hop-by-hop** result naming, for each hop, the host, egress interface, next hop, and the **route or ACL line that decided it** with its snapshot citation. **Graded at depth 1 only.** No flow reachable in this snapshot takes a second hop — core1's only non-connected routes point at 10.0.10.254 and 10.0.30.254, which are not collected hosts, and core2 has no default route — so the multi-hop half (a second hop's decider, hop-to-hop navigation, `resolveNextHost`'s cable-map branch, the TTL cut and the loop detector) does not execute on the shipped data. It is **UNPROVEN in the product** and must not be graded PASS from a depth-1 capture. | A trace result rendered with citations visible, **plus the measured hop-depth distribution** (`engine.test.ts`'s depth ratchet). Multi-hop rendering is evidenced only by `src/forwarding/multihop.test.tsx`, which drives the real engine over a one-line mutation of the real compiled data; that is a fixture, and the criterion says so rather than borrowing its result. |
| A3 | For a **blocked** flow, the UI names the exact blocking device, ACL name, line index, and the literal configuration text of the line. | The `06-path-blocked` capture. |
| A4 | Selecting a finding, a device, a link or a hop **re-aims** every other surface; no surface blanks or loses its scroll/selection context. Re-aiming the priority queue means the selected row is **scrolled into view**, not merely marked — a `data-active` row 6,171 px below the fold is not a re-aimed surface. A device or link selection marks the rows naming it and states the count in words; it never narrows the corpus. **The evidence tab is deliberately re-aimed, not preserved:** selecting a finding while the Device pane is on `acl` switches Rail B to `findings`, because the tab that can render the newly selected record is the re-aiming this criterion asks for. Scroll position, camera, flow and batch are all preserved across that change. | Before/after captures of all four surfaces on one selection change, **plus the queue's `scrollTop` and the active row's in-view state** before and after a selection made from another surface. Regression tests: `PriorityQueue.test.tsx` → "a selection from another surface is revealed, not merely marked". |
| A5 | The 3-D fabric supports selection, hover, focus-to-device and reset, and a trace is drawn **on** the fabric, not in a separate picture. | Captures `01`, `02`, `06`. |
| A6 | Blast radius: selecting a device or link shows what becomes unreachable **on the fabric as well as in the Inspector**, cross-checked against the snapshot's own `failure_impact` / `link_centrality`, with any **disagreement surfaced** rather than hidden. The stranded hosts are lifted out of the dimmed field and carry a `stranded` mark; the selection carries a `cut point` mark — which is a conditional, and so is never drawn in the down colour or given the trace's alarm word. | Capture plus the disagreement list, **plus a pixel diff of the canvas between an articulation point and a device that partitions nothing**, which must exceed the diff between two devices that both partition nothing. Regression tests: `Fabric3D.test.tsx` → "the blast radius reaches the fabric". |

## B. Claim honesty — the Batfish bar, and this repository's doctrine

| # | Criterion | Evidence |
|---|---|---|
| B1 | No surface renders a `null`/absent value as a healthy, passing, or zero state. | Adversarial sweep report: every place a null reaches a renderer, and what it renders as. |
| B2 | Every forwarding verdict carries a one-sentence **scope claim** and a **non-empty caveat list**. The scope names that RIBs exist for only 2 of 26 hosts. | `traceFlow` output for every `suggestedFlows()` entry. |
| B3 | A trace that traverses a host with no RIB returns **indeterminate**, never *delivered*. | Unit test, run output pasted. |
| B4 | A trace whose source IP is in no observed subnet returns **out-of-scope**, and says so in words. | Unit test, run output pasted. |
| B5 | An ACL match preceded by an **unevaluable** line (established / icmp-type / object-group) is reported as indeterminate, naming the line that blocked evaluation. | Unit test against the real `INET_RETURN` / `PROTECT_SERVERS` data. |
| B6 | Every displayed claim resolves to a citation, and the Inspector shows **the record that carries it, with the source file and sha named**. Where the citation is itself a model path the parsed record is shown directly; where it names a record in the source snapshot — which is not bundled with this build — the Inspector shows the compiled record carrying the citation and says so in those words, naming the source file on the Provenance tab. It must never present a projection as the source bytes. | Click-through on 10 randomly chosen claims; count of unresolvable citations must be 0, and every non-model-path resolution must state which of the two it is. |
| B7 | Coverage is stated permanently and visibly: how many hosts were collected, how many have RIBs, how many have ACLs. | Status bar capture. |
| B8 | A counterexample is offered where one exists (a denied flow shows the nearest flow that would succeed). | Capture of the affordance. |

## C. Craft — the Linear / AAA bar

| # | Criterion | Evidence |
|---|---|---|
| C1 | A harsh independent critic, shown our capture and a reference capture **blind and side by side**, picks ours or calls it a genuine tie — for each of: overall composition, information density, typographic craft, colour discipline, and the 3-D render. | Blind panel verdicts, ≥ 2 independent critics per pairing. |
| C2 | Zero placeholder, lorem, TODO, or obviously-unfinished UI in any captured state. | Sweep of all captures. |
| C3 | Dense views carry real information at real density — a findings row shows severity, id, title, device, category without truncating the title to uselessness. | `03` capture at both viewports. |
| C4 | Both dark and light themes are complete and deliberate — not one theme with inverted colours. | Side-by-side of all 7 states in both themes. |
| C5 | The 3-D view is free of the named cheap-render tells: aliased edges, unlit flat geometry, uniform ambient light, z-fighting, 1px hairline links, default `0x000000` background, visible banding, popping LOD. | Critic checklist against the capture, item by item. |
| C6 | Motion is purposeful and under 300 ms except deliberate camera moves; nothing loops or pulses without a reason. | Motion inventory listing every animation, its duration, and its justification. |

## D. Accessibility — WCAG 2.2 AA floor

| # | Criterion | Evidence |
|---|---|---|
| D1 | Every interactive control is reachable and operable by keyboard alone; the full investigation flows A1 and A2 are completable without a mouse. | Keyboard-only walkthrough transcript. |
| D2 | The findings table implements the **APG grid** keyboard contract: arrows, Home/End, Ctrl+Home/End, PageUp/Down, and correct `role`/`aria-*`. | Key-by-key test report against the APG example. |
| D3 | Focus is always visible, never trapped except in an intentional modal, and returns to the invoking element on close. | Focus-order trace for the palette and any dialog. |
| D4 | Text contrast ≥ 4.5:1, non-text UI and state indicators ≥ 3:1, in **both** themes. Measured, not asserted. | Computed contrast table for every token pairing in use. |
| D5 | Interactive targets ≥ 24×24 CSS px, or exempt with the reason stated. | Measured list of every control under 24px. |
| D6 | The 3-D canvas has a non-canvas equivalent: everything selectable in 3-D is selectable and readable from the DOM. | Screen-reader-visible tree of the fabric. |
| D7 | `prefers-reduced-motion` removes camera tweens, packet animation and transitions — and the app remains fully usable. | `node review/capture.mjs reduced` — forces the media feature through the browser context (the `app` pass cannot: it pins `no-preference` and freezes animation itself), measures the camera against a `no-preference` control, and exits non-zero if the reduced run animates or the control does not. Plus `src/fabric3d/reduced-motion.test.ts`, which drives the WebGL branches (`camera.moveTo` immediate, `flow` packet never started) with a control for each. **The packet half is fixture-driven, and that is not coverage over shipped behaviour:** every trace in the real compiled snapshot is single-hop, so the packet never starts on real data regardless of the motion preference, and the reduced/control pair either side uses a synthetic multi-hop fixture. The test says so in its own name and pins it with `expect(real.hops.length).toBe(1)`, which will fail the day the snapshot grows a second RIB — a tripwire, not a claim. Reading the `@media` blocks is NOT evidence: it covers only the half that cannot silently break. |
| D8 | No information is conveyed by colour alone (severity carries a shape/label too). | Greyscale capture of states `03` and `06`. |

## E. Responsiveness — the INP bar

| # | Criterion | Evidence |
|---|---|---|
| E1 | Declared representative journeys: (1) select a finding, (2) select a device in 3-D, (3) type in the query bar, (4) run a path trace, (5) open the command palette. | Named list with what each does. |
| E2 | Each journey's **laboratory** INP ≤ 200 ms at the 95th percentile over ≥ 20 repetitions, measured with the Event Timing API on the real build. Labelled as laboratory, not field. | Measurement script + its raw output. |
| E3 | No single task exceeds 50 ms on the interaction path; long work is chunked, yielded, or moved off the input handler. | `node review/measure-inp.mjs` — its **E3 verdict**, which is a second axis and is printed and exited on separately from the INP verdict (`longTasksOver50OnPath` per journey). A green INP run is not E3 evidence: measured 2026-09-21, J2 passed the 200 ms bar with twelve tasks over 50 ms on its own interaction path. |
| E4 | The fabric holds ≥ 55 fps **while it is actually rendering**, with the full 26-node fabric, on the reference machine; degradation is explicit (quality tier), never silent. The render condition must be **named and established**, not assumed — see the note below. | `node review/measure-fps.mjs`: frame-time series gated on `stats().converged === false` for the sample, the render condition it used, the quality tier in force, and the canvas dimensions the figure was taken at. Exit 0 only on a genuine sample that held the bar. |
| E5 | Work that is genuinely slow is **budgeted separately** and communicated, not hidden behind a frozen UI. | List of anything over 200 ms and how it is surfaced, plus `node review/_audit_e5_coldload.mjs` — the worst animation frame and its blocking duration on a cold load, and the latency of keystrokes fired DURING that load. |

### E4, restated — why "1920×1080 with a trace animating" was not checkable as written

Two words in the original criterion could not be evidenced, and both are corrected above rather than
quietly satisfied.

**"A trace animating."** The packet only runs when the stitched path has non-zero length, which needs
at least two hops joined by a cable (`src/fabric3d/flow.ts`: `acc.length < 6` ⇒ `totalLength = 0`,
`packetRunning = !reducedMotion && totalLength > 0`). Measured over the product's own
`suggestedFlows()` + `traceFlow()` on this snapshot: every flow returns **one hop**, and one returns
none. So no reachable state animates a packet, and a 60 fps figure taken on a `?flow=` page is a
measurement of an **idle rAF loop with the renderer doing nothing** — the dirty flag is clear, the
loop ticks at the display rate, and nothing is drawn. Whether multi-hop traces should exist is a
question for the forwarding engine (A2/A5), not for this criterion.

The criterion therefore asks for a render condition that is **established and named**:
`review/measure-fps.mjs` prefers the trace packet, falls back to sustained camera motion — the
product's own focus-to-device affordance — and records which one it used. Every sample is gated on
`stats().converged === false`: a window the scene spent converged is reported **NOT MEASURED**, never
as a frame rate. Verified by removing the camera motion from a copy of the harness: it still reads
"mean 60 fps" off the idle loop and the gate answers `NOT MEASURED — the sample window was rendering
only 0% of the time`, exit 1.

**"At 1920×1080."** That is the **viewport**, not the render target. At a 1920×1080 viewport the
fabric is one region of a simultaneous four-surface layout and its canvas is **1160×962** — 1.12 MPix,
not 2.07 — at `devicePixelRatio` 1. No figure in this repository has been taken with the fabric
filling a 1920×1080 render target, and the reference machine's physical panel is 1280×800, so that
viewport is emulated in every run. Canvas CSS size, drawing-buffer size, device pixel ratio and
megapixels are now recorded beside every frame-rate figure, and `ATLAS_FULLBLEED=1` measures the
wider layout the product itself produces below 1024 px. A figure without its render target is not
evidence for this criterion.

## F. Engineering integrity

| # | Criterion | Evidence |
|---|---|---|
| F1 | `npx tsc --noEmit` clean under `strict` + `noUncheckedIndexedAccess`. | Actual command output from **both** projects, because one does not cover the other. `tsc -p tsconfig.json` reads `src/` only — `include` also lists `tools`, but `allowJs` is off, so no `.mjs` is read and `tools/compile-snapshot.mjs`, which produces every rendered byte, is outside that command's `--listFiles` entirely. `tsconfig.scripts.json` is the other half (strict + `checkJs` over `tools`), and `src/core/scripts-typecheck.test.ts` runs it from inside the suite so it is a gate rather than a command someone has to remember. |
| F2 | `npx vitest run` green, with tests that exercise the **real** compiled data, not hand-shaped fixtures. | Actual output plus a list of which tests touch real data. **`npx vitest run` is not the whole of F2.** `src/fabric3d/scene.test.ts` disclaims what jsdom cannot reach — post-processing pass order, colour management, SSAO, bloom thresholding, shadow-map fitting, measured frame rate — and delegates all of it to `npm run capture` (`review/capture.mjs app`) against a real browser. A red delegate is a red F2: cite the harness's own exit code (0 = every frame rendered, 3 = at least one did not), not just the unit suite's. |
| F3 | Every engine has survived an **adversarial refuter** whose stated job was to disprove it; confirmed defects fixed with a regression test that failed before the fix. | Refutation reports and the regression tests. |
| F4 | `npm run build` succeeds; the three.js bundle is code-split so the initial payload does not carry it. | Build output with chunk sizes. |
| F5 | Data is **source-bound**: `fabric.json` is reproducible from the snapshot by `tools/compile-snapshot.mjs`, and **the source snapshot's** sha256 is displayed in the app. | Re-run the compiler; byte-compare. The displayed digest is `meta.sourceSha256` — the digest of the snapshot the compiler READ (`9cc348bd…`), not of `fabric.json` itself (`fce33d24…`). Two different numbers, and the criterion means the first: the source digest is what binds the rendered model to an upstream artefact, which is the property "source-bound" names. The wording used to say "its sha256" and read as the second. The product never overclaimed either way — `Inspector.tsx` says out loud that the value is the compiler's declaration read back out of the model, not a digest this page recomputed. |
| F6 | No `Math.random()` or `Date.now()` in rendered output paths; two runs produce byte-identical captures. | Capture twice, compare hashes. |

---

## The blind comparison protocol (criterion C1)

This is the user's explicit bar and it decides when the loop stops.

1. Capture Atlas Scope in the seven investigation states, both themes, both viewports.
2. Capture the reference products at the same viewport.
3. Present a critic **two images with no identifying labels** — ours and a reference — and ask
   which is the better professional tool interface, and why, in specifics.
4. The critic must not be told which is which, and must not have built either.
5. Record the verdict and the specific reasons. **Every reason ours loses becomes a work item.**
6. Repeat until ours wins or ties on every pairing, with at least two independent critics agreeing.

A critic who cannot articulate a specific, actionable reason for its preference has not done the
job and its verdict is discarded.
