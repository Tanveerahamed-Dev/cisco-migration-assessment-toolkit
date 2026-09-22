/**
 * Inspector.tsx — the raw-evidence inspector. Grafana Explore's Inspector, for network evidence.
 *
 * The promise it keeps: nothing this application says is unauditable. From any claim a reader can
 * reach the exact record behind it, the exact file that record was compiled from, the sha256 and
 * byte length of that file, and the exact list of things nobody collected.
 *
 * THE CITATION CHAIN, AND WHY IT HAS TWO LAYERS.
 * Every compiled record carries a `cite` — a path into the SOURCE snapshot
 * (`meta.source`, ~3 MB), not into the compiled model. 628 of the 652 distinct citations in the
 * shipped data therefore do NOT resolve against `fabric.json`: `punchlist[0]` names a snapshot
 * array this model does not contain. `resolveCite` alone would report almost every citation as
 * broken, which would be a false alarm, and a component that cries wolf gets ignored — which in
 * this product means a real broken citation gets ignored too.
 *
 * So resolution has two layers and the reader is told which one answered:
 *   1. MODEL     — the path resolves inside the compiled model (`routes.core1[0]`).
 *   2. BEARER    — no path hit, but one or more compiled records CARRY this citation. That record
 *                  is the compiled form of the source record, and its position in the model is
 *                  shown so the JSON tab can reveal it.
 *   3. UNRESOLVED— neither. That is a broken evidence chain and it is rendered loudly.
 * The source record itself lives in a file that is not bundled with this build, and the Provenance
 * tab says exactly that, with the file name, sha256 and byte length needed to go and read it.
 *
 * Opening this panel never touches the investigation: no selection is cleared, no navigation
 * happens, nothing is re-run (design brief §2.4, §5.3).
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactElement,
  type ReactNode,
} from "react";
import { aclUndecidability } from "../core/acl-coverage";
import { bandObserved } from "../core/band-qualification";
import { deviceById, fabric, findingById, linkById, resolveCite } from "../core/data";
import { missingInventoryFields, notApplicableReason } from "../core/claims";
import { placeholderZero } from "../core/placeholders";
import { useInvestigation } from "../core/store";
import type { Cite } from "../core/types";
import { IconClose, IconCopy } from "../ui/icons";
import {
  Button,
  Chip,
  Empty,
  IconButton,
  LiveRegion,
  NotObserved,
  Tabs,
  TabPanel,
  orNotObserved,
  type TabItem,
} from "../ui/primitives";
import { JsonView, useCopyToClipboard } from "./JsonView";
import { lineEvaluability } from "../forwarding/engine";
import { producerFieldNotEmitted } from "./producer-emission";
import type { AclLine } from "../core/types";
import "./Inspector.css";

/* ── the active citation: module state, so any surface can open the Inspector ──
   It does NOT live in the investigation store: `store.ts` is frozen, and a citation is chrome —
   which record you are reading — not part of the investigation the URL reproduces (design brief
   §5.4). Keeping it out of the store is also what guarantees that opening the Inspector cannot
   perturb a selection. */

let activeCite: Cite | null = null;
let focusReturn: HTMLElement | null = null;
const citeListeners = new Set<() => void>();

const emit = (): void => {
  for (const fn of citeListeners) fn();
};

/** Point the Inspector at a citation and show it. The one call every `Cite` affordance makes. */
export function openInspector(cite: Cite | null): void {
  activeCite = cite;
  const el = typeof document === "undefined" ? null : document.activeElement;
  focusReturn = el instanceof HTMLElement ? el : null;
  emit();
  useInvestigation.getState().setInspectorOpen(true);
}

/** Change the citation without opening or closing anything. */
export function setInspectorCite(cite: Cite | null): void {
  activeCite = cite;
  emit();
}

function useActiveCite(): Cite | null {
  return useSyncExternalStore(
    (cb) => {
      citeListeners.add(cb);
      return () => citeListeners.delete(cb);
    },
    () => activeCite,
    () => null,
  );
}

/* ── citation resolution ───────────────────────────────────────────────────── */

export type CiteResolutionKind = "model" | "bearer" | "unresolved";

export interface CiteResolution {
  kind: CiteResolutionKind;
  /** The record to display. `undefined` only when kind is "unresolved". */
  record: unknown;
  /** Where the record sits inside the compiled model, for the JSON tree. */
  modelPath: string | null;
  /** Every compiled record carrying this citation — more than one is legitimate and is shown. */
  bearers: string[];
  /**
   * The records carrying this citation in a compiled document OTHER than the one `record` came from,
   * rendered beside it rather than behind a switcher. The forwarding engine reads interface ACL
   * bindings from `acl-bindings.json`, not from `fabric.json`; a binding claim cited
   * `interfaces.core1.Vlan30` used to resolve to the fabric interface record — status, duplex,
   * description, and no ACL field — so the record that CARRIED the claim was unreachable
   * (2026-09-21 critic, B6).
   */
  companions: { path: string; record: unknown }[];
}

/* ── the sidecar documents ─────────────────────────────────────────────────
   Every compiled JSON next to the forwarding engine that binds the snapshot's bytes
   (`meta.sourceSha256`) is a citation bearer too — found by content, not listed by name, so a new
   sidecar compiler cannot fall outside the Inspector the way acl-bindings.json once did. A sidecar
   path is written `<file>#<path inside it>`. */
const SIDECAR_MODULES = import.meta.glob("../forwarding/*.json", { eager: true, import: "default" }) as Record<string, unknown>;

const SIDECARS: ReadonlyMap<string, unknown> = new Map(
  Object.entries(SIDECAR_MODULES)
    .filter(([, doc]) => {
      const meta = (doc as { meta?: { sourceSha256?: unknown } } | null)?.meta;
      return typeof meta?.sourceSha256 === "string";
    })
    .map(([p, doc]) => [p.slice(p.lastIndexOf("/") + 1), doc] as const)
    .sort(([a], [b]) => a.localeCompare(b)),
);

