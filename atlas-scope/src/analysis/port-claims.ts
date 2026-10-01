/**
 * One physical port, one cable: the cable map's own consistency check.
 *
 * A port terminates at most one cable. When the cable map places the SAME host:port on two or more
 * cables, at most one of them can be real, and the evidence does not say which. That is a
 * contradiction in the collection, not topology. Before this module nothing detected it: L7
 * (access16 Gi0/1 ↔ core1 Gi1/0/40, confirmed from access16 only) and L26 (core1 Gi1/0/40 ↔ dist1
 * Gi1/0/3, confirmed from both ends) both drew as observed cables, and L7's blast radius was reported
 * as "observed", with access16 stranded (2026-09-22 critic, B1).
 *
 * The test is structural, over every cable in the map: every port a cable names (either end, and
 * each side of each member pair) is claimed by that cable, and a port claimed by more than one cable
 * is disputed. It is not a list of links or hosts. The same rule catches the uncollected AP-floor1,
 * whose single port Gi0 is named as the far end of 17 cables by 17 different access switches —
 * one hostname reported for several devices, or a stale neighbour record. Either way, which cable
 * that port is really on is not determinable from this collection.
 */
import { fabric } from "../core/data";
import type { Link } from "../core/types";

export interface PortClaim {
  linkId: string;
  /** The adjacency confirmation the cable map recorded, verbatim ("Both ends", "One end (x)"). */
  confirmation: string | null;
  /** True when the device that OWNS the port confirmed this cable from its own neighbour table. */
  confirmedByOwner: boolean;
}

export interface PortDispute {
  host: string;
  port: string;
  /** Every cable that claims this port, in cable-map order. Always two or more. */
  claims: PortClaim[];
}

const MEMBER_SPLIT = /\s*↔\s*/;

function confirmedBy(confirmation: string | null, host: string): boolean {
  if (confirmation === null) return false;
  if (/both ends/i.test(confirmation)) return true;
  const one = /one end\s*\(([^)]+)\)/i.exec(confirmation);
  return one !== null && one[1]!.trim() === host;
}

/** Every host:port a cable claims — both ends, plus each side of each member pair. */
function portsClaimedBy(link: Link): Array<{ host: string; port: string }> {
  const out = new Map<string, { host: string; port: string }>();
  const add = (host: string, port: string | null | undefined): void => {
    const p = typeof port === "string" ? port.trim() : "";
    if (p === "") return;
    out.set(`${host}|${p}`, { host, port: p });
  };
  add(link.a, link.aPort);
  add(link.b, link.bPort);
  for (const m of link.members) {
    const [ap, bp] = m.split(MEMBER_SPLIT);
    add(link.a, ap);
    add(link.b, bp);
  }
  return [...out.values()];
}

export function findPortDisputes(links: readonly Link[]): PortDispute[] {
  const byPort = new Map<string, PortDispute>();
  for (const link of links) {
    // A cable whose two ends are the same host:port is a self-loop, handled by the projection.
    for (const { host, port } of portsClaimedBy(link)) {
      const key = `${host}|${port}`;
      const claim: PortClaim = { linkId: link.id, confirmation: link.confirmation, confirmedByOwner: confirmedBy(link.confirmation, host) };
      const hit = byPort.get(key);
      if (hit === undefined) byPort.set(key, { host, port, claims: [claim] });
      else if (!hit.claims.some((c) => c.linkId === link.id)) hit.claims.push(claim);
    }
  }
  return [...byPort.values()].filter((d) => d.claims.length > 1);
}

function indexByLink(disputes: readonly PortDispute[]): ReadonlyMap<string, PortDispute[]> {
  const m = new Map<string, PortDispute[]>();
  for (const d of disputes) {
    for (const c of d.claims) {
      const list = m.get(c.linkId);
      if (list === undefined) m.set(c.linkId, [d]);
      else list.push(d);
    }
  }
  return m;
}

/** Over the shipped cable map, computed once at load. */
export const PORT_DISPUTES: readonly PortDispute[] = findPortDisputes(fabric.links);
const BY_LINK = indexByLink(PORT_DISPUTES);

/** The disputes a cable is party to; empty when every port it names is on no other cable. */
export function disputesOf(linkId: string): readonly PortDispute[] {
  return BY_LINK.get(linkId) ?? [];
}

const plural = (n: number, one: string, many = `${one}s`): string => `${n} ${n === 1 ? one : many}`;

function claimPhrase(c: PortClaim): string {
  return `${c.linkId} (${c.confirmation ?? "confirmation not recorded"})`;
}

/**
 * One sentence per dispute, from `linkId`'s side: which port, which other cable(s) claim it, and
 * how each claim was confirmed. Names the evidence; never picks a winner.
 */
