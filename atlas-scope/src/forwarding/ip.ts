/**
 * ip.ts — IPv4 primitives for the forwarding simulator.
 *
 * Addresses are carried as host-order unsigned 32-bit numbers. Every parser returns `null` on
 * anything it cannot read exactly: a forwarding claim built on a guessed address is worse than no
 * claim at all, so nothing here coerces, pads, or "helpfully" repairs input.
 *
 * The one distinction this file exists to get right: a Cisco wildcard mask is the BITWISE INVERSE
 * of a subnet mask. `0.0.0.255` as a wildcard pins the first 24 bits (= /24); as a subnet mask it
 * is not a legal mask at all. Conflating them silently widens or narrows an ACL by a factor of
 * 2^24, so the two spellings get separate parsers that each reject the other's shape.
 */

import type { Flow } from "../core/types";

/** Host-order unsigned 32-bit IPv4 address. */
export type Ipv4 = number;

export interface Prefix {
  /** Network address: the base with all host bits cleared. */
  base: Ipv4;
  bits: number;
}

/** Strict dotted-quad octet: 0-255, no leading zeros (inet_aton would read those as octal). */
const OCTET = /^(0|[1-9][0-9]{0,2})$/;

export function parseIpv4(text: string): Ipv4 | null {
  const parts = text.trim().split(".");
  if (parts.length !== 4) return null;
  let v = 0;
  for (const p of parts) {
    if (!OCTET.test(p)) return null;
    const n = Number(p);
    if (n > 255) return null;
    v = (v << 8) | n;
  }
  return v >>> 0;
}

export function formatIpv4(v: Ipv4): string {
  return [(v >>> 24) & 0xff, (v >>> 16) & 0xff, (v >>> 8) & 0xff, v & 0xff].join(".");
}

/**
 * The subnet mask for a prefix length, or null when `bits` is not one.
 *
 * Null rather than a number because this is the primitive every containment test is built on, and
 * the only two numbers it could return on bad input are both wrong in the dangerous direction: 0 is
 * the /0 mask, which makes `prefixContains` answer TRUE for every address on earth, and all-ones
 * narrows an ACL by 2^32. A mask we cannot derive has no safe default, so it has none.
 *
 * `<<` operates mod 32 in JS, so /0 must also be special-cased or it comes back as all-ones.
 */
export function maskOf(bits: number): Ipv4 | null {
  if (!Number.isInteger(bits) || bits < 0 || bits > 32) return null;
  return bits === 0 ? 0 : (0xffffffff << (32 - bits)) >>> 0;
}

export function parsePrefix(text: string): Prefix | null {
  /* Typed as text, but a compiled table is data: a number prefix reached this at engine module load and
     threw, taking every consumer of the engine down with it (acceptance B3, 2026-10 wave-1 refuter). The
     compiler now drops such an entry (tools/lib/compile-model.mjs `usableRoutePrefix`, held equal to this
     grammar); this refuses one that arrives anyway. */
  if (typeof text !== "string") return null;
  const m = /^([0-9.]+)\/(\d{1,2})$/.exec(text.trim());
  if (!m) return null;
  const ip = parseIpv4(m[1]!);
  if (ip === null) return null;
  const bits = Number(m[2]);
  const mask = maskOf(bits);
  if (mask === null) return null;
  return { base: (ip & mask) >>> 0, bits };
}

export function formatPrefix(p: Prefix): string {
  return `${formatIpv4(p.base)}/${p.bits}`;
}

/** Containment is refused, not assumed, for a prefix whose length is not a length: no mask, no match. */
export function prefixContains(p: Prefix, ip: Ipv4): boolean {
  const m = maskOf(p.bits);
  if (m === null) return false;
  return ((ip & m) >>> 0) === ((p.base & m) >>> 0);
}

export type AddressRole = "outside" | "network" | "broadcast" | "host";

/**
 * What an address IS inside a prefix — the module's single statement of the fact that the network
 * and directed-broadcast addresses of a /30-or-wider subnet are not hosts.
 *
 * It lives here, rather than inside `hostAddressIn`, because that knowledge was previously applied
 * only when GENERATING an address and not when reading one back: the same module refused to emit
 * 10.0.30.255 and then accepted it as a flow endpoint. One owner, both directions.
 */
export function addressRoleIn(p: Prefix, ip: Ipv4): AddressRole {
  if (!prefixContains(p, ip)) return "outside";
  // /31 (RFC 3021 point-to-point) and /32 have no network/broadcast convention — every address is usable.
  if (p.bits >= 31) return "host";
  const mask = maskOf(p.bits);
  if (mask === null) return "outside";
  const hostBits = (~mask) >>> 0;
  const hostPart = (ip & hostBits) >>> 0;
  if (hostPart === 0) return "network";
  if (hostPart === hostBits) return "broadcast";
  return "host";
}

