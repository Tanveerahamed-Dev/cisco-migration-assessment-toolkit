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
import { useDeferredValue, useEffect, useMemo, useRef, useSyncExternalStore, type CSSProperties, type RefObject } from "react";

import { failureImpact } from "../analysis/blast";
import { releaseFocusFrom } from "../app/focus-return";
import { presentBand } from "../core/band-qualification";
import { linksByHost } from "../core/data";
import type { Device } from "../core/types";

import type { FabricScene } from "./contract";
import { LABEL_DROP_EVERY_FRAMES } from "./emphasis";
import { labelDwellVerdict, labelSettleMayReverse, labelUrgent } from "./labelResolve";

/** Gutter (CSS px) between two placed label boxes, side by side. Below this they read as one smear. */
const DECLUTTER_GUTTER = 4;
/** The same between two label ROWS, one above the other. 6, was the shared 4: less the hysteresis
 *  that left two SHOWN rows 1 px apart, and access9/access7 read as one stacked plate with their
 *  band badges touching (C5 critic, low orbit). Now >= 3 px. Vertical only — widening the side
 *  gutter as well cost wan-edge-rtr1.lab its name next to dist1's. */
const DECLUTTER_ROW_GUTTER = 6;
/** Declutter hysteresis (CSS px). Kept under the gutter, so two SHOWN labels still never touch. */
const DECLUTTER_HYSTERESIS = 3;

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

/** Plain overlap with a small pad, for a 1 px leader line against a label box. */
const LEADER_PAD = 2;
const touches = (a: Box, b: Box): boolean =>
  a.x < b.x + b.w + LEADER_PAD && a.x + a.w + LEADER_PAD > b.x && a.y < b.y + b.h + LEADER_PAD && a.y + a.h + LEADER_PAD > b.y;

const intersects = (a: Box, b: Box): boolean =>
  a.x < b.x + b.w + DECLUTTER_GUTTER &&
  a.x + a.w + DECLUTTER_GUTTER > b.x &&
  a.y < b.y + b.h + DECLUTTER_ROW_GUTTER &&
  a.y + a.h + DECLUTTER_ROW_GUTTER > b.y;

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
  /** The certainty clause of the blast radius the stranded marks come from ("" when observed). A
   *  mark drawn from an uncertain radius says so on the mark itself (2026-09-22 critic, B1). */
  strandedQualifier?: string;
  /**
   * Told which stranded hosts this layer could NOT draw — their anchor is off the canvas or hidden,
   * or the declutter dropped them — as device ids in placement order, whenever that set changes
   * (acceptance A6: with the camera on a trace, 3 of core2's 8 stranded hosts were off the canvas
   * and nothing on the fabric said so). Never called per frame with an unchanged answer.
   */
  onStrandedUnseen?: (ids: readonly string[]) => void;
  /**
   * The selected finding and the hosts it names (acceptance A4). A finding is a THIRD kind of
   * subject, distinct from the device selection: selecting F030 used to call setHighlight with
   * access15 and change nothing on screen for it — its label stayed as it was (and at the default
   * pose was decluttered away entirely), so the fabric could not answer "where is this finding?".
   * Each named host's label now carries the finding's id as a mark of its own, and is never
   * dropped by the declutter.
   */
  finding?: { id: string; severity: string; hosts: ReadonlySet<string> } | null;
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
  /**
   * Called when an off-view pointer that HOLDS keyboard focus leaves the stage (its host came into
   * view — because the reader just activated it to frame the host, or because the stage was resized
   * or re-projected). The pointer stops being rendered as it goes, and a focused element that stops
   * being rendered drops focus to <body> (acceptance D3). The callback DECIDES NOTHING: it returns the
   * stage's stated successors, in order (Fabric3D: its canvas, now framing that host), and the layer
   * hands them to focus-return.ts's third door (`releaseFocusFrom`) BEFORE the pointer is hidden, so a
   * successor that refuses focus (an inert or unrendered canvas) falls through to the owner's own
   * order (the landmark around the pointer, then the nearest real tab stop), never to <body>.
   * MEASURED (independent verifier R5-V2): this was the one imperative hide in the product that
   * bypassed the owner, answered by a bare `canvas.focus()` that never checked the canvas took focus.
   */
  onPointerFocusLost?: () => readonly (HTMLElement | null | undefined)[] | void;
}

/** How far above the anchor a label sits, as a multiple of its own height. The blocked host's
 *  label clears the alarm halo entirely rather than sitting on top of it. */
const LIFT = 1.6;
const LIFT_BLOCKED = 3;
/** Where an off-canvas finding pointer's CENTRE is pinned, in from the stage edge, px. Wider than
 *  tall because the pointer is a horizontal chip. Only the DIRECTION's anchor: the placed box is then
 *  kept inside the stage by its measured size, and clear of every other layer on the stage. */
const POINTER_EDGE_X = 84;
const POINTER_EDGE_Y = 22;
/** Clearance between a pointer and another layer on the stage (the HUD, the Legend, the tree), px. */
const POINTER_GAP = 4;
/** Minimum clearance between a label and the stage edge, px. */
const LABEL_EDGE_PX = 4;
/** A name displaced further than this from its anchor gets a leader line back to it, px. */
const LEADER_MIN_PX = 6;
/** The zone around ANOTHER device's anchor a label may not cover, in multiples of label height:
 *  half-width, reach above the anchor, reach below it (the chassis hangs below its anchor). */
const CHASSIS_HALF_W = 1.1;
const CHASSIS_UP = 0.1;
const CHASSIS_DOWN = 1.1;
/** Pixels trimmed off each side of a projected chassis box: its corners are mostly empty screen. */
const CHASSIS_INSET_PX = 3;

