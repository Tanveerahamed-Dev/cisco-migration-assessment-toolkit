# The reference set — what it contains, and what it does not

A blind comparison is only as honest as the material it compares. This file records what a critic
is shown, where each image came from, and how the blinding is measured, so a favourable verdict
cannot rest on an unfair pairing. **A verdict obtained from a bad pairing is worthless even when it
favours us.**

Owners:

- `review/capture-refs-clean.mjs` — the C1 reference set and its self-check
  (`node review/capture-refs-clean.mjs --fetch` to capture, `node review/capture-refs-clean.mjs`
  to re-check what is on disk, offline).
- `review/blind-pair.mjs` — the sheets, the KEY, the pre-registered rule and the verdict validator
  (`node review/blind-pair.mjs`; `--validate` re-reads `blind/verdicts.jsonl`).
- `review/capture-deep.mjs` — live design-research captures (tours advanced, banners dismissed).
  Not used for pairing.

All reference imagery is third-party product material. It lives only under `review/shots/` and
`review/blind/`, both gitignored: it is never tracked and never goes into anything published
(including the master-reference site and the golden artifacts).

## The C1 reference set (`shots/refs-clean/`, listed in its `manifest.json`)

| Frame | Product | How it is made | What it shows |
|---|---|---|---|
| `forward-path-dropped` | Forward Enterprise | Storylane page file, rendered offline | Path search result: hop list ending at a firewall, `Out ACL DENY ALL (default rule)`, `dropped`, Path MTU violation, the path on the physical topology. |
| `forward-topology-path` | Forward Enterprise | Storylane page file, rendered offline | A data-centre physical topology with a traced path highlighted. |
| `forward-path-device-details` | Forward Enterprise | Storylane page file, rendered offline | Path results with one device's details pane open (alternate). |
| `forward-topology-home` | Forward Enterprise | Storylane page file, rendered offline | Search home: site map with the quick path search panel (alternate). |
| `forward-vulnerability-table` | Forward Enterprise | Storylane stored page screenshot | A dense working table of devices by vulnerability, key metrics above. |
| `ipfabric-path-detail` | IP Fabric | Documentation screenshot (unannotated) | Path lookup detail: path topology, per-hop decision table, packet diff. |
| `ipfabric-path-lookup-app` | IP Fabric | Documentation screenshot (unannotated) | The whole application on its path lookup surface (alternate). |
| `grafana-explore` | Grafana | play.grafana.org, live, banner dismissed by pre-seeded localStorage, menu undocked | Explore: query editor, graph and table results, Query inspector. |
| `grafana-node-graph-kiosk` | Grafana | play.grafana.org, live, `?kiosk` | A node-graph dashboard (alternate). |

**Provenance that must travel with every Forward frame:** these are **Storylane recordings of
Forward, not the live product**. The demo's page list is read from the server-rendered data of a
plain GET (no player runs, so no tour and no player analytics); each recorded page is a saved copy
of Forward's DOM with its CSS inlined, rendered with JavaScript disabled at its recorded viewport
(1920x869). A recorded `<canvas>` whose pixels were stored as a `data:` image is replaced by that
image, which is a rendering-fidelity step and is disclosed as one. The vulnerability table is a
stored screenshot (2560x1168); its DPR (4/3) is derived from the same demo's recorded video
viewport, not assumed.

Every frame's manifest row records the source URL, the source bytes' sha256, the frame's sha256,
its CSS size and DPR, its **measured** theme (mean luminance), the DOM census where a DOM existed,
and when it was captured.

### Not obtainable

- **Linear — not obtainable without an account.** There is no public workspace, and the
  documentation figures are not small originals shown small: the source asset is 2494x1021, but it
  is a zoomed crop of part of a window on a marketing gradient, not a working screen. Linear is out
  of scope for C1 unless the owner supplies a capture of their own signed-in workspace. It is
  recorded as unobtainable in the manifest rather than substituted.
- IP Fabric's guided demo and trial are gated on an email + legal-consent form; this harness never
  fills one. The documentation screenshots above are the product without that gate.

## What the self-check proves (`node review/capture-refs-clean.mjs`)

It fails closed on each of these; a missing reference set is UNPROVEN, never "clean".

1. **Positive controls first.** The phrase matcher, the duplicate-reference check, the DOM census
   and the OCR text layer are each run on a known-bad input (a synthetic Storylane-style tour card
   rendered and read from its pixels) and must flag it. A check whose failure path never ran is not
   a check.
