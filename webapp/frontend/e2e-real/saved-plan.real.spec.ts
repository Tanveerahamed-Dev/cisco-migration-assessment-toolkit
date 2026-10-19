import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { inflateRawSync } from "node:zlib";
import { expect, test, type Page, type Request as PlaywrightRequest, type TestInfo } from "@playwright/test";
import type { SavedPlanRecord, SavedPlanState } from "../src/api";
import { REAL_ORIGIN } from "./paths";

// The existing real-backend core walk proves fresh collection/engine ingestion. This separate
// walk uses the bundled synthetic snapshot through the ordinary browser upload, avoiding another
// expensive engine run. Traffic is unmodified; passive request and WebSocket observers fail the
// walk if any foreign origin is contacted. No response is mocked or connection intercepted.
// This is synthetic local-browser evidence, not a physical disconnected/Python-absent host test.
const SAMPLE = fileURLToPath(new URL("../../sample_data/sample_fleet.snapshot.json", import.meta.url));
const DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
const hash = (value: Buffer) => createHash("sha256").update(value).digest("hex");

/** Read only the bounded main XML part from the actual native browser download, with no extra dependency. */
function mainDocumentXml(bytes: Buffer): string {
  expect(bytes.length).toBeLessThanOrEqual(32 * 1024 * 1024);
  let end = bytes.length - 22;
  const earliest = Math.max(0, bytes.length - 22 - 65535);
  while (end >= earliest && bytes.readUInt32LE(end) !== 0x06054b50) end--;
  expect(end, "DOCX must contain a ZIP central-directory end record").toBeGreaterThanOrEqual(earliest);
  const count = bytes.readUInt16LE(end + 10);
  expect(count).toBeGreaterThan(0);
  expect(count).toBeLessThanOrEqual(512);
  let cursor = bytes.readUInt32LE(end + 16);
  let xml: Buffer | null = null;
  const names: string[] = [];
  for (let index = 0; index < count; index++) {
    expect(bytes.readUInt32LE(cursor)).toBe(0x02014b50);
    const method = bytes.readUInt16LE(cursor + 10);
    const compressed = bytes.readUInt32LE(cursor + 20);
    const expanded = bytes.readUInt32LE(cursor + 24);
    const nameLength = bytes.readUInt16LE(cursor + 28);
    const extraLength = bytes.readUInt16LE(cursor + 30);
    const commentLength = bytes.readUInt16LE(cursor + 32);
    const name = bytes.subarray(cursor + 46, cursor + 46 + nameLength).toString("utf8");
    names.push(name);
    if (name === "word/document.xml") {
      expect(xml, "DOCX must not contain duplicate main parts").toBeNull();
      expect(expanded).toBeLessThanOrEqual(4 * 1024 * 1024);
      const local = bytes.readUInt32LE(cursor + 42);
      expect(bytes.readUInt32LE(local)).toBe(0x04034b50);
      expect(bytes.readUInt16LE(local + 6) & 1, "DOCX main part must not be encrypted").toBe(0);
      const start = local + 30 + bytes.readUInt16LE(local + 26) + bytes.readUInt16LE(local + 28);
      expect(start + compressed).toBeLessThanOrEqual(bytes.length);
      const payload = bytes.subarray(start, start + compressed);
      expect([0, 8]).toContain(method);
      xml = method === 8 ? inflateRawSync(payload, { maxOutputLength: 4 * 1024 * 1024 }) : payload;
      expect(xml.length).toBe(expanded);
    }
    cursor += 46 + nameLength + extraLength + commentLength;
  }
  expect(new Set(names).size, "DOCX member names must be unique").toBe(names.length);
  expect(names).toContain("[Content_Types].xml");
  expect(names).toContain("_rels/.rels");
  expect(xml).not.toBeNull();
  return new TextDecoder("utf-8", { fatal: true }).decode(xml!);
}

