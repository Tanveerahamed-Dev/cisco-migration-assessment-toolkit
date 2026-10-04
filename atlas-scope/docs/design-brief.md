# Atlas Scope — Design Brief

> **Status: CONTRACT.** This document is the binding specification for every build agent working
> on `atlas-scope/`. Where it gives a number, that number is the value to implement — not a
> starting point to reinterpret. Where it says a thing is INFERRED or UNVERIFIED, that label is
> part of the contract too: do not launder it into fact, and do not remove the hedge because the
> result looked fine.
>
> **Provenance of this brief.** Synthesised from seven independent reference extractions
> (Forward Enterprise, IP Fabric, Linear, Grafana Explore, Batfish, WCAG 2.2 AA + ARIA APG + INP,
> three.js r186 / pmndrs-postprocessing 6.39.5) and reconciled against this repository's own
> ground truth: `atlas-scope/src/core/types.ts`, `atlas-scope/src/fabric3d/contract.ts`,
> `atlas-scope/src/core/store.ts`, `atlas-scope/src/core/tokens.css`,
> `atlas-scope/tools/compile-snapshot.mjs`, `atlas-scope/docs/acceptance.md`, and the compiled
> `atlas-scope/src/data/fabric.json` itself. Every contrast ratio quoted in §3 was computed from
> the literal hex values in this document, not estimated.
>
> **The data, measured from `fabric.json` on 2026-09-20:** 26 devices (23 inventoried, 3
> topology-only), 44 links, 146 findings (3 Critical / 104 High / 33 Medium / 6 Low — and **zero
> Info**), 43 cross-layer findings, 5 ACL findings (all 5 `indeterminate`), 9 L3 interfaces,
> 122 port-health records, 28 protocol-health records, 50 endpoints, 5 tiers, and 17 of 26 devices
> carrying `role: null`. RIBs exist for **2 hosts** (`core1`, `core2`). ACLs exist for **1 host**
> (`core1`). Link centrality was computed for **25 of 44** links. Source:
> `webapp/sample_data/sample_fleet.snapshot.json`, sha256 `9cc348bd58bbc2ed…`, 3,148,592 bytes,
> schema `collect_parse_snapshot/1`, engine `V3.23.0`, collected `2026-08-07T00:00:00+03:00`.
>
> **Do not hardcode those counts anywhere in the application.** They are a cache of
> `fabric.json` / `fabric.coverage` and must be read from it at render time (SSOT, Law 1).
>
> **Owner decisions of phase 2.75 (2026-09-28) — the engine output phase 3 will compile.** These
> change what the engine's sample fleet says once phase 3 regenerates and recompiles it, and so what
> this app renders from it; the figures above remain the committed fleet's until then
> (`docs/open-issues.md` R116–R119, O53, O63–O67).
> - **The core-to-core OSPF adjacency's home is an existing SVI, Vlan10.** core1's FULL/DR neighbour
>   10.0.99.2 runs over an SVI both cores already have (core1 10.0.10.2, core2 10.0.10.3, HSRP group 10
>   unchanged) on a VLAN Po1 already carries; the transit VLAN 900 added in phase 2.5 is retired.
>   Vlan20 was rejected because core1's inbound `VOICE_FILTER` would drop OSPF hellos. For Flow B
>   (§5.2) this means core1's table is no longer contradicted by its own neighbour, so the regenerated
>   fleet carries decided core1 outcomes, 2-hop traces and a found counterexample (a scratch run, not
>   yet the shipped data: open-issues O53). The RIBs held, the hosts modelled and the tables shown
>   incomplete must still be read from the compiled data at render time, never from this paragraph.
> - **core1's BGP configured-peer baseline is honestly INDETERMINATE**, because core1's configuration
>   capture is incomplete (it does not end with `end`, the fixtures' convention, which is kept). Its one
>   row — core1's established peer, NOT VERIFIED / BLOCKER — is the coverage-honest verdict, not a
>   defect to be engineered away. Any surface that shows this baseline shows INDETERMINATE with the
>   producer's reason, never CLEAR and never as healthy; the committed fleet's NOT_APPLICABLE is a
>   pre-substrate reading, not a statement about the substrate.
> - **The golden snapshot has no wall-clock boundary.** The owner's decision: the registry-health
>   "today" fields are volatile in the golden, and the freshness logic is proven with an injected
>   clock. **As implemented (awaiting the owner's ratification, open-issues O63):** the golden harness
>   pins the one registry freshness clock to the golden's evidence date instead, because normalising
>   the now-relative fields was measured not to remove the boundary (a stale registry cascades into
>   four snapshot sections and a workbook sheet); every `data_authorities` field therefore stays
>   frozen, and the fresh / exact-boundary / stale / future-dated behaviour is proven with an injected
>   clock (`tests/test_eol_registry_freshness_clock.py`). The engine's own freshness verdict is
>   unchanged: a real run judges registry health against its wall clock. The golden is a test fixture,
>   never the shipped data, so nothing this app renders changes; and the boundary is gone from the
>   golden only — the engine's other EoL/data-authority tests keep it (O63).
>
> **Phases 3 and 3.5 (2026-09-28 to 2026-09-30) — the regenerated fleet is the shipped data, and the
> owner's decisions it was built under.** Phase 3's precursor (`74275919`) regenerated the sample fleet
> from this branch's engine and recompiled the four documents from it (source digest `4d1805c6…`), so the
> data paragraph above describes the fleet of 2026-09-20, not the shipped one: the regenerated fleet
> carries RIBs for more hosts, ACLs for more than one, and decided multi-hop traces — read every figure from
> `fabric.json` / `fabric.coverage`, never from this brief. What these phases settled — the owner's
> decisions where marked "(owner)", otherwise designs their independent verifiers upheld
> (`docs/open-issues.md` R120–R129, O68–O77):
> - **A1's evidence route (§5.1):** the Evidence pane's header lists one control per record the engine
>   names, never folded and never scrolled with the pane body, so any finding reaches any engine-named
>   record in palette (1), id + Enter (2), control (3).
> - **(owner) The loading skeleton labels every device at the tier the layout places it** — the same
>   reconciliation, in the layout's own device order (`src/fabric3d/tier-groups.ts`); "tier not observed"
>   is only the layout's synthetic plane.
> - **(owner) The tier-fade slot's methods cannot act through a copy** (§4.8): the slot is a class with ES-private
>   state.
> - **(owner) Every test that pinned the old sample is an invariant chosen by property or a golden block**
>   (`src/test-support/golden-sample.ts`, which throws when the tracked sample's digest changes).
> - **(owner) Scale:** a 300- and a 1,000-device fleet lay out in slices that never stall the UI and fail loudly
>   into the fabric's error boundary; the wall-clock budgets (≤ 300 ms at 300 devices, ≤ 2 s at 1,000,
>   median main-thread layout compute) are gated in a real browser by `review/measure-scale.mjs`, and no
>   receipt is yet acceptance evidence (open-issues O74).
> - **One door for data:** `src/core/dataset.ts` is the only reader of the compiled documents; the
>   AssessHub hub build (`npm run build:hub` → `dist-hub`) carries no compiled dataset and compiles the
>   stored snapshot in a worker at run time; a standalone build can open a snapshot file. Every load
>   failure is a coded refusal; a digest the page did not compute says ", as AssessHub stated it (not
>   recomputed here)".
> - **(owner) AssessHub reads a /scope document only as a browser reads it**, in a restricted markup language
>   (the XML path is still open: open-issues O69).
> - **(owner) C1:** pairings matched by task on both panels, neutral masks on both, and a pre-registered KEY rule
>   under which a loss is never ignored (acceptance.md, "The blind comparison protocol"; three validator
>   holes remain, O70).
> - **(owner) D3's focus audit must finish each mode in ≤ 60 minutes with its denominators intact** — not met by
>   any recorded run (O68).
> - **(owner) Instruction of 2026-09-29:** phase 3.5 finishes without further focus-audit runs, without the C1
>   critic panel and without the acceptance re-grade, so no criterion moves on the strength of these
>   phases.

---

## 1. The one-sentence thesis

**Atlas Scope is one persistent investigation context — a query, a selection, and a snapshot —
rendered simultaneously as a 3-D fabric, a priority queue, a hop list and a raw-evidence
inspector, in which every claim carries the exact citation it rests on and the exact boundary
beyond which it does not hold, so that "we did not observe this" can never be read as "this is
fine."**

The three clauses are load-bearing and rank in this order when they conflict:

1. **Honesty outranks completeness.** A missing verdict is shipped as a missing verdict. We hold
   RIBs for 2 of 26 hosts; the product says so permanently, in the chrome, on every screen.
2. **Continuity outranks novelty.** Nothing the user does may blank, reset, re-layout or
   re-navigate a surface they were reading. Selection re-aims; it never restarts.
3. **Density outranks decoration.** Chroma is spent on severity and operational state only. The
   chrome is achromatic so that a Critical finding is the loudest thing on screen.

---

## 2. Screen architecture

### 2.1 Named regions

| Region | Id | Persistent? | Owns |
|---|---|---|---|
| Header | `#app-header` | Always | Brand, snapshot identity + sha256, coverage chip, theme toggle, palette trigger |
| Query bar | `#query-bar` | Always | The investigation question as removable tokens (§5) |
| Rail A — Path | `#rail-path` | Conditional (present iff `flow !== null`) | Hop tree, per-hop verdict, path findings, return-path stub |
| Rail A — Queue | `#rail-queue` | Always | Priority queue: the findings APG grid |
| Stage | `#stage` | Always | The three.js fabric canvas + its DOM mirror + canvas HUD |
| Inspector | `#inspector` | Transient (bottom-docked over Stage) | Claim / Query / Data / Raw / Error tabs (§5.3) |
| Rail B — Evidence | `#rail-evidence` | Always (content re-aims, never blanks) | Tabs: Summary · Ports · Routing · ACL · Findings · Raw |
| Status bar | `#status-bar` | Always | Coverage denominators, quality tier, frame budget, claim-strength legend |

`EvidenceTab` in `src/core/store.ts` already enumerates exactly `summary | ports | routing | acl |
findings | raw`. Rail B implements those six and no others.

### 2.2 Exact geometry — 1440 × 900

```
  0        300                                              1060      1440
  ├─────────┴───────────────────────────────────────────────┴─────────┤
0 ┌───────────────────────────────────────────────────────────────────┐
  │ HEADER                                                     44 px  │  --header-h
44├───────────────────────────────────────────────────────────────────┤
  │ QUERY BAR  (token chips)                                   40 px  │  --querybar-h
84├─────────┬───────────────────────────────────────────────┬─────────┤
  │ RAIL A  │  STAGE                                        │ RAIL B  │
  │ 300 px  │  758 px                                       │ 380 px  │
  │ 20.8 %  │  52.6 %                                       │ 26.4 %  │
  │         │                                               │         │
  │ ┌─────┐ │   ┌───────────────────────────────────────┐   │ ┌─────┐ │
  │ │PATH │ │   │  three.js canvas                      │   │ │TABS │ │
  │ │474px│ │   │  758 × 790 (or 758 × 474 w/ inspector)│   │ ├─────┤ │
  │ │(60%)│ │   │                                       │   │ │     │ │
  │ ├─────┤ │   └───────────────────────────────────────┘   │ │EVID-│ │
  │ │QUEUE│ │   ┌───────────────────────────────────────┐   │ │ENCE │ │
  │ │316px│ │   │  INSPECTOR (transient) 758 × 316      │   │ │790px│ │
  │ │(40%)│ │   │  = 40 % of 790, drag 200–632 px       │   │ │     │ │
  │ └─────┘ │   └───────────────────────────────────────┘   │ └─────┘ │
874├─────────┴───────────────────────────────────────────────┴─────────┤
  │ STATUS BAR   RIBs 2/26 · ACLs 1/26 · centrality 25/44 · tier HIGH │ 26 px
900└───────────────────────────────────────────────────────────────────┘
```

- Body height = `900 − 44 − 40 − 26 = 790 px`.
- Stage width = `1440 − 300 − 380 − 2 (1 px hairlines) = 758 px`.
- When `flow === null`, `#rail-queue` occupies the full 790 px and `#rail-path` is **absent from
  the DOM**, not present-and-empty. An empty panel that says "no path yet" is chrome; a panel that
  appears when the question is asked is an answer.
- When a trace exists, the Rail A splitter defaults to 60/40 and is draggable between 30 % and
  80 %, **with keyboard arrow operation and a double-click reset** (WCAG 2.5.7, §7).

### 2.3 Exact geometry — 1920 × 1080

```
   0         340                                                 1500      1920
 0 ┌──────────────────────────────────────────────────────────────────────┐
   │ HEADER  48 px                                                        │
48 ├──────────────────────────────────────────────────────────────────────┤
   │ QUERY BAR  44 px                                                     │
92 ├──────────┬────────────────────────────────────────────────┬──────────┤
   │ RAIL A   │  STAGE                                         │ RAIL B   │
   │ 340 px   │  1158 px                                       │ 420 px   │
   │ 17.7 %   │  60.3 %                                        │ 21.9 %   │
   │ 962 px   │  1158 × 962 (or × 578 with inspector at 384)   │ 962 px   │
1054├─────────┴────────────────────────────────────────────────┴──────────┤
   │ STATUS BAR  26 px                                                    │
1080└──────────────────────────────────────────────────────────────────────┘
```

- Body height = `1080 − 48 − 44 − 26 = 962 px` (status bar stays 26 px; header and query bar step
  up by 4 px each at ≥ 1600 px width).
- Stage width = `1920 − 340 − 420 − 2 = 1158 px`.
- **Stage gains the extra width, not the rails.** Rail A grows only 40 px, which is exactly enough
  to stop the finding title truncating at the 1440 width (acceptance C3); the remaining 400 px buy
  fabric legibility.

### 2.4 What is persistent, what is transient

**Persistent for the life of the investigation — must never unmount, blank, re-layout or lose
scroll position:** header, query bar, `#rail-queue`, `#stage` (including camera pose, tier state
and the three.js scene graph), `#rail-evidence`, status bar.

**Transient, dismissible, and always leaving its origin visible behind it:** `#inspector`
(bottom-docked, never covers the rails), the command palette (modal, focus-trapped,
Escape-dismissible), the config-evidence panel (§5.1 step 4 — a right-side overlay at **48 % of
window width**, 691 px at 1440 / 922 px at 1920, layered over the Stage with the Stage still
readable at reduced contrast, never a modal).

**Conditional but structural:** `#rail-path` exists iff a flow exists.

### 2.5 Responsive collapse ladder

| Breakpoint | Behaviour |
|---|---|
| **≥ 1600 px** | Rail A 340 / Rail B 420. Header 48, query bar 44. |
| **1280–1599 px** | Rail A 300 / Rail B 380. Header 44, query bar 40. The reference layout. |
| **1024–1279 px** | Rail A 280. **Rail B becomes an overlay drawer** (380 px, right-anchored, over the Stage, which stays visible and is not dimmed — the unapplied `.stage-dim` rule was deleted as dead CSS, 2026-09-23), toggled by `E` and by any evidence affordance, and closed by `Esc` from inside it (§7.1, owner decision 2026-09-26). A closed drawer is `inert` from the commit that closes it. Stage keeps ≥ 360 px. **Layering (PROPOSED 2026-09-26, pending the routed `shell.css` change — `docs/open-issues.md` O58):** an open drawer and the bottom-docked Inspector must not overlap; the Inspector docks to the drawer's left edge (`margin-inline-end: 23.75rem`). Until that change lands the drawer paints over the Inspector at this rung. |
| **768–1023 px** | Single column. Order: query bar → Stage (46 vh, min 320 px) → a segmented control (Queue · Path · Evidence) selecting one full-width panel below. Inspector becomes a full-width sheet. |
| **≤ 767 px down to 320 CSS px** | Stage defaults to **collapsed with the DOM mirror table shown instead**, and 3-D sits behind an explicit "Show 3-D fabric" toggle. This is the WCAG 1.4.10 reflow answer for the canvas and it is deliberate: at 320 px a 26-node fabric is not legible, and pretending otherwise is decoration. Every rail is a full-width stacked section. The grid scrolls horizontally **inside its own `overflow-x: auto` region**; the page body never scrolls in two dimensions. |

Every panel width is expressed in `rem` against a 16 px root, or in `ch` for text columns — never
as a fixed `px` literal in the stylesheet. The px figures above are the computed result at a 16 px
root and exist so a build agent can verify a screenshot, not so it can hardcode a pixel.

### 2.6 Layout conflicts between references, resolved

| Conflict | Winner | Why for us |
|---|---|---|
| Forward's 4-column shell (nav 10 / list 21 / evidence 21 / canvas 48) vs IP Fabric's single canvas with a left panel | **Forward's column model, minus the nav rail.** | We have no product-area navigation to rail — the palette (`Cmd/Ctrl+K`) is the destination switcher. Dropping the 10 % nav rail returns those pixels to the Stage: 52.6 % vs Forward's 48 %. |
| Forward's transient evidence column vs IP Fabric's always-live canvas | **Both, split by role.** | Rail B is *persistent and re-aiming* — once anything is selected it is never empty. The *deep* evidence (raw config text, raw snapshot JSON) is the transient overlay. Forward's transience applies to the deep layer only. |
| Grafana's bottom-docked inspector vs Forward's right-side config panel | **Grafana for raw data, Forward for config text.** | Raw data is wide and short → bottom dock keeps the claim visible above it. Config text is narrow and tall → right panel with a line gutter. Two shapes, two docks. |
| IP Fabric's expand-a-site-cloud-in-place vs a fixed tier layout | **Fixed deterministic tier layout wins; cloud expansion is out of scope.** | Our fabric is 26 nodes across 5 named tiers already given by `fabric.tiers`. Site clouds solve a 900-node problem we do not have, and force-expansion introduces nondeterminism that breaks acceptance F6 (byte-identical captures). |
| Linear's "hide empty groups by default" vs coverage honesty | **Coverage honesty wins: empty groups render by default.** | `Info · 0` is a positive statement about this snapshot. Linear's default optimises for a backlog; ours optimises for a denominator. |

---

## 3. Visual system

The token file `src/core/tokens.css` already exists and is largely correct. This section is the
**amended** contract: where a value below differs from the current file, the value below wins and
the file is to be updated. **Six tokens in the current file fail WCAG 2.2 AA and are corrected
here**; each correction states the measured ratio it failed at.

### 3.1 Typography

Families (unchanged):

```css
--font-ui:   "Inter var", "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
--font-mono: "JetBrains Mono", "SF Mono", "Cascadia Mono", ui-monospace, Menlo, Consolas, monospace;
```

Scale — six steps, and **working views use only `--fs-0` … `--fs-2`**:

| Token | rem | px @16 | Weight | Line-height | Letter-spacing | Used for |
|---|---|---|---|---|---|---|
| `--fs-0` | 0.6875 | **11** | 500 | 1.35 (14.85 px) | `0.01em` | Status bar, key labels in key:value rows, keycaps, table units, citation strings |
| `--fs-1` | 0.75 | **12** | 400 / 500 | 1.40 (16.8 px) | `0` | Dense grid rows, hop sub-lines, chip text, column headers (500) |
| `--fs-2` | 0.8125 | **13** | 400 / 500 | 1.50 (19.5 px) | `-0.006em` | Body text, finding titles, evidence prose, panel rows |
| `--fs-3` | 0.9375 | **15** | 600 | 1.35 (20.25 px) | `-0.010em` | Panel titles, tab labels, section headers |
| `--fs-4` | 1.25 | **20** | 600 | 1.25 (25 px) | `-0.015em` | Surface titles, empty-state headlines |
| `--fs-5` | 1.75 | **28** | 600 | 1.20 (33.6 px) | `-0.020em` | Headline numerals only (coverage counts, hop counts) |

- **Weights: exactly three.** `--fw-regular: 400`, `--fw-medium: 500`, `--fw-semibold: 600`. No 700.
  Hierarchy inside a row is carried by weight + ink colour, never by size.
- **`--fs-4` and `--fs-5` never appear inside `#rail-queue`, `#rail-path` or `#rail-evidence`.**
  They belong to empty states and status-bar numerals. This is Linear's near-flat rule and it is
  what gets 40 findings on screen at 1440.
- **Tabular numerals are mandatory** (`font-variant-numeric: tabular-nums`) on every numeric column,
  IP address, interface name, line index, byte count, and `elapsedMs`. Identifiers (`F001`, `L0`,
  `core1`, `Gi0/2`, `10.20.0.0/16`) render in `--font-mono` at `--fs-1` in `--text-muted`.
- **Minimum type size anywhere in the product: 11 px.** Forward's tours use 9 px topology labels; we
  reject that. Canvas node labels render at 11 px via SDF text, scaled with DPR, never below.

### 3.2 Spacing, radius, hit targets

4 px lattice, used exclusively:

```css
--sp-1: 0.25rem;  /*  4px */   --sp-5: 1.5rem;  /* 24px */
--sp-2: 0.5rem;   /*  8px */   --sp-6: 2rem;    /* 32px */
--sp-3: 0.75rem;  /* 12px */   --sp-7: 3rem;    /* 48px */
--sp-4: 1rem;     /* 16px */
```

Radii: `--radius-sm: 3px` (severity chips, badges), `--radius-md: 5px` (buttons, inputs, menus,
query tokens), `--radius-lg: 8px` (overlay panels, palette, inspector). Nothing is pill-rounded
except the coverage chip and the claim-strength badge.

**Row heights, fixed and non-negotiable:**

| Element | Height | Rationale |
|---|---|---|
| Findings grid row | **32 px** | The floor that fits a 24 × 24 target with 4 px padding (WCAG 2.5.8). 24 px rows cannot, and we do not use them. |
| Findings grid row, multi-device | **auto; min 32 px, max 56 px** | Forward's variable-height rule: vertical space ∝ how much is wrong. Beyond 56 px it truncates with a `+N more` affordance. |
| Hop row (device line) | **28 px** | The whole row is one target; no inline action glyph on it. |
| Hop sub-line (`key: value`) | **18 px** | Non-interactive text; exempt from 2.5.8 because it is not a target. |
| Evidence key:value row | **22 px** | Non-interactive. |
| Tab | **32 px** tall × ≥ 48 px wide | Target. |
| Column header | **28 px** tall × ≥ 56 px wide | Target (sort). |
| Inspector data-table row | **26 px** | Non-interactive cells; the row-inspect glyph is 24 × 24 with 1 px bleed, permitted because adjacent targets are ≥ 24 px apart centre-to-centre. |

**Every interactive target is ≥ 24 × 24 CSS px.** Where the glyph is 12 or 16 px, the hit area is
grown with padding or a `::before` overlay — never by shrinking the target. Where a target
genuinely cannot reach 24 px, it must satisfy the spacing exception: a 24 px-diameter circle centred
on its bounding box must not intersect another target's circle. **Every such exception is enumerated
in `docs/target-size-exceptions.md` with its measured spacing.** An unenumerated undersized target
is a defect. `docs/target-size-exceptions.md` exists only while at least one such exception does;
none does today, and `src/ui/target-size.test.ts` asserts the file's absence until it is taught to
read one (an exemption list nothing enforces is the defect it guards against).

**A grid cell is part of its row's target, not a target of its own.** The D5 browser census finds
`div.ag__cell` boxes under 24 px tall: one line of text inside a findings or record grid row that is
at least 32 px tall. They are not spacing exceptions, because the pointer action belongs to the row.
The data row's click activates it (`DataGrid.tsx`, `handlers.activate`); a click on a cell moves the
grid's roving focus to that cell (`handlers.move`) and bubbles to the row, which activates. The one
cell that is a target in its own right is a cell holding its own control (`GridColumn.interactive`):
that control stops the click, and it is held to the 24 px floor like any other target. The grid does
not present a cell as a separate control either: `.ag__row--data` sets `cursor: default` and no
`.ag__cell` rule declares a cursor (`DataGrid.css`). `src/ui/target-size.test.ts` reads that code, so
the argument fails the build the day it stops being true. The census, not this paragraph, remains
D5's evidence.

### 3.3 Colour — the full system, both themes, with measured ratios

**The rule for when colour may carry meaning.** Colour carries meaning for exactly four things:

1. **Severity** (`Critical · High · Medium · Low · Info`) — always paired with a distinct **glyph
   shape** and the literal word.
2. **Operational state** (`up · down · unknown`) — always paired with a glyph.
3. **Forwarding verdict** (the `HopVerdict` / `TraceOutcome` enums in `types.ts`) — always paired
   with a glyph and the verdict word.
4. **Health band** (`Excellent · Good · Fair · Poor · Critical`) — always paired with the band name.

Everything else — navigation, panels, borders, headers, tabs, scrollbars, the 3-D ground plane, all
chrome of every kind — is **achromatic**. There is exactly one non-semantic accent (`--accent`),
spent only on: the brand mark, the primary action in a dialog, link emphasis, and the active tab
underline. There is no second accent, no gradient, no glow on chrome, no tinted panel, no spotlight
card. **A UI that tints its own furniture cannot make a Critical finding louder than its furniture.**

#### 3.3.1 Light theme (`:root`)

**Owner: `src/core/tokens.css`.** The hex values below are a cache of it. Reconciled 2026-09-22
(open-issues O20): 18 light and 13 dark colour tokens here had drifted from the shipped tokens —
e.g. `--sev-high` read `#a14a0a` here while tokens.css ships `#803804` — so every drifted value now
carries the owner's own measured ratios (`tokens.css:` comments; light columns are surface-1 ·
surface-3 · `--chip-ink` on the fill). When the two disagree, tokens.css is right.

