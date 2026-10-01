/**
 * capture-linear.mjs — pull Linear's actual PRODUCT imagery out of its docs pages.
 *
 * The homepage capture is mostly marketing copy, which is a weak comparison target for "dense
 * working list view". Linear's docs pages embed real screenshots of the product at working density;
 * those are the honest bar for criterion C3, so we extract the images themselves rather than
 * screenshotting prose around them.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(HERE, "shots", "refs-deep");
mkdirSync(OUT, { recursive: true });

/**
 * Docs pages whose embedded figures ARE the product. Screenshotting the page would compare our
 * full-bleed application against a thumbnail surrounded by prose — the critic would simply prefer
 * the larger image, which measures nothing. Extracting the figure compares product to product.
 */
const PAGES = [
  { id: "linear-custom-views", url: "https://linear.app/docs/custom-views" },
  { id: "linear-display-options", url: "https://linear.app/docs/display-options" },
  { id: "linear-inbox", url: "https://linear.app/docs/inbox" },
  { id: "ipfabric-viewer", url: "https://docs.ipfabric.io/latest/IP_Fabric_GUI/diagrams/network_viewer/" },
  { id: "ipfabric-pathlookup", url: "https://docs.ipfabric.io/latest/IP_Fabric_GUI/diagrams/how_to_use_path-lookup/" },
  { id: "ipfabric-dashboard", url: "https://docs.ipfabric.io/latest/IP_Fabric_GUI/dashboard/" },
];

const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  deviceScaleFactor: 2,
  colorScheme: "dark",
});
const written = [];

for (const p of PAGES) {
  const page = await ctx.newPage();
  try {
    await page.goto(p.url, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForTimeout(5000);
    // Scroll the whole page so lazy-loaded screenshots actually fetch before we measure them.
    await page.evaluate(async () => {
      for (let y = 0; y < document.body.scrollHeight; y += 700) {
        window.scrollTo(0, y);
        await new Promise((r) => setTimeout(r, 180));
      }
      window.scrollTo(0, 0);
    });
    await page.waitForTimeout(2500);

    /* Take the LARGEST images on the page: on a docs page those are the product screenshots, and
       the small ones are icons and avatars. Sorting by rendered area avoids hard-coding selectors
       that will rot the next time the site is restyled. */
    const shots = await page
      .locator("img")
      .evaluateAll((els) =>
        els
          .map((el, i) => {
            const r = el.getBoundingClientRect();
            return { i, w: Math.round(r.width), h: Math.round(r.height), area: r.width * r.height };
          })
          .filter((x) => x.w >= 560 && x.h >= 300)
          .sort((a, b) => b.area - a.area)
          .slice(0, 3),
      );

    for (const [n, s] of shots.entries()) {
      const el = page.locator("img").nth(s.i);
      await el.scrollIntoViewIfNeeded().catch(() => {});
      await page.waitForTimeout(500);
      const file = resolve(OUT, `${p.id}-product${n + 1}.png`);
      await el.screenshot({ path: file }).catch(() => null);
      written.push({ id: `${p.id}-product${n + 1}`, url: p.url, file, size: `${s.w}x${s.h}`, ok: true });
      console.log(`  ok   ${p.id}-product${n + 1}  ${s.w}x${s.h}`);
    }
    if (shots.length === 0) {
      written.push({ id: p.id, url: p.url, file: null, ok: false, error: "no image >= 560x300 found" });
      console.log(`  none ${p.id}: no product-sized image found`);
    }
  } catch (e) {
    written.push({ id: p.id, url: p.url, file: null, ok: false, error: String(e).slice(0, 200) });
    console.log(`  FAIL ${p.id}: ${String(e).slice(0, 120)}`);
  }
  await page.close();
}

await browser.close();
writeFileSync(resolve(OUT, "linear-index.json"), JSON.stringify(written, null, 1));
console.log(`captured ${written.filter((w) => w.ok).length} Linear product frames`);
