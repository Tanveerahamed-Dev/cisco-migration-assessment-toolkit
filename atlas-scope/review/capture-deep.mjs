/**
 * capture-deep.mjs — DESIGN RESEARCH captures of the reference products' working surfaces, driven
 * live (tours advanced, banners dismissed). Output: review/shots/refs-deep/ (gitignored).
 *
 *   node review/capture-deep.mjs              capture (network; the Storylane player sends its own analytics)
 *   node review/capture-deep.mjs --selftest   offline: the tour/banner controls are found on their real markup
 *
 * NOT THE C1 REFERENCE SET. The blind pairings read review/capture-refs-clean.mjs, which renders
 * Forward's recorded pages OFFLINE (no player, no tour layer at all), keeps provenance, and
 * self-checks every frame for tour/banner markers on its pixels. This script remains for looking
 * at the live tours, and it is kept honest by the same lessons:
 *
 *   - Storylane's tour controls are NOT <button>s. They are `<div class="PlayerButton_root__…">`
 *     ("Start", "Next"). The old locator (`button:has-text("Next"), [class*="next"]` — lower-case
 *     n) matched nothing, the loop broke on its first iteration, and "step3" and "step6" were
 *     byte-identical frames presented as two reference states. `TOUR_ADVANCE` now targets the
 *     control's component class, and a frame byte-identical to the previous one is refused and
 *     reported as "the tour did not advance" instead of being written as a new state.
 *   - The tour layer (`WidgetManagerHtml_root…` and the other `Widget*` components) is hidden
 *     before every shot (`HIDE_TOUR_CSS`), so a frame shows the recording, not the coachmark.
 *   - Grafana's promo banner is dismissed by a control labelled "Close alert", which the old exact
 *     `[aria-label="Close"]` match missed. `DISMISS` matches every aria-label that STARTS with
 *     "Close" (the class of dismiss controls, not one label), plus the consent buttons.
 */
import { createHash } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const HERE = dirname(fileURLToPath(import.meta.url));
const SHOTS = resolve(HERE, "shots", "refs-deep");
const rel = (p) => relative(resolve(HERE, ".."), p).split("\\").join("/");

export const TOUR_ADVANCE = '[class*="PlayerButton_root"]:is(:text-matches("^(Start|Next|Continue|Let.s go|Get started)", "i"))';
export const HIDE_TOUR_CSS =
  '[class*="WidgetManagerHtml_root"],[class*="FloatingFrameControls"],[class*="WidgetDialogBackdrop"],[class*="WidgetBackdropAnimation"],[class*="WidgetSpotlight"]{visibility:hidden!important}';
export const DISMISS = ['[aria-label^="Close" i]:not([aria-label*="menu" i])', 'button:has-text("Accept")', 'button:has-text("Got it")', 'button:has-text("Allow all")'];

const settle = (page, ms) => page.waitForTimeout(ms);

/** Click the tour forward up to `steps` times. Returns how many clicks actually happened. */
export async function advanceTour(page, steps, pause = 2600) {
  let done = 0;
  for (let i = 0; i < steps; i++) {
    const next = page.locator(TOUR_ADVANCE).first();
    if (!(await next.count().catch(() => 0))) break;
    const ok = await next
      .click({ timeout: 4000 })
      .then(() => true)
      .catch(() => false);
    if (!ok) break;
    done++;
    await settle(page, pause);
  }
  return done;
}

export async function dismissOverlays(page) {
  const hit = [];
  for (const sel of DISMISS) {
    const els = page.locator(sel);
    const n = await els.count().catch(() => 0);
    for (let i = 0; i < n; i++) {
      const el = els.nth(i);
      if (!(await el.isVisible().catch(() => false))) continue;
      const label = (await el.getAttribute("aria-label").catch(() => null)) ?? sel;
      if (await el.click({ timeout: 1500 }).then(() => true, () => false)) hit.push(label);
    }
  }
  return hit;
}

const TARGETS = [
  { id: "grafana-explore", url: "https://play.grafana.org/explore", wait: 14000, note: "Grafana Explore — the query/result/inspect surface.", steps: 0 },
  { id: "grafana-dashboard-dense", url: "https://play.grafana.org/d/000000012/grafana-play-home", wait: 14000, note: "A dense working Grafana dashboard.", steps: 0 },
  { id: "forward-demo-a-step3", url: "https://app.storylane.io/demo/ts9nkc4osn4z?embed=inline", wait: 12000, note: "Forward demo advanced into the product.", steps: 3 },
  { id: "forward-demo-a-step6", url: "https://app.storylane.io/demo/ts9nkc4osn4z?embed=inline", wait: 12000, note: "Forward demo deeper into the flow.", steps: 6 },
  { id: "forward-demo-b-step3", url: "https://app.storylane.io/demo/jdhoywyw5voi?embed=inline", wait: 12000, note: "Second Forward demo, in-product.", steps: 3 },
  { id: "forward-demo-b-step6", url: "https://app.storylane.io/demo/jdhoywyw5voi?embed=inline", wait: 12000, note: "Second Forward demo, deeper.", steps: 6 },
  /* Research only — excluded from pairing (see REFERENCES.md): marketing and documentation pages. */
  { id: "linear-method", url: "https://linear.app/method", wait: 6000, note: "Linear's method page (marketing).", steps: 0, scrollY: 1400 },
  { id: "linear-homepage-product", url: "https://linear.app/", wait: 7000, note: "Linear homepage product imagery (marketing).", steps: 0, scrollY: 900 },
  { id: "ipfabric-viewer-figure", url: "https://docs.ipfabric.io/latest/IP_Fabric_GUI/diagrams/network_viewer/", wait: 6000, note: "IP Fabric network viewer docs figures.", steps: 0, scrollY: 1200 },
  { id: "batfish-results", url: "https://batfish.readthedocs.io/en/latest/notebooks/linked/introduction-to-forwarding-change-validation.html", wait: 6000, note: "Batfish result tables — claim vocabulary.", steps: 0, scrollY: 2600 },
];

