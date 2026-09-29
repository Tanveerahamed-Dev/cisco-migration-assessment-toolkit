/**
 * EvidencePane.engine-refs.test.tsx — every finding reaches the evidence the ENGINE names for it (acceptance
 * A1, phase 3), within three interactions from the priority queue, without the topology resetting.
 *
 * WHY. Until the phase-3 regeneration the engine published no per-finding evidence, and this pane reached a
 * record by matching the finding's words (EvidencePane.namedconfig.test.ts measures that route: 6 of 146
 * findings named their configuration). Every punch-list row now carries `evidence_basis` and `evidence_refs`
 * (RFC 6901 pointers; contracts/engine-contract.v1.json), and the compiler projects each pointed record into
 * the model (`fabric.evidenceRecords`). This file re-measures A1 over EVERY finding of the compiled data, by
 * operating the real app's parts the way a reader does and COUNTING the interactions EXACTLY as
 * docs/acceptance.md settles them for A1 (a click, a key chord, or one typed query committed with Enter is one
 * interaction; scrolling is a FAILURE, not an interaction). A queue row that is not in view is reached through the
 * command palette, so every finding is selected that way here, worst case for all:
 *   1  Ctrl+K (the real CommandPalette, mounted beside the pane);
 *   2  the finding's id typed and committed with Enter;
 *   3  the record's control in the pane's header — the header does not scroll, so the control is on screen at
 *      selection; activating it opens the record (an interface / access-list / route record opens its compiled
 *      record, any other record shows its members, configuration text is printed verbatim), in step 3, and the
 *      APP brings it into view and moves focus to it. No reader scroll, no "Show all", no second disclosure.
 * The phase-3 measurement counted selection as 1 whatever the row's position, did not count the move to step 3,
 * and counted "Show all" and the disclosure as extra steps — so folded refs and folded-only findings needed 4 by
 * the acceptance's counting (verifier P3A1-V2-1). Each pointer is also a WORKING citation: its control opens
 * exactly that pointer, and the Inspector resolves the pointer to the projected record. The whole investigation
 * store is compared before and after, so no step re-aims or resets the topology.
 *
 * Expectations are derived from the compiled data; the numbers true only of the tracked sample are in the
 * golden tier (src/test-support/golden-sample.ts), never scattered literals.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { CommandPalette } from "../app/CommandPalette";
import { fabric, findingById } from "../core/data";
import { useInvestigation } from "../core/store";
import type { Finding } from "../core/types";
import { actAsync } from "../test-support/act-turns";
import { describeGolden } from "../test-support/golden-sample";
import { citesIn } from "./cited-text";
import { EvidencePane, engineEvidenceFor, evidenceRecordAt, pointerTokens, type ConfigEvidence, type EngineRef, engineNameRuns, engineRecordNames } from "./EvidencePane";
import { resolveCitation } from "./Inspector";
import { PriorityQueue } from "./PriorityQueue";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mounted: { root: Root; container: HTMLElement }[] = [];
function mount(ui: ReactNode): HTMLElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(ui));
  mounted.push({ root, container });
  return container;
}
afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
});

interface Spies {
  opened: string[];
  shown: ConfigEvidence[];
}
function mountFor(findingId: string): { c: HTMLElement; spies: Spies } {
  act(() => {
    useInvestigation.getState().reset();
    useInvestigation.getState().selectFinding(findingId);
  });
  const spies: Spies = { opened: [], shown: [] };
  const c = mount(<EvidencePane onOpenCite={(x) => spies.opened.push(x)} onShowConfig={(t) => spies.shown.push(t)} />);
  return { c, spies };
}
const click = (el: Element): void => {
  act(() => {
    el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
};
/** The investigation as data: what a control that resets or re-aims the topology would change. */
const investigation = (): string =>
  JSON.stringify(useInvestigation.getState(), (_k, v: unknown) => (typeof v === "function" ? undefined : v));
const byAttr = (root: ParentNode, attr: string, value: string): HTMLElement | undefined =>
  [...root.querySelectorAll<HTMLElement>(`[${attr}]`)].find((e) => e.getAttribute(attr) === value);

const withRefs = fabric.findings.filter((f) => f.evidenceRefs !== null && f.evidenceRefs !== undefined);

/**
 * Every number a section heading prints is the ENGINE's count for that section, whatever the fold shows: the
 * heading of the witnesses said "witnessed by 7 records" for F142, which has 20 (only the unfolded ones were
 * counted), and the named-records heading said 8 for findings naming 11–26 (verifier P3A1-V1-1). Derived from
 * the finding's own pointers, so it holds for any snapshot.
 */
