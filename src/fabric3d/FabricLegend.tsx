/**
 * FabricLegend.tsx — the key to the fabric's visual encoding.
 *
 * A 3-D view whose encoding is undocumented on screen is decoration. Every channel the scene
 * spends — chassis colour, bezel glyph, surface treatment, rim, line width, dash pattern — is
 * listed here with the word that goes with it, which is also how the canvas satisfies "no meaning
 * by colour alone": the legend supplies the name, the shape supplies the second channel.
 *
 * Every count on this panel is computed from the data at render time. None of them is written down
 * anywhere in this file, because a cached denominator is the first thing to rot.
 */
import { useCallback, useEffect, useState, type CSSProperties, type ReactNode } from "react";

import type { Device, Link } from "../core/types";

const STORAGE_KEY = "atlas-scope.fabric-legend.open";

/** Kinds in the order the fabric reads top-down; anything else is appended, never dropped. */
const KIND_ORDER = ["router", "device", "ap"] as const;

const KIND_LABEL: Record<string, string> = {
  router: "Router",
  device: "Switch",
  ap: "Access point",
};

const BANDS = ["Excellent", "Good", "Fair", "Poor", "Critical"] as const;

const BAND_TOKEN: Record<string, string> = {
  Excellent: "--band-excellent",
  Good: "--band-good",
  Fair: "--band-fair",
  Poor: "--band-poor",
  Critical: "--band-critical",
};

const tokenStyle = (token: string): CSSProperties =>
  ({ "--swatch-fill": `var(${token})`, "--swatch-stroke": `var(${token})` }) as CSSProperties;

const readStored = (): boolean => {
  /* CLOSED is the default, and only an explicit stored "1" opens it.
     It used to default open, on the argument that a legend nobody asked to hide is never the
     defect. Measured, it is: at 1920x1080 the panel is an opaque 175x930 overlay covering 14.6% of
     a 1160x962 canvas, and it is docked over the left edge of the stage where core2, access17,
     access3, access5 and access10 render — so a first-time visitor's first sight of the product's
     central surface is a partially occluded topology with labels truncated to "re2", "ccess17",
     "ccess3", "ss5" and "s10".
     Closing it by default costs one click and loses nothing, because the collapsed state is not a
     hidden feature: it is a permanently visible "Legend" button in the same corner (see the !open
     branch below), discoverable, keyboard reachable and bound to the same command. A blocked or
     unreadable storage therefore also resolves to closed — the safe direction is the one that does
     not paint over the geometry. */
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
};

export interface FabricLegendProps {
  id: string;
  devices: readonly Device[];
  links: readonly Link[];
}

function Row({
  swatch,
  name,
  meaning,
  count,
}: {
  swatch: ReactNode;
  name: string;
  meaning?: string;
  count?: number;
}) {
  return (
    <li className="fabric3d-legend__row">
      <svg className="fabric3d-legend__swatch" viewBox="0 0 32 16" aria-hidden="true" focusable="false">
        {swatch}
      </svg>
      <span className="fabric3d-legend__text">
        {name}
        {count === undefined ? null : <> · <span className="fabric3d-legend__count">{count}</span></>}
        {meaning === undefined ? null : <span className="fabric3d-legend__meaning">{meaning}</span>}
      </span>
    </li>
  );
}

const chassis = (style?: CSSProperties, extra?: string) => (
  <rect
    x="4"
    y="4"
    width="24"
    height="8"
    rx="2"
    className={extra ? `fabric3d-legend__chassis ${extra}` : "fabric3d-legend__chassis"}
    style={style}
  />
);

/**
 * A health-band swatch: the chassis in its band colour PLUS the letter that device's on-canvas
 * label carries. A legend whose rows differ only by `--swatch-fill` is unreadable in exactly the
 * conditions the legend exists for — greyscale print, a projector, colour-vision deficiency — so
 * the swatch has to carry the second channel too, not just describe it.
 */
const bandSwatch = (letter: string, style?: CSSProperties, extra?: string) => (
  <>
    {chassis(style, extra)}
    <text
      x="16"
      y="8"
      className="fabric3d-legend__bandletter"
      style={style}
      textAnchor="middle"
      dominantBaseline="central"
    >
      {letter}
    </text>
  </>
);

