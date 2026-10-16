import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EvidenceProvider, FactView, ListState } from "./NativeEvidence";
import type { Fact, Identity, Limitation, SourceList } from "../../projection";

const identity: Identity = { snapshot_id: 1, sha256: `sha256:${"a".repeat(64)}`, bytes: 20, digest_form: "assesshub-store-blob" };
const base = { subject: "/a~1b/0", refs: [{ pointer: "/witness/4", role: "witness" as const }], basis: "owner.rule" };
const limitations: Limitation[] = [{ id: "health_scored_without_security", owner: "engine", text: "Security input is absent.", applies_to: ["health"] }];
function show(fact: Fact) {
  return render(<EvidenceProvider identity={identity} limitations={limitations}><FactView label="Health" fact={fact} /></EvidenceProvider>);
}
describe("Projection fact rendering", () => {
  it("preserves a published zero as zero", () => {
    show({ ...base, state: "published", value: 0 });
    expect(screen.getByText("0")).toBeInTheDocument();
    expect(screen.getByText("0").closest(".projection-fact")).toHaveAttribute("data-evidence-state", "published");
    expect(screen.queryByText("Not collected")).not.toBeInTheDocument();
    expect(screen.queryByText("Published")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Info for Health" }));
    expect(within(screen.getByRole("dialog")).getByText("Published")).toBeInTheDocument();
    expect(within(screen.getByRole("dialog")).getByText("0")).toBeInTheDocument();
  });
  it.each([
    ["collected_but_empty", "Collected, empty"], ["not_collected", "Not collected"],
    ["analysis_unavailable", "Analysis unavailable"], ["not_assessed", "Not assessed"], ["unverified", "Unverified"],
  ] as const)("keeps %s distinct with the owner reason", (state, label) => {
    show({ ...base, state, value: null, reason: "Exact owner reason" });
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByText("Exact owner reason")).toBeInTheDocument();
    expect(screen.getByText("Exact owner reason").closest(".projection-fact")).toHaveAttribute("data-evidence-state", state);
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });
  it("opens evidence with exact pointers, source identity and caveats, traps focus and returns it", () => {
    show({ ...base, state: "published", value: 87, caveats: ["health_scored_without_security"] });
    const button = screen.getByRole("button", { name: "Info for Health" });
    button.focus();
    fireEvent.click(button);
    const dialog = screen.getByRole("dialog", { name: "Evidence: Health" });
    expect(dialog).toHaveTextContent("/a~1b/0");
    expect(dialog).toHaveTextContent("/witness/4");
    expect(dialog).toHaveTextContent(identity.sha256);
    expect(dialog).toHaveTextContent("owner.rule");
    expect(dialog).toHaveTextContent("Snapshot 1 · 20 bytes");
    expect(dialog).toHaveTextContent(identity.digest_form);
    expect(dialog).toHaveTextContent("Security input is absent.");
    const close = screen.getByRole("button", { name: "Close evidence" });
    expect(close).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
    expect(close).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(button).toHaveFocus();
  });
  it("renders source text as data and makes every caveat available through one Info control", () => {
    const { container } = show({ ...base, state: "published", value: "<img src=x onerror=alert(1)>", caveats: ["health_scored_without_security"] });
    expect(container.querySelector("img")).toBeNull();
    const info = screen.getByRole("button", { name: "Info for Health" });
    expect(info).toHaveAttribute("aria-haspopup", "dialog");
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Qualifications for Health" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Evidence for Health" })).not.toBeInTheDocument();
    fireEvent.click(info);
    expect(screen.getByRole("dialog")).toHaveTextContent("Security input is absent.");
    expect(screen.getByRole("dialog")).toHaveTextContent("health_scored_without_security");
    expect(screen.getByRole("dialog")).toHaveTextContent("Owner: engine");
    expect(screen.getByRole("dialog")).toHaveTextContent("Applies to: health");
    expect(screen.getByRole("dialog")).toHaveTextContent("<img src=x onerror=alert(1)>");
    expect(container.querySelector("img")).toBeNull();
  });
  it.each([
    { ...identity, sha256: `sha256:${"b".repeat(64)}` },
    { ...identity, snapshot_id: 2 },
    { ...identity, bytes: 21 },
  ])("never presents an old selected fact under replacement source identity %j", (replacement) => {
    const tree = (source: Identity) => <EvidenceProvider identity={source} limitations={limitations}>
      <FactView label="Health" fact={{ ...base, state: "published", value: 87 }} /></EvidenceProvider>;
    const view = render(tree(identity));
    fireEvent.click(screen.getByRole("button", { name: "Info for Health" }));
    view.rerender(tree(replacement));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
  it("keeps a published lower bound and its exact reason immediate while preserving engine metadata in Info", () => {
    const reason = "Synthetic owner marks this count as a minimum.";
    render(<EvidenceProvider identity={identity} limitations={limitations}>
      <FactView label="Stranded endpoints" fact={{ ...base, state: "published", value: 5,
        engine_state: "unverified", engine_state_owner: "ssot.abstention_reason" }} lowerBound={reason} />
    </EvidenceProvider>);
    expect(screen.getByText("≥ 5", { exact: true })).toBeInTheDocument();
    expect(screen.getByText(`At least 5: a lower bound, not an exact measurement. Why: ${reason}`)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Info for Stranded endpoints" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("unverified · ssot.abstention_reason");
    expect(screen.getByRole("dialog")).toHaveTextContent("/witness/4");
  });
  it.each([
    ["published", "Published"], ["collected_but_empty", "Collected, empty"], ["not_collected", "Not collected"],
    ["analysis_unavailable", "Analysis unavailable"], ["not_assessed", "Not assessed"], ["unverified", "Unverified"],
  ] as const)("keeps a %s list's own state, reason and caveats through its single Info control", (state, label) => {
    const source: SourceList = state === "published"
      ? { ...base, state, caveats: [limitations[0].id] }
      : { ...base, state, reason: "Exact list owner reason", caveats: [limitations[0].id] };
    render(<EvidenceProvider identity={identity} limitations={limitations}><ListState label="Endpoints" source={source} /></EvidenceProvider>);
    expect(screen.getAllByRole("button")).toHaveLength(1);
    if (state === "published") expect(screen.queryByText(label)).not.toBeInTheDocument();
    else {
      expect(screen.getByText(label)).toBeInTheDocument();
      expect(screen.getByText("Exact list owner reason")).toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "Info for Endpoints" }).closest(".projection-list-state")).toHaveAttribute("data-evidence-state", state);
    fireEvent.click(screen.getByRole("button", { name: "Info for Endpoints" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(label)).toBeInTheDocument();
    expect(dialog).toHaveTextContent("Security input is absent.");
    expect(dialog).toHaveTextContent(identity.sha256);
    if (state !== "published") expect(dialog).toHaveTextContent("Exact list owner reason");
  });
  it("retains an unresolved caveat identifier rather than dropping its missing detail", () => {
    show({ ...base, state: "published", value: 87, caveats: ["path_route_model_only"] });
    fireEvent.click(screen.getByRole("button", { name: "Info for Health" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Limitation detail unavailable: path_route_model_only");
  });
  it("keeps supplied axis metadata reachable in the same exact-source Info drawer as plain text", () => {
    const { container } = render(<EvidenceProvider identity={identity} limitations={limitations}>
      <FactView label="Capture axis" fact={{ ...base, state: "published", value: "unverified" }}
        metadata={{ "Engine axis index": 0, "Basis sections": ["collection_completeness", "<script>untrusted()</script>"] }} />
    </EvidenceProvider>);
    expect(screen.queryByText("Engine axis index")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Info for Capture axis" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Source metadata");
    expect(dialog).toHaveTextContent("Engine axis index");
    expect(within(dialog).getByText("0", { exact: true })).toBeInTheDocument();
    expect(dialog).toHaveTextContent("Basis sections");
    expect(dialog).toHaveTextContent("collection_completeness");
    expect(dialog).toHaveTextContent("<script>untrusted()</script>");
    expect(dialog).toHaveTextContent(identity.sha256);
    expect(container.querySelector("script")).toBeNull();
  });
  it("closes Info and releases the body scroll lock when a retained workspace becomes inactive, without reopening on return", () => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "scroll";
    const tree = (active: boolean) => <><button type="button">Outside Network</button><div hidden={!active} inert={!active}>
      <EvidenceProvider identity={identity} limitations={limitations} active={active}>
        <FactView label="Health" fact={{ ...base, state: "published", value: 87 }} />
      </EvidenceProvider></div></>;
    const rendered = render(tree(true));
    try {
      const info = screen.getByRole("button", { name: "Info for Health" });
      info.focus(); fireEvent.click(info);
      expect(screen.getByRole("dialog", { name: "Evidence: Health" })).toHaveTextContent("owner.rule");
      expect(document.body.style.overflow).toBe("hidden");
      const outside = screen.getByRole("button", { name: "Outside Network" }); outside.focus();
      rendered.rerender(tree(false));
      expect(screen.queryByRole("dialog", { hidden: true })).toBeNull();
      expect(document.body.style.overflow).toBe("scroll"); expect(outside).toHaveFocus();
      rendered.rerender(tree(true));
      expect(screen.queryByRole("dialog")).toBeNull(); expect(document.body.style.overflow).toBe("scroll");
      expect(screen.getByRole("button", { name: "Info for Health" })).toBeVisible();
      fireEvent.click(screen.getByRole("button", { name: "Info for Health" }));
      expect(screen.getByRole("dialog", { name: "Evidence: Health" })).toHaveTextContent("87");
      expect(document.body.style.overflow).toBe("hidden");
      fireEvent.click(screen.getByRole("button", { name: "Close evidence" }));
      expect(document.body.style.overflow).toBe("scroll");
    } finally {
      rendered.unmount(); document.body.style.overflow = previousOverflow;
    }
  });
});
