"use client";

/* oxlint-disable nextjs/no-html-link-for-pages -- lab selections are stable full-document deep links. */

import { useMemo, useState, type KeyboardEvent } from "react";
import type { Lab, OwnerRef } from "./types";
import { StateMark } from "./Shell";
import styles from "./LabsExplorer.module.css";

type LabsExplorerProps = {
  labs: Lab[];
  owners: OwnerRef[];
  initialLab?: string;
  initialStep?: number;
};

type WalkthroughStep = {
  label: string;
  title: string;
  instruction: string;
  resultLabel: string;
  result: string;
};

function sourceHref(path: string): string {
  return `/source/${path.split("/").map(encodeURIComponent).join("/")}`;
}

function stepsFor(lab: Lab): WalkthroughStep[] {
  return [
    {
      label: "Bound",
      title: "Read the claim boundary",
      instruction: lab.objective,
      resultLabel: "Support state",
      result: `The underlying product capability is ${lab.underlying_support_state}; the lab itself is ${lab.content_role}.`,
    },
    {
      label: "Arrange",
      title: "Stage only synthetic inputs",
      instruction: lab.interaction,
      resultLabel: "Data boundary",
      result: lab.data_policy,
    },
    {
      label: "Observe",
      title: "Inspect the bounded learning result",
      instruction: "Follow the declared interaction without importing, collecting, or persisting evidence.",
      resultLabel: "This walkthrough can demonstrate",
      result: lab.proves,
    },
    {
      label: "Challenge",
      title: "Try to over-claim—and stop",
      instruction: "Compare the demonstrated concept with the unsupported remainder before drawing a conclusion.",
      resultLabel: "This walkthrough cannot demonstrate",
      result: lab.does_not_prove,
    },
  ];
}

function clampStep(step: number | undefined): number {
  if (!Number.isFinite(step)) return 0;
  return Math.max(0, Math.min(3, Math.trunc(step ?? 0)));
}

