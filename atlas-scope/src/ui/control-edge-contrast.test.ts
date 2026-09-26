/**
 * control-edge-contrast.test.ts — a BUTTON's drawn edge is a control edge, and control edges use
 * `--border-strong` (>= 3:1 on every surface), never the hairline `--border` (1.38:1 light,
 * 1.46:1 dark — tokens.css says "hairline only, never a control edge").
 *
 * THE DEFECT THIS PINS (independent a11y audit, 2026-09-22, D4, measured on rendered pixels):
 *   the evidence-chain device chips (`.ev-devbtn`, border 1.30:1, fill 1.00:1), "Clear scope"
 *   (`.qbar__clear`, 1.38:1) and the path presets (`.pt-preset__btn`, 1.38:1) drew their only
 *   outline in the hairline token, so the button's shape was invisible against its panel.
 *
 * Stated over the CLASS, not the three names the audit happened to render: every class placed on a
 * `<button>` anywhere in the TSX source is collected, and the base rule for each in every stylesheet
 * must not paint its border in `var(--border)`. A new button styled with the hairline fails here
 * without anyone remembering to add it to a list.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");

const walk = (dir: string, ext: string): string[] =>
  readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return walk(p, ext);
    return p.endsWith(ext) && !/\.test\.tsx?$/.test(p) ? [p] : [];
  });

/** Every literal class on a `<button …>` opening tag (className="a b" and className={cx("a", …)}). */
const buttonClasses = (): Set<string> => {
  const out = new Set<string>();
  for (const f of walk(SRC, ".tsx")) {
    const src = readFileSync(f, "utf8");
    for (const m of src.matchAll(/<button\b[^>]*?className=(?:"([^"]+)"|\{([^}]*)\})/gs)) {
      const literal = m[1] ?? (m[2] ?? "").match(/"[^"]*"/g)?.map((s) => s.slice(1, -1)).join(" ") ?? "";
      for (const c of literal.split(/\s+/)) if (/^[a-z][\w-]*$/.test(c)) out.add(c);
    }
  }
  return out;
};

type Rule = { file: string; selector: string; body: string };
const rules = (): Rule[] =>
  walk(SRC, ".css").flatMap((file) => {
    const css = readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    return [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({
      file: file.slice(SRC.length + 1),
      selector: (m[1] ?? "").trim(),
      body: m[2] ?? "",
    }));
  });

describe("button edges clear the 3:1 non-text floor (D4)", () => {
  it("finds the button classes it is meant to cover", () => {
    const classes = buttonClasses();
    for (const c of ["ev-devbtn", "qbar__clear", "pt-preset__btn"]) expect(classes.has(c)).toBe(true);
  });

  it("no button class draws its edge in the hairline token", () => {
    const classes = buttonClasses();
    const offenders: string[] = [];
    for (const r of rules()) {
      for (const sel of r.selector.split(",").map((s) => s.trim())) {
        const m = /^\.([\w-]+)$/.exec(sel);
        if (!m || !classes.has(m[1] ?? "")) continue;
        if (/border(?:-color)?\s*:[^;]*var\(--border\)/.test(r.body)) offenders.push(`${r.file}: ${sel}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});
