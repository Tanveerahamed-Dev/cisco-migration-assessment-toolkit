"use client";

import { useMemo, useState } from "react";

type Persona = "all" | "operator" | "reviewer" | "maintainer" | "security";

type PipelineStage = {
  id: string;
  step: string;
  title: string;
  summary: string;
  input: string;
  guardrail: string;
  output: string;
  failure: string;
};

type Decision = {
  id: string;
  category: string;
  title: string;
  outcome: string;
  reason: string;
  tradeoff: string;
  enforcement: string;
  evidence: string;
  personas: Exclude<Persona, "all">[];
  tags: string[];
};

const pipeline: PipelineStage[] = [
  {
    id: "intake",
    step: "01",
    title: "Constrain intake",
    summary:
      "Accept only named evidence shapes, bounded archives, and regular files whose identity stays stable while read.",
    input: "CLI captures, snapshots, or explicitly supported Atlas archives",
    guardrail:
      "Size, entry-count, path, link, reparse-point, duplicate-key, and format checks run before parsing.",
    output: "A bounded candidate set with explicit intake status",
    failure:
      "Reject the whole candidate. Unsupported or ambiguous input never becomes trusted evidence.",
  },
  {
    id: "custody",
    step: "02",
    title: "Bind custody",
    summary:
      "Record what was opened, what was read, and whether the path still names the same object.",
    input: "Validated regular files",
    guardrail:
      "Open-handle identity, before/after metadata, byte count, and digest are bound in a custody ledger.",
    output: "Same-read evidence records",
    failure:
      "Abort on replacement, truncation, growth, link substitution, or incomplete capture.",
  },
  {
    id: "parse",
    step: "03",
    title: "Parse without invention",
    summary:
      "Preserve raw observations, normalize only where a contract exists, and surface unknowns.",
    input: "Custody-bound command output",
    guardrail:
      "Parser fidelity tests, explicit coercion rules, totality checks, and deterministic identifiers.",
    output: "Observed facts plus provenance",
    failure:
      "Unknown stays unknown; malformed data produces diagnostics rather than optimistic defaults.",
  },
  {
    id: "reconcile",
    step: "04",
    title: "Reconcile one SSOT",
    summary:
      "Combine observations into a canonical snapshot while keeping source, conflict, and confidence visible.",
    input: "Parsed facts from one or more captures",
    guardrail:
      "Schema contracts, conflict registers, provenance chains, and stable ordering.",
    output: "Canonical fleet snapshot",
    failure:
      "Conflicts remain explicit and block claims that require stronger certainty.",
  },
  {
    id: "reason",
    step: "05",
    title: "Reason with authority",
    summary:
      "Enrich only from verified official registries and make abstention a first-class result.",
    input: "Canonical observations and immutable registry packs",
    guardrail:
      "Manifest-bound IEEE/IANA packs and exact Cisco lifecycle bulletin mappings.",
    output: "Attributed findings, lifecycle state, and design context",
    failure:
      "Integrity without authority is labeled honestly; unresolved product scope is omitted.",
  },
  {
    id: "decide",
    step: "06",
    title: "Gate every decision",
    summary:
      "Separate recommendation, approval, execution, and proof so no green label can be self-asserted.",
    input: "Attributed findings and policy",
    guardrail:
      "Preconditions, approval records, state transitions, and fail-closed completion semantics.",
    output: "Auditable recommendation or approved action",
    failure:
      "A missing prerequisite, stale proof, or failed mandatory phase prevents COMPLETE.",
  },
  {
    id: "deliver",
    step: "07",
    title: "Render from evidence",
    summary:
      "Generate field, executive, engineering, and machine-readable artifacts from the same snapshot.",
    input: "Canonical snapshot and decision state",
    guardrail:
      "Artifact manifests, deterministic metadata, XML-safe rendering, and provenance labels.",
    output: "Reports, workbooks, decks, runbooks, and Atlas views",
    failure:
      "Partial artifacts are marked incomplete and cannot masquerade as final deliverables.",
  },
  {
    id: "distribute",
    step: "08",
    title: "Prove distribution",
    summary:
      "Treat the built archive—not the checkout—as the release subject.",
    input: "Frozen source plus generated registry packs",
    guardrail:
      "Exact archive inventory, privacy scan, clean-environment install, self-test, and digest evidence.",
    output: "A reproducible, inspectable package",
    failure:
      "Any unexpected, missing, sensitive, or stale byte invalidates the release proof.",
  },
];

