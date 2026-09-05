import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { GRAPH_RELATIONS } from "../../build/projection/build.mjs";


test("browser projection graph relations match the strict record schema", async () => {
  const schema = JSON.parse(
    await readFile(new URL("../../schema/atlas-records.schema.json", import.meta.url), "utf8"),
  );
  const schemaRelations = schema.$defs.graphEdgeRecord.properties.relation.enum;

  assert.deepEqual([...GRAPH_RELATIONS].sort(), [...schemaRelations].sort());
  for (const relation of ["cites", "dynamic_import", "extends"]) {
    assert.equal(GRAPH_RELATIONS.has(relation), true);
  }
});
