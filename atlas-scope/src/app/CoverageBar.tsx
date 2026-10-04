/**
 * CoverageBar.tsx — what was collected, what was not, and what could not have been.
 *
 * THREE STATES, NEVER TWO. A two-state coverage chart ("23 of 26") forces every member that was
 * never reachable into the same bucket as every member we simply failed to collect, and the
 * reader cannot tell a collection gap from a structural one. So every row reports:
 *
 *   observed         we hold the evidence for this member
 *   not observed     the member could have carried this evidence and we did not collect it
 *   not applicable   the collector never reached the device at all, so this evidence could not
 *                    exist for it — and that gap is already counted once, in the first row
 *
 * The "not applicable" rule is deliberately narrow and mechanical (`Device.collected === false`).
 * A generous n/a rule is how a coverage chart becomes a marketing chart: every inconvenient gap
 * gets reclassified as "does not apply" and the bar goes green. n/a here never means "fine", and
 * it is never used to explain away a device the collector could have reached.
 *
 * DERIVED AND STATED FIGURES ARE BOTH SHOWN WHEN THEY DISAGREE. Each row counts the real records
 * itself and compares the total against the snapshot's own `coverage.*` field. Silently trusting
 * either one would invent a fact exactly where the two sources of truth disagree, which is the
 * most load-bearing place a fabrication could land (design brief T9).
 *
 * Nothing here is hardcoded: every number is read from `fabric` at render time (SSOT, Law 1).
 */
import { useMemo, type ReactElement } from "react";
import { aclUndecidability, undecidableAclSentence } from "../core/acl-coverage";
import { bandScored } from "../core/band-qualification";
import { COLLECTION_REPORT, collectionCensus, type CollectionCensus } from "../core/collection";
import { fabric, hasRib } from "../core/data";
import { own } from "../core/own";
import { missingInventoryFields } from "../core/claims";
import { ribCountQualifier, ribHostsShownIncomplete } from "../forwarding/rib-completeness";
import type { Cite, Device } from "../core/types";
import { Cite as CiteLink } from "../ui/primitives";
import "./chrome.css";

export type CoverageState = "observed" | "absent" | "notApplicable";

export interface CoverageRow {
  id: string;
  /** What evidence this row is about, as a reader would name it. */
  label: string;
  /** What "observed" means here, in one clause. Rendered, not just documented. */
  meaning: string;
  unit: "devices" | "links";
  observed: number;
  absent: number;
  notApplicable: number;
  total: number;
  /** The snapshot's own figure for the same question, when it publishes one. */
  stated: number | null;
  /** Names the field `stated` came from, so a disagreement can be chased to its source. */
  statedField: string | null;
  cite: Cite;
}

/**
 * True when our own count of the records and the snapshot's published figure agree. Exported and
 * tested directly: the disagreement path is the one that matters and it cannot be exercised by
 * this snapshot, which agrees everywhere. An untested branch that only runs when the data is
 * surprising is not a check — it is a hope that the data will never be surprising.
 */
export const agrees = (row: Pick<CoverageRow, "observed" | "stated">): boolean =>
  row.stated === null || row.stated === row.observed;

/**
 * Build the rows from the compiled fabric.
 *
 * Arithmetic invariant, and the reason the three counts are derived from ONE predicate each:
 * `observed + absent + notApplicable === total`, always. A device the collector never reached
 * that nonetheless carries the evidence counts as observed rather than as not-applicable, so a
 * surprising record widens the observed count instead of vanishing from the table.
 */
