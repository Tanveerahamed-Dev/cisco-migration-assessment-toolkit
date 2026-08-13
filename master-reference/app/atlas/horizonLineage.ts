import type {
  HorizonCadence,
  HorizonDisposition,
  HorizonIntakeStep,
  HorizonMaturity,
  HorizonMetric,
  HorizonModel,
  HorizonReviewTrigger,
  HorizonSignal,
  HorizonView,
  HorizonWatchFamily,
} from "./types";

const MATURITY_LEVELS = [
  "research",
  "draft",
  "standardized",
  "shipping",
  "observed-in-estate",
  "mainstream",
  "unknown",
] as const satisfies readonly HorizonMaturity[];

const DISPOSITIONS = [
  "adopt-candidate",
  "watch",
  "defer",
  "reject",
  "out-of-scope",
  "unknown",
] as const satisfies readonly HorizonDisposition[];

const EXPECTED_RECORD_COUNTS = {
  intake_pipeline: 8,
  review_triggers: 7,
  metrics: 9,
  ui_views: 5,
  watch_families: 18,
  signals: 16,
} as const;

const ROOT_KEYS = [
  "schema_version",
  "id",
  "catalog_version",
  "kind",
  "content_role",
  "support_claim",
  "mutates_assessment_truth",
  "promise",
  "separation_contract",
  "maturity_levels",
  "dispositions",
  "intake_pipeline",
  "review_triggers",
  "cadence",
  "metrics",
  "ui_views",
  "watch_families",
  "signals",
] as const;

const WATCH_KEYS = [
  "id",
  "name",
  "source_url",
  "authority_scope",
  "topics",
  "review_cadence",
  "content_role",
  "engine_ingestion",
] as const;

const SIGNAL_KEYS = [
  "id",
  "theme",
  "title",
  "first_seen",
  "last_reviewed",
  "maturity",
  "disposition",
  "source_refs",
  "adoption_evidence",
  "affected_capability_refs",
  "business_relevance",
  "risk_opportunity",
  "current_coverage",
  "uncertainty",
  "rationale",
  "owner_role",
  "next_review_rule",
  "promotion_criteria",
  "privacy_trust_implications",
  "content_role",
  "support_claim",
] as const;

type HorizonObservationValue = string | boolean | readonly string[];

export type HorizonRenderedObservation = {
  rule_id: string;
  record_identity: string;
  facet_path: string;
  disposition:
    | "rendered_identity"
    | "rendered_labeled"
    | "rendered_ordered_array"
    | "rendered_derived";
  slot_id: string;
  transform_id: string;
  observed_value: HorizonObservationValue;
};

export type HorizonSafetyObservation = {
  rule_id: string;
  record_identity: string;
  boundary_field: "content_role" | "support_claim" | "mutates_assessment_truth";
  observed_value: string | boolean;
  slot_id: string;
  transform_id: string;
};

export type HorizonGapsObservationEnvelope = {
  rendered_observations: readonly HorizonRenderedObservation[];
  safety_observations: readonly HorizonSafetyObservation[];
};

export type HorizonGapsViewModel = HorizonGapsObservationEnvelope & {
  horizon: HorizonModel;
  safetyBoundary: {
    contentRole: "advisory";
    supportClaim: "none";
    mutatesAssessmentTruth: false;
  };
};

function fail(_path: string, _reason: string): never {
  throw new TypeError("Invalid open horizon register.");
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
      (descriptor) => descriptor.get !== undefined || descriptor.set !== undefined,
    )
  ) {
    fail(path, "expected a plain JSON object");
  }
  if (Object.keys(item).length > 64) fail(path, "object is over the field bound");
  return item;
}

function exactKeys(
  value: Record<string, unknown>,
  required: readonly string[],
  path: string,
  optional: readonly string[] = [],
): void {
  const allowed = new Set([...required, ...optional]);
  const missing = required.filter((key) => !Object.hasOwn(value, key));
  const extra = Object.keys(value).filter((key) => !allowed.has(key));
  if (missing.length > 0 || extra.length > 0) {
    fail(
      path,
      `exact shape mismatch (missing: ${missing.join(", ") || "none"}; extra: ${extra.join(", ") || "none"})`,
    );
  }
}

