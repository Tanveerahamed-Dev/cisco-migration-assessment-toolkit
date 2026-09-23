/**
 * HopList.admin-distance.test.tsx — one structural null, one set of words, on every surface.
 *
 * THE DEFECT (2026-09-23 acceptance report, B1 item 14). For the same record — a connected route
 * whose `adminDistance` is null — the Inspector rendered "0 — a connected route's administrative
 * distance by definition" while the hop list rendered "not observed". One of them was wrong about
 * the evidence, and a reader comparing the two surfaces could not tell which. The owner of "is this
 * null structural?" is `claims.ts :: notApplicableReason`; the Inspector read it and the hop list did
 * not.
 *
 * THE CLASS, NOT THE FIELD. Every route field the hop list renders from a record goes through the
 * same owner, so the test walks every route record in the snapshot whose null the owner calls
 * structural — for each such field — and asserts the hop list's words are the Inspector's words.
 * The records are found from the compiled data, never listed.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, extname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import ts from "typescript";
import { afterEach, describe, expect, it } from "vitest";
import { notApplicableReason } from "../core/claims";
import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import type { RouteField } from "../core/claims";
import type { Flow, Trace } from "../core/types";
import { traceFlow } from "../forwarding/engine";
import { formatIpv4, hostAddressIn, parseInterfaceAddress } from "../forwarding/ip";
import { DevicePane } from "./DevicePane";
import { HopList } from "./HopList";
import { Inspector, setInspectorCite } from "./Inspector";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mounted: { root: Root; container: HTMLElement }[] = [];
function mount(ui: ReactNode): HTMLElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(ui));
  mounted.push({ root, container });
  return container;
}
afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
  act(() => {
    useInvestigation.getState().reset();
    useInvestigation.getState().setInspectorOpen(false);
  });
  setInspectorCite(null);
});

const squash = (s: string | null | undefined): string => (s ?? "").replace(/\s+/g, " ").trim();

/** The route fields the hop list renders from a route record. */
const ROUTE_FIELDS = ["adminDistance", "nextHop"] as const;

/* Flows from one observed subnet to a host address in every other observed subnet: every connected
   route the collected RIBs hold is then the winner or a beaten alternative on some hop. Derived
   from the snapshot's own L3 records, not typed in. */
const SUBNETS = [...new Map(fabric.l3.flatMap((r) => {
  const a = r.sviIp === null ? null : parseInterfaceAddress(r.sviIp);
  return a === null ? [] : [[`${a.prefix.base}/${a.prefix.bits}`, a.prefix] as const];
})).values()];
const TRACES: Trace[] = SUBNETS.flatMap((from) =>
  SUBNETS.flatMap((to) => {
    const src = hostAddressIn(from, 50);
    const dst = hostAddressIn(to, 10);
    if (src === null || dst === null || from === to) return [];
    const flow: Flow = { srcIp: formatIpv4(src), dstIp: formatIpv4(dst), protocol: "tcp", dstPort: 443, srcPort: null };
    return [traceFlow(flow)];
  }),
);

/** The Inspector's rendered words for one field of the record a cite names. */
function inspectorWords(cite: string, field: string): string {
  const c = mount(<Inspector cite={cite} forceOpen />);
  const row = [...c.querySelectorAll("#inspector-panel-data .insp-kv__row")].find(
    (r) => squash(r.querySelector(".insp-kv__key")?.textContent) === field,
  );
  if (row === undefined) throw new Error(`the Inspector shows no ${field} row for ${cite}`);
  return squash(row.querySelector(".insp-kv__val")?.textContent);
}

