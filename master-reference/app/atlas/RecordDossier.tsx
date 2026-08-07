/* oxlint-disable nextjs/no-html-link-for-pages -- full-document navigation preserves the connect-src 'none' privacy boundary. */
"use client";

import { useEffect, useState } from "react";
import { loadProjection, shortDigest, sourceHref } from "./SourceExplorerData";
import type {
  ClaimRecord,
  DatasetRecord,
  DossierRecord,
  ProjectionIndex,
  SymbolRecord,
  TestRecord,
  WorkflowRecord,
} from "./SourceExplorerTypes";
import styles from "./SourceExplorer.module.css";

type DossierKind = "symbol" | "data" | "test" | "workflow" | "claim";
type DossierState =
  | { state: "loading" }
  | { state: "missing"; message: string }
  | { state: "ready"; index: ProjectionIndex; record: DossierRecord };

function title(kind: DossierKind, record: DossierRecord): string {
  if (kind === "symbol") return (record as SymbolRecord).qualifiedName;
  if (kind === "test") return (record as TestRecord).name;
  if (kind === "workflow") return (record as WorkflowRecord).name;
  if (kind === "claim") return (record as ClaimRecord).predicate;
  return (record as DatasetRecord).path;
}

function rangeOf(record: DossierRecord): { start_line: number; end_line: number } | null {
  return "range" in record && record.range ? record.range : null;
}

function pathOf(record: DossierRecord): string | null {
  return "path" in record ? record.path : null;
}

function unresolved(record: DossierRecord): string[] {
  return [...new Set(record.unresolvedReasons ?? [])];
}

function MissingField({ children = "Not emitted by the current compiler" }: { children?: string }) {
  return <span className={styles.missingValue}>{children}</span>;
}

function SymbolDetails({ record }: { record: SymbolRecord }) {
  return (
    <>
      <section>
        <h2>Declared structure</h2>
        <dl className={styles.factList}>
          <div><dt>Kind</dt><dd>{record.kind}</dd></div>
          <div><dt>Language</dt><dd>{record.language}</dd></div>
          <div><dt>Exported</dt><dd>{record.exported ? "yes" : "no"}</dd></div>
          <div><dt>Syntax nesting</dt><dd>{record.syntaxDepth ?? "not emitted"}</dd></div>
          <div><dt>Symbol digest</dt><dd><code>{shortDigest(record.digest, 20)}</code></dd></div>
          <div><dt>Criticality</dt><dd>{record.criticality.replaceAll("_", " ")}</dd></div>
          <div><dt>Review</dt><dd>{record.reviewState.replaceAll("_", " ")} · depth {record.explanationDepth}</dd></div>
        </dl>
      </section>
      <section>
        <h2>Behavioral contract</h2>
        <dl className={styles.factList}>
          <div><dt>Purpose</dt><dd>{record.purpose || <MissingField />}</dd></div>
          <div><dt>Purpose basis</dt><dd>{record.purposeBasis.replaceAll("_", " ")}</dd></div>
          <div><dt>Responsibility</dt><dd>{record.responsibility || <MissingField />}</dd></div>
          <div><dt>Parameters</dt><dd>{record.parametersAndTypes.length ? JSON.stringify(record.parametersAndTypes) : <MissingField>None declared or resolved</MissingField>}</dd></div>
          <div><dt>Return / output</dt><dd>{record.returnOrOutput == null ? <MissingField /> : JSON.stringify(record.returnOrOutput)}</dd></div>
          <div><dt>State read / written</dt><dd>{record.stateRead.length || record.stateWritten.length ? `${JSON.stringify(record.stateRead)} / ${JSON.stringify(record.stateWritten)}` : <MissingField>Not semantically resolved</MissingField>}</dd></div>
          <div><dt>External effects</dt><dd>{record.externalEffects.length ? JSON.stringify(record.externalEffects) : <MissingField>None resolved</MissingField>}</dd></div>
          <div><dt>Failure / abstention</dt><dd>{record.failureAndExceptionBehavior.replaceAll("_", " ")} · {record.abstentionBehavior.replaceAll("_", " ")}</dd></div>
          <div><dt>Callers</dt><dd>{record.callers.join(" · ") || <MissingField />}</dd></div>
          <div><dt>Callees</dt><dd>{record.callees.join(" · ") || <MissingField />}</dd></div>
          <div><dt>Data dependencies</dt><dd>{record.dataDependencies.join(" · ") || <MissingField />}</dd></div>
          <div><dt>Known impact if changed</dt><dd>{record.knownImpactIfChanged.join(" · ") || <MissingField />}</dd></div>
        </dl>
      </section>
      <section>
        <h2>Proof</h2>
        <dl className={styles.factList}>
          <div><dt>Tests</dt><dd>{record.tests.length ? record.tests.join(" · ") : <MissingField>No test-to-symbol linkage emitted</MissingField>}</dd></div>
          <div><dt>Test linkage</dt><dd>{record.testLinkage.replaceAll("_", " ")}</dd></div>
          <div><dt>Runtime traces</dt><dd>{record.runtimeTraceEvidence.length ? JSON.stringify(record.runtimeTraceEvidence) : <MissingField>{record.runtimeTraceState.replaceAll("_", " ")}</MissingField>}</dd></div>
          <div><dt>Performance</dt><dd>{record.performanceCharacteristics.replaceAll("_", " ")}</dd></div>
          <div><dt>Security boundary</dt><dd>{record.securityBoundary.replaceAll("_", " ")}</dd></div>
          <div><dt>GUI / artifact consumers</dt><dd>{record.downstreamSurfaces.join(" · ") || <MissingField />}</dd></div>
          <div><dt>Review depth</dt><dd>Level {record.explanationDepth} · {record.reviewState.replaceAll("_", " ")}</dd></div>
        </dl>
      </section>
    </>
  );
}

