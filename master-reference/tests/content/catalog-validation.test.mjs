import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import test from "node:test";

const contentRoot = new URL("../../content/", import.meta.url);
const repositoryRoot = new URL("../../../", import.meta.url);

async function load(name) {
  return JSON.parse(await readFile(new URL(name, contentRoot), "utf8"));
}

const [core, catalog, governance, horizon, outputContract] = await Promise.all([
  load("atlas-core.json"),
  load("capability-catalog.json"),
  load("delivery-governance.json"),
  load("open-horizon-register.json"),
  load("output-contract.json"),
]);

const documents = [core, catalog, governance, horizon, outputContract];
const capabilities = catalog.domains.flatMap((domain) =>
  domain.entries.map((entry) => ({ ...entry, domain_ref: domain.id })),
);

const supportStates = new Set([
  "current",
  "partial",
  "missing",
  "gated",
  "excluded",
  "unknown",
]);

function visit(value, callback, path = "$") {
  if (Array.isArray(value)) {
    value.forEach((item, index) => visit(item, callback, `${path}[${index}]`));
    return;
  }
  if (!value || typeof value !== "object") return;
  callback(value, path);
  Object.entries(value).forEach(([key, item]) =>
    visit(item, callback, `${path}.${key}`),
  );
}

function idsIn(value) {
  const rows = [];
  visit(value, (item, path) => {
    if (typeof item.id === "string" && item.entity_role !== "reference") {
      rows.push({ id: item.id, path });
    }
  });
  return rows;
}

function assertOwnerGrounded(records, stateKey = "state") {
  for (const record of records) {
    if (["current", "partial"].includes(record[stateKey])) {
      assert.ok(
        Array.isArray(record.owner_refs) && record.owner_refs.length > 0,
        `${record.id} claims a ${record[stateKey]} slice without owner_refs`,
      );
    }
  }
}

function assertIncompleteDisposition(records, stateKey = "state") {
  for (const record of records) {
    if (record[stateKey] !== "current") {
      assert.ok(
        Array.isArray(record.gap_refs) && record.gap_refs.length > 0,
        `${record.id} is ${record[stateKey]} without a dispositioned gap`,
      );
    }
  }
}

test("uses one schema/catalog version and globally unique stable IDs", () => {
  for (const document of documents) {
    assert.match(document.schema_version, /^\d+\.\d+\.\d+$/);
    assert.equal(document.schema_version, core.schema_version);
    assert.equal(document.catalog_version, core.catalog_version);
  }

  const rows = documents.flatMap(idsIn);
  const seen = new Map();
  for (const row of rows) {
    assert.match(row.id, /^[a-z0-9]+(?:[.-][a-z0-9]+)*$/);
    assert.equal(
      seen.has(row.id),
      false,
      `duplicate id ${row.id} at ${seen.get(row.id)} and ${row.path}`,
    );
    seen.set(row.id, row.path);
  }
  assert.ok(rows.length >= 450, "the curated layer unexpectedly lost major entities");
});

test("contains all requested domains, six architecture planes, eight traffic planes, and fourteen labs", () => {
  const requiredDomains = new Set([
    "domain.outcomes",
    "domain.architecture",
    "domain.protocols",
    "domain.traffic",
    "domain.enterprise-design",
    "domain.security-privacy",
    "domain.observability-operations",
    "domain.vendors-channels",
    "domain.gui-white-label",
    "domain.artifacts-deliverables",
    "domain.code-tests-release-knowledge",
    "domain.product-business",
  ]);
  const declaredDomains = new Set(core.domain_registry.map((domain) => domain.id));
  const catalogDomains = new Set(catalog.domains.map((domain) => domain.id));
  assert.deepEqual(declaredDomains, requiredDomains);
  assert.deepEqual(catalogDomains, requiredDomains);

  const minimumEntries = {
    "domain.outcomes": 8,
    "domain.architecture": 8,
    "domain.protocols": 30,
    "domain.traffic": 8,
    "domain.enterprise-design": 15,
    "domain.security-privacy": 18,
    "domain.observability-operations": 18,
    "domain.vendors-channels": 18,
    "domain.gui-white-label": 12,
    "domain.artifacts-deliverables": 17,
    "domain.code-tests-release-knowledge": 15,
    "domain.product-business": 12,
  };
  for (const domain of catalog.domains) {
    assert.ok(
      domain.entries.length >= minimumEntries[domain.id],
      `${domain.id} lost required breadth`,
    );
  }

  assert.equal(core.system_architecture.planes.length, 6);
  assert.deepEqual(
    core.system_architecture.planes.map((plane) => plane.order),
    [1, 2, 3, 4, 5, 6],
  );
  assert.equal(core.traffic_model.planes.length, 8);
  assert.deepEqual(
    core.traffic_model.planes.map((plane) => plane.order),
    [1, 2, 3, 4, 5, 6, 7, 8],
  );
  assert.equal(governance.labs.length, 14);
  assert.deepEqual(
    governance.labs.map((lab) => lab.number),
    Array.from({ length: 14 }, (_, index) => index + 1),
  );
});

