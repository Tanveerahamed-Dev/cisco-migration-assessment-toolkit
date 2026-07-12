// Vitest global setup: register @testing-library/jest-dom's matchers on Vitest's expect
// (toBeInTheDocument, toHaveTextContent, …) and auto-clean the DOM between tests.
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// jsdom does not implement matchMedia; components that read `prefers-reduced-motion` (CountUp / Gauge
// via useReducedMotion) call it during render and would throw. Polyfill a stable "no reduction" query
// (the animated path — what a normal browser reports), so those components render under test.
if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = (query: string): MediaQueryList => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  });
}

afterEach(() => {
  cleanup();
});
