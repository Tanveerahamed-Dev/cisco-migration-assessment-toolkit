/**
 * RecordGrid.tabstop.test.tsx — a record grid is ONE tab stop, whatever its cells render (D1).
 *
 * MEASURED (W6 gate, 2026-09-25; found by the composite-widget census once its cases stopped
 * leaking state): on core1 the Device evidence "Ports" tab rendered grid "Ports on core1" with 31
 * sequential-focus stops and "Endpoints on core1" with 2, and "Routing" rendered "Routing table for
 * core1" with 9 — the roving cell plus every cite button a column's `render` produced. APG: every
 * interactive descendant of a grid cell is `tabindex=-1`, reached from its cell with Enter/F2 and
 * left with Escape/F2.
 *
 * The class is "whatever a column renders", so the fixture renders a button, a link, a field and a
 * control that mounts only after its own state changes — not one named component.
 */
import { act, type ReactNode, useEffect, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { actAsync } from "../test-support/act-turns";
import { afterEach, describe, expect, it } from "vitest";
import { RecordGrid, type GridColumn } from "./DevicePane";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mounted: Root[] = [];
afterEach(() => {
  for (const r of mounted.splice(0)) act(() => r.unmount());
  document.body.innerHTML = "";
});

interface Rec {
  id: string;
}

/** A control that appears only after its own effect runs — a re-render the grid itself never sees. */
function Late({ id }: { id: string }): ReactNode {
  const [shown, setShown] = useState(false);
  useEffect(() => setShown(true), []);
  return shown ? <button type="button">late {id}</button> : <span>…</span>;
}

const columns: GridColumn<Rec>[] = [
  { id: "id", header: "ID", width: "4rem", rowHeader: true, render: (r) => r.id },
  { id: "cite", header: "Evidence", width: "6rem", render: (r) => <button type="button">cite {r.id}</button> },
  { id: "link", header: "Link", width: "6rem", render: (r) => <a href={`#${r.id}`}>open {r.id}</a> },
  { id: "field", header: "Note", width: "6rem", render: (r) => <input aria-label={`note ${r.id}`} /> },
  { id: "late", header: "Late", width: "6rem", render: (r) => <Late id={r.id} /> },
];

const recs = (n: number): Rec[] => Array.from({ length: n }, (_, i) => ({ id: `r${i + 1}` }));

function mount(ui: ReactNode): { c: HTMLElement; render: (ui: ReactNode) => void } {
  const c = document.createElement("div");
  document.body.appendChild(c);
  const root = createRoot(c);
  mounted.push(root);
  act(() => root.render(ui));
  return { c, render: (next) => act(() => root.render(next)) };
}

const grid = (rows: Rec[]): ReactNode => <RecordGrid id="g" label="Records" columns={columns} rows={rows} rowKey={(r) => r.id} />;

/** Sequential-focus stops inside the grid, as the browser counts them. */
const stops = (c: HTMLElement): HTMLElement[] =>
  [...c.querySelectorAll<HTMLElement>("*")].filter((el) => el.tabIndex >= 0 && !(el as HTMLButtonElement).disabled);

/** Deliver pending MutationObserver records: they are microtasks, as in a browser, where they are
 *  delivered before the next task — so before any key a reader can press. */
const flush = (): Promise<void> => actAsync(async () => {});

const keydown = (el: Element, key: string): void =>
  act(() => {
    el.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
  });

describe("RecordGrid holds exactly one tab stop", () => {
  it("whatever its columns render: buttons, links, fields, and a control mounted later", async () => {
    const { c } = mount(grid(recs(4)));
    await flush();
    expect(c.querySelectorAll("button, a[href], input").length, "precondition: the cells hold controls").toBeGreaterThanOrEqual(16);
    expect(stops(c).map((e) => e.textContent || e.getAttribute("aria-label"))).toEqual(["ID"]);
  });

  it("stays one stop when the rows change under it", async () => {
    const { c, render } = mount(grid(recs(2)));
    render(grid(recs(6)));
    await flush();
    expect(stops(c)).toHaveLength(1);
  });

  it("a cell's control is still reachable: Enter steps into it, Escape steps back out", async () => {
    const { c } = mount(grid(recs(2)));
    await flush();
    const cell = c.querySelector<HTMLElement>('[data-r="1"][data-c="1"]')!;
    act(() => cell.focus());
    keydown(cell, "Enter");
    expect(document.activeElement?.textContent).toBe("cite r1");
    keydown(document.activeElement!, "Escape");
    expect(document.activeElement).toBe(cell);
    expect(stops(c)).toHaveLength(1);
  });
});
