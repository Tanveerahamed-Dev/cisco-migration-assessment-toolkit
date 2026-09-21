/**
 * announcement-single-owner.test.tsx — one message, one live region.
 *
 * THE DEFECT THIS PINS, as measured in the running application:
 *
 *   Every global status message was placed into TWO simultaneously-updating polite live regions.
 *   `useCommandAnnouncement()` fed `#sr-status` in App.tsx AND a `<LiveRegion>` inside
 *   ShortcutHelp, which stays mounted whether or not the shortcuts sheet is open. Pressing `m`
 *   wrote the identical refusal sentence into both in the same tick; a screen reader read it
 *   twice, and a reader cannot tell a double announcement from two separate events.
 *
 * Two assertions, at two different levels, because either one alone is escapable:
 *
 *   1. SOURCE — the number of modules that subscribe to the announcement is pinned at one. A
 *      second subscriber is how the defect returns, whatever it chooses to render. This is a
 *      count, not a list of forbidden filenames: any new subscriber trips it.
 *   2. RUNTIME — the always-mounted keyboard layer is mounted for real, a unique sentence is
 *      announced, and its subtree is searched for ANY `aria-live` node carrying that text. That
 *      catches a reintroduction written some other way (a raw div, a different primitive).
 *
 * The one owner is `#sr-status` in App.tsx, beside `sr-alert` and `sr-log`, which already have
 * exactly one owner each — this makes the third one obey the same rule.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, extname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { announce, installAppCommands } from "./commands";
import { ShortcutHelp } from "./ShortcutHelp";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

/* ── source scan ─────────────────────────────────────────────────────────── */

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if ([".ts", ".tsx"].includes(extname(p)) && !p.includes(".test.")) out.push(p);
  }
  return out;
}

const rel = (f: string): string => relative(SRC, f).split("\\").join("/");

describe("the command announcement has exactly one live region", () => {
  const files = walk(SRC);

  it("scans the source tree — an empty scan is not a pass", () => {
    expect(files.length).toBeGreaterThan(20);
    expect(files.some((f) => rel(f) === "app/App.tsx")).toBe(true);
    expect(files.some((f) => rel(f) === "app/ShortcutHelp.tsx")).toBe(true);
  });

  it("is subscribed to by one module, and that module is the owner", () => {
    const subscribers = files
      .filter((f) => rel(f) !== "app/commands.ts") // where the hook is DEFINED
      .filter((f) => /useCommandAnnouncement\s*\(/.test(readFileSync(f, "utf8")))
      .map(rel)
      .sort();

    expect(
      subscribers,
      `every module here renders the same command announcement into a live region of its own, so\n` +
        `a screen reader reads each message once PER subscriber. There must be exactly one, and it\n` +
        `is #sr-status in App.tsx. Found: ${subscribers.join(", ") || "(none — the announcement is now unreachable)"}`,
    ).toEqual(["app/App.tsx"]);
  });

  it("is rendered by App.tsx into the region the design brief names", () => {
    /* The owner is only an owner if it actually renders it: a subscriber that dropped its region
       would leave the count at one and announce nothing at all. */
    const app = readFileSync(join(SRC, "app/App.tsx"), "utf8");
    expect(app).toMatch(/id="sr-status"[\s\S]{0,200}\{status\}/);
  });
});

/* ── runtime ─────────────────────────────────────────────────────────────── */

const mounted: { root: Root; container: HTMLElement }[] = [];
const teardown: (() => void)[] = [];

function mount(ui: ReactNode): HTMLElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(ui));
  mounted.push({ root, container });
  return container;
}

afterEach(() => {
  for (const t of teardown.splice(0)) t();
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
});

describe("the always-mounted keyboard layer announces nothing itself", () => {
  it("carries no live region of its own when a command announces", () => {
    teardown.push(installAppCommands());
    const c = mount(<ShortcutHelp />);
    const unique = "announcement-single-owner probe sentence";
    act(() => announce(unique));

    const carriers = [...c.querySelectorAll("[aria-live]")].filter((n) =>
      (n.textContent ?? "").includes(unique),
    );
    expect(
      carriers.map((n) => `${n.tagName}.${n.className}`),
      `ShortcutHelp is mounted for the whole session, open or not. A live region here is a SECOND\n` +
        `region carrying what #sr-status already carries, and every message is read out twice.`,
    ).toEqual([]);
  });
});
