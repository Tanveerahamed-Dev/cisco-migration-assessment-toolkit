import assert from "node:assert/strict";
import { gunzipSync, gzipSync } from "node:zlib";
import { mkdtemp, mkdir, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { Miniflare } from "miniflare";

import { CANONICAL_GZIP_HEADER_BYTES } from "../build/gzip-contract.js";

const root = new URL("../", import.meta.url);
const workerUrl = new URL("../dist/server/index.js", import.meta.url);
workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
const { default: worker } = await import(workerUrl.href);

function canonicalGzip(source) {
  const encoded = gzipSync(source, { level: 9 });
  Buffer.from(CANONICAL_GZIP_HEADER_BYTES).copy(encoded, 0);
  return encoded;
}

function noncanonicalGzip(source) {
  const encoded = canonicalGzip(source);
  encoded[CANONICAL_GZIP_HEADER_BYTES.length - 1] = 0x00;
  return encoded;
}

function byteStream(chunks) {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
  });
}

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

async function miniflareWithAssets(directory) {
  const serverRoot = fileURLToPath(new URL("../dist/server/", import.meta.url));
  const entry = join(serverRoot, "index.js");
  const serverModules = (await sourceFiles(serverRoot))
    .filter((path) => path.endsWith(".js"))
    .sort();
  return new Miniflare({
    modulesRoot: serverRoot,
    modules: [entry, ...serverModules.filter((path) => path !== entry)].map((path) => ({
      type: "ESModule",
      path,
    })),
    unsafeDevRegistry: false,
    compatibilityDate: "2026-08-01",
    compatibilityFlags: ["nodejs_compat"],
    assets: {
      directory,
      binding: "ASSETS",
      routerConfig: {
        invoke_user_worker_ahead_of_assets: false,
        has_user_worker: true,
      },
    },
  });
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
  assert.equal(projectionResponse.status, 404);
  assert.match(projectionResponse.headers.get("content-type") ?? "", /^text\/plain\b/i);
  assert.match(projectionResponse.headers.get("cache-control") ?? "", /no-store/);
});

test("renders normal routes when the local production adapter omits Worker bindings", async () => {
  const response = await worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    undefined,
    { waitUntil() {}, passThroughOnException() {} },
  );
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
  assert.match(await response.text(), /Master Reference/);
});

