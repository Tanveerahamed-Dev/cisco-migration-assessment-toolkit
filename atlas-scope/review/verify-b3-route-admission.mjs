/**
 * B3's opened-file integration witness, over the actual standalone production bundle.
 *
 * HOSTED ONLY. After npm run build, build-freshness --stamp and playwright install chromium:
 *   node review/verify-b3-route-admission.mjs --expected-commit <checkout SHA> --output <fresh external directory>
 *
 * The only changed evidence is routes.<subject> in ephemeral copies of the tracked snapshot.
 * No compiler, engine, dataset slot, diagnostic injection or debug scene API is called here: the
 * reader's file control compiles/installs each file, and the reader's form runs each flow. The
 * positive control must visibly use the subject's default route. Its exact flow then challenges
 * null, omitted, wholly mask-spelled and numeric-prefix tables, and an unreadable default in an
 * otherwise readable table. Every branch must run; missing preconditions fail rather than skip.
 *
 * PASS is bounded DOM integration evidence for B3. It is not an acceptance regrade, real-network
 * qualification, canvas-pixel proof, or an endorsement of the address-specificity ACL fallback.
 */
import { chromium, expect } from "@playwright/test";
import { spawn, spawnSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { closeSync, constants, existsSync, fstatSync, lstatSync, mkdirSync, openSync, readFileSync, readSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { checkBuildFreshness } from "./build-freshness.mjs";

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const REPO = realpathSync(resolve(PKG, ".."));
const SAMPLE_REL = "webapp/sample_data/sample_fleet.snapshot.json";
const PORT = 4187;
const ORIGIN = `http://127.0.0.1:${PORT}`;
const WAIT_MS = 30000;
const MAX_MATERIAL_BYTES = 16 * 1024 * 1024;
const sha = (bytes) => createHash("sha256").update(bytes).digest("hex");
const norm = (s) => (s ?? "").replace(/\s+/g, " ").trim();
const check = (ok, why) => { if (!ok) throw new Error(why); };
const inside = (parent, child) => {
  const rel = relative(parent, child);
  return rel === "" || (!isAbsolute(rel) && rel !== ".." && !rel.startsWith(`..${sep}`));
};
const gitBytes = (...args) => {
  const out = spawnSync("git", args, { cwd: REPO, timeout: 30000, maxBuffer: MAX_MATERIAL_BYTES });
  check(out.status === 0, `git ${args[0]} failed: ${out.stderr}`);
  return out.stdout;
};
const git = (...args) => gitBytes(...args).toString("utf8").trim();
/** Resolve aliases at every existing parent, including for a directory not created yet. */
function canonicalPath(input) {
  check(isAbsolute(input), "custody paths must be absolute");
  let parent = resolve(input);
  const tail = [];
  while (!existsSync(parent)) {
    check(parent !== dirname(parent), "custody path has no existing parent");
    tail.unshift(basename(parent));
    parent = dirname(parent);
  }
  return resolve(realpathSync(parent), ...tail);
}
function protectedPaths() {
  const roots = git("worktree", "list", "--porcelain", "-z").split("\0")
    .filter((line) => line.startsWith("worktree ")).map((line) => line.slice("worktree ".length));
  const common = git("rev-parse", "--path-format=absolute", "--git-common-dir");
  check(roots.length > 0 && isAbsolute(common), "managed worktrees and absolute common Git directory must be identifiable");
  return [...new Set([...roots, REPO, common].map(canonicalPath))];
}
function outsideProtected(input) {
  const path = canonicalPath(input);
  for (const root of protectedPaths()) check(!inside(root, path) && !inside(path, root),
    "evidence/scratch paths may not overlap any managed worktree or the common Git directory");
  return path;
}
const sameFileIdentity = (a, b) => ["dev", "ino", "mode", "nlink", "size", "mtimeNs", "ctimeNs"]
  .every((key) => typeof a[key] === "bigint" && typeof b[key] === "bigint" && a[key] === b[key]);
/** Admit the open object, not a pathname checked before the read (CodeQL js/file-system-race). */
function readOrdinaryMaterial(path) {
  check(typeof constants.O_NOFOLLOW === "number" && typeof constants.O_NONBLOCK === "number",
    "hosted Linux no-follow/nonblocking file opening is required");
  const descriptor = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const before = fstatSync(descriptor, { bigint: true });
    check(before.isFile() && before.nlink === 1n && before.size >= 0n && before.size <= BigInt(MAX_MATERIAL_BYTES)
      && canonicalPath(path) === resolve(path), "source material is non-ordinary, hardlinked, aliased or exceeds the bounded read");
    const chunk = Buffer.alloc(64 * 1024);
    const parts = [];
    let total = 0;
    while (total <= MAX_MATERIAL_BYTES) {
      const count = readSync(descriptor, chunk, 0, Math.min(chunk.length, MAX_MATERIAL_BYTES + 1 - total), null);
      if (count === 0) break;
      parts.push(Buffer.from(chunk.subarray(0, count)));
      total += count;
    }
    check(total <= MAX_MATERIAL_BYTES, "source material exceeded the bounded descriptor read");
    const after = fstatSync(descriptor, { bigint: true });
    const named = lstatSync(path, { bigint: true });
    check(named.isFile() && !named.isSymbolicLink() && named.nlink === 1n
      && sameFileIdentity(before, after) && sameFileIdentity(before, named)
      && total === Number(before.size) && canonicalPath(path) === resolve(path), "source descriptor/path identity changed during the read");
    return Buffer.concat(parts, total);
  } finally {
    closeSync(descriptor);
  }
}
/** Exclusive owner-only snapshots in the owned private directory (CodeQL js/insecure-temporary-file). */
function writePrivateSnapshot(path, bytes) {
  const descriptor = openSync(path, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
  try {
    writeFileSync(descriptor, bytes);
  } finally {
    closeSync(descriptor);
  }
}
function arg(name) {
  const at = process.argv.indexOf(name);
  check(at > 0 && typeof process.argv[at + 1] === "string", `required argument ${name}`);
  return process.argv[at + 1];
}
// Reject a workstation invocation before starting any browser or server.
check(process.env.GITHUB_ACTIONS === "true" && process.env.RUNNER_ENVIRONMENT === "github-hosted" && process.platform === "linux",
  "B3 browser integration runs only on a GitHub-hosted Linux runner");
const expectedCommit = arg("--expected-commit");
check(/^[0-9a-f]{40}$/.test(expectedCommit), "expected checkout commit must be a full Git SHA");
const outArg = arg("--output");
check(isAbsolute(outArg), "output directory must be absolute, fresh and outside the repository");
check(!existsSync(outArg) && existsSync(dirname(outArg)), "output must be fresh and its parent must exist");
const output = outsideProtected(outArg);
check(!existsSync(output), "resolved evidence destination must also be fresh");
mkdirSync(output);
const report = {
  schema: "atlas-scope.b3-route-admission-browser.v1",
  verdict: "FAIL",
  qualification: false,
  acceptanceRegrade: false,
  canvasPixelVerification: false,
  startedAt: new Date().toISOString(),
  expectedCommit,
  source: null,
  buildFreshness: null,
  subject: null,
  counters: { positiveDefaultFlows: 0, noRibCases: 0, indeterminateNoRibFlows: 0, partialDefaultCases: 0, undecidedPartialNoRouteFlows: 0 },
  cases: [],
  failures: [],
};
const save = () => writeFileSync(join(output, "b3-route-admission.json"), `${JSON.stringify(report, null, 2)}\n`);
save();

/** A chooser-only strict CIDR reader, not the route-admission implementation under test. */
function cidr(text) {
  if (typeof text !== "string") return null;
  const m = /^(\d+)\.(\d+)\.(\d+)\.(\d+)\/(\d+)$/.exec(text.trim());
  if (m === null) return null;
  const ns = m.slice(1).map(Number);
  if (ns.some((n) => !Number.isInteger(n)) || ns.slice(0, 4).some((n) => n < 0 || n > 255) || ns[4] < 0 || ns[4] > 32) return null;
  const ip = (((ns[0] * 256 + ns[1]) * 256 + ns[2]) * 256 + ns[3]) >>> 0;
  const mask = ns[4] === 0 ? 0 : (0xffffffff << (32 - ns[4])) >>> 0;
  return { ip, net: (ip & mask) >>> 0, mask, bits: ns[4] };
}
const ipv4 = (n) => [24, 16, 8, 0].map((shift) => (n >>> shift) & 255).join(".");
const contains = (p, ip) => ((ip & p.mask) >>> 0) === p.net;
const maskSpelling = (prefix) => {
  const p = cidr(prefix);
  check(p !== null, `chooser requires a readable original CIDR: ${String(prefix)}`);
  return `${ipv4(p.ip)} ${ipv4(p.mask)}`;
};
function chooseSubject(snapshot) {
  check(snapshot.routes !== null && typeof snapshot.routes === "object" && !Array.isArray(snapshot.routes), "tracked sample has no host-keyed routes section");
  check(Array.isArray(snapshot.l3_forwarding), "tracked sample has no L3 rows");
  const candidates = snapshot.l3_forwarding.filter((row) => {
    if (row === null || typeof row !== "object" || typeof row.switch !== "string" || String(row.role).toLowerCase() !== "active") return false;
    const rows = snapshot.routes[row.switch];
    const prefix = cidr(row.primary_subnet);
    return prefix !== null && prefix.bits < 27 && Array.isArray(rows) && rows.length > 1 && rows.every((r) => cidr(r?.prefix) !== null)
      && rows.filter((r) => cidr(r.prefix).bits === 0).length === 1
      && rows.some((r) => r.source === "connected" && cidr(r.prefix).net === prefix.net && cidr(r.prefix).bits === prefix.bits);
  });
  const aclCount = (host) => Object.values(snapshot.acls?.[host] ?? {}).reduce((n, rows) => n + (Array.isArray(rows) ? rows.length : 0), 0);
  candidates.sort((a, b) => aclCount(b.switch) - aclCount(a.switch) || a.switch.localeCompare(b.switch) || a.vlan - b.vlan);
  check(candidates.length > 0, "mandatory subject: observed-Active SVI gateway with readable default plus connected source subnet");
  const row = candidates[0];
  const prefix = cidr(row.primary_subnet);
  const srcIp = ipv4(prefix.net + 50);
  const dstIp = "8.8.8.8";
  const dst = cidr(`${dstIp}/32`).ip;
  const rows = snapshot.routes[row.switch];
  check(!rows.some((r) => cidr(r.prefix).bits > 0 && contains(cidr(r.prefix), dst)), "external challenge is covered by a non-default source route");
  check(!snapshot.l3_forwarding.some((r) => typeof r.vip === "string" && r.vip === srcIp || typeof r.svi_ip === "string" && r.svi_ip.split(/[ /]/)[0] === srcIp), "derived source is a router-owned address");
  return { host: row.switch, sourceSubnet: row.primary_subnet, sourceRecord: `l3_forwarding[${snapshot.l3_forwarding.indexOf(row)}]`,
    defaultIndex: rows.findIndex((r) => cidr(r.prefix).bits === 0), sourceRouteCount: rows.length, srcIp, dstIp,
    routableHostsBefore: Object.entries(snapshot.routes).filter(([, rs]) => Array.isArray(rs) && rs.some((r) => cidr(r?.prefix) !== null)).map(([h]) => h).sort() };
}
function materialHashes() {
  const selected = ["atlas-scope", SAMPLE_REL, ".github/workflows/atlas-scope-ci.yml", ".github/scripts/scope_compile_handoff.py"];
  const entries = (isIndex) => {
    const raw = isIndex ? gitBytes("ls-files", "--stage", "-z", "--", ...selected) : gitBytes("ls-tree", "-r", "-z", "HEAD", "--", ...selected);
    const found = {};
    for (const row of raw.toString("utf8").split("\0").filter(Boolean)) {
      const tab = row.indexOf("\t");
      check(tab > 0, "malformed Git source entry");
      const header = row.slice(0, tab).split(" ");
      const path = row.slice(tab + 1);
      check(header.length === 3 && !isAbsolute(path) && !path.split("/").some((part) => ["", ".", ".."].includes(part)) && !path.includes("\\"), "unsafe Git material path/header");
      const [mode, second, third] = header;
      const blob = isIndex ? second : third;
      const kind = isIndex ? third : second;
      check(["100644", "100755"].includes(mode) && kind === (isIndex ? "0" : "blob") && /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/.test(blob), "source material must be an ordinary HEAD blob at index stage zero");
      check(!Object.hasOwn(found, path), "duplicate/ambiguous Git source entry");
      found[path] = { gitMode: mode, gitBlob: blob };
    }
    return Object.fromEntries(Object.entries(found).sort(([a], [b]) => a.localeCompare(b)));
  };
  const head = entries(false);
  const index = entries(true);
  check(JSON.stringify(head) === JSON.stringify(index), "source material index mode/blob/stage differs from HEAD");
  const flags = gitBytes("ls-files", "-v", "-z", "--", ...selected).toString("utf8").split("\0").filter(Boolean);
  // Lowercase tags hide changes with assume-unchanged; S/s is skip-worktree. Only normal cached H is admitted.
  check(flags.length === Object.keys(head).length && flags.every((row) => row.startsWith("H ")), "source materials carry assume-unchanged, skip-worktree or unsupported index flags");
  check(Object.keys(head).length > 0 && Object.hasOwn(head, "atlas-scope/review/verify-b3-route-admission.mjs"), "harness/source materials must be tracked in the selected commit");
  return Object.fromEntries(Object.entries(head).map(([path, identity]) => {
    const local = join(REPO, path);
    const bytes = readOrdinaryMaterial(local);
    const committed = gitBytes("cat-file", "blob", `HEAD:${path}`);
    check(bytes.length === committed.length && sha(bytes) === sha(committed), "source material bytes differ from the selected HEAD blob, regardless of clean-status flags");
    return [path, { ...identity, bytes: bytes.length, sha256: sha(bytes) }];
  }));
}
async function ready(server) {
  const until = Date.now() + WAIT_MS;
  while (Date.now() < until) {
    check(server.exitCode === null, `owned preview exited with ${server.exitCode}`);
    try {
      const r = await fetch(`${ORIGIN}/`, { signal: AbortSignal.timeout(1000) });
      if (r.ok) return;
    } catch { /* bounded startup polling, not a swallowed verification failure */ }
    await new Promise((done) => setTimeout(done, 100));
  }
  throw new Error("owned standalone preview did not start within 30 seconds");
}
async function routeFlow(page, flow) {
  await page.getByLabel("Source IP", { exact: true }).fill(flow.srcIp);
  await page.getByLabel("Destination IP", { exact: true }).fill(flow.dstIp);
  await page.getByLabel("Protocol", { exact: true }).selectOption(flow.protocol);
  if (flow.protocol === "tcp" || flow.protocol === "udp") await page.getByLabel("Destination port", { exact: true }).fill(String(flow.dstPort));
  const line = `${flow.protocol} ${flow.srcIp} → ${flow.dstIp}${["tcp", "udp"].includes(flow.protocol) ? `:${flow.dstPort}` : ""}`;
  await page.locator(".pt-form button[type='submit']").click();
  await expect(page.locator(".pt-result .claim__flow").first()).toHaveText(line, { timeout: WAIT_MS });
  await expect(page.locator(".pt-result .hoplist .hop").first()).toBeAttached({ timeout: WAIT_MS });
  return page.locator(".pt-result").evaluate((result) => {
    const text = (x) => (x?.textContent ?? "").replace(/\s+/g, " ").trim();
    const claim = result.querySelector(".claim");
    return { band: claim?.getAttribute("data-band"), badge: claim?.getAttribute("data-badge"),
      flow: text(claim?.querySelector(".claim__flow")), outcome: text(claim?.querySelector(".claim__outcome-word")),
      sentence: text(claim?.querySelector(".claim__sentence")),
      hops: [...result.querySelectorAll(".hoplist .hop")].map((hop) => ({ host: text(hop.querySelector(".hop__host")),
        verdict: hop.getAttribute("data-verdict"), band: hop.getAttribute("data-band"), text: text(hop),
        routePrefixes: [...hop.querySelectorAll(".hop__fact")].filter((fact) => text(fact.querySelector("dt")).startsWith("Route"))
          .map((fact) => text(fact.querySelector("dd > .hop__mono"))),
        undecidedReasons: [...hop.querySelectorAll("[data-undecided-reason]")].map(text) })) };
  });
}
async function coverage(page) {
  await page.locator("#status-bar .sb__cov").filter({ hasText: /^RIBs / }).click();
  const panel = page.getByRole("dialog", { name: "Collection coverage", exact: true });
  await expect(panel).toBeVisible();
  const row = panel.locator(".cov__table tbody tr").filter({ has: page.locator(".cov__label", { hasText: /^Routing table \(RIB\)$/ }) });
  await expect(row).toHaveCount(1);
  const observed = Number(await row.locator("td[data-state='observed']").textContent());
  const meaning = norm(await row.locator(".cov__meaning").textContent());
  const scope = await panel.locator(".cov__note").filter({ has: page.locator("dt", { hasText: /^Forwarding scope$/ }) }).locator("dd").textContent();
  const state = { observed, meaning, forwardingScope: norm(scope) };
  await page.screenshot({ path: join(output, `${currentCase.name}-coverage.png`), fullPage: true });
  await page.getByRole("button", { name: "Close the coverage disclosure", exact: true }).click();
  return state;
}
let currentCase;
let browser;
let server;
let scratch;
let scratchParent;
let selectedFlow;
let before;
let statusBefore;
try {
  const commit = git("rev-parse", "HEAD");
  check(commit === expectedCommit && process.env.GITHUB_SHA === expectedCommit, "checkout/source expectation/GitHub SHA differ");
  statusBefore = git("status", "--porcelain");
  check(statusBefore === "", "B3 requires a clean selected source checkout before browser verification");
  before = materialHashes();
  const raw = readOrdinaryMaterial(join(REPO, SAMPLE_REL));
  const snapshot = JSON.parse(raw.toString("utf8"));
  const subject = chooseSubject(snapshot);
  report.source = { commit, tree: git("rev-parse", "HEAD^{tree}"), githubSha: process.env.GITHUB_SHA,
    githubHeadRef: process.env.GITHUB_HEAD_REF ?? "", runId: process.env.GITHUB_RUN_ID, attempt: process.env.GITHUB_RUN_ATTEMPT,
    runnerEnvironment: process.env.RUNNER_ENVIRONMENT, nodeVersion: process.version, platform: process.platform,
    playwrightVersion: JSON.parse(readFileSync(join(PKG, "node_modules/@playwright/test/package.json"), "utf8")).version,
    harnessSha256: sha(readOrdinaryMaterial(fileURLToPath(import.meta.url))), sourceSnapshotSha256: sha(raw),
    sourceMaterials: before, sourceStatus: statusBefore };
  report.subject = subject;
  scratchParent = canonicalPath(tmpdir());
  // Check both parent and selected unique child before mkdir writes anything (including prunable worktree paths).
  for (const root of protectedPaths()) check(!inside(root, scratchParent), "ephemeral temp parent is inside a managed worktree/common Git directory");
  const plannedScratch = outsideProtected(join(scratchParent, `atlas-b3-browser-${randomUUID()}`));
  check(!existsSync(plannedScratch), "selected scratch directory must be fresh");
  mkdirSync(plannedScratch, { mode: 0o700 });
  scratch = plannedScratch;
  const variants = [
    { name: "positive", kind: "positive", change: null },
    { name: "missing-rib", kind: "missing", change: (s) => { delete s.routes[subject.host]; } },
    { name: "null-rib", kind: "no-rib", change: (s) => { s.routes[subject.host] = null; } },
    { name: "mask-rib", kind: "no-rib", change: (s) => { s.routes[subject.host] = s.routes[subject.host].map((r) => ({ ...r, prefix: maskSpelling(r.prefix) })); } },
    { name: "number-rib", kind: "no-rib", change: (s) => { s.routes[subject.host] = s.routes[subject.host].map((r) => ({ ...r, prefix: 10 })); } },
    { name: "partial-default", kind: "partial", change: (s) => {
      const rows = s.routes[subject.host];
      rows[subject.defaultIndex] = { ...rows[subject.defaultIndex], prefix: maskSpelling(rows[subject.defaultIndex].prefix) };
    } },
  ];
  const log = [];
  let occupied = false;
  try { await fetch(`${ORIGIN}/`, { signal: AbortSignal.timeout(1000) }); occupied = true; } catch { /* no listener is the required precondition */ }
  check(!occupied, "owned preview port already has a listener; refusing to observe another server");
  server = spawn(process.execPath, [join(PKG, "node_modules/vite/bin/vite.js"), "preview", "--host", "127.0.0.1", "--port", String(PORT), "--strictPort"],
    { cwd: PKG, stdio: ["ignore", "pipe", "pipe"] });
  server.on("error", (e) => log.push(`spawn error: ${String(e)}`));
  for (const stream of [server.stdout, server.stderr]) stream.on("data", (bytes) => { log.push(bytes.toString()); writeFileSync(join(output, "preview.log"), log.join("")); });
  await ready(server);
  report.buildFreshness = await checkBuildFreshness(ORIGIN);
  check(report.buildFreshness.fresh && report.buildFreshness.servesLocalDist === true && report.buildFreshness.devServer === false, "B3 requires this source's fresh production bundle, never a dev server");
  browser = await chromium.launch({ args: ["--enable-unsafe-swiftshader"] });
  report.source.chromiumVersion = browser.version();
  for (const variant of variants) {
    currentCase = { name: variant.name, kind: variant.kind, verdict: "FAIL", failures: [], traces: [], pageErrors: [], console: [], forbiddenRequests: [] };
    report.cases.push(currentCase);
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 1080 }, colorScheme: "light" });
    let page;
    try {
      await ctx.route("**/*", (route) => {
        const url = new URL(route.request().url());
        if (url.origin === ORIGIN || ["data:", "blob:"].includes(url.protocol)) return route.continue();
        currentCase.forbiddenRequests.push({ url: url.href, method: route.request().method() });
        return route.abort("blockedbyclient");
      });
      const clone = JSON.parse(raw.toString("utf8"));
      if (variant.change !== null) variant.change(clone);
      // The snapshot is not adorned with diagnostic/private fields; only its route subject changed.
      const bytes = variant.change === null ? raw : Buffer.from(`${JSON.stringify(clone, null, 1)}\n`);
      const fileName = `b3-${variant.name}.snapshot.json`;
      const path = join(scratch, fileName);
      writePrivateSnapshot(path, bytes);
      currentCase.snapshot = { fileName, bytes: bytes.length, sha256: sha(bytes), sourceExactSha256: `sha256:${sha(bytes)}` };
      page = await ctx.newPage();
      page.setDefaultTimeout(WAIT_MS);
      page.on("pageerror", (e) => currentCase.pageErrors.push(String(e)));
      page.on("console", (m) => { if (["warning", "error"].includes(m.type())) currentCase.console.push({ type: m.type(), text: m.text() }); });
      await page.goto(`${ORIGIN}/`, { waitUntil: "load" });
      await expect(page.locator(".hdr-snap")).toBeVisible();
      await page.locator(".hdr-snap").click();
      const input = page.locator(".open-snapshot input[type='file']");
      await expect(input).toHaveCount(1);
      await input.setInputFiles(path);
      await expect(page.locator(".sb-dataset[data-origin='opened-file'] [data-dataset-name]")).toHaveText(fileName, { timeout: WAIT_MS });
      const exactTitle = await page.locator(".sb-dataset [data-digest='sourceExactSha256']").getAttribute("title");
      check(exactTitle?.includes(`sha256:${sha(bytes)}`), `${variant.name}: browser identity is not bound to the opened exact bytes`);
      currentCase.loadedIdentity = { fileName: await page.locator("[data-dataset-name]").textContent(), exactDigestTitle: exactTitle };
      const warnings = page.locator(".sb-dataset__warnings");
      if (await warnings.count() > 0) await warnings.locator("summary").click();
      currentCase.warnings = await page.locator(".sb-dataset [data-warning]").evaluateAll((rows) => rows.map((r) => ({ code: r.getAttribute("data-warning"), text: r.textContent })));
      await page.screenshot({ path: join(output, `${variant.name}-warnings.png`), fullPage: true });
      const namedWarnings = currentCase.warnings.filter((w) => w.code === "W_ROUTES_NOT_USABLE" && w.text.includes(`routes.${subject.host}`));
      if (variant.kind === "no-rib") check(namedWarnings.length === 1, `${variant.name}: require one named no-usable-RIB warning`);
      if (variant.kind === "positive" || variant.kind === "partial") check(namedWarnings.length === 0, `${variant.name}: readable RIB must not be marked absent`);
      if (variant.kind === "partial") {
        const warning = currentCase.warnings.filter((w) => w.code === "W_ROUTE_ENTRY_UNREADABLE");
        check(warning.length === 1 && warning[0].text.includes(`routes.${subject.host}[${subject.defaultIndex}]`), "partial default warning lost its original source entry index");
      }
      currentCase.coverage = await coverage(page);
      const isAbsent = variant.kind === "missing" || variant.kind === "no-rib";
      check(currentCase.coverage.observed === subject.routableHostsBefore.length - Number(isAbsent), `${variant.name}: CoverageBar RIB count did not reconcile to the changed source table`);
      const expectedHosts = subject.routableHostsBefore.filter((host) => !isAbsent || host !== subject.host);
      check(currentCase.coverage.forwardingScope.startsWith(`modelled on ${expectedHosts.join(", ")} —`), `${variant.name}: CoverageBar falsely includes or excludes the subject's RIB`);
      if (variant.kind === "partial") check(currentCase.coverage.meaning.includes(subject.host) && currentCase.coverage.meaning.includes("incomplete"), "partly unreadable RIB needs named incomplete disclosure");
      const pathButton = page.locator(".hdr-surface").filter({ has: page.locator(".hdr-surface__label", { hasText: /^Path$/ }) });
      await expect(pathButton).toBeVisible();
      await pathButton.click();
      await expect(page.getByLabel("Source IP", { exact: true })).toBeVisible();
      if (variant.kind === "positive") {
        for (const [protocol, dstPort] of [["tcp", 443], ["tcp", 22], ["udp", 53], ["icmp", null], ["ip", null]]) {
          const flow = { srcIp: subject.srcIp, dstIp: subject.dstIp, protocol, dstPort };
          const shown = await routeFlow(page, flow);
          currentCase.traces.push({ flow, shown });
          const hop = shown.hops[0];
          if (hop?.host === subject.host && hop.routePrefixes.includes("0.0.0.0/0") && hop.verdict !== "denied") {
            selectedFlow = flow;
            report.counters.positiveDefaultFlows += 1;
            break;
          }
        }
        check(report.counters.positiveDefaultFlows > 0, "mandatory positive control: real source-derived flow must visibly use the subject's default route without being stopped first by an ACL denial");
      } else {
        check(selectedFlow !== undefined, "challenge cannot run without the positive default flow");
        const shown = await routeFlow(page, selectedFlow);
        currentCase.traces.push({ flow: selectedFlow, shown });
        const hop = shown.hops[0];
        check(hop?.host === subject.host, `${variant.name}: mandatory trace did not reach the subject`);
        check(shown.band === "UNDETERMINED" && ["INDETERMINATE", "PARTIAL"].includes(shown.badge), `${variant.name}: trace published a decided badge/band`);
        if (isAbsent) {
          check(shown.badge === "INDETERMINATE", `${variant.name}: absent RIB must show the INDETERMINATE badge`);
          check(hop.verdict === "unmodeled" && hop.routePrefixes.length === 0, `${variant.name}: missing/unreadable RIB became a no-route drop or readable route`);
          check(shown.sentence.includes(subject.host) && shown.sentence.includes("no routing table was collected"), `${variant.name}: claim must name the unmodelled subject and missing table`);
          check(!hop.text.includes("No other route in this host") && !shown.sentence.includes("it carries no default route"), `${variant.name}: missing table rendered as an empty but collected/complete table`);
          report.counters.noRibCases += 1;
          report.counters.indeterminateNoRibFlows += 1;
        } else {
          const cite = `routes.${subject.host}[${subject.defaultIndex}]`;
          check(hop.verdict === "no-route" && hop.routePrefixes.length === 0, "partial default must reach the real no-route branch, not another refusal");
          check(shown.sentence.includes(cite) && !shown.sentence.includes("it carries no default route"), "partial default absence was decided or its original unreadable entry citation disappeared");
          check(hop.undecidedReasons.some((text) => text.includes(cite)) && hop.text.includes("table incomplete"), "HopList must state its incomplete table reason with the original entry cite");
          report.counters.partialDefaultCases += 1;
          report.counters.undecidedPartialNoRouteFlows += 1;
        }
      }
      await page.screenshot({ path: join(output, `${variant.name}-trace.png`), fullPage: true });
      currentCase.bodyText = await page.locator("body").innerText();
      check(currentCase.pageErrors.length === 0, `${variant.name}: browser page error: ${currentCase.pageErrors.join("; ")}`);
      check(currentCase.forbiddenRequests.length === 0, `${variant.name}: browser attempted external access`);
      currentCase.verdict = "PASS";
    } catch (error) {
      currentCase.failures.push(String(error));
      if (page !== undefined) {
        try { currentCase.bodyText = await page.locator("body").innerText(); } catch { /* retain original failure */ }
        try { await page.screenshot({ path: join(output, `${variant.name}-failure.png`), fullPage: true }); } catch { /* a closed page cannot produce pixels */ }
      }
      report.failures.push(`${variant.name}: ${String(error)}`);
    } finally {
      await ctx.close();
      save();
    }
  }
  check(report.cases.length === 6 && report.cases.every((c) => c.verdict === "PASS"), "every mandatory positive/no-RIB/partial-default case must pass");
  check(report.counters.positiveDefaultFlows > 0 && report.counters.noRibCases === 4 && report.counters.indeterminateNoRibFlows === 4
    && report.counters.partialDefaultCases === 1 && report.counters.undecidedPartialNoRouteFlows === 1, "mandatory branch counts were not met");
  check(git("rev-parse", "HEAD") === expectedCommit, "source commit changed during browser verification");
  const after = materialHashes();
  check(JSON.stringify(after) === JSON.stringify(before) && git("status", "--porcelain") === statusBefore, "tracked/source material or source status changed during the witness");
  report.source.materialsStableAfter = true;
  report.source.distIndexSha256 = sha(readFileSync(join(PKG, "dist/index.html")));
  report.verdict = "PASS";
} catch (error) {
  report.failures.push(String(error));
} finally {
  if (browser !== undefined) await browser.close();
  if (server !== undefined && server.exitCode === null) {
    server.kill("SIGTERM");
    await Promise.race([new Promise((done) => server.once("exit", done)), new Promise((done) => setTimeout(done, 3000))]);
    if (server.exitCode === null) server.kill("SIGKILL");
  }
  // Only the unique directory this invocation created; never the caller's retained evidence directory.
  if (scratch !== undefined) {
    try {
      check(canonicalPath(scratch) === scratch && lstatSync(scratch).isDirectory() && !lstatSync(scratch).isSymbolicLink()
        && dirname(scratch) === scratchParent && basename(scratch).startsWith("atlas-b3-browser-"), "owned scratch identity changed before cleanup");
      outsideProtected(scratch); // Fresh inventory: a newly registered worktree is not ours to remove.
      rmSync(scratch, { recursive: true, force: false });
    } catch (error) {
      report.failures.push(`scratch cleanup refused: ${String(error)}`);
      report.verdict = "FAIL";
    }
  }
  report.finishedAt = new Date().toISOString();
  save();
}
console.log(JSON.stringify({ verdict: report.verdict, counters: report.counters, failures: report.failures }));
process.exitCode = report.verdict === "PASS" ? 0 : 1;
