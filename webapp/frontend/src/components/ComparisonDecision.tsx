import type { ReactNode } from "react";
import type {
  CompareResponse,
  CutoverGate,
  CutoverGateVerdict,
  ImpactsViewRow,
  ObservedL2FailureEvidence,
  PrecertReceipt,
  ProtocolComparisonStatus,
  ProtocolFamilyChange,
  ProtocolFamilyChangeSet,
  ProtocolFamilyChangeSummary,
  RehearsalImpactsView,
} from "../api";

const ROW_CAP = 8;

const GATE_COLOR: Record<CutoverGateVerdict, string> = {
  PASS: "var(--ok)",
  CONDITIONAL: "var(--watch)",
  REVIEW: "var(--watch)",
  INDETERMINATE: "var(--text-faint)",
  FAIL: "var(--crit)",
  REGRESSED: "var(--crit)",
};

const ADMISSION_COLOR: Record<ProtocolComparisonStatus, string> = {
  admitted: "var(--ok)",
  coverage_lost: "var(--watch)",
  not_comparable: "var(--crit)",
};

const DECISION_EFFECT_COLOR: Record<ProtocolFamilyChange["decision_effect"], string> = {
  block: "var(--crit)",
  review: "var(--watch)",
  none: "var(--accent)",
  not_verified: "var(--text-faint)",
};

const L2_REHEARSAL_COLOR: Record<string, string> = {
  simulation_only: "var(--accent)",
  projected_risk: "var(--watch)",
  current_fault: "var(--crit)",
  local_safety_preservation: "var(--accent)",
  observed_survival: "var(--accent)",
  observed_failure: "var(--crit)",
  not_verified: "var(--text-faint)",
};

export interface ProtocolFamilyPresentationBuckets {
  expected: ProtocolFamilyChange[];
  unexpected: ProtocolFamilyChange[];
  coverage: ProtocolFamilyChange[];
  drilldownOnly: ProtocolFamilyChange[];
}

/**
 * Partition rows only from producer-owned classifications.
 *
 * Transition vocabulary remains useful evidence in each row, but it is not a second UI-owned
 * classifier. Rows whose producer effect is `none` and which are not declared expected remain in
 * the per-family drilldown and complete export instead of being relabelled by presentation code.
 */
export function bucketProtocolFamilyRows(
  rows: ProtocolFamilyChange[],
): ProtocolFamilyPresentationBuckets {
  const buckets: ProtocolFamilyPresentationBuckets = {
    expected: [], unexpected: [], coverage: [], drilldownOnly: [],
  };
  for (const row of rows) {
    if (row.decision_effect === "not_verified") buckets.coverage.push(row);
    else if (row.expected) buckets.expected.push(row);
    else if (row.decision_effect === "block" || row.decision_effect === "review") {
      buckets.unexpected.push(row);
    } else buckets.drilldownOnly.push(row);
  }
  return buckets;
}

type ReconciledSummary = Pick<
  ProtocolFamilyChangeSummary,
  "n_subject_changes" | "n_expected" | "n_blocking" | "n_review" | "n_not_verified" | "by_decision_effect"
>;

function summaryCountMismatches(
  label: string,
  summary: ReconciledSummary,
  rows: ProtocolFamilyChange[],
): string[] {
  const effects: Record<ProtocolFamilyChange["decision_effect"], number> = {
    block: 0, review: 0, none: 0, not_verified: 0,
  };
  let expected = 0;
  for (const row of rows) {
    expected += row.expected ? 1 : 0;
    effects[row.decision_effect] += 1;
  }
  const checks: Array<[string, number | undefined, number]> = [
    ["n_subject_changes", summary.n_subject_changes, rows.length],
    ["n_expected", summary.n_expected, expected],
    ["n_blocking", summary.n_blocking, effects.block],
    ["n_review", summary.n_review, effects.review],
    ["n_not_verified", summary.n_not_verified, effects.not_verified],
  ];
  const failures = checks.flatMap(([field, declared, observed]) => (
    typeof declared === "number" && declared !== observed
      ? [`${label}.${field}=${declared}, rows=${observed}`]
      : []
  ));
  if (summary.by_decision_effect) {
    for (const effect of Object.keys(effects) as Array<ProtocolFamilyChange["decision_effect"]>) {
      const declared = summary.by_decision_effect[effect];
      if (typeof declared === "number" && declared !== effects[effect]) {
        failures.push(`${label}.by_decision_effect.${effect}=${declared}, rows=${effects[effect]}`);
      }
    }
  }
  return failures;
}

/** Structural reconciliation only: exact producer fields and counters, never transition semantics. */
export function protocolFamilySummaryMismatches(value: ProtocolFamilyChangeSet): string[] {
  const rows = value.families.flatMap((family) => family.changes);
  const failures = summaryCountMismatches("summary", value.summary, rows);
  for (const family of value.families) {
    failures.push(...summaryCountMismatches(`family[${family.family}]`, family.summary, family.changes));
  }
  return failures;
}

function safeFilename(value: string) {
  const stem = value.trim().replace(/[^a-z0-9._-]+/gi, "-").replace(/^-+|-+$/g, "");
  return stem || "atlas-comparison-receipt.json";
}

function downloadCompleteJson(value: CompareResponse, filename: string) {
  // Export the complete API response, never the capped arrays rendered below. The detached receipt
  // and its digest stay beside every decision input for portable/offline reconciliation.
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: "application/json;charset=utf-8" });
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = safeFilename(filename);
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(href);
}

const COMPLETE_EXPORT_NOTE = "Complete JSON export includes all received rows.";

/** `exportNote` says what the complete JSON export holds of these rows; the default is true only where the rows
 * rendered are the comparison's own rows (the export is the comparison, `downloadCompleteJson`). A `total` of null is
 * a count nobody published (W51 round 4): it reads "unavailable", never a 0 that would claim there is nothing. */
function CapDisclosure({ rendered, total, exportNote = COMPLETE_EXPORT_NOTE }: {
  rendered: number;
  total: number | null;
  exportNote?: string;
}) {
  if (total === null) {
    return (
      <div className="faint" data-testid="comparison-cap-disclosure" data-total="unavailable"
        style={{ fontSize: 10.5, marginTop: 7 }}>
        Rendered: {rendered} · Total: unavailable · Omitted: unavailable. {exportNote}
      </div>
    );
  }
  const omitted = Math.max(0, total - rendered);
  return (
    <div className="faint" data-testid="comparison-cap-disclosure" style={{ fontSize: 10.5, marginTop: 7 }}>
      Rendered: {rendered} · Total: {total} · Omitted: {omitted}. {exportNote}
    </div>
  );
}