/**
 * A label-mark swatch: the glyph the on-canvas label actually prints, in the mark's own colour.
 * The words are in the row name, which is the point — these marks exist BECAUSE a colour is not a
 * channel on its own, so the legend row must not be a colour either.
 */
const markSwatch = (glyph: string, style?: CSSProperties, dashed = false) => (
  <>
    <rect
      x="2"
      y="2"
      width="28"
      height="12"
      rx="2"
      className="fabric3d-legend__chassis fabric3d-legend__chassis--wire"
      style={style}
      {...(dashed ? { strokeDasharray: "3 2" } : {})}
    />
    <text
      x="16"
      y="8"
      className="fabric3d-legend__bandletter"
      style={style}
      textAnchor="middle"
      dominantBaseline="central"
    >
      {glyph}
    </text>
  </>
);

const line = (dash: string | undefined, cls: string, style?: CSSProperties, y = 8) => (
  <path
    d={`M2 ${y} H30`}
    className={cls}
    style={style}
    {...(dash === undefined ? {} : { strokeDasharray: dash })}
  />
);

export function FabricLegend({ id, devices, links }: FabricLegendProps) {
  const [open, setOpen] = useState<boolean>(() =>
    typeof window === "undefined" ? true : readStored(),
  );

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, open ? "1" : "0");
    } catch {
      /* Storage is a convenience here; losing it costs the user one click. */
    }
  }, [open]);

  const toggle = useCallback(() => setOpen((v) => !v), []);

  const kinds = new Map<string, number>();
  for (const d of devices) kinds.set(d.kind, (kinds.get(d.kind) ?? 0) + 1);
  const orderedKinds = [
    ...KIND_ORDER.filter((k) => kinds.has(k)),
    ...[...kinds.keys()].filter((k) => !KIND_ORDER.includes(k as (typeof KIND_ORDER)[number])).sort(),
  ];

  const bandCount = (b: string) => devices.filter((d) => d.band === b).length;
  const bandUnobserved = devices.filter((d) => d.band === null).length;
  const roleAccess = devices.filter((d) => d.role === "access").length;
  const roleDist = devices.filter((d) => d.role === "distribution").length;
  const roleOther = devices.filter(
    (d) => d.role !== null && d.role !== "access" && d.role !== "distribution",
  ).length;
  const roleUnobserved = devices.filter((d) => d.role === null).length;
  const uncollected = devices.filter((d) => !d.collected).length;
  const stateUnknown = devices.filter((d) => d.opStatus === "unknown").length;
  const stateDown = devices.filter((d) => d.opStatus === "down").length;
  const linksDown = links.filter((l) => l.opStatus === "down").length;
  const linksUnknown = links.filter((l) => l.opStatus === "unknown").length;
  const bridges = links.filter((l) => l.isBridge === true).length;
  const unmeasured = links.filter((l) => l.isBridge === null).length;
  const portChannels = links.filter((l) => l.isPortChannel).length;

  if (!open) {
    return (
      <button
        type="button"
        className="fabric3d__btn fabric3d-legend__show"
        /* No aria-controls while collapsed: the panel is not in the DOM, and pointing at an id
           that does not resolve is worse than not pointing at all. */
        aria-expanded={false}
        data-atlas-command="fabric.toggleLegend"
        onClick={toggle}
        data-testid="fabric3d-legend-show"
      >
        Legend
      </button>
    );
  }

  return (
    <section className="fabric3d-legend" id={id} aria-labelledby={`${id}-title`} data-testid="fabric3d-legend">
      <div className="fabric3d-legend__head">
        <h2 className="fabric3d-legend__title" id={`${id}-title`}>
          Legend
        </h2>
        <button
          type="button"
          className="fabric3d-legend__close"
          aria-expanded
          aria-controls={id}
          data-atlas-command="fabric.toggleLegend"
          onClick={toggle}
        >
          <span aria-hidden="true">✕</span>
          <span className="fabric3d__sr-only">Hide the legend</span>
        </button>
      </div>

      <div className="fabric3d-legend__group">
        <h3 className="fabric3d-legend__legend">Chassis shape — device kind</h3>
        <ul className="fabric3d-legend__list">
          {orderedKinds.map((k) => (
            <Row
              key={k}
              swatch={
                k === "ap" ? (
                  <ellipse cx="16" cy="8" rx="7" ry="4" className="fabric3d-legend__chassis" />
                ) : k === "router" ? (
                  <rect x="4" y="3" width="24" height="10" rx="2" className="fabric3d-legend__chassis" />
                ) : (
                  chassis()
                )
              }
              name={KIND_LABEL[k] ?? k}
              count={kinds.get(k) ?? 0}
            />
          ))}
        </ul>
      </div>

      <div className="fabric3d-legend__group">
        <h3 className="fabric3d-legend__legend">Chassis colour and label letter — health band</h3>
        <ul className="fabric3d-legend__list">
          {BANDS.map((b) => (
            <Row
              key={b}
              swatch={bandSwatch(b.slice(0, 1), tokenStyle(BAND_TOKEN[b] ?? "--text-faint"))}
              name={b}
              count={bandCount(b)}
            />
          ))}
          <Row
            swatch={bandSwatch("?", undefined, "fabric3d-legend__chassis--wire")}
            name="Band not observed"
            meaning="No health score was computed. Not a passing band."
            count={bandUnobserved}
          />
        </ul>
        <p className="fabric3d-legend__note fabric3d-legend__note--tight">
          The five band colours are within 1.14:1 of each other in greyscale, so the band is also
          printed as a letter on the device's own label — E, G, F, P, C, or ? when no band was
          computed. Either channel alone is enough to read it.
        </p>
      </div>

      <div className="fabric3d-legend__group">
        <h3 className="fabric3d-legend__legend">Bezel glyph — role</h3>
        <ul className="fabric3d-legend__list">
          <Row
            swatch={
              <>
                <path d="M10 5 H22" className="fabric3d-legend__glyph" />
                <path d="M10 8 H22" className="fabric3d-legend__glyph" />
                <path d="M10 11 H22" className="fabric3d-legend__glyph" />
              </>
            }
            name="Access"
            count={roleAccess}
          />
          <Row
            swatch={<path d="M11 4 L20 8 L11 12" className="fabric3d-legend__glyph" />}
            name="Distribution"
            count={roleDist}
          />
          {roleOther === 0 ? null : (
            <Row
              swatch={<path d="M11 8 H21" className="fabric3d-legend__glyph" />}
              name="Other role"
              count={roleOther}
            />
          )}
          <Row
            swatch={
              <path
                d="M10 8 H22"
                className="fabric3d-legend__glyph"
                strokeDasharray="3 2"
                style={tokenStyle("--claim-indeterminate")}
              />
            }
            name="Role not observed"
            meaning="The snapshot never stated a role for this device."
            count={roleUnobserved}
          />
        </ul>
      </div>

      <div className="fabric3d-legend__group">
        <h3 className="fabric3d-legend__legend">Surface — collection</h3>
        <ul className="fabric3d-legend__list">
          <Row
            swatch={chassis()}
            name="Collected"
            meaning="The collector reached this device."
            count={devices.length - uncollected}
          />
          <Row
            swatch={
              <>
                {chassis(undefined, "fabric3d-legend__chassis--wire")}
                <path d="M6 12 L12 4 M12 12 L18 4 M18 12 L24 4" className="fabric3d-legend__hatch" />
              </>
            }
            name="Topology only — not collected"
            meaning="Seen as a neighbour. Nothing about its state was observed."
            count={uncollected}
          />
        </ul>
      </div>

      <div className="fabric3d-legend__group">
        <h3 className="fabric3d-legend__legend">Chassis rim — operational state</h3>
        <ul className="fabric3d-legend__list">
          <Row
            swatch={<rect x="5" y="4" width="22" height="8" rx="2" className="fabric3d-legend__rim" style={tokenStyle("--state-up")} />}
            name="Up"
            count={devices.length - stateUnknown - stateDown}
          />
          <Row
            swatch={<rect x="5" y="4" width="22" height="8" rx="2" className="fabric3d-legend__rim" style={tokenStyle("--state-down")} />}
            name="Down"
            count={stateDown}
          />
          <Row
            swatch={
              <rect
                x="5"
                y="4"
                width="22"
                height="8"
                rx="2"
                className="fabric3d-legend__rim"
                strokeDasharray="2 2"
                style={tokenStyle("--state-unknown")}
              />
            }
            name="Unknown"
            meaning="A third state, neither up nor down."
            count={stateUnknown}
          />
        </ul>
      </div>

      {/* The marks a label can carry about the CURRENT investigation. Three of them are the three
          endings a trace can have, and they are listed together on purpose: `blocked` and
          `undecided` used to be drawn with the same treatment and the same word, and `delivered
          here` did not exist at all, so a successful trace over an already-selected host left no
          mark anywhere on the fabric. */}
      <div className="fabric3d-legend__group">
        <h3 className="fabric3d-legend__legend">Label mark — this trace, this selection</h3>
        <ul className="fabric3d-legend__list">
          <Row
            swatch={markSwatch("✕", tokenStyle("--state-down"))}
            name="✕ blocked"
            meaning="A rule or an absent route stopped the traced packet at this host."
          />
          <Row
            swatch={markSwatch("?", tokenStyle("--claim-indeterminate"), true)}
            name="? undecided"
            meaning="The simulation reached this host and declined to decide. Not a drop, and not a delivery."
          />
          <Row
            swatch={markSwatch("✓", tokenStyle("--accent"))}
            name="✓ delivered here"
            meaning="The traced packet reached its destination at this host."
          />
          <Row
            swatch={markSwatch("⚠", tokenStyle("--claim-indeterminate"), true)}
            name="⚠ cut point"
            meaning="Removing the selected host would cut other hosts off the fabric. A hypothesis, not an event."
          />
          <Row
            swatch={markSwatch("⊘", tokenStyle("--claim-indeterminate"), true)}
            name="⊘ stranded"
            meaning="Unreachable if the current selection fails."
          />
        </ul>
        <p className="fabric3d-legend__note fabric3d-legend__note--tight">
          A trace mark and a cut-point mark are separate claims and a host can carry both at once:
          one is a fact about the packet in front of you, the other is a projection about a failure
          that has not happened.
        </p>
      </div>

      <div className="fabric3d-legend__group">
        <h3 className="fabric3d-legend__legend">Cables</h3>
        <ul className="fabric3d-legend__list">
          <Row swatch={line(undefined, "fabric3d-legend__line")} name="Link, up" />
          <Row
            swatch={line("5 3", "fabric3d-legend__line", tokenStyle("--state-down"))}
            name="Link, down"
            count={linksDown}
          />
          <Row
            swatch={line("1 3", "fabric3d-legend__line", tokenStyle("--state-unknown"))}
            name="Link state unknown"
            count={linksUnknown}
          />
          <Row
            swatch={
              <>
                {line(undefined, "fabric3d-legend__line fabric3d-legend__line--thick", tokenStyle("--sev-high"), 6)}
                {line(undefined, "fabric3d-legend__line fabric3d-legend__line--thick", tokenStyle("--sev-high"), 11)}
              </>
            }
            name="Bridge — cutting it partitions the fabric"
            count={bridges}
          />
          <Row
            swatch={line("2 2", "fabric3d-legend__line", tokenStyle("--claim-indeterminate"))}
            name="Centrality not computed"
            meaning="Unmeasured, not redundant. The blast radius of this cable is unknown."
            count={unmeasured}
          />
          <Row
            swatch={
              <>
                {line(undefined, "fabric3d-legend__line", undefined, 6)}
                {line(undefined, "fabric3d-legend__line", undefined, 11)}
              </>
            }
            name="Port channel — one line per member"
            count={portChannels}
          />
          <Row
            swatch={line(undefined, "fabric3d-legend__line fabric3d-legend__line--trace", tokenStyle("--accent"))}
            name="On the traced path"
          />
          <Row
            swatch={line(undefined, "fabric3d-legend__line fabric3d-legend__line--trace", tokenStyle("--sev-critical"))}
            name="Blocking hop"
            meaning="The device, ACL or absent route that stopped the flow."
          />
        </ul>
      </div>

      <p className="fabric3d-legend__note">
        Nothing is hidden by a filter or a selection: off-path and non-matching elements dim to stay
        readable. A dimmed cable is still a cable you could have taken.
      </p>
    </section>
  );
}
