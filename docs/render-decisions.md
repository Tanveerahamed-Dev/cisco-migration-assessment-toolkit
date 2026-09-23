# Render decisions

The A/Bs `design-brief.md` §4.5 and §4.6 required, run and recorded. Every row here is a
measurement taken from the shipped code path on a real GPU, not an argument.

The brief marks two render flags **INFERRED** and says, of the first: *"Do not ship the inferred
order as settled."* They were shipped as settled, with no A/B, behind a switch that was not
connected to anything. This file closes both.

## Method

All figures below come from the running dev build at `http://localhost:4180/fabric-preview.html`,
driven by Playwright with a real hardware rasteriser:

```
chromium --use-gl=angle --use-angle=d3d11
ANGLE (Intel, Intel(R) Graphics (0x00007D41) Direct3D11 vs_5_0 ps_5_0, D3D11)
viewport 1600x900, deviceScaleFactor 1, dark theme, quality tier `high`
```

Instruments:

- `review/_audit_cableaa.mjs` — counts, over the pure cable-over-background band (y 270–345,
  x 380–1000) at the default overview pose, how many background-to-cable edge crossings have **no**
  intermediate sample, plus single-pixel holes punched into the strokes. This is the repo's own
  metric and the one the finding was raised on.
- A threshold-free cross-check that walks each crossing from a confident background pixel to the
  cable plateau and counts samples strictly inside the ramp. It exists because the first metric
  classifies a pixel by a hard `isOrange` predicate, so anything that widens a stroke can move the
  number without the picture changing.
- 8x nearest-neighbour crops of a fixed cable band, looked at, because both metrics are proxies.

Every A/B below was re-run in both directions and reproduced.

## 1. SMAA before or after tone mapping — SETTLED: after, and it required a second pass

`design-brief.md` §4.6 flags the placement INFERRED. The code advertised a
`smaaAfterToneMapping` option to run the A/B.

**The option could not have changed a pixel, and the chain could not express the order it claimed.**

`EffectPass` merges its effects into one fragment shader, so listing `[tone, smaa, dither]` reads
as "tone maps first, then SMAA sees the result". `SMAAEffect` does not work that way. It carries
`EffectAttribute.CONVOLUTION` and does its real work in `update(renderer, inputBuffer)`, which runs
its edge-detection and weights passes over the buffer handed to the **whole EffectPass**, before
the merged shader executes at all (`node_modules/postprocessing/build/index.js`, `SMAAEffect#update`).
The edge detector therefore always saw the raw HalfFloat HDR buffer, on either side of `tone`.

Measured, flipping the flag's default and verifying the served module over HTTP:

| order (as listed in the single EffectPass) | crossings | zero-intermediate | holes |
| --- | --- | --- | --- |
| `[tone, smaa, dither]` | 876 | 675 (77.1 %) | 108 |
| `[smaa, tone, dither]` | 876 | 675 (77.1 %) | 108 |

Byte-identical, which is the signature of a flag wired to nothing.

**Decision.** Tone mapping moves into an `EffectPass` of its own, ahead of the SMAA pass, so the
order the brief asked for is the order that actually runs. Cost: one extra fullscreen pass.

| chain | crossings | zero-intermediate | holes |
| --- | --- | --- | --- |
| merged `EffectPass(tone, smaa, dither)` | 876 | 675 (**77.1 %**) | 108 |
| split `EffectPass(tone)` + `EffectPass(smaa, dither)` | 825 | 524 (**63.5 %**) | 90 |

Why it matters: SMAA is a perceptual filter. Its threshold, and especially its local-contrast
adaptation step — an edge is discarded when its delta is small beside the largest neighbouring
delta — are specified against display-referred values in [0, 1]. Fed unbounded linear radiance over
a near-black stage, a thin bright stroke's edge is numerically tiny beside the specular highlights
elsewhere in the kernel, and was being thrown away.

The `smaaAfterToneMapping` option has been **removed** rather than kept. It was never reachable
from `SceneOptions` (`contract.ts` is frozen and declares no such field), `src/dev/preview.tsx`
never read the query parameter it documented, and `scene.ts` never passed it. A settled decision
does not need a knob; an unreachable knob that advertises an experiment nobody can run is the
defect, not the fix.

## 2. `alphaToCoverage` on the cable material — SETTLED: removed

§4.5 required this to be A/B'd and removed if a no-op. The comment above it claimed it "is what
removes the stair-stepping from long diagonal cable runs".

