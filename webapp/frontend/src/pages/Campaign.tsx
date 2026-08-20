import { Fragment, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api, bandColor, gateColor } from "../api";
import type {
  CampaignTrendResponse,
  CompareResponse,
  CutoverChangeIntentInput,
  CurrentBaselineGate,
  GateRecord,
  ProtocolAdjacencyDelta,
  SnapshotVerification,
} from "../api";
import ComparisonDecision from "../components/ComparisonDecision";
import { ErrorBox, Loading, SegBar, useAsync, useToast } from "../components/ui";
import {
  normalizedVerification,
  VerificationBadge,
} from "../components/VerificationStatus";

export const NEXT_DECISION: Record<string, string> = { pending: "go", go: "no-go", "no-go": "slipped", slipped: "pending" };

function completionMessage(
  prefix: string,
  verificationValue?: SnapshotVerification | null,
): string {
  const verification = normalizedVerification(verificationValue);
  if (verification.status === "verified") return `${prefix} Verified coverage.`;
  return `${prefix} ${verification.label}; open the snapshot to review the coverage warning.`;
}

function GateBoard({ id, latest, toast }: { id: number; latest: number; toast: (m: string) => void }) {
  // `latest` (newest snapshot id) is a dependency so uploading/ingesting a snapshot refetches the
  // derivable waves (V3.23.159 — the board previously kept the old snapshot's waves until remount).
  const { data, error, reload } = useAsync(() => api.getGates(id), [id, latest]);
  const [signer, setSigner] = useState("");
  const [busy, setBusy] = useState(false);
  // The POST response already carries the authoritative records — apply it locally instead of a
  // second round-trip GET; a real refetch (deps change) supersedes the optimistic list.
  const [recOverride, setRecOverride] = useState<GateRecord[] | null>(null);
  useEffect(() => setRecOverride(null), [data]);

  // Keep the last data rendered through a refetch (no unmount-flash); surface a failed load
  // instead of silently vanishing (V3.23.159).
  if (!data) {
    if (error) {
      return (
        <div className="panel">
          <h3>Gate board · T-minus sign-offs</h3>
          <ErrorBox msg={error} />
        </div>
      );
    }
    return null;
  }
  // audit FE-8: the guard above only fires on the FIRST load. useAsync keeps `data` across a
  // refetch, so once the board had ever loaded a later failure (a 403 cross-site refusal, a 404
  // after the campaign's snapshot set changed, a dropped connection) set `error` while the stale
  // grid kept rendering — indistinguishable from a successful refresh. The board is a governance
  // record; showing a superseded wave set as if it were current is the wrong failure. Disclose the
  // stale read ABOVE the grid rather than replacing it (the last-known board is still useful).
  const staleBanner = error ? (
    <div className="panel" style={{ borderColor: "var(--risk)", padding: "8px 12px", marginBottom: 10 }}>
      <b style={{ color: "var(--risk)" }}>Gate board is STALE.</b>{" "}
      <span className="dim" style={{ fontSize: 12.5 }}>
        The last refresh failed ({error}) — the sign-offs below are the previous read and may not
        reflect the current campaign.
      </span>
    </div>
  ) : null;
  const records = recOverride ?? data.records;
  // union: waves derivable from the latest snapshot + any wave that already has recorded history
  const waves = Array.from(new Set([...data.waves, ...records.map((r) => r.wave)]));
  // A board with nothing to show hides itself (by design) — but never at the cost of hiding a failed
  // refresh, which is the difference between "no waves" and "we could not find out".
  if (waves.length === 0) return staleBanner && <div className="panel">{staleBanner}</div>;
  const rec = new Map(records.map((r) => [`${r.wave}|${r.gate}`, r]));

  async function cycle(wave: string, gate: string) {
    if (busy) return; // one decision in flight — a double-click must not re-read stale state
    const r = rec.get(`${wave}|${gate}`);
    const next = NEXT_DECISION[r?.decision || "pending"] || "go";
    // Advancing a signed gate must not erase its trail: a typed signer wins, otherwise the
    // existing signer and note carry forward (V3.23.159 — empty re-posts were stomping them).
    const by = signer.trim() || r?.signed_by || "";
    const note = r?.note || "";
    setBusy(true);
    try {
      const resp = await api.setGate(id, wave, gate, next, by, note);
      setRecOverride(resp.records);
    } catch (e: any) {
      toast(e.message);
      reload();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      {staleBanner}
      <div className="spread" style={{ marginBottom: 6 }}>
        <h3 style={{ margin: 0 }}>Gate board · T-minus sign-offs</h3>
        <input value={signer} onChange={(e) => setSigner(e.target.value)} placeholder="signed by…"
          style={{ width: 140, fontSize: 12 }} />
      </div>
      <div className="dim" style={{ fontSize: 12.5, marginBottom: 12 }}>
        Click a cell to cycle pending → GO → NO-GO → SLIPPED → pending. Decisions are recorded
        against this campaign and land in the Engagement Workflow &amp; Plan of Record (§4.3 “Gate
        record (as signed)”) the next time it is downloaded.
      </div>
      <div style={{ overflowX: "auto" }}>
        <div style={{ display: "grid", gridTemplateColumns: `minmax(90px, auto) repeat(${data.cadence.length}, 1fr)`, gap: 6, minWidth: 640 }}>
          <span />
          {data.cadence.map((g) => (
            <div key={g.key} style={{ textAlign: "center" }}>
              <div style={{ fontSize: 11.5, fontWeight: 700 }}>{g.label}</div>
              <div className="faint mono" style={{ fontSize: 10.5 }}>{g.when}</div>
            </div>
          ))}
          {waves.map((w) => (
            <Fragment key={w}>
              <span className="chip mono" style={{ alignSelf: "center" }}>{w}</span>
              {data.cadence.map((g) => {
                const r = rec.get(`${w}|${g.key}`);
                const d = r?.decision || "pending";
                // Coverage-honest disclosure (backend gates.annotate_out_of_order, PR #376): a GO signed
                // before its upstream cadence gate was GO. We surface it, we don't block it — the sign-off
                // still stands; the ⚠ + tooltip just make the out-of-order state visible on the board.
                const ooo = r?.out_of_order === true;
                const oooTip = `Out of order: signed before upstream ${r?.out_of_order_upstream || "gate"} was GO`;
                const tip = r
                  ? `${d.toUpperCase()} — ${r.signed_by || "unsigned"} · ${new Date(r.decided_at).toLocaleString()}${r.note ? ` · ${r.note}` : ""}${ooo ? ` · ${oooTip}` : ""}`
                  : "pending — click to sign";
                return (
                  <span key={`${w}|${g.key}`} role="button" tabIndex={0} className="chip gate"
                    onClick={() => cycle(w, g.key)}
                    onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); cycle(w, g.key); } }}
                    data-wave={w} data-gate={g.key} data-out-of-order={ooo || undefined} title={tip} aria-label={tip}
                    style={{ ["--gc" as any]: gateColor(d === "pending" ? "PENDING" : d.toUpperCase()), cursor: "pointer", justifyContent: "center", gap: 4, fontSize: 11, opacity: busy ? 0.65 : 1 }}>
                    {d === "pending" ? "—" : d.toUpperCase()}
                    {ooo && (
                      <span className="gate-ooo" role="img" aria-label={oooTip} title={oooTip}
                        style={{ color: "var(--watch)", fontWeight: 700 }}>⚠</span>
                    )}
                  </span>
                );
              })}
            </Fragment>
          ))}
        </div>
      </div>
    </div>
  );
}

