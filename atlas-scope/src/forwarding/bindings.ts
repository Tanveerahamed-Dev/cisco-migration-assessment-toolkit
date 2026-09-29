/**
 * bindings.ts — which ACL is applied where: the `ip access-group` bindings the snapshot carries.
 *
 * The engine used to say "No `ip access-group` binding exists anywhere in this snapshot" and pick
 * the list to apply by an address-specificity heuristic. The snapshot DOES hold bindings — core1
 * binds VOICE_FILTER inbound on Vlan20 and PROTECT_SERVERS outbound on Vlan30 — the shared compiler
 * simply never projected them. The consequence was concrete: a flow PROTECT_SERVERS genuinely
 * denies was headlined INDETERMINATE because an UNBOUND list's unevaluable line was counted
 * against it, and the permitted flow's hop named that unbound line as "what decided the hop".
 *
 * The bindings are read from `acl-bindings.json` (compiled by `tools/compile-acl-bindings.mjs`
 * from the same source bytes as fabric.json; see that file for why it is separate). Every
 * question here has THREE answers, never two:
 *
 *   - `bound`   — the interface record carries `acl_in`/`acl_out`: that list filters here;
 *   - `none`    — the interface's running configuration WAS observed and the producer projected no
 *                 access-group for this direction: nothing filters here;
 *   - `unknown` — anything else, each with its reason: no interface record, running config not
 *                 observed, the producer saw a candidate binding but did not project its name
 *                 (`candidate_projection_incomplete`), the interface itself could not be resolved,
 *                 or the sidecar was compiled from other bytes. Unknown is never read as `none`.
 */
import bindingsJson from "./acl-bindings.json";
import { aclsOf, fabric, linksByHost, resolveCite, routesOf } from "../core/data";
import { sameSourceBinding, type Cite, type Hop, type HopEvidence, type SourceBinding } from "../core/types";
import { formatIpv4, parseInterfaceAddress, parseIpv4, prefixContains, rankPrefixMatches, type Ipv4 } from "./ip";

export type Direction = "in" | "out";

interface BindingRecord {
  port: string;
  vlan: string | null;
  switchportMode: string | null;
  aclIn: string | null;
  aclOut: string | null;
  gateCandidates: string[];
  gateUnmodeled: string[];
  runConfigObserved: boolean;
  cite: Cite;
}

interface BindingsFile {
  meta: SourceBinding;
  hosts: Record<string, BindingRecord[]>;
}

const FILE = bindingsJson as unknown as BindingsFile;

/** The sidecar is evidence only about the bytes it was compiled from — the same digest, over the same
    byte form (LF-normalised), of the same length. A sidecar stating no form is refused. */
export const BINDINGS_TRUSTED = sameSourceBinding(FILE.meta, fabric.meta);

const BY_HOST: ReadonlyMap<string, ReadonlyMap<string, BindingRecord>> = new Map(
  Object.entries(FILE.hosts).map(([host, recs]) => [host, new Map(recs.map((r) => [r.port, r] as const))] as const),
);

const INCOMPLETE = "candidate_projection_incomplete";

export type BindingState =
  | { kind: "bound"; host: string; intf: string; dir: Direction; acl: string; cite: Cite }
  | { kind: "none"; host: string; intf: string; dir: Direction; cite: Cite }
  | { kind: "unknown"; host: string; intf: string | null; dir: Direction; reason: string; cite: Cite | null };

const dirWord = (dir: Direction): string => (dir === "in" ? "inbound" : "outbound");

