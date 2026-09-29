/**
 * dataset.refusal.test.ts — when the page cannot show its dataset (or cannot load at all), the boot line
 * is replaced by a CODED, plain-language refusal, whatever the failure was.
 *
 * The coded refusals of the dataset door (DatasetBootError, from dataset/boot.ts) keep every issue's code.
 * A failure that is not one of them — the slot refusing an install, a build carrying no dataset, the
 * application chunk failing to load — used to fall through to one uncoded sentence, so a reader (or a
 * support conversation) had nothing to quote. Every failure now carries a code on the element and in the
 * text: the one the error states (`E_…:` at the head of its message), else E_APP_LOAD.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DatasetBootError } from "./dataset/boot";
import { showDatasetRefusal } from "./dataset/refusal";
import { selectActiveDataset } from "./dataset/select";
import { asOpenedFile, compileGolden, PKG } from "./dataset/testing";

function bootLine(): HTMLElement {
  const root = document.createElement("div");
  root.innerHTML = '<p class="boot" role="status" aria-busy="true">Loading Atlas Scope</p>';
  document.body.appendChild(root);
  return root.querySelector<HTMLElement>(".boot")!;
}

afterEach(() => {
  document.body.innerHTML = "";
  vi.resetModules();
});

const thrown = (fn: () => unknown): unknown => {
  try {
    fn();
  } catch (e) {
    return e;
  }
  throw new Error("expected a throw");
};

describe("every failure to load is a coded, plain-language refusal", () => {
  it("a dataset-door refusal keeps each issue's code and message", () => {
    const boot = bootLine();
    showDatasetRefusal(boot, new DatasetBootError("Atlas Scope could not open AssessHub snapshot 7", [
      { code: "E_HUB_HTTP", message: "AssessHub answered 404 for snapshot 7." },
      { code: "E_NOT_JSON", message: "the bytes are not JSON." },
    ]));
    expect(boot.getAttribute("role")).toBe("alert");
    expect(boot.getAttribute("aria-busy")).toBe("false");
    expect(boot.dataset.datasetError).toBe("E_HUB_HTTP");
    expect(boot.textContent).toContain("[E_HUB_HTTP]");
    expect(boot.textContent).toContain("[E_NOT_JSON]");
    expect(boot.textContent).toContain("The bytes are not JSON.");
  });

  it("the slot refusing a late install is coded (E_DATASET_SEALED)", async () => {
    const slot = await import("./dataset/slot");
    slot.resetDatasetSlotForTests();
    slot.takeInstalledDataset();
    const err = thrown(() => slot.installDataset(asOpenedFile(compileGolden())));
    const boot = bootLine();
    showDatasetRefusal(boot, err);
    expect(boot.dataset.datasetError).toBe("E_DATASET_SEALED");
    expect(boot.getAttribute("role")).toBe("alert");
    expect(boot.textContent).toContain("[E_DATASET_SEALED]");
    slot.resetDatasetSlotForTests();
  });

  it("a build with no dataset and nothing installed is coded (E_NO_DATASET)", () => {
    const boot = bootLine();
    showDatasetRefusal(boot, thrown(() => selectActiveDataset(null, null)));
    expect(boot.dataset.datasetError).toBe("E_NO_DATASET");
    expect(boot.textContent).toContain("carries no bundled dataset");
  });

  it("an uncoded failure (the application chunk did not load) is still coded: E_APP_LOAD", () => {
    const boot = bootLine();
    showDatasetRefusal(boot, new TypeError("Failed to fetch dynamically imported module"));
    expect(boot.dataset.datasetError).toBe("E_APP_LOAD");
    expect(boot.getAttribute("role")).toBe("alert");
    expect(boot.textContent).toContain("[E_APP_LOAD]");
    expect(boot.textContent).toContain("Reload the page");
  });

  it("the boot entry (src/main.tsx) renders its failures through this one owner", () => {
    const main = readFileSync(resolve(PKG, "src", "main.tsx"), "utf8");
    expect(main).toMatch(/import\s*\{\s*showDatasetRefusal\s*\}\s*from\s*"\.\/core\/dataset\/refusal"/);
    expect(main).toMatch(/\.catch\([^)]*\)\s*=>\s*\{[\s\S]*showDatasetRefusal\(/);
  });
});
