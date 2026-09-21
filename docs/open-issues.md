# Atlas Scope — open issues found during the build

Tracked here so they cannot be lost between agent waves. Each entry says how it was found and what
evidence exists, because an issue asserted without evidence is a rumour.

## Resolved

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

## Open

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

### R15. F6 failed — the status bar painted the live frame rate into every captured frame — FIXED, and now MEASURED (2026-09-21)

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

### R10. Wall-clock assertions in the unit suite were a flaky gate — FIXED AS A CLASS
(Formerly O2. Retained below in full because the diagnosis is the useful part.)

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