describe("a structural null in a route renders the same words in the hop list and the Inspector", () => {
  it("rests on at least one connected route with no recorded administrative distance on a traced hop", () => {
    const hit = TRACES.some((t) =>
      t.hops.some((h) => h.evidence.some((e) => e.kind === "route" && /routes\.[^[]+\[\d+\]/.test(e.cite))),
    );
    expect(hit).toBe(true);
    const structural = Object.values(fabric.routes).flat().filter((r) => notApplicableReason(r, "adminDistance") !== null);
    expect(structural.length, "precondition: the snapshot holds a connected/local route with a null AD").toBeGreaterThan(0);
  });

  it("the reported instance: the winning connected route of a delivered hop, AD null", () => {
    /* Whichever traced hop WON on a connected route with a null AD — found, not named. */
    let found: { t: Trace; cite: string } | null = null;
    for (const t of TRACES) {
      for (const h of t.hops) {
        for (const e of h.evidence) {
          if (e.kind !== "route" || found !== null) continue;
          const m = /^routes\.([^[]+)\[(\d+)\]$/.exec(e.cite);
          const r = m ? fabric.routes[m[1]!]?.[Number(m[2])] : undefined;
          if (r !== undefined && r.adminDistance === null && notApplicableReason(r, "adminDistance") !== null) found = { t, cite: e.cite };
        }
      }
    }
    expect(found, "precondition: some traced hop took a connected route with a null AD").not.toBeNull();
    const c = mount(<HopList trace={found!.t} activeIndex={0} onSelect={() => {}} />);
    const fact = [...c.querySelectorAll(".hop__fact")].find(
      (f) => f.querySelector(".hop__key")?.textContent?.startsWith("Route") && f.querySelector(`[aria-label="Open source record ${found!.cite}"]`) !== null,
    );
    expect(fact, `no Route row cites ${found!.cite}`).toBeDefined();
    const inspector = inspectorWords(found!.cite, "adminDistance");
    /* The wording changed on 2026-09-23 (acceptance B1, "allows no inference exemption"): the value
       slot of a null may not lead with the digit 0 — the record carries no number, so the reading
       says "not recorded" and names the platform convention as a reason, not as the value. */
    expect(inspector).toMatch(/^not recorded — the record carries no value; a (connected|local) route's administrative distance is zero by platform convention/);
    expect(inspector).not.toMatch(/^0\b/);
    expect(squash(fact!.textContent)).toContain(inspector);
    expect(squash(fact!.textContent)).not.toMatch(/administrative distance: not observed/);
  });

  it("every rendered route field whose null is structural reads exactly as the Inspector reads it", () => {
    let compared = 0;
    for (const t of TRACES) {
      if (t.hops.length === 0) continue;
      const c = mount(<HopList trace={t} activeIndex={0} onSelect={() => {}} />);
      for (const cell of c.querySelectorAll<HTMLElement>("[data-route-field]")) {
        const field = cell.dataset["routeField"]!;
        const cite = cell.dataset["routeCite"]!;
        const record = (fabric.routes[/^routes\.([^[]+)\[/.exec(cite)?.[1] ?? ""] ?? [])[Number(/\[(\d+)\]$/.exec(cite)?.[1])];
        expect(record, `the hop list cites ${cite}, which does not resolve`).toBeDefined();
        const na = notApplicableReason(record, field);
        if (na === null) continue;
        const words = squash(cell.textContent);
        expect(words, `${cite}.${field} in the hop list`).toBe(na);
        expect(words).not.toMatch(/not observed/);
        expect(inspectorWords(cite, field), `${cite}.${field} in the Inspector`).toBe(words);
        compared += 1;
      }
      for (const m of mounted.splice(0)) {
        act(() => m.root.unmount());
        m.container.remove();
      }
    }
    // Both fields, and more than one record: a comparison that never ran proves nothing.
    expect(compared, "no structural null was compared at all").toBeGreaterThan(1);
  });

  it("marks every route field it renders, so none can escape the comparison above", () => {
    const t = TRACES.find((x) => x.hops.some((h) => h.alternatives.length > 0))!;
    const c = mount(<HopList trace={t} activeIndex={0} onSelect={() => {}} />);
    const fields = new Set([...c.querySelectorAll<HTMLElement>("[data-route-field]")].map((e) => e.dataset["routeField"]));
    for (const f of ROUTE_FIELDS) expect(fields.has(f), `no rendered ${f} carries data-route-field`).toBe(true);
  });
});

/* ── every surface, every route record: one owner, one set of words ─────────
   B1 failed twice for the same class. The 2026-09-23 fix unified the hop list with the Inspector and
   left the Device pane's Routing tab — the third surface that prints the same record — reading the
   field raw, so `routes.core1[6]` was "0 — … by definition" in the Path panel and "administrative
   distance: not observed" on the Routing tab. The comparison below is not scoped to the two surfaces
   that were reported: it renders the Routing tab of EVERY host that holds a RIB, finds each route
   record's cells by the record's citation and the column's header (never by a data attribute the fix
   adds), and requires the words to be the Inspector's words for the same record and field. */

/** The Device pane's Routing tab for `host`, mounted. */
function routingTab(host: string): HTMLElement {
  act(() => {
    useInvestigation.getState().reset();
    useInvestigation.getState().selectDevice(host);
    useInvestigation.getState().setEvidenceTab("routing");
  });
  return mount(<DevicePane />);
}

/** cite -> { header -> cell words } for the routing-table grid in `c`. */
function routingCells(c: HTMLElement, host: string): Map<string, Record<string, string>> {
  const grid = c.querySelector<HTMLElement>(`[role="grid"][aria-label="Routing table for ${host}"]`);
  if (grid === null) throw new Error(`no routing-table grid for ${host}`);
  const [head, ...rows] = [...grid.querySelectorAll('[role="row"]')];
  const headers = [...head!.querySelectorAll('[role="columnheader"]')].map((h) => squash(h.textContent));
  const out = new Map<string, Record<string, string>>();
  for (const row of rows) {
    const cells = [...row.querySelectorAll('[role="gridcell"],[role="rowheader"]')].map((x) => squash(x.textContent));
    const cite = (row.querySelector(".ui-cite")?.getAttribute("aria-label") ?? "").replace(/^Open source record /, "");
    out.set(cite, Object.fromEntries(headers.map((h, i) => [h, cells[i] ?? ""])));
  }
  return out;
}

describe("B1: a route field reads the same on the Routing tab, the Path panel and the Inspector", () => {
  it("the reported record, routes.core1[6].adminDistance: identical on all three surfaces, and never a bare 0", () => {
    const cite = "routes.core1[6]";
    const record = fabric.routes["core1"]?.[6];
    expect(record?.adminDistance, "precondition: the reported record still carries no AD").toBeNull();

    const inspector = inspectorWords(cite, "adminDistance");
    const routing = routingCells(routingTab("core1"), "core1").get(cite)?.["AD"];
    const trace = TRACES.find((t) => t.hops.some((h) => h.evidence.some((e) => e.cite === cite) || h.alternatives.some((a) => a.cite === cite)));
    expect(trace, `precondition: some traced hop shows ${cite}`).toBeDefined();
    const hop = mount(<HopList trace={trace!} activeIndex={0} onSelect={() => {}} />);
    const path = [...hop.querySelectorAll<HTMLElement>('[data-route-field="adminDistance"]')].find((e) => e.dataset["routeCite"] === cite);
    expect(path, `the Path panel renders no AD for ${cite}`).toBeDefined();

    const words = { inspector, routing, path: squash(path!.textContent) };
    expect(words.routing, "the Routing tab reads the record as the Inspector does").toBe(inspector);
    expect(words.path, "the Path panel reads the record as the Inspector does").toBe(inspector);
    for (const [where, w] of Object.entries(words)) {
      expect(w, `${where}: a null AD may not be presented as the number 0`).not.toMatch(/^0\b/);
      expect(w, `${where}: a structural null is not an evidence gap`).not.toMatch(/not observed/);
    }
  });

  it("every route record on every Routing tab reads each route field exactly as the Inspector reads it", () => {
    let compared = 0;
    const fields = { AD: "adminDistance", "Next hop": "nextHop" } as const;
    for (const host of fabric.coverage.routableHosts) {
      const cells = routingCells(routingTab(host), host);
      expect(cells.size, `${host}: the grid shows every route record`).toBe(fabric.routes[host]!.length);
      for (const [cite, row] of cells) {
        for (const [header, field] of Object.entries(fields)) {
          expect(row[header], `${cite} ${header} on the Routing tab`).toBe(inspectorWords(cite, field));
          compared += 1;
        }
      }
      for (const m of mounted.splice(0)) {
        act(() => m.root.unmount());
        m.container.remove();
      }
    }
    expect(compared).toBe(Object.values(fabric.routes).flat().length * 2);
  });
});

/* ── the parser guard: no surface formats Route.adminDistance itself ─────────
   Same construction as src/core/band-read.guard.test.ts, for the same reason: a hand-made list of
   surfaces is the defect shape, and B1 fell through one twice. The invariant is stated about the
   CLASS — no expression outside the owner (the module that DECLARES `routeFieldReading`, found by
   the type checker through `claims.ts`'s export, never typed in) reads the `adminDistance` declared by
   `RouteEntry`. "A route record" is resolved by the TYPE CHECKER, not by a variable name; a read is
   property access, optional chaining, element access by literal OR by a key whose type admits
   "adminDistance" (`route[field]` with `field: "nextHop" | "adminDistance"`), and destructuring.
   A module that needs the number for RANKING asks the owner too (`adminDistanceRank`): deciding that
   a null reads as 0 is exactly the judgement B1 is about, so it may not be made twice. */

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const ROOT = resolve(SRC, "..");
const TYPES = join(SRC, "core", "types.ts");
/** The public door every surface imports the owner through; the OWNER itself is where it is declared. */
const CLAIMS = join(SRC, "core", "claims.ts");
const ENGINE = join(SRC, "forwarding", "engine.ts");
const normPath = (p: string): string => resolve(p).split(sep).join("/").toLowerCase();

function walkSources(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (name.startsWith("_")) continue; // vitest.config.ts: "src/**/_*/**", "src/**/_*"
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walkSources(p, out);
    else if ([".ts", ".tsx"].includes(extname(p)) && !/\.test\.tsx?$/.test(p) && !p.endsWith(".d.ts")) out.push(p);
  }
  return out;
}

function compilerOptions(): ts.CompilerOptions {
  const cfg = ts.readConfigFile(join(ROOT, "tsconfig.json"), ts.sys.readFile);
  if (cfg.error) throw new Error(ts.flattenDiagnosticMessageText(cfg.error.messageText, "\n"));
  return { ...ts.parseJsonConfigFileContent(cfg.config, ts.sys, ROOT).options, noEmit: true };
}

interface FieldRead { file: string; line: number; text: string }

/** Every read, in files `consider` accepts, of the route `field` (default `adminDistance`) that `RouteEntry` declares. */
function findAdminDistanceReads(program: ts.Program, consider: (f: string) => boolean, field: RouteField = "adminDistance"): FieldRead[] {
  const checker = program.getTypeChecker();
  const typesSf = program.getSourceFiles().find((sf) => normPath(sf.fileName) === normPath(TYPES));
  if (!typesSf) throw new Error("types.ts is not in the program");
  let found: ts.Declaration | undefined;
  typesSf.forEachChild((n) => {
    if (ts.isInterfaceDeclaration(n) && n.name.text === "RouteEntry") {
      for (const m of n.members) if (m.name && ts.isIdentifier(m.name) && m.name.text === field) found = m;
    }
  });
  if (!found) throw new Error(`RouteEntry.${field} not found in types.ts — the guard has nothing to resolve against`);
  const decl: ts.Declaration = found;
  const carries = (type: ts.Type): boolean => {
    for (const t of type.isUnionOrIntersection() ? type.types : [type]) {
      const prop = checker.getPropertyOfType(checker.getApparentType(t), field);
      if (prop && (prop.declarations ?? []).includes(decl)) return true;
    }
    return false;
  };
  const symbolIs = (sym: ts.Symbol | undefined): boolean => {
    const seen = new Set<ts.Symbol>();
    const stack = sym ? [sym] : [];
    while (stack.length) {
      const s = stack.pop()!;
      if (seen.has(s)) continue;
      seen.add(s);
      if ((s.declarations ?? []).includes(decl)) return true;
      if (s.flags & ts.SymbolFlags.Alias) stack.push(checker.getAliasedSymbol(s));
      for (const r of checker.getRootSymbols(s)) if (r !== s) stack.push(r);
    }
    return false;
  };
  /** A key expression whose type admits the literal `field` (a literal, a union, a generic bound). */
  const keyAdmits = (key: ts.Expression): boolean => {
    const parts = (tt: ts.Type): ts.Type[] => {
      const c = tt.isTypeParameter() ? checker.getBaseConstraintOfType(tt) : tt;
      if (!c) return [];
      return c.isUnion() ? c.types.flatMap(parts) : [c];
    };
    return parts(checker.getTypeAtLocation(key)).some((p) => p.isStringLiteral() && p.value === field);
  };
  const out: FieldRead[] = [];
  for (const sf of program.getSourceFiles()) {
    if (sf.isDeclarationFile || !consider(sf.fileName)) continue;
    const record = (node: ts.Node): void => {
      const { line } = sf.getLineAndCharacterOfPosition(node.getStart(sf));
      out.push({ file: sf.fileName, line: line + 1, text: node.getText(sf).replace(/\s+/g, " ").slice(0, 120) });
    };
    const visit = (node: ts.Node): void => {
      if (ts.isPropertyAccessExpression(node) && node.name.text === field) {
        if (symbolIs(checker.getSymbolAtLocation(node.name)) || carries(checker.getTypeAtLocation(node.expression))) record(node);
      } else if (ts.isElementAccessExpression(node) && carries(checker.getTypeAtLocation(node.expression)) && keyAdmits(node.argumentExpression)) {
        record(node);
      } else if (ts.isObjectBindingPattern(node) && carries(checker.getTypeAtLocation(node))) {
        for (const el of node.elements) {
          const key = el.propertyName ?? el.name;
          if ((ts.isIdentifier(key) || ts.isStringLiteralLike(key)) && key.text === field && !el.dotDotDotToken) record(el);
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(sf);
  }
  return out;
}

/**
 * The owner: the file that DECLARES the `routeFieldReading` that `claims.ts` exports — resolved
 * through any re-export by the type checker, so moving the owner cannot silently move the guard.
 */
function ownerOf(program: ts.Program): string {
  const checker = program.getTypeChecker();
  const claimsSf = program.getSourceFiles().find((sf) => normPath(sf.fileName) === normPath(CLAIMS));
  const mod = claimsSf ? checker.getSymbolAtLocation(claimsSf) : undefined;
  if (!mod) throw new Error("claims.ts is not in the program");
  let sym = checker.getExportsOfModule(mod).find((s) => s.name === "routeFieldReading");
  if (!sym) throw new Error("claims.ts does not export routeFieldReading — the owner has no public door");
  if (sym.flags & ts.SymbolFlags.Alias) sym = checker.getAliasedSymbol(sym);
  const decl = sym.declarations?.find((d) => ts.isFunctionDeclaration(d));
  if (!decl) throw new Error("routeFieldReading resolves to no function declaration");
  return decl.getSourceFile().fileName;
}

/**
 * Every module `file` loads AT RUNTIME, transitively: `import`/`export … from` edges that survive
 * type erasure (`import type`, `export type` and all-type-only named lists are dropped), resolved by
 * the compiler's own module resolution.
 */
function runtimeImportClosure(program: ts.Program, file: string): Set<string> {
  const opts = program.getCompilerOptions();
  const seen = new Set<string>();
  const stack = [file];
  while (stack.length) {
    const f = stack.pop()!;
    if (seen.has(normPath(f))) continue;
    seen.add(normPath(f));
    const sf = program.getSourceFile(f);
    if (!sf) continue;
    for (const st of sf.statements) {
      let spec: ts.Expression | undefined;
      if (ts.isImportDeclaration(st)) {
        const cl = st.importClause;
        const typeOnly =
          cl !== undefined &&
          (cl.isTypeOnly ||
            (cl.name === undefined && cl.namedBindings !== undefined && ts.isNamedImports(cl.namedBindings) &&
              cl.namedBindings.elements.length > 0 && cl.namedBindings.elements.every((e) => e.isTypeOnly)));
        if (!typeOnly) spec = st.moduleSpecifier;
      } else if (ts.isExportDeclaration(st) && st.moduleSpecifier && !st.isTypeOnly) {
        spec = st.moduleSpecifier;
      }
      if (!spec || !ts.isStringLiteral(spec)) continue;
      const r = ts.resolveModuleName(spec.text, sf.fileName, opts, ts.sys).resolvedModule;
      if (r && !r.isExternalLibraryImport && /\.tsx?$/.test(r.resolvedFileName)) stack.push(r.resolvedFileName);
    }
  }
  return seen;
}

describe("B1 structural guard: Route.adminDistance is read only by its owner, the module declaring routeFieldReading", () => {
  const files = walkSources(SRC);
  let memo: ts.Program | null = null;
  const program = (): ts.Program => (memo ??= ts.createProgram(files, compilerOptions()));

  it("walks the whole denominator vitest collects over", () => {
    const cfg = readFileSync(join(ROOT, "vitest.config.ts"), "utf8");
    expect(cfg).toContain(`include: ["src/**/*.test.ts", "src/**/*.test.tsx"]`);
    expect(cfg).toContain(`exclude: [...configDefaults.exclude, "src/**/_*/**", "src/**/_*"]`);
    const rel = files.map((f) => relative(SRC, f).split(sep).join("/"));
    for (const must of ["core/claims.ts", "panels/HopList.tsx", "panels/DevicePane.tsx", "panels/Inspector.tsx", "panels/EvidencePane.tsx", "forwarding/engine.ts"]) {
      expect(rel).toContain(must);
    }
    expect(files.length).toBeGreaterThan(60);
  });

  it("finds no read of RouteEntry.adminDistance outside the owner", () => {
    const owner = ownerOf(program());
    const inTree = new Set(files.map(normPath));
    const reads = findAdminDistanceReads(program(), (f) => inTree.has(normPath(f)));
    // The owner does read it — which also proves the resolver resolves on the real tree.
    expect(reads.some((r) => normPath(r.file) === normPath(owner)), "the owner reads RouteEntry.adminDistance").toBe(true);
    const outside = reads
      .filter((r) => normPath(r.file) !== normPath(owner))
      .map((r) => `${relative(SRC, r.file).split(sep).join("/")}:${r.line}  ${r.text}`);
    expect(outside).toEqual([]);
  }, 90_000);

  /* `nextHop` is the owner's other field, and the same B1 class (a connected route's null next hop
     rendered "not observed" — the 2026-09-21 finding). Unlike the distance, the engine must read a
     next hop's VALUE to forward, so the invariant for it is scoped to the RENDER surfaces: no React
     module (every `.tsx` under src, found by walking, not listed) reads `RouteEntry.nextHop` outside
     the owner; each prints it through `RouteFieldValue`. Residual: a `.ts` helper that formats the
     field for a surface is not caught by this half of the guard. */
  it("finds no render module (.tsx) reading RouteEntry.nextHop outside the owner", () => {
    const owner = ownerOf(program());
    const surfaces = new Set(files.filter((f) => f.endsWith(".tsx")).map(normPath));
    expect(surfaces.size, "the walk found the React surfaces").toBeGreaterThan(20);
    const reads = findAdminDistanceReads(program(), (f) => surfaces.has(normPath(f)), "nextHop");
    // Live on the real tree: the owner itself reads the field (it is a .ts module, so it is checked here directly).
    expect(findAdminDistanceReads(program(), (f) => normPath(f) === normPath(owner), "nextHop").length).toBeGreaterThan(0);
    expect(reads.map((r) => `${relative(SRC, r.file).split(sep).join("/")}:${r.line}  ${r.text}`)).toEqual([]);
  }, 90_000);

  /* The engine ranks tied routes by administrative distance, and "a null ranks as 0" is the same
     judgement the rendering makes, so the engine must ask the owner too. It can only do that if the
     owner never loads the engine back: `claims.ts` does (and evaluates an engine binding at module
     load — `REFUSAL_UNDECIDING`), so an owner living there would force an import cycle on exactly the
     module that has to consult it. */
  it("the owner is a module the forwarding engine can import: its runtime imports never reach the engine", () => {
    const owner = ownerOf(program());
    const closure = runtimeImportClosure(program(), owner);
    expect(closure.has(normPath(owner)), "the closure walk starts at the owner").toBe(true);
    expect(
      [...closure].map((f) => relative(SRC, f).split(sep).join("/").toLowerCase()),
      `${relative(SRC, owner)} loads the engine at runtime`,
    ).not.toContain(relative(SRC, ENGINE).split(sep).join("/").toLowerCase());
    // The walk is live: from claims.ts it DOES reach the engine.
    expect(runtimeImportClosure(program(), CLAIMS).has(normPath(ENGINE))).toBe(true);
  }, 90_000);

  it("is live: a planted module reading the field under any name, by key or by destructuring, is flagged", () => {
    const planted = join(SRC, "core", "__planted_ad_reader.ts").split(sep).join("/");
    const source = [
      `import type { RouteEntry, Hop } from "./types";`,
      `export const a = (zq: RouteEntry) => String(zq.adminDistance);`,
      `export const b = ({ adminDistance }: RouteEntry) => adminDistance ?? 0;`,
      `export const c = (x: RouteEntry | undefined) => x?.adminDistance;`,
      `export const d = (y: RouteEntry) => y["adminDistance"];`,
      `export const e = <K extends "nextHop" | "adminDistance">(w: RouteEntry, k: K) => w[k];`,
      `export const f = (h: Hop) => h.alternatives.map((r) => r.adminDistance);`,
      `interface Other { adminDistance: number }`,
      `export const g = (o: Other) => o.adminDistance;`,
      `export const h = (y: RouteEntry, k: "prefix" | "source") => y[k];`,
    ].join("\n");
    const opts = compilerOptions();
    const host = ts.createCompilerHost(opts);
    const origGet = host.getSourceFile.bind(host);
    host.getSourceFile = (name, lang, onErr, create) =>
      normPath(name) === normPath(planted) ? ts.createSourceFile(name, source, lang, true, ts.ScriptKind.TS) : origGet(name, lang, onErr, create);
    const origExists = host.fileExists.bind(host);
    host.fileExists = (name) => normPath(name) === normPath(planted) || origExists(name);
    const program = ts.createProgram([planted, TYPES], opts, host);
    const lines = findAdminDistanceReads(program, (f) => normPath(f) === normPath(planted)).map((r) => r.line).sort((p, q) => p - q);
    // Lines 2-7 read it six ways under six names; line 9 is an unrelated type's field and line 10 a
    // key that cannot be "adminDistance" — neither may be flagged.
    expect(lines).toEqual([2, 3, 4, 5, 6, 7]);
  }, 90_000);
});
