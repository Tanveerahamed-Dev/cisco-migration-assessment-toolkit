import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import CoreSnapshot from "../pages/CoreSnapshot";
import SnapshotPage from "../pages/Snapshot";
import { TopologyScope } from "../pages/core/TopologyScope";
import { initialTopologyRows } from "../pages/core/topologyData";
import * as protocol from "../projectionEmbed";
import { overviewFixture, topologyFixture } from "../test/projectionFixtures";
import { SCOPE_PREVIEW_DETAIL, ScopePreviewTag } from "./ScopePreview";

// Atlas Scope ships as a LABELLED PREVIEW (owner decision, 2026-10-09). Every AssessHub entry to Scope carries
// a visible "Preview" qualifier directly beside it — the core snapshot header link, the Tools page link and the
// embedded 3-D view's heading — and an entry that is not offered carries none. This file fails when the
// qualifier is removed from any of them, moved away from its entry, hidden, or loses its words.

const AVAILABLE = { available: true, status: "ready", href: "/scope/snapshots/1/", detail: "ready" };
const UNAVAILABLE = { available: false, status: "not_built", href: null, detail: "Atlas Scope is not built in this installation." };

/** Why `el` would not be seen, from the DOM alone: it or an ancestor hidden, aria-hidden, sr-only or styled away. */
function hiddenBy(el: HTMLElement): string[] {
  const out: string[] = [];
  for (let n: HTMLElement | null = el; n !== null; n = n.parentElement) {
    const what = `${n.tagName.toLowerCase()}${n.className ? `.${String(n.className).trim().split(/\s+/).join(".")}` : ""}`;
    if (n.hidden) out.push(`${what}: the hidden attribute`);
    if (n.getAttribute("aria-hidden") === "true") out.push(`${what}: aria-hidden`);
    if (n.classList.contains("sr-only")) out.push(`${what}: sr-only`);
    if (n.style.display === "none" || n.style.visibility === "hidden" || n.style.opacity === "0") out.push(`${what}: an inline style hides it`);
  }
  return out;
}

/** The words a sighted reader sees: the qualifier's text without its screen-reader-only part. */
function seenText(el: HTMLElement): string {
  const copy = el.cloneNode(true) as HTMLElement;
  for (const hidden of [...copy.querySelectorAll(".sr-only")]) hidden.remove();
  return (copy.textContent ?? "").replace(/\s+/g, " ").trim();
}

/** The element right after `entry`, in the same wrapper, is the shown, worded preview qualifier. */
function expectQualified(entry: HTMLElement, where: string) {
  const tag = entry.nextElementSibling as HTMLElement | null;
  expect(tag, `${where}: nothing is beside the entry`).not.toBeNull();
  expect(tag!.hasAttribute("data-scope-preview"), `${where}: the element beside the entry is not the preview qualifier`).toBe(true);
  expect(tag!.parentElement, `${where}: the qualifier is not in the entry's own wrapper`).toBe(entry.parentElement);
  expect(hiddenBy(tag!), `${where}: the qualifier is hidden`).toEqual([]);
  expect(seenText(tag!), `${where}: the visible word`).toBe("Preview");
  expect(tag!.getAttribute("title"), `${where}: the tooltip`).toBe(SCOPE_PREVIEW_DETAIL);
  expect(tag!.textContent, `${where}: the screen-reader sentence`).toContain("acceptance is not complete");
  expect(document.querySelectorAll("[data-scope-preview]"), `${where}: one qualifier per entry`).toHaveLength(1);
  // D6: the entry names the qualifier as its accessible description, so a screen reader hears "Preview" and its
  // reason with the entry itself, not only by reading on to the next element.
  const describedBy = (entry.getAttribute("aria-describedby") ?? "").split(/\s+/).filter(Boolean);
  expect(describedBy.length, `${where}: the entry carries no aria-describedby`).toBeGreaterThan(0);
  expect(document.getElementById(describedBy[0]), `${where}: aria-describedby does not name the qualifier first`).toBe(tag);
  expect(entry, `${where}: the accessible description`).toHaveAccessibleDescription(/^Preview.*acceptance is not complete/);
}