/** A subnet mask: contiguous leading ones. `0.0.0.255` is refused here — that shape is a wildcard. */
export function parseDottedMask(text: string): number | null {
  const v = parseIpv4(text);
  if (v === null) return null;
  const inverted = (~v) >>> 0;
  // Contiguity test: leading-ones masks have (~mask) + 1 a power of two (and 0 for /32).
  if (((inverted + 1) & inverted) !== 0) return null;
  return 32 - bitCount(inverted);
}

/** A Cisco wildcard: contiguous trailing ones. Returns the equivalent prefix length. */
export function parseWildcard(text: string): number | null {
  const v = parseIpv4(text);
  if (v === null) return null;
  if (((v + 1) & v) !== 0) return null; // discontiguous — legal on IOS, but it has no prefix length
  return 32 - bitCount(v);
}

/**
 * True ACL match semantics, valid for discontiguous wildcards too (IOS permits them, and
 * `parseWildcard` deliberately returns null for those — matching must still have an exact answer).
 */
export function wildcardMatches(ip: Ipv4, base: Ipv4, wild: Ipv4): boolean {
  return (((ip ^ base) & ~wild) >>> 0) === 0;
}

/** How many bits a wildcard pins — 0 for `any`, 32 for a host match. Used to rank ACL specificity. */
export function wildcardSpecificity(wild: Ipv4): number {
  return 32 - bitCount(wild >>> 0);
}

function bitCount(v: number): number {
  let x = v >>> 0;
  let n = 0;
  while (x !== 0) {
    x &= x - 1;
    n += 1;
  }
  return n;
}

export interface InterfaceAddress {
  ip: Ipv4;
  prefix: Prefix;
}

/**
 * The snapshot carries SVI addresses in two spellings — `10.0.10.2 255.255.255.0` (IOS) and
 * `10.0.10.3/24` (NX-OS). Both appear in the same `l3_forwarding` table, so both are read here.
 * A wildcard in the mask position is refused rather than inverted: guessing which convention a
 * field used is exactly the error this module exists to prevent.
 */
export function parseInterfaceAddress(text: string): InterfaceAddress | null {
  const t = text.trim();
  const slash = parsePrefixedAddress(t);
  if (slash) return slash;
  const parts = t.split(/\s+/);
  if (parts.length !== 2) return null;
  const ip = parseIpv4(parts[0]!);
  const bits = parseDottedMask(parts[1]!);
  if (ip === null || bits === null) return null;
  const mask = maskOf(bits);
  if (mask === null) return null;
  return { ip, prefix: { base: (ip & mask) >>> 0, bits } };
}

function parsePrefixedAddress(t: string): InterfaceAddress | null {
  const m = /^([0-9.]+)\/(\d{1,2})$/.exec(t);
  if (!m) return null;
  const ip = parseIpv4(m[1]!);
  const mask = maskOf(Number(m[2]));
  if (ip === null || mask === null) return null;
  return { ip, prefix: { base: (ip & mask) >>> 0, bits: Number(m[2]) } };
}

/**
 * A representative usable address inside a prefix, or null when the offset is not one.
 * Used to turn an ACL's destination space into a concrete question ("what happens to 10.0.30.10?")
 * without inventing an address outside the space the evidence names.
 */
export function hostAddressIn(p: Prefix, offset: number): Ipv4 | null {
  if (!Number.isInteger(offset) || offset < 0) return null;
  if (!Number.isInteger(p.bits) || p.bits < 0 || p.bits > 32) return null;
  if (offset >= 2 ** (32 - p.bits)) return null;
  const candidate = ((p.base + offset) >>> 0) as Ipv4;
  // Delegated rather than re-derived: the network/broadcast rule has exactly one owner in this file.
  return addressRoleIn(p, candidate) === "host" ? candidate : null;
}

export interface PrefixMatch<T> {
  item: T;
  prefix: Prefix;
}

/**
 * Every matching prefix, longest first; stable within equal lengths so the caller's tie-break
 * (administrative distance, for a RIB) is the only thing that decides a tie. Unparseable prefixes
 * are dropped rather than treated as matches — a prefix we cannot read matches nothing we can prove.
 */
export function rankPrefixMatches<T>(
  items: readonly T[],
  ip: Ipv4,
  prefixOf: (t: T) => string | null,
): PrefixMatch<T>[] {
  const out: (PrefixMatch<T> & { seq: number })[] = [];
  items.forEach((item, seq) => {
    const text = prefixOf(item);
    if (text === null) return;
    const prefix = parsePrefix(text);
    if (prefix === null) return;
    if (!prefixContains(prefix, ip)) return;
    out.push({ item, prefix, seq });
  });
  out.sort((a, b) => b.prefix.bits - a.prefix.bits || a.seq - b.seq);
  return out.map(({ item, prefix }) => ({ item, prefix }));
}