function expectHeadingCounts(engine: HTMLElement, f: Finding, when: string): void {
  const all = engineEvidenceFor(f) ?? [];
  const nOpen = all.filter((r) => r.open !== null).length;
  const nWit = all.filter((r) => r.open === null && r.ref.kind === "absence_witness").length;
  const head = (label: string): string | null => engine.querySelector(`section[aria-label="${label}"] > h4`)?.textContent ?? null;
  const named = head("Records the engine names");
  const wit = head("Absence, witnessed by");
  if (nOpen === 0) expect(named, `${f.id} ${when}`).toBeNull();
  else if (nOpen === 1) expect(named, `${f.id} ${when}`).toMatch(/^The record the engine names(?: \(|$)/);
  else expect(named, `${f.id} ${when}: the named records are counted over all ${nOpen}`).toMatch(new RegExp(`^The ${nOpen} records the engine names(?: \\(|$)`));
  if (nWit === 0) expect(wit, `${f.id} ${when}`).toBeNull();
  else expect(wit, `${f.id} ${when}: the witnesses are counted over all ${nWit}`).toMatch(new RegExp(`^Absence, witnessed by ${nWit} records?(?: \\(|$)`));
  /* Where the fold hides some, the heading says how many are on screen — the true number, never presented as the total. */
  for (const [label, n] of [["Records the engine names", nOpen], ["Absence, witnessed by", nWit]] as const) {
    const section = engine.querySelector(`section[aria-label="${label}"]`);
    if (section === null) continue;
    const onScreen = section.querySelectorAll(":scope > ul > li").length;
    const text = head(label) ?? "";
    if (onScreen < n) expect(text, `${f.id} ${when}: ${label}`).toMatch(new RegExp(`\\(${onScreen} shown\\)$`));
    else expect(text, `${f.id} ${when}: ${label}`).not.toMatch(/shown\)$/);
  }
}
/** Filled by the per-finding cases, read by the census after them. */
const reached = new Map<string, number>();
/** How many of each finding's pointers the per-finding cases worked (the census checks none was skipped). */
const refsWorked = new Map<string, number>();

describe("every engine pointer is a working citation (B6 over the engine's own grammar)", () => {
  const pointers = [...new Set(withRefs.flatMap((f) => (f.evidenceRefs ?? []).map((r) => r.ref)))];

  it("the model carries pointers at all, and one projected record per pointer", () => {
    expect(pointers.length).toBeGreaterThan(0);
    for (const p of pointers) expect(evidenceRecordAt(p), p).not.toBeNull();
  });

  it("the resolver recognises every pointer as a citation — alone, in a control's name, and at the end of a sentence", () => {
    for (const p of pointers) {
      expect(citesIn(p), p).toEqual([p]);
      expect(citesIn(`Open source record ${p}`), p).toEqual([p]);
      expect(citesIn(`the engine points at ${p}.`), p).toEqual([p]);
    }
  });

  it("the Inspector resolves every pointer to the record the model projected for it", () => {
    for (const p of pointers) {
      const r = resolveCitation(p);
      expect(r.kind, p).toBe("bearer");
      expect((r.record as { pointer?: string } | undefined)?.pointer, p).toBe(p);
      expect(r.modelPath, p).toMatch(/^evidenceRecords\[\d+\]$/);
    }
  });

  it("slashes that are not a pointer the model carries are not citations", () => {
    for (const t of ["10.0.0.0/24", "and/or", "https://example.invalid/a/b", "/no/such/pointer", " / "]) expect(citesIn(t), t).toEqual([]);
    // The dotted grammar is unchanged beside it.
    const iface = Object.values(fabric.interfaces).flat()[0];
    expect(iface, "precondition: a compiled interface record").toBeDefined();
    expect(citesIn(`see ${iface!.cite} and /no/such`)).toEqual([iface!.cite]);
  });

  it("a dotted citation right after a slash is still found when the slash does not start a pointer the model carries", () => {
    /* The pointer grammar is tried first at a slash; when its token names no record it used to be SKIPPED whole,
       so the citation the dotted grammar would have found inside it was lost (verifier P3A1-V1-3). */
    const [a, b] = fabric.findings.map((f) => f.cite);
    expect(a !== undefined && b !== undefined, "precondition: two finding citations").toBe(true);
    expect(citesIn(`${a}/${b}`)).toEqual([a, b]);
    expect(citesIn(`(${a}) /${b}`)).toEqual([a, b]);
    expect(citesIn(`see ${a}, /${b}`)).toEqual([a, b]);
    // …while an unresolved pointer's own segments are still not read as bare records.
    const heads = [...new Set(withRefs.flatMap((f) => f.evidenceRefs ?? []).map((r) => pointerTokens(r.ref)?.[0] ?? ""))];
    const citable = heads.filter((h) => citesIn(h).length > 0);
    expect(citable.length, "precondition: a pointer whose first segment, alone, is a citation").toBeGreaterThan(0);
    for (const h of citable) expect(citesIn(`/${h}/no-such-member-here`), h).toEqual([]);
  });
});

