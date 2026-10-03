/**
 * synth-fleet.mjs — deterministic, ENGINE-SHAPED synthetic assessment snapshots at fleet scale.
 *
 * WHY. Every layout, tree and budget in this app was measured on the 26-device reference sample. The
 * canonical real reference fleet is about 300 devices, and the layout was measured (brief
 * disc-compiler-any-snapshot §5) at 2,765 ms for 300 and 73,924 ms for 1,000 on the main thread. A
 * scale claim needs fleets of that size, and a fleet of that size must not be client data. This file
 * makes them: synthetic from the first byte, never derived from a collection.
 *
 * ENGINE-SHAPED, NOT LAYOUT-SHAPED. A fixture built in the shape the layout expects would agree with a
 * layout bug. So the generator builds a TOPOLOGY (a campus: a core pair, distribution pairs, dual- and
 * single-homed access, daisy-chained pod access, WAN routers, firewalls and access points seen only as
 * CDP neighbours) and then derives every section the Atlas Scope compiler reads the way the ENGINE
 * derives it:
 *   - `cable_map` is `cisco_toolkit/analyze.py :: compute_cable_map` restated — tiers are BFS depth from
 *     the core-role seeds, each tier sorted and then given the engine's four barycentre sweeps, nodes
 *     sorted by (tier, order, host), ports only where a cable terminates, off-scan nodes `collected:
 *     false` with the `uncollected` badge and a kind (ap / router / firewall) — so the tier partition the
 *     layout receives is the one the engine would publish for this topology, not one chosen to suit it;
 *   - `link_centrality` is real undirected edge betweenness (Brandes) over the collected graph, with
 *     bridges (Tarjan) and the pairs a bridge cuts — the quantity the layout picks its hub tier from;
 *   - `health_scores`, `failure_impact`, `devices`, `interfaces`, `physical_health`, `protocol_health`,
 *     `endpoint_identity` and a `punchlist` whose every evidence ref resolves inside the snapshot (the
 *     compiler refuses one that does not).
 * Sections the synthetic fleet has no basis for (routes, ACLs, overlay, …) are ABSENT rather than
 * invented, so the compiler reports them as not observed; nothing here claims a RIB it never built.
 *
 * SYNTHETIC BY CONSTRUCTION: hostnames `syn-*`, addresses from 198.18.0.0/15 (RFC 2544 benchmarking),
 * serials `SYN…`, MACs from the locally administered 02:… range. `script_version` says so.
 *
 * WHERE IT WRITES: only `atlas-scope/.local-data/synth/`, and only while Git ignores `.local-data/`
 * (checked with `git check-ignore`; refused otherwise). There is no --out: the one place is the rule.
 *
 *   node review/synth-fleet.mjs --devices 300 [--seed 1]            # write the snapshot
 *   node review/synth-fleet.mjs --devices 300 --measure [--runs 5] [--budget-ms 300]  # LABORATORY timing
 *
 * Exit 0 = done (and, with --budget-ms, the median is within it); 1 = the median is over the budget;
 * 2 = refused or failed (bad arguments are refused before anything is generated).
 *
 * `--measure` validates and compiles the snapshot with the app's own compiler, then times
 * `computeLayout` (src/fabric3d/layout.ts) on it and prints the figures labelled LABORATORY. Wall-clock
 * figures depend on the host and on what else it is doing; they are reported, and `--budget-ms` turns
 * one into an exit code for a Node-side check. The owner's LABORATORY budgets (≤ 300 ms at 300 devices,
 * ≤ 2 s at 1 000) are gated in a REAL BROWSER by review/measure-scale.mjs, which opens these same fleets
 * through the app's own open-a-snapshot control under host-env.mjs's gates. The unit suite asserts COUNTED
 * work instead (src/fabric3d/scale.test.ts), per vitest.config.ts's rule that a unit test asserts no
 * wall-clock time.
 *
 * Exports `synthFleet({ devices, seed })` (the snapshot object) and `synthFleetBytes(...)` (its UTF-8
 * JSON), which scale.test.ts imports so the test and this command generate the same bytes.
 */
import { execFileSync } from "node:child_process";
import { mkdirSync, renameSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "..");

/** The smallest fleet the role mix below can be built from without a role collapsing to zero. */
export const MIN_DEVICES = 40;
export const SYNTH_SCRIPT_VERSION = "synthetic-fleet/1 (review/synth-fleet.mjs; not a collection)";

/* ── deterministic noise ───────────────────────────────────────────────────── */

