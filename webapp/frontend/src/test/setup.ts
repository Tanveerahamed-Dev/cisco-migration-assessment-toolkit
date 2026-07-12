// Vitest global setup: register @testing-library/jest-dom's matchers on Vitest's expect
// (toBeInTheDocument, toHaveTextContent, …) and auto-clean the DOM between tests.
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
});