async function rawAssessment(page: Page, snapshotId: number): Promise<Buffer> {
  const result = await page.evaluate(async (id) => {
    const response = await fetch(`/api/snapshots/${id}/raw`);
    if (!response.ok) throw new Error(`Original assessment read failed: ${response.status}`);
    return Array.from(new Uint8Array(await response.arrayBuffer()));
  }, snapshotId);
  return Buffer.from(result);
}

async function saveRevision(page: Page, snapshotId: number, label: string, fabric: string): Promise<SavedPlanRecord> {
  await page.getByLabel("Plan name", { exact: true }).fill(label);
  await page.getByLabel("Fabric operating model", { exact: true }).selectOption(fabric);
  await page.getByLabel("Convergence budget (ms)", { exact: true }).fill("0");
  await page.getByLabel("Constraints", { exact: true }).fill("Synthetic offline UI qualification");
  const saved = page.waitForResponse((response) => response.request().method() === "POST"
    && new URL(response.url()).pathname === `/api/snapshots/${snapshotId}/plans`);
  // Exercise the labelled form's keyboard submit instead of relying only on pointer activation.
  await page.getByRole("button", { name: "Save new revision", exact: true }).focus();
  await page.getByRole("button", { name: "Save new revision", exact: true }).press("Enter");
  const response = await saved;
  expect(response.status(), "The real server must persist a new revision").toBe(201);
  const plan = await response.json() as SavedPlanRecord;
  expect(plan.schema).toBe("atlas.saved_plan/1");
  expect(plan.status).toBe("UNAPPROVED_DRAFT");
  expect(plan.projection.requirements.fabric_operating_model).toBe(fabric);
  expect(typeof plan.projection.requirements.convergence_budget_ms).toBe("number");
  expect(plan.projection.requirements.convergence_budget_ms).toBe(0);
  expect(plan.projection.requirements.constraints).toContain("Synthetic offline UI qualification");
  await expect(page.getByRole("status").filter({ hasText: `Revision ${plan.revision} saved and selected.` })).toBeVisible();
  return plan;
}