export function bindingAt(host: string, intf: string | null, dir: Direction): BindingState {
  if (!BINDINGS_TRUSTED) {
    return {
      kind: "unknown",
      host,
      intf,
      dir,
      reason: `the binding projection was compiled from different snapshot bytes (${FILE.meta.sourceSha256.slice(0, 8)}) than this build's data, so it is not read`,
      cite: null,
    };
  }
  if (intf === null) {
    return {
      kind: "unknown",
      host,
      intf,
      dir,
      reason: `the interface the flow ${dir === "in" ? "enters" : "leaves"} ${host} by could not be resolved from the collected evidence`,
      cite: null,
    };
  }
  const rec = BY_HOST.get(host)?.get(intf);
  if (rec === undefined) {
    return { kind: "unknown", host, intf, dir, reason: `no interface record for ${intf} was collected on ${host}`, cite: null };
  }
  const name = dir === "in" ? rec.aclIn : rec.aclOut;
  if (name !== null) return { kind: "bound", host, intf, dir, acl: name, cite: rec.cite };
  if (rec.gateUnmodeled.includes(INCOMPLETE) && rec.gateCandidates.includes(`interface_acl_${dir}`)) {
    return {
      kind: "unknown",
      host,
      intf,
      dir,
      reason: `the collector recorded an ${dirWord(dir)} access-group candidate on ${intf} but did not project which ACL it names (forwarding_gate_unmodeled: ${INCOMPLETE})`,
      cite: rec.cite,
    };
  }
  if (!rec.runConfigObserved) {
    return { kind: "unknown", host, intf, dir, reason: `the running configuration of ${host} ${intf} was not observed`, cite: rec.cite };
  }
  return { kind: "none", host, intf, dir, cite: rec.cite };
}

/** The literal snapshot field a bound state was read from — the `raw` of its evidence item. */
const bindingRaw = (dir: Direction, acl: string): string => `acl_${dir}: ${acl}`;

export function bindingEvidence(s: BindingState): HopEvidence {
  switch (s.kind) {
    case "bound":
      return {
        kind: "topology",
        label: `${s.host} ${s.intf} applies ACL ${s.acl} ${dirWord(s.dir)} (observed \`ip access-group ${s.acl} ${s.dir}\` binding)`,
        raw: bindingRaw(s.dir, s.acl),
        cite: s.cite,
      };
    case "none":
      return {
        kind: "topology",
        label: `${s.host} ${s.intf} carries no ${dirWord(s.dir)} access-group in its observed running configuration`,
        raw: null,
        cite: s.cite,
      };
    case "unknown":
      return {
        kind: "absence",
        label: `${s.host} ${s.intf ?? "(interface unresolved)"} ${dirWord(s.dir)} ACL binding not observed: ${s.reason}`,
        raw: null,
        cite: s.cite ?? `interfaces.${s.host}`,
      };
  }
}

/** Does this hop's evidence carry an OBSERVED binding of `acl` on this hop's host? Structural, not prose. */
export function hopHasObservedBinding(hop: Hop, acl: string): boolean {
  const prefix = `interfaces.${hop.host}.`;
  return hop.evidence.some(
    (e) => e.kind === "topology" && e.cite.startsWith(prefix) && (e.raw === bindingRaw("in", acl) || e.raw === bindingRaw("out", acl)),
  );
}

/**
 * The interfaces on this hop's host whose ACL binding the hop's evidence records as NOT observed —
 * the `unknown` items `bindingEvidence` emits (an `absence` citing `interfaces.<host>[.<intf>]`).
 * `null` stands for an interface the engine could not resolve. Structural, not prose.
 *
 * Read it only for a hop that applied a list WITHOUT an observed binding (`hopHasObservedBinding`
 * false): the observed-bindings path can also cite a binding with an `absence` (a bound list whose
 * lines were not collected), and on such a hop this would over-report.
 */
export function hopUnobservedBindings(hop: Hop): (string | null)[] {
  const base = `interfaces.${hop.host}`;
  const out: (string | null)[] = [];
  for (const e of hop.evidence) {
    if (e.kind !== "absence") continue;
    const intf = e.cite === base ? null : e.cite.startsWith(`${base}.`) ? e.cite.slice(base.length + 1) : undefined;
    if (intf === undefined || out.includes(intf)) continue;
    out.push(intf);
  }
  return out;
}

