/* oxlint-disable nextjs/no-html-link-for-pages -- full-document navigation preserves the connect-src 'none' privacy boundary. */
"use client";

import { useMemo, useState } from "react";
import type { CapabilityCatalog, CapabilityState, Gap } from "./types";
import { OwnerLinks, StateMark } from "./Shell";

const STATES: CapabilityState[] = [
  "current",
  "partial",
  "missing",
  "gated",
  "excluded",
  "unknown",
];

type CapabilityExplorerProps = {
  catalog: CapabilityCatalog;
  gaps: Gap[];
  domainTitles: Record<string, string>;
  initialDomain?: string;
  initialState?: string;
  initialQuery?: string;
};

function updateUrl(domain: string, state: string, query: string) {
  const params = new URLSearchParams();
  if (domain !== "all") params.set("domain", domain);
  if (state !== "all") params.set("state", state);
  if (query.trim()) params.set("q", query.trim());
  const suffix = params.size ? `?${params}` : "";
  window.history.replaceState(null, "", `/capabilities${suffix}`);
}

export function CapabilityExplorer({
  catalog,
  gaps,
  domainTitles,
  initialDomain = "all",
  initialState = "all",
  initialQuery = "",
}: CapabilityExplorerProps) {
  const [domain, setDomain] = useState(initialDomain);
  const [state, setState] = useState(initialState);
  const [query, setQuery] = useState(initialQuery);
  const gapMap = useMemo(() => new Map(gaps.map((gap) => [gap.id, gap])), [gaps]);

  const entries = useMemo(
    () =>
      catalog.domains.flatMap((item) =>
        item.entries.map((entry) => ({ ...entry, domain: item.id })),
      ),
    [catalog],
  );

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return entries.filter((entry) => {
      if (domain !== "all" && entry.domain !== domain) return false;
      if (state !== "all" && entry.state !== state) return false;
      if (!needle) return true;
      return [entry.id, entry.title, entry.current_scope, entry.domain]
        .join(" ")
        .toLowerCase()
        .includes(needle);
    });
  }, [domain, entries, query, state]);

  function selectDomain(value: string) {
    setDomain(value);
    updateUrl(value, state, query);
  }

  function selectState(value: string) {
    setState(value);
    updateUrl(domain, value, query);
  }

  function search(value: string) {
    setQuery(value);
    updateUrl(domain, state, value);
  }

  return (
    <div className="explorer">
      <div className="explorer-controls" aria-label="Capability filters">
        <label>
          <span>Domain</span>
          <select value={domain} onChange={(event) => selectDomain(event.target.value)}>
            <option value="all">All declared domains</option>
            {catalog.domains.map((item) => (
              <option value={item.id} key={item.id}>
                {domainTitles[item.id] ?? item.id}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>State</span>
          <select value={state} onChange={(event) => selectState(event.target.value)}>
            <option value="all">All states</option>
            {STATES.map((item) => (
              <option value={item} key={item}>
                {item}
              </option>
            ))}
          </select>
        </label>
        <label className="search-field">
          <span>Find a capability</span>
          <input
            type="search"
            value={query}
            onChange={(event) => search(event.target.value)}
            placeholder="BGP, SASE, PKI, Kubernetes…"
          />
        </label>
      </div>

      <div className="result-summary" aria-live="polite">
        <strong>{filtered.length}</strong> of {entries.length} capability records
        <span>{catalog.denominator_rule}</span>
      </div>

      <div className="capability-table-wrap">
        <table className="capability-table">
          <caption className="visually-hidden">Capability catalog</caption>
          <thead>
            <tr className="capability-row capability-head">
              <th scope="col">Capability</th>
              <th scope="col">State</th>
              <th scope="col">Current bounded scope</th>
              <th scope="col">Owners / disposition</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((entry) => (
              <tr className="capability-row" key={entry.id}>
                <th scope="row" aria-label={entry.title}>
                  <span className="capability-identity">
                    <code>{entry.id}</code>
                    <strong>{entry.title}</strong>
                    <span>{domainTitles[entry.domain] ?? entry.domain}</span>
                  </span>
                </th>
                <td><StateMark state={entry.state} /></td>
                <td><p>{entry.current_scope}</p></td>
                <td>
                  <div className="capability-proof">
                    <OwnerLinks ownerRefs={entry.owner_refs} />
                    {entry.gap_refs?.map((gapId) => {
                      const gap = gapMap.get(gapId);
                      return (
                        <a href={`/gaps#${encodeURIComponent(gapId)}`} key={gapId}>
                          {gap?.priority ? `${gap.priority} · ` : ""}
                          {gap?.title ?? gapId}
                        </a>
                      );
                    })}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {filtered.length === 0 ? (
        <div className="empty-state">
          <strong>No capability matches this view.</strong>
          <p>The catalog is intact; clear one or more filters to widen the lens.</p>
          <button
            className="button"
            type="button"
            onClick={() => {
              setDomain("all");
              setState("all");
              setQuery("");
              updateUrl("all", "all", "");
            }}
          >
            Clear filters
          </button>
        </div>
      ) : null}
    </div>
  );
}
