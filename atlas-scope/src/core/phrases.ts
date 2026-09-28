/* phrases.ts — the ONE owner of how a list of names is joined into prose.
 *
 * Several sentences joined host lists with no empty case, so a fleet with no routing table read "Under the
 * collected RIBs of  only (0 of 26 hosts…)". listPhrase always yields a phrase: the `empty` wording when there is
 * nothing, "a", "a and b", "a, b and c" otherwise.
 */
export function listPhrase(items: readonly string[], empty = "no host"): string {
  const xs = items.filter((x) => x !== "");
  if (xs.length === 0) return empty;
  if (xs.length === 1) return xs[0] as string;
  return `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1] as string}`;
}
