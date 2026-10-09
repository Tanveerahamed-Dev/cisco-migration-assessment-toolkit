import { useEffect, useRef, useState, type ReactNode } from "react";
import { loadProjectionPage, type Page, type Projection } from "../../projection";
import { ListState } from "./ProjectionEvidence";

// Feature-private transport renderer for CoreSnapshot; requires its exact document identity.

export function ProjectionList<P extends Page>({ title, initial, document, host, renderRow, reference, paired = false }: {
  title: string; initial: P; document: Projection; host?: string;
  renderRow: (row: P["page"]["items"][number]) => ReactNode;
  reference?: { index: number; pointer: string }; paired?: boolean;
}) {
  const [current, setCurrent] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [requestedOffset, setRequestedOffset] = useState(initial.page.offset);
  const request = useRef<AbortController | null>(null);
  const referencedRecord = useRef<HTMLDivElement | null>(null);
  const matches = (row: P["page"]["items"][number]) => !!reference && typeof row === "object" && row !== null && "index" in row && "pointer" in row &&
    row.index === reference.index && row.pointer === reference.pointer;
  // The source the paging state was built for. useState already starts from `initial`, so the effect below resets
  // and aborts only when the source really changes. Before, its first run also reset and aborted, and React may run a
  // passive effect after a click that lands between the first commit and that run (a render outside a discrete
  // event flushes its effects later): the click's page request was aborted and the list snapped back to its first
  // page, with Next enabled and no error (W29's intermittent paging failure).
  const source = useRef({ initial, document, host, pointer: reference?.pointer, index: reference?.index });
  useEffect(() => {
    const next = { initial, document, host, pointer: reference?.pointer, index: reference?.index };
    const was = source.current;
    const changed = was.initial !== next.initial || was.document !== next.document || was.host !== next.host
      || was.pointer !== next.pointer || was.index !== next.index;
    source.current = next;
    if (changed) {
      request.current?.abort(); request.current = null;
      setCurrent(initial); setBusy(false); setError(""); setRequestedOffset(initial.page.offset);
    }
    // A source index is only a search hint, never proof of a projection position. Even
    // on that page both pointer and original index must match before it is highlighted.
    // A page the user already requested for this source is never overridden by the hint.
    if (reference && !request.current && !initial.page.items.some(matches) && initial.page.total > 0) {
      const hint = Math.min(Math.floor(reference.index / initial.page.limit) * initial.page.limit,
        Math.floor((initial.page.total - 1) / initial.page.limit) * initial.page.limit);
      if (hint !== initial.page.offset) void page(hint);
    }
  }, [initial, document, host, reference?.pointer, reference?.index]);
  // Unmounting abandons any page still in flight. (Under StrictMode's development remount this also clears the
  // in-flight marker, so the remounted effect can issue the reference hint again.)
  useEffect(() => () => { request.current?.abort(); request.current = null; }, []);
  // `request.current` is the page request in flight, or null: a settled request clears it.
  async function page(offset: number) {
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    setBusy(true); setError(""); setRequestedOffset(offset);
    try {
      const next = await loadProjectionPage(document, initial, offset, host, controller.signal);
      if (!controller.signal.aborted) setCurrent(next);
    } catch (error) {
      if (!controller.signal.aborted) setError(error instanceof Error ? error.message : "Page could not be loaded.");
    } finally {
      if (!controller.signal.aborted) setBusy(false);
      if (request.current === controller) request.current = null;
    }
  }
  return <section className="panel projection-list" aria-label={title} aria-busy={busy}>
    <h2>{title}</h2><ListState label={title} source={current.source_list} />
    {reference && current.page.items.some(matches) && <button className="btn" onClick={() => {
      referencedRecord.current?.focus({ preventScroll: true });
      referencedRecord.current?.scrollIntoView?.({ behavior: "auto", block: "start" });
    }}>Jump to referenced record</button>}
    {reference && !busy && !current.page.items.some(matches) && <p className="projection-disclosure">Reference only: source index {reference.index}, <code>{reference.pointer}</code>. No exact pointer-and-index match is present on this page. Use paging to inspect other projected rows.</p>}
    <div className={`projection-list-items${paired ? " paired" : ""}`}>{current.page.items.map((row, index) =>
      <div key={`${current.page.offset}:${index}`} aria-label={matches(row) ? "Referenced record" : undefined}
        ref={matches(row) ? referencedRecord : undefined} tabIndex={matches(row) ? -1 : undefined}
        className={`projection-list-item${matches(row) ? " referenced" : ""}`}>{renderRow(row as P["page"]["items"][number])}</div>)}</div>
    {!current.page.returned && <p className="projection-disclosure">No rows on this page. The source evidence state above is unchanged.</p>}
    {error && <p role="alert" className="projection-error">{error}</p>}
    <footer className="projection-pagination">
      <span>{current.page.returned ? `Rows ${current.page.offset + 1}–${current.page.offset + current.page.returned}` : "No rows"} of {current.page.total} projected rows</span>
      <button className="btn" disabled={busy || current.page.offset === 0}
        onClick={() => void page(Math.max(0, current.page.offset - current.page.limit))}>Previous {title} page</button>
      <button className="btn" disabled={busy || !current.page.has_more}
        onClick={() => void page(current.page.offset + current.page.limit)}>Next {title} page</button>
      {error && <button className="btn" onClick={() => void page(requestedOffset)}>Retry {title} page</button>}
    </footer>
  </section>;
}