test("uses only controlled support states and demonstrates every state", () => {
  const stateBearing = [
    ...capabilities,
    ...core.current_maturity,
    ...core.traffic_model.planes,
    ...governance.quality_scenarios,
  ];
  for (const record of stateBearing) {
    assert.ok(supportStates.has(record.state), `${record.id} has invalid state ${record.state}`);
  }
  for (const lab of governance.labs) {
    assert.ok(
      supportStates.has(lab.underlying_support_state),
      `${lab.id} has invalid underlying support state`,
    );
  }

  const catalogStates = new Set(capabilities.map((entry) => entry.state));
  assert.deepEqual(catalogStates, supportStates);
});

test("grounds current and partial claims in live owner paths", async () => {
  const ownerIds = new Set(core.owners.map((owner) => owner.id));
  assert.equal(ownerIds.size, core.owners.length);

  for (const owner of core.owners) {
    assert.ok(owner.path && !owner.path.includes("::"), `${owner.id} needs a real path`);
    await access(fileURLToPath(new URL(owner.path.replaceAll("\\", "/"), repositoryRoot)));
  }

  assertOwnerGrounded(core.current_baseline.map((record) => ({ ...record, state: "current" })));
  assertOwnerGrounded(core.current_maturity);
  assertOwnerGrounded(core.traffic_model.planes);
  assertOwnerGrounded(capabilities);
  assertOwnerGrounded(governance.quality_scenarios);
  assertOwnerGrounded(governance.labs, "underlying_support_state");

  visit(documents, (record) => {
    if (!Array.isArray(record.owner_refs)) return;
    for (const ownerRef of record.owner_refs) {
      assert.ok(ownerIds.has(ownerRef), `${record.id ?? "record"} cites unknown owner ${ownerRef}`);
    }
  });
});

test("links every incomplete cell to an actionable, dispositioned gap", () => {
  const gapIds = new Set(governance.gaps.map((gap) => gap.id));
  assert.equal(gapIds.size, governance.gaps.length);
  assertIncompleteDisposition(core.current_maturity);
  assertIncompleteDisposition(core.traffic_model.planes);
  assertIncompleteDisposition(capabilities);
  assertIncompleteDisposition(governance.quality_scenarios);
  assertIncompleteDisposition(governance.labs, "underlying_support_state");

  for (const gap of governance.gaps) {
    assert.ok(governance.gap_dispositions.includes(gap.disposition));
    assert.match(gap.priority, /^P[0-3]$/);
    assert.ok(gap.problem.length >= 40);
    assert.ok(gap.next_actions.length >= 3);
    assert.ok(gap.acceptance_evidence.length >= 2);
    assert.ok(gap.owner_role.length > 0);
  }

  const usedGaps = new Set();
  visit(documents, (record) => {
    if (!Array.isArray(record.gap_refs)) return;
    for (const gapRef of record.gap_refs) {
      assert.ok(gapIds.has(gapRef), `${record.id ?? "record"} cites unknown gap ${gapRef}`);
      usedGaps.add(gapRef);
    }
  });
  assert.deepEqual(usedGaps, gapIds, "every gap must be reachable from curated content");
});