/**
 * The interface on `host` whose connected subnet contains `ip` — how a packet from `ip` enters it,
 * or how one addressed to `ip` leaves it. Read from the RIB first, then the SVI records.
 */
export function connectedInterfaceFor(host: string, ip: Ipv4): string | null {
  const connected = routesOf(host).filter((r) => (r.source === "connected" || r.source === "local") && r.outIntf !== null);
  const ranked = rankPrefixMatches(connected, ip, (r) => r.prefix);
  const hit = ranked[0]?.item.outIntf ?? null;
  if (hit !== null) return hit;
  for (const r of fabric.l3) {
    if (r.host !== host || r.sviIp === null || r.vlan === null) continue;
    const addr = parseInterfaceAddress(r.sviIp);
    if (addr !== null && prefixContains(addr.prefix, ip)) return `Vlan${r.vlan}`;
  }
  return null;
}

/** ip -> the (host, port) pairs the endpoint table observed it on. */
const ENDPOINT_PORTS: ReadonlyMap<number, { host: string; port: string; cite: Cite }[]> = (() => {
  const m = new Map<number, { host: string; port: string; cite: Cite }[]>();
  for (const e of fabric.endpoints) {
    if (e.ip === null || e.host === null || e.port === null) continue;
    const ip = parseIpv4(e.ip);
    if (ip === null) continue;
    const list = m.get(ip) ?? [];
    list.push({ host: e.host, port: e.port, cite: e.cite });
    m.set(ip, list);
  }
  return m;
})();

export interface PathBindings {
  /** Every state consulted, in the order a packet meets them. */
  states: BindingState[];
  /** Bound lists in packet order (port-in, SVI-in, SVI-out, port-out), deduplicated. */
  bound: Extract<BindingState, { kind: "bound" }>[];
  unknown: Extract<BindingState, { kind: "unknown" }>[];
  evidence: HopEvidence[];
  /** Statements about L2 ports considered and set aside, so the exclusion is visible. */
  notes: string[];
}

/**
 * Port ACLs on the access ports of an SVI's VLAN. A port ACL filters only frames entering or
 * leaving THAT port, so it is relevant to this flow only if the endpoint is attached there. When the
 * endpoint table places the address on some other port it is set aside, and said so; when the
 * address's attachment was never observed, the port could be the one, and its binding state counts.
 */
function portStates(host: string, svi: string | null, dir: Direction, endpoint: Ipv4, notes: string[]): BindingState[] {
  const vlan = svi === null ? null : /^Vlan(\d+)$/i.exec(svi)?.[1] ?? null;
  if (vlan === null) return [];
  const out: BindingState[] = [];
  const seen = ENDPOINT_PORTS.get(endpoint) ?? [];
  for (const rec of BY_HOST.get(host)?.values() ?? []) {
    if (rec.vlan !== vlan || !/access/i.test(rec.switchportMode ?? "")) continue;
    const state = bindingAt(host, rec.port, dir);
    if (state.kind === "none") continue;
    const here = seen.some((s) => s.host === host && s.port === rec.port);
    if (!here && seen.length > 0) {
      notes.push(
        `${host} ${rec.port} (Vlan${vlan}) ${state.kind === "bound" ? `binds ${state.acl} ${state.dir}` : "has an access-group whose ACL name was not projected"}, but it filters only frames on that port, and ${formatIpv4(endpoint)} was observed on ${seen
          .slice(0, 2)
          .map((s) => `${s.host} ${s.port}`)
          .join(", ")}${seen.length > 2 ? ` and ${seen.length - 2} other(s)` : ""} (${seen[0]!.cite}), not there.`,
      );
      continue;
    }
    if (!here && state.kind === "unknown") {
      out.push({ ...state, reason: `${state.reason}; ${formatIpv4(endpoint)}'s attachment port was not observed, so this port could be it` });
      continue;
    }
    out.push(state);
  }
  return out;
}