export function LabsExplorer({ labs, owners, initialLab, initialStep }: LabsExplorerProps) {
  const selected = labs.find((lab) => lab.id === initialLab) ?? labs[0];
  const [step, setStep] = useState(clampStep(initialStep));
  const ownerMap = useMemo(() => new Map(owners.map((owner) => [owner.id, owner])), [owners]);
  const walkthrough = stepsFor(selected);
  const activeStep = walkthrough[step];
  const stateCounts = labs.reduce<Record<string, number>>((counts, lab) => {
    counts[lab.underlying_support_state] = (counts[lab.underlying_support_state] ?? 0) + 1;
    return counts;
  }, {});

  function moveTo(next: number) {
    const bounded = clampStep(next);
    setStep(bounded);
    const params = new URLSearchParams({ lab: selected.id, step: String(bounded + 1) });
    window.history.replaceState(null, "", `/labs?${params}`);
  }

  function moveTab(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const keyOffset = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    let next = index;
    if (keyOffset) next = (index + keyOffset + walkthrough.length) % walkthrough.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = walkthrough.length - 1;
    else return;
    event.preventDefault();
    moveTo(next);
    document.getElementById(`lab-step-${next + 1}`)?.focus();
  }

  return (
    <div className={styles.workspace}>
      <section className={styles.labContract} aria-labelledby="lab-contract-title">
        <div>
          <p>Truth-preserving training contract</p>
          <h2 id="lab-contract-title">Explore the model without changing the model.</h2>
          <span>
            Every lab is deterministic, repository-owned, synthetic, read-only, and advisory. No
            result becomes assessment evidence or an implementation claim.
          </span>
        </div>
        <dl>
          <div><dt>Total</dt><dd>{labs.length}</dd></div>
          {Object.entries(stateCounts).sort().map(([state, count]) => (
            <div key={state}><dt>{state}</dt><dd>{count}</dd></div>
          ))}
        </dl>
      </section>

      <section className={styles.labIndex} aria-labelledby="lab-index-title">
        <header>
          <p>All governed labs</p>
          <h2 id="lab-index-title">Choose a bounded scenario.</h2>
        </header>
        <div>
          {labs.map((lab) => (
            <a
              aria-current={lab.id === selected.id ? "page" : undefined}
              href={`/labs?lab=${encodeURIComponent(lab.id)}&step=1`}
              key={lab.id}
            >
              <span>{String(lab.number).padStart(2, "0")}</span>
              <StateMark state={lab.underlying_support_state} />
              <strong>{lab.title}</strong>
              <small>{lab.objective}</small>
            </a>
          ))}
        </div>
      </section>

      <section className={styles.walkthrough} aria-labelledby="active-lab-title">
        <header>
          <div>
            <p>Lab {String(selected.number).padStart(2, "0")} · {selected.content_role}</p>
            <h2 id="active-lab-title">{selected.title}</h2>
            <code>{selected.id}</code>
          </div>
          <div className={styles.supportSummary}>
            <span>Underlying product state</span>
            <StateMark state={selected.underlying_support_state} />
            <strong>{selected.mutates_assessment_truth ? "Mutating" : "Never mutates truth"}</strong>
          </div>
        </header>

        <div className={styles.transparencyGrid}>
          <article><span>Objective</span><p>{selected.objective}</p></article>
          <article><span>Interaction</span><p>{selected.interaction}</p></article>
          <article><span>Data policy</span><p>{selected.data_policy}</p></article>
          <article className={styles.canProve}><span>Can demonstrate</span><p>{selected.proves}</p></article>
          <article className={styles.cannotProve}><span>Cannot demonstrate</span><p>{selected.does_not_prove}</p></article>
        </div>

        <div className={styles.stepper}>
          <div className={styles.stepTabs} role="tablist" aria-label="Lab walkthrough steps">
            {walkthrough.map((item, index) => (
              <button
                aria-controls="lab-step-panel"
                aria-selected={index === step}
                id={`lab-step-${index + 1}`}
                key={item.label}
                onClick={() => moveTo(index)}
                onKeyDown={(event) => moveTab(event, index)}
                role="tab"
                tabIndex={index === step ? 0 : -1}
                type="button"
              >
                <span>{index + 1}</span>
                {item.label}
              </button>
            ))}
          </div>

          <div
            aria-labelledby={`lab-step-${step + 1}`}
            className={styles.stepPanel}
            id="lab-step-panel"
            role="tabpanel"
            tabIndex={0}
          >
            <div className={styles.progressLine}>
              <span>Step {step + 1} of {walkthrough.length}</span>
              <progress aria-label="Lab progress" max={walkthrough.length} value={step + 1} />
            </div>
            <p className={styles.stepLabel}>{activeStep.label}</p>
            <h3>{activeStep.title}</h3>
            <p>{activeStep.instruction}</p>
            <output className={styles.deterministicResult} aria-live="polite">
              <strong>{activeStep.resultLabel}</strong>
              <p>{activeStep.result}</p>
            </output>
            <div className={styles.stepActions}>
              <button disabled={step === 0} onClick={() => moveTo(step - 1)} type="button">← Previous</button>
              {step < walkthrough.length - 1 ? (
                <button onClick={() => moveTo(step + 1)} type="button">Next boundary →</button>
              ) : (
                <a href={`/ask?q=${encodeURIComponent(selected.title)}`}>Resolve related records →</a>
              )}
            </div>
          </div>
        </div>

        <footer className={styles.ownerFooter}>
          <span>Claim owners</span>
          <div>
            {selected.owner_refs.map((ownerId) => {
              const owner = ownerMap.get(ownerId);
              return owner ? (
                <a href={sourceHref(owner.path)} key={ownerId}>
                  <code>{ownerId}</code>
                  <span>{owner.path}</span>
                </a>
              ) : <code key={ownerId}>{ownerId}</code>;
            })}
          </div>
        </footer>
      </section>
    </div>
  );
}
