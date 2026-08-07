/* oxlint-disable nextjs/no-html-link-for-pages -- full-document navigation preserves the connect-src 'none' privacy boundary. */
"use client";

import { useMemo, useState } from "react";
import type { DeliveryGovernance } from "./types";
import { StateMark } from "./Shell";

type GapWorkbenchProps = {
  model: DeliveryGovernance;
  initialDisposition?: string;
  initialQuery?: string;
  initialSelected?: string[];
};

const BENEFIT_AXES = [
  "user_value",
  "risk_reduction",
  "evidence_readiness",
  "strategic_reach",
] as const;
const COST_AXES = ["implementation_effort", "operational_change_risk", "uncertainty"] as const;

function isDominated(
  candidate: DeliveryGovernance["opportunity_portfolio"]["items"][number],
  all: DeliveryGovernance["opportunity_portfolio"]["items"],
) {
  return all.some((other) => {
    if (other.id === candidate.id) return false;
    const noWorseBenefits = BENEFIT_AXES.every(
      (axis) => (other.axes[axis] ?? 0) >= (candidate.axes[axis] ?? 0),
    );
    const noWorseCosts = COST_AXES.every(
      (axis) => (other.axes[axis] ?? 6) <= (candidate.axes[axis] ?? 6),
    );
    const strictlyBetter =
      BENEFIT_AXES.some((axis) => (other.axes[axis] ?? 0) > (candidate.axes[axis] ?? 0)) ||
      COST_AXES.some((axis) => (other.axes[axis] ?? 6) < (candidate.axes[axis] ?? 6));
    return noWorseBenefits && noWorseCosts && strictlyBetter;
  });
}

function updateUrl(disposition: string, query: string, selected: string[]) {
  const params = new URLSearchParams();
  if (disposition !== "all") params.set("disposition", disposition);
  if (query.trim()) params.set("q", query.trim());
  if (selected.length) params.set("compare", selected.join(","));
  window.history.replaceState(null, "", `/gaps${params.size ? `?${params}` : ""}`);
}