function nonemptyString(value: unknown, path: string): string {
  if (typeof value !== "string" || value.trim().length === 0 || value.length > 4_096) {
    fail(path, "expected a non-empty string");
  }
  return value;
}

function identifier(value: unknown, path: string): string {
  const id = nonemptyString(value, path);
  if (!/^[a-z0-9]+(?:[.-][a-z0-9]+(?:-[a-z0-9]+)*)+$/.test(id)) {
    fail(path, "expected a bounded semantic identifier");
  }
  return id;
}

function literalString<const T extends string>(value: unknown, expected: T, path: string): T {
  if (value !== expected) fail(path, `expected ${JSON.stringify(expected)}`);
  return expected;
}

function stringArray(
  value: unknown,
  path: string,
  options: { allowEmpty?: boolean; unique?: boolean } = {},
): string[] {
  if (
    !Array.isArray(value) ||
    Object.getPrototypeOf(value) !== Array.prototype ||
    Reflect.ownKeys(value).some((key) => typeof key !== "string") ||
    Object.values(Object.getOwnPropertyDescriptors(value)).some(
      (descriptor) => descriptor.get !== undefined || descriptor.set !== undefined,
    )
  ) {
    fail(path, "expected a plain JSON array");
  }
  if (value.length > 64) fail(path, "array is over the item bound");
  if (!options.allowEmpty && value.length === 0) fail(path, "expected a non-empty array");
  const items = value.map((item, index) => nonemptyString(item, `${path}[${index}]`));
  if (options.unique && new Set(items).size !== items.length) {
    fail(path, "expected unique values");
  }
  return items;
}

function objectArray(value: unknown, path: string): Record<string, unknown>[] {
  if (
    !Array.isArray(value) ||
    Object.getPrototypeOf(value) !== Array.prototype ||
    Reflect.ownKeys(value).some((key) => typeof key !== "string") ||
    Object.values(Object.getOwnPropertyDescriptors(value)).some(
      (descriptor) => descriptor.get !== undefined || descriptor.set !== undefined,
    ) ||
    value.length === 0 ||
    value.length > 64
  ) {
    fail(path, "expected a bounded non-empty array");
  }
  return value.map((item, index) => record(item, `${path}[${index}]`));
}

function positiveInteger(value: unknown, path: string): number {
  if (!Number.isSafeInteger(value) || Number(value) < 1) fail(path, "expected a positive integer");
  return Number(value);
}

function isoDate(value: unknown, path: string): string {
  const date = nonemptyString(value, path);
  const parsed = new Date(`${date}T00:00:00Z`);
  if (
    !/^\d{4}-\d{2}-\d{2}$/.test(date) ||
    Number.isNaN(parsed.valueOf()) ||
    parsed.toISOString().slice(0, 10) !== date
  ) {
    fail(path, "expected an ISO calendar date");
  }
  return date;
}

function catalogDate(value: unknown, path: string): string {
  const version = nonemptyString(value, path);
  if (!/^\d{4}\.\d{2}\.\d{2}$/.test(version)) fail(path, "expected a catalog date");
  isoDate(version.replaceAll(".", "-"), path);
  return version;
}

function httpsUrl(value: unknown, path: string): string {
  const source = nonemptyString(value, path);
  let parsed: URL;
  try {
    parsed = new URL(source);
  } catch {
    fail(path, "expected an absolute HTTPS URL");
  }
  if (parsed.protocol !== "https:" || parsed.username || parsed.password) {
    fail(path, "expected an uncredentialed HTTPS URL");
  }
  return source;
}

function enumValue<const T extends string>(
  value: unknown,
  allowed: readonly T[],
  path: string,
): T {
  if (typeof value !== "string" || !(allowed as readonly string[]).includes(value)) {
    fail(path, `expected one of ${allowed.join(", ")}`);
  }
  return value as T;
}

function requireUniqueIds(records: readonly { id: string }[], path: string): void {
  const ids = records.map((item) => item.id);
  if (new Set(ids).size !== ids.length) fail(path, "duplicate record id");
}

