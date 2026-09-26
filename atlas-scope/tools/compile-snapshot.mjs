/**
 * compile-snapshot.mjs — the ONLY bridge between the assessment engine's evidence snapshot
 * and Atlas Scope's UI model.
 *
 * Doctrine (CLAUDE.md, SSOT + coverage-honesty):
 *   - Every field emitted here is READ from the snapshot; nothing is invented, defaulted to a
 *     healthy value, or interpolated. Absence is emitted as `null` and rendered as "not observed".
 *   - Every record carries `cite`: a dotted path back into the snapshot so the Inspector can show
 *     the raw evidence a claim rests on. A claim with no `cite` is a bug.
 *   - The source file's sha256 + byte length are stamped into `meta` so a rendered view can be
 *     bound to the exact bytes it was compiled from — taken over the LF-normalised bytes, the form
 *     Git stores (`meta.sourceDigestForm`); tools/source-binding.mjs owns that rule for every compiler.
 */
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { readSource } from "./source-binding.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(HERE, "../src/data/fabric.json");

/* The source and the bytes that bind it: tools/source-binding.mjs owns the rule (LF-normalised). */
const { path: SRC, snap, binding, workingTree } = readSource(HERE);

/** Absence is absence. "", "-", "N/A" and the engine's explicit [NOT OBSERVED] marker all mean unobserved. */
const NOT_OBSERVED = /^\s*\[NOT OBSERVED\]/i;
/* TYPES. The snapshot is untrusted JSON, so every value read from it enters as `unknown` and each
   helper below is the one place that narrows it. The parameters are JSDoc-annotated so this file
   is clean under `noImplicitAny` (tsconfig.scripts.json); JSDoc changes no emitted byte of
   src/data/fabric.json, and that is checked by hashing it before and after. */
/** @param {unknown} v */
const val = (v) => {
  if (v === undefined || v === null) return null;
  if (typeof v === "string") {
    const t = v.trim();
    if (t === "" || t === "-" || t === "N/A" || NOT_OBSERVED.test(t)) return null;
    return t;
  }
  if (typeof v === "number" && !Number.isFinite(v)) return null;
  return v;
};
/**
 * Keep the engine's own unobserved prose when it carries a REASON worth showing.
 * @param {unknown} v
 */
const reason = (v) => (typeof v === "string" && NOT_OBSERVED.test(v.trim()) ? v.trim() : null);
/**
 * A number is a number the snapshot ACTUALLY carried, or nothing.
 *
 * The previous implementation stripped every non-digit character before calling Number(), which
 * turned the snapshot's own absence markers into measurements: `num("")`, `num("N/A")`,
 * `num("unknown")` and `num("[NOT OBSERVED]")` all returned 0, and `num("Gi0/1")` returned 1.
 * Measured 2026-09-21 on the shipped data: 92 of 122 port-health rows rendered a clean
 * 0 / 0 / 0 / 0 error profile — 73 of them on ports whose own source record says the counters
 * were never read — and 19 of 44 cables rendered "Speed 0 Mbps" and were announced as
 * "0 megabit per second". `orNotObserved` cannot rescue any of that, because by the time a
 * surface sees the value it is a real, finite number. Absence laundered into a healthy-looking
 * zero is precisely the defect class this project exists to refuse.
 *
 * So: no character stripping, ever. A string is accepted only if the WHOLE of it parses.
 * @param {unknown} v
 */
const num = (v) => {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v !== "string") return null;
  const t = v.trim();
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
};
/** @param {unknown} v @returns {any[]} */
const arr = (v) => (Array.isArray(v) ? v : []);
/**
 * String arrays, with a loud refusal instead of `[object Object]`.
 *
 * `arr(x).map(String)` over a list of OBJECTS emits the literal string "[object Object]", and it
 * does it silently: the field is present, non-empty, and typed `string[]`, so every honesty guard
 * downstream sees a value and renders it. Measured 2026-09-21: all 44 compiled links carried
 * `members: ["[object Object]"]`, printed verbatim as the "Port channel" value on both of the
 * fabric's port-channels, and the honest "members not observed" branch was unreachable because
 * the array was never empty. This helper makes that shape a BUILD FAILURE rather than a shipped
 * string — the structural fix, so the next `.map(String)` over an object cannot repeat it.
 * @param {unknown} v
 * @param {string} where  the snapshot path, named in the build failure
 * @returns {string[]}
 */
