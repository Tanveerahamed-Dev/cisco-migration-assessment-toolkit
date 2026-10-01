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
import { holds } from "./own";
import { BAND_ORDER, NOT_MEASURED_BAND, notMeasuredBand, recognisedBand, unrecognisedPhrase, type Band, type Device } from "./types";

/** The tone a band is drawn in when it stands unqualified. */
export type BandTone = "up" | "high" | "critical" | "neutral";

/* Keyed by the CLOSED band vocabulary and read only with a band `recognisedBand` admitted: a snapshot band the
   vocabulary does not name ("constructor", "Bogus") and the engine's not-measured band ("Insufficient Data") never
   reach this table, so neither can answer from Object.prototype nor borrow a member's tone. */
export const BAND_TONE: Readonly<Record<Band, BandTone>> = {
  Excellent: "up",
  Good: "up",
  Fair: "high",
  Poor: "high",
  Critical: "critical",
};

/** A band whose unqualified tone is favourable — the only bands the absence of evidence can flatter. */
export const isFavourableBand = (band: string | null | undefined): boolean =>
  recognisedBand(band) && BAND_TONE[band] === "up";

/** `interfacesOf`/`physicalByHost` flatten "no records" and "host never collected" into an empty
 *  array. The difference decides whether an empty table means zero or means unknown, so the
 *  presence of the host KEY is read directly rather than the length of what it returns. */
const hasInterfaceRecords = (host: string): boolean => holds(fabric.interfaces, host);

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
  /** Which legend row counts this device: the band, `${band}${PARTIAL_MARK}`, "none", "not-measured", or "unrecognised". */
  legendKey: string;
  /** The text the snapshot states for a band the vocabulary does not name (legendKey "unrecognised"), exactly as
   *  written, so a surface can quote it; null for every other band. Never a band: a surface shows it, never reads it as one. */
  unrecognised: string | null;
  /** The engine states it could not measure this device (NOT_MEASURED_BAND, legendKey "not-measured"): no band, and
   *  the score it publishes beside that is not a measurement (`measuredScore`). */
  notMeasured: boolean;
}

/** The words for the engine's not-measured band, quoting the engine's own term so a reader can find it in the snapshot. */
export const NOT_MEASURED_LABEL = `not measured (engine: ${NOT_MEASURED_BAND})`;

/** Colour token for each band; `null` (no band computed) is indeterminate, never neutral grey. */
const BAND_TOKEN: Readonly<Record<Band, string>> = {
  Excellent: "--band-excellent",
  Good: "--band-good",
  Fair: "--band-fair",
  Poor: "--band-poor",
  Critical: "--band-critical",
};
/** The neutral ink a qualified band is drawn in — the same `--text-muted` DevicePane.css uses. */
export const QUALIFIED_BAND_TOKEN = "--text-muted";
export const NO_BAND_TOKEN = "--claim-indeterminate";

export const bandToken = (band: Band): string => BAND_TOKEN[band];

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
      unrecognised: null,
      notMeasured: false,
    };
  }
  if (notMeasuredBand(band)) {
    /* The engine's own statement that it could not measure this device (core/types.ts NOT_MEASURED_BAND): no band,
       no tone, no colour, no ceiling, no answer to is:healthy — and not "unrecognised", because the engine defines it. */
    return {
      band,
      unassessed,
      qualified: false,
      label: NOT_MEASURED_LABEL,
      tone: "neutral",
      colorToken: NO_BAND_TOKEN,
      letter: "?",
      short: NOT_MEASURED_LABEL,
      sentence: `Health band not measured: the engine banded ${device.host} ${JSON.stringify(band)} — its collection was too incomplete to score, so no band applies and the score it publishes is not a measurement.`,
      legendKey: "not-measured",
      unrecognised: null,
      notMeasured: true,
    };
  }
  if (!recognisedBand(band)) {
    /* A band the snapshot STATES that the vocabulary does not name: shown as it was written, drawn indeterminate,
       and never read as a band — no tone, no colour, no ceiling, no answer to is:healthy. */
    const words = unrecognisedPhrase("band", band);
    return {
      band,
      unassessed,
      qualified: false,
      label: words,
      tone: "neutral",
      colorToken: NO_BAND_TOKEN,
      letter: "?",
      short: words,
      sentence: `Health band not recognised: the snapshot states ${JSON.stringify(band)}, which is not one of ${BAND_ORDER.join(", ")}, so it is not read as a band.`,
      legendKey: "unrecognised",
      unrecognised: band,
      notMeasured: false,
    };
  }
  const qualified = isFavourableBand(band) && unassessed.length > 0;
  if (!qualified) {
    return {
      band,
      unassessed,
      qualified,
      label: band,
      tone: BAND_TONE[band],
      colorToken: bandToken(band),
      letter: band.slice(0, 1),
      short: band,
      sentence: `Health band ${band}.`,
      legendKey: band,
      unrecognised: null,
      notMeasured: false,
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
    unrecognised: null,
    notMeasured: false,
  };
}

