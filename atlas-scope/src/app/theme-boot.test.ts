/**
 * theme-boot.test.ts — acceptance C4: the FIRST paint is in the reader's theme.
 *
 * THE DEFECT, measured (2026-09-22 grading, light OS, no stored preference, fresh context):
 * `index.html` shipped `<html lang="en" data-theme="dark">`, so the boot line painted dark
 * (`{t:36, boot-line-painted, themeAtCallback:"dark", bg:"rgb(8, 10, 14)"}`) and stayed dark for
 * ~190-330 ms until the application chunk loaded ThemeToggle, whose module-level apply removed the
 * attribute. The hard-coded attribute defeated the rule that "system" means NO attribute (tokens.css
 * keys the OS branch on its absence). It became visible in 254694b, when src/main.tsx started
 * waiting for the boot line to PAINT before importing the application (E5): until then the whole
 * application — ThemeToggle included — evaluated before the browser's first rendering step, so the
 * attribute was already corrected when anything painted.
 *
 * The halves, one owner each:
 *   1. No page ships a theme: every HTML page at the project root (the class — read from the
 *      directory, not a list of three names) has an `<html>` start tag with no `data-theme`.
 *   2. An EXPLICIT stored preference is applied by the entry itself, synchronously, before anything
 *      else it does — so before its wait for the boot line's paint and before `import("./mount")`.
 *      Proven by executing the real `src/main.tsx` in a document with no `#root`: the entry throws
 *      "#root missing" at its first statement after the theme, so the attribute it leaves behind was
 *      set before the application could have been imported.
 *   2b. index.html restates that rule in a classic inline <head> script, because a module entry
 *      runs after parsing and a slow entry fetch let the boot line paint first (measured). The two
 *      are EXECUTED over the same storage states here and must set the same attribute.
 *   3. One reader: no source file other than theme-preference.ts both names the storage key and
 *      reads storage, and the entry and the control import that module.
 *
 * What this cannot show is a real first paint. That is measured in a browser (Element Timing on the
 * boot line, `colorScheme` light and dark, empty and stored preference) — see the wave record.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { THEME_STORAGE_KEY, applyTheme, readThemePreference } from "./theme-preference";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const ROOT = resolve(SRC, "..");

function htmlPages(): string[] {
  return readdirSync(ROOT).filter((n) => n.endsWith(".html") && statSync(join(ROOT, n)).isFile());
}

function htmlStartTag(file: string): string {
  const src = readFileSync(join(ROOT, file), "utf8").replace(/<!--[\s\S]*?-->/g, " ");
  const m = /<html\b[^>]*>/i.exec(src);
  if (!m) throw new Error(`${file} has no <html> start tag`);
  return m[0];
}

describe("C4 half 1: no page ships a hard-coded theme", () => {
  const pages = htmlPages();

  it("finds the pages the dev server and the build serve — an empty scan is not a pass", () => {
    expect(pages).toContain("index.html");
    expect(pages).toContain("fabric-preview.html");
    expect(pages).toContain("panels-preview.html");
  });

  it("no <html> start tag carries data-theme", () => {
    const offenders = pages.filter((p) => /\sdata-theme\s*=/.test(htmlStartTag(p))).map((p) => `${p}: ${htmlStartTag(p)}`);
    expect(
      offenders,
      'A theme in the HTML is painted before any script can read the reader\'s preference, and "system" means NO attribute:\n' +
        offenders.join("\n"),
    ).toEqual([]);
  });

  it("the known-answer case: the check fires on the shape that shipped", () => {
    expect(/\sdata-theme\s*=/.test('<html lang="en" data-theme="dark">')).toBe(true);
    expect(/\sdata-theme\s*=/.test('<html lang="en">')).toBe(false);
  });
});

describe("C4 half 2: src/main.tsx applies an explicit stored preference before anything else", () => {
  let storageSpy: { mockRestore(): void } | null = null;

  beforeEach(() => {
    vi.resetModules();
    document.body.innerHTML = ""; // no #root: the entry must throw right after applying the theme
    document.documentElement.removeAttribute("data-theme");
    try {
      localStorage.clear();
    } catch {
      /* not evidence */
    }
  });

  afterEach(() => {
    storageSpy?.mockRestore();
    storageSpy = null;
    document.documentElement.removeAttribute("data-theme");
    try {
      localStorage.clear();
    } catch {
      /* not evidence */
    }
  });

  for (const stored of ["light", "dark"] as const) {
    it(`a stored '${stored}' is on <html> before the entry reaches #root, its paint wait or ./mount`, async () => {
      localStorage.setItem(THEME_STORAGE_KEY, stored);
      await expect(import("../main")).rejects.toThrow("#root missing");
      expect(document.documentElement.getAttribute("data-theme")).toBe(stored);
    });
  }

  for (const stored of [null, "system", "sepia"] as const) {
    it(`a stored ${JSON.stringify(stored)} means the system theme: no attribute, even over a stale one`, async () => {
      if (stored !== null) localStorage.setItem(THEME_STORAGE_KEY, stored);
      document.documentElement.setAttribute("data-theme", "dark");
      await expect(import("../main")).rejects.toThrow("#root missing");
      expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    });
  }

  it("a browser that refuses storage (SecurityError on access) gets the system theme, not a crash", async () => {
    storageSpy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    document.documentElement.setAttribute("data-theme", "dark");
    await expect(import("../main")).rejects.toThrow("#root missing");
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });
});

