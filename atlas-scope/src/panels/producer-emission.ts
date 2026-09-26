/**
 * producer-emission.ts — was a compiled field EMITTED by the collector, or filled in by the compiler?
 *
 * The shared compiler (tools/compile-snapshot.mjs, owned elsewhere) turns some absent producer keys
 * into values: an ACL line with no `unevaluable` key compiles to `unevaluable: false`, one with no
 * `unmodeled_qualifiers` key to `[]`, one with no `established` key to `false`, and a device with no
 * health_scores record to `deductions: []`. Rendered as they stand, those read as the collector's own
 * testimony — "unevaluable false — the collector's own flag", "[ ] empty — 0 items" — for fields it
 * never emitted (2026-09-22 critic, B6 major and B1 minor). This module reads the sidecar compiled by
 * `tools/compile-producer-emission.mjs` from the same source bytes, and answers one question per
 * field: is this value the collector's, or a projection's?
 *
 * Fail-closed: when the sidecar was compiled from other bytes than this build's data, every field the
 * sidecar is about reads "whether the collector emitted it is unknown" — never as emitted.
 */
import emissionJson from "./producer-emission.json";
import { fabric } from "../core/data";
import { sameSourceBinding, type SourceBinding } from "../core/types";

interface EmissionFile {
  meta: SourceBinding & {
    aclLineFields: Record<string, string>;
    deviceHealthFields: Record<string, string>;
  };
  aclLineAbsent: Record<string, string[]>;
  deviceAbsent: Record<string, string[]>;
}

const FILE = emissionJson as unknown as EmissionFile;

/* Every binding field must agree — digest, its form, byte length and source (O15, `sameSourceBinding`). */
export const PRODUCER_EMISSION_TRUSTED = sameSourceBinding(FILE.meta, fabric.meta);

const ACL_LINE_PATH = /^acls\.[^.[\]]+\.[^[\]]+\[\d+\]$/;

/**
 * Why `field` of the record at `path` is NOT producer testimony, or null when it is (or when this
 * module has nothing to say about that field). `record` identifies a device record, which is cited
 * under more than one path.
 */
export function producerFieldNotEmitted(path: string | null, record: unknown, field: string): string | null {
  if (path !== null && ACL_LINE_PATH.test(path) && field in FILE.meta.aclLineFields) {
    const key = FILE.meta.aclLineFields[field]!;
    if (!PRODUCER_EMISSION_TRUSTED) return `whether the collector emitted \`${key}\` for this line is unknown — the emission record was compiled from other snapshot bytes; the value shown is the compiler's default`;
    if ((FILE.aclLineAbsent[path] ?? []).includes(field))
      return `not emitted by the collector — the source line carries no \`${key}\` key; the compiled value is the compiler's default, not the collector's testimony`;
    return null;
  }
  if (field in FILE.meta.deviceHealthFields) {
    const device = fabric.devices.find((d) => d === record);
    if (device === undefined) return null;
    if (!PRODUCER_EMISSION_TRUSTED) return `whether the collector emitted a health record for ${device.host} is unknown — the emission record was compiled from other snapshot bytes`;
    if ((FILE.deviceAbsent[device.host] ?? []).includes(field))
      return device.collected
        ? `the collector emitted no health_scores record for ${device.host}, so it was never scored; the empty list is the compiler's default`
        : `${device.host} was never reached, so it was never scored; the empty list is the compiler's default, not a finding of none`;
    return null;
  }
  return null;
}
