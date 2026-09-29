/**
 * Build-time constants vite.config.ts defines (the `define` block of its dataset plugin).
 *
 * `__ATLAS_COMPILER_ID__`: sha256 over the one compiler's sources (tools/lib/compile-model.mjs,
 * tools/lib/validate-snapshot.mjs and contracts/engine-contract.v1.json) as this build bundled them. A
 * snapshot the reader opened is kept with the id of the compiler that compiled it, and recompiled when
 * the page's compiler differs (dataset/store.ts).
 */
declare const __ATLAS_COMPILER_ID__: string;
