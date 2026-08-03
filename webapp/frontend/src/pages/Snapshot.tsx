import { useState } from "react";
import { Link, useParams } from "react-router";
import { api, bandColor, readyColor, sevColor, LifecycleSummary, SnapshotMeta, Summary } from "../api";
import { Bars, CountUp, ErrorBox, Gauge, Loading, SegBar, SevChip, SkelLines, SkelTable, useAsync } from "../components/ui";
import TopologyGraph from "../components/TopologyGraph";
import CableMap from "../components/CableMap";
import CutoverPlanner from "../components/CutoverPlanner";
import ArchReviewPanel from "../components/ArchReview";
import DesignBlueprintPanel from "../components/DesignBlueprint";
import CausalFlowPanel from "../components/CausalFlow";
import {
  VerificationBadge,
  VerificationWarning,
} from "../components/VerificationStatus";

const HEALTH_TONE = (n: number) => (n >= 80 ? "ok" : n >= 60 ? "watch" : n >= 35 ? "risk" : "crit");

/** A summary count that may legitimately be `""` (the engine published no figure). `Number("")` is 0,
 *  which would turn "not measured" into "measured zero" — return NaN so callers must decide. */
const countOf = (v: unknown): number => {
  if (typeof v === "number") return Number.isFinite(v) ? v : NaN;
  if (typeof v === "string" && v.trim() !== "") { const n = Number(v); return Number.isFinite(n) ? n : NaN; }
  return NaN;
};

/** Must the lifecycle line disclose a coverage gap? Pulled out of LifecycleNote's JSX so it is a pure,
 *  executable predicate: webapp/tests/test_backend.py runs THIS function (extracted from this file and
 *  type-stripped) under node, rather than grepping the source for a phrase.
 *
 *  review r8 F6 — SILENCE-AS-HEALTH, the quietest form of U1-1. With every rollup the engine's ""
 *  ("not measured") and unknown 0, LifecycleNote rendered NOTHING — byte-identical to what a
 *  fully-assessed, fully-clean fleet renders, so the reader could not tell "nothing wrong" from
 *  "nothing measured". `coverageGap` is the backend's FAIL-CLOSED verdict (true when assets were not
 *  assessed AND when the lifecycle section published no basis to count them at all — see
 *  webapp/backend/summary.py::_lifecycle). An OLDER backend that omits the flag falls back to
 *  "nothing measurable was published is itself a gap", never to silence. */
function lifecycleGapDisclosed(coverageGap: boolean | undefined, unknown: number, hasFigures: boolean): boolean {
  if (Number.isFinite(unknown) && unknown > 0) return true;   // counted un-assessed assets
  if (coverageGap === true) return true;                      // the backend's own fail-closed verdict
  if (coverageGap === undefined) return !hasFigures;          // pre-flag backend: silence is not a result
  return false;                                               // measured, and nothing was un-assessed
}

/** The hardware-lifecycle line under the KPI hero.
 *
 *  audit U1-1 (CRITICAL false-health, two bugs in one expression): the page rendered
 *  `{eol ? ` · ${eol} past-EoS` : ""}` from `s.lifecycle?.past_eos`.
 *    (1) FALSY ZERO — a measured 0 past-EoS erased the ONLY lifecycle text on the page, so the
 *        assessed-and-clean case looked identical to the section-absent case; and
 *    (2) it read the RISK rollup alone, so an all-Unknown fleet (nothing assessed at all) also
 *        rendered nothing — the coverage gap was invisible by construction.
 *  Both are the same shape: an un-assessed fleet reading as a healthy one. `unknown` is disclosed
 *  in a non-green tone whenever it is > 0, and a measured 0 now prints as a measurement. */
function LifecycleNote({ lc }: { lc?: LifecycleSummary }) {
  if (!lc || !Object.keys(lc).length) return null;   // section absent -> say nothing, claim nothing
  const eos = countOf(lc.past_eos), ldos = countOf(lc.past_ldos);
  const unknown = countOf(lc.unknown), total = countOf(lc.n_devices);
  const bits: string[] = [];
  if (Number.isFinite(eos)) bits.push(`${eos} past-EoS`);
  if (Number.isFinite(ldos) && ldos > 0) bits.push(`${ldos} past-LDoS`);
  const counted = Number.isFinite(unknown) && unknown > 0;
  const gap = lifecycleGapDisclosed(lc.coverage_gap, unknown, bits.length > 0);   // see r8 F6 above
  const gapText = counted
    ? `${unknown}${Number.isFinite(total) && total > 0 ? `/${total}` : ""} EoL NOT ASSESSED`
    : "EoL NOT ASSESSED — no lifecycle figure was published for this fleet";
  const gapTitle = counted
    ? "No EoX bulletin matched these platforms — their support state was NOT determined. Un-assessed is a coverage gap, never a clean bill of health."
    : "The lifecycle section published no band census and no un-assessed count, so hardware support state was NOT measured here. A missing measurement is a coverage gap, never a clean bill of health.";
  return (
    <>
      {bits.length ? <> · {bits.join(" · ")}</> : null}
      {gap && (
        <>
          {" "}
          <b style={{ color: "var(--text-dim)" }} title={gapTitle}>· {gapText}</b>
        </>
      )}
    </>
  );
}
const GAUGE_COLOR = (n: number) => (!Number.isFinite(n) ? "var(--border)" : n >= 80 ? "var(--ok)" : n >= 60 ? "var(--watch)" : n >= 35 ? "var(--risk)" : "var(--crit)");

