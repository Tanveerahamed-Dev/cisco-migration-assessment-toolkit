/**
 * EvidencePane.tsx — the chain from a finding down to the configuration text behind it.
 *
 * Acceptance A1 asks for configuration evidence in three interactions without the topology
 * resetting. This pane is where the last of those three happens, and the design position it
 * implements is Forward's: a reader cannot audit a floating snippet. So every step of the chain
 * is a real affordance that navigates, the configuration excerpt carries the record's OWN line
 * indices, and any elided region states the exact number of lines it is hiding.
 *
 * The honesty constraint that shapes most of the code below: this snapshot preserves literal
 * configuration TEXT for ACL lines only. Interface and route records survive as parsed fields.
 * Reconstructing `interface Gi1/0/1 / description to-core2-a` from those fields would put
 * synthesised text in front of a reader who asked to see the configuration — so the two are
 * rendered by two different components that say which they are, and the parsed one says plainly
 * that the surrounding block was not preserved.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactElement,
  type ReactNode,
} from "react";
import {
  crossLayerByHost,
  deviceById,
  fabric,
  findingById,
  findingsByHost,
  hasRib,
  interfacesOf,
  l3ByHost,
  physicalByHost,
  protocolsByHost,
  routesOf,
  bySeverityThenRank,
} from "../core/data";
import { useInvestigation, type EvidenceTab } from "../core/store";
import type {
  AclLine,
  Cite,
  CrossLayerFinding,
  Finding,
  InterfaceRecord,
  RouteEntry,
} from "../core/types";
import {
  Button,
  Cite as CiteButton,
  Empty,
  Input,
  LiveRegion,
  NotObserved,
  SeverityBadge,
  orNotObserved,
} from "../ui/primitives";
import { AclLines, Kv, Section, useOpenCite, type KvRow } from "./DevicePane";
import "./EvidencePane.css";

const cx = (...parts: (string | false | null | undefined)[]): string => parts.filter(Boolean).join(" ");

const plural = (n: number, one: string, many = `${one}s`): string => `${n} ${n === 1 ? one : many}`;

/* ══ cross-layer composition ═══════════════════════════════════════════════
   The punchlist and the cross-layer table are separate arrays with no shared key, so the join is
   on the title string. That is an inference, and it is reported as one: the denominator below is
   computed, not asserted, so a future snapshot where the join stops holding shows it here rather
   than silently dropping the composition. */

const crossLayerByTitle: ReadonlyMap<string, CrossLayerFinding> = new Map(
  fabric.crossLayer.map((c) => [c.title, c]),
);

const CROSS_JOIN_RATE = (() => {
  const resolved = fabric.crossLayer.filter((c) => fabric.findings.some((f) => f.title === c.title)).length;
  return { resolved, total: fabric.crossLayer.length };
})();

/* ══ configuration evidence ════════════════════════════════════════════════ */

export type ConfigEvidence =
  | {
      kind: "acl";
      host: string;
      label: string;
      /** Literal configuration text, with the record's own indices. */
      lines: readonly AclLine[];
      focusIndex: number | null;
      cite: Cite;
      /** How this record was reached from the finding, shown to the reader. */
      how: string;
    }
  | {
      kind: "interface";
      host: string;
      label: string;
      record: InterfaceRecord;
      cite: Cite;
      how: string;
    }
  | {
      kind: "route";
      host: string;
      label: string;
      entries: readonly RouteEntry[];
      cite: Cite;
      how: string;
    };

const escapeRe = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Interface names the engine emits. Anchored to a digit so `Poor` and `Ethernet` prose do not match. */
const PORT_TOKEN = "(?:Gi|Te|TenGig|Fa|Eth|Ethernet|Twe|Fo|Po|Vlan|Se)\\d[\\w./:-]*";

/* Hosts longest-first: `access1` is a prefix of `access17`, and the short alternative would win
   the alternation and leave a stray `7` in front of the port token. */
const HOST_ALTERNATION = fabric.devices
  .map((d) => d.host)
  .sort((a, b) => b.length - a.length)
  .map(escapeRe)
  .join("|");

const HOST_PORT_RE = new RegExp(`\\b(${HOST_ALTERNATION})\\s+(${PORT_TOKEN})`, "g");
const ACL_LINE_RE = /\bline\s+(\d+)\b/i;
const CIDR_RE = /\b(\d{1,3}(?:\.\d{1,3}){3}\/\d{1,2})\b/g;

