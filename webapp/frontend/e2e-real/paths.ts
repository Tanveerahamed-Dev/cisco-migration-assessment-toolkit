import os from "node:os";
import path from "node:path";

// The one owner of the real-backend tier's port and scratch locations. playwright.real.config.ts
// hands every path below to the launcher (serve_real_backend.py), and the spec reads back the
// synthetic archive and its manifest from the same paths, so no name is spelled twice.
//
// E2E_REAL_PORT and E2E_REAL_ROOT override the defaults (CI points the root at runner.temp). The
// port stays clear of the mocked tier (41973), the visual tier (43973) and the OS ephemeral range.
export const REAL_PORT = process.env.E2E_REAL_PORT || "42973";
if (!/^[1-9][0-9]{3,4}$/.test(REAL_PORT) || Number(REAL_PORT) > 65535) {
  throw new Error(`E2E_REAL_PORT must be a TCP port number, got ${JSON.stringify(REAL_PORT)}`);
}
export const REAL_ORIGIN = `http://127.0.0.1:${REAL_PORT}`;

export const REAL_ROOT = path.resolve(
  process.env.E2E_REAL_ROOT || path.join(os.tmpdir(), `assesshub-real-e2e-${REAL_PORT}`),
);
// Every path below is quoted into the webServer shell command; refuse what quoting cannot carry.
if (/["\r\n]/.test(REAL_ROOT)) {
  throw new Error("E2E_REAL_ROOT must not contain a double quote or a line break");
}
/** Fresh `vite build` output for this run; never the tracked webapp/frontend/dist. */
export const REAL_SPA_DIR = path.join(REAL_ROOT, "spa");
/** Launcher-owned: recreated on every start (fresh SQLite store + the synthetic archive). */
export const REAL_RUN_DIR = path.join(REAL_ROOT, "run");
export const SYNTHETIC_COLLECTION_ZIP = path.join(REAL_RUN_DIR, "synthetic-collection.zip");
export const SYNTHETIC_COLLECTION_MANIFEST = path.join(REAL_RUN_DIR, "synthetic-collection.json");