async function expectSavedView(page: Page, plan: SavedPlanRecord): Promise<void> {
  await expect(page.getByLabel("Plan name", { exact: true })).toHaveValue(plan.label);
  await expect(page.getByLabel("Convergence budget (ms)", { exact: true })).toHaveValue("0");
  await expect(page.getByLabel("Fabric operating model", { exact: true }))
    .toHaveValue(plan.projection.requirements.fabric_operating_model!);
  const selected = page.getByRole("region", { name: "Selected plan and documents", exact: true });
  await expect(selected).toContainText(`Revision ${plan.revision} · Selection ${plan.selection_id}`);
  await expect(selected).toContainText(plan.sha256);
  await expect(selected).toContainText("UNAPPROVED DRAFT");
  const preview = page.getByRole("region", { name: "Saved design and NRFU plan", exact: true });
  const headline = plan.projection.sections.design_blueprint.summary.headline;
  expect(headline.trim(), "The fixture must yield a visible persisted design summary").not.toBe("");
  await expect(preview).toContainText(headline);
  await expect(page.getByRole("button", { name: "Download MOP", exact: true })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Download NRFU", exact: true })).toBeEnabled();
}

type OriginalHttpCapture = {
  requestUrl: string;
  method: string;
  responseUrl: string;
  status: number;
  headers: Record<string, string>;
  bytes: number[];
  matchingRequests: number;
  originalFetchRestored: boolean;
};

type OriginalHttpCaptureState = {
  originalFetch: typeof window.fetch;
  wrappedFetch: typeof window.fetch;
  pending: Promise<OriginalHttpCapture>;
  matchingRequests: number;
  nativePromise?: Promise<Response>;
  nativeResponse?: Response;
};

declare global {
  interface Window {
    __atlasOriginalHttpCapture?: OriginalHttpCaptureState;
  }
}

/** Observe the original browser HTTP response, without CDP's optional retained-body cache. */
async function beginOriginalHttpCapture(page: Page, pathname: string): Promise<void> {
  await page.evaluate((targetPath) => {
    if (window.__atlasOriginalHttpCapture) throw new Error("An earlier HTTP capture was not consumed");
    const originalFetch = window.fetch;
    let complete!: (value: OriginalHttpCapture) => void;
    let fail!: (reason: unknown) => void;
    const pending = new Promise<OriginalHttpCapture>((resolve, reject) => { complete = resolve; fail = reject; });
    // The unchanged download assertions always await this promise; a rejected observation is never a fallback.
    void pending.catch(() => undefined);
    const state: OriginalHttpCaptureState = {
      originalFetch, wrappedFetch: originalFetch, pending, matchingRequests: 0,
    };
    const restore = (): void => {
      if (window.fetch !== state.wrappedFetch && window.fetch !== originalFetch) {
        throw new Error("The original fetch observer was replaced during capture");
      }
      window.fetch = originalFetch;
      if (window.fetch !== originalFetch) throw new Error("The original fetch was not restored");
    };
    const refuse = (error: unknown): void => {
      try { restore(); } catch (restoreError) {
        fail(new AggregateError([error, restoreError], "HTTP capture and restoration failed"));
        return;
      }
      fail(error);
    };
    const wrappedFetch = new Proxy(originalFetch, {
      apply(target, thisArg, args) {
        // Forward exactly once, preserving this/arguments and the SAME native promise/Response.
        const nativePromise = Reflect.apply(target, thisArg, args) as Promise<Response>;
        try {
          const input = args[0] as RequestInfo | URL;
          const options = args[1] as RequestInit | undefined;
          const requestUrl = new URL(input instanceof Request ? input.url : String(input), window.location.href);
          const method = (options?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
          if (method === "GET" && requestUrl.origin === window.location.origin && requestUrl.pathname === targetPath) {
            state.matchingRequests++;
            state.nativePromise = nativePromise;
            if (state.matchingRequests !== 1) {
              refuse(new Error("The download issued more than one matching HTTP request"));
              return nativePromise;
            }
            void nativePromise.then(async (response) => {
              state.nativeResponse = response;
              // This reaction is registered before returning the native promise to the UI consumer.
              // Clone its real response; never replay the request, synthesize bytes, or replace the response.
              const reader = response.clone().body?.getReader();
              if (!reader) throw new Error("The original HTTP response has no readable body");
              const chunks: Uint8Array[] = [];
              let total = 0;
              try {
                for (;;) {
                  const part = await reader.read();
                  if (part.done) break;
                  total += part.value.byteLength;
                  if (total > 32 * 1024 * 1024) {
                    void reader.cancel().catch(() => undefined);
                    throw new Error("The original HTTP body exceeds the existing 32 MiB document limit");
                  }
                  chunks.push(part.value);
                }
              } finally { reader.releaseLock(); }
              const bytes = new Uint8Array(total);
              let offset = 0;
              for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
              const headers: Record<string, string> = {};
              response.headers.forEach((value, name) => { headers[name] = value; });
              restore();
              complete({ requestUrl: requestUrl.href, method, responseUrl: response.url,
                status: response.status, headers, bytes: Array.from(bytes),
                matchingRequests: state.matchingRequests, originalFetchRestored: window.fetch === originalFetch });
            }, refuse).catch(refuse);
          }
        } catch (error) { refuse(error); }
        return nativePromise;
      },
    });
    state.wrappedFetch = wrappedFetch;
    window.__atlasOriginalHttpCapture = state;
    window.fetch = wrappedFetch;
  }, pathname);
}

async function takeOriginalHttpCapture(page: Page): Promise<OriginalHttpCapture> {
  return page.evaluate(async () => {
    const state = window.__atlasOriginalHttpCapture;
    if (!state) throw new Error("The original HTTP capture is missing");
    const captured = await state.pending;
    if (window.fetch !== state.originalFetch) throw new Error("The original fetch identity changed after capture");
    delete window.__atlasOriginalHttpCapture;
    return captured;
  });
}

async function downloadDocument(page: Page, testInfo: TestInfo, snapshotId: number,
  plan: SavedPlanRecord, kind: "mop" | "nrfu"): Promise<Record<string, unknown>> {
  const exportPath = `/api/snapshots/${snapshotId}/plans/${plan.revision}/deliverable/${kind}`;
  const exportOrigin = new URL(page.url()).origin;
  const exportRequests: string[] = [];
  const observeExportRequest = (request: PlaywrightRequest) => {
    const url = new URL(request.url());
    if (request.method() === "GET" && url.origin === exportOrigin && url.pathname === exportPath) {
      exportRequests.push(request.url());
    }
  };
  // Keep observing after the native-fetch clone restores fetch, through save/hash/XML checks.
  page.on("request", observeExportRequest);
  try {
    await beginOriginalHttpCapture(page, exportPath);
    const responsePromise = page.waitForResponse((response) => response.request().method() === "GET"
      && new URL(response.url()).pathname === exportPath);
    const downloadPromise = page.waitForEvent("download");
    // An earlier HTTP assertion must remain the failure if no native download can follow it.
    void responsePromise.catch(() => undefined);
    void downloadPromise.catch(() => undefined);
    await page.getByRole("button", { name: kind === "mop" ? "Download MOP" : "Download NRFU", exact: true }).click();
    const response = await responsePromise;
    expect(response.status()).toBe(200);
    const headers = response.headers();
    expect(headers["content-type"].split(";", 1)[0]).toBe(DOCX_MEDIA);
    expect(headers["x-atlas-assessment-sha256"]).toBe(plan.assessment.sha256);
    expect(headers["x-atlas-plan-revision"]).toBe(String(plan.revision));
    expect(headers["x-atlas-plan-sha256"]).toBe(plan.sha256);
    expect(headers["x-atlas-plan-selection"]).toBe(String(plan.selection_id));
    expect(headers["x-atlas-plan-status"]).toBe("UNAPPROVED_DRAFT");
    const query = new URL(response.url()).searchParams;
    expect(query.get("plan_sha256")).toBe(plan.sha256);
    expect(query.get("selection_id")).toBe(String(plan.selection_id));
    const captured = await takeOriginalHttpCapture(page);
    expect(captured.method).toBe("GET");
    expect(captured.requestUrl).toBe(response.url());
    expect(captured.responseUrl).toBe(response.url());
    expect(captured.status).toBe(response.status());
    expect(captured.matchingRequests).toBe(1);
    expect(captured.originalFetchRestored).toBe(true);
    for (const name of ["content-type", "x-atlas-assessment-sha256", "x-atlas-plan-revision",
      "x-atlas-plan-sha256", "x-atlas-plan-selection", "x-atlas-plan-status"]) {
      expect(captured.headers[name], "The original browser response must match the observed HTTP identity headers")
        .toBe(headers[name]);
    }
    const originalHttpBytes = Buffer.from(captured.bytes);
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe(`Atlas-snapshot-${snapshotId}-plan-r${plan.revision}-${kind}.docx`);
    const path = testInfo.outputPath(`${kind}-revision-${plan.revision}-selection-${plan.selection_id}.docx`);
    await download.saveAs(path);
    expect(await download.failure()).toBeNull();
    const bytes = await readFile(path);
    expect(hash(bytes), "The native blob download must equal the exact verified API response")
      .toBe(hash(originalHttpBytes));
    const xml = mainDocumentXml(bytes);
    const visible = await page.evaluate(({ xml: content, namespace }) => {
      const document = new DOMParser().parseFromString(content, "application/xml");
      if (document.getElementsByTagName("parsererror").length || document.documentElement.localName !== "document"
          || document.documentElement.namespaceURI !== namespace) throw new Error("Invalid main Word document XML");
      return Array.from(document.getElementsByTagNameNS(namespace, "t")).map((item) => item.textContent || "").join(" ");
    }, { xml, namespace: WORD_NAMESPACE });
    for (const text of ["UNAPPROVED DRAFT", `Original assessment SHA-256: ${plan.assessment.sha256}`,
      `Selected plan SHA-256: ${plan.sha256}`, `Revision ${plan.revision} · Selection ${plan.selection_id}`]) {
      expect(visible, "The downloaded document must carry visible original-source and selected-plan identity").toContain(text);
    }
    expect(exportRequests, "The complete native download must issue one exact export GET")
      .toEqual([response.url()]);
    return { kind, revision: plan.revision, selection_id: plan.selection_id, plan_sha256: plan.sha256,
      assessment_sha256: plan.assessment.sha256, bytes: bytes.length, sha256: hash(bytes),
      browser_blob_matches_http: true, visible_provenance: true, unapproved_draft: true,
      http_capture: "original_native_fetch_response_clone", matching_request_count: exportRequests.length };
  } finally {
    page.off("request", observeExportRequest);
  }
}

test("original HTTP capture preserves native fetch promise, response and bytes", async ({ page }) => {
  // A real JSON navigation has no application scripts or background requests. No endpoint is mocked.
  await page.goto("/api/meta");
  const requests: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "GET" && new URL(request.url()).pathname === "/api/meta") requests.push(request.url());
  });
  await beginOriginalHttpCapture(page, "/api/meta");
  const consumer = await page.evaluate(async () => {
    const pending = window.fetch("/api/meta", { cache: "no-store" });
    const state = window.__atlasOriginalHttpCapture!;
    const samePromise = pending === state.nativePromise;
    const response = await pending;
    const sameResponse = response === state.nativeResponse;
    return { samePromise, sameResponse, status: response.status,
      bytes: Array.from(new Uint8Array(await response.arrayBuffer())) };
  });
  const captured = await takeOriginalHttpCapture(page);
  expect(consumer.samePromise).toBe(true);
  expect(consumer.sameResponse).toBe(true);
  expect(consumer.status).toBe(200);
  expect(captured.status).toBe(200);
  expect(captured.matchingRequests).toBe(1);
  expect(captured.originalFetchRestored).toBe(true);
  expect(requests).toHaveLength(1);
  expect(hash(Buffer.from(consumer.bytes))).toBe(hash(Buffer.from(captured.bytes)));
});

