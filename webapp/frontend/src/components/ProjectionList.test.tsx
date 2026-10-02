import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProjectionList } from "./ProjectionList";
import type { Page, Projection } from "../projection";
const document = { schema: "ui_projection_transport/1", projection_schema: "ui_projection/1", view: "findings",
  identity: { snapshot_id: 1, sha256: `sha256:${"a".repeat(64)}`, bytes: 20, digest_form: "assesshub-store-blob" } } as Projection;
const initial = { pointer: "/rows", source_list: { state: "analysis_unavailable", reason: "Some rows remain usable", subject: "/punchlist", refs: [], basis: "engine" },
  page: { offset: 0, limit: 1, returned: 1, total: 3, has_more: true, items: [{ index: 8, pointer: "/punchlist/8" }] } } as Page;
describe("Projection paging", () => {
  afterEach(() => vi.restoreAllMocks());
  it("renders usable items from a withheld list without inventing zero", () => {
    render(<ProjectionList title="Findings" document={document} initial={initial} renderRow={() => <p>Partial row retained</p>} />);
    expect(screen.getByText("Analysis unavailable")).toBeInTheDocument();
    expect(screen.getByText("Some rows remain usable")).toBeInTheDocument();
    expect(screen.getByText("Partial row retained")).toBeInTheDocument();
  });
  it("retries the requested failed page, not the currently displayed one", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("", { status: 503 }));
    render(<ProjectionList title="Findings" document={document} initial={initial} renderRow={() => <p>Existing row</p>} />);
    fireEvent.click(screen.getByRole("button", { name: "Next Findings page" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Retry Findings page" }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    expect(fetcher.mock.calls.map(([url]) => new URL(String(url), "http://localhost").searchParams.get("offset"))).toEqual(["1", "1"]);
  });
  it("joins reordered rows by both original index and pointer", () => {
    const fetcher = vi.spyOn(globalThis, "fetch");
    const source = { ...initial, page: { ...initial.page, limit: 25, returned: 2, total: 2, has_more: false,
      items: [{ index: 93, pointer: "/punchlist/93" }, { index: 7, pointer: "/punchlist/7" }] } } as Page;
    render(<ProjectionList title="Findings" document={document} initial={source} reference={{ index: 7, pointer: "/punchlist/7" }}
      renderRow={(row) => <p>{typeof row === "object" && "index" in row ? `Source ${row.index}` : "row"}</p>} />);
    expect(screen.getByLabelText("Referenced record")).toHaveTextContent("Source 7");
    expect(screen.getByLabelText("Referenced record")).not.toHaveTextContent("Source 93");
    fireEvent.click(screen.getByRole("button", { name: "Jump to referenced record" }));
    expect(screen.getByLabelText("Referenced record")).toHaveFocus();
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("never joins a matching index with a different pointer", () => {
    const source = { ...initial, page: { ...initial.page, limit: 25, total: 1, has_more: false } };
    render(<ProjectionList title="Findings" document={document} initial={source} reference={{ index: 8, pointer: "/other/8" }} renderRow={() => <p>Different row</p>} />);
    expect(screen.queryByLabelText("Referenced record")).not.toBeInTheDocument();
    expect(screen.getByText(/Reference only/)).toBeInTheDocument();
  });
  it("uses a bounded page hint for a sparse source index and discloses a missing exact record", async () => {
    const next = { ...initial, page: { ...initial.page, offset: 2, has_more: false, items: [{ index: 500, pointer: "/punchlist/500" }] } };
    const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ ...document, list: next })));
    render(<ProjectionList title="Findings" document={document} initial={initial} reference={{ index: 93, pointer: "/punchlist/93" }} renderRow={() => <p>Row</p>} />);
    await screen.findByText(/Reference only/);
    expect(screen.queryByLabelText("Referenced record")).not.toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(new URL(String(fetcher.mock.calls[0][0]), "http://localhost").searchParams.get("offset")).toBe("2");
  });
});
