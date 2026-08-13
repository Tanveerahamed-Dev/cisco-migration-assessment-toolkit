import type {
  CapabilityState,
  CoreBaselineValue,
  CoreModel,
  CoreOutcome,
  OwnerRef,
} from "./types";

const CORE_STATES = [
  "current",
  "partial",
  "missing",
  "gated",
  "excluded",
  "unknown",
] as const satisfies readonly CapabilityState[];

const EXPECTED_SEMANTIC_RECORD_COUNT = 135;
const EXPECTED_OUTCOME_COUNT = 9;
const MAX_PORTABLE_INTEGER = 9_007_199_254_740_991;
const MAX_JSON_DEPTH = 64;
const MAX_JSON_VALUES = 1_000_000;
const MAX_JSON_CONTAINER_ITEMS = 100_000;
const MAX_JSON_STRING_LENGTH = 1_048_576;
const MAX_REFERENCE_ITEMS = 1_000;
const MAX_REFERENCE_LENGTH = 1_024;
const CORE_SCHEMA_VERSION = "1.0.0";
const CORE_ROOT_ID = "atlas.core.2026-08-07";
const NONBLANK = /[^\u0020\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/u;
const MEANINGFUL_TEXT = /[^\p{White_Space}\p{M}]/u;
const DEFAULT_IGNORABLE = /\p{Default_Ignorable_Code_Point}/u;
const FORMAT_CONTROL = /\p{Cf}/u;

const ROOT_KEYS = [
  "schema_version",
  "id",
  "catalog_version",
  "title",
  "as_of",
  "scope",
  "truth_contract",
  "controlled_states",
  "owners",
  "current_baseline",
  "outcomes",
  "maturity_model",
  "current_maturity",
  "non_goals",
  "lifecycle_stages",
  "digital_thread",
  "system_architecture",
  "traffic_model",
  "domain_registry",
] as const;

const TRUTH_CONTRACT_KEYS = [
  "declared_scope_promise",
  "open_world_promise",
  "support_rule",
  "partial_rule",
  "training_rule",
  "client_data_rule",
] as const;

export type CoreRenderedObservation = {
  rule_id: "core.outcome";
  record_identity: string;
  facet_path: "success_signal";
  disposition: "rendered_identity";
  slot_id: string;
  transform_id: "identity-text";
  observed_value: string;
};

export type CoreOutcomeObservationEnvelope = {
  rendered_observations: readonly CoreRenderedObservation[];
  safety_observations: readonly [];
};

export type CoreReferenceRegistry = {
  gap_ids: readonly string[];
};

export type CoreOutcomeViewModel = CoreOutcomeObservationEnvelope & {
  core: CoreModel;
  semantic_record_count: 135;
};

function fail(_path: string, _reason: string): never {
  throw new TypeError("Invalid Atlas Core contract.");
}

function portableString(value: string): boolean {
  if (value.length > MAX_JSON_STRING_LENGTH) return false;
  for (const character of value) {
    const point = character.codePointAt(0) ?? 0;
    if (
      point <= 0x1f ||
      (point >= 0x7f && point <= 0x9f) ||
      (point >= 0xd800 && point <= 0xdfff) ||
      (point >= 0xfdd0 && point <= 0xfdef) ||
      (point & 0xffff) >= 0xfffe ||
      point === 0x2800 ||
      FORMAT_CONTROL.test(character) ||
      DEFAULT_IGNORABLE.test(character)
    ) {
      return false;
    }
  }
  return true;
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
    prototype !== Object.prototype ||
    ownKeys.length > MAX_JSON_CONTAINER_ITEMS ||
    ownKeys.some((key) => typeof key !== "string" || !portableString(key)) ||
    Object.values(descriptors).some(
      (descriptor) =>
        descriptor.get !== undefined ||
        descriptor.set !== undefined ||
        descriptor.enumerable !== true ||
        descriptor.configurable !== true ||
        descriptor.writable !== true,
    )
  ) {
    fail(path, "expected a bounded plain JSON object");
  }
  return item;
}