function DatasetDetails({ record }: { record: DatasetRecord }) {
  return (
    <>
      <section>
        <h2>Dataset inventory</h2>
        <dl className={styles.factList}>
          <div><dt>Format</dt><dd>{record.format}</dd></div>
          <div><dt>Declared rows</dt><dd>{record.structuredRecordCount ?? <MissingField />}</dd></div>
          <div><dt>Bytes</dt><dd>{record.sizeBytes.toLocaleString()}</dd></div>
          <div><dt>Digest</dt><dd><code>{shortDigest(record.contentDigest, 20)}</code></dd></div>
        </dl>
      </section>
      <section>
        <h2>Lineage</h2>
        <dl className={styles.factList}>
          <div><dt>Schema</dt><dd><MissingField /></dd></div>
          <div><dt>Generator / provenance</dt><dd><MissingField /></dd></div>
          <div><dt>Consumers</dt><dd><MissingField /></dd></div>
          <div><dt>Integrity validation</dt><dd>Content digest only</dd></div>
        </dl>
      </section>
    </>
  );
}

function TestDetails({ record }: { record: TestRecord }) {
  const assertionKinds = record.assertions.map((assertion) => assertion.kind);
  return (
    <>
      <section>
        <h2>Test declaration</h2>
        <dl className={styles.factList}>
          <div><dt>Framework</dt><dd>{record.framework}</dd></div>
          <div><dt>Name</dt><dd>{record.name}</dd></div>
          <div><dt>Entity type</dt><dd>{record.entityType.replaceAll("_", " ")}</dd></div>
          <div><dt>Definition</dt><dd>{record.range ? `lines ${record.range.start_line}–${record.range.end_line}` : <MissingField />}</dd></div>
          <div><dt>Extraction</dt><dd>{record.extractionDisposition.replaceAll("_", " ")}</dd></div>
        </dl>
      </section>
      <section>
        <h2>Proof dossier</h2>
        <dl className={styles.factList}>
          <div><dt>Subject under test</dt><dd><MissingField /></dd></div>
          <div><dt>Assertion group</dt><dd>{record.assertionGroupId ? <a href={`/test/${encodeURIComponent(record.assertionGroupId)}`}>{record.assertionGroupId}</a> : record.entityType === "test_assertion_group" ? record.id : <MissingField />}</dd></div>
          <div><dt>Static assertion denominator</dt><dd>{record.assertionCount ?? <MissingField />}</dd></div>
          <div><dt>Extracted assertion kinds</dt><dd>{assertionKinds.join(" · ") || <MissingField>No syntactic assertion was found; helpers and runtime failures remain unresolved</MissingField>}</dd></div>
          <div><dt>Fixture provenance</dt><dd><MissingField /></dd></div>
          <div><dt>Execution state</dt><dd><MissingField>No coverage or run receipt joined</MissingField></dd></div>
          <div><dt>Proof tier</dt><dd>Structural assertion extraction only</dd></div>
        </dl>
        {record.assertions.length ? <pre className={styles.rawRecord}>{JSON.stringify(record.assertions, null, 2)}</pre> : null}
      </section>
    </>
  );
}

