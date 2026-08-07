"use client";

import { useEffect, useState } from "react";
import { loadProjection } from "./SourceExplorerData";
import type { ProjectionIndex } from "./SourceExplorerTypes";

type IdentityState =
  | { state: "loading" }
  | { state: "missing" }
  | { state: "ready"; index: ProjectionIndex };

export function BuildIdentity() {
  const [state, setState] = useState<IdentityState>({ state: "loading" });
  useEffect(() => {
    let active = true;
    void loadProjection()
      .then((module) => {
        if (active) setState({ state: "ready", index: module.projection });
      })
      .catch(() => {
        if (active) setState({ state: "missing" });
      });
    return () => {
      active = false;
    };
  }, []);

  if (state.state === "loading") {
    return <div><span>Source binding</span><strong>Checking</strong><small>loading projection receipt</small></div>;
  }
  if (state.state === "missing") {
    return <div><span>Source binding</span><strong>Pending</strong><small>no exact projection in this build</small></div>;
  }
  const acceptance = state.index.completeness.acceptance_gates ?? [];
  const failed = acceptance.filter((gate) => !gate.passed);
  return (
    <div title={failed.length ? `Blocked: ${failed.map((gate) => gate.name).join(", ")}` : "All emitted semantic gates passed"}>
      <span>Source / verdict</span>
      <strong>{state.index.sourceCommit.slice(0, 12)}</strong>
      <small>{failed.length} semantic gate{failed.length === 1 ? "" : "s"} blocked · {state.index.releaseClass}</small>
    </div>
  );
}