```css
:root {
  color-scheme: light dark;

  /* surfaces */
  --bg:        #ffffff;
  --surface-1: #f7f8fa;
  --surface-2: #eef0f4;
  --surface-3: #e4e7ec;
  --overlay:   #ffffff;
  --stage-bg:  #eef1f5;   /* the 3-D ground; one step off surface-2 so the canvas reads as a
                             surface, not a hole */

  /* ink — three steps, all >=4.5:1 on every surface they are permitted on */
  --text:       #11151c;  /* 17.22:1 on s1 · 14.76:1 on s3 · 18.29:1 on bg */
  --text-muted: #4e5768;  /*  6.84:1 on s1 ·  5.87:1 on s3   CHANGED from #5b6474 */
  --text-faint: #5f6775;  /*  5.36:1 on s1 ·  4.60:1 on s3   CHANGED from #8992a3 (was 2.95:1 — FAILED) */

  /* borders */
  --border:        #d7dce4; /* 1.38:1 on bg — STRUCTURAL HAIRLINE ONLY, never a control boundary */
  --border-strong: #747e91; /* tokens.css: 4.09:1 bg · 3.85:1 s1 · 3.58:1 s2 · 3.30:1 s3 — control edges */

  /* the single accent */
  --accent:      #0b6f68;  /* 6.02:1 bg · 5.67:1 s1 · 4.86:1 s3
                              CHANGED from #0d7d75 (was 4.03:1 on s3 — FAILED) */
  --accent-text: #ffffff;  /* 6.02:1 on --accent */
  --focus:       #0b6bd3;  /* 5.18:1 bg · 4.87:1 s1 · 4.57:1 on --stage-bg */

  /* severity — every value >=4.5:1 on the WORST surface it may appear on (surface-3) */
  --sev-critical: #8c1111; /* tokens.css: 8.97 · 7.69 · 9.53 */
  --sev-high:     #803804; /* tokens.css: 7.95 · 6.82 · 8.45 */
  --sev-medium:   #6e5000; /* tokens.css: 7.03 · 6.03 · 7.47 */
  --sev-low:      #246190; /* tokens.css: 6.20 · 5.31 · 6.59 */
  --sev-info:     #58677c; /* tokens.css: 5.42 · 4.65 · 5.76 */

  /* operational state — unknown is a THIRD thing, neither green nor red */
  --state-up:     #1b7352; /* tokens.css: 5.46 · 4.68 · 5.80 */
  --state-down:   #8c1111; /* tokens.css: 8.97 · 7.69 · 9.53 — tracks --sev-critical by design */
  --state-unknown: #63488c; /* tokens.css: 6.97 · 5.97 · 7.40 */

  /* health bands */
  --band-excellent: #1b7352; /* tokens.css: 5.46 · 4.68 · 5.80 */
  --band-good:    #40681d; /* tokens.css: 6.15 · 5.27 · 6.53 */
  --band-fair:    #6e5000; /* tokens.css: 7.03 · 6.03 · 7.47 */
  --band-poor:    #803804; /* tokens.css: 7.95 · 6.82 · 8.45 */
  --band-critical: #8c1111; /* tokens.css: 8.97 · 7.69 · 9.53 */

  /* claim strength — §6. Deliberately NOT on the severity ramp. */
  --claim-observed: #58677c; /* tokens.css: 5.42 · 4.65 — a complete traversal over partial evidence */
  --claim-scoped: #246190; /* tokens.css: 6.20 · 5.31 — bounded and complete within its scope */
  --claim-indeterminate: #63488c; /* tokens.css: 6.97 · 5.97 — the model could not decide */
  --claim-out-of-scope: #747e91; /* tokens.css: 3.85 s1 · 3.30 s3 — NON-TEXT only (rules, hatching), and always accompanied by the word */

  /* elevation */
  --shadow-1: 0 1px 2px rgb(16 22 32 / 8%);
  --shadow-2: 0 4px 12px rgb(16 22 32 / 10%);
  --shadow-3: 0 12px 32px rgb(16 22 32 / 16%);
}
```

#### 3.3.2 Dark theme

Emitted into **both** `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { … } }`
and `[data-theme="dark"] { … }`, with identical bodies, so an explicit choice wins in both
directions and the OS default is honoured.

```css
  /* surfaces */
  --bg:        #080a0e;
  --surface-1: #0d1117;
  --surface-2: #131923;
  --surface-3: #1b2330;
  --overlay:   #161d28;
  --stage-bg:  #0a0d13;

  /* ink */
  --text:       #e8ecf2;  /* 15.96:1 s1 · 13.32:1 s3 */
  --text-muted: #96a1b2;  /*  7.24:1 s1 ·  6.04:1 s3 */
  --text-faint: #828da0;  /*  5.65:1 s1 ·  4.71:1 s3   CHANGED from #68738a (3.97 — FAILED) */

  /* borders */
  --border:        #28323f; /* 1.46:1 s1 — structural hairline only   CHANGED from #222b39 */
  --border-strong: #61728f; /* 3.89:1 s1 · 3.62:1 s2 · 3.24:1 s3
                               CHANGED from #354154 (1.83:1 — FAILED) */

  --accent:      #3fd0c9;  /*  9.98:1 s1 */
  --accent-text: #04201f;  /*  8.99:1 on --accent */
  --focus:       #5aa8ff;  /*  7.64:1 s1 · 7.85:1 on --stage-bg */

  --sev-critical: #ff6b6b; /*  6.82:1 s1 */
  --sev-high:     #ff8317; /* tokens.css: 7.67 · 6.40 · 7.67 */
  --sev-medium:   #dca80c; /* tokens.css: 8.70 · 7.26 · 8.70 */
  --sev-low:      #89c1f3; /* tokens.css: 9.90 · 8.26 · 9.90 */
  --sev-info:     #c0c9d4; /* tokens.css: 11.31 · 9.44 · 11.31 */

  --state-up:     #4de0a5; /* tokens.css: 11.28 · 9.42 · 11.28 */
  --state-down:    #ff6b6b; /*  6.82:1 s1 */
  --state-unknown: #bea5e7; /* tokens.css: 8.76 · 7.31 · 8.76 */

  --band-excellent: #4de0a5; /* tokens.css: 11.28 · 9.42 · 11.28 */
  --band-good:    #7bd12f; /* tokens.css: 9.92 · 8.28 · 9.92 */
  --band-fair:    #dca80c; /* tokens.css: 8.70 · 7.26 · 8.70 */
  --band-poor:    #ff8317; /* tokens.css: 7.67 · 6.40 · 7.67 */
  --band-critical:  #ff6b6b;

  --claim-observed: #c0c9d4; /* tokens.css: 11.31 · 9.44 */
  --claim-scoped: #89c1f3; /* tokens.css: 9.90 · 8.26 */
  --claim-indeterminate: #bea5e7; /* tokens.css: 8.76 · 7.31 */
  --claim-out-of-scope:  #61728f; /* 3.89:1 — non-text only */

  --shadow-1: 0 1px 2px rgb(0 0 0 / 40%);
  --shadow-2: 0 6px 18px rgb(0 0 0 / 48%);
  --shadow-3: 0 18px 44px rgb(0 0 0 / 58%);
```

**Severity chips** (filled pill; dark ink on a light fill in dark theme, white ink on a dark fill in
light theme) — measured:

| Chip | Dark: ink `#0d1117` on fill | Light: ink `#ffffff` on fill |
|---|---|---|
| Critical | `#ff6b6b` → **6.82:1** | `#8c1111` → **9.53:1** |
| High | `#ff8317` → **7.67:1** | `#803804` → **8.45:1** |
| Medium | `#dca80c` → **8.70:1** | `#6e5000` → **7.47:1** |
| Low | `#89c1f3` → **9.90:1** | `#246190` → **6.59:1** |

**The light theme is not the dark theme inverted** (acceptance C4). Two concrete structural
differences that must hold:

1. **Severity ink flips, not just the hue.** Light = filled chip with white text; dark = filled chip
   with near-black text. The saturated dark-theme hues are too bright to carry white text and too
   light to work as outlines.
2. **Separation mechanism differs.** Light separates panels with a `--border` hairline on a white
   ground. Dark separates with the surface ladder (`#0d1117 → #131923 → #1b2330`), hairline
   secondary. Dark uses value steps; light uses rules.

### 3.4 Elevation and border rules

- **Depth on dark is the surface ladder + a 1 px hairline. Never a drop shadow.** A shadow on
  `#0d1117` is invisible; a lighter surface is the only depth cue that reads.
- **Depth on light is a 1 px `--border` plus at most `--shadow-1`.** `--shadow-2` is reserved for the
  inspector and the config overlay; `--shadow-3` for the command palette only.
- **No element inside a working view has a per-row border, per-row background, or per-row
  elevation.** Rows are separated by a single 1 px `--border` divider or by nothing at all. Hover is
  a `--surface-2` fill, no border change, no lift.
- `--border` may sit below 3:1 because it is structural decoration. **`--border-strong` is the only
  token permitted as a control boundary** (input outline, button edge, splitter handle, checkbox) and
  is ≥ 3:1 in both themes by construction (3.57:1 light, 3.89:1 dark).
- **Focus ring, one treatment for the whole app:**
  `outline: 2px solid var(--focus); outline-offset: 2px;` plus an inner ring via
  `box-shadow: 0 0 0 1px var(--bg) inset`, so the indicator survives on both the panel ground and
  the row-hover fill. **Use `outline` for the ring itself, never `box-shadow`** — `outline` survives
  `forced-colors` / Windows High Contrast; `box-shadow` does not.
  **No ancestor of a focusable cell may set `overflow: hidden`.** A clipped ring is the single most
  common silent regression in a dense grid, and it passes visual review because the ring is visible
  on whichever row happens to sit mid-viewport.

---

## 4. The 3-D fabric

**The stack is pinned and was verified by reading the installed modules, not assumed:**
`three@0.186.0`, `postprocessing@6.39.5`, `react@19.2.8`, `vite@8.2.1`
(`atlas-scope/package.json`). The installed `node_modules/postprocessing/package.json` declares
`peerDependencies: { "three": ">= 0.168.0 < 0.187.0" }`. r186 is in range; **r187 is not.** A CI
check must fail the build if the installed three version leaves that range.

**N8AO is NOT a dependency of this project and will not be added.** The three.js research recipe is
built around it; we substitute `postprocessing`'s own `SSAOEffect` + `NormalPass` +
`DepthDownsamplingPass` — all three confirmed present in the installed
`node_modules/postprocessing/build/types/index.d.ts`, along with `SelectiveBloomEffect`,
`ToneMappingEffect`, `ToneMappingMode`, `SMAAEffect`, `SMAAPreset`, `EdgeDetectionMode`,
`OutlineEffect` and `Selection`. The parameter defaults quoted in §4.6 were read from that file's
own JSDoc. Adding N8AO later is a separate, justified dependency decision — not a licence to build
against an absent package today.

### 4.1 Camera model

- `THREE.PerspectiveCamera(38, w/h, 1.2, 600)`. FOV 38° — wide enough to hold 5 tiers, narrow
  enough that perspective does not distort tier spacing into a false hierarchy.
- **`near = 1.2`, not 0.1.** Scene extent is ~140 world units; pushing `near` out is what buys depth
  precision, and SSAO quality depends directly on depth precision.
  **`logarithmicDepthBuffer` stays `false`** — it costs performance, interacts badly with the
  depth-consuming SSAO pass, and tightening `near` is the better fix.
- Orbit is constrained, not free: azimuth unlimited, **polar clamped to [12°, 78°]** so the user can
  never end up under the fabric or in a useless top-down plan that destroys tier reading. Dolly
  clamped to `[0.55×, 2.40×]` of the framing distance.
- Three camera commands, all already frozen on the `FabricScene` contract:
  `focusDevice(id)`, `resetCamera()`, and the implicit re-framing `setTrace()` performs.
  **Nothing else moves the camera.** Hover never moves it — the contract already documents
  `setHover` as the weak state.
- **The camera never drifts.** No idle rotation, no ambient float. SSAO converges better on a still
  camera, and a drifting camera makes a screenshot non-reproducible (acceptance F6).

### 4.2 Layout algorithm — deterministic, tiered, no physics

`fabric.tiers` already gives 5 ordered tiers from the engine:
`[AP-floor1]` · `[access1…access17]` · `[core1, core2]` ·
`[dist1, AP-floor3-01, dist2, wan-edge-rtr1.lab]` · `[podacc1, podacc2]`.

```
y(tier)   = (tier - 2) * 18            // the core tier (index 2) sits at y = 0, the visual datum
radius(n) = max(26, 7.5 * n / PI)      // arc radius grows with member count
dTheta    = (n === 1) ? 0 : (2.15 / (n - 1))   // a 123-degree arc, NOT a full ring
theta0    = -1.075
x(i,n)    = radius * cos(theta0 + i*dTheta)
z(i,n)    = radius * sin(theta0 + i*dTheta) * 0.62   // 0.62 flattens the arc into an ellipse, so
                                                     // the camera reads a row rather than a ring
```

- Ordering within a tier is by `Device.order` (present in the model), then `host` lexically.
  **No `Math.random()`, no `Date.now()`, no force simulation, no annealing.** Two runs produce
  byte-identical positions (acceptance F6) — which is also why we reject IP Fabric's force-directed
  model wholesale.
- Links spanning non-adjacent tiers use `LayoutResult.linkMidpoints` to arc **around** the
  intervening tier, never through it: a quadratic Bézier whose control point is offset radially
  outward by `0.35 × |Δtier| × 18`.
- The 3 topology-only devices (`collected: false`) are laid out in their tier like any other — they
  are part of the topology, and hiding them would be exactly the absence-as-health failure. They are
  *rendered* differently (§4.4).
- `LayoutResult.framing` is computed from `bounds` with a 1.18 padding factor and is the target of
  `resetCamera()`.
- **`prefers-reduced-motion`:** the layout is already static, so there is nothing to settle. The only
  motion to suppress is the camera tween (§4.8).

### 4.3 Renderer, composer and colour pipeline

```ts
const renderer = new THREE.WebGLRenderer({
  canvas, powerPreference: "high-performance",
  antialias: false,  // an MSAA default framebuffer is allocated and then discarded the moment
                     // RenderPass writes to an offscreen target — pure cost, zero benefit
  stencil:   false,
  depth:     false,  // the composer owns depth via its own targets
});
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.outputColorSpace  = THREE.SRGBColorSpace;   // r186 default; asserted at boot
renderer.toneMapping       = THREE.NoToneMapping;    // r186 default; the COMPOSER owns tone mapping
renderer.shadowMap.enabled = true;
renderer.shadowMap.type    = THREE.PCFSoftShadowMap; // r186 default is the HARDER PCFShadowMap
renderer.info.autoReset    = false;                  // multi-pass: we reset once per frame

const composer = new EffectComposer(renderer, {
  frameBufferType: THREE.HalfFloatType,  // UnsignedByte bands on #0a0d13 and clips emissive > 1,
                                         // leaving bloom nothing above threshold to find
  multisampling: 0,
});
```

**Colour-management contract, asserted at boot, throwing in dev:**

1. `THREE.ColorManagement.enabled === true` (r186 default — left alone).
2. `renderer.outputColorSpace === THREE.SRGBColorSpace`.
3. `renderer.toneMapping === THREE.NoToneMapping`.
4. Every colour-carrying texture (`map`, `emissiveMap`) is `SRGBColorSpace`; every data texture
   (`normalMap`, `roughnessMap`, `metalnessMap`, `aoMap`) is `NoColorSpace`. Our fabric ships with
   **no image textures at all** (§4.9), so this assertion guards future additions.
5. Every CSS token injected into the scene passes through `Color.setStyle()`, never `setHex()` on a
   raw literal, so sRGB values are converted into the working space instead of injected as raw
   linear numbers.

> **INFERRED, flagged:** the three.js researcher could not load
> `threejs.org/manual/en/color-management.html` (404 under the restructured docs) and reconstructed
> items 1 and 4 from the r152 change history. **Verify against the live manual before locking the
> assertion list.** Do not treat this note as satisfied because the render "looked right."

**Resize is a single choke point with four obligations, and missing any one fails silently:**
`composer.setSize(w, h)` (**never** `renderer.setSize`) → every `LineMaterial.resolution.set(w, h)`
→ `camera.aspect` + `updateProjectionMatrix()` → passes resized by the composer. Missing the second
produces cables at subtly wrong widths with no error anywhere.

Shaders are **precompiled before the first animated frame** so the fabric's first appearance does
not stutter.

### 4.4 Device representation

Three `InstancedMesh` instances, one per `Device.kind` observed in the data (`device`, `router`,
`ap`) — **not one Mesh per device.** Draw-call ceiling for the entire scene: **176**, asserted after
every render against `renderer.info.render.calls`.

That ceiling is a model, not a single reading, and it replaced a flat **120** that the product
breached permanently and silently the moment a path trace was on screen. A composed frame costs a
base plus a surcharge for each `OutlineEffect` that currently has something selected, because
postprocessing's `OutlineEffect.update()` re-renders the whole scene into a depth buffer and then
renders the selection into a mask. One number could only ever be right for one of those frames, and
120 was measured on the idle one.

| Frame | Measured | Budget |
|---|---|---|
| Base — no outline effect active | 74 | **88** |
| Each outline effect with a non-empty selection | +29 (selection) / +38 (blocked, which also blurs) | **+44** |
| Ceiling — base plus both outline effects at once | 141 | **176** |

Measured 2026-09-21, ANGLE → Intel D3D11, 1920×1080, `high`, `converged: true`, 30 consecutive rAF
samples per state with `min === max` in every row. The traced frame's extra cost is entirely the
second outline effect: a *delivered* trace measures 103, identical to a plain device selection, so
the trace geometry itself costs **zero** additional draw calls.

The base figure of 74 above was measured on the 2026-09-20 sample (`9cc348bd…`). Re-measured 2026-09-28 on
the regenerated sample (phase 3, reported): 71 at the `high` tier and 31 at `low`, and 73 / 32 with the
"other" role glyph present. A synthetic 300-device fleet opened through "Open a snapshot file…" measured
77 idle (45–47 during an orbit), inside the same base budget (phase 3, reported; laboratory, host at 100 %,
and on a 420×508 CSS px canvas, about a fifth of the sample's 1160×962 pixels, so not like-for-like:
open-issues R124).
The budget is unchanged.

The per-frame budget is `base + active outline effects × surcharge`, so the idle frame is now held
to 88 rather than to 120 — the model tightens the common frame while it stops lying about the rare
one. A breach is reported through `stats().overBudget` after two consecutive rendered frames over
the ceiling (so a post-chain rebuild transient is not called a standing breach) and is shown on the
quality chip in **every** build, dev and production alike.

| Kind | Geometry | Dimensions (world units) |
|---|---|---|
| `device` (switch) | `RoundedBoxGeometry` | 9.0 × 1.8 × 5.4, radius 0.22, 3 segments |
| `router` | `RoundedBoxGeometry` | 9.0 × 2.6 × 5.4, radius 0.22, 3 segments |
| `ap` | Cylinder + rounded cap | ⌀ 4.2 × 1.1 |

**Four encoding channels on the chassis, none of them colour alone:**

| Channel | Encodes | Values |
|---|---|---|
| Instance colour (`setColorAt`) | `Device.band` | `--band-*`, read from the live token via `Color.setStyle` |
| Chassis height | **nothing** | Fixed per kind. Height must never encode a metric — it reads as a bar chart and invites a comparison the data does not support. |
| Front-bezel extruded glyph (0.08 units) | `Device.role` | `access` = three stacked bars · `distribution` = a chevron · `null` = an outlined dash. `role === null` on **17 of 26** devices, and that is the truth of this data. |
| Surface treatment | `Device.collected` | `true` → solid PBR chassis. `false` → **the same silhouette as a 2 px (`MIN_STROKE_PX`) wireframe outline over a 22 %-opacity fill, with a 45° hatch on the top face.** Never green, never grey-as-disabled, never absent. |

**As shipped — where the band is actually legible (recorded 2026-09-21, C5 audit).** The instance
colour reaches two surfaces. On the chassis BODY it is a wash that the tone curve compresses on the
lit lid until adjacent bands (Poor/Critical, Good/Excellent) are only a few ΔE apart — the reasoning
and the measured mix sweep are owned by `BAND_BODY_WASH` in `src/fabric3d/scene.ts`. The band is
therefore carried by the emissive **status bar** on the faceplate (`LED_BAR_W`/`LED_BAR_H`,
`src/fabric3d/geometry/chassis.ts`, enlarged so it is several pixels at the overview) and, as the
colour-independent second channel, by the band letter on the device's DOM label chip. Do not read
this table as a promise that the body hue alone separates adjacent bands.

`Device.band === null` (3 devices) renders in `--claim-indeterminate` — **not** neutral grey and
**not** `--band-good`. `Device.opStatus === "unknown"` adds a `--state-unknown` rim, 0.06 units, on
the chassis edge.

Labels: a single SDF text atlas as one `InstancedMesh` of billboarded quads, 11 px at DPR 1. Below a
0.55 dolly factor labels drop **by count, not by opacity** (with 0.06 hysteresis to prevent popping):
the selected node and tier 2 keep their labels, the rest drop. Opacity fading produces the muddy
half-legible text that reads as unfinished.

### 4.5 Link representation

**Every link is a `Line2` / `LineSegments2` with `LineMaterial` from `three/addons/lines/`.**
`LineBasicMaterial` is forbidden for anything visible: WebGL silently ignores `linewidth > 1` on
essentially every platform — it does not throw, it renders a 1 px hairline forever, and no
post-processing pass rescues it. That is cheap-render tell #1 in acceptance C5.

`worldUnits: false` (the default), so widths are in **CSS pixels** and link weight is constant under
zoom — correct for a diagrammatic view, where a link's importance does not change because you
dollied in.

| State | `linewidth` | Colour | Second channel |
|---|---|---|---|
| Ordinary link, `opStatus: "up"` | **2 px** | `--claim-out-of-scope` @ 55 % | solid |
| Ordinary link, `opStatus: "down"` | 2 px | `--state-down` | **dashed** `dashSize 1.6 / gapSize 1.1` |
| Ordinary link, `opStatus: "unknown"` | 2 px | `--state-unknown` | **dotted** `dashSize 0.35 / gapSize 1.0` |
| `isPortChannel: true` | 2 px | as above | **N parallel offset lines, one per member**, 0.5 units apart — a port-channel is not one cable, and drawing it as one is a lie the data itself can refute |
| `isBridge: true` (cut partitions the graph) | **3 px** | `--sev-high` | **double line**, 0.35-unit gap |
| `isBridge: null` (centrality not computed — **19 of 44** links) | 2 px | `--claim-indeterminate` | **short-dash** `1.0 / 1.0` — it is not "fine", it is unmeasured |
| On the active trace path | **4 px** | `--accent` | directional arrowheads every 12 units |
| Selected / blocked hop segment | **6 px** | `--sev-critical` | arrowheads + a terminal stop-cap glyph |
| Hover | +1 px on current | unchanged | unchanged |

`alphaToCoverage: true` is set. **Flagged honestly:** the three.js docs describe `alphaToCoverage` as
improving line-edge AA *"when using MSAA"*, and our composer runs `multisampling: 0`. Its benefit
here is therefore **unverified** and must be A/B'd against SMAA-only during bring-up. If it is a
no-op, remove it rather than leaving a cargo-cult flag in the material.

Off-path links are **dimmed, never hidden** — 55 % opacity, 2 px, desaturated. Hiding off-path
structure produces a picture that cannot be checked: you cannot see the alternate link that should
have been taken, or how close the drop was to the edge. This is Forward's and IP Fabric's strongest
shared position and it is non-negotiable.

**Canvas contrast (WCAG 1.4.11 covers graphical objects — a canvas is not exempt), measured:**

| Element | Dark, on `--stage-bg` `#0a0d13` | Light, on `--stage-bg` `#eef1f5` |
|---|---|---|
| Trace path (`--accent`) | `#3fd0c9` → **10.26:1** | `#0b6f68` → **5.31:1** |
| Blocked hop | `#ff6b6b` → **7.01:1** | `#8c1111` → **8.41:1** |
| Dimmed off-path link | `#5c6678` → **3.36:1** | `#78839a` → **3.36:1** |
| `up` state | `#4de0a5` → **11.59:1** | `#1b7352` → **5.12:1** |
| `unknown` state | `#bea5e7` → **9.01:1** | `#63488c` → **6.54:1** |
| Node label | `#c7d0dd` → **12.50:1** | `#2a3140` → **11.50:1** |

