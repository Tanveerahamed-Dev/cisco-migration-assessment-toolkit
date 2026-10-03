import {
  EMBED_MAX_QUERY_IDS, EMBED_PROTOCOL, PROJECTION_SCHEMA, TOPOLOGY_STYLE_SCHEMA, parseEmbedMessage, sameProjectionIdentity,
  type ContextHasher, type EmbedMessage, type EmbedRefusalCode, type ProjectionIdentity, type SelectionTarget,
} from "../../../webapp/frontend/src/projectionEmbed";
import { releaseFocusFrom } from "../app/focus-return";
import { own } from "../core/own";
import type { ContractMode } from "./entry";
import { ContractRefusal } from "./errors";
import { hasSelection } from "./geometry";
import { loadCompleteTopology, loadContractPath } from "./load";
import type { CompleteTopology } from "./types";
import type { ContractView, ViewOptions } from "./view";

type Mode = Extract<ContractMode, { valid: true }>;
type ViewModule = { createContractView(root: HTMLElement, model: CompleteTopology, options: ViewOptions): ContractView };
export type ContractBootDeps = Readonly<{ host?: Window; fetch?: typeof fetch; subtle?: ContextHasher;
  loadView?: () => Promise<ViewModule>; loadTopology?: typeof loadCompleteTopology; loadPath?: typeof loadContractPath }>;
const READY_INTERVAL_MS = 750;
const BIND_TIMEOUT_MS = 30_000;

