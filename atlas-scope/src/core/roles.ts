/* roles.ts — the ONE owner of how a device role reads, for the legend, the scene's glyphs and the layout.
 *
 * The engine emits more roles than access and distribution (core, backbone, spine, superspine, ... — its role
 * weights and up-tier roles name them). Before this owner existed the scene mapped only access/distribution and
 * drew every other OBSERVED role with the 'role not observed' glyph, while the legend counted those devices in a
 * separate 'Other role' row: an observed fact rendered as absence. Case handling also differed between modules.
 *
 * normalizeRole: trim + lower-case; a missing, non-string or blank role is null (not observed).
 * roleGlyphClass: null -> "unobserved"; access / distribution -> themselves; ANY other observed role -> "other".
 */
export type RoleGlyphClass = "access" | "distribution" | "other" | "unobserved";

export function normalizeRole(role: unknown): string | null {
  if (typeof role !== "string") return null;
  const r = role.trim().toLowerCase();
  return r === "" ? null : r;
}

export function roleGlyphClass(role: unknown): RoleGlyphClass {
  const r = normalizeRole(role);
  if (r === null) return "unobserved";
  if (r === "access" || r === "distribution") return r;
  return "other";
}