describe("the Atlas Scope preview qualifier", () => {
  afterEach(() => vi.restoreAllMocks());

  it("a description that names no qualifier fails the check (negative control for the aria-describedby tie)", () => {
    render(<div><a href="/scope/snapshots/1/" aria-describedby="nothing-here">Open in Atlas Scope</a><ScopePreviewTag /></div>);
    const link = screen.getByRole("link", { name: "Open in Atlas Scope" });
    expect(() => expectQualified(link, "untied link")).toThrow();
  });

  it("is a visible word with its reason, and no control", () => {
    render(<ScopePreviewTag />);
    const tag = document.querySelector<HTMLElement>("[data-scope-preview]");
    expect(tag).not.toBeNull();
    expect(seenText(tag!)).toBe("Preview");
    expect(hiddenBy(tag!)).toEqual([]);
    expect(SCOPE_PREVIEW_DETAIL).toContain("acceptance is not complete");
    expect(SCOPE_PREVIEW_DETAIL).toContain("atlas-scope/docs/acceptance-report.md");
    expect(tag!.querySelector("a, button, input, [tabindex]")).toBeNull();
  });

  describe("beside the core snapshot header link", () => {
    const show = () => render(
      <MemoryRouter initialEntries={["/snapshots/1"]}><Routes><Route path="/snapshots/:id" element={<CoreSnapshot />} /></Routes></MemoryRouter>,
    );

    it("when the scope view is offered", async () => {
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input) =>
        new Response(JSON.stringify(String(input).endsWith("/scope-view") ? AVAILABLE : overviewFixture())));
      show();
      const link = await screen.findByRole("link", { name: /Open in Atlas Scope/ });
      expect(link).toHaveAttribute("href", "/scope/snapshots/1/");
      expectQualified(link, "core snapshot header");
    });

    it("and nowhere when it is not", async () => {
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input) =>
        new Response(JSON.stringify(String(input).endsWith("/scope-view") ? UNAVAILABLE : overviewFixture())));
      show();
      await screen.findByText("Synthetic fleet needs review");
      await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith("/api/snapshots/1/scope-view", { cache: "no-store" }));
      expect(screen.queryByRole("link", { name: /Open in Atlas Scope/ })).toBeNull();
      expect(document.querySelector("[data-scope-preview]")).toBeNull();
    });
  });

  describe("beside the Tools page link", () => {
    const meta = {
      campaign_id: 1, label: "Demo Fleet", n_devices: 50, script_version: "V3.23.0", uploaded_at: "2026-06-13T06:32:00Z",
      summary: {
        avg_health: 72, n_critical: 3, n_switches: 40, version: "V3.23.0",
        punchlist: { crit_high: 5, total: 20, by_severity: { High: 3 }, by_category: { Security: 4 } },
        readiness: { READY: 30, CAUTION: 8, "NOT READY": 2 }, bands: { Good: 25, Critical: 3 },
        sections: [{ key: "overview", label: "Overview" }, { key: "punchlist", label: "Punch list" }],
        lifecycle: { past_eos: 2 },
      },
    };
    function mockScope(view: unknown) {
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (/\/api\/snapshots\/\d+\/scope-view$/.test(url)) return new Response(JSON.stringify(view), { status: 200 });
        if (/\/api\/snapshots\/\d+\/graph\b/.test(url)) return new Response(JSON.stringify({ nodes: [], edges: [] }), { status: 200 });
        if (/\/api\/snapshots\/\d+(\?.*)?$/.test(url)) return new Response(JSON.stringify(meta), { status: 200 });
        return new Response(JSON.stringify({ detail: "not mocked" }), { status: 404 });
      });
    }
    const show = () => render(
      <MemoryRouter initialEntries={["/snapshots/1"]}><Routes><Route path="/snapshots/:id" element={<SnapshotPage />} /></Routes></MemoryRouter>,
    );

    it("when the scope view is offered", async () => {
      mockScope(AVAILABLE);
      show();
      const link = await screen.findByRole("link", { name: /Open in Atlas Scope/ });
      expect(link).toHaveAttribute("href", "/scope/snapshots/1/");
      expectQualified(link, "Tools page header");
    });

    it("is described by the qualifier AND by the server's detail, which aria-describedby would otherwise hide", async () => {
      const detail = "Atlas Scope hub build is current for this snapshot.";
      mockScope({ ...AVAILABLE, detail });
      show();
      const link = await screen.findByRole("link", { name: /Open in Atlas Scope/ });
      expectQualified(link, "Tools page header with a detail");
      expect(link).toHaveAttribute("title", detail);
      const ids = (link.getAttribute("aria-describedby") ?? "").split(/\s+/);
      expect(ids).toHaveLength(2);
      const detailNode = document.getElementById(ids[1])!;
      expect(detailNode.textContent).toBe(detail);
      expect(detailNode.classList.contains("sr-only")).toBe(true);
      expect(link).toHaveAccessibleDescription(/acceptance is not complete.*Atlas Scope hub build is current for this snapshot\.$/);
    });

    it("and nowhere when it is not", async () => {
      mockScope(UNAVAILABLE);
      show();
      await screen.findByRole("heading", { name: "Demo Fleet" });
      await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith("/api/snapshots/1/scope-view", { cache: "no-store" }));
      expect(screen.queryByRole("link", { name: /Atlas Scope/ })).toBeNull();
      expect(document.querySelector("[data-scope-preview]")).toBeNull();
    });
  });

  it("beside the embedded 3-D view's heading (Scope's contract mode has no status bar of its own)", () => {
    vi.spyOn(api, "scopeView").mockResolvedValue({ ...AVAILABLE, href: "/scope/?snapshot=1",
      engine_projection: { available: true, protocol: protocol.EMBED_PROTOCOL, projection_schema: protocol.PROJECTION_SCHEMA,
        style_schema: protocol.TOPOLOGY_STYLE_SCHEMA, href: "/scope/snapshots/1/?engine_projection=1", detail: "Current synthetic contract build" } });
    vi.spyOn(protocol, "projectionContextDigest").mockResolvedValue(`sha256:${"d".repeat(64)}`);
    const data = topologyFixture();
    render(<TopologyScope document={data as never} rows={initialTopologyRows(data as never)} selected={null}
      desired={{ request_id: "initial-clear", query: null }} onSelect={vi.fn()} onClear={vi.fn()} onReturnTo2D={vi.fn()} />);
    const heading = screen.getByRole("heading", { name: "3-D investigation" });
    expectQualified(heading, "embedded 3-D view");
  });
});
