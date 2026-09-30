/**
 * palette-warm.mjs — the one wait every settle-gated harness takes for the command palette's pre-warm.
 *
 * After the scene converges, `src/app/CommandPalette.tsx` draws the palette's frame ONCE at opacity
 * 0.001 for at least WARM_MIN_HOLD_MS and WARM_HOLD_FRAMES presented frames (that raster carries a
 * one-time GPU program compile, measured at ~120 ms), then PARKS it (visibility:hidden, inert, no
 * roles) until the first Ctrl+K. It publishes its phase on `<html data-palette-warm>`:
 *   waiting | scheduled | mounted            — still ahead of, or inside, the drawn window;
 *   done | unpresented | superseded          — terminal: nothing more is drawn by the pre-warm.
 * A capture taken inside the drawn window can differ by one 8-bit step, and a timed action taken
 * inside it pays the compile. So a harness that waits for the scene to settle before photographing
 * or timing anything also waits for a terminal pre-warm phase. `src/core/palette-warm-harness.test.ts`
 * derives that class from the harness sources (every one that reads the scene's `converged`) and
 * holds each to this module, and pins PALETTE_WARM_TERMINAL to the component's own state type.
 *
 * NOT in the class, on purpose: `audit-e5-coldload.mjs` (the pre-warm is part of the cold load it
 * measures) and `measure-inp.mjs` (it records the phase at every press and reports overlapping reps
 * apart rather than waiting them away).
 *
 * The wait is bounded (15 s by default) and FAILS LOUDLY with the phase it last saw: a pre-warm that
 * never reaches a terminal phase is a finding, never silently photographed through.
 */

import { pathToFileURL } from "node:url";

/** The phases after which the pre-warm draws nothing more. */
export const PALETTE_WARM_TERMINAL = Object.freeze(["done", "unpresented", "superseded"]);

/** Default bound on the wait, in ms. */
export const PALETTE_WARM_WAIT_MS = 15000;

/**
 * Wait until `<html data-palette-warm>` reads a terminal phase. Throws, naming the last phase seen
 * (or "absent"), when it does not within `timeoutMs`.
 * @param {import("@playwright/test").Page} page
 * @param {number} [timeoutMs]
 * @returns {Promise<string>} the terminal phase reached
 */
export async function awaitPaletteWarm(page, timeoutMs = PALETTE_WARM_WAIT_MS) {
  const terminal = [...PALETTE_WARM_TERMINAL];
  try {
    const handle = await page.waitForFunction(
      (t) => {
        const s = document.documentElement.dataset.paletteWarm;
        return s !== undefined && t.includes(s) ? s : false;
      },
      terminal,
      { timeout: timeoutMs },
    );
    return String(await handle.jsonValue());
  } catch (err) {
    const seen = await page
      .evaluate(() => document.documentElement.dataset.paletteWarm ?? "absent")
      .catch(() => "unreadable");
    throw new Error(
      `the command palette's pre-warm did not reach a terminal phase (${terminal.join("/")}) within ` +
        `${timeoutMs} ms; last phase: ${seen} (${err instanceof Error ? err.message.split("\n")[0] : String(err)})`,
    );
  }
}

/* ── the parked palette opens ON TOP (acceptance D1, WCAG 2.4.11; verifier R6 round 1, V4) ─────────
 *
 * The pre-warm parks the palette's frame in <body> long before its first open. MEASURED (verifier
 * round 2, E2/E3, 2026-09-27, release build, 1280x800): with the keyboard reference open, the first
 * Ctrl+K drew that parked palette UNDER the reference, its search box focused and out of sight, and one
 * Escape closed both. The dialog stack (src/ui/primitives.tsx) now decides paint order from the order
 * dialogs were opened; its jsdom sweeps pin attributes, and this is the RENDERED half: the procedure a
 * browser audit runs (review/audit-d3-focus.mjs is its intended durable caller) and a CLI that runs it
 * on its own.
 *
 * PAINT ORDER, NOT HIT TESTING. Chromium does not hit-test inert nodes, so `elementFromPoint` looks
 * straight THROUGH an inert dialog painted over the focused control — a probe built that way passed on
 * the broken build. Every dialog scrim and panel covering the focused control's centre (body children,
 * fixed, in the root stacking context) is ranked by computed z-index, then DOM order.
 */

