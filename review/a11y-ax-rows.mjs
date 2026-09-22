/**
 * a11y-ax-rows.mjs — the live accessibility-tree check for the findings grid.
 *
 * Reads Chromium's full AX tree (CDP Accessibility.getFullAXTree) at load, with no scrolling and no
 * focus, and fails unless every data row exposes its rowheader and no row is unnamed. This is the
 * measurement that caught `content-visibility: auto` on grid rows pruning 76 of 152 rows' cells
 * (2026-09-22). Source-side tripwire: src/panels/DataGrid.a11y-tree.test.ts.
 *
 * Usage: node review/a11y-ax-rows.mjs [url]   (default http://localhost:4180/)
 */
import { chromium } from "playwright";

const url = process.argv[2] || "http://localhost:4180/";
const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1920, height: 1080 } });
const p = await ctx.newPage();
await p.goto(url, { waitUntil: "networkidle" });
await p.waitForSelector(".ag__row--data");
await p.waitForTimeout(3000);
const cdp = await ctx.newCDPSession(p);
const { nodes } = await cdp.send("Accessibility.getFullAXTree");
const role = (n) => n.role?.value;
const rows = nodes.filter((n) => role(n) === "row");
const count = (r) => nodes.filter((n) => role(n) === r).length;
const dataRows = await p.$$eval(".ag__row--data", (e) => e.length);
const out = {
  url,
  rows: rows.length,
  dataRows,
  gridcell: count("gridcell"),
  rowheader: count("rowheader"),
  unnamedRows: rows.filter((n) => !n.name?.value).length,
};
console.log(JSON.stringify(out));
await b.close();
const ok = dataRows > 0 && out.rowheader === dataRows && out.unnamedRows === 0;
if (!ok) {
  console.error("FAIL: grid rows are exposed without their cells (rowheader != dataRows or unnamed rows > 0)");
  process.exit(1);
}