const DIR_ICON: Record<string, string> = { improving: "▲", worsening: "▼", flat: "▬" };
const DIR_COLOR: Record<string, string> = { improving: "var(--ok)", worsening: "var(--crit)", flat: "var(--text-faint)" };
export const VERDICT_COLOR: Record<string, string> = {
  // campaign-trend vocabulary (compute_campaign_trend)
  IMPROVING: "var(--ok)", REGRESSING: "var(--crit)", MIXED: "var(--watch)", FLAT: "var(--text-dim)", INSUFFICIENT: "var(--text-faint)",
  // snapshot_delta vocabulary (compute_snapshot_delta) — the 'Compare two waves' panel reuses this map; without
  // these keys cmp.verdict (CLEAN/REVIEW/REGRESSED) fell through to a flat dim chip, never colored (audit-5 CA#5).
  CLEAN: "var(--ok)", REVIEW: "var(--watch)", REGRESSED: "var(--crit)", INDETERMINATE: "var(--text-faint)",
};

const CURRENT_BASELINE_COLOR: Record<string, string> = {
  BLOCKED: "var(--crit)",
  INDETERMINATE: "var(--watch)",
  NOT_ASSESSED: "var(--text-faint)",
  CLEAR: "var(--ok)",
};

const TREND_PAIR_RENDER_CAP = 3;
const CANONICAL_GATE_COLOR: Record<string, string> = {
  PASS: "var(--ok)",
  CONDITIONAL: "var(--watch)",
  REVIEW: "var(--watch)",
  INDETERMINATE: "var(--text-faint)",
  FAIL: "var(--crit)",
  REGRESSED: "var(--crit)",
};

function downloadTrendJson(value: CampaignTrendResponse, campaignId: number) {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: "application/json;charset=utf-8" });
  const makeUrl = typeof URL.createObjectURL === "function";
  const href = makeUrl
    ? URL.createObjectURL(blob)
    : `data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(value, null, 2))}`;
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = `atlas-campaign-${campaignId}-trend-receipts.json`;
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  if (makeUrl) URL.revokeObjectURL(href);
}