/**
 * The box painted on top among `boxes` (each `{ z, index }`: computed z-index and DOM order among the
 * body's children), or null when there is none. A later DOM position wins a z-index tie. Pure.
 * @template {{ z: number, index: number }} B
 * @param {readonly B[]} boxes
 * @returns {B | null}
 */
export function topmostByPaint(boxes) {
  let top = null;
  for (const b of boxes) if (top === null || b.z > top.z || (b.z === top.z && b.index > top.index)) top = b;
  return top;
}

/** In the page: the focused control, and every visible dialog scrim/panel covering its centre. */
const STACK_STATE = () => {
  const a = document.activeElement;
  const body = [...document.body.children];
  const dialogs = [...document.querySelectorAll('.ui-dialog[role="dialog"]')].map((p) => ({
    cls: String(p.className),
    layer: p.getAttribute("data-dialog-layer"),
    inert: p.closest("[inert]") !== null,
    insideInert: p.querySelectorAll("[inert]").length,
  }));
  let covering = [];
  if (a && a !== document.body) {
    const r = a.getBoundingClientRect();
    const x = r.left + Math.min(r.width / 2, 20);
    const y = r.top + r.height / 2;
    covering = body
      .filter((el) => el.matches(".ui-dialog, .ui-dialog__scrim"))
      .filter((el) => getComputedStyle(el).visibility !== "hidden" && Number(getComputedStyle(el).opacity) > 0.01)
      .filter((el) => {
        const b = el.getBoundingClientRect();
        return x >= b.left && x <= b.right && y >= b.top && y <= b.bottom;
      })
      .map((el) => ({ label: `${el.tagName.toLowerCase()}.${el.className}`, z: Number(getComputedStyle(el).zIndex) || 0, index: body.indexOf(el), holdsFocus: el.contains(a) }));
  }
  return {
    active: a ? `${a.tagName.toLowerCase()}.${a.className}` : null,
    activeIn: a?.closest(".ui-dialog")?.className ?? null,
    activeInert: a ? a.closest("[inert]") !== null : null,
    covering,
    dialogs,
    layers: document.querySelectorAll("[data-dialog-layer]").length,
    inertOutsidePrewarm: [...document.querySelectorAll("[inert]")].filter((e) => !e.closest("[data-dialog-prewarm]")).length,
  };
};

/**
 * Whether the focused control is inside a dialog whose class names `want`, live, and inside the box
 * painted on top of every dialog box covering it. Pure over a STACK_STATE reading.
 * @param {{ covering: { z: number, index: number, holdsFocus: boolean }[], activeInert: boolean | null, activeIn: string | null }} s
 * @param {string} want
 */
export function focusedOnTop(s, want) {
  const top = topmostByPaint(s.covering);
  return top !== null && top.holdsFocus && s.activeInert === false && (s.activeIn ?? "").split(/\s+/).includes(want);
}

/**
 * The D1 procedure on a loaded app page: wait for the palette's frame to park, open the keyboard
 * reference with a click, press the FIRST Ctrl+K over it, then Escape once, then a second Ctrl+K, then
 * close everything. Returns every failed condition, each in words ([] when the stack held), and the
 * states it read.
 * @param {import("@playwright/test").Page} page
 * @returns {Promise<{ failures: string[], states: Record<string, unknown> }>}
 */
