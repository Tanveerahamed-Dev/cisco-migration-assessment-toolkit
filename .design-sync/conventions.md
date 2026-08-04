# AssessHub design system — build conventions

AssessHub is a **dark-first network-assessment cockpit**. Everything below names real, shipped vocabulary — read `styles.css` (it `@import`s `_ds_bundle.css`: design tokens first, then every component class) before inventing anything.

## Setup — the one wrapper that matters
The six snapshot widgets — `TopologyGraph`, `CableMap`, `CausalFlowPanel`, `CutoverPlanner`, `DesignBlueprintPanel`, `ArchReviewPanel` — fetch their data at mount and show eternal spinners without a backend. Wrap them (once, at the top of the design) in `DemoDataProvider`: it serves a built-in, internally consistent sample fleet and provides the Router context `CutoverPlanner` needs. Any `snapId` value works; nesting is safe. The UI-kit pieces (`Kpi`, `Gauge`, `SegBar`, `Bars`, `SevChip`, `CountUp`, `Loading`, `ErrorBox`, `ErrorBoundary`, `Skeleton`, `SkelLines`, `SkelTable`, `VerificationBadge`, `VerificationWarning`) don't need it and aren't harmed by it.

```tsx
<DemoDataProvider>
  <div className="panel"><h3>Topology · blast radius</h3><TopologyGraph snapId={1} /></div>
</DemoDataProvider>
```

## Styling idiom — global classes + CSS custom properties
No CSS-in-JS, no utility framework. Style with (1) the shipped global classes and (2) `var(--*)` tokens in inline styles — exactly how the app itself does it.

| Family | Real class names |
|---|---|
| Surfaces & layout | `panel` (+ `pad-lg`), `grid` with `cols-2` / `cols-3` / `cols-4` / `auto`, `row-flex`, `spread`, `container`, `divider`, `center`, `empty` |
| Text | `mono`, `dim`, `faint` — and `panel h3` renders the uppercase section heading |
| Buttons & controls | `btn` (+ `primary` / `ghost` / `lg` / `danger`), `tabs` (buttons take `.on`), bare `input`/`select`/`textarea` are pre-styled |
| Chips | `chip`; `chip sev` (colour via `--c`/`--cs`), `chip gate` (via `--gc`), `chip tag` |
| Data display | `tbl` (+ `num` cells), `kpi` (children `l`/`v`/`hint`; tone class `ok`/`watch`/`risk`/`crit`), `segbar`, `legend` (+ `item`/`sw`), `bars`, `gauge`, `cmd` (code block) |
| Coverage honesty | `verification-badge`, `verification-warning` — each takes a state modifier `verification-verified` / `verification-partial` / `verification-unverified` |
| App chrome | `topbar`, `brand`, `page-head`, `breadcrumb`, `toast`, `spinner`, `wave-card`, `blocker`, `ros` (run-of-show timeline) |

Tokens (dark default; put `data-theme="light"` on a root element to flip): surfaces `--bg --surface --surface-2 --surface-3 --border --border-strong --border-faint`; text `--text --text-dim --text-faint`; accent `--accent --accent-dim --accent-soft`; posture `--ok --watch --risk --crit` (each with a `-soft` pair); fonts `--sans --mono`; radii `--radius --radius-sm`; motion `--ease --motion-fast --motion --motion-reveal`; **depth & glass** `--glass` / `--glass-2` (frosted surface fills), `--glass-border` (frosted border), `--blur` (backdrop-blur radius), `--elev-1` / `--elev-2` (resting / raised shadow), `--accent-grad` (gradient CTA fill), `--glow` (accent halo).

The depth layer is applied for you by `panel`, `topbar`, `btn primary` and `tabs` (active `.on`). To frost a **custom** surface, mirror them: `background: var(--glass); border: 1px solid var(--glass-border); backdrop-filter: blur(var(--blur)); box-shadow: var(--elev-1)` — swap `--elev-2` when raised/hovered. For a custom accent CTA: `background: var(--accent-grad)` with a `var(--glow)` halo in `box-shadow`.

**Engine vocabulary → colour: never hand-pick.** Use the exported helpers `sevColor("High")` / `sevSoft`, `bandColor("Fair")`, `readyColor("CAUTION")`, `gateColor("NO-GO")` — or the underlying `--sev-*`, `--band-*`, `--ready-*`, `--gate-*` tokens. Severities are `Critical | High | Medium | Low | Info`; bands `Excellent | Good | Fair | Poor | Critical`.

