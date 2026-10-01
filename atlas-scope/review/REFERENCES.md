# The reference set — what it contains, and what it does not

A blind comparison is only as honest as the material it compares. This file records what a critic
is shown, where each image came from, and how the blinding is measured, so a favourable verdict
cannot rest on an unfair pairing. **A verdict obtained from a bad pairing is worthless even when it
favours us.**

Owners:

- `review/capture-refs-clean.mjs` — the C1 reference set and its self-check
  (`node review/capture-refs-clean.mjs --fetch` to capture, `node review/capture-refs-clean.mjs`
  to re-check what is on disk, offline).
- `review/blind-pair.mjs` — the sheets, the KEY, the task vocabulary, the pre-registered rule and
  the verdict validator (`node review/blind-pair.mjs`; `--validate` re-reads `blind/verdicts.jsonl`).
  Our frames come from a private capture root, `blind/_ours/`, written by
  `ATLAS_URL=http://localhost:<port> node review/blind-pair.mjs --capture-ours` against a served build:
  it runs `capture.mjs app` there (with all of that harness's render checks) and measures our identity
  geometry from the same server. The shared `shots/app/` is not used: other review runs rewrite it.
- `review/capture-deep.mjs` — live design-research captures (tours advanced, banners dismissed).
  Not used for pairing.

### Regenerating the sheets — one command

From `atlas-scope/`, with the reference set on disk (`shots/refs-clean/`) and our frames on disk
(`blind/_ours/`):

    node review/blind-pair.mjs

That one command runs the self-tests (it builds nothing if one fails), re-reads the reference set,
re-checks every frame binding (our capture records, the derived frames against their base, the
declared reference slots against their frame sha), builds both side variants of every pairing,
and validates `blind/verdicts.jsonl`. It is deterministic for fixed inputs: a sheet is named by its
own bytes, so a rebuild whose rule, commit, frames and masks are unchanged writes byte-identical
sheets and keeps the existing `KEY.json` and `sheets.json` (it prints "unchanged since …"). Only
the per-critic side draw is random, and it is drawn once per build and kept with the KEY. Exit 0 =
built, 2 = at least one pairing BLOCKED, 1 = a self-test failed or the verdict file was edited.

Refreshing the INPUTS is separate, and each step is its own command: `node
review/capture-refs-clean.mjs --fetch` (network) for the references, and, against a served build
(`npx vite build --outDir <dir>` then `npx vite preview --outDir <dir> --port <port>
--strictPort`), `ATLAS_URL=http://localhost:<port> node review/blind-pair.mjs --capture-ours` for
ours. `--capture-ours` asks `capture.mjs app` for only the paired states (`ATLAS_STATES`) at
1920x1080 and at every paired reference's own CSS viewport (`ATLAS_VIEWPORTS`), then captures the
derived states and measures our identity geometry from the same server. The heaviest state
(`08-path-indeterminate`) must be captured on a quiet host: a contended host steps it down to tier
"balanced", which BLOCKS its pairing.

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
   what caught the "topology" frame that was actually a world map of sites. **And each paired
   reference DECLARES its task's result** (O70 R2-5): a TARGET's `taskState` — Grafana's result
   values, the traced path's "(source)" and "(transit)" labels, the device table's rows, the hop's
   decision rows, the dropping rule — is reviewed result text, and `blind-pair.mjs` requires it
   INSIDE the crop the critic sees (a pairing whose reference crop lacks it is BLOCKED). Toolbar
   labels ("Query inspector", "Query history") and panel titles ("Physical topology") hold whatever
   the screen shows, so they no longer prove the task. The self-check adds a contrast SCREEN: the
   declared text must be on the frame and on no frame of the same product whose task kind cannot show
   the task (`TASK_KINDS[kind].ref.contrast`: a network at rest, a query form before its result).
   **That screen is a sanity check, not a proof that the text is content rather than chrome:** fed
   each paired target's own chrome labels, it accepts them all on the current set (the product's
   contrast frame lacks that chrome — Grafana's only contrast is a kiosk page with no toolbar), and
   the self-check reports each target as "contrast screen UNCALIBRATED" (W5 round 2, QG-V3). A
   calibrated screen needs, per product, a no-result frame that carries the same chrome.
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
7. **Every frame whose identity marks were not measured in its DOM declares its identity slots**
   (logo glyph, workspace chip, user menu) as geometry measured on that frame, or an empty list with a
   reason. That is every raster frame, and every DOM frame captured before `--fetch` recorded
   `identityRects` (the DOM census then measured logo slots only). OCR reads words, not the chip
   around them, and cannot read a glyph, so it never stands for "covered". A later `--fetch` records
   each frame's identity marks structurally, with the same census that measures ours. Declared
   slots (and a declared "no slots" note) name the frame they were measured on by its sha256 prefix
   (`identitySlotsCheckedOn`); a frame with other bytes is refused until they are re-measured on it.
8. **Every reference names its task kind** from the one vocabulary (`blind-pair.mjs :: TASK_KINDS`),
   and every pairing's reference declares the pairing's kind; a control pairing whose reference shows
   another task must be flagged.
10. **No identity glyph beside a masked identity word escapes the masks** (O70 R2-6). OCR reads
   words, never glyphs, and widens an identity word's mask left by a fixed 2.5 line heights; a nav
   entry's icon can sit further out (the "Forward AI" sparkle survived on the composition sheet).
   For every identity word OCR finds on every frame, the first run of ink within 2 line heights to
   its left is measured on the pixels; a run that is text (an OCR word of two or more letters or
   digits) is not a glyph, and any other run must lie inside the masks the sheet will paint. A
   synthetic sparkle is its positive control. The Forward nav entry is now a declared slot, measured
   on each Forward frame.
9. A live undismissed Grafana control frame is captured too. It must be flagged **when the banner
   was actually served** to that session (its "Close alert" control is in the DOM); when the banner
   was not served, the self-check says so instead of counting the control as passed, and real-banner
   detection rests on the synthetic control.

## How a sheet is built (`node review/blind-pair.mjs`)

- **One pairing per C1 dimension**, matched by task:

  | Dimension | Task kind | Ours | Reference |
  |---|---|---|---|
  | composition | `path-blocked` | `06-path-blocked` | `forward-path-dropped` |
  | information density | `finding-list` | `03-finding-drill` | `forward-vulnerability-table` |
  | typographic craft | `path-hop-decision` | `06b-path-hop-evidence` (light; derived) | `ipfabric-path-detail` |
  | colour discipline | `result-data-inspection` | `07-evidence-raw` (dark) | `grafana-explore` |
  | network visualisation | `path-drawn` | `08-path-indeterminate` | `forward-topology-path` |

  **Matched by task on both sides, through one definition.** Each pairing names a kind from
  `blind-pair.mjs :: TASK_KINDS`. The reference TARGET must declare that kind (and proves it shows it
  by its expected text, above); our frame must meet the kind's `ours` specification: the captured URL
  (the investigation state), text legible in our frame, and, for `path-drawn`, a hop count of at
  least 2 on the header's Path badge; for `path-hop-decision`, the hop's evidence list recorded OPEN
  with a row on screen. Every one of these is checked **inside the crop the critic sees**, not on the
  whole frame. A pairing cannot carry a requirement of its own, and a kind's specification must name
  what only the task's visible surface shows (URL parameters alone can name a tab that is not the one
  showing). The REFERENCE must likewise show its TARGET's `taskState` (its task's result) inside
  the crop the critic sees (O70 R2-5). A state that
  does not show the task is BLOCKED, not judged. Two mismatches this closed: `05-path-trace` (the path
  surface before any flow is run) against a traced-path reference (now `08-path-indeterminate`, a
  drawn multi-hop trace), and `07-evidence-raw` — ONE DEVICE's compiled record — against IP Fabric's
  per-hop decision table. Repair round (verifier V1, V4): `04-finding-evidence` against Grafana
  Explore showed the FINDING tab (its URL's `tab=raw` belongs to the Device tab, which was not
  visible), so colour discipline now uses `07-evidence-raw`, whose visible surface is the raw
  compiled record; and the typographic state showed the hop's evidence list only as a collapsed label,
  so it now uses a DERIVED capture.
