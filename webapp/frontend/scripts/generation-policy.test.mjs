import { test } from "node:test";
import assert from "node:assert/strict";
import { requireLocalReferences, generationMode, requirementsTypeSource } from "./generation-policy.mjs";

test("generation modes never ignore an output path or combine review with check", () => {
  assert.equal(generationMode([]), "generate");
  assert.equal(generationMode(["--check"]), "check");
  assert.equal(generationMode(["--review"]), "review");
  for (const args of [["--output", "/tmp/types.ts"], ["--check", "--review"],
    ["--check", "--check"], ["--review", "extra"], ["--unknown"]]) {
    assert.throws(() => generationMode(args), /exclusively/);
  }
});

test("allows local component references without changing schema", () => {
  const source = { components: { schemas: { X: { $ref: "#/components/schemas/Y" } } } };
  const before = JSON.stringify(source);
  requireLocalReferences(source);
  assert.equal(JSON.stringify(source), before);
});
for (const value of ["https://generator.invalid/example.json", "file:///private.json", "../private.json"]) {
  test(`rejects nested externalValue before CLI resolution: ${value}`, () => {
    assert.throws(() => requireLocalReferences({ schemas: { X: { example: { externalValue: value } } } }), /externalValue/);
  });
  test(`rejects external $ref before CLI resolution: ${value}`, () => {
    assert.throws(() => requireLocalReferences({ schema: { $ref: value } }), /local/);
  });
}
for (const key of ["$dynamicRef", "$recursiveRef"]) {
  test(`rejects unsupported semantic reference ${key}`, () => {
    assert.throws(() => requireLocalReferences({ schemas: [{ [key]: "#/components/schemas/X" }] }), /unsupported/);
  });
}

function requirementsSchema() {
  return { "x-atlas-requirements-contract": {
    schema: "atlas.requirements-contract/1", scope: "saved_plan_admission",
    keys: ["availability_tier", "fabric_operating_model", "convergence_budget_ms", "vlan_zones", "example_list"],
    list_fields: ["example_list"], availability_tiers: ["premium", "standard"],
    fabric_models: ["example-fabric"], vlan_id: { minimum: 2, maximum: 42 },
  } };
}

test("runtime contract and mapped types derive from the actual OpenAPI extension, including future list keys", () => {
  const schema = requirementsSchema();
  const before = JSON.stringify(schema);
  const source = requirementsTypeSource(schema);
  assert.match(source, /export const designRequirementsContract = /);
  assert.match(source, /"premium"/);
  assert.match(source, /"example_list"/);
  assert.match(source, /"minimum": 2/);
  assert.match(source, /"maximum": 42/);
  assert.match(source, /typeof designRequirementsContract\.list_fields\[number\]/);
  assert.match(source, /export type DesignRequirements = /);
  assert.equal(JSON.stringify(schema), before);
  schema["x-atlas-requirements-contract"].availability_tiers.push("new-tier");
  assert.notEqual(requirementsTypeSource(schema), source, "owner domain drift must change api:check's compared bytes");
  const reversed = Object.fromEntries(Object.entries(schema["x-atlas-requirements-contract"]).reverse());
  assert.equal(requirementsTypeSource({ "x-atlas-requirements-contract": reversed }), requirementsTypeSource(schema));
});

for (const [name, mutate] of [
  ["missing extension", (schema) => { delete schema["x-atlas-requirements-contract"]; }],
  ["wrong scope", (schema) => { schema["x-atlas-requirements-contract"].scope = "all_cli_inputs"; }],
  ["unknown property", (schema) => { schema["x-atlas-requirements-contract"].foreign = true; }],
  ["duplicate domain", (schema) => { schema["x-atlas-requirements-contract"].availability_tiers.push("premium"); }],
  ["foreign list field", (schema) => { schema["x-atlas-requirements-contract"].list_fields.push("missing"); }],
  ["missing required field", (schema) => { schema["x-atlas-requirements-contract"].keys.shift(); }],
  ["executable domain text", (schema) => { schema["x-atlas-requirements-contract"].fabric_models = ["\"; throw 1;"]; }],
  ["invalid VLAN domain", (schema) => { schema["x-atlas-requirements-contract"].vlan_id.maximum = 1; }],
  ["extra VLAN property", (schema) => { schema["x-atlas-requirements-contract"].vlan_id.foreign = 2; }],
]) {
  test(`requirements metadata refuses ${name} before generation`, () => {
    const schema = requirementsSchema();
    assert.doesNotThrow(() => requirementsTypeSource(schema));
    mutate(schema);
    assert.throws(() => requirementsTypeSource(schema), /engine-owned saved-plan requirements contract/);
  });
}