test("keeps all cross-document references valid", () => {
  const knownByKey = {
    owner_refs: new Set(core.owners.map((owner) => owner.id)),
    gap_refs: new Set(governance.gaps.map((gap) => gap.id)),
    traffic_plane_refs: new Set(core.traffic_model.planes.map((plane) => plane.id)),
    affected_capability_refs: new Set(capabilities.map((entry) => entry.id)),
    source_refs: new Set(horizon.watch_families.map((source) => source.id)),
  };
  visit(documents, (record) => {
    for (const [key, known] of Object.entries(knownByKey)) {
      if (!Array.isArray(record[key])) continue;
      for (const ref of record[key]) {
        assert.ok(known.has(ref), `${record.id ?? "record"} has unknown ${key} ${ref}`);
      }
    }
  });

  const systemPlaneIds = new Set(core.system_architecture.planes.map((plane) => plane.id));
  for (const edge of core.system_architecture.flow) {
    assert.ok(systemPlaneIds.has(edge.from));
    assert.ok(systemPlaneIds.has(edge.to));
  }
  const domainIds = new Set(core.domain_registry.map((domain) => domain.id));
  for (const domain of catalog.domains) {
    assert.equal(domain.entity_role, "reference");
    assert.ok(domainIds.has(domain.id));
  }
});

test("reconciles cached live counts to their code owners", async () => {
  const architectureSource = await readFile(
    new URL("cisco_toolkit/design_advisor.py", repositoryRoot),
    "utf8",
  );
  const architectureStart = architectureSource.indexOf("_ARCH_COVERAGE_REGISTRY = [");
  const architectureEnd = architectureSource.indexOf(
    "def compute_architecture_coverage",
    architectureStart,
  );
  assert.ok(architectureStart >= 0 && architectureEnd > architectureStart);
  const architectureBlock = architectureSource.slice(architectureStart, architectureEnd);
  const architectureRows = [
    ...architectureBlock.matchAll(
      /^\s*\("[^"]+",\s*"[^"]+",\s*"(?:ssh|json)",\s*\[(.*?)\]\),?\s*$/gm,
    ),
  ];
  const detectorCount = architectureRows.reduce(
    (count, row) => count + [...row[1].matchAll(/"[^"]+"/g)].length,
    0,
  );
  const architectureBaseline = core.current_baseline.find(
    (fact) => fact.id === "baseline.architecture.coverage",
  );
  assert.equal(architectureRows.length, architectureBaseline.value.classes);
  assert.equal(detectorCount, architectureBaseline.value.detectors);

  const explorerSource = await readFile(
    new URL("cisco_toolkit/blast_radius_explorer.html", repositoryRoot),
    "utf8",
  );
  const modeStart = explorerSource.indexOf("const MODES=[");
  const modeEnd = explorerSource.indexOf("const MODE_BY_KEY", modeStart);
  const liveModes = [
    ...explorerSource.slice(modeStart, modeEnd).matchAll(/\{key:"([^"]+)"/g),
  ].map((match) => match[1]);
  const modeBaseline = core.current_baseline.find(
    (fact) => fact.id === "baseline.explorer.modes",
  );
  assert.deepEqual(liveModes, modeBaseline.value);

  const docmetaSource = await readFile(
    new URL("cisco_toolkit/docmeta.py", repositoryRoot),
    "utf8",
  );
  const familyStart = docmetaSource.indexOf("FAMILY = (");
  const familyEnd = docmetaSource.indexOf("\n)\r\n", familyStart);
  assert.ok(familyStart >= 0 && familyEnd > familyStart);
  const familyKeys = [
    ...docmetaSource.slice(familyStart, familyEnd).matchAll(/^\s*\("([^"]+)"/gm),
  ].map((match) => match[1]);
  const cliStart = docmetaSource.indexOf("CLI_ARTIFACT_SUFFIX = {");
  const cliEnd = docmetaSource.indexOf("\n}\r\n", cliStart);
  assert.ok(cliStart >= 0 && cliEnd > cliStart);
  const cliKeys = [
    ...docmetaSource.slice(cliStart, cliEnd).matchAll(/^\s*"([^"]+)":/gm),
  ].map((match) => match[1]);
  const deliverableBaseline = core.current_baseline.find(
    (fact) => fact.id === "baseline.deliverables",
  );
  assert.equal(familyKeys.length, deliverableBaseline.value.family);
  assert.equal(cliKeys.length, deliverableBaseline.value.cli);
  assert.equal(familyKeys.length - cliKeys.length, deliverableBaseline.value.web_only);
});