/** mulberry32: small, fast, fully determined by its seed. */
function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const pad = (n, w) => String(n).padStart(w, "0");
/** RFC 6901 token escape, as the engine writes its evidence refs. */
const tok = (s) => String(s).replace(/~/g, "~0").replace(/\//g, "~1");
const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

/* ── the role mix ──────────────────────────────────────────────────────────── */

/**
 * How N nodes (every node the cable map draws, collected or not) divide into roles. Proportions are a
 * campus of the reference fleet's kind: ~15 % access points seen only by CDP, a distribution pair per
 * ~50 nodes, ~6 % of access switches daisy-chained behind another one (a deeper tier), and a core pair,
 * two WAN routers and two firewalls at any size.
 */
export function roleMix(n) {
  if (!Number.isSafeInteger(n) || n < MIN_DEVICES) {
    throw new Error(`synth-fleet: --devices must be a whole number >= ${MIN_DEVICES}, got ${n}`);
  }
  const cores = 2;
  const wan = 2;
  const firewalls = 2;
  const distPairs = Math.max(2, Math.round(n / 50));
  const aps = Math.round(n * 0.15);
  const rest = n - cores - wan - firewalls - 2 * distPairs - aps;
  const pods = Math.max(1, Math.round(rest * 0.06));
  const access = rest - pods;
  return { cores, wan, firewalls, distPairs, dist: 2 * distPairs, aps, access, pods, total: n };
}

/* ── topology ──────────────────────────────────────────────────────────────── */

function buildTopology(n, seed) {
  const rnd = mulberry32(seed ^ 0x9e3779b9);
  const mix = roleMix(n);
  /** @type {{ host: string; role: string; collected: boolean; kind: string; platform: string; model: string }[]} */
  const nodes = [];
  const add = (host, role, collected, kind, platform, model) => {
    nodes.push({ host, role, collected, kind, platform, model });
    return host;
  };
  const cores = [1, 2].map((i) => add(`syn-core-${pad(i, 2)}`, "core", true, "device", "ios-xe", "C9500-48Y4C"));
  const wans = [1, 2].map((i) => add(`syn-wan-${pad(i, 2)}`, "", false, "router", "cisco ISR4451-X", "ISR4451-X"));
  const fws = [1, 2].map((i) => add(`syn-fw-${pad(i, 2)}`, "", false, "firewall", "cisco Firepower 2130", "FPR-2130"));
  const distPairs = [];
  for (let p = 1; p <= mix.distPairs; p += 1) {
    distPairs.push([
      add(`syn-dist-${pad(p, 2)}a`, "distribution", true, "device", "ios-xe", "C9500-24Y4C"),
      add(`syn-dist-${pad(p, 2)}b`, "distribution", true, "device", "ios-xe", "C9500-24Y4C"),
    ]);
  }
  const width = String(n).length;
  const access = [];
  for (let i = 1; i <= mix.access; i += 1) access.push(add(`syn-acc-${pad(i, width)}`, "access", true, "device", "ios-xe", "C9300-48P"));
  const pods = [];
  for (let i = 1; i <= mix.pods; i += 1) pods.push(add(`syn-pod-${pad(i, width)}`, "access", true, "device", "ios", "WS-C2960X-24PS-L"));
  const aps = [];
  for (let i = 1; i <= mix.aps; i += 1) aps.push(add(`syn-ap-${pad(i, width)}`, "", false, "ap", "cisco AIR-AP2802I-B-K9", "AIR-AP2802I"));

  /* Cables. Ports are allocated per host so every cable end names a port that exists on its record. */
  const nextPort = new Map();
  const port = (host, prefix) => {
    const k = `${host}|${prefix}`;
    const i = (nextPort.get(k) ?? 0) + 1;
    nextPort.set(k, i);
    return `${prefix}${i}`;
  };
  /** Port-channel numbers are per host, like the interface names they are. */
  const nextPo = new Map();
  const po = (host) => {
    const i = (nextPo.get(host) ?? 0) + 1;
    nextPo.set(host, i);
    return `Po${i}`;
  };
  /** @type {{ a: string; b: string; aPorts: string[]; bPorts: string[]; pc: boolean; aPo: string; bPo: string; speed: string; up: boolean }[]} */
  const cables = [];
  const cable = (a, b, { members = 1, aPrefix, bPrefix, speed }) => {
    const aPorts = Array.from({ length: members }, () => port(a, aPrefix));
    const bPorts = Array.from({ length: members }, () => port(b, bPrefix));
    // ~1 % of cables are down: a real fleet always has some, and op-status is evidence the UI renders.
    const pc = members > 1;
    cables.push({ a, b, aPorts, bPorts, pc, aPo: pc ? po(a) : "", bPo: pc ? po(b) : "", speed, up: rnd() >= 0.01 });
  };
  const [c1, c2] = cores;
  cable(c1, c2, { members: 2, aPrefix: "Hu1/0/", bPrefix: "Hu1/0/", speed: "100000" });
  wans.forEach((w, i) => cable(cores[i], w, { aPrefix: "Te1/1/", bPrefix: "Gi0/0/", speed: "10000" }));
  for (const f of fws) for (const c of cores) cable(c, f, { aPrefix: "Te1/1/", bPrefix: "Eth1/", speed: "10000" });
  for (const [da, db] of distPairs) {
    for (const d of [da, db]) for (const c of cores) cable(c, d, { members: 2, aPrefix: "Te1/0/", bPrefix: "Te1/1/", speed: "40000" });
    cable(da, db, { members: 2, aPrefix: "Te1/0/", bPrefix: "Te1/0/", speed: "10000" });
  }
  /** Which distribution pair each access switch hangs off: contiguous blocks, like building risers. */
  const pairOf = new Map();
  access.forEach((acc, i) => {
    const pair = distPairs[Math.floor((i * distPairs.length) / access.length)];
    pairOf.set(acc, pair);
    // Most access switches are dual-homed; about one in nine is single-homed, which is the finding
    // a real assessment raises most often.
    const single = rnd() < 0.11;
    cable(pair[0], acc, { aPrefix: "Te1/0/", bPrefix: "Te1/1/", speed: "10000" });
    if (!single) cable(pair[1], acc, { aPrefix: "Te1/0/", bPrefix: "Te1/1/", speed: "10000" });
  });
  /* Pod access switches are daisy-chained behind an access switch: one tier deeper. */
  pods.forEach((pod) => {
    const parent = access[Math.floor(rnd() * access.length)];
    cable(parent, pod, { aPrefix: "Gi1/0/", bPrefix: "Gi0/", speed: "1000" });
  });
  /* Access points, seen only from the access switch that reports them over CDP. */
  const edge = [...access, ...pods];
  aps.forEach((ap) => {
    const sw = edge[Math.floor(rnd() * edge.length)];
    cable(sw, ap, { aPrefix: "Gi1/0/", bPrefix: "Gi0", speed: "1000" });
  });
  return { mix, nodes, cables, rnd, pairOf };
}

/* ── the engine's cable map, restated (cisco_toolkit/analyze.py :: compute_cable_map) ──────── */

function engineCableMap(nodes, cables) {
  const byHost = new Map(nodes.map((n) => [n.host, n]));
  const adj = new Map(nodes.map((n) => [n.host, new Set()]));
  for (const c of cables) {
    adj.get(c.a).add(c.b);
    adj.get(c.b).add(c.a);
  }
  const UP_TIER_ROLES = new Set(["core", "backbone", "superspine", "spine"]);
  const hosts = nodes.map((n) => n.host);
  let seeds = hosts.filter((h) => UP_TIER_ROLES.has(byHost.get(h).role)).sort(cmp);
  if (seeds.length === 0) seeds = [[...hosts].sort((a, b) => adj.get(b).size - adj.get(a).size || cmp(a, b))[0]];
  const tier = new Map(seeds.map((h) => [h, 0]));
  let frontier = [...seeds];
  while (frontier.length > 0) {
    const nxt = [];
    for (const cur of frontier) {
      for (const o of adj.get(cur)) {
        if (!tier.has(o)) {
          tier.set(o, tier.get(cur) + 1);
          nxt.push(o);
        }
      }
    }
    frontier = nxt;
  }
  let maxT = Math.max(0, ...tier.values());
  for (const h of hosts) if (!tier.has(h)) tier.set(h, maxT + 1);
  maxT = Math.max(0, ...tier.values());
  const tiers = Array.from({ length: maxT + 1 }, (_, k) => hosts.filter((h) => tier.get(h) === k).sort(cmp));
  for (let s = 0; s < 4; s += 1) {
    for (let k = 1; k < tiers.length; k += 1) {
      const above = new Map(tiers[k - 1].map((h, i) => [h, i]));
      const scored = tiers[k].map((h) => {
        const ns = [...adj.get(h)].filter((o) => above.has(o)).map((o) => above.get(o));
        return [ns.length > 0 ? ns.reduce((x, y) => x + y, 0) / ns.length : 1e9, h];
      });
      // Python sorts the (score, host) tuples: score first, then host.
      scored.sort((x, y) => x[0] - y[0] || cmp(x[1], y[1]));
      tiers[k] = scored.map((x) => x[1]);
    }
  }
  const order = new Map();
  for (const t of tiers) t.forEach((h, i) => order.set(h, i));

  const opOf = (c) => (c.up ? "up" : "down");
  const downIncident = new Set();
  const ports = new Map(hosts.map((h) => [h, []]));
  const cableRecords = cables.map((c) => {
    const status = opOf(c);
    if (status === "down") {
      downIncident.add(c.a);
      downIncident.add(c.b);
    }
    const aPort = c.pc ? c.aPo : c.aPorts[0];
    const bPort = c.pc ? c.bPo : c.bPorts[0];
    ports.get(c.a).push({ name: aPort, peer: c.b, peer_port: bPort, op_status: status, is_pc: c.pc });
    ports.get(c.b).push({ name: bPort, peer: c.a, peer_port: aPort, op_status: status, is_pc: c.pc });
    const aCol = byHost.get(c.a).collected;
    const bCol = byHost.get(c.b).collected;
    return {
      a: c.a,
      a_port: aPort,
      b: c.b,
      b_port: bPort,
      is_pc: c.pc,
      members: c.aPorts.map((p, i) => ({ a_port: p, b_port: c.bPorts[i] })),
      speed: c.speed,
      confirmation: aCol && bCol ? "Both ends" : `One end (${aCol ? c.a : c.b})`,
      op_status: status,
    };
  });
  cableRecords.sort(
    (x, y) => cmp(x.a.toLowerCase(), y.a.toLowerCase()) || cmp(x.a_port.toLowerCase(), y.a_port.toLowerCase()) || cmp(x.b.toLowerCase(), y.b.toLowerCase()),
  );
  const nodeRecords = [...hosts]
    .sort((x, y) => tier.get(x) - tier.get(y) || order.get(x) - order.get(y) || cmp(x, y))
    .map((h) => {
      const n = byHost.get(h);
      const badges = [];
      if (!n.collected) badges.push("uncollected");
      if (downIncident.has(h)) badges.push("links-down");
      return {
        host: h,
        role: n.role,
        tier: tier.get(h),
        order: order.get(h),
        collected: n.collected,
        op_status: n.collected ? "up" : "unknown",
        kind: n.collected ? "device" : n.kind,
        badges: badges.slice(0, 3),
        ports: ports.get(h).sort((x, y) => cmp(x.name.toLowerCase(), y.name.toLowerCase())),
      };
    });
  const op = { up: 0, down: 0, unknown: 0 };
  for (const c of cableRecords) op[c.op_status] += 1;
  return {
    nodes: nodeRecords,
    cables: cableRecords,
    tiers,
    summary: { n_nodes: nodeRecords.length, n_cables: cableRecords.length, n_tiers: tiers.length, op },
  };
}

/* ── centrality: edge betweenness (Brandes) and bridges (Tarjan) over the collected graph ──── */

function linkCentrality(nodes, cables, cableMap) {
  const collected = new Set(nodes.filter((n) => n.collected).map((n) => n.host));
  const hosts = [...collected].sort(cmp);
  const idx = new Map(hosts.map((h, i) => [h, i]));
  const rows = cableMap.cables.filter((c) => collected.has(c.a) && collected.has(c.b));
  const adj = hosts.map(() => []);
  rows.forEach((c, e) => {
    adj[idx.get(c.a)].push([idx.get(c.b), e]);
    adj[idx.get(c.b)].push([idx.get(c.a), e]);
  });
  const V = hosts.length;
  const btw = new Float64Array(rows.length);
  for (let s = 0; s < V; s += 1) {
    const stack = [];
    const preds = Array.from({ length: V }, () => []);
    const sigma = new Float64Array(V);
    const dist = new Int32Array(V).fill(-1);
    sigma[s] = 1;
    dist[s] = 0;
    const q = [s];
    for (let qi = 0; qi < q.length; qi += 1) {
      const v = q[qi];
      stack.push(v);
      for (const [w, e] of adj[v]) {
        if (dist[w] < 0) {
          dist[w] = dist[v] + 1;
          q.push(w);
        }
        if (dist[w] === dist[v] + 1) {
          sigma[w] += sigma[v];
          preds[w].push([v, e]);
        }
      }
    }
    const delta = new Float64Array(V);
    while (stack.length > 0) {
      const w = stack.pop();
      for (const [v, e] of preds[w]) {
        const c = (sigma[v] / sigma[w]) * (1 + delta[w]);
        btw[e] += c;
        delta[v] += c;
      }
    }
  }
  /* Bridges and the component split each one causes (iterative Tarjan: no recursion depth limit). */
  const disc = new Int32Array(V).fill(-1);
  const low = new Int32Array(V);
  const size = new Int32Array(V);
  const bridgeCut = new Map();
  const compSize = new Int32Array(V);
  let time = 0;
  for (let r = 0; r < V; r += 1) {
    if (disc[r] >= 0) continue;
    const members = [];
    const stack = [[r, -1, 0]];
    disc[r] = low[r] = time++;
    size[r] = 1;
    members.push(r);
    const treeChildren = [];
    while (stack.length > 0) {
      const top = stack[stack.length - 1];
      const [v, parentEdge] = top;
      if (top[2] < adj[v].length) {
        const [w, e] = adj[v][top[2]];
        top[2] += 1;
        if (e === parentEdge) continue;
        if (disc[w] < 0) {
          disc[w] = low[w] = time++;
          size[w] = 1;
          members.push(w);
          stack.push([w, e, 0]);
        } else {
          low[v] = Math.min(low[v], disc[w]);
        }
      } else {
        stack.pop();
        if (stack.length > 0) {
          const p = stack[stack.length - 1][0];
          low[p] = Math.min(low[p], low[v]);
          size[p] += size[v];
          treeChildren.push([v, parentEdge, p]);
        }
      }
    }
    for (const m of members) compSize[m] = members.length;
    for (const [v, e, p] of treeChildren) if (low[v] > disc[p]) bridgeCut.set(e, size[v] * (members.length - size[v]));
  }
  const scored = rows.map((c, e) => ({ c, e, b: Math.round(btw[e] * 2) / 4 })); // /2 for undirected, to 0.5
  const ranked = [...scored].sort((x, y) => y.b - x.b || x.e - y.e);
  const rankOf = new Map(ranked.map((s, i) => [s.e, i + 1]));
  return scored.map(({ c, e, b }) => ({
    a_host: c.a,
    a_port: c.a_port,
    b_host: c.b,
    b_port: c.b_port,
    betweenness: b,
    is_bridge: bridgeCut.has(e),
    pairs_cut: bridgeCut.get(e) ?? 0,
    rank: rankOf.get(e),
  }));
}

/* ── the snapshot ──────────────────────────────────────────────────────────── */

/**
 * @param {{ devices: number; seed?: number }} o
 * @returns {Record<string, unknown>}
 */
export function synthFleet({ devices, seed = 1 }) {
  if (!Number.isSafeInteger(seed)) throw new Error(`synth-fleet: --seed must be a whole number, got ${seed}`);
  const { mix, nodes, cables, rnd } = buildTopology(devices, seed);
  const cableMap = engineCableMap(nodes, cables);
  const byHost = new Map(nodes.map((n) => [n.host, n]));
  const collected = nodes.filter((n) => n.collected).map((n) => n.host).sort(cmp);
  const nodeRec = new Map(cableMap.nodes.map((n) => [n.host, n]));

  /* Addresses: 198.18.0.0/15, one /32 per collected host, in host order. */
  const ipOf = new Map(collected.map((h, i) => [h, `198.18.${Math.floor((i + 1) / 250)}.${((i + 1) % 250) + 1}`]));
  let serial = 0;
  let mac = 0;
  const nextMac = () => {
    mac += 1;
    const hex = pad(mac.toString(16), 8);
    return `0200.${hex.slice(0, 4)}.${hex.slice(4)}`;
  };

  /* devices (inventory) — the engine's record keys. */
  const devicesSection = {};
  for (const h of collected) {
    const n = byHost.get(h);
    serial += 1;
    devicesSection[h] = {
      hostname: h,
      platform: n.platform,
      model: n.model,
      serial_number: `SYN${pad(serial, 8)}`,
      chassis_serial: "",
      sw_version: n.role === "access" && n.platform === "ios" ? "15.2(7)E8" : "17.9.4a",
      uptime: `${1 + Math.floor(rnd() * 400)} days`,
      system_mac: "",
      num_power_supplies: n.role === "access" ? 1 : 2,
      ps_status: "",
      power_capacity_w: "",
      power_drawn_w: "",
      power_remaining_w: "",
      num_modules: n.role === "core" ? 2 : 1,
      total_ports: nodeRec.get(h).ports.length + 2,
      active_ports: nodeRec.get(h).ports.length,
      fan_status: "",
      temperature_status: "",
      reported_hostname: "",
    };
  }

  /* interfaces — every port a cable terminates on (members for a bundle, plus the bundle) and two
     edge ports per access switch, keyed the way the engine keys them. */
  const interfaces = {};
  const iface = (host, name, extra) => {
    interfaces[host] ??= {};
    interfaces[host][name] = {
      port: name,
      status: "connected",
      switchport_mode: "Trunk",
      vlan: "10,20,30",
      duplex: "Full",
      speed: "10000",
      port_type: "10GBase-SR SFP",
      link_type: "Fiber",
      description: "",
      end_host_ip: "",
      stp_blocked: "Forwarding",
      endpoint_type: "Switch",
      trunk_native_vlan: "1",
      trunk_allowed_vlans: "10,20,30",
      trunk_status: "trunking",
      cdp_neighbor: "",
      current_switch_serial: devicesSection[host]?.serial_number ?? "",
      current_switch_ip: ipOf.get(host) ?? "",
      neighbor_switch_ip: "",
      stp_fwd_vlans: "10,20,30",
      neighbor_port: "",
      neighbor_platform: "",
      port_channel: "",
      port_channel_protocol: "",
      run_config_observed: true,
      ...extra,
    };
  };
  for (const c of cables) {
    for (const [self, peer, own, theirs, po] of [
      [c.a, c.b, c.aPorts, c.bPorts, c.aPo],
      [c.b, c.a, c.bPorts, c.aPorts, c.bPo],
    ]) {
      if (!byHost.get(self).collected) continue;
      const peerNode = byHost.get(peer);
      own.forEach((p, i) => {
        iface(self, p, {
          status: c.up ? "connected" : "notconnect",
          speed: c.speed,
          description: `link-to-${peer}`,
          cdp_neighbor: `${peer}.syn.invalid`,
          neighbor_port: theirs[i],
          neighbor_platform: peerNode.platform === "ios-xe" || peerNode.platform === "ios" ? `cisco ${peerNode.model}` : peerNode.platform,
          neighbor_switch_ip: ipOf.get(peer) ?? "",
          endpoint_type: peerNode.kind === "ap" ? "Access Point" : peerNode.kind === "router" ? "Router" : peerNode.kind === "firewall" ? "Firewall" : "Switch",
          port_channel: po,
          port_channel_protocol: po ? "LACP" : "",
          switchport_mode: peerNode.kind === "ap" ? "Access" : "Trunk",
          vlan: peerNode.kind === "ap" ? "40" : "10,20,30",
        });
      });
      if (po) iface(self, po, { status: c.up ? "connected" : "notconnect", speed: c.speed, description: `bundle-to-${peer}`, port_type: "", link_type: "" });
    }
  }
  for (const h of collected) {
    if (byHost.get(h).role !== "access") continue;
    for (const p of ["Gi1/0/47", "Gi1/0/48"]) {
      iface(h, p, {
        status: rnd() < 0.7 ? "connected" : "notconnect",
        switchport_mode: "Access",
        vlan: "10",
        speed: "1000",
        port_type: "10/100/1000BaseTX",
        link_type: "Copper",
        endpoint_type: "Workstation",
        trunk_native_vlan: "",
        trunk_allowed_vlans: "",
        trunk_status: "",
      });
    }
  }

  /* health_scores — collected devices only, as the engine scores them. */
  const band = (s) => (s >= 90 ? "Excellent" : s >= 75 ? "Good" : s >= 60 ? "Fair" : s >= 35 ? "Poor" : "Critical");
  const crit = { core: 1.5, distribution: 1.2, access: 1.0 };
  const healthScores = collected.map((h) => {
    const role = byHost.get(h).role;
    const score = Math.round(25 + rnd() * 75);
    const deductions = [];
    if (score < 60) deductions.push("err-disabled @ Gi1/0/47 (-8)");
    if (score < 40) deductions.push("single-gateway (VLAN 10) (-10)");
    return {
      switch: h,
      score,
      band: band(score),
      role,
      criticality: crit[role],
      deductions,
      deduction_refs: [],
      data_quality: rnd() < 0.9 ? 1 : 0.8,
    };
  });
  const healthIndex = new Map(healthScores.map((r, k) => [r.switch, k]));

  /* failure_impact — what losing each collected device strands (its single-homed dependants). */
  const dependants = new Map(collected.map((h) => [h, 0]));
  for (const n of cableMap.nodes) {
    const ups = n.ports.filter((p) => nodeRec.get(p.peer).tier < n.tier);
    if (ups.length === 1) dependants.set(ups[0].peer, (dependants.get(ups[0].peer) ?? 0) + 1);
  }
  const failureImpact = collected.map((h) => {
    const stranded = (dependants.get(h) ?? 0) * (byHost.get(h).role === "access" ? 6 : 12);
    const severity = stranded >= 40 ? "High" : stranded >= 10 ? "Medium" : stranded > 0 ? "Low" : "Info";
    return {
      host: h,
      severity,
      vlans_impacted: stranded > 0 ? 1 + Math.floor(rnd() * 3) : 0,
      stranded,
      hard: stranded > 0 ? 1 : 0,
      backup: 0,
      fhrp: 0,
      off_scan_gw_vlans: 0,
      detail: stranded > 0 ? `${stranded} endpoint(s) behind single-homed dependants` : "no single-homed dependants",
    };
  });

  /* physical_health — one row per access uplink; single uplinks carry the engine's risk tag. */
  const physicalHealth = [];
  for (const h of collected) {
    if (byHost.get(h).role !== "access") continue;
    const ups = nodeRec.get(h).ports.filter((p) => nodeRec.get(p.peer).tier < nodeRec.get(h).tier);
    for (const p of ups) {
      const crc = rnd() < 0.05 ? Math.floor(rnd() * 900) : 0;
      physicalHealth.push({
        switch: h,
        port: p.name,
        status: p.op_status === "up" ? "connected" : "notconnect",
        speed: "10Gb/s",
        duplex: "Full",
        media: "SFP/fiber",
        input_errors: crc,
        crc_errors: crc,
        output_errors: "",
        late_collisions: "",
        output_drops: 0,
        port_channel: "",
        poe: "",
        risk: ups.length === 1 ? "single-fiber-uplink" : crc > 0 ? "crc-errors" : "",
        severity: ups.length === 1 || crc > 0 ? "Medium" : "Info",
      });
    }
  }

  /* protocol_health — an STP row per collected switch, OSPF on the routed layers. */
  const protocolHealth = [];
  for (const h of collected) {
    const role = byHost.get(h).role;
    protocolHealth.push({ switch: h, protocol: "STP", severity: "Info", summary: "mode rapid-pvst; 0 blocked, 0 inconsistent", detail: "" });
    if (role !== "access") {
      protocolHealth.push({ switch: h, protocol: "OSPF", severity: "Info", summary: "all adjacencies FULL", detail: "" });
    }
  }

  /* endpoint_identity — the APs, seen from the switch port that reports them. */
  const endpointIdentity = [];
  for (const n of cableMap.nodes) {
    if (n.kind !== "ap") continue;
    for (const p of n.ports) {
      endpointIdentity.push({
        host: p.peer,
        port: p.peer_port,
        vlan: "40",
        ip: `198.19.${Math.floor(endpointIdentity.length / 250)}.${(endpointIdentity.length % 250) + 1}`,
        mac: nextMac(),
        mac_count: 1,
        vendor: "Cisco",
        endpoint_class: "Wireless AP",
        confidence: "Inferred-high",
        evidence: `CDP platform '${byHost.get(n.host).platform}'`,
      });
    }
  }

  /* punchlist — findings whose every evidence ref resolves inside this snapshot. */
  const punchlist = [];
  const SEV_RANK = { Critical: 4, High: 3, Medium: 2, Low: 1 };
  const finding = (severity, category, devicesList, title, detail, refs, basis) =>
    punchlist.push({
      severity,
      rank: SEV_RANK[severity],
      category,
      devices: devicesList,
      wave: "",
      title,
      detail,
      remediation: "",
      evidence_basis: basis,
      evidence_refs: refs,
      priority: 0,
    });
  for (const h of collected) {
    const k = healthIndex.get(h);
    const hs = healthScores[k];
    if (hs.band === "Critical") {
      finding("High", "Health", [h], `${h}: health score ${hs.score} (Critical)`, `Composite health ${hs.score}/100.`, [
        { kind: "analysis_row", host: h, ref: `/health_scores/${k}`, role: "derived_from", cite: `${h} health-score row` },
      ], "row");
    }
  }
  physicalHealth.forEach((row, k) => {
    if (row.risk === "single-fiber-uplink") {
      finding("Medium", "L1", [row.switch], `${row.switch}: single uplink ${row.port}`, `${row.switch} reaches the fabric over one non-redundant uplink.`, [
        { kind: "interface", host: row.switch, ref: `/interfaces/${tok(row.switch)}/${tok(firstMember(interfaces, row.switch, row.port))}`, role: "subject", cite: `${row.switch} ${row.port} (single uplink)` },
        { kind: "analysis_row", host: row.switch, ref: `/physical_health/${k}`, role: "derived_from", cite: `${row.switch} physical-health row` },
      ], "record");
    } else if (row.risk === "crc-errors") {
      finding("Low", "L1", [row.switch], `${row.switch}: CRC errors on ${row.port}`, `${row.crc_errors} CRC errors counted.`, [
        { kind: "analysis_row", host: row.switch, ref: `/physical_health/${k}`, role: "derived_from", cite: `${row.switch} physical-health row` },
      ], "row");
    }
  });
  for (const c of cableMap.cables) {
    if (c.op_status !== "down") continue;
    const ends = [c.a, c.b].filter((h) => byHost.get(h).collected);
    finding("High", "L1", ends, `Cable ${c.a} ${c.a_port} ↔ ${c.b} ${c.b_port} is down`, "Operational status down at an observed end.", ends.map((h) => {
      const p = h === c.a ? c.a_port : c.b_port;
      return { kind: "interface", host: h, ref: `/interfaces/${tok(h)}/${tok(p)}`, role: "subject", cite: `${h} ${p} (down)` };
    }), "record");
  }
  collected.forEach((h, i) => {
    if (byHost.get(h).platform === "ios" && i % 3 === 0) {
      finding("Low", "Software exposure", [h], `${h}: classic IOS 15.2 train`, "Software train is in maintenance-only support.", [
        { kind: "device_fact", host: h, ref: `/devices/${tok(h)}`, role: "derived_from", cite: `${h} inventory record` },
      ], "row");
    }
  });
  punchlist.sort((x, y) => y.rank - x.rank || cmp(x.title, y.title));
  punchlist.forEach((p, i) => {
    p.priority = i + 1;
  });

  return {
    schema: "collect_parse_snapshot/1",
    script_version: SYNTH_SCRIPT_VERSION,
    generated_at: "2026-01-01T00:00:00Z",
    collected_at: "2026-01-01T00:00:00Z",
    synthetic: { generator: "atlas-scope/review/synth-fleet.mjs", seed, mix },
    devices: devicesSection,
    interfaces,
    physical_health: physicalHealth,
    protocol_health: protocolHealth,
    health_scores: healthScores,
    cable_map: cableMap,
    failure_impact: failureImpact,
    link_centrality: linkCentrality(nodes, cables, cableMap),
    endpoint_identity: endpointIdentity,
    punchlist,
    /* `cisco_toolkit/analyze.py :: compute_collection_completeness` for a fleet whose every inventoried device
       returned every essential command: all complete, no blind spot listed. Without it the app states the fleet's
       collection as not stated (acceptance B7), which is true of the file but not of the fleet it models. */
    collection_completeness: {
      summary: { inventory: collected.length, complete: collected.length, partial: 0, not_collected: 0 },
      devices: [],
    },
  };
}

/** The first member port of a bundle named `po` on `host`, or `po` itself when it is not a bundle. */
function firstMember(interfaces, host, po) {
  if (!po.startsWith("Po")) return po;
  const hit = Object.values(interfaces[host] ?? {}).find((r) => r.port_channel === po);
  return hit ? hit.port : po;
}

/** @param {{ devices: number; seed?: number }} o */
export function synthFleetBytes(o) {
  return new TextEncoder().encode(`${JSON.stringify(synthFleet(o), null, 1)}\n`);
}

/* ── CLI ───────────────────────────────────────────────────────────────────── */

function parseArgs(argv) {
  const o = { devices: NaN, seed: 1, measure: false, runs: 5, budgetMs: null };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    const v = () => {
      const x = argv[i + 1];
      if (x === undefined) throw new Error(`synth-fleet: ${a} needs a value`);
      i += 1;
      return x;
    };
    if (a === "--devices") o.devices = Number(v());
    else if (a === "--seed") o.seed = Number(v());
    else if (a === "--runs") o.runs = Number(v());
    else if (a === "--budget-ms") o.budgetMs = Number(v());
    else if (a === "--measure") o.measure = true;
    else throw new Error(`synth-fleet: unknown argument ${a}`);
  }
  /* `--budget-ms` is a GATE: it turns the median into an exit code. Every way of giving it that could
     not fail is refused before anything is generated — NaN (`median > NaN` is never true), zero, a
     negative or an infinite budget, a budget without --measure (nothing would be timed), and a run
     count that is not a whole number of at least one (NaN runs timed nothing; 0 silently became 1). */
  if (o.budgetMs !== null && !(Number.isFinite(o.budgetMs) && o.budgetMs > 0)) {
    throw new Error(`synth-fleet: --budget-ms must be a finite number of milliseconds above zero, got ${o.budgetMs}`);
  }
  if (o.budgetMs !== null && !o.measure) {
    throw new Error("synth-fleet: --budget-ms judges a measurement; it needs --measure");
  }
  if (!(Number.isSafeInteger(o.runs) && o.runs >= 1)) {
    throw new Error(`synth-fleet: --runs must be a whole number of at least 1, got ${o.runs}`);
  }
  if (!Number.isSafeInteger(o.seed)) throw new Error(`synth-fleet: --seed must be a whole number, got ${o.seed}`);
  return o;
}

