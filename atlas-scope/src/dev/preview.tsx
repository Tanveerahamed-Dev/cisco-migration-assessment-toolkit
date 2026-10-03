/**
 * preview.tsx — a standalone mount for the 3-D fabric, served at /fabric-preview.html.
 *
 * It exists so the renderer can be looked at, screenshotted and profiled without waiting for the
 * application shell, and without any dev-only scaffolding leaking into `App.tsx`. Separate Vite
 * entry, separate root, no shared files — it cannot collide with the integration work.
 *
 * It mounts the LABEL LAYER as well as the canvas, and that is not a convenience.
 *
 * Labels in this application are DOM, not canvas text (FabricLabels.tsx), so a harness that mounts
 * only `createScene` draws none of them — while `scene.stats()` keeps reporting
 * `labelsShown: 26, labelsTotal: 26`, because that count comes from the declutter pass inside
 * scene.ts and is computed whether or not any label element exists. The surface a reviewer is
 * pointed at for judging the render was therefore omitting a whole visual system while its own
 * instrument asserted the system was present. An instrument that cannot be wrong is not an
 * instrument.
 *
 * The `?smaaAfterToneMapping=0|1` switch this file used to document is GONE. It never read the
 * query parameter (the only `params.get` here has always been `theme`), `SceneOptions` has no such
 * field, and `scene.ts` never passed one — and the experiment it advertised has since been run by
 * patching source and settled in docs/render-decisions.md.
 */
