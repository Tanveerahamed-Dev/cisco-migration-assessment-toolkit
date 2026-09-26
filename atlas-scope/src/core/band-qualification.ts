/**
 * band-qualification.ts — the ONE owner of how a device's health band is presented.
 *
 * A score is a sum of deductions, and a scoring domain that was never assessed on a device could
 * not deduct. So a FAVOURABLE band on a collected device whose protocols, routing table or ACLs were
 * never collected partly measures the ABSENCE of evidence: podacc1 read "90 Excellent" in the
 * healthy tone beside "Its routing and switching protocols were not assessed here" (2026-09-22
 * auditor, B1). Such a band is presented NEUTRAL with the unassessed domains named. An unfavourable
 * band is left as is, because its deductions were observed.
 *
 * The rule used to live inside DevicePane's Health section only; then in `presentBand` with six
 * surfaces switched to it BY HAND, and the surfaces nobody listed (the command palette row, the query
 * row description, the `is:healthy` filter, the `band:` facet, the queue's band grouping, sort keys…)
 * went on reading the raw band — B1 failed acceptance twice for that one reason. So this module is
 * now the ONLY one that reads `Device.band` at all, and `band-read.guard.test.ts` enforces that with
 * the TypeScript type checker over every authored module: a surface cannot state a band without
 * going through one of the exports below, each of which carries the qualification.
 *
 * THE CEILING. Because an unassessed domain could not deduct, a qualified band is an UPPER BOUND:
 * the device's true band is that band or any band below it. `bandCandidates` states exactly that, and
 * every yes/no question about a band (`bandHealthy`, `bandDegraded`, `bandMatches`) is answered over
 * the candidates — "yes" only when every candidate agrees, "no" only when none does, otherwise
 * "unknown". podacc1's "90 Excellent" therefore answers `is:healthy` with unknown, never yes.
 */
import { fabric, hasRib, protocolsByHost } from "./data";
import { BAND_ORDER, type Band, type Device } from "./types";

/** The tone a band is drawn in when it stands unqualified. */
export type BandTone = "up" | "high" | "critical" | "neutral";

export const BAND_TONE: Readonly<Record<string, BandTone>> = {
  Excellent: "up",
  Good: "up",
  Fair: "high",
  Poor: "high",
  Critical: "critical",
};

/** A band whose unqualified tone is favourable — the only bands the absence of evidence can flatter. */
export const isFavourableBand = (band: string | null | undefined): boolean =>
  typeof band === "string" && BAND_TONE[band] === "up";

/** `interfacesOf`/`physicalByHost` flatten "no records" and "host never collected" into an empty
 *  array. The difference decides whether an empty table means zero or means unknown, so the
 *  presence of the host KEY is read directly rather than the length of what it returns. */
const hasInterfaceRecords = (host: string): boolean =>
  Object.prototype.hasOwnProperty.call(fabric.interfaces, host);

/**
 * The scoring domains with NO evidence on this device, each named with why — read from the per-host
 * coverage owners (protocol_health rows, the collected-RIB set, the collected-ACL set, the interface
 * records), never from a list of host names.
 */
export function unassessedScoringDomains(host: string): string[] {
  const out: string[] = [];
  if ((protocolsByHost.get(host) ?? []).length === 0) out.push("protocol health (not assessed)");
  if (!hasRib(host)) out.push("routing (no RIB collected)");
  if (!fabric.coverage.aclHosts.includes(host)) out.push("ACLs (none collected)");
  if (!hasInterfaceRecords(host)) out.push("interfaces (no records)");
  return out;
}

