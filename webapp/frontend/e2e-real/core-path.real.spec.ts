import { readFile, writeFile } from "node:fs/promises";
import { test, expect, type Locator, type Page } from "@playwright/test";
import { SYNTHETIC_COLLECTION_MANIFEST, SYNTHETIC_COLLECTION_ZIP } from "./paths";

// The core path against the REAL backend: no page.route anywhere in this file. One campaign, two
// real engine ingests of the repository's synthetic collection (tests/synthetic_fixtures.py, written
// by serve_real_backend.py), the five snapshot views plus one device, and one
// cutover plan -> execution run -> post-change comparison walk.
//
// Assertions are coverage-honest rather than fixture-exact. Every engine value can legitimately be
// published or withheld, so the walk requires what holds either way:
// - the page never crashes (no uncaught page error, no /api 5xx, no "View unavailable" alert);
// - every withheld fact or list shows its evidence state AND its reason, and never a value;
// - no client-side placeholder (`undefined`, `NaN`, `[object Object]`) reaches text or an accessible
//   name, except verbatim inside text the engine itself authored (read from the same /api bodies);
// - where the fixture provably lacks evidence (a device folder without capacity captures), the
//   Trust screen lists that device as not assessed by the Control plane input, custody Not collected.
// Fixture preconditions are read from the launcher's manifest of the archive, never restated.

const INGEST_TIMEOUT = 10 * 60_000; // the backend's own engine-child timeout is 600 s
const LEAK = /\bundefined\b|\bNaN\b|\[object Object\]/;
// The commands compute_platform_health reads capacity from (cisco_toolkit/analyze.py). A device folder
// with none of them cannot be assessed by the register's Control plane input.
const CAPACITY_COMMAND_PREFIXES = ["show processes cpu", "show processes memory", "show system resources"];
// cutover_gate/1's closed verdict vocabulary, as ComparisonDecision colours it.
const CUTOVER_VERDICTS = ["PASS", "CONDITIONAL", "REVIEW", "INDETERMINATE", "FAIL", "REGRESSED"];
const ARROW = "\u2197";
const CAMPAIGN = "Real-backend E2E campaign";

type CollectionManifest = {
  schema: string;
  source: string;
  archive: string;
  devices: string[];
  commands: Record<string, string[]>;
};
type IngestMeta = {
  id: number;
  label: string;
  n_devices: number;
  ingest: { devices: string[]; n_device_dirs: number; devices_json: string; engine_seconds: number };
};

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Every string (and object key) any /api JSON body carried: the engine-authored text on screen. */
class EngineText {
  private readonly strings = new Set<string>();
  private readonly pending: Promise<void>[] = [];

  watch(page: Page): void {
    page.on("response", (response) => {
      if (!new URL(response.url()).pathname.startsWith("/api/")) return;
      if (!(response.headers()["content-type"] || "").includes("json")) return;
      // Read at once: a body can become unavailable after a later navigation.
      this.pending.push(response.text().then((body) => this.add(JSON.parse(body), 0)).catch(() => undefined));
    });
  }

  private add(value: unknown, depth: number): void {
    if (depth > 64) return;
    if (typeof value === "string") {
      this.strings.add(value);
    } else if (Array.isArray(value)) {
      for (const item of value) this.add(item, depth + 1);
    } else if (value !== null && typeof value === "object") {
      for (const [key, item] of Object.entries(value)) {
        this.strings.add(key);
        this.strings.add(key.replaceAll("_", " ")); // the screens' own key-to-label rendering
        this.add(item, depth + 1);
      }
    }
  }

  /** Engine strings that themselves contain a leak token, longest first. */
  async withLeakTokens(): Promise<string[]> {
    await Promise.all(this.pending.splice(0));
    return [...this.strings].filter((value) => LEAK.test(value)).sort((a, b) => b.length - a.length);
  }
}