/** The compiled document a candidate path lives in: "fabric.json" or a sidecar file name. */
export function documentOf(path: string): string {
  const hash = path.indexOf("#");
  return hash > 0 && SIDECARS.has(path.slice(0, hash)) ? path.slice(0, hash) : "fabric.json";
}

/** Resolve a candidate path — a fabric path, or `<sidecar>#<path>`. */
export function resolveCandidate(path: string): unknown {
  const doc = documentOf(path);
  if (doc === "fabric.json") return resolveCite(path);
  let cur: unknown = SIDECARS.get(doc);
  for (const part of path.slice(doc.length + 1).split(/[.[]/).map((p) => p.replace(/]$/, "")).filter(Boolean)) {
    if (cur === null || typeof cur !== "object") return undefined;
    cur = Array.isArray(cur) ? cur[Number(part)] : (cur as Record<string, unknown>)[part];
  }
  return cur;
}

/**
 * cite -> the model paths of every record carrying it. Built once, lazily, by one walk of the
 * compiled model. Module-level rather than a React memo because it is derived from a frozen
 * import and is identical for every mount.
 */
let bearerIndex: ReadonlyMap<string, string[]> | null = null;

export function citeBearers(): ReadonlyMap<string, string[]> {
  if (bearerIndex) return bearerIndex;
  const map = new Map<string, string[]>();
  const walk = (value: unknown, path: string): void => {
    if (Array.isArray(value)) {
      value.forEach((v, i) => walk(v, `${path}[${i}]`));
      return;
    }
    if (typeof value !== "object" || value === null) return;
    const rec = value as Record<string, unknown>;
    const cite = rec["cite"];
    if (typeof cite === "string") {
      const list = map.get(cite);
      if (list) list.push(path);
      else map.set(cite, [path]);
    }
    for (const k of Object.keys(rec)) walk(rec[k], path === "" || path.endsWith("#") ? `${path}${k}` : `${path}.${k}`);
  };
  walk(fabric as unknown, "");
  // The sidecars follow the fabric, so a citation's first candidate stays the fabric record.
  for (const [name, doc] of SIDECARS) walk(doc, `${name}#`);
  bearerIndex = map;
  return map;
}

/**
 * Every place in the compiled model that can answer this citation, best first: the citation path
 * itself when it resolves, then each record that carries the citation. Deduped, because a record
 * whose `cite` is its own model path legitimately appears in both.
 */
export function citationCandidates(cite: Cite): string[] {
  const out: string[] = [];
  if (resolveCite(cite) !== undefined) out.push(cite);
  for (const p of citeBearers().get(cite) ?? []) if (!out.includes(p)) out.push(p);
  return out;
}

export function resolveCitation(cite: Cite | null, which = 0): CiteResolution {
  if (cite === null)
    return {
      kind: "unresolved",
      record: undefined,
      modelPath: null,
      bearers: [],
      companions: [],
    };
  const bearers = citationCandidates(cite);
  /* `which` indexes the CANDIDATE list, not the bearer list. Indexing only bearers made the
     switcher inert whenever the citation also resolved by path: the reader clicked a second
     record and the panel kept showing the first, with nothing to say why. */
  const path = bearers[Math.min(Math.max(0, which), bearers.length - 1)];
  if (path === undefined) {
    return { kind: "unresolved", record: undefined, modelPath: null, bearers, companions: [] };
  }
  const doc = documentOf(path);
  return {
    kind: path === cite && resolveCite(cite) !== undefined ? "model" : "bearer",
    record: resolveCandidate(path),
    modelPath: path,
    bearers,
    companions: bearers.filter((b) => documentOf(b) !== doc).map((b) => ({ path: b, record: resolveCandidate(b) })),
  };
}

/* ── panel geometry ────────────────────────────────────────────────────────
   The px figures mirror --inspector-min / --inspector-max in tokens.css at a 16px root. They are
   here as numbers because a drag handler has to clamp arithmetic, which CSS cannot express; the
   stylesheet remains the only place a colour, a type size or a duration is chosen. */
const MIN_H = 200;
const MAX_H = 632;
const DEFAULT_H = 316;
const STORE_KEY = "atlas-scope.inspector.height";

const clampH = (n: number): number => Math.max(MIN_H, Math.min(MAX_H, Math.round(n)));

function readStoredHeight(): number {
  try {
    const raw = window.localStorage.getItem(STORE_KEY);
    const n = raw === null ? Number.NaN : Number(raw);
    return Number.isFinite(n) ? clampH(n) : DEFAULT_H;
  } catch {
    /* Private mode and blocked site data both throw on access, not on read. A preference that
       cannot be stored is not an error worth showing anyone. */
    return DEFAULT_H;
  }
}

/* ── small rendering helpers ───────────────────────────────────────────────── */

function KeyRow({
  label,
  children,
  mono = false,
}: {
  label: string;
  children: ReactNode;
  mono?: boolean;
}): ReactElement {
  return (
    <div className="insp-kv__row">
      <dt className="insp-kv__key">{label}</dt>
      <dd className={mono ? "insp-kv__val insp-kv__val--mono" : "insp-kv__val"}>{children}</dd>
    </div>
  );
}

const typeOf = (v: unknown): string =>
  v === null ? "null" : Array.isArray(v) ? "array" : typeof v;