function TrendCanonicalReceipts({ value, campaignId }: {
  value: CampaignTrendResponse;
  campaignId: number;
}) {
  const rows = Array.isArray(value.adjacent_comparisons) ? value.adjacent_comparisons : [];
  const status = value.adjacent_comparison_status;
  const rendered = rows.slice(0, TREND_PAIR_RENDER_CAP);
  const produced = rows.length;
  const omitted = Math.max(0, produced - rendered.length);
  const expected = Math.max(produced, status?.n_pairs_total ?? 0);
  const statusText = (status?.status || "not_verified").replaceAll("_", " ").toUpperCase();
  const statusColor = status?.status === "verified"
    ? "var(--ok)"
    : status?.status === "not_comparable"
      ? "var(--crit)"
      : "var(--text-faint)";

  return (
    <section aria-label="Adjacent canonical cutover receipts" data-testid="trend-canonical-receipts"
      style={{ border: "1px solid var(--border-faint)", borderRadius: 9, padding: 10, marginBottom: 12 }}>
      <div className="spread" style={{ gap: 8, marginBottom: 7 }}>
        <div>
          <b>Adjacent canonical cutover receipts</b>
          <div className="faint" style={{ fontSize: 10.5, marginTop: 2 }}>
            Server-owned cutover_gate/1 decisions from each persisted Cn → Cn+1 source pair
          </div>
        </div>
        <div className="row-flex" style={{ gap: 7, flexWrap: "wrap", justifyContent: "flex-end" }}>
          <span className="chip" data-testid="trend-receipt-status"
            style={{ color: statusColor, borderColor: statusColor }}>{statusText}</span>
          <button type="button" className="btn ghost" data-testid="trend-json-export"
            onClick={() => downloadTrendJson(value, campaignId)} style={{ fontSize: 10.5, padding: "4px 8px" }}>
            Export Trend JSON
          </button>
        </div>
      </div>
      <div className="dim" data-testid="trend-receipt-note" style={{ fontSize: 11.5, marginBottom: rows.length ? 7 : 0 }}>
        {status?.note || "No canonical adjacent comparison status was published. Trend cutover receipt coverage is not verified."}
      </div>
      {rendered.map((entry) => {
        const gate = entry.comparison.cutover_gate;
        const receipt = entry.comparison.comparison_receipt;
        const admission = entry.comparison.comparison_admission;
        const gateVerdict = gate?.verdict || "NOT VERIFIED";
        const gateTone = CANONICAL_GATE_COLOR[gateVerdict] || "var(--text-faint)";
        return (
          <details key={`${entry.index}|${entry.before_snapshot_id}|${entry.after_snapshot_id}`}
            data-testid="trend-adjacent-comparison"
            style={{ borderTop: "1px solid var(--border-faint)", padding: "7px 0" }}>
            <summary style={{ cursor: "pointer" }}>
              <span className="mono">{entry.from} → {entry.to}</span>{" "}
              <b>{entry.before_label} → {entry.after_label}</b>{" "}
              <span className="chip" data-testid="trend-adjacent-gate"
                style={{ color: gateTone, borderColor: gateTone }}>{gateVerdict}</span>
            </summary>
            <div className="faint mono" data-testid="trend-adjacent-receipt"
              style={{ fontSize: 10, margin: "6px 0", overflowWrap: "anywhere" }}>
              Snapshots {entry.before_snapshot_id} → {entry.after_snapshot_id} · admission {admission?.status || "not verified"}<br />
              Receipt: {receipt?.receipt_sha256 || "not published"}
            </div>
            <ComparisonDecision value={entry.comparison}
              exportFilename={`atlas-campaign-${campaignId}-${entry.from}-${entry.to}-comparison.json`} />
          </details>
        );
      })}
      <div className="faint" data-testid="trend-cap-disclosure" style={{ fontSize: 10.5, marginTop: 7 }}>
        Rendered: {rendered.length} · Total produced: {produced} · Omitted from view: {omitted} · Expected pairs: {expected} · Receipt set complete: {status?.complete === true ? "YES" : "NO"}. Trend JSON export contains every produced receipt; unproduced expected pairs remain NOT VERIFIED.
      </div>
    </section>
  );
}

function currentBaselineVerdict(value?: CurrentBaselineGate | null) {
  return value && typeof value.verdict === "string" && value.verdict ? value.verdict : "NOT_ASSESSED";
}

function compareDeltaColor(verdict: string, current?: CurrentBaselineGate | null) {
  // CLEAN is only a before→after claim. Without a producer-owned CLEAR current-state gate, painting
  // it green lets an unchanged EXSTART/Idle baseline masquerade as cutover acceptance.
  if (verdict === "CLEAN" && currentBaselineVerdict(current) !== "CLEAR") return "var(--text-faint)";
  return VERDICT_COLOR[verdict] || "var(--text-dim)";
}

type CurrentBaselineExport = NonNullable<
  NonNullable<CompareResponse["operator_evidence"]>["current_baseline_blocker_export"]
>;

