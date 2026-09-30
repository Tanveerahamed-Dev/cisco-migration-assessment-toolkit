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
 *      focusable (`tabindex=-1`, never a Tab stop) for as long as it holds focus.
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
 * focus, for as long as the container's closing transition runs), and so is every candidate inside a
 * `hidden` subtree. `src/app/drawer-focus-return.test.tsx` drives the drawer's three close paths, a
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
  return { target: from, opener: openerOf(from), region: landmarkOf(from) };
}

const takesFocus = (el: HTMLElement): boolean =>
  el.isConnected &&
  el !== document.body &&
  el.closest("[inert]") === null &&
  el.closest("[aria-hidden='true']") === null &&
  !(el as HTMLButtonElement).disabled;

/** Focus `el` and report whether it actually took focus. */
function tryFocus(el: Candidate): boolean {
  if (!el || !takesFocus(el)) return false;
  el.focus({ preventScroll: false });
  return document.activeElement === el;
}

/** The labelled region around `from` (or its labelling heading), excluding `from` itself. */
function landmarkOf(from: Element | null | undefined): HTMLElement | null {
  let n = from?.parentElement?.closest<HTMLElement>(REGION_SELECTOR) ?? null;
  while (n !== null && !isNamed(n)) n = n.parentElement?.closest<HTMLElement>(REGION_SELECTOR) ?? null;
  return n === null ? null : statedRegion(n);
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
 * next choices. Order: the target, its opener, the fallbacks, the landmark around `context`, and
 * last the landmark the target sat in when it was recorded (`ReturnRecord.region`). Returns the
 * element that now holds focus, or null when focus was left in place.
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
  const mark = landmarkOf(context);
  if (mark !== null && focusLandmark(mark)) return mark;
  const region = record instanceof HTMLElement ? null : (record?.region ?? null);
  if (region !== null && region !== mark) {
    /* The region's first heading that can take focus names the same place and is small enough for
       its ring to be seen whole; a ring round a tall, rail-clipped region measured under half its
       perimeter (focus-return.region.test.ts). Headings in a hidden sub-pane refuse focus and are
       passed over; the region itself is the last resort. */
    if (!/^H[1-6]$/.test(region.tagName)) {
      for (const h of region.querySelectorAll<HTMLElement>("h1, h2, h3, h4, h5, h6")) if (focusLandmark(h)) return h;
    }
    if (focusLandmark(region)) return region;
  }
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
  const usable = (el: Candidate): el is HTMLElement =>
    el instanceof HTMLElement && !container.contains(el) && el.closest("[hidden]") === null;
  const attempt = (el: Candidate): boolean => usable(el) && tryFocus(el);

  const target = record instanceof HTMLElement ? record : (record?.target ?? null);
  const opener = record instanceof HTMLElement ? null : (record?.opener ?? null);
  for (const c of [target, opener, ...fallbacks]) if (attempt(c)) return c as HTMLElement;

  const mark = landmarkOf(container);
  if (usable(mark) && focusLandmark(mark)) return mark;
  const region = record instanceof HTMLElement ? null : (record?.region ?? null);
  if (usable(region) && region !== mark && focusLandmark(region)) return region;

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
  /** The region landmark around the control (rule 4). */
  readonly landmark: HTMLElement | null;
  /** Every named region landmark further out, nearest first: where rule 4 goes when the nearest one was hidden. */
  readonly outer: readonly HTMLElement[];
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
  /* Every named region around the control, nearest first, each as landmarkOf states it (its labelling heading, else
     itself); the nearest is rule 4's landmark, the rest are `outer`. Walked by REGION, not by the stated element, so a
     region labelled by a heading inside it does not stop the walk at that heading. */
  const around: HTMLElement[] = [];
  for (let n = control.parentElement?.closest<HTMLElement>(REGION_SELECTOR) ?? null; n !== null; n = n.parentElement?.closest<HTMLElement>(REGION_SELECTOR) ?? null) {
    if (isNamed(n)) around.push(statedRegion(n));
  }
  const landmark = landmarkOf(control);
  const outer = around.filter((m) => m !== landmark);
  return {
    siblings: [...after, ...before],
    label: labelEl instanceof HTMLElement && set !== null && !set.contains(labelEl) ? labelEl : null,
    landmark,
    outer,
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
       SHOWN landmark further out is where focus goes (the Evidence rail around both panes) — never <body>. */
    const shown = (el: Candidate): boolean => el instanceof HTMLElement && el.closest("[hidden]") === null;
    for (const c of plan.siblings) if (shown(c) && tryFocus(c)) return;
    for (const s of stated) {
      const c = typeof s === "function" ? s() : s;
      if (shown(c) && tryFocus(c)) return;
    }
    if (plan.label !== null && shown(plan.label) && focusLandmark(plan.label)) return;
    for (const m of plan.landmark === null ? [] : [plan.landmark, ...plan.outer]) if (shown(m) && focusLandmark(m)) return;
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
