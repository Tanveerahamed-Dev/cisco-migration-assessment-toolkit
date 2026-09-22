/**
 * capture.mjs — deterministic screenshot harness for the visual-review loop.
 *
 * Four jobs:
 *   1. `node review/capture.mjs app`    — capture Atlas Scope in a fixed set of investigation states.
 *   2. `node review/capture.mjs refs`   — capture the quality-bar reference products.
 *   3. `node review/capture.mjs reduced`— the `prefers-reduced-motion` evidence (acceptance D7).
 *   4. `node review/capture.mjs twice`  — capture, re-capture, byte-compare (acceptance F6).
 *
 * Determinism matters more than convenience here: a critic comparing two runs must be looking at a
 * difference we made, not at a layout that reshuffled. So: fixed viewport, fixed deviceScaleFactor,
 * animations disabled at capture time, web fonts awaited, and the app's own layout seeded.
 */
import { createHash } from "node:crypto";
import { mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const HERE = dirname(fileURLToPath(import.meta.url));
const SHOTS = resolve(HERE, "shots");
/* The default is the PREVIEW build (`npm run preview`, :4181), not the dev server (:4180). The two
   render the same state differently — 27 of 32 frames differed in bytes between them (audit F6,
   2026-09-21) — so a frame taken from the dev server does not show what ships. Whatever server is
   used, its mode is detected and written into every index.json record (see serverIdentity). */
const APP = process.env.ATLAS_URL || "http://localhost:4181";

/**
 * Which kind of server produced the frames. Vite's dev server injects `/@vite/client` into the
 * page it serves; a production build never contains it. Read from the served HTML itself rather
 * than from the port number, so a build served on :4180 (or a dev server on :4181) is named
 * correctly. "unknown" when the page could not be read: stated, never guessed as "build".
 */
async function serverIdentity(url = APP) {
  try {
    const res = await fetch(url + "/");
    const html = await res.text();
    const mode = !res.ok ? "unknown" : html.includes("/@vite/client") ? "dev" : "build";
    return { url, mode };
  } catch (e) {
    return { url, mode: "unknown", error: String(e).slice(0, 200) };
  }
}

function announceServer(server) {
  console.log(`server: ${server.url} (${server.mode})`);
  if (server.mode !== "build") {
    console.log(
      `  WARNING: these frames are NOT from the shipped build (mode=${server.mode}). ` +
        "Run `npm run build && npm run preview` and capture against :4181 for evidence of what ships.",
    );
  }
}

/**
 * The investigation states a reviewer must see. Each is a URL the store can rehydrate from, using
 * the grammar in src/core/store.ts :: encodeInvestigation.
 *
 * Every parameter below was verified against the real compiled data, not assumed:
 *   - `core1` is a real inventoried host and the one host whose ACLs we hold.
 *   - `F001` is a real Critical finding ("CR-01: End-of-support keystone") on core1.
 *   - tcp/3389 to 10.0.30.10 is genuinely DENIED by acls.core1.PROTECT_SERVERS[3]; tcp/443 on the
 *     same pair is DELIVERED. An earlier version of this file used 443 for the "blocked" state,
 *     which would have shown a critic a successful trace under a screenshot named "blocked".
 */
const APP_STATES = [
  { id: "01-fabric-overview", q: "", note: "First paint: the whole fabric, nothing selected." },
  { id: "02-device-selected", q: "d=core1&s=fabric", note: "A device selected — evidence pane populated." },
  { id: "03-finding-drill", q: "s=findings&sev=CH", note: "Priority queue filtered to Critical+High." },
  { id: "04-finding-evidence", q: "s=findings&f=F001&d=core1&tab=raw", note: "Finding to its configuration evidence." },
  { id: "05-path-trace", q: "s=path", note: "Path trace surface, before a flow is run." },
  {
    id: "06-path-blocked",
    q: "s=path&flow=10.0.10.50>10.0.30.10>tcp>3389&hop=0",
    note:
      "A genuinely denied flow: the blocking-hop answer, naming PROTECT_SERVERS line 4 of 4 (acls.core1.PROTECT_SERVERS[3]). " +
      "On the fabric the trace is a BLOCKED verdict marker on core1 only — the trace is single-hop, so no path geometry between devices is drawn (acceptance A5).",
  },
  {
    id: "08-path-indeterminate",
    q: "s=path&flow=10.0.40.50>10.0.30.10>tcp>443&hop=0",
    note: "A flow reaching dist1, which has no collected RIB — the honest 'I cannot tell you' state.",
  },
  { id: "07-evidence-raw", q: "s=evidence&d=core1&tab=raw", note: "Raw inspectable evidence, Grafana-style." },
];

const VIEWPORTS = [
  { id: "1920", width: 1920, height: 1080 },
  { id: "1440", width: 1440, height: 900 },
];

const THEMES = ["dark", "light"];

/** Reference products. `wait` gives JS apps time to settle; `note` tells the critic what it is. */
const REFS = [
  { id: "forward-getting-started", url: "https://www.forwardnetworks.com/getting-started/", wait: 6000 },
  { id: "forward-demo-a", url: "https://app.storylane.io/demo/ts9nkc4osn4z?embed=inline", wait: 12000 },
  { id: "forward-demo-b", url: "https://app.storylane.io/demo/jdhoywyw5voi?embed=inline", wait: 12000 },
  { id: "ipfabric-network-viewer", url: "https://docs.ipfabric.io/latest/IP_Fabric_GUI/diagrams/network_viewer/", wait: 6000 },
  { id: "ipfabric-path-lookup", url: "https://docs.ipfabric.io/latest/IP_Fabric_GUI/diagrams/how_to_use_path-lookup/", wait: 6000 },
  { id: "linear-custom-views", url: "https://linear.app/docs/custom-views", wait: 6000 },
  { id: "linear-display-options", url: "https://linear.app/docs/display-options", wait: 6000 },
  { id: "grafana-play", url: "https://play.grafana.org/", wait: 14000 },
  { id: "grafana-explore-inspector", url: "https://grafana.com/docs/grafana/latest/explore/explore-inspector/", wait: 6000 },
  { id: "batfish-fwd-validation", url: "https://batfish.readthedocs.io/en/latest/notebooks/linked/introduction-to-forwarding-change-validation.html", wait: 6000 },
  { id: "apg-data-grid", url: "https://www.w3.org/WAI/ARIA/apg/patterns/grid/examples/data-grids/", wait: 4000 },
];

const FREEZE_CSS = `
  *, *::before, *::after {
    animation-duration: 0s !important;
    animation-delay: 0s !important;
    transition-duration: 0s !important;
    transition-delay: 0s !important;
    caret-color: transparent !important;
  }
`;

async function shoot(page, file, { fullPage = false } = {}) {
  mkdirSync(dirname(file), { recursive: true });
  await page.screenshot({ path: file, fullPage, animations: "disabled", scale: "device" });
  return file;
}

/**
 * Decide whether a captured state is worth showing a critic.
 *
 * A blank or half-rendered frame costs a whole review round: three critics spend their effort
 * describing an accident rather than the design, and their fault lists are then worthless. So each
 * capture is checked for actual content before it is admitted, and anything that fails is reported
 * LOUDLY rather than written into index.json as if it were our work.
 */
async function verifyRendered(page, state) {
  return page.evaluate((st) => {
    const problems = [];
    const root = document.getElementById("root");
    if (!root) problems.push("no #root");
    const text = (document.body.innerText || "").trim();
    if (text.length < 120) problems.push(`only ${text.length} chars of visible text`);
    if (/error|failed to fetch|cannot read|undefined is not/i.test(text.slice(0, 600)))
      problems.push("an error message is on screen");
    // A surface that should show the fabric must actually have a canvas with pixels behind it.
    if (st.id.includes("fabric") || st.id.includes("device")) {
      const c = document.querySelector("canvas");
      if (!c) problems.push("no <canvas> on a fabric surface");
      else if (c.width < 200 || c.height < 200) problems.push(`canvas is ${c.width}x${c.height}`);
    }
    // A path state must have produced a verdict, not an empty form.
    if (st.id.includes("path-blocked") || st.id.includes("path-indeterminate")) {
      if (!/denied|indeterminate|dropped|delivered|out of scope/i.test(text))
        problems.push("no forwarding verdict rendered");
    }
    return problems;
  }, state);
}

/* ── C2/C3/D4: clipped and broken text ───────────────────────────────────────────────────────
 *
 * WHY THIS EXISTS. `verifyRendered` asks whether a frame has content. It never asked whether that
 * content can be READ, so the 2026-09-22 acceptance pass found, on frames this harness had recorded
 * as `problems: []`: the DECIDED BY citation squeezed into a two-character column ("co / ll / ec"),
 * prose broken mid-word ("collecte / d for"), the ORDER label cut to "Ranked: severity, th", the
 * findings-row titles cut to their rule-ID prefix ("CR-03: Ro…"), and the palette's "<Esc> close"
 * hint painted 15 px past the dialog onto the backdrop — where its container still reported
 * `scrollWidth == clientWidth`, so an overflow check on the CONTAINER could not see it either.
 *
 * So the check is made per TEXT, from the glyph boxes the browser actually laid out (a Range over
 * each text node), against every box that can hide or strand them. It reports four kinds:
 *
 *   clipped   — a text's glyphs extend past the box its hiding ancestors leave (overflow
 *               hidden/clip, per axis: an ellipsis clips x, a line clamp clips y), and more of its
 *               line length is lost than TEXT_LIMITS allows: maxHiddenShare (20 %) for a text cut
 *               to ONE visible line, maxHiddenShareWrapped (50 %) for one given two or more visible
 *               lines. An ellipsis is the same loss with a courtesy glyph: "CR-03: Ro…" hid ~80 %
 *               of its title. The share is stated, not zero, because an ellipsis on a long
 *               identifier that keeps most of it is a design choice; one that keeps a prefix is not.
 *               Text painted BY a control rather than laid out as a node — a closed <select>'s
 *               chosen option, an empty field's placeholder — is measured with the control's font
 *               against its content box (that is where "Ranked: severity, th" was cut).
 *               Wholly off-screen text (an off-canvas label, a row scrolled away) is not clipped.
 *   escaped   — glyphs painted OUTSIDE the nearest ancestor that paints its own background (the
 *               surface the text was designed against) while still on screen: the D4 palette hint.
 *               Its contrast was measured against the wrong background, because it is on one.
 *   column    — a text that wraps inside a column narrower than TEXT_LIMITS.minColumnCh characters.
 *   mid-word  — a natural-language word (letters only) broken across lines with no hyphen. A word
 *               only breaks when its column cannot hold it, so this is the same fault seen from the
 *               word's side ("collecte / d").
 *   mid-identifier — the same break inside an IDENTIFIER: a token carrying `_ . / : -` or digits
 *               ("(num_power_supplie / s)", 2026-09-22 acceptance C2). This file used to exempt
 *               identifiers ("may legitimately wrap anywhere"), so `overflow-wrap: anywhere` on a
 *               prose block could split a config key between two letters and the check, scoped to
 *               letters-only words, could not see it by construction. An identifier may break only
 *               at a `_ . / -` boundary or not at all (owner: src/ui/primitives.css); a break with a
 *               letter or digit on BOTH sides is never that.
 *
 * Scrolled-away content is not "clipped": a list or a horizontal scroll region hides content the
 * reader can reach. That is a different invariant, checked for the one surface where it is a
 * defect — the permanent coverage line (B7, `readCoverageVisibility`).
 *
 * Self-contained: it is serialised into the page, so it may reference nothing outside itself.
 */
const TEXT_LIMITS = { maxHiddenShare: 0.2, maxHiddenShareWrapped: 0.5, minColumnCh: 8, maxFindings: 40 };

function readTextFidelity(L) {
  const findings = [];
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const ctx = document.createElement("canvas").getContext("2d");
  const zeroWidth = (cs) => {
    ctx.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    return ctx.measureText("0").width || parseFloat(cs.fontSize) * 0.55;
  };
  const selectorOf = (el) => {
    const parts = [];
    for (let n = el; n && n !== document.body && parts.length < 4; n = n.parentElement) {
      let s = n.tagName.toLowerCase();
      if (n.id) {
        parts.unshift(`${s}#${n.id}`);
        break;
      }
      const cls = [...n.classList].slice(0, 2);
      if (cls.length) s += "." + cls.join(".");
      parts.unshift(s);
    }
    return parts.join(" > ");
  };
  /* Visually hidden (the screen-reader-only idiom), not rendered, or transparent: not a text a
     sighted reader sees, so it cannot be a clipped one. */
  const hiddenFromSight = (el) => {
    for (let n = el; n; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (cs.display === "none" || cs.visibility === "hidden" || cs.visibility === "collapse") return true;
      if (parseFloat(cs.opacity) === 0) return true;
      if (/inset\(50%\)/.test(cs.clipPath) || cs.clip === "rect(0px, 0px, 0px, 0px)") return true;
      const r = n.getBoundingClientRect();
      if (r.width <= 1 && r.height <= 1 && cs.overflow !== "visible") return true;
    }
    return false;
  };
  const paintsSurface = (cs) => {
    const m = cs.backgroundColor.match(/rgba?\(([^)]+)\)/);
    if (!m) return cs.backgroundImage !== "none";
    const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
    return (p.length < 4 ? 1 : p[3]) >= 0.5;
  };
  const snippet = (t) => (t.length > 80 ? `${t.slice(0, 77)}...` : t);

  const byElement = new Map();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let t = walker.nextNode(); t; t = walker.nextNode()) {
    if (!t.nodeValue || !t.nodeValue.trim()) continue;
    const el = t.parentElement;
    if (!el || el.closest("script,style,noscript,svg,canvas")) continue;
    if (!byElement.has(el)) byElement.set(el, []);
    byElement.get(el).push(t);
  }

  for (const [el, nodes] of byElement) {
    if (findings.length >= L.maxFindings) break;
    const box = el.getBoundingClientRect();
    if (box.width <= 0 || box.height <= 0) continue;
    if (box.right <= 0 || box.left >= vw || box.bottom <= 0 || box.top >= vh) continue;
    if (hiddenFromSight(el)) continue;
    const cs = getComputedStyle(el);
    const text = nodes.map((n) => n.nodeValue).join("").replace(/\s+/g, " ").trim();
    /* The text a reader would recognise: the element's own, or its parent's when that is a
       fragment (a keycap label, a prefix span). */
    const own = el.textContent.replace(/\s+/g, " ").trim();
    const fullText = own.length >= 12 || !el.parentElement ? own : el.parentElement.textContent.replace(/\s+/g, " ").trim();

    /* Glyph boxes, one per line fragment, from the layout itself. */
    const range = document.createRange();
    const rects = [];
    for (const n of nodes) {
      range.selectNodeContents(n);
      for (const r of range.getClientRects()) if (r.width > 0 && r.height > 0) rects.push(r);
    }
    if (rects.length === 0) continue;
    /* One extent per LINE. Chrome reports an ellipsised text as two overlapping fragments (the laid
       out run and the painted one), so summing fragments double-counts; the union per line does not. */
    const lines = [];
    for (const r of rects) {
      const line = lines.find((l) => Math.abs(l.top - r.top) < 2);
      if (line) {
        line.left = Math.min(line.left, r.left);
        line.right = Math.max(line.right, r.right);
      } else lines.push({ top: r.top, bottom: r.bottom, left: r.left, right: r.right });
    }
    const textWidth = lines.reduce((a, l) => a + (l.right - l.left), 0);

    /* The clipping and surface ancestors, nearest first. A scroll container is not a clip
       (see the header), and it ends the search for a clip: beyond it the content is reachable. */
    /* The box the text can be seen through: the intersection of every ancestor that hides overflow,
       per axis (an ellipsis clips x; a line clamp clips y). The walk stops at a scroll container:
       beyond it the content is reachable (see the header). */
    let clipL = -Infinity;
    let clipR = Infinity;
    let clipT = -Infinity;
    let clipB = Infinity;
    let clipper = null;
    let selfLost = 0;
    let surface = null;
    let scrolled = false;
    /* The PAINT box: what reaches the screen at all, through every clipping ancestor, scrollers
       included. Only used to decide what a reader can see; the loss above stops at a scroller. */
    let paintL = 0;
    let paintR = vw;
    let paintT = 0;
    let paintB = vh;
    for (let a = el; a && a !== document.documentElement; a = a.parentElement) {
      const acs = a === el ? cs : getComputedStyle(a);
      if (surface === null && a !== el && paintsSurface(acs)) surface = a;
      /* `overflow` does not apply to an inline box, so an inline ancestor clips nothing. */
      if (acs.display === "inline" || acs.display === "contents") continue;
      const ox = acs.overflowX;
      const oy = acs.overflowY;
      if (ox !== "visible" || oy !== "visible") {
        const pb = a.getBoundingClientRect();
        if (ox !== "visible") {
          paintL = Math.max(paintL, pb.left + a.clientLeft);
          paintR = Math.min(paintR, pb.left + a.clientLeft + a.clientWidth);
        }
        if (oy !== "visible") {
          paintT = Math.max(paintT, pb.top + a.clientTop);
          paintB = Math.min(paintB, pb.top + a.clientTop + a.clientHeight);
        }
      }
      if (ox === "auto" || ox === "scroll" || oy === "auto" || oy === "scroll") scrolled = true;
      if (scrolled) continue;
      const hx = ox === "hidden" || ox === "clip";
      const hy = oy === "hidden" || oy === "clip";
      if (!hx && !hy) continue;
      const ab = a.getBoundingClientRect();
      const left = ab.left + a.clientLeft;
      const top = ab.top + a.clientTop;
      if (hx && (left > clipL || left + a.clientWidth < clipR)) {
        clipL = Math.max(clipL, left);
        clipR = Math.min(clipR, left + a.clientWidth);
        clipper = clipper ?? a;
      }
      if (hy && (top > clipT || top + a.clientHeight < clipB)) {
        clipT = Math.max(clipT, top);
        clipB = Math.min(clipB, top + a.clientHeight);
        clipper = clipper ?? a;
      }
      /* An ellipsis is painted by the clipping box itself, so its own scrollWidth is the width of
         the text it cut, whatever the Range reports. */
      if (a === el && hx) selfLost = Math.max(0, el.scrollWidth - el.clientWidth);
    }
    /* Not shown at all (wholly outside what is painted: an off-canvas label, a row scrolled away)
       is not clipped text; it is simply not on screen. */
    const onScreen = lines.some((l) => {
      const mid = (l.top + l.bottom) / 2;
      return mid >= paintT && mid <= paintB && Math.min(l.right, paintR) - Math.max(l.left, paintL) > 1;
    });
    if (!onScreen) continue;
    let visible = 0;
    let visibleLines = 0;
    for (const l of lines) {
      const mid = (l.top + l.bottom) / 2;
      if (mid < clipT || mid > clipB) continue;
      const w = Math.max(0, Math.min(l.right, clipR) - Math.max(l.left, clipL));
      if (w > 0) visibleLines++;
      visible += w;
    }
    const clipped = Math.max(textWidth - visible, selfLost);
    const hiddenShare = textWidth > 0 ? clipped / textWidth : 0;
    /* A text given two or more visible lines has been given a reading budget, and is judged by the
       looser share; one cut to a single line is judged by the strict one. */
    const limit = visibleLines >= 2 ? L.maxHiddenShareWrapped : L.maxHiddenShare;
    if (hiddenShare > limit && clipped > 2) {
      findings.push({
        kind: "clipped",
        selector: selectorOf(el),
        clippedBy: clipper === el ? "itself" : clipper ? selectorOf(clipper) : "-",
        text: snippet(fullText),
        detail: `${Math.round(hiddenShare * 100)}% of the text is hidden (${Math.round(clipped)} of ${Math.round(textWidth)} px of line length, ${visibleLines} line(s) visible; limit ${Math.round(limit * 100)}%)`,
      });
    }

    /* Escaped onto a surface it was not designed against. Only the part a reader can see counts:
       inside the viewport, and not already hidden by a clip or scroller. */
    if (surface !== null) {
      const sb = surface.getBoundingClientRect();
      let out = 0;
      for (const r of lines) {
        const mid = (r.top + r.bottom) / 2;
        if (mid < paintT || mid > paintB) continue;
        const l = Math.max(r.left, paintL);
        const rr = Math.min(r.right, paintR);
        if (rr <= l) continue;
        out += Math.max(0, Math.min(rr, sb.left) - l) + Math.max(0, rr - Math.max(l, sb.right));
      }
      if (out > 2) {
        findings.push({
          kind: "escaped",
          selector: selectorOf(el),
          surface: selectorOf(surface),
          text: snippet(fullText),
          detail: `${Math.round(out)} px of glyphs painted outside the surface behind them (its contrast is against a different background)`,
        });
      }
    }

    /* Wrapping: distinct line tops. */
    if (lines.length >= 2) {
      const tops = lines;
      const ch = zeroWidth(cs);
      const column = Math.max(...lines.map((l) => l.right - l.left));
      if (column < L.minColumnCh * ch && text.length > L.minColumnCh) {
        findings.push({
          kind: "column",
          selector: selectorOf(el),
          text: snippet(fullText),
          detail: `wraps into ${tops.length} lines no wider than ${(column / ch).toFixed(1)} characters (limit ${L.minColumnCh})`,
        });
      } else {
        /* Find each line break inside the text and ask whether it split a TOKEN: two letters or
           digits on either side of the break, with no space, hyphen or separator between them.
           A plain word ("collecte / d") and an identifier ("num_power_supplie / s)",
           "10.0.1 / 0.50") are both tokens; they are reported as different kinds because they
           have different owners (prose wraps at spaces; an identifier may break only at a
           `_ . / -` boundary, or not at all — src/ui/primitives.css). `hyphens: auto` licenses
           a hyphenated break inside a plain word only, never inside an identifier. */
        for (const n of nodes) {
          const s = n.nodeValue;
          if (s.length > 600) continue;
          let prevTop = null;
          for (let i = 0; i < s.length; i++) {
            if (/\s/.test(s[i])) continue;
            range.setStart(n, i);
            range.setEnd(n, i + 1);
            const r = range.getClientRects()[0];
            if (!r) continue;
            const top = Math.round(r.top);
            if (prevTop !== null && top > prevTop + 2 && i > 0 && /[\p{L}\p{N}]/u.test(s[i - 1]) && /[\p{L}\p{N}]/u.test(s[i])) {
              /* The token: the whitespace-free run around the break, less wrapping punctuation. */
              const tokStart = s.slice(0, i).search(/\S+$/u);
              const tokEnd = i + (s.slice(i).match(/^\S+/u)?.[0].length ?? 0);
              const token = s.slice(tokStart, tokEnd).replace(/^[("'‘“\[{<]+|[)"'’”\]}>,;:!?.]+$/gu, "");
              const identifier = /[_.\/:\d-]/u.test(token) || !/^\p{L}+$/u.test(token);
              if (!identifier && cs.hyphens === "auto") {
                prevTop = top;
                continue;
              }
              findings.push({
                kind: identifier ? "mid-identifier" : "mid-word",
                selector: selectorOf(el),
                text: snippet(fullText),
                detail: `the ${identifier ? "identifier" : "word"} "${token}" is broken across lines as "${s.slice(tokStart, i)} / ${s.slice(i, tokEnd)}" (line tops ${prevTop}, ${top}; overflow-wrap ${cs.overflowWrap}, word-break ${cs.wordBreak})`,
              });
              break;
            }
            prevTop = top;
          }
        }
      }
    }
  }
  /* A closed <select> paints its chosen option inside its own box, and that text is not a text
     node in the layout (an <option>'s Range has no rects), so the walk above cannot see it. This is
     where the ORDER label "Ranked: severity, th" was cut. Measured with the control's own font
     against its content box. */
  /* The same holds for an empty text field's placeholder: painted by the control, not a node. */
  for (const sel of document.querySelectorAll("select, input:placeholder-shown, textarea:placeholder-shown")) {
    if (findings.length >= L.maxFindings) break;
    const box = sel.getBoundingClientRect();
    if (box.width <= 0 || box.right <= 0 || box.left >= vw || box.bottom <= 0 || box.top >= vh) continue;
    if (sel.multiple || sel.size > 1 || hiddenFromSight(sel)) continue;
    const isSelect = sel.tagName === "SELECT";
    const opt = isSelect ? sel.selectedOptions[0] : null;
    if (isSelect && !opt) continue;
    if (!isSelect && (sel.tagName === "TEXTAREA" || !sel.placeholder)) continue;
    const cs = getComputedStyle(sel);
    ctx.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    const shown = isSelect ? opt.label || opt.text : sel.placeholder;
    const need = ctx.measureText(shown).width;
    const room = sel.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    const lost = need - room;
    if (lost > 2 && lost / need > L.maxHiddenShare) {
      findings.push({
        kind: "clipped",
        selector: selectorOf(sel),
        clippedBy: isSelect ? "itself (select)" : "itself (placeholder)",
        text: snippet(shown),
        detail: `${Math.round((lost / need) * 100)}% of the ${isSelect ? "selected option" : "placeholder"}'s width is hidden (${Math.round(lost)} of ${Math.round(need)} px; limit ${Math.round(L.maxHiddenShare * 100)}%)`,
      });
    }
  }
  return findings;
}
const READ_TEXT_FIDELITY = `(${readTextFidelity.toString()})(${JSON.stringify(TEXT_LIMITS)})`;

/**
 * C2: no tab is hidden off its strip. Measured 2026-09-22 at 1440: the Device-pane tab strip had
 * scrollWidth 427 against clientWidth 379, and its Raw tab sat at x1440-1488 against an innerWidth of
 * 1440, i.e. past the pane edge with nothing on screen saying there was more. `readTextFidelity`
 * cannot see that: the tab's label is not clipped by a hiding ancestor, it is simply off-screen,
 * and off-screen text is (correctly) not "clipped text".
 *
 * So, per `[role=tablist]` a reader can see: if its content is wider than its box
 * (scrollWidth > clientWidth), there must be a VISIBLE overflow affordance, which here means a
 * horizontal scroll container whose scrollbar actually takes space (`scrollbar-width: none` or an
 * overflow of hidden/clip/visible does not count). Independently, every tab must lie inside the
 * viewport horizontally unless it is inside such a scroller. Self-contained; serialised into the page.
 */
function readTabOverflow() {
  const out = [];
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const seen = (el) => {
    for (let n = el; n; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (cs.display === "none" || cs.visibility === "hidden" || parseFloat(cs.opacity) === 0) return false;
    }
    return el.getClientRects().length > 0;
  };
  for (const list of document.querySelectorAll('[role="tablist"]')) {
    if (!seen(list)) continue;
    const r = list.getBoundingClientRect();
    if (r.width <= 0 || r.bottom <= 0 || r.top >= vh || r.right <= 0 || r.left >= vw) continue;
    const cs = getComputedStyle(list);
    const label = list.getAttribute("aria-label") || list.id || list.className || "tablist";
    const scroller = cs.overflowX === "auto" || cs.overflowX === "scroll";
    const bar = list.offsetHeight - list.clientHeight - parseFloat(cs.borderTopWidth) - parseFloat(cs.borderBottomWidth);
    const affordance = scroller && bar > 0;
    const tabs = [...list.querySelectorAll('[role="tab"]')].filter(seen);
    const past = tabs.filter((t) => {
      const b = t.getBoundingClientRect();
      return b.right > Math.min(vw, r.right) + 0.5 || b.left < Math.max(0, r.left) - 0.5;
    });
    const names = (ts) => ts.map((t) => `"${(t.textContent || "").replace(/\s+/g, " ").trim()}" ${Math.round(t.getBoundingClientRect().left)}-${Math.round(t.getBoundingClientRect().right)}`).join(", ");
    if (list.scrollWidth > list.clientWidth + 1 && !affordance) {
      out.push(
        `tablist "${label}" overflows with no visible affordance: scrollWidth ${list.scrollWidth} > clientWidth ${list.clientWidth} ` +
          `(overflow-x ${cs.overflowX}, scrollbar ${Math.max(0, bar)} px, innerWidth ${vw})` + (past.length ? `; hidden tabs ${names(past)}` : ""),
      );
    } else if (past.length && !affordance) {
      out.push(`tablist "${label}" paints tabs outside its box / the viewport (innerWidth ${vw}): ${names(past)}`);
    }
  }
  return out;
}
const READ_TAB_OVERFLOW = `(${readTabOverflow.toString()})()`;

/**
 * B7: the coverage denominators are PERMANENTLY visible — at every viewport, not only the two the
 * capture set photographs. Measured 2026-09-22 at 390x844: "ACLs 1/26" sat at x369-418 in a
 * horizontally scrolling status bar, i.e. off-screen until the reader scrolled a bar they had no
 * reason to know scrolls. "In the DOM" and "inside a scroll region" are not visible; each
 * denominator must lie wholly inside the viewport AND inside every ancestor that can hide it
 * (a scroll container included — here scrolled-away IS the defect), and must be the element
 * found at its own centre (nothing painted over it). Self-contained; serialised into the page.
 */
function readCoverageVisibility() {
  const out = [];
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const group = document.querySelector('#status-bar [aria-label="Collection coverage"]');
  if (!group) return [{ label: "(coverage group)", problem: "no coverage group in #status-bar" }];
  const items = [...group.querySelectorAll("button")];
  if (items.length === 0) return [{ label: "(coverage group)", problem: "no coverage denominators" }];
  for (const b of items) {
    const label = (b.textContent || "").replace(/\s+/g, " ").trim();
    const r = b.getBoundingClientRect();
    let left = 0;
    let right = vw;
    let top = 0;
    let bottom = vh;
    for (let a = b.parentElement; a && a !== document.documentElement; a = a.parentElement) {
      const cs = getComputedStyle(a);
      if (cs.overflowX !== "visible" || cs.overflowY !== "visible") {
        const ab = a.getBoundingClientRect();
        left = Math.max(left, ab.left + a.clientLeft);
        right = Math.min(right, ab.left + a.clientLeft + a.clientWidth);
        top = Math.max(top, ab.top + a.clientTop);
        bottom = Math.min(bottom, ab.top + a.clientTop + a.clientHeight);
      }
    }
    const inView = r.width > 0 && r.left >= left - 0.5 && r.right <= right + 0.5 && r.top >= top - 0.5 && r.bottom <= bottom + 0.5;
    /* An open MODAL dialog makes the page behind it inert on purpose and dims it with a scrim:
       the figures are still visible through it, and being under the scrim is not being hidden. */
    const modal = [...document.querySelectorAll('[aria-modal="true"]')].some((m) => m.getClientRects().length > 0);
    const hit = document.elementFromPoint(Math.min(vw - 1, Math.max(0, r.left + r.width / 2)), Math.min(vh - 1, Math.max(0, r.top + r.height / 2)));
    const onTop = modal || (hit !== null && (hit === b || b.contains(hit)));
    if (!inView || !onTop) {
      out.push({
        label,
        problem: `${!inView ? `not wholly visible (@x${Math.round(r.left)}-${Math.round(r.right)} y${Math.round(r.top)}-${Math.round(r.bottom)}; visible box x${Math.round(left)}-${Math.round(right)} y${Math.round(top)}-${Math.round(bottom)})` : ""}${!inView && !onTop ? "; " : ""}${!onTop ? `covered by ${hit ? hit.tagName.toLowerCase() + (hit.className ? "." + String(hit.className).split(" ")[0] : "") : "nothing (off-screen)"}` : ""}`,
      });
    }
  }
  return out;
}
const READ_COVERAGE_VISIBILITY = `(${readCoverageVisibility.toString()})()`;

/**
 * D4, MEASURED: the contrast of every text under `root`, from computed colours against the
 * background actually composited under each text's glyphs — the stack `elementsFromPoint` returns
 * at the glyph run's centre, alpha-composited bottom-up over the canvas — not against the token the
 * CSS intended. That distinction is the whole D4 finding: the palette hint's tokens pass on the
 * dialog surface, and it measured 1.37:1 because it had escaped onto the scrim. Background IMAGES
 * (the not-observed hatch) are not composited; an element carrying one is reported as such rather
 * than measured as if it were flat. Self-contained; serialised into the page.
 */
function readContrast(rootSelector) {
  const parse = (c) => {
    const m = String(c).match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
    return { r: p[0], g: p[1], b: p[2], a: p.length < 4 ? 1 : p[3] };
  };
  const over = (top, bottom) => {
    const a = top.a + bottom.a * (1 - top.a);
    if (a === 0) return { r: 0, g: 0, b: 0, a: 0 };
    const mix = (t, b) => (t * top.a + b * bottom.a * (1 - top.a)) / a;
    return { r: mix(top.r, bottom.r), g: mix(top.g, bottom.g), b: mix(top.b, bottom.b), a };
  };
  const lum = ({ r, g, b }) => {
    const f = (v) => {
      const c = v / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const hex = ({ r, g, b }) => "#" + [r, g, b].map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");
  const out = [];
  const root = document.querySelector(rootSelector);
  if (!root) return [{ selector: rootSelector, error: "not found" }];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const seen = new Set();
  for (let t = walker.nextNode(); t; t = walker.nextNode()) {
    if (!t.nodeValue.trim()) continue;
    const el = t.parentElement;
    if (seen.has(el)) continue;
    seen.add(el);
    const range = document.createRange();
    range.selectNodeContents(t);
    const r = range.getBoundingClientRect();
    if (r.width === 0) continue;
    const x = r.left + r.width / 2;
    const y = r.top + r.height / 2;
    const cs = getComputedStyle(el);
    let fg = parse(cs.color);
    let opacity = 1;
    for (let a = el; a; a = a.parentElement) opacity *= parseFloat(getComputedStyle(a).opacity);
    const stack = document.elementsFromPoint(x, y);
    let bg = { r: 255, g: 255, b: 255, a: 1 };
    const canvas = parse(getComputedStyle(document.documentElement).backgroundColor);
    const bodyBg = parse(getComputedStyle(document.body).backgroundColor);
    if (canvas && canvas.a > 0) bg = over(canvas, bg);
    if (bodyBg && bodyBg.a > 0) bg = over(bodyBg, bg);
    let image = null;
    for (const e of [...stack].reverse()) {
      const ecs = getComputedStyle(e);
      const c = parse(ecs.backgroundColor);
      if (c && c.a > 0) bg = over({ ...c, a: c.a * parseFloat(ecs.opacity) }, bg);
      if (ecs.backgroundImage !== "none" && e.contains(el)) image = e.className || e.tagName;
    }
    fg = over({ ...fg, a: fg.a * opacity }, bg);
    const L1 = lum(fg);
    const L2 = lum(bg);
    const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
    out.push({
      text: el.textContent.trim().slice(0, 40),
      selector: el.className ? `${el.tagName.toLowerCase()}.${String(el.className).split(" ")[0]}` : el.tagName.toLowerCase(),
      fg: hex(fg),
      bg: hex(bg),
      top: stack[0] === el || el.contains(stack[0]) || stack[0]?.contains(el) ? "self" : stack[0]?.className || stack[0]?.tagName,
      ratio: Math.round(ratio * 100) / 100,
      fontPx: parseFloat(cs.fontSize),
      ...(image ? { backgroundImage: image } : {}),
    });
  }
  return out;
}

/** One problem line per finding, so a failing frame names every element it failed on. */
function describeTextFindings(findings) {
  return findings.map(
    (f) => `text ${f.kind}: ${f.selector}${f.clippedBy ? ` (clipped by ${f.clippedBy})` : ""}${f.surface ? ` (surface ${f.surface})` : ""} "${f.text}" — ${f.detail}`,
  );
}

/**
 * Launch flags that get us a REAL GPU rather than SwiftShader.
 *
 * This matters more than it looks. The 3-D subsystem probes the renderer and picks a quality tier
 * from what it finds; on SwiftShader it correctly selects `low`, which switches off bloom and SSAO.
 * Capturing with default flags therefore photographs a deliberately degraded render — and the blind
 * comparison would then be judging our low tier against another product's full one, which is not a
 * comparison at all. `--use-gl=angle` routes through the platform GPU (D3D11 on this host).
 */
/*
 * WHY DOM RASTER IS ON THE CPU (`--disable-gpu-rasterization`) — the F6 "alternate frame" (R15).
 *
 * WebGL does not depend on this flag: `--use-gl=angle` still gives the fabric the real GPU (the
 * tier is still observed as `high` on every frame, and the harness fails closed if it is not).
 * The flag chooses how CHROME rasterizes the page's own tiles — text, CSS gradients, SVG icons.
 *
 * With GPU tile raster (the previous `--enable-gpu-rasterization`) a rare capture differed from
 * its twin by exactly 1 in 8 bits, and ONLY on anti-aliased non-text geometry: every cut-row scrim
 * gradient band on the page (both rails, at once) plus a few SVG header-icon edges, never glyphs,
 * never flat fills, never inside the WebGL canvas; the alternate was the same bytes each time it
 * recurred. The signature is page-wide, not tied to one box — so it is the GPU rasterizer's
 * per-process state (gradient and path caches) choosing between two equally-correct rasterizations,
 * not a layout or a paint property of this product. Measured 2026-09-21 on a frozen `vite build`
 * served by `vite preview` (one tree, nobody writing to it): GPU tile raster, 3 `twice` runs =
 * 6 captures per frame, 1 of 32 frames varied (dark/1920/06-path-blocked: the two rail scrims and
 * header icons, maxd 1); CPU tile raster, 10 `twice` runs = 20 captures per frame, 0 of 32 varied
 * across ALL 20 (not only within pairs). Two product-side remedies had already been measured and
 * failed (layer-pinning every scrim scroller; see src/core/sticky-layer.test.ts), which is
 * consistent: the variance is not in the product's paint.
 *
 * The cost, stated: DOM pixels are Skia's software rasterization, which is also what a large share
 * of real users get; text anti-aliasing differs from a GPU-raster screenshot by a few levels. That
 * is a property of the photograph, identical on every run, and the reason every run must use it.
 */
const GPU_ARGS = ["--use-gl=angle", "--disable-gpu-rasterization", "--ignore-gpu-blocklist"];

/**
 * Opt in to the scene handle. `src/fabric3d/devHandle.ts` publishes `window.__atlasScene` on a
 * production build ONLY when the page asks for it before the app mounts, and this harness used to
 * rely on it without asking. Against `dist/` the handle was therefore absent on every frame, the
 * convergence wait silently degraded to a fixed sleep, the quality-tier check was skipped (it ran
 * only `if (render.quality !== null)`), and a run exited 0 with `converged: null` on all 32 frames
 * — absence rendered as health. An init script rather than a query parameter, so the URL each
 * frame records is still exactly the investigation state it names.
 */
function exposeScene() {
  window.__atlasExposeScene = true;
}

/**
 * The capture condition, evaluated IN THE PAGE: what the renderer says AND what the screen shows.
 *
 * Waiting on `stats().converged` alone was a race. Measured 2026-09-21 on the release build with
 * the handle on: two runs, every frame recorded `converged: true, quality: high`, and 18 of 32
 * frames still differed — one run photographed the warm-up overlay ("counting the shader
 * programs…") and a status bar reading "refining", the other "settled". The scene publishes stats
 * at most every 500 ms and `telemetry.ts` notifies React at most once a second (both measured
 * frame-rate trade-offs, deliberately left alone), so the DOM trails the renderer. Probe at the
 * moment `converged` first read true: status bar "refining" in 3 of 3 states, warm-up overlay
 * still up in 2 of 3; the DOM caught up 0.6-0.8 s later.
 *
 * So the harness waits for the thing it photographs: the renderer converged, the status bar's own
 * convergence word reading "settled", and no visible warm-up overlay. Self-contained on purpose —
 * it is serialised into the page, so it may reference nothing outside itself.
 */
function readSettle() {
  const scene = window.__atlasScene;
  const stats = scene?.stats?.();
  const word = document.querySelector(".sb__converged")?.textContent ?? null;
  const warm = document.querySelector(".stage-warmup");
  const warmVisible = warm !== null && warm.getClientRects().length > 0;
  return {
    handle: Boolean(scene),
    converged: stats?.converged ?? null,
    /* Every rAF callback the scene receives, rendered or idle (scene.ts counts it before the idle
       short-circuit). It is the harness's evidence that the render loop is ALIVE, as opposed to
       merely not finished yet. */
    framesTimed: stats?.framesTimed ?? null,
    statusWord: word,
    warmupVisible: warmVisible,
    ok: Boolean(scene) && stats?.converged === true && word === "settled" && !warmVisible,
  };
}
const READ_SETTLE = `(${readSettle.toString()})()`;

/* WHY THE WAIT IS PROGRESS-BOUNDED, NOT A FIXED WALL-CLOCK TIMEOUT (review finding F6, 2026-09-21).
 *
 * It used to be a flat 20 s. A `twice` pair then disagreed on its VERDICT while agreeing on every
 * byte: run 2 reported dark/1920/07-evidence-raw "not settled within 20000 ms", yet the PNG it wrote
 * shows "settled" — the frame settled after the cut-off and was shot anyway, so the record
 * (`converged:false`) contradicted its own pixels. That frame was written ~71 s after the previous
 * one, i.e. the host was heavily contended (other suites were running on it).
 *
 * Measured on a frozen `vite preview` build, full 8-state sequence per context, 1920x1080 @2x:
 * unloaded, every state in both themes settled on screen in 2.5-4.1 s; under 8x CDP CPU throttling
 * the same states settled in 11.6-35.7 s, tier `high` throughout, with no stall and no pathology.
 * Settle time scales with host load; there is no state-specific delay on s=evidence. A wall-clock
 * cut-off therefore measures the machine, not the renderer.
 *
 * So the wait now distinguishes the two things a timeout used to conflate:
 *   - SLOW  — the render loop is alive (`framesTimed` still advancing) but has not settled: keep
 *             waiting, up to SETTLE_HARD_CAP_MS, and RECORD how long it took (`settle.settledAtMs`),
 *             so a contended run is visible in index.json instead of silently absorbed.
 *   - STUCK — no new frame for SETTLE_STALL_MS while not converged (rAF suspended, a hung warm-up),
 *             or the hard cap reached: a recorded failure.
 * And a frame that fails the wait is NOT shot under its canonical name; see captureApp. */
const SETTLE_HARD_CAP_MS = 120000;
const SETTLE_STALL_MS = 15000;
const SETTLE_POLL_MS = 100;
/** Suffix of a frame that failed the settle wait: kept for diagnosis, never compared by `twice`. */
const UNSETTLED_SUFFIX = ".unsettled-diagnostic.png";

/**
 * Wait until the frame is settled ON SCREEN, then confirm it STAYS settled across two animation
 * frames. Returns `{ problems, settle }`; an empty problem list is the only way through, and
 * `settle` records when (ms after `t0`) the settled state was first seen.
 *
 * There is no fallback sleep. A failed wait is a recorded problem, because a frame shot at an
 * undefined moment is exactly what F6 cannot compare and F2's delegate cannot certify.
 */
async function awaitSettledOnScreen(page, t0) {
  const settle = { settledAtMs: null, waitedMs: null, lastFrameAdvanceMs: null, framesTimed: null };
  let lastFrames = null;
  let lastAdvance = Date.now();
  let st = null;
  for (;;) {
    st = await page.evaluate(READ_SETTLE).catch(() => null);
    const now = Date.now();
    if (st !== null && st.framesTimed !== null && st.framesTimed !== lastFrames) {
      lastFrames = st.framesTimed;
      lastAdvance = now;
    }
    settle.waitedMs = now - t0;
    settle.lastFrameAdvanceMs = lastAdvance - t0;
    settle.framesTimed = lastFrames;
    if (st?.ok) {
      settle.settledAtMs = now - t0;
      break;
    }
    const describe = () =>
      st === null
        ? "the page could not be read"
        : `converged=${st.converged}, status bar=${JSON.stringify(st.statusWord)}, ` +
          `warm-up overlay visible=${st.warmupVisible}, frames=${st.framesTimed}`;
    if (now - t0 >= SETTLE_HARD_CAP_MS) {
      if (st !== null && !st.handle) {
        return { settle, problems: ["no scene handle (window.__atlasScene): the renderer's convergence and quality tier were not observable"] };
      }
      return { settle, problems: [`not settled on screen within the ${SETTLE_HARD_CAP_MS} ms hard cap: ${describe()}`] };
    }
    // A stall is only meaningful once the loop has produced a frame and is not merely lagging the
    // DOM (converged=true with the status bar still catching up is progress, not a stall).
    if (lastFrames !== null && st?.converged !== true && now - lastAdvance >= SETTLE_STALL_MS) {
      return { settle, problems: [`render loop stalled: no new frame for ${SETTLE_STALL_MS} ms while not settled: ${describe()}`] };
    }
    await page.waitForTimeout(SETTLE_POLL_MS);
  }
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
  const again = await page.evaluate(READ_SETTLE);
  if (again.ok) return { settle, problems: [] };
  return {
    settle,
    problems: [
      `settled, then left it within two frames: converged=${again.converged}, ` +
        `status bar=${JSON.stringify(again.statusWord)}, warm-up overlay visible=${again.warmupVisible}`,
    ],
  };
}

async function captureApp(outRoot = resolve(SHOTS, "app")) {
  const server = await serverIdentity();
  announceServer(server);
  const browser = await chromium.launch({ args: GPU_ARGS });
  const written = [];
  const failures = [];
  for (const theme of THEMES) {
    for (const vp of VIEWPORTS) {
      const ctx = await browser.newContext({
        viewport: { width: vp.width, height: vp.height },
        deviceScaleFactor: 2,
        colorScheme: theme,
        reducedMotion: "no-preference",
      });
      await ctx.addInitScript(exposeScene);
      const page = await ctx.newPage();
      const consoleErrors = [];
      page.on("console", (m) => {
        if (m.type() === "error") consoleErrors.push(m.text().slice(0, 200));
      });
      page.on("pageerror", (e) => consoleErrors.push(String(e).slice(0, 200)));

      for (const st of APP_STATES) {
        const url = `${APP}/${st.q ? "?" + st.q : ""}`;

        /* PREPARE, with a bounded retry on a navigation that happened UNDER us.
         *
         * Against `npm run dev`, Vite's HMR client reloads the page whenever any module it is
         * serving changes. If that lands between `goto` and `addStyleTag`, Playwright throws
         * "Execution context was destroyed" and the whole run dies — which is what happened on the
         * second of the two F6 runs while other agents were editing the tree.
         *
         * A retry, not a swallow. It re-navigates from scratch (so the state is set up cleanly
         * rather than half-applied), it is bounded, and the attempt count is RECORDED on the frame
         * so a reviewer can see that a capture needed three goes. Exhausting the retries is a
         * recorded problem, not a silent pass. Note this makes the harness survive a live-reload;
         * it does not make a capture taken DURING active editing authoritative — F6's measurement
         * belongs on a tree nobody is writing to. */
        let attempts = 0;
        let prepareError = null;
        let t0 = Date.now();
        let prepMs = null;
        for (; attempts < 3; attempts++) {
          try {
            consoleErrors.length = 0;
            t0 = Date.now();
            await page.goto(url, { waitUntil: "networkidle" });
            await page.evaluate((t) => document.documentElement.setAttribute("data-theme", t), theme);
            await page.addStyleTag({ content: FREEZE_CSS });
            await page.evaluate(() => document.fonts?.ready);
            prepMs = Date.now() - t0;
            prepareError = null;
            break;
          } catch (e) {
            prepareError = String(e).slice(0, 200);
          }
        }

        /* Every state in APP_STATES is captured at a viewport of at least 1440 px, where the stage
           always shows the fabric (the < 768 px hidden-fabric layout is not in VIEWPORTS), so every
           frame must reach a settled on-screen render before it is shot. */
        const { problems: settleProblems, settle } =
          prepareError === null
            ? await awaitSettledOnScreen(page, t0).catch((e) => ({
                problems: [`settle check failed: ${String(e).slice(0, 160)}`],
                settle: null,
              }))
            : { problems: [], settle: null };
        const problems = await verifyRendered(page, st).catch((e) => [`verify failed: ${String(e).slice(0, 160)}`]);
        problems.push(...settleProblems);
        /* Content present is not content readable (C2/C3/D4), and coverage present is not coverage
           visible (B7). Both fail the frame, per element. */
        const textFindings = await page.evaluate(READ_TEXT_FIDELITY).catch((e) => [
          { kind: "check-failed", selector: "-", text: "", detail: String(e).slice(0, 160) },
        ]);
        problems.push(...describeTextFindings(textFindings));
        const coverage = await page.evaluate(READ_COVERAGE_VISIBILITY).catch((e) => [{ label: "-", problem: `check failed: ${String(e).slice(0, 160)}` }]);
        for (const c of coverage) problems.push(`coverage "${c.label}" ${c.problem}`);
        const tabOverflow = await page.evaluate(READ_TAB_OVERFLOW).catch((e) => [`tab overflow check failed: ${String(e).slice(0, 160)}`]);
        problems.push(...tabOverflow);
        if (prepareError !== null) problems.push(`could not prepare the page in 3 attempts: ${prepareError}`);
        if (attempts > 0) problems.push(`the page reloaded under the harness; captured on attempt ${attempts + 1}`);
        if (consoleErrors.length) problems.push(`console: ${consoleErrors.slice(0, 3).join(" | ")}`);

        /* Record WHICH quality tier and renderer produced each frame. A reviewer comparing two
           captures has to be able to tell a design change from a tier change, and a capture that
           silently ran on a software renderer would otherwise look like a design regression. */
        const render = await page.evaluate(() => {
          const s = window.__atlasScene?.stats?.();
          const c = document.createElement("canvas").getContext("webgl2");
          const dbg = c?.getExtension("WEBGL_debug_renderer_info");
          return {
            quality: s?.quality ?? null,
            drawCalls: s?.drawCalls ?? null,
            converged: s?.converged ?? null,
            /* The E4 frame-rate bar (fabric3d/stepdown.ts createFrameRateBar) is a rAF-clock-derived
               flag that StatusBar draws on the permanent chrome as "below frame-rate bar". Read from
               the scene AND from the DOM, because the pixels are what is compared. */
            frameRateBelowBar: s ? s.frameRateBelowBar === true : null,
            belowBarWords: [...document.querySelectorAll(".sb__reduced")].some((n) => /below frame-rate bar/.test(n.textContent ?? "")),
            renderer: c && dbg ? String(c.getParameter(dbg.UNMASKED_RENDERER_WEBGL)) : null,
          };
        });
        /* `null` is not a pass. It used to be skipped, so a run with no handle recorded no tier and
           no problem; an unobserved tier is now a problem in its own right. */
        if (render.quality === null) {
          problems.push("quality tier not observed: no scene handle on a fabric surface");
        } else if (render.quality !== "high") {
          problems.push(`rendered at quality tier "${render.quality}" (${render.renderer ?? "unknown GPU"})`);
        }
        if (render.converged !== true) problems.push(`scene not converged at shoot time (converged=${render.converged})`);
        /* Same rule as a tier other than high: a frame whose status line depends on how fast THIS
           host drew it is not a comparable capture (critic F6, 2026-09-22 — the flag reached the
           status line and nothing here looked at it). */
        if (render.frameRateBelowBar === true || render.belowBarWords) {
          problems.push(
            `status line reported "below frame-rate bar" at shoot time (scene flag=${render.frameRateBelowBar}, words drawn=${render.belowBarWords}): the chrome depends on this host's frame rate`,
          );
        }

        /* A frame that did not settle is NOT written under its canonical name. It used to be, so a
           run could hold a PNG whose pixels showed a later, settled moment next to a record saying
           `converged:false` — the record and the image disagreeing about the same frame. It is kept
           for diagnosis under a name `pngs()` excludes, and any canonical PNG left by an earlier run
           is removed so it cannot stand in for this one. */
        const settledBeforeShot = settleProblems.length === 0 && prepareError === null;
        const canonical = resolve(outRoot, theme, vp.id, `${st.id}.png`);
        const diagnostic = resolve(outRoot, theme, vp.id, `${st.id}${UNSETTLED_SUFFIX}`);
        rmSync(settledBeforeShot ? diagnostic : canonical, { force: true });
        const file = settledBeforeShot ? canonical : diagnostic;
        await shoot(page, file);
        /* ...and the state must still hold AFTER the shot, so the record describes the pixels. */
        if (settledBeforeShot) {
          const after = await page.evaluate(READ_SETTLE).catch(() => null);
          const barAfter = await page
            .evaluate(() => [...document.querySelectorAll(".sb__reduced")].some((n) => /below frame-rate bar/.test(n.textContent ?? "")))
            .catch(() => null);
          if (barAfter !== false) problems.push(`status line after the shot: below-frame-rate-bar words drawn=${barAfter}`);
          if (!after?.ok) {
            problems.push(
              `left the settled state during the screenshot: converged=${after?.converged ?? null}, ` +
                `status bar=${JSON.stringify(after?.statusWord ?? null)}`,
            );
          }
        }
        const rec = { ...st, theme, viewport: vp.id, file, url, server, render, prepMs, settle, attempts: attempts + 1, problems };
        written.push(rec);
        if (problems.length) {
          failures.push(`${theme}/${vp.id}/${st.id}: ${problems.join("; ")}`);
          console.log(`  BAD  ${theme}/${vp.id}/${st.id} — ${problems.join("; ")}`);
        }
      }
      await ctx.close();
    }
  }
  await browser.close();
  mkdirSync(outRoot, { recursive: true });
  writeFileSync(resolve(outRoot, "index.json"), JSON.stringify(written, null, 1));
  console.log(`captured ${written.length} app frames -> ${outRoot}`);
  /* Host contention is visible here rather than only as a flake: settle time scales with load. */
  const settled = written.filter((w) => w.settle?.settledAtMs != null);
  if (settled.length) {
    const slowest = settled.reduce((a, b) => (b.settle.settledAtMs > a.settle.settledAtMs ? b : a));
    console.log(
      `slowest settle: ${slowest.theme}/${slowest.viewport}/${slowest.id} at ${slowest.settle.settledAtMs} ms ` +
        `(hard cap ${SETTLE_HARD_CAP_MS} ms; unloaded host measured 2.5-4.1 s — a much larger figure means a contended run)`,
    );
  }
  if (failures.length) {
    console.log(`\n${failures.length} of ${written.length} frames did NOT render properly:`);
    for (const f of failures) console.log(`  ${f}`);
  }
  /* The verdict, stated and exited on. An empty capture set is not a pass either. */
  const verdict = written.length === 0 ? "NOT ESTABLISHED" : failures.length ? "FAIL" : "PASS";
  console.log(
    `${verdict}  capture app  ${written.length - failures.length} of ${written.length} frames rendered, ` +
      `settled on screen and at tier high` + (verdict === "PASS" ? " (render check only; NOT an F6 determinism result: run `twice 5`)" : ""),
  );
  // Non-zero so a review round cannot start on broken captures without someone noticing.
  if (verdict !== "PASS") process.exitCode = 3;
  return { written, failures, server };
}

/* ── F6: two runs produce byte-identical captures ─────────────────────────────────────────────
 *
 * WHY THIS EXISTS. Acceptance F6 reads "No `Math.random()` or `Date.now()` in rendered output
 * paths; two runs produce byte-identical captures", and its stated evidence is "capture twice,
 * compare hashes". Nothing in this repository did that. The half that WAS gated —
 * `src/core/determinism.test.ts` — is a syntactic scan of `src/`, and it was green while the
 * property was false: two consecutive `capture.mjs app` runs on 2026-09-21 differed in 23 of 32
 * frames, because `scene.ts`'s frame rate reached the status bar as a rAF callback PARAMETER,
 * which is not a call and so was invisible to it. A criterion whose evidence is a measurement
 * nobody performs is not a criterion; it is a sentence.
 *
 * So this mode performs it. Capture, re-capture into a second directory, hash every PNG, and exit
 * non-zero on any difference — naming the files, so the next person starts from the fault rather
 * than from the discovery that there is one.
 *
 * It is deliberately a WHOLE-FRAME comparison of the real product in a real browser. The unit
 * suite can prove that the status line draws no digit; only this can prove that the picture is the
 * same picture. Neither is a substitute for the other, and both are cited by F6. */

function sha256(file) {
  return createHash("sha256").update(readFileSync(file)).digest("hex");
}

/** Every PNG under `root`, keyed by its path relative to `root` in POSIX form. */
function pngs(root, dir = root, out = new Map()) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) pngs(root, p, out);
    else if (p.endsWith(".png") && !p.endsWith(UNSETTLED_SUFFIX)) out.set(relative(root, p).split("\\").join("/"), p);
  }
  return out;
}

/**
 * `twice [N]` — N complete captures (default 2), EVERY frame compared across ALL of them.
 *
 * One pair is a sample: the alternate frame this repository chased (R15) appeared in roughly one
 * pair in three, so a single PASS was read as green three times before anyone saw the fail. With
 * N > 2 a frame passes only if all N captures of it are byte-identical — the `N >= 5` evidence a
 * determinism claim needs is one command, with one verdict and one exit code.
 */
async function captureTwice(n = 2) {
  if (!Number.isInteger(n) || n < 2) {
    console.error(`twice needs N >= 2 captures (got ${n})`);
    process.exitCode = 2;
    return;
  }
  const root = resolve(SHOTS, "_twice");
  rmSync(root, { recursive: true, force: true });
  const runs = [];
  for (let i = 0; i < n; i++) {
    // "a" and "b" for the classic pair, so existing references to _twice/a and _twice/b still hold.
    const dir = resolve(root, n === 2 ? (i === 0 ? "a" : "b") : `run${i + 1}`);
    console.log(`run ${i + 1} of ${n}`);
    const r = await captureApp(dir);
    runs.push({ dir, failures: r.failures, server: r.server });
  }

  /* A run that did not render is not evidence of determinism either way. Two blank pages hash
     identically, and reporting that as F6 satisfied is the exact failure this repository calls
     "absence rendered as health". */
  const failed = runs.reduce((k, r) => k + r.failures.length, 0);
  if (failed) {
    console.log(
      `\nverdict: F6 NOT ESTABLISHED: ${failed} frame(s) did not ` +
        `render properly, so the comparison below says nothing about determinism.`,
    );
    process.exitCode = 3;
    return;
  }

  const sets = runs.map((r) => pngs(r.dir));
  const names = new Set(sets.flatMap((m) => [...m.keys()]));
  const missing = [...names].filter((k) => sets.some((m) => !m.has(k))).sort();
  const differing = [];
  const hashes = {};
  for (const rel of [...names].sort()) {
    if (missing.includes(rel)) continue;
    const hs = sets.map((m) => sha256(m.get(rel)));
    const distinct = [...new Set(hs)];
    hashes[rel] = { runs: hs, distinct: distinct.length, identical: distinct.length === 1 };
    // Back-compatible fields for the classic pair.
    if (n === 2) Object.assign(hashes[rel], { run1: hs[0], run2: hs[1] });
    if (distinct.length > 1) differing.push(rel);
  }
  const frames = sets[0].size;

  writeFileSync(resolve(root, "index.json"), JSON.stringify({ runs: n, servers: runs.map((r) => r.server), frames, differing, missing, hashes }, null, 1));

  // A capture set that is EMPTY compares clean. Say so rather than printing a green line.
  if (frames === 0) {
    console.log("\nverdict: F6 NOT ESTABLISHED: no frames were captured, so nothing was compared.");
    process.exitCode = 3;
    return;
  }
  if (missing.length) {
    console.log(`\nverdict: F6 FAIL: ${missing.length} file(s) missing from at least one run:\n  ${missing.join("\n  ")}`);
    process.exitCode = 3;
    return;
  }
  if (differing.length) {
    console.log(`\nverdict: F6 FAIL: ${differing.length} of ${frames} frames differ across ${n} runs:`);
    for (const rel of differing) {
      console.log(`  ${rel}`);
      hashes[rel].runs.forEach((h, i) => console.log(`    run${i + 1} ${h}`));
    }
    console.log(`\nhashes -> ${resolve(root, "index.json")}`);
    process.exitCode = 3;
    return;
  }
  console.log(`\nverdict: F6 PASS: ${frames} of ${frames} frames byte-identical across ${n} runs.`);
  if (n < 5) console.log(`note: ${n} runs is a sample; cite F6 on 'twice 5' or more (see the header of captureTwice).`);
  console.log(`hashes -> ${resolve(root, "index.json")}`);
}

async function captureRefs() {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 2,
    colorScheme: "dark",
    userAgent:
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
  });
  const page = await ctx.newPage();
  const written = [];
  for (const r of REFS) {
    try {
      await page.goto(r.url, { waitUntil: "domcontentloaded", timeout: 60000 });
      await page.waitForTimeout(r.wait);
      // Dismiss the obvious consent overlays so the capture shows the product, not a banner.
      for (const sel of ['button:has-text("Accept")', 'button:has-text("Got it")', '[aria-label="Close"]']) {
        const el = page.locator(sel).first();
        if (await el.count().catch(() => 0)) await el.click({ timeout: 1500 }).catch(() => {});
      }
      await page.waitForTimeout(1200);
      const file = resolve(SHOTS, "refs", `${r.id}.png`);
      await shoot(page, file);
      written.push({ id: r.id, url: r.url, file, ok: true });
      console.log(`  ok   ${r.id}`);
    } catch (e) {
      // A reference we could not capture must be RECORDED as uncaptured, never quietly skipped —
      // a critic must know it compared against 9 references, not 11.
      written.push({ id: r.id, url: r.url, file: null, ok: false, error: String(e).slice(0, 300) });
      console.log(`  FAIL ${r.id}: ${String(e).slice(0, 120)}`);
    }
  }
  await browser.close();
  mkdirSync(resolve(SHOTS, "refs"), { recursive: true });
  writeFileSync(resolve(SHOTS, "refs", "index.json"), JSON.stringify(written, null, 1));
  const ok = written.filter((w) => w.ok).length;
  console.log(`captured ${ok}/${REFS.length} reference frames -> ${resolve(SHOTS, "refs")}`);
}

