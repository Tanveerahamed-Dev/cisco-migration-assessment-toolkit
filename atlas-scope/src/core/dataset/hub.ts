/**
 * dataset/hub.ts — AssessHub mode: read the snapshot this page was opened for, from the guarded /api, at
 * run time. Nothing about the snapshot is in the build (vite.config.ts, mode "hub"): AssessHub serves
 * /scope outside its API guard, so client evidence may only arrive through /api/snapshots/{id}/raw,
 * which carries every guard (same-origin, Host, loopback-or-token).
 *
 *   1. the snapshot id is read from the path, /scope/snapshots/{id}/ — never from the query string, which
 *      the URL state (app/urlSync.ts) owns and rewrites;
 *   2. GET /api/snapshots/{id}/raw, same-origin credentials, no cache. The body is the stored bytes
 *      exactly; X-Snapshot-Sha256 / X-Snapshot-Bytes / X-Snapshot-Digest-Form state their binding;
 *   3. the worker checks the length, recomputes the sha256 where WebCrypto exists (a secure context),
 *      validates, and compiles with the one compiler, labelled `assesshub:snapshot/{id}` in the
 *      "assesshub-store-blob" digest form — the store's own binding, NOT a file's LF-normalised digest.
 *
 * Every failure is a coded, plain-language refusal; the page then shows that and nothing else.
 */
import type { CompileFn } from "./compile-client";
import type { DatasetIssue, InstalledDataset } from "./types";

/** The only digest form this door accepts from AssessHub (webapp/backend/app.py `get_snapshot_raw`). */
export const HUB_DIGEST_FORM = "assesshub-store-blob";
/** A store id, as the compiler's source label accepts it (`assesshub:snapshot/<id>`). */
const ID = /^[A-Za-z0-9_-]+$/;

/**
 * The snapshot id in `pathname`, which must be `<base>snapshots/<id>/` (the trailing slash optional), or
 * null. `base` is the build's base (import.meta.env.BASE_URL, "/scope/" in the hub build).
 */
export function snapshotIdFromPath(pathname: string, base: string): string | null {
  const root = base.endsWith("/") ? base : `${base}/`;
  if (!pathname.startsWith(`${root}snapshots/`)) return null;
  const rest = pathname.slice(`${root}snapshots/`.length).replace(/\/$/, "");
  let id: string;
  try {
    id = decodeURIComponent(rest);
  } catch {
    return null;
  }
  return ID.test(id) ? id : null;
}

export interface HubDeps {
  pathname: string;
  base: string;
  fetch: typeof fetch;
  /** window.isSecureContext: whether the page can recompute the digest (WebCrypto exists only there). */
  secure: boolean;
  compile: CompileFn;
  onProgress?: (message: string) => void;
}

export type HubResult = { ok: true; dataset: InstalledDataset } | { ok: false; snapshotId: string | null; errors: DatasetIssue[] };

const HTTP_MEANING: Readonly<Record<number, string>> = {
  401: "AssessHub asked for a sign-in. Open AssessHub, sign in, and follow its 'Open in Atlas Scope' link again.",
  403: "AssessHub refused the request (it accepts snapshot reads only from its own pages on this machine, or with a session). Open the snapshot from AssessHub itself.",
  404: "AssessHub has no snapshot with this id. It may have been deleted; go back to AssessHub's snapshot list.",
};

/** Fetch, verify and compile the snapshot the page was opened for. Never throws. */
export async function loadFromAssessHub(deps: HubDeps): Promise<HubResult> {
  const id = snapshotIdFromPath(deps.pathname, deps.base);
  const refuse = (code: string, message: string): HubResult => ({ ok: false, snapshotId: id, errors: [{ code, message }] });
  if (id === null) {
    return refuse(
      "E_HUB_NO_SNAPSHOT_ID",
      `this address (${deps.pathname}) does not name a snapshot. Atlas Scope in AssessHub opens at ${deps.base}snapshots/<id>/ — use the 'Open in Atlas Scope' link on a snapshot's page.`,
    );
  }

  deps.onProgress?.(`Loading Atlas Scope — fetching snapshot ${id} from AssessHub.`);
  let res: Response;
  try {
    res = await deps.fetch(`/api/snapshots/${encodeURIComponent(id)}/raw`, {
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
  } catch (e) {
    return refuse("E_HUB_FETCH", `AssessHub could not be reached (${e instanceof Error ? e.message : String(e)}). Is it still running? Reload the page once it is.`);
  }
  if (!res.ok) {
    return refuse(
      "E_HUB_HTTP",
      `AssessHub answered ${res.status}${res.statusText ? ` ${res.statusText}` : ""} for snapshot ${id}. ${HTTP_MEANING[res.status] ?? "Reload the page; if it persists, check AssessHub's own log."}`,
    );
  }

  const shaHeader = res.headers.get("x-snapshot-sha256");
  const bytesHeader = res.headers.get("x-snapshot-bytes");
  const formHeader = res.headers.get("x-snapshot-digest-form");
  if (shaHeader === null || !/^[0-9a-f]{64}$/.test(shaHeader) || bytesHeader === null || !/^(0|[1-9][0-9]{0,15})$/.test(bytesHeader)) {
    return refuse(
      "E_HUB_HEADERS",
      "AssessHub sent the snapshot without a well-formed binding (X-Snapshot-Sha256 as 64 lowercase hex digits and X-Snapshot-Bytes as a byte count), so what arrived cannot be tied to the stored snapshot. This AssessHub may be older than this Atlas Scope build.",
    );
  }
  if (formHeader !== HUB_DIGEST_FORM) {
    return refuse(
      "E_HUB_DIGEST_FORM",
      `AssessHub stated its digest in the form ${JSON.stringify(formHeader)}, not "${HUB_DIGEST_FORM}", so this build cannot say which bytes the digest covers.`,
    );
  }

  let body: ArrayBuffer;
  try {
    body = await res.arrayBuffer();
  } catch (e) {
    return refuse("E_HUB_FETCH", `the snapshot transfer failed part-way (${e instanceof Error ? e.message : String(e)}). Reload the page.`);
  }

  deps.onProgress?.(
    deps.secure
      ? `Loading Atlas Scope — verifying and compiling snapshot ${id}.`
      : `Loading Atlas Scope — compiling snapshot ${id} (server-attested, not re-verified).`,
  );
  const expectBytes = Number(bytesHeader);
  const outcome = await deps.compile({
    bytes: body,
    label: { source: `assesshub:snapshot/${id}`, sourceOrigin: "assesshub-store", sourceDigestForm: HUB_DIGEST_FORM },
    expect: { sha256: shaHeader, bytes: expectBytes },
  });
  if (!outcome.ok) return { ok: false, snapshotId: id, errors: outcome.errors };
  return {
    ok: true,
    dataset: {
      set: outcome.set,
      origin: {
        kind: "assesshub",
        snapshotId: id,
        verification: outcome.verification === "verified-in-browser" ? "verified-in-browser" : "server-attested",
        attestedSha256: shaHeader,
        attestedBytes: expectBytes,
        warnings: outcome.warnings,
      },
    },
  };
}
