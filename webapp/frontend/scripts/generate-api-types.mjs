import { readFileSync, writeFileSync, mkdirSync, mkdtempSync, rmSync, realpathSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve, join } from "node:path";
import { tmpdir } from "node:os";
import { spawnSync } from "node:child_process";
import { requireLocalReferences, generationMode } from "./generation-policy.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const input = join(root, ".generated", "openapi.json");
const target = join(root, "src", "generated", "openapi.ts");
const mode = generationMode(process.argv.slice(2));
const check = mode === "check";
// Review output is a fresh, fixed hosted path; it never replaces the committed target.
let reviewTarget;
if (mode === "review") {
  if (process.env.GITHUB_ACTIONS !== "true" || process.env.RUNNER_ENVIRONMENT !== "github-hosted"
      || process.env.RUNNER_OS !== "Linux" || process.env.GITHUB_JOB !== "frontend") {
    throw new Error("API review generation requires the hosted frontend job");
  }
  const directory = join(realpathSync(process.env.RUNNER_TEMP), "ui-projection-contract");
  const checkout = realpathSync(resolve(root, "../.."));
  if (realpathSync(directory) !== directory || directory === checkout || directory.startsWith(checkout + "/")) {
    throw new Error("API review directory must be ordinary and outside the checkout");
  }
  reviewTarget = join(directory, "openapi.ts");
  if (existsSync(reviewTarget)) throw new Error("API review output must be fresh");
}
const schema = JSON.parse(readFileSync(input, "utf8"));
// Only the actual offline app export is admitted; generation never resolves remote references.
requireLocalReferences(schema);
if (!schema.paths?.["/api/snapshots/{snapshot_id}/ui-projection/{view}"]) {
  throw new Error("Missing engine projection route in app OpenAPI export");
}
const temp = mkdtempSync(join(tmpdir(), "atlas-api-types-"));
try {
  const output = join(temp, "openapi.ts");
  const result = spawnSync(process.execPath, [join(root, "node_modules/openapi-typescript/bin/cli.js"),
    input, "--output", output, "--redocly", join(root, "redocly.yaml"),
    "--immutable", "--alphabetize", "--array-length", "--default-non-nullable", "false"],
  { cwd: root, stdio: "inherit" });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exitCode = result.status || 1;
  else {
    const bytes = readFileSync(output);
    if (check) {
      let existing;
      try { existing = readFileSync(target); } catch { /* missing is drift */ }
      if (!existing || !existing.equals(bytes)) {
        console.error("Generated API types differ from the actual app schema; run api:generate.");
        process.exitCode = 1;
      } else console.log("Generated API types match the actual app schema.");
    } else if (mode === "review") {
      writeFileSync(reviewTarget, bytes, { flag: "wx", mode: 0o600 });
    } else {
      mkdirSync(dirname(target), { recursive: true });
      writeFileSync(target, bytes);
    }
  }
} finally { rmSync(temp, { recursive: true, force: true }); }