describe("C4 half 2b: index.html applies an explicit choice before the FIRST paint, identically to the entry", () => {
  /* WHY THE ENTRY ALONE IS NOT ENOUGH, measured on the release build (vite preview, 2026-09-23):
     with the entry script's fetch delayed 300 ms (a slow network), the boot line painted at 40-44 ms
     in the OS theme for a reader who had explicitly chosen the other one — a module script runs
     after parsing, and the browser may paint the parsed boot line before the module arrives. A
     classic inline script in <head> runs during parsing, so it is ahead of every paint. It cannot
     import the module, so it is a SECOND implementation of one rule — which is exactly what this
     test exists to stop drifting: it executes the page's inline script and the module reader over
     the same storage states and requires the same attribute. */
  const inlineScripts = (): string[] => {
    const html = readFileSync(join(ROOT, "index.html"), "utf8").replace(/<!--[\s\S]*?-->/g, " ");
    return [...html.matchAll(/<script(?![^>]*\bsrc=)(?![^>]*type=["']module["'])[^>]*>([\s\S]*?)<\/script>/g)].map((m) => m[1]!);
  };

  it("index.html carries exactly one classic inline script, in <head>, ahead of every other script and stylesheet", () => {
    const html = readFileSync(join(ROOT, "index.html"), "utf8").replace(/<!--[\s\S]*?-->/g, " ");
    const scripts = inlineScripts();
    expect(scripts).toHaveLength(1);
    const head = html.slice(html.indexOf("<head"), html.indexOf("</head>"));
    const at = head.indexOf(scripts[0]!);
    expect(at, "the pre-paint script must be in <head>").toBeGreaterThan(-1);
    for (const later of [/<script\b[^>]*\bsrc=/, /<link\b[^>]*rel=["']stylesheet/]) {
      const m = later.exec(head);
      if (m) expect(m.index, `${later} must come after the pre-paint script`).toBeGreaterThan(at);
    }
  });

  const cases: readonly (string | null | "THROWS")[] = ["light", "dark", "system", "sepia", "", null, "THROWS"];
  for (const stored of cases) {
    it(`stored ${JSON.stringify(stored)}: the inline script and the entry's reader set the same attribute`, () => {
      const code = inlineScripts()[0] ?? "";
      const spy =
        stored === "THROWS"
          ? vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
              throw new DOMException("blocked", "SecurityError");
            })
          : null;
      try {
        localStorage.clear();
        if (stored !== null && stored !== "THROWS") localStorage.setItem(THEME_STORAGE_KEY, stored);
        document.documentElement.removeAttribute("data-theme");
        // eslint-disable-next-line @typescript-eslint/no-implied-eval
        new Function(code)();
        const inline = document.documentElement.getAttribute("data-theme");
        document.documentElement.removeAttribute("data-theme");
        applyTheme(readThemePreference());
        const entry = document.documentElement.getAttribute("data-theme");
        expect(inline).toBe(entry);
        if (stored === "light" || stored === "dark") expect(inline, "an explicit choice must be applied").toBe(stored);
      } finally {
        spy?.mockRestore();
        document.documentElement.removeAttribute("data-theme");
        localStorage.clear();
      }
    });
  }
});

describe("C4 half 3: one reader of the stored preference", () => {
  it("no source file but theme-preference.ts both names the storage key and reads storage", () => {
    /* The class is "a second READER of the preference" — the thing that lets the entry and the control
       disagree about which theme was asked for. A file that names the key and calls getItem is one,
       whatever it calls its constant. (A write-only duplicate of the key is guarded separately by the
       next test: commands.ts's setTheme now writes through writeThemePreference().) */
    const owners: string[] = [];
    const readers: string[] = [];
    const walk = (dir: string): void => {
      /* The entry's type comes from the directory read itself — no second stat of the path before it is read. */
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const p = join(dir, entry.name);
        if (entry.isDirectory()) walk(p);
        else if (/\.(ts|tsx|mjs|js)$/.test(p) && !/\.test\.(ts|tsx)$/.test(p)) {
          const text = readFileSync(p, "utf8");
          if (!text.includes(THEME_STORAGE_KEY)) continue;
          const rel = relative(SRC, p).split("\\").join("/");
          owners.push(rel);
          if (rel !== "app/theme-preference.ts" && /\bgetItem\s*\(/.test(text)) readers.push(rel);
        }
      }
    };
    walk(SRC);
    expect(owners, "the owner must still hold the key — an empty scan is not a pass").toContain("app/theme-preference.ts");
    expect(readers).toEqual([]);
  });

  it("no source file but theme-preference.ts names the storage key at all — a write-only copy is a second owner", () => {
    /* commands.ts's setTheme once kept its own `THEME_KEY` and its own setItem block. It could not
       change what boot reads, but it was a second place the key could be renamed from, and a
       second policy for a refused write. Writers go through writeThemePreference(). */
    const named: string[] = [];
    const walk = (dir: string): void => {
      /* The entry's type comes from the directory read itself — no second stat of the path before it is read. */
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const p = join(dir, entry.name);
        if (entry.isDirectory()) walk(p);
        else if (/\.(ts|tsx|mjs|js)$/.test(p) && !/\.test\.(ts|tsx)$/.test(p)) {
          if (readFileSync(p, "utf8").includes(THEME_STORAGE_KEY)) named.push(relative(SRC, p).split("\\").join("/"));
        }
      }
    };
    walk(SRC);
    expect(named).toEqual(["app/theme-preference.ts"]);
  });

  it("commands.ts's setTheme writes and applies through the module", () => {
    const text = readFileSync(join(SRC, "app/commands.ts"), "utf8");
    expect(text).toMatch(/import\s*\{[^}]*\bwriteThemePreference\b[^}]*\}\s*from\s*["']\.\/theme-preference["']/);
    expect(text).toMatch(/import\s*\{[^}]*\bapplyTheme\b[^}]*\}\s*from\s*["']\.\/theme-preference["']/);
  });

  it("the entry and the control both read it through that module", () => {
    for (const f of ["main.tsx", "app/ThemeToggle.tsx"]) {
      expect(readFileSync(join(SRC, f), "utf8"), f).toMatch(/from\s+["']\.\/(?:app\/)?theme-preference["']/);
    }
  });
});

describe("C4 half 4: an explicit theme also sets the UA colour scheme", () => {
  /* `:root { color-scheme: light dark }` lets the browser pick its own scrollbars, form controls and
     the Canvas colour by the OS preference. With an explicit [data-theme] opposite to the OS those
     UA-painted parts kept following the OS: a dark page with light scrollbars, and in `vite` dev the
     boot line's Canvas fallback in the wrong theme before tokens load. tokens.css owns color-scheme. */
  const topLevelRules = (): { selector: string; body: string }[] => {
    const css = readFileSync(join(SRC, "core/tokens.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, " ");
    const out: { selector: string; body: string }[] = [];
    let depth = 0;
    let start = 0;
    let selector = "";
    for (let i = 0; i < css.length; i++) {
      const c = css[i];
      if (c === "{") {
        if (depth === 0) {
          selector = css.slice(start, i).trim();
          start = i + 1;
        }
        depth++;
      } else if (c === "}") {
        depth--;
        if (depth === 0) {
          out.push({ selector, body: css.slice(start, i) });
          start = i + 1;
        }
      }
    }
    return out;
  };

  for (const theme of ["dark", "light"] as const) {
    it(`an unconditional [data-theme="${theme}"] rule sets color-scheme: ${theme}`, () => {
      const rules = topLevelRules().filter(
        (r) => !r.selector.startsWith("@") && r.selector.split(",").some((s) => s.trim() === `[data-theme="${theme}"]`),
      );
      const schemes = rules.flatMap((r) => [...r.body.matchAll(/(?:^|[;{\s])color-scheme\s*:\s*([^;]+);/g)].map((m) => m[1]!.trim()));
      expect(schemes, `tokens.css: [data-theme="${theme}"] must pin the UA colour scheme`).toContain(theme);
    });
  }

  it("the print block still wins: it comes after the explicit-theme rules at the same specificity", () => {
    const css = readFileSync(join(SRC, "core/tokens.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, " ");
    const print = css.indexOf("@media print");
    expect(print).toBeGreaterThan(-1);
    for (const theme of ["dark", "light"]) {
      const at = css.search(new RegExp(String.raw`\[data-theme="${theme}"\]\s*\{[^}]*color-scheme`));
      expect(at, theme).toBeGreaterThan(-1);
      expect(at, `[data-theme="${theme}"] color-scheme must precede @media print`).toBeLessThan(print);
    }
  });
});