test("fails closed for unavailable or invalid projection module assets", async (context) => {
  const workerContext = { waitUntil() {}, passThroughOnException() {} };
  const diagnostics = [];
  context.mock.method(console, "error", (message) => diagnostics.push(String(message)));
  const cases = [
    {
      name: "missing binding",
      request: new Request("http://localhost/atlas-projection/identity.mjs"),
      env: undefined,
      status: 503,
      code: "binding_unavailable",
    },
    {
      name: "unsupported method",
      request: new Request("http://localhost/atlas-projection/identity.mjs", { method: "POST" }),
      env: { ASSETS: { fetch: async () => new Response(null, { status: 204 }) } },
      status: 405,
      code: "method_not_allowed",
    },
    {
      name: "missing member",
      request: new Request("http://localhost/atlas-projection/identity.mjs"),
      env: { ASSETS: { fetch: async () => new Response("missing", { status: 404 }) } },
      status: 404,
      code: "asset_not_found",
    },
    {
      name: "upstream failure",
      request: new Request("http://localhost/atlas-projection/identity.mjs"),
      env: { ASSETS: { fetch: async () => new Response("failed", { status: 500 }) } },
      status: 502,
      code: "asset_status_invalid",
    },
    {
      name: "empty success",
      request: new Request("http://localhost/atlas-projection/identity.mjs"),
      env: { ASSETS: { fetch: async () => new Response(null, { status: 204 }) } },
      status: 502,
      code: "asset_status_invalid",
    },
    {
      name: "bodyless 200",
      request: new Request("http://localhost/atlas-projection/identity.mjs"),
      env: {
        ASSETS: {
          fetch: async () => new Response(null, {
            headers: {
              "content-encoding": "gzip",
              "content-type": "text/javascript; charset=utf-8",
            },
          }),
        },
      },
      status: 502,
      code: "asset_body_missing",
    },
    {
      name: "lookup exception",
      request: new Request(
        "http://localhost/atlas-projection/identity.mjs?diagnostic=private-query-value",
      ),
      env: { ASSETS: { fetch: async () => { throw new Error("asset binding failed"); } } },
      status: 502,
      code: "asset_lookup_exception",
    },
    {
      name: "upstream HTML fallback",
      request: new Request("http://localhost/atlas-projection/identity.mjs"),
      env: {
        ASSETS: {
          fetch: async () => new Response("<html></html>", { headers: { "content-type": "text/html" } }),
        },
      },
      status: 502,
      code: "asset_metadata_invalid",
    },
    {
      name: "misleading gzip MIME suffix",
      request: new Request("http://localhost/atlas-projection/identity.mjs"),
      env: {
        ASSETS: {
          fetch: async () => new Response("not gzip", {
            headers: {
              "content-encoding": "gzip",
              "content-type": "application/gzip+json",
            },
          }),
        },
      },
      status: 502,
      code: "asset_metadata_invalid",
    },
    {
      name: "unexpected upstream encoding",
      request: new Request("http://localhost/atlas-projection/identity.mjs"),
      env: {
        ASSETS: {
          fetch: async () => new Response("encoded", {
            headers: { "content-encoding": "br", "content-type": "application/gzip" },
          }),
        },
      },
      status: 502,
      code: "asset_metadata_invalid",
    },
    {
      name: "multiple upstream encodings",
      request: new Request("http://localhost/atlas-projection/identity.mjs"),
      env: {
        ASSETS: {
          fetch: async () => new Response("encoded", {
            headers: {
              "content-encoding": "gzip, br",
              "content-type": "application/gzip",
            },
          }),
        },
      },
      status: 502,
      code: "asset_metadata_invalid",
    },
    {
      name: "gzip-encoded HTML fallback",
      request: new Request("http://localhost/atlas-projection/identity.mjs"),
      env: {
        ASSETS: {
          fetch: async () => new Response("encoded HTML", {
            headers: { "content-encoding": "gzip", "content-type": "text/html" },
          }),
        },
      },
      status: 502,
      code: "asset_metadata_invalid",
    },
    {
      name: "JavaScript MIME without gzip encoding",
      request: new Request("http://localhost/atlas-projection/identity.mjs"),
      env: {
        ASSETS: {
          fetch: async () => new Response("not gzip", {
            headers: { "content-type": "text/javascript" },
          }),
        },
      },
      status: 502,
      code: "asset_representation_invalid",
    },
    {
      name: "encoded MIME with a noncanonical gzip header",
      request: new Request("http://localhost/atlas-projection/identity.mjs"),
      env: {
        ASSETS: {
          fetch: async () => new Response(noncanonicalGzip(Buffer.from("not canonical")), {
            headers: { "content-type": "application/gzip" },
          }),
        },
      },
      status: 502,
      code: "asset_representation_invalid",
    },
    {
      name: "encoded MIME with plaintext body",
      request: new Request("http://localhost/atlas-projection/identity.mjs"),
      env: {
        ASSETS: {
          fetch: async () => new Response("not gzip", {
            headers: { "content-type": "application/gzip" },
          }),
        },
      },
      status: 502,
      code: "asset_representation_invalid",
    },
    {
      name: "short gzip representation",
      request: new Request("http://localhost/atlas-projection/identity.mjs"),
      env: {
        ASSETS: {
          fetch: async () => new Response(Uint8Array.from([0x1f, 0x8b, 0x08]), {
            headers: { "content-type": "application/gzip" },
          }),
        },
      },
      status: 502,
      code: "asset_representation_invalid",
    },
    {
      name: "projection body read failure",
      request: new Request("http://localhost/atlas-projection/identity.mjs"),
      env: {
        ASSETS: {
          fetch: async () => new Response(new ReadableStream({
            pull() {
              throw new Error("private stream failure");
            },
          }), { headers: { "content-type": "application/gzip" } }),
        },
      },
      status: 502,
      code: "asset_representation_invalid",
    },
    {
      name: "locked projection body",
      request: new Request("http://localhost/atlas-projection/identity.mjs"),
      env: {
        ASSETS: {
          fetch: async () => {
            const upstream = new Response(canonicalGzip(Buffer.from("locked")), {
              headers: { "content-type": "application/gzip" },
            });
            upstream.body.getReader();
            return upstream;
          },
        },
      },
      status: 502,
      code: "asset_representation_invalid",
    },
  ];

  for (const fixture of cases) {
    await context.test(fixture.name, async () => {
      const response = await worker.fetch(fixture.request, fixture.env, workerContext);
      assert.equal(response.status, fixture.status);
      assert.match(response.headers.get("content-type") ?? "", /^text\/plain\b/i);
      assert.match(response.headers.get("cache-control") ?? "", /no-store/);
      assert.equal(response.headers.get("x-content-type-options"), "nosniff");
      assert.equal(response.headers.get("x-atlas-projection-error"), fixture.code);
      if (fixture.status === 405) assert.equal(response.headers.get("allow"), "GET, HEAD");
    });
  }
  const expectedDiagnostics = cases.filter((fixture) => fixture.status === 502);
  assert.equal(diagnostics.length, expectedDiagnostics.length);
  for (const fixture of expectedDiagnostics) {
    assert.ok(
      diagnostics.some((message) =>
        message.startsWith("atlas_projection_rejected ") &&
        message.includes(`"code":"${fixture.code}"`)),
      `missing safe diagnostic for ${fixture.name}`,
    );
  }
  const joinedDiagnostics = diagnostics.join("\n");
  for (const forbidden of [
    "asset binding failed",
    "private-query-value",
    "http://localhost",
    "application/gzip+json",
    "gzip, br",
    "encoded HTML",
    "not gzip",
    "private stream failure",
    "ReadableStream is locked",
  ]) {
    assert.ok(!joinedDiagnostics.includes(forbidden), `diagnostic leaked ${forbidden}`);
  }
});