const decisions: Decision[] = [
  {
    id: "snapshot-ssot",
    category: "Architecture",
    title: "One canonical snapshot is the system of record",
    outcome:
      "All downstream reasoning and deliverables read the same normalized evidence model.",
    reason:
      "Independent report-specific transforms drift. A single snapshot makes disagreement detectable and regeneration predictable.",
    tradeoff:
      "The schema becomes a deliberate compatibility surface and must evolve carefully.",
    enforcement:
      "Schema census, golden snapshots, reconciliation tests, and artifact manifest bindings.",
    evidence: "cisco_toolkit/ssot.py · tests/test_ssot_* · tests/golden/snapshot.json",
    personas: ["operator", "reviewer", "maintainer"],
    tags: ["ssot", "schema", "determinism"],
  },
  {
    id: "bounded-intake",
    category: "Security",
    title: "Input is bounded before it is interpreted",
    outcome:
      "Archives, directories, JSON, and uploads fail closed before expensive or ambiguous processing.",
    reason:
      "A parser cannot safely repair an intake boundary that already accepted traversal, expansion, or identity ambiguity.",
    tradeoff:
      "Some unusual but benign files are rejected until their shape is explicitly supported.",
    enforcement:
      "Byte, member, entry, depth, path, link, reparse, duplicate-key, and concurrency limits.",
    evidence: "webapp/backend/ingest.py · cisco_toolkit/path_assertions.py",
    personas: ["operator", "maintainer", "security"],
    tags: ["ingest", "zip", "limits", "fail-closed"],
  },
  {
    id: "same-read-custody",
    category: "Evidence",
    title: "Custody binds the bytes actually parsed",
    outcome:
      "Evidence identity is checked around the same open handle that supplies parser bytes.",
    reason:
      "Hashing a path and reopening it later leaves a replacement window. Same-read binding closes that gap.",
    tradeoff:
      "Collection performs more metadata checks and records more evidence.",
    enforcement:
      "Open-handle identity, digest, byte count, before/after stat, ABA ledger, incomplete sidecars.",
    evidence: "cisco_toolkit/input_custody.py · tests/test_custody_pipeline.py",
    personas: ["reviewer", "maintainer", "security"],
    tags: ["custody", "toctou", "integrity"],
  },
  {
    id: "unknown-not-green",
    category: "Reasoning",
    title: "Unknown never silently becomes healthy",
    outcome:
      "Missing, malformed, conflicting, and unsupported observations remain visible uncertainty.",
    reason:
      "Optimistic defaults create false assurance, which is more dangerous than an explicit gap.",
    tradeoff:
      "Reports may contain more amber states and require follow-up collection.",
    enforcement:
      "Totality tests, false-health tests, explicit confidence, and prerequisite-aware gates.",
    evidence: "cisco_toolkit/assertions.py · tests/test_audit5_false_health.py",
    personas: ["operator", "reviewer", "maintainer"],
    tags: ["unknown", "confidence", "totality"],
  },
  {
    id: "integrity-authority",
    category: "Data authority",
    title: "Integrity and authority are separate claims",
    outcome:
      "A pack can be byte-perfect yet still be labeled non-authoritative if its provenance is insufficient.",
    reason:
      "Checksums prove sameness, not correctness or official origin.",
    tradeoff:
      "Health reporting is more nuanced than a single loaded/not-loaded flag.",
    enforcement:
      "Registry manifests expose source identity, generation chain, digest, schema, and authority state.",
    evidence: "cisco_toolkit/registry_integrity.py · cisco_toolkit/data/registry_manifest.json",
    personas: ["reviewer", "maintainer", "security"],
    tags: ["authority", "integrity", "provenance"],
  },
  {
    id: "official-packs",
    category: "Data authority",
    title: "OUI and service registries derive from exact official corpora",
    outcome:
      "IEEE MA-L/MA-M/MA-S and IANA service-name data are reproducibly transformed into runtime packs.",
    reason:
      "Embedded hand-maintained maps go stale and cannot demonstrate source completeness.",
    tradeoff:
      "Regeneration is stricter and source changes require explicit review.",
    enforcement:
      "Four-source public manifest, exact URL/path/header/row/digest checks, deterministic generators.",
    evidence: "reference-data/official-sources/ · cisco_toolkit/gen_oui_registry.py",
    personas: ["reviewer", "maintainer"],
    tags: ["ieee", "iana", "registry", "reproducible"],
  },
  {
    id: "scoped-port-authority",
    category: "Data authority",
    title: "Port authority is scoped, not global",
    outcome:
      "The service-port pack keeps its whole-pack authority flag false while the official IANA component carries its own verified source and freshness claims.",
    reason:
      "The pack deliberately mixes official IANA assignments with curated service hints; a single global flag either overclaims the hints or discards the official rows.",
    tradeoff:
      "Consumers read component and per-record authority fields instead of one convenient boolean.",
    enforcement:
      "authority_scope=iana-service-assignments-only, per-record assignment/semantics authority and overlay status, self-tests that require integrity plus the official component's proof rather than universal authority.",
    evidence: "cisco_toolkit/data/gen_port_registry.py · cisco_toolkit/registry_integrity.py",
    personas: ["reviewer", "maintainer"],
    tags: ["iana", "authority", "scoped"],
  },
  {
    id: "eol-abstention",
    category: "Data authority",
    title: "Lifecycle coverage is narrow enough to prove",
    outcome:
      "A product ID is classified only when an exact bounded scope maps to an official Cisco bulletin.",
    reason:
      "Broad family regexes can apply one model's lifecycle to a different, active model.",
    tradeoff:
      "Uncovered platforms return unknown instead of a convenient estimate.",
    enforcement:
      "Exact bulletin IDs and URLs, bounded PID patterns, overlap validation, zero unresolved authority rows.",
    evidence: "cisco_toolkit/eoldb.py · tests/test_eoldb_provenance.py",
    personas: ["operator", "reviewer", "maintainer"],
    tags: ["eol", "cisco", "abstention"],
  },
  {
    id: "independent-redaction",
    category: "Privacy",
    title: "Redaction is independently verified",
    outcome:
      "A separate scanner evaluates JSON, HTML, and supported OOXML output before a safe label is granted.",
    reason:
      "Producer self-attestation repeats the same blind spots. Independent verification provides a distinct control.",
    tradeoff:
      "Strict output verification can reject newly introduced formats until a verifier exists.",
    enforcement:
      "Stable pseudonyms, collision-safe key handling, bounded scanners, and explicit verification status.",
    evidence: "webapp/backend/redaction_verify.py · tests/test_redact_e2e.py",
    personas: ["operator", "reviewer", "security"],
    tags: ["redaction", "privacy", "verification"],
  },
  {
    id: "server-trust",
    category: "Security",
    title: "Trust labels are server-owned",
    outcome:
      "Uploaded JSON cannot declare itself verified by setting provenance or status fields.",
    reason:
      "Any client-controlled trust label is a confused-deputy boundary.",
    tradeoff:
      "Legacy or externally prepared snapshots remain unverified until a stronger evidence mechanism exists.",
    enforcement:
      "Reserved provenance stripping, route-owned stamping, persistence tests, and origin-aware status.",
    evidence: "webapp/backend/app.py · webapp/backend/summary.py",
    personas: ["reviewer", "maintainer", "security"],
    tags: ["trust", "provenance", "upload"],
  },
  {
    id: "decision-gates",
    category: "Governance",
    title: "Recommendations cannot approve themselves",
    outcome:
      "Pre-certification, approval, execution, and validation are distinct, evidenced transitions.",
    reason:
      "A single mutable status collapses governance and makes stale or partial work look complete.",
    tradeoff:
      "The workflow requires explicit records at each consequential boundary.",
    enforcement:
      "Gate state machine, immutable audit trail, prerequisite binding, fail-closed finalization.",
    evidence: "cisco_toolkit/precert.py · tests/test_decision_integrity_failclosed.py",
    personas: ["operator", "reviewer", "security"],
    tags: ["gates", "approval", "audit"],
  },
  {
    id: "deterministic-artifacts",
    category: "Delivery",
    title: "Artifacts are deterministic views, not parallel truths",
    outcome:
      "HTML, DOCX, PPTX, XLSX, runbooks, and machine-readable outputs share identifiers and provenance.",
    reason:
      "Format-specific truth makes review impossible and reruns noisy.",
    tradeoff:
      "Renderers must obey common contracts and avoid ambient timestamps or random identifiers.",
    enforcement:
      "Artifact manifest, reproducible metadata, golden tests, XML safety, and schema checks.",
    evidence: "cisco_toolkit/manifest.py · cisco_toolkit/docmeta.py",
    personas: ["operator", "reviewer", "maintainer"],
    tags: ["artifacts", "determinism", "manifest"],
  },
  {
    id: "research-isolation",
    category: "Security",
    title: "Research is isolated from assessment truth",
    outcome:
      "External material enters a quarantined lane and contributes only after sanitization and provenance checks.",
    reason:
      "Web content is mutable, adversarial, and not client evidence.",
    tradeoff:
      "Useful research takes an extra promotion step before it can influence recommendations.",
    enforcement:
      "HTTPS/redirect/SSRF guard, source policy, sanitized feed, vault digest, no direct SSOT mutation.",
    evidence: "research_lane/http_guard.py · research_lane/producer.py",
    personas: ["reviewer", "maintainer", "security"],
    tags: ["research", "ssrf", "quarantine"],
  },
  {
    id: "privacy-guard",
    category: "Privacy",
    title: "Repository privacy is a release invariant",
    outcome:
      "Client evidence, likely identifiers, unsafe links, and unapproved binary payloads block the check across the Git index and working tree.",
    reason:
      "Ignore rules hide files from Git; they do not prove that tracked or packaged bytes are safe.",
    tradeoff:
      "The gate proves current content, not file names or Git history; commits predating sanitization carry their own explicit decision. Exact public corpora and visual assets need manifest-bound exceptions.",
    enforcement:
      "Stable-file scanning, aggregate bounds, strict JSON/UTF-8, exact public-source manifest, CI gate.",
    evidence: ".github/scripts/verify_repository_privacy.py · tests/test_repository_privacy.py",
    personas: ["reviewer", "maintainer", "security"],
    tags: ["privacy", "repository", "ci"],
  },
  {
    id: "archive-is-release",
    category: "Distribution",
    title: "The archive is the release subject",
    outcome:
      "Wheel and source archive inventories are compared to policy and tested from a clean environment.",
    reason:
      "A clean checkout can still build an unsafe or incomplete artifact.",
    tradeoff:
      "Release evidence must be regenerated after any byte-affecting change.",
    enforcement:
      "Exact inclusion rules, RECORD verification, digest report, clean install, self-test, Twine checks.",
    evidence: "cisco_toolkit/distribution_verify.py · tests/test_distribution_verify.py",
    personas: ["reviewer", "maintainer", "security"],
    tags: ["wheel", "sdist", "supply-chain"],
  },
  {
    id: "static-reference",
    category: "Architecture",
    title: "The master reference is static by design",
    outcome:
      "This site explains the repository without receiving evidence, persisting state, or calling operational APIs.",
    reason:
      "A reference surface should not create a new data boundary or become an alternate source of truth.",
    tradeoff:
      "It visualizes contracts and evidence snapshots but does not operate the engine.",
    enforcement:
      "No database, auth, analytics, cookies, external fonts, runtime fetch, or user-submitted content.",
    evidence: "master-reference/app/ · master-reference/tests/",
    personas: ["operator", "reviewer", "maintainer", "security"],
    tags: ["reference", "static", "performance"],
  },
];