const strs = (v, where) =>
  arr(v)
    .map((x) => {
      if (typeof x === "string") return x.trim();
      if (typeof x === "number" || typeof x === "boolean") return String(x);
      throw new Error(
        `compile-snapshot: ${where} contains a non-primitive member ` +
          `(${JSON.stringify(x).slice(0, 120)}). Stringifying it would emit "[object Object]". ` +
          `Compile it structurally instead.`,
      );
    })
    .filter((s) => s !== "");
/**
 * A JSON object, or an empty one. Its members stay `any` on purpose: they are snapshot values,
 * and each is narrowed by `val`/`num`/`strs`/`arr` at the point it is read.
 * @param {unknown} v
 * @returns {Record<string, any>}
 */
const obj = (v) => (v && typeof v === "object" && !Array.isArray(v) ? v : {});

/* devices ------------------------------------------------------------------ */
const cableNodes = arr(snap.cable_map?.nodes);
const nodeByHost = new Map(cableNodes.map((n) => [n.host, n]));
const healthByHost = new Map(arr(snap.health_scores).map((h) => [h.switch, h]));
const impactByHost = new Map(arr(snap.failure_impact).map((f) => [f.host, f]));

/* Hosts the fabric must render = cable-map nodes union inventoried devices. A cable-map-only node
   (an AP, a phone, an uncollected neighbour) is REAL topology; dropping it would silently shrink
   the blast radius. It is emitted with collected:false so the UI can never imply we assessed it. */
const hosts = [...new Set([...cableNodes.map((n) => n.host), ...Object.keys(obj(snap.devices))])].sort();

/* PER-FIELD PROVENANCE (acceptance B6). A device record is assembled from up to four source records —
   the inventory (`devices.<host>`), the cable-map node, the health score and the failure impact — so
   one `cite` cannot say where each field came from: the Device pane used to show Model, Criticality
   and Tier under the single inventory citation, a record that holds no criticality and no tier.
   `fieldCites` names, for each compiled field, the source record it was READ from, and it names one
   only where that record exists. A field with no entry is either absent (null) or the compiler's own
   default, and a surface must say which rather than borrow another record's citation. */
const INVENTORY_FIELDS = ["platform", "model", "serial", "swVersion", "uptime", "powerSupplies", "modules"];
const NODE_FIELDS = ["tier", "order", "opStatus", "badges"];
const HEALTH_FIELDS = ["score", "band", "criticality", "dataQuality", "deductions"];
/**
 * @param {string} host
 * @param {Record<string, any> | undefined} d  inventory record
 * @param {Record<string, any> | undefined} n  cable-map node
 * @param {Record<string, any> | undefined} h  health score
 * @returns {Record<string, string>}
 */
const deviceFieldCites = (host, d, n, h) => {
  /** @type {Record<string, string>} */
  const out = {};
  const inv = `devices.${host}`;
  const node = `cable_map.nodes[host=${host}]`;
  const health = `health_scores[switch=${host}]`;
  const own = d ? inv : node;
  out.id = own;
  out.host = own;
  if (d) out.collected = inv;
  else if (n && typeof n.collected === "boolean") out.collected = node;
  if (d) for (const f of INVENTORY_FIELDS) out[f] = inv;
  if (n) for (const f of NODE_FIELDS) out[f] = node;
  if (n && val(n.kind) !== null) out.kind = node;
  if (h && val(h.role) !== null) out.role = health;
  else if (n && val(n.role) !== null) out.role = node;
  else if (h) out.role = health;
  else if (n) out.role = node;
  if (h) for (const f of HEALTH_FIELDS) out[f] = health;
  return out;
};