It is not, and it could not be. In three 0.186.0's `LineMaterial` fragment shader the
`USE_ALPHA_TO_COVERAGE` branch replaces a `discard` with a smoothstep **only inside**
`if (abs(vUv.y) > 1.0)` — the round cap at each end of a segment. `vUv.y` runs along the segment
and `vUv.x` across it, which you can read off the cap test itself
(`a = vUv.x; b = vUv.y ∓ 1; if (a*a + b*b > 1.0) discard`, a unit circle centred on each segment
end). The two long edges of a stroke — essentially all of a cable's visible perimeter — are the raw
rasterised edges of a camera-facing quad and were untouched.

| | crossings | zero-intermediate |
| --- | --- | --- |
| `alphaToCoverage = true` | 876 | 675 (77.1 %) |
| `alphaToCoverage = false` | 828 | 609 (73.6 %) |

Slightly **worse** than nothing, which is what an unused multisample coverage path does when the
composer runs `multisampling: 0`. Removed, and the claim removed with it.

## 3. Composer MSAA — SETTLED: off, against expectation

Not required by the brief. Tried because it was the obvious candidate for the cable aliasing, and
recorded because it refuted the hypothesis.

| | repo metric, zero-intermediate | threshold-free, hard | cable pixels |
| --- | --- | --- | --- |
| `multisampling: 0` | 524 / 825 (63.5 %) | 42.5 % | 2882 |
| `multisampling: 4` | 574 / 789 (**72.8 %**) | **59.6 %** | 3471 |

Reproduced three times, including a same-session toggle back. Per-sample coverage quantises a
1.5–3 px stroke's edge to five levels and then hands SMAA a locally-clean image it declines to
filter further; at 8x the strokes come out chunkier, not smoother. The `msaaSamples` field added to
`QualityProfile` while testing this was **removed** afterwards rather than left sitting at 0 on
every tier — an always-zero knob is the same defect shape as §1's dead switch.

## 4. Cable edge coverage — the actual fix, and its cost

With the library shown to have no coverage term on the long edges, the cables get one of their own,
in `geometry/cables.ts`: a linear filter on the exact signed distance to the stroke edge, expressed
in device pixels via `fwidth(vUv.x)`, with the drawn quad widened by the same amount so the ramp is
added outside the encoded width rather than eaten out of it.

The widening is not cosmetic. The first attempt ramped inward without it, and
`cablePixels` fell from 2882 to 1195 — the cables had quietly gone translucent while the aliasing
metric appeared to improve. Because the filter is centred on the nominal edge, the ink that lands
on screen is the nominal width at every width, so the four speed steps keep their exact relative
weight (1.5 : 2.1 : 2.7 : 3.3) and only the outer extent grows, equally, on every cable.

| filter width | zero-intermediate at `high` | holes |
| --- | --- | --- |
| none (shipped) | 77.1 % | 108 |
| none, tone split only | 63.5 % | 108 |
| 1.0 px | 69.7 % | 105 |
| **1.6 px (chosen)** | **64.1 %** | **45** |
| 2.2 px | 57.7 % | 17 |

2.2 keeps winning on the metric and loses on the picture: at that width a 1.5 px cable never reaches
full coverage anywhere across its section, so the thinnest speed step — the one reserved for "speed
not observed" — reads as a smear rather than a wire. 1.6 is the last value where every width still
has an opaque core.

**Not closed.** 64 % of crossings at `high` are still single-step. A 1.5 px stroke has an honest
floor here — it cannot present several pixels of consistent edge for any reconstruction filter —
but the number is a long way from zero and this should not be read as solved. The gate to hold it
at is `review/_audit_cableaa.mjs`; treat a rise above 65 % at `high`, or holes above 50, as a
regression.

## 5. Shadows and grounding

Not a brief A/B, recorded here because the conclusion is counter-intuitive and the next reader will
otherwise re-diagnose "shadows are broken".

The shadow map works: it is enabled, allocated 2048², and rendered every frame. At the shipped
settings its **entire** contribution to the composed image was self-shadowing artefacts. Turning
shadows off changed 1.32 % of a focused-chassis crop at mean delta 10.7; leaving them on and
raising `normalBias` alone to 3.0 world units changed 1.29 % at mean 9.3 — i.e. almost the whole
difference between "on" and "off" was acne between the four interpenetrating meshes that make up
one chassis, not shadow.

The cast shadow is small **by construction**: `KEY_DIR` sits 52° above the horizon, and a rack unit
3.04 tall by 16 wide throws a shadow that clears its own footprint by 1.56 units in x and 1.78 in z
against half-extents of 8 and 5.5. It is a thin crescent at the base, which is also what a real
switch on a real shelf does. Grounding therefore has to come from the contact decals, and those
were failing for a separate reason: the decal used the same radial fade as the ground, which peaks
at the decal's CENTRE — the one part of it a chassis standing on it hides completely. See
`materials.ts :: contactFade` and `geometry/ground.ts :: CONTACT_SPREAD`.

