/**
 * placeholders.ts — numeric device fields the producer reports as the SAME ZERO for every device.
 *
 * "Power supplies 0" on a WS-C3850-24T that has a serial and a software version is not a count;
 * when every inventoried device in the fleet carries the identical 0, the far likelier reading is
 * that the collector never filled the field. Rendering it as the number 0 turns a likely absence
 * into a measurement — the product's named failure shape (absence rendered as a value).
 *
 * Derived from `fabric.devices` over EVERY numeric field of the record, never from a hand-kept list
 * of field names (a guard scoped to named fields is the shape this repository keeps rediscovering).
 * The set empties by itself the day the collector starts reporting real values. Every surface that
 * renders a device field reads this one owner, so the DevicePane and the Inspector cannot disagree.
 */
import { fabric } from "./data";
import type { Device } from "./types";
import { own } from "./own";

export interface PlaceholderZero {
  /** How many inventoried devices carry the field — the denominator of the reconciliation. */
  inventoried: number;
  /** The sentence rendered in place of the number. */
  reason: string;
}

const inventoried = fabric.devices.filter((d) => d.inventoried);

/** Device field name → why its 0 is rendered as not observed. Only fields where EVERY inventoried device reports 0. */
export const PLACEHOLDER_ZERO_FIELDS: ReadonlyMap<string, PlaceholderZero> = (() => {
  const out = new Map<string, PlaceholderZero>();
  // A "constant" across one device is not evidence of anything; require a real fleet.
  if (inventoried.length < 2) return out;
  const keys = new Set<string>();
  for (const d of inventoried) for (const [k, v] of Object.entries(d)) if (typeof v === "number") keys.add(k);
  for (const k of [...keys].sort()) {
    const all = inventoried.map((d) => own(d as unknown as Record<string, unknown>, k));
    if (all.every((v) => v === 0)) {
      out.set(k, {
        inventoried: inventoried.length,
        reason: `the producer reported 0 for all ${inventoried.length} inventoried devices, so this field is very likely uncollected rather than counted`,
      });
    }
  }
  return out;
})();

/** The placeholder reading for `field` on `device`, or null when the value should render as itself. */
export function placeholderZero(device: Device, field: string): PlaceholderZero | null {
  if (!device.inventoried) return null;
  const v = own(device as unknown as Record<string, unknown>, field);
  return v === 0 ? (PLACEHOLDER_ZERO_FIELDS.get(field) ?? null) : null;
}
