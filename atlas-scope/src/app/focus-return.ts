/**
 * focus-return.ts — the ONE owner of "put focus back when a surface lets go of it" (acceptance D3).
 *
 * THE DEFECT CLASS. Several surfaces release focus — the query bar on Escape, the grid on Escape, a
 * popover or dialog as it closes — and each wrote its own two-line restore:
 *
 *     if (back && back.isConnected) back.focus(); else e.currentTarget.blur();
 *
 * The else-arm is the bug. `blur()` does not move focus anywhere; it removes it, and the browser
 * parks it on <body>. A keyboard reader's next Tab then starts again from the top of the page, and
 * a screen reader announces nothing at all. MEASURED (acceptance-report D3, 2 of 2): snapshot
 * popover, Tab, Escape — the return target recorded on the query input's `focus` event was the
 * popover's own Copy button, which unmounted as the popover closed, so the else-arm ran. The grid
 * had the same arm unconditionally: its only host passes no exit target, so Escape out of the
 * findings grid always went to <body>.
 *
 * THE RULE, owned here and nowhere else:
 *   1. Return to the recorded target if it is still connected and can take focus.
 *   2. Otherwise to the element that OPENED the surface the target lived in — captured at record
 *      time, because by restore time the surface (and so the link to its opener) may be gone. The
 *      opener is found structurally: the element whose `aria-controls` names an ancestor of the
 *      target, which is how every disclosure, popover and menu trigger here declares itself.
 *   3. Otherwise to any explicit fallbacks the caller names, in order.
 *   4. Otherwise to the region landmark around the element giving focus up — its labelling heading
 *      when it is `aria-labelledby` one, else the labelled region itself — made programmatically
 *      focusable (`tabindex=-1`, never a Tab stop) for as long as it holds focus; and when that region is
 *      no longer rendered, the next named region OUTWARD, and so on (every door walks outward: the first
 *      door once tried only the nearest region and the recorded one, and left focus on <body> with an
 *      outer region still shown — independent verifier V2-3, focus-return.rule4-doors.test.ts).
 *   5. Otherwise leave focus exactly where it is.
 * Never blur, and never land on <body>.
 *
 * A SECOND DOOR, SAME RULE: a control that removes ITSELF (`handOffFocus`). A chip's remove button,
 * "Clear scope", an empty state's own reset — the element holding focus is the thing the action
 * takes out of the document, so there is nothing to "return" to and the browser parks focus on
 * <body>. MEASURED (acceptance report D3, overturned PASS to FAIL): 'Remove the Critical severity
 * filter' reached after 7 Tabs, Enter, and 2.5 s later activeElement was BODY with no ring; the same
 * for 'Remove the High severity filter', 'Clear scope', 'Deselect device core1' and 'Stop
 * investigating the flow …'. Such a control names no successor by hand. Its successor is found
 * STRUCTURALLY, before the action runs, while everything around it still exists:
 *   a. the nearest tab stop in the control's set that survives — the next one, else the previous
 *      one — where the set is the nearest labelled group, list, toolbar or landmark around it (the
 *      next chip, else the previous chip);
 *   b. else the caller's stated successors, in order (the query field a scope bar edits);
 *   c. else the set's labelling element, else the region landmark — made focusable as in rule 4.
 * It acts only if focus was actually lost: a surface that already moved focus somewhere real (the
 * grid, a heading it announces) keeps it. `src/app/self-removing-focus.test.tsx` presses EVERY tab
 * stop of the mounted application with Enter and with Space and fails on any self-removing control
 * that leaves focus on <body>; `review/audit-d3-focus.mjs --self-removing` does the same in Chromium
 * by real Tab presses and also measures the successor's ring.
 *
 * A THIRD DOOR, SAME RULE: a CONTAINER hidden while it holds focus (`releaseFocusFrom`, and its
 * React form `useReleaseFocusOnHide`). Nothing is removed and no surface "closes" in the sense above:
 * the element holding focus stays connected, and the container around it becomes unrendered — the
 * `hidden` attribute, `display: none` at a layout rung, or a CSS `visibility` step. The browser then
 * parks focus on <body> on its own, at the moment the hide takes effect. MEASURED (acceptance report
 * D3, overturned PASS to FAIL): the evidence drawer (Rail B at 1024–1279 px) closed by `e`, by the
 * palette's "Toggle the evidence rail", and by a resize to 900 px, each with focus on its "Finding"
 * radio — the last sample still in the rail at 251 ms, <body> at 276 ms, exactly the drawer's
 * delayed 240 ms `visibility` step. No code ran on that path at all, so no guard shape could see it.
 * The door is called SYNCHRONOUSLY on the shown -> hidden transition (a layout effect, before any
 * delayed style step), and acts only when focus is inside the container. Its order:
 *   a. the recorded target (what held focus when a READER'S ACTION showed the container — the drawer's
 *      opener; a show that is part of a commit changing a declared layout records nothing, so a hide
 *      never returns to whatever happened to hold focus when a resize showed the rail — independent
 *      verifier R5-V2-5, a landing that depended on history),
 *   b. that target's opener (rule 2),
 *   c. the caller's fallbacks, in order,
 *   d. the region landmark around the container, then the target's recorded region (rule 4),
 *   e. the nearest tab stop OUTSIDE the container in document order — the next one, else the
 *      previous one — so there is always somewhere real left to go;
 * and from that same commit the container is `inert` until it is shown again, so neither Tab nor a
 * later focus() can walk back into it while a closing slide still paints it (measured by the
 * independent verifier: seven fast Tabs after `e` re-entered the sliding drawer and ended on <body>);
 * every candidate INSIDE the container is passed over (it is still rendered, and so still accepts
 * focus, for as long as the container's closing transition runs), and so is every candidate that is not
 * rendered (`isRendered`: a `hidden` subtree, `display: none` however set, `visibility: hidden`) — the one
 * test every door's `tryFocus` applies. `src/app/drawer-focus-return.test.tsx` drives the drawer's three close paths, a
 * lost opener and a resize; `review/audit-d3-focus.mjs --sweep` drives them in Chromium at every
 * drawer width derived from the ladder, with the real 240 ms step.
 *
 * A FOURTH DOOR, SAME RULE: a LAYOUT CHANGE that takes the focused element away
 * (`releaseFocusAfterLayoutChange`, and its React form `useReleaseFocusOnLayoutChange`). A rung
 * crossing, or a fold decided by measurement, mounts one form of a control and unmounts the other, or
 * stops rendering a whole region: nothing "closes", nobody "removes itself", and no container is
 * declared hidden — the element holding focus is simply not in the new layout. MEASURED (independent
 * verifier, D3-R2-1, release build): 11 of 74 tab stops lost to <body> across 7 rung crossings — the
 * pane switch below 1024 px ('900->1100 BUTTON.paneswitch__btn "Queue" -> BODY'), the header's More
 * button, popover and inline toolbar ('1100 "Copy the link…" -> 1100->900 BODY'), the queue's View
 * disclosure ('1100->1440 BUTTON.ui-btn "View" -> BODY') and the fabric's controls when the stage
 * collapses ('768->390 BUTTON.fabric3d__btn "Legend" -> BODY'). The owner follows focus (`focusin`, so
 * it still knows the element and its ancestors after React has removed them), and the component that
 * DECIDES the layout declares it — `useReleaseFocusOnLayoutChange(<the value the layout is keyed on>)`
 * — so the release runs in the layout phase of the very commit that took the element away. It acts
 * only when that element is gone from the rendered page and focus is nowhere real, and hands focus to
 * its DOCUMENTED SUCCESSOR, in order:
 *   a. its TWIN in the new layout — a rendered control with the same role and accessible name (the
 *      inline "Copy the link…" for the same button inside the More popover that just unmounted);
 *   b. the successor its surface STATES: `data-focus-successor` (FOCUS_SUCCESSOR_ATTR) on the lost
 *      element or its nearest recorded ancestor that carries one — selectors tried in order, each
 *      match landed on itself when it takes focus, else on its first rendered tab stop (the pane
 *      switch names the region of the pane it chose; the stage names the fabric toggle that stands for
 *      it below 768 px; the header names More, else its inline surface toolbar);
 *   c. the caller's fallbacks; d. the landmark around the nearest surviving ancestor, then its first
 *      tab stop.
 * `src/app/rung-focus-crossing.test.tsx` drives the unmount shapes through the real frame at the
 * real ladder widths, and `review/audit-d3-focus.mjs --sweep` (its rung-crossing pass) focuses EVERY
 * rendered tab stop — and every tab stop inside every surface a control's activation reveals, found by
 * the effect (the tab stops that were not there before) — at one width per rung, crosses to each
 * neighbouring rung, and fails on <body> or on a landing that is not seen.
 *
 * `src/app/focus-return.guard.test.ts` parses every source
 * file and fails on a `.blur()` call anywhere but here, on an `isConnected` focus branch whose
 * else-arm does not call this module, on a state-driven `hidden`/`inert` attribute on an element
 * whose `ref` is not the container a third-door call names, on a write from script whose DOM effect
 * leaves an element unrendered or detached (its hidden/inert state, a hiding style however written, a
 * popover or dialog closed, a removal or a contents replacement) on an element no third-door call names
 * (on it or an ancestor), and on a component that renders from the viewport ladder without declaring
 * the fourth door keyed on it.
 */