/** Text nodes and accessible-name attributes under `scope` that carry a client-side placeholder. */
async function expectNoClientLeaks(scope: Locator, engine: EngineText, where: string): Promise<void> {
  const authored = await engine.withLeakTokens();
  const rendered = await scope.evaluate((root) => {
    const out: string[] = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (node.parentElement?.closest("script, style, noscript")) continue;
      const text = (node.nodeValue || "").trim();
      if (text) out.push(text);
    }
    const named = [root, ...Array.from(root.querySelectorAll("[aria-label], [title], [placeholder], [alt]"))];
    for (const element of named) {
      for (const attribute of ["aria-label", "title", "placeholder", "alt"]) {
        const value = element.getAttribute(attribute);
        if (value && value.trim()) out.push(value.trim());
      }
    }
    return out;
  });
  const leaks = rendered.filter((text) => {
    let residual = text;
    for (const value of authored) residual = residual.split(value).join(" ");
    return LEAK.test(residual);
  });
  expect(leaks, `${where}: a client-side placeholder reached the page outside engine-authored text`).toEqual([]);
}

/** The coverage-honest render contract of every FactView / ListState under `scope`; returns state counts. */
async function expectHonestStates(scope: Locator, where: string): Promise<Record<string, number>> {
  const result = await scope.evaluate((root) => {
    const counts: Record<string, number> = {};
    const problems: string[] = [];
    for (const host of Array.from(root.querySelectorAll(".projection-fact, .projection-list-state"))) {
      const excerpt = (host.textContent || "").replace(/\s+/g, " ").trim().slice(0, 160);
      const label = host.querySelector(":scope > .projection-state");
      const token = label
        ? Array.from(label.classList).find((name) => name.startsWith("state-"))?.slice("state-".length)
        : undefined;
      if (!label || !token || !(label.textContent || "").trim()) {
        problems.push(`no evidence state: ${excerpt}`);
        continue;
      }
      counts[token] = (counts[token] || 0) + 1;
      if (token === "published") continue;
      const reason = (host.querySelector(":scope > .projection-reason")?.textContent || "").trim();
      if (!reason) problems.push(`${token} without its reason: ${excerpt}`);
      if (host.classList.contains("projection-fact")) {
        const value = (host.querySelector(":scope > .projection-fact-value")?.textContent || "").trim();
        if (value !== "\u2014") problems.push(`${token} still renders a value ${JSON.stringify(value)}: ${excerpt}`);
      }
    }
    return { counts, problems };
  });
  expect(result.problems, `${where}: withheld evidence must show its state and reason, never a value`).toEqual([]);
  return result.counts;
}

/** The FactView labelled `label` under `scope`. The inner locator comes from the page on purpose:
 * Playwright evaluates a `has` locator's whole selector inside each candidate element. */
function factByLabel(page: Page, scope: Page | Locator, label: string): Locator {
  return scope.locator(".projection-fact").filter({
    has: page.getByRole("button", { name: `Evidence for ${label}`, exact: true }),
  });
}

async function ingestSyntheticCollection(page: Page, campaignId: number, label: string): Promise<IngestMeta> {
  await page.goto(`/campaigns/${campaignId}`);
  const panel = page.locator(".panel").filter({ has: page.getByRole("heading", { name: /ingest a raw collection/ }) });
  await expect(panel).toHaveCount(1);
  await panel.getByLabel("Collection archive (.zip)").setInputFiles(SYNTHETIC_COLLECTION_ZIP);
  await panel.getByLabel("Label (optional)").fill(label);
  const ingested = page.waitForResponse((response) => response.request().method() === "POST"
    && new URL(response.url()).pathname === `/api/campaigns/${campaignId}/ingest`, { timeout: INGEST_TIMEOUT });
  await panel.getByRole("button", { name: /Run engine & ingest/ }).click();
  const response = await ingested;
  const body = await response.text();
  expect(response.status(), `engine ingest refused: ${body.slice(0, 2000)}`).toBe(201);
  const meta = JSON.parse(body) as IngestMeta;
  expect(meta.label).toBe(label);
  await page.waitForURL(new RegExp(`/snapshots/${meta.id}$`));
  return meta;
}

