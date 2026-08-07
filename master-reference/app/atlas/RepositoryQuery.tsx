"use client";

import { useEffect, useState } from "react";
import { dossierHref, loadProjection, sourceHref } from "./SourceExplorerData";
import type { SourceFileRecord, SourceLine } from "./SourceExplorerTypes";
import styles from "./RepositoryQuery.module.css";

type QueryRecord = {
  id: string;
  kind: string;
  title: string;
  detail: string;
  href: string;
  score: number;
};

type QueryState =
  | { state: "loading" }
  | { state: "unavailable"; message: string }
  | { state: "ready"; commit: string; records: QueryRecord[]; limitation: string };

function words(value: string) {
  return [...new Set(value.toLowerCase().match(/[a-z0-9_.:/-]{2,}/g) ?? [])];
}

function lexicalValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(lexicalValue).join(" ");
  return "";
}

function textOf(record: Record<string, unknown>) {
  return [
    record.id,
    record.path,
    record.name,
    record.qualifiedName,
    record.route,
    record.kind,
    record.language,
    record.purpose,
    record.predicate,
    record.subject,
    record.module,
    record.names,
    record.alias,
    record.callee,
    record.containing_symbol,
    record.ecosystem,
    record.scope,
    record.constraint,
    record.resolved_version,
    record.runtimeTraceState,
    record.tests,
    record.evidenceIds,
    record.unresolvedReasons,
    record.unresolved_reasons,
  ].map(lexicalValue).join(" ");
}

function rank(record: Record<string, unknown>, queryWords: string[]) {
  const haystack = textOf(record).toLowerCase();
  return queryWords.reduce((total, word) => total + (haystack.includes(word) ? 2 : 0), 0);
}

function toQueryRecord(kind: string, record: Record<string, unknown>, score: number): QueryRecord | null {
  const id = lexicalValue(record.id).trim();
  const path = lexicalValue(record.path).trim();
  if (!id) return null;
  const title = [
    record.qualifiedName,
    record.name,
    record.predicate,
    record.callee,
    record.module,
    record.route,
    path,
    id,
  ].map(lexicalValue).find((value) => value.trim()) ?? id;
  const dossierKind = kind === "datasets" ? "data" : kind === "claims" ? "claim" : kind.endsWith("s") ? kind.slice(0, -1) : kind;
  const hasDossier = ["symbol", "data", "test", "workflow", "claim"].includes(dossierKind);
  const startLine = typeof (record.range as { start_line?: unknown } | undefined)?.start_line === "number"
    ? (record.range as { start_line: number }).start_line
    : undefined;
  return {
    id,
    kind,
    title,
    detail: [
      path,
      record.kind,
      record.language,
      record.verdict,
      record.freshness,
      record.ecosystem,
      record.scope,
      record.runtimeTraceState,
    ].map(lexicalValue).filter(Boolean).join(" · "),
    href: hasDossier
      ? dossierHref(dossierKind as "symbol" | "data" | "test" | "workflow" | "claim", id)
      : path ? sourceHref(path, startLine) : `/ask?q=${encodeURIComponent(id)}`,
    score,
  };
}

function lineRecord(file: SourceFileRecord, line: SourceLine): QueryRecord {
  return {
    id: line.recordId ?? `${file.id}:L${line.number}`,
    kind: "line",
    title: `${file.path}:${line.number}`,
    detail: `${line.syntaxKind ?? "structural line"} · depth ${line.explanationDepth} · tests ${line.testsCoveringIt.length} · runtime ${line.runtimeTraceState}`,
    href: sourceHref(file.path, line.number),
    score: 100,
  };
}

export function RepositoryQuery({ query }: { query: string }) {
  const [state, setState] = useState<QueryState>({ state: "loading" });
  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const projectionModule = await loadProjection();
        const groups = [
          "files",
          "symbols",
          "tests",
          "workflows",
          "datasets",
          "routes",
          "components",
          "claims",
          "imports",
          "calls",
          "dependencies",
        ];
        const loaded = await Promise.all(groups.map((group) => projectionModule.loadMetadata(group)));
        const queryWords = words(query);
        const candidates: QueryRecord[] = [];
        for (const [index, records] of loaded.entries()) {
          const group = groups[index];
          for (const item of records as Record<string, unknown>[]) {
            const score = rank(item, queryWords);
            if (score > 0) {
              const candidate = toQueryRecord(group, item, score);
              if (candidate) candidates.push(candidate);
            }
          }
        }

        const files = loaded[0] as SourceFileRecord[];
        const lineMatch = query.match(/(?:line\s+|:)(\d{1,7})\b/i);
        const matchingFile = files
          .filter((file) => file.privacyExposure === "full")
          .map((file) => ({ file, score: words(query).filter((word) => file.path.toLowerCase().includes(word)).length }))
          .sort((left, right) => right.score - left.score || left.file.path.localeCompare(right.file.path))[0];
        if (lineMatch && matchingFile?.score) {
          const source = await projectionModule.loadSource(matchingFile.file.path);
          const line = source?.lines.find((item) => item.number === Number(lineMatch[1]));
          if (line) candidates.unshift(lineRecord(matchingFile.file, line));
        }

        candidates.sort((left, right) => right.score - left.score || left.id.localeCompare(right.id));
        if (active) {
          setState({
            state: "ready",
            commit: projectionModule.projection.sourceCommit,
            records: candidates.slice(0, 12),
            limitation: candidates.length
              ? "Lexical and stable-ID resolution only; structural/coverage labels retain their emitted depth and do not become correctness proof."
              : "The exact projection contains no citable lexical match; Atlas abstains rather than infer one.",
          });
        }
      } catch {
        if (active) setState({ state: "unavailable", message: "No exact clean-commit repository projection is available to support this query." });
      }
    })();
    return () => {
      active = false;
    };
  }, [query]);

  if (!query.trim()) return null;
  if (state.state === "loading") return <output className={styles.panel}><strong>Resolving exact repository records…</strong></output>;
  if (state.state === "unavailable") return <output className={styles.panel}><strong>Repository query abstained.</strong><p>{state.message}</p></output>;
  return (
    <section className={styles.panel} aria-labelledby="repository-query-title">
      <header><p>Whole-repository projection · {state.commit.slice(0, 12)}</p><h3 id="repository-query-title">Citable source, claim, symbol, test, workflow, import, call and dependency matches</h3></header>
      {state.records.length ? <ol>{state.records.map((record) => <li key={`${record.kind}-${record.id}`}><span>{record.kind}</span><strong>{record.title}</strong><p>{record.detail}</p><a href={record.href}>[{record.id}]</a></li>)}</ol> : <strong>No supported repository answer.</strong>}
      <p className={styles.limit}>{state.limitation}</p>
    </section>
  );
}
