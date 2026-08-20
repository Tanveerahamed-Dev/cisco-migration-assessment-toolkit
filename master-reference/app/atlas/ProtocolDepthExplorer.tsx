/* oxlint-disable nextjs/no-html-link-for-pages -- stable full-document links preserve the connect-src 'none' boundary. */
import type {
  Capability,
  Gap,
  OwnerRef,
  ProtocolDepthFamily,
  ProtocolDepthModel,
  ProtocolDepthState,
} from "./types";
import { StateMark } from "./Shell";
import styles from "./ProtocolDepthExplorer.module.css";

type ProtocolDepthExplorerProps = {
  model: ProtocolDepthModel;
  protocolCapabilities: Capability[];
  gaps: Gap[];
  owners: OwnerRef[];
  selectedFamily?: string;
  selectionError?: string;
};

const stateOrder: ProtocolDepthState[] = ["covered", "partial", "missing"];

function sourceHref(path: string): string {
  return `/source/${path.split("/").map(encodeURIComponent).join("/")}`;
}

function selectedHref(familyId: string, stageId?: string): string {
  const anchor = stageId ? `#${familyId}-${stageId}` : "#protocol-family-detail";
  return `/protocols?family=${encodeURIComponent(familyId)}${anchor}`;
}

function capabilityHref(capabilityId: string): string {
  return `/capabilities?domain=domain.protocols&q=${encodeURIComponent(capabilityId)}#${capabilityId}`;
}

function Status({ state }: { state: ProtocolDepthState }) {
  return (
    <span className={`${styles.status} ${styles[state]}`}>
      <span aria-hidden="true" />
      {state}
    </span>
  );
}

function stageCount(model: ProtocolDepthModel, state: ProtocolDepthState): number {
  return model.families.reduce(
    (total, family) =>
      total + Object.values(family.cells).filter((cell) => cell.state === state).length,
    0,
  );
}