Deck luminance either side of a focused chassis, horizontal scan, dark theme, tier `high`:

```
no decal at all   ... 99 98 [chassis] 96 94 ...
opacity 0.52      ... 98 93 [chassis] 80 73 ...
opacity 0.70      ... 98 91 [chassis] 73 63 ...   <- chosen
opacity 0.85      ... 98 89 [chassis] 67 53 ...
```

## 6. Ground planes and depth — the one-line cause of two defects

`materials.ts` now sets `depthWrite: false` on the deck and floor materials. A depth write is not
alpha-weighted, so the outer band of a faded plane — which paints nothing — was still stamping the
depth buffer across its whole rectangle and discarding everything drawn behind it.

- The "hard rectangle" the decks were documented never to terminate on was not painted deck. It was
  the rectangular silhouette of **erased background**. The fade was working; the depth write was
  drawing the rectangle.
- Every cable behind a deck vanished outright instead of showing through an 85 %-opacity surface.
  Framed on `core1`, the nine core-to-access cables stopped dead at a straight line partway down
  the frame.

Both disappear with the write off, and nothing needed it: chassis are opaque, so they draw before
any transparent surface and still occlude these planes through the depth **test**, which stays on.
Disabling mipmaps on the fade texture — the other candidate — changed nothing at all, and is not
part of the fix.

## 7. Band colour — the encoding moved channel

`design-brief.md` §4.4 makes instance colour the `Device.band` encoding. On the chassis body it
carried nothing: Poor rendered `#bdbabb` and Critical `#bbb6b9`, three levels apart, against a
within-Poor spread of about fifteen levels.

The wash toward white was reduced from 0.72 to 0.40, but a sweep to 0.0 shows that is not where the
information was going:

| wash | Poor | Critical | Good | Excellent |
| --- | --- | --- | --- | --- |
| 0.72 | 189,186,187 | 187,182,185 | 174,179,177 | 178,184,185 |
| 0.55 | 187,183,182 | 186,179,180 | 170,176,171 | 173,183,181 |
| 0.40 | 186,182,178 | 183,178,175 | 163,174,165 | 169,181,178 |
| 0.25 | 182,181,175 | 179,177,172 | 159,172,160 | 162,181,175 |
| 0.00 | 180,180,171 | 177,175,167 | 154,169,151 | 156,180,172 |

Poor against Critical moves by three levels across that entire range. The face being measured is
the lit lid, at roughly 185/255, where AgX's shoulder compresses chroma hard — which is what AgX is
for. `--band-poor` (#ff9f45) and `--band-critical` (#ff6b6b) differ only in green and blue and
cannot survive there at any mix.

So the band is carried on the status LED, whose material is emissive-driven from the instance
colour and sits on a near-black recess where nothing is compressed. That channel already existed
and its call site already carried a comment claiming it showed "the band at FULL saturation" — it
did not, it was passing the body's 72 %-white wash, brightened. Fixing that is what makes the
encoding real: a Critical chassis and an Excellent chassis are now plainly different pictures.

### 7a. Band colour on the body — hue at fixed luminance (2026-09-22, supersedes the wash)

The C5 critic measured the body channel still failing after §7: Critical and Poor lids nearly
identical in both themes, and in light theme every lid dark and muddy (the light band tokens are the
AA-on-white text variants, `#b52626` / `#a14a0a`, multiplied almost raw onto a mid-grey body). The
wash could not fix it at any value, because a token washed toward white keeps only what its channels
happen to differ in.

`scene.ts :: BODY_BAND_TINT` now takes only the token's **hue** and re-expresses it at one fixed
saturation and one fixed linear **luminance** per theme (light `s 0.55, Y 0.22`; dark `s 1, Y 0.32`),
then multiplies the body albedo. Equal luminance, not equal HSL lightness — at one lightness a green
carries ~2.5x a red's luminance. The LED keeps the true token. Measured (real GPU, `high`,
1920x1080, median lid RGB inside `chassisScreenBox`, ring 6-10 px outside it for the ground):

