"use client";

import { useState, type KeyboardEvent } from "react";
import type { CoreModel } from "./types";

type Plane = CoreModel["system_architecture"]["planes"][number];
type Lens = "map" | "trace" | "matrix" | "dossier";

const LENSES: Array<{ id: Lens; label: string; purpose: string }> = [
  { id: "map", label: "Map", purpose: "Structure and dependency boundaries" },
  { id: "trace", label: "Trace", purpose: "Ordered evidence lifecycle" },
  { id: "matrix", label: "Matrix", purpose: "Inputs, outputs, and owners" },
  { id: "dossier", label: "Dossier", purpose: "One complete canonical explanation" },
];

function replaceUrl(lens: Lens, entity: string) {
  const params = new URLSearchParams({ lens, entity });
  window.history.replaceState(null, "", `/system?${params}`);
}

export function SystemLens({
  planes,
  flow,
  lifecycle,
  initialLens = "map",
  initialEntity,
}: {
  planes: Plane[];
  flow: CoreModel["system_architecture"]["flow"];
  lifecycle: CoreModel["lifecycle_stages"];
  initialLens?: Lens;
  initialEntity?: string;
}) {
  const first = planes[0]?.id ?? "";
  const [lens, setLens] = useState<Lens>(initialLens);
  const [entity, setEntity] = useState(
    planes.some((plane) => plane.id === initialEntity) ? initialEntity ?? first : first,
  );
  const selected = planes.find((plane) => plane.id === entity) ?? planes[0];

  function chooseLens(next: Lens) {
    setLens(next);
    replaceUrl(next, entity);
  }

  function chooseEntity(next: string) {
    setEntity(next);
    replaceUrl(lens, next);
  }

  function moveLens(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const keyOffset = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    let next = index;
    if (keyOffset) next = (index + keyOffset + LENSES.length) % LENSES.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = LENSES.length - 1;
    else return;
    event.preventDefault();
    chooseLens(LENSES[next].id);
    document.getElementById(`system-lens-${LENSES[next].id}`)?.focus();
  }

  return (
    <div className="lens-workspace">
      <div className="lens-tabs" role="tablist" aria-label="System lenses">
        {LENSES.map((item) => (
          <button
            aria-selected={lens === item.id}
            aria-controls="system-lens-panel"
            className={lens === item.id ? "active" : ""}
            id={`system-lens-${item.id}`}
            key={item.id}
            onClick={() => chooseLens(item.id)}
            onKeyDown={(event) => moveLens(event, LENSES.indexOf(item))}
            role="tab"
            tabIndex={lens === item.id ? 0 : -1}
            type="button"
          >
            <strong>{item.label}</strong>
            <span>{item.purpose}</span>
          </button>
        ))}
      </div>

      <div className="entity-selector" aria-label="Select architecture plane">
        {planes.map((plane) => (
          <button
            aria-pressed={entity === plane.id}
            className={entity === plane.id ? "active" : ""}
            key={plane.id}
            onClick={() => chooseEntity(plane.id)}
            type="button"
          >
            <span>{String(plane.order).padStart(2, "0")}</span>
            {plane.title}
          </button>
        ))}
      </div>

      <section
        aria-labelledby={`system-lens-${lens}`}
        className="lens-panel"
        id="system-lens-panel"
        role="tabpanel"
        tabIndex={0}
      >
        {lens === "map" ? (
          <div className="architecture-map" aria-label="Six-plane architecture map">
            {planes.map((plane) => (
              <button
                className={entity === plane.id ? "active" : ""}
                key={plane.id}
                onClick={() => chooseEntity(plane.id)}
                type="button"
              >
                <span>{String(plane.order).padStart(2, "0")}</span>
                <strong>{plane.title}</strong>
                <small>{plane.outputs[0]}</small>
              </button>
            ))}
            <div className="map-contracts">
              {flow.map((edge) => (
                <p key={`${edge.from}-${edge.to}`}>
                  <code>{edge.from.replace("plane.", "")}</code>
                  <span aria-hidden="true">→</span>
                  <code>{edge.to.replace("plane.", "")}</code>
                  {edge.contract}
                </p>
              ))}
            </div>
          </div>
        ) : null}

        {lens === "trace" ? (
          <ol className="lifecycle-trace">
            {lifecycle.map((stage) => (
              <li key={stage.id}>
                <span>{String(stage.order).padStart(2, "0")}</span>
                <div>
                  <strong>{stage.label}</strong>
                  <p>{stage.question}</p>
                </div>
              </li>
            ))}
          </ol>
        ) : null}

        {lens === "matrix" ? (
          <div className="system-matrix-wrap">
            <table className="system-matrix">
              <caption className="visually-hidden">Architecture plane matrix</caption>
              <thead>
                <tr className="system-matrix-head">
                  <th scope="col">Plane</th>
                  <th scope="col">Inputs</th>
                  <th scope="col">Outputs</th>
                  <th scope="col">Owners</th>
                </tr>
              </thead>
              <tbody>
                {planes.map((plane) => (
                  <tr key={plane.id}>
                    <th scope="row">{plane.title}</th>
                    <td>{plane.inputs.join(" · ")}</td>
                    <td>{plane.outputs.join(" · ")}</td>
                    <td><code>{plane.owner_refs.join(" · ")}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {lens === "dossier" && selected ? (
          <article className="system-dossier">
            <div className="dossier-index">Plane {String(selected.order).padStart(2, "0")}</div>
            <h2>{selected.title}</h2>
            <p className="dossier-purpose">{selected.purpose}</p>
            <dl>
              <div>
                <dt>Inputs admitted</dt>
                <dd>{selected.inputs.join(" · ")}</dd>
              </div>
              <div>
                <dt>Outputs produced</dt>
                <dd>{selected.outputs.join(" · ")}</dd>
              </div>
              <div>
                <dt>Authoritative owners</dt>
                <dd>{selected.owner_refs.map((owner) => <code key={owner}>{owner}</code>)}</dd>
              </div>
              <div>
                <dt>Known downstream contracts</dt>
                <dd>
                  {flow
                    .filter((edge) => edge.from === selected.id || edge.to === selected.id)
                    .map((edge) => <p key={`${edge.from}-${edge.to}`}>{edge.contract}</p>)}
                </dd>
              </div>
            </dl>
          </article>
        ) : null}
      </section>
    </div>
  );
}