/* ---------- generic, shape-robust section renderer ---------- */
function cell(v: any): string {
  if (v === null || v === undefined || v === "") return "—";
  if (Array.isArray(v)) return v.map(cell).join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}
function truncate(s: string, n = 90) { return s.length > n ? s.slice(0, n) + "…" : s; }

/* Render caps. The table is a viewport onto the section, NOT the section — so whenever a cap bites,
   say so (audit FE-4). Silently stopping at 200 rows while the tab badge above still reads the FULL
   engine count (t.count) is the coverage-honesty failure in table form: on the canonical 303-device
   fleet the Health-scores tab announced "303" and rendered 200, and 103 devices simply were not
   there for an engineer who scrolled to the last row and concluded they had seen the fleet. Same for
   the 8-column cap, which drops whole FIELDS with no trace. The full set is always in the workbook /
   explorer deliverable, which is what the note points at. */
const ROW_CAP = 200;
const COL_CAP = 8;

function TruncNote({ shown, total, cols, allCols }:
  { shown: number; total: number; cols?: number; allCols?: number }) {
  const rowsCut = total > shown;
  const colsCut = cols !== undefined && allCols !== undefined && allCols > cols;
  if (!rowsCut && !colsCut) return null;
  return (
    <div className="faint" style={{ fontSize: 11, marginTop: 8 }}>
      ⚠ Showing {rowsCut ? `the first ${shown} of ${total} rows` : `all ${total} rows`}
      {colsCut ? ` and ${cols} of ${allCols} columns` : ""} — this view is capped, not the data.
      The remaining {rowsCut ? `${total - shown} row(s)` : "column(s)"} are NOT absent: open the
      workbook or the Explorer below for the complete section.
    </div>
  );
}