export function GapWorkbench({
  model,
  initialDisposition = "all",
  initialQuery = "",
  initialSelected = [],
}: GapWorkbenchProps) {
  const [disposition, setDisposition] = useState(initialDisposition);
  const [query, setQuery] = useState(initialQuery);
  const validOpportunityIds = useMemo(
    () => new Set(model.opportunity_portfolio.items.map((item) => item.id)),
    [model.opportunity_portfolio.items],
  );
  const [selected, setSelected] = useState<string[]>(
    initialSelected.filter((id) => validOpportunityIds.has(id)).slice(0, 3),
  );
  const dispositions = useMemo(
    () => [...new Set(model.gaps.map((gap) => gap.disposition))].sort(),
    [model.gaps],
  );

  const gaps = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return model.gaps.filter((gap) => {
      if (disposition !== "all" && gap.disposition !== disposition) return false;
      if (!needle) return true;
      return [gap.id, gap.title, gap.problem, gap.owner_role, gap.next_actions.join(" ")]
        .join(" ")
        .toLowerCase()
        .includes(needle);
    });
  }, [disposition, model.gaps, query]);

  function toggleOpportunity(id: string) {
    setSelected((current) => {
      const next = current.includes(id)
        ? current.filter((item) => item !== id)
        : current.length >= 3
          ? current
          : [...current, id];
      updateUrl(disposition, query, next);
      return next;
    });
  }

  const compared = model.opportunity_portfolio.items.filter((item) => selected.includes(item.id));

  return (
    <>
      <section className="workspace-section" id="decisions">
        <header className="subsection-heading">
          <div>
            <span>01</span>
            <h2>Owner decision queue</h2>
          </div>
          <p>Open choices change the product boundary or evidence burden. They are not silently converted into engineering tickets.</p>
        </header>
        <div className="decision-queue">
          {model.decision_queue.map((decision, index) => (
            <details key={decision.id}>
              <summary>
                <span>D-{String(index + 1).padStart(2, "0")}</span>
                <div>
                  <StateMark state={decision.status} />
                  <h3>{decision.title}</h3>
                  <p>{decision.current_recommendation}</p>
                </div>
                <strong>{decision.authority}</strong>
              </summary>
              <div className="decision-detail">
                <div>
                  <h4>Options</h4>
                  <ol>{decision.options.map((option) => <li key={option}>{option}</li>)}</ol>
                </div>
                <div>
                  <h4>Evidence still needed</h4>
                  <ul>{decision.evidence_needed.map((item) => <li key={item}>{item}</li>)}</ul>
                </div>
                <div>
                  <h4>Affected gaps</h4>
                  {decision.gap_refs.map((gap) => <a href={`#${gap}`} key={gap}>{gap}</a>)}
                </div>
              </div>
            </details>
          ))}
        </div>
      </section>

      <section className="workspace-section" id="opportunities">
        <header className="subsection-heading">
          <div>
            <span>02</span>
            <h2>Transparent opportunity portfolio</h2>
          </div>
          <p>{model.opportunity_portfolio.ranking_rule}</p>
        </header>
        <div className="opportunity-axis-legend">
          {model.opportunity_axes.map((axis) => (
            <span key={axis.id}><strong>{axis.id.replace("axis.", "").replaceAll("-", " ")}</strong>{axis.five_means}</span>
          ))}
        </div>
        <div className="opportunity-grid">
          {model.opportunity_portfolio.items.map((opportunity) => {
            const dominated = isDominated(opportunity, model.opportunity_portfolio.items);
            const isSelected = selected.includes(opportunity.id);
            return (
              <article className={isSelected ? "selected" : ""} key={opportunity.id}>
                <div className="opportunity-topline">
                  <StateMark state={dominated ? "dominated" : "pareto frontier"} />
                  <span>{opportunity.horizon}</span>
                </div>
                <h3>{opportunity.title}</h3>
                <p>{opportunity.axis_notes}</p>
                <div className="axis-bars">
                  {Object.entries(opportunity.axes).map(([axis, value]) => (
                    <div key={axis}>
                      <span>{axis.replaceAll("_", " ")}</span>
                      <i><i style={{ width: `${value * 20}%` }} /></i>
                      <strong>{value}</strong>
                    </div>
                  ))}
                </div>
                <label className="compare-check">
                  <input
                    checked={isSelected}
                    disabled={!isSelected && selected.length >= 3}
                    onChange={() => toggleOpportunity(opportunity.id)}
                    type="checkbox"
                  />
                  Compare {selected.length >= 3 && !isSelected ? "(maximum three)" : ""}
                </label>
              </article>
            );
          })}
        </div>
        {compared.length ? (
          <div className="comparison-table-wrap">
            <table className="comparison-table">
              <caption className="visually-hidden">Selected opportunity comparison</caption>
              <thead><tr><th scope="col">Axis</th>{compared.map((item) => <th scope="col" key={item.id}>{item.title}</th>)}</tr></thead>
              <tbody>
                {Object.keys(compared[0].axes).map((axis) => (
                  <tr key={axis}>
                    <th scope="row">{axis.replaceAll("_", " ")}</th>
                    {compared.map((item) => <td key={item.id}>{item.axes[axis]}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      <section className="workspace-section" id="gaps">
        <header className="subsection-heading">
          <div>
            <span>03</span>
            <h2>Actionable gap ledger</h2>
          </div>
          <p>Every gap has a disposition, owner role, smallest actions, and acceptance evidence. Missing capability and missing evidence remain distinct.</p>
        </header>
        <div className="explorer-controls">
          <label>
            <span>Disposition</span>
            <select
              value={disposition}
              onChange={(event) => {
                setDisposition(event.target.value);
                updateUrl(event.target.value, query, selected);
              }}
            >
              <option value="all">All dispositions</option>
              {dispositions.map((item) => <option value={item} key={item}>{item}</option>)}
            </select>
          </label>
          <label className="search-field">
            <span>Find a gap</span>
            <input
              type="search"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                updateUrl(disposition, event.target.value, selected);
              }}
              placeholder="stateful flow, PKI, wireless…"
            />
          </label>
        </div>
        <p className="result-summary" aria-live="polite"><strong>{gaps.length}</strong> of {model.gaps.length} gaps</p>
        <div className="gap-list">
          {gaps.map((gap) => (
            <details id={gap.id} key={gap.id}>
              <summary>
                <div>
                  <code>{gap.id}</code>
                  <h3>{gap.title}</h3>
                </div>
                <span>{gap.priority}</span>
                <StateMark state={gap.disposition} />
                <strong>{gap.owner_role}</strong>
              </summary>
              <div className="gap-detail">
                <p>{gap.problem}</p>
                <div>
                  <section>
                    <h4>Next actions</h4>
                    <ol>{gap.next_actions.map((item) => <li key={item}>{item}</li>)}</ol>
                  </section>
                  <section>
                    <h4>Acceptance evidence</h4>
                    <ul>{gap.acceptance_evidence.map((item) => <li key={item}>{item}</li>)}</ul>
                  </section>
                </div>
                <a className="text-link" href={`/ask?target=${encodeURIComponent(gap.id)}`}>Compile an enhancement brief →</a>
              </div>
            </details>
          ))}
        </div>
        {gaps.length === 0 ? (
          <div className="empty-state">
            <strong>No gap matches this view.</strong>
            <p>Clear the filters; no missing record is being rendered as a healthy state.</p>
            <button
              type="button"
              onClick={() => {
                setDisposition("all");
                setQuery("");
                updateUrl("all", "", selected);
              }}
            >
              Clear gap filters
            </button>
          </div>
        ) : null}
      </section>
    </>
  );
}
