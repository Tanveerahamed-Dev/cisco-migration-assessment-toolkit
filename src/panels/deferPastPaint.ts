/**
 * Run `fn` in a task of its own AFTER the next frame has been painted — design brief 8.3 rule 3.
 *
 * A store write in this app re-aims four surfaces at once, and a `useSyncExternalStore` update is
 * urgent: React renders and commits every subscriber in the task that made the write, and
 * `startTransition` cannot slice it. So an interaction that must feel instant commits its OWN
 * acknowledgement from local state first and hands the cross-surface write to this.
 *
 *   - `requestAnimationFrame` puts the write after the acknowledgement frame's rendering steps;
 *   - the `setTimeout` inside it puts the write in a task of its own rather than inside the frame
 *     callback, where it would extend that same animation frame and defeat the split.
 *
 * `frames` (default 1) is how many animation frames to wait out before that task is queued. One is
 * "after the acknowledgement frame's rendering steps", which is not yet "after it is on screen": a
 * task queued from inside that frame's callback runs as soon as the main thread has painted, and the
 * compositor may still be presenting the frame — so the task can begin inside the interaction's own
 * Event Timing window. A caller whose deferred commit is itself long (the canvas's cross-surface
 * selection, Fabric3D.tsx) waits out two: the second frame callback only runs once the first frame
 * has been handed on.
 *
 * Both are feature-detected: a jsdom render without them runs `fn` synchronously, so a component
 * using this stays testable without a browser. Returns a cancel function.
 */
export function deferPastPaint(fn: () => void, frames = 1): () => void {
  if (typeof requestAnimationFrame !== "function" || typeof setTimeout !== "function") {
    fn();
    return () => undefined;
  }
  let timer: ReturnType<typeof setTimeout> | null = null;
  let cancelled = false;
  let frame = 0;
  const waitFrames = (left: number): void => {
    frame = requestAnimationFrame(() => {
      if (cancelled) return;
      if (left > 1) {
        waitFrames(left - 1);
        return;
      }
      timer = setTimeout(() => {
        if (!cancelled) fn();
      }, 0);
    });
  };
  waitFrames(Math.max(1, Math.floor(frames)));
  return () => {
    cancelled = true;
    if (typeof cancelAnimationFrame === "function") cancelAnimationFrame(frame);
    if (timer !== null) clearTimeout(timer);
  };
}

/**
 * Frames to wait, when Event Timing is available but reports nothing for the interaction: an
 * interaction presented in under 16 ms is below the smallest threshold an observer may ask for, and
 * a lost entry must not leave the commit waiting for ever. About 100 ms at 60 Hz.
 */
export const PRESENTATION_FALLBACK_FRAMES = 6;

/**
 * Run `fn` in a task of its own once the browser reports that the interaction started by an
 * `eventName` event on `target` — the one being handled now — has been PRESENTED.
 *
 * `deferPastPaint` waits for frames, and a frame count is a guess about the GPU: MEASURED on this
 * project's reference machine (Intel iGPU, ANGLE D3D11), a canvas click was presented 56-80 ms after
 * it happened, three to four frames on, so a commit two frames later still landed inside the click's
 * own Event Timing window (Fabric3D.tsx, acceptance E3). The browser's statement that an interaction
 * has been presented is its Event Timing entry, which is delivered only after the frame that
 * presents it; this waits for exactly that entry and then runs `fn` in the next task, never inside
 * the observer callback. The entry is recognised by its name and its target: the observer is created
 * while the event is being handled and asks for no buffered history, so the first such entry it is
 * handed is this event's (an entry is dispatched only after the frame that presents its event). No
 * clock is read to identify it.
 *
 * Fallbacks, so the commit always happens exactly once: without Event Timing, `deferPastPaint(fn, 2)`
 * (the old behaviour); with it, after PRESENTATION_FALLBACK_FRAMES frames if no entry has come.
 * Without requestAnimationFrame (jsdom) `fn` runs synchronously, as `deferPastPaint` does. Returns a
 * cancel function that stops every path.
 */
export function deferPastPresentation(eventName: string, target: EventTarget | null, fn: () => void): () => void {
  let done = false;
  let observer: PerformanceObserver | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let cancelFallback: () => void = () => undefined;
  const finish = (): void => {
    done = true;
    observer?.disconnect();
    observer = null;
    cancelFallback();
    if (timer !== null) clearTimeout(timer);
  };
  const run = (): void => {
    if (done) return;
    finish();
    fn();
  };
  try {
    const PO = typeof PerformanceObserver === "undefined" ? undefined : PerformanceObserver;
    if (PO !== undefined && Array.isArray(PO.supportedEntryTypes) && PO.supportedEntryTypes.includes("event") && typeof setTimeout === "function") {
      observer = new PO((list) => {
        if (done) return;
        for (const e of list.getEntries()) {
          if (e.name !== eventName || (e as PerformanceEntry & { target?: EventTarget | null }).target !== target) continue;
          observer?.disconnect();
          observer = null;
          timer = setTimeout(run, 0);
          return;
        }
      });
      /* 16 ms is the smallest threshold the Event Timing API accepts. */
      observer.observe({ type: "event", durationThreshold: 16 } as PerformanceObserverInit);
    }
  } catch {
    observer = null;
  }
  cancelFallback = deferPastPaint(run, observer === null ? 2 : PRESENTATION_FALLBACK_FRAMES);
  return () => {
    if (!done) finish();
  };
}