/**
 * `node review/capture.mjs reduced` — the evidence acceptance D7 asks for.
 *
 * The app pass above pins `reducedMotion: "no-preference"` AND injects FREEZE_CSS, so it can never
 * say anything about the preference: it photographs an app whose animations were switched off by
 * the harness rather than by the user's setting. D7 was therefore UNPROVEN, which is a fail — and
 * the half that is easy to break is the WebGL half, a JavaScript boolean no stylesheet dump shows.
 *
 * So this pass forces the media feature through the browser context (the only place it can really
 * be set), takes NO freeze CSS, and MEASURES rather than eyeballs: it asks the live scene to frame
 * a device and samples that device's projection frame by frame. Under `reduce` the camera must land
 * on the first frame; the control run at `no-preference` must take several. Both are printed, and a
 * reduced run that animates exits non-zero.
 */
async function captureReduced() {
  const server = await serverIdentity();
  announceServer(server);
  const browser = await chromium.launch({ args: GPU_ARGS });
  const out = [];
  for (const motion of ["reduce", "no-preference"]) {
    const ctx = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      deviceScaleFactor: 2,
      colorScheme: "dark",
      reducedMotion: motion,
    });
    await ctx.addInitScript(exposeScene);
    const page = await ctx.newPage();
    const st = APP_STATES.find((s) => s.id === "06-path-blocked") ?? APP_STATES[0];
    /* `awaitSettledOnScreen` returns `{ settle, problems }` and measures every deadline from `t0`.
       This call site used to take the whole object AS the problem list (so `for … of` threw "not
       iterable" and D7's gate never reached a verdict) and passed no `t0` (so every elapsed time was
       NaN and the hard cap could never fire). Both halves of the contract, as `captureApp` uses it. */
    const t0 = Date.now();
    await page.goto(`${APP}/${st.q ? "?" + st.q : ""}`, { waitUntil: "networkidle" });
    await page.evaluate(() => document.fonts?.ready);
    const { problems: settleProblems } = await awaitSettledOnScreen(page, t0);

    const measured = await page.evaluate(async () => {
      const css = getComputedStyle(document.documentElement);
      const s = window.__atlasScene;
      const series = [];
      if (s) {
        s.resetCamera({ immediate: true });
        await new Promise((r) => requestAnimationFrame(r));
        s.focusDevice("core1");
        for (let i = 0; i < 24; i += 1) {
          await new Promise((r) => requestAnimationFrame(r));
          const p = s.project("core1");
          series.push(p ? `${Math.round(p.x)},${Math.round(p.y)}` : "null");
        }
      }
      return {
        mediaMatches: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
        durCamera: css.getPropertyValue("--dur-camera").trim(),
        durMedium: css.getPropertyValue("--dur-medium").trim(),
        // How many DISTINCT camera poses the device was projected through: 1 means it jumped.
        cameraPoses: new Set(series).size,
        sceneHandle: Boolean(s),
      };
    });

    const file = resolve(SHOTS, "reduced-motion", `${motion}.png`);
    await shoot(page, file);
    out.push({ motion, file, server, settleProblems, ...measured });
    console.log(`  ${motion}: media=${measured.mediaMatches} --dur-camera=${measured.durCamera} cameraPoses=${measured.cameraPoses}`);
    await ctx.close();
  }
  await browser.close();
  mkdirSync(resolve(SHOTS, "reduced-motion"), { recursive: true });
  writeFileSync(resolve(SHOTS, "reduced-motion", "index.json"), JSON.stringify(out, null, 1));

  const reduced = out.find((o) => o.motion === "reduce");
  const control = out.find((o) => o.motion === "no-preference");
  const problems = [];
  if (!reduced?.mediaMatches) problems.push("the reduce context did not report the media feature");
  if (!reduced?.sceneHandle) problems.push("no scene handle: the WebGL half was not exercised at all");
  for (const o of out) for (const sp of o.settleProblems) problems.push(`${o.motion}: ${sp}`);
  if ((reduced?.cameraPoses ?? 0) !== 1) problems.push(`camera moved through ${reduced?.cameraPoses} poses under reduce`);
  // Without a control that DOES animate, the check above would pass against a dead renderer.
  if ((control?.cameraPoses ?? 0) < 2) problems.push(`control run did not animate (${control?.cameraPoses} poses) — the measurement proves nothing`);
  const verdict = problems.length ? "FAIL" : "PASS";
  if (verdict !== "PASS") {
    console.log(`\n${verdict}  D7 NOT satisfied:\n  ${problems.join("\n  ")}`);
    process.exitCode = 3;
  } else {
    console.log(`${verdict}  D7: camera lands in one frame under reduce, ${control?.cameraPoses} poses without it.`);
  }
}

