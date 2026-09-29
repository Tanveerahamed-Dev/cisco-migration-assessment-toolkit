/**
 * dataset.banner.test.ts — the page always says WHICH dataset it shows.
 *
 *   - the bundled sample: the header's provenance names it as this build's sample, and offers "Open a
 *     snapshot file…"; the status bar carries no banner (nothing to warn about);
 *   - an opened file: a persistent banner on the status bar (every screen) names the file, its origin and
 *     both digests with their form, and offers "Return to the sample";
 *   - an AssessHub snapshot: the banner names the snapshot id, the store-blob digest form, and whether the
 *     digest was verified in this browser or is server-attested, not re-verified; there is no sample to
 *     return to and no file to open;
 *   - an opened file that could not be restored: the banner says the sample on screen is NOT their file.
 *
 * And the header's size/digest wording follows the loaded dataset's digest form instead of always
 * saying "LF-normalised" (an AssessHub snapshot's digest is over the stored bytes exactly).
 */
import { createElement, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { actAsync } from "../test-support/act-turns";
import type { CompiledDataset, InstalledDataset } from "./dataset/types";
import { asOpenedFile, compileGolden } from "./dataset/testing";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mounted: { root: Root; el: HTMLElement }[] = [];
function mount(node: ReactNode): HTMLElement {
  const el = document.createElement("div");
  document.body.appendChild(el);
  const root = createRoot(el);
  act(() => {
    root.render(node);
  });
  mounted.push({ root, el });
  return el;
}
afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => {
      m.root.unmount();
    });
    m.el.remove();
  }
  document.body.innerHTML = "";
  vi.resetModules();
});

const golden: CompiledDataset = compileGolden();

async function load(install: InstalledDataset | null, notice?: { code: string; message: string }) {
  const slot = await import("./dataset/slot");
  if (install !== null) slot.installDataset(install);
  if (notice) slot.noteDatasetNotice(notice);
  const { StatusBar } = await import("../app/StatusBar");
  const { Header } = await import("../app/Header");
  const { datasetActions } = await import("./dataset/actions");
  return { StatusBar, Header, datasetActions };
}

const openProvenance = (c: HTMLElement): HTMLElement => {
  const trigger = c.querySelector<HTMLButtonElement>(".hdr-snap")!;
  act(() => {
    trigger.click();
  });
  return document.querySelector<HTMLElement>('[role="dialog"][aria-label="Snapshot provenance"]')!;
};