function GenericTable({ data }: { data: any }) {
  if (Array.isArray(data)) {
    if (data.length === 0) return <div className="faint" style={{ fontSize: 13 }}>Empty.</div>;
    const first = data[0];
    if (first && typeof first === "object" && !Array.isArray(first)) {
      const allCols = Array.from(new Set(data.flatMap((r: any) => Object.keys(r || {}))));
      const cols = allCols.slice(0, COL_CAP);
      return (
        <div>
          <div style={{ overflow: "auto" }}>
            <table className="tbl">
              <thead><tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr></thead>
              <tbody>
                {data.slice(0, ROW_CAP).map((r: any, i: number) => (
                  <tr key={`${cell(r?.[cols[0]])}|${i}`} className="row-reveal" style={{ animationDelay: `${Math.min(i, 8) * 40}ms` }}>
                    {cols.map((c) => <td key={c} title={cell(r?.[c])}>{truncate(cell(r?.[c]))}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <TruncNote shown={ROW_CAP} total={data.length} cols={cols.length} allCols={allCols.length} />
        </div>
      );
    }
    // array of arrays / scalars
    return (
      <div>
        <div style={{ overflow: "auto" }}>
          <table className="tbl"><tbody>
            {data.slice(0, ROW_CAP).map((r: any, i: number) => (
              <tr key={i} className="row-reveal" style={{ animationDelay: `${Math.min(i, 8) * 40}ms` }}>
                {(Array.isArray(r) ? r : [r]).map((v: any, k: number) => <td key={k} title={cell(v)}>{truncate(cell(v))}</td>)}
              </tr>
            ))}
          </tbody></table>
        </div>
        <TruncNote shown={ROW_CAP} total={data.length} />
      </div>
    );
  }
  if (data && typeof data === "object") {
    return (
      <table className="tbl"><tbody>
        {Object.entries(data).map(([k, v]) => (
          <tr key={k}><td style={{ color: "var(--text-dim)", width: 220, fontWeight: 600 }}>{k}</td>
            <td title={cell(v)}>{Array.isArray(v) ? `${v.length} item(s)` : truncate(cell(v), 160)}</td></tr>
        ))}
      </tbody></table>
    );
  }
  return <div className="faint">{cell(data)}</div>;
}

function PunchTable({ rows }: { rows: any[] }) {
  return (
    <div style={{ overflow: "auto" }}>
      <table className="tbl">
        <thead><tr><th>Sev</th><th>Category</th><th>Devices</th><th>Title</th><th>Detail</th></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${r.category}|${r.title}|${(r.devices || []).join(",")}` || i}
                className="row-reveal" style={{ animationDelay: `${Math.min(i, 8) * 40}ms` }}>
              <td><SevChip sev={r.severity} /></td>
              <td className="dim">{r.category}</td>
              <td className="mono" style={{ fontSize: 12 }}>{(r.devices || []).join(", ") || "—"}</td>
              <td><b>{r.title}</b></td>
              <td className="dim" title={r.detail} style={{ maxWidth: 360 }}>{truncate(r.detail || "", 140)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ---------- orchestration-peer engines (G1 / I2 / K1) ----------
   Each is a dict {<primary list>, summary}. The generic dict renderer would only show
   "findings: N item(s)"; instead show the summary as a strip + drill into the primary list as a
   real table — true parity with the explorer's coverage-honest cards. */
const ENGINE_PRIMARY: Record<string, string> = {
  acl_line_reachability: "findings",   // G1 — the shadowed/unmatchable ACL lines
  feature_compliance: "features",      // I2 — per-policy-area drift rollup
  capture_integrity: "findings",       // K1 — truncated/paginated/errored captures
  state_assertions: "results",         // A1 — check-pack verdicts (opt-in)
  path_intents: "results",             // G3 — named path-intent verdicts (opt-in)
  external_reconcile: "rows",          // B  — declared-vs-observed drift rows (opt-in)
};
function SummaryStrip({ summary }: { summary: any }) {
  if (!summary || typeof summary !== "object") return null;
  const parts = Object.entries(summary)
    .filter(([, v]) => v !== null && typeof v !== "object")
    .map(([k, v]) => `${k.replace(/^n_/, "").replace(/_/g, " ")}: ${v}`);
  if (!parts.length) return null;
  return <div className="faint" style={{ fontSize: 12, marginBottom: 8 }}>{parts.join("  ·  ")}</div>;
}

/* ---------- Parse yield (Plan A / Tier-1 #3) ----------
   snap.parse_yield = the cmdio zero-parse ledger: a command that returned real CONTENT but whose parser
   produced 0 entities is collected-but-unparsed evidence (a possible platform-variant format gap in the
   parser) — NEVER a device verdict, so the class column ranks evidence-trust, not device health. The
   note renders VERBATIM from the engine (one wording across workbook / explorer / webapp). */
const PY_CLASS = (ev: any, mbe: Set<string>) =>
  ev?.error ? "parser ERROR" : mbe.has(ev?.parser) ? "expected-empty" : "SUSPECT format gap";
const PY_SEV: Record<string, string> = { "parser ERROR": "Critical", "SUSPECT format gap": "High", "expected-empty": "Info" };
const PY_ORD: Record<string, number> = { "SUSPECT format gap": 0, "parser ERROR": 1, "expected-empty": 2 };

function ParseYieldPane({ data }: { data: any }) {
  const s = data?.summary || {};
  const mbe = new Set<string>(Object.entries(data?.per_parser || {})
    .filter(([, c]: [string, any]) => c && (c as any).may_be_empty).map(([n]) => n));
  const events: any[] = Array.isArray(data?.events) ? data.events : [];
  const rows = events.slice().sort((a, b) => (PY_ORD[PY_CLASS(a, mbe)] ?? 9) - (PY_ORD[PY_CLASS(b, mbe)] ?? 9));
  return (
    <div>
      <div className="faint" style={{ fontSize: 12, marginBottom: 6 }}>
        parsers called: {s.parsers_called ?? "—"} ·{" "}
        <span style={{ color: (s.zero_yield_suspect || 0) > 0 ? "var(--crit)" : undefined }}>
          suspect: {s.zero_yield_suspect ?? 0}
        </span>{" "}
        · expected-empty: {s.zero_yield_expected ?? 0} · parser errors: {s.parse_errors ?? 0}
      </div>
      {s.note && <div className="faint" style={{ fontSize: 11, marginBottom: 10 }}>{s.note}</div>}
      <div style={{ overflow: "auto" }}>
        <table className="tbl">
          <thead><tr><th>Class</th><th>Parser</th><th>Device</th><th>Command</th><th className="num">Lines in</th></tr></thead>
          <tbody>
            {rows.map((ev: any, i: number) => {
              const klass = PY_CLASS(ev, mbe);
              return (
                <tr key={`${ev.device}|${ev.parser}|${ev.cmd}` || i}
                    className="row-reveal" style={{ animationDelay: `${Math.min(i, 8) * 40}ms` }}>
                  <td><SevChip sev={PY_SEV[klass]} label={klass} /></td>
                  <td className="mono">{ev.parser || "—"}</td>
                  <td className="mono">{ev.device || "—"}</td>
                  <td className="dim">{ev.cmd || "—"}</td>
                  <td className="num">{ev.lines_in ?? "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {data?.events_truncated && (
        <div className="faint" style={{ fontSize: 11, marginTop: 8 }}>
          … event list truncated at the cap — the per-parser counters carry the full counts.
        </div>
      )}
    </div>
  );
}

function SectionPane({ snapId, name }: { snapId: number; name: string }) {
  const { data, error, loading } = useAsync(() => api.section(snapId, name), [snapId, name]);
  if (loading) return <SkelTable />;
  if (error) return <ErrorBox msg={error} />;
  const d = data!.data;
  if (name === "punchlist" && Array.isArray(d)) return <PunchTable rows={d} />;
  if (name === "device_dossiers" && d?.per_device) return <RegisterTable rows={d.per_device} note={d.note} />;
  if (name === "parse_yield" && d && typeof d === "object" && !Array.isArray(d)) return <ParseYieldPane data={d} />;
  if (name === "whatif" && Array.isArray(d)) {
    // G4 what-if is a LIST of scenarios; flatten each to the Excel sheet's columns (a raw list-of-objects
    // would JSON-stringify the nested summary). lost_path = was reached, now unprovable (never a fake block).
    return <GenericTable data={d.map((sc: any) => ({
      scenario: sc.name || (sc.removed_hosts || []).join(", ") || "(no match)",
      removed: (sc.removed_hosts || []).join(", ") || "—",
      blocked: sc.summary?.blocked ?? 0,
      lost_path: sc.summary?.lost_path ?? 0,
      preserved: sc.summary?.preserved ?? 0,
      inconclusive: (sc.summary?.inconclusive_other ?? 0) + (sc.summary?.other ?? 0),
    }))} />;
  }
  if (name in ENGINE_PRIMARY && d && typeof d === "object" && !Array.isArray(d)) {
    const list = d[ENGINE_PRIMARY[name]];
    return <div><SummaryStrip summary={d.summary} /><GenericTable data={Array.isArray(list) ? list : d} /></div>;
  }
  return <GenericTable data={d} />;
}

/* ---------- Device Risk Register (V3.23.174) ---------- */
const BAND_COLOR: Record<string, string> = {
  Severe: "var(--crit)", Elevated: "var(--risk)", Guarded: "var(--watch)", Low: "var(--ok)",
  Unassessed: "var(--text-faint)",   // coverage gap (no evidence collected) — neutral, never the green "ok"
};
const BAND_SEV: Record<string, string> = { Severe: "Critical", Elevated: "High", Guarded: "Medium", Low: "Low", Unassessed: "Info" };

/** How much of an asset's risk-axis census actually carried evidence.
 *
 *  audit U1-2: compute_device_dossiers ABSTAINS on an axis it has no evidence for (state "na") and weights
 *  abstention at ZERO exposure — so an asset with almost nothing collected scores risk_index 0, bands "Low"
 *  and reads "No stacked risk — routine migration handling." The register already carried `n_na` per row and
 *  no surface rendered it. Structural over the row's own axis census, never a host or band list; mirrors
 *  cisco_toolkit/excel.py::dossier_coverage (the CANONICAL rule) and the explorer's rrCoverage().
 *  The three mirrors cannot import one module across Python / embedded JS / TSX, so drift is caught by
 *  EXECUTION: tests/test_explorer_render_safety.py drives all three over one shared case table
 *  (excel.DOSSIER_COVERAGE_CASES). Change the rule in excel.py and this must follow in the same commit.
 *
 *  review r8 F1 — FAIL CLOSED when there is no census. `!!(n && …)` evaluated false for n === 0, i.e. on
 *  exactly the input the `n_na` fallback below was written for, so a dossier carrying NO axis data read
 *  as fully assessed: absence-rendered-as-health inside the guard that exists to close it. With no
 *  denominator, how much of the band rests on evidence is itself NOT ASSESSED — so disclose it. */
function dossierCoverage(d: any): { na: number; n: number; thin: boolean } {
  const axes = Array.isArray(d?.exposures) ? d.exposures.filter((e: any) => e && typeof e === "object") : [];
  const n = axes.length;
  if (!n) {
    const raw = Number(d?.n_na);
    return { na: Number.isFinite(raw) && raw > 0 ? Math.floor(raw) : 0, n: 0, thin: true };
  }
  const na = axes.filter((e: any) => e.state === "na").length;
  return { na, n, thin: na * 2 >= n };
}

function RegisterTable({ rows, note }: { rows: any[]; note?: string }) {
  return (
    <div style={{ overflow: "auto" }}>
      <table className="tbl">
        <thead><tr><th>#</th><th>Band</th><th>Asset</th><th style={{ minWidth: 130 }}>Risk index</th>
          <th>Impact × exposure</th><th>Axes assessed</th><th>Compound</th><th>Engineer's verdict</th></tr></thead>
        <tbody>
          {rows.map((d, i) => {
            const cov = dossierCoverage(d);
            return (
            <tr key={d.host || i} className="row-reveal" style={{ animationDelay: `${Math.min(i, 8) * 40}ms` }}>
              <td className="dim">{i + 1}</td>
              <td><SevChip sev={cov.thin ? "Info" : (BAND_SEV[d.risk_band] || "Low")}
                           label={cov.thin ? `${d.risk_band} *` : d.risk_band} /></td>
              <td className="mono"><b>{d.host}</b></td>
              <td>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <div style={{ flex: 1, height: 7, borderRadius: 4, background: "var(--surface-2)", overflow: "hidden" }}>
                    <div style={{ width: `${Math.max(2, Number(d.risk_index) || 0)}%`, height: "100%", borderRadius: 4,
                                  background: cov.thin ? "var(--text-faint)" : (BAND_COLOR[d.risk_band] || "var(--text-faint)") }} />
                  </div>
                  <span className="mono" style={{ fontSize: 12, minWidth: 34 }}>{d.risk_index}</span>
                </div>
              </td>
              <td className="mono" style={{ fontSize: 12 }}>{d.impact_score} × {d.exposure_score}</td>
              <td className="mono" style={{ fontSize: 12, color: cov.thin ? "var(--text-dim)" : undefined }}
                  title={!cov.thin
                    ? "Risk axes that carried evidence, of the axes evaluated for this asset."
                    : cov.n
                      ? "An un-assessed axis scores ZERO exposure, so this band was computed largely on absent evidence — a collection gap, never a clean bill of health."
                      : "This asset published no risk-axis census at all, so how much of its band rests on evidence is itself NOT ASSESSED — a collection gap, never a clean bill of health."}>
                {cov.n
                  ? `${cov.n - cov.na}/${cov.n}${cov.thin ? " — mostly NOT ASSESSED" : ""}`
                  : "census ABSENT — NOT ASSESSED"}
              </td>
              <td>
                {(d.compound || []).map((c: any) => (
                  <span key={c.code} className="chip" title={`${c.title} — ${c.basis}`}
                        style={{ marginRight: 4, color: BAND_COLOR[d.risk_band] }}>{c.code}</span>
                ))}
                {!(d.compound || []).length && <span className="faint">—</span>}
              </td>
              <td className="dim" title={d.verdict} style={{ maxWidth: 380 }}>{truncate(d.verdict || "", 130)}</td>
            </tr>
          );})}
        </tbody>
      </table>
      {rows.some((d) => dossierCoverage(d).thin) && (
        <div className="faint" style={{ fontSize: 11, marginTop: 8 }}>
          <b style={{ color: "var(--text-dim)" }}>*</b> half or more of this asset's risk axes were NOT
          assessed. An abstaining axis scores zero exposure, so the band was computed on absent evidence —
          a collection gap, never a clean bill of health.
        </div>
      )}
      {note && <div className="faint" style={{ fontSize: 11, marginTop: 8 }}>{note}</div>}
    </div>
  );
}

/* ---------- local empty-state panel (Unit 10) — a real .panel so an empty section joins the mount
   reveal instead of silently vanishing (bare `return null`). Not exported; lives only in this file. ---------- */
function EmptyPanel({ title, note }: { title: string; note: string }) {
  return (
    <div className="panel">
      <h3>{title}</h3>
      <div className="faint" style={{ fontSize: 12 }}>{note}</div>
    </div>
  );
}

function RiskRegisterPanel({ snapId }: { snapId: number }) {
  // audit FE-2: the fetch used to carry its OWN `.catch(() => null)`, so useAsync's `error` never
  // fired and EVERY failure — a 403 cross-site refusal, a 500 from the device_dossiers recompute, a
  // 503 — landed on the "older snapshots didn't compute it" empty state. That is a positive claim
  // about the SNAPSHOT made from a server fault, and this is the one panel that surfaces the
  // 'Unassessed' coverage gap, so the failure mode erased exactly the blind devices it exists to
  // show. `loading` is read for the same reason: without it the same false claim rendered for the
  // whole duration of the fetch. Absence, error and not-yet-known are now three distinct states.
  const { data, error, loading } = useAsync(() => api.section(snapId, "device_dossiers"), [snapId]);
  const dd = data?.data;
  if (loading && !data) return <div className="panel"><h3>Device Risk Register · the senior-engineer read</h3><SkelTable /></div>;
  if (error) {
    return (
      <div className="panel">
        <h3>Device Risk Register · the senior-engineer read</h3>
        <ErrorBox msg={error} />
        <div className="faint" style={{ fontSize: 11, marginTop: 8 }}>
          The register could NOT be loaded — this is not evidence that the fleet carries no stacked
          risk, and any un-assessed device is still un-assessed. Reload before relying on this page.
        </div>
      </div>
    );
  }
  if (!dd?.per_device?.length) {
    return <EmptyPanel title="Device Risk Register · the senior-engineer read"
      note="No per-device risk register in this snapshot — older snapshots didn't compute it." />;
  }
  const bands = dd.summary?.bands || {};
  // Unassessed (no evidence collected) is a coverage gap, not a risk — keep it out of the
  // risk-flagged rows; it is surfaced as its own count in the panel header instead.
  const flagged = dd.per_device.filter((d: any) => d.risk_band !== "Low" && d.risk_band !== "Unassessed");
  const shown = (flagged.length ? flagged : dd.per_device).slice(0, 8);
  // audit FE-1: the risk chip below is a mutually-exclusive ternary chain, so `Unassessed` only ever
  // reached the header when Severe AND Elevated were both zero — i.e. the coverage gap was hidden by
  // exactly the finding that makes it matter (3 Severe + 40 Unassessed rendered "3 Severe" and the
  // 40 blind devices appeared nowhere, since `flagged` drops them from the rows too). The gap gets
  // its OWN chip, always, independent of the risk chip. "Not observed" is not "healthy".
  const nUnassessed = Number(bands.Unassessed) || 0;
  /* r8 F5, same class one panel up: the engine's "Unassessed" BAND is not the only coverage gap here.
     An asset whose axes mostly (or entirely) abstained is banded "Low" — abstention weighs ZERO
     exposure — so it is dropped from `flagged` AND misses the nUnassessed chip, and the header goes
     green "no stacked risk" over a fleet nobody collected. Count the thin rows too; the headline may
     only be green when something was actually assessed. */
  const nThin = dd.per_device.filter((d: any) => dossierCoverage(d).thin).length;
  const gapped = nUnassessed + nThin;
  return (
    <div className="panel">
      <h3>
        Device Risk Register · the senior-engineer read
        <span className="chip" style={{ marginLeft: 10, color: bands.Severe ? "var(--crit)" : bands.Elevated ? "var(--risk)" : gapped ? "var(--text-faint)" : "var(--ok)" }}>
          {bands.Severe ? `${bands.Severe} Severe` : bands.Elevated ? `${bands.Elevated} Elevated`
            : nUnassessed ? `${nUnassessed} not assessed`
            : nThin ? "no stacked risk observed — coverage-limited" : "no stacked risk"}
        </span>
        {gapped > 0 && !!(bands.Severe || bands.Elevated) && (
          <span className="chip" title="No evidence was collected for these devices — they are a coverage gap, not a clean result"
                style={{ marginLeft: 6, color: "var(--text-faint)" }}>
            + {gapped} not assessed
          </span>
        )}
      </h3>
      <div className="faint" style={{ fontSize: 12, marginBottom: 10 }}>
        Every per-device axis stacked per asset — risk index = topology impact × exposure; CR-xx chips mark
        independent risks coinciding on one box (hover for the why). Full ranking in the "Risk register" section below.
        {nUnassessed > 0 && (
          <> <b style={{ color: "var(--text-dim)" }}>{nUnassessed} device(s) were NOT assessed</b> (no evidence
            collected) and are excluded from the ranking below — un-assessed is a blind spot, never a clean bill
            of health.</>
        )}
        {nThin > 0 && (
          <> <b style={{ color: "var(--text-dim)" }}>{nThin} device(s) were banded on absent evidence</b> (half or
            more of their risk axes not assessed, or no axis census at all) — an abstaining axis scores zero
            exposure, so a "Low" there is a collection gap, never a clean result.</>
        )}
      </div>
      <RegisterTable rows={shown} />
    </div>
  );
}

function Keystones({ meta }: { meta: SnapshotMeta }) {
  const ks = meta.summary.keystones || [];
  if (!ks.length) {
    return <EmptyPanel title="Keystone devices · fleet depends on these most"
      note="No keystone devices flagged — no single switch dominates the fleet's dependency graph." />;
  }
  return (
    <div className="panel">
      <h3>Keystone devices · fleet depends on these most</h3>
      <table className="tbl">
        <thead><tr><th>Device</th><th>Severity</th><th className="num">Stranded</th><th className="num">VLANs</th><th>Impact</th></tr></thead>
        <tbody>
          {ks.map((k, i) => (
            <tr key={k.host || k.device || i} className="row-reveal" style={{ animationDelay: `${Math.min(i, 8) * 40}ms` }}>
              <td className="mono"><b>{k.host || k.device || "—"}</b></td>
              <td>{k.severity ? <SevChip sev={k.severity} /> : "—"}</td>
              <td className="num">{k.stranded ?? "—"}</td>
              <td className="num">{k.vlans_impacted ?? "—"}</td>
              <td className="dim" title={k.detail} style={{ maxWidth: 380 }}>{truncate(k.detail || "", 120)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DeliverablesPanel({ snapId }: { snapId: number }) {
  // audit FE-3: same class as the Risk Register — `useAsync` was destructured for `data` only, so
  // both "still loading" and "/api/meta failed" fell through to the flat assertion "No deliverables
  // are available from this server build", which is a claim about the SERVER derived from not
  // knowing. Loading and failure are now said as themselves.
  const { data, error, loading } = useAsync(() => api.meta(), []);
  const items = data?.deliverables || [];
  if (loading && !data) {
    return <div className="panel"><h3>Deliverables · generated from this snapshot</h3><SkelLines n={2} /></div>;
  }
  if (error) {
    return (
      <div className="panel">
        <h3>Deliverables · generated from this snapshot</h3>
        <ErrorBox msg={error} />
        <div className="faint" style={{ fontSize: 11, marginTop: 8 }}>
          The deliverable catalogue could not be read — this does NOT mean the server has no
          deliverables. Reload before concluding a document is unavailable.
        </div>
      </div>
    );
  }
  if (!items.length) {
    return <EmptyPanel title="Deliverables · generated from this snapshot"
      note="No deliverables are available from this server build." />;
  }
  return (
    <div className="panel">
      <h3>Deliverables · generated from this snapshot</h3>
      <div className="row-flex">
        {items.map((d) =>
          d.available ? (
            <a key={d.key} className="btn" href={api.deliverableUrl(snapId, d.key)} download>
              ↓ {d.label} <span className="chip mono" style={{ fontSize: 9, padding: "1px 6px" }}>{d.ext.toUpperCase()}</span>
            </a>
          ) : (
            <span key={d.key} className="btn" style={{ opacity: 0.45, cursor: "not-allowed" }}
              title="Unavailable — the server is missing the optional library for this format">
              {d.label} <span className="chip mono" style={{ fontSize: 9, padding: "1px 6px" }}>{d.ext.toUpperCase()}</span>
            </span>
          ),
        )}
        <a className="btn" href={api.explorerUrl(snapId)} target="_blank" rel="noreferrer">
          ◈ Interactive Explorer <span className="chip mono" style={{ fontSize: 9, padding: "1px 6px" }}>HTML</span>
        </a>
      </div>
      <div className="faint" style={{ fontSize: 11, marginTop: 10 }}>
        Each is produced by the engine's own writer from this exact snapshot — identical to the CLI output.
      </div>
    </div>
  );
}

export default function SnapshotPage() {
  const { id } = useParams();
  const sid = Number(id);
  const { data: meta, error, loading } = useAsync(() => api.getSnapshot(sid), [sid]);
  const [tab, setTab] = useState<string>("");
  const [showExplorer, setShowExplorer] = useState(false);

  if (loading) return <div className="container"><Loading /></div>;
  if (error) return <div className="container"><ErrorBox msg={error} /></div>;
  const s = meta!.summary;
  // WEBAP-02: when the engine could not compute a fleet average, summarize() emits avg_health as "". Coercing
  // it with `Number("") || 0` produced a finite 0, so the hero Gauge showed a measured-looking red '0' instead
  // of its own '—' unknown state. Pass NaN through so the Gauge (Number.isFinite check) renders '—', and
  // GAUGE_COLOR (now guarded) uses a neutral ring -- mirroring the Dashboard PostureStrip treatment.
  const avg = typeof s.avg_health === "number" ? s.avg_health : NaN;
  // audit-5 FH#22: when the engine computed no fleet health at all (avg_health ""), the fleet is effectively
  // un-assessed -- the sibling KPI cards must NOT show the green 'ok' tone (0 critical / 0 punch-list / 0 not-ready
  // reads identically to a verified-clean fleet). Neutralize their tone, mirroring the Gauge's own '—' state.
  const unknownFleet = !Number.isFinite(avg);
  const lc = s.lifecycle;   // rendered by <LifecycleNote> — see its header for the false-health it fixes
  // audit FE-12: summarize() (webapp/backend/summary.py) SEEDS readiness as {READY:0, CAUTION:0,
  // "NOT READY":0} and only ever increments it from snap["migration_readiness"] — so a snapshot with
  // no migration_readiness section emits the same all-zero object a fully-classified fleet with zero
  // problems would. The tile keyed its tone on `NOT READY > 0 ? crit : CAUTION > 0 ? watch : ok`,
  // which lands on the green `ok` for BOTH, and printed "0✓ 0! 0✕" as if the groups had been counted.
  // The CutoverPlanner further down the SAME page says "No migration waves were derived from this
  // snapshot" for that input — two surfaces, one fact, opposite verdicts. A real classification always
  // assigns EVERY move group one of the three labels, so a zero total can only mean nothing was
  // assessed: say that, and drop the tone (`unknownFleet` can't cover it — avg_health comes from
  // health_scores, an independent section that is routinely present when this one is not).
  const rdy = s.readiness || ({} as Summary["readiness"]);
  const nReady = Number(rdy.READY) || 0, nCaution = Number(rdy.CAUTION) || 0, nNotReady = Number(rdy["NOT READY"]) || 0;
  const noGroupsAssessed = nReady + nCaution + nNotReady === 0;

  const tabs = s.sections;
  const activeTab = tab || (tabs[0]?.key ?? "");

  return (
    <div className="container">
      <div className="breadcrumb">
        <Link to="/campaigns">Campaigns</Link> / <Link to={`/campaigns/${meta!.campaign_id}`}>campaign</Link> / {meta!.label}
      </div>
      <div className="page-head">
        <div>
          <h1>{meta!.label}</h1>
          <div className="sub row-flex">
            <span>{meta!.n_devices} devices · engine {meta!.script_version || s.version} · uploaded {new Date(meta!.uploaded_at).toLocaleString()}</span>
            <VerificationBadge value={s.verification} />
          </div>
        </div>
        <span style={{ flex: 1 }} />
        <a className="btn" href={api.explorerUrl(sid)} target="_blank" rel="noreferrer">↗ Explorer (new tab)</a>
        <button className="btn primary" aria-expanded={showExplorer} onClick={() => setShowExplorer((v) => !v)}>{showExplorer ? "Hide" : "◈ Open"} explorer</button>
      </div>

      <VerificationWarning value={s.verification} />

      {/* KPI hero */}
      <div className="grid" style={{ gridTemplateColumns: "auto 1fr 1fr 1fr", gap: 16, alignItems: "stretch" }}>
        <div className="panel" style={{ display: "grid", placeItems: "center" }}>
          <Gauge value={avg} color={GAUGE_COLOR(avg)} label="avg health" />
        </div>
        <div className={`panel kpi ${unknownFleet ? "" : s.n_critical > 0 ? "crit" : "ok"}`}>
          <div className="l">Critical-band switches</div>
          <div className="v"><CountUp value={s.n_critical} /></div>
          <div className="hint">of {s.n_switches} switches</div>
        </div>
        <div className={`panel kpi ${unknownFleet ? "" : HEALTH_TONE(100 - Math.min(100, s.punchlist.crit_high * 8))}`}>
          <div className="l">Punch-list (crit/high)</div>
          <div className="v"><CountUp value={s.punchlist.crit_high} /><span className="faint" style={{ fontSize: 16, fontWeight: 600 }}> / <CountUp value={s.punchlist.total} /></span></div>
          <div className="hint">prioritised actions</div>
        </div>
        <div className={`panel kpi ${unknownFleet || noGroupsAssessed ? "" : nNotReady > 0 ? "crit" : nCaution > 0 ? "watch" : "ok"}`}>
          <div className="l">Move-group readiness</div>
          {noGroupsAssessed ? (
            <div className="v" style={{ fontSize: 20, color: "var(--text-faint)" }}>—</div>
          ) : (
            <div className="v" style={{ fontSize: 20, display: "flex", gap: 12 }}>
              <span style={{ color: readyColor("READY") }}>{nReady}✓</span>
              <span style={{ color: readyColor("CAUTION") }}>{nCaution}!</span>
              <span style={{ color: readyColor("NOT READY") }}>{nNotReady}✕</span>
            </div>
          )}
          <div className="hint">
            {noGroupsAssessed
              ? <>not assessed — no move group was classified<LifecycleNote lc={lc} /></>
              : <>ready · caution · not ready<LifecycleNote lc={lc} /></>}
          </div>
        </div>
      </div>

      {/* distributions */}
      <div className="grid cols-3" style={{ marginTop: 16 }}>
        <div className="panel"><h3>Health bands</h3><SegBar data={s.bands} colorFor={bandColor} /></div>
        <div className="panel"><h3>Punch-list by severity</h3><Bars data={s.punchlist.by_severity} colorFor={sevColor} /></div>
        <div className="panel"><h3>Punch-list by category</h3><Bars data={s.punchlist.by_category} /></div>
      </div>

      <div className="grid" style={{ marginTop: 16, gap: 16 }}>
        <RiskRegisterPanel snapId={sid} />

        <ArchReviewPanel snapId={sid} />

        <DesignBlueprintPanel snapId={sid} />

        <CausalFlowPanel snapId={sid} />

        <CutoverPlanner snapId={sid} />

        <DeliverablesPanel snapId={sid} />

        <div className="panel" style={{ ["--stagger-i" as any]: 4 }}>
          <h3>Fleet topology · coloured by health band</h3>
          <TopologyGraph snapId={sid} />
        </div>

        <div className="panel" style={{ ["--stagger-i" as any]: 5 }}>
          <h3>Physical cable map · Nokia-EDA style</h3>
          <CableMap snapId={sid} />
        </div>

        <Keystones meta={meta!} />

        {showExplorer && (
          <div className="panel" style={{ padding: 0, overflow: "hidden", ["--stagger-i" as any]: 6 }}>
            {/* sandbox WITHOUT allow-same-origin: the explorer is fully self-contained (embedded
                snapshot; storage is feature-detected for opaque origins), so it needs no origin —
                and must never inherit ours (script there would otherwise reach this app's API). */}
            <iframe title="Network Migration Explorer" src={api.explorerUrl(sid)}
              sandbox="allow-scripts allow-downloads allow-modals"
              style={{ width: "100%", height: "78vh", border: 0, display: "block", background: "var(--bg)" }} />
          </div>
        )}

        {/* detail sections */}
        {tabs.length > 0 && (
          <div className="panel" style={{ ["--stagger-i" as any]: 7 }}>
            <div className="tabs" role="tablist" aria-label="Detail sections" style={{ marginBottom: 16 }}>
              {tabs.map((t) => (
                <button key={t.key} role="tab" id={`sectiontab-${t.key}`} aria-controls={`sectionpanel-${t.key}`}
                        aria-selected={activeTab === t.key} className={activeTab === t.key ? "on" : ""}
                        onClick={() => setTab(t.key)}>
                  {t.label}<span className="ct">{t.count}</span>
                </button>
              ))}
            </div>
            <div role="tabpanel" id={`sectionpanel-${activeTab}`} aria-labelledby={`sectiontab-${activeTab}`}
                 className="tabfade" key={activeTab}>
              <SectionPane snapId={sid} name={activeTab} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
