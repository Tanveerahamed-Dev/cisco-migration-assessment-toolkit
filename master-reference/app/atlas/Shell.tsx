/* oxlint-disable nextjs/no-html-link-for-pages -- full-document navigation preserves the connect-src 'none' privacy boundary. */
import type { ReactNode } from "react";

const NAVIGATION = [
  ["overview", "/", "Owner cockpit"],
  ["outcomes", "/capabilities?domain=domain.outcomes", "Outcomes & maturity"],
  ["system", "/system", "System & assurance"],
  ["graph", "/graph", "Complete Graphify map"],
  ["capabilities", "/capabilities", "Capability matrix"],
  ["protocols", "/capabilities?domain=domain.protocols", "Protocol intelligence"],
  ["traffic", "/system#traffic", "Traffic truth"],
  ["designs", "/capabilities?domain=domain.enterprise-design", "Enterprise designs"],
  ["security", "/capabilities?domain=domain.security-privacy", "Security & privacy"],
  ["operations", "/capabilities?domain=domain.observability-operations", "Operations & observability"],
  ["vendors", "/capabilities?domain=domain.vendors-channels", "Vendors & channels"],
  ["product", "/capabilities?domain=domain.gui-white-label", "Product & GUI"],
  ["artifacts", "/capabilities?domain=domain.artifacts-deliverables", "Artifacts & deliverables"],
  ["gaps", "/gaps", "Decisions & gaps"],
  ["horizon", "/gaps#horizon", "Industry horizon"],
  ["source", "/source", "Source explorer"],
  ["labs", "/labs", "Labs"],
  ["ask", "/ask", "Ask Atlas"],
  ["exports", "/exports", "Export & recovery"],
] as const;

const PROTECTED = [
  "No device writes",
  "No raw Vault or client evidence",
  "Unknown never becomes healthy",
  "Proposer differs from verifier",
] as const;

type AtlasShellProps = {
  active: (typeof NAVIGATION)[number][0];
  eyebrow?: string;
  children: ReactNode;
};

export function AtlasShell({ active, eyebrow, children }: AtlasShellProps) {
  return (
    <div className="atlas-shell">
      <a className="skip-link" href="#atlas-content">
        Skip to content
      </a>
      <header className="atlas-header">
        <a className="atlas-brand" href="/" aria-label="Atlas master reference home">
          <span className="atlas-brand-mark" aria-hidden="true">
            A
          </span>
          <span>
            <strong>Atlas</strong>
            <small>Master Reference</small>
          </span>
        </a>
        <div className="atlas-header-context">
          <span className="signal signal-private">Private</span>
          <span className="header-source">Tracked-tree accounting</span>
        </div>
      </header>

      <div className="constraint-strip" aria-label="Protected constraints">
        <span className="constraint-label">Protected</span>
        {PROTECTED.map((item) => (
          <span key={item}>{item}</span>
        ))}
      </div>

      <div className="atlas-frame">
        <aside className="atlas-nav">
          <p className="nav-kicker">Navigate the system</p>
          <nav aria-label="Atlas workspaces">
            {NAVIGATION.map(([id, href, label], index) => (
              <a
                aria-current={active === id ? "page" : undefined}
                href={href}
                key={id}
              >
                <span>{String(index + 1).padStart(2, "0")}</span>
                {label}
              </a>
            ))}
          </nav>
          <div className="nav-proof">
            <span className="proof-pulse" aria-hidden="true" />
            <p>
              <strong>Coverage-honest</strong>
              Lower-depth and unresolved areas remain visible.
            </p>
          </div>
        </aside>

        <main className="atlas-content" id="atlas-content">
          {eyebrow ? <p className="page-eyebrow">{eyebrow}</p> : null}
          {children}
        </main>
      </div>

      <footer className="atlas-footer">
        <p>
          Atlas Master Reference <span>·</span> read-only <span>·</span> offline-first
        </p>
        <p>No analytics · no persistence · no operational mutation</p>
      </footer>
    </div>
  );
}

export function StateMark({ state }: { state: string }) {
  return (
    <span className={`state-mark state-${state.replaceAll("_", "-")}`}>
      <span aria-hidden="true" />
      {state.replaceAll("_", " ")}
    </span>
  );
}

export function OwnerLinks({ ownerRefs }: { ownerRefs?: string[] }) {
  if (!ownerRefs?.length) return <span className="muted">No live owner claimed</span>;
  return (
    <span className="owner-links">
      {ownerRefs.map((owner) => (
        <code key={owner}>{owner}</code>
      ))}
    </span>
  );
}

export function SectionHeading({
  index,
  title,
  description,
}: {
  index: string;
  title: string;
  description: string;
}) {
  return (
    <header className="section-heading">
      <div>
        <span>{index}</span>
        <h2>{title}</h2>
      </div>
      <p>{description}</p>
    </header>
  );
}