const findingText = (f: Finding): string => [f.title, f.detail ?? "", f.remediation ?? ""].join(" — ");

/**
 * Resolve a finding to the configuration records it actually names.
 *
 * Deliberately conservative: a pair is accepted only when the port token follows a host token AND
 * an interface record for that exact port exists. A guessed record shown as "the configuration
 * behind this finding" is worse than none, because it looks like an answer.
 */
export function configEvidenceFor(finding: Finding): ConfigEvidence[] {
  const text = findingText(finding);
  const out: ConfigEvidence[] = [];
  const seen = new Set<string>();

  for (const m of text.matchAll(HOST_PORT_RE)) {
    const host = m[1];
    const port = m[2];
    if (host === undefined || port === undefined) continue;
    const record = interfacesOf(host).find((i) => i.port === port);
    if (!record) continue;
    if (seen.has(record.cite)) continue;
    seen.add(record.cite);
    out.push({
      kind: "interface",
      host,
      label: `${host} ${port}`,
      record,
      cite: record.cite,
      how: `named literally in this finding as “${host} ${port}”`,
    });
  }

  for (const host of finding.devices) {
    const named = fabric.acls[host];
    if (!named) continue;
    for (const [aclName, lines] of Object.entries(named)) {
      if (!text.includes(aclName)) continue;
      const idx = ACL_LINE_RE.exec(text)?.[1];
      const focusIndex = idx === undefined ? null : Number(idx);
      const first = lines[0];
      if (!first) continue;
      out.push({
        kind: "acl",
        host,
        label: `${host} · ${aclName}`,
        lines,
        focusIndex,
        cite: first.cite.replace(/\[\d+]$/, ""),
        how: `this finding names the access list “${aclName}” on ${host}`,
      });
    }
  }

  for (const host of finding.devices) {
    if (!hasRib(host)) continue;
    const prefixes = [...text.matchAll(CIDR_RE)].map((m) => m[1]).filter((p): p is string => p !== undefined);
    if (prefixes.length === 0) continue;
    const entries = routesOf(host).filter((r) => prefixes.includes(r.prefix));
    if (entries.length === 0) continue;
    const first = entries[0];
    if (!first) continue;
    out.push({
      kind: "route",
      host,
      label: `${host} · ${prefixes.join(", ")}`,
      entries,
      cite: first.cite,
      how: `this finding names ${plural(prefixes.length, "prefix", "prefixes")} for which ${host} holds a route`,
    });
  }

  return out;
}

/** The records we hold for the finding's hosts when the finding names no line of its own. */
export function nearestConfigFor(finding: Finding): ConfigEvidence[] {
  const out: ConfigEvidence[] = [];
  for (const host of finding.devices) {
    const named = fabric.acls[host];
    if (named) {
      for (const [aclName, lines] of Object.entries(named)) {
        const first = lines[0];
        if (!first) continue;
        out.push({
          kind: "acl",
          host,
          label: `${host} · ${aclName}`,
          lines,
          focusIndex: null,
          cite: first.cite.replace(/\[\d+]$/, ""),
          how: `not named by this finding — it is an access list collected on ${host}`,
        });
      }
    }
    for (const i of interfacesOf(host).slice(0, 6)) {
      out.push({
        kind: "interface",
        host,
        label: `${host} ${i.port}`,
        record: i,
        cite: i.cite,
        how: `not named by this finding — it is an interface record collected on ${host}`,
      });
    }
  }
  return out;
}

/* ══ the configuration excerpt ═════════════════════════════════════════════ */

interface ExcerptLine {
  index: number;
  text: string | null;
  match: boolean;
  cite: Cite;
  unevaluable: boolean;
}

interface Block {
  kind: "lines" | "elided";
  lines: ExcerptLine[];
  hidden: number;
}

/**
 * Collapse to the matching lines plus `radius` of context, and state the hidden count exactly.
 *
 * Three lines of configuration prove nothing: a reader cannot tell whether context was
 * cherry-picked. "line 3 of 4, with 1 line hidden above it" is auditable, so the elision is a
 * counted bar rather than an ellipsis.
 */