test("serves every virtual projection module from its exact gzip asset", async () => {
  const source = Buffer.from("export const exact = 'source-bound';\n", "utf8");
  const encoded = canonicalGzip(source);
  let requestedPath = "";
  const response = await worker.fetch(
    new Request("http://localhost/atlas-projection/identity.mjs"),
    {
      ASSETS: {
        fetch: async (request) => {
          requestedPath = new URL(request.url).pathname;
          return new Response(encoded, {
            headers: {
              "content-length": String(encoded.byteLength),
              "content-type": "application/gzip",
            },
          });
        },
      },
    },
    { waitUntil() {}, passThroughOnException() {} },
  );

  assert.equal(requestedPath, "/atlas-projection/identity.mjs.gz");
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("content-encoding"), "gzip");
  assert.match(response.headers.get("content-type") ?? "", /^text\/javascript\b/i);
  assert.equal(response.headers.get("vary"), "Accept-Encoding");
  assert.match(response.headers.get("cache-control") ?? "", /no-store/);
  assert.deepEqual(gunzipSync(Buffer.from(await response.arrayBuffer())), source);
});

test("accepts Sites-inferred JavaScript MIME only for canonical gzip bytes", async () => {
  const source = Buffer.from("export const exact = 'sites-inferred-source-bound';\n", "utf8");
  const encoded = canonicalGzip(source);
  const response = await worker.fetch(
    new Request("http://localhost/atlas-projection/identity.mjs"),
    {
      ASSETS: {
        fetch: async () => new Response(
          byteStream([...encoded].map((value) => Uint8Array.of(value))),
          {
            headers: {
              "content-length": String(encoded.byteLength),
              "content-type": "text/javascript; charset=utf-8",
            },
          },
        ),
      },
    },
    { waitUntil() {}, passThroughOnException() {} },
  );

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("content-encoding"), "gzip");
  assert.match(response.headers.get("content-type") ?? "", /^text\/javascript\b/i);
  assert.equal(response.headers.get("vary"), "Accept-Encoding");
  assert.match(response.headers.get("cache-control") ?? "", /no-store/);
  const replayed = Buffer.from(await response.arrayBuffer());
  assert.deepEqual(replayed, encoded);
  assert.deepEqual(gunzipSync(replayed), source);
});

