import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EvidenceProvider, FactView } from "./ProjectionEvidence";
import type { Fact, Identity, Limitation } from "../projection";

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
    expect(screen.queryByText("Not collected")).not.toBeInTheDocument();
  });
  it.each([
    ["collected_but_empty", "Collected, empty"], ["not_collected", "Not collected"],
    ["analysis_unavailable", "Analysis unavailable"], ["not_assessed", "Not assessed"], ["unverified", "Unverified"],
  ] as const)("keeps %s distinct with the owner reason", (state, label) => {
    show({ ...base, state, value: null, reason: "Exact owner reason" });
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByText("Exact owner reason")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });
  it("opens evidence with exact pointers, source identity and caveats, traps focus and returns it", () => {
    show({ ...base, state: "published", value: 87, caveats: ["health_scored_without_security"] });
    const button = screen.getByRole("button", { name: "Evidence for Health" });
    button.focus();
    fireEvent.click(button);
    const dialog = screen.getByRole("dialog", { name: "Evidence: Health" });
    expect(dialog).toHaveTextContent("/a~1b/0");
    expect(dialog).toHaveTextContent("/witness/4");
    expect(dialog).toHaveTextContent(identity.sha256);
    expect(dialog).toHaveTextContent("Security input is absent.");
    const close = screen.getByRole("button", { name: "Close evidence" });
    expect(close).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
    expect(close).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(button).toHaveFocus();
  });
  it("renders source text as data and keeps caveats visible beside the fact", () => {
    const { container } = show({ ...base, state: "published", value: "<img src=x onerror=alert(1)>", caveats: ["health_scored_without_security"] });
    expect(container.querySelector("img")).toBeNull();
    const qualifications = screen.getByRole("button", { name: "Qualifications for Health" });
    expect(qualifications).toHaveTextContent("Qualifications (1)");
    fireEvent.click(qualifications);
    expect(screen.getByRole("dialog")).toHaveTextContent("Security input is absent.");
    expect(screen.getByRole("dialog")).toHaveTextContent("health_scored_without_security");
    expect(screen.getByRole("dialog")).toHaveTextContent("Owner: engine");
  });
  it("never presents an old selected fact under a replacement source identity", () => {
    const tree = (sha: string) => <EvidenceProvider identity={{ ...identity, sha256: sha }} limitations={limitations}>
      <FactView label="Health" fact={{ ...base, state: "published", value: 87 }} /></EvidenceProvider>;
    const view = render(tree(identity.sha256));
    fireEvent.click(screen.getByRole("button", { name: "Evidence for Health" }));
    view.rerender(tree(`sha256:${"b".repeat(64)}`));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
