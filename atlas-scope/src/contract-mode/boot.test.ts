import { afterEach, describe, expect, it, vi } from "vitest";
import { bootContractMode } from "./boot";
import { ContractRefusal } from "./errors";
import { completeFixture, typedPath } from "../test-support/projection-contract-fixtures";
import { EMBED_PROTOCOL, PROJECTION_SCHEMA, TOPOLOGY_STYLE_SCHEMA, type EmbedMessage } from "../../../webapp/frontend/src/projectionEmbed";
import type { CompleteTopology, PathDocument } from "./types";
import type { ContractView, ViewOptions } from "./view";

class Host extends EventTarget {
  parent = window;
  fetch = vi.fn<typeof fetch>();
  timers = new Map<number, { callback: () => void; delay: number }>();
  serial = 0;
  setTimeout(callback: () => void, delay: number): number { const id = ++this.serial; this.timers.set(id, { callback, delay }); return id; }
  clearTimeout(id: number): void { this.timers.delete(id); }
}
const origin = window.location.origin;
const nonce = "7".repeat(32);
const mode = { selected: true, valid: true, snapshotId: 7, nonce, origin } as const;
const flush = async (): Promise<void> => { for (let step = 0; step < 10; step++) await Promise.resolve(); };
function pending<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((done) => { resolve = done; }); return { promise, resolve }; }
const disposers: (() => void)[] = [];
afterEach(() => { for (const dispose of disposers.splice(0)) dispose(); vi.restoreAllMocks(); document.body.replaceChildren(); });

async function harness(options: { topology?: ReturnType<typeof pending<CompleteTopology>>; path?: (typeof loadPath) } = {}) {
  const model = await completeFixture(), host = new Host();
  const root = document.createElement("div"); document.body.append(root);
  const post = vi.spyOn(window, "postMessage").mockImplementation(() => {});
  const view: ContractView = { select: vi.fn(), path: vi.fn(), dispose: vi.fn() };
  const factory = vi.fn((_root: HTMLElement, _model: CompleteTopology, _options: ViewOptions) => view);
  const topology = vi.fn(async () => options.topology ? options.topology.promise : model);
  const path = options.path ?? loadPath;
  const dispose = bootContractMode(root, mode, { host: host as unknown as Window, fetch: host.fetch,
    loadTopology: topology, loadPath: path, loadView: async () => ({ createContractView: factory }) });
  disposers.push(dispose);
  const command = { protocol: EMBED_PROTOCOL, nonce, identity: model.document.identity, context_digest: model.contextDigest };
  const init = { ...command, type: "init", projection_schema: PROJECTION_SCHEMA, style_schema: TOPOLOGY_STYLE_SCHEMA };
  const emit = (data: unknown, eventOrigin = origin, source: Window = window): void => {
    host.dispatchEvent(new MessageEvent("message", { data, origin: eventOrigin, source }));
  };
  return { model, host, root, post, view, factory, topology, dispose, command, init, emit };
}
const loadPath = vi.fn(async () => typedPath());

