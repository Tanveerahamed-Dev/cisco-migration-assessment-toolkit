import { releaseFocusFrom } from "../app/focus-return";
import { applyTheme, readThemePreference, THEME_STORAGE_KEY } from "../app/theme-preference";
import { createContractScene, type LinkLayer, type SceneOptions, type SceneView } from "./scene";
import { rowKey } from "./geometry";
import type { CompleteTopology, PathDocument } from "./types";
import type { SelectionTarget } from "../../../webapp/frontend/src/projectionEmbed";
import "./view.css";

export type ContractView = Readonly<{ select(target: SelectionTarget | null): void; path(value: PathDocument | null): void; dispose(): void }>;
export type ViewOptions = Readonly<SceneOptions & { makeScene?: typeof createContractScene }>;

/** Every value in this view is either supplied engine text or an explicitly labelled UI record count. */
export function createContractView(root: HTMLElement, model: CompleteTopology, options: ViewOptions): ContractView {
  const section = document.createElement("section");
  section.className = "contract-scope"; section.setAttribute("role", "region"); section.setAttribute("aria-label", "Engine topology in 3D");
  const heading = document.createElement("h2"); heading.textContent = "Topology in 3D";
  const records = document.createElement("p");
  records.className = "contract-scope-records";
  records.textContent = `Loaded records: ${model.rows.nodes.length} nodes and ${model.rows.cables.length} cables. Positions are for display.`;
  const controls = document.createElement("div"); controls.className = "contract-scope-controls"; controls.setAttribute("role", "toolbar"); controls.setAttribute("aria-label", "3D view controls");
  const nodeLabel = document.createElement("label"); nodeLabel.textContent = "Node ";
  const nodeSelect = document.createElement("select"); nodeSelect.setAttribute("aria-label", "Select a node record");
  const none = document.createElement("option"); none.value = ""; none.textContent = "No node selected"; nodeSelect.append(none);
  const nodeOptions = new Map<string, SelectionTarget>();
  for (const row of model.rows.nodes) {
    const option = document.createElement("option"); option.value = rowKey(row);
    option.textContent = row.host.state === "published" ? row.host.value : `${row.host.state}: ${row.host.reason}`;
    nodeSelect.append(option); nodeOptions.set(option.value, { list: "nodes", row: { index: row.index, pointer: row.pointer } });
  }
  nodeLabel.append(nodeSelect);
  const layerLabel = document.createElement("label"); layerLabel.textContent = "Links ";
  const layerSelect = document.createElement("select"); layerSelect.setAttribute("aria-label", "Link display layer");
  for (const [value, label] of [["cables", "Physical cable records"], ["structural_links", "Structural graph records"]] as const) {
    const option = document.createElement("option"); option.value = value; option.textContent = label; layerSelect.append(option);
  }
  layerLabel.append(layerSelect);
  const reset = document.createElement("button"); reset.type = "button"; reset.textContent = "Reset view";
  controls.append(nodeLabel, layerLabel, reset);
  const canvas = document.createElement("canvas"); canvas.className = "contract-scope-canvas";
  canvas.tabIndex = 0; canvas.setAttribute("role", "img"); canvas.setAttribute("aria-label", "3D engine topology. Drag to orbit and scroll to zoom; use the node selector for keyboard selection.");
  const viewport = document.createElement("div"); viewport.className = "contract-scope-viewport"; viewport.append(canvas);
  const selection = document.createElement("p"); selection.className = "contract-scope-selection"; selection.setAttribute("role", "status");
  const path = document.createElement("div"); path.className = "contract-scope-path"; path.setAttribute("aria-live", "polite");
  const note = document.createElement("p"); note.className = "contract-scope-note";
  note.textContent = "Only unambiguous engine endpoint joins are drawn. All records remain available in the 2D view. Path arcs show hop order, not physical cable attribution.";
  const legend = document.createElement("details"); legend.className = "contract-scope-legend";
  const legendTitle = document.createElement("summary"); legendTitle.textContent = "Engine legend and limitations";
  const list = document.createElement("ul");
  for (const entry of model.document.payload.legend.entries) {
    const item = document.createElement("li"); item.dataset.tone = entry.tone; item.dataset.stroke = entry.stroke; item.dataset.weight = entry.weight;
    item.textContent = entry.meaning; list.append(item);
  }
  for (const limitation of model.document.limitations) {
    const item = document.createElement("li"); item.textContent = limitation.text; list.append(item);
  }
  legend.append(legendTitle, list); section.append(heading, records, controls, viewport, selection, path, note, legend);
  releaseFocusFrom(root, null); root.replaceChildren(section);
  let scene: SceneView;
  try { scene = (options.makeScene ?? createContractScene)(canvas, model, options); }
  catch (error) { releaseFocusFrom(section, null); section.remove(); throw error; }
  let disposed = false;
  const onNode = (): void => options.onSelect(nodeOptions.get(nodeSelect.value) ?? null);
  const renderAction = (action: () => void): void => { if (!disposed) { try { action(); } catch { options.onFailure(); } } };
  const onLayer = (): void => renderAction(() => scene.layer(layerSelect.value as LinkLayer));
  const onReset = (): void => renderAction(() => scene.reset());
  const onStorage = (event: StorageEvent): void => { if (!disposed && (event.key === null || event.key === THEME_STORAGE_KEY)) { applyTheme(readThemePreference()); renderAction(() => scene.theme()); } };
  const media = window.matchMedia?.("(prefers-color-scheme: dark)");
  const onTheme = (): void => renderAction(() => scene.theme());
  nodeSelect.addEventListener("change", onNode); layerSelect.addEventListener("change", onLayer); reset.addEventListener("click", onReset);
  window.addEventListener("storage", onStorage); media?.addEventListener("change", onTheme);
  function select(target: SelectionTarget | null): void {
    if (disposed) return;
    nodeSelect.value = target?.list === "nodes" ? rowKey(target.row) : "";
    if (target?.list === "cables" || target?.list === "structural_links") layerSelect.value = target.list;
    releaseFocusFrom(selection, null, [nodeSelect]);
    selection.textContent = target ? `Selected ${target.list} record: ${target.row.pointer}` : "No record selected.";
    scene.select(target);
  }
  function showPath(value: PathDocument | null): void {
    if (disposed) return;
    scene.path(value);
    releaseFocusFrom(path, null, [nodeSelect, reset]); path.replaceChildren();
    const status = document.createElement("p");
    if (value === null) status.textContent = "No path query is active.";
    else {
      const style = value.payload.style.state === "published" ? value.payload.style.value : value.payload.legend.fallback;
      status.textContent = `${style.label} — ${value.payload.query.src_ip} → ${value.payload.query.dst_ip}`;
      const details = document.createElement("details");
      const title = document.createElement("summary"); title.textContent = "Complete engine path and evidence details";
      const data = document.createElement("pre"); data.textContent = JSON.stringify(value.payload, null, 2);
      details.append(title, data); path.append(details);
    }
    path.prepend(status); scene.render();
  }
  select(null); showPath(null);
  return {
    select, path: showPath,
    dispose() {
      if (disposed) return;
      disposed = true;
      nodeSelect.removeEventListener("change", onNode); layerSelect.removeEventListener("change", onLayer); reset.removeEventListener("click", onReset);
      window.removeEventListener("storage", onStorage); media?.removeEventListener("change", onTheme);
      scene.dispose(); releaseFocusFrom(section, null); section.remove();
    },
  };
}