export function blocksFor(lines: readonly ExcerptLine[], radius = 3): Block[] {
  const anyMatch = lines.some((l) => l.match);
  const keep = new Set<number>();
  if (!anyMatch) {
    lines.forEach((_, i) => keep.add(i));
  } else {
    lines.forEach((l, i) => {
      if (!l.match) return;
      for (let j = i - radius; j <= i + radius; j += 1) if (j >= 0 && j < lines.length) keep.add(j);
    });
  }
  const out: Block[] = [];
  let run: ExcerptLine[] = [];
  let hidden = 0;
  const flushRun = (): void => {
    if (run.length > 0) {
      out.push({ kind: "lines", lines: run, hidden: 0 });
      run = [];
    }
  };
  const flushHidden = (): void => {
    if (hidden > 0) {
      out.push({ kind: "elided", lines: [], hidden });
      hidden = 0;
    }
  };
  lines.forEach((l, i) => {
    if (keep.has(i)) {
      flushHidden();
      run.push(l);
    } else {
      flushRun();
      hidden += 1;
    }
  });
  flushRun();
  flushHidden();
  return out;
}

function SnapshotBinding(): ReactElement {
  const m = fabric.meta;
  return (
    <p className="ev-binding">
      <span className="ev-mono">{m.source}</span>
      <span aria-hidden="true"> · </span>
      <span className="ev-mono">sha256 {m.sourceSha256.slice(0, 12)}…</span>
      <span aria-hidden="true"> · </span>
      collected{" "}
      {orNotObserved(m.collectedAt, (s) => s.slice(0, 10), { what: "collection date", compact: true })}
    </p>
  );
}

function ConfigExcerpt({
  target,
  onClose,
  onOpenCite,
}: {
  target: ConfigEvidence;
  onClose: () => void;
  onOpenCite: (c: Cite) => void;
}): ReactElement {
  const [search, setSearch] = useState("");
  const headRef = useRef<HTMLHeadingElement>(null);

  /* Focus moves to the excerpt's heading when it opens, for two reasons that are really one:
     a reader who activated the control needs to arrive at what it produced, and Escape cannot
     reach the handler below unless focus is inside. `onClose` returns focus to the trigger. */
  useEffect(() => {
    headRef.current?.focus();
  }, [target]);

  const lines: ExcerptLine[] = useMemo(() => {
    if (target.kind !== "acl") return [];
    const needle = search.trim().toLowerCase();
    return target.lines.map((l) => ({
      index: l.index,
      text: l.raw,
      cite: l.cite,
      unevaluable: l.unevaluable,
      match:
        needle === ""
          ? target.focusIndex === l.index
          : (l.raw ?? "").toLowerCase().includes(needle),
    }));
  }, [target, search]);

  const blocks = useMemo(() => blocksFor(lines), [lines]);
  const shown = blocks.reduce((a, b) => a + b.lines.length, 0);
  const matches = lines.filter((l) => l.match).length;

  const onKeyDown = (e: ReactKeyboardEvent<HTMLElement>): void => {
    if (e.key === "Escape") {
      e.stopPropagation();
      onClose();
    }
  };

  return (
    <aside className="ev-cfg" aria-label={`Configuration evidence for ${target.label}`} onKeyDown={onKeyDown}>
      <header className="ev-cfg__head">
        <h4 className="ev-cfg__title" ref={headRef} tabIndex={-1}>
          {target.label}
        </h4>
        <Button variant="ghost" size="sm" onClick={onClose}>
          Close
        </Button>
      </header>
      <p className="ev-cfg__how">Reached because {target.how}.</p>

      {target.kind === "acl" ? (
        <>
          <div className="ev-cfg__toolbar">
            <Input
              label={`Search ${plural(target.lines.length, "line")}`}
              value={search}
              mono
              onChange={(e) => setSearch(e.currentTarget.value)}
              placeholder="e.g. deny"
            />
            {/* A match count with an empty search box is a zero standing in for a question nobody
                asked — the same absence-as-a-number defect this application exists to remove, in
                the panel the whole evidence chain terminates on. With no query there is no match
                count to report: the panel says what it is showing, and nothing about matching.
                The highlighted line, when the finding named one, is a different statement and is
                reported as one. */}
            <p className="ev-cfg__count">
              {search.trim() === ""
                ? `Showing ${plural(shown, "line")} of ${target.lines.length}${
                    target.focusIndex === null ? "" : `, line ${target.focusIndex} highlighted`
                  }.`
                : matches === 0
                  ? "0 matching lines — the search ran and matched nothing."
                  : `${plural(matches, "matching line")} · showing ${shown} of ${target.lines.length}`}
            </p>
          </div>
          <ol className="ev-cfg__lines">
            {blocks.map((b, bi) =>
              b.kind === "elided" ? (
                <li key={`elide-${bi}`} className="ev-cfg__elide">
                  {plural(b.hidden, "line")} hidden
                </li>
              ) : (
                b.lines.map((l) => (
                  <li
                    key={l.cite}
                    className={cx("ev-cfg__line", l.match && "ev-cfg__line--match", l.unevaluable && "ev-cfg__line--unevaluable")}
                  >
                    {/* The record's OWN index, never a 1-based renumbering of the excerpt: a
                        renumbered gutter makes "line 3" mean two different lines. */}
                    <span className="ev-cfg__gutter">{l.index}</span>
                    <span className="ev-cfg__text">
                      {orNotObserved(l.text, (s) => <code>{s}</code>, {
                        what: "configuration text",
                        why: "the collector kept this line's parsed fields but not its literal text",
                        compact: true,
                      })}
                      {l.unevaluable ? (
                        <span className="ev-cfg__flag">the producer could not model this line</span>
                      ) : null}
                    </span>
                    <CiteButton cite={l.cite} onOpen={onOpenCite} label="cite" />
                  </li>
                ))
              ),
            )}
          </ol>
        </>
      ) : (
        <ParsedRecord target={target} onOpenCite={onOpenCite} />
      )}

      <footer className="ev-cfg__foot">
        <SnapshotBinding />
      </footer>
    </aside>
  );
}

