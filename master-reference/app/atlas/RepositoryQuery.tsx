"use client";

import { useEffect, useState } from "react";
import { loadProjection } from "./SourceExplorerData";
import type { SearchProjectionRecord } from "./SourceExplorerTypes";
import styles from "./RepositoryQuery.module.css";

type QueryState =
  | { state: "loading" }
  | { state: "unavailable"; message: string }
  | { state: "ready"; commit: string; records: SearchProjectionRecord[]; limitation: string };

function words(value: string) {
  return [...new Set(value.toLowerCase().match(/[a-z0-9_.:/-]{2,}/g) ?? [])];
}

export function RepositoryQuery({ query }: { query: string }) {
  const [state, setState] = useState<QueryState>({ state: "loading" });
  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const projectionModule = await loadProjection();
        const lineMatch = query.match(/(?:line\s+|:)(\d{1,7})\b/i);
        const queryWords = words(query);
        if (lineMatch) {
          const withoutLine = query.replace(lineMatch[0], "");
          queryWords.push(...words(withoutLine));
        }
        const result = await projectionModule.searchRecords([...new Set(queryWords)]);
        const candidates = result.records.map((record) => lineMatch && record.kind === "files"
          ? { ...record, href: `${record.href.split("#", 1)[0]}#L${lineMatch[1]}`, title: `${record.title}:${lineMatch[1]}`, score: record.score + 100 }
          : record).sort((left, right) => right.score - left.score || left.id.localeCompare(right.id));
        if (active) {
          setState({
            state: "ready",
            commit: projectionModule.projection.sourceCommit,
            records: candidates.slice(0, 12),
            limitation: candidates.length
              ? `Exact-token and stable-ID resolution from bounded content-hashed shards; structural/coverage labels retain their emitted depth. ${result.truncatedTerms.length ? `${result.truncatedTerms.length} broad term(s) were deterministically capped—use a stable ID or narrower token.` : "No term posting was capped."}${result.ignoredTokenCount ? ` ${result.ignoredTokenCount} token(s) beyond the bounded query limit were ignored.` : ""}`
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
