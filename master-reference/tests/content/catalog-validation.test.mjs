import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { access, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import test from "node:test";
import {
  CAPABILITY_STATES,
  capabilitySelectionUrl,
  filterCapabilityEntries,
  flattenCapabilityEntries,
} from "../../app/atlas/CapabilitySelection.mjs";

const execFileAsync = promisify(execFile);

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

function artifactRegistryRecords(source) {
  const normalized = source.replace(/\r\n?/g, "\n");
  const assignment = "ARTIFACT_SPECS = (";
  const registryStart = normalized.indexOf(assignment);
  const validatorStart = normalized.indexOf("\ndef validate_artifact_registry", registryStart);
  assert.ok(registryStart >= 0 && validatorStart > registryStart);
  const prefix = normalized.slice(registryStart, validatorStart);
  const registryEnd = prefix.lastIndexOf("\n)");
  assert.ok(registryEnd > assignment.length);
  const block = prefix.slice(assignment.length, registryEnd);
  const starts = [...block.matchAll(/^ {4}ArtifactSpec\(/gm)].map((match) => match.index);
  const records = starts.map((start, index) => block.slice(start, starts[index + 1] ?? block.length));
  assert.ok(records.length > 0, "ARTIFACT_SPECS unexpectedly contains no ArtifactSpec records");
  return records;
}

function artifactRegistryFacts(source) {
  const records = artifactRegistryRecords(source);
  return {
    lifecycle: records.length,
    pre_cutover: records.filter((record) => !/\bstage=POST_EXECUTION\b/.test(record)).length,
    engine_cli: records.filter((record) => /\bcli_suffix=/.test(record)).length,
    assesshub_only_pre_cutover: records.filter((record) =>
      /\bASSESSHUB_SNAPSHOT_PRODUCER\b/.test(record)
    ).length,
    conditional_post_execution: records.filter((record) =>
      /\bstage=POST_EXECUTION\b/.test(record) && /\bconditional=True\b/.test(record)
    ).length,
  };
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
    "domain.artifacts-deliverables": 18,
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
  assert.deepEqual(
    core.traffic_model.planes.map((plane) => plane.id),
    [
      "traffic.physical",
      "traffic.l2",
      "traffic.l3-underlay",
      "traffic.overlay-segmentation",
      "traffic.stateless-policy",
      "traffic.stateful-policy",
      "traffic.application-service",
      "traffic.measured-performance",
    ],
  );
  assert.equal(governance.labs.length, 14);
  assert.deepEqual(
    governance.labs.map((lab) => lab.number),
    Array.from({ length: 14 }, (_, index) => index + 1),
  );
  assert.deepEqual(
    governance.labs.map((lab) => lab.id),
    [
      "lab.01-evidence-to-artifact",
      "lab.02-claim-coverage-honesty",
      "lab.03-protocol-intelligence",
      "lab.04-traffic-flow-engines",
      "lab.05-topology-failure",
      "lab.06-enterprise-patterns",
      "lab.07-cutover-nrfu-pir",
      "lab.08-lifecycle-authority",
      "lab.09-custody-redaction-privacy",
      "lab.10-ssot-freshness",
      "lab.11-static-runtime-architecture",
      "lab.12-decision-voi",
      "lab.13-line-to-output",
      "lab.14-white-label-propagation",
    ],
  );
  const architectureLab = governance.labs.find(
    (lab) => lab.id === "lab.11-static-runtime-architecture",
  );
  assert.ok(architectureLab.owner_refs.includes("owner.operating.doctrine"));
  assert.match(architectureLab.does_not_prove, /incremental rebuild/i);
  assert.match(architectureLab.does_not_prove, /full Graphify rebuild/i);
});

test("keeps every mandated breadth denominator explicit", () => {
  const capabilityIds = new Set(capabilities.map((entry) => entry.id));
  const required = [
    "cap.architecture.assessment-mcp",
    "cap.protocol.discovery-endpoint-learning",
    "cap.protocol.static-routing",
    "cap.protocol.rip-ripng",
    "cap.protocol.pbr-route-policy",
    "cap.design.sda-catalyst-center",
    "cap.design.datacenter",
    "cap.design.vxlan-evpn",
    "cap.design.aci",
    "cap.design.service-provider-transport",
    "cap.design.ot-iot",
    "cap.design.automation-source-of-truth",
    "cap.design.sovereignty-residency",
    "cap.vendor.cisco-catalyst-center",
    "cap.vendor.f5",
    "cap.vendor.aruba-hpe",
    "cap.vendor.nokia",
    "cap.vendor.huawei",
    "cap.vendor.vmware-nsx",
    "cap.channel.netbox-nautobot",
    "cap.channel.openconfig",
    "cap.channel.kubernetes",
  ];
  for (const id of required) assert.ok(capabilityIds.has(id), `${id} missing from denominator`);

  const joined = required.map((id) => capabilities.find((entry) => entry.id === id)?.title).join(" ");
  for (const term of [
    "CDP", "LLDP", "ARP", "Static", "RIP", "Policy-based", "Catalyst Center",
    "VXLAN-EVPN", "ACI", "Service-provider", "OT", "source-of-truth", "Sovereignty",
    "F5", "Aruba", "HPE", "Nokia", "Huawei", "VMware", "NSX", "Nautobot", "OpenConfig", "Kubernetes",
  ]) {
    assert.match(joined, new RegExp(term, "i"), `${term} is not explicit in the closed denominator`);
  }
});

test("declares the complete typed digital thread with deterministic abstention", () => {
  const thread = core.digital_thread;
  assert.equal(thread.id, "thread.project-digital-thread");
  assert.match(thread.abstention_rule, /stop|abstain/i);
  assert.deepEqual(
    thread.stages.map((stage) => stage.id),
    [
      "thread.business-outcome",
      "thread.stakeholder-concern",
      "thread.requirement",
      "thread.architecture-decision",
      "thread.capability",
      "thread.input-evidence",
      "thread.collector-importer",
      "thread.parser-normalizer",
      "thread.snapshot-field",
      "thread.detector-analysis",
      "thread.fact-recommendation",
      "thread.design-plan",
      "thread.human-gate",
      "thread.gui-artifact",
      "thread.execution-validation",
      "thread.pir-outcome",
      "thread.learning",
    ],
  );
  assert.deepEqual(
    thread.stages.map((stage) => stage.order),
    Array.from({ length: 17 }, (_, index) => index + 1),
  );
  assert.deepEqual(
    thread.stages.map((stage) => stage.entity_type),
    [
      "OutcomeContract",
      "StakeholderConcern",
      "Requirement",
      "DecisionRecord",
      "CapabilityCell",
      "EvidenceRecord",
      "ReferenceEntity",
      "SymbolDossier",
      "ReferenceEntity",
      "SymbolDossier",
      "TypedClaim",
      "DecisionRecord",
      "VerificationReceipt",
      "ReferenceEntity",
      "VerificationReceipt",
      "DigitalThreadEvent",
      "DigitalThreadEvent",
    ],
  );
  for (const [index, stage] of thread.stages.entries()) {
    assert.ok(stage.question.length >= 20, `${stage.id} needs a useful trace question`);
    assert.ok(stage.abstention.length >= 30, `${stage.id} needs an explicit stop condition`);
    assert.ok(stage.owner_refs.length >= 1, `${stage.id} needs a live owner`);
    if (index < thread.stages.length - 1) {
      assert.ok(stage.relation_to_next, `${stage.id} needs a typed outgoing relation`);
    } else {
      assert.equal(stage.relation_to_next, null);
    }
  }
});

test("uses the catalog domain id in Atlas filtering and search context", async () => {
  const [typesSource, dataSource, explorerSource, selectionSource] = await Promise.all([
    readFile(new URL("master-reference/app/atlas/types.ts", repositoryRoot), "utf8"),
    readFile(new URL("master-reference/app/atlas/data.ts", repositoryRoot), "utf8"),
    readFile(new URL("master-reference/app/atlas/CapabilityExplorer.tsx", repositoryRoot), "utf8"),
    readFile(new URL("master-reference/app/atlas/CapabilitySelection.mjs", repositoryRoot), "utf8"),
  ]);
  assert.match(typesSource, /type CapabilityDomain = \{\s*id: string;/);
  assert.doesNotMatch(typesSource, /type CapabilityDomain = \{\s*domain_ref:/);
  assert.match(dataSource, /domain_id: domain\.id/);
  assert.doesNotMatch(dataSource, /domain_id: domain\.domain_ref/);
  assert.match(explorerSource, /flattenCapabilityEntries\(catalog\)/);
  assert.match(selectionSource, /domain: item\.id/);
  assert.doesNotMatch(explorerSource, /item\.domain_ref/);
  assert.doesNotMatch(selectionSource, /item\.domain_ref/);
});

test("executes the shipped capability-matrix contract against the canonical catalog", async () => {
  const explorerSource = await readFile(
    new URL("master-reference/app/atlas/CapabilityExplorer.tsx", repositoryRoot),
    "utf8",
  );
  for (const imported of [
    "CAPABILITY_STATES",
    "capabilitySelectionUrl",
    "filterCapabilityEntries",
    "flattenCapabilityEntries",
  ]) {
    assert.match(explorerSource, new RegExp(`\\b${imported}\\b`));
  }

  const rows = flattenCapabilityEntries(catalog);
  assert.equal(rows.length, capabilities.length);
  assert.deepEqual(new Set(CAPABILITY_STATES), supportStates);

  for (const domain of catalog.domains) {
    const selected = filterCapabilityEntries(rows, { domain: domain.id });
    assert.equal(selected.length, domain.entries.length, domain.id);
    assert.ok(selected.every((entry) => entry.domain === domain.id), domain.id);
  }
  for (const state of CAPABILITY_STATES) {
    const selected = filterCapabilityEntries(rows, { state });
    assert.ok(selected.length > 0, `${state} is not executable from the UI denominator`);
    assert.ok(selected.every((entry) => entry.state === state), state);
  }

  const target = capabilities.find((entry) => entry.id === "cap.vendor.cisco-ise");
  const searched = filterCapabilityEntries(rows, { query: target.id });
  assert.deepEqual(searched.map((entry) => entry.id), [target.id]);
  assert.equal(
    capabilitySelectionUrl({
      domain: target.domain_ref,
      state: target.state,
      query: "  Cisco ISE  ",
    }),
    `/capabilities?domain=${encodeURIComponent(target.domain_ref)}&state=${target.state}&q=Cisco+ISE`,
  );
  assert.equal(capabilitySelectionUrl(), "/capabilities");

  const masterReference = capabilities.find((entry) => entry.id === "cap.gui.master-reference");
  assert.equal(masterReference.state, "current");
  assert.ok(masterReference.owner_refs.includes("owner.reference.capability-ui"));
  const residual = governance.gaps.find((gap) => gap.id === "gap.catalog-ui");
  for (const shipped of ["static loading", "domain/state filters", "search", "owner provenance", "gap navigation", "accessible table", "URL-bound filters"]) {
    assert.match(residual.problem, new RegExp(shipped, "i"));
  }
  assert.match(residual.problem, /does not yet give every capability ID a stable dossier/i);
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

test("reports bounded Traffic Assurance without erasing stateful, live, or field gaps", () => {
  const owner = core.owners.find((record) => record.id === "owner.traffic.assurance");
  assert.equal(owner.path, "cisco_toolkit/traffic_assurance.py");
  for (const symbol of ["assess_flow", "assess_flows", "build_traffic_evidence_custody"]) {
    assert.match(owner.symbol, new RegExp(`\\b${symbol}\\b`));
  }
  for (const boundary of ["IPv4 TCP/UDP", "scoped RIB", "stateless interface ACL", "MTU", "ECMP", "current-run", "synthetic"]) {
    assert.match(owner.claim_scope, new RegExp(boundary, "i"));
  }
  for (const excluded of ["stateful session", "NAT", "live-traffic", "field-validation"]) {
    assert.match(owner.claim_scope, new RegExp(excluded, "i"));
  }

  const stateless = core.traffic_model.planes.find(
    (plane) => plane.id === "traffic.stateless-policy",
  );
  assert.equal(stateless.state, "partial");
  assert.ok(stateless.owner_refs.includes(owner.id));
  for (const supported of [
    "IPv4 TCP/UDP",
    "forward and return",
    "scoped RIB",
    "stateless interface ACL",
    "per-hop MTU",
    "ECMP",
    "scoped-route projection receipt",
  ]) {
    assert.match(stateless.current_scope, new RegExp(supported, "i"));
  }
  for (const gap of ["gap.flow-stateful", "gap.flow-actual-telemetry", "gap.vendor-lab-evidence"]) {
    assert.ok(stateless.gap_refs.includes(gap));
  }

  const stateful = core.traffic_model.planes.find(
    (plane) => plane.id === "traffic.stateful-policy",
  );
  assert.equal(stateful.state, "missing");
  for (const unsupported of ["firewall session state", "NAT/PAT", "runtime rule hits", "observed live traffic", "field-validated"]) {
    assert.match(stateful.current_scope, new RegExp(unsupported, "i"));
  }

  const capability = capabilities.find(
    (record) => record.id === "cap.traffic.acl-l4-simulation",
  );
  assert.equal(capability.state, "partial");
  assert.ok(capability.owner_refs.includes(owner.id));
  assert.match(capability.current_scope, /one canonical verdict/i);
  assert.match(capability.current_scope, /not stateful firewall\/session or NAT\/PAT/i);
  assert.match(capability.current_scope, /not .*observed live traffic.*field validation/i);

  const observedTraffic = capabilities.find(
    (record) => record.id === "cap.traffic.actual-flow-telemetry",
  );
  assert.equal(observedTraffic.state, "missing");
  assert.match(observedTraffic.current_scope, /Synthetic Traffic Assurance verdicts are not observed traffic/i);

  const statefulGap = governance.gaps.find((gap) => gap.id === "gap.flow-stateful");
  assert.match(statefulGap.problem, /requested forward and reverse scoped-RIB paths/i);
  for (const missing of ["firewall session state", "NAT/PAT", "observed packets/flows", "field behavior"]) {
    assert.match(statefulGap.problem, new RegExp(missing, "i"));
  }

  const lab = governance.labs.find((record) => record.id === "lab.04-traffic-flow-engines");
  assert.ok(lab.owner_refs.includes(owner.id));
  assert.match(lab.deterministic_definition.source_binding, /executable Traffic Assurance owner/i);
  assert.doesNotMatch(lab.deterministic_definition.source_binding, /no unified flow-engine executable/i);
  assert.match(lab.does_not_prove, /stateful session/i);
  assert.match(lab.does_not_prove, /field-validation/i);
});

test("documents current-run custody and post-redaction lookup-only Traffic Assurance", async () => {
  const [doctrine, ssot, mcpSource] = await Promise.all([
    readFile(new URL("CLAUDE.md", repositoryRoot), "utf8"),
    readFile(new URL("docs/ssot.md", repositoryRoot), "utf8"),
    readFile(new URL("cisco_toolkit/mcp_server.py", repositoryRoot), "utf8"),
  ]);
  const entrypoint = doctrine.split(/\r?\n/).find((line) =>
    line.includes("**Traffic Assurance (opt-in):**")
  );
  assert.ok(entrypoint, "CLAUDE.md lost the Traffic Assurance entrypoint");
  for (const contract of [
    "--traffic-intents",
    "traffic_assurance_set/1",
    "one global redaction transform",
    "MCP performs exact lookup only",
    "current-run marked custody",
    "scoped_route_projection/1",
    "JSON-loaded custody block is audit evidence only",
    "not observed traffic",
    "field validation",
  ]) {
    assert.match(entrypoint, new RegExp(contract, "i"));
  }

  const registryRow = ssot.split(/\r?\n/).find((line) =>
    line.includes("**Traffic Assurance result and evidence custody**")
  );
  assert.ok(registryRow, "docs/ssot.md lost the Traffic Assurance owner row");
  for (const contract of [
    "current-run custody marker",
    "scoped_route_projection/1",
    "Persisted custody and projection fields are audit evidence only",
    "JSON serialization intentionally destroys the trust marker",
    "one global redaction transform",
    "MCP performs an exact lookup",
    "No delivery surface recalculates assurance",
  ]) {
    assert.match(registryRow, new RegExp(contract, "i"));
  }

  const normalizedMcp = mcpSource.replace(/\r\n?/g, "\n");
  const mcpStart = normalizedMcp.indexOf("def assess_traffic(");
  const mcpEnd = normalizedMcp.indexOf("\n\n# name -> pure function", mcpStart);
  assert.ok(mcpStart >= 0 && mcpEnd > mcpStart);
  const mcpBlock = normalizedMcp.slice(mcpStart, mcpEnd);
  assert.match(mcpBlock, /precomputed Traffic Assurance result/i);
  assert.match(mcpBlock, /exact lookup/i);
  assert.doesNotMatch(mcpBlock, /traffic_assurance\.assess_flow\s*\(/);
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
  const artifactFacts = artifactRegistryFacts(docmetaSource);
  const crlfArtifactFacts = artifactRegistryFacts(
    docmetaSource.replace(/\r\n?|\n/g, "\r\n"),
  );
  assert.deepEqual(crlfArtifactFacts, artifactFacts, "ARTIFACT_SPECS derivation changed under CRLF");
  const lifecycleKeys = artifactRegistryRecords(docmetaSource).map((record) => {
    const match = record.match(/^ {4}ArtifactSpec\(\s*"([^"]+)"/s);
    assert.ok(match, "ARTIFACT_SPECS record lost its literal stable key");
    return match[1];
  });
  assert.equal(new Set(lifecycleKeys).size, lifecycleKeys.length);
  for (const key of lifecycleKeys) {
    const capability = capabilities.find((record) => record.id === `cap.artifact.${key}`);
    assert.ok(capability, `artifact lifecycle record ${key} has no catalog capability`);
    assert.equal(capability.state, "current");
    assert.ok(capability.owner_refs.includes("owner.deliverable.family"));
  }
  const pirCapability = capabilities.find((record) => record.id === "cap.artifact.pir");
  assert.match(pirCapability.current_scope, /conditional post-execution/i);
  assert.match(pirCapability.current_scope, /outside .*pre-cutover family.*engine CLI denominator/i);
  const deliverableBaseline = core.current_baseline.find(
    (fact) => fact.id === "baseline.deliverables",
  );
  assert.deepEqual(deliverableBaseline.value, artifactFacts);
  assert.equal(artifactFacts.lifecycle, artifactFacts.pre_cutover + artifactFacts.conditional_post_execution);
  assert.equal(
    artifactFacts.pre_cutover,
    artifactFacts.engine_cli + artifactFacts.assesshub_only_pre_cutover,
  );
  const deliverableOwner = core.owners.find((owner) => owner.id === "owner.deliverable.family");
  assert.match(deliverableOwner.symbol, /\bARTIFACT_SPECS\b/);
  assert.match(deliverableOwner.claim_scope, /thirteen-record artifact lifecycle/i);
  assert.match(deliverableOwner.claim_scope, /twelve pre-cutover/i);
  assert.match(deliverableOwner.claim_scope, /conditional post-execution PIR/i);
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
    assert.equal(lab.deterministic_definition.execution_state, "definition_only");
    assert.ok(lab.deterministic_definition.deterministic_inputs.length >= 2);
    assert.ok(lab.deterministic_definition.expected_observations.length >= 2);
    assert.ok(lab.deterministic_definition.reset_rule.length >= 25);
    assert.match(lab.deterministic_definition.source_binding, /tracked|exact-tree|owner/i);
    assert.ok(lab.gap_refs.includes("gap.training-labs"));
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

test("gives every invariant an auditable formal contract with tracked enforcement and tests", async () => {
  const { stdout } = await execFileAsync("git", ["ls-files", "-z"], {
    cwd: fileURLToPath(repositoryRoot),
    encoding: "utf8",
  });
  const tracked = new Set(stdout.split("\0").filter(Boolean).map((path) => path.replaceAll("\\", "/")));
  const requiredFields = [
    "formal_rule",
    "scope",
    "enforcement_points",
    "supporting_tests",
    "counterexample_test",
    "exceptions_allowed",
    "residual_risk",
    "independent_verifier",
  ];
  assert.ok(governance.invariants.length >= 20);
  for (const invariant of governance.invariants) {
    for (const field of requiredFields) {
      assert.ok(Object.hasOwn(invariant, field), `${invariant.id} missing ${field}`);
    }
    assert.ok(invariant.formal_rule.length >= 40);
    assert.ok(invariant.scope.length >= 2);
    assert.ok(invariant.enforcement_points.length >= 1);
    assert.ok(invariant.supporting_tests.length >= 1);
    assert.ok(Array.isArray(invariant.exceptions_allowed));
    assert.ok(invariant.residual_risk.length >= 30);
    assert.ok(invariant.independent_verifier.length >= 10);
    for (const path of [
      ...invariant.enforcement_points,
      ...invariant.supporting_tests,
      invariant.counterexample_test,
    ]) {
      assert.ok(tracked.has(path), `${invariant.id} cites untracked path ${path}`);
    }
  }
});

test("renders rejected and revoked governance branches", async () => {
  const source = await readFile(new URL("master-reference/app/exports/page.tsx", repositoryRoot), "utf8");
  assert.match(source, /state: "REJECTED"/);
  assert.match(source, /state: "REVOKED"/);
  assert.match(source, /Rejected and revoked lifecycle branches/i);
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
  assert.deepEqual(
    outputContract.members.map((item) => item.id),
    [
      "output.private-site",
      "output.reference-json",
      "output.owner-handbook",
      "output.engineering-dossier",
      "output.source-index-json",
      "output.source-index-markdown",
      "output.capability-gap",
      "output.decisions-opportunities",
      "output.enhancement-brief",
      "output.agent-pack",
      "output.sbom",
      "output.executive-html",
      "output.pdf-gate",
      "output.pdf",
      "output.provenance",
      "output.offline-zip",
      "output.preservation",
      "output.preservation-coverage",
      "output.artifact-inventory",
      "output.family-attestation",
      "output.release-manifest",
    ],
    "the canonical output denominator changed without an explicit contract update",
  );
  const members = outputContract.members.filter((item) => item.emission !== "external");
  assert.equal(new Set(members.map((item) => item.manifest_member)).size, members.length);
  assert.ok(members.every((item) => typeof item.manifest_member === "string" && item.manifest_member.length > 0));
  assert.ok(outputContract.members.some((item) => item.manifest_member === "master-reference.html"));
  assert.ok(outputContract.members.some((item) => item.manifest_member === "atlas-master-reference-offline.zip"));
  assert.ok(outputContract.members.some((item) => item.manifest_member === "master-reference.pdf"));
  assert.ok(outputContract.members.some((item) => item.manifest_member === "release-manifest.json"));
  assert.ok(outputContract.members.filter((item) => item.ui_surface).every((item) => item.label && item.gate));
});

test("gives every canonical output a complete artifact dossier and tracked writer", async () => {
  const { stdout } = await execFileAsync("git", ["ls-files", "-z"], {
    cwd: fileURLToPath(repositoryRoot),
    encoding: "utf8",
  });
  const tracked = new Set(stdout.split("\0").filter(Boolean).map((path) => path.replaceAll("\\", "/")));
  const outputIds = new Set(outputContract.members.map((item) => item.id));
  const requiredFields = [
    "audience",
    "decision_supported",
    "inputs",
    "owner_refs",
    "producing_writer",
    "gate_behavior",
    "redaction",
    "cross_artifact_ids",
    "validation",
    "distribution_inclusion",
    "safe_sample_status",
    "human_owned_evidence",
    "limitations",
  ];
  const safeSampleStates = new Set(["generated-preview", "synthetic-template", "not-provided"]);
  const writerStates = new Set(["current", "conditional", "external"]);

  for (const item of outputContract.members) {
    assert.ok(item.dossier, `${item.id} has no artifact dossier`);
    for (const field of requiredFields) {
      assert.ok(Object.hasOwn(item.dossier, field), `${item.id} dossier missing ${field}`);
    }
    for (const field of [
      "audience",
      "inputs",
      "owner_refs",
      "cross_artifact_ids",
      "validation",
      "human_owned_evidence",
      "limitations",
    ]) {
      assert.ok(Array.isArray(item.dossier[field]) && item.dossier[field].length > 0, `${item.id} needs nonempty ${field}`);
    }
    assert.ok(item.dossier.decision_supported.length >= 30);
    assert.ok(item.dossier.gate_behavior.length >= 30);
    assert.ok(item.dossier.redaction.length >= 20);
    assert.ok(item.dossier.distribution_inclusion.length >= 20);
    assert.ok(safeSampleStates.has(item.dossier.safe_sample_status));
    assert.ok(writerStates.has(item.dossier.producing_writer.state));
    for (const ref of item.dossier.cross_artifact_ids) {
      assert.ok(outputIds.has(ref), `${item.id} cites unknown output ${ref}`);
    }
    if (item.dossier.producing_writer.state === "external") {
      assert.equal(item.dossier.producing_writer.path, null);
      assert.equal(item.dossier.producing_writer.symbol, null);
    } else {
      assert.ok(tracked.has(item.dossier.producing_writer.path), `${item.id} cites untracked writer ${item.dossier.producing_writer.path}`);
      assert.ok(item.dossier.producing_writer.symbol?.length > 0, `${item.id} needs a writer symbol`);
      const writerSource = await readFile(
        new URL(item.dossier.producing_writer.path, repositoryRoot),
        "utf8",
      );
      for (const symbol of item.dossier.producing_writer.symbol.split("/").map((value) => value.trim())) {
        assert.ok(writerSource.includes(`def ${symbol}(`), `${item.id} cites missing writer symbol ${symbol}`);
      }
    }
  }
});
