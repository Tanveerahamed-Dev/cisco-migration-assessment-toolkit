export type CoverageCensusDepth = {
  identity_depth_files: number;
  identity_depth_nonblank_lines_deferred: number;
};

export function proofCardCoverageNote(
  card: "lines" | "symbols",
  censusDepth: CoverageCensusDepth | undefined,
  recordCounts: Record<string, number | undefined> | undefined,
): string;
