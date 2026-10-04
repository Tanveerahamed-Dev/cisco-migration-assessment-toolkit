/**
 * FabricA11yTree.tsx — the fabric as a real DOM tree (acceptance D6).
 *
 * A canvas is opaque to assistive technology: a selection made in 3-D has no accessible name, no
 * role and no position. This is not a caption for the canvas — it is the same fabric, reachable by
 * a different input, writing the same investigation state. Everything selectable in 3-D is
 * selectable here, and every unobserved field is stated as unobserved rather than left blank.
 *
 * Semantics follow the ARIA treeview pattern in its flat form: `role="tree"` with `role="treeitem"`
 * children carrying `aria-level`, `aria-posinset` and `aria-setsize`. Flat is used over nested
 * groups because rows are virtualised out of the DOM when their parent collapses, and a nested
 * `role="group"` whose only child has been removed is an empty group the screen reader still walks.
 *
 * VISIBILITY IS A SCREEN CONCERN ONLY — stated here because an audit reasonably read it as a bug.
 *
 * When `visible` is false this section is clipped, but it keeps `visibility: visible`, takes no
 * `inert` and no `aria-hidden`, so all of its treeitems stay in the accessibility tree. That is
 * the point of it: this is not a disclosure panel, it is the only non-canvas representation of
 * the fabric, and gating it behind a toggle would mean a screen-reader user has to discover a
 * control before the fabric exists for them at all. The clip is the standard visually-hidden
 * recipe (Fabric3D.css), not a 1px layout accident, and `:focus-within` un-clips it so a focus
 * ring inside is never invisible (WCAG 2.4.7).
 *
 * The cost is that the "Fabric list" toggle reads `aria-pressed="false"` while the tree is
 * present. That contradiction is resolved where it is met, by a description on the toggle itself
 * (Fabric3D.tsx) saying the list is always readable and the button only puts it on screen.
 */
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";

import { linkFailureImpact, type LinkFailureResult } from "../analysis/blast";
import { bandScored, presentBand } from "../core/band-qualification";
import { COLLECTION_WORDS } from "../core/collection";
import { classifyLink } from "./geometry/cables";
import { useInvestigation } from "../core/store";
import type { Device, Link } from "../core/types";

/** How long a type-ahead buffer survives between keystrokes, per the APG tree pattern. */
/** The tree's gestures, each stated against the canvas gesture it is equivalent to. */
export const TREE_GESTURES =
  "Click or Space selects, as a click on the fabric does, and leaves the camera where it is. Double-click or Enter selects and frames the device, as a double-click on the fabric does.";

const TYPEAHEAD_MS = 500;

/**
 * How many device rows the tree opens on first render. Tiers are opened in order while their devices
 * fit this budget; a tier that would overrun it starts collapsed, its row still stating its count.
 *
 * SCALE (2026-09-28). Every tier used to open, a choice made for the 26-device reference sample ("26
 * device rows are readable in one pass, 70 rows are not"). On a 300-node fleet that is 300 rows before
 * the first tier ends, and 1 000 on the next size up — a list a screen-reader user cannot get through
 * and a mount that renders every row. 40 keeps the reference sample fully open (26 rows, unchanged)
 * and a large fleet's small tiers (core, distribution) open, with the access blocks one keystroke away.
 * Type-ahead still finds a device inside a collapsed tier (see onKeyDown).
 */
export const TREE_OPEN_DEVICE_BUDGET = 40;

type RowKind = "tier" | "device" | "link";

interface Row {
  key: string;
  kind: RowKind;
  level: number;
  parent: string | null;
  label: string;
  /** Right-hand column: the one fact that matters most for this row. */
  meta: string;
  /** True when `meta` is an explicit "not observed", so it is styled as a claim, not as data. */
  metaUnobserved: boolean;
  /** The store identity this row selects; null when the row is a group or names no record. */
  targetId: string | null;
  childKeys: string[];
  /** A row naming a host the snapshot has no device record for: listed, never silently dropped. */
  orphan: boolean;
}

interface TreeModel {
  rows: Map<string, Row>;
  roots: string[];
  /** Each row's 1-based position among its siblings: computed once, not searched per rendered row. */
  posInSet: Map<string, number>;
  /** Links by id, so a link row's wording is computed when the row is shown, not for every link at mount. */
  linkById: Map<string, Link>;
}

