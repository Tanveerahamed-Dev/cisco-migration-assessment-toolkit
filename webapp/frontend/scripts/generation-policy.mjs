export function generationMode(args) {
  if (args.length === 0) return "generate";
  if (args.length === 1 && args[0] === "--check") return "check";
  if (args.length === 1 && args[0] === "--review") return "review";
  throw new Error("Expected no argument, --check, or --review exclusively");
}

export function requireLocalReferences(value) {
  if (!value || typeof value !== "object") return;
  if ("externalValue" in value) throw new Error("API generation forbids externalValue resource loading");
  if ("$dynamicRef" in value || "$recursiveRef" in value) throw new Error("API generation has an unsupported reference keyword");
  if ("$ref" in value && (typeof value.$ref !== "string" || !value.$ref.startsWith("#/"))) {
    throw new Error("API generation requires local OpenAPI references");
  }
  Object.values(value).forEach(requireLocalReferences);
}

export function requirementsTypeSource(schema) {
  const contract = schema?.["x-atlas-requirements-contract"];
  const fields = ["schema", "scope", "keys", "list_fields", "availability_tiers", "fabric_models", "vlan_id"];
  const object = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
  const strings = (value, pattern) => Array.isArray(value) && value.length > 0
    && value.every((item) => typeof item === "string" && pattern.test(item))
    && new Set(value).size === value.length;
  if (!object(contract) || Object.keys(contract).length !== fields.length
      || !fields.every((field) => Object.hasOwn(contract, field))
      || contract.schema !== "atlas.requirements-contract/1" || contract.scope !== "saved_plan_admission"
      || !strings(contract.keys, /^[a-z][a-z0-9_]*$/)
      || !strings(contract.list_fields, /^[a-z][a-z0-9_]*$/)
      || !contract.list_fields.every((field) => contract.keys.includes(field))
      || !["availability_tier", "fabric_operating_model", "convergence_budget_ms", "vlan_zones"]
        .every((field) => contract.keys.includes(field) && !contract.list_fields.includes(field))
      || !strings(contract.availability_tiers, /^[a-z][a-z0-9-]*$/)
      || !strings(contract.fabric_models, /^[a-z][a-z0-9-]*$/)
      || !object(contract.vlan_id) || Object.keys(contract.vlan_id).length !== 2
      || !Number.isSafeInteger(contract.vlan_id.minimum) || contract.vlan_id.minimum < 1
      || !Number.isSafeInteger(contract.vlan_id.maximum) || contract.vlan_id.maximum < contract.vlan_id.minimum) {
    throw new Error("Missing or invalid engine-owned saved-plan requirements contract");
  }
  // Field order is stable even when the OpenAPI exporter sorts object properties.
  const ordered = Object.fromEntries(fields.map((field) => [field, field === "vlan_id"
    ? { minimum: contract.vlan_id.minimum, maximum: contract.vlan_id.maximum } : contract[field]]));
  return "\n// Engine-owned saved-plan admission metadata from the actual app OpenAPI export.\n"
    + `export const designRequirementsContract = ${JSON.stringify(ordered, null, 2)} as const;\n`
    + "\nexport type DesignRequirements = {\n"
    + "  [K in typeof designRequirementsContract.keys[number]]?:\n"
    + "    K extends typeof designRequirementsContract.list_fields[number] ? string | string[]\n"
    + "    : K extends \"convergence_budget_ms\" ? number | string\n"
    + "    : K extends \"vlan_zones\" ? Record<string, string | Array<string | number>>\n"
    + "    : string;\n"
    + "};\n";
}
