import type { Summary, SummaryFact } from "../api";
import { StateLabel, ValueText } from "../pages/core/ProjectionEvidence";

// Render the engine's state and minimum mark. No threshold, evidence rule, or verdict lives here.
export function SummaryValue({ fact }: { fact?: SummaryFact }) {
  if (!fact) return <span>Not verified — summary contract unavailable</span>;
  const prefix = fact.minimum ? "≥ " : "";
  const minimum = fact.minimum ? " (engine-published minimum)" : "";
  const reason = "reason" in fact ? fact.reason : "";
  return <span data-summary-state={fact.state}>
    <span>{prefix}<ValueText value={fact.value} /></span>
    <StateLabel state={fact.state} /> <span>{reason}</span>
    <small>{minimum}</small>
    <details><summary>Evidence and qualifications</summary>
      <div>{fact.basis}</div>
      {fact.refs.map((ref, i) => <div key={i}>{ref.role}: <code>{ref.pointer}</code></div>)}
      {fact.caveats?.map((id) => <div key={id}>{id}</div>)}
    </details>
  </span>;
}

export function SummaryBands({ summary }: { summary: Summary }) {
  return <SummaryRows rows={summary.assessment?.bands.map((row) => ({ k: row.band, n: row.n }))} />;
}

export function SummaryRows({ rows }: { rows?: { k: string; n: SummaryFact }[] }) {
  if (!rows) return <SummaryValue />;
  return <dl>{rows.map((row) => <div key={row.k}><dt>{row.k}</dt><dd><SummaryValue fact={row.n} /></dd></div>)}</dl>;
}
