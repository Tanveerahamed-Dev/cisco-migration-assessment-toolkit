/* oxlint-disable nextjs/no-html-link-for-pages -- local full-document navigation is deliberate for the offline site. */
import type { Metadata } from "vinext/shims/metadata";
import { core, ownerById } from "../atlas/data";
import { AtlasShell, SectionHeading } from "../atlas/Shell";
import styles from "../atlas/Workspace.module.css";

export const metadata: Metadata = {
  title: "Digital Thread & Trace | Atlas Master Reference",
  description:
    "A deterministic, source-bound traversal of the typed Atlas digital thread with explicit abstention.",
};

type TracePageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function sourceHref(path: string): string {
  return `/source/${path.split("/").map(encodeURIComponent).join("/")}`;
}

export default async function TracePage({ searchParams }: TracePageProps) {
  const params = (await searchParams) ?? {};
  const requestedStage = first(params.stage);
  const requestedRecord = requestedStage
    ? core.digital_thread.stages.find((stage) => stage.id === requestedStage)
    : undefined;
  const invalidRequest = Boolean(requestedStage && !requestedRecord);
  const selected = requestedRecord ?? core.digital_thread.stages[0];
  const selectedIndex = selected
    ? core.digital_thread.stages.findIndex((stage) => stage.id === selected.id)
    : -1;
  const visibleStages = selectedIndex >= 0
    ? core.digital_thread.stages.slice(selectedIndex)
    : core.digital_thread.stages;

  return (
    <AtlasShell active="trace" eyebrow="Typed digital thread">
      <header className="page-title">
        <h1>Traverse the declared chain without inventing a missing edge.</h1>
        <p>
          This is a deterministic model of the required business-to-learning thread. It is not
          evidence that every stage executed for a particular assessment.
        </p>
      </header>

      <section className="workspace-section">
        <SectionHeading
          index="01"
          title="Trace builder"
          description="Choose a canonical start stage. The selection persists in the URL and the remaining ordered chain is rendered from owned content."
        />
        <form action="/trace" className={styles.traceForm} method="get">
          <label>
            <span>Start at canonical stage</span>
            <select defaultValue={selected?.id} name="stage">
              {core.digital_thread.stages.map((stage) => (
                <option key={stage.id} value={stage.id}>
                  {String(stage.order).padStart(2, "0")} - {stage.label}
                </option>
              ))}
            </select>
          </label>
          <button type="submit">Build trace</button>
        </form>
        {invalidRequest ? (
          <output className={styles.abstention}>
            <strong>Trace abstained: unknown stage</strong>
            The requested identifier <code>{requestedStage}</code> is not in the canonical
            digital-thread denominator. No substitute relationship was inferred; the complete
            declared thread is shown from its first stage.
          </output>
        ) : null}
        <div className={styles.notice}>
          <strong>Global abstention rule</strong>
          {core.digital_thread.abstention_rule}
        </div>
      </section>

      {selected ? (
        <section className="workspace-section" id={selected.id}>
          <SectionHeading
            index="02"
            title={`Selected: ${selected.label}`}
            description="The selected record states the expected entity, question, owners, outgoing relation, and exact reason to stop."
          />
          <article className={`${styles.card} ${styles.wide}`}>
            <code>{selected.id}</code>
            <h3>{selected.entity_type}</h3>
            <dl>
              <div><dt>Question</dt><dd>{selected.question}</dd></div>
              <div><dt>Relation to next</dt><dd>{selected.relation_to_next ?? "Terminal stage; no outgoing relation"}</dd></div>
              <div><dt>Abstention</dt><dd>{selected.abstention}</dd></div>
              <div><dt>Owners</dt><dd>{selected.owner_refs.join(", ")}</dd></div>
            </dl>
          </article>
        </section>
      ) : null}

      <section className="workspace-section">
        <SectionHeading
          index="03"
          title="Ordered source-bound thread"
          description={`${visibleStages.length} stage${visibleStages.length === 1 ? "" : "s"} remain from the selected start. Each arrow is typed; missing evidence stops the traversal.`}
        />
        <ol className={styles.thread} start={selected?.order ?? 1}>
          {visibleStages.map((stage) => (
            <li id={stage.id} key={stage.id}>
              <span className={styles.threadIndex}>{String(stage.order).padStart(2, "0")}</span>
              <div>
                <h3>{stage.label}</h3>
                <code>{stage.entity_type}</code>
                {stage.relation_to_next ? <span className={styles.relation}>{stage.relation_to_next} -&gt;</span> : <span className={styles.relation}>terminal</span>}
              </div>
              <div>
                <p>{stage.question}</p>
                <p><strong>Stop when:</strong> {stage.abstention}</p>
                <ul className={styles.tagList} aria-label={`${stage.label} source owners`}>
                  {stage.owner_refs.map((ownerId) => {
                    const owner = ownerById.get(ownerId);
                    return (
                      <li key={ownerId}>
                        {owner ? <a href={sourceHref(owner.path)}>{ownerId}</a> : ownerId}
                      </li>
                    );
                  })}
                </ul>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="workspace-section">
        <SectionHeading
          index="04"
          title="What this trace does not prove"
          description="Declared structure and an executed assessment are different evidence classes."
        />
        <div className={styles.abstention}>
          <strong>No synthetic-to-field promotion</strong>
          This view does not claim that evidence was collected, a detector ran, a human approved
          a plan, execution succeeded, or an outcome was measured. Those claims require
          assessment-bound receipts linked at each stage.
        </div>
      </section>
    </AtlasShell>
  );
}