- **Derived states of ours** (`blind-pair.mjs :: DERIVED_STATES`). A state no URL encodes (an opened
  disclosure) is captured by `--capture-ours` FROM a clean capture.mjs frame: same URL, theme,
  viewport and DPR; the same settle, tier, convergence and palette pre-warm gates; then the
  interaction (`06b-path-hop-evidence` = `06-path-blocked` with "Evidence consulted at this hop"
  opened and its first row scrolled into view). Its record (`blind/_ours/derived/index.json`) carries
  the DOM facts the task kinds check and the sha of its base frame; a derived frame whose base has been
  re-captured since is refused. capture.mjs's text-fidelity and overflow audits ran on the base frame,
  not again on the derived one.

  The C1 criterion names "the 3-D render"; no reference product has one. That dimension is judged
  as **network visualisation** against Forward's 2-D topology, stated in the pairing, pending the
  owner's decision to keep it in C1 or move it to C5.
- **Symmetric presentation.** Both panels are the same CSS-pixel rectangle of their frame, rendered
  at the same device pixel ratio (the lower of the two captures'), so they match in pixel size and
  text scale; the build refuses a sheet whose two panels differ in size. Our theme follows the
  reference's measured theme. **Our frame is taken at the reference's own CSS viewport** when
  `--capture-ours` captured it there (`capture.mjs` `ATLAS_VIEWPORTS`, filed under `WxH`), so neither
  panel is a crop; only when that capture is absent does the build fall back to our 1920x1080 frame,
  cropped, with the cut recorded in the KEY (O70 D5).
- **Masks on both panels, by geometry first.** The union of these rectangles is painted, neutral
  grey, at the same place on both panels:
  - **our identity marks, measured in our DOM** (`identityCensus`): every visible element whose text
    holds one of our identity strings — the product name (index.html `<title>`) and every field the
    header's snapshot row renders (file, schema, sha8, read from the compiled data the header reads) —
    widened to the compact block it sits in (the brand with its glyph; the whole two-line snapshot
    button, collection date included), or only the phrase's own box inside prose. Measured once per
    frame by `--capture-ours` (cached by frame sha256 in `blind/_ours/identity-geometry.json`) and
    checked against the pixels: an identity string OCR reads on our frame outside every measured
    rectangle BLOCKS the pairing (the geometry does not describe that frame). An unmeasured geometry
    BLOCKS too. Why: on the 1x IP Fabric sheet OCR read neither `collect_parse_snapshot/1` nor the
    sha8, so the earlier string-only masks left our dataset row legible and the leak re-check (the same
    OCR) passed it;
  - the reference's identity marks: DOM logo slots, DOM identity marks where a fetch recorded them,
    and the slots its TARGET declares (Forward's glyph, workspace chip with its caret, user menu with
    its avatar; Grafana's "Powered by" footer);
  - as a second net, every product, vendor, wordmark, user and workspace string OCR finds in either
    panel (a match inside a chip of at most four closely spaced words masks the whole chip; inside
    prose only the phrase), read at the higher of the two captures' DPRs.

  The masked panels are read again, and a sheet on which any identity string is still legible is not
  emitted — its pairing is reported BLOCKED and stays UNPROVEN. That re-read is a net, not the proof:
  the proof of coverage is the measured geometry.
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
  masks, the slots and their sides, and the recognition vocabulary (`identityMasked` plus
  `referenceProducts`, the Product column of the table above, read from this file). Critics see only
  `blind/sheets.json` (slot, sheet name and sheet sha, question). Verdicts are appended to
  `blind/verdicts.jsonl` as exactly
  `{sheetSha, oursSha, refSha, commit, criticId, criticModel, recognized, recognizedAs, perDimension, reasons, faults}`
  — the schema is CLOSED and TYPED (`reasons` and `faults` are arrays of strings; the answer is
  `perDimension[<the sheet's dimension>]`): the panel step must write no other field and no other type,
  because a field or value the validator cannot interpret is read, leaf by leaf, as a possible pick (a
  possible loss), and such a line never counts.
- Sheets of an earlier build are moved to `blind/_superseded/`, and the KEY is not written while an
  orphan sheet remains in `blind/`.
- **The crop is disclosed.** The critic's instructions say both panels are same-size crops cut at
  the same place, and that content cut at a panel edge is not a fault. The KEY records, per pairing,
  how many CSS px each panel lost on the right and at the bottom.
- **Verdicts are append-only.** Each validation records the length and sha256 of the verdict bytes
  it read (`blind/verdicts.receipt.json`); a later file that does not start with exactly those bytes
  is refused. This is a tripwire, not a lock.

### The pre-registered rule (verbatim in `blind-pair.mjs :: RULE`; its sha is in every KEY)

Rule v6 (O70. v5, verifier round 2: v4 could still lose a loss through the key it was filed under, the
sheet reference it named, or a product named outside the `recognized` flag. v6, W5 round 2: v5 could
still lose one through a first-line "recognition" naming an ordinary identity string such as "Sign in",
a pick held in a malformed schema field, or an unbound line whose frames named no pairing). **A line is bound to its
sheet through one resolver, tolerant of form:** the full sha, the sheet's file name (with or without a
path or ".png"), or a unique hex prefix of at least 8 characters, after Unicode form, invisible
characters, case and surrounding space are normalised. A line on a sheet only an EARLIER build's KEY
lists (`blind/_superseded/*/KEY.json`) is **stale**; any other unresolved line is **unbound** and keeps
C1 UNPROVEN, and it is also an invalid verdict — the critic's first line — of every pairing it can be
tied to (the one pairing its frame shas name, and every pairing whose dimension it files an answer
under), where its A or B is a possible loss (its side is unknown). **A critic is its criticId with Unicode form,
invisible characters, case and spacing normalised** ("k1", " K1 " and "k1" plus a zero-width space are
one critic), and must then be plain ASCII; an id that is not (a homoglyph such as Cyrillic "к1") makes
the line **unattributable**: never counted, and its loss still blocks. **A pick is read from every
pick-bearing shape on the line**, since each sheet asks one question: every value in `perDimension`
under any key, a `perDimension` that is not an object (a bare "B"), every leaf of a field outside the
schema or of a schema field of the wrong type (`faults` as an object, `recognized: "B"`, `reasons: "B"`,
a non-string reason or fault), and a reason or fault that is nothing but "A", "B" or "tie".
Each value is normalised as an id is ("b" and " B " are B); a value that is not A, B or tie is
**unreadable** and is treated as a possible loss, never as a win, as are disagreeing values that may
pick the reference. An answer not filed under the sheet's own dimension (case, Unicode form and
separators aside: "Colour-Discipline" is the dimension, "color-discipline" is not) makes the verdict
invalid but is still read: a win filed elsewhere never counts, a loss filed elsewhere still blocks.
**One verdict per critic per pairing and dimension:** the first line from a critic bound to the
pairing is that critic's verdict, whatever its outcome (counted, recognised or invalid); a later line
never counts. **Recognition drops a win but never erases a loss:** a line discloses recognition when it
says `recognized: true`, or when its `recognizedAs`, reasons, faults or an extra field NAME anything in
the vocabulary (the KEY's `identityMasked` and the products this file lists; whole words — "IPFabric"
and "Grafana's" count, "forwarding" does not name Forward) whatever the flag says. A critic who
discloses recognition on any line, first or later, is excluded from counting, and **every loss on its
record stands** — including a first-line recognition that names a product (v5 set that loss aside, and
decided "names a product" against a vocabulary that holds ordinary words, so "a Sign in form" erased a
loss). `recognized: true` with an empty `recognizedAs`, and `recognized: false` with a non-empty one,
are invalid. A verdict counts only if it is
complete (and has no other field), bound to a current sheet, the current frames and the commit,
attributable, from a critic that disclosed no recognition, filed under the dimension, and reasoned.
**A loss is never ignored:** any line that picks the reference or whose pick is unreadable — counted,
invalid (an unreasoned loss is not a win), unattributable (recognising or not), bound only by its
frames or its dimension, a later re-ask, or any line of a critic who disclosed recognition — keeps the
pairing UNPROVEN; no loss is set aside. A pairing
is **PASS** iff at least two distinct critics' counted verdicts exist and there is no loss; otherwise
**UNPROVEN**. A loss keeps the pairing UNPROVEN for that build and its reasons become work items;
faults about content cut at a panel edge are crop artefacts, not work items. An unparseable or unbound
verdict line, or an empty recognition vocabulary, keeps C1 UNPROVEN. C1 is PASS iff every pairing is
PASS. Verdicts from recognising critics are reported separately, never counted. Each of these is a row
of `blind-pair.mjs :: VALIDATOR_CASES`, which the self-test runs.