/** The one place this writes, refused unless Git ignores it: synthetic or not, it is not source. */
function outputPath(devices, seed) {
  const dir = join(PKG, ".local-data", "synth");
  try {
    execFileSync("git", ["check-ignore", "-q", join(PKG, ".local-data", "probe")], { cwd: PKG, stdio: "ignore" });
  } catch {
    throw new Error("synth-fleet: .local-data/ is not Git-ignored here (or Git is unavailable); refusing to write inside the repository");
  }
  return join(dir, `synth-fleet-${devices}-s${seed}.snapshot.json`);
}

async function main() {
  const o = parseArgs(process.argv.slice(2));
  const bytes = synthFleetBytes({ devices: o.devices, seed: o.seed });
  const out = outputPath(o.devices, o.seed);
  mkdirSync(dirname(out), { recursive: true });
  writeFileSync(`${out}.tmp`, bytes);
  renameSync(`${out}.tmp`, out);
  console.log(`wrote ${relative(PKG, out).replaceAll("\\", "/")} (${bytes.length} bytes, ${JSON.stringify(roleMix(o.devices))})`);
  if (!o.measure) return 0;

  const { validateSnapshot } = await import("../tools/lib/validate-snapshot.mjs");
  const { bindSourceWith, compileFabric } = await import("../tools/lib/compile-model.mjs");
  const { createHash } = await import("node:crypto");
  const v = validateSnapshot(bytes);
  if (!v.ok || v.snap === null) throw new Error(`synth-fleet: the compiler's validator refused the synthetic snapshot: ${JSON.stringify(v.errors)}`);
  const hashes = {
    sha256Hex: (b) => createHash("sha256").update(b).digest("hex"),
    sha1Hex: (b) => createHash("sha1").update(b).digest("hex"),
  };
  const binding = bindSourceWith(bytes, { source: `synth-fleet-${o.devices}`, sourceOrigin: "external-file" }, hashes);
  const fabric = compileFabric(v.snap, binding);
  const { computeLayout } = await import("../src/fabric3d/layout.ts");
  const times = [];
  let last = null;
  for (let r = 0; r < o.runs; r += 1) {
    const t0 = performance.now();
    last = computeLayout({ devices: fabric.devices, links: fabric.links, tiers: fabric.tiers });
    times.push(performance.now() - t0);
  }
  times.sort((a, b) => a - b);
  const median = times[Math.floor(times.length / 2)];
  const tiers = last.tierBounds.map((b) => `${b.observedTier ?? "not observed"}:${b.count}`).join(" ");
  console.log(
    `LABORATORY computeLayout ${o.devices} nodes / ${fabric.links.length} links: median ${median.toFixed(1)} ms ` +
      `(min ${times[0].toFixed(1)}, max ${times[times.length - 1].toFixed(1)}, ${times.length} runs); ` +
      `route hints ${last.routeHints.length}; tiers ${tiers}`,
  );
  if (o.budgetMs !== null && median > o.budgetMs) {
    console.error(`LABORATORY budget exceeded: median ${median.toFixed(1)} ms > ${o.budgetMs} ms`);
    return 1;
  }
  return 0;
}

if (process.argv[1] !== undefined && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().then(
    (code) => {
      process.exitCode = code;
    },
    (err) => {
      console.error(err instanceof Error ? err.message : err);
      process.exitCode = 2;
    },
  );
}