export async function checkPaletteOverDialog(page) {
  const failures = [];
  const states = {};
  states.warm = await awaitPaletteWarm(page, 90000);
  states.parked = await page.evaluate(() => document.querySelector('.ui-dialog[data-dialog-prewarm="parked"]') !== null);
  if (!states.parked) failures.push(`the palette's frame was not parked before the first Ctrl+K (pre-warm ${states.warm}), so the parked open was not tested`);
  await page.getByRole("button", { name: "Keyboard reference" }).first().click();
  await page.waitForSelector('.ui-dialog.kb-help[role="dialog"]');
  await page.keyboard.press("Control+k");
  await page.waitForSelector('.ui-dialog.palette[role="dialog"]');
  await page.waitForTimeout(400);
  const first = (states.firstOpenOverHelp = await page.evaluate(STACK_STATE));
  if (!focusedOnTop(first, "palette"))
    failures.push(`first Ctrl+K over the keyboard reference: the focused control is not the palette's, live, on top (top: ${JSON.stringify(topmostByPaint(first.covering))})`);
  if (first.dialogs.some((d) => /\bpalette\b/.test(d.cls) && d.insideInert > 0)) failures.push("first Ctrl+K: a node inside the open palette is inert");
  await page.keyboard.press("Escape");
  await page.waitForTimeout(400);
  const back = (states.afterOneEscape = await page.evaluate(STACK_STATE));
  if (back.dialogs.length !== 1) failures.push(`one Escape left ${back.dialogs.length} dialog(s) open; it must close the palette alone`);
  if (!focusedOnTop(back, "kb-help")) failures.push("after one Escape: focus is not back in the keyboard reference, live and on top");
  if (back.inertOutsidePrewarm === 0) failures.push("after one Escape: the page behind the keyboard reference, still open, is not inert");
  await page.keyboard.press("Control+k");
  await page.waitForSelector('.ui-dialog.palette[role="dialog"]');
  await page.waitForTimeout(400);
  const again = (states.secondOpenOverHelp = await page.evaluate(STACK_STATE));
  if (!focusedOnTop(again, "palette")) failures.push("second Ctrl+K over the keyboard reference: the palette is not on top with focus");
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");
  await page.waitForTimeout(400);
  const closed = (states.allClosed = await page.evaluate(STACK_STATE));
  if (closed.dialogs.length !== 0 || closed.layers !== 0 || closed.inertOutsidePrewarm !== 0)
    failures.push(`with every dialog closed: ${closed.dialogs.length} open, ${closed.layers} layer(s), ${closed.inertOutsidePrewarm} node(s) left inert`);
  return { failures, states };
}

/* ── the app's modal dialogs, discovered by the RENDERED primitive (independent verifier R6 VR2-3) ──────
 * Both the D1 pair sweep (src/app/CommandPalette.test.tsx) and the D3 rung-crossing pass
 * (review/audit-d3-focus.mjs) need "every modal dialog the app can open". They used to find it with the
 * regex /<Dialog\b/ over the source — the modules that SPELL `<Dialog`. A module rendering the exported
 * `<DialogFrame` directly, an aliased import (`import { Dialog as Modal }`), a namespace member
 * (`<ui.Dialog>`), `createElement(Dialog, …)`, or an inline `role="dialog" aria-modal="true"` element was
 * invisible to it, so the set was "modules that spell <Dialog", not "dialogs the app can open".
 *
 * THE RULE, read from the syntax tree of every non-test .ts/.tsx under the root:
 *   1. A MODAL ELEMENT is an intrinsic JSX element (lower-case tag) that is given `role` "dialog" or
 *      "alertdialog" and an `aria-modal` that is not literally false — as a JSX attribute, or as a property of
 *      an object spread into it (DialogFrame spreads `{ role: "dialog", "aria-modal": "true" }`) — or a native
 *      `<dialog>`, which is modal when shown with showModal() and carries no aria-modal at all: it counts
 *      unless its module never calls showModal() AND renders it `open` or calls show() (independent verifier
 *      QH-V1-6: both kinds were outside the census).
 *   2. A component (a function declaration, or a const bound to an arrow/function) that renders a modal
 *      element, or a DIALOG PRIMITIVE, is a dialog component. A tag or `createElement` argument is resolved
 *      through the module's own declarations and const aliases, named/default/aliased imports, and
 *      namespace members, to the component it names — never by its spelling.
 *   3. A dialog component whose accessible name comes from ITS CALLER — it takes a `title` (a destructured
 *      parameter property, or `props.title`) — is a PRIMITIVE: Dialog, DialogFrame, and any wrapper that
 *      forwards a title. One that names the dialog itself is an OWNER: a dialog the app opens.
 * A component that merely MOUNTS an owner (App renders <CommandPalette />) renders no primitive and no
 * modal element, so it is neither. `aria-modal="false"` (a popover, the status bar's coverage panel) is not
 * a modal dialog. Returns the owners (module-relative file and component) and the primitives.
 * @param {Record<string, string>} files  module path relative to the root ("app/X.tsx") -> source text
 * @returns {Promise<{ owners: { file: string, component: string }[], primitives: { file: string, component: string }[] }>}
 */
