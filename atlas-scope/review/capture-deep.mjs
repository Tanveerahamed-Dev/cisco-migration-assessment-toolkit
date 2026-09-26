/**
 * capture-deep.mjs — capture the reference products' actual WORKING surfaces, not their landing
 * pages. A blind comparison against a marketing page proves nothing; the bar is what these tools
 * look like while someone is using them.
 *
 * Each target drives the page to a real working state before shooting: opening a dashboard,
 * advancing a guided tour past its intro modal, expanding a docs figure to full size.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const HERE = dirname(fileURLToPath(import.meta.url));
const SHOTS = resolve(HERE, "shots", "refs-deep");

const settle = (page, ms) => page.waitForTimeout(ms);

/** Click a Storylane tour forward N times so the capture shows the product, not the intro card. */
async function advanceTour(page, steps) {
  for (let i = 0; i < steps; i++) {
    const next = page
      .locator('button:has-text("Next"), [class*="next"], [data-testid*="next"]')
      .first();
    if (!(await next.count().catch(() => 0))) break;
    await next.click({ timeout: 4000 }).catch(() => {});
    await settle(page, 2600);
  }
}

const TARGETS = [
  {
    id: "grafana-explore",
    url: "https://play.grafana.org/explore",
    wait: 14000,
    note: "Grafana Explore — the query/result/inspect surface.",
    drive: async (page) => {
      await settle(page, 6000);
    },
  },
  {
    id: "grafana-dashboard-dense",
    // A real, dense, working dashboard rather than the Play home page.
    url: "https://play.grafana.org/d/000000012/grafana-play-home",
    wait: 14000,
    note: "A dense working Grafana dashboard.",
    drive: async (page) => {
      await settle(page, 5000);
    },
  },
  {
    id: "forward-demo-a-step3",
    url: "https://app.storylane.io/demo/ts9nkc4osn4z?embed=inline",
    wait: 12000,
    note: "Forward demo advanced past the intro modal into the product.",
    drive: async (page) => advanceTour(page, 3),
  },
  {
    id: "forward-demo-a-step6",
    url: "https://app.storylane.io/demo/ts9nkc4osn4z?embed=inline",
    wait: 12000,
    note: "Forward demo deeper into the investigation flow.",
    drive: async (page) => advanceTour(page, 6),
  },
  {
    id: "forward-demo-b-step3",
    url: "https://app.storylane.io/demo/jdhoywyw5voi?embed=inline",
    wait: 12000,
    note: "Second Forward demo, in-product.",
    drive: async (page) => advanceTour(page, 3),
  },
  {
    id: "forward-demo-b-step6",
    url: "https://app.storylane.io/demo/jdhoywyw5voi?embed=inline",
    wait: 12000,
    note: "Second Forward demo, deeper.",
    drive: async (page) => advanceTour(page, 6),
  },
  {
    id: "linear-method",
    url: "https://linear.app/method",
    wait: 6000,
    note: "Linear's own product surfaces at full craft.",
    drive: async (page) => {
      await page.evaluate(() => window.scrollTo(0, 1400));
      await settle(page, 2500);
    },
  },
  {
    id: "linear-homepage-product",
    url: "https://linear.app/",
    wait: 7000,
    note: "Linear product shots: density, typography, colour discipline.",
    drive: async (page) => {
      await page.evaluate(() => window.scrollTo(0, 900));
      await settle(page, 2500);
    },
  },
  {
    id: "ipfabric-viewer-figure",
    url: "https://docs.ipfabric.io/latest/IP_Fabric_GUI/diagrams/network_viewer/",
    wait: 6000,
    note: "IP Fabric network viewer figures, scrolled to the diagram itself.",
    drive: async (page) => {
      await page.evaluate(() => window.scrollTo(0, 1200));
      await settle(page, 2000);
    },
  },
  {
    id: "batfish-results",
    url: "https://batfish.readthedocs.io/en/latest/notebooks/linked/introduction-to-forwarding-change-validation.html",
    wait: 6000,
    note: "Batfish result tables — the claim/counterexample presentation.",
    drive: async (page) => {
      await page.evaluate(() => window.scrollTo(0, 2600));
      await settle(page, 2000);
    },
  },
];

const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  deviceScaleFactor: 2,
  colorScheme: "dark",
  userAgent:
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
});
const written = [];
mkdirSync(SHOTS, { recursive: true });

for (const t of TARGETS) {
  const page = await ctx.newPage();
  try {
    await page.goto(t.url, { waitUntil: "domcontentloaded", timeout: 60000 });
    await settle(page, t.wait);
    for (const sel of ['button:has-text("Accept")', 'button:has-text("Got it")', 'button:has-text("Allow all")']) {
      const el = page.locator(sel).first();
      if (await el.count().catch(() => 0)) await el.click({ timeout: 1500 }).catch(() => {});
    }
    await t.drive(page);
    const file = resolve(SHOTS, `${t.id}.png`);
    await page.screenshot({ path: file, animations: "disabled", scale: "device" });
    written.push({ id: t.id, url: t.url, note: t.note, file, ok: true });
    console.log(`  ok   ${t.id}`);
  } catch (e) {
    written.push({ id: t.id, url: t.url, note: t.note, file: null, ok: false, error: String(e).slice(0, 300) });
    console.log(`  FAIL ${t.id}: ${String(e).slice(0, 140)}`);
  }
  await page.close();
}

await browser.close();
writeFileSync(resolve(SHOTS, "index.json"), JSON.stringify(written, null, 1));
console.log(`captured ${written.filter((w) => w.ok).length}/${TARGETS.length} deep reference frames`);