/* ── everything a surface asks of a band, each answer carrying the qualification ── */

type BandSubject = Pick<Device, "host" | "band" | "collected">;

/** Tri-state, the same vocabulary as the query engine: `unknown` = the evidence to decide is absent. */
export type BandTri = "yes" | "no" | "unknown";

/**
 * Did the engine SCORE this device into one of its five bands? (Presence only — says nothing about its quality.)
 * No for no band, for the engine's not-measured band (it says it could not score), and for a band the vocabulary
 * does not name (nothing Atlas Scope can read as a band). It used to be `band !== null`, which counted the engine's
 * "Insufficient Data" as a scored device in the coverage bar.
 */
export const bandScored = (device: Pick<Device, "band">): boolean => recognisedBand(device.band);

/**
 * The health score as a MEASUREMENT: the published score, or null where the engine banded the device not-measured —
 * the number it publishes beside that is not one (cisco_toolkit/analyze.py `compute_health_scores` leaves an
 * empty-parse host's untouched 100 in place, and the engine's own statistics exclude such rows). Every surface that
 * counts, sorts, filters or draws a score reads this, never `Device.score` alone.
 */
export const measuredScore = (device: Pick<Device, "band" | "score">): number | null =>
  notMeasuredBand(device.band) ? null : device.score;

/** The suffix a qualified band's key carries in query values, grouping keys and sort order. A word,
 *  not PARTIAL_MARK: `*` is the query language's wildcard. */
export const PARTIAL_KEY_SUFFIX = "-partial";

/** Every presented band key, best first: each favourable band is followed by its qualified form. */
export const BAND_KEY_ORDER: readonly string[] = BAND_ORDER.flatMap((b) =>
  isFavourableBand(b) ? [b, `${b}${PARTIAL_KEY_SUFFIX}`] : [b],
);

/** The key a device's band is filed, grouped, faceted and counted under: "Excellent",
 *  "Excellent-partial", or null when no band was computed or the band is not one the vocabulary names. */
export function bandKey(device: BandSubject): string | null {
  const band = device.band;
  if (band === null || !recognisedBand(band)) return null;
  return presentBand(device).qualified ? `${band}${PARTIAL_KEY_SUFFIX}` : band;
}

/** The GROUP key of a device the engine banded not-measured (never a `bandKey`: it is not a band). */
export const NOT_MEASURED_GROUP_KEY = "not-measured";
/** Every band GROUP key, in order: the scored band keys, then the engine's not-measured band. */
export const BAND_GROUP_ORDER: readonly string[] = [...BAND_KEY_ORDER, NOT_MEASURED_GROUP_KEY];

/**
 * The group a device is filed under by band — every device has exactly one answer: a scored band's key, the
 * not-measured group, an UNRECOGNISED band (the producer's text, tagged so it can never collide with a key and is
 * labelled as unrecognised by core/query.ts `groupItems`), or null (no band computed: the Not-observed group). A
 * grouping that read `bandKey` alone filed the last three under "Not observed", which is true of none but the last.
 */
export function bandGroupKey(device: BandSubject): string | { readonly unrecognised: string } | null {
  const band = device.band;
  if (band === null) return null;
  if (notMeasuredBand(band)) return NOT_MEASURED_GROUP_KEY;
  if (!recognisedBand(band)) return { unrecognised: band };
  return bandKey(device);
}

/** Human words for a band key: "Excellent-partial" -> "Excellent (partial)", the not-measured group in words. */
export const bandKeyLabel = (key: string): string =>
  key === NOT_MEASURED_GROUP_KEY
    ? NOT_MEASURED_LABEL
    : key.endsWith(PARTIAL_KEY_SUFFIX)
      ? `${key.slice(0, -PARTIAL_KEY_SUFFIX.length)} (partial)`
      : key;

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
  if (band === null || !recognisedBand(band)) return null;
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