(The blocked-hop and state rows were recomputed on 2026-09-22 from the shipped tokens.css values — O20.)
Every one clears 3:1; labels and path colours clear 4.5:1. **Minimum painted stroke is 2 CSS px at
DPR 1**, so the ratio is measured on real pixels rather than antialiased fringe.

### 4.6 Lighting, materials, post-processing — the concrete recipe

**Lighting: one key light plus an image-based environment. No light rigs.**

```ts
// Environment generated FROM A SCENE, so the build stays asset-free, offline and deterministic.
const pmrem = new THREE.PMREMGenerator(renderer);
pmrem.compileCubemapShader();                       // faster first paint
const envRT = pmrem.fromScene(buildStudioRig(), 0.04, 0.1, 100, { size: 256 });
scene.environment = envRT.texture;
scene.environmentIntensity = 0.85;                  // r163+; tune globally, not per material
pmrem.dispose();  // NOTE: PMREMGenerator is STATIC — disposing one instance affects all others.
                  // Dispose exactly once, at the end of environment generation.

// buildStudioRig(): three emissive planes — a large key box above-front-left, a cooler fill box
// behind-right, a dim floor bounce. No HDRI file, no network fetch, fully deterministic.

const key = new THREE.DirectionalLight(0xffffff, 2.1);
key.position.set(46, 62, 38);
key.castShadow = true;
key.shadow.mapSize.set(2048, 2048);
// Frustum fitted TIGHTLY to layout.bounds — not the +/-5 default. Shadow quality is dominated by
// frustum tightness, not map size: a 4096 map over a loose frustum is blurrier than a fitted 1024.
key.shadow.camera.left   = bounds.min[0] - 6;  key.shadow.camera.right  = bounds.max[0] + 6;
key.shadow.camera.top    = bounds.max[2] + 6;  key.shadow.camera.bottom = bounds.min[2] - 6;
key.shadow.camera.near   = 20;                 key.shadow.camera.far    = 190;
key.shadow.bias          = -0.0004;  // bias and normalBias are a PAIR — tuning either alone is
key.shadow.normalBias    =  0.022;   // wrong: bias alone buys acne removal at the price of
                                     // peter-panning (detached contact shadows = floating objects)
```

Exactly **one** shadow-casting light. `castShadow` and `receiveShadow` are set **deliberately on
every mesh** — a single mesh missing `receiveShadow` makes the whole scene read as unlit, silently,
and is a named item on the C5 checklist.

> **As shipped — deviation from the recipe above (recorded 2026-09-21, C5 audit).** The shadow map
> is **off at every tier**. The measurement that decided it, and the grounding that replaces it (a
> contact decal plus a surface pad under every node — not SSAO, because the ground planes write no
> depth), are owned by `src/fabric3d/quality.ts` (`SHADOW_MAP_IN_USE`, `SHADOW_MAP_REASON`) and are
> published at runtime in `stats().qualityReasons`; read them there rather than from a copy here.
> The key-light snippet above remains the recipe to restore if that decision is reversed. The
> `receiveShadow` rule still applies to every mesh so re-enabling the map is a one-flag change.

**Materials — `MeshStandardMaterial` by default; `MeshPhysicalMaterial` only on the named list
below.** The installed docs state `MeshPhysicalMaterial` has "a higher performance cost per pixel"
and that an environment map should always be supplied.

| Surface | Material | Values |
|---|---|---|
| Chassis body | `MeshStandardMaterial` | `metalness 1.0`, `roughness 0.38`, `envMapIntensity 1.0` |
| Chassis bezel / faceplate | `MeshPhysicalMaterial` | `metalness 1.0`, `roughness 0.29`, `anisotropy 0.6`, `anisotropyRotation 0` (brushing runs along X), `clearcoat 0`, `envMapIntensity 1.1` |
| Status rim / emissive band | `MeshStandardMaterial` | `metalness 0.0`, `roughness 0.55`, `emissive: <token>`, **`emissiveIntensity 2.2`** — must exceed 1.0 in linear space to cross the bloom threshold |
| Ground plane | `MeshStandardMaterial` | `metalness 0.0`, `roughness 0.82`, colour `--stage-bg` stepped 6 % |
| Tier plate | `MeshStandardMaterial` | `metalness 0.0`, `roughness 0.9`, 4 % opacity, `depthWrite: false` |

Enforced by the material factory and a lint rule: `metalness ∈ {0.0, 1.0}` only; `roughness ∈
[0.25, 0.9]` for dielectrics and `[0.15, 0.45]` for metal; **`roughness === 0` is forbidden** (a
perfect mirror is an instant tell); dielectric albedo luminance confined to sRGB `[0.03, 0.9]` — no
pure black, no pure white, because neither exists in a real material and both destroy the tone
mapper's shoulder.

> **INFERRED, flagged:** every numeric band in the paragraph above is standard PBR authoring
> practice as reported by the researcher, not a figure quoted from three.js documentation.

**The post chain — exact order, and it is a tested invariant:**

```ts
const normalPass = new NormalPass(scene, camera);
const depthDown  = new DepthDownsamplingPass({ normalBuffer: normalPass.texture, resolutionScale: 0.5 });

const ssao = new SSAOEffect(camera, normalPass.texture, {
  blendFunction: BlendFunction.MULTIPLY,   // library default
  distanceScaling: true,
  depthAwareUpsampling: true,
  normalDepthBuffer: depthDown.texture,
  samples: 16,              // library default 9
  rings: 7,                 // library default 7
  luminanceInfluence: 0.6,  // library default 0.7
  radius: 0.09,             // library default 0.1825 — a scale relative to resolution, range [1e-6, 1]
  intensity: 1.8,           // library default 1.0
  bias: 0.03,               // library default 0.025 — kills depth-discontinuity artifacts
  fade: 0.015,              // library default 0.01 — lower = higher contrast shadows
  resolutionScale: 0.5,     // MUST match the downsampled normal/depth buffer
  worldDistanceThreshold: 120, worldDistanceFalloff: 20,
  worldProximityThreshold: 6,  worldProximityFalloff: 2,
});

const bloomSelection = new Selection();   // layer-bound; scene-wide bloom is FORBIDDEN
const bloom = new SelectiveBloomEffect(scene, camera, {
  blendFunction: BlendFunction.SCREEN,
  mipmapBlur: true,        // kernelSize / resolutionScale on BloomEffect are DEPRECATED
  levels: 8,
  radius: 0.85,
  intensity: 0.7,
  luminanceThreshold: 1.0, // NEVER lower this to make something glow — raise emissiveIntensity
  luminanceSmoothing: 0.03,
});

const tone = new ToneMappingEffect({ mode: ToneMappingMode.AGX });
// ToneMappingEffect DEFAULTS TO ACES_FILMIC; AgX must be selected explicitly.
const smaa = new SMAAEffect({ preset: SMAAPreset.ULTRA, edgeDetectionMode: EdgeDetectionMode.COLOR });
// SMAAEffect DEFAULTS TO MEDIUM. ULTRA because our dominant geometry is long diagonal cable runs —
// exactly where low SMAA presets stair-step. COLOR detection (also the library default) is right
// here because many of our edges are colour boundaries on coplanar surfaces (severity bands, bezel
// glyphs, selection outlines) that carry no depth discontinuity and DEPTH detection would miss.

composer.addPass(new RenderPass(scene, camera));
composer.addPass(normalPass);
composer.addPass(depthDown);
composer.addPass(new EffectPass(camera, ssao));
composer.addPass(new EffectPass(camera, bloom));
composer.addPass(new EffectPass(camera, tone, smaa));   // merged into ONE shader by EffectPass
```

Order rationale: SSAO runs while a clean normal/depth buffer exists and **before** anything adds
glow, or bloom bleeds into the occlusion. Bloom runs on **HDR linear** values, which is the only way
`luminanceThreshold: 1.0` means anything. Tone mapping runs **once, last**, on the whole image.

> **INFERRED, flagged, and required to be A/B'd:** placing SMAA *after* `ToneMappingEffect` inside
> the final merged `EffectPass`. The sources say "tone mapping last" and "SSAO before
> anti-aliasing" but never adjudicate SMAA-vs-tone-mapping directly. The argument for this order is
> that SMAA is a perceptual edge filter tuned for display-referred input and mis-detects edges on
> unbounded HDR values. **Build both orders, capture both, and record the choice with its evidence
> in `docs/render-decisions.md`.** Do not ship the inferred order as settled.

A unit test snapshots `composer.passes.map(p => p.constructor.name)` plus the effect class names
inside each `EffectPass`, and fails on any reordering.

**Tone-mapping mode by surface:** `AGX` for the live scene — softest shoulder, and it is what keeps
a saturated `--sev-critical` red from blowing to orange-white as `emissiveIntensity` climbs.
**`NEUTRAL` for the screenshot / report export path**, where brand and severity colours must survive
unshifted. **`ACES_FILMIC` is not used anywhere:** it is the most colour-shifting of the three, and
we are rendering an evidence tool, not a film.

**Per-material `tonemapped: false` is ignored once post-processing is active** — it only works when
rendering directly to the screen. Any element that must bypass tone mapping (a legend swatch, a HUD
readout) lives in the DOM over the canvas, never as a flagged material.

### 4.7 Selection, hover and focus — three states, visually separate

The frozen contract in `src/fabric3d/contract.ts` already distinguishes selection (strong), hover
(weak) and highlight (emphasis without selection). The visual grammar:

| State | Treatment | Camera |
|---|---|---|
| **Hover** | 1.5 px `--text` rim on the chassis; the DOM label promotes to full opacity; cursor `pointer`. | **Never moves.** |
| **Selection** | 2.5 px `--accent` rim + a 44-unit translucent halo disc (`--accent` @ 9 %) on the tier plane beneath the node + the label pinned. | Moves only via `focusDevice`, and only on an explicit action (click, Enter, palette) — never on hover, never on arrow traversal of the queue. |
| **Keyboard focus in the DOM mirror** | A **pseudo focus ring drawn on the canvas**: 2 px `--focus`, 3 px offset, at the node's projected position, re-synchronised every frame. Required, because a canvas has no default focus indication. | Arrow traversal **does not fly the camera**. It pans only when the focused node would otherwise be off-screen, and then by the minimum delta. |
| **Highlight** (filter / blast radius) | Non-matching nodes drop to 35 % chassis opacity and lose labels. **They do not disappear.** | Unchanged. |
| **Blocked** (`HighlightState.blockedHost` / `blockedLink`) | 3 px `--sev-critical` rim + an octagonal stop glyph billboarded above the node + the 6 px terminal link treatment. | Unchanged; the user chooses whether to focus. |

Selection and hover are never the same colour. Selection survives hover. Hovering a different node
never clears selection.

### 4.8 Motion — every animation, its duration, its justification

Acceptance C6: nothing loops or pulses without a reason; nothing exceeds 300 ms except a deliberate
camera move.

**What a duration means here.** Every fade below is FINITE: it has an explicit start (the frame its
target changes), an explicit duration and an explicit curve, and it shows its end state — the target
itself, not a value near it — on the first frame at or after start + duration. At 60 Hz that frame
can be up to one frame (16.7 ms) after the nominal duration, so each JavaScript-stepped fade also
states the time its end state is first on screen at 60 fps, measured by stepping the real ease, and
that time is what is held under 300 ms. (Until 2026-09-22 the three JavaScript fades were
EXPONENTIAL — `k = min(1, dt / RECEDE_MS); cur += (tgt - cur) * k` — so their "durations" were time
constants: measured, the recession settled at 1,350 ms, the hover rim at ~417 ms and the halo at
~917 ms. The ease owner is now `src/fabric3d/emphasis.ts`, and `src/core/motion-inventory.test.ts`
parses `src/` and fails on an exponential step anywhere, and steps each ease against its row here.)

