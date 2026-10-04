import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { api } from "../../api";
import { EMBED_PROTOCOL, PROJECTION_SCHEMA, TOPOLOGY_STYLE_SCHEMA, parseEmbedMessage, projectionContextDigest,
  projectionEmbedUrl, sameProjectionIdentity, sameSelection, type EmbedMessage, type EmbedRefusalCode } from "../../projectionEmbed";
import { hasTarget, type TopologyDocument, type TopologyRows, type TopologyTarget } from "./topologyData";
import type { DesiredPathQuery } from "./TopologyPaths";

const REFUSAL_TEXT: Record<EmbedRefusalCode, string> = {
  WEBGL_UNAVAILABLE: "WebGL is unavailable here. The 2-D map and engine path results remain available.",
  RENDER_FAILED: "The 3-D renderer could not complete. Continue with the 2-D map.",
  RENDER_CAPACITY: "This topology exceeds the 3-D rendering capacity. Continue with the paged 2-D evidence view.",
  UNSUPPORTED_CONTRACT: "This Scope build does not support the current engine projection contract.",
  IDENTITY_MISMATCH: "Scope could not confirm the same stored snapshot. Reload the topology before continuing.",
  CONTEXT_MISMATCH: "Scope could not confirm the same engine and qualification context.",
  INCOMPLETE_PAGES: "Scope could not assemble every required source-bound page.",
  HTTP_REFUSED: "The server refused Scope's current projection request.",
  INVALID_MESSAGE: "The embedded view could not confirm its current session.",
};
const READY_TIMEOUT = 20_000;

