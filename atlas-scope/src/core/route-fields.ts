/**
 * route-fields.ts — the ONE owner of how a route record's `adminDistance` and `nextHop` read.
 *
 * B1 failed twice for one class. A connected route's null administrative distance was
 * "0 — … by definition" in the Path panel and the Inspector and "administrative distance: not
 * observed" on the Device pane's Routing tab — one record, two readings, because each surface decided
 * for itself. An earlier fix moved the judgement into `claims.ts :: notApplicableReason` and wired two
 * of the three surfaces to it. So the judgement now lives HERE, in one function every surface renders
 * (`HopList.tsx :: RouteFieldValue`), and `HopList.admin-distance.test.tsx` holds a type-checker guard
 * that fails if any other module reads `RouteEntry.adminDistance` at all.
 *
 * WHY A LEAF MODULE, NOT `claims.ts`. The forwarding engine ranks tied routes by administrative
 * distance, and ranking a null as 0 is the same judgement the rendering makes — so the engine must ask
 * this owner too. `claims.ts` imports the engine, and a module-level constant there
 * (`REFUSAL_UNDECIDING = REFUSAL_UNDECIDING_KINDS`) is evaluated at load: an engine that imported
 * `claims.ts` back would, when the engine loads first, read that binding before it exists. This file
 * imports types only, so every module — the engine included — can depend on it without a cycle; the
 * guard test asserts that property. `claims.ts` re-exports everything here.
 *
 * DECISION CHANGED 2026-09-23 (acceptance B1, "allows no inference exemption"). The 2026-09-22
 * auditor decision rendered that null as "0 — … by definition", which put the digit 0 in the value
 * slot of a record that carries no number. The value slot now reads "not recorded"; the platform
 * convention (connected and local routes rank at administrative distance zero) is given as the
 * REASON that the missing number is not an evidence gap — never as the record's value. It is still
 * not "not observed": nothing that was collectable is missing.
 */
import type { RouteEntry } from "./types";

/** The route-record fields whose null this owner decides. */
export type RouteField = "adminDistance" | "nextHop";

export interface RouteFieldReading {
  /**
   * `value` — the record carries it; `not-applicable` — a structural null (the record's own shape
   * says the field cannot carry a value); `absent` — a real evidence gap, rendered "not observed".
   */
  kind: "value" | "not-applicable" | "absent";
  /**
   * The words every surface renders for the field, in full. For `not-applicable` it is exactly
   * `${short} — ${reason}`; for `absent`, the generic "not observed".
   */
  text: string;
  /** The value-slot word alone ("not recorded", "n/a"), for a cell too narrow for the reason. */
  short: string;
  /** For `not-applicable`: why the null is structural. A narrow cell still carries it, off-screen. */
  reason: string | null;
  /** The noun, for the not-observed mark's accessible name. */
  what: string;
  /** For `absent`: why the value is missing. */
  why: string | null;
}

const ROUTE_FIELD_NOUN: Readonly<Record<RouteField, string>> = {
  adminDistance: "administrative distance",
  nextHop: "next-hop address",
};
const ROUTE_FIELD_ABSENT: Readonly<Record<RouteField, string>> = {
  adminDistance: "the collected routing table did not record a distance for this entry",
  nextHop: "the collected route names no next-hop address",
};

/** An attached route: its prefix is on an interface of the device itself. */
const attachedSource = (route: Pick<RouteEntry, "source">): "connected" | "local" | null => {
  const src = typeof route.source === "string" ? route.source.toLowerCase() : null;
  return src === "connected" || src === "local" ? src : null;
};

/** A compiled route record, by its own shape — not by where it was found. */
export function isRouteRecord(v: unknown): v is RouteEntry {
  if (typeof v !== "object" || v === null) return false;
  const r = v as Record<string, unknown>;
  return typeof r.prefix === "string" && "source" in r && ("adminDistance" in r || "nextHop" in r);
}

/**
 * How one field of a route record reads, on every surface: the Path panel's hop list, the Device
 * pane's Routing tab and the Inspector all render THIS, so the same record cannot read two ways.
 */
export function routeFieldReading(route: RouteEntry, field: RouteField): RouteFieldReading {
  const what = ROUTE_FIELD_NOUN[field];
  const attached = attachedSource(route);
  const value = (text: string): RouteFieldReading => ({ kind: "value", text, short: text, reason: null, what, why: null });
  const structural = (short: string, reason: string): RouteFieldReading => ({
    kind: "not-applicable",
    text: `${short} — ${reason}`,
    short,
    reason,
    what,
    why: null,
  });
  const absent: RouteFieldReading = { kind: "absent", text: "not observed", short: "not observed", reason: null, what, why: ROUTE_FIELD_ABSENT[field] };
  if (field === "adminDistance") {
    const ad = route.adminDistance ?? null;
    if (ad !== null) return value(String(ad));
    if (attached !== null) {
      return structural(
        "not recorded",
        `the record carries no value; a ${attached} route's administrative distance is zero by platform convention, so nothing collectable is missing`,
      );
    }
    return absent;
  }
  const nh = route.nextHop ?? null;
  if (nh !== null) return value(nh);
  if (attached !== null) return structural("n/a", `a ${attached} route has no next hop`);
  return absent;
}

/**
 * The administrative distance to RANK a route by, or null when it is unknown. A connected or local
 * route with no recorded number ranks at 0 — the platform convention stated in `routeFieldReading` —
 * and that reading is decided here so a ranking and a rendering cannot drift apart. A number this
 * returns for a null record is a convention, never the record's value: do not print it as one; to
 * show a route's distance, render `routeFieldReading(route, "adminDistance")`.
 */
export function adminDistanceRank(route: RouteEntry): number | null {
  if (route.adminDistance !== null) return route.adminDistance;
  return attachedSource(route) !== null ? 0 : null;
}
