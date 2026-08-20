import { readFileSync } from "node:fs";
import { createServer, type Server } from "node:http";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

const EXPLORER_PATH = fileURLToPath(
  new URL("../../../cisco_toolkit/blast_radius_explorer.html", import.meta.url),
);
const CANONICAL_MODE_COUNT = 14;

let server: Server;
let explorerUrl: string;

test.describe("Offline blast-radius explorer (real browser)", () => {
  test.beforeAll(async () => {
    const explorer = readFileSync(EXPLORER_PATH);

    // Use an ephemeral loopback-only origin. This preserves normal browser-origin behavior
    // (notably localStorage) without making the self-contained explorer network-accessible.
    server = createServer((request, response) => {
      const pathname = new URL(request.url ?? "/", "http://127.0.0.1").pathname;
      if (pathname === "/favicon.ico") {
        response.writeHead(204).end();
        return;
      }
      if ((request.method !== "GET" && request.method !== "HEAD") || pathname !== "/explorer.html") {
        response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" }).end("Not found");
        return;
      }

      response.writeHead(200, {
        "Cache-Control": "no-store",
        "Content-Length": explorer.byteLength,
        "Content-Type": "text/html; charset=utf-8",
        "X-Content-Type-Options": "nosniff",
      });
      response.end(request.method === "HEAD" ? undefined : explorer);
    });

    await new Promise<void>((resolve, reject) => {
      server.once("error", reject);
      server.listen(0, "127.0.0.1", resolve);
    });

    const address = server.address();
    if (!address || typeof address === "string") throw new Error("Explorer smoke server did not bind a TCP port");
    explorerUrl = `http://127.0.0.1:${address.port}/explorer.html`;
  });

  test.afterAll(async () => {
    if (!server) return;
    await new Promise<void>((resolve, reject) => {
      server.close((error) => (error ? reject(error) : resolve()));
    });
  });

  test("boots cleanly and renders every registered mode", async ({ page }) => {
    const pageErrors: string[] = [];
    const consoleErrors: string[] = [];
    const externalRequests: string[] = [];

    page.on("pageerror", (error) => pageErrors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (url.protocol !== "data:" && url.protocol !== "blob:" && url.origin !== new URL(explorerUrl).origin) {
        externalRequests.push(request.url());
      }
    });

    await page.addInitScript(() => {
      try {
        localStorage.setItem("nme-coach-seen", "1");
      } catch {
        // The target loopback origin supports storage; tolerate the initial opaque about:blank document.
      }
    });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto(explorerUrl);

    await expect(page).toHaveTitle("Network Migration Explorer");
    await expect(page.locator("#src")).toHaveText("DEMO TOPOLOGY");

    // Exercise the live registry rather than maintaining a second list of mode names in this test.
    const registryModes = (await page.evaluate("MODES.map(({ key }) => key)")) as string[];
    const toolbarModes = await page.locator("#modes button[data-mode]").evaluateAll((buttons) =>
      buttons.map((button) => (button as HTMLButtonElement).dataset.mode ?? ""),
    );

    expect(registryModes).toHaveLength(CANONICAL_MODE_COUNT);
    expect(new Set(registryModes).size).toBe(registryModes.length);
    expect(toolbarModes).toEqual(registryModes);

    for (const mode of registryModes) {
      await test.step(`${mode} mode activates and renders`, async () => {
        const button = page.locator(`#modes button[data-mode="${mode}"]`);
        await button.click();

        await expect(button).toHaveClass(/\bon\b/);
        await expect(button).toHaveAttribute("aria-pressed", "true");
        await expect(page.locator("#modes button.on")).toHaveCount(1);
        await expect(page.locator('#modes button[aria-pressed="true"]')).toHaveCount(1);
        await expect(page.locator("#modetag")).toContainText(/\S/);
        await expect(page.locator("#hint")).toContainText(/\S/);
        await expect(page.locator("#legend h4")).toHaveText(`Legend — ${mode}`);
        await expect(page.locator("#panel")).toContainText(/\S/);
        await expect.poll(() => new URL(page.url()).hash).toContain(`mode=${mode}`);

        if (mode === "3d") {
          const canvas = page.locator("#g3d");
          await expect(page.locator("#stage")).toHaveClass(/\bmode3d\b/);
          await expect(canvas).toBeVisible();
          const bitmap = await canvas.evaluate((element: HTMLCanvasElement) => ({
            height: element.height,
            width: element.width,
          }));
          expect(bitmap.width).toBeGreaterThan(0);
          expect(bitmap.height).toBeGreaterThan(0);
        } else {
          await expect(page.locator("#stage")).not.toHaveClass(/\bmode3d\b/);
          await expect(page.locator("#g3d")).toBeHidden();
          await expect(page.locator("#svg")).toBeVisible();
          await expect(page.locator("#svg #vp")).toBeAttached();
          await expect.poll(() => page.locator("#svg #vp").evaluate((element) => element.childElementCount)).toBeGreaterThan(0);
        }

        // Let mode-specific requestAnimationFrame work run so async render failures reach pageerror.
        await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
      });
    }

    expect(pageErrors, `unexpected page errors:\n${pageErrors.join("\n")}`).toEqual([]);
    expect(consoleErrors, `unexpected console errors:\n${consoleErrors.join("\n")}`).toEqual([]);
    expect(externalRequests, `explorer attempted external requests:\n${externalRequests.join("\n")}`).toEqual([]);
  });
});