function intakeStep(value: unknown, path: string): HorizonIntakeStep {
  const item = record(value, path);
  exactKeys(item, ["id", "order", "action"], path);
  return {
    id: identifier(item.id, `${path}.id`),
    order: positiveInteger(item.order, `${path}.order`),
    action: nonemptyString(item.action, `${path}.action`),
  };
}

function reviewTrigger(value: unknown, path: string): HorizonReviewTrigger {
  const item = record(value, path);
  exactKeys(item, ["id", "event"], path);
  return {
    id: identifier(item.id, `${path}.id`),
    event: nonemptyString(item.event, `${path}.event`),
  };
}

function cadence(value: unknown, path: string): HorizonCadence {
  const item = record(value, path);
  const keys = ["scheduled", "event_driven", "staleness_rule", "independent_challenge"] as const;
  exactKeys(item, keys, path);
  return {
    scheduled: nonemptyString(item.scheduled, `${path}.scheduled`),
    event_driven: nonemptyString(item.event_driven, `${path}.event_driven`),
    staleness_rule: nonemptyString(item.staleness_rule, `${path}.staleness_rule`),
    independent_challenge: nonemptyString(
      item.independent_challenge,
      `${path}.independent_challenge`,
    ),
  };
}

function metric(value: unknown, path: string): HorizonMetric {
  const item = record(value, path);
  exactKeys(item, ["id", "definition", "target", "warning"], path);
  return {
    id: identifier(item.id, `${path}.id`),
    definition: nonemptyString(item.definition, `${path}.definition`),
    target: nonemptyString(item.target, `${path}.target`),
    warning: nonemptyString(item.warning, `${path}.warning`),
  };
}

function horizonView(value: unknown, path: string): HorizonView {
  const item = record(value, path);
  exactKeys(item, ["id", "label", "shows"], path);
  return {
    id: identifier(item.id, `${path}.id`),
    label: nonemptyString(item.label, `${path}.label`),
    shows: nonemptyString(item.shows, `${path}.shows`),
  };
}

function watchFamily(value: unknown, path: string): HorizonWatchFamily {
  const item = record(value, path);
  exactKeys(item, WATCH_KEYS, path, ["additional_urls"]);
  const additionalUrls = Object.hasOwn(item, "additional_urls")
    ? stringArray(item.additional_urls, `${path}.additional_urls`, { unique: true }).map((url, index) =>
        httpsUrl(url, `${path}.additional_urls[${index}]`),
      )
    : undefined;
  return {
    id: identifier(item.id, `${path}.id`),
    name: nonemptyString(item.name, `${path}.name`),
    source_url: httpsUrl(item.source_url, `${path}.source_url`),
    ...(additionalUrls ? { additional_urls: additionalUrls } : {}),
    authority_scope: nonemptyString(item.authority_scope, `${path}.authority_scope`),
    topics: stringArray(item.topics, `${path}.topics`, { unique: true }),
    review_cadence: nonemptyString(item.review_cadence, `${path}.review_cadence`),
    content_role: literalString(item.content_role, "advisory", `${path}.content_role`),
    engine_ingestion: nonemptyString(item.engine_ingestion, `${path}.engine_ingestion`),
  };
}

