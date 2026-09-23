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
import { RouteFieldValue } from "./HopList";

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
      /** Set by `nearestConfigFor` when the list was ranked first by matching the finding's words. */
      matched?: true;
    }
  | {
      kind: "interface";
      host: string;
      label: string;
      record: InterfaceRecord;
      cite: Cite;
      how: string;
      /** Set by `nearestConfigFor` when the record was ranked first by matching the finding's words. */
      matched?: true;
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
/** Findings listed under the at-rest preview, after the top one. The queue holds all of them. */
const PREVIEW_NEXT = 6;
/** How many step-4 records show before the reader asks for the rest (access lists are never cut). */
const TARGET_CAP = 8;
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

/**
 * Words compared without punctuation or case: the punchlist spells a state "err disabled" in one
 * field and "err-disabled" in the next, and the interface record spells it a third way. Matching is
 * on whole words, padded with spaces, so "up" does not match inside "uplink".
 */
const normalise = (s: string): string => ` ${s.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim()} `;

/** A record attribute worth matching on: long enough to mean something, and not a bare number. */
const matchable = (s: string | null): s is string => s !== null && /[a-z]/i.test(s) && s.replace(/[^a-z0-9]/gi, "").length >= 4;

/** `err-disabled @ Gi0/11 (-8)` → { tag: "err-disabled", port: "Gi0/11" }. */
const DEDUCTION_RE = /^\s*(.+?)\s+@\s+(\S+)/;

/**
 * Words an access-list NAME is spelled with that say what kind of list it is rather than what it is
 * about: `PROTECT_SERVERS` is about servers, and "protect" would match any finding that says so.
 */
const ACL_ROLE_WORDS: ReadonlySet<string> = new Set(["filter", "protect", "return", "permit", "deny", "access", "list", "inbound", "outbound"]);

/** Operator spellings inside list names, expanded so a name can be compared with prose. */
const NAME_ABBREVIATIONS: Readonly<Record<string, string>> = { mgmt: "management", inet: "internet", svr: "server", srv: "server" };

/** `MGMT_IN` → [{ raw: "MGMT", word: "management" }]; role words and words under four letters dropped. */
function aclNameWords(aclName: string): { raw: string; word: string }[] {
  return aclName
    .split(/[^A-Za-z0-9]+/)
    .filter((raw) => raw.length > 0)
    .map((raw) => ({ raw, word: NAME_ABBREVIATIONS[raw.toLowerCase()] ?? raw.toLowerCase() }))
    .filter(({ word }) => word.length >= 4 && /[a-z]/.test(word) && !ACL_ROLE_WORDS.has(word));
}

/**
 * The normalised finding text uses `word` as a whole word, exactly. No singular/plural folding:
 * measured, "server" ~ "servers" tied F107 and F134 (an HTTP server ON the device) to
 * PROTECT_SERVERS (a list guarding the server VLAN) — the same word about a different thing.
 */
const statesWord = (text: string, word: string): boolean => text.includes(` ${word} `);

/**
 * The records we hold for the finding's hosts when the finding names no line of its own, MOST
 * RELEVANT FIRST.
 *
 * This used to return every host's records in collection order, and the header button opens
 * `[0]`. F099 ("L1 risk 'err-disabled' on 6 switch(es)") therefore landed on access13 Gi0/1 —
 * a `connected` uplink — while the same host's err-disabled Gi0/11 and Gi0/12 sat further down the
 * list, and access13's own deductions named them ("err-disabled @ Gi0/11"). "Nearest" was
 * "first", which is a guess wearing the word nearest.
 *
 * The same defect then survived one level down: access lists were pushed ahead of every interface
 * with no score at all, so every finding whose first host is core1 — a hardware failure (F004), a
 * single gateway (F100), VTY telnet (F106) — opened core1 · VOICE_FILTER, core1's first list.
 *
 * Relevance is measured against the finding's own words, never assumed:
 *   - a port the host's own deductions name under a tag the finding states (strongest: the engine
 *     itself tied that state to that port);
 *   - an interface whose collected status the finding states;
 *   - an access list whose NAME uses a word the finding uses, after the abbreviation expansion
 *     above and ignoring words that only say it is a list ("filter", "protect"). The expansion is
 *     shown in `how`, never applied silently.
 * Matched records come first, each saying WHY in `how`. Records nothing matched follow in
 * COLLECTION ORDER — interfaces, then access lists, capped as before — and say they are NOT
 * ranked, because they are not: list order must never be presented as "nearest". A record is
 * never promoted to "this finding's source" by matching.
 */
export function nearestConfigFor(finding: Finding): ConfigEvidence[] {
  const text = normalise(findingText(finding));
  const matched: { ev: ConfigEvidence; score: number; order: number }[] = [];
  const contextIfaces: ConfigEvidence[] = [];
  const contextAcls: ConfigEvidence[] = [];
  let order = 0;

  for (const host of finding.devices) {
    const named = fabric.acls[host];
    if (named) {
      for (const [aclName, lines] of Object.entries(named)) {
        const first = lines[0];
        if (!first) continue;
        const cite = first.cite.replace(/\[\d+]$/, "");
        const hits = aclNameWords(aclName).filter(({ word }) => statesWord(text, word));
        if (hits.length > 0) {
          const why = hits
            .map(({ raw, word }) => (raw.toLowerCase() === word ? `“${word}”` : `“${raw}”, read as “${word}”`))
            .join("; ");
          matched.push({
            ev: {
              kind: "acl",
              host,
              label: `${host} · ${aclName}`,
              lines,
              focusIndex: null,
              cite,
              how: `not named by this finding, but its list name uses a word the finding uses: ${why}`,
              matched: true,
            },
            score: hits.length,
            order: order++,
          });
          continue;
        }
        contextAcls.push({
          kind: "acl",
          host,
          label: `${host} · ${aclName}`,
          lines,
          focusIndex: null,
          cite,
          how: `not named by this finding and not ranked — an access list collected on ${host}, in collection order`,
        });
      }
    }

    // The host's own deductions that tie a state the finding states to a specific port.
    const deducedPorts = new Map<string, string>();
    for (const d of deviceById.get(host)?.deductions ?? []) {
      const m = DEDUCTION_RE.exec(d);
      const tag = m?.[1];
      const port = m?.[2];
      if (tag === undefined || port === undefined || !matchable(tag)) continue;
      if (text.includes(normalise(tag))) deducedPorts.set(port, d.trim());
    }

    let unmatched = 0;
    for (const i of interfacesOf(host)) {
      const reasons: string[] = [];
      let score = 0;
      const deduction = deducedPorts.get(i.port);
      if (deduction !== undefined) {
        score += 2;
        reasons.push(`${host}'s own deductions name it (“${deduction}”)`);
      }
      /* Status only, never description: a description is free text an operator typed, and matching
         it measured badly — F104 ("local user(s) … password") "matched" core1 Vlan10 because that
         SVI is described "USERS". A status is a collected STATE, which is what a finding is about. */
      if (matchable(i.status) && text.includes(normalise(i.status))) {
        score += 1;
        reasons.push(`its collected status “${i.status}” is the state this finding describes`);
      }
      if (score > 0) {
        matched.push({
          ev: {
            kind: "interface",
            host,
            label: `${host} ${i.port}${i.status === null ? "" : ` (${i.status})`}`,
            record: i,
            cite: i.cite,
            how: `not named literally by this finding, but it matches it: ${reasons.join("; ")}`,
            matched: true,
          },
          score,
          order: order++,
        });
        continue;
      }
      if (unmatched >= 6) continue;
      unmatched += 1;
      contextIfaces.push({
        kind: "interface",
        host,
        label: `${host} ${i.port}`,
        record: i,
        cite: i.cite,
        how: `not named by this finding and not ranked — an interface record collected on ${host}, in collection order`,
      });
    }
  }

  const ranked = matched.sort((a, b) => b.score - a.score || a.order - b.order).map((m) => m.ev);
  return [...ranked, ...contextIfaces, ...contextAcls];
}

/** True when a nearest record was ranked first because it matches the finding's own words. */
export const isMatchedNearest = (t: ConfigEvidence): boolean => t.kind !== "route" && t.matched === true;

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
              /* An observed negative only where the running configuration WAS collected; otherwise
                 the record is missing, not empty (2026-09-22 critic, B1 — same class as DevicePane). */
              why: i.runConfigObserved
                ? "this interface carries no description in the collected configuration"
                : "the running configuration for this port was not collected, so its description is unknown — not absent",
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
              via <RouteFieldValue route={r} field="nextHop" compact classes={{ value: "ev-mono" }} />
              {" out "}
              {orNotObserved(r.outIntf, (s) => <span className="ev-mono">{s}</span>, { what: "egress interface", compact: true })}
              {" ("}
              {orNotObserved(r.source, (s) => s, { what: "route source", compact: true })}
              {", AD "}
              <RouteFieldValue route={r} field="adminDistance" compact />
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

/**
 * How many records of this family the collection produced for this host — or null when it produced
 * NONE. A zero here is never a measurement: no family in this snapshot is a complete per-host
 * census (the Device pane says of the same host "the collection produced no l3_forwarding row …
 * whether it carries an SVI at all was not established here"), so "0 L3 interface records" stated
 * as a count contradicted it. The class is fixed here, once, for every family — not by listing the
 * families that happened to be caught — and the caller renders null through NotObserved.
 */
function familyCount(family: RecordFamily, host: string): number | null {
  const n = rawFamilyCount(family, host);
  return n === null || n === 0 ? null : n;
}

function rawFamilyCount(family: RecordFamily, host: string): number | null {
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

/**
 * The finding's OWN evidence pointer, exactly as the producer published it — and what it is not.
 *
 * A1 (2026-09-22): the source snapshot was searched for any per-finding pointer to an interface,
 * an ACL line or a configuration block that the compiler might be dropping. There is none; the
 * one producer field the compiler did drop is `source_command` (33 of 146 rows), the show-command
 * the engine cites for the finding's category. It is shown here, in the header, because it is the
 * only evidence link the ENGINE made for most findings — every other record in this pane is one we
 * reached by matching words or listing a host's records. It names a command, and the snapshot keeps
 * no raw command output, so it is stated as provenance and never offered as a record to open.
 * One owner: every finding renders exactly one of the two branches below.
 */
function FindingSource({ finding }: { finding: Finding }): ReactElement {
  const cmd = finding.sourceCommand ?? null;
  return (
    <p className="ev__jump ev__source" data-finding-source={cmd === null ? "uncited" : "cited"}>
      <span className="ev__jump-note">
        {cmd === null ? (
          "Source: the engine cites no source command for this finding, so it names no evidence of its own beyond the devices listed."
        ) : (
          <>
            Source: the engine cites <span className="ev-mono">{cmd}</span> for this finding (it assigns the
            command by category). The command&rsquo;s output is not held in this snapshot, so this says
            where the evidence came from; it is not a record to open.
          </>
        )}
      </span>
    </p>
  );
}

export function EvidencePane({ onOpenCite, onShowConfig, className }: EvidencePaneProps): ReactElement {
  const findingId = useInvestigation((s) => s.findingId);
  const selectFinding = useInvestigation((s) => s.selectFinding);
  const selectDevice = useInvestigation((s) => s.selectDevice);
  const deviceId = useInvestigation((s) => s.deviceId);
  const setEvidenceTab = useInvestigation((s) => s.setEvidenceTab);
  const openCite = useOpenCite(onOpenCite);

  /* The open excerpt belongs to the finding it was opened FOR. It used to be plain state, so a record
     opened under F004 stayed open under F099 — present in F099's list, but opened by nobody for
     F099. Keying it to the finding id closes it on every selection change without an effect. */
  const [opened, setOpened] = useState<{ findingId: string; target: ConfigEvidence } | null>(null);
  const openTarget = opened !== null && opened.findingId === findingId ? opened.target : null;
  const setOpenTarget = useCallback(
    (t: ConfigEvidence | null) => setOpened(t === null || findingId === null ? null : { findingId, target: t }),
    [findingId],
  );
  /* The element that opened the excerpt, captured at click time rather than bound to the first
     button: focus must return to the control the reader actually used, not to the one that
     happens to be first. */
  const triggerRef = useRef<HTMLButtonElement | null>(null);

  const finding = findingId === null ? null : (findingById.get(findingId) ?? null);

  /* SELECTING FROM INSIDE THIS PANE RE-RENDERS THE CONTROL AWAY. Every in-pane selection route —
     the rest-state primary button, the "Next by rank" list, the sibling list — sits in markup that
     the new selection replaces, so the focused button was removed and focus fell to <body> (measured
     2026-09-22: Enter on "F002 …" left document.activeElement === BODY). All three go through
     `selectHere`, which arms a one-shot hand-off; once the new chain has rendered, focus lands on its
     heading — the thing the reader asked for — unless focus has meanwhile gone somewhere live. */
  const titleRef = useRef<HTMLHeadingElement>(null);
  const focusTitlePending = useRef(false);
  const selectHere = useCallback(
    (id: string) => {
      focusTitlePending.current = true;
      selectFinding(id);
    },
    [selectFinding],
  );
  useEffect(() => {
    if (!focusTitlePending.current) return;
    focusTitlePending.current = false;
    const active = document.activeElement;
    const lost = active === null || active === document.body || !active.isConnected;
    if (lost) titleRef.current?.focus();
  }, [findingId]);

  const named = useMemo(() => (finding ? configEvidenceFor(finding) : []), [finding]);
  const nearest = useMemo(() => (finding && named.length === 0 ? nearestConfigFor(finding) : []), [finding, named.length]);
  const targets = named.length > 0 ? named : nearest;
  /* The step-4 list is capped so a many-host finding does not bury the chain, but the cap is
     STATED and reversible, and it never cuts an access list: an ACL is the only record kind that
     carries literal configuration text, so it is the last thing a cap may hide. The cut used to be
     a silent `slice(0, 8)` under a sentence counting all of them — "The 10 records below" over 8
     buttons, with MGMT_IN and INET_RETURN the two dropped (2026-09-22 critic, A1). */
  const [allTargetsFor, setAllTargetsFor] = useState<string | null>(null);
  const showAllTargets = finding !== null && allTargetsFor === finding.id;
  const shownTargets = showAllTargets
    ? targets
    : targets.filter((t, i) => i < TARGET_CAP || t.kind === "acl");

  const show = useCallback(
    (t: ConfigEvidence, trigger: HTMLButtonElement) => {
      triggerRef.current = trigger;
      if (onShowConfig) onShowConfig(t);
      else setOpenTarget(t);
    },
    [onShowConfig, setOpenTarget],
  );

  const closeConfig = useCallback(() => {
    setOpenTarget(null);
    triggerRef.current?.focus();
  }, [setOpenTarget]);

  /* The chain's own step-4 control sits at the bottom of a long pane: measured at 1920×1080 with
     the pane at scrollTop 0 it was 23 px below the fold, at 1600×900 it was 203 px below, and at
     1440×900 it was 245 px below. A1's two-click path was therefore really click, SCROLL, click —
     and at 1920 the margin was one line of prose. This is the same control, hoisted into the
     header where it cannot fall below the fold at any viewport. The excerpt itself still opens
     inside step 4, where the chain's narrative is: there is one disclosure, opened from two
     places, rather than two panels that could disagree. */
  const first = targets[0] ?? null;

  if (finding === null) {
    /* THE REST STATE IS A PREVIEW, NOT A BLANK. The blind panel measured this rail at ~26 % of
       the width at rest showing one sentence and one button. It now shows what the button would
       open — the top finding's own summary — and the next few in rank order, each one click from
       its chain. It is labelled as a preview: nothing is SELECTED until the reader asks, so no
       other surface re-aims because this rail has content. */
    const ranked = [...fabric.findings].sort(bySeverityThenRank);
    const top = ranked[0];
    const next = ranked.slice(1, 1 + PREVIEW_NEXT);
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
                ? "Select a finding in the priority queue and its chain to the configuration text appears here. The highest-ranked one is previewed below."
                : `The investigation names finding ${findingId}, but no such record exists in this snapshot. The link may predate the snapshot in the header.`
            }
            action={
              top ? (
                <Button variant="primary" onClick={() => selectHere(top.id)}>
                  Open the highest-priority finding ({top.id})
                </Button>
              ) : undefined
            }
          />
          {top ? (
            <section className="ev-preview" aria-label={`Preview of ${top.id}, not selected`}>
              <p className="ev-preview__kicker">Highest priority · preview, not selected</p>
              <div className="ev__idline">
                <SeverityBadge severity={top.severity} />
                <span className="ev-mono ev__id">{top.id}</span>
                <CiteButton cite={top.cite} onOpen={openCite} />
              </div>
              <p className="ev-preview__title">{top.title}</p>
              <p className="ev-preview__hosts ev-mono ev-wrap">
                {top.devices.length > 0 ? top.devices.join(", ") : "names no host"}
                {top.category ? <span className="ev-preview__cat"> · {top.category}</span> : null}
              </p>
              {top.detail ? <p className="ev-prose ev-preview__detail">{top.detail}</p> : null}
            </section>
          ) : null}
          {next.length > 0 ? (
            <section aria-label="Next by rank">
              <h3 className="ev-sub">Next by rank</h3>
              <ul className="ev-siblings">
                {next.map((f) => (
                  <li key={f.id} className="ev-siblings__item">
                    <SeverityBadge severity={f.severity} compact />
                    <button type="button" className="ev-devbtn ev-siblings__btn" onClick={() => selectHere(f.id)}>
                      <span className="ev-mono">{f.id}</span>
                      <span className="ev-siblings__title">{f.title}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
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
        <h2 className="ev__title" ref={titleRef} tabIndex={-1}>
          {finding.title}
        </h2>
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
        <FindingSource finding={finding} />
        {first === null ? null : (
          <div className="ev__jump" data-evidence-route={named.length > 0 ? "named" : isMatchedNearest(first) ? "ranked" : "context"}>
            {/* A record reached only by collection order is CONTEXT, not the configuration evidence
                behind the finding: 133 of 139 fallback landings were such records, and the primary
                button presented each ("Show the first record collected on core1: description
                to-core2-a" for a hardware-support finding) as the evidence route (2026-09-22
                critic, A1). The primary action is reserved for a record the finding names or one
                ranked by its own words; an unranked record is offered as a secondary browse. */}
            <Button
              variant={named.length > 0 || isMatchedNearest(first) ? "primary" : "ghost"}
              size="sm"
              onClick={(e) => show(first, e.currentTarget)}
            >
              {named.length > 0
                ? `Show the configuration this finding names: ${first.label}`
                : isMatchedNearest(first)
                  ? `Show the record that matches this finding: ${first.label}`
                  : `Browse ${first.host}'s collected records (context, not this finding's evidence)`}
            </Button>
            {named.length > 0 ? null : (
              <span className="ev__jump-note">
                {isMatchedNearest(first)
                  ? first.kind === "acl"
                    ? "Matched by its list name, not quoted by the finding — the finding names no configuration line."
                    : "Matched by its state, not quoted by the finding — the finding names no configuration line."
                  : "No configuration evidence route: the finding names no configuration line and nothing we hold matches its words. The records there are in collection order and are context, not relevance."}
              </span>
            )}
          </div>
        )}
        {/* Selecting a finding re-aims the highlight, the queue and this chain — NOT the device
            subject (design-brief §5.1: the camera and the device surfaces stay where the reader
            put them). A reader on core2 who picks a core1 finding therefore still sees core2 in the
            Device pane; that is stated here, with the one-key route to move it (2026-09-22
            critic, A4), rather than left for the reader to mistake for a failed re-aim. */}
        {finding.devices[0] !== undefined && deviceId !== null && !finding.devices.includes(deviceId) ? (
          <p className="ev__jump ev__devnote" data-finding-device-note="">
            <span className="ev__jump-note">
              {`The Device pane still shows ${deviceId}: selecting a finding moves the highlight and the queue, not the device.`}
            </span>
            <Button
              variant="secondary"
              size="sm"
              aria-keyshortcuts="d"
              onClick={() => selectDevice(finding.devices[0] ?? null)}
            >
              {`Select ${finding.devices[0]}`}
              <kbd className="ev__kbd" aria-hidden="true">D</kbd>
            </Button>
          </p>
        ) : null}
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

            <ChainStep n={2} title={finding.devices.length === 0 ? "The fleet it speaks for" : `The ${plural(finding.devices.length, "device")} it names`}>
              {finding.devices.length === 0 ? (
                <>
                  <NotObserved
                    what="devices"
                    why="this finding names no device, so it cannot be traced to one"
                    cite={finding.cite}
                    onOpenCite={openCite}
                  />
                  <FleetDenominator finding={finding} />
                </>
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
                            /* A device selection moves the SUBJECT, never the reader's tab —
                               the same rule as a fabric, palette or hop pick, all of which call
                               `selectDevice` alone. This chip used to force Summary, so a reader
                               on Ports, Routing or ACL lost that choice only when the device came
                               from here (acceptance A4). Every Device-pane tab renders for every
                               device — an absent one explains itself — so there is no record
                               this tab cannot show and nothing to fall back from. Step 3 below is
                               different by design: it is a route INTO a named evidence family. */
                            selectDevice(host);
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
                                why={
                                  deviceById.get(host)?.collected === false
                                    ? `${host} was never collected (topology only), so it has no ${FAMILY_LABEL[family]}s to count`
                                    : `the collection produced no ${FAMILY_LABEL[family]} for ${host}; whether it has none was not established here`
                                }
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
                    : nearest.some(isMatchedNearest)
                      ? ` The ${plural(nearest.length, "record")} below are configuration evidence we hold for the hosts it names — those matching the finding's words first, then the rest in collection order — shown as context, not as this finding's source.`
                      : ` The ${plural(nearest.length, "record")} below are configuration evidence we hold for the hosts it names, in collection order: none of them matches the finding's words, so none is ranked as nearest. Shown as context, not as this finding's source.`}
                </p>
              )}
              {targets.length === 0 ? (
                <NotObserved
                  what="configuration evidence"
                  why={
                    /* Two different absences, and they must not share a sentence.
                       A finding that NAMES hosts we hold nothing for is a genuine collection gap,
                       and saying so is true. A finding that names NO host is a conclusion drawn
                       across the whole fleet — F142, "No QoS configured anywhere", rests on a
                       complete sweep of every assessable device, all of which WERE collected.
                       Describing that as "not collected for the hosts this finding names" was
                       false twice over (there are no such hosts, and the data exists), and it is
                       the model-gap-as-collection-gap defect already fixed once in the compiler:
                       it sends an engineer to gather evidence the snapshot already holds, and it
                       quietly weakens a finding that is actually well-founded. */
                    finding.devices.length === 0
                      ? "this finding is a conclusion drawn across the whole fleet rather than about one device, so there is no single record behind it to open — the evidence is that no assessable device carried the configuration it describes"
                      : `no access list, interface record or route entry was collected for ${finding.devices.join(", ")}`
                  }
                  cite={finding.cite}
                  onOpenCite={openCite}
                />
              ) : (
                <div className="ev-cfgactions" data-targets-shown={shownTargets.length} data-targets-total={targets.length}>
                  {shownTargets.length < targets.length ? (
                    <p className="ev-step__text ev-cfgactions__cap">
                      Showing {shownTargets.length} of {plural(targets.length, "record")} — every access
                      list is shown; {plural(targets.length - shownTargets.length, targets.every((t) => t.kind !== "route") ? "interface record" : "interface or route record")} further down
                      the collection order {targets.length - shownTargets.length === 1 ? "is" : "are"} folded.{" "}
                      <Button variant="ghost" size="sm" onClick={() => setAllTargetsFor(finding.id)}>
                        Show all {targets.length}
                      </Button>
                    </p>
                  ) : null}
                  {shownTargets.map((t, i) => (
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

            {/* This step used to be titled "The raw snapshot record" and to say the Inspector walks
                the cite into the source snapshot and shows "the record itself". The source
                snapshot is not bundled with this build, and the Inspector says so: it shows the
                COMPILED record that carries the citation. A projection presented as the source
                bytes is the exact overclaim B6 forbids, so the words now match the Inspector's. */}
            <ChainStep n={5} title="The compiled record behind the citation">
              <p className="ev-step__text">
                <span className="ev-mono">{finding.cite}</span> is a path into the source snapshot,
                which is not bundled with this build. The Inspector shows the compiled record that
                carries this citation — this build&rsquo;s projection of the source record, not its
                bytes — and its Provenance tab names the source file and sha256 needed to read the
                original.
              </p>
              <CiteButton cite={finding.cite} onOpen={openCite} />
              <SnapshotBinding />
            </ChainStep>
          </ol>
        </Section>

        {/* A finding that names no host has no "these hosts". Rendering the block anyway said "This
            is the only punchlist entry listing them" about an empty list — a sentence about nothing. */}
        {finding.devices.length === 0 ? null : (
          <Section
            title="Other findings on these hosts"
            note="What else is wrong with the same boxes — the comparison a single finding cannot give you."
          >
            <SiblingFindings finding={finding} onSelect={selectHere} onOpenCite={openCite} />
          </Section>
        )}

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

/**
 * The denominator a fleet-wide finding states for itself, reconciled against the coverage.
 *
 * F142 says "None of the 18 assessable device(s)…" while 23 devices were collected and 26 exist. A
 * fleet-wide ABSENCE claim is only as wide as its denominator, and an unexplained 18 silently
 * narrows "anywhere" to a set nobody named. Read from the finding's own text (the producer owns the
 * number) and set beside the compiled coverage (which owns the others); neither is suppressed.
 */
export function statedDenominator(finding: Finding): number | null {
  const m = /\b(\d+)\s+assessable\s+device/i.exec(`${finding.title} ${finding.detail ?? ""}`);
  return m === null ? null : Number(m[1]);
}

function FleetDenominator({ finding }: { finding: Finding }): ReactElement {
  const stated = statedDenominator(finding);
  const total = fabric.devices.length;
  const collected = fabric.devices.filter((d) => d.collected).length;
  if (stated === null) {
    return (
      <p className="ev-step__text ev-step__text--absent">
        It states no denominator of its own, so how many of the {collected} collected of {total} devices it
        swept is not observed.
      </p>
    );
  }
  const outside = collected - stated;
  return (
    <ul className="ev-denominator" aria-label="The finding's denominator against this snapshot's coverage">
      <li>
        <span className="ev-mono">{stated}</span> assessable devices — the denominator the finding states
      </li>
      <li>
        <span className="ev-mono">{collected}</span> of <span className="ev-mono">{total}</span> devices collected
        in this snapshot
      </li>
      {outside !== 0 ? (
        <li data-disagreement="true">
          {`DISAGREEMENT: the finding's denominator (${stated}) differs from the collected count (${collected}). `}
          {outside > 0
            ? `${outside} collected device(s) fall outside it, and the finding does not name which or why, so its "anywhere" covers ${stated} of ${total} devices, not the fleet. For the other ${total - stated}, the configuration it describes is not observed rather than absent.`
            : "It counts more devices than were collected; which records it counted is not observed."}
        </li>
      ) : null}
    </ul>
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
