import type {
  Capability,
  CapabilityCatalog,
  CapabilityDomain,
  CapabilityEntryContract,
  CapabilityState,
} from "./types";

const CAPABILITY_STATES = [
  "current",
  "partial",
  "missing",
  "gated",
  "excluded",
  "unknown",
] as const satisfies readonly CapabilityState[];

const EXPECTED_DOMAIN_COUNT = 12;
const EXPECTED_ENTRY_COUNT = 212;
const EXPECTED_SEMANTIC_RECORD_COUNT = 226;
const ADVISORY_ENTRY_ID = "cap.engine.training-curriculum";

const ROOT_KEYS = [
  "schema_version",
  "id",
  "catalog_version",
  "kind",
  "denominator_rule",
  "entry_contract",
  "domains",
] as const;

const ENTRY_CONTRACT_KEYS = [
  "current",
  "partial",
  "incomplete",
  "catalog_presence",
] as const;

const DOMAIN_KEYS = ["id", "entity_role", "entries"] as const;
const ENTRY_KEYS = ["id", "title", "state", "current_scope"] as const;
const ENTRY_OPTIONAL_KEYS = [
  "owner_refs",
  "gap_refs",
  "traffic_plane_refs",
  "content_role",
  "mutates_assessment_truth",
] as const;

type CapabilityObservationValue = string | boolean;

export type CapabilityRenderedObservation = {
  rule_id: "capability.entry";
  record_identity: string;
  facet_path: "state" | "current_scope";
  disposition: "rendered_derived" | "rendered_identity";
  slot_id: string;
  transform_id: "state-mark-label" | "identity-text";
  observed_value: string;
};

export type CapabilitySafetyObservation = {
  rule_id: "capability.root" | "capability.entry_contract" | "capability.entry";
  record_identity: string;
  boundary_field:
    | "denominator_rule"
    | "current"
    | "partial"
    | "incomplete"
    | "catalog_presence"
    | "content_role"
    | "mutates_assessment_truth";
  observed_value: CapabilityObservationValue;
  slot_id: string;
  transform_id: "visible-source-contract-text";
};

export type CapabilityObservationEnvelope = {
  rendered_observations: readonly CapabilityRenderedObservation[];
  safety_observations: readonly CapabilitySafetyObservation[];
};

export type CapabilityReferenceRegistry = {
  domain_ids: readonly string[];
  owner_ids: readonly string[];
  gap_ids: readonly string[];
  traffic_plane_ids: readonly string[];
};

export type CapabilityCatalogViewModel = CapabilityObservationEnvelope & {
  catalog: CapabilityCatalog;
  semantic_record_count: 226;
};

function fail(_path: string, _reason: string): never {
  throw new TypeError("Invalid capability catalog.");
}

function record(value: unknown, path: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    fail(path, "expected an object");
  }
  const item = value as Record<string, unknown>;
  const prototype = Object.getPrototypeOf(item);
  const ownKeys = Reflect.ownKeys(item);
  const descriptors = Object.getOwnPropertyDescriptors(item);
  if (
    (prototype !== Object.prototype && prototype !== null) ||
    ownKeys.some((key) => typeof key !== "string") ||
    Object.values(descriptors).some(
      (descriptor) =>
        descriptor.get !== undefined ||
        descriptor.set !== undefined ||
        descriptor.enumerable !== true,
    )
  ) {
    fail(path, "expected a plain JSON object");
  }
  if (Object.keys(item).length > 32) fail(path, "object is over the field bound");
  return item;
}

function exactKeys(
  value: Record<string, unknown>,
  required: readonly string[],
  path: string,
  optional: readonly string[] = [],
): void {
  const allowed = new Set([...required, ...optional]);
  if (
    required.some((key) => !Object.hasOwn(value, key)) ||
    Object.keys(value).some((key) => !allowed.has(key))
  ) {
    fail(path, "exact shape mismatch");
  }
}

