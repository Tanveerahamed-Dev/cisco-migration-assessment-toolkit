/**
 * collection.ts — the ONE owner of the collected-host figures (acceptance B7).
 *
 * "How many hosts were collected" is the engine's statement, not this application's inference. The engine's
 * authority is `collection_completeness` (cisco_toolkit/analyze.py `compute_collection_completeness`), whose
 * `summary.complete` is the canonical `n_collected` (cisco_toolkit/ssot.py CANONICAL_FACTS; docs/ssot.md). The
 * compiler reads it into each device's `collection` and into `fabric.collection_completeness`
 * (tools/lib/compile-model.mjs `readCollectionCompleteness`).
 *
 * WHAT WAS WRONG (2026-10 re-grade refuter). The status bar, the coverage disclosure and the overlay coverage line
 * counted device RECORDS as collections. The engine writes a record for every inventoried host, an empty capture
 * folder included, so with one dead host and one show-version-only host the bar read "25/28 collected" where the
 * engine says 23 complete, 1 partial and 1 not collected. Every surface that states the figure now reads it here:
 *   - the headline is the engine's `summary.complete`, out of every device the fabric draws;
 *   - a partial host is named as answered but incomplete, and never folded into the complete count;
 *   - a not-collected host is named as returning no usable output, and never as having answered;
 *   - a snapshot with no usable block states that the basis is not stated — a record is not promoted to a collection.
 * Where the per-host states this application derived disagree with the engine's summary, both are said.
 *
 * Read once: `fabric` is a static import, so there is nothing for the figures to go stale against.
 */
import { fabric } from "./data";
import { listPhrase } from "./phrases";
import type { CollectionBlindSpot, CollectionCompleteness, CollectionState, Device } from "./types";

export interface CollectionCensus {
  /** The engine's summary, or null when the snapshot states no usable collection completeness. */
  stated: CollectionCompleteness["summary"] | null;
  /** Why the snapshot states none, or null when it does. */
  unstated: string | null;
  /** Every device the fabric draws: the denominator every coverage figure on the line shares. */
  total: number;
  /** The devices in each state, by name. */
  hosts: Readonly<Record<CollectionState, readonly string[]>>;
  /** The engine's blind-spot rows, by host (what each partial / not-collected host is missing). */
  blindSpots: ReadonlyMap<string, CollectionBlindSpot>;
  /** A sentence naming each figure where the per-host states disagree with the engine's summary, or null. */
  disagreement: string | null;
}

/**
 * How rendered prose names the engine's block. Never its snapshot key: since the compiler reads that section, the key
 * is a citation the Inspector resolves (panels/cited-text.tsx), and a citation printed as prose — or in a tooltip,
 * where no control can hold it — is an inert citation (acceptance B6). The surfaces that cite the record do so with
 * a working control (the coverage disclosure's source, the device pane's banner).
 */
export const COLLECTION_REPORT = "collection-completeness report";

const STATES: readonly CollectionState[] = ["complete", "partial", "not collected", "topology only", "not stated"];

let censusOnce: CollectionCensus | null = null;

/** The collection census of the one dataset this page shows. */
export function collectionCensus(): CollectionCensus {
  if (censusOnce !== null) return censusOnce;
  const devices: readonly Device[] = fabric.devices;
  const hosts = Object.fromEntries(STATES.map((s) => [s, devices.filter((d) => d.collection === s).map((d) => d.host).sort()])) as Record<
    CollectionState,
    string[]
  >;
  const cc = fabric.collection_completeness ?? null;
  const stated = cc === null ? null : cc.summary;
  let disagreement: string | null = null;
  if (stated !== null) {
    const pairs: [string, number, number][] = [
      ["summary.complete", stated.complete, hosts.complete.length],
      ["summary.partial", stated.partial, hosts.partial.length],
      ["summary.not_collected", stated.notCollected, hosts["not collected"].length],
      ["summary.inventory", stated.inventory, hosts.complete.length + hosts.partial.length + hosts["not collected"].length],
    ];
    const off = pairs.filter(([, s, d]) => s !== d);
    if (off.length > 0) {
      disagreement =
        `DISAGREEMENT: the snapshot's own ${COLLECTION_REPORT} states ${off.map(([f, s]) => `${f} ${s}`).join(", ")}; ` +
        `the per-host states read from its blind-spot list and the device records give ${off.map(([f, , d]) => `${f.replace("summary.", "")} ${d}`).join(", ")}. ` +
        "Both are shown. Neither is suppressed.";
    }
  }
  censusOnce = {
    stated,
    unstated: fabric.coverage.collectionUnstated ?? (cc === null ? `the snapshot carries no ${COLLECTION_REPORT}` : null),
    total: devices.length,
    hosts,
    blindSpots: new Map((cc?.devices ?? []).map((b) => [b.host, b])),
    disagreement,
  };
  return censusOnce;
}

