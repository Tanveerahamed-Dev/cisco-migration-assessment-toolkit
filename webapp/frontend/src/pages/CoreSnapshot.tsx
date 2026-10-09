import { useEffect, useState, type ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { api } from "../api";
import { loadProjection, type Fact, type Projection, type Schemas, type View, type ViewDocument } from "../projection";
import { EvidenceProvider, FactView, ImpactFactView, ListState, Qualifications, StateLabel, ValueText } from "./core/ProjectionEvidence";
import { ProjectionList } from "./core/ProjectionList";
import { TopologyPaths } from "./core/TopologyPaths";
import { ScopeEntryLink } from "../components/ScopePreview";
import "./coreSnapshot.css";

const titles = { overview: "Overview", trust: "Trust", inventory: "Inventory", findings: "Findings", topology: "Topology & Paths", device: "Device" };
const factLabel = (key: string) => key.replaceAll("_", " ");
function FactGrid({ facts, order }: { facts: Readonly<Record<string, Fact>>; order?: readonly string[] }) {
  const entries = order ? order.map((key) => [key, facts[key]] as const) : Object.entries(facts);
  return <div className="projection-fact-grid">{entries.map(([key, fact]) => <FactView key={key} label={factLabel(key)} fact={fact} compact />)}</div>;
}
function Panel({ title, children }: { title: string; children: ReactNode }) {
  return <section className="panel projection-panel"><h2>{title}</h2>{children}</section>;
}
function Disclosure({ children }: { children: ReactNode }) { return <p className="projection-disclosure">{children}</p>; }
function Pointer({ pointer }: { pointer: string | null }) { return pointer ? <code className="projection-pointer">{pointer}</code> : null; }
function deviceUrl(sid: number, host: string) { return `/snapshots/${sid}?${new URLSearchParams({ view: "device", host })}`; }
function referenceUrl(document: Projection, row: Schemas["UiProjection1_RowRef"], view: "findings" | "inventory") {
  const query = new URLSearchParams({ view, ref: row.pointer, row: String(row.index), source: document.identity.sha256, source_bytes: String(document.identity.bytes) });
  if (view === "inventory") query.set("inventory", "endpoints");
  return `/snapshots/${document.identity.snapshot_id}?${query}`;
}
function useReference() {
  const [params] = useSearchParams();
  const pointer = params.get("ref"), token = params.get("row");
  const index = token && /^(0|[1-9][0-9]*)$/.test(token) ? Number(token) : NaN;
  return pointer && Number.isSafeInteger(index) ? { pointer, index } : undefined;
}

function ScopeLink({ sid }: { sid: number }) {
  const [href, setHref] = useState<string | null>(null);
  useEffect(() => {
    let active = true; setHref(null);
    api.scopeView(sid).then((value) => {
      if (active && value.available === true && typeof value.href === "string" && value.href.startsWith("/scope/") && !value.href.includes("\\")) {
        const target = new URL(value.href, window.location.origin);
        if (target.origin === window.location.origin && target.pathname.startsWith("/scope/")) setHref(value.href);
      }
    }).catch(() => {});
    return () => { active = false; };
  }, [sid]);
  return href ? <ScopeEntryLink href={href}>Open in Atlas Scope ↗</ScopeEntryLink> : null;
}

function Overview({ document }: { document: ViewDocument<"overview"> }) {
  const p = document.payload;
  const metricLabels = { n_devices: "Devices with health records", n_collected: "Complete collections", n_endpoints: "Evidenced endpoints", n_vlans: "VLANs in use", avg_health: "Mean fleet health score" };
  return <>
    <Panel title="Fleet posture"><FactView label="Engine statement" fact={p.posture_statement} /></Panel>
    <div className="projection-metrics">{(["n_devices", "n_collected", "n_endpoints", "n_vlans", "avg_health"] as const).map((key) =>
      <section className="panel" key={key}><FactView label={metricLabels[key]} fact={p.facts[key].fact} /></section>)}</div>
    <div className="projection-two">
      <Panel title="Health assessment"><StateLabel state={p.fleet_health.state} />
        {"reason" in p.fleet_health && <p>{p.fleet_health.reason}</p>}
        {p.fleet_health.not_assessed_reason && <p>{p.fleet_health.not_assessed_reason}</p>}
        <FactGrid facts={{ scored: p.fleet_health.n_scored, source_rows: p.fleet_health.n_rows,
          critical: p.facts.n_critical.fact, poor: p.facts.n_poor.fact, worst_band: p.facts.worst_band.fact }} />
        <div className="projection-list-items">{p.fleet_health.bands.map((band) => <article key={band.band}
          className="projection-list-item" aria-label={`${band.band} health band`}>
          <h3>{band.band}</h3><FactGrid facts={{ count: band.n, hosts: band.hosts }} />
          {band.hosts.state === "published" && <div className="projection-device-links">{band.hosts.value.map((host) =>
            <Link key={host} to={deviceUrl(document.identity.snapshot_id, host)}>{host} ↗</Link>)}</div>}
        </article>)}</div>
      </Panel>
      <Panel title="Lifecycle"><FactView label="Assets in lifecycle assessment" fact={p.lifecycle.of} />
        <div className="projection-fact-grid">{p.lifecycle.bands.map((band) => <FactView key={band.band} label={band.band} fact={p.facts[band.fact_name].fact} compact />)}</div>
        <FactView label="As of" fact={p.lifecycle.asof} compact />
      </Panel>
    </div>
    <ProjectionList title="Gating items" document={document} initial={p.top_gating} renderRow={(row) => <>
      <FactView label={`Gating item ${row.index}`} fact={row.fact} /><span className="dim">Engine axis index: {row.axis_index}</span></>} />
    <ProjectionList title="Assessment axes" document={document} initial={p.axes} renderRow={(row) => <>
      <FactView label={row.axis ?? "Unnamed axis"} fact={row.fact} /><span className="dim">Basis sections: {row.basis_sections.join(", ")}</span></>} />
    {p.absent_axes.length > 0 && <Panel title="Axes without a published result">{p.absent_axes.map((row) => <FactView key={row.axis} label={row.axis} fact={row.fact} />)}</Panel>}
    <ProjectionList title="Move-group readiness" document={document} initial={p.readiness.groups} renderRow={(row) =>
        <div role="group" aria-label={`Move-group source row ${row.index}`}>
          <FactGrid facts={{ group: row.group, readiness: row.readiness, switches: row.switches,
            endpoints: row.endpoints, failed_checks: row.n_fail, warning_checks: row.n_warn }} />
          {row.switches.state === "published" && <div className="projection-device-links">{row.switches.value.map((host) =>
            <Link key={host} to={deviceUrl(document.identity.snapshot_id, host)}>{host} ↗</Link>)}</div>}
          <details><summary>Readiness checks and evidence</summary>
            <ListState label={`Readiness checks for source row ${row.index}`} source={row.checks} />
            {row.checks.state === "published" && row.checks.items.map((check) => <div key={check.pointer} className="projection-list-item">
              <FactGrid facts={{ check: check.check, status: check.status, note: check.note, phase: check.phase }} />
              <Pointer pointer={check.pointer} /></div>)}
          </details><Pointer pointer={row.pointer} />
        </div>} />
    <Panel title="Decisions"><FactView label="Design decisions" fact={p.facts.n_design_decisions.fact} />
      <Disclosure>Design-decision details are available in Tools; they have no core-screen projection yet.</Disclosure></Panel>
  </>;
}

// A device's custody under an input that could not assess it, worded for that context. Collected-but-empty here means
// the input's evidence was read but held nothing assessable (the trust_inputs_scope limitation's own words), which the
// generic "Collected, empty" state label would read as an empty, clean collection. The state and its style are kept.
const CUSTODY_TEXT: Partial<Record<Schemas["UiProjection1_TrustInputHost"]["custody"], string>> = {
  collected_but_empty: "Evidence collected, nothing assessable",
};

// One analysis input's gap row, rendered from the contract alone: the ratio sentence appears only when the
// projection published both counts, and a withheld count or list keeps its own state and reason. The sentence states
// two facts, so it carries both facts' qualifications beside it: the count's, and the inventory denominator's own
// (ui_projection._inventory_total publishes its own caveats, which the count does not inherit). Each control opens
// its own fact's caveats.
function InputGap({ row, sid }: { row: Schemas["UiProjection1_TrustInput"]; sid: number }) {
  const { n, of, hosts } = row;
  const ratio = n.state === "published" && of.state === "published" ? `${n.value} of ${of.value} inventory devices could not be assessed` : null;
  return <article className="projection-list-item" aria-label={`${row.input} analysis input`}>
    <h3>{row.input}</h3>
    {ratio !== null && <p className="projection-ratio">{ratio}<Qualifications label={ratio} envelope={n} />
      <Qualifications label={`the inventory denominator of ${ratio}`} envelope={of} text="Denominator qualifications" /></p>}
    <FactGrid facts={{ could_not_be_assessed: n, inventory_devices: of }} />
    {row.sections.length > 0 && <p className="dim">Input sections: {row.sections.join(", ")}</p>}
    <ListState label={`Devices not assessed by ${row.input}`} source={hosts} />
    {hosts.items.length > 0 && <details><summary>Devices and custody</summary>
      <div className="projection-list-items">{hosts.items.map((item) =>
        <div key={item.host} className="projection-list-item" role="group" aria-label={`${item.host} not assessed by ${row.input}`}>
          <Link to={deviceUrl(sid, item.host)}>{item.host} ↗</Link>
          <p>Custody: <StateLabel state={item.custody} text={CUSTODY_TEXT[item.custody]} /></p>
          {item.label !== null && <p className="dim">{item.label}</p>}
          <Pointer pointer={item.pointer} />
        </div>)}</div>
    </details>}
  </article>;
}

function Trust({ document }: { document: ViewDocument<"trust"> }) {
  const p = document.payload;
  return <>
    <Panel title="Evidence coverage"><FactGrid facts={p.coverage_matrix} />
      <Disclosure>These are the engine's published coverage totals. The full device-by-axis matrix is not included in this view.</Disclosure></Panel>
    <Panel title="What the analysis could not see">
      <Disclosure>Each input is one axis of the engine's per-device risk register, not every analysis. The projection counts each input's devices from the engine's per-device custody and shows each device's custody state; nothing is recomputed from raw evidence. A withheld count keeps its state and reason and is never shown as zero.</Disclosure>
      <div className="projection-list-items">{p.inputs.map((row) => <InputGap key={row.input} row={row} sid={document.identity.snapshot_id} />)}</div>
    </Panel>
    <Panel title="Unknown evidence"><FactGrid facts={{ state: p.unknown_evidence.state, events: p.unknown_evidence.n_events,
      unresolved: p.unknown_evidence.n_unresolved, source_coverage_complete: p.unknown_evidence.source_coverage_complete,
      claim_scope: p.unknown_evidence.claim_scope, note: p.unknown_evidence.note }} /></Panel>
    <ProjectionList title="Evidence sources" document={document} initial={p.unknown_evidence.sources} renderRow={(row) => <FactView label={`Source ${row.index}`} fact={row.fact} />} />
    <Panel title="Single source of truth checks"><FactGrid facts={{ verified: p.ssot.verified, facts: p.ssot.n_facts,
      checked: p.ssot.n_checked, violations: p.ssot.n_violations, engine_stamp: p.ssot.engine_stamp }} />
      <p>Stored stamp matches live check: {p.ssot.stamp_matches_live === null ? "Not published" : p.ssot.stamp_matches_live ? "Yes" : "No"}</p></Panel>
    <ProjectionList title="SSOT violations" document={document} initial={p.ssot.violations} renderRow={(row) => <ValueText value={row} />} />
    <Panel title="Section census"><FactGrid facts={p.census.summary} /><p className="dim">Basis: {p.census.basis}</p>
      <p>Embedded census: <StateLabel state={p.census.embedded.state} /> · matches live: {p.census.embedded.matches_live === null ? "Not published" : p.census.embedded.matches_live ? "Yes" : "No"}</p></Panel>
    <ProjectionList title="Section evidence" document={document} initial={p.census.rows} renderRow={(row) => <>
      <h3>{row.key}</h3><StateLabel state={row.state} /><p>{row.kind} · published count: {row.count === null ? "Not published" : row.count}</p>
      <p>{row.note}</p><Pointer pointer={row.pointer} /></>} />
    <ProjectionList title="Recorded analysis failures" document={document} initial={p.failures.record} renderRow={(row) => <ValueText value={row} />} />
    <Panel title="Failure attribution"><p>Unattributed failure: {p.failures.unattributed ? "Yes" : "No"}</p>
      <ValueText value={p.failures.direct_sections} /></Panel>
    <Panel title="Limits and qualifications"><ul className="projection-limitations">{document.limitations.map((item) =>
      <li key={item.id}><strong>{factLabel(item.id)}</strong><p>{item.text}</p><small>{item.owner} · {item.applies_to.join(", ")}</small></li>)}</ul></Panel>
  </>;
}

function FindingRollup({ rollup, label }: { rollup: Schemas["UiProjection1_DeviceRow"]["findings"]; label: string }) {
  return <div className="projection-fact-grid" role="group" aria-label={label}>
    <FactView label="Worst finding severity" fact={rollup.worst} compact />
    <FactView label="Findings by severity" fact={rollup.by_severity} compact />
  </div>;
}

function CoverageRollup({ rollup, label }: { rollup: Schemas["UiProjection1_DeviceRow"]["coverage"]; label: string }) {
  return <div className="projection-fact-grid" role="group" aria-label={label}>
    <FactView label="Worst coverage state" fact={rollup.worst} compact />
    <FactView label="Abstaining coverage axes" fact={rollup.n_abstained} compact />
  </div>;
}

// G10/G11: the engine's stored scanned-model rows selected for this device, rendered cell by cell as supplied.
// A withheld cell shows its own state and reason, never a value, a zero or a clean bill; rows keep engine order.
// The device document carries no topology legend, so each row's style fact is shown as the engine's own label
// and token. No tone, severity map or bridge test exists on this page.
function RowRefs({ label, refs }: { label: string; refs: Schemas["UiProjection1_RowRefList"] }) {
  return <div><ListState label={label} source={refs} />
    {refs.items.map((ref) => <Pointer key={`${ref.index}:${ref.pointer}`} pointer={ref.pointer} />)}</div>;
}

// The row's cells go through ImpactFactView, the view the fleet topology's failure-impact rows share (one builder,
// ui_projection._topology_impact): a published measure the engine marks as a minimum (it cites a witness) reads
// "≥ N" with its reason, never the bare count; an unmarked published value, a published 0 included, stays itself.
function FailureImpactRow({ row }: { row: Schemas["UiProjection1_TopologyImpactRow"] }) {
  const cell = (field: "severity" | "vlans_impacted" | "stranded" | "hard" | "backup" | "fhrp" | "off_scan_gw_vlans", label: string) =>
    <ImpactFactView field={field} label={label} fact={row[field]} row={row.pointer} />;
  return <div role="group" aria-label={`Failure impact source row ${row.index}`}>
    <div className="projection-fact-grid">
      <FactView label="Engine presentation" fact={row.style} compact />
      {cell("severity", "Severity")}
      {cell("vlans_impacted", "VLANs impacted")}
      {cell("stranded", "Stranded endpoints")}
      {cell("hard", "Hard-partition VLANs")}
      {cell("backup", "Backup-covered VLANs")}
      {cell("fhrp", "FHRP-covered VLANs")}
      {cell("off_scan_gw_vlans", "Off-scan gateway VLANs")}
    </div>
    <FactView label="Per-VLAN detail" fact={row.detail} />
    <details><summary>Row host and topology node join</summary>
      <FactView label="Row host" fact={row.host} compact />
      <RowRefs label={`Topology node records for failure impact row ${row.index}`} refs={row.node_refs} />
    </details><Pointer pointer={row.pointer} />
  </div>;
}

function StructuralLinkRow({ row }: { row: Schemas["UiProjection1_TopologyStructuralLinkRow"] }) {
  return <div role="group" aria-label={`Structural link source row ${row.index}`}>
    <div className="projection-fact-grid">
      <FactView label="Engine presentation" fact={row.style} compact />
      <FactView label="Link ends" fact={row.ends} compact />
      <FactView label="Bridge" fact={row.is_bridge} compact />
      <FactView label="Switch pairs severed" fact={row.pairs_cut} compact />
      <FactView label="Betweenness" fact={row.betweenness} compact />
      <FactView label="Betweenness rank" fact={row.rank} compact />
    </div>
    <details><summary>Node joins and host-pair cable candidates</summary>
      <RowRefs label={`A-end node records for structural link row ${row.index}`} refs={row.a_nodes} />
      <RowRefs label={`B-end node records for structural link row ${row.index}`} refs={row.b_nodes} />
      <RowRefs label={`Host-pair cable candidates for structural link row ${row.index}`} refs={row.host_pair_cable_refs} />
    </details><Pointer pointer={row.pointer} />
  </div>;
}

function DeviceCard({ row, sid }: { row: Schemas["UiProjection1_DeviceRow"]; sid: number }) {
  return <article><h3><Link to={deviceUrl(sid, row.host)}>{row.host} ↗</Link></h3><Pointer pointer={row.pointer} />
    <FactGrid facts={{ model: row.model, health_band: row.health_band, move_group: row.move_group }} />
    <FindingRollup label={`Finding severity for ${row.host}`} rollup={row.findings} />
    <CoverageRollup label={`Coverage for ${row.host}`} rollup={row.coverage} />
    <details><summary>Collection, identity and risk</summary><FactGrid facts={{ health_score: row.health_score, risk_band: row.risk_band,
      collection: row.collection_status, platform: row.platform, software: row.sw_version,
      serial: row.serial_number, role: row.role, lifecycle: row.lifecycle_band }} /></details>
  </article>;
}

function Inventory({ document }: { document: ViewDocument<"inventory"> }) {
  const [params, setParams] = useSearchParams();
  const tab = params.get("inventory") ?? "devices";
  const reference = useReference();
  const p = document.payload;
  return <>
    <nav className="projection-subnav" aria-label="Inventory categories">{["devices", "vlans", "endpoints", "peers"].map((key) =>
      <button className="btn" key={key} aria-current={tab === key ? "page" : undefined} onClick={() => {
        const next = new URLSearchParams(params); next.set("inventory", key); setParams(next);
      }}>{key === "vlans" ? "VLANs" : key[0].toUpperCase() + key.slice(1)}</button>)}</nav>
    {tab === "devices" && <><Panel title="Device inventory"><FactView label="Engine device total" fact={p.devices.total} /></Panel>
      <ProjectionList title="Devices" paired document={document} initial={p.devices.rows} renderRow={(row) => <DeviceCard row={row} sid={document.identity.snapshot_id} />} /></>}
    {tab === "vlans" && <><Panel title="VLAN inventory"><FactView label="Engine VLAN total" fact={p.vlans.total} /></Panel>
      <ProjectionList title="VLANs" document={document} initial={p.vlans.rows} renderRow={(row) => <article>
        <FactGrid facts={{ vlan: row.vlan, name: row.name, readiness: row.readiness, stp_root: row.stp_root, root_election_state: row.stp_root_state,
          root_election_reason: row.stp_root_reason, default_election: row.stp_root_default_election }} />
        <details><summary>Gateway, endpoints and migration detail</summary><FactGrid facts={{ fhrp: row.fhrp, gateways: row.gateway_svi_hosts,
          endpoint_count: row.endpoint_count, endpoint_mix: row.endpoint_mix, wave: row.wave, scenario: row.scenario,
          domain: row.app_domain, criticality: row.criticality, dependencies: row.dependencies, window: row.cutover_window,
          rollback_owner: row.rollback_owner, root_claimants: row.stp_root_claimants, root_identities: row.stp_root_identities }} />
          <Pointer pointer={row.pointer} /></details></article>} /></>}
    {tab === "endpoints" && <><Panel title="Endpoint inventory"><FactView label="Engine endpoint total" fact={p.endpoints.total} /></Panel>
      <ProjectionList title="Endpoints" reference={reference} document={document} initial={p.endpoints.rows} renderRow={(row) => <article>
        <FactGrid facts={{ host: row.host, port: row.port, mac: row.mac, vlan: row.vlan, ip: row.ip, class: row.endpoint_class,
          confidence: row.confidence, vendor: row.vendor, mac_count: row.mac_count, evidence: row.evidence }} /><Pointer pointer={row.pointer} /></article>} />
      <ProjectionList title="Shared IP evidence" document={document} initial={p.endpoints.shared_ip} renderRow={(row) => <FactView label={`Shared IP row ${row.index}`} fact={row.fact} />} />
      <ProjectionList title="Dual-homed endpoints" document={document} initial={p.endpoints.dual_homed} renderRow={(row) => <>
        <FactGrid facts={{ mac: row.mac, class: row.endpoint_class, ip: row.ip, vendor: row.vendor, switches: row.switches,
          ports: row.ports, groups: row.move_groups, split_across_groups: row.split_across_groups }} />
        <Cap label="Port list" cap={row.ports_cap} /></>} /></>}
    {tab === "peers" && <ProjectionList title="Uncollected peers" document={document} initial={p.uncollected_peers} renderRow={(row) => <>
      <FactGrid facts={{ host: row.host, kind: row.kind }} /><Pointer pointer={row.pointer} /></>} />}
    {!["devices", "vlans", "endpoints", "peers"].includes(tab) && <Disclosure>Unknown inventory category. Choose a category above.</Disclosure>}
  </>;
}

function Cap({ label, cap }: { label: string; cap: Schemas["UiProjection1_Cap"] | Schemas["UiProjection1_EvidenceCap"] }) {
  return <div className="projection-cap"><p>{label} engine cap: {cap.limit} · reached: {cap.reached === null ? "Not published" : cap.reached ? "Yes" : "No"}</p>
    <FactView label={`${label} engine source total`} fact={cap.total} compact /></div>;
}
function Finding({ row, sid }: { row: Schemas["UiProjection1_FindingRow"]; sid: number }) {
  return <article className="projection-finding"><FactView label="Finding" fact={row.title} /><FactGrid facts={{ severity: row.severity, priority: row.priority, devices: row.devices }} />
    {row.devices.state === "published" && <div className="projection-device-links">{row.devices.value.map((host) =>
      <Link key={host} to={deviceUrl(sid, host)}>{host} ↗</Link>)}</div>}
    <details><summary>Issue, remediation and evidence</summary>
      <FactView label="Issue" fact={row.detail} /><FactView label="Remediation" fact={row.remediation} />
      <FactGrid facts={{ rank: row.rank, category: row.category, wave: row.wave, severity_basis: row.severity_basis,
      confidence: row.evidence_confidence, source_command: row.source_command, evidence_basis: row.evidence_basis }} />
      <ListState label="Finding evidence references" source={row.evidence_refs} />
      {row.evidence_refs.items.map((item) => <FactView key={item.pointer} label={`Evidence reference ${item.index}`} fact={item.fact} />)}
      {row.evidence_refs_total && <FactView label="Evidence reference source total" fact={row.evidence_refs_total} />}
      {row.evidence_refs_cap && <Cap label="Finding references" cap={row.evidence_refs_cap} />}
      <Pointer pointer={row.pointer} /></details></article>;
}
// G21 (W41) publishes the punch-list facet totals (findings.facets): one count per severity and per category, in the
// engine's vocabulary order, and a paged per-inventory-device list. Each is the engine's own count with its own state,
// so a withheld total shows its state and reason, never a zero; this page neither counts the rows nor fills a gap.
//
// W51 round 4: a published severity or category count can be only a lower bound, and the engine marks it so by the
// caveat it carries (ui_projection._finding_facets: while a fleet qualification applies -- blind devices, devices
// without a captured running-config -- or a category's source section is incomplete, "a positive count is a lower
// bound that carries this caveat"). These are hand copies of those caveat ids, held equal to the owner by
// tests/test_ui_projection_finding_facets.py. Such a count renders through the shared bound treatment (FactView's
// lowerBound: "≥ N" with a visible reason), never as a bare exact number. Any other caveat (a one-hop attribution, the
// device facet's scope note) does not make a count a minimum.
const FACET_LOWER_BOUND_CAVEATS: readonly string[] = [
  "fleet_lists_exclude_blind_devices", "findings_without_running_config", "finding_facet_source_incomplete",
];
function facetLowerBound(fact: Fact): string | undefined {
  if (fact.state !== "published") return undefined;
  const cited = (fact.caveats ?? []).filter((id) => FACET_LOWER_BOUND_CAVEATS.includes(id));
  return cited.length
    ? `the engine publishes this count only as a minimum while ${cited.join(", ")} applies (see its Qualifications)`
    : undefined;
}
function FindingFacets({ document }: { document: ViewDocument<"findings"> }) {
  const facets = document.payload.facets;
  return <>
    <Panel title="Findings by severity"><div className="projection-fact-grid">{facets.severity.map((row) =>
      <FactView key={row.k} label={`${row.k} findings`} fact={row.n} compact lowerBound={facetLowerBound(row.n)} />)}</div></Panel>
    <Panel title="Findings by category"><div className="projection-fact-grid">{facets.category.map((row) =>
      <FactView key={row.k} label={`${row.k} findings`} fact={row.n} compact lowerBound={facetLowerBound(row.n)} />)}</div></Panel>
    <ProjectionList title="Findings by inventory device" document={document} initial={facets.device} renderRow={(row) =>
      <FactView label={`Findings on ${row.k}`} fact={row.n} compact />} />
  </>;
}
function Findings({ document }: { document: ViewDocument<"findings"> }) {
  const reference = useReference();
  return <><Panel title="Prioritised findings"><FactView label="Engine finding total" fact={document.payload.total} />
    <Disclosure>Rows retain the engine's order. The facet totals below are the engine's own counts (G21), each with its own state: a withheld total is not a zero, and a total the engine publishes only as a minimum reads ≥ N.</Disclosure></Panel>
    <FindingFacets document={document} />
    <ProjectionList title="Findings" reference={reference} document={document} initial={document.payload.rows} renderRow={(row) => <Finding row={row} sid={document.identity.snapshot_id} />} /></>;
}

function Device({ document }: { document: ViewDocument<"device"> }) {
  const p = document.payload;
  const host = p.host ?? "";
  return <>
    <Panel title={p.host ?? "Device not identified"}><FactView label="Move group" fact={p.move_group} /><FactGrid facts={p.identity} /></Panel>
    <div className="projection-two"><Panel title="Health"><FactGrid facts={{ score: p.health.score, band: p.health.band, role: p.health.role }} /></Panel>
      <Panel title="Collection"><FactGrid facts={p.collection} /></Panel></div>
    <div className="projection-two"><Panel title="Physical"><FactGrid facts={p.physical} /></Panel><Panel title="Lifecycle"><FactGrid facts={p.lifecycle} /></Panel></div>
    <Panel title="Finding severity"><FindingRollup label="Device finding severity" rollup={p.findings_rollup} /></Panel>
    <Panel title="Coverage summary"><CoverageRollup label="Device coverage summary" rollup={p.coverage_rollup} /></Panel>
    <Panel title="Risk register"><FactView label="Risk band" fact={p.dossier.risk_band} /></Panel>
    <ProjectionList title="If this device fails" document={document} host={host} initial={p.failure_impact} renderRow={(row) => <FailureImpactRow row={row} />} />
    <ProjectionList title="Structural links" document={document} host={host} initial={p.structural_links} renderRow={(row) => <StructuralLinkRow row={row} />} />
    <Disclosure>Failure impact and structural links are the engine's stored scanned-model rows for this device, in engine order; this page does not simulate, rank or fill them in. This device view carries no topology legend, so each row's presentation is shown as the engine's label and token, without a colour tone.</Disclosure>
    <ProjectionList title="Exposure axes" document={document} host={host} initial={p.dossier.exposures} renderRow={(row) => <FactView label={`Exposure ${row.index}`} fact={row.fact} />} />
    <ProjectionList title="Compound findings" document={document} host={host} initial={p.dossier.compound} renderRow={(row) => <FactView label={`Compound ${row.index}`} fact={row.fact} />} />
    <ProjectionList title="Health deductions" document={document} host={host} initial={p.health.deductions} renderRow={(row) => <FactView label={`Deduction ${row.index}`} fact={row.fact} />} />
    <Cap label="Health deductions" cap={p.health.deductions_cap} />
    <Disclosure>Deduction references are an ordered subsequence. They are shown separately and are not paired by row position.</Disclosure>
    <ProjectionList title="Deduction evidence references" document={document} host={host} initial={p.health.deduction_refs} renderRow={(row) => <FactView label={`Deduction reference ${row.index}`} fact={row.fact} />} />
    <Cap label="Deduction references" cap={p.health.deduction_refs_cap} />
    <ProjectionList title="Device coverage" document={document} host={host} initial={p.coverage} renderRow={(row) =>
      <div role="group" aria-label={`Coverage axis ${row.axis}`}>
        <FactView label={row.axis} fact={row.fact} />
        <FactGrid facts={{ dimension: row.dimension, verdict_source: row.verdict_source, is_abstention: row.is_abstention }} />
      </div>} />
    <details className="panel projection-engineering"><summary>Interfaces, links and routing</summary>
      <ProjectionList title="Interfaces" document={document} host={host} initial={p.interfaces.rows} renderRow={(row) => <><h3>{row.port}</h3><FactGrid facts={row.cells} order={p.interfaces.columns} />
        <FactView label="Running configuration observed" fact={row.run_config_observed} compact /><Pointer pointer={row.pointer} /></>} />
      <ProjectionList title="Links" document={document} host={host} initial={p.links} renderRow={(row) => <FactGrid facts={{ ends: row.ends, speed: row.speed, confirmation: row.confirmation, operational_status: row.op_status }} />} />
      <ProjectionList title="Routes" document={document} host={host} initial={p.routes} renderRow={(row) => <FactGrid facts={{ prefix: row.prefix, source: row.source, next_hop: row.next_hop, interface: row.out_intf, admin_distance: row.admin_distance }} />} />
      <ProjectionList title="Routing neighbors" document={document} host={host} initial={p.routing_neighbors} renderRow={(row) => <><h3>{row.protocol}</h3>
        <ListState label={`${row.protocol} neighbors`} source={row.neighbors} />{row.neighbors.items.map((item) =>
          <FactGrid key={item.pointer} facts={{ neighbor: item.neighbor, state: item.state, address: item.address, interface: item.interface, as: item.as }} />)}</>} />
    </details>
    <details className="panel projection-engineering"><summary>Security and remediation</summary>
      <FactView label="Security summary" fact={p.security.summary} />
      <ProjectionList title="Security checks" document={document} host={host} initial={p.security.checks} renderRow={(row) => <FactView label={`Check ${row.index}`} fact={row.fact} />} />
      <ProjectionList title="Native VLAN mismatches" document={document} host={host} initial={p.native_vlan_mismatches} renderRow={(row) => <FactView label={`Mismatch ${row.index}`} fact={row.fact} />} />
      <FactView label="Remediation notice" fact={p.remediation.banner} />
      <ProjectionList title="Remediation" document={document} host={host} initial={p.remediation.items} renderRow={(row) => <FactGrid facts={{ severity: row.severity, category: row.category, title: row.title,
        why: row.why, commands: row.commands, verify: row.verify, caution: row.caution, source: row.source, wave: row.wave }} />} />
      <ProjectionList title="NRFU cases" document={document} host={host} initial={p.nrfu_cases} renderRow={(row) => <FactGrid facts={{ id: row.id, scope: row.scope, command: row.command,
        source_key: row.source_key, phase: row.phase, expected: row.expected, evidence_state: row.evidence_state }} />} />
    </details>
    <ProjectionList title="Device finding references" document={document} host={host} initial={p.findings} renderRow={(row) => <>
      <p>Finding source index {row.index}</p><Pointer pointer={row.pointer} /><Link to={referenceUrl(document, row, "findings")}>Open referenced finding ↗</Link></>} />
    <ProjectionList title="Device endpoint references" document={document} host={host} initial={p.endpoints} renderRow={(row) => <>
      <p>Endpoint source index {row.index}</p><Pointer pointer={row.pointer} /><Link to={referenceUrl(document, row, "inventory")}>Open referenced endpoint ↗</Link></>} />
  </>;
}

export default function CoreSnapshot() {
  const { id } = useParams();
  const sid = Number(id);
  const [params] = useSearchParams();
  const requested = params.get("view") ?? "overview";
  const valid = Object.prototype.hasOwnProperty.call(titles, requested);
  const view = valid ? requested as View : "overview";
  const host = view === "device" ? params.get("host") ?? undefined : undefined;
  const expectedSource = params.get("source"), expectedBytes = params.get("source_bytes");
  const key = JSON.stringify([id, view, host, expectedSource, expectedBytes]);
  const [result, setResult] = useState<{ key: string; document: Projection } | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setResult(null); setFailure(null);
    if (!valid || (view === "device" && host === undefined)) {
      setFailure({ key, message: "Choose a valid view and an exact device from Inventory." });
      return;
    }
    loadProjection(sid, view, host, controller.signal).then((document) => {
      if (expectedSource !== null && (document.identity.sha256 !== expectedSource || String(document.identity.bytes) !== expectedBytes)) {
        throw new Error("The referenced record belongs to a different stored snapshot. Return to Inventory and select it again.");
      }
      if (!controller.signal.aborted) setResult({ key, document });
    }).catch((error) => {
      if (!controller.signal.aborted) setFailure({ key, message: error instanceof Error ? error.message : "Projection unavailable." });
    });
    return () => controller.abort();
  }, [key, sid, view, host, valid, retry, expectedSource, expectedBytes]);
  const document = result?.key === key ? result.document : null;
  return <main className="container projection-shell">
    <div className="breadcrumb"><Link to="/campaigns">Campaigns</Link> / Snapshot {id}</div>
    <header className="page-head"><div><h1>{view === "device" ? host ?? "Device" : `Snapshot ${id}`}</h1>
      <p className="sub">Evidence-led migration assessment</p></div><span className="spacer" /><ScopeLink key={sid} sid={sid} />
      <Link className="btn" to={`/snapshots/${id}/tools`}>Tools and downloads</Link></header>
    <nav className="projection-nav" aria-label="Snapshot views">{(["overview", "trust", "inventory", "findings", "topology"] as const).map((item) =>
      <Link key={item} aria-current={view === item || (view === "device" && item === "inventory") ? "page" : undefined}
        to={`/snapshots/${id}?view=${item}`}>{titles[item]}</Link>)}</nav>
    {failure?.key === key ? <section className="panel projection-error" role="alert"><h2>View unavailable</h2><p>{failure.message}</p>
      <button className="btn" onClick={() => setRetry((n) => n + 1)}>Retry view</button></section>
      : !document ? <section className="panel" role="status">Loading {titles[view].toLowerCase()}…</section>
        : <EvidenceProvider key={`${key}:${document.identity.sha256}`} identity={document.identity} limitations={document.limitations}>
          <div className="projection-content">
            {document.view === "overview" && <Overview document={document} />}
            {document.view === "trust" && <Trust document={document} />}
            {document.view === "inventory" && <Inventory document={document} />}
            {document.view === "findings" && <Findings document={document} />}
            {document.view === "topology" && <TopologyPaths document={document} reload={() => setRetry((n) => n + 1)} />}
            {document.view === "device" && <Device document={document} />}
          </div>
          <details className="panel projection-source"><summary>Snapshot and engine identity</summary>
            <p>Snapshot {document.identity.snapshot_id} · {document.identity.bytes} bytes · {document.identity.digest_form}</p>
            <code>{document.identity.sha256}</code><FactGrid facts={{ script: document.engine.script_version,
              schema: document.engine.snapshot_schema, generated: document.engine.generated_at, collected: document.engine.collected_at }} />
            <p>Code schema: {document.engine.code_schema_version} · source schema supported: {document.engine.snapshot_schema_supported === null ? "Not published" : document.engine.snapshot_schema_supported ? "Yes" : "No"}</p>
          </details>
        </EvidenceProvider>}
  </main>;
}