function nonemptyString(value: unknown, path: string): string {
  if (typeof value !== "string" || value.trim().length === 0 || value.length > 4_096) {
    fail(path, "expected a bounded non-empty string");
  }
  return value;
}

function identifier(value: unknown, path: string, prefix: string): string {
  const id = nonemptyString(value, path);
  if (
    !id.startsWith(prefix) ||
    !/^[a-z0-9]+(?:[.-][a-z0-9]+(?:-[a-z0-9]+)*)+$/.test(id) ||
    id.length > 160
  ) {
    fail(path, "expected a bounded semantic identifier");
  }
  return id;
}

function literalString<const T extends string>(value: unknown, expected: T, path: string): T {
  if (value !== expected) fail(path, "unexpected literal");
  return expected;
}

function enumValue<const T extends string>(
  value: unknown,
  allowed: readonly T[],
  path: string,
): T {
  if (typeof value !== "string" || !(allowed as readonly string[]).includes(value)) {
    fail(path, "unexpected enum value");
  }
  return value as T;
}

function plainArray(value: unknown, path: string, maximum: number): unknown[] {
  if (!Array.isArray(value)) fail(path, "expected a bounded plain JSON array");
  const ownKeys = Reflect.ownKeys(value);
  const descriptors = Object.getOwnPropertyDescriptors(value);
  if (
    Object.getPrototypeOf(value) !== Array.prototype ||
    ownKeys.some((key) => typeof key !== "string") ||
    ownKeys.length !== value.length + 1 ||
    !Object.hasOwn(value, "length") ||
    !Array.from({ length: value.length }, (_, index) => String(index)).every((key) =>
      Object.hasOwn(value, key),
    ) ||
    Object.entries(descriptors).some(
      ([key, descriptor]) =>
        key !== "length" &&
        (descriptor.enumerable !== true ||
          descriptor.get !== undefined ||
          descriptor.set !== undefined),
    ) ||
    Object.values(descriptors).some(
      (descriptor) => descriptor.get !== undefined || descriptor.set !== undefined,
    ) ||
    value.length > maximum
  ) {
    fail(path, "expected a bounded plain JSON array");
  }
  return value;
}

function referenceArray(value: unknown, path: string, prefix: string): string[] {
  const values = plainArray(value, path, 64).map((item, index) =>
    identifier(item, `${path}[${index}]`, prefix),
  );
  if (new Set(values).size !== values.length) fail(path, "duplicate reference");
  return values;
}

function optionalReferenceArray(
  item: Record<string, unknown>,
  field: "owner_refs" | "gap_refs" | "traffic_plane_refs",
  path: string,
  prefix: string,
): string[] | undefined {
  return Object.hasOwn(item, field)
    ? referenceArray(item[field], `${path}.${field}`, prefix)
    : undefined;
}

