/**
 * compile-producer-emission.mjs — writes ONE file of the compiled set: src/panels/producer-emission.json, which defaulted producer fields the collector actually emitted.
 *
 * The compile itself is not here. Since 2026-09-26 there is one compiler, tools/lib/compile-model.mjs
 * (pure; the same code a browser runs), and this command is a thin wrapper over tools/lib/compile-io.mjs:
 * it reads the snapshot once, validates and binds it, compiles and checks the WHOLE set, and then writes
 * only its own file. Its reasoning — what the file carries and why each field is read rather than
 * defaulted — lives beside the code, in compile-model.mjs.
 *
 * Normally run the whole set instead: `npm run compile:data` (tools/compile-all.mjs), which cannot leave
 * this file bound to a different snapshot from the files beside it.
 *
 * Run: node tools/compile-producer-emission.mjs [--source <snapshot.json>] [--out <dir>] [--label <name>] [--allow-legacy]
 */
import { runCompileCli } from "./lib/compile-io.mjs";

process.exitCode = runCompileCli(import.meta.url, process.argv.slice(2), "producerEmission");
