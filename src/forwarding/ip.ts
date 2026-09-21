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