function stateText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return "[unrenderable state]";
  }
}

function ChangeRows({ rows, testId, total = rows.length }: {
  rows: ProtocolFamilyChange[];
  testId: string;
  total?: number;
}) {
  const rendered = rows.slice(0, ROW_CAP);
  return (
    <>
      {rendered.length === 0 ? (
        <div className="faint" style={{ fontSize: 11.5 }}>No rows published in this category.</div>
      ) : rendered.map((row, index) => {
        const before = stateText(row.before_state);
        const after = stateText(row.after_state);
        return (
        <div key={`${row.family}|${row.subject}|${row.transition}|${index}`} data-testid={testId}
          style={{ borderTop: index ? "1px solid var(--border-faint)" : undefined, padding: "6px 0" }}>
          <div className="row-flex" style={{ gap: 6, flexWrap: "wrap", alignItems: "baseline" }}>
            <span className="chip mono">{row.family}</span>
            {row.subject_kind && (
              <span className="chip" data-testid={`${testId}-subject-kind`}>
                {row.subject_kind.replaceAll("_", " ").toUpperCase()}
              </span>
            )}
            <span className="chip">{row.transition.replaceAll("_", " ").toUpperCase()}</span>
            <span className="chip" data-testid={`${testId}-effect`}
              style={{ color: DECISION_EFFECT_COLOR[row.decision_effect], borderColor: DECISION_EFFECT_COLOR[row.decision_effect] }}>
              {row.decision_effect.replaceAll("_", " ").toUpperCase()}
            </span>
            <span className="chip" data-testid={`${testId}-expectation`}>
              {row.expected ? "EXPECTED" : "UNEXPECTED"}
            </span>
            <b className="mono" style={{ fontSize: 11.5, overflowWrap: "anywhere" }}>{row.subject || "unnamed subject"}</b>
          </div>
          {(before !== "—" || after !== "—") && (
            <div className="faint mono" style={{ fontSize: 10.5, marginTop: 3 }}>
              {before} → {after}
            </div>
          )}
          {row.note && <div className="dim" style={{ fontSize: 11, marginTop: 3 }}>{row.note}</div>}
        </div>
      );})}
      <CapDisclosure rendered={rendered.length} total={Math.max(total, rows.length)} />
    </>
  );
}

function FamilyChangeSection({
  title,
  rows,
  tone,
  testId,
  total,
}: {
  title: string;
  rows: ProtocolFamilyChange[];
  tone: string;
  testId: string;
  total?: number;
}) {
  return (
    <section aria-label={`${title} protocol family changes`} data-testid={`${testId}-section`}
      style={{ border: "1px solid var(--border-faint)", borderRadius: 8, padding: 9 }}>
      <div className="spread" style={{ gap: 8, marginBottom: 6 }}>
        <b style={{ color: tone, fontSize: 12 }}>{title}</b>
        <span className="chip" style={{ color: tone, borderColor: tone }}>{total ?? rows.length}</span>
      </div>
      <ChangeRows rows={rows} testId={`${testId}-row`} total={total} />
    </section>
  );
}

function PrecertEvidence({ value }: { value?: PrecertReceipt }) {
  if (!value) {
    return (
      <section aria-label="Service and path evidence" data-testid="comparison-precert"
        style={{ border: "1px solid var(--border-faint)", borderRadius: 8, padding: 9 }}>
        <b style={{ fontSize: 12 }}>Service and path evidence</b>
        <div className="faint" style={{ fontSize: 11.5, marginTop: 5 }}>
          No precert/1 receipt was published. Service and path preservation is not verified by this response.
        </div>
      </section>
    );
  }

  const evidence = [
    ...value.regressions.map((text) => ({ kind: "Regression", text, color: "var(--crit)" })),
    ...value.gate_failures.map((text) => ({ kind: "Gate failure", text, color: "var(--crit)" })),
    ...value.blind_spots.map((text) => ({ kind: "Blind spot", text, color: "var(--watch)" })),
  ];
  const rendered = evidence.slice(0, ROW_CAP);
  const verdictColor = value.verdict === "PASS"
    ? "var(--ok)"
    : value.verdict === "FAIL"
      ? "var(--crit)"
      : value.verdict === "CONDITIONAL"
        ? "var(--watch)"
        : "var(--text-faint)";
  const changed = Array.isArray(value.flows.changed) ? value.flows.changed.length : 0;

  return (
    <section aria-label="Service and path evidence" data-testid="comparison-precert"
      style={{ border: "1px solid var(--border-faint)", borderRadius: 8, padding: 9 }}>
      <div className="spread" style={{ gap: 8 }}>
        <b style={{ fontSize: 12 }}>Service and path evidence</b>
        <span className="chip" style={{ color: verdictColor, borderColor: verdictColor }}>{value.verdict}</span>
      </div>
      <div className="dim" data-testid="comparison-precert-note" style={{ fontSize: 11.5, marginTop: 6 }}>
        {value.verdict_note}
      </div>
      <div className="faint" style={{ fontSize: 10.5, marginTop: 5 }}>
        Reachability: {value.flows.assessed ? "assessed" : "not assessed"}
        {typeof value.flows.subnets_tested === "number" && typeof value.flows.subnets_total === "number"
          ? ` · ${value.flows.subnets_tested} of ${value.flows.subnets_total} subnet(s) tested`
          : ""}
        {value.flows.capped ? " · bounded sample" : ""} · {changed} changed flow(s) · {value.segmentation.length} segmentation invariant(s) · {value.intents.length} path intent(s)
      </div>
      {rendered.map((row, index) => (
        <div key={`${row.kind}|${row.text}|${index}`} data-testid="comparison-precert-evidence-row"
          style={{ borderTop: "1px solid var(--border-faint)", marginTop: 6, paddingTop: 6, fontSize: 11 }}>
          <b style={{ color: row.color }}>{row.kind}:</b> <span className="dim">{row.text}</span>
        </div>
      ))}
      <CapDisclosure rendered={rendered.length} total={evidence.length} />
    </section>
  );
}