| Animation | Duration | Easing | Justification |
|---|---|---|---|
| Camera tween (`focusDevice`, `resetCamera`; `CAMERA_TWEEN_MS` in `src/fabric3d/camera.ts`) | **620 ms** — the constant the tween divides by. `--dur-camera` in tokens.css states the same figure, but no stylesheet uses it | `cubic-bezier(0.16, 1, 0.3, 1)` | The one deliberate exception. Exempt from the 300 ms bar: a deliberate camera move, the exception acceptance C6 itself names. A cut between camera poses destroys the spatial model; 620 ms is long enough to follow and short enough not to be waited on. Under reduced motion: the camera jumps to its target pose in one frame. |
| Orbit / pan inertia (OrbitControls `dampingFactor`, set in `src/fabric3d/camera.ts`) | No fixed duration: factor **0.085** — each frame keeps 91.5 % of the previous frame's motion, so the tail's length scales with the gesture | exponential, per frame | The pointer's own inertia; keyboard orbit and pan drive the same handlers, so they share it (D1). Exempt from the 300 ms bar: it is the tail of a camera move the user made (C6: "deliberate camera moves"). Under reduced motion: `enableDamping` is off — no tail, the move lands whole. |
| Selection rim + halo fade-in (`SELECT_MS`, `SELECT_EASE` in `src/fabric3d/emphasis.ts`) | **140 ms** (`--dur-fast`); end state first on screen — settles in **150 ms** at 60 fps (9 frames) | `--ease-out` | Acknowledgement of a click. The rim rides the halo's ease, so the two land together. Under reduced motion: lands on its target in the frame the selection changes. |
| Hover rim (`HOVER_MS`, `HOVER_EASE`) | **80 ms** (`--dur-instant`); settles in **83.4 ms** at 60 fps (5 frames) | linear | Must feel like a cursor property, not a transition. Under reduced motion: lands on its target in the frame the hover changes. |
| Dim / undim on filter change (`RECEDE_MS`, `RECEDE_EASE`) | **240 ms** (`--dur-medium`); settles in **250 ms** at 60 fps (15 frames) | `--ease-out` | Long enough to see *which* nodes left the set. Devices, cable segments, state rings and role glyphs recede on this one ease. Under reduced motion: lands on its target in the frame the subject changes. |
| Trace path draw-on (`DRAW_ON_MS`, `src/fabric3d/flow.ts`) | **240 ms** total — ONE reveal along the whole path, whatever the hop count. There is no per-hop stagger | ease-out cubic, `1 − (1 − t)³`, computed in script | The head of the path moves fastest at the start, which is what makes the hop ORDER legible rather than just the path's existence. (Until 2026-09-23 this row promised a per-hop stagger; `flow.ts` has never had one.) Trigger: it runs once per new trace — a trace the overlay is not already drawing — and on nothing else. A hop step re-runs nothing: the shell re-sends the trace on every hop change, and the overlay treats the trace it is already drawing as a no-op (`flow.ts` TRIGGER; `scene.ts` `setTrace` also skips the camera framing for it). Under reduced motion: the path draws instantly and fully. |
| Trace packet marker (`PACKET_LOOP_MS`, `PACKET_LOOPS` in `src/fabric3d/flow.ts`) | **1600 ms** per loop, one marker, stops after `PACKET_LOOPS` = 3 loops and leaves the path drawn | linear | The only looping animation in the product, and it is bounded. Exempt from the 300 ms bar: a bounded loop whose job is to distinguish a live trace overlay from a static path screenshot. Trigger: one run per new trace, and on nothing else. A hop step (`]` / `[`, a hop-list row) restarts nothing and extends nothing: the run keeps its original start, and once it is over a hop step owes no frame. Until 2026-10-03 every hop step re-armed the draw-on and all three loops — stepping hops kept this loop running indefinitely — and a hop step was said to steer the packet's "resting position", which was overwritten on the next frame and hidden after the loops, so it was never on screen. The overlay now draws nothing per hop: the active hop is shown by the selection the shell re-aims to its host (acceptance A4) and by the hop list. An explicit re-run builds a new trace and runs once more. Exercised on the shipped snapshot: the multi-hop presets (for example TCP/22 from 10.0.40.0/24 to 10.0.10.0/24, dist1 then core1) draw a path and run the packet, and the acceptance re-grade measured the canvas still once the third loop ended. (No stylesheet declares an unbounded loop: the unrendered stage-pending spinner App.css used to declare was dead CSS and is deleted — open-issues O18.) Under reduced motion: the packet does not run at all. |
| Quality-tier cross-fade (`TIER_FADE_MS`, `createTierFadeDriver` in `src/fabric3d/emphasis.ts`, wired by `src/fabric3d/scene.ts`) | **280 ms** opacity, started when the hold in the next row ends; settles in **283.4 ms** at 60 fps (17 frames). FRAME-STEPPED, at most 0.2 opacity per frame | `ease-in-out`, stepped in script on each frame's real duration (never a CSS transition) | A tier change (manual or the automatic step-down) swaps SMAA, SSAO and outlines in one frame — a measured 3.6 % canvas pop. The old tier's frame is held over the canvas and faded out. 280 ms, not 300: a 300 ms transition MEASURED 299.9–300.1 ms (acceptance grading, C6) — at the ceiling, not under it — and a transition's end state can land up to one 60 Hz frame after its duration, so 280 + 16.7 stays under 300. **Owner decision (C5, 2026-09-26): the fade is frame-stepped with a per-frame cap, and the cap wins.** The render loop steps it through the ease owner's driver on each frame's real duration, and no frame — including the one after a host stall or a returning tab — moves the overlay's opacity by more than `FADE_MAX_STEP` = 0.2; the overlay is removed on the frame its value reaches exactly 0, and a no-frames watchdog of two `maxHoldMs` windows removes it if frames stop arriving. The old CSS transition was wall-clock: one 116.6 ms host frame moved it 0.36 at once, a cut. On ordinary frames the cap never binds (a frame under 33 ms never engages it) and the fade IS the 280 ms ease-in-out. On a host stall it binds, and the fade can run past 300 ms on the wall clock — modelled at 60 Hz, it adds at most 1, 2 or 4 frames for an 83–100, 116–133 or 200–250 ms stall, and the uncapped wall-clock fade already reached 300 ms on one 50 ms frame among its last. So `review/capture-motion.mjs` judges the product's 300 ms on ordinary frames, and a fade with a host stall inside it (a frame over 25 ms, one missed vsync) may run past 300 ms only if every frame from 300 ms on ends the fade or moves the full 0.2: catching up passes, dawdling fails. A tier change that lands while a fade is running must not remove the half-faded overlay in one frame; at the time of this decision it still did, outside the driver (`docs/open-issues.md` O57). Since phase 3.5 the slot is a class with ES-private state, so no copy of one of its methods can remove the overlay behind the driver's back, and the phase-3.5 laboratory motion run passed its "handed over, never cut" item (open-issues R123, O57). Under reduced motion: no fade for an overlay that has been up under reduced motion throughout — the held frame is removed in one step on the new tier's first frame (a swap, not an animation); an overlay shown under full motion when reduced motion turns on (held, waiting or composed) finishes at `FADE_MAX_STEP` per frame, never in one step. |
| Quality-tier cross-fade HOLD — the wait before that fade starts (`TIER_FADE_HOLD_DEFAULTS.maxHoldMs`, `createTierFadeHold` in `src/fabric3d/stepdown.ts`) | **1200 ms** at most, counted from the new tier's first presented frame, and ONLY while the camera and the content are exactly as in the frame the held picture was taken from. The first frame on which the camera moves or the content changes ends it | none (a hold, not a curve) | The fade waits for the new tier's frames to be ordinary ones (three frames under 40 ms), because a heavy frame just after the swap swallowed a fade started at once — measured low → high, one 210 ms frame took the overlay from 0.94 to 0.056, a cut. A hold, not an animation: nothing moves while it holds, so the 300 ms bar that governs the fade does not govern it — its bound does, and `src/core/motion-inventory.test.ts` holds this row to the code's. It holds only over a still view, where the held picture IS the current view at the previous tier, and it never holds over a camera move or a content change: that was the C5 defect of 2026-09-23 (an automatic step-down mid-orbit on a contended host held a frozen frame at full opacity for about 1,000 ms while the camera kept moving, then released it as a 6.08× one-frame change). The automatic step-down also lands only with the camera at rest, never mid-motion — the new tier's re-warm-up presents nothing until it ends, so a mid-orbit landing froze the view for ~600 ms-1 s — so this hold, and the re-warm-up before it, are over a still view unless the reader starts moving during them; a caller-made tier change (`setQuality`) is not deferred. Under reduced motion: no hold — the held frame is removed in one step on the new tier's first frame. |
| Hover / active tint on controls and rows (`.ui-btn`, `.palette__row`, `.ag__row--data`, `.pt-preset__btn`, `.hop__head`) | **80 ms** (`--dur-instant`) on background-color, background and color; the palette row also eases its box-shadow (its inset active marker) | linear | A hover is a cursor property, not an event. This is the command palette's ONLY motion: the palette itself opens without animating (an earlier row here claimed a palette transition that the code has never had). Under reduced motion: `--dur-instant` collapses to 1 ms (tokens.css). |
| Column-resizer rule (`.ag__resizer::after`) | **80 ms** (`--dur-instant`) opacity, on hover | linear | Reveals the drag handle only where the pointer is. Under reduced motion: `--dur-instant` collapses to 1 ms. |
| Fabric DOM labels (`.fabric3d-label`) | **80 ms** (`--dur-instant`) opacity | linear | A label promoting to full opacity on hover (§4.7) or dropping out at the dolly threshold must not pop. Under reduced motion: the token collapses to 1 ms and Fabric3D.css also sets `transition-duration: 1ms` on the label directly. |
| Trace-set progress bar (`.pt-progress__fill`) | **80 ms** (`--dur-instant`) inline-size | linear | Smooths each step of "N / M flows" so progress reads as progress, not flicker. Under reduced motion: `--dur-instant` collapses to 1 ms. |
| Skip link (`.skip-link`) | **140 ms** (`--dur-fast`) top, sliding in on keyboard focus | `--ease-out` | The first Tab stop must be seen arriving. Under reduced motion: `--dur-fast` collapses to 1 ms. |
| Switch (`.ui-switch__track`, `.ui-switch__knob`) | **140 ms** (`--dur-fast`) — background-color on the track, transform on the knob | `--ease-out` | Knob position is the non-colour channel of the state; the move makes the change legible. Under reduced motion: `--dur-fast` collapses to 1 ms. |
| Disclosure chevron (`.ui-disclosure__chev`) | **140 ms** (`--dur-fast`) transform (a 90° rotation) | `--ease-out` | Ties the open state to the control that caused it. Under reduced motion: `--dur-fast` collapses to 1 ms. |
| Narrow-layout evidence drawer (`.rail--b`, `.app[data-drawer="open"] .rail--b`) | **240 ms** (`--dur-medium`) transform; visibility flips at 0 ms on open and after the **240 ms** slide on close | `--ease-out` for the transform, linear for the visibility step | Below 80 rem the evidence rail becomes a drawer over the stage; the slide shows where it came from. The delayed visibility is for the picture only: since the D3 owner decision of 2026-09-26 the closing drawer is `inert` from the commit that closes it (`useReleaseFocusOnHide`, `src/app/focus-return.ts`, which releases focus first and then sets `inert`), so neither Tab nor a `focus()` call can re-enter it during its 240 ms slide; before that, Tab walked back into a drawer still sliding shut (§7.1). Under reduced motion: `--dur-medium` collapses to 1 ms. |

**`prefers-reduced-motion: reduce` — the contract:** `--dur-instant/fast/medium/camera` all collapse
to `1ms` (already implemented in `tokens.css`); the camera **jumps** to its target pose; the trace
draws instantly and fully; the packet marker **does not run at all**; the recession, hover-rim and
selection eases land on their targets in the frame their target changes; the tier cross-fade
becomes a one-frame swap. The end state is byte-identical
to the animated end state. **The reduced-motion path never shows less information, only less
movement.**

### 4.9 The explicit list of cheap-looking things we will not do

Each item is a named failure mode from the research or from acceptance C5, and each is a checklist
item a critic will be asked to test one by one:

1. **No `LineBasicMaterial` links.** `linewidth > 1` is silently ignored; hairlines are tell #1.
2. **No aliased edges.** SMAA `ULTRA` with `EdgeDetectionMode.COLOR` in the chain — not
   `antialias: true` on the renderer, which is discarded the moment `RenderPass` writes offscreen.
3. **No `UnsignedByteType` composer buffers.** They band visibly on `#0a0d13` and clip emissive at
   1.0, leaving bloom nothing to threshold.
4. **No global bloom and no `luminanceThreshold` below 1.0.** Glow is layer-bound and *means*
   "this element is emitting" — it is information, not atmosphere.
5. **No double gamma, no double tone map.** Renderer stays `NoToneMapping`; exactly one
   `ToneMappingEffect`, last.
6. **No `0x000000` background.** `--stage-bg` is `#0a0d13` / `#eef1f5`, a real surface.
7. **No uniform ambient light.** One directional key + a PMREM environment. No `AmbientLight`
   flattening everything to one value.
8. **No pile of point lights.** Environment maps render faster than several per-frame lights and
   produce the grazing-angle reflection that makes metal read as metal.
9. **No `roughness: 0` and no mid `metalness`.** Neither exists in a real material.
10. **No z-fighting.** Tier plates are `depthWrite: false` at 4 % and offset 0.02 units below the
    chassis plane; coplanar geometry is eliminated at authoring time, not fought with `polygonOffset`.
11. **No popping LOD.** Labels drop by *count* at a fixed dolly threshold with 0.06 hysteresis.
    Geometry has no LOD at 26 nodes.
12. **No uncapped `devicePixelRatio`.** `Math.min(dpr, 2)`. Internal render scale (1.0 / 0.85 / 0.75)
    is a **separate** adaptive-quality knob, never conflated with DPR.
13. **No force-directed jiggle, no idle camera drift, no breathing nodes, no pulsing halos.**
14. **No `Math.random()` or `Date.now()` anywhere on a render path** (acceptance F6).
15. **No hidden off-path topology.** Dim to 55 %; never remove.
16. **No decorative particle field, volumetric fog, lens flare, chromatic aberration, vignette or
    film grain.** Every one is a demo tell in a tool whose job is to be read.
17. **No `logarithmicDepthBuffer`** as a reflex; tighten `camera.near` instead.
18. **No negatively-scaled matrices** in any instanced or batched transform (explicitly unsupported
    by `BatchedMesh.setMatrixAt`).
19. **No height-encoded metrics on the chassis.** A taller box reads as a bar chart and invites a
    comparison the data does not support.
20. **No colour-only state.** All four semantic channels of §3.3 carry a second channel on the canvas
    too: dash pattern, rim thickness, glyph, or hatching.

---

## 5. Investigation flows

### 5.1 Flow A — priority → device → finding → configuration evidence

Acceptance A1 requires configuration evidence in **≤ 3 interactions with no topology reset**. This
flow costs **exactly 3**.

**State 0 — arrival.** `#rail-queue` holds the findings APG grid, grouped by `severity`, ordered by
`priority` then `rank`. Group headers read `Critical · 3`, `High · 104`, `Medium · 33`, `Low · 6`,
and — critically — **`Info · 0` renders; it is not hidden.** An empty group is a positive statement
("zero findings at this severity in this scope"); hiding it converts that statement into silence.
The display-options popover exposes `Show empty groups`, **defaulted ON**, which is where we
deliberately diverge from Linear's default, for coverage honesty.

Row anatomy — a single-line CSS grid with fixed leading/trailing tracks and one flexible middle
track, so identifiers and metadata align into true vertical columns down the whole list:

```
[sev glyph 24px][mono id 40px][ title — 1fr, single line, ellipsis ][category 88px][devices 72px][inspect 24px]
       ^              ^                     ^                            ^              ^             ^
  shape+colour    F001, muted        never wraps, never           Compound risk      core1        DEDICATED
  (never colour   tabular-nums       truncated below 32ch                            +2 more      drill glyph
   alone)                                                                                         NOT a row click
```

Severity glyph set (shape, so the encoding survives greyscale and colour-vision deficiency):
Critical = filled octagon · High = filled triangle · Medium = filled square rotated 45 degrees ·
Low = filled circle · Info = hollow circle · **absent/unknown = a dashed hollow circle**, never a
blank cell.

Row click selects. **Drill-down is the dedicated glyph at the right edge.** That separation is what
keeps a dense grid safely explorable: you can select, compare and multi-select without being
teleported somewhere else.

**Interaction 1 — select a finding.** `ArrowDown`/`ArrowUp` moves grid focus; `Enter` or click
selects. This writes `findingId` to the store, and **four things re-aim simultaneously with nothing
blanking** (acceptance A4):

- `#rail-queue` keeps its scroll offset and its selection highlight.
- `#stage` applies `setHighlight({ hosts: finding.devices, ... })`: the named devices lift to full
  opacity, everything else drops to 35 %. **The camera does not move.**
- `#rail-evidence` switches to the `findings` tab and renders the full record — title, `detail`,
  `remediation`, `category`, `wave`, `rank`, `priority` — and the `cite` string (`punchlist[0]`) as
  a **clickable monospace token**.
- `#status-bar` shows the scope readout: `146 findings · 1 selected · 146 of 146 shown`.

**Interaction 2 — select the device.** From the evidence pane's device chip (`core1`), or by
pressing `D`. This writes `deviceId`, and:

- `#stage` calls `focusDevice("core1")` — a 620 ms camera tween, the selection rim, the halo. The
  fabric does not re-layout and the scene is not re-instantiated.
- `#rail-evidence` switches to `summary` and shows the `Device` record. **Every `null` renders as
  the literal token `not observed`, in `--claim-indeterminate` — never as an em dash, never as `0`,
  never as an empty cell, never omitted.** For `AP-floor1` that is eleven `not observed` rows
  (platform, model, serial, swVersion, uptime, powerSupplies, modules, score, band, criticality,
  dataQuality) plus the `uncollected` badge and the citation `cable_map.nodes[host=AP-floor1]`.
- The `acl` tab is enabled only for the 1 host with ACLs; `routing` only for the 2 hosts with RIBs.
  **A disabled tab still renders, with its reason on it** — `Routing · no RIB collected` — because a
  *missing* tab reads as "nothing to see here", while a *labelled disabled* tab reads as "we did not
  collect this."

**Interaction 3 — open the configuration evidence.** Click the citation token, or press `V`. A
right-side overlay opens at 48 % of window width (691 px at 1440), layered over the Stage with the
Stage still visible at reduced contrast. **Not a modal.** Anatomy, taken directly from Forward:

- **Header:** `core1` plus a close affordance top-right, and a bottom-left `Close` button — two
  dismissal affordances covering both mouse-position conventions. `Esc` also closes, and returns
  focus to the citation token that opened it.
- **Toolbar:** a search input labelled with the **real** record size (`Search 41 lines`), and a
  `Copy citation` button.
- **Body:** the **actual source record** at `cite`, rendered with a **true index gutter** — for an
  ACL that means the real `AclLine.index` values, never a 1-based renumbering of the excerpt.
  Matching lines carry an olive highlight band. Elided regions render as a full-width bar stating
  the **exact count**: `12 lines hidden`. A `1 matching range` badge and a thin right-edge minimap
  locate the excerpt within the whole record.
- **Footer:** the snapshot binding —
  `sample_fleet.snapshot.json · sha256 9cc348bd... · collected 2026-08-07`.

> **Why true indices and counted elision.** Three lines of config prove nothing — a reader cannot
> tell whether context was cherry-picked. "Line 18 of 41, with 12 lines hidden above it" is
> auditable; a floating snippet is not.

**The active filter chips travel into every drill-down.** If the queue was filtered to
`severity = Critical` when the finding was opened, that chip renders at the top of the evidence pane
and of the config overlay, so the detail reads "1 of 1 under these filters" rather than as an
unqualified claim about the device.

**Per-finding evidence pointers — the rendering contract (decided 2026-09-26, phase 2 of the
single-source-of-truth program; not rendered until phase 3 — RENDERED since phases 3 and 3.5, below).** The engine now publishes, on
every punch-list row, `evidence_basis` (`record` / `row` / `absence`), `evidence_refs` (elements
`{kind, host, ref, role, cite}`, where `ref` is an RFC 6901 pointer into the SAME snapshot) and, only
when the list is capped, `evidence_refs_total`; the compiler carries them onto the finding as
`evidenceBasis`, `evidenceRefs` and `evidenceRefsTotal`, beside `severityBasis` and
`evidenceConfidence`. The pane that renders them obeys these rules:
- It renders by `evidence_basis` **and** each ref's `kind` and `role` — never by the basis alone and
  never by matching words. A row's `record` basis does not make every ref on it configuration: a
  CL-02 row is `record` through its interface refs, and those refs are `role: derived_from` links to
  the graph cut, not configuration, so they are never presented as the configuration behind the
  finding.
- `health_scores` `deduction_refs` pair with deductions by pointer and cite, never by index: the list
  is a subsequence, not one ref per deduction.
- `severityBasis` and `evidenceConfidence` are the producer's words VERBATIM — even `N/A`, `-` or an
  empty string — and are disclosures, never measurements; null means the key was not emitted.
- A capped list (`evidenceRefsTotal` greater than the number of refs) never reads as complete; a null
  `evidenceRefs` means "not emitted", never "no evidence".
