/* V3.23.163: "Ask the engineer" — the senior-engineer design review, interactive.
   Renders the SAME review object the DOCX report, the workbook scorecard sheet and the explorer
   Review mode carry (GET /api/snapshots/{id}/archreview; the server prefers the stored section and
   computes with the engine function otherwise). The question chips are DETERMINISTIC routes into
   slices of that object — no verdict is ever re-derived or invented in the UI. */
import { useState } from "react";
import { api, ArchCheck, ArchReview, ArchVerdict } from "../api";
import { ErrorBox, SkelLines, useAsync } from "./ui";

export const V_LABEL: Record<ArchVerdict, string> = {
  critical: "CRITICAL DEVIATION",
  deviation: "DEVIATION",
  advisory: "ADVISORY",
  conforms: "CONFORMS",
  "not-assessable": "NOT ASSESSABLE",
};
export const V_COLOR: Record<ArchVerdict, string> = {
  critical: "var(--crit)",
  deviation: "var(--risk)",
  advisory: "var(--watch)",
  conforms: "var(--ok)",
  "not-assessable": "var(--text-faint)",
};
export const GRADE_COLOR = (g: string) =>
  g === "A" || g === "B" ? "var(--ok)" : g === "C" ? "var(--watch)" : g === "D" || g === "F" ? "var(--crit)" : "var(--text-faint)";

function VerdictPill({ v }: { v: ArchVerdict }) {
  return (
    <span className="chip" style={{ color: V_COLOR[v], borderColor: V_COLOR[v], fontWeight: 700, fontSize: 10 }}>
      {V_LABEL[v]}
    </span>
  );
}

