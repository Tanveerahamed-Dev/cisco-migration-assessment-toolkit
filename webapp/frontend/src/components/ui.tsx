import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { flushSync } from "react-dom";

/* ---- respects the OS "reduce motion" setting (live) ---- */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches,
  );
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const on = () => setReduced(mq.matches);
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);
  return reduced;
}

/* ---- animated number (easeOutCubic). Conveys magnitude; jumps straight to the value under reduced
   motion. Animates from the previously shown value, so live updates tween rather than restart at 0. ---- */
export function CountUp({ value, duration = 700, decimals = 0, suffix = "", prefix = "" }:
  { value: number; duration?: number; decimals?: number; suffix?: string; prefix?: string }) {
  const reduced = useReducedMotion();
  const [display, setDisplay] = useState(reduced ? value : 0);
  const fromRef = useRef(0);
  useEffect(() => {
    if (reduced || !Number.isFinite(value)) { setDisplay(value); fromRef.current = value; return; }
    const from = fromRef.current;
    // Anchor the tween to the FIRST rAF callback's own timestamp, never performance.now() at
    // setup: rAF timestamps are a per-frame clock that need not share an origin with a
    // performance.now() read (they measurably don't under jsdom), and mixing them skews t.
    let start = -1;
    let raf = 0;
    const tick = (now: number) => {
      if (start < 0) start = now;
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      const v = from + (value - from) * eased;
      // Mirror the shown value on EVERY frame, not only on completion: a retarget mid-tween
      // reads fromRef as its start, and a completion-only write made it restart from the
      // pre-tween value (0→100 interrupted at ~87 by a retarget to 50 visibly snapped to 0).
      fromRef.current = v;
      setDisplay(v);
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value, duration, reduced]);
  const shown = Number.isFinite(display)
    ? (decimals ? display.toFixed(decimals) : Math.round(display).toString())
    : "—";
  return <>{prefix}{shown}{suffix}</>;
}

/* ---- View Transitions wrapper: run(update) cross-fades the DOM change via
   document.startViewTransition where supported, else applies it instantly. Reduced motion is
   gated HERE, not by the styles.css kill-switch — ::view-transition-* pseudo-elements live in a
   UA-generated tree a page-authored `*` selector can't reliably reach. flushSync commits the
   React update inside the snapshot callback (the API's documented contract). Starting a new
   transition while one is active auto-skips the old one — no queueing needed. ---- */
export function useViewTransition(): (update: () => void) => void {
  const reduced = useReducedMotion();
  return useCallback((update: () => void) => {
    const doc = document as Document & { startViewTransition?: (cb: () => void) => unknown };
    if (reduced || typeof doc.startViewTransition !== "function") { update(); return; }
    doc.startViewTransition(() => { flushSync(update); });
  }, [reduced]);
}

export interface Pt { x: number; y: number }

/* ---- CountUp generalized to 2-D for diagram relayouts (topology lanes, cable map): every id
   that persists across a targets change tweens from its last SHOWN point (live-mirrored each
   frame, so a retarget mid-tween continues from what is on screen); a newly-appeared id renders
   AT its target (no fly-in — resting state is the final state); a vanished id drops immediately.
   Under reduced motion the targets pass through untouched, zero rAF. Callers must useMemo the
   Map, and must re-derive dependent anchor points (cable stubs) as anchor + (shown - target) of
   their OWN node — tweening anchors independently desyncs cables from chassis mid-flight. ---- */
export function usePositionTween(targets: ReadonlyMap<string, Pt>, duration = 400): ReadonlyMap<string, Pt> {
  const reduced = useReducedMotion();
  const [shown, setShown] = useState<ReadonlyMap<string, Pt>>(targets);
  const shownRef = useRef(shown);
  useEffect(() => {
    const from = shownRef.current;
    let moved = false;
    if (!reduced) {
      for (const [id, to] of targets) {
        const f = from.get(id);
        if (f && (f.x !== to.x || f.y !== to.y)) { moved = true; break; }
      }
    }
    // Nothing persisting actually moved (or reduced motion): adopt the targets in one hop —
    // membership-only changes (add/remove) snap by design.
    if (reduced || !moved) { shownRef.current = targets; setShown(targets); return; }
    let start = -1; // anchored to the first rAF timestamp — same single-clock rule as CountUp
    let raf = 0;
    const tick = (now: number) => {
      if (start < 0) start = now;
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      const next = new Map<string, Pt>();
      for (const [id, to] of targets) {
        const f = from.get(id);
        next.set(id, f ? { x: f.x + (to.x - f.x) * eased, y: f.y + (to.y - f.y) * eased } : to);
      }
      shownRef.current = next;
      setShown(next);
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [targets, reduced, duration]);
  return shown;
}

/* ---- async data hook ---- */
export function useAsync<T>(fn: () => Promise<T>, deps: any[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const run = useCallback(() => {
    setLoading(true);
    setError(null);
    fn()
      .then((d) => setData(d))
      .catch((e) => setError(e.message || String(e)))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(run, [run]);
  return { data, error, loading, reload: run };
}

export function Loading({ label }: { label?: string }) {
  return (
    <div className="center">
      <div style={{ textAlign: "center" }}>
        <div className="spinner" style={{ margin: "0 auto 12px" }} />
        <div className="faint" style={{ fontSize: 12 }}>{label || "Loading…"}</div>
      </div>
    </div>
  );
}

export function ErrorBox({ msg }: { msg: string }) {
  return (
    <div className="panel" style={{ borderColor: "var(--crit)", color: "var(--crit)" }}>
      <b>Something went wrong.</b> <span className="dim">{msg}</span>
    </div>
  );
}

/* ---- KPI tile ---- */
export function Kpi({ value, label, hint, tone }: { value: ReactNode; label: string; hint?: string; tone?: "ok" | "watch" | "risk" | "crit" }) {
  return (
    <div className={`panel kpi ${tone || ""}`}>
      <div className="l">{label}</div>
      <div className="v">{value}</div>
      {hint && <div className="hint">{hint}</div>}
    </div>
  );
}

/* ---- donut gauge ---- */
export function Gauge({ value, max = 100, size = 132, color, label }: { value: number; max?: number; size?: number; color: string; label?: string }) {
  const stroke = 11;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const frac = Math.max(0, Math.min(1, value / max));
  return (
    <div className="gauge" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-3)" strokeWidth={stroke} />
        <circle
          cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={stroke}
          strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - frac)}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: "stroke-dashoffset .7s ease" }}
        />
      </svg>
      <div className="num">
        <b>{Number.isFinite(value) ? <CountUp value={value} /> : "—"}</b>
        {label && <span>{label}</span>}
      </div>
    </div>
  );
}

/* ---- segmented distribution bar + legend ---- */
export function SegBar({ data, colorFor }: { data: Record<string, number>; colorFor: (k: string) => string }) {
  const entries = Object.entries(data).filter(([, v]) => v > 0);
  const total = entries.reduce((s, [, v]) => s + v, 0) || 1;
  return (
    <>
      <div className="segbar">
        {entries.map(([k, v]) => (
          <span key={k} title={`${k}: ${v}`} style={{ width: `${(v / total) * 100}%`, background: colorFor(k) }} />
        ))}
      </div>
      <div className="legend">
        {entries.map(([k, v]) => (
          <span className="item" key={k}>
            <span className="sw" style={{ background: colorFor(k) }} /> {k} <b>{v}</b>
          </span>
        ))}
      </div>
    </>
  );
}

/* ---- horizontal bars ---- */
export function Bars({ data, colorFor }: { data: Record<string, number>; colorFor?: (k: string) => string }) {
  const entries = Object.entries(data).filter(([, v]) => v > 0);
  const max = Math.max(1, ...entries.map(([, v]) => v));
  return (
    <div className="bars">
      {entries.map(([k, v]) => (
        <div className="row" key={k}>
          <div className="name" title={k}>{k}</div>
          <div className="track">
            <div className="fill" style={{ width: `${(v / max) * 100}%`, background: colorFor ? colorFor(k) : "var(--accent)" }} />
          </div>
          <div className="n">{v}</div>
        </div>
      ))}
      {entries.length === 0 && <div className="faint" style={{ fontSize: 12 }}>None.</div>}
    </div>
  );
}

/* ---- severity chip ---- */
export function SevChip({ sev, label }: { sev: string; label?: string }) {
  const key = sev.replace(/\s+/g, "");
  return (
    <span className="chip sev" style={{ ["--c" as any]: `var(--sev-${key}, var(--text-faint))`, ["--cs" as any]: `var(--sev-${key}-soft, var(--surface-3))` }}>
      <span className="dot" /> {label ?? sev}
    </span>
  );
}

/* ---- tiny toast: fades/slides in (styles.css toast-in) and, symmetrically, out. `closing` flips
   at the 2600ms display timeout and adds the exit class; the node itself clears TOAST_EXIT_MS later,
   giving the animation time to finish. ---- */
const TOAST_EXIT_MS = 260; // mirrors --motion (0.26s) — jsdom runs css:false, so the token can't be read at runtime

export function useToast() {
  const [msg, setMsg] = useState<string | null>(null);
  const [closing, setClosing] = useState(false);
  const reduced = useReducedMotion();
  // Batched with setMsg so a replacement toast never paints with the outgoing one's exit class.
  const toast = useCallback((m: string) => { setClosing(false); setMsg(m); }, []);
  useEffect(() => {
    if (!msg) return;
    if (reduced) {
      const t = setTimeout(() => setMsg(null), 2600); // no exit phase — today's exact behavior
      return () => clearTimeout(t);
    }
    const out = setTimeout(() => setClosing(true), 2600);
    const gone = setTimeout(() => { setMsg(null); setClosing(false); }, 2600 + TOAST_EXIT_MS);
    return () => { clearTimeout(out); clearTimeout(gone); };
  }, [msg, reduced]);
  const node = msg ? <div className={`toast${closing ? " out" : ""}`}>{msg}</div> : null;
  return { toast, node };
}

/* ---- Skeleton loading placeholders (animation Unit 23): structure-shaped stand-ins for panels
   whose content SHAPE is already known, so a panel reveals in place instead of blanking-then-popping
   behind the centered Loading spinner (which stays for full-page/unknown-shape contexts). Skeleton
   is the base bar — every instance gets className="skel loading" (the "loading" class is what keeps
   Campaign.test.tsx's `.spinner, .loading` selector satisfied wherever a skeleton lands) plus a
   visually-hidden "Loading…" child. LOAD-BEARING: ArchReview.test.tsx and DesignBlueprint.test.tsx
   assert getByText(/Loading/i) during load and must keep passing untouched. `announce=false` drops
   that child on the repeated bars within a preset, so a single-match getByText query never trips
   over duplicate "Loading…" text nodes — exactly one bar per preset instance announces. ---- */
export function Skeleton({ className = "", label, announce = true }: { className?: string; label?: string; announce?: boolean }) {
  return (
    <div className={`skel loading ${className}`}>
      {announce && <span className="sr-only">{label || "Loading…"}</span>}
    </div>
  );
}

// cycled per body line/cell for a "content, not a bar chart" look. Structural, lives in the preset —
// callers never pass widths in.
const SKEL_W = ["skel-w1", "skel-w2", "skel-w3", "skel-w4"];

/* ---- prose/panel-body preset: a heading-width bar + n body lines of varying width. ---- */
export function SkelLines({ n = 4, label }: { n?: number; label?: string }) {
  return (
    <div className="skel-lines">
      <Skeleton className="skel-h" label={label} />
      {Array.from({ length: n }, (_, i) => (
        <Skeleton key={i} className={`skel-line ${SKEL_W[i % SKEL_W.length]}`} announce={false} />
      ))}
    </div>
  );
}

/* ---- table/grid preset: a header bar + rows×cols cell bars, uniform per column like a real table. ---- */
export function SkelTable({ rows = 4, cols = 4, label }: { rows?: number; cols?: number; label?: string }) {
  return (
    <div className="skel-table">
      <div className="skel-row">
        {Array.from({ length: cols }, (_, c) => (
          <Skeleton key={c} className="skel-th" label={label} announce={c === 0} />
        ))}
      </div>
      {Array.from({ length: rows }, (_, r) => (
        <div className="skel-row" key={r}>
          {Array.from({ length: cols }, (_, c) => (
            <Skeleton key={c} className="skel-td" announce={false} />
          ))}
        </div>
      ))}
    </div>
  );
}