2. Every target is captured and every frame still matches its recorded sha256.
3. **No tour/banner marker**, on two independent layers: the DOM census (overlay roles — dialog,
   alertdialog, alert, aria-modal — and the tour player's component classes) where the frame was
   rendered from a DOM, and the OCR text of the **pixels** of every frame (Windows.Media.Ocr, the
   host's own engine, no network). A raster frame has no DOM layer; it is not thereby clean — the
   pixel layer applies to every frame, and an unavailable OCR engine fails the check.
4. Each frame shows the working surface it claims (its expected text is in its pixels). This is
   what caught the "topology" frame that was actually a world map of sites.
5. No two frames are byte-identical, and no two pairings share a byte-identical reference unless a
   pairing declares it (`sharesReferenceWith`).
6. **No two pairings present a near-identical reference SCREEN unless declared.** Byte identity is
   the narrow case: the check correlates 48x27 luminance thumbnails and flags pairs at 0.85 or above
   (calibrated on this set: the two Forward path-result recordings correlate at 0.92, every other pair
   at 0.77 or below; a synthetic "same layout, highlight moved" control must trip it). A pairing may
   declare a similar screen with its reason (`similarScreenWith`). One is declared:
   `forward-path-dropped` (composition) and `forward-topology-path` (network visualisation) are both
   Forward's path-search result screen with a different recorded path, because both of our states
   are our path surface too. Composition is judged on the whole screen, network visualisation on the
   drawing.
7. **Every raster frame declares its identity slots** (logo glyph, user avatar) as geometry measured
   on that frame, or an empty list with a reason. A raster frame has no DOM to measure a logo slot
   from, and OCR cannot read a glyph.
8. A live undismissed Grafana control frame is captured too. It must be flagged **when the banner
   was actually served** to that session (its "Close alert" control is in the DOM); when the banner
   was not served, the self-check says so instead of counting the control as passed, and real-banner
   detection rests on the synthetic control.

## How a sheet is built (`node review/blind-pair.mjs`)

- **One pairing per C1 dimension**, matched by task:

  | Dimension | Ours | Reference |
  |---|---|---|
  | composition | `06-path-blocked` | `forward-path-dropped` |
  | information density | `03-finding-drill` | `forward-vulnerability-table` |
  | typographic craft | `07-evidence-raw` | `ipfabric-path-detail` |
  | colour discipline | `04-finding-evidence` | `grafana-explore` |
  | network visualisation | `08-path-indeterminate` | `forward-topology-path` |

  **Matched by task on both sides.** A reference proves its task by its expected text (above); our
  state proves its task by `oursRequires` in `blind-pair.mjs`: the captured URL (the investigation
  state), text that must be legible in our frame, and, for the traced-path pairing, a hop count of at
  least 2 on the header's Path badge. A state that does not show the task is BLOCKED, not judged. This
  replaced `05-path-trace` (the path surface before any flow is run) with `08-path-indeterminate` (a
  drawn multi-hop trace). `06-path-blocked` is single-hop and draws no path geometry, so it is refused
  for that pairing too.

  The C1 criterion names "the 3-D render"; no reference product has one. That dimension is judged
  as **network visualisation** against Forward's 2-D topology, stated in the pairing, pending the
  owner's decision to keep it in C1 or move it to C5.
- **Symmetric presentation.** Both panels are the same CSS-pixel rectangle of their frame, rendered
  at the same device pixel ratio (the lower of the two captures'), so they match in pixel size and
  text scale; the build refuses a sheet whose two panels differ in size. Our theme follows the
  reference's measured theme.
- **Masks on both panels.** Every product, vendor, wordmark, user and workspace string found in
  either panel's pixels, plus the reference's logo slots (DOM-measured, or declared for a raster
  frame), becomes a neutral grey rectangle; the union of the rectangles is painted at the same place
  on both panels. Our identity strings are the product name and every field our header's snapshot
  row renders (file, schema, sha8), read from the compiled data the header reads, so our dataset row
  is masked as Forward's workspace chip is. A match inside a chip (a run of at most four closely
  spaced words, such as "Demo Network (default)") masks the whole chip; inside prose it masks only
  the phrase. Identity is read at the higher of the two captures' DPRs, because text a critic can
  still read on a 1x sheet may be too small for OCR at 1x. The masked panels are read
  again, and a sheet on which any identity string is still legible is not emitted — its pairing is
  reported BLOCKED and stays UNPROVEN.
- **Our frame must have rendered properly.** A pairing whose capture of our state recorded a
  rendering problem (or has no capture record) is BLOCKED rather than judged.
- **The side is drawn per critic.** Each pairing has both side variants; each critic slot in the
  KEY draws its side with `crypto.randomInt`. Sheet file names are derived from the sheet's bytes
  (both variants have names of the same form, so a name does not reveal the side). A rebuild whose
  rule, commit, frames, masks and sheet bytes are unchanged keeps its KEY and slots, so a critic
  panel already working from `sheets.json` is not disturbed.
- **Neutral questions**, one dimension each, and a **recognition question answered first**.
- **The KEY** (`blind/KEY.json`, never given to a critic) records the rule and its sha, the commit
  and whether the tree was dirty, each sheet's sha, both frames' shas and provenance, the crop, the
  masks, the slots and their sides. Critics see only `blind/sheets.json` (slot, sheet, question).
  Verdicts are appended to `blind/verdicts.jsonl` as
  `{sheetSha, oursSha, refSha, commit, criticId, criticModel, recognized, recognizedAs, perDimension, reasons, faults}`.
- Sheets of an earlier build are moved to `blind/_superseded/`, and the KEY is not written while an
  orphan sheet remains in `blind/`.
- **The crop is disclosed.** The critic's instructions say both panels are same-size crops cut at
  the same place, and that content cut at a panel edge is not a fault. The KEY records, per pairing,
  how many CSS px each panel lost on the right and at the bottom.
- **Verdicts are append-only.** Each validation records the length and sha256 of the verdict bytes
  it read (`blind/verdicts.receipt.json`); a later file that does not start with exactly those bytes
  is refused. This is a tripwire, not a lock.

### The pre-registered rule (verbatim in `blind-pair.mjs :: RULE`; its sha is in every KEY)

Rule v2. **One verdict per critic per pairing:** the first line from a critic on one of the
pairing's current sheets is that critic's verdict, whatever its outcome (counted, recognised or
invalid). So a critic who recognised a product, or gave an unreasoned loss, cannot be asked again.
A verdict counts only if it is complete, bound to the current frames and commit, from a critic who
did **not** recognise either product, and reasoned. A pairing is **PASS** iff at least two distinct
critics' counted verdicts exist and no unrecognising verdict, counted or invalid, picks the
reference; otherwise **UNPROVEN**. A loss keeps the pairing UNPROVEN for that build and its reasons
become work items; faults about content cut at a panel edge are crop artefacts, not work items. An
unparseable verdict line keeps C1 UNPROVEN. C1 is PASS iff every pairing is PASS. Verdicts from
recognising critics are reported separately, never counted.

Critics must be independent: a fresh context with no repository access and no design brief. A
human network engineer or a model from a different family is preferable; critics from the
builder's own model family weaken "must not have built either", and the KEY records `criticModel`
so that is visible.

## What earlier rounds established — and what they did not

Three earlier rounds (before this set existed) reported 104 of 105 verdicts for ours. **That count
is not evidence for C1** and is superseded, for reasons now known precisely:

1. **The tours never advanced, because of a selector miss — not because the product could not be
   captured.** `capture-deep.mjs` looked for a `<button>` "Next"; Storylane's controls are
   `<div class="PlayerButton_root__…">`. So "step3" and "step6" were byte-identical, four of six
   pairings showed a tour modal, and six pairings used three distinct reference images. A critic
   comparing a clean application with a screenshot blocked by a modal judged the wrapper.
2. **The Grafana banner stayed up** because both scripts looked for `aria-label="Close"` exactly;
   its control is "Close alert".
3. **The critics could identify the reference**, and the "-craft" crop (4 % of panel width) left
   "Forward AI" and our own wordmark legible.
4. **The side was a fixed hash of the pair id**, which put the reference on the left in every
   "-craft" sheet, and one question primed the critic with "rather than a demo".

The earlier claims that there was "no Forward RESULTS screen" and that "the IP Fabric material is
all annotated crops" were wrong: Forward's path result (`forward-path-dropped`) is in the recorded
pages, and IP Fabric's documentation includes unannotated product screenshots.

What those rounds DID establish still stands: the critics were required to list every specific,
actionable fault in our panel regardless of the winner (roughly 350 across three rounds), those
lists fed the repair waves, and the per-critic count fell from 24 to 7–13. That is evidence of
improvement measured against itself.

**C1 remains UNPROVEN until the recognition-screened panel runs against these sheets.** The honest
outcome may be that some pairings stay UNPROVEN because critics recognise a product or our 3-D
render; that is a correct result of the method, not a failure of it.

## Known limits — stated so nobody assumes otherwise

1. **Forward frames are recordings.** They are Storylane's saved copies of Forward's pages from its
   demo network, not the live product, and the map canvas is re-rendered from its stored image.
2. **Viewports differ, so the crop changes what is judged.** Forward pages are 1920x869 CSS, the
   stored vulnerability screenshot 1920x876 at 4/3, the IP Fabric figure 1692x943 at DPR 1 (declared
   from its text size, since the documentation does not publish it), ours 1920x1080 at 2x. Each
   sheet crops both panels to the common rectangle from the top-left and renders both at the lower
   DPR. The crop, the DPR and what each panel lost are in the KEY, and the critic is told the panels
   are crops. Our screen is cut more often than the reference: its bottom ~210 px on the Forward
   pairings, its right 228 px on the IP Fabric one. Capturing our state at the reference's own
   viewport would remove the cut; that needs a viewport option in `review/capture.mjs`.
3. **Blinding is measured, not perfect.** Logo glyphs that OCR cannot read, a familiar layout, and
   our distinctive 3-D render can all be recognised. That is why recognition is asked and recognising
   verdicts are excluded.
4. **Everything is a static frame.** Motion, latency and interaction feel are covered by
   `review/measure-inp.mjs` and the specialist audits, not by this set.
5. The research captures that are NOT comparison targets (`shots/refs/`, `shots/refs-deep/`:
   marketing pages, the Batfish notebook, the W3C APG grid) remain design research only.
