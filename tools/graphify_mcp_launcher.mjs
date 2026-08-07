#!/usr/bin/env node

// Cross-platform Graphify MCP launcher. On Windows, `python` can resolve to the
// Microsoft Store alias even when the real interpreter is installed elsewhere.
// Select an interpreter that can actually import graphify.serve before attaching
// it to MCP stdio. No packages are installed and no network access is attempted.

import { spawn, spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function localGraphifyPython() {
  const pin = resolve(repoRoot, "graphify-out", ".graphify_python");
  if (!existsSync(pin)) return null;

  let raw;
  try {
    raw = readFileSync(pin, "utf8").trim();
  } catch {
    return null;
  }
  if (!raw) return null;

  if (process.platform === "win32") {
    const posixDrive = /^\/([A-Za-z])\/(.*)$/.exec(raw);
    if (posixDrive) {
      return `${posixDrive[1].toUpperCase()}:\\${posixDrive[2].replaceAll("/", "\\")}`;
    }
  }
  return raw;
}

function interpreterCandidates() {
  const candidates = [];
  const add = (command, prefixArgs = []) => {
    if (!command) return;
    const key = JSON.stringify([command, prefixArgs]);
    if (!candidates.some((candidate) => candidate.key === key)) {
      candidates.push({ command, prefixArgs, key });
    }
  };

  add(process.env.GRAPHIFY_PYTHON);
  add(localGraphifyPython());
  if (process.platform === "win32") {
    add("py", ["-3.12"]);
    add("py", ["-3"]);
    add("python");
    add("python3");
  } else {
    add("python3");
    add("python");
  }
  return candidates;
}

export const IMPORT_PROBE = ["-c", "import graphify.serve"];

export function selectInterpreter(
  candidates,
  { runner = spawnSync, cwd = repoRoot } = {},
) {
  for (const candidate of candidates) {
    const result = runner(
      candidate.command,
      [...candidate.prefixArgs, ...IMPORT_PROBE],
      {
        cwd,
        stdio: "ignore",
        timeout: 10_000,
        windowsHide: true,
      },
    );
    if (result.status === 0) return candidate;
  }
  return null;
}

export function childExitCode(code, signal) {
  if (code !== null && code !== undefined) return code;
  if (signal === "SIGINT") return 130;
  if (signal === "SIGTERM") return 143;
  return 1;
}

export function main() {
  const selected = selectInterpreter(interpreterCandidates());
  if (!selected) {
    console.error(
      "Graphify MCP could not find a Python interpreter that imports graphify.serve. " +
        "Install Graphify or set GRAPHIFY_PYTHON to the correct interpreter.",
    );
    process.exit(1);
  }

  if (process.argv.includes("--probe")) {
    console.log(JSON.stringify({ command: selected.command, args: selected.prefixArgs }));
    process.exit(0);
  }

  const child = spawn(
    selected.command,
    [...selected.prefixArgs, "-m", "graphify.serve"],
    {
      cwd: repoRoot,
      stdio: "inherit",
      windowsHide: true,
    },
  );

  for (const signal of ["SIGINT", "SIGTERM"]) {
    process.on(signal, () => {
      if (!child.killed) child.kill(signal);
    });
  }

  child.on("error", (error) => {
    console.error(`Graphify MCP failed to start: ${error.message}`);
    process.exit(1);
  });

  child.on("exit", (code, signal) => {
    process.exit(childExitCode(code, signal));
  });
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main();
}
