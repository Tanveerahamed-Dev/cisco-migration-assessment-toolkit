import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import type { Fact, Identity, Limitation, SourceList, State } from "../projection";

export const STATE_LABEL: Record<State, string> = {
  published: "Published", collected_but_empty: "Collected, empty", not_collected: "Not collected",
  analysis_unavailable: "Analysis unavailable", not_assessed: "Not assessed", unverified: "Unverified",
};
type Envelope = Fact | SourceList;
type Selection = { label: string; envelope: Envelope };
type EvidenceContextValue = { open: (selection: Selection) => void; limitations: readonly Limitation[] };
const EvidenceContext = createContext<EvidenceContextValue>({ open: () => {}, limitations: [] });

export function StateLabel({ state }: { state: State }) {
  return <span className={`projection-state state-${state}`}>{STATE_LABEL[state]}</span>;
}

// Presentation only: values have already been typed by the generated owner schema. No HTML,
// arithmetic, severity mapping, inference, object execution or external resource loading occurs.
type DisplayValue = string | number | boolean | null | readonly DisplayValue[] | { readonly [key: string]: DisplayValue };
export function ValueText({ value }: { value: DisplayValue }) {
  if (value === null) return <span className="dim">—</span>;
  if (typeof value === "boolean") return <>{value ? "Yes" : "No"}</>;
  if (typeof value !== "object") return <>{String(value)}</>;
  if (Array.isArray(value)) return value.length
    ? <ul className="projection-values">{value.map((item, index) => <li key={index}><ValueText value={item} /></li>)}</ul>
    : <span className="dim">Empty list</span>;
  return <dl className="projection-record">{Object.entries(value).map(([key, item]) =>
    <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd><ValueText value={item} /></dd></div>)}</dl>;
}

function Caveats({ envelope }: { envelope: Envelope }) {
  const { limitations } = useContext(EvidenceContext);
  if (!envelope.caveats?.length) return null;
  return <ul className="projection-caveats">{envelope.caveats.map((id) => {
    const limitation = limitations.find((item) => item.id === id);
    return <li key={id}><strong>{id}</strong><p>{limitation?.text ?? `Limitation detail unavailable: ${id}`}</p>
      {limitation && <small>Owner: {limitation.owner} · Applies to: {limitation.applies_to.join(", ")}</small>}</li>;
  })}</ul>;
}

function Qualifications({ label, envelope }: { label: string; envelope: Envelope }) {
  const { open } = useContext(EvidenceContext);
  if (!envelope.caveats?.length) return null;
  return <button type="button" className="projection-qualifications" onClick={() => open({ label, envelope })}
    aria-label={`Qualifications for ${label}`}>Qualifications ({envelope.caveats.length})</button>;
}

export function EnvelopeEvidence({ label, envelope }: { label: string; envelope: Envelope }) {
  const { open } = useContext(EvidenceContext);
  return <button type="button" className="projection-evidence" onClick={() => open({ label, envelope })}
    aria-label={`Evidence for ${label}`}>Evidence ↗</button>;
}

export function FactView({ label, fact, compact = false }: { label: string; fact: Fact; compact?: boolean }) {
  return <div className={`projection-fact${compact ? " compact" : ""}`}>
    <div className="projection-fact-label">{label}<EnvelopeEvidence label={label} envelope={fact} /></div>
    <div className="projection-fact-value">{fact.state === "published" ? <ValueText value={fact.value} /> : <span aria-hidden="true">—</span>}</div>
    <StateLabel state={fact.state} />
    {fact.state !== "published" && <p className="projection-reason">{fact.reason}</p>}
    <Qualifications label={label} envelope={fact} />
  </div>;
}

export function ListState({ label, source }: { label: string; source: SourceList }) {
  return <div className="projection-list-state"><StateLabel state={source.state} /> <EnvelopeEvidence label={label} envelope={source} />
    {source.state !== "published" && <p className="projection-reason">{source.reason}</p>}
    <Qualifications label={label} envelope={source} />
  </div>;
}

export function EvidenceProvider({ identity, limitations, children }: {
  identity: Identity; limitations: readonly Limitation[]; children: ReactNode;
}) {
  const identityKey = `${identity.snapshot_id}:${identity.sha256}:${identity.bytes}:${identity.digest_form}`;
  const [selected, setSelected] = useState<(Selection & { identityKey: string }) | null>(null);
  const selection = selected?.identityKey === identityKey ? selected : null;
  const close = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!selection) return;
    const previous = document.activeElement;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    close.current?.focus();
    return () => {
      document.body.style.overflow = overflow;
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, [selection]);
  const envelope = selection?.envelope;
  return <EvidenceContext.Provider value={{ open: (value) => setSelected({ ...value, identityKey }), limitations }}>
    {children}
    {selection && envelope && <div className="projection-drawer-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) setSelected(null);
    }}>
      <aside className="projection-drawer" role="dialog" aria-modal="true" aria-labelledby="projection-evidence-title"
        onKeyDown={(event) => {
          if (event.key === "Escape") { event.preventDefault(); setSelected(null); }
          // The drawer contains one interactive control. Do not let Tab move behind the modal.
          if (event.key === "Tab") { event.preventDefault(); close.current?.focus(); }
        }}>
        <header><h2 id="projection-evidence-title">Evidence: {selection.label}</h2>
          <button ref={close} type="button" className="btn" aria-label="Close evidence" onClick={() => setSelected(null)}>Close ×</button></header>
        <StateLabel state={envelope.state} />
        {"reason" in envelope && <p>{envelope.reason}</p>}
        {"value" in envelope && <><h3>Value</h3><ValueText value={envelope.value} /></>}
        <h3>Basis</h3><p>{envelope.basis}</p>
        <h3>Subject</h3><code>{envelope.subject ?? "No subject address was published."}</code>
        <h3>References</h3>
        {envelope.refs.length ? <ul>{envelope.refs.map((ref, index) => <li key={index}><span>{ref.role}</span> <code>{ref.pointer}</code></li>)}</ul>
          : <p>No references were published.</p>}
        {"engine_state" in envelope && envelope.engine_state && <><h3>Engine state</h3><p>{envelope.engine_state} · {envelope.engine_state_owner}</p></>}
        <h3>Qualifications</h3><Caveats envelope={envelope} />
        {!envelope.caveats?.length && <p>No additional caveat is attached to this fact.</p>}
        <h3>Stored snapshot identity</h3><p>Snapshot {identity.snapshot_id} · {identity.bytes} bytes</p>
        <code>{identity.sha256}</code><p className="dim">{identity.digest_form}</p>
        <p className="projection-disclosure">These addresses and explanations come from the projection. Raw evidence values are not available in this view.</p>
      </aside>
    </div>}
  </EvidenceContext.Provider>;
}