/* ══ A1, counted as the acceptance counts ═══════════════════════════════════════════════════════════════ */

const press = (key: string, init: KeyboardEventInit = {}, target: EventTarget = document): void => {
  act(() => {
    target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init }));
  });
};
/** The one key that reaches the manager on this platform for a `mod+` chord. */
const MOD: KeyboardEventInit = /mac|iphone|ipad/i.test(navigator.platform || navigator.userAgent) ? { metaKey: true } : { ctrlKey: true };
const paletteInput = (): HTMLInputElement => {
  const el = document.querySelector<HTMLInputElement>(".palette__input");
  if (!el) throw new Error("palette input not rendered");
  return el;
};
const typeInto = (input: HTMLInputElement, value: string): void => {
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
};
/** Every element the app asked to bring into view while `run` ran (jsdom lays nothing out; the ASK is the act). */
function scrolledDuring(run: () => void): Element[] {
  const calls: Element[] = [];
  const real = Element.prototype.scrollIntoView;
  Element.prototype.scrollIntoView = function (this: Element): void {
    calls.push(this);
  };
  try {
    run();
  } finally {
    Element.prototype.scrollIntoView = real;
  }
  return calls;
}
/** The investigation's subject before the reader starts: a device and a link that nothing below may move. */
const SUBJECT = { host: fabric.devices.find((d) => d.collected)?.host ?? null, link: fabric.links[0]?.id ?? null };

/**
 * What the reader has in front of them once `el` (a ref's <li> in step 3) was reached: the record the POINTER
 * names, opened, shown or printed there — asserted per kind, so no kind can pass by being skipped.
 */
function expectReached(el: HTMLElement, f: Finding, r: EngineRef, where: string): void {
  const p = r.ref.ref;
  const rec = evidenceRecordAt(p);
  if (r.open !== null) {
    const aside = el.querySelector<HTMLElement>("aside.ev-cfg");
    expect(aside, `${f.id} ${p} ${where}: the record the engine names is open beside its pointer`).not.toBeNull();
    expect(aside!.textContent ?? "").toMatch(/Reached because the engine names it for this finding/);
    const tok = pointerTokens(p)!;
    // The record opened is the one the POINTER names, read from its tokens — not one matched by words.
    expect(r.open.host, p).toBe(tok[1]);
    if (r.open.kind === "interface") expect(r.open.record.port, p).toBe(tok[2]);
    if (r.open.kind === "acl") expect(r.open.label, p).toContain(tok[2]!);
    if (r.open.kind === "route") expect(r.open.entries[0]!.cite, p).toBe(`routes.${tok[1]}[${tok[2]}]`);
    expect(aside!.getAttribute("aria-label"), p).toBe(`Configuration evidence for ${r.open.label}`);
    expect(el.querySelector("[data-open-record]")?.getAttribute("aria-expanded"), `${f.id} ${p}: its control says it is open`).toBe("true");
  } else if (r.ref.kind === "config_text") {
    expect(rec, p).not.toBeNull();
    const code = el.querySelector("code");
    expect(code, `${f.id} ${p}: the literal text is printed`).not.toBeNull();
    const v = rec!.value;
    expect(typeof v).toBe("string");
    expect((code!.textContent ?? "").startsWith((v as string).slice(0, 20)), p).toBe(true);
    expect(el.textContent ?? "").toMatch(/verbatim from the snapshot/);
  } else {
    expect(rec, p).not.toBeNull();
    if (rec!.withheld) expect(el.querySelector("[data-evidence-withheld]"), `${f.id} ${p}: withheld, stated`).not.toBeNull();
    else {
      const fields = el.querySelector<HTMLElement>("[data-evidence-fields]");
      expect(fields, `${f.id} ${p} ${where}: the record's members are shown`).not.toBeNull();
      if (rec!.type === "object" || rec!.type === "array") {
        const keys = [...fields!.querySelectorAll(".ev-rec__key")].map((d) => d.textContent);
        const want = Array.isArray(rec!.value) ? rec!.value.map((_, i) => String(i)) : Object.keys(rec!.value ?? {});
        expect(keys, `${f.id} ${p}: every carried member, in the engine's order`).toEqual(want);
      }
      const disclose = el.querySelector<HTMLElement>("[data-evidence-disclose]");
      expect(disclose?.getAttribute("aria-expanded"), `${f.id} ${p}: its disclosure says it is open`).toBe("true");
    }
    if (r.ref.kind === "absence_witness") expect(el.closest("section")?.getAttribute("aria-label")).toBe("Absence, witnessed by");
  }
  expect(el.closest("li.ev-step")?.querySelector(".ev-step__title")?.textContent, `${f.id} ${p}: under the engine's step`).toBe("What the engine points at");
}

