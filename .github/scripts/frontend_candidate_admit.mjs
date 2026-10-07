/** Reviewed-current-code bridge only. Never import a producer subject or archive module. */
import { readFileSync } from "node:fs";
import { admitMetadata, admitCandidate, planManifest } from "./frontend_dependency_prepare.mjs";
if (process.env.GITHUB_ACTIONS !== "true" || process.env.RUNNER_ENVIRONMENT !== "github-hosted"
  || process.platform !== "linux" || process.version !== "v24.19.0") throw new Error("Hosted pinned bridge only");
if (process.argv.length !== 3) throw new Error("One receiver-owned payload path required");
const payload = JSON.parse(readFileSync(process.argv[2], "utf8"));
if (!["metadata", "candidate"].includes(payload.mode)) throw new Error("Unknown current-code bridge profile");
const metadata = new Map(payload.plan.changes.map((change, index) =>
  [change.name, admitMetadata(payload.metadata[index], change)]));
if (payload.mode === "metadata") {
  process.stdout.write(JSON.stringify({ metadata: Object.fromEntries(metadata) }));
} else {
const diff = admitCandidate(payload.plan, payload.before_manifest, payload.before_lock,
  payload.candidate_manifest, payload.candidate_lock, metadata);
process.stdout.write(JSON.stringify({ diff, metadata: Object.fromEntries(metadata),
  manifest_text: JSON.stringify(planManifest(payload.plan, payload.before_manifest), null, 2) + "\n" }));
}