**Absence is never health.** Any screen showing assessment results states its coverage rather than
implying it: `<VerificationBadge value={snap.verification} />` in the page header (add `compact` for
table cells), `<VerificationWarning value={snap.verification} />` above the first `.grid`. Mount the
warning **unconditionally** — it returns `null` for a verified snapshot and only speaks when it has
something to say. Never hand-roll either from `chip`/`panel`: both run their input through
`normalizedVerification`, which forces absent, legacy or self-contradicting metadata **down** to
unverified, so they cannot over-claim and a hand-rolled lookalike can. An empty result table gets the
same treatment — say "[NOT OBSERVED]" (the house phrasing used by `TopologyGraph`, `CableMap` and
`CausalFlowPanel` when nothing resolved), never a silent blank that reads as all-clear.

## Motion — shipped classes only, never hand-rolled keyframes
Every animation below is pre-gated behind `prefers-reduced-motion`; compose with these and reduced-motion correctness comes free. Durations/easing always via the motion tokens (`--motion-fast` micro, `--motion` transitions, `--motion-reveal` mount reveals, `--ease`) — never literal ms values.
- **Mount reveals**: `panel` animates in by itself. Direct `panel` children of a `grid` stagger — set `style={{ "--stagger-i": Math.min(i, 8) }}` per card for ordered reveal of a data-driven list. Table rows: add class `row-reveal` + `style={{ animationDelay: `${Math.min(i, 8) * 40}ms` }}`.
- **Content swaps**: wrap swappable content in `<div className="tabfade" key={activeKey}>` — the key change replays a fade (the app's tab idiom). For a disclosure/accordion body that mounts on open, add `ros-reveal`.
- **Loading states**: `SkelLines` (panel bodies), `SkelTable` (tables) — structure-shaped, self-announcing placeholders; keep `Loading` for full-page/unknown-shape waits. Never leave a blank div while data loads.

## Where the truth lives — and what this DS does not ship
- `styles.css` → `_ds_bundle.css` — tokens + every class above, in that order. **That is the only
  stylesheet.** This DS ships **no `tokens/*.css` files and no `fonts/` directory** — the tokens are
  compiled into `_ds_bundle.css`, and the type stack is deliberately system fonts (`--sans`, `--mono`).
  A generic "Where things are" list further down names both paths; for *this* design system they are
  empty, so `read_file("tokens/…")` returns nothing. Read `_ds_bundle.css` instead.
- Per-component API and usage: `components/<group>/<Name>/<Name>.prompt.md` and `<Name>.d.ts`
  (every component publishes a real props interface).
- **Load order is load-bearing.** `_ds_bundle.js` externalises React rather than vendoring it, so
  React must already be on the page: load `_vendor/react.js`, then `_vendor/react-dom.js`, then
  `_ds_bundle.js` — exactly what the shipped preview cards do. `styles.css` is a plain `<link>` and
  can sit anywhere in `<head>`. Get the order wrong and the bundle throws part-way through its IIFE,
  `window.AssessHub` is **never created at all**, and the `<script>` tag itself reports no error —
  so every component reads as `undefined` with nothing in the console to explain it.

## An idiomatic page
```tsx
<DemoDataProvider>
  <div className="container">
    <div className="page-head"><h1>Fleet assessment</h1><span className="sub">snapshot #1</span></div>
    <div className="grid cols-4">
      <Kpi label="switches" value={<CountUp value={303} />} hint="253 collected · 50 not" />
      <Kpi label="avg health" value={72.4} tone="watch" />
      <Kpi label="critical findings" value={12} tone="crit" />
      <Kpi label="readiness" value="CAUTION" tone="watch" />
    </div>
    <div className="grid cols-2" style={{ marginTop: 16 }}>
      <div className="panel"><h3>Fleet health</h3><SegBar data={{ Good: 118, Fair: 62, Poor: 22 }} colorFor={bandColor} /></div>
      <div className="panel"><h3>Topology</h3><TopologyGraph snapId={1} /></div>
    </div>
  </div>
</DemoDataProvider>
```

Body background (`var(--bg)`) and base text colour apply automatically from the shipped CSS; the dotted-grid backdrop additionally needs an element with `id="root"`. Fonts are system stacks (`--sans`, `--mono`) by design — there is no brand webfont to load.