/**
 * A record the snapshot preserved as fields rather than as text.
 *
 * The banner is the whole point of this component: it tells the reader that what follows is the
 * parse, not the configuration, so nobody quotes a reconstructed line into a change record.
 */
function ParsedRecord({
  target,
  onOpenCite,
}: {
  target: Extract<ConfigEvidence, { kind: "interface" | "route" }>;
  onOpenCite: (c: Cite) => void;
}): ReactElement {
  if (target.kind === "interface") {
    const i = target.record;
    const rows: KvRow[] = [
      { k: "Port", v: <span className="ev-mono">{i.port}</span> },
      { k: "Status", v: orNotObserved(i.status, (s) => s, { what: "status", compact: true }) },
      { k: "Speed", v: orNotObserved(i.speed, (s) => s, { what: "speed", compact: true }) },
      { k: "Duplex", v: orNotObserved(i.duplex, (s) => s, { what: "duplex", compact: true }) },
      { k: "Port type", v: orNotObserved(i.portType, (s) => s, { what: "port type", compact: true }) },
      { k: "Link type", v: orNotObserved(i.linkType, (s) => s, { what: "link type", compact: true }) },
      { k: "Channel", v: orNotObserved(i.portChannel, (s) => <span className="ev-mono">{s}</span>, { what: "port-channel", compact: true }) },
      { k: "Channel protocol", v: orNotObserved(i.pcProtocol, (s) => s, { what: "channel protocol", compact: true }) },
    ];
    return (
      <div className="ev-cfg__parsed">
        <p className="ev-cfg__banner">
          The snapshot preserved this interface as parsed fields. Its surrounding configuration
          block was not kept, so there is no literal text to show for it. The description below is
          the one literal configuration string this record carries.
          {i.runConfigObserved
            ? " The running configuration was observed for this port."
            : " The running configuration was NOT observed for this port, so what is absent here was never read."}
        </p>
        <div className="ev-cfg__literal">
          <span className="ev-cfg__literal-k">description</span>
          <span className="ev-cfg__literal-v">
            {orNotObserved(i.description, (s) => <code>{s}</code>, {
              what: "interface description",
              why: "this interface carries no description in the collected configuration",
              compact: true,
            })}
          </span>
        </div>
        <Kv rows={rows} onOpenCite={onOpenCite} />
        <CiteButton cite={i.cite} onOpen={onOpenCite} />
      </div>
    );
  }

  return (
    <div className="ev-cfg__parsed">
      <p className="ev-cfg__banner">
        Route entries are preserved as parsed fields, taken from the collected routing table rather
        than from configuration text. There is no configuration line behind them to show.
      </p>
      <ol className="ev-cfg__routes">
        {target.entries.map((r) => (
          <li key={r.cite} className="ev-cfg__route">
            <span className="ev-mono ev-cfg__route-prefix">{r.prefix}</span>
            <span className="ev-cfg__route-body">
              via {orNotObserved(r.nextHop, (s) => <span className="ev-mono">{s}</span>, { what: "next hop", compact: true })}
              {" out "}
              {orNotObserved(r.outIntf, (s) => <span className="ev-mono">{s}</span>, { what: "egress interface", compact: true })}
              {" ("}
              {orNotObserved(r.source, (s) => s, { what: "route source", compact: true })}
              {", AD "}
              {orNotObserved(r.adminDistance, (n) => String(n), { what: "administrative distance", compact: true })}
              {")"}
            </span>
            <CiteButton cite={r.cite} onOpen={onOpenCite} label="cite" />
          </li>
        ))}
      </ol>
    </div>
  );
}