const personaLabels: { id: Persona; label: string; hint: string }[] = [
  { id: "all", label: "Whole system", hint: "Every decision" },
  { id: "operator", label: "Field operator", hint: "Collect and deliver" },
  { id: "reviewer", label: "Reviewer", hint: "Challenge the proof" },
  { id: "maintainer", label: "Maintainer", hint: "Change safely" },
  { id: "security", label: "Security", hint: "Inspect boundaries" },
];

const authority = [
  {
    source: "IEEE Registration Authority",
    scope: "MAC organization identity",
    material: "MA-L · MA-M · MA-S",
    decision:
      "Three exact official CSVs are manifest-bound and deterministically collapsed into the OUI pack.",
    boundary: "No network lookup at analysis time",
    state: "Verified authoritative",
  },
  {
    source: "IANA",
    scope: "Service names and transport ports",
    material: "Service Name and Transport Protocol Port Number Registry",
    decision:
      "The official CSV is normalized into protocol-aware service rows; local policy additions stay distinguishable.",
    boundary: "Source truth and toolkit overlays do not blur",
    state: "Verified authoritative",
  },
  {
    source: "Cisco product bulletins",
    scope: "Lifecycle classification",
    material: "Exact EOL bulletin ID + bounded product-ID scope",
    decision:
      "Only directly evidenced scopes are classified. Broad family inference is intentionally absent.",
    boundary: "Uncovered model means unknown",
    state: "Schema-verified authoritative",
  },
];

