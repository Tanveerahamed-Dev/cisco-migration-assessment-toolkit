/* oxlint-disable nextjs/no-html-link-for-pages -- full-document navigation preserves the connect-src 'none' privacy boundary. */
"use client";

import { useEffect, useMemo, useState } from "react";
import { humanBytes, loadProjection, shortDigest, sourceHref } from "./SourceExplorerData";
import type { ProjectionLoadState, SourceFileRecord } from "./SourceExplorerTypes";
import styles from "./SourceExplorer.module.css";

type SourceExplorerProps = {
  initialQuery?: string;
  initialLanguage?: string;
  initialExposure?: string;
};

const NO_FILES: SourceFileRecord[] = [];

function setExplorerUrl(query: string, language: string, exposure: string) {
  const params = new URLSearchParams();
  if (query.trim()) params.set("q", query.trim());
  if (language !== "all") params.set("language", language);
  if (exposure !== "all") params.set("exposure", exposure);
  window.history.replaceState(null, "", `/source${params.size ? `?${params}` : ""}`);
}

function groupFiles(files: SourceFileRecord[]) {
  const groups = new Map<string, SourceFileRecord[]>();
  for (const file of files) {
    const slash = file.path.indexOf("/");
    const key = slash === -1 ? "Repository root" : file.path.slice(0, slash);
    const current = groups.get(key) ?? [];
    current.push(file);
    groups.set(key, current);
  }
  return [...groups.entries()]
    .map(([name, entries]) => [name, entries.sort((a, b) => a.path.localeCompare(b.path))] as const)
    .sort(([left], [right]) => left.localeCompare(right));
}

function PendingProjection() {
  return (
    <output className={styles.loading}>
      <span className={styles.loadingPulse} aria-hidden="true" />
      <strong>Opening the source-bound projection…</strong>
      <span>Metadata loads first. File text remains in per-file lazy modules.</span>
    </output>
  );
}

