// Presentation of the engine's nullable classification, never a keystone rule.
const KEYSTONE_LABELS = new Map<boolean | null | undefined, string>([
  [true, "keystone"],
  [false, "not a keystone"],
  [null, "keystone not classified"],
]);

export function keystoneLabel(value: boolean | null | undefined): string {
  return KEYSTONE_LABELS.get(value) ?? "keystone not classified";
}
