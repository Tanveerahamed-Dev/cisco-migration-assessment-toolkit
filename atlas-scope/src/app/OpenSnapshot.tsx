/**
 * OpenSnapshot.tsx — which dataset this page shows, said where it cannot be missed, and the controls
 * that change it.
 *
 *   DatasetBanner       A persistent line (rendered by the status bar, which is on every screen) whenever
 *                       the page shows anything but this build's bundled sample — an AssessHub snapshot or
 *                       a file the reader opened — naming it, its origin and its digests. And whenever an
 *                       opened file could NOT be restored: then it says the sample on screen is not their
 *                       file. The bundled sample itself needs no banner: the header names it.
 *   OpenSnapshotControl "Open a snapshot file…" (standalone builds): the file is validated and compiled in
 *                       a worker with the one compiler, kept in this browser (IndexedDB), and the page
 *                       reloads into it. Nothing is uploaded. Refusals are shown with their codes.
 *   ReturnToSample      Forget the opened file and reload into the bundled sample.
 *
 * Every figure is read from the loaded dataset (core/dataset.ts) at render time.
 */
import { useCallback, useId, useRef, useState, type ReactElement } from "react";
import { datasetNotices, datasetOrigin, isBundledSample, type DatasetIssue, type DatasetOrigin } from "../core/dataset";
import { fabric } from "../core/data";
import { datasetActions } from "../core/dataset/actions";
import { openSnapshotFile, returnToSample } from "../core/dataset/opened";
import type { SnapshotMeta } from "../core/types";
import { Button } from "../ui/primitives";

/** The digest form, in words: which bytes `sourceSha256` was taken over. */
export function digestFormWords(form: SnapshotMeta["sourceDigestForm"]): string {
  return form === "assesshub-store-blob" ? "AssessHub's stored bytes, exactly" : "the file's LF-normalised bytes";
}

/** The digest form as a short label: "LF-normalised" for a file, "AssessHub stored bytes" for a store blob. */
export function digestFormLabel(form: SnapshotMeta["sourceDigestForm"]): string {
  return form === "assesshub-store-blob" ? "AssessHub stored bytes" : "LF-normalised";
}

/** One line naming the dataset and where it came from. */
export function describeOrigin(origin: DatasetOrigin): string {
  switch (origin.kind) {
    case "bundled-sample":
      return "the sample fleet bundled with this build of Atlas Scope";
    case "opened-file":
      return `${origin.fileName}, a snapshot file opened in this browser — read and compiled here, not uploaded`;
    case "assesshub":
      return `AssessHub snapshot ${origin.snapshotId}, read from AssessHub at run time`;
  }
}

/** Where it came from, without its name and in few words (the banner's own line; the full sentence is its title). */
export function originShort(origin: DatasetOrigin): string {
  switch (origin.kind) {
    case "bundled-sample":
      return "bundled sample";
    case "opened-file":
      return `file opened in this browser, not the sample`;
    case "assesshub":
      return "read from AssessHub, compiled here";
  }
}

/** Whether the digest shown was checked in this browser, in the owner's words. */
export function verificationWords(origin: DatasetOrigin): string | null {
  if (origin.kind !== "assesshub") return null;
  return origin.verification === "verified-in-browser"
    ? "digest recomputed in this browser: the sha256 over the bytes received equals the one AssessHub stated"
    : "server-attested, not re-verified: this page is not a secure context, so it could not recompute the sha256";
}

/**
 * Where a displayed digest came from, as a clause every digest statement carries (phase 3.5, P3E-V3).
 * Outside a secure context the page computes no sha256: both digests of the binding ARE AssessHub's
 * X-Snapshot-Sha256, passed through (core/dataset/hashes.ts `attestedHashes`). A title or label reading
 * "over the bytes as read" there claimed a computation that did not happen.
 */
export function digestSourceClause(origin: DatasetOrigin): string {
  return origin.kind === "assesshub" && origin.verification === "server-attested" ? ", as AssessHub stated it (not recomputed here)" : "";
}

/** The exact-bytes digest, described by where its value came from. */
export function exactDigestWords(origin: DatasetOrigin): string {
  return digestSourceClause(origin) === "" ? "the engine's binding form, over the bytes as read" : `the engine's binding form${digestSourceClause(origin)}`;
}

const short = (d: string): string => `${d.replace(/^sha256:/, "").slice(0, 12)}…`;

const bannerStyle = {
  flexBasis: "100%",
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  gap: "var(--sp-2)",
  paddingBlock: "var(--sp-1)",
  color: "var(--text)",
  whiteSpace: "normal",
} as const;

