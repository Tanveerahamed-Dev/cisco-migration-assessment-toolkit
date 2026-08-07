import assert from "node:assert/strict";
import { gzipSync } from "node:zlib";
import { readFile, readdir } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const root = new URL("../", import.meta.url);
const workerUrl = new URL("../dist/server/index.js", import.meta.url);
workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
const { default: worker } = await import(workerUrl.href);

async function render(path = "/") {
  return worker.fetch(
    new Request(`http://localhost${path}`, { headers: { accept: "text/html" } }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

async function sourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) files.push(...(await sourceFiles(path)));
    else files.push(path);
  }
  return files;
}

test("hardens every HTML response at the Worker boundary", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
  assert.equal(response.headers.get("x-content-type-options"), "nosniff");
  assert.equal(response.headers.get("x-frame-options"), "DENY");
  assert.equal(response.headers.get("referrer-policy"), "no-referrer");
  assert.equal(response.headers.get("cross-origin-opener-policy"), "same-origin");
  assert.equal(response.headers.get("cross-origin-resource-policy"), "same-origin");
  assert.match(response.headers.get("permissions-policy") ?? "", /camera=\(\)/);
  assert.match(response.headers.get("content-security-policy") ?? "", /connect-src 'none'/);
  assert.match(response.headers.get("content-security-policy") ?? "", /form-action 'self'/);
  assert.match(response.headers.get("content-security-policy") ?? "", /frame-ancestors 'none'/);
  assert.match(response.headers.get("cache-control") ?? "", /no-store/);

  const projectionResponse = await worker.fetch(
    new Request("http://localhost/atlas-projection/index.mjs"),
    { ASSETS: { fetch: async () => new Response("missing", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
  assert.match(projectionResponse.headers.get("cache-control") ?? "", /no-store/);
});

test("server-renders every owner workspace with its proof boundary", async () => {
  const expectations = new Map([
    ["/", ["See the whole system", "Nine outcomes hold the project together", "Coverage debt has different meanings"]],
    ["/system", ["Living system map", "Eight traffic lenses keep different proofs separate", "Declared dependency directions"]],
    ["/graph", ["Complete static graph", "Keep every safe node and edge", "Loading complete safe graph projection"]],
    ["/capabilities", ["Every declared capability has a state", "capability records", "Current bounded scope"]],
    ["/gaps", ["Choose with the uncertainty visible", "Owner decision queue", "Open Horizon Register"]],
    ["/labs", ["Learn the boundary without crossing it", "Fourteen deterministic labs", "Never mutates truth"]],
    ["/ask?q=stateful+traffic", ["Answers must show their records", "Deterministic answer", "cited records"]],
    ["/ask?target=gap.flow-stateful", ["Deterministic enhancement compiler", "Do nothing", "Rollback and kill criteria"]],
    ["/exports", ["One manifest. Every output reconciled", "Mandatory output family", "Publication is deliberately separate"]],
    ["/source", ["Find any tracked path", "Opening the source-bound projection", "File text remains in per-file lazy modules"]],
  ]);

  for (const [path, phrases] of expectations) {
    const response = await render(path);
    assert.equal(response.status, 200, path);
    const html = await response.text();
    assert.match(html, /<main\b[^>]*id="atlas-content"/i, path);
    assert.match(html, /No analytics/i, path);
    for (const phrase of phrases) assert.ok(html.includes(phrase), `${path} is missing: ${phrase}`);
    assert.doesNotMatch(html, /Starter Project|SkeletonPreview|taking shape/i, path);
  }
});

test("keeps the landing payload within the declared performance envelope", async () => {
  const response = await render();
  const html = await response.text();
  assert.ok(gzipSync(html).byteLength <= 35 * 1024, "landing HTML exceeds 35 KiB gzip");
  assert.doesNotMatch(html, /sourceLoaders|atlas-projection\/source\//);

  const assetPaths = [...html.matchAll(/(?:src|href)="([^"?#]+\.(?:js|css))(?:[?#][^"]*)?"/g)]
    .map((match) => match[1])
    .filter((path) => path.startsWith("/assets/"));
  const unique = [...new Set(assetPaths)];
  let scripts = 0;
  let styles = 0;
  for (const path of unique) {
    const bytes = await readFile(new URL(`../dist/client${path}`, import.meta.url));
    if (path.endsWith(".js")) scripts += gzipSync(bytes).byteLength;
    if (path.endsWith(".css")) styles += gzipSync(bytes).byteLength;
  }
  assert.ok(scripts <= 120 * 1024, `initial JS is ${scripts} bytes gzip`);
  assert.ok(styles <= 20 * 1024, `initial CSS is ${styles} bytes gzip`);
});

test("keeps runtime local, read-only, private, and dependency-light", async () => {
  const appDirectory = fileURLToPath(new URL("../app/", import.meta.url));
  const appPaths = await sourceFiles(appDirectory);
  const appSource = (
    await Promise.all(
      appPaths
        .filter((path) => /\.(?:ts|tsx|css)$/.test(path))
        .map((path) => readFile(path, "utf8")),
    )
  ).join("\n");
  const [layout, workerSource, packageText, publicEntries, socialCard] = await Promise.all([
    readFile(new URL("app/layout.tsx", root), "utf8"),
    readFile(new URL("worker/index.ts", root), "utf8"),
    readFile(new URL("package.json", root), "utf8"),
    readdir(new URL("public/", root), { withFileTypes: true }),
    readFile(new URL("public/atlas-social-card.png", root)),
  ]);
  const packageData = JSON.parse(packageText);

  assert.deepEqual(Object.keys(packageData.dependencies).sort(), ["next", "react", "react-dom"]);
  assert.equal(packageData.private, true);
  assert.match(layout, /index:\s*false/);
  assert.match(layout, /follow:\s*false/);
  assert.match(appSource, /prefers-reduced-motion/);
  assert.match(appSource, /prefers-color-scheme:\s*light/);
  assert.doesNotMatch(
    appSource,
    /\bfetch\s*\(|XMLHttpRequest|WebSocket|localStorage|sessionStorage|document\.cookie/,
  );
  assert.doesNotMatch(workerSource, /D1Database|handleImageOptimization/);
  assert.doesNotMatch(packageText, /drizzle|tailwind|react-loading-skeleton|analytics/i);

  const names = publicEntries.map((entry) => entry.name).sort();
  assert.ok(names.includes("favicon.svg"));
  assert.ok(names.includes("og.png"));
  assert.ok(names.includes("atlas-social-card.png"));
  assert.ok(names.every((name) => ["atlas-projection", "atlas-social-card.png", "favicon.svg", "og.png"].includes(name)));
  assert.equal(socialCard.subarray(1, 4).toString("ascii"), "PNG");
  const width = socialCard.readUInt32BE(16);
  const height = socialCard.readUInt32BE(20);
  assert.ok(width >= 1200 && height >= 630, `social card too small: ${width}x${height}`);
  assert.ok(width / height >= 1.85 && width / height <= 1.95, `unexpected social-card ratio: ${width}x${height}`);
});

test("renders deterministic catalogs and never promotes advisory content", async () => {
  const [catalogText, governanceText, horizonText] = await Promise.all([
    readFile(new URL("content/capability-catalog.json", root), "utf8"),
    readFile(new URL("content/delivery-governance.json", root), "utf8"),
    readFile(new URL("content/open-horizon-register.json", root), "utf8"),
  ]);
  const catalog = JSON.parse(catalogText);
  const governance = JSON.parse(governanceText);
  const horizon = JSON.parse(horizonText);
  const capabilities = catalog.domains.flatMap((domain) => domain.entries);

  assert.equal(capabilities.length, 189);
  assert.equal(governance.gaps.length, 41);
  assert.equal(governance.decision_queue.length, 10);
  assert.equal(governance.labs.length, 14);
  assert.equal(horizon.signals.length, 16);
  assert.ok(horizon.signals.every((signal) => signal.content_role === "advisory"));
  assert.ok(horizon.signals.every((signal) => signal.support_claim === "none"));
});
