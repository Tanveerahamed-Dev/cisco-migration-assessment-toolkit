# Atlas Scope

A three-dimensional network **investigation** surface over the assessment engine's evidence
snapshot. It answers two questions and refuses to answer them further than the evidence allows:

1. **From a priority, what is actually wrong, on which device, and what configuration proves it?**
2. **Can this flow get from A to B — and if not, exactly which line of configuration stopped it?**

It is built for a senior network engineer working a brownfield estate before a migration. Every
number on screen traces to a record in the snapshot; nothing is inferred, smoothed, or defaulted to
a healthy value.

---

## The one rule

**Absence is never rendered as health.**

`null` means *not observed*. It does not mean zero, and it does not mean fine. A device we never
reached is not a healthy device. An ACL line we cannot evaluate does not become a permit. A host
with no collected routing table does not get a forwarding verdict.

This is enforced in four places, not just intended:

| Mechanism | File | What it does |
|---|---|---|
| Compiler | `tools/compile-snapshot.mjs` | Converts `""`, `"-"`, `"N/A"` and the engine's `[NOT OBSERVED]` marker to `null`, and stamps a `cite` path on every record. |
| Types | `src/core/types.ts` | `null` is in the type of every optional datum, so a renderer cannot forget the case. |
| Claim layer | `src/core/claims.ts` | The only place a `null` becomes words, and the only source of verdict prose. |
| Gate | `src/core/claim-lint.test.ts` | Scans every source file's user-visible strings each test run and fails on an asserted overclaim. |

`0` and `false` are *measurements*, not absences. A port with zero CRC errors was counted. Treating
that as "not observed" would be the same lie in mirror image.

---

## What the data actually covers

Read from `fabric.coverage` at runtime — these are the real numbers, not a target:

- **26 devices** on the topology; **23** were inventoried, **3** are neighbours we never collected.
- **44 links**, of which **25** carry centrality analysis.
- **RIBs for 2 hosts** (`core1`, `core2`) out of 26. Forwarding claims are scoped to those two and
  say so in every verdict.
- **ACLs for 1 host** (`core1`). No `ip access-group` binding was collected anywhere, so *which
  interface and direction* an ACL applies to is unknown — every trace carries that caveat.
- **146 findings**, **43 cross-layer findings**, **122 port-health records**, **50 endpoints**.

The strongest claim this product can make is **SCOPED**. There is deliberately no badge above it:
with RIBs for 2 of 26 hosts there is no exhaustive search to be had, so nothing here is ever
labelled *proven*.

---

## Running it

```bash
npm install
npm run compile:data   # rebuilds src/data/fabric.json from the engine snapshot
npm run dev            # http://localhost:4180
```

```bash
npm run build          # typecheck + production bundle
npm test               # the full suite
```

The data is **source-bound**: `src/data/fabric.json` is reproducible byte-for-byte from
`webapp/sample_data/sample_fleet.snapshot.json` by running `npm run compile:data`, and the source
file's sha256 is displayed in the application. If the app shows a hash, that hash is what it was
built from.

---

## Architecture

```
tools/compile-snapshot.mjs     the ONLY bridge from engine snapshot to UI model
  └── src/data/fabric.json     compiled, cited, sha-stamped

src/core/
  types.ts        domain model — FROZEN contract
  data.ts         indexes + citation resolution
  store.ts        one investigation context, serialized to the URL
  claims.ts       claim honesty: badges, templates, the absence renderer
  query.ts        the filter grammar behind the query bar and palette
  tokens.css      the design system

src/forwarding/   longest-prefix match, ordered ACL evaluation, scoped verdicts
src/analysis/     articulation points, bridges, blast radius
src/fabric3d/     the three.js subsystem behind an imperative contract
src/panels/       the investigation surfaces
src/app/          shell, routing, keyboard model
review/           capture, blind comparison, and INP measurement harnesses
docs/             design brief, acceptance criteria, open issues
```

**Why the 3-D subsystem is imperative.** React owns the DOM and the investigation state; three.js
owns the canvas; `src/fabric3d/contract.ts` is the only place they meet. That boundary keeps the
render loop off React's critical path — an evidence-pane re-render cannot drop a frame, and a
camera tween cannot schedule React work. It is also what keeps the responsiveness budget honest:
input goes straight to the scene handle, not through a reconciler.

---

## An investigation is its link

Selection, scope, query and the active flow are all encoded in the URL
(`src/core/store.ts :: encodeInvestigation`). Panel sizes and tab memory are *not* — those are
preference, not evidence. So one link reproduces one investigation rather than one furniture
arrangement, and a finding can be handed to a colleague verbatim.

Copy and Share always emit the claim sentence, its scope tuple and its badge as a single block. A
verdict pasted into a ticket stripped of its bounds is the most common way an honest result becomes
a dishonest quotation.

---

## Reviewing it

```bash
node review/capture.mjs app      # 7 investigation states x 2 themes x 2 viewports
node review/capture.mjs refs     # the reference products, for comparison
node review/blind-pair.mjs       # unlabelled side-by-side sheets + a key you keep
node review/measure-inp.mjs      # laboratory responsiveness per declared journey
```

`review/blind-pair.mjs` exists because "it looks good" is not a measurement. It builds sheets
labelled only **A** and **B**, with the side chosen by a hash so it is not always the same, opaque
filenames so the sheet cannot be identified from its path, and an optional crop of the branding
band so a critic cannot recognise the reference and reason from reputation instead of from pixels.
The key mapping A and B back to source is written to a separate file.

INP numbers from `measure-inp.mjs` are **laboratory** measurements from a scripted actor on one
machine. They are not field INP and must never be reported as such. A journey the harness could not
measure is reported as `NOT MEASURED` and exits non-zero — an unexercised gate is not a gate.

---

## Documents

- `docs/design-brief.md` — the design contract: exact geometry, measured contrast, the 3-D recipe,
  claim templates, the keyboard and accessibility contract.
- `docs/acceptance.md` — how this is graded, by someone who did not build it.
- `docs/open-issues.md` — what is known to be wrong, with the evidence that established it.