function catalogDate(value: unknown, path: string): string {
  const version = nonemptyString(value, path);
  if (!/^\d{4}\.\d{2}\.\d{2}$/.test(version)) fail(path, "expected a catalog date");
  const date = version.replaceAll(".", "-");
  const parsed = new Date(`${date}T00:00:00Z`);
  if (Number.isNaN(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== date) {
    fail(path, "expected a catalog date");
  }
  return version;
}

function entryContract(value: unknown, path: string): CapabilityEntryContract {
  const item = record(value, path);
  exactKeys(item, ENTRY_CONTRACT_KEYS, path);
  return {
    current: nonemptyString(item.current, `${path}.current`),
    partial: nonemptyString(item.partial, `${path}.partial`),
    incomplete: nonemptyString(item.incomplete, `${path}.incomplete`),
    catalog_presence: nonemptyString(item.catalog_presence, `${path}.catalog_presence`),
  };
}

function capabilityEntry(value: unknown, path: string): Capability {
  const item = record(value, path);
  exactKeys(item, ENTRY_KEYS, path, ENTRY_OPTIONAL_KEYS);
  const id = identifier(item.id, `${path}.id`, "cap.");
  const state = enumValue(item.state, CAPABILITY_STATES, `${path}.state`);
  const ownerRefs = optionalReferenceArray(item, "owner_refs", path, "owner.");
  const gapRefs = optionalReferenceArray(item, "gap_refs", path, "gap.");
  const trafficPlaneRefs = optionalReferenceArray(item, "traffic_plane_refs", path, "traffic.");

  if (["current", "partial"].includes(state) && !ownerRefs?.length) {
    fail(path, "implemented states require an owner reference");
  }
  if (state !== "current" && !gapRefs?.length) {
    fail(path, "incomplete states require a gap reference");
  }
  if (state === "current" && gapRefs?.length) {
    fail(path, "current state cannot carry a gap disposition");
  }

  const hasContentRole = Object.hasOwn(item, "content_role");
  const hasMutationBoundary = Object.hasOwn(item, "mutates_assessment_truth");
  if (id === ADVISORY_ENTRY_ID) {
    if (!hasContentRole || !hasMutationBoundary) {
      fail(path, "advisory entry boundary is incomplete");
    }
  } else if (hasContentRole || hasMutationBoundary) {
    fail(path, "unexpected entry-local advisory boundary");
  }

  const contentRole = hasContentRole
    ? literalString(item.content_role, "advisory", `${path}.content_role`)
    : undefined;
  const mutatesAssessmentTruth = hasMutationBoundary
    ? item.mutates_assessment_truth === false
      ? false
      : fail(`${path}.mutates_assessment_truth`, "expected false")
    : undefined;

  return {
    id,
    title: nonemptyString(item.title, `${path}.title`),
    state,
    current_scope: nonemptyString(item.current_scope, `${path}.current_scope`),
    ...(ownerRefs === undefined ? {} : { owner_refs: ownerRefs }),
    ...(gapRefs === undefined ? {} : { gap_refs: gapRefs }),
    ...(trafficPlaneRefs === undefined ? {} : { traffic_plane_refs: trafficPlaneRefs }),
    ...(contentRole === undefined ? {} : { content_role: contentRole }),
    ...(mutatesAssessmentTruth === undefined
      ? {}
      : { mutates_assessment_truth: mutatesAssessmentTruth }),
  };
}

function capabilityDomain(value: unknown, path: string): CapabilityDomain {
  const item = record(value, path);
  exactKeys(item, DOMAIN_KEYS, path);
  const rawEntries = plainArray(item.entries, `${path}.entries`, 64);
  if (rawEntries.length === 0) fail(`${path}.entries`, "expected a non-empty domain");
  return {
    id: identifier(item.id, `${path}.id`, "domain."),
    entity_role: literalString(item.entity_role, "reference", `${path}.entity_role`),
    entries: rawEntries.map((entry, index) =>
      capabilityEntry(entry, `${path}.entries[${index}]`),
    ),
  };
}

function referenceSets(value: unknown): {
  domains: ReadonlySet<string>;
  owners: ReadonlySet<string>;
  gaps: ReadonlySet<string>;
  trafficPlanes: ReadonlySet<string>;
} {
  const item = record(value, "$references");
  exactKeys(
    item,
    ["domain_ids", "owner_ids", "gap_ids", "traffic_plane_ids"],
    "$references",
  );
  const collect = (field: string, prefix: string, maximum: number): ReadonlySet<string> => {
    const values = plainArray(item[field], `$references.${field}`, maximum).map(
      (entry, index) => identifier(entry, `$references.${field}[${index}]`, prefix),
    );
    if (values.length === 0 || new Set(values).size !== values.length) {
      fail(`$references.${field}`, "empty or duplicate registry");
    }
    return new Set(values);
  };
  return {
    domains: collect("domain_ids", "domain.", 64),
    owners: collect("owner_ids", "owner.", 256),
    gaps: collect("gap_ids", "gap.", 256),
    trafficPlanes: collect("traffic_plane_ids", "traffic.", 32),
  };
}

function validateCapabilityCatalogUnsafe(
  value: unknown,
  references: CapabilityReferenceRegistry,
): CapabilityCatalog {
  const resolvedReferences = referenceSets(references);
  const root = record(value, "$");
  exactKeys(root, ROOT_KEYS, "$");
  const schemaVersion = literalString(root.schema_version, "1.0.0", "$.schema_version");
  const catalogVersion = catalogDate(root.catalog_version, "$.catalog_version");
  const rootId = identifier(root.id, "$.id", "atlas.capability-catalog.");
  if (rootId !== `atlas.capability-catalog.${catalogVersion.replaceAll(".", "-")}`) {
    fail("$.id", "root identity does not bind the catalog version");
  }

  const rawDomains = plainArray(root.domains, "$.domains", EXPECTED_DOMAIN_COUNT);
  if (rawDomains.length !== EXPECTED_DOMAIN_COUNT) fail("$.domains", "domain denominator mismatch");
  const domains = rawDomains.map((domain, index) =>
    capabilityDomain(domain, `$.domains[${index}]`),
  );
  if (new Set(domains.map((domain) => domain.id)).size !== domains.length) {
    fail("$.domains", "duplicate domain identity");
  }
  if (domains.some((domain) => !resolvedReferences.domains.has(domain.id))) {
    fail("$.domains", "unresolved domain reference");
  }

  const entries = domains.flatMap((domain) => domain.entries);
  if (
    entries.length !== EXPECTED_ENTRY_COUNT ||
    new Set(entries.map((entry) => entry.id)).size !== EXPECTED_ENTRY_COUNT
  ) {
    fail("$.domains", "entry denominator mismatch");
  }
  if (new Set(entries.map((entry) => entry.state)).size !== CAPABILITY_STATES.length) {
    fail("$.domains", "support-state vocabulary is not fully represented");
  }
  for (const entry of entries) {
    if (entry.owner_refs?.some((reference) => !resolvedReferences.owners.has(reference))) {
      fail("$.domains", "unresolved owner reference");
    }
    if (entry.gap_refs?.some((reference) => !resolvedReferences.gaps.has(reference))) {
      fail("$.domains", "unresolved gap reference");
    }
    if (
      entry.traffic_plane_refs?.some(
        (reference) => !resolvedReferences.trafficPlanes.has(reference),
      )
    ) {
      fail("$.domains", "unresolved traffic-plane reference");
    }
  }
  const semanticRecordCount = 1 + 1 + domains.length + entries.length;
  if (semanticRecordCount !== EXPECTED_SEMANTIC_RECORD_COUNT) {
    fail("$", "semantic record denominator mismatch");
  }

  return {
    schema_version: schemaVersion,
    id: rootId,
    catalog_version: catalogVersion,
    kind: literalString(
      root.kind,
      "closed-world-capability-catalog",
      "$.kind",
    ),
    denominator_rule: nonemptyString(root.denominator_rule, "$.denominator_rule"),
    entry_contract: entryContract(root.entry_contract, "$.entry_contract"),
    domains,
  };
}

export function validateCapabilityCatalog(
  value: unknown,
  references: CapabilityReferenceRegistry,
): CapabilityCatalog {
  try {
    return validateCapabilityCatalogUnsafe(value, references);
  } catch (error) {
    if (error instanceof TypeError && error.message === "Invalid capability catalog.") {
      throw error;
    }
    return fail("$", "unexpected non-JSON input");
  }
}

export function capabilityEntrySlotId(
  recordIdentity: string,
  field: "state" | "current_scope",
): string {
  return `web.capabilities.capability.entry.${recordIdentity}.${field}`;
}

export function capabilitySafetySlotId(
  ruleId: CapabilitySafetyObservation["rule_id"],
  recordIdentity: string,
  field: CapabilitySafetyObservation["boundary_field"],
): string {
  return `web.capabilities.${ruleId}.${recordIdentity}.${field}`;
}

export function isCapabilityLineageActive(
  lineageDefaultView: boolean,
  pristineRuntime: boolean,
  domain: string,
  state: string,
  query: string,
): boolean {
  return (
    lineageDefaultView &&
    pristineRuntime &&
    domain === "all" &&
    state === "all" &&
    query === ""
  );
}

function renderedObservationsFor(
  catalog: CapabilityCatalog,
): CapabilityRenderedObservation[] {
  return catalog.domains.flatMap((domain) =>
    domain.entries.flatMap((entry) => [
      {
        rule_id: "capability.entry" as const,
        record_identity: entry.id,
        facet_path: "state" as const,
        disposition: "rendered_derived" as const,
        slot_id: capabilityEntrySlotId(entry.id, "state"),
        transform_id: "state-mark-label" as const,
        observed_value: entry.state,
      },
      {
        rule_id: "capability.entry" as const,
        record_identity: entry.id,
        facet_path: "current_scope" as const,
        disposition: "rendered_identity" as const,
        slot_id: capabilityEntrySlotId(entry.id, "current_scope"),
        transform_id: "identity-text" as const,
        observed_value: entry.current_scope,
      },
    ]),
  );
}

function safetyObservation(
  ruleId: CapabilitySafetyObservation["rule_id"],
  recordIdentity: string,
  field: CapabilitySafetyObservation["boundary_field"],
  value: CapabilityObservationValue,
): CapabilitySafetyObservation {
  return {
    rule_id: ruleId,
    record_identity: recordIdentity,
    boundary_field: field,
    observed_value: value,
    slot_id: capabilitySafetySlotId(ruleId, recordIdentity, field),
    transform_id: "visible-source-contract-text",
  };
}

function observationsForValidatedCatalog(
  catalog: CapabilityCatalog,
): CapabilityObservationEnvelope {
  const advisoryEntry = catalog.domains
    .flatMap((domain) => domain.entries)
    .find((entry) => entry.id === ADVISORY_ENTRY_ID);
  if (
    !advisoryEntry ||
    advisoryEntry.content_role === undefined ||
    advisoryEntry.mutates_assessment_truth === undefined
  ) {
    fail("$.domains", "advisory entry boundary is absent");
  }

  return {
    rendered_observations: renderedObservationsFor(catalog),
    safety_observations: [
      safetyObservation(
        "capability.root",
        "@root",
        "denominator_rule",
        catalog.denominator_rule,
      ),
      ...ENTRY_CONTRACT_KEYS.map((field) =>
        safetyObservation(
          "capability.entry_contract",
          "@root",
          field,
          catalog.entry_contract[field],
        ),
      ),
      safetyObservation(
        "capability.entry",
        advisoryEntry.id,
        "content_role",
        advisoryEntry.content_role,
      ),
      safetyObservation(
        "capability.entry",
        advisoryEntry.id,
        "mutates_assessment_truth",
        advisoryEntry.mutates_assessment_truth,
      ),
    ],
  };
}

export function buildCapabilityCatalogSinkObservations(
  value: unknown,
  references: CapabilityReferenceRegistry,
): CapabilityObservationEnvelope {
  return observationsForValidatedCatalog(validateCapabilityCatalog(value, references));
}

export function buildCapabilityCatalogViewModel(
  value: unknown,
  references: CapabilityReferenceRegistry,
): CapabilityCatalogViewModel {
  const catalog = validateCapabilityCatalog(value, references);
  return {
    catalog,
    semantic_record_count: EXPECTED_SEMANTIC_RECORD_COUNT,
    ...observationsForValidatedCatalog(catalog),
  };
}