const trustBoundaries = [
  {
    edge: "Filesystem → intake",
    threat: "Traversal, links, reparse points, races, unbounded trees",
    control: "Stable regular-file reads, lexical path policy, entry/byte/depth limits",
    proof: "Adversarial intake and custody tests",
  },
  {
    edge: "Archive → parser",
    threat: "Zip bombs, duplicate paths, unsupported members, reserved names",
    control: "Complete preflight before extraction; normalized Windows-name checks",
    proof: "Fail-closed archive corpus",
  },
  {
    edge: "Parser → SSOT",
    threat: "Silent coercion, false health, conflicting observations",
    control: "Explicit unknowns, provenance, conflict retention, schema totality",
    proof: "Golden and false-health suites",
  },
  {
    edge: "Registry → enrichment",
    threat: "Stale or counterfeit authority",
    control: "Official-source manifest, generator provenance, runtime pack verification",
    proof: "Source-to-pack chain checks",
  },
  {
    edge: "Client JSON → web UI",
    threat: "Spoofed trust metadata and duplicate-key ambiguity",
    control: "Strict JSON plus server-owned origin and verification labels",
    proof: "Spoofing and persistence tests",
  },
  {
    edge: "SSOT → redacted artifact",
    threat: "Identifier leakage or producer blind spots",
    control: "Stable pseudonyms plus independent multi-format scanner",
    proof: "Producer/verifier cross-tests",
  },
  {
    edge: "Checkout → release archive",
    threat: "Unexpected files, secrets, missing runtime data, stale proof",
    control: "Exact inventory, privacy gate, clean install, archive-bound evidence",
    proof: "Immutable distribution report",
  },
];

const repositoryAreas = [
  {
    path: "COLLECT_PARSE_V3_23_0.py",
    role: "Orchestrates collection, parsing, stage finalization, and failure custody.",
    contract: "No COMPLETE when a mandatory phase or evidence binding fails.",
  },
  {
    path: "cisco_toolkit/",
    role: "Core evidence, analysis, reconciliation, decision, and artifact engines.",
    contract: "Deterministic, provenance-carrying, fail-closed domain logic.",
  },
  {
    path: "cisco_toolkit/data/",
    role: "Runtime registry packs and the manifest that binds their generation.",
    contract: "Integrity and authority health remain separate and inspectable.",
  },
  {
    path: "reference-data/official-sources/",
    role: "Exact public IEEE and IANA source corpora used to generate packs.",
    contract: "Only manifest-enumerated path, URL, schema, rows, size, and digest are exempted.",
  },
  {
    path: "research_lane/",
    role: "Quarantined external research, sanitization, and digest production.",
    contract: "Research cannot silently mutate assessment truth.",
  },
  {
    path: "webapp/",
    role: "Local-first Atlas interface, upload boundary, redaction, and visualization.",
    contract: "Client data stays bounded; only server-owned proof can grant trust.",
  },
  {
    path: "portable/",
    role: "Field packaging and offline Atlas construction.",
    contract: "Portable does not mean weaker verification or hidden dependencies.",
  },
  {
    path: ".github/",
    role: "CI, privacy policy, dependency automation, release, and publish gates.",
    contract: "Pinned actions, least privilege, reproducible checks, trusted publishing.",
  },
  {
    path: "tests/",
    role: "Executable contracts across evidence, privacy, authority, rendering, and release.",
    contract: "Negative and adversarial paths matter as much as happy paths.",
  },
  {
    path: "master-reference/",
    role: "Static explanatory surface for decisions, boundaries, and operating evidence.",
    contract: "A view of the system—not an intake path or alternate SSOT.",
  },
];