test("sanitizes stream failures and cancellation after canonical-prefix acceptance", async () => {
  let deliveredPrefix = false;
  const failingResponse = await worker.fetch(
    new Request("http://localhost/atlas-projection/identity.mjs"),
    {
      ASSETS: {
        fetch: async () => new Response(new ReadableStream({
          pull(controller) {
            if (!deliveredPrefix) {
              deliveredPrefix = true;
              controller.enqueue(Uint8Array.from(CANONICAL_GZIP_HEADER_BYTES));
              return;
            }
            throw new Error("private downstream failure");
          },
        }), { headers: { "content-type": "application/gzip" } }),
      },
    },
    { waitUntil() {}, passThroughOnException() {} },
  );
  assert.equal(failingResponse.status, 200);
  await assert.rejects(
    failingResponse.arrayBuffer(),
    (error) => {
      assert.equal(error.message, "Atlas projection stream failed");
      assert.ok(!String(error).includes("private downstream failure"));
      return true;
    },
  );

  let upstreamCancelReason = "not-called";
  let deliveredCancellationPrefix = false;
  const cancellableResponse = await worker.fetch(
    new Request("http://localhost/atlas-projection/identity.mjs"),
    {
      ASSETS: {
        fetch: async () => new Response(new ReadableStream({
          pull(controller) {
            if (!deliveredCancellationPrefix) {
              deliveredCancellationPrefix = true;
              controller.enqueue(Uint8Array.from(CANONICAL_GZIP_HEADER_BYTES));
            }
          },
          cancel(reason) {
            upstreamCancelReason = reason;
            throw new Error("private cancellation failure");
          },
        }), { headers: { "content-type": "application/gzip" } }),
      },
    },
    { waitUntil() {}, passThroughOnException() {} },
  );
  assert.equal(cancellableResponse.status, 200);
  await cancellableResponse.body.cancel("private downstream reason");
  assert.equal(upstreamCancelReason, undefined);
});

test("accepts Sites metadata for already gzip-encoded projection assets", async () => {
  const source = Buffer.from("export const exact = 'sites-source-bound';\n", "utf8");
  const encoded = gzipSync(source, { level: 9 });
  for (const contentType of [
    "application/gzip",
    "application/x-gzip",
    "application/octet-stream",
    "text/javascript; charset=utf-8",
    "application/javascript",
  ]) {
    const response = await worker.fetch(
      new Request("http://localhost/atlas-projection/identity.mjs"),
      {
        ASSETS: {
          fetch: async () => new Response(encoded, {
            headers: {
              "content-encoding": "gzip",
              "content-length": String(encoded.byteLength),
              "content-type": contentType,
            },
          }),
        },
      },
      { waitUntil() {}, passThroughOnException() {} },
    );

    assert.equal(response.status, 200);
    assert.equal(response.headers.get("content-encoding"), "gzip");
    assert.match(response.headers.get("content-type") ?? "", /^text\/javascript\b/i);
    assert.equal(response.headers.get("vary"), "Accept-Encoding");
    assert.match(response.headers.get("cache-control") ?? "", /no-store/);
    assert.deepEqual(gunzipSync(Buffer.from(await response.arrayBuffer())), source);
  }
});