- A ref resolves to a NON-NULL value in the compiled source or the compile refuses it
  (`E_EVIDENCE_REF_UNRESOLVED`): citing a present key that holds null would render absence as a
  record. Refs point at records (`/interfaces/<host>/<port>`), not at sparsifiable fields the engine's
  on-disk writer may drop, and no ref indexes a list a published consumer re-filters (the explorer
  embed re-filters `physical_health`).
Acceptance A1 does not move until these are rendered and re-graded (`docs/open-issues.md` O12, O50).

**As rendered (phases 3 and 3.5, 2026-09-30; open-issues R120).** Step 3 of the chain, "What the engine
points at", lists the engine's refs in the engine's order, and each section heading counts every ref the
engine names, saying how many are shown when a fold hides some (F142: "Absence, witnessed by 20 records (7
shown)"). The pane's header carries one control per engine-named record, in the engine's order, never
folded, in a header that does not scroll with the pane body; activating one lists that record in step 3
even past the fold, opens it there — the compiled interface, ACL or route record, the record's members, or
its verbatim text — scrolls it to the top of the body and moves focus to it, and leaves the topology
untouched. Word-matched records open only in step 5, as context. A projected text cut never ends inside a
citation: when the cut text holds no delimiter at all, none of the cut token is shown and the sentence
says so. The compiled projection (`fabric.evidenceRecords`) is bounded as WRITTEN:
`evidenceProjection.totalChars` covers the whole array — every withheld record's pointer-only stub, its
brackets and separating commas (`writtenChars` = `projectedChars` + `withheldChars` + n + 1) — stubs are
reserved first, and full records are admitted in the engine's priority order (finding priority, then
punch-list order, each finding's pointers in the engine's order), so a lower-ranked record never
displaces a higher-ranked one; when the stubs alone exceed the total, every record is withheld and
`writtenChars` above `totalChars` says so. Known limit: the header grows with the number of records a
finding names — up to about 512 px on this sample — and at 1280×720 it leaves too little body for A1
(open-issues O72).

### 5.2 Flow B — path question → blocking-hop explanation

**Step 1 — ask.** The query bar accepts a `Flow`. Progressive disclosure: a protocol of `tcp` or
`udp` reveals `dstPort` and `srcPort`; `icmp` and `ip` do not. Placeholders teach syntax rather than
restating the label (`srcIp` gets `e.g. 10.20.10.5`). Submit with `Enter` or `Ctrl+Enter`.

**Step 2 — the question becomes tokens, and stays.** On run, the form collapses into a horizontal
**token bar** directly under the header, persistent for the entire investigation. Each token is a
chip with a dim 11 px uppercase key on line 1 and the value on line 2, plus an inline remove
affordance:

```
+-----------++-----------++--------++--------++--------------+   x   search   [ Ignore ACLs ]  [ Save view ]
| SRC       || DST       || PROTO  || DPORT  || SCOPE        |
| 10.20.10.5|| 10.30.40.9|| tcp    || 443    || core1, core2 |
+-------- x-++-------- x-++----- x-++----- x-++--- (fixed) --+
```

Removing one chip re-runs immediately with that dimension dropped. **The SCOPE chip is not
removable** — it names the 2 hosts whose RIBs we hold, and it is the boundary of the claim. A
removable scope chip would let a user delete the honesty.

**Step 3 — `#rail-path` appears** above the queue, which shrinks to 40 % and **keeps its scroll
offset; it does not unmount.** The hop tree:

```
v core1  (source)                                          <- 28px row; tier group + role suffix
  |  Route:  10.30.40.0/24 via 10.0.0.2 (ospf, AD 110)     <- 18px key:value sub-line
  |  Out:    Gi0/1                                            NO CLICK REQUIRED — the answer
  |  ACL:    MGMT_IN line 7 - deny tcp any host 10.30.40.9     is already on the row
  |  cite:   acls.core1.MGMT_IN[7]                         <- monospace, clickable
  v  [STOP] denied                                         <- terminal verdict row: glyph + word
> core2  (not on path)
o Return path                                              <- collapsed, ALWAYS-present peer section
```

Sub-lines render **without a click**. Keys are `--fs-0` / `--text-faint`; values are `--fs-1` /
`--text`, aligned on one tab stop per section. The ACL value is the **rule name plus line index**,
never a bare index.

**Step 4 — the fabric draws the path on itself, not beside itself.** `setTrace(trace, activeHop)`
paints the 4 px `--accent` polyline (a new trace only: re-sent with another `activeHop`, the trace
already drawn changes nothing on the canvas — the active hop is the selection the shell re-aims to
its host, §4.8) with arrowheads over the already-mounted scene. On-path nodes
take the selection rim; off-path nodes and links dim to 55 %. The blocking hop takes the 3 px
`--sev-critical` rim, the stop glyph, and the 6 px terminal link. **The scene is never rebuilt** —
`setTrace` is a state overlay onto instantiated geometry, and camera, zoom and selection all survive
it.

**Step 5 — per-hop evidence.** Selecting a hop (`ArrowDown` in the tree, or a click) writes
`hopIndex` and fills `#rail-evidence` with the `Hop` record: `decidedBy` **first and visually
heaviest**, then `evidence[]` in evaluation order, then `alternatives[]` under the heading
**"Routes considered and beaten"** — which answers the question most tools drop entirely: *why not
that one*. Each `HopEvidence.raw` string is shown verbatim with its `cite`.

**Step 6 — the counterfactual, offered in-panel at the moment it is relevant.** When a trace
terminates in `denied`, an amber banner appears at the top of `#rail-path`, worded as what it will
do rather than as what it is called:

> **Re-run with every ACL treated as permit.** This separates "the route is broken" from "the route
> is fine and policy is dropping it."

Activating it adds a `MODE · ignore acls` chip to the token bar — visible, removable, carried in the
shareable URL — and re-runs **without re-asking a single flow parameter**. In the re-run, **every
rule that would have acted keeps its row**, rendered with strikethrough at 60 % opacity, annotated
inline `deny (ignored in permit-all mode)`, and its hop carries an amber sub-label
`ACL rules ignored`. Deleting the ignored rule instead of striking it would teach the user that the
path "works" and hide that a blocker still stands.

**Step 7 — counterexample.** Acceptance B8: where a flow is denied, the UI offers the **nearest flow
that would succeed**, computed by relaxing exactly one field of the five-tuple against the same ACL,
rendered as a one-click chip: `Try dport 22 — permitted by MGMT_IN line 3`. If no such flow exists
within the modelled scope, **the affordance says so explicitly rather than disappearing.** A vanished
affordance reads as "there is nothing to try"; a present one that says "no relaxation of a single
field is permitted by this ACL" is a finding.

**Step 8 — scope, permanently, never collapsible:**

> Scope: forwarding modelled on **core1, core2** (2 of 26 hosts with a collected RIB). ACL
> evaluation modelled on **core1** (1 of 26). Hops through the other 24 hosts are **not modelled**
> and are reported as `unmodeled`, not as forwarded.

### 5.3 The inspector (Grafana's contribution)

Bottom-docked over the Stage, 40 % of stage height by default, drag-resizable 200 px to 80 %, height
persisted in `localStorage` — **not in the URL**. Opening or closing it never re-runs anything. Five
tabs, fixed order, the fifth conditional:

| Tab | Contents |
|---|---|
| **Claim** | The generated claim sentence (section 6) plus the scope tuple as editable chips. |
| **Query** | The literal `Flow` object and the resolved scope, as a collapsible JSON tree, with `Copy`. |
| **Data** | The raw records the verdict rests on, as a real sortable table: `RouteEntry[]` considered, `AclLine[]` evaluated, per-hop `HopEvidence[]`. `Download CSV` exports **exactly what is displayed** after the current frame selection and toggles — never a silent full-dataset substitution. |
| **Raw** | The raw snapshot record at the active `cite`, resolved by walking the dotted path into the source. This is what makes acceptance B6 checkable. |
| **Error** | **Rendered only when the run produced an error**, and **auto-selected on open** when present. |

**Three visually distinct result states, and the failed state can never look like the empty one:**

1. **FAILED** — the trace threw, or a citation did not resolve. The Error tab appears and is
   selected; the result area shows an error state carrying the verbatim error string, never empty
   axes.
2. **INDETERMINATE / PARTIAL** — the engine returned `indeterminate` or `out-of-scope`, or some hops
   are `unmodeled`. The successful hops render **and** a non-dismissable banner names the unmodelled
   hosts.
3. **EMPTY SUCCESS** — the query ran and legitimately returned zero rows. A distinct "No rows" state
   whose copy states that the query **succeeded** and returned 0 rows, echoing the scope it ran over.

> Grafana itself has shipped the bug where a failed query renders as an empty chart
> (`grafana/grafana#33273`, the lost red error bar for SQL errors). That is the cautionary case, not
> the model. In an evidence tool, rendering failure as emptiness converts "I could not check" into
> "there is nothing wrong", which is the worst defect available to us.

### 5.4 URL and view state — the deliberate split

| Goes in the URL (it is evidence) | Goes in `localStorage` (it is preference) |
|---|---|
| `deviceId`, `linkId`, `findingId`, `hopIndex` | Inspector height, Rail A splitter position |
| The full `Flow` and the `ignore acls` mode flag | Which evidence tab was last open |
| `query`, `severities`, `roles`, `onlyUncollected` | Theme override, quality-tier override |
| `evidenceTab` when reached by an explicit action | Column visibility, group collapse state |
| The snapshot sha256, so a stale link is detectable | Display-options popover state |

Rationale, and it is load-bearing: **if furniture rode in the evidence link, two people opening the
same URL would receive "different" investigations that are actually identical**, and the URL would
stop being a clean reproduction key. A `schemaVersion` integer is carried; a reader that sees an
unknown version **refuses to parse and says so**, rather than silently mis-reconstructing a state
that then looks successful.

URL writes are debounced 300 ms and use `history.replaceState` for in-progress edits,
`history.pushState` for committed actions (run, selection change, mode toggle), so browser Back
traverses investigative steps rather than keystrokes.

---

## 6. Claim honesty

### 6.1 What we adopt from Batfish — and, importantly, what we do not

Batfish's central mechanism is the **exhaustive counterexample search**: a claim is stated as a
search for its own negation over a declared header space, and an empty result is a *proof* bounded
by that space.

**We cannot do that here, and we will not pretend to.** We hold RIBs for 2 hosts and ACLs for 1.
There is no exhaustive search over a modelled network — there is a traversal over a partial one.
Adopting Batfish's strong vocabulary on top of that would be the exact overclaim this section
exists to prevent. So:

| Batfish element | Our adoption |
|---|---|
| Two-part change contract (intended effect AND absence of unintended effect) | **Adopted in structure** wherever a counterfactual runs (5.2 step 6): the permit-all re-run is the second slot, and both slots render independently. Neither alone renders as success. |
| Empty result = proof | **REJECTED as written.** A clean result from our engine is *observed*, never *proven*. Our strongest possible sentence is "no counterexample was found **within the 2 hosts modelled**" — a sentence that names its own denominator. |
| The scope tuple as a first-class, always-rendered object | **Adopted wholesale.** This is the single most valuable transferable idea in the whole reference set for us. |
| A sample path is labelled a sample and cannot close a claim | **Adopted wholesale.** |
| A closed disposition vocabulary with an undetermined band never folded into success or failure | **Adopted, but mapped onto our own enums.** We do **not** import Batfish's 10 dispositions: our engine does not model six of them (no MAC tables, no NAT, no multicast, no ARP-level neighbour resolution). Importing a vocabulary we cannot compute would itself be an overclaim. |
| A fixed claim-sentence grammar with reserved words | **Adopted wholesale, and mechanically enforced.** |
| A parse-ledger / model-limit surface as a permanent denominator | **Adopted**, realised as `fabric.coverage` in the status bar and on every verdict. |

Our disposition vocabulary is exactly the union of `HopVerdict` and `TraceOutcome`, already frozen
in `src/core/types.ts`:

```
HopVerdict:    forwarded · delivered · no-route · denied · unmodeled · loop · ttl-exceeded
TraceOutcome:  delivered · dropped · denied · indeterminate · out-of-scope
```

Banded into three, and **the third band is as visually loud as failure, never greyed out**:

- **RESOLVED** — `delivered`, `forwarded`
- **REFUTED** — `dropped`, `denied`, `no-route`, `loop`, `ttl-exceeded`
- **UNDETERMINED** — `indeterminate`, `out-of-scope`, `unmodeled`

Greying out `indeterminate` reads as "not applicable". It means "the model could not decide", which
is a finding, not an omission. It gets `--claim-indeterminate` — a violet, deliberately neither red
nor green nor grey — and its own count in every summary and every roll-up.

### 6.2 Reserved-word grammar — mechanically enforced

Verdict prose is **generated from templates**. No human writes verdict text, and no surface renders
a strong word from a weak result.

**Strong words — emitted ONLY when the traversal completed with zero `unmodeled` hops, zero
indeterminate evidence items, and every host on the path inside `coverage.routableHosts`:**
`no counterexample was found`, `within this scope, every`, `bounded`, `complete within`.

**Weak words — emitted for everything else:** `observed`, `this flow`, `some traffic`,
`not modelled`, `not observed`, `could not be determined`, `stops here`.

**Forbidden everywhere, in every surface, unconditionally, regardless of result strength:**
`proven`, `guaranteed`, `all traffic`, `verified`, `safe`, `healthy`, `clean`, `no issues`,
`fine`, `OK`, `passing`, `all clear`. **A lint rule greps the rendered string table for these and
fails the build.** Honesty that depends on author discipline is not honesty; it is a hope.

### 6.3 Literal templates

Implement these verbatim as pure functions in `src/core/claims.ts`.

> **STATUS, 2026-09-21: ALREADY IMPLEMENTED.** `src/core/claims.ts` exists, is covered by
> `src/core/claims.test.ts` against real `traceFlow` output, and is enforced by
> `src/core/claim-lint.test.ts`, which scans every source file's user-visible strings each test run.
> Import from it. Do not rewrite it.
 Angle brackets mark
substitutions; everything else is literal text, including punctuation.

**T1 — scoped forwarding verdict (emitted for every trace, always):**

```
<OBSERVED|SCOPED>: <flow> is <outcome> — traversed <nHops> hop(s) across <nModelled> of <nTotal>
hosts with a collected RIB; <nUnmodelled> host(s) on this path could not be modelled;
<nIndeterminate> evidence item(s) were indeterminate. Snapshot <sha8>, collected <collectedAt>.
```

Worked example against the real data:

> **OBSERVED:** tcp 10.0.10.50 -> 10.0.30.10:3389 is **denied** — traversed 1 hop across 2 of 26
> hosts with a collected RIB; 0 hosts on this path could not be modelled; 0 evidence items were
> indeterminate. Snapshot 9cc348bd, collected 2026-08-07.

> **CORRECTION, 2026-09-20.** This example originally read `10.20.10.5 -> 10.30.40.9`. Neither
> address exists in `fabric.json`: the only subnets this snapshot observed are `10.0.10.0/24`,
> `10.0.20.0/24` and `10.0.30.0/24`, and an invented example would have sent every build agent to a
> flow that returns `out-of-scope`. The substituted flow is a real one — verified by running
> `traceFlow`, which returns `denied` at `core1` on `PROTECT_SERVERS` line 3 (`deny ip any any`,
> cited `acls.core1.PROTECT_SERVERS[3]`), while the same pair on port 443 is `delivered`. That pair
> is also the product's real counterexample affordance. **Every example in this brief must be run
> before it is written down.**

**T2 — the blocking-hop sentence:**

```
Blocked at <host>, <direction> ACL <aclName> line <lineIndex>: <rawLineText>.
Cited at <cite>. This names the first rule that matched; <nAlternatives> route(s) were considered
and beaten at this hop.
```

**T3 — out of scope (source IP in no observed subnet — acceptance B4):**

```
OUT OF SCOPE: <srcIp> is not inside any subnet observed in this snapshot, so no ingress point can
be determined. This is not a statement that the flow fails; it is a statement that we cannot
evaluate it. Observed subnets: <list>.
```

**T4 — indeterminate (traversal reached a host with no RIB — acceptance B3):**

```
INDETERMINATE: forwarding could not be modelled at <host> because no routing table was collected
for it (<nRoutable> of <nTotal> hosts have one: <routableHosts>). The result above stops here.
It is NOT a delivery and NOT a drop.
```

**T5 — ACL evaluation blocked by an unevaluable line (acceptance B5; all 5 of our ACL findings are
`indeterminate`, so this template is on the hot path, not a rare edge):**

