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
 * Both are feature-detected: a jsdom render without them runs `fn` synchronously, so a component
 * using this stays testable without a browser. Returns a cancel function.
 */
export function deferPastPaint(fn: () => void): () => void {
  if (typeof requestAnimationFrame !== "function" || typeof setTimeout !== "function") {
    fn();
    return () => undefined;
  }
  let timer: ReturnType<typeof setTimeout> | null = null;
  let cancelled = false;
  const frame = requestAnimationFrame(() => {
    if (cancelled) return;
    timer = setTimeout(() => {
      if (!cancelled) fn();
    }, 0);
  });
  return () => {
    cancelled = true;
    if (typeof cancelAnimationFrame === "function") cancelAnimationFrame(frame);
    if (timer !== null) clearTimeout(timer);
  };
}