function FamilyProfile({
  family,
  model,
  capabilities,
  gaps,
  owners,
}: {
  family: ProtocolDepthFamily;
  model: ProtocolDepthModel;
  capabilities: Map<string, Capability>;
  gaps: Map<string, Gap>;
  owners: Map<string, OwnerRef>;
}) {
  const capability = capabilities.get(family.capability_ref);
  const witnessById = new Map(model.witnesses.map((witness) => [witness.id, witness]));

  return (
    <section
      aria-labelledby="protocol-family-title"
      className={styles.dossier}
      data-selected-protocol={family.id}
      id="protocol-family-detail"
    >
      <header className={styles.profileHeader}>
        <div>
          <p>Selected health family · <code>{family.health_label}</code></p>
          <h2 id="protocol-family-title">{family.label}</h2>
          <code>{family.id}</code>
        </div>
        <div className={styles.profileState}>
          <span>Catalog capability</span>
          <StateMark state={capability?.state ?? "unknown"} />
          <a href={capabilityHref(family.capability_ref)}>{family.capability_ref}</a>
        </div>
      </header>

      <div className={styles.profileGrid}>
        <article>
          <span>Current bounded scope</span>
          <p>{capability?.current_scope ?? "Capability record unavailable; no substitute scope inferred."}</p>
        </article>
        <article>
          <span>Assessable only when</span>
          <p>{family.assessable_when}</p>
        </article>
        <article>
          <span>Evidence inputs</span>
          <ul className={styles.commandList}>
            {family.evidence_inputs.map((input) => (
              <li key={`${input.command}:${input.platforms.join(",")}`}>
                <small>{input.platforms.join(" / ")}</small>
                <code>{input.command}</code>
              </li>
            ))}
          </ul>
        </article>
        <article>
          <span>Joined abnormal-state advice</span>
          {family.advice_states.length ? (
            <ul className={styles.commandList}>
              {family.advice_states.map((state) => <li key={state}><code>{state}</code></li>)}
            </ul>
          ) : (
            <p className={styles.emptyFact}>No abnormal-state doctrine is claimed.</p>
          )}
        </article>
        <article>
          <span>Validation boundary</span>
          <p>{family.validation_scope}</p>
        </article>
        <article>
          <span>Known limitations</span>
          <ul>{family.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul>
        </article>
      </div>

      <div className={styles.stageGrid}>
        {model.stages.map((stage) => {
          const cell = family.cells[stage.id];
          const witnesses = cell.witness_refs.map((id) => witnessById.get(id)).filter(Boolean);
          return (
            <article
              className={styles.stageCard}
              data-protocol-stage-detail={`${family.id}:${stage.id}`}
              id={`${family.id}-${stage.id}`}
              key={stage.id}
            >
              <header>
                <div><span>{String(stage.order).padStart(2, "0")}</span><h3>{stage.label}</h3></div>
                <Status state={cell.state} />
              </header>
              <p className={styles.question}>{stage.question}</p>
              <dl>
                <div><dt>Prerequisite</dt><dd>{cell.prerequisite}</dd></div>
                <div><dt>Boundary</dt><dd>{cell.boundary}</dd></div>
                <div><dt>Does not prove</dt><dd>{stage.non_proof}</dd></div>
              </dl>
              {witnesses.length ? (
                <div className={styles.witnesses}>
                  <span>Direct witnesses</span>
                  {witnesses.map((witness) => witness ? (
                    <div className={styles.witness} key={witness.id}>
                      <a href={sourceHref(witness.path)}>
                        <strong>{witness.path}</strong>
                        <small>{witness.symbols.join(" · ")}</small>
                      </a>
                      <p>{witness.proves}</p>
                      <div className={styles.testRefs}>
                        {witness.test_refs.map((testRef) => (
                          <a href={sourceHref(testRef)} key={testRef}>{testRef}</a>
                        ))}
                      </div>
                    </div>
                  ) : null)}
                </div>
              ) : (
                <p className={styles.noWitness}>No implementation witness is claimed for this stage.</p>
              )}
            </article>
          );
        })}
      </div>

      <footer className={styles.profileFooter}>
        <div>
          <span>Exact-tree owners</span>
          <div className={styles.ownerList}>
            {(capability?.owner_refs ?? []).map((ownerId) => {
              const owner = owners.get(ownerId);
              return owner ? (
                <a href={sourceHref(owner.path)} key={ownerId}>
                  <code>{ownerId}</code><small>{owner.path}{owner.symbol ? ` · ${owner.symbol}` : ""}</small>
                </a>
              ) : <code key={ownerId}>{ownerId}</code>;
            })}
          </div>
        </div>
        <div>
          <span>Disposition and acceptance</span>
          {family.gap_refs.map((gapId) => {
            const gap = gaps.get(gapId);
            return gap ? (
              <article key={gapId}>
                <a href={`/gaps?q=${encodeURIComponent(gapId)}`}><code>{gapId}</code> · {gap.title}</a>
                <p><strong>Next:</strong> {gap.next_actions[0]}</p>
                <p><strong>Accept with:</strong> {gap.acceptance_evidence.join(" · ")}</p>
              </article>
            ) : <code key={gapId}>{gapId}</code>;
          })}
        </div>
      </footer>
    </section>
  );
}

export function ProtocolDepthExplorer({
  model,
  protocolCapabilities,
  gaps,
  owners,
  selectedFamily,
  selectionError,
}: ProtocolDepthExplorerProps) {
  const selected = model.families.find((family) => family.id === selectedFamily);
  const family = selected ?? model.families[0];
  const invalidSelection = Boolean(selectionError || (selectedFamily && !selected));
  const activeFamilyId = invalidSelection ? undefined : family.id;
  const capabilityMap = new Map(protocolCapabilities.map((capability) => [capability.id, capability]));
  const gapMap = new Map(gaps.map((gap) => [gap.id, gap]));
  const ownerMap = new Map(owners.map((owner) => [owner.id, owner]));
  const matrixCapabilityIds = new Set(model.families.map((item) => item.capability_ref));
  const broaderCatalogCount = protocolCapabilities.filter(
    (capability) => !matrixCapabilityIds.has(capability.id),
  ).length;
  const catalogStates = protocolCapabilities.reduce<Record<string, number>>((counts, capability) => {
    counts[capability.state] = (counts[capability.state] ?? 0) + 1;
    return counts;
  }, { current: 0, partial: 0, missing: 0 });

  return (
    <div className={styles.workspace}>
      <section aria-label="Protocol depth summary" className={styles.metrics}>
        <div><span>Protocol families</span><strong>{model.denominator.family_count}</strong><small>{model.denominator.health_family_count} health + {model.denominator.family_count - model.denominator.health_family_count} receipt-owned</small></div>
        <div><span>Lifecycle stages</span><strong>{model.denominator.stage_count}</strong><small>Lab 03 comparison lens</small></div>
        {stateOrder.map((state) => (
          <div key={state}><span>{state} cells</span><strong>{stageCount(model, state)}</strong><small>of {model.denominator.cell_count}</small></div>
        ))}
      </section>

      <div className={styles.boundaryNotice}>
        <strong>Source coverage, not a field-behavior claim</strong>
        {model.authority} No emitted family row means <em>not assessable from this view</em>, never healthy.
      </div>

      <div className={styles.boundaryNotice} data-runtime-assessability-contract>
        <strong>Runtime assessability contract</strong>
        Assessment artifacts publish one current-run cell for every inventory device × seven health
        families, separating assessed, partial, captured-no-record, empty, error, not-collected, and
        analysis-unavailable states. The receipt never infers protocol presence or health from omission.
      </div>

      <div className={styles.boundaryNotice} data-runtime-stp-consistency-contract>
        <strong>STP consistency cutover contract</strong>
        For a conservatively identified L2/STP subject, assessed or degraded consistency requires a
        validated current-run STP receipt with usable <code>state</code> and
        <code>inconsistent_ports</code> inputs plus exactly one matching, well-formed STP health row.
        Missing or contradictory evidence becomes review or not verified, prevents a readiness pass,
        and keeps the current-baseline workflow on HOLD. <code>blocked_ports</code> is disclosed
        independently as observed or not collected—missing evidence is never rendered as zero blocked—and
        <code>topology_changes</code>/detail is optional. A clean no-subject host is omitted without a
        health or applicability claim. This does not prove configured STP applicability, complete
        VLAN/MST-instance coverage, timers, convergence, interoperability, or cutover authorization.
      </div>

      <div className={styles.boundaryNotice} data-runtime-etherchannel-baseline-contract>
        <strong>Single-snapshot EtherChannel baseline contract</strong>
        EtherChannel rows become assessed—or an exact observed degraded blocker—only with an assessed
        current-run receipt and a well-formed, nonempty configured-subject/member-state projection.
        Review and not-verified rows abstain; matching a degraded baseline is not acceptance, no complete
        configured-bundle or partner denominator is inferred, and projection custody remains embedded_unverified.
      </div>

      <div className={styles.boundaryNotice} data-runtime-routing-baseline-contract>
        <strong>Single-snapshot routing baseline contract</strong>
        OSPF, BGP, and EIGRP rows become assessed—or an exact observed degraded blocker—only with an
        assessed current-run receipt and a well-formed, nonempty observed projection. Review and
        not-verified rows abstain; no expected-peer denominator is inferred by this observed-routing
        receipt, and projection custody remains embedded_unverified. The separate configured BGP gate
        below has a narrower literal-peer denominator.
      </div>

      <div className={styles.boundaryNotice} data-runtime-ipv6-routing-adjacency-contract>
        <strong>IPv6 routing adjacency gate — observed default/global runtime</strong>
        The separately owned <code>ipv6_routing_adjacency_baseline/1</code> receipt reconciles exact
        observed OSPFv3 and IPv6-unicast BGP peer/state rows with three route-summary, OSPFv3, and
        BGPv6 coverage cells per inspected host. Adjacency-row totals come from
        <code>summary.by_status</code>; fleet coverage comes only from
        <code>summary.by_coverage_status</code>, while <code>coverage[]</code> remains
        host-family/input drilldown and can keep a coverage-only host visible. Every degraded,
        review, and not-verified row is a blocker; matching a degraded state is NOT ACCEPTANCE.
        Current-run decisions require process-local source custody. Audit copies are
        <code>embedded_unverified</code>, and a serialized <code>current_run_source_bound</code> claim
        fails closed. Workbook and runbook retain every blocker plus the first 50 assessed rows.
        Explorer initially renders at most 200 blockers plus the first 50 assessed rows, reports exact
        rendered/total/omitted counts, and exports every validated blocker row through a bounded safe
        JSON projection. These surfaces render bounded command/custody and exact observed peer/state, and never render raw
        captures, SHA values, source locators, or paths. This is not a configured or expected-peer
        denominator. Empty or NOT_APPLICABLE evidence is not absence; OSPF process/VRF/network-type,
        BGP policy/VRF/other-AF, route/prefix correctness, RIB/FIB/path selection, convergence,
        freshness, simultaneity, interoperability, and cutover authorization remain unproved. Route
        summary is a point-in-time census and prefix counts are informational.
      </div>

      <div className={styles.boundaryNotice} data-runtime-vtp-safety-contract>
        <strong>VTP safety gate — observed local status</strong>
        The typed <code>vtp_safety_baseline/1</code> owner reconciles one bounded local
        <code>show vtp status</code> subject per host with exact subject-row
        <code>summary.by_status</code> counts and the distinct producer-owned fleet
        <code>summary.by_coverage_status</code> census; <code>coverage[]</code> is reserved for
        bounded per-host detail. A VTP Server configuration revision of 100 or higher is a
        conservative REVIEW heuristic requiring explicit disposition—not proof that an overwrite or
        propagation failure will occur—and matching it is NOT ACCEPTANCE. Current-run decisions require
        process-local source custody; JSON audit copies are <code>embedded_unverified</code> and a
        serialized <code>current_run_source_bound</code> claim is rejected. Operator outputs retain every
        REVIEW and NOT VERIFIED subject plus the first 50 assessed subjects without replacing the separate
        protocol-health and intelligence detail, and render no raw capture, hash, source locator, or path.
        This local observation proves no VLAN-database equality or contents, advertisement/per-VLAN
        propagation, intended version/compatibility, pruning, password/authentication, freshness,
        revision-reset safety, or cutover authorization. NOT_APPLICABLE means no positive local subject was
        identified; it is not proof that VTP is absent from the platform or network.
      </div>

      <div className={styles.boundaryNotice} data-runtime-bgp-configured-peer-contract>
        <strong>Configured BGP peer gate — default/global IPv4 unicast</strong>
        A validated <code>bgp_configured_peer_baseline/1</code> receipt reconciles literal
        configured-active peers with usable summary evidence; a missing or non-Established peer is a
        blocker, while ambiguity or custody loss remains review or not verified. Peer-row counts come
        from <code>summary.by_status</code>; the distinct fleet host-coverage census comes from
        <code>summary.by_coverage_status</code>, with <code>coverage[]</code> reserved for host detail.
        NOT_APPLICABLE means no in-scope literal peer subject was identified; it is not proof that BGP
        is absent or that configuration coverage is complete. This bounded gate keeps BGP partial: it
        excludes VRFs, IPv6, VPNv4/EVPN, peer groups/templates, dynamic peers, policy, routes, best path,
        RPKI, convergence, freshness, interoperability, and cutover authorization.
      </div>

      <div className={styles.boundaryNotice} data-runtime-fhrp-configured-group-contract>
        <strong>Configured FHRP group gate — default/global IPv4</strong>
        A validated <code>fhrp_configured_group_baseline/1</code> receipt reconciles direct-literal
        local HSRP, VRRP, and GLBP groups with usable subtype runtime evidence. A configured-active
        group absent from that evidence is a blocker; ambiguity or custody loss remains review or not
        verified. Across distinct hosts, complete healthy rows are compared only when default/IPv4,
        subtype, normalized interface, group, and equal configured/runtime VIP all match. If two or
        more such exact candidates contain zero or multiple observed leaders, every matching existing
        row becomes a pre-cutover review blocker. This is sequential election-consistency review; it is
        not proof of simultaneous dual leadership or split brain; it does not invent a peer or infer an
        expected peer/member count. Candidate scope may be incomplete; simultaneous verification or
        explicit disposition is required, and Matching the conflicting or unresolved sequential roles
        is NOT ACCEPTANCE. Exactly one observed leader with healthy backups, or a lone candidate,
        remains only bounded local-state evidence. Concrete
        group-row counts come from <code>summary.by_status</code>; the distinct,
        exact three-cells-per-host census comes from <code>summary.by_coverage_status</code>, with
        <code>coverage[]</code> reserved for host × subtype detail. NOT_APPLICABLE means no in-scope
        literal local group subject was identified; it is not proof that FHRP is absent or that
        configuration coverage is complete. This gate excludes VRFs, IPv6,
        templates/inheritance/dynamic constructs, secondary VIPs, expected peer/member count or
        identity, timers, authentication, preemption, tracking behavior, simultaneous election health,
        failover, convergence, freshness, interoperability, and cutover authorization;
        NX-OS configured-group parsing is limited to nested HSRP.
      </div>

      <div className={styles.boundaryNotice} data-runtime-fhrp-redundancy-domain-contract>
        <strong>FHRP redundancy-domain composition contract</strong>
        The authoritative <code>fhrp_redundancy_domain_baseline/1</code> joins the validated
        configured-group receipt to every current normalized SVI member inside the exact observed IPv4
        domain: VLAN, normalized VRF, and observed subnet. Within that domain, candidate identity is the
        concrete protocol, group, and virtual IP. A same-domain SVI with zero positive HSRP/VRRP/GLBP
        participation is <em>review</em>—intended membership is unresolved—not a proven unprotected
        gateway or failure. Missing subtype capture/parser evidence is not verified; a bounded upstream
        local configured/runtime group fault remains degraded. Multiple groups are supported when the
        same members carry the same candidate set; disjoint or subset candidate sets require review.
        Matching unresolved composition is NOT ACCEPTANCE. The receipt is process-current projection
        bound to a canonical normalized-SVI digest and its validated upstream receipt; after JSON
        serialization its custody is <code>embedded_unverified</code>. For this domain owner,
        NOT_APPLICABLE means no subject was identified; it is not proof that FHRP is absent or that
        intended membership is complete. It does not establish off-scan or
        intended member count, simultaneous roles, timers, authentication, tracking, failover behavior,
        convergence, freshness, interoperability, or cutover authorization.
      </div>

      <div className={styles.boundaryNotice} data-runtime-adjacency-change-contract>
        <strong>Before/after adjacency change contract</strong>
        Cutover comparisons preserve baseline-observed OSPF, BGP, and EIGRP peers only when both
        device-family receipt cells are assessed. A parsed healthy-to-unhealthy state is a regression;
        a peer that is no longer observed needs review, and loss of the last peer abstains because zero
        parsed rows cannot distinguish a real empty table from parser non-yield. This is not an
        expected-neighbor denominator, and embedded projection custody remains explicitly unverified.
        The comparator does not yet include the separately owned OSPFv3/BGPv6 receipt; its current-state
        typed blockers still reach the shared current-baseline gate.
      </div>

      <div className={styles.boundaryNotice} data-runtime-current-baseline-gate-contract>
        <strong>Current-baseline cutover gate</strong>
        Before/after change detection and current-state acceptance are separate decisions. An emitted
        degraded baseline is BLOCKED even when it is unchanged; review or not-verified evidence is
        INDETERMINATE, and an absent or invalid validation plan cannot authorize the cutover. The MOP and
        Explorer Waves view consume this global gate, render HOLD for BLOCKED, INDETERMINATE, and
        NOT_ASSESSED, and retain blockers outside a scheduled wave under (unscheduled). Only global CLEAR
        permits scheduling-eligible copy, and even then CLEAR means only that no blocker was emitted in
        reconciled validation scope—it is not configured-neighbor, configured-group, configured-bundle,
        interoperability, or cutover-completeness proof.
      </div>

      <div aria-label="Protocol depth state definitions" className={styles.stateLegend}>
        {stateOrder.map((state) => (
          <article key={state}>
            <Status state={state} />
            <p>{model.state_contract[state]}</p>
          </article>
        ))}
      </div>

      <section aria-labelledby="protocol-matrix-title" className={styles.matrixSection}>
        <header className={styles.sectionHeader}>
          <div><span>01</span><h2 id="protocol-matrix-title">Eight runtime families × eight lifecycle stages</h2></div>
          <p>{model.denominator.scope_rule}</p>
        </header>

        <form action="/protocols#protocol-family-detail" className={styles.familyForm} method="get">
          <label htmlFor="protocol-family">
            <span>Inspect one family</span>
            <select defaultValue={family.id} id="protocol-family" name="family">
              {model.families.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select>
          </label>
          <button type="submit">Open stage dossier</button>
        </form>

        {invalidSelection ? (
          <output className={styles.abstention}>
            <strong>Protocol selection not recognized</strong>
            {selectionError ? (
              <span>{selectionError}</span>
            ) : (
              <span><code>{selectedFamily}</code> is outside the eight-family runtime denominator. No substitute family was inferred. </span>
            )}
            <a href="/protocols">Reset to the complete matrix</a>
          </output>
        ) : null}

        <div className={styles.matrixWrap}>
          <table className={styles.matrix}>
            <caption>Source-bound implementation state for every family and lifecycle stage</caption>
            <thead>
              <tr>
                <th scope="col">Protocol family</th>
                {model.stages.map((stage) => <th scope="col" key={stage.id}>{stage.label}</th>)}
              </tr>
            </thead>
            <tbody>
              {model.families.map((item) => (
                <tr key={item.id}>
                  <th aria-label={`${item.label} health family`} scope="row">
                    <a aria-current={item.id === activeFamilyId ? "true" : undefined} href={selectedHref(item.id)}>
                      <strong>{item.health_label}</strong><small>{item.label}</small>
                    </a>
                  </th>
                  {model.stages.map((stage) => {
                    const cell = item.cells[stage.id];
                    return (
                      <td data-protocol-cell={`${item.id}:${stage.id}`} key={stage.id}>
                        <a
                          aria-label={`${item.label}, ${stage.label}: ${cell.state}. Open detail.`}
                          href={selectedHref(item.id, stage.id)}
                        >
                          <Status state={cell.state} />
                        </a>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className={styles.stageLegend}>
          {model.stages.map((stage) => (
            <article key={stage.id}><span>{String(stage.order).padStart(2, "0")}</span><h3>{stage.label}</h3><p>{stage.question}</p></article>
          ))}
        </div>
      </section>

      {invalidSelection ? null : (
        <FamilyProfile
          capabilities={capabilityMap}
          family={family}
          gaps={gapMap}
          model={model}
          owners={ownerMap}
        />
      )}

      <section className={styles.catalogBoundary}>
        <div>
          <span>02</span>
          <h2>The broader protocol catalog stays visible.</h2>
        </div>
        <p>
          This matrix covers {model.families.length} bounded runtime families: seven shared health
          families plus the separately owned IPv6 Routing receipt. The closed protocol
          catalog has {protocolCapabilities.length} cells, so {broaderCatalogCount} adjacent or
          currently missing protocol cells remain outside this runtime denominator.
        </p>
        <ul>
          {Object.entries(catalogStates).sort().map(([state, count]) => <li key={state}>{state}: {count}</li>)}
        </ul>
        <div className={styles.catalogActions}>
          <a href="/capabilities?domain=domain.protocols">Open all protocol catalog cells</a>
          <a href="/labs?lab=lab.03-protocol-intelligence&step=1">Open Lab 03 boundary walkthrough</a>
        </div>
      </section>
    </div>
  );
}
