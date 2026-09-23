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
 * `src/app/focus-return.guard.test.ts` parses every source
 * file and fails on a `.blur()` call anywhere but here, and on an `isConnected` focus branch whose
 * else-arm does not call this module.
 */

/** Where focus should go back to, and — captured while it still exists — what opened its surface. */
export interface ReturnRecord {
  readonly target: HTMLElement;
  readonly opener: HTMLElement | null;
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

/** The element whose `aria-controls` names `el` or one of its ancestors: the surface's opener. */
function openerOf(el: HTMLElement): HTMLElement | null {
  if (typeof document === "undefined") return null;
  const controllers = [...document.querySelectorAll<HTMLElement>("[aria-controls]")];
  if (controllers.length === 0) return null;
  for (let n: HTMLElement | null = el; n !== null; n = n.parentElement) {
    const id = n.id;
    if (id === "") continue;
    const hit = controllers.find(
      (c) => !n!.contains(c) && (c.getAttribute("aria-controls") ?? "").split(/\s+/).includes(id),
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
  return { target: from, opener: openerOf(from) };
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
  if (n === null) return null;
  const by = (n.getAttribute("aria-labelledby") ?? "").split(/\s+/).find((id) => id !== "");
  const heading = by === undefined ? null : document.getElementById(by);
  return heading instanceof HTMLElement && n.contains(heading) ? heading : n;
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
 * next choices. Returns the element that now holds focus, or null when focus was left in place.
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
  return null;
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
  const by = (set?.getAttribute("aria-labelledby") ?? "").split(/\s+/).find((id) => id !== "");
  const labelEl = by === undefined ? null : document.getElementById(by);
  return {
    siblings: [...after, ...before],
    label: labelEl instanceof HTMLElement && set !== null && !set.contains(labelEl) ? labelEl : null,
    landmark: landmarkOf(control),
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
    for (const c of plan.siblings) if (tryFocus(c)) return;
    for (const s of stated) if (tryFocus(typeof s === "function" ? s() : s)) return;
    if (plan.label !== null && focusLandmark(plan.label)) return;
    if (plan.landmark !== null) focusLandmark(plan.landmark);
  };
  queueMicrotask(attempt);
  if (typeof setTimeout === "function") for (const ms of HANDOFF_DELAYS_MS) setTimeout(attempt, ms);
}