const n = (k: number, one: string, many: string): string => `${k} ${k === 1 ? one : many}`;

/** "partsw (missing interface status, switchport)" — a blind spot with what the engine says it lacks. */
function withMissing(c: CollectionCensus, host: string): string {
  const missing = c.blindSpots.get(host)?.missing ?? [];
  return missing.length === 0 ? host : `${host} (missing ${listPhrase(missing, "nothing named")})`;
}

/** The qualifier the headline carries when the engine names hosts it did not collect completely, or "". */
export function collectionQualifier(c: CollectionCensus = collectionCensus()): string {
  if (c.stated === null) return "";
  const parts = [
    c.stated.partial > 0 ? `${c.stated.partial} partial` : "",
    c.stated.notCollected > 0 ? `${c.stated.notCollected} not collected` : "",
  ].filter((p) => p !== "");
  return parts.length === 0 ? "" : `(${parts.join(", ")})`;
}

/**
 * The collected-host figure as the permanent line states it: "23/28 collected", qualified "(1 partial, 1 not
 * collected)" when the engine names such hosts, or "collection not stated" when the snapshot does not report it.
 */
export function collectedFigure(c: CollectionCensus = collectionCensus()): string {
  if (c.stated === null) return "collection not stated";
  const q = collectionQualifier(c);
  return `${c.stated.complete}/${c.total} collected${q === "" ? "" : ` ${q}`}`;
}

/** The figure in words, naming every host that is not complete and what it lacks: the collected control's tooltip. */
export function collectedDescription(c: CollectionCensus = collectionCensus()): string {
  const topo = c.hosts["topology only"].length;
  const topoSentence =
    topo === 0 ? "" : ` ${n(topo, "more device is", "more devices are")} on the cable map only (${listPhrase(c.hosts["topology only"])}), never a collector target.`;
  if (c.stated === null) {
    const records = c.hosts["not stated"].length;
    return (
      `How many devices were collected is not stated: the snapshot carries no usable ${COLLECTION_REPORT}` +
      `${c.unstated === null ? "" : ` (${c.unstated})`}. ` +
      `${records} of ${c.total} devices have a device record, but the engine writes one for every inventoried device whether or not ` +
      `the collector reached it, so a record is not counted as a collection.${topoSentence}`
    );
  }
  const partial = c.hosts.partial;
  const dead = c.hosts["not collected"];
  return (
    `${c.stated.complete} of ${c.total} devices were collected completely — the engine's own ${COLLECTION_REPORT} ` +
    `(summary.complete, the canonical collected count; ${c.stated.inventory} inventoried).` +
    (partial.length === 0
      ? ""
      : ` ${n(partial.length, "device", "devices")} answered the collector but incompletely (partial): ${listPhrase(partial.map((h) => withMissing(c, h)))}.`) +
    (dead.length === 0
      ? ""
      : ` ${n(dead.length, "inventoried device", "inventoried devices")} returned no usable output and ${dead.length === 1 ? "is" : "are"} not collected: ${listPhrase(dead)}.`) +
    topoSentence +
    (c.disagreement === null ? "" : ` ${c.disagreement}`)
  );
}

/**
 * A device's collection state in a few words, for the per-device surfaces (the palette, the fabric's accessible tree,
 * the query's host values). Every state says what it is: a partial host is never just "collected", and a host the
 * engine calls not collected is never "topology only" — it was a collector target that returned nothing usable.
 */
export const COLLECTION_WORDS: Readonly<Record<CollectionState, string>> = {
  complete: "collected",
  partial: "partially collected",
  "not collected": "not collected — no usable output came back",
  "topology only": "topology only — never collected",
  "not stated": "collection not stated",
};

/** A device's collection state as one announced sentence (the fabric's selection announcement). */
export function collectionSentence(d: Device): string {
  switch (d.collection) {
    case "complete":
      return "Collected.";
    case "partial": {
      const missing = collectionCensus().blindSpots.get(d.host)?.missing ?? [];
      return `Partially collected: it answered the collector, but ${missing.length === 0 ? "some essential evidence is missing" : `${listPhrase(missing, "nothing named")} returned no usable output`}.`;
    }
    case "not collected":
      return "Not collected: inventoried, but no usable output came back.";
    case "topology only":
      return "Topology only: this device was never collected.";
    case "not stated":
      return "Collection not stated by the snapshot; a device record is present.";
  }
}
