import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { api } from "../api";
import { useReducedMotion, useToast } from "../components/ui";

const FEATURES = [
  { icon: "◎", title: "Risk cockpit", body: "Fleet posture, health bands, and the punch-list triaged by severity — the few things to fix first, not thousands of findings." },
  { icon: "⌗", title: "Keystone devices", body: "The switches the fleet most depends on by migration blast radius — the prioritisation that holds even when every score saturates." },
  { icon: "⟲", title: "Campaign timeline", body: "Track waves across the migration: what regressed, what improved, and a trajectory verdict from one collection to the next." },
  { icon: "◈", title: "Deep explorer", body: "Open the full interactive topology explorer for any snapshot — blast radius, path trace, flow, protocols, cross-layer, causality." },
];

const PIPELINE = ["SSH collection (CLI engine)", "snapshot.json", "AssessHub store", "cockpit + explorer"];

/* ---- reveal-on-view: indexed elements start visible/classless; the first one to enter the
   viewport lands its index in `seen` (reveal class + stagger apply) and is unobserved — an element
   already in view when observed fires immediately, so nothing depends on scrolling ever happening.
   No-op under reduced motion or without IntersectionObserver (jsdom): elements just stay at their
   default, fully-visible resting state. ---- */
function useRevealOnView<T extends Element>(reduced: boolean) {
  const els = useRef<(T | null)[]>([]);
  const [seen, setSeen] = useState<Set<number>>(new Set());
  useEffect(() => {
    if (reduced || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        io.unobserve(e.target);
        const i = els.current.indexOf(e.target as T);
        if (i >= 0) setSeen((s) => new Set(s).add(i));
      }
    });
    els.current.forEach((el) => el && io.observe(el));
    return () => io.disconnect();
  }, [reduced]);
  return { ref: (i: number) => (el: T | null) => { els.current[i] = el; }, seen };
}

export default function Landing() {
  const nav = useNavigate();
  const { toast, node } = useToast();
  const [seeding, setSeeding] = useState(false);
  const reduced = useReducedMotion();
  const step = useRevealOnView<HTMLSpanElement>(reduced);

  async function loadSample() {
    setSeeding(true);
    try {
      const r = await api.seedDemo();
      toast("Sample fleet loaded.");
      nav(`/snapshots/${r.snapshot.id}`);
    } catch (e: any) {
      toast(e.message || "Could not load sample.");
      setSeeding(false);
    }
  }

  return (
    <div className="container">
      <section className="hero-reveal" style={{ padding: "44px 0 30px", maxWidth: 760 }}>
        <div className="chip" style={{ marginBottom: 18 }}>
          <span className="dot" style={{ color: "var(--ok)" }} /> Offline engine · live cockpit
        </div>
        <h1 style={{ fontSize: 44, lineHeight: 1.05, letterSpacing: "-.02em" }}>
          Your network migration,<br />
          <span style={{ background: "linear-gradient(120deg,var(--accent),var(--ok))", WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent" }}>
            decision-ready in a browser.
          </span>
        </h1>
        <p className="dim" style={{ fontSize: 16, marginTop: 16, maxWidth: 620 }}>
          AssessHub is a live web surface over the Cisco Migration-Assessment engine. One offline SSH
          collection produces a snapshot; upload it here to track campaigns and waves over time, triage
          the punch-list, rank keystone devices by blast radius, and open the deep topology explorer —
          all from the same evidence the workbook and runbook are built on.
        </p>
        <div className="row-flex" style={{ marginTop: 26 }}>
          <button className="btn primary lg" onClick={loadSample} disabled={seeding}>
            {seeding ? "Loading…" : "▶  Open a sample fleet"}
          </button>
          <button className="btn lg" onClick={() => nav("/campaigns")}>Go to campaigns</button>
        </div>
        <div className="faint" style={{ fontSize: 12, marginTop: 12 }}>
          The sample is the bundled demo snapshot — no live network needed.
        </div>
      </section>

      <div className="grid cols-2" style={{ marginTop: 18 }}>
        {FEATURES.map((f) => (
          <div className="panel pad-lg" key={f.title}>
            <div style={{ fontSize: 22, color: "var(--accent)", marginBottom: 10 }}>{f.icon}</div>
            <h3 style={{ textTransform: "none", letterSpacing: 0, fontSize: 16, color: "var(--text)", marginBottom: 6 }}>{f.title}</h3>
            <p className="dim" style={{ margin: 0, fontSize: 13 }}>{f.body}</p>
          </div>
        ))}
      </div>

      <div className="panel pad-lg" style={{ marginTop: 18 }}>
        <h3>How it fits together</h3>
        <div className="row-flex" style={{ gap: 0, fontSize: 13, fontWeight: 600, flexWrap: "wrap" }}>
          {PIPELINE.map((s, i, a) => (
            <span key={s} className="row-flex" style={{ gap: 0 }}>
              <span
                ref={step.ref(i)}
                className={step.seen.has(i) ? "step-in" : undefined}
                style={{
                  padding: "8px 14px", border: "1px solid var(--border)", borderRadius: 9, background: "var(--surface-2)",
                  animationDelay: `${Math.min(i, 8) * 50}ms`,
                }}
              >
                {s}
              </span>
              {i < a.length - 1 && <span className="faint" style={{ padding: "0 12px" }}>→</span>}
            </span>
          ))}
        </div>
        <p className="dim" style={{ fontSize: 12, marginTop: 14, marginBottom: 0 }}>
          The CLI engine stays the single source of truth — AssessHub never re-runs analysis, it serves,
          slices, diffs, and trends the snapshots the engine already produced.
        </p>
      </div>
      {node}
    </div>
  );
}
