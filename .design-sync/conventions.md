# AssessHub design system — build conventions

AssessHub is a **dark-first network-assessment cockpit**. Everything below names real, shipped vocabulary — read `styles.css` (it `@import`s `_ds_bundle.css`: design tokens first, then every component class) before inventing anything.

## Setup — the one wrapper that matters
The six snapshot widgets — `TopologyGraph`, `CableMap`, `CausalFlowPanel`, `CutoverPlanner`, `DesignBlueprintPanel`, `ArchReviewPanel` — fetch their data at mount and show eternal spinners without a backend. Wrap them (once, at the top of the design) in `DemoDataProvider`: it serves a built-in, internally consistent sample fleet and provides the Router context `CutoverPlanner` needs. Any `snapId` value works; nesting is safe. The UI-kit pieces (`Kpi`, `Gauge`, `SegBar`, `Bars`, `SevChip`, `CountUp`, `Loading`, `ErrorBox`, `ErrorBoundary`) don't need it and aren't harmed by it.

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
| App chrome | `topbar`, `brand`, `page-head`, `breadcrumb`, `toast`, `spinner`, `wave-card`, `blocker`, `ros` (run-of-show timeline) |

Tokens (dark default; put `data-theme="light"` on a root element to flip): surfaces `--bg --surface --surface-2 --surface-3 --border --border-strong --border-faint`; text `--text --text-dim --text-faint`; accent `--accent --accent-dim --accent-soft`; posture `--ok --watch --risk --crit` (each with a `-soft` pair); fonts `--sans --mono`; radii `--radius --radius-sm`; motion `--ease --motion-fast --motion --motion-reveal`.

**Engine vocabulary → colour: never hand-pick.** Use the exported helpers `sevColor("High")` / `sevSoft`, `bandColor("Fair")`, `readyColor("CAUTION")`, `gateColor("NO-GO")` — or the underlying `--sev-*`, `--band-*`, `--ready-*`, `--gate-*` tokens. Severities are `Critical | High | Medium | Low | Info`; bands `Excellent | Good | Fair | Poor | Critical`.

## Where the truth lives
- `styles.css` → `_ds_bundle.css` — tokens + every class above, in that order.
- Per-component API and usage: `components/<group>/<Name>/<Name>.prompt.md` and `<Name>.d.ts`.

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
