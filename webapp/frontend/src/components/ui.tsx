import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

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
    const start = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplay(from + (value - from) * eased);
      if (t < 1) raf = requestAnimationFrame(tick);
      else fromRef.current = value;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value, duration, reduced]);
  const shown = Number.isFinite(display)
    ? (decimals ? display.toFixed(decimals) : Math.round(display).toString())
    : "—";
  return <>{prefix}{shown}{suffix}</>;
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

/* ---- tiny toast ---- */
export function useToast() {
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    if (!msg) return;
    const t = setTimeout(() => setMsg(null), 2600);
    return () => clearTimeout(t);
  }, [msg]);
  const node = msg ? <div className="toast">{msg}</div> : null;
  return { toast: setMsg, node };
}