function ObservedL2Evidence({ value, gate }: {
  value?: ObservedL2FailureEvidence;
  gate?: CutoverGate;
}) {
  const gateStatus = gate?.l2_observed_trial_status;
  if (!value && !gateStatus) return null;
  const status = gateStatus || value?.status || "not_verified";
  const assurance = gate?.l2_observed_trial_assurance
    || value?.assurance_level
    || "not_verified";
  const color = L2_REHEARSAL_COLOR[status] || "var(--text-faint)";
  const phases = value ? ([
    ["Pre-failure", value.source_binding.pre_failure],
    ["Post-failure", value.source_binding.post_failure],
    ["Recovery / comparison after", value.source_binding.recovery],
  ] as const) : [];
  const stepRows = value ? ([
    ["Precondition", value.precondition.status],
    ["Failure witness", value.failure_witness.status],
    ["Post-failure", value.post_failure.status],
    ["Recovery", value.recovery.status],
  ] as const) : [];
  const failures = value?.failures || [];
  const renderedFailures = failures.slice(0, ROW_CAP);
  return (
    <div data-testid="comparison-observed-l2-trial"
      style={{ borderTop: "1px solid var(--border-faint)", marginTop: 8, paddingTop: 8 }}>
      <div className="spread" style={{ gap: 8, alignItems: "start" }}>
        <div>
          <b style={{ fontSize: 11.5 }}>Observed local L2 failure trial</b>
          <div className="faint" style={{ fontSize: 10.5, marginTop: 2 }}>
            Exact subject/scenario only · no service, traffic, or convergence inference
          </div>
        </div>
        <span className="chip" data-testid="comparison-observed-l2-status"
          style={{ color, borderColor: color }}>
          {status.replaceAll("_", " ").toUpperCase()}
        </span>
      </div>
      <div className="dim" data-testid="comparison-observed-l2-note"
        style={{ fontSize: 11, marginTop: 5, overflowWrap: "anywhere" }}>
        {gate?.l2_observed_trial_note
          || "The canonical gate did not publish a context-bound observed-trial conclusion."}
      </div>
      <div className="faint" style={{ fontSize: 10.5, marginTop: 5 }}>
        Family: <span className="mono">{gate?.l2_observed_trial_family || value?.family || "not verified"}</span>
        {" · "}Subject: <span className="mono">{gate?.l2_observed_trial_subject || value?.subject || "not verified"}</span>
        {" · "}Scenario: <span className="mono">{gate?.l2_observed_trial_scenario || value?.failure_scenario || "not verified"}</span>
        {" · "}Assurance: {assurance.replaceAll("_", " ")}
        {" · "}Matched exact local projected risk(s): {gate?.l2_observed_trial_matched_projected_risks ?? 0}
      </div>
      {phases.map(([label, source]) => (
        <div key={label} data-testid="comparison-observed-l2-phase"
          className="faint mono" style={{ fontSize: 10, marginTop: 5, overflowWrap: "anywhere" }}>
          <b>{label}:</b> {source.source_id} · {source.sha256} · {source.bytes} bytes
          <br />collected {source.collected_at} · custody {source.custody_at}
        </div>
      ))}
      {value && (
        <div className="faint mono" data-testid="comparison-observed-l2-witness"
          style={{ fontSize: 10, marginTop: 5, overflowWrap: "anywhere" }}>
          Witness: {value.source_binding.failure_witness.sha256} · {value.source_binding.failure_witness.bytes} bytes
          {" · induced "}{value.source_binding.failure_witness.induced_at}
        </div>
      )}
      {stepRows.length > 0 && (
        <div className="row-flex" style={{ gap: 5, flexWrap: "wrap", marginTop: 6 }}>
          {stepRows.map(([label, stepStatus]) => (
            <span key={label} className="chip" data-testid="comparison-observed-l2-step">
              {label}: {stepStatus.replaceAll("_", " ").toUpperCase()}
            </span>
          ))}
        </div>
      )}
      {value && (
        <div className="faint" data-testid="comparison-observed-l2-claim-boundary"
          style={{ fontSize: 10.5, marginTop: 6 }}>
          Local scenario: {value.claims.local_scenario.replaceAll("_", " ")} · service-path survival: {value.claims.service_path_survival.replaceAll("_", " ")} · traffic continuity: {value.claims.traffic_continuity.replaceAll("_", " ")} · convergence: {value.claims.convergence.replaceAll("_", " ")}
        </div>
      )}
      {renderedFailures.map((failure, index) => (
        <div key={`${failure}|${index}`} data-testid="comparison-observed-l2-failure"
          style={{ color: "var(--crit)", fontSize: 10.5, marginTop: 4 }}>
          {failure}
        </div>
      ))}
      {failures.length > 0 && (
        <CapDisclosure rendered={renderedFailures.length} total={failures.length} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------
// W50: failure-impact rows are shown ONLY through the engine owner's live interpretation (RehearsalImpactsView).
// A comparison's operator_evidence.rehearsal.impacts binds the stored rows as raw evidence (a lower bound's count
// as written, a held zero as a zero), so this view never renders those values. The two tables below are the owner's
// own words, keyed by the stable tokens it publishes, and each is held EQUAL to its owner in
// cisco_toolkit/impact_assessability.py (CODE_PHRASES, VERDICT_LABELS) by webapp/tests/test_impacts_view_constants.py.
// The owner's state words (STATE_WORD) arrive with the view itself (`state_words`), so no copy of the state tokens
// lives here. A token without a word renders as unrecognised, never as a guess.
// ---------------------------------------------------------------------------------------------------------------
const IMPACT_REASON_PHRASES: Readonly<Record<string, string>> = {
  "section_unavailable": "the failure-impact analysis did not complete this run",
  "row_unreadable": "the stored row cannot be read",
  "duplicate_host": "{n} rows name this switch, so no single result can be chosen",
  "indeterminate": "the simulation could not assess this switch (its detail says why)",
  "legacy_row": "the row predates the engine's assessability marker",
  "off_scan_unreadable": "its off-scan VLAN count cannot be read",
  "blind_links_unreadable": "its count of inter-switch links without VLAN evidence cannot be read",
  "no_host": "the row names no readable switch",
  "no_run_config": "its interface running-config, the only source of its gateway addresses, was not captured",
  "off_scan_only": "every VLAN on it has a gateway outside the scan ({n} VLAN(s))",
  "blind_links_only": "{n} inter-switch link(s) on it carry no VLAN evidence, and none of its VLANs could be simulated",
  "off_scan_partial": "{n} VLAN(s) on it have a gateway outside the scan that was not simulated",
  "blind_links": "{n} inter-switch link(s) on it carry no VLAN evidence, so what it carries over them was not simulated",
  "blind_links_legacy": "the row predates the engine's count of inter-switch links without VLAN evidence",
  "uncollected_neighbours": "it faces {n} uncollected neighbour(s) that can carry endpoints",
  "neighbours_unreadable": "the cable map cannot be read to check its neighbours",
};
const IMPACT_VERDICT_LABELS: Readonly<Record<string, string>> = {
  "published": "published",
  "lower_bound": "lower bound",
  "not_assessed": "not assessed",
  "ambiguous": "ambiguous",
};

/** The one view schema this page reads (engine.REHEARSAL_IMPACTS_VIEW_SCHEMA); any other is shown as unrecognised. */
const IMPACTS_VIEW_SCHEMA = "rehearsal_impacts_view/1";
/** The cell kinds the owner publishes (impact_assessability.CELL_KINDS, held equal by test_impacts_view_constants). */
const IMPACT_CELL_KINDS: ReadonlyArray<string> = ["published", "floor", "withheld", "unreadable"];
/** What the complete JSON export holds of the failure-impact rows: the export is the comparison, whose
 * rehearsal.impacts binds the frozen evidence (each stored row that is an object, raw), never this interpretation. */
const IMPACTS_EXPORT_NOTE = "The complete JSON export holds only the bound evidence (each stored row that is an"
  + " object, raw and uninterpreted): neither this interpretation nor any stored row that is not an object.";

const IMPACT_VERDICT_COLOR: Readonly<Record<string, string>> = {
  published: "var(--accent)",
  lower_bound: "var(--watch)",
  not_assessed: "var(--text-faint)",
  ambiguous: "var(--text-faint)",
};

/** The measures of an impacts_view row, with the workbook's Failure Impact column names. */
const IMPACT_CELL_LABELS: ReadonlyArray<readonly [string, string]> = [
  ["severity", "severity"],
  ["stranded", "stranded endpoints"],
  ["vlans_impacted", "VLANs impacted"],
  ["hard", "hard partitions"],
  ["backup", "backup-covered"],
  ["fhrp", "FHRP-covered"],
];

/** An own entry of `table`, so a prototype key ("constructor", "toString", "__proto__") never matches. This is
 * `Object.hasOwn`'s check in its ES5 form: `Object.hasOwn` is ES2022 and this project's TypeScript lib is ES2021. */
function ownEntry<T>(table: Readonly<Record<string, T>>, key: unknown): T | undefined {
  return typeof key === "string" && Object.prototype.hasOwnProperty.call(table, key) ? table[key] : undefined;
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

/** The owner's word for a state token, from the view's own `state_words` ("not collected", "unverified",
 * "analysis unavailable"); `null` for no state, and a token the owner gave no word is named, never guessed at. */
type StateWords = Readonly<Record<string, string>>;

function impactStateWord(state: unknown, words: StateWords): string | null {
  if (state === null || state === undefined) return null;
  const word = ownEntry(words, state);
  return typeof word === "string" && word ? word : `unrecognised state (${String(state)})`;
}

/** One reason in the owner's words, its count filled in; an unknown code is named, never guessed at. */
function impactReason(entry: unknown): string {
  const record = asRecord(entry);
  const phrase = ownEntry(IMPACT_REASON_PHRASES, record.code);
  if (phrase === undefined) {
    return `unrecognised reason code (${typeof record.code === "string" ? record.code : "unreadable"})`;
  }
  const n = typeof record.n === "number" && Number.isSafeInteger(record.n) && record.n >= 0 ? String(record.n) : "?";
  return phrase.replaceAll("{n}", n);
}

/** A cell kind the owner did not publish, named instead of guessed at; `null` for a known kind or no cell at all. */
function unrecognisedCellKind(record: Record<string, unknown>): string | null {
  if (record.kind === undefined || IMPACT_CELL_KINDS.includes(record.kind as string)) return null;
  return `unrecognised value kind (${typeof record.kind === "string" ? record.kind : "unreadable"})`;
}

/** One cell in words: a measurement or the owner's floor text ("≥ 45", "High (lower bound)"); a withheld value as
 * NOT ASSESSED with the owner's state; an unreadable value as unavailable, which is never a zero; a kind the owner
 * does not publish as unrecognised. */
function impactCellText(cell: unknown, words: StateWords): string {
  const record = asRecord(cell);
  const unknownKind = unrecognisedCellKind(record);
  if (unknownKind) return unknownKind;
  if (record.kind === "published" || record.kind === "floor") {
    return typeof record.text === "string" && record.text ? record.text : "unavailable";
  }
  if (record.kind === "withheld") {
    const state = impactStateWord(record.state, words);
    return state ? `not assessed (${state})` : "not assessed";
  }
  if (record.kind === "unreadable") return "unavailable (the stored value cannot be read)";
  return "unavailable";
}

function impactDetailText(cell: unknown, words: StateWords): string {
  const record = asRecord(cell);
  const unknownKind = unrecognisedCellKind(record);
  if (unknownKind) return `Producer detail: ${unknownKind}.`;
  if (record.kind === "published" && typeof record.text === "string" && record.text) {
    return `Producer detail: ${record.text}`;
  }
  if (record.kind === "withheld") {
    const state = impactStateWord(record.state, words);
    return `Producer detail withheld: not assessed${state ? ` (${state})` : ""}.`;
  }
  return "No readable producer detail.";
}

/** How a row is named wherever the view discloses it: the host the owner publishes, else its stored position. */
function impactRowName(row: { index: unknown; host: unknown }): string {
  return typeof row.host === "string" && row.host
    ? row.host
    : `stored row ${String(row.index)} (switch not named by the engine owner)`;
}

function ImpactsViewRowItem({ row, words }: { row: ImpactsViewRow; words: StateWords }) {
  const label = ownEntry(IMPACT_VERDICT_LABELS, row.assessable);
  const color = ownEntry(IMPACT_VERDICT_COLOR, row.assessable) || "var(--text-faint)";
  const state = impactStateWord(row.state, words);
  const reasons = Array.isArray(row.reasons) ? row.reasons.map(impactReason) : [];
  const cells = asRecord(row.cells);
  return (
    <div data-testid="comparison-rehearsal-row" data-assessable={label ? row.assessable : "unrecognised"}
      style={{ borderTop: "1px solid var(--border-faint)", marginTop: 6, paddingTop: 6, fontSize: 11 }}>
      <div className="row-flex" style={{ gap: 6, flexWrap: "wrap", alignItems: "baseline" }}>
        <b className="mono">{impactRowName(row)}</b>
        <span className="chip" data-testid="comparison-rehearsal-row-verdict" style={{ color, borderColor: color }}>
          {label ? label.toUpperCase() : `UNRECOGNISED VERDICT (${String(row.assessable)})`}
        </span>
        {state && (
          <span className="faint" data-testid="comparison-rehearsal-row-state">{state}</span>
        )}
        {row.ranked !== true && (
          <span className="faint" data-testid="comparison-rehearsal-row-unranked">not ranked</span>
        )}
      </div>
      {reasons.length > 0 && (
        <div className="faint" data-testid="comparison-rehearsal-row-reasons" style={{ marginTop: 2 }}>
          Engine-owner reason: {reasons.join("; ")}
        </div>
      )}
      <div className="dim" data-testid="comparison-rehearsal-row-values" style={{ marginTop: 2 }}>
        {IMPACT_CELL_LABELS.map(([field, name]) =>
          `${name}: ${label ? impactCellText(cells[field], words) : "unavailable"}`).join(" · ")}
      </div>
      <div className="faint" data-testid="comparison-rehearsal-row-detail" style={{ marginTop: 2 }}>
        {label ? impactDetailText(cells.detail, words)
          : "The engine owner's verdict on this row is unrecognised here, so none of its values is shown."}
      </div>
    </div>
  );
}

/** The failure-impact rows of a comparison, read ONLY through the engine owner's live impacts_view. The view is
 * shown only when it interpreted exactly the bytes this comparison binds (`source_sha256` equals the bound after
 * snapshot's SHA-256); otherwise, or when no view was supplied, the rows are explicitly unavailable and their raw
 * values are never shown. */
function RehearsalImpacts({ view, boundSha256, evidenceRows }: {
  view?: RehearsalImpactsView | null;
  boundSha256?: string;
  /** The rehearsal's published count of bound rows; null when no rehearsal projection publishes one. */
  evidenceRows: number | null;
}) {
  const live = (
    <div className="faint" data-testid="comparison-rehearsal-impact-live" style={{ fontSize: 10.5, marginTop: 6 }}>
      Failure-impact interpretation is computed live by the engine owner from the bound evidence; it is not part of
      this comparison or of any receipt.{" "}
      {evidenceRows === null
        ? "How many rows it binds is unavailable: no rehearsal projection published that count (n_impacts_total), "
          + "so this is not a statement that it binds none."
        : `The ${evidenceRows} bound row(s) are in the complete JSON export as raw evidence.`}
    </div>
  );
  // A view under a schema this page does not read is unrecognised: none of its values is shown, whatever it holds.
  const schema = view ? (view as { schema?: unknown }).schema : undefined;
  if (view && schema !== IMPACTS_VIEW_SCHEMA) {
    return (
      <>
        {live}
        <div data-testid="comparison-rehearsal-impacts-unrecognised" style={{ color: "var(--watch)", fontSize: 11, marginTop: 6 }}>
          Failure-impact interpretation unrecognised: this page does not read view
          schema {typeof schema === "string" ? `"${schema}"` : "(none)"}. No row value is shown.
        </div>
        <CapDisclosure rendered={0} total={evidenceRows} exportNote={IMPACTS_EXPORT_NOTE} />
      </>
    );
  }
  let unavailable: string | null = null;
  if (!view) {
    unavailable = "this surface does not supply the engine owner's interpretation of the bound rows; the after"
      + " snapshot's Failure impact view, or an execution receipt of this comparison, shows it";
  } else if (view.available !== true) {
    unavailable = typeof view.reason === "string" && view.reason ? view.reason : "no reason was published";
  } else if (!boundSha256 || view.source_sha256 !== boundSha256) {
    unavailable = "the interpretation was computed from different evidence bytes than this comparison binds";
  }
  if (unavailable !== null || !view || view.available !== true) {
    return (
      <>
        {live}
        <div data-testid="comparison-rehearsal-impacts-unavailable" style={{ color: "var(--watch)", fontSize: 11, marginTop: 6 }}>
          Failure-impact interpretation unavailable: {unavailable ?? "no reason was published"}. No row value is shown.
        </div>
        <CapDisclosure rendered={0} total={evidenceRows} exportNote={IMPACTS_EXPORT_NOTE} />
      </>
    );
  }
  const rows = Array.isArray(view.rows) ? view.rows : [];
  const rendered = rows.slice(0, ROW_CAP);
  const total = typeof view.n_rows_total === "number" ? view.n_rows_total : rows.length;
  const unreadable = typeof view.n_rows_unreadable === "number" ? view.n_rows_unreadable : 0;
  const counts = asRecord(view.counts);
  const words: StateWords = Object.fromEntries(Object.entries(asRecord(view.state_words))
    .filter((entry): entry is [string, string] => typeof entry[1] === "string"));
  const sectionState = impactStateWord(view.section_state, words);
  // Every stored row that is not an object, by position, from the owner's own list: the same rule as the census count
  // above (never selected by a reason code, which a failed section words differently), however far down it ranks.
  const unreadableIndexes = Array.isArray(view.unreadable) ? view.unreadable : null;
  // Every row the owner does not rank (held, ambiguous, a withheld or zero floor, unreadable). They sort after every
  // ranked row, so the cap below would drop them without a name; each is named here whatever the cap.
  const unranked = Array.isArray(view.unranked) ? view.unranked : null;
  // W51 round 4: an empty stored list reads as the snapshot's Failure impact tab reads it. The view carries the engine
  // projection's own disclosure when it withholds the empty list (not collected while the collection record is absent
  // or lists a blind device); null means the projection publishes it as collected but empty. A view without the field
  // (an older server) cannot say which, so the empty list is never worded as a finding of no impact.
  const emptyHeld = asRecord(view.empty_disclosure);
  const emptyReason = typeof emptyHeld.reason === "string" && emptyHeld.reason ? emptyHeld.reason : null;
  const emptyWord = emptyReason !== null ? impactStateWord(emptyHeld.state ?? "unverified", words) : null;
  return (
    <>
      {live}
      {sectionState && (
        <div data-testid="comparison-rehearsal-impact-section" style={{ color: "var(--watch)", fontSize: 11, marginTop: 6 }}>
          The bound evidence's failure-impact section is {sectionState}: its rows cannot be read as results, and
          this is not a finding of no impact.
        </div>
      )}
      {!sectionState && total === 0 && (emptyReason !== null ? (
        <div data-testid="comparison-rehearsal-impact-empty" data-impact-empty="withheld"
          style={{ color: "var(--watch)", fontSize: 11, marginTop: 6 }}>
          The bound evidence stores no failure-impact rows, and this is not a finding of no impact ({emptyWord}):{" "}
          {emptyReason}
        </div>
      ) : (
        <div className="faint" data-testid="comparison-rehearsal-impact-empty"
          data-impact-empty={view.empty_disclosure === null ? "collected_but_empty" : "unqualified"}
          style={{ fontSize: 11, marginTop: 6 }}>
          The bound evidence stores no failure-impact rows.
          {view.empty_disclosure === null ? "" : " This view does not say whether the collection reached every device,"
            + " so this is not a finding of no impact; the after snapshot's Failure impact tab says whether its"
            + " collection record leaves the list not collected."}
        </div>
      ))}
      {total > 0 && (
        <div className="faint" data-testid="comparison-rehearsal-impact-census" style={{ fontSize: 10.5, marginTop: 6 }}>
          Engine-owner verdicts over {unreadable > 0 ? `all ${total} stored rows (${unreadable} unreadable)` : `every one of the ${total} stored rows`}:{" "}
          {Object.entries(IMPACT_VERDICT_LABELS).map(([token, word]) =>
            `${typeof counts[token] === "number" ? counts[token] : "unavailable"} ${word}`).join(" · ")}
        </div>
      )}
      {unreadable > 0 && (
        <div data-testid="comparison-rehearsal-impact-unreadable" style={{ color: "var(--watch)", fontSize: 10.5, marginTop: 4 }}>
          Unreadable stored rows (counted above, never dropped): {unreadableIndexes && unreadableIndexes.length > 0
            ? unreadableIndexes.map((index) => `#${String(index)}`).join(", ")
            : "their positions are not published by this view"}
        </div>
      )}
      {total > 0 && (
        <div className="faint" data-testid="comparison-rehearsal-impact-order" style={{ fontSize: 10.5, marginTop: 4 }}>
          Ranked by the engine owner's stranded-endpoint floor or measurement; rows it does not rank follow in stored order.
        </div>
      )}
      {unranked !== null && unranked.length > 0 && (
        <div data-testid="comparison-rehearsal-impact-unranked" style={{ color: "var(--watch)", fontSize: 10.5, marginTop: 4 }}>
          Not ranked by the engine owner ({unranked.length}; each named here whether or not it is rendered below):
          <ul style={{ margin: "2px 0 0", paddingLeft: 16 }}>
            {unranked.map((row, index) => {
              const label = ownEntry(IMPACT_VERDICT_LABELS, row.assessable);
              const state = impactStateWord(row.state, words);
              const reasons = Array.isArray(row.reasons) ? row.reasons.map(impactReason) : [];
              return (
                <li key={`${String(row.index)}|${index}`} data-testid="comparison-rehearsal-impact-unranked-row">
                  <span className="mono">{impactRowName(row)}</span>
                  {" — "}{label ?? `unrecognised verdict (${String(row.assessable)})`}
                  {state ? ` (${state})` : ""}
                  {reasons.length > 0 ? `: ${reasons.join("; ")}` : ""}
                </li>
              );
            })}
          </ul>
        </div>
      )}
      {total > 0 && unranked === null && (
        <div data-testid="comparison-rehearsal-impact-unranked-unavailable" style={{ color: "var(--watch)", fontSize: 10.5, marginTop: 4 }}>
          The rows the engine owner does not rank are not listed by this view; any beyond the cap below are unnamed.
        </div>
      )}
      {rendered.map((row, index) => (
        <ImpactsViewRowItem key={`${String(row.index)}|${index}`} row={row} words={words} />
      ))}
      <CapDisclosure rendered={rendered.length} total={total} exportNote={IMPACTS_EXPORT_NOTE} />
    </>
  );
}

function OperatorEvidence({ value, gate, impactsView, boundSha256 }: {
  value: CompareResponse["operator_evidence"];
  gate?: CutoverGate;
  impactsView?: RehearsalImpactsView | null;
  boundSha256?: string;
}) {
  const rehearsal = value?.rehearsal;
  const rollback = value?.rollback;
  // A count nobody published is unavailable, never 0 (W51 round 4): an absent rehearsal, or one whose n_impacts_total is
  // not a non-negative whole number, says nothing about how many rows the comparison binds.
  const published = rehearsal?.n_impacts_total;
  const evidenceRows = typeof published === "number" && Number.isInteger(published) && published >= 0 ? published : null;
  const l2 = rehearsal?.l2_failure_rehearsal;
  const l2Rows = (l2?.scenarios || []).slice(0, ROW_CAP);
  const rollbackRows = (rollback?.plans || []).slice(0, ROW_CAP);
  return (
    <>
      <section aria-label="Failure rehearsal evidence" data-testid="comparison-rehearsal"
        style={{ border: "1px solid var(--border-faint)", borderRadius: 8, padding: 9 }}>
        <div className="spread" style={{ gap: 8 }}>
          <b style={{ fontSize: 12 }}>Failure rehearsal</b>
          <span className="chip" data-testid="comparison-rehearsal-status"
            style={{
              color: L2_REHEARSAL_COLOR[rehearsal?.status || "not_verified"] || "var(--text-faint)",
              borderColor: L2_REHEARSAL_COLOR[rehearsal?.status || "not_verified"] || "var(--text-faint)",
            }}>
            {(rehearsal?.status || "not_verified").replaceAll("_", " ").toUpperCase()}
          </span>
        </div>
        <div className="dim" style={{ fontSize: 11.5, marginTop: 6 }}>
          {rehearsal?.note || "No cutover_operator_evidence/1 rehearsal projection was published; rehearsal is not verified."}
        </div>
        <ObservedL2Evidence
          value={rehearsal?.observed_l2_failure_evidence}
          gate={gate}
        />
        <RehearsalImpacts view={impactsView} boundSha256={boundSha256} evidenceRows={evidenceRows} />
        {l2 && (
          <div data-testid="comparison-l2-rehearsal"
            style={{ borderTop: "1px solid var(--border-faint)", marginTop: 8, paddingTop: 8 }}>
            <div className="spread" style={{ gap: 8 }}>
              <b style={{ fontSize: 11.5 }}>L2 failure projections</b>
              <span className="chip" data-testid="comparison-l2-rehearsal-status"
                style={{
                  color: L2_REHEARSAL_COLOR[l2.status] || "var(--text-faint)",
                  borderColor: L2_REHEARSAL_COLOR[l2.status] || "var(--text-faint)",
                }}>
                {l2.status.replaceAll("_", " ").toUpperCase()}
              </span>
            </div>
            <div className="faint" style={{ fontSize: 10.5, marginTop: 4 }}>
              Exact-source bound: {l2.source_bound ? "yes" : "no"} · {l2.summary.n_current_faults} current fault(s) · {l2.summary.n_projected_risks} projected risk(s) · {l2.summary.n_not_verified} not verified
            </div>
            {l2Rows.map((row, index) => (
              <div key={`${row.family}|${row.subject}|${index}`} data-testid="comparison-l2-rehearsal-row"
                style={{ borderTop: "1px solid var(--border-faint)", marginTop: 6, paddingTop: 6, fontSize: 11 }}>
                <div className="row-flex" style={{ gap: 6, flexWrap: "wrap", alignItems: "baseline" }}>
                  <span className="chip mono">{row.family}</span>
                  <b className="mono">{row.subject}</b>
                  <span className="chip" data-testid="comparison-l2-rehearsal-disposition"
                    style={{
                      color: L2_REHEARSAL_COLOR[row.disposition] || "var(--text-faint)",
                      borderColor: L2_REHEARSAL_COLOR[row.disposition] || "var(--text-faint)",
                    }}>
                    {row.disposition.replaceAll("_", " ").toUpperCase()}
                  </span>
                </div>
                <div className="faint" style={{ marginTop: 2 }}>
                  {row.failure_scenario.replaceAll("_", " ")} · {row.source_owner}
                </div>
                <div className="dim" style={{ marginTop: 2 }}>{row.note}</div>
              </div>
            ))}
            <CapDisclosure rendered={l2Rows.length} total={l2.summary.n_scenarios} />
          </div>
        )}
      </section>

      <section aria-label="Rollback evidence" data-testid="comparison-rollback"
        style={{ border: "1px solid var(--border-faint)", borderRadius: 8, padding: 9 }}>
        <div className="spread" style={{ gap: 8 }}>
          <b style={{ fontSize: 12 }}>Rollback</b>
          <span className="chip" data-testid="comparison-rollback-status"
            style={{ color: rollback?.status === "planned" ? "var(--watch)" : "var(--text-faint)", borderColor: rollback?.status === "planned" ? "var(--watch)" : "var(--text-faint)" }}>
            {(rollback?.status || "not_verified").replaceAll("_", " ").toUpperCase()}
          </span>
        </div>
        <div className="dim" style={{ fontSize: 11.5, marginTop: 6 }}>
          {rollback?.note || "No cutover_operator_evidence/1 rollback projection was published; rollback coverage is not verified."}
        </div>
        {rollbackRows.map((row, index) => (
          <div key={`${row.group}|${index}`} data-testid="comparison-rollback-row"
            style={{ borderTop: "1px solid var(--border-faint)", marginTop: 6, paddingTop: 6, fontSize: 11 }}>
            <b className="mono">{row.group || "unnamed group"}</b>
            {row.recommended_scenario && <span className="faint"> · {row.recommended_scenario}</span>}
            <div className="dim" style={{ marginTop: 2 }}>{row.rollback}</div>
          </div>
        ))}
        <CapDisclosure rendered={rollbackRows.length} total={rollback?.n_plans_total || 0} />
      </section>
    </>
  );
}

function ReceiptCustody({ value }: { value: CompareResponse }) {
  const admission = value.comparison_admission;
  const receipt = value.comparison_receipt;
  const issues = admission
    ? [
      ...admission.failures.map((text) => ({ kind: "Failure", text, color: "var(--crit)" })),
      ...admission.coverage_gaps.map((text) => ({ kind: "Coverage gap", text, color: "var(--watch)" })),
    ]
    : [];
  const rendered = issues.slice(0, ROW_CAP);
  const status = admission?.status;
  const statusColor = status ? ADMISSION_COLOR[status] : "var(--text-faint)";

  return (
    <section aria-label="Comparison admission and receipt custody" data-testid="comparison-admission"
      style={{ border: "1px solid var(--border-faint)", borderRadius: 8, padding: 9 }}>
      <div className="spread" style={{ gap: 8 }}>
        <b style={{ fontSize: 12 }}>Comparison admission and receipt custody</b>
        <span className="chip" data-testid="comparison-admission-status"
          style={{ color: statusColor, borderColor: statusColor }}>
          {(status || "not verified").replaceAll("_", " ").toUpperCase()}
        </span>
      </div>
      {!admission ? (
        <div className="faint" style={{ fontSize: 11.5, marginTop: 5 }}>
          No source/campaign/engagement admission receipt was published by this legacy response.
        </div>
      ) : (
        <>
          <div className="faint" style={{ fontSize: 10.5, marginTop: 6 }}>
            Engagement: <span className="mono">{admission.engagement_id}</span> · campaign {admission.campaign_id} · assurance {admission.assurance_level.replaceAll("_", " ")}
          </div>
          <div className="faint mono" style={{ fontSize: 10, marginTop: 4, overflowWrap: "anywhere" }}>
            Before snapshot {admission.source_binding.before.snapshot_id}: {admission.source_binding.before.sha256}<br />
            After snapshot {admission.source_binding.after.snapshot_id}: {admission.source_binding.after.sha256}
          </div>
          {rendered.map((row, index) => (
            <div key={`${row.kind}|${row.text}|${index}`} data-testid="comparison-admission-issue"
              style={{ borderTop: "1px solid var(--border-faint)", marginTop: 6, paddingTop: 6, fontSize: 11 }}>
              <b style={{ color: row.color }}>{row.kind}:</b> <span className="dim">{row.text}</span>
            </div>
          ))}
          <CapDisclosure rendered={rendered.length} total={issues.length} />
        </>
      )}
      {receipt && (
        <div className="faint mono" data-testid="comparison-receipt-digests"
          style={{ fontSize: 10, marginTop: 7, overflowWrap: "anywhere" }}>
          Payload: {receipt.payload_sha256}<br />Receipt: {receipt.receipt_sha256}
        </div>
      )}
    </section>
  );
}

export default function ComparisonDecision({
  value,
  currentBaseline,
  exportFilename = "atlas-comparison-receipt.json",
  impactsView,
}: {
  value: CompareResponse;
  /** Optional producer-owned current-state panel, placed directly after the canonical decision. */
  currentBaseline?: ReactNode;
  exportFilename?: string;
  /**
   * W50: the engine owner's live, display-only interpretation of the failure-impact rows this comparison binds,
   * as the API returns it BESIDE the comparison (never inside it, so the export below stays the exact comparison).
   * Without it the rows are shown as unavailable, never as raw values.
   */
  impactsView?: RehearsalImpactsView | null;
}) {
  const gate = value.cutover_gate?.schema === "cutover_gate/1" ? value.cutover_gate : undefined;
  const gateColor = gate ? (GATE_COLOR[gate.verdict] || "var(--text-faint)") : "var(--text-faint)";
  const families = value.protocol_families?.schema === "protocol_family_change_set/1"
    ? value.protocol_families
    : undefined;
  const rows = families?.families.flatMap((family) => family.changes) || [];
  // Presentation consumes the producer's two classifications directly. It does not duplicate the
  // Python transition vocabulary or derive the overall verdict; cutover_gate/1 remains the sole
  // decision owner. Neutral producer rows remain available in the family drilldown/export.
  const buckets = bucketProtocolFamilyRows(rows);
  const reconciliationFailures = families ? protocolFamilySummaryMismatches(families) : [];
  const expectedTotal = families?.summary.n_expected === buckets.expected.length
    ? families.summary.n_expected
    : buckets.expected.length;
  const unexpectedTotal = families?.summary.n_unexpected === buckets.unexpected.length
    ? families.summary.n_unexpected
    : buckets.unexpected.length;
  const declaredCoverage = families?.summary.n_not_verified;
  const coverageTotal = declaredCoverage === buckets.coverage.length
    ? declaredCoverage
    : buckets.coverage.length;
  const gateBackground = gate?.verdict === "PASS"
    ? "var(--ok-soft)"
    : gate?.verdict === "FAIL" || gate?.verdict === "REGRESSED"
      ? "var(--crit-soft)"
      : gate?.verdict === "CONDITIONAL" || gate?.verdict === "REVIEW"
        ? "var(--watch-soft)"
        : undefined;

  return (
    <div data-testid="comparison-decision" style={{ marginBottom: 12 }}>
      <section aria-label="Canonical cutover decision" data-testid="canonical-cutover-decision"
        style={{ border: `1px solid ${gateColor}`, borderRadius: 9, marginBottom: 12, overflow: "hidden" }}>
        <div className="spread" style={{ padding: "10px 11px", gap: 9, background: gateBackground }}>
          <div>
            <b>Canonical cutover decision</b>
            <div className="faint" style={{ fontSize: 10.5, marginTop: 2 }}>Server-owned cutover_gate/1 · sole overall decision</div>
          </div>
          <div className="row-flex" style={{ gap: 7, flexWrap: "wrap", justifyContent: "flex-end" }}>
            <span className="chip" data-testid="canonical-cutover-verdict" style={{ color: gateColor, borderColor: gateColor }}>
              <span className="dot" /> {gate?.verdict || "NOT VERIFIED"}
            </span>
            <button type="button" className="btn ghost" data-testid="comparison-json-export"
              onClick={() => downloadCompleteJson(value, exportFilename)} style={{ fontSize: 10.5, padding: "4px 8px" }}>
              Export complete JSON
            </button>
          </div>
        </div>
        <div style={{ padding: "9px 11px" }}>
          {gate ? (
            <>
              <div className="dim" data-testid="canonical-cutover-operator-note" style={{ fontSize: 12.5, overflowWrap: "anywhere" }}>
                {gate.operator_note}
              </div>
              <div className="faint" data-testid="canonical-cutover-basis" style={{ fontSize: 10.5, marginTop: 7, overflowWrap: "anywhere" }}>
                {gate.note}
              </div>
            </>
          ) : (
            <div className="faint" data-testid="canonical-cutover-legacy-absence" style={{ fontSize: 12 }}>
              This response did not publish a canonical source-bound cutover gate. The legacy delta below remains supporting evidence, not cutover authorization.
            </div>
          )}
        </div>
      </section>

      {currentBaseline}

      <section aria-label="Protocol family changes" data-testid="protocol-family-changes"
        style={{ border: "1px solid var(--border-faint)", borderRadius: 9, padding: 10, marginBottom: 12 }}>
        <div className="spread" style={{ gap: 8, marginBottom: 8 }}>
          <div>
            <b>Protocol family changes</b>
            <div className="faint" style={{ fontSize: 10.5, marginTop: 2 }}>Reference-only composition; owns no score or verdict</div>
          </div>
          {families && (
            <span className="faint" data-testid="protocol-family-server-summary" style={{ fontSize: 10.5 }}>
              Server summary: {families.summary.n_expected} expected · {families.summary.n_unexpected} unexpected · {families.summary.n_coverage_lost} coverage lost
            </span>
          )}
        </div>
        {!families && (
          <div className="faint" style={{ fontSize: 11.5, marginBottom: 8 }}>
            No protocol_family_change_set/1 receipt was published. Family change coverage is not verified.
          </div>
        )}
        {families && (
          <div data-testid="protocol-family-summary-reconciliation"
            style={{
              color: reconciliationFailures.length ? "var(--crit)" : "var(--text-faint)",
              fontSize: 10.5,
              marginBottom: 8,
              overflowWrap: "anywhere",
            }}>
            {reconciliationFailures.length
              ? `NOT VERIFIED — producer summary/row mismatch: ${reconciliationFailures.join("; ")}`
              : "RECONCILED — producer subject, expected, and decision-effect counters match every received row."}
          </div>
        )}
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 8 }}>
          <FamilyChangeSection title="Expected changes" rows={buckets.expected} tone="var(--accent)" testId="family-change-expected"
            total={expectedTotal} />
          <FamilyChangeSection title="Unexpected changes" rows={buckets.unexpected} tone="var(--watch)" testId="family-change-unexpected"
            total={unexpectedTotal} />
          <FamilyChangeSection title="Coverage loss / not verified" rows={buckets.coverage} tone="var(--text-faint)" testId="family-change-coverage"
            total={coverageTotal} />
        </div>
        {buckets.drilldownOnly.length > 0 && (
          <div className="faint" data-testid="protocol-family-drilldown-only" style={{ fontSize: 10.5, marginTop: 8 }}>
            {buckets.drilldownOnly.length} non-expected producer row(s) have decision effect NONE;
            they remain in the family drilldown and complete JSON without being relabelled by this UI.
          </div>
        )}
        {families && families.families.length > 0 && (
          <div data-testid="protocol-assurance-portfolio" style={{ marginTop: 9 }}>
            <div className="faint" style={{ fontSize: 10.5, marginBottom: 5 }}>
              Protocol Assurance portfolio · open a family to inspect its bound subjects
            </div>
            {families.families.map((family) => (
              <details key={`${family.family}|${family.owner_schema}`} data-testid="protocol-assurance-family"
                style={{ borderTop: "1px solid var(--border-faint)", padding: "6px 0" }}>
                <summary style={{ cursor: "pointer", fontSize: 11.5 }}>
                  <b>{family.family}</b>{" · "}
                  <span className="faint">{family.assurance_level.replaceAll("_", " ")} · {family.summary.n_subject_changes} subject change(s)</span>
                </summary>
                <div style={{ padding: "6px 8px 2px" }}>
                  <ChangeRows rows={family.changes} testId="protocol-assurance-subject"
                    total={family.summary.n_subject_changes} />
                </div>
              </details>
            ))}
          </div>
        )}
      </section>

      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 8 }}>
        <PrecertEvidence value={value.precert} />
        <OperatorEvidence value={value.operator_evidence} gate={gate} impactsView={impactsView}
          boundSha256={value.comparison_admission?.source_binding?.after?.sha256} />
        <ReceiptCustody value={value} />
      </div>
    </div>
  );
}