/**
 * `node review/capture.mjs text` — the text-fidelity and coverage-visibility checks alone, over
 * every capture state PLUS the command palette open, at every width the product supports (not only
 * the two the photographs use: B7 failed at 390 px, which no capture viewport reaches), in both
 * themes. No screenshots and no renderer-settle wait — these are DOM layout questions, answered in
 * seconds, so they can gate an edit loop. `captureApp` runs the same two checks on every frame it
 * shoots; this mode is not a substitute for that, it is the fast way to reach the same verdict.
 * Exit 3 on any finding.
 */
const TEXT_VIEWPORTS = [
  { id: "390", width: 390, height: 844 },
  { id: "768", width: 768, height: 1024 },
  { id: "1440", width: 1440, height: 900 },
  { id: "1920", width: 1920, height: 1080 },
];
const TEXT_EXTRA_STATES = [
  { id: "09-palette-open", q: "", note: "Command palette open (Ctrl+K): its footer hints (D4).", open: "palette", contrastOf: ".palette__foot" },
];

async function checkText() {
  const server = await serverIdentity();
  announceServer(server);
  const only = process.argv[3] ? new Set(process.argv[3].split(",")) : null;
  const browser = await chromium.launch({ args: GPU_ARGS });
  const failures = [];
  let checked = 0;
  for (const theme of THEMES) {
    for (const vp of TEXT_VIEWPORTS) {
      if (only && !only.has(vp.id)) continue;
      const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, deviceScaleFactor: 1, colorScheme: theme });
      const page = await ctx.newPage();
      for (const st of [...APP_STATES, ...TEXT_EXTRA_STATES]) {
        const url = `${APP}/${st.q ? "?" + st.q : ""}`;
        let findings = [];
        let coverage = [];
        let contrast = [];
        let tabOverflow = [];
        for (let attempt = 0; attempt < 3; attempt++) {
          try {
            await page.goto(url, { waitUntil: "networkidle" });
            await page.evaluate((t) => document.documentElement.setAttribute("data-theme", t), theme);
            await page.addStyleTag({ content: FREEZE_CSS });
            await page.evaluate(() => document.fonts?.ready);
            /* The shell mounts after the entry chunk loads; a check run before the status bar
               exists would report the app's absence as a coverage failure. Waited for, bounded:
               if it never appears, the coverage check below says so. */
            await page.waitForSelector("#status-bar", { timeout: 15000 }).catch(() => {});
            if (st.open === "palette") {
              await page.keyboard.press("Control+k");
              await page.waitForSelector(".palette__foot", { timeout: 5000 });
            }
            /* Wait for the DOM to stop changing (an async trace fills in after load). */
            let last = -1;
            for (let i = 0; i < 40; i++) {
              const len = await page.evaluate(() => document.body.innerText.length);
              if (len === last) break;
              last = len;
              await page.waitForTimeout(250);
            }
            findings = await page.evaluate(READ_TEXT_FIDELITY);
            coverage = await page.evaluate(READ_COVERAGE_VISIBILITY);
            tabOverflow = await page.evaluate(READ_TAB_OVERFLOW);
            if (st.contrastOf) {
              contrast = await page.evaluate(`(${readContrast.toString()})(${JSON.stringify(st.contrastOf)})`);
            }
            break;
          } catch (e) {
            findings = [{ kind: "check-failed", selector: "-", text: "", detail: String(e).slice(0, 160) }];
          }
        }
        checked++;
        const problems = [...describeTextFindings(findings), ...coverage.map((c) => `coverage "${c.label}" ${c.problem}`), ...tabOverflow];
        for (const c of contrast) {
          if (c.error) problems.push(`contrast ${c.selector}: ${c.error}`);
          else if (c.backgroundImage) problems.push(`contrast "${c.text}" not measured: background image on ${c.backgroundImage}`);
          else if (c.ratio < 4.5) problems.push(`contrast "${c.text}" ${c.selector} ${c.fg} on ${c.bg} = ${c.ratio}:1 (< 4.5:1)`);
        }
        if (contrast.length) {
          const lo = contrast.filter((c) => typeof c.ratio === "number").reduce((a, c) => Math.min(a, c.ratio), Infinity);
          console.log(`  contrast ${theme}/${vp.id}/${st.id} ${st.contrastOf}: min ${lo}:1 over ${contrast.length} texts — ` + contrast.map((c) => `"${c.text}" ${c.fg}/${c.bg} ${c.ratio}`).join("; "));
        }
        if (problems.length) {
          failures.push(`${theme}/${vp.id}/${st.id}`);
          console.log(`  BAD  ${theme}/${vp.id}/${st.id}`);
          for (const p of problems) console.log(`       ${p}`);
        }
      }
      await ctx.close();
    }
  }
  await browser.close();
  const verdict = checked === 0 ? "NOT ESTABLISHED" : failures.length ? "FAIL" : "PASS";
  console.log(`${verdict}  text  ${checked - failures.length} of ${checked} states free of clipped/broken text, with coverage wholly visible and no tab hidden off its strip`);
  if (verdict !== "PASS") process.exitCode = 3;
}

const mode = process.argv[2];
if (mode === "app") await captureApp();
else if (mode === "text") await checkText();
else if (mode === "refs") await captureRefs();
else if (mode === "reduced") await captureReduced();
else if (mode === "twice") await captureTwice(process.argv[3] === undefined ? 2 : Number(process.argv[3]));
else {
  console.error("usage: node review/capture.mjs app|refs|reduced|twice [N]|text [390,768,1440,1920]");
  process.exit(2);
}
