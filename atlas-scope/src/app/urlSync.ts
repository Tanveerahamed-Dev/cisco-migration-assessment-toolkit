/**
 * urlSync.ts — the investigation IS its link (design brief 5.4).
 *
 * `encodeInvestigation` / `decodeInvestigation` in `src/core/store.ts` own the field grammar and
 * are frozen. This module owns everything around them: the envelope that makes a stale link
 * detectable, when a write is a history entry and when it is not, and the coalescing that stops a
 * typed query from filling the back stack with one entry per keystroke.
 *
 * Three decisions here are load-bearing.
 *
 * 1. VERSIONED ENVELOPE. A reader that meets a URL from a different build must refuse to parse it
 *    and say so. Partially reconstructing an investigation is the failure mode that matters: the
 *    result looks like a successful reproduction, so the reader draws conclusions from a state
 *    that is not the one the link recorded. `v` is checked BEFORE any field is read.
 *
 * 2. SNAPSHOT BINDING. The link carries the first 12 hex of the snapshot sha256. Ids are only
 *    meaningful against the snapshot that minted them — `core1`, `F013` and `punchlist[12]`
 *    resolve against a different snapshot to a different thing, or to nothing. A mismatch is
 *    surfaced, never silently applied and never silently dropped either.
 *
 * 3. FURNITURE STAYS OUT. Inspector height, rail split, column visibility and theme are
 *    preferences and live in localStorage. If they rode in the link, two people opening the same
 *    URL would see "different" investigations that are in fact identical, and the URL would stop
 *    being a clean reproduction key.
 */
import { useEffect, useRef, useState } from "react";

import { fabric } from "../core/data";
import {
  decodeInvestigation,
  encodeInvestigation,
  useInvestigation,
  type EvidenceTab,
  type InvestigationState,
} from "../core/store";
import type { SurfaceId } from "../core/types";

/** Bumped only when the field grammar changes meaning. An unknown value is refused, not guessed. */
export const URL_SCHEMA_VERSION = 1;

const V_PARAM = "v";
const SNAP_PARAM = "snap";

/** 12 hex is 48 bits — unambiguous across any plausible number of snapshots, and short enough that
 *  the link stays readable in a chat message, which is where these links actually travel. */
const SNAP_LEN = 12;

export const snapshotTag = (): string => fabric.meta.sourceSha256.slice(0, SNAP_LEN);

/**
 * Fields whose change is a NAVIGATION — a step the reader should be able to walk back through.
 * Everything else (query text, severity chips, role chips, the evidence tab) is an in-progress
 * edit and overwrites the current history entry instead of adding one.
 */
const NAVIGATION_FIELDS = ["deviceId", "linkId", "findingId", "hopIndex", "surface"] as const;

const navigationSignature = (s: InvestigationState): string => {
  const f = s.flow;
  const flow = f === null ? "" : `${f.srcIp}>${f.dstIp}>${f.protocol}>${f.dstPort ?? ""}`;
  /* WHO made the device selection is part of the step (store.ts SelectionOrigin): choosing the
     trace's own hop host from the palette changes the question on the fabric (its blast radius is
     drawn) and adds `d=` to the link, so Back must be able to return to the trace's picture. */
  return [...NAVIGATION_FIELDS.map((k) => (s[k] === null ? "" : String(s[k]))), s.deviceOrigin, flow].join("|");
};

/** The query string this state serialises to, envelope included. */
export function encodeUrl(s: InvestigationState): string {
  const p = new URLSearchParams(encodeInvestigation(s));
  p.set(V_PARAM, String(URL_SCHEMA_VERSION));
  p.set(SNAP_PARAM, snapshotTag());
  return p.toString();
}

export type UrlProblem =
  | { kind: "unknown-version"; found: string; message: string }
  | { kind: "snapshot-mismatch"; found: string; expected: string; message: string };

export interface UrlRead {
  /** Empty when the envelope was refused — a refused link contributes no state at all. */
  patch: Partial<InvestigationState>;
  problem: UrlProblem | null;
  /** True when the URL carried nothing beyond the envelope, i.e. a first visit. */
  empty: boolean;
}

/**
 * Parse a query string into a store patch.
 *
 * A link with no `v` at all is read as version 1: it is either hand-typed or predates the
 * envelope, and both are unambiguous against the current grammar. A link carrying a `v` this
 * build does not implement is refused outright — there is no partial-credit reading of a grammar
 * we do not have.
 */
export function readUrl(search: string): UrlRead {
  const p = new URLSearchParams(search);
  const version = p.get(V_PARAM);
  const snap = p.get(SNAP_PARAM);

  p.delete(V_PARAM);
  p.delete(SNAP_PARAM);
  const body = p.toString();
  const empty = body === "";

  if (version !== null && version !== String(URL_SCHEMA_VERSION)) {
    return {
      patch: {},
      problem: {
        kind: "unknown-version",
        found: version,
        message:
          `This link was written in link format ${version}; this build reads format ` +
          `${URL_SCHEMA_VERSION}. Nothing from it has been applied, because reading it with the ` +
          `wrong grammar would rebuild a state that is not the one the link recorded. Ask for the ` +
          `link to be shared again from a matching build.`,
      },
      empty,
    };
  }

  const expected = snapshotTag();
  if (snap !== null && snap !== expected) {
    return {
      patch: {},
      problem: {
        kind: "snapshot-mismatch",
        found: snap,
        expected,
        message:
          `This link points at snapshot ${snap}; the snapshot loaded here is ${expected}. Device, ` +
          `finding and citation ids are only meaningful against the snapshot that minted them, so ` +
          `nothing from the link has been applied. What is on screen is the unfiltered current ` +
          `snapshot, not the investigation the link recorded.`,
      },
      empty,
    };
  }

  return { patch: decodeInvestigation(body), problem: null, empty };
}