import { useLayoutEffect, useRef, type RefObject } from "react";

/** Where focus should go back to, and — captured while it still exists — what opened its surface. */
export interface ReturnRecord {
  readonly target: HTMLElement;
  readonly opener: HTMLElement | null;
  /**
   * The named landmark the target sat in (or its labelling heading), captured while the target
   * still exists: the last place that still means "where you were" once the target, its opener and
   * every stated fallback are gone. See `src/app/focus-return.region.test.ts` (a phone-width
   * Inspector close whose citation had re-rendered, and whose stage fallback was display:none).
   */
  readonly region: HTMLElement | null;
  /**
   * EVERY named region the target sat in, nearest first, captured with it: rule 4's outward walk from where the
   * reader was, which must still be possible once the target's own subtree (and so its path to the outer regions)
   * has been removed (independent verifier V2-3).
   */
  readonly regions: readonly HTMLElement[];
}

type Candidate = HTMLElement | null | undefined;

/**
 * Landmark regions a surface can fall back to. Deliberately structural (role or element plus an
 * accessible name), never a list of this application's class names.
 */
const REGION_SELECTOR = [
  "[role='region']",
  "[role='search']",
  "[role='dialog']",
  "[role='complementary']",
  "[role='main']",
  "[role='navigation']",
  "[role='form']",
  "section",
  "form",
  "aside",
  "main",
  "nav",
].join(",");

const isNamed = (el: Element): boolean =>
  (el.getAttribute("aria-label") ?? "").trim() !== "" || (el.getAttribute("aria-labelledby") ?? "").trim() !== "";

/** The ids an ID-reference list attribute names (`aria-labelledby`, `aria-controls`): whitespace-separated, empty
 *  entries dropped. The ONE place this module splits such a list — a restated split once used `/s+/`, the letter s,
 *  and misread every id containing one (focus-return.labelledby.test.ts). */
const idRefs = (el: Element, attr: string): string[] => (el.getAttribute(attr) ?? "").split(/\s+/).filter((id) => id !== "");

/** How a named region is stated: the heading its `aria-labelledby` names when that heading lies inside it, else the
 *  region itself. The ONE statement of that rule, for `landmarkOf` and the second door's outer walk alike. */
function statedRegion(n: HTMLElement): HTMLElement {
  const by = idRefs(n, "aria-labelledby")[0];
  const heading = by === undefined ? null : document.getElementById(by);
  return heading instanceof HTMLElement && n.contains(heading) ? heading : n;
}

/** Every named region around `from` (excluding `from` itself), nearest first. */
function namedRegionsAround(from: Element | null | undefined): HTMLElement[] {
  const out: HTMLElement[] = [];
  for (let n = from?.parentElement?.closest<HTMLElement>(REGION_SELECTOR) ?? null; n !== null; n = n.parentElement?.closest<HTMLElement>(REGION_SELECTOR) ?? null) {
    if (isNamed(n)) out.push(n);
  }
  return out;
}

/** RULE 4's places for ONE named region, in order: its labelling heading (`statedRegion`), else the region itself. The
 *  ONE statement of "else the labelled region itself" — every door tries both, so a region whose heading sits in a
 *  part of it that is not rendered is still a place (focus-return.rule4-doors.test.ts, independent verifier V1-1). */
const placesOf = (n: HTMLElement): HTMLElement[] => {
  const h = statedRegion(n);
  return h === n ? [n] : [h, n];
};

/** The places a RECORDED region (`ReturnRecord.region`, stated as `landmarkOf` states it) stands for: itself, and —
 *  when it is a labelling heading — the region it labels. */
function recordedPlaces(stated: HTMLElement): HTMLElement[] {
  for (const n of namedRegionsAround(stated)) if (statedRegion(n) === stated) return [stated, n];
  return [stated];
}

/** The element whose `aria-controls` names `el` or one of its ancestors: the surface's opener. */
function openerOf(el: HTMLElement): HTMLElement | null {
  if (typeof document === "undefined") return null;
  const controllers = [...document.querySelectorAll<HTMLElement>("[aria-controls]")];
  if (controllers.length === 0) return null;
  for (let n: HTMLElement | null = el; n !== null; n = n.parentElement) {
    const id = n.id;
    if (id === "") continue;
    const hit = controllers.find(
      (c) => !n!.contains(c) && idRefs(c, "aria-controls").includes(id),
    );
    if (hit) return hit;
  }
  return null;
}

