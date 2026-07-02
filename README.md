# Cisco Migration-Assessment Toolkit

[![CI](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/actions/workflows/ci.yml)

A Python toolkit that connects to Cisco switches (IOS / IOS-XE / NX-OS), parses
their `show`-command output, and correlates the full **L1 → L4 + cross-layer +
routing-protocol + security/config** picture into decision-ready outputs for a
network migration. It answers the three questions an assessment must: **what's
the current state, where is the migration risk, and what do I fix first.**

Every run produces two self-contained, **offline / air-gapped** deliverables —
no live network needed to read them:

- a **multi-sheet Excel workbook** (30+ tabs) that opens on a one-page
  **Executive Summary**: fleet posture, the punch-list breakdown, the
  **keystone devices** the fleet most depends on (by migration blast radius),
  and per-move-group readiness;
- an interactive single-file **Network Migration Explorer** (the
  `blast_radius_explorer.html` viewer) with 13 analysis modes and a graphical
  **Risk cockpit** that distils thousands of findings into "fix these first."

The engine is **multi-vendor**: Cisco IOS / IOS-XE / NX-OS over SSH show-text plus
JSON controller-REST ingestion (Cisco ACI/APIC, Catalyst SD-WAN/vManage, ISE, FMC),
Arista EOS, Juniper SRX, Fortinet FortiGate, and AWS security-group exports — and it
carries a set of offline **proof engines** (ACL shadow-proofs, RIB→FIB path traces,
capture integrity, parse-yield telemetry, state assertions, chain-of-custody manifest)
whose verdicts are coverage-honest: absence of evidence is never reported as health.

Underneath sit a per-switch **health score (0–100)**, a per-move-group
**migration-readiness verdict** (`READY` / `CAUTION` / `NOT READY`), a
consolidated severity-ranked **migration punch-list**, and a blast-radius
**failure-impact** simulation — all derived offline from one collection.

> ℹ️ The topology embedded in the bundled `blast_radius_explorer.html` is
> **demo/sample data** (private `10.0.x.x` addresses, generic `CORE` / `DIST`
> labels) — not a real network capture.

## Repository contents

| File | What it is |
|------|------------|
| [`COLLECT_PARSE_V3_23_0.py`](COLLECT_PARSE_V3_23_0.py) | The toolkit — collects over SSH (netmiko), parses, scores health, computes migration readiness, and writes the workbook + explorer. |
| [`COLLECT_PARSE_V3_23_0.md`](COLLECT_PARSE_V3_23_0.md) | Documentation for the current version (health scoring, the 10-check readiness checklist, the HTML Health mode) plus the change log. |
| [`cisco_toolkit/blast_radius_explorer.html`](cisco_toolkit/blast_radius_explorer.html) | The interactive single-file explorer that renders a collected snapshot — topology graph plus 13 analysis modes (Blast radius, Path trace, Compare, Flow, **Health** w/ the Risk cockpit, Protocols, Cross-Layer, Causal Flow, Waves, Apps, Review, Design, Cable Map). The live snapshot is baked into a copy of this template on every run. (Lives inside the package so it ships in a wheel.) |
| [`compass_artifact_..._markdown1.md`](compass_artifact_wf-4178d659-b124-4412-9854-fc7bea5b9094_text_markdown1.md) | Design playbook — best-practice layout, color, and interaction redesign for the Explorer. |
| [`compass_artifact_..._markdown.md`](compass_artifact_wf-6d4cf577-c82e-4281-8744-55bdc473f75d_text_markdown.md) | Hardening playbook — parsing robustness, collection, scoring validation, and an accessible Explorer. |

## Requirements

- **Python 3.10+** (CI tests 3.10 → 3.14 on Linux and Windows)
- [`netmiko`](https://pypi.org/project/netmiko/) — SSH collection
- [`openpyxl`](https://pypi.org/project/openpyxl/) — Excel read/write
- [`python-docx`](https://pypi.org/project/python-docx/) — *optional*, enables the DOCX runbook
- Everything else is the standard library.

## Install

The quickest path is just the two runtime dependencies:

```bash
pip install netmiko openpyxl          # minimal runtime
```

Or install the project itself (editable, from a checkout) to get a stable
**`cisco-assess`** console command plus declared dependencies:

```bash
pip install -e .                      # runtime only
pip install -e ".[docx]"             # + the DOCX runbook
pip install -e ".[dev,docx]"         # + pytest / ruff / mypy for development
```

After installing, `cisco-assess …` is equivalent to `python COLLECT_PARSE_V3_23_0.py …`
(same entry point). Use an **editable** install (`-e`): the explorer-HTML template and the
offline KB data are read relative to the checkout.

## Inputs & outputs

**Inputs**
- A **devices file** (`--devices-file`, JSON) describing what to connect to (see below).
- A **template workbook** (`--template`, default `Migration_Assessment_Template_Updated.xlsx`)
  used as the starting point for the filled report. *Provide your own; it is not
  included in this repo.*

**Outputs** (written to the working directory)
- `Migration_Assessment_AUTOFILLED_<timestamp>.xlsx` — the filled workbook. It
  opens on the **Executive Summary** tab and then carries 30+ detail sheets
  (Switch Inventory, SVI/Gateway, VLAN & Endpoint census, Move Groups, Topology
  Links, Capacity, Interface/Physical Health, Security Posture, Config
  Compliance & Hygiene, STP & STP-Root, Routing Adjacencies, Cross-Layer
  Analysis, Causality Chains, Failure Impact, Health Scores, Migration
  Readiness, the Migration Punch-List, and more).
- `..._explorer.html` — the Network Migration Explorer beside the workbook
  (unless `--no-html`), with the snapshot embedded.
- `..._snapshot.json` — the data contract shared by the workbook and explorer
  (also re-loadable in the explorer and usable with `--compare`).
- `..._runbook.docx` — the Assessment & Migration **Runbook**, the narrative twin
  of the workbook (unless `--no-docx`; needs `python-docx`).
- `..._executive_deck.pptx` — the **Executive presentation deck**: a short,
  stakeholder-ready slide summary (posture, top risks, keystone devices,
  end-of-support exposure, the wave plan, where to start) generated from the same
  snapshot (unless `--no-pptx`; needs `python-pptx`).
- `..._design.docx` — the **As-Built Network Design Document** (HLD + LLD): the
  current design reconstructed from the snapshot (topology tiers, L2/L3 design,
  resilience, multicast/timing, segmentation, per-device build detail, BoM) plus
  target-state recommendations (unless `--no-design`; needs `python-docx`).
- `..._mop.docx` — the per-wave **Method of Procedure**: a maintenance-window
  cutover template per migration wave (scope, blockers, pre-cutover baseline,
  port mapping + staged config, the procedure with per-step success criteria,
  post-cutover validation and rollback) (unless `--no-mop`; needs `python-docx`).
- `..._crd.docx` — the **Customer Requirements Document**: the Plan-phase
  requirements-capture instrument, primed with the assessment evidence
  (current-environment summary, evidence-gated technical-requirement sections,
  REQ-ID capture tables and the traceability skeleton into design and acceptance)
  (unless `--no-crd`; needs `python-docx`).
- `..._engagement.docx` — the **Engagement Workflow & Plan of Record**: the
  engagement-management layer over the whole document set — an evidence-led
  verdict (proceed / proceed-with-conditions / hold), a phase tracker with
  entry/exit gates, the ordered next-action queue, a per-wave T-minus gate
  calendar (commit → checkpoint → go/no-go → window → hypercare exit), and a
  RAID log seeded from the assessment's own findings (unless
  `--no-engagement`; needs `python-docx`).
- `..._archreview.docx` — the **Architecture Review & Conformance Report**: the
  automated senior-engineer design review — ~24 leading-practice checks across
  8 design domains (hierarchy, resiliency, L2, L3/gateway, capacity &
  oversubscription, operational readiness, security & segmentation, lifecycle
  & software), each with a verdict / evidence / why-it-matters / remediation /
  cited rule, rolled up into a conformance grade, a domain scorecard and a
  priority remediation queue; checks whose evidence was not captured are
  declared not-assessable rather than silently skipped (unless
  `--no-archreview`; needs `python-docx`).
- `..._ops_handbook.docx` — the **Operations Handbook**: the PPDIOO
  Operate-phase deliverable — the Day-2 handbook whose baselines are this
  fleet's own assessed evidence: the alert list is what the syslog analysis
  actually saw fire, the capacity baseline is each device's own measured
  normal, plus drift control, software/PSIRT governance cadence, a routine
  operations calendar and a TAC-readiness evidence pack; sections whose
  evidence was not collected are declared, never invented (unless
  `--no-opshandbook`; needs `python-docx`).

## Usage

```bash
# Collect from devices, then build the workbook and explorer
python COLLECT_PARSE_V3_23_0.py \
    --devices-file devices.json \
    --template Migration_Assessment_Template_Updated.xlsx

# Diff two previously saved snapshots into a change workbook (no SSH, no template)
python COLLECT_PARSE_V3_23_0.py --compare old_snapshot.json new_snapshot.json

# Trend a SERIES of snapshots across the migration into a campaign workbook (oldest first)
python COLLECT_PARSE_V3_23_0.py --trend wave0.snapshot.json wave1.snapshot.json wave2.snapshot.json

# See every option
python COLLECT_PARSE_V3_23_0.py --help
```

Useful flags: `--workers N` (parallel SSH workers, default 5; `1` = sequential),
`--no-html` / `--no-docx` / `--no-pptx` / `--no-design` / `--no-mop` / `--no-crd` /
`--no-engagement`
(skip the explorer / runbook / deck / design doc / MOP / CRD / engagement plan),
`--output FILE` (override the workbook name), `--golden-config FILE` (a config
baseline for the **Golden-Config Drift** sheet — omit to auto-derive it from the
fleet majority), `--flow-src IP` / `--flow-dst IP` (add an optional flow-trace
sheet between two endpoints), and `--redact` (pseudonymize IPs / MACs / serials across the
**whole output bundle** — the snapshot JSON, the HTML explorer, **and** the always-produced
`.xlsx` workbook — consistent and subnet-preserving, hostnames kept — so every deliverable can
be shared without leaking real addressing). See
[`COLLECT_PARSE_V3_23_0.md`](COLLECT_PARSE_V3_23_0.md) for the full feature set.

### Devices file

A JSON file — accepted as an array, a single object, or one object per line.
Each entry needs `ip`, `hostname`, and `username` (common aliases like `host`,
`name`, and `user` are accepted). `platform` is optional and autodetected when
omitted (`ios` / `nxos` / `auto`). Start from
[`devices.example.json`](devices.example.json) — it shows the recommended,
password-free shape.

```json
[
  { "hostname": "core-1", "ip": "10.0.0.1", "username": "netadmin", "platform": "ios" },
  { "hostname": "dist-1", "ip": "10.0.0.2", "username": "netadmin", "password_env": "DIST1_PASS", "platform": "nxos" }
]
```

**Keep passwords OUT of the file — the environment chain is the default.**
Passwords resolve in this order:

1. `"password_env": "VAR"` on the entry — read from that environment variable,
2. the global `$CISCO_PASS` environment variable (one read-only account fleet-wide),
3. a secure `getpass` prompt (interactive terminals only),
4. an explicit `"password"` on the entry — supported for back-compat, **discouraged**:
   `devices.json` then holds live credentials in cleartext on disk.

Authentication failures are **never** retried (this avoids account lockout);
transient connection/timeout failures are retried with backoff.

### Secrets at rest — the raw collection directory

The collection directory holds the devices' **verbatim output**, running-configs
included — passwords, SNMP communities, and keys in **cleartext**. `--redact` makes the
*deliverables* share-safe but deliberately never touches this evidence dir (it is the
`--compare` / `--trend` source), and every run now prints a `[SENSITIVE]` warning naming
it. Once analysis is final, scrub the raw captures in place with **`--redact-collection`**:
it replaces secret *values* with the same conservative deny-list `--redact` uses, keeps
IPs/hostnames/interfaces so the dir stays analyzable, is idempotent, and never deletes
anything. (Scrubbed captures will no longer match any archive hashes recorded at
collection time — that modification is the point, and it is opt-in.)

## Reading the results

**Excel — start on the Executive Summary.** The first tab is a one-page synthesis:
fleet posture (health-band distribution), the migration punch-list breakdown, the
**keystone devices** ranked by blast radius (the few switches the fleet most
depends on — the prioritisation that still works when every per-switch score
saturates to Critical), per-group readiness, and a plain-English *"where to
start."* Each section points to a detail tab for the underlying evidence.

**Then the Device Risk Register.** The per-**asset** synthesis: the eleven
per-device axes (health, hardware EoL, software risk, control-plane capacity,
operational logs, CIS posture, config hygiene, golden drift, QoS, physical,
protocol) stacked per box and ranked by **risk index = topology impact ×
exposure**, with named **compound patterns** (CR-01..CR-06) where independent
risks coincide on one asset — an end-of-support keystone, a root bridge on
degraded hardware, an open advisory surface on a box whose removal partitions
the network — and a one-sentence engineer's verdict each. An axis without
evidence reads *not assessed*, never healthy-by-silence. The top row is the
scariest box in the fleet; the compound patterns also fold into the punch-list.

**Explorer — eleven modes over one topology.** Pan/zoom the graph; search by
switch / IP / MAC; filter by VLAN. The modes:

- **Blast radius** — click a switch to simulate its removal and see what it strands.
- **Path trace** — the L2/L3 path between two switches, with the bridges / articulation points on it.
- **Compare** — diff two snapshots (pre/post-cutover): what regressed, what improved.
- **Flow** — an L1→L3 flow trace between two endpoints, with ACL / NAT / MTU / VRF awareness.
- **Health** — the **Risk cockpit**: a risk-by-tier matrix, the keystone devices, the
  **Asset risk register** (the fleet ranked by per-asset compound risk, with CR-pattern
  chips and inline engineer's verdicts) and a punch-list triage up top, then per-switch
  health, the root-cause SPOF list, and a what-if remediation simulator. Selecting any
  switch in any mode opens its dossier, led by the engine's **Engineer's verdict** card.
- **Protocols** — routing-protocol topology, redistribution boundaries, adjacency health.
- **Cross-Layer** — findings that compound across layers into one real migration risk.
- **Causality** — each structural SPOF as a trigger → mechanism → impact → mitigation chain.
- **Waves** — the migration move-groups in recommended cutover order, each with its readiness
  verdict, scenario (make-before-break vs hard cutover) and post-cutover validation checks.
- **Apps** — application domains (workloads) with footprint, criticality tier and inter-domain
  coupling — the unit the business actually migrates.
- **Review** — the senior-engineer architecture review: leading-practice checks across eight
  design domains with an A–F conformance grade and not-assessable honesty.

The explorer is a single self-contained file (no server, no external assets) and
runs fully offline — safe to email or open from a USB stick.

## AssessHub — the web platform

[`webapp/`](webapp/README.md) layers a served, full-stack platform over the engine — **purely
additive** (the engine and its golden test contract are untouched). Where the CLI produces one
assessment, AssessHub manages the whole migration *campaign*:

- **Campaigns & waves** — snapshots stored in SQLite, tracked over time with trajectory verdicts
  and pairwise compare; the **risk cockpit**, the **Device Risk Register** (per-asset compound
  risk, ranked, with compound-pattern chips), a native **force-directed fleet topology**, 20+
  detail sections (including the syslog / QoS / software-risk / platform-health axes), and the
  deep explorer embedded per snapshot.
- **Two ways in** — upload a finished `*.snapshot.json`, or upload a **ZIP of raw show-command
  outputs** and the real engine pipeline runs server-side.
- **Gated cutover planner** — per-wave Go / Conditional-Go / No-Go gates, pilot-first sequencing,
  maintenance-window estimates, and a PPDIOO run-of-show per wave.
- **Execution console (war room)** — run the change window live: timestamped step check-off,
  validation PASS/FAIL against captured baselines, wave closeouts, a deviation scribe log, and a
  derived change-management outcome.
- **Deliverables on demand** — Engagement Workflow & Plan of Record / CRD / Runbook / Design
  Document / Architecture Review & Conformance Report / MOP / Executive Deck via the engine's own
  writers, plus the Cutover Plan, the NRFU/Acceptance Test Plan, and the **Post-Implementation
  Review / as-executed record** for any execution run.
- **Gate board** — per-wave T-minus sign-offs (commit → checkpoint → readiness → go/no-go →
  window → hypercare exit) recorded on the campaign page; decisions feed back into the
  Engagement Workflow & Plan of Record's "Gate record (as signed)" section.
- **Ask the engineer** — the senior-engineer architecture review on every snapshot page:
  A–F conformance grade, deterministic question chips (*where do we start · what blocks the
  migration · how resilient is the fabric · judge every domain · what couldn't you assess*),
  and per-domain drill-down — rendering the same verdict object as the DOCX report, the
  workbook scorecard sheet and the explorer ☑ Review mode. Older snapshots get the review
  computed server-side by the same engine function.

```bash
pip install -r webapp/requirements.txt
cd webapp/frontend && npm install && npm run build && cd ../..
python -m uvicorn backend.app:app --app-dir webapp --port 8000   # http://127.0.0.1:8000
```

Open the page and click **"Open a sample fleet"** — a bundled 23-device demo, no network needed.
Full docs in [`webapp/README.md`](webapp/README.md).

## Health score & migration readiness

The score starts at 100 with weighted, **per-category-capped** deductions across
L1, L3, cross-layer, and protocol findings, banded **Excellent / Good / Fair /
Poor / Critical**. Migration readiness runs a 10-check pre-migration checklist
per move group: any hard-fail check → `NOT READY`, otherwise any warn →
`CAUTION`, otherwise `READY`. Both the weights and band thresholds are a
defensible default, not calibrated against a labelled dataset — tune to taste.
Full details are in [`COLLECT_PARSE_V3_23_0.md`](COLLECT_PARSE_V3_23_0.md).