/* ── the hook ──────────────────────────────────────────────────────────────── */

interface SyncOptions {
  /** Test seam. Defaults to `requestAnimationFrame`, so writes coalesce to at most one a frame. */
  schedule?: (fn: () => void) => () => void;
}

/**
 * A frame OR a task, whichever arrives first, and exactly one of them runs.
 *
 * `requestAnimationFrame` alone is wrong here and the failure is silent and permanent: a hidden or
 * backgrounded tab never paints, so the callback is never called, and because the caller treats a
 * scheduled flush as "one is already pending" it never schedules another either. The URL then
 * stops mirroring the investigation for the rest of the session while the app keeps working
 * perfectly — which is precisely the "looks fine, is wrong" failure this module exists to prevent.
 * Measured: typing into the query bar with the browser pane hidden left the address bar empty and
 * it never caught up after the pane was shown again.
 *
 * The timeout is the floor that guarantees delivery; the frame is kept because when the tab IS
 * visible it aligns the write with the paint that accompanies it.
 */
const rafSchedule = (fn: () => void): (() => void) => {
  let settled = false;
  const run = (): void => {
    if (settled) return;
    settled = true;
    fn();
  };
  const timer = setTimeout(run, 0);
  const frame = typeof requestAnimationFrame === "function" ? requestAnimationFrame(run) : null;
  return () => {
    settled = true;
    clearTimeout(timer);
    if (frame !== null) cancelAnimationFrame(frame);
  };
};

const DEFAULT_SURFACE: SurfaceId = "fabric";
const DEFAULT_TAB: EvidenceTab = "summary";

/**
 * Returning to a history entry must REMOVE the fields that entry did not carry. `store.reset()`
 * clears the selection and the scope but deliberately leaves the view state alone, so the two
 * view fields the URL does carry are restored to their defaults here before the patch is applied.
 * Without this, walking Back from an evidence-tab link leaves the rail on a tab that entry never
 * named — a state that never existed in the history the reader is walking.
 */
function applyHistoryState(patch: Partial<InvestigationState>): void {
  const s = useInvestigation.getState();
  s.reset();
  s.setSurface(patch.surface ?? DEFAULT_SURFACE);
  s.setEvidenceTab(patch.evidenceTab ?? DEFAULT_TAB);
  if (Object.keys(patch).length > 0) s.hydrate(patch);
}

/**
 * Hydrate from the URL once, then keep the URL in step with the store.
 *
 * Returns the envelope problem, if any, so the shell can render it. It is returned rather than
 * announced from in here because a refused link is a standing fact about what is on screen — a
 * toast that expires would leave the reader believing they are looking at the state they were
 * sent.
 */
export function useUrlSync(opts: SyncOptions = {}): UrlProblem | null {
  const schedule = opts.schedule ?? rafSchedule;
  const [problem, setProblem] = useState<UrlProblem | null>(null);

  /* Set while a popstate is being applied to the store, so the subscription below does not write
     the URL back and turn a Back press into a no-op the user has to press twice. */
  const applying = useRef(false);
  /* The signature at the last history write. A push happens only when this changes, so the back
     stack holds investigative steps and not keystrokes. */
  const lastNav = useRef<string | null>(null);
  const lastSearch = useRef<string | null>(null);

  useEffect(() => {
    const store = useInvestigation;

    const read = readUrl(window.location.search);
    if (read.problem !== null) setProblem(read.problem);
    if (Object.keys(read.patch).length > 0) store.getState().hydrate(read.patch);

    const initial = store.getState();
    lastNav.current = navigationSignature(initial);
    lastSearch.current = encodeUrl(initial);
    /* Normalise the address bar to the envelope form on arrival, replacing rather than pushing:
       landing on a page must not create a history entry the reader never navigated to. */
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}?${lastSearch.current}`,
    );

    let cancel: (() => void) | null = null;

    const flush = (): void => {
      cancel = null;
      const s = store.getState();
      const search = encodeUrl(s);
      const nav = navigationSignature(s);
      /* Nothing to write — but a step can still have happened: the trace's own re-aim lands a device
         WITHOUT adding `d=` (store.ts encodeInvestigation), so the signature moves while the link does
         not. Record it, or the next in-progress edit is compared with the pre-landing signature and
         pushed as a history entry of its own. */
      if (search === lastSearch.current) {
        lastNav.current = nav;
        return;
      }

      const isNavigation = nav !== lastNav.current;
      lastNav.current = nav;
      lastSearch.current = search;

      const url = `${window.location.pathname}?${search}`;
      if (isNavigation) window.history.pushState(null, "", url);
      else window.history.replaceState(window.history.state, "", url);
    };

    const unsubscribe = store.subscribe(() => {
      if (applying.current) return;
      /* Coalesced, not debounced on a timer: a timer either loses the last write when the tab is
         backgrounded or lands a stale one after it. One write per frame is bounded by the same
         clock as the rendering it accompanies. */
      if (cancel === null) cancel = schedule(flush);
    });

    const onPop = (): void => {
      const back = readUrl(window.location.search);
      setProblem(back.problem);
      applying.current = true;
      try {
        applyHistoryState(back.patch);
      } finally {
        applying.current = false;
      }
      const s = store.getState();
      lastNav.current = navigationSignature(s);
      lastSearch.current = encodeUrl(s);
    };

    window.addEventListener("popstate", onPop);
    return () => {
      cancel?.();
      unsubscribe();
      window.removeEventListener("popstate", onPop);
    };
  }, [schedule]);

  return problem;
}