/**
 * Record where focus came from. `from` is typically a focus event's `relatedTarget`; `self` is the
 * element receiving focus, which is never its own return target.
 */
export function recordReturn(from: EventTarget | null | undefined, self?: Element | null): ReturnRecord | null {
  if (typeof HTMLElement === "undefined" || !(from instanceof HTMLElement)) return null;
  if (from === self || from === document.body) return null;
  return { target: from, opener: openerOf(from), region: landmarkOf(from), regions: namedRegionsAround(from) };
}

const takesFocus = (el: HTMLElement): boolean =>
  el.isConnected &&
  el !== document.body &&
  el.closest("[inert]") === null &&
  el.closest("[aria-hidden='true']") === null &&
  !(el as HTMLButtonElement).disabled;

/**
 * Focus `el` and report whether it actually took focus. Only a RENDERED element is tried (`isRendered`): a browser
 * refuses focus() on an element in a `hidden` or `display: none` subtree, and jsdom does not, so without this every
 * door's answer depended on the engine running it (the first door focused a heading in a hidden subtree and a target
 * in a pane a stylesheet hides — independent verifier V1-1, focus-return.rule4-doors.test.ts). One statement for every
 * door, not one filter per door.
 */
function tryFocus(el: Candidate): boolean {
  if (!el || !takesFocus(el) || !isRendered(el)) return false;
  el.focus({ preventScroll: false });
  return document.activeElement === el;
}

/** The labelled region around `from` (or its labelling heading), excluding `from` itself. */
function landmarkOf(from: Element | null | undefined): HTMLElement | null {
  const n = namedRegionsAround(from)[0];
  return n === undefined ? null : statedRegion(n);
}

/** Make a landmark programmatically focusable for exactly as long as it holds focus. */
function focusLandmark(el: HTMLElement): boolean {
  if (!takesFocus(el)) return false;
  const added = !el.hasAttribute("tabindex");
  if (added) {
    el.setAttribute("tabindex", "-1");
    el.addEventListener("blur", () => el.removeAttribute("tabindex"), { once: true });
  }
  if (tryFocus(el)) return true;
  if (added) el.removeAttribute("tabindex");
  return false;
}

/**
 * Return focus. `record` is what `recordReturn` captured (or a plain element); `context` is the
 * element giving focus up, used to find the region landmark; `fallbacks` are the caller's explicit
 * next choices. Order: the target, its opener, the fallbacks, the landmark around `context`, the
 * landmark the target sat in when it was recorded (`ReturnRecord.region`), and then rule 4's OUTWARD walk:
 * every further named region around `context`, then every further one the target sat in, nearest first —
 * each as its heading, else itself. Returns the element that now holds focus, or null when focus was left
 * in place (no candidate and no named region around either is rendered).
 */
export function returnFocus(
  record: ReturnRecord | HTMLElement | null | undefined,
  context: Element | null | undefined,
  fallbacks: readonly Candidate[] = [],
): HTMLElement | null {
  if (typeof document === "undefined") return null;
  const target = record instanceof HTMLElement ? record : (record?.target ?? null);
  const opener = record instanceof HTMLElement ? null : (record?.opener ?? null);
  for (const c of [target, opener, ...fallbacks]) if (c && tryFocus(c)) return c;
  const around = namedRegionsAround(context);
  const tried = new Set<HTMLElement>();
  const tryPlace = (m: HTMLElement): boolean => {
    if (tried.has(m)) return false;
    tried.add(m);
    return focusLandmark(m);
  };
  const nearest = around[0];
  if (nearest !== undefined) for (const m of placesOf(nearest)) if (tryPlace(m)) return m;
  const region = record instanceof HTMLElement ? null : (record?.region ?? null);
  if (region !== null) {
    /* The region's first heading that can take focus names the same place and is small enough for
       its ring to be seen whole; a ring round a tall, rail-clipped region measured under half its
       perimeter (focus-return.region.test.ts). Headings in a hidden sub-pane refuse focus and are
       passed over; the region itself is the last resort — and a recorded HEADING that no longer
       renders stands for the region it labels (rule 4). */
    if (!tried.has(region) && !/^H[1-6]$/.test(region.tagName)) {
      for (const h of region.querySelectorAll<HTMLElement>("h1, h2, h3, h4, h5, h6")) if (tryPlace(h)) return h;
    }
    for (const m of recordedPlaces(region)) if (tryPlace(m)) return m;
  }
  /* Rule 4 OUTWARD (independent verifier V2-3): past every region that is no longer rendered, the next one out —
     around the element giving focus up, then around where the target was (captured with it, so a removed subtree
     does not cut the walk short). */
  const recorded = record instanceof HTMLElement ? namedRegionsAround(record) : (record?.regions ?? []);
  for (const n of [...around.slice(1), ...recorded]) for (const m of placesOf(n)) if (tryPlace(m)) return m;
  return null;
}

/* ══ a container hidden while it holds focus ═════════════════════════════════ */

/** Tab stops in document order, filtered by `isTabStop`. Hoisted use: defined with the second door. */
function tabStopsOf(root: ParentNode): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>(TAB_STOP_SELECTOR)].filter(isTabStop);
}

/**
 * The THIRD DOOR (see the module comment): `container` is about to stop being rendered. If focus is
 * inside it, move focus out — to the recorded target, its opener, the caller's fallbacks, the landmark
 * around the container, the target's recorded region, and last the nearest tab stop outside the
 * container in document order — never to a candidate inside the container or inside a `hidden`
 * subtree, and never to <body>. Returns the element that now holds focus, or null when focus was not
 * inside the container (nothing to do) or nothing outside it could take focus.
 */