const devices = hosts.map((host) => {
  const d = obj(snap.devices)[host];
  const n = nodeByHost.get(host);
  const h = healthByHost.get(host);
  const fi = impactByHost.get(host);
  return {
    id: host,
    host,
    collected: d ? true : Boolean(n?.collected),
    inventoried: Boolean(d),
    kind: val(n?.kind) ?? (d ? "switch" : "unknown"),
    role: val(h?.role) ?? val(n?.role),
    tier: Number.isFinite(n?.tier) ? n.tier : null,
    order: Number.isFinite(n?.order) ? n.order : 0,
    opStatus: val(n?.op_status) ?? "unknown",
    badges: strs(n?.badges, `cable_map.nodes[host=${host}].badges`),
    platform: val(d?.platform),
    model: val(d?.model),
    serial: val(d?.serial_number) ?? val(d?.chassis_serial),
    swVersion: val(d?.sw_version),
    uptime: val(d?.uptime),
    powerSupplies: num(d?.num_power_supplies),
    modules: num(d?.num_modules),
    score: Number.isFinite(h?.score) ? h.score : null,
    band: val(h?.band),
    criticality: Number.isFinite(h?.criticality) ? h.criticality : null,
    dataQuality: Number.isFinite(h?.data_quality) ? h.data_quality : null,
    deductions: strs(h?.deductions, `health_scores[switch=${host}].deductions`),
    impact: fi
      ? {
          severity: val(fi.severity),
          vlans: num(fi.vlans_impacted),
          stranded: num(fi.stranded),
          hard: num(fi.hard),
          backup: num(fi.backup),
          fhrp: num(fi.fhrp),
          detail: val(fi.detail),
          cite: `failure_impact[host=${host}]`,
        }
      : null,
    fieldCites: deviceFieldCites(host, d, n, h),
    cite: d ? `devices.${host}` : `cable_map.nodes[host=${host}]`,
  };
});

/* The source records the device fields above were read from, compiled under the SAME path the
   citations name, so a citation into them resolves inside the model to the very record that carries
   the figure — not to an assembled device record that also carries a dozen fields the cited source
   record never held. Only the fields the compiler reads are carried (a node's `ports` are the
   cables, compiled as `links`); nothing is defaulted here — an absent source value is null. */
const cableMapNodes = cableNodes.map((n) => ({
  host: n.host,
  kind: val(n.kind),
  role: val(n.role),
  tier: Number.isFinite(n.tier) ? n.tier : null,
  order: Number.isFinite(n.order) ? n.order : null,
  collected: typeof n.collected === "boolean" ? n.collected : null,
  opStatus: val(n.op_status),
  badges: strs(n.badges, `cable_map.nodes[host=${n.host}].badges`),
  cite: `cable_map.nodes[host=${n.host}]`,
}));
const healthScores = arr(snap.health_scores).map((h) => ({
  switch: h.switch,
  role: val(h.role),
  score: Number.isFinite(h.score) ? h.score : null,
  band: val(h.band),
  criticality: Number.isFinite(h.criticality) ? h.criticality : null,
  dataQuality: Number.isFinite(h.data_quality) ? h.data_quality : null,
  deductions: strs(h.deductions, `health_scores[switch=${h.switch}].deductions`),
  cite: `health_scores[switch=${h.switch}]`,
}));

/* links -------------------------------------------------------------------- */
/** @param {unknown} a @param {unknown} ap @param {unknown} b @param {unknown} bp */
const centralityKey = (a, ap, b, bp) => [`${a}|${ap}`, `${b}|${bp}`].sort().join("::");
/* The engine's own link_centrality rows, compiled under their source path so `link_centrality[k]`
   resolves inside the model to the record that carries the figures (acceptance B6: the link pane
   showed betweenness, bridge status, pairs cut and rank with no citation at all, and the model did
   not contain the record they came from). Read with the same guards the link fields use. */
