#!/usr/bin/env node

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

export const REQUIRED_NODE_ENGINE = ">=24.18.0 <25";

const MINIMUM_NODE = Object.freeze([24, 18, 0]);
const STABLE_NODE_VERSION = /^(?:v)?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/u;

function parseStableNodeVersion(runtimeVersion) {
  if (typeof runtimeVersion !== "string") {
    throw new Error(`Node runtime version must be a string; found ${typeof runtimeVersion}`);
  }
  const match = STABLE_NODE_VERSION.exec(runtimeVersion);
  if (!match) {
    throw new Error(
      `Node runtime must be a stable semantic version (MAJOR.MINOR.PATCH); found ${JSON.stringify(runtimeVersion)}`,
    );
  }
  return match.slice(1).map(Number);
}

function isAtLeastMinimum([major, minor, patch]) {
  const [minimumMajor, minimumMinor, minimumPatch] = MINIMUM_NODE;
  return major > minimumMajor
    || (major === minimumMajor && minor > minimumMinor)
    || (major === minimumMajor && minor === minimumMinor && patch >= minimumPatch);
}

export function assertNodePlatform({ manifestEngine, runtimeVersion }) {
  if (manifestEngine !== REQUIRED_NODE_ENGINE) {
    throw new Error(
      `package.json engines.node must be exactly ${JSON.stringify(REQUIRED_NODE_ENGINE)}; found ${JSON.stringify(manifestEngine)}`,
    );
  }

  const parsed = parseStableNodeVersion(runtimeVersion);
  if (parsed[0] !== 24 || !isAtLeastMinimum(parsed)) {
    throw new Error(`AssessHub requires Node ${REQUIRED_NODE_ENGINE}; found ${runtimeVersion}`);
  }
  return parsed.join(".");
}

function readManifestEngine() {
  const manifestUrl = new URL("../package.json", import.meta.url);
  let manifest;
  try {
    manifest = JSON.parse(readFileSync(manifestUrl, "utf8"));
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(`Unable to read the AssessHub package manifest: ${detail}`, { cause: error });
  }
  return manifest?.engines?.node;
}

export function verifyCurrentNode() {
  return assertNodePlatform({
    manifestEngine: readManifestEngine(),
    runtimeVersion: process.versions.node,
  });
}

const invokedUrl = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : null;
if (invokedUrl === import.meta.url) {
  try {
    const runtimeVersion = verifyCurrentNode();
    console.log(`Node platform verified: ${runtimeVersion} (${REQUIRED_NODE_ENGINE})`);
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}