async function capture() {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 2,
    colorScheme: "dark",
    userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
  });
  const written = [];
  const seen = new Map();
  mkdirSync(SHOTS, { recursive: true });
  for (const t of TARGETS) {
    const page = await ctx.newPage();
    try {
      await page.goto(t.url, { waitUntil: "domcontentloaded", timeout: 60000 });
      await settle(page, t.wait);
      const dismissed = await dismissOverlays(page);
      const advanced = t.steps ? await advanceTour(page, t.steps) : 0;
      if (t.scrollY) {
        await page.evaluate((y) => window.scrollTo(0, y), t.scrollY);
        await settle(page, 2000);
      }
      if (t.steps && advanced < t.steps) throw new Error(`the tour advanced ${advanced} of ${t.steps} steps — refusing to label this frame step${t.steps}`);
      await page.addStyleTag({ content: HIDE_TOUR_CSS });
      await settle(page, 400);
      const buf = await page.screenshot({ animations: "disabled", scale: "device" });
      const sha = createHash("sha256").update(buf).digest("hex");
      if (seen.has(sha)) throw new Error(`byte-identical to ${seen.get(sha)} — the tour did not advance; not written as a new state`);
      seen.set(sha, t.id);
      const file = resolve(SHOTS, `${t.id}.png`);
      writeFileSync(file, buf);
      written.push({ id: t.id, url: t.url, note: t.note, file: rel(file), sha256: sha, advanced, dismissed, ok: true });
      console.log(`  ok   ${t.id} (advanced ${advanced}, dismissed ${dismissed.length})`);
    } catch (e) {
      written.push({ id: t.id, url: t.url, note: t.note, file: null, ok: false, error: String(e).slice(0, 300) });
      console.log(`  FAIL ${t.id}: ${String(e).slice(0, 160)}`);
    }
    await page.close();
  }
  await browser.close();
  writeFileSync(resolve(SHOTS, "index.json"), JSON.stringify(written, null, 1));
  console.log(`captured ${written.filter((w) => w.ok).length}/${TARGETS.length} deep reference frames (design research; C1 uses capture-refs-clean.mjs)`);
}

/** Offline: the controls are found on the markup the real player and banner use. */
export async function selfTest() {
  let fails = 0;
  const t = (name, ok, detail = "") => {
    console.log(`${ok ? "  ok  " : "  FAIL"} ${name}${detail ? ` — ${detail}` : ""}`);
    if (!ok) fails++;
  };
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.setContent(
      `<div class="WidgetManagerHtml_root__zz"><div class="WidgetText_text__a">In this demo we investigate</div><div class="PlayerButton_root__KQ0uR" onclick="window.__n=(window.__n||0)+1">Next</div></div><div id="banner" role="alert">Create free account <button aria-label="Close alert" onclick="banner.remove()">x</button></div><button aria-label="Close menu" onclick="window.__menu=1">x</button>`,
    );
    t("TOUR_ADVANCE finds Storylane's <div> Next control", (await page.locator(TOUR_ADVANCE).count()) === 1);
    const n = await advanceTour(page, 2, 50);
    t("advanceTour clicks it and reports the clicks", n === 2 && (await page.evaluate(() => window.__n)) === 2, `advanced ${n}`);
    const d = await dismissOverlays(page);
    t("dismissOverlays closes a 'Close alert' banner", (await page.locator("#banner").count()) === 0, d.join(", "));
    t("dismissOverlays leaves the navigation menu alone", (await page.evaluate(() => window.__menu)) !== 1);
    await page.addStyleTag({ content: HIDE_TOUR_CSS });
    t("HIDE_TOUR_CSS hides the tour layer", !(await page.locator('[class*="WidgetManagerHtml_root"]').isVisible()));
    await page.setContent(`<div class="PlayerButton_root__KQ0uR">Back</div>`);
    t("TOUR_ADVANCE does not press a Back control", (await page.locator(TOUR_ADVANCE).count()) === 0);
  } finally {
    await browser.close();
  }
  return fails;
}

if (process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url))) {
  if (process.argv.includes("--selftest")) {
    const f = await selfTest();
    console.log(f ? `SELF-TEST FAILED (${f})` : "SELF-TEST PASSED");
    process.exit(f ? 1 : 0);
  }
  await capture();
}