describe("A1: every record the engine names is reached in at most three interactions, counted as the acceptance counts", () => {
  it("the compiled data carries findings with engine pointers (the per-finding cases below are over them)", () => {
    expect(withRefs.length).toBeGreaterThan(0);
    expect(SUBJECT.host, "precondition: a collected device to hold as the subject").not.toBeNull();
    expect(SUBJECT.link, "precondition: a link to hold as the subject").not.toBeNull();
  });

  it.each(withRefs.map((f) => [f.id, f] as const))("%s", (_id, f) => {
    act(() => {
      const s = useInvestigation.getState();
      s.reset();
      s.setPaletteOpen(false);
      s.selectDevice(SUBJECT.host);
      s.selectLink(SUBJECT.link);
    });
    const opened: string[] = [];
    const c = mount(
      <>
        <CommandPalette />
        <EvidencePane onOpenCite={(x) => opened.push(x)} />
      </>,
    );
    let n = 0;
    press("k", MOD);
    n += 1;
    expect(useInvestigation.getState().paletteOpen, `${f.id}: interaction ${n}, Ctrl+K, opens the palette`).toBe(true);
    typeInto(paletteInput(), f.id);
    press("Enter", {}, paletteInput());
    n += 1;
    expect(useInvestigation.getState().findingId, `${f.id}: interaction ${n}, the id committed with Enter, selects it`).toBe(f.id);
    expect(useInvestigation.getState().paletteOpen).toBe(false);
    expect(useInvestigation.getState().deviceId, `${f.id}: selecting the finding kept the device`).toBe(SUBJECT.host);
    expect(useInvestigation.getState().linkId, `${f.id}: selecting the finding kept the link`).toBe(SUBJECT.link);

    const pane = c.querySelector<HTMLElement>('section[aria-label="Evidence chain"]')!;
    const engine = pane.querySelector<HTMLElement>("[data-engine-evidence]");
    expect(engine, "the engine's evidence is rendered at selection").not.toBeNull();
    const basis = f.evidenceBasis ?? null;
    expect(engine!.dataset.evidenceBasis).toBe(basis ?? "unstated");
    const said = engine!.querySelector(".ev-engine__basis")?.textContent ?? "";
    if (basis === "record") expect(said).toMatch(/^Basis: record\./);
    if (basis === "row") expect(said).toMatch(/derived from an analysis row.*not configuration/);
    if (basis === "absence") expect(said).toMatch(/^Basis: absence\..*no configuration line/);
    expectHeadingCounts(engine!, f, "at selection");

    // The route to EVERY record the engine names is on screen at selection: in the header, which does not scroll.
    const all = engineEvidenceFor(f) ?? [];
    const index = pane.querySelector<HTMLElement>("[data-engine-index]");
    expect(index, `${f.id}: the header lists the engine's records`).not.toBeNull();
    expect(index!.closest(".ev__head"), `${f.id}: in the pane's header`).not.toBeNull();
    expect(index!.closest(".ev__body"), `${f.id}: not inside the scrolling body`).toBeNull();
    expect(index!.dataset.evidenceRoute, "the header's route is the engine's").toBe("engine");
    const chips = [...index!.querySelectorAll<HTMLButtonElement>("button[data-engine-chip]")];
    expect(chips.map((b) => b.dataset.engineChip), `${f.id}: one control per record the engine names, in its order, none folded`).toEqual(all.map((r) => r.ref.ref));
    /* Each control's accessible name is its whole name; what it shows is that name, or its start where a run of
       controls shares the ending and says it once (label in name, WCAG 2.5.3). */
    const names = chips.map((b) => b.getAttribute("aria-label") ?? (b.textContent ?? "").trim());
    expect(new Set(names).size, `${f.id}: every control is told apart by its name`).toBe(names.length);
    chips.forEach((b, k) => {
      const shows = (b.textContent ?? "").trim();
      expect(shows, `${f.id}: a named control`).not.toBe("");
      expect(names[k]!.startsWith(shows), `${f.id}: "${shows}" is the start of its accessible name "${names[k]}"`).toBe(true);
      expect(citesIn(names[k]!), `${f.id}: no citation printed inertly inside a control that opens something else`).toEqual([]);
    });
    for (const cap of index!.querySelectorAll(".ev-echips__run")) expect(citesIn(cap.textContent ?? ""), `${f.id}: a run's caption`).toEqual([]);

    const before = investigation();
    let worst = 0;
    all.forEach((r, k) => {
      const chip = chips[k]!;
      const asked = scrolledDuring(() => click(chip));
      const steps = n + 1;
      const el = byAttr(engine!, "data-evidence-ref", r.ref.ref);
      expect(el, `${f.id} ref ${k} ${r.ref.ref} is listed in step 3 once its control is used (even past the fold)`).toBeDefined();
      expect(el!.dataset.evidenceKind).toBe(r.ref.kind);
      expect(asked, `${f.id} ${r.ref.ref}: the app brings the record into view — the reader does not scroll`).toContain(el);
      expect(el!.contains(document.activeElement), `${f.id} ${r.ref.ref}: focus moves to what the control produced`).toBe(true);
      expectReached(el!, f, r, "after its header control");

      // The pointer is a working citation control: activating it opens exactly that pointer.
      const cite = [...el!.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.getAttribute("aria-label") === `Open source record ${r.ref.ref}`);
      expect(cite, `${f.id} ${r.ref.ref}: a citation control for the pointer`).toBeDefined();
      opened.length = 0;
      click(cite!);
      expect(opened).toEqual([r.ref.ref]);

      expect(steps, `${f.id} ${r.ref.ref}: interactions from the queue, palette route`).toBeLessThanOrEqual(3);
      worst = Math.max(worst, steps);
    });

    // The list's own fold still says what it hides, and "Show all" lists every record for reading.
    const more = engine!.querySelector<HTMLElement>("[data-engine-show-all]");
    if (more !== null) {
      click(more);
      expectHeadingCounts(engine!, f, "after Show all");
    }
    for (const r of all) expect(byAttr(engine!, "data-evidence-ref", r.ref.ref), `${f.id} ${r.ref.ref} listed`).toBeDefined();
    expect(investigation(), `${f.id}: following the engine's evidence re-aimed or reset the investigation`).toBe(before);
    reached.set(f.id, worst);
    refsWorked.set(f.id, all.length);
  });

  it("every case above ran (a filtered or failed run proves nothing here), and none needed more than three", () => {
    expect(reached.size).toBe(withRefs.length);
    expect(Math.max(...reached.values())).toBeLessThanOrEqual(3);
  });
});