describe("Scope frame lifecycle and context admission", () => {
  it("announces readiness without fetching and binds only after complete independent loading", async () => {
    const slow = pending<CompleteTopology>(), h = await harness({ topology: slow });
    expect(h.post).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ type: "ready", snapshot_id: 7, nonce }), origin);
    expect(h.topology).not.toHaveBeenCalled(); expect(h.host.fetch).not.toHaveBeenCalled();
    h.emit(h.init); await flush();
    expect(h.factory).not.toHaveBeenCalled();
    slow.resolve(h.model); await flush();
    expect(h.factory).toHaveBeenCalledTimes(1);
    expect(h.post).toHaveBeenLastCalledWith({ ...h.command, type: "bound" }, origin);
    h.emit(h.init); await flush();
    expect(h.factory).toHaveBeenCalledTimes(1); expect(h.topology).toHaveBeenCalledTimes(1);
  });

  it("ignores foreign origin/window and old nonce without disturbing the bound model", async () => {
    const h = await harness(); h.emit(h.init); await flush(); h.post.mockClear();
    const sibling = document.createElement("iframe"); document.body.append(sibling);
    h.emit({ ...h.command, type: "select", target: null }, "https://elsewhere.invalid");
    h.emit({ ...h.command, type: "select", target: null }, origin, sibling.contentWindow!);
    h.emit({ ...h.command, nonce: "8".repeat(32), type: "select", target: null });
    await flush();
    expect(h.view.select).not.toHaveBeenCalled(); expect(h.view.dispose).not.toHaveBeenCalled(); expect(h.post).not.toHaveBeenCalled();
  });

  it.each(["nonce", "protocol"] as const)("does not execute a forged %s accessor during admission", async (field) => {
    const h = await harness(); h.emit(h.init); await flush(); h.post.mockClear();
    const getter = vi.fn(() => { throw new Error("A message getter must never execute"); });
    const message = { ...h.command, type: "select", target: null };
    Object.defineProperty(message, field, { enumerable: true, get: getter });
    h.emit(message); await flush();
    expect(getter).not.toHaveBeenCalled(); expect(h.view.select).not.toHaveBeenCalled();
    if (field === "nonce") {
      expect(h.view.dispose).not.toHaveBeenCalled(); expect(h.post).not.toHaveBeenCalled();
    } else {
      expect(h.view.dispose).toHaveBeenCalledTimes(1);
      expect(h.post).toHaveBeenLastCalledWith(expect.objectContaining({ type: "refused", code: "UNSUPPORTED_CONTRACT" }), origin);
    }
  });

  it("ignores a forged inherited nonce and a proxy whose descriptors cannot be inspected", async () => {
    const h = await harness(); h.emit(h.init); await flush(); h.post.mockClear();
    const inherited = Object.assign(Object.create({ nonce }), { ...h.command, type: "select", target: null });
    delete inherited.nonce;
    h.emit(inherited);
    const trap = vi.fn(() => { throw new Error("Unavailable descriptor enumeration"); });
    h.emit(new Proxy({ ...h.command, type: "select", target: null }, { ownKeys: trap }));
    await flush();
    expect(trap).toHaveBeenCalledTimes(1); expect(h.view.select).not.toHaveBeenCalled();
    expect(h.view.dispose).not.toHaveBeenCalled(); expect(h.post).not.toHaveBeenCalled();
  });

  it("refuses active identity/context drift and unknown selected rows", async () => {
    for (const kind of ["identity", "context", "row", "version"] as const) {
      const h = await harness(); h.emit(h.init); await flush(); h.post.mockClear();
      const valid = { ...h.command, type: "select", target: { list: "nodes", row: { index: 0, pointer: "/cable_map/nodes/0" } } };
      if (kind === "identity") h.emit({ ...valid, identity: { ...h.command.identity, bytes: 999 } });
      if (kind === "context") h.emit({ ...valid, context_digest: `sha256:${"9".repeat(64)}` });
      if (kind === "row") h.emit({ ...valid, target: { list: "nodes", row: { index: 99, pointer: "/missing" } } });
      if (kind === "version") h.emit({ ...valid, protocol: "atlas.ui_projection_embed/2" });
      await flush();
      expect(h.view.dispose).toHaveBeenCalledTimes(1);
      expect(h.post).toHaveBeenCalledWith(expect.objectContaining({ type: "refused", identity: h.command.identity, context_digest: h.command.context_digest }), origin);
      expect(h.root.textContent).toContain("2D Topology & Paths"); h.dispose(); h.post.mockRestore();
    }
  });

  it("clears before querying, rejects stale results and acknowledges a clear only after rendering", async () => {
    const first = pending<PathDocument>(), second = pending<PathDocument>();
    const path = vi.fn<typeof loadPath>().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const h = await harness({ path }); h.emit(h.init); await flush(); h.post.mockClear();
    h.emit({ ...h.command, type: "query", request_id: "q1", query: { src_ip: "192.0.2.10", dst_ip: "198.51.100.10" } });
    await flush(); expect(h.view.path).toHaveBeenLastCalledWith(null);
    h.emit({ ...h.command, type: "query", request_id: "q2", query: { src_ip: "192.0.2.10", dst_ip: "198.51.100.11" } }); await flush();
    first.resolve(typedPath()); await flush();
    expect(h.post).not.toHaveBeenCalledWith(expect.objectContaining({ type: "query_applied", request_id: "q1" }), origin);
    second.resolve(typedPath()); await flush();
    expect(h.view.path).toHaveBeenLastCalledWith(expect.objectContaining({ view: "path" }));
    expect(h.post).toHaveBeenLastCalledWith({ ...h.command, type: "query_applied", request_id: "q2" }, origin);
    h.emit({ ...h.command, type: "query", request_id: "q3", query: null }); await flush();
    expect(h.view.path).toHaveBeenLastCalledWith(null);
    expect(h.post).toHaveBeenLastCalledWith({ ...h.command, type: "query_applied", request_id: "q3" }, origin);
    expect(path).toHaveBeenCalledTimes(2);
    h.emit({ ...h.command, type: "query", request_id: "q1", query: null }); await flush();
    expect(h.post).toHaveBeenLastCalledWith(expect.objectContaining({ type: "refused", code: "INVALID_MESSAGE", request_id: "q1" }), origin);
  });

  it("does not mount after teardown and removes timers/message listeners", async () => {
    const slow = pending<CompleteTopology>(), h = await harness({ topology: slow });
    h.emit(h.init); await flush(); h.dispose(); h.post.mockClear();
    slow.resolve(h.model); await flush(); h.emit(h.init); await flush();
    expect(h.factory).not.toHaveBeenCalled(); expect(h.post).not.toHaveBeenCalled(); expect(h.host.timers.size).toBe(0);
  });

  it("reports WebGL failure without binding or leaking received error details", async () => {
    const h = await harness(); h.factory.mockImplementation(() => { throw new ContractRefusal("WEBGL_UNAVAILABLE"); });
    h.emit(h.init); await flush();
    const messages = h.post.mock.calls.map(([message]) => message as EmbedMessage);
    expect(messages.some((message) => message.type === "bound")).toBe(false);
    expect(messages.at(-1)).toEqual({ protocol: EMBED_PROTOCOL, nonce, type: "refused", identity: null, context_digest: null, code: "WEBGL_UNAVAILABLE", request_id: null });
    expect(h.host.timers.size).toBe(0);
  });
});
