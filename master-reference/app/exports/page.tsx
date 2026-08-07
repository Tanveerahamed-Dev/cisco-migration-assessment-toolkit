/* oxlint-disable nextjs/no-html-link-for-pages -- full-document navigation preserves the connect-src 'none' privacy boundary. */
import type { Metadata } from "next";
import outputContract from "../../content/output-contract.json";
import { AtlasShell, SectionHeading, StateMark } from "../atlas/Shell";

export const metadata: Metadata = {
  title: "Export, Verification & Recovery · Atlas Master Reference",
  description:
    "The single-manifest output family, exact-source release gates, offline verification, signing, and preservation contract.",
};

const OUTPUTS = outputContract.members.filter((item) => item.ui_surface);

const LIFECYCLE = [
  "DRAFT",
  "CANDIDATE",
  "VERIFIED",
  "PUBLISHED",
  "SUPERSEDED",
  "ARCHIVED",
] as const;

export default function ExportsPage() {
  return (
    <AtlasShell active="exports" eyebrow="Release control">
      <header className="page-title">
        <h1>One manifest. Every output reconciled.</h1>
        <p>
          Export formats are projections of one exact-source inventory. A generated file can be
          complete as a preview while the independent-review, owner-key, publication, or recovery
          gates remain blocked.
        </p>
      </header>

      <section className="workspace-section">
        <SectionHeading
          index="01"
          title="Mandatory output family"
          description="State labels describe the required gate; they are not claims that an artifact has already been released."
        />
        <div className="export-table-wrap">
          <table className="export-table">
            <caption className="visually-hidden">Mandatory Atlas outputs</caption>
            <thead><tr className="export-table-head"><th scope="col">Output</th><th scope="col">Manifest member</th><th scope="col">Current gate</th></tr></thead>
            <tbody>
              {OUTPUTS.map((item) => (
                <tr key={item.id}>
                  <th scope="row">{item.label}</th>
                  <td><code>{item.manifest_member ?? "external private deployment"}</code></td>
                  <td><StateMark state={item.gate} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="workspace-section">
        <SectionHeading
          index="02"
          title="Executable lifecycle"
          description="There is no draft-to-published shortcut. Rejection and revocation remain durable events even when current views move on."
        />
        <ol className="release-lifecycle" aria-label="Reference release lifecycle">
          {LIFECYCLE.map((state, index) => (
            <li key={state}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <strong>{state}</strong>
              <small>
                {state === "VERIFIED"
                  ? "independent receipts and exact-source gates"
                  : state === "PUBLISHED"
                    ? "separate owner publication authority"
                    : "hash-chained semantic event"}
              </small>
            </li>
          ))}
        </ol>
        <div className="release-caveat">
          <StateMark state="blocked" />
          <div>
            <strong>Signing remains owner-controlled</strong>
            <p>
              The repository may verify an Ed25519 signature, but it never creates, stores, or
              recovers the owner&apos;s private key. Until a key and independent receipts are supplied,
              generated bundles remain unsigned previews.
            </p>
          </div>
        </div>
      </section>

      <section className="workspace-section recovery-grid">
        <div>
          <SectionHeading
            index="03"
            title="Offline verification"
            description="A receiver can prove which bytes, tree, schemas and exception set a bundle declares without contacting Atlas."
          />
          <ol className="verification-steps">
            <li>Verify the artifact-inventory digest and optional detached signature.</li>
            <li>Recompute every member digest and the manifest root.</li>
            <li>Confirm source commit, source-tree digest, schema and compiler versions.</li>
            <li>Inspect exceptions, failed acceptance gates, revocations and review receipts.</li>
            <li>Open the offline viewer only after byte reconciliation succeeds.</li>
          </ol>
        </div>
        <div>
          <SectionHeading
            index="04"
            title="Preservation and recovery"
            description="Recoverability is demonstrated by exercises, not by the presence of a ZIP file."
          />
          <ul className="recovery-checks">
            <li><strong>3-2-1 copies</strong><span>human-controlled; never inferred from this repository</span></li>
            <li><strong>Annual checksum drill</strong><span>receipt required</span></li>
            <li><strong>Bare-machine rebuild</strong><span>toolchain and caches must reconcile</span></li>
            <li><strong>Key-loss exercise</strong><span>two encrypted recovery copies, locations private</span></li>
            <li><strong>Schema recovery</strong><span>upcasters and historical viewer verified together</span></li>
          </ul>
        </div>
      </section>

      <section className="workspace-section">
        <SectionHeading
          index="05"
          title="Publication is deliberately separate"
          description="Private deployment, public release and GitHub publication are three different authorities."
        />
        <div className="publication-boundary">
          <article><StateMark state="candidate" /><h3>Local candidate</h3><p>May be built from a clean exact tree and inspected offline.</p></article>
          <article><StateMark state="gated" /><h3>Private deployment</h3><p>Requires owner-only access and served-hash verification.</p></article>
          <article><StateMark state="blocked" /><h3>Public publication</h3><p>Requires explicit owner authority; never inherited from implementation approval.</p></article>
        </div>
        <a className="text-link" href="/source">Inspect the source binding →</a>
      </section>
    </AtlasShell>
  );
}
