/**
 * build-freshness.mjs — is the server a harness is about to measure serving THIS checkout's code?
 *
 * WHY THIS EXISTS (review finding, E2, 2026-09-21). The shared release preview on :4181 served a
 * `dist/` that predated more than twenty changed source files, and every harness that took its
 * default URL measured the old code while reporting the numbers as evidence about the new. A
 * measurement of a stale bundle is not a slow or a fast result; it is a result about a different
 * program. So every evidence harness asks two questions before its numbers may be quoted:
 *
 *   1. Is the served page the local `dist/` at all? The served `index.html` is compared byte for
 *      byte with `dist/index.html`, which names the content-hashed entry chunk — so two builds of
 *      different source produce different files. A server whose page differs is serving some OTHER
 *      build (another checkout, another outDir), and nothing here can say how old that is.
 *   2. Is the local `dist/` older than the source? Any file under `src/`, `index.html` or a build
 *      config newer than `dist/index.html` means the build predates the code it is named after.
 *
 * CONTENT, NOT MTIME (review finding, E2, 2026-09-21). Question 2 used to be answered by mtime
 * alone. A concurrent process rewrote src/data/fabric.json with byte-identical content ten seconds
 * after a build, and every later harness run reported "build NOT FRESH" for a build that was, byte
 * for byte, built from the source on disk. Conservative, but wrong. So a build is STAMPED with a
 * sha256 of every source file it was built from (`.atlas-source-stamp.json` beside dist/index.html,
 * bound to that index.html's own hash), and a file whose mtime is newer but whose content still
 * matches the stamp is not a change. The stamp is written only when the mtime evidence already says
 * the build is fresh — right after a build, run `node review/build-freshness.mjs --stamp`; any
 * harness check that finds the build fresh by mtime also writes it — so it never certifies anything
 * mtime would not have certified at that moment. With no stamp, mtime still decides, as before.
 *
 * A dev server answers neither question and needs neither: it compiles the source on request.
 * Callers put `fresh` into their acceptance gate and `why` into their report; this module never
 * decides a verdict itself.
 */
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const SOURCES = ["src", "index.html", "vite.config.ts", "package.json", "tsconfig.json"];

const sha = (path) => createHash("sha256").update(readFileSync(path)).digest("hex");

/** Every build-relevant source file, relative to ROOT, test files excluded (they never reach the bundle). */
function sourceFilesUnder(path, out) {
  if (!existsSync(path)) return out;
  const st = statSync(path);
  if (st.isDirectory()) {
    for (const entry of readdirSync(path)) sourceFilesUnder(join(path, entry), out);
    return out;
  }
  if (/\.test\.[cm]?[jt]sx?$/.test(path)) return out;
  out.push(relative(ROOT, path).replaceAll("\\", "/"));
  return out;
}

const stampPath = (distIndex) => join(dirname(distIndex), ".atlas-source-stamp.json");

/** Write the content stamp for the build whose entry page is `distIndex`. */
function writeStamp(distIndex) {
  const files = {};
  for (const s of SOURCES) for (const rel of sourceFilesUnder(join(ROOT, s), [])) files[rel] = sha(join(ROOT, rel));
  writeFileSync(stampPath(distIndex), JSON.stringify({ distIndexSha256: sha(distIndex), files }, null, 1));
}

/** The stamp for THIS build, or null when there is none or it belongs to another build. */
function readStamp(distIndex) {
  try {
    const stamp = JSON.parse(readFileSync(stampPath(distIndex), "utf8"));
    return stamp && stamp.distIndexSha256 === sha(distIndex) && stamp.files ? stamp : null;
  } catch {
    return null;
  }
}

function newestUnder(path, since, out) {
  if (!existsSync(path)) return;
  const st = statSync(path);
  if (st.isDirectory()) {
    for (const entry of readdirSync(path)) newestUnder(join(path, entry), since, out);
    return;
  }
  /* Test files never reach the bundle, so a newer one does not make a build stale. */
  if (/\.test\.[cm]?[jt]sx?$/.test(path)) return;
  if (st.mtimeMs > since) out.push(relative(ROOT, path).replaceAll("\\", "/"));
}