describe("a queue row already in view: row (1), then the record's control (2), the topology untouched", () => {
  it("clicking a queue row renders that finding's engine evidence, and one more click reaches its first record", async () => {
    act(() => {
      useInvestigation.getState().reset();
    });
    const c = mount(
      <>
        <PriorityQueue debounceMs={0} />
        <EvidencePane onOpenCite={() => {}} />
      </>,
    );
    const row = [...c.querySelectorAll<HTMLElement>(".ag__row--data")].find((r) => {
      const id = r.querySelector('[role="rowheader"]')?.textContent ?? "";
      return (findingById.get(id)?.evidenceRefs ?? []).length > 0;
    });
    expect(row, "precondition: a queue row whose finding carries pointers").toBeDefined();
    const id = row!.querySelector('[role="rowheader"]')!.textContent!;
    const { deviceId, linkId } = useInvestigation.getState();
    click(row!.querySelector('[role="gridcell"]') ?? row!);
    await actAsync(async () => {
      await new Promise<void>((resolve) => requestAnimationFrame(() => setTimeout(resolve, 0)));
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
    });
    expect(useInvestigation.getState().findingId).toBe(id);
    const f = findingById.get(id)!;
    const first = (engineEvidenceFor(f) ?? [])[0]!;
    const chip = byAttr(c, "data-engine-chip", first.ref.ref);
    expect(chip, "one click puts the route to the engine's evidence on screen").toBeDefined();
    const asked = scrolledDuring(() => click(chip!));
    const el = byAttr(c, "data-evidence-ref", first.ref.ref)!;
    expect(asked).toContain(el);
    expectReached(el, f, first, "from the queue");
    expect(useInvestigation.getState().deviceId).toBe(deviceId);
    expect(useInvestigation.getState().linkId).toBe(linkId);
  });
});

