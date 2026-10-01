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
| Compiler | `tools/lib/compile-model.mjs` | The ONE compiler (the Node wrappers in `tools/` and the browser both call it). Converts `""`, `"-"`, `"N/A"` and the engine's `[NOT OBSERVED]` marker to `null`, and stamps a `cite` path on every record — except the stated uncited residual of bare host lists / host-keyed maps and aggregate summaries (`webapp/tests/test_scope_mount.py :: _UNCITED_MEMBERS`). |
| Types | `src/core/types.ts` | `null` is in the type of every optional datum, so a renderer cannot forget the case. |
| Claim layer | `src/core/claims.ts` | The only place a `null` becomes words, and the only source of verdict prose. |
| Gate | `src/core/claim-lint.test.ts` | Scans every source file's user-visible strings each test run and fails on an asserted overclaim. |

`0` and `false` are *measurements*, not absences. A port with zero CRC errors was counted. Treating
that as "not observed" would be the same lie in mirror image.

---

## What the data actually covers

Whatever the loaded snapshot recorded, and no more. The figures (devices on the topology and how
many were actually collected, links with centrality, which hosts have a collected RIB or ACLs,
findings, endpoints) are read from the loaded dataset's `fabric.coverage` at run time and shown in
the app; this page deliberately restates none of them, because a count copied here is a cache that
drifts from its owner (`docs/ssot.md`, "Atlas Scope compiled fabric"). For the bundled sample the
owner is the engine's sample fleet, `webapp/sample_data/sample_fleet.snapshot.json`, regenerated
only by `python webapp/sample_data/build_sample.py`.

Forwarding verdicts are scoped to the hosts whose RIB was collected, and say so in every verdict;
where no `ip access-group` binding was collected, *which interface and direction* an ACL applies to
is unknown and every trace carries that caveat. The strongest claim this product can make is
**SCOPED**. There is deliberately no badge above it: without a collected RIB for every host there is
no exhaustive search to be had, so nothing here is ever labelled *proven*.

---

## Running it — three ways, one compiler

Every way runs the same compiler, `tools/lib/compile-model.mjs`, over an engine snapshot; they
differ only in which snapshot and where it is compiled. Install the locked toolchain once
(`npm ci`, Node per `package.json` `engines`).

**1. Standalone, the bundled sample.** The tracked compiled documents (the compiler's
`OUTPUTS[].trackedPath`) are the sample fleet, compiled ahead of time.

```bash
npm run dev            # http://localhost:4180
npm run build          # typecheck + the standalone bundle in dist/ (base "/")
npm test               # the full suite
npm run compile:data   # regenerate the tracked compiled documents from the sample (never hand-edit them)
```

The data is **source-bound**: the compiled documents are reproducible byte-for-byte from
`webapp/sample_data/sample_fleet.snapshot.json`, and the app displays the digest it was compiled
from, with its form (see "digest forms" below).

**2. Open a snapshot file.** In a standalone build, "Open a snapshot file…" (the header) validates
and compiles an engine snapshot in a worker in the browser, keeps it in that browser (IndexedDB) and
reloads into it; nothing is uploaded. A banner names the opened file on every screen, and "Return to
the sample" forgets it (`src/app/OpenSnapshot.tsx`). From the command line,
`node tools/compile-all.mjs --source <snapshot.json>` compiles a snapshot into `.local-data/` (the
only in-repository place it will write a real assessment, because that directory is ignored);
`ATLAS_DATASET_DIR=<that directory> npx vitest run` runs the suite against it (`vitest.config.ts`).

**3. Inside AssessHub — the one door.** `npm run build:hub` writes the hub build to `dist-hub/`
(base `/scope/`, no sourcemaps, and no compiled dataset at all: the page reads the snapshot at run
time). AssessHub serves that directory at `/scope` by default (`webapp/backend/app.py`
`_REPO_ATLAS_SCOPE_DIST`); start AssessHub from the repository root with
`python -m webapp.backend.serve`, open a snapshot, and use **Open in Atlas Scope**
(`/scope/snapshots/{id}/`). The page fetches `GET /api/snapshots/{id}/raw` — the stored bytes, under
every AssessHub access guard — and compiles them in the browser. AssessHub refuses to serve a /scope
build that is not a runtime build or that carries any snapshot evidence, and says why instead of
linking it (`webapp/backend/app.py` `_scope_file_index`; its self-test prints the verdict on its
`atlas-scope-dist` line). It also reads `index.html` — and any other HTML or XML page a build ships —
only the way a browser reads it, so the shell must stay plain markup: every `<` opens a tag, an end
tag `</name>` or a well-formed comment (never `a < b` in an inline script, `</script x>`, `<!-->` or
`<![CDATA[`), no comment contains `</`, and no page declares its own referrer policy
(`_scope_html_reading`; anything else is refused as `invalid_build`, never guessed at). The portable Atlas bundle ships the same hub build as its own member
(`portable/atlas_bundle.py` `SCOPE_DIST_SOURCE`), and its build refuses to proceed without it.

**Digest forms.** A digest is shown with its form, because the same snapshot has several: the
file's LF-normalised digest (ways 1 and 2) and AssessHub's stored-blob digest (way 3) are NOT the
same fact — the store re-serialises what it parses. The forms are registered in `docs/ssot.md`
("Facts that live in two homes").

---

## Architecture

```
tools/lib/compile-model.mjs    the ONE compiler: engine snapshot -> UI model (Node and browser)
  ├── tools/compile-all.mjs    Node wrapper: the tracked sample outputs, or --source <file>
  └── src/data/fabric.json     compiled, cited, sha-stamped (plus the three sidecars)

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