export function coverageRows(): CoverageRow[] {
  const devices = fabric.devices;
  const total = devices.length;
  const c = fabric.coverage;
  const aclHosts = new Set(c.aclHosts);

  const deviceRow = (
    id: string,
    label: string,
    meaning: string,
    has: (d: Device) => boolean,
    stated: number | null,
    statedField: string | null,
  ): CoverageRow => {
    let observed = 0;
    let absent = 0;
    let notApplicable = 0;
    for (const d of devices) {
      if (has(d)) observed++;
      else if (d.collected) absent++;
      else notApplicable++;
    }
    return {
      id,
      label,
      meaning,
      unit: "devices",
      observed,
      absent,
      notApplicable,
      total,
      stated,
      statedField,
      cite: c.cite,
    };
  };

  /* The ENGINE's collection authority (core/collection.ts), never record presence. This row counted
     `d.collected` — a device record — and so listed a host whose capture folder was empty under "Collector
     reached the device" (2026-10 refuter, B7). It now counts the hosts the engine's collection_completeness
     calls complete and compares that with the engine's own summary.complete; partial and not-collected
     hosts are named in the Collection note below the table. With no usable block nothing is counted as
     collected: the row says the basis is not stated. */
  const census = collectionCensus();
  const complete = census.hosts.complete.length;

  return [
    {
      id: "collected",
      label: "Collected completely",
      meaning:
        census.stated === null
          ? `not stated — ${census.unstated ?? `the snapshot carries no ${COLLECTION_REPORT}`}; a device record is not counted as a collection`
          : `every essential command returned usable output, as the engine's ${COLLECTION_REPORT} states it`,
      unit: "devices",
      observed: complete,
      /* The first row is the one place n/a is structurally zero: a device that was not collected is
         exactly what this row measures, so routing it into n/a would make the row measure
         nothing. Every later row defers its uncollected members to the collector's answer. */
      absent: total - complete,
      notApplicable: 0,
      total,
      stated: census.stated === null ? null : census.stated.complete,
      statedField: census.stated === null ? null : "collection_completeness.summary.complete",
      cite: census.stated === null ? c.cite : census.stated.cite,
    },
    /* The flag says a record was RETURNED; it does not say the record is complete. This row used to
       read "a model, serial and software record exists" over `d.inventoried`, and counted core2 —
       whose software version is empty in the source snapshot — as observed (critic B7). The words
       now say what the flag means, and the record's CONTENT is counted in its own row below, over
       every field the lifecycle and advisory questions depend on. */
    deviceRow(
      "inventory",
      "Inventory record",
      "an inventory record was returned (its fields are counted in the next row)",
      (d) => d.inventoried,
      c.devicesInventoried,
      "coverage.devicesInventoried",
    ),
    deviceRow(
      "inventory-fields",
      "Model, serial and software version",
      "all three were returned — lifecycle and advisory questions depend on them",
      (d) => missingInventoryFields(d).length === 0,
      null,
      null,
    ),
    deviceRow(
      "interfaces",
      "Interface table",
      "the interface list was collected",
      /* The host's OWN table (core/own.ts): `fabric.interfaces[host]` counted a host named "constructor", which has
         none, as collected — the Object function has a length. */
      (d) => (own(fabric.interfaces, d.host)?.length ?? 0) > 0,
      c.hostsWithInterfaces,
      "coverage.hostsWithInterfaces",
    ),
    deviceRow(
      "rib",
      "Routing table (RIB)",
      ribHostsShownIncomplete().length === 0
        ? "a routing table was collected, so forwarding can be modelled on this host"
        : `a routing table was collected, so forwarding can be modelled on this host — the snapshot shows ${ribHostsShownIncomplete().join(" and ")}'s ${ribHostsShownIncomplete().length === 1 ? "table" : "tables"} to be incomplete ${ribCountQualifier()}`,
      (d) => hasRib(d.host),
      c.hostsWithRoutes,
      "coverage.hostsWithRoutes",
    ),
    deviceRow(
      "acl",
      "Access lists",
      "at least one access list was collected from this host",
      (d) => aclHosts.has(d.host),
      c.hostsWithAcls,
      "coverage.hostsWithAcls",
    ),
    deviceRow(
      "band",
      "Health score and band",
      "the engine scored this device and placed it in a band",
      /* Scored into one of the five bands: not the engine's "Insufficient Data" (it says it could not score), and not
         a band Atlas Scope does not recognise. */
      bandScored,
      null,
      null,
    ),
    (() => {
      const links = fabric.links;
      const observed = links.filter((l) => l.isBridge !== null).length;
      return {
        id: "centrality",
        label: "Link centrality",
        meaning: "betweenness was computed, so the link's loss can be reasoned about",
        unit: "links" as const,
        observed,
        absent: links.length - observed,
        /* Centrality is derived from the topology, and the topology names every link — including
           the ones touching a device the collector never reached. So there is no member this
           question cannot apply to, and the honest n/a here is zero rather than a convenient
           reclassification of the nineteen links nobody computed. */
        notApplicable: 0,
        total: links.length,
        stated: fabric.coverage.linksWithCentrality,
        statedField: "coverage.linksWithCentrality",
        cite: c.cite,
      };
    })(),
  ];
}