/** The persistent dataset line. Null only for this build's bundled sample with nothing to report. */
export function DatasetBanner(): ReactElement | null {
  const m = fabric.meta;
  if (isBundledSample && datasetNotices.length === 0) return null;
  const verification = verificationWords(datasetOrigin);
  return (
    <section className="sb-dataset" aria-label="Loaded dataset" data-origin={datasetOrigin.kind} style={bannerStyle}>
      {datasetNotices.map((n) => (
        <p key={n.code} role="alert" data-code={n.code} style={{ margin: 0, color: "var(--text)" }}>
          {`${n.message} [${n.code}]`}
        </p>
      ))}
      {isBundledSample ? null : (
        <>
          <span className="sb__key">dataset</span>
          <strong data-dataset-name>{datasetOrigin.kind === "assesshub" ? `AssessHub snapshot ${datasetOrigin.snapshotId}` : datasetOrigin.kind === "opened-file" ? datasetOrigin.fileName : m.source}</strong>
          <span title={`${describeOrigin(datasetOrigin)}.`}>{`— ${originShort(datasetOrigin)}`}</span>
          <span>
            {"sha256 "}
            <code title={`sha256 over ${digestFormWords(m.sourceDigestForm)}${digestSourceClause(datasetOrigin)}: ${m.sourceSha256}`} data-digest="sourceSha256">
              {short(m.sourceSha256)}
            </code>
            {` (${m.sourceDigestForm}, ${m.sourceBytes} bytes)`}
          </span>
          <span>
            {"exact "}
            <code title={`${exactDigestWords(datasetOrigin)}: ${m.sourceExactSha256}`} data-digest="sourceExactSha256">
              {`sha256:${short(m.sourceExactSha256)}`}
            </code>
          </span>
          {verification === null || datasetOrigin.kind !== "assesshub" ? null : (
            <span data-verification={datasetOrigin.verification} title={`${verification}.`}>
              {datasetOrigin.verification === "verified-in-browser" ? "digest recomputed here, equal to AssessHub's" : "server-attested, not re-verified"}
            </span>
          )}
          <DatasetWarnings warnings={datasetOrigin.kind === "bundled-sample" ? [] : datasetOrigin.warnings} />
          <ReturnToSample />
        </>
      )}
    </section>
  );
}

/**
 * What the validator reported about the loaded snapshot without refusing it (tools/lib/validate-snapshot.mjs
 * warnings: a collection date it does not state, a section it does not carry). Each is said, with its
 * code — a snapshot that lacks something is never presented as one that lacks nothing. Collapsed behind
 * its count so the status bar stays one line; the text is in the page either way.
 */
function DatasetWarnings({ warnings }: { warnings: readonly DatasetIssue[] }): ReactElement | null {
  if (warnings.length === 0) return null;
  return (
    <details className="sb-dataset__warnings">
      <summary>{`${warnings.length} ${warnings.length === 1 ? "thing" : "things"} this snapshot does not state`}</summary>
      <ul style={{ margin: 0, paddingInlineStart: "var(--sp-4)" }}>
        {warnings.map((w, i) => (
          <li key={`${w.code}-${i}`} data-warning={w.code}>{`${w.message} [${w.code}]`}</li>
        ))}
      </ul>
    </details>
  );
}

/** "Return to the sample" — only while an opened file is shown. */
export function ReturnToSample(): ReactElement | null {
  const [busy, setBusy] = useState(false);
  if (datasetOrigin.kind !== "opened-file") return null;
  return (
    <Button
      size="sm"
      disabled={busy}
      onClick={() => {
        setBusy(true);
        void returnToSample({ store: datasetActions.store, reload: datasetActions.reload });
      }}
    >
      Return to the sample
    </Button>
  );
}

type OpenState = { phase: "idle" } | { phase: "working"; fileName: string } | { phase: "refused"; fileName: string; errors: DatasetIssue[] };

/** "Open a snapshot file…" — standalone builds only; an AssessHub page shows the snapshot it was opened for. */
export function OpenSnapshotControl(): ReactElement | null {
  const input = useRef<HTMLInputElement>(null);
  const id = useId();
  const [state, setState] = useState<OpenState>({ phase: "idle" });
  const onFile = useCallback(async (file: File | undefined) => {
    if (file === undefined) return;
    setState({ phase: "working", fileName: file.name });
    const r = await openSnapshotFile(file, datasetActions);
    if (!r.ok) setState({ phase: "refused", fileName: file.name, errors: r.errors });
  }, []);
  if (import.meta.env.MODE === "hub" || datasetOrigin.kind === "assesshub") return null;
  return (
    <div className="open-snapshot" style={{ display: "grid", gap: "var(--sp-2)" }}>
      <input
        ref={input}
        id={id}
        type="file"
        accept=".json,application/json"
        hidden
        onChange={(e) => {
          void onFile(e.currentTarget.files?.[0]);
          e.currentTarget.value = "";
        }}
      />
      <Button size="sm" disabled={state.phase === "working"} onClick={() => input.current?.click()} aria-describedby={`${id}-what`}>
        Open a snapshot file…
      </Button>
      <p id={`${id}-what`} style={{ margin: 0, color: "var(--text-muted)" }}>
        An engine snapshot (.snapshot.json) is read, checked and compiled in this browser and kept here until you return to the
        sample. Nothing is uploaded.
      </p>
      {state.phase === "working" ? (
        <p role="status" style={{ margin: 0 }}>{`Checking and compiling ${state.fileName}…`}</p>
      ) : null}
      {state.phase === "refused" ? (
        <div role="alert" data-open-refused>
          <p style={{ margin: 0 }}>{`${state.fileName} cannot be shown:`}</p>
          <ul style={{ margin: 0, paddingInlineStart: "var(--sp-4)" }}>
            {state.errors.map((e, i) => (
              <li key={`${e.code}-${i}`} data-code={e.code}>{`${e.message} [${e.code}]`}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