/** Tiers opened on first render: in order, while their devices fit TREE_OPEN_DEVICE_BUDGET. */
function initiallyOpen(model: TreeModel): Set<string> {
  const open = new Set<string>();
  let shown = 0;
  for (const key of model.roots) {
    const n = model.rows.get(key)?.childKeys.length ?? 0;
    if (shown + n > TREE_OPEN_DEVICE_BUDGET) continue;
    open.add(key);
    shown += n;
  }
  return open;
}

function buildModel(
  devices: readonly Device[],
  links: readonly Link[],
  tiers: readonly (readonly string[])[],
): TreeModel {
  const rows = new Map<string, Row>();
  const roots: string[] = [];
  const byHost = new Map<string, Device>();
  for (const d of devices) {
    byHost.set(d.host, d);
    if (!byHost.has(d.id)) byHost.set(d.id, d);
  }
  const linkById = new Map(links.map((l) => [l.id, l]));
  /* The links touching each device, from THIS tree's link list — the fabric it was given, not the
     module-level sample index — so a tree over another fabric lists that fabric's cables. */
  const incidentByHost = new Map<string, Link[]>();
  for (const l of links) {
    for (const h of l.a === l.b ? [l.a] : [l.a, l.b]) {
      const list = incidentByHost.get(h);
      if (list) list.push(l);
      else incidentByHost.set(h, [l]);
    }
  }
  const placed = new Set<string>();

  const addDevice = (parentKey: string, level: number, host: string): string => {
    const dev = byHost.get(host);
    const key = `device:${dev ? dev.id : host}`;
    if (rows.has(key)) return key;
    const incident = (dev ? (incidentByHost.get(dev.host) ?? incidentByHost.get(dev.id) ?? []) : [])
      .slice()
      .sort((a, b) => a.id.localeCompare(b.id));
    const childKeys: string[] = [];
    rows.set(key, {
      key,
      kind: "device",
      level,
      parent: parentKey,
      label: dev ? dev.host : host,
      /* An uncollected device must SAY so on its own row: "band not observed" alone reads the same
         for a topology-only neighbour and for a collected-but-unscored device, and a screen-reader
         user navigating rows never hears the preamble's count again. */
      meta: dev
        ? dev.collected
          ? dev.collection === "partial"
            ? `${presentBand(dev).short} · ${COLLECTION_WORDS.partial}`
            : presentBand(dev).short
          : COLLECTION_WORDS[dev.collection]
        : "no device record",
      /* A qualified band is partly an absence of evidence, so it is styled as a claim too (B1). */
      metaUnobserved: !dev || !dev.collected || dev.collection === "partial" || !bandScored(dev) || presentBand(dev).qualified,
      targetId: dev ? dev.id : null,
      childKeys,
      orphan: !dev,
    });
    for (const l of incident) {
      const peer = l.a === (dev ? dev.host : host) || l.a === (dev ? dev.id : host) ? l.b : l.a;
      const nearPort = l.a === peer ? l.bPort : l.aPort;
      const farPort = l.a === peer ? l.aPort : l.bPort;
      const linkKey = `${key}/link:${l.id}`;
      rows.set(linkKey, {
        key: linkKey,
        kind: "link",
        level: level + 1,
        parent: key,
        label: `${nearPort ?? "port not observed"} → ${peer} ${farPort ?? "port not observed"}`,
        /* Filled in when the row is shown (linkRowMeta): the same computation, and certainty, the
           Inspector and the live announcement use — the snapshot's bridge flag is not stated as fact on
           a disputed cable. Computing it for every link at mount was a failure analysis per cable
           before the tree could draw at all. */
        meta: "",
        metaUnobserved: true,
        targetId: l.id,
        childKeys: [],
        orphan: false,
      });
      childKeys.push(linkKey);
    }
    if (dev) placed.add(dev.id);
    return key;
  };

  tiers.forEach((hosts, index) => {
    const key = `tier:${index}`;
    const childKeys: string[] = [];
    rows.set(key, {
      key,
      kind: "tier",
      level: 1,
      parent: null,
      label: `Tier ${index}`,
      meta: `${hosts.length} ${hosts.length === 1 ? "device" : "devices"}`,
      metaUnobserved: false,
      targetId: null,
      childKeys,
      orphan: false,
    });
    roots.push(key);
    for (const host of [...hosts].sort((a, b) => a.localeCompare(b))) {
      childKeys.push(addDevice(key, 2, host));
    }
  });

  /* Devices the cable map never placed in a tier. Rendering them under a "tier not observed" group
     is the honest treatment: dropping them would make the tree look like a complete fabric. */
  const unplaced = devices.filter((d) => !placed.has(d.id));
  if (unplaced.length > 0) {
    const key = "tier:unobserved";
    const childKeys: string[] = [];
    rows.set(key, {
      key,
      kind: "tier",
      level: 1,
      parent: null,
      label: "Tier not observed",
      meta: `${unplaced.length} ${unplaced.length === 1 ? "device" : "devices"}`,
      metaUnobserved: true,
      targetId: null,
      childKeys,
      orphan: false,
    });
    roots.push(key);
    for (const d of [...unplaced].sort((a, b) => a.host.localeCompare(b.host))) {
      childKeys.push(addDevice(key, 2, d.host));
    }
  }

  const posInSet = new Map<string, number>();
  roots.forEach((k, i) => posInSet.set(k, i + 1));
  for (const row of rows.values()) row.childKeys.forEach((k, i) => posInSet.set(k, i + 1));
  return { rows, roots, posInSet, linkById };
}

