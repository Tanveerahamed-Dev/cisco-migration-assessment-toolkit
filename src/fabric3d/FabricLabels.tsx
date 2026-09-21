/**
 * FabricLabels.tsx — DOM text over 3-D anchors.
 *
 * Canvas text at 11 px is the single loudest "this is a demo" tell: it is resampled by the
 * composer, it fights SMAA, and it cannot use the UI font stack. DOM labels stay crisp, inherit the
 * type tokens, and cost nothing on the GPU. The price is that they must be positioned every frame,
 * which is why nothing in this file re-renders React on a frame tick — the loop writes transforms
 * straight to the element.
 *
 * Declutter drops labels rather than overlapping them. Half-legible overlapping text reads as
 * unfinished, and fading to 50 % opacity produces the muddy result the brief rejects by name. The
 * selected and hovered nodes are exempt: whatever else is dropped, the thing the user is pointing
 * at is labelled.
 */
import { useEffect, useMemo, useRef, useSyncExternalStore, type RefObject } from "react";

import { linksByHost } from "../core/data";
import type { Device } from "../core/types";

import type { FabricScene } from "./contract";

/** Gutter (CSS px) between two placed label boxes. Below this they read as one smear. */
const DECLUTTER_GUTTER = 4;

export interface HoverState {
  deviceId: string | null;
  linkId: string | null;
}

/**
 * Hover is a per-pointer-move value and it must not re-render the stage. It lives in this tiny
 * external store so exactly one component — the label layer — subscribes to it.
 */
export interface HoverChannel {
  get(): HoverState;
  set(next: HoverState): void;
  subscribe(onChange: () => void): () => void;
}

const EMPTY_HOVER: HoverState = { deviceId: null, linkId: null };
const EMPTY_SET: ReadonlySet<string> = new Set<string>();

export function createHoverChannel(): HoverChannel {
  let state: HoverState = EMPTY_HOVER;
  const listeners = new Set<() => void>();
  return {
    get: () => state,
    set: (next) => {
      // Reference stability matters: useSyncExternalStore re-renders on every identity change,
      // and pointermove would otherwise re-render on every event that resolves to the same node.
      if (next.deviceId === state.deviceId && next.linkId === state.linkId) return;
      state = next;
      for (const l of listeners) l();
    },
    subscribe: (onChange) => {
      listeners.add(onChange);
      return () => listeners.delete(onChange);
    },
  };
}

interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

const intersects = (a: Box, b: Box): boolean =>
  a.x < b.x + b.w + DECLUTTER_GUTTER &&
  a.x + a.w + DECLUTTER_GUTTER > b.x &&
  a.y < b.y + b.h + DECLUTTER_GUTTER &&
  a.y + a.h + DECLUTTER_GUTTER > b.y;

export interface FabricLabelsProps {
  devices: readonly Device[];
  sceneRef: RefObject<FabricScene | null>;
  /** Bumped when the scene instance is replaced, so the loop re-attaches to the live handle. */
  epoch: number;
  hover: HoverChannel;
  selectedId: string | null;
  /**
   * The host where the traced packet's story ends, AND WHICH OF THE THREE ENDINGS IT IS.
   *
   * The label layer needs to know, because the canvas alarm is a halo at the node ANCHOR and the
   * label box is positioned on that same anchor, so the box occludes the thing it is next to.
   * Measured on the release build: the entire visual difference between a DENIED trace and a
   * DELIVERED one was an 18×23 px region — thin slivers of red above and below the `core1` label.
   * A reader could not tell a blocked path from a successful one.
   *
   * The KIND is not decoration; it is the whole claim. The scene has ONE alarm channel and a trace
   * has THREE endings, so the canvas alone cannot say which it is:
   *
   *   blocked      — the engine names the rule or the absent route that stopped this packet.
   *   undetermined — the simulation ran and DECLINED TO DECIDE. Measured before this existed: an
   *                  indeterminate trace rendered byte-identically to a denied one, alarm word and
   *                  all, while the side panel for the same trace said INDETERMINATE.
   *   delivered    — the packet arrived here. Measured before this existed: with the terminating
   *                  host already selected, a delivered trace produced a canvas byte-identical to
   *                  no trace at all — a successful result with no mark of its own anywhere on the
   *                  fabric.
   */
  alarm?: { id: string; kind: "blocked" | "undetermined" | "delivered" } | null;
  /**
   * The articulation point whose failure is being projected (A6) — a SEPARATE channel from `alarm`
   * on purpose. It is a hypothesis about a failure that has not happened; the alarm is a fact about
   * the packet in front of the reader. While the two shared one slot, the winner erased the loser,
   * so a delivered flow over a cut point could say only one of the two true things about that host.
   */
  cutPointId?: string | null;
  /** Hosts that become unreachable if the current selection fails (A6). Marked, and never dropped
   *  by the declutter before an unaffected label is. */
  strandedIds?: ReadonlySet<string>;
  /**
   * Which space `scene.project()` reports in.
   *
   * The default is "canvas" because that is what the scene actually contracts: scene.ts's
   * projectDevice() divides by the renderer's own width/height and documents the result as
   * "Canvas-relative CSS pixels". `pick()` taking CLIENT coordinates is the asymmetry — it is an
   * input fed straight from a PointerEvent, not an output — and reasoning from pick() to project()
   * is what previously made this default "client" and drew every label one canvas-origin
   * (~340px, ~120px at 1920x1080) up and to the left of the device it names.
   *
   * Keep this defaulted to the scene's real contract. A caller only sets "client" for a scene that
   * projects into page space, and no scene in this app does.
   */
  coordinateSpace?: "client" | "canvas";
}