/**
 * The NON-access physical ports on gateway `gw` that frames from `src` (in VLAN `vlan`) could arrive
 * by, whose inbound filtering is not an observed "none". Access ports are `portStates`' job; this
 * covers the trunks and uplinks the L2 path from the attachment switch ends on, which the model does
 * not simulate.
 *
 * Candidate ports are derived, never listed: for each switch the endpoint table places `src` on, the
 * gateway-side port of every cable between that switch and the gateway. Where some attachment switch
 * has no direct cable to the gateway, or the attachment was never observed, the frame could arrive
 * by ANY of the gateway's non-access ports that may carry the VLAN (VLAN membership stated and
 * including it, or not recorded) or that sit on a cable — every one of those counts.
 */
export function physicalIngressStates(gw: string, vlan: string, src: Ipv4): BindingState[] {
  const recs = BY_HOST.get(gw) ?? new Map<string, BindingRecord>();
  const cables = linksByHost.get(gw) ?? [];
  const localPort = (l: (typeof cables)[number]): string | null => (l.a === gw ? l.aPort : l.bPort);
  const otherEnd = (l: (typeof cables)[number]): string => (l.a === gw ? l.b : l.a);
  const isAccess = (port: string): boolean => /access/i.test(recs.get(port)?.switchportMode ?? "");
  const isSvi = (port: string): boolean => /^vlan\d+$/i.test(port);

  const candidates = new Set<string>();
  const seen = (ENDPOINT_PORTS.get(src) ?? []).filter((s) => s.host !== gw);
  const attachedHere = (ENDPOINT_PORTS.get(src) ?? []).some((s) => s.host === gw);
  let unresolved = seen.length === 0 && !attachedHere;
  for (const s of seen) {
    const direct = cables.filter((l) => otherEnd(l) === s.host).map(localPort).filter((p): p is string => p !== null);
    if (direct.length === 0) unresolved = true;
    for (const p of direct) candidates.add(p);
  }
  if (unresolved) {
    for (const l of cables) {
      const p = localPort(l);
      if (p !== null) candidates.add(p);
    }
    for (const r of recs.values()) {
      const members = (r.vlan ?? "").split(",").map((v) => v.trim()).filter((v) => v.length > 0);
      if (members.length === 0 || members.includes(vlan)) candidates.add(r.port);
    }
  }
  const out: BindingState[] = [];
  for (const port of [...candidates].sort()) {
    if (isSvi(port) || isAccess(port)) continue;
    const rec = recs.get(port);
    // A port whose OBSERVED config places it in other VLANs only cannot carry this one.
    const members = (rec?.vlan ?? "").split(",").map((v) => v.trim()).filter((v) => v.length > 0);
    if (rec !== undefined && rec.runConfigObserved && members.length > 0 && !members.includes(vlan)) continue;
    const state = bindingAt(gw, port, "in");
    if (state.kind !== "none") out.push(state);
  }
  return out;
}

/**
 * Every binding a packet meets on `host` for this flow: the access port it arrives on (when the
 * source is attached here), the L3 interface it enters, the L3 interface it leaves, the access port
 * it leaves by. Hosts with no collected ACLs are not asked — their filtering is already reported as
 * unobserved, and a binding to a list whose text we do not hold decides nothing.
 */
export function pathBindings(host: string, ingress: string | null, egress: string | null, srcIp: Ipv4, egressTarget: Ipv4 | null): PathBindings {
  const notes: string[] = [];
  const states: BindingState[] = [
    ...portStates(host, ingress, "in", srcIp, notes),
    bindingAt(host, ingress, "in"),
    bindingAt(host, egress, "out"),
    ...(egressTarget === null
      ? [{ kind: "unknown", host, intf: egress, dir: "out", reason: "the next-hop address the packet is framed toward could not be parsed, so which access port it leaves by is unknown", cite: null } as const]
      : portStates(host, egress, "out", egressTarget, notes)),
  ];
  const bound: Extract<BindingState, { kind: "bound" }>[] = [];
  const unknown: Extract<BindingState, { kind: "unknown" }>[] = [];
  for (const s of states) {
    if (s.kind === "bound" && !bound.some((b) => b.acl === s.acl && b.dir === s.dir && b.intf === s.intf)) bound.push(s);
    if (s.kind === "unknown") unknown.push(s);
  }
  return { states, bound, unknown, evidence: states.map(bindingEvidence), notes };
}