| | Critical lid | Poor lid | CIE76 dE C/P | collected chassis vs ground |
| --- | --- | --- | --- | --- |
| light, before | 126,91,92 | 122,96,91 | 6.2 | 3.93-5.22:1 |
| light, after | 146,89,89 | 138,93,67 | 14.9 | 4.39-5.16:1 |
| dark, before | 174,143,151 | 172,142,143 | 3.9 | 5.53-6.67:1 |
| dark, after | 179,109,110 | 173,112,89 | 13.1 | 4.05-4.49:1 |

The label letter remains the greyscale channel; the body is now a second, genuinely hue-carrying one.

## 8. Cables are schematic strokes, not cable geometry — ACCEPTED, deliberately

The C5 critic measured a cable's cross-section as a flat plateau (`[100,158,157,101]`) with no
thickness change under dolly, and called it the "real cable geometry" anti-pattern. That reading is
correct and the choice is kept, for a reason that outranks the look: **stroke width is an encoding.**
The four link-speed steps are 1.5 : 2.1 : 2.7 : 3.3 CSS px (`geometry/cables.ts`, `worldUnits:
false`), and a world-space width component would make a link's apparent speed depend on how far it
is from the camera — a near 1 G link would out-weigh a far 10 G one. The cylindrical term that
exists (`CABLE_TUBE_EDGE`, crown 1.0 to edge 0.68) is below what a 2-3 px stroke can resolve once the
one-pixel coverage ramp is applied, which is why the profile reads flat. Cables in this product are
schematic strokes of honest, depth-independent weight; that is a decision, not an omission.

## 9. Uncollected ("ghost") chassis fill — raised to a state indicator (light theme)

Light theme, the three never-collected chassis rendered their fill at 1.82-2.08:1 against the
ground (tint 0.72 toward `--claim-indeterminate`, opacity 0.40) — the legend's "collection:
topology only" state below the 3:1 a state indicator needs. The shell is now the indeterminate hue
deepened 40 % toward the ink at opacity 0.92, and the lid hatch deepens with it (a pale hatch
measured the fill back down to 2.4-2.8:1). Measured after: AP-floor1 4.14:1, AP-floor3-01 4.08:1,
wan-edge-rtr1.lab 5.06:1 (`materials.ts :: LIGHT_GHOST_DEEPEN`, `LIGHT_GHOST_OPACITY`). Dark theme was
already 4.54-5.78:1 and is unchanged.

## 10. Edge sparkle under a creeping camera (C5) — a reprojection-free history blend while the camera creeps

**What flickers, classified.** `review/capture-motion.mjs` classifies every flip-flopping pixel by
the image around it. Release build, Intel iGPU / ANGLE D3D11, 760x790, the two orbit sequences at
dark/high and light/low: about **90 % thin strokes** (cables, curbs, faceplate strips), the rest
**silhouettes**, and **zero** specular-highlight or flat (shading / ambient-occlusion) pixels. It is
therefore not a shading problem: specular anti-aliasing or a steadier SSAO would change nothing. With
SMAA's blend weights cleared the same sequences flip 7-65 px, so the flicker is SMAA re-deciding a
1-3 px feature's edges every frame while the damped orbit creeps it by a fraction of a pixel.

**What did not close it**, beside the measurements above: 4x composer MSAA (§3, worse for these
strokes); every SMAA preset (347/350 px); diagonal detection off (259 px); diagonal off plus a
stroke mask (107-194 px); 2x supersampling (75-125 px, at four times the fill).

**Decision.** The chain's final output is blended with the previous presented frame **only while
the camera creeps** — the reprojection-free half of a temporal anti-aliaser: under a pixel per frame
the previous frame is already aligned to within that pixel, so no motion vectors are needed.
`postfx.ts :: HISTORY_AA` owns the numbers: weight **0.75** at full strength (a pixel toggling by D
per frame then moves by D(1-w)/(1+w), a seventh), full strength for camera steps of **0.02-0.5 px**
per frame, ramping to **off at 1 px** and above (a history of a frame that far away would trail),
and **plain** — the chain's output bit for bit — whenever the camera is still, and on any frame
where something other than the camera changed. Every settled frame, and so every F6 capture, is
unchanged; a frame drawn with a history is always followed by a plain one before the scene reports
`converged`.

**A/B, same host** (repair wave 3, R5): flip-flopping pixels over the orbit sequences were
**300 / 699 px** at `d3e2a1c` and **5-40 px** after. Re-measured on the merged wave-3 tree
(2026-09-23, release preview, same host): **9-35 px** per orbit sequence across the four legs
(dark/high 17 and 35, dark/low 17 and 23, light/high 20 and 32, light/low 9 and 34), all but five of
them thin strokes, no cluster of 16 px or more, and every C5 motion item PASS.
`review/capture-motion.mjs` is the gate.