function WorkflowDetails({ record }: { record: WorkflowRecord }) {
  const permissionReferences = [...record.permissionIds, ...record.permissions];
  const artifactReferences = [...record.artifactIds, ...record.artifacts];
  return (
    <>
      <section>
        <h2>Workflow declaration</h2>
        <dl className={styles.factList}>
          <div><dt>Entity type</dt><dd>{record.entityType.replaceAll("_", " ")}</dd></div>
          <div><dt>Extraction</dt><dd>{record.extractionDisposition.replaceAll("_", " ")}</dd></div>
          <div><dt>Triggers</dt><dd>{record.triggers.join(" · ") || <MissingField>Only emitted for the workflow root</MissingField>}</dd></div>
          <div><dt>Declared jobs</dt><dd>{record.jobs.join(" · ") || record.jobIds.join(" · ") || <MissingField />}</dd></div>
          <div><dt>Parent job</dt><dd>{record.job ?? <MissingField>Not a job child</MissingField>}</dd></div>
          <div><dt>Steps</dt><dd>{record.steps.join(" · ") || record.stepIds.join(" · ") || <MissingField />}</dd></div>
          <div><dt>Step index</dt><dd>{record.stepIndex ?? <MissingField>Not a step entity</MissingField>}</dd></div>
          <div><dt>Action / command</dt><dd>{record.uses ?? (record.runDeclared ? "Inline run command declared; command text intentionally not projected" : <MissingField />)}</dd></div>
          <div><dt>Source digest</dt><dd>{record.sourceDigest ? <code>{shortDigest(record.sourceDigest, 20)}</code> : <MissingField />}</dd></div>
          <div><dt>Parser mode</dt><dd>{record.parserMode}</dd></div>
        </dl>
      </section>
      <section>
        <h2>Release and trust effects</h2>
        <dl className={styles.factList}>
          <div><dt>Permissions</dt><dd>{permissionReferences.join(" · ") || (record.scope && record.access ? `${record.scope}: ${record.access}` : <MissingField />)}</dd></div>
          <div><dt>Artifacts</dt><dd>{artifactReferences.join(" · ") || (record.direction ? `${record.direction}: ${record.declaredPath ?? "dynamic or default path"}` : <MissingField />)}</dd></div>
          <div><dt>Artifact action</dt><dd>{record.action ?? <MissingField />}</dd></div>
          <div><dt>Artifact step</dt><dd>{record.stepId ?? <MissingField />}</dd></div>
          <div><dt>Secrets boundary</dt><dd><MissingField /></dd></div>
          <div><dt>Failure effects</dt><dd><MissingField /></dd></div>
          <div><dt>Last execution receipt</dt><dd><MissingField /></dd></div>
        </dl>
      </section>
    </>
  );
}

