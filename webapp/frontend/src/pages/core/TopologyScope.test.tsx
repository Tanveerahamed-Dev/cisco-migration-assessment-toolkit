import { useState } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import * as protocol from "../../projectionEmbed";
import { topologyFixture } from "../../test/projectionFixtures";
import { TopologyScope } from "./TopologyScope";
import { initialTopologyRows } from "./topologyData";

const DIGEST = `sha256:${"d".repeat(64)}`;
const data = topologyFixture();
const capability = { available: true, status: "ready", href: "/scope/?snapshot=1", detail: "Legacy unchanged",
  engine_projection: { available: true, protocol: protocol.EMBED_PROTOCOL, projection_schema: protocol.PROJECTION_SCHEMA,
    style_schema: protocol.TOPOLOGY_STYLE_SCHEMA, href: "/scope/snapshots/1/?engine_projection=1", detail: "Current synthetic contract build" } };

function emit(frame: HTMLIFrameElement, payload: unknown, origin = window.location.origin, source: MessageEventSource | null = frame.contentWindow) {
  return act(async () => { window.dispatchEvent(new MessageEvent("message", { data: payload, origin, source })); });
}
function envelope(frame: HTMLIFrameElement) {
  return { protocol: protocol.EMBED_PROTOCOL, nonce: new URL(frame.src).searchParams.get(protocol.PROJECTION_NONCE_PARAM)!,
    identity: data.identity, context_digest: DIGEST };
}
async function connect(frame: HTMLIFrameElement) {
  const receiver = frame.contentWindow!;
  const sent = vi.spyOn(receiver, "postMessage").mockImplementation(() => {});
  const { identity: _identity, context_digest: _digest, ...ready } = envelope(frame);
  await emit(frame, { ...ready, type: "ready", snapshot_id: 1, projection_schema: protocol.PROJECTION_SCHEMA, style_schema: protocol.TOPOLOGY_STYLE_SCHEMA });
  expect(frame.contentWindow).toBe(receiver);
  expect(sent).toHaveBeenCalledWith({ ...envelope(frame), type: "init", projection_schema: protocol.PROJECTION_SCHEMA,
    style_schema: protocol.TOPOLOGY_STYLE_SCHEMA }, window.location.origin);
  await emit(frame, { ...envelope(frame), type: "bound" });
  await waitFor(() => expect(sent.mock.calls.some(([message]) => (message as protocol.EmbedMessage).type === "query")).toBe(true));
  await emit(frame, { ...envelope(frame), type: "query_applied", request_id: "initial-clear" });
  expect(frame).toHaveStyle({ visibility: "visible" });
  return sent;
}
function setup() {
  vi.spyOn(api, "scopeView").mockResolvedValue(capability);
  vi.spyOn(protocol, "projectionContextDigest").mockResolvedValue(DIGEST);
  const select = vi.fn(), clear = vi.fn(), back = vi.fn();
  function Harness() {
    const [desired, setDesired] = useState<{ request_id: string; query: { src_ip: string; dst_ip: string } | null }>({ request_id: "initial-clear", query: null });
    return <><button onClick={() => setDesired({ request_id: "new-query", query: { src_ip: "192.0.2.10", dst_ip: "198.51.100.10" } })}>Submit another query</button>
      <TopologyScope document={data as never} rows={initialTopologyRows(data as never)} selected={null} desired={desired}
        onSelect={select} onClear={clear} onReturnTo2D={back} /></>;
  }
  render(<Harness />);
  return { select, clear, back };
}

