#!/usr/bin/env node
import { resolve } from "node:path";
import { compressProjection } from "./compress-projection.mjs";
import { buildDeploymentManifestWithReport } from "./deployment-manifest.mjs";

try {
  const compression = await compressProjection();
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
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
}