/** One field of a resolved record. Nested structures are summarised and read in full in the JSON tab. */
function FieldValue({
  name,
  value,
  record,
  path = null,
}: {
  name: string;
  value: unknown;
  record?: unknown;
  path?: string | null;
}): ReactElement {
  /* A value the compiler filled in for a key the collector never emitted is not an observation,
     whatever it looks like (`false`, `[]`). Asked FIRST, so neither the empty-array reading below
     nor a bare boolean can present it as the collector's testimony (./producer-emission.ts). */
  const notEmitted = producerFieldNotEmitted(path, record, name);
  if (notEmitted !== null) return <NotObserved what={name} why={notEmitted} />;
  if (value === null) {
    /* A structural null (no port constraint on an `ip` line, no next hop on a connected route) is
       not missing evidence; saying "not observed" there would dilute the marker where it matters. */
    const na = record === undefined ? null : notApplicableReason(record, name);
    if (na !== null) return <span className="insp-val insp-val--meta" data-not-applicable="true">{na}</span>;
    return <NotObserved what={name} compact />;
  }
  /* A device field every inventoried device reports as 0 is a likely absence, not a count — the same
     reading the Device pane gives it, from the same owner (core/placeholders.ts). */
  const device = record === undefined ? undefined : fabric.devices.find((d) => d === record);
  const ph = device === undefined ? null : placeholderZero(device, name);
  if (ph !== null) return <NotObserved what={name} why={`${ph.reason}; the record carries 0`} />;
  if (Array.isArray(value)) {
    if (value.length === 0) {
      /* An EMPTY array is an observation: the collector looked and found none. It must not borrow
         the not-observed treatment, or the two become indistinguishable. */
      return <span className="insp-val insp-val--meta">[ ] empty — 0 items</span>;
    }
    const allPrimitive = value.every((v) => v === null || typeof v !== "object");
    return (
      <span className="insp-val">
        {allPrimitive
          ? value.map((v, i) => (
              <span key={i} className="insp-val__item">
                {v === null ? <NotObserved compact /> : String(v)}
              </span>
            ))
          : `${value.length} records — read them in the JSON tab`}
      </span>
    );
  }
  if (typeof value === "object") {
    const n = Object.keys(value as Record<string, unknown>).length;
    return (
      <span className="insp-val insp-val--meta">
        {n === 0 ? "{ } empty — 0 keys" : `${n} keys — read them in the JSON tab`}
      </span>
    );
  }
  if (typeof value === "string") {
    /* orNotObserved also catches the engine's own `[NOT OBSERVED] - reason` marker and keeps the
       reason, which is why a raw string never goes straight into the DOM here. */
    return <span className="insp-val">{orNotObserved(value, (s) => s, { what: name })}</span>;
  }
  return <span className="insp-val insp-val--num">{String(value)}</span>;
}