Known consequence, stated so it is not mistaken for a defect: the vocabulary holds ordinary words
("Forward", "Sign in"), so a critic writing "the forward path" is read as naming Forward and its WIN
is dropped. That errs toward UNPROVEN, never toward a counted win; since no recognition erases a loss
(v6), a loss is never dropped by it. A second consequence: a critic who recognises the reference and
picks it keeps that pairing UNPROVEN for the build, so a pairing whose reference is easily recognised may
never PASS — a correct, fail-closed result of the method, and a reason to improve the blinding rather
than to discount the verdict.

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
   its control is "Close alert". (`capture-deep.mjs` matches every aria-label starting "Close";
   `capture.mjs refs` now dismisses by accessible role and name — a button named "Close …" or
   "Dismiss …" that does not close a menu, panel, sidebar or navigation, plus the consent buttons — and
   any other element whose aria-label carries such a name, so it stays a superset of the old selector.)
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
   pairings, its right 228 px on the IP Fabric one. `capture.mjs` now takes a viewport list
   (`ATLAS_VIEWPORTS`) and `--capture-ours` asks for every paired reference's viewport, so the next
   capture of ours removes the cut; until that capture is on disk the sheets fall back to the crop.
3. **Blinding is measured, not perfect.** Logo glyphs that OCR cannot read, a familiar layout, and
   our distinctive 3-D render can all be recognised. That is why recognition is asked and a recognising
   critic's win is never counted (its loss still stands).
4. **Everything is a static frame.** Motion, latency and interaction feel are covered by
   `review/measure-inp.mjs` and the specialist audits, not by this set.
5. The research captures that are NOT comparison targets (`shots/refs/`, `shots/refs-deep/`:
   marketing pages, the Batfish notebook, the W3C APG grid) remain design research only.