const pct = (n: number, of: number): number => (of <= 0 ? 0 : (n / of) * 100);

/**
 * Every device's collection state, by name, as the engine states it: complete, partial (answered,
 * incomplete — with what is missing), not collected (no usable output), on the cable map only. A partial
 * host is never folded into the complete count, and a not-collected host is never described as having
 * answered (acceptance B7). With no usable collection_completeness the note says the basis is not stated.
 */
function CollectionNote({ census }: { census: CollectionCensus }): ReactElement {
  const named = (hosts: readonly string[]): string => (hosts.length === 0 ? "" : `: ${hosts.join(", ")}`);
  const withMissing = (h: string): string => {
    const missing = census.blindSpots.get(h)?.missing ?? [];
    return missing.length === 0 ? h : `${h} (missing ${missing.join(", ")})`;
  };
  const topo = census.hosts["topology only"];
  return (
    <div className="cov__note" data-tone={census.stated === null ? "indeterminate" : undefined}>
      <dt>Collection</dt>
      <dd>
        {census.stated === null ? (
          `Not stated: ${census.unstated ?? `the snapshot carries no ${COLLECTION_REPORT}`}. ${census.hosts["not stated"].length} of ${census.total} devices have a device record; the engine writes one for every inventoried device whether or not the collector reached it, so no device is counted as collected here.`
        ) : (
          <>
            {`Read from the engine's ${COLLECTION_REPORT} (${census.stated.inventory} inventoried).`}
            {census.disagreement === null ? null : <span data-disagreement="true">{` ${census.disagreement}`}</span>}
          </>
        )}
        <ul className="cov__members">
          {census.stated === null ? null : (
            <li data-collection="complete">{`${census.hosts.complete.length} complete — every essential command returned usable output`}</li>
          )}
          {census.hosts.partial.length === 0 ? null : (
            <li data-collection="partial">
              {`${census.hosts.partial.length} partial — answered the collector, but incompletely, so not counted as collected: ${census.hosts.partial.map(withMissing).join("; ")}`}
            </li>
          )}
          {census.hosts["not collected"].length === 0 ? null : (
            <li data-collection="not collected">
              {`${census.hosts["not collected"].length} not collected — inventoried, but no usable output came back (unreachable, auth-failed or empty captures)${named(census.hosts["not collected"])}`}
            </li>
          )}
          {topo.length === 0 ? null : (
            <li data-collection="topology only">{`${topo.length} on the cable map only — never a collector target${named(topo)}`}</li>
          )}
        </ul>
      </dd>
    </div>
  );
}

export interface CoverageBarProps {
  /** Row to mark as the one the reader arrived for, e.g. from the status bar's `RIBs 2/26`. */
  highlight?: string | null;
  /** Wired by the shell when an inspector exists to open; without it the citation renders inert. */
  onOpenCite?: (cite: Cite) => void;
  className?: string;
}

