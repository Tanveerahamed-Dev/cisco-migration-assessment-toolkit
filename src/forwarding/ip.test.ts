/**
 * ip.test.ts — the IPv4 primitives, exercised against literals for the semantics that have exact
 * right answers, and against EVERY address-shaped string in the real fabric.json so the parser is
 * tested by the actual producer's output rather than by fixtures shaped the way it expects.
 */
import { describe, expect, it } from "vitest";
import { fabric } from "../core/data";
import {
  addressRoleIn,
  formatIpv4,
  formatPrefix,
  hostAddressIn,
  maskOf,
  parseDottedMask,
  parseInterfaceAddress,
  parseIpv4,
  parsePrefix,
  parseWildcard,
  prefixContains,
  rankPrefixMatches,
  wildcardMatches,
  wildcardSpecificity,
} from "./ip";

describe("parseIpv4", () => {
  it("parses dotted quads to host-order unsigned 32-bit values", () => {
    expect(parseIpv4("0.0.0.0")).toBe(0);
    expect(parseIpv4("10.0.10.2")).toBe(0x0a000a02);
    expect(parseIpv4("255.255.255.255")).toBe(0xffffffff);
    expect(parseIpv4("  10.0.30.1  ")).toBe(0x0a001e01);
  });

  it("rejects malformed input rather than coercing it", () => {
    for (const bad of [
      "",
      "   ",
      "10.0.0",
      "10.0.0.1.2",
      "10.0.0.256",
      "10.0.0.-1",
      "10.0.0.1/24",
      "10.0.0.01", // leading zeros are octal in inet_aton; ambiguous, so refused
      "ten.0.0.1",
      "1e2.0.0.1",
      "0x0a.0.0.1",
      "10..0.1",
      "any",
    ]) {
      expect(parseIpv4(bad), `"${bad}" must not parse`).toBeNull();
    }
  });

  it("round-trips through formatIpv4", () => {
    for (const s of ["0.0.0.0", "10.0.10.50", "192.168.1.255", "255.255.255.255"]) {
      const v = parseIpv4(s);
      expect(v).not.toBeNull();
      expect(formatIpv4(v!)).toBe(s);
    }
  });
});

describe("masks and wildcards are INVERTED relative to each other", () => {
  it("reads a subnet mask as leading ones", () => {
    expect(parseDottedMask("255.255.255.0")).toBe(24);
    expect(parseDottedMask("255.255.255.255")).toBe(32);
    expect(parseDottedMask("0.0.0.0")).toBe(0);
    expect(parseDottedMask("255.255.254.0")).toBe(23);
  });

  it("reads a Cisco wildcard as the INVERSE — 0 bits are the ones that must match", () => {
    expect(parseWildcard("0.0.0.255")).toBe(24); // last octet is a don't-care => /24
    expect(parseWildcard("0.0.0.0")).toBe(32); // exact host
    expect(parseWildcard("255.255.255.255")).toBe(0); // "any"
    expect(parseWildcard("0.0.1.255")).toBe(23);
  });

  it("does not confuse the two: 0.0.0.255 as a mask is /0-shaped nonsense, as a wildcard it is /24", () => {
    expect(parseDottedMask("0.0.0.255")).toBeNull(); // not contiguous leading ones
    expect(parseWildcard("0.0.0.255")).toBe(24);
    expect(parseWildcard("255.255.255.0")).toBeNull(); // not contiguous trailing ones
    expect(parseDottedMask("255.255.255.0")).toBe(24);
  });

  it("matches with true bit semantics, including discontiguous wildcards that have no prefix length", () => {
    const ip = parseIpv4("10.0.20.50")!;
    expect(wildcardMatches(ip, parseIpv4("10.0.20.0")!, parseIpv4("0.0.0.255")!)).toBe(true);
    expect(wildcardMatches(ip, parseIpv4("10.0.30.0")!, parseIpv4("0.0.0.255")!)).toBe(false);
    expect(wildcardMatches(ip, parseIpv4("0.0.0.0")!, parseIpv4("255.255.255.255")!)).toBe(true);
    // 0.0.255.0 is discontiguous: third octet free, fourth pinned. parseWildcard gives no length…
    expect(parseWildcard("0.0.255.0")).toBeNull();
    // …but matching still has an exact answer.
    expect(wildcardMatches(ip, parseIpv4("10.0.99.50")!, parseIpv4("0.0.255.0")!)).toBe(true);
    expect(wildcardMatches(ip, parseIpv4("10.0.99.51")!, parseIpv4("0.0.255.0")!)).toBe(false);
  });

  it("scores specificity by how many bits the wildcard pins", () => {
    expect(wildcardSpecificity(parseIpv4("255.255.255.255")!)).toBe(0); // any
    expect(wildcardSpecificity(parseIpv4("0.0.0.255")!)).toBe(24);
    expect(wildcardSpecificity(parseIpv4("0.0.0.0")!)).toBe(32); // host
  });
});