function exactKeys(
  value: Record<string, unknown>,
  required: readonly string[],
  path: string,
  optional: readonly string[] = [],
): void {
  const keys = Object.keys(value);
  const allowed = new Set([...required, ...optional]);
  if (
    required.some((key) => !Object.hasOwn(value, key)) ||
    keys.some((key) => !allowed.has(key))
  ) {
    fail(path, "exact shape mismatch");
  }
}

function plainArray(value: unknown, path: string, maximum: number): unknown[] {
  if (!Array.isArray(value) || value.length > maximum) {
    fail(path, "expected a bounded plain JSON array");
  }
  const ownKeys = Reflect.ownKeys(value);
  const descriptors = Object.getOwnPropertyDescriptors(value) as Record<
    string,
    PropertyDescriptor
  >;
  const lengthDescriptor = descriptors.length;
  if (
    Object.getPrototypeOf(value) !== Array.prototype ||
    ownKeys.some((key) => typeof key !== "string") ||
    ownKeys.length !== value.length + 1 ||
    !lengthDescriptor ||
    lengthDescriptor.get !== undefined ||
    lengthDescriptor.set !== undefined ||
    lengthDescriptor.enumerable !== false ||
    lengthDescriptor.configurable !== false ||
    lengthDescriptor.writable !== true ||
    !Array.from({ length: value.length }, (_, index) => String(index)).every((key) => {
      const descriptor = descriptors[key];
      return (
        descriptor !== undefined &&
        descriptor.get === undefined &&
        descriptor.set === undefined &&
        descriptor.enumerable === true &&
        descriptor.configurable === true &&
        descriptor.writable === true
      );
    })
  ) {
    fail(path, "expected a bounded plain JSON array");
  }
  return value;
}

function validatePlainJsonTree(value: unknown): void {
  const stack: Array<[unknown, number]> = [[value, 1]];
  let values = 0;
  while (stack.length > 0) {
    const [current, depth] = stack.pop() ?? fail("$", "invalid JSON traversal");
    values += 1;
    if (values > MAX_JSON_VALUES || depth > MAX_JSON_DEPTH) {
      fail("$", "JSON structure exceeds its bound");
    }
    if (Array.isArray(current)) {
      const items = plainArray(current, "$", MAX_JSON_CONTAINER_ITEMS);
      for (const item of items) stack.push([item, depth + 1]);
    } else if (current !== null && typeof current === "object") {
      const item = record(current, "$");
      for (const member of Object.values(item)) stack.push([member, depth + 1]);
    } else if (typeof current === "string") {
      if (!portableString(current)) fail("$", "non-portable JSON string");
    } else if (typeof current === "number") {
      if (!Number.isSafeInteger(current)) fail("$", "non-portable JSON number");
    } else if (
      current !== null &&
      typeof current !== "boolean"
    ) {
      fail("$", "unexpected JSON scalar");
    }
  }
}

function nonemptyString(value: unknown, path: string): string {
  if (
    typeof value !== "string" ||
    !NONBLANK.test(value) ||
    !MEANINGFUL_TEXT.test(value) ||
    !portableString(value)
  ) {
    fail(path, "expected a bounded portable non-empty string");
  }
  return value;
}

function identifier(value: unknown, path: string, prefix: string): string {
  const id = nonemptyString(value, path);
  if (
    id.length > 160 ||
    !id.startsWith(prefix) ||
    !/^[a-z0-9]+(?:[.-][a-z0-9]+(?:-[a-z0-9]+)*)+$/.test(id)
  ) {
    fail(path, "expected a bounded semantic identifier");
  }
  return id;
}

