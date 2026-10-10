/** Pure synthetic policy controls. Hosted only; no network, npm resolution or package execution. */
import test from "node:test";
import assert from "node:assert/strict";
import { admitCandidate, admitLock, admitMetadata, dependencyDiff, metadataMember, outputMember, planManifest, registryEvidence,
  registryUrl, strictJson } from "./frontend_dependency_prepare.mjs";

if (process.env.GITHUB_ACTIONS !== "true" || process.env.RUNNER_ENVIRONMENT !== "github-hosted")
  throw new Error("Preparation guard tests require GitHub-hosted execution");

const integrity = `sha512-${Buffer.alloc(64).toString("base64")}`;
function packageRow(name, version) {
  return { version, resolved: `https://registry.npmjs.org/${name}/-/${name}-${version}.tgz`, integrity, license: "MIT" };
}
function fixture() {
  const before = { name: "synthetic-frontend", version: "1.0.0", private: true,
    engines: { node: ">=24.18.0 <25" }, scripts: { test: "unchanged-test-command" },
    dependencies: { react: "1.0.0", three: "^0.185.1" }, devDependencies: { vite: "8.2.2" }, overrides: { nanoid: "3.3.18" } };
  const plan = { schema: "frontend-dependency-plan/1", changes: [
    { section: "dependencies", name: "react", from: "1.0.0", to: "2.0.0", version: "2.0.0" },
  ] };
  const lock = { name: before.name, version: before.version, lockfileVersion: 3, requires: true, packages: {
    "": { name: before.name, version: before.version, engines: before.engines,
      dependencies: before.dependencies, devDependencies: before.devDependencies },
    "node_modules/react": packageRow("react", "1.0.0"),
    "node_modules/three": packageRow("three", "0.185.1"), "node_modules/vite": packageRow("vite", "8.2.2"),
  } };
  const candidate = planManifest(plan, before); const next = structuredClone(lock);
  next.packages[""].dependencies = candidate.dependencies;
  next.packages["node_modules/react"] = packageRow("react", "2.0.0");
  const published = { name: "react", version: "2.0.0", license: "MIT",
    dist: { tarball: next.packages["node_modules/react"].resolved, integrity } };
  const metadata = new Map([["react", admitMetadata(published, plan.changes[0])]]);
  return { before, plan, lock, candidate, next, published, metadata };
}
const admit = (f) => admitCandidate(f.plan, f.before, f.lock, f.candidate, f.next, f.metadata);

test("one requested direct update preserves deferred direct versions and legacy manifest fields", () => {
  const f = fixture(); const result = admit(f);
  assert.deepEqual(f.candidate.scripts, f.before.scripts);
  assert.deepEqual(f.candidate.overrides, f.before.overrides);
  assert.deepEqual(result.direct.map((row) => [row.name, row.before, row.after]),
    [["react", "1.0.0", "2.0.0"], ["three", "0.185.1", "0.185.1"], ["vite", "8.2.2", "8.2.2"]]);
  assert.deepEqual(result.changed_packages.map((row) => row.path), ["", "node_modules/react"]);
});
test("transitive observation retains complete added, removed and metadata-only changed rows", () => {
  const f = fixture();
  f.lock.packages["node_modules/old-transitive"] = packageRow("old-transitive", "1.0.0");
  f.next.packages["node_modules/new-transitive"] = packageRow("new-transitive", "1.0.0");
  f.lock.packages["node_modules/shared"] = packageRow("shared", "1.0.0");
  f.next.packages["node_modules/shared"] = { ...packageRow("shared", "1.0.0"), dev: true };
  const rows = admit(f).changed_packages;
  assert.equal(rows.find((row) => row.path === "node_modules/old-transitive").change, "removed");
  assert.equal(rows.find((row) => row.path === "node_modules/new-transitive").change, "added");
  assert.equal(rows.find((row) => row.path === "node_modules/shared").after.dev, true);
});
for (const [title, alter] of [
  ["unexpected plan key", (f) => { f.plan.command = "npm update"; }],
  ["unknown plan group", (f) => { f.plan.changes[0].section = "scripts"; }],
  ["unknown direct package", (f) => { f.plan.changes[0].name = "not-installed"; }],
  ["incorrect current spec", (f) => { f.plan.changes[0].from = "0.0.0"; }],
  ["unbounded latest spec", (f) => { f.plan.changes[0].to = "latest"; }],
  ["duplicate planned name", (f) => { f.plan.changes.push({ ...f.plan.changes[0] }); }],
  ["extra change key", (f) => { f.plan.changes[0].url = "https://example.invalid/package.tgz"; }],
  ["empty plan", (f) => { f.plan.changes = []; }],
]) test(`plan refuses ${title}`, () => { const f = fixture(); alter(f); assert.throws(() => planManifest(f.plan, f.before)); });