function CheckCard({ c, full = true }: { c: ArchCheck; full?: boolean }) {
  return (
    <div className="panel" style={{ padding: 12, borderLeft: `3px solid ${V_COLOR[c.verdict]}`, marginBottom: 8 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <b className="mono" style={{ fontSize: 12 }}>{c.id}</b>
        <b style={{ fontSize: 13 }}>{c.title}</b>
        <span style={{ flex: 1 }} />
        <VerdictPill v={c.verdict} />
      </div>
      <div className="dim" style={{ fontSize: 12, marginTop: 6 }}>{c.observed}</div>
      {full && c.verdict !== "conforms" && c.verdict !== "not-assessable" && (
        <>
          <div style={{ fontSize: 12, marginTop: 6 }}><b>Why it matters:</b> <span className="dim">{c.implication}</span></div>
          <div style={{ fontSize: 12, marginTop: 4 }}><b>Fix:</b> <span className="dim">{c.recommendation}</span></div>
        </>
      )}
      <div className="faint" style={{ fontSize: 11, marginTop: 6 }}>
        {c.evidence.length > 0 && (
          <>
            <span className="mono">{c.evidence.slice(0, 8).join(", ")}{c.evidence.length > 8 ? ` +${c.evidence.length - 8}` : ""}</span>
            {" · "}
          </>
        )}
        {c.reference}
      </div>
    </div>
  );
}

/* The deterministic question routes — each one is a slice of the review, in the senior engineer's
   answering voice. The lead() line is composed ONLY from summary counts already in the object. */
const QUESTIONS = [
  { key: "start", label: "Where do we start?" },
  { key: "blockers", label: "What blocks the migration?" },
  { key: "resilient", label: "How resilient is the fabric?" },
  { key: "domains", label: "Judge every design domain" },
  { key: "blind", label: "What couldn't you assess?" },
] as const;
type QKey = (typeof QUESTIONS)[number]["key"];

export default function ArchReviewPanel({ snapId }: { snapId: number }) {
  const { data, error, loading } = useAsync(() => api.archreview(snapId), [snapId]);
  const [q, setQ] = useState<QKey>("start");
  const [domainSel, setDomainSel] = useState<string>("");

  if (loading) return <div className="panel"><h3>Ask the engineer · architecture review</h3><SkelLines n={5} /></div>;
  if (error) return <div className="panel"><h3>Ask the engineer · architecture review</h3><ErrorBox msg={error} /></div>;
  const ar = data as ArchReview;
  const s = ar.summary;
  const byId = new Map(ar.checks.map((c) => [c.id, c]));

  const answer = (() => {
    if (q === "start") {
      if (!ar.top_actions.length)
        return <div className="dim" style={{ fontSize: 13 }}>Nothing in the remediation queue — every assessable check conforms. Start with the pilot wave the cutover planner recommends.</div>;
      return (
        <>
          <div className="dim" style={{ fontSize: 13, marginBottom: 10 }}>
            In this order — severity first, then blast radius. Items overlapping the migration punch-list keep their punch-list owners.
          </div>
          {ar.top_actions.map((a) => (
            <div key={a.rank} style={{ display: "flex", gap: 10, alignItems: "baseline", padding: "6px 0", borderBottom: "1px solid var(--border)" }}>
              <b style={{ color: V_COLOR[a.verdict], minWidth: 26 }}>#{a.rank}</b>
              <span className="mono" style={{ fontSize: 11, minWidth: 56 }}>{a.id}</span>
              <span style={{ fontSize: 13, flex: 1 }}>{a.action}</span>
              {a.evidence.length > 0 && <span className="faint mono" style={{ fontSize: 11 }}>{a.evidence.slice(0, 4).join(", ")}{a.evidence.length > 4 ? "…" : ""}</span>}
            </div>
          ))}
        </>
      );
    }
    if (q === "blockers") {
      const hard = ar.checks.filter((c) => c.verdict === "critical" || c.verdict === "deviation");
      if (!hard.length)
        return <div className="dim" style={{ fontSize: 13 }}>No critical or material deviations — nothing in the review hard-blocks a wave. The advisory items below the line are improvement work, not blockers.</div>;
      return (
        <>
          <div className="dim" style={{ fontSize: 13, marginBottom: 10 }}>
            {s.n_critical > 0
              ? `${s.n_critical} critical deviation(s) must be closed before any wave is scheduled; ${s.n_deviation} material deviation(s) should be fixed or explicitly risk-accepted at the go/no-go gate.`
              : `No critical deviations, but ${s.n_deviation} material deviation(s) should be fixed or explicitly risk-accepted at the go/no-go gate.`}
          </div>
          {hard.map((c) => <CheckCard key={c.id} c={c} />)}
        </>
      );
    }
    if (q === "resilient") {
      const dom = ar.domains.find((d) => d.key.toLowerCase().startsWith("resiliency"));
      const checks = (dom?.checks || []).map((id) => byId.get(id)).filter(Boolean) as ArchCheck[];
      if (!dom) return <div className="dim" style={{ fontSize: 13 }}>No resiliency domain in this review.</div>;
      return (
        <>
          <div className="dim" style={{ fontSize: 13, marginBottom: 10 }}>
            The availability analysis verdict for <b>{dom.key}</b>: <VerdictPill v={dom.verdict} />
            {dom.score_pct != null && <> · domain score <b>{dom.score_pct}%</b></>}. Every check below cites its evidence.
          </div>
          {checks.map((c) => <CheckCard key={c.id} c={c} />)}
        </>
      );
    }
    if (q === "blind") {
      const na = ar.checks.filter((c) => c.verdict === "not-assessable");
      return (
        <>
          <div className="dim" style={{ fontSize: 13, marginBottom: 10 }}>
            {na.length
              ? `${na.length} check(s) had no evidence in this collection — they are declared, never scored. Close the collection gaps and regenerate; the grade may move.`
              : "Every check had evidence — nothing in the review was skipped for lack of collection."}
            {" "}A full review also needs data an offline snapshot never carries (QoS counters, wireless RF, WAN policy, live telemetry) — that scope is listed in the DOCX report §2.
          </div>
          {na.map((c) => <CheckCard key={c.id} c={c} full={false} />)}
        </>
      );
    }
    // domains
    const sel = ar.domains.find((d) => d.key === domainSel);
    const selChecks = (sel?.checks || []).map((id) => byId.get(id)).filter(Boolean) as ArchCheck[];
    return (
      <>
        <table className="tbl">
          <thead><tr><th>Design domain</th><th>Verdict</th><th className="num">Score</th><th className="num">Checks</th></tr></thead>
          <tbody>
            {ar.domains.map((d) => (
              <tr key={d.key} role="button" tabIndex={0} aria-pressed={domainSel === d.key}
                onClick={() => setDomainSel(domainSel === d.key ? "" : d.key)}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setDomainSel(domainSel === d.key ? "" : d.key); } }}
                style={{ cursor: "pointer", background: domainSel === d.key ? "var(--surface-3)" : undefined }}>
                <td><b>{d.key}</b></td>
                <td><VerdictPill v={d.verdict} /></td>
                <td className="num">{d.score_pct != null ? `${d.score_pct}%` : "—"}</td>
                <td className="num">{d.checks.length}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {sel && (
          <div style={{ marginTop: 12 }}>
            {selChecks.map((c) => <CheckCard key={c.id} c={c} />)}
          </div>
        )}
        {!sel && <div className="faint" style={{ fontSize: 11, marginTop: 8 }}>Click a domain row for its checks.</div>}
      </>
    );
  })();

  return (
    <div className="panel">
      <h3>Ask the engineer · architecture review</h3>
      <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap", marginTop: 4 }}>
        <div style={{ textAlign: "center", minWidth: 86 }}>
          <div style={{ fontSize: 40, fontWeight: 800, lineHeight: 1, color: GRADE_COLOR(s.grade) }}>{s.grade}</div>
          <div className="faint" style={{ fontSize: 11, marginTop: 2 }}>{s.score_pct != null ? `${s.score_pct}% conformance` : "not gradeable"}</div>
        </div>
        <div style={{ flex: 1, minWidth: 260 }}>
          <div style={{ fontSize: 13, fontWeight: 700 }}>{s.grade_label}</div>
          <div className="dim" style={{ fontSize: 12, marginTop: 4 }}>{s.statement}</div>
          <div className="faint" style={{ fontSize: 11, marginTop: 6 }}>
            {s.n_conforms} conform · {s.n_advisory} advisory · {s.n_deviation} deviation · {s.n_critical} critical · {s.n_not_assessable} not assessable
            {" — "}the same verdict object behind the DOCX report, the workbook scorecard and the explorer ☑ Review mode.
          </div>
        </div>
      </div>
      <div className="tabs" role="tablist" aria-label="Ask the engineer questions" style={{ marginTop: 14, marginBottom: 12 }}>
        {QUESTIONS.map((x) => (
          <button key={x.key} id={`archtab-${x.key}`} role="tab" aria-controls="archpanel" aria-selected={q === x.key}
            className={q === x.key ? "on" : ""} onClick={() => { setQ(x.key); setDomainSel(""); }}>
            {x.label}
          </button>
        ))}
      </div>
      <div className="tabfade" key={q + domainSel} role="tabpanel" id="archpanel" aria-labelledby={`archtab-${q}`}>{answer}</div>
    </div>
  );
}