describe("which dataset the page shows is always said", () => {
  it("bundled sample: no status-bar banner; the header names it as this build's sample and offers to open a file", async () => {
    const { StatusBar, Header } = await load(null);
    const bar = mount(createElement(StatusBar));
    expect(bar.querySelector(".sb-dataset")).toBeNull();
    const panel = openProvenance(mount(createElement(Header)));
    expect(panel.textContent).toContain("the sample fleet bundled with this build");
    expect([...panel.querySelectorAll("button")].map((b) => b.textContent)).toContain("Open a snapshot file…");
    expect(panel.textContent).toContain("bytes (LF-normalised)");
  });

  it("opened file: a persistent banner names the file, its origin and both digests, and returns to the sample", async () => {
    const { StatusBar, datasetActions } = await load(asOpenedFile(golden, "customer-fleet.snapshot.json"));
    const bar = mount(createElement(StatusBar));
    const banner = bar.querySelector<HTMLElement>(".sb-dataset")!;
    expect(banner).not.toBeNull();
    expect(banner.dataset.origin).toBe("opened-file");
    const text = banner.textContent ?? "";
    expect(text).toContain("customer-fleet.snapshot.json");
    expect(text).toContain("opened in this browser");
    expect(text).toContain("lf-normalised");
    expect(banner.querySelector('[data-digest="sourceSha256"]')?.getAttribute("title")).toContain(golden.fabric.meta.sourceSha256);
    expect(banner.querySelector('[data-digest="sourceExactSha256"]')?.getAttribute("title")).toContain(golden.fabric.meta.sourceExactSha256);
    let reloaded = 0;
    const cleared: string[] = [];
    datasetActions.reload = () => (reloaded += 1);
    datasetActions.store = { get: async () => undefined, put: async () => undefined, clear: async () => void cleared.push("store") };
    const back = [...banner.querySelectorAll("button")].find((b) => b.textContent === "Return to the sample")!;
    await actAsync(async () => {
      back.click();
    });
    expect(cleared).toEqual(["store"]);
    expect(reloaded).toBe(1);
  });

  for (const verification of ["verified-in-browser", "server-attested"] as const) {
    it(`AssessHub snapshot (${verification}): the banner names the id, the store-blob form and what was checked; no return, no open`, async () => {
      const set = structuredClone(golden);
      for (const doc of [set.fabric, set.aclBindings, set.ribEvidence, set.producerEmission]) {
        Object.assign(doc.meta, { source: "assesshub:snapshot/12", sourceOrigin: "assesshub-store", sourceDigestForm: "assesshub-store-blob" });
      }
      const { StatusBar, Header } = await load({
        set,
        origin: { kind: "assesshub", snapshotId: "12", verification, attestedSha256: set.fabric.meta.sourceSha256, attestedBytes: set.fabric.meta.sourceBytes, warnings: [] },
      });
      const banner = mount(createElement(StatusBar)).querySelector<HTMLElement>(".sb-dataset")!;
      const text = banner.textContent ?? "";
      expect(text).toContain("AssessHub snapshot 12");
      expect(text).toContain("assesshub-store-blob");
      expect(text).toContain(verification === "verified-in-browser" ? "digest recomputed here, equal to AssessHub's" : "server-attested, not re-verified");
      if (verification === "server-attested") expect(text).not.toContain("recomputed");
      expect([...banner.querySelectorAll("button")].map((b) => b.textContent)).not.toContain("Return to the sample");
      const panel = openProvenance(mount(createElement(Header)));
      expect([...panel.querySelectorAll("button")].map((b) => b.textContent)).not.toContain("Open a snapshot file…");
      expect(panel.textContent).not.toContain("LF-normalised");
      expect(panel.textContent).toContain("AssessHub snapshot 12");
      /* EVERY statement of a digest — the banner's titles and the provenance panel's copy controls — says
         where the value came from (phase 3.5, P3E-V3). Outside a secure context nothing was computed:
         both digests are AssessHub's X-Snapshot-Sha256 passed through (dataset/hashes.ts attestedHashes),
         so "over the bytes as read" / "the exact bytes read" was a computation claim with no computation. */
      const statements = [
        ...[...banner.querySelectorAll<HTMLElement>("[data-digest]")].map((d) => `banner ${d.dataset.digest}: ${d.getAttribute("title") ?? ""}`),
        ...[...panel.querySelectorAll<HTMLElement>(".ui-copyable--digest button")].map((b) => `panel: ${b.getAttribute("aria-label") ?? ""}`),
      ];
      expect(statements.length, "both digests are stated on the banner and in the panel").toBe(4);
      for (const st of statements) {
        if (verification === "server-attested") {
          expect(st, st).toContain("as AssessHub stated it (not recomputed here)");
          expect(st, st).not.toMatch(/\bas read\b|\bbytes read\b|\bover the bytes\b/);
        } else {
          expect(st, st).not.toContain("not recomputed");
        }
      }
    });
  }

  it("what the snapshot does not state (the validator's warnings) is said on the banner, not dropped", async () => {
    /* The REAL validator's warnings on a real snapshot (the golden fleet states neither collected_at nor
       generated_at), not a hand-made list: the banner must carry whatever the validator reported. */
    const { runCompileRequest } = await import("./dataset/compile-request");
    const { readFileSync } = await import("node:fs");
    const { GOLDEN_SNAPSHOT } = await import("./dataset/testing");
    const bytes = new Uint8Array(readFileSync(GOLDEN_SNAPSHOT));
    const outcome = await runCompileRequest({ bytes: bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength), label: { source: "snapshot.json", sourceOrigin: "external-file" }, expect: null }, globalThis.crypto.subtle);
    if (!outcome.ok) throw new Error(`golden did not compile: ${JSON.stringify(outcome.errors)}`);
    expect(outcome.warnings.length).toBeGreaterThan(0);
    const { StatusBar } = await load({
      set: outcome.set,
      origin: { kind: "opened-file", fileName: "snapshot.json", fileBytes: bytes.byteLength, warnings: outcome.warnings },
    });
    const banner = mount(createElement(StatusBar)).querySelector<HTMLElement>(".sb-dataset")!;
    const shown = [...banner.querySelectorAll<HTMLElement>("[data-warning]")].map((w) => w.dataset.warning);
    expect(shown).toEqual(outcome.warnings.map((w) => w.code));
    for (const w of outcome.warnings) expect(banner.textContent).toContain(w.message);
  });

  it("an opened file that could not be restored: the banner says the sample is not their file", async () => {
    const { StatusBar } = await load(null, {
      code: "E_STORE_EMPTY",
      message: "The snapshot you opened earlier could not be restored: x. This is the bundled sample fleet, not your file — open it again to see it.",
    });
    const banner = mount(createElement(StatusBar)).querySelector<HTMLElement>(".sb-dataset")!;
    expect(banner).not.toBeNull();
    expect(banner.querySelector('[role="alert"]')?.textContent).toContain("not your file");
    expect(banner.textContent).toContain("E_STORE_EMPTY");
  });

  it("opening an invalid file shows its refusal with the code, and nothing reloads", async () => {
    const { Header, datasetActions } = await load(null);
    let reloaded = 0;
    datasetActions.reload = () => (reloaded += 1);
    const { runCompileRequest } = await import("./dataset/compile-request");
    datasetActions.compile = (req) => runCompileRequest(req, globalThis.crypto.subtle);
    const panel = openProvenance(mount(createElement(Header)));
    const input = panel.querySelector<HTMLInputElement>('input[type="file"]')!;
    const file = new File([new Uint8Array([0xef, 0xbb, 0xbf, 0x7b, 0x7d])], "bom.snapshot.json", { type: "application/json" });
    Object.defineProperty(input, "files", { value: [file], configurable: true });
    await actAsync(async () => {
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await vi.waitFor(() => expect(document.querySelector("[data-open-refused]")).not.toBeNull(), { timeout: 30_000 });
    const refused = document.querySelector<HTMLElement>("[data-open-refused]")!;
    expect(refused.textContent).toContain("bom.snapshot.json cannot be shown");
    expect(refused.querySelector('[data-code="E_BOM"]')).not.toBeNull();
    expect(reloaded).toBe(0);
  });
});