/** How far above the anchor a label sits, as a multiple of its own height. The blocked host's
 *  label clears the alarm halo entirely rather than sitting on top of it. */
const LIFT = 1.6;
const LIFT_BLOCKED = 3;

export function FabricLabels({
  devices,
  sceneRef,
  epoch,
  hover,
  selectedId,
  alarm = null,
  cutPointId = null,
  strandedIds,
  coordinateSpace = "canvas",
}: FabricLabelsProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const elsRef = useRef(new Map<string, HTMLSpanElement>());
  const sizesRef = useRef(new Map<string, { w: number; h: number }>());
  const writtenRef = useRef(new Map<string, string>());

  const hoverState = useSyncExternalStore(hover.subscribe, hover.get, () => EMPTY_HOVER);
  const hoveredId = hoverState.deviceId;

  const selectedRef = useRef(selectedId);
  selectedRef.current = selectedId;
  const hoveredRef = useRef(hoveredId);
  hoveredRef.current = hoveredId;

  /* Resolved against BOTH keys, because `id` and `host` are separate fields and the rest of this
     application never assumes they agree. */
  const alarmed = useMemo((): { id: string; kind: "blocked" | "undetermined" | "delivered" } | null => {
    if (alarm === null) return null;
    const d = devices.find((x) => x.id === alarm.id || x.host === alarm.id);
    return d === undefined ? null : { id: d.id, kind: alarm.kind };
  }, [alarm, devices]);

  /** Resolved the same way, and for the same reason: `id` and `host` are separate fields. */
  const cutPoint = useMemo((): string | null => {
    if (cutPointId === null) return null;
    const d = devices.find((x) => x.id === cutPointId || x.host === cutPointId);
    return d === undefined ? null : d.id;
  }, [cutPointId, devices]);

  const stranded = useMemo((): ReadonlySet<string> => {
    if (strandedIds === undefined || strandedIds.size === 0) return EMPTY_SET;
    const out = new Set<string>();
    for (const d of devices) if (strandedIds.has(d.id) || strandedIds.has(d.host)) out.add(d.id);
    return out;
  }, [strandedIds, devices]);

  const alarmRef = useRef(alarmed);
  alarmRef.current = alarmed;
  const cutRef = useRef(cutPoint);
  cutRef.current = cutPoint;
  const strandedRef = useRef(stranded);
  strandedRef.current = stranded;

  /** Busiest first, then by host. Both keys are stable, so the set of surviving labels is the same
   *  on every run of the same camera pose (acceptance F6). */
  const baseOrder = useMemo(
    () =>
      [...devices]
        .sort((a, b) => {
          const da = linksByHost.get(a.host)?.length ?? 0;
          const db = linksByHost.get(b.host)?.length ?? 0;
          return db - da || a.host.localeCompare(b.host);
        })
        .map((d) => d.id),
    [devices],
  );

  useEffect(() => {
    const els = elsRef.current;
    const sizes = sizesRef.current;
    const written = writtenRef.current;
    const placed: Box[] = [];
    const seq: string[] = [];
    let frame = 0;

    const hide = (id: string, el: HTMLSpanElement) => {
      if (written.get(id) === "hidden") return;
      written.set(id, "hidden");
      el.dataset.visible = "false";
    };

    const tick = () => {
      frame = requestAnimationFrame(tick);
      const scene = sceneRef.current;
      const container = containerRef.current;
      if (!scene || !container) return;

      const rect = container.getBoundingClientRect();
      const originX = coordinateSpace === "client" ? rect.left : 0;
      const originY = coordinateSpace === "client" ? rect.top : 0;

      const sel = selectedRef.current;
      const hov = hoveredRef.current;
      const alm = alarmRef.current;
      const blk = alm?.id ?? null;
      const cut = cutRef.current;
      const str = strandedRef.current;
      /* Placement order IS the declutter priority: earlier entries claim their box first. The
         failing host and the hosts that go dark behind it are the answer to the question on
         screen, so they are placed before the merely busy ones — otherwise a high-degree node
         nobody asked about can take the box and the answer gets dropped. */
      seq.length = 0;
      const pushed = new Set<string>();
      const push = (id: string | null): void => {
        if (id === null || pushed.has(id)) return;
        pushed.add(id);
        seq.push(id);
      };
      push(sel);
      push(hov);
      push(blk);
      push(cut);
      for (const id of baseOrder) if (str.has(id)) push(id);
      for (const id of baseOrder) push(id);
      placed.length = 0;

      for (let i = 0; i < seq.length; i += 1) {
        const id = seq[i];
        if (id === undefined) continue;
        const el = els.get(id);
        if (!el) continue;

        const p = scene.project(id);
        // An anchor behind the camera or occluded by a chassis reports invisible. Drawing its label
        // anyway would attach a hostname to a device the viewer cannot see.
        if (!p || !p.visible) {
          hide(id, el);
          continue;
        }

        /* THE MARKS ARE APPLIED BEFORE THE BOX IS MEASURED, and this order is load-bearing. The
           `stranded` / `cut point` marks are shown by CSS off these attributes, so a label that
           gains one gets WIDER. Writing them after the measurement — where the rest of the state
           is written — meant the declutter pass tested a box narrower than the label it was about
           to draw, and two marked labels smeared into each other. Any change of shape drops the
           cached size with it. */
        const isAlarmed = id === blk;
        const isCut = id === cut;
        const wantAlarm = isAlarmed && alm !== null ? alm.kind : "";
        const wantCut = isCut ? "yes" : "";
        const wantStranded = str.has(id) ? "yes" : "";
        if (
          el.dataset.alarm !== wantAlarm ||
          el.dataset.cut !== wantCut ||
          el.dataset.stranded !== wantStranded
        ) {
          el.dataset.alarm = wantAlarm;
          el.dataset.cut = wantCut;
          el.dataset.stranded = wantStranded;
          sizes.delete(id);
          written.delete(id);
        }

        let size = sizes.get(id);
        if (!size) {
          // offsetWidth is valid while the element is `visibility: hidden` (it still has layout),
          // which is why hiding uses visibility and not display.
          size = { w: el.offsetWidth, h: el.offsetHeight };
          if (size.w > 0) sizes.set(id, size);
        }

        const x = Math.round(p.x - originX);
        const y = Math.round(p.y - originY);
        /* The blocked host's label lifts clear of the alarm halo drawn at its anchor. Sitting on
           the anchor is what reduced a denied trace to slivers of red around a hostname. */
        const lift = isAlarmed || isCut ? LIFT_BLOCKED : LIFT;
        const box: Box = { x: x - size.w / 2, y: y - size.h * lift, w: size.w, h: size.h };

        // The marked host is never dropped: it is the one thing the picture has to say.
        const forced = id === sel || id === hov || isAlarmed || isCut;
        if (!forced && placed.some((b) => intersects(box, b))) {
          hide(id, el);
          continue;
        }
        placed.push(box);

        /* `state` stays what it always was. The alarm and the stranded mark are SEPARATE channels
           written above, because a host can be selected and alarmed at once and neither statement
           may overwrite the other. */
        const state = id === sel ? "selected" : id === hov ? "hover" : "";
        const key = `${x}:${y}:${state}:${wantStranded}:${wantCut}:${wantAlarm}`;
        if (written.get(id) === key) continue;
        written.set(id, key);
        el.dataset.visible = "true";
        el.dataset.state = state;
        el.style.transform = `translate3d(${x}px, ${y}px, 0) translate(-50%, ${-100 * lift}%)`;
      }
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
    // `epoch` is a dependency so a replaced scene gets a fresh loop rather than a stale handle.
  }, [baseOrder, coordinateSpace, epoch, sceneRef]);

  /* Web-font metrics land after first paint; a stale width makes the declutter reject labels that
     would in fact fit. Clearing the cache is enough — the next tick re-measures. */
  useEffect(() => {
    const fonts = typeof document === "undefined" ? undefined : document.fonts;
    if (!fonts) return;
    let live = true;
    void fonts.ready.then(() => {
      if (live) sizesRef.current.clear();
    });
    return () => {
      live = false;
    };
  }, []);

  return (
    <div
      className="fabric3d__labels"
      ref={containerRef}
      /* The fabric tree is the accessible equivalent of this view (acceptance D6). Exposing the
         labels too would read every hostname twice. */
      aria-hidden="true"
      data-testid="fabric3d-labels"
    >
      {devices.map((d) => (
        <span
          key={d.id}
          className="fabric3d-label"
          data-device={d.id}
          data-visible="false"
          data-state=""
          data-stranded=""
          data-cut=""
          data-alarm=""
          ref={(el) => {
            if (el) elsRef.current.set(d.id, el);
            else {
              elsRef.current.delete(d.id);
              sizesRef.current.delete(d.id);
              writtenRef.current.delete(d.id);
            }
          }}
        >
          <span className="fabric3d-label__name">{d.host}</span>
          {/* SECOND CHANNEL FOR THE HEALTH BAND (acceptance D8). On the canvas the band is carried
              by chassis colour, and the five band tokens are 1.12–1.14:1 apart in greyscale — which
              is to say indistinguishable to a deuteranope, in monochrome print, or on a projector.
              The letter is the same device the severity badge already uses (shape + C/H/M/L/I): it
              survives greyscale, it is co-located with the device it describes, and the legend
              names it. `band === null` prints its own mark rather than nothing, because a missing
              letter would read as "no problems here". */}
          {d.band === null ? (
            <span className="fabric3d-label__band" data-band="none" title="Health band not observed">
              ?
            </span>
          ) : (
            <span className="fabric3d-label__band" data-band={d.band} title={`Health band ${d.band}`}>
              {d.band.slice(0, 1)}
            </span>
          )}
          {d.collected ? null : (
            <span className="fabric3d-label__unobserved">not collected</span>
          )}
          {/* THE ANALYSIS STATES, IN WORDS AND A GLYPH. Each was previously carried on the canvas
              by colour alone — a red halo at the anchor for the failing host, and nothing at all
              for a stranded one. A halo behind an opaque label box is not a channel, and a colour
              is not a channel on its own (D8).

              `data-alarm` carries the TRACE's ending and exactly one of its three words shows at a
              time. They are three distinct claims and the fabric may not blur them: `blocked` says
              a rule or a missing route stopped this packet; `undecided` says the simulation ran
              and refused to decide, which is a finding about our evidence and NOT a failure of the
              network; `delivered here` says the packet arrived. `data-cut` is a separate attribute
              carrying a separate claim — a hypothetical — so a delivered flow over an articulation
              point can say both true things at once instead of one of them silently winning.
              CSS hides every mark at the empty value, so an unaffected label is what it was. */}
          <span className="fabric3d-label__alarm fabric3d-label__alarm--blocked" title="This host stopped the traced flow">
            <span aria-hidden="true">✕</span> blocked
          </span>
          <span
            className="fabric3d-label__alarm fabric3d-label__alarm--undetermined"
            title="The simulation reached this host and declined to decide the flow. Not a drop, not a delivery."
          >
            <span aria-hidden="true">?</span> undecided
          </span>
          <span
            className="fabric3d-label__alarm fabric3d-label__alarm--delivered"
            title="The traced flow reached its destination at this host"
          >
            <span aria-hidden="true">✓</span> delivered here
          </span>
          <span
            className="fabric3d-label__alarm fabric3d-label__alarm--cut"
            title="Removing this host would cut other hosts off the fabric"
          >
            <span aria-hidden="true">⚠</span> cut point
          </span>
          <span className="fabric3d-label__stranded" title="Unreachable if the current selection fails">
            <span aria-hidden="true">⊘</span> stranded
          </span>
        </span>
      ))}
    </div>
  );
}