export async function modalDialogsIn(files) {
  const ts = (await import("typescript")).default;
  const posix = (p) => p.split("\\").join("/");
  const norm = (p) => {
    const out = [];
    for (const part of posix(p).split("/")) {
      if (part === "" || part === ".") continue;
      if (part === "..") out.pop();
      else out.push(part);
    }
    return out.join("/");
  };
  const resolveModule = (from, spec) => {
    if (!spec.startsWith(".")) return null;
    const base = norm(`${from.split("/").slice(0, -1).join("/")}/${spec}`);
    for (const c of [base, `${base}.tsx`, `${base}.ts`, `${base}/index.tsx`, `${base}/index.ts`]) if (c in files) return c;
    return null;
  };
  /** Per module: its components (name -> function node), import bindings, const aliases and export names. */
  const mods = new Map();
  for (const [file, text] of Object.entries(files)) {
    const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
    const components = new Map();
    const imports = new Map(); /* local -> { module, name } ; name "*" = namespace */
    const aliases = new Map(); /* local const -> the expression it is bound to */
    const exported = new Map(); /* exported name -> local name */
    const reexports = new Map(); /* exported name -> { module, name } */
    const starFrom = []; /* modules re-exported whole */
    for (const st of sf.statements) {
      if (ts.isImportDeclaration(st) && ts.isStringLiteral(st.moduleSpecifier) && st.importClause !== undefined) {
        const target = resolveModule(file, st.moduleSpecifier.text);
        if (target === null) continue;
        const c = st.importClause;
        if (c.name !== undefined) imports.set(c.name.text, { module: target, name: "default" });
        const nb = c.namedBindings;
        if (nb !== undefined && ts.isNamespaceImport(nb)) imports.set(nb.name.text, { module: target, name: "*" });
        if (nb !== undefined && ts.isNamedImports(nb)) for (const e of nb.elements) imports.set(e.name.text, { module: target, name: (e.propertyName ?? e.name).text });
      }
      const isExported = ts.canHaveModifiers(st) && (ts.getModifiers(st) ?? []).some((m) => m.kind === ts.SyntaxKind.ExportKeyword);
      const isDefault = ts.canHaveModifiers(st) && (ts.getModifiers(st) ?? []).some((m) => m.kind === ts.SyntaxKind.DefaultKeyword);
      if (ts.isFunctionDeclaration(st) && st.name !== undefined) {
        components.set(st.name.text, st);
        if (isExported) exported.set(isDefault ? "default" : st.name.text, st.name.text);
      }
      if (ts.isVariableStatement(st)) {
        for (const d of st.declarationList.declarations) {
          if (!ts.isIdentifier(d.name) || d.initializer === undefined) continue;
          let init = d.initializer;
          while (ts.isParenthesizedExpression(init) || ts.isAsExpression(init) || ts.isSatisfiesExpression(init)) init = init.expression;
          /* memo(fn) / forwardRef(fn): the component is the function inside. */
          if (ts.isCallExpression(init) && init.arguments.length > 0 && (ts.isArrowFunction(init.arguments[0]) || ts.isFunctionExpression(init.arguments[0]))) init = init.arguments[0];
          if (ts.isArrowFunction(init) || ts.isFunctionExpression(init)) components.set(d.name.text, init);
          else aliases.set(d.name.text, init);
          if (isExported) exported.set(d.name.text, d.name.text);
        }
      }
      if (ts.isExportAssignment(st) && ts.isIdentifier(st.expression)) exported.set("default", st.expression.text);
      if (ts.isExportDeclaration(st) && st.moduleSpecifier === undefined && st.exportClause !== undefined && ts.isNamedExports(st.exportClause))
        for (const e of st.exportClause.elements) exported.set(e.name.text, (e.propertyName ?? e.name).text);
      /* `export { X as Y } from "./m"` and `export * from "./m"`: resolved in the module they come from. */
      if (ts.isExportDeclaration(st) && st.moduleSpecifier !== undefined && ts.isStringLiteral(st.moduleSpecifier)) {
        const target = resolveModule(file, st.moduleSpecifier.text);
        if (target === null) continue;
        if (st.exportClause === undefined) starFrom.push(target);
        else if (ts.isNamedExports(st.exportClause)) for (const e of st.exportClause.elements) reexports.set(e.name.text, { module: target, name: (e.propertyName ?? e.name).text });
      }
    }
    mods.set(file, { sf, components, imports, aliases, exported, reexports, starFrom });
  }
  const key = (file, name) => `${file}#${name}`;
  /** The component key an expression (a JSX tag, or createElement's first argument) names, or null. */
  const resolveExpr = (file, expr, seen = new Set()) => {
    const m = mods.get(file);
    if (m === undefined) return null;
    if (ts.isIdentifier(expr)) {
      const name = expr.text;
      if (seen.has(key(file, name))) return null;
      const next = new Set([...seen, key(file, name)]);
      if (m.components.has(name)) return key(file, name);
      if (m.aliases.has(name)) return resolveExpr(file, m.aliases.get(name), next);
      const imp = m.imports.get(name);
      if (imp !== undefined && imp.name !== "*") return resolveExport(imp.module, imp.name, next);
      return null;
    }
    if (ts.isPropertyAccessExpression(expr) && ts.isIdentifier(expr.expression)) {
      const imp = m.imports.get(expr.expression.text);
      if (imp !== undefined && imp.name === "*") return resolveExport(imp.module, expr.name.text, seen);
    }
    if (ts.isParenthesizedExpression(expr) || ts.isAsExpression(expr)) return resolveExpr(file, expr.expression, seen);
    return null;
  };
  const resolveExport = (file, name, seen) => {
    const m = mods.get(file);
    if (m === undefined) return null;
    const local = m.exported.get(name) ?? (name !== "default" && m.components.has(name) ? name : undefined);
    if (local !== undefined) return resolveExpr(file, ts.factory.createIdentifier(local), seen);
    const guard = `${file}#export:${name}`;
    if (seen.has(guard)) return null;
    const next = new Set([...seen, guard]);
    const re = m.reexports.get(name);
    if (re !== undefined) return resolveExport(re.module, re.name, next);
    for (const star of m.starFrom) {
      const k = resolveExport(star, name, next);
      if (k !== null) return k;
    }
    return null;
  };
  const literal = (e) => {
    if (e === undefined) return true; /* `<div aria-modal>` */
    if (ts.isStringLiteral(e) || ts.isNoSubstitutionTemplateLiteral(e)) return e.text;
    if (ts.isJsxExpression(e)) return e.expression === undefined ? undefined : literal(e.expression);
    if (ts.isAsExpression(e) || ts.isParenthesizedExpression(e) || ts.isSatisfiesExpression(e)) return literal(e.expression);
    if (e.kind === ts.SyntaxKind.TrueKeyword) return true;
    if (e.kind === ts.SyntaxKind.FalseKeyword) return false;
    return undefined; /* not knowable: an expression */
  };
  /** The role and aria-modal an intrinsic element is given, from attributes and spread object literals. */
  const modalOf = (attrs) => {
    let role;
    let modal;
    const fromObject = (o) => {
      for (const p of o.properties) {
        if (ts.isPropertyAssignment(p)) {
          const n = ts.isIdentifier(p.name) || ts.isStringLiteral(p.name) ? p.name.text : null;
          if (n === "role") role = literal(p.initializer) ?? role;
          if (n === "aria-modal") modal = literal(p.initializer);
        } else if (ts.isSpreadAssignment(p)) visitSpread(p.expression);
      }
    };
    const visitSpread = (e) => {
      if (ts.isObjectLiteralExpression(e)) fromObject(e);
      else if (ts.isConditionalExpression(e)) {
        visitSpread(e.whenTrue);
        visitSpread(e.whenFalse);
      } else if (ts.isParenthesizedExpression(e)) visitSpread(e.expression);
      else if (ts.isBinaryExpression(e)) {
        visitSpread(e.left);
        visitSpread(e.right);
      }
    };
    for (const a of attrs.properties) {
      if (ts.isJsxAttribute(a)) {
        const n = a.name.getText();
        if (n === "role") role = literal(a.initializer) ?? role;
        if (n === "aria-modal") modal = literal(a.initializer);
      } else if (ts.isJsxSpreadAttribute(a)) visitSpread(a.expression);
    }
    /* `alertdialog` is a dialog by the same contract (independent verifier QH-V1-6). */
    return (role === "dialog" || role === "alertdialog") && modal !== false && modal !== "false" && modal !== null;
  };
  /** Whether a module calls a member named `name` anywhere (`ref.current?.showModal()`, `d.show()`). */
  const callsMember = (sf, name) => {
    const find = (n) =>
      (ts.isCallExpression(n) && ts.isPropertyAccessExpression(n.expression) && n.expression.name.text === name) ||
      (ts.forEachChild(n, find) ?? false);
    return find(sf);
  };
  /** A NATIVE <dialog> (QH-V1-6): modal when shown with showModal() — no aria-modal attribute at all. It is non-modal
   *  only on evidence: its module never calls showModal(), and it is rendered `open` or its module calls show(). */
  const nativeModal = (file, attrs) => {
    const sf = mods.get(file).sf;
    if (callsMember(sf, "showModal")) return true;
    const open = attrs.properties.some((a) => ts.isJsxAttribute(a) && a.name.getText() === "open" && literal(a.initializer) !== false);
    return !(open || callsMember(sf, "show"));
  };
  /** Per component: whether it renders a modal element, which components it renders, whether it takes a title. */
  const facts = new Map();
  for (const [file, m] of mods) {
    for (const [name, fn] of m.components) {
      const renders = new Set();
      let modal = false;
      const visit = (n) => {
        if (ts.isJsxElement(n) || ts.isJsxSelfClosingElement(n)) {
          const open = ts.isJsxElement(n) ? n.openingElement : n;
          const tag = open.tagName;
          if (ts.isIdentifier(tag) && /^[a-z]/.test(tag.text)) {
            if (modalOf(open.attributes) || (tag.text === "dialog" && nativeModal(file, open.attributes))) modal = true;
          } else {
            const k = resolveExpr(file, tag);
            if (k !== null) renders.add(k);
          }
        }
        if (ts.isCallExpression(n) && n.arguments.length > 0) {
          const callee = n.expression;
          const nm = ts.isIdentifier(callee) ? callee.text : ts.isPropertyAccessExpression(callee) ? callee.name.text : "";
          if (nm === "createElement" || nm === "jsx" || nm === "jsxs") {
            const k = resolveExpr(file, n.arguments[0]);
            if (k !== null) renders.add(k);
          }
        }
        ts.forEachChild(n, visit);
      };
      visit(fn);
      const p0 = fn.parameters[0];
      let takesTitle = false;
      if (p0 !== undefined && ts.isObjectBindingPattern(p0.name)) takesTitle = p0.name.elements.some((e) => (e.propertyName ?? e.name).getText() === "title");
      else if (p0 !== undefined && ts.isIdentifier(p0.name)) {
        const pn = p0.name.text;
        const find = (n) => (ts.isPropertyAccessExpression(n) && ts.isIdentifier(n.expression) && n.expression.text === pn && n.name.text === "title") || (ts.forEachChild(n, find) ?? false);
        takesTitle = find(fn.body ?? fn);
      }
      facts.set(key(file, name), { file, component: name, renders, modal, takesTitle });
    }
  }
  /* Primitives: the least fixed point of "takes a title, and renders a modal element or a primitive". */
  const primitives = new Set();
  for (let changed = true; changed; ) {
    changed = false;
    for (const [k, f] of facts) {
      if (primitives.has(k) || !f.takesTitle) continue;
      if (f.modal || [...f.renders].some((r) => primitives.has(r))) {
        primitives.add(k);
        changed = true;
      }
    }
  }
  const owners = [...facts]
    .filter(([k, f]) => !primitives.has(k) && (f.modal || [...f.renders].some((r) => primitives.has(r))))
    .map(([, f]) => ({ file: f.file, component: f.component }));
  const pick = (ks) => [...ks].map((k) => facts.get(k)).map((f) => ({ file: f.file, component: f.component }));
  const byName = (a, b) => (a.file + a.component).localeCompare(b.file + b.component);
  return { owners: owners.sort(byName), primitives: pick(primitives).sort(byName) };
}