function ClaimDetails({ record }: { record: ClaimRecord }) {
  return (
    <>
      <section>
        <h2>Typed claim</h2>
        <dl className={styles.factList}>
          <div><dt>Subject</dt><dd><code>{record.subject}</code></dd></div>
          <div><dt>Predicate</dt><dd>{record.predicate}</dd></div>
          <div><dt>Value / unit</dt><dd><code>{JSON.stringify(record.value) ?? "undefined"}</code>{record.unit ? ` ${record.unit}` : null}</dd></div>
          <div><dt>Verdict</dt><dd>{record.verdict.replaceAll("_", " ")}</dd></div>
          <div><dt>Freshness</dt><dd>{record.freshness.replaceAll("_", " ")}</dd></div>
          <div><dt>Status / current view</dt><dd>{record.status.replaceAll("_", " ")} · {record.currentView ? "included" : "excluded"}</dd></div>
          <div><dt>Confidence</dt><dd>{record.confidence ?? <MissingField />}</dd></div>
          <div><dt>Evidence requirement</dt><dd>{record.satisfiesEvidenceRequirement ? "satisfied in declared scope" : <MissingField>Not satisfied</MissingField>}</dd></div>
        </dl>
      </section>
      <section>
        <h2>Scope and time</h2>
        <dl className={styles.factList}>
          <div><dt>Basis</dt><dd>{record.basis}</dd></div>
          <div><dt>Scope</dt><dd><code>{JSON.stringify(record.scope)}</code></dd></div>
          <div><dt>Effective time</dt><dd>{record.effectiveTime ?? <MissingField />}</dd></div>
          <div><dt>Recorded time</dt><dd>{record.recordedTime ?? <MissingField />}</dd></div>
          <div><dt>Temporal basis</dt><dd>{record.temporalBasis.replaceAll("_", " ")}</dd></div>
          <div><dt>Owner</dt><dd><code>{record.owner}</code></dd></div>
          <div><dt>Source commit</dt><dd><code>{record.sourceCommit ?? "not emitted"}</code></dd></div>
        </dl>
      </section>
      <section>
        <h2>Evidence and transformation</h2>
        <dl className={styles.factList}>
          <div><dt>Evidence class</dt><dd>{record.evidenceClass.replaceAll("_", " ")}</dd></div>
          <div><dt>Evidence IDs</dt><dd>{record.evidenceIds.length ? record.evidenceIds.map((evidence) => <a key={evidence} href={`/ask?q=${encodeURIComponent(evidence)}`}>[{evidence}]</a>) : <MissingField />}</dd></div>
          <div><dt>Lineage</dt><dd>{record.lineage.join(" · ") || <MissingField />}</dd></div>
          <div><dt>Derived from claims</dt><dd>{record.derivedFrom.join(" · ") || <MissingField>Not a claim-derived claim</MissingField>}</dd></div>
          <div><dt>Transformation</dt><dd>{record.transformation ? <code>{JSON.stringify(record.transformation)}</code> : <MissingField />}</dd></div>
          <div><dt>Denominator</dt><dd>{record.denominator ? <code>{JSON.stringify(record.denominator)}</code> : <MissingField />}</dd></div>
          <div><dt>Origin / extraction</dt><dd>{record.origin.replaceAll("_", " ")} · {record.extractionMode.replaceAll("_", " ")}</dd></div>
          <div><dt>Conflicts</dt><dd>{record.conflictsWith.join(" · ") || "None emitted"}</dd></div>
          <div><dt>Revocation</dt><dd>{record.revokedBy ?? record.revocationReason ?? "Not revoked"}</dd></div>
        </dl>
        <p className={styles.missingValue}>A proven claim verdict applies only to its declared evidence, denominator, source tree and transformation. It does not imply runtime execution, test coverage or human review.</p>
      </section>
    </>
  );
}

