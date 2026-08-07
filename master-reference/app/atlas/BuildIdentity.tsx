"use client";

import { useEffect, useState } from "react";
import { loadProjectionIdentity } from "./SourceExplorerData";
import type { ProjectionIdentity } from "./SourceExplorerTypes";

type IdentityState =
  | { state: "loading" }
  | { state: "missing" }
  | { state: "ready"; identity: ProjectionIdentity };

export function BuildIdentity() {
  const [state, setState] = useState<IdentityState>({ state: "loading" });
  useEffect(() => {
    let active = true;
    void loadProjectionIdentity()
      .then((module) => {
        if (active) setState({ state: "ready", identity: module.identity });
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
  const failed = state.identity.failedAcceptanceGates;
  return (
    <div title={failed.length ? `Blocked: ${failed.map((gate) => gate.name).join(", ")}` : "All emitted semantic gates passed"}>
      <span>Source / verdict</span>
      <strong>{state.identity.sourceCommit.slice(0, 12)}</strong>
      <small>{failed.length} semantic gate{failed.length === 1 ? "" : "s"} blocked · {state.identity.releaseClass}</small>
    </div>
  );
}
