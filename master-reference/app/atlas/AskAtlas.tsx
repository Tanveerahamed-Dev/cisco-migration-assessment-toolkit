/* oxlint-disable nextjs/no-html-link-for-pages -- full-document navigation preserves connect-src 'none'. */

import {
  capabilities,
  core,
  deliveryGovernance,
  horizon,
  ownerById,
} from "./data";
import { StateMark } from "./Shell";
import { RepositoryQuery } from "./RepositoryQuery";
import styles from "./AskAtlas.module.css";

type AskAtlasProps = {
  initialQuery?: string;
  initialTarget?: string;
};

type IndexKind = "capability" | "gap" | "invariant" | "horizon" | "owner";

type IndexRecord = {
  id: string;
  kind: IndexKind;
  title: string;
  summary: string;
  detail?: string;
  state?: string;
  href: string;
  ownerRefs: string[];
  searchText: string;
};

const QUESTION_TEMPLATES = [
  "What owns lifecycle authority?",
  "What is missing for stateful traffic?",
  "Why can unknown not mean healthy?",
  "Which horizon signals affect cloud networking?",
  "What is the current white-label capability?",
] as const;

const UNSUPPORTED_PROOF_TERMS = new Set([
  "assertion",
  "assertions",
  "branch",
  "branches",
  "caller",
  "callers",
  "coverage",
  "executed",
  "execution",
  "line",
  "lines",
  "runtime",
  "test",
  "tests",
  "trace",
  "traces",
]);

function sourceHref(path: string): string {
  return `/source/${path.split("/").map(encodeURIComponent).join("/")}`;
}

function normalize(value: string): string[] {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9._/-]+/g, " ")
    .split(/\s+/)
    .filter((token) => token.length > 1);
}

function makeIndex(): IndexRecord[] {
  const capabilityRecords: IndexRecord[] = capabilities.map((capability) => ({
    id: capability.id,
    kind: "capability",
    title: capability.title,
    summary: capability.current_scope,
    detail: `Declared state: ${capability.state}.`,
    state: capability.state,
    href: `/capabilities?q=${encodeURIComponent(capability.id)}`,
    ownerRefs: capability.owner_refs ?? [],
    searchText: [
      capability.id,
      capability.title,
      capability.current_scope,
      capability.state,
      capability.domain_id,
      ...(capability.owner_refs ?? []),
      ...(capability.gap_refs ?? []),
    ].join(" "),
  }));

  const gapRecords: IndexRecord[] = deliveryGovernance.gaps.map((gap) => ({
    id: gap.id,
    kind: "gap",
    title: gap.title,
    summary: gap.problem,
    detail: `${gap.priority} · ${gap.disposition} · owner role: ${gap.owner_role}`,
    state: gap.disposition,
    href: `/gaps#${encodeURIComponent(gap.id)}`,
    ownerRefs: [],
    searchText: [
      gap.id,
      gap.title,
      gap.problem,
      gap.priority,
      gap.disposition,
      gap.owner_role,
      ...gap.next_actions,
      ...gap.acceptance_evidence,
    ].join(" "),
  }));

  const invariantRecords: IndexRecord[] = deliveryGovernance.invariants.map((invariant) => ({
    id: invariant.id,
    kind: "invariant",
    title: invariant.id.replace("invariant.", "").replaceAll("-", " "),
    summary: invariant.statement,
    href: `/system#${encodeURIComponent(invariant.id)}`,
    ownerRefs: invariant.owner_refs,
    searchText: [invariant.id, invariant.statement, ...invariant.owner_refs].join(" "),
  }));

  const horizonRecords: IndexRecord[] = horizon.signals.map((signal) => ({
    id: signal.id,
    kind: "horizon",
    title: signal.title,
    summary: signal.current_coverage,
    detail: `${signal.disposition} · ${signal.maturity}. ${signal.uncertainty}`,
    state: signal.disposition,
    href: `/gaps#horizon`,
    ownerRefs: [],
    searchText: [
      signal.id,
      signal.theme,
      signal.title,
      signal.maturity,
      signal.disposition,
      signal.current_coverage,
      signal.business_relevance,
      signal.uncertainty,
      signal.rationale,
      ...signal.affected_capability_refs,
      ...signal.source_refs,
    ].join(" "),
  }));

  const ownerRecords: IndexRecord[] = core.owners.map((owner) => ({
    id: owner.id,
    kind: "owner",
    title: owner.path,
    summary: owner.claim_scope,
    detail: [owner.kind, owner.symbol].filter(Boolean).join(" · "),
    href: sourceHref(owner.path),
    ownerRefs: [owner.id],
    searchText: [
      owner.id,
      owner.path,
      owner.kind,
      owner.symbol ?? "",
      owner.claim_scope,
    ].join(" "),
  }));

  return [
    ...capabilityRecords,
    ...gapRecords,
    ...invariantRecords,
    ...horizonRecords,
    ...ownerRecords,
  ];
}