test("preserves fail-closed HEAD semantics for projection modules", async (context) => {
  const diagnostics = [];
  context.mock.method(console, "error", (message) => diagnostics.push(String(message)));
  let upstreamMethod = "";
  const success = await worker.fetch(
    new Request("http://localhost/atlas-projection/identity.mjs", { method: "HEAD" }),
    {
      ASSETS: {
        fetch: async (request) => {
          upstreamMethod = request.method;
          return new Response(null, {
            headers: {
              "content-encoding": "gzip",
              "content-length": "47",
              "content-type": "text/javascript; charset=utf-8",
            },
          });
        },
      },
    },
    { waitUntil() {}, passThroughOnException() {} },
  );
  assert.equal(upstreamMethod, "HEAD");
  assert.equal(success.status, 200);
  assert.equal(success.headers.get("content-encoding"), "gzip");
  assert.match(success.headers.get("content-type") ?? "", /^text\/javascript\b/i);
  assert.equal(success.headers.get("vary"), "Accept-Encoding");
  assert.match(success.headers.get("cache-control") ?? "", /no-store/);
  assert.equal(success.headers.get("x-content-type-options"), "nosniff");
  assert.equal((await success.arrayBuffer()).byteLength, 0);

  const encodedMimeWithoutEncoding = await worker.fetch(
    new Request("http://localhost/atlas-projection/identity.mjs", { method: "HEAD" }),
    {
      ASSETS: {
        fetch: async () => new Response(null, {
          headers: {
            "content-length": "47",
            "content-type": "application/gzip",
          },
        }),
      },
    },
    { waitUntil() {}, passThroughOnException() {} },
  );
  assert.equal(encodedMimeWithoutEncoding.status, 200);
  assert.equal(encodedMimeWithoutEncoding.headers.get("content-encoding"), "gzip");
  assert.equal((await encodedMimeWithoutEncoding.arrayBuffer()).byteLength, 0);

  const ambiguousJavaScript = await worker.fetch(
    new Request("http://localhost/atlas-projection/identity.mjs", { method: "HEAD" }),
    {
      ASSETS: {
        fetch: async () => new Response(null, {
          headers: {
            "content-length": "47",
            "content-type": "text/javascript; charset=utf-8",
          },
        }),
      },
    },
    { waitUntil() {}, passThroughOnException() {} },
  );
  assert.equal(ambiguousJavaScript.status, 502);
  assert.equal(
    ambiguousJavaScript.headers.get("x-atlas-projection-error"),
    "asset_metadata_invalid",
  );
  assert.equal((await ambiguousJavaScript.arrayBuffer()).byteLength, 0);
  assert.equal(diagnostics.length, 1);
  assert.match(diagnostics[0], /"code":"asset_metadata_invalid"/);
  assert.match(diagnostics[0], /"contentEncoding":"missing"/);
  assert.match(diagnostics[0], /"contentType":"javascript"/);

  const unavailable = await worker.fetch(
    new Request("http://localhost/atlas-projection/identity.mjs", { method: "HEAD" }),
    undefined,
    { waitUntil() {}, passThroughOnException() {} },
  );
  assert.equal(unavailable.status, 503);
  assert.equal((await unavailable.arrayBuffer()).byteLength, 0);
  assert.match(unavailable.headers.get("cache-control") ?? "", /no-store/);
});