/**
 * One sentence per ACL-holding host describing what the collection says about bindings — the
 * replacement for the old global "no binding was collected anywhere", which was false.
 *
 * Every clause that names the host cites the records it counted (acceptance B6: a claim is displayed
 * with its citation). "dist1: 0 interface ACL bindings were observed." used to stand uncited: a count
 * of zero is a statement about records, and the reader must be able to open the records it was
 * counted over — the host's interface table, or its ACL table where no interface record exists.
 */
export function bindingCoverageSentences(): string[] {
  const out: string[] = [];
  for (const host of Object.keys(fabric.acls).sort()) {
    if (Object.keys(aclsOf(host)).length === 0) continue;
    /* Each clause cites what IT was read from (2026-09-28 verifier, D7): a refusal cites the two digests
       that disagree and this build's own binding record, an absence cites the coverage record that counts
       the hosts with interface records — never the ACL table, which says nothing about either. */
    if (!BINDINGS_TRUSTED) {
      out.push(
        `ACL bindings on ${host} are not read in this build: the binding projection was compiled from snapshot bytes ${String(FILE.meta.sourceSha256).slice(0, 8)}…, not this build's ${fabric.meta.sourceSha256.slice(0, 8)}… (meta.sourceSha256), so which interface and direction each of its ACLs (acls.${host}) is applied to is treated as unknown and the list is chosen by the address-specificity rule.`,
      );
      continue;
    }
    const recs = [...(BY_HOST.get(host)?.values() ?? [])];
    if (recs.length === 0) {
      out.push(
        `${host}: no interface record was collected for it (${fabric.coverage.cite}: interface records were collected for ${fabric.coverage.hostsWithInterfaces} hosts, and the binding projection holds none for ${host}), so which interface and direction each of its ACLs (acls.${host}) is applied to is unknown; a trace through ${host} falls back to the address-specificity rule and says so at that hop.`,
      );
      continue;
    }
    /* The host's interface table where the compiled model resolves it, else the first record counted. */
    const counted = resolveCite(`interfaces.${host}`) !== undefined ? `interfaces.${host}` : recs[0]!.cite;
    const bound = recs.flatMap((r) => [
      ...(r.aclIn === null ? [] : [`${r.aclIn} in on ${r.port} (${r.cite})`]),
      ...(r.aclOut === null ? [] : [`${r.aclOut} out on ${r.port} (${r.cite})`]),
    ]);
    const incomplete = recs.filter((r) => r.gateUnmodeled.includes(INCOMPLETE)).map((r) => `${r.port} (${r.cite})`);
    const unobserved = recs.filter((r) => !r.runConfigObserved).length;
    out.push(
      `${host}: ${bound.length} interface ACL ${bound.length === 1 ? "binding was" : "bindings were"} observed across its ${recs.length} interface ${recs.length === 1 ? "record" : "records"} (${counted})${bound.length === 0 ? "" : ` — ${bound.join("; ")}`}. ` +
        (incomplete.length === 0
          ? ""
          : `${incomplete.length} ${incomplete.length === 1 ? "port has" : "ports have"} an access-group whose ACL name the collector did not project (${incomplete.join(", ")}; ${INCOMPLETE}). `) +
        (unobserved === 0 ? "" : `${unobserved} of ${recs.length} interface records carry no observed running configuration (${counted}), so their bindings are unknown. `) +
        `A trace applies the observed bindings of the interfaces it enters and leaves by; only where one of those is unknown does it fall back to the address-specificity rule, and it says so at that hop.`,
    );
  }
  return out;
}
