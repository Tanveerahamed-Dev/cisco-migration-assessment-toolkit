# The reference set — what it contains, and what it does not

A blind comparison is only as honest as the material it compares. This file records exactly what a
critic is shown and where each image came from, so a favourable verdict cannot rest on an unfair
pairing. **A verdict obtained from a bad pairing is worthless even when it favours us.**

Regenerate with `node review/capture.mjs refs`, `node review/capture-deep.mjs` and
`node review/capture-linear.mjs`.

## Usable as full-product comparison targets

These fill a 1920×1080 viewport with a real application and are what the blind pairings use.

| Frame | Product | What it shows |
|---|---|---|
| `refs-deep/forward-demo-b-step6.png` | Forward Enterprise | Nav rail, header with snapshot + timestamp selector, the grammar-teaching search bar, and the **Quick path search** panel (Traffic source / Traffic destination / Traffic type) over the topology canvas. |
| `refs-deep/forward-demo-a-step6.png` | Forward Enterprise | The same chrome with the Security section expanded (Posture, Blast Radius, Vulnerability, Exposure) over the map. |
| `refs-deep/grafana-explore.png` | Grafana Explore | The real query/result/inspect surface: datasource picker, time range, Run query, the Outline navigator, the query editor with **Query inspector**, and Graph + Table result panels. |
| `refs-deep/grafana-dashboard-dense.png` | Grafana | A dense working dashboard. |

## Captured but NOT used for pairing, and why

Keeping these on disk is deliberate — they are useful design research. Using them to judge craft
would not be.

| Frame | Why it is excluded |
|---|---|
| `refs/ipfabric-*.png`, `refs-deep/ipfabric-*-product*.png` | The IP Fabric material is **documentation**, and its figures are annotated instructional crops with red callout boxes drawn on them. Comparing our application to a tutorial diagram measures which image is less cluttered, not which is the better tool. |
| `refs-deep/linear-homepage-product.png`, `linear-method.png` | Mostly marketing headline copy, not a working list view. |
| `refs-deep/linear-*-product*.png` | Real product figures, but rendered at 650 px inside a docs page — an eighth of the pixel area of our capture. Size would decide the verdict. |
| `refs/batfish-fwd-validation.png` | A Jupyter notebook. Invaluable for its **claim vocabulary** (which we adopted in `docs/design-brief.md` §6) but not a UI to compare against. |
| `refs/apg-data-grid.png` | The W3C APG example. A conformance reference for keyboard behaviour, deliberately unstyled. |

## What the blind panel actually established — and what it did not

Three rounds, three critic lenses per sheet, twelve sheets per round:

| Round | Verdicts | Ours won | Tied | Lost |
|---|---|---|---|---|
| 1 | 33 | 32 | 0 | 1 |
| 2 | 36 | 36 | 0 | 0 |
| 3 | 36 | 36 | 0 | 0 |

**Read that table with suspicion. I do.** Two things undermine the win count as evidence that this
application is better than Forward Enterprise or Grafana:

1. **The critics could identify the reference.** The round-2 decoder reported "in every verdict the
   critic's loser was the REFERENCE panel (Forward Networks demo capture…". The brand-cropped
   `-craft` variants did not prevent it — the tour UI is recognisable on its own.
2. **The references are wrapped in demo chrome.** The Forward captures carry the Storylane tour
   modal ("End-to-End Path Search Demo") and a "Click on Vulnerability" coachmark over the centre of
   the working surface; the Grafana captures carry a "Create free account" promotional banner. A
   critic comparing a clean working application against a screenshot with a modal blocking it is
   judging the WRAPPER, not the product. Limit 1 below explains why the tours could not be
   advanced past their opening step.

A third reason for caution: one round-1 verdict declared a "decisive" win while listing **zero**
faults on our panel. Under the protocol in `docs/acceptance.md`, a critic who cannot name a
specific, actionable reason has not done the job, and that verdict should be discarded.

**So the head-to-head win count is reported, and is NOT offered as proof of C1.** It saturated at
72 of 72 across rounds 2–3, and a signal that cannot move cannot discriminate. From round 4 the
critique loop stopped using it as a convergence condition, in either direction, and dropped to one
critic per sheet.

**What the panel DID establish, and this part is solid:** the critics were required to list every
specific, actionable fault in OUR panel regardless of who won, and they did — 8 to 24 per critic,
roughly 350 across three rounds. Those fault lists fed the repair waves, and their per-critic count
fell from a peak of 24 in round 2 to 7–13 in round 3. That is real evidence of improvement, measured
against itself rather than against a compromised comparison.

The honest statement of acceptance C1 is therefore **UNPROVEN** against the named products, with the
reason above — not PASS.

## Known limits of this reference set — stated so nobody assumes otherwise

1. **Only two distinct Forward screens.** The Storylane demos are guided tours gated on clicking a
   specific highlighted element inside an `about:blank` `sl-renderer` iframe. Two automated drivers
   were written and both failed to advance past the opening step: a generic "Next" click produced
   nine byte-identical frames, and a coachmark-reading driver targeting the renderer frame found no
   clickable target. The duplicates were **deleted rather than kept**, because sixteen identical
   images presented as sixteen reference states would have inflated the apparent breadth of this
   set. What we have is genuine; there is simply less of it than intended.

2. **No Forward or IP Fabric RESULTS screen.** We can compare our path-trace surface against
   Forward's path-search *input* panel, but not against its rendered hop-by-hop *output*. That is
   the single biggest gap, and it means the p2 pairing judges composition and craft rather than
   result presentation head to head.

   A third attempt was made to close it by mining Forward's public product pages for embedded
   screenshots (the technique that worked for Linear and IP Fabric docs). It returned marketing
   architecture diagrams — "DATA IN / DIGITAL TWIN / INSIGHT OUT" — and no product UI. Those frames
   were **deleted rather than kept**: a marketing diagram in a reference set inflates its apparent
   size while contributing nothing a critic can judge craft against, and would quietly weaken every
   verdict drawn from the set. Three techniques tried, three failures, recorded so the fourth person
   does not repeat them.

3. **Everything is a static frame.** Motion, transition quality, latency and interaction feel are
   not in this set and cannot be judged from it. They are covered instead by `review/measure-inp.mjs`
   and the specialist audits.

4. **Brand marks are visible** in the uncropped sheets. `blind-pair.mjs` therefore also emits a
   `-craft` variant of every pairing with the top band cropped off both panels, and critics are
   instructed that brand recognition is not evidence of quality. The blinding is good but not
   perfect, and the fault lists the critics produce are useful regardless of which panel wins.