function mountNonce(): string {
  const bytes = new Uint8Array(16);
  if (!globalThis.crypto?.getRandomValues) throw new Error("Secure frame coordination is unavailable.");
  globalThis.crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function TopologyScope({ document, rows, selected, desired, onSelect, onClear, onReturnTo2D }: {
  document: TopologyDocument; rows: TopologyRows; selected: TopologyTarget | null; desired: DesiredPathQuery;
  onSelect: (target: TopologyTarget | null) => void; onClear: () => void; onReturnTo2D: () => void;
}) {
  const [attempt, setAttempt] = useState(0);
  const [session, setSession] = useState<{ document: TopologyDocument; nonce: string; href: string; digest: string } | null>(null);
  const [error, setError] = useState("");
  const [bound, setBound] = useState(false);
  const [applied, setApplied] = useState<string | null>(null);
  const iframe = useRef<HTMLIFrameElement>(null);
  const phase = useRef<"preparing" | "ready" | "binding" | "bound" | "failed">("preparing");
  const latest = useRef({ document, rows, selected, desired, onSelect, onClear });
  latest.current = { document, rows, selected, desired, onSelect, onClear };
  const sentQuery = useRef<string | null>(null);
  const sentSelection = useRef<TopologyTarget | null>(null);
  const loaded = useRef(false);
  const activeSession = session?.document === document ? session : null;

  function refuse(message: string) {
    phase.current = "failed"; setBound(false); setApplied(null); setError(message); setSession(null);
    sentQuery.current = null; sentSelection.current = null; latest.current.onClear();
  }
  useEffect(() => {
    let active = true;
    phase.current = "preparing"; loaded.current = false; sentQuery.current = null; sentSelection.current = null;
    setSession(null); setError(""); setBound(false); setApplied(null);
    let nonce: string;
    try { nonce = mountNonce(); }
    catch { refuse("Secure context verification is unavailable. Use the 2-D map."); return; }
    Promise.all([api.scopeView(document.identity.snapshot_id), projectionContextDigest(document.engine, document.limitations)])
      .then(([capability, digest]) => {
        if (!active || latest.current.document !== document) return;
        const current = capability.engine_projection;
        const href = current?.available === true && current.protocol === EMBED_PROTOCOL && current.projection_schema === PROJECTION_SCHEMA &&
          current.style_schema === TOPOLOGY_STYLE_SCHEMA ? projectionEmbedUrl(current.href, document.identity.snapshot_id, nonce, window.location.origin) : null;
        if (!href) {
          refuse(current?.detail || "A current same-hub Scope projection build is unavailable. The 2-D map remains available."); return;
        }
        phase.current = "ready";
        setSession({ document, nonce, href, digest });
      }).catch(() => { if (active && latest.current.document === document) refuse("The current Scope capability or context could not be verified. Use the 2-D map."); });
    return () => { active = false; phase.current = "failed"; };
  }, [document, attempt]);

  useLayoutEffect(() => {
    if (!activeSession) return;
    const mount = activeSession;
    const origin = window.location.origin;
    const timeout = window.setTimeout(() => refuse("Scope did not bind the current source in time. The 2-D map remains available."), READY_TIMEOUT);
    function receive(event: MessageEvent) {
      // Other windows/origins cannot change this session, even with a copied nonce.
      if (event.origin !== origin || event.source !== iframe.current?.contentWindow || !event.source) return;
      if (latest.current.document !== mount.document || phase.current === "failed") return;
      // Stale mounts have no authority here. Read only an own data property; malformed
      // current-nonce messages refuse, while foreign or stale nonces cannot clear this mount.
      let nonce: unknown;
      try {
        const descriptor = event.data && typeof event.data === "object" ? Object.getOwnPropertyDescriptor(event.data, "nonce") : undefined;
        nonce = descriptor && "value" in descriptor ? descriptor.value : undefined;
      } catch { return; }
      if (nonce !== mount.nonce) return;
      const message = parseEmbedMessage(event.data);
      if (!message) { refuse(REFUSAL_TEXT.INVALID_MESSAGE); return; }
      const post = (value: EmbedMessage) => iframe.current?.contentWindow?.postMessage(value, origin);
      if (message.type === "ready") {
        if (message.snapshot_id !== mount.document.identity.snapshot_id) { refuse(REFUSAL_TEXT.IDENTITY_MISMATCH); return; }
        if (phase.current === "bound") { refuse("The embedded document restarted. Start a fresh 3-D session."); return; }
        if (phase.current === "binding") return;
        phase.current = "binding";
        post({ protocol: EMBED_PROTOCOL, type: "init", nonce: mount.nonce, identity: mount.document.identity,
          context_digest: mount.digest, projection_schema: PROJECTION_SCHEMA, style_schema: TOPOLOGY_STYLE_SCHEMA });
        return;
      }
      if (message.type === "refused" && message.identity === null) {
        if (phase.current === "bound") refuse(REFUSAL_TEXT.INVALID_MESSAGE);
        else refuse(REFUSAL_TEXT[message.code]);
        return;
      }
      if (!message.identity || !sameProjectionIdentity(message.identity, mount.document.identity)) { refuse(REFUSAL_TEXT.IDENTITY_MISMATCH); return; }
      if (message.context_digest !== mount.digest) { refuse(REFUSAL_TEXT.CONTEXT_MISMATCH); return; }
      if (message.type === "bound") {
        if (phase.current === "bound") return;
        if (phase.current !== "binding") { refuse(REFUSAL_TEXT.INVALID_MESSAGE); return; }
        window.clearTimeout(timeout); phase.current = "bound"; setBound(true); return;
      }
      if (phase.current !== "bound") { refuse(REFUSAL_TEXT.INVALID_MESSAGE); return; }
      if (message.type === "select") {
        if (message.target && !hasTarget(latest.current.rows, message.target)) { refuse(REFUSAL_TEXT.INVALID_MESSAGE); return; }
        sentSelection.current = message.target; latest.current.onSelect(message.target);
      } else if (message.type === "query_applied") {
        if (message.request_id === latest.current.desired.request_id && message.request_id === sentQuery.current) setApplied(message.request_id);
      } else if (message.type === "refused") {
        if (message.request_id !== null && message.request_id !== latest.current.desired.request_id) return;
        refuse(REFUSAL_TEXT[message.code]);
      } else refuse(REFUSAL_TEXT.INVALID_MESSAGE);
    }
    window.addEventListener("message", receive);
    return () => { window.clearTimeout(timeout); window.removeEventListener("message", receive); };
  }, [activeSession]);

  useEffect(() => {
    if (!activeSession || !bound || phase.current !== "bound" || latest.current.document !== activeSession.document) return;
    const target = iframe.current?.contentWindow;
    if (!target) return;
    const envelope = { protocol: EMBED_PROTOCOL, nonce: activeSession.nonce, identity: document.identity, context_digest: activeSession.digest };
    if (!sameSelection(selected, sentSelection.current)) {
      const message: EmbedMessage = { ...envelope, type: "select", target: selected };
      target.postMessage(message, window.location.origin); sentSelection.current = selected;
    }
    if (sentQuery.current !== desired.request_id) {
      const message: EmbedMessage = { ...envelope, type: "query", request_id: desired.request_id, query: desired.query };
      target.postMessage(message, window.location.origin); sentQuery.current = desired.request_id; setApplied(null);
    }
  }, [activeSession, bound, document, selected, desired]);

  useEffect(() => {
    if (!activeSession || !bound || applied === desired.request_id) return;
    const timeout = window.setTimeout(() => refuse("Scope did not apply the current query in time. Continue with the 2-D view."), 45_000);
    return () => window.clearTimeout(timeout);
  }, [activeSession, bound, applied, desired.request_id]);

  const currentVisible = bound && applied === desired.request_id;
  return <section className="panel topology-scope" aria-label="Embedded Atlas Scope">
    <div className="topology-scope-toolbar"><h2>3-D investigation</h2><button className="btn" onClick={onReturnTo2D}>Return to 2-D</button></div>
    {error ? <><p role="alert" className="projection-disclosure">{error}</p><button className="btn" onClick={() => { onClear(); setAttempt((value) => value + 1); }}>Retry current 3-D capability</button></>
      : <p role="status">{currentVisible ? "Scope is bound to this snapshot and current query." : bound ? "Clearing or updating the current 3-D overlay…" : "Verifying the current same-hub Scope view…"}</p>}
    {activeSession && <iframe key={activeSession.nonce} ref={iframe} src={activeSession.href} title="Atlas Scope engine topology"
      sandbox="allow-scripts allow-same-origin" allowFullScreen style={{ visibility: currentVisible ? "visible" : "hidden" }}
      onLoad={() => { if (loaded.current) refuse("The embedded document changed. Start a fresh 3-D session."); else loaded.current = true; }} />}
    <p className="dim">2-D and the evidence lists stay available below. A connected 3-D session does not certify complete network evidence.</p>
  </section>;
}
