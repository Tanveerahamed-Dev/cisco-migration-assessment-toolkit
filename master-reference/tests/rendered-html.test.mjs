import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
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

test("server-renders the complete master reference", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>Enhancements · Master Reference<\/title>/i);
  assert.match(html, /From raw evidence/);
  assert.match(html, /earned confidence/);
  assert.match(html, /One evidence spine, eight guarded transitions/);
  assert.match(html, /Every important choice carries its/);
  assert.match(html, /Confidence is earned at the edges/);
  assert.match(html, /PPDIOO, expressed as evidence gates/);
  assert.match(html, /Where each contract lives/);
  assert.match(html, /A green label must say what it proves/);
  assert.match(html, /No analytics/);
  assert.match(html, /role="tablist"/);
  assert.match(html, /aria-live="polite"/);
  assert.doesNotMatch(html, /Starter Project|SkeletonPreview|taking shape/i);
});

test("keeps the reference static, local, and dependency-light", async () => {
  const [
    page,
    layout,
    reference,
    styles,
    worker,
    packageJson,
    publicFiles,
    socialCard,
  ] =
    await Promise.all([
      readFile(new URL("app/page.tsx", root), "utf8"),
      readFile(new URL("app/layout.tsx", root), "utf8"),
      readFile(new URL("app/MasterReference.tsx", root), "utf8"),
      readFile(new URL("app/globals.css", root), "utf8"),
      readFile(new URL("worker/index.ts", root), "utf8"),
      readFile(new URL("package.json", root), "utf8"),
      readdir(new URL("public/", root)),
      readFile(new URL("public/og.png", root)),
    ]);

  const packageData = JSON.parse(packageJson);
  assert.deepEqual(Object.keys(packageData.dependencies).sort(), [
    "next",
    "react",
    "react-dom",
  ]);
  assert.equal(packageData.private, true);
  assert.match(page, /<MasterReference \/>/);
  assert.match(layout, /Enhancements · Master Reference/);
  assert.match(reference, /"use client"/);
  assert.match(reference, /const decisions: Decision\[\]/);
  assert.match(reference, /const trustBoundaries =/);
  assert.match(styles, /prefers-reduced-motion/);
  assert.doesNotMatch(reference, /\bfetch\s*\(|XMLHttpRequest|WebSocket|localStorage|sessionStorage|document\.cookie/);
  assert.doesNotMatch(worker, /D1Database|handleImageOptimization/);
  assert.doesNotMatch(
    packageJson,
    /drizzle|tailwind|react-loading-skeleton|analytics/i,
  );
  assert.deepEqual(publicFiles.sort(), ["favicon.svg", "og.png"]);
  assert.equal(socialCard.subarray(1, 4).toString("ascii"), "PNG");
  assert.equal(socialCard.readUInt32BE(16), 1730);
  assert.equal(socialCard.readUInt32BE(20), 909);
  assert.equal(
    createHash("sha256").update(socialCard).digest("hex"),
    "ea17869f8f9f1a933e6d14ffed48d51fad2908c293d5eb439f4d61218b1cc208",
  );
});

test("documents rationale, tradeoffs, enforcement, and evidence for decisions", async () => {
  const source = await readFile(
    new URL("app/MasterReference.tsx", root),
    "utf8",
  );

  const decisionIds = [...source.matchAll(/\n    id: "([^"]+)",/g)].map(
    (match) => match[1],
  );
  assert.ok(decisionIds.length >= 15);
  assert.equal(new Set(decisionIds).size, decisionIds.length);
  assert.ok((source.match(/\n    reason:/g) ?? []).length >= 15);
  assert.ok((source.match(/\n    tradeoff:/g) ?? []).length >= 15);
  assert.ok((source.match(/\n    enforcement:/g) ?? []).length >= 15);
  assert.ok((source.match(/\n    evidence:/g) ?? []).length >= 15);
});