/** "protocol health (not assessed)" -> "protocol health". */
const domainName = (g: string): string => g.replace(/\s*\(.*$/, "");

/** The mark appended to a qualified band's letter; the legend names it. */
export const PARTIAL_MARK = "*";

export interface BandPresentation {
  /** The band the snapshot publishes, untouched. Read it ONLY inside this module: outside, it is the
   *  raw band laundered through a second name, so `band-read.guard.test.ts` flags reads of it too. */
  band: string | null;
  /** The words a band pill prints: "Excellent", "Excellent (partial)"; "" when no band. */
  label: string;
  /** Unassessed scoring domains (only ever non-empty for a collected device). */
  unassessed: readonly string[];
  /** A favourable band on a device with unassessed domains: drawn neutral, gap named. */
  qualified: boolean;
  /** The tone to draw in. */
  tone: BandTone;
  /** The CSS custom property that colours the band (chassis tint, LED, legend swatch). */
  colorToken: string;
  /** The greyscale channel on the label and legend: E/G/F/P/C, `?` for no band, `E*` qualified. */
  letter: string;
  /** Short words for a list row: "Excellent", "band not observed", or the qualified form. */
  short: string;
  /** One sentence for a live region or a tooltip. */
  sentence: string;
  /** Which legend row counts this device: the band, `${band}${PARTIAL_MARK}`, or "none". */
  legendKey: string;
}

/** Colour token for each band; `null` (no band computed) is indeterminate, never neutral grey. */
const BAND_TOKEN: Readonly<Record<string, string>> = {
  Excellent: "--band-excellent",
  Good: "--band-good",
  Fair: "--band-fair",
  Poor: "--band-poor",
  Critical: "--band-critical",
};
/** The neutral ink a qualified band is drawn in — the same `--text-muted` DevicePane.css uses. */
export const QUALIFIED_BAND_TOKEN = "--text-muted";
export const NO_BAND_TOKEN = "--claim-indeterminate";

export const bandToken = (band: string): string => BAND_TOKEN[band] ?? "--band-critical";

/**
 * The presentation of one device's band. `unassessed` defaults to the snapshot's own coverage
 * records; it is a parameter only so a caller holding a device that is not in the snapshot can
 * state its coverage rather than have it looked up by a host name the snapshot does not know.
 */
export function presentBand(
  device: Pick<Device, "host" | "band" | "collected">,
  unassessed: readonly string[] = device.collected ? unassessedScoringDomains(device.host) : [],
): BandPresentation {
  const band = device.band;
  if (band === null) {
    return {
      band,
      unassessed,
      qualified: false,
      label: "",
      tone: "neutral",
      colorToken: NO_BAND_TOKEN,
      letter: "?",
      short: "band not observed",
      sentence: "Health band not observed.",
      legendKey: "none",
    };
  }
  const qualified = isFavourableBand(band) && unassessed.length > 0;
  if (!qualified) {
    return {
      band,
      unassessed,
      qualified,
      label: band,
      tone: BAND_TONE[band] ?? "neutral",
      colorToken: bandToken(band),
      letter: band.slice(0, 1),
      short: band,
      sentence: `Health band ${band}.`,
      legendKey: band,
    };
  }
  const names = unassessed.map(domainName).join(", ");
  return {
    band,
    unassessed,
    qualified,
    label: `${band} (partial)`,
    tone: "neutral",
    colorToken: QUALIFIED_BAND_TOKEN,
    letter: `${band.slice(0, 1)}${PARTIAL_MARK}`,
    short: `${band}, partial — not assessed: ${names}`,
    sentence: `Health band ${band}, partial: the score does not reflect ${names} — never assessed on ${device.host}, so nothing there could deduct.`,
    legendKey: `${band}${PARTIAL_MARK}`,
  };
}

/* ── everything a surface asks of a band, each answer carrying the qualification ── */

type BandSubject = Pick<Device, "host" | "band" | "collected">;

/** Tri-state, the same vocabulary as the query engine: `unknown` = the evidence to decide is absent. */
export type BandTri = "yes" | "no" | "unknown";

/** Was a band computed for this device at all? (Presence only — says nothing about its quality.) */
export const bandObserved = (device: Pick<Device, "band">): boolean => device.band !== null;

/** The suffix a qualified band's key carries in query values, grouping keys and sort order. A word,
 *  not PARTIAL_MARK: `*` is the query language's wildcard. */
export const PARTIAL_KEY_SUFFIX = "-partial";

/** Every presented band key, best first: each favourable band is followed by its qualified form. */
export const BAND_KEY_ORDER: readonly string[] = BAND_ORDER.flatMap((b) =>
  isFavourableBand(b) ? [b, `${b}${PARTIAL_KEY_SUFFIX}`] : [b],
);

/** The key a device's band is filed, grouped, faceted and counted under: "Excellent",
 *  "Excellent-partial", or null when no band was computed. */
export function bandKey(device: BandSubject): string | null {
  const band = device.band;
  if (band === null) return null;
  return presentBand(device).qualified ? `${band}${PARTIAL_KEY_SUFFIX}` : band;
}

/** Human words for a band key: "Excellent-partial" -> "Excellent (partial)". */
export const bandKeyLabel = (key: string): string =>
  key.endsWith(PARTIAL_KEY_SUFFIX) ? `${key.slice(0, -PARTIAL_KEY_SUFFIX.length)} (partial)` : key;

/** A one-line description of a band key for a vocabulary list, or null for a plain band. */
export const bandKeyDetail = (key: string): string | null =>
  key.endsWith(PARTIAL_KEY_SUFFIX)
    ? "favourable band, but some scoring domains were never assessed, so it is an upper bound"
    : null;

/** Sort rank (0 = best) that keeps the qualification: a qualified band sorts just after its plain
 *  form, never level with it. null = no band. */
export function bandRank(device: BandSubject): number | null {
  const k = bandKey(device);
  return k === null ? null : BAND_KEY_ORDER.indexOf(k);
}

/**
 * The bands this device could truly be in. null = no band observed (nothing is known). A plain band
 * is exactly itself; a qualified band is a ceiling, so it and every band below it.
 */
export function bandCandidates(device: BandSubject): readonly Band[] | null {
  const band = device.band;
  if (band === null) return null;
  if (!presentBand(device).qualified) return [band];
  return BAND_ORDER.slice(BAND_ORDER.indexOf(band));
}

/** Answer a yes/no question over the candidates: yes iff all agree, no iff none does. */
function overCandidates(device: BandSubject, test: (b: Band) => boolean): BandTri {
  const c = bandCandidates(device);
  if (c === null) return "unknown";
  const hits = c.filter(test).length;
  return hits === c.length ? "yes" : hits === 0 ? "no" : "unknown";
}

/** `is:healthy`: scored into Excellent or Good. A qualified favourable band is NEVER a bare yes. */
export const bandHealthy = (device: BandSubject): BandTri =>
  overCandidates(device, (b) => b === "Excellent" || b === "Good");

/** `is:degraded`: scored into Poor or Critical. A qualified band cannot rule it out. */
export const bandDegraded = (device: BandSubject): BandTri =>
  overCandidates(device, (b) => b === "Poor" || b === "Critical");

/**
 * The `band:` facet. A value naming the device's own key (`band:excellent-partial`, or a wildcard
 * that covers it) is a yes; otherwise the value is tested against the candidate bands, so
 * `band:excellent` answers a qualified Excellent with unknown rather than yes.
 */
export function bandMatches(device: BandSubject, test: (candidate: string) => boolean): BandTri {
  const k = bandKey(device);
  if (k === null) return "unknown";
  if (test(k)) return "yes";
  return overCandidates(device, test);
}