test("serves projection gzip as browser-decodable JavaScript through Workerd", async () => {
  const scratch = await mkdtemp(join(tmpdir(), "atlas-worker-compression-"));
  let miniflare;
  try {
    const projection = join(scratch, "atlas-projection");
    await mkdir(projection, { recursive: true });
    const source = await readFile(new URL("../public/atlas-projection/identity.mjs", import.meta.url));
    const encoded = canonicalGzip(source);
    await writeFile(join(projection, "identity.mjs.gz"), encoded);
    const deployableHeaders = await readFile(new URL("../dist/client/_headers", import.meta.url));
    const trackedHeaders = await readFile(new URL("../public/_headers", import.meta.url));
    assert.equal(
      trackedHeaders.toString("utf8"),
      [
        "# Cache content-hashed application assets immutably.",
        "/assets/*",
        "  Cache-Control: public, max-age=31536000, immutable",
        "",
        "# Preserve the exact precompressed projection representation through ASSETS.",
        "/atlas-projection/*.mjs.gz",
        "  ! Content-Encoding",
        "  Cache-Control: private, no-cache, no-store, must-revalidate",
        "  Content-Type: application/gzip",
        "  Cross-Origin-Resource-Policy: same-origin",
        "  X-Content-Type-Options: nosniff",
        "",
      ].join("\n"),
    );
    assert.deepEqual(deployableHeaders, trackedHeaders);
    await writeFile(join(scratch, "_headers"), deployableHeaders);

    miniflare = await miniflareWithAssets(scratch);

    const physical = await miniflare.dispatchFetch(
      "http://localhost/atlas-projection/identity.mjs.gz",
      { headers: { "Accept-Encoding": "gzip" } },
    );
    assert.equal(physical.status, 200);
    assert.match(physical.headers.get("content-type") ?? "", /^application\/gzip\b/i);
    assert.equal(physical.headers.get("content-encoding"), null);
    assert.equal(physical.headers.get("mf-content-encoding"), null);
    assert.match(physical.headers.get("cache-control") ?? "", /no-store/);
    assert.equal(physical.headers.get("cross-origin-resource-policy"), "same-origin");
    assert.equal(physical.headers.get("x-content-type-options"), "nosniff");
    assert.deepEqual(Buffer.from(await physical.arrayBuffer()), encoded);

    const response = await miniflare.dispatchFetch(
      "http://localhost/atlas-projection/identity.mjs",
      { headers: { "Accept-Encoding": "gzip" } },
    );
    assert.equal(response.status, 200);
    assert.match(response.headers.get("content-type") ?? "", /^text\/javascript\b/i);
    assert.equal(
      response.headers.get("content-encoding") ?? response.headers.get("mf-content-encoding"),
      "gzip",
    );
    assert.equal(response.headers.get("vary"), "Accept-Encoding");
    assert.match(response.headers.get("cache-control") ?? "", /no-store/);
    const decoded = Buffer.from(await response.arrayBuffer());
    assert.deepEqual(decoded, source);
    const loaded = await import(`data:text/javascript;base64,${decoded.toString("base64")}`);
    assert.equal(loaded.identity.status, "complete");
    assert.equal(loaded.identity.releaseClass, "exact_commit");
  } finally {
    if (miniflare) await miniflare.dispose();
    await rm(scratch, { recursive: true, force: true });
  }
});

