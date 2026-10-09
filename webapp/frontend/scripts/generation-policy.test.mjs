import { test } from "node:test";
import assert from "node:assert/strict";
import { requireLocalReferences, generationMode } from "./generation-policy.mjs";

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