/* ══ the chain ═════════════════════════════════════════════════════════════ */

type RecordFamily = "physical" | "interfaces" | "l3" | "protocols" | "acl" | "crossLayer" | "impact";

/** Which evidence family a finding's category belongs to, and which tab holds it. */
const FAMILY_BY_CATEGORY: Readonly<Record<string, readonly RecordFamily[]>> = {
  "L1": ["physical", "interfaces"],
  "L3": ["l3"],
  "FHRP": ["l3"],
  "IPv6 Routing": ["l3"],
  "Protocol": ["protocols"],
  "STP": ["protocols", "interfaces"],
  "Trunk": ["interfaces", "protocols"],
  "QoS": ["interfaces", "protocols"],
  "Security": ["acl", "interfaces"],
  "Config hygiene": ["interfaces"],
  "Health": ["physical", "protocols"],
  "Operational logs": ["protocols"],
  "Platform capacity": ["interfaces"],
  "False-health": ["protocols", "physical"],
  "Software exposure": ["impact"],
  "Cross-layer": ["crossLayer", "impact"],
  "Compound risk": ["crossLayer", "impact"],
};

const FAMILY_TAB: Readonly<Record<RecordFamily, EvidenceTab>> = {
  physical: "ports",
  interfaces: "ports",
  l3: "routing",
  protocols: "summary",
  acl: "acl",
  crossLayer: "findings",
  impact: "summary",
};

/** Singular: every call site runs it through `plural`, so "1 interface records" cannot happen. */
const FAMILY_LABEL: Readonly<Record<RecordFamily, string>> = {
  physical: "physical-health row",
  interfaces: "interface record",
  l3: "L3 interface record",
  protocols: "protocol-health row",
  acl: "access-list line",
  crossLayer: "cross-layer record",
  impact: "failure-impact record",
};

function familyCount(family: RecordFamily, host: string): number | null {
  switch (family) {
    case "physical": return (physicalByHost.get(host) ?? []).length;
    case "interfaces": return interfacesOf(host).length;
    case "l3": return (l3ByHost.get(host) ?? []).length;
    case "protocols": return (protocolsByHost.get(host) ?? []).length;
    case "acl": {
      const named = fabric.acls[host];
      return named ? Object.values(named).reduce((a, l) => a + l.length, 0) : null;
    }
    case "crossLayer": return (crossLayerByHost.get(host) ?? []).length;
    case "impact": return deviceById.get(host)?.impact ? 1 : null;
    default: return null;
  }
}

function ChainStep({
  n,
  title,
  children,
}: {
  n: number;
  title: string;
  children: ReactNode;
}): ReactElement {
  return (
    <li className="ev-step">
      <span className="ev-step__num" aria-hidden="true">{n}</span>
      <div className="ev-step__body">
        <h3 className="ev-step__title">{title}</h3>
        {children}
      </div>
    </li>
  );
}

/* ══ the pane ══════════════════════════════════════════════════════════════ */

export interface EvidencePaneProps {
  onOpenCite?: (cite: Cite) => void;
  /**
   * Hands the configuration record to a wider surface (the right-side config overlay). When it is
   * not supplied the excerpt opens inline in this pane instead, so the affordance is never inert.
   */
  onShowConfig?: (target: ConfigEvidence) => void;
  className?: string;
}

