/* oxlint-disable nextjs/no-html-link-for-pages -- full-document navigation preserves the connect-src 'none' privacy boundary. */
"use client";

import { useEffect, useMemo, useState } from "react";
import {
  dossierHref,
  humanBytes,
  loadProjection,
  shortDigest,
  sourceHref,
} from "./SourceExplorerData";
import type {
  ProjectionModule,
  SourceChunkPayload,
  SourceFilePayload,
  SourceFileRecord,
  SourceLine,
} from "./SourceExplorerTypes";
import styles from "./SourceExplorer.module.css";

type FileLoadState =
  | { state: "loading" }
  | { state: "missing"; message: string }
  | {
      state: "ready";
      module: ProjectionModule;
      file: SourceFileRecord;
      source: SourceFilePayload | null;
      chunk: SourceChunkPayload | null;
      chunkIndex: number | null;
    };

function lineFromHash(): number | null {
  const match = window.location.hash.match(/^#L(\d+)$/);
  if (!match) return null;
  const value = Number(match[1]);
  return Number.isInteger(value) && value > 0 ? value : null;
}

function Missing({ value, reason }: { value?: string | null; reason: string }) {
  return value ? <>{value}</> : <span className={styles.missingValue}>{reason}</span>;
}

function LineDossier({ line }: { line: SourceLine | null }) {
  if (!line) {
    return (
      <aside className={styles.lineDossier} aria-live="polite">
        <h2>Select a line</h2>
        <p>Choose a line number to inspect its structural mapping and explicit unknowns.</p>
      </aside>
    );
  }
  const uncertainty = [...new Set(line.unresolvedReasons)];
  const depthLabels = ["inventoried", "structural", "behavioral", "verified", "human reviewed"];
  const structuredEffects = line.securityAndPrivacyEffect
    ? JSON.stringify(line.securityAndPrivacyEffect)
    : null;
  const inputOutput = line.inputsAndOutputs ? JSON.stringify(line.inputsAndOutputs) : null;
  return (
    <aside className={styles.lineDossier} aria-live="polite">
      <div>
        <span className={styles.badge} data-state={line.explanationDepth ? "parsed" : "metadata_only"}>
          Depth {line.explanationDepth} · {depthLabels[line.explanationDepth] ?? "unknown"}
        </span>
        <h2>Line {line.number}</h2>
      </div>
      <div className={styles.depthMeter} aria-label={`Explanation depth ${line.explanationDepth} of 4`}>
        {[0, 1, 2, 3, 4].map((depth) => (
          <i data-on={depth <= line.explanationDepth ? "true" : "false"} key={depth} />
        ))}
      </div>
      <p>{line.explanationDepth < 2
        ? "This record establishes inventory or syntax ownership. It does not prove execution, correctness, or downstream impact."
        : "This depth is preserved from the compiler record; its evidence and unresolved reasons remain separately visible."}</p>
      <dl className={styles.factList}>
        <div><dt>Line record</dt><dd><Missing value={line.recordId} reason="Blank line: inventory only" /></dd></div>
        <div><dt>Syntax kind</dt><dd><Missing value={line.syntaxKind} reason="Not structurally mapped" /></dd></div>
        <div><dt>Mapping basis</dt><dd><Missing value={line.structuralMappingBasis} reason="Blank line: inventory only" /></dd></div>
        <div>
          <dt>Containing symbol</dt>
          <dd>
            {line.containingSymbolId ? (
              <a href={dossierHref("symbol", line.containingSymbolId)}>{line.containingSymbol}</a>
            ) : (
              <Missing value={line.containingSymbol} reason="No containing symbol emitted" />
            )}
          </dd>
        </div>
        <div><dt>Semantic entity</dt><dd><Missing value={line.semanticEntity} reason="Not emitted" /></dd></div>
        <div><dt>Owner</dt><dd><Missing value={line.owner} reason="Not emitted" /></dd></div>
        <div><dt>Behavior group</dt><dd>{line.behaviorGroup.length ? line.behaviorGroup.join(" · ") : <span className={styles.missingValue}>Not emitted</span>}</dd></div>
        <div><dt>Inputs and outputs</dt><dd><Missing value={inputOutput} reason="Not emitted" /></dd></div>
        <div><dt>Claims influenced</dt><dd>{line.claimsInfluenced.length ? line.claimsInfluenced.join(" · ") : <span className={styles.missingValue}>None linked</span>}</dd></div>
        <div><dt>Tests covering this line</dt><dd>{line.testsCoveringIt.length ? line.testsCoveringIt.map((test) => <a href={dossierHref("test", test)} key={test}>{test}</a>) : <span className={styles.missingValue}>No test linkage emitted</span>}</dd></div>
        <div><dt>Test coverage state</dt><dd>{line.testCoverageState.replaceAll("_", " ")}</dd></div>
        <div><dt>Runtime trace</dt><dd className={line.runtimeTraceState === "not_collected" || line.runtimeTraceState === "not_emitted" ? styles.missingValue : undefined}>{line.runtimeTraceState.replaceAll("_", " ")}</dd></div>
        <div><dt>GUI / artifact consumers</dt><dd>{line.guiOrArtifactConsumers.length ? line.guiOrArtifactConsumers.join(" · ") : <span className={styles.missingValue}>None linked</span>}</dd></div>
        <div><dt>Security / privacy effect</dt><dd><Missing value={structuredEffects} reason="Not reviewed" /></dd></div>
        <div><dt>Current / historical</dt><dd><Missing value={line.currentOrHistorical} reason="Not classified" /></dd></div>
        <div><dt>Callers / dependencies</dt><dd>{line.callersAndDependencies.length ? line.callersAndDependencies.join(" · ") : <span className={styles.missingValue}>None linked</span>}</dd></div>
        <div><dt>Change impact</dt><dd className={line.callersAndDependencies.length || line.guiOrArtifactConsumers.length ? undefined : styles.missingValue}>{[...line.callersAndDependencies, ...line.guiOrArtifactConsumers].join(" · ") || "Not established"}</dd></div>
        <div><dt>Line digest</dt><dd><code>{shortDigest(line.lineDigest, 20)}</code></dd></div>
      </dl>
      <div className={styles.uncertainty}>
        <strong>Explicit uncertainty</strong>
        <ul>{uncertainty.map((reason) => <li key={reason}>{reason.replaceAll("_", " ")}</li>)}</ul>
      </div>
    </aside>
  );
}

export function SourceFileView({ path }: { path: string }) {
  const [loadState, setLoadState] = useState<FileLoadState>({ state: "loading" });
  const [selectedLine, setSelectedLine] = useState<number | null>(null);

  useEffect(() => {
    let active = true;
    void loadProjection()
      .then(async (module) => {
        const files = (await module.loadMetadata("files")) as SourceFileRecord[];
        const file = files.find((candidate) => candidate.path === path);
        if (!file) {
          if (active) setLoadState({ state: "missing", message: "This path is not in the bound Git-tree census." });
          return;
        }
        const source = await module.loadSource(path);
        if (!active) return;
        const target = lineFromHash();
        const requested = target && source && target <= source.lineCount ? target : 1;
        const chunkIndex = source?.chunks.findIndex((chunk) => chunk.startLine <= requested && chunk.endLine >= requested) ?? -1;
        const chunk = source && chunkIndex >= 0 ? await module.loadSourceChunk(path, chunkIndex) : null;
        if (!active) return;
        setLoadState({ state: "ready", module, file, source, chunk, chunkIndex: chunkIndex >= 0 ? chunkIndex : null });
        if (target && chunk) {
          setSelectedLine(target);
          window.requestAnimationFrame(() => document.getElementById(`L${target}`)?.scrollIntoView());
        }
      })
      .catch(() => {
        if (active) setLoadState({ state: "missing", message: "The generated projection is absent from this build." });
      });
    return () => {
      active = false;
    };
  }, [path]);

  const selected = useMemo(() => {
    if (loadState.state !== "ready" || !loadState.source || !selectedLine) return null;
    return loadState.chunk?.segments.find((line) => line.number === selectedLine) ?? null;
  }, [loadState, selectedLine]);

  function openChunk(index: number, line?: number) {
    if (loadState.state !== "ready" || !loadState.source) return;
    const bounded = Math.max(0, Math.min(index, loadState.source.chunkCount - 1));
    void loadState.module.loadSourceChunk(path, bounded).then((chunk) => {
      setLoadState((current) => current.state === "ready" ? { ...current, chunk, chunkIndex: bounded } : current);
      setSelectedLine(line ?? null);
      if (line) window.requestAnimationFrame(() => document.getElementById(`L${line}`)?.scrollIntoView());
    });
  }

  if (loadState.state === "loading") {
    return <output className={styles.loading}><span className={styles.loadingPulse} /><strong>Loading file metadata…</strong></output>;
  }
  if (loadState.state === "missing") {
    return <div className={styles.error}><strong>Source path unavailable</strong><p>{loadState.message}</p><a href="/source">Return to the tracked tree</a></div>;
  }

  const { file, source, chunk, chunkIndex, module } = loadState;
  const pieces = file.path.split("/");
  const pageLines = chunk?.segments ?? [];
  const chunkDescriptor = source && chunkIndex != null ? source.chunks[chunkIndex] : null;
  const firstVisible = chunkDescriptor?.startLine ?? 0;
  const lastVisible = chunkDescriptor?.endLine ?? 0;
  return (
    <div>
      <header className={styles.sourceHeader}>
        <div>
          <nav className={styles.breadcrumbs} aria-label="Source path">
            <a href="/source">source</a>
            {pieces.map((piece, index) => <span key={`${piece}-${index}`}>/ {piece}</span>)}
          </nav>
          <h1>{file.path}</h1>
          <p>{file.roles.join(" · ")} · bound to {module.projection.sourceCommit.slice(0, 12)}</p>
        </div>
        <span className={styles.badge} data-state={file.privacyExposure}>
          {source ? "safe text · lazy loaded" : file.privacyExposure}
        </span>
      </header>

      <dl className={styles.sourceMeta}>
        <div><dt>Parser</dt><dd>{file.parser ?? "not applicable"} · {file.parserMode ?? "unknown mode"}</dd></div>
        <div><dt>Extent</dt><dd>{file.lineCount.toLocaleString()} lines · {humanBytes(file.sizeBytes)}</dd></div>
        <div><dt>Content digest</dt><dd><code>{shortDigest(file.contentDigest, 20)}</code></dd></div>
        <div><dt>Proof depth</dt><dd>Level 1 structural where mapped</dd></div>
      </dl>

      {!source ? (
        <div className={styles.notice}>
          <strong>Content intentionally opaque</strong>
          <span>
            This tracked path is classified <code>{file.privacyExposure}</code> / <code>{file.parseStatus}</code>.
            Atlas exposes its digest, media type, role, and classification only. No source module exists.
          </span>
        </div>
      ) : (
        <>
          <div className={styles.resultCount}>
            <span>Showing bounded chunk <strong>{(chunkIndex ?? 0) + 1}/{source.chunkCount}</strong> · lines <strong>{firstVisible}–{lastVisible}</strong> of {source.lineCount.toLocaleString()}</span>
            <span>
              {chunkIndex != null && chunkIndex > 0 ? <a href={sourceHref(path, source.chunks[chunkIndex - 1].startLine)} onClick={(event) => { event.preventDefault(); openChunk(chunkIndex - 1); }}>← Previous chunk</a> : null}
              {chunkIndex != null && chunkIndex > 0 && chunkIndex + 1 < source.chunkCount ? " · " : null}
              {chunkIndex != null && chunkIndex + 1 < source.chunkCount ? <a href={sourceHref(path, source.chunks[chunkIndex + 1].startLine)} onClick={(event) => { event.preventDefault(); openChunk(chunkIndex + 1); }}>Next chunk →</a> : null}
            </span>
          </div>
          <div className={styles.sourceLayout}>
            <div className={styles.codePane} aria-label={`Source for ${file.path}`}>
              <table className={styles.codeTable}>
                <caption className="visually-hidden">
                  Source lines, exact text, and structural syntax kind for {file.path}
                </caption>
                <thead className="visually-hidden">
                  <tr>
                    <th scope="col">Line</th>
                    <th scope="col">Source text</th>
                    <th scope="col">Syntax kind</th>
                  </tr>
                </thead>
                <tbody>
                  {pageLines.map((line) => (
                    <tr className={styles.codeLine} data-selected={selectedLine === line.number ? "true" : "false"} id={line.fragmentIndex === 0 ? `L${line.number}` : `L${line.number}-part-${line.fragmentIndex + 1}`} key={`${line.number}-${line.fragmentIndex}`}>
                      <th className={styles.lineNumber} scope="row">
                        <a
                          aria-label={`Inspect line ${line.number}`}
                          href={sourceHref(path, line.number)}
                          onClick={() => setSelectedLine(line.number)}
                        >
                          {line.fragmentIndex === 0 ? line.number : `↳ ${line.number}.${line.fragmentIndex + 1}`}
                        </a>
                      </th>
                      <td className={styles.lineText}>{line.text || " "}</td>
                      <td className={styles.lineKind}>{line.fragmentCount > 1 ? `part ${line.fragmentIndex + 1}/${line.fragmentCount} · ` : ""}{line.syntaxKind ?? ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <LineDossier line={selected} />
          </div>
        </>
      )}
    </div>
  );
}