const linkCentrality = arr(snap.link_centrality).map((c, k) => ({
  aHost: val(c.a_host),
  aPort: val(c.a_port),
  bHost: val(c.b_host),
  bPort: val(c.b_port),
  betweenness: Number.isFinite(c.betweenness) ? c.betweenness : null,
  isBridge: typeof c.is_bridge === "boolean" ? c.is_bridge : null,
  pairsCut: Number.isFinite(c.pairs_cut) ? c.pairs_cut : null,
  rank: Number.isFinite(c.rank) ? c.rank : null,
  cite: `link_centrality[${k}]`,
}));
/** @type {Map<string, { row: any, k: number }>} */
const centrality = new Map();
arr(snap.link_centrality).forEach((c, k) => {
  centrality.set(centralityKey(c.a_host, c.a_port, c.b_host, c.b_port), { row: c, k });
});
const links = arr(snap.cable_map?.cables).map((c, i) => {
  const hit = centrality.get(centralityKey(c.a, c.a_port, c.b, c.b_port));
  const cen = hit?.row;
  return {
    id: `L${i}`,
    a: c.a,
    aPort: val(c.a_port),
    b: c.b,
    bPort: val(c.b_port),
    isPortChannel: Boolean(c.is_pc),
    /* A member is a PAIR of ports, not a name. The source carries
       `{a_port, b_port}` objects; `.map(String)` destroyed them into "[object Object]" before any
       surface could show them. They are compiled to the pair the reader wants to see
       ("Po1 ↔ Po1"), and a member whose ports are BOTH unobserved contributes nothing — which is
       what makes DevicePane's "members not observed" branch reachable again. */
    members: arr(c.members)
      .map((m, mi) => {
        if (typeof m === "string" || typeof m === "number") return strs([m], `cable_map.cables[${i}].members[${mi}]`)[0] ?? null;
        const a = val(m?.a_port);
        const b = val(m?.b_port);
        if (a === null && b === null) return null;
        return `${a ?? "port not observed"} ↔ ${b ?? "port not observed"}`;
      })
      .filter((m) => m !== null),
    speedMbps: num(c.speed),
    opStatus: val(c.op_status) ?? "unknown",
    confirmation: val(c.confirmation),
    betweenness: cen && Number.isFinite(cen.betweenness) ? cen.betweenness : null,
    /* The one field on this object whose FALSE value is a safety claim ("a redundant path exists
       around this link"). `Boolean(undefined)` would publish that claim from a missing field, so
       it is read as a boolean or not at all — the same guard its numeric siblings already carry. */
    isBridge: cen && typeof cen.is_bridge === "boolean" ? cen.is_bridge : null,
    pairsCut: cen && Number.isFinite(cen.pairs_cut) ? cen.pairs_cut : null,
    centralityRank: cen && Number.isFinite(cen.rank) ? cen.rank : null,
    /* The link_centrality row the four figures above were read from, or null when the engine
       scored no such cable — a citation of its own, because `cite` names the cable record, which
       holds none of them. */
    centralityCite: hit ? `link_centrality[${hit.k}]` : null,
    cite: `cable_map.cables[${i}]`,
  };
});

/* findings (punchlist) ------------------------------------------------------ */
/**
 * Every key the producer may put on a punchlist row, and the compiled field that carries it.
 *
 * A row key NOT in this map is a BUILD FAILURE, not a silent drop. That is the structural answer to
 * the defect class this compiler has already shipped twice (object groups, ACL evaluability): the
 * producer adds a field, the compiler never learns of it, and the UI reports a model gap as though
 * the evidence did not exist. `source_command` was the third instance — the show-command the engine
 * cites as a finding's evidence (engine: `compute_migration_punchlist`, `_PUNCH_SOURCE_COMMAND`),
 * on 33 of 146 rows, dropped until 2026-09-22.
 *
 * The engine can also emit `severity_basis` and `evidence_confidence`; it appends both to `detail`
 * as well. They are deliberately NOT listed: this snapshot carries neither, and the day one appears
 * the build should stop and make someone decide how to show it.
 */
