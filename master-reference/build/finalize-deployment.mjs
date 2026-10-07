#!/usr/bin/env node
import { resolve } from "node:path";
import { compressProjection } from "./compress-projection.mjs";
import {
  buildDeploymentManifestWithReport,
  getDeploymentRefusalDiagnostic,
} from "./deployment-manifest.mjs";

let phase = "projection_compression";
try {
  const compression = await compressProjection();
  phase = "deployment_manifest";
  const { receipt: deployment, physicalBundleBytes } = await buildDeploymentManifestWithReport();
  process.stdout.write(
    `${JSON.stringify({
      output: resolve("dist"),
      compressedModules: compression.moduleCount,
      deploymentMembers: deployment.memberCount,
      deploymentBytes: deployment.totalBytes,
      physicalBundleBytes,
      hostingEligibility: "not_evaluated",
      bundleDigest: deployment.bundleDigest,
    })}\n`,
  );
} catch (error) {
  process.exitCode = 1;
  let diagnosticLine = "";
  try {
    const diagnostic = getDeploymentRefusalDiagnostic(error);
    diagnosticLine = `${JSON.stringify({ phase, ...(diagnostic ?? { kind: "unclassified" }) })}\n`;
  } catch {
    // Diagnostic failure must not expose the original error or change exit1.
  }
  process.stderr.write(`deployment finalization failed\n${diagnosticLine}`);
}