export function SourceExplorer({
  initialQuery = "",
  initialLanguage = "all",
  initialExposure = "all",
}: SourceExplorerProps) {
  const [loadState, setLoadState] = useState<ProjectionLoadState>({ state: "loading" });
  const [query, setQuery] = useState(initialQuery);
  const [language, setLanguage] = useState(initialLanguage);
  const [exposure, setExposure] = useState(initialExposure);

  useEffect(() => {
    let active = true;
    void loadProjection()
      .then(async (module) => {
        const files = (await module.loadMetadata("files")) as SourceFileRecord[];
        if (active) setLoadState({ state: "ready", module, files });
      })
      .catch(() => {
        if (active) {
          setLoadState({
            state: "missing",
            message:
              "No generated projection is available in this build. Run the compiler and projection adapter; the UI will not invent a partial repository universe.",
          });
        }
      });
    return () => {
      active = false;
    };
  }, []);

  const index = loadState.state === "ready" ? loadState.module.projection : null;
  const files = loadState.state === "ready" ? loadState.files : NO_FILES;
  const languages = useMemo(
    () => [...new Set(files.map((file) => file.language))].sort(),
    [files],
  );
  const exposures = useMemo(
    () => [...new Set(files.map((file) => file.privacyExposure))].sort(),
    [files],
  );
  const filtered = useMemo(() => {
    if (!index) return [];
    const needle = query.trim().toLowerCase();
    return files.filter((file) => {
      if (language !== "all" && file.language !== language) return false;
      if (exposure !== "all" && file.privacyExposure !== exposure) return false;
      if (!needle) return true;
      return [file.path, file.language, file.mediaType, ...file.roles]
        .join(" ")
        .toLowerCase()
        .includes(needle);
    });
  }, [exposure, files, index, language, query]);
  const grouped = useMemo(() => groupFiles(filtered), [filtered]);

  if (loadState.state === "loading") return <PendingProjection />;
  if (loadState.state === "missing") {
    return (
      <output className={styles.empty}>
        <strong>Repository projection pending</strong>
        <span>{loadState.message}</span>
        <small>The cockpit and curated catalogs remain usable; source claims remain unavailable.</small>
      </output>
    );
  }

  const projection = loadState.module.projection;
  const census = projection.completeness.census;
  const recordCounts = projection.completeness.record_counts;
  return (
    <div>
      <div className={styles.notice}>
        <strong>Proof boundary</strong>
        <span>
          The index is compiler-derived from commit <code>{projection.sourceCommit.slice(0, 12)}</code>.
          Exact source text is absent from this page and loads only when a safe file is selected.
          Structural mapping is Level 1, not behavioral verification.
        </span>
      </div>

      <div className={styles.proofGrid} aria-label="Whole-repository coverage summary">
        <article className={styles.proofCard}>
          <strong>{census.tracked_files?.toLocaleString() ?? "—"}</strong>
          <span>Tracked files</span>
          <small>{census.classified_files?.toLocaleString() ?? "—"} classified</small>
        </article>
        <article className={styles.proofCard}>
          <strong>{recordCounts.lines?.toLocaleString() ?? "—"}</strong>
          <span>Nonblank lines mapped</span>
          <small>Exact denominator from completeness ledger</small>
        </article>
        <article className={styles.proofCard}>
          <strong>{recordCounts.symbols?.toLocaleString() ?? "—"}</strong>
          <span>Symbols</span>
          <small>{recordCounts.tests?.toLocaleString() ?? "—"} declared tests</small>
        </article>
        <article className={styles.proofCard}>
          <strong>{projection.completeness.invariants.filter((item) => item.passed).length}</strong>
          <span>Completeness invariants pass</span>
          <small>Tree {shortDigest(projection.sourceTreeDigest)}</small>
        </article>
      </div>

      <div className={styles.controls} aria-label="Source filters">
        <label>
          Find a tracked path
          <input
            type="search"
            value={query}
            placeholder="parser, workflow, component, registry…"
            onChange={(event) => {
              const value = event.target.value;
              setQuery(value);
              setExplorerUrl(value, language, exposure);
            }}
          />
        </label>
        <label>
          Language
          <select
            value={language}
            onChange={(event) => {
              setLanguage(event.target.value);
              setExplorerUrl(query, event.target.value, exposure);
            }}
          >
            <option value="all">All languages</option>
            {languages.map((item) => <option value={item} key={item}>{item}</option>)}
          </select>
        </label>
        <label>
          Exposure
          <select
            value={exposure}
            onChange={(event) => {
              setExposure(event.target.value);
              setExplorerUrl(query, language, event.target.value);
            }}
          >
            <option value="all">All privacy classes</option>
            {exposures.map((item) => <option value={item} key={item}>{item}</option>)}
          </select>
        </label>
      </div>

      <p className={styles.resultCount} aria-live="polite">
        <span><strong>{filtered.length}</strong> of {files.length} tracked paths</span>
        <span>{projection.sourceModuleCount} per-file source modules</span>
      </p>

      {grouped.length ? (
        <div className={styles.fileGroups}>
          {grouped.map(([group, files], index) => (
            <details className={styles.fileGroup} key={group} open={index === 0 || grouped.length <= 3}>
              <summary>{group}<span>{files.length} paths</span></summary>
              <div className={styles.fileList}>
                {files.map((file) => (
                  <a className={styles.fileRow} href={sourceHref(file.path)} key={file.id}>
                    <span className={styles.filePath}>
                      <strong>{file.path}</strong>
                      <small>{file.roles.join(" · ") || "unclassified role"}</small>
                    </span>
                    <span>{file.language}</span>
                    <span>{file.lineCount.toLocaleString()} lines · {humanBytes(file.sizeBytes)}</span>
                    <span className={styles.badge} data-state={file.privacyExposure}>
                      {file.privacyExposure === "full" ? file.parseStatus : file.privacyExposure}
                    </span>
                  </a>
                ))}
              </div>
            </details>
          ))}
        </div>
      ) : (
        <div className={styles.empty}>
          <strong>No tracked path matches this view.</strong>
          <span>The denominator is unchanged; clear a filter to widen the view.</span>
        </div>
      )}
    </div>
  );
}