export function RecordDossier({ kind, id }: { kind: DossierKind; id: string }) {
  const [loadState, setLoadState] = useState<DossierState>({ state: "loading" });
  useEffect(() => {
    let active = true;
    void loadProjection()
      .then(async (module) => {
        const record = await module.loadRecord(kind, id) as DossierRecord | null;
        if (!active) return;
        if (!record) {
          setLoadState({ state: "missing", message: `${id} is not present in the exact-tree ${kind} denominator.` });
        } else {
          setLoadState({ state: "ready", index: module.projection, record });
        }
      })
      .catch(() => {
        if (active) setLoadState({ state: "missing", message: "The generated repository projection is absent." });
      });
    return () => { active = false; };
  }, [id, kind]);

  if (loadState.state === "loading") {
    return <output className={styles.loading}><span className={styles.loadingPulse} /><strong>Opening canonical dossier…</strong></output>;
  }
  if (loadState.state === "missing") {
    return <div className={styles.error}><strong>Dossier unavailable</strong><p>{loadState.message}</p><a href="/source">Search the exact tracked tree</a></div>;
  }

  const { index, record } = loadState;
  const range = rangeOf(record);
  const path = pathOf(record);
  const reasons = unresolved(record);
  const explanationDepth = kind === "symbol" ? (record as SymbolRecord).explanationDepth : 1;
  return (
    <article className={styles.recordDossier}>
      <header>
        <div className={styles.recordTopline}>
          <span className={styles.badge} data-state="parsed">{record.derivation.replaceAll("_", " ")}</span>
          <span className={styles.badge}>Level {explanationDepth}</span>
        </div>
        <h1>{title(kind, record)}</h1>
        <p>{kind} dossier · source commit <code>{index.sourceCommit.slice(0, 12)}</code></p>
        <code>{record.id}</code>
      </header>

      <dl className={styles.dossierGrid}>
        <div><dt>Tracked path</dt><dd>{path ? <a href={sourceHref(path, range?.start_line)}>{path}</a> : <MissingField>Claim is source-tree bound through its scope and evidence, not one path</MissingField>}</dd></div>
        <div><dt>Source range</dt><dd>{range ? `${range.start_line}–${range.end_line}` : "whole file"}</dd></div>
        <div><dt>Derivation</dt><dd>{record.derivation.replaceAll("_", " ")}</dd></div>
        <div><dt>Behavior verified</dt><dd className={explanationDepth >= 3 ? undefined : styles.missingValue}>{explanationDepth >= 3 ? "Depth declares verification" : "No"}</dd></div>
        <div><dt>Runtime traced</dt><dd className={kind === "symbol" && (record as SymbolRecord).runtimeTraceEvidence.length ? undefined : styles.missingValue}>{kind === "symbol" ? (record as SymbolRecord).runtimeTraceState.replaceAll("_", " ") : "Not emitted"}</dd></div>
        <div><dt>Stable link</dt><dd><code>/{kind}/{encodeURIComponent(record.id)}</code></dd></div>
      </dl>

      <div className={styles.notice}>
        <strong>Interpretation boundary</strong>
        <span>
          This dossier proves that the record exists in the selected tree and shows its parsed structure.
          Empty behavioral fields are visible; they are not filled with generated prose or inferred certainty.
        </span>
      </div>

      <div className={styles.dossierSections}>
        {kind === "symbol" ? <SymbolDetails record={record as SymbolRecord} /> : null}
        {kind === "data" ? <DatasetDetails record={record as DatasetRecord} /> : null}
        {kind === "test" ? <TestDetails record={record as TestRecord} /> : null}
        {kind === "workflow" ? <WorkflowDetails record={record as WorkflowRecord} /> : null}
        {kind === "claim" ? <ClaimDetails record={record as ClaimRecord} /> : null}
        <section>
          <h2>Uncertainty</h2>
          {reasons.length ? <ul>{reasons.map((reason) => <li key={reason}>{reason.replaceAll("_", " ")}</li>)}</ul> : <p>No parser-specific reason was emitted. Behavioral and runtime fields still remain unverified.</p>}
        </section>
        <section>
          <h2>Compiler projection record</h2>
          <pre className={styles.rawRecord}>{JSON.stringify(record, null, 2)}</pre>
        </section>
      </div>
    </article>
  );
}