/**
 * modalDialogsIn over every non-test .ts/.tsx module under `srcDir` (a directory URL or path), keyed by
 * its path relative to `srcDir`.
 * @param {string | URL} srcDir
 */
export async function appModalDialogs(srcDir) {
  const { readdirSync, readFileSync } = await import("node:fs");
  const { join, relative } = await import("node:path");
  const { fileURLToPath } = await import("node:url");
  const root = typeof srcDir === "string" ? srcDir : fileURLToPath(srcDir);
  const files = {};
  const walk = (dir) => {
    /* The entry's type comes from the directory read itself — no second stat of the path before it is read. */
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const name = entry.name;
      if (name === "node_modules") continue;
      const p = join(dir, name);
      if (entry.isDirectory()) walk(p);
      else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) && !name.endsWith(".d.ts")) files[relative(root, p).split("\\").join("/")] = readFileSync(p, "utf8");
    }
  };
  walk(root);
  return modalDialogsIn(files);
}

/* `node review/palette-warm.mjs --dialog-stack [url]`: the D1 procedure at 1280x800, dark and light,
   against a release preview (default http://localhost:4181). Exit 0 only when both legs held. Imported,
   this module runs nothing. */
const IS_MAIN = typeof process.argv[1] === "string" && import.meta.url === pathToFileURL(process.argv[1]).href;
if (IS_MAIN && process.argv.includes("--dialog-stack")) {
  const url = process.argv.find((a) => /^https?:\/\//.test(a)) ?? "http://localhost:4181";
  const { chromium } = await import("@playwright/test");
  const browser = await chromium.launch();
  let failed = 0;
  try {
    for (const colorScheme of ["dark", "light"]) {
      const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, colorScheme });
      const page = await ctx.newPage();
      await page.goto(url.replace(/\/$/, "") + "/");
      await page.waitForSelector("canvas", { timeout: 30000 });
      const { failures, states } = await checkPaletteOverDialog(page).catch((e) => ({ failures: [`the procedure threw: ${String(e).split("\n")[0]}`], states: {} }));
      failed += failures.length;
      console.log(`1280x800 ${colorScheme}: ${failures.length === 0 ? "the most recently opened dialog held the top layer" : failures.join("; ")}`);
      console.log(JSON.stringify(states));
      await ctx.close();
    }
  } finally {
    await browser.close();
  }
  console.log(failed === 0 ? "D1 RENDERED: HELD (2 of 2 legs)" : `D1 RENDERED: BROKEN (${failed} failed condition(s))`);
  process.exit(failed === 0 ? 0 : 1);
}