export function FabricLabels({
  devices,
  sceneRef,
  epoch,
  hover,
  selectedId,
  alarm = null,
  cutPointId = null,
  strandedIds,
  strandedQualifier = "",
  onStrandedUnseen,
  finding = null,
  coordinateSpace = "canvas",
  onPointerFocusLost,
}: FabricLabelsProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const pointerLayerRef = useRef<HTMLDivElement | null>(null);
  const elsRef = useRef(new Map<string, HTMLSpanElement>());
  const sizesRef = useRef(new Map<string, { w: number; h: number; nameC: number }>());
  const writtenRef = useRef(new Map<string, string>());
  /** Edge-of-canvas pointers for finding hosts projected OFF the canvas (A4), by device id. */
  const pointerElsRef = useRef(new Map<string, HTMLButtonElement>());
  /** Each pointer's measured box (its text is the finding id and the host, so it is per finding). */
  const pointerSizesRef = useRef(new Map<string, { w: number; h: number }>());
  const focusLostRef = useRef(onPointerFocusLost);
  focusLostRef.current = onPointerFocusLost;

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
  const unseenCbRef = useRef(onStrandedUnseen);
  unseenCbRef.current = onStrandedUnseen;

  /** The finding's hosts resolved to device ids, by id OR host (the two are separate fields). */
  const findingHosts = useMemo((): ReadonlySet<string> => {
    if (finding === null || finding.hosts.size === 0) return EMPTY_SET;
    const out = new Set<string>();
    for (const d of devices) if (finding.hosts.has(d.id) || finding.hosts.has(d.host)) out.add(d.id);
    return out;
  }, [finding, devices]);
  const findingRef = useRef(findingHosts);
  findingRef.current = findingHosts;

  /* A6: the selected host whose failure the SNAPSHOT says strands hosts while our graph reproduces
     no partition ("engine-impact-only" — the same comparison the Inspector reads). Measured before
     this existed: access13's failure_impact claims 39 endpoints and 2 partitions, ours claims none,
     and the fabric drew no mark at all, so the 3-D view read the same as a device that breaks
     nothing. Deferred: this is a second opinion on the selection, not the selection itself, so it
     must never sit on the frame that presents a click or a grid keystroke (acceptance E3/E5). */
  const deferredSelected = useDeferredValue(selectedId);
  const disputed = useMemo((): string | null => {
    if (deferredSelected === null) return null;
    const d = devices.find((x) => x.id === deferredSelected || x.host === deferredSelected);
    if (d === undefined) return null;
    return failureImpact(d.host).engine.qualitative === "engine-impact-only" ? d.id : null;
  }, [deferredSelected, devices]);
  const disputedRef = useRef(disputed);
  disputedRef.current = disputed;

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
    /* Every leader line drawn this pass, as a thin box. A leader is ink on the stage like the label
       it belongs to: it was left out of the declutter, and MEASURED (C5 critic) wan-edge-rtr1.lab's
       leader struck straight through the 'AP-floor3-01' text. */
    const leaders: Box[] = [];
    const chassis: (Box & { id: string; blocksOwn: boolean })[] = [];
    const homes: (Box & { id: string; released: boolean })[] = [];
    const bindings: { id: string; x: number; y: number }[] = [];
    const seq: string[] = [];
    let frame = 0;

    /* The stage width, kept current by a ResizeObserver instead of read from layout every frame
       (see the tick). Read ONCE here, at attach, which is outside any frame. The border box, so it
       is the same number `getBoundingClientRect().width` used to return. */
    const host = containerRef.current;
    let stageWidth = host ? host.getBoundingClientRect().width : 0;
    /* The height too, for the off-canvas finding pointers below — same observer, same reason. */
    let stageHeight = host ? host.getBoundingClientRect().height : 0;

    /* KEEP-OUT REGIONS. The stage's own overlays — the toolbar chips across the top, the Legend
       button — float over the canvas, and a name placed under one is a name nobody can read.
       MEASURED (C5 audit, trace view): core2's name and its G badge ran under the Quality chip.
       Any element in the stage marked `data-label-keepout` is an obstacle to the declutter exactly
       like a placed label: an ordinary label moves or drops, a forced one searches up and down.
       Measured in the ResizeObserver callback (layout is already clean there), never in the tick,
       for the same E3 reason the stage width is. */
    const keepouts: Box[] = [];
    const keepoutEls = (): HTMLElement[] =>
      host?.parentElement ? Array.from(host.parentElement.querySelectorAll<HTMLElement>("[data-label-keepout]")) : [];
    /* THE POINTER'S OBSTACLES are wider than the labels' keep-outs: every OTHER LAYER on the stage —
       each child of the stage except the canvas's own host and these two overlay layers — whatever
       it is called and whether or not it opted in with `data-label-keepout`. The pointer is a control:
       under the HUD, the Legend or the tree (all stacked above it) it is a control a click cannot
       reach, and MEASURED (acceptance D1, dark theme, 1440x900) that is where it sat — under the
       blast-radius HUD, where a click did nothing. A layer clipped to nothing (the fabric tree's
       visually-hidden recipe) is not an obstacle. */
    const pointerObstacles: Box[] = [];
    const overlayEls = (): HTMLElement[] => {
      const stage = host?.parentElement;
      if (!stage) return [];
      return Array.from(stage.children).filter(
        (el): el is HTMLElement =>
          el instanceof HTMLElement &&
          el !== host &&
          el !== pointerLayerRef.current &&
          !el.matches("canvas") &&
          el.querySelector("canvas") === null,
      );
    };
    const measureKeepouts = (): void => {
      keepouts.length = 0;
      pointerObstacles.length = 0;
      if (!host) return;
      const c = host.getBoundingClientRect();
      for (const el of keepoutEls()) {
        const r = el.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) continue;
        keepouts.push({ x: r.left - c.left, y: r.top - c.top, w: r.width, h: r.height });
      }
      for (const el of new Set([...keepoutEls(), ...overlayEls()])) {
        const r = el.getBoundingClientRect();
        if (r.width < 2 || r.height < 2) continue;
        const cs = typeof getComputedStyle === "function" ? getComputedStyle(el) : null;
        if (cs !== null && (cs.visibility === "hidden" || cs.display === "none" || /inset\(\s*50%/.test(cs.clipPath))) continue;
        pointerObstacles.push({ x: r.left - c.left, y: r.top - c.top, w: r.width, h: r.height });
      }
    };
    measureKeepouts();

    let ro: ResizeObserver | null = null;
    let mo: MutationObserver | null = null;
    if (host && typeof ResizeObserver !== "undefined") {
      ro = new ResizeObserver((entries) => {
        for (const entry of entries) {
          if (entry.target !== host) continue;
          const box = entry.borderBoxSize?.[0];
          stageWidth = box ? box.inlineSize : entry.contentRect.width;
          stageHeight = box ? box.blockSize : entry.contentRect.height;
        }
        measureKeepouts();
      });
      ro.observe(host);
      for (const el of new Set([...keepoutEls(), ...overlayEls()])) ro.observe(el);
      /* A layer can be REPLACED rather than resized (the Legend swaps its button for its panel): the
         new element is observed and everything re-measured. Direct children only — the label writes
         every frame inside this layer's own subtree must never reach this callback. */
      const stage = host.parentElement;
      if (stage && typeof MutationObserver !== "undefined") {
        mo = new MutationObserver(() => {
          for (const el of overlayEls()) ro?.observe(el);
          measureKeepouts();
        });
        mo.observe(stage, { childList: true });
      }
    }

    /* Projections of this tick, by position in `seq`, so the write pass and the read pass below
       project each anchor once between them. */
    const projected: ({ x: number; y: number; visible: boolean } | null)[] = [];
    /** The previous tick deferred its measurements; this one must not defer again. */
    let deferredLast = false;

    /* STAGGERED DECLUTTER (C5 critic, 2026-09-22: one wheel tick dropped ~5 names in the same frame
       — counts 26,26,26,22,22,17,15). A name that was on screen and now loses its slot leaves at
       most one per LABEL_DROP_EVERY_FRAMES ticks; the rest hold their own anchor (overlap briefly, the
       lesser failure) until their turn. Mirrors scene.ts recomputeLabels, which staggers the
       scene-side resolver the same way; this DOM pass is the one the reader actually sees. */
    /* Ticks since a label last left. Frame-counted, never clock-read, so the pacing is a pure
       function of the frame sequence; it is advanced once per tick below. */
    let ticksSinceDrop = LABEL_DROP_EVERY_FRAMES;
    const mayDrop = (): boolean => {
      if (ticksSinceDrop < LABEL_DROP_EVERY_FRAMES) return false;
      ticksSinceDrop = 0;
      return true;
    };

    /* THE SETTLED PASS (acceptance F6, independent critic 2026-09-22). The hysteresis below reads a
       label's previous `data-visible`, and the staggered drops above count frames — both right while
       the camera moves, and both made the label set a still camera settles on depend on the frames
       that led to it: fresh loads of the same state kept or dropped access8's name 7:3, every settle
       condition met both times. So once the scene is idle (its own `labelsSettled()`, when it has
       one) AND every projection this tick equals the previous tick's, the pass runs history-free: no
       margin either way and no stagger. The result is then a pure function of the final projection,
       the label sizes and the marks, and the same on every tick the pose holds.
       `pose` is this tick's projections flattened (x, y, visible per seq slot), with the seq order
       and the stage width folded in, so a change of priority or of stage reads as movement. */
    const pose: number[] = [];
    let prevPose: number[] = [];
    /** The unseen-stranded answer last reported (A6), so an unchanged one is never re-sent. */
    let unseenKey: string | null = null;
    let prevSeq = "";
    let settledNow = false;
    /* THE DWELL (acceptance C5, label popping). Whether a name may appear or leave THIS pass, given
       what it did on the passes before, is decided by labelResolve's `labelDwellVerdict` — the gate
       the scene's resolver uses too — never by a rule of this file's own. MEASURED before (motion
       audit, 2026-09-22, the harness's six camera sequences on a real GPU): the scene resolver
       blinked on none, while this layer — spatial hysteresis, but no time dwell, and free to show
       a hidden name mid-move — blinked on four (`access16 hidden 4f` orbiting, `access2`/`access4`
       2–4 frame runs at a focus fly, `access15 hidden 1f` at a reset fly). What the gate needs:
         `ages`     passes since each label's drawn verdict last changed (0xffff = never changed, the
                    scene's own initial age), advanced at the top of every pass from `lastShown`;
         `pending`  the one-pass temporal hold, per label;
         `cameraMoving` this tick's projections differ from the previous tick's (see poseHeld). */
    const ages = new Map<string, number>();
    const lastShown = new Map<string, boolean>();
    const pendingIds = new Set<string>();
    /** The names forced (urgent) on this pass: the settled pass cannot move them (see STILL CONVERGING). */
    const forcedIds = new Set<string>();
    let cameraMoving = true;
    const poseHeld = (seqKey: string): boolean => {
      const same =
        seqKey === prevSeq && pose.length === prevPose.length && pose.every((v, i) => Object.is(v, prevPose[i]));
      prevSeq = seqKey;
      prevPose = pose.slice();
      return same;
    };

    const hide = (id: string, el: HTMLSpanElement) => {
      if (written.get(id) === "hidden") return;
      written.set(id, "hidden");
      /* Fabric3D.css hides a label by this attribute (visibility: hidden): focus leaves it first through the owner
         (focus-return.ts, third door) — a no-op while the label layer holds no focus, which is always today. */
      releaseFocusFrom(el, null);
      el.dataset.visible = "false";
    };

    /* A4 — OFF-CANVAS FINDING POINTERS. A finding names devices; the camera is deliberately not
       flown on a queue click (Fabric3D.tsx, the highlight memo), so a named device can project far
       outside the canvas — measured: F094 names only access5, which sat at y=1224 on a 962 px
       canvas, and its "◆ F094" mark was applied to a label nobody could see, so the fabric did not
       answer "where is this finding?". Every named device whose anchor projects OUTSIDE the stage
       gets a pointer pinned to the stage edge on the line from the centre towards it; a click frames
       that device (the camera moves only when the reader asks). A device projecting INSIDE the stage
       but hidden (occluded) is on screen and gets no pointer. Writes only — positions come from this
       tick's projections, the stage size from the observer — so it adds no layout read (E3), except
       ONE size read per pointer per finding, on the tick it first shows.

       A CONTROL, NOT A MARK (acceptance D1/D5, repair wave 6). The pointer is a <button> in a layer
       of its own, outside the label layer's aria-hidden: MEASURED, the `<span onClick>` it was could
       be clicked but never reached by Tab (250 stops), was hidden from assistive technology, and was
       141.23 x 16.84. A hidden pointer carries the `hidden` attribute, so it leaves the Tab order with
       the screen. And it is placed clear of every other stage layer (pointerObstacles): the edge point
       on the line towards the device is only where it WANTS to be. */
    const pointerWritten = new Map<string, string>();
    const hidePointer = (id: string, el: HTMLButtonElement): void => {
      if (pointerWritten.get(id) === "hidden") return;
      pointerWritten.set(id, "hidden");
      /* Focus first, through the owner's third door, while the pointer is still rendered (the door
         does nothing when focus is elsewhere); then the hide. See `onPointerFocusLost`. */
      if (typeof document !== "undefined" && el.contains(document.activeElement)) {
        releaseFocusFrom(el, null, focusLostRef.current?.() ?? []);
      }
      el.dataset.visible = "false";
      el.hidden = true;
    };
    /** The centre nearest `want` whose box (hw, hh half-extents) is inside the stage and clear of every
     *  obstacle. Candidates: `want` itself, then flush against each side of each obstacle (and, once
     *  more, of each obstacle from there — the HUD and the Legend can both be in the way). */
    const clearCentre = (want: { x: number; y: number }, hw: number, hh: number, w: number, h: number): { x: number; y: number } => {
      const lo = LABEL_EDGE_PX;
      const clamp = (c: { x: number; y: number }) => ({
        x: w - 2 * lo > 2 * hw ? Math.min(Math.max(c.x, lo + hw), w - lo - hw) : w / 2,
        y: h - 2 * lo > 2 * hh ? Math.min(Math.max(c.y, lo + hh), h - lo - hh) : h / 2,
      });
      const clearOf = (c: { x: number; y: number }): boolean =>
        pointerObstacles.every(
          (o) =>
            !(c.x - hw < o.x + o.w + POINTER_GAP && c.x + hw + POINTER_GAP > o.x && c.y - hh < o.y + o.h + POINTER_GAP && c.y + hh + POINTER_GAP > o.y),
        );
      const around = (c: { x: number; y: number }) =>
        pointerObstacles.flatMap((o) => [
          clamp({ x: o.x - POINTER_GAP - hw - 1, y: c.y }),
          clamp({ x: o.x + o.w + POINTER_GAP + hw + 1, y: c.y }),
          clamp({ x: c.x, y: o.y - POINTER_GAP - hh - 1 }),
          clamp({ x: c.x, y: o.y + o.h + POINTER_GAP + hh + 1 }),
        ]);
      const first = clamp(want);
      if (clearOf(first)) return first;
      const level1 = around(first);
      const candidates = [...level1, ...level1.flatMap(around)].filter(clearOf);
      if (candidates.length === 0) return first;
      const dist = (c: { x: number; y: number }) => Math.hypot(c.x - want.x, c.y - want.y);
      return candidates.reduce((best, c) => (dist(c) < dist(best) ? c : best));
    };
    const placePointers = (w: number, container: HTMLElement): void => {
      const ptrs = pointerElsRef.current;
      if (ptrs.size === 0) return;
      // Layout is asked only while a finding pointer exists and the observer has not reported yet.
      const h = stageHeight > 0 ? stageHeight : container.getBoundingClientRect().height;
      const byId = new Map<string, { x: number; y: number; visible: boolean } | null>();
      for (let i = 0; i < seq.length; i += 1) {
        const id = seq[i];
        if (id !== undefined && ptrs.has(id)) byId.set(id, projected[i] ?? null);
      }
      const cx = w / 2;
      const cy = h / 2;
      const sizes = pointerSizesRef.current;
      for (const [id, el] of ptrs) {
        const p = byId.get(id) ?? null;
        if (p === null || w <= 0 || h <= 0 || (p.x >= 0 && p.x <= w && p.y >= 0 && p.y <= h)) {
          hidePointer(id, el);
          continue;
        }
        if (el.hidden) {
          el.hidden = false;
          el.dataset.visible = "true";
          pointerWritten.delete(id);
        }
        let size = sizes.get(id);
        if (size === undefined) {
          size = { w: el.offsetWidth, h: el.offsetHeight };
          if (size.w > 0) sizes.set(id, size);
        }
        const dx = p.x - cx;
        const dy = p.y - cy;
        const hx = Math.max(1, cx - POINTER_EDGE_X);
        const hy = Math.max(1, cy - POINTER_EDGE_Y);
        const t = Math.min(dx === 0 ? Infinity : hx / Math.abs(dx), dy === 0 ? Infinity : hy / Math.abs(dy));
        const at = clearCentre({ x: cx + dx * t, y: cy + dy * t }, size.w / 2, size.h / 2, w, h);
        const px = Math.round(at.x);
        const py = Math.round(at.y);
        /* The arrow still points from where the chip sits towards the device, so a chip moved off
           its edge point by an obstacle does not point somewhere else. */
        const deg = Math.round((Math.atan2(p.y - py, p.x - px) * 180) / Math.PI);
        const key = `${px}:${py}:${deg}`;
        if (pointerWritten.get(id) === key) continue;
        pointerWritten.set(id, key);
        el.dataset.visible = "true";
        el.style.transform = `translate3d(${px}px, ${py}px, 0) translate(-50%, -50%)`;
        el.style.setProperty("--pointer-deg", `${deg}deg`);
      }
    };

    const tick = () => {
      frame = requestAnimationFrame(tick);
      ticksSinceDrop += 1;
      const scene = sceneRef.current;
      const container = containerRef.current;
      if (!scene || !container) return;

      /* Advance the dwell ages from the verdicts the previous pass drew (DOM attribute reads only,
         no layout). A change made on pass t reads as age 0 on pass t+1 — the scene resolver's
         arithmetic exactly. */
      for (const [id, el] of els) {
        const now = el.dataset.visible === "true";
        const before = lastShown.get(id);
        const age = ages.get(id);
        ages.set(id, before === undefined || age === undefined ? 0xffff : before !== now ? 0 : Math.min(0xffff, age + 1));
        lastShown.set(id, now);
      }

      /* RESPONSIVENESS FIX, 2026-09-21 (acceptance E3). This read `getBoundingClientRect()` on
         every animation frame. A layout read in a rAF callback that follows a React commit forces
         the whole page's style and layout synchronously, inside this callback — the CPU profile
         of a finding-select put 318 ms of self time on that one call across twelve clicks, all of
         it on the frame that presents the click. In canvas space (the only space the app uses)
         only the WIDTH is needed, and a ResizeObserver already knows it without asking layout. */
      let originX = 0;
      let originY = 0;
      let stageW = stageWidth;
      if (coordinateSpace === "client") {
        const rect = container.getBoundingClientRect();
        originX = rect.left;
        originY = rect.top;
        stageW = rect.width;
      } else if (stageW <= 0) {
        /* Not reported yet (the observer delivers after the first layout) or a collapsed stage:
           ask layout directly, and keep asking only for as long as there is no answer. */
        stageW = container.getBoundingClientRect().width;
      }

      const sel = selectedRef.current;
      const hov = hoveredRef.current;
      const alm = alarmRef.current;
      const blk = alm?.id ?? null;
      const cut = cutRef.current;
      const str = strandedRef.current;
      const fnd = findingRef.current;
      const dsp = disputedRef.current;
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
      for (const id of baseOrder) if (fnd.has(id)) push(id);
      for (const id of baseOrder) if (str.has(id)) push(id);
      for (const id of baseOrder) push(id);
      placed.length = 0;
      leaders.length = 0;
      forcedIds.clear();

      /* PASS 1 — WRITES ONLY. Project every anchor, hide the invisible ones and apply the marks.
         Nothing in this pass reads layout.

         THE MARKS ARE APPLIED BEFORE THE BOX IS MEASURED, and this order is load-bearing. The
         `stranded` / `cut point` marks are shown by CSS off these attributes, so a label that gains
         one gets WIDER. Writing them after the measurement — where the rest of the state is
         written — meant the declutter pass tested a box narrower than the label it was about to
         draw, and two marked labels smeared into each other. Any change of shape drops the cached
         size with it.

         RESPONSIVENESS FIX, 2026-09-21 (acceptance E3). The write and the read used to alternate
         label by label in ONE loop — mark this one, measure it, mark the next — so every marked
         label forced a fresh synchronous layout of the page: a finding that marks nine hosts cost
         nine layouts inside the frame that presents the click. Now all the writes happen first,
         and when any of them left a label needing measurement, the measuring waits one frame: the
         browser lays the marks out in its own rendering step, and the next tick reads sizes from a
         layout that is already clean. The labels hold their previous placement for that one frame,
         which is the same frame the scene itself spends yielding to the page (scene.ts). */
      let wroteMarks = false;
      let needsMeasure = false;
      projected.length = seq.length;
      for (let i = 0; i < seq.length; i += 1) {
        const id = seq[i];
        projected[i] = null;
        if (id === undefined) continue;
        const el = els.get(id);
        if (!el) continue;

        const p = scene.project(id);
        projected[i] = p;
        const onScreen = p !== null && p.visible;

        /* The marks are the LABEL's state, written whether or not the label is drawn this pass. They
           used to be written only for an on-screen anchor, so a label that left the view kept the
           marks of the selection it left under — stale state on a hidden element — and a stranded
           host off the canvas carried no mark at all (A6, refuted at 70bea72: 5 of core2's 8). A
           hidden label's mark draws nothing (visibility: hidden); the stage's count names it as out
           of view (Fabric3D, onStrandedUnseen). */
        const wantAlarm = id === blk && alm !== null ? alm.kind : "";
        const wantCut = id === cut ? "yes" : "";
        const wantStranded = str.has(id) ? "yes" : "";
        const wantFinding = fnd.has(id) ? "yes" : "";
        const wantDisputed = id === dsp ? "yes" : "";
        if (
          el.dataset.alarm !== wantAlarm ||
          el.dataset.cut !== wantCut ||
          el.dataset.stranded !== wantStranded ||
          el.dataset.finding !== wantFinding ||
          el.dataset.disputed !== wantDisputed
        ) {
          /* Each mark is a rule Fabric3D.css renders a chip by, so a changed mark can stop one rendering: focus
             leaves the label first (focus-return.ts, third door; a no-op when it is elsewhere). */
          releaseFocusFrom(el, null);
          el.dataset.alarm = wantAlarm;
          el.dataset.cut = wantCut;
          el.dataset.stranded = wantStranded;
          el.dataset.finding = wantFinding;
          el.dataset.disputed = wantDisputed;
          sizes.delete(id);
          written.delete(id);
          // Only a label about to be placed needs its new box measured before placement.
          if (onScreen) wroteMarks = true;
        }

        // An anchor behind the camera or occluded by a chassis reports invisible. Drawing its label
        // anyway would attach a hostname to a device the viewer cannot see.
        if (!onScreen) {
          // Left the view (or the scene's own resolver dropped it): gone at once, never held —
          // the gate's rule for an anchor that is not on screen, as in resolveLabels.
          pendingIds.delete(id);
          hide(id, el);
          continue;
        }
        if (!sizes.has(id)) needsMeasure = true;
      }
      placePointers(stageW, container);

      pose.length = 0;
      pose.push(stageW);
      for (const q of projected) {
        if (q === null) pose.push(NaN, NaN, -1);
        else pose.push(q.x, q.y, q.visible ? 1 : 0);
      }
      const sceneIdle = (scene as FabricScene & { labelsSettled?: () => boolean }).labelsSettled;
      const still = poseHeld(seq.join("|"));
      cameraMoving = !still;
      settledNow = still && (typeof sceneIdle !== "function" || sceneIdle.call(scene));
      // A fresh start for the stagger: the next drop after the camera moves again is paced from here.
      if (settledNow) ticksSinceDrop = LABEL_DROP_EVERY_FRAMES;

      /* Never two deferrals in a row: a label that measures 0 wide (a collapsed stage) stays
         uncached, and it must not keep the whole layer from being placed. */
      if (wroteMarks && needsMeasure && !deferredLast) {
        deferredLast = true;
        return;
      }
      deferredLast = false;

      /* PASS 2 — READS, THEN PLACEMENT. Every missing size is read before any label is moved, so
         the placement writes below cannot dirty the layout a later read would then force. */
      if (needsMeasure) {
        for (let i = 0; i < seq.length; i += 1) {
          const id = seq[i];
          const p = projected[i];
          if (id === undefined || !p || !p.visible || sizes.has(id)) continue;
          const el = els.get(id);
          if (!el) continue;
          const nameEl = el.firstElementChild as HTMLElement | null;
          const nameC = nameEl ? nameEl.offsetLeft + nameEl.offsetWidth / 2 : el.offsetWidth / 2;
          const measured = { w: el.offsetWidth, h: el.offsetHeight, nameC };
          if (measured.w > 0) sizes.set(id, measured);
        }
      }
      /* EVERY visible device is an obstacle, not only every placed label. The declutter used to
         test a label against the other labels alone, so a name could land squarely on a
         NEIGHBOURING device: the blind panel's damning finding, measured at 1440×900 as access14's
         name over access16's chassis, access3's over access17's, access7's over access9's and
         wan-edge-rtr1.lab's over dist2's. The anchor sits on the chassis' top edge and the chassis
         hangs below it, so the zone reaches further down than up. Sized from the label height
         (the one on-screen length this layer owns) — an approximation of the tile, not its mesh. */
      /* The zones are the chassis bodies as the scene PROJECTS them this frame, not a box guessed
         from the label height around the anchor. The guess (1.1 label-heights either side, 1.1
         below) was right for the default steep view and wrong at a graze, where a chassis is wide
         and short and neighbouring rows overlap on screen (C5 critic, z-gpu-high-graze.png: the
         access7/5/3 names stacked across the chassis bodies, AP-floor3-01's across the wan-edge
         box). And a label's OWN chassis was exempt, so a name displaced one row down landed on its
         own hardware (core2, dist2). Every body is an obstacle now, the label's own included: its
         home slot hangs above the lid, so it only meets its own body when displaced onto it. A
         scene without the method keeps the old estimate rather than losing every zone. */
      chassis.length = 0;
      const refH = sizes.values().next().value?.h ?? 20;
      const boxOf = (scene as FabricScene & {
        chassisScreenBox?: (id: string) => { x0: number; y0: number; x1: number; y1: number } | null;
      }).chassisScreenBox;
      for (let i = 0; i < seq.length; i += 1) {
        const id = seq[i];
        const p = projected[i];
        if (id === undefined || !p || !p.visible) continue;
        const real = typeof boxOf === "function" ? boxOf.call(scene, id) : undefined;
        if (real !== undefined) {
          if (real === null) continue;
          const inset = CHASSIS_INSET_PX;
          const w = real.x1 - real.x0 - 2 * inset;
          const h = real.y1 - real.y0 - 2 * inset;
          if (w <= 0 || h <= 0) continue;
          chassis.push({ id, x: real.x0 + inset - originX, y: real.y0 + inset - originY, w, h, blocksOwn: true });
          continue;
        }
        chassis.push({
          id,
          x: p.x - originX - CHASSIS_HALF_W * refH,
          y: p.y - originY - CHASSIS_UP * refH,
          w: 2 * CHASSIS_HALF_W * refH,
          h: (CHASSIS_UP + CHASSIS_DOWN) * refH,
          // The estimate reaches above the anchor, into the label's own home slot, so it can only
          // ever be a NEIGHBOUR's obstacle.
          blocksOwn: false,
        });
      }
      const onChassis = (b: Box, own: string): boolean =>
        chassis.some(
          (c) =>
            (c.blocksOwn || c.id !== own) && b.x < c.x + c.w && b.x + b.w > c.x && b.y < c.y + c.h && b.y + b.h > c.y,
        );
      /* Every visible device's HOME slot — where its own name hangs when nothing displaces it.
         A label pushed off its anchor must not land in a neighbour's home slot: MEASURED (C5
         critic, low orbit) AP-floor3-01's name was pushed one row up onto wan-edge-rtr1.lab's
         anchor, which then either lost its name or hung it with a leader through the AP's text.
         A displaced name sitting exactly where another device's name belongs reads as that
         device's name. Only DISPLACED candidates are tested against these; a label at its own
         home competes through the placed list as before. */
      homes.length = 0;
      for (let i = 0; i < seq.length; i += 1) {
        const id = seq[i];
        const p = projected[i];
        const sz = id === undefined ? undefined : sizes.get(id);
        if (id === undefined || !p || !p.visible || sz === undefined) continue;
        homes.push({
          id,
          released: false,
          x: p.x - originX - sz.nameC,
          y: p.y - originY - sz.h * LIFT,
          w: sz.w,
          h: sz.h,
        });
      }
      const inNeighbourHome = (b: Box, own: string): boolean =>
        homes.some((h) => !h.released && h.id !== own && intersects(b, h));
      /* BINDING. Where each visible device is READ from: the top-centre of its projected chassis
         (the anchor when the scene cannot project one). A name is read as the name of whichever
         device it sits nearest, so a label placed anywhere is only honest if that device is its
         own. The obstacle tests above are all "do not cover X"; none of them said "stay nearest
         your own box", and MEASURED (1920x1080, ?f=F099 and ?d=access13 + focus) the SELECTED
         host's name was pushed 72 px off its own chassis and landed 6-7 px above access11's — the
         highlighted box unlabelled, its name on a grey neighbour. This is the structural rule every
         displaced candidate must pass, forced or not: a forced label that finds no bound slot
         keeps its home over hardware (a name across a body still reads as its own); an ordinary
         one is dropped. Home (dy = 0) is exempt: its bottom edge IS the anchor. */
      bindings.length = 0;
      for (let i = 0; i < seq.length; i += 1) {
        const id = seq[i];
        const p = projected[i];
        if (id === undefined || !p || !p.visible) continue;
        const c = chassis.find((k) => k.id === id);
        bindings.push(
          c !== undefined && c.blocksOwn
            ? { id, x: c.x + c.w / 2, y: c.y - CHASSIS_INSET_PX }
            : { id, x: p.x - originX, y: p.y - originY },
        );
      }
      /** Whether a name drawn in box `b` reads as naming `own`: no other device is nearer to it.
       *  `nameC` is the name's centre within the pill; the reading edge is the one facing the device
       *  (bottom, or top when flipped). A TIE is bound: devices that project to one point (a pile of
       *  stranded access switches) cannot be told apart by position, only stacked. */
      const readsAsOwn = (b: Box, nameC: number, flip: boolean, own: string): boolean => {
        const lx = b.x + nameC;
        const ly = flip ? b.y : b.y + b.h;
        let mine = Infinity;
        let other = Infinity;
        for (const k of bindings) {
          const d = Math.hypot(k.x - lx, k.y - ly);
          if (k.id === own) mine = Math.min(mine, d);
          else other = Math.min(other, d);
        }
        return mine === Infinity || mine <= other + 0.5;
      };
      /* A home is only worth protecting while its owner may still be placed there: once a label
         has been displaced or dropped, its slot is free for the neighbours. */
      const releaseHome = (own: string): void => {
        for (const h of homes) if (h.id === own) h.released = true;
      };
      for (let i = 0; i < seq.length; i += 1) {
        const id = seq[i];
        if (id === undefined) continue;
        const el = els.get(id);
        if (!el) continue;
        const p = projected[i];
        if (!p || !p.visible) continue;

        const isAlarmed = id === blk;
        const isCut = id === cut;
        const wantAlarm = isAlarmed && alm !== null ? alm.kind : "";
        const wantCut = isCut ? "yes" : "";
        const wantStranded = str.has(id) ? "yes" : "";
        const wantFinding = fnd.has(id) ? "yes" : "";
        const wantDisputed = id === dsp ? "yes" : "";

        let size = sizes.get(id);
        if (!size) {
          // offsetWidth is valid while the element is `visibility: hidden` (it still has layout),
          // which is why hiding uses visibility and not display.
          const nameEl = el.firstElementChild as HTMLElement | null;
          const nameC = nameEl ? nameEl.offsetLeft + nameEl.offsetWidth / 2 : el.offsetWidth / 2;
          size = { w: el.offsetWidth, h: el.offsetHeight, nameC };
          if (size.w > 0) sizes.set(id, size);
        }

        const x = Math.round(p.x - originX);
        const y = Math.round(p.y - originY);
        /* The blocked host's label lifts clear of the alarm halo drawn at its anchor. Sitting on
           the anchor is what reduced a denied trace to slivers of red around a hostname. */
        /* Except UNDECIDED: that ending always comes from a trace, whose open-ring glyph the scene's
           anchor (scene.ts projectLabelAnchor) already clears, so the extra lift only stranded the
           chip ~35 px above the ring it belongs to. */
        const lift = (isAlarmed && alm?.kind !== "undetermined") || isCut ? LIFT_BLOCKED : LIFT;
        /* The NAME is centred on the anchor, not the whole pill, and the pill is then kept inside
           the stage. Centring the pill put a suffixed name ("? not collected", "stranded", a
           finding id) half a suffix LEFT of its own device: measured in the traced view, the
           wan-edge-rtr1.lab name sat ~44 px left of its anchor, squarely over the AP-floor3-01
           disc whose own label had been decluttered — so the router's name read as naming the AP
           — and the suffix ran off the canvas edge. When the stage edge forces the pill off its
           anchor anyway, a leader line (data-leader, CSS) ties it back to the device it names. */
        const rawLeft = Math.round(x - size.nameC);
        const clampedLeft =
          stageW > 2 * LABEL_EDGE_PX + size.w
            ? Math.round(Math.min(Math.max(LABEL_EDGE_PX, rawLeft), stageW - LABEL_EDGE_PX - size.w))
            : rawLeft;
        const left = clampedLeft;
        /* The same rule on the VERTICAL axis. A label is lifted above its anchor, so a device near
           the top of the stage — core1 once the camera focuses it — pushed its name, and the
           CUT POINT mark with it, off the top edge (measured: the pill's top at stage y = 1). A
           label that would cross the top edge flips BELOW its anchor instead, tied back to it by
           an upward leader, rather than being clipped. */
        const flipped = y - size.h * lift < LABEL_EDGE_PX;
        const flipDy = flipped ? size.h * (2 * lift - 1) : 0;
        let box: Box = { x: left, y: y - size.h * lift + flipDy, w: size.w, h: size.h };

        /* A MARKED host is never dropped: its mark is the answer to the question on screen. That
           class is every host carrying a mark, not a list of the first few — the stranded set was
           left out, and MEASURED (A6): selecting core1 strands nine hosts and only six carried the
           mark; access2, access8 and access16 were decluttered by each other's marks, their
           STRANDED pill gone while the Inspector listed them. */
        /* The hovered host is forced only on a still camera (labelResolve `labelUrgent`): an orbit
           drag's pointer crosses devices without pointing at any, and forcing each one's name in on
           the way past was itself a pop (motion probe, high tier). */
        const forced = labelUrgent(
          id === sel || isAlarmed || isCut || wantStranded !== "" || wantFinding !== "",
          id === hov,
          cameraMoving,
        );
        if (forced) forcedIds.add(id);
        /* Hysteresis, same rule and same reason as scene.ts LABEL_HYSTERESIS_PX: a label already
           on screen must overlap by more than the margin before it goes, a hidden one must clear
           by it before it comes back. Without it the two passes flicker names on and off for
           single frames while the camera moves. */
        /* Read from the DOM, not from `written`. `written` is a write-dedupe cache, and it is emptied
           far more often than a label changes visibility — the inline `ref` callback below deletes an
           element's entry on every re-render of this component. MEASURED (2026-09-22, wheel dolly on
           the preview): every label a tick dropped had `written` undefined, so all of them were
           judged "not on screen" and both this hysteresis and the staggered drops were inert. */
        const shown = el.dataset.visible === "true";
        // History-free once settled (see settledNow): the previous verdict does not move the margin.
        const m = settledNow ? 0 : shown ? DECLUTTER_HYSTERESIS : -DECLUTTER_HYSTERESIS;
        const test: Box = { x: box.x + m, y: box.y + m, w: box.w - 2 * m, h: box.h - 2 * m };
        /* A label is NEVER placed across the stage edge while the stage is wide enough to hold it.
           This used to fall back to the unclamped (name-on-anchor) position whenever the clamped
           one collided, on the argument that a clipped suffix beats a lost name — and MEASURED
           (C5 audit, 1600 and 1440 wide) that fallback is exactly what rendered wan-edge-rtr1.lab
           as "... ? nc", 61-74 px past the canvas edge with no leader. The clamped pill now looks
           for a clear slot above or below instead (tied back to its device by the leader line);
           only a stage narrower than the label itself still lets it overhang. */
        const step = size.h + DECLUTTER_ROW_GUTTER;
        const clamped = left !== rawLeft;
        let dy = 0;
        /* The leader this label would draw at box b: a vertical line from the box edge nearest the
           anchor to the anchor itself (see the --leader-len arithmetic below). */
        const leaderFor = (b: Box, off: boolean): Box | null => {
          if (!off) return null;
          const edge = flipped ? b.y : b.y + b.h;
          const len = Math.abs(edge - y);
          return len < 1 ? null : { x: x - 1, y: Math.min(edge, y), w: 2, h: len };
        };
        const nameOffAnchor = Math.abs(left + size.nameC - x) > LEADER_MIN_PX || flipped;
        /* A displaced slot is only a candidate while the name there still reads as THIS device's
           (see BINDING above). */
        const nameC = size.nameC;
        const bound = (k: number): boolean => readsAsOwn({ ...box, y: box.y + k * step }, nameC, flipped, id);
        const blocked = (t: Box, off: boolean, strict = true): boolean => {
          if (placed.some((b) => intersects(t, b)) || keepouts.some((b) => intersects(t, b)) || onChassis(t, id)) {
            return true;
          }
          if (!strict) return false;
          // Neither across an earlier label's leader, nor with our own leader across an earlier label.
          if (leaders.some((l) => touches(t, l))) return true;
          const own = leaderFor(t, off);
          return own !== null && placed.some((b) => touches(own, b));
        };
        let clear = true;
        if (blocked(test, nameOffAnchor)) {
          /* A forced label is never hidden, and two forced labels must not smear into one either;
             an ordinary label near the edge gets the same search so the clamp does not cost it its
             name. Nine stranded access switches in one row is the case the forced search exists
             for. Order is up first, then down, by whole label heights. An ordinary label gets one
             label-height either way — a short leader still reads as its own device's; a long one
             does not, and dropping the name is then the honest outcome. */
          let found = false;
          const ks = forced || clamped ? [-1, 1, -2, 2, -3, 3] : [-1, 1];
          for (const k of ks) {
            const t: Box = { ...test, y: test.y + k * step };
            if (t.y + m >= 0 && bound(k) && !blocked(t, true) && !inNeighbourHome(t, id)) {
              dy = k * step;
              found = true;
              break;
            }
          }
          /* A FORCED label that found no slot clear of leaders and neighbours' homes still stacks
             rather than piling onto its own anchor: several marked hosts that project to one point
             (a pile of stranded access switches) can only be told apart as a column, and a column
             of labels over one anchor necessarily shares one leader. */
          if (!found && forced) {
            for (const k of ks) {
              const t: Box = { ...test, y: test.y + k * step };
              if (t.y + m >= 0 && bound(k) && !blocked(t, true, false)) {
                dy = k * step;
                found = true;
                break;
              }
            }
          }
          /* LAST RESORT for a forced label: text over text is the one outcome that hides a mark,
             so it outranks every other obstacle. MEASURED (C5 critic, core1 selected, 1920x1080):
             nine stranded access switches in a dense grid left access4 with no slot clear of the
             chassis bodies within three rows, so it "kept its own anchor" — squarely over
             access14's STRANDED? chip, truncating it to "STI". A name drawn across a chassis body
             still reads; a chip drawn under another label does not. So the final search accepts a
             slot over hardware, reaching further, and refuses only other labels and the stage's
             own keep-out chrome. */
          if (!found && forced) {
            for (const k of [...ks, -4, 4, -5, 5]) {
              const t: Box = { ...test, y: test.y + k * step };
              if (t.y + m < 0 || !bound(k)) continue;
              if (placed.some((b) => intersects(t, b)) || keepouts.some((b) => intersects(t, b))) continue;
              dy = k * step;
              found = true;
              break;
            }
          }
          /* If nothing clears, a forced label keeps its own anchor — overlapping is the lesser
             failure than silently dropping the mark. */
          clear = found;
        }
        /* WHETHER the name is drawn this pass is the shared dwell gate's answer (labelResolve
           `labelDwellVerdict`, the scene resolver's own rule), given only what THIS layer's geometry
           says: is the box clear. A forced label is urgent and exempt; the settled pass is
           history-free (F6). A hidden name whose box has cleared waits, claiming no box, while the
           camera moves and for its dwell; a shown name whose box is taken is held at its own anchor
           until its dwell runs out, and then leaves at the stagger's pace. */
        const verdict = labelDwellVerdict({
          wasShown: shown,
          age: ages.get(id) ?? 0xffff,
          pending: pendingIds.has(id),
          clear,
          urgent: forced,
          cameraMoving,
          settled: settledNow,
        });
        if (verdict.pending) pendingIds.add(id);
        else pendingIds.delete(id);
        if (!verdict.show) {
          if (!verdict.leaving || settledNow || mayDrop()) {
            releaseHome(id);
            hide(id, el);
            continue;
          }
          /* Its turn in the stagger has not come: held for a later frame at its own anchor. */
          dy = 0;
        }
        box = dy === 0 ? box : { ...box, y: box.y + dy };
        const offAnchor = Math.abs(left + size.nameC - x) > LEADER_MIN_PX || dy !== 0 || flipped;
        placed.push(box);
        if (dy !== 0 || flipped) releaseHome(id);
        const drawnLeader = leaderFor(box, offAnchor);
        if (drawnLeader !== null) leaders.push(drawnLeader);

        /* `state` stays what it always was. The alarm and the stranded mark are SEPARATE channels
           written above, because a host can be selected and alarmed at once and neither statement
           may overwrite the other. */
        const state = id === sel ? "selected" : id === hov ? "hover" : "";
        const key = `${x}:${left}:${y}:${dy}:${flipDy}:${state}:${wantStranded}:${wantCut}:${wantAlarm}:${wantFinding}:${wantDisputed}`;
        if (written.get(id) === key) continue;
        written.set(id, key);
        el.dataset.visible = "true";
        el.dataset.state = state;
        el.style.transform = `translate3d(${left}px, ${y + flipDy + dy}px, 0) translate(0, ${-100 * lift}%)`;
        if (offAnchor) {
          /* "up" = the label sits below its device and the leader rises from its top edge. */
          el.dataset.leader = flipped ? "up" : "yes";
          el.style.setProperty("--leader-x", `${x - left}px`);
          el.style.setProperty(
            "--leader-len",
            `${Math.max(0, flipped ? size.h * (lift - 1) + dy : size.h * (lift - 1) - dy)}px`,
          );
        } else if (el.dataset.leader !== "") {
          el.dataset.leader = "";
        }
      }
      /* The scene's own resolver estimates label widths from character counts and never sees the
         marks, so its `labelsShown` said 26 of 26 while four labels here were hidden (A6). The
         count that is TRUE is this one — every label this pass actually placed — so it is handed
         back to the scene's telemetry. Duck-typed: the frozen contract has no such method, and a
         scene without it simply keeps its resolver's count. */
      (scene as FabricScene & { reportLabelsShown?: (n: number) => void }).reportLabelsShown?.(placed.length);

      /* A6: the stranded hosts this pass could not draw — read off what the pass actually drew
         (`data-visible`), not re-derived, so the count the stage states is the picture's own. */
      const report = unseenCbRef.current;
      if (report !== undefined) {
        const unseen: string[] = [];
        for (const id of seq) if (str.has(id) && els.get(id)?.dataset.visible !== "true") unseen.push(id);
        const key = unseen.join("|");
        if (key !== unseenKey) {
          unseenKey = key;
          report(unseen);
        }
      }

      /* STILL CONVERGING (acceptance C5, the settle's half of the dwell — labelResolve
         `labelSettleMayReverse`). The settled pass above is history-free (F6) and so has no dwell:
         run while a name here changed fewer than LABEL_MIN_DWELL_PASSES passes ago, it can reverse
         that change within a few frames — MEASURED, `access12 hidden for only 5 frame(s)` in a
         six-frame dolly (review/capture-motion.mjs, light/high). This layer cannot hold the scene's
         settle, so it says whether it is still converging, and a scene that honours the report keeps
         `labelsSettled()` (and its `converged`) false meanwhile; the reversal then lands only after the
         dwell, and a capture is never taken of a set this layer is about to change. Conservative: any
         name whose verdict is younger than the dwell, except the ones the settled pass cannot move —
         a forced (urgent) name, and one with no anchor on screen. Duck-typed like the calls above; a
         scene without the method settles as before. */
      let converging = false;
      for (let i = 0; i < seq.length && !converging; i += 1) {
        const id = seq[i];
        const p = projected[i];
        if (id === undefined || !p || !p.visible || forcedIds.has(id)) continue;
        const el = els.get(id);
        if (!el) continue;
        const changed = (el.dataset.visible === "true") !== lastShown.get(id);
        const age = changed ? 0 : Math.min(0xffff, (ages.get(id) ?? 0xffff) + 1);
        if (!labelSettleMayReverse(age)) converging = true;
      }
      (scene as FabricScene & { reportLabelsConverging?: (b: boolean) => void }).reportLabelsConverging?.(converging);
    };

    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      ro?.disconnect();
      mo?.disconnect();
    };
    // `epoch` is a dependency so a replaced scene gets a fresh loop rather than a stale handle.
  }, [baseOrder, coordinateSpace, epoch, sceneRef]);

  /* The finding mark's text is the finding id, so a new finding can change a label's width. */
  useEffect(() => {
    sizesRef.current.clear();
    writtenRef.current.clear();
    pointerSizesRef.current.clear();
  }, [finding]);

  /* Web-font metrics land after first paint; a stale width makes the declutter reject labels that
     would in fact fit. Clearing the cache is enough — the next tick re-measures. */
  useEffect(() => {
    const fonts = typeof document === "undefined" ? undefined : document.fonts;
    if (!fonts) return;
    let live = true;
    void fonts.ready.then(() => {
      if (!live) return;
      sizesRef.current.clear();
      pointerSizesRef.current.clear();
    });
    return () => {
      live = false;
    };
  }, []);

  return (
    <>
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
            data-finding=""
            data-cut=""
            data-alarm=""
            data-disputed=""
            data-leader=""
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
            {(() => {
              /* The letter, colour and tooltip come from the ONE band owner: a favourable band on a
                 host with unassessed scoring domains prints its letter with the partial mark, in the
                 neutral ink, and the tooltip names the gaps (B1). */
              const p = presentBand(d);
              return (
                <span
                  className="fabric3d-label__band"
                  data-band={p.legendKey}
                  {...(p.qualified ? { "data-band-partial": "" } : {})}
                  style={{ "--band-ink": `var(${p.colorToken})` } as CSSProperties}
                  title={p.sentence}
                >
                  {p.letter}
                </span>
              );
            })()}
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
            <span
              className="fabric3d-label__stranded"
              title={strandedQualifier === "" ? "Unreachable if the current selection fails" : `Unreachable if the current selection fails — ${strandedQualifier}`}
            >
              <span aria-hidden="true">⊘</span> {strandedQualifier === "" ? "stranded" : "stranded?"}
            </span>
            <span
              className="fabric3d-label__disputed"
              title="The snapshot's failure_impact says this failure strands hosts; this graph reproduces no partition. The Inspector compares the two measures."
            >
              <span aria-hidden="true">≠</span> impact disputed
            </span>
            {finding !== null ? (
              <span
                className="fabric3d-label__finding"
                data-sev={finding.severity}
                title={`Named by the selected finding ${finding.id}`}
              >
                <span aria-hidden="true">◆</span> {finding.id}
              </span>
            ) : null}
          </span>
        ))}
      </div>
      {/* THE OFF-VIEW POINTERS — controls, so NOT inside the aria-hidden label layer above (acceptance
          D1). A native button: Tab reaches it (after the canvas, before the HUD, in DOM order), Enter
          and Space activate it, and its name is what it shows — the finding and the host, "off view".
          It is not a second copy of the fabric for a screen reader: it exists only for a finding's
          host while that host is outside the view, and says so. Hidden (`hidden`) whenever it is not
          drawn, so an undrawn pointer is never a Tab stop. */}
      <div className="fabric3d__pointers" ref={pointerLayerRef} data-testid="fabric3d-pointers">
        {finding !== null
          ? devices
              .filter((d) => findingHosts.has(d.id))
              .map((d) => (
                <button
                  type="button"
                  key={`ptr-${d.id}`}
                  className="fabric3d-pointer"
                  data-pointer-for={d.id}
                  data-visible="false"
                  hidden
                  data-sev={finding.severity}
                  title={`${d.host} is named by the selected finding ${finding.id} and lies outside the view. Activate to frame it.`}
                  onClick={() => sceneRef.current?.focusDevice(d.id)}
                  ref={(el) => {
                    if (el) pointerElsRef.current.set(d.id, el);
                    else pointerElsRef.current.delete(d.id);
                  }}
                >
                  <span className="fabric3d-pointer__arrow" aria-hidden="true">
                    →
                  </span>
                  <span aria-hidden="true">◆</span> {`${finding.id} ${d.host}`}{" "}
                  <span className="fabric3d-pointer__note">off view</span>
                </button>
              ))
          : null}
      </div>
    </>
  );
}