/** No API read precedes init, and no model is displayed before complete source/context binding. */
export function bootContractMode(root: HTMLElement, mode: Mode, deps: ContractBootDeps = {}): () => void {
  const host = deps.host ?? window;
  const parent = host.parent;
  const fetcher = deps.fetch ?? host.fetch.bind(host);
  let alive = true, phase: "ready" | "binding" | "bound" = "ready", epoch = 0, queryEpoch = 0;
  let expected: { identity: ProjectionIdentity; context_digest: string } | null = null;
  let model: CompleteTopology | null = null, view: ContractView | null = null;
  let loading: AbortController | null = null, querying: AbortController | null = null;
  let readyTimer: number | null = null, bindTimer: number | null = null;
  const queryIds = new Set<string>();
  const common = { protocol: EMBED_PROTOCOL, nonce: mode.nonce };
  const send = (message: EmbedMessage): void => { if (alive && parent !== host) parent.postMessage(message, mode.origin); };
  function clearTimers(): void {
    if (readyTimer !== null) host.clearTimeout(readyTimer);
    if (bindTimer !== null) host.clearTimeout(bindTimer);
    readyTimer = null; bindTimer = null;
  }
  function dispose(): void {
    if (!alive) return;
    alive = false; epoch++; queryEpoch++; clearTimers();
    loading?.abort(); querying?.abort();
    host.removeEventListener("message", onMessage); host.removeEventListener("pagehide", dispose);
    view?.dispose(); view = null; model = null; queryIds.clear();
  }
  function refuse(code: EmbedRefusalCode, requestId: string | null = null): void {
    if (!alive) return;
    const context = phase === "bound" && expected ? expected : { identity: null, context_digest: null };
    send({ ...common, ...context, type: "refused", code, request_id: requestId });
    dispose();
    const message = document.createElement("p"); message.className = "contract-scope-refusal"; message.setAttribute("role", "alert");
    message.textContent = `The 3D view is unavailable. Continue in the 2D Topology & Paths view. [${code}]`;
    releaseFocusFrom(root, null); root.replaceChildren(message);
  }
  const bound = (): void => { if (expected) send({ ...common, ...expected, type: "bound" }); };
  const ready = (): void => {
    if (!alive || phase !== "ready") return;
    send({ ...common, type: "ready", snapshot_id: mode.snapshotId, projection_schema: PROJECTION_SCHEMA, style_schema: TOPOLOGY_STYLE_SCHEMA });
    readyTimer = host.setTimeout(ready, READY_INTERVAL_MS);
  };
  function selected(target: SelectionTarget | null): void {
    if (!alive || phase !== "bound" || !model || !view || !expected) return;
    if (!hasSelection(model, target)) { refuse("INVALID_MESSAGE"); return; }
    view.select(target); send({ ...common, ...expected, type: "select", target });
  }
  async function receive(message: EmbedMessage): Promise<void> {
    if (!alive) return;
    if (message.type === "init") {
      if (message.identity.snapshot_id !== mode.snapshotId) { refuse("IDENTITY_MISMATCH"); return; }
      if (expected) {
        if (!sameProjectionIdentity(expected.identity, message.identity)) { refuse("IDENTITY_MISMATCH"); return; }
        if (expected.context_digest !== message.context_digest) { refuse("CONTEXT_MISMATCH"); return; }
        if (phase === "bound") bound();
        return;
      }
      phase = "binding"; expected = { identity: message.identity, context_digest: message.context_digest };
      clearTimers(); bindTimer = host.setTimeout(() => refuse("HTTP_REFUSED"), BIND_TIMEOUT_MS);
      loading = new AbortController(); const turn = ++epoch;
      try {
        const loaded = await (deps.loadTopology ?? loadCompleteTopology)(message.identity, message.context_digest,
          { fetch: fetcher, signal: loading.signal, subtle: deps.subtle });
        if (!alive || turn !== epoch) return;
        const module = await (deps.loadView ?? (() => import("./view")))();
        if (!alive || turn !== epoch) return;
        const created = module.createContractView(root, loaded, { onSelect: selected, onFailure: () => refuse("RENDER_FAILED") });
        if (!alive || turn !== epoch) { created.dispose(); return; }
        model = loaded; view = created; phase = "bound"; clearTimers(); bound();
      } catch (error) {
        if (alive && turn === epoch) refuse(error instanceof ContractRefusal ? error.code : "RENDER_FAILED");
      }
      return;
    }
    if (!("identity" in message) || !message.identity || !expected || !sameProjectionIdentity(expected.identity, message.identity)) {
      refuse("IDENTITY_MISMATCH"); return;
    }
    if (message.context_digest !== expected.context_digest) { refuse("CONTEXT_MISMATCH"); return; }
    if (phase !== "bound" || !model || !view) { refuse("INVALID_MESSAGE"); return; }
    if (message.type === "select") {
      if (!hasSelection(model, message.target)) { refuse("INVALID_MESSAGE"); return; }
      view.select(message.target); return; // Programmatic selection never echoes back.
    }
    if (message.type !== "query") { refuse("INVALID_MESSAGE"); return; }
    if (queryIds.has(message.request_id) || queryIds.size >= EMBED_MAX_QUERY_IDS) { refuse("INVALID_MESSAGE", message.request_id); return; }
    queryIds.add(message.request_id); querying?.abort(); const turn = ++queryEpoch;
    view.path(null); // Clear first, even when the following request fails or is superseded.
    if (message.query === null) { send({ ...common, ...expected, type: "query_applied", request_id: message.request_id }); return; }
    querying = new AbortController();
    try {
      const result = await (deps.loadPath ?? loadContractPath)(model, message.query, { fetch: fetcher, signal: querying.signal, subtle: deps.subtle });
      if (!alive || turn !== queryEpoch || !view || !expected) return;
      view.path(result);
      send({ ...common, ...expected, type: "query_applied", request_id: message.request_id });
    } catch (error) {
      if (alive && turn === queryEpoch) refuse(error instanceof ContractRefusal ? error.code : "HTTP_REFUSED", message.request_id);
    }
  }
  function onMessage(event: MessageEvent<unknown>): void {
    if (!alive || event.origin !== mode.origin || event.source !== parent) return;
    // Structured-clone messages have ordinary data fields. Read descriptors so a
    // locally forged MessageEvent cannot make a getter part of admission.
    try {
      if (event.data === null || typeof event.data !== "object") return;
      const descriptors = Object.getOwnPropertyDescriptors(event.data);
      if (own(descriptors, "nonce")?.value !== mode.nonce) return;
      if (own(descriptors, "protocol")?.value !== EMBED_PROTOCOL) {
        refuse("UNSUPPORTED_CONTRACT"); return;
      }
    } catch { return; }
    const message = parseEmbedMessage(event.data);
    if (!message) { refuse("INVALID_MESSAGE"); return; }
    void receive(message).catch(() => refuse("RENDER_FAILED"));
  }
  if (parent === host) { refuse("UNSUPPORTED_CONTRACT"); return dispose; }
  host.addEventListener("message", onMessage); host.addEventListener("pagehide", dispose);
  bindTimer = host.setTimeout(() => refuse("UNSUPPORTED_CONTRACT"), BIND_TIMEOUT_MS);
  ready();
  return dispose;
}
