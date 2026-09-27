/**
 * producer-emission.test.ts — a compiled value filled in for a key the collector never emitted is
 * never rendered as the collector's testimony (2026-09-22 critic, B6 major and B1 minor).
 *
 * The oracle is the SOURCE snapshot, read here independently of both compilers: for every ACL line
 * and every device, each defaulted field whose source key is absent must be answered "not emitted".
 */
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { fabric } from "../core/data";
import emission from "./producer-emission.json";
import { PRODUCER_EMISSION_TRUSTED, producerFieldNotEmitted } from "./producer-emission";

/* The dataset under test: the file this sidecar names (`meta.source`, repository-relative), not a typed
   path (R7). The critic's-line and AP-floor1 cases below are explicitly SAMPLE-scoped: they name records
   of the tracked sample fleet, which is the only source the tracked sidecar may be compiled from. */
const SRC = resolve(__dirname, "../../..", emission.meta.source);
const raw = readFileSync(SRC);
const snap = JSON.parse(raw.toString("utf8")) as Record<string, any>;

/* The bound form (O15, tools/source-binding.mjs): the LF-normalised bytes — every CR LF read as LF,
   nothing else touched — which is what Git stores, so the digest is the same from a CRLF (Windows)
   or an LF checkout. Restated here independently of the tool (latin1 is a byte-preserving decode).
   This used to hash the RAW disk bytes, i.e. the Windows working tree, which no clone reproduces. */
const lfNormalised = Buffer.from(raw.toString("latin1").split("\r\n").join("\n"), "latin1");

describe("the emission sidecar is bound to the same bytes", () => {
  it("sha256 matches the source (LF-normalised form) and the compiled fabric", () => {
    expect(emission.meta.sourceDigestForm).toBe("lf-normalised");
    expect(emission.meta.sourceSha256).toBe(createHash("sha256").update(lfNormalised).digest("hex"));
    expect(emission.meta.sourceBytes).toBe(lfNormalised.byteLength);
    expect(emission.meta.sourceSha256).toBe(fabric.meta.sourceSha256);
    expect(PRODUCER_EMISSION_TRUSTED).toBe(true);
  });
});

describe("a missing source key never becomes producer testimony", () => {
  it("ACL lines: every compiled defaulted field whose source key is absent reads as not emitted", () => {
    const fields = emission.meta.aclLineFields as Record<string, string>;
    let absent = 0;
    for (const [host, lists] of Object.entries(snap.acls ?? {}))
      for (const [name, lines] of Object.entries(lists as Record<string, any[]>))
        lines.forEach((l, i) => {
          const path = `acls.${host}.${name}[${i}]`;
          const compiled = (fabric.acls as any)[host]?.[name]?.[i];
          expect(compiled, path).toBeDefined();
          for (const [field, key] of Object.entries(fields)) {
            const emitted = Object.prototype.hasOwnProperty.call(l, key);
            const why = producerFieldNotEmitted(path, compiled, field);
            if (!emitted) absent += 1;
            expect(why === null, `${path}.${field} (source key ${key} ${emitted ? "present" : "absent"})`).toBe(emitted);
          }
        });
    expect(absent, "the sweep must meet at least one absent key").toBeGreaterThan(0);
  });

  it("the critic's line: INET_RETURN[0] emitted no unevaluable and no unmodeled_qualifiers", () => {
    const rec = (fabric.acls as any).core1.INET_RETURN[0];
    expect(producerFieldNotEmitted("acls.core1.INET_RETURN[0]", rec, "unevaluable")).toMatch(/not emitted by the collector/);
    expect(producerFieldNotEmitted("acls.core1.INET_RETURN[0]", rec, "unmodeledQualifiers")).toMatch(/not emitted by the collector/);
    expect(producerFieldNotEmitted("acls.core1.INET_RETURN[0]", rec, "established")).toBeNull();
  });

  it("devices: deductions read as not emitted exactly where no health_scores record carries the host", () => {
    const scored = new Set((snap.health_scores as any[]).map((h) => h.switch));
    let unscored = 0;
    for (const d of fabric.devices) {
      const why = producerFieldNotEmitted(null, d, "deductions");
      if (!scored.has(d.host)) unscored += 1;
      expect(why === null, d.host).toBe(scored.has(d.host));
    }
    expect(unscored).toBeGreaterThan(0);
    const ap = fabric.devices.find((d) => d.host === "AP-floor1")!;
    expect(producerFieldNotEmitted(null, ap, "deductions")).toMatch(/never reached, so it was never scored/);
  });
});
