/**
 * describe-device.test.ts — the canvas announcement may not invent a measurement.
 *
 * THE DEFECT. Selecting a topology-only device in the 3-D fabric announced
 * "AP-floor1 selected. ap. Topology only: this device was never collected. … 17 links, 0 findings."
 * That zero was produced by never having looked: on this snapshot every uncollected device has
 * zero finding records and every collected one has at least one, so the number was only ever
 * emitted for a device nobody assessed.
 *
 * It is the one surface where the announcement is the reader's ONLY channel — there is no visible
 * panel beside it to carry the qualification. And the same product refuses the number on the
 * visual path: `DevicePane` renders "finding counts: not observed / … was never collected, so a
 * severity tally here would count an empty search rather than an assessed device". Two surfaces of
 * one product disagreeing about whether a number may be stated at all is the defect.
 *
 * The assertion is structural, not a string match on today's wording: no digit may immediately
 * precede the word "finding"/"findings" in the announcement for an uncollected device, and the
 * announcement must say the count was not observed. A future rewording that reintroduces a tally
 * fails.
 */
import { describe, expect, it } from "vitest";
import { fabric, findingsByHost } from "../core/data";
import { describeDevice } from "./Fabric3D";

const uncollected = fabric.devices.filter((d) => !d.collected);
const collected = fabric.devices.filter((d) => d.collected);

describe("the 3-D selection announcement", () => {
  it("has both kinds of device to speak about", () => {
    /* Without this the two suites below could both pass over an empty list. */
    expect(uncollected.length, "no uncollected device in this snapshot").toBeGreaterThan(0);
    expect(collected.length).toBeGreaterThan(0);
  });

  it.each(uncollected.map((d) => d.id))("states no finding tally for %s (never collected)", (id) => {
    const said = describeDevice(id);
    expect(said).toContain("never collected");
    expect(
      /\d+\s+findings?\b/i.test(said),
      `"${said}" states a finding tally for a device nobody assessed — a zero produced by never having looked`,
    ).toBe(false);
    expect(said).toMatch(/finding count not observed/i);
  });

  it.each(collected.map((d) => d.id))("states the real finding tally for %s (collected)", (id) => {
    const said = describeDevice(id);
    const n = findingsByHost.get(id)?.length ?? 0;
    /* Where the device WAS assessed the number is a measurement and must be stated, including a
       genuine zero. Suppressing it there would be the mirror-image error. */
    expect(said).toMatch(new RegExp(`\\b${n}\\s+findings?\\b`));
    expect(said).not.toMatch(/finding count not observed/i);
  });
});