function GapSection({
  title,
  observed,
  total,
  meaning,
  items,
}: {
  title: string;
  observed: number;
  total: number;
  meaning: string;
  items: readonly string[];
}): ReactElement {
  /* Column measure from this section's own longest member. A single width across every section
     would either strand half the panel on a list of eight-character host names or wrap the link
     descriptions. The bounds keep one freak-length member from collapsing the list to one column.
     Derived from the data, so it is stable across runs. */
  const widest = items.reduce((n, s) => Math.max(n, s.length), 0);
  const col = `${Math.min(62, Math.max(14, widest + 2))}ch`;
  return (
    <section className="insp-gap">
      <h4 className="insp-gap__title">
        {title}
        <span className="insp-gap__count">
          {observed} of {total}
        </span>
      </h4>
      <p className="insp-gap__meaning">{meaning}</p>
      {items.length === 0 ? (
        <p className="insp-gap__none">
          Nothing is missing in this category for this snapshot — every one of the {total} was
          collected.
        </p>
      ) : (
        <ul className="insp-gap__list" style={{ "--insp-gap-col": col } as CSSProperties}>
          {items.map((it) => (
            <li key={it} className="insp-gap__item">
              {it}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/* ── coverage, derived from the model at render time ───────────────────────
   Every figure below is computed from the arrays. Nothing is hardcoded and nothing is copied from
   the coverage block — the coverage block is RECONCILED against these, and a disagreement is shown
   rather than resolved in favour of whichever looks better.

   But recomputing a figure the COMPILER derived from the same array with the same predicate is a
   self-check, not a cross-verification, and must not be reported as one. `reconcileCoverage()`
   below therefore labels every row with what it is capable of catching, and the headline counts
   only the rows that compare Atlas against an analysis it did not perform. */

interface Gap {
  key: string;
  title: string;
  meaning: string;
  total: number;
  items: string[];
}

function computeGaps(): Gap[] {
  const hosts = fabric.devices.map((d) => d.host);
  const routeHosts = new Set(Object.keys(fabric.routes));
  const aclHosts = new Set(Object.keys(fabric.acls));
  const ifaceHosts = new Set(Object.keys(fabric.interfaces));
  const nDev = fabric.devices.length;

  const undecidable = aclUndecidability();

  return [
    {
      key: "rib",
      title: "Hosts with no collected RIB",
      meaning:
        "Forwarding is not modelled on these hosts. A path through one of them stops being a traversal and becomes an assumption, so the engine reports the hop as unmodeled.",
      total: nDev,
      items: hosts.filter((h) => !routeHosts.has(h)).sort(),
    },
    {
      key: "acl",
      title: "Hosts with no collected ACLs",
      meaning:
        "No policy evaluation happens on these hosts. Traffic crossing one is neither permitted nor denied by this model — it is simply not examined.",
      total: nDev,
      items: hosts.filter((h) => !aclHosts.has(h)).sort(),
    },
    {
      key: "iface",
      title: "Hosts with no interface records",
      meaning:
        "Port state, duplex, speed and description are absent for these hosts, so every per-port question about them is unanswerable from this snapshot.",
      total: nDev,
      items: hosts.filter((h) => !ifaceHosts.has(h)).sort(),
    },
    {
      key: "topology",
      title: "Devices seen on topology only",
      meaning:
        "These were named by a neighbour's discovery table; the collector never reached them. Everything about their internals is unobserved, and they are drawn as outlines in the fabric for that reason.",
      total: nDev,
      items: fabric.devices
        .filter((d) => !d.collected)
        .map((d) => `${d.host} — reported by a neighbour, not collected`)
        .sort(),
    },
    {
      key: "inventory",
      title: "Devices with no inventory record",
      meaning:
        "No inventory record was returned, so lifecycle and advisory questions about these devices cannot be answered here at all.",
      total: nDev,
      items: fabric.devices
        .filter((d) => !d.inventoried)
        .map((d) => d.host)
        .sort(),
    },
    {
      /* A record that was returned is not a record that is complete: core2's software version is
         empty in the source snapshot, and the gap list above (which reads only the flag) left it
         out (critic B7). Same predicate as the coverage disclosure's field row. */
      key: "inventory-fields",
      title: "Devices with an incomplete inventory record",
      meaning:
        "An inventory record was returned but it is missing a model, serial or software version. A missing software version is exactly what lifecycle and advisory questions depend on.",
      total: nDev,
      items: fabric.devices
        .filter((d) => d.inventoried && missingInventoryFields(d).length > 0)
        .map((d) => `${d.host} — no ${missingInventoryFields(d).join(", ")}`)
        .sort(),
    },
    {
      key: "band",
      title: "Devices with no health band",
      meaning:
        "Scoring produced no band for these devices. A missing band is not a good band: they are rendered as indeterminate, never as the default colour of the ramp.",
      total: nDev,
      items: fabric.devices
        .filter((d) => !bandObserved(d))
        .map((d) => d.host)
        .sort(),
    },
    {
      key: "role",
      title: "Devices with no role",
      meaning:
        "No access/distribution/core role was derivable. Any grouping by role silently omits these unless it renders them as an explicit unobserved group.",
      total: nDev,
      items: fabric.devices
        .filter((d) => d.role === null)
        .map((d) => d.host)
        .sort(),
    },
    {
      key: "centrality",
      title: "Links with no centrality computed",
      meaning:
        "Betweenness and the bridge test were not computed for these links, so nothing is known about whether cutting one partitions the fabric. They are drawn as indeterminate, not as ordinary links.",
      total: fabric.links.length,
      items: fabric.links
        .filter((l) => l.isBridge === null)
        .map(
          (l) =>
            `${l.id} — ${l.a} ${l.aPort ?? "(port not observed)"} to ${l.b} ${l.bPort ?? "(port not observed)"}`,
        )
        .sort(),
    },
    {
      key: "aclline",
      title: "ACL lines that cannot be decided",
      meaning:
        "The union of three sets: lines this model refuses to evaluate, lines the collector's parser could not model, and lines the snapshot's own reachability analysis returned indeterminate. They overlap only partly, so no one of them is the denominator — stating the parser's flag alone understated this surface and named a line the model decides. Membership is about the line across all flows. A flow that could match a member this model cannot read is reported indeterminate and names the line; a member whose fields CAN be read for a particular flow (one the snapshot marks indeterminate only in general) may decide that flow, and the trace says so in its caveats. Even then, unless that list's `ip access-group` binding on the hop was observed, such a verdict is capped at OBSERVED and an intent search counts it as undecided.",
      total: undecidable.total,
      items: undecidable.members.map(
        (m) => `${m.label} — ${m.raw ?? "(line text not observed)"} (${m.reasons.join("; ")})`,
      ),
    },
  ];
}

/**
 * How much a comparison can actually catch.
 *
 * `self-check` — the "stated" side was computed by `tools/compile-snapshot.mjs` from the SAME
 * array with the SAME predicate that the "derived" side recomputes. It can catch a build or
 * transport fault (a truncated array, a stale bundle) and nothing else: it is structurally
 * incapable of disagreeing about the MODEL. Presenting a wall of these as "0 disagree" was this
 * panel's own instance of the repository's named defect shape — a gate whose failure path cannot
 * execute, rendered as a reassuring green zero.
 *
 * `cross-predicate` — same source array, but the two sides ask slightly different questions
 * (`inventoried` versus `collected`, `betweenness` versus `isBridge`). It can catch a genuine
 * modelling divergence, but only where those predicates come apart.
 *
 * `independent` — the "stated" side comes from an analysis Atlas did not perform: the snapshot's
 * own `acl_line_reachability`, or the collector's own parser verdict. These are the only rows
 * where a disagreement means something about the network rather than about the build. They DO
 * disagree on this snapshot, and that disagreement is the honest headline.
 */
type ReconKind = "self-check" | "cross-predicate" | "independent";

interface Reconciliation {
  label: string;
  stated: string;
  derived: string;
  agrees: boolean;
  kind: ReconKind;
  /** What this particular comparison is and is not able to detect. Rendered, not just documented. */
  note: string;
}

const SELF_CHECK_NOTE =
  "Self-check: the stated figure is computed by the compiler from this same array with the same predicate. A disagreement here would mean a corrupt or stale build, never a modelling difference.";

function reconcileCoverage(): Reconciliation[] {
  const c = fabric.coverage;
  const aclLines = Object.values(fabric.acls).flatMap((a) => Object.values(a).flat());
  const undecidable = aclUndecidability();
  const snapshotIndeterminate = c.aclSummary["n_indeterminate"] ?? null;

  const rows: [string, number | string, number | string, ReconKind, string][] = [
    [
      "devicesInventoried",
      c.devicesInventoried,
      fabric.devices.filter((d) => d.inventoried).length,
      "self-check",
      SELF_CHECK_NOTE,
    ],
    [
      "devicesOnTopologyOnly",
      c.devicesOnTopologyOnly,
      fabric.devices.filter((d) => !d.collected).length,
      "cross-predicate",
      "The compiler counts devices with no inventory record; this side counts devices the collector never reached. They coincide on this snapshot, but a device that answered without producing an inventory record would separate them.",
    ],
    ["hostsWithRoutes", c.hostsWithRoutes, Object.keys(fabric.routes).length, "self-check", SELF_CHECK_NOTE],
    ["hostsWithAcls", c.hostsWithAcls, Object.keys(fabric.acls).length, "self-check", SELF_CHECK_NOTE],
    ["hostsWithObjectGroups", c.hostsWithObjectGroups, Object.keys(fabric.objectGroups).length, "self-check", SELF_CHECK_NOTE],
    ["hostsWithInterfaces", c.hostsWithInterfaces, Object.keys(fabric.interfaces).length, "self-check", SELF_CHECK_NOTE],
    [
      "linksWithCentrality",
      c.linksWithCentrality,
      fabric.links.filter((l) => l.isBridge !== null).length,
      "cross-predicate",
      "The compiler counts links with a betweenness value; this side counts links with a bridge verdict. A centrality run that produced one without the other would separate them.",
    ],
    ["aclLinesTotal", c.aclLinesTotal, aclLines.length, "self-check", SELF_CHECK_NOTE],
    [
      "aclLinesUnevaluable  vs  lines this model refuses",
      c.aclLinesUnevaluable,
      undecidable.bySource.engine,
      "independent",
      "The collector's parser flag against this engine's own evaluability rule — two different analyses of the same lines. They are not nested: the parser flags an object-group reference this engine resolves, and misses two qualifiers this engine refuses. Neither is the denominator; the union is.",
    ],
    [
      "acl_line_reachability.n_indeterminate  vs  lines this model refuses",
      snapshotIndeterminate ?? "not observed",
      undecidable.bySource.engine,
      "independent",
      "The snapshot's own reachability analysis against this engine's evaluability rule. The snapshot also calls the trailing deny of a poisoned list indeterminate, which this engine evaluates directly — so a disagreement here is expected and informative, not a fault.",
    ],
    [
      "routableHosts",
      [...c.routableHosts].sort().join(", "),
      Object.keys(fabric.routes).sort().join(", "),
      "self-check",
      SELF_CHECK_NOTE,
    ],
    [
      "aclHosts",
      [...c.aclHosts].sort().join(", "),
      Object.keys(fabric.acls).sort().join(", "),
      "self-check",
      SELF_CHECK_NOTE,
    ],
  ];
  return rows.map(([label, stated, derived, kind, note]) => ({
    label,
    stated: String(stated),
    derived: String(derived),
    agrees: String(stated) === String(derived),
    kind,
    note,
  }));
}

/* ── the panel ─────────────────────────────────────────────────────────────── */

type InspectorTab = "data" | "provenance" | "coverage" | "json";

const TAB_IDS: readonly InspectorTab[] = ["data", "provenance", "coverage", "json"];
const isTab = (v: string): v is InspectorTab => (TAB_IDS as readonly string[]).includes(v);

export interface InspectorProps {
  /** Overrides the module-level citation. Mostly for tests and for a host that owns its own state. */
  cite?: Cite | null;
  /** Rendered even when the store says the Inspector is closed. */
  forceOpen?: boolean;
  className?: string;
}

export function Inspector({
  cite,
  forceOpen = false,
  className,
}: InspectorProps): ReactElement | null {
  const open = useInvestigation((s) => s.inspectorOpen) || forceOpen;
  const setInspectorOpen = useInvestigation((s) => s.setInspectorOpen);
  const deviceId = useInvestigation((s) => s.deviceId);
  const linkId = useInvestigation((s) => s.linkId);
  const findingId = useInvestigation((s) => s.findingId);
  const moduleCite = useActiveCite();

  /* The Inspector opened by a keyboard shortcut has no citation of its own. Rather than showing an
     empty panel it falls back to whatever the investigation is currently pointed at, narrowest
     first — which is what the reader means by "inspect this". */
  const fallback =
    (findingId ? (findingById.get(findingId)?.cite ?? null) : null) ??
    (linkId ? (linkById.get(linkId)?.cite ?? null) : null) ??
    (deviceId ? (deviceById.get(deviceId)?.cite ?? null) : null);
  const effectiveCite = cite ?? moduleCite ?? fallback;

  const [tab, setTab] = useState<InspectorTab>("data");
  const [bearerAt, setBearerAt] = useState(0);
  const [height, setHeight] = useState<number>(DEFAULT_H);
  const { copy, status } = useCopyToClipboard();
  const tablistRef = useRef<HTMLDivElement>(null);
  const openedRef = useRef(false);

  useEffect(() => {
    setHeight(readStoredHeight());
  }, []);

  useEffect(() => {
    setBearerAt(0);
  }, [effectiveCite]);

  /* APG: opening moves focus into the tablist; closing returns it to whatever invoked us. This is
     NOT a focus trap — the Inspector is a dock, not a modal, and Tab must be able to leave it. */
  useEffect(() => {
    if (open && !openedRef.current) {
      openedRef.current = true;
      tablistRef.current?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')?.focus();
    } else if (!open && openedRef.current) {
      openedRef.current = false;
      focusReturn?.focus();
    }
  }, [open]);

  const resolution = useMemo(
    () => resolveCitation(effectiveCite, bearerAt),
    [effectiveCite, bearerAt],
  );
  const gaps = useMemo(() => computeGaps(), []);
  const reconciliation = useMemo(() => reconcileCoverage(), []);
  /* Split by what the comparison is CAPABLE of catching. A headline that pools the self-checks in
     with the independent comparisons reports a zero that no data could make non-zero. */
  const independent = reconciliation.filter((r) => r.kind === "independent");
  const independentDisagreements = independent.filter((r) => !r.agrees);
  const selfChecks = reconciliation.filter((r) => r.kind === "self-check");

  const recordJson = useMemo(
    () => (resolution.record === undefined ? "" : JSON.stringify(resolution.record, null, 2)),
    [resolution.record],
  );

  const persistHeight = useCallback((h: number) => {
    setHeight(h);
    try {
      window.localStorage.setItem(STORE_KEY, String(h));
    } catch {
      /* Preference storage is best-effort; the panel still works at the session height. */
    }
  }, []);

  const dragFrom = useRef<{ y: number; h: number } | null>(null);
  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>): void => {
    dragFrom.current = { y: e.clientY, h: height };
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };
  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>): void => {
    const from = dragFrom.current;
    if (!from) return;
    // Dragging the divider UP makes the panel taller: it is docked to the bottom edge.
    persistHeight(clampH(from.h + (from.y - e.clientY)));
  };
  const onPointerUp = (e: ReactPointerEvent<HTMLDivElement>): void => {
    dragFrom.current = null;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
  };

  /* WCAG 2.5.7: every drag has a click-or-key-only twin. Arrows resize, Home/End jump to the
     bounds, and a double-click resets — the divider is never the only way to change the height. */
  const onDividerKey = (e: ReactKeyboardEvent<HTMLDivElement>): void => {
    const step = e.shiftKey ? 64 : 16;
    switch (e.key) {
      case "ArrowUp":
        e.preventDefault();
        persistHeight(clampH(height + step));
        break;
      case "ArrowDown":
        e.preventDefault();
        persistHeight(clampH(height - step));
        break;
      case "Home":
        e.preventDefault();
        persistHeight(MIN_H);
        break;
      case "End":
        e.preventDefault();
        persistHeight(MAX_H);
        break;
      case "Enter":
        e.preventDefault();
        persistHeight(DEFAULT_H);
        break;
      default:
        break;
    }
  };

  const download = useCallback(() => {
    if (recordJson === "") return;
    /* The filename is derived from the citation, never from a clock: two runs of the same export
       produce the same file name as well as the same bytes (acceptance F6). */
    const stem = (effectiveCite ?? "record").replace(/[^A-Za-z0-9._-]+/g, "-").slice(0, 80);
    const blob = new Blob([recordJson], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `atlas-scope-${stem}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }, [recordJson, effectiveCite]);

  if (!open) return null;

  const record = resolution.record;
  const fields: [string, unknown][] =
    record !== undefined && typeof record === "object" && record !== null && !Array.isArray(record)
      ? Object.entries(record as Record<string, unknown>)
      : [];
  const aclVerdict = aclLineVerdict(resolution.modelPath, record);

  const tabs: TabItem[] = [
    {
      id: "data",
      label: "Data",
      /* Three distinct states, three distinct counts. No citation yet: no denominator exists, so
         no count is shown. A citation that resolves: the field count. A citation that resolves to
         nothing: the denominator is genuinely UNKNOWN and gets the not-observed mark, because a
         `0` there would read as "this record has no fields" rather than "we could not find it". */
      count:
        effectiveCite === null
          ? undefined
          : resolution.kind === "unresolved"
            ? null
            : fields.length,
    },
    { id: "provenance", label: "Provenance" },
    {
      id: "coverage",
      label: "Coverage",
      count: gaps.filter((g) => g.items.length > 0).length,
    },
    { id: "json", label: "JSON" },
  ];

  const m = fabric.meta;

  return (
    <section
      id="inspector"
      className={["inspector", className].filter(Boolean).join(" ")}
      aria-label="Inspector"
      style={{ blockSize: `${height}px` }}
    >
      <div
        role="separator"
        aria-orientation="horizontal"
        aria-label="Resize the inspector"
        aria-valuenow={height}
        aria-valuemin={MIN_H}
        aria-valuemax={MAX_H}
        tabIndex={0}
        className="inspector__divider"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onKeyDown={onDividerKey}
        onDoubleClick={() => persistHeight(DEFAULT_H)}
      >
        <span className="inspector__grip" />
      </div>

      <header className="inspector__head">
        <h2 className="inspector__title">Inspector</h2>
        {effectiveCite === null ? (
          <span className="inspector__nocite">
            Nothing is selected — choose a finding, a device, a link or any citation to inspect its
            record.
          </span>
        ) : (
          <Chip mono tone="neutral" title={effectiveCite}>
            <span className="inspector__citelabel">citation</span>
            {effectiveCite}
          </Chip>
        )}
        {effectiveCite === null ? null : (
          <IconButton
            label="Copy the citation path"
            icon={<IconCopy />}
            size="sm"
            onClick={() => copy(effectiveCite, "citation path")}
          />
        )}
        <span className="inspector__spacer" />
        <IconButton
          label="Close the inspector"
          icon={<IconClose />}
          size="sm"
          onClick={() => setInspectorOpen(false)}
        />
      </header>

      {resolution.kind === "unresolved" && effectiveCite !== null ? (
        <div className="inspector__broken" role="alert">
          <strong className="inspector__broken-title">Broken evidence chain</strong>
          <span className="inspector__broken-body">
            The citation <code>{effectiveCite}</code> names no record in the compiled model, and no
            compiled record carries it. The claim that cited it cannot be audited from this build.
            Report it against the compiler — a claim whose evidence cannot be found is a defect, not
            a display problem.
          </span>
        </div>
      ) : null}

      {/* Tabs owns its own root and forwards no ref, so the wrapper is what the focus effect
          reaches through. */}
      <div ref={tablistRef} className="inspector__tabsbar">
        <Tabs
          id="inspector"
          label="Inspector views"
          items={tabs}
          value={tab}
          onChange={(id) => {
            if (isTab(id)) setTab(id);
          }}
          className="inspector__tabs"
        />
      </div>

      <div className="inspector__body">
        <TabPanel id="inspector" tabId="data" active={tab === "data"}>
          {effectiveCite === null ? (
            <Empty
              title="No citation is active"
              reason="Every record in this application carries a citation. Select a finding, a device, a link or a hop — or activate any citation affordance — and the record behind it is shown here."
            />
          ) : resolution.kind === "unresolved" ? (
            <p className="insp-note insp-note--bad">
              There is no record to show. See the broken evidence chain above.
            </p>
          ) : (
            <>
              <p className="insp-note">
                {resolution.kind === "model" ? (
                  <>
                    This citation resolves directly inside the compiled model at{" "}
                    <code>{resolution.modelPath}</code>.
                  </>
                ) : (
                  <>
                    This citation names a record in the source snapshot, which is not bundled with
                    this build. Shown below is the compiled record that carries the citation, at{" "}
                    <code>{resolution.modelPath}</code> in the model. The Provenance tab names the
                    file the source record lives in.
                  </>
                )}
              </p>
              {resolution.bearers.length > 1 ? (
                <div className="insp-bearers">
                  <span className="insp-bearers__label">
                    {resolution.bearers.length} records in the compiled model answer this citation:
                  </span>
                  {resolution.bearers.map((b, i) => (
                    <Button
                      key={b}
                      size="sm"
                      variant={i === bearerAt ? "primary" : "ghost"}
                      aria-pressed={i === bearerAt}
                      onClick={() => setBearerAt(i)}
                    >
                      {b}
                    </Button>
                  ))}
                </div>
              ) : null}
              {fields.length === 0 ? (
                <p className="insp-note">
                  The record at this citation is a {typeOf(record)} rather than a keyed record. Read
                  it in the JSON tab, where its structure is navigable.
                </p>
              ) : (
                <dl className="insp-kv">
                  {fields.map(([k, v]) => (
                    <div key={k} className="insp-kv__row">
                      <dt className="insp-kv__key">{k}</dt>
                      <dd className="insp-kv__val">
                        <FieldValue name={k} value={v} record={record} path={resolution.modelPath} />
                        {aclVerdict !== null && k === "unmodeledQualifiers" && !aclVerdict.evaluable && producerFieldNotEmitted(resolution.modelPath, record, k) === null ? (
                          <p className="insp-kv__model" data-model-evaluable={false}>
                            The qualifiers the collector itself named — not this model’s list.
                            This model’s verdict on the line is on the unevaluable row.
                          </p>
                        ) : null}
                        {aclVerdict !== null && k === "unevaluable" ? (
                          <p className="insp-kv__model" data-model-evaluable={aclVerdict.evaluable}>
                            {producerFieldNotEmitted(resolution.modelPath, record, k) === null
                              ? "The collector’s own flag."
                              : "The collector raised no flag either way."}{" "}
                            {aclVerdict.evaluable
                              ? "This model also evaluates the line."
                              : `This model cannot evaluate this line: ${aclVerdict.reason ?? "no reason recorded"}. ${producerFieldNotEmitted(resolution.modelPath, record, k) === null ? "The collector’s flag is narrower than the model’s check, so the" : "The"} line is treated as undecidable wherever it could match.`}
                          </p>
                        ) : null}
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
              {resolution.companions.map((c) => (
                <div key={c.path} className="insp-companion" data-companion={c.path}>
                  <p className="insp-note">
                    The same citation is also carried by <code>{c.path}</code> in{" "}
                    <code>{documentOf(c.path)}</code>, a second record compiled from the same snapshot
                    bytes. {documentOf(c.path) === "fabric.json" ? "" : "The forwarding engine reads its evidence from this one. "}
                    It is shown in full here, not behind the switcher above.
                  </p>
                  {c.record !== null && typeof c.record === "object" && !Array.isArray(c.record) ? (
                    <dl className="insp-kv">
                      {Object.entries(c.record as Record<string, unknown>).map(([k, v]) => (
                        <div key={k} className="insp-kv__row">
                          <dt className="insp-kv__key">{k}</dt>
                          <dd className="insp-kv__val">
                            <FieldValue name={k} value={v} record={c.record} path={c.path} />
                          </dd>
                        </div>
                      ))}
                    </dl>
                  ) : (
                    <p className="insp-note">The record there is a {typeOf(c.record)} rather than a keyed record.</p>
                  )}
                </div>
              ))}
              <div className="insp-actions">
                <Button
                  size="sm"
                  icon={<IconCopy />}
                  onClick={() => copy(recordJson, "this record as JSON")}
                >
                  Copy record
                </Button>
                <Button size="sm" onClick={download}>
                  Download record as JSON
                </Button>
                <span className="insp-actions__note">
                  Exports exactly the record at {resolution.modelPath} — {recordJson.length} bytes.
                </span>
              </div>
            </>
          )}
        </TabPanel>

        <TabPanel id="inspector" tabId="provenance" active={tab === "provenance"}>
          <p className="insp-note">
            The full chain from the claim on screen back to the bytes it was compiled from. Every
            row below is read from <code>meta</code> in the compiled model at render time.
          </p>
          <dl className="insp-kv insp-kv--wide">
            <KeyRow label="Citation">
              {effectiveCite === null ? (
                <NotObserved what="citation" compact />
              ) : (
                <code>{effectiveCite}</code>
              )}
            </KeyRow>
            <KeyRow label="Resolved by">
              {resolution.kind === "model"
                ? "the compiled model directly, at the citation path"
                : resolution.kind === "bearer"
                  ? `the compiled record carrying it, at ${resolution.modelPath}`
                  : "nothing — this citation resolves to no record"}
            </KeyRow>
            <KeyRow label="Source file" mono>
              {orNotObserved(m.source, (s) => s, { what: "source file" })}
            </KeyRow>
            <KeyRow label="Source sha256" mono>
              <span className="insp-sha">
                {orNotObserved(m.sourceSha256, (s) => s, {
                  what: "source sha256",
                })}
              </span>
              <IconButton
                label="Copy the source sha256"
                icon={<IconCopy />}
                size="sm"
                onClick={() => copy(m.sourceSha256, "source sha256")}
              />
            </KeyRow>
            <KeyRow label="Source bytes" mono>
              {orNotObserved(m.sourceBytes, (n) => `${n.toLocaleString("en-GB")} bytes`, {
                what: "source byte length",
              })}
            </KeyRow>
            <KeyRow label="Snapshot schema" mono>
              {orNotObserved(m.schema, (s) => s, { what: "snapshot schema" })}
            </KeyRow>
            <KeyRow label="Collection engine" mono>
              {orNotObserved(m.scriptVersion, (s) => s, {
                what: "collection engine version",
              })}
            </KeyRow>
            <KeyRow label="Collected at" mono>
              {orNotObserved(m.collectedAt, (s) => s, {
                what: "collection timestamp",
              })}
            </KeyRow>
            <KeyRow label="Compiled at" mono>
              {orNotObserved(m.generatedAt, (s) => s, {
                what: "compile timestamp",
              })}
            </KeyRow>
            <KeyRow label="Compiler" mono>
              tools/compile-snapshot.mjs
            </KeyRow>
          </dl>
          <p className="insp-note">
            Two producers sit in this chain and they are recorded differently. The collection engine
            stamps its own version into the snapshot, so the row above is evidence. The compiler
            that turned that snapshot into this model does not stamp itself: its name is declared by
            this build, not read from the data, and is shown as such rather than dressed up as a
            recorded fact.
          </p>
          <p className="insp-note">
            The source record itself lives in the file named above, which is {""}
            {m.sourceBytes.toLocaleString("en-GB")} bytes and is deliberately not bundled with this
            build. The sha256 is the compiler's DECLARATION about the bytes it read — this page
            reads it back out of the compiled model, it does not recompute it, so on its own it is
            a label rather than a proof. What makes it a binding is a check that runs elsewhere:
            the build's test suite recomputes the digest from the named file and rebuilds this
            model from it, and fails if either disagrees. Recompile from a file with that digest
            and you reproduce this model, byte for byte.
          </p>
        </TabPanel>

        <TabPanel id="inspector" tabId="coverage" active={tab === "coverage"}>
          <p className="insp-note">
            What nobody collected. Each category states its denominator and then lists the actual
            members, because a count alone cannot be checked and a list that is merely shorter than
            expected reads as completeness.
          </p>
          {gaps.map((g) => (
            <GapSection
              key={g.key}
              title={g.title}
              observed={g.items.length}
              total={g.total}
              meaning={g.meaning}
              items={g.items}
            />
          ))}

          <section className="insp-gap insp-gap--recon">
            <h4 className="insp-gap__title">
              Coverage block reconciled against the model
              <span className="insp-gap__count">
                {independentDisagreements.length} of {independent.length} independent comparisons
                disagree
              </span>
            </h4>
            <p className="insp-gap__meaning">
              Most of the coverage block is <strong>not</strong> shipped by the snapshot: the
              compiler computes it from the same arrays this panel recomputes, with the same
              predicate. Those rows are marked <strong>self-check</strong> and cannot disagree
              about the model — only about the build — so their agreement is reported here but is
              not evidence that anything was cross-verified. Counting them in a headline
              &ldquo;{selfChecks.length} of {selfChecks.length} agree&rdquo; would be a green zero
              that no data could have turned red.
            </p>
            <p className="insp-gap__meaning">
              Only the rows marked <strong>independent</strong> compare Atlas against an analysis
              it did not perform, and they are the only place a disagreement means something about
              the network.{" "}
              {independentDisagreements.length === 0
                ? "None disagree on this snapshot."
                : `${independentDisagreements.length} disagree here, and both are real: the parser's flag, the snapshot's reachability analysis and this engine's evaluability rule pick out overlapping but different sets of access-list lines, which is why every coverage surface states their union rather than any one of them.`}{" "}
              The snapshot&rsquo;s own <code>collection_completeness.summary</code> is not compiled
              into this build, so its <code>not_collected</code> figure cannot be reconciled here —
              that is a gap in this check, not an agreement.
            </p>
            {/* Wide content scrolls inside its own region; the page body never scrolls sideways. */}
            <div className="insp-tablewrap">
              <table className="insp-table">
                <caption className="visually-hidden">
                  Coverage counters as stated by the snapshot, beside the same figure derived from
                  the compiled arrays
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Counter</th>
                    <th scope="col">Stated</th>
                    <th scope="col">Derived</th>
                    <th scope="col">What this can catch</th>
                    <th scope="col">Agreement</th>
                  </tr>
                </thead>
                <tbody>
                  {reconciliation.map((r) => (
                    <tr
                      key={r.label}
                      data-disagree={r.agrees ? undefined : "true"}
                      data-kind={r.kind}
                    >
                      <th scope="row">{r.label}</th>
                      <td>{r.stated}</td>
                      <td>{r.derived}</td>
                      <td title={r.note}>
                        {r.kind}
                        <span className="visually-hidden"> — {r.note}</span>
                      </td>
                      <td>
                        {r.agrees
                          ? r.kind === "self-check"
                            ? "agrees (self-check — cannot disagree about the model)"
                            : "agrees"
                          : r.kind === "independent"
                            ? "DISAGREES — two independent analyses; the union is what is rendered"
                            : "DISAGREES — do not rely on either"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </TabPanel>

        <TabPanel
          id="inspector"
          tabId="json"
          active={tab === "json"}
          className="inspector__jsonpanel"
        >
          <JsonView
            value={fabric as unknown}
            rootLabel="fabric.json"
            label="Compiled evidence document"
            citedPath={resolution.modelPath !== null && documentOf(resolution.modelPath) === "fabric.json" ? resolution.modelPath : null}
            visible={tab === "json"}
          />
        </TabPanel>
      </div>
      <LiveRegion message={status} />
    </section>
  );
}

/**
 * This model's evaluability verdict for a compiled ACL line, or null when the record is not one.
 *
 * The compiled line carries the COLLECTOR's `unevaluable` flag and `unmodeledQualifiers` list. The
 * model's check is wider — a `time-range` or `established` line is flagged false by the collector
 * and is undecidable to the engine — so a record showing `unevaluable: false` and an empty
 * qualifier list read as "this line is evaluable" while the status bar and every trace listed it as
 * undecidable. The verdict is recomputed from the engine's own function rather than restated, so
 * the two can never drift.
 */
export function aclLineVerdict(modelPath: string | null, record: unknown): { evaluable: boolean; reason: string | null } | null {
  if (modelPath === null || !/^acls\.[^.[\]]+\.[^[\]]+\[\d+\]$/.test(modelPath)) return null;
  if (typeof record !== "object" || record === null || Array.isArray(record)) return null;
  const r = record as Record<string, unknown>;
  if (!("unevaluable" in r) || !("raw" in r) || !("action" in r)) return null;
  const v = lineEvaluability(record as AclLine);
  return { evaluable: v.evaluable, reason: v.reason };
}
