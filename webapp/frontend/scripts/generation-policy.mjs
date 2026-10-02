export function requireLocalReferences(value) {
  if (!value || typeof value !== "object") return;
  if ("externalValue" in value) throw new Error("API generation forbids externalValue resource loading");
  if ("$dynamicRef" in value || "$recursiveRef" in value) throw new Error("API generation has an unsupported reference keyword");
  if ("$ref" in value && (typeof value.$ref !== "string" || !value.$ref.startsWith("#/"))) {
    throw new Error("API generation requires local OpenAPI references");
  }
  Object.values(value).forEach(requireLocalReferences);
}