```
INDETERMINATE: ACL <aclName> on <host> could not be evaluated past line <lineIndex>
(<rawLineText>) — <reason>. Lines after <lineIndex> were not reached by this evaluation.
Cited at <cite>.
```

**T6 — counterfactual pair, intended vs unintended (5.2 step 6):**

```
INTENDED       — with ACLs enforced: <flow> is <outcomeA>.
COUNTERFACTUAL — with every ACL treated as permit: <flow> is <outcomeB>.
<nIgnored> rule(s) would have acted and are shown struck through, not removed: <ruleList>.
Clearing the ACL path requires addressing all <nIgnored>.
```

**T7 — the absence sentence, used everywhere a `null` reaches a renderer (acceptance B1):**

```
not observed
```

Exactly that string, in `--claim-indeterminate`, carrying
`title` / `aria-description` = `Not present in the snapshot. This is not a measurement of zero, and
not a statement of health.` Where the compiler preserved the engine's own reason prose
(`L3Interface.trackingUnobserved`, `L3Interface.riskUnobserved` — both already on the model),
**render that verbatim instead**, because a stated reason beats a generic placeholder.

**T8 — coverage denominator (status bar, permanent — acceptance B7):**

```
<nCollected>/<nTotal> collected · RIBs <nRoutes>/<nTotal> · ACLs <nAcls>/<nTotal> ·
link centrality <nCentrality>/<nLinks> · snapshot <sha8> <collectedAt>
```

Which renders today as: `23/26 collected · RIBs 2/26 · ACLs 1/26 · link centrality 25/44 ·
snapshot 9cc348bd 2026-08-07`. **Read from `fabric.coverage` at render time. Never hardcoded.**

**T9 — blast-radius disagreement (acceptance A6):**

```
DISAGREEMENT: our computed blast radius for <element> (<ourValue>) differs from the snapshot's own
<field> (<theirValue>). Both are shown. Neither is suppressed. Cited at <cite>.
```

Surfacing the disagreement rather than picking a winner *is* the requirement. A silently reconciled
number is an invented fact, and it is invented precisely at the point where the two sources of truth
disagree — the most load-bearing place a fabrication could land.

**T10 — the sample-path disclaimer, permanently inline on every single-flow result:**

```
This is one flow. It shows that SOME traffic behaves this way. It does not show that ALL traffic
does, and this result cannot close a claim about the flow class.
```

Carrying a primary action, `Show the scope this holds over`, which expands the scope tuple.

### 6.4 Claim-strength badge

Every verdict carries exactly one badge, and the badge is part of the copy/share payload:

| Badge | Token | Emitted when |
|---|---|---|
| `SCOPED` | `--claim-scoped` | Traversal complete, every host on the path modelled, no indeterminate evidence. **This is the strongest badge that exists in this product.** |
| `OBSERVED` | `--claim-observed` | A complete traversal that relied on partial evidence. |
| `INDETERMINATE` | `--claim-indeterminate` | Any `unmodeled` hop, any unevaluable ACL line, or a cancelled/timed-out computation. |
| `OUT OF SCOPE` | `--claim-out-of-scope` | The flow could not be entered into the model at all. |

**Copy and Share always emit the claim sentence, the scope tuple and the badge as one block.** A
verdict cannot be pasted into a ticket stripped of its bounds — that is the single most common way
an honest result becomes a dishonest quotation.

---

## 7. Keyboard and accessibility contract

### 7.1 Global shortcuts

| Key | Action |
|---|---|
| `Cmd/Ctrl + K` | Command palette. **Context-sensitive**: with a selection it lists actions for that selection; without one it lists navigation and global commands. Same verb list as right-click. |
| `/` | Focus the query bar |
| `Cmd/Ctrl + F` | Find within the current surface (deliberately a different scope and a different key from `/`) |
| `?` | Searchable keyboard-reference overlay |
| `G` then `Q` / `P` / `E` / `F` | Go to Queue / Path / Evidence / Fabric |
| `F` | Open the filter menu |
| `Shift + V` | Display-options popover |
| `Alt/Option + V` | Save the current filtered state as a named view |
| `E` | Toggle Rail B (evidence) |
| `I` | Toggle the inspector |
| `V` | Open config evidence for the current selection |
| `D` | Select the primary device of the focused finding |
| `T` | Run / re-run the trace |
| `M` | Toggle the `ignore acls` counterfactual mode |
| `R` | Reset camera |
| `Cmd/Ctrl + Enter` | Run the query in the focused surface |
| `Esc` | Close the topmost transient surface; from the grid, clear selection. **Never closes a persistent rail.** At the drawer rung (1024–1279 px) the evidence drawer is a transient surface: `Esc` closes it when focus is inside it and no inner layer is open (owner decision 2026-09-26, below). |
| `[` / `]` | Previous / next hop |
| `Cmd/Ctrl + \` | Toggle theme |

**Single unmodified keys act on the focused surface.** Therefore every text input must capture them
correctly, and `Esc` from an input returns focus to the surface that input belongs to.

**Owner decision, 2026-09-26 (D3) — `Esc` and the evidence drawer.** At the drawer rung (1024–1279
px), `Esc` closes the evidence drawer when focus is inside it and no inner layer is open; an inner
layer (the configuration overlay, a popover) closes first, and the next `Esc` closes the drawer.
`Esc` with focus outside the drawer leaves it open: it closes the layer that holds focus. Focus
returns to the control that opened the drawer; if that control has left the page, it follows
`src/app/focus-return.ts`'s fallback chain (the third door, `releaseFocusFrom` /
`useReleaseFocusOnHide`) — **never `<body>`**, and never back into the closed rail. From the commit
that closes it, the closed drawer is `inert`, so Tab skips it and a `focus()` call cannot re-enter it
during its 240 ms slide (§4.8). The persistent rail (≥ 1280 px) is never collapsed by `Esc` and is
never `inert`. `releaseFocusFrom` is the one owner for every container that can stop being rendered
while it holds focus — including panels removed by a layout change or a resize — and a surface that
unmounts on a rung crossing is inside that class whether or not it is wired to the owner yet
(`docs/open-issues.md` O58). Pinned by `src/app/drawer-focus-return.test.tsx`.

### 7.2 The APG data-grid contract, implemented literally

Applies to `#rail-queue`, the inspector's Data table, and every tabular evidence surface.

Structure: `role="grid"` containing `role="row"` containing
`role="columnheader" | "rowheader" | "gridcell"`. **Exactly one cell in the whole grid carries
`tabindex="0"`; every other cell carries `tabindex="-1"` (roving tabindex). The grid container
itself is NOT focusable.** `Tab` enters at the roving cell; the next `Tab` leaves the grid entirely.
A 146-row grid is **one** tab stop, not 876.

| Key | Behaviour |
|---|---|
| `Right Arrow` | One cell right. **At the right-most cell, focus does not move.** |
| `Left Arrow` | One cell left. At the left-most cell, focus does not move. |
| `Down Arrow` | One cell down. At the bottom cell of the column, focus does not move. |
| `Up Arrow` | One cell up. At the top cell of the column, focus does not move. |
| `Home` | First cell **in the row that contains focus**. |
| `End` | Last cell in the row that contains focus. |
| `Ctrl + Home` | First cell of the first row. |
| `Ctrl + End` | Last cell of the last row. |
| `Page Down` | Down **one visible page** — the rows that fit in the visible band, measured row by row from the focused row (rows differ in height: group headers, folded second lines), so the row left stays on screen as context and no row is passed unseen. Where the viewport cannot be measured (jsdom, a hidden ancestor, first paint) it falls back to **5 rows**. In the last row, focus does not move. |
| `Page Up` | Up the same page. In the first row, focus does not move. |
| `Enter` or `F2` | Enter cell edit/expand mode; focus moves into the control inside the cell. |
| `F2` or `Esc` | Exit that mode; grid navigation restored, focus returned to the cell. |
| `Shift + Space` | Select the row that contains focus. |
| `Ctrl + Space` | Select the column that contains focus. |
| `Ctrl + A` | Select all rows **matching the current filter**, not the whole dataset. |
| `X` | Toggle selection on the focused row **without moving focus**. |
| `t` (group header hovered or focused) | Collapse / expand that group. |

**Arrow keys clamp; they never wrap.** Wrapping is layout-grid behaviour, and importing it into a
data grid breaks the positional model an engineer builds while scanning.

**Focus and selection are separate states.** Moving the highlight never adds to a batch. Conflating
them is the single most common failure in dense tools: it makes "look at the next one" and "add the
next one to my batch" the same gesture, so bulk operations become accidental.

**Virtualisation must be declared through ARIA, or it lies.** `aria-rowcount` / `aria-colcount` on
the grid are the **logical totals** (146, not the roughly 30 rendered). `aria-rowindex` /
`aria-colindex` on rows and cells are 1-based **logical** positions. Announcing "row 12 of 30" when
the user is at logical row 118 of 146 makes the grid actively misleading — the screen-reader
position becomes a lie about the data, which is exactly the failure class this product exists to
eliminate elsewhere. `aria-sort` is `ascending` / `descending` / `none` on sortable columns and
**absent entirely** on non-sortable ones. `aria-multiselectable` on the grid; `aria-selected` on
selected rows.

### 7.3 The canvas DOM mirror (acceptance D6)

The three.js canvas is drawn for humans; a parallel DOM tree serves the keyboard and the
accessibility tree. A canvas draws pixels with no semantics: without the mirror, the entire
investigative core of this product is invisible to a screen reader and unreachable by keyboard.

- A visually-hidden (clip-rect, **not** `display: none`) container holds one `role="treeitem"` per
  device and per trace hop, grouped by tier as `role="group"`, inside one `role="tree"`.
- Accessible name per node:
  `<host> · <kind> · <role or "role not observed"> · band <band or "not observed"> · <nLinks> links ·
  <nFindings> findings`.
- The canvas element is **one** tab stop that delegates inward to the tree. Arrow keys move tree
  focus; the canvas draws the **pseudo focus ring** at the focused node's projected position,
  because a canvas has no default focus indication of any kind.
- `role="img"` plus `aria-label` on the canvas is used **only** in the collapsed/non-interactive
  state. When interactive, the mirror is the semantics.
- An always-available **"View as table"** toggle renders the same fabric as an APG grid: host, tier,
  role, band, collected, link count, findings count. This is also the 1.4.10 reflow answer at 320 px,
  where it is the default.

### 7.4 Focus management rules

1. One global focus token (3.4): `outline: 2px solid var(--focus); outline-offset: 2px` plus a 1 px
   inner ring. Applied to every focusable element — grid cells, canvas mirror nodes, tabs, chips,
   splitter handles, the lot.
2. **No ancestor of a focusable element sets `overflow: hidden`.** A clipped ring is a silent
   regression that passes visual review, because the ring is visible on whichever row happens to sit
   mid-viewport when someone looks.
3. Sticky chrome: every scroll container sets
   `scroll-padding-top: calc(var(--header-h) + var(--querybar-h))` and
   `scroll-padding-bottom: var(--statusbar-h)`, so `scrollIntoView` never parks a focused row
   underneath the bars (SC 2.4.11).
4. Modals — the command palette is the only one — trap focus, close on `Esc`, and **return focus to
   the exact invoking element**. `store.focusReturn` already exists for precisely this.
5. The inspector and the config overlay are **not** modals and do not trap focus. Opening the
   inspector moves focus into its tablist; closing returns focus to the Inspector button.
6. Opening the config overlay moves focus to its header; `Esc` returns focus to the citation token
   that opened it.
7. **Results never steal focus.** Query completion, counts, errors and progress announce through
   live regions (7.5). Yanking focus to the top of the results on every query is the fastest way to
   make the keyboard path unusable.
8. Focusing a control never changes context; changing a filter updates the view in place and
   announces the new count. Arrow-key traversal of the queue previews inside the existing layout and
   never swaps a panel.

### 7.5 Live regions

| Region | Role | Announces |
|---|---|---|
| `#sr-status` | `role="status"` (polite) | `Trace complete: 1 hop, denied at core1` · `118 of 146 findings match` · `Camera framed on core1` |
| `#sr-alert` | `role="alert"` (assertive) | Errors and unresolvable citations only. Nothing else. |
| `#sr-log` | `role="log"` | The append-only investigation timeline |

Containers exist in the DOM before any text is injected. `aria-busy="true"` on a grid while it
repopulates, so partial rows are not announced one at a time.

### 7.6 The WCAG 2.2 AA criteria that bite, and how each is satisfied