/** A row as shown: a link row gets its wording here, the first time it is on screen. */
function shownRow(model: TreeModel, row: Row): Row {
  if (row.kind !== "link" || row.meta !== "" || row.targetId === null) return row;
  const link = model.linkById.get(row.targetId);
  if (link === undefined) return row;
  const cut = linkCutMeta(link);
  row.meta = cut.text;
  row.metaUnobserved = cut.unobserved;
  return row;
}

export interface FabricA11yTreeProps {
  devices: readonly Device[];
  links: readonly Link[];
  tiers: readonly (readonly string[])[];
  /** Pinned open by the stage's "Fabric list" control. When false the tree is clipped but still
   *  focusable, and un-clips itself on focus so the ring is actually visible (WCAG 2.4.7). */
  visible: boolean;
  onHide(): void;
  onFocusDevice(id: string): void;
}

export function FabricA11yTree({
  devices,
  links,
  tiers,
  visible,
  onHide,
  onFocusDevice,
}: FabricA11yTreeProps) {
  const domId = useId();
  const model = useMemo(() => buildModel(devices, links, tiers), [devices, links, tiers]);

  /* Link lists closed, and tiers open only while their devices fit TREE_OPEN_DEVICE_BUDGET. */
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => initiallyOpen(model));
  const [activeKey, setActiveKey] = useState<string | null>(() => model.roots[0] ?? null);
  const [focusReq, setFocusReq] = useState(0);
  /** The row a focus request is for. Read only when `focusReq` changes — see the focus effect. */
  const focusTarget = useRef<string | null>(null);
  /**
   * A link appears twice, once under each endpoint. The copy the user activated is the one that
   * stays selected and keeps the roving tabindex; without this the FIRST copy in model order won,
   * which expanded the other endpoint unasked and moved focus there (a11y audit D6).
   */
  const [linkOrigin, setLinkOrigin] = useState<string | null>(null);

  const storeDeviceId = useInvestigation((s) => s.deviceId);
  const storeLinkId = useInvestigation((s) => s.linkId);

  const elsRef = useRef(new Map<string, HTMLDivElement>());
  const typeahead = useRef<{ buffer: string; timer: number }>({ buffer: "", timer: 0 });

  const visibleRows = useMemo(() => {
    const out: Row[] = [];
    const walk = (keys: readonly string[]) => {
      for (const k of keys) {
        const row = model.rows.get(k);
        if (!row) continue;
        out.push(shownRow(model, row));
        if (row.childKeys.length > 0 && expanded.has(k)) walk(row.childKeys);
      }
    };
    walk(model.roots);
    return out;
  }, [model, expanded]);

  const selectedKey = useMemo(() => {
    if (storeLinkId !== null) {
      const copies: string[] = [];
      for (const row of model.rows.values()) {
        if (row.kind === "link" && row.targetId === storeLinkId) copies.push(row.key);
      }
      // The activated copy, else the first — a selection made on the canvas has no origin in the
      // tree, so it falls through to model order. (Not "the copy the reader is on": the effect
      // below moves the roving tabindex to the selected row, so keying on it would snap arrow
      // navigation back to copy one the moment the reader left copy two.)
      if (linkOrigin !== null && copies.includes(linkOrigin)) return linkOrigin;
      return copies[0] ?? null;
    }
    if (storeDeviceId !== null) return model.rows.has(`device:${storeDeviceId}`) ? `device:${storeDeviceId}` : null;
    return null;
  }, [model, storeDeviceId, storeLinkId, linkOrigin]);

  /* A selection made in 3-D has to be reachable here without the user hunting for it: open its
     ancestors and move the roving tabindex, but never steal focus — the canvas still has it. */
  useEffect(() => {
    if (selectedKey === null) return;
    setExpanded((prev) => {
      const next = new Set(prev);
      let cursor = model.rows.get(selectedKey)?.parent ?? null;
      let changed = false;
      while (cursor !== null) {
        if (!next.has(cursor)) {
          next.add(cursor);
          changed = true;
        }
        cursor = model.rows.get(cursor)?.parent ?? null;
      }
      return changed ? next : prev;
    });
    setActiveKey(selectedKey);
  }, [model, selectedKey]);

  /* Keyed on the REQUEST only. Keyed on `activeKey` too, every later selection made elsewhere (a
     canvas pick moves the roving tabindex) pulled focus into the tree once the user had arrowed
     through it even once — the "never steal focus" rule above, broken by a dependency list. */
  useEffect(() => {
    const key = focusTarget.current;
    if (focusReq === 0 || key === null) return;
    const el = elsRef.current.get(key);
    if (!el) return;
    el.focus();
    // jsdom has no layout, so scrollIntoView is absent there; the tree must still work in tests.
    if (typeof el.scrollIntoView === "function") el.scrollIntoView({ block: "nearest" });
  }, [focusReq]);

  useEffect(
    () => () => {
      if (typeahead.current.timer !== 0) window.clearTimeout(typeahead.current.timer);
    },
    [],
  );

  const move = useCallback((key: string) => {
    focusTarget.current = key;
    setActiveKey(key);
    setFocusReq((n) => n + 1);
  }, []);

  const setOpen = useCallback((key: string, open: boolean) => {
    setExpanded((prev) => {
      if (prev.has(key) === open) return prev;
      const next = new Set(prev);
      if (open) next.add(key);
      else next.delete(key);
      return next;
    });
  }, []);

  const activate = useCallback(
    (row: Row, withCamera: boolean) => {
      const st = useInvestigation.getState();
      if (row.kind === "tier") {
        setOpen(row.key, !expanded.has(row.key));
        return;
      }
      if (row.targetId === null) return; // a row naming a host with no record selects nothing
      if (row.kind === "device") {
        st.selectDevice(row.targetId, { surface: "fabric" });
        if (withCamera) onFocusDevice(row.targetId);
      } else {
        setLinkOrigin(row.key);
        st.selectLink(row.targetId);
      }
    },
    [expanded, onFocusDevice, setOpen],
  );

  const onKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.altKey || e.metaKey) return;
    const index = visibleRows.findIndex((r) => r.key === activeKey);
    const row = index >= 0 ? visibleRows[index] : undefined;

    switch (e.key) {
      case "ArrowDown": {
        e.preventDefault();
        const next = visibleRows[Math.min(visibleRows.length - 1, index + 1)];
        if (next) move(next.key);
        return;
      }
      case "ArrowUp": {
        e.preventDefault();
        const next = visibleRows[Math.max(0, index - 1)];
        if (next) move(next.key);
        return;
      }
      case "ArrowRight": {
        e.preventDefault();
        if (!row) return;
        if (row.childKeys.length === 0) return;
        if (!expanded.has(row.key)) setOpen(row.key, true);
        else {
          const first = row.childKeys[0];
          if (first) move(first);
        }
        return;
      }
      case "ArrowLeft": {
        e.preventDefault();
        if (!row) return;
        if (row.childKeys.length > 0 && expanded.has(row.key)) setOpen(row.key, false);
        else if (row.parent !== null) move(row.parent);
        return;
      }
      case "Home": {
        e.preventDefault();
        const first = visibleRows[0];
        if (first) move(first.key);
        return;
      }
      case "End": {
        e.preventDefault();
        const last = visibleRows[visibleRows.length - 1];
        if (last) move(last.key);
        return;
      }
      case "Enter": {
        e.preventDefault();
        if (row) activate(row, true);
        return;
      }
      case " ": {
        e.preventDefault();
        if (row) activate(row, false);
        return;
      }
      case "*": {
        // APG: expand every sibling of the focused node.
        e.preventDefault();
        if (!row) return;
        const siblings = visibleRows.filter((r) => r.parent === row.parent && r.childKeys.length > 0);
        setExpanded((prev) => {
          const next = new Set(prev);
          for (const s of siblings) next.add(s.key);
          return next;
        });
        return;
      }
      case "Escape": {
        e.preventDefault();
        onHide();
        return;
      }
      default:
        break;
    }

    if (e.key.length === 1 && /\S/.test(e.key) && !e.ctrlKey) {
      e.preventDefault();
      const buf = typeahead.current;
      buf.buffer += e.key.toLowerCase();
      if (buf.timer !== 0) window.clearTimeout(buf.timer);
      buf.timer = window.setTimeout(() => {
        buf.buffer = "";
        buf.timer = 0;
      }, TYPEAHEAD_MS);
      const from = index < 0 ? 0 : index;
      for (let i = 1; i <= visibleRows.length; i += 1) {
        const candidate = visibleRows[(from + i) % visibleRows.length];
        if (candidate && candidate.label.toLowerCase().startsWith(buf.buffer)) {
          move(candidate.key);
          return;
        }
      }
      /* Nothing on screen matches: look inside the collapsed tiers too, in tree order, and open the
         one that holds the match. A tier collapsed only because the fabric is large must not hide its
         devices from the one gesture that finds a device by name. */
      for (const tierKey of model.roots) {
        const tier = model.rows.get(tierKey);
        if (!tier || expanded.has(tierKey)) continue;
        const hit = tier.childKeys.find((k) => model.rows.get(k)?.label.toLowerCase().startsWith(buf.buffer) === true);
        if (hit !== undefined) {
          setOpen(tierKey, true);
          move(hit);
          return;
        }
      }
    }
  };

  const uncollected = devices.filter((d) => !d.collected).length;
  const deadInventoried = devices.filter((d) => d.collection === "not collected").length;
  const partial = devices.filter((d) => d.collection === "partial").length;
  /* Tiers that are collapsed right now and hold devices, so the reader is told what is not listed. */
  const collapsed = model.roots
    .map((k) => model.rows.get(k))
    .filter((r): r is Row => r !== undefined && !expanded.has(r.key) && r.childKeys.length > 0);
  const collapsedDevices = collapsed.reduce((n, r) => n + r.childKeys.length, 0);
  const unmeasured = links.filter((l) => l.isBridge === null).length;
  /* Decided against the rows actually rendered: an active key that is stale or hidden under a
     collapsed ancestor must not leave the tree with no tab stop (FabricA11yTree.tabstop.test.tsx). */
  const rovingKey = visibleRows.some((r) => r.key === activeKey) ? activeKey : (visibleRows[0]?.key ?? null);

  return (
    <section
      className="fabric3d__tree"
      data-stage-overlay=""
      data-hidden={visible ? "false" : "true"}
      data-testid="fabric3d-tree"
      aria-labelledby={`${domId}-title`}
    >
      <div className="fabric3d__tree-head">
        <h2 className="fabric3d__tree-title" id={`${domId}-title`}>
          Fabric list
        </h2>
        <button type="button" className="fabric3d__btn" onClick={onHide}>
          Hide
        </button>
      </div>

      <div className="fabric3d__tree-scroll">
        <div
          role="tree"
          aria-labelledby={`${domId}-title`}
          aria-describedby={collapsed.length === 0 ? `${domId}-gestures` : `${domId}-gestures ${domId}-collapsed`}
          aria-multiselectable={false}
          onKeyDown={onKeyDown}
        >
          {visibleRows.map((row) => {
            const siblings =
              row.parent === null
                ? model.roots
                : (model.rows.get(row.parent)?.childKeys ?? []);
            const pos = model.posInSet.get(row.key) ?? 0;
            const isSelected = row.key === selectedKey;
            return (
              <div
                key={row.key}
                role="treeitem"
                id={`${domId}-${row.key}`}
                className="fabric3d__treeitem"
                data-kind={row.kind}
                data-testid={`fabric3d-tree-${row.kind}`}
                data-target={row.targetId ?? ""}
                aria-level={row.level}
                aria-posinset={pos > 0 ? pos : 1}
                aria-setsize={siblings.length || 1}
                aria-selected={row.targetId === null ? undefined : isSelected}
                aria-disabled={row.orphan ? true : undefined}
                {...(row.childKeys.length > 0 ? { "aria-expanded": expanded.has(row.key) } : {})}
                tabIndex={row.key === rovingKey ? 0 : -1}
                style={{ paddingInlineStart: `calc(var(--sp-2) + ${row.level - 1} * var(--sp-3))` }}
                ref={(el) => {
                  if (el) elsRef.current.set(row.key, el);
                  else elsRef.current.delete(row.key);
                }}
                onClick={() => {
                  setActiveKey(row.key);
                  activate(row, false);
                }}
                onDoubleClick={() => activate(row, true)}
                onFocus={() => setActiveKey(row.key)}
              >
                <span className="fabric3d__tw" aria-hidden="true">
                  {row.childKeys.length === 0 ? "" : expanded.has(row.key) ? "▾" : "▸"}
                </span>
                <span className="fabric3d__tree-label">{row.label}</span>
                <span className="fabric3d__tree-meta" data-unobserved={row.metaUnobserved ? "true" : "false"}>
                  {row.meta}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* GESTURE PARITY (a11y audit D6, 2026-09-21). An audit compared tree Enter with a single
          canvas click and found the camera moved for one and not the other. The two routes were
          never meant to be those two: each gesture here mirrors the SAME gesture on the canvas.
          Click or Space selects and leaves the camera where it is (canvas: click); double-click or
          Enter selects and frames the device (canvas: double-click, or Enter on the stage). The
          mapping was only discoverable by reading this file, so it is now stated to every user and
          wired as the tree's description. Pinned by FabricA11yTree.parity.test.tsx. */}
      <p className="fabric3d__tree-foot">
        {devices.length} devices, {links.length} links. {uncollected} not collected
        {deadInventoried === 0 ? " (topology only)" : ` (${deadInventoried} inventoried with no usable output, the rest topology only)`}
        {partial === 0 ? "" : `, ${partial} collected only partially`}.{" "}
        {unmeasured} links have no centrality measurement, so whether cutting them partitions the
        fabric is unknown.
      </p>
      {collapsed.length === 0 ? null : (
        <p className="fabric3d__tree-foot" id={`${domId}-collapsed`} data-testid="fabric3d-tree-collapsed">
          {collapsedDevices} {collapsedDevices === 1 ? "device is" : "devices are"} in{" "}
          {collapsed.length} collapsed {collapsed.length === 1 ? "tier" : "tiers"} (
          {collapsed.map((r) => `${r.label}: ${r.childKeys.length}`).join(", ")}). Tiers start open only while they
          hold {TREE_OPEN_DEVICE_BUDGET} devices or fewer between them; Right arrow opens a tier, and typing a name
          finds a device in any tier.
        </p>
      )}
      <p className="fabric3d__tree-foot fabric3d__tree-gestures" id={`${domId}-gestures`}>
        {TREE_GESTURES}
      </p>
    </section>
  );
}

/* ── link-cut wording (kept in this tracked module: the Fabric list and the live announcement in
   Fabric3D.tsx share it) ── */
/**
 * what the NON-CANVAS channels (the live announcement, the Fabric list) may say about
 * cutting a link.
 *
 * Both used to read the snapshot's `isBridge` flag and state it as fact: "Cutting this link
 * partitions the fabric." MEASURED (audit A6, real canvas click on L7): the announcement said that,
 * while the Inspector for the same link said its blast radius is NOT DETERMINABLE, because L7
 * shares core1 Gi1/0/40 with L26 and whether L7 exists at all is disputed. The disagreement was
 * shown to sighted readers and hidden from everyone else.
 *
 * So the sentence is built from the SAME `linkFailureImpact` the Inspector reads, with its
 * certainty, and when the snapshot's flag and our computation part ways the sentence names both.
 */

/* The snapshot is immutable for the life of the page, so one computation per link is enough; the
   Fabric list asks for every link at once. */
const linkImpactCache = new Map<string, LinkFailureResult>();
function impactOf(id: string): LinkFailureResult {
  let r = linkImpactCache.get(id);
  if (r === undefined) {
    r = linkFailureImpact(id);
    linkImpactCache.set(id, r);
  }
  return r;
}

const snapshotSays = (b: boolean | null): string =>
  b === null
    ? "The snapshot did not compute whether cutting this link partitions the fabric."
    : b
      ? "The snapshot says cutting this link partitions the fabric."
      : "The snapshot says a redundant path exists around this link.";

const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;

/** The full sentence(s), for the live region that is the only channel a screen-reader user has. */
export function linkCutSentence(link: Pick<Link, "id" | "isBridge">): string {
  const r = impactOf(link.id);
  const snap = link.isBridge;
  if (r.certainty === "not-determinable" || r.isBridge === null) {
    // `claim` is the Inspector's own sentence, naming why (a disputed cable, an uncollected end).
    const ours = `Our computation cannot decide it. ${r.claim}`;
    return `${snapshotSays(snap)} ${ours}`;
  }
  const qual = r.certainty === "observed" ? "" : ` This is ${r.certainty}; the Inspector lists the other projections.`;
  const verdict = r.isBridge
    ? `cutting it partitions the fabric, stranding ${r.newlyStranded.length === 0 ? "no host" : plural(r.newlyStranded.length, "host", "hosts")}.`
    : "a redundant path exists around it.";
  const lead = snap === null ? "Our computation finds" : snap === r.isBridge ? "Our computation agrees:" : "Our computation disagrees:";
  return `${snapshotSays(snap)} ${lead} ${verdict}${qual}`;
}

/**
 * The short tag for a Fabric-list row, and whether it is a definite (observed) statement.
 *
 * The row may not say less than the cable draws. MEASURED (independent acceptance D6, 2026-09-22):
 * L34 and L35 have no observed operational state, and the fabric draws them with the state-unknown
 * pattern, while this row said only "centrality not computed" — true (a link with no observed
 * state is outside the connectivity graph, so nothing computed its centrality), but not what the
 * canvas shows. Every claim the drawn pattern makes (`classifyLink(link).drawnClaims`, set in the
 * same branch that picks the pattern) is therefore carried here, leading, unless the cut wording
 * already states it.
 */
export function linkCutMeta(link: Link): { text: string; unobserved: boolean } {
  const cut = cutMeta(link);
  const missing = classifyLink(link).drawnClaims.filter((c) => !cut.text.includes(c.key));
  if (missing.length === 0) return cut;
  return {
    text: [...missing.map((c) => c.words), cut.text].join(" · "),
    unobserved: cut.unobserved || missing.some((c) => c.gap),
  };
}

function cutMeta(link: Pick<Link, "id" | "isBridge" | "opStatus">): { text: string; unobserved: boolean } {
  const r = impactOf(link.id);
  const snap = link.isBridge;
  if (r.certainty === "not-determinable" || r.isBridge === null) {
    return snap === null
      ? { text: "centrality not computed", unobserved: true }
      : { text: snap ? "snapshot: cut partitions; ours: undecided" : "cut impact not determinable", unobserved: true };
  }
  if (snap !== null && snap !== r.isBridge) return { text: "cut impact disputed", unobserved: true };
  const uncertain = r.certainty !== "observed";
  if (r.isBridge) return { text: uncertain ? "cut partitions fabric (uncertain)" : "cut partitions fabric", unobserved: uncertain };
  return { text: `state ${link.opStatus}`, unobserved: link.opStatus === "unknown" };
}