export function EvidencePane({ onOpenCite, onShowConfig, className }: EvidencePaneProps): ReactElement {
  const findingId = useInvestigation((s) => s.findingId);
  const selectFinding = useInvestigation((s) => s.selectFinding);
  const selectDevice = useInvestigation((s) => s.selectDevice);
  const setEvidenceTab = useInvestigation((s) => s.setEvidenceTab);
  const openCite = useOpenCite(onOpenCite);

  const [openTarget, setOpenTarget] = useState<ConfigEvidence | null>(null);
  /* The element that opened the excerpt, captured at click time rather than bound to the first
     button: focus must return to the control the reader actually used, not to the one that
     happens to be first. */
  const triggerRef = useRef<HTMLButtonElement | null>(null);

  const finding = findingId === null ? null : (findingById.get(findingId) ?? null);

  const named = useMemo(() => (finding ? configEvidenceFor(finding) : []), [finding]);
  const nearest = useMemo(() => (finding && named.length === 0 ? nearestConfigFor(finding) : []), [finding, named.length]);
  const targets = named.length > 0 ? named : nearest;

  const show = useCallback(
    (t: ConfigEvidence, trigger: HTMLButtonElement) => {
      triggerRef.current = trigger;
      if (onShowConfig) onShowConfig(t);
      else setOpenTarget(t);
    },
    [onShowConfig],
  );

  const closeConfig = useCallback(() => {
    setOpenTarget(null);
    triggerRef.current?.focus();
  }, []);

  /* The chain's own step-4 control sits at the bottom of a long pane: measured at 1920×1080 with
     the pane at scrollTop 0 it was 23 px below the fold, at 1600×900 it was 203 px below, and at
     1440×900 it was 245 px below. A1's two-click path was therefore really click, SCROLL, click —
     and at 1920 the margin was one line of prose. This is the same control, hoisted into the
     header where it cannot fall below the fold at any viewport. The excerpt itself still opens
     inside step 4, where the chain's narrative is: there is one disclosure, opened from two
     places, rather than two panels that could disagree. */
  const first = targets[0] ?? null;

  if (finding === null) {
    const top = [...fabric.findings].sort(bySeverityThenRank)[0];
    return (
      <section className={cx("ev", className)} aria-label="Evidence chain">
        <header className="ev__head">
          <h2 className="ev__title">Evidence</h2>
        </header>
        <div className="ev__body scroll-scrim">
          <Empty
            title="No finding is selected"
            reason={
              findingId === null
                ? "Select a finding in the priority queue and the chain from it to the configuration text behind it appears here."
                : `The investigation names finding ${findingId}, but no such record exists in this snapshot. The link may predate the snapshot in the header.`
            }
            action={
              top ? (
                <Button variant="primary" onClick={() => selectFinding(top.id)}>
                  Open the highest-priority finding ({top.id})
                </Button>
              ) : undefined
            }
          />
        </div>
      </section>
    );
  }

  const cross = crossLayerByTitle.get(finding.title) ?? null;
  const families = FAMILY_BY_CATEGORY[finding.category ?? ""] ?? (["impact"] as const);

  return (
    <section className={cx("ev", className)} aria-label="Evidence chain">
      <header className="ev__head">
        <div className="ev__idline">
          <SeverityBadge severity={finding.severity} />
          <span className="ev-mono ev__id">{finding.id}</span>
          <CiteButton cite={finding.cite} onOpen={openCite} />
        </div>
        <h2 className="ev__title">{finding.title}</h2>
        <Kv
          rows={[
            { k: "Category", v: orNotObserved(finding.category, (s) => s, { what: "category", compact: true }) },
            { k: "Wave", v: orNotObserved(finding.wave, (s) => s, { what: "migration wave", compact: true, why: "the engine assigned no wave to this finding" }) },
            { k: "Priority", v: orNotObserved(finding.priority, (n) => String(n), { what: "priority", compact: true }) },
            { k: "Rank", v: orNotObserved(finding.rank, (n) => String(n), { what: "rank", compact: true }) },
          ]}
          onOpenCite={openCite}
          className="ev__facts"
        />
        {first === null ? null : (
          <div className="ev__jump">
            <Button
              variant="primary"
              size="sm"
              onClick={(e) => show(first, e.currentTarget)}
            >
              {named.length > 0
                ? `Show the configuration this finding names: ${first.label}`
                : `Show the nearest configuration we hold: ${first.label}`}
            </Button>
            {named.length > 0 ? null : (
              <span className="ev__jump-note">
                Not this finding&rsquo;s own source — it names no configuration line.
              </span>
            )}
          </div>
        )}
      </header>

      <div className="ev__body scroll-scrim">
        <Section title="What the engine said">
          <p className="ev-prose">
            {orNotObserved(finding.detail, (s) => s, {
              what: "detail",
              why: "the engine published this finding without a detail paragraph",
            })}
          </p>
          <h4 className="ev-sub">Remediation</h4>
          <p className="ev-prose">
            {orNotObserved(finding.remediation, (s) => s, {
              what: "remediation",
              why: "the engine published no remediation for this finding",
            })}
          </p>
        </Section>

        {cross ? (
          <Section
            title="Layer composition"
            note={`Joined to the cross-layer table on an identical title; ${CROSS_JOIN_RATE.resolved} of ${CROSS_JOIN_RATE.total} cross-layer records resolve to a finding this way. The two arrays carry no shared key, so this is a derived link, not one the engine published.`}
          >
            <div className="ev-layers">
              {cross.layers === null ? (
                <NotObserved what="layer composition" why="the cross-layer record names no layers" compact />
              ) : (
                cross.layers.split("+").map((layer) => (
                  <span key={layer} className="ev-layer">{layer}</span>
                ))
              )}
              <span className="ev-layers__note">
                {cross.layers === null
                  ? "Which layers this composes was not recorded."
                  : `This is a compound risk: it is what happens when ${cross.layers.split("+").join(" and ")} fail together, which is why neither layer's own record states it.`}
              </span>
            </div>
            <Kv
              rows={[
                { k: "Record", v: <span className="ev-mono">{cross.id}</span>, cite: cross.cite },
                { k: "Recommendation", v: orNotObserved(cross.recommendation, (s) => s, { what: "recommendation", compact: true }), wide: true },
                { k: "Hosts", v: <span className="ev-mono ev-wrap">{cross.hosts.join(", ")}</span>, wide: true },
              ]}
              onOpenCite={openCite}
            />
          </Section>
        ) : null}

        <Section
          title="The evidence chain"
          note="Each step is a control. Following the chain re-aims the other surfaces; it does not replace them."
        >
          <ol className="ev-chain">
            <ChainStep n={1} title="The finding">
              <p className="ev-step__text">
                Published on the punchlist as <span className="ev-mono">{finding.id}</span>, at{" "}
                <span className="ev-mono">{finding.cite}</span>.
              </p>
              <CiteButton cite={finding.cite} onOpen={openCite} />
            </ChainStep>

            <ChainStep n={2} title={`The ${plural(finding.devices.length, "device")} it names`}>
              {finding.devices.length === 0 ? (
                <NotObserved
                  what="devices"
                  why="this finding names no device, so it cannot be traced to one"
                  cite={finding.cite}
                  onOpenCite={openCite}
                />
              ) : (
                <ul className="ev-devices">
                  {finding.devices.map((host) => {
                    const d = deviceById.get(host);
                    return (
                      <li key={host} className="ev-devices__item">
                        <button
                          type="button"
                          className="ev-devbtn"
                          onClick={() => {
                            selectDevice(host);
                            setEvidenceTab("summary");
                          }}
                        >
                          <span className="ev-mono">{host}</span>
                          <span className="ev-devbtn__meta">
                            {d === undefined ? (
                              <NotObserved
                                what="device record"
                                why="this host is named by the finding but has no device record in the compiled model"
                                compact
                              />
                            ) : d.collected ? (
                              "assessed"
                            ) : (
                              "topology only — never reached"
                            )}
                          </span>
                        </button>
                        {d ? <CiteButton cite={d.cite} onOpen={openCite} label="cite" /> : null}
                      </li>
                    );
                  })}
                </ul>
              )}
            </ChainStep>

            <ChainStep n={3} title="The records in the same evidence family">
              <p className="ev-step__text">
                Routed from this finding&rsquo;s category
                {finding.category === null ? " (not observed)" : ` (${finding.category})`}. This is
                a route into the evidence, not a statement that the engine derived the finding from
                these exact rows.
              </p>
              <ul className="ev-families">
                {families.flatMap((family) =>
                  finding.devices.map((host) => {
                    const n = familyCount(family, host);
                    return (
                      <li key={`${family}-${host}`} className="ev-families__item">
                        <button
                          type="button"
                          className="ev-devbtn"
                          onClick={() => {
                            selectDevice(host);
                            setEvidenceTab(FAMILY_TAB[family]);
                          }}
                        >
                          <span className="ev-mono">{host}</span>
                          <span className="ev-devbtn__meta">
                            {n === null ? (
                              <NotObserved
                                what={FAMILY_LABEL[family]}
                                why={`no ${FAMILY_LABEL[family]}s were collected for ${host}`}
                                compact
                              />
                            ) : (
                              plural(n, FAMILY_LABEL[family])
                            )}
                          </span>
                        </button>
                      </li>
                    );
                  }),
                )}
              </ul>
            </ChainStep>

            <ChainStep n={4} title="The configuration behind it">
              {named.length > 0 ? (
                <p className="ev-step__text">
                  This finding names {plural(named.length, "configuration record")} literally.
                </p>
              ) : (
                <p className="ev-step__text ev-step__text--absent">
                  This finding names no configuration line. It is a conclusion about collected
                  state rather than a quotation from a configuration file, so there is no line to
                  land on.
                  {nearest.length === 0
                    ? null
                    : ` The ${plural(nearest.length, "record")} below are the nearest configuration evidence we hold for the hosts it names — shown as context, not as this finding's source.`}
                </p>
              )}
              {targets.length === 0 ? (
                <NotObserved
                  what="configuration evidence"
                  why={`no access list, interface record or route entry was collected for ${finding.devices.join(", ") || "the hosts this finding names"}`}
                  cite={finding.cite}
                  onOpenCite={openCite}
                />
              ) : (
                <div className="ev-cfgactions">
                  {targets.slice(0, 8).map((t, i) => (
                    <Button
                      key={`${t.kind}-${t.cite}`}
                      variant={i === 0 && named.length > 0 ? "primary" : "secondary"}
                      size="sm"
                      /* Only claimed when this pane owns the disclosure. With an external
                         overlay handler the open state lives elsewhere, and asserting a
                         collapsed control while the panel is open would be a false state. */
                      aria-expanded={onShowConfig ? undefined : openTarget?.cite === t.cite}
                      onClick={(e) => show(t, e.currentTarget)}
                    >
                      {t.kind === "acl" ? "Show the configuration" : "Show the record"}: {t.label}
                    </Button>
                  ))}
                </div>
              )}
              {openTarget ? (
                <ConfigExcerpt target={openTarget} onClose={closeConfig} onOpenCite={openCite} />
              ) : null}
            </ChainStep>

            <ChainStep n={5} title="The raw snapshot record">
              <p className="ev-step__text">
                The Inspector resolves <span className="ev-mono">{finding.cite}</span> by walking
                that path into the source snapshot, so what it shows is the record itself rather
                than this pane&rsquo;s reading of it.
              </p>
              <CiteButton cite={finding.cite} onOpen={openCite} />
              <SnapshotBinding />
            </ChainStep>
          </ol>
        </Section>

        <Section
          title="Other findings on these hosts"
          note="What else is wrong with the same boxes — the comparison a single finding cannot give you."
        >
          <SiblingFindings finding={finding} onSelect={selectFinding} onOpenCite={openCite} />
        </Section>

        {/* The full ACL is rendered here as well as inside the excerpt, so a reader who reached
            this finding from an ACL host can read the policy without opening anything. */}
        {named.filter((t): t is Extract<ConfigEvidence, { kind: "acl" }> => t.kind === "acl").map((t) => (
          <Section key={t.cite} title={`${t.label} — every line`}>
            <AclLines lines={t.lines} highlightIndex={t.focusIndex} onOpenCite={openCite} />
          </Section>
        ))}
      </div>

      <LiveRegion message={`Evidence for ${finding.id}: ${finding.title}`} />
    </section>
  );
}

