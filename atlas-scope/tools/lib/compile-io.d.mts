/**
 * Types for tools/lib/compile-io.mjs (Node only: it reads and writes files). Declared so the tests can
 * drive it under `tsc` strict; `src/core/compile-model.test.ts` requires the exports to match.
 */
import type { SourceBinding } from "../../src/core/types";
import type { CompiledSet, OutputKey } from "./compile-model.mjs";
import type { Issue } from "./validate-snapshot.mjs";

export interface CompileArgs {
  source?: string;
  out?: string;
  label?: string;
  allowLegacy: boolean;
  help: boolean;
}
export interface CompileToDiskOptions {
  /** The tools/ directory of the package to compile for (its parent's parent is the repository). */
  toolsDir: string;
  source?: string;
  out?: string;
  label?: string;
  allowLegacy?: boolean;
  /** Write only this output (after compiling and checking the whole set). */
  only?: OutputKey;
  /**
   * Test seams. beforeCommitStep is called before each file of the set is moved into place (a throw
   * rolls the set back); beforeRestoreStep before each file of a rollback is restored (a throw stands
   * for a restore that cannot happen, e.g. a Windows file lock, and must leave the previous file kept).
   */
  hooks?: {
    beforeCommitStep?: (index: number, key: OutputKey) => void;
    beforeRestoreStep?: (index: number, key: OutputKey) => void;
    /**
     * Called before each open of the source or of a sibling output; a throw stands for that open failing with the
     * thrown error (an errno this host cannot produce — ELOOP, ENXIO, EACCES on a directory — is injected so).
     */
    beforeOpen?: (path: string) => void;
  };
}
export interface CompileToDiskResult {
  sourcePath: string;
  binding: SourceBinding;
  warnings: Issue[];
  set: CompiledSet;
  written: string[];
  workingTree: { sha256: string; bytes: number };
}

export declare function parseCompileArgs(argv: string[]): CompileArgs;
export declare function compileToDisk(o: CompileToDiskOptions): CompileToDiskResult;
export declare function runCompileCli(moduleUrl: string, argv: string[], only?: OutputKey): number;