test("real backend: engine ingest, coverage-honest core views, cutover plan to execution to compare", async ({ page }, testInfo) => {
  const evidence: Record<string, unknown> = {};
  const pageErrors: string[] = [];
  const serverErrors: string[] = [];
  const consoleErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("response", (response) => {
    const pathname = new URL(response.url()).pathname;
    if (pathname.startsWith("/api/") && response.status() >= 500) {
      serverErrors.push(`${response.status()} ${response.request().method()} ${pathname}`);
    }
  });
  const engine = new EngineText();
  engine.watch(page);

  try {
    const collection = JSON.parse(await readFile(SYNTHETIC_COLLECTION_MANIFEST, "utf-8")) as CollectionManifest;
    expect(collection.schema).toBe("real_backend_e2e_collection/1");
    const capacityBlind = collection.devices.filter((host) => !(collection.commands[host] || [])
      .some((command) => CAPACITY_COMMAND_PREFIXES.some((prefix) => command.startsWith(prefix))));
    // Precondition from the archive itself: some, but not all, device folders lack capacity evidence.
    expect(capacityBlind.length, `fixture precondition: ${collection.source}`).toBeGreaterThan(0);
    expect(capacityBlind.length, `fixture precondition: ${collection.source}`).toBeLessThan(collection.devices.length);
    evidence.collection = { source: collection.source, devices: collection.devices, capacity_blind: capacityBlind };

    const campaignId = await test.step("create a campaign", async () => {
      await page.goto("/campaigns");
      await page.getByRole("button", { name: /New campaign$/ }).click();
      await page.getByLabel("Name", { exact: true }).fill(CAMPAIGN);
      await page.getByRole("button", { name: "Create", exact: true }).click();
      await page.waitForURL(/\/campaigns\/\d+$/);
      await expect(page.getByRole("heading", { level: 1, name: CAMPAIGN, exact: true })).toBeVisible();
      return Number(new URL(page.url()).pathname.split("/").pop());
    });
    evidence.campaign_id = campaignId;

    const baseline = await test.step("ingest the synthetic collection through the real engine", async () => {
      const meta = await ingestSyntheticCollection(page, campaignId, "Baseline collection");
      expect(meta.n_devices).toBe(collection.devices.length);
      expect([...meta.ingest.devices].sort()).toEqual(collection.devices);
      expect(meta.ingest.devices_json).toBe("synthesized");
      return meta;
    });
    evidence.baseline = { id: baseline.id, engine_seconds: baseline.ingest.engine_seconds };

    const shell = page.locator("main.projection-shell");
    const views: Record<string, Record<string, number>> = {};
    const settle = async (where: string) => {
      await expect(shell.getByRole("status").filter({ hasText: /^(Loading|Preparing) / })).toHaveCount(0);
      await expect(shell.getByRole("alert"), `${where}: a view or list failed to load`).toHaveCount(0);
      views[where] = await expectHonestStates(shell, where);
      await expectNoClientLeaks(page.locator("body"), engine, where);
    };
    const openView = async (title: string, anchor: Locator, timeout = 30_000) => {
      await page.getByRole("navigation", { name: "Snapshot views" }).getByRole("link", { name: title, exact: true }).click();
      await expect(anchor).toBeVisible({ timeout });
    };

    await test.step("Overview", async () => {
      await expect(page.getByRole("heading", { level: 1, name: `Snapshot ${baseline.id}`, exact: true })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Fleet posture", exact: true })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Health assessment", exact: true })).toBeVisible();
      await settle("overview");
      // A published device count must be the fleet this archive carried; a withheld one is covered above.
      const devicesFact = factByLabel(page, page, "Devices with health records");
      await expect(devicesFact).toHaveCount(1);
      if (/\bstate-published\b/.test(await devicesFact.locator(".projection-state").getAttribute("class") || "")) {
        await expect(devicesFact.locator(".projection-fact-value")).toHaveText(String(collection.devices.length));
      }
    });

    await test.step("Trust: the fixture's missing capacity evidence is shown as not assessed", async () => {
      await openView("Trust", page.getByRole("heading", { name: "Evidence coverage", exact: true }));
      await expect(page.getByRole("heading", { name: "What the analysis could not see", exact: true })).toBeVisible();
      await settle("trust");
      const controlPlane = page.getByRole("article", { name: "Control plane analysis input", exact: true });
      await expect(controlPlane).toBeVisible();
      const sentence = controlPlane.locator("p").filter({ hasText: /^\d+ of \d+ inventory devices could not be assessed$/ });
      if (await sentence.count()) {
        // Both counts published: the gap may not be rendered as zero.
        const [n, of] = ((await sentence.first().innerText()).match(/\d+/g) || []).map(Number);
        expect(n).toBeGreaterThanOrEqual(capacityBlind.length);
        expect(n).toBeLessThanOrEqual(of);
        evidence.control_plane_gap = { n, of };
      } else {
        evidence.control_plane_gap = "count withheld with its own state and reason";
      }
      await controlPlane.locator("summary").filter({ hasText: "Devices and custody" }).click();
      for (const host of capacityBlind) {
        const gap = controlPlane.getByRole("group", { name: `${host} not assessed by Control plane`, exact: true });
        await expect(gap).toBeVisible();
        await expect(gap.locator(".projection-state")).toHaveClass(/(^|\s)state-not_collected(\s|$)/);
      }
    });

    await test.step("Inventory", async () => {
      await openView("Inventory", page.getByRole("heading", { name: "Device inventory", exact: true }));
      await settle("inventory");
      for (const host of collection.devices) {
        await expect(page.getByRole("link", { name: `${host} ${ARROW}`, exact: true })).toBeVisible();
      }
    });

    await test.step("Device page for a device with missing evidence", async () => {
      const host = capacityBlind[0];
      await page.getByRole("link", { name: `${host} ${ARROW}`, exact: true }).click();
      await expect(page.getByRole("heading", { level: 1, name: host, exact: true })).toBeVisible();
      for (const title of ["Health", "Collection", "Physical", "Lifecycle", "Finding severity", "Coverage summary", "Risk register"]) {
        await expect(page.getByRole("heading", { level: 2, name: title, exact: true })).toBeVisible();
      }
      await settle("device");
    });

    await test.step("Findings", async () => {
      await openView("Findings", page.getByRole("heading", { name: "Prioritised findings", exact: true }));
      await settle("findings");
      const finding = page.locator("article.projection-finding").first();
      await expect(finding).toBeVisible();
      await finding.locator("summary").filter({ hasText: "Issue, remediation and evidence" }).click();
      await expect(factByLabel(page, finding, "Remediation")).toBeVisible();
    });

    await test.step("Topology & Paths", async () => {
      await openView("Topology & Paths", page.getByText("All projected list pages loaded.", { exact: false }), 120_000);
      await expect(page.getByRole("img", { name: "Engine topology diagram" })).toBeVisible();
      for (const host of collection.devices) {
        await expect(page.getByRole("button", { name: new RegExp(`^Inspect node ${escapeRegExp(host)}: `) })).toBeVisible();
      }
      await settle("topology");
    });
    evidence.views = views;
    const withheld = Object.values(views).reduce((total, counts) => total + Object.entries(counts)
      .filter(([token]) => token !== "published").reduce((sum, [, count]) => sum + count, 0), 0);
    // The fixture lacks evidence; the screens must say so somewhere rather than render it all as published.
    expect(withheld, "no view showed any withheld evidence for a collection that lacks some").toBeGreaterThan(0);

    const executionId = await test.step("cutover plan -> start an execution run", async () => {
      await page.goto(`/snapshots/${baseline.id}/tools`);
      const heading = page.getByRole("heading", { name: "Cutover plan \u00b7 run-of-show", exact: true });
      await expect(heading).toBeVisible({ timeout: 120_000 });
      const planner = heading.locator("xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' panel ')][1]");
      await expectNoClientLeaks(planner, engine, "cutover plan");
      await planner.getByRole("button", { name: /Start execution run/ }).click();
      await page.waitForURL(/\/executions\/\d+$/);
      return Number(new URL(page.url()).pathname.split("/").pop());
    });

    const steps = await test.step("execution: no receipt yet, then action every implementation step", async () => {
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      // Absence of post-change evidence is said as itself, never as a pass.
      await expect(page.getByTestId("execution-canonical-gate-missing")).toContainText("NOT VERIFIED");
      await expect(page.getByTestId("execution-compare-form"))
        .toContainText("No post-start snapshot is available in this campaign yet.");
      await expectNoClientLeaks(page.locator("body"), engine, "execution (live)");
      const pending = page.getByRole("button", { name: /^Mark step \d+ done$/ });
      const total = await pending.count();
      expect(total, "the plan materialized no implementation steps").toBeGreaterThan(0);
      for (let remaining = total; remaining > 0; remaining -= 1) {
        await pending.first().click();
        await expect(pending).toHaveCount(remaining - 1);
      }
      await expect(page.getByText(new RegExp(`\\b${total} of ${total} steps done\\b`))).toBeVisible();
      return total;
    });

    const postChange = await test.step("ingest post-change evidence after the steps were actioned", async () => {
      const meta = await ingestSyntheticCollection(page, campaignId, "Post-change collection");
      expect(meta.id).toBeGreaterThan(baseline.id);
      return meta;
    });

    const verdict = await test.step("bind the post-change snapshot and compare", async () => {
      await page.goto(`/executions/${executionId}`);
      const after = page.getByLabel("After snapshot", { exact: true });
      await expect(after.locator(`option[value="${postChange.id}"]`)).toHaveCount(1);
      await after.selectOption(String(postChange.id));
      const compared = page.waitForResponse((response) => response.request().method() === "POST"
        && new URL(response.url()).pathname === `/api/executions/${executionId}/compare`, { timeout: 300_000 });
      await page.getByRole("button", { name: "Bind and compare", exact: true }).click();
      const response = await compared;
      const body = await response.text();
      expect(response.status(), `post-change comparison refused: ${body.slice(0, 2000)}`).toBe(200);
      await expect(page.getByTestId("canonical-cutover-decision")).toBeVisible();
      const chip = (await page.getByTestId("canonical-cutover-verdict").innerText()).trim();
      expect(CUTOVER_VERDICTS).toContain(chip);
      await expect(page.getByTestId("canonical-cutover-operator-note")).not.toBeEmpty();
      await expect(page.getByTestId("execution-canonical-gate-missing")).toHaveCount(0);
      await expect(page.getByTestId("execution-compare-form")).toContainText("1 immutable comparison receipt(s) retained");
      await expectNoClientLeaks(page.locator("body"), engine, "execution (compared)");
      return chip;
    });
    evidence.cutover = {
      execution_id: executionId, steps_actioned: steps, post_change_snapshot: postChange.id,
      post_change_engine_seconds: postChange.ingest.engine_seconds, verdict,
    };

    expect(pageErrors, "uncaught page errors").toEqual([]);
    expect(serverErrors, "API responses with a 5xx status").toEqual([]);
  } finally {
    const file = testInfo.outputPath("real-backend-walk.json");
    await writeFile(file, `${JSON.stringify({ ...evidence, pageErrors, serverErrors, consoleErrors: consoleErrors.slice(0, 50) }, null, 2)}\n`, "utf-8");
    await testInfo.attach("real-backend-walk", { path: file, contentType: "application/json" });
  }
});