function SiblingFindings({
  finding,
  onSelect,
  onOpenCite,
}: {
  finding: Finding;
  onSelect: (id: string) => void;
  onOpenCite: (c: Cite) => void;
}): ReactElement {
  const siblings = useMemo(() => {
    const seen = new Map<string, Finding>();
    for (const h of finding.devices) {
      for (const f of findingsByHost.get(h) ?? []) if (f.id !== finding.id) seen.set(f.id, f);
    }
    return [...seen.values()].sort(bySeverityThenRank);
  }, [finding]);

  if (siblings.length === 0) {
    return (
      <Empty
        title="No other finding names these hosts"
        reason="This is the only punchlist entry listing them. It is the absence of another published finding, not an assessment that nothing else is wrong."
      />
    );
  }

  return (
    <ul className="ev-siblings">
      {siblings.slice(0, 12).map((f) => (
        <li key={f.id} className="ev-siblings__item">
          <SeverityBadge severity={f.severity} compact />
          <button type="button" className="ev-devbtn ev-siblings__btn" onClick={() => onSelect(f.id)}>
            <span className="ev-mono">{f.id}</span>
            <span className="ev-siblings__title">{f.title}</span>
          </button>
          <CiteButton cite={f.cite} onOpen={onOpenCite} label="cite" />
        </li>
      ))}
      {siblings.length > 12 ? (
        <li className="ev-siblings__more">
          {siblings.length - 12} more not listed here — the priority queue holds all{" "}
          {siblings.length}.
        </li>
      ) : null}
    </ul>
  );
}

export default EvidencePane;