test("keeps opportunity prioritization transparent and unblended", () => {
  const requiredAxes = [
    "user_value",
    "risk_reduction",
    "evidence_readiness",
    "strategic_reach",
    "implementation_effort",
    "operational_change_risk",
    "uncertainty",
  ];
  assert.match(governance.opportunity_portfolio.ranking_rule, /No hidden or aggregate score/i);
  for (const opportunity of governance.opportunity_portfolio.items) {
    assert.deepEqual(Object.keys(opportunity.axes).sort(), [...requiredAxes].sort());
    for (const value of Object.values(opportunity.axes)) {
      assert.ok(Number.isInteger(value) && value >= 1 && value <= 5);
    }
    assert.equal("score" in opportunity, false);
    assert.equal("rank" in opportunity, false);
    assert.equal("weighted_score" in opportunity, false);
    assert.ok(opportunity.axis_notes.length >= 30);
  }
});

test("keeps labs and external horizon content advisory-only", () => {
  for (const lab of governance.labs) {
    assert.equal(lab.content_role, "advisory");
    assert.equal(lab.mutates_assessment_truth, false);
    assert.ok(lab.does_not_prove.length >= 25);
  }
  assert.equal(horizon.content_role, "advisory");
  assert.equal(horizon.support_claim, "none");
  assert.equal(horizon.mutates_assessment_truth, false);
  assert.ok(horizon.watch_families.length >= 15);
  for (const source of horizon.watch_families) {
    assert.equal(source.content_role, "advisory");
    assert.match(source.source_url, /^https:\/\//);
    assert.match(source.engine_ingestion, /none|only through/i);
  }
  for (const entry of horizon.signals) {
    assert.equal(entry.content_role, "advisory");
    assert.equal(entry.support_claim, "none");
    assert.ok(horizon.maturity_levels.includes(entry.maturity));
    assert.ok(horizon.dispositions.includes(entry.disposition));
    assert.ok(entry.promotion_criteria.length >= 4);
    assert.ok(entry.next_review_rule.length > 0);
  }
  assert.ok(horizon.signals.some((entry) => entry.id === "horizon.unknown"));
  assert.match(horizon.promise, /never reports an industry-completeness percentage/i);
});

test("contains no raw-client or runtime-external-content mechanism", async () => {
  const [readme, indexSource] = await Promise.all([
    readFile(new URL("README.md", contentRoot), "utf8"),
    readFile(new URL("index.ts", contentRoot), "utf8"),
  ]);
  assert.match(readme, /client-free/i);
  assert.match(readme, /Do not add raw collections/i);
  assert.doesNotMatch(indexSource, /\bfetch\s*\(|XMLHttpRequest|WebSocket|localStorage|sessionStorage/);
  assert.equal(
    documents.some((document) => Object.hasOwn(document, "client_data")),
    false,
  );
});

test("uses one output contract for UI labels and deterministic release member names", () => {
  assert.equal(outputContract.members.length, 21);
  const members = outputContract.members.filter((item) => item.emission !== "external");
  assert.equal(new Set(members.map((item) => item.manifest_member)).size, members.length);
  assert.ok(members.every((item) => typeof item.manifest_member === "string" && item.manifest_member.length > 0));
  assert.ok(outputContract.members.some((item) => item.manifest_member === "master-reference.html"));
  assert.ok(outputContract.members.some((item) => item.manifest_member === "atlas-master-reference-offline.zip"));
  assert.ok(outputContract.members.some((item) => item.manifest_member === "master-reference.pdf"));
  assert.ok(outputContract.members.some((item) => item.manifest_member === "release-manifest.json"));
  assert.ok(outputContract.members.filter((item) => item.ui_surface).every((item) => item.label && item.gate));
});