export function releaseFocusFrom(
  container: Element | null | undefined,
  record: ReturnRecord | HTMLElement | null | undefined,
  fallbacks: readonly Candidate[] = [],
): HTMLElement | null {
  if (typeof document === "undefined" || !container) return null;
  const active = document.activeElement;
  if (active === null || !container.contains(active)) return null;
  /* Outside the container, and RENDERED — the owner's one statement of it (`isRendered`: no `hidden` subtree, a box,
     not `visibility: hidden`), not the `hidden` attribute alone, which stood in for the class and let a candidate a
     stylesheet hides through (focus-return.handoff-hidden.test.ts). */
  const usable = (el: Candidate): el is HTMLElement => el instanceof HTMLElement && !container.contains(el) && isRendered(el);
  const attempt = (el: Candidate): boolean => usable(el) && tryFocus(el);

  const target = record instanceof HTMLElement ? record : (record?.target ?? null);
  const opener = record instanceof HTMLElement ? null : (record?.opener ?? null);
  for (const c of [target, opener, ...fallbacks]) if (attempt(c)) return c as HTMLElement;

  /* Rule 4, as every door states it: the region around the container as its heading, else itself; then the target's
     recorded region the same way (placesOf / recordedPlaces). */
  const around = namedRegionsAround(container)[0];
  const marks = around === undefined ? [] : placesOf(around);
  for (const m of marks) if (usable(m) && focusLandmark(m)) return m;
  const region = record instanceof HTMLElement ? null : (record?.region ?? null);
  if (region !== null) for (const m of recordedPlaces(region)) if (!marks.includes(m) && usable(m) && focusLandmark(m)) return m;

  /* The nearest tab stop outside, by document position relative to the container. */
  const stops = tabStopsOf(document).filter((s) => usable(s));
  const after = stops.filter((s) => (container.compareDocumentPosition(s) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0);
  const before = stops.filter((s) => (container.compareDocumentPosition(s) & Node.DOCUMENT_POSITION_PRECEDING) !== 0).reverse();
  for (const s of [...after, ...before]) if (tryFocus(s)) return s;
  return null;
}

const NO_FALLBACKS = (): readonly Candidate[] => [];

/**
 * The declared layouts (fourth-door users) whose value changes in the commit being rendered. A declarer
 * adds itself while it RENDERS a changed value and leaves in that commit's layout phase — after its
 * descendants' layout effects (the rails' third doors run first) and after its own earlier hooks'. So
 * while any is pending, a container shown in this commit was shown by the LAYOUT, not by a reader's
 * action (independent verifier R5-V2-5). A render that is discarded before it commits leaves its
 * declarer's token until that declarer next commits (the membership check below runs every commit).
 */
const layoutChanging = new Set<object>();

/**
 * The third door as a React hook, for the component that decides whether `ref`'s element is SHOWN.
 * On a hidden -> shown transition made by a READER'S ACTION it records what holds focus at that moment
 * (for a drawer, the control that opened it — focus has not moved yet when the open commits). A show
 * that is part of a commit changing a declared layout (a resize across a rung: `layoutChanging`)
 * records nothing, and the record is cleared: what held focus when a resize showed the rail is not the
 * rail's opener, and returning there on a later hide made the landing depend on history (independent
 * verifier R5-V2-5). Such a container's hide goes to the stated fallbacks and on down the order, which
 * is where a fresh load goes. On every shown -> hidden
 * transition it calls `releaseFocusFrom` synchronously, in the layout phase, before the browser gets
 * to a delayed style step or its own focus fix-up. `fallbacks` is read when the release runs.
 *
 * A container that is not shown is also made `inert`, from the same commit, for as long as it is not
 * shown — after the release, so focus leaves before the container stops accepting it. Releasing once
 * is not enough when the hide is a delayed style step: MEASURED (independent verifier, release build,
 * 1100 px), seven Tab presses right after the drawer closed walked focus back INTO the still-visible
 * sliding rail, and 600 ms later it was on <body>; a programmatic focus() did the same. `inert` makes
 * the browser skip the container for Tab and refuse focus() into it at once, while its slide still
 * paints. The hook removes only an `inert` it set itself.
 */
export function useReleaseFocusOnHide(
  ref: RefObject<Element | null>,
  shown: boolean,
  fallbacks: () => readonly Candidate[] = NO_FALLBACKS,
): void {
  const was = useRef(shown);
  const record = useRef<ReturnRecord | null>(null);
  const madeInert = useRef(false);
  const latestFallbacks = useRef(fallbacks);
  latestFallbacks.current = fallbacks;
  useLayoutEffect(() => {
    const before = was.current;
    was.current = shown;
    if (typeof document === "undefined") return;
    const el = ref.current;
    if (shown) {
      if (madeInert.current && el !== null) el.removeAttribute("inert");
      madeInert.current = false;
      if (before !== shown) record.current = layoutChanging.size > 0 ? null : recordReturn(document.activeElement, el);
      return;
    }
    if (before !== shown) {
      releaseFocusFrom(el, record.current, latestFallbacks.current());
      record.current = null;
    }
    if (el !== null && !el.hasAttribute("inert")) {
      el.setAttribute("inert", "");
      madeInert.current = true;
    }
  }, [shown, ref]);
}

/* ══ a control that removes itself ═══════════════════════════════════════════ */

/** A stated successor: an element, or a function that finds it when the hand-off runs. */
export type Successor = Candidate | (() => Candidate);

/** Anything that can be a tab stop. Filtered by `isTabStop`; never a list of this app's classes. */
const TAB_STOP_SELECTOR = "a[href], button, input, select, textarea, summary, [tabindex], [contenteditable='true']";

/**
 * The SET a control belongs to: the nearest ancestor that groups controls and says so — an ARIA
 * grouping role, a list, a fieldset, a region landmark, or any element carrying an accessible name.
 */
const SET_SELECTOR = [
  "[role='group']",
  "[role='toolbar']",
  "[role='list']",
  "[role='listbox']",
  "[role='radiogroup']",
  "[role='tablist']",
  "[role='menu']",
  "[role='menubar']",
  "ul",
  "ol",
  "fieldset",
  "[aria-label]",
  "[aria-labelledby]",
  REGION_SELECTOR,
].join(",");

const isTabStop = (el: HTMLElement): boolean =>
  el.tabIndex >= 0 && !(el instanceof HTMLInputElement && el.type === "hidden") && takesFocus(el);

interface HandOffPlan {
  /** Tab stops of the control's set, nearest first: every one after it, then every one before it. */
  readonly siblings: readonly HTMLElement[];
  /** The set's labelling element, when it is `aria-labelledby` one that lies outside the set. */
  readonly label: HTMLElement | null;
  /**
   * Rule 4's places, nearest first: every named region around the control, each as its labelling heading (when it
   * is `aria-labelledby` one inside it) and then as the region itself. The first is `landmarkOf`'s answer; the rest
   * are where rule 4 goes when that one is no longer rendered — including the region itself when its heading is not.
   */
  readonly regions: readonly HTMLElement[];
}

/** Everything the hand-off may need, captured while the control and its surroundings still exist. */
function planHandOff(control: HTMLElement): HandOffPlan {
  const set = control.parentElement?.closest<HTMLElement>(SET_SELECTOR) ?? control.parentElement;
  const stops =
    set === null
      ? []
      : [...set.querySelectorAll<HTMLElement>(TAB_STOP_SELECTOR)].filter((s) => s !== control && !control.contains(s) && isTabStop(s));
  const after = stops.filter((s) => (control.compareDocumentPosition(s) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0);
  const before = stops.filter((s) => (control.compareDocumentPosition(s) & Node.DOCUMENT_POSITION_PRECEDING) !== 0).reverse();
  const by = set === null ? undefined : idRefs(set, "aria-labelledby")[0];
  const labelEl = by === undefined ? null : document.getElementById(by);
  /* Every named region around the control, nearest first, each as landmarkOf states it (its labelling heading) and
     then as itself — rule 4's "else the labelled region itself", which a heading in a hidden part of the region
     needs (focus-return.handoff-hidden.test.ts). Walked by REGION, not by the stated element, so a region labelled
     by a heading inside it does not stop the walk at that heading. */
  const regions: HTMLElement[] = [];
  for (const n of namedRegionsAround(control)) for (const m of placesOf(n)) if (!regions.includes(m)) regions.push(m);
  return {
    siblings: [...after, ...before],
    label: labelEl instanceof HTMLElement && set !== null && !set.contains(labelEl) ? labelEl : null,
    regions,
  };
}

/** Focus is lost when nothing real holds it: <body>, nothing, or an element no longer in the page. */
const focusLost = (): boolean => {
  const a = document.activeElement;
  return a === null || a === document.body || a === document.documentElement || !a.isConnected;
};

/** When to look again after the action: a microtask (React's discrete-event commit has run by then),
 *  a task, and a frame-and-a-bit — the last for a removal that waits on a debounce or an effect. */
const HANDOFF_DELAYS_MS: readonly number[] = [0, 50, 200];

/**
 * Run `action`, which removes `control` (or may), and if that leaves focus nowhere hand it to the
 * control's structural successor (see the module comment, "A SECOND DOOR"). Call it from the
 * control's activation handler — the click that Enter and Space also produce — with the control as
 * `control`, typically `event.currentTarget`.
 */
export function handOffFocus(control: EventTarget | null | undefined, action: () => void, stated: readonly Successor[] = []): void {
  if (typeof document === "undefined" || typeof HTMLElement === "undefined" || !(control instanceof HTMLElement)) {
    action();
    return;
  }
  const plan = planHandOff(control);
  action();

  let done = false;
  const attempt = (): void => {
    if (done) return;
    if (!focusLost()) {
      /* Focus is somewhere real. Unless it is still on the control and the control still stands (its
         removal has not been committed yet), that was someone's decision: keep it. */
      if (document.activeElement !== control || !control.isConnected) done = true;
      return;
    }
    done = true;
    /* Never into a `hidden` subtree — the rule the third door already keeps (`releaseFocusFrom`'s `usable`). The action
       may hide the control's whole surface as well as removing the control: the Finding pane's "Select <host>" selects a
       device, and the rail switches to the Device pane and hides the Finding pane with every sibling the plan captured
       (phase 3.5 close, 2026-09-30). A browser refuses focus() there; jsdom does not, so without this the owner's answer
       depended on the engine running it. With the siblings, the label and the nearest landmark all hidden, the next
       SHOWN landmark further out is where focus goes (the Evidence rail around both panes) — never <body>.
       "Hidden" is the owner's one statement of it (`isRendered`), not the `hidden` attribute alone: a pane a
       stylesheet hides (every rung of the ladder hides panes that way) is just as unrendered, and jsdom would focus
       into it where a browser refuses (independent verification of R129, focus-return.handoff-hidden.test.ts). */
    const shown = (el: Candidate): el is HTMLElement => el instanceof HTMLElement && isRendered(el);
    for (const c of plan.siblings) if (shown(c) && tryFocus(c)) return;
    for (const s of stated) {
      const c = typeof s === "function" ? s() : s;
      if (shown(c) && tryFocus(c)) return;
    }
    if (plan.label !== null && shown(plan.label) && focusLandmark(plan.label)) return;
    for (const m of plan.regions) if (shown(m) && focusLandmark(m)) return;
  };
  queueMicrotask(attempt);
  if (typeof setTimeout === "function") for (const ms of HANDOFF_DELAYS_MS) setTimeout(attempt, ms);
}

/* ══ a layout change that takes the focused element away ═════════════════════ */

/**
 * The attribute a surface states its successor in: a comma-separated list of selectors, tried in
 * order, each match "landed on" as `landOn` says. Read from the lost element first and then from each
 * of its recorded ancestors, nearest first — so a control can name its own successor and a region can
 * name one for everything inside it. Read at release time: a surviving ancestor answers for the NEW
 * layout (its attribute has re-rendered), a removed one for the layout it was removed from.
 */
export const FOCUS_SUCCESSOR_ATTR = "data-focus-successor";

/** The last element that received focus, and the ancestors it had then (a removed subtree loses them). */
interface FocusTrail {
  readonly el: HTMLElement;
  readonly ancestors: readonly HTMLElement[];
}
let trail: FocusTrail | null = null;
let trackers = 0;

function trailOf(el: HTMLElement): FocusTrail {
  const ancestors: HTMLElement[] = [];
  for (let n = el.parentElement; n !== null && n !== document.body && n !== document.documentElement; n = n.parentElement) ancestors.push(n);
  return { el, ancestors };
}
const onTrailFocusIn = (e: FocusEvent): void => {
  const t = e.target;
  if (t instanceof HTMLElement && t !== document.body) trail = trailOf(t);
};
/* A pointer press starts a new focus decision: whatever it focuses records itself on `focusin`; a
   press on nothing leaves focus on <body> BY THE READER'S CHOICE, which no later layout change undoes. */
const onTrailPointerDown = (): void => {
  trail = null;
};

/** Start following focus (ref-counted: every door user shares one listener pair). Returns the stop. */
function followFocus(): () => void {
  if (typeof document === "undefined") return () => {};
  if (trackers === 0) {
    document.addEventListener("focusin", onTrailFocusIn, true);
    document.addEventListener("pointerdown", onTrailPointerDown, true);
    const a = document.activeElement;
    trail = a instanceof HTMLElement && a !== document.body ? trailOf(a) : null;
  }
  trackers += 1;
  return () => {
    trackers -= 1;
    if (trackers > 0) return;
    document.removeEventListener("focusin", onTrailFocusIn, true);
    document.removeEventListener("pointerdown", onTrailPointerDown, true);
    trail = null;
  };
}

/**
 * Is `el` RENDERED: in the document, outside a `hidden` subtree, with a box, and not `visibility:
 * hidden`? `checkVisibility` answers in a browser (it forces the style the new layout needs); without
 * it (a test DOM) the computed `display` chain and `visibility` are read instead.
 */
function isRendered(el: Element): boolean {
  if (!el.isConnected || el.closest("[hidden]") !== null) return false;
  const check = (el as Element & { checkVisibility?: (o?: { visibilityProperty?: boolean }) => boolean }).checkVisibility;
  if (typeof check === "function") return check.call(el, { visibilityProperty: true });
  if (typeof getComputedStyle !== "function") return true;
  for (let n: Element | null = el; n !== null; n = n.parentElement) if (getComputedStyle(n).display === "none") return false;
  return getComputedStyle(el).visibility !== "hidden";
}

const roleOf = (el: Element): string => el.getAttribute("role") ?? el.tagName.toLowerCase();
const nameOf = (el: Element): string => (el.getAttribute("aria-label") ?? el.textContent ?? "").replace(/\s+/g, " ").trim();

/**
 * Land on what a successor names: the element itself when it can take focus (a control, or a region
 * that is programmatically focusable, `tabindex=-1`), else its first rendered tab stop, else the
 * element made focusable as a landmark (rule 4). Nothing unrendered, inert or `aria-hidden`.
 */
function landOn(el: Element | null | undefined): HTMLElement | null {
  if (!(el instanceof HTMLElement) || !isRendered(el) || !takesFocus(el)) return null;
  if (el.matches(TAB_STOP_SELECTOR) && tryFocus(el)) return el;
  for (const s of tabStopsOf(el)) if (isRendered(s) && tryFocus(s)) return s;
  return focusLandmark(el) ? el : null;
}

/* ══ a layout change that leaves focus where the reader cannot see it ══════════ */

/** Whether a reader can see any part of an element: "unmeasured" when it has no box to measure. */
type Sight = "seen" | "unseen" | "unmeasured";

/**
 * THE CONTAINING-BLOCK RULE FOR A FIXED BOX, stated ONCE (independent refuter W5-X3): does the element whose computed
 * style is `cs` establish the containing block of its `position: fixed` descendants? CSS Position 3 defers the answer
 * to the specifications of the properties that do it, and this is that class, not a sample of it: every property
 * whose non-initial value makes the element a fixed box's containing block (CSS Transforms 1/2, Motion Path — the
 * offset path and its position — Filter Effects 1/2, CSS Containment 2 — layout or paint containment, which `contain`
 * and `content-visibility` apply), and `will-change` naming one of them (CSS Will Change: a property that WOULD
 * create one creates one when it is announced) — derived from the same table, never listed a second time. The two
 * hand lists it replaces (here and in the audit) named four of these and missed, among others, `will-change:
 * transform`, which this codebase's own stylesheets use and say makes a containing block (shell.css, DataGrid.css).
 *
 * MEASURED, NOT ASSUMED: `review/audit-d3-focus.mjs --containing-blocks` (every audit mode runs it first) sets each
 * literal declaration the app's stylesheets write, `will-change` naming every property Chromium knows,
 * and every property with a vocabulary of values on a real element, measures whether a fixed box inside it still
 * covers the viewport, and fails on any disagreement with this function. Its first run corrected this table three
 * ways (R-D3 follow-up, Chromium 2026-10): `container-type` does NOT make a containing block (CSS Containment 3 no
 * longer has it apply layout containment, so `PathTrace.css`'s `container-type: inline-size`, which the refuter
 * listed, is no gap); `offset-position` other than `normal`/`auto` does, and so does `will-change` naming it; and
 * `will-change: content-visibility` does not, although `content-visibility: auto | hidden` itself does.
 *
 * SELF-CONTAINED BY CONTRACT: it names nothing outside its own body, because the audit runs THIS source in the page
 * (focus-return.sight.test.ts evaluates it alone). A computed value of "" (a DOM that computes nothing) states nothing.
 */
export function containsFixedBoxes(cs: Pick<CSSStyleDeclaration, "getPropertyValue">): boolean {
  const notNone = (v: string): boolean => v !== "none";
  /* [property, the values that make the element a fixed box's containing block, whether `will-change` naming it does,
     the shorthands that set it — naming one of those names it (the census measures every shorthand Chromium has)] */
  const members: readonly (readonly [string, (v: string) => boolean, boolean, (readonly string[])?])[] = [
    ["transform", notNone, true],
    ["translate", notNone, true],
    ["rotate", notNone, true],
    ["scale", notNone, true],
    ["offset-path", notNone, true, ["offset"]],
    ["offset-position", (v) => v !== "normal" && v !== "auto", true, ["offset"]],
    ["perspective", notNone, true],
    ["transform-style", (v) => v === "preserve-3d", true],
    ["filter", notNone, true],
    ["backdrop-filter", notNone, true],
    ["contain", (v) => /(?:^|\s)(?:layout|paint|strict|content)(?:\s|$)/.test(v), true],
    ["content-visibility", (v) => v === "auto" || v === "hidden", false],
  ];
  const valueOf = (p: string): string => (cs.getPropertyValue(p) ?? "").trim();
  for (const [p, holds] of members) {
    const v = valueOf(p);
    if (v !== "" && holds(v)) return true;
  }
  /* `will-change` names a property by any name the engine accepts for it: an ALIAS too (independent verifier SD3V-6,
     MEASURED in Chromium: `will-change: -webkit-transform` contains a fixed box, and the computed value keeps the
     alias as written). Every `-webkit-` alias of a member is that member, so each named ident is read without the
     prefix, and property names are ASCII case-insensitive. A SHORTHAND that sets a member names it as well (MEASURED:
     `will-change: offset`). The census measures every name Chromium accepts — longhand, shorthand and alias. */
  const announced = valueOf("will-change")
    .split(",")
    .map((x) => x.trim().toLowerCase().replace(/^-webkit-/, ""));
  return members.some(([p, , byWillChange, shorthands = []]) => byWillChange && [p, ...shorthands].some((n) => announced.includes(n)));
}

/** The part of an element a reader can see, in viewport px, and the ancestors that clipped it (`tag.class`). */
export interface VisiblePart {
  readonly l: number;
  readonly t: number;
  readonly r: number;
  readonly b: number;
  readonly clippers: readonly string[];
}

/**
 * THE ONE WALK of "what part of `el` can the reader see": its border box, met with the viewport and with every
 * ancestor that clips it — on each axis whose computed `overflow` is not `visible` (`clip` included: no scroll can
 * undo a clip; the computed value already carries CSS's pairing rule, so `overflow-x: clip` beside a visible y clips
 * x alone) — following the containing-block chain: a fixed box escapes every ancestor that does not contain fixed
 * boxes (`containsFixedBoxes`), an absolute box every static one that does not. Null when the element has no box to
 * measure (zero area, as everything in a DOM nothing lays out): unknown, never "unseen". The owner's sight
 * (`sightOf`) is this answer, and `review/audit-d3-focus.mjs` runs this very source in the page for its "no part of it
 * is on screen (clipped by …)" verdict — one definition, not two walks that agree by hand (refuter W5-X3: the audit
 * clipped both axes where this clipped one). Self-contained apart from `containsFixedBoxes`, for the same reason.
 */
export function visiblePartOf(el: Element): VisiblePart | null {
  const box = el.getBoundingClientRect();
  if (!(box.width > 0 && box.height > 0)) return null;
  const root = document.documentElement;
  const vw = root.clientWidth > 0 ? root.clientWidth : window.innerWidth;
  const vh = root.clientHeight > 0 ? root.clientHeight : window.innerHeight;
  let l = Math.max(box.left, 0);
  let t = Math.max(box.top, 0);
  let r = Math.min(box.right, vw);
  let b = Math.min(box.bottom, vh);
  const clippers: string[] = [];
  /* "" is a value a DOM that computes nothing reports: it states no clip and no position. */
  const clips = (v: string): boolean => v !== "" && v !== "visible";
  const positioned = (p: string): boolean => p !== "" && p !== "static";
  let pos = getComputedStyle(el).position;
  for (let n = el.parentElement; n !== null && n !== document.body && n !== root; n = n.parentElement) {
    const cs = getComputedStyle(n);
    const applies = pos === "fixed" ? containsFixedBoxes(cs) : pos === "absolute" ? positioned(cs.position) || containsFixedBoxes(cs) : true;
    if (!applies) continue;
    const clipX = clips(cs.getPropertyValue("overflow-x"));
    const clipY = clips(cs.getPropertyValue("overflow-y"));
    if (clipX || clipY) {
      const nr = n.getBoundingClientRect();
      const nl = nr.left + n.clientLeft;
      const nt = nr.top + n.clientTop;
      if (clipX) {
        l = Math.max(l, nl);
        r = Math.min(r, nl + n.clientWidth);
      }
      if (clipY) {
        t = Math.max(t, nt);
        b = Math.min(b, nt + n.clientHeight);
      }
      const cls = typeof n.className === "string" ? n.className.split(" ")[0] : "";
      clippers.push(`${n.tagName.toLowerCase()}${cls ? `.${cls}` : ""}`);
    }
    pos = cs.position;
  }
  return { l, t, r, b, clippers };
}

/**
 * Can the reader see ANY part of `el`? `visiblePartOf`'s answer: "seen" when at least 1 px on each axis is left,
 * "unseen" when nothing is, "unmeasured" when there is no box — so this owner never moves focus on a guess.
 */
function sightOf(el: Element): Sight {
  const part = visiblePartOf(el);
  if (part === null) return "unmeasured";
  return part.r - part.l >= 1 && part.b - part.t >= 1 ? "seen" : "unseen";
}

/**
 * The running, FINITE animations and transitions on `el` or any ancestor: what is moving it right now. An element is
 * judged where it comes to REST, never mid-flight: MEASURED (release build, draws suspended, R-D3 render check and
 * probe), a crossing's settle look at focus fired 80 ms after the reader focused the skip link, which slides in from
 * above the viewport on `:focus-visible` (`transition: top`, shell.css); at that instant it was still at top = -56,
 * "unseen", and focus was moved to the stage — away from a control on its way into view. An infinite animation never
 * comes to rest and is not waited for. Without `getAnimations` (a DOM that animates nothing) nothing moves.
 */
function movingNow(el: Element): Animation[] {
  const out: Animation[] = [];
  for (let n: Element | null = el; n !== null; n = n.parentElement) {
    const get = (n as Element & { getAnimations?: () => Animation[] }).getAnimations;
    if (typeof get !== "function") continue;
    for (const x of get.call(n)) {
      if (x.playState !== "running") continue;
      const end = x.effect?.getComputedTiming().endTime;
      if (typeof end === "number" && Number.isFinite(end)) out.push(x);
    }
  }
  return out;
}

/** If `el` is moving, run `again` once everything moving it has finished (or been cancelled) — while `el` still holds
 *  focus — and report true: the caller judges nothing now. */
function judgeAtRest(el: HTMLElement, again: () => void): boolean {
  const moving = movingNow(el);
  if (moving.length === 0) return false;
  void Promise.all(moving.map((x) => x.finished.catch(() => undefined))).then(() => {
    if (document.activeElement === el) again();
  });
  return true;
}

/**
 * The FOURTH DOOR's last step, for an element the layout did NOT take away but left where no part of it can be seen
 * (acceptance D3; independent verifier QH-V2-2). A rung crossing re-flows every region, and the frame scrolls the
 * focused element into view — but a scroll cannot reveal what a CLIP hides: MEASURED (release build, 768 -> 390 px)
 * the Inspector's "Copy the citation path" sat right of the viewport under `.app`'s `overflow-x: clip`, still
 * rendered, still connected, still focused, "no part of it on screen". Call this AFTER the new layout has settled and
 * focus has been scrolled into view. If the element holding focus has a box and no visible part, focus goes to the
 * nearest place the reader can see — judged where it comes to REST (`movingNow`: an element mid-transition is judged
 * once the transition ends, if it still holds focus then) — in order:
 *   a. the named regions around it, nearest first, each as its labelling heading and then as itself (rule 4), each
 *      accepted only if it is SEEN once focused (focusing scrolls it into view);
 *   b. the caller's fallbacks, landed as the fourth door lands them, each accepted only if seen;
 * and if nothing is seen, focus goes back to where it was — never <body>. Returns the element that now holds focus
 * when it moved, else null (focus was seen, unmeasured, or had nowhere better to go).
 */
export function releaseFocusLeftUnseen(fallbacks: readonly Candidate[] = []): HTMLElement | null {
  if (typeof document === "undefined") return null;
  const a = document.activeElement;
  if (!(a instanceof HTMLElement) || a === document.body || a === document.documentElement || !a.isConnected) return null;
  if (judgeAtRest(a, () => void releaseFocusLeftUnseen(fallbacks))) return null;
  if (sightOf(a) !== "unseen") return null;
  const tried = new Set<HTMLElement>();
  const seenOnce = (landed: HTMLElement | null): landed is HTMLElement => landed !== null && document.activeElement === landed && sightOf(landed) === "seen";
  for (const n of namedRegionsAround(a)) {
    for (const m of placesOf(n)) {
      if (tried.has(m) || m === a) continue;
      tried.add(m);
      if (focusLandmark(m) && seenOnce(m)) return m;
    }
  }
  for (const c of fallbacks) {
    if (!(c instanceof HTMLElement) || tried.has(c) || c === a) continue;
    tried.add(c);
    const landed = landOn(c);
    if (landed !== a && seenOnce(landed)) return landed;
  }
  /* Nowhere better: back where it was (a landmark tried above gives up its temporary tabindex on blur). */
  if (document.activeElement !== a) tryFocus(a);
  return null;
}

/**
 * "Focus is always seen" after ANY resize, not only one that crosses a rung (independent verifier V1-4: an injected
 * offset inside the stacked rung, 700 -> 390 px, left the focused control wholly off screen and nothing ran). If the
 * element holding focus has a box and no visible part: first scroll it into view (a scroller CAN reveal what it has
 * scrolled away; centred, as the frame's crossing does, so a sticky bar does not cover it), and only if that did not
 * reveal it, `releaseFocusLeftUnseen` (a clip cannot be scrolled). A seen or unmeasured element is not touched — no
 * scroll moves content under a reader whose focus is already in view. Returns the element focus moved to, else null.
 */
export function keepFocusSeen(fallbacks: readonly Candidate[] = []): HTMLElement | null {
  if (typeof document === "undefined") return null;
  const a = document.activeElement;
  if (!(a instanceof HTMLElement) || a === document.body || a === document.documentElement || !a.isConnected) return null;
  if (judgeAtRest(a, () => void keepFocusSeen(fallbacks))) return null;
  if (sightOf(a) !== "unseen") return null;
  a.scrollIntoView?.({ block: "center", inline: "nearest" });
  return releaseFocusLeftUnseen(fallbacks);
}

/**
 * The FOURTH DOOR (see the module comment): a layout change has just been committed. If it took the
 * focused element away — removed it, or left it unrendered — hand focus to its successor, in order:
 *   a. its TWIN: a rendered control with the same role and the same accessible name, preferring one
 *      inside the nearest ancestor that survived (the header's inline "Copy the link…" for the same
 *      button inside the More popover that just unmounted);
 *   b. the successor the lost element, or its nearest recorded ancestor that states one, names in
 *      `data-focus-successor` (FOCUS_SUCCESSOR_ATTR), each selector in order;
 *   c. the caller's fallbacks, in order;
 *   d. the region landmark around the nearest surviving ancestor, then that ancestor's first tab stop.
 * It acts ONLY when the element that last took focus is gone from the rendered page AND focus is
 * nowhere real (on <body>, or still on that unrendered element): focus the crossing did not take stays
 * exactly where it is, and so does a <body> the reader chose with a pointer press on nothing. Returns
 * the element that now holds focus, or null when there was nothing to do (or nowhere to go).
 */
export function releaseFocusAfterLayoutChange(fallbacks: readonly Candidate[] = []): HTMLElement | null {
  if (typeof document === "undefined") return null;
  const t = trail;
  if (t === null) return null;
  const a = document.activeElement;
  const nowhere = a === null || a === document.body || a === document.documentElement;
  if (!nowhere && a !== t.el) return null;
  if (a === t.el && isRendered(t.el) && takesFocus(t.el)) return null;
  if (nowhere && isRendered(t.el)) return null;

  const scope = t.ancestors.find((n) => isRendered(n)) ?? null;

  const name = nameOf(t.el);
  if (name !== "") {
    const role = roleOf(t.el);
    const twins = [...document.querySelectorAll<HTMLElement>(TAB_STOP_SELECTOR)].filter(
      (c) => c !== t.el && roleOf(c) === role && nameOf(c) === name,
    );
    const inScope = scope === null ? [] : twins.filter((c) => scope.contains(c));
    for (const c of [...inScope, ...twins.filter((c) => !inScope.includes(c))]) {
      if (isRendered(c) && takesFocus(c) && tryFocus(c)) return c;
    }
  }

  for (const n of [t.el, ...t.ancestors]) {
    const spec = n.getAttribute(FOCUS_SUCCESSOR_ATTR);
    if (spec === null) continue;
    for (const sel of spec.split(",").map((s) => s.trim()).filter((s) => s !== "")) {
      let matches: HTMLElement[] = [];
      try {
        matches = [...document.querySelectorAll<HTMLElement>(sel)];
      } catch {
        continue; /* a malformed successor names nothing; the next one is tried */
      }
      for (const m of matches) {
        const landed = landOn(m);
        if (landed !== null) return landed;
      }
    }
  }

  for (const c of fallbacks) {
    const landed = landOn(c);
    if (landed !== null) return landed;
  }

  if (scope !== null) {
    const mark = scope.matches(REGION_SELECTOR) && isNamed(scope) ? scope : landmarkOf(scope);
    if (mark !== null && isRendered(mark) && focusLandmark(mark)) return mark;
    return landOn(scope);
  }
  return null;
}

/** Fallbacks the declared layout changes of the current commit asked for; null when none is pending. */
let pendingRelease: Candidate[] | null = null;

/**
 * Run the fourth door ONCE for the commit being laid out, AFTER every layout effect of that commit —
 * a microtask queued from the layout phase runs when the commit's synchronous work is done and before
 * the browser renders (and so before its own focus fix-up). Why not in the effect itself: a commit
 * that crosses a rung also hides containers whose THIRD door knows more (Rail B knows the control that
 * opened the drawer), and React runs an earlier sibling's layout effects first. MEASURED
 * (drawer-focus-return.test.tsx, 1100 -> 900 with focus in the drawer): the header's door ran before
 * Rail B's and sent focus to the first tab stop of the body, the pane switch's "Queue", instead of the
 * drawer's opener. Deferred, the third door acts first and this one finds focus somewhere real. Every
 * caller's fallbacks in the commit are kept, in call order.
 */
function scheduleLayoutRelease(fallbacks: readonly Candidate[]): void {
  if (pendingRelease !== null) {
    pendingRelease.push(...fallbacks);
    return;
  }
  pendingRelease = [...fallbacks];
  queueMicrotask(() => {
    const all = pendingRelease ?? [];
    pendingRelease = null;
    releaseFocusAfterLayoutChange(all);
  });
}

/**
 * The fourth door as a React hook, for the component whose LAYOUT decides what is rendered: `layout`
 * is the value that decision is keyed on (a rung, a fold, a visibility flag). On every commit that
 * changes it, `releaseFocusAfterLayoutChange` runs once that commit's layout effects are done — after
 * React has removed what the change removed, after any container's own third door, and before the
 * browser paints or runs its own focus fix-up (which parks focus on <body> for an element left
 * unrendered). `fallbacks` is read in the commit's layout phase. While any user of the hook is
 * mounted, the owner follows focus (`focusin`), so it knows what held focus BEFORE the commit even
 * when that element has since been removed.
 */
export function useReleaseFocusOnLayoutChange(layout: unknown, fallbacks: () => readonly Candidate[] = NO_FALLBACKS): void {
  const was = useRef(layout);
  const latestFallbacks = useRef(fallbacks);
  latestFallbacks.current = fallbacks;
  /* Announce, while rendering, that this commit changes the layout (a render-phase write: idempotent,
     so a double render adds the same token once). Withdrawn in this commit's layout phase, below. */
  const token = useRef<object>({});
  if (!Object.is(was.current, layout)) layoutChanging.add(token.current);
  useLayoutEffect(() => {
    layoutChanging.delete(token.current);
  });
  useLayoutEffect(() => () => void layoutChanging.delete(token.current), []);
  useLayoutEffect(() => followFocus(), []);
  useLayoutEffect(() => {
    if (Object.is(was.current, layout)) return;
    was.current = layout;
    scheduleLayoutRelease(latestFallbacks.current());
  }, [layout]);
}