for (const [title, alter] of [
  ["changed script", (f) => { f.candidate.scripts.test = "weakened"; }],
  ["changed override", (f) => { f.candidate.overrides.nanoid = "*"; }],
  ["new manifest key", (f) => { f.candidate.newField = true; }],
  ["missing root lock", (f) => { delete f.next.packages[""]; }],
  ["lock metadata drift", (f) => { f.next.requires = false; }],
  ["root lock field drift", (f) => { f.next.packages[""].license = "unrequested"; }],
  ["unreviewed selected patch", (f) => { f.next.packages["node_modules/react"].version = "2.0.1"; }],
  ["unreviewed deferred patch", (f) => { f.next.packages["node_modules/three"].version = "0.185.2"; }],
  ["missing direct row", (f) => { delete f.next.packages["node_modules/vite"]; }],
  ["integrity metadata mismatch", (f) => { f.next.packages["node_modules/react"].integrity = `sha512-${Buffer.alloc(64, 1).toString("base64")}`; }],
  ["engine metadata mismatch", (f) => { f.next.packages["node_modules/react"].engines = { node: ">=99" }; }],
  ["peer metadata mismatch", (f) => { f.next.packages["node_modules/react"].peerDependencies = { three: "*" }; }],
  ["license metadata mismatch", (f) => { f.next.packages["node_modules/react"].license = "unreviewed"; }],
  ["link row", (f) => { f.next.packages["node_modules/three"].link = true; }],
  ["malformed integrity", (f) => { f.next.packages["node_modules/three"].integrity = "sha512-A=="; }],
  ["escaping package path", (f) => { f.next.packages["../elsewhere"] = packageRow("elsewhere", "1.0.0"); }],
]) test(`candidate refuses ${title}`, () => { const f = fixture(); alter(f); assert.throws(() => admit(f)); });

for (const [title, alter] of [
  ["same-version URL", (row) => { row.resolved = "https://registry.npmjs.org/three/-/different-distribution.tgz"; }],
  ["same-version integrity", (row) => { row.integrity = `sha512-${Buffer.alloc(64, 2).toString("base64")}`; }],
  ["license", (row) => { row.license = "Apache-2.0"; }],
  ["engines", (row) => { row.engines = { node: ">=26" }; }],
  ["dependency specification", (row) => { row.dependencies = { helper: "^2.0.0" }; }],
  ["optional dependency specification", (row) => { row.optionalDependencies = { helper: "^2.0.0" }; }],
  ["peer specification", (row) => { row.peerDependencies = { helper: "^2.0.0" }; }],
  ["optional peer metadata", (row) => { row.peerDependenciesMeta = { helper: { optional: true } }; }],
  ["installation script marker", (row) => { row.hasInstallScript = true; }],
  ["unknown future metadata", (row) => { row.futureMetadata = { changed: true }; }],
]) test(`unchanged direct refuses ${title} drift without a version change`, () => {
  const f = fixture(); const old = f.lock.packages["node_modules/three"];
  alter(f.next.packages["node_modules/three"]);
  assert.equal(f.next.packages["node_modules/three"].version, old.version);
  assert.throws(() => admit(f), /Unreviewed distribution or declared metadata change for unchanged direct/);
  assert.ok(dependencyDiff(f.plan, f.before, f.lock, f.candidate, f.next).changed_packages
    .some((row) => row.path === "node_modules/three"));
});
test("unchanged direct refuses metadata deletion as well as additions", () => {
  const f = fixture(); f.lock.packages["node_modules/three"].engines = { node: ">=20" };
  assert.throws(() => admit(f), /Unreviewed distribution or declared metadata change for unchanged direct/);
});
test("only four typed graph flags may differ on an otherwise identical direct distribution", () => {
  const f = fixture(); Object.assign(f.lock.packages["node_modules/three"], { dev: true, optional: false, peer: false });
  Object.assign(f.next.packages["node_modules/three"], { dev: false, optional: true, devOptional: true, peer: true });
  const result = admit(f);
  const changed = result.changed_packages.find((row) => row.path === "node_modules/three");
  assert.equal(changed.before.integrity, changed.after.integrity);
  assert.equal(changed.before.resolved, changed.after.resolved);
  assert.equal(changed.before.dev, true); assert.equal(changed.after.dev, false);
  assert.equal(changed.after.devOptional, true);
  f.next.packages["node_modules/three"].peer = "true";
  assert.throws(() => admit(f), /Invalid graph classification flag/);
});