/* ── the flow question: ONE validator for every door ─────────────────────────────────────────────
 *
 * A flow reaches the engine through four doors: the form, a shared link, the engine's own presets
 * and counterexamples, and a direct `traceFlow` call. Only the form used to check it (1–65535, whole
 * number), so a link carrying `tcp>abc` restored `dstPort: NaN` and the trace came back "a tcp/NaN
 * flow … is delivered" (2026-09-23 acceptance report, B1). The check lives HERE, once, and every door
 * goes through it: the form and the link hand it the fields as text (`readFlow`), and the engine
 * hands it the typed value it was given (`flowProblems`), which is judged by the SAME text rules —
 * a `Flow` whose `dstPort` holds NaN is a flow whose port reads "NaN", and "NaN" is not a port.
 *
 * Nothing is coerced. A value that is not exactly one of the accepted spellings is a PROBLEM naming
 * its field and quoting its raw value; the caller decides how to say it (`describeFlowProblem`). */

/** The protocols this model traces. Anything else is not a narrower question — it is not a question. */
export const FLOW_PROTOCOLS: readonly Flow["protocol"][] = ["tcp", "udp", "icmp", "ip"];

const isFlowProtocol = (p: string): p is Flow["protocol"] => (FLOW_PROTOCOLS as readonly string[]).includes(p);

/** Only these carry ports; a port on any other protocol names something that does not exist. */
export const protocolCarriesPorts = (p: string): boolean => p === "tcp" || p === "udp";

/** `flow` is the shared link's whole flow parameter, for a problem with its SHAPE rather than a field. */
export type FlowField = "srcIp" | "dstIp" | "protocol" | "dstPort" | "srcPort" | "flow";

export type FlowProblemKind =
  | "missing"
  | "subnet"
  | "not-ipv4"
  | "unknown-protocol"
  | "not-a-port-number"
  | "port-out-of-range"
  | "port-without-ports"
  | "malformed";

export interface FlowProblem {
  field: FlowField;
  kind: FlowProblemKind;
  /** The raw text of the field, verbatim (trimmed). Quoted back to the reader, never repaired. */
  value: string;
}

/** A flow as text, field by field — what a form holds and what a link carries. */
export interface FlowText {
  srcIp: string;
  dstIp: string;
  protocol: string;
  /** Empty means "any port" (and is the only legal value for a protocol with no ports). */
  dstPort: string;
  srcPort?: string;
}

const PORT_TEXT = /^\d+$/;

function addressProblem(field: "srcIp" | "dstIp", raw: string): FlowProblem | null {
  const v = raw.trim();
  if (v === "") return { field, kind: "missing", value: v };
  if (v.includes("/")) return { field, kind: "subnet", value: v };
  if (parseIpv4(v) === null) return { field, kind: "not-ipv4", value: v };
  return null;
}

function portProblem(field: "dstPort" | "srcPort", raw: string, protocol: string): { problem: FlowProblem | null; port: number | null } {
  const v = raw.trim();
  if (v === "") return { problem: null, port: null };
  if (!PORT_TEXT.test(v)) return { problem: { field, kind: "not-a-port-number", value: v }, port: null };
  const n = Number(v);
  if (!Number.isInteger(n) || n < 1 || n > 65535) return { problem: { field, kind: "port-out-of-range", value: v }, port: null };
  /* A port on a protocol that has none is judged only once the protocol itself is known-good: "bogus
     with port 443" is a protocol problem, not a second, derivative port problem. */
  if (isFlowProtocol(protocol) && !protocolCarriesPorts(protocol)) {
    return { problem: { field, kind: "port-without-ports", value: v }, port: null };
  }
  return { problem: null, port: n };
}

/**
 * Read a flow from its fields as text. Returns the flow when every field is exactly valid, and
 * otherwise no flow and EVERY problem — a reader fixing one field at a time, only to be told about
 * the next, is being made to do the validator's work.
 */
export function readFlow(text: FlowText): { flow: Flow | null; problems: FlowProblem[] } {
  const problems: FlowProblem[] = [];
  const src = addressProblem("srcIp", text.srcIp);
  if (src) problems.push(src);
  const dst = addressProblem("dstIp", text.dstIp);
  if (dst) problems.push(dst);
  const protocol = text.protocol.trim();
  if (protocol === "") problems.push({ field: "protocol", kind: "missing", value: protocol });
  else if (!isFlowProtocol(protocol)) problems.push({ field: "protocol", kind: "unknown-protocol", value: protocol });
  const dport = portProblem("dstPort", text.dstPort, protocol);
  if (dport.problem) problems.push(dport.problem);
  const sport = portProblem("srcPort", text.srcPort ?? "", protocol);
  if (sport.problem) problems.push(sport.problem);
  if (problems.length > 0 || !isFlowProtocol(protocol)) return { flow: null, problems };
  return {
    flow: { srcIp: text.srcIp.trim(), dstIp: text.dstIp.trim(), protocol, dstPort: dport.port, srcPort: sport.port },
    problems,
  };
}