const PUNCHLIST_FIELDS = {
  severity: "severity",
  rank: "rank",
  priority: "priority",
  category: "category",
  devices: "devices",
  wave: "wave",
  title: "title",
  detail: "detail",
  remediation: "remediation",
  source_command: "sourceCommand",
};
arr(snap.punchlist).forEach((p, i) => {
  const unknownKeys = Object.keys(obj(p)).filter((k) => !Object.hasOwn(PUNCHLIST_FIELDS, k));
  if (unknownKeys.length > 0) {
    throw new Error(
      `compile-snapshot: punchlist[${i}] carries producer field(s) this compiler does not compile: ` +
        `${unknownKeys.join(", ")}. Compile them (and add them to PUNCHLIST_FIELDS) rather than dropping them.`,
    );
  }
});
const findings = arr(snap.punchlist).map((p, i) => ({
  id: `F${String(i + 1).padStart(3, "0")}`,
  severity: val(p.severity) ?? "Info",
  rank: num(p.rank),
  priority: num(p.priority),
  category: val(p.category),
  devices: strs(p.devices, `punchlist[${i}].devices`),
  wave: val(p.wave),
  title: val(p.title) ?? "(untitled finding)",
  detail: val(p.detail),
  remediation: val(p.remediation),
  /* The show-command the engine cites as this finding's evidence, or null when its category is a
     composite with no single backing command. A COMMAND NAME, not a record: the snapshot keeps no
     raw command output, so this is provenance, never a route to literal configuration text. */
  sourceCommand: val(p.source_command),
  cite: `punchlist[${i}]`,
}));

const crossLayer = arr(snap.cross_layer).map((c, i) => ({
  id: val(c.id) ?? `CL-${i}`,
  severity: val(c.severity) ?? "Info",
  layers: val(c.layers),
  title: val(c.title) ?? "",
  detail: val(c.detail),
  recommendation: val(c.recommendation),
  hosts: strs(c.hosts, `cross_layer[${i}].hosts`),
  cite: `cross_layer[${i}]`,
}));

/* forwarding substrate: routes, ACLs, SVIs ---------------------------------- */
/** @type {Record<string, object[]>} */
const routes = {};
for (const [host, rs] of Object.entries(obj(snap.routes))) {
  routes[host] = arr(rs)
    .map((r, i) => ({
      prefix: val(r.prefix),
      source: val(r.source),
      nextHop: val(r.next_hop),
      outIntf: val(r.out_intf),
      adminDistance: num(r.admin_distance),
      cite: `routes.${host}[${i}]`,
    }))
    .filter((r) => r.prefix);
}
/**
 * A match field may name an OBJECT-GROUP instead of an address/wildcard pair. Dropping that
 * reference (and the groups below) made the application tell users that a group's members "were
 * not collected" while the source file carried them — a model gap reported as a collection gap,
 * which is the one kind of error this project cannot tolerate.
 */
/** @param {any} f  one `src`/`dst` match field from the snapshot, or nothing */
const matchField = (f) =>
  f ? { ip: val(f.ip), wild: val(f.wild), group: val(f.group) } : null;

/** @type {Record<string, Record<string, Array<{ unevaluable: boolean }>>>} */
const acls = {};
for (const [host, named] of Object.entries(obj(snap.acls))) {
  acls[host] = {};
  for (const [name, lines] of Object.entries(obj(named))) {
    acls[host][name] = arr(lines).map((l, i) => ({
      index: i,
      action: val(l.action),
      raw: val(l.raw),
      proto: val(l.proto),
      src: matchField(l.src),
      dst: matchField(l.dst),
      sport: l.sport ?? null,
      dport: l.dport ?? null,
      /* The producer's OWN verdict on whether it could model this line, plus the qualifiers that
         defeated it. Carrying these is what stops the application re-deriving evaluability from
         the raw text and drifting away from the parser that produced it — the recurring
         parser-versus-detector defect this repository names explicitly. The producer's answer is
         ground truth; a consumer's re-derivation is at best a second opinion. */
      unevaluable: l.unevaluable === true,
      unmodeledQualifiers: strs(l.unmodeled_qualifiers, `acls.${host}.${name}[${i}].unmodeled_qualifiers`),
      /* Individually named because each defeats a DIFFERENT part of the model, and a reader is
         owed the specific reason rather than a generic "cannot evaluate":
           established — stateful; a forward-direction model cannot decide it
           icmpType    — an ICMP qualifier the matcher does not implement
           timeRange   — the rule is only active inside a named window, so ANY verdict on it is
                         conditional even when the packet plainly matches */
      established: l.established === true,
      icmpType: val(l.icmp_type),
      timeRange: val(l.time_range),
      cite: `acls.${host}.${name}[${i}]`,
    }));
  }
}