describe("the App's own path: the pane opens the engine's record itself, in step 3, as the engine's", () => {
  /* The App mounts `<EvidencePane onOpenCite={…} />` with NO onShowConfig (src/app/surfaces.tsx), so the pane
     owns the disclosure. Every opened record rendered inside step 5, under "Other records we hold for these
     hosts" and a note calling what is there "context, not the engine's evidence" — the engine's own record
     presented as a guess (verifier P3A1-V1-2). These mount as the App does, for every record the engine names
     that the model can open, from BOTH of its controls: the header's and the one beside its pointer. */
  const openableFindings = withRefs.filter((f) => (engineEvidenceFor(f) ?? []).some((r) => r.open !== null));
  const stepOf = (el: Element): string => el.closest("li.ev-step")?.querySelector(".ev-step__title")?.textContent ?? "(no step)";
  const excerpts = (c: HTMLElement): HTMLElement[] => [...c.querySelectorAll<HTMLElement>("aside.ev-cfg")];
  const mountAsApp = (id: string): HTMLElement => {
    act(() => {
      useInvestigation.getState().reset();
      useInvestigation.getState().selectFinding(id);
    });
    return mount(<EvidencePane onOpenCite={() => {}} />);
  };
  /** The one excerpt on screen is in step 3, inside the ref that names it, and no step-5 control claims it. */
  const expectEngineExcerpt = (c: HTMLElement, f: Finding, cite: string, where: string): void => {
    const shown = excerpts(c);
    expect(shown, `${f.id} ${where}: one record is open`).toHaveLength(1);
    const aside = shown[0]!;
    expect(stepOf(aside), `${f.id} ${where}: the engine's record opens under the engine's step`).toBe("What the engine points at");
    expect(aside.closest("[data-engine-evidence]"), `${f.id} ${where}`).not.toBeNull();
    expect(aside.textContent ?? "", `${f.id} ${where}`).toMatch(/Reached because the engine names it for this finding/);
    const ref = aside.closest<HTMLElement>("[data-evidence-ref]");
    expect(ref, `${f.id} ${where}: next to the pointer that names it`).not.toBeNull();
    const opener = ref!.querySelector<HTMLElement>("[data-open-record]");
    expect(opener?.getAttribute("data-open-record"), `${f.id} ${where}`).toBe(cite);
    expect(opener?.getAttribute("aria-expanded"), `${f.id} ${where}: its control says it is open`).toBe("true");
    for (const b of c.querySelectorAll<HTMLElement>("[data-evidence-list='context'] button[aria-expanded]"))
      expect(b.getAttribute("aria-expanded"), `${f.id} ${where}: a context control does not claim the engine's record`).toBe("false");
  };

  it("the sample carries findings whose engine-named record the model opens (the cases below are over them)", () => {
    expect(openableFindings.length).toBeGreaterThan(0);
  });

  it.each(openableFindings.map((f) => [f.id, f] as const))("%s", (_id, f) => {
    const c = mountAsApp(f.id);
    const before = investigation();
    const engine = c.querySelector<HTMLElement>("[data-engine-evidence]")!;
    const openable = (engineEvidenceFor(f) ?? []).filter((x) => x.open !== null);
    // From the header: each record the engine names, from its own control there.
    for (const r of openable) {
      click(byAttr(c, "data-engine-chip", r.ref.ref)!);
      expectEngineExcerpt(c, f, r.open!.cite, `${r.ref.ref} from the header`);
    }
    // …and from the control beside its pointer, once the list shows every one.
    const more = engine.querySelector<HTMLElement>("[data-engine-show-all]");
    if (more !== null) click(more);
    for (const r of openable) {
      const el = byAttr(engine, "data-evidence-ref", r.ref.ref);
      expect(el, `${f.id} ${r.ref.ref}`).toBeDefined();
      const open = el!.querySelector<HTMLButtonElement>("[data-open-record]")!;
      if (open.getAttribute("aria-expanded") !== "true") click(open);
      expectEngineExcerpt(c, f, r.open!.cite, `${r.ref.ref} from its pointer`);
    }
    expect(investigation(), `${f.id}: opening the engine's records re-aimed or reset the investigation`).toBe(before);
  });

  it("a record this pane matched by words still opens in step 5, as context — the two are never mixed", () => {
    const f = withRefs.find((x) => {
      const c = mountAsApp(x.id);
      return c.querySelector("[data-evidence-list='context'] button") !== null;
    });
    expect(f, "precondition: a finding with a step-5 context record").toBeDefined();
    const c = mountAsApp(f!.id);
    const b = c.querySelector<HTMLButtonElement>("[data-evidence-list='context'] button[aria-expanded]")!;
    click(b);
    const shown = excerpts(c);
    expect(shown).toHaveLength(1);
    expect(stepOf(shown[0]!)).toBe("Other records we hold for these hosts");
    expect(shown[0]!.closest("[data-engine-evidence]"), "a context record is not placed among the engine's").toBeNull();
    expect(b.getAttribute("aria-expanded")).toBe("true");
    for (const o of c.querySelectorAll<HTMLElement>("[data-engine-evidence] [data-open-record]"))
      expect(o.getAttribute("aria-expanded"), "an engine control does not claim a context record").toBe("false");
  });

  it.each(openableFindings.map((f) => [f.id, f] as const))("with a wider surface owning the disclosure, %s's header controls hand it the record each pointer names", (_id, f) => {
    const shown: ConfigEvidence[] = [];
    act(() => {
      useInvestigation.getState().reset();
      useInvestigation.getState().selectFinding(f.id);
    });
    const c = mount(<EvidencePane onOpenCite={() => {}} onShowConfig={(t) => shown.push(t)} />);
    for (const r of (engineEvidenceFor(f) ?? []).filter((x) => x.open !== null)) {
      shown.length = 0;
      click(byAttr(c, "data-engine-chip", r.ref.ref)!);
      expect(shown, `${f.id} ${r.ref.ref}`).toEqual([r.open]);
      expect(excerpts(c), `${f.id}: nothing opens inline when a wider surface owns it`).toHaveLength(0);
    }
  });

  it("the header's controls are one tab stop, walked by the arrow keys (a toolbar), so 27 records are not 27 stops", () => {
    const f = [...withRefs].sort((a, b) => (b.evidenceRefs?.length ?? 0) - (a.evidenceRefs?.length ?? 0))[0]!;
    const c = mountAsApp(f.id);
    const bar = c.querySelector<HTMLElement>('[data-engine-index] [role="toolbar"]');
    expect(bar, "a toolbar").not.toBeNull();
    const chips = [...bar!.querySelectorAll<HTMLButtonElement>("button[data-engine-chip]")];
    expect(chips.length).toBeGreaterThan(1);
    expect(chips.filter((b) => b.tabIndex === 0)).toHaveLength(1);
    act(() => chips[0]!.focus());
    press("ArrowRight", {}, chips[0]!);
    expect(document.activeElement).toBe(chips[1]);
    expect(chips.filter((b) => b.tabIndex === 0)).toEqual([chips[1]]);
    press("End", {}, chips[1]!);
    expect(document.activeElement).toBe(chips[chips.length - 1]);
    press("ArrowRight", {}, chips[chips.length - 1]!);
    expect(document.activeElement, "wraps").toBe(chips[0]);
    press("ArrowLeft", {}, chips[0]!);
    expect(document.activeElement).toBe(chips[chips.length - 1]);
    press("Home", {}, chips[chips.length - 1]!);
    expect(document.activeElement).toBe(chips[0]);
  });
});

