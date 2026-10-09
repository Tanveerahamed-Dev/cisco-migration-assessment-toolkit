// @vitest-environment node
import { describe, expect, it } from "vitest";
import { compileAll } from "../../tools/lib/compile-model.mjs";
import { assertValidSnapshot } from "../../tools/lib/validate-snapshot.mjs";
import { bindSource } from "../../tools/source-binding.mjs";

const HOST = "node.with.dots";
const row = (host = HOST) => ({ host, severity: "High", vlans_impacted: 3, stranded: 45, hard: 3,
  backup: 0, fhrp: 0, off_scan_gw_vlans: 0, blind_links: 0, detail: "Stored simulation detail" });
const dossier = (assessable = "published") => ({ host: HOST, impact_assessability: {
  assessable, why: assessable === "published" ? "" : "Owner reason: incomplete simulation", pointer: "/failure_impact/0",
} });
function snapshot(assessable = "published"): Record<string, any> {
  return { schema: "collect_parse_snapshot/1", devices: { [HOST]: {} },
    cable_map: { nodes: [], cables: [] }, failure_impact: [row()], device_dossiers: { per_device: [dossier(assessable)] } };
}
function compile(snap: Record<string, any>) {
  const bytes = new TextEncoder().encode(JSON.stringify(snap));
  const checked = assertValidSnapshot(bytes);
  return compileAll(checked.snap, bindSource(bytes, { source: "impact-case.json", sourceOrigin: "external-file" })).fabric;
}
const impact = (snap: Record<string, any>) => compile(snap).devices.find((d) => d.host === HOST)!.impact!;

describe("failure-impact measurements consume the persisted dossier owner", () => {
  it("published keeps measured zero and the exact pointer-selected row, with both citations", () => {
    const got = impact(snapshot());
    expect(got).toMatchObject({ assessable: "published", why: "", unavailable: null, severity: "High",
      stranded: 45, backup: 0, fhrp: 0, cite: "device_dossiers.per_device[0].impact_assessability" });
    expect(got.row).toMatchObject({ host: HOST, stranded: 45, backup: 0, cite: "failure_impact[0]" });
    expect(got).not.toHaveProperty("codes"); // the stored owner does not publish them
  });

  it("lower bound keeps positive floors, holds zero and categorical severity, and keeps the owner's reason", () => {
    const got = impact(snapshot("lower_bound"));
    expect(got).toMatchObject({ assessable: "lower_bound", why: "Owner reason: incomplete simulation", unavailable: null,
      stranded: 45, vlans: 3, hard: 3, severity: null, backup: null, fhrp: null });
    expect(got.row).toMatchObject({ severity: "High", backup: 0, fhrp: 0 });
  });

  it.each(["not_assessed", "ambiguous"])("%s never publishes stored positive values as measurements", (state) => {
    expect(impact(snapshot(state))).toMatchObject({ assessable: state, severity: null, stranded: null,
      vlans: null, hard: null, backup: null, fhrp: null, row: { stranded: 45 } });
  });

  it.each(["lower_bound", "not_assessed", "ambiguous"])("%s does not publish a held clean-bill detail", (state) => {
    const snap = snapshot(state);
    snap.failure_impact[0].detail = "No reachability impact";
    expect(impact(snap)).toMatchObject({ detail: null, row: { detail: "No reachability impact" } });
  });

  it("selects by the owner pointer, never by the last raw host row", () => {
    const snap = snapshot("ambiguous");
    snap.failure_impact.push({ ...row(), stranded: 99 });
    const got = impact(snap);
    expect(got.row?.stranded).toBe(45);
    expect(got.stranded).toBeNull();
  });

  it.each([
    ["missing dossiers", (s: Record<string, any>) => { delete s.device_dossiers; }],
    ["missing owner", (s: Record<string, any>) => { delete s.device_dossiers.per_device[0].impact_assessability; }],
    ["duplicate dossier", (s: Record<string, any>) => { s.device_dossiers.per_device.push(dossier()); }],
    ["unknown verdict", (s: Record<string, any>) => { s.device_dossiers.per_device[0].impact_assessability.assessable = "exact-ish"; }],
    ["unreadable reason", (s: Record<string, any>) => { s.device_dossiers.per_device[0].impact_assessability.why = {}; }],
    ["bound without reason", (s: Record<string, any>) => { s.device_dossiers.per_device[0].impact_assessability = { assessable: "lower_bound", why: " ", pointer: "/failure_impact/0" }; }],
    ["noncanonical pointer", (s: Record<string, any>) => { s.device_dossiers.per_device[0].impact_assessability.pointer = "/failure_impact/00"; }],
    ["pointer to another host", (s: Record<string, any>) => { s.failure_impact[0].host = "different-host"; }],
    ["out-of-range pointer", (s: Record<string, any>) => { s.device_dossiers.per_device[0].impact_assessability.pointer = "/failure_impact/12"; }],
    ["duplicate raw host under published verdict", (s: Record<string, any>) => { s.failure_impact.push(row()); }],
  ] as const)("%s is held without a raw-row fallback", (_title, mutate) => {
    const snap = snapshot();
    mutate(snap);
    const got = impact(snap);
    expect(got.assessable).toBeNull();
    expect(got.unavailable).toBeTypeOf("string");
    expect([got.severity, got.stranded, got.vlans, got.hard, got.backup, got.fhrp]).toEqual(Array(6).fill(null));
  });

  it("not assessed with no row keeps the owner's no-row reason", () => {
    const snap = snapshot("not_assessed");
    snap.failure_impact = [];
    snap.device_dossiers.per_device[0].impact_assessability.pointer = null;
    expect(impact(snap)).toMatchObject({ assessable: "not_assessed", why: "Owner reason: incomplete simulation", row: null, unavailable: null });
  });

  it("invalid numeric cells are absent, never coerced to zero", () => {
    const snap = snapshot();
    Object.assign(snap.failure_impact[0], { stranded: "45", hard: -1, backup: 0.5, fhrp: Number.MAX_SAFE_INTEGER + 1 });
    expect(impact(snap)).toMatchObject({ stranded: null, hard: null, backup: null, fhrp: null, vlans: 3 });
  });

  it.each(["missing", "duplicate"])("%s ownership on a cable-only host cites its existing topology context", (state) => {
    const snap = snapshot();
    snap.devices = {};
    snap.cable_map.nodes = [{ host: HOST, collected: false, kind: "switch" }];
    snap.device_dossiers.per_device = state === "missing" ? [] : [dossier(), dossier()];
    const device = compile(snap).devices.find((d) => d.host === HOST)!;
    expect(device.cite).toBe(`cable_map.nodes[host=${HOST}]`);
    expect(device.impact).toMatchObject({ cite: device.cite, assessable: null, row: null,
      severity: null, stranded: null, vlans: null, hard: null, backup: null, fhrp: null });
    expect(device.impact?.unavailable).toBeTypeOf("string");
  });
});
