#!/usr/bin/env node
import { resolve } from "node:path";
import { compressProjection } from "./compress-projection.mjs";
import { buildDeploymentManifest } from "./deployment-manifest.mjs";

try {
  const compression = await compressProjection();
  const deployment = await buildDeploymentManifest();
  process.stdout.write(
    `${JSON.stringify({
      output: resolve("dist"),
      compressedModules: compression.moduleCount,
      deploymentMembers: deployment.memberCount,
      deploymentBytes: deployment.totalBytes,
      bundleDigest: deployment.bundleDigest,
    })}\n`,
  );
} catch (error) {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
}