const INDEX = makeIndex();

function score(record: IndexRecord, query: string, tokens: string[]): number {
  const haystack = record.searchText.toLowerCase();
  const title = record.title.toLowerCase();
  const id = record.id.toLowerCase();
  const exact = query.trim().toLowerCase();
  let value = 0;
  if (id === exact) value += 100;
  if (title === exact) value += 80;
  if (id.includes(exact) && exact.length > 2) value += 24;
  if (title.includes(exact) && exact.length > 2) value += 18;
  for (const token of tokens) {
    if (id.includes(token)) value += 8;
    if (title.includes(token)) value += 6;
    if (haystack.includes(token)) value += 2;
  }
  return value;
}

function referenceLabel(index: number): string {
  return `[${index + 1}]`;
}

function EnhancementBrief({ target }: { target: string }) {
  const gap = deliveryGovernance.gaps.find((item) => item.id === target);
  if (!gap) {
    return (
      <section className={styles.abstention} role="alert">
        <strong>No enhancement brief compiled.</strong>
        <p>
          <code>{target}</code> is not an exact ID in the current gap ledger. Atlas will not
          guess a target. Choose a stable gap link from the ledger below.
        </p>
        <a href="/gaps#gaps">Open the canonical gap ledger →</a>
      </section>
    );
  }

  const linkedCapabilities = capabilities.filter((capability) =>
    capability.gap_refs?.includes(gap.id),
  );
  const linkedOpportunities = deliveryGovernance.opportunity_portfolio.items.filter((item) =>
    item.gap_refs.includes(gap.id),
  );
  const linkedDecisions = deliveryGovernance.decision_queue.filter((item) =>
    item.gap_refs.includes(gap.id),
  );
  const linkedCapabilityIds = new Set(linkedCapabilities.map((item) => item.id));
  const linkedSignals = horizon.signals.filter((signal) =>
    signal.affected_capability_refs.some((capability) => linkedCapabilityIds.has(capability)),
  );
  const linkedOwnerIds = new Set(
    linkedCapabilities.flatMap((capability) => capability.owner_refs ?? []),
  );
  const linkedOwners = [...linkedOwnerIds]
    .map((id) => ownerById.get(id))
    .filter((owner): owner is NonNullable<typeof owner> => Boolean(owner));
  const linkedInvariants = deliveryGovernance.invariants.filter((invariant) =>
    invariant.owner_refs.some((owner) => linkedOwnerIds.has(owner)),
  );
  const baselineInvariants = deliveryGovernance.invariants.filter((invariant) =>
    [
      "invariant.one-fact-owner",
      "invariant.unknown-not-healthy",
      "invariant.proposer-not-verifier",
      "invariant.static-reference",
    ].includes(invariant.id),
  );
  const gateInvariants = [...new Map(
    [...linkedInvariants, ...baselineInvariants].map((invariant) => [invariant.id, invariant]),
  ).values()];
  const relatedGapIds = new Set(
    linkedOpportunities.flatMap((opportunity) => opportunity.gap_refs).filter((id) => id !== gap.id),
  );
  const relatedGaps = deliveryGovernance.gaps.filter((item) => relatedGapIds.has(item.id));
  const firstAction = gap.next_actions[0] ?? "Define a bounded, owned next action.";
  const firstEvidence = gap.acceptance_evidence[0] ?? "Record independently reviewable evidence.";
  const firstCapability = linkedCapabilities[0];

  return (
    <section className={styles.brief} aria-labelledby="enhancement-brief-title">
      <header className={styles.briefHeader}>
        <div>
          <p>Deterministic enhancement compiler</p>
          <h2 id="enhancement-brief-title">{gap.title}</h2>
          <code>{gap.id}</code>
        </div>
        <div>
          <StateMark state={gap.disposition} />
          <span>{gap.priority}</span>
        </div>
      </header>

      <div className={styles.briefGrid}>
        <article>
          <span>01</span>
          <h3>Desired outcome</h3>
          <p>
            Advance this gap only when every declared acceptance obligation is satisfied and
            independently reviewable.
          </p>
          <a href={`/gaps#${encodeURIComponent(gap.id)}`}>Gap record [G1]</a>
        </article>
        <article>
          <span>02</span>
          <h3>Current behavior, evidence and uncertainty</h3>
          <p>{gap.problem}</p>
          {linkedCapabilities.length ? (
            <ul>
              {linkedCapabilities.map((capability) => (
                <li key={capability.id}>
                  <strong>{capability.state}</strong> — {capability.current_scope}{" "}
                  <a href={`/capabilities?q=${encodeURIComponent(capability.id)}`}>
                    [{capability.id}]
                  </a>
                </li>
              ))}
            </ul>
          ) : (
            <p className={styles.unknown}>
              No capability record links to this gap; affected product scope remains unresolved.
            </p>
          )}
          <p className={styles.unknown}>
            Acceptance evidence below is required future proof, not proof already held.
          </p>
        </article>
        <article>
          <span>03</span>
          <h3>Missing stages</h3>
          <ol>{gap.next_actions.map((action) => <li key={action}>{action}</li>)}</ol>
        </article>
        <article>
          <span>04</span>
          <h3>Alternatives</h3>
          <ol>
            <li><strong>Declared path:</strong> execute the listed next actions in order.</li>
            <li><strong>Evidence-first:</strong> seek the first acceptance obligation before expanding scope.</li>
            <li><strong>Do nothing:</strong> retain <em>{gap.disposition}</em>, keep the gap visible, and accept the stated limitation.</li>
          </ol>
        </article>
        <article className={styles.wide}>
          <span>05</span>
          <h3>Dependency closure</h3>
          <div className={styles.closureGrid}>
            <div><strong>{linkedCapabilities.length}</strong><span>capabilities</span></div>
            <div><strong>{linkedOwners.length}</strong><span>code/doc owners</span></div>
            <div><strong>{linkedDecisions.length}</strong><span>owner decisions</span></div>
            <div><strong>{linkedOpportunities.length}</strong><span>opportunities</span></div>
            <div><strong>{linkedSignals.length}</strong><span>horizon signals</span></div>
            <div><strong>{relatedGaps.length}</strong><span>coupled gaps</span></div>
          </div>
          {[...linkedCapabilities, ...relatedGaps].length ? (
            <div className={styles.tagLinks}>
              {linkedCapabilities.map((capability) => (
                <a href={`/capabilities?q=${encodeURIComponent(capability.id)}`} key={capability.id}>{capability.id}</a>
              ))}
              {relatedGaps.map((item) => (
                <a href={`/gaps#${encodeURIComponent(item.id)}`} key={item.id}>{item.id}</a>
              ))}
            </div>
          ) : null}
        </article>
        <article className={styles.wide}>
          <span>06</span>
          <h3>Known owners and downstream surfaces</h3>
          <p>Gap owner role: <strong>{gap.owner_role}</strong>.</p>
          {linkedOwners.length ? (
            <div className={styles.ownerGrid}>
              {linkedOwners.map((owner) => (
                <a href={sourceHref(owner.path)} key={owner.id}>
                  <code>{owner.id}</code>
                  <strong>{owner.path}</strong>
                  <span>{owner.claim_scope}</span>
                </a>
              ))}
            </div>
          ) : (
            <p className={styles.unknown}>No linked code/document owner is asserted by the catalog.</p>
          )}
        </article>
        <article>
          <span>07</span>
          <h3>Smallest safe vertical slice</h3>
          <p><strong>Action:</strong> {firstAction}</p>
          <p><strong>Proof:</strong> {firstEvidence}</p>
          <p>
            <strong>Scope:</strong>{" "}
            {firstCapability
              ? `Begin with ${firstCapability.id}; do not imply parity beyond its declared scope.`
              : "First bind the gap to an explicit capability and owner before implementation."}
          </p>
        </article>
        <article>
          <span>08</span>
          <h3>Tests and release gates</h3>
          <h4>Acceptance proof</h4>
          <ul>{gap.acceptance_evidence.map((evidence) => <li key={evidence}>{evidence}</li>)}</ul>
          <h4>Invariant gates to re-evaluate</h4>
          <ul>
            {gateInvariants.map((invariant) => (
              <li key={invariant.id}>
                {invariant.statement}{" "}
                <a href={`/system#${encodeURIComponent(invariant.id)}`}>
                  [{invariant.id}]
                </a>
              </li>
            ))}
          </ul>
        </article>
        <article>
          <span>09</span>
          <h3>Rollback and kill criteria</h3>
          <ul>
            <li>Kill the slice if it requires violating any protected invariant listed above.</li>
            <li>Rollback a favorable capability-state change when its declared acceptance proof is absent or stale.</li>
            <li>Stop when affected ownership cannot be reconciled; this brief grants no implementation or publication authority.</li>
          </ul>
        </article>
        <article>
          <span>10</span>
          <h3>Residual unsupported behavior and outcome review</h3>
          <p>
            Until the proof obligations pass, the gap and every linked non-current capability retain
            their present state. The brief itself changes no product truth.
          </p>
          <p>
            Review outcome by checking each acceptance item, reconciling the listed owners, recording
            independent verification, and explicitly restating what remains unsupported.
          </p>
        </article>
      </div>
    </section>
  );
}

