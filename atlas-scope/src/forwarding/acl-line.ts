/**
 * acl-line.ts — how an access-list line is NAMED to a person.
 *
 * `AclLine.index` is the 0-based position of the line in the compiled record, and it is what the
 * citation carries (`acls.core1.PROTECT_SERVERS[3]`). Prose used to print that index bare —
 * "PROTECT_SERVERS line 3" — which is neither the 1-based position an engineer counts in
 * `show access-lists` (that line is the 4th) nor the IOS sequence number (40). An engineer checking
 * "line 3" against the device lands on the line above the one that decided the flow.
 *
 * So there is one formatter, and every sentence that names a line goes through it: prose is
 * 1-based and says how long the list is, and the 0-based index survives only inside the citation,
 * where it is a record path rather than a count. Sequence numbers were not collected in this
 * snapshot, so they are not claimed.
 */

/** "line 4 of 4" — 1-based. `total` is the number of lines in the list as collected. */
export function aclLineName(index: number, total?: number | null): string {
  const n = index + 1;
  return total === undefined || total === null ? `line ${n}` : `line ${n} of ${total}`;
}

/** The sentence a tooltip or footnote uses to explain the numbering once. */
export const ACL_LINE_NUMBERING_NOTE =
  "Lines are counted from 1, as in `show access-lists`; the citation's [n] is the 0-based record index. IOS sequence numbers were not collected in this snapshot.";