/** Object groups referenced by ACL match fields. Present in the snapshot; previously discarded. */
/** @type {Record<string, Record<string, object>>} */
const objectGroups = {};
for (const [host, groups] of Object.entries(obj(snap.object_groups))) {
  objectGroups[host] = {};
  for (const [name, g] of Object.entries(obj(groups))) {
    objectGroups[host][name] = {
      kind: val(g.kind),
      members: arr(g.members).map((m) => ({ ip: val(m.ip), wild: val(m.wild) })),
      cite: `object_groups.${host}.${name}`,
    };
  }
}
const aclFindings = arr(snap.acl_line_reachability?.findings).map((f, i) => ({
  host: val(f.host),
  acl: val(f.acl),
  lineIndex: num(f.line_index),
  action: val(f.action),
  raw: val(f.raw),
  verdict: val(f.verdict),
  reason: val(f.reason),
  detail: val(f.detail),
  blockingLines: arr(f.blocking_lines),
  sourceCommand: val(f.source_command),
  cite: val(f.citation) ?? `acl_line_reachability.findings[${i}]`,
}));

const l3 = arr(snap.l3_forwarding).map((r, i) => ({
  host: val(r.switch),
  vlan: num(r.vlan),
  sviIp: val(r.svi_ip),
  fhrp: val(r.fhrp),
  fhrpRole: val(r.role),
  vip: val(r.vip),
  routingSource: val(r.routing_source),
  nextHop: val(r.next_hop),
  primarySubnet: val(r.primary_subnet),
  secondary: val(r.secondary),
  tracking: val(r.tracking),
  trackingUnobserved: reason(r.tracking),
  risk: val(r.risk),
  riskUnobserved: reason(r.risk),
  severity: val(r.severity),
  cite: `l3_forwarding[${i}]`,
}));

/* per-port and per-protocol evidence ---------------------------------------- */
/** @type {Record<string, object[]>} */
const interfaces = {};
for (const [host, ports] of Object.entries(obj(snap.interfaces))) {
  interfaces[host] = Object.entries(obj(ports)).map(([port, p]) => ({
    port,
    status: val(p.status),
    duplex: val(p.duplex),
    speed: val(p.speed),
    portType: val(p.port_type),
    linkType: val(p.link_type),
    description: val(p.description),
    portChannel: val(p.port_channel),
    pcProtocol: val(p.port_channel_protocol),
    runConfigObserved: Boolean(p.run_config_observed),
    cite: `interfaces.${host}.${port}`,
  }));
}
const physical = arr(snap.physical_health).map((p, i) => ({
  host: val(p.switch),
  port: val(p.port),
  status: val(p.status),
  speed: val(p.speed),
  duplex: val(p.duplex),
  media: val(p.media),
  inputErrors: num(p.input_errors),
  crcErrors: num(p.crc_errors),
  outputErrors: num(p.output_errors),
  /* Present in every source row and previously dropped on the floor. A counter the collector DID
     read is evidence; discarding it is a self-inflicted coverage gap. */
  lateCollisions: num(p.late_collisions),
  outputDrops: num(p.output_drops),
  poe: val(p.poe),
  risk: val(p.risk),
  /* The engine's own explanation for why this port has no counters — "[NOT OBSERVED] - no 'show
     interfaces' counters for this port; L1 error rate NOT assessed" — which `val()` nulls. Carried
     through so the reader gets the REASON, exactly as `l3.riskUnobserved` already does. */
  riskUnobserved: reason(p.risk),
  severity: val(p.severity),
  cite: `physical_health[${i}]`,
}));
const protocols = arr(snap.protocol_health).map((p, i) => ({
  host: val(p.switch),
  protocol: val(p.protocol),
  severity: val(p.severity),
  summary: val(p.summary),
  detail: val(p.detail),
  cite: `protocol_health[${i}]`,
}));
const endpoints = arr(snap.endpoint_identity).map((e, i) => ({
  host: val(e.host),
  port: val(e.port),
  vlan: val(e.vlan),
  ip: val(e.ip),
  mac: val(e.mac),
  macCount: num(e.mac_count),
  vendor: val(e.vendor),
  endpointClass: val(e.endpoint_class),
  confidence: val(e.confidence),
  evidence: val(e.evidence),
  cite: `endpoint_identity[${i}]`,
}));

