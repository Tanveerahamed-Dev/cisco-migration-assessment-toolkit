/**
 * compile-all.mjs — compile the four Atlas Scope data files from ONE engine snapshot, as a set.
 *
 *   node tools/compile-all.mjs [--source <snapshot.json>] [--out <dir>] [--label <name>] [--allow-legacy]
 *
 * With no arguments it rebuilds the four TRACKED files from the tracked sample snapshot
 * (`npm run compile:data`). Any other snapshot compiles to the git-ignored `.local-data/` unless
 * `--out` names a directory under `.local-data/` or one outside the repository (never `src/`, `dist/`,
 * `public/`, `review/` or any other in-repository location, Git-ignored or not). The source is read once, validated
 * (tools/lib/validate-snapshot.mjs), bound (tools/source-binding.mjs), compiled by the one pure compiler
 * (tools/lib/compile-model.mjs) and written atomically as a set (tools/lib/compile-io.mjs): a failure
 * leaves the previous set intact. Exit 0 = compiled, 1 = the snapshot was refused (a coded reason is
 * printed), 2 = the command was refused.
 */
import { runCompileCli } from "./lib/compile-io.mjs";

process.exitCode = runCompileCli(import.meta.url, process.argv.slice(2));