/**
 * @param {string} url  The origin being measured.
 * @param {{ devServer: boolean }} [served]  What the harness already observed about the server. When
 *   omitted, a Vite dev server is recognised by the `/@vite/client` its page loads.
 * @returns {Promise<{ fresh: boolean, devServer: boolean, servesLocalDist: boolean | null, newerThanDist: string[], why: string }>}
 */
export async function checkBuildFreshness(url, served) {
  let servedHtml = null;
  try {
    const res = await fetch(url.replace(/\/$/, "") + "/");
    servedHtml = res.ok ? await res.text() : null;
  } catch {
    servedHtml = null;
  }
  const devServer = served ? served.devServer : servedHtml !== null && servedHtml.includes("/@vite/client");
  if (devServer) {
    return { fresh: true, devServer, servesLocalDist: null, newerThanDist: [], why: "dev server: compiles the working tree on request" };
  }
  /* ATLAS_DIST_DIR names a build written somewhere other than dist/ (vite build --outDir X). */
  const distIndex = join(process.env.ATLAS_DIST_DIR || join(ROOT, "dist"), "index.html");
  if (!existsSync(distIndex)) {
    return { fresh: false, devServer, servesLocalDist: false, newerThanDist: [], why: `no ${distIndex} to compare the served page with` };
  }
  const servesLocalDist = servedHtml !== null && servedHtml === readFileSync(distIndex, "utf8");
  const newerByMtime = [];
  const builtAt = statSync(distIndex).mtimeMs;
  for (const s of SOURCES) newestUnder(join(ROOT, s), builtAt, newerByMtime);
  /* A newer mtime is a CANDIDATE change; the stamp decides. A file absent from the stamp is new
     since the build, and stays a change. */
  const stamp = newerByMtime.length > 0 ? readStamp(distIndex) : null;
  const newer = stamp
    ? newerByMtime.filter((rel) => stamp.files[rel] === undefined || stamp.files[rel] !== sha(join(ROOT, rel)))
    : newerByMtime;
  /* Files the build had that are gone now are a change too, and mtime cannot see a deletion. */
  if (stamp) for (const rel of Object.keys(stamp.files)) if (!existsSync(join(ROOT, rel))) newer.push(rel);
  const touchedOnly = newerByMtime.length - newer.length;
  if (!servesLocalDist) {
    return {
      fresh: false,
      devServer,
      servesLocalDist,
      newerThanDist: newer,
      why: `${url} does not serve this checkout's dist/ (its index.html differs), so its age is unknown`,
    };
  }
  if (newer.length > 0) {
    return {
      fresh: false,
      devServer,
      servesLocalDist,
      newerThanDist: newer,
      why: `dist/ is older than ${newer.length} source file(s) (${newer.slice(0, 4).join(", ")}${newer.length > 4 ? ", ..." : ""}); rebuild before measuring`,
    };
  }
  if (newerByMtime.length === 0 && !existsSync(stampPath(distIndex))) {
    try {
      writeStamp(distIndex);
    } catch {
      /* A read-only dist/ keeps the mtime-only behaviour; nothing is certified by failing here. */
    }
  }
  return {
    fresh: true,
    devServer,
    servesLocalDist,
    newerThanDist: [],
    why:
      touchedOnly > 0
        ? `served page is this checkout's dist/; ${touchedOnly} source file(s) have a newer mtime but content identical to the build's stamp`
        : "served page is this checkout's dist/, and nothing in the source is newer",
  };
}

/* CLI: `node review/build-freshness.mjs --stamp` right after `npm run build`. Refuses when mtime
   already says the build is older than the source, so a stamp can never launder a stale build. */
if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1] && process.argv.includes("--stamp")) {
  const distIndex = join(process.env.ATLAS_DIST_DIR || join(ROOT, "dist"), "index.html");
  const newer = [];
  if (!existsSync(distIndex)) {
    console.error(`no ${distIndex}: build first`);
    process.exit(1);
  }
  for (const s of SOURCES) newestUnder(join(ROOT, s), statSync(distIndex).mtimeMs, newer);
  if (newer.length > 0) {
    console.error(`refusing to stamp: ${newer.length} source file(s) are newer than the build (${newer.slice(0, 4).join(", ")})`);
    process.exit(2);
  }
  writeStamp(distIndex);
  console.log(`stamped ${stampPath(distIndex)}`);
}