/* coverage honesty: what the snapshot does NOT contain ----------------------- */
const coverage = {
  devicesInventoried: devices.filter((d) => d.inventoried).length,
  devicesOnTopologyOnly: devices.filter((d) => !d.inventoried).length,
  hostsWithRoutes: Object.keys(routes).length,
  hostsWithAcls: Object.keys(acls).length,
  hostsWithObjectGroups: Object.keys(objectGroups).length,
  /* Lines the PRODUCER could not model. These are the hot path for honesty: a definite verdict
     that silently steps over one of them is an overclaim. */
  aclLinesUnevaluable: Object.values(acls).flatMap((n) => Object.values(n).flat()).filter((l) => l.unevaluable).length,
  aclLinesTotal: Object.values(acls).flatMap((n) => Object.values(n).flat()).length,
  hostsWithInterfaces: Object.keys(interfaces).length,
  routableHosts: Object.keys(routes).sort(),
  aclHosts: Object.keys(acls).sort(),
  linksWithCentrality: links.filter((l) => l.betweenness !== null).length,
  aclSummary: obj(snap.acl_line_reachability?.summary),
  cite: "collection_completeness / coverage_matrix",
};

const out = {
  meta: {
    ...binding,
    schema: val(snap.schema),
    scriptVersion: val(snap.script_version),
    collectedAt: val(snap.collected_at),
    generatedAt: val(snap.generated_at),
  },
  tiers: arr(snap.cable_map?.tiers).map((t, i) => strs(t, `cable_map.tiers[${i}]`)),
  devices,
  links,
  findings,
  crossLayer,
  routes,
  acls,
  aclFindings,
  l3,
  objectGroups,
  interfaces,
  physical,
  protocols,
  endpoints,
  coverage,
  /* Source records the device and link figures were read from, under the paths their citations
     name (acceptance B6). Appended last so every earlier model path is unchanged. */
  cable_map: { nodes: cableMapNodes },
  health_scores: healthScores,
  link_centrality: linkCentrality,
};

mkdirSync(dirname(OUT), { recursive: true });
const text = JSON.stringify(out);
writeFileSync(OUT, text, "utf8");
console.log(`compiled ${SRC}`);
console.log(`     -> ${OUT}  (${(text.length / 1024).toFixed(0)} KB)`);
console.log(`  sha256(source, ${binding.sourceDigestForm}) = ${binding.sourceSha256}  (${binding.sourceBytes} bytes)`);
console.log(`  sha256(working tree, not bound) = ${workingTree.sha256}  (${workingTree.bytes} bytes)`);
console.log(
  `  devices=${devices.length} (inventoried=${coverage.devicesInventoried}, topology-only=${coverage.devicesOnTopologyOnly})`,
);
console.log(`  links=${links.length}  findings=${findings.length}  crossLayer=${crossLayer.length}`);
console.log(
  `  routes-hosts=${coverage.hostsWithRoutes}  acl-hosts=${coverage.hostsWithAcls}  iface-hosts=${coverage.hostsWithInterfaces}`,
);
console.log(
  `  physical=${physical.length}  protocols=${protocols.length}  endpoints=${endpoints.length}  aclFindings=${aclFindings.length}`,
);