describe("prefixes", () => {
  it("handles the degenerate lengths", () => {
    const any = parsePrefix("0.0.0.0/0")!;
    expect(any.bits).toBe(0);
    expect(maskOf(0)).toBe(0);
    expect(prefixContains(any, parseIpv4("8.8.8.8")!)).toBe(true);
    expect(prefixContains(any, 0)).toBe(true);

    const host = parsePrefix("10.0.10.2/32")!;
    expect(host.bits).toBe(32);
    expect(maskOf(32)).toBe(0xffffffff);
    expect(prefixContains(host, parseIpv4("10.0.10.2")!)).toBe(true);
    expect(prefixContains(host, parseIpv4("10.0.10.3")!)).toBe(false);
  });

  it("normalises the base to the network address", () => {
    expect(formatPrefix(parsePrefix("10.0.10.77/24")!)).toBe("10.0.10.0/24");
  });

  it("rejects malformed prefixes", () => {
    for (const bad of ["10.0.10.0/33", "10.0.10.0/-1", "10.0.10.0/", "10.0.10.0", "/24", "10.0.10.0/2a", ""]) {
      expect(parsePrefix(bad), `"${bad}" must not parse`).toBeNull();
    }
  });

  it("parses both interface-address spellings the engine emits", () => {
    const a = parseInterfaceAddress("10.0.10.2 255.255.255.0")!;
    expect(a).not.toBeNull();
    expect(formatIpv4(a.ip)).toBe("10.0.10.2");
    expect(formatPrefix(a.prefix)).toBe("10.0.10.0/24");

    const b = parseInterfaceAddress("10.0.10.3/24")!;
    expect(formatIpv4(b.ip)).toBe("10.0.10.3");
    expect(formatPrefix(b.prefix)).toBe("10.0.10.0/24");

    expect(parseInterfaceAddress("10.0.10.3 0.0.0.255")).toBeNull(); // a wildcard is not a mask
    expect(parseInterfaceAddress("unnumbered")).toBeNull();
  });

  /* REGRESSION — maskOf used to return 0 for anything it could not read, and 0 is the /0 mask.
     A prefix length of 33, -1, 1.5 or NaN therefore became "match everything" rather than a
     refusal: `prefixContains({base: 10.0.30.0, bits: 33}, 8.8.8.8)` answered true. That is a
     fail-OPEN default in the one primitive whose stated contract is exact refusal. */
  it("refuses a prefix length that is not one, instead of falling back to the /0 mask", () => {
    for (const bad of [33, 64, -1, 1.5, NaN, Infinity, -Infinity]) {
      expect(maskOf(bad), `maskOf(${bad})`).toBeNull();
    }
    expect(maskOf(0)).toBe(0); // /0 is a real length and still a real mask
    expect(maskOf(24)).toBe(0xffffff00);
    expect(maskOf(32)).toBe(0xffffffff);
  });

  it("never lets an unreadable prefix length contain an address", () => {
    const base = parseIpv4("10.0.30.0")!;
    const outside = parseIpv4("8.8.8.8")!;
    for (const bits of [33, -1, 1.5, NaN]) {
      expect(prefixContains({ base, bits }, outside), `bits=${bits}`).toBe(false);
      // Not even its own base: containment we cannot compute is refused, not assumed either way.
      expect(prefixContains({ base, bits }, base), `bits=${bits}`).toBe(false);
      expect(hostAddressIn({ base, bits }, 10), `bits=${bits}`).toBeNull();
    }
    expect(prefixContains(parsePrefix("10.0.30.0/24")!, parseIpv4("10.0.30.7")!)).toBe(true);
  });

  /* REGRESSION — the network/broadcast rule was applied only when GENERATING an address. It is now
     one exported fact so a consumer validating an address it was GIVEN reads the same rule. */
  it("names what an address is inside a prefix, not merely whether it is inside one", () => {
    const p = parsePrefix("10.0.30.0/24")!;
    expect(addressRoleIn(p, parseIpv4("10.0.30.0")!)).toBe("network");
    expect(addressRoleIn(p, parseIpv4("10.0.30.255")!)).toBe("broadcast");
    expect(addressRoleIn(p, parseIpv4("10.0.30.1")!)).toBe("host");
    expect(addressRoleIn(p, parseIpv4("10.0.31.1")!)).toBe("outside");
    // /31 and /32 have no network/broadcast convention (RFC 3021), so both addresses are hosts.
    const p31 = parsePrefix("10.0.30.0/31")!;
    expect(addressRoleIn(p31, parseIpv4("10.0.30.0")!)).toBe("host");
    expect(addressRoleIn(p31, parseIpv4("10.0.30.1")!)).toBe("host");
    expect(addressRoleIn(parsePrefix("10.0.10.2/32")!, parseIpv4("10.0.10.2")!)).toBe("host");
  });

  it("keeps the generator and the classifier in agreement across every observed SVI subnet", () => {
    const subnets = fabric.l3.filter((r) => r.sviIp !== null).map((r) => parseInterfaceAddress(r.sviIp!)!.prefix);
    expect(subnets.length).toBeGreaterThan(0);
    for (const p of subnets) {
      const size = 2 ** (32 - p.bits);
      for (const offset of [0, 1, 10, size - 2, size - 1]) {
        const addr = ((p.base + offset) >>> 0) as number;
        const role = addressRoleIn(p, addr);
        expect(hostAddressIn(p, offset) === null, `${formatPrefix(p)} +${offset} (${role})`).toBe(role !== "host");
      }
    }
  });

  it("derives a representative in-prefix address, refusing network and broadcast", () => {
    const p = parsePrefix("10.0.30.0/24")!;
    expect(formatIpv4(hostAddressIn(p, 10)!)).toBe("10.0.30.10");
    expect(hostAddressIn(p, 0)).toBeNull(); // network address
    expect(hostAddressIn(p, 255)).toBeNull(); // broadcast
    expect(hostAddressIn(p, 1000)).toBeNull(); // outside
    expect(formatIpv4(hostAddressIn(parsePrefix("10.0.10.2/32")!, 0)!)).toBe("10.0.10.2"); // /32 has one address
  });
});