test("serves the exact live Sites-inferred metadata tuple through Workerd", async () => {
  const scratch = await mkdtemp(join(tmpdir(), "atlas-worker-sites-metadata-"));
  let miniflare;
  try {
    const projection = join(scratch, "atlas-projection");
    await mkdir(projection, { recursive: true });
    const source = await readFile(new URL("../public/atlas-projection/identity.mjs", import.meta.url));
    const encoded = canonicalGzip(source);
    await writeFile(join(projection, "identity.mjs.gz"), encoded);
    await writeFile(
      join(scratch, "_headers"),
      [
        "/atlas-projection/*.mjs.gz",
        "  ! Content-Encoding",
        "  Cache-Control: private, no-cache, no-store, must-revalidate",
        "  Content-Type: text/javascript; charset=utf-8",
        "  Cross-Origin-Resource-Policy: same-origin",
        "  X-Content-Type-Options: nosniff",
        "",
      ].join("\n"),
    );
    miniflare = await miniflareWithAssets(scratch);

    const physical = await miniflare.dispatchFetch(
      "http://localhost/atlas-projection/identity.mjs.gz",
      { headers: { "Accept-Encoding": "gzip" } },
    );
    assert.equal(physical.status, 200);
    assert.match(physical.headers.get("content-type") ?? "", /^text\/javascript\b/i);
    assert.equal(physical.headers.get("content-encoding"), null);
    assert.equal(physical.headers.get("mf-content-encoding"), "gzip");
    assert.deepEqual(Buffer.from(await physical.arrayBuffer()), encoded);

    const response = await miniflare.dispatchFetch(
      "http://localhost/atlas-projection/identity.mjs",
      { headers: { "Accept-Encoding": "gzip" } },
    );
    assert.equal(response.status, 200);
    assert.match(response.headers.get("content-type") ?? "", /^text\/javascript\b/i);
    assert.equal(
      response.headers.get("content-encoding") ?? response.headers.get("mf-content-encoding"),
      "gzip",
    );
    assert.equal(response.headers.get("vary"), "Accept-Encoding");
    assert.match(response.headers.get("cache-control") ?? "", /no-store/);
    const decoded = Buffer.from(await response.arrayBuffer());
    assert.deepEqual(decoded, source);
    const loaded = await import(`data:text/javascript;base64,${decoded.toString("base64")}`);
    assert.equal(loaded.identity.status, "complete");
    assert.equal(loaded.identity.releaseClass, "exact_commit");
  } finally {
    if (miniflare) await miniflare.dispose();
    await rm(scratch, { recursive: true, force: true });
  }
});

test("keeps the complete compressed projection inside the Sites expanded limit", async () => {
  const distDirectory = fileURLToPath(new URL("../dist/", import.meta.url));
  const projectionDirectory = fileURLToPath(
    new URL("../dist/client/atlas-projection/", import.meta.url),
  );
  const [distPaths, projectionPaths, receiptText, projectionManifestText] = await Promise.all([
    sourceFiles(distDirectory),
    sourceFiles(projectionDirectory),
    readFile(join(projectionDirectory, "compression-manifest.json"), "utf8"),
    readFile(join(projectionDirectory, "projection-manifest.json"), "utf8"),
  ]);
  const receipt = JSON.parse(receiptText);
  const projectionManifest = JSON.parse(projectionManifestText);
  const compressed = projectionPaths.filter((path) => path.endsWith(".mjs.gz"));
  const originals = projectionPaths.filter((path) => path.endsWith(".mjs"));
  const sizes = await Promise.all(distPaths.map(async (path) => (await stat(path)).size));
  const expandedBytes = sizes.reduce((total, size) => total + size, 0);

  assert.equal(originals.length, 0, "deployable dist retained uncompressed projection modules");
  assert.equal(compressed.length, receipt.moduleCount);
  assert.equal(receipt.modules.length, receipt.moduleCount);
  assert.equal(receipt.sourceCommit, projectionManifest.sourceCommit);
  assert.equal(receipt.sourceTreeDigest, projectionManifest.sourceTreeDigest);
  assert.ok(receipt.originalBytes > receipt.compressedBytes);
  assert.ok(
    expandedBytes <= 248 * 1024 * 1024,
    `Sites expanded payload is ${(expandedBytes / 1024 / 1024).toFixed(1)} MiB`,
  );
});

