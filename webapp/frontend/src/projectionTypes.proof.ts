import type { Fact, Projection, Schemas } from "./projection";

// Compiled by the normal build. These assertions must fail if generation widens the owner union.
export function projectionTypeProof(fact: Schemas["UiProjection1_CountFact"], view: Projection, allFacts: Fact) {
  if (fact.state === "published") {
    const value: number = fact.value;
    // @ts-expect-error Published count cannot carry null.
    const invalid: null = fact.value;
    void [value, invalid];
  } else {
    const value: null = fact.value;
    const reason: string = fact.reason;
    // @ts-expect-error A withheld fact cannot carry a measured count.
    const invalid: number = fact.value;
    void [value, reason, invalid];
  }
  // @ts-expect-error Generated owner properties are immutable.
  fact.value = 4;
  // @ts-expect-error State vocabulary is closed.
  const invented: Fact["state"] = "healthy";
  if (view.view === "inventory") {
    const model = view.payload.devices.rows.page.items[0]?.model;
    // @ts-expect-error Inventory cannot be mistaken for a findings payload.
    const invalid = view.payload.headline_axis_index;
    void [model, invalid];
  }
  // @ts-expect-error No catch-all owner property is exposed.
  const extra = allFacts.made_up;
  void [invented, extra];
}
