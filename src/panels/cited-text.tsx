/**
 * cited-text.tsx — a sentence and the citations inside it, rendered as one thing.
 *
 * The engine writes its claims and caveats as prose with the record behind each clause named in
 * parentheses — "denied at core1 by ACL PROTECT_SERVERS line 4 of 4 (acls.core1.PROTECT_SERVERS[3]…)".
 * A surface that printed that prose as a plain string showed the citation as inert text, and a
 * sentence that was ASSEMBLED from cited records without carrying their cites (the RIB-incompleteness
 * sentence joined each reason's `label` and dropped its `cite`) showed a claim with nothing behind it
 * at all: on the Path surface "FULL/DR, yet the table" appeared five times and its citations, which the
 * model held, appeared zero times (acceptance B6, refuter, 2026-09-24).
 *
 * `CitedText` renders every citation IN the sentence as the same citation control every other surface
 * uses, in place, so the reader opens the record from the clause it backs. What counts as a citation
 * is decided by the compiled model, never by a list of names or shapes: a token is a citation exactly
 * when `citationCandidates` (./Inspector.tsx — the resolver the Inspector itself uses) finds a record
 * for it. A path-shaped token that resolves to nothing stays text, and a resolvable path is never
 * missed because its shape was not anticipated.
 *
 * `citesIn` exposes the same split, so a guard can count citations PER CLAIM rather than per page.
 */
import { Fragment, type ReactElement } from "react";
import type { Cite } from "../core/types";
import { Cite as CiteLink } from "../ui/primitives";
import { citationCandidates } from "./Inspector";

/* One path segment chain: an identifier followed by `.member`, `[index]` / `[key=value]` or
   `#sidecar-path` parts. Interface names carry `/` (`interfaces.core1.Gi1/0/5`). */
const SEGMENT = String.raw`[A-Za-z_][\w-]*(?:\.[A-Za-z0-9_/-]*[A-Za-z0-9_]|\[[^\]\s]+\]|#[A-Za-z_][\w-]*)*`;
/* A citation may join two record names with " / " — the snapshot's coverage record is cited as
   `collection_completeness / coverage_matrix`. The joined form is tried first, then each part. */
const CANDIDATE = new RegExp(String.raw`${SEGMENT}(?:\s/\s${SEGMENT})*`, "g");

/* A bare identifier ("routes", "coverage", "devices") is an English word as often as it is a model
   key, so a candidate must carry path structure before resolution is even asked. */
const PATH_SHAPED = /[.[#_]|\s\/\s/;

const resolves = (token: string): boolean => PATH_SHAPED.test(token) && citationCandidates(token).length > 0;

export type CitedPart = { text: string } | { cite: Cite };

/** Split prose into text runs and the citations inside it, in order. Concatenating the parts'
 *  `text`/`cite` reproduces the input exactly. */
export function splitCited(text: string): CitedPart[] {
  const out: CitedPart[] = [];
  let at = 0;
  const push = (s: string): void => {
    if (s === "") return;
    const last = out[out.length - 1];
    if (last !== undefined && "text" in last) last.text += s;
    else out.push({ text: s });
  };
  for (const m of text.matchAll(CANDIDATE)) {
    const start = m.index;
    const whole = m[0];
    if (resolves(whole)) {
      push(text.slice(at, start));
      out.push({ cite: whole });
      at = start + whole.length;
      continue;
    }
    /* The joined form did not resolve: try each " / " part on its own. */
    let offset = 0;
    for (const part of whole.split(" / ")) {
      const partStart = start + offset;
      if (resolves(part)) {
        push(text.slice(at, partStart));
        out.push({ cite: part });
        at = partStart + part.length;
      }
      offset += part.length + 3;
    }
  }
  push(text.slice(at));
  return out;
}

/** The citations a sentence carries, in order, as the resolver finds them. */
export function citesIn(text: string): Cite[] {
  return splitCited(text).flatMap((p) => ("cite" in p ? [p.cite] : []));
}

/**
 * The sentence with its citations taken OUT, for a place where a citation cannot be a working control:
 * a `role="option"` row, whose activation runs something else and which may not contain a control
 * (the command palette's suggested flows, acceptance B6). Printing the record there would name it
 * where choosing it opens nothing. The same resolver decides what is a citation, so nothing
 * citation-shaped survives and no ordinary word is cut. A bracket that held only citations goes with
 * them; a citation listed beside other words in a bracket leaves the words; a citation that is a
 * noun of the sentence ("acls.core1.X[2] could match this flow") becomes "the cited record", so the
 * sentence keeps its subject.
 */
export function withoutCitations(text: string): string {
  const MARK = "\u0000";
  const SEP = String.raw`\s*(?:,|;|\/|and)\s*`;
  return splitCited(text)
    .map((p) => ("cite" in p ? MARK : p.text))
    .join("")
    .replace(new RegExp(String.raw`\s*\(\s*${MARK}(?:${SEP}${MARK})*\s*\)`, "g"), "")
    .replace(new RegExp(String.raw`\(\s*${MARK}${SEP}`, "g"), "(")
    .replace(new RegExp(String.raw`${SEP}${MARK}\s*\)`, "g"), ")")
    .replace(new RegExp(MARK, "g"), (_m, at: number, all: string) =>
      /(?:^|[.!?]\s+)$/.test(all.slice(0, at)) ? "The cited record" : "the cited record",
    )
    .trim();
}

/**
 * Prose with every citation inside it rendered as a citation control, in place. `also` names
 * citations that back the sentence but are not written in it (a structured record's `cite` beside its
 * label); each one the text does not already carry is rendered after the text, so a sentence is never
 * shown without the record behind it.
 */
export function CitedText({
  text,
  onOpenCite,
  also = [],
}: {
  text: string;
  onOpenCite: (cite: Cite) => void;
  also?: readonly Cite[];
}): ReactElement {
  const parts = splitCited(text);
  const inline = new Set(parts.flatMap((p) => ("cite" in p ? [p.cite] : [])));
  const extra = [...new Set(also)].filter((c) => !inline.has(c));
  return (
    <>
      {parts.map((p, i) =>
        "cite" in p ? (
          <CiteLink key={i} cite={p.cite} onOpen={onOpenCite} className="cited-text__cite" />
        ) : (
          <Fragment key={i}>{p.text}</Fragment>
        ),
      )}
      {extra.map((c) => (
        <Fragment key={`also-${c}`}>
          {" "}
          <CiteLink cite={c} onOpen={onOpenCite} className="cited-text__cite" />
        </Fragment>
      ))}
    </>
  );
}