describe("what the pane says about the engine's contract, on findings the sample does not carry", () => {
  /* Registered in the same map the pane resolves selections through, as EvidencePane.fleetwide.test.tsx does,
     and removed afterwards. Each is built from a REAL finding and its real pointers. */
  const base = withRefs.find((f) => (f.evidenceRefs ?? []).length > 1) ?? null;
  const withFixture = (over: Partial<Finding>, body: (c: HTMLElement) => void): void => {
    expect(base, "precondition: a real finding with more than one pointer").not.toBeNull();
    const fixture: Finding = { ...base!, ...over, id: "FIXTURE-ENGINE" };
    const registry = findingById as Map<string, Finding>;
    registry.set(fixture.id, fixture);
    try {
      body(mountFor(fixture.id).c);
    } finally {
      registry.delete(fixture.id);
    }
  };

  it("the producer's severity basis and evidence confidence are shown where it wrote them, as its words", () => {
    withFixture({ severityBasis: "observed querier state", evidenceConfidence: "evidence confidence NOT published by this snapshot" }, (c) => {
      const head = c.querySelector(".ev__head")?.textContent ?? "";
      expect(head).toContain("Severity basis (the engine's words)");
      expect(head).toContain("observed querier state");
      expect(head).toContain("Evidence confidence (the engine's words)");
      expect(head).toContain("evidence confidence NOT published by this snapshot");
    });
    withFixture({ severityBasis: "", evidenceConfidence: null }, (c) => {
      const head = c.querySelector(".ev__head")?.textContent ?? "";
      expect(head).toContain("an empty statement");
      expect(head).not.toContain("Evidence confidence");
    });
  });

  it("a capped list says it was capped, by how much", () => {
    const n = base!.evidenceRefs!.length;
    withFixture({ evidenceRefsTotal: n + 5 }, (c) => {
      const el = c.querySelector<HTMLElement>("[data-evidence-refs-total]");
      expect(el?.textContent ?? "").toContain(`names ${n} of ${n + 5} records`);
    });
  });

  it("a snapshot with no pointers says so, and falls back to the pane's own matching, labelled as such", () => {
    withFixture({ evidenceRefs: null, evidenceBasis: null }, (c) => {
      expect(c.querySelector("[data-engine-evidence]")).toBeNull();
      expect(c.textContent ?? "").toMatch(/written before the engine published them/);
      expect(c.querySelector('.ev__head [data-evidence-route="engine"]')).toBeNull();
    });
  });

  it("a record past the projection budget is stated as withheld, with its pointer still a working citation", () => {
    const r = base!.evidenceRefs!.find((x) => evidenceRecordAt(x.ref) !== null && !["interface", "acl_line", "route"].includes(x.kind)) ?? null;
    expect(r, "precondition: a pointer whose record is disclosed rather than opened").not.toBeNull();
    const rec = evidenceRecordAt(r!.ref)!;
    const saved = structuredClone(rec);
    try {
      Object.assign(rec, { withheld: true, value: null, nested: [], cut: {} });
      withFixture({ evidenceRefs: [r!], evidenceBasis: "row" }, (c) => {
        const el = c.querySelector<HTMLElement>("[data-evidence-withheld]");
        expect(el, "the withheld record is stated").not.toBeNull();
        expect(el!.textContent ?? "").toMatch(/evidence budget/);
        expect(el!.querySelector("[data-unobserved='true']"), "as not observed, never as an empty record").not.toBeNull();
      });
    } finally {
      Object.assign(rec, saved);
    }
  });

  it("engineEvidenceFor keeps the engine's order and pairs each pointer with its projected record", () => {
    for (const f of withRefs.slice(0, 20)) {
      const e = engineEvidenceFor(f)!;
      expect(e.map((x) => x.ref.ref)).toEqual((f.evidenceRefs ?? []).map((x) => x.ref));
      for (const x of e) expect(x.record?.pointer).toBe(x.ref.ref);
    }
  });
});