function CurrentBaselineGatePanel({ value, completeExport }: {
  value?: CurrentBaselineGate | null;
  completeExport?: CurrentBaselineExport | null;
}) {
  const verdict = currentBaselineVerdict(value);
  const color = CURRENT_BASELINE_COLOR[verdict] || "var(--text-dim)";
  const summary = value?.summary || {};
  const byState = summary.by_state || {};
  const blockers = Array.isArray(value?.blockers) ? value!.blockers! : [];
  const integrityFailures = Array.isArray(value?.integrity?.failures) ? value!.integrity!.failures! : [];
  const rendered = typeof summary.n_blockers_returned === "number"
    ? summary.n_blockers_returned
    : blockers.length;
  const total = typeof summary.n_blockers === "number" ? summary.n_blockers : rendered;
  const omitted = Math.max(0, total - rendered);
  return (
    <section aria-label="Current baseline gate" data-testid="compare-current-baseline"
      style={{ border: `1px solid ${color}`, borderRadius: 9, marginBottom: 12, overflow: "hidden" }}>
      <div className="spread" style={{ padding: "9px 11px", gap: 9, background: verdict === "BLOCKED" ? "var(--crit-soft)" : verdict === "INDETERMINATE" ? "var(--watch-soft)" : undefined }}>
        <div>
          <b>Current baseline gate</b>
          <div className="faint" style={{ fontSize: 10.5, marginTop: 2 }}>Comparison snapshot · current state, not delta</div>
        </div>
        <span className="chip" data-testid="compare-current-baseline-verdict" style={{ color, borderColor: color }}>
          <span className="dot" /> {verdict.replaceAll("_", " ")}
        </span>
      </div>
      <div style={{ padding: "8px 11px" }}>
        <div className="dim" data-testid="compare-current-baseline-note" style={{ fontSize: 11.5 }}>
          {value?.note || "The comparison response did not include an assessable current-baseline gate. A clean delta is not acceptance."}
        </div>
        <div className="faint" style={{ fontSize: 10.5, marginTop: 4 }}>
          {Number(summary.n_blockers) || 0} blocker(s) · {Number(byState.degraded) || 0} degraded · {Number(byState.review) || 0} review · {Number(byState.not_verified) || 0} not verified
        </div>
        {verdict === "CLEAR" && (
          <div className="faint" data-testid="compare-current-baseline-clear-boundary" style={{ fontSize: 10.5, marginTop: 4 }}>
            CLEAR is bounded to producer-declared blockers in observed validation scope; it is not cutover authorization.
          </div>
        )}
        {verdict === "BLOCKED" && (
          <div style={{ color: "var(--crit)", fontSize: 11.5, marginTop: 5 }}>
            An unchanged blocker is still a blocker. The change result below cannot clear the current baseline.
          </div>
        )}
        {value?.integrity?.valid === false && (
          <div style={{ color: "var(--watch)", fontSize: 11.5, marginTop: 5 }}>
            Validation-plan integrity failed{integrityFailures.length ? `: ${integrityFailures.join("; ")}` : "."}
          </div>
        )}
      </div>
      {blockers.map((row, index) => {
        const state = String(row.evidence_state || "review").trim().toLowerCase();
        const rowColor = state === "degraded" ? "var(--crit)" : "var(--watch)";
        return (
          <div key={`${row.wave || ""}|${row.device || ""}|${row.check || ""}|${row.source_key || index}`}
            data-testid="compare-current-baseline-blocker"
            style={{ borderTop: "1px solid var(--border-faint)", borderLeft: `3px solid ${rowColor}`, padding: "8px 10px" }}>
            <div className="row-flex" style={{ gap: 6, flexWrap: "wrap", alignItems: "baseline" }}>
              <span className="chip" style={{ color: rowColor, borderColor: rowColor }}>{state.replaceAll("_", " ").toUpperCase()}</span>
              {row.device && <span className="chip mono">{row.device}</span>}
              {row.wave && <span className="faint" style={{ fontSize: 10.5 }}>{row.wave}</span>}
              <b style={{ fontSize: 11.5 }}>{row.check || "Current baseline blocker"}</b>
            </div>
            {row.expect && <div className="dim" style={{ fontSize: 10.5, marginTop: 4 }}>{row.expect}</div>}
            <div className="faint" style={{ fontSize: 10, marginTop: 4 }}>
              Evidence: <span className="mono">{state}</span>
              {row.projection_custody && <> · custody: <span className="mono">{row.projection_custody}</span></>}
              {row.source_key && <> · source: <span className="mono">{row.source_key}</span></>}
            </div>
          </div>
        );
      })}
      <div className="faint" data-testid="current-baseline-cap-disclosure"
        style={{ fontSize: 10.5, padding: "7px 11px" }}>
        Rendered: {rendered} · Total: {total} · Omitted: {omitted}.{" "}
        {completeExport?.status === "available" && completeExport.summary.complete
          ? `Complete comparison JSON contains ${completeExport.summary.n_rows_returned} of ${completeExport.summary.n_blockers_total} blocker rows (omitted ${completeExport.summary.omitted}).`
          : "Complete blocker export is NOT VERIFIED; do not infer omitted rows are clear."}
      </div>
    </section>
  );
}

const PROTOCOL_GATE_COLOR: Record<string, string> = {
  PASS: "var(--ok)",
  REVIEW: "var(--watch)",
  REGRESSED: "var(--crit)",
  NOT_ASSESSED: "var(--text-faint)",
};

