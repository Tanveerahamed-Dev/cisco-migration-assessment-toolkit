/* Design-sync preview support for AssessHub.
 *
 * DemoDataProvider — the wrapper every AssessHub snapshot widget needs outside the real app:
 * it serves SYNTHETIC sample fleet data for the /api endpoints the widgets fetch (the payloads
 * live in ./sample-data.ts; entirely fictional hosts and doc-range IPs), and provides the
 * Router context CutoverPlanner's links/navigation need. Wrap once at the top of a design.
 * (The widgets themselves are exported from webapp/frontend/ds.entry.ts — the bundle entry.)
 */
import { type ReactNode } from "react";
import { MemoryRouter, useInRouterContext } from "react-router";
import { DEMO_ROUTES } from "./sample-data";

let patched = false;
function patchFetch() {
  if (patched || typeof window === "undefined") return;
  patched = true;
  const real = window.fetch.bind(window);
  window.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    const url =
      typeof input === "string" ? input : input instanceof URL ? input.href : (input as Request).url;
    const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
    for (const [rx, payload] of DEMO_ROUTES) {
      if (rx.test(path)) {
        return Promise.resolve(
          new Response(JSON.stringify(payload), {
            status: 200,
            headers: { "content-type": "application/json" },
          }),
        );
      }
    }
    return real(input as RequestInfo, init);
  }) as typeof window.fetch;
}

/** Wrap AssessHub snapshot widgets (TopologyGraph, CableMap, CausalFlowPanel, CutoverPlanner,
 *  DesignBlueprintPanel, ArchReviewPanel) in this provider so they render with built-in sample
 *  data instead of spinning on a backend that isn't there. Any `snapId` works — every id maps to
 *  the same demo fleet. Non-/api fetches pass through untouched. */
export function DemoDataProvider({ children }: { children: ReactNode }) {
  // Patch during render, not in an effect: children's effects (where the widgets fetch) run
  // before a parent's effect would, so an effect here would be too late on first mount.
  patchFetch();
  // Nesting-safe: a second DemoDataProvider inside an existing Router context (e.g. the preview
  // harness already wraps every card in one) must not mount a second MemoryRouter — react-router
  // throws on nested routers. The fetch patch is idempotent, so the inner wrap degrades to a no-op.
  const inRouter = useInRouterContext();
  return inRouter ? <>{children}</> : <MemoryRouter>{children}</MemoryRouter>;
}