export function CoverageBar({
  highlight = null,
  onOpenCite,
  className,
}: CoverageBarProps): ReactElement {
  const rows = useMemo(() => coverageRows(), []);
  const census = collectionCensus();
  const c = fabric.coverage;
  /* NOT `c.aclLinesUnevaluable`. That field counts only the producer's own flag; the set that
     bounds a rendered verdict is the union of three sets, and on this snapshot the producer's
     flag names a line the engine decides while missing two it refuses. See core/acl-coverage.ts. */
  const undecidable = useMemo(() => aclUndecidability(), []);

  return (
    <div className={className ? `cov ${className}` : "cov"}>
      <table className="cov__table">
        <caption className="visually-hidden">
          Collection coverage by evidence category. Every category reports three states: observed,
          not observed, and not applicable. Not applicable means the collector never reached the
          device, so the evidence could not exist for it.
        </caption>
        <thead>
          <tr>
            <th scope="col" className="cov__c-label">
              Evidence
            </th>
            <th scope="col" className="cov__c-num">
              Observed
            </th>
            <th scope="col" className="cov__c-num">
              Not observed
            </th>
            <th scope="col" className="cov__c-num">
              Not applicable
            </th>
            <th scope="col" className="cov__c-num">
              Of
            </th>
            <th scope="col" className="cov__c-bar">
              Share
            </th>
            <th scope="col" className="cov__c-cite">
              Source
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.flatMap((r) => [
            (
              <tr
                key={r.id}
                data-highlight={r.id === highlight ? "true" : undefined}
                aria-current={r.id === highlight ? "true" : undefined}
              >
                <th scope="row" className="cov__c-label">
                  <span className="cov__label">{r.label}</span>
                  <span className="cov__meaning">{r.meaning}</span>
                </th>
                <td className="cov__c-num" data-state="observed">
                  {r.observed}
                </td>
                <td className="cov__c-num" data-state="absent">
                  {r.absent}
                </td>
                <td className="cov__c-num" data-state="na">
                  {r.notApplicable}
                </td>
                <td className="cov__c-num cov__c-of">
                  {r.total} {r.unit}
                </td>
                <td className="cov__c-bar">
                  {/* The numbers above ARE the accessible data; announcing the same proportion a
                      second time makes the table unusable with a screen reader. The three
                      segments differ in fill, texture and height, so the picture is not carried
                      by colour alone either. */}
                  <span className="cov__stack" aria-hidden="true">
                    <span
                      className="cov__seg"
                      data-state="observed"
                      style={{ inlineSize: `${pct(r.observed, r.total)}%` }}
                    />
                    <span
                      className="cov__seg"
                      data-state="absent"
                      style={{ inlineSize: `${pct(r.absent, r.total)}%` }}
                    />
                    <span
                      className="cov__seg"
                      data-state="na"
                      style={{ inlineSize: `${pct(r.notApplicable, r.total)}%` }}
                    />
                  </span>
                </td>
                <td className="cov__c-cite">
                  {onOpenCite ? (
                    <CiteLink cite={r.cite} onOpen={onOpenCite} label="source" />
                  ) : (
                    <code className="cov__cite" title={r.cite}>
                      {r.cite}
                    </code>
                  )}
                </td>
              </tr>
            ),
            /* A disagreement gets its own full-width row rather than an extra cell: a row with
               one more cell than the header describes is a table whose columns have stopped
               meaning anything, which is a poor way to report that two numbers disagree. */
            agrees(r) ? null : (
              <tr key={`${r.id}-disagreement`} className="cov__disagreement">
                <td colSpan={7}>
                  {`DISAGREEMENT: we counted ${r.observed} ${r.unit} with ${r.label.toLowerCase()}; the snapshot's own ${r.statedField ?? "figure"} states ${r.stated ?? 0}. Both are shown. Neither is suppressed. Cited at ${r.cite}.`}
                </td>
              </tr>
            ),
          ])}
        </tbody>
      </table>

      <dl className="cov__notes">
        <CollectionNote census={census} />
        <div className="cov__note">
          <dt>Not applicable</dt>
          <dd>
            the collector never reached the device, so this evidence could not exist for it. That
            gap is counted once, in the first row. It is not a statement that the device is
            without problems.
          </dd>
        </div>
        <div className="cov__note">
          <dt>Forwarding scope</dt>
          <dd>
            {`modelled on ${c.routableHosts.join(", ") || "no host"} — ${c.routableHosts.length} of ${fabric.devices.length} hosts with a collected routing table. Hops through the other ${fabric.devices.length - c.routableHosts.length} are reported as unmodeled.`}
          </dd>
        </div>
        <div className="cov__note" data-tone="indeterminate">
          <dt>Access-list lines</dt>
          <dd>
            {`Collected across ${c.hostsWithAcls} host${c.hostsWithAcls === 1 ? "" : "s"}. ${undecidableAclSentence(undecidable)}`}
            {undecidable.count === 0 ? null : (
              <ul className="cov__members">
                {undecidable.members.map((m) => (
                  <li key={m.cite}>
                    <code>{m.label}</code> {m.raw ?? "(line text not observed)"} —{" "}
                    {m.reasons.join("; ")}
                  </li>
                ))}
              </ul>
            )}
          </dd>
        </div>
      </dl>
    </div>
  );
}