describe("longest-prefix ordering", () => {
  const prefixes = ["0.0.0.0/0", "10.0.0.0/16", "10.0.30.0/24", "10.0.30.1/32", "192.168.0.0/16"];

  it("orders every matching prefix longest-first", () => {
    const ranked = rankPrefixMatches(prefixes, parseIpv4("10.0.30.1")!, (p) => p);
    expect(ranked.map((r) => r.item)).toEqual(["10.0.30.1/32", "10.0.30.0/24", "10.0.0.0/16", "0.0.0.0/0"]);
    expect(ranked.map((r) => r.prefix.bits)).toEqual([32, 24, 16, 0]);
  });

  it("returns only matching prefixes, and an empty list when nothing matches", () => {
    expect(rankPrefixMatches(["10.0.0.0/16"], parseIpv4("8.8.8.8")!, (p) => p)).toEqual([]);
    expect(rankPrefixMatches(prefixes, parseIpv4("8.8.8.8")!, (p) => p).map((r) => r.item)).toEqual(["0.0.0.0/0"]);
  });

  it("is stable for equal prefix lengths so the caller's tie-break is the only thing that decides", () => {
    const dupes = ["10.0.30.0/24", "10.0.30.0/24"];
    const ranked = rankPrefixMatches(dupes.map((p, i) => ({ p, i })), parseIpv4("10.0.30.7")!, (x) => x.p);
    expect(ranked.map((r) => r.item.i)).toEqual([0, 1]);
  });

  it("skips unparseable prefixes instead of treating them as matches", () => {
    expect(rankPrefixMatches(["not-a-prefix", "10.0.0.0/8"], parseIpv4("10.1.2.3")!, (p) => p).map((r) => r.item)).toEqual(
      ["10.0.0.0/8"],
    );
  });
});

/* ── the real producer's output, not a fixture ─────────────────────────────── */

describe("every address string in the real fabric.json parses", () => {
  it("parses every route prefix on every host that has a RIB", () => {
    const seen: string[] = [];
    for (const [host, routes] of Object.entries(fabric.routes)) {
      for (const r of routes) {
        seen.push(`${host}:${r.prefix}`);
        expect(parsePrefix(r.prefix), `${host} ${r.prefix}`).not.toBeNull();
      }
    }
    expect(seen.length).toBeGreaterThan(0);
  });

  it("parses every ACL match field — address plus wildcard — that the snapshot carries", () => {
    let fields = 0;
    for (const named of Object.values(fabric.acls)) {
      for (const lines of Object.values(named)) {
        for (const l of lines) {
          for (const f of [l.src, l.dst]) {
            if (!f || f.ip === null) continue; // object-group reference: no address to parse
            fields += 1;
            expect(parseIpv4(f.ip), `${l.raw}`).not.toBeNull();
            expect(f.wild === null || parseIpv4(f.wild) !== null, `${l.raw}`).toBe(true);
          }
        }
      }
    }
    expect(fields).toBeGreaterThan(0);
  });

  it("parses every SVI address, in whichever spelling the source used", () => {
    const parsed = fabric.l3.filter((r) => r.sviIp !== null).map((r) => parseInterfaceAddress(r.sviIp!));
    expect(parsed.length).toBeGreaterThan(0);
    expect(parsed.filter((p) => p === null)).toEqual([]);
  });

  it("agrees with the engine's own primarySubnet wherever the engine stated one", () => {
    for (const r of fabric.l3) {
      if (r.sviIp === null || r.primarySubnet === null) continue;
      const derived = parseInterfaceAddress(r.sviIp);
      expect(derived, r.cite).not.toBeNull();
      expect(formatPrefix(derived!.prefix), r.cite).toBe(formatPrefix(parsePrefix(r.primarySubnet)!));
    }
  });
});
