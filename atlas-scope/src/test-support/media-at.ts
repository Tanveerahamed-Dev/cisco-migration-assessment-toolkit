/**
 * media-at.ts — answer a viewport width media query the way a browser does, at a given CSS-pixel
 * width AND a given browser default font size (acceptance F4(c), re-grade 2).
 *
 * WHY THE FONT SIZE IS A PARAMETER. In a media query `rem` and `em` resolve against the browser's
 * INITIAL font size, which is a standard reader setting (Chrome: Settings > Appearance > Font size,
 * 9 to 72 px; "Small" is 12, "Medium" 16, "Large" 20), not a constant 16 px. Every earlier mock in
 * this suite multiplied a rem by 16, so none of them could see the measured defect: at a 12 px
 * default a 700 px load matched `(min-width: 48rem)` (576 px) and fetched three.js with no "Show
 * the 3-D fabric" button, and at a 20 px default a 900 px load (45 rem) never fetched it.
 *
 * It models exactly the syntax this application writes — an optional `not`/`only`, an optional
 * media type, and `and`-joined parenthesised features — and THROWS on anything else, so an
 * unmodelled query is a failure rather than a silent `false`. A non-width feature (a preference such
 * as `prefers-reduced-motion`) answers "no preference": false.
 */

const unitPx = (unit: string, fontPx: number): number => (unit === "px" ? 1 : fontPx);

function feature(inner: string, width: number, fontPx: number): boolean {
  const s = inner.trim();
  const m = /^(min|max)-width\s*:\s*(\d+(?:\.\d+)?|\.\d+)(px|rem|em)$/.exec(s);
  if (m) {
    const bound = Number(m[2]) * unitPx(m[3] as string, fontPx);
    return m[1] === "min" ? width >= bound : width <= bound;
  }
  if (/width/.test(s)) throw new Error(`media-at: unmodelled width feature "(${s})"`);
  if (/^[a-z-]+\s*(:\s*[a-z0-9-]+)?$/.test(s)) return false;
  throw new Error(`media-at: unmodelled feature "(${s})"`);
}

/** Does ONE media query (no top-level comma) match a screen `width` CSS px wide at `fontPx`? */
export function mediaMatchesAt(query: string, width: number, fontPx: number): boolean {
  let s = query.trim().toLowerCase().replace(/\s+/g, " ");
  let negate = false;
  const lead = /^(not|only) /.exec(s);
  if (lead) {
    negate = lead[1] === "not";
    s = s.slice(lead[0].length);
  }
  let type = "all";
  const t = /^(all|screen|print)\b ?/.exec(s);
  if (t) {
    type = t[1] as string;
    s = s.slice(t[0].length);
    if (s !== "") {
      if (!s.startsWith("and ")) throw new Error(`media-at: unmodelled query "${query}"`);
      s = s.slice(4);
    }
  } else if (negate) {
    throw new Error(`media-at: unmodelled query "${query}" (\`not\` without a media type)`);
  }
  let all = type !== "print";
  while (s !== "") {
    const f = /^\(([^()]*)\)/.exec(s);
    if (!f) throw new Error(`media-at: unmodelled query "${query}"`);
    all = feature(f[1] as string, width, fontPx) && all;
    s = s.slice(f[0].length).trim();
    if (s === "") break;
    if (!s.startsWith("and ")) throw new Error(`media-at: unmodelled combinator in "${query}" (only \`and\` is modelled)`);
    s = s.slice(4);
  }
  return negate ? !all : all;
}

/** A media query LIST: matches when any of its comma-separated queries does. */
export const mediaListMatchesAt = (list: string, width: number, fontPx: number): boolean =>
  list.split(",").some((q) => q.trim() !== "" && mediaMatchesAt(q, width, fontPx));

/**
 * Replace `window.matchMedia` with one that answers every query at `width` CSS px and a browser
 * default font size of `fontPx`. Returns the restore function. `setViewport` mutates the answer in
 * place, so a later `resize` event re-reads a new width without reinstalling.
 */
export function installMatchMediaAt(width: number, fontPx: number): { restore: () => void; set: (w: number, f?: number) => void } {
  const real = window.matchMedia;
  let w = width;
  let f = fontPx;
  window.matchMedia = ((q: string) =>
    ({
      matches: mediaListMatchesAt(q, w, f),
      media: q,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList) as typeof window.matchMedia;
  return {
    restore: () => {
      window.matchMedia = real;
    },
    set: (nw: number, nf?: number) => {
      w = nw;
      if (nf !== undefined) f = nf;
    },
  };
}
