import { api } from "../api";
import { Link } from "react-router";
import { ErrorBox, Loading, useAsync } from "../components/ui";

// The About/version page (ADR-0004 P1). Every fact here is SERVED: the app identity comes from
// /api/meta, whose values come from the brand SSOT (cisco_toolkit/brand_tokens.py) — nothing on
// this page hardcodes the name, the versions, or the deliverable-family size.
export default function AboutPage() {
  const { data, error, loading } = useAsync(() => api.meta(), []);
  if (loading) return <div className="container"><Loading /></div>;
  if (error) return <div className="container"><ErrorBox msg={error} /></div>;
  const meta = data!;
  const app = meta.app;
  const artifactSummary = meta.artifact_family
    ? `${meta.artifact_family.pre_cutover} pre-cutover + ${meta.artifact_family.conditional_post_execution} conditional post-execution`
    : `${meta.deliverables.length} snapshot downloads`;

  const facts: Array<[string, string]> = [
    ["Release", app.release],
    ["Engine schema", meta.engine_schema],
    ["Artifact lifecycle", artifactSummary],
  ];

  return (
    <div className="container" style={{ maxWidth: 760 }}>
      <div className="page-head"><h1>About</h1></div>

      <div className="panel">
        <h3>{app.title}</h3>
        <div className="dim" style={{ fontSize: 13, marginBottom: 14 }}>
          The one door to the Cisco migration-assessment engine: campaigns, risk cockpit, cutover
          planner, war room and the full artifact lifecycle, served from a single origin. The
          canonical registry distinguishes engine outputs, AssessHub synthesis and conditional PIR.
        </div>
        <div className="grid" style={{ gap: 8 }}>
          {facts.map(([k, v]) => (
            <div key={k} className="spread" style={{ fontSize: 13 }}>
              <span className="dim">{k}</span>
              <span className="mono">{v}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <h3>Offline field workflow</h3>
        <ol>
          <li>Open Campaigns and import your collected evidence or an assessment snapshot.</li>
          <li>Open the assessment, then choose <strong>Saved plans · MOP / NRFU</strong>.</li>
          <li>Enter requirements and save a named revision. Reopen it to review the same saved design
            and acceptance checklist.</li>
          <li>Download its MOP, NRFU and supporting documents. Each file identifies the assessment,
            revision and selection used. Changes need a new saved revision before downloading.</li>
        </ol>
        <p>Plans stay <strong>unapproved drafts</strong>. A generated test plan is a checklist to run;
          it does not establish that a cutover passed.</p>
        <p>This workflow uses the bundled application and document libraries. It requires no host
          Python, Node, Office installation or remote service. Windows and a supported local browser
          are host prerequisites; a compatible viewer is optional for opening the document files.</p>
        <Link className="btn primary" to="/campaigns">Open Campaigns</Link>
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <h3>Field readiness</h3>
        <div className="dim" style={{ fontSize: 13 }}>
          Before an engagement, run <span className="mono">{app.name}.exe --selftest</span>. It fails loud on
          the assets that otherwise degrade silently: the explorer template, the OUI/port/EoL knowledge
          packs, the DOCX/PPTX generators, the built frontend, the engine entry point and the data
          directory. Collection stays explicit and read-only — this app never writes to a device.
        </div>
        <p className="dim">A self-test or hosted check does not replace managed Windows policy,
          physical USB/recovery, signing or field-operator acceptance. Keep the complete application
          folder together, protect its data folder, and use the field guide shipped beside the executable.</p>
      </div>
    </div>
  );
}