| SC | Level | How we satisfy it |
|---|---|---|
| **1.4.1** Use of Color | A | Section 3.3 rule plus 4.9 item 20: all four semantic channels carry a glyph, shape, dash pattern or label. A greyscale capture of states 03 and 06 is an acceptance artefact (D8). |
| **1.4.3** Contrast (Minimum) | AA | Section 3.3 — every ink/surface pairing computed and tabulated; six tokens corrected. Enforced by a **build-time pairwise token test** over every (foreground, background) pair the stylesheet actually uses, plus axe-core over the seven capture states in both themes. **A manual spot-check is not accepted as evidence**; contrast regressions arrive one token at a time and are invisible to their author. |
| **1.4.4** Resize Text | AA | No fixed-px heights on text-bearing rows (they are `min-height`); no `overflow: hidden` on a wrapping label. |
| **1.4.10** Reflow | AA | Section 2.5 ladder; the canvas claims the two-dimensional-layout exception but is replaced by the table by default at 320 px; grids scroll inside their own region and the page body never scrolls in two dimensions. |
| **1.4.11** Non-text Contrast | AA | `--border-strong` is 3.57:1 light / 3.89:1 dark; section 4.5 tabulates every canvas graphic against `--stage-bg`, measured at the point of lowest contrast, with a 2 CSS px minimum painted stroke. |
| **1.4.12** Text Spacing | AA | Survives line-height 1.5x, paragraph spacing 2x, letter-spacing 0.12x, word-spacing 0.16x with no loss of content or function. |
| **1.4.13** Content on Hover or Focus | AA | Every popover is **dismissible** (`Esc`, pointer unmoved), **hoverable** (no dead gap between trigger and popover; no mouseout-closes-instantly), **persistent** (never timeout-dismissed). Same content on focus, and never the only route — every popover fact is also in Rail B. |
| **2.1.1 / 2.1.2** Keyboard / No Keyboard Trap | A | Sections 7.1–7.3. Both investigation flows are completable with no mouse (D1). |
| **2.2.1** Timing Adjustable | AA | No investigation state expires on a timer. Full stop. |
| **2.3.3** Animation from Interactions | **AAA — adopted above the floor** | Section 4.8. Adopted because a physics-free but camera-animated 3-D view makes it materially relevant; labelled as AAA-derived, not claimed as our AA conformance. |
| **2.4.3** Focus Order | A | Header → query bar → Rail A → Stage (one stop, delegating to the mirror) → Rail B → status bar. Transient surfaces insert immediately after their trigger. |
| **2.4.7** Focus Visible | AA | Sections 3.4 and 7.4. |
| **2.4.11** Focus Not Obscured (Minimum) | AA, new in 2.2 | Section 7.4 rule 3. Tested by tabbing the entire app at 1280x720 **and** at 320 px, asserting the focused element's rect is at least partially in-viewport and not covered by any higher-stacking element. |
| **2.4.13** Focus Appearance | **AAA — adopted above the floor** | Adopted as the design rule because it is the only source giving testable numbers (at least a 2 CSS px perimeter, at least 3:1 focused-vs-unfocused); 2.4.7 AA alone gives none. Stated as AAA-derived. |
| **2.5.7** Dragging Movements | AA, new in 2.2 | Every drag has a click-only twin: splitters get arrow-key resize plus double-click reset plus a preset menu; camera orbit and pan get explicit buttons and click-to-centre; zoom gets plus/minus/Fit buttons; the inspector divider is keyboard-operable. Dragging remains as the fast path — the criterion requires an alternative, not removal. |
| **2.5.8** Target Size (Minimum) | AA, new in 2.2 | Section 3.2 — 24x24 floor, 32 px rows, hit areas grown with padding, and every spacing exception, when one exists, enumerated in `docs/target-size-exceptions.md` with its measured 24 px centre-to-centre spacing (none exists today, so the file does not; a grid cell is part of its row's target, section 3.2). |
| **3.2.1 / 3.2.2** On Focus / On Input | A | Section 7.4 rule 8. |
| **3.3.7** Redundant Entry | A, new in 2.2 | A device already selected pre-fills the path form; a target IP typed once is offered in the next flow's autocomplete. |
| **4.1.2** Name, Role, Value | A | Section 7.2 grid roles; section 7.3 canvas mirror. |
| **4.1.3** Status Messages | AA | Section 7.5. |

---

## 8. Responsiveness budget

### 8.1 The target, stated honestly

**Target: INP at or below 200 ms.** INP is defined over **click, tap and key press only** — hover,
scroll and zoom are excluded — and measures input delay plus event-handler processing duration plus
presentation delay, through to the next painted frame, **at the 75th percentile of field data**.
On pages exceeding 50 interactions, one highest interaction is ignored per 50.

**We do not have field data and we will not claim an INP number.** What acceptance E2 requires is a
**laboratory** measurement: the Event Timing API, on the real build, at least 20 repetitions per
journey, reported at the 95th percentile, on a **named reference machine**. Every published figure
must be labelled `laboratory, scripted, <machine>` — never `INP`. Quoting a lab number as a field
p75 would be precisely the false-health pattern this product exists to detect, committed by the
product itself.

The five declared representative journeys (acceptance E1). A declared journey is exactly what
`review/measure-inp.mjs` times (acceptance.md, "E3's scope"): every input its measured act performs
belongs to the journey.

1. Select a finding in the queue — including the first selection after page load
2. Select a device in the 3-D fabric
3. Type a character in the query bar
4. Run a path trace — swap the flow's endpoints, then submit; both inputs are the journey's
5. Open the command palette — Ctrl+K opens it and Escape closes it; both inputs are the journey's

### 8.2 Per-journey budget, decomposed

Phase allocation per interaction — **INFERRED engineering allocation, not a figure from any spec**:
input delay at most 50 ms, processing at most 50 ms, presentation at most 100 ms.

| Journey | Work | How it stays under budget |
|---|---|---|
| **1. Select a finding** | Write `findingId`; re-aim three surfaces (the first selection after load included) | The store write is synchronous and O(1). Rail B renders at most 40 DOM rows. `setHighlight` writes instance colours on an existing `InstancedMesh` — **no scene rebuild, no re-layout, and no React reconciliation of the canvas**, because the frozen contract in `contract.ts` deliberately keeps three.js off React's critical path. |
| **2. Select a device in 3-D** | Raycast, store write, 620 ms camera tween | The raycast runs against 3 `InstancedMesh` objects, not 26 Meshes, and resolves through `intersection.instanceId`. **The camera tween is NOT in the interaction budget**: the selection rim and the Rail B fill must paint in the first frame; the tween is a subsequent, separately budgeted animation. |
| **3. Type in the query bar** | Character echo, then a candidate filter over 146 findings | **The character echoes synchronously and unyielded in the same frame.** The filter recompute is debounced 120 ms and chunked. These are two different things and must never be coupled — coupling them is what makes a search box feel like it is thinking. |
| **4. Run a path trace** | Swap the endpoints (a form-state write), then submit: `traceFlow` over 2 RIBs and 1 ACL set, then re-aim four surfaces | `Trace.elapsedMs` is already on the model and is measured, not estimated — **measured 0.03–0.21 ms** per flow over the product's own `suggestedFlows()`. The trace is not the cost, and neither is the swap, which only rewrites the form's two fields. **The cost is the React commit that re-aims every surface: 46–89 ms in the submit handler, measured with Long Animation Frames attribution** (`DIV#root.onsubmit`), and it is the same 46–89 ms with the 3-D stage unmounted, so it is the DOM panels rather than the fabric. See 8.3 rule 1 for what is and is not enforced about that. |
| **5. Open the palette** | Ctrl+K: mount the modal; index 146 findings, 26 devices, and the command list. Escape: close it and return focus | The search index is **built once at boot and memoised**, never on open. Opening is a visibility toggle over an existing index, and so is closing it on Escape. **Owner goal, 2026-09-26: the FIRST Ctrl+K after a load pays no first-mount cost.** Implemented in phase 2 of the single-source-of-truth program (verdict pending a quiet host, `docs/open-issues.md` O59): after the scene converges, the palette's own frame is drawn once in idle slices (opacity 0.001, `aria-hidden`, `inert`, for at least 3 frames and 250 ms), then PARKED with `visibility: hidden` — laid out, out of the accessibility tree — until the first Ctrl+K, which flips attributes on those nodes. While parked its rows are frozen and its figures are computed in idle slices, so neither the pre-warm nor the first open reads the dataset. After the first open closes, the palette renders nothing when closed, as before. |

### 8.3 The hard rules

1. **No task on the main thread exceeds 50 ms.** Any loop over the data checks elapsed time and
   yields at a 50 ms deadline via `scheduler.yield()`, with a feature-detected Promise-wrapped
   `setTimeout(..., 0)` fallback. **The fallback re-queues at the BACK of the task queue and can be
   preempted by unrelated tasks** — that asymmetry is documented at the call site, not hidden inside
   the wrapper where a future reader would assume equivalence.

   **WHAT IS ACTUALLY ENFORCED, 2026-09-21 — this rule is a TARGET, not a mechanism that exists.**
   `grep -rn "scheduler\.yield\|requestIdleCallback\|Worker(" src/` returns nothing. No loop in this
   product yields at a deadline, because the tasks that break the rule are **not loops over data**:
   they are single synchronous React commits that re-aim four surfaces from one store write, and a
   `useSyncExternalStore` update is specified to be urgent — React will not time-slice it, so
   `startTransition` cannot break it up either. Measured on the release build with a hardware
   renderer: J1 (select a finding) 51–107 ms, J4 (run a path trace) 46–89 ms in the submit handler
   with the trace itself costing 0.2 ms, and the same figures with the 3-D stage unmounted.

   So the honest state of this rule is: **the 50 ms ceiling is measured and reported, not enforced.**
   `review/measure-inp.mjs` carries a separate **E3 verdict** — a journey with any task over 50 ms
   overlapping one of its own interactions fails it, and the process exits non-zero — so a violation
   is red on a gate instead of being a sentence in this document. Removing the violation means
   splitting the re-aim commit itself; until that is done, nothing here may be quoted as an enforced
   ceiling. A Web Worker is **not** the fix and the measurement says why: the engine is three orders
   of magnitude below the budget and the cost is the render.
2. **`isInputPending()` is not used.** The source explicitly withdrew that recommendation.
3. **Paint the acknowledgement first, compute after.** Commit the selection/highlight frame, then
   `requestAnimationFrame(() => setTimeout(work, 0))` the expensive recompute.
4. **No layout thrash.** All layout reads batched, then all writes — never interleaved within one
   task.
5. **Bounded DOM.** Any list over 200 rows is virtualised. The findings grid at 146 rows is under
   that today; **the virtualiser ships anyway**, because 146 is a property of this snapshot, not of
   the product, and the ARIA index overrides in 7.2 are required either way.
6. **`content-visibility: auto`** with `contain-intrinsic-size` on off-screen panels, collapsed
   inspector sections and inactive tab bodies.
7. **`renderer.info.autoReset = false`**, reset once per frame by us — a multi-pass composer makes
   naive per-frame draw-call readings wrong, and a wrong instrument is worse than none.

### 8.4 What is allowed to be slow, and how that is communicated

Four classes of work are **explicitly outside** the interaction budget. Each must be separately
budgeted, visibly in progress, and cancellable.

| Slow work | Treatment |
|---|---|
| **Initial three.js chunk load, and the scene warm-up behind it** | Code-split (acceptance F4); the initial payload does not carry three.js. **The cold load is a staged, yielding warm-up** (`src/fabric3d/scene.ts`), not one long frame: the environment prefilter, the scene's programs, the chain's programs and each pass are separate frames, and the driver's parallel link is waited on by polling rather than blocked on at first use. Measured on the release build with a hardware renderer: worst animation frame **375–447 ms** (blocking 317–382), against **1622–3260 ms** before the warm-up existed, and keystrokes fired during the load complete in 16 ms in most runs against 1888–3200 ms before. The remaining single cost above 200 ms is `PMREMGenerator.fromScene` (~0.4–0.6 s, one frame, measured independent of `envSize`, so it is program-link cost and three exposes no way to split it); the stage says the renderer is still building while it runs. |
| **Camera tween (620 ms)** | Labelled motion, not latency. Excluded from the interaction budget by definition, and removed entirely under `prefers-reduced-motion`. |
| **A trace or blast-radius computation exceeding 50 ms** | Would move to a Web Worker, with a `RUNNING` claim card **within 200 ms** carrying the scope tuple, a determinate progress readout, elapsed time and a Cancel control. **NOT BUILT, and on this snapshot not needed: `traceFlow` measures 0.03–0.21 ms per flow over the product's own `suggestedFlows()`.** Recorded as an unbuilt contingency rather than a shipped mechanism — the 50 ms tasks this product actually has are React commits, not computations (8.3 rule 1). No figure here describes running code. |
| **SSAO progressive convergence** | `SceneStats.converged` is already on the frozen contract. The status bar shows `refining...` until it flips; a screenshot taken before convergence is labelled as such rather than presented as final. |

**A cancelled or timed-out computation resolves to `INDETERMINATE` — never to a clean-looking empty
result.** This is the rule that keeps section 6 honest: if an unfinished job could render the same
state as a completed one, every honesty guarantee in this document collapses at the exact moment the
machine is under load.

**Adaptive quality is explicit, never silent** (acceptance E4). Three tiers, already typed as
`QualityTier` on the frozen contract, changing exactly four things:

| Tier | SSAO | SMAA | Internal render scale | Shadow map |
|---|---|---|---|---|
| `high` | 16 samples, `resolutionScale 0.5` | `ULTRA` | 1.00 | 2048 |
| `balanced` | 9 samples, `resolutionScale 0.5` | `HIGH` | 0.85 | 1536 |
| `low` | disabled | `MEDIUM` | 0.75 | 1024 |

Tier is selected from the **median** frame time over the first 60 frames after the scene settles —
median, not mean, because a single 120 ms hitch is what a user actually perceives and a mean hides
it. **Never from a user-agent string**, which stops being true the moment new hardware ships. The
active tier is named in the status bar at all times: a degradation the user cannot see is a silent
lie about what they are looking at.

Declared laboratory frame budget: **16.6 ms (60 fps) at 1920x1080 on the named reference machine,
with the full 26-node fabric and a trace animating.** Acceptance E4 asks for at least 55 fps; we
budget to 60 and report the measured median and p95. **This figure is a specification to be
validated, not a measurement — nothing in the source research was benchmarked, and no figure here
may be quoted as measured until it has been.**

---

## 9. Anti-patterns

The specific things a naive build of this application would do, and that this brief forbids. Each is
drawn from the research or from `docs/acceptance.md`, and each is checkable.

### Honesty

1. **Rendering `null` as an em dash, `0`, an empty cell, a green tick, or nothing at all.** It
   renders as `not observed` (T7), in `--claim-indeterminate`, with the explanatory description.
2. **Greying out `indeterminate`.** Grey reads as "not applicable" or "disabled". Indeterminate is a
   finding, with its own loud colour and its own count in every roll-up.
3. **Letting a successful sample path close a claim.** Every single-flow result carries T10
   permanently and inline.
4. **Rendering a failed, cancelled or unfinished computation with the same empty state as a
   completed clean one.** Three states, three treatments (5.3).
5. **Hiding an empty severity group.** `Info · 0` renders. An empty group is a positive statement;
   hiding it destroys that statement and leaves the reader to assume it was never checked.
6. **Deleting the ignored rules under the counterfactual.** Strikethrough plus
   `(ignored in permit-all mode)`, so the user still counts every blocker rather than learning that
   the path "works".
7. **Emitting a strong word from a weak result.** Mechanically prevented by 6.2; `proven`,
   `guaranteed`, `healthy`, `verified`, `safe`, `clean`, `OK` are grep-forbidden and fail the build.
8. **Letting a verdict float free of its snapshot.** The sha256 and `collectedAt` are in the chrome
   on every screen, and in every copied claim.
9. **Making the SCOPE chip removable.** It names the 2 modelled hosts and it is the boundary of the
   claim. A removable boundary is not a boundary.
10. **Silently reconciling our blast-radius number with the snapshot's own `failure_impact`.** The
    disagreement is surfaced (T9); a reconciled number is a fabrication introduced at exactly the
    point where the two sources disagree.
11. **Quoting a laboratory latency number as "INP".** INP is field, p75. Ours is laboratory, p95, on
    a named machine, and it is labelled that way every time it appears.
12. **Hardcoding 26 / 44 / 146 / 2 / 1 anywhere in the app.** Read `fabric.coverage` and the arrays
    at render time (SSOT, Law 1).
13. **Importing a disposition vocabulary we cannot compute.** Our enum is exactly `HopVerdict` plus
    `TraceOutcome` from `types.ts` — not Batfish's ten, six of which our engine does not model.

### Continuity

14. **Replacing the hop list with the evidence panel, or the topology with a full-page detail view.**
    Investigation is comparison; the moment one answer replaces another, the user starts
    re-navigating instead of concluding.
15. **Rebuilding the three.js scene to show a path.** `setTrace` is a state overlay onto already
    instantiated geometry. Camera, zoom and selection survive it.
16. **Re-laying-out the fabric when anything is selected, filtered or expanded.**
17. **Hiding off-path topology.** Dim to 55 %; never remove. The path must be checkable against the
    alternatives it did not take.
18. **Resetting the query when one dimension changes.** Tokens are independently removable, and the
    counterfactual re-runs without re-asking a single parameter.
19. **Putting config evidence in a modal.** It is a layered side panel; the originating context stays
    visible behind it, so you can always see what you clicked from.
20. **Blanking a rail when nothing is selected.** Rail B always shows something; `#rail-path` is
    absent rather than present-and-empty.

### Craft and density

21. **Making the whole grid row clickable for drill-down.** Drill-down has its own glyph; the row
    click is selection. Otherwise selection and navigation cannot be separated in a dense grid.
22. **Conflating focus and selection.** `X` is a separate, deliberate gesture from `ArrowDown`.
23. **Making every grid cell a tab stop.** One roving `tabindex="0"`; 146 rows is one tab stop, not
    876.
24. **Letting arrow keys wrap between rows or columns.** Data grids clamp; layout grids wrap.
25. **Trusting the browser's implicit row numbering under virtualisation.** `aria-rowindex` and
    `aria-rowcount` carry the logical values, or the screen reader confidently announces a wrong
    position.
26. **Rendering rows as bordered cards with per-row elevation.** Hairline or nothing; card padding
    belongs to detail panels, and letting it leak into the list halves the rows on screen.
27. **Using drop shadows for depth on dark surfaces.** Surface ladder plus hairlines.
28. **Introducing a second chromatic accent, a gradient, a glow on chrome, or a spotlight card.**
29. **Encoding severity by colour alone.** Every level carries a distinct glyph shape.
30. **Using display type (20 px and above) inside a working view.**
31. **Shrinking a target to gain density.** Density is information per row; a 14 px caret is a 2.5.8
    failure that buys no information at all.
32. **Removing or clipping the focus outline** — including via `overflow: hidden` on a cell wrapper.
33. **Auto-dismissing a tooltip on a timer**, or losing it across the gap to the popover. The
    truncated evidence it carries is exactly what the user was reaching for.
34. **Moving focus in order to announce a result.**
35. **Putting chrome geometry (inspector height, splitter position) into the shared URL.** Query,
    selection and scope are evidence and go in the URL; panel sizes are preferences and go in
    `localStorage`. Two people opening one link must receive the same *investigation*, not the same
    furniture.

### Rendering

The full list is 4.9. The four a naive build reaches for first:

36. **`LineBasicMaterial` with `linewidth: 3`.** Silently ignored on essentially every WebGL
    implementation; hairlines forever, with no error to find.
37. **`antialias: true` on the renderer while using a composer.** The MSAA default framebuffer is
    allocated and then discarded.
38. **Lowering `luminanceThreshold` below 1.0 to make something glow.** Raise `emissiveIntensity`
    instead; a sub-1.0 threshold blooms every ordinary lit surface and dates the scene instantly.
39. **Letting the renderer tone-map while the composer is present.** Two tone mappers is the classic
    double transform, and it is invisible in code review because nothing errors — it just looks
    slightly wrong forever.

### Dependency

40. **Bumping three.js past r186.** The installed `postprocessing@6.39.5` declares
    `>= 0.168.0 < 0.187.0` (verified by reading its `package.json`), and out-of-range drift in this
    library has historically surfaced as runtime GL errors rather than clean failures. Gate it in CI.
41. **Building against `N8AO`, or against the `RenderPipeline` / `ClearPass` / `GeometryPass` API.**
    Neither is installed. The v7 `RenderPipeline` API documented on the live pmndrs manual **does not
    exist in 6.39.5** — use `EffectComposer` / `RenderPass` / `EffectPass` exactly as specified in
    4.6.
42. **Quoting any figure from the source research as measured.** Nothing in it was benchmarked. The
    frame budget, the tier thresholds and the phase allocation are specifications to be validated,
    and they must be relabelled as laboratory measurements on named hardware only once they have
    been measured there.