function ProtocolAdjacencyGate({ value }: { value?: ProtocolAdjacencyDelta | null }) {
  // Additive API shape: comparisons produced before protocol_adjacency_delta/1 simply omit this block.
  if (!value || typeof value !== "object") return null;

  const assessed = value.assessed === true;
  const gate = typeof value.gate === "string" && value.gate ? value.gate : "NOT_ASSESSED";
  const gateColor = PROTOCOL_GATE_COLOR[gate] || "var(--text-dim)";
  const summary = value.summary && typeof value.summary === "object" ? value.summary : {};
  const finiteCount = (key: keyof NonNullable<ProtocolAdjacencyDelta["summary"]>) => {
    const raw = summary[key];
    return typeof raw === "number" && Number.isFinite(raw) && raw >= 0 ? raw : null;
  };
  const metrics = [
    { key: "n_preserved", label: "Preserved", color: "var(--ok)", outcome: true },
    { key: "n_state_regressed", label: "State regressed", color: "var(--crit)", outcome: true },
    { key: "n_no_longer_observed", label: "No longer observed", color: "var(--watch)", outcome: true },
    { key: "n_recovered", label: "Recovered", color: "var(--ok)", outcome: true },
    { key: "n_added", label: "New peers", color: "var(--watch)", outcome: true },
    { key: "n_coverage_gaps", label: "Coverage gaps", color: "var(--watch)", outcome: false },
  ] as const;

  return (
    <section aria-label="Protocol adjacency change gate" data-testid="protocol-adjacency-gate"
      style={{ border: "1px solid var(--border)", borderRadius: 9, padding: "10px 12px", marginBottom: 12 }}>
      <div className="spread" style={{ gap: 8, marginBottom: 6 }}>
        <b>Protocol change gate</b>
        <span className="chip" data-testid="protocol-gate-verdict"
          style={{ color: gateColor, borderColor: gateColor }}>
          <span className="dot" /> {gate.replaceAll("_", " ")}
        </span>
      </div>
      <div className="faint" style={{ fontSize: 11.5, marginBottom: 9 }}>
        Baseline-observed OSPF, BGP, and EIGRP peers only — not an expected-peer completeness check.
        <div data-testid="protocol-gate-scope" style={{ marginTop: 3 }}>
          Scope: {finiteCount("n_baseline_peers") ?? "—"} baseline peer(s) · {finiteCount("n_comparable_cells") ?? "—"}
          {" "}of {finiteCount("n_scoped_cells") ?? "—"} device-family cell(s) comparable
        </div>
        <div data-testid="protocol-gate-custody" style={{ marginTop: 3 }}>
          Projection custody: <span className="mono">{value.projection_custody || "embedded_unverified"}</span>.
          {" "}Snapshot hashes do not independently bind the embedded routing-neighbor projection.
        </div>
      </div>
      <div className="grid" style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 6 }}>
        {metrics.map((metric) => {
          // A zero is meaningful only for a fully assessed outcome. Positive observations remain
          // visible even when another cell has a coverage gap; unknown/zero outcomes stay neutral.
          const observedCount = finiteCount(metric.key);
          const count = !metric.outcome || assessed || (observedCount !== null && observedCount > 0)
            ? observedCount
            : null;
          return (
            <div key={metric.key} style={{ fontSize: 12.5 }}>
              {metric.label}: {" "}
              <b data-testid={`protocol-${metric.key.replace(/^n_/, "").replaceAll("_", "-")}`}
                style={{ color: count === null ? "var(--text-faint)" : metric.color }}>
                {count ?? "—"}
              </b>
            </div>
          );
        })}
      </div>
      {typeof value.note === "string" && value.note && (
        <div className="dim" data-testid="protocol-gate-note" style={{ fontSize: 12, marginTop: 9 }}>
          {value.note}
        </div>
      )}
    </section>
  );
}