for (const [index, url] of ["http://registry.npmjs.org/react.tgz", "https://other.invalid/react.tgz",
  "https://name:secret@registry.npmjs.org/react.tgz", "file:///tmp/react.tgz", "git+https://github.com/a/b",
  "https://registry.npmjs.org/react.tgz?token=secret", "https://registry.npmjs.org/react.tgz#fragment"].entries())
  test(`registry admission refuses noncanonical source case ${index + 1}`, () => {
    assert.throws(() => registryUrl(url)); const f = fixture(); f.next.packages["node_modules/react"].resolved = url;
    assert.throws(() => admitLock(f.next, f.candidate));
  });
for (const spec of ["git+https://github.com/a/b", "file:../local", "https://elsewhere.invalid/a.tgz", "owner/repo", "npm:alias@1.0.0"])
  test(`metadata refuses nonregistry edge ${spec.split(":")[0]}`, () => {
    const f = fixture(); f.published.dependencies = { other: spec };
    assert.throws(() => admitMetadata(f.published, f.plan.changes[0]));
  });
test("exact requested metadata must match package/version and retain peers and engines", () => {
  const f = fixture(); f.published.engines = { node: ">=24" }; f.published.peerDependencies = { three: "^0.185.1" };
  const read = admitMetadata(f.published, f.plan.changes[0]);
  assert.deepEqual(read.engines, f.published.engines); assert.deepEqual(read.peerDependencies, f.published.peerDependencies);
  assert.throws(() => admitMetadata({ ...f.published, version: "2.0.1" }, f.plan.changes[0]));
  assert.throws(() => admitMetadata({ ...f.published, license: undefined }, f.plan.changes[0]));
});
test("refused direct drift still has a nonpromoting complete graph observation", () => {
  const f = fixture(); f.next.packages["node_modules/three"].version = "0.186.1";
  assert.throws(() => admit(f));
  const diff = dependencyDiff(f.plan, f.before, f.lock, f.candidate, f.next);
  assert.equal(diff.status, "UNAPPROVED_GRAPH_OBSERVATION");
  assert.equal(diff.direct.find((row) => row.name === "three").after, "0.186.1");
  assert.ok(diff.changed_packages.some((row) => row.path === "node_modules/three"));
});
test("output members are a closed census: fixed names and metadata/01.json to metadata/32.json only", () => {
  for (const name of ["preparation.json", "npm-version.stdout.log", "npm-lock-only.stderr.log", "selected-metadata.json",
    "dependency-diff.json", "candidate.patch", "patch.stderr.log", "candidate/package.json", "candidate/package-lock.json",
    "metadata/01.json", "metadata/32.json"]) assert.equal(outputMember(name), name);
  for (const name of ["metadata/00.json", "metadata/33.json", "metadata/1.json", "metadata/01.json.tgz", "../preparation.json",
    "metadata/../preparation.json", "/tmp/preparation.json", "candidate/node_modules/x.js", "candidate\\package.json",
    "preparation.json\0", "", 1]) assert.throws(() => outputMember(name), /Undeclared preparation output member/);
  assert.equal(metadataMember(1), "metadata/01.json"); assert.equal(metadataMember(32), "metadata/32.json");
  for (const index of [0, 33, 1.5, "1", -1]) assert.throws(() => metadataMember(index), /outside the plan bound/);
  for (let index = 1; index <= 32; index += 1) assert.equal(outputMember(metadataMember(index)), metadataMember(index));
});
test("registry evidence is admitted before it is written: 200, bounded, one strict JSON object", () => {
  const body = Buffer.from('{"name":"react","version":"2.0.0"}');
  assert.equal(registryEvidence(200, body).version, "2.0.0");
  assert.throws(() => registryEvidence(404, body), /unavailable/);
  assert.throws(() => registryEvidence(301, body), /unavailable/);
  for (const text of ["<html>not json</html>", '["an","array"]', '"text"', "null", '{"a":1,"a":2}', '{"a":1}tail'])
    assert.throws(() => registryEvidence(200, Buffer.from(text)));
  assert.throws(() => registryEvidence(200, Buffer.from([0xff, 0xfe, 0x7b, 0x7d])));
  assert.equal(registryEvidence(200, Buffer.concat([body, Buffer.alloc(2 * 1024 * 1024 - body.length, 0x20)])).name, "react");
  assert.throws(() => registryEvidence(200, Buffer.alloc(2 * 1024 * 1024 + 1, 0x20)), /byte buffer within its bound/);
  assert.throws(() => registryEvidence(200, '{"name":"react"}'), /byte buffer within its bound/);
});
test("strict JSON preserves ordinary values and rejects escaped duplicate keys", () => {
  assert.equal(strictJson(Buffer.from('{"name":"ok","nested":[1,true,null]}')).name, "ok");
  for (const text of ['{"a":1,"a":2}', '{"a":1,"\\u0061":2}', '{"a":[1,]}', '{"a":1}tail', '{"a":1e999}', '{"a":1,}'])
    assert.throws(() => strictJson(Buffer.from(text)));
});
