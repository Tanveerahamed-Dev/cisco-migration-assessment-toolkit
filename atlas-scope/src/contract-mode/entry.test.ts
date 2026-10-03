import { afterEach, describe, expect, it, vi } from "vitest";
import { readContractMode } from "./entry";
const nonce = "7".repeat(32);
const origin = window.location.origin;
const location = (search: string) => ({ pathname: "/scope/snapshots/7/", search, hash: "", origin });
afterEach(() => { vi.unstubAllEnvs(); vi.resetModules(); vi.doUnmock("./boot"); vi.doUnmock("../core/dataset/boot"); vi.doUnmock("../mount"); history.replaceState(null, "", "/"); document.body.replaceChildren(); });

describe("Scope early contract entry", () => {
  it("recognizes only the closed same-hub mode and never downgrades an attempted mode", () => {
    expect(readContractMode(location("?ordinary=1"), "hub")).toEqual({ selected: false });
    expect(readContractMode(location(`?engine_projection=1&projection_nonce=${nonce}`), "hub")).toEqual({ selected: true, valid: true, snapshotId: 7, nonce, origin });
    for (const query of ["?engine_projection=2", `?projection_nonce=${nonce}`, `?engine_projection=1&projection_nonce=${nonce}&extra=1`,
      `?engine_projection=1&engine_projection=1&projection_nonce=${nonce}`, `?engine_projection=1&projection_nonce=${nonce}&projection_nonce=${nonce}`,
      `?engine_projection=1&projection_nonce=${nonce.slice(0, -1)}%0a`]) {
      expect(readContractMode(location(query), "hub")).toEqual({ selected: true, valid: false });
    }
    expect(readContractMode(location(`?engine_projection=1&projection_nonce=${nonce}`), "production")).toEqual({ selected: true, valid: false });
    expect(readContractMode({ ...location(`?engine_projection=1&projection_nonce=${nonce}`), pathname: "/scope/snapshots/8/../7/" }, "hub")).toEqual({ selected: true, valid: false });
  });

  it("executes the real entry in contract mode without evaluating dataset boot or mount", async () => {
    vi.resetModules(); vi.stubEnv("MODE", "hub");
    const boot = vi.fn(() => () => {});
    vi.doMock("./boot", () => ({ bootContractMode: boot }));
    vi.doMock("../core/dataset/boot", () => { throw new Error("legacy dataset boot evaluated"); });
    vi.doMock("../mount", () => { throw new Error("legacy App mount evaluated"); });
    document.body.innerHTML = '<div id="root"><p class="boot">Loading</p></div>';
    history.replaceState(null, "", `/scope/snapshots/7/?engine_projection=1&projection_nonce=${nonce}`);
    await import("../main"); await vi.dynamicImportSettled();
    expect(boot).toHaveBeenCalledExactlyOnceWith(document.getElementById("root"), { selected: true, valid: true, snapshotId: 7, nonce, origin });
  });

  it("refuses an invalid attempted mode without evaluating either application", async () => {
    vi.resetModules(); vi.stubEnv("MODE", "hub");
    const boot = vi.fn(); vi.doMock("./boot", () => ({ bootContractMode: boot }));
    vi.doMock("../core/dataset/boot", () => { throw new Error("legacy dataset boot evaluated"); });
    vi.doMock("../mount", () => { throw new Error("legacy App mount evaluated"); });
    document.body.innerHTML = '<div id="root"><p class="boot">Loading</p></div>';
    history.replaceState(null, "", `/scope/snapshots/7/?engine_projection=unsupported&projection_nonce=${nonce}`);
    await import("../main"); await vi.dynamicImportSettled();
    expect(boot).not.toHaveBeenCalled(); expect(document.querySelector(".boot")?.textContent).toContain("E_CONTRACT_MODE");
  });
});