function Trend({ id }: { id: number }) {
  const { data, error, loading } = useAsync(() => api.trend(id), [id]);
  // A failed trend fetch must SURFACE, not vanish — every other panel on this page shows ErrorBox
  // (GateBoard's pattern); the old `!data → null` guard swallowed errors forever, silently.
  if (error) {
    return (
      <div className="panel">
        <h3>Campaign trajectory</h3>
        <ErrorBox msg={error} />
      </div>
    );
  }
  if (loading || !data) return null;
  const adjacentRows = Array.isArray(data.adjacent_comparisons)
    ? data.adjacent_comparisons
    : [];
  const latestAdjacent = adjacentRows.length
    ? adjacentRows[adjacentRows.length - 1]
    : undefined;
  const finalBaselineExport = latestAdjacent?.comparison.operator_evidence
    ?.current_baseline_blocker_export;
  const baselineVerdict = currentBaselineVerdict(data.current_baseline);
  const trendColor = data.verdict === "IMPROVING" && baselineVerdict !== "CLEAR"
    ? "var(--text-faint)"
    : (VERDICT_COLOR[data.verdict] || "var(--text-dim)");
  if (data.verdict === "INSUFFICIENT") {
    return (
      <div className="panel">
        <h3>Campaign trajectory</h3>
        <div className="dim" style={{ fontSize: 13, marginBottom: 12 }}>{data.verdict_note}</div>
        <TrendCanonicalReceipts value={data} campaignId={id} />
        <CurrentBaselineGatePanel value={data.current_baseline}
          completeExport={finalBaselineExport} />
      </div>
    );
  }
  return (
    <div className="panel">
      <div className="spread" style={{ marginBottom: 14 }}>
        <h3 style={{ margin: 0 }}>Campaign trajectory</h3>
        <span className="chip" data-testid="trend-verdict" style={{ color: trendColor, borderColor: trendColor }}
          title={data.verdict === "IMPROVING" && baselineVerdict !== "CLEAR"
            ? "Trend improved, but the final snapshot current-baseline gate is not CLEAR"
            : undefined}>
          <span className="dot" /> {data.verdict}
        </span>
      </div>
      <div className="dim" style={{ fontSize: 13, marginBottom: 14 }}>{data.verdict_note}</div>
      <TrendCanonicalReceipts value={data} campaignId={id} />
      <CurrentBaselineGatePanel value={data.current_baseline}
        completeExport={finalBaselineExport} />
      <ProtocolAdjacencyGate value={data.protocol_adjacencies} />
      <div className="grid cols-3">
        {data.trajectory.map((t: any) => (
          <div key={t.metric} style={{ border: "1px solid var(--border)", borderRadius: 9, padding: "10px 12px" }}>
            <div className="faint" style={{ fontSize: 11 }}>{t.metric}</div>
            <div className="row-flex" style={{ gap: 8, marginTop: 4 }}>
              <span style={{ fontWeight: 700, fontSize: 18 }}>{t.first} → {t.last}</span>
              <span style={{ color: DIR_COLOR[t.direction], fontSize: 13, fontWeight: 700 }}>
                {DIR_ICON[t.direction]} {t.delta > 0 ? "+" : ""}{t.delta}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function CampaignPage() {
  const { id } = useParams();
  const cid = Number(id);
  const nav = useNavigate();
  const { toast, node } = useToast();
  const { data, error, loading, reload } = useAsync(() => api.getCampaign(cid), [cid]);
  const fileRef = useRef<HTMLInputElement>(null);
  const zipRef = useRef<HTMLInputElement>(null);
  const [label, setLabel] = useState("");
  const [zipLabel, setZipLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [folderPath, setFolderPath] = useState("");
  const [folderLabel, setFolderLabel] = useState("");
  const [folderIngesting, setFolderIngesting] = useState(false);
  const [cmpA, setCmpA] = useState<number | "">("");
  const [cmpB, setCmpB] = useState<number | "">("");
  const [changeIntentText, setChangeIntentText] = useState("");
  const [cmp, setCmp] = useState<CompareResponse | null>(null);
  const [cmpErr, setCmpErr] = useState<string | null>(null);

  async function upload() {
    const f = fileRef.current?.files?.[0];
    if (!f) { toast("Choose a snapshot .json first."); return; }
    setBusy(true);
    try {
      const meta = await api.uploadSnapshot(cid, f, label);
      toast(completionMessage("Snapshot added.", meta.summary.verification));
      setLabel("");
      if (fileRef.current) fileRef.current.value = "";
      reload();
    }
    catch (e: any) { toast(e.message); } finally { setBusy(false); }
  }
  async function ingestZip() {
    const f = zipRef.current?.files?.[0];
    if (!f) { toast("Choose a collection .zip first."); return; }
    setIngesting(true);
    try {
      const meta = await api.ingestCollection(cid, f, zipLabel);
      toast(completionMessage(
        `Engine run complete — ${meta.ingest.n_device_dirs} device(s) in ${meta.ingest.engine_seconds}s.`,
        meta.ingest.verification,
      ));
      nav(`/snapshots/${meta.id}`);
    } catch (e: any) { toast(e.message); } finally { setIngesting(false); }
  }
  async function ingestFolder() {
    const p = folderPath.trim();
    if (!p) { toast("Enter the server-local folder path first."); return; }
    setFolderIngesting(true);
    try {
      const meta = await api.ingestFolder(cid, p, folderLabel);
      toast(completionMessage(
        `Engine run complete — ${meta.ingest.n_device_dirs} device(s) in ${meta.ingest.engine_seconds}s.`,
        meta.ingest.verification,
      ));
      nav(`/snapshots/${meta.id}`);
    } catch (e: any) { toast(e.message); } finally { setFolderIngesting(false); }
  }
  async function runCompare() {
    if (cmpA === "" || cmpB === "" || cmpA === cmpB) { toast("Pick two different snapshots."); return; }
    // audit FE-7: a failed re-compare used to leave the PREVIOUS pair's verdict on screen under the
    // newly-selected pair — the reader attributes an old CLEAN/REGRESSED to snapshots it was never
    // computed from. Drop the stale result first and say the run failed where the result would be.
    setCmp(null);
    setCmpErr(null);
    let changeIntent: CutoverChangeIntentInput | undefined;
    if (changeIntentText.trim()) {
      try {
        const parsed = JSON.parse(changeIntentText);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          throw new Error("Expected-change intent must be a JSON object.");
        }
        changeIntent = parsed as CutoverChangeIntentInput;
      } catch (e: any) {
        const message = e?.message || String(e);
        setCmpErr(`Expected-change intent is not valid JSON: ${message}`);
        toast("Fix the expected-change intent before comparing.");
        return;
      }
    }
    try {
      setCmp(changeIntent
        ? await api.compare(Number(cmpA), Number(cmpB), changeIntent)
        : await api.compare(Number(cmpA), Number(cmpB)));
    }
    catch (e: any) { setCmpErr(e.message || String(e)); toast(e.message); }
  }
  async function delCampaign() {
    if (!confirm("Delete this campaign and all its snapshots?")) return;
    try { await api.deleteCampaign(cid); nav("/campaigns"); } catch (e: any) { toast(e.message); }
  }

  if (loading) return <div className="container"><Loading /></div>;
  if (error) return <div className="container"><ErrorBox msg={error} /></div>;
  const snaps = data!.snapshots || [];

  return (
    <div className="container">
      <div className="breadcrumb"><Link to="/campaigns">Campaigns</Link> / {data!.name}</div>
      <div className="page-head">
        <div>
          <h1>{data!.name}</h1>
          {data!.description && <div className="sub">{data!.description}</div>}
        </div>
        <span style={{ flex: 1 }} />
        <button className="btn danger ghost" onClick={delCampaign}>Delete</button>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "1.4fr 1fr", gap: 16 }}>
        <div className="grid" style={{ gap: 16 }}>
          {snaps.length >= 2 && <Trend id={cid} />}
          <div className="panel">
            <h3>Waves ({snaps.length})</h3>
            {snaps.length === 0 ? <div className="faint" style={{ fontSize: 13 }}>No snapshots yet — upload one on the right.</div> : (
              <div className="grid" style={{ gap: 10 }}>
                {snaps.map((s, i) => (
                  <Link key={s.id} to={`/snapshots/${s.id}`} className="panel"
                    style={{ padding: 14, display: "block", color: "inherit", textDecoration: "none", background: "var(--surface-2)", ["--stagger-i" as any]: Math.min(i, 8) }}>
                    <div className="spread">
                      <div className="row-flex" style={{ gap: 10 }}>
                        <span className="chip mono">C{i + 1}</span>
                        <b style={{ fontSize: 15 }}>{s.label}</b>
                        <VerificationBadge value={s.summary.verification} compact />
                      </div>
                      <span className="dim" style={{ fontSize: 12 }}>{s.n_devices} dev · {new Date(s.uploaded_at).toLocaleDateString()}</span>
                    </div>
                    <div style={{ marginTop: 10 }}><SegBar data={s.summary.bands} colorFor={bandColor} /></div>
                  </Link>
                ))}
              </div>
            )}
          </div>
          {/* Always mounted: gate records are campaign-scoped and must stay visible/clearable
              even with zero snapshots (the board hides itself when there is nothing to show). */}
          <GateBoard id={cid} latest={snaps[snaps.length - 1]?.id ?? 0} toast={toast} />
        </div>

        <div className="grid" style={{ gap: 16, alignSelf: "start" }}>
          <div className="panel">
            <h3>Add a wave</h3>
            <label className="field"><span>Snapshot file (.json from the engine)</span>
              <input ref={fileRef} type="file" accept=".json,application/json" />
            </label>
            <label className="field"><span>Label (optional)</span>
              <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Wave 2 post-cutover" />
            </label>
            <button className="btn primary" onClick={upload} disabled={busy}>{busy ? "Uploading…" : "Upload snapshot"}</button>
          </div>

          <div className="panel">
            <h3>…or ingest a raw collection</h3>
            <div className="dim" style={{ fontSize: 12.5, marginBottom: 12 }}>
              Upload a ZIP of show-command outputs (one folder per device, e.g.{" "}
              <span className="mono">core1/show_interface_status.txt</span> — the collector's own
              layout). The real engine pipeline runs on the server and the snapshot lands here.
              A bundled <span className="mono">devices.json</span> is used if present; otherwise
              platforms are autodetected.
            </div>
            <label className="field"><span>Collection archive (.zip)</span>
              <input ref={zipRef} type="file" accept=".zip,application/zip" disabled={ingesting} />
            </label>
            <label className="field"><span>Label (optional)</span>
              <input value={zipLabel} onChange={(e) => setZipLabel(e.target.value)}
                placeholder="e.g. Baseline collection" disabled={ingesting} />
            </label>
            <button className="btn primary" onClick={ingestZip} disabled={ingesting}>
              {ingesting ? <><span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} /> Running engine…</> : "⚙ Run engine & ingest"}
            </button>
            {ingesting && (
              <div className="faint" style={{ fontSize: 11, marginTop: 8 }}>
                The full assessment pipeline is running over your outputs — typically seconds for a
                small fleet, a few minutes for a large one.
              </div>
            )}
          </div>

          <div className="panel">
            <h3>…or ingest a local folder</h3>
            <div className="dim" style={{ fontSize: 12.5, marginBottom: 12 }}>
              Point at a collection folder on the <b>server&rsquo;s</b> disk (same per-device layout,
              no ZIP round-trip) — the portable-app path, where the collection already sits beside
              the app. The folder is only read; outputs stay in a private workdir.
            </div>
            <label className="field"><span>Folder path (on the server)</span>
              <input value={folderPath} onChange={(e) => setFolderPath(e.target.value)}
                placeholder="e.g. D:\collections\siteA" disabled={folderIngesting} />
            </label>
            <label className="field"><span>Label (optional)</span>
              <input value={folderLabel} onChange={(e) => setFolderLabel(e.target.value)}
                placeholder="e.g. Field baseline" disabled={folderIngesting} />
            </label>
            <button className="btn primary" onClick={ingestFolder} disabled={folderIngesting}>
              {folderIngesting ? <><span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} /> Running engine…</> : "⚙ Run engine on folder"}
            </button>
          </div>

          {snaps.length >= 2 && (
            <div className="panel">
              <h3>Compare two waves</h3>
              <div className="row-flex" style={{ gap: 8 }}>
                {/* audit FE-6: `Number(e.target.value)` turned the "from…"/"to…" placeholder ("") into
                    0, which is not "" — so the `cmpA === ""` guard passed and the app POSTed
                    /api/compare with old_id 0, getting back the server's "One or both snapshots not
                    found" 404 instead of the local "Pick two different snapshots." prompt. Keep ""
                    as "" so the unselected state stays distinguishable from a real id. */}
                <select value={cmpA} onChange={(e) => setCmpA(e.target.value === "" ? "" : Number(e.target.value))}>
                  <option value="">from…</option>
                  {snaps.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
                </select>
                <span className="faint">→</span>
                <select value={cmpB} onChange={(e) => setCmpB(e.target.value === "" ? "" : Number(e.target.value))}>
                  <option value="">to…</option>
                  {snaps.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
                </select>
              </div>
              <details style={{ marginTop: 9 }}>
                <summary className="faint" style={{ cursor: "pointer", fontSize: 11.5 }}>
                  Expected family changes (optional, source-bound JSON)
                </summary>
                <div className="faint" style={{ fontSize: 10.5, margin: "6px 0" }}>
                  Supply <span className="mono">expected_changes</span> with family, transition,
                  optional subjects, and reason. A VTP reset additionally requires exact subjects and
                  <span className="mono"> intent_kind: revision_reset</span>. Evidence loss or incompatibility can never be authorized.
                </div>
                <textarea aria-label="Expected family changes JSON" value={changeIntentText}
                  onChange={(event) => setChangeIntentText(event.target.value)} rows={5}
                  placeholder={'{"expected_changes":[{"family":"vtp_safety","transitions":["intent_changed"],"subjects":["dist-1"],"intent_kind":"revision_reset","reason":"planned revision reset"}],"note":"CAB-1234"}'}
                  style={{ width: "100%", fontFamily: "var(--mono)", fontSize: 11 }} />
              </details>
              <button className="btn" style={{ marginTop: 10 }} onClick={runCompare}>Compare</button>
              {cmpErr && (
                <div style={{ marginTop: 12 }}>
                  <ErrorBox msg={cmpErr} />
                  <div className="faint" style={{ fontSize: 11, marginTop: 6 }}>
                    No comparison was produced for this pair — nothing below is a result for it.
                  </div>
                </div>
              )}
              {cmp && (
                <div style={{ marginTop: 14, fontSize: 13 }}>
                  <ComparisonDecision
                    value={cmp}
                    currentBaseline={<CurrentBaselineGatePanel
                      value={cmp.current_baseline}
                      completeExport={cmp.operator_evidence?.current_baseline_blocker_export}
                    />}
                    exportFilename={`campaign-${cid}-snapshots-${cmpA}-${cmpB}-comparison.json`}
                  />
                  <div className="row-flex" style={{ marginBottom: 8 }}>
                    <span className="faint" style={{ fontSize: 11 }}>Before→after change result:</span>
                    <span className="chip" data-testid="compare-delta-verdict"
                      style={{ color: compareDeltaColor(cmp.verdict, cmp.current_baseline) }}>
                      <span className="dot" /> {cmp.verdict_display || cmp.verdict}
                    </span>
                  </div>
                  {typeof cmp.verdict_note === "string" && cmp.verdict_note && (
                    <div className="dim" data-testid="compare-verdict-note" style={{ fontSize: 12, marginBottom: 10 }}>
                      {cmp.verdict_note}
                    </div>
                  )}
                  <ProtocolAdjacencyGate value={cmp.protocol_adjacencies} />
                  <div className="grid cols-2" style={{ gap: 8 }}>
                    {/* `?? "—"` (not `?? 0`) throughout: an absent count is unknown, not a measured
                        zero. n_opened_high used to land on `?? 0`, so a comparison with no findings
                        block read "— (0 high)" — half honest, half a fabricated all-clear. */}
                    <div>Opened: <b style={{ color: "var(--crit)" }}>{cmp.findings?.n_opened ?? "—"}</b> ({cmp.findings?.n_opened_high ?? "—"} high)</div>
                    <div>Resolved: <b style={{ color: "var(--ok)" }}>{cmp.findings?.n_resolved ?? "—"}</b></div>
                    <div>Regressed: <b style={{ color: "var(--crit)" }}>{cmp.health?.n_regressed ?? "—"}</b></div>
                    <div>Improved: <b style={{ color: "var(--ok)" }}>{cmp.health?.n_improved ?? "—"}</b></div>
                    {/* physical cabling delta (EDA cable-map SSOT) — coverage-honest: 'not assessed' is disclosed, never a silent zero */}
                    <div>Cables ±: <b>{cmp.cabling?.assessed ? `${cmp.cabling.summary?.n_added ?? 0} added / ${cmp.cabling.summary?.n_removed ?? 0} removed` : "not assessed"}</b></div>
                    {/* audit FE-5: the colour was computed from `n_went_down ?? 0` BEFORE the
                        `assessed` check that picks the text, so an UNASSESSED cabling delta rendered
                        its "—" in var(--ok) — a green em-dash, i.e. the not-observed case painted as
                        the healthy case. Colour now follows the same assessed gate as the text. */}
                    <div>Cables down: <b style={{ color: !cmp.cabling?.assessed ? "var(--text-faint)" : (cmp.cabling.summary?.n_went_down ?? 0) > 0 ? "var(--crit)" : "var(--ok)" }}
                                       title={cmp.cabling?.assessed ? undefined : "No cable-map evidence in one or both snapshots — not assessed, not clean"}>
                      {cmp.cabling?.assessed ? (cmp.cabling.summary?.n_went_down ?? 0) : "—"}</b></div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
      {node}
    </div>
  );
}