test("real backend: ordinary upload to persisted selected plan and source-bound MOP/NRFU downloads", async ({ page, context }, testInfo) => {
  const evidence: Record<string, unknown> = { fixture: "bundled synthetic snapshot", physical_host_qualified: false };
  const foreign: string[] = [];
  const pageErrors: string[] = [];
  const serverErrors: string[] = [];
  let nativeDownloads = 0;
  let actor: Page | null = null;
  context.on("request", (request) => {
    const url = new URL(request.url());
    if ((url.protocol === "http:" || url.protocol === "https:") && url.origin !== REAL_ORIGIN) {
      foreign.push(`${url.origin}${url.pathname}`);
    }
  });
  const observedPages = new WeakSet<Page>();
  const observePage = (observed: Page): void => {
    if (observedPages.has(observed)) return;
    observedPages.add(observed);
    observed.on("pageerror", (error) => pageErrors.push(error.message));
    observed.on("websocket", (socket) => {
      const url = new URL(socket.url());
      if (url.origin.replace(/^ws/, "http") !== REAL_ORIGIN) {
        foreign.push(`${url.origin}${url.pathname}`);
      }
    });
  };
  context.on("page", observePage);
  context.pages().forEach(observePage);
  page.on("download", () => nativeDownloads++);
  context.on("response", (response) => {
    const url = new URL(response.url());
    if (url.origin === REAL_ORIGIN && url.pathname.startsWith("/api/") && response.status() >= 500) {
      serverErrors.push(`${response.status()} ${response.request().method()} ${url.pathname}`);
    }
  });
  try {
    await page.goto("/campaigns");
    await page.getByRole("button", { name: /New campaign$/ }).click();
    await page.getByLabel("Name", { exact: true }).fill("Saved-plan real UI qualification");
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await page.waitForURL(/\/campaigns\/\d+$/);
    const campaignId = Number(new URL(page.url()).pathname.split("/").pop());
    expect(Number.isSafeInteger(campaignId)).toBe(true);
    const uploadPanel = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Add a wave", exact: true }) });
    await uploadPanel.getByLabel("Snapshot file (.json from the engine)", { exact: true }).setInputFiles(SAMPLE);
    await uploadPanel.getByLabel("Label (optional)", { exact: true }).fill("Synthetic saved-plan baseline");
    const uploaded = page.waitForResponse((response) => response.request().method() === "POST"
      && new URL(response.url()).pathname === `/api/campaigns/${campaignId}/snapshots`);
    await uploadPanel.getByRole("button", { name: "Upload snapshot", exact: true }).click();
    const uploadResponse = await uploaded;
    expect(uploadResponse.status()).toBe(201);
    const snapshotId = (await uploadResponse.json() as { id: number }).id;
    // Ordinary snapshot upload refreshes the wave roster; unlike engine ingestion it does not
    // navigate automatically. Follow the operator-visible link and bind it to the returned ID.
    const uploadedSnapshot = page.getByRole("link", { name: /Synthetic saved-plan baseline/ });
    await expect(uploadedSnapshot).toHaveCount(1);
    await expect(uploadedSnapshot).toBeVisible();
    await expect(uploadedSnapshot).toHaveAttribute("href", `/snapshots/${snapshotId}`);
    await uploadedSnapshot.click();
    await page.waitForURL(new RegExp(`/snapshots/${snapshotId}$`));
    await expect(page.getByRole("heading", { name: `Snapshot ${snapshotId}`, level: 1, exact: true })).toBeVisible();
    const original = await rawAssessment(page, snapshotId);
    evidence.assessment = { snapshot_id: snapshotId, campaign_id: campaignId, bytes: original.length, sha256: hash(original) };
    await page.getByRole("link", { name: "Saved plans · MOP / NRFU", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Saved plans and downloads", level: 1, exact: true })).toBeVisible();
    await expect(page.getByText("No saved plan revisions yet.", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Download MOP", exact: true })).toBeDisabled();
    await page.setViewportSize({ width: 728, height: 1024 });
    const planName = page.getByLabel("Plan name", { exact: true });
    await expect(planName).toBeEnabled();
    await planName.focus();
    await expect(planName).toBeFocused();
    await planName.press("Tab");
    await expect(page.getByLabel("Availability tier", { exact: true })).toBeFocused();
    const first = await saveRevision(page, snapshotId, "UI qualification ACI plan", "aci");
    expect(first.assessment.sha256).toBe("sha256:" + hash(original));
    await expectSavedView(page, first);
    await page.reload();
    await expectSavedView(page, first);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
      "Saved plan controls and long identities must fit the 728px field viewport").toBe(true);
    const documents = [await downloadDocument(page, testInfo, snapshotId, first, "mop"),
      await downloadDocument(page, testInfo, snapshotId, first, "nrfu")];
    expect(documents[0].sha256).not.toBe(documents[1].sha256);
    const downloadedBeforeDirty = nativeDownloads;
    await page.getByLabel("Plan name", { exact: true }).fill("Unsaved operator edits");
    await expect(page.getByRole("status").filter({ hasText: "Unsaved changes." })).toBeVisible();
    await expect(page.getByRole("button", { name: "Download MOP", exact: true })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Download NRFU", exact: true })).toBeDisabled();
    expect(nativeDownloads).toBe(downloadedBeforeDirty);
    await page.getByRole("button", { name: "Discard changes", exact: true }).click();
    await expectSavedView(page, first);
    const second = await saveRevision(page, snapshotId, "UI qualification EVPN plan", "nxos-evpn");
    expect(second.revision).toBeGreaterThan(first.revision);
    expect(second.sha256).not.toBe(first.sha256);
    expect(second.selection_id).toBeGreaterThan(first.selection_id);
    await expectSavedView(page, second);

    actor = await context.newPage();
    await actor.goto(`/snapshots/${snapshotId}/plans`);
    await expectSavedView(actor, second);
    const changed = actor.waitForResponse((response) => response.request().method() === "POST"
      && new URL(response.url()).pathname === `/api/snapshots/${snapshotId}/plans/${first.revision}/select`);
    await actor.getByRole("button", { name: `Select revision ${first.revision}`, exact: true }).click();
    const changedResponse = await changed;
    expect(changedResponse.status()).toBe(200);
    const selected = await changedResponse.json() as SavedPlanRecord;
    expect(selected.sha256).toBe(first.sha256);
    expect(selected.selection_id).toBeGreaterThan(second.selection_id);
    await expectSavedView(actor, selected);
    await expect(page.getByLabel("Plan name", { exact: true })).toHaveValue(second.label);
    const downloadsBeforeConflict = nativeDownloads;
    const refused = page.waitForResponse((response) => response.request().method() === "GET"
      && new URL(response.url()).pathname === `/api/snapshots/${snapshotId}/plans/${second.revision}/deliverable/mop`);
    await page.getByRole("button", { name: "Download MOP", exact: true }).click();
    expect((await refused).status()).toBe(409);
    await expect(page.getByRole("alert")).toContainText("Selection needs reloading.");
    await expect(page.getByRole("button", { name: "Download MOP", exact: true })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Download NRFU", exact: true })).toBeDisabled();
    await expect(page.getByLabel("Plan name", { exact: true })).toHaveValue(second.label);
    expect(nativeDownloads, "A stale export must not create a native download or silently use the latest plan").toBe(downloadsBeforeConflict);
    await page.getByRole("button", { name: "Reload saved plans", exact: true }).click();
    await expectSavedView(page, selected);
    documents.push(await downloadDocument(page, testInfo, snapshotId, selected, "mop"));
    const after = await rawAssessment(page, snapshotId);
    expect(after.equals(original), "Saving/selecting/exporting must retain exact original assessment bytes").toBe(true);
    const state = await page.evaluate(async (id) => {
      const response = await fetch(`/api/snapshots/${id}/plans`);
      if (!response.ok) throw new Error(`Plan state read failed: ${response.status}`);
      return response.json();
    }, snapshotId) as SavedPlanState;
    expect(state.revisions.map((row) => row.revision)).toEqual([first.revision, second.revision]);
    expect(state.selected_revision).toBe(first.revision);
    expect(state.selection_id).toBe(selected.selection_id);
    expect(foreign, "No core workflow request may leave the local test origin").toEqual([]);
    expect(pageErrors, "No uncaught browser error may accompany the supported journey").toEqual([]);
    expect(serverErrors, "No real API 5xx may accompany the supported journey").toEqual([]);
    evidence.plans = [first, second].map((plan) => ({ revision: plan.revision, sha256: plan.sha256,
      selection_id: plan.selection_id, fabric: plan.projection.requirements.fabric_operating_model, convergence_budget_ms: 0 }));
    evidence.final_selection = { revision: selected.revision, sha256: selected.sha256, selection_id: selected.selection_id };
    evidence.documents = documents;
    evidence.original_bytes_unchanged = true;
    evidence.stale_export_status = 409;
    evidence.foreign_origin_requests = foreign;
    evidence.viewport = { width: 728, height: 1024 };
  } finally {
    await actor?.close();
    evidence.page_errors = pageErrors;
    evidence.server_errors = serverErrors;
    evidence.foreign_origin_requests = foreign;
    await testInfo.attach("saved-plan-local-browser-evidence", {
      body: JSON.stringify(evidence, null, 2), contentType: "application/json",
    });
  }
});