export function AskAtlas({ initialQuery = "", initialTarget = "" }: AskAtlasProps) {
  const query = initialQuery;
  const tokens = normalize(query);
  const asksForUnavailableProof = tokens.some((token) => UNSUPPORTED_PROOF_TERMS.has(token));
  const ranked = query.trim()
    ? INDEX
      .map((record) => ({ record, score: score(record, query, tokens) }))
      .filter((entry) => entry.score > 0)
      .sort((left, right) => right.score - left.score || left.record.id.localeCompare(right.record.id))
      .slice(0, 8)
    : [];

  return (
    <div className={styles.workspace}>
      {initialTarget ? <EnhancementBrief target={initialTarget} /> : null}

      <section className={styles.askPanel} aria-labelledby="ask-atlas-title">
        <header>
          <div>
            <p>Local deterministic index</p>
            <h2 id="ask-atlas-title">Ask for an owner, boundary, gap or horizon signal.</h2>
          </div>
          <span>{INDEX.length} indexed records · zero runtime calls</span>
        </header>

        <form
          action="/ask"
          className={styles.searchForm}
          method="get"
        >
          <label htmlFor="atlas-query">Question or stable ID</label>
          <div>
            <input
              defaultValue={query}
              id="atlas-query"
              name="q"
              placeholder="What is missing for stateful traffic?"
              type="search"
            />
            <button type="submit">Resolve from records</button>
          </div>
        </form>

        <div className={styles.templates} aria-label="Question templates">
          {QUESTION_TEMPLATES.map((template) => (
            <a href={`/ask?q=${encodeURIComponent(template)}`} key={template}>
              {template}
            </a>
          ))}
        </div>

        {!query.trim() ? (
          <div className={styles.emptyAnswer}>
            <strong>No question selected.</strong>
            <p>
              Atlas searches exact repository-owned catalog records. It does not send a prompt,
              generate a plausible answer, or convert advisory content into product truth.
            </p>
          </div>
        ) : asksForUnavailableProof ? (
          <output className={styles.abstention}>
            <strong>Atlas abstains from the requested proof claim.</strong>
            <p>
              The curated catalog cannot establish line/test/runtime proof. The exact repository
              projection below will return citable structural records when available and will retain
              their emitted coverage, runtime, and explanation-depth limitations.
            </p>
            <a href="/source">Open Source Explorer →</a>
          </output>
        ) : ranked.length ? (
          <div className={styles.answer} aria-live="polite">
            <header>
              <p>Deterministic answer set</p>
              <strong>{ranked.length} cited records match the indexed terms.</strong>
              <span>Rank = exact ID/title, then stable lexical overlap. No semantic inference.</span>
            </header>
            <ol>
              {ranked.map(({ record }, index) => (
                <li key={`${record.kind}-${record.id}`}>
                  <div>
                    <span>{record.kind}</span>
                    {record.state ? <StateMark state={record.state} /> : null}
                  </div>
                  <h3>{record.title}</h3>
                  <p>{record.summary}</p>
                  {record.detail ? <small>{record.detail}</small> : null}
                  {record.ownerRefs.length ? (
                    <div className={styles.ownerRefs}>
                      {record.ownerRefs.map((owner) => {
                        const ownerRecord = ownerById.get(owner);
                        return ownerRecord ? (
                          <a href={sourceHref(ownerRecord.path)} key={owner}>
                            {owner}
                          </a>
                        ) : <code key={owner}>{owner}</code>;
                      })}
                    </div>
                  ) : null}
                  <a className={styles.citation} href={record.href}>
                    {referenceLabel(index)} {record.id}
                  </a>
                </li>
              ))}
            </ol>
          </div>
        ) : (
          <output className={styles.abstention}>
            <strong>No supported answer.</strong>
            <p>
              No capability, gap, invariant, horizon signal or owner record has lexical evidence for
              this question. Atlas preserves the unknown instead of inventing a response.
            </p>
            <a href="/capabilities">Browse the complete declared catalog →</a>
          </output>
        )}
        <RepositoryQuery query={query} />
      </section>

      <section className={styles.gapTargets} aria-labelledby="enhancement-targets-title">
        <header>
          <p>Stable enhancement targets</p>
          <h2 id="enhancement-targets-title">Compile from a governed gap, never an ambiguous wish.</h2>
        </header>
        <div>
          {deliveryGovernance.gaps.map((gap) => (
            <a href={`/ask?target=${encodeURIComponent(gap.id)}`} key={gap.id}>
              <span>{gap.priority}</span>
              <strong>{gap.title}</strong>
              <code>{gap.id}</code>
            </a>
          ))}
        </div>
      </section>
    </div>
  );
}