test("server-renders every owner workspace with its proof boundary", async () => {
  const expectations = new Map([
    ["/", ["See the whole system", "Nine outcomes hold the project together", "Coverage debt has different meanings"]],
    ["/product", ["What Atlas is, what it protects", "Operating surfaces and deployment boundary", "White-label and product gap ledger"]],
    ["/system", ["Living system map", "Eight traffic lenses keep different proofs separate", "Declared dependency directions"]],
    ["/trace", ["Traverse the declared chain", "Trace builder", "Ordered source-bound thread"]],
    ["/trace?stage=not-real", ["Trace abstained: unknown stage", "No substitute relationship was inferred", "Ordered source-bound thread"]],
    ["/graph", ["Complete static graph", "Keep every safe node and edge", "Loading bounded graph overview"]],
    ["/capabilities", ["Every declared capability has a state", "capability records", "Current bounded scope"]],
    ["/gaps", ["Choose with the uncertainty visible", "Owner decision queue", "Open Horizon Register"]],
    ["/labs", ["Learn the boundary without crossing it", "Fourteen deterministic labs", "Never mutates truth"]],
    ["/knowledge", ["Knowledge may advise Atlas", "Source-of-truth and code-graph owners", "Vault and private-evidence boundary"]],
    ["/progress", ["Current state comes from owners", "P0 and P1 gap queue", "Semantic change delta unavailable"]],
    ["/ask?q=stateful+traffic", ["Answers must show their records", "Deterministic answer", "cited records"]],
    ["/ask?target=gap.flow-stateful", ["Deterministic enhancement compiler", "Do nothing", "Rollback and kill criteria"]],
    ["/exports", ["One manifest. Every output reconciled", "Canonical artifact dossiers", "Publication is deliberately separate"]],
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

test("exposes every dedicated owner workspace in shell navigation", async () => {
  const response = await render();
  const html = await response.text();
  for (const href of ["/product", "/trace", "/knowledge", "/progress"]) {
    assert.match(html, new RegExp(`href="${href}"`), `navigation is missing ${href}`);
  }
});

test("renders the exact canonical output denominator as artifact dossiers", async () => {
  const outputContract = JSON.parse(
    await readFile(new URL("content/output-contract.json", root), "utf8"),
  );
  const response = await render("/exports");
  const html = await response.text();
  assert.equal(outputContract.members.length, 21);
  for (const item of outputContract.members) {
    assert.ok(html.includes(`id="${item.id}"`), `/exports is missing dossier ${item.id}`);
    assert.ok(html.includes(item.dossier.decision_supported), `/exports omitted decision for ${item.id}`);
  }
});

test("server-renders every capability domain deep link with its own records", async () => {
  const catalog = JSON.parse(
    await readFile(new URL("content/capability-catalog.json", root), "utf8"),
  );
  for (const domain of catalog.domains) {
    const response = await render(`/capabilities?domain=${encodeURIComponent(domain.id)}`);
    assert.equal(response.status, 200, domain.id);
    const html = await response.text();
    assert.ok(html.includes(domain.entries[0].title), `${domain.id} did not render its first record`);
    assert.doesNotMatch(html, />0<\/strong> of \d+ capability records/, domain.id);
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
  const identitySource = await readFile(new URL("app/atlas/BuildIdentity.tsx", root), "utf8");
  assert.match(identitySource, /loadProjectionIdentity\(\)/);
  assert.doesNotMatch(identitySource, /\bloadProjection\(\)/);
  const identityModule = await readFile(
    new URL("public/atlas-projection/identity.mjs", root),
  );
  assert.ok(identityModule.byteLength <= 8 * 1024, "identity module exceeds 8 KiB raw");
  scripts += gzipSync(identityModule).byteLength;
  assert.ok(scripts <= 120 * 1024, `true immediate JS is ${scripts} bytes gzip`);
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
  assert.ok(
    names.every((name) =>
      ["_headers", "atlas-projection", "atlas-social-card.png", "favicon.svg", "og.png"].includes(name)),
  );
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

  assert.equal(capabilities.length, 210);
  assert.equal(governance.gaps.length, 41);
  assert.equal(governance.decision_queue.length, 10);
  assert.equal(governance.labs.length, 14);
  assert.equal(horizon.signals.length, 16);
  assert.ok(horizon.signals.every((signal) => signal.content_role === "advisory"));
  assert.ok(horizon.signals.every((signal) => signal.support_claim === "none"));
});