function signal(value: unknown, path: string): HorizonSignal {
  const item = record(value, path);
  exactKeys(item, SIGNAL_KEYS, path);
  return {
    id: identifier(item.id, `${path}.id`),
    theme: nonemptyString(item.theme, `${path}.theme`),
    title: nonemptyString(item.title, `${path}.title`),
    first_seen: isoDate(item.first_seen, `${path}.first_seen`),
    last_reviewed: isoDate(item.last_reviewed, `${path}.last_reviewed`),
    maturity: enumValue(item.maturity, MATURITY_LEVELS, `${path}.maturity`),
    disposition: enumValue(item.disposition, DISPOSITIONS, `${path}.disposition`),
    source_refs: stringArray(item.source_refs, `${path}.source_refs`, {
      allowEmpty: true,
      unique: true,
    }).map((sourceRef, index) => identifier(sourceRef, `${path}.source_refs[${index}]`)),
    adoption_evidence: nonemptyString(item.adoption_evidence, `${path}.adoption_evidence`),
    affected_capability_refs: stringArray(
      item.affected_capability_refs,
      `${path}.affected_capability_refs`,
      { unique: true },
    ).map((capabilityRef, index) =>
      identifier(capabilityRef, `${path}.affected_capability_refs[${index}]`),
    ),
    business_relevance: nonemptyString(item.business_relevance, `${path}.business_relevance`),
    risk_opportunity: nonemptyString(item.risk_opportunity, `${path}.risk_opportunity`),
    current_coverage: nonemptyString(item.current_coverage, `${path}.current_coverage`),
    uncertainty: nonemptyString(item.uncertainty, `${path}.uncertainty`),
    rationale: nonemptyString(item.rationale, `${path}.rationale`),
    owner_role: nonemptyString(item.owner_role, `${path}.owner_role`),
    next_review_rule: nonemptyString(item.next_review_rule, `${path}.next_review_rule`),
    promotion_criteria: stringArray(item.promotion_criteria, `${path}.promotion_criteria`),
    privacy_trust_implications: nonemptyString(
      item.privacy_trust_implications,
      `${path}.privacy_trust_implications`,
    ),
    content_role: literalString(item.content_role, "advisory", `${path}.content_role`),
    support_claim: literalString(item.support_claim, "none", `${path}.support_claim`),
  };
}

function validateHorizonModelUnsafe(value: unknown): HorizonModel {
  const root = record(value, "$");
  exactKeys(root, ROOT_KEYS, "$");
  const schemaVersion = literalString(root.schema_version, "1.0.0", "$.schema_version");
  const catalogVersion = catalogDate(root.catalog_version, "$.catalog_version");
  const rootId = identifier(root.id, "$.id");
  if (rootId !== `atlas.open-horizon-register.${catalogVersion.replaceAll(".", "-")}`) {
    fail("$.id", "root identity does not bind the catalog version");
  }
  const kind = literalString(root.kind, "open-world-horizon-register", "$.kind");
  const contentRole = literalString(root.content_role, "advisory", "$.content_role");
  const supportClaim = literalString(root.support_claim, "none", "$.support_claim");
  const mutatesAssessmentTruth =
    root.mutates_assessment_truth === false
      ? false
      : fail("$.mutates_assessment_truth", "expected false");

  const maturityLevels = stringArray(root.maturity_levels, "$.maturity_levels", { unique: true });
  if (JSON.stringify(maturityLevels) !== JSON.stringify(MATURITY_LEVELS)) {
    fail("$.maturity_levels", "unexpected or reordered maturity vocabulary");
  }
  const dispositions = stringArray(root.dispositions, "$.dispositions", { unique: true });
  if (JSON.stringify(dispositions) !== JSON.stringify(DISPOSITIONS)) {
    fail("$.dispositions", "unexpected or reordered disposition vocabulary");
  }

  const intakePipeline = objectArray(root.intake_pipeline, "$.intake_pipeline").map((item, index) =>
    intakeStep(item, `$.intake_pipeline[${index}]`),
  );
  if (!intakePipeline.every((item, index) => item.order === index + 1)) {
    fail("$.intake_pipeline", "steps must retain one-based source order");
  }
  const reviewTriggers = objectArray(root.review_triggers, "$.review_triggers").map((item, index) =>
    reviewTrigger(item, `$.review_triggers[${index}]`),
  );
  const metrics = objectArray(root.metrics, "$.metrics").map((item, index) =>
    metric(item, `$.metrics[${index}]`),
  );
  const uiViews = objectArray(root.ui_views, "$.ui_views").map((item, index) =>
    horizonView(item, `$.ui_views[${index}]`),
  );
  const watchFamilies = objectArray(root.watch_families, "$.watch_families").map((item, index) =>
    watchFamily(item, `$.watch_families[${index}]`),
  );
  const signals = objectArray(root.signals, "$.signals").map((item, index) =>
    signal(item, `$.signals[${index}]`),
  );

  for (const [path, records, expectedCount] of [
    ["$.intake_pipeline", intakePipeline, EXPECTED_RECORD_COUNTS.intake_pipeline],
    ["$.review_triggers", reviewTriggers, EXPECTED_RECORD_COUNTS.review_triggers],
    ["$.metrics", metrics, EXPECTED_RECORD_COUNTS.metrics],
    ["$.ui_views", uiViews, EXPECTED_RECORD_COUNTS.ui_views],
    ["$.watch_families", watchFamilies, EXPECTED_RECORD_COUNTS.watch_families],
    ["$.signals", signals, EXPECTED_RECORD_COUNTS.signals],
  ] as const) {
    if (records.length !== expectedCount) fail(path, "record denominator mismatch");
    requireUniqueIds(records, path);
  }

  const watchIds = new Set(watchFamilies.map((item) => item.id));
  for (const item of signals) {
    if (item.last_reviewed < item.first_seen) {
      fail(`$.signals.${item.id}.last_reviewed`, "review date precedes first-seen date");
    }
    const isUnknown = item.id === "horizon.unknown";
    if (isUnknown !== (item.source_refs.length === 0)) {
      fail(`$.signals.${item.id}.source_refs`, "only horizon.unknown may have no source family");
    }
    if (isUnknown && (item.maturity !== "unknown" || item.disposition !== "unknown")) {
      fail(`$.signals.${item.id}`, "the permanent unknown record must remain unknown");
    }
    for (const sourceRef of item.source_refs) {
      if (!watchIds.has(sourceRef)) {
        fail(`$.signals.${item.id}.source_refs`, `unknown watch-family reference ${sourceRef}`);
      }
    }
  }
  if (signals.filter((item) => item.id === "horizon.unknown").length !== 1) {
    fail("$.signals", "requires exactly one permanent horizon.unknown record");
  }

  return {
    schema_version: schemaVersion,
    id: rootId,
    catalog_version: catalogVersion,
    kind,
    content_role: contentRole,
    support_claim: supportClaim,
    mutates_assessment_truth: mutatesAssessmentTruth,
    promise: nonemptyString(root.promise, "$.promise"),
    separation_contract: stringArray(root.separation_contract, "$.separation_contract"),
    maturity_levels: maturityLevels as HorizonMaturity[],
    dispositions: dispositions as HorizonDisposition[],
    intake_pipeline: intakePipeline,
    review_triggers: reviewTriggers,
    cadence: cadence(root.cadence, "$.cadence"),
    metrics,
    ui_views: uiViews,
    watch_families: watchFamilies,
    signals,
  };
}