const verification = [
  {
    layer: "Input custody",
    proves: "The bytes parsed are the bytes recorded",
    mechanism: "Identity + digest + bounded same-read ledger",
    status: "Focused suite green",
  },
  {
    layer: "Registry chain",
    proves: "Runtime packs derive from exact official source material",
    mechanism: "Source manifest → generator → pack manifest → loader",
    status: "Authority chain green",
  },
  {
    layer: "Lifecycle scope",
    proves: "Every claimed product scope has an exact official bulletin",
    mechanism: "Bounded PID map + overlap and provenance validation",
    status: "Zero unresolved rows",
  },
  {
    layer: "Privacy",
    proves: "Tracked/released content excludes client evidence and unapproved binary data",
    mechanism: "Stable-file repository scanner + exact exceptions",
    status: "Focused suite green",
  },
  {
    layer: "Web fail-closed",
    proves: "Uploads, provenance, and redaction cannot self-certify",
    mechanism: "Boundary tests + independent artifact verifier",
    status: "Integrated matrix green",
  },
  {
    layer: "Distribution",
    proves: "The built archives contain exactly the allowed, functioning bytes",
    mechanism: "Inventory + RECORD + clean install + self-test + source binding",
    status: "Source-bound · 115 of 129 members",
  },
  {
    layer: "Whole repository",
    proves: "The integrated checkout satisfies quality, type, security, and coverage gates",
    mechanism: "Pytest + Ruff + mypy + frontend + audit + package checks",
    status: "Matrix green · commit 213f5a3",
  },
];

const lifecycle = [
  {
    phase: "Prepare",
    question: "Do we know what we are looking at?",
    gate: "Custody complete · parsers bounded · authority healthy",
  },
  {
    phase: "Plan",
    question: "Is the recommendation evidence-linked and reversible?",
    gate: "Alternatives recorded · blast radius modeled · unknowns visible",
  },
  {
    phase: "Design",
    question: "Are contracts, dependencies, and failure modes explicit?",
    gate: "SSOT impact reviewed · invariants mapped · artifacts aligned",
  },
  {
    phase: "Implement",
    question: "Can the change proceed without outrunning approval?",
    gate: "Pre-cert green · execution boundary authorized · rollback ready",
  },
  {
    phase: "Operate",
    question: "Did observed post-state satisfy the promised outcome?",
    gate: "Validation evidence bound · drift tracked · completion earned",
  },
  {
    phase: "Optimize",
    question: "What did the evidence teach the next cycle?",
    gate: "Trends derived from comparable snapshots · no hindsight rewrite",
  },
];

const commands = [
  {
    label: "Run the engine",
    command: "python COLLECT_PARSE_V3_23_0.py --help",
    note: "Start with the CLI contract; collection paths and output roots are explicit.",
  },
  {
    label: "Verify repository privacy",
    command: "python .github/scripts/verify_repository_privacy.py",
    note: "Runs the same stable-file and exact-exception policy used by CI.",
  },
  {
    label: "Run the Python contract suite",
    command: "python -m pytest -q",
    note: "Exercises core, pipeline, privacy, authority, release, and web backend behavior.",
  },
  {
    label: "Run Atlas frontend checks",
    command: "npm --prefix webapp/frontend test -- --run",
    note: "Verifies user-facing trust states, flows, and UI contracts.",
  },
  {
    label: "Build distribution artifacts",
    command: "python -m build",
    note: "The resulting wheel and sdist must then pass archive-level verification.",
  },
  {
    label: "Build this reference",
    command: "npm --prefix master-reference test",
    note: "Builds the static surface and checks its rendered semantic contract.",
  },
];

const glossary = [
  ["Authority", "Evidence that a source is entitled to make the claim—not merely that its bytes are intact."],
  ["Custody", "The recorded chain binding an input object, the bytes read, and the parser result."],
  ["Fail closed", "Stop or return unknown when a required proof is absent; never infer success from silence."],
  ["SSOT", "The canonical snapshot from which analysis, decisions, and deliverables are derived."],
  ["Pre-certification", "A readiness decision made before execution, with prerequisites and proof attached."],
  ["Provenance", "Where a fact or artifact came from and which transformations produced it."],
  ["Abstention", "An intentional unknown result when evidence is not strong or specific enough."],
  ["Immutable proof", "Verification tied to exact archive bytes and invalidated by any later byte change."],
];

function ArrowIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 12h13M14 7l5 5-5 5" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="m5 12 4 4L19 6" />
    </svg>
  );
}

export function MasterReference() {
  const [activeStage, setActiveStage] = useState(pipeline[0].id);
  const [persona, setPersona] = useState<Persona>("all");
  const [query, setQuery] = useState("");
  const [activeBoundary, setActiveBoundary] = useState(0);

  const selectedStage =
    pipeline.find((stage) => stage.id === activeStage) ?? pipeline[0];

  const filteredDecisions = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return decisions.filter((decision) => {
      const personaMatch =
        persona === "all" || decision.personas.includes(persona);
      if (!personaMatch) return false;
      if (!needle) return true;
      return [
        decision.title,
        decision.category,
        decision.outcome,
        decision.reason,
        decision.tags.join(" "),
      ]
        .join(" ")
        .toLowerCase()
        .includes(needle);
    });
  }, [persona, query]);

  return (
    <main>
      <header className="site-header">
        <a className="brand" href="#top" aria-label="Enhancements master reference">
          <span className="brand-mark" aria-hidden="true">
            E
          </span>
          <span>
            <strong>Enhancements</strong>
            <small>Master reference</small>
          </span>
        </a>
        <nav aria-label="Primary navigation">
          <a href="#system">System</a>
          <a href="#decisions">Decisions</a>
          <a href="#trust">Trust</a>
          <a href="#operate">Operate</a>
        </nav>
        <a className="header-status" href="#verification">
          <span className="status-dot" aria-hidden="true" />
          Evidence state
        </a>
      </header>

      <section className="hero" id="top">
        <div className="hero-grid" aria-hidden="true" />
        <div className="hero-copy">
          <p className="eyebrow">
            Repository decision system <span>·</span> 2 August 2026
          </p>
          <h1>
            From raw evidence
            <br />
            to <em>earned confidence.</em>
          </h1>
          <p className="hero-lede">
            A visual operating model for the entire repository: how evidence
            enters, how truth is constrained, why decisions were made, where
            trust stops, and what must pass before anything is called complete.
          </p>
          <div className="hero-actions">
            <a className="primary-action" href="#system">
              Explore the system <ArrowIcon />
            </a>
            <a className="secondary-action" href="#decisions">
              Read the decision ledger
            </a>
          </div>
          <div className="hero-principles" aria-label="Core principles">
            <span>
              <CheckIcon /> Unknown stays unknown
            </span>
            <span>
              <CheckIcon /> Proof is byte-bound
            </span>
            <span>
              <CheckIcon /> Authority is explicit
            </span>
          </div>
        </div>

        <div className="signal-panel" aria-label="Evidence flow summary">
          <div className="signal-header">
            <span>System signal</span>
            <span className="live-label">
              <i aria-hidden="true" /> verified state
            </span>
          </div>
          <div className="signal-orbit">
            <div className="orbit orbit-one" />
            <div className="orbit orbit-two" />
            <div className="orbit orbit-three" />
            <div className="signal-core">
              <strong>SSOT</strong>
              <span>canonical truth</span>
            </div>
            <span className="node node-a">capture</span>
            <span className="node node-b">authority</span>
            <span className="node node-c">decision</span>
            <span className="node node-d">artifact</span>
          </div>
          <div className="signal-metrics">
            <div>
              <span>Authority</span>
              <strong>3 domains</strong>
              <small>IEEE · IANA · Cisco</small>
            </div>
            <div>
              <span>Lifecycle</span>
              <strong>0 unresolved</strong>
              <small>claimed rows</small>
            </div>
            <div>
              <span>Release</span>
              <strong>Fail closed</strong>
              <small>archive is subject</small>
            </div>
          </div>
        </div>
      </section>

      <section className="principle-strip" aria-label="Operating doctrine">
        <p>The shortest version</p>
        <blockquote>
          Observe without invention. Enrich without pretending. Decide without
          self-approval. Deliver without losing the proof.
        </blockquote>
      </section>

      <section className="section system-section" id="system">
        <div className="section-heading">
          <div>
            <p className="eyebrow">01 · System map</p>
            <h2>One evidence spine, eight guarded transitions.</h2>
          </div>
          <p>
            Select a stage to see its input, enforcement point, output, and
            explicit failure behavior.
          </p>
        </div>

        <div className="pipeline" role="tablist" aria-label="Evidence pipeline">
          {pipeline.map((stage) => (
            <button
              key={stage.id}
              type="button"
              role="tab"
              aria-selected={stage.id === activeStage}
              aria-controls="stage-detail"
              className={stage.id === activeStage ? "active" : ""}
              onClick={() => setActiveStage(stage.id)}
            >
              <span>{stage.step}</span>
              <strong>{stage.title}</strong>
            </button>
          ))}
        </div>

        <article
          className="stage-detail"
          id="stage-detail"
          role="tabpanel"
          aria-live="polite"
        >
          <div className="stage-summary">
            <span className="stage-number">{selectedStage.step}</span>
            <div>
              <p className="micro-label">Selected transition</p>
              <h3>{selectedStage.title}</h3>
              <p>{selectedStage.summary}</p>
            </div>
          </div>
          <dl>
            <div>
              <dt>Input</dt>
              <dd>{selectedStage.input}</dd>
            </div>
            <div>
              <dt>Guardrail</dt>
              <dd>{selectedStage.guardrail}</dd>
            </div>
            <div>
              <dt>Output</dt>
              <dd>{selectedStage.output}</dd>
            </div>
            <div className="failure-cell">
              <dt>Failure behavior</dt>
              <dd>{selectedStage.failure}</dd>
            </div>
          </dl>
        </article>
      </section>

      <section className="section decisions-section" id="decisions">
        <div className="section-heading">
          <div>
            <p className="eyebrow">02 · Decision ledger</p>
            <h2>Every important choice carries its “why.”</h2>
          </div>
          <p>
            Filter by responsibility or search by concept. Open a decision for
            its reason, tradeoff, enforcement, and executable evidence.
          </p>
        </div>

        <div className="decision-controls">
          <div className="persona-filter" aria-label="Filter by role">
            {personaLabels.map((item) => (
              <button
                type="button"
                key={item.id}
                className={persona === item.id ? "active" : ""}
                aria-pressed={persona === item.id}
                onClick={() => setPersona(item.id)}
                title={item.hint}
              >
                {item.label}
              </button>
            ))}
          </div>
          <label className="decision-search">
            <span className="sr-only">Search decisions</span>
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="10.5" cy="10.5" r="6.5" />
              <path d="m15.5 15.5 5 5" />
            </svg>
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search trust, privacy, authority…"
            />
          </label>
        </div>

        <p className="result-count" aria-live="polite">
          Showing {filteredDecisions.length} of {decisions.length} decisions
        </p>

        <div className="decision-grid">
          {filteredDecisions.map((decision, index) => (
            <details className="decision-card" key={decision.id}>
              <summary>
                <span className="decision-index">
                  D{String(index + 1).padStart(2, "0")}
                </span>
                <span className="decision-category">{decision.category}</span>
                <h3>{decision.title}</h3>
                <p>{decision.outcome}</p>
                <span className="open-label">
                  <span className="when-closed">Inspect decision</span>
                  <span className="when-open">Close decision</span>
                  <ArrowIcon />
                </span>
              </summary>
              <div className="decision-body">
                <dl>
                  <div>
                    <dt>Why this decision</dt>
                    <dd>{decision.reason}</dd>
                  </div>
                  <div>
                    <dt>Accepted tradeoff</dt>
                    <dd>{decision.tradeoff}</dd>
                  </div>
                  <div>
                    <dt>How it is enforced</dt>
                    <dd>{decision.enforcement}</dd>
                  </div>
                  <div>
                    <dt>Evidence</dt>
                    <dd>
                      <code>{decision.evidence}</code>
                    </dd>
                  </div>
                </dl>
                <div className="tag-row">
                  {decision.tags.map((tag) => (
                    <span key={tag}>{tag}</span>
                  ))}
                </div>
              </div>
            </details>
          ))}
        </div>
        {filteredDecisions.length === 0 && (
          <div className="empty-state">
            <strong>No matching decision.</strong>
            <p>Try a broader term or return to the whole-system view.</p>
            <button
              type="button"
              onClick={() => {
                setQuery("");
                setPersona("all");
              }}
            >
              Clear filters
            </button>
          </div>
        )}
      </section>

      <section className="section authority-section" id="authority">
        <div className="section-heading">
          <div>
            <p className="eyebrow">03 · Data authority</p>
            <h2>“Loaded” is not the same as “authoritative.”</h2>
          </div>
          <p>
            Runtime enrichments expose both byte integrity and the provenance
            that earns authority.
          </p>
        </div>
        <div className="authority-grid">
          {authority.map((item, index) => (
            <article key={item.source}>
              <div className="authority-top">
                <span>0{index + 1}</span>
                <span className="authority-state">
                  <CheckIcon /> {item.state}
                </span>
              </div>
              <p className="micro-label">{item.scope}</p>
              <h3>{item.source}</h3>
              <strong>{item.material}</strong>
              <p>{item.decision}</p>
              <footer>{item.boundary}</footer>
            </article>
          ))}
        </div>
        <div className="authority-equation">
          <div>
            <span>Digest + schema</span>
            <strong>Integrity</strong>
          </div>
          <span className="equation-plus">+</span>
          <div>
            <span>Official origin + bounded claim</span>
            <strong>Authority</strong>
          </div>
          <span className="equation-equals">=</span>
          <div className="equation-result">
            <span>Usable enrichment</span>
            <strong>Verified claim</strong>
          </div>
        </div>
      </section>

      <section className="section trust-section" id="trust">
        <div className="section-heading light-heading">
          <div>
            <p className="eyebrow">04 · Trust boundaries</p>
            <h2>Confidence is earned at the edges.</h2>
          </div>
          <p>
            Each boundary names an adversary, a control, and a proof. Select a
            row to inspect its contract.
          </p>
        </div>

        <div className="boundary-layout">
          <div className="boundary-list" role="tablist" aria-label="Trust boundaries">
            {trustBoundaries.map((boundary, index) => (
              <button
                type="button"
                role="tab"
                aria-selected={activeBoundary === index}
                className={activeBoundary === index ? "active" : ""}
                key={boundary.edge}
                onClick={() => setActiveBoundary(index)}
              >
                <span>{String(index + 1).padStart(2, "0")}</span>
                <strong>{boundary.edge}</strong>
                <ArrowIcon />
              </button>
            ))}
          </div>
          <article className="boundary-detail" role="tabpanel" aria-live="polite">
            <p className="micro-label">Boundary {activeBoundary + 1}</p>
            <h3>{trustBoundaries[activeBoundary].edge}</h3>
            <dl>
              <div>
                <dt>Threat</dt>
                <dd>{trustBoundaries[activeBoundary].threat}</dd>
              </div>
              <div>
                <dt>Control</dt>
                <dd>{trustBoundaries[activeBoundary].control}</dd>
              </div>
              <div>
                <dt>Proof</dt>
                <dd>{trustBoundaries[activeBoundary].proof}</dd>
              </div>
            </dl>
          </article>
        </div>
      </section>

      <section className="section lifecycle-section" id="lifecycle">
        <div className="section-heading">
          <div>
            <p className="eyebrow">05 · Operating lifecycle</p>
            <h2>PPDIOO, expressed as evidence gates.</h2>
          </div>
          <p>
            The lifecycle is not a decorative sequence. Each phase asks a
            question that must be answered before confidence can advance.
          </p>
        </div>
        <div className="lifecycle-track">
          {lifecycle.map((item, index) => (
            <article key={item.phase}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <h3>{item.phase}</h3>
              <p>{item.question}</p>
              <footer>{item.gate}</footer>
            </article>
          ))}
        </div>
      </section>

      <section className="section repository-section" id="repository">
        <div className="section-heading">
          <div>
            <p className="eyebrow">06 · Repository atlas</p>
            <h2>Where each contract lives.</h2>
          </div>
          <p>
            The map is organized by responsibility, not file count. Every area
            has one dominant role and one non-negotiable contract.
          </p>
        </div>
        <div className="repo-grid">
          {repositoryAreas.map((area) => (
            <article key={area.path}>
              <code>{area.path}</code>
              <p>{area.role}</p>
              <footer>
                <span>Contract</span>
                {area.contract}
              </footer>
            </article>
          ))}
        </div>
      </section>

      <section className="section verification-section" id="verification">
        <div className="section-heading">
          <div>
            <p className="eyebrow">07 · Verification matrix</p>
            <h2>A green label must say what it proves.</h2>
          </div>
          <p>
            Focused evidence is retained, and the integrated matrix and
            archive-level proof have completed against the recorded source
            state.
          </p>
        </div>
        <table className="verification-table">
          <caption className="sr-only">Repository verification matrix</caption>
          <thead>
            <tr className="verification-row verification-head">
              <th scope="col">Layer</th>
              <th scope="col">Claim</th>
              <th scope="col">Mechanism</th>
              <th scope="col">State</th>
            </tr>
          </thead>
          <tbody>
            {verification.map((item) => (
              <tr className="verification-row" key={item.layer}>
                <th scope="row">{item.layer}</th>
                <td>{item.proves}</td>
                <td>{item.mechanism}</td>
                <td className="verification-state">
                  <i aria-hidden="true" /> {item.status}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="verification-note">
          <strong>Evidence rule:</strong> a focused pass proves only its named
          invariant. The final repository status is published here only after
          all integrated checks and archive-level proofs complete.
        </p>
      </section>

      <section className="section operate-section" id="operate">
        <div className="section-heading light-heading">
          <div>
            <p className="eyebrow">08 · Operator desk</p>
            <h2>Start from the contract, then run the tool.</h2>
          </div>
          <p>
            These entry points are intentionally boring: explicit commands,
            local execution, and no hidden service dependency.
          </p>
        </div>
        <div className="command-grid">
          {commands.map((item) => (
            <article key={item.label}>
              <p className="micro-label">{item.label}</p>
              <code>{item.command}</code>
              <p>{item.note}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="section glossary-section" id="glossary">
        <div className="section-heading">
          <div>
            <p className="eyebrow">09 · Shared language</p>
            <h2>Terms with operational meaning.</h2>
          </div>
          <p>
            These words are used as contracts throughout the codebase, tests,
            review records, and this reference.
          </p>
        </div>
        <dl className="glossary-grid">
          {glossary.map(([term, meaning]) => (
            <div key={term}>
              <dt>{term}</dt>
              <dd>{meaning}</dd>
            </div>
          ))}
        </dl>
      </section>

      <footer className="site-footer">
        <div>
          <span className="brand-mark" aria-hidden="true">
            E
          </span>
          <p>
            <strong>Enhancements master reference</strong>
            <span>A static view of the repository’s executable contracts.</span>
          </p>
        </div>
        <p>
          No analytics · no cookies · no runtime data intake · no alternate
          source of truth
        </p>
        <a href="#top">
          Back to top <span aria-hidden="true">↑</span>
        </a>
      </footer>
    </main>
  );
}