describe("Scope parent custody", () => {
  afterEach(() => vi.restoreAllMocks());
  it("uses a fresh closed same-hub capability and explicit identity/context handshake", async () => {
    setup();
    const frame = await screen.findByTitle<HTMLIFrameElement>("Atlas Scope engine topology");
    expect(protocol.isEmbedNonce(envelope(frame).nonce)).toBe(true);
    expect(new URL(frame.src).pathname).toBe("/scope/snapshots/1/");
    await connect(frame);
    expect(api.scopeView).toHaveBeenCalledWith(1);
  });
  it("ignores foreign origin/window and stale nonces, while accepting only a known current row", async () => {
    const { select, clear } = setup();
    const frame = await screen.findByTitle<HTMLIFrameElement>("Atlas Scope engine topology");
    await connect(frame);
    const target = { list: "nodes", row: { index: 0, pointer: "/cable_map/nodes/0" } };
    const message = { ...envelope(frame), type: "select", target };
    await emit(frame, message, "https://foreign.invalid");
    await emit(frame, message, window.location.origin, window);
    await emit(frame, { ...message, nonce: "0".repeat(32) });
    expect(select).not.toHaveBeenCalled(); expect(clear).not.toHaveBeenCalled(); expect(frame).toHaveStyle({ visibility: "visible" });
    await emit(frame, message); expect(select).toHaveBeenCalledWith(target);
  });
  it.each(["identity", "context", "version", "unknown-row"])("refuses a current-nonce %s mismatch and removes prior success", async (kind) => {
    const { clear } = setup();
    const frame = await screen.findByTitle<HTMLIFrameElement>("Atlas Scope engine topology");
    await connect(frame);
    const base = envelope(frame);
    const message = kind === "version" ? { ...base, protocol: "future", type: "bound" }
      : { ...base, type: "select", target: { list: "nodes", row: { index: kind === "unknown-row" ? 91 : 0, pointer: "/cable_map/nodes/0" } },
        ...(kind === "identity" ? { identity: { ...data.identity, bytes: 999 } } : {}),
        ...(kind === "context" ? { context_digest: `sha256:${"e".repeat(64)}` } : {}) };
    await emit(frame, message);
    expect(screen.queryByTitle("Atlas Scope engine topology")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument(); expect(clear).toHaveBeenCalled();
  });
  it("hides old overlays until the current query ACK and ignores a late old ACK", async () => {
    setup(); const frame = await screen.findByTitle<HTMLIFrameElement>("Atlas Scope engine topology");
    const sent = await connect(frame);
    fireEvent.click(screen.getByRole("button", { name: "Submit another query" }));
    expect(frame).toHaveStyle({ visibility: "hidden" });
    await waitFor(() => expect(sent.mock.calls.some(([value]) => (value as protocol.EmbedMessage).type === "query" && "request_id" in value && value.request_id === "new-query")).toBe(true));
    await emit(frame, { ...envelope(frame), type: "query_applied", request_id: "initial-clear" });
    expect(frame).toHaveStyle({ visibility: "hidden" });
    await emit(frame, { ...envelope(frame), type: "query_applied", request_id: "new-query" });
    expect(frame).toHaveStyle({ visibility: "visible" });
  });
  it("offers a usable2D fallback when WebGL is unavailable", async () => {
    const { clear } = setup(); const frame = await screen.findByTitle<HTMLIFrameElement>("Atlas Scope engine topology");
    await emit(frame, { protocol: protocol.EMBED_PROTOCOL, nonce: envelope(frame).nonce, type: "refused", identity: null,
      context_digest: null, code: "WEBGL_UNAVAILABLE", request_id: null });
    expect(screen.getByRole("alert")).toHaveTextContent("WebGL is unavailable");
    expect(screen.queryByTitle("Atlas Scope engine topology")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Return to 2-D" })).toBeEnabled(); expect(clear).toHaveBeenCalled();
  });
  it("refuses a stale/foreign capability instead of falling through to the legacy hub", async () => {
    setup(); vi.mocked(api.scopeView).mockResolvedValue({ ...capability, engine_projection: { ...capability.engine_projection,
      href: "https://foreign.invalid/scope/snapshots/1/?engine_projection=1" } });
    // Retry rechecks capability with a new mount, never following the legacy href.
    const frame = await screen.findByTitle<HTMLIFrameElement>("Atlas Scope engine topology");
    await emit(frame, { protocol: protocol.EMBED_PROTOCOL, nonce: envelope(frame).nonce, type: "refused", identity: null,
      context_digest: null, code: "UNSUPPORTED_CONTRACT", request_id: null });
    fireEvent.click(screen.getByRole("button", { name: "Retry current 3-D capability" }));
    await waitFor(() => expect(api.scopeView).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByTitle("Atlas Scope engine topology")).not.toBeInTheDocument();
  });
  it("keeps a2D fallback when secure context comparison is unavailable", async () => {
    vi.spyOn(api, "scopeView").mockResolvedValue(capability);
    vi.spyOn(protocol, "projectionContextDigest").mockRejectedValue(new Error("No SubtleCrypto"));
    render(<TopologyScope document={data as never} rows={initialTopologyRows(data as never)} selected={null}
      desired={{ request_id: "clear", query: null }} onSelect={vi.fn()} onClear={vi.fn()} onReturnTo2D={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be verified");
    expect(screen.queryByTitle("Atlas Scope engine topology")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Return to 2-D" })).toBeEnabled();
  });
});