function calendarDate(
  value: unknown,
  path: string,
  separator: "-" | ".",
): string {
  const date = nonemptyString(value, path);
  const escapedSeparator = separator === "." ? "\\." : separator;
  const match = new RegExp(
    `^(\\d{4})${escapedSeparator}(\\d{2})${escapedSeparator}(\\d{2})$`,
  ).exec(date);
  if (!match) fail(path, "expected a calendar date");
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const instant = new Date(Date.UTC(year, month - 1, day));
  if (
    instant.getUTCFullYear() !== year ||
    instant.getUTCMonth() !== month - 1 ||
    instant.getUTCDate() !== day
  ) {
    fail(path, "expected a real calendar date");
  }
  return date;
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

function portableInteger(value: unknown, path: string, minimum: number, maximum: number): number {
  if (
    typeof value !== "number" ||
    !Number.isSafeInteger(value) ||
    value < minimum ||
    value > maximum
  ) {
    fail(path, "expected a bounded portable integer");
  }
  return value;
}

function stringArray(
  value: unknown,
  path: string,
  maximum: number,
  allowEmpty = false,
): string[] {
  const values = plainArray(value, path, maximum).map((item, index) =>
    nonemptyString(item, `${path}[${index}]`),
  );
  if (!allowEmpty && values.length === 0) fail(path, "expected a non-empty array");
  return values;
}

function referenceArray(
  value: unknown,
  path: string,
  prefix: string,
  allowEmpty = false,
): string[] {
  const values = plainArray(value, path, MAX_REFERENCE_ITEMS).map((item, index) =>
    identifier(item, `${path}[${index}]`, prefix),
  );
  if (
    (!allowEmpty && values.length === 0) ||
    values.some((item) => item.length > MAX_REFERENCE_LENGTH) ||
    new Set(values).size !== values.length
  ) {
    fail(path, "empty or duplicate reference array");
  }
  return values;
}

function optionalReferenceArray(
  item: Record<string, unknown>,
  field: "owner_refs" | "gap_refs",
  path: string,
  prefix: string,
  allowEmpty = false,
): string[] | undefined {
  return Object.hasOwn(item, field)
    ? referenceArray(item[field], `${path}.${field}`, prefix, allowEmpty)
    : undefined;
}

function assertUniqueIds(records: readonly { id: string }[], path: string): void {
  if (new Set(records.map((item) => item.id)).size !== records.length) {
    fail(path, "duplicate semantic identity");
  }
}

function baselineValue(value: unknown, path: string): CoreBaselineValue {
  if (typeof value === "string") return nonemptyString(value, path);
  if (Array.isArray(value)) return stringArray(value, path, MAX_JSON_CONTAINER_ITEMS);
  const item = record(value, path);
  const keys = Object.keys(item);
  if (
    keys.length === 0 ||
    keys.some((key) => !NONBLANK.test(key) || !MEANINGFUL_TEXT.test(key))
  ) {
    fail(path, "expected a non-empty baseline value");
  }
  const resolved: Record<string, string | number | string[]> = {};
  for (const key of keys) {
    const entry = item[key];
    if (typeof entry === "string") resolved[key] = nonemptyString(entry, `${path}.${key}`);
    else if (typeof entry === "number") {
      resolved[key] = portableInteger(entry, `${path}.${key}`, -MAX_PORTABLE_INTEGER, MAX_PORTABLE_INTEGER);
    } else if (Array.isArray(entry)) {
      resolved[key] = stringArray(entry, `${path}.${key}`, MAX_JSON_CONTAINER_ITEMS);
    }
    else fail(`${path}.${key}`, "unexpected baseline value member");
  }
  return resolved;
}

function truthContract(value: unknown, path: string): CoreModel["truth_contract"] {
  const item = record(value, path);
  exactKeys(item, TRUTH_CONTRACT_KEYS, path);
  return {
    declared_scope_promise: nonemptyString(item.declared_scope_promise, `${path}.declared_scope_promise`),
    open_world_promise: nonemptyString(item.open_world_promise, `${path}.open_world_promise`),
    support_rule: nonemptyString(item.support_rule, `${path}.support_rule`),
    partial_rule: nonemptyString(item.partial_rule, `${path}.partial_rule`),
    training_rule: nonemptyString(item.training_rule, `${path}.training_rule`),
    client_data_rule: nonemptyString(item.client_data_rule, `${path}.client_data_rule`),
  };
}

function controlledStates(value: unknown, path: string): CoreModel["controlled_states"] {
  const rows = plainArray(value, path, 6);
  if (rows.length !== 6) fail(path, "controlled-state denominator mismatch");
  const resolved = rows.map((value, index) => {
    const rowPath = `${path}[${index}]`;
    const item = record(value, rowPath);
    exactKeys(item, ["id", "value", "meaning"], rowPath);
    return {
      id: identifier(item.id, `${rowPath}.id`, "state."),
      value: enumValue(item.value, CORE_STATES, `${rowPath}.value`),
      meaning: nonemptyString(item.meaning, `${rowPath}.meaning`),
    };
  });
  assertUniqueIds(resolved, path);
  if (new Set(resolved.map((item) => item.value)).size !== resolved.length) {
    fail(path, "duplicate controlled-state value");
  }
  return resolved;
}

function owners(value: unknown, path: string): OwnerRef[] {
  const rows = plainArray(value, path, 29);
  if (rows.length !== 29) fail(path, "owner denominator mismatch");
  const resolved = rows.map((value, index) => {
    const rowPath = `${path}[${index}]`;
    const item = record(value, rowPath);
    exactKeys(item, ["id", "path", "kind", "claim_scope"], rowPath, ["symbol"]);
    return {
      id: identifier(item.id, `${rowPath}.id`, "owner."),
      path: nonemptyString(item.path, `${rowPath}.path`),
      ...(Object.hasOwn(item, "symbol")
        ? { symbol: nonemptyString(item.symbol, `${rowPath}.symbol`) }
        : {}),
      kind: nonemptyString(item.kind, `${rowPath}.kind`),
      claim_scope: nonemptyString(item.claim_scope, `${rowPath}.claim_scope`),
    };
  });
  assertUniqueIds(resolved, path);
  return resolved;
}

function currentBaseline(value: unknown, path: string): CoreModel["current_baseline"] {
  const rows = plainArray(value, path, 6);
  if (rows.length !== 6) fail(path, "baseline denominator mismatch");
  const resolved = rows.map((value, index) => {
    const rowPath = `${path}[${index}]`;
    const item = record(value, rowPath);
    exactKeys(item, ["id", "statement", "value", "owner_refs"], rowPath);
    return {
      id: identifier(item.id, `${rowPath}.id`, "baseline."),
      statement: nonemptyString(item.statement, `${rowPath}.statement`),
      value: baselineValue(item.value, `${rowPath}.value`),
      owner_refs: referenceArray(item.owner_refs, `${rowPath}.owner_refs`, "owner."),
    };
  });
  assertUniqueIds(resolved, path);
  return resolved;
}

function outcomes(value: unknown, path: string): CoreOutcome[] {
  const rows = plainArray(value, path, EXPECTED_OUTCOME_COUNT);
  if (rows.length !== EXPECTED_OUTCOME_COUNT) fail(path, "outcome denominator mismatch");
  const resolved = rows.map((value, index) => {
    const rowPath = `${path}[${index}]`;
    const item = record(value, rowPath);
    exactKeys(item, ["id", "title", "success_signal"], rowPath);
    return {
      id: identifier(item.id, `${rowPath}.id`, "outcome."),
      title: nonemptyString(item.title, `${rowPath}.title`),
      success_signal: nonemptyString(item.success_signal, `${rowPath}.success_signal`),
    };
  });
  assertUniqueIds(resolved, path);
  return resolved;
}

function maturityModel(value: unknown, path: string): CoreModel["maturity_model"] {
  const rows = plainArray(value, path, 7);
  if (rows.length !== 7) fail(path, "maturity-model denominator mismatch");
  const resolved = rows.map((value, index) => {
    const rowPath = `${path}[${index}]`;
    const item = record(value, rowPath);
    exactKeys(item, ["id", "level", "label", "exit_criteria"], rowPath);
    return {
      id: identifier(item.id, `${rowPath}.id`, "maturity."),
      level: portableInteger(item.level, `${rowPath}.level`, 0, 6),
      label: nonemptyString(item.label, `${rowPath}.label`),
      exit_criteria: nonemptyString(item.exit_criteria, `${rowPath}.exit_criteria`),
    };
  });
  assertUniqueIds(resolved, path);
  if (new Set(resolved.map((item) => item.level)).size !== resolved.length) {
    fail(path, "duplicate maturity level");
  }
  return resolved;
}

function currentMaturity(value: unknown, path: string): CoreModel["current_maturity"] {
  const rows = plainArray(value, path, 6);
  if (rows.length !== 6) fail(path, "current-maturity denominator mismatch");
  const resolved = rows.map((value, index) => {
    const rowPath = `${path}[${index}]`;
    const item = record(value, rowPath);
    exactKeys(
      item,
      ["id", "dimension", "level", "state", "basis", "owner_refs"],
      rowPath,
      ["gap_refs"],
    );
    const state = enumValue(item.state, CORE_STATES, `${rowPath}.state`);
    const gapRefs = optionalReferenceArray(item, "gap_refs", rowPath, "gap.", true);
    if (state === "current" ? gapRefs?.length : !gapRefs?.length) {
      fail(rowPath, "maturity state and gap disposition disagree");
    }
    return {
      id: identifier(item.id, `${rowPath}.id`, "maturity.current."),
      dimension: nonemptyString(item.dimension, `${rowPath}.dimension`),
      level: portableInteger(item.level, `${rowPath}.level`, 0, 6),
      state,
      basis: nonemptyString(item.basis, `${rowPath}.basis`),
      owner_refs: referenceArray(item.owner_refs, `${rowPath}.owner_refs`, "owner."),
      ...(gapRefs === undefined ? {} : { gap_refs: gapRefs }),
    };
  });
  assertUniqueIds(resolved, path);
  return resolved;
}

function nonGoals(value: unknown, path: string): CoreModel["non_goals"] {
  const rows = plainArray(value, path, 8);
  if (rows.length !== 8) fail(path, "non-goal denominator mismatch");
  const resolved = rows.map((value, index) => {
    const rowPath = `${path}[${index}]`;
    const item = record(value, rowPath);
    exactKeys(item, ["id", "statement"], rowPath, ["owner_refs"]);
    const ownerRefs = optionalReferenceArray(item, "owner_refs", rowPath, "owner.");
    return {
      id: identifier(item.id, `${rowPath}.id`, "non-goal."),
      statement: nonemptyString(item.statement, `${rowPath}.statement`),
      ...(ownerRefs === undefined ? {} : { owner_refs: ownerRefs }),
    };
  });
  assertUniqueIds(resolved, path);
  return resolved;
}

function lifecycleStages(value: unknown, path: string): CoreModel["lifecycle_stages"] {
  const rows = plainArray(value, path, 10);
  if (rows.length !== 10) fail(path, "lifecycle denominator mismatch");
  const resolved = rows.map((value, index) => {
    const rowPath = `${path}[${index}]`;
    const item = record(value, rowPath);
    exactKeys(item, ["id", "order", "label", "question"], rowPath);
    return {
      id: identifier(item.id, `${rowPath}.id`, "stage."),
      order: portableInteger(
        item.order,
        `${rowPath}.order`,
        -MAX_PORTABLE_INTEGER,
        MAX_PORTABLE_INTEGER,
      ),
      label: nonemptyString(item.label, `${rowPath}.label`),
      question: nonemptyString(item.question, `${rowPath}.question`),
    };
  });
  assertUniqueIds(resolved, path);
  return resolved;
}

function digitalThread(value: unknown, path: string): CoreModel["digital_thread"] {
  const root = record(value, path);
  exactKeys(root, ["id", "abstention_rule", "stages"], path);
  const rawStages = plainArray(root.stages, `${path}.stages`, 17);
  if (rawStages.length !== 17) fail(`${path}.stages`, "digital-thread denominator mismatch");
  const stages = rawStages.map((value, index) => {
    const rowPath = `${path}.stages[${index}]`;
    const item = record(value, rowPath);
    exactKeys(
      item,
      [
        "id",
        "order",
        "label",
        "entity_type",
        "question",
        "owner_refs",
        "abstention",
        "relation_to_next",
      ],
      rowPath,
    );
    const relation = item.relation_to_next;
    if (relation !== null && typeof relation !== "string") {
      fail(`${rowPath}.relation_to_next`, "expected a relationship or null");
    }
    const resolvedRelation = relation === null
      ? null
      : nonemptyString(relation, `${rowPath}.relation_to_next`);
    return {
      id: identifier(item.id, `${rowPath}.id`, "thread."),
      order: portableInteger(
        item.order,
        `${rowPath}.order`,
        -MAX_PORTABLE_INTEGER,
        MAX_PORTABLE_INTEGER,
      ),
      label: nonemptyString(item.label, `${rowPath}.label`),
      entity_type: nonemptyString(item.entity_type, `${rowPath}.entity_type`),
      question: nonemptyString(item.question, `${rowPath}.question`),
      owner_refs: referenceArray(item.owner_refs, `${rowPath}.owner_refs`, "owner."),
      abstention: nonemptyString(item.abstention, `${rowPath}.abstention`),
      relation_to_next: resolvedRelation,
    };
  });
  assertUniqueIds(stages, `${path}.stages`);
  return {
    id: identifier(root.id, `${path}.id`, "thread."),
    abstention_rule: nonemptyString(root.abstention_rule, `${path}.abstention_rule`),
    stages,
  };
}

function systemArchitecture(value: unknown, path: string): CoreModel["system_architecture"] {
  const root = record(value, path);
  exactKeys(root, ["id", "planes", "flow"], path);
  const rawPlanes = plainArray(root.planes, `${path}.planes`, 6);
  if (rawPlanes.length !== 6) fail(`${path}.planes`, "system-plane denominator mismatch");
  const planes = rawPlanes.map((value, index) => {
    const rowPath = `${path}.planes[${index}]`;
    const item = record(value, rowPath);
    exactKeys(
      item,
      ["id", "order", "title", "purpose", "inputs", "outputs", "owner_refs"],
      rowPath,
    );
    return {
      id: identifier(item.id, `${rowPath}.id`, "plane."),
      order: portableInteger(
        item.order,
        `${rowPath}.order`,
        -MAX_PORTABLE_INTEGER,
        MAX_PORTABLE_INTEGER,
      ),
      title: nonemptyString(item.title, `${rowPath}.title`),
      purpose: nonemptyString(item.purpose, `${rowPath}.purpose`),
      inputs: stringArray(item.inputs, `${rowPath}.inputs`, MAX_JSON_CONTAINER_ITEMS),
      outputs: stringArray(item.outputs, `${rowPath}.outputs`, MAX_JSON_CONTAINER_ITEMS),
      owner_refs: referenceArray(item.owner_refs, `${rowPath}.owner_refs`, "owner."),
    };
  });
  assertUniqueIds(planes, `${path}.planes`);
  const planeIds = new Set(planes.map((plane) => plane.id));

  const rawFlow = plainArray(root.flow, `${path}.flow`, 6);
  if (rawFlow.length !== 6) fail(`${path}.flow`, "system-flow denominator mismatch");
  const flow = rawFlow.map((value, index) => {
    const rowPath = `${path}.flow[${index}]`;
    const item = record(value, rowPath);
    exactKeys(item, ["from", "to", "contract"], rowPath);
    const from = identifier(item.from, `${rowPath}.from`, "plane.");
    const to = identifier(item.to, `${rowPath}.to`, "plane.");
    if (!planeIds.has(from) || !planeIds.has(to)) {
      fail(rowPath, "unresolved system-plane reference");
    }
    return {
      from,
      to,
      contract: nonemptyString(item.contract, `${rowPath}.contract`),
    };
  });
  if (new Set(flow.map((edge) => `${edge.from}\0${edge.to}`)).size !== flow.length) {
    fail(`${path}.flow`, "duplicate system flow");
  }
  return {
    id: identifier(root.id, `${path}.id`, "architecture."),
    planes,
    flow,
  };
}

function trafficModel(value: unknown, path: string): CoreModel["traffic_model"] {
  const root = record(value, path);
  exactKeys(root, ["id", "warning", "planes"], path);
  const rawPlanes = plainArray(root.planes, `${path}.planes`, 8);
  if (rawPlanes.length !== 8) fail(`${path}.planes`, "traffic-plane denominator mismatch");
  const planes = rawPlanes.map((value, index) => {
    const rowPath = `${path}.planes[${index}]`;
    const item = record(value, rowPath);
    exactKeys(
      item,
      ["id", "order", "title", "questions", "state", "current_scope", "gap_refs"],
      rowPath,
      ["owner_refs"],
    );
    const state = enumValue(item.state, CORE_STATES, `${rowPath}.state`);
    const ownerRefs = optionalReferenceArray(item, "owner_refs", rowPath, "owner.", true);
    const gapRefs = referenceArray(item.gap_refs, `${rowPath}.gap_refs`, "gap.");
    if (["current", "partial"].includes(state) && !ownerRefs?.length) {
      fail(rowPath, "implemented traffic state requires an owner");
    }
    if (state === "current" && gapRefs.length > 0) {
      fail(rowPath, "current traffic state cannot carry a gap");
    }
    return {
      id: identifier(item.id, `${rowPath}.id`, "traffic."),
      order: portableInteger(
        item.order,
        `${rowPath}.order`,
        -MAX_PORTABLE_INTEGER,
        MAX_PORTABLE_INTEGER,
      ),
      title: nonemptyString(item.title, `${rowPath}.title`),
      questions: stringArray(
        item.questions,
        `${rowPath}.questions`,
        MAX_JSON_CONTAINER_ITEMS,
      ),
      state,
      current_scope: nonemptyString(item.current_scope, `${rowPath}.current_scope`),
      ...(ownerRefs === undefined ? {} : { owner_refs: ownerRefs }),
      gap_refs: gapRefs,
    };
  });
  assertUniqueIds(planes, `${path}.planes`);
  return {
    id: identifier(root.id, `${path}.id`, "traffic."),
    warning: nonemptyString(root.warning, `${path}.warning`),
    planes,
  };
}

function domainRegistry(value: unknown, path: string): CoreModel["domain_registry"] {
  const rows = plainArray(value, path, 12);
  if (rows.length !== 12) fail(path, "domain denominator mismatch");
  const resolved = rows.map((value, index) => {
    const rowPath = `${path}[${index}]`;
    const item = record(value, rowPath);
    exactKeys(item, ["id", "title"], rowPath);
    return {
      id: identifier(item.id, `${rowPath}.id`, "domain."),
      title: nonemptyString(item.title, `${rowPath}.title`),
    };
  });
  assertUniqueIds(resolved, path);
  return resolved;
}

function referenceSets(value: unknown): ReadonlySet<string> {
  const item = record(value, "$references");
  exactKeys(item, ["gap_ids"], "$references");
  const gaps = referenceArray(item.gap_ids, "$references.gap_ids", "gap.");
  return new Set(gaps);
}

function validateReferences(core: CoreModel, gapIds: ReadonlySet<string>): void {
  const ownerIds = new Set(core.owners.map((owner) => owner.id));
  const ownerRefs = [
    ...core.current_baseline.flatMap((item) => item.owner_refs),
    ...core.current_maturity.flatMap((item) => item.owner_refs),
    ...core.non_goals.flatMap((item) => item.owner_refs ?? []),
    ...core.digital_thread.stages.flatMap((item) => item.owner_refs),
    ...core.system_architecture.planes.flatMap((item) => item.owner_refs),
    ...core.traffic_model.planes.flatMap((item) => item.owner_refs ?? []),
  ];
  if (ownerRefs.some((reference) => !ownerIds.has(reference))) {
    fail("$", "unresolved owner reference");
  }
  const gapRefs = [
    ...core.current_maturity.flatMap((item) => item.gap_refs ?? []),
    ...core.traffic_model.planes.flatMap((item) => item.gap_refs ?? []),
  ];
  if (gapRefs.some((reference) => !gapIds.has(reference))) {
    fail("$", "unresolved gap reference");
  }
}

function validateAtlasCoreUnsafe(
  value: unknown,
  references: CoreReferenceRegistry,
): CoreModel {
  validatePlainJsonTree(value);
  validatePlainJsonTree(references);
  const gapIds = referenceSets(references);
  const root = record(value, "$");
  exactKeys(root, ROOT_KEYS, "$");
  const schemaVersion = nonemptyString(root.schema_version, "$.schema_version");
  const catalogVersion = calendarDate(root.catalog_version, "$.catalog_version", ".");
  const asOf = calendarDate(root.as_of, "$.as_of", "-");
  const rootId = identifier(root.id, "$.id", "atlas.core.");
  if (
    schemaVersion !== CORE_SCHEMA_VERSION ||
    rootId !== CORE_ROOT_ID ||
    catalogVersion.replaceAll(".", "-") !== asOf ||
    rootId !== `atlas.core.${asOf}`
  ) {
    fail("$", "root metadata does not identify the live Atlas Core contract");
  }

  const core: CoreModel = {
    schema_version: schemaVersion,
    id: rootId,
    catalog_version: catalogVersion,
    title: nonemptyString(root.title, "$.title"),
    as_of: asOf,
    scope: nonemptyString(root.scope, "$.scope"),
    truth_contract: truthContract(root.truth_contract, "$.truth_contract"),
    controlled_states: controlledStates(root.controlled_states, "$.controlled_states"),
    owners: owners(root.owners, "$.owners"),
    current_baseline: currentBaseline(root.current_baseline, "$.current_baseline"),
    outcomes: outcomes(root.outcomes, "$.outcomes"),
    maturity_model: maturityModel(root.maturity_model, "$.maturity_model"),
    current_maturity: currentMaturity(root.current_maturity, "$.current_maturity"),
    non_goals: nonGoals(root.non_goals, "$.non_goals"),
    lifecycle_stages: lifecycleStages(root.lifecycle_stages, "$.lifecycle_stages"),
    digital_thread: digitalThread(root.digital_thread, "$.digital_thread"),
    system_architecture: systemArchitecture(root.system_architecture, "$.system_architecture"),
    traffic_model: trafficModel(root.traffic_model, "$.traffic_model"),
    domain_registry: domainRegistry(root.domain_registry, "$.domain_registry"),
  };
  const semanticRecordCount =
    1 +
    1 +
    core.controlled_states.length +
    core.owners.length +
    core.current_baseline.length +
    core.outcomes.length +
    core.maturity_model.length +
    core.current_maturity.length +
    core.non_goals.length +
    core.lifecycle_stages.length +
    1 +
    core.digital_thread.stages.length +
    1 +
    core.system_architecture.planes.length +
    core.system_architecture.flow.length +
    1 +
    core.traffic_model.planes.length +
    core.domain_registry.length;
  if (semanticRecordCount !== EXPECTED_SEMANTIC_RECORD_COUNT) {
    fail("$", "semantic record denominator mismatch");
  }
  validateReferences(core, gapIds);
  return core;
}

export function validateAtlasCore(
  value: unknown,
  references: CoreReferenceRegistry,
): CoreModel {
  try {
    return validateAtlasCoreUnsafe(value, references);
  } catch {
    return fail("$", "unexpected non-JSON input");
  }
}

export function coreOutcomeSlotId(recordIdentity: string): string {
  const outcomeId = identifier(recordIdentity, "$.record_identity", "outcome.");
  return `web.product.core.outcome.${outcomeId}.success_signal`;
}

function observationsFor(core: CoreModel): CoreOutcomeObservationEnvelope {
  return {
    rendered_observations: core.outcomes.map((outcome) => ({
      rule_id: "core.outcome",
      record_identity: outcome.id,
      facet_path: "success_signal",
      disposition: "rendered_identity",
      slot_id: coreOutcomeSlotId(outcome.id),
      transform_id: "identity-text",
      observed_value: outcome.success_signal,
    })),
    safety_observations: [],
  };
}

export function buildCoreOutcomeSinkObservations(
  value: unknown,
  references: CoreReferenceRegistry,
): CoreOutcomeObservationEnvelope {
  return observationsFor(validateAtlasCore(value, references));
}

export function buildCoreOutcomeViewModel(
  value: unknown,
  references: CoreReferenceRegistry,
): CoreOutcomeViewModel {
  const core = validateAtlasCore(value, references);
  return {
    core,
    semantic_record_count: EXPECTED_SEMANTIC_RECORD_COUNT,
    ...observationsFor(core),
  };
}

export function requireCoreOutcome(core: CoreModel, id: string): CoreOutcome {
  const outcome = core.outcomes.find((candidate) => candidate.id === id);
  if (!outcome) return fail("$.outcomes", "required outcome is absent");
  return outcome;
}