/** A typed value's text, exactly as it would be written: `NaN` stays "NaN", `1.5` stays "1.5". */
const asText = (v: unknown): string => (v === null || v === undefined ? "" : String(v));

/**
 * The problems with a flow that arrived already typed — the engine's entry check. The same rules as
 * `readFlow`, applied to the value's own text, so a `Flow` is valid exactly when the form would have
 * produced it.
 */
export function flowProblems(flow: Flow): FlowProblem[] {
  return readFlow({
    srcIp: asText(flow.srcIp),
    dstIp: asText(flow.dstIp),
    protocol: asText(flow.protocol),
    dstPort: asText(flow.dstPort),
    srcPort: asText(flow.srcPort),
  }).problems;
}

const FIELD_NAME: Readonly<Record<FlowField, string>> = {
  srcIp: "source address",
  dstIp: "destination address",
  protocol: "protocol",
  dstPort: "destination port",
  srcPort: "source port",
  flow: "flow",
};

export const flowFieldName = (f: FlowField): string => FIELD_NAME[f];

export interface FlowProblemWords {
  /** What is wrong, naming the field and quoting its value. A complete sentence. */
  problem: string;
  /** What to do about it. A complete sentence, or "" when there is nothing to add. */
  advice: string;
}

export interface DescribeFlowOptions {
  /**
   * Who is being told:
   *   - `form`     the reader typed it: the value is the subject ("abc is not a port number");
   *   - `link`     a shared link carried it: the field and the link are named ("The destination
   *                port "abc" in the shared link is not a port number");
   *   - `question` the engine was asked it: the field is named, and there is nothing to type.
   */
  where: "form" | "link" | "question";
  /** A real address from the snapshot to suggest, when the caller has one. */
  example?: string;
  /** The flow's protocol text, so a port on a portless protocol can name it. */
  protocol?: string;
}

/** The words for a problem. The ONE place a flow problem is phrased, for every surface. */
export function describeFlowProblem(p: FlowProblem, opts: DescribeFlowOptions): FlowProblemWords {
  const name = FIELD_NAME[p.field];
  const subject = opts.where === "form" ? p.value : `The ${name} "${p.value}"${opts.where === "link" ? " in the shared link" : ""}`;
  const holder = opts.where === "link" ? "The shared link names" : "The flow names";
  const forExample = opts.example ? `, for example ${opts.example}` : "";
  const protocols = `Use one of ${FLOW_PROTOCOLS.slice(0, -1).join(", ")} or ${FLOW_PROTOCOLS[FLOW_PROTOCOLS.length - 1] ?? ""}.`;
  switch (p.kind) {
    case "missing":
      if (p.field === "protocol") return { problem: opts.where === "form" ? "No protocol is chosen." : `${holder} no protocol.`, advice: protocols };
      if (opts.where === "form") return { problem: `Enter a ${p.field === "srcIp" ? "source" : "destination"} IPv4 address${forExample}.`, advice: "" };
      return { problem: `${holder} no ${name}.`, advice: opts.where === "link" && opts.example ? `Enter one${forExample}.` : "" };
    case "subnet":
      return { problem: `${subject} names a subnet.`, advice: `This traces one flow, so enter a single address inside it${opts.example ? ` — for example ${opts.example}` : ""}.` };
    case "not-ipv4":
      return { problem: `${subject} is not an IPv4 address.`, advice: `Use four dot-separated numbers, each 0 to 255${forExample}.` };
    case "unknown-protocol":
      return { problem: `${subject} is not a protocol this model traces.`, advice: protocols };
    case "not-a-port-number":
      return { problem: `${subject} is not a port number.`, advice: "Enter a whole number between 1 and 65535, or leave it empty." };
    case "port-out-of-range":
      return { problem: `${subject} is outside the port range.`, advice: "Enter a number between 1 and 65535." };
    case "port-without-ports":
      return { problem: `${subject} is a port, but ${opts.protocol ?? "this protocol"} carries no ports.`, advice: "Leave the port empty, or choose tcp or udp." };
    case "malformed":
      return { problem: `${subject} is not a flow: it has more than four ">"-separated fields.`, advice: "A flow is written source>destination>protocol>port." };
  }
}

/** Problem then advice, as one string — what most surfaces render. */
export function flowProblemSentence(p: FlowProblem, opts: DescribeFlowOptions): string {
  const w = describeFlowProblem(p, opts);
  return w.advice === "" ? w.problem : `${w.problem} ${w.advice}`;
}
