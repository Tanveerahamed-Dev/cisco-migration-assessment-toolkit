#!/usr/bin/env node
/**
 * rename-snapshot.mjs — a deterministic ISOMORPHIC rename of an engine snapshot: every device host name
 * replaced, consistently, everywhere it occurs (object keys and string values alike), and nothing else
 * changed. The renamed snapshot is the same network under other names, so every property of the app
 * that is not a fact about the tracked sample must hold on it unchanged. That is the phase gate's
 * RENAME LEG:
 *
 *   node review/rename-snapshot.mjs --compile
 *   ATLAS_DATASET_DIR=.local-data/rename-compiled npx vitest run
 *
 * Every invariant test must pass on the renamed dataset; the golden tier (src/test-support/golden-sample.ts)
 * reports itself skipped by name. A test that fails there has a sample host name, or an order that only
 * the sample's names produce, baked into it.
 *
 * THE MAPPING. The hosts are the snapshot's own device inventory (`devices` keys) and the cable map's
 * nodes (`cable_map.nodes[].host`) — derived from the snapshot, never a list. They are sorted, and the
 * i-th of n becomes `rn-<n - i>` (zero-padded): the new names sort in the REVERSE order of the old ones,
 * so an assumption about which host sorts first is exposed as well as an assumption about a name.
 * A host is replaced where it stands as a whole token — not preceded by a letter, digit or underscore and
 * not followed by one — longest name first, so `access1` never rewrites the front of `access10`. The run
 * refuses (exit 1) when a new name already occurs in the snapshot, since the rename would then merge two
 * things into one.
 *
 * Usage: node review/rename-snapshot.mjs [--source <snapshot.json>] [--out <file>] [--compile] [--compiled-out <dir>]
 *   --source        default: the tracked engine sample (webapp/sample_data/sample_fleet.snapshot.json)
 *   --out           default: .local-data/rename/<source stem>.renamed.snapshot.json (Git-ignored); for the
 *                   sample, .local-data/rename/sample_fleet.renamed.snapshot.json
 *   --compile       also compile it with the one compiler: for the default renamed sample into
 *                   .local-data/rename-compiled/ (the rename leg), otherwise into `<renamed file>-compiled/`
 *                   beside the renamed file — never over the rename leg's directory
 *   --compiled-out  compile into this directory instead
 * Output is compact JSON with a trailing LF; the same input always gives the same bytes.
 */
import { spawnSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { basename, dirname, relative, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DEFAULT_SOURCE = resolve(PKG, "..", "webapp", "sample_data", "sample_fleet.snapshot.json");
const DEFAULT_OUT = resolve(PKG, ".local-data", "rename", "sample_fleet.renamed.snapshot.json");
const DEFAULT_COMPILED = resolve(PKG, ".local-data", "rename-compiled");

/** @param {unknown} v @returns {v is Record<string, unknown>} */
const isObject = (v) => v !== null && typeof v === "object" && !Array.isArray(v);

/**
 * The host names a snapshot names: its device inventory and its cable map's nodes.
 * @param {Record<string, unknown>} snap
 * @returns {string[]}
 */
export function hostsOf(snap) {
  const hosts = new Set();
  if (isObject(snap.devices)) for (const h of Object.keys(snap.devices)) hosts.add(h);
  const nodes = isObject(snap.cable_map) && Array.isArray(snap.cable_map.nodes) ? snap.cable_map.nodes : [];
  for (const n of nodes) if (isObject(n) && typeof n.host === "string" && n.host.trim() !== "") hosts.add(n.host);
  return [...hosts].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
}

const escape = (/** @type {string} */ s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/**
 * Rename every host of `snap`. Pure: returns a new snapshot and the mapping; throws on a collision.
 * @param {Record<string, unknown>} snap
 * @returns {{ snapshot: Record<string, unknown>; mapping: Record<string, string> }}
 */
export function renameSnapshot(snap) {
  const hosts = hostsOf(snap);
  if (hosts.length === 0) throw new Error("rename-snapshot: the snapshot names no host (no `devices`, no `cable_map.nodes`) — nothing to rename.");
  const width = String(hosts.length).length;
  /** @type {Record<string, string>} */
  const mapping = {};
  hosts.forEach((h, i) => {
    mapping[h] = `rn-${String(hosts.length - i).padStart(width, "0")}`;
  });
  const text = JSON.stringify(snap);
  for (const n of Object.values(mapping)) {
    if (new RegExp(`(?<![A-Za-z0-9_])${escape(n)}(?![A-Za-z0-9_])`).test(text)) {
      throw new Error(`rename-snapshot: the new name ${n} already occurs in the snapshot; renaming onto it would merge two things.`);
    }
  }
  const byLength = [...hosts].sort((a, b) => b.length - a.length || (a < b ? -1 : 1));
  const token = new RegExp(`(?<![A-Za-z0-9_])(?:${byLength.map(escape).join("|")})(?![A-Za-z0-9_])`, "g");
  const sub = (/** @type {string} */ s) => s.replace(token, (m) => mapping[m] ?? m);
  /** @param {unknown} v @returns {unknown} */
  const walk = (v) => {
    if (typeof v === "string") return sub(v);
    if (Array.isArray(v)) return v.map(walk);
    if (isObject(v)) {
      /** @type {Record<string, unknown>} */
      const out = {};
      for (const [k, x] of Object.entries(v)) {
        const nk = sub(k);
        if (Object.prototype.hasOwnProperty.call(out, nk)) throw new Error(`rename-snapshot: two keys became ${nk}; the rename is not one-to-one here.`);
        out[nk] = walk(x);
      }
      return out;
    }
    return v;
  };
  return { snapshot: /** @type {Record<string, unknown>} */ (walk(snap)), mapping };
}

/** The renamed snapshot's exact bytes: compact JSON and one trailing LF. @param {Record<string, unknown>} snap */
export const serialiseRenamed = (snap) => `${JSON.stringify(snap)}\n`;

/** A path as printed: package-relative, so a log never carries the home directory (a privacy marker). */
const shown = (/** @type {string} */ p) => relative(PKG, p).split("\\").join("/") || ".";

const USAGE = "usage: node review/rename-snapshot.mjs [--source <snapshot.json>] [--out <file>] [--compile] [--compiled-out <dir>]";

/** A snapshot file name without its `.snapshot.json` / `.json` suffix. @param {string} p */
const stemOf = (p) => basename(p).replace(/(\.snapshot)?\.json$/i, "");

/**
 * Where a run reads and writes — pure, so the choice is tested (src/core/dataset.rename.test.ts). Every
 * output follows its INPUT (phase 3.5, P3E-V5): `--compile` used to write the fixed
 * .local-data/rename-compiled whatever --source / --out said, so renaming another snapshot overwrote the
 * rename leg's compiled dataset under the rename leg's name.
 *   - the renamed file: --out, else .local-data/rename/<source stem>.renamed.snapshot.json (for the tracked
 *     sample that is the documented sample_fleet.renamed.snapshot.json);
 *   - the compiled directory: --compiled-out, else .local-data/rename-compiled for the default renamed
 *     file (the documented rename leg), else `<renamed file without .json>-compiled` beside it.
 * @param {string[]} argv
 * @returns {{ source: string; out: string; compile: boolean; compiled: string } | { usage: string }}
 */
export function planOutputs(argv) {
  let source = DEFAULT_SOURCE;
  /** @type {string | null} */ let out = null;
  /** @type {string | null} */ let compiled = null;
  let compile = false;
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === "--source") source = resolve(argv[++i] ?? "");
    else if (a === "--out") out = resolve(argv[++i] ?? "");
    else if (a === "--compiled-out") compiled = resolve(argv[++i] ?? "");
    else if (a === "--compile") compile = true;
    else return { usage: USAGE };
  }
  const renamedFile = out ?? resolve(PKG, ".local-data", "rename", `${stemOf(source)}.renamed.snapshot.json`);
  const compiledDir =
    compiled ?? (renamedFile === DEFAULT_OUT ? DEFAULT_COMPILED : resolve(dirname(renamedFile), `${basename(renamedFile).replace(/\.json$/i, "")}-compiled`));
  return { source, out: renamedFile, compile, compiled: compiledDir };
}

/** @param {string[]} argv */
function main(argv) {
  const plan = planOutputs(argv);
  if ("usage" in plan) {
    process.stderr.write(`${plan.usage}\n`);
    return 2;
  }
  const { source, out, compile, compiled } = plan;
  let snap;
  try {
    snap = JSON.parse(readFileSync(source, "utf8"));
  } catch (e) {
    process.stderr.write(`rename-snapshot: cannot read ${shown(source)}:${e instanceof Error ? e.message : String(e)}\n`);
    return 1;
  }
  let renamed;
  try {
    renamed = renameSnapshot(snap);
  } catch (e) {
    process.stderr.write(`${e instanceof Error ? e.message : String(e)}\n`);
    return 1;
  }
  mkdirSync(dirname(out), { recursive: true });
  writeFileSync(out, serialiseRenamed(renamed.snapshot));
  process.stdout.write(`renamed ${Object.keys(renamed.mapping).length} hosts -> ${shown(out)}\n`);
  if (!compile) return 0;
  const r = spawnSync(process.execPath, [resolve(PKG, "tools", "compile-all.mjs"), "--source", out, "--out", compiled], { stdio: "inherit" });
  if (r.status !== 0) {
    process.stderr.write(`rename-snapshot: compiling the renamed snapshot failed (exit ${r.status}).\n`);
    return 1;
  }
  process.stdout.write(`compiled -> ${shown(compiled)}\nnext: ATLAS_DATASET_DIR=${shown(compiled)} npx vitest run\n`);
  return 0;
}

if (process.argv[1] !== undefined && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  process.exitCode = main(process.argv.slice(2));
}