/* ══ the golden tier: the census on the tracked reference sample ════════════════════════════════════
   Derived from the regenerated sample's compiled data (2026-09-28) and true ONLY of it; on any other dataset
   these blocks are skipped by name, and a changed sample fails at import (golden-sample.ts). */
describeGolden("A1 census over the regenerated sample: what the engine points at", () => {
  const count = (pred: (f: Finding) => boolean): number => fabric.findings.filter(pred).length;
  const kinds = (f: Finding): Set<string> => new Set((f.evidenceRefs ?? []).map((r) => r.kind));

  it("every one of the 146 findings carries the engine's pointers, and every one reaches them", () => {
    expect(fabric.findings.length).toBe(146);
    expect(withRefs.length).toBe(146);
    expect(count((f) => (f.evidenceRefs ?? []).length === 0)).toBe(0);
  });

  it("the basis split: 58 record, 82 derived from an analysis row, 6 absence", () => {
    expect(count((f) => f.evidenceBasis === "record")).toBe(58);
    expect(count((f) => f.evidenceBasis === "row")).toBe(82);
    expect(count((f) => f.evidenceBasis === "absence")).toBe(6);
  });

  it("55 findings open an interface record the engine names; 3 print configuration text; 6 are witnessed absences", () => {
    expect(count((f) => engineEvidenceFor(f)!.some((r) => r.open !== null))).toBe(55);
    expect(count((f) => kinds(f).has("config_text"))).toBe(3);
    expect(count((f) => kinds(f).has("absence_witness"))).toBe(6);
    // Every record-basis finding has a configuration record to open or text to read; no row or absence one does.
    for (const f of fabric.findings) {
      const config = engineEvidenceFor(f)!.some((r) => r.open !== null || r.ref.kind === "config_text");
      expect(config, f.id).toBe(f.evidenceBasis === "record");
    }
  });

  it("the interactions needed to reach EVERY pointer of a finding, by the acceptance's counting, over the 146", () => {
    /* Measured by the per-finding cases above (so a filtered run, which fills none of them, fails here), over
       the palette route every finding can take whether or not its row is in view: Ctrl+K, the id with Enter,
       the record's control. The worst case is the finding's worst pointer. Re-measured 2026-09-29 after the
       verifier's recount (P3A1-V2-1) found the phase-3 {1:82, 2:33, 3:31} counted selection as one interaction
       for every row and left the move to step 3 uncounted — 30 findings then needed 4. */
    expect(reached.size, "every per-finding case ran").toBe(146);
    const dist: Record<number, number> = {};
    for (const n of reached.values()) dist[n] = (dist[n] ?? 0) + 1;
    expect(dist).toEqual({ 3: 146 });
    // Every pointer instance of every finding was worked, the ones past step 3's fold included.
    expect([...refsWorked.values()].reduce((a, b) => a + b, 0)).toBe(583);
    expect(fabric.findings.filter((f) => (f.evidenceRefs ?? []).length > 8).length, "findings with refs past the step-3 fold").toBe(31);
    for (const id of ["F127", "F129", "F132", "F133", "F135", "F142", "F144", "F145", "F146"])
      expect(reached.get(id), `${id}: a folded-only finding the verifier counted at 4`).toBe(3);
  });

  it("F142's 20 witnesses share the ending of their names, said once: the header stays short enough to read the chain", () => {
    const f = findingById.get("F142")!;
    const refs = engineEvidenceFor(f)!;
    const names = engineRecordNames(refs);
    expect(names.slice(1).every((n) => n.endsWith(" assessed -- none found"))).toBe(true);
    expect(engineNameRuns(refs, names)).toEqual([{ start: 1, end: 21, suffix: " assessed -- none found" }]);
  });

  it("369 distinct pointers, each projected, none withheld by the budget", () => {
    expect(fabric.evidenceRecords?.length).toBe(369);
    expect(fabric.evidenceProjection?.recordsWithheld).toBe(0);
  });

  it("F142 (fleet-wide QoS absence) is witnessed by per-device records, not by configuration", () => {
    const f = findingById.get("F142")!;
    expect(f.devices).toEqual([]);
    expect(f.evidenceBasis).toBe("absence");
    expect(kinds(f).has("absence_witness")).toBe(true);
    expect(engineEvidenceFor(f)!.some((r) => r.open !== null || r.ref.kind === "config_text")).toBe(false);
  });
});
