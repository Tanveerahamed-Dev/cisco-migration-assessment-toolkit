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
