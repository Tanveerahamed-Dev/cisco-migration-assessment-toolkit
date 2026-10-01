import { StrictMode, startTransition } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";

/**
 * The application half of the entry. `main.tsx` imports this module DYNAMICALLY, after the boot line
 * in index.html has had a rendering opportunity — see the note there for why the split exists.
 *
 * The first render is a TRANSITION, so React renders it in 5 ms slices and yields to input between
 * them instead of rendering four populated surfaces as one task. Acceptance E5: keystrokes fired
 * during the cold load were measured at 272-336 ms while this render ran unsliced. The boot line in
 * index.html (role="status", aria-busy) stays on screen until the commit replaces it, so the wait
 * is communicated either way; this only stops it from also being a frozen wait.
 */
export function mount(el: HTMLElement): void {
  const root = createRoot(el);
  startTransition(() => {
    root.render(
      <StrictMode>
        <App />
      </StrictMode>,
    );
  });
}