import { StrictMode, useEffect, useMemo, useRef, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { computeLayout } from "../fabric3d/layout";
import { createScene } from "../fabric3d/scene";
import { exposeSceneForCapture } from "../fabric3d/devHandle";
import { FabricLabels, createHoverChannel } from "../fabric3d/FabricLabels";
import type { FabricScene, SceneStats } from "../fabric3d/contract";
import { fabric } from "../core/data";
import { releaseFocusFrom } from "../app/focus-return";
import "../core/tokens.css";
// The app's base stylesheet: it is what puts `--font-ui` on <body>. Without it every label here
// inherited the UA default (Times New Roman) while the app renders Inter, so any label judgement
// made on this surface was made on the wrong font. panels-preview.tsx imports it for the same reason.
import "../app/shell.css";
// The label layer is DOM and its positioning lives entirely in this stylesheet. Mounting the
// component without it leaves 160 correctly-built elements stacked in the document flow at the top
// left, which looks exactly like "labels are broken" and is really "no stylesheet".
import "../fabric3d/Fabric3D.css";

const params = new URLSearchParams(window.location.search);
const theme = params.get("theme") === "light" ? "light" : "dark";
document.documentElement.setAttribute("data-theme", theme);

function Preview() {
  const slotRef = useRef<HTMLDivElement | null>(null);
  const sceneRef = useRef<FabricScene | null>(null);
  const [stats, setStats] = useState<SceneStats | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  /** Bumped when a scene instance is created, so the label loop re-attaches to the live handle. */
  const [epoch, setEpoch] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const hover = useMemo(() => createHoverChannel(), []);

  useEffect(() => {
    const slot = slotRef.current;
    if (!slot) return;

    /* A NEW canvas element per scene instance, created here rather than rendered by React.
       A canvas binds exactly one drawing context for its whole life, and a disposed WebGL context
       cannot be re-acquired on the same element — so under StrictMode's double-invoke the second
       mount gets `null` from getContext and three.js dies on
       "Cannot read properties of null (reading 'precision')". Reusing a React-rendered <canvas>
       ref is precisely that bug; this harness hit it, which is a decent proof that the same guard
       in Fabric3D.tsx is load-bearing rather than defensive boilerplate. */
    const canvas = slot.ownerDocument.createElement("canvas");
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    canvas.style.display = "block";
    canvas.tabIndex = 0;
    /* The slot's old contents (a previous mount's focusable canvas) go: focus leaves them first (focus-return.ts,
       third door; a no-op when focus is elsewhere). */
    releaseFocusFrom(slot, null);
    slot.replaceChildren(canvas);

    const layout = computeLayout({ devices: fabric.devices, links: fabric.links, tiers: fabric.tiers });
    const scene = createScene(
      canvas,
      {
        devices: fabric.devices,
        links: fabric.links,
        layout,
        theme,
        reducedMotion: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
      },
      {
        onEvent(e) {
          if (e.type === "stats") setStats(e.stats);
          if (e.type === "pick" && e.result) {
            setSelected(`${e.result.kind}: ${e.result.id}`);
            setSelectedId(e.result.kind === "device" ? e.result.id : null);
            if (e.result.kind === "device") scene.setSelection(e.result.id, null);
            else scene.setSelection(null, e.result.id);
          }
        },
      },
    );
    sceneRef.current = scene;
    setEpoch((e) => e + 1);
    const release = exposeSceneForCapture(scene);

    const ro = new ResizeObserver(() => {
      const r = canvas.getBoundingClientRect();
      scene.resize(r.width, r.height);
    });
    ro.observe(canvas);

    const onClick = (ev: MouseEvent) => {
      const hit = scene.pick(ev.clientX, ev.clientY);
      if (!hit) {
        scene.setSelection(null, null);
        setSelected(null);
            setSelectedId(null);
      }
    };
    const onMove = (ev: MouseEvent) => {
      const hit = scene.pick(ev.clientX, ev.clientY);
      const hoverDevice = hit?.kind === "device" ? hit.id : null;
      const hoverLink = hit?.kind === "link" ? hit.id : null;
      scene.setHover(hoverDevice, hoverLink);
      hover.set({ deviceId: hoverDevice, linkId: hoverLink });
    };
    canvas.addEventListener("click", onClick);
    canvas.addEventListener("mousemove", onMove);

    return () => {
      canvas.removeEventListener("click", onClick);
      canvas.removeEventListener("mousemove", onMove);
      ro.disconnect();
      release();
      scene.dispose();
      sceneRef.current = null;
      releaseFocusFrom(slot, null);
      slot.replaceChildren();
    };
  }, [hover]);

  return (
    <div style={{ position: "fixed", inset: 0, background: "var(--stage-bg)" }}>
      <div ref={slotRef} style={{ position: "absolute", inset: 0 }} />
      <FabricLabels
        devices={fabric.devices}
        sceneRef={sceneRef}
        epoch={epoch}
        hover={hover}
        selectedId={selectedId}
      />
      <div
        style={{
          position: "absolute",
          left: 12,
          bottom: 12,
          padding: "6px 10px",
          font: "400 11px/1.5 ui-monospace, Consolas, monospace",
          color: "var(--text-muted)",
          background: "var(--overlay)",
          border: "1px solid var(--border)",
          borderRadius: 5,
          whiteSpace: "pre",
        }}
      >
        {/* determinism: a developer HUD, and the numbers ARE the point of it. This module is not
            reachable from the product: the Vite entry is `src/main.tsx`, and this one is mounted
            only by the root `fabric-preview.html` harness, which nothing in `review/capture.mjs`
            ever loads. Nothing here is captured, so nothing here can make a capture depend on the
            machine that took it. */}
        {stats
          ? `${stats.fps.toFixed(0)} fps · ${stats.frameMs.toFixed(1)} ms · ${stats.drawCalls} calls · ` +
            `${(stats.triangles / 1000).toFixed(0)}k tris · ${stats.quality}` +
            `${stats.converged ? " · converged" : ""}`
          : "starting…"}
        {selected ? `\n${selected}` : ""}
      </div>
    </div>
  );
}

/* One root per container, however many times this module is evaluated. A re-evaluation (a Vite HMR
   update of this module or of anything it imports that is not a boundary) used to call createRoot
   on the same #root again, and React logged "calling ReactDOMClient.createRoot() on a container that
   has already been passed to createRoot()" — twice per load in the C5 audit's console capture, on
   the very surface used to catch shader-compile errors, where a real error must not hide in noise.
   The root is kept on the element and re-rendered instead. */
type RootHost = HTMLElement & { __atlasPreviewRoot?: Root };
const el = document.getElementById("root") as RootHost | null;
if (el) {
  el.__atlasPreviewRoot ??= createRoot(el);
  el.__atlasPreviewRoot.render(<StrictMode><Preview /></StrictMode>);
}