export function validateHorizonModel(value: unknown): HorizonModel {
  try {
    return validateHorizonModelUnsafe(value);
  } catch (error) {
    if (error instanceof TypeError && error.message === "Invalid open horizon register.") {
      throw error;
    }
    return fail("$", "unexpected non-JSON input");
  }
}

function rendered(
  ruleId: string,
  recordIdentity: string,
  facetPath: string,
  disposition: HorizonRenderedObservation["disposition"],
  slotId: string,
  transformId: string,
  observedValue: HorizonObservationValue,
): HorizonRenderedObservation {
  return {
    rule_id: ruleId,
    record_identity: recordIdentity,
    facet_path: facetPath,
    disposition,
    slot_id: slotId,
    transform_id: transformId,
    observed_value: observedValue,
  };
}

function safety(
  ruleId: string,
  recordIdentity: string,
  boundaryField: HorizonSafetyObservation["boundary_field"],
  observedValue: string | boolean,
  slotId: string,
  transformId: string,
): HorizonSafetyObservation {
  return {
    rule_id: ruleId,
    record_identity: recordIdentity,
    boundary_field: boundaryField,
    observed_value: observedValue,
    slot_id: slotId,
    transform_id: transformId,
  };
}

function observationsForValidatedHorizon(
  horizon: HorizonModel,
): HorizonGapsObservationEnvelope {
  const renderedObservations: HorizonRenderedObservation[] = [
    rendered(
      "horizon.root",
      "@root",
      "promise",
      "rendered_identity",
      "web.gaps.horizon.heading.promise",
      "identity-text",
      horizon.promise,
    ),
  ];
  for (const item of horizon.watch_families) {
    const prefix = `web.gaps.horizon.watch.${item.id}`;
    renderedObservations.push(
      rendered(
        "horizon.watch_family",
        item.id,
        "authority_scope",
        "rendered_identity",
        `${prefix}.authority-scope`,
        "identity-text",
        item.authority_scope,
      ),
      rendered(
        "horizon.watch_family",
        item.id,
        "review_cadence",
        "rendered_labeled",
        `${prefix}.review-cadence`,
        "labeled-text",
        item.review_cadence,
      ),
      rendered(
        "horizon.watch_family",
        item.id,
        "engine_ingestion",
        "rendered_labeled",
        `${prefix}.engine-ingestion`,
        "labeled-text",
        item.engine_ingestion,
      ),
    );
  }

  const signalFields = [
    ["maturity", "maturity", "rendered_identity", "identity-text"],
    ["disposition", "disposition", "rendered_derived", "state-mark-label"],
    ["business_relevance", "business-relevance", "rendered_labeled", "labeled-text"],
    ["current_coverage", "current-coverage", "rendered_identity", "identity-text"],
    ["uncertainty", "uncertainty", "rendered_labeled", "labeled-text"],
    ["next_review_rule", "next-review-rule", "rendered_labeled", "labeled-text"],
    [
      "promotion_criteria",
      "promotion-criteria",
      "rendered_ordered_array",
      "ordered-list-items",
    ],
  ] as const;
  for (const item of horizon.signals) {
    const prefix = `web.gaps.horizon.signal.${item.id}`;
    for (const [field, slotSuffix, disposition, transformId] of signalFields) {
      renderedObservations.push(
        rendered(
          "horizon.signal",
          item.id,
          field,
          disposition,
          `${prefix}.${slotSuffix}`,
          transformId,
          item[field],
        ),
      );
    }
  }

  const safetyObservations: HorizonSafetyObservation[] = [
    safety(
      "horizon.root",
      "@root",
      "content_role",
      horizon.content_role,
      "web.gaps.horizon.safety.content-role",
      "validated-uniform-boundary-summary",
    ),
    safety(
      "horizon.root",
      "@root",
      "support_claim",
      horizon.support_claim,
      "web.gaps.horizon.safety.support-claim",
      "validated-uniform-boundary-summary",
    ),
    safety(
      "horizon.root",
      "@root",
      "mutates_assessment_truth",
      horizon.mutates_assessment_truth,
      "web.gaps.horizon.safety.truth-mutation",
      "validated-uniform-boundary-summary",
    ),
  ];
  for (const item of horizon.watch_families) {
    safetyObservations.push(
      safety(
        "horizon.watch_family",
        item.id,
        "content_role",
        item.content_role,
        "web.gaps.horizon.safety.content-role",
        "validated-uniform-boundary-summary",
      ),
    );
  }
  for (const item of horizon.signals) {
    safetyObservations.push(
      safety(
        "horizon.signal",
        item.id,
        "content_role",
        item.content_role,
        "web.gaps.horizon.safety.content-role",
        "validated-uniform-boundary-summary",
      ),
      safety(
        "horizon.signal",
        item.id,
        "support_claim",
        item.support_claim,
        "web.gaps.horizon.safety.support-claim",
        "validated-uniform-boundary-summary",
      ),
    );
  }

  return {
    rendered_observations: renderedObservations,
    safety_observations: safetyObservations,
  };
}

export function buildHorizonGapsSinkObservations(value: unknown): HorizonGapsObservationEnvelope {
  return observationsForValidatedHorizon(validateHorizonModel(value));
}

export function buildHorizonGapsViewModel(value: unknown): HorizonGapsViewModel {
  const horizon = validateHorizonModel(value);
  return {
    horizon,
    safetyBoundary: {
      contentRole: horizon.content_role,
      supportClaim: horizon.support_claim,
      mutatesAssessmentTruth: horizon.mutates_assessment_truth,
    },
    ...observationsForValidatedHorizon(horizon),
  };
}