export function disputeSentence(linkId: string, d: PortDispute): string {
  const others = d.claims.filter((c) => c.linkId !== linkId);
  const self = d.claims.find((c) => c.linkId === linkId);
  const shown = others.slice(0, 4).map(claimPhrase).join(", ");
  const more = others.length > 4 ? ` and ${others.length - 4} more` : "";
  const ownerNote =
    self === undefined
      ? ""
      : self.confirmedByOwner
        ? ` ${d.host}'s own neighbour table confirms ${linkId}`
        : ` ${d.host} itself does not confirm ${linkId}`;
  const otherOwner = others.filter((c) => c.confirmedByOwner).map((c) => c.linkId);
  const otherNote = otherOwner.length === 0 ? "" : `${ownerNote === "" ? " " : "; "}it confirms ${otherOwner.join(", ")}`;
  return (
    `${d.host} ${d.port} is placed on ${plural(d.claims.length, "cable")}: ${linkId} and ${shown}${more}. ` +
    `A port terminates one cable, so at most one of these is real, and the collection does not settle which.` +
    (ownerNote === "" && otherNote === "" ? "" : `${ownerNote}${otherNote}.`)
  );
}

/**
 * How many of the cables a host appears on can be real, by the same one-port-one-cable rule the
 * link pane applies (2026-09-22 critic, B1). Every surface that states a host's cable count — the
 * device pane's "Cables" and "Severed cables" rows, the blast caveat, the canvas announcement —
 * reads this, so a device view can never claim more cables than the link view says can exist.
 *
 * `records` counts cable-map rows; `maxReal` is the upper bound once each port dispute ON THIS HOST
 * is allowed at most one real cable. Cables disputed only at the far end are listed separately:
 * they may not exist either, but they do not collapse this host's count.
 */
export interface HostCableAccount {
  host: string;
  records: number;
  maxReal: number;
  /** Disputes over this host's own ports. */
  ownDisputes: PortDispute[];
  /** Cables on this host that are party to any dispute (either end). */
  disputedLinkIds: string[];
}

export function hostCableAccount(host: string, links: readonly Link[], disputes: readonly PortDispute[] = PORT_DISPUTES): HostCableAccount {
  const mine = links.filter((l) => l.a === host || l.b === host);
  const ids = new Set(mine.map((l) => l.id));
  const ownDisputes = disputes.filter((d) => d.host === host && d.claims.some((c) => ids.has(c.linkId)));
  const collapsed = new Set<string>();
  for (const d of ownDisputes) for (const c of d.claims) if (ids.has(c.linkId)) collapsed.add(c.linkId);
  const disputedLinkIds = mine
    .filter((l) => disputes.some((d) => d.claims.some((c) => c.linkId === l.id)))
    .map((l) => l.id);
  return {
    host,
    records: mine.length,
    maxReal: Math.min(mine.length, mine.length - collapsed.size + ownDisputes.length),
    ownDisputes,
    disputedLinkIds,
  };
}

/**
 * The count stated as the evidence allows: plain when nothing is disputed, otherwise as records
 * plus the ceiling and the port(s) at issue. Never picks which record is the real one.
 */
export function cableCountPhrase(a: HostCableAccount): string {
  const base = `${plural(a.records, "cable record")} in the cable map`;
  if (a.disputedLinkIds.length === 0) return `${plural(a.records, "cable")} in the cable map`;
  const parts: string[] = [];
  if (a.ownDisputes.length > 0) {
    const ports = a.ownDisputes.map((d) => `${d.port} is named on ${d.claims.length} of them`).join(", ");
    /* The "one name, several devices" reading is offered only where the host itself confirms none
       of the claims (AP-floor1: 17 access switches name it, it names nothing back). Where the owner
       confirms one, the dispute is a contradiction between records, and is stated as that. */
    const ownerSilent = a.ownDisputes.every((d) => d.claims.every((c) => !c.confirmedByOwner));
    parts.push(
      `of which at most ${a.maxReal} can be real: port ${ports}, and a port terminates one cable` +
        (ownerSilent
          ? `. ${a.host} confirms none of them itself, so the name may cover several unrelated neighbours, or a record is stale`
          : `, and the collection does not settle which`),
    );
  }
  const farOnly = a.disputedLinkIds.filter((id) => !a.ownDisputes.some((d) => d.claims.some((c) => c.linkId === id)));
  if (farOnly.length > 0) {
    parts.push(`${farOnly.join(", ")} share${farOnly.length === 1 ? "s" : ""} a far-end port with another cable, so ${farOnly.length === 1 ? "its" : "their"} existence is disputed`);
  }
  return `${base}, ${parts.join("; ")}`;
}
